"""Prepare one image for drawing: layers to reveal + the pen's route.

Every image (PNG/JPG/WebP or SVG) becomes a `PreparedDrawing`:
  line layer  what the pen reveals first (outlines / dark line art)
  full layer  the finished, coloured picture
  strokes     ordered polylines the pen tip follows
  regions     areas to colour in, each with its own marker strokes
  segments    parts of an SVG that wait for a spoken word (data-word="...")
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .imageio import imread
from .strokes import (Stroke, fill_radius, hatch, label_objects, order_groups, order_paths, order_strokes,
                      strokes_from_mask)

MAX_REGIONS = 32        # colour regions per raster picture (smaller ones join their neighbours)


@dataclass
class ColorRegion:
    """One area to colour in: marker strokes plus the soft mask they may paint inside."""
    paths: list[np.ndarray]     # marker strokes (frame px once prepared)
    radius: float
    x0: int                     # mask position inside the drawing (layer px)
    y0: int
    mask: np.ndarray            # (h, w) uint8 0..255
    segment: int = 0

    @property
    def area(self) -> int:
        return int(np.count_nonzero(self.mask > 127))


@dataclass
class Segment:
    """Part of a drawing that starts when a word is spoken (SVG data-word)."""
    cue: str | None
    strokes: tuple[int, int]    # index range in PreparedDrawing.strokes
    regions: tuple[int, int]    # index range in PreparedDrawing.regions


@dataclass
class PreparedDrawing:
    rect: tuple[int, int, int, int]       # x0, y0, x1, y1 in frame pixels
    line_rgb: np.ndarray                  # (h, w, 3) float32
    line_a: np.ndarray                    # (h, w) float32 0..1
    full_rgb: np.ndarray                  # (h, w, 3) float32
    full_a: np.ndarray                    # (h, w) float32 0..1
    strokes: list[Stroke]
    regions: list[ColorRegion] = field(default_factory=list)
    colorful: bool = False                # has colour (or shading) worth a colouring pass
    segments: list[Segment] = field(default_factory=list)

    @property
    def size(self) -> tuple[int, int]:
        return self.line_a.shape[1], self.line_a.shape[0]

    @property
    def color_paths(self) -> list[tuple[np.ndarray, float]]:
        return [(p, r.radius) for r in self.regions for p in r.paths]

    def parts(self) -> list[Segment]:
        """Segments to draw in order (the whole drawing is one untimed segment by default)."""
        if self.segments:
            return self.segments
        return [Segment(None, (0, len(self.strokes)), (0, len(self.regions)))]


def fit_rect(img_w: int, img_h: int, area: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Largest rect with the image's aspect ratio, centred in `area` (x0, y0, x1, y1)."""
    ax0, ay0, ax1, ay1 = area
    aw, ah = max(2, ax1 - ax0), max(2, ay1 - ay0)
    s = min(aw / img_w, ah / img_h)
    w, h = max(2, int(img_w * s)), max(2, int(img_h * s))
    x0 = ax0 + (aw - w) // 2
    y0 = ay0 + (ah - h) // 2
    return x0, y0, x0 + w, y0 + h


# ──────────────────────────────────────────────────────────────
# Colour handling for dark boards (chalk look)
# ──────────────────────────────────────────────────────────────
def to_chalk(rgb: np.ndarray) -> np.ndarray:
    """Dark ink -> light chalk; colours keep their hue but get lighter."""
    lab = cv2.cvtColor(np.clip(rgb, 0, 255).astype(np.uint8), cv2.COLOR_BGR2LAB).astype(np.float32)
    L, a, b = lab[..., 0], lab[..., 1] - 128, lab[..., 2] - 128
    chroma = np.sqrt(a * a + b * b)
    neutral = np.clip(1 - chroma / 40, 0, 1)
    L_inv = 255 - L * 0.85
    L_col = np.maximum(L, 150)
    lab[..., 0] = L_inv * neutral + L_col * (1 - neutral)
    out = cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)
    return out.astype(np.float32)


def chalk_texture(alpha: np.ndarray, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    grain = rng.random(alpha.shape, dtype=np.float32)
    grain = cv2.GaussianBlur(grain, (0, 0), 0.8)
    return alpha * np.clip(0.55 + grain * 0.7, 0, 1)


# ──────────────────────────────────────────────────────────────
# Colour regions
# ──────────────────────────────────────────────────────────────
def _soft(mask: np.ndarray, grow: int) -> np.ndarray:
    """Boolean mask -> uint8 mask grown by `grow` px with a soft edge (no seams between regions)."""
    m = mask.astype(np.uint8) * 255
    if grow > 0:
        m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1)))
    return cv2.GaussianBlur(m, (0, 0), 0.7)


def _make_region(mask: np.ndarray, diag: float, angle: float, seed: int, segment: int = 0,
                 grow: int = 1) -> ColorRegion | None:
    """Crop a full-size region mask and plan its marker strokes (layer px)."""
    ys, xs = np.nonzero(mask > 0)
    if len(xs) == 0:
        return None
    pad = grow + 3
    h, w = mask.shape
    x0, y0 = max(0, int(xs.min()) - pad), max(0, int(ys.min()) - pad)
    x1, y1 = min(w, int(xs.max()) + pad + 1), min(h, int(ys.max()) + pad + 1)
    crop = mask[y0:y1, x0:x1]
    hard = crop > 127 if crop.dtype == np.uint8 else crop.astype(bool)
    radius = fill_radius(hard, diag)
    paths = [p + np.array([x0, y0], np.float32) for p in hatch(hard, radius, angle, seed)]
    soft = _soft(hard, grow) if crop.dtype != np.uint8 or grow else crop
    return ColorRegion(paths, radius, x0, y0, soft, segment)


def _chain(regions: list[ColorRegion], start: tuple[float, float]) -> tuple[float, float]:
    """Order each region's strokes so the pen continues from where it is. Returns the end point."""
    pen = start
    for r in regions:
        if r.paths:
            r.paths = order_paths(r.paths, pen)
            pen = (float(r.paths[-1][-1][0]), float(r.paths[-1][-1][1]))
    return pen


def _raster_regions(bgr: np.ndarray, fg: np.ndarray, ink: np.ndarray, labels: np.ndarray,
                    group_order: list[int], angle: float, seed: int) -> tuple[list[ColorRegion], bool]:
    """Areas of similar colour that the outline does not cover, in drawing order.

    Returns (regions, colorful). `colorful` is False for black-and-white line
    art: nothing would change during a colouring pass.
    """
    h, w = fg.shape
    total = w * h
    k = max(1, int(round(0.0008 * (w + h))))
    ink_d = cv2.dilate(ink.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1)))
    cand = ((fg > 0.35) & (ink_d == 0)).astype(np.uint8)
    cand = cv2.morphologyEx(cand, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(cand, connectivity=8)
    keep = stats[:, cv2.CC_STAT_AREA] >= max(24, int(0.0004 * total))
    keep[0] = False
    cand = keep[lab]
    area = int(cand.sum())
    if area == 0:
        return [], False
    colorful = area >= 0.0015 * total

    # Work on a smaller copy: colour clusters do not need full resolution.
    s = min(1.0, float(np.sqrt(350_000 / total)))
    ws, hs = max(8, int(w * s)), max(8, int(h * s))
    small = cv2.resize(bgr, (ws, hs), interpolation=cv2.INTER_AREA) if s < 1 else bgr
    cand_s = cv2.resize(cand.astype(np.uint8), (ws, hs), interpolation=cv2.INTER_NEAREST) > 0 if s < 1 else cand
    if not cand_s.any():
        cand_s = cv2.resize(cand.astype(np.uint8), (ws, hs), interpolation=cv2.INTER_AREA) > 0
    lab_img = cv2.cvtColor(cv2.medianBlur(small, 5), cv2.COLOR_BGR2LAB).astype(np.float32)
    feats = lab_img[cand_s] * np.array([0.5, 1.0, 1.0], np.float32)
    rng = np.random.default_rng(seed)
    sample = feats[rng.choice(len(feats), min(len(feats), 20_000), replace=False)] if len(feats) > 20_000 else feats
    kk = int(min(6, max(1, len(sample) // 50)))
    if kk > 1:
        crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 15, 0.5)
        cv2.setRNGSeed(seed)
        _c, _l, centers = cv2.kmeans(np.ascontiguousarray(sample), kk, None, crit, 2, cv2.KMEANS_PP_CENTERS)
        merged: list[np.ndarray] = []
        for c in centers:                       # similar colours are one colour
            if all(np.linalg.norm(c - m) > 14 for m in merged):
                merged.append(c)
        centers = np.array(merged, np.float32)
    else:
        centers = feats.mean(axis=0, keepdims=True)
    d = ((feats[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
    assign = np.full((hs, ws), -1, np.int32)
    assign[cand_s] = np.argmin(d, axis=1)

    # Connected areas of one colour become regions; tiny ones join their neighbours.
    reg = np.zeros((hs, ws), np.int32)
    sizes: list[int] = []
    min_reg = max(12, int(0.0008 * hs * ws))
    for c in range(len(centers)):
        nc, cl, st, _ = cv2.connectedComponentsWithStats((assign == c).astype(np.uint8), connectivity=8)
        lut = np.zeros(nc, np.int32)
        for j in range(1, nc):
            if st[j, cv2.CC_STAT_AREA] >= min_reg:
                sizes.append(int(st[j, cv2.CC_STAT_AREA]))
                lut[j] = len(sizes)
        m = assign == c
        reg[m] = lut[cl[m]]
    if not sizes:
        reg[cand_s] = 1
        sizes = [int(cand_s.sum())]
    if len(sizes) > MAX_REGIONS:
        big = np.argsort(sizes)[::-1][:MAX_REGIONS] + 1
        lut = np.zeros(len(sizes) + 1, np.int32)
        lut[big] = np.arange(1, len(big) + 1)
        reg = lut[reg]
        sizes = [sizes[i - 1] for i in big]

    # Back to full size; every leftover candidate pixel joins the nearest region.
    if s < 1:
        reg = cv2.resize(reg.astype(np.uint16), (w, h), interpolation=cv2.INTER_NEAREST).astype(np.int32)
    reg[~cand] = 0
    left = cand & (reg == 0)
    if left.any() and (reg > 0).any():
        src = (reg == 0).astype(np.uint8)
        _dist, near = cv2.distanceTransformWithLabels(src, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
        kept = reg > 0
        lut = np.zeros(int(near.max()) + 1, np.int32)
        lut[near[kept]] = reg[kept]
        reg[left] = lut[near[left]]
    rank = {g: i for i, g in enumerate(group_order)}
    diag = float(np.hypot(w, h))
    items = []
    for rid in range(1, len(sizes) + 1):
        m = reg == rid
        cnt = int(m.sum())
        if cnt < 8:
            continue
        objs = labels[m]
        objs = objs[objs > 0]
        obj = int(np.bincount(objs).argmax()) if len(objs) else 0
        items.append((rank.get(obj, len(rank)), -cnt, rid, m))
    items.sort(key=lambda it: (it[0], it[1]))
    regions = []
    for i, (_r, _c, _rid, m) in enumerate(items):
        region = _make_region(m, diag, angle, seed + i, grow=max(1, k))
        if region is not None:
            regions.append(region)
    return regions, colorful


# ──────────────────────────────────────────────────────────────
# Raster images
# ──────────────────────────────────────────────────────────────
def _foreground_alpha(img: np.ndarray) -> np.ndarray:
    """Separate the drawing from a plain background (alpha channel if present)."""
    if img.shape[2] == 4:
        return img[:, :, 3].astype(np.float32) / 255.0
    bgr = img.astype(np.float32)
    h, w = bgr.shape[:2]
    m = max(2, min(h, w) // 60)
    border = np.concatenate([bgr[:m].reshape(-1, 3), bgr[-m:].reshape(-1, 3),
                             bgr[:, :m].reshape(-1, 3), bgr[:, -m:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    spread = np.median(np.abs(border - bg).sum(axis=1))
    if spread > 40:
        # Busy background (photo): keep everything.
        return np.ones((h, w), dtype=np.float32)
    dist = np.abs(bgr - bg).sum(axis=2)
    lo, hi = 18 + spread, 60 + spread
    return np.clip((dist - lo) / (hi - lo), 0, 1).astype(np.float32)


def _ink_mask(bgr: np.ndarray, fg: np.ndarray) -> np.ndarray:
    """Line art: pixels clearly darker than their surroundings, plus colour edges."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    local = cv2.GaussianBlur(gray, (0, 0), 6)
    area = fg > 0.3
    total = max(1, int(area.sum()))
    ink = None
    for thr in (14, 22, 32, 45, 60):
        ink = (((local - gray) > thr) | (gray < 70)) & area
        if ink.sum() / total < 0.35:
            break
    # Outlines of flat colour shapes that have no dark border.
    edges = cv2.Canny(cv2.GaussianBlur(bgr, (3, 3), 0), 60, 140) > 0
    edges = cv2.dilate(edges.astype(np.uint8), np.ones((2, 2), np.uint8)) > 0
    ink = ink | (edges & area)
    # Remove dust.
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    keep = np.zeros(n, dtype=bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= 6
    return keep[lab]


def prepare_raster(path: Path, area: tuple[int, int, int, int], dark: bool,
                   order: str, start: tuple[float, float], angle: float = 55.0) -> PreparedDrawing:
    img = imread(path)
    if img is None:
        raise ValueError(f"Cannot read image {path}")
    rect = fit_rect(img.shape[1], img.shape[0], area)
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    interp = cv2.INTER_AREA if w < img.shape[1] else cv2.INTER_CUBIC
    img = cv2.resize(img, (w, h), interpolation=interp)
    bgr = np.ascontiguousarray(img[:, :, :3])
    fg = _foreground_alpha(img)
    ink = _ink_mask(bgr, fg)

    full_rgb = bgr.astype(np.float32)
    full_a = fg
    line_rgb = full_rgb
    soft_ink = cv2.GaussianBlur(ink.astype(np.float32), (3, 3), 0)
    line_a = np.maximum(soft_ink * fg, ink * fg)

    gap = max(9, int(0.012 * (w + h)))
    labels, stats = label_objects(ink | (fg > 0.5), gap)
    group_order = order_groups(stats, order)
    local_start = (start[0] - rect[0], start[1] - rect[1])
    strokes = order_strokes(strokes_from_mask(ink, labels), group_order, local_start)
    regions, colorful = _raster_regions(bgr, fg, ink, labels, group_order, angle, seed=w * 31 + h)
    pen = tuple(strokes[-1].points[-1]) if strokes else local_start
    _chain(regions, pen)
    if dark:
        full_rgb = to_chalk(full_rgb)
        line_rgb = full_rgb
        line_a = chalk_texture(line_a, seed=w * 31 + h)
        full_a = np.clip(full_a * 0.92, 0, 1)
    return PreparedDrawing(rect, line_rgb, line_a.astype(np.float32), full_rgb, full_a.astype(np.float32),
                           strokes, regions, colorful)


# ──────────────────────────────────────────────────────────────
# SVG images (vector line art, e.g. drawn by Claude Code)
# ──────────────────────────────────────────────────────────────
def _svg_color(c) -> tuple[int, int, int, float] | None:
    if c is None:
        return None
    try:
        if c.value is None or str(c).lower() == "none":
            return None
        alpha = c.alpha / 255.0 if c.alpha is not None else 1.0
        if alpha <= 0:
            return None
        return (c.blue, c.green, c.red, alpha)
    except AttributeError:
        return None


def _sample_subpath(sub, scale: float, ox: float, oy: float, step: float = 3.0) -> np.ndarray:
    from svgelements import Close, Line, Move

    pts: list[tuple[float, float]] = []
    for seg in sub:
        if isinstance(seg, Move):
            if seg.end is not None:
                pts.append((seg.end.x, seg.end.y))
            continue
        if seg.start is None or seg.end is None:
            continue
        if isinstance(seg, (Line, Close)):
            if not pts:
                pts.append((seg.start.x, seg.start.y))
            pts.append((seg.end.x, seg.end.y))
            continue
        try:
            length = seg.length(error=1e-3) * scale
        except Exception:
            length = 50.0
        n = max(4, int(length / step))
        for t in np.linspace(0, 1, n + 1)[(1 if pts else 0):]:
            p = seg.point(float(t))
            pts.append((p.x, p.y))
    if not pts:
        return np.zeros((0, 2), dtype=np.float32)
    arr = np.array(pts, dtype=np.float32)
    arr[:, 0] = arr[:, 0] * scale + ox
    arr[:, 1] = arr[:, 1] * scale + oy
    return arr


def svg_cues(path: Path) -> list[str]:
    """Words that start timed parts of an SVG (data-word="..."), in document order. Cheap: no rendering."""
    import re

    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [m.group(2).strip() for m in re.finditer(r"data-word\s*=\s*([\"'])(.*?)\1", text) if m.group(2).strip()]


def prepare_svg(path: Path, area: tuple[int, int, int, int], dark: bool,
                thickness: float = 1.0, angle: float = 55.0) -> PreparedDrawing:
    from svgelements import SVG, Path as SvgPath, Shape

    svg = SVG.parse(str(path), reify=True)
    vw = float(svg.width or 0) or 1000.0
    vh = float(svg.height or 0) or 1000.0
    rect = fit_rect(int(vw), int(vh), area)
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    ss = 2  # supersampling for smooth anti-aliased edges
    scale = w / vw

    full = np.zeros((h * ss, w * ss, 3), np.uint8)
    full_a = np.zeros((h * ss, w * ss), np.uint8)
    line = np.zeros((h * ss, w * ss, 3), np.uint8)
    line_a = np.zeros((h * ss, w * ss), np.uint8)
    strokes: list[Stroke] = []
    stroke_seg: list[int] = []
    fills: list[tuple[list[np.ndarray], int]] = []   # (polygons in drawing px, segment)
    cues: list[str | None] = [None]
    current: str | None = None

    for el in svg.elements():
        if not isinstance(el, Shape):
            continue
        if str(el.values.get("visibility", "")).lower() == "hidden" or \
                str(el.values.get("display", "")).lower() == "none":
            continue
        stroke_c = _svg_color(el.stroke)
        fill_c = _svg_color(el.fill)
        if stroke_c is None and fill_c is None:
            continue
        cue = (el.values.get("data-word") or "").strip() or None
        if cue is not None and cue != current:
            current = cue
            if strokes or fills or cues[-1] is not None:
                cues.append(cue)
            else:
                cues[-1] = cue
        seg_i = len(cues) - 1
        try:
            sw = float(el.implicit_stroke_width if hasattr(el, "implicit_stroke_width") else el.stroke_width)
        except Exception:
            sw = 1.0
        width_px = max(1.0, sw * scale * thickness)
        subs = [_sample_subpath(sp, scale, 0, 0) for sp in SvgPath(el).as_subpaths()]
        subs = [s for s in subs if len(s) >= 2]
        if not subs:
            continue
        if fill_c is not None:
            polys = [np.round(s * ss).astype(np.int32) for s in subs if len(s) >= 3]
            if polys:
                color = tuple(int(c) for c in fill_c[:3])
                cv2.fillPoly(full, polys, color, lineType=cv2.LINE_AA)
                cv2.fillPoly(full_a, polys, 255, lineType=cv2.LINE_AA)
                fills.append(([s for s in subs if len(s) >= 3], seg_i))
        if stroke_c is not None:
            color = tuple(int(c) for c in stroke_c[:3])
            t = max(1, int(round(width_px * ss)))
            for s in subs:
                pts = np.round(s * ss).astype(np.int32)
                cv2.polylines(full, [pts], False, color, t, cv2.LINE_AA)
                cv2.polylines(full_a, [pts], False, 255, t, cv2.LINE_AA)
                cv2.polylines(line, [pts], False, color, t, cv2.LINE_AA)
                cv2.polylines(line_a, [pts], False, 255, t, cv2.LINE_AA)
                # Reveal exactly the stroke itself (+AA edge), so crossing strokes do not peek through.
                r = np.full(len(s), width_px / 2 + 0.8, dtype=np.float32)
                strokes.append(Stroke(s.astype(np.float32), r))
                stroke_seg.append(seg_i)

    def down(img):
        return cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)

    full_rgb = down(full).astype(np.float32)
    line_rgb = down(line).astype(np.float32)
    fa = down(full_a).astype(np.float32) / 255
    la = down(line_a).astype(np.float32) / 255
    # Un-premultiply colours at anti-aliased edges (they were drawn on black).
    full_rgb = full_rgb / np.maximum(fa[..., None], 1e-3)
    line_rgb = line_rgb / np.maximum(la[..., None], 1e-3)
    full_rgb = np.clip(full_rgb, 0, 255)
    line_rgb = np.clip(line_rgb, 0, 255)

    # Each fill is coloured where it is still visible (later shapes cover earlier ones).
    diag = float(np.hypot(w, h))
    covered = np.zeros((h, w), np.uint8)
    visible: list[tuple[np.ndarray, int]] = []
    for polys, seg_i in reversed(fills):
        m = np.zeros((h * ss, w * ss), np.uint8)
        cv2.fillPoly(m, [np.round(p * ss).astype(np.int32) for p in polys], 255, lineType=cv2.LINE_AA)
        m = down(m)
        vis = cv2.multiply(m, 255 - covered, scale=1 / 255)
        np.maximum(covered, m, out=covered)
        visible.append((vis, seg_i))
    visible.reverse()
    regions: list[ColorRegion] = []
    min_area = max(6, int(0.00002 * w * h))
    for i, (vis, seg_i) in enumerate(visible):
        hard = vis > 127
        if int(hard.sum()) < min_area:
            continue
        region = _make_region(hard, diag, angle, seed=w * 17 + h + i, segment=seg_i)
        if region is not None:
            regions.append(region)

    segments: list[Segment] = []
    if len(cues) > 1 or cues[0] is not None:
        for si, cue in enumerate(cues):
            s_idx = [k for k, s in enumerate(stroke_seg) if s == si]
            r_idx = [k for k, r in enumerate(regions) if r.segment == si]
            s_rng = (s_idx[0], s_idx[-1] + 1) if s_idx else (len([s for s in stroke_seg if s < si]),) * 2
            r_rng = (r_idx[0], r_idx[-1] + 1) if r_idx else (len([r for r in regions if r.segment < si]),) * 2
            segments.append(Segment(cue, s_rng, r_rng))
    # Colouring of each part starts where that part's outline ended.
    for seg in (segments or [Segment(None, (0, len(strokes)), (0, len(regions)))]):
        a, b = seg.strokes
        pen = tuple(strokes[b - 1].points[-1]) if b > a else (w / 2, h / 2)
        _chain(regions[seg.regions[0]:seg.regions[1]], pen)

    if dark:
        full_rgb = to_chalk(full_rgb)
        line_rgb = to_chalk(line_rgb)
        la = chalk_texture(la, seed=w * 17 + h)
    return PreparedDrawing(rect, line_rgb, la, full_rgb, fa, strokes, regions, bool(regions), segments)


# ──────────────────────────────────────────────────────────────
def content_area(frame_w: int, frame_h: int, settings: dict) -> tuple[int, int, int, int]:
    """The frame minus the image margin."""
    margin = float(settings.get("image_margin", 0.05))
    mx, my = int(frame_w * margin), int(frame_h * margin)
    return mx, my, frame_w - mx, frame_h - my


def prepare(path: Path, area: tuple[int, int, int, int], settings: dict, dark: bool,
            language: str) -> PreparedDrawing:
    """Prepare an image to be drawn inside `area` (frame px)."""
    order = settings.get("stroke_order", "auto")
    if order == "auto":
        order = "right_to_left" if language == "fa" else "left_to_right"
    # Marker strokes lean like a right hand's ("/"), or the other way for a left hand.
    angle = 125.0 if settings.get("hand_mirror") else 55.0
    if path.suffix.lower() == ".svg":
        d = prepare_svg(path, area, dark, float(settings.get("line_thickness", 1.0)), angle)
    else:
        # The pen starts from the corner where reading starts.
        start = (area[2], area[1]) if order == "right_to_left" else (area[0], area[1])
        d = prepare_raster(path, area, dark, order, start, angle)
    # Strokes and marker paths in frame coordinates are easier for the compositor.
    off = np.array([d.rect[0], d.rect[1]], dtype=np.float32)
    for st in d.strokes:
        st.points = st.points + off
    for r in d.regions:
        r.paths = [p + off for p in r.paths]
    return d
