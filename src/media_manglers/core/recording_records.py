"""Recording records (the library): the one front door to what the app remembers (242).

Every screen and feature asks this module what the app remembers about a recording or a run. It keeps
that in one SQLite database in the app's local data folder, the raw bin library's own file, backed up
once a day. Nothing else opens that database:

- ``raw_bin_library`` is this library's scan engine. It keeps its scan, guess and idle code and the SQL
  for its own tables, and opens the database only through ``connect`` here.
- Every other module asks a function here: the player's waveform lookups (``current_copy``), the AI Video
  Editor's recording picker (``list_recordings``), the Raw bin page (``connect``, ``last_scan_finished``).

The database's structure moves up one step at a time (``SCHEMA_STEPS``). Before a step changes a library
that already holds data, the whole library is copied with SQLite's own backup call into
``backups/migrations``, which the daily backup's pruning never touches; the step runs in one
transaction and is checked before it is kept. A library a newer build has already moved on is refused
for writing, never moved back.

Review Media Inbox keeps its own ledger until it moves in (224, Wave B2). Until then the library reads
it here, read-only (``inbox_reviewed``, ``inbox_run_outcomes``), through the Inbox's own store
(``inbox_records.connect_read_only``), which never makes, moves up or writes a ledger.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import errno
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any, Callable, Iterable
import uuid

from .review_ledger import FINALIZED_BATCH_STATES, INBOX_TABLES as INBOX_TABLE_NAMES, library_schema_statements
from .user_folders import APP_FOLDER, local_data_root, recordings_drive_problem

# 2: the raw bin's tables as Wave 6 made them (220). 3: Wave A1 (242, 243): the structure steps, the
# registered folders and every run with each recording's outcome. 4: Wave A2 (244): confirmed contents,
# where each copy came from, the Never-use and Bugs-done marks, and the stopped run Continue picks up. 5: Wave
# B2b (224): Review Media Inbox's records, its ledger's tables under names that start with ``inbox_``. 6: Wave
# C1 (264): speech facts, each recording's measured moments and who answered which track is its narration. 7: Wave
# C2 (242, H6 and M2): an index of the AI Video Editor's projects and versions, which the project files keep authority over.
SCHEMA_VERSION = 7
LIBRARY_ROOT_ENV = "MEDIA_MANGLERS_LIBRARY_ROOT"
# The Workbench's own local app data override (media_manglers_workbench.settings.LOCALAPPDATA_OVERRIDE_ENV).
WORKBENCH_LOCALAPPDATA_ENV = "MEDIA_MANGLERS_WORKBENCH_LOCALAPPDATA"
DATABASE_NAME = "raw-bin-library.sqlite"
BACKUP_KEEP = 14
MIGRATION_BACKUPS = "migrations"
# SQLite waits this long for another writer (a scan) before giving up, so a tag saved while a scan runs
# waits instead of failing.
BUSY_TIMEOUT_MS = 30_000
BUILTIN_LABELS = ("Bug report", "YouTube", "Short", "B-roll", "Training")
INBOX_TABLES = tuple(INBOX_TABLE_NAMES.values())
# The tables a structure step must never lose a row of.
KEPT_TABLES = ("recordings", "locations", "labels", "recording_labels", "scan_runs", "marks", "resume_points",
               *INBOX_TABLES, "voice_measures", "voice_measure_tracks", "voice_decisions", "narration_answers",
               "editor_projects", "editor_versions")
# What each version must have once its step is taken (244): a step is only kept when it is all there.
EXPECTED_STRUCTURE = {
    "runs": ("run_id", "state"), "run_items": ("outcome",), "legacy_imports": ("status",),
    "contents": ("content_sha256",), "locations": ("registered_by",),
    "marks": ("kind", "recording_id", "old_key", "outcome", "mark_date", "import_key", "cleared_utc"),
    "resume_points": ("feature", "folder", "recordings_json", "tracks_json", "cleared_utc"),
    # 224 (Wave B2b): the Inbox's tables, each with its key and the columns the move checks it by.
    "inbox_metadata": ("key", "value"), "inbox_legacy_reviews": ("ledger_id", "status"),
    "inbox_sources": ("source_id", "provisional_identity", "stable_identity", "lifecycle_state"),
    "inbox_source_locations": ("location_id", "normalized_path"), "inbox_batches": ("batch_id", "status"),
    "inbox_batch_sources": ("batch_id", "source_id", "state"), "inbox_attempts": ("attempt_id", "status"),
    "inbox_findings": ("finding_id", "status"), "inbox_lifecycle_events": ("event_id", "event_type"),
    "inbox_final_results": ("result_id", "disposition"), "inbox_finalization_runs": ("plan_sha256", "journal_path"),
    "inbox_retention_records": ("plan_sha256", "history_path"), "inbox_relocation_runs": ("operation_id", "status"),
    # 264 (Wave C1): speech facts.
    "voice_measures": ("measure_id", "content_sha256", "recording_id", "size_bytes", "modified_ns",
                       "activity_rule_version", "measured_by"),
    "voice_measure_tracks": ("measure_id", "track", "silent", "moments_json", "listened"),
    "voice_decisions": ("measure_id", "voice_rule_version", "roles_key", "preferred_key", "status", "chosen_track",
                        "decided_by", "tracks_json"),
    "narration_answers": ("answer_id", "content_sha256", "recording_id", "track", "answered_by", "cleared_utc"),
    # 242 (Wave C2): the AI Video Editor's projects and versions, indexed from their own files.
    "editor_projects": ("project_id", "root_id", "relative_path", "content_sha256", "recording_id", "edit_of",
                        "link_state", "bound_utc", "bound_how"),
    "editor_versions": ("project_id", "version", "created", "editor_label", "preview_passed", "final_passed",
                        "exported", "documents_json", "state", "checked_utc"),
}


# Privacy classes (242): what may leave this computer, and how. Every table of the library has one; a new
# table must be given one before it ships (tests/test_records_privacy.py).
SHAREABLE = "shareable"  # versions and counts: may appear in any export or log
PRIVATE = "private to this PC"  # paths, names, hashes: stay here; exported only where the raw bin's own
#                                 CSV/JSON export always did (its columns are raw_bin_library.EXPORT_FIELDS)
PERSONAL = "personal"  # what the operator ran and decided: never exported, packaged, shown to an agent or logged
TABLE_PRIVACY = {
    "schema_metadata": SHAREABLE,
    "schema_steps": PRIVATE,
    "recordings": PRIVATE,
    "locations": PRIVATE,
    "labels": PRIVATE,
    "recording_labels": PRIVATE,
    "scan_runs": PRIVATE,
    "roots": PRIVATE,
    "legacy_imports": PRIVATE,
    "runs": PERSONAL,
    "run_items": PERSONAL,
    "run_events": PERSONAL,
    "run_products": PERSONAL,
    "contents": PRIVATE,
    # 244: what Find my bug reports and the player decided about each recording, and the stopped run.
    "marks": PERSONAL,
    "resume_points": PERSONAL,
    # 224 (Wave B2b, design 3.7): Review Media Inbox's records. What the operator said and what was decided (the
    # findings and the accepted final results) is personal; the rest holds paths, hashes and folder names.
    "inbox_metadata": SHAREABLE,
    "inbox_legacy_reviews": PRIVATE,
    "inbox_sources": PRIVATE,
    "inbox_source_locations": PRIVATE,
    "inbox_batches": PRIVATE,
    "inbox_batch_sources": PRIVATE,
    "inbox_attempts": PRIVATE,
    "inbox_findings": PERSONAL,
    "inbox_lifecycle_events": PRIVATE,
    "inbox_final_results": PERSONAL,
    "inbox_finalization_runs": PRIVATE,
    "inbox_retention_records": PRIVATE,
    "inbox_relocation_runs": PRIVATE,
    # 264 (Wave C1, design 3.3): when the operator spoke on each track, and which track they say is theirs. Never
    # the words heard. ``speech_facts`` is the only code that reads or writes them, apart from ``merge_speech_facts``.
    "voice_measures": PERSONAL,
    "voice_measure_tracks": PERSONAL,
    "voice_decisions": PERSONAL,
    "narration_answers": PERSONAL,
    # 242 (Wave C2, design 3.3): where each edit lives (relative to a registered folder) and which recording it is of.
    # The project files stay the authority; this only indexes them.
    "editor_projects": PRIVATE,
    "editor_versions": PRIVATE,
}


class LibraryTooNew(ValueError):
    """The library was moved on by a newer build of the app; this build never moves it back."""


# Windows' own numbers for a drive that could not be read: not ready, a read error (CRC), an I/O device error, a
# device that is not connected, and a network path or network that cannot be reached.
_DRIVE_ERRORS = {21, 23, 53, 59, 64, 67, 1117, 1167, 1231, 1232}
_HELD_ERRORS = {32, 33}


def plain_problem(exc: BaseException, root: Path | None = None) -> tuple[str, str]:
    """Why the library could not be opened, in plain words, and what to do next (224, Wave B2a, 5d).

    The common refusals each have their own words; the raw text belongs in the log. Anything else is said as
    it came, with "" for the next step, so the caller says its usual one."""

    text = str(exc).casefold()
    winerror = getattr(exc, "winerror", None)
    number = getattr(exc, "errno", None)
    folder = Path(root) if root is not None else library_root()
    if isinstance(exc, LibraryTooNew):
        return ("A newer version of the Workbench has updated your library, so this version cannot use it.",
                "Use the newer version of the Workbench; this version does not change your library.")
    if isinstance(exc, sqlite3.DatabaseError) and any(
            words in text for words in ("not a database", "malformed", "encrypted")):
        return ("Your library file is damaged, so it cannot be read.",
                "Starting again will not fix this. The app keeps daily copies in its backups folder: "
                f"{folder / 'backups'}")
    if "database is locked" in text or "database table is locked" in text or winerror in _HELD_ERRORS or (
            number in (errno.EDEADLK, errno.EACCES) and winerror is None and "lock" in text):
        return ("Your library file is locked by another program, so it could not be opened.",
                "Close the other program or Workbench window that has it open, or wait a moment, then start the "
                "Workbench again.")
    if "disk i/o error" in text or winerror in _DRIVE_ERRORS or number == errno.EIO or (
            isinstance(exc, OSError) and folder.anchor and not Path(folder.anchor).exists()):
        return ("The drive that holds your library could not be read.",
                "Check that the drive is connected and working, then start the Workbench again.")
    if isinstance(exc, PermissionError) or winerror == 5 or "unable to open database file" in text:
        return ("Windows refused access to your library file.",
                "Check that your Windows account can open the library folder, then start the Workbench again: "
                f"{folder}")
    return str(exc) or type(exc).__name__, ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def path_key(path: Path | str) -> str:
    """The library's one spelling of a path: absolute, and in the case the system compares names in."""

    return os.path.normcase(os.path.abspath(str(path)))


# Where it lives ----------------------------------------------------------------------------------


def library_root() -> Path:
    """Where the library lives: the library override, else the Workbench's own local app data folder
    (its override moves the library too, so a test or the build's start-up check that points the
    Workbench elsewhere never opens the operator's own library), else the system's."""

    override = os.environ.get(LIBRARY_ROOT_ENV, "").strip()
    if override:
        return Path(override)
    workbench_local = os.environ.get(WORKBENCH_LOCALAPPDATA_ENV, "").strip()
    base = Path(workbench_local) if workbench_local else local_data_root()
    return base / APP_FOLDER / "Workbench" / "library"


def database_path(root: Path | None = None) -> Path:
    return Path(root or library_root()) / DATABASE_NAME


# Opening it ----------------------------------------------------------------------------------------


def connect(root: Path | None = None, *, backup: bool = True) -> sqlite3.Connection:
    """Open the library for reading and writing, making it when it is new and moving its structure up
    to this build's; take today's backup if there is none yet."""

    root = Path(root or library_root())
    problem = recordings_drive_problem(root, "library folder")
    if problem:
        raise ValueError(problem)
    root.mkdir(parents=True, exist_ok=True)
    existed = database_path(root).is_file()
    connection = sqlite3.connect(str(database_path(root)), timeout=BUSY_TIMEOUT_MS / 1000)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        # Refused before anything is written: switching the journal mode below rewrites the file's header.
        _refuse_newer(stored_version(connection))
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        upgrade(connection, root, existed=existed)
        if backup:
            daily_backup(connection, root)
    except BaseException:
        connection.close()
        raise
    return connection


def connect_read_only(root: Path | None = None) -> sqlite3.Connection | None:
    """The library opened so that nothing can be changed, or None when there is no library yet. It is
    never made, moved up or backed up from here, and a library a newer build moved on is refused
    (``LibraryTooNew``), as ``connect`` refuses it (224, F7)."""

    database = database_path(root)
    if not database.is_file():
        return None
    connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True, timeout=5)
    try:
        connection.row_factory = sqlite3.Row
        _refuse_newer(stored_version(connection))
    except BaseException:
        connection.close()
        raise
    return connection


def stored_version(connection: sqlite3.Connection) -> int:
    """The structure version the library says it has; 0 for a database with none yet."""

    try:
        row = connection.execute("SELECT value FROM schema_metadata WHERE key = 'schema_version'").fetchone()
    except sqlite3.Error:
        return 0
    try:
        return int(row[0]) if row else 0
    except (TypeError, ValueError):
        return 0


# The structure, one step at a time ---------------------------------------------------------------


def _add_missing_columns(connection: sqlite3.Connection, table: str, columns: tuple[tuple[str, str], ...]) -> None:
    have = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
    for name, kind in columns:
        if name not in have:
            try:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
            except sqlite3.OperationalError as exc:
                # Another process (the page and a scan) added it a moment ago.
                if "duplicate column" not in str(exc).casefold():
                    raise


def _step_raw_bin(connection: sqlite3.Connection) -> None:
    """Versions 1 and 2: the raw bin's own tables (215, 220)."""

    connection.execute("CREATE TABLE IF NOT EXISTS schema_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS recordings (
            recording_id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_sha256 TEXT,
            sampled_sha256 TEXT,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            duration_seconds REAL,
            audio_tracks INTEGER,
            track_titles_json TEXT,
            guess TEXT,
            guess_reason TEXT,
            narration_track INTEGER,
            speech_seconds REAL,
            speech_stretches_json TEXT,
            other_speech_track INTEGER,
            game_track INTEGER,
            game_track_decided_by TEXT,
            idle_status TEXT,
            idle_seconds REAL,
            idle_share REAL,
            idle_stretches_json TEXT,
            active_stretches_json TEXT,
            flag_count INTEGER,
            flags_json TEXT,
            transcript_path TEXT,
            decision TEXT NOT NULL DEFAULT 'undecided',
            decision_utc TEXT,
            duplicate_of INTEGER REFERENCES recordings(recording_id) ON DELETE SET NULL,
            content_changed_utc TEXT,
            first_seen_utc TEXT NOT NULL,
            scanned_utc TEXT,
            scan_rule_version INTEGER,
            bytes_read INTEGER,
            scan_error TEXT
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_recordings_content ON recordings(content_sha256)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS locations (
            location_id INTEGER PRIMARY KEY AUTOINCREMENT,
            recording_id INTEGER NOT NULL REFERENCES recordings(recording_id) ON DELETE CASCADE,
            path TEXT NOT NULL,
            path_key TEXT NOT NULL UNIQUE,
            root_key TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            modified_ns INTEGER NOT NULL,
            is_current INTEGER NOT NULL DEFAULT 1,
            missing INTEGER NOT NULL DEFAULT 0,
            first_seen_utc TEXT NOT NULL,
            last_seen_utc TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_locations_recording ON locations(recording_id, is_current)")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS labels (label_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "name TEXT NOT NULL UNIQUE COLLATE NOCASE, builtin INTEGER NOT NULL DEFAULT 0)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS recording_labels (recording_id INTEGER NOT NULL REFERENCES "
        "recordings(recording_id) ON DELETE CASCADE, label_id INTEGER NOT NULL REFERENCES labels(label_id) "
        "ON DELETE CASCADE, PRIMARY KEY(recording_id, label_id))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS scan_runs (run_id INTEGER PRIMARY KEY AUTOINCREMENT, started_utc TEXT NOT NULL, "
        "finished_utc TEXT, status TEXT NOT NULL, files_seen INTEGER DEFAULT 0, files_read INTEGER DEFAULT 0, "
        "bytes_read INTEGER DEFAULT 0, seconds_of_video_read REAL DEFAULT 0, detail TEXT)"
    )
    # Version 2 (220): the reason idle time is estimated or unknown, and which rules and Track roles the
    # stored guess and idle time were worked out with.
    _add_missing_columns(connection, "recordings",
                         (("idle_reason", "TEXT"), ("rules_version", "INTEGER"), ("rules_roles", "TEXT")))
    for name in BUILTIN_LABELS:
        connection.execute("INSERT OR IGNORE INTO labels(name, builtin) VALUES (?, 1)", (name,))


def _step_records(connection: sqlite3.Connection) -> None:
    """Version 3 (242, 243): every structure step taken; the folders generated products live under;
    every run, each recording's outcome in it, what changed afterwards, and the folders it made; the
    receipts of the one-time move out of settings.json."""

    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_steps (step_id INTEGER PRIMARY KEY AUTOINCREMENT, from_version INTEGER "
        "NOT NULL, to_version INTEGER NOT NULL, applied_utc TEXT NOT NULL, backup_path TEXT)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS roots (root_id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, "
        "path TEXT NOT NULL, path_key TEXT NOT NULL, first_seen_utc TEXT NOT NULL, last_seen_utc TEXT NOT NULL, "
        "UNIQUE(kind, path_key))"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            feature INTEGER,
            title TEXT NOT NULL DEFAULT '',
            workflow TEXT NOT NULL DEFAULT '',
            origin TEXT,
            profile TEXT,
            source TEXT,
            output TEXT,
            log TEXT,
            started_utc TEXT,
            started_local TEXT,
            ended_utc TEXT,
            finished_local TEXT,
            process_status TEXT NOT NULL,
            exit_code INTEGER,
            state TEXT NOT NULL DEFAULT 'unknown',
            state_source TEXT NOT NULL DEFAULT 'runner',
            headline TEXT,
            counts_json TEXT,
            owner_session TEXT,
            feature_ref TEXT,
            legacy INTEGER NOT NULL DEFAULT 0,
            legacy_key TEXT UNIQUE,
            legacy_status TEXT,
            details_unknown INTEGER NOT NULL DEFAULT 0,
            updated_utc TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_order ON runs(ended_utc, started_utc)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_process ON runs(process_status)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS run_items (
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            item_key TEXT NOT NULL,
            position INTEGER NOT NULL,
            kind TEXT NOT NULL,
            recording_id INTEGER REFERENCES recordings(recording_id) ON DELETE SET NULL,
            name TEXT,
            path TEXT,
            size_bytes INTEGER,
            modified_ns INTEGER,
            outcome TEXT NOT NULL DEFAULT 'not_reported',
            reason TEXT,
            reported_by TEXT,
            updated_utc TEXT NOT NULL,
            PRIMARY KEY(run_id, item_key)
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_run_items_recording ON run_items(recording_id)")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS run_events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL "
        "REFERENCES runs(run_id) ON DELETE CASCADE, at_utc TEXT NOT NULL, old_state TEXT, new_state TEXT, "
        "source TEXT, note TEXT)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS run_products (product_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL "
        "REFERENCES runs(run_id) ON DELETE CASCADE, recording_id INTEGER REFERENCES recordings(recording_id) "
        "ON DELETE SET NULL, kind TEXT NOT NULL, root_id INTEGER REFERENCES roots(root_id) ON DELETE SET NULL, "
        "relative_path TEXT, path TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'unchecked', checked_utc TEXT, "
        "UNIQUE(run_id, kind, path))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS legacy_imports (import_id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, "
        "source_sha256 TEXT, started_utc TEXT NOT NULL, finished_utc TEXT, status TEXT NOT NULL, counts_json TEXT, "
        "backup_folder TEXT, note TEXT)"
    )


def _step_marks(connection: sqlite3.Connection) -> None:
    """Version 4 (244): a recording is its content (the full hash), the copy the operator manages (a
    ``recordings`` row) and where that copy was seen (``locations``).

    - ``contents``: each confirmed content once. Filled from every copy's full hash, here on every open (so
      a scan by an older build is caught up) and by the scan as it stores what it read.
    - ``locations.registered_by``: "scan" for a copy a scan found; "outside" for one Find my bug reports or
      the player marked that no scan has read (outside the watched folders, or not scanned yet). Those
      stay off the raw bin's list until a scan reads them.
    - ``marks``: Never use (per copy) and done in Find my bug reports (shared by identical content). An old
      entry from settings.json that the library cannot tie to a copy keeps its path instead (``old_key``,
      the path lower-cased as the old lists compared it, and ``old_path`` as it was written). A cleared
      mark is kept, with when and by whom.
    - ``resume_points``: a stopped run Continue picks up, at most one active per feature.
    """

    connection.execute(
        "CREATE TABLE IF NOT EXISTS contents (content_sha256 TEXT PRIMARY KEY, size_bytes INTEGER, "
        "first_confirmed_utc TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT OR IGNORE INTO contents(content_sha256, size_bytes, first_confirmed_utc) "
        "SELECT content_sha256, MAX(size_bytes), MIN(COALESCE(scanned_utc, first_seen_utc)) FROM recordings "
        "WHERE COALESCE(content_sha256, '') <> '' GROUP BY content_sha256"
    )
    _add_missing_columns(connection, "locations", (("registered_by", "TEXT NOT NULL DEFAULT 'scan'"),))
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS marks (
            mark_id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL CHECK (kind IN ('never_use', 'bugs_done')),
            recording_id INTEGER REFERENCES recordings(recording_id) ON DELETE CASCADE,
            old_key TEXT,
            old_path TEXT,
            outcome TEXT CHECK (outcome IS NULL OR outcome IN ('done', 'no_narration', 'unknown')),
            mark_date TEXT,
            run_id TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
            set_by TEXT NOT NULL,
            import_key TEXT UNIQUE,
            created_utc TEXT NOT NULL,
            cleared_utc TEXT,
            cleared_by TEXT,
            CHECK (recording_id IS NOT NULL OR old_key IS NOT NULL)
        )
        """
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_marks_never_use_copy ON marks(recording_id) "
        "WHERE kind = 'never_use' AND cleared_utc IS NULL AND recording_id IS NOT NULL"
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_marks_never_use_old ON marks(old_key) "
        "WHERE kind = 'never_use' AND cleared_utc IS NULL AND recording_id IS NULL"
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_marks_copy ON marks(kind, recording_id)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS resume_points (
            resume_id INTEGER PRIMARY KEY AUTOINCREMENT,
            feature TEXT NOT NULL,
            run_id TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
            folder TEXT NOT NULL,
            recordings_json TEXT NOT NULL,
            tracks_json TEXT NOT NULL,
            import_key TEXT UNIQUE,
            created_utc TEXT NOT NULL,
            cleared_utc TEXT
        )
        """
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_resume_points_active ON resume_points(feature) WHERE cleared_utc IS NULL"
    )


def _step_inbox(connection: sqlite3.Connection) -> None:
    """Version 5 (224, Wave B2b): Review Media Inbox's records, the ledger's own tables and indexes, each named
    with ``inbox_`` in front (``review_ledger.INBOX_TABLES``). They start empty; the one-time move fills them
    (``inbox_move``), and only the Inbox's own modules use them, through its store (``inbox_records``)."""

    for statement in library_schema_statements():
        connection.execute(statement)


def _step_speech_facts(connection: sqlite3.Connection) -> None:
    """Version 6 (264, Wave C1): what was measured about each recording's speech and who decided its narration
    track. Each belongs to the content (the full hash, shared by exact copies) or, until the content is known, to
    the copy (``recording_id``, and only while the file keeps the size and time noted here). A cleared answer is
    kept, with when and by whom. Nothing is filled here: no data moves, the facts are written as recordings are read."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS voice_measures (
            measure_id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_sha256 TEXT,
            recording_id INTEGER REFERENCES recordings(recording_id) ON DELETE CASCADE,
            size_bytes INTEGER NOT NULL,
            modified_ns INTEGER NOT NULL,
            duration_seconds REAL,
            track_count INTEGER NOT NULL DEFAULT 0,
            titles_json TEXT NOT NULL DEFAULT '{}',
            activity_rule_version INTEGER NOT NULL,
            measured_by TEXT NOT NULL,
            run_id TEXT,
            measured_utc TEXT NOT NULL,
            CHECK (content_sha256 IS NOT NULL OR recording_id IS NOT NULL)
        )
        """
    )
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_voice_measures_content ON voice_measures(content_sha256) "
                       "WHERE content_sha256 IS NOT NULL")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_voice_measures_copy ON voice_measures(recording_id) "
                       "WHERE content_sha256 IS NULL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS voice_measure_tracks (
            measure_id INTEGER NOT NULL REFERENCES voice_measures(measure_id) ON DELETE CASCADE,
            track INTEGER NOT NULL,
            silent INTEGER NOT NULL DEFAULT 0,
            active_seconds REAL,
            active_ratio REAL,
            noise_floor_dbfs REAL,
            peak_dbfs REAL,
            level_swing_db REAL,
            loud_share REAL,
            moments_json TEXT NOT NULL DEFAULT '[]',
            confident_words INTEGER,
            spotter_words INTEGER,
            own_words INTEGER,
            probed_seconds REAL,
            listened INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (measure_id, track)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS voice_decisions (
            measure_id INTEGER NOT NULL REFERENCES voice_measures(measure_id) ON DELETE CASCADE,
            voice_rule_version INTEGER NOT NULL,
            roles_key TEXT NOT NULL DEFAULT '',
            preferred_key TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            chosen_track INTEGER,
            confidence REAL,
            decided_by TEXT NOT NULL DEFAULT '',
            explanation TEXT NOT NULL DEFAULT '',
            tracks_json TEXT NOT NULL DEFAULT '[]',
            details_json TEXT NOT NULL DEFAULT '{}',
            decided_utc TEXT NOT NULL,
            PRIMARY KEY (measure_id, voice_rule_version, roles_key, preferred_key)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS narration_answers (
            answer_id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_sha256 TEXT,
            recording_id INTEGER REFERENCES recordings(recording_id) ON DELETE CASCADE,
            size_bytes INTEGER,
            modified_ns INTEGER,
            track INTEGER NOT NULL,
            answered_by TEXT NOT NULL,
            answered_utc TEXT NOT NULL,
            cleared_utc TEXT,
            cleared_by TEXT,
            CHECK (content_sha256 IS NOT NULL OR recording_id IS NOT NULL)
        )
        """
    )
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_narration_answers_content ON narration_answers("
                       "content_sha256) WHERE cleared_utc IS NULL AND content_sha256 IS NOT NULL")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_narration_answers_copy ON narration_answers(recording_id) "
                       "WHERE cleared_utc IS NULL AND content_sha256 IS NULL")


def _step_editor_index(connection: sqlite3.Connection) -> None:
    """Version 7 (242, Wave C2, audit H6 and M2): an index of the AI Video Editor's projects and versions. Each
    project is kept by the registered folder it lives under and its place inside it, never a whole path; its
    recording by content (the full hash its ``project.json`` is bound to) and by the copy at its path. The project
    files stay the authority: ``index_editor_projects`` only makes this index match them, and a project no longer
    on disk is marked unavailable, never deleted. Nothing is filled here."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS editor_projects (
            project_id INTEGER PRIMARY KEY AUTOINCREMENT,
            root_id INTEGER NOT NULL REFERENCES roots(root_id) ON DELETE CASCADE,
            relative_path TEXT NOT NULL,
            content_sha256 TEXT,
            recording_id INTEGER REFERENCES recordings(recording_id) ON DELETE SET NULL,
            edit_of TEXT NOT NULL DEFAULT '',
            link_state TEXT NOT NULL CHECK (link_state IN ('bound', 'unbound', 'unavailable')),
            bound_utc TEXT,
            bound_how TEXT,
            checked_utc TEXT NOT NULL,
            UNIQUE (root_id, relative_path)
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_editor_projects_content ON editor_projects(content_sha256)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS editor_versions (
            project_id INTEGER NOT NULL REFERENCES editor_projects(project_id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            created TEXT NOT NULL DEFAULT '',
            editor_label TEXT NOT NULL DEFAULT '',
            preview_passed INTEGER,
            final_passed INTEGER,
            exported INTEGER NOT NULL DEFAULT 0,
            documents_json TEXT NOT NULL DEFAULT '[]',
            state TEXT NOT NULL DEFAULT 'present' CHECK (state IN ('present', 'unavailable')),
            checked_utc TEXT NOT NULL,
            PRIMARY KEY (project_id, version)
        )
        """
    )


# Each version's step. Every step only adds, and checks before it adds, so it can run again safely: an
# older build opened after a newer one writes its own version number back (Wave 6 did that on every
# open), and the next open of a newer build simply takes its steps again.
SCHEMA_STEPS: dict[int, Callable[[sqlite3.Connection], None]] = {
    2: _step_raw_bin,
    3: _step_records,
    4: _step_marks,
    5: _step_inbox,
    6: _step_speech_facts,
    7: _step_editor_index,
}


def _missing_structure(connection: sqlite3.Connection) -> list[str]:
    """Every table and column this build expects that is not there."""

    missing: list[str] = []
    for table, columns in EXPECTED_STRUCTURE.items():
        have = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
        if not have:
            missing.append(table)
        missing += [f"{table}.{column}" for column in columns if have and column not in have]
    return missing


def _counts(connection: sqlite3.Connection) -> dict[str, int]:
    found: dict[str, int] = {}
    for table in KEPT_TABLES:
        try:
            found[table] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        except sqlite3.Error:
            found[table] = 0
    return found


def _refuse_newer(version: int) -> None:
    if version > SCHEMA_VERSION:
        raise LibraryTooNew(
            f"The library was updated by a newer version of the app (structure {version}; this version knows "
            f"{SCHEMA_VERSION}). Use the newer version; this one does not change it.")


def _new_backup_folder(root: Path, label: str) -> Path:
    """A folder of its own for one backup, never one an earlier backup in the same second uses."""

    parent = Path(root) / "backups" / MIGRATION_BACKUPS
    parent.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{label}"
    for number in range(1, 1000):
        folder = parent / (stem if number == 1 else f"{stem}-{number}")
        try:
            folder.mkdir()
            return folder
        except FileExistsError:
            continue
    raise RuntimeError(f"No free backup folder in {parent}.")


def migration_backup(connection: sqlite3.Connection, root: Path, label: str) -> Path:
    """A whole copy of the library, made with SQLite's backup call before its structure changes, in a
    folder the daily backup's pruning never touches. The copy is checked before anything changes."""

    from . import safe_write  # noqa: PLC0415

    folder = _new_backup_folder(root, label)
    target = folder / DATABASE_NAME
    try:
        safe_write.checked_copy(connection, target)
    except safe_write.CopyNotChecked as exc:
        raise RuntimeError(f"The library's backup in {folder} did not check out, so nothing was changed.") from exc
    return target


def upgrade(connection: sqlite3.Connection, root: Path, *, existed: bool = True) -> int:
    """Move the library's structure up to this build's, one step at a time. Returns the version it had."""

    before = stored_version(connection)
    _refuse_newer(before)
    backup_path = ""
    if existed and 0 < before < SCHEMA_VERSION:
        backup_path = str(migration_backup(connection, root, f"schema-{before}-to-{SCHEMA_VERSION}"))
    connection.execute("BEGIN IMMEDIATE")
    try:
        # Read again inside the transaction: another process may have moved it on a moment ago.
        before = stored_version(connection)
        _refuse_newer(before)
        kept = _counts(connection)
        for version in sorted(SCHEMA_STEPS):
            SCHEMA_STEPS[version](connection)
        if before < SCHEMA_VERSION:
            after = _counts(connection)
            if any(after[table] < kept[table] for table in KEPT_TABLES):
                raise RuntimeError("A structure step would have lost rows; nothing was changed.")
            problems = connection.execute("PRAGMA foreign_key_check").fetchall()
            if problems:
                raise RuntimeError(f"A structure step left {len(problems)} broken links; nothing was changed.")
            missing = _missing_structure(connection)
            if missing:
                raise RuntimeError(f"A structure step left out {', '.join(missing)}; nothing was changed.")
            connection.execute("INSERT INTO schema_steps(from_version, to_version, applied_utc, backup_path) "
                               "VALUES (?, ?, ?, ?)", (before, SCHEMA_VERSION, _now(), backup_path or None))
            connection.execute("INSERT INTO schema_metadata(key, value) VALUES ('schema_version', ?) "
                               "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (str(SCHEMA_VERSION),))
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return before


def daily_backup(connection: sqlite3.Connection, root: Path, *, today: date | None = None,
                 keep: int = BACKUP_KEEP) -> Path | None:
    """One dated copy per day the library is opened, made with SQLite's backup call (never a raw file
    copy, which would miss what is still in the write-ahead log). The newest ``keep`` stay; the backups
    taken before a structure step, in their own folder, are never pruned."""

    folder = Path(root) / "backups"
    stamp = (today or date.today()).isoformat()
    target = folder / f"raw-bin-library-{stamp}.sqlite"
    if target.exists():
        return None
    folder.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".partial")
    copy = sqlite3.connect(str(partial))
    try:
        connection.backup(copy)
    finally:
        copy.close()
    os.replace(partial, target)
    dated = sorted(folder.glob("raw-bin-library-????-??-??.sqlite"))
    for old in dated[:-keep] if keep > 0 else []:
        try:
            old.unlink()
        except OSError:
            pass
    return target


# Reading the raw bin for other features ----------------------------------------------------------


def current_copy(source: Path | str, *, root: Path | None = None) -> dict[str, Any] | None:
    """The recording the library holds at this path now, while the path is current and not missing: its
    content hash, length and the size and modified time it had when the library last read it. Read-only;
    None when the library does not know the path or cannot be opened."""

    try:
        connection = connect_read_only(root)
        if connection is None:
            return None
        try:
            row = connection.execute(
                "SELECT r.content_sha256, r.sampled_sha256, r.duration_seconds, l.size_bytes, l.modified_ns FROM recordings r "
                "JOIN locations l ON l.recording_id = r.recording_id "
                "WHERE l.path_key = ? AND l.is_current = 1 AND l.missing = 0 LIMIT 1",
                (path_key(source),),
            ).fetchone()
        finally:
            connection.close()
    except (OSError, sqlite3.Error, ValueError):
        return None
    return dict(row) if row else None


def list_recordings(*, root: Path | None = None) -> list[dict[str, Any]]:
    """Every recording the library knows, read without changing anything (the library opened read-only), with
    the Inbox's verdict and what mined it; [] when there is no library yet."""

    try:
        connection = connect_read_only(root)
        if connection is None:
            return []
        try:
            return list_library(connection)
        finally:
            connection.close()
    except (OSError, sqlite3.Error, ValueError):
        return []


def list_library(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    """The raw bin's list (``raw_bin_library.list_recordings``), each recording with what mined it for tickets
    (244): ``bugs_mined`` ("done", "no_narration", "unknown", "old_list" or "") and ``mined``, the words the
    raw bin and Choose a recording show. Neither is ever exported (the export keeps its columns). The Inbox's
    verdict comes from the same library (224, Wave B2b), so no setting can hide it."""

    from . import raw_bin_library  # noqa: PLC0415 - the scan engine imports this module

    rows = raw_bin_library.list_recordings(connection)
    try:
        _add_bugs_mined(connection, rows)
    except sqlite3.Error:
        # A library read without being moved up (an older structure) has no marks yet.
        for row in rows:
            row["bugs_mined"] = ""
    for row in rows:
        row["mined"] = mined_words(bool(row.get("reviewed_by_inbox")), str(row.get("bugs_mined") or ""))
    return rows


# What mined a recording (244, operator decisions Q2 and Q3): the raw bin's Mined column and Choose a
# recording say it in the same words. "Bugs (old list)" is an old "done" entry the library could not tie to
# a copy, matched by the path, as the old list was.
MINED_BUGS_WORDS = {"done": "Bugs", "unknown": "Bugs", "no_narration": "Bugs: no narration",
                    "old_list": "Bugs (old list)"}


def mined_words(inbox: bool, bugs: str) -> str:
    """"Inbox", "Bugs", "Inbox + Bugs", "Bugs: no narration", "Bugs (old list)", or "" when nothing mined it."""

    part = MINED_BUGS_WORDS.get(bugs, "")
    if inbox:
        return f"Inbox + {part}" if part else "Inbox"
    return part


def _add_bugs_mined(connection: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    """Each listed copy's Bugs part, from the library alone (the raw bin never waits on the recordings
    drive): its own newest done mark; else, for a copy that is there and holds a confirmed content, the
    newest mark on an identical copy; else an old entry for its path."""

    own: dict[int, str] = {}
    for row in connection.execute(
            "SELECT recording_id, outcome FROM marks WHERE kind = ? AND cleared_utc IS NULL AND recording_id IS NOT "
            "NULL ORDER BY mark_date, mark_id", (MARK_BUGS_DONE,)):
        own[int(row[0])] = str(row[1] or "unknown")
    shared: dict[str, tuple[int, str]] = {}
    for row in connection.execute(
            "SELECT r.content_sha256, m.recording_id, m.outcome FROM marks m JOIN recordings r ON r.recording_id = "
            "m.recording_id WHERE m.kind = ? AND m.cleared_utc IS NULL AND COALESCE(r.content_sha256, '') <> '' "
            "ORDER BY m.mark_date, m.mark_id", (MARK_BUGS_DONE,)):
        shared[str(row[0])] = (int(row[1]), str(row[2] or "unknown"))
    old: set[str] = set()
    for row in connection.execute(
            "SELECT old_key, old_path FROM marks WHERE kind = ? AND cleared_utc IS NULL AND recording_id IS NULL",
            (MARK_BUGS_DONE,)):
        old |= {str(row[0] or "")} | path_spellings(row[1])
    for row in rows:
        recording_id = int(row["recording_id"])
        content = str(row.get("content_sha256") or "")
        holder = shared.get(content) if content and not row.get("missing") else None
        if recording_id in own:
            bugs = own[recording_id]
        elif holder is not None and holder[0] != recording_id:
            bugs = holder[1]
        elif not str(row.get("path_key") or "").startswith(REPLACED_KEY_PREFIX) and path_spellings(row.get("path")) & old:
            bugs = "old_list"
        else:
            bugs = ""
        row["bugs_mined"] = bugs


def last_scan_finished(connection: sqlite3.Connection) -> str:
    """When the last raw bin scan finished (UTC, as stored), or "" when none has."""

    try:
        row = connection.execute(
            "SELECT finished_utc FROM scan_runs WHERE finished_utc IS NOT NULL ORDER BY run_id DESC LIMIT 1"
        ).fetchone()
    except sqlite3.Error:
        return ""
    return str(row[0]) if row and row[0] else ""


# Review Media Inbox, read-only until its ledger moves in (224) -----------------------------------


class InboxVerdicts:
    """What Review Media Inbox has finished, from its ledger: the content hashes, and by path what was
    finished there. ``known`` is False when the ledger could not be read (missing, locked or damaged):
    then nothing here says a recording was not reviewed, only that it is not known."""

    def __init__(self, hashes: set[str] | None = None,
                 paths: dict[str, list[tuple[str, str, int]]] | None = None, *, known: bool = True) -> None:
        self.hashes = hashes or set()
        self.paths = paths or {}
        self.known = known

    def __iter__(self):  # (hashes, paths), the shape the raw bin always used
        return iter((self.hashes, self.paths))

    def __getitem__(self, index: int) -> Any:
        return (self.hashes, self.paths)[index]


def inbox_known(connection: sqlite3.Connection) -> bool:
    """Whether the library can say what Review Media Inbox reviewed (224, F11): its records are in, because the
    one-time move is complete (or there was never anything to move). Before that, or when the move was undone,
    "not reviewed" would only mean "not known"."""

    try:
        row = connection.execute(
            "SELECT status FROM legacy_imports WHERE source = ? ORDER BY import_id DESC LIMIT 1",
            (INBOX_RECEIPT_SOURCE,)).fetchone()
    except sqlite3.Error:
        return False
    return bool(row) and str(row[0] or "") == "complete"


def inbox_reviewed(connection: sqlite3.Connection) -> InboxVerdicts:
    """The recordings Review Media Inbox has finished, from its own tables in the library, over the caller's
    connection (224, Wave B2b): their content hashes, and by path what was finished there (its content hash and
    sampled hash, "" when the Inbox has none, and its size), so a different recording later saved at that path is
    not taken for it (268).

    A recording counts from its own finished state (Q7): finished in any batch it was in, or its own state
    finished, or its batch finished (the rule before the move, so nothing shows less than it did). ``known`` is
    False until the Inbox's records are in the library (``inbox_known``)."""

    if not inbox_known(connection):
        return InboxVerdicts(known=False)
    try:
        hashes, paths = inbox_verdicts(connection)
    except sqlite3.Error:
        return InboxVerdicts(known=False)
    return InboxVerdicts(hashes, paths)


def inbox_verdicts(connection: sqlite3.Connection) -> tuple[set[str], dict[str, list[tuple[str, str, int]]]]:
    """``inbox_reviewed``'s rule on the library's Inbox tables, whatever the move's receipt says (the move checks
    its own import with it). Raises ``sqlite3.Error`` when the tables cannot be read."""

    states = sorted(FINALIZED_BATCH_STATES)
    marks = ", ".join("?" for _ in states)
    rows = connection.execute(
        f"""
        SELECT DISTINCT s.content_sha256, s.sampled_sha256, s.size_bytes, l.normalized_path FROM inbox_sources s
        LEFT JOIN inbox_source_locations l ON l.source_id = s.source_id
        WHERE s.lifecycle_state IN ({marks})
           OR EXISTS (SELECT 1 FROM inbox_batch_sources bs WHERE bs.source_id = s.source_id AND bs.state IN ({marks}))
           OR EXISTS (SELECT 1 FROM inbox_batch_sources bs JOIN inbox_batches b ON b.batch_id = bs.batch_id
                      WHERE bs.source_id = s.source_id AND b.status IN ({marks}))
        """,
        [*states, *states, *states],
    ).fetchall()
    return verdicts_from_rows(rows)


def verdicts_from_rows(rows: Iterable[Any]) -> tuple[set[str], dict[str, list[tuple[str, str, int]]]]:
    """(content hashes, {path: [(content hash, sampled hash, size)]}) from rows of (content hash, sampled hash,
    size, normalized path), the shape ``reviewed_by_inbox`` compares a raw bin recording with."""

    hashes: set[str] = set()
    paths: dict[str, list[tuple[str, str, int]]] = {}
    for content, sampled, size, normalized in rows:
        if content:
            hashes.add(str(content).lower())
        if normalized:
            paths.setdefault(os.path.normcase(str(normalized)), []).append(
                (str(content or "").lower(), str(sampled or "").lower(), int(size or 0)))
    return hashes, paths


INBOX_RECEIPT_SOURCE = "inbox ledger"  # inbox_records.RECEIPT_SOURCE
INBOX_ROOT_KIND = "inbox"  # inbox_records.ROOT_KIND
INBOX_FAILED_STATES = {"retryable_failure", "failed"}
INBOX_ATTENTION_STATES = {"needs_manual_review", "source_changed"}


def inbox_run_outcomes(connection: sqlite3.Connection, orchestration_run_id: str, *,
                       already_counted: set[str] | None = None) -> list[dict[str, Any]]:
    """Each recording one Inbox "Process" run took, with its outcome (243): the run's own journal
    (``.orchestration`` in the Inbox folder registered in the library) says which recordings it took and which
    it got through; the Inbox's records in the library, over the caller's connection, say where each one stands
    now (224, Wave B2b). A Process run the Inbox picks up again later keeps its journal, so a recording an
    earlier Workbench run of it already counted (``already_counted``, path keys) is left out. [] when the journal
    cannot be read; a recording whose state cannot be read is counted with an empty reason."""

    if not orchestration_run_id:
        return []
    try:
        root = connection.execute("SELECT path FROM roots WHERE kind = ? ORDER BY root_id LIMIT 1",
                                  (INBOX_ROOT_KIND,)).fetchone()
    except sqlite3.Error:
        return []
    if root is None:
        return []
    folder = Path(str(root[0])) / ".orchestration"
    journal: dict[str, Any] | None = None
    for candidate in (folder / "completed-runs" / f"{orchestration_run_id}.json", folder / "active-run.json"):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        # The Inbox writes {"journal_version", "run", "run_sha256"} (review_orchestration._write_journal).
        run = data.get("run") if isinstance(data, dict) and isinstance(data.get("run"), dict) else data
        if isinstance(run, dict) and str(run.get("run_id") or "") == str(orchestration_run_id):
            journal = run
            break
    if journal is None:
        return []
    taken = [item for item in journal.get("snapshot") or [] if isinstance(item, dict)]
    done = {str(value) for value in journal.get("completed_source_ids") or [] if str(value)}
    states: dict[str, str] = {}
    ids = [int(item["source_id"]) for item in taken if str(item.get("source_id") or "").isdigit()]
    if ids:
        try:
            for source_id, state in connection.execute(
                    f"SELECT source_id, lifecycle_state FROM inbox_sources WHERE source_id IN "
                    f"({', '.join('?' for _ in ids)})", ids):
                states[str(source_id)] = str(state or "")
        except sqlite3.Error:
            states = {}
    outcomes: list[dict[str, Any]] = []
    for item in taken:
        source_id, path = str(item.get("source_id") or ""), str(item.get("path") or "")
        if not path or path_key(path) in (already_counted or set()):
            continue
        state = states.get(source_id, "")
        if source_id not in done:
            outcome, reason = "cancelled", "Not reached in this run; the Inbox carries on with it next time."
        elif state in INBOX_FAILED_STATES:
            outcome, reason = "failed", state.replace("_", " ")
        elif state in INBOX_ATTENTION_STATES:
            outcome, reason = "completed_with_problems", state.replace("_", " ")
        else:
            outcome, reason = "completed", state.replace("_", " ")
        outcomes.append({"item": path, "outcome": outcome, "reason": reason})
    return outcomes


def reviewed_by_inbox(row: Any, hashes: set[str], paths: dict[str, list[tuple[str, str, int]]]) -> bool:
    """Whether the Inbox finished this recording (268): its content hash is one the Inbox finished; or
    the Inbox finished a recording at its path and nothing known says this is another one. Never when
    both content hashes are known (they differ, or the first test would have matched), nor when the
    sizes differ, nor when both sampled hashes are known and differ."""

    content = str(row["content_sha256"] or "").lower()
    if content and content in hashes:
        return True
    sampled = str(row["sampled_sha256"] or "").lower()
    for reviewed_content, reviewed_sampled, reviewed_size in paths.get(str(row["path_key"] or ""), []):
        if content and reviewed_content:
            continue
        if reviewed_size and int(row["size_bytes"] or 0) != reviewed_size:
            continue
        if sampled and reviewed_sampled and sampled != reviewed_sampled:
            continue
        return True
    return False


# Runs (243) -------------------------------------------------------------------------------------
#
# A run is written when it is launched (``Records.open_run``, from the one place every run goes
# through), closed when its process ends (``end_run``), and given each recording's outcome by the
# feature that knows it, when it knows it (``record_outcomes``, ``finish_run``). Writing the same
# outcome again changes nothing; a later, different one corrects it, and a changed run state is kept
# in ``run_events``.

RUNNING = "running"
INTERRUPTED = "interrupted"
UNKNOWN = "unknown"
# A run's final state: the one status rule's words (run_status, 213), plus a run cut off by a crash or
# a close, and one whose state nobody could tell.
RUN_STATES = ("completed", "complete_with_warnings", "completed_with_problems", "failed", "cancelled",
              INTERRUPTED, UNKNOWN)
# One recording's outcome in a run (243).
OUTCOME_COMPLETED = "completed"
OUTCOME_NO_NARRATION = "no_narration"
OUTCOME_SKIPPED = "skipped"  # skipped by the operator, with the reason
OUTCOME_FAILED = "failed"
OUTCOME_CANCELLED = "cancelled"  # the run stopped before it reached this one
OUTCOME_UNCHANGED = "unchanged"  # the raw bin had already read it as it is
OUTCOME_NOT_REPORTED = "not_reported"  # the feature does not say, and nothing is guessed
OUTCOMES = ("completed", "complete_with_warnings", "completed_with_problems", OUTCOME_NO_NARRATION,
            OUTCOME_SKIPPED, OUTCOME_FAILED, OUTCOME_CANCELLED, OUTCOME_UNCHANGED, OUTCOME_NOT_REPORTED)
# Which of the four features a kind of run belongs to; 0 is the Archive Catalog (kept, not one of the four).
RUN_KINDS = {
    "full_review": 1, "transcript_only": 1, "ticket_evidence": 2, "archive_catalog": 0, "inbox_process": 3,
    "bug_reports": 2, "raw_scan": 3, "raw_deep_scan": 3, "editor_prepare": 4, "editor_preview": 4,
    "editor_export": 4, "other": None,
}
SESSIONS = "sessions"
# The fields of one run in settings.json's old list (243), and its status words.
LEGACY_RUN_FIELDS = ("timestamp", "workflow", "workflow_title", "profile", "source", "output", "log", "status")
LEGACY_STATES = {"succeeded": "completed", "completed": "completed", "failed": "failed", "cancelled": "cancelled",
                 "completed with problems": "completed_with_problems"}
# The titles History gave each kind of run, so an old entry still says which feature it was.
LEGACY_TITLES = {
    "Full Review": "full_review", "Transcript Only": "transcript_only", "AI / Ticket Evidence": "ticket_evidence",
    "Archive Catalog": "archive_catalog", "Review Media Inbox": "inbox_process",
    "Find my bug reports": "bug_reports", "Raw bin scan": "raw_scan", "Raw bin Deep scan": "raw_deep_scan",
    "AI Video Editor: analysis": "editor_prepare", "AI Video Editor: preview": "editor_preview",
    "AI Video Editor: export": "editor_export",
}


def legacy_run_key(entry: dict[str, Any]) -> str:
    """One old History entry's own key: a hash of every field it had, so moving it twice adds it once."""

    import hashlib  # noqa: PLC0415

    fields = {name: str(entry.get(name) or "") for name in LEGACY_RUN_FIELDS}
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode("utf-8")).hexdigest()


def _utc_from_local_minute(text: str) -> str | None:
    """'YYYY-MM-DD HH:MM' on this computer's clock, as the library's UTC time; None when it is not one."""

    try:
        moment = datetime.strptime(text.strip(), "%Y-%m-%d %H:%M").astimezone(timezone.utc)
    except ValueError:
        return None
    return moment.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _local_minute() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _lock_now(handle: Any) -> None:
    """Hold an open file's first byte, or raise OSError when someone else holds it. The system lets go
    when the process ends, however it ends."""

    if sys.platform == "win32":
        import msvcrt  # noqa: PLC0415

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl  # noqa: PLC0415

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _session_alive(root: Path, session: str) -> bool:
    """Whether the Workbench that opened ``session`` is still running: it holds its session file."""

    path = Path(root) / SESSIONS / f"{session}.lock"
    if not session or not path.is_file():
        return False
    try:
        handle = open(path, "a+b")
    except OSError:
        return True
    try:
        _lock_now(handle)
    except OSError:
        return True
    finally:
        handle.close()
    return False


def _item_key(item: str) -> tuple[str, str]:
    """(key, kind) for an item of a run: a recording or folder by the library's path rule, a web address
    as it is, anything else (a bare name) by its text."""

    text = str(item or "").strip()
    if "://" in text:
        return text, "url"
    if os.path.isabs(text):
        return path_key(text), "path"
    return f"name:{text}", "name"


def _runner_state(process_status: str, partial: bool) -> str:
    if process_status == "succeeded":
        return "completed"
    if process_status == "failed":
        return "completed_with_problems" if partial else "failed"
    if process_status == "cancelled":
        return "cancelled"
    return UNKNOWN


def history_status(run: Any) -> str:
    """The word History shows for a run, the same words it always showed: "succeeded", "failed",
    "cancelled", "completed with problems", and "completed" for a run a page found complete after its
    process said otherwise; "interrupted" for a run cut off by a crash or a close."""

    if run["legacy"]:
        return str(run["legacy_status"] or "")
    state, process = str(run["state"] or ""), str(run["process_status"] or "")
    if state in ("completed", "complete_with_warnings"):
        return "succeeded" if process == "succeeded" else "completed"
    if state == "completed_with_problems":
        return "completed with problems"
    if state in ("failed", "cancelled", INTERRUPTED):
        return state
    return process or UNKNOWN


def _history_entry(row: Any) -> dict[str, Any]:
    """A run as History and Home read it: the keys the settings list always had, plus its own number."""

    return {
        "timestamp": str(row["finished_local"] or row["started_local"] or ""),
        "workflow": str(row["workflow"] or ""),
        "workflow_title": str(row["title"] or ""),
        "profile": str(row["profile"] or ""),
        "source": str(row["source"] or ""),
        "output": str(row["output"] or ""),
        "log": str(row["log"] or ""),
        "status": history_status(row),
        "run_id": str(row["run_id"]),
        "state": str(row["state"] or ""),
        "kind": str(row["kind"] or ""),
        "legacy": bool(row["legacy"]),
    }


def _add_item(connection: sqlite3.Connection, run_id: str, item: str, position: int, now: str,
              outcome: str = OUTCOME_NOT_REPORTED, reason: str = "", reported_by: str = "",
              recording_id: int | None = None) -> None:
    key, kind = _item_key(item)
    size = modified = None
    if kind == "path":
        try:
            stat = os.stat(item)
            if os.path.isdir(item):
                kind = "folder"
            else:
                kind, size, modified = "recording", int(stat.st_size), int(stat.st_mtime_ns)
        except OSError:
            kind = "recording"
        if recording_id is None:
            found = connection.execute(
                "SELECT recording_id FROM locations WHERE path_key = ? AND is_current = 1", (key,)).fetchone()
            recording_id = int(found[0]) if found else None
    connection.execute(
        "INSERT OR IGNORE INTO run_items(run_id, item_key, position, kind, recording_id, name, path, size_bytes, "
        "modified_ns, outcome, reason, reported_by, updated_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, key, position, kind, recording_id, Path(item).name if kind != "url" else item,
         item if kind != "name" else None, size, modified, outcome, reason or None, reported_by or None, now))


def _insert_legacy_runs(connection: sqlite3.Connection, entries: Any) -> dict[str, int]:
    """The old history's entries as old runs, inside the caller's transaction (``Records.import_legacy_runs``)."""

    valid = [entry for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else []
    counts = {"read": len(valid), "added": 0, "already": 0}
    now = _stamp()
    seen: dict[str, int] = {}
    # Stored newest first; written oldest first. History keeps the list's own order, which is the truth when
    # its times are not (a clock changed, a summer time ended): each one sorts no earlier than the one before
    # it in the list.
    order: str | None = None
    for entry in reversed(valid):
        base = legacy_run_key(entry)
        seen[base] = seen.get(base, 0) + 1
        key = f"{base}:{seen[base]}"
        when = _utc_from_local_minute(str(entry.get("timestamp") or ""))
        order = when if order is None or (when is not None and when > order) else order
        if connection.execute("SELECT 1 FROM runs WHERE legacy_key = ?", (key,)).fetchone():
            counts["already"] += 1
            continue
        title = str(entry.get("workflow_title") or "")
        kind = LEGACY_TITLES.get(title, "other")
        status = str(entry.get("status") or "")
        connection.execute(
            "INSERT INTO runs(run_id, kind, feature, title, workflow, profile, source, output, log, ended_utc, "
            "finished_local, process_status, state, state_source, legacy, legacy_key, legacy_status, "
            "details_unknown, updated_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'legacy', ?, 'old history', "
            "1, ?, ?, 1, ?)",
            (uuid.uuid4().hex, kind, RUN_KINDS.get(kind), title, str(entry.get("workflow") or ""),
             str(entry.get("profile") or ""), str(entry.get("source") or ""), str(entry.get("output") or ""),
             str(entry.get("log") or ""), order,
             str(entry.get("timestamp") or ""), LEGACY_STATES.get(status, UNKNOWN), key, status, now))
        counts["added"] += 1
    return counts


def write_outcomes(connection: sqlite3.Connection, run_id: str, outcomes: Iterable[dict[str, Any]], *,
                   reported_by: str) -> int:
    """Write each recording's outcome into a run, inside the caller's transaction. An outcome may say who
    reported it (``reported_by``); the same outcome again changes nothing, a different one corrects the
    earlier. Returns how many items changed; nothing when the run is not in the library."""

    if not run_id or connection.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone() is None:
        return 0
    now = _stamp()
    changed = 0
    for outcome in outcomes:
        word = str(outcome.get("outcome") or "")
        if word not in OUTCOMES:
            raise ValueError(f"Unknown outcome {word!r}")
        item = str(outcome.get("item") or "")
        reason = str(outcome.get("reason") or "")
        by = str(outcome.get("reported_by") or reported_by)
        recording_id = outcome.get("recording_id")
        key, _kind = _item_key(item)
        row = connection.execute("SELECT outcome, reason, reported_by FROM run_items WHERE run_id = ? AND "
                                 "item_key = ?", (run_id, key)).fetchone()
        if row is None:
            position = int(connection.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM run_items WHERE "
                                              "run_id = ?", (run_id,)).fetchone()[0])
            _add_item(connection, run_id, item, position, now, word, reason, by,
                      int(recording_id) if recording_id else None)
            changed += 1
            continue
        if (row["outcome"], row["reason"] or "", row["reported_by"] or "") == (word, reason, by):
            continue
        connection.execute(
            "UPDATE run_items SET outcome = ?, reason = ?, reported_by = ?, updated_utc = ?, "
            "recording_id = COALESCE(?, recording_id) WHERE run_id = ? AND item_key = ?",
            (word, reason or None, by, now, int(recording_id) if recording_id else None, run_id, key))
        changed += 1
    return changed


# Copies, marks and the stopped run (244) --------------------------------------------------------
#
# Never use belongs to the copy: it follows a copy a scan finds renamed or moved, and a different file
# saved at its path inherits nothing. Done in Find my bug reports belongs to the content: a copy is done
# when it has its own mark, or when its bytes are still the ones the library read (confirmed) and an
# identical copy, by the full hash, has one (decision E). A sampled hash never shares anything. An old
# entry from settings.json the library cannot tie to a copy keeps working by its path, exactly as the old
# lists did, and is never given to whatever file is at that path now (242 correction 3).

MARK_NEVER_USE = "never_use"
MARK_BUGS_DONE = "bugs_done"
DONE_OUTCOMES = ("done", "no_narration")
BUG_REPORTS = "bug_reports"
# raw_bin_library.REPLACED_KEY_PREFIX (268): the key a place keeps once another recording holds its path.
REPLACED_KEY_PREFIX = "replaced:"
REGISTERED_BY_SCAN = "scan"
REGISTERED_OUTSIDE = "outside"
# The settings keys Find my bug reports kept its two lists and its stopped run in (114, 115), moved into
# the library once. media_manglers_workbench.recording_lists names the same keys.
LEGACY_NEVER_USE_KEY = "bug_report_excluded_recordings"
LEGACY_DONE_KEY = "bug_report_processed_recordings"
LEGACY_STOPPED_RUN_KEY = "bug_report_stopped_run"


def path_spellings(path: Any) -> set[str]:
    """Both spellings a recording's path is compared by (R5): the old lists' (its text lower-cased, as
    ``recording_lists.path_key`` does) and the library's (``path_key``: absolute, in the system's case)."""

    text = str(path or "") if isinstance(path, (str, os.PathLike)) else ""
    if not text.strip():
        return set()
    return {text.lower(), path_key(text)}


def _unchanged(path: Any, size: Any, modified: Any) -> bool:
    """Whether the file at ``path`` still has the size and modified time the library last read: a quick
    look at the file, nothing read from it."""

    try:
        stat = os.stat(str(path))
    except (OSError, ValueError):
        return False
    return (size is not None and modified is not None and int(stat.st_size) == int(size)
            and int(stat.st_mtime_ns) == int(modified))


def _set_resume_point(connection: sqlite3.Connection, feature: str, record: Any, now: str, *, run_id: str = "",
                      import_key: str | None = None) -> bool:
    """Replace the feature's stopped run with ``record`` ({"folder", "recordings", "tracks"}), or clear it
    when there is none, inside the caller's transaction. The one it replaces is kept, cleared."""

    connection.execute("UPDATE resume_points SET cleared_utc = ? WHERE feature = ? AND cleared_utc IS NULL",
                       (now, feature))
    if not isinstance(record, dict) or not str(record.get("folder") or "").strip():
        return False
    recordings = record.get("recordings")
    tracks = record.get("tracks")
    run = run_id if run_id and connection.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone() else None
    connection.execute(
        "INSERT INTO resume_points(feature, run_id, folder, recordings_json, tracks_json, import_key, created_utc) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (feature, run, str(record.get("folder")), json.dumps(recordings if isinstance(recordings, list) else []),
         json.dumps(tracks if isinstance(tracks, dict) else {}), import_key, now))
    return True


def is_stand_in(connection: sqlite3.Connection, location: Any) -> bool:
    """Whether the copy at ``location`` (a locations row) is one a list registered before any scan read it
    (``Records._locate``): it has no content yet, so the scan may still find it is a recording it knows."""

    if location is None or str(location["registered_by"] or REGISTERED_BY_SCAN) == REGISTERED_BY_SCAN:
        return False
    row = connection.execute("SELECT content_sha256 FROM recordings WHERE recording_id = ?",
                             (int(location["recording_id"]),)).fetchone()
    return row is not None and not row["content_sha256"]


def absorb_copy(connection: sqlite3.Connection, stand_in: int, into: int, *, by: str, size: int | None = None,
                modified: int | None = None) -> None:
    """A copy a list registered before any scan read it turned out to be ``into``, a recording the library
    already knew, renamed or moved. Inside the caller's transaction, its marks and what runs said about it go
    to that recording, and the stand-in is removed once no place is left on it. A Never use the recording
    already has is not doubled: the stand-in's own is cleared, with when and by whom."""

    if int(stand_in) == int(into):
        return
    if connection.execute("SELECT 1 FROM marks WHERE kind = ? AND recording_id = ? AND cleared_utc IS NULL",
                          (MARK_NEVER_USE, int(into))).fetchone():
        connection.execute("UPDATE marks SET cleared_utc = ?, cleared_by = ? WHERE kind = ? AND recording_id = ? "
                           "AND cleared_utc IS NULL", (_stamp(), by, MARK_NEVER_USE, int(stand_in)))
    connection.execute("UPDATE marks SET recording_id = ? WHERE recording_id = ?", (int(into), int(stand_in)))
    connection.execute("UPDATE run_items SET recording_id = ? WHERE recording_id = ?", (int(into), int(stand_in)))
    connection.execute("UPDATE run_products SET recording_id = ? WHERE recording_id = ?", (int(into), int(stand_in)))
    connection.execute("INSERT OR IGNORE INTO recording_labels(recording_id, label_id) SELECT ?, label_id FROM "
                       "recording_labels WHERE recording_id = ?", (int(into), int(stand_in)))
    connection.execute("UPDATE recordings SET duplicate_of = ? WHERE duplicate_of = ?", (int(into), int(stand_in)))
    # 264: what was measured about it and what the operator answered go with it: only what was made on the file the
    # scan just read (``size``, ``modified``). A different file of the same size saved over it since inherits nothing.
    row = connection.execute("SELECT content_sha256 FROM recordings WHERE recording_id = ?", (int(into),)).fetchone()
    merge_speech_facts(connection, int(stand_in), int(into), str(row["content_sha256"] or "") if row else "",
                       size=size, modified=modified)
    if not connection.execute("SELECT 1 FROM locations WHERE recording_id = ?", (int(stand_in),)).fetchone():
        connection.execute("DELETE FROM recordings WHERE recording_id = ?", (int(stand_in),))


def merge_speech_facts(connection: sqlite3.Connection, recording_id: int, into: int, content: str, *,
                       size: int | None = None, modified: int | None = None) -> None:
    """The facts a copy holds under its own number become the facts of ``into`` and, once the content is known, of
    that content, so exact copies share them (``speech_facts.attach_content``), inside the caller's transaction.
    With ``size`` and ``modified`` only facts made on that very file move: a file saved over the copy since inherits
    nothing. A measure the content already has stays; of two active answers the newer stays, the other is cleared."""

    same_file = "" if size is None or modified is None else " AND size_bytes = ? AND modified_ns = ?"
    file_values = () if not same_file else (int(size), int(modified))
    for row in connection.execute(
            f"SELECT measure_id FROM voice_measures WHERE recording_id = ? AND content_sha256 IS NULL{same_file}",
            (int(recording_id), *file_values)).fetchall():
        measure = int(row["measure_id"])
        kept = connection.execute(
            "SELECT measure_id FROM voice_measures WHERE " + ("content_sha256 = ?" if content else
                                                              "recording_id = ? AND content_sha256 IS NULL AND measure_id <> ?"),
            (content,) if content else (int(into), measure)).fetchone()
        if kept is not None:
            connection.execute("INSERT OR IGNORE INTO voice_decisions SELECT ?, voice_rule_version, roles_key, "
                               "preferred_key, status, chosen_track, confidence, decided_by, explanation, tracks_json, "
                               "details_json, decided_utc FROM voice_decisions WHERE measure_id = ?",
                               (int(kept["measure_id"]), measure))
            connection.execute("DELETE FROM voice_measures WHERE measure_id = ?", (measure,))
        elif content:
            connection.execute("UPDATE voice_measures SET content_sha256 = ?, recording_id = NULL WHERE measure_id = ?",
                               (content, measure))
        else:
            connection.execute("UPDATE voice_measures SET recording_id = ? WHERE measure_id = ?", (int(into), measure))
    # Cleared answers go along too (they stay on record); only one answer per recording can be active.
    for row in connection.execute(
            f"SELECT answer_id, answered_utc, cleared_utc FROM narration_answers WHERE recording_id = ? "
            f"AND content_sha256 IS NULL{same_file} ORDER BY answer_id", (int(recording_id), *file_values)).fetchall():
        answer = int(row["answer_id"])
        if row["cleared_utc"] is None:
            active = connection.execute(
                "SELECT answer_id, answered_utc FROM narration_answers WHERE cleared_utc IS NULL AND answer_id <> ? AND "
                + ("content_sha256 = ?" if content else "recording_id = ? AND content_sha256 IS NULL"),
                (answer, content if content else int(into))).fetchone()
            if active is not None:
                older = answer if str(row["answered_utc"]) < str(active["answered_utc"]) else int(active["answer_id"])
                connection.execute("UPDATE narration_answers SET cleared_utc = ?, cleared_by = 'same recording' "
                                   "WHERE answer_id = ?", (_stamp(), older))
        if content:
            connection.execute("UPDATE narration_answers SET content_sha256 = ?, recording_id = NULL WHERE answer_id = ?",
                               (content, answer))
        else:
            connection.execute("UPDATE narration_answers SET recording_id = ? WHERE answer_id = ?", (int(into), answer))


def copy_at(connection: sqlite3.Connection, path: Any) -> dict[str, Any] | None:
    """The copy the library holds at this path now, while the path is current, and whether the file is still the bytes
    the library read (``confirmed``): a quick look at the file, nothing read from it. None when it holds none."""

    row = connection.execute(
        "SELECT l.recording_id, l.size_bytes, l.modified_ns, l.is_current, r.content_sha256 FROM locations l "
        "JOIN recordings r ON r.recording_id = l.recording_id WHERE l.path_key = ?", (path_key(path),)).fetchone()
    if row is None or not row["is_current"]:
        return None
    content = str(row["content_sha256"] or "")
    return {"recording_id": int(row["recording_id"]), "content_sha256": content,
            "confirmed": bool(content) and _unchanged(path, row["size_bytes"], row["modified_ns"])}


def scanned_pick(connection: sqlite3.Connection, recording_id: int) -> dict[str, Any] | None:
    """What a raw bin scan stored about this copy's narration track, for ``speech_facts`` (design 2.3): the track, the
    Track roles it was worked out with and the track names. None when no scan picked one, or the scan failed."""

    row = connection.execute(
        "SELECT narration_track, rules_roles, track_titles_json, duration_seconds, audio_tracks, scan_error FROM recordings "
        "WHERE recording_id = ?", (int(recording_id),)).fetchone()
    if row is None or row["scan_error"] or not row["narration_track"]:
        return None
    return dict(row)


def copies_like(connection: sqlite3.Connection, size: int, modified_ns: int | None = None, *,
                modified_seconds: int | None = None) -> list[dict[str, Any]]:
    """The current, present copies the library holds of this size and modified time (to the nanosecond, or to the
    whole second an older record kept), with their content and whether the file is still the bytes the library
    read: what a moved recording may be now (242, Wave C2). A quick look at each file; nothing is read from it."""

    rows = connection.execute(
        "SELECT l.path, l.size_bytes, l.modified_ns, r.content_sha256, r.duration_seconds FROM locations l "
        "JOIN recordings r ON r.recording_id = l.recording_id WHERE l.is_current = 1 AND l.missing = 0 "
        "AND l.size_bytes = ? ORDER BY l.path", (int(size),)).fetchall()
    found = []
    for row in rows:
        stored = int(row["modified_ns"] or 0)
        if modified_ns is not None and stored != int(modified_ns):
            continue
        if modified_seconds is not None and stored // 1_000_000_000 != int(modified_seconds):
            continue
        content = str(row["content_sha256"] or "")
        found.append({"path": str(row["path"]), "content_sha256": content,
                      "duration_seconds": row["duration_seconds"],
                      "confirmed": bool(content) and _unchanged(row["path"], row["size_bytes"], row["modified_ns"])})
    return found


# The AI Video Editor's index (242, Wave C2) --------------------------------------------------------------------
EDITOR_ROOT_KIND = "editor_output"
LINK_BOUND, LINK_UNBOUND, LINK_UNAVAILABLE = "bound", "unbound", "unavailable"
_EDITOR_PROJECT_FIELDS = ("content_sha256", "recording_id", "edit_of", "link_state", "bound_utc", "bound_how")
_EDITOR_VERSION_FIELDS = ("created", "editor_label", "preview_passed", "final_passed", "exported", "documents_json",
                          "state")


def _changed(row: Any, values: dict[str, Any], fields: Iterable[str]) -> bool:
    return row is None or any(row[name] != values[name] for name in fields)


def index_editor_projects(connection: sqlite3.Connection, output_root: Path | str, projects: Iterable[dict[str, Any]],
                          *, only: str | None = None) -> int:
    """Make the index of the editor's projects under ``output_root`` match ``projects``, what their own files say
    (``race_video.library.reconcile``), in one transaction. Each is a dict: ``relative_path`` (inside the output
    folder), ``source`` (its recording's path, used only to find the copy), ``content_sha256``, ``edit_of``,
    ``link_state``, ``bound_utc``, ``bound_how`` and ``versions`` (each ``version``, ``created``, ``editor_label``,
    ``preview_passed``, ``final_passed``, ``exported`` and ``documents``).

    A row changes only when what it says changes, so running it twice changes nothing. A project or version that is
    no longer on disk becomes unavailable and is never deleted. With ``only`` (one project's relative path), only that
    project is looked at. Returns how many rows changed."""

    now = _stamp()
    changed = 0
    # Only what changed is written, so when nothing did, no write is started and nothing waits on another writer (a
    # scan, or an agent's command at that moment; Wave C2 review).
    with connection:
        root = connection.execute("SELECT root_id FROM roots WHERE kind = ? AND path_key = ?",
                                  (EDITOR_ROOT_KIND, path_key(output_root))).fetchone()
        root_id = int(root[0]) if root else int(connection.execute(
            "INSERT INTO roots(kind, path, path_key, first_seen_utc, last_seen_utc) VALUES (?, ?, ?, ?, ?)",
            (EDITOR_ROOT_KIND, str(output_root), path_key(output_root), now, now)).lastrowid)
        seen: set[str] = set()
        for project in projects:
            relative = str(project["relative_path"])
            if only is not None and relative != only:
                continue
            seen.add(relative)
            copy = copy_at(connection, project["source"]) if project.get("source") else None
            values = {"content_sha256": str(project.get("content_sha256") or "") or None,
                      "recording_id": copy["recording_id"] if copy else None,
                      "edit_of": str(project.get("edit_of") or ""), "link_state": str(project["link_state"]),
                      "bound_utc": project.get("bound_utc") or None, "bound_how": project.get("bound_how") or None}
            row = connection.execute("SELECT * FROM editor_projects WHERE root_id = ? AND relative_path = ?",
                                     (root_id, relative)).fetchone()
            if row is None:
                project_id = int(connection.execute(
                    "INSERT INTO editor_projects(root_id, relative_path, content_sha256, recording_id, edit_of, link_state, "
                    "bound_utc, bound_how, checked_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (root_id, relative, *(values[name] for name in _EDITOR_PROJECT_FIELDS), now)).lastrowid)
                changed += 1
            else:
                project_id = int(row["project_id"])
                if _changed(row, values, _EDITOR_PROJECT_FIELDS):
                    connection.execute(
                        "UPDATE editor_projects SET " + ", ".join(f"{name} = ?" for name in _EDITOR_PROJECT_FIELDS)
                        + ", checked_utc = ? WHERE project_id = ?",
                        (*(values[name] for name in _EDITOR_PROJECT_FIELDS), now, project_id))
                    changed += 1
            numbers = set()
            for version in project.get("versions") or []:
                number = int(version["version"])
                numbers.add(number)
                passed = {name: None if version.get(name) is None else int(bool(version[name]))
                          for name in ("preview_passed", "final_passed")}
                wanted = {"created": str(version.get("created") or ""), "editor_label": str(version.get("editor_label") or ""),
                          **passed, "exported": int(bool(version.get("exported"))),
                          "documents_json": json.dumps(sorted(version.get("documents") or [])), "state": "present"}
                have = connection.execute("SELECT * FROM editor_versions WHERE project_id = ? AND version = ?",
                                          (project_id, number)).fetchone()
                if not _changed(have, wanted, _EDITOR_VERSION_FIELDS):
                    continue
                connection.execute(
                    "INSERT INTO editor_versions(project_id, version, " + ", ".join(_EDITOR_VERSION_FIELDS)
                    + ", checked_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(project_id, version) DO UPDATE SET "
                    + ", ".join(f"{name} = excluded.{name}" for name in _EDITOR_VERSION_FIELDS) + ", checked_utc = excluded.checked_utc",
                    (project_id, number, *(wanted[name] for name in _EDITOR_VERSION_FIELDS), now))
                changed += 1
            kept = f" AND version NOT IN ({', '.join('?' for _ in numbers)})" if numbers else ""
            where = f"WHERE project_id = ? AND state <> 'unavailable'{kept}"
            if connection.execute(f"SELECT 1 FROM editor_versions {where} LIMIT 1", (project_id, *sorted(numbers))).fetchone():
                changed += connection.execute(f"UPDATE editor_versions SET state = 'unavailable', checked_utc = ? {where}",
                                              (now, project_id, *sorted(numbers))).rowcount
        gone = [row for row in connection.execute(
            "SELECT project_id, relative_path FROM editor_projects WHERE root_id = ? AND link_state <> ?",
            (root_id, LINK_UNAVAILABLE)) if row["relative_path"] not in seen and (only is None or row["relative_path"] == only)]
        for row in gone:
            connection.execute("UPDATE editor_projects SET link_state = ?, checked_utc = ? WHERE project_id = ?",
                               (LINK_UNAVAILABLE, now, int(row["project_id"])))
            connection.execute("UPDATE editor_versions SET state = 'unavailable', checked_utc = ? WHERE project_id = ? "
                               "AND state <> 'unavailable'", (now, int(row["project_id"])))
            changed += 1
    return changed


def editor_index(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    """The editor's index as it stands: each project with its folder's root and its versions."""

    found = []
    for row in connection.execute("SELECT p.*, r.path AS root_path FROM editor_projects p JOIN roots r ON "
                                  "r.root_id = p.root_id ORDER BY p.project_id"):
        item = dict(row)
        item["versions"] = [dict(version) for version in connection.execute(
            "SELECT * FROM editor_versions WHERE project_id = ? ORDER BY version", (int(row["project_id"]),))]
        found.append(item)
    return found


def register_copy(connection: sqlite3.Connection, path: Any) -> dict[str, Any] | None:
    """The copy at ``path``, registered as "outside" when no scan has read it (``Records._locate_in``), inside the
    caller's transaction."""

    Records._locate_in(connection, path, register_outside=True, now=_stamp())
    return copy_at(connection, path)


class Records:
    """The Workbench's open library: every run and what it did (243).

    One per Workbench window, opened when the window starts. It holds a session file the system lets go
    of when the app ends however it ends, so the next start can tell a run cut off by a crash or a close
    from one another open Workbench is still running.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or library_root())
        self._connection: sqlite3.Connection | None = connect(self.root)
        self.session = uuid.uuid4().hex
        sessions = self.root / SESSIONS
        self._session_path = sessions / f"{self.session}.lock"
        self._session_handle: Any = None
        try:
            sessions.mkdir(parents=True, exist_ok=True)
            self._session_handle = open(self._session_path, "a+b")
            _lock_now(self._session_handle)
        except BaseException:
            # 224 (Wave B2a, note 3): a library the window cannot use is never left open behind it.
            self.close()
            raise

    # Opening and closing ---------------------------------------------------------------------------

    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise ValueError("The library is closed.")
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        if self._session_handle is not None:
            self._session_handle.close()
            self._session_handle = None
            try:
                self._session_path.unlink(missing_ok=True)
            except OSError:
                pass

    # Writing a run ---------------------------------------------------------------------------------

    def open_run(self, *, kind: str, title: str, workflow: str = "", origin: str = "", profile: str = "",
                 source: str = "", output: str = "", log: str = "", items: Iterable[str] = (),
                 feature_ref: str = "", run_id: str = "") -> str:
        """Write a run before it starts, with one item per recording, folder or web address. A recording's
        size and modified time are noted from a quick look at the file; nothing is read from it."""

        kind = kind if kind in RUN_KINDS else "other"
        # A page may name the run itself, when the run's own request must carry its number (a raw bin scan).
        run_id = run_id or uuid.uuid4().hex
        now = _stamp()
        connection = self.connection()
        with connection:
            connection.execute(
                "INSERT INTO runs(run_id, kind, feature, title, workflow, origin, profile, source, output, log, "
                "started_utc, started_local, process_status, state, state_source, owner_session, feature_ref, "
                "updated_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'runner', ?, ?, ?)",
                (run_id, kind, RUN_KINDS.get(kind), title, workflow, origin, profile, source, output, log, now,
                 _local_minute(), RUNNING, UNKNOWN, self.session, feature_ref or None, now))
            for position, item in enumerate(items, start=1):
                _add_item(connection, run_id, str(item), position, now)
        return run_id

    def end_run(self, run_id: str, *, process_status: str, exit_code: int | None = None, partial: bool = False,
                **shown: str) -> None:
        """The run's process ended: what the runner saw, and a first state by the one status rule. A state
        a feature already set is kept. ``shown`` updates what History shows (title, workflow, profile,
        source, output, log), which a run may only know at its end."""

        connection = self.connection()
        now = _stamp()
        fields = {key: str(value) for key, value in shown.items()
                  if key in ("title", "workflow", "profile", "source", "output", "log") and value is not None}
        with connection:
            row = connection.execute("SELECT state_source FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                return
            sets = ["process_status = ?", "exit_code = ?", "ended_utc = ?", "finished_local = ?", "updated_utc = ?"]
            values: list[Any] = [process_status, exit_code, now, _local_minute(), now]
            if str(row["state_source"] or "runner") == "runner":
                sets += ["state = ?"]
                values += [_runner_state(process_status, partial)]
            for key, value in fields.items():
                sets.append(f"{key} = ?")
                values.append(value)
            connection.execute(f"UPDATE runs SET {', '.join(sets)} WHERE run_id = ?", (*values, run_id))
            output = fields.get("output")
            if output:
                self._link_product(connection, run_id, "output_folder", output, now)

    def _link_product(self, connection: sqlite3.Connection, run_id: str, kind: str, path: str, now: str) -> None:
        """A folder a run made, relative to a registered root when it is inside one (242)."""

        root_id, relative = None, None
        target = path_key(path)
        for root in connection.execute("SELECT root_id, path_key FROM roots"):
            base = str(root["path_key"]).rstrip("\\/")
            if target == base or target.startswith(base + os.sep):
                root_id, relative = int(root["root_id"]), os.path.relpath(target, base)
                break
        connection.execute(
            "INSERT OR IGNORE INTO run_products(run_id, kind, root_id, relative_path, path, status, checked_utc) "
            "VALUES (?, ?, ?, ?, ?, 'unchecked', ?)", (run_id, kind, root_id, relative, path, now))

    def register_root(self, kind: str, path: str) -> None:
        """A folder generated products live under (the main output folder, the library)."""

        if not str(path or "").strip():
            return
        now = _stamp()
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO roots(kind, path, path_key, first_seen_utc, last_seen_utc) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(kind, path_key) DO UPDATE SET last_seen_utc = excluded.last_seen_utc",
                (kind, str(path), path_key(path), now, now))

    def record_outcomes(self, run_id: str, outcomes: Iterable[dict[str, Any]], *, reported_by: str) -> int:
        """Each recording's outcome, written by the feature that knows it. The same outcome again changes
        nothing; a different one corrects the earlier. Returns how many items changed."""

        connection = self.connection()
        with connection:
            return write_outcomes(connection, run_id, outcomes, reported_by=reported_by)

    def finish_run(self, run_id: str, state: str, *, headline: str = "", reported_by: str = "feature",
                   counts: dict[str, Any] | None = None) -> bool:
        """The run's final state from the feature that knows it. Calling it again with the same state changes
        nothing; a different state corrects the earlier one, which is kept in ``run_events``."""

        if state not in RUN_STATES:
            raise ValueError(f"Unknown run state {state!r}")
        connection = self.connection()
        now = _stamp()
        with connection:
            row = connection.execute("SELECT state, state_source, headline FROM runs WHERE run_id = ?",
                                     (run_id,)).fetchone()
            if row is None:
                return False
            same = (row["state"], row["state_source"]) == (state, reported_by)
            if same and (not headline or headline == (row["headline"] or "")) and counts is None:
                return False
            if row["state"] != state:
                connection.execute("INSERT INTO run_events(run_id, at_utc, old_state, new_state, source) VALUES "
                                   "(?, ?, ?, ?, ?)", (run_id, now, row["state"], state, reported_by))
            connection.execute(
                "UPDATE runs SET state = ?, state_source = ?, headline = COALESCE(?, headline), "
                "counts_json = COALESCE(?, counts_json), updated_utc = ? WHERE run_id = ?",
                (state, reported_by, headline or None, json.dumps(counts) if counts is not None else None, now,
                 run_id))
        return True

    def sweep_interrupted(self) -> int:
        """Runs still marked running whose Workbench is gone become Interrupted. A run another open
        Workbench is running is left alone."""

        connection = self.connection()
        now = _stamp()
        swept = 0
        sessions: dict[str, bool] = {}
        rows = connection.execute("SELECT run_id, owner_session FROM runs WHERE process_status = ?",
                                  (RUNNING,)).fetchall()
        for row in rows:
            owner = str(row["owner_session"] or "")
            if owner == self.session:
                continue
            if owner not in sessions:
                sessions[owner] = _session_alive(self.root, owner)
            if sessions[owner]:
                continue
            with connection:
                done = connection.execute(
                    "UPDATE runs SET process_status = ?, state = ?, state_source = 'start-up', updated_utc = ? "
                    "WHERE run_id = ? AND process_status = ?",
                    (INTERRUPTED, INTERRUPTED, now, row["run_id"], RUNNING)).rowcount
                if done:
                    connection.execute(
                        "INSERT INTO run_events(run_id, at_utc, old_state, new_state, source, note) VALUES "
                        "(?, ?, ?, ?, 'start-up', 'The app closed or stopped before the run ended.')",
                        (row["run_id"], now, UNKNOWN, INTERRUPTED))
                    swept += 1
        for owner, alive in sessions.items():
            if not alive and owner:
                try:
                    (self.root / SESSIONS / f"{owner}.lock").unlink(missing_ok=True)
                except OSError:
                    pass
        return swept

    # Reading runs ----------------------------------------------------------------------------------

    def _where(self, include_running: bool) -> str:
        return "" if include_running else f"WHERE process_status <> '{RUNNING}'"

    def list_runs(self, *, limit: int = 200, offset: int = 0, include_running: bool = False) -> list[dict[str, Any]]:
        """History, newest first: every run, in pages."""

        rows = self.connection().execute(
            f"SELECT * FROM runs {self._where(include_running)} "
            "ORDER BY COALESCE(ended_utc, started_utc) DESC, rowid DESC LIMIT ? OFFSET ?",
            (max(0, int(limit)), max(0, int(offset)))).fetchall()
        return [_history_entry(row) for row in rows]

    def count_runs(self, *, include_running: bool = False) -> int:
        return int(self.connection().execute(f"SELECT COUNT(*) FROM runs {self._where(include_running)}").fetchone()[0])

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.connection().execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def get_history_entry(self, run_id: str) -> dict[str, Any] | None:
        row = self.connection().execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return _history_entry(row) if row else None

    def run_items(self, run_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection().execute(
            "SELECT * FROM run_items WHERE run_id = ? ORDER BY position", (run_id,))]

    def import_legacy_runs(self, entries: Any) -> dict[str, int]:
        """The run history settings.json kept (243), moved in once: each entry as an old run, with the
        fields History showed and its status word, its details unknown (no start time, no recordings).
        Importing the same entries again adds nothing. Returns how many were read, added and already there."""

        connection = self.connection()
        with connection:
            return _insert_legacy_runs(connection, entries)

    def set_feature_ref(self, run_id: str, ref: str) -> None:
        """The feature's own name for the run (the Inbox's orchestration run), kept with it."""

        with self.connection() as connection:
            connection.execute("UPDATE runs SET feature_ref = ?, updated_utc = ? WHERE run_id = ?",
                               (ref or None, _stamp(), run_id))

    def counted_in_earlier_runs(self, ref: str, run_id: str) -> set[str]:
        """The recordings earlier runs with the same feature reference already counted (path keys)."""

        if not ref:
            return set()
        return {str(row[0]) for row in self.connection().execute(
            "SELECT i.item_key FROM run_items i JOIN runs r ON r.run_id = i.run_id WHERE r.feature_ref = ? "
            "AND r.run_id <> ? AND i.outcome <> ?", (ref, run_id, OUTCOME_CANCELLED))}

    def run_events(self, run_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection().execute(
            "SELECT * FROM run_events WHERE run_id = ? ORDER BY event_id", (run_id,))]

    # Copies (244) ---------------------------------------------------------------------------------

    @staticmethod
    def _copy_at(connection: sqlite3.Connection, path: Any) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT l.location_id, l.recording_id, l.path, l.size_bytes, l.modified_ns, l.is_current, l.missing, "
            "l.registered_by, r.content_sha256 FROM locations l JOIN recordings r ON r.recording_id = l.recording_id "
            "WHERE l.path_key = ?", (path_key(path),)).fetchone()

    def _locate(self, connection: sqlite3.Connection, path: Any, *, register_outside: bool,
                now: str) -> sqlite3.Row | None:
        return self._locate_in(connection, path, register_outside=register_outside, now=now)

    @classmethod
    def _locate_in(cls, connection: sqlite3.Connection, path: Any, *, register_outside: bool,
                   now: str) -> sqlite3.Row | None:
        """The copy at ``path`` now, inside the caller's transaction. With ``register_outside``, a file no scan
        has read gets a copy of its own, marked "outside", from a quick look at its size and time: nothing is
        read from the file, and the raw bin does not list it. So does a file saved over a known path since the
        library last looked (another size, as the scan tells it, 268), so a mark made now is not given to the
        copy whose bytes were there before."""

        found = cls._copy_at(connection, path)
        saved_over = False
        if found is not None and found["is_current"]:
            if not register_outside:
                return found
            saved_over = cls._saved_over(found, path)
            if not saved_over:
                return found
        if not register_outside:
            return None
        if found is not None:
            # The copy that had this path lives elsewhere now, or another file was saved over it: its old
            # place keeps its record under a key no path can have (268), shown Missing when it was saved
            # over, and the file here is a copy of its own.
            connection.execute("UPDATE locations SET path_key = ?, missing = MAX(missing, ?) WHERE location_id = ?",
                               (f"{REPLACED_KEY_PREFIX}{int(found['location_id'])}:{path_key(path)}",
                                int(saved_over), int(found["location_id"])))
        try:
            stat = os.stat(str(path))
            size, modified = int(stat.st_size), int(stat.st_mtime_ns)
        except (OSError, ValueError):
            size = modified = 0
        recording_id = int(connection.execute("INSERT INTO recordings(first_seen_utc, size_bytes) VALUES (?, ?)",
                                              (now, size)).lastrowid)
        connection.execute(
            "INSERT INTO locations(recording_id, path, path_key, root_key, size_bytes, modified_ns, is_current, missing, "
            "first_seen_utc, last_seen_utc, registered_by) VALUES (?, ?, ?, '', ?, ?, 1, 0, ?, ?, ?)",
            (recording_id, str(path), path_key(path), size, modified, now, now, REGISTERED_OUTSIDE))
        return cls._copy_at(connection, path)

    @staticmethod
    def _saved_over(found: sqlite3.Row, path: Any) -> bool:
        """Whether the file at ``path`` now has another size than the copy the library knows there."""

        try:
            size = int(os.stat(str(path)).st_size)
        except (OSError, ValueError):
            return False
        return bool(found["size_bytes"]) and size != int(found["size_bytes"])

    def locate(self, path: Any, *, register_outside: bool = False) -> dict[str, Any] | None:
        """The copy at ``path``, and how sure the library is: ``confirmed`` when the library read that copy
        and the file still has the size and modified time it had then; otherwise it is the copy by its path
        only. None when no copy is there (unless ``register_outside``). The recordings drive is only looked at,
        never read."""

        connection = self.connection()
        if register_outside:
            with connection:
                row = self._locate(connection, path, register_outside=True, now=_stamp())
        else:
            row = self._locate(connection, path, register_outside=False, now="")
        if row is None:
            return None
        return {
            "recording_id": int(row["recording_id"]),
            "path": str(row["path"]),
            "registered_by": str(row["registered_by"] or REGISTERED_BY_SCAN),
            "content_sha256": str(row["content_sha256"] or ""),
            "missing": bool(row["missing"]),
            "confirmed": bool(row["content_sha256"]) and _unchanged(path, row["size_bytes"], row["modified_ns"]),
        }

    # Never use (244) ------------------------------------------------------------------------------

    @staticmethod
    def _never_use_keys(connection: sqlite3.Connection) -> set[str]:
        keys: set[str] = set()
        for row in connection.execute(
                "SELECT l.path, l.path_key FROM marks m JOIN locations l ON l.recording_id = m.recording_id "
                "WHERE m.kind = ? AND m.cleared_utc IS NULL AND l.is_current = 1 AND l.path_key NOT LIKE ?",
                (MARK_NEVER_USE, REPLACED_KEY_PREFIX + "%")):
            keys |= {str(row["path"]).lower(), str(row["path_key"])}
        for row in connection.execute(
                "SELECT old_key, old_path FROM marks WHERE kind = ? AND cleared_utc IS NULL AND recording_id IS NULL",
                (MARK_NEVER_USE,)):
            keys |= {str(row["old_key"])} | path_spellings(row["old_path"])
        return keys

    def never_use_keys(self) -> set[str]:
        """The never-use list as the old ``recording_lists.excluded_keys`` answered it: every spelling of the
        path of each never-use copy where it is now, and of each old entry's path."""

        return self._never_use_keys(self.connection())

    def set_never_use(self, path: Any, on: bool, *, by: str, mark_ids: Iterable[int] = ()) -> bool:
        """Put the copy at ``path`` on the never-use list (True when it was not on it yet), or take it off
        (True when it was on it): its own mark, any old entry for this path, and the marks ``mark_ids`` names
        (a copy whose file was replaced since). A mark taken off is kept, with when and by whom."""

        wanted = path_spellings(path)
        connection = self.connection()
        now = _stamp()
        with connection:
            if on:
                if not wanted or wanted & self._never_use_keys(connection):
                    return False
                copy = self._locate(connection, path, register_outside=True, now=now)
                connection.execute("INSERT INTO marks(kind, recording_id, set_by, created_utc) VALUES (?, ?, ?, ?)",
                                   (MARK_NEVER_USE, int(copy["recording_id"]), by, now))
                return True
            named = {int(mark) for mark in mark_ids}
            copy = self._locate(connection, path, register_outside=False, now=now) if wanted else None
            cleared: list[int] = []
            for row in connection.execute(
                    "SELECT mark_id, recording_id, old_key, old_path FROM marks WHERE kind = ? AND cleared_utc IS NULL",
                    (MARK_NEVER_USE,)).fetchall():
                if row["recording_id"] is not None:
                    hit = copy is not None and int(row["recording_id"]) == int(copy["recording_id"])
                else:
                    hit = bool(wanted & ({str(row["old_key"])} | path_spellings(row["old_path"])))
                if hit or int(row["mark_id"]) in named:
                    cleared.append(int(row["mark_id"]))
            for mark in cleared:
                connection.execute("UPDATE marks SET cleared_utc = ?, cleared_by = ? WHERE mark_id = ?", (now, by, mark))
            return bool(cleared)

    def never_use_entries(self) -> list[dict[str, Any]]:
        """The Never-use list... dialog's rows, oldest first: each mark's ID, the path to show (where a moved
        copy is now; an old entry's path as it was written) and whether it is an old entry."""

        entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in self.connection().execute(
                "SELECT m.mark_id, m.recording_id, m.old_path, "
                "(SELECT l.path FROM locations l WHERE l.recording_id = m.recording_id AND l.is_current = 1 "
                " AND l.path_key NOT LIKE ? ORDER BY l.missing, l.last_seen_utc DESC LIMIT 1) AS current_path, "
                "(SELECT l.path FROM locations l WHERE l.recording_id = m.recording_id "
                " ORDER BY l.is_current DESC, l.last_seen_utc DESC LIMIT 1) AS last_path "
                "FROM marks m WHERE m.kind = ? AND m.cleared_utc IS NULL ORDER BY m.mark_id",
                (REPLACED_KEY_PREFIX + "%", MARK_NEVER_USE)):
            shown = str(row["current_path"] or row["old_path"] or row["last_path"] or "")
            if not shown or shown.lower() in seen:
                continue
            seen.add(shown.lower())
            entries.append({"mark_id": int(row["mark_id"]), "path": shown, "old": row["recording_id"] is None})
        return entries

    # Done in Find my bug reports (244) ------------------------------------------------------------

    def done_dates(self) -> dict[str, str]:
        """The already-done map as the old ``recording_lists.processed_dates`` answered it: every spelling of
        the path of each done copy where it is now, of each copy that holds the same confirmed content as a
        done one (its file looked at, never read), and of each old entry's path, with the newest date."""

        connection = self.connection()
        dates: dict[str, str] = {}

        def put(keys: set[str], day: str) -> None:
            for key in keys:
                if day > dates.get(key, ""):
                    dates[key] = day

        own = {int(row[0]): str(row[1] or "") for row in connection.execute(
            "SELECT recording_id, MAX(mark_date) FROM marks WHERE kind = ? AND cleared_utc IS NULL AND recording_id "
            "IS NOT NULL GROUP BY recording_id", (MARK_BUGS_DONE,))}
        shared = {str(row[0]): str(row[1] or "") for row in connection.execute(
            "SELECT r.content_sha256, MAX(m.mark_date) FROM marks m JOIN recordings r ON r.recording_id = m.recording_id "
            "WHERE m.kind = ? AND m.cleared_utc IS NULL AND COALESCE(r.content_sha256, '') <> '' "
            "GROUP BY r.content_sha256", (MARK_BUGS_DONE,))}
        for row in connection.execute(
                "SELECT l.recording_id, l.path, l.path_key, l.size_bytes, l.modified_ns, l.missing, r.content_sha256 "
                "FROM locations l JOIN recordings r ON r.recording_id = l.recording_id WHERE l.is_current = 1 "
                "AND l.path_key NOT LIKE ?", (REPLACED_KEY_PREFIX + "%",)):
            spellings = {str(row["path"]).lower(), str(row["path_key"])}
            mine = own.get(int(row["recording_id"]), "")
            if mine:
                put(spellings, mine)
            others = shared.get(str(row["content_sha256"] or ""), "")
            # A copy the last scan found missing is not looked for (a drive that is not there can be slow to say so).
            if others > mine and not row["missing"] and _unchanged(row["path"], row["size_bytes"], row["modified_ns"]):
                put(spellings, others)
        for row in connection.execute(
                "SELECT old_key, old_path, mark_date FROM marks WHERE kind = ? AND cleared_utc IS NULL AND recording_id "
                "IS NULL", (MARK_BUGS_DONE,)):
            put({str(row["old_key"])} | path_spellings(row["old_path"]), str(row["mark_date"] or ""))
        return dates

    def done_on(self, path: Any, *, look: bool = True) -> str:
        """The day the recording at ``path`` was done ("" when it never was), as ``done_dates`` would say.
        Without ``look`` the file is not looked at, so a copy that is only done through an identical copy
        says nothing yet."""

        connection = self.connection()
        wanted = path_spellings(path)
        best = ""
        copy = self._copy_at(connection, path) if wanted else None
        if copy is not None and copy["is_current"]:
            best = str(connection.execute(
                "SELECT MAX(mark_date) FROM marks WHERE kind = ? AND cleared_utc IS NULL AND recording_id = ?",
                (MARK_BUGS_DONE, int(copy["recording_id"]))).fetchone()[0] or "")
            if look and copy["content_sha256"]:
                others = str(connection.execute(
                    "SELECT MAX(m.mark_date) FROM marks m JOIN recordings r ON r.recording_id = m.recording_id WHERE "
                    "m.kind = ? AND m.cleared_utc IS NULL AND r.content_sha256 = ? AND m.recording_id <> ?",
                    (MARK_BUGS_DONE, str(copy["content_sha256"]), int(copy["recording_id"]))).fetchone()[0] or "")
                if others > best and _unchanged(path, copy["size_bytes"], copy["modified_ns"]):
                    best = others
        for row in connection.execute(
                "SELECT old_key, old_path, mark_date FROM marks WHERE kind = ? AND cleared_utc IS NULL AND recording_id "
                "IS NULL", (MARK_BUGS_DONE,)):
            if wanted & ({str(row["old_key"])} | path_spellings(row["old_path"])):
                best = max(best, str(row["mark_date"] or ""))
        return best

    def mark_done(self, run_id: str, rows: Iterable[tuple[Any, str]], *, by: str, day: str | None = None) -> int:
        """Done in Find my bug reports, one mark per recording ("done" or "no_narration"), dated ``day`` (today
        by default), with the run it came from. Returns how many were written."""

        connection = self.connection()
        now = _stamp()
        day = day or date.today().isoformat()
        written = 0
        with connection:
            run = run_id if run_id and connection.execute("SELECT 1 FROM runs WHERE run_id = ?",
                                                          (run_id,)).fetchone() else None
            for path, outcome in rows:
                if outcome not in DONE_OUTCOMES:
                    raise ValueError(f"Not a Find my bug reports outcome: {outcome!r}")
                copy = self._locate(connection, path, register_outside=True, now=now)
                connection.execute(
                    "INSERT INTO marks(kind, recording_id, outcome, mark_date, run_id, set_by, created_utc) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)", (MARK_BUGS_DONE, int(copy["recording_id"]), outcome, day, run, by, now))
                written += 1
        return written

    # The stopped run Continue picks up (115, 244) ------------------------------------------------

    def stopped_bug_run(self) -> dict[str, Any] | None:
        """Find my bug reports' stopped run, the same {"folder", "recordings", "tracks"} it was given."""

        row = self.connection().execute(
            "SELECT folder, recordings_json, tracks_json FROM resume_points WHERE feature = ? AND cleared_utc IS NULL",
            (BUG_REPORTS,)).fetchone()
        if row is None:
            return None
        try:
            recordings, tracks = json.loads(row["recordings_json"]), json.loads(row["tracks_json"])
        except ValueError:
            recordings, tracks = [], {}
        return {"folder": str(row["folder"]), "recordings": recordings if isinstance(recordings, list) else [],
                "tracks": tracks if isinstance(tracks, dict) else {}}

    def set_stopped_bug_run(self, record: dict[str, Any] | None, *, run_id: str = "") -> None:
        """Keep a stopped run for Continue, or clear it (None)."""

        connection = self.connection()
        with connection:
            _set_resume_point(connection, BUG_REPORTS, record, _stamp(), run_id=run_id)

    def list_recordings(self) -> list[dict[str, Any]]:
        """The raw bin's list with what mined each recording (``list_library``)."""

        return list_library(self.connection())


# The one-time move out of settings.json (242, 243, 244) --------------------------------------
#
# Wave A1 moves the run history (``recent_runs``); Wave A2 moves Find my bug reports' never-use list, its
# already-done map and its stopped run, and takes the stray copies of them out of custom profiles. Before
# anything changes, settings.json, every custom profile and the library are copied into a backup folder of
# their own; everything is imported (twice is the same as once: each old entry has its own key, kept even
# after its mark is cleared, so a cleared mark never comes back) and checked; only then are the moved keys
# taken out of settings.json and the profiles, written safely and read back. A move that fails leaves the
# library as it was and settings.json and the profiles untouched; a cleaning that cannot be finished now is
# finished at the next start, when the same entries import as nothing new.

MOVED_SETTINGS_KEYS = ("recent_runs", LEGACY_NEVER_USE_KEY, LEGACY_DONE_KEY, LEGACY_STOPPED_RUN_KEY)
# What a custom profile can hold a stray copy of (Save profile as copied the window's settings into it).
# Never read back from a profile, so it is removed after the backup. Built-in profiles are never touched.
PROFILE_STRAY_KEYS = (LEGACY_STOPPED_RUN_KEY, LEGACY_NEVER_USE_KEY, LEGACY_DONE_KEY, "recent_runs")
MOVED_BY = "settings.json move"
MOVE_LOCK = "migration.lock"
HOW_TO_RESTORE = """How to put back what the Workbench changed on {when}

The Workbench moved your run history, Find my bug reports' never-use list, its already-done list and its
stopped run out of settings.json into its library, and took the stray copies of them out of your own
profiles. Before it changed anything it copied all of them here, and checked the copies:

  settings.json            your settings file as it was
  raw-bin-library.sqlite   the library as it was
  profiles\\               each of your own profiles as it was (when you have any)

To put them back:
  1. Close the Workbench.
  2. Copy settings.json over the one in your settings folder:
       {settings}
  3. Copy raw-bin-library.sqlite over the one in the library folder, and delete the files beside it named
     raw-bin-library.sqlite-wal and raw-bin-library.sqlite-shm if they are there:
       {library}
  4. Copy the files in profiles\\ over the ones with the same names in your profiles folder:
       {profiles}
  5. Start the Workbench again.

BACKUP_MANIFEST.json lists each copy's SHA-256.
"""
HOW_TO_RESTORE_PROFILES = """How to put back what the Workbench changed on {when}

The Workbench took stray copies of Find my bug reports' lists and stopped run out of your own profiles (the
lists themselves are kept in its library). Before it changed anything it copied each of those profiles here,
and checked the copies:

  profiles\\               each of those profiles as it was

To put them back:
  1. Close the Workbench.
  2. Copy the files in profiles\\ over the ones with the same names in your profiles folder:
       {profiles}
  3. Start the Workbench again.

BACKUP_MANIFEST.json lists each copy's SHA-256.
"""


def _sha256(data: bytes) -> str:
    import hashlib  # noqa: PLC0415

    return hashlib.sha256(data).hexdigest()


def _settings_part(payload: Any) -> dict[str, Any] | None:
    """The settings inside a settings.json payload, the way the Workbench reads it."""

    if not isinstance(payload, dict):
        return None
    inner = payload.get("settings") if "settings" in payload else payload
    return inner if isinstance(inner, dict) else None


def _holds(value: Any) -> bool:
    return value not in (None, [], {}, "")


def _custom_profiles(profiles_dir: Path | str | None) -> list[tuple[Path, bytes, dict[str, Any]]]:
    """Every custom profile in ``profiles_dir`` that can be read: its file, its bytes and what it holds.
    Built-in profiles are left out (they are never touched); so is a file that cannot be read."""

    found: list[tuple[Path, bytes, dict[str, Any]]] = []
    if not profiles_dir or not Path(profiles_dir).is_dir():
        return found
    for path in sorted(Path(profiles_dir).glob("*.json")):
        try:
            data = path.read_bytes()
            payload = json.loads(data.decode("utf-8-sig"))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if isinstance(payload, dict) and payload.get("profileType") != "built-in" \
                and isinstance(payload.get("settings"), dict):
            found.append((path, data, payload))
    return found


def _has_strays(profile: tuple[Path, bytes, dict[str, Any]]) -> bool:
    return any(key in profile[2]["settings"] for key in PROFILE_STRAY_KEYS)


def import_legacy_settings(records: Records, settings_path: Path | str,
                           profiles_dir: Path | str | None = None) -> dict[str, Any]:
    """Move what Waves A1 and A2 move out of ``settings_path`` (and the stray copies out of the custom
    profiles in ``profiles_dir``) into the library. Returns what happened: ``status`` is "nothing"
    (nothing to move), "moved", "imported" (moved, the cleaning left for the next start), "refused" (an
    unreadable settings.json, kept as it is), "busy" (another Workbench is moving it now) or "restored" (a
    check failed: the library was put back, settings.json and the profiles never changed), with the counts
    per key and the backup folder. When settings.json has nothing left to move, only the stray copies are
    taken out of the profiles (``_clean_strays_only``), and the status stays "nothing"."""

    path = Path(settings_path)
    if not path.is_file():
        return {"status": "nothing", "counts": {}}
    original = path.read_bytes()
    try:
        payload = json.loads(original.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        payload = None
    settings = _settings_part(payload)
    if settings is None:
        folder = _new_backup_folder(records.root, "unreadable-settings")
        (folder / "settings.json").write_bytes(original)
        return {"status": "refused", "counts": {}, "backup_folder": str(folder),
                "message": f"settings.json could not be read, so nothing was moved. A copy of it is in {folder}."}
    present = {key: settings[key] for key in MOVED_SETTINGS_KEYS if _holds(settings.get(key))}
    # An empty list an older build saved is taken out too (operator decision Q6), as is a profile's stray copy.
    stale = [key for key in MOVED_SETTINGS_KEYS if key in settings and key not in present]
    profiles = _custom_profiles(profiles_dir)
    if not present and not stale:
        if not any(_has_strays(profile) for profile in profiles):
            return {"status": "nothing", "counts": {}}
        return _clean_strays_only(records, profiles, profiles_dir)
    lock_path = records.root / MOVE_LOCK
    lock = open(lock_path, "a+b")
    try:
        try:
            _lock_now(lock)
        except OSError:
            return {"status": "busy", "counts": {}, "message": "Another Workbench is moving its settings now."}
        _close_interrupted_moves(records.connection())
        return _move(records, path, original, payload, settings, present, profiles, profiles_dir)
    finally:
        lock.close()


def _close_interrupted_moves(connection: sqlite3.Connection) -> None:
    """224 (Wave B2a, F8): a receipt still at "started" while this Workbench holds the move's lock belongs to a
    move that was cut off (a crash, a power cut) before it changed anything, so it says so."""

    # Only the settings move's own receipts: the Inbox's move keeps its receipt and finishes or undoes it itself
    # (224, Wave B2b, ``inbox_move``).
    with connection:
        connection.execute("UPDATE legacy_imports SET status = 'failed', note = 'interrupted', finished_utc = ? "
                           "WHERE status = 'started' AND source = 'settings.json'", (_stamp(),))


def _back_up_for_move(records: Records, folder: Path, path: Path, original: bytes,
                      profiles: list[tuple[Path, bytes, dict[str, Any]]], profiles_dir: Path | str | None) -> None:
    """settings.json, the library and every custom profile copied into ``folder`` and checked, with the files that
    say how to put them back. Raises when any of it did not work."""

    from . import safe_write  # noqa: PLC0415

    settings_copy = folder / "settings.json"
    settings_copy.write_bytes(original)
    library_copy = folder / DATABASE_NAME
    # 224 (Wave B2a, F8): the library's copy is checked (damage check, every table's rows) before it counts.
    safe_write.checked_copy(records.connection(), library_copy)
    manifest: dict[str, Any] = {
        "settings.json": _sha256(settings_copy.read_bytes()), DATABASE_NAME: _sha256(library_copy.read_bytes()),
        "settings_source": str(path), "library_source": str(database_path(records.root))}
    if manifest["settings.json"] != _sha256(original):
        raise RuntimeError(f"The backup of settings.json in {folder} did not check out, so nothing was moved.")
    if profiles:
        (folder / "profiles").mkdir()
        manifest["profiles_source"] = str(profiles_dir or "")
        for profile_path, data, _payload in profiles:
            kept = folder / "profiles" / profile_path.name
            kept.write_bytes(data)
            manifest[f"profiles/{profile_path.name}"] = _sha256(kept.read_bytes())
            if manifest[f"profiles/{profile_path.name}"] != _sha256(data):
                raise RuntimeError(f"The backup of a profile in {folder} did not check out, so nothing was moved.")
    safe_write.write_text(folder / "BACKUP_MANIFEST.json", json.dumps(manifest, indent=2))
    safe_write.write_text(folder / "HOW_TO_RESTORE.txt", HOW_TO_RESTORE.format(
        when=datetime.now().strftime("%Y-%m-%d %H:%M"), settings=path.parent, library=records.root,
        profiles=profiles_dir or "(none)"))


def _move(records: Records, path: Path, original: bytes, payload: dict[str, Any], settings: dict[str, Any],
          present: dict[str, Any], profiles: list[tuple[Path, bytes, dict[str, Any]]] = (),  # type: ignore[assignment]
          profiles_dir: Path | str | None = None) -> dict[str, Any]:
    connection = records.connection()
    folder = _new_backup_folder(records.root, "settings-move")
    with connection:
        receipt = int(connection.execute(
            "INSERT INTO legacy_imports(source, source_sha256, started_utc, status, backup_folder) VALUES "
            "('settings.json', ?, ?, 'started', ?)", (_sha256(original), _stamp(), str(folder))).lastrowid)
    try:
        _back_up_for_move(records, folder, path, original, list(profiles), profiles_dir)
    except (OSError, sqlite3.Error, RuntimeError) as exc:
        # 224 (Wave B2a, F8): a backup that did not work ends the move before anything changes, and its receipt
        # says why instead of staying at "started".
        with connection:
            connection.execute("UPDATE legacy_imports SET status = 'failed', finished_utc = ?, note = ? WHERE "
                               "import_id = ?", (_stamp(), str(exc)[:500], receipt))
        return {"status": "failed", "counts": {}, "backup_folder": str(folder),
                "message": f"The backup before the move did not work ({exc}); nothing was moved and settings.json "
                           "was not changed."}
    counts: dict[str, dict[str, int]] = {}
    connection.execute("BEGIN IMMEDIATE")
    try:
        now = _stamp()
        counts["recent_runs"] = _insert_legacy_runs(connection, present.get("recent_runs") or [])
        counts[LEGACY_NEVER_USE_KEY] = _insert_never_use(connection, present.get(LEGACY_NEVER_USE_KEY), now)
        counts[LEGACY_DONE_KEY] = _insert_done(connection, present.get(LEGACY_DONE_KEY), now)
        counts[LEGACY_STOPPED_RUN_KEY] = _insert_stopped_run(connection, present.get(LEGACY_STOPPED_RUN_KEY), now)
        problems = _check_move(connection, present, counts)
        if problems:
            raise RuntimeError("; ".join(problems))
        connection.execute("UPDATE legacy_imports SET status = 'imported', counts_json = ? WHERE import_id = ?",
                           (json.dumps(counts), receipt))
        connection.commit()
    except (sqlite3.Error, RuntimeError, ValueError, OSError) as exc:
        connection.rollback()
        with connection:
            connection.execute("UPDATE legacy_imports SET status = 'restored', finished_utc = ?, note = ? WHERE "
                               "import_id = ?", (_stamp(), str(exc)[:500], receipt))
        return {"status": "restored", "counts": counts, "backup_folder": str(folder),
                "message": f"The move did not check out ({exc}); nothing was added to the library and "
                           "settings.json was not changed."}
    cleaned = _clean_settings(path, original, payload, settings)
    counts["profiles"] = _clean_profiles(profiles)
    done = cleaned and counts["profiles"]["left"] == 0
    with connection:
        connection.execute("UPDATE legacy_imports SET status = ?, counts_json = ?, finished_utc = ? WHERE import_id = ?",
                           ("complete" if done else "imported", json.dumps(counts), _stamp(), receipt))
    return {"status": "moved" if done else "imported", "counts": counts, "backup_folder": str(folder)}


def _backed_up_profiles(root: Path) -> set[tuple[str, str]]:
    """(name, SHA-256) of every profile an earlier move or cleaning already backed up."""

    kept: set[tuple[str, str]] = set()
    for copy in (Path(root) / "backups" / MIGRATION_BACKUPS).glob("*/profiles/*.json"):
        try:
            kept.add((copy.name.lower(), _sha256(copy.read_bytes())))
        except OSError:
            continue
    return kept


def _clean_strays_only(records: Records, profiles: list[tuple[Path, bytes, dict[str, Any]]],
                       profiles_dir: Path | str | None) -> dict[str, Any]:
    """settings.json has nothing left to move, but a custom profile still holds a stray copy (one that could
    not be written at the move, or one an older build saved since). Each such profile is backed up on its own
    first, unless a backup of the very same file is already kept, so a profile that cannot be written now is
    not backed up again at every start; then the stray keys are taken out. The library and settings.json are
    not touched, and the lists stay in the library ("nothing" either way)."""

    strays = [profile for profile in profiles if _has_strays(profile)]
    left = {"custom": len(profiles), "with_strays": len(strays), "cleaned": 0, "left": len(strays)}
    lock = open(records.root / MOVE_LOCK, "a+b")
    try:
        try:
            _lock_now(lock)
        except OSError:
            return {"status": "nothing", "counts": {"profiles": left}}
        kept = _backed_up_profiles(records.root)
        new = [profile for profile in strays if (profile[0].name.lower(), _sha256(profile[1])) not in kept]
        folder: Path | None = None
        from . import safe_write  # noqa: PLC0415

        try:
            if new:
                folder = _new_backup_folder(records.root, "profile-clean")
                (folder / "profiles").mkdir()
                manifest: dict[str, Any] = {"profiles_source": str(profiles_dir or "")}
                for profile_path, data, _payload in new:
                    copy = folder / "profiles" / profile_path.name
                    copy.write_bytes(data)
                    manifest[f"profiles/{profile_path.name}"] = _sha256(copy.read_bytes())
                    if manifest[f"profiles/{profile_path.name}"] != _sha256(data):
                        raise RuntimeError(f"The backup of a profile in {folder} did not check out.")
                safe_write.write_text(folder / "BACKUP_MANIFEST.json", json.dumps(manifest, indent=2))
                safe_write.write_text(folder / "HOW_TO_RESTORE.txt", HOW_TO_RESTORE_PROFILES.format(
                    when=datetime.now().strftime("%Y-%m-%d %H:%M"), profiles=profiles_dir or "(none)"))
        except (OSError, RuntimeError) as exc:
            # Nothing is cleaned without its backup; the next start tries again.
            return {"status": "nothing", "counts": {"profiles": left}, "message": str(exc)}
        return {"status": "nothing", "counts": {"profiles": _clean_profiles(profiles)},
                "backup_folder": str(folder) if folder else ""}
    finally:
        lock.close()


def _legacy_never_use(value: Any) -> list[str]:
    """The old never-use list, read as the Workbench always read it: every member that is text."""

    if not isinstance(value, (list, tuple)):
        return []
    return [member for member in value if isinstance(member, str) and member.strip()]


def _legacy_done(value: Any) -> list[tuple[str, str]]:
    """The old already-done map: (path as written, "YYYY-MM-DD") for every entry with text for both."""

    if not isinstance(value, dict):
        return []
    return [(str(text), day) for text, day in value.items()
            if isinstance(text, str) and text.strip() and isinstance(day, str) and day.strip()]


def _never_use_key(text: str) -> str:
    return f"never_use:{text.lower()}"


def _done_key(text: str, day: str) -> str:
    return f"bugs_done:{text.lower()}:{day}"


def _stopped_run_key(record: dict[str, Any]) -> str:
    return "stopped_run:" + _sha256(json.dumps(record, sort_keys=True, default=str).encode("utf-8"))


def _local_day(utc_text: Any) -> str:
    """A stored UTC time as the day it was on this computer's clock; "~" (after every day) when unreadable."""

    try:
        return datetime.fromisoformat(str(utc_text).replace("Z", "+00:00")).astimezone().date().isoformat()
    except (TypeError, ValueError):
        return "~"


def proven_copy(connection: sqlite3.Connection, text: str, day: str) -> int | None:
    """The copy an old "done" entry for ``text`` on ``day`` belongs to, only when the library itself proves
    the same bytes were at that path on that day (design 4.3): the copy there now was first seen there on or
    before that day, its content never changed after it, the library read its content, and the file still has
    the size and modified time the library last read. None otherwise: the entry then stays an old entry,
    matched by its path, and is never given to whatever file is there now (242 correction 3)."""

    row = connection.execute(
        "SELECT l.recording_id, l.path, l.size_bytes, l.modified_ns, l.first_seen_utc, r.content_sha256, "
        "r.content_changed_utc FROM locations l JOIN recordings r ON r.recording_id = l.recording_id "
        "WHERE l.path_key = ? AND l.is_current = 1", (path_key(text),)).fetchone()
    if row is None or not row["content_sha256"] or _local_day(row["first_seen_utc"]) > day:
        return None
    if row["content_changed_utc"] and _local_day(row["content_changed_utc"]) > day:
        return None
    if not _unchanged(row["path"], row["size_bytes"], row["modified_ns"]):
        return None
    return int(row["recording_id"])


def _insert_never_use(connection: sqlite3.Connection, value: Any, now: str) -> dict[str, int]:
    """The old never-use list as old entries, by path: it has no date and no bytes to prove anything."""

    entries = _legacy_never_use(value)
    counts = {"read": len(entries), "added": 0, "already": 0}
    for text in entries:
        key = _never_use_key(text)
        if connection.execute("SELECT 1 FROM marks WHERE import_key = ?", (key,)).fetchone():
            counts["already"] += 1
            continue
        connection.execute(
            "INSERT INTO marks(kind, old_key, old_path, set_by, import_key, created_utc) VALUES (?, ?, ?, ?, ?, ?)",
            (MARK_NEVER_USE, text.lower(), text, MOVED_BY, key, now))
        counts["added"] += 1
    return counts


def _insert_done(connection: sqlite3.Connection, value: Any, now: str) -> dict[str, int]:
    """The old already-done map, each entry with its date and an unknown outcome (Done and No narration
    found were both kept as just a date). Tied to a copy only by ``proven_copy``."""

    entries = _legacy_done(value)
    counts = {"read": len(entries), "added": 0, "already": 0, "tied_to_a_recording": 0, "old_list": 0}
    for text, day in entries:
        key = _done_key(text, day)
        if connection.execute("SELECT 1 FROM marks WHERE import_key = ?", (key,)).fetchone():
            counts["already"] += 1
            continue
        copy = proven_copy(connection, text, day)
        connection.execute(
            "INSERT INTO marks(kind, recording_id, old_key, old_path, outcome, mark_date, set_by, import_key, "
            "created_utc) VALUES (?, ?, ?, ?, 'unknown', ?, ?, ?, ?)",
            (MARK_BUGS_DONE, copy, text.lower(), text, day, MOVED_BY, key, now))
        counts["added"] += 1
        counts["tied_to_a_recording" if copy is not None else "old_list"] += 1
    return counts


def _insert_stopped_run(connection: sqlite3.Connection, value: Any, now: str) -> dict[str, int]:
    """The old stopped run, as the stopped run Continue picks up, unless this very one was moved in before."""

    if not isinstance(value, dict) or not str(value.get("folder") or "").strip():
        return {"read": 0, "added": 0, "already": 0, "ignored": int(_holds(value))}
    key = _stopped_run_key(value)
    if connection.execute("SELECT 1 FROM resume_points WHERE import_key = ?", (key,)).fetchone():
        return {"read": 1, "added": 0, "already": 1, "ignored": 0}
    _set_resume_point(connection, BUG_REPORTS, value, now, import_key=key)
    return {"read": 1, "added": 1, "already": 0, "ignored": 0}


def _clean_profiles(profiles: Iterable[tuple[Path, bytes, dict[str, Any]]]) -> dict[str, int]:
    """Take the stray keys out of each custom profile that holds one, written safely and read back. A file
    that changed since it was read, or cannot be written now, is left as it was until the next start."""

    from . import safe_write  # noqa: PLC0415

    counts = {"custom": 0, "with_strays": 0, "cleaned": 0, "left": 0}
    for path, original, payload in profiles:
        counts["custom"] += 1
        if not any(key in payload["settings"] for key in PROFILE_STRAY_KEYS):
            continue
        counts["with_strays"] += 1
        kept = {key: value for key, value in payload["settings"].items() if key not in PROFILE_STRAY_KEYS}
        new_payload = {**payload, "settings": kept}
        try:
            if path.read_bytes() != original:
                counts["left"] += 1
                continue
            safe_write.write_json(path, new_payload)
            try:
                again = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                again = None
            if again != new_payload:
                # Never leave a profile worse than it was: put the original bytes back.
                safe_write.write_bytes(path, original)
                counts["left"] += 1
                continue
        except OSError:
            counts["left"] += 1
            continue
        counts["cleaned"] += 1
    return counts


def _check_move(connection: sqlite3.Connection, present: dict[str, Any], counts: dict[str, dict[str, int]]) -> list[str]:
    """Every entry read is in the library, and the library is whole."""

    problems: list[str] = []
    for name in ("recent_runs", LEGACY_NEVER_USE_KEY, LEGACY_DONE_KEY, LEGACY_STOPPED_RUN_KEY):
        part = counts.get(name) or {}
        if part.get("added", 0) + part.get("already", 0) != part.get("read", 0):
            problems.append(f"{name}: {part} do not add up")
    wanted = ([_never_use_key(text) for text in _legacy_never_use(present.get(LEGACY_NEVER_USE_KEY))]
              + [_done_key(text, day) for text, day in _legacy_done(present.get(LEGACY_DONE_KEY))])
    found = sum(int(connection.execute("SELECT COUNT(*) FROM marks WHERE import_key = ?", (key,)).fetchone()[0])
                for key in set(wanted))
    if found != len(set(wanted)):
        problems.append(f"the lists: {found} of {len(set(wanted))} entries are in the library")
    stopped = present.get(LEGACY_STOPPED_RUN_KEY)
    if counts.get(LEGACY_STOPPED_RUN_KEY, {}).get("read") and not connection.execute(
            "SELECT 1 FROM resume_points WHERE import_key = ?", (_stopped_run_key(stopped),)).fetchone():
        problems.append("the stopped run is not in the library")
    entries = [entry for entry in present.get("recent_runs") or [] if isinstance(entry, dict)]
    seen: dict[str, int] = {}
    keys = []
    for entry in reversed(entries):
        base = legacy_run_key(entry)
        seen[base] = seen.get(base, 0) + 1
        keys.append(f"{base}:{seen[base]}")
    if keys:
        found = 0
        for start in range(0, len(keys), 500):
            chunk = keys[start:start + 500]
            found += int(connection.execute(
                f"SELECT COUNT(*) FROM runs WHERE legacy_key IN ({', '.join('?' for _ in chunk)})", chunk).fetchone()[0])
        if found != len(keys):
            problems.append(f"run history: {found} of {len(keys)} entries are in the library")
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        problems.append("the library's integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        problems.append("the library has broken links")
    return problems


def _clean_settings(path: Path, original: bytes, payload: dict[str, Any], settings: dict[str, Any]) -> bool:
    """Take the moved keys out of settings.json, written safely and read back. False, and nothing changed,
    when the file changed since it was read (something else wrote it) or cannot be written now (another
    program holds it): the next start finishes it."""

    try:
        return _clean_settings_now(path, original, payload, settings)
    except OSError:
        return False


def _clean_settings_now(path: Path, original: bytes, payload: dict[str, Any], settings: dict[str, Any]) -> bool:

    try:
        if path.read_bytes() != original:
            return False
    except OSError:
        return False
    kept = {key: value for key, value in settings.items() if key not in MOVED_SETTINGS_KEYS}
    new_payload = dict(payload)
    if "settings" in payload:
        new_payload["settings"] = kept
    else:
        new_payload = kept
    from . import safe_write  # noqa: PLC0415

    safe_write.write_json(path, new_payload)
    try:
        again = _settings_part(json.loads(path.read_text(encoding="utf-8-sig")))
    except (OSError, ValueError):
        again = None
    if again is None or any(key in again for key in MOVED_SETTINGS_KEYS) or again != kept:
        # Never leave settings.json worse than it was: put the original bytes back.
        safe_write.write_bytes(path, original)
        return False
    return True
