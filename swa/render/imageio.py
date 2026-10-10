"""Image loading that works with non-ASCII (e.g. Persian) Windows paths."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def imread(path: str | Path, flags: int = cv2.IMREAD_UNCHANGED) -> np.ndarray | None:
    """Read an image as BGR or BGRA. cv2.imread fails on non-ASCII Windows paths."""
    path = Path(path)
    if not path.exists():
        return None
    raw = np.fromfile(str(path), dtype=np.uint8)
    if raw.size == 0:
        return None
    img = cv2.imdecode(raw, flags)
    if img is None:
        try:  # WebP/other formats OpenCV may lack
            from PIL import Image
            with Image.open(path) as im:
                im = im.convert("RGBA")
                arr = np.array(im)
                img = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGRA)
        except Exception:
            return None
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.dtype != np.uint8:
        img = (img / (img.max() or 1) * 255).astype(np.uint8)
    return img


def imwrite(path: str | Path, img: np.ndarray) -> None:
    path = Path(path)
    ok, buf = cv2.imencode(path.suffix or ".png", img)
    if not ok:
        raise IOError(f"Could not encode {path}")
    buf.tofile(str(path))
