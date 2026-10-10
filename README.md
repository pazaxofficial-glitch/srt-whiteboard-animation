<p align="center">
  <img src="swa/app/static/logo.svg" width="84" alt="">
</p>

<h1 align="center">Simple Whiteboard Animation</h1>

<p align="center">
  <b>Narration + script + images → a hand-drawn whiteboard video, in sync with every line.</b><br>
  Runs on your own computer. No subscriptions, no paid image models.
</p>

<p align="center">
  <a href="README.fa.md">فارسی</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#let-claude-code-draw-the-images">Claude Code drawing</a> ·
  <a href="#command-line">CLI</a>
</p>

<p align="center">
  <img src="docs/images/demo.gif" width="100%" alt="A hand drawing a Spartan helmet, a shield and spear, and mountains with a running soldier, one picture per narration line">
</p>

## What it does

You upload three things:

1. **The narration** (MP3, WAV, M4A…)
2. **The script**, one line per picture: `1. Life, the Spartan way.` `2. Every boy was given a shield…`
3. **The images**, named by line number: `1.png`, `2.png` … `300.png` (PNG, JPG, WebP or SVG)

Whisper listens to the narration and finds the exact moment each line is
spoken. When line 58 starts, the hand starts drawing image 58: outline first,
then colour, moving while the narrator speaks and slowing down in pauses.
Then the board changes and the next drawing begins. You get an MP4 with your
voice-over.

<p align="center"><img src="docs/images/app.jpg" width="100%" alt="The app: purple and black interface with board, hand and drawing options and a live preview"></p>

## Features

- **Voice-synced drawing**: each image starts on the first word of its line (Whisper word timestamps, aligned to your script so recognition mistakes do not matter)
- **Natural pen**: line art is traced into real pen strokes; the hand follows them, lifts between strokes and colours in afterwards. SVG images are drawn exactly along their paths
- **Boards**: whiteboard, plain white, paper, chalkboard, blackboard, or your own image. On dark boards dark ink turns into chalk automatically
- **Hands**: built-in marker hand, or upload any number of your own PNG hands and click where the pen tip is
- **Styles**: outline then colour, draw directly in colour, or line art only; slide / fade / wipe / cut transitions
- **Formats**: 16:9 YouTube, 9:16 Shorts/Reels, 1:1, 4:5, from 720p to 4K, 24/30/60 fps
- **Fine control**: edit any line's start/end, play a line's audio, render a preview of a single line
- **English and Persian**: the interface switches between English and فارسی (right-to-left); Persian narration and scripts are supported
- **Offline**: everything runs locally. Internet is only needed once, to install components
- **Agent friendly**: projects are plain folders; Claude Code can draw all the SVG images for you

## Quick start

You need **Python 3.10+** and **FFmpeg**. Whisper is optional but recommended
for exact sync.

| | |
|---|---|
| **Windows** | Double-click **`Start-Windows.bat`** |
| **macOS** | Double-click **`Start-Mac.command`** (first time: right-click → Open) |
| **Linux** | Run `./start.sh` |

The first start prepares a private environment (one time, needs internet).
After that it opens straight to the app in your browser at
`http://127.0.0.1:7860`. Close the black window to stop it.

The environment can see packages you already installed, so an existing
Whisper installation is used as is. If you do not have Whisper yet:

```bash
pip install faster-whisper
```

Tip: right-click `Start-Windows.bat` → *Send to → Desktop (create shortcut)*
for a one-click icon.

## How it works

1. **Narration & script**: upload the voice-over and paste the script. Numbered lines (`1.` `2)` `[3]` `4 -`) or one line per row. Persian digits work too.
2. **Images**: drop all images at once (or a ZIP). The number in each file name decides its line: `7.png`, `007.jpg`, `scene_7.png` all belong to line 7. Missing images are highlighted; the previous drawing simply stays on screen.
3. **Style**: board, hand and hand size, drawing style, pen rhythm, drawing time, transitions, format, resolution. A live preview shows the finished look.
4. **Sync**: *Whisper* (exact), *Import SRT* (use existing subtitle timing) or *Estimate* (quick draft). Then adjust any line in the timeline table, play it, or render a preview of just that line.
5. **Export**: render the MP4 (High quality or Fast draft) and download it.

Or press **Make video**: it syncs (if needed) and renders in one click.

### Getting the best results

- Clean line art on a plain white background draws most naturally. Transparent PNGs work too.
- Busy photos still work, but are traced as a whole picture.
- **Drawing time** controls how much of each line is spent drawing; the rest shows the finished picture. **Longest drawing** caps very long lines.
- **Pen rhythm → Follow the voice** moves the pen while words are spoken and slows it in pauses. **Steady speed** draws evenly.
- For Persian videos, set **Drawing order → Right → left** (Auto does this when the script is Persian).

## Let Claude Code draw the images

No image generator? Projects are plain folders, so an AI coding agent can draw
the pictures as SVG line art, which is also the most natural-looking input
for the pen.

1. Create the project in the app and add the narration and script.
2. Open this app's folder in [Claude Code](https://claude.com/claude-code) and ask:
   > Draw the images for the project "my-video".
3. Claude Code reads the script and writes `images/1.svg`, `images/2.svg`, … following
   [`docs/svg-style-guide.md`](docs/svg-style-guide.md). It checks its own work with
   `python -m swa lint-svg` and a contact sheet (`python -m swa sheet`).
4. Back in the app: **Sync → Export**.

You can mix sources freely: your own PNGs for some lines, SVGs for others.

## Hands and boards

- **Hands** (sidebar → Hands): upload a PNG of a hand holding a pen, marker or chalk, ideally with a transparent background and the arm running off the bottom edge. Click the pen tip, set the size. Upload as many as you like and pick one per project.
- **Boards** (sidebar → Boards): upload any image as a custom board. Dark images automatically switch drawings to chalk colours.

## Command line

Everything in the app is also available from the terminal:

```bash
python -m swa                          # start the app
python -m swa new "The Spartan Way"    # create a project
python -m swa check the-spartan-way    # what is missing?
python -m swa align the-spartan-way    # sync with Whisper (--method srt --srt subs.srt | --method estimate)
python -m swa render the-spartan-way --line 12 --draft   # quick preview of one line
python -m swa render the-spartan-way   # full video → data/projects/the-spartan-way/output/
python -m swa sheet the-spartan-way    # contact sheet of all drawings
python -m swa lint-svg the-spartan-way # check SVG drawings
```

## Project folder

```
data/projects/the-spartan-way/
  project.json      name and settings
  narration.mp3     your voice-over
  script.txt        numbered lines
  images/           1.png, 2.svg, ... (number = script line)
  transcript.json   saved Whisper result (re-sync is instant)
  timeline.json     start/end of every line (editable in the app)
  output/           rendered videos
```

Set the `SWA_DATA` environment variable to keep projects somewhere else.

## Troubleshooting

| Problem | Fix |
|---|---|
| "FFmpeg not found" | Install FFmpeg and make sure `ffmpeg` works in a terminal, or set `FFMPEG` to the full path of `ffmpeg.exe`. |
| "Whisper not found" | `pip install faster-whisper` in the same Python you start the app with, or use *Import SRT* / *Estimate*. |
| Whisper is slow | Pick a smaller model (`base` or `small`) in the Sync tab. `medium` / `large-v3` are more accurate for Persian. |
| A drawing starts too early or late | Sync tab → edit that line's start time → *Save times*. |
| The pen starts at the wrong spot on my hand | Hands → *Pen tip* → click the exact tip. |
| Port 7860 is busy | The app picks the next free port automatically. |

## For developers

```bash
pip install -r requirements.txt pytest
python -m pytest -q
```

Code map and conventions: [`CLAUDE.md`](CLAUDE.md).

## License

MIT, see [LICENSE](LICENSE). Grew out of the original *srt-whiteboard-animation*
skill by 江哥是老登啊.
