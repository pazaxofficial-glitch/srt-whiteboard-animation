"""Command line interface.

    python -m swa                      start the app (opens the browser)
    python -m swa new "My Video"       create a project folder
    python -m swa check <project>      show what is missing
    python -m swa align <project>      find line timings with Whisper
    python -m swa render <project>     render the video
    python -m swa render <project> --line 12 --draft   quick preview of one line

<project> is a project folder path or the name of a folder in data/projects.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import paths


def _project(arg: str):
    from .project import Project

    p = Path(arg)
    if not (p / "project.json").exists() and not (p / "script.txt").exists():
        p = paths.PROJECTS / arg
    if not p.exists():
        sys.exit(f"Project not found: {arg}")
    return Project.load(p)


def _bar(msg: str, frac: float, info: dict | None = None) -> None:
    width = 30
    filled = int(frac * width)
    eta = f"  ETA {info['eta']:.0f}s" if info and info.get("eta") is not None else ""
    sys.stdout.write(f"\r[{'#' * filled}{'.' * (width - filled)}] {frac * 100:5.1f}%  {msg}{eta}   ")
    sys.stdout.flush()
    if frac >= 1:
        sys.stdout.write("\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="swa", description="Simple Whiteboard Animation")
    sub = ap.add_subparsers(dest="cmd")

    a = sub.add_parser("app", help="start the web app")
    a.add_argument("--port", type=int, default=7860)
    a.add_argument("--no-browser", action="store_true")

    n = sub.add_parser("new", help="create a project")
    n.add_argument("name")

    c = sub.add_parser("check", help="show project status")
    c.add_argument("project")

    al = sub.add_parser("align", help="sync script lines to the narration")
    al.add_argument("project")
    al.add_argument("--method", choices=["whisper", "srt", "estimate"], default="whisper")
    al.add_argument("--srt", help="SRT file (for --method srt)")
    al.add_argument("--retranscribe", action="store_true", help="ignore the saved transcript")

    r = sub.add_parser("render", help="render the video")
    r.add_argument("project")
    r.add_argument("--out")
    r.add_argument("--from", dest="t_from", type=float, default=0.0, help="start time (seconds)")
    r.add_argument("--to", dest="t_to", type=float, help="end time (seconds)")
    r.add_argument("--line", type=int, help="render only this script line")
    r.add_argument("--draft", action="store_true", help="fast 720p preview")

    sh = sub.add_parser("sheet", help="contact sheet of finished drawings (for reviewing images)")
    sh.add_argument("project")
    sh.add_argument("--out")
    sh.add_argument("--lines", help="e.g. 1-20")

    ls = sub.add_parser("lint-svg", help="check SVG drawings before rendering")
    ls.add_argument("project")

    sub.add_parser("hands", help="list drawing hands")

    args = ap.parse_args(argv)
    paths.ensure_dirs()

    if args.cmd in (None, "app"):
        from .app.server import run
        run(port=getattr(args, "port", 7860), open_browser=not getattr(args, "no_browser", False))
        return 0

    if args.cmd == "new":
        from .project import Project
        proj = Project.create(paths.PROJECTS, args.name)
        print(proj.root)
        return 0

    if args.cmd == "check":
        print(json.dumps(_project(args.project).status(), indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "align":
        from .align import align_project
        proj = _project(args.project)
        srt = Path(args.srt).read_text(encoding="utf-8") if args.srt else None
        tl = align_project(proj, args.method, srt, progress=lambda m, f: _bar(m, f),
                           reuse_transcript=not args.retranscribe)
        for ln in tl["lines"]:
            print(f"{ln['id']:>4}  {ln['start']:8.2f} → {ln['end']:8.2f}  {ln['text'][:60]}")
        return 0

    if args.cmd == "render":
        from .render.compositor import render_project
        proj = _project(args.project)
        overrides = {}
        if args.draft:
            overrides.update({"resolution": 720, "quality": "draft"})
        t_from, t_to = args.t_from, args.t_to
        if args.line is not None:
            tl = proj.load_timeline() or {"lines": []}
            ids = [ln["id"] for ln in tl["lines"]]
            if args.line not in ids:
                sys.exit(f"Line {args.line} is not in the timeline.")
            i = ids.index(args.line)
            t_from = max(0.0, tl["lines"][i]["start"] - 0.8)
            t_to = tl["lines"][i + 1]["start"] if i + 1 < len(ids) else None
        out = render_project(proj, Path(args.out) if args.out else None, progress=_bar,
                             t_from=t_from, t_to=t_to, overrides=overrides)
        print(f"\nSaved: {out}")
        return 0

    if args.cmd == "sheet":
        from .tools import contact_sheet
        proj = _project(args.project)
        rng = None
        if args.lines:
            a, _, b = args.lines.partition("-")
            rng = (int(a), int(b or a))
        out = contact_sheet(proj, Path(args.out) if args.out else None, rng)
        print(out)
        return 0

    if args.cmd == "lint-svg":
        from .tools import lint_svgs
        problems = lint_svgs(_project(args.project))
        for line in problems:
            print(line)
        print("OK" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0

    if args.cmd == "hands":
        from .render.hands import list_hands
        for h in list_hands():
            print(f"{h['id']:<20} {h['name']}{'  (built-in)' if h['builtin'] else ''}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
