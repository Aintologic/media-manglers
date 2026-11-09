"""Where Media Manglers keeps things, the way the operating system expects (127).

- Videos and music made for the user go in the user's own Videos or Music folder, as the operating
  system reports it: on Windows the known folder (which follows a move to OneDrive or another
  drive), on macOS ~/Movies and ~/Music, on Linux the XDG user folders.
- Settings go in the per-user application-data folder; logs and caches in the local one.
- Short-lived scratch files go in the operating system's temp folder and are removed afterwards.
- Nothing the user keeps may be written into a temp folder: the system, or the user, clears those
  without warning. ``temporary_folder_problem`` says so in plain words.

The ``MEDIA_MANGLERS_VIDEOS_FOLDER`` and ``MEDIA_MANGLERS_MUSIC_FOLDER`` overrides exist so the test
suite never touches a real user's folders; ``MEDIA_MANGLERS_ALLOW_TEMP_OUTPUT=1`` lets automated
tests write their throw-away output into a temp folder.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

APP_FOLDER = "MediaManglers"
VIDEOS_OVERRIDE_ENV = "MEDIA_MANGLERS_VIDEOS_FOLDER"
MUSIC_OVERRIDE_ENV = "MEDIA_MANGLERS_MUSIC_FOLDER"
ALLOW_TEMP_OUTPUT_ENV = "MEDIA_MANGLERS_ALLOW_TEMP_OUTPUT"

# Windows known-folder IDs (FOLDERID_Videos, FOLDERID_Music).
_KNOWN_FOLDERS = {
    "videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
    "music": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
}
_XDG_NAMES = {"videos": ("XDG_VIDEOS_DIR", "Videos"), "music": ("XDG_MUSIC_DIR", "Music")}
_MAC_NAMES = {"videos": "Movies", "music": "Music"}
_TEMP_NAMES = {"temp", "tmp"}


def _windows_known_folder(kind: str) -> Path | None:
    try:
        import ctypes  # noqa: PLC0415
        from ctypes import wintypes  # noqa: PLC0415
        import uuid  # noqa: PLC0415

        class _GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                        ("Data4", ctypes.c_ubyte * 8)]

        raw = uuid.UUID(_KNOWN_FOLDERS[kind]).bytes_le
        guid = _GUID.from_buffer_copy(raw)
        out = ctypes.c_wchar_p()
        result = ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(out))
        try:
            if result == 0 and out.value:
                return Path(out.value)
        finally:
            ctypes.windll.ole32.CoTaskMemFree(out)
    except Exception:  # noqa: BLE001 - fall back to the profile folder below
        return None
    return None


def _xdg_user_folder(kind: str, home: Path) -> Path:
    key, fallback = _XDG_NAMES[kind]
    value = os.environ.get(key, "")
    if value and os.path.isabs(value):
        return Path(value)
    config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    try:
        for line in (config / "user-dirs.dirs").read_text(encoding="utf-8").splitlines():
            name, _, raw = line.partition("=")
            if name.strip() == key:
                text = raw.strip().strip('"').replace("$HOME", str(home))
                if os.path.isabs(text):
                    return Path(text)
    except OSError:
        pass
    return home / fallback


def _user_folder(kind: str, override_env: str) -> Path:
    override = os.environ.get(override_env, "").strip()
    if override:
        return Path(override)
    home = Path.home()
    if sys.platform == "win32":
        found = _windows_known_folder(kind)
        if found:
            return found
        return Path(os.environ.get("USERPROFILE") or home) / _XDG_NAMES[kind][1]
    if sys.platform == "darwin":
        return home / _MAC_NAMES[kind]
    return _xdg_user_folder(kind, home)


def videos_folder() -> Path:
    """The user's own Videos folder (Movies on macOS)."""

    return _user_folder("videos", VIDEOS_OVERRIDE_ENV)


def music_folder() -> Path:
    """The user's own Music folder."""

    return _user_folder("music", MUSIC_OVERRIDE_ENV)


def settings_root() -> Path:
    """The per-user folder for settings, which can roam with the user's account."""

    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def local_data_root() -> Path:
    """The per-user folder for logs and caches that stay on this computer."""

    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")


def temp_root() -> Path:
    """The operating system's temp folder, for short-lived scratch files."""

    return Path(tempfile.gettempdir())


def _norm(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path))).rstrip("\\/")


def is_temporary_folder(path: str | os.PathLike[str]) -> bool:
    """True when ``path`` is the system temp folder, inside it, or inside a folder named Temp or Tmp."""

    text = str(path or "").strip()
    if not text:
        return False
    full = _norm(Path(os.path.expandvars(os.path.expanduser(text))))
    temp = _norm(temp_root())
    if full == temp or full.startswith(temp + os.sep):
        return True
    return any(part.lower() in _TEMP_NAMES for part in Path(full).parts)


def check_folders_from_request(payload: dict) -> dict:
    """211: the backend's check, through this one rule. A temp output folder is refused; a temp
    input folder only warned about, since files kept there can still be read."""

    allowed = os.environ.get(ALLOW_TEMP_OUTPUT_ENV, "").strip() == "1"
    input_folder = str(payload.get("input_folder") or "").strip()
    output_folder = str(payload.get("output_folder") or "").strip()
    if payload.get("recordings_folders"):
        set_recordings_folders([str(item) for item in payload.get("recordings_folders") or []])
    input_warning = ""
    if input_folder and not allowed and is_temporary_folder(input_folder):
        input_warning = (f"The input folder {input_folder} is a temporary folder. Files kept there can be "
                         "cleared without warning.")
    return {"output_problem": temporary_folder_problem(output_folder) if output_folder else "",
            "input_warning": input_warning}


def temporary_folder_problem(path: str | os.PathLike[str], what: str = "output folder") -> str:
    """The one output-folder rule: a plain-words refusal when ``path`` is a temp folder or on the
    recordings drive (220), or an empty string when it is fine."""

    guard = recordings_drive_problem(path, what)
    if guard:
        return guard
    if os.environ.get(ALLOW_TEMP_OUTPUT_ENV, "").strip() == "1":
        return ""
    if not is_temporary_folder(path):
        return ""
    return (f"The {what} {path} is a temporary folder. The computer, or a clean-up tool, can empty it "
            f"without warning and take your results with it. Choose a folder you keep, for example "
            f"{videos_folder() / 'Media Mangler'}.")


# 220: the drive that holds the operator's recordings is read-only to the app. The watched
# recordings folders (the raw bin's and the Inbox's one setting) are handed to every process the app
# starts in this variable, so the backend applies the same rule. Folders are separated by os.pathsep.
RECORDINGS_FOLDERS_ENV = "MEDIA_MANGLERS_RECORDINGS_FOLDERS"


def recordings_folders() -> list[str]:
    """The watched recordings folders. The Workbench always says which (possibly none); a backend run
    started on its own, outside the app, reads them from the Workbench's saved settings instead, so the
    rule holds there too (220)."""

    if RECORDINGS_FOLDERS_ENV in os.environ:
        raw = os.environ.get(RECORDINGS_FOLDERS_ENV, "")
        return [part.strip() for part in raw.split(os.pathsep) if part.strip()]
    return _saved_recordings_folders()


def workbench_settings_file() -> Path:
    """The Workbench's saved settings file: under MEDIA_MANGLERS_WORKBENCH_APPDATA when that is set (the
    tests' and the build's own folder), otherwise in the per-user settings folder. Read only by core
    (220, 226)."""

    override = os.environ.get("MEDIA_MANGLERS_WORKBENCH_APPDATA", "").strip()
    base = Path(override) if override else settings_root()
    return base / APP_FOLDER / "workbench" / "settings.json"


def _saved_recordings_folders() -> list[str]:
    try:
        import json  # noqa: PLC0415

        saved = json.loads(workbench_settings_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    value = str(((saved or {}).get("settings") or {}).get("review_source_folders") or "")
    return [part.strip() for part in value.replace("\n", ";").split(";") if part.strip()]


def set_recordings_folders(folders: list[str] | tuple[str, ...] | str) -> None:
    """Tell this process, and everything it starts, which folders hold the recordings."""

    if isinstance(folders, str):
        folders = [part for part in folders.replace("\n", ";").split(";")]
    os.environ[RECORDINGS_FOLDERS_ENV] = os.pathsep.join(str(part).strip() for part in folders if str(part).strip())


def _existing_ancestor(path: Path) -> Path | None:
    current = path
    while True:
        if current.exists():
            return current
        if current.parent == current:
            return None
        current = current.parent


def _volume(path: Path) -> int | None:
    """The volume a path is on, by the volume itself (st_dev is the volume serial number on Windows),
    so a junction, mount point or subst drive letter does not get round the rule."""

    found = _existing_ancestor(path)
    if found is None:
        return None
    try:
        return os.stat(found).st_dev
    except OSError:
        return None


def _system_volume() -> int | None:
    root = os.environ.get("SystemDrive", "C:") + os.sep if sys.platform == "win32" else os.sep
    return _volume(Path(root))


def recordings_drive_problem(path: str | os.PathLike[str], what: str = "output folder",
                             folders: list[str] | None = None) -> str:
    """A refusal when ``path`` is inside a watched recordings folder, or anywhere on a drive that holds
    one (unless that drive is the system drive, where only the folders themselves are refused)."""

    text = str(path or "").strip()
    watched = recordings_folders() if folders is None else [str(item) for item in folders if str(item).strip()]
    if not text or not watched:
        return ""
    target = Path(os.path.expandvars(os.path.expanduser(text)))
    try:
        target_real = _norm(Path(os.path.realpath(target)))
    except OSError:
        target_real = _norm(target)
    target_volume = _volume(target)
    system = _system_volume()
    for folder in watched:
        source = Path(os.path.expandvars(os.path.expanduser(folder)))
        try:
            source_real = _norm(Path(os.path.realpath(source)))
        except OSError:
            source_real = _norm(source)
        inside = target_real == source_real or target_real.startswith(source_real + os.sep)
        source_volume = _volume(source)
        same_drive = target_volume is not None and target_volume == source_volume and source_volume != system
        if inside or same_drive:
            return (f"The {what} {text} is on the drive that holds your recordings ({folder}). That drive is "
                    "read-only to Media Manglers: nothing is ever written there. Choose a folder on another drive.")
    return ""
