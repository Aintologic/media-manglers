"""224 (Wave B2b): Review Media Inbox's one-time move of its ledger into the library (design section 4, 5.4).

Every test builds a version-2 ledger of its own, with rows in every table, and moves it into a library of its own
through the real mover (``inbox_move.move_ledger``), as a Workbench start does.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from unittest import mock

from media_manglers.cli import main
from media_manglers.contracts import CommandEnvelope, read_json_file, write_json_file
from media_manglers.core import (inbox_move, inbox_records, raw_bin_library, recording_records, review_inbox,
                                 review_ledger, safe_write)
from media_manglers_workbench.app import AdvancedSettingsDialog, ReviewInboxOperationThread, WorkbenchWindow
from media_manglers_workbench.metadata import WORKFLOW_REVIEW_NEW_VIDEOS
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION
from PySide6.QtWidgets import QApplication
from tests import inbox_library
from tests.outside_holder import OutsideHolder
from tests.test_raw_bin_library import FFMPEG, FFPROBE, HearingTranscriber, make_recording
from tests.test_workbench_review_media_inbox import _ready_resources

WINDOWS = sys.platform == "win32"
NOW = "2026-10-20T10:00:00Z"
STEPS = ("locked", "settled", "receipt", "backed_up", "checked", "imported", "rechecked", "original_unchanged",
         "guarded", "swapped", "settings", "complete")
PUT_BACK = STEPS[:STEPS.index("guarded") + 1]  # a failure up to here is undone; after it the next start finishes


def build_ledger(path: Path, *, relocated_from: str = "", recordings: int = 3) -> Path:
    """A version-2 ledger with rows in every table, numbered with gaps (the counters must move too)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        for statement in (*review_ledger._legacy_schema_statements(), *review_ledger._v2_schema_statements()):
            connection.execute(statement)
        if relocated_from:
            connection.execute(review_ledger.RELOCATION_TABLE)
        connection.execute("PRAGMA user_version = 2")
        connection.execute("INSERT INTO schema_metadata VALUES ('schema_version', '2')")
        connection.execute("INSERT INTO schema_metadata VALUES ('migration_completed_utc', ?)", (NOW,))
        folder = path.parent
        batch = folder / "batches" / "batch-1"
        (batch / "imports" / "abc").mkdir(parents=True)
        (batch / "imports" / "abc" / "validation.json").write_text('{"ok": true}', encoding="utf-8")
        (batch / "batch-manifest.json").write_text('{"batch_id": "batch-1"}', encoding="utf-8")
        (batch / "visuals.jpg").write_bytes(b"\xff\xd8 not read")
        connection.execute("INSERT INTO batches VALUES ('batch-1', 'needs_manual_review', ?, 0, ?, ?)",
                           (str(batch), NOW, NOW))
        for number in range(1, recordings + 1):
            source_id = number * 10
            content = hashlib.sha256(f"recording {number}".encode()).hexdigest()
            state = "finalized_no_findings" if number == 1 else "needs_manual_review" if number == 2 else "pending"
            connection.execute(
                "INSERT INTO sources (source_id, provisional_identity, stable_identity, content_sha256, sampled_sha256, "
                "size_bytes, lifecycle_state, first_seen_utc, updated_utc) VALUES (?, ?, ?, ?, ?, 100, ?, ?, ?)",
                (source_id, f"provisional:{number}", f"sha256:{content}", content, f"s{number}", state, NOW, NOW))
            connection.execute(
                "INSERT INTO source_locations (location_id, source_id, original_path, normalized_path, size_bytes, "
                "modified_utc, first_seen_utc, last_seen_utc) VALUES (?, ?, ?, ?, 100, ?, ?, ?)",
                (number * 3, source_id, f"X:\\rec\\r{number}.mkv", os.path.normcase(f"x:\\rec\\r{number}.mkv"),
                 NOW, NOW, NOW))
            if number <= 2:
                connection.execute("INSERT INTO batch_sources VALUES ('batch-1', ?, ?, ?, 'sig-2', ?, ?)",
                                   (source_id, number, state, NOW, NOW))
                connection.execute(
                    "INSERT INTO attempts (attempt_id, source_id, batch_id, attempt_type, status, started_utc) "
                    "VALUES (?, ?, 'batch-1', 'prepare', 'prepared', ?)", (number * 5, source_id, NOW))
        connection.execute("INSERT INTO findings VALUES ('finding-1', 'batch-1', 20, 'preliminary', 'accepted', 1.0, "
                           "2.0, '{\"note\": \"x\"}', ?, ?)", (NOW, NOW))
        connection.execute("INSERT INTO lifecycle_events (event_id, source_id, batch_id, event_type, created_utc) VALUES "
                           "(41, 10, 'batch-1', 'prepared', ?)", (NOW,))
        connection.execute(
            "INSERT INTO final_results VALUES ('result-1', 'batch-1', 10, NULL, 'sub', 'pre', 'no_actionable_findings', "
            "NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'nothing', 'none', '[]', '{}', ?, ?)", (NOW, NOW))
        journal = batch / ".finalization" / "journal-a.json"
        journal.parent.mkdir()
        journal.write_text('{"phase": "cleanup_complete"}', encoding="utf-8")
        connection.execute("INSERT INTO finalization_runs VALUES ('plan-1', 'batch-1', 'sub', 'pre', 'cleanup_complete', "
                           "?, ?, ?)", (str(journal), NOW, NOW))
        history = folder / "history" / "sources" / "t1" / "batch-1"
        history.mkdir(parents=True)
        (history / "manifest.json").write_text("{}", encoding="utf-8")
        connection.execute("INSERT INTO retention_records VALUES ('plan-1', 'batch-1', 10, 'finalized_no_findings', ?, 5, "
                           "1, 'h', ?)", (str(history), NOW))
        if relocated_from:
            connection.execute("INSERT INTO relocation_runs VALUES ('op-1', 'plan-r', 'completed', 'j', 'b', ?, '{}', ?, "
                               "?, ?)", (json.dumps([{"old_root": relocated_from}]), NOW, NOW, NOW))
        connection.execute("UPDATE sqlite_sequence SET seq = seq + 7")  # a deleted row's number is never reused
        connection.commit()
    finally:
        connection.close()
    (path.parent / "queue-index.json").write_text('{"batches": []}', encoding="utf-8")
    return path


class _Move(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="inbox-move-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        inbox_library.use_own_library(self, self.root)
        self.ledger = build_ledger(self.root / "inbox" / "review-ledger.sqlite")
        self.settings_path = self.root / "settings.json"
        self.settings = {"review_ledger_path": str(self.ledger)}
        self.settings_path.write_text(json.dumps({"schemaVersion": 8, "settings": self.settings}), encoding="utf-8")
        self.profiles = self.root / "profiles"
        self.profiles.mkdir()
        self.saved: list[Path] = []
        self.records = recording_records.Records()
        self.addCleanup(self._close)

    def _close(self) -> None:
        if self.records is not None:
            self.records.close()
            self.records = None
        inbox_records.release_all()

    def move(self) -> inbox_move.MoveResult:
        return inbox_move.move_ledger(self.records, self.settings, settings_path=self.settings_path,
                                      profiles_dir=self.profiles, version="9.9.9", save_folder=self.saved.append)

    def library(self) -> sqlite3.Connection:
        return self.records.connection()

    def rows(self, table: str) -> int:
        return int(self.library().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def receipts(self) -> list[str]:
        return [row[0] for row in self.library().execute(
            "SELECT status FROM legacy_imports WHERE source = 'inbox ledger' ORDER BY import_id")]

    def ledger_state(self) -> tuple[bool, str]:
        return inbox_records.is_database(self.ledger), hashlib.sha256(self.ledger.read_bytes()).hexdigest()

    def assert_put_back(self, before: tuple[bool, str]) -> None:
        self.assertEqual(self.ledger_state(), before, "the ledger is at its own name, unchanged")
        self.assertEqual(sum(self.rows(table) for table in review_ledger.INBOX_TABLES.values()), 0)
        self.assertIsNone(inbox_records.registered_folder(self.library()))
        self.assertEqual(self.library().execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger'")
                         .fetchone()[0], 0)
        self.assertEqual(self.saved, [], "the settings were not changed")


class TheMoveTests(_Move):
    def test_every_row_moves_with_its_own_id_and_the_counters_move_too(self) -> None:
        copy = inbox_records.read_only_file(self.ledger)
        try:
            present = [table for table in review_ledger.INBOX_TABLES if table in inbox_move._tables(copy)]
            before = inbox_move.measure(copy, {}, copy, present)
            counters = dict(copy.execute("SELECT name, seq FROM sqlite_sequence").fetchall())
        finally:
            copy.close()
        original = self.ledger.read_bytes()
        result = self.move()
        self.assertEqual(result.status, "moved", result.message)
        library = self.library()
        library.execute("ATTACH DATABASE ? AS ledger_copy", (str(Path(result.backup_folder) / "review-ledger.sqlite"),))
        try:
            self.assertEqual(inbox_move._measure_library(library, present), before)
        finally:
            library.execute("DETACH DATABASE ledger_copy")
        for table, seq in counters.items():
            carried = library.execute("SELECT seq FROM sqlite_sequence WHERE name = ?",
                                      (review_ledger.INBOX_TABLES[table],)).fetchone()[0]
            self.assertGreaterEqual(carried, seq, table)
        self.assertEqual(inbox_records.registered_folder(library), self.ledger.parent)
        self.assertEqual(self.receipts(), ["complete"])
        self.assertEqual(self.saved, [self.ledger.parent])
        moved = self.ledger.parent / f"review-ledger.sqlite.moved-{__import__('datetime').date.today().isoformat()}.sqlite"
        self.assertEqual(moved.read_bytes(), original, "the original is kept beside the note, byte for byte")
        note = self.ledger.read_text(encoding="utf-8")
        self.assertIn("moved into the Workbench library", note)
        self.assertIn(moved.name, note)
        with self.assertRaises(sqlite3.DatabaseError):
            older = sqlite3.connect(self.ledger)  # what an older Workbench gets from the note
            try:
                older.execute("SELECT * FROM sqlite_master").fetchall()
            finally:
                older.close()
        backup = Path(result.backup_folder)
        self.assertEqual(backup.parent.name, "migrations")
        self.assertTrue(backup.name.endswith("-wave-b"))
        for name in ("review-ledger.sqlite", "raw-bin-library.sqlite", "settings.json", "WORKSPACE_INVENTORY.json",
                     "BACKUP_MANIFEST.json", "HOW_TO_RESTORE.txt", "MOVE_RECEIPT.json"):
            self.assertTrue((backup / name).is_file(), name)
        inventory = json.loads((backup / "WORKSPACE_INVENTORY.json").read_text(encoding="utf-8"))["files"]
        self.assertIn("batches/batch-1/imports/abc/validation.json", inventory)
        self.assertNotIn("batches/batch-1/visuals.jpg", inventory, "media is left out")

    def test_running_it_twice_changes_nothing(self) -> None:
        self.assertEqual(self.move().status, "moved")
        state = inbox_library.fingerprint(), sorted(p.name for p in self.ledger.parent.iterdir())
        self.assertEqual(self.move().status, "nothing")
        self.assertEqual((inbox_library.fingerprint(), sorted(p.name for p in self.ledger.parent.iterdir())), state)
        self.assertEqual(self.receipts(), ["complete"])

    def test_a_recording_the_inbox_finished_shows_mined_and_one_in_a_batch_needing_a_look_too(self) -> None:
        # Q7: recording 1 finished on its own while its batch still needs a look.
        self.assertEqual(self.move().status, "moved")
        hashes, _paths = recording_records.inbox_verdicts(self.library())
        self.assertIn(hashlib.sha256(b"recording 1").hexdigest(), hashes)
        self.assertNotIn(hashlib.sha256(b"recording 2").hexdigest(), hashes)
        self.assertTrue(recording_records.inbox_reviewed(self.library()).known)

    def test_after_the_move_accepted_results_and_recordings_are_kept(self) -> None:
        self.assertEqual(self.move().status, "moved")
        library = self.library()
        for statement in ("UPDATE inbox_final_results SET notes = 'changed'", "DELETE FROM inbox_final_results",
                          "DELETE FROM inbox_sources WHERE source_id = 30",
                          "UPDATE inbox_retention_records SET retained_bytes = 0", "DELETE FROM inbox_retention_records"):
            with self.subTest(statement=statement), self.assertRaises(sqlite3.IntegrityError):
                with library:
                    library.execute(statement)
        with library:  # the relocation tool moves where history is
            library.execute("UPDATE inbox_retention_records SET history_path = 'Y:\\\\moved'")


class PutBackTests(_Move):
    def test_a_failure_after_every_step_puts_everything_back_and_the_next_start_finishes(self) -> None:
        before = self.ledger_state()
        for step in STEPS:
            with self.subTest(step=step):
                self.tearDown_move()
                self.setUp()
                before = self.ledger_state()

                def fail(at: str, wanted: str = step) -> None:
                    if at == wanted:
                        raise RuntimeError(f"injected after {wanted}")

                with mock.patch.object(inbox_move, "checkpoint", fail):
                    try:
                        result = self.move()
                    except RuntimeError as exc:
                        result = inbox_move.MoveResult("raised", str(exc))
                if step in PUT_BACK:
                    self.assert_put_back(before)
                    if step not in ("locked", "settled"):
                        self.assertEqual(self.receipts()[-1], "restored")
                        self.assertIn(f"injected after {step}", result.message)
                else:
                    self.assertEqual(sum(self.rows(t) for t in review_ledger.INBOX_TABLES.values()) > 0, True,
                                     "the records are in and safe; the next start finishes the move")
                self.assertEqual(self.move().status, "moved" if step != "complete" else "nothing")
                self.assertEqual(self.receipts()[-1], "complete")
                self.assertFalse(inbox_records.is_database(self.ledger))

    def tearDown_move(self) -> None:
        self._close()
        shutil.rmtree(self.root, True)


@unittest.skipUnless(WINDOWS, "a hard kill of a Windows process")
class KillTests(unittest.TestCase):
    """A kill after every step, in a process of its own: the next start finishes or undoes it, nothing lost or
    doubled."""

    def test_a_kill_after_every_step_is_finished_or_undone_at_the_next_start(self) -> None:
        script = textwrap.dedent("""
            import json, os, sys
            from pathlib import Path
            from media_manglers.core import inbox_move, recording_records
            step, ledger, settings = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
            def checkpoint(at):
                if at == step:
                    os._exit(9)
            inbox_move.checkpoint = checkpoint
            records = recording_records.Records()
            saved = lambda folder: settings.write_text(json.dumps({"settings": {"review_ledger_path": str(ledger),
                                                       "review_inbox_folder": str(folder)}}), encoding="utf-8")
            result = inbox_move.move_ledger(records, {"review_ledger_path": str(ledger)}, settings_path=settings,
                                            profiles_dir=None, version="9.9.9", save_folder=saved)
            print(result.status)
            """)
        for step in STEPS:
            with self.subTest(step=step):
                root = Path(tempfile.mkdtemp(prefix="inbox-kill-"))
                try:
                    ledger = build_ledger(root / "inbox" / "review-ledger.sqlite")
                    settings = root / "settings.json"
                    settings.write_text(json.dumps({"settings": {"review_ledger_path": str(ledger)}}), encoding="utf-8")
                    original = ledger.read_bytes()
                    env = {**os.environ, recording_records.LIBRARY_ROOT_ENV: str(root / "library"),
                           "PYTHONPATH": os.pathsep.join(sys.path)}
                    killed = subprocess.run([sys.executable, "-c", script, step, str(ledger), str(settings)], env=env,
                                            capture_output=True, text=True, timeout=120)
                    self.assertEqual(killed.returncode, 9, killed.stderr)
                    again = subprocess.run([sys.executable, "-c", script, "", str(ledger), str(settings)], env=env,
                                           capture_output=True, text=True, timeout=120)
                    self.assertEqual(again.returncode, 0, again.stderr)
                    self.assertIn(again.stdout.strip(), {"moved", "nothing"})
                    library = sqlite3.connect(root / "library" / "raw-bin-library.sqlite")
                    try:
                        self.assertEqual(library.execute("SELECT COUNT(*) FROM inbox_sources").fetchone()[0], 3,
                                         "nothing lost and nothing doubled")
                        statuses = [row[0] for row in library.execute(
                            "SELECT status FROM legacy_imports WHERE source = 'inbox ledger' ORDER BY import_id")]
                        self.assertEqual(statuses[-1], "complete")
                    finally:
                        library.close()
                    moved = list(ledger.parent.glob("review-ledger.sqlite.moved-*"))
                    self.assertEqual(len(moved), 1)
                    self.assertEqual(moved[0].read_bytes(), original)
                finally:
                    shutil.rmtree(root, True)


class WaitsTests(_Move):
    def test_it_waits_while_an_inbox_run_holds_the_lock_and_changes_nothing(self) -> None:
        before = self.ledger_state()
        lock = inbox_records.lock_file(self.ledger.parent)
        with inbox_records.ProcessLock(lock):
            pass
        with OutsideHolder(lock, lock=True, forever=True):
            result = self.move()
        self.assertEqual(result.status, "waiting")
        self.assertIn("An Inbox run is still going", result.message)
        self.assert_put_back(before)
        self.assertEqual(self.receipts(), [])

    def test_it_waits_while_another_workbench_is_open(self) -> None:
        before = self.ledger_state()
        other = recording_records.Records()
        try:
            result = self.move()
        finally:
            other.close()
        self.assertEqual(result.status, "waiting")
        self.assertIn("Close any other Workbench window", result.message)
        self.assert_put_back(before)

    def test_it_waits_while_the_inbox_folder_cannot_be_reached(self) -> None:
        self.settings["review_ledger_path"] = str(self.root / "offline-drive" / "review-ledger.sqlite")
        result = self.move()
        self.assertEqual(result.status, "waiting")
        self.assertIn("cannot be reached", result.message)
        self.assertEqual(self.receipts(), [])

    def test_it_waits_while_a_side_file_stays_beside_the_ledger(self) -> None:
        before = self.ledger_state()
        self.ledger.with_name(self.ledger.name + "-wal").write_bytes(b"held by another program")
        with mock.patch.object(inbox_records, "settle_file"):
            result = self.move()
        self.assertEqual(result.status, "waiting")
        self.assertIn("half-written change", result.message)
        self.assert_put_back(before)

    def test_a_change_a_crash_left_beside_the_ledger_is_finished_and_moves_too(self) -> None:
        script = textwrap.dedent("""
            import os, sqlite3, sys
            connection = sqlite3.connect(sys.argv[1], isolation_level=None)
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA wal_autocheckpoint = 0")
            connection.execute("UPDATE batches SET status = 'left_by_a_crash'")
            os._exit(0)
            """)
        crashed = subprocess.run([sys.executable, "-c", script, str(self.ledger)], capture_output=True, text=True,
                                 timeout=60)
        self.assertEqual(crashed.returncode, 0, crashed.stderr)
        self.assertTrue(self.ledger.with_name(self.ledger.name + "-wal").stat().st_size > 0, "the crash left a change")
        self.assertEqual(self.move().status, "moved")
        self.assertEqual(self.library().execute("SELECT status FROM inbox_batches").fetchone()[0], "left_by_a_crash")

    def test_a_ledger_held_open_at_the_swap_is_finished_at_the_next_start(self) -> None:
        with mock.patch.object(safe_write, "replace_file",
                               side_effect=safe_write.FileInUse("review-ledger.sqlite is held by a program")):
            result = self.move()
        self.assertEqual(result.status, "waiting")
        self.assertEqual(self.receipts()[-1], "verified")
        self.assertTrue(inbox_records.is_database(self.ledger))
        status = inbox_records.status(self.library(), self.ledger.parent)
        self.assertFalse(status.ready, "the Inbox waits until the swap is done")
        self.assertEqual(self.move().status, "moved")
        self.assertEqual(self.receipts()[-1], "complete")


class RefusalTests(_Move):
    def refused(self, *, status: str = "restored") -> inbox_move.MoveResult:
        before = self.ledger_state()
        result = self.move()
        self.assertEqual(result.status, status, result.message)
        self.assert_put_back(before)
        return result

    def test_a_damaged_ledger_is_refused(self) -> None:
        data = bytearray(self.ledger.read_bytes())
        data[4096:8192] = b"\x00" * 4096
        self.ledger.write_bytes(bytes(data))
        self.refused()

    def test_a_ledger_with_a_table_this_version_does_not_know_is_refused(self) -> None:
        connection = sqlite3.connect(self.ledger)
        connection.execute("CREATE TABLE surprise (x)")
        connection.commit()
        connection.close()
        self.assertIn("does not know", self.refused().message)

    def test_a_ledger_not_at_version_2_is_refused(self) -> None:
        connection = sqlite3.connect(self.ledger)
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
        connection.close()
        self.assertIn("structure 1", self.refused().message)

    def test_an_unfinished_run_that_names_another_inbox_folder_is_refused(self) -> None:
        active = self.ledger.parent / ".orchestration" / "active-run.json"
        active.parent.mkdir()
        active.write_text(json.dumps({"run": {"scan_settings": {"ledger_path": "Z:\\elsewhere\\review-ledger.sqlite"}}}),
                          encoding="utf-8")
        self.assertIn("names another Inbox folder", self.refused().message)

    def test_a_relocated_inbox_whose_unfinished_run_names_its_old_folder_is_moved(self) -> None:
        shutil.rmtree(self.ledger.parent)
        self.ledger = build_ledger(self.root / "inbox" / "review-ledger.sqlite", relocated_from="Z:\\old-inbox")
        active = self.ledger.parent / ".orchestration" / "active-run.json"
        active.parent.mkdir()
        active.write_text(json.dumps({"run": {"scan_settings": {"ledger_path": "Z:\\old-inbox\\review-ledger.sqlite"}}}),
                          encoding="utf-8")
        self.assertEqual(self.move().status, "moved")
        self.assertEqual(self.rows("inbox_relocation_runs"), 1)

    def test_a_second_ledger_is_refused_once_the_library_holds_inbox_records(self) -> None:
        self.assertEqual(self.move().status, "moved")
        other = build_ledger(self.root / "other" / "review-ledger.sqlite")
        before = other.read_bytes()
        self.settings["review_ledger_path"] = str(other)
        self.assertEqual(self.move().status, "nothing", "Wave B moves exactly one ledger")
        self.assertEqual(other.read_bytes(), before)
        found = inbox_records.status(self.library(), other.parent)
        self.assertFalse(found.ready)

    def test_no_ledger_named_is_nothing_to_move_and_the_inbox_starts_fresh(self) -> None:
        self.settings.pop("review_ledger_path")
        self.assertEqual(self.move().status, "nothing")
        self.assertEqual(self.receipts(), ["complete"])
        self.assertTrue(inbox_records.status(self.library(), self.root / "new-inbox").ready)
        self.assertTrue(self.ledger_state()[0], "an unnamed ledger is left alone")


class BeforeTheMoveTests(unittest.TestCase):
    def test_a_command_line_helper_started_before_the_move_refuses_and_makes_nothing(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="inbox-before-move-"))
        self.addCleanup(shutil.rmtree, root, True)
        inbox_library.use_own_library(self, root)
        ledger = build_ledger(root / "inbox" / "review-ledger.sqlite")
        before = ledger.read_bytes()
        (root / "sources").mkdir()
        request, result = root / "request.json", root / "result.json"
        write_json_file(request, CommandEnvelope(payload={"source_folders": [str(root / "sources")],
                                                          "ledger_path": str(ledger)}).to_dict())
        code = main(["review-media-inbox-scan", "--request-file", str(request), "--result-file", str(result)])
        self.assertEqual(code, 1)
        self.assertEqual(read_json_file(result)["error"], inbox_records.NOT_MOVED_YET)
        self.assertEqual(ledger.read_bytes(), before)
        library = sqlite3.connect(recording_records.database_path())
        try:
            self.assertEqual(library.execute("SELECT COUNT(*) FROM inbox_sources").fetchone()[0], 0)
        finally:
            library.close()
        inbox_records.release_all()


class NeverSetUpMeansNeverSetUpTests(_Move):
    """Design 4.1: only a ledger named nowhere is "never set up". Anything else waits and writes no receipt, because
    a "complete" receipt can never be undone and would let a new Inbox start ahead of the real one."""

    def assert_waits(self, *words: str) -> inbox_move.MoveResult:
        result = self.move()
        self.assertEqual(result.status, "waiting", result.message)
        for word in words:
            self.assertIn(word, result.message)
        self.assertEqual(self.receipts(), [], "no receipt: the next good start still moves the ledger")
        self.assertEqual(self.saved, [])
        return result

    def test_a_settings_file_that_cannot_be_read_waits_and_the_next_good_start_moves(self) -> None:
        good = self.settings_path.read_bytes()
        self.settings_path.write_text("{ this is not json", encoding="utf-8")
        named = self.settings.pop("review_ledger_path")  # what a start gets from a settings file it cannot read
        self.assert_waits("settings")
        self.settings_path.write_bytes(good)
        self.settings["review_ledger_path"] = named
        self.assertEqual(self.move().status, "moved")

    def test_a_ledger_named_only_in_a_custom_profile_waits(self) -> None:
        self.settings.pop("review_ledger_path")
        (self.profiles / "Mine.json").write_text(json.dumps({"settings": {"review_ledger_path": str(self.ledger)}}),
                                                 encoding="utf-8")
        self.assert_waits("profile")

    def test_a_named_ledger_moved_aside_waits_and_moves_when_it_is_put_back(self) -> None:
        aside = self.root / "aside"
        aside.mkdir()
        for name in ("batches", "history", "review-ledger.sqlite"):
            shutil.move(str(self.ledger.parent / name), str(aside / name))
        self.assertTrue((self.ledger.parent / "queue-index.json").is_file(), "the Inbox was used here")
        self.assert_waits("not there")
        for name in ("batches", "history", "review-ledger.sqlite"):
            shutil.move(str(aside / name), str(self.ledger.parent / name))
        self.assertEqual(self.move().status, "moved")

    def test_a_named_ledger_in_a_folder_the_inbox_never_used_is_nothing_to_move(self) -> None:
        empty = self.root / "never-used"
        empty.mkdir()
        self.settings["review_ledger_path"] = str(empty / "review-ledger.sqlite")
        self.assertEqual(self.move().status, "nothing")
        self.assertEqual(self.receipts(), ["complete"])

    def test_no_ledger_named_anywhere_is_still_nothing_to_move(self) -> None:
        self.settings.pop("review_ledger_path")
        self.assertEqual(self.move().status, "nothing")
        self.assertEqual(self.receipts(), ["complete"])


class RefusalsThatTellTheTruthTests(_Move):
    def backups(self) -> list[str]:
        folder = self.records.root / "backups" / "migrations"
        return sorted(path.name for path in folder.glob("*-wave-b")) if folder.is_dir() else []

    def test_damage_on_the_ledgers_first_page_is_refused_as_damage(self) -> None:
        data = bytearray(self.ledger.read_bytes())
        data[100:4096] = b"\xee" * 3996  # the SQLite header is fine; the page that lists its tables is not
        self.ledger.write_bytes(bytes(data))
        before = self.ledger.read_bytes()
        result = self.move()
        self.assertEqual(result.status, "refused", result.message)
        self.assertIn("damaged", result.message)
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertEqual(self.saved, [])
        self.assertEqual(self.backups(), [], "nothing to back up for a ledger that cannot be moved")

    def test_a_ledger_that_is_refused_makes_no_backup_and_no_new_receipt_at_each_start(self) -> None:
        connection = sqlite3.connect(self.ledger)
        connection.execute("CREATE TABLE surprise (x)")
        connection.commit()
        connection.close()
        for _start in range(3):
            self.assertEqual(self.move().status, "restored")
        self.assertEqual(self.backups(), [], "thirty starts must not leave thirty library copies")
        self.assertEqual(self.receipts(), ["restored"])

    def test_a_ledger_below_version_2_is_not_sent_to_a_workbench_that_cannot_open_the_library(self) -> None:
        connection = sqlite3.connect(self.ledger)
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
        connection.close()
        self.assertNotIn("earlier Workbench", self.move().message)

    @unittest.skipUnless(WINDOWS, "a Windows sharing refusal")
    def test_a_ledger_another_program_holds_waits_and_says_so(self) -> None:
        with OutsideHolder(self.ledger, exclusive=True):
            result = self.move()
        self.assertEqual(result.status, "waiting", result.message)
        self.assertIn("open in another program", result.message)
        self.assertEqual(self.receipts(), [])
        self.assertEqual(self.move().status, "moved")

    def test_an_empty_journal_left_beside_the_ledger_does_not_stop_the_move_for_ever(self) -> None:
        self.ledger.with_name(self.ledger.name + "-journal").write_bytes(b"")
        self.assertEqual(self.move().status, "moved")


class ResumeOutcomesTests(_Move):
    def stop_after_the_import(self) -> None:
        with mock.patch.object(inbox_move, "_after_import", return_value=inbox_move.MoveResult("waiting", "cut off")):
            self.move()
        self.assertEqual(self.receipts(), ["imported"])

    def stop_before_the_swap(self) -> None:
        with mock.patch.object(safe_write, "replace_file", side_effect=safe_write.FileInUse("held")):
            self.assertEqual(self.move().status, "waiting")
        self.assertEqual(self.receipts(), ["verified"])

    def test_imported_with_a_check_that_now_fails_is_undone_and_the_next_start_moves(self) -> None:
        self.stop_after_the_import()
        (self.ledger.parent / "queue-index.json").write_text('{"batches": ["changed"]}', encoding="utf-8")
        result = self.move()
        self.assertEqual(result.status, "restored", result.message)
        self.assertEqual(sum(self.rows(table) for table in review_ledger.INBOX_TABLES.values()), 0)
        self.assertEqual(self.move().status, "moved")

    def test_imported_when_the_undo_fails_says_it_is_unfinished_and_not_that_all_is_as_it_was(self) -> None:
        self.stop_after_the_import()
        latest = self.library().execute("SELECT backup_folder FROM legacy_imports ORDER BY import_id DESC").fetchone()
        (Path(latest[0]) / inbox_move.LEDGER_COPY).unlink()
        with mock.patch.object(inbox_move, "_undo_import", return_value=False):
            result = self.move()
        self.assertEqual(result.status, "waiting", result.message)
        self.assertEqual(result.message, inbox_records.MOVE_UNFINISHED)
        self.assertEqual(self.receipts(), ["imported"])

    def test_verified_with_a_ledger_that_changed_says_what_to_do_next(self) -> None:
        self.stop_before_the_swap()
        connection = sqlite3.connect(self.ledger)
        connection.execute("UPDATE batches SET status = 'written_after_the_import'")
        connection.commit()
        connection.close()
        result = self.move()
        self.assertEqual(result.status, "refused", result.message)
        self.assertIn("changed", result.message)
        self.assertIn("HOW_TO_RESTORE.txt", result.message)

    def test_verified_when_the_check_cannot_run_waits_and_does_not_blame_the_ledger(self) -> None:
        self.stop_before_the_swap()
        latest = self.library().execute("SELECT backup_folder FROM legacy_imports ORDER BY import_id DESC").fetchone()
        (Path(latest[0]) / inbox_move.LEDGER_COPY).unlink()
        result = self.move()
        self.assertEqual(result.status, "waiting", result.message)
        self.assertNotIn("changed", result.message)
        self.assertEqual(self.receipts(), ["verified"])


class TheRestoreNoteTests(_Move):
    def test_it_points_at_the_library_from_before_this_version_and_the_real_moved_name(self) -> None:
        earlier = self.records.root / "backups" / "migrations" / "20260101-000000-schema-4-to-5"
        earlier.mkdir(parents=True, exist_ok=True)
        (earlier / recording_records.DATABASE_NAME).write_bytes(b"the library as it was")
        result = self.move()
        note = (Path(result.backup_folder) / "HOW_TO_RESTORE.txt").read_text(encoding="utf-8")
        self.assertIn(str(earlier), note)
        self.assertIn("review-ledger.sqlite.moved-", note)
        self.assertNotIn("Putting back only the library (step 2) puts the Inbox's records back", note)
        self.assertIn("Do not put it back on its own", note)

    def test_264_a_later_structure_steps_backup_is_not_the_library_from_before_the_inbox(self) -> None:
        # The library that went from 4 to 5 and then from 5 to 6 has a newer backup, which has the Inbox's tables and
        # which a version before the move cannot open; one that went from 4 straight to 6 has only that one.
        folders = self.records.root / "backups" / "migrations"
        earlier = folders / "20260101-000000-schema-4-to-5"
        later = folders / "20260102-000000-schema-5-to-6"
        for folder in (earlier, later):
            folder.mkdir(parents=True, exist_ok=True)
            (folder / recording_records.DATABASE_NAME).write_bytes(b"the library as it was")
        result = self.move()
        note = (Path(result.backup_folder) / "HOW_TO_RESTORE.txt").read_text(encoding="utf-8")
        self.assertIn(str(earlier), note)
        self.assertNotIn(str(later), note)

    def test_264_a_library_that_went_from_before_the_inbox_straight_to_now_points_at_that_backup(self) -> None:
        straight = self.records.root / "backups" / "migrations" / "20260103-000000-schema-4-to-6"
        straight.mkdir(parents=True, exist_ok=True)
        (straight / recording_records.DATABASE_NAME).write_bytes(b"the library as it was")
        result = self.move()
        self.assertIn(str(straight), (Path(result.backup_folder) / "HOW_TO_RESTORE.txt").read_text(encoding="utf-8"))

    def test_it_says_so_when_there_is_no_earlier_library(self) -> None:
        result = self.move()
        note = (Path(result.backup_folder) / "HOW_TO_RESTORE.txt").read_text(encoding="utf-8")
        self.assertIn("no earlier copy", note)


class ScansTogetherTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs FFmpeg")
    def test_a_raw_bin_scan_and_an_inbox_scan_running_together_both_finish(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="inbox-together-"))
        self.addCleanup(shutil.rmtree, root, True)
        library = inbox_library.use_own_library(self, root)
        ledger = root / "inbox" / inbox_records.LEDGER_NAME
        inbox_library.ready(ledger)
        raw, sources = root / "raw", root / "sources"
        raw.mkdir()
        sources.mkdir()
        for number in range(3):
            make_recording(raw / f"raw-{number}.mkv")
            make_recording(sources / f"inbox-{number}.mkv")
        finished: dict[str, object] = {}

        def run(name: str, work) -> None:
            try:
                finished[name] = work()
            except Exception as exc:  # noqa: BLE001 - reported by the assertion below
                finished[name] = exc
            finally:
                inbox_records.release()

        options = raw_bin_library.ScanOptions(
            folders=[str(raw)], ffmpeg=FFMPEG, ffprobe=FFPROBE, transcriber=HearingTranscriber({2}),
            library_root=str(library), cache_folder=str(root / "cache"), stable_after_seconds=0)
        threads =[threading.Thread(target=run, args=("raw", lambda: raw_bin_library.scan(options)), daemon=True),
                   threading.Thread(target=run, args=("inbox", lambda: review_inbox.scan_from_request(
                       {"source_folders": [str(sources)], "ledger_path": str(ledger)})), daemon=True)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(240)
            self.assertFalse(thread.is_alive(), "a scan never finished")
        for name, value in finished.items():
            self.assertNotIsInstance(value, Exception, f"{name}: {value}")
        connection = inbox_library.connect(read_only=True)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM inbox_sources").fetchone()[0], 3)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM recordings").fetchone()[0], 3)
        finally:
            connection.close()


class WorkbenchStartTests(unittest.TestCase):
    """The move as a real Workbench start runs it, with the real settings saver and not a stand-in."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="inbox-start-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        inbox_library.use_own_library(self, self.root / "library")
        self.ledger = build_ledger(self.root / "inbox" / "review-ledger.sqlite")
        self.settings = self.root / "settings.json"
        self.settings.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
            "log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
            "output_folder": str(self.root / "out"), "review_ledger_path": str(self.ledger)}}), encoding="utf-8")

    def start(self) -> WorkbenchWindow:
        return WorkbenchWindow(settings_path=self.settings, profiles_dir=self.root / "profiles",
                               resources=_ready_resources())

    def stop(self, window: WorkbenchWindow) -> None:
        window._closing_after_smoke = True
        window.close()
        self.app.processEvents()

    def saved(self) -> dict:
        return json.loads(self.settings.read_text(encoding="utf-8"))["settings"]

    def test_the_first_start_moves_the_ledger_saves_the_folder_and_logs_counts_only(self) -> None:
        window = self.start()
        try:
            self.assertEqual(window.inbox_move_result["status"], "moved", window.inbox_move_result)
            self.assertEqual(window.app_settings["review_inbox_folder"], str(self.ledger.parent))
            log = Path(window.run_log_path).read_text(encoding="utf-8")
            line = next(line for line in log.splitlines() if "records moved into the library" in line)
            self.assertIn("3 recordings", line)
            self.assertNotIn(str(self.root), line)
        finally:
            self.stop(window)
        self.assertEqual(self.saved()["review_inbox_folder"], str(self.ledger.parent))
        self.assertEqual(self.saved()["review_ledger_path"], str(self.ledger), "kept, so an older build finds the note")
        self.assertFalse(inbox_records.is_database(self.ledger))
        second = self.start()
        try:
            self.assertEqual(second.inbox_move_result["status"], "nothing")
            self.assertEqual(second._review_inbox_not_ready(), "")
        finally:
            self.stop(second)

    def test_a_settings_file_that_cannot_be_saved_finishes_at_the_next_start(self) -> None:
        with mock.patch("media_manglers_workbench.app.save_settings", side_effect=OSError("disk full")):
            window = self.start()
        try:
            self.assertEqual(window.inbox_move_result["status"], "waiting")
            self.assertIn("finishes at the next start", window.inbox_move_result["message"])
        finally:
            self.stop(window)
        second = self.start()
        try:
            self.assertEqual(second.inbox_move_result["status"], "moved")
        finally:
            self.stop(second)
        self.assertEqual(self.saved()["review_inbox_folder"], str(self.ledger.parent))

    def test_a_smoke_style_launch_leaves_a_real_ledger_alone(self) -> None:
        original = self.ledger.read_bytes()
        self.settings.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
            "log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
            "output_folder": str(self.root / "out")}}), encoding="utf-8")
        window = self.start()
        try:
            self.assertEqual(window.inbox_move_result["status"], "nothing")
        finally:
            self.stop(window)
        self.assertEqual(self.ledger.read_bytes(), original)

    def test_the_log_names_no_folder_when_the_move_waits(self) -> None:
        offline = self.root / "offline-drive" / "review-ledger.sqlite"
        self.settings.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
            "log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
            "output_folder": str(self.root / "out"), "review_ledger_path": str(offline)}}), encoding="utf-8")
        window = self.start()
        try:
            self.assertEqual(window.inbox_move_result["status"], "waiting")
            self.assertIn(str(offline.parent), window.inbox_move_result["message"], "the page says which folder")
            line = next(line for line in Path(window.run_log_path).read_text(encoding="utf-8").splitlines()
                        if "move into the library" in line)
            self.assertNotIn(str(self.root), line)
        finally:
            self.stop(window)

    def test_the_advanced_settings_show_no_ledger_path_row(self) -> None:
        window = self.start()
        try:
            dialog = AdvancedSettingsDialog(dict(window.run_settings), {}, dict(window.app_settings),
                                            WORKFLOW_REVIEW_NEW_VIDEOS, window)
            try:
                self.assertNotIn("review_ledger_path", dialog.controls, "the plan does not list this row")
            finally:
                dialog.deleteLater()
        finally:
            self.stop(window)

    def test_the_status_check_thread_lets_its_library_connection_go(self) -> None:
        window = self.start()
        try:
            inbox_records.release_all()
            seen: list[int] = []

            def operation(_payload: dict) -> dict:
                inbox_records._library()
                seen.append(threading.get_ident())
                return {}

            thread = ReviewInboxOperationThread({}, operation)
            thread.start()
            self.assertTrue(thread.wait(30000))
            self.app.processEvents()
            self.assertEqual(len(seen), 1)
            self.assertEqual([key for key in inbox_records._shared if key[0] == seen[0]], [])
        finally:
            self.stop(window)

    def test_a_fault_nobody_planned_for_never_stops_the_workbench_opening(self) -> None:
        with mock.patch.object(inbox_move, "move_ledger", side_effect=AttributeError("a fault in the code")):
            window = self.start()
        try:
            self.assertEqual(window.inbox_move_result["status"], "waiting")
            self.assertEqual(window._review_inbox_not_ready(), inbox_records.MOVE_UNFINISHED)
        finally:
            self.stop(window)


if __name__ == "__main__":
    unittest.main()
