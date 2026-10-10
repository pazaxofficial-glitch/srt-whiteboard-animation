from pathlib import Path

from swa.project import image_number, map_images, parse_script
from swa.textnorm import detect_language, normalize_token


def ids_texts(text):
    return [(ln.id, ln.text) for ln in parse_script(text)]


def test_numbered_styles_and_continuation():
    text = "1. Life, the Spartan way.\n2) Soldiers trained\n   every day\n\n[3] They never gave up\n4 - The end"
    assert ids_texts(text) == [
        (1, "Life, the Spartan way."),
        (2, "Soldiers trained every day"),
        (3, "They never gave up"),
        (4, "The end"),
    ]


def test_persian_digits_and_text():
    text = "۱- زندگی به سبک اسپارتی\n۲- سربازها هر روز تمرین می‌کردند"
    assert ids_texts(text) == [(1, "زندگی به سبک اسپارتی"), (2, "سربازها هر روز تمرین می‌کردند")]


def test_plain_lines_are_numbered_in_order():
    assert ids_texts("Hello world\n300 Spartans fought\nThe end") == [
        (1, "Hello world"), (2, "300 Spartans fought"), (3, "The end")]


def test_bare_sequential_numbers():
    assert ids_texts("1 one\n2 two\n3 three") == [(1, "one"), (2, "two"), (3, "three")]


def test_gaps_in_numbering_are_kept():
    assert [ln.id for ln in parse_script("1. a\n2. b\n5. c")] == [1, 2, 5]


def test_image_numbers():
    assert image_number(Path("001.png")) == 1
    assert image_number(Path("58.jpg")) == 58
    assert image_number(Path("scene_12_final.png")) == 12
    assert image_number(Path("۱۲.png")) == 12
    assert image_number(Path("cover.png")) is None


def test_map_images(tmp_path):
    for name in ["1.png", "002.svg", "03.jpg", "notes.txt", "x.png"]:
        (tmp_path / name).write_bytes(b"x")
    mapping, warnings = map_images(tmp_path)
    assert sorted(mapping) == [1, 2, 3]
    assert any("x.png" in w for w in warnings)


def test_normalization():
    assert normalize_token("می‌خواهم") == normalize_token("میخواهم")
    assert normalize_token("كتاب") == normalize_token("کتاب")
    assert normalize_token("Spartan,") == "spartan"
    assert detect_language("زندگی به سبک اسپارتی") == "fa"
    assert detect_language("Life the Spartan way") == "en"
