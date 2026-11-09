"""Review Media Inbox's store (224): the one place the Inbox opens its records, works out its folder and takes its
lock.

It plays the part for the Inbox that ``raw_bin_library`` plays for the raw bin. Every Inbox module asks it
for a connection and never opens a database file itself (``tests/test_inbox_records.py`` checks that):

- ``connect`` opens the records for reading and writing; ``connect_read_only`` never writes.
- ``workspace`` is the Inbox's folder: its queue, batches, history, locks, run journals and every file the
  outside agent reads or writes. Nothing else works it out.
- ``process_lock`` is the Inbox's one lock. Every Inbox action that writes takes it first.

Since Wave B2b the records are in the library, in its ``inbox_`` tables, opened through its front door
(``recording_records``). The old ledger file was moved in once (``inbox_move``), and the Inbox folder is
registered in the library as a root of kind ``inbox``. Until that move is complete the Inbox opens nothing at
all (``status``): every caller, the Workbench, the PowerShell host and every command-line helper, gets the same
plain answer, so no Inbox record can appear in the library ahead of the real ledger.

The text ``ledger_path`` still travels in requests, plans and journals: it names ``review-ledger.sqlite`` in the
Inbox folder (now a short note saying where the records went), and the folder is its parent. Plans made before
the move carry the same text, so their hashes stay valid.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import errno
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any
import uuid

from . import recording_records, review_ledger, safe_write

LOCK_NAME = "process.lock"
ORCHESTRATION_FOLDER = ".orchestration"
LEDGER_NAME = "review-ledger.sqlite"
# 224 (Wave B2a): what a run could not clean up because another program still held it (Decision 3); the next
# Inbox action that writes removes it.
LEFTOVERS_NAME = "leftovers.json"
# What a command-line action says when it finds the lock held (224, design 2.3), after waiting up to
# LOCK_WAIT_SECONDS for it (Wave B2a). The Workbench's own two paths take the same lock, so this is never seen in
# the app.
BUSY_MESSAGE = "The Inbox is busy with another run. Try again when it finishes."
# 224 (Wave B2a, item 4): the Workbench's short status check holds the lock for a moment; a command-line write
# arriving then tries again every quarter second for up to ten seconds before it is refused.
LOCK_WAIT_SECONDS = 10.0
LOCK_RETRY_SECONDS = 0.25
# 224 (Wave B2b): the library's record of the one-time move (a row of Wave A's receipts table), and the kind of
# root the Inbox folder is registered as.
RECEIPT_SOURCE = recording_records.INBOX_RECEIPT_SOURCE
ROOT_KIND = recording_records.INBOX_ROOT_KIND
TABLES = review_ledger.INBOX_TABLES
SQLITE_HEADER = b"SQLite format 3\x00"

READY = "ready"
WAITING = "waiting"
UNAVAILABLE = "unavailable"

NOT_MOVED_YET = ("The Inbox's records move into the library the next time the Workbench starts. Start the "
                 "Workbench once, then try again. Nothing was changed.")
MOVE_UNFINISHED = ("The Inbox's records are part-way through moving into the library. The Workbench finishes the "
                   "move the next time it starts: close any other Workbench window, then restart it. Nothing was "
                   "changed.")
MOVE_UNDONE = ("The Inbox's records could not be moved into the library, so the Inbox is not available in this "
               "version yet. Your Inbox folder and its ledger are as they were. Reason: {reason}")
OLDER_LEDGER = "This Inbox folder has an older ledger that was not moved into the library. Nothing was changed."
NEW_LEDGER_AFTER_MOVE = ("An older version of the Workbench made a new Inbox ledger in your Inbox folder after the "
                         "move. It was not moved; nothing in your library changed.")
OTHER_FOLDER = ("The Inbox's records belong to the Inbox folder {registered}, not {folder}. Choose that folder in "
                "Inbox settings, or move the Inbox folder with the relocation command. Nothing was changed.")


class InboxBusy(RuntimeError):
    """Another run holds the Inbox's lock."""

    def __init__(self) -> None:
        super().__init__(BUSY_MESSAGE)


class InboxFolderMissing(FileNotFoundError):
    """The Inbox folder a lock was asked for is not there, so no folder was made and nothing was changed."""

    def __init__(self, folder: Path) -> None:
        super().__init__(f"There is no Review Media Inbox folder at {folder}, so nothing was changed.")
        self.folder = folder


class InboxLockRefused(OSError):
    """Windows refused to open the Inbox's lock file for a reason other than another run holding it."""


class LedgerTooNew(ValueError):
    """The records were moved on by a newer version of the app; this version reads nothing from them."""


class InboxNotReady(ValueError):
    """The Inbox opens nothing yet (224, Wave B2b): its records have not been moved into the library, the move is
    unfinished or was undone, or this Inbox folder is not the one the records belong to. ``state`` is WAITING or
    UNAVAILABLE; the message says why in plain words."""

    def __init__(self, message: str, state: str = WAITING) -> None:
        super().__init__(message)
        self.state = state


class LedgerMissing(FileNotFoundError):
    """An Inbox action that only works on records that already exist found none for this Inbox folder, so it
    changed nothing."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"There are no Review Media Inbox records for {Path(path).parent}, so nothing was changed.")
        self.path = path


# Where it is ---------------------------------------------------------------------------------------


def ledger_file(where: Mapping[str, Any] | str | os.PathLike[str]) -> Path:
    """The ledger's name in the Inbox folder (``review-ledger.sqlite``, a note since the move), from the Inbox
    folder setting (``review_inbox_folder``, or ``inbox_folder`` in a helper request), the old ledger setting
    (``review_ledger_path``, ``ledger_path``, also inside a request's ``cli`` part) or a path."""

    if isinstance(where, Mapping):
        cli = where.get("cli") if isinstance(where.get("cli"), Mapping) else {}
        folder = str(where.get("inbox_folder") or cli.get("inbox_folder") or where.get("review_inbox_folder") or "")
        if folder.strip():
            return Path(folder.strip()).expanduser() / LEDGER_NAME
        value = str(where.get("ledger_path") or cli.get("ledger_path") or where.get("review_ledger_path") or "")
    else:
        value = os.fspath(where) if where is not None else ""
    value = str(value or "").strip()
    if not value:
        raise ValueError("Choose the Review Media Inbox folder in Inbox settings (ledger_path is required).")
    path = Path(value).expanduser()
    if path.name in {"", ".", ".."}:
        raise ValueError("ledger_path must identify the Review Media Inbox ledger file.")
    return path


def workspace(where: Mapping[str, Any] | str | os.PathLike[str]) -> Path:
    """The Inbox's folder: the folder the ledger's name sits in, as it always was. The queue's own rule
    (``review_queue.queue_root_for_ledger``) and every other place that worked it out ask this."""

    return ledger_file(where).parent


def orchestration_folder(where: Mapping[str, Any] | str | os.PathLike[str]) -> Path:
    """Where Process keeps its run journals, its stop signal and the lock."""

    return workspace(where) / ORCHESTRATION_FOLDER


def lock_file(folder: str | os.PathLike[str]) -> Path:
    """The lock file of the workspace ``folder`` (a folder, not a ledger: the relocation tool knows only that)."""

    return Path(folder) / ORCHESTRATION_FOLDER / LOCK_NAME


def leftovers_file(where: Mapping[str, Any] | str | os.PathLike[str]) -> Path:
    """The list of clean-ups another program blocked (``safe_write.remove_disposable_tree``), for the next run."""

    return orchestration_folder(where) / LEFTOVERS_NAME


def sweep_leftovers(where: Mapping[str, Any] | str | os.PathLike[str]) -> list[str]:
    """Remove what earlier runs could not; a plain line for each one still held. Only a holder of the lock
    calls this."""

    return safe_write.sweep_leftovers(leftovers_file(where))


def is_database(path: str | os.PathLike[str]) -> bool:
    """Whether ``path`` is a SQLite database (a real ledger), not the note the move leaves in its place."""

    try:
        with open(path, "rb") as handle:
            return handle.read(len(SQLITE_HEADER)) == SQLITE_HEADER
    except OSError:
        return False


# Whether the Inbox may open anything ---------------------------------------------------------------


@dataclass(frozen=True)
class InboxStatus:
    """What the Inbox may do now (224, design 4.1). ``state`` is READY, WAITING or UNAVAILABLE; ``message`` says
    why in plain words when it is not ready; ``folder`` is the Inbox folder registered in the library, or None
    while no Inbox folder has records yet."""

    state: str
    message: str = ""
    folder: Path | None = None

    @property
    def ready(self) -> bool:
        return self.state == READY


def receipt(connection: sqlite3.Connection) -> sqlite3.Row | None:
    """The newest receipt of the move, or None when the library has none."""

    try:
        return connection.execute(
            "SELECT import_id, status, note, counts_json, backup_folder, source_sha256 FROM legacy_imports "
            "WHERE source = ? ORDER BY import_id DESC LIMIT 1", (RECEIPT_SOURCE,)).fetchone()
    except sqlite3.Error:
        return None


def registered_folder(connection: sqlite3.Connection) -> Path | None:
    """The Inbox folder registered in the library, or None while no Inbox folder holds records."""

    try:
        row = connection.execute("SELECT path FROM roots WHERE kind = ? ORDER BY root_id LIMIT 1",
                                 (ROOT_KIND,)).fetchone()
    except sqlite3.Error:
        return None
    return Path(str(row[0])) if row else None


def status(connection: sqlite3.Connection, folder: str | os.PathLike[str] | None = None) -> InboxStatus:
    """Whether the Inbox may open its records for ``folder`` (the Inbox folder a request names; None for
    "whichever is registered"), read from the move's receipt and the registered folder in the library."""

    found = receipt(connection)
    if found is None:
        return InboxStatus(WAITING, NOT_MOVED_YET)
    state = str(found["status"] or "")
    if state in ("failed", "restored"):
        reason = str(found["note"] or "").strip() or "not recorded"
        return InboxStatus(UNAVAILABLE, MOVE_UNDONE.format(reason=reason))
    if state != "complete":
        return InboxStatus(WAITING, MOVE_UNFINISHED)
    registered = registered_folder(connection)
    if registered is not None:
        if folder is not None and recording_records.path_key(folder) != recording_records.path_key(registered):
            return InboxStatus(UNAVAILABLE, OTHER_FOLDER.format(registered=registered, folder=folder), registered)
        if is_database(registered / LEDGER_NAME):
            return InboxStatus(UNAVAILABLE, NEW_LEDGER_AFTER_MOVE, registered)
        return InboxStatus(READY, "", registered)
    if folder is not None and is_database(Path(folder) / LEDGER_NAME):
        return InboxStatus(UNAVAILABLE, OLDER_LEDGER)
    return InboxStatus(READY)


def current_status(where: Mapping[str, Any] | str | os.PathLike[str] | None = None) -> InboxStatus:
    """``status`` read from the library without changing anything, for a page or a check that only looks."""

    folder = workspace(where) if where is not None else None
    try:
        connection = recording_records.connect_read_only()
    except recording_records.LibraryTooNew as exc:
        return InboxStatus(UNAVAILABLE, str(exc))
    if connection is None:
        return InboxStatus(WAITING, NOT_MOVED_YET)
    try:
        return status(connection, folder)
    finally:
        connection.close()


# Opening it ----------------------------------------------------------------------------------------


class _Shared:
    """The library connection one helper (one thread) keeps for every Inbox step it takes (224, Wave B2b: the
    library's front door takes a write lock on every open, so each helper opens it once). Closing it gives back
    what it did not commit and keeps it open for the next step; ``release`` really closes it."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)

    def __enter__(self) -> "_Shared":
        self._connection.__enter__()
        return self

    def __exit__(self, *details: Any) -> Any:
        return self._connection.__exit__(*details)

    def close(self) -> None:
        if self._connection.in_transaction:
            self._connection.rollback()


_shared: dict[tuple[int, str], sqlite3.Connection] = {}
_shared_guard = threading.Lock()


def _library() -> sqlite3.Connection:
    """This thread's library connection, opened (and moved up) once."""

    key = (threading.get_ident(), recording_records.path_key(recording_records.library_root()))
    with _shared_guard:
        connection = _shared.get(key)
        stale = [other for other in _shared if other[0] == key[0] and other != key]
        for other in stale:  # the library moved (a test's own folder): the old one is let go
            _shared.pop(other).close()
    if connection is None:
        connection = recording_records.connect(backup=False)
        with _shared_guard:
            _shared[key] = connection
    return connection


def release() -> None:
    """Close this thread's library connection (the end of a helper, or of the Workbench's status-check thread)."""

    ident = threading.get_ident()
    with _shared_guard:
        mine = [key for key in _shared if key[0] == ident]
        connections = [_shared.pop(key) for key in mine]
    for connection in connections:
        connection.close()


def release_all() -> None:
    """Close every thread's library connection (a test's end)."""

    with _shared_guard:
        connections = list(_shared.values())
        _shared.clear()
    for connection in connections:
        try:
            connection.close()
        except sqlite3.ProgrammingError:
            pass  # made in another thread that has ended; the system closes it with the thread's objects


def _ready(connection: sqlite3.Connection, where: Mapping[str, Any] | str | os.PathLike[str]) -> InboxStatus:
    found = status(connection, workspace(where))
    if not found.ready:
        raise InboxNotReady(found.message, found.state)
    return found


def has_records(where: Mapping[str, Any] | str | os.PathLike[str]) -> bool:
    """Whether the library holds the Inbox's records for this Inbox folder (it is the registered one). Every place
    that asked "is there a ledger file" asks this since the move: the note is a file too (224, Wave B2b)."""

    connection = recording_records.connect_read_only()
    if connection is None:
        return False
    try:
        found = status(connection, workspace(where))
        return found.ready and found.folder is not None
    finally:
        connection.close()


def connect(where: Mapping[str, Any] | str | os.PathLike[str], *, must_exist: bool = False) -> sqlite3.Connection:
    """The Inbox's records for reading and writing, in the library. Only an Inbox writer, holding
    ``process_lock``, opens them this way. A first run of a new Inbox registers its folder. ``must_exist`` is for
    an action that works on records it expects to be there (an import, a finalization): with none for this
    folder it changes nothing and registers nothing (224, F4 and F5)."""

    connection = _library()
    found = _ready(connection, where)
    if found.folder is None:
        if must_exist:
            raise LedgerMissing(ledger_file(where))
        _register(connection, workspace(where))
    return _Shared(connection)  # type: ignore[return-value]


def _register(connection: sqlite3.Connection, folder: Path) -> None:
    now = recording_records._stamp()
    with connection:
        connection.execute(
            "INSERT INTO roots(kind, path, path_key, first_seen_utc, last_seen_utc) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(kind, path_key) DO UPDATE SET last_seen_utc = excluded.last_seen_utc",
            (ROOT_KIND, str(folder), recording_records.path_key(folder), now, now))
        for statement in review_ledger.library_guard_statements():
            connection.execute(statement)


def settle(where: Mapping[str, Any] | str | os.PathLike[str]) -> None:
    """Nothing to move up since the records live in the library (its front door moves its structure up); kept so
    an Inbox writer's entry point reads the same."""

    return None


def connect_read_only(where: Mapping[str, Any] | str | os.PathLike[str]) -> sqlite3.Connection | None:
    """The Inbox's records opened so that nothing can be changed, or None when this Inbox folder has none yet. A
    reader never makes, registers or moves anything and never takes a write lock (224, F4). An Inbox that
    opens nothing yet raises ``InboxNotReady`` with the plain reason."""

    connection = recording_records.connect_read_only()
    if connection is None:
        raise InboxNotReady(NOT_MOVED_YET)
    try:
        version = recording_records.stored_version(connection)
        if version < recording_records.SCHEMA_VERSION:
            raise InboxNotReady(NOT_MOVED_YET)
        found = _ready(connection, where)
        if found.folder is None:
            connection.close()
            return None
        connection.execute("PRAGMA foreign_keys = ON")
    except BaseException:
        connection.close()
        raise
    return connection


def settle_file(path: str | os.PathLike[str]) -> None:
    """Open an old ledger once the normal way and close it, so SQLite finishes or undoes a change a crash left
    half-written beside it (it writes to the file only then, as any open does). Only the move calls this, before
    its backup (224, design 4.2 step 3); it never moves the ledger's structure up (the design's correction:
    the move does not ``settle`` the old way)."""

    connection = sqlite3.connect(path, timeout=5)
    try:
        connection.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
    finally:
        connection.close()


def read_only_file(path: str | os.PathLike[str]) -> sqlite3.Connection:
    """A database file, or a copy of one, opened so that nothing can be changed: for the move, which reads the old
    ledger and its checked copy, and the relocation tool, which reads its backups."""

    connection = sqlite3.connect(safe_write.read_only_address(path), uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def backup(where: Mapping[str, Any] | str | os.PathLike[str], target: str | os.PathLike[str], *,
           overwrite: bool = False) -> Path:
    """A whole, checked copy of the library holding the Inbox's records, at ``target``
    (``safe_write.checked_copy``), for the relocation tool, which may be moving the Inbox folder ``where`` names.
    A file already at ``target`` is refused unless ``overwrite``."""

    connection = relocation_connection(write=True)
    safe_write.checked_copy(connection, target, overwrite=overwrite)
    return Path(target)


def _moved(connection: sqlite3.Connection) -> None:
    """The move is complete, or ``InboxNotReady``. Only the receipt is read: the folder the library registers may
    be the relocation's old one, on a drive that is gone, and the relocation tool never probes an old root."""

    found = receipt(connection)
    state = str(found["status"] or "") if found is not None else ""
    if state == "complete":
        return
    if state in ("failed", "restored"):
        reason = str(found["note"] or "").strip() or "not recorded"
        raise InboxNotReady(MOVE_UNDONE.format(reason=reason), UNAVAILABLE)
    raise InboxNotReady(MOVE_UNFINISHED if found is not None else NOT_MOVED_YET)


def relocation_connection(*, write: bool = False) -> sqlite3.Connection:
    """The Inbox's records for the relocation tool (224, Q6). It moves the Inbox folder itself, so it is held to
    the move being complete, not to the folder registered now; it checks that folder against its own plan. Read
    only unless ``write`` (then this thread's shared connection, as ``connect`` gives)."""

    if write:
        connection = _library()
        _moved(connection)
        return _Shared(connection)  # type: ignore[return-value]
    connection = recording_records.connect_read_only()
    if connection is None:
        raise InboxNotReady(NOT_MOVED_YET)
    try:
        _moved(connection)
        connection.execute("PRAGMA foreign_keys = ON")
    except BaseException:
        connection.close()
        raise
    return connection


def link_problems(connection: sqlite3.Connection) -> list[Any]:
    """Every broken link of the Inbox's own tables, checked table by table (``PRAGMA foreign_key_check(<table>)``),
    so an unrelated raw bin row in the shared library never refuses an Inbox step (224, design 4.3)."""

    return [row for table in TABLES.values()
            for row in connection.execute(f"PRAGMA foreign_key_check({table})").fetchall()]


def validate(connection: sqlite3.Connection) -> dict[str, Any]:
    """The ledger's own rules (``review_ledger.validate_ledger``) on the Inbox's tables in the library, with the
    library's structure version."""

    return {"schema_version": recording_records.stored_version(connection),
            **review_ledger.validate_ledger(connection, TABLES)}


# The lock ------------------------------------------------------------------------------------------


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


class ProcessLock:
    """The Inbox's one lock: one locked byte of ``<workspace>\\.orchestration\\process.lock``. ``acquired`` is
    False, not an error, when another process holds it; the PowerShell host's Process loop holds the same file
    open with no sharing, which also leaves ``acquired`` False here. A crashed holder's lock is released by
    the system."""

    def __init__(self, path: Path, *, make_workspace: bool = False) -> None:
        self.path = path
        self.token = uuid.uuid4().hex
        self.acquired = False
        self.make_workspace = make_workspace
        self._handle: Any = None

    def __enter__(self) -> "ProcessLock":
        # 224 (Wave B2a, note 10): the lock makes only its own folder, inside an Inbox folder that is there. A
        # caller that may start a new Inbox (a first run) says make_workspace; the relocation tool, which works on
        # an existing one, never makes the folders of a mistyped path.
        workspace_folder = self.path.parent.parent
        if self.make_workspace:
            workspace_folder.mkdir(parents=True, exist_ok=True)
        elif not workspace_folder.is_dir():
            raise InboxFolderMissing(workspace_folder)
        self.path.parent.mkdir(exist_ok=True)
        try:
            handle = _open_lock_file(self.path)
        except OSError as exc:
            # 224 (Wave B2a, note 7): only another run holding the file (the host's Process loop holds it open
            # with no sharing) means busy; anything else is said plainly.
            if _held_by_another_run(exc):
                return self
            reason = (exc.strerror or str(exc)).strip().rstrip(".")
            raise InboxLockRefused(f"Windows refused to open the Inbox's lock file ({reason}), so nothing was done. "
                                   f"({self.path})") from exc
        try:
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b" ")
                os.fsync(handle.fileno())
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, ValueError):
            handle.close()
            return self

        record = _canonical_bytes(
            {
                "schema_version": 1,
                "token": self.token,
                "process_id": os.getpid(),
                "created_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        try:
            handle.seek(0)
            handle.write(record)
            handle.truncate()
            os.fsync(handle.fileno())
        except OSError:
            try:
                self._unlock(handle)
            finally:
                handle.close()
            raise
        self._handle = handle
        self.acquired = True
        return self

    @staticmethod
    def _unlock(handle: Any) -> None:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        handle = self._handle
        self._handle = None
        if not self.acquired or handle is None:
            return
        self.acquired = False
        try:
            self._unlock(handle)
        finally:
            handle.close()


def _open_lock_file(path: Path) -> Any:
    """The lock file opened for reading and writing (made when it is not there), shared for reading and writing as
    Python's own ``open`` shares it. On Windows it is opened through ``CreateFileW`` itself, because Python's
    ``os.open`` reports a sharing refusal and a real "access denied" as the same "Permission denied"; this way the
    error carries Windows' own number, so another run holding the file can be told from anything else."""

    if os.name != "nt":
        return os.fdopen(os.open(path, os.O_CREAT | os.O_RDWR), "r+b", buffering=0)
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415
    import msvcrt  # noqa: PLC0415

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                     wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    read_write, share_read_write, open_always, normal = 0xC0000000, 0x1 | 0x2, 4, 0x80
    handle = kernel32.CreateFileW(str(path), read_write, share_read_write, None, open_always, normal, None)
    if not handle or handle == wintypes.HANDLE(-1).value:
        code = ctypes.get_last_error()
        raise OSError(errno.EACCES, ctypes.FormatError(code).strip(), str(path), code)
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDWR)
    except OSError:
        kernel32.CloseHandle(handle)
        raise
    return os.fdopen(descriptor, "r+b", buffering=0)


def _held_by_another_run(exc: OSError) -> bool:
    if os.name == "nt":
        return getattr(exc, "winerror", None) in (32, 33)  # a sharing or lock violation
    return exc.errno in (errno.EAGAIN, errno.EBUSY)


class CoordinatorOwnedLock:
    """Stands in for the lock when the PowerShell host already holds it for its whole Process loop and passes
    ``coordinator_lock_held`` to the helpers it calls inside that loop."""

    acquired = True

    def __enter__(self) -> "CoordinatorOwnedLock":
        return self

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        return None


def process_lock(where: Mapping[str, Any] | str | os.PathLike[str], *,
                 coordinator_lock_held: bool = False) -> ProcessLock | CoordinatorOwnedLock:
    """The Inbox's lock for this workspace, to use in a ``with``; check ``acquired`` before writing."""

    if coordinator_lock_held:
        return CoordinatorOwnedLock()
    # Reconcile, Process and the command-line writers may be the first run of a new Inbox, so they make its folder.
    return ProcessLock(lock_file(workspace(where)), make_workspace=True)


@contextmanager
def writing(where: Mapping[str, Any] | str | os.PathLike[str], *, coordinator_lock_held: bool = False,
            wait: float = LOCK_WAIT_SECONDS, pause: Callable[[float], None] | None = None) -> Iterator[None]:
    """Run one command-line Inbox action under the lock. While another run holds it, try again every quarter
    second for up to ``wait`` seconds (the Workbench's status check holds it for a moment), then refuse with one
    plain line. A helper the PowerShell host calls inside its own Process loop says ``coordinator_lock_held``
    and never waits. An Inbox that opens nothing yet (224, Wave B2b) is refused before the lock is taken, and
    nothing is made."""

    connection = _library()
    _ready(connection, where)
    lock = _take_lock(where, coordinator_lock_held, wait, pause)
    try:
        sweep_leftovers(where)
        yield
    finally:
        lock.__exit__(None, None, None)


def _take_lock(where: Mapping[str, Any] | str | os.PathLike[str], coordinator_lock_held: bool, wait: float,
               pause: Callable[[float], None] | None) -> ProcessLock | CoordinatorOwnedLock:
    waited = 0.0
    while True:
        lock = process_lock(where, coordinator_lock_held=coordinator_lock_held).__enter__()
        if lock.acquired:
            return lock
        if waited >= wait - 1e-9:
            raise InboxBusy()
        step = min(LOCK_RETRY_SECONDS, wait - waited)
        (pause or time.sleep)(step)
        waited += step
