"""One shot on the board, frame by frame: picture, handwriting and the hand.

The shot's timing comes from schedule.py; this module turns it into board
pixels and a hand position for every frame.

A picture is drawn as a list of parts: the outline of each segment, then
its colouring (or, when a picture is not coloured in, a gentle fade of the
colours that the outline did not cover). An SVG made of timed parts
(data-word="...") has one segment per part, and each one waits for its word.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .board import Board, ColorReveal, Layer, PenPlan, Region, Reveal, build_plan, with_rest
from .clips import ClipReader, PreparedClip
from .drawing import PreparedDrawing
from .handwriting import PreparedText
from .schedule import Shot, cue_indices, progress_curve, write_progress

FADE_SHARE = 0.12     # share of the drawing time used to fade in colours that are not coloured by hand


@dataclass
class HandState:
    pos: tuple[float, float]
    down: bool            # pen touching the board
    kind: str             # "ink" | "color" | "write" | "move" | "rest"


@dataclass
class Part:
    kind: str                         # "ink" | "color" | "fade"
    reveal: Reveal | ColorReveal | None
    effort: float
    segment: int
    done: bool = False


def _ease(q: float) -> float:
    q = min(1.0, max(0.0, q))
    return q * q * (3 - 2 * q)


def _lerp(a, b, q):
    return (a[0] + (b[0] - a[0]) * q, a[1] + (b[1] - a[1]) * q)


def colour_pass(drawing: PreparedDrawing, mode: str, coloring: str) -> bool:
    """Does this picture get a colouring pass? ("auto": only when it has colour to add)."""
    if mode == "ink_only" or not drawing.regions:
        return False
    return coloring == "on" or (coloring == "auto" and drawing.colorful)


class ShotScene:
    def __init__(self, shot: Shot, board: Board, drawing: PreparedDrawing | None, text: PreparedText | None,
                 mode: str, ink_share: float, fps: int, sync_mode: str, coloring: str = "auto"):
        self.shot = shot
        self.board = board
        self.fps = fps
        self.done = False
        self.appear = shot.mode == "appear"
        self.image_done = drawing is None
        self.parts: list[Part] = []
        self.bounds: list[float] = [0.0]
        self.part_i = 0
        self.curve = None
        self.layers: list[Layer] = []
        self.text: Reveal | None = None
        self.text_layer: Layer | None = None
        self.img_pos: tuple[float, float] | None = None
        self.last_pos: tuple[float, float] | None = None
        self.last_p = -1.0
        self.word_masks: dict[int, tuple[int, int, np.ndarray]] = {}
        self.word_level: dict[int, float] = {}
        self.clip: ClipReader | None = None
        self.clip_layer: Layer | None = None

        if isinstance(drawing, PreparedClip):
            self._start_clip(drawing)
            drawing = None
        elif drawing is not None:
            line = board.add(Layer(drawing.rect, drawing.line_rgb, drawing.line_a))
            full = None if mode == "ink_only" else board.add(Layer(drawing.rect, drawing.full_rgb, drawing.full_a))
            self.layers = [line] + ([full] if full is not None else [])
            if not self.appear:
                self._plan_picture(drawing, line, full, mode, ink_share, coloring, sync_mode)

        # Handwriting: one pen route through all written words; each word owns a slice of it.
        self.word_range: dict[int, tuple[float, float]] = {}
        self.word_start: dict[int, tuple[float, float]] = {}
        if text is not None and text.words:
            layer = board.add(Layer(text.rect, text.rgb, text.alpha))
            self.text_layer = layer
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
            if self.appear:
                self._word_masks(text, layer, line_index)
        self.text_effort = 0.0

    # ── video clips ───────────────────────────────────────
    def _start_clip(self, clip: PreparedClip) -> None:
        x0, y0, x1, y1 = clip.rect
        self.clip = ClipReader(clip, self.fps, clip.still_at)
        self.clip_layer = self.board.add(Layer(clip.rect, np.zeros((y1 - y0, x1 - x0, 3), np.float32),
                                               np.zeros((y1 - y0, x1 - x0), np.float32)))
        self.clip_layer.reveal_all()
        self._show_clip(0)          # the first frame is already there during the transition

    def _show_clip(self, k: int) -> None:
        got = self.clip.frame(k)
        if got is not None:
            self.clip_layer.rgb, self.clip_layer.alpha = got
            self.board.compose(list(self.clip_layer.rect))

    # ── planning ──────────────────────────────────────────
    def _plan_picture(self, drawing: PreparedDrawing, line: Layer, full: Layer | None, mode: str,
                      ink_share: float, coloring: str, sync_mode: str) -> None:
        colour = full is not None and colour_pass(drawing, mode, coloring)
        ink_full = full is not None and (mode == "color_strokes" or not colour)
        fade = full is not None and not colour and bool(drawing.regions)
        targets = [(line, 1.0)] + ([(full, 1.5)] if ink_full else [])
        rect = drawing.rect
        pen = tuple(drawing.strokes[0].points[0]) if drawing.strokes else (rect[0], rect[1])
        segments = drawing.parts()
        for si, seg in enumerate(segments):
            strokes = drawing.strokes[seg.strokes[0]:seg.strokes[1]]
            if strokes:
                plan, _ = build_plan([(s.points, s.radius) for s in strokes], pen)
                self.parts.append(Part("ink", Reveal(plan, targets), plan.total, si))
                pen = plan.end
            regs = drawing.regions[seg.regions[0]:seg.regions[1]] if colour else []
            polys, ids = [], []
            for k, r in enumerate(regs):
                for p in r.paths:
                    polys.append((p, np.full(len(p), r.radius, np.float32)))
                    ids.append(k)
            if polys:
                plan, spans = build_plan(polys, pen, lift_cost=0.25, lift_pause=4.0, ids=ids)
                own = [0.0] * len(regs)
                for (a, b), k in zip(spans, ids):
                    own[k] += float(plan.cum[b] - plan.cum[max(0, a - 1)])
                settle = [max(30.0, 0.2 * e) for e in own]
                plan = with_rest(plan, settle[-1])
                reveal = ColorReveal(plan, full, [Region(r.x0, r.y0, r.mask) for r in regs], settle,
                                     seed=int(rect[0] * 7 + rect[1] + si))
                self.parts.append(Part("color", reveal, plan.total, si))
                pen = plan.end
        if fade or not self.parts:
            self.parts.append(Part("fade", None, 0.0, len(segments) - 1))

        ink_total = sum(p.effort for p in self.parts if p.kind == "ink")
        col_total = sum(p.effort for p in self.parts if p.kind == "color")
        share = ink_share if ink_total > 0 and col_total > 0 else (1.0 if ink_total > 0 else 0.0)
        has_fade = any(p.kind == "fade" for p in self.parts)
        fade_w = 1.0 if has_fade and ink_total + col_total <= 0 else (FADE_SHARE if has_fade else 0.0)
        for p in self.parts:
            if p.kind == "ink":
                wgt = share * p.effort / ink_total * (1 - fade_w)
            elif p.kind == "color":
                wgt = (1 - share) * p.effort / col_total * (1 - fade_w)
            else:
                wgt = fade_w
            self.bounds.append(self.bounds[-1] + wgt)
        total = self.bounds[-1] or 1.0
        self.bounds = [b / total for b in self.bounds]

        # Timed parts wait for their word.
        anchors = []
        cue_idx = cue_indices([seg.cue for seg in segments], self.shot.words) if drawing.segments else []
        for si, idx in enumerate(cue_idx):
            if idx is None:
                continue
            first = next((j for j, p in enumerate(self.parts) if p.segment == si), None)
            if first is not None:
                anchors.append((float(self.shot.words[idx]["s"]), self.bounds[first]))
        self.curve = progress_curve(self.shot, self.fps, sync_mode, anchors or None)
        first_plan = next((p.reveal.plan for p in self.parts if p.reveal is not None), None)
        self.img_pos = first_plan.start if first_plan is not None else None

    def _word_masks(self, text: PreparedText, layer: Layer, line_index: list[int]) -> None:
        """Short lines: where each word sits on the text layer, so it can fade in on its own."""
        ox, oy = layer.rect[0], layer.rect[1]
        for j, ww in enumerate(text.words):
            pts = [s.points for s in ww.strokes if len(s.points)]
            if not pts:
                continue
            allp = np.concatenate(pts)
            r = max(float(s.radius.max()) for s in ww.strokes if len(s.points)) + 2
            x0 = max(0, int(allp[:, 0].min() - r) - ox)
            y0 = max(0, int(allp[:, 1].min() - r) - oy)
            x1 = min(layer.mask.shape[1], int(allp[:, 0].max() + r) - ox + 1)
            y1 = min(layer.mask.shape[0], int(allp[:, 1].max() + r) - oy + 1)
            if x0 >= x1 or y0 >= y1:
                continue
            m = np.zeros((y1 - y0, x1 - x0), np.uint8)
            for s in ww.strokes:
                for a, b, rad in zip(s.points[:-1], s.points[1:], s.radius[1:]):
                    cv2.line(m, (int(round(a[0] - ox - x0)), int(round(a[1] - oy - y0))),
                             (int(round(b[0] - ox - x0)), int(round(b[1] - oy - y0))), 255,
                             max(1, int(round(2 * rad))), cv2.LINE_AA)
                if len(s.points) == 1:
                    p = s.points[0]
                    cv2.circle(m, (int(round(p[0] - ox - x0)), int(round(p[1] - oy - y0))),
                               max(1, int(round(s.radius[0]))), 255, -1, cv2.LINE_AA)
            li = line_index[j] if j < len(line_index) else j
            self.word_masks[li] = (x0, y0, m)

    # ── picture ───────────────────────────────────────────
    def _advance_part(self, part: Part, q: float) -> HandState | None:
        if part.kind == "fade":
            for layer in self.layers:
                box = layer.fade_in(_ease(q))
                if box:
                    self.board.compose(box)
            pos = self.img_pos or self.last_pos
            return HandState(pos, False, "rest") if pos is not None else None
        e = q * part.effort
        box = part.reveal.advance(e)
        if box:
            self.board.compose(box)
        plan = part.reveal.plan
        return HandState(plan.position(e), plan.is_down(e), part.kind)

    def _image_at(self, p: float) -> HandState | None:
        state = None
        while self.part_i < len(self.parts):
            j = self.part_i
            part = self.parts[j]
            a, b = self.bounds[j], self.bounds[j + 1]
            if p >= b:
                self._advance_part(part, 1.0)
                part.done = True
                self.part_i += 1
                continue
            q = (p - a) / (b - a) if b > a else 1.0
            state = self._advance_part(part, max(0.0, q))
            break
        if state is None and self.parts:
            last = next((pt for pt in reversed(self.parts) if pt.reveal is not None), None)
            if last is not None:
                state = HandState(last.reveal.plan.end, False, "rest")
        if state is not None:
            if p <= self.last_p + 1e-9 and state.kind in ("ink", "color"):
                state = HandState(state.pos, False, "rest")      # waiting for the next word: pen up
            self.img_pos = state.pos
        self.last_p = p
        return state

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
        if self.appear:
            return None
        if shot.writes and (shot.kind == "text" or (shot.busy and shot.busy[0][0] <= shot.start + 1e-3)):
            w = shot.writes[0]
            if w.word in self.word_start:
                return self.word_start[w.word]
        first = next((p.reveal.plan for p in self.parts if p.reveal is not None), None)
        if first is not None:
            return first.start
        return None

    # ── short lines: everything fades in, no hand ─────────
    def _appear_update(self, t: float) -> None:
        shot = self.shot
        if self.layers:
            span = max(1e-3, shot.image_end - shot.start)
            q = _ease((t - shot.start) / span)
            for layer in self.layers:
                box = layer.fade_in(q)
                if box:
                    self.board.compose(box)
        if self.text_layer is not None:
            ox, oy = self.text_layer.rect[0], self.text_layer.rect[1]
            for w in shot.writes:
                if w.word not in self.word_masks or t < w.t0:
                    continue
                q = _ease((t - w.t0) / max(1e-3, w.t1 - w.t0))
                if q <= self.word_level.get(w.word, 0.0):
                    continue
                self.word_level[w.word] = q
                x0, y0, m = self.word_masks[w.word]
                roi = self.text_layer.mask[y0:y0 + m.shape[0], x0:x0 + m.shape[1]]
                np.maximum(roi, cv2.convertScaleAbs(m, alpha=q), out=roi)
                self.board.compose([x0 + ox, y0 + oy, x0 + ox + m.shape[1], y0 + oy + m.shape[0]])

    # ── per frame ─────────────────────────────────────────
    def update(self, t: float) -> HandState | None:
        """Advance the board to time t. Returns where the hand is (None = off the board)."""
        shot = self.shot
        if self.done or t < shot.start:
            return None
        if self.clip is not None:
            self._show_clip(max(0, int(round((t - shot.start) * self.fps))))
            return None
        if self.appear:
            self._appear_update(t)
            return None

        img_state = None
        busy_now = next(((a, b) for a, b in shot.busy if a <= t < b), None)
        if self.parts and not self.image_done:
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
        self.close()

    def close(self) -> None:
        """Free what the shot holds open (a clip's decoder)."""
        if self.clip is not None:
            self.clip.close()
            self.clip = None
