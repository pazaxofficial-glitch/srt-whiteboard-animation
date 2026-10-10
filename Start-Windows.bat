@echo off
setlocal
title Simple Whiteboard Animation
cd /d "%~dp0"

rem ---- find Python -------------------------------------------------------
rem Prefer the "python" you normally use (where Whisper is likely installed).
set "PY="
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=python"
if not defined PY (
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=py -3"
)
if not defined PY (
  echo.
  echo  Python was not found.
  echo  Install Python 3.10 or newer from https://www.python.org/downloads/
  echo  and tick "Add python.exe to PATH" during setup.
  echo.
  pause
  exit /b 1
)

rem ---- one-time setup: a private environment that can still see your
rem ---- existing Whisper / PyTorch installation ---------------------------
if not exist ".venv\Scripts\python.exe" (
  echo  First start: preparing Simple Whiteboard Animation. This happens only once...
  %PY% -m venv --system-site-packages .venv
  if errorlevel 1 (
    echo  Could not create the Python environment.
    pause
    exit /b 1
  )
)

rem ---- install or update requirements only when they changed -------------
fc /b requirements.txt ".venv\installed-requirements.txt" >nul 2>nul
if errorlevel 1 (
  echo  Installing components...
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
  if errorlevel 1 (
    echo  Installing components failed. Check your internet connection and try again.
    pause
    exit /b 1
  )
  copy /y requirements.txt ".venv\installed-requirements.txt" >nul
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo.
  echo  WARNING: FFmpeg was not found on PATH. Videos cannot be rendered without it.
  echo.
)

".venv\Scripts\python.exe" -m swa app
if errorlevel 1 pause
