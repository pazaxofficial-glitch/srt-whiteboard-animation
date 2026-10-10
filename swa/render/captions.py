"""Burned-in captions and subtitle files (SRT / VTT).

Words come with their spoken times, so captions can highlight the word being
said (karaoke style) and show short "pop" chunks like Shorts and Reels.
Rendering goes through the same HarfBuzz text engine as the handwriting, so
Persian captions join and order correctly.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .text import FontPair, fit_text, render_layout

STYLES = ("off", "clean", "box", "highlight", "pop")
_BREAK_AFTER = (".", ",", "!", "?", ";", ":", "،", "؛", "؟")  # incl. Persian comma/semicolon/question


@dataclass
class Chunk:
    start: float
    end: float
    words: list[str]
    times: list[tuple[float, float]]
    line_id: int

    @property
    def text(self) -> str:
        return " ".join(self.words)


def build_chunks(timeline: dict, pop: bool = False, max_words: int = 7, max_chars: int = 40) -> list[Chunk]:
    """Split every script line into short caption chunks that never cross lines."""
    if pop:
        max_words, max_chars = 3, 16
    chunks: list[Chunk] = []
    for ln in sorted(timeline.get("lines", []), key=lambda x: x["start"]):
        words = ln.get("words", [])
        cur: list[dict] = []
        for i, w in enumerate(words):
            cur.append(w)
            chars = sum(len(x["w"]) + 1 for x in cur)
            nxt = words[i + 1] if i + 1 < len(words) else None
            breaks = (len(cur) >= max_words or (nxt is not None and chars + len(nxt["w"]) > max_chars)
                      or (w["w"].endswith(_BREAK_AFTER) and len(cur) >= (1 if pop else 3)))
            if nxt is None or breaks:
                chunks.append(Chunk(cur[0]["s"], cur[-1]["e"] + 0.3, [x["w"] for x in cur],
                                    [(x["s"], x["e"]) for x in cur], int(ln["id"])))
                cur = []
    # No overlaps, and no flicker in short gaps.
    for a, b in zip(chunks, chunks[1:]):
        if b.start - a.end < 0.45:
            a.end = b.start
        a.end = min(a.end, b.start)
    return chunks


def _ts(t: float, sep: str) -> str:
    t = max(0.0, t)
    h, rem = divmod(int(round(t * 1000)), 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def write_srt(chunks: list[Chunk], path: Path, offset: float = 0.0) -> Path:
    rows = []
    for i, c in enumerate(chunks, start=1):
        rows.append(f"{i}\n{_ts(c.start - offset, ',')} --> {_ts(c.end - offset, ',')}\n{c.text}\n")
    path.write_text("\n".join(rows), encoding="utf-8")
    return path


def write_vtt(chunks: list[Chunk], path: Path, offset: float = 0.0) -> Path:
    rows = ["WEBVTT\n"]
    for c in chunks:
        rows.append(f"{_ts(c.start - offset, '.')} --> {_ts(c.end - offset, '.')}\n{c.text}\n")
    path.write_text("\n".join(rows), encoding="utf-8")
    return path


def _hex_bgr(value: str, default=(59, 212, 255)) -> tuple[int, int, int]:
    v = (value or "").lstrip("#")
    if len(v) != 6:
        return default
    try:
        return (int(v[4:6], 16), int(v[2:4], 16), int(v[0:2], 16))
    except ValueError:
        return default


class CaptionRenderer:
    """Draws the caption for time t onto a frame."""

    def __init__(self, timeline: dict, frame_w: int, frame_h: int, settings: dict):
        self.style = settings.get("captions", "off")
        self.W, self.H = frame_w, frame_h
        self.position = settings.get("caption_position", "bottom")
        pop = self.style == "pop"
        self.chunks = build_chunks(timeline, pop=pop)
        self.starts = [c.start for c in self.chunks]
        base = min(frame_w, frame_h)
        self.size = base * (0.08 if pop else 0.054) * float(settings.get("caption_size", 1.0))
        self.lines = 1 if pop else 2
        self.margin = int(base * 0.035)
        self.band_h = int(self.size * 1.3 * self.lines + self.size * 0.6) + self.margin
        self.fonts = FontPair.get("caption", "caption")
        self.highlight = _hex_bgr(settings.get("caption_color", "#FFD43B"))
        self._cache: dict[tuple[int, int], tuple[np.ndarray, np.ndarray, int, int]] = {}

    @property
    def enabled(self) -> bool:
        return self.style in STYLES and self.style != "off" and bool(self.chunks)

    def band(self) -> tuple[int, int]:
        """Frame rows the captions occupy (kept free of drawings)."""
        if self.position == "top":
            return 0, self.band_h
        return self.H - self.band_h, self.H

    def chunk_at(self, t: float) -> tuple[int, int] | None:
        i = bisect.bisect_right(self.starts, t) - 1
        if i < 0 or t >= self.chunks[i].end:
            return None
        c = self.chunks[i]
        active = max(0, bisect.bisect_right([s for s, _e in c.times], t) - 1)
        return i, active

    def _render(self, i: int, active: int) -> tuple[np.ndarray, np.ndarray, int, int]:
        key = (i, active if self.style in ("highlight", "pop") else -1)
        if key in self._cache:
            return self._cache[key]
        c = self.chunks[i]
        max_w = self.W * 0.86
        lay = fit_text(c.words, self.fonts, max_w, self.size * 1.3 * self.lines, self.size,
                       min_size=self.size * 0.55, line_height=1.18, max_lines=self.lines)
        size = lay.words[0].size if lay.words else self.size
        pad = int(size * 0.45)
        alpha, parts = render_layout(lay, ss=2, pad=pad)
        h, w = alpha.shape
        color = np.empty((h, w, 3), np.float32)
        color[:] = (255, 255, 255)
        if self.style in ("highlight", "pop"):
            for index, a, x, y in parts:
                if index == active:
                    sub = color[max(0, y):y + a.shape[0], max(0, x):x + a.shape[1]]
                    aa = a[:sub.shape[0], :sub.shape[1], None]
                    sub[:] = sub * (1 - aa) + np.array(self.highlight, np.float32) * aa
        out_rgb = np.zeros((h, w, 3), np.float32)
        out_a = np.zeros((h, w), np.float32)

        def over(rgb, a):
            nonlocal out_rgb, out_a
            out_rgb = out_rgb * (1 - a[..., None]) + np.asarray(rgb, np.float32) * a[..., None]
            out_a = out_a + a * (1 - out_a)

        if self.style == "box":
            ys, xs = np.nonzero(alpha > 0.05)
            if len(xs):
                px, py = int(size * 0.35), int(size * 0.18)
                box = np.zeros((h, w), np.uint8)
                x0, y0 = max(0, xs.min() - px), max(0, ys.min() - py)
                x1, y1 = min(w - 1, xs.max() + px), min(h - 1, ys.max() + py)
                r = int(size * 0.28)
                cv2.rectangle(box, (x0 + r, y0), (x1 - r, y1), 255, -1)
                cv2.rectangle(box, (x0, y0 + r), (x1, y1 - r), 255, -1)
                for cx, cy in ((x0 + r, y0 + r), (x1 - r, y0 + r), (x0 + r, y1 - r), (x1 - r, y1 - r)):
                    cv2.circle(box, (cx, cy), r, 255, -1, cv2.LINE_AA)
                over((20, 16, 24), box.astype(np.float32) / 255 * 0.62)
        else:
            k = max(3, int(size * 0.13) | 1)
            outline = cv2.dilate(alpha, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
            shadow = cv2.GaussianBlur(outline, (0, 0), max(1.0, size * 0.07))
            sx, sy = int(size * 0.03), int(size * 0.06)
            shifted = np.zeros_like(shadow)
            if sy < h and sx < w:
                shifted[sy:, sx:] = shadow[:h - sy, :w - sx]
            over((0, 0, 0), shifted * 0.45)
            over((18, 14, 20), outline)
        over(color, alpha)
        cx = (self.W - w) // 2
        y0b, y1b = self.band()
        cy = y0b + (y1b - y0b - h) // 2 + (self.margin // 2 if self.position == "top" else -self.margin // 2)
        res = (out_rgb, out_a, cx, cy)
        if len(self._cache) > 64:
            self._cache.clear()
        self._cache[key] = res
        return res

    def draw(self, frame: np.ndarray, t: float) -> None:
        if not self.enabled:
            return
        hit = self.chunk_at(t)
        if hit is None:
            return
        rgb, a, x, y = self._render(*hit)
        h, w = a.shape
        fx0, fy0 = max(0, x), max(0, y)
        fx1, fy1 = min(self.W, x + w), min(self.H, y + h)
        if fx0 >= fx1 or fy0 >= fy1:
            return
        sa = a[fy0 - y:fy1 - y, fx0 - x:fx1 - x, None]
        region = frame[fy0:fy1, fx0:fx1].astype(np.float32)
        region += (rgb[fy0 - y:fy1 - y, fx0 - x:fx1 - x] - region) * sa
        frame[fy0:fy1, fx0:fx1] = region.astype(np.uint8)
