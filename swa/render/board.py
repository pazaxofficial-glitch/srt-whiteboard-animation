"""The board: a background plus layers that the pen reveals stroke by stroke.

A Layer is a picture (colour + alpha) placed on the board with a reveal mask
that starts empty. A PenPlan is the pen's route (pen-down strokes and pen-up
moves) measured in "effort" units; a Reveal walks a PenPlan and stamps the
masks of its target layers, so the picture appears exactly where the pen
has been.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np


class Layer:
    def __init__(self, rect: tuple[int, int, int, int], rgb: np.ndarray, alpha: np.ndarray):
        self.rect = rect                      # x0, y0, x1, y1 in frame px (x1/y1 exclusive)
        self.rgb = rgb.astype(np.float32, copy=False)
        self.alpha = alpha.astype(np.float32, copy=False)
        h, w = alpha.shape
        self.mask = np.zeros((h, w), np.uint8)

    def reveal_all(self) -> None:
        self.mask[:] = 255


class Board:
    """Background + layers. `img` always holds the current picture."""

    def __init__(self, bg: np.ndarray):
        self.bg = bg
        self.img = bg.copy()
        self.layers: list[Layer] = []
        self.h, self.w = bg.shape[:2]

    def add(self, layer: Layer) -> Layer:
        self.layers.append(layer)
        return layer

    def compose(self, box: list[float] | tuple | None = None) -> None:
        """Recompute the board inside `box` (frame px) from the background and layers."""
        if box is None:
            x0, y0, x1, y1 = 0, 0, self.w, self.h
        else:
            x0, y0 = max(0, int(box[0])), max(0, int(box[1]))
            x1, y1 = min(self.w, int(math.ceil(box[2])) + 1), min(self.h, int(math.ceil(box[3])) + 1)
        if x0 >= x1 or y0 >= y1:
            return
        out = None
        for L in self.layers:
            lx0, ly0, lx1, ly1 = L.rect
            ix0, iy0, ix1, iy1 = max(x0, lx0), max(y0, ly0), min(x1, lx1), min(y1, ly1)
            if ix0 >= ix1 or iy0 >= iy1:
                continue
            if out is None:
                out = self.bg[y0:y1, x0:x1].astype(np.float32)
            sy, sx = slice(iy0 - ly0, iy1 - ly0), slice(ix0 - lx0, ix1 - lx0)
            a = L.mask[sy, sx].astype(np.float32) * (1 / 255) * L.alpha[sy, sx]
            region = out[iy0 - y0:iy1 - y0, ix0 - x0:ix1 - x0]
            region += (L.rgb[sy, sx] - region) * a[..., None]
        if out is None:
            self.img[y0:y1, x0:x1] = self.bg[y0:y1, x0:x1]
        else:
            self.img[y0:y1, x0:x1] = np.clip(out, 0, 255).astype(np.uint8)

    def finish(self) -> None:
        for L in self.layers:
            L.reveal_all()
        self.compose(None)


# ──────────────────────────────────────────────────────────────
# Pen plans
# ──────────────────────────────────────────────────────────────
@dataclass
class PenPlan:
    pts: np.ndarray      # (P, 2) frame px
    rad: np.ndarray      # (P,)   reveal radius at each point
    down: np.ndarray     # (P,)   True if the segment ending at P is drawn
    cum: np.ndarray      # (P,)   cumulative effort

    @property
    def total(self) -> float:
        return float(self.cum[-1]) if len(self.cum) else 0.0

    def _locate(self, effort: float) -> tuple[int, float]:
        i = int(np.searchsorted(self.cum, effort, side="right"))
        if i <= 0:
            return 0, 0.0
        if i >= len(self.pts):
            return len(self.pts) - 1, 1.0
        c0, c1 = self.cum[i - 1], self.cum[i]
        return i, (0.0 if c1 <= c0 else (effort - c0) / (c1 - c0))

    def position(self, effort: float) -> tuple[float, float]:
        if len(self.pts) == 0:
            return (0.0, 0.0)
        i, f = self._locate(effort)
        if i == 0:
            return (float(self.pts[0][0]), float(self.pts[0][1]))
        p = self.pts[i - 1] + (self.pts[i] - self.pts[i - 1]) * f
        return (float(p[0]), float(p[1]))

    def is_down(self, effort: float) -> bool:
        if len(self.pts) < 2 or effort >= self.total:
            return False
        i, _f = self._locate(effort)
        return bool(self.down[i]) if 0 < i < len(self.down) else False

    @property
    def start(self) -> tuple[float, float]:
        """Where the pen first touches the board."""
        if len(self.pts) > 1:
            return (float(self.pts[1][0]), float(self.pts[1][1]))
        return self.end

    @property
    def end(self) -> tuple[float, float]:
        if len(self.pts) == 0:
            return (0.0, 0.0)
        return (float(self.pts[-1][0]), float(self.pts[-1][1]))


def build_plan(polylines: list[tuple[np.ndarray, np.ndarray]], start: tuple[float, float],
               lift_cost: float = 0.35, lift_pause: float = 10.0) -> tuple[PenPlan, list[tuple[int, int]]]:
    """Join strokes into one pen route. Also returns each stroke's (first, last) point index."""
    pts, rad, down, cost = [np.array(start, np.float32)], [1.0], [False], [0.0]
    spans: list[tuple[int, int]] = []
    prev = np.array(start, np.float32)
    for p, r in polylines:
        if len(p) == 0:
            spans.append((len(pts) - 1, len(pts) - 1))
            continue
        travel = float(np.linalg.norm(p[0] - prev))
        first = len(pts)
        pts.append(p[0])
        rad.append(float(r[0]))
        down.append(False)
        cost.append(travel * lift_cost + lift_pause)
        seg = np.linalg.norm(np.diff(p, axis=0), axis=1)
        for j in range(1, len(p)):
            pts.append(p[j])
            rad.append(float(r[j]))
            down.append(True)
            cost.append(float(seg[j - 1]))
        spans.append((first, len(pts) - 1))
        prev = p[-1]
    plan = PenPlan(np.array(pts, np.float32), np.array(rad, np.float32), np.array(down, bool),
                   np.cumsum(np.array(cost, np.float64)))
    return plan, spans


class Reveal:
    """Walks a pen plan and reveals the target layers along it."""

    def __init__(self, plan: PenPlan, targets: list[tuple[Layer, float]]):
        self.plan = plan
        self.targets = targets           # (layer, thickness multiplier)
        self.idx = 1
        self.effort = 0.0

    def advance(self, effort: float) -> list[float] | None:
        """Reveal up to `effort`. Returns the dirty box in frame px (or None)."""
        plan = self.plan
        n = len(plan.pts)
        effort = min(effort, plan.total)
        if effort <= self.effort and self.idx > 1:
            return None
        self.effort = max(self.effort, effort)
        box = None

        def stamp(a, b, r):
            nonlocal box
            for layer, mult in self.targets:
                ox, oy = layer.rect[0], layer.rect[1]
                t = max(1, int(round(2 * r * mult)))
                pa = (int(round(a[0] - ox)), int(round(a[1] - oy)))
                pb = (int(round(b[0] - ox)), int(round(b[1] - oy)))
                cv2.line(layer.mask, pa, pb, 255, t, cv2.LINE_AA)
            rr = r * max(m for _l, m in self.targets) + 2
            bx = [min(a[0], b[0]) - rr, min(a[1], b[1]) - rr, max(a[0], b[0]) + rr, max(a[1], b[1]) + rr]
            box = bx if box is None else [min(box[0], bx[0]), min(box[1], bx[1]),
                                          max(box[2], bx[2]), max(box[3], bx[3])]

        idx = self.idx
        while idx < n and plan.cum[idx] <= effort:
            if plan.down[idx]:
                stamp(plan.pts[idx - 1], plan.pts[idx], (plan.rad[idx - 1] + plan.rad[idx]) / 2)
            idx += 1
        self.idx = idx
        # Partial segment up to the exact pen position.
        if idx < n and plan.down[idx] and plan.cum[idx] > plan.cum[idx - 1]:
            f = (effort - plan.cum[idx - 1]) / (plan.cum[idx] - plan.cum[idx - 1])
            if f > 0:
                a = plan.pts[idx - 1]
                stamp(a, a + (plan.pts[idx] - a) * f, plan.rad[idx])
        return box
