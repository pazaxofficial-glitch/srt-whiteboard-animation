"""Helpers for reviewing a project's images (used by the CLI and by AI agents)."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .project import Project
from .render.imageio import imwrite


def contact_sheet(project: Project, out: Path | None = None, line_range: tuple[int, int] | None = None,
                  cols: int = 4, tile_w: int = 400) -> Path:
    """Grid of finished frames (board + drawing) with line numbers, as one PNG."""
    from .render.compositor import still_frame

    images, _ = project.images()
    ids = sorted(images)
    if line_range:
        ids = [i for i in ids if line_range[0] <= i <= line_range[1]]
    if not ids:
        raise ValueError("No images to show.")
    tiles = []
    for i in ids:
        img = still_frame(project, i, overrides={"hand": "none"}, max_width=tile_w)
        cv2.rectangle(img, (0, 0), (64, 30), (124, 58, 237), -1)
        cv2.putText(img, str(i), (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
        tiles.append(img)
    th, tw = tiles[0].shape[:2]
    rows = (len(tiles) + cols - 1) // cols
    sheet = np.full((rows * (th + 8) + 8, min(cols, len(tiles)) * (tw + 8) + 8, 3), 40, np.uint8)
    for k, tile in enumerate(tiles):
        r, c = divmod(k, cols)
        y, x = 8 + r * (th + 8), 8 + c * (tw + 8)
        sheet[y:y + tile.shape[0], x:x + tile.shape[1]] = tile
    out = out or project.root / "contact-sheet.png"
    imwrite(out, sheet)
    return out


def lint_svgs(project: Project) -> list[str]:
    """Problems that make an SVG draw badly. Empty list = all good."""
    from svgelements import SVG, Shape, Text

    problems: list[str] = []
    images, _ = project.images()
    for n in [ln.id for ln in project.lines()]:
        p = images.get(n)
        if p is None or p.suffix.lower() != ".svg":
            continue
        try:
            svg = SVG.parse(str(p), reify=True)
        except Exception as exc:
            problems.append(f"{p.name}: cannot be parsed ({exc})")
            continue
        strokes = fills = texts = black_fills = 0
        for el in svg.elements():
            if isinstance(el, Text):
                texts += 1
            elif isinstance(el, Shape):
                stroked = el.stroke is not None and el.stroke.value is not None
                filled = el.fill is not None and el.fill.value is not None
                strokes += stroked
                fills += filled
                if filled and not stroked and str(el.fill).lower() in ("#000000", "black"):
                    black_fills += 1
        if texts:
            problems.append(f"{p.name}: has {texts} <text> element(s); text is not drawn — write letters as paths")
        if strokes == 0:
            problems.append(f"{p.name}: no stroked shapes; the pen has nothing to draw (add stroke=\"#222\")")
        if black_fills:
            problems.append(f"{p.name}: {black_fills} shape(s) filled black without a stroke — "
                            "forgot fill=\"none\"? (SVG fills shapes black by default)")
        if not svg.viewbox:
            problems.append(f"{p.name}: no viewBox; use viewBox=\"0 0 1600 900\"")
    return problems
