"""Media Manglers' own tools inside the packaged application folder (installer plan, Stage 1).

Both editions, the portable ZIP and the installer, are one packaged application folder:

    <app folder>\\VideoManglerWorkbench.exe, Video Mangler.ps1, python-core\\src
    <app folder>\\runtime\\ffmpeg\\bin\\ffmpeg.exe and ffprobe.exe        our FFmpeg
    <app folder>\\runtime\\python\\python.exe and speech-lock.json      our private Python

The speech libraries our private Python needs are downloaded once, into
``user_folders.addons_root()\\sp-<set>`` (the set named in ``speech-lock.json``), and shared by both editions.
``use_addons`` puts that one folder on the import path, and only when the running Python is our private one:
a Python already on the PC is never given our files, and our files never go into it. Each Python runs with
only its own packages, plus our add-ons when it is ours.

Every helper run passes through ``media_manglers.cli.main``, which calls ``use_addons`` first; the readiness
check's own probe calls it too.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys

from .user_folders import addons_root

RUNTIME_FOLDER = "runtime"
PYTHON_FOLDER = "python"
FFMPEG_FOLDER = "ffmpeg"
SPEECH_LOCK_FILE = "speech-lock.json"
# The packaged application folder always holds the backend script beside the Workbench.
APP_MARKER = "Video Mangler.ps1"
_PYTHON_NAMES = {"python.exe", "pythonw.exe"}
# A set's name stays short, so the longest speech-library path stays within Windows' path limit.
_SET_ID = re.compile(r"^[0-9a-z]{1,16}$")


def _resolved(path: str | os.PathLike[str] | None) -> Path:
    value = Path(path or sys.executable)
    try:
        return value.resolve()
    except OSError:
        return value.absolute()


def _is_python_folder(folder: Path) -> bool:
    return folder.name.casefold() == PYTHON_FOLDER and folder.parent.name.casefold() == RUNTIME_FOLDER


def app_folder(executable: str | os.PathLike[str] | None = None) -> Path:
    """The packaged application folder a program runs from: the Workbench exe's own folder, or, for our private
    Python, the folder above ``runtime\\python``. Anchored on the program itself, never on the current folder."""

    folder = _resolved(executable).parent
    return folder.parent.parent if _is_python_folder(folder) else folder


def runtime_folder(executable: str | os.PathLike[str] | None = None) -> Path:
    """``<app folder>\\runtime``: where our own FFmpeg and Python sit."""

    return app_folder(executable) / RUNTIME_FOLDER


def private_python_path(app: str | os.PathLike[str]) -> Path:
    """Where our private Python sits inside the packaged application folder ``app``."""

    return Path(app) / RUNTIME_FOLDER / PYTHON_FOLDER / "python.exe"


def is_private_python(executable: str | os.PathLike[str] | None = None) -> bool:
    """Whether ``executable`` (the running Python by default) is our private Python: ``python.exe`` or
    ``pythonw.exe`` in ``runtime\\python`` of a packaged application folder."""

    path = _resolved(executable)
    if path.name.casefold() not in _PYTHON_NAMES or not _is_python_folder(path.parent):
        return False
    return (path.parent.parent.parent / APP_MARKER).is_file()


def speech_set_id(app: str | os.PathLike[str]) -> str:
    """The speech-library set this application folder needs, from its pinned list; "" when it has none."""

    lock = Path(app) / RUNTIME_FOLDER / PYTHON_FOLDER / SPEECH_LOCK_FILE
    try:
        data = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    value = str((data or {}).get("set_id") or "").strip().casefold() if isinstance(data, dict) else ""
    return value if _SET_ID.match(value) else ""


def addons_folder(app: str | os.PathLike[str]) -> Path | None:
    """``addons_root()\\sp-<set>`` for this application folder's set, or None when it names no set."""

    set_id = speech_set_id(app)
    return addons_root() / f"sp-{set_id}" if set_id else None


def use_addons(executable: str | os.PathLike[str] | None = None, path: list[str] | None = None) -> Path | None:
    """Put our downloaded speech libraries on the import path, only when the running Python is our private one.

    Returns the folder added, or None when nothing was added: another Python, no set named, or the set not
    downloaded yet. The folder goes after the Python's own folders, so its own copy of a package wins."""

    if not is_private_python(executable):
        return None
    folder = addons_folder(app_folder(executable))
    if folder is None or not folder.is_dir():
        return None
    target = sys.path if path is None else path
    text = str(folder)
    if not any(os.path.normcase(item) == os.path.normcase(text) for item in target):
        target.append(text)
    return folder
