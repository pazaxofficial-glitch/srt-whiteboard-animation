import shutil
import subprocess
import wave

import numpy as np
import pytest

from swa.render import audio, music


def read_wav(path):
    with wave.open(str(path)) as wf:
        data = np.frombuffer(wf.readframes(wf.getnframes()), "<i2").astype(np.float32) / 32767
        return data.reshape(-1, wf.getnchannels()), wf.getframerate()


def test_drawing_sounds_follow_the_pen(tmp_path):
    fps, n = 30, 90
    log = audio.ActivityLog(fps, 0, n, 2200.0)
    for f in range(n):
        down = 30 <= f < 60
        log.record(f, ("ink", (100 + f * 12.0, 300.0), down))
    out = audio.write_sfx(log, False, 1.0, tmp_path / "sfx.wav")
    x, sr = read_wav(out)
    x = x[:, 0]
    assert abs(len(x) / sr - 3.0) < 0.01
    rms = lambda a, b: np.sqrt(np.mean(x[int(a * sr):int(b * sr)] ** 2))
    assert rms(1.2, 1.8) > 20 * rms(0.2, 0.8)              # loud while drawing, quiet otherwise
    assert rms(2.3, 2.9) < rms(1.2, 1.8) / 20


def test_music_loops_seamlessly():
    y = music.generate("calm", repeats=1)
    assert y.ndim == 2 and y.shape[1] == 2
    assert np.abs(y).max() <= 0.96
    # The end flows into the start: the jump at the loop point is no bigger than a normal sample step.
    step = np.abs(np.diff(y[:, 0])).max()
    assert abs(y[0, 0] - y[-1, 0]) <= step * 1.5


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_final_mix_is_normalized(tmp_path, monkeypatch):
    monkeypatch.setattr(music, "music_dir", lambda: tmp_path / "music")
    fps, secs = 25, 8
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=white:s=320x180:d={secs}:r={fps}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
    voice = tmp_path / "voice.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=6",
                    "-af", "volume=0.05", str(voice)], check=True)
    log = audio.ActivityLog(fps, 0, fps * secs, 400.0)
    for f in range(fps * secs):
        log.record(f, ("ink", (f * 3.0, 50.0), f % 20 < 14))
    out = tmp_path / "out.mp4"
    settings = {"sfx": True, "sfx_volume": 0.5, "music": "builtin:focus", "music_volume": 0.3, "ducking": 0.7,
                "normalize_audio": True, "loudness": -14.0}
    audio.finalize(video, out, voice, log, settings, False, 0.0, float(secs))
    level = audio.loudness(out)
    assert level is not None and abs(level - (-14.0)) < 1.0
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                "default=nw=1:nk=1", str(out)], capture_output=True, text=True).stdout)
    assert abs(dur - secs) < 0.2
