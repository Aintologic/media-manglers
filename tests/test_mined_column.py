"""The Raw bin says what mined each recording; Choose a recording says it in the same words (244, Wave A2.6).

The raw bin's "Inbox" column is now "Mined" (operator decision Q2): "Inbox", "Bugs", "Inbox + Bugs",
"Bugs: no narration", and "Bugs (old list)" for an old done entry the library could not tie to the
recording (Q3), matched by its path. A recording identical to a mined one shows as mined (decision E).
Recordings only Find my bug reports or the player marked, outside the watched folders, are not listed
(Q4). The export keeps exactly its columns, so what Find my bug reports did never leaves this PC. The AI
Video Editor's Choose a recording shows the same words (Q8).
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from media_manglers.core import raw_bin_library, recording_records  # noqa: E402
from media_manglers_workbench import ai_video_editor_parts  # noqa: E402
from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: E402
from tests.test_raw_bin_library import FFMPEG, FFPROBE, HearingTranscriber  # noqa: E402
from tests.test_recording_marks import store_copy, write_recording  # noqa: E402
from tests.test_workbench_review_media_inbox import _ready_resources  # noqa: E402
import pytest
from tests import inbox_library  # noqa: E402

# 224 (Wave B2b): the Inbox's records are in this test's library, moved in (nothing to move).
pytestmark = pytest.mark.inbox_moved

DONE = "bug_report_processed_recordings"


class MinedColumnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.raw = self.root / "raw"
        self.window: WorkbenchWindow | None = None

    def tearDown(self) -> None:
        if self.window is not None:
            self.window._closing_after_smoke = True
            self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def _window(self, settings: dict | None = None) -> WorkbenchWindow:
        settings_path = self.root / "settings.json"
        settings_path.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
            "log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
            "output_folder": str(self.root / "out"), "review_source_folders": str(self.raw), **(settings or {})}}),
            encoding="utf-8")
        self.window = WorkbenchWindow(settings_path=settings_path, profiles_dir=self.root / "profiles",
                                      resources=_ready_resources())
        self.window.resize(1400, 900)
        self.window.show()
        self.app.processEvents()
        return self.window

    def _open_raw_bin(self, window: WorkbenchWindow):
        QTest.mouseClick(window.nav_buttons["Raw Bin"], Qt.MouseButton.LeftButton)
        self.app.processEvents()
        page = window.raw_bin_page
        page.missing_check.setChecked(True)
        return page

    @staticmethod
    def _column(page, header: str) -> dict[str, tuple[str, str]]:
        headers = [page.table.horizontalHeaderItem(index).text() for index in range(page.table.columnCount())]
        column = headers.index(header)
        return {page.table.item(row, 0).text(): (page.table.item(row, column).text(),
                                                 page.table.item(row, column).toolTip())
                for row in range(page.table.rowCount())}

    def _library_with_every_kind(self) -> WorkbenchWindow:
        names = ("done.mkv", "quiet.mkv", "twin-of-done.mkv", "old-list.mkv", "untouched.mkv")
        paths = {name: write_recording(self.raw / name, seed=index + 1) for index, name in enumerate(names)}
        write_recording(paths["twin-of-done.mkv"], seed=1)  # the same bytes as done.mkv
        # An old "done" entry from before the library kept it, for a file the library first sees after it.
        window = self._window({DONE: {str(paths["old-list.mkv"]): "2026-01-02"}})
        for path in paths.values():
            store_copy(window.records, path, self.raw)
        window.records.mark_done("", [(paths["done.mkv"], "done"), (paths["quiet.mkv"], "no_narration")],
                                 by="Find Bug Reports", day="2026-10-20")
        # A recording a Bugs run used from outside the watched folders: kept off the list.
        window.records.mark_done("", [(write_recording(self.root / "elsewhere" / "outside.mkv", seed=9), "done")],
                                 by="Find Bug Reports", day="2026-10-20")
        return window

    def test_the_raw_bin_column_is_called_mined_and_says_what_mined_each_recording(self) -> None:
        window = self._library_with_every_kind()
        page = self._open_raw_bin(window)
        mined = self._column(page, "Mined")
        self.assertEqual({name: words for name, (words, _tip) in mined.items()}, {
            "done.mkv": "Bugs", "quiet.mkv": "Bugs: no narration", "twin-of-done.mkv": "Bugs",
            "old-list.mkv": "Bugs (old list)", "untouched.mkv": ""})
        self.assertIn("could not prove", mined["old-list.mkv"][1])
        self.assertNotIn("Inbox", [page.table.horizontalHeaderItem(i).text() for i in range(page.table.columnCount())])

    def test_the_export_keeps_its_columns_and_never_carries_what_bugs_did(self) -> None:
        window = self._library_with_every_kind()
        page = self._open_raw_bin(window)
        written = page.export_to(self.root / "out" / "raw-bin.csv")
        with open(written, encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(list(rows[0].keys()), raw_bin_library.EXPORT_FIELDS)
        self.assertEqual({row["reviewed_by_inbox"] for row in rows}, {"no"}, "the Inbox part only, as before")
        text = Path(written).read_text(encoding="utf-8-sig")
        for word in ("Bugs", "no narration", "old list", "mined"):
            self.assertNotIn(word, text)

    def test_choose_a_recording_shows_the_same_mined_words(self) -> None:
        window = self._library_with_every_kind()
        rows = ai_video_editor_parts.library_recordings()
        dialog = ai_video_editor_parts.ChooseRecordingDialog(rows, {})
        try:
            known = {dialog.table.item(row, 0).text(): dialog.table.item(row, 2).text()
                     for row in range(dialog.table.rowCount())}
        finally:
            dialog.deleteLater()
        self.assertIn("Mined: Bugs", known["done.mkv"])
        self.assertIn("Mined: Bugs: no narration", known["quiet.mkv"])
        self.assertIn("Mined: Bugs", known["twin-of-done.mkv"])
        self.assertIn("Mined: Bugs (old list)", known["old-list.mkv"])
        self.assertNotIn("Mined", known["untouched.mkv"])
        self.assertNotIn("outside.mkv", known, "outside the watched folders: not listed")
        self.assertIsNotNone(window.records)


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class InboxAndBugsTests(unittest.TestCase):
    """The Inbox's verdict comes from records the Inbox's own finalization finished (no findings), in the same
    library the raw bin scans into (224, Wave B2b)."""

    def setUp(self) -> None:
        from tests.test_review_inbox_finalization import ReviewInboxFinalizationTests  # noqa: PLC0415

        self.temp = tempfile.TemporaryDirectory()
        self.inbox = ReviewInboxFinalizationTests(methodName="runTest")
        self.inbox.setUp()
        self.addCleanup(self.inbox.tearDown)
        # The Inbox's records are in its own test library; the raw bin scans into that same library.
        self.library = recording_records.library_root()
        self.inbox._accept()
        self.assertEqual(self.inbox._finalize(self.inbox._preview())["status"], "finalized_no_findings")
        self.sources = Path(self.inbox.fixture.fixture.sources)
        result = raw_bin_library.scan(raw_bin_library.ScanOptions(
            folders=[str(self.sources)], ffmpeg=FFMPEG, ffprobe=FFPROBE, transcriber=HearingTranscriber({2}),
            library_root=str(self.library), cache_folder=str(Path(self.temp.name) / "cache"), stable_after_seconds=0))
        self.assertEqual(result["status"], "completed", result)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_a_recording_both_features_mined_says_both(self) -> None:
        records = recording_records.Records(self.library)
        try:
            records.mark_done("", [(self.sources / "source-00.mp4", "done")], by="Find Bug Reports", day="2026-10-20")
            mined = {Path(row["path"]).name: row["mined"] for row in records.list_recordings()}
        finally:
            records.close()
        self.assertEqual(mined["source-00.mp4"], "Inbox + Bugs")
        self.assertEqual(mined["source-01.mp4"], "Inbox")


if __name__ == "__main__":
    unittest.main()
