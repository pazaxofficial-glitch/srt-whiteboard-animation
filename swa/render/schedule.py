"""Timing inside every shot (no pixels here, so it is easy to test).

A shot is one board: a script line drawn as a picture ("image") or, for a
line without a picture, written out as text ("text").

    trans_start ── start ──────────────────────── draw_end ──── next shot
       board        the hand draws the picture and writes the marked words
       changes      exactly when they are spoken

One hand does everything, so while it writes a word the picture pauses:
those moments (plus the time to move between picture and text) are the
shot's `busy` intervals.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

PER_CHAR = 0.085      # seconds per written character at write_speed 1.0
WORD_BASE = 0.12      # extra seconds per written word (pen lift, spacing)
TRAVEL = 0.2          # seconds to move the hand between picture and text
GAP = 0.04            # pause between two written words


@dataclass
class WriteWindow:
    word: int          # index in the line's word list
    t0: float
    t1: float


@dataclass
class Shot:
    line_id: int
    image: Path | None
    trans_start: float
    start: float                      # first word of the line is spoken
    image_end: float                  # picture finished
    draw_end: float                   # everything on this board finished
    words: list[dict] = field(default_factory=list)       # timeline words {w, s, e}
    kind: str = "image"                                   # "image" | "text"
    write_words: list[int] = field(default_factory=list)  # word indices to handwrite
    writes: list[WriteWindow] = field(default_factory=list)
    busy: list[tuple[float, float]] = field(default_factory=list)

    @property
    def text_words(self) -> list[str]:
        return [w["w"] for w in self.words]


def _letters(word: str) -> int:
    return max(1, sum(1 for ch in word if ch.isalnum()))


def word_duration(word: str, speed: float = 1.0) -> float:
    return float(np.clip((WORD_BASE + _letters(word) * PER_CHAR) / max(0.2, speed), 0.22, 1.8))


def _sequence(indices: list[int], words: list[dict], floor: float, speed: float) -> list[WriteWindow]:
    """Write words one after another, each starting when it is spoken (or when the
    previous one is finished, whichever is later)."""
    out = []
    t_prev = floor
    for i in indices:
        s = float(words[i]["s"]) if i < len(words) else t_prev
        t0 = max(s, t_prev + (GAP if out else 0.0))
        t1 = t0 + word_duration(words[i]["w"] if i < len(words) else "", speed)
        out.append(WriteWindow(i, t0, t1))
        t_prev = t1
    return out


def _squeeze(windows: list[WriteWindow], hi: float) -> None:
    """Make windows finish by `hi` (keeps their order; writing just gets faster)."""
    if not windows or windows[-1].t1 <= hi:
        return
    a = windows[0].t0
    a2 = min(a, hi - 0.18 * len(windows))
    span, new_span = windows[-1].t1 - a, max(0.05, hi - a2)
    for w in windows:
        w.t0 = a2 + (w.t0 - a) * new_span / span
        w.t1 = a2 + (w.t1 - a) * new_span / span


def _busy(writes: list[WriteWindow], start: float) -> list[tuple[float, float]]:
    """Intervals when the hand is away from the picture: moving to the text,
    writing, and moving back. Close groups of words share one interval."""
    out: list[list[float]] = []
    for w in writes:
        a, b = max(start, w.t0 - TRAVEL), w.t1 + TRAVEL
        if out and a <= out[-1][1] + 0.3:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _overlap(intervals: list[tuple[float, float]], a: float, b: float) -> float:
    return sum(max(0.0, min(b, y) - max(a, x)) for x, y in intervals)


def plan_shots(timeline: dict, images: dict[int, Path], settings: dict, end_time: float,
               marks: dict[int, list[int]] | None = None) -> list[Shot]:
    """Shots for every line that has a picture (or is written as text).

    marks: line id -> indices of words to handwrite when spoken (from *word* in the script).
    """
    lines = sorted(timeline["lines"], key=lambda ln: ln["start"])
    fill = float(settings.get("draw_fill", 0.8))
    min_draw = float(settings.get("min_draw", 0.8))
    max_draw = float(settings.get("max_draw", 14.0))
    speed = float(settings.get("write_speed", 1.0))
    handwriting = bool(settings.get("handwriting", True))
    text_lines = settings.get("text_lines", "write")
    trans = float(settings.get("transition_duration", 0.6)) if settings.get("transition", "slide") != "cut" else 0.0
    marks = marks or {}

    shots: list[Shot] = []
    for i, ln in enumerate(lines):
        lid = int(ln["id"])
        words = ln.get("words", [])
        img = images.get(lid)
        if img is None and not (text_lines == "write" and words):
            continue
        start = float(ln["start"])
        nxt = float(lines[i + 1]["start"]) if i + 1 < len(lines) else end_time
        avail = max(0.05, nxt - start)
        limit = start + max(0.25, avail - trans - 0.05) if i + 1 < len(lines) else nxt

        if img is None:
            # Text card: write every word as it is spoken.
            idx = list(range(len(words)))
            writes = _sequence(idx, words, start, speed)
            _squeeze(writes, limit)
            end = writes[-1].t1 if writes else start + 0.25
            shots.append(Shot(lid, None, start, start, start, end, words, "text", idx, writes, []))
            continue

        draw = min(max(avail * fill, min_draw), max_draw)
        draw = min(draw, max(avail - trans - 0.05, avail * 0.85))
        draw = max(0.25, min(draw, avail))
        image_end = start + draw

        idx = sorted({k for k in (marks.get(lid, []) if handwriting else []) if 0 <= k < len(words)})
        writes = _sequence(idx, words, start, speed)
        busy = _busy(writes, start)
        if busy and busy[-1][1] > limit:
            _squeeze(writes, limit - TRAVEL)
            busy = _busy(writes, start)

        # Give the picture back the time the hand spends writing.
        lost = _overlap(busy, start, image_end)
        if lost > 0:
            image_end = min(max(limit, image_end), image_end + lost)
        draw_end = max(image_end, busy[-1][1] if busy else image_end)
        shots.append(Shot(lid, img, start, start, image_end, draw_end, words, "image", idx, writes, busy))

    for k, shot in enumerate(shots):
        if k == 0:
            shot.trans_start = shot.start
            continue
        room = max(0.0, shot.start - shots[k - 1].draw_end)
        shot.trans_start = shot.start - min(trans, room)
    return shots


def progress_curve(shot: Shot, fps: int, mode: str) -> np.ndarray:
    """Picture progress (0..1) for each frame from shot.start to shot.image_end.

    With mode "speech" the pen moves faster while words are spoken; it stops
    while the hand is busy writing.
    """
    n = max(2, int(math.ceil((shot.image_end - shot.start) * fps)) + 1)
    t = shot.start + np.arange(n) / fps
    if mode == "speech" and shot.words:
        w = np.full(n, 0.3, dtype=np.float64)
        for wd in shot.words:
            w[(t >= wd["s"]) & (t < wd["e"] + 0.05)] = 1.0
        k = max(1, int(0.15 * fps))
        w = np.convolve(w, np.ones(k) / k, mode="same")
    else:
        w = np.ones(n, dtype=np.float64)
    ramp = max(1, min(int(0.12 * fps), n // 2))
    env = np.ones(n)
    env[:ramp] = np.linspace(0.35, 1, ramp)
    env[-ramp:] = np.minimum(env[-ramp:], np.linspace(1, 0.35, ramp))
    w = w * env
    free = w.copy()
    for a, b in shot.busy:
        free[(t >= a) & (t < b)] = 0.0
    if free.sum() > 1e-6:
        w = free
    c = np.concatenate([[0.0], np.cumsum(w[:-1])])
    return c / c[-1] if c[-1] > 0 else np.linspace(0, 1, n)


def write_progress(window: WriteWindow, t: float) -> float:
    """0..1 through one written word (smooth start and finish)."""
    if t <= window.t0:
        return 0.0
    if t >= window.t1:
        return 1.0
    q = (t - window.t0) / max(1e-6, window.t1 - window.t0)
    return 0.5 * q + 0.5 * (q * q * (3 - 2 * q))
