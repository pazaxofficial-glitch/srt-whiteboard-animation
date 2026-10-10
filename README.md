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
  <a href="#no-images-let-claude-draw-the-scenes">Claude draws</a> ·
  <a href="#command-line">CLI</a>
</p>

<p align="center">
  <img src="docs/images/demo.gif" width="100%" alt="A hand draws a Spartan helmet and writes the word Spartan as it is spoken, then a shield and spear, mountains, and finally writes a whole line of text, with word-by-word captions underneath">
</p>

## What it does

You upload three things:

1. **The narration** (MP3, WAV, M4A…)
2. **The script**, one line per picture: `1. Life, the Spartan way.` `2. Every boy was given a shield…`
3. **The images**, named by line number: `1.png`, `2.png` … `300.png` (PNG, JPG, WebP or SVG),
   or no images at all: let **Claude draw the scenes** for you

Whisper listens to the narration and finds the exact moment each line is
spoken. When line 58 starts, the hand starts drawing image 58: outline first,
then colour, moving while the narrator speaks and slowing down in pauses.
Mark a word in the script like `*this*` and the hand writes it on the board the
moment it is said. Then the board changes and the next drawing begins.

You get an MP4 with your voice-over, marker sounds that follow the pen,
optional background music that dips under your voice, burned-in captions and
an SRT subtitle file.

<p align="center"><img src="docs/images/app.jpg" width="100%" alt="The app: purple and black interface with board, hand and drawing options and a live preview"></p>

## Features

- **Voice-synced drawing**: each image starts on the first word of its line (Whisper word timestamps, aligned to your script so recognition mistakes do not matter)
- **Words written as they are spoken**: `*marked*` words are handwritten next to the picture on the exact word; lines without a picture are written out word by word (English and Persian handwriting fonts)
- **Natural pen and hand**: line art is traced into real pen strokes; the hand follows them, lifts between strokes, swings and flexes like a real arm and casts a soft shadow. SVG images are drawn exactly along their paths
- **Colouring like a real marker**: each area of colour is filled with back-and-forth marker strokes that stay inside it, one area at a time, streaky at first and then even. Black-and-white pictures are simply drawn (no pointless colouring pass); choose per project or per picture
- **Claude draws the scenes**: no images? Claude Code (on your computer, with your Claude account) draws every line as an SVG scene in your style and times each object to the word that mentions it. Upload your own images for any line at any time
- **Short lines are not rushed**: a line shorter than 3 seconds (adjustable) is not drawn in a hurry; its picture, or its text, simply appears
- **Captions**: clean, boxed, highlighted-word (karaoke) or Shorts-style pop, in English and Persian, plus an SRT file for YouTube
- **Sound design**: marker or chalk sounds only while the pen touches the board, a whoosh on transitions, three built-in music tracks composed by the app (or your own), automatic ducking under the voice and loudness set to −14 LUFS
- **Boards**: whiteboard, plain white, paper, chalkboard, blackboard, or your own image. On dark boards dark ink turns into chalk automatically
- **Hands**: built-in marker hand, or upload any number of your own PNG hands and click where the pen tip is; left-hand mode
- **Styles**: outline then colour, draw directly in colour, or line art only; slide / fade / wipe / zoom / cut transitions, or **Mix** for a different one on every board
- **Video clips**: a line can play an MP4/WebM clip instead of a drawing (an animated chart made with HyperFrames or Remotion, a screen recording); plain backgrounds are keyed out
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
2. **Images**: drop all images at once (or a ZIP). The number in each file name decides its line: `7.png`, `007.jpg`, `scene_7.png` all belong to line 7. Missing images are highlighted; those lines are written as text. Or switch to **Claude draws them** and let Claude Code draw every scene.
3. **Style**: board, hand, handwriting fonts, captions, drawing style, pen rhythm, transitions, format, resolution. A live preview shows the finished look.
4. **Audio**: drawing sounds, background music (listen before choosing), ducking and loudness.
5. **Sync**: *Whisper* (exact), *Import SRT* (use existing subtitle timing) or *Estimate* (quick draft). Then adjust any line in the timeline table, play it, or render a preview of just that line.
6. **Export**: render the MP4 (High quality or Fast draft) and download it with its SRT subtitles.

Or press **Make video**: it syncs (if needed) and renders in one click.

### Getting the best results

- Clean line art on a plain white background draws most naturally. Transparent PNGs work too.
- Busy photos still work, but are traced as a whole picture.
- **Drawing time** controls how much of each line is spent drawing; the rest shows the finished picture. **Longest drawing** caps very long lines.
- **Pen rhythm → Follow the voice** moves the pen while words are spoken and slows it in pauses. **Steady speed** draws evenly.
- For Persian videos, set **Drawing order → Right → left** (Auto does this when the script is Persian).
- **Colour in → Auto** colours only pictures that have colour; black-and-white line art is just drawn and gets all the time. The 🎨 chip on a picture in the Images tab overrides it for that picture (auto → no colour → always).
- **Short lines** (default: shorter than 3 s until the next line) are not drawn: the picture fades in without the hand, or choose *Show text* to show the line's words instead, or *Draw anyway*. The Sync table marks those lines.

## Write words on the board

Put stars around words in the script and the hand writes them on the board at
the moment they are spoken; the picture pauses for that moment and then
continues:

```text
1. Life, the *Spartan* way.
2. Every boy was given a *shield and a spear*.
3. *۳۰۰* سرباز اسپارتی در برابر هزاران نفر ایستادند.
```

A line that has no image is written out completely, word by word, in time with
the narrator: good for titles, quotes, numbers and summaries. (Prefer the old
behaviour? Style → Handwriting → *Keep previous drawing*.)

Handwriting fonts: Marker, Casual, Neat, Bold caps for English; Naskh,
Playful, Display, Clean for Persian. Ink colour, position (above or below the
picture) and writing speed are adjustable.

## Captions and sound

- **Captions** (Style → Captions): the word being spoken is highlighted in the
  colour you choose. *Pop* shows 1–3 big words at a time for Shorts and Reels.
  Every full render also saves `video.srt` next to `video.mp4`.
- **Drawing sounds** (Audio): synthesized by the app, marker on light boards
  and chalk on dark ones, louder when the pen moves faster, silent when it
  lifts.
- **Music** (Audio): *Calm*, *Bright* and *Focus* are composed by the app and
  free to use; or upload your own tracks. Music dips automatically while you
  speak.
- **Levels** are set relative to your voice, so a quiet or loud microphone
  gives the same balance, and the final mix is normalized to −14 LUFS
  (YouTube), −16 (podcast) or −23 (TV).

## No images? Let Claude draw the scenes

Projects are plain folders, so Claude Code can draw the pictures as SVG line
art, which is also the most natural input for the pen. The app can start it
for you:

1. Install [Claude Code](https://claude.com/claude-code) and sign in once (it
   uses your own Claude account; the app itself never talks to an AI service).
2. In the app: **Images → Claude draws them**. Optionally write a brief: the
   style, the main characters, colours, things to avoid.
3. Press **Draw with Claude** (or **Make video**, which syncs, lets Claude draw
   the missing scenes and renders). Claude writes `images/1.svg`, `images/2.svg`, …
   following [`docs/svg-style-guide.md`](docs/svg-style-guide.md), checks its own
   work with `python -m swa lint-svg` and a contact sheet, and the scenes appear
   in the app as they are drawn. Redraw any scene with one click, or drop your
   own image on any line.

Each object in a scene is tagged with the word that mentions it
(`<g data-word="shield">`), so the hand draws the shield exactly when
"shield" is said. Board, hand, captions and sound settings work the same as
with uploaded images.

Prefer to drive it yourself? Open this folder in Claude Code and type
`Draw the scenes for the project "my-video"`. The same way you can ask for
**animated clips** for the few lines that need motion: with the
[HyperFrames](https://github.com/heygen-com/hyperframes) or Remotion skills
installed, ask e.g. *"Make line 12 an animated bar chart with HyperFrames"*.
Clips (`images/12.webm` or `.mp4`) play on the board while the line is spoken.

From the terminal: `python -m swa claude my-video` (add `--lines 5-9 --redo` to
redraw some lines).

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
python -m swa claude the-spartan-way   # let Claude Code draw the lines without a picture
```

## Project folder

```
data/projects/the-spartan-way/
  project.json      name and settings
  narration.mp3     your voice-over
  script.txt        numbered lines
  images/           1.png, 2.svg, 3.webm ... (number = script line)
  transcript.json   saved Whisper result (re-sync is instant)
  timeline.json     start/end of every line (editable in the app)
  output/           rendered videos (.mp4) and subtitles (.srt)
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

Bundled fonts: Patrick Hand, Caveat, Kalam, Mirza, Marhey, Katibeh and
Vazirmatn (SIL Open Font License) and Permanent Marker (Apache 2.0); licences
in [`assets/fonts/licenses`](assets/fonts/licenses). Built-in music and sounds
are generated by the app's own code.
