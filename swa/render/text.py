"""Text shaping and rendering for English and Persian, with no system libraries.

HarfBuzz (uharfbuzz) shapes each word, so Persian letters join and take
their correct forms on every platform; fontTools gives the glyph outlines,
which are filled with OpenCV using the non-zero winding rule. A small bidi
step orders words for right-to-left lines with embedded English words or
numbers.

Used for handwritten words on the board and for burned-in captions.
"""
from __future__ import annotations

import functools
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import uharfbuzz as hb
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont

from .. import paths

FONTS_DIR = paths.ASSETS / "fonts"

# Built-in fonts: id -> (file, display name, script). All OFL / Apache licensed.
FONTS = {
    # English handwriting
    "marker": ("PatrickHand-Regular.ttf", "Marker", "latin"),
    "casual": ("Caveat-SemiBold.ttf", "Casual", "latin"),
    "neat": ("Kalam-Regular.ttf", "Neat", "latin"),
    "bold": ("PermanentMarker-Regular.ttf", "Bold caps", "latin"),
    # Persian handwriting
    "naskh": ("Mirza-Medium.ttf", "Naskh", "rtl"),
    "playful": ("Marhey-SemiBold.ttf", "Playful", "rtl"),
    "display": ("Katibeh-Regular.ttf", "Display", "rtl"),
    "clean": ("Vazirmatn-Medium.ttf", "Clean", "rtl"),
    # Captions (Latin + Persian)
    "caption": ("Vazirmatn-ExtraBold.ttf", "Caption", "rtl"),
}

# Strong right-to-left letters. Arabic-Indic digits (U+0660..0669, U+06F0..06F9)
# are left out on purpose: numbers read left to right.
_RTL = re.compile("[\u0590-\u05ff\u0600-\u065f\u066a-\u06ef\u06fa-\u08ff\ufb1d-\ufdff\ufe70-\ufefc]")
_STRONG_LTR = re.compile(r"[A-Za-z\u00c0-\u024f]")


def is_rtl(text: str) -> bool:
    return bool(_RTL.search(text))


def font_path(font_id: str) -> Path:
    if font_id in FONTS:
        return FONTS_DIR / FONTS[font_id][0]
    p = Path(font_id)
    if p.exists():
        return p
    user = paths.DATA / "fonts" / Path(font_id).name
    if user.exists():
        return user
    raise FileNotFoundError(f"Font not found: {font_id}")


# ──────────────────────────────────────────────────────────────
# Fonts
# ──────────────────────────────────────────────────────────────
class _FlattenPen(BasePen):
    """Collects glyph contours as polylines (font units)."""

    def __init__(self, glyphset):
        super().__init__(glyphset)
        self.contours: list[np.ndarray] = []
        self._cur: list[tuple[float, float]] = []

    def _moveTo(self, p):
        self._flush()
        self._cur = [p]

    def _lineTo(self, p):
        self._cur.append(p)

    def _curveToOne(self, p1, p2, p3):
        p0 = self._getCurrentPoint()
        t = np.linspace(0, 1, 13)[1:, None]
        a, b, c, d = (np.array(p, dtype=np.float64) for p in (p0, p1, p2, p3))
        pts = (1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t ** 2 * c + t ** 3 * d
        self._cur.extend(map(tuple, pts))

    def _qCurveToOne(self, p1, p2):
        p0 = self._getCurrentPoint()
        t = np.linspace(0, 1, 9)[1:, None]
        a, b, c = (np.array(p, dtype=np.float64) for p in (p0, p1, p2))
        pts = (1 - t) ** 2 * a + 2 * (1 - t) * t * b + t ** 2 * c
        self._cur.extend(map(tuple, pts))

    def _closePath(self):
        self._flush()

    def _endPath(self):
        self._flush()

    def _flush(self):
        if len(self._cur) >= 3:
            self.contours.append(np.array(self._cur, dtype=np.float64))
        self._cur = []


class Font:
    def __init__(self, path: Path):
        self.path = Path(path)
        data = self.path.read_bytes()
        self.face = hb.Face(hb.Blob(data))
        self.hb = hb.Font(self.face)
        self.upem = self.face.upem
        self.tt = TTFont(self.path, lazy=True)
        self.glyphset = self.tt.getGlyphSet()
        self.cmap = self.tt.getBestCmap() or {}
        os2 = self.tt["OS/2"] if "OS/2" in self.tt else None
        hhea = self.tt["hhea"]
        asc = getattr(os2, "sTypoAscender", 0) if os2 is not None else 0
        desc = getattr(os2, "sTypoDescender", 0) if os2 is not None else 0
        if not asc:
            asc, desc = hhea.ascent, hhea.descent
        self.ascent = asc / self.upem
        self.descent = -desc / self.upem       # positive
        self.space = self._advance(" ") or 0.25
        self._glyphs: dict[int, list[np.ndarray]] = {}

    def covers(self, text: str) -> bool:
        for ch in text:
            if ch.isspace() or unicodedata.category(ch).startswith("C"):
                continue
            if ord(ch) not in self.cmap:
                return False
        return True

    def _advance(self, text: str) -> float:
        _ids, pos = self.shape(text)
        return sum(p[0] for p in pos)

    def shape(self, text: str) -> tuple[list[int], list[tuple[float, float, float]]]:
        """Glyph ids and (advance, x offset, y offset) in em units, in visual order."""
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        rtl = is_rtl(text)
        buf.direction = "rtl" if rtl else "ltr"
        if rtl:
            buf.language = "fa"
        hb.shape(self.hb, buf, {"kern": True, "liga": True})
        ids = [g.codepoint for g in buf.glyph_infos]
        pos = [(p.x_advance / self.upem, p.x_offset / self.upem, p.y_offset / self.upem)
               for p in buf.glyph_positions]
        return ids, pos

    def contours(self, gid: int) -> list[np.ndarray]:
        """Glyph outline in em units (y up)."""
        if gid not in self._glyphs:
            name = self.tt.getGlyphName(gid)
            pen = _FlattenPen(self.glyphset)
            try:
                self.glyphset[name].draw(pen)
            except KeyError:
                pass
            pen._flush()
            self._glyphs[gid] = [c / self.upem for c in pen.contours]
        return self._glyphs[gid]


@functools.lru_cache(maxsize=16)
def load_font(font_id: str) -> Font:
    return Font(font_path(font_id))


@dataclass
class FontPair:
    """A Latin font and a Persian/Arabic font; each word uses the one that fits."""
    latin: Font
    rtl: Font

    def for_word(self, word: str) -> Font:
        if is_rtl(word):
            return self.rtl if self.rtl.covers(word) else self.latin
        return self.latin if self.latin.covers(word) else self.rtl

    @classmethod
    def get(cls, latin_id: str, rtl_id: str) -> "FontPair":
        return cls(load_font(latin_id), load_font(rtl_id))


# ──────────────────────────────────────────────────────────────
# Layout
# ──────────────────────────────────────────────────────────────
@dataclass
class PlacedWord:
    index: int                 # position in the input word list (logical order)
    text: str
    font: Font
    size: float                # px per em
    x: float                   # left edge, px
    baseline: float            # px
    width: float               # px
    rtl: bool
    glyphs: list[tuple[int, float, float]] = field(default_factory=list)  # (gid, x px, y px) origins

    @property
    def top(self) -> float:
        return self.baseline - self.font.ascent * self.size

    @property
    def bottom(self) -> float:
        return self.baseline + self.font.descent * self.size


@dataclass
class TextLayout:
    words: list[PlacedWord]
    width: int
    height: int
    rtl: bool
    lines: list[list[int]]     # word indices per line (logical order)


def _word_dir(word: str) -> str:
    if is_rtl(word):
        return "R"
    if _STRONG_LTR.search(word):
        return "L"
    return "N"                 # digits / punctuation only


def visual_order(words: list[str], base_rtl: bool) -> list[int]:
    """Indices of `words` in left-to-right display order (simplified bidi)."""
    dirs = [_word_dir(w) for w in words]
    # Neutral words (numbers) read left-to-right inside an RTL line, but join
    # the surrounding LTR run when there is one.
    resolved = []
    for i, d in enumerate(dirs):
        if d != "N":
            resolved.append(d)
            continue
        prev = next((dirs[j] for j in range(i - 1, -1, -1) if dirs[j] != "N"), None)
        nxt = next((dirs[j] for j in range(i + 1, len(dirs)) if dirs[j] != "N"), None)
        resolved.append("L" if (prev == "L" or nxt == "L" or not base_rtl) else "N")
    runs: list[tuple[str, list[int]]] = []
    for i, d in enumerate(resolved):
        kind = "R" if d == "R" else ("L" if d == "L" else "N")
        if runs and runs[-1][0] == kind:
            runs[-1][1].append(i)
        else:
            runs.append((kind, [i]))
    out: list[int] = []
    ordered_runs = runs[::-1] if base_rtl else runs
    for kind, idx in ordered_runs:
        out.extend(idx[::-1] if kind == "R" else idx)
    return out


def layout_text(text_or_words, fonts: FontPair, size: float, max_width: float | None = None,
                align: str = "center", line_height: float = 1.25, base_rtl: bool | None = None) -> TextLayout:
    words = text_or_words.split() if isinstance(text_or_words, str) else list(text_or_words)
    if base_rtl is None:
        rtl_n = sum(1 for w in words if is_rtl(w))
        base_rtl = rtl_n > 0 and rtl_n >= sum(1 for w in words if _STRONG_LTR.search(w))
    shaped = []
    for w in words:
        f = fonts.for_word(w)
        ids, pos = f.shape(w)
        width = sum(p[0] for p in pos) * size
        shaped.append((f, ids, pos, width))
    space = (fonts.rtl if base_rtl else fonts.latin).space * size

    # Greedy line breaking in logical order.
    lines: list[list[int]] = []
    cur: list[int] = []
    cur_w = 0.0
    for i, (_f, _ids, _pos, w) in enumerate(shaped):
        add = w if not cur else cur_w + space + w
        if cur and max_width is not None and add > max_width:
            lines.append(cur)
            cur, cur_w = [i], w
        else:
            cur.append(i)
            cur_w = add
    if cur:
        lines.append(cur)

    asc = max((s[0].ascent for s in shaped), default=fonts.latin.ascent)
    desc = max((s[0].descent for s in shaped), default=fonts.latin.descent)
    line_px = size * max(line_height, asc + desc)
    widths = []
    for ln in lines:
        widths.append(sum(shaped[i][3] for i in ln) + space * (len(ln) - 1))
    box_w = max(widths) if widths else 0.0
    if max_width is not None and align != "left" and align != "right":
        box_w = max(box_w, 0.0)
    placed: list[PlacedWord] = []
    for li, ln in enumerate(lines):
        lw = widths[li]
        if align == "center":
            x = (box_w - lw) / 2
        elif (align == "start" and base_rtl) or align == "right":
            x = box_w - lw
        else:
            x = 0.0
        baseline = asc * size + li * line_px
        order = visual_order([words[i] for i in ln], base_rtl)
        for k in order:
            i = ln[k]
            f, ids, pos, w = shaped[i]
            gx = x
            glyphs = []
            for gid, (adv, xo, yo) in zip(ids, pos):
                glyphs.append((gid, gx + xo * size, baseline - yo * size))
                gx += adv * size
            placed.append(PlacedWord(i, words[i], f, size, x, baseline, w, is_rtl(words[i]), glyphs))
            x += w + space
    height = int(np.ceil(asc * size + (len(lines) - 1) * line_px + desc * size)) if lines else 0
    return TextLayout(placed, int(np.ceil(box_w)) + 1, max(1, height), base_rtl, lines)


def fit_text(text_or_words, fonts: FontPair, max_w: float, max_h: float, max_size: float,
             min_size: float = 8.0, line_height: float = 1.25, align: str = "center",
             max_lines: int | None = None) -> TextLayout:
    """Largest font size whose wrapped layout fits the box."""
    lo, hi = min_size, max_size
    best = layout_text(text_or_words, fonts, lo, max_w, align, line_height)
    for _ in range(14):
        mid = (lo + hi) / 2
        lay = layout_text(text_or_words, fonts, mid, max_w, align, line_height)
        ok = lay.height <= max_h and lay.width <= max_w + 1 and (max_lines is None or len(lay.lines) <= max_lines)
        if ok:
            best, lo = lay, mid
        else:
            hi = mid
    return best


# ──────────────────────────────────────────────────────────────
# Rendering
# ──────────────────────────────────────────────────────────────
def _fill_nonzero(acc: np.ndarray, contours: list[np.ndarray]) -> None:
    """Add each closed contour with its orientation sign (non-zero winding rule)."""
    h, w = acc.shape
    for c in contours:
        if len(c) < 3:
            continue
        x, y = c[:, 0], c[:, 1]
        area = 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
        if area == 0:
            continue
        x0 = max(0, int(np.floor(x.min())))
        y0 = max(0, int(np.floor(y.min())))
        x1 = min(w, int(np.ceil(x.max())) + 1)
        y1 = min(h, int(np.ceil(y.max())) + 1)
        if x0 >= x1 or y0 >= y1:
            continue
        tmp = np.zeros((y1 - y0, x1 - x0), np.uint8)
        pts = np.round(np.stack([x - x0, y - y0], axis=1) * 16).astype(np.int32)
        cv2.fillPoly(tmp, [pts], 1, lineType=cv2.LINE_8, shift=4)
        acc[y0:y1, x0:x1] += tmp.astype(np.int16) * (1 if area > 0 else -1)


def render_word(word: PlacedWord, ss: int = 3, pad: int = 4) -> tuple[np.ndarray, int, int]:
    """Alpha mask (float32 0..1) of one placed word and its top-left corner (px)."""
    x0 = int(np.floor(word.x)) - pad
    y0 = int(np.floor(word.top)) - pad
    w = int(np.ceil(word.width)) + 2 * pad + 2
    h = int(np.ceil(word.bottom - word.top)) + 2 * pad + 2
    acc = np.zeros((h * ss, w * ss), np.int16)
    s = word.size
    for gid, gx, gy in word.glyphs:
        cs = []
        for c in word.font.contours(gid):
            px = (gx + c[:, 0] * s - x0) * ss
            py = (gy - c[:, 1] * s - y0) * ss
            cs.append(np.stack([px, py], axis=1))
        _fill_nonzero(acc, cs)
    mask = (acc != 0).astype(np.float32)
    alpha = cv2.resize(mask, (w, h), interpolation=cv2.INTER_AREA)
    return alpha, x0, y0


def render_layout(layout: TextLayout, ss: int = 3, pad: int = 4) -> tuple[np.ndarray, list[tuple[int, np.ndarray, int, int]]]:
    """Whole-text alpha (with `pad` px border) and per-word (index, alpha, x, y) patches."""
    W, H = layout.width + 2 * pad, layout.height + 2 * pad
    full = np.zeros((H, W), np.float32)
    parts = []
    for word in layout.words:
        a, x, y = render_word(word, ss)
        x += pad
        y += pad
        fx0, fy0 = max(0, x), max(0, y)
        fx1, fy1 = min(W, x + a.shape[1]), min(H, y + a.shape[0])
        if fx0 < fx1 and fy0 < fy1:
            sub = a[fy0 - y:fy1 - y, fx0 - x:fx1 - x]
            np.maximum(full[fy0:fy1, fx0:fx1], sub, out=full[fy0:fy1, fx0:fx1])
        parts.append((word.index, a, x, y))
    return full, parts
