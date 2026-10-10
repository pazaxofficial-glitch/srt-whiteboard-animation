import importlib
import io
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

DEMO = Path(__file__).resolve().parent.parent / "examples" / "demo"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SWA_DATA", str(tmp_path))
    import swa.paths
    importlib.reload(swa.paths)
    import swa.render.hands
    importlib.reload(swa.render.hands)
    import swa.app.server as server
    importlib.reload(server)
    swa.paths.ensure_dirs()
    from fastapi.testclient import TestClient
    return TestClient(server.app)


def test_project_flow(client):
    p = client.post("/api/projects", json={"name": "Spartan Way"}).json()
    slug = p["slug"]
    r = client.put(f"/api/projects/{slug}/script", json={"text": "1. Helmet\n2. Shield\n3. Training"})
    assert [ln["id"] for ln in r.json()["parsed"]] == [1, 2, 3]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name in ("1.svg", "2.png", "3.svg"):
            zf.write(DEMO / "images" / name, f"pics/{name}")
    r = client.post(f"/api/projects/{slug}/images", files=[("files", ("pics.zip", buf.getvalue(), "application/zip"))])
    assert r.json()["saved"] == 3
    assert r.json()["missing_images"] == []

    assert client.get(f"/api/projects/{slug}/images/2.png?thumb=1").status_code == 200
    s = client.put(f"/api/projects/{slug}/settings", json={"background": "chalkboard", "fps": "24", "bogus": 1}).json()
    assert s["background"] == "chalkboard" and s["fps"] == 24 and "bogus" not in s
    assert client.get(f"/api/projects/{slug}/still").headers["content-type"] == "image/jpeg"


def test_hands_and_backgrounds(client):
    hands = client.get("/api/hands").json()
    assert any(h["id"] == "marker" and h["builtin"] for h in hands)
    png = (DEMO / "images" / "2.png").read_bytes()
    hid = client.post("/api/hands", files={"file": ("my hand.png", png, "image/png")}, data={"name": "My hand"}).json()["id"]
    assert client.put(f"/api/hands/{hid}", json={"tip": [10, 20], "size": 0.4}).status_code == 200
    assert client.delete("/api/hands/marker").status_code == 400
    assert client.delete(f"/api/hands/{hid}").status_code == 200
    r = client.post("/api/backgrounds", files={"file": ("wood desk.png", png, "image/png")}).json()
    assert r["id"] == "custom:wood-desk.png"
    assert client.get("/api/backgrounds/preview", params={"id": r["id"]}).status_code == 200


def test_path_traversal_is_blocked(client):
    slug = client.post("/api/projects", json={"name": "x"}).json()["slug"]
    assert client.get(f"/api/projects/{slug}/images/..%2Fproject.json").status_code == 404


def test_line_options_and_claude_info(client):
    slug = client.post("/api/projects", json={"name": "opts"}).json()["slug"]
    client.put(f"/api/projects/{slug}/script", json={"text": "1. One\n2. Two"})
    r = client.put(f"/api/projects/{slug}/lines/2", json={"coloring": "off"})
    assert r.json()["line_options"] == {"2": {"coloring": "off"}}
    assert client.put(f"/api/projects/{slug}/lines/2", json={"coloring": "maybe"}).status_code == 400
    assert client.put(f"/api/projects/{slug}/lines/2", json={"coloring": "auto"}).json()["line_options"] == {}
    p = client.get(f"/api/projects/{slug}").json()
    assert p["claude_prompt"].startswith("Draw the scenes") and p["settings"]["engine"] == "images"
    s = client.put(f"/api/projects/{slug}/settings", json={"engine": "claude", "claude_brief": "Stick figures",
                                                           "short_threshold": "2.5", "transition": "mix"}).json()
    assert s["engine"] == "claude" and s["short_threshold"] == 2.5 and s["claude_brief"] == "Stick figures"
    assert "claude" in client.get("/api/info").json()


@pytest.mark.skipif(sys.platform.startswith("win"), reason="the fake CLI is a shebang script")
def test_claude_job_draws_scenes(client, tmp_path, monkeypatch):
    from test_claude import fake_cli
    import swa.claude
    importlib.reload(swa.claude)
    monkeypatch.setenv("CLAUDE_CLI", str(fake_cli(tmp_path)))
    slug = client.post("/api/projects", json={"name": "drawn by claude"}).json()["slug"]
    client.put(f"/api/projects/{slug}/script", json={"text": "1. A helmet\n2. A shield"})
    job = client.post(f"/api/projects/{slug}/claude", json={}).json()
    for _ in range(100):
        j = client.get(f"/api/jobs/{job['id']}").json()
        if j["status"] != "running":
            break
        time.sleep(0.1)
    assert j["status"] == "done", j
    assert j["result"]["drawn"] == [1, 2]
    assert client.get(f"/api/projects/{slug}").json()["missing_images"] == []


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_clip_upload_and_thumbnail(client, tmp_path):
    clip = tmp_path / "3.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=160x90:d=1.5:r=10",
                    "-pix_fmt", "yuv420p", str(clip)], check=True)
    slug = client.post("/api/projects", json={"name": "clips"}).json()["slug"]
    client.put(f"/api/projects/{slug}/script", json={"text": "1. a\n2. b\n3. c"})
    r = client.post(f"/api/projects/{slug}/images", files=[("files", ("3.mp4", clip.read_bytes(), "video/mp4"))])
    assert r.json()["saved"] == 1 and r.json()["image_files"]["3"] == "3.mp4"
    t = client.get(f"/api/projects/{slug}/images/3.mp4?thumb=1")
    assert t.status_code == 200 and t.headers["content-type"] == "image/jpeg"
