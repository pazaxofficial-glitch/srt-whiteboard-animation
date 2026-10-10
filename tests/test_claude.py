import importlib
import json
import os
import stat
import sys
import time
from pathlib import Path

import pytest

FAKE = r'''#!{python}
"""Stands in for the Claude Code CLI: draws a tiny SVG for every line in the task file."""
import json, re, sys
from pathlib import Path
args = sys.argv[1:]
mode = {mode!r}
prompt = args[args.index("-p") + 1]
task = Path(re.search(r"task file (\S+)", prompt).group(1))
text = task.read_text(encoding="utf-8")
folder = Path(re.search(r"Project folder: `([^`]+)`", text).group(1))
assert "--allowedTools" in args and "Read" in args and "acceptEdits" in args
if mode == "login":
    print(json.dumps({{"type": "result", "subtype": "success", "is_error": True,
                       "result": "Invalid API key · Please run /login"}}))
    sys.exit(1)
for n in re.findall(r"^(\d+)\. ", text, flags=re.M):
    f = folder / "images" / f"{{n}}.svg"
    f.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900" width="1600" height="900">'
                 '<g fill="none" stroke="#222" stroke-width="7"><circle cx="800" cy="450" r="200"/></g></svg>')
    print(json.dumps({{"type": "assistant", "message": {{"content": [
        {{"type": "tool_use", "name": "Write", "input": {{"file_path": str(f), "content": "..."}}}}]}}}}), flush=True)
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "result": "Drew them all."}}))
'''


def fake_cli(tmp_path: Path, mode: str = "ok") -> Path:
    exe = tmp_path / f"claude-{mode}"
    exe.write_text(FAKE.format(python=sys.executable, mode=mode), encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SWA_DATA", str(tmp_path / "data"))
    import swa.paths
    importlib.reload(swa.paths)
    import swa.claude
    importlib.reload(swa.claude)
    swa.paths.ensure_dirs()
    from swa.project import Project
    proj = Project.create(swa.paths.PROJECTS, "Claude test")
    proj.script_path.write_text("1. A helmet.\n2. A shield and a spear.\n3. Mountains at sunrise.\n", encoding="utf-8")
    return swa.claude, proj


@pytest.mark.skipif(sys.platform.startswith("win"), reason="the fake CLI is a shebang script")
def test_claude_draws_missing_lines(env, tmp_path, monkeypatch):
    claude, proj = env
    (proj.images_dir / "2.png").write_bytes(b"not really a png")
    monkeypatch.setenv("CLAUDE_CLI", str(fake_cli(tmp_path)))
    assert claude.find_cli() is not None
    seen = []
    res = claude.draw_scenes(proj, progress=lambda m, f, i: seen.append(i.get("step")))
    assert res["drawn"] == [1, 3] and res["missing"] == []
    assert (proj.images_dir / "1.svg").exists() and (proj.images_dir / "3.svg").exists()
    assert "drawing" in seen and seen[-1] == "done"
    assert not list((proj.root.parent.parent / ".cache" / "claude").glob("*.md"))   # task files are cleaned up


@pytest.mark.skipif(sys.platform.startswith("win"), reason="the fake CLI is a shebang script")
def test_redraw_replaces_the_old_picture(env, tmp_path, monkeypatch):
    claude, proj = env
    old = proj.images_dir / "2.png"
    old.write_bytes(b"old")
    os.utime(old, (time.time() - 100, time.time() - 100))
    monkeypatch.setenv("CLAUDE_CLI", str(fake_cli(tmp_path)))
    res = claude.draw_scenes(proj, [2], redo=True)
    assert res["drawn"] == [2]
    images, warnings = proj.images()
    assert images[2].name == "2.svg" and not warnings
    assert (proj.images_dir / ".replaced" / "2.png").exists()


@pytest.mark.skipif(sys.platform.startswith("win"), reason="the fake CLI is a shebang script")
def test_not_signed_in_is_explained(env, tmp_path, monkeypatch):
    claude, proj = env
    monkeypatch.setenv("CLAUDE_CLI", str(fake_cli(tmp_path, "login")))
    with pytest.raises(claude.ClaudeError) as err:
        claude.draw_scenes(proj)
    assert err.value.code == "login"


def test_task_file_has_lines_brief_and_rules(env):
    claude, proj = env
    proj.settings["claude_brief"] = "Use one Spartan character with a red crest."
    text = claude.task_text(proj, [1, 3])
    assert "1. A helmet." in text and "3. Mountains at sunrise." in text and "2. A shield" not in text
    assert "red crest" in text and "lint-svg" in text and "data-word" in text
    assert claude.manual_prompt(proj).startswith('Draw the scenes for the project "claude-test"')


def test_missing_cli(env, monkeypatch):
    claude, proj = env
    monkeypatch.setenv("CLAUDE_CLI", "/nonexistent/claude")
    assert claude.find_cli() is None
    with pytest.raises(claude.ClaudeError) as err:
        claude.draw_scenes(proj)
    assert err.value.code == "missing"
