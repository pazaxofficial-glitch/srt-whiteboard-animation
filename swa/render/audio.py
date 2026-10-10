"""Sound: drawing noises that follow the pen, background music, final mix.

Everything is synthesized here (no sound files to license):
  - marker on a whiteboard / chalk on a dark board while the pen is down,
    louder when the pen moves faster, with small taps when it touches down
    and the odd marker squeak
  - a softer brush sound while colouring in
  - a whoosh for slide/fade transitions, an eraser rub for wipes

The final mix (FFmpeg): narration + drawing sounds + music that ducks under
the voice, then two-pass loudness normalization (-14 LUFS, YouTube level).
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import tempfile
import threading
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np

from .encoder import ffmpeg_path

SR = 24000          # drawing sounds have nothing above ~10 kHz
KIND = {"ink": 1, "color": 2, "write": 3}


# ──────────────────────────────────────────────────────────────
# What the pen did, frame by frame
# ──────────────────────────────────────────────────────────────
class ActivityLog:
    def __init__(self, fps: int, f_from: int, f_to: int, diag: float):
        self.fps, self.f_from = fps, f_from
        n = max(0, f_to - f_from)
        self.down = np.zeros(n, bool)
        self.kind = np.zeros(n, np.int8)
        self.speed = np.zeros(n, np.float32)       # frame diagonals per second
        self.events: list[tuple[float, str, float]] = []
        self.diag = diag
        self._prev: tuple[float, float] | None = None

    def record(self, f: int, state) -> None:
        """state = (kind, (x, y), pen_down) or None when the hand is off the board."""
        if state is None:
            self._prev = None
            return
        kind, pos, down = state
        speed = 0.0
        if self._prev is not None:
            speed = math.hypot(pos[0] - self._prev[0], pos[1] - self._prev[1]) * self.fps / self.diag
        self._prev = pos
        i = f - self.f_from
        if 0 <= i < len(self.down):
            self.down[i] = bool(down)
            self.kind[i] = KIND.get(kind, 0)
            self.speed[i] = speed

    def event(self, t: float, kind: str, duration: float) -> None:
        self.events.append((t, kind, duration))

    @property
    def duration(self) -> float:
        return len(self.down) / self.fps


# ──────────────────────────────────────────────────────────────
# Noise textures (periodic, so they loop without seams)
# ──────────────────────────────────────────────────────────────
def _shaped_noise(n: int, lo: float, hi: float, tilt: float, seed: int, sr: int = SR) -> np.ndarray:
    """Periodic noise with energy between lo and hi Hz (smooth band edges)."""
    rng = np.random.default_rng(seed)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / sr)
    band = 1 / (1 + (lo / np.maximum(f, 1)) ** 4) / (1 + (f / hi) ** 4)
    band *= (np.maximum(f, 1) / 1000.0) ** tilt
    x = np.fft.irfft(spec * band, n)
    return (x / (np.sqrt(np.mean(x ** 2)) + 1e-9)).astype(np.float32)


@lru_cache(maxsize=4)
def _textures(seed: int = 7) -> dict[str, np.ndarray]:
    n = SR * 3
    rng = np.random.default_rng(seed)
    t = np.arange(n) / SR
    # Marker: bright friction with a slightly uneven "fibre" grain.
    grain = _shaped_noise(n, 15, 60, 0, seed + 1)
    marker = _shaped_noise(n, 1800, 7000, -0.3, seed + 2) * (0.75 + 0.25 * np.tanh(grain))
    # Chalk: broader, grittier, with crackle.
    crackle = np.zeros(n, np.float32)
    idx = rng.integers(0, n, size=int(n / SR * 380))
    crackle[idx] = rng.standard_normal(len(idx)).astype(np.float32) * 4
    crackle = np.fft.irfft(np.fft.rfft(crackle) * (1 / (1 + (2500 / np.maximum(np.fft.rfftfreq(n, 1 / SR), 1)) ** 2)), n)
    chalk = _shaped_noise(n, 700, 8500, -0.15, seed + 3) * 0.8 + crackle.astype(np.float32) * 0.6
    chalk /= np.sqrt(np.mean(chalk ** 2)) + 1e-9
    # Brush / felt colouring: soft and low.
    brush = _shaped_noise(n, 250, 2200, -0.5, seed + 4) * (0.8 + 0.2 * np.sin(2 * np.pi * 3 * t)).astype(np.float32)
    return {"marker": marker.astype(np.float32), "chalk": chalk.astype(np.float32), "brush": brush.astype(np.float32)}


def _loop(tex: np.ndarray, start: int, n: int) -> np.ndarray:
    L = len(tex)
    idx = (start + np.arange(n)) % L
    return tex[idx]


def _burst(n: int, lo: float, hi: float, seed: int) -> np.ndarray:
    return _shaped_noise(max(n, 64), lo, hi, 0, seed)[:n]


# ──────────────────────────────────────────────────────────────
# Drawing sounds
# ──────────────────────────────────────────────────────────────
def _frame_levels(log: ActivityLog, dark: bool) -> dict[str, np.ndarray]:
    speed_gain = np.clip(log.speed / 0.35, 0.0, 1.0) ** 0.6
    moving = np.clip(log.speed / 0.03, 0.0, 1.0)            # silent when the pen stands still
    down = log.down.astype(np.float32) * moving
    draw = down * (np.isin(log.kind, (KIND["ink"], KIND["write"]))) * (0.25 + 0.75 * speed_gain)
    color = down * (log.kind == KIND["color"]) * (0.3 + 0.7 * speed_gain)
    if dark:
        return {"chalk": draw * 0.9, "marker": np.zeros_like(draw), "brush": color * 0.0, "chalk_color": color * 0.45}
    return {"marker": draw, "chalk": np.zeros_like(draw), "brush": color * 0.6, "chalk_color": np.zeros_like(draw)}


def _per_sample(levels: np.ndarray, fps: int, a: int, n: int) -> np.ndarray:
    """Frame levels -> smooth per-sample envelope for samples [a, a+n)."""
    k = int(SR * 0.012)            # ~12 ms moving average: no clicks at pen up/down
    pad = k
    t = (a - pad + np.arange(n + 2 * pad)) / SR * fps
    env = np.interp(t, np.arange(len(levels)), levels, left=0.0, right=0.0).astype(np.float64)
    c = np.concatenate([[0.0], np.cumsum(env)])
    sm = (c[k:] - c[:-k]) / k
    off = pad - k // 2
    return sm[off:off + n].astype(np.float32)


def _events(log: ActivityLog, dark: bool, seed: int = 11) -> list[tuple[int, np.ndarray]]:
    """One-shot sounds: pen taps, marker squeaks, transition whooshes and erasers."""
    rng = np.random.default_rng(seed)
    out: list[tuple[int, np.ndarray]] = []
    spf = SR / log.fps
    down = log.down
    # Taps where the pen touches down after a lift.
    up_run = 0
    for i, d in enumerate(down):
        if not d:
            up_run += 1
            continue
        if up_run >= 2 and log.kind[i] in (KIND["ink"], KIND["write"]):
            n = int(SR * 0.012)
            env = np.exp(-np.arange(n) / (SR * 0.0025)).astype(np.float32)
            out.append((int(i * spf), _burst(n, 900, 5000, int(rng.integers(1 << 30))) * env * 0.55))
        up_run = 0
    # Marker squeaks (light boards only), rare and short.
    if not dark:
        for i in np.nonzero(down & (log.speed > 0.18) & (log.kind != KIND["color"]))[0]:
            if rng.random() < 0.012:
                n = int(SR * rng.uniform(0.04, 0.11))
                tt = np.arange(n) / SR
                f0 = rng.uniform(1900, 3100)
                f = f0 * (1 + rng.uniform(-0.12, 0.12) * tt / tt[-1])
                ph = 2 * np.pi * np.cumsum(f) / SR
                env = np.sin(np.pi * np.arange(n) / n) ** 2
                tone = (np.sin(ph) + 0.3 * np.sin(2 * ph)) * env * 0.12
                out.append((int(i * spf), tone.astype(np.float32)))
    # Transitions.
    for t, kind, dur in log.events:
        n = int(SR * max(0.25, dur))
        q = np.linspace(0, 1, n, dtype=np.float32)
        lo_b = _burst(n, 200, 900, int(rng.integers(1 << 30)))
        hi_b = _burst(n, 1500, 6000, int(rng.integers(1 << 30)))
        if kind == "erase":
            rub = 0.6 + 0.4 * np.sin(2 * np.pi * 7 * q * dur) ** 2
            snd = (lo_b * 0.5 + hi_b * 0.5) * rub * np.sin(np.pi * q) ** 0.7 * 0.28
        else:
            sweep = q ** 1.5
            snd = (lo_b * (1 - sweep) + hi_b * sweep) * np.sin(np.pi * q) ** 2 * 0.3
        out.append((int((t - log.f_from / log.fps) * SR), snd.astype(np.float32)))
    return out


def write_sfx(log: ActivityLog, dark: bool, volume: float, path: Path, chunk_s: float = 20.0) -> Path:
    """Render the drawing sounds for the whole log into a mono WAV (streamed in chunks)."""
    tex = _textures()
    levels = _frame_levels(log, dark)
    total = int(log.duration * SR)
    events = _events(log, dark)
    gain = 0.12 * 2.0 * float(np.clip(volume, 0.0, 1.5))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        a = 0
        step = int(chunk_s * SR)
        while a < total:
            n = min(step, total - a)
            buf = np.zeros(n, np.float32)
            for name, lv in levels.items():
                if not lv.any():
                    continue
                src = tex["chalk"] if name == "chalk_color" else tex[name]
                env = _per_sample(lv, log.fps, a, n)
                if env.any():
                    buf += _loop(src, a, n) * env
            for pos, snd in events:
                lo, hi = max(a, pos), min(a + n, pos + len(snd))
                if lo < hi:
                    buf[lo - a:hi - a] += snd[lo - pos:hi - pos]
            buf = np.tanh(buf * gain * 1.2) / 1.2
            wf.writeframes((np.clip(buf, -1, 1) * 32767).astype("<i2").tobytes())
            a += n
    return path


# ──────────────────────────────────────────────────────────────
# Final mix
# ──────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _amix_has_normalize() -> bool:
    try:
        out = subprocess.run([ffmpeg_path(), "-hide_banner", "-h", "filter=amix"], capture_output=True, text=True)
        return "normalize" in out.stdout
    except Exception:
        return False


def _run(cmd: list[str], cancel: threading.Event | None = None) -> str:
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace")
    _out, err = proc.communicate()
    if cancel is not None and cancel.is_set():
        raise RuntimeError("Cancelled")
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg audio step failed: {err.strip()[-800:]}")
    return err


def _measure_loudness(path: Path, target: float = -14.0, start: float | None = None,
                      duration: float | None = None) -> dict | None:
    """EBU R128 measurement (FFmpeg loudnorm, first pass). None for silence."""
    cmd = [ffmpeg_path(), "-hide_banner", "-nostats"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    if duration:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-i", str(path), "-af", f"loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"]
    err = _run(cmd)
    m = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", err, re.S)
    if not m:
        return None
    data = json.loads(m[-1])
    try:
        if not math.isfinite(float(data["input_i"])) or float(data["input_i"]) < -70:
            return None
    except (KeyError, ValueError):
        return None
    return data


def loudness(path: Path, start: float | None = None, duration: float | None = None) -> float | None:
    m = _measure_loudness(path, start=start, duration=duration)
    return float(m["input_i"]) if m else None


_LOUDNESS_CACHE: dict[tuple[str, float, int], float | None] = {}


def cached_loudness(path: Path) -> float | None:
    st = path.stat()
    key = (str(path), st.st_mtime, st.st_size)
    if key not in _LOUDNESS_CACHE:
        _LOUDNESS_CACHE[key] = loudness(path)
    return _LOUDNESS_CACHE[key]


def sfx_offset_db(volume: float) -> float:
    """Drawing sounds relative to the voice: 0.5 -> 16 dB quieter."""
    return -26.0 + 20.0 * float(volume)


def music_offset_db(volume: float) -> float:
    """Music (before ducking) relative to the voice: 0.3 -> 15 dB quieter."""
    return -24.0 + 30.0 * float(volume)


def music_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                          "default=noprint_wrappers=1:nokey=1", str(path)], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def finalize(video: Path, out: Path, narration: Path | None, log: ActivityLog, settings: dict, dark: bool,
             t_from: float, t_to: float, cancel: threading.Event | None = None) -> Path:
    """Mux the silent render with narration, drawing sounds and music."""
    from .music import resolve_music

    ff = ffmpeg_path()
    D = log.duration
    use_sfx = bool(settings.get("sfx", True)) and float(settings.get("sfx_volume", 0.5)) > 0
    music = resolve_music(settings.get("music", "none"))
    mvol = float(settings.get("music_volume", 0.35))
    normalize = bool(settings.get("normalize_audio", True))
    target = float(settings.get("loudness", -14.0))

    if narration is None and not use_sfx and music is None:
        shutil.move(str(video), str(out))
        return out

    tmp = Path(tempfile.mkdtemp(prefix="swa-audio-"))
    try:
        # Levels are relative to the voice, so any microphone gives the same balance.
        voice = loudness(narration, t_from or None, D) if narration is not None else None
        voice = voice if voice is not None else -20.0
        inputs: list[str] = []
        labels: list[str] = []
        graph: list[str] = []
        idx = 0
        fmt = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
        nar_label = None
        if narration is not None:
            inputs += ["-ss", f"{t_from:.3f}", "-t", f"{D:.3f}", "-i", str(narration)]
            # Pad to the full length so the music ducking does not stop with the voice.
            graph.append(f"[{idx}:a]{fmt},apad=whole_dur={D:.3f}[nar]")
            nar_label = "nar"
            idx += 1
        if use_sfx:
            sfx = write_sfx(log, dark, 1.0, tmp / "sfx.wav")
            level = loudness(sfx)
            if level is not None:
                gain = 10 ** ((voice + sfx_offset_db(float(settings.get("sfx_volume", 0.5))) - level) / 20)
                inputs += ["-i", str(sfx)]
                graph.append(f"[{idx}:a]{fmt},volume={gain:.5f}[sfx]")
                labels.append("[sfx]")
                idx += 1
        if music is not None and mvol > 0:
            mlen = music_duration(music) or 1.0
            inputs += ["-stream_loop", "-1", "-ss", f"{t_from % mlen:.3f}", "-t", f"{D:.3f}", "-i", str(music)]
            fade_out = max(0.0, D - 2.5)
            mlevel = cached_loudness(music)
            mgain = 10 ** ((voice + music_offset_db(mvol) - mlevel) / 20) if mlevel is not None else 0.2
            graph.append(f"[{idx}:a]{fmt},volume={mgain:.5f},"
                         f"afade=t=in:st=0:d={min(1.5, D / 3):.2f},afade=t=out:st={fade_out:.2f}:d={min(2.5, D):.2f}[mus]")
            idx += 1
            duck = float(np.clip(settings.get("ducking", 0.7), 0.0, 1.0))
            if nar_label and duck > 0:
                graph.append("[nar]asplit=2[nar1][key]")
                graph.append(f"[mus][key]sidechaincompress=threshold=0.03:ratio={2 + 10 * duck:.2f}:"
                             f"attack=25:release=450:makeup=1[duck]")
                nar_label = "nar1"
                labels.append("[duck]")
            else:
                labels.append("[mus]")
        if nar_label:
            labels.insert(0, f"[{nar_label}]")
        if len(labels) > 1:
            norm = ":normalize=0" if _amix_has_normalize() else ""
            graph.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:dropout_transition=0{norm}"
                         + ("" if norm else f",volume={len(labels)}") + "[mix]")
        else:
            graph.append(f"{labels[0]}anull[mix]")
        mix = tmp / "mix.wav"
        _run([ff, "-hide_banner", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(graph),
              "-map", "[mix]", "-c:a", "pcm_s16le", "-ar", "48000", str(mix)], cancel)

        af: list[str] = []
        if normalize:
            m = _measure_loudness(mix, target)  # second pass below applies it linearly
            if m is not None:
                af = ["-af", (f"loudnorm=I={target}:TP=-1.5:LRA=11:measured_I={m['input_i']}:"
                              f"measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
                              f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")]
        _run([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-i", str(mix),
              "-map", "0:v", "-map", "1:a", "-c:v", "copy", *af, "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
              "-movflags", "+faststart", str(out)], cancel)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def sfx_preview(dark: bool, volume: float, path: Path) -> Path:
    """A few seconds of drawing sounds for the settings page."""
    fps = 30
    n = fps * 4
    log = ActivityLog(fps, 0, n, 2200.0)
    rng = np.random.default_rng(3)
    t = np.arange(n) / fps
    for i in range(n):
        phase = t[i] % 1.3
        down = phase < 1.0 and t[i] < 3.4
        kind = "color" if t[i] > 2.6 else "ink"
        log.down[i] = down
        log.kind[i] = KIND[kind]
        log.speed[i] = (0.25 + 0.2 * np.sin(t[i] * 9) + 0.05 * rng.random()) if down else 0.0
    return write_sfx(log, dark, volume, path)

