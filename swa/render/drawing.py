"""Prepare one image for drawing: layers to reveal + the pen's route.

Every image (PNG/JPG/WebP or SVG) becomes a `PreparedDrawing`:
  line layer  what the pen reveals first (outlines / dark line art)
  full layer  the finished, coloured picture
  strokes     ordered polylines the pen tip follows
  colour path brush sweeps used while colouring in
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .imageio import imread
from .strokes import Stroke, label_objects, order_groups, order_strokes, strokes_from_mask, zigzag


@dataclass
class PreparedDrawing:
    rect: tuple[int, int, int, int]       # x0, y0, x1, y1 in frame pixels
    line_rgb: np.ndarray                  # (h, w, 3) float32
    line_a: np.ndarray                    # (h, w) float32 0..1
    full_rgb: np.ndarray                  # (h, w, 3) float32
    full_a: np.ndarray                    # (h, w) float32 0..1
    strokes: list[Stroke]
    color_paths: list[tuple[np.ndarray, float]] = field(default_factory=list)  # (points, radius)

    @property
    def size(self) -> tuple[int, int]:
        return self.line_a.shape[1], self.line_a.shape[0]


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
                   order: str, start: tuple[float, float]) -> PreparedDrawing:
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
    if dark:
        full_rgb = to_chalk(full_rgb)
        line_rgb = full_rgb
        line_a = chalk_texture(line_a, seed=w * 31 + h)
        full_a = np.clip(full_a * 0.92, 0, 1)

    gap = max(9, int(0.012 * (w + h)))
    labels, stats = label_objects(ink | (fg > 0.5), gap)
    group_order = order_groups(stats, order)
    local_start = (start[0] - rect[0], start[1] - rect[1])
    strokes = order_strokes(strokes_from_mask(ink, labels), group_order, local_start)
    color_paths = _color_paths(stats, group_order, w, h)
    return PreparedDrawing(rect, line_rgb, line_a.astype(np.float32), full_rgb, full_a.astype(np.float32),
                           strokes, color_paths)


def _color_paths(stats: np.ndarray, group_order: list[int], w: int, h: int):
    """One back-and-forth brush sweep per object (colour only shows where the picture is)."""
    radius = max(10.0, min(w, h) / 16)
    paths = []
    for g in group_order:
        x, y, bw, bh, area = (int(v) for v in stats[g])
        if area < 20:
            continue
        paths.append((zigzag(x, y, x + bw - 1, y + bh - 1, radius), radius))
    return paths


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


def prepare_svg(path: Path, area: tuple[int, int, int, int], dark: bool,
                thickness: float = 1.0) -> PreparedDrawing:
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
    fills: list[tuple[np.ndarray, float]] = []
    fill_radius = max(10.0, min(w, h) / 18)

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
                allp = np.concatenate(subs)
                x0, y0 = allp.min(axis=0)
                x1, y1 = allp.max(axis=0)
                fills.append((zigzag(int(x0), int(y0), int(x1), int(y1), fill_radius), fill_radius))
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
    if dark:
        full_rgb = to_chalk(full_rgb)
        line_rgb = to_chalk(line_rgb)
        la = chalk_texture(la, seed=w * 17 + h)
    return PreparedDrawing(rect, line_rgb, la, full_rgb, fa, strokes, fills)


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
    if path.suffix.lower() == ".svg":
        d = prepare_svg(path, area, dark, float(settings.get("line_thickness", 1.0)))
    else:
        # The pen starts from the corner where reading starts.
        start = (area[2], area[1]) if order == "right_to_left" else (area[0], area[1])
        d = prepare_raster(path, area, dark, order, start)
    # Strokes and sweeps in frame coordinates are easier for the compositor.
    x0, y0 = d.rect[0], d.rect[1]
    for st in d.strokes:
        st.points = st.points + np.array([x0, y0], dtype=np.float32)
    d.color_paths = [(p + np.array([x0, y0], dtype=np.float32), r) for p, r in d.color_paths]
    return d
