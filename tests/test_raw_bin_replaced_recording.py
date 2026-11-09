"""268: a different recording saved under a file name the raw bin already knows.

Everything goes through the real scan of real recordings made with FFmpeg (see
``test_raw_bin_library``), and the Inbox's verdict through a ledger finalized by the Inbox's own
finalization. A recording is known by its content: new content at a known path is another recording,
with its own entry, and the one that was there keeps its decision and labels and shows as Missing, as a
recording that disappeared does (215). A renamed or moved file with the same content keeps its tags.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core import raw_bin_library  # noqa: E402
from tests.test_raw_bin_library import FFMPEG, FFPROBE, HearingTranscriber, make_recording  # noqa: E402
import pytest
from tests import inbox_library  # noqa: E402

# 224 (Wave B2b): the Inbox's records are in this test's library, moved in (nothing to move).
pytestmark = pytest.mark.inbox_moved


class _LibraryCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.raw = self.root / "raw"
        self.library = self.root / "library"
        self.cache = self.root / "cache"
        self.environment = mock.patch.dict(os.environ, {})
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temp.cleanup()

    def _scan(self, folder: Path | None = None) -> dict:
        options = raw_bin_library.ScanOptions(
            folders=[str(folder or self.raw)], ffmpeg=FFMPEG, ffprobe=FFPROBE, transcriber=HearingTranscriber({2}),
            library_root=str(self.library), cache_folder=str(self.cache), stable_after_seconds=0)
        result = raw_bin_library.scan(options)
        self.assertEqual(result["status"], "completed", result)
        return result

    def _rows(self) -> list[dict]:
        # 224 (Wave B2b): the Inbox's verdict comes from the same library as the raw bin's list.
        connection = raw_bin_library.connect(self.library)
        try:
            return raw_bin_library.list_recordings(connection)
        finally:
            connection.close()

    def _tag(self, recording_id: int, decision: str, label: str) -> None:
        connection = raw_bin_library.connect(self.library)
        try:
            raw_bin_library.set_decision(connection, [recording_id], decision)
            raw_bin_library.set_label(connection, [recording_id], label, True)
        finally:
            connection.close()

    @staticmethod
    def _one(rows: list[dict], recording_id: int) -> dict:
        return next(row for row in rows if row["recording_id"] == recording_id)


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class ReplacedRecordingTests(_LibraryCase):
    def test_a_different_recording_at_a_known_path_gets_its_own_entry(self) -> None:
        path = make_recording(self.raw / "session.mkv")
        self._scan()
        first = self._rows()[0]
        self._tag(first["recording_id"], raw_bin_library.DECISION_KEEP, "YouTube")

        # Another race saved under the same file name.
        path.unlink()
        make_recording(path, seconds=200, game_idle=(10, 40))
        self._scan()
        rows = self._rows()
        self.assertEqual(len(rows), 2, "the new content is a recording of its own")
        old = self._one(rows, first["recording_id"])
        new = next(row for row in rows if row["recording_id"] != first["recording_id"])
        self.assertEqual(old["decision"], raw_bin_library.DECISION_KEEP)
        self.assertEqual(old["labels"], ["YouTube"])
        self.assertTrue(old["missing"], "the old recording is no longer there")
        self.assertEqual(Path(old["path"]), path, "it is still shown by the name and folder it had")
        self.assertEqual(new["decision"], raw_bin_library.DECISION_UNDECIDED, "no decision is carried over")
        self.assertEqual(new["labels"], [], "no labels are carried over")
        self.assertFalse(new["missing"])
        self.assertEqual(Path(new["path"]), path)
        self.assertNotEqual(new["content_sha256"], old["content_sha256"])

        again = self._scan()
        self.assertEqual((again["files_read"], again["unchanged"]), (0, 1), "the new entry holds the path now")
        self.assertEqual(len(self._rows()), 2)

    def test_a_recording_saved_over_a_file_too_small_to_hash_does_not_get_its_delete_mark(self) -> None:
        # An almost empty file is never hashed (Empty); a different size alone says the content changed.
        path = self.raw / "session.mkv"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"not a recording" * 50)
        self._scan()
        empty = self._rows()[0]
        self.assertEqual((empty["guess"], empty["content_sha256"]), (raw_bin_library.GUESS_EMPTY, None))
        self._tag(empty["recording_id"], raw_bin_library.DECISION_DELETE, "B-roll")

        path.unlink()
        make_recording(path)
        self._scan()
        rows = self._rows()
        self.assertEqual(len(rows), 2)
        new = next(row for row in rows if row["recording_id"] != empty["recording_id"])
        self.assertEqual((new["decision"], new["labels"], new["guess"]),
                         (raw_bin_library.DECISION_UNDECIDED, [], raw_bin_library.GUESS_KEEP))
        old = self._one(rows, empty["recording_id"])
        self.assertEqual((old["decision"], old["missing"]), (raw_bin_library.DECISION_DELETE, True))

    def test_the_old_recording_put_back_gets_its_place_and_tags_back(self) -> None:
        path = make_recording(self.raw / "session.mkv")
        self._scan()
        first = self._rows()[0]
        self._tag(first["recording_id"], raw_bin_library.DECISION_KEEP, "YouTube")
        kept = self.root / "kept-aside.mkv"
        shutil.copy2(path, kept)
        path.unlink()
        make_recording(path, seconds=200, game_idle=(10, 40))
        self._scan()
        replacement = next(row for row in self._rows() if row["recording_id"] != first["recording_id"])
        self._tag(replacement["recording_id"], raw_bin_library.DECISION_DELETE, "B-roll")

        path.unlink()
        shutil.copy2(kept, path)
        self._scan()
        rows = self._rows()
        self.assertEqual(len(rows), 2)
        back = self._one(rows, first["recording_id"])
        self.assertEqual((back["decision"], back["labels"], back["missing"]),
                         (raw_bin_library.DECISION_KEEP, ["YouTube"], False))
        self.assertEqual(Path(back["path"]), path)
        gone = self._one(rows, replacement["recording_id"])
        self.assertEqual((gone["decision"], gone["labels"], gone["missing"]),
                         (raw_bin_library.DECISION_DELETE, ["B-roll"], True))
        self.assertEqual(Path(gone["path"]), path)

    def test_a_recording_moved_onto_a_deleted_one_s_name_keeps_its_own_tags(self) -> None:
        first_path = make_recording(self.raw / "a.mkv")
        second_path = make_recording(self.raw / "b.mkv", seconds=200, game_idle=(10, 40))
        self._scan()
        rows = self._rows()
        first = next(row for row in rows if Path(row["path"]) == first_path)
        second = next(row for row in rows if Path(row["path"]) == second_path)
        self._tag(first["recording_id"], raw_bin_library.DECISION_KEEP, "YouTube")
        self._tag(second["recording_id"], raw_bin_library.DECISION_DELETE, "B-roll")

        first_path.unlink()
        second_path.rename(first_path)
        self._scan()
        rows = self._rows()
        self.assertEqual(len(rows), 2)
        moved = self._one(rows, second["recording_id"])
        self.assertEqual((moved["decision"], moved["labels"], moved["missing"]),
                         (raw_bin_library.DECISION_DELETE, ["B-roll"], False))
        self.assertEqual(Path(moved["path"]), first_path)
        deleted = self._one(rows, first["recording_id"])
        self.assertEqual((deleted["decision"], deleted["labels"], deleted["missing"]),
                         (raw_bin_library.DECISION_KEEP, ["YouTube"], True))
        self.assertEqual(Path(deleted["path"]), first_path, "shown Missing by the name it had, not as a blank row")

    def test_a_copy_saved_over_a_known_name_is_a_copy_and_the_one_it_replaced_is_missing(self) -> None:
        first_path = make_recording(self.raw / "a.mkv")
        second_path = make_recording(self.raw / "b.mkv", seconds=200, game_idle=(10, 40))
        self._scan()
        rows = self._rows()
        first = next(row for row in rows if Path(row["path"]) == first_path)
        second = next(row for row in rows if Path(row["path"]) == second_path)
        self._tag(first["recording_id"], raw_bin_library.DECISION_KEEP, "YouTube")

        first_path.unlink()
        shutil.copy2(second_path, first_path)
        self._scan()
        rows = self._rows()
        self.assertEqual(len(rows), 3, "two live copies stay two entries, and the replaced one is kept")
        copy = next(row for row in rows if row["recording_id"] not in (first["recording_id"], second["recording_id"]))
        self.assertEqual((copy["duplicate_of"], copy["decision"], copy["labels"], Path(copy["path"])),
                         (second["recording_id"], raw_bin_library.DECISION_UNDECIDED, [], first_path))
        replaced = self._one(rows, first["recording_id"])
        self.assertEqual((replaced["decision"], replaced["labels"], replaced["missing"], Path(replaced["path"])),
                         (raw_bin_library.DECISION_KEEP, ["YouTube"], True, first_path))

    def test_a_renamed_recording_still_keeps_its_tags(self) -> None:
        path = make_recording(self.raw / "session.mkv")
        self._scan()
        first = self._rows()[0]
        self._tag(first["recording_id"], raw_bin_library.DECISION_KEEP, "YouTube")
        renamed = self.raw / "renamed" / "race night.mkv"
        renamed.parent.mkdir()
        path.rename(renamed)
        self._scan()
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["recording_id"], rows[0]["decision"], rows[0]["labels"], rows[0]["missing"]),
                         (first["recording_id"], raw_bin_library.DECISION_KEEP, ["YouTube"], False))
        self.assertEqual(Path(rows[0]["path"]), renamed)


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class ReviewedByInboxTests(_LibraryCase):
    """The Inbox's verdict comes from records the Inbox's own finalization finished (no findings), in the same
    library the raw bin scans into (224, Wave B2b)."""

    def setUp(self) -> None:
        super().setUp()
        from tests.test_review_inbox_finalization import ReviewInboxFinalizationTests  # noqa: PLC0415

        self.inbox = ReviewInboxFinalizationTests(methodName="runTest")
        self.inbox.setUp()
        self.addCleanup(self.inbox.tearDown)
        self.inbox._accept()
        finalized = self.inbox._finalize(self.inbox._preview())
        self.assertEqual(finalized["status"], "finalized_no_findings")
        self.sources = Path(self.inbox.fixture.fixture.sources)
        # The Inbox's records are in its own test library; the raw bin scans into that same library.
        from media_manglers.core import recording_records  # noqa: PLC0415

        self.library = recording_records.library_root()

    def test_a_different_recording_at_a_reviewed_path_is_not_reviewed(self) -> None:
        replaced = self.sources / "source-00.mp4"
        untouched = self.sources / "source-01.mp4"
        ledger = inbox_library.connect(read_only=True)
        try:
            self.assertIn(raw_bin_library.path_key(replaced), raw_bin_library.inbox_reviewed(ledger)[1],
                          "the Inbox finished a recording at this path")
        finally:
            ledger.close()
        ledger = inbox_library.connect(read_only=True)
        try:
            known = [content for content, path in ledger.execute(
                "SELECT s.content_sha256, l.original_path FROM inbox_sources s JOIN inbox_source_locations l ON l.source_id = s.source_id")
                if Path(path) == replaced]
        finally:
            ledger.close()
        self.assertTrue(known and all(known), "the Inbox knows the content it reviewed there, so both hashes are known")
        # Another recording saved under the reviewed one's name.
        replaced.unlink()
        make_recording(replaced, seconds=120)
        self._scan(self.sources)
        rows = {Path(row["path"]).name: row for row in self._rows()}
        self.assertTrue(rows["source-00.mp4"]["content_sha256"], "the raw bin knows the new content")
        self.assertFalse(rows["source-00.mp4"]["reviewed_by_inbox"],
                         "both contents are known and differ: it is not the recording the Inbox reviewed")
        # The Inbox's own test file is too small for the raw bin to hash (it is Empty): only the path and
        # the size are known, and nothing says it is another recording, so it shows as reviewed.
        self.assertIsNone(rows["source-01.mp4"]["content_sha256"])
        self.assertEqual(Path(rows["source-01.mp4"]["path"]), untouched)
        self.assertTrue(rows["source-01.mp4"]["reviewed_by_inbox"])


if __name__ == "__main__":
    unittest.main()
