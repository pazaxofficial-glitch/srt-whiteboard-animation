# Simple Whiteboard Animation

Narration + numbered script + one image per line → hand-drawn whiteboard MP4,
synced to the voice. Python (OpenCV, NumPy, scikit-image, svgelements),
FastAPI web UI, FFmpeg for encoding, Whisper for speech timing.

**New session? Read `docs/ROADMAP.md` first**: current status, what is and is
not verified, known limitations and the agreed next phases.

## If the user asks you to draw / make the images (scenes) for a project

Follow `.claude/skills/draw-whiteboard-images/SKILL.md` and
`docs/svg-style-guide.md` exactly. In short: for each line N of
`data/projects/<project>/script.txt`, write
`data/projects/<project>/images/N.svg` (1600×900 viewBox, stroked line art,
`fill="none"` by default, document order = drawing order, objects grouped
with `data-word="..."` so they are drawn on their word). The author's own
instructions are in `project.json` → `settings.claude_brief`. Work in batches,
and after each batch run `python -m swa lint-svg <project>` and
`python -m swa sheet <project> --lines A-B`, then look at `contact-sheet.png`.
The app's "Claude draws them" button runs exactly this through
`swa/claude.py` (headless `claude -p` with a task file).

## Code map

- `swa/project.py` — project folder model, script parsing (`1.`, `1)`, `[1]`, plain lines, `*marked*` words), image ↔ line mapping by number in file name, settings defaults
- `swa/align.py` — Whisper (faster-whisper or openai-whisper) word timestamps, script↔transcript alignment (difflib), SRT import, even estimate
- `swa/render/schedule.py` — pure timing: shots per line (`kind` image/text/clip, `mode` draw/appear for short lines, `trans_kind` incl. Mix), when marked words are written (`writes`), when the hand is away from the picture (`busy`), picture progress curve with word anchors for `data-word` parts
- `swa/render/scene.py` — one shot frame by frame: the picture as a list of parts (outline → colouring per segment, or a fade), handwriting, short-line fade-ins, clip playback, hand position and pen state
- `swa/render/board.py` — board layers with reveal masks, pen plans (effort units), `Reveal` (pen) and `ColorReveal` (marker colouring clipped to a region, streaky, settles when the region is done)
- `swa/render/drawing.py` — image → layers (line art, full colour) + pen strokes + colour regions (raster: colour clusters; SVG: each visible fill) + `colorful` flag (auto colouring) + `data-word` segments; chalk colours for dark boards
- `swa/render/strokes.py` — skeletonize, trace, order strokes, dabs for dots, `hatch` (marker strokes that colour a region)
- `swa/render/clips.py` — MP4/WebM/MOV clips as pictures: probe, decode to the board, key out a plain background
- `swa/render/text.py` — HarfBuzz shaping + fontTools outlines, mini-bidi (EN/FA), layout/fit, rendering; `FONTS` table (bundled in `assets/fonts`)
- `swa/render/handwriting.py` — words → pen strokes in writing order (RTL for Persian, dots after letters)
- `swa/render/captions.py` — caption chunks from word timings, styles, SRT/VTT
- `swa/render/hands.py` — hand library (PNG + tip point) and `HandRig` (rotation around the tip, shadow, lift, mirror)
- `swa/render/audio.py` — pen `ActivityLog`, synthesized drawing sounds, final FFmpeg mix (ducking, two-pass loudnorm), levels relative to the voice
- `swa/render/music.py` — built-in procedural music (seamless loops, cached in `data/music/.builtin`) and user music library
- `swa/render/compositor.py` — orchestration: layout per shot, background prefetch, transitions, hand, captions, encoder, audio
- `swa/render/encoder.py`, `backgrounds.py`, `imageio.py` — FFmpeg pipe, boards, Unicode-safe image IO
- `swa/claude.py` — "Claude draws them": finds the local Claude Code CLI, writes a task file per batch of lines, runs `claude -p` (stream-json, acceptEdits, only `python -m swa` checks allowed), reports progress, tidies redrawn lines
- `swa/app/server.py` — FastAPI API + static UI in `swa/app/static/` (vanilla JS, EN/FA i18n in `i18n.js`)
- `swa/__main__.py` — CLI (`app`, `new`, `check`, `align`, `render`, `sheet`, `lint-svg`, `claude`, `hands`)

## Gotchas

- Persian strings in Python source: write them with `\uXXXX` escapes (some editors and tools silently turn escapes into invisible characters).
- Timeline word indices match `tokenize(line.text)` of the *clean* text (stars removed); `ScriptLine.marks` uses the same indices.
- Video is rendered silent to `<name>.video.mp4`, then `audio.finalize` muxes the sound; keep both steps when changing output.
- Tests must never start the real `claude` CLI: set `CLAUDE_CLI` to a fake script (see `tests/test_claude.py`). In the cloud sandbox `claude` is on PATH, so a running app finds it; do not press "Draw with Claude" there.
- Stopping the dev server: never put `swa app` in the same shell command as `pkill -f` (it matches and kills that shell).

## Commands

```bash
python -m swa                      # start the app
python -m swa render <project> --line 3 --draft
python -m pytest -q                # tests (need ffmpeg on PATH for the render test)
```

Keep the UI offline (no CDNs) and keep every user-facing string in both
languages in `swa/app/static/i18n.js`.
