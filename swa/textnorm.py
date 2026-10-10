"""Text normalization shared by script parsing and audio alignment.

Whisper output and a hand-written script rarely agree character for
character, especially in Persian (Arabic vs. Persian letter forms, ZWNJ,
diacritics, digits). Every comparison between the two goes through
`normalize_token` so those differences do not break the alignment.
"""
from __future__ import annotations

import re
import unicodedata

# Arabic code points that Persian text often contains by accident.
_CHAR_MAP = str.maketrans({
    "\u064a": "\u06cc",  # Arabic yeh -> Persian yeh
    "\u0649": "\u06cc",  # alef maksura -> Persian yeh
    "\u0643": "\u06a9",  # Arabic kaf -> Persian keheh
    "\u0629": "\u0647",  # teh marbuta -> heh
    "\u06c0": "\u0647",  # heh with yeh above -> heh
    "\u0623": "\u0627",  # alef with hamza above -> alef
    "\u0625": "\u0627",  # alef with hamza below -> alef
    "\u0622": "\u0627",  # alef with madda -> alef
    "\u0671": "\u0627",  # alef wasla -> alef
    "\u0624": "\u0648",  # waw with hamza -> waw
    "\u0626": "\u06cc",  # yeh with hamza -> Persian yeh
    # Persian (U+06F0..) and Arabic-Indic (U+0660..) digits -> ASCII
    **{chr(0x06F0 + i): str(i) for i in range(10)},
    **{chr(0x0660 + i): str(i) for i in range(10)},
    # Typographic quotes / apostrophes
    "\u2019": "'", "\u2018": "'", "`": "'",
})

# ZWNJ, ZWJ, LRM, RLM, BOM
_ZW_CHARS = "\u200c\u200d\u200e\u200f\ufeff"
# Harakat (U+064B..U+065F), superscript alef, Quranic marks and tatweel
_DIACRITICS = re.compile("[\u064b-\u065f\u0670\u06d6-\u06ed\u0640]")
_PUNCT = re.compile(r"[^\w']+", re.UNICODE)

_PERSIAN_RANGE = re.compile("[\u0600-\u06ff]")


def detect_language(text: str) -> str:
    """Return 'fa' if the text is mostly Persian/Arabic script, else 'en'."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "en"
    persian = sum(1 for c in letters if _PERSIAN_RANGE.match(c))
    return "fa" if persian / len(letters) > 0.3 else "en"


def normalize_text(text: str) -> str:
    """Normalize a whole string (keeps word boundaries)."""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_CHAR_MAP)
    text = _DIACRITICS.sub("", text)
    # ZWNJ joins the parts of one Persian word ("می‌خواهم"); drop it so both
    # "میخواهم" and "می‌خواهم" become the same token.
    for ch in _ZW_CHARS:
        text = text.replace(ch, "")
    return text.lower()


def normalize_token(token: str) -> str:
    """Normalize a single word for matching: no punctuation, lowercase."""
    token = normalize_text(token)
    token = _PUNCT.sub("", token)
    return token.strip("'_")


def tokenize(text: str) -> list[str]:
    """Split text into display words (original spelling, punctuation kept)."""
    return [w for w in re.split(r"\s+", text.strip()) if w]


def match_tokens(text: str) -> list[str]:
    """Normalized tokens of a text, empty tokens dropped."""
    out = []
    for word in tokenize(text):
        norm = normalize_token(word)
        if norm:
            out.append(norm)
    return out
