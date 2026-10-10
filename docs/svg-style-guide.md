# Drawing images as SVG (guide for Claude Code and other AI agents)

Simple Whiteboard Animation can draw any PNG/JPG, but **SVG line art looks the
most natural**: the hand follows the real paths, stroke by stroke, in the order
they are written in the file. This guide is everything an agent needs to make
those SVGs for a project without an image generator.

## The job

A project folder looks like this:

```
data/projects/<project>/
  script.txt     numbered lines: "1. ...", "2. ...", one line = one image
  images/        put 1.svg, 2.svg, ... here (number = script line)
```

For every line in `script.txt`, write `images/<number>.svg` that illustrates
that line. Line 58 → `images/58.svg`. Skip lines that already have an image
unless the user asks to redo them.

## File rules (the renderer depends on these)

- Root: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900" width="1600" height="900">`
  (use `0 0 900 1600` for a 9:16 project; check `"aspect"` in `project.json`).
- Allowed elements: `path`, `line`, `polyline`, `polygon`, `circle`, `ellipse`,
  `rect`, `g` (with `transform` if needed). Nothing else is drawn: no `<text>`,
  `<image>`, gradients, filters, masks, clip paths or patterns.
- **SVG fills shapes black by default.** Put `fill="none"` on the outer `<g>`
  and give a `fill` only to shapes that should be coloured.
- Lines: `stroke="#222222"`, `stroke-width` 5–8 (thin details 4),
  `stroke-linecap="round"`, `stroke-linejoin="round"`.
- Keep files small: roughly 15–120 elements, under 30 KB.

## Drawing order = animation order

The pen draws stroked shapes **in document order**, then colours the filled
shapes (also in document order). So:

1. Order objects the way the narration mentions them.
2. Inside an object: big outline first, then inner details, then small accents.
3. Draw a person head → body → arms → legs, like a person would.
4. Prefer a few long continuous paths over many tiny segments; long paths
   look like confident hand-drawing.

## Style

- Minimal, friendly whiteboard sketch. One clear idea per image, centred,
  10% empty margin, lots of white space. 1–4 objects.
- Concept over realism: simple outlines, no shading, no hatching walls of lines.
- People: simple and consistent across the whole video (round head, simple
  body). Keep the same character design for recurring characters.
- Colour sparingly, 1–3 accents per image from this palette:

  | name | hex | use |
  |---|---|---|
  | red | `#D9452B` | danger, passion, Spartan crests |
  | orange | `#F2A23A` | sun, energy, highlights |
  | gold | `#E8B04A` | metal, money, success |
  | sky | `#9FC3E8` | sky, water, calm |
  | blue | `#4F7CAC` | trust, clothing |
  | green | `#7BB37B` | nature, growth, yes |
  | tan | `#C9A27E` | wood, skin, earth |
  | cream | `#F3E3B0` | paper, light fills |

- Words: never put text in the SVG. If a word should appear on the board,
  mark it in `script.txt` with stars (`Life, the *Spartan* way.`): the app
  handwrites it next to the picture at the exact moment it is spoken. A line
  that needs only words and no picture gets no SVG at all; the app writes the
  whole line.
- Abstract lines ("success takes time") → use a visual metaphor: a staircase
  with a flag, an hourglass, a seedling growing into a tree.

## Example

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900" width="1600" height="900">
  <!-- 12. "He trained with his shield every morning." -->
  <g fill="none" stroke="#222222" stroke-width="7" stroke-linecap="round" stroke-linejoin="round">
    <!-- sun first: "every morning" sets the scene -->
    <circle cx="1250" cy="200" r="70" fill="#F2A23A"/>
    <path d="M1250 100 V 70 M1250 300 V 330 M1150 200 H 1120 M1350 200 H 1380"/>
    <!-- soldier: head, body, arms, legs -->
    <circle cx="640" cy="330" r="45"/>
    <path d="M640 375 L 630 560"/>
    <path d="M636 420 L 560 470 L 520 440"/>
    <path d="M630 560 L 590 690 M630 560 L 680 690"/>
    <!-- shield, coloured after the line art -->
    <circle cx="760" cy="470" r="110" fill="#D9452B"/>
    <path d="M700 430 L 820 430 L 760 540 Z" fill="#F3E3B0"/>
    <!-- ground -->
    <path d="M420 700 C 700 715, 1000 690, 1250 705"/>
  </g>
</svg>
```

## Check your work

Run these from the app folder after every batch (10–20 images):

```bash
python -m swa lint-svg <project>   # rule violations (black fills, <text>, no strokes...)
python -m swa sheet <project> --lines 1-20   # writes contact-sheet.png: look at it
python -m swa render <project> --line 12 --draft   # watch one line being drawn
```

Open `contact-sheet.png` and look at every tile: is the idea readable at a
glance, is anything filled black by mistake, are the objects centred? Fix and
re-run before moving on.
