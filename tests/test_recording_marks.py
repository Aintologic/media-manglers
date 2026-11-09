"""The bug-report lists in the library (244, Wave A2.1 and A2.2).

The library's structure moves up to 4: confirmed contents, where each copy came from, the Never-use and
Bugs-done marks, and the stopped run Continue picks up. A recording is three layers: its content (the full
hash), the copy the operator manages, and where that copy was seen. Never use belongs to the copy and
follows it when it is renamed or moved; "done in Find my bug reports" is shared by identical copies
(decision E), but only by a copy whose bytes are still the ones the library read. A file saved over a
known path is another copy and inherits nothing.

Copies are stored by the raw bin's own store and found again by its own scan; nothing here writes the
library's tables by hand except to build a library as an older build left it.
"""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core import raw_bin_library, recording_identity, recording_records  # noqa: E402
from tests.test_recording_records import make_wave6_library  # noqa: E402


def make_a1_library(root: Path, recording: Path) -> None:
    """A library as a Wave A1 build left it: structure 3, one recording decided Keep."""

    make_wave6_library(root, recording)
    connection = sqlite3.connect(str(root / "raw-bin-library.sqlite"))
    try:
        recording_records._step_records(connection)
        connection.execute("UPDATE schema_metadata SET value = '3' WHERE key = 'schema_version'")
        connection.commit()
    finally:
        connection.close()


def write_recording(path: Path, seed: int = 1, size: int = 1_200_000) -> Path:
    """Bytes enough to be hashed in full (the raw bin hashes files of 1 MB and more)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    block = bytes((seed * 31 + index) % 251 for index in range(4096))
    path.write_bytes((block * (size // len(block) + 1))[:size])
    return path


def store_copy(records: recording_records.Records, path: Path, folder: Path | None = None) -> int:
    """Store one recording the way a scan stores what it read (``raw_bin_library._store``)."""

    sampled, content = recording_identity.file_identity(path)
    stat = path.stat()
    found = {"guess": raw_bin_library.Guess(raw_bin_library.GUESS_CHECK, "Synthetic."), "size_bytes": stat.st_size,
             "modified_ns": stat.st_mtime_ns, "content_sha256": content, "sampled_sha256": sampled,
             "bytes_read": stat.st_size}
    root_key = raw_bin_library.path_key(folder).rstrip("\\/") if folder else ""
    return raw_bin_library._store(records.connection(), path, root_key, found, None)


def scan(library: Path, folder: Path) -> dict:
    """The raw bin's real scan of one folder. Nothing here can be decoded, which is fine: a moved copy is
    found again by its hash alone, and anything new is stored as unreadable."""

    options = raw_bin_library.ScanOptions(folders=[str(folder)], ffmpeg="no-ffmpeg-here", ffprobe="no-ffprobe-here",
                                          library_root=str(library), cache_folder=str(library.parent / "cache"),
                                          stable_after_seconds=0)
    return raw_bin_library.scan(options)


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = self.root / "library"
        self.watched = self.root / "watched"
        self.records = recording_records.Records(self.library)

    def tearDown(self) -> None:
        self.records.close()
        self.temp.cleanup()


class StructureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = self.root / "library"
        self.recording = write_recording(self.root / "race.mkv")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _tables(self) -> dict[str, set[str]]:
        connection = sqlite3.connect(str(self.library / "raw-bin-library.sqlite"))
        try:
            names = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
            return {name: {row[1] for row in connection.execute(f"PRAGMA table_info({name})")} for name in names}
        finally:
            connection.close()

    def test_an_a1_library_moves_up_to_the_current_version_with_a_backup_first_and_keeps_every_row(self) -> None:
        make_a1_library(self.library, self.recording)
        connection = sqlite3.connect(str(self.library / "raw-bin-library.sqlite"))
        with connection:
            connection.execute("UPDATE recordings SET content_sha256 = ?", ("c" * 64,))
        connection.close()
        raw_bin_library.connect(self.library, backup=False).close()

        # 4 was Wave A2 (244); 5 is Wave B2b (224), the Inbox's tables; 6 is Wave C1 (264), speech facts. One step
        # from 3, one backup.
        self.assertEqual(recording_records.SCHEMA_VERSION, 7)  # 7 is Wave C2 (242), the editor's index
        tables = self._tables()
        for table in ("contents", "marks", "resume_points", "inbox_sources", "inbox_batches"):
            self.assertIn(table, tables)
        self.assertIn("registered_by", tables["locations"])
        backups = list((self.library / "backups" / "migrations").glob("*-schema-3-to-7/raw-bin-library.sqlite"))
        self.assertEqual(len(backups), 1, "one backup, taken before the step")
        connection = sqlite3.connect(str(self.library / "raw-bin-library.sqlite"))
        try:
            self.assertEqual(connection.execute("SELECT value FROM schema_metadata").fetchone()[0], "7")
            self.assertEqual(connection.execute("SELECT decision FROM recordings").fetchone()[0], "keep")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM recording_labels").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT registered_by FROM locations").fetchall(), [("scan",)],
                             "every copy a scan found says so")
            self.assertEqual(connection.execute("SELECT content_sha256 FROM contents").fetchall(), [("c" * 64,)],
                             "each confirmed content is listed once")
            self.assertEqual(connection.execute("SELECT from_version, to_version FROM schema_steps").fetchall(),
                             [(3, 7)])
        finally:
            connection.close()

    def test_a_mark_needs_a_copy_or_an_old_path_and_a_copy_or_path_has_one_active_never_use(self) -> None:
        connection = recording_records.connect(self.library, backup=False)
        try:
            add = ("INSERT INTO marks(kind, recording_id, old_key, set_by, created_utc) "
                   "VALUES ('never_use', ?, ?, 'test', '2026-10-26T10:00:00Z')")
            with self.assertRaises(sqlite3.IntegrityError):
                with connection:
                    connection.execute(add, (None, None))
            with connection:
                connection.execute(add, (None, "q:\\old\\one.mkv"))
            with self.assertRaises(sqlite3.IntegrityError):
                with connection:
                    connection.execute(add, (None, "q:\\old\\one.mkv"))
            with connection:
                connection.execute("UPDATE marks SET cleared_utc = '2026-10-26T11:00:00Z'")
                connection.execute(add, (None, "q:\\old\\one.mkv"))
        finally:
            connection.close()

    def test_every_new_table_has_a_privacy_class_and_the_lists_are_personal(self) -> None:
        self.assertEqual(recording_records.TABLE_PRIVACY["marks"], recording_records.PERSONAL)
        self.assertEqual(recording_records.TABLE_PRIVACY["resume_points"], recording_records.PERSONAL)
        self.assertEqual(recording_records.TABLE_PRIVACY["contents"], recording_records.PRIVATE)


class LocateTests(_Case):
    def test_a_copy_is_confirmed_only_while_the_file_is_as_the_library_last_read_it(self) -> None:
        path = write_recording(self.watched / "race.mkv")
        copy = store_copy(self.records, path, self.watched)
        found = self.records.locate(path)
        self.assertEqual((found["recording_id"], found["confirmed"]), (copy, True))
        os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 5_000_000_000))
        found = self.records.locate(str(path).upper())
        self.assertEqual((found["recording_id"], found["confirmed"]), (copy, False), "path only now")
        self.assertIsNone(self.records.locate(self.watched / "not-known.mkv"))

    def test_a_recording_outside_the_watched_folders_gets_a_copy_kept_off_the_raw_bin_list(self) -> None:
        store_copy(self.records, write_recording(self.watched / "watched.mkv"), self.watched)
        outside = write_recording(self.root / "elsewhere" / "from-a-list.mkv", seed=2)
        self.assertTrue(self.records.set_never_use(outside, True, by="Find my bug reports"))
        copy = self.records.locate(outside)
        self.assertEqual(copy["registered_by"], "outside")
        self.assertEqual(self.records.never_use_entries()[0]["path"], str(outside))
        listed = [row["path"] for row in self.records.list_recordings()]
        self.assertEqual(listed, [str(self.watched / "watched.mkv")], "the raw bin lists your watched folders")
        self.assertEqual([row["path"] for row in recording_records.list_recordings(root=self.library)], listed)

    def test_a_recording_registered_by_a_list_and_scanned_later_keeps_its_marks(self) -> None:
        path = write_recording(self.watched / "new.mkv")
        self.records.set_never_use(path, True, by="player")
        self.assertEqual(scan(self.library, self.watched)["status"], "completed")
        copy = self.records.locate(path)
        self.assertEqual(copy["registered_by"], "scan")
        self.assertIn(str(path).lower(), self.records.never_use_keys())
        self.assertEqual(len(self.records.list_recordings()), 1)


class NeverUseTests(_Case):
    def test_never_use_is_per_copy_and_allow_again_keeps_a_record_of_it(self) -> None:
        first = write_recording(self.watched / "first.mkv")
        second = write_recording(self.watched / "copy-of-first.mkv")
        store_copy(self.records, first, self.watched)
        store_copy(self.records, second, self.watched)
        self.assertTrue(self.records.set_never_use(first, True, by="player"))
        self.assertFalse(self.records.set_never_use(str(first).upper(), True, by="player"), "already on the list")
        keys = self.records.never_use_keys()
        self.assertIn(str(first).lower(), keys)
        self.assertNotIn(str(second).lower(), keys, "the identical copy is not never-use")
        self.assertTrue(self.records.set_never_use(first, False, by="Find my bug reports"))
        self.assertEqual(self.records.never_use_keys(), set())
        self.assertEqual(self.records.never_use_entries(), [])
        row = self.records.connection().execute(
            "SELECT cleared_utc, cleared_by FROM marks WHERE kind = 'never_use'").fetchone()
        self.assertIsNotNone(row["cleared_utc"])
        self.assertEqual(row["cleared_by"], "Find my bug reports")
        self.assertFalse(self.records.set_never_use(first, False, by="player"), "nothing left to allow")

    def test_a_never_use_mark_follows_a_watched_recording_renamed_or_moved(self) -> None:
        old = write_recording(self.watched / "session.mkv")
        store_copy(self.records, old, self.watched)
        self.records.set_never_use(old, True, by="player")
        moved = self.watched / "renamed" / "session-renamed.mkv"
        moved.parent.mkdir()
        old.rename(moved)
        self.assertEqual(scan(self.library, self.watched)["status"], "completed")
        keys = self.records.never_use_keys()
        self.assertIn(str(moved).lower(), keys)
        self.assertNotIn(str(old).lower(), keys)
        self.assertEqual([entry["path"] for entry in self.records.never_use_entries()], [str(moved)],
                         "the list shows where it is now")

    def test_a_file_saved_over_a_known_path_inherits_nothing(self) -> None:
        path = write_recording(self.watched / "session.mkv")
        store_copy(self.records, path, self.watched)
        self.records.set_never_use(path, True, by="player")
        self.records.mark_done("", [(path, "done")], by="Find my bug reports", day="2026-10-20")
        write_recording(path, seed=9, size=1_300_000)
        self.assertEqual(scan(self.library, self.watched)["status"], "completed")
        self.assertNotIn(str(path).lower(), self.records.never_use_keys())
        self.assertNotIn(str(path).lower(), self.records.done_dates())
        self.assertEqual(self.records.done_on(path), "")
        # The copy that was there keeps its mark, shown where it was.
        self.assertEqual([entry["path"] for entry in self.records.never_use_entries()], [str(path)])

    def test_both_spellings_of_a_path_answer(self) -> None:
        path = write_recording(self.watched / "Session One.mkv")
        store_copy(self.records, path, self.watched)
        self.records.set_never_use(str(path).replace("\\", "/"), True, by="player")
        keys = self.records.never_use_keys()
        self.assertIn(str(path).lower(), keys)
        self.assertIn(os.path.normcase(os.path.abspath(str(path))), keys)
        self.assertTrue(self.records.set_never_use(str(path).upper(), False, by="player"))


class DoneTests(_Case):
    def test_two_live_copies_share_done_but_not_never_use(self) -> None:
        first = write_recording(self.watched / "first.mkv")
        second = write_recording(self.root / "backup-drive" / "first-copy.mkv")
        store_copy(self.records, first, self.watched)
        store_copy(self.records, second, self.root / "backup-drive")
        self.assertEqual(self.records.mark_done("", [(first, "done")], by="Find my bug reports", day="2026-10-21"), 1)
        dates = self.records.done_dates()
        self.assertEqual(dates[str(first).lower()], "2026-10-21")
        self.assertEqual(dates[str(second).lower()], "2026-10-21", "decision E: identical content was mined")
        self.assertEqual(self.records.done_on(second), "2026-10-21")
        self.records.set_never_use(first, True, by="player")
        self.assertNotIn(str(second).lower(), self.records.never_use_keys())

    def test_a_copy_whose_bytes_are_not_proven_now_shares_nothing(self) -> None:
        first = write_recording(self.watched / "first.mkv")
        second = write_recording(self.watched / "second.mkv")
        store_copy(self.records, first, self.watched)
        store_copy(self.records, second, self.watched)
        self.records.mark_done("", [(first, "done")], by="Find my bug reports", day="2026-10-21")
        os.utime(second, ns=(second.stat().st_atime_ns, second.stat().st_mtime_ns + 5_000_000_000))
        self.assertNotIn(str(second).lower(), self.records.done_dates())
        self.assertEqual(self.records.done_on(second), "")
        self.assertEqual(self.records.done_on(first), "2026-10-21", "its own mark still counts")

    def test_the_newest_mark_gives_the_date_and_no_narration_is_its_own_outcome(self) -> None:
        path = write_recording(self.watched / "quiet.mkv")
        store_copy(self.records, path, self.watched)
        self.records.mark_done("", [(path, "done")], by="Find my bug reports", day="2026-10-01")
        self.records.mark_done("", [(path, "no_narration")], by="Find my bug reports", day="2026-10-05")
        self.assertEqual(self.records.done_on(path), "2026-10-05")
        outcomes = [row[0] for row in self.records.connection().execute(
            "SELECT outcome FROM marks WHERE kind = 'bugs_done' ORDER BY mark_id")]
        self.assertEqual(outcomes, ["done", "no_narration"])

    def test_done_comes_from_the_run_that_made_it(self) -> None:
        path = write_recording(self.watched / "race.mkv")
        store_copy(self.records, path, self.watched)
        run_id = self.records.open_run(kind="bug_reports", title="Find my bug reports", items=[str(path)])
        self.records.mark_done(run_id, [(path, "done")], by="Find my bug reports", day="2026-10-22")
        row = self.records.connection().execute("SELECT run_id, set_by FROM marks").fetchone()
        self.assertEqual((row["run_id"], row["set_by"]), (run_id, "Find my bug reports"))

    def test_looking_only_at_the_library_never_reads_the_file(self) -> None:
        first = write_recording(self.watched / "first.mkv")
        second = write_recording(self.watched / "second.mkv")
        store_copy(self.records, first, self.watched)
        store_copy(self.records, second, self.watched)
        self.records.mark_done("", [(first, "done")], by="Find my bug reports", day="2026-10-21")
        # A copy that is only shared "done" needs its file looked at; without that it says nothing yet.
        started = time.monotonic()
        self.assertEqual(self.records.done_on(second, look=False), "")
        self.assertEqual(self.records.done_on(first, look=False), "2026-10-21")
        self.assertLess(time.monotonic() - started, 5)

    def test_a_copy_the_last_scan_found_missing_is_not_looked_for(self) -> None:
        first = write_recording(self.watched / "first.mkv")
        gone = write_recording(self.watched / "first-copy.mkv")
        store_copy(self.records, first, self.watched)
        store_copy(self.records, gone, self.watched)
        self.records.mark_done("", [(first, "done")], by="Find my bug reports", day="2026-10-21")
        gone.unlink()
        self.assertEqual(scan(self.library, self.watched)["status"], "completed")
        looked: list[str] = []
        real = recording_records._unchanged

        def spy(path, size, modified):
            looked.append(str(path))
            return real(path, size, modified)

        with mock.patch.object(recording_records, "_unchanged", side_effect=spy):
            dates = self.records.done_dates()
        self.assertEqual(dates[str(first).lower()], "2026-10-21")
        self.assertNotIn(str(gone), looked, "a copy the scan found missing is not looked for on the drive")


class ChangedBeforeTheNextScanTests(_Case):
    """A list marks a watched recording that was renamed or saved over since the last scan."""

    def _kept(self, path: Path) -> int:
        recording = store_copy(self.records, path, self.watched)
        raw_bin_library.set_decision(self.records.connection(), [recording], "keep")
        raw_bin_library.set_label(self.records.connection(), [recording], "Race night", True)
        return recording

    def _mark(self, path: Path) -> None:
        self.assertTrue(self.records.set_never_use(path, True, by="player"))
        self.records.mark_done("", [(path, "done")], by="Find my bug reports", day="2026-10-22")

    def _assert_one_recording_with_everything(self, path: Path, recording: int) -> None:
        self.assertEqual(self.records.locate(path)["recording_id"], recording, "the recording you decided on")
        rows = self.records.list_recordings()
        self.assertEqual([(row["path"], row["missing"], row["decision"], row["labels"]) for row in rows],
                         [(str(path), False, "keep", ["Race night"])], "nothing is left behind as Missing")
        self.assertIn(str(path).lower(), self.records.never_use_keys())
        self.assertEqual([entry["path"] for entry in self.records.never_use_entries()], [str(path)])
        self.assertEqual(self.records.done_on(path), "2026-10-22")
        self.assertEqual(self.records.connection().execute("SELECT COUNT(*) FROM recordings").fetchone()[0], 1,
                         "the stand-in the list made is gone")

    def test_a_recording_renamed_then_marked_before_the_next_scan_keeps_its_decision_and_the_marks(self) -> None:
        old = write_recording(self.watched / "session.mkv")
        recording = self._kept(old)
        renamed = old.with_name("session-renamed.mkv")
        old.rename(renamed)
        self._mark(renamed)
        self.assertEqual(scan(self.library, self.watched)["status"], "completed")
        self._assert_one_recording_with_everything(renamed, recording)

    def test_the_store_gives_a_moved_recording_its_new_path_and_the_marks_a_list_made_there(self) -> None:
        old = write_recording(self.watched / "session.mkv")
        recording = self._kept(old)
        moved = self.watched / "moved" / "session.mkv"
        moved.parent.mkdir()
        old.rename(moved)
        self._mark(moved)
        self.assertEqual(store_copy(self.records, moved, self.watched), recording)
        self._assert_one_recording_with_everything(moved, recording)

    def test_a_copy_a_list_marked_beside_a_recording_still_there_stays_a_copy_of_its_own(self) -> None:
        first = write_recording(self.watched / "session.mkv")
        recording = self._kept(first)
        copy = write_recording(self.watched / "session-copy.mkv")
        self.assertTrue(self.records.set_never_use(copy, True, by="player"))
        copied = store_copy(self.records, copy, self.watched)
        self.assertNotEqual(copied, recording)
        found = self.records.locate(copy)
        self.assertEqual((found["recording_id"], found["registered_by"]), (copied, "scan"))
        keys = self.records.never_use_keys()
        self.assertIn(str(copy).lower(), keys)
        self.assertNotIn(str(first).lower(), keys, "Never use stays with the copy you marked")
        self.assertEqual(len(self.records.list_recordings()), 2)

    def test_a_file_saved_over_a_known_path_and_marked_before_the_next_scan_gets_the_marks_itself(self) -> None:
        path = write_recording(self.watched / "session.mkv")
        twin = write_recording(self.watched / "session-twin.mkv")
        old = store_copy(self.records, path, self.watched)
        store_copy(self.records, twin, self.watched)
        write_recording(path, seed=9, size=1_300_000)  # saved over, and no scan since
        self._mark(path)
        self.assertNotEqual(self.records.locate(path)["recording_id"], old, "another copy")
        self.assertEqual(self.records.done_on(path), "2026-10-22")
        self.assertEqual(self.records.done_on(twin), "", "the twin holds the old bytes, which nobody mined")
        self.assertNotIn(str(twin).lower(), self.records.done_dates())
        self.assertEqual(scan(self.library, self.watched)["status"], "completed")
        self.assertIn(str(path).lower(), self.records.never_use_keys(), "the marks stay with the file there now")
        self.assertEqual(self.records.done_on(path), "2026-10-22")
        self.assertEqual(self.records.done_on(twin), "")


class StoppedRunTests(_Case):
    def test_the_stopped_run_is_kept_exactly_as_given_and_cleared(self) -> None:
        self.assertIsNone(self.records.stopped_bug_run())
        record = {"folder": str(self.root / "run"), "recordings": [r"Q:\One.mkv", r"Q:\two.MKV"],
                  "tracks": {r"Q:\two.MKV": 3}}
        self.records.set_stopped_bug_run(record)
        self.assertEqual(self.records.stopped_bug_run(), record)
        newer = {**record, "recordings": [r"Q:\One.mkv"], "tracks": {}}
        self.records.set_stopped_bug_run(newer)
        self.assertEqual(self.records.stopped_bug_run(), newer, "one stopped run at a time")
        self.records.set_stopped_bug_run(None)
        self.assertIsNone(self.records.stopped_bug_run())
        kept = self.records.connection().execute(
            "SELECT COUNT(*) FROM resume_points WHERE cleared_utc IS NOT NULL").fetchone()[0]
        self.assertEqual(kept, 2, "cleared ones are kept, not deleted")


if __name__ == "__main__":
    unittest.main()
