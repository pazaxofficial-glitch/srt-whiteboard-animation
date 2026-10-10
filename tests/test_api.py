import importlib
import io
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
