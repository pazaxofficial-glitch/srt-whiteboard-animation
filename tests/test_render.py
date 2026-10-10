import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from swa.project import DEFAULT_SETTINGS, Project
from swa.render.backgrounds import BUILTIN, make_background
from swa.render.compositor import DrawState, frame_size, plan_shots, progress_curve, render_project
from swa.render.drawing import prepare

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
def test_prepare_and_finish(name):
    d = prepare(DEMO / "images" / name, 640, 360, dict(DEFAULT_SETTINGS), False, "en")
    assert d.strokes, "pen strokes were found"
    assert d.color_paths, "colouring sweeps were found"
    bg, _ = make_background("white", 640, 360)
    board = bg.copy()
    st = DrawState(d, board, bg, "ink_then_color", 0.7, (0, 0))
    st.advance(0.5)
    half = np.abs(board.astype(int) - bg).sum()
    st.advance(1.0)
    st.finish()
    full = np.abs(board.astype(int) - bg).sum()
    assert 0 < half < full


def test_dark_board_turns_ink_light():
    d = prepare(DEMO / "images" / "1.svg", 640, 360, dict(DEFAULT_SETTINGS), True, "en")
    lines = d.line_rgb[d.line_a > 0.8]
    assert lines.mean() > 150  # dark strokes became chalk


def test_plan_shots_timing():
    tl = {"lines": [{"id": 1, "start": 0.5, "end": 2.0, "words": []},
                    {"id": 2, "start": 3.0, "end": 5.0, "words": []},
                    {"id": 3, "start": 6.0, "end": 8.0, "words": []}]}
    images = {1: Path("1.png"), 3: Path("3.png")}
    shots = plan_shots(tl, images, dict(DEFAULT_SETTINGS), 9.0)
    assert [s.line_id for s in shots] == [1, 3]
    assert shots[0].start == 0.5
    assert shots[1].start == 6.0
    assert shots[1].trans_start < 6.0
    assert shots[0].draw_end <= shots[1].trans_start


def test_speech_curve_moves_with_words():
    from swa.render.compositor import Shot
    shot = Shot(1, Path("x"), 0, 0.0, 4.0, [{"s": 0.0, "e": 1.0}, {"s": 3.0, "e": 4.0}])
    c = progress_curve(shot, 30, "speech")
    assert c[0] == 0 and abs(c[-1] - 1) < 1e-9
    assert np.all(np.diff(c) >= 0)
    # Faster while speaking (0-1 s) than in the pause (1.5-2.5 s).
    assert (c[30] - c[0]) > (c[75] - c[45]) * 1.5


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_render_demo(tmp_path):
    root = tmp_path / "demo"
    shutil.copytree(DEMO, root)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono",
                    "-t", "6", str(root / "narration.wav")], check=True)
    proj = Project.load(root)
    proj.settings.update(resolution=360, fps=12, quality="draft", transition="fade")
    proj.save()
    from swa.align import align_project
    align_project(proj, "estimate")
    out = render_project(proj, tmp_path / "out.mp4")
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                            "default=nw=1:nk=1", str(out)], capture_output=True, text=True, check=True)
    assert abs(float(probe.stdout) - 6.6) < 0.3
