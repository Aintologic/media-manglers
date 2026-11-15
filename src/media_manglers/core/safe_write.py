"""One safe way to replace, move or remove a file or folder (242, 224): a crash, a full disk or another
program holding the file leaves the old file or the whole new one, never half of it, and never loses data.

The app had sixteen copies of the replace, each with some of the care below. This one has all of it. Wave A uses
it for the files it rewrites (``settings.json``, the profiles, the records' receipts), and since Wave B1
(224) Review Media Inbox's seven copies hand their replace to it. Since Wave B2a the Inbox's folder moves,
renames and clean-ups use it too (``move``, ``remove``, ``remove_disposable_tree``, ``replace_file``):

- the new text goes into a short, unique name beside the target, so a long target path stays within
  Windows' path limit while the temporary file exists (73), and two writers never share a name;
- it is flushed to the disk before the rename (183: a rename alone left a damaged file after a system
  crash, because the data was still in the write cache);
- antivirus scanners, the search indexer and Explorer's thumbnails open a file the app has just written for a
  moment, and Windows refuses to rename or delete it (or the folder holding it) until they let go. Only those
  refusals are waited for, in one shared loop: a sharing or lock violation, or "access denied" while the
  file is still there (a folder whose file is open gets that). Every other error fails at once. The wait is
  bounded: under a second for the app's own small files (``SHORT_WAIT_SECONDS``), ten seconds for the Inbox's
  steps, which run in a background helper and never freeze the window (``INBOX_WAIT_SECONDS``);
- the app never waits for itself: at the first refusal it asks Windows' Restart Manager who holds the file,
  and when that is the app (this process, the Workbench that started it, or one of their children, each step
  checked by its start time) it stops at once, because waiting cannot help;
- when Windows still refuses at the deadline, the error says so in plain words (``FileInUse``), naming the
  program that holds the file when Windows can say which;
- the temporary file is always removed.

It also makes the one checked copy of a database (``checked_copy``, 224 Wave B2a): a backup the app relies on
gets its real name only after it passed SQLite's damage check and holds every table's rows.

Installer plan, Stage 2: every NEW file step (a download put in place, the speech libraries unpacked into a
temporary folder and renamed into place, older speech-library sets removed, the add-ons removed, data removed at
uninstall) passes a ``StepBudget`` and follows stricter rules. The wait is measured by the clock: at most ten
seconds per file, counted from its first refusal, and thirty seconds for the whole step. Every file of a folder is
asked about, not only the first 512. Asking Windows takes a few milliseconds per file (about a minute for a
speech-library set), so the question runs beside the step, in parts, and the step keeps trying while Windows answers;
it never waits past its limits for the answer, and it is always tried once more at the deadline (Wave I-A review,
H4). The question is asked again at every refusal once the last one is answered, so a hold by the app itself stops
the step at once even when it begins later. ``FileInUse`` carries the holders as a list (``Holder``), and the
message names the file really held and a program, a Windows service, or a Media Manglers that is still running.
A read-only file (the source or the file being replaced), or one the app itself holds, stops at once.

No message ever advises closing, stopping, excluding or turning off the program that holds a file: Windows reports
some virus scanners as ordinary programs, so a held file's message only names the program and says to wait a moment
and try again (H3). The app's older file steps keep their own waits until the next wave, with the same words.
"""

from __future__ import annotations

from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import threading
import time
from typing import Any, Callable, Iterator, TypeVar
from urllib.parse import quote
import uuid

T = TypeVar("T")

SHORT_WAIT_SECONDS = 0.75
INBOX_WAIT_SECONDS = 10.0
# The pauses between tries: quick at first, then once a second until the wait is used up.
PAUSE_STEPS = (0.05, 0.1, 0.2, 0.4, 0.8)
LATER_PAUSE_SECONDS = 1.0
# The Workbench writes "<process number>:<start time>" here when it starts, so the host, the helpers and FFmpeg it
# starts know which process is the app.
APP_PROCESS_VARIABLE = "MEDIA_MANGLERS_APP_PROCESS"
TRASH_PREFIX = ".mm-trash-"
# Windows' own numbers: access denied, sharing violation, lock violation; ReplaceFileW's "could not remove the
# file to be replaced" and "could not move the replacement".
_ACCESS_DENIED, _SHARING_VIOLATION, _LOCK_VIOLATION = 5, 32, 33
_UNABLE_TO_REMOVE_REPLACED, _UNABLE_TO_MOVE_REPLACEMENT, _UNABLE_TO_MOVE_REPLACEMENT_2 = 1175, 1176, 1177
# "The directory is not empty": what removing a folder answers while a file in it waits to be deleted, because a
# virus scan opened it allowing deletion and has not let go yet.
_DIRECTORY_NOT_EMPTY = 145
# A folder's holder is found through the files inside it; at most this many are asked about.
_HOLDER_FILES_PER_FOLDER = 512


# Installer plan, Stage 2: a new file step waits at most this long for one file, and this long in all.
NEW_STEP_FILE_SECONDS = 10.0
NEW_STEP_SECONDS = 30.0
# Restart Manager's kind for a Windows service; and the Workbench's program name.
_RM_SERVICE = 3
WORKBENCH_PROGRAM = "VideoManglerWorkbench.exe"
# Restart Manager is asked about this many files at a time; a folder's files are all asked about, in parts.
_RM_FILES_PER_CALL = 1000
# The first files a new step's question names are asked about one at a time, so the message can name the file that
# is really held: the step's own files, then a folder's likeliest (programs and libraries, then the largest).
_ONE_AT_A_TIME = 8
# A new step's question asks about a folder's other files this many at a time. Restart Manager opens the files it is
# asked about for as long as it takes to answer (measured: a folder rename stays refused while it does), so the step
# and the question take turns, and a part this size keeps each turn to a fraction of a second.
_FILES_PER_QUESTION_PART = 100
# The longest a try waits for the question's turn before it tries anyway.
_TURN_WAIT_SECONDS = 0.25
# How long a new step waits for a question's answer before it pauses: an answer about a file or two comes within it,
# so the app's own hold stops the step before it waits at all; a folder's answer goes on beside the step.
_ANSWER_GRACE_SECONDS = 0.5
# Files a virus scanner looks at longest: programs and libraries.
_PROGRAM_SUFFIXES = (".dll", ".pyd", ".exe", ".so", ".lib")


@dataclass(frozen=True, slots=True)
class Holder:
    """A program that has a file open, as Windows' Restart Manager reports it.

    ``kind`` is "app" (this process, the Workbench that started it, or one of their children), "workbench" (a
    Media Manglers window still running), "service" (a Windows service) or "program"."""

    pid: int
    name: str
    kind: str = "program"
    service: str = ""

    def describe(self) -> str:
        if self.kind == "service":
            return f"the Windows service {self.name or self.service} (process {self.pid})"
        if self.kind in {"workbench", "app"}:
            return f"Media Manglers (process {self.pid})"
        return f"{self.name or 'a program'} (process {self.pid})"


class FileInUse(PermissionError):
    """Windows still refused to replace, move or remove the file after the wait (another program kept it open),
    or the app itself holds it. It was left as it was. The message names the program when Windows can say
    which; a new file step (Stage 2) also lists them in ``holders``."""

    holders: tuple[Holder, ...] = ()


class FileStepRefused(OSError):
    """A move or removal Windows refused for a reason other than another program holding the file (the path is
    not there, the disk is full, a folder on another drive). Nothing was moved or removed."""


class DownloadNotChecked(FileStepRefused):
    """A downloaded file's SHA-256 did not match the one it was pinned to. It was removed, never put in place."""


class StepBudget:
    """One new file step's time, measured by the clock (installer plan, Stage 2): each file waits at most
    ``per_file`` seconds, and every file of the step together at most ``per_step``. ``clock`` is for tests."""

    def __init__(self, per_file: float = NEW_STEP_FILE_SECONDS, per_step: float = NEW_STEP_SECONDS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.per_file = float(per_file)
        self.per_step = float(per_step)
        self.clock = clock
        self.started = clock()

    def file_deadline(self) -> float:
        """When the file starting now must be done: its own limit, or the step's, whichever comes first."""

        return min(self.clock() + self.per_file, self.started + self.per_step)

    def spent(self) -> float:
        return self.clock() - self.started


class CopyNotChecked(RuntimeError):
    """A database copy did not pass its checks, so it was not kept under the backup's name."""


# Writing a small file --------------------------------------------------------------------------------


def write_text(path: Path | str, text: str, *, encoding: str = "utf-8", wait: float = SHORT_WAIT_SECONDS) -> Path:
    """Replace ``path`` with ``text``. Lines end the way ``Path.write_text`` ends them on this system."""

    def write(temporary: Path) -> None:
        with open(temporary, "w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

    return _replace(Path(path), write, wait)


def write_bytes(path: Path | str, data: bytes, *, wait: float = SHORT_WAIT_SECONDS) -> Path:
    """Replace ``path`` with exactly ``data`` (a backup put back as it was, byte for byte)."""

    def write(temporary: Path) -> None:
        with open(temporary, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

    return _replace(Path(path), write, wait)


def write_json(path: Path | str, data: Any, *, wait: float = SHORT_WAIT_SECONDS) -> Path:
    """Replace ``path`` with ``data`` as indented JSON, the way the app's settings files are written."""

    return write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n", wait=wait)


def _replace(target: Path, write: Callable[[Path], None], wait: float) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".mm-{uuid.uuid4().hex[:16]}.tmp")
    try:
        write(temporary)
        # 224 (Wave B2a review): a small file is waited for even when the app's own reader has it open for a
        # moment (the PowerShell host reads the Inbox's progress file every half second while it is replaced).
        _with_wait(lambda: os.replace(temporary, target), [target, temporary], "replaced", wait, None,
                   source=temporary, app_check=False)
        if os.name != "nt":
            # Linux and macOS: the rename itself reaches the disk once the folder is flushed. NTFS
            # records renames in its journal.
            folder = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(folder)
            finally:
                os.close(folder)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return target


# Moving and removing ---------------------------------------------------------------------------------


def remove(path: Path | str, *, wait: float = SHORT_WAIT_SECONDS,
           pause: Callable[[float], None] | None = None, budget: StepBudget | None = None) -> None:
    """Delete the file ``path`` if it is there, waiting for a program that has it open for a moment."""

    target = Path(path)

    def unlink() -> None:
        target.unlink(missing_ok=True)

    _with_wait(unlink, [target], "removed", wait, pause, source=target, budget=budget)


def move(source: Path | str, destination: Path | str, *, wait: float = INBOX_WAIT_SECONDS,
         pause: Callable[[float], None] | None = None, budget: StepBudget | None = None) -> Path:
    """Move the file or folder ``source`` to ``destination``, which must not be there yet (nothing is ever
    written over). On one drive it is a rename. A file moving to another drive is copied, checked byte for
    byte, given its name, and only then removed from where it was; a folder is only ever moved within one
    drive. Whatever fails, the data is where it was."""

    source, destination = Path(source), Path(destination)
    if not os.path.lexists(source):
        raise FileStepRefused(f"{source.name} could not be moved: it is not there. Nothing was moved. ({source})")
    if os.path.lexists(destination):
        raise FileStepRefused(
            f"{source.name} was not moved: {destination.name} is already there, and the app never writes over "
            f"it. Nothing was moved. ({destination})")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise _refused(exc, source, "moved") from exc
    if _same_drive(source, destination.parent):
        # os.rename, unlike os.replace, refuses a destination that appeared in the meantime.
        _with_wait(lambda: os.rename(source, destination), _holder_paths(source, budget), "moved", wait, pause,
                   source=source, budget=budget)
        return destination
    if source.is_dir():
        raise FileStepRefused(
            f"{source.name} could not be moved: a folder is moved only within one drive, and "
            f"{destination.parent} is on another. Nothing was moved. ({source})")
    copy_file(source, destination, wait=wait, pause=pause, budget=budget)
    try:
        remove(source, wait=wait, pause=pause, budget=budget)
    except FileInUse as exc:
        raised = FileInUse(
            f"{source.name} was copied to {destination} and checked, but the original could not be removed: "
            f"{exc} Nothing was lost.")
        raised.holders = exc.holders
        raise raised from exc
    return destination


def copy_file(source: Path | str, destination: Path | str, *, wait: float = INBOX_WAIT_SECONDS,
              pause: Callable[[float], None] | None = None, budget: StepBudget | None = None) -> Path:
    """A copy of the file ``source`` at ``destination`` (which must not be there yet), made under a short
    partial name beside it, flushed to the disk and checked byte for byte against the original before it gets
    its name. A copy that does not check out is removed and never looks like the real file."""

    source, destination = Path(source), Path(destination)
    if os.path.lexists(destination):
        raise FileStepRefused(
            f"{source.name} was not copied: {destination.name} is already there, and the app never writes over "
            f"it. ({destination})")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f".mm-{uuid.uuid4().hex[:16]}.partial")
    try:
        try:
            shutil.copy2(source, partial)
            with open(partial, "rb+") as handle:
                os.fsync(handle.fileno())
        except OSError as exc:
            raise _refused(exc, source, "copied") from exc
        if partial.stat().st_size != source.stat().st_size or _sha256(partial) != _sha256(source):
            raise FileStepRefused(f"The copy of {source.name} did not match the original, so it was not kept. "
                                  f"Nothing was lost. ({source})")
        _with_wait(lambda: os.rename(partial, destination), [partial, destination], "moved", wait, pause,
                   source=partial, budget=budget)
    finally:
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass
    return destination


def remove_disposable_tree(path: Path | str, *, within: Path | str, wait: float = INBOX_WAIT_SECONDS,
                           pause: Callable[[float], None] | None = None, leftovers: Path | str | None = None,
                           budget: StepBudget | None = None) -> None:
    """Delete ``path`` (a folder or a file) the app made and no longer needs, which must lie inside ``within``.

    A folder is first renamed to a trash name beside it and then deleted, so a delete cut short never looks
    like real data. When another program still holds something in it at the deadline, ``FileInUse`` is raised
    with what was left; with ``leftovers`` the path is also noted there, and ``sweep_leftovers`` removes it at
    the next run. With ``budget`` it is a new file step (Stage 2)."""

    target, root = Path(path), Path(within)
    if not _strictly_within(root, target):
        raise FileStepRefused(f"{target.name} was not removed: it is not inside {root}. ({target})")
    if not os.path.lexists(target):
        _sweep_trash_beside(target, root, pause=pause, leftovers=leftovers)
        return
    if not target.is_dir():
        try:
            remove(target, wait=wait, pause=pause, budget=budget)
        except FileInUse:
            _note_leftover(leftovers, target, root)
            raise
        _sweep_trash_beside(target, root, pause=pause, leftovers=leftovers)
        return
    trash = target.with_name(f"{TRASH_PREFIX}{uuid.uuid4().hex[:12]}")
    try:
        _with_wait(lambda: os.rename(target, trash), _holder_paths(target, budget), "removed", wait, pause,
                   source=target, budget=budget)
    except (FileInUse, FileStepRefused):
        _note_leftover(leftovers, target, root)
        raise
    try:
        _with_wait(lambda: shutil.rmtree(trash), _holder_paths(trash, budget), "removed", wait, pause, source=trash,
                   deleting=True, budget=budget)
    except FileInUse:
        _note_leftover(leftovers, trash, root)
        raise
    except FileStepRefused as exc:
        # Already set aside under its trash name, so "nothing was removed" would not be true.
        _note_leftover(leftovers, trash, root)
        reason = (getattr(exc.__cause__, "strerror", None) or str(exc.__cause__ or exc)).strip().rstrip(".")
        raised = FileStepRefused(
            f"{target.name} was set aside as {trash.name} to be removed, but Windows refused to remove part of it "
            f"({reason}). Nothing that is needed was lost; it is removed at the next run. ({trash})")
        raised.errno, raised.winerror = exc.errno, getattr(exc, "winerror", None)  # type: ignore[attr-defined]
        raise raised from exc
    _sweep_trash_beside(target, root, pause=pause, leftovers=leftovers)


def remove_trash_beside(target: Path | str, *, within: Path | str, budget: StepBudget,
                        pause: Callable[[float], None] | None = None) -> list[Path]:
    """Remove, as a new file step, every trash folder an earlier removal left beside ``target`` (M10 of the Wave I-A
    review): a removal cut short (a read-only file, a program that grabbed a file, the helper being stopped) leaves
    the folder under its trash name. Returns what was removed. When something is still there, ``FileInUse`` or
    ``FileStepRefused`` names it, so the caller never reports success while it is left."""

    target, root = Path(target), Path(within)
    try:
        found = sorted(item for item in target.parent.iterdir() if item.name.startswith(TRASH_PREFIX))
    except OSError:
        return []
    removed: list[Path] = []
    for trash in found:
        if not _strictly_within(root, trash):
            continue
        if trash.is_dir() and not trash.is_symlink():
            _with_wait(lambda folder=trash: shutil.rmtree(folder), [trash], "removed", 0.0, pause, source=trash,
                       deleting=True, budget=budget)
        else:
            remove(trash, pause=pause, budget=budget)
        removed.append(trash)
    return removed


def _sweep_trash_beside(target: Path, root: Path, *, pause: Callable[[float], None] | None,
                        leftovers: Path | str | None) -> None:
    """Remove the trash folders beside ``target`` that an earlier delete left when it was cut short (224, Wave
    B2a): a crash in the middle of deleting one leaves it under its trash name, on no leftovers list. Only this
    helper makes those names, so they are always the app's own disposable copies. One another program still
    holds is noted for the next run; it never fails the clean-up that found it."""

    try:
        found = [item for item in target.parent.iterdir() if item.name.startswith(TRASH_PREFIX)]
    except OSError:
        return
    for trash in found:
        if not _strictly_within(root, trash):
            continue
        try:
            if trash.is_dir() and not trash.is_symlink():
                _with_wait(lambda: shutil.rmtree(trash), _holder_paths(trash), "removed", SHORT_WAIT_SECONDS,
                           pause, source=trash, deleting=True)
            else:
                remove(trash, pause=pause)
        except FileInUse:
            _note_leftover(leftovers, trash, root)
        except OSError:
            pass


def sweep_leftovers(leftovers: Path | str, *, wait: float = SHORT_WAIT_SECONDS,
                    pause: Callable[[float], None] | None = None) -> list[str]:
    """Remove what an earlier run noted in ``leftovers`` (``remove_disposable_tree``) because another program
    still held it then. Returns a plain line for each one still held now; those stay noted for the next run."""

    note = Path(leftovers)
    if not note.is_file():
        return []
    try:
        entries = json.loads(note.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    kept: list[dict[str, str]] = []
    messages: list[str] = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        target, root = Path(str(entry.get("path") or "")), Path(str(entry.get("within") or ""))
        if not str(entry.get("path") or "") or not _strictly_within(root, target):
            continue
        try:
            remove_disposable_tree(target, within=root, wait=wait, pause=pause)
        except FileInUse as exc:
            kept.append({"path": str(target), "within": str(root)})
            messages.append(str(exc))
        except OSError as exc:
            messages.append(str(exc))
    try:
        if kept:
            write_json(note, kept)
        else:
            remove(note)
    except OSError:
        pass
    return messages


def replace_file(target: Path | str, replacement: Path | str, backup_name: str, *,
                 wait: float = INBOX_WAIT_SECONDS, pause: Callable[[float], None] | None = None) -> Path:
    """Put ``replacement`` in ``target``'s place in one Windows step (``ReplaceFileW``), keeping the old target
    beside it as ``backup_name``. Both files are where they were when it fails; the backup is never written
    over. Returns the backup's path."""

    target, replacement = Path(target), Path(replacement)
    backup = target.with_name(backup_name)
    if os.path.lexists(backup):
        raise FileStepRefused(f"{target.name} was not replaced: {backup.name} is already there, and the app never "
                              f"writes over it. ({backup})")
    for path in (target, replacement):
        if not path.is_file():
            raise FileStepRefused(f"{target.name} was not replaced: {path.name} is not there. ({path})")
    if os.name == "nt":
        step = lambda: _replace_file_windows(target, replacement, backup)  # noqa: E731
    else:
        def step() -> None:
            os.rename(target, backup)
            try:
                os.rename(replacement, target)
            except OSError:
                os.rename(backup, target)
                raise
    _with_wait(step, [target, replacement], "replaced", wait, pause, source=target)
    return backup


def _replace_file_windows(target: Path, replacement: Path, backup: Path) -> None:
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.ReplaceFileW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                      ctypes.c_void_p, ctypes.c_void_p]
    kernel32.ReplaceFileW.restype = wintypes.BOOL
    write_through = 0x1
    if kernel32.ReplaceFileW(str(target), str(replacement), str(backup), write_through, None, None):
        return
    code = ctypes.get_last_error()
    if code == _UNABLE_TO_MOVE_REPLACEMENT_2 and backup.exists() and not target.exists():
        # The old file already has the backup's name, but the replacement could not take its place: the old file
        # goes back, so nothing is lost and the next try starts from the same state.
        os.rename(backup, target)
    raise OSError(errno.EACCES, ctypes.FormatError(code).strip(), str(target), code)


# New file steps (installer plan, Stage 2) -----------------------------------------------------------------


def place_checked(partial: Path | str, target: Path | str, sha256: str, *, replace: bool = False,
                  budget: StepBudget | None = None, pause: Callable[[float], None] | None = None) -> Path:
    """Put a finished download in place: ``partial`` is checked against its pinned ``sha256`` first, and only
    then given ``target``'s name. A file that does not match is removed and never looks like the real one.
    A file already at ``target`` is replaced only when the caller says ``replace`` (an approved download
    replacing a damaged copy); otherwise it is never written over."""

    partial, target = Path(partial), Path(target)
    budget = budget or StepBudget()
    if not partial.is_file():
        raise FileStepRefused(f"{target.name} was not put in place: its download is not there. ({partial})")
    found = _sha256(partial)
    if found.casefold() != str(sha256 or "").strip().casefold():
        try:
            remove(partial, pause=pause, budget=budget)
        except OSError:
            pass
        raise DownloadNotChecked(
            f"The download of {target.name} did not match its published checksum, so it was not kept. Nothing "
            f"else was changed; try the download again. ({target})")
    if os.path.lexists(target) and not replace:
        raise FileStepRefused(f"{target.name} was not put in place: it is already there, and the app never writes "
                              f"over it. ({target})")
    target.parent.mkdir(parents=True, exist_ok=True)
    step = (lambda: os.replace(partial, target)) if replace else (lambda: os.rename(partial, target))  # noqa: E731
    _with_wait(step, [partial, target], "put in place", 0.0, pause, source=partial, budget=budget)
    return target


def rename_into_place(temporary: Path | str, final: Path | str, *, budget: StepBudget | None = None,
                      pause: Callable[[float], None] | None = None) -> Path:
    """Give a file or folder built under a temporary name its final name, on the same drive. ``final`` must not
    be there yet; nothing is ever written over."""

    temporary, final = Path(temporary), Path(final)
    budget = budget or StepBudget()
    if not os.path.lexists(temporary):
        raise FileStepRefused(f"{final.name} was not put in place: {temporary.name} is not there. ({temporary})")
    if os.path.lexists(final):
        raise FileStepRefused(f"{final.name} was not put in place: it is already there, and the app never writes "
                              f"over it. ({final})")
    _with_wait(lambda: os.rename(temporary, final), _holder_paths(temporary, budget), "put in place", 0.0, pause,
               source=temporary, budget=budget)
    return final


# The one wait ----------------------------------------------------------------------------------------


def _pauses(wait: float) -> Iterator[float]:
    total, index = 0.0, 0
    while total < wait - 1e-9:
        step = PAUSE_STEPS[index] if index < len(PAUSE_STEPS) else LATER_PAUSE_SECONDS
        step = min(step, wait - total)
        yield step
        total += step
        index += 1


def _is_hold(exc: OSError, source: Path | None, *, deleting: bool = False) -> bool:
    """Whether ``exc`` is Windows refusing because a program has the file open, the one refusal worth waiting
    for. While a folder is deleted, "the directory is not empty" is one too: a file in it waits to be deleted
    until the program that opened it lets go."""

    if os.name != "nt":
        return exc.errno in (errno.EBUSY, errno.ETXTBSY)
    code = getattr(exc, "winerror", None)
    if code in (_SHARING_VIOLATION, _LOCK_VIOLATION, _UNABLE_TO_REMOVE_REPLACED, _UNABLE_TO_MOVE_REPLACEMENT,
                _UNABLE_TO_MOVE_REPLACEMENT_2):
        return True
    if deleting and code == _DIRECTORY_NOT_EMPTY:
        return True
    # A folder whose file is open, or a file being deleted, answers "access denied"; once the file is gone the
    # same answer means something else.
    return code == _ACCESS_DENIED and (source is None or os.path.lexists(source))


def _with_wait(step: Callable[[], T], paths: list[Path], done: str, wait: float,
               pause: Callable[[float], None] | None, *, source: Path | None = None, app_check: bool = True,
               deleting: bool = False, budget: StepBudget | None = None) -> T:
    """Run ``step``, waiting a bounded time while another program holds the file. Without ``app_check`` a hold
    by the app itself is waited for too (a small file's replace, which the app's own reader holds only for a
    moment). With ``budget`` it is a new file step and follows Stage 2's rules (``_with_budget``)."""

    if budget is not None:
        return _with_budget(step, paths, done, budget, pause, source=source, deleting=deleting)
    pauses = _pauses(wait)
    asked = not app_check
    while True:
        try:
            return step()
        except OSError as exc:
            if not _is_hold(exc, source, deleting=deleting):
                if done in {"moved", "removed"}:
                    raise _refused(exc, paths[0], done) from exc
                raise
            if not asked:
                asked = True
                if _app_holds(paths):
                    raise FileInUse(_own_message(paths[0], done)) from exc
            delay = next(pauses, None)
            if delay is None:
                raise FileInUse(_held_message(paths[0], done, paths)) from exc
            (pause or time.sleep)(delay)


def _with_budget(step: Callable[[], T], paths: list[Path], done: str, budget: StepBudget,
                 pause: Callable[[float], None] | None, *, source: Path | None = None, deleting: bool = False) -> T:
    """Stage 2's wait for a new file step: by the clock, at most ``budget``'s time for this file (from its first
    refusal) and for the step; a read-only file or the app's own hold stops at once.

    Who holds the files is asked beside the step (``_HolderQuestion``): the step keeps trying while Windows answers,
    the two take turns (Restart Manager opens the files it is asked about, and Windows refuses the step while it
    does), a new question starts at a refusal once the last one is answered, and the deadline never waits for an
    answer. At the deadline the step is tried once more, then the message names what the latest answer found (H4
    and M9 of the Wave I-A review)."""

    sleep = pause or time.sleep
    deadline: float | None = None
    question: _HolderQuestion | None = None
    answered: _HolderQuestion | None = None
    last_try = False
    index = 0
    try:
        while True:
            try:
                if question is None:
                    return step()
                # The question's part ends within a fraction of a second; a question slower than that never holds
                # the step up: it tries anyway.
                turn = question.turn.acquire(timeout=_TURN_WAIT_SECONDS)
                try:
                    return step()
                finally:
                    if turn:
                        question.turn.release()
            except OSError as exc:
                read_only = _read_only_path(exc, paths)
                if read_only is not None:
                    raise _read_only_refusal(read_only, done) from exc
                if not _is_hold(exc, source, deleting=deleting):
                    if done in {"moved", "removed", "put in place"}:
                        raise _refused(exc, paths[0], done) from exc
                    raise
                now = budget.clock()
                if deadline is None:
                    deadline = min(now + budget.per_file, budget.started + budget.per_step)
                if question is None or (question.done.is_set() and not last_try and now < deadline):
                    answered = question if question is not None and question.found() else answered
                    question = _HolderQuestion(paths, deadline, budget.clock)
                    # A file or two is answered within moments: the app's own hold then stops the step before it
                    # waits at all.
                    question.done.wait(max(0.0, min(_ANSWER_GRACE_SECONDS, deadline - now)))
                if any(holder.kind == "app" for holder in question.found()):
                    raised = FileInUse(_own_message(question.held_file() or paths[0], done))
                    raised.holders = tuple(question.found())
                    raise raised from exc
                now = budget.clock()
                if not last_try:
                    if now >= deadline:
                        # Always tried once more at the deadline, after the latest answer, with the question over.
                        last_try = True
                        question.stop()
                        continue
                    delay = PAUSE_STEPS[index] if index < len(PAUSE_STEPS) else LATER_PAUSE_SECONDS
                    index += 1
                    sleep(max(0.0, min(delay, deadline - now)))
                    continue
                # The latest answer that named someone: the question still running, or the last one answered.
                latest = question if question.found() or answered is None else answered
                found = latest.found()
                held = latest.held_file()
                # The step's own file that is held is named as itself; a file inside a folder as the one held there.
                own_file = held is not None and any(
                    os.path.normcase(str(held)) == os.path.normcase(str(path)) for path in paths)
                raised = FileInUse(new_step_held_message(held if own_file else paths[0], done, found, held))
                raised.holders = tuple(found)
                raise raised from exc
    finally:
        if question is not None:
            # The question asks about no more files; the part it may be asking about now ends within moments, so the
            # caller's next step does not meet a file Restart Manager still has open.
            question.stop()
            question.done.wait(_TURN_WAIT_SECONDS)

class _HolderQuestion:
    """Who holds a new file step's files, asked of Windows' Restart Manager in a worker thread (H4 of the Wave I-A
    review). Restart Manager needs a few milliseconds per file, so a folder is asked about in parts with the clock
    checked between them, and each part's holders are known as soon as it is answered: the step keeps trying while
    Windows answers, and nothing ever waits past ``stop_at`` for it. The first files are asked about one at a time,
    so the file that is really held can be named (M9)."""

    def __init__(self, paths: list[Path], stop_at: float, clock: Callable[[], float]) -> None:
        self._paths = list(paths)
        self._stop_at = stop_at
        self._clock = clock
        self._lock = threading.Lock()
        self._found: list[Holder] = []
        self._held: Path | None = None
        self._stopped = threading.Event()
        # Held while one part is asked about; the step takes it to try, so the two never overlap.
        self.turn = threading.Lock()
        self.done = threading.Event()
        threading.Thread(target=self._ask, name="media-manglers-holder-question", daemon=True).start()

    def stop(self) -> None:
        """The step is over: ask about no more parts."""

        self._stopped.set()

    def found(self) -> list[Holder]:
        with self._lock:
            return list(self._found)

    def held_file(self) -> Path | None:
        with self._lock:
            return self._held

    def _ask(self) -> None:
        try:
            files = _question_files(self._paths)
            roots = _app_roots()
            parents: dict[int, int] | None = None
            index = 0
            while index < len(files) and self._clock() < self._stop_at and not self._stopped.is_set():
                size = 1 if index < _ONE_AT_A_TIME else _FILES_PER_QUESTION_PART
                part = files[index:index + size]
                index += len(part)
                with self.turn:
                    details = _holder_details(part)
                if not details:
                    continue
                parents = _parent_processes() if parents is None else parents
                listed = _classify(details, roots, parents)
                with self._lock:
                    self._found += [holder for holder in listed if holder not in self._found]
                    if self._held is None and len(part) == 1:
                        self._held = part[0]
        except Exception:  # noqa: BLE001 - naming the holder is a courtesy; the step's own error is raised anyway
            pass
        finally:
            self.done.set()


def _question_files(paths: list[Path]) -> list[Path]:
    """Every file a new step's question asks about: the step's own files as given, then each folder's files, the
    ones a virus scanner looks at longest first (programs and libraries, then the largest)."""

    direct: list[Path] = []
    inside: list[tuple[int, int, str]] = []
    for path in paths:
        path = Path(path)
        try:
            folder = path.is_dir() and not path.is_symlink()
        except OSError:
            continue
        if not folder:
            if os.path.lexists(path):
                direct.append(path)
            continue
        pending = [str(path)]
        while pending:
            try:
                with os.scandir(pending.pop()) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                pending.append(entry.path)
                            elif entry.is_file(follow_symlinks=False):
                                program = 0 if entry.name.casefold().endswith(_PROGRAM_SUFFIXES) else 1
                                inside.append((program, -entry.stat(follow_symlinks=False).st_size, entry.path))
                        except OSError:
                            continue
            except OSError:
                continue
    inside.sort()
    return direct + [Path(item) for _program, _size, item in inside]


def _read_only_path(exc: OSError, paths: list[Path]) -> Path | None:
    """The file Windows refused because it is marked read-only, if that is why: waiting cannot help with it.

    Only the files Windows named (the source, and the file being replaced: M9 of the Wave I-A review), or the
    step's own target, are looked at: another read-only file elsewhere in a folder says nothing about why this one
    was refused, and a real hold must still be waited for."""

    if os.name != "nt" or getattr(exc, "winerror", None) != _ACCESS_DENIED:
        return None
    for candidate in [exc.filename, exc.filename2, paths[0] if paths else None]:
        if not candidate:
            continue
        try:
            attributes = os.lstat(candidate).st_file_attributes  # type: ignore[attr-defined]
        except (OSError, AttributeError):
            continue
        if attributes & stat.FILE_ATTRIBUTE_READONLY and not attributes & stat.FILE_ATTRIBUTE_DIRECTORY:
            return Path(candidate)
    return None


def _read_only_refusal(path: Path, done: str) -> FileStepRefused:
    return FileStepRefused(
        f"{path.name} could not be {done}: it is marked read-only, so the app did not wait. Nothing was lost. "
        f"Clear its read-only setting in its Properties, then try again. ({path})")


def new_step_held_message(target: Path, done: str, found: list[Holder], held: Path | None = None) -> str:
    """The plain message when a file step is still refused at its deadline, naming the file and who holds it
    (``held``: the file inside a folder that is really held, when Windows said which).

    It never tells the user to close, stop, exclude or turn off the holder (H3 of the Wave I-A review): Windows
    reports some virus scanners as ordinary programs, so a program, a service or an unnamed holder all get the same
    words, to wait a moment and try again. Only Media Manglers itself, still running, is asked to be closed."""

    target = Path(target)
    it = "it" if held is None or os.path.normcase(str(held)) == os.path.normcase(str(target)) else Path(held).name
    lost = "Nothing was lost."
    workbench = [holder for holder in found if holder.kind == "workbench"]
    if workbench:
        return (f"{target.name} could not be {done} because Media Manglers is still running and has {it} open "
                f"({', '.join(holder.describe() for holder in workbench)}). {lost} Close Media Manglers, then try "
                f"again. ({target})")
    others = [holder for holder in found if holder.kind == "program"] + [
        holder for holder in found if holder.kind == "service"]
    if others:
        names = ", ".join(holder.describe() for holder in others)
        return (f"{target.name} could not be {done} because {names} has {it} open. {lost} Wait a moment, then try "
                f"again. ({target})")
    own = [holder for holder in found if holder.kind == "app"]
    if own:
        return (f"{target.name} could not be {done} because Media Manglers itself still had {it} open "
                f"({', '.join(holder.describe() for holder in own)}). {lost} Try again in a moment. ({target})")
    return (f"{target.name} could not be {done}: another program has {it} open, and Windows did not say which. "
            f"{lost} Wait a moment, then try again. ({target})")


def _refused(exc: OSError, path: Path, done: str) -> FileStepRefused:
    reason = (exc.strerror or str(exc)).strip().rstrip(".")
    refused = FileStepRefused(
        f"{path.name} could not be {done}: Windows refused it ({reason}). Nothing was moved or removed. ({path})")
    refused.errno, refused.winerror = exc.errno, getattr(exc, "winerror", None)  # type: ignore[attr-defined]
    return refused


def _own_message(target: Path, done: str) -> str:
    unchanged = "Nothing was changed" if done == "replaced" else "Nothing was moved or removed"
    return (f"The app itself still has {target.name} open, so it did not wait. {unchanged}. This is a fault in "
            f"the app. ({target})")


def _held_message(target: Path, done: str, paths: list[Path]) -> str:
    """An older step's message at its deadline: the same words as a new step's (H3 of the Wave I-A review)."""

    found = holder_list(paths)
    if found:
        return new_step_held_message(target, done, found)
    # Windows names no program: the file may be read-only, not allowed, or held by something it cannot see.
    return (f"{target.name} could not be {done}: Windows did not say which program has it open. Nothing was "
            f"lost. Wait a moment, then try again; if it still cannot be {done}, check that it is not marked "
            f"read-only. ({target})")


def _holder_paths(path: Path, budget: StepBudget | None = None) -> list[Path]:
    """The paths Windows is asked about for ``path``: a folder's holder is found through the files inside. An older
    step asks about the first 512, listed now; a new file step (``budget``) about every one, listed by its question
    beside the step (``_HolderQuestion``), so a large folder never delays the step itself."""

    if budget is not None or not path.is_dir():
        return [path]
    found = [path]
    for current, _folders, files in os.walk(path):
        for name in files:
            found.append(Path(current) / name)
            if budget is None and len(found) > _HOLDER_FILES_PER_FOLDER:
                return found
    return found


def _same_drive(source: Path, folder: Path) -> bool:
    return os.stat(source).st_dev == os.stat(folder).st_dev


def _strictly_within(root: Path, target: Path) -> bool:
    try:
        root_resolved, target_resolved = root.resolve(), target.resolve()
    except OSError:
        return False
    return root_resolved != target_resolved and root_resolved in target_resolved.parents


def _note_leftover(leftovers: Path | str | None, path: Path, within: Path) -> None:
    if leftovers is None:
        return
    note = Path(leftovers)
    try:
        entries = json.loads(note.read_text(encoding="utf-8")) if note.is_file() else []
    except (OSError, ValueError):
        entries = []
    entries = [entry for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else []
    if not any(str(entry.get("path")) == str(path) for entry in entries):
        entries.append({"path": str(path), "within": str(within)})
    try:
        write_json(note, entries)
    except OSError:
        pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Who holds it ----------------------------------------------------------------------------------------


def holders(paths: list[Path]) -> list[str]:
    """The programs that have any of ``paths`` open, by name and process number, as Windows' Restart Manager
    reports them; [] elsewhere or when Windows cannot tell."""

    return [f"{name or 'a program'} (process {pid})" for pid, _start, name in _holder_processes(paths)]


def holder_list(paths: list[Path]) -> list[Holder]:
    """Every program holding any of ``paths``, each with its kind: the app itself, a Media Manglers still running,
    a Windows service, or another program (installer plan, Stage 2)."""

    found = _holder_details(paths)
    if not found:
        return []
    return _classify(found, _app_roots(), _parent_processes())


def _classify(found: list[tuple[int, int, str, str, int]], roots: dict[int, int | None],
              parents: dict[int, int]) -> list[Holder]:
    """Each holder Restart Manager reported, with its kind."""

    listed: list[Holder] = []
    for pid, started, name, service, app_type in found:
        if _is_app(pid, started, roots, parents):
            kind = "app"
        elif _program_file(pid).casefold() == WORKBENCH_PROGRAM.casefold():
            kind = "workbench"
        elif app_type == _RM_SERVICE or service:
            kind = "service"
        else:
            kind = "program"
        listed.append(Holder(pid, name, kind, service))
    return listed


def _holder_processes(paths: list[Path]) -> list[tuple[int, int, str]]:
    """(process number, start time, name) of every program holding any of ``paths``."""

    return [(pid, started, name) for pid, started, name, _service, _kind in _holder_details(paths)]


def _holder_details(paths: list[Path]) -> list[tuple[int, int, str, str, int]]:
    """(process number, start time, name, service name, Restart Manager kind) of every holder of ``paths``."""

    if os.name != "nt":
        return []
    try:
        # Restart Manager knows files only; a folder in the list makes it refuse the whole question.
        files = [str(path) for path in paths if not Path(path).is_dir()]
        return _restart_manager_holders(files) if files else []
    except Exception:  # noqa: BLE001 - naming the holder is a courtesy; the error itself is raised anyway
        return []


def _program_file(pid: int) -> str:
    """The file name of the program running as process ``pid`` ("" when Windows will not say)."""

    if os.name != "nt":
        return ""
    try:
        import ctypes  # noqa: PLC0415
        from ctypes import wintypes  # noqa: PLC0415

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                        ctypes.POINTER(wintypes.DWORD)]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(1024)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return ""
            return Path(buffer.value).name
        finally:
            kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001
        return ""


def _restart_manager_holders(paths: list[str]) -> list[tuple[int, int, str, str, int]]:
    import ctypes
    from ctypes import wintypes

    class UniqueProcess(ctypes.Structure):
        _fields_ = [("dwProcessId", wintypes.DWORD), ("ProcessStartTime", wintypes.FILETIME)]

    class ProcessInfo(ctypes.Structure):
        _fields_ = [("Process", UniqueProcess), ("strAppName", wintypes.WCHAR * 256),
                    ("strServiceShortName", wintypes.WCHAR * 64), ("ApplicationType", ctypes.c_int),
                    ("AppStatus", wintypes.ULONG), ("TSSessionId", wintypes.DWORD), ("bRestartable", wintypes.BOOL)]

    manager = ctypes.WinDLL("rstrtmgr")
    session = wintypes.DWORD()
    key = ctypes.create_unicode_buffer(33)
    if manager.RmStartSession(ctypes.byref(session), 0, key) != 0:
        return []
    try:
        # Asked in parts, so every file of a large folder (a speech-library set has thousands) is asked about.
        for start in range(0, len(paths), _RM_FILES_PER_CALL):
            part = paths[start:start + _RM_FILES_PER_CALL]
            files = (wintypes.LPCWSTR * len(part))(*part)
            if manager.RmRegisterResources(session, len(part), files, 0, None, 0, None) != 0:
                return []
        needed, count, reasons = wintypes.UINT(0), wintypes.UINT(0), wintypes.DWORD(0)
        result = manager.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reasons))
        if result not in (0, 234) or needed.value == 0:  # 234: more data, the list is the size given in needed
            return []
        found = (ProcessInfo * needed.value)()
        count = wintypes.UINT(needed.value)
        if manager.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), found, ctypes.byref(reasons)) != 0:
            return []
        seen: list[tuple[int, int, str, str, int]] = []
        for info in found[: count.value]:
            started = info.Process.ProcessStartTime
            entry = (int(info.Process.dwProcessId), (started.dwHighDateTime << 32) | started.dwLowDateTime,
                     str(info.strAppName or ""), str(info.strServiceShortName or ""), int(info.ApplicationType))
            if entry not in seen:
                seen.append(entry)
        return seen
    finally:
        manager.RmEndSession(session)


# Which process is the app ----------------------------------------------------------------------------


def mark_app_process() -> None:
    """Called once by the Workbench when it starts: the programs it starts (the PowerShell host, the helpers,
    FFmpeg) inherit this, so a file any of them holds counts as the app's own."""

    started = _process_start_time(os.getpid())
    os.environ[APP_PROCESS_VARIABLE] = f"{os.getpid()}:{started or 0}"


def starting_app_alive() -> bool:
    """Whether the Workbench that started this process (``mark_app_process``) is still running: its process number
    is there and started when it says (M15 of the Wave I-A review: a paused run whose Workbench is gone ends itself).
    True for a process no Workbench started."""

    pid_text, _sep, start_text = os.environ.get(APP_PROCESS_VARIABLE, "").partition(":")
    try:
        pid, started = int(pid_text), int(start_text)
    except ValueError:
        return True
    if pid <= 0 or pid == os.getpid():
        return True
    # An ended process can still be opened while another program holds a handle to it, so it must still be running.
    found = _process_start_time(pid)
    if found is None or not _process_running(pid):
        return False
    return started <= 0 or found == started


def _process_running(pid: int) -> bool:
    """Whether process ``pid`` has not ended yet (Windows' STILL_ACTIVE)."""

    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    try:
        import ctypes  # noqa: PLC0415
        from ctypes import wintypes  # noqa: PLC0415

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001 - when Windows cannot say, the run is not ended
        return True


def _app_roots() -> dict[int, int | None]:
    roots: dict[int, int | None] = {os.getpid(): None}
    pid_text, _sep, start_text = os.environ.get(APP_PROCESS_VARIABLE, "").partition(":")
    try:
        if int(pid_text) > 0 and int(start_text) > 0:
            roots.setdefault(int(pid_text), int(start_text))
    except ValueError:
        pass
    return roots


def _app_holds(paths: list[Path]) -> bool:
    found = _holder_processes(paths)
    if not found:
        return False
    roots = _app_roots()
    parents = _parent_processes()
    return any(_is_app(pid, started, roots, parents) for pid, started, _name in found)


def _is_app(pid: int, started: int, roots: dict[int, int | None], parents: dict[int, int]) -> bool:
    """Whether the process ``pid`` (started at ``started``) is the app: this process, the Workbench that started
    it, or a child of either. Every step up the chain must have started before the one below it, so a process
    number Windows gave to another program after its owner ended is never taken for the app."""

    for _step in range(64):
        if pid == os.getpid():
            return True
        if pid in roots and roots[pid] is not None and started and roots[pid] == started:
            return True
        parent = parents.get(pid, 0)
        if parent <= 0 or parent == pid:
            return False
        parent_started = _process_start_time(parent)
        if not parent_started or not started or parent_started > started:
            return False
        pid, started = parent, parent_started
    return False


def _parent_processes() -> dict[int, int]:
    """Every running process's parent process number (Windows' process snapshot)."""

    if os.name != "nt":
        return {}
    try:
        import ctypes  # noqa: PLC0415
        from ctypes import wintypes  # noqa: PLC0415

        class ProcessEntry(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                        ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                        ("szExeFile", wintypes.WCHAR * 260)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
        if not snapshot or snapshot == wintypes.HANDLE(-1).value:
            return {}
        try:
            entry = ProcessEntry()
            entry.dwSize = ctypes.sizeof(ProcessEntry)
            parents: dict[int, int] = {}
            more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while more:
                parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
            return parents
        finally:
            kernel32.CloseHandle(snapshot)
    except Exception:  # noqa: BLE001 - without the snapshot nothing is taken for the app, and the wait applies
        return {}


def _process_start_time(pid: int) -> int | None:
    """When process ``pid`` started (Windows' FILETIME count), or None when it cannot be read."""

    if os.name != "nt":
        return None
    try:
        import ctypes  # noqa: PLC0415
        from ctypes import wintypes  # noqa: PLC0415

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            created, ended, kernel, user = (wintypes.FILETIME() for _ in range(4))
            if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(ended), ctypes.byref(kernel),
                                            ctypes.byref(user)):
                return None
            return (created.dwHighDateTime << 32) | created.dwLowDateTime
        finally:
            kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001
        return None


# The checked copy of a database (224, Wave B2a, F8) -------------------------------------------------


def read_only_address(path: Path | str) -> str:
    """The address SQLite opens ``path`` from without being able to change it. A network path
    (``\\\\server\\share\\...``) needs ``file:////server/share/...``: SQLite refuses the ``file://server/...``
    form that ``Path.as_uri`` gives it."""

    resolved = Path(path).resolve()
    text = str(resolved)
    if text.startswith("\\\\"):
        return "file:////" + quote(text.lstrip("\\").replace("\\", "/"), safe="/") + "?mode=ro"
    return resolved.as_uri() + "?mode=ro"


def table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    """How many rows every table of the database holds, by table name."""

    names = [str(row[0]) for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    return {name: int(connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]) for name in names}


def _backup_into(connection: sqlite3.Connection, partial: Path) -> None:
    copy = sqlite3.connect(partial)
    try:
        connection.backup(copy)
        # A backup is one file: a copy of a database kept in WAL mode would otherwise grow -wal and -shm files
        # beside it the moment it is read.
        copy.execute("PRAGMA journal_mode = DELETE")
    finally:
        copy.close()


def _side_files(path: Path) -> list[Path]:
    return [path, *(path.with_name(path.name + suffix) for suffix in ("-wal", "-shm", "-journal"))]


def _copy_counts(partial: Path) -> dict[str, int] | None:
    """The copy's table counts, or None when it does not pass SQLite's damage check or cannot be read."""

    try:
        check = sqlite3.connect(read_only_address(partial), uri=True)
    except sqlite3.Error:
        return None
    try:
        if [str(row[0]) for row in check.execute("PRAGMA integrity_check")] != ["ok"]:
            return None
        return table_counts(check)
    except sqlite3.Error:
        return None
    finally:
        check.close()


def checked_copy(connection: sqlite3.Connection, target: Path | str, *, overwrite: bool = False,
                 wait: float = SHORT_WAIT_SECONDS) -> dict[str, int]:
    """A whole copy of the database ``connection`` has open, at ``target``, made with SQLite's own backup call.

    The copy is made under a partial name beside ``target`` and checked there: it must pass SQLite's damage
    check and hold as many rows in every table as the original did at the moment it was copied. Only then is it
    given ``target``'s name, so a damaged, short or empty copy never looks like a backup. A file already at
    ``target`` is never trusted: it is refused, or replaced when the caller says ``overwrite``. ``wait`` is
    how long the rename waits for a program that holds the new copy for a moment. Returns the table counts the
    copy was checked against."""

    target = Path(target)
    if target.exists() and not overwrite:
        raise FileExistsError(
            f"{target.name} is already there, so it was not taken as a backup and nothing was copied over it. "
            f"({target})")
    partial = target.with_name(target.name + ".partial")
    for leftover in _side_files(partial):
        remove(leftover)  # what an interrupted copy left behind is never reused
    reading = not connection.in_transaction
    try:
        # One read covers the counts and the copy, so a write by another program in between cannot make a
        # whole copy look short.
        if reading:
            connection.execute("BEGIN")
        expected = table_counts(connection)
        _backup_into(connection, partial)
    finally:
        if reading and connection.in_transaction:
            connection.rollback()
    try:
        found = _copy_counts(partial)
        if found != expected:
            what = "it is damaged" if found is None else "its row counts differ from the original's"
            raise CopyNotChecked(f"The copy of {target.name} did not check out ({what}), so it was not kept. "
                                 f"({target})")
        _with_wait(lambda: os.replace(partial, target), [partial, target], "replaced", wait, None, source=partial)
    finally:
        for leftover in _side_files(partial):
            try:
                leftover.unlink(missing_ok=True)
            except OSError:
                pass
    return expected
