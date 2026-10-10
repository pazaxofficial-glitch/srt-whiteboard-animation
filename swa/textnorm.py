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
    "ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه", "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ؤ": "و", "ئ": "ی",
    # Persian and Arabic-Indic digits -> ASCII
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4", "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    # Typographic quotes / apostrophes
    "’": "'", "‘": "'", "`": "'",
})

_ZW_CHARS = "‌‍‎‏﻿"
_DIACRITICS = re.compile("[ً-ٰٟۖ-ۭـ]")  # harakat + tatweel
_PUNCT = re.compile(r"[^\w']+", re.UNICODE)

_PERSIAN_RANGE = re.compile("[؀-ۿ]")


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
