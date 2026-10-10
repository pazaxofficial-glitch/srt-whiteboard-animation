"""One shot on the board, frame by frame: picture, handwriting and the hand.

The shot's timing comes from schedule.py; this module turns it into board
pixels and a hand position for every frame.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .board import Board, Layer, PenPlan, Reveal, build_plan
from .drawing import PreparedDrawing
from .handwriting import PreparedText
from .schedule import Shot, progress_curve, write_progress


@dataclass
class HandState:
    pos: tuple[float, float]
    down: bool            # pen touching the board
    kind: str             # "ink" | "color" | "write" | "move" | "rest"


def _ease(q: float) -> float:
    q = min(1.0, max(0.0, q))
    return q * q * (3 - 2 * q)


def _lerp(a, b, q):
    return (a[0] + (b[0] - a[0]) * q, a[1] + (b[1] - a[1]) * q)


class ShotScene:
    def __init__(self, shot: Shot, board: Board, drawing: PreparedDrawing | None, text: PreparedText | None,
                 mode: str, ink_share: float, fps: int, sync_mode: str):
        self.shot = shot
        self.board = board
        self.fps = fps
        self.done = False
        self.image_done = drawing is None
        self.ink: Reveal | None = None
        self.col: Reveal | None = None
        self.text: Reveal | None = None
        self.curve = None
        self.ink_share = 1.0
        self.img_pos: tuple[float, float] | None = None
        self.last_pos: tuple[float, float] | None = None

        if drawing is not None:
            line = board.add(Layer(drawing.rect, drawing.line_rgb, drawing.line_a))
            full = None if mode == "ink_only" else board.add(Layer(drawing.rect, drawing.full_rgb, drawing.full_a))
            self.ink_share = 1.0 if mode == "ink_only" else (ink_share if drawing.color_paths else 1.0)
            if not drawing.strokes and drawing.color_paths and mode != "ink_only":
                self.ink_share = 0.0
            start = tuple(drawing.strokes[0].points[0]) if drawing.strokes else (drawing.rect[0], drawing.rect[1])
            ink_plan, _ = build_plan([(s.points, s.radius) for s in drawing.strokes], start)
            targets = [(line, 1.0)]
            if mode == "color_strokes" and full is not None:
                targets.append((full, 1.5))
            self.ink = Reveal(ink_plan, targets)
            if full is not None and drawing.color_paths:
                col_plan, _ = build_plan([(p, np.full(len(p), r, np.float32)) for p, r in drawing.color_paths],
                                         ink_plan.end, lift_cost=0.25, lift_pause=4.0)
                self.col = Reveal(col_plan, [(full, 1.0)])
            self.curve = progress_curve(shot, fps, sync_mode)
            self.img_pos = ink_plan.start

        # Handwriting: one pen route through all written words; each word owns a slice of it.
        self.word_range: dict[int, tuple[float, float]] = {}
        self.word_start: dict[int, tuple[float, float]] = {}
        if text is not None and text.words:
            layer = board.add(Layer(text.rect, text.rgb, text.alpha))
            polylines, owners = [], []
            for j, ww in enumerate(text.words):
                for s in ww.strokes:
                    polylines.append((s.points, s.radius))
                    owners.append(j)
            first_pt = polylines[0][0][0] if polylines else (text.rect[0], text.rect[1])
            plan, spans = build_plan(polylines, tuple(first_pt), lift_cost=0.3, lift_pause=6.0)
            self.text = Reveal(plan, [(layer, 1.0)])
            line_index = shot.write_words
            for j in range(len(text.words)):
                own = [spans[k] for k, o in enumerate(owners) if o == j]
                li = line_index[j] if j < len(line_index) else j
                if own:
                    a = plan.cum[max(0, own[0][0] - 1)]
                    b = plan.cum[own[-1][1]]
                    self.word_range[li] = (float(a), float(b))
                    self.word_start[li] = (float(plan.pts[own[0][0]][0]), float(plan.pts[own[0][0]][1]))
        self.text_effort = 0.0

    # ── picture ───────────────────────────────────────────
    def _image_at(self, p: float) -> HandState:
        ink_p = min(1.0, p / self.ink_share) if self.ink_share > 0 else 1.0
        col_p = 0.0 if self.ink_share >= 1.0 else max(0.0, (p - self.ink_share) / (1 - self.ink_share))
        e = ink_p * self.ink.plan.total
        box = self.ink.advance(e)
        if box:
            self.board.compose(box)
        pos, down, kind = self.ink.plan.position(e), self.ink.plan.is_down(e), "ink"
        if col_p > 0 and self.col is not None:
            e = col_p * self.col.plan.total
            box = self.col.advance(e)
            if box:
                self.board.compose(box)
            pos, down, kind = self.col.plan.position(e), self.col.plan.is_down(e), "color"
        self.img_pos = pos
        return HandState(pos, down, kind)

    def _picture_progress(self, t: float) -> float:
        shot = self.shot
        if t >= shot.image_end:
            return 1.0
        i = int(round((t - shot.start) * self.fps))
        return float(self.curve[min(len(self.curve) - 1, max(0, i))])

    # ── handwriting ───────────────────────────────────────
    def _text_target(self, t: float) -> float:
        target = self.text_effort
        for w in self.shot.writes:
            if w.word not in self.word_range or t < w.t0:
                continue
            a, b = self.word_range[w.word]
            target = max(target, a + (b - a) * write_progress(w, t))
        return target

    def entry_target(self) -> tuple[float, float] | None:
        """Where the hand goes first when it walks onto the board."""
        shot = self.shot
        if shot.writes and (shot.kind == "text" or (shot.busy and shot.busy[0][0] <= shot.start + 1e-3)):
            w = shot.writes[0]
            if w.word in self.word_start:
                return self.word_start[w.word]
        if self.ink is not None:
            return self.ink.plan.start
        return None

    # ── per frame ─────────────────────────────────────────
    def update(self, t: float) -> HandState | None:
        """Advance the board to time t. Returns where the hand is (None = off the board)."""
        shot = self.shot
        if self.done or t < shot.start:
            return None

        img_state = None
        busy_now = next(((a, b) for a, b in shot.busy if a <= t < b), None)
        if self.ink is not None and not self.image_done:
            p = self._picture_progress(t)
            img_state = self._image_at(p)
            if p >= 1.0:
                self.image_done = True

        txt_state = None
        if self.text is not None:
            e = self._text_target(t)
            if e > self.text_effort:
                box = self.text.advance(e)
                if box:
                    self.board.compose(box)
                self.text_effort = max(self.text_effort, e)
            active = next((w for w in shot.writes if w.t0 <= t < w.t1 and w.word in self.word_range), None)
            plan: PenPlan = self.text.plan
            if active is not None:
                txt_state = HandState(plan.position(self.text_effort), plan.is_down(self.text_effort), "write")
            elif shot.kind == "text":
                txt_state = HandState(plan.position(self.text_effort), False, "rest")
            elif busy_now is not None:
                a, b = busy_now
                inside = [w for w in shot.writes if a <= w.t0 < b and w.word in self.word_range]
                if inside:
                    first, last = inside[0], inside[-1]
                    here = self.img_pos or self.word_start[first.word]
                    if t < first.t0:          # moving from the picture to the text
                        q = _ease((t - a) / max(1e-6, first.t0 - a))
                        txt_state = HandState(_lerp(here, self.word_start[first.word], q), False, "move")
                    elif t >= last.t1:        # moving back to the picture
                        end = plan.position(self.word_range[last.word][1])
                        back = self.img_pos if not self.image_done else end
                        q = _ease((t - last.t1) / max(1e-6, b - last.t1))
                        txt_state = HandState(_lerp(end, back, q), False, "move")
                    else:                     # between two written words
                        txt_state = HandState(plan.position(self.text_effort), False, "rest")

        state = txt_state or img_state
        if state is None and self.last_pos is not None and t < shot.draw_end:
            state = HandState(self.last_pos, False, "rest")   # waiting for the next word
        if state is not None:
            self.last_pos = state.pos
        return state

    def finish(self) -> None:
        if not self.done:
            self.board.finish()
            self.done = True
