"""The shared first-launch setup: speech recognition for Media Manglers' own Python (installer plan, Stage 4).

Both editions, the portable ZIP and the installer, run this same setup, once, after the one question the app asks
at first launch. It needs no pip and changes nothing in any other Python:

1. every speech library pinned in ``runtime\\python\\speech-lock.json`` (PyTorch for the processor, numpy and their
   partners) is downloaded through the one shared downloader (``downloads``: a ``.partial`` file, its SHA-256
   checked, then renamed; every certificate checked through Windows) into ``addons_root()\\downloads``. A file a
   cut-short setup already downloaded and that still matches its checksum is used, not fetched again;
2. each one is unpacked by this module, not by pip, into ``addons_root()\\sp-<set>.tmp``. Every file is checked
   against its library's own list of checksums (the wheel's RECORD), and nothing may land outside the folder;
3. everything is compiled to bytecode once, here, so Python never writes beside the libraries later;
4. the finished folder is renamed into place as ``addons_root()\\sp-<set>`` (Stage 2's new file step), so a set
   that exists is always complete; older sets and the downloaded files are removed the same way;
5. ``base.en``, which every review's voice detection uses, comes through the Stage 3 approval path
   (``whisper_models.download_model``): a valid copy already in the Whisper cache is used as it is.

When a Python of the operator's is kept under one of the two exceptions, it has its own speech libraries, so only
step 5 runs: the libraries are skipped and only the models it lacks are fetched.
"""

from __future__ import annotations

import base64
import compileall
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import fnmatch
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import py_compile
import sys
import sysconfig
import time
from typing import Any, Callable
import zipfile

from . import downloads, private_runtime, safe_write, whisper_models
from .user_folders import addons_root

SET_PREFIX = "sp-"
TEMP_SUFFIX = ".tmp"
DOWNLOADS_FOLDER = "downloads"
MARKER_FILE = "speech-set.json"
VOICE_MODEL = "base.en"
# base.en's size as Whisper publishes it, for the question's total before anything is downloaded.
VOICE_MODEL_BYTES = 145_261_783
# Windows' path limit for a file, when the PC has not turned long paths on.
WINDOWS_PATH_LIMIT = 259
_RECORD_SIGNATURES = (".dist-info/RECORD", ".dist-info/RECORD.jws", ".dist-info/RECORD.p7s")


class SetupRefused(RuntimeError):
    """The setup cannot run here, for a reason waiting or trying again does not change. Nothing was changed."""


# The pinned list ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LockedFile:
    name: str
    version: str
    file: str
    url: str
    sha256: str
    size: int
    licence: str = ""


@dataclass(frozen=True, slots=True)
class SpeechLock:
    set_id: str
    python: str
    platform: str
    files: tuple[LockedFile, ...]
    skip_on_unpack: tuple[str, ...]

    @property
    def total_bytes(self) -> int:
        return sum(item.size for item in self.files)


def set_id_for(files: list[tuple[str, str]], skip_on_unpack: list[str], python: str, platform: str) -> str:
    """The set's name: the first eight hex digits of a checksum over everything that decides what is unpacked, so a
    changed pin always makes a new set beside the old one instead of changing a set in place."""

    text = json.dumps({"files": sorted([str(name), str(sha).casefold()] for name, sha in files),
                       "skip": sorted(skip_on_unpack), "python": python, "platform": platform}, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def lock_path(app: str | os.PathLike[str]) -> Path:
    return Path(app) / private_runtime.RUNTIME_FOLDER / private_runtime.PYTHON_FOLDER / private_runtime.SPEECH_LOCK_FILE


def read_lock(app: str | os.PathLike[str]) -> SpeechLock | None:
    """The speech-library list this application folder pins; None when it has none or it cannot be read."""

    try:
        data = json.loads(lock_path(app).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        files = tuple(LockedFile(str(item["name"]), str(item.get("version") or ""), str(item["file"]),
                                 str(item["url"]), str(item["sha256"]).casefold(), int(item.get("size") or 0),
                                 str(item.get("licence") or ""))
                      for item in data.get("files") or [])
    except (KeyError, TypeError, ValueError):
        return None
    set_id = private_runtime.speech_set_id(app)
    if not set_id or not files:
        return None
    return SpeechLock(set_id, str(data.get("python") or ""), str(data.get("platform") or ""), files,
                      tuple(str(item) for item in data.get("skip_on_unpack") or []))


def set_folder(set_id: str) -> Path:
    return addons_root() / f"{SET_PREFIX}{set_id}"


def libraries_ready(app: str | os.PathLike[str]) -> bool:
    """Whether this application folder's speech libraries are set up. A set folder exists only once it is complete:
    it gets its name in one rename, after everything in it was checked and compiled."""

    folder = private_runtime.addons_folder(app)
    return bool(folder is not None and (folder / MARKER_FILE).is_file())


# Progress -----------------------------------------------------------------------------------------------------


class Reporter:
    """Where the setup says how far it is: a small JSON file the Workbench's job banner reads, about twice a
    second, plus a list of what happened for the result."""

    def __init__(self, progress_file: str = "", callback: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.progress_file = progress_file
        self.callback = callback
        self._last = 0.0

    def __call__(self, stage: str, text: str, done: int = 0, total: int = 0, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last < 0.5 and not (total and done >= total):
            return
        self._last = now
        percent = int(100 * done / total) if total else None
        state = {"stage": stage, "text": text, "done": int(done), "total": int(total), "percent": percent}
        if self.callback is not None:
            self.callback(state)
        if self.progress_file:
            try:
                safe_write.write_json(self.progress_file, state)
            except OSError:
                pass


def _megabytes(count: int) -> str:
    return f"{count / 1_000_000:,.0f} MB"


# Unpacking, with no pip ----------------------------------------------------------------------------------------


def _member_target(name: str, skip: tuple[str, ...]) -> str | None:
    """Where a wheel member goes inside the set, as a relative path with forward slashes; None to leave it out.

    Only the importable parts are kept: the package folders, their ``.dist-info``, and a ``.data`` folder's
    ``purelib`` or ``platlib``. Scripts, headers and data files meant for other places are left out, as is anything
    the lock's ``skip_on_unpack`` names (PyTorch's own ``protoc.exe``)."""

    path = PurePosixPath(name)
    if name.endswith("/") or not path.parts:
        return None
    if path.is_absolute() or any(part in {"", ".", ".."} or ":" in part or "\\" in part for part in path.parts):
        raise SetupRefused(f"A speech library holds a file with an unsafe name ({name}), so nothing was set up.")
    parts = list(path.parts)
    if parts[0].endswith(".data"):
        if len(parts) > 2 and parts[1] in {"purelib", "platlib"}:
            parts = parts[2:]
        else:
            return None
    relative = "/".join(parts)
    if any(fnmatch.fnmatch(relative, pattern) for pattern in skip):
        return None
    return relative


def _record(archive: zipfile.ZipFile, wheel: str) -> dict[str, str]:
    # The wheel's own list is in its top-level .dist-info folder; a library it carries inside may have its own.
    names = [name for name in archive.namelist()
             if name.endswith(".dist-info/RECORD") and name.count("/") == 1]
    if len(names) != 1:
        raise SetupRefused(f"{wheel} has no list of checksums (RECORD), so it was not unpacked. Nothing was set up.")
    expected: dict[str, str] = {}
    for row in csv.reader(io.StringIO(archive.read(names[0]).decode("utf-8"))):
        if len(row) >= 2 and row[1].startswith("sha256="):
            expected[row[0]] = row[1][len("sha256="):]
    return expected


def _long_path(path: Path) -> str:
    """``path`` in the form Windows accepts beyond its path limit (a network path as ``\\\\?\\UNC\\server\\...``)."""

    text = os.path.abspath(str(path))
    if os.name != "nt" or text.startswith("\\\\?\\"):
        return text
    if text.startswith("\\\\"):
        return "\\\\?\\UNC\\" + text[2:]
    return "\\\\?\\" + text


def _final_lengths(relative: str, final: Path) -> list[int]:
    """The lengths of the paths a member ends up at: its own, and for Python source the bytecode beside it."""

    lengths = [len(str(final)) + 1 + len(relative)]
    if relative.endswith(".py"):
        folder, _sep, stem = relative.rpartition("/")
        tag = sys.implementation.cache_tag or "cpython"
        pyc = f"{folder + '/' if folder else ''}__pycache__/{stem[:-3]}.{tag}.pyc"
        lengths.append(len(str(final)) + 1 + len(pyc))
    return lengths


def longest_path(lock: SpeechLock, wheels: Path, final: Path) -> int:
    """The longest path, in characters, any unpacked or compiled file will have once the set is in place."""

    longest = 0
    for item in lock.files:
        with zipfile.ZipFile(wheels / item.file) as archive:
            for name in archive.namelist():
                relative = _member_target(name, lock.skip_on_unpack)
                if relative is not None:
                    longest = max(longest, *_final_lengths(relative, final))
    return longest


def long_paths_enabled() -> bool:
    """Whether Windows' long-path support is turned on for this PC."""

    if os.name != "nt":
        return True
    try:
        import winreg  # noqa: PLC0415

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            return int(winreg.QueryValueEx(key, "LongPathsEnabled")[0]) == 1
    except OSError:
        return False


def unpack_wheel(wheel: Path, folder: Path, skip: tuple[str, ...]) -> list[str]:
    """Unpack ``wheel`` into ``folder``, checking every file against the wheel's own RECORD. Returns what it wrote,
    as relative paths. A file that does not match stops the setup; nothing outside ``folder`` is ever written."""

    written: list[str] = []
    with zipfile.ZipFile(wheel) as archive:
        expected = _record(archive, wheel.name)
        for info in archive.infolist():
            name = info.filename
            relative = _member_target(name, skip)
            if relative is None:
                continue
            if name.endswith(_RECORD_SIGNATURES):
                pass
            elif name not in expected:
                raise SetupRefused(f"{wheel.name} holds {name}, which its own list of checksums does not name, so it "
                                   f"was not unpacked. Nothing was set up.")
            target = folder.joinpath(*relative.split("/"))
            os.makedirs(_long_path(target.parent), exist_ok=True)
            digest = hashlib.sha256()
            with archive.open(info) as source, open(_long_path(target), "wb") as handle:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
                    handle.write(chunk)
            if name in expected:
                found = base64.urlsafe_b64encode(digest.digest()).rstrip(b"=").decode("ascii")
                if found != expected[name]:
                    raise SetupRefused(f"{name} in {wheel.name} does not match its library's own checksum, so "
                                       f"nothing was set up. Try again; the file is downloaded afresh.")
            written.append(relative)
    return written


def compile_folder(folder: Path, *, workers: int = 0) -> bool:
    """Compile every Python file in ``folder`` once, now, so Python never writes bytecode there later."""

    return bool(compileall.compile_dir(str(folder), quiet=2, workers=workers,
                                       invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH))


# The setup ----------------------------------------------------------------------------------------------------


def _check_python(lock: SpeechLock) -> None:
    if not private_runtime.is_private_python():
        raise SetupRefused("The speech libraries are set up only by Media Manglers' own Python, for itself. "
                           "Nothing was changed.")
    want = lock.python.replace("cp", "")
    have = f"{sys.version_info.major}{sys.version_info.minor}"
    platform = sysconfig.get_platform().replace("-", "_")
    if want and want != have or lock.platform and lock.platform != platform:
        raise SetupRefused(f"These speech libraries are for Python {lock.python} on {lock.platform}, not this Python "
                           f"({have}, {platform}). Nothing was changed.")


def _remove_leftovers(root: Path, final: Path, notes: list[str]) -> None:
    """A folder a cut-short setup left under its temporary name is removed first; it is never used."""

    temporary = final.with_name(final.name + TEMP_SUFFIX)
    if os.path.lexists(temporary):
        safe_write.remove_disposable_tree(temporary, within=root, budget=safe_write.StepBudget())
        notes.append(f"Removed {temporary.name}, left by a setup that was cut short.")
    if os.path.lexists(final) and not (final / MARKER_FILE).is_file():
        safe_write.remove_disposable_tree(final, within=root, budget=safe_write.StepBudget())
        notes.append(f"Removed {final.name}, which was not complete.")


def _download_all(lock: SpeechLock, wheels: Path, report: Reporter, opener: downloads.Opener) -> dict[str, Any]:
    started = time.monotonic()
    missing = [item for item in lock.files if not downloads.has_checked_copy(wheels / item.file, item.sha256)]
    total = sum(item.size for item in missing)
    done_before = 0
    for item in missing:
        def progress(done: int, _total: int, base: int = done_before) -> None:
            report("download", f"Downloading the speech libraries: {_megabytes(base + done)} of {_megabytes(total)}",
                   base + done, total)

        # The downloads folder is the setup's own: a file there that is not the pinned one is replaced.
        downloads.download_file(item.url, wheels / item.file, item.sha256, size=item.size, replace=True,
                                name=f"The speech library {item.name} {item.version}".strip(), opener=opener,
                                progress=progress)
        done_before += item.size
    report("download", f"Downloaded the speech libraries ({_megabytes(total)})", total, total, force=True)
    return {"files": len(lock.files), "downloaded": len(missing), "reused": len(lock.files) - len(missing),
            "bytes": total, "seconds": round(time.monotonic() - started, 2)}


def _remove_downloads(root: Path, notes: list[str]) -> None:
    wheels = root / DOWNLOADS_FOLDER
    if not os.path.lexists(wheels):
        return
    try:
        safe_write.remove_disposable_tree(wheels, within=root, budget=safe_write.StepBudget())
    except OSError as exc:
        notes.append(f"The downloaded files were not removed yet; the next setup removes them. ({exc})")


def _build_set(lock: SpeechLock, wheels: Path, final: Path, report: Reporter, result: dict[str, Any],
               compile_workers: int) -> None:
    """Steps 2 to 4 inside the temporary folder; only a complete, compiled set gets its final name."""

    started = time.monotonic()
    temporary = final.with_name(final.name + TEMP_SUFFIX)
    temporary.mkdir()
    unpacked = 0
    for index, item in enumerate(lock.files, start=1):
        report("unpack", f"Unpacking the speech libraries: {item.name} ({index} of {len(lock.files)})",
               index - 1, len(lock.files), force=True)
        unpacked += len(unpack_wheel(wheels / item.file, temporary, lock.skip_on_unpack))
    result["unpack"] = {"files": unpacked, "seconds": round(time.monotonic() - started, 2)}

    started = time.monotonic()
    report("compile", "Preparing the speech libraries (compiling them once)", force=True)
    result["compile"] = {"all_compiled": compile_folder(temporary, workers=compile_workers),
                         "seconds": round(time.monotonic() - started, 2)}

    marker = {"set_id": lock.set_id, "python": lock.python, "platform": lock.platform,
              "files": [{"name": item.name, "version": item.version, "sha256": item.sha256} for item in lock.files],
              "unpacked_files": unpacked, "certificates": downloads.verification(),
              "set_up_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    safe_write.write_json(temporary / MARKER_FILE, marker)
    report("finish", "Putting the speech libraries in place", force=True)
    started = time.monotonic()
    safe_write.rename_into_place(temporary, final, budget=safe_write.StepBudget())
    result["rename_seconds"] = round(time.monotonic() - started, 2)


def set_up_libraries(app: str | os.PathLike[str], *, opener: downloads.Opener = downloads.open_url,
                     report: Reporter | None = None, check_python: bool = True, repair: bool = False,
                     compile_workers: int = 0) -> dict[str, Any]:
    """Steps 1 to 4: download, check, unpack, compile and rename this application folder's speech libraries into
    ``addons_root()\\sp-<set>``, then remove the other sets and the downloaded files. ``repair`` sets up again a
    set that is there but no longer loads (part of it was removed or quarantined)."""

    report = report or Reporter()
    lock = read_lock(app)
    if lock is None:
        raise SetupRefused("This copy of Media Manglers names no speech libraries to set up "
                           f"({lock_path(app)}). Nothing was changed.")
    if check_python:
        _check_python(lock)
    root = addons_root()
    final = set_folder(lock.set_id)
    result: dict[str, Any] = {"set_id": lock.set_id, "folder": str(final), "notes": []}
    if (final / MARKER_FILE).is_file():
        if not repair:
            result["already_set_up"] = True
            result["older_sets_removed"] = remove_older_sets(lock.set_id, result["notes"])
            _remove_downloads(root, result["notes"])
            return result
        # Set aside first (a trash name, then deleted), so a half-removed set never looks like one.
        safe_write.remove_disposable_tree(final, within=root, budget=safe_write.StepBudget())
        result["notes"].append(f"Removed {final.name}, which no longer loaded, to set it up again.")
    root.mkdir(parents=True, exist_ok=True)
    _remove_leftovers(root, final, result["notes"])
    wheels = root / DOWNLOADS_FOLDER
    result["download"] = _download_all(lock, wheels, report, opener)

    longest = longest_path(lock, wheels, final)
    result["longest_path"] = longest
    if longest > WINDOWS_PATH_LIMIT and not long_paths_enabled():
        raise SetupRefused(
            f"The speech libraries would need paths of {longest} characters in {root}, longer than Windows allows "
            f"({WINDOWS_PATH_LIMIT}) on this PC. Nothing was set up; the downloaded files are kept for the next try.")
    try:
        _build_set(lock, wheels, final, report, result, compile_workers)
    except BaseException as exc:
        # The half-built set is removed at once (a disk filled by it stays full otherwise); the downloads that match
        # their pins are kept for the next try.
        temporary = final.with_name(final.name + TEMP_SUFFIX)
        try:
            if os.path.lexists(temporary):
                safe_write.remove_disposable_tree(temporary, within=root, budget=safe_write.StepBudget())
        except OSError:
            pass
        if isinstance(exc, OSError) and downloads.is_disk_full(exc):
            raise SetupRefused(
                f"The disk holding {root} is full, so the speech libraries were not set up (they need about "
                f"{5.5 * lock.total_bytes / 1_000_000_000:.1f} GB free: the downloads and the unpacked libraries). Nothing was "
                "set up; free some space, then choose Set up again.") from exc
        raise
    result["older_sets_removed"] = remove_older_sets(lock.set_id, result["notes"])
    _remove_downloads(root, result["notes"])
    return result


def remove_older_sets(keep: str, notes: list[str]) -> list[str]:
    """Remove every other speech-library set (installer plan 3.1: each version has its own set; a copy whose set was
    removed simply downloads it again), and what a cut-short setup left of one. One that another program still holds
    stays, is named in ``notes``, and is removed by the next setup; it never fails this one."""

    root = addons_root()
    removed: list[str] = []
    try:
        found = [item for item in root.iterdir() if item.name.startswith(SET_PREFIX) and item.is_dir()]
    except OSError:
        return removed
    for folder in found:
        if folder.name == f"{SET_PREFIX}{keep}":
            continue
        try:
            safe_write.remove_disposable_tree(folder, within=root, budget=safe_write.StepBudget())
            removed.append(folder.name)
        except OSError as exc:
            notes.append(f"An older set of speech libraries, {folder.name}, was not removed yet: {exc}")
    return removed


def set_up_models(models: list[str], *, opener: downloads.Opener = downloads.open_url,
                  report: Reporter | None = None) -> list[dict[str, Any]]:
    """Step 5: each model through the Stage 3 approval path; a valid copy in the Whisper cache is used as it is."""

    report = report or Reporter()
    table = whisper_models.model_table()
    results: list[dict[str, Any]] = []
    for name in models:
        def progress(done: int, total: int, name: str = name) -> None:
            amount = f"{_megabytes(done)} of {_megabytes(total)}" if total else _megabytes(done)
            report("model", f"Downloading the Whisper model {name}: {amount}", done, total)

        before = whisper_models.model_state(name, table=table)
        found = whisper_models.download_model(name, table=table, opener=opener, progress=progress)
        results.append({**found.to_dict(), "reused": before.valid})
    return results


def run_setup(*, app: str | os.PathLike[str] | None = None, libraries: bool = True, repair: bool = False,
              models: list[str] | tuple[str, ...] = (VOICE_MODEL,), opener: downloads.Opener = downloads.open_url,
              report: Reporter | None = None, check_python: bool = True) -> dict[str, Any]:
    """The whole first-launch setup, as one job. ``libraries`` is False when a Python of the operator's is kept: it
    has its own, so only the models it lacks are fetched. ``repair`` sets up again a set that no longer loads."""

    started = time.monotonic()
    report = report or Reporter()
    app = Path(app) if app is not None else private_runtime.app_folder()
    result: dict[str, Any] = {"app_folder": str(app), "addons_root": str(addons_root()),
                              "certificates": downloads.verification()}
    if libraries:
        result["libraries"] = set_up_libraries(app, opener=opener, report=report, check_python=check_python,
                                               repair=repair)
    result["models"] = set_up_models([str(name) for name in models if str(name).strip()], opener=opener,
                                     report=report)
    result["seconds"] = round(time.monotonic() - started, 2)
    report("done", "Speech recognition is set up", 1, 1, force=True)
    return result


def setup_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """``speech-setup``: the first-launch setup the operator agreed to (the Workbench runs it, in our own Python)."""

    models = payload.get("models")
    return run_setup(libraries=bool(payload.get("libraries", True)), repair=bool(payload.get("repair")),
                     models=[str(name) for name in (models if models is not None else [VOICE_MODEL])],
                     report=Reporter(str(payload.get("progress_file") or "")))
