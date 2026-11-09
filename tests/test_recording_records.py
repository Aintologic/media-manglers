"""The library's front door (242): opening it, moving its structure up one step at a time with a backup
first, refusing what a newer build made, and reading it for other features without changing it.

The library a Wave 6 build made is written here with plain SQL as that build left it, so these tests
also run against the code from before the front door existed.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core import inbox_records, raw_bin_library  # noqa: E402

try:
    from media_manglers.core import recording_records  # noqa: E402
except ImportError:  # shown failing on the code before the front door existed
    recording_records = None  # type: ignore[assignment]

WAVE6_TABLES = """
CREATE TABLE schema_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE recordings (
    recording_id INTEGER PRIMARY KEY AUTOINCREMENT, content_sha256 TEXT, sampled_sha256 TEXT,
    size_bytes INTEGER NOT NULL DEFAULT 0, duration_seconds REAL, audio_tracks INTEGER, track_titles_json TEXT,
    guess TEXT, guess_reason TEXT, narration_track INTEGER, speech_seconds REAL, speech_stretches_json TEXT,
    other_speech_track INTEGER, game_track INTEGER, game_track_decided_by TEXT, idle_status TEXT,
    idle_seconds REAL, idle_share REAL, idle_stretches_json TEXT, active_stretches_json TEXT, flag_count INTEGER,
    flags_json TEXT, transcript_path TEXT, decision TEXT NOT NULL DEFAULT 'undecided', decision_utc TEXT,
    duplicate_of INTEGER REFERENCES recordings(recording_id) ON DELETE SET NULL, content_changed_utc TEXT,
    first_seen_utc TEXT NOT NULL, scanned_utc TEXT, scan_rule_version INTEGER, bytes_read INTEGER,
    scan_error TEXT, idle_reason TEXT, rules_version INTEGER, rules_roles TEXT);
CREATE INDEX idx_recordings_content ON recordings(content_sha256);
CREATE TABLE locations (
    location_id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER NOT NULL REFERENCES recordings(recording_id) ON DELETE CASCADE,
    path TEXT NOT NULL, path_key TEXT NOT NULL UNIQUE, root_key TEXT NOT NULL, size_bytes INTEGER NOT NULL,
    modified_ns INTEGER NOT NULL, is_current INTEGER NOT NULL DEFAULT 1, missing INTEGER NOT NULL DEFAULT 0,
    first_seen_utc TEXT NOT NULL, last_seen_utc TEXT NOT NULL);
CREATE INDEX idx_locations_recording ON locations(recording_id, is_current);
CREATE TABLE labels (label_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    builtin INTEGER NOT NULL DEFAULT 0);
CREATE TABLE recording_labels (recording_id INTEGER NOT NULL REFERENCES recordings(recording_id) ON DELETE CASCADE,
    label_id INTEGER NOT NULL REFERENCES labels(label_id) ON DELETE CASCADE, PRIMARY KEY(recording_id, label_id));
CREATE TABLE scan_runs (run_id INTEGER PRIMARY KEY AUTOINCREMENT, started_utc TEXT NOT NULL, finished_utc TEXT,
    status TEXT NOT NULL, files_seen INTEGER DEFAULT 0, files_read INTEGER DEFAULT 0, bytes_read INTEGER DEFAULT 0,
    seconds_of_video_read REAL DEFAULT 0, detail TEXT);
"""


def make_wave6_library(root: Path, recording: Path, *, version: str = "2") -> None:
    """A library as a Wave 6 build left it: one recording, decided Keep, labelled, scanned once."""

    root.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(root / "raw-bin-library.sqlite"))
    try:
        connection.executescript(WAVE6_TABLES)
        connection.execute("INSERT INTO schema_metadata(key, value) VALUES ('schema_version', ?)", (version,))
        connection.execute(
            "INSERT INTO recordings(content_sha256, sampled_sha256, size_bytes, duration_seconds, decision, "
            "first_seen_utc) VALUES ('ab' || hex(zeroblob(31)), 'cd', ?, 120.0, 'keep', '2026-10-01T10:00:00Z')",
            (recording.stat().st_size,))
        connection.execute(
            "INSERT INTO locations(recording_id, path, path_key, root_key, size_bytes, modified_ns, first_seen_utc, "
            "last_seen_utc) VALUES (1, ?, ?, '', ?, ?, '2026-10-01T10:00:00Z', '2026-10-01T10:00:00Z')",
            (str(recording), os.path.normcase(os.path.abspath(str(recording))), recording.stat().st_size,
             recording.stat().st_mtime_ns))
        connection.execute("INSERT INTO labels(name, builtin) VALUES ('YouTube', 1)")
        connection.execute("INSERT INTO recording_labels(recording_id, label_id) VALUES (1, 1)")
        connection.execute("INSERT INTO scan_runs(started_utc, finished_utc, status) VALUES "
                           "('2026-10-01T10:00:00Z', '2026-10-01T10:05:00Z', 'completed')")
        connection.commit()
    finally:
        connection.close()


def _version(root: Path) -> str:
    connection = sqlite3.connect(str(root / "raw-bin-library.sqlite"))
    try:
        return str(connection.execute("SELECT value FROM schema_metadata WHERE key = 'schema_version'").fetchone()[0])
    finally:
        connection.close()


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class StructureStepTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="records-"))
        self.library = self.root / "library"
        self.recording = self.root / "race.mkv"
        self.recording.write_bytes(b"recording bytes")

    def test_a_wave_6_library_is_backed_up_whole_before_its_structure_moves_up(self) -> None:
        make_wave6_library(self.library, self.recording)
        connection = raw_bin_library.connect(self.library, backup=False)
        connection.close()
        backups = list((self.library / "backups" / "migrations").glob("*/raw-bin-library.sqlite"))
        self.assertEqual(len(backups), 1, "one backup, taken before the step")
        copy = sqlite3.connect(f"{backups[0].as_uri()}?mode=ro", uri=True)
        try:
            self.assertEqual(copy.execute("SELECT value FROM schema_metadata").fetchone()[0], "2")
            self.assertEqual(copy.execute("SELECT decision FROM recordings").fetchone()[0], "keep")
            self.assertEqual(copy.execute("SELECT COUNT(*) FROM recording_labels").fetchone()[0], 1)
        finally:
            copy.close()
        self.assertEqual(_version(self.library), str(recording_records.SCHEMA_VERSION))

    def test_nothing_the_operator_decided_is_lost_by_the_step(self) -> None:
        make_wave6_library(self.library, self.recording)
        connection = raw_bin_library.connect(self.library, backup=False)
        try:
            rows = raw_bin_library.list_recordings(connection)
        finally:
            connection.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["decision"], rows[0]["labels"]), ("keep", ["YouTube"]))
        self.assertEqual(rows[0]["path"], str(self.recording))

    def test_the_step_is_taken_once_and_kept(self) -> None:
        make_wave6_library(self.library, self.recording)
        for _ in range(3):
            raw_bin_library.connect(self.library, backup=False).close()
        self.assertEqual(len(list((self.library / "backups" / "migrations").glob("*"))), 1)
        connection = sqlite3.connect(str(self.library / "raw-bin-library.sqlite"))
        try:
            steps = connection.execute("SELECT from_version, to_version FROM schema_steps").fetchall()
        finally:
            connection.close()
        self.assertEqual(steps, [(2, recording_records.SCHEMA_VERSION)])

    def test_an_older_build_writing_its_version_back_is_moved_up_again_safely(self) -> None:
        # A Wave 6 build opened after this one writes "2" back on every open; its rows stay.
        make_wave6_library(self.library, self.recording)
        raw_bin_library.connect(self.library, backup=False).close()
        connection = sqlite3.connect(str(self.library / "raw-bin-library.sqlite"))
        with connection:
            connection.execute("UPDATE schema_metadata SET value = '2' WHERE key = 'schema_version'")
        connection.close()
        raw_bin_library.connect(self.library, backup=False).close()
        self.assertEqual(_version(self.library), str(recording_records.SCHEMA_VERSION))
        self.assertEqual(len(list((self.library / "backups" / "migrations").glob("*"))), 2)

    def test_a_library_a_newer_build_moved_on_is_refused_and_left_unchanged(self) -> None:
        make_wave6_library(self.library, self.recording, version="99")
        database = self.library / "raw-bin-library.sqlite"
        before = _digest(database)
        with self.assertRaises(ValueError):
            raw_bin_library.connect(self.library, backup=False).close()
        self.assertEqual(_digest(database), before)
        self.assertEqual(_version(self.library), "99")

    def test_a_step_that_fails_changes_nothing(self) -> None:
        make_wave6_library(self.library, self.recording)

        def broken_step(connection: sqlite3.Connection) -> None:
            connection.execute("CREATE TABLE IF NOT EXISTS half_made (x INTEGER)")
            raise RuntimeError("the disk went away")

        with mock.patch.dict(recording_records.SCHEMA_STEPS, {3: broken_step}):
            with self.assertRaises(RuntimeError):
                recording_records.connect(self.library, backup=False)
        self.assertEqual(_version(self.library), "2")
        connection = sqlite3.connect(str(self.library / "raw-bin-library.sqlite"))
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        finally:
            connection.close()
        self.assertNotIn("half_made", tables)
        self.assertNotIn("schema_steps", tables)

    def test_a_new_library_starts_at_this_builds_structure_without_a_step_backup(self) -> None:
        raw_bin_library.connect(self.library, backup=False).close()
        self.assertEqual(_version(self.library), str(recording_records.SCHEMA_VERSION))
        self.assertFalse((self.library / "backups" / "migrations").exists())

    def test_step_backups_are_never_pruned_by_the_daily_backup(self) -> None:
        make_wave6_library(self.library, self.recording)
        connection = raw_bin_library.connect(self.library, backup=False)
        try:
            for day in range(1, 20):
                recording_records.daily_backup(connection, self.library,
                                               today=__import__("datetime").date(2026, 9, day), keep=3)
        finally:
            connection.close()
        self.assertEqual(len(list((self.library / "backups").glob("raw-bin-library-*.sqlite"))), 3)
        self.assertEqual(len(list((self.library / "backups" / "migrations").glob("*/raw-bin-library.sqlite"))), 1)


class ReadOnlyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="records-read-"))
        self.library = self.root / "library"
        self.recording = self.root / "race.mkv"
        self.recording.write_bytes(b"recording bytes")

    def test_reading_without_a_library_makes_none(self) -> None:
        self.assertIsNone(recording_records.current_copy(self.recording, root=self.library))
        self.assertEqual(recording_records.list_recordings(root=self.library), [])
        self.assertFalse(self.library.exists())

    def test_reading_never_moves_the_structure_up_or_changes_the_file(self) -> None:
        make_wave6_library(self.library, self.recording)
        database = self.library / "raw-bin-library.sqlite"
        before = _digest(database)
        found = recording_records.current_copy(self.recording, root=self.library)
        self.assertEqual(found["size_bytes"], self.recording.stat().st_size)
        self.assertEqual(found["duration_seconds"], 120.0)
        self.assertEqual(len(recording_records.list_recordings(root=self.library)), 1)
        self.assertEqual(_digest(database), before)
        self.assertEqual(_version(self.library), "2")


class InboxAdapterTests(unittest.TestCase):
    """224 (Wave B2b): what Review Media Inbox reviewed is read from its own tables in the library, over the
    caller's connection; "not known" until its records have moved in (F11); a recording counts from its own
    finished state (Q7)."""

    NOW = "2026-11-01T00:00:00Z"

    def setUp(self) -> None:
        from tests import inbox_library  # noqa: PLC0415

        self.inbox_library = inbox_library
        self.root = Path(tempfile.mkdtemp(prefix="records-inbox-"))
        recording_records.connect(backup=False).close()

    def _reviewed(self) -> "recording_records.InboxVerdicts":
        connection = self.inbox_library.connect(read_only=True)
        try:
            return recording_records.inbox_reviewed(connection)
        finally:
            connection.close()

    def _source(self, connection: sqlite3.Connection, source_id: int, state: str, content: str) -> None:
        connection.execute(
            "INSERT INTO inbox_sources(source_id, provisional_identity, stable_identity, content_sha256, size_bytes, "
            "lifecycle_state, first_seen_utc, updated_utc) VALUES (?, ?, ?, ?, 10, ?, ?, ?)",
            (source_id, f"provisional:{source_id}", f"sha256:{content}", content, state, self.NOW, self.NOW))

    def test_before_the_inbox_moved_in_nothing_is_known(self) -> None:
        verdicts = self._reviewed()
        self.assertFalse(verdicts.known, "no move receipt: \"not reviewed\" would only mean \"not known\"")
        self.assertEqual((verdicts.hashes, verdicts.paths), (set(), {}))

    def test_a_library_with_nothing_to_move_is_known_and_reviews_nothing(self) -> None:
        self.inbox_library.ready()
        verdicts = self._reviewed()
        self.assertTrue(verdicts.known)
        self.assertEqual((verdicts.hashes, verdicts.paths), (set(), {}))

    def test_a_recording_finished_in_a_batch_that_still_needs_a_look_counts_as_reviewed(self) -> None:
        self.inbox_library.ready()
        finished, open_one = "a" * 64, "b" * 64
        connection = self.inbox_library.connect()
        with connection:
            self._source(connection, 1, "finalized_no_findings", finished)
            self._source(connection, 2, "needs_manual_review", open_one)
            connection.execute("INSERT INTO inbox_batches VALUES ('b1', 'needs_manual_review', NULL, 0, ?, ?)",
                               (self.NOW, self.NOW))
            connection.execute("INSERT INTO inbox_batch_sources VALUES ('b1', 1, 1, 'finalized_no_findings', NULL, ?, ?)",
                               (self.NOW, self.NOW))
            connection.execute("INSERT INTO inbox_batch_sources VALUES ('b1', 2, 2, 'needs_manual_review', NULL, ?, ?)",
                               (self.NOW, self.NOW))
        connection.close()
        verdicts = self._reviewed()
        self.assertTrue(verdicts.known)
        self.assertEqual(verdicts.hashes, {finished}, "Q7: its own finished state counts, the batch's does not hold it")

    def test_reading_never_changes_the_inbox_records(self) -> None:
        self.inbox_library.ready()
        connection = self.inbox_library.connect()
        with connection:
            self._source(connection, 1, "finalized_with_findings", "c" * 64)
        connection.close()
        before = self.inbox_library.fingerprint()
        self.assertTrue(self._reviewed().known)
        self.assertEqual(self.inbox_library.fingerprint(), before)


if __name__ == "__main__":
    unittest.main()
