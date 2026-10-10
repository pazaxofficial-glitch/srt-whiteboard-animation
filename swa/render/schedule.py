"""Timing inside every shot (no pixels here, so it is easy to test).

A shot is one board: a script line drawn as a picture ("image"), a video
clip that plays ("clip") or, for a line without a picture, written out as
text ("text").

    trans_start ── start ──────────────────────── draw_end ──── next shot
       board        the hand draws the picture and writes the marked words
       changes      exactly when they are spoken

One hand does everything, so while it writes a word the picture pauses:
those moments (plus the time to move between picture and text) are the
shot's `busy` intervals.

Lines that are too short to draw (see `short_lines`) become "appear" shots:
the picture (or the text) fades in on its own, without the hand.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..project import CLIP_EXTS
from ..textnorm import normalize_token

PER_CHAR = 0.085      # seconds per written character at write_speed 1.0
WORD_BASE = 0.12      # extra seconds per written word (pen lift, spacing)
TRAVEL = 0.2          # seconds to move the hand between picture and text
GAP = 0.04            # pause between two written words
APPEAR = 0.35         # seconds for a picture to fade in on a short line
WORD_FADE = 0.18      # seconds for one word to fade in on a short line
SEG_MIN = 0.9         # seconds left for the last word-timed part of a picture

TRANSITIONS = ("slide", "fade", "wipe", "zoom", "cut")
# The "mix" transition: kinds and how often each one comes up.
MIX = (("slide", 3), ("fade", 3), ("wipe", 2), ("zoom", 2), ("slide_up", 2))


@dataclass
class WriteWindow:
    word: int          # index in the line's word list
    t0: float
    t1: float


@dataclass
class Shot:
    line_id: int
    image: Path | None
    trans_start: float
    start: float                      # first word of the line is spoken
    image_end: float                  # picture finished
    draw_end: float                   # everything on this board finished
    words: list[dict] = field(default_factory=list)       # timeline words {w, s, e}
    kind: str = "image"                                   # "image" | "text" | "clip"
    write_words: list[int] = field(default_factory=list)  # word indices to handwrite
    writes: list[WriteWindow] = field(default_factory=list)
    busy: list[tuple[float, float]] = field(default_factory=list)
    mode: str = "draw"                # "draw": the hand draws | "appear": fades in, no hand
    trans_kind: str = "slide"         # transition into this shot

    @property
    def text_words(self) -> list[str]:
        return [w["w"] for w in self.words]


def _letters(word: str) -> int:
    return max(1, sum(1 for ch in word if ch.isalnum()))


def word_duration(word: str, speed: float = 1.0) -> float:
    return float(np.clip((WORD_BASE + _letters(word) * PER_CHAR) / max(0.2, speed), 0.22, 1.8))


def _sequence(indices: list[int], words: list[dict], floor: float, speed: float) -> list[WriteWindow]:
    """Write words one after another, each starting when it is spoken (or when the
    previous one is finished, whichever is later)."""
    out = []
    t_prev = floor
    for i in indices:
        s = float(words[i]["s"]) if i < len(words) else t_prev
        t0 = max(s, t_prev + (GAP if out else 0.0))
        t1 = t0 + word_duration(words[i]["w"] if i < len(words) else "", speed)
        out.append(WriteWindow(i, t0, t1))
        t_prev = t1
    return out


def _appear(indices: list[int], words: list[dict], floor: float) -> list[WriteWindow]:
    """Words that simply fade in as they are spoken (no hand)."""
    out = []
    for i in indices:
        t0 = max(floor, float(words[i]["s"]) if i < len(words) else floor)
        out.append(WriteWindow(i, t0, t0 + WORD_FADE))
    return out


def _squeeze(windows: list[WriteWindow], hi: float) -> None:
    """Make windows finish by `hi` (keeps their order; writing just gets faster)."""
    if not windows or windows[-1].t1 <= hi:
        return
    a = windows[0].t0
    a2 = min(a, hi - 0.18 * len(windows))
    span, new_span = windows[-1].t1 - a, max(0.05, hi - a2)
    for w in windows:
        w.t0 = a2 + (w.t0 - a) * new_span / span
        w.t1 = a2 + (w.t1 - a) * new_span / span


def _busy(writes: list[WriteWindow], start: float) -> list[tuple[float, float]]:
    """Intervals when the hand is away from the picture: moving to the text,
    writing, and moving back. Close groups of words share one interval."""
    out: list[list[float]] = []
    for w in writes:
        a, b = max(start, w.t0 - TRAVEL), w.t1 + TRAVEL
        if out and a <= out[-1][1] + 0.3:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _overlap(intervals: list[tuple[float, float]], a: float, b: float) -> float:
    return sum(max(0.0, min(b, y) - max(a, x)) for x, y in intervals)


def pick_transition(setting: str, line_id: int, prev: str | None) -> str:
    """The transition into one board. "mix" varies it (never the same twice in a row)."""
    if setting != "mix":
        return setting if setting in TRANSITIONS else "slide"
    rng = random.Random(line_id * 7919 + 17)
    pool = [(k, w) for k, w in MIX if k != prev]
    return rng.choices([k for k, _ in pool], [w for _, w in pool])[0]


def cue_indices(cues: list[str | None], words: list[dict]) -> list[int | None]:
    """Word index for each timed part of a picture (data-word="spear").

    Searched in order, so a second "shield" finds the shield after the first one.
    A number that is not one of the words counts as a word number (1 = first).
    """
    norm = [normalize_token(w["w"]) for w in words]
    out: list[int | None] = []
    pos = 0
    for cue in cues:
        key = normalize_token(cue.split()[0]) if cue and cue.split() else ""
        if not key:
            out.append(None)
            continue
        idx = next((i for i in range(pos, len(norm)) if norm[i] == key), None)
        if idx is None:   # "shield" for "shields", "spear" for "spears,"
            idx = next((i for i in range(pos, len(norm)) if norm[i] and
                        (norm[i].startswith(key) or key.startswith(norm[i])) and min(len(key), len(norm[i])) >= 3),
                       None)
        if idx is None and key.isdigit() and 1 <= int(key) <= len(norm):
            idx = int(key) - 1
        if idx is None:
            idx = next((i for i, n in enumerate(norm) if n == key), None)
        out.append(idx)
        if idx is not None:
            pos = max(pos, idx)
    return out


def is_short(lines: list[dict], i: int, end_time: float, settings: dict) -> bool:
    """True when line i has too little time to be drawn (it appears instead)."""
    if settings.get("short_lines", "show") == "draw":
        return False
    nxt = float(lines[i + 1]["start"]) if i + 1 < len(lines) else end_time
    return nxt - float(lines[i]["start"]) < float(settings.get("short_threshold", 3.0))


def plan_shots(timeline: dict, images: dict[int, Path], settings: dict, end_time: float,
               marks: dict[int, list[int]] | None = None,
               cues: dict[int, list[int]] | None = None) -> list[Shot]:
    """Shots for every line that has a picture (or is written as text).

    marks: line id -> indices of words to handwrite when spoken (from *word* in the script).
    cues:  line id -> word indices where timed parts of the picture start (SVG data-word).
    """
    lines = sorted(timeline["lines"], key=lambda ln: ln["start"])
    fill = float(settings.get("draw_fill", 0.8))
    min_draw = float(settings.get("min_draw", 0.8))
    max_draw = float(settings.get("max_draw", 14.0))
    speed = float(settings.get("write_speed", 1.0))
    handwriting = bool(settings.get("handwriting", True))
    text_lines = settings.get("text_lines", "write")
    short_mode = settings.get("short_lines", "show")
    setting = settings.get("transition", "slide")
    trans_dur = float(settings.get("transition_duration", 0.6))
    trans = trans_dur if setting != "cut" else 0.0
    marks = marks or {}
    cues = cues or {}

    shots: list[Shot] = []
    for i, ln in enumerate(lines):
        lid = int(ln["id"])
        words = ln.get("words", [])
        img = images.get(lid)
        quick = bool(words or img) and is_short(lines, i, end_time, settings)
        as_text = img is None or (quick and short_mode == "text" and bool(words))
        if img is None and not (text_lines == "write" and words):
            continue
        start = float(ln["start"])
        nxt = float(lines[i + 1]["start"]) if i + 1 < len(lines) else end_time
        avail = max(0.05, nxt - start)
        limit = start + max(0.25, avail - trans - 0.05) if i + 1 < len(lines) else nxt

        if as_text:
            # Text card: every word as it is spoken (written by hand, or fading in on a short line).
            idx = list(range(len(words)))
            if quick:
                writes = _appear(idx, words, start)
            else:
                writes = _sequence(idx, words, start, speed)
                _squeeze(writes, limit)
            end = writes[-1].t1 if writes else start + 0.25
            shots.append(Shot(lid, None, start, start, start, end, words, "text", idx, writes, [],
                              "appear" if quick else "draw"))
            continue

        if img.suffix.lower() in CLIP_EXTS:
            # A video clip plays from the first word until the next board (no hand).
            shots.append(Shot(lid, img, start, start, start, max(start + 0.05, limit), words, "clip"))
            continue

        idx = sorted({k for k in (marks.get(lid, []) if handwriting else []) if 0 <= k < len(words)})
        if quick:
            # Too short to draw: the picture fades in and marked words appear when spoken.
            image_end = start + min(APPEAR, max(0.1, avail * 0.3))
            writes = _appear(idx, words, start)
            draw_end = max(image_end, writes[-1].t1 if writes else image_end)
            shots.append(Shot(lid, img, start, start, image_end, draw_end, words, "image", idx, writes, [],
                              "appear"))
            continue

        draw = min(max(avail * fill, min_draw), max_draw)
        draw = min(draw, max(avail - trans - 0.05, avail * 0.85))
        draw = max(0.25, min(draw, avail))
        image_end = start + draw
        timed = [k for k in cues.get(lid, []) if 0 <= k < len(words)]
        if timed:
            # The last timed part starts on its word; leave it time to be drawn.
            image_end = max(image_end, min(limit, float(words[max(timed)]["s"]) + SEG_MIN))

        writes = _sequence(idx, words, start, speed)
        busy = _busy(writes, start)
        if busy and busy[-1][1] > limit:
            _squeeze(writes, limit - TRAVEL)
            busy = _busy(writes, start)

        # Give the picture back the time the hand spends writing.
        lost = _overlap(busy, start, image_end)
        if lost > 0:
            image_end = min(max(limit, image_end), image_end + lost)
        draw_end = max(image_end, busy[-1][1] if busy else image_end)
        shots.append(Shot(lid, img, start, start, image_end, draw_end, words, "image", idx, writes, busy))

    prev: str | None = None
    for k, shot in enumerate(shots):
        shot.trans_kind = pick_transition(setting, shot.line_id, prev)
        prev = shot.trans_kind
        if k == 0:
            shot.trans_start = shot.start
            continue
        room = max(0.0, shot.start - shots[k - 1].draw_end)
        dur = 0.0 if shot.trans_kind == "cut" else trans_dur
        shot.trans_start = shot.start - min(dur, room)
    return shots


def progress_curve(shot: Shot, fps: int, mode: str,
                   anchors: list[tuple[float, float]] | None = None) -> np.ndarray:
    """Picture progress (0..1) for each frame from shot.start to shot.image_end.

    With mode "speech" the pen moves faster while words are spoken; it stops
    while the hand is busy writing. `anchors` are (time, progress) pairs: the
    picture may not pass `progress` before `time` (a part that waits for its
    word). The pen then draws each part at its natural pace and rests until
    the next word, speeding up only when a part would not be done in time.
    """
    n = max(2, int(math.ceil((shot.image_end - shot.start) * fps)) + 1)
    t = shot.start + np.arange(n) / fps
    if mode == "speech" and shot.words:
        w = np.full(n, 0.3, dtype=np.float64)
        for wd in shot.words:
            w[(t >= wd["s"]) & (t < wd["e"] + 0.05)] = 1.0
        k = max(1, int(0.15 * fps))
        w = np.convolve(w, np.ones(k) / k, mode="same")
    else:
        w = np.ones(n, dtype=np.float64)
    ramp = max(1, min(int(0.12 * fps), n // 2))
    env = np.ones(n)
    env[:ramp] = np.linspace(0.35, 1, ramp)
    env[-ramp:] = np.minimum(env[-ramp:], np.linspace(1, 0.35, ramp))
    w = w * env
    free = w.copy()
    for a, b in shot.busy:
        free[(t >= a) & (t < b)] = 0.0
    if free.sum() > 1e-6:
        w = free
    if anchors:
        return _anchored(w, t, anchors)
    c = np.concatenate([[0.0], np.cumsum(w[:-1])])
    return c / c[-1] if c[-1] > 0 else np.linspace(0, 1, n)


def _anchored(w: np.ndarray, t: np.ndarray, anchors: list[tuple[float, float]]) -> np.ndarray:
    n = len(w)
    total = float(w[:-1].sum())
    if total <= 0:
        return np.linspace(0, 1, n)
    base = 1.0 / total
    pts: list[tuple[float, float]] = []
    for a, p in sorted(anchors, key=lambda ap: ap[1]):
        if 0.0 <= p < 1.0:
            a = max(a, pts[-1][0]) if pts else a      # keep times in order
            pts.append((a, p))
    bounds = [0] + [min(n - 1, int(np.searchsorted(t, a - 1e-9))) for a, _ in pts] + [n - 1]
    goals = [p for _, p in pts] + [1.0]
    out = np.zeros(n)
    p = 0.0
    for j in range(len(bounds) - 1):
        a, b = bounds[j], bounds[j + 1]
        goal = goals[j]
        weight = float(w[a:b].sum())
        rate = max(base, (goal - p) / weight) if weight > 0 and goal > p else 0.0
        for i in range(a, b):
            out[i] = p
            p = min(goal, p + w[i] * rate)
    out[n - 1] = 1.0
    return np.maximum.accumulate(out)


def write_progress(window: WriteWindow, t: float) -> float:
    """0..1 through one written word (smooth start and finish)."""
    if t <= window.t0:
        return 0.0
    if t >= window.t1:
        return 1.0
    q = (t - window.t0) / max(1e-6, window.t1 - window.t0)
    return 0.5 * q + 0.5 * (q * q * (3 - 2 * q))
