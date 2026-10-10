"""Turn line art into ordered pen strokes.

A raster image becomes a list of polylines that a pen could follow:
skeletonize the ink mask, trace the skeleton into strokes, then order the
strokes object by object so the hand moves the way a person would draw.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class Stroke:
    points: np.ndarray   # (N, 2) float32, x/y in drawing coordinates
    radius: np.ndarray   # (N,) float32, reveal radius at each point
    group: int = 0       # object the stroke belongs to (for ordering)

    @property
    def length(self) -> float:
        if len(self.points) < 2:
            return 0.0
        return float(np.linalg.norm(np.diff(self.points, axis=0), axis=1).sum())


# ──────────────────────────────────────────────────────────────
# Skeleton
# ──────────────────────────────────────────────────────────────
def skeletonize(mask: np.ndarray) -> np.ndarray:
    """Boolean skeleton of a boolean mask."""
    try:
        from skimage.morphology import skeletonize as sk
        return sk(mask.astype(bool))
    except Exception:  # pragma: no cover - fallback when scikit-image is missing
        pass
    if hasattr(cv2, "ximgproc"):
        return cv2.ximgproc.thinning(mask.astype(np.uint8) * 255) > 0
    return _zhang_suen(mask.astype(bool))


def _zhang_suen(img: np.ndarray, max_iter: int = 200) -> np.ndarray:
    """Pure NumPy Zhang-Suen thinning (slow fallback)."""
    img = img.copy().astype(np.uint8)
    for _ in range(max_iter):
        changed = False
        for step in (0, 1):
            p = np.pad(img, 1)
            p2, p3, p4 = p[:-2, 1:-1], p[:-2, 2:], p[1:-1, 2:]
            p5, p6, p7 = p[2:, 2:], p[2:, 1:-1], p[2:, :-2]
            p8, p9 = p[1:-1, :-2], p[:-2, :-2]
            nbrs = [p2, p3, p4, p5, p6, p7, p8, p9]
            b = sum(n.astype(np.int32) for n in nbrs)
            seq = nbrs + [p2]
            a = sum(((seq[i] == 0) & (seq[i + 1] == 1)).astype(np.int32) for i in range(8))
            if step == 0:
                c1, c2 = p2 * p4 * p6, p4 * p6 * p8
            else:
                c1, c2 = p2 * p4 * p8, p2 * p6 * p8
            rm = (img == 1) & (b >= 2) & (b <= 6) & (a == 1) & (c1 == 0) & (c2 == 0)
            if rm.any():
                img[rm] = 0
                changed = True
        if not changed:
            break
    return img.astype(bool)


# 8-neighbourhood, 4-neighbours first so walks prefer straight steps.
_OFFS = [(0, 1), (1, 0), (0, -1), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)]


def trace_skeleton(skel: np.ndarray, min_points: int = 3) -> list[np.ndarray]:
    """Trace a skeleton into polylines of (x, y) points."""
    h, w = skel.shape
    ys, xs = np.nonzero(skel)
    n = len(xs)
    if n == 0:
        return []
    idx = np.full((h + 2, w + 2), -1, dtype=np.int64)
    idx[ys + 1, xs + 1] = np.arange(n)
    nbr = np.stack([idx[ys + 1 + dy, xs + 1 + dx] for dy, dx in _OFFS], axis=1)  # (n, 8)
    deg = (nbr >= 0).sum(axis=1)
    visited = np.zeros(n, dtype=bool)
    nbr_list = nbr.tolist()
    xs_l, ys_l = xs.tolist(), ys.tolist()

    def walk(start: int) -> list[int]:
        path = [start]
        visited[start] = True
        cur = start
        prev_dir = None
        while True:
            best, best_score = -1, None
            for k, j in enumerate(nbr_list[cur]):
                if j < 0 or visited[j]:
                    continue
                dy, dx = _OFFS[k]
                # Prefer continuing in the same direction (straightest path).
                score = 0.0 if prev_dir is None else -(dx * prev_dir[0] + dy * prev_dir[1])
                score += 0.01 * k  # 4-neighbours first on ties
                if best_score is None or score < best_score:
                    best, best_score = j, score
            if best < 0:
                # Touch a visited neighbour so branches connect to the trunk.
                for j in nbr_list[cur]:
                    if j >= 0 and j != (path[-2] if len(path) > 1 else -1) and visited[j] and len(path) > 1:
                        path.append(j)
                        break
                return path
            prev_dir = (xs_l[best] - xs_l[cur], ys_l[best] - ys_l[cur])
            visited[best] = True
            path.append(best)
            cur = best

    paths: list[list[int]] = []
    for start in np.nonzero(deg == 1)[0].tolist():
        if not visited[start]:
            paths.append(walk(start))
    for start in np.nonzero(deg >= 3)[0].tolist():
        if not visited[start]:
            paths.append(walk(start))
    for start in range(n):  # closed loops
        if not visited[start]:
            p = walk(start)
            if len(p) > 2:
                p.append(p[0])
            paths.append(p)

    out = []
    for p in paths:
        if len(p) < min_points:
            continue
        out.append(np.stack([xs[p], ys[p]], axis=1).astype(np.float32))
    return out


def simplify(points: np.ndarray, step: float = 2.5) -> np.ndarray:
    """Resample a polyline to roughly `step` px spacing and smooth it lightly."""
    if len(points) < 3:
        return points
    seg = np.linalg.norm(np.diff(points, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = cum[-1]
    if total < step:
        return points[[0, -1]]
    t = np.linspace(0, total, max(2, int(total / step) + 1))
    x = np.interp(t, cum, points[:, 0])
    y = np.interp(t, cum, points[:, 1])
    pts = np.stack([x, y], axis=1)
    if len(pts) > 4:  # light moving-average smoothing, ends pinned
        sm = pts.copy()
        sm[1:-1] = (pts[:-2] + 2 * pts[1:-1] + pts[2:]) / 4
        pts = sm
    return pts.astype(np.float32)


# ──────────────────────────────────────────────────────────────
# Raster -> strokes
# ──────────────────────────────────────────────────────────────
def strokes_from_mask(ink: np.ndarray, groups: np.ndarray) -> list[Stroke]:
    """Strokes covering the ink mask. `groups` labels objects (int image)."""
    if not ink.any():
        return []
    dist = cv2.distanceTransform(ink.astype(np.uint8), cv2.DIST_L2, 3)
    skel = skeletonize(ink)
    polys = trace_skeleton(skel, min_points=2)
    strokes: list[Stroke] = []
    h, w = ink.shape
    for poly in polys:
        xi = np.clip(poly[:, 0].astype(int), 0, w - 1)
        yi = np.clip(poly[:, 1].astype(int), 0, h - 1)
        r = dist[yi, xi] + 1.6
        pts = simplify(poly)
        rr = np.interp(np.linspace(0, 1, len(pts)), np.linspace(0, 1, len(r)), r).astype(np.float32)
        g = int(groups[yi[len(yi) // 2], xi[len(xi) // 2]])
        strokes.append(Stroke(pts, rr, g))
    return strokes


def label_objects(mask: np.ndarray, gap: int) -> tuple[np.ndarray, np.ndarray]:
    """Group nearby marks into objects (so the pen finishes one thing first).

    Returns (labels, stats) as cv2.connectedComponentsWithStats does.
    """
    k = max(3, gap | 1)
    merged = cv2.dilate(mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    _n, labels, stats, _c = cv2.connectedComponentsWithStats(merged, connectivity=8)
    return labels, stats


def order_groups(stats: np.ndarray, order: str) -> list[int]:
    """Object order on the board: reading order by default."""
    items = []
    for g in range(1, len(stats)):
        x, y, w, h, area = (int(v) for v in stats[g])
        if area == 0:
            continue
        items.append((g, x, x + w - 1, y, y + h - 1, area))
    if order == "top_to_bottom":
        key = lambda it: (it[3], it[1])
    elif order == "right_to_left":
        key = lambda it: (-it[2], it[3])
    elif order == "size":
        key = lambda it: -it[5]
    else:  # left_to_right
        key = lambda it: (it[1], it[3])
    return [it[0] for it in sorted(items, key=key)]


def order_strokes(strokes: list[Stroke], group_order: list[int], start: tuple[float, float]) -> list[Stroke]:
    """Greedy nearest-neighbour ordering inside each object."""
    rank = {g: i for i, g in enumerate(group_order)}
    by_group: dict[int, list[Stroke]] = {}
    for s in strokes:
        by_group.setdefault(s.group, []).append(s)
    groups = sorted(by_group, key=lambda g: rank.get(g, len(rank)))
    pen = np.array(start, dtype=np.float32)
    out: list[Stroke] = []
    for g in groups:
        pool = by_group[g]
        # Long strokes first inside a group feels like "outline, then details".
        pool.sort(key=lambda s: -s.length)
        heads = np.array([s.points[0] for s in pool])
        tails = np.array([s.points[-1] for s in pool])
        lengths = np.array([s.length for s in pool])
        alive = np.ones(len(pool), dtype=bool)
        for _ in range(len(pool)):
            dh = np.linalg.norm(heads - pen, axis=1)
            dt = np.linalg.norm(tails - pen, axis=1)
            d = np.minimum(dh, dt) - 0.15 * np.minimum(lengths, 200)
            d[~alive] = np.inf
            i = int(np.argmin(d))
            alive[i] = False
            s = pool[i]
            if dt[i] < dh[i]:
                s = Stroke(s.points[::-1].copy(), s.radius[::-1].copy(), s.group)
            out.append(s)
            pen = s.points[-1]
    return out


# ──────────────────────────────────────────────────────────────
# Colouring sweep
# ──────────────────────────────────────────────────────────────
def zigzag(x0: int, y0: int, x1: int, y1: int, radius: float) -> np.ndarray:
    """Back-and-forth brush path covering a box."""
    stride = max(4.0, radius * 1.4)
    ys = np.arange(y0 + radius * 0.6, y1 + stride * 0.5, stride)
    if len(ys) == 0:
        ys = np.array([(y0 + y1) / 2])
    pts = []
    for i, y in enumerate(ys):
        a, b = (x0, x1) if i % 2 == 0 else (x1, x0)
        pts.append((a, min(y, y1)))
        pts.append((b, min(y, y1)))
    return np.array(pts, dtype=np.float32)
