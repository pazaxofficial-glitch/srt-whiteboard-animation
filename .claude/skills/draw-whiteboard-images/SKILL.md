---
name: draw-whiteboard-images
description: Draw the SVG images for a Simple Whiteboard Animation project, one per script line, without an image generator. Use when the user asks to draw, make or create images/illustrations/scenes for a project or for script lines.
---

# Draw whiteboard images for a project

1. Find the project: `data/projects/<name>/` (ask which one if there are several and the user did not say). Read `script.txt` and `project.json` (`settings.aspect` decides 1600×900 or 900×1600).
2. Read `docs/svg-style-guide.md` and follow every rule in it.
3. List which lines have no image yet (`python -m swa check <project>` shows `missing_images`). Draw only those unless asked to redo.
4. Work in batches of 10–20 lines. For each line N write `images/N.svg`.
5. After each batch:
   - `python -m swa lint-svg <project>` — fix every problem it lists.
   - `python -m swa sheet <project> --lines A-B` — open the written `contact-sheet.png` and check each tile reads clearly at a glance; redraw weak ones.
6. When done, tell the user how many images you drew and suggest `python -m swa render <project> --line N --draft` (or the app's Sync tab preview button) to watch one being drawn.
