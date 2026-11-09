"""One checked copy of a database (224, Wave B2a, F8 and note 4).

A backup the app relies on is copied with SQLite's own backup call to a partial name beside its real one,
checked there (the copy passes SQLite's damage check, and every table holds as many rows as the original),
and only then given its real name. So a damaged, short or empty copy never looks like a backup, and a file
already sitting at the backup's name is never trusted. The settings mover and the library's structure
backups use it now; Wave B2b's move uses it for both databases.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

from media_manglers.core import inbox_records, review_relocation, safe_write
import pytest
from tests import inbox_library  # noqa: E402

# 224 (Wave B2b): the Inbox's records are in this test's library, moved in (nothing to move).
pytestmark = pytest.mark.inbox_moved


def _database(path: Path, rows: int = 5) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("CREATE TABLE runs (run_id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT)")
    connection.execute("CREATE TABLE notes (note TEXT)")
    connection.executemany("INSERT INTO runs(title) VALUES (?)", [(f"run {n}",) for n in range(rows)])
    connection.execute("INSERT INTO notes VALUES ('one')")
    connection.commit()
    return connection


def _write_damaged(_connection: sqlite3.Connection, partial: Path) -> None:
    """A copy that went wrong: the start of a database file and then nothing."""

    Path(partial).write_bytes(b"SQLite format 3\x00" + b"\x00" * 84)


class CheckedCopyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="checked-copy-"))
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.source = _database(self.folder / "library.sqlite")
        self.addCleanup(self.source.close)
        self.target = self.folder / "backup" / "library.sqlite"
        self.target.parent.mkdir()

    def _leftovers(self) -> list[str]:
        return sorted(path.name for path in self.target.parent.iterdir() if path.name != self.target.name)

    def test_a_good_copy_gets_its_name_with_every_tables_rows(self) -> None:
        counts = safe_write.checked_copy(self.source, self.target)
        self.assertEqual(counts["runs"], 5)
        self.assertEqual(counts["notes"], 1)
        copy = sqlite3.connect(self.target)
        try:
            self.assertEqual(copy.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(copy.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 5)
        finally:
            copy.close()
        self.assertEqual(self._leftovers(), [])

    def test_a_damaged_copy_never_gets_the_backups_name(self) -> None:
        with mock.patch.object(safe_write, "_backup_into", side_effect=_write_damaged):
            with self.assertRaises(safe_write.CopyNotChecked) as raised:
                safe_write.checked_copy(self.source, self.target)
        self.assertIn("did not check out", str(raised.exception))
        self.assertFalse(self.target.exists())
        self.assertEqual(self._leftovers(), [], "the partial copy is removed too")

    def test_a_short_copy_never_gets_the_backups_name(self) -> None:
        real = safe_write._backup_into

        def short(connection: sqlite3.Connection, partial: Path) -> None:
            real(connection, partial)
            copy = sqlite3.connect(partial)
            copy.execute("DELETE FROM runs WHERE run_id = 1")
            copy.commit()
            copy.close()

        with mock.patch.object(safe_write, "_backup_into", side_effect=short):
            with self.assertRaises(safe_write.CopyNotChecked):
                safe_write.checked_copy(self.source, self.target)
        self.assertFalse(self.target.exists())

    def test_a_file_already_at_the_backups_name_is_never_trusted(self) -> None:
        self.target.write_bytes(b"")
        with self.assertRaises(FileExistsError):
            safe_write.checked_copy(self.source, self.target)
        self.assertEqual(self.target.read_bytes(), b"", "it is refused, not overwritten, unless asked")
        safe_write.checked_copy(self.source, self.target, overwrite=True)
        self.assertGreater(self.target.stat().st_size, 0)

    def test_a_partial_copy_an_earlier_crash_left_is_not_reused(self) -> None:
        partial = self.target.with_name(self.target.name + ".partial")
        partial.write_bytes(b"left by a crash")
        safe_write.checked_copy(self.source, self.target)
        self.assertFalse(partial.exists())
        self.assertEqual(self._leftovers(), [])


class RelocationBackupTests(unittest.TestCase):
    """Note 4: a relocation whose backup failed could leave an empty file that the next try accepted, because
    an empty file passes SQLite's damage check."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="relocation-backup-"))
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.ledger = self.folder / "inbox" / "review-ledger.sqlite"
        inbox_library.ready(self.ledger)
        self.backup = self.folder / "operation" / "backup" / "review-ledger.sqlite.bak"

    def _sources(self, path: Path) -> int:
        connection = sqlite3.connect(path)
        try:
            return int(connection.execute("SELECT COUNT(*) FROM inbox_sources").fetchone()[0])
        finally:
            connection.close()

    def test_an_empty_backup_a_failed_try_left_is_replaced_by_a_checked_copy(self) -> None:
        self.backup.parent.mkdir(parents=True)
        self.backup.write_bytes(b"")
        review_relocation._backup_database(self.ledger, self.backup, journal=None)
        self.assertGreater(self.backup.stat().st_size, 0)
        self.assertEqual(self._sources(self.backup), 0)

    def test_a_run_already_under_way_keeps_its_backup_and_refuses_an_empty_one(self) -> None:
        # With a journal, the ledger may already have changed: the backup from before is the one to keep.
        self.backup.parent.mkdir(parents=True)
        self.backup.write_bytes(b"")
        with self.assertRaises(review_relocation.RelocationError):
            review_relocation._backup_database(self.ledger, self.backup, journal={"phase": "journal_created"})
        self.assertEqual(self.backup.read_bytes(), b"")

    def test_a_run_already_under_way_reuses_its_good_backup(self) -> None:
        review_relocation._backup_database(self.ledger, self.backup, journal=None)
        before = self.backup.read_bytes()
        review_relocation._backup_database(self.ledger, self.backup, journal={"phase": "database_committed"})
        self.assertEqual(self.backup.read_bytes(), before)

    def test_the_relocation_backup_is_a_checked_copy(self) -> None:
        with mock.patch.object(safe_write, "_backup_into", side_effect=_write_damaged):
            with self.assertRaises(safe_write.CopyNotChecked):
                review_relocation._backup_database(self.ledger, self.backup, journal=None)
        self.assertFalse(self.backup.exists())


if __name__ == "__main__":
    unittest.main()
