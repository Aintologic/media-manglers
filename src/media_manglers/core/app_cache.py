"""The app's cache folder (220): data that can be rebuilt, kept in one place with a size cap.

Waveforms and levels per second (the raw bin's, and the player's from ``track_levels``) go here.
Nothing here is the only copy of anything: tags, decisions, guesses and idle times live in the raw
bin library's database, so clearing the cache never loses them. The folder is one main setting
("Cache folder"); left blank it is the app's local data folder. It is never on the recordings drive (the one output-folder rule refuses that).

When the cache grows past its cap, the items used longest ago are removed first. Reading an item
counts as using it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import time
from typing import Any

from .user_folders import APP_FOLDER, local_data_root

DEFAULT_CAP_BYTES = 10 * 1024 ** 3
# The test suite points the default cache at a scratch folder with this.
CACHE_ROOT_ENV = "MEDIA_MANGLERS_CACHE_ROOT"
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def default_cache_root() -> Path:
    override = os.environ.get(CACHE_ROOT_ENV, "").strip()
    return Path(override) if override else local_data_root() / APP_FOLDER / "Workbench" / "cache"


# A folder the operator chooses gets a subfolder of the app's own, so the size cap and Clear cache only
# ever touch files the app made, never anything else that is in the chosen folder (220).
CHOSEN_FOLDER_SUBFOLDER = "Media Manglers cache"


def cache_root(setting: str | os.PathLike[str] | None = None) -> Path:
    chosen = str(setting or "").strip()
    if not chosen:
        return default_cache_root()
    return Path(os.path.expandvars(os.path.expanduser(chosen))) / CHOSEN_FOLDER_SUBFOLDER


def _item(root: Path, kind: str, key: str, suffix: str) -> Path:
    return root / _SAFE.sub("-", kind) / f"{_SAFE.sub('-', key)}{suffix}"


def item_path(root: Path, kind: str, key: str, suffix: str = ".json") -> Path:
    """Where an item lives; the folder is made when the item is written."""

    return _item(Path(root), kind, key, suffix)


def put_json(root: Path, kind: str, key: str, data: Any) -> Path:
    path = item_path(root, kind, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, path)
    return path


def get_json(root: Path, kind: str, key: str) -> Any | None:
    path = item_path(root, kind, key)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    touch(path)
    return data


def touch(path: Path) -> None:
    """Count a read as a use, so the size cap removes what was used longest ago."""

    try:
        now = time.time()
        os.utime(path, (now, now))
    except OSError:
        pass


def _files(root: Path) -> list[Path]:
    if not Path(root).is_dir():
        return []
    return [path for path in Path(root).rglob("*") if path.is_file()]


def size_bytes(root: Path) -> int:
    total = 0
    for path in _files(root):
        try:
            total += path.stat().st_size
        except OSError:
            pass
    return total


def enforce_cap(root: Path, cap_bytes: int = DEFAULT_CAP_BYTES) -> int:
    """Remove the items used longest ago until the cache fits its cap. Returns the bytes freed."""

    entries = []
    for path in _files(root):
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append((stat.st_mtime, stat.st_size, path))
    total = sum(size for _when, size, _path in entries)
    freed = 0
    for _when, size, path in sorted(entries):
        if total - freed <= max(0, int(cap_bytes)):
            break
        try:
            path.unlink()
            freed += size
        except OSError:
            pass
    return freed


def clear(root: Path) -> int:
    """Empty the cache folder. Returns the bytes freed. Only the cache's own folder is touched."""

    root = Path(root)
    freed = size_bytes(root)
    if root.is_dir():
        for child in root.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                try:
                    child.unlink()
                except OSError:
                    pass
    return freed - size_bytes(root)
