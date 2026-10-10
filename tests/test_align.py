from swa.align import Word, align_words, build_timeline, parse_srt, words_from_srt
from swa.project import parse_script

SCRIPT = parse_script("1. Life the Spartan way.\n2. Soldiers trained every day.\n3. They never gave up")


def timeline(words, duration=8.0):
    return build_timeline(SCRIPT, align_words(SCRIPT, words, duration), duration, "test")["lines"]


def test_exact_transcript():
    words = [Word("Life", 0.5, 0.8), Word("the", 0.8, 0.9), Word("Spartan", 0.9, 1.4), Word("way.", 1.4, 1.7),
             Word("Soldiers", 3.0, 3.5), Word("trained", 3.5, 3.9), Word("every", 3.9, 4.1), Word("day.", 4.1, 4.5),
             Word("They", 6.0, 6.2), Word("never", 6.2, 6.5), Word("gave", 6.5, 6.8), Word("up", 6.8, 7.0)]
    lines = timeline(words)
    assert [ln["start"] for ln in lines] == [0.5, 3.0, 6.0]
    assert [ln["end"] for ln in lines] == [1.7, 4.5, 7.0]


def test_misheard_and_missing_words():
    # "Spartan" heard as "spar ten", "every" missing, extra filler "um".
    words = [Word("Life", 0.5, 0.8), Word("the", 0.8, 0.9), Word("spar", 0.9, 1.1), Word("ten", 1.1, 1.4),
             Word("way", 1.4, 1.7), Word("um", 2.0, 2.3),
             Word("Soldiers", 3.0, 3.5), Word("trained", 3.5, 3.9), Word("day", 4.1, 4.5),
             Word("They", 6.0, 6.2), Word("nefer", 6.2, 6.5), Word("gave", 6.5, 6.8), Word("up", 6.8, 7.0)]
    lines = timeline(words)
    assert lines[1]["start"] == 3.0
    assert lines[2]["start"] == 6.0
    every = lines[1]["words"][2]
    assert 3.9 <= every["s"] <= 4.1


def test_no_transcript_spreads_evenly():
    lines = timeline([], duration=12.0)
    assert lines[0]["start"] == 0.0
    assert abs(lines[-1]["end"] - 12.0) < 0.01
    starts = [ln["start"] for ln in lines]
    assert starts == sorted(starts)


def test_srt_import():
    srt = """1
00:00:01,000 --> 00:00:02,500
Life the Spartan way.

2
00:00:04,000 --> 00:00:06,000
Soldiers trained every day.

3
00:00:07,000 --> 00:00:08,000
They never gave up
"""
    assert len(parse_srt(srt)) == 3
    lines = timeline(words_from_srt(srt), duration=9.0)
    assert [ln["start"] for ln in lines] == [1.0, 4.0, 7.0]
