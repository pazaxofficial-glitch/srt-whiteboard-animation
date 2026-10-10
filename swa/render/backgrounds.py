"""Board surfaces: whiteboard, white, paper, chalkboard, blackboard or a custom image."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .imageio import imread

BUILTIN = {
    # name: (base BGR, dark?)
    "whiteboard": ((246, 247, 245), False),
    "white": ((255, 255, 255), False),
    "paper": ((215, 235, 245), False),     # warm cream #F5EBD7
    "chalkboard": ((58, 74, 46), True),     # deep green #2E4A3A
    "blackboard": ((34, 31, 30), True),     # near black #1E1F22
}


def _noise(h: int, w: int, scale: float, seed: int) -> np.ndarray:
    """Smooth noise in [-1, 1] at a given feature size (pixels)."""
    rng = np.random.default_rng(seed)
    sh, sw = max(2, int(h / scale)), max(2, int(w / scale))
    small = rng.standard_normal((sh, sw)).astype(np.float32)
    big = cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)
    m = np.abs(big).max() or 1.0
    return big / m


def make_background(kind: str, width: int, height: int, custom_dir: Path | None = None) -> tuple[np.ndarray, bool]:
    """Return (BGR uint8 board, is_dark)."""
    if kind.startswith("custom:"):
        name = kind.split(":", 1)[1]
        path = (custom_dir / name) if custom_dir else Path(name)
        img = imread(path)
        if img is None:
            raise FileNotFoundError(f"Background image not found: {path}")
        img = img[:, :, :3]
        ih, iw = img.shape[:2]
        s = max(width / iw, height / ih)
        img = cv2.resize(img, (int(np.ceil(iw * s)), int(np.ceil(ih * s))), interpolation=cv2.INTER_AREA)
        y0 = (img.shape[0] - height) // 2
        x0 = (img.shape[1] - width) // 2
        img = np.ascontiguousarray(img[y0:y0 + height, x0:x0 + width])
        lum = float(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).mean())
        return img, lum < 110

    base, dark = BUILTIN.get(kind, BUILTIN["whiteboard"])
    h, w = height, width
    board = np.empty((h, w, 3), dtype=np.float32)
    board[:] = base

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    nx, ny = xx / w - 0.5, yy / h - 0.5
    vignette = 1.0 - 0.9 * (nx ** 2 + ny ** 2)  # 1 in the middle, ~0.78 in corners

    if kind == "whiteboard":
        # Glossy board: soft diagonal sheen + faint ghosting of old marker.
        sheen = np.exp(-((nx * 0.8 + ny * 1.2 + 0.1) ** 2) / 0.02) * 6
        ghost = _noise(h, w, 260, 7) * 2.2
        board += (sheen + ghost)[..., None]
        board *= (0.965 + 0.035 * vignette)[..., None]
    elif kind == "paper":
        grain = _noise(h, w, 3, 11) * 4 + _noise(h, w, 90, 12) * 5
        board += grain[..., None]
        board *= (0.94 + 0.06 * vignette)[..., None]
    elif dark:
        # Chalk dust: wide smudges and fine dust.
        smudge = np.clip(_noise(h, w, 220, 21), 0, 1) * 16 + np.clip(_noise(h, w, 60, 22), 0, 1) * 6
        dust = _noise(h, w, 2, 23) * 3
        board += (smudge + dust)[..., None]
        board *= (0.8 + 0.2 * vignette)[..., None]
    return np.clip(board, 0, 255).astype(np.uint8), dark
