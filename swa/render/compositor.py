"""Build the whole video: one drawing per script line, in time with the voice.

Timing model for every line that has an image:

    trans_start ── start ─────────── draw_end ───────── next line
        │ board changes │ hand draws (ink, then colour) │ finished picture stays

`start` is the moment the first word of the line is spoken, so the pen
touches the board exactly when the narrator starts that line. With
sync_mode="speech" the pen moves while words are spoken and slows down in
pauses.
"""
from __future__ import annotations

import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from .. import paths
from ..project import Project
from .backgrounds import make_background
from .drawing import PreparedDrawing, prepare
from .encoder import VideoWriter
from .hands import HandSprite, find_hand

Progress = Callable[[str, float, dict], None]

ASPECTS = {"16:9": (16, 9), "9:16": (9, 16), "1:1": (1, 1), "4:5": (4, 5)}


def frame_size(settings: dict) -> tuple[int, int]:
    aw, ah = ASPECTS.get(settings.get("aspect", "16:9"), (16, 9))
    short = int(settings.get("resolution", 1080))
    if aw >= ah:
        h = short
        w = int(round(short * aw / ah))
    else:
        w = short
        h = int(round(short * ah / aw))
    return w - w % 2, h - h % 2


@dataclass
class Shot:
    line_id: int
    image: Path
    trans_start: float
    start: float
    draw_end: float
    words: list[dict] = field(default_factory=list)


def plan_shots(timeline: dict, images: dict[int, Path], settings: dict, end_time: float) -> list[Shot]:
    lines = sorted(timeline["lines"], key=lambda ln: ln["start"])
    fill = float(settings.get("draw_fill", 0.8))
    min_draw = float(settings.get("min_draw", 0.8))
    max_draw = float(settings.get("max_draw", 14.0))
    trans = float(settings.get("transition_duration", 0.6)) if settings.get("transition", "slide") != "cut" else 0.0

    shots: list[Shot] = []
    for i, ln in enumerate(lines):
        img = images.get(int(ln["id"]))
        if img is None:
            continue
        start = float(ln["start"])
        nxt = float(lines[i + 1]["start"]) if i + 1 < len(lines) else end_time
        avail = max(0.05, nxt - start)
        draw = min(max(avail * fill, min_draw), max_draw)
        # Leave room for the next board change.
        draw = min(draw, max(avail - trans - 0.05, avail * 0.85))
        draw = max(0.25, min(draw, avail))
        shots.append(Shot(int(ln["id"]), img, start, start, start + draw, ln.get("words", [])))

    for k, shot in enumerate(shots):
        if k == 0:
            shot.trans_start = shot.start
            continue
        room = max(0.0, shot.start - shots[k - 1].draw_end)
        shot.trans_start = shot.start - min(trans, room)
    return shots


def _ease(q: float) -> float:
    q = min(1.0, max(0.0, q))
    return q * q * (3 - 2 * q)


def progress_curve(shot: Shot, fps: int, mode: str) -> np.ndarray:
    """Drawing progress (0..1) for each frame between shot.start and shot.draw_end."""
    n = max(2, int(math.ceil((shot.draw_end - shot.start) * fps)) + 1)
    t = shot.start + np.arange(n) / fps
    if mode == "speech" and shot.words:
        w = np.full(n, 0.3, dtype=np.float64)
        for wd in shot.words:
            w[(t >= wd["s"]) & (t < wd["e"] + 0.05)] = 1.0
        k = max(1, int(0.15 * fps))
        w = np.convolve(w, np.ones(k) / k, mode="same")
    else:
        w = np.ones(n, dtype=np.float64)
    # Gentle start and finish of the pen.
    ramp = max(1, min(int(0.12 * fps), n // 2))
    env = np.ones(n)
    env[:ramp] = np.linspace(0.35, 1, ramp)
    env[-ramp:] = np.minimum(env[-ramp:], np.linspace(1, 0.35, ramp))
    w = w * env
    c = np.concatenate([[0.0], np.cumsum(w[:-1])])
    return c / c[-1] if c[-1] > 0 else np.linspace(0, 1, n)


# ──────────────────────────────────────────────────────────────
# Pen plan: one polyline with pen-up / pen-down segments
# ──────────────────────────────────────────────────────────────
@dataclass
class PenPlan:
    pts: np.ndarray      # (P, 2)
    rad: np.ndarray      # (P,)
    down: np.ndarray     # (P,) True if the segment ending at P is drawn
    cum: np.ndarray      # (P,) cumulative effort

    @property
    def total(self) -> float:
        return float(self.cum[-1]) if len(self.cum) else 0.0

    def position(self, effort: float) -> tuple[float, float]:
        if len(self.pts) == 0:
            return (0.0, 0.0)
        i = int(np.searchsorted(self.cum, effort, side="right"))
        if i <= 0:
            return tuple(self.pts[0])
        if i >= len(self.pts):
            return tuple(self.pts[-1])
        c0, c1 = self.cum[i - 1], self.cum[i]
        f = 0.0 if c1 <= c0 else (effort - c0) / (c1 - c0)
        p = self.pts[i - 1] + (self.pts[i] - self.pts[i - 1]) * f
        return (float(p[0]), float(p[1]))


def build_plan(polylines: list[tuple[np.ndarray, np.ndarray]], start: tuple[float, float],
               lift_cost: float = 0.35, lift_pause: float = 10.0) -> PenPlan:
    pts, rad, down, cost = [np.array(start, np.float32)], [1.0], [False], [0.0]
    prev = np.array(start, np.float32)
    for p, r in polylines:
        if len(p) == 0:
            continue
        travel = float(np.linalg.norm(p[0] - prev))
        pts.append(p[0])
        rad.append(float(r[0]))
        down.append(False)
        cost.append(travel * lift_cost + lift_pause)
        seg = np.linalg.norm(np.diff(p, axis=0), axis=1)
        for j in range(1, len(p)):
            pts.append(p[j])
            rad.append(float(r[j]))
            down.append(True)
            cost.append(float(seg[j - 1]))
        prev = p[-1]
    return PenPlan(np.array(pts, np.float32), np.array(rad, np.float32), np.array(down, bool),
                   np.cumsum(np.array(cost, np.float64)))


# ──────────────────────────────────────────────────────────────
# Revealing one drawing on the board
# ──────────────────────────────────────────────────────────────
class DrawState:
    def __init__(self, d: PreparedDrawing, board: np.ndarray, bg: np.ndarray, mode: str, ink_share: float,
                 start: tuple[float, float]):
        self.d = d
        self.board = board
        self.bg = bg
        self.mode = mode
        w, h = d.size
        self.mline = np.zeros((h, w), np.uint8)
        self.mcol = np.zeros((h, w), np.uint8)
        self.ink_share = 1.0 if mode == "ink_only" else (ink_share if d.color_paths else 1.0)
        if not d.strokes and d.color_paths and mode != "ink_only":
            self.ink_share = 0.0  # fill-only picture: go straight to colouring
        self.ink = build_plan([(s.points, s.radius) for s in d.strokes], start)
        ink_end = tuple(self.ink.pts[-1]) if len(self.ink.pts) else start
        self.col = build_plan([(p, np.full(len(p), r, np.float32)) for p, r in d.color_paths], ink_end,
                              lift_cost=0.25, lift_pause=4.0)
        self.ink_i = 1
        self.col_i = 1
        self.ink_effort = 0.0
        self.col_effort = 0.0
        self.done = False

    def _draw_segments(self, plan: PenPlan, idx: int, effort: float, mask: np.ndarray, extra: np.ndarray | None,
                       scale: float = 1.0) -> tuple[int, list[float] | None]:
        """Draw pen-down segments up to `effort`. Returns (next index, dirty box)."""
        ox, oy = self.d.rect[0], self.d.rect[1]
        box = None
        n = len(plan.pts)

        def stamp(a, b, r):
            nonlocal box
            t = max(1, int(round(2 * r * scale)))
            pa = (int(round(a[0] - ox)), int(round(a[1] - oy)))
            pb = (int(round(b[0] - ox)), int(round(b[1] - oy)))
            cv2.line(mask, pa, pb, 255, t, cv2.LINE_AA)
            if extra is not None:
                cv2.line(extra, pa, pb, 255, max(1, int(t * 1.5)), cv2.LINE_AA)
            rr = r * scale * 1.5 + 2
            x0, x1 = min(pa[0], pb[0]) - rr, max(pa[0], pb[0]) + rr
            y0, y1 = min(pa[1], pb[1]) - rr, max(pa[1], pb[1]) + rr
            box = [x0, y0, x1, y1] if box is None else [min(box[0], x0), min(box[1], y0),
                                                          max(box[2], x1), max(box[3], y1)]

        while idx < n and plan.cum[idx] <= effort:
            if plan.down[idx]:
                stamp(plan.pts[idx - 1], plan.pts[idx], (plan.rad[idx - 1] + plan.rad[idx]) / 2)
            idx += 1
        # Partial segment up to the exact pen position.
        if idx < n and plan.down[idx] and plan.cum[idx] > plan.cum[idx - 1]:
            c0, c1 = plan.cum[idx - 1], plan.cum[idx]
            f = (effort - c0) / (c1 - c0)
            if f > 0:
                a = plan.pts[idx - 1]
                b = a + (plan.pts[idx] - a) * f
                stamp(a, b, plan.rad[idx])
        return idx, box

    def compose(self, box: list[float] | None = None) -> None:
        d = self.d
        w, h = d.size
        if box is None:
            x0, y0, x1, y1 = 0, 0, w, h
        else:
            x0, y0 = max(0, int(box[0])), max(0, int(box[1]))
            x1, y1 = min(w, int(math.ceil(box[2])) + 1), min(h, int(math.ceil(box[3])) + 1)
            if x0 >= x1 or y0 >= y1:
                return
        fx, fy = d.rect[0], d.rect[1]
        base = self.bg[fy + y0:fy + y1, fx + x0:fx + x1].astype(np.float32)
        ml = (self.mline[y0:y1, x0:x1].astype(np.float32) * (1 / 255)) * d.line_a[y0:y1, x0:x1]
        mc = (self.mcol[y0:y1, x0:x1].astype(np.float32) * (1 / 255)) * d.full_a[y0:y1, x0:x1]
        out = base + (d.line_rgb[y0:y1, x0:x1] - base) * ml[..., None]
        out += (d.full_rgb[y0:y1, x0:x1] - out) * mc[..., None]
        self.board[fy + y0:fy + y1, fx + x0:fx + x1] = np.clip(out, 0, 255).astype(np.uint8)

    def advance(self, p: float) -> tuple[float, float]:
        """Draw up to progress p (0..1). Returns the pen position."""
        ink_p = min(1.0, p / self.ink_share) if self.ink_share > 0 else 1.0
        col_p = 0.0 if self.ink_share >= 1.0 else max(0.0, (p - self.ink_share) / (1 - self.ink_share))

        extra = self.mcol if self.mode == "color_strokes" else None
        effort = ink_p * self.ink.total
        self.ink_i, box = self._draw_segments(self.ink, self.ink_i, effort, self.mline, extra)
        if box:
            self.compose(box)
        pos = self.ink.position(effort)
        if col_p > 0 and self.col.total > 0:
            effort = col_p * self.col.total
            self.col_i, box = self._draw_segments(self.col, self.col_i, effort, self.mcol, None, scale=1.0)
            if box:
                self.compose(box)
            pos = self.col.position(effort)
        return pos

    def finish(self) -> None:
        if self.done:
            return
        self.mline[:] = 255
        if self.mode != "ink_only":
            self.mcol[:] = 255
        self.compose(None)
        self.done = True

    @property
    def last_pos(self) -> tuple[float, float]:
        plan = self.col if (self.col.total > 0 and self.ink_share < 1.0) else self.ink
        return tuple(plan.pts[-1]) if len(plan.pts) else (0.0, 0.0)


# ──────────────────────────────────────────────────────────────
# Transitions
# ──────────────────────────────────────────────────────────────
def transition_frame(kind: str, prev: np.ndarray, new: np.ndarray, q: float, rtl: bool) -> np.ndarray:
    q = _ease(q)
    h, w = prev.shape[:2]
    if kind == "fade":
        return cv2.addWeighted(prev, 1 - q, new, q, 0)
    if kind == "wipe":
        edge = int(q * (w + 120)) - 60
        ramp = np.clip((edge - np.arange(w)) / 60 + 0.5, 0, 1).astype(np.float32)
        if rtl:
            ramp = ramp[::-1]
        r = ramp[None, :, None]
        return (prev * (1 - r) + new * r).astype(np.uint8)
    if kind == "slide":
        dx = int(round(q * w))
        out = np.empty_like(prev)
        if rtl:
            out[:, dx:] = prev[:, :w - dx]
            out[:, :dx] = new[:, w - dx:]
        else:
            out[:, :w - dx] = prev[:, dx:]
            out[:, w - dx:] = new[:, :dx]
        return out
    return new if q >= 1 else prev


# ──────────────────────────────────────────────────────────────
# Main renderer
# ──────────────────────────────────────────────────────────────
class Cancelled(Exception):
    pass


def render_project(project: Project, out_path: Path | None = None, progress: Progress | None = None,
                   cancel: threading.Event | None = None, t_from: float = 0.0, t_to: float | None = None,
                   overrides: dict | None = None) -> Path:
    settings = dict(project.settings)
    if overrides:
        settings.update(overrides)
    timeline = project.load_timeline()
    if timeline is None:
        raise ValueError("Sync the narration first (no timeline yet).")
    narration = project.narration_path()
    images, _ = project.images()
    if not images:
        raise ValueError("No images found. Upload images named 1.png, 2.png, ...")

    fps = int(settings.get("fps", 30))
    W, H = frame_size(settings)
    duration = float(timeline.get("duration") or 0) or max(ln["end"] for ln in timeline["lines"])
    end_time = duration + float(settings.get("tail", 0.6))
    language = project.language()
    rtl = language == "fa"
    mode = settings.get("color_mode", "ink_then_color")
    ink_share = float(settings.get("ink_share", 0.7))
    sync_mode = settings.get("sync_mode", "speech")
    trans_kind = settings.get("transition", "slide")

    bg, dark = make_background(settings.get("background", "whiteboard"), W, H, paths.USER_BACKGROUNDS)
    hand = None
    if settings.get("hand", "marker") != "none":
        hdir = find_hand(settings.get("hand", "marker")) or find_hand("marker")
        if hdir is not None:
            hand = HandSprite(hdir, min(W, H), float(settings.get("hand_scale", 1.0)), H)
    offscreen = (W * 0.82, H * 1.12)

    shots = plan_shots(timeline, images, settings, end_time)
    t_to = end_time if t_to is None else min(t_to, end_time)
    f_from = int(t_from * fps)
    f_to = int(math.ceil(t_to * fps))
    # Start simulating at the shot before the requested range so the board state is right.
    first = 0
    for k, s in enumerate(shots):
        if s.trans_start <= t_from:
            first = max(0, k - 1)
    f_sim = min(f_from, int(shots[first].trans_start * fps)) if shots else f_from

    if out_path is None:
        project.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out_path = project.output_dir / f"{project.slug}-{stamp}.mp4"
    writer = VideoWriter(out_path, W, H, fps, narration, settings.get("quality", "high"),
                         audio_start=t_from, audio_duration=(t_to - t_from) if (t_from > 0 or t_to < end_time) else None)

    pool = ThreadPoolExecutor(max_workers=2)
    futures: dict[int, object] = {}

    def want(k: int):
        if 0 <= k < len(shots) and k not in futures:
            futures[k] = pool.submit(prepare, shots[k].image, W, H, settings, dark, language)

    board = bg.copy()
    prev_board: np.ndarray | None = None
    state: DrawState | None = None
    cur = -1
    nxt = first
    curves: dict[int, np.ndarray] = {}
    t0 = time.time()
    total = max(1, f_to - f_from)
    try:
        for k in range(first, min(first + 2, len(shots))):
            want(k)
        for f in range(f_sim, f_to):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            t = f / fps
            while nxt < len(shots) and t >= shots[nxt].trans_start:
                if state is not None:
                    state.finish()
                prev_board = board.copy() if cur >= 0 else bg.copy()
                board = bg.copy()
                cur = nxt
                nxt += 1
                want(cur)
                want(cur + 1)
                try:
                    drawing = futures.pop(cur).result()
                except Exception as exc:  # unreadable image: keep going without it
                    if progress:
                        progress(f"Skipping image for line {shots[cur].line_id}: {exc}", (f - f_from) / total, {})
                    drawing = None
                state = None
                if drawing is not None:
                    first_pt = (tuple(drawing.strokes[0].points[0]) if drawing.strokes else
                                (drawing.rect[0], drawing.rect[1]))
                    state = DrawState(drawing, board, bg, mode, ink_share, first_pt)
                curves[cur] = progress_curve(shots[cur], fps, sync_mode)
                for old in [k for k in curves if k < cur - 1]:
                    curves.pop(old)

            hand_pos = None
            if cur < 0:
                frame = board
            else:
                shot = shots[cur]
                if t < shot.start and prev_board is not None and trans_kind != "cut":
                    q = (t - shot.trans_start) / max(1e-6, shot.start - shot.trans_start)
                    frame = transition_frame(trans_kind, prev_board, board, q, rtl)
                elif t < shot.start and prev_board is not None:
                    frame = prev_board
                else:
                    frame = board
                    if state is not None and not state.done:
                        if t <= shot.draw_end:
                            curve = curves[cur]
                            i = min(len(curve) - 1, int(round((t - shot.start) * fps)))
                            hand_pos = state.advance(float(curve[i]))
                        else:
                            state.advance(1.0)
                            state.finish()
                hand_pos = _hand_position(t, shots, cur, nxt, state, hand_pos, offscreen)

            if f < f_from:
                continue
            if hand is not None and hand_pos is not None:
                out = frame.copy()
                hand.paste(out, hand_pos[0], hand_pos[1])
                writer.write(out)
            else:
                writer.write(frame)
            done = f - f_from + 1
            if progress and (done % max(1, fps // 2) == 0 or done == total):
                el = time.time() - t0
                eta = el / done * (total - done)
                progress("Rendering", done / total, {"frame": done, "frames": total, "eta": round(eta, 1),
                                                     "line": shots[cur].line_id if cur >= 0 else None})
        writer.close()
    except BaseException:
        writer.abort()
        raise
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return out_path


def still_frame(project: Project, line_id: int | None = None, overrides: dict | None = None,
                max_width: int = 960) -> np.ndarray:
    """A finished drawing on the chosen board with the hand: quick style preview."""
    settings = dict(project.settings)
    if overrides:
        settings.update(overrides)
    W, H = frame_size(settings)
    bg, dark = make_background(settings.get("background", "whiteboard"), W, H, paths.USER_BACKGROUNDS)
    board = bg.copy()
    images, _ = project.images()
    if images:
        if line_id is None or line_id not in images:
            line_id = min(images)
        d = prepare(images[line_id], W, H, settings, dark, project.language())
        state = DrawState(d, board, bg, settings.get("color_mode", "ink_then_color"), 0.7,
                          (d.rect[0], d.rect[1]))
        state.finish()
        pos = tuple(d.strokes[len(d.strokes) * 2 // 3].points[-1]) if d.strokes else (W * 0.6, H * 0.6)
    else:
        pos = (W * 0.6, H * 0.6)
    if settings.get("hand", "marker") != "none":
        hdir = find_hand(settings.get("hand", "marker"))
        if hdir is not None:
            HandSprite(hdir, min(W, H), float(settings.get("hand_scale", 1.0)), H).paste(board, pos[0], pos[1])
    if W > max_width:
        board = cv2.resize(board, (max_width, int(H * max_width / W)), interpolation=cv2.INTER_AREA)
    return board


def _hand_position(t: float, shots: list[Shot], cur: int, nxt: int, state: DrawState | None,
                   drawing_pos, offscreen) -> tuple[float, float] | None:
    """Where the hand is: drawing, walking in before a line, or leaving after it."""
    if drawing_pos is not None:
        return drawing_pos
    shot = shots[cur]
    entry = 0.4
    # Walking in just before the line starts.
    if state is not None and not state.done and t < shot.start:
        first = state.ink.pts[1] if len(state.ink.pts) > 1 else state.ink.pts[0]
        q = 1 - (shot.start - t) / entry
        if q <= 0:
            return None
        q = 1 - (1 - q) ** 2
        return (offscreen[0] + (first[0] - offscreen[0]) * q, offscreen[1] + (first[1] - offscreen[1]) * q)
    # Leaving after the drawing is finished.
    if state is not None and t > shot.draw_end:
        next_start = shots[nxt].start if nxt < len(shots) else shot.draw_end + 10
        exit_d = min(0.6, max(0.15, (next_start - shot.draw_end) * 0.4))
        q = (t - shot.draw_end) / exit_d
        if q >= 1:
            return None
        q = q * q
        last = state.last_pos
        return (last[0] + (offscreen[0] - last[0]) * q, last[1] + (offscreen[1] - last[1]) * q)
    return None
