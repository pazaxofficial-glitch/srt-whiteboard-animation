# Status and roadmap

Read this first when you pick the project up in a new session (together with
`CLAUDE.md`, which has the code map and the gotchas).

## Where things stand

The newest work is on the branch **`claude/nifty-hawking-x3ca05`**: it holds
everything from `claude/cool-wright-ytypgi` (commits below) plus phase 1.5.
The default branch (`main`) still contains the old Chinese
"srt-whiteboard-animation" skill until this work is merged, so start new work
from the newest branch (or from `main` once it has been merged).

| Commit | What it contains |
|---|---|
| `f654177` | The app itself: project folders, numbered script ↔ numbered images, Whisper alignment, stroke renderer (raster + SVG), boards, hands, FastAPI web UI (purple/black + light, English/Persian), one-click launchers, CLI, Claude Code SVG workflow |
| `6924615` | Phase 1: `*marked*` words handwritten when spoken, lines without an image written word by word, HarfBuzz text engine + bundled EN/FA fonts, captions (4 styles) + SRT, synthesized drawing sounds, 3 built-in music tracks, ducking, two-pass loudness (−14 LUFS), realistic hand (rotation, flex, lift, shadow, mirror), Audio tab |
| phase 1.5 | Natural colouring (marker strokes per colour region, streaky then settling; no colouring pass for black-and-white pictures; Colour in auto/always/never + per-picture chip), short lines appear without the hand (picture or text, threshold), Mix and Zoom transitions, "Claude draws them" (local Claude Code CLI run from the app, brief, redraw, progress), word-timed SVG parts (`data-word`), video clips as pictures (HyperFrames/Remotion output), dots no longer pop in at the end |

The person behind the project speaks Persian (answer them in Persian); code,
comments, commits and docs are in English; every UI string exists in both
languages in `swa/app/static/i18n.js`. English videos matter most, Persian must
keep working.

## What has been verified, and what has not

Verified in the cloud sandbox:
- 62 tests pass (`python -m pytest -q`)
- phase 1.5 renders checked frame by frame: colouring on whiteboard and chalkboard, black-and-white art without a colouring pass, grey shading, every Mix transition, a 1.2 s line fading in, a `data-word` part waiting for its word, MP4 and transparent WebM clips; render speed unchanged (30 s at 720p: 22 s before and after)
- the "Claude draws them" flow end to end in the browser (EN/FA) against a fake `claude` CLI: progress per line, refresh, redraw keeps the old file in `images/.replaced`
- full renders in English (whiteboard) and Persian (chalkboard), checked frame by frame
- final loudness measured at −14.1 LUFS; music/drawing-sound balance is the same with an 18 dB quieter narration
- the whole web API flow (create, upload narration/script/ZIP, sync, render, SRT, line preview, delete)
- UI screenshots in English/Persian and dark/light

Not verified yet (no access in the sandbox):
- a real Claude Code drawing run started by the app: the command line (`claude -p … --output-format stream-json --verbose --permission-mode acceptEdits --allowedTools …`) was checked against `claude --help` of Claude Code 2.1.296 but not run, to avoid starting a session on the user's account; on Windows also the `claude.cmd` launch and the process-tree kill on Cancel
- HyperFrames / Remotion clips: not installed here; clip playback was tested with clips made by FFmpeg
- real Whisper transcription: Hugging Face model downloads are blocked there, so alignment was tested with synthetic word timings, SRT import and the estimate mode
- `Start-Windows.bat` and `Start-Mac.command` on real machines (`start.sh` was tested from scratch on Linux)
- how the drawing sounds and the built-in music sound to a human ear (only measured)
- speed on the user's PC; in the sandbox a 1-minute 1080p30 video takes about 40 s on 4 cores

## Known limitations

- One image per board; no shared canvas or camera moves yet
- `<text>` inside SVG files is not drawn (mark words with `*stars*` instead)
- Raster stroke order is heuristic (objects in reading order, nearest neighbour inside an object)
- Persian "handwriting" fonts are typeset fonts (Naskh, Playful, Display, Clean), not true handwriting
- The only built-in hand holds a marker (no chalk hand); users can upload their own
- Captions use at most two lines; very long words shrink the text
- Raster colour regions come from colour clustering (up to 32 per picture); a busy photo is coloured in by large areas, not object by object
- A clip's own sound is ignored (the narration drives the audio); clips play without the hand
- Runs started from the app only let Claude write SVGs; animated clips are made by asking Claude Code directly
- The 🎨 chip shows the choice per picture, not what Auto detected

## Next phases (agreed plan)

### Phase 2: no image needed for every line
- Parts of one image appear on different words: done for SVG (`data-word`); still to do: raster objects linked to words in the Sync table
- Automatic emphasis: underline or circle a word when it is marked or stressed
- Photo → hand-drawn sketch filter, so any image looks drawn
- Built-in doodle library (Open Peeps CC0, OpenMoji, Tabler, game-icons) with English/Persian keyword search, and automatic scenes for lines without images

### Phase 3: beyond VideoScribe
- Large shared canvas with camera moves (pan/zoom following the hand, zoom out at the end of a section)
- Scene editor: drag and drop doodles, text, arrows, shapes and charts
- Entry animations: draw, move in, fade, erase, morph
- Hand-drawn charts and counting numbers

### Phase 4: final product
- Live preview (scrub without rendering) and a waveform timeline
- Offline text-to-speech (Piper; English and Persian voices)
- Faster rendering (all CPU cores, NVENC), render queue, resume after a crash
- Windows `.exe` installer with its own window, auto-update
- Brand kit (logo, intro/outro, colours, fonts), YouTube thumbnails, export presets

## Working notes for the cloud sandbox

- Python deps: `pip install -r requirements.txt pytest httpx` (use a venv); FFmpeg is preinstalled
- Whisper models cannot be downloaded there; use `python -m swa align <project> --method estimate`, an SRT, or build a timeline from synthetic words (see `tests/test_schedule.py`)
- UI screenshots: Playwright with `executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome"`
- When stopping the dev server, do not put the server's own command line (`-m swa app`) in the same shell command as the kill, or the shell kills itself
- Projects for experiments: set `SWA_DATA` to a scratch folder so nothing lands in the repo (`data/` is git-ignored anyway)
