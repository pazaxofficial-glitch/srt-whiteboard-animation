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


def _png(path: Path, colour: bool) -> Path:
    import cv2
    img = np.full((300, 400, 3), 255, np.uint8)
    if colour:
        cv2.circle(img, (130, 150), 90, (60, 170, 240), -1, cv2.LINE_AA)
        cv2.rectangle(img, (250, 80), (360, 230), (172, 124, 79), -1)
    cv2.circle(img, (130, 150), 90, (20, 20, 20), 5, cv2.LINE_AA)
    cv2.rectangle(img, (250, 80), (360, 230), (20, 20, 20), 5)
    cv2.imwrite(str(path), img)
    return path


def test_black_and_white_picture_is_not_coloured_in(tmp_path):
    settings = dict(DEFAULT_SETTINGS)
    bw = prepare(_png(tmp_path / "bw.png", False), content_area(640, 360, settings), settings, False, "en")
    col = prepare(_png(tmp_path / "c.png", True), content_area(640, 360, settings), settings, False, "en")
    assert not bw.colorful and col.colorful and len(col.regions) >= 2
    bg, _ = make_background("white", 640, 360)
    shot = Shot(1, tmp_path / "bw.png", 0.0, 0.0, 2.0, 2.0)
    kinds = lambda d, c: [p.kind for p in ShotScene(shot, Board(bg), d, None, "ink_then_color", 0.7, 30, "linear", c).parts]
    assert kinds(bw, "auto") == ["ink"]
    assert kinds(col, "auto") == ["ink", "color"]
    assert kinds(col, "off") == ["ink", "fade"]


def test_colouring_stays_inside_its_region(tmp_path):
    settings = dict(DEFAULT_SETTINGS)
    d = prepare(_png(tmp_path / "c.png", True), content_area(640, 360, settings), settings, False, "en")
    bg, _ = make_background("white", 640, 360)
    board = Board(bg)
    scene = ShotScene(Shot(1, tmp_path / "c.png", 0.0, 0.0, 3.0, 3.0), board, d, None, "ink_then_color", 0.5, 30, "linear")
    colour = [p for p in scene.parts if p.kind == "color"][0]
    first_end = colour.reveal.ends[0]
    for k in range(0, 91):                         # run until the first region is half done
        if scene.update(k / 30) and colour.reveal.effort > first_end * 0.5:
            break
    full = board.layers[1]
    allowed = np.zeros(full.mask.shape, bool)
    for r in d.regions:
        allowed[r.y0:r.y0 + r.mask.shape[0], r.x0:r.x0 + r.mask.shape[1]] |= r.mask > 0
    assert full.mask.any() and not (full.mask[~allowed] > 0).any()


def test_svg_fill_regions_exclude_shapes_on_top(tmp_path):
    svg = tmp_path / "s.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300" width="400" height="300">'
                   '<g fill="none" stroke="#222" stroke-width="6">'
                   '<circle cx="200" cy="150" r="100" fill="#D9452B"/>'
                   '<rect x="170" y="120" width="60" height="60" fill="#F3E3B0"/></g></svg>', encoding="utf-8")
    settings = dict(DEFAULT_SETTINGS, image_margin=0)
    d = prepare(svg, (0, 0, 400, 300), settings, False, "en")
    assert len(d.regions) == 2
    disk = d.regions[0]
    centre = disk.mask[150 - disk.y0, 200 - disk.x0]
    assert centre == 0 and disk.mask[150 - disk.y0, 120 - disk.x0] == 255


def test_timed_svg_parts_wait_for_their_words(tmp_path):
    svg = tmp_path / "t.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300" width="400" height="300">'
                   '<g fill="none" stroke="#222" stroke-width="8">'
                   '<path d="M40 150 L 160 150"/>'
                   '<g data-word="spear"><path d="M240 60 L 360 240"/></g></g></svg>', encoding="utf-8")
    settings = dict(DEFAULT_SETTINGS, image_margin=0)
    d = prepare(svg, (0, 0, 400, 300), settings, False, "en")
    assert [s.cue for s in d.segments] == [None, "spear"]
    ws = [{"w": w, "s": 0.5 * i, "e": 0.5 * i + 0.4} for i, w in enumerate("a shield and a spear here".split())]
    bg, _ = make_background("white", 400, 300)
    board = Board(bg)
    shot = Shot(1, svg, 0.0, 0.0, 4.0, 4.0, ws)
    scene = ShotScene(shot, board, d, None, "ink_then_color", 0.7, 30, "linear")
    spear = lambda: np.abs(board.img[60:240, 260:360].astype(int) - bg[60:240, 260:360]).sum()
    for k in range(0, 60):                          # up to 2.0 s; "spear" is said at 2.0 s
        scene.update(k / 30)
    assert spear() == 0
    for k in range(60, 121):
        scene.update(k / 30)
    assert spear() > 0


def test_short_line_fades_in_without_hand():
    settings = dict(DEFAULT_SETTINGS)
    d = prepare(DEMO / "images" / "1.svg", content_area(640, 360, settings), settings, False, "en")
    bg, _ = make_background("white", 640, 360)
    board = Board(bg)
    shot = Shot(1, DEMO / "images" / "1.svg", 0.0, 0.0, 0.35, 0.35, mode="appear")
    scene = ShotScene(shot, board, d, None, "ink_then_color", 0.7, 30, "linear")
    states = [scene.update(k / 30) for k in range(12)]
    assert all(s is None for s in states)
    assert np.abs(board.img.astype(int) - bg).sum() > 0


def test_mix_transition_frames():
    from swa.render.compositor import transition_frame
    a = np.zeros((90, 160, 3), np.uint8)
    b = np.full((90, 160, 3), 200, np.uint8)
    for kind in ("zoom", "slide_up", "slide", "fade", "wipe"):
        assert transition_frame(kind, a, b, 0.0, False).mean() < 1
        assert transition_frame(kind, a, b, 1.0, False).mean() > 199
        mid = transition_frame(kind, a, b, 0.5, False)
        assert mid.shape == a.shape and 20 < mid.mean() < 180


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_render_clip_timed_svg_and_mix(tmp_path):
    proj = _demo_project(tmp_path, seconds=9.0)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=white:s=320x180:d=3:r=12",
                    "-f", "lavfi", "-i", "color=red:s=60x60:d=3:r=12", "-filter_complex",
                    "[0][1]overlay=x='20+t*60':y=60:eval=frame", "-pix_fmt", "yuv420p",
                    str(proj.images_dir / "2.mp4")], check=True)
    (proj.images_dir / "2.png").unlink()
    (proj.images_dir / "3.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900" width="1600" height="900">'
        '<g fill="none" stroke="#222222" stroke-width="8"><path d="M200 700 L 700 300 L 1200 700"/>'
        '<g data-word="sunset"><circle cx="1300" cy="250" r="90" fill="#F2A23A"/></g></g></svg>', encoding="utf-8")
    proj.script_path.write_text("1. Life, the *Spartan* way.\n2. A clip plays here.\n"
                                "3. They trained every day until sunset.\n4. Short.\n", encoding="utf-8")
    proj.settings.update(resolution=360, fps=12, quality="draft", transition="mix", music="none", sfx=True)
    proj.save()
    from swa.align import align_project
    align_project(proj, "estimate")
    out = render_project(proj, tmp_path / "mix.mp4")
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1",
                            str(out)], capture_output=True, text=True, check=True).stdout
    assert abs(float(probe) - 9.6) < 0.3
    tl = proj.load_timeline()
    t = tl["lines"][1]["start"] + 1.0                     # one second into the clip
    frame = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(out), "-frames:v", "1",
                            "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True, check=True).stdout
    img = np.frombuffer(frame, np.uint8).reshape(360, 640, 3).astype(int)
    red = (img[:, :, 2] > 150) & (img[:, :, 1] < 90) & (img[:, :, 0] < 90)
    assert red.sum() > 200                                # the clip's red box is on the board


def test_lint_reports_unknown_data_word(tmp_path):
    from swa.tools import lint_svgs
    root = tmp_path / "p"
    (root / "images").mkdir(parents=True)
    (root / "script.txt").write_text("1. A shield and a spear.\n", encoding="utf-8")
    (root / "images" / "1.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900" width="1600" height="900">'
        '<g fill="none" stroke="#222"><g data-word="shield"><circle cx="5" cy="5" r="3"/></g>'
        '<g data-word="sword"><circle cx="9" cy="9" r="3"/></g></g></svg>', encoding="utf-8")
    problems = lint_svgs(Project.load(root))
    assert len(problems) == 1 and 'data-word="sword"' in problems[0]
