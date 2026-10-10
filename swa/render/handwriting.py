"""Handwritten text on the board: words become pen strokes, one word at a time.

Each word is rendered with a handwriting font, skeletonized into strokes and
ordered the way a person writes: letter by letter in reading direction
(right to left for Persian), with dots and small marks added right after
the letter they belong to.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .drawing import chalk_texture
from .strokes import Stroke, order_strokes, strokes_from_mask
from .text import FontPair, fit_text, render_layout

INK_COLORS = {
    "auto": None,
    "black": (40, 34, 30),
    "blue": (160, 80, 30),
    "red": (50, 50, 200),
    "green": (70, 130, 40),
    "purple": (170, 60, 120),
}
CHALK_COLORS = {
    "auto": (238, 242, 244),
    "black": (238, 242, 244),
    "blue": (245, 215, 160),
    "red": (180, 175, 250),
    "green": (180, 235, 190),
    "purple": (240, 190, 230),
}


def ink_color(name: str, dark: bool) -> tuple[int, int, int]:
    """BGR colour for written text on a light or dark board."""
    if dark:
        return CHALK_COLORS.get(name, CHALK_COLORS["auto"])
    if name.startswith("#") and len(name) == 7:
        r, g, b = int(name[1:3], 16), int(name[3:5], 16), int(name[5:7], 16)
        return (b, g, r)
    return INK_COLORS.get(name) or INK_COLORS["black"]


@dataclass
class WrittenWord:
    index: int                     # word index inside the written phrase
    strokes: list[Stroke]          # frame coordinates


@dataclass
class PreparedText:
    rect: tuple[int, int, int, int]                # x0, y0, x1, y1 (frame px)
    rgb: np.ndarray                                # (h, w, 3) float32
    alpha: np.ndarray                              # (h, w) float32
    words: list[WrittenWord] = field(default_factory=list)
    size: float = 0.0

    @property
    def strokes(self) -> list[Stroke]:
        return [s for w in self.words for s in w.strokes]


def _letter_order(ink: np.ndarray, rtl: bool) -> tuple[np.ndarray, list[int]]:
    """Connected parts of a word in writing order; dots follow their letter."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    if n <= 1:
        return labels, []
    areas = stats[1:, cv2.CC_STAT_AREA]
    big_area = float(areas.max())
    h = ink.shape[0]
    bodies, marks = [], []
    for g in range(1, n):
        x, y, w, hh, a = (int(v) for v in stats[g])
        if a < 0.16 * big_area and hh < 0.42 * h:
            marks.append(g)
        else:
            bodies.append(g)
    if not bodies:
        bodies, marks = marks, []

    def key(g):
        x, _y, w, _h, _a = stats[g]
        return -(x + w) if rtl else x

    bodies.sort(key=key)
    attached: dict[int, list[int]] = {b: [] for b in bodies}
    for m in marks:
        mx = stats[m, 0] + stats[m, 2] / 2

        def gap(b):
            # Horizontal distance from the mark to the letter (0 when above/below it).
            x0, x1 = stats[b, 0], stats[b, 0] + stats[b, 2]
            return (max(0.0, x0 - mx, mx - x1), abs((x0 + x1) / 2 - mx))

        attached[min(bodies, key=gap)].append(m)
    order: list[int] = []
    for b in bodies:
        order.append(b)
        order.extend(sorted(attached[b], key=key))
    return labels, order


def word_strokes(alpha: np.ndarray, rtl: bool) -> list[Stroke]:
    """Pen strokes for one rendered word (patch coordinates)."""
    ink = alpha > 0.45
    if not ink.any():
        return []
    labels, order = _letter_order(ink, rtl)
    strokes = strokes_from_mask(ink, labels)
    h, w = ink.shape
    start = (float(w), h * 0.4) if rtl else (0.0, h * 0.4)
    return order_strokes(strokes, order, start, prefer_long=False)


def prepare_text(words: list[str], fonts: FontPair, box: tuple[int, int, int, int], color: str,
                 dark: bool, max_size: float, align: str = "center", max_lines: int | None = None,
                 line_height: float = 1.2) -> PreparedText:
    """Lay out and prepare `words` to be handwritten inside `box` (frame px)."""
    bx0, by0, bx1, by1 = box
    bw, bh = max(8, bx1 - bx0), max(8, by1 - by0)
    lay = fit_text(words, fonts, bw, bh, max_size, min_size=10, line_height=line_height, align=align,
                   max_lines=max_lines)
    pad = 6
    full, parts = render_layout(lay, ss=3, pad=pad)
    h, w = full.shape
    # Centre the text block in the box.
    ox = bx0 + (bw - (w - 2 * pad)) // 2 - pad
    oy = by0 + (bh - (h - 2 * pad)) // 2 - pad
    bgr = ink_color(color, dark)
    rgb = np.empty((h, w, 3), np.float32)
    rgb[:] = bgr
    alpha = full
    if dark:
        alpha = chalk_texture(alpha, seed=w * 7 + h)
    written: list[WrittenWord] = []
    for index, a, x, y in parts:
        rtl = any(pw.index == index and pw.rtl for pw in lay.words)
        strokes = word_strokes(a, rtl)
        for s in strokes:
            s.points = s.points + np.array([ox + x, oy + y], dtype=np.float32)
        written.append(WrittenWord(index, strokes))
    written.sort(key=lambda ww: ww.index)
    return PreparedText((ox, oy, ox + w, oy + h), rgb, alpha.astype(np.float32), written, lay.words[0].size if lay.words else 0)
