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


def _extend_arm(png: np.ndarray, tip: tuple[float, float], length: int) -> tuple[np.ndarray, tuple[float, float]]:
    """Continue an arm that leaves the bottom of the PNG, following its slant."""
    alpha = png[:, :, 3]
    if (alpha[-1] > 128).mean() <= 0.08 or len(png) < 8:
        return png, tip

    def centre(row: np.ndarray) -> float | None:
        xs = np.nonzero(row > 128)[0]
        return float(xs.mean()) if len(xs) else None

    look = min(len(png) - 1, max(4, len(png) // 8))
    c1, c0 = centre(alpha[-1]), centre(alpha[-1 - look])
    slope = 0.0 if c1 is None or c0 is None else float(np.clip((c1 - c0) / look, -1.0, 1.0))
    h, w = png.shape[:2]
    drift = int(round(abs(slope) * length)) + 2
    left_pad = drift if slope < 0 else 0
    out = np.zeros((h + length, w + drift, 4), np.uint8)
    out[:h, left_pad:left_pad + w] = png
    bottom = png[-1]
    for k in range(length):
        x = left_pad + int(round(slope * (k + 1)))
        out[h + k, x:x + w] = bottom
    return out, (tip[0] + left_pad, tip[1])


class HandRig:
    """A hand scaled for one video size that moves like a real one.

    The PNG is rotated around the pen tip (so the tip always stays on the
    line): the arm swings with the tip position, flexes a little while
    drawing and leans into the stroke direction. Between strokes the hand
    lifts (a bit larger, shadow further away). A soft shadow falls on the
    board. `mirror` turns it into a left hand.
    """

    def __init__(self, hand_dir: Path, frame_w: int, frame_h: int, scale: float = 1.0,
                 mirror: bool = False, motion: bool = True, shadow: bool = True):
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
        base = min(frame_w, frame_h)
        target_h = max(8, int(base * float(meta.get("size", 0.46)) * scale))
        s = target_h / png.shape[0]
        png = cv2.resize(png, (max(1, int(png.shape[1] * s)), target_h),
                         interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        tip = (tip[0] * s, tip[1] * s)
        # If the arm runs off the bottom of the PNG, continue it along its own
        # direction so it never ends in the middle of the frame (also when the
        # hand rotates).
        png, tip = _extend_arm(png, tip, int(frame_h * 1.2))
        if mirror:
            png = np.ascontiguousarray(png[:, ::-1])
            tip = (png.shape[1] - 1 - tip[0], tip[1])
        self.sprite = png
        self.tip = tip
        self.W, self.H = frame_w, frame_h
        self.mirror = mirror
        self.motion = motion
        self.shadow = shadow
        self.reset()

    def reset(self) -> None:
        self._angle: float | None = None
        self._lift = 1.0
        self._prev: tuple[float, float] | None = None
        self._vx = 0.0

    @property
    def offscreen(self) -> tuple[float, float]:
        """A resting point outside the frame where the hand waits."""
        return (self.W * (0.18 if self.mirror else 0.82), self.H * 1.12)

    # ── pose ──────────────────────────────────────────────
    def _target_angle(self, x: float, y: float, t: float, down: bool) -> float:
        if not self.motion:
            return 0.0
        side = -1.0 if self.mirror else 1.0
        # Reaching away from the shoulder (bottom right) swings the forearm flatter.
        reach = (self.W * 0.6 - x) / (self.W * 0.6) if not self.mirror else (x - self.W * 0.4) / (self.W * 0.6)
        angle = 9.0 * float(np.clip(reach, -1.0, 1.4)) + 4.0 * float(np.clip(y / self.H - 0.5, -0.6, 0.6))
        flex = 1.0 * np.sin(2 * np.pi * 0.9 * t) + 0.45 * np.sin(2 * np.pi * 2.3 * t + 1.3)
        angle += flex * (1.0 if down else 0.5)
        angle += float(np.clip(-self._vx / self.W * 4.0, -3.0, 3.0))
        return side * angle

    def draw(self, frame: np.ndarray, x: float, y: float, t: float, down: bool, dt: float) -> None:
        """Paste the hand with its tip at (x, y), updating its smooth motion state."""
        if self._prev is not None and dt > 0:
            vx = (x - self._prev[0]) / dt
            self._vx += (vx - self._vx) * min(1.0, dt / 0.15)
        self._prev = (x, y)
        target = self._target_angle(x, y, t, down)
        k = 1.0 - np.exp(-dt / 0.12) if dt > 0 else 1.0
        self._angle = target if self._angle is None else self._angle + (target - self._angle) * k
        lift_target = 0.0 if down else 1.0
        self._lift += (lift_target - self._lift) * (1.0 - np.exp(-dt / 0.06) if dt > 0 else 1.0)
        self.paste(frame, x, y, self._angle, self._lift)

    def paste(self, frame: np.ndarray, x: float, y: float, angle: float = 0.0, lift: float = 0.0) -> None:
        """Rotate the sprite around its tip by `angle` degrees and composite it at (x, y)."""
        fh, fw = frame.shape[:2]
        sh, sw = self.sprite.shape[:2]
        scale = 1.0 + 0.025 * lift
        M = cv2.getRotationMatrix2D(self.tip, angle, scale)
        M[0, 2] += x - self.tip[0]
        M[1, 2] += y - self.tip[1]
        corners = np.array([[0, 0, 1], [sw, 0, 1], [0, sh, 1], [sw, sh, 1]], np.float64) @ M.T
        dx = int(fw * (0.006 + 0.012 * lift)) if self.shadow else 0
        dy = int(fh * (0.010 + 0.016 * lift)) if self.shadow else 0
        x0 = max(0, int(np.floor(corners[:, 0].min())))
        y0 = max(0, int(np.floor(corners[:, 1].min())))
        x1 = min(fw, int(np.ceil(corners[:, 0].max())) + dx + 1)
        y1 = min(fh, int(np.ceil(corners[:, 1].max())) + dy + 1)
        if x0 >= x1 or y0 >= y1:
            return
        Mr = M.copy()
        Mr[0, 2] -= x0
        Mr[1, 2] -= y0
        roi_w, roi_h = x1 - x0, y1 - y0
        warped = cv2.warpAffine(self.sprite, Mr, (roi_w, roi_h), flags=cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
        a = cv2.multiply(warped[:, :, 3], 1 / 255, dtype=cv2.CV_32F)
        region = np.ascontiguousarray(frame[y0:y1, x0:x1])
        if self.shadow and dy < roi_h and dx < roi_w:
            # Soft shadow: blurred silhouette, shifted down-right, at quarter resolution.
            q = 4
            small = cv2.resize(a, (max(1, roi_w // q), max(1, roi_h // q)), interpolation=cv2.INTER_AREA)
            small = cv2.GaussianBlur(small, (0, 0), 2.5 + 2.5 * lift)
            sha = cv2.resize(small, (roi_w, roi_h), interpolation=cv2.INTER_LINEAR)
            keep = np.ones_like(sha)
            keep[dy:, dx:] -= (0.22 - 0.07 * lift) * sha[:roi_h - dy, :roi_w - dx]
            region = cv2.blendLinear(region, np.zeros_like(region), keep, 1.0 - keep)
        frame[y0:y1, x0:x1] = cv2.blendLinear(np.ascontiguousarray(warped[:, :, :3]), region, a, 1.0 - a)
