"""Local web app: http://127.0.0.1:7860 (only reachable from this computer)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import webbrowser
import zipfile
from pathlib import Path

import cv2
import numpy as np
from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import __version__, paths
from ..align import align_project, whisper_backends
from ..project import AUDIO_EXTS, DEFAULT_SETTINGS, IMAGE_EXTS, Project, slugify
from ..render import hands as hands_mod
from ..render.backgrounds import BUILTIN as BUILTIN_BACKGROUNDS
from ..render.backgrounds import make_background
from ..render.imageio import imread
from .jobs import JobManager

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Simple Whiteboard Animation", version=__version__)
jobs = JobManager()


# ──────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────
def _proj(slug: str) -> Project:
    root = paths.PROJECTS / Path(slug).name
    if not root.is_dir():
        raise HTTPException(404, "Project not found")
    return Project.load(root)


def _safe_child(folder: Path, name: str) -> Path:
    p = folder / Path(name).name
    if not p.exists():
        raise HTTPException(404, "File not found")
    return p


def _save_upload(upload: UploadFile, dst: Path) -> None:
    with dst.open("wb") as fh:
        shutil.copyfileobj(upload.file, fh)


def _jpeg(img, quality: int = 85) -> Response:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return Response(buf.tobytes(), media_type="image/jpeg")


def _coerce(key: str, value):
    default = DEFAULT_SETTINGS[key]
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(default, int) and not isinstance(default, bool):
        return int(float(value))
    if isinstance(default, float):
        return float(value)
    return str(value)


def ffmpeg_ok() -> bool:
    return bool(os.environ.get("FFMPEG") or shutil.which("ffmpeg"))


# ──────────────────────────────────────────────────────────────
# app info
# ──────────────────────────────────────────────────────────────
@app.get("/api/info")
def info():
    return {
        "version": __version__,
        "whisper": whisper_backends(),
        "ffmpeg": ffmpeg_ok(),
        "defaults": DEFAULT_SETTINGS,
        "data_dir": str(paths.DATA),
    }


# ──────────────────────────────────────────────────────────────
# projects
# ──────────────────────────────────────────────────────────────
@app.get("/api/projects")
def list_projects():
    out = []
    if paths.PROJECTS.exists():
        for d in sorted(paths.PROJECTS.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if d.is_dir() and (d / "project.json").exists():
                st = Project.load(d).status()
                st["modified"] = d.stat().st_mtime
                out.append(st)
    return out


@app.post("/api/projects")
def create_project(data: dict = Body(...)):
    name = (data.get("name") or "").strip() or "Untitled video"
    proj = Project.create(paths.PROJECTS, name)
    return proj.status()


@app.get("/api/projects/{slug}")
def get_project(slug: str):
    proj = _proj(slug)
    images, _ = proj.images()
    st = proj.status()
    st.update({
        "settings": proj.settings,
        "script": proj.script_text(),
        "parsed": [{"id": ln.id, "text": ln.text, "image": images[ln.id].name if ln.id in images else None}
                   for ln in proj.lines()],
        "image_files": {str(k): v.name for k, v in sorted(images.items())},
        "timeline": proj.load_timeline(),
        "jobs": [j.as_dict() for j in jobs.active_for(slug)],
        "path": str(proj.root),
    })
    return st


@app.patch("/api/projects/{slug}")
def rename_project(slug: str, data: dict = Body(...)):
    proj = _proj(slug)
    if data.get("name"):
        proj.name = str(data["name"]).strip()
        proj.save()
    return proj.status()


@app.delete("/api/projects/{slug}")
def delete_project(slug: str):
    proj = _proj(slug)
    shutil.rmtree(proj.root)
    return {"ok": True}


@app.put("/api/projects/{slug}/settings")
def update_settings(slug: str, data: dict = Body(...)):
    proj = _proj(slug)
    for k, v in data.items():
        if k in DEFAULT_SETTINGS:
            try:
                proj.settings[k] = _coerce(k, v)
            except (TypeError, ValueError):
                raise HTTPException(400, f"Bad value for {k}")
    proj.save()
    return proj.settings


@app.put("/api/projects/{slug}/script")
def update_script(slug: str, data: dict = Body(...)):
    proj = _proj(slug)
    proj.script_path.write_text(str(data.get("text", "")), encoding="utf-8")
    # Lines changed: old timings no longer match.
    tl = proj.load_timeline()
    if tl is not None:
        old = [(ln["id"], ln["text"]) for ln in tl["lines"]]
        new = [(ln.id, ln.text) for ln in proj.lines()]
        if old != new:
            proj.timeline_path.unlink()
    return get_project(slug)


@app.post("/api/projects/{slug}/narration")
def upload_narration(slug: str, file: UploadFile = File(...)):
    proj = _proj(slug)
    if Path(file.filename or "").suffix.lower() not in AUDIO_EXTS:
        raise HTTPException(400, "Unsupported audio format")
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
    try:
        proj.set_narration(Path(tmp.name), file.filename or "narration.mp3")
    finally:
        os.unlink(tmp.name)
    return proj.status()


@app.get("/api/projects/{slug}/narration")
def get_narration(slug: str):
    proj = _proj(slug)
    p = proj.narration_path()
    if p is None:
        raise HTTPException(404, "No narration")
    return FileResponse(p)


# ── images ─────────────────────────────────────────────────
@app.post("/api/projects/{slug}/images")
def upload_images(slug: str, files: list[UploadFile] = File(...), replace: bool = Form(False)):
    proj = _proj(slug)
    proj.images_dir.mkdir(parents=True, exist_ok=True)
    if replace:
        shutil.rmtree(proj.images_dir)
        proj.images_dir.mkdir()
        shutil.rmtree(proj.root / ".thumbs", ignore_errors=True)
    saved, skipped = 0, []
    for up in files:
        name = Path(up.filename or "").name
        ext = Path(name).suffix.lower()
        if ext == ".zip":
            with tempfile.TemporaryFile() as tmp:
                shutil.copyfileobj(up.file, tmp)
                tmp.seek(0)
                with zipfile.ZipFile(tmp) as zf:
                    for member in zf.infolist():
                        mname = Path(member.filename).name
                        if member.is_dir() or Path(mname).suffix.lower() not in IMAGE_EXTS or mname.startswith("."):
                            continue
                        with zf.open(member) as src, (proj.images_dir / mname).open("wb") as dst:
                            shutil.copyfileobj(src, dst)
                        saved += 1
            continue
        if ext not in IMAGE_EXTS:
            skipped.append(name)
            continue
        _save_upload(up, proj.images_dir / name)
        thumb = proj.root / ".thumbs" / (name + ".jpg")
        if thumb.exists():
            thumb.unlink()
        saved += 1
    st = get_project(slug)
    st["saved"] = saved
    st["skipped"] = skipped
    return st


@app.delete("/api/projects/{slug}/images")
def delete_all_images(slug: str):
    proj = _proj(slug)
    shutil.rmtree(proj.images_dir, ignore_errors=True)
    shutil.rmtree(proj.root / ".thumbs", ignore_errors=True)
    proj.images_dir.mkdir()
    return get_project(slug)


@app.delete("/api/projects/{slug}/images/{name}")
def delete_image(slug: str, name: str):
    proj = _proj(slug)
    _safe_child(proj.images_dir, name).unlink()
    return get_project(slug)


@app.get("/api/projects/{slug}/images/{name}")
def get_image(slug: str, name: str, thumb: bool = False):
    proj = _proj(slug)
    p = _safe_child(proj.images_dir, name)
    if not thumb or p.suffix.lower() == ".svg":
        return FileResponse(p)
    tdir = proj.root / ".thumbs"
    tdir.mkdir(exist_ok=True)
    t = tdir / (p.name + ".jpg")
    if not t.exists() or t.stat().st_mtime < p.stat().st_mtime:
        img = imread(p)
        if img is None:
            raise HTTPException(415, "Unreadable image")
        if img.shape[2] == 4:
            a = img[:, :, 3:4].astype("float32") / 255
            img = (img[:, :, :3] * a + 255 * (1 - a)).astype("uint8")
        s = 360 / max(img.shape[:2])
        if s < 1:
            img = cv2.resize(img, (int(img.shape[1] * s), int(img.shape[0] * s)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 82])
        buf.tofile(str(t))
    return FileResponse(t, media_type="image/jpeg")


# ── sync ───────────────────────────────────────────────────
@app.post("/api/projects/{slug}/align")
def start_align(slug: str, data: dict = Body(default={})):
    proj = _proj(slug)
    method = data.get("method", "whisper")
    srt = data.get("srt")
    if "whisper_model" in data:
        proj.settings["whisper_model"] = str(data["whisper_model"])
        proj.save()

    def run(job):
        def prog(msg, frac):
            job.message, job.progress = msg, frac
            if job.cancel.is_set():
                raise RuntimeError("Cancelled")
        tl = align_project(proj, method, srt, progress=prog, reuse_transcript=not data.get("retranscribe"))
        return {"lines": len(tl["lines"])}

    try:
        job = jobs.start("align", slug, run)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return job.as_dict()


@app.put("/api/projects/{slug}/timeline")
def save_timeline(slug: str, data: dict = Body(...)):
    """Manual timing edits: [{id, start, end}] — the line's words are stretched to fit."""
    proj = _proj(slug)
    tl = proj.load_timeline()
    if tl is None:
        raise HTTPException(400, "No timeline yet")
    edits = {int(e["id"]): e for e in data.get("lines", [])}
    for ln in tl["lines"]:
        e = edits.get(int(ln["id"]))
        if not e:
            continue
        s, en = float(e["start"]), float(e["end"])
        if en < s:
            en = s
        os_, oe = ln["start"], ln["end"]
        span = (oe - os_) or 1.0
        for w in ln.get("words", []):
            w["s"] = round(s + (w["s"] - os_) / span * (en - s), 3)
            w["e"] = round(s + (w["e"] - os_) / span * (en - s), 3)
        ln["start"], ln["end"] = round(s, 3), round(en, 3)
    tl["source"] = tl.get("source", "") + "+edited" if "edited" not in tl.get("source", "") else tl["source"]
    proj.save_timeline(tl)
    return tl


# ── render ─────────────────────────────────────────────────
@app.post("/api/projects/{slug}/render")
def start_render(slug: str, data: dict = Body(default={})):
    from ..render.compositor import render_project

    proj = _proj(slug)
    if not ffmpeg_ok():
        raise HTTPException(400, "FFmpeg was not found on this computer.")
    overrides = {}
    if data.get("draft"):
        overrides.update({"resolution": min(720, int(proj.settings.get("resolution", 1080))), "quality": "draft"})
    t_from, t_to = 0.0, None
    out = None
    if data.get("line") is not None:
        tl = proj.load_timeline() or {"lines": []}
        ids = [int(ln["id"]) for ln in tl["lines"]]
        lid = int(data["line"])
        if lid not in ids:
            raise HTTPException(400, "Line not in timeline")
        i = ids.index(lid)
        t_from = max(0.0, tl["lines"][i]["start"] - 0.8)
        t_to = tl["lines"][i + 1]["start"] if i + 1 < len(ids) else None
        prev_dir = proj.root / ".previews"
        prev_dir.mkdir(exist_ok=True)
        for old in prev_dir.glob("*.mp4"):
            old.unlink()
        out = prev_dir / f"line-{lid}-{os.urandom(3).hex()}.mp4"

    def run(job):
        def prog(msg, frac, info):
            job.message, job.progress = msg, frac
            job.info.update(info or {})
        path = render_project(proj, out, progress=prog, cancel=job.cancel, t_from=t_from, t_to=t_to,
                              overrides=overrides)
        return {"file": path.name, "preview": out is not None}

    try:
        job = jobs.start("render", slug, run)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return job.as_dict()


@app.get("/api/projects/{slug}/output/{name}")
def get_output(slug: str, name: str, download: bool = False):
    proj = _proj(slug)
    for folder in (proj.output_dir, proj.root / ".previews"):
        p = folder / Path(name).name
        if p.exists():
            kind = "text/plain; charset=utf-8" if p.suffix.lower() in (".srt", ".vtt") else "video/mp4"
            return FileResponse(p, media_type=kind, filename=p.name if download else None)
    raise HTTPException(404, "Not found")


@app.delete("/api/projects/{slug}/output/{name}")
def delete_output(slug: str, name: str):
    proj = _proj(slug)
    p = _safe_child(proj.output_dir, name)
    p.unlink()
    for side in (p.with_suffix(".srt"), p.with_suffix(".vtt")):
        if side.exists():
            side.unlink()
    return {"ok": True}


@app.get("/api/projects/{slug}/still")
def still(slug: str, line: int | None = None):
    from ..render.compositor import still_frame

    proj = _proj(slug)
    try:
        img = still_frame(proj, line)
    except Exception as exc:
        raise HTTPException(400, str(exc))
    return _jpeg(img)


@app.get("/api/projects/{slug}/cover")
def cover(slug: str):
    """Small cached still for the project list."""
    from ..render.compositor import still_frame

    proj = _proj(slug)
    tdir = proj.root / ".thumbs"
    tdir.mkdir(exist_ok=True)
    c = tdir / "cover.jpg"
    newest = max([proj.config_path.stat().st_mtime, proj.images_dir.stat().st_mtime if proj.images_dir.exists() else 0])
    if not c.exists() or c.stat().st_mtime < newest:
        try:
            img = still_frame(proj, None, max_width=480)
        except Exception as exc:
            raise HTTPException(400, str(exc))
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 82])
        buf.tofile(str(c))
    return FileResponse(c, media_type="image/jpeg")


@app.post("/api/projects/{slug}/open-folder")
def open_folder(slug: str):
    proj = _proj(slug)
    _open_path(proj.root)
    return {"ok": True}


def _open_path(p: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
    except Exception as exc:
        raise HTTPException(500, f"Could not open folder: {exc}")


# ── jobs ───────────────────────────────────────────────────
@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job")
    return job.as_dict()


@app.post("/api/jobs/{job_id}/cancel")
def job_cancel(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job")
    job.cancel.set()
    return job.as_dict()


# ──────────────────────────────────────────────────────────────
# hands
# ──────────────────────────────────────────────────────────────
@app.get("/api/hands")
def get_hands():
    return hands_mod.list_hands()


@app.get("/api/hands/{hand_id}/image")
def hand_image(hand_id: str):
    d = hands_mod.find_hand(hand_id)
    if d is None:
        raise HTTPException(404, "Unknown hand")
    return FileResponse(d / "hand.png", media_type="image/png")


@app.post("/api/hands")
def upload_hand(file: UploadFile = File(...), name: str = Form("My hand")):
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename or "x.png").suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
    try:
        hid = hands_mod.save_hand(Path(tmp.name), name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    finally:
        os.unlink(tmp.name)
    return {"id": hid}


@app.put("/api/hands/{hand_id}")
def edit_hand(hand_id: str, data: dict = Body(...)):
    try:
        hands_mod.update_hand(hand_id, name=data.get("name"), tip=data.get("tip"),
                              size=float(data["size"]) if data.get("size") else None)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@app.delete("/api/hands/{hand_id}")
def remove_hand(hand_id: str):
    try:
        hands_mod.delete_hand(hand_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


# ──────────────────────────────────────────────────────────────
# fonts (handwriting)
# ──────────────────────────────────────────────────────────────
@app.get("/api/fonts")
def get_fonts():
    from ..render.text import FONTS
    return [{"id": k, "name": v[1], "script": v[2]} for k, v in FONTS.items() if k != "caption"]


@app.get("/api/fonts/preview")
def font_preview(id: str, text: str = ""):
    from ..render.text import FONTS, FontPair, layout_text, render_layout

    if id not in FONTS:
        raise HTTPException(404, "Unknown font")
    if not text:
        text = "Life, the Spartan way" if FONTS[id][2] == "latin" else "\u0632\u0646\u062f\u06af\u06cc \u0627\u0633\u067e\u0627\u0631\u062a\u06cc"
    pair = FontPair.get(id, id)
    lay = layout_text(text[:60], pair, 56)
    alpha, _ = render_layout(lay, pad=6)
    img = np.dstack([np.full(alpha.shape + (3,), 30, np.uint8), (alpha * 255).astype(np.uint8)])
    ok, buf = cv2.imencode(".png", img)
    return Response(buf.tobytes(), media_type="image/png")


# ──────────────────────────────────────────────────────────────
# music & sounds
# ──────────────────────────────────────────────────────────────
@app.get("/api/music")
def get_music():
    from ..render.music import list_music
    return list_music()


@app.get("/api/music/play")
def play_music(id: str):
    from ..render.music import resolve_music
    try:
        p = resolve_music(id)
    except Exception as exc:
        raise HTTPException(500, f"Could not prepare music: {exc}")
    if p is None:
        raise HTTPException(404, "Unknown track")
    return FileResponse(p)


@app.post("/api/music")
def upload_music(file: UploadFile = File(...)):
    from ..render.music import MUSIC_EXTS, music_dir
    name = Path(file.filename or "music.mp3").name
    ext = Path(name).suffix.lower()
    if ext not in MUSIC_EXTS:
        raise HTTPException(400, "Use MP3, WAV, M4A, OGG or FLAC")
    music_dir().mkdir(parents=True, exist_ok=True)
    dst = music_dir() / f"{slugify(Path(name).stem)}{ext}"
    _save_upload(file, dst)
    return {"id": f"file:{dst.name}"}


@app.delete("/api/music/{name}")
def delete_music(name: str):
    from ..render.music import music_dir
    _safe_child(music_dir(), name).unlink()
    return {"ok": True}


@app.get("/api/sfx/preview")
def sfx_preview(dark: bool = False):
    from ..render.audio import sfx_preview as make
    d = paths.DATA / ".cache"
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"sfx-{'chalk' if dark else 'marker'}.wav"
    if not out.exists():
        make(dark, 1.0, out)
    return FileResponse(out, media_type="audio/wav")


# ──────────────────────────────────────────────────────────────
# backgrounds
# ──────────────────────────────────────────────────────────────
@app.get("/api/backgrounds")
def get_backgrounds():
    items = [{"id": k, "builtin": True, "dark": v[1]} for k, v in BUILTIN_BACKGROUNDS.items()]
    if paths.USER_BACKGROUNDS.exists():
        for p in sorted(paths.USER_BACKGROUNDS.iterdir()):
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                items.append({"id": f"custom:{p.name}", "builtin": False, "name": p.stem})
    return items


@app.get("/api/backgrounds/preview")
def background_preview(id: str):
    try:
        img, _ = make_background(id, 480, 270, paths.USER_BACKGROUNDS)
    except FileNotFoundError:
        raise HTTPException(404, "Unknown background")
    return _jpeg(img, 88)


@app.post("/api/backgrounds")
def upload_background(file: UploadFile = File(...)):
    paths.USER_BACKGROUNDS.mkdir(parents=True, exist_ok=True)
    name = Path(file.filename or "background.png").name
    if Path(name).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(400, "Use a PNG, JPG or WebP image")
    stem, ext = Path(name).stem, Path(name).suffix.lower()
    dst = paths.USER_BACKGROUNDS / f"{slugify(stem)}{ext}"
    _save_upload(file, dst)
    return {"id": f"custom:{dst.name}"}


@app.delete("/api/backgrounds/{name}")
def delete_background(name: str):
    _safe_child(paths.USER_BACKGROUNDS, name).unlink()
    return {"ok": True}


# ──────────────────────────────────────────────────────────────
# static UI
# ──────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC / "index.html").read_text(encoding="utf-8")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


def run(port: int = 7860, open_browser: bool = True) -> None:
    import socket

    import uvicorn

    paths.ensure_dirs()
    # Pick a free port if the default one is taken.
    for candidate in range(port, port + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", candidate)) != 0:
                port = candidate
                break
    url = f"http://127.0.0.1:{port}"

    def warm_up():
        # Compose the built-in music once in the background so previews start instantly.
        from ..render.music import BUILTIN, resolve_music
        for style in BUILTIN:
            try:
                resolve_music(f"builtin:{style}")
            except Exception:
                pass

    threading.Thread(target=warm_up, daemon=True).start()
    print(f"\n  Simple Whiteboard Animation is running at {url}\n  Close this window to stop it.\n")
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
