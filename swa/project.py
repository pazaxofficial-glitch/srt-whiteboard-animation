"""Project folders: script lines, numbered images, settings and timeline.

A project is a plain folder, so it can be edited by hand, by the web app or
by an AI coding agent (for example Claude Code drawing SVG images):

    projects/<slug>/
        project.json        name + render settings
        narration.<ext>     the voice-over (mp3/wav/m4a/...)
        script.txt          one line per image, optionally numbered "1. ..."
        images/             001.png, 2.jpg, 58.svg ... (number = script line)
        transcript.json     cached Whisper words (created by `align`)
        timeline.json       start/end time of every line (created by `align`)
        output/             rendered videos
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .textnorm import detect_language, normalize_text

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".svg"}
CLIP_EXTS = {".mp4", ".webm", ".mov", ".m4v"}       # a line can also play a video clip
VISUAL_EXTS = IMAGE_EXTS | CLIP_EXTS
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus", ".wma", ".mp4", ".mov", ".webm"}

DEFAULT_SETTINGS: dict = {
    "language": "auto",          # auto | en | fa  (Whisper language + UI hints)
    "aspect": "16:9",            # 16:9 | 9:16 | 1:1
    "resolution": 1080,          # short side in pixels: 720 | 1080 | 1440 | 2160
    "fps": 30,
    "background": "whiteboard",  # whiteboard | white | paper | chalkboard | blackboard | custom:<file>
    "hand": "marker",            # hand folder name in the library, or "none"
    "hand_scale": 1.0,
    "color_mode": "ink_then_color",  # ink_then_color | ink_only | color_strokes
    "coloring": "auto",          # colouring pass: auto (only pictures that have colour) | on | off
    "stroke_order": "auto",      # auto | left_to_right | right_to_left | top_to_bottom
    "sync_mode": "speech",       # speech: pen moves while words are spoken; linear: constant speed
    "draw_fill": 0.8,            # share of each line's time spent drawing
    "ink_share": 0.7,            # share of the drawing time spent on line art (rest = colouring)
    "min_draw": 0.8,             # seconds
    "max_draw": 14.0,            # seconds
    "transition": "slide",       # slide | fade | wipe | zoom | cut | mix (a varied mix)
    "transition_duration": 0.6,  # seconds
    "short_lines": "show",       # lines shorter than short_threshold: draw | show (picture fades in) | text
    "short_threshold": 3.0,      # seconds
    "image_margin": 0.05,        # empty border around each image (fraction of frame)
    "line_thickness": 1.0,       # thickness multiplier for SVG strokes
    "whisper_model": "small",
    "quality": "high",           # draft | high
    "tail": 0.6,                 # seconds of finished frame after the narration ends
    # Where the pictures come from
    "engine": "images",          # images: you upload them | claude: Claude Code draws them
    "claude_brief": "",          # your instructions for Claude (style, characters, colours...)
    # Handwriting
    "handwriting": True,         # write words marked *like this* when they are spoken
    "text_lines": "write",       # lines without an image: write | keep (previous drawing stays)
    "font_latin": "marker",      # marker | casual | neat | bold
    "font_rtl": "naskh",         # naskh | playful | display | clean
    "text_color": "auto",        # auto | black | blue | red | green | purple
    "text_position": "bottom",   # bottom | top (marked words next to the picture)
    "write_speed": 1.0,
    # Hand
    "hand_motion": True,         # natural rotation and flex
    "hand_shadow": True,
    "hand_mirror": False,        # left hand
    # Captions
    "captions": "off",           # off | clean | box | highlight | pop
    "caption_position": "bottom",  # bottom | top
    "caption_size": 1.0,
    "caption_color": "#FFD43B",  # highlighted word
    # Audio
    "sfx": True,                 # marker / chalk sounds while drawing
    "sfx_volume": 0.5,
    "music": "none",             # none | builtin:calm | builtin:bright | builtin:focus | file:<name>
    "music_volume": 0.3,
    "ducking": 0.7,              # how much the music dips under the voice
    "normalize_audio": True,     # loudness to `loudness` LUFS
    "loudness": -14.0,
}

_D = "[0-9\u06f0-\u06f9\u0660-\u0669]+"  # ASCII, Persian and Arabic-Indic digits
_NUMBERED = re.compile(
    rf"^\s*(?:\[\s*(?P<a>{_D})\s*\]|\(\s*(?P<b>{_D})\s*\)|(?P<c>{_D})\s*[.):\-–—|])\s*(?P<text>.*)$"
)
_BARE_NUMBER = re.compile(rf"^\s*(?P<c>{_D})\s+(?P<text>.+)$")
_TAB_NUMBER = re.compile(rf"^\s*(?P<c>{_D})\t+(?P<text>.*)$")
_NUMBER_IN_NAME = re.compile(_D)


def _to_int(digits: str) -> int:
    return int(normalize_text(digits))


def _match_number(m: re.Match) -> int:
    groups = m.groupdict()
    return _to_int(next(groups[k] for k in ("a", "b", "c") if groups.get(k)))


@dataclass
class ScriptLine:
    id: int
    text: str                                        # clean text (no *marks*)
    marks: list[int] = field(default_factory=list)   # word indices to handwrite when spoken


def extract_marks(text: str) -> tuple[str, list[int]]:
    """'Life, the *Spartan* way' -> ('Life, the Spartan way', [2]).

    Words between asterisks get written on the board at the moment they are
    spoken. A mark can span several words: '*shield and spear*'.
    """
    words: list[str] = []
    marks: list[int] = []
    inside = False
    for tok in text.split():
        stars_at = [i for i, ch in enumerate(tok) if ch == "*"]
        clean = tok.replace("*", "")
        if not stars_at:
            if clean:
                if inside:
                    marks.append(len(words))
                words.append(clean)
            continue
        letters = [i for i, ch in enumerate(tok) if ch.isalnum()]
        if not letters:                       # a lone "*" toggles the mark
            inside = not inside
            continue
        opens = any(i < letters[0] for i in stars_at)
        closes = any(i > letters[-1] for i in stars_at)
        if opens:
            inside = True
        if clean:
            if inside:
                marks.append(len(words))
            words.append(clean)
        if closes:
            inside = False
    return " ".join(words), marks


def parse_script(text: str) -> list[ScriptLine]:
    """Parse a script into numbered lines.

    Accepted forms (mixed spacing, Persian digits and blank lines are fine):
        1. text      1) text      1 - text      [1] text      1<TAB>text
        plain lines without numbers (numbered 1..N in order)

    In a numbered script, an un-numbered line continues the previous line.
    """
    raw_lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    nonblank = [ln for ln in raw_lines if ln.strip()]
    if not nonblank:
        return []

    def numbered(ln: str):
        return _NUMBERED.match(ln) or _TAB_NUMBER.match(ln)

    explicit = sum(1 for ln in nonblank if numbered(ln))
    pattern = None
    if explicit >= max(1, len(nonblank) // 2):
        pattern = numbered
    else:
        # "1 text" only counts as numbering if the numbers run 1, 2, 3, ...
        bare = [_BARE_NUMBER.match(ln) for ln in nonblank]
        if all(bare):
            nums = [_match_number(m) for m in bare]  # type: ignore[union-attr]
            if nums == list(range(nums[0], nums[0] + len(nums))):
                pattern = _BARE_NUMBER.match

    lines: list[ScriptLine] = []
    if pattern is None:
        for i, ln in enumerate(nonblank, start=1):
            lines.append(ScriptLine(i, ln.strip()))
        return _with_marks(lines)

    for ln in nonblank:
        m = pattern(ln)
        if m:
            lines.append(ScriptLine(_match_number(m), m.group("text").strip()))
        elif lines:
            lines[-1].text = (lines[-1].text + " " + ln.strip()).strip()
        else:
            lines.append(ScriptLine(1, ln.strip()))
    # Drop empty numbered lines but keep their numbers reserved.
    return _with_marks([ln for ln in lines if ln.text])


def _with_marks(lines: list[ScriptLine]) -> list[ScriptLine]:
    for ln in lines:
        ln.text, ln.marks = extract_marks(ln.text)
    return [ln for ln in lines if ln.text]


def image_number(path: Path) -> int | None:
    """Line number encoded in an image file name ('001.png', 'scene 58.jpg')."""
    stem = path.stem
    groups = _NUMBER_IN_NAME.findall(stem)
    if not groups:
        return None
    if normalize_text(stem).isdigit():
        return _to_int(stem)
    return _to_int(groups[0])


def map_images(images_dir: Path) -> tuple[dict[int, Path], list[str]]:
    """Map line number -> image file. Returns (mapping, warnings)."""
    mapping: dict[int, Path] = {}
    warnings: list[str] = []
    if not images_dir.exists():
        return mapping, warnings
    files = sorted(p for p in images_dir.iterdir() if p.is_file() and p.suffix.lower() in VISUAL_EXTS)
    for p in files:
        n = image_number(p)
        if n is None:
            warnings.append(f"No line number in image name: {p.name}")
            continue
        if n in mapping:
            warnings.append(f"Two images for line {n}: {mapping[n].name} and {p.name} (using the first)")
            continue
        mapping[n] = p
    return mapping, warnings


def slugify(name: str) -> str:
    slug = re.sub(r"[^\w\-]+", "-", name.strip().lower(), flags=re.UNICODE).strip("-")
    return slug or "project"


def audio_duration(path: Path) -> float:
    """Duration in seconds using ffprobe."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


@dataclass
class Project:
    root: Path
    name: str = ""
    settings: dict = field(default_factory=lambda: dict(DEFAULT_SETTINGS))
    created: str = ""
    line_options: dict = field(default_factory=dict)   # "12" -> {"coloring": "off"}

    # ── paths ──────────────────────────────────────────────
    @property
    def config_path(self) -> Path:
        return self.root / "project.json"

    @property
    def script_path(self) -> Path:
        return self.root / "script.txt"

    @property
    def images_dir(self) -> Path:
        return self.root / "images"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def timeline_path(self) -> Path:
        return self.root / "timeline.json"

    @property
    def transcript_path(self) -> Path:
        return self.root / "transcript.json"

    @property
    def slug(self) -> str:
        return self.root.name

    # ── load / save ────────────────────────────────────────
    @classmethod
    def create(cls, parent: Path, name: str) -> "Project":
        parent.mkdir(parents=True, exist_ok=True)
        base = slugify(name)
        root = parent / base
        i = 2
        while root.exists():
            root = parent / f"{base}-{i}"
            i += 1
        root.mkdir(parents=True)
        (root / "images").mkdir()
        (root / "output").mkdir()
        proj = cls(root=root, name=name, created=datetime.now().isoformat(timespec="seconds"))
        proj.save()
        return proj

    @classmethod
    def load(cls, root: Path) -> "Project":
        root = Path(root)
        data: dict = {}
        if (root / "project.json").exists():
            data = json.loads((root / "project.json").read_text(encoding="utf-8"))
        settings = dict(DEFAULT_SETTINGS)
        settings.update(data.get("settings", {}))
        return cls(root=root, name=data.get("name", root.name), settings=settings,
                   created=data.get("created", ""), line_options=data.get("line_options", {}))

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        data = {"name": self.name, "created": self.created, "settings": self.settings}
        if self.line_options:
            data["line_options"] = self.line_options
        self.config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def line_option(self, line_id: int, key: str, default=None):
        return self.line_options.get(str(line_id), {}).get(key, default)

    def set_line_option(self, line_id: int, key: str, value) -> None:
        """Per-line choice; None removes it (back to the project setting)."""
        opts = self.line_options.setdefault(str(line_id), {})
        if value is None:
            opts.pop(key, None)
        else:
            opts[key] = value
        if not opts:
            self.line_options.pop(str(line_id), None)

    # ── content ────────────────────────────────────────────
    def narration_path(self) -> Path | None:
        for p in sorted(self.root.glob("narration.*")):
            if p.suffix.lower() in AUDIO_EXTS:
                return p
        return None

    def set_narration(self, src: Path, filename: str) -> Path:
        for old in self.root.glob("narration.*"):
            old.unlink()
        ext = Path(filename).suffix.lower() or ".mp3"
        dst = self.root / f"narration{ext}"
        shutil.copyfile(src, dst)
        # Timings belong to the old recording.
        for stale in (self.transcript_path, self.timeline_path):
            if stale.exists():
                stale.unlink()
        return dst

    def script_text(self) -> str:
        return self.script_path.read_text(encoding="utf-8") if self.script_path.exists() else ""

    def lines(self) -> list[ScriptLine]:
        return parse_script(self.script_text())

    def language(self) -> str:
        lang = self.settings.get("language", "auto")
        if lang in ("en", "fa"):
            return lang
        return detect_language(self.script_text())

    def images(self) -> tuple[dict[int, Path], list[str]]:
        return map_images(self.images_dir)

    def load_timeline(self) -> dict | None:
        if not self.timeline_path.exists():
            return None
        return json.loads(self.timeline_path.read_text(encoding="utf-8"))

    def save_timeline(self, timeline: dict) -> None:
        self.timeline_path.write_text(json.dumps(timeline, indent=1, ensure_ascii=False), encoding="utf-8")

    def status(self) -> dict:
        """Summary used by the UI and the CLI `check` command."""
        lines = self.lines()
        images, warnings = self.images()
        ids = [ln.id for ln in lines]
        missing = [i for i in ids if i not in images]
        extra = sorted(n for n in images if n not in set(ids))
        timeline = self.load_timeline()
        narration = self.narration_path()
        renders = sorted(self.output_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True) \
            if self.output_dir.exists() else []
        return {
            "name": self.name,
            "slug": self.slug,
            "language": self.language(),
            "narration": narration.name if narration else None,
            "lines": len(lines),
            "images": len(images),
            "missing_images": missing,
            "extra_images": extra,
            "warnings": warnings,
            "aligned": timeline is not None,
            "timeline_source": timeline.get("source") if timeline else None,
            "renders": [p.name for p in renders],
            "subtitles": [p.with_suffix(".srt").name for p in renders if p.with_suffix(".srt").exists()],
        }
