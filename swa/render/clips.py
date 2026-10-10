"""Video clips as pictures: a line can play an animation instead of being drawn.

Any MP4/WebM/MOV named by its line number (12.webm) plays on the board while
that line is spoken: an animated chart or motion graphic made with
HyperFrames or Remotion, a screen recording, a short film. Transparent clips
(WebM with alpha, ProRes 4444 MOV) sit on the board as they are; a clip with
a plain background colour has that colour keyed out, so the board shows
through. On dark boards the colours turn into chalk like every drawing.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from ..project import CLIP_EXTS
from .drawing import fit_rect, to_chalk
from .encoder import ffmpeg_path


def is_clip(path: Path | None) -> bool:
    return path is not None and path.suffix.lower() in CLIP_EXTS


def _ffprobe() -> str:
    exe = ffmpeg_path()
    probe = Path(exe).with_name(Path(exe).name.replace("ffmpeg", "ffprobe"))
    return str(probe) if probe.exists() else "ffprobe"


@lru_cache(maxsize=1)
def _has_libvpx() -> bool:
    try:
        out = subprocess.run([ffmpeg_path(), "-hide_banner", "-decoders"], capture_output=True, text=True).stdout
    except (OSError, RuntimeError):
        return False
    return "libvpx-vp9" in out


def probe(path: Path) -> tuple[int, int, float]:
    """Width, height and duration (seconds) of a clip."""
    out = subprocess.run([_ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    st = data["streams"][0]
    return int(st["width"]), int(st["height"]), float(data.get("format", {}).get("duration") or 0.0)


@dataclass
class PreparedClip:
    rect: tuple[int, int, int, int]       # x0, y0, x1, y1 in frame pixels
    path: Path
    duration: float
    dark: bool
    still_at: float = 0.0                 # where a still preview is taken from (seconds)


def prepare_clip(path: Path, area: tuple[int, int, int, int], dark: bool) -> PreparedClip:
    w, h, dur = probe(path)
    return PreparedClip(fit_rect(w, h, area), path, dur, dark)


class ClipReader:
    """Decodes a clip at the video's frame rate and size, one frame after another.

    After the last frame it keeps returning that frame (the clip holds).
    """

    def __init__(self, clip: PreparedClip, fps: int, start: float = 0.0):
        x0, y0, x1, y1 = clip.rect
        self.w, self.h = x1 - x0, y1 - y0
        self.clip = clip
        cmd = [ffmpeg_path(), "-hide_banner", "-loglevel", "error"]
        if clip.path.suffix.lower() == ".webm" and _has_libvpx():
            cmd += ["-c:v", "libvpx-vp9"]          # the VP9 decoder that keeps transparency
        if start > 0:
            cmd += ["-ss", f"{start:.3f}"]
        cmd += ["-i", str(clip.path), "-an", "-vf", f"fps={fps},scale={self.w}:{self.h}:flags=area",
                "-f", "rawvideo", "-pix_fmt", "bgra", "-"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.index = -1
        self.last: tuple[np.ndarray, np.ndarray] | None = None
        self.key: np.ndarray | None = None     # background colour to key out (decided on frame 0)
        self.ended = False

    def _read(self) -> np.ndarray | None:
        n = self.w * self.h * 4
        buf = self.proc.stdout.read(n) if self.proc.stdout else b""
        if len(buf) < n:
            self.ended = True
            return None
        return np.frombuffer(buf, np.uint8).reshape(self.h, self.w, 4)

    def _convert(self, bgra: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        rgb = bgra[:, :, :3].astype(np.float32)
        alpha = bgra[:, :, 3].astype(np.float32) / 255.0
        if self.key is None:
            self.key = np.zeros(0)
            if alpha.min() > 0.99:               # opaque: key out a plain background colour
                m = max(2, min(self.w, self.h) // 60)
                border = np.concatenate([rgb[:m].reshape(-1, 3), rgb[-m:].reshape(-1, 3),
                                         rgb[:, :m].reshape(-1, 3), rgb[:, -m:].reshape(-1, 3)])
                bg = np.median(border, axis=0)
                if np.median(np.abs(border - bg).sum(axis=1)) < 24:
                    self.key = bg
        if self.key.size:
            dist = np.abs(rgb - self.key).sum(axis=2)
            alpha = np.minimum(alpha, np.clip((dist - 24) / 50, 0, 1))
        if self.clip.dark:
            rgb = to_chalk(rgb)
        return rgb, alpha.astype(np.float32)

    def frame(self, k: int) -> tuple[np.ndarray, np.ndarray] | None:
        """Frame number k (0 = the clip's start). Frames only move forward."""
        newest = None
        while self.index < k and not self.ended:
            raw = self._read()
            if raw is None:
                break
            self.index += 1
            newest = raw
        if newest is not None:
            self.last = self._convert(newest)
        return self.last

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
        if self.proc.stdout:
            self.proc.stdout.close()
        self.proc.wait()
