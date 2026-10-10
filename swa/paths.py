"""Where things live on disk.

Built-in assets ship with the app in `assets/`. Everything the user creates
(projects, uploaded hands and backgrounds) goes to the data folder, which is
`data/` next to the app unless SWA_DATA points somewhere else.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
ASSETS = APP_ROOT / "assets"
DATA = Path(os.environ.get("SWA_DATA", APP_ROOT / "data")).resolve()

PROJECTS = DATA / "projects"
USER_HANDS = DATA / "hands"
USER_BACKGROUNDS = DATA / "backgrounds"
BUILTIN_HANDS = ASSETS / "hands"


def ensure_dirs() -> None:
    for d in (PROJECTS, USER_HANDS, USER_BACKGROUNDS):
        d.mkdir(parents=True, exist_ok=True)
