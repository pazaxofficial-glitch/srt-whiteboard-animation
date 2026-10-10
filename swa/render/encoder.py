"""Stream raw frames into FFmpeg and mux the narration."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import numpy as np

QUALITY = {
    "draft": ("veryfast", "26"),
    "high": ("medium", "18"),
}


def ffmpeg_path() -> str:
    exe = os.environ.get("FFMPEG") or shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("FFmpeg was not found. Install it and make sure `ffmpeg` is on PATH "
                           "(or set the FFMPEG environment variable to its full path).")
    return exe


class VideoWriter:
    def __init__(self, out: Path, width: int, height: int, fps: int, audio: Path | None,
                 quality: str = "high", audio_start: float = 0.0, audio_duration: float | None = None):
        preset, crf = QUALITY.get(quality, QUALITY["high"])
        cmd = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
               "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}", "-r", str(fps), "-i", "-"]
        if audio is not None:
            if audio_start > 0:
                cmd += ["-ss", f"{audio_start:.3f}"]
            if audio_duration is not None:
                cmd += ["-t", f"{audio_duration:.3f}"]
            cmd += ["-i", str(audio), "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k"]
        cmd += ["-c:v", "libx264", "-preset", preset, "-crf", crf, "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(out)]
        self.out = out
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    def write(self, frame: np.ndarray) -> None:
        try:
            self.proc.stdin.write(memoryview(np.ascontiguousarray(frame)))
        except BrokenPipeError:
            err = self.proc.stderr.read().decode(errors="replace") if self.proc.stderr else ""
            raise RuntimeError(f"FFmpeg stopped: {err.strip()}")

    def close(self) -> None:
        self.proc.stdin.close()
        err = self.proc.stderr.read().decode(errors="replace") if self.proc.stderr else ""
        code = self.proc.wait()
        if code != 0:
            raise RuntimeError(f"FFmpeg failed ({code}): {err.strip()}")

    def abort(self) -> None:
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        self.proc.kill()
        self.proc.wait()
        if self.out.exists():
            self.out.unlink()
