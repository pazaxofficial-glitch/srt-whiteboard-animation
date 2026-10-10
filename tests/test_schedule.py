from pathlib import Path

import numpy as np

from swa.project import DEFAULT_SETTINGS, extract_marks
from swa.render.schedule import TRAVEL, Shot, plan_shots, progress_curve, write_progress


def words(text, start, step=0.4):
    out, t = [], start
    for w in text.split():
        out.append({"w": w, "s": t, "e": t + step - 0.05})
        t += step
    return out


def timeline():
    return {"lines": [
        {"id": 1, "start": 0.5, "end": 2.0, "words": words("Life the Spartan way", 0.5)},
        {"id": 2, "start": 3.0, "end": 5.0, "words": words("A shield and a spear", 3.0)},
        {"id": 3, "start": 6.0, "end": 8.0, "words": words("No picture for this line", 6.0)},
    ]}


def test_marks():
    assert extract_marks("Life, the *Spartan* way.") == ("Life, the Spartan way.", [2])
    assert extract_marks("a *shield and spear* here") == ("a shield and spear here", [1, 2, 3])
    assert extract_marks("plain") == ("plain", [])


def test_plan_shots_timing():
    tl = timeline()
    images = {1: Path("1.png"), 2: Path("2.png")}
    settings = dict(DEFAULT_SETTINGS, text_lines="keep")
    shots = plan_shots(tl, images, settings, 9.0)
    assert [s.line_id for s in shots] == [1, 2]
    assert shots[0].start == 0.5
    assert shots[1].trans_start < 3.0
    assert shots[0].draw_end <= shots[1].trans_start


def test_text_card_for_line_without_image():
    shots = plan_shots(timeline(), {1: Path("1.png")}, dict(DEFAULT_SETTINGS), 9.0)
    card = [s for s in shots if s.line_id == 3][0]
    assert card.kind == "text" and card.image is None
    assert len(card.writes) == 5
    # Every word starts no earlier than it is spoken, in order.
    for w, nxt in zip(card.writes, card.writes[1:]):
        assert w.t0 >= card.words[w.word]["s"] - 1e-6
        assert nxt.t0 >= w.t1
    assert card.draw_end == card.writes[-1].t1


def test_marked_word_is_written_when_spoken_and_picture_pauses():
    shots = plan_shots(timeline(), {1: Path("1.png"), 2: Path("2.png")}, dict(DEFAULT_SETTINGS), 9.0, {1: [2]})
    s1 = shots[0]
    assert [w.word for w in s1.writes] == [2]
    w = s1.writes[0]
    assert abs(w.t0 - s1.words[2]["s"]) < 1e-6           # written exactly when "Spartan" is said
    assert s1.busy and s1.busy[0][0] == w.t0 - TRAVEL       # hand leaves the picture just before
    curve = progress_curve(s1, 30, "linear")
    t = s1.start + np.arange(len(curve)) / 30
    inside = (t > s1.busy[0][0] + 0.05) & (t < s1.busy[0][1] - 0.05)
    assert np.ptp(curve[inside]) < 1e-9                     # picture paused while writing
    assert curve[-1] == 1.0


def test_speech_curve_moves_with_words():
    shot = Shot(1, Path("x"), 0, 0.0, 4.0, 4.0, [{"w": "a", "s": 0.0, "e": 1.0}, {"w": "b", "s": 3.0, "e": 4.0}])
    c = progress_curve(shot, 30, "speech")
    assert c[0] == 0 and abs(c[-1] - 1) < 1e-9
    assert np.all(np.diff(c) >= 0)
    assert (c[30] - c[0]) > (c[75] - c[45]) * 1.5


def test_write_progress_is_smooth_and_bounded():
    from swa.render.schedule import WriteWindow
    w = WriteWindow(0, 1.0, 2.0)
    vals = [write_progress(w, t) for t in np.linspace(0.5, 2.5, 41)]
    assert vals[0] == 0 and vals[-1] == 1 and all(b >= a for a, b in zip(vals, vals[1:]))
