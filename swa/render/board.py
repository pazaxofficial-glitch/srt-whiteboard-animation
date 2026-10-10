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
        self.level = 0.0                      # how far fade_in() has gone

    def reveal_all(self) -> None:
        self.mask[:] = 255
        self.level = 1.0

    def fade_in(self, q: float) -> list[float] | None:
        """Show the whole layer at strength q (0..1) without a pen. Returns the dirty box."""
        q = min(1.0, max(0.0, q))
        if q <= self.level:
            return None
        self.level = q
        np.maximum(self.mask, np.uint8(round(q * 255)), out=self.mask)
        return [float(v) for v in self.rect]


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
    seg: np.ndarray | None = None   # (P,) which region a point colours in (colour plans)

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
               lift_cost: float = 0.35, lift_pause: float = 10.0,
               ids: list[int] | None = None) -> tuple[PenPlan, list[tuple[int, int]]]:
    """Join strokes into one pen route. Also returns each stroke's (first, last) point index.

    ids: optional region index for every polyline (stored per point in `plan.seg`).
    """
    pts, rad, down, cost, seg_id = [np.array(start, np.float32)], [1.0], [False], [0.0], [-1]
    spans: list[tuple[int, int]] = []
    prev = np.array(start, np.float32)
    for k, (p, r) in enumerate(polylines):
        if len(p) == 0:
            spans.append((len(pts) - 1, len(pts) - 1))
            continue
        sid = ids[k] if ids is not None else -1
        travel = float(np.linalg.norm(p[0] - prev))
        first = len(pts)
        pts.append(p[0])
        rad.append(float(r[0]))
        down.append(False)
        cost.append(travel * lift_cost + lift_pause)
        seg_id.append(sid)
        seg = np.linalg.norm(np.diff(p, axis=0), axis=1)
        for j in range(1, len(p)):
            pts.append(p[j])
            rad.append(float(r[j]))
            down.append(True)
            cost.append(float(seg[j - 1]))
            seg_id.append(sid)
        spans.append((first, len(pts) - 1))
        prev = p[-1]
    plan = PenPlan(np.array(pts, np.float32), np.array(rad, np.float32), np.array(down, bool),
                   np.cumsum(np.array(cost, np.float64)), np.array(seg_id, np.int32) if ids is not None else None)
    return plan, spans


def with_rest(plan: PenPlan, effort: float, lift: float = 30.0) -> PenPlan:
    """Append a short pen-up drift at the end of a plan (the hand lifts and looks)."""
    if len(plan.pts) == 0 or effort <= 0:
        return plan
    end = plan.pts[-1]
    pts = np.vstack([plan.pts, (end + np.array([lift * 0.6, -lift], np.float32))[None]])
    seg = None if plan.seg is None else np.concatenate([plan.seg, [-1]]).astype(np.int32)
    return PenPlan(pts, np.concatenate([plan.rad, [1.0]]).astype(np.float32),
                   np.concatenate([plan.down, [False]]), np.concatenate([plan.cum, [plan.cum[-1] + effort]]), seg)


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


@dataclass
class Region:
    """Where one group of colouring strokes may paint: a soft mask on a layer."""
    x0: int              # top-left of the mask in layer px
    y0: int
    mask: np.ndarray     # (h, w) uint8 0..255


class ColorReveal:
    """Colours a layer in with marker strokes, one region at a time.

    Each stroke only paints inside its own region, so neighbouring colours
    never appear early. The marker leaves a streaky, uneven coat (like felt
    tip on a board); when a region is finished its colour settles to the
    clean picture over the next bit of pen travel.
    """

    def __init__(self, plan: PenPlan, layer: Layer, regions: list[Region], settle: list[float],
                 seed: int = 0):
        self.plan = plan
        self.layer = layer
        self.regions = regions
        self.idx = 1
        self.effort = 0.0
        seg = plan.seg if plan.seg is not None else np.full(len(plan.pts), -1, np.int32)
        self.seg = seg
        self.ends = np.zeros(len(regions), np.float64)
        for k in range(len(regions)):
            where = np.nonzero(seg == k)[0]
            self.ends[k] = plan.cum[where[-1]] if len(where) else 0.0
        self.spans = [max(1.0, s) for s in settle]
        self.settled = np.zeros(len(regions), np.float64)
        rng = np.random.default_rng(seed)
        self.profiles = [rng.uniform(0.7, 0.97, 5) * np.array([0.85, 1, 1, 1, 0.85]) for _ in regions]

    def _stamp(self, a, b, r: float, k: int) -> list[float] | None:
        reg = self.regions[k]
        ox, oy = self.layer.rect[0], self.layer.rect[1]
        ax, ay, bx, by = a[0] - ox, a[1] - oy, b[0] - ox, b[1] - oy
        pad = r + 2
        ix0 = max(int(np.floor(min(ax, bx) - pad)), reg.x0)
        iy0 = max(int(np.floor(min(ay, by) - pad)), reg.y0)
        ix1 = min(int(np.ceil(max(ax, bx) + pad)) + 1, reg.x0 + reg.mask.shape[1])
        iy1 = min(int(np.ceil(max(ay, by) + pad)) + 1, reg.y0 + reg.mask.shape[0])
        if ix0 >= ix1 or iy0 >= iy1:
            return None
        tmp = np.zeros((iy1 - iy0, ix1 - ix0), np.uint8)
        d = np.array([bx - ax, by - ay], np.float64)
        n_len = float(np.hypot(*d))
        d = d / n_len if n_len > 1e-6 else np.array([1.0, 0.0])
        nrm = np.array([-d[1], d[0]])
        prof = self.profiles[k]
        kk = len(prof) if r >= 5 else 1
        width = 2 * r / kk
        sh = 4.0  # sub-pixel precision for cv2.line (shift=2)
        for j in range(kk):
            off = -r + width * (j + 0.5) if kk > 1 else 0.0
            val = int(255 * (prof[j] if kk > 1 else float(prof.mean())))
            p = (int(round((ax + nrm[0] * off - ix0) * sh)), int(round((ay + nrm[1] * off - iy0) * sh)))
            q = (int(round((bx + nrm[0] * off - ix0) * sh)), int(round((by + nrm[1] * off - iy0) * sh)))
            cv2.line(tmp, p, q, val, max(1, int(round(width * 1.35))), cv2.LINE_AA, 2)
        clip = reg.mask[iy0 - reg.y0:iy1 - reg.y0, ix0 - reg.x0:ix1 - reg.x0]
        tmp = cv2.multiply(tmp, clip, scale=1 / 255)
        roi = self.layer.mask[iy0:iy1, ix0:ix1]
        np.maximum(roi, tmp, out=roi)
        return [ix0 + ox, iy0 + oy, ix1 + ox, iy1 + oy]

    def _settle(self, effort: float) -> list[list[float]]:
        boxes = []
        ox, oy = self.layer.rect[0], self.layer.rect[1]
        for k, reg in enumerate(self.regions):
            if self.settled[k] >= 1.0 or effort < self.ends[k]:
                continue
            q = 1.0 if effort >= self.plan.total else min(1.0, (effort - self.ends[k]) / self.spans[k])
            if q <= self.settled[k]:
                continue
            self.settled[k] = q
            h, w = reg.mask.shape
            roi = self.layer.mask[reg.y0:reg.y0 + h, reg.x0:reg.x0 + w]
            np.maximum(roi, cv2.multiply(reg.mask, np.full_like(reg.mask, 255), scale=q / 255), out=roi)
            boxes.append([reg.x0 + ox, reg.y0 + oy, reg.x0 + w + ox, reg.y0 + h + oy])
        return boxes

    def advance(self, effort: float) -> list[float] | None:
        """Colour in up to `effort`. Returns the dirty box in frame px (or None)."""
        plan = self.plan
        n = len(plan.pts)
        effort = min(effort, plan.total)
        if effort <= self.effort and self.idx > 1:
            return None
        self.effort = max(self.effort, effort)
        boxes: list[list[float]] = []

        def stamp(a, b, r, k):
            if k >= 0:
                bx = self._stamp(a, b, r, k)
                if bx:
                    boxes.append(bx)

        idx = self.idx
        while idx < n and plan.cum[idx] <= effort:
            if plan.down[idx]:
                stamp(plan.pts[idx - 1], plan.pts[idx], (plan.rad[idx - 1] + plan.rad[idx]) / 2, int(self.seg[idx]))
            idx += 1
        self.idx = idx
        if idx < n and plan.down[idx] and plan.cum[idx] > plan.cum[idx - 1]:
            f = (effort - plan.cum[idx - 1]) / (plan.cum[idx] - plan.cum[idx - 1])
            if f > 0:
                a = plan.pts[idx - 1]
                stamp(a, a + (plan.pts[idx] - a) * f, plan.rad[idx], int(self.seg[idx]))
        boxes += self._settle(effort)
        if not boxes:
            return None
        return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
