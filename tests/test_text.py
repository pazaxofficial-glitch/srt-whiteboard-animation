import numpy as np

from swa.render.captions import build_chunks, write_srt
from swa.render.handwriting import prepare_text
from swa.render.text import FONTS, FontPair, font_path, is_rtl, layout_text, render_layout, visual_order


def test_bundled_fonts_exist():
    for fid in FONTS:
        assert font_path(fid).exists()


def test_rtl_detection_ignores_digits():
    assert is_rtl("زندگی")      # Persian word
    assert not is_rtl("۱۴۰۳")        # Persian digits read left to right
    assert not is_rtl("Spartan")


def test_visual_order_mixed_line():
    fa1, fa2 = "زندگی", "با"
    words = [fa1, fa2, "Simple", "Whiteboard"]
    order = visual_order(words, base_rtl=True)
    # Left to right on screen: the English run keeps its order, Persian words are reversed.
    assert order == [2, 3, 1, 0]


def test_persian_shapes_and_renders():
    fonts = FontPair.get("marker", "naskh")
    lay = layout_text("زندگی به سبک", fonts, 60)
    assert lay.rtl and len(lay.words) == 3
    alpha, parts = render_layout(lay)
    assert alpha.max() > 0.9 and len(parts) == 3
    # Joined letters: the first word is one big connected shape, not separate letters.
    first = [p for p in parts if p[0] == 0][0][1] > 0.5
    import cv2
    n, _labels, stats, _ = cv2.connectedComponentsWithStats(first.astype(np.uint8))
    assert stats[1:, cv2.CC_STAT_AREA].max() > 0.5 * first.sum()


def test_handwriting_strokes_go_in_reading_order():
    fonts = FontPair.get("marker", "naskh")
    en = prepare_text(["Hello", "world"], fonts, (0, 0, 800, 200), "auto", False, 80)
    xs = [np.mean(s.points[:, 0]) for s in en.words[0].strokes]
    assert xs[0] < xs[-1]                                 # English: left to right
    fa = prepare_text(["زندگی"], fonts, (0, 0, 800, 200), "auto", False, 80)
    xs = [np.mean(s.points[:, 0]) for s in fa.words[0].strokes]
    assert xs[0] > xs[-1]                                 # Persian: right to left


def test_caption_chunks_and_srt(tmp_path):
    tl = {"lines": [{"id": 1, "start": 0.0, "end": 4.0, "words": [
        {"w": w, "s": i * 0.4, "e": i * 0.4 + 0.35} for i, w in enumerate("one two three four five six seven eight nine".split())]}]}
    chunks = build_chunks(tl)
    assert sum(len(c.words) for c in chunks) == 9
    assert all(a.end <= b.start for a, b in zip(chunks, chunks[1:]))
    pop = build_chunks(tl, pop=True)
    assert max(len(c.words) for c in pop) <= 3
    srt = write_srt(chunks, tmp_path / "x.srt").read_text(encoding="utf-8")
    assert srt.startswith("1\n00:00:00,000 --> ")
