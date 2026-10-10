# Simple Whiteboard Animation

Narration + numbered script + one image per line → hand-drawn whiteboard MP4,
synced to the voice. Python (OpenCV, NumPy, scikit-image, svgelements),
FastAPI web UI, FFmpeg for encoding, Whisper for speech timing.

## If the user asks you to draw / make the images for a project

Read `docs/svg-style-guide.md` first and follow it exactly. In short: for each
line N of `data/projects/<project>/script.txt`, write
`data/projects/<project>/images/N.svg` (1600×900 viewBox, stroked line art,
`fill="none"` by default, document order = drawing order). Work in batches,
and after each batch run `python -m swa lint-svg <project>` and
`python -m swa sheet <project> --lines A-B`, then look at `contact-sheet.png`.

## Code map

- `swa/project.py` — project folder model, script parsing (`1.`, `1)`, `[1]`, plain lines, `*marked*` words), image ↔ line mapping by number in file name, settings defaults
- `swa/align.py` — Whisper (faster-whisper or openai-whisper) word timestamps, script↔transcript alignment (difflib), SRT import, even estimate
- `swa/render/schedule.py` — pure timing: shots per line, when marked words are written (`writes`), when the hand is away from the picture (`busy`), picture progress curve
- `swa/render/scene.py` — one shot frame by frame: picture + handwriting layers, hand position and pen state
- `swa/render/board.py` — board layers with reveal masks, pen plans (effort units), `Reveal`
- `swa/render/drawing.py` — image → layers (line art, full colour) + pen strokes; raster and SVG; chalk colours for dark boards
- `swa/render/strokes.py` — skeletonize, trace, order strokes, colouring sweeps
- `swa/render/text.py` — HarfBuzz shaping + fontTools outlines, mini-bidi (EN/FA), layout/fit, rendering; `FONTS` table (bundled in `assets/fonts`)
- `swa/render/handwriting.py` — words → pen strokes in writing order (RTL for Persian, dots after letters)
- `swa/render/captions.py` — caption chunks from word timings, styles, SRT/VTT
- `swa/render/hands.py` — hand library (PNG + tip point) and `HandRig` (rotation around the tip, shadow, lift, mirror)
- `swa/render/audio.py` — pen `ActivityLog`, synthesized drawing sounds, final FFmpeg mix (ducking, two-pass loudnorm), levels relative to the voice
- `swa/render/music.py` — built-in procedural music (seamless loops, cached in `data/music/.builtin`) and user music library
- `swa/render/compositor.py` — orchestration: layout per shot, background prefetch, transitions, hand, captions, encoder, audio
- `swa/render/encoder.py`, `backgrounds.py`, `imageio.py` — FFmpeg pipe, boards, Unicode-safe image IO
- `swa/app/server.py` — FastAPI API + static UI in `swa/app/static/` (vanilla JS, EN/FA i18n in `i18n.js`)
- `swa/__main__.py` — CLI (`app`, `new`, `check`, `align`, `render`, `sheet`, `lint-svg`, `hands`)

## Gotchas

- Persian strings in Python source: write them with `\uXXXX` escapes (some editors and tools silently turn escapes into invisible characters).
- Timeline word indices match `tokenize(line.text)` of the *clean* text (stars removed); `ScriptLine.marks` uses the same indices.
- Video is rendered silent to `<name>.video.mp4`, then `audio.finalize` muxes the sound; keep both steps when changing output.

## Commands

```bash
python -m swa                      # start the app
python -m swa render <project> --line 3 --draft
python -m pytest -q                # tests (need ffmpeg on PATH for the render test)
```

Keep the UI offline (no CDNs) and keep every user-facing string in both
languages in `swa/app/static/i18n.js`.
