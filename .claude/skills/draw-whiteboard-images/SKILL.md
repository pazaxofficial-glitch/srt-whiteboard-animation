---
name: draw-whiteboard-images
description: Draw the scenes for a Simple Whiteboard Animation project as SVG line art, one per script line, timed to the spoken words, without an image generator; optionally make an animated clip for a line with HyperFrames or Remotion. Use when the user asks to draw, make or create images, illustrations or scenes for a project or for script lines, or when a task file from the app asks for it.
---

# Draw the scenes for a project

1. Find the project: `data/projects/<name>/` (ask which one if there are several and the user did not say).
   Read `script.txt` and `project.json`:
   - `settings.aspect` decides the viewBox (16:9 → `0 0 1600 900`, 9:16 → `0 0 900 1600`, 1:1 → `0 0 1200 1200`, 4:5 → `0 0 1200 1500`).
   - `settings.claude_brief` is the author's own instructions (style, characters, colours, things to show or avoid). Follow them; they win over the defaults in the style guide.
   - A dark `settings.background` (chalkboard, blackboard) needs nothing special: draw dark ink as usual, the app turns it into chalk.
2. Read `docs/svg-style-guide.md` and follow every rule in it.
3. Decide which lines to draw: the ones the user or the task file names, otherwise the lines with no picture yet (`python -m swa check <project>` lists `missing_images`). Never overwrite a picture you were not asked to redo.
4. Look at two or three pictures already in `images/` (SVGs are text) and keep the same characters, line weight and colours, so the whole video looks like one hand drew it.
5. For each line N write `images/N.svg`. Put every object the line mentions in its own group and time it to its word with `data-word="..."` (see the style guide), so the hand draws the shield when "shield" is said. Lines that are only words (titles, quotes, numbers) get no SVG: the app writes them by hand on its own. Suggest `*word*` marks in `script.txt` when a key word should appear on the board.
6. Work in batches of 10–20 lines. After each batch:
   - `python -m swa lint-svg <project>` and fix every problem it lists.
   - `python -m swa sheet <project> --lines A-B`, open `contact-sheet.png` and check each tile reads clearly at a glance; redraw weak ones.
7. When done, say how many scenes you drew and suggest `python -m swa render <project> --line N --draft` (or the Sync tab's preview button) to watch one being drawn.

## Animated clips (only when asked)

Some lines are better as motion than as a drawing: a chart that grows, a number that counts up, a map with a moving route, an animated diagram. When the user asks for that, and HyperFrames (`npx hyperframes`) or Remotion is available with its own skill, make a clip for that line instead of an SVG:

- Length: the line's time on screen. Read `timeline.json` (after Sync): from this line's `start` to the next line's `start`.
- Size: the project's aspect at 1280 px on the long side (16:9 → 1280×720), 30 fps.
- Background: transparent if the tool can export it (WebM with alpha, or ProRes 4444 MOV); otherwise plain white. The app removes a plain background colour, so the board shows through.
- Look: whiteboard style (dark lines, the palette from the style guide, a hand-drawn font), so the clip fits the drawn scenes around it.
- Save it as `images/N.webm` (or `.mp4` / `.mov`) and remove `images/N.svg` if there was one. The app plays it while the line is spoken (no hand), with the project's transitions, captions and sound.

Keep clips for the few lines that need motion: the hand-drawn scenes are the point of the video. An unattended run started from the app never makes clips (it may only write SVGs).
