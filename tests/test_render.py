import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from swa.project import DEFAULT_SETTINGS, Project
from swa.render.backgrounds import BUILTIN, make_background
from swa.render.board import Board
from swa.render.compositor import frame_size, render_project, shot_layout
from swa.render.drawing import content_area, prepare
from swa.render.scene import ShotScene
from swa.render.schedule import Shot

DEMO = Path(__file__).resolve().parent.parent / "examples" / "demo"


def test_frame_sizes():
    assert frame_size({"aspect": "16:9", "resolution": 1080}) == (1920, 1080)
    assert frame_size({"aspect": "9:16", "resolution": 720}) == (720, 1280)
    assert frame_size({"aspect": "1:1", "resolution": 720}) == (720, 720)


@pytest.mark.parametrize("kind", list(BUILTIN))
def test_backgrounds(kind):
    img, dark = make_background(kind, 320, 180)
    assert img.shape == (180, 320, 3)
    assert dark == BUILTIN[kind][1]


@pytest.mark.parametrize("name", ["1.svg", "2.png"])
def test_prepare_and_draw(name):
    settings = dict(DEFAULT_SETTINGS)
    d = prepare(DEMO / "images" / name, content_area(640, 360, settings), settings, False, "en")
    assert d.strokes, "pen strokes were found"
    assert d.color_paths, "colouring sweeps were found"
    bg, _ = make_background("white", 640, 360)
    board = Board(bg)
    shot = Shot(1, DEMO / "images" / name, 0.0, 0.0, 2.0, 2.0)
    scene = ShotScene(shot, board, d, None, "ink_then_color", 0.7, 30, "linear")
    st = scene.update(1.0)
    assert st is not None and st.kind in ("ink", "color")
    half = np.abs(board.img.astype(int) - bg).sum()
    scene.update(2.0)
    scene.finish()
    full = np.abs(board.img.astype(int) - bg).sum()
    assert 0 < half < full


def test_dark_board_turns_ink_light():
    settings = dict(DEFAULT_SETTINGS)
    d = prepare(DEMO / "images" / "1.svg", content_area(640, 360, settings), settings, True, "en")
    lines = d.line_rgb[d.line_a > 0.8]
    assert lines.mean() > 150  # dark strokes became chalk


def test_layout_keeps_text_and_captions_apart():
    settings = dict(DEFAULT_SETTINGS)
    shot = Shot(1, Path("1.png"), 0, 0, 2, 2, words=[{"w": "a", "s": 0, "e": 1}], write_words=[0])
    shot.writes = [object()]
    lay = shot_layout(shot, 1920, 1080, settings, caption_band=(950, 1080))
    assert lay.image_area[3] <= lay.text_area[1]          # picture above the written words
    assert lay.text_area[3] <= 950                         # words above the captions


def _demo_project(tmp_path: Path, seconds: float = 6.0) -> Project:
    root = tmp_path / "demo"
    shutil.copytree(DEMO, root)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=180",
                    "-t", str(seconds), "-af", "volume=0.3", str(root / "narration.wav")], check=True)
    return Project.load(root)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_render_demo(tmp_path):
    proj = _demo_project(tmp_path)
    proj.script_path.write_text("1. Life, the *Spartan* way.\n2. A shield and a spear.\n3. Training.\n"
                                "4. No picture here, so this line is written.\n", encoding="utf-8")
    proj.settings.update(resolution=360, fps=12, quality="draft", transition="fade", captions="highlight",
                         music="none", sfx=True)
    proj.save()
    from swa.align import align_project
    align_project(proj, "estimate")
    out = render_project(proj, tmp_path / "out.mp4")
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type:format=duration",
                            "-of", "default=nw=1", str(out)], capture_output=True, text=True, check=True).stdout
    assert "codec_type=video" in probe and "codec_type=audio" in probe
    dur = float(probe.split("duration=")[1].split()[0])
    assert abs(dur - 6.6) < 0.3
    assert (tmp_path / "out.srt").exists()
    assert not (tmp_path / "out.video.mp4").exists()
