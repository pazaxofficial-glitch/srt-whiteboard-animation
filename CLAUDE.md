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

- `swa/project.py` — project folder model, script parsing (`1.`, `1)`, `[1]`, plain lines), image ↔ line mapping by number in file name, settings defaults
- `swa/align.py` — Whisper (faster-whisper or openai-whisper) word timestamps, script↔transcript alignment (difflib), SRT import, even estimate
- `swa/render/drawing.py` — image → layers (line art, full colour) + pen strokes; raster and SVG paths; chalk colours for dark boards
- `swa/render/strokes.py` — skeletonize, trace, order strokes, colouring sweeps
- `swa/render/compositor.py` — timing plan per line, pen plan, incremental reveal, transitions, hand motion, frame loop
- `swa/render/encoder.py` — raw frames → FFmpeg (libx264 + AAC)
- `swa/render/hands.py`, `backgrounds.py` — hand library (PNG + tip point) and boards
- `swa/app/server.py` — FastAPI API + static UI in `swa/app/static/` (vanilla JS, EN/FA i18n in `i18n.js`)
- `swa/__main__.py` — CLI (`app`, `new`, `check`, `align`, `render`, `sheet`, `lint-svg`, `hands`)

## Commands

```bash
python -m swa                      # start the app
python -m swa render <project> --line 3 --draft
python -m pytest -q                # tests (need ffmpeg on PATH for the render test)
```

Keep the UI offline (no CDNs) and keep every user-facing string in both
languages in `swa/app/static/i18n.js`.
