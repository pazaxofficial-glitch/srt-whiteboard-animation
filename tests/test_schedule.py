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
    settings = dict(DEFAULT_SETTINGS, short_lines="draw")      # line 1 is only 2.5 s long
    shots = plan_shots(timeline(), {1: Path("1.png"), 2: Path("2.png")}, settings, 9.0, {1: [2]})
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


def short_timeline():
    return {"lines": [
        {"id": 1, "start": 0.5, "end": 1.9, "words": words("Life the Spartan way", 0.5, 0.35)},
        {"id": 2, "start": 2.5, "end": 7.0, "words": words("A shield and a spear", 2.5, 0.8)},
    ]}


def test_short_line_appears_without_drawing():
    from swa.render.schedule import APPEAR
    shots = plan_shots(short_timeline(), {1: Path("1.png"), 2: Path("2.png")}, dict(DEFAULT_SETTINGS), 8.0, {1: [2]})
    s1, s2 = shots
    assert s1.mode == "appear" and s1.kind == "image" and not s1.busy
    assert abs((s1.image_end - s1.start) - APPEAR) < 1e-6
    assert abs(s1.writes[0].t0 - s1.words[2]["s"]) < 1e-6        # the marked word appears when spoken
    assert s2.mode == "draw"                                       # 4.5 s is long enough to draw


def test_short_line_as_text_and_threshold():
    images = {1: Path("1.png"), 2: Path("2.png")}
    text = plan_shots(short_timeline(), images, dict(DEFAULT_SETTINGS, short_lines="text"), 8.0)
    assert text[0].kind == "text" and text[0].mode == "appear" and len(text[0].writes) == 4
    drawn = plan_shots(short_timeline(), images, dict(DEFAULT_SETTINGS, short_lines="draw"), 8.0)
    assert drawn[0].mode == "draw"
    longer = plan_shots(short_timeline(), images, dict(DEFAULT_SETTINGS, short_threshold=6.0), 8.0)
    assert [s.mode for s in longer] == ["appear", "appear"]


def test_mix_transition_varies_and_is_stable():
    from swa.render.schedule import MIX
    lines = [{"id": i, "start": i * 4.0, "end": i * 4.0 + 3, "words": words("one two three", i * 4.0)} for i in range(1, 13)]
    images = {i: Path(f"{i}.png") for i in range(1, 13)}
    settings = dict(DEFAULT_SETTINGS, transition="mix")
    kinds = [s.trans_kind for s in plan_shots({"lines": lines}, images, settings, 60.0)]
    assert kinds == [s.trans_kind for s in plan_shots({"lines": lines}, images, settings, 60.0)]
    assert set(kinds) <= {k for k, _ in MIX} and len(set(kinds)) >= 3
    assert all(a != b for a, b in zip(kinds, kinds[1:]))
    fade = plan_shots({"lines": lines}, images, dict(DEFAULT_SETTINGS, transition="fade"), 60.0)
    assert {s.trans_kind for s in fade} == {"fade"}


def test_timed_part_waits_for_its_word():
    shot = Shot(1, Path("x.svg"), 0, 0.0, 6.0, 6.0, words("one two three four five six", 0.0, 1.0))
    c = progress_curve(shot, 30, "linear", anchors=[(4.5, 0.5)])
    t = np.arange(len(c)) / 30
    assert c[0] == 0 and c[-1] == 1 and np.all(np.diff(c) >= -1e-12)
    assert c[t < 4.5].max() <= 0.5 + 1e-9                  # the second part waits for its word
    assert np.ptp(c[(t > 3.4) & (t < 4.4)]) < 1e-9          # first part done at its own pace; the pen rests
    assert c[np.searchsorted(t, 5.0)] > 0.6                 # then the second part catches up in time


def test_cue_words_are_found_in_order():
    from swa.render.schedule import cue_indices
    ws = words("A shield, and a spear and another shield", 0.0)
    assert cue_indices(["shield", "spear", "shield"], ws) == [1, 4, 7]
    assert cue_indices(["Spears", "2", "missing", None], ws) == [4, 1, None, None]
