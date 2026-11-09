"""The one-time move of Review Media Inbox's ledger into the library (224, Wave B2b; design section 4).

The Workbench runs ``move_ledger`` once at every start, after the library is open and its settings are read and
before any page or Inbox action exists. It does nothing once the move is complete. Otherwise it follows the move's
receipt (a row of Wave A's ``legacy_imports``, source "inbox ledger"):

1. it takes the library's move lock, checks no other Workbench is open, and takes the Inbox's own lock;
2. writes the receipt ("started") before anything changes;
3. lets SQLite finish or undo anything a crash left half-written beside the ledger, and waits while a
   ``-journal``, ``-wal`` or ``-shm`` file is still there;
4. backs up, into ``<library>\\backups\\migrations\\<date-time>-wave-b\\`` (never pruned): the ledger and the
   library (checked copies), ``settings.json`` and every custom profile (byte for byte), an inventory of every
   record file in the Inbox folder, ``BACKUP_MANIFEST.json`` and ``HOW_TO_RESTORE.txt``;
5. checks the ledger's copy (damage, links, version 2, only known tables, the ledger's own rules, identities,
   and that no unfinished plan or journal names another folder);
6. copies every table into the library's ``inbox_`` tables with every ID unchanged, in one transaction that
   also registers the Inbox folder and proves every count, state count, fingerprint and link equal; any
   difference rolls it all back;
7. checks again after the commit, re-hashes every record file, and requires the Raw bin's Mined answer to be
   the same for every recording, or wider only where a recording finished on its own (Q7);
8. proves nothing wrote to the original meanwhile (its fingerprints, read without writing, equal the copy's);
9. switches on the library's rules that keep accepted results ("verified");
10. swaps a short note into the ledger's place in one Windows step, keeping the original beside it as
    ``review-ledger.sqlite.moved-<date>.sqlite``;
11. names the Inbox folder in the settings (``review_inbox_folder``); ``review_ledger_path`` stays as it was;
12. marks the receipt "complete".

A failure before 9 is put back: the import is rolled back, or deleted again in one transaction (the library's
rules are not on yet, and no library file is ever copied back while a Workbench runs), and the receipt says
"restored" with the reason. A held ledger at 10, or a failure at 11, leaves the records safe and the next start
finishes the move. A crash anywhere is finished or undone at the next start, from the receipt. Running it twice
changes nothing.

Nothing here reads drive media: the inventory leaves media files out, so the move takes seconds.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any

from . import inbox_records, recording_records, review_ledger, safe_write

BACKUP_LABEL = "wave-b"
# The library's structure from which the Inbox's records are in it (``recording_records._step_inbox``).
INBOX_STRUCTURE = 5
LEDGER_COPY = "review-ledger.sqlite"
INVENTORY = "WORKSPACE_INVENTORY.json"
RECEIPT_COPY = "MOVE_RECEIPT.json"
# The ledger's own tables: twelve in every version-2 ledger, relocation_runs only where a relocation ran.
REQUIRED_TABLES = tuple(name for name in review_ledger.INBOX_TABLES if name != "relocation_runs")
OPTIONAL_TABLES = ("relocation_runs",)
SQLITE_OWN = {"sqlite_sequence"}
# The four tables that number their own rows (design 3.2): their counters move too.
NUMBERED_TABLES = ("sources", "source_locations", "attempts", "lifecycle_events")
# The counts the move checks by state (design 3.3).
STATE_COLUMNS = {
    "sources": ("lifecycle_state",), "batch_sources": ("state",), "batches": ("status",),
    "attempts": ("attempt_type", "status"), "findings": ("stage", "status"), "final_results": ("disposition",),
    "finalization_runs": ("status",), "relocation_runs": ("status",), "reviews": ("status",),
}
# The stored generated paths, each counted as inside the Inbox folder, outside it, or missing (design 4.3).
GENERATED_PATHS = (("batches", "package_path"), ("finalization_runs", "journal_path"),
                   ("retention_records", "history_path"))
# Media is left out of the inventory: only the record files (manifests, imports, journals, plans) are hashed.
MEDIA_SUFFIXES = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".ts", ".m4v", ".wav", ".mp3", ".m4a", ".aac", ".flac",
    ".ogg", ".opus", ".wma", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".zip",
}
NOTE = ("This Review Media Inbox ledger was moved into the Workbench library on {date} by version {version}. The "
        "original is kept beside this note as {moved}. Use version {version} or later.\n")
HOW_TO_RESTORE = """How to put back what the Workbench changed on {when}

The Workbench moved Review Media Inbox's records out of its ledger into its library, and put a short note in the
ledger's place (the original ledger is kept beside it, under a name that starts with review-ledger.sqlite.moved-).
Before it changed anything it copied these here, and checked the copies:

  review-ledger.sqlite     the Inbox's ledger as it was
  raw-bin-library.sqlite   the library just before the move
  settings.json           your settings file as it was
  profiles\\               each of your own profiles as it was (when you have any)
  WORKSPACE_INVENTORY.json the size and SHA-256 of every record file in your Inbox folder

To go back to the Workbench version you used before this one:
  1. Close every Workbench window.
  2. {earlier_library}
     Then delete the files beside it named raw-bin-library.sqlite-wal and raw-bin-library.sqlite-shm if they are
     there. The library folder is:
       {library}
     This puts back the library as it was before this version: anything the Workbench recorded in it since (raw bin
     scans, decisions, run history) goes back with it.
  3. In your Inbox folder, delete the note named review-ledger.sqlite, and rename the file beside it whose name
     starts with review-ledger.sqlite.moved- back to review-ledger.sqlite:
       {folder}
  4. Copy settings.json from this folder over the one in your settings folder:
       {settings}
  5. Use the earlier version. Starting this version again moves the ledger again.

The raw-bin-library.sqlite in this folder is the library just before the move, at this version's structure and
without the Inbox's records, kept as a record. Do not put it back on its own: the note in your Inbox folder says the
records have moved, so the Workbench would refuse it.

A daily copy of the library made after the move (in its backups folder) holds the Inbox's records. Putting one of
those back puts the records back with it, while the files in your Inbox folder stay as they are now: the Inbox
imports what it already received again from its kept copies, and a finalization whose journal is further along than
its records stops with "needs a look" instead of guessing.

BACKUP_MANIFEST.json lists each copy's SHA-256.
"""
EARLIER_LIBRARY = """Copy raw-bin-library.sqlite from the folder below over the one in the library folder. An earlier
     version cannot open the copy in this folder, because it is already at this version's structure.
       {folder}"""
NO_EARLIER_LIBRARY = """This version made your library, so there is no earlier copy to put back. Rename the
     raw-bin-library.sqlite in the library folder, and the earlier version starts a new one."""

# One function a test (or the rehearsal on copies) sets to fail or stop the move after a step; None in the app.
checkpoint: Callable[[str], None] | None = None


class MoveRefused(RuntimeError):
    """The move found something it must not import; nothing was changed in the Inbox."""


@dataclass
class MoveResult:
    """What the move did: ``status`` is "nothing" (complete already, or nothing to move), "moved", "waiting" (the
    next start tries again), "refused" or "restored" (put back, with the reason). ``message`` is one plain line
    for the Inbox page and the log; ``counts`` hold numbers only."""

    status: str
    message: str = ""
    counts: dict[str, Any] = field(default_factory=dict)
    backup_folder: str = ""
    receipt: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "message": self.message, "counts": self.counts,
                "backup_folder": self.backup_folder, "receipt": self.receipt}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _step(name: str) -> None:
    if checkpoint is not None:
        checkpoint(name)


def _sha256_file(path: Path) -> str:
    return review_ledger.sha256_file(path)


# Fingerprints and counts ---------------------------------------------------------------------------


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')]


def _key_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    keyed = sorted((int(row[5]), str(row[1])) for row in connection.execute(f'PRAGMA table_info("{table}")')
                   if int(row[5]))
    return [name for _order, name in keyed]


def _tagged(value: Any) -> list[Any]:
    if value is None:
        return ["n"]
    if isinstance(value, bool):
        return ["i", int(value)]
    if isinstance(value, int):
        return ["i", value]
    if isinstance(value, float):
        return ["f", repr(value)]
    if isinstance(value, bytes):
        return ["b", value.hex()]
    return ["s", str(value)]


def fingerprint(connection: sqlite3.Connection, table: str, columns: list[str], keys: list[str]) -> tuple[int, str]:
    """(rows, SHA-256 over every row in key order, every column, each value with its type): even one changed
    value changes it (design 3.6)."""

    digest = hashlib.sha256()
    count = 0
    selected = ", ".join(f'"{name}"' for name in columns)
    order = ", ".join(f'"{name}"' for name in keys) or "rowid"
    for row in connection.execute(f'SELECT {selected} FROM "{table}" ORDER BY {order}'):
        digest.update(json.dumps([_tagged(value) for value in row], separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
        count += 1
    return count, digest.hexdigest()


def _state_counts(connection: sqlite3.Connection, table: str, columns: tuple[str, ...]) -> dict[str, int]:
    selected = ", ".join(f'COALESCE("{name}", \'\')' for name in columns)
    return {"|".join(str(value) for value in row[:-1]): int(row[-1]) for row in connection.execute(
        f'SELECT {selected}, COUNT(*) FROM "{table}" GROUP BY {selected} ORDER BY {selected}')}


def measure(connection: sqlite3.Connection, names: Mapping[str, str], shape: sqlite3.Connection,
            present: list[str]) -> dict[str, Any]:
    """Every count, state count and fingerprint of the Inbox's tables, read through ``connection`` under
    ``names`` (the ledger's own names, or the library's ``inbox_`` names), with the columns and keys the ledger
    copy ``shape`` has, so both sides are measured the same way."""

    tables: dict[str, Any] = {}
    for table in present:
        columns, keys = _columns(shape, table), _key_columns(shape, table)
        rows, digest = fingerprint(connection, names.get(table, table), columns, keys)
        entry: dict[str, Any] = {"rows": rows, "fingerprint": digest}
        if table in STATE_COLUMNS:
            entry["states"] = _state_counts(connection, names.get(table, table), STATE_COLUMNS[table])
        tables[table] = entry
    return tables


def _sequences(connection: sqlite3.Connection, names: Mapping[str, str]) -> dict[str, int]:
    wanted = {names.get(table, table): table for table in NUMBERED_TABLES}
    found: dict[str, int] = {}
    try:
        for name, seq in connection.execute("SELECT name, seq FROM sqlite_sequence"):
            if str(name) in wanted:
                found[wanted[str(name)]] = int(seq or 0)
    except sqlite3.Error:
        pass
    return found


# The checks ---------------------------------------------------------------------------------------


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def check_copy(copy: sqlite3.Connection, folder: Path) -> dict[str, Any]:
    """Check 1 (design 4.3) on the ledger's checked copy. Raises ``MoveRefused`` with the plain reason."""

    if [str(row[0]) for row in copy.execute("PRAGMA integrity_check")] != ["ok"]:
        raise MoveRefused("The ledger's copy did not pass SQLite's damage check.")
    if copy.execute("PRAGMA foreign_key_check").fetchall():
        raise MoveRefused("The ledger has broken links between its records.")
    version = int(copy.execute("PRAGMA user_version").fetchone()[0])
    if version != review_ledger.SCHEMA_VERSION:
        raise MoveRefused(f"The ledger is at structure {version}; only a version {review_ledger.SCHEMA_VERSION} "
                          "ledger is moved.")
    tables = _tables(copy)
    unknown = sorted(tables - set(review_ledger.INBOX_TABLES) - SQLITE_OWN)
    if unknown:
        raise MoveRefused(f"The ledger has {len(unknown)} table(s) this version does not know, so nothing was moved.")
    missing = [table for table in REQUIRED_TABLES if table not in tables]
    if missing:
        raise MoveRefused(f"The ledger is missing {len(missing)} of its tables, so nothing was moved.")
    try:
        review_ledger.validate_ledger(copy)
    except RuntimeError as exc:
        raise MoveRefused(f"The ledger did not pass its own checks ({exc}).") from exc
    bad_identity = int(copy.execute(
        "SELECT COUNT(*) FROM sources WHERE stable_identity IS NOT NULL AND "
        "stable_identity <> 'sha256:' || lower(COALESCE(content_sha256, ''))").fetchone()[0])
    if bad_identity:
        raise MoveRefused(f"{bad_identity} recording(s) in the ledger have a content identity that does not match "
                          "their content hash.")
    duplicated = int(copy.execute(
        "SELECT COUNT(*) FROM (SELECT provisional_identity FROM sources GROUP BY provisional_identity "
        "HAVING COUNT(*) > 1)").fetchone()[0])
    if duplicated:
        raise MoveRefused("The ledger names one provisional recording identity more than once.")
    return {"structure_version": version, "tables": sorted(tables - SQLITE_OWN),
            "plans_and_journals": check_plans(copy, folder, "relocation_runs" in tables)}


def _old_roots(copy: sqlite3.Connection, has_relocations: bool) -> set[str]:
    """The folders a recorded relocation moved this Inbox away from: they count as this Inbox folder."""

    roots: set[str] = set()
    if not has_relocations:
        return roots
    for (mappings,) in copy.execute("SELECT mappings_json FROM relocation_runs"):
        try:
            for mapping in json.loads(str(mappings or "[]")):
                if isinstance(mapping, Mapping) and mapping.get("old_root"):
                    roots.add(recording_records.path_key(str(mapping["old_root"])))
        except ValueError:
            continue
    return roots


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError):
        return None


def check_plans(copy: sqlite3.Connection, folder: Path, has_relocations: bool) -> dict[str, int]:
    """Every plan and journal still in progress names this Inbox folder (design 2.4): the active Process run, the
    plan of every finalization not finished, the targeted-evidence plans of every batch not finished, and an
    unfinished relocation. A finished one may name an older folder on purpose and is left alone. Folders are
    compared by the library's path rule; a folder a recorded relocation moved away from counts as this one."""

    allowed = {recording_records.path_key(folder)} | _old_roots(copy, has_relocations)
    found = {"in_progress": 0, "active_runs": 0, "finalization_plans": 0, "targeted_plans": 0, "relocations": 0}

    def named(value: Any, what: str) -> None:
        text = str(value or "").strip()
        if not text:
            return
        found["in_progress"] += 1
        if recording_records.path_key(Path(text).parent) not in allowed:
            raise MoveRefused(f"An unfinished {what} names another Inbox folder, so nothing was moved.")

    active = _read_json(folder / inbox_records.ORCHESTRATION_FOLDER / "active-run.json")
    if isinstance(active, Mapping):
        run = active.get("run") if isinstance(active.get("run"), Mapping) else active
        settings = run.get("scan_settings") if isinstance(run.get("scan_settings"), Mapping) else {}
        found["active_runs"] += 1
        named(settings.get("ledger_path"), "Process run")
    finished = set(review_ledger.FINALIZED_BATCH_STATES)
    for batch_id, status, package in copy.execute("SELECT batch_id, status, package_path FROM batches"):
        if str(status or "") in finished or not package:
            continue
        root = Path(str(package))
        for plan in sorted((root / ".finalization").glob("plan-*.json")):
            data = _read_json(plan)
            if isinstance(data, Mapping):
                found["finalization_plans"] += 1
                named(data.get("ledger_path"), "finalization")
        for plan in sorted((root / ".staging" / "targeted-evidence").glob("render-plan-*.json")):
            data = _read_json(plan)
            if isinstance(data, Mapping):
                found["targeted_plans"] += 1
                named(data.get("ledger_path"), "targeted-evidence render")
    for journal in sorted((folder / ".relocation" / "operations").glob("*/relocation-journal.json")):
        data = _read_json(journal)
        if isinstance(data, Mapping) and str(data.get("phase") or "") not in {"completed", "rolled_back"}:
            found["relocations"] += 1
            plan = _read_json(folder / ".relocation" / "plans" / f"{data.get('operation_id')}.json")
            named(plan.get("ledger_path") if isinstance(plan, Mapping) else "", "relocation")
    return found


def link_counts(connection: sqlite3.Connection, names: Mapping[str, str], folder: Path) -> dict[str, Any]:
    """Every stored generated path counted as inside the Inbox folder, outside it, or missing (none is ever
    rewritten), and how many recordings with a full hash match a raw bin copy (any number is right)."""

    base = recording_records.path_key(folder).rstrip("\\/")
    places: dict[str, dict[str, int]] = {}
    for table, column in GENERATED_PATHS:
        tally = {"inside": 0, "outside": 0, "missing": 0}
        for (value,) in connection.execute(f'SELECT "{column}" FROM "{names.get(table, table)}"'):
            text = str(value or "").strip()
            if not text:
                tally["missing"] += 1
                continue
            key = recording_records.path_key(text)
            inside = key == base or key.startswith(base + os.sep)
            if not Path(text).exists():
                tally["missing"] += 1
            elif inside:
                tally["inside"] += 1
            else:
                tally["outside"] += 1
        places[f"{table}.{column}"] = tally
    try:
        matched = int(connection.execute(
            f"SELECT COUNT(DISTINCT s.source_id) FROM \"{names.get('sources', 'sources')}\" s JOIN recordings r "
            "ON lower(r.content_sha256) = lower(s.content_sha256) WHERE COALESCE(s.content_sha256, '') <> ''"
        ).fetchone()[0])
    except sqlite3.Error:
        matched = 0
    return {"paths": places, "matched_raw_bin_copies": matched}


# The inventory of record files ----------------------------------------------------------------------


def _inventory_skips(relative: Path) -> bool:
    name = relative.name.casefold()
    if name == inbox_records.LEDGER_NAME or name.startswith(inbox_records.LEDGER_NAME + "-") \
            or name.startswith(inbox_records.LEDGER_NAME + ".moved-") \
            or name.startswith(inbox_records.LEDGER_NAME + ".note-"):
        return True
    if relative.parts[:1] == (inbox_records.ORCHESTRATION_FOLDER,) and name in {
            inbox_records.LOCK_NAME, inbox_records.LEFTOVERS_NAME}:
        return True  # the lock the move itself holds, and what the next writer sweeps
    return relative.suffix.casefold() in MEDIA_SUFFIXES


def inventory(folder: Path) -> dict[str, dict[str, Any]]:
    """The relative path, size and SHA-256 of every record file in the Inbox folder (design 4.2, step 4): media,
    the ledger and its note, and the lock are left out."""

    found: dict[str, dict[str, Any]] = {}
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(folder)
        if _inventory_skips(relative):
            continue
        found[relative.as_posix()] = {"size": path.stat().st_size, "sha256": _sha256_file(path)}
    return found


# Mined, before and after -----------------------------------------------------------------------------


def _finished_before(copy: sqlite3.Connection) -> tuple[set[str], dict[str, list[tuple[str, str, int]]]]:
    """What the Raw bin counted as reviewed by the Inbox just before the move: a recording in a finished batch."""

    states = sorted(review_ledger.FINALIZED_BATCH_STATES)
    rows = copy.execute(
        f"""
        SELECT DISTINCT s.content_sha256, s.sampled_sha256, s.size_bytes, l.normalized_path FROM sources s
        JOIN batch_sources bs ON bs.source_id = s.source_id
        JOIN batches b ON b.batch_id = bs.batch_id
        LEFT JOIN source_locations l ON l.source_id = s.source_id
        WHERE b.status IN ({", ".join("?" for _ in states)})
        """, states).fetchall()
    return recording_records.verdicts_from_rows(rows)


def mined(connection: sqlite3.Connection, verdicts: tuple[set[str], dict[str, list[tuple[str, str, int]]]]) -> set[int]:
    """The raw bin recordings these verdicts call reviewed by the Inbox."""

    from . import raw_bin_library  # noqa: PLC0415 - the scan engine imports the front door

    hashes, paths = verdicts
    return {int(row["recording_id"]) for row in raw_bin_library.list_recordings(connection)
            if recording_records.reviewed_by_inbox(row, hashes, paths)}


# The move ----------------------------------------------------------------------------------------------


def _other_workbench_open(records: recording_records.Records) -> bool:
    sessions = records.root / recording_records.SESSIONS
    for lock in sessions.glob("*.lock"):
        if lock.stem != records.session and recording_records._session_alive(records.root, lock.stem):
            return True
    return False


def _ledger_named(settings: Mapping[str, Any]) -> str:
    return str(settings.get("review_ledger_path") or "").strip()


def _profile_ledgers(profiles_dir: Path | str | None, ledger: str) -> dict[str, int]:
    """How many custom profiles name a ledger, and how many of them name another one (design 2.5). None is
    changed."""

    named = other = 0
    for _path, _data, payload in recording_records._custom_profiles(profiles_dir):
        value = str(payload["settings"].get("review_ledger_path") or "").strip()
        if value:
            named += 1
            if not ledger or recording_records.path_key(value) != recording_records.path_key(ledger):
                other += 1
    return {"with_ledger_path": named, "with_another_ledger": other}


def _write_receipt(connection: sqlite3.Connection, receipt: int, **fields: Any) -> None:
    sets = ", ".join(f"{name} = ?" for name in fields)
    connection.execute(f"UPDATE legacy_imports SET {sets} WHERE import_id = ?", (*fields.values(), receipt))


def _new_receipt(connection: sqlite3.Connection, status: str, *, source_sha256: str | None, backup_folder: str,
                 counts: Mapping[str, Any], note: str = "") -> int:
    finished = _now() if status == "complete" else None
    with connection:
        return int(connection.execute(
            "INSERT INTO legacy_imports(source, source_sha256, started_utc, finished_utc, status, counts_json, "
            "backup_folder, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (inbox_records.RECEIPT_SOURCE, source_sha256, _now(), finished, status, json.dumps(dict(counts)),
             backup_folder or None, note or None)).lastrowid)


def _inbox_rows(connection: sqlite3.Connection) -> int:
    return sum(int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
               for table in review_ledger.INBOX_TABLES.values())


def move_ledger(records: recording_records.Records, settings: Mapping[str, Any], *, settings_path: Path | str,
                profiles_dir: Path | str | None, version: str,
                save_folder: Callable[[Path], None]) -> MoveResult:
    """Move the ledger the Workbench's own settings name (``review_ledger_path`` in ``settings.json``; design D3)
    into the library, or finish or undo a move a crash cut off. ``save_folder`` names the Inbox folder in the
    settings (step 11) and raises when it cannot."""

    connection = records.connection()
    latest = inbox_records.receipt(connection)
    if latest is not None and str(latest["status"]) == "complete":
        return MoveResult("nothing", receipt=int(latest["import_id"]))
    ledger_text = _ledger_named(settings)
    profiles = _profile_ledgers(profiles_dir, ledger_text)
    lock_file = records.root / recording_records.MOVE_LOCK
    lock = open(lock_file, "a+b")
    try:
        try:
            recording_records._lock_now(lock)
        except OSError:
            return MoveResult("waiting", "Your Inbox's records move into the library the next time the Workbench "
                                         "starts. Close any other Workbench window, then restart.")
        latest = inbox_records.receipt(connection)
        if latest is not None and str(latest["status"]) == "complete":
            return MoveResult("nothing", receipt=int(latest["import_id"]))
        if not ledger_text:
            if latest is not None and str(latest["status"]) in ("started", "imported", "verified"):
                return MoveResult("waiting", "Your Inbox's records are part-way through moving into the library, "
                                             "but your settings no longer name the old ledger, so the move cannot "
                                             "finish. Nothing was changed.")
            # Design 4.1: "never set up" is a ledger named nowhere. A complete receipt can never be undone, so a
            # settings file that could not be read, or a profile that names a ledger, is not that: it waits.
            if _settings_unreadable(Path(settings_path)):
                return MoveResult("waiting", "Your settings file could not be read, so the Inbox's records were not "
                                             "moved into the library yet. Nothing was changed. Close anything that "
                                             "has it open, then restart.")
            if profiles["with_ledger_path"]:
                return MoveResult("waiting", "A custom profile names an Inbox ledger but your settings do not, so "
                                             "nothing was moved into the library and the Inbox is not available "
                                             "yet. Nothing was changed. If that ledger is no longer used, delete "
                                             "that profile, then restart.", counts={"profiles": profiles})
            receipt = _new_receipt(connection, "complete", source_sha256=None, backup_folder="",
                                   counts={"version": version, "ledger": "none named", "profiles": profiles},
                                   note="nothing to move: no Inbox ledger was named")
            return MoveResult("nothing", counts={"profiles": profiles}, receipt=receipt)
        ledger = Path(ledger_text).expanduser()
        folder = ledger.parent
        if _other_workbench_open(records):
            return MoveResult("waiting", "Your Inbox's records move into the library the next time the Workbench "
                                         "starts. Close any other Workbench window, then restart.")
        if not folder.is_dir():
            return MoveResult("waiting", f"Your Inbox folder cannot be reached, so its records were not moved into "
                                         f"the library yet. Connect the drive that holds it, then restart. "
                                         f"({folder})")
        with inbox_records.ProcessLock(inbox_records.lock_file(folder)) as inbox_lock:
            if not inbox_lock.acquired:
                return MoveResult("waiting", "An Inbox run is still going, so the Inbox's records were not moved "
                                             "into the library yet. Let it finish or close it, then restart.")
            return _move_locked(records, connection, latest, ledger, folder, settings_path=Path(settings_path),
                                profiles_dir=profiles_dir, profiles=profiles, version=version, save_folder=save_folder)
    finally:
        lock.close()


def _settings_unreadable(settings_path: Path) -> bool:
    """A settings file that is there but cannot be read as settings, which a start sees as blank defaults."""

    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        return True
    return not isinstance(payload, dict) or not isinstance(payload.get("settings", {}), dict)


def _held_by_another_program(ledger: Path) -> bool:
    try:
        with ledger.open("rb"):
            return False
    except FileNotFoundError:
        return False
    except OSError:
        return True


def _inbox_was_used_here(folder: Path) -> bool:
    """Anything the Inbox leaves in its folder, whose ledger then counts as lost and not as never made. The lock the
    move itself just took does not count."""

    if any((folder / name).exists() for name in ("history", ".relocation", "queue-index.json",
                                                 "CODEX_REVIEW_QUEUE_PROMPT.md")):
        return True
    if any(folder.glob(f"{inbox_records.LEDGER_NAME}.moved-*")):
        return True
    orchestration = folder / ".orchestration"
    return orchestration.is_dir() and any(path.name != "process.lock" for path in orchestration.iterdir())


def _move_locked(records: recording_records.Records, connection: sqlite3.Connection, latest: sqlite3.Row | None,
                 ledger: Path, folder: Path, *, settings_path: Path, profiles_dir: Path | str | None,
                 profiles: dict[str, int], version: str, save_folder: Callable[[Path], None]) -> MoveResult:
    _step("locked")
    if _held_by_another_program(ledger):
        return MoveResult("waiting", "Your Inbox's ledger is open in another program, so its records were not moved "
                                     "into the library yet. Close that program, then restart.")
    status = str(latest["status"]) if latest is not None else ""
    if status == "started":
        # Cut off before or during the import, which is one transaction: nothing was imported.
        with connection:
            _write_receipt(connection, int(latest["import_id"]), status="restored", finished_utc=_now(),
                           note="interrupted before the import was saved; started again")
    elif status in ("imported", "verified"):
        return _resume(records, connection, latest, ledger, folder, version=version, save_folder=save_folder)
    if not ledger.exists():
        if (folder / "batches").is_dir():
            return MoveResult("refused", "Your Inbox folder has batches but no ledger file, so nothing was moved. "
                                         f"Put the ledger back in {folder}, then restart.")
        if _inbox_was_used_here(folder):
            return MoveResult("waiting", "Your settings name an Inbox ledger that is not there, so its records were "
                                         f"not moved into the library yet. Put it back in {folder}, then restart.")
        receipt = _new_receipt(connection, "complete", source_sha256=None, backup_folder="",
                               counts={"version": version, "ledger": "not there", "profiles": profiles},
                               note="nothing to move: the named ledger file is not there")
        return MoveResult("nothing", counts={"profiles": profiles}, receipt=receipt)
    if not inbox_records.is_database(ledger):
        return MoveResult("refused", "Your Inbox's ledger was already moved into a library, but this library does "
                                     "not hold its records (was an older copy of the library put back?). Nothing "
                                     "was changed. HOW_TO_RESTORE.txt in the library's backups\\migrations folder "
                                     "says how to put things back.")
    if _inbox_rows(connection) or inbox_records.registered_folder(connection) is not None:
        return MoveResult("refused", "The library already holds Inbox records from a different ledger, so this "
                                     "ledger was not moved. Nothing was changed.")
    return _fresh_move(records, connection, ledger, folder, settings_path=settings_path, profiles_dir=profiles_dir,
                       profiles=profiles, version=version, save_folder=save_folder)


def _settle(ledger: Path) -> bool:
    """Step 3: open the ledger once the normal way, so SQLite finishes or undoes what a crash left half-written
    beside it (it writes only then, as any open does), and close it. True when no side file is left."""

    inbox_records.settle_file(ledger)
    for suffix in ("-journal", "-wal", "-shm"):
        side = ledger.with_name(ledger.name + suffix)
        # An empty journal or log holds no change, and SQLite leaves an empty journal where it is.
        if side.exists() and (suffix == "-shm" or side.stat().st_size > 0):
            return False
    return True


def _refused_before_any_copy(connection: sqlite3.Connection, source_sha: str, counts: dict[str, Any],
                             reason: str) -> MoveResult:
    """A ledger that cannot be moved leaves the same one receipt at every start, and no backup: nothing changed."""

    latest = inbox_records.receipt(connection)
    if (latest is not None and str(latest["status"]) == "restored" and latest["source_sha256"] == source_sha
            and str(latest["note"] or "") == reason[:500]):
        receipt = int(latest["import_id"])
    else:
        receipt = _new_receipt(connection, "restored", source_sha256=source_sha, backup_folder="", counts=counts,
                               note=reason[:500])
        with connection:
            _write_receipt(connection, receipt, finished_utc=_now())
    return MoveResult("restored", inbox_records.MOVE_UNDONE.format(reason=reason[:500]), counts, "", receipt)


def _fresh_move(records: recording_records.Records, connection: sqlite3.Connection, ledger: Path, folder: Path, *,
                settings_path: Path, profiles_dir: Path | str | None, profiles: dict[str, int], version: str,
                save_folder: Callable[[Path], None]) -> MoveResult:
    try:
        settled = _settle(ledger)
    except sqlite3.OperationalError as exc:
        return MoveResult("waiting", "Your Inbox's ledger could not be opened just now, so its records were not moved "
                                     f"into the library yet. Restart the Workbench to try again. ({_reason(exc)})")
    except sqlite3.DatabaseError as exc:
        return MoveResult("refused", "Your Inbox's ledger is damaged, so its records were not moved into the library "
                                     f"and the Inbox is not available yet. Nothing was changed. ({_reason(exc)})")
    if not settled:
        return MoveResult("waiting", "A half-written change is still beside your Inbox's ledger, so its records "
                                     "were not moved into the library yet. Restart the Workbench to try again.")
    _step("settled")
    source_sha = _sha256_file(ledger)
    counts: dict[str, Any] = {"version": version, "profiles": profiles}
    # The same checks run again on the checked copy; here they keep a ledger that can never move from leaving a new
    # copy of the whole library behind at every start.
    try:
        original = inbox_records.read_only_file(ledger)
        try:
            check_copy(original, folder)
        finally:
            original.close()
    except (MoveRefused, sqlite3.DatabaseError) as exc:
        return _refused_before_any_copy(connection, source_sha, counts, _reason(exc))
    backup_folder = recording_records._new_backup_folder(records.root, BACKUP_LABEL)
    receipt = _new_receipt(connection, "started", source_sha256=source_sha, backup_folder=str(backup_folder),
                           counts=counts)
    try:
        _step("receipt")
        copy_path, inventory_before = _back_up(records, connection, ledger, folder, backup_folder, settings_path,
                                                profiles_dir)
        _step("backed_up")
        copy = inbox_records.read_only_file(copy_path)
        try:
            counts["checks"] = check_copy(copy, folder)
            present = [table for table in review_ledger.INBOX_TABLES if table in _tables(copy)]
            before = measure(copy, {}, copy, present)
            sequences = _sequences(copy, {})
            mined_before = mined(connection, _finished_before(copy))
            counts["orphaned_batches"] = _orphaned_batches(copy, folder)
            counts["finalization_journals"] = _journal_counts(copy)
        finally:
            copy.close()
        _step("checked")
        counts["before"] = before
        _import(connection, copy_path, folder, present, before, sequences, receipt, counts)
    except BaseException as exc:
        if connection.in_transaction:
            connection.rollback()
        _detach(connection)
        with connection:
            _write_receipt(connection, receipt, status="restored", finished_utc=_now(), note=_reason(exc),
                           counts_json=json.dumps(counts))
        if not isinstance(exc, Exception):
            raise
        return MoveResult("restored", _restored_message(exc), counts, str(backup_folder), receipt)
    return _after_import(records, connection, receipt, ledger, folder, backup_folder, copy_path, present, before,
                         inventory_before, mined_before, counts, version=version, save_folder=save_folder)


def _reason(exc: BaseException) -> str:
    return (str(exc) or type(exc).__name__)[:500]


def _restored_message(exc: BaseException) -> str:
    return inbox_records.MOVE_UNDONE.format(reason=_reason(exc))


def _back_up(records: recording_records.Records, connection: sqlite3.Connection, ledger: Path, folder: Path,
             backup_folder: Path, settings_path: Path, profiles_dir: Path | str | None) -> tuple[Path, dict[str, Any]]:
    """Step 4. Raises when any copy does not check out."""

    original = inbox_records.read_only_file(ledger)
    try:
        ledger_counts = safe_write.checked_copy(original, backup_folder / LEDGER_COPY)
    finally:
        original.close()
    library_counts = safe_write.checked_copy(connection, backup_folder / recording_records.DATABASE_NAME)
    manifest: dict[str, Any] = {
        LEDGER_COPY: _sha256_file(backup_folder / LEDGER_COPY),
        recording_records.DATABASE_NAME: _sha256_file(backup_folder / recording_records.DATABASE_NAME),
        "ledger_source": str(ledger), "library_source": str(recording_records.database_path(records.root)),
        "inbox_folder": str(folder), "ledger_tables": ledger_counts, "library_tables": library_counts,
    }
    if settings_path.is_file():
        data = settings_path.read_bytes()
        safe_write.write_bytes(backup_folder / "settings.json", data)
        manifest["settings.json"] = _sha256_file(backup_folder / "settings.json")
        if manifest["settings.json"] != hashlib.sha256(data).hexdigest():
            raise RuntimeError("The backup of settings.json did not check out.")
        manifest["settings_source"] = str(settings_path)
    profiles = recording_records._custom_profiles(profiles_dir)
    if profiles:
        manifest["profiles_source"] = str(profiles_dir or "")
        for path, data, _payload in profiles:
            kept = backup_folder / "profiles" / path.name
            safe_write.write_bytes(kept, data)
            manifest[f"profiles/{path.name}"] = _sha256_file(kept)
            if manifest[f"profiles/{path.name}"] != hashlib.sha256(data).hexdigest():
                raise RuntimeError("The backup of a profile did not check out.")
    found = inventory(folder)
    safe_write.write_json(backup_folder / INVENTORY, {"inbox_folder": str(folder), "files": found})
    manifest[INVENTORY] = _sha256_file(backup_folder / INVENTORY)
    safe_write.write_json(backup_folder / "BACKUP_MANIFEST.json", manifest)
    earlier = _earlier_library(records, backup_folder)
    safe_write.write_text(backup_folder / "HOW_TO_RESTORE.txt", HOW_TO_RESTORE.format(
        when=datetime.now().strftime("%Y-%m-%d %H:%M"), library=records.root, folder=folder,
        settings=settings_path.parent,
        earlier_library=EARLIER_LIBRARY.format(folder=earlier) if earlier else NO_EARLIER_LIBRARY))
    return backup_folder / LEDGER_COPY, found


def _earlier_library(records: recording_records.Records, backup_folder: Path) -> Path | None:
    """The newest copy of the library from before the Inbox's records were in it, which a version before this move can
    open: the backup the library's own upgrade took (``recording_records.upgrade``). Later structure steps (264) took
    backups too, but those already have the Inbox's tables, so they are not it."""

    found = []
    for path in sorted(backup_folder.parent.glob("*-schema-*-to-*")):
        step = re.search(r"-schema-(\d+)-to-(\d+)(?:-\d+)?$", path.name)
        if step and int(step.group(1)) < INBOX_STRUCTURE <= int(step.group(2)) \
                and (path / recording_records.DATABASE_NAME).is_file():
            found.append(path)
    return found[-1] if found else None


def _orphaned_batches(copy: sqlite3.Connection, folder: Path) -> dict[str, int]:
    """F9: unfinished batches whose folder is outside the Inbox folder (an older command-line Prepare's). They are
    counted, never moved."""

    base = recording_records.path_key(folder).rstrip("\\/")
    finished = set(review_ledger.FINALIZED_BATCH_STATES)
    outside = unfinished = 0
    for status, package in copy.execute("SELECT status, package_path FROM batches"):
        if str(status or "") in finished:
            continue
        unfinished += 1
        key = recording_records.path_key(str(package or ""))
        if package and not (key == base or key.startswith(base + os.sep)):
            outside += 1
    return {"unfinished": unfinished, "unfinished_outside_inbox_folder": outside}


def _journal_counts(copy: sqlite3.Connection) -> dict[str, int]:
    """F10: batches whose folder holds more than one finalization journal (recovery follows the recorded one)."""

    many = recorded = 0
    for (package,) in copy.execute("SELECT package_path FROM batches"):
        if not package:
            continue
        journals = list((Path(str(package)) / ".finalization").glob("journal-*.json"))
        if len(journals) > 1:
            many += 1
    recorded = int(copy.execute("SELECT COUNT(*) FROM finalization_runs").fetchone()[0])
    return {"batches_with_more_than_one_journal": many, "recorded_finalizations": recorded}


def _detach(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("DETACH DATABASE ledger_copy")
    except sqlite3.Error:
        pass


def _import(connection: sqlite3.Connection, copy_path: Path, folder: Path, present: list[str],
            before: dict[str, Any], sequences: dict[str, int], receipt: int, counts: dict[str, Any]) -> None:
    """Step 6: every table copied with its own keys, the counters carried across, the Inbox folder registered,
    checks 2 to 4 inside the same transaction, and the receipt set to "imported" — all or nothing."""

    names = review_ledger.INBOX_TABLES
    # SQLite cannot attach inside a transaction; the copy is attached by its plain path and only read.
    connection.execute("ATTACH DATABASE ? AS ledger_copy", (str(copy_path),))
    try:
        connection.execute("BEGIN IMMEDIATE")
        for table in present:
            columns = ", ".join(f'"{name}"' for name in _copy_columns(connection, table))
            connection.execute(f'INSERT INTO main."{names[table]}" ({columns}) SELECT {columns} '
                               f'FROM ledger_copy."{table}"')
        for table, seq in sequences.items():
            name = names[table]
            connection.execute("UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = ?", (seq, name))
            if not connection.execute("SELECT 1 FROM sqlite_sequence WHERE name = ?", (name,)).fetchone():
                connection.execute("INSERT INTO sqlite_sequence(name, seq) VALUES (?, ?)", (name, seq))
        now = recording_records._stamp()
        connection.execute(
            "INSERT INTO roots(kind, path, path_key, first_seen_utc, last_seen_utc) VALUES (?, ?, ?, ?, ?)",
            (inbox_records.ROOT_KIND, str(folder), recording_records.path_key(folder), now, now))
        problems = _compare(connection, present, before, sequences)
        if problems:
            raise MoveRefused("; ".join(problems))
        counts["links"] = link_counts(connection, names, folder)
        _write_receipt(connection, receipt, status="imported", counts_json=json.dumps(counts))
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        _detach(connection)


def _copy_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in connection.execute(f'PRAGMA ledger_copy.table_info("{table}")')]


def _compare(connection: sqlite3.Connection, present: list[str], before: dict[str, Any],
             sequences: dict[str, int]) -> list[str]:
    """Checks 2 to 4 (design 4.3): counts, state counts and fingerprints equal on both sides, every link of the
    Inbox's tables resolves, every counter carried across."""

    names = review_ledger.INBOX_TABLES
    problems: list[str] = []
    after = _measure_library(connection, present)
    for table in present:
        if after[table] != before[table]:
            problems.append(f"the {table} records differ after the copy")
    if inbox_records.link_problems(connection):
        problems.append("a link between the Inbox's records does not resolve")
    carried = _sequences(connection, names)
    for table, seq in sequences.items():
        if carried.get(table, 0) < seq:
            problems.append(f"the {table} counter was not carried across")
    return problems


def _measure_library(connection: sqlite3.Connection, present: list[str]) -> dict[str, Any]:
    """The library's ``inbox_`` tables measured with the columns and keys of the attached ledger copy, or, once it
    is detached, of the checked copy in the backup folder (``_after_import`` reattaches it)."""

    names = review_ledger.INBOX_TABLES
    tables: dict[str, Any] = {}
    for table in present:
        columns = [str(row[1]) for row in connection.execute(f'PRAGMA ledger_copy.table_info("{table}")')]
        keyed = sorted((int(row[5]), str(row[1])) for row in connection.execute(
            f'PRAGMA ledger_copy.table_info("{table}")') if int(row[5]))
        rows, digest = fingerprint(connection, names[table], columns, [name for _order, name in keyed])
        entry: dict[str, Any] = {"rows": rows, "fingerprint": digest}
        if table in STATE_COLUMNS:
            entry["states"] = _state_counts(connection, names[table], STATE_COLUMNS[table])
        tables[table] = entry
    return tables


def _after_import(records: recording_records.Records, connection: sqlite3.Connection, receipt: int, ledger: Path,
                  folder: Path, backup_folder: Path, copy_path: Path, present: list[str], before: dict[str, Any],
                  inventory_before: dict[str, Any], mined_before: set[int] | None, counts: dict[str, Any], *,
                  version: str, save_folder: Callable[[Path], None]) -> MoveResult:
    """Steps 7 to 12, from a saved import (a fresh move, or a start after a crash left the receipt "imported")."""

    try:
        _step("imported")
        _check_after(connection, copy_path, folder, present, before, inventory_before, mined_before, counts)
        _step("rechecked")
        _original_unchanged(ledger, copy_path, present)
        _step("original_unchanged")
        moved = _moved_name(folder, planned=False)
        counts["moved_name"] = moved
        with connection:
            for statement in review_ledger.library_guard_statements():
                connection.execute(statement)
            _write_receipt(connection, receipt, status="verified", counts_json=json.dumps(counts))
        _step("guarded")
    except BaseException as exc:
        if connection.in_transaction:
            connection.rollback()
        undone = _undo_import(connection, receipt, exc, counts)
        if not isinstance(exc, Exception):
            raise
        if not undone:
            return MoveResult("waiting", inbox_records.MOVE_UNFINISHED, counts, str(backup_folder), receipt)
        return MoveResult("restored", _restored_message(exc), counts, str(backup_folder), receipt)
    return _finish(connection, receipt, ledger, folder, backup_folder, counts, version=version,
                   save_folder=save_folder)


def _check_after(connection: sqlite3.Connection, copy_path: Path, folder: Path, present: list[str],
                 before: dict[str, Any], inventory_before: dict[str, Any], mined_before: set[int] | None,
                 counts: dict[str, Any]) -> None:
    """Check 5 (design 4.3), after the commit."""

    if [str(row[0]) for row in connection.execute("PRAGMA integrity_check")] != ["ok"]:
        raise MoveRefused("The library did not pass SQLite's damage check after the import.")
    connection.execute("ATTACH DATABASE ? AS ledger_copy", (str(copy_path),))
    try:
        problems = _compare(connection, present, before, _sequences_of_copy(connection))
        if mined_before is None:
            mined_before = mined(connection, _finished_before_attached(connection))
    finally:
        _detach(connection)
    if problems:
        raise MoveRefused("; ".join(problems))
    changed = [name for name, entry in inventory(folder).items() if inventory_before.get(name) != entry]
    gone = [name for name in inventory_before if not (folder / name).is_file()]
    if changed or gone:
        raise MoveRefused(f"{len(changed) + len(gone)} record file(s) in the Inbox folder changed during the move.")
    mined_after = mined(connection, recording_records.inbox_verdicts(connection))
    if not mined_before <= mined_after:
        raise MoveRefused(f"{len(mined_before - mined_after)} recording(s) the Raw bin showed as mined by the Inbox "
                          "would no longer show it.")
    counts["mined"] = {"before": len(mined_before), "after": len(mined_after),
                       "wider_by_own_finished_state": len(mined_after - mined_before)}
    counts["record_files"] = len(inventory_before)


def _sequences_of_copy(connection: sqlite3.Connection) -> dict[str, int]:
    found: dict[str, int] = {}
    try:
        for name, seq in connection.execute("SELECT name, seq FROM ledger_copy.sqlite_sequence"):
            if str(name) in NUMBERED_TABLES:
                found[str(name)] = int(seq or 0)
    except sqlite3.Error:
        pass
    return found


def _finished_before_attached(connection: sqlite3.Connection) -> tuple[set[str], dict[str, list[tuple[str, str, int]]]]:
    states = sorted(review_ledger.FINALIZED_BATCH_STATES)
    rows = connection.execute(
        f"""
        SELECT DISTINCT s.content_sha256, s.sampled_sha256, s.size_bytes, l.normalized_path FROM ledger_copy.sources s
        JOIN ledger_copy.batch_sources bs ON bs.source_id = s.source_id
        JOIN ledger_copy.batches b ON b.batch_id = bs.batch_id
        LEFT JOIN ledger_copy.source_locations l ON l.source_id = s.source_id
        WHERE b.status IN ({", ".join("?" for _ in states)})
        """, states).fetchall()
    return recording_records.verdicts_from_rows(rows)


def _original_unchanged(ledger: Path, copy_path: Path, present: list[str]) -> None:
    """Step 8: the original, read without writing, still has the copy's every row."""

    copy = inbox_records.read_only_file(copy_path)
    original = inbox_records.read_only_file(ledger)
    try:
        if measure(original, {}, copy, present) != measure(copy, {}, copy, present):
            raise MoveRefused("Something wrote to the Inbox's ledger during the move.")
    finally:
        original.close()
        copy.close()


def _undo_import(connection: sqlite3.Connection, receipt: int, exc: BaseException, counts: dict[str, Any]) -> bool:
    """Design 4.5: the imported rows deleted again in one transaction, before the library's rules for the Inbox
    are on (so a plain delete is allowed), and the registered folder with them. No library file is copied back.
    False when even that did not work: the receipt stays "imported" and the next start checks again."""

    names = review_ledger.INBOX_TABLES
    try:
        connection.execute("BEGIN IMMEDIATE")
        for trigger in review_ledger.GUARD_TRIGGERS:
            connection.execute(f"DROP TRIGGER IF EXISTS {trigger}")
        for table in reversed(list(names)):
            connection.execute(f"DELETE FROM {names[table]}")
        connection.execute("DELETE FROM sqlite_sequence WHERE name IN (" + ", ".join(
            "?" for _ in NUMBERED_TABLES) + ")", [names[table] for table in NUMBERED_TABLES])
        connection.execute("DELETE FROM roots WHERE kind = ?", (inbox_records.ROOT_KIND,))
        _write_receipt(connection, receipt, status="restored", finished_utc=_now(), note=_reason(exc),
                       counts_json=json.dumps(counts))
        connection.commit()
    except sqlite3.Error:
        if connection.in_transaction:
            connection.rollback()
        return False
    return True


def _moved_name(folder: Path, *, planned: bool) -> str:
    """The name the original ledger keeps beside its note: ``review-ledger.sqlite.moved-<date>.sqlite``, with a
    number when that name is taken."""

    stem = f"{inbox_records.LEDGER_NAME}.moved-{datetime.now().strftime('%Y-%m-%d')}"
    for number in range(1, 1000):
        name = f"{stem}.sqlite" if number == 1 else f"{stem}-{number}.sqlite"
        if planned or not (folder / name).exists():
            return name
    raise RuntimeError(f"No free name for the moved ledger in {folder}.")


def _finish(connection: sqlite3.Connection, receipt: int, ledger: Path, folder: Path, backup_folder: Path | str,
            counts: dict[str, Any], *, version: str, save_folder: Callable[[Path], None]) -> MoveResult:
    """Steps 10 to 12, from a "verified" receipt."""

    moved = str(counts.get("moved_name") or _moved_name(folder, planned=False))
    if inbox_records.is_database(ledger):
        note = folder / f"{inbox_records.LEDGER_NAME}.note-{os.getpid()}.tmp"
        try:
            safe_write.write_text(note, NOTE.format(date=datetime.now().strftime("%Y-%m-%d"), version=version,
                                                    moved=moved))
            safe_write.replace_file(ledger, note, moved)
        except (OSError, safe_write.FileStepRefused) as exc:
            try:
                safe_write.remove(note)
            except OSError:
                pass
            return MoveResult("waiting", "Your Inbox's records are in the library, but its old ledger file is still "
                                         f"open in another program, so the move finishes at the next start. ({exc})",
                              counts, str(backup_folder), receipt)
    elif not (folder / moved).is_file():
        return MoveResult("refused", "The ledger's note is in place but the moved ledger is not beside it, so the "
                                     "move was not finished. Nothing else was changed.", counts, str(backup_folder),
                          receipt)
    _step("swapped")
    try:
        save_folder(folder)
    except (OSError, ValueError, RuntimeError) as exc:
        return MoveResult("waiting", f"Your Inbox's records are in the library, but the settings could not name its "
                                     f"folder yet, so the move finishes at the next start. ({exc})", counts,
                          str(backup_folder), receipt)
    _step("settings")
    with connection:
        _write_receipt(connection, receipt, status="complete", finished_utc=_now(), counts_json=json.dumps(counts))
    _step("complete")
    if backup_folder:
        try:
            safe_write.write_json(Path(backup_folder) / RECEIPT_COPY, {
                "receipt": receipt, "status": "complete", "source_sha256": _receipt_sha(connection, receipt),
                "counts": counts})
        except OSError:
            pass  # the receipt in the library is the record; this copy is a convenience
    return MoveResult("moved", "", counts, str(backup_folder), receipt)


def _receipt_sha(connection: sqlite3.Connection, receipt: int) -> str:
    row = connection.execute("SELECT source_sha256 FROM legacy_imports WHERE import_id = ?", (receipt,)).fetchone()
    return str(row[0] or "") if row else ""


def _resume(records: recording_records.Records, connection: sqlite3.Connection, latest: sqlite3.Row, ledger: Path,
            folder: Path, *, version: str, save_folder: Callable[[Path], None]) -> MoveResult:
    """Design 4.6: a start after a crash with the receipt at "imported" checks again (and undoes the import when
    the checks fail); at "verified" it finishes the swap and the settings."""

    receipt = int(latest["import_id"])
    backup_folder = Path(str(latest["backup_folder"] or ""))
    try:
        counts = json.loads(str(latest["counts_json"] or "{}"))
    except ValueError:
        counts = {}
    copy_path = backup_folder / LEDGER_COPY
    if str(latest["status"]) == "verified":
        if inbox_records.is_database(ledger):
            try:
                copy = inbox_records.read_only_file(copy_path)
                try:
                    present = [table for table in review_ledger.INBOX_TABLES if table in _tables(copy)]
                finally:
                    copy.close()
                _original_unchanged(ledger, copy_path, present)
            except MoveRefused as exc:
                return MoveResult("refused", "The Inbox's records are in the library, but its old ledger changed since, "
                                             "so the move was not finished and the Inbox is not available. Nothing "
                                             f"else was changed. HOW_TO_RESTORE.txt in {backup_folder} says how to go "
                                             f"back. ({_reason(exc)})", counts, str(backup_folder), receipt)
            except (OSError, sqlite3.Error) as exc:
                return MoveResult("waiting", "The Inbox's records are in the library, but the last check before "
                                             "finishing the move could not run, so it finishes at a later start. "
                                             f"The backup is in {backup_folder}. ({_reason(exc)})", counts,
                                  str(backup_folder), receipt)
        return _finish(connection, receipt, ledger, folder, backup_folder, counts, version=version,
                       save_folder=save_folder)
    try:
        copy = inbox_records.read_only_file(copy_path)
        try:
            present = [table for table in review_ledger.INBOX_TABLES if table in _tables(copy)]
            before = measure(copy, {}, copy, present)
        finally:
            copy.close()
        inventory_before = (_read_json(backup_folder / INVENTORY) or {}).get("files") or {}
    except (OSError, sqlite3.Error, AttributeError) as exc:
        if not _undo_import(connection, receipt, exc, counts):
            return MoveResult("waiting", inbox_records.MOVE_UNFINISHED, counts, str(backup_folder), receipt)
        return MoveResult("restored", _restored_message(exc), counts, str(backup_folder), receipt)
    return _after_import(records, connection, receipt, ledger, folder, backup_folder, copy_path, present, before,
                         inventory_before, None, counts, version=version, save_folder=save_folder)
