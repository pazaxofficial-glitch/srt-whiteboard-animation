#!/usr/bin/env bash
# Start Simple Whiteboard Animation (macOS / Linux).
set -e
cd "$(dirname "$0")"

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  echo "Python 3.10+ is required: https://www.python.org/downloads/"
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "First start: preparing Simple Whiteboard Animation. This happens only once..."
  # --system-site-packages lets the app use a Whisper/PyTorch you already installed.
  "$PY" -m venv --system-site-packages .venv
fi

if ! cmp -s requirements.txt .venv/installed-requirements.txt; then
  echo "Installing components..."
  .venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt
  cp requirements.txt .venv/installed-requirements.txt
fi

command -v ffmpeg >/dev/null 2>&1 || echo "WARNING: FFmpeg was not found. Videos cannot be rendered without it."

exec .venv/bin/python -m swa app "$@"
