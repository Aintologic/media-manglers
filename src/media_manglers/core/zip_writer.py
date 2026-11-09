"""The one ZIP writer (209): every feature that builds a ZIP lists and writes through here.

Windows paths past the old 260-character limit are listed and read through the extended-length
form, whether or not long paths are turned on in Windows, so nothing under a long folder is left
out without a word. Entries are a file (``source``), a folder (``source`` that is a folder, with
optional ``exclude_suffixes``) or ready-made content (``data``, bytes or text, or a callable that
returns it), each under its name in the archive (``name``; a folder's name is its prefix).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable
import zipfile


def local_io_path(path: Path | str) -> Path:
    """The Windows extended-length form of a path, for local file input and output."""

    path = Path(path)
    if os.name != "nt":
        return path
    value = os.path.abspath(str(path))
    if value.startswith("\\\\?\\"):
        return Path(value)
    if value.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + value[2:])
    return Path("\\\\?\\" + value)


def list_files(
    root: Path | str,
    *,
    skip_hidden: bool = True,
    exclude_names: Iterable[str] = (),
    exclude_suffixes: Iterable[str] = (),
) -> list[Path]:
    """Every file under ``root``, as plain paths under it, sorted case-insensitively."""

    root = Path(root)
    io_root = local_io_path(root)
    names = set(exclude_names)
    suffixes = {suffix.lower() for suffix in exclude_suffixes}
    found: list[Path] = []
    for folder, subfolders, files in os.walk(io_root):
        relative_folder = Path(folder).relative_to(io_root)
        if skip_hidden:
            subfolders[:] = [name for name in subfolders if not name.startswith(".")]
        for name in files:
            if (skip_hidden and name.startswith(".")) or name in names or Path(name).suffix.lower() in suffixes:
                continue
            if (Path(folder) / name).is_file():
                found.append(root / relative_folder / name)
    return sorted(found, key=lambda path: path.relative_to(root).as_posix().lower())


def _archive_name(*parts: str) -> str:
    return "/".join(part.strip("/\\").replace("\\", "/") for part in parts if part and part.strip("/\\"))


def write_zip(zip_path: Path | str, entries: Iterable[dict[str, Any]], *, compresslevel: int = 6) -> dict[str, Any]:
    """Write ``entries`` to ``zip_path`` (replacing it); the files and bytes written."""

    zip_path = Path(zip_path)
    local_io_path(zip_path.parent).mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    with zipfile.ZipFile(local_io_path(zip_path), "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=compresslevel) as archive:
        for entry in entries:
            name = str(entry.get("name") or "")
            data = entry.get("data")
            if data is not None:
                payload = data() if callable(data) else data
                archive.writestr(_archive_name(name), payload)
                written.append(_archive_name(name))
                continue
            source = Path(str(entry.get("source") or ""))
            io_source = local_io_path(source)
            if io_source.is_dir():
                for path in list_files(source, skip_hidden=False, exclude_suffixes=entry.get("exclude_suffixes") or ()):
                    arcname = _archive_name(name, path.relative_to(source).as_posix())
                    archive.write(local_io_path(path), arcname)
                    written.append(arcname)
            elif io_source.is_file():
                archive.write(io_source, _archive_name(name or source.name))
                written.append(_archive_name(name or source.name))
    return {"zip_path": str(zip_path), "size_bytes": local_io_path(zip_path).stat().st_size,
            "file_count": len(written), "files": written}


def write_zip_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """CLI ``zip-write``: ``zip_path`` and ``entries`` of files and folders (the backend's ZIPs)."""

    entries = [dict(item) for item in payload.get("entries") or [] if isinstance(item, dict)]
    result = write_zip(Path(str(payload["zip_path"])), entries)
    result.pop("files", None)
    return result
