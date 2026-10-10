"""Background music: your own tracks, or built-in ones composed in code.

The built-in tracks are generated on first use (a few seconds) and cached:
  calm    72 BPM, A minor   soft pad, kalimba arpeggios, warm bass
  bright  100 BPM, C major  marimba, light drums, bouncy bass
  focus   84 BPM, D minor   lo-fi electric piano, brushed drums, vinyl
Each track is a seamless loop: note tails and reverb wrap around the end,
so FFmpeg can repeat it for any video length.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

from .. import paths
from .encoder import ffmpeg_path

SR = 44100
VERSION = 1
MUSIC_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus"}
BUILTIN = {
    "calm": "Calm",
    "bright": "Bright",
    "focus": "Focus",
}


def music_dir() -> Path:
    return paths.DATA / "music"


def list_music() -> list[dict]:
    items = [{"id": f"builtin:{k}", "name": v, "builtin": True} for k, v in BUILTIN.items()]
    d = music_dir()
    if d.exists():
        for p in sorted(d.iterdir()):
            if p.is_file() and p.suffix.lower() in MUSIC_EXTS:
                items.append({"id": f"file:{p.name}", "name": p.stem, "builtin": False})
    return items


def resolve_music(choice: str | None) -> Path | None:
    """Path of the chosen track (generating a built-in one if needed), or None."""
    if not choice or choice == "none":
        return None
    if choice.startswith("builtin:"):
        style = choice.split(":", 1)[1]
        if style not in BUILTIN:
            return None
        cache = music_dir() / ".builtin" / f"{style}-v{VERSION}.m4a"
        if not cache.exists():
            cache.parent.mkdir(parents=True, exist_ok=True)
            _encode(generate(style), cache)
        return cache
    if choice.startswith("file:"):
        p = music_dir() / Path(choice.split(":", 1)[1]).name
        return p if p.exists() else None
    return None


def _encode(stereo: np.ndarray, dst: Path) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="swa-music-"))
    try:
        wav = tmp / "m.wav"
        with wave.open(str(wav), "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(SR)
            wf.writeframes((np.clip(stereo, -1, 1) * 32767).astype("<i2").tobytes())
        part = dst.with_suffix(".part.m4a")
        subprocess.run([ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav),
                        "-c:a", "aac", "-b:a", "192k", str(part)], check=True)
        shutil.move(str(part), str(dst))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ──────────────────────────────────────────────────────────────
# Synthesis helpers
# ──────────────────────────────────────────────────────────────
def hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


class Track:
    """A stereo buffer where notes wrap around the end (seamless loop)."""

    def __init__(self, seconds: float):
        self.n = int(seconds * SR)
        self.buf = np.zeros((2, self.n), np.float32)

    def add(self, t: float, sig: np.ndarray, pan: float = 0.0, gain: float = 1.0) -> None:
        start = int(t * SR) % self.n
        L = np.float32(np.cos((pan + 1) * np.pi / 4) * gain)
        R = np.float32(np.sin((pan + 1) * np.pi / 4) * gain)
        sig = sig.astype(np.float32)
        pos = 0
        while pos < len(sig):
            a = (start + pos) % self.n
            k = min(len(sig) - pos, self.n - a)
            self.buf[0, a:a + k] += sig[pos:pos + k] * L
            self.buf[1, a:a + k] += sig[pos:pos + k] * R
            pos += k


def _env(n: int, attack: float, decay_tau: float, release: float = 0.05, hold: float | None = None) -> np.ndarray:
    t = np.arange(n) / SR
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    d = np.exp(-t / decay_tau) if decay_tau > 0 else np.ones(n)
    env = a * d
    if hold is not None:
        r = np.clip((hold + release - t) / max(release, 1e-4), 0, 1)
        env *= r
    return env.astype(np.float32)


def kalimba(f: float, dur: float = 1.6, seed: int = 0) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(seed)
    det = 1 + rng.uniform(-0.0015, 0.0015)
    sig = (np.sin(2 * np.pi * f * det * t) * np.exp(-t / 0.75)
           + 0.22 * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t / 0.25)
           + 0.07 * np.sin(2 * np.pi * 5.4 * f * t) * np.exp(-t / 0.06))
    return (sig * np.clip(t / 0.004, 0, 1)).astype(np.float32)


def marimba(f: float, dur: float = 1.0) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    sig = (np.sin(2 * np.pi * f * t) * np.exp(-t / 0.45)
           + 0.35 * np.sin(2 * np.pi * 4 * f * t) * np.exp(-t / 0.05)
           + 0.12 * np.sin(2 * np.pi * 9.2 * f * t) * np.exp(-t / 0.02))
    return (sig * np.clip(t / 0.002, 0, 1)).astype(np.float32)


def epiano(f: float, dur: float = 1.8) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    trem = 1 + 0.12 * np.sin(2 * np.pi * 4.5 * t)
    sig = (np.sin(2 * np.pi * f * t + 0.6 * np.sin(2 * np.pi * f * t) * np.exp(-t / 0.3))
           * np.exp(-t / 1.1) + 0.18 * np.sin(2 * np.pi * 3 * f * t) * np.exp(-t / 0.18))
    return (sig * trem * _env(n, 0.006, 0, 0.3, dur - 0.3)).astype(np.float32)


def pad(freqs: list[float], dur: float, bright: float = 1.0) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    sig = np.zeros(n, np.float64)
    for f in freqs:
        for det in (-0.004, 0.0, 0.004):
            for k in range(1, 7):
                sig += np.sin(2 * np.pi * f * (1 + det) * k * t + k * 1.7) / (k ** (2.2 - 0.4 * bright))
    sig /= len(freqs) * 3 * 1.6
    env = np.clip(t / 1.2, 0, 1) * np.clip((dur - t) / 1.4, 0, 1)
    return (sig * env).astype(np.float32)


def bass(f: float, dur: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    sig = np.sin(2 * np.pi * f * t) + 0.18 * np.sin(2 * np.pi * 2 * f * t)
    return (sig * _env(n, 0.012, 0, 0.08, max(0.05, dur - 0.08))).astype(np.float32)


def kick(gain: float = 1.0) -> np.ndarray:
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    f = 45 + 75 * np.exp(-t / 0.035)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return (np.sin(ph) * np.exp(-t / 0.13) * gain).astype(np.float32)


def noise_hit(dur: float, lo: float, hi: float, tau: float, seed: int) -> np.ndarray:
    n = int(dur * SR)
    rng = np.random.default_rng(seed)
    spec = np.fft.rfft(rng.standard_normal(n))
    fr = np.fft.rfftfreq(n, 1 / SR)
    band = 1 / (1 + (lo / np.maximum(fr, 1)) ** 4) / (1 + (fr / hi) ** 4)
    x = np.fft.irfft(spec * band, n)
    x /= np.abs(x).max() + 1e-9
    t = np.arange(n) / SR
    return (x * np.exp(-t / tau)).astype(np.float32)


def reverb(buf: np.ndarray, seconds: float = 2.2, wet: float = 0.22, seed: int = 5) -> np.ndarray:
    """Circular convolution reverb: the tail wraps around, keeping the loop seamless."""
    n = buf.shape[1]
    rng = np.random.default_rng(seed)
    m = int(seconds * SR)
    t = np.arange(m) / SR
    out = np.empty_like(buf)
    for ch in range(2):
        ir = rng.standard_normal(m) * np.exp(-t / (seconds / 6.9))
        ir[: int(0.012 * SR)] *= np.linspace(0, 1, int(0.012 * SR))
        ir /= np.sqrt(np.sum(ir ** 2))
        full = np.zeros(n)
        full[: min(m, n)] = ir[: min(m, n)]
        wet_sig = np.fft.irfft(np.fft.rfft(buf[ch]) * np.fft.rfft(full), n)
        out[ch] = buf[ch] * (1 - wet) + wet_sig * wet * 1.8
    return out.astype(np.float32)


def master(buf: np.ndarray, rms_db: float = -17.0) -> np.ndarray:
    buf = buf - buf.mean(axis=1, keepdims=True)
    rms = np.sqrt(np.mean(buf ** 2)) + 1e-9
    buf = buf * (10 ** (rms_db / 20) / rms)
    buf = np.tanh(buf * 1.1) / np.tanh(1.1)
    peak = np.abs(buf).max()
    if peak > 0.95:
        buf *= 0.95 / peak
    return buf.T.copy()


# ──────────────────────────────────────────────────────────────
# Compositions
# ──────────────────────────────────────────────────────────────
def generate(style: str, repeats: int = 3, seed: int = 1) -> np.ndarray:
    """Stereo float32 (samples, 2) seamless loop."""
    rng = np.random.default_rng(seed)
    if style == "bright":
        bpm, prog = 100, [(36, [60, 64, 67]), (43, [59, 62, 67]), (45, [60, 64, 69]), (41, [60, 65, 69])]
    elif style == "focus":
        bpm, prog = 84, [(38, [62, 65, 69, 72]), (46, [58, 62, 65, 69]), (41, [60, 64, 65, 69]), (48, [60, 64, 67, 71])]
    else:
        style = "calm"
        bpm, prog = 72, [(45, [57, 60, 64]), (41, [53, 57, 60]), (48, [55, 60, 64]), (43, [55, 59, 62])]
    beat = 60.0 / bpm
    bar = 4 * beat
    loop = 8 * bar
    tr = Track(loop * repeats)

    for r in range(repeats):
        base = r * loop
        for ci, (root, chord) in enumerate(prog):
            t0 = base + ci * 2 * bar
            if style == "calm":
                tr.add(t0, pad([hz(m) for m in chord], 2 * bar + 1.2, bright=0.6), 0.0, 0.32)
                tr.add(t0, bass(hz(root), 2 * bar - 0.1), 0.0, 0.42)
                pattern = [0, 1, 2, 1, 3, 2, 1, 2] if r != 1 else [0, 2, 1, 3, 2, 1, 2, 0]
                tones = chord + [chord[0] + 12]
                for b in range(2):
                    for k in range(8):
                        if r == 0 and b == 0 and k in (5, 7):
                            continue
                        if rng.random() < 0.12:
                            continue
                        m = tones[pattern[k] % len(tones)] + 12
                        vel = 0.5 + 0.2 * rng.random() + (0.15 if k == 0 else 0)
                        tr.add(t0 + b * bar + k * beat / 2 + rng.uniform(-0.006, 0.006),
                               kalimba(hz(m), seed=int(rng.integers(1 << 30))), rng.uniform(-0.5, 0.5), 0.22 * vel)
            elif style == "bright":
                tr.add(t0, pad([hz(m) for m in chord], 2 * bar + 0.8, bright=0.9), 0.0, 0.14)
                tones = chord + [chord[0] + 12, chord[1] + 12]
                for b in range(2):
                    bt = t0 + b * bar
                    for k in range(8):
                        m = tones[(k + (b * 2) + r) % len(tones)] + 12
                        tr.add(bt + k * beat / 2, marimba(hz(m)), -0.35 + 0.1 * (k % 3), 0.26 * (0.7 + 0.3 * rng.random()))
                    for k, (off, length) in enumerate([(0, 0.9), (2, 0.9), (3.5, 0.45)]):
                        note = root + (7 if k == 2 else 0)
                        tr.add(bt + off * beat, bass(hz(note), length * beat), 0.0, 0.5)
                    for k in (0, 2):
                        tr.add(bt + k * beat, kick(), 0.0, 0.55)
                    for k in (1, 3):
                        tr.add(bt + k * beat, noise_hit(0.25, 900, 3500, 0.05, int(rng.integers(1 << 30))), 0.1, 0.18)
                    for k in range(16):
                        tr.add(bt + k * beat / 4, noise_hit(0.06, 5000, 12000, 0.012, int(rng.integers(1 << 30))),
                               0.4, 0.05 + (0.03 if k % 2 == 0 else 0))
            else:  # focus
                swing = beat / 2 * 0.16
                for b in range(2):
                    bt = t0 + b * bar
                    for hit, vel in ((0.0, 0.32), (1.5 * beat + swing, 0.24), (3.0 * beat, 0.18)):
                        for j, m in enumerate(chord):
                            tr.add(bt + hit + j * 0.012, epiano(hz(m)), -0.2 + 0.13 * j, vel * 0.55)
                    tr.add(bt, bass(hz(root), 1.8 * beat), 0.0, 0.45)
                    tr.add(bt + 2.5 * beat + swing, bass(hz(root + 7), 1.2 * beat), 0.0, 0.35)
                    for k in (0, 2.5):
                        tr.add(bt + k * beat + (swing if k % 1 else 0), kick(0.8), 0.0, 0.5)
                    for k in (1, 3):
                        tr.add(bt + k * beat, noise_hit(0.18, 1200, 5000, 0.04, int(rng.integers(1 << 30))), 0.0, 0.14)
                    for k in range(8):
                        tr.add(bt + k * beat / 2 + (swing if k % 2 else 0),
                               noise_hit(0.05, 6000, 11000, 0.015, int(rng.integers(1 << 30))), 0.3, 0.06)
    if style == "focus":
        # Vinyl crackle and a gentle low-pass for the lo-fi feel.
        crackle = np.zeros(tr.n, np.float32)
        idx = rng.integers(0, tr.n, size=int(tr.n / SR * 6))
        crackle[idx] = rng.uniform(-1, 1, len(idx)).astype(np.float32)
        tr.buf += crackle * 0.05
        spec = np.fft.rfft(tr.buf, axis=1)
        f = np.fft.rfftfreq(tr.n, 1 / SR)
        tr.buf = np.fft.irfft(spec / (1 + (f / 5500) ** 2), tr.n, axis=1).astype(np.float32)
    wet = {"calm": 0.3, "bright": 0.16, "focus": 0.2}[style]
    return master(reverb(tr.buf, 2.6 if style == "calm" else 1.6, wet))
