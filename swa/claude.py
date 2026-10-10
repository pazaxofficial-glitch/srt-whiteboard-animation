"""Let Claude Code draw a project's scenes, so no images are needed.

The app does not call an AI service itself. It starts the Claude Code
command line tool that is installed on this computer (signed in with the
user's own Claude account) in the app folder, with a task file that points
at the drawing skill (.claude/skills/draw-whiteboard-images). Claude writes
images/<line>.svg for every line it is asked to draw; the app follows its
progress through Claude Code's event stream and the images folder.

The same result can be had by hand: open this folder in Claude Code and
paste `manual_prompt(project)`. That is also the way to ask for animated
clips made with HyperFrames or Remotion, which need more permissions than
an unattended run gets.
"""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from . import paths
from .project import VISUAL_EXTS, Project, image_number

SKILL = ".claude/skills/draw-whiteboard-images/SKILL.md"
BATCH = 15            # lines per Claude Code run (fresh context, steady quality, visible progress)
# Unattended runs may only read, write files in this folder and run the app's own checks.
ALLOWED_TOOLS = [
    "Read", "Write", "Edit", "MultiEdit", "Glob", "Grep", "TodoWrite",
    "Bash(python -m swa lint-svg:*)", "Bash(python -m swa sheet:*)", "Bash(python -m swa check:*)",
    "Bash(python -m swa lint-svg *)", "Bash(python -m swa sheet *)", "Bash(python -m swa check *)",
]

Progress = Callable[[str, float, dict], None]


class ClaudeError(RuntimeError):
    def __init__(self, message: str, code: str = "failed"):
        super().__init__(message)
        self.code = code            # "missing" | "login" | "limit" | "failed"


def find_cli() -> str | None:
    """Path of the `claude` command, or None if Claude Code is not installed."""
    env = os.environ.get("CLAUDE_CLI")
    if env:
        return env if Path(env).exists() or shutil.which(env) else None
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    candidates = [home / ".local" / "bin" / "claude", home / ".claude" / "local" / "claude",
                  home / ".claude" / "local" / "claude.exe", home / ".local" / "bin" / "claude.exe",
                  Path("/usr/local/bin/claude"), Path("/opt/homebrew/bin/claude")]
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "npm" / "claude.cmd")
    return next((str(p) for p in candidates if p.exists()), None)


def manual_prompt(project: Project) -> str:
    """What to type into Claude Code to have the scenes drawn by hand."""
    return f'Draw the scenes for the project "{project.slug}". Follow {SKILL}.'


def missing_lines(project: Project) -> list[int]:
    images, _ = project.images()
    return [ln.id for ln in project.lines() if ln.id not in images]


def _ranges(ids: list[int]) -> str:
    out, i = [], 0
    while i < len(ids):
        j = i
        while j + 1 < len(ids) and ids[j + 1] == ids[j] + 1:
            j += 1
        out.append(str(ids[i]) if i == j else f"{ids[i]}-{ids[j]}")
        i = j + 1
    return ", ".join(out)


def task_text(project: Project, line_ids: list[int], redo: bool = False) -> str:
    """The instructions one Claude Code run reads (written to a file, linked from the prompt)."""
    try:
        rel = os.path.relpath(project.root, paths.APP_ROOT).replace(os.sep, "/")
    except ValueError:          # another drive on Windows
        rel = str(project.root)
    if rel.startswith(".."):
        rel = str(project.root)
    aspect = project.settings.get("aspect", "16:9")
    box = {"9:16": "0 0 900 1600", "1:1": "0 0 1200 1200", "4:5": "0 0 1200 1500"}.get(aspect, "0 0 1600 900")
    brief = (project.settings.get("claude_brief") or "").strip()
    dark = str(project.settings.get("background", "")).startswith(("chalk", "black"))
    lines = {ln.id: ln.text for ln in project.lines()}
    todo = "\n".join(f"{i}. {lines[i]}" for i in line_ids if i in lines)
    images, _ = project.images()
    examples = sorted((p.name for n, p in images.items() if p.suffix.lower() == ".svg" and n not in line_ids))[:3]
    parts = [
        f"# Task: draw whiteboard scenes for the project \"{project.name}\"",
        "",
        f"Project folder: `{rel}` (script: `{rel}/script.txt`, settings: `{rel}/project.json`).",
        f"Read `{SKILL}` and `docs/svg-style-guide.md` first and follow them exactly.",
        "",
        f"Draw these lines ({_ranges(line_ids)}). For each line N write `{rel}/images/N.svg` "
        f"with viewBox=\"{box}\".",
        "" if not redo else "These lines already have a picture: replace it with a better one (write N.svg).",
        "",
        todo,
        "",
        "Use data-word=\"...\" groups so each object is drawn when its word is spoken.",
        "This is an unattended run: only write SVG files for the lines above, do not touch any other file, "
        "and do not try to install or run other tools (no HyperFrames or Remotion clips in this run).",
        f"When the SVGs are written, run `python -m swa lint-svg {project.slug}` and fix every problem, then "
        f"`python -m swa sheet {project.slug} --lines {line_ids[0]}-{line_ids[-1]}` and look at "
        f"`{rel}/contact-sheet.png`; redraw anything that does not read clearly.",
    ]
    if dark:
        parts.append("The board is dark: draw with dark ink as usual, the app turns it into chalk.")
    if examples:
        parts.append(f"Match the style and the characters of the pictures already drawn, e.g. "
                     + ", ".join(f"`{rel}/images/{e}`" for e in examples) + ".")
    if brief:
        parts += ["", "## Instructions from the author (follow them)", "", brief]
    parts += ["", "Finish with one short sentence saying how many scenes you drew."]
    return "\n".join(p for p in parts if p is not None) + "\n"


def _env() -> dict:
    env = dict(os.environ)
    # `python -m swa ...` inside Claude Code must find this Python and these projects.
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    env["SWA_DATA"] = str(paths.DATA)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _kill(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        else:
            os.killpg(proc.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _explain(text: str) -> ClaudeError:
    low = text.lower()
    if any(k in low for k in ("login", "log in", "api key", "authenticat", "not logged", "/login")):
        return ClaudeError("Claude Code is not signed in. Open a terminal, run `claude` once and sign in.", "login")
    if any(k in low for k in ("usage limit", "rate limit", "limit reached", "quota")):
        return ClaudeError(text.strip()[:300] or "Claude usage limit reached.", "limit")
    return ClaudeError(text.strip()[:500] or "Claude Code stopped without drawing.", "failed")


def _line_of(path: str) -> int | None:
    m = re.search(r"images[\\/]+(\d+)\.[A-Za-z0-9]+$", path or "")
    return int(m.group(1)) if m else None


def _tidy(project: Project, ids: list[int], since: float) -> set[int]:
    """Lines that got a new picture. Such a line keeps only its new file; older ones go to images/.replaced/."""
    if not project.images_dir.exists():
        return set()
    files = [p for p in project.images_dir.iterdir() if p.is_file() and p.suffix.lower() in VISUAL_EXTS]
    old_dir = project.images_dir / ".replaced"
    done = set()
    for n in ids:
        mine = [p for p in files if image_number(p) == n]
        fresh = [p for p in mine if p.stat().st_mtime >= since - 1]
        if not fresh:
            continue
        done.add(n)
        for p in mine:
            if p not in fresh:
                old_dir.mkdir(exist_ok=True)
                shutil.move(str(p), str(old_dir / p.name))
    return done


def _run_batch(cli: str, project: Project, line_ids: list[int], redo: bool, progress: Progress,
               cancel: threading.Event | None, done_before: int, total: int) -> tuple[set[int], str]:
    task_dir = paths.DATA / ".cache" / "claude"
    task_dir.mkdir(parents=True, exist_ok=True)
    task = task_dir / f"task-{os.getpid()}-{line_ids[0]}.md"
    task.write_text(task_text(project, line_ids, redo), encoding="utf-8")
    try:
        rel_task = os.path.relpath(task, paths.APP_ROOT).replace(os.sep, "/")
    except ValueError:
        rel_task = str(task)
    if rel_task.startswith(".."):
        rel_task = str(task)
    cmd = [cli, "-p", f"Read the task file {rel_task} and do exactly what it says.",
           "--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits",
           "--allowedTools", *ALLOWED_TOOLS]
    if not str(paths.DATA).startswith(str(paths.APP_ROOT)):
        cmd += ["--add-dir", str(paths.DATA)]
    kw: dict = {}
    if sys.platform.startswith("win"):
        kw["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kw["start_new_session"] = True
    proc = subprocess.Popen(cmd, cwd=str(paths.APP_ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=_env(), **kw)
    lines: queue.Queue = queue.Queue()

    def pump():
        for raw in proc.stdout:
            lines.put(raw)
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    wanted = set(line_ids)
    drawn: set[int] = set()
    result_text, is_error = "", False
    step, line = "starting", None
    try:
        while True:
            if cancel is not None and cancel.is_set():
                _kill(proc)
                raise ClaudeError("Cancelled", "cancelled")
            try:
                raw = lines.get(timeout=0.5)
            except queue.Empty:
                continue
            if raw is None:
                break
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            if ev.get("type") == "assistant":
                for block in (ev.get("message") or {}).get("content") or []:
                    if block.get("type") != "tool_use":
                        continue
                    name, args = block.get("name", ""), block.get("input") or {}
                    target = _line_of(str(args.get("file_path", "")))
                    if name in ("Write", "Edit", "MultiEdit") and target is not None:
                        step, line = "drawing", target
                        if target in wanted:
                            drawn.add(target)
                    elif name == "Bash" and "lint-svg" in str(args.get("command", "")):
                        step, line = "checking", None
                    elif name == "Bash" and "sheet" in str(args.get("command", "")):
                        step, line = "reviewing", None
                    elif name == "Read" and "contact-sheet" in str(args.get("file_path", "")):
                        step, line = "reviewing", None
                    elif name == "Read" and step == "starting":
                        step = "reading"
                    frac = (done_before + len(drawn)) / max(1, total)
                    msg = {"reading": "Reading the script and the style guide", "drawing": f"Drawing line {line}",
                           "checking": "Checking the drawings", "reviewing": "Looking at the drawings"}.get(step, "")
                    progress(msg, min(0.99, frac), {"step": step, "line": line, "drawn": done_before + len(drawn),
                                                    "total": total})
            elif ev.get("type") == "result":
                result_text = str(ev.get("result") or "")
                is_error = bool(ev.get("is_error")) or ev.get("subtype", "success") != "success"
        proc.wait()
    finally:
        _kill(proc)
        try:
            task.unlink()
        except OSError:
            pass
    err = proc.stderr.read() if proc.stderr else ""
    if (is_error or proc.returncode not in (0, None)) and not drawn:
        raise _explain(result_text or err)
    return drawn, result_text


def draw_scenes(project: Project, line_ids: list[int] | None = None, redo: bool = False,
                progress: Progress | None = None, cancel: threading.Event | None = None) -> dict:
    """Have Claude Code draw `line_ids` (default: every line without a picture)."""
    cli = find_cli()
    if cli is None:
        raise ClaudeError("Claude Code was not found on this computer.", "missing")
    ids = sorted(set(line_ids)) if line_ids else missing_lines(project)
    known = {ln.id for ln in project.lines()}
    ids = [i for i in ids if i in known]
    if not ids:
        return {"drawn": [], "missing": [], "message": "Every line already has a picture."}
    progress = progress or (lambda m, f, i: None)
    started = time.time()
    drawn: set[int] = set()
    message = ""
    for k in range(0, len(ids), BATCH):
        batch = ids[k:k + BATCH]
        got, message = _run_batch(cli, project, batch, redo, progress, cancel, len(drawn), len(ids))
        drawn |= got
    really = _tidy(project, ids, started)
    progress("Done", 1.0, {"step": "done", "drawn": len(really), "total": len(ids)})
    return {"drawn": sorted(really), "missing": [i for i in ids if i not in really], "message": message[:500]}
