"""Drawing hands: a transparent PNG plus the pixel where the pen touches the board.

Each hand is a folder with `hand.png` (transparent background) and
`hand.json`:  {"name": "Marker", "tip": [x, y], "size": 0.46}
`tip` is the pen tip in PNG pixels, `size` the hand height as a share of the
video height.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import cv2
import numpy as np

from .. import paths
from ..project import slugify
from .imageio import imread


def hand_dirs() -> list[Path]:
    out = []
    for base in (paths.BUILTIN_HANDS, paths.USER_HANDS):
        if base.exists():
            out += sorted(d for d in base.iterdir() if (d / "hand.png").exists())
    return out


def list_hands() -> list[dict]:
    items = []
    for d in hand_dirs():
        meta = _meta(d)
        items.append({"id": d.name, "name": meta.get("name", d.name), "tip": meta.get("tip"),
                      "size": meta.get("size", 0.46), "builtin": d.parent == paths.BUILTIN_HANDS})
    return items


def find_hand(hand_id: str) -> Path | None:
    for d in hand_dirs():
        if d.name == hand_id:
            return d
    return None


def _meta(d: Path) -> dict:
    p = d / "hand.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {}


def guess_tip(png: np.ndarray) -> list[int]:
    """Best guess for the pen tip: the opaque pixel furthest to the top-left."""
    alpha = png[:, :, 3] if png.shape[2] == 4 else (cv2.cvtColor(png, cv2.COLOR_BGR2GRAY) < 245).astype(np.uint8) * 255
    ys, xs = np.nonzero(alpha > 128)
    if len(xs) == 0:
        return [0, 0]
    k = int(np.argmin(xs + ys))
    return [int(xs[k]), int(ys[k])]


def save_hand(src: Path, name: str, tip: list[int] | None = None, size: float = 0.46) -> str:
    """Add an uploaded hand to the user's library. Returns its id."""
    paths.USER_HANDS.mkdir(parents=True, exist_ok=True)
    img = imread(src)
    if img is None:
        raise ValueError("Could not read the hand image.")
    if img.shape[2] == 3:
        # No transparency: treat near-white as background.
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        alpha = np.where(gray > 242, 0, 255).astype(np.uint8)
        alpha = cv2.GaussianBlur(alpha, (3, 3), 0)
        img = np.dstack([img, alpha])
    base = slugify(name) or "hand"
    hid, i = base, 2
    while find_hand(hid) is not None:
        hid = f"{base}-{i}"
        i += 1
    d = paths.USER_HANDS / hid
    d.mkdir(parents=True)
    ok, buf = cv2.imencode(".png", img)
    buf.tofile(str(d / "hand.png"))
    meta = {"name": name, "tip": tip or guess_tip(img), "size": size}
    (d / "hand.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return hid


def update_hand(hand_id: str, **fields) -> None:
    d = find_hand(hand_id)
    if d is None or d.parent != paths.USER_HANDS:
        raise ValueError("Only your own hands can be changed.")
    meta = _meta(d)
    meta.update({k: v for k, v in fields.items() if v is not None})
    (d / "hand.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def delete_hand(hand_id: str) -> None:
    d = find_hand(hand_id)
    if d is None or d.parent != paths.USER_HANDS:
        raise ValueError("Built-in hands cannot be deleted.")
    shutil.rmtree(d)


class HandSprite:
    """A hand scaled for one video size, ready to paste onto frames."""

    def __init__(self, hand_dir: Path, base: int, scale: float = 1.0, frame_h: int | None = None):
        """`base` is the frame's shorter side; hand size is relative to it."""
        frame_h = frame_h or base
        meta = _meta(hand_dir)
        png = imread(hand_dir / "hand.png")
        if png is None:
            raise FileNotFoundError(hand_dir / "hand.png")
        if png.shape[2] == 3:
            png = np.dstack([png, np.full(png.shape[:2], 255, np.uint8)])
        tip = meta.get("tip") or guess_tip(png)
        alpha = png[:, :, 3]
        ys, xs = np.nonzero(alpha > 8)
        x0, y0, x1, y1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
        png = png[y0:y1, x0:x1]
        tip = (tip[0] - x0, tip[1] - y0)
        target_h = max(8, int(base * float(meta.get("size", 0.46)) * scale))
        s = target_h / png.shape[0]
        png = cv2.resize(png, (max(1, int(png.shape[1] * s)), target_h),
                         interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        self.tip = (int(round(tip[0] * s)), int(round(tip[1] * s)))
        # If the arm runs off the bottom of the PNG, continue it so it never
        # ends in the middle of the frame.
        bottom = png[-1:, :, :]
        if (bottom[0, :, 3] > 128).mean() > 0.08:
            png = np.concatenate([png, np.repeat(bottom, frame_h, axis=0)], axis=0)
        a = png[:, :, 3:4].astype(np.float32) / 255.0
        self.premul = png[:, :, :3].astype(np.float32) * a
        self.inv_alpha = 1.0 - a
        self.h, self.w = png.shape[:2]

    def paste(self, frame: np.ndarray, x: float, y: float) -> None:
        """Paste so that the pen tip lands on (x, y). Modifies `frame` in place."""
        fh, fw = frame.shape[:2]
        left = int(round(x)) - self.tip[0]
        top = int(round(y)) - self.tip[1]
        fx0, fy0 = max(0, left), max(0, top)
        fx1, fy1 = min(fw, left + self.w), min(fh, top + self.h)
        if fx0 >= fx1 or fy0 >= fy1:
            return
        sx0, sy0 = fx0 - left, fy0 - top
        sx1, sy1 = sx0 + (fx1 - fx0), sy0 + (fy1 - fy0)
        region = frame[fy0:fy1, fx0:fx1].astype(np.float32)
        region *= self.inv_alpha[sy0:sy1, sx0:sx1]
        region += self.premul[sy0:sy1, sx0:sx1]
        frame[fy0:fy1, fx0:fx1] = region.astype(np.uint8)
