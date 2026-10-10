"""Build the whole video: every script line drawn (or written) in time with the voice.

    plan shots (schedule.py) -> prepare pictures and handwriting (in background
    threads) -> for every frame: board + transitions + hand + captions ->
    FFmpeg -> audio mix (narration, drawing sounds, music) -> MP4 (+ SRT)
"""
from __future__ import annotations

import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from .. import paths
from ..project import Project
from . import audio
from .backgrounds import make_background
from .board import Board
from .captions import CaptionRenderer, build_chunks, write_srt
from .drawing import PreparedDrawing, content_area, prepare
from .encoder import VideoWriter
from .hands import HandRig, find_hand
from .handwriting import PreparedText, prepare_text
from .scene import ShotScene
from .schedule import Shot, plan_shots
from .text import FontPair

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


def script_marks(project: Project) -> dict[int, list[int]]:
    """Line id -> indices of the words marked *like this* in the script."""
    return {ln.id: ln.marks for ln in project.lines() if ln.marks}


# ──────────────────────────────────────────────────────────────
# Layout of one shot
# ──────────────────────────────────────────────────────────────
@dataclass
class ShotLayout:
    image_area: tuple[int, int, int, int] | None
    text_area: tuple[int, int, int, int] | None
    text_size: float
    text_lines: int | None


def shot_layout(shot: Shot, W: int, H: int, settings: dict, caption_band: tuple[int, int] | None) -> ShotLayout:
    x0, y0, x1, y1 = content_area(W, H, settings)
    if caption_band is not None:
        b0, b1 = caption_band
        if b0 <= 0:
            y0 = max(y0, b1)
        else:
            y1 = min(y1, b0)
    base = min(W, H)
    if shot.kind == "text":
        px, py = int((x1 - x0) * 0.04), int((y1 - y0) * 0.06)
        return ShotLayout(None, (x0 + px, y0 + py, x1 - px, y1 - py), base * 0.13, None)
    if not shot.writes:
        return ShotLayout((x0, y0, x1, y1), None, 0, None)
    band = max(int(H * 0.12), int((y1 - y0) * 0.2))
    gap = int(H * 0.015)
    if settings.get("text_position", "bottom") == "top":
        text = (x0, y0, x1, y0 + band)
        image = (x0, y0 + band + gap, x1, y1)
    else:
        text = (x0, y1 - band, x1, y1)
        image = (x0, y0, x1, y1 - band - gap)
    return ShotLayout(image, text, band * 0.78, 2)


def prepare_shot(shot: Shot, W: int, H: int, settings: dict, dark: bool, language: str,
                 caption_band: tuple[int, int] | None) -> tuple[PreparedDrawing | None, PreparedText | None]:
    lay = shot_layout(shot, W, H, settings, caption_band)
    drawing = prepare(shot.image, lay.image_area, settings, dark, language) if shot.image is not None else None
    text = None
    if lay.text_area is not None and shot.write_words:
        words = [shot.words[i]["w"] for i in shot.write_words if i < len(shot.words)]
        fonts = FontPair.get(settings.get("font_latin", "marker"), settings.get("font_rtl", "naskh"))
        text = prepare_text(words, fonts, lay.text_area, settings.get("text_color", "auto"), dark,
                            lay.text_size, max_lines=lay.text_lines)
    return drawing, text


# ──────────────────────────────────────────────────────────────
# Transitions
# ──────────────────────────────────────────────────────────────
def _ease(q: float) -> float:
    q = min(1.0, max(0.0, q))
    return q * q * (3 - 2 * q)


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


def _curve_path(a, b, q: float, bend: float = 0.25) -> tuple[float, float]:
    """Point on a gentle arc from a to b (the hand swings in rather than sliding)."""
    q = min(1.0, max(0.0, q))
    cx = a[0] + (b[0] - a[0]) * 0.5 + (b[1] - a[1]) * bend
    cy = a[1] + (b[1] - a[1]) * 0.5 - abs(b[0] - a[0]) * bend * 0.5
    x = (1 - q) ** 2 * a[0] + 2 * (1 - q) * q * cx + q * q * b[0]
    y = (1 - q) ** 2 * a[1] + 2 * (1 - q) * q * cy + q * q * b[1]
    return (x, y)


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
    if not images and settings.get("text_lines", "write") != "write":
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
            hand = HandRig(hdir, W, H, float(settings.get("hand_scale", 1.0)),
                           mirror=bool(settings.get("hand_mirror", False)),
                           motion=bool(settings.get("hand_motion", True)),
                           shadow=bool(settings.get("hand_shadow", True)))
    offscreen = hand.offscreen if hand else (W * 0.82, H * 1.12)
    captions = CaptionRenderer(timeline, W, H, settings)
    cap_band = captions.band() if captions.enabled else None

    shots = plan_shots(timeline, images, settings, end_time, script_marks(project))
    if not shots:
        raise ValueError("Nothing to draw: no line has an image (and writing lines as text is off).")
    t_to = end_time if t_to is None else min(t_to, end_time)
    f_from = int(t_from * fps)
    f_to = int(math.ceil(t_to * fps))
    # Start simulating at the shot before the requested range so the board state is right.
    first = 0
    for k, s in enumerate(shots):
        if s.trans_start <= t_from:
            first = max(0, k - 1)
    f_sim = min(f_from, int(shots[first].trans_start * fps))

    if out_path is None:
        project.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out_path = project.output_dir / f"{project.slug}-{stamp}.mp4"
    video_tmp = out_path.with_name(out_path.stem + ".video.mp4")
    writer = VideoWriter(video_tmp, W, H, fps, None, settings.get("quality", "high"))
    log = audio.ActivityLog(fps, f_from, f_to, math.hypot(W, H))

    pool = ThreadPoolExecutor(max_workers=2)
    futures: dict[int, object] = {}

    def want(k: int):
        if 0 <= k < len(shots) and k not in futures:
            futures[k] = pool.submit(prepare_shot, shots[k], W, H, settings, dark, language, cap_band)

    board = Board(bg)
    prev_img: np.ndarray | None = None
    scene: ShotScene | None = None
    cur = -1
    nxt = first
    t0 = time.time()
    total = max(1, f_to - f_from)
    dt = 1.0 / fps
    try:
        for k in range(first, min(first + 2, len(shots))):
            want(k)
        for f in range(f_sim, f_to):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            t = f / fps
            while nxt < len(shots) and t >= shots[nxt].trans_start:
                if scene is not None:
                    scene.finish()
                prev_img = board.img.copy() if cur >= 0 else bg.copy()
                board = Board(bg)
                cur = nxt
                nxt += 1
                want(cur)
                want(cur + 1)
                try:
                    drawing, text = futures.pop(cur).result()
                except Exception as exc:  # unreadable image: keep going without it
                    if progress:
                        progress(f"Skipping line {shots[cur].line_id}: {exc}", max(0.0, (f - f_from) / total), {})
                    drawing, text = None, None
                scene = ShotScene(shots[cur], board, drawing, text, mode, ink_share, fps, sync_mode)
                if cur > 0 and trans_kind != "cut" and shots[cur].start > shots[cur].trans_start:
                    log.event(shots[cur].trans_start, "whoosh" if trans_kind in ("slide", "fade") else "erase",
                              shots[cur].start - shots[cur].trans_start)

            hand_state = None
            if cur < 0:
                frame = board.img
            else:
                shot = shots[cur]
                if t < shot.start:
                    if prev_img is not None and trans_kind != "cut" and shot.start > shot.trans_start:
                        q = (t - shot.trans_start) / max(1e-6, shot.start - shot.trans_start)
                        frame = transition_frame(trans_kind, prev_img, board.img, q, rtl)
                    else:
                        frame = prev_img if prev_img is not None else board.img
                    target = scene.entry_target() if scene is not None else None
                    if target is not None and shot.start - t < 0.4:
                        q = 1 - (1 - (1 - (shot.start - t) / 0.4)) ** 2
                        hand_state = ("move", _curve_path(offscreen, target, q), False)
                else:
                    frame = board.img
                    if scene is not None and not scene.done:
                        st = scene.update(min(t, shot.draw_end))
                        if t > shot.draw_end:
                            scene.finish()
                        elif st is not None:
                            hand_state = (st.kind, st.pos, st.down)
                    if hand_state is None and scene is not None and scene.last_pos is not None and t > shot.draw_end:
                        next_start = shots[nxt].start if nxt < len(shots) else shot.draw_end + 10
                        exit_d = min(0.6, max(0.15, (next_start - shot.draw_end) * 0.4))
                        q = (t - shot.draw_end) / exit_d
                        if q < 1:
                            hand_state = ("move", _curve_path(scene.last_pos, offscreen, q * q, -0.2), False)

            if hand_state is None and hand is not None:
                hand.reset()
            log.record(f, hand_state)
            if f < f_from:
                continue
            if (hand is not None and hand_state is not None) or captions.enabled:
                out = frame.copy()
                if hand is not None and hand_state is not None:
                    hand.draw(out, hand_state[1][0], hand_state[1][1], t, hand_state[2], dt)
                captions.draw(out, t)
                writer.write(out)
            else:
                writer.write(frame)
            done = f - f_from + 1
            if progress and (done % max(1, fps // 2) == 0 or done == total):
                el = time.time() - t0
                eta = el / done * (total - done)
                progress("Rendering", done / total * 0.97, {"frame": done, "frames": total, "eta": round(eta, 1),
                                                            "line": shots[cur].line_id if cur >= 0 else None})
        writer.close()
    except BaseException:
        writer.abort()
        raise
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    try:
        if progress:
            progress("Mixing audio", 0.98, {})
        audio.finalize(video_tmp, out_path, narration, log, settings, dark, t_from, t_to, cancel)
    finally:
        if video_tmp.exists():
            video_tmp.unlink()
    if t_from <= 0 and t_to >= end_time - 1e-6:
        write_srt(build_chunks(timeline), out_path.with_suffix(".srt"))
    return out_path


def still_frame(project: Project, line_id: int | None = None, overrides: dict | None = None,
                max_width: int = 960) -> np.ndarray:
    """The finished board for one line, with hand and captions: quick style preview."""
    settings = dict(project.settings)
    if overrides:
        settings.update(overrides)
    W, H = frame_size(settings)
    bg, dark = make_background(settings.get("background", "whiteboard"), W, H, paths.USER_BACKGROUNDS)
    images, _ = project.images()
    timeline = project.load_timeline()
    marks = script_marks(project)
    shot = None
    if timeline is not None:
        shots = plan_shots(timeline, images, settings, float(timeline.get("duration") or 60) + 1, marks)
        pick = [s for s in shots if line_id is None or s.line_id == line_id]
        shot = pick[0] if pick else (shots[0] if shots else None)
    if shot is None and images:
        lid = line_id if line_id in images else min(images)
        shot = Shot(lid, images[lid], 0.0, 0.0, 1.0, 1.0)
    captions = CaptionRenderer(timeline, W, H, settings) if timeline is not None else None
    cap_band = captions.band() if captions is not None and captions.enabled else None
    board = Board(bg)
    pos = (W * 0.6, H * 0.6)
    if shot is not None:
        drawing, text = prepare_shot(shot, W, H, settings, dark, project.language(), cap_band)
        scene = ShotScene(shot, board, drawing, text, settings.get("color_mode", "ink_then_color"), 0.7, 30, "linear")
        scene.finish()
        strokes = (text.strokes if text is not None and text.strokes else
                   drawing.strokes if drawing is not None else [])
        if strokes:
            pos = tuple(strokes[len(strokes) * 2 // 3].points[-1])
    img = board.img.copy()
    if settings.get("hand", "marker") != "none":
        hdir = find_hand(settings.get("hand", "marker")) or find_hand("marker")
        if hdir is not None:
            rig = HandRig(hdir, W, H, float(settings.get("hand_scale", 1.0)),
                          mirror=bool(settings.get("hand_mirror", False)),
                          motion=bool(settings.get("hand_motion", True)),
                          shadow=bool(settings.get("hand_shadow", True)))
            rig.draw(img, pos[0], pos[1], 0.0, True, 0.0)
    if captions is not None and captions.enabled and shot is not None:
        c = next((c for c in captions.chunks if c.line_id == shot.line_id), None)
        if c is not None:
            captions.draw(img, c.times[min(1, len(c.times) - 1)][0] + 0.01)
    if W > max_width:
        img = cv2.resize(img, (max_width, int(H * max_width / W)), interpolation=cv2.INTER_AREA)
    return img
