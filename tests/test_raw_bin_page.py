"""220: the raw bin library page, driven the way the operator drives it.

A real three-track recording is scanned into a library of the test's own, then the window is opened
on it: the list shows it with its guess, a click selects it, Keep and labels are saved and survive a
restart, Play opens the shared player at the first speech on the narration track, Scan starts the
library scan on the shared runner, Export writes what is on screen, and Settings refuse a cache
folder on the recordings drive and clear the cache without touching a tag.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from media_manglers.core import app_cache, raw_bin_library  # noqa: E402
from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.runner import FakeRunner  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: E402
from tests.qt_input import bring_to_front, double_click_row, row_point  # noqa: E402
from tests.test_raw_bin_library import FFMPEG, FFPROBE, HearingTranscriber, make_recording  # noqa: E402
from tests.test_workbench_bug_reports import _resources  # noqa: E402


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg is required")
class RawBinPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.raw = self.root / "raw"
        self.environment = mock.patch.dict(os.environ, {
            raw_bin_library.LIBRARY_ROOT_ENV: str(self.root / "library"),
            app_cache.CACHE_ROOT_ENV: str(self.root / "cache"),
        })
        self.environment.start()
        self.recording = make_recording(self.raw / "session.mkv")
        raw_bin_library.scan(raw_bin_library.ScanOptions(
            folders=[str(self.raw)], ffmpeg=FFMPEG, ffprobe=FFPROBE, transcriber=HearingTranscriber({2}),
            stable_after_seconds=0))
        self.window: WorkbenchWindow | None = None

    def tearDown(self) -> None:
        if self.window is not None:
            self.window._closing_after_smoke = True
            self.window.close()
        self.app.processEvents()
        self.environment.stop()
        self.temp.cleanup()

    def _window(self) -> WorkbenchWindow:
        settings_path = self.root / "settings.json"
        if not settings_path.exists():
            settings_path.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
                "log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
                "output_folder": str(self.root / "out"), "review_source_folders": str(self.raw)}}), encoding="utf-8")
        if self.window is not None:
            self.window._closing_after_smoke = True
            self.window.close()
        self.window = WorkbenchWindow(settings_path=settings_path, profiles_dir=self.root / "profiles",
                                      runner_factory=FakeRunner, resources=_resources())
        self.window.resize(1400, 900)
        self.window.show()
        self.app.processEvents()
        QTest.mouseClick(self.window.nav_buttons["Raw Bin"], Qt.MouseButton.LeftButton)
        self.app.processEvents()
        return self.window

    def _click_row(self, page, row: int = 0) -> None:
        index = page.table.model().index(row, 0)
        QTest.mouseClick(page.table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         row_point(page.table, index))
        self.app.processEvents()

    def test_the_list_shows_every_recording_with_its_guess_without_reading_it(self) -> None:
        window = self._window()
        page = window.raw_bin_page
        self.assertIs(window.page_stack.currentWidget(), page)
        self.assertEqual(page.table.rowCount(), 1)
        self.assertEqual(page.table.item(0, 0).text(), "session.mkv")
        self.assertEqual(page.table.item(0, 1).text(), "Keep likely")
        self.assertIn("1 recordings", page.summary.text())

    def test_idle_time_estimated_from_the_full_mix_says_so(self) -> None:
        # 220: the game track is silent the whole recording, so idle time comes from the full mix.
        shutil.rmtree(self.raw)
        make_recording(self.raw / "early.mkv", game_silent=True)
        summary = raw_bin_library.scan(raw_bin_library.ScanOptions(
            folders=[str(self.raw)], ffmpeg=FFMPEG, ffprobe=FFPROBE, transcriber=HearingTranscriber({2}),
            stable_after_seconds=0))
        self.assertEqual(summary["failed"], 0, summary["errors"])
        page = self._window().raw_bin_page
        row = next(index for index in range(page.table.rowCount()) if page.table.item(index, 0).text() == "early.mkv")
        stored = next(item for item in page.rows if str(item.get("path") or "").endswith("early.mkv"))
        idle = page.table.item(row, 3)
        self.assertTrue(idle.text().endswith("(estimated)"),
                        (idle.text(), stored.get("idle_status"), stored.get("idle_reason"), stored.get("guess_reason")))
        self.assertIn("full mix (Track 1)", idle.toolTip())
        # The GUI run (220): the column was too narrow and "(estimated)" showed as "0% ...".
        widest = page.table.fontMetrics().horizontalAdvance("100% (estimated)")
        self.assertGreater(page.table.columnWidth(3), widest)
        self._click_row(page, row)
        self.assertIn("Idle time estimated from the full mix (Track 1): Track 3, your game audio, is silent",
                      page.detail.text())

    def test_a_decision_and_a_label_are_kept_across_a_restart(self) -> None:
        page = self._window().raw_bin_page
        self._click_row(page)
        QTest.mouseClick(page.decision_buttons[raw_bin_library.DECISION_KEEP], Qt.MouseButton.LeftButton)
        page._fill_labels_menu()
        youtube = next(action for action in page.labels_menu.actions() if action.text() == "YouTube")
        youtube.trigger()
        page = self._window().raw_bin_page
        self.assertEqual(page.table.item(0, 4).text(), "Keep")
        self.assertEqual(page.table.item(0, 5).text(), "YouTube")

    def test_play_opens_the_shared_player_at_the_first_speech_on_the_narration_track(self) -> None:
        window = self._window()
        page = window.raw_bin_page
        with mock.patch.object(window.video_opener, "open", return_value=True) as opened:
            double_click_row(page.table, page.table.model().index(0, 0))
        target = opened.call_args.args[0]
        self.assertEqual(target.path, self.recording)
        self.assertEqual(target.hear_track, 2)
        self.assertEqual(target.stretch_kind, "speech")
        self.assertTrue(target.stretches)
        self.assertEqual(target.start_seconds, target.stretches[0][0])
        self.assertIsNotNone(target.levels_path, "the waveform strip has the scan's levels")

    def test_a_recording_no_longer_where_the_scan_found_it_gets_none_of_its_levels(self) -> None:
        # 125 Part 2 (Wave 8): the scan's levels count only while the library's row is still this file.
        from media_manglers_workbench.raw_bin_page import raw_bin_levels_path

        self.assertIsNotNone(raw_bin_levels_path(self.recording))
        connection = raw_bin_library.connect(self.root / "library")
        try:
            connection.execute("UPDATE locations SET missing = 1")
            connection.commit()
        finally:
            connection.close()
        self.assertIsNone(raw_bin_levels_path(self.recording))

    def test_scan_starts_on_the_shared_runner_with_the_recordings_folder(self) -> None:
        window = self._window()
        page = window.raw_bin_page
        with mock.patch.object(window, "start_external_run", return_value=True) as started:
            QTest.mouseClick(page.scan_button, Qt.MouseButton.LeftButton)
        command = started.call_args.args[0]
        self.assertIn("raw-bin-scan", command.argv)
        request = Path(command.argv[command.argv.index("--request-file") + 1])
        payload = json.loads(request.read_text(encoding="utf-8"))["payload"]
        self.assertEqual(payload["folders"], [str(self.raw)])
        self.assertTrue(payload["run_control_path"])
        self.assertNotIn(str(self.raw).lower(), str(request).lower(), "nothing is written in the recordings folder")

    def test_export_writes_what_is_on_screen_and_never_onto_the_recordings_drive(self) -> None:
        page = self._window().raw_bin_page
        written = page.export_to(self.root / "exports" / "view.json")
        rows = json.loads(written.read_text(encoding="utf-8"))
        self.assertEqual([row["name"] for row in rows], ["session.mkv"])
        with mock.patch("media_manglers_workbench.raw_bin_page.QMessageBox.information") as refused:
            self.assertIsNone(page.export_to(self.raw / "view.csv"))
        self.assertIn("read-only", refused.call_args.args[2])
        self.assertFalse((self.raw / "view.csv").exists())

    def test_settings_refuse_a_cache_on_the_recordings_drive_and_clear_cache_keeps_tags(self) -> None:
        window = self._window()
        raw_bin_library.set_decision(window.raw_bin_page.connection(), [1], raw_bin_library.DECISION_DELETE)
        bring_to_front(window.settings_cache_folder_edit)
        window.settings_cache_folder_edit.setText(str(self.raw / "cache"))
        # 237: the refusal is said beside Save settings and stays until dismissed.
        with mock.patch("media_manglers_workbench.app.QMessageBox.information") as told:
            outcome = window.save_settings_from_page()
        told.assert_not_called()
        self.assertEqual(outcome.kind, "failed")
        self.assertIn("read-only", outcome.text)
        self.assertNotEqual(window.app_settings.get("cache_folder"), str(self.raw / "cache"))

        cache = app_cache.default_cache_root()
        self.assertGreater(app_cache.size_bytes(cache), 0, "the scan cached its levels")
        with mock.patch("media_manglers_workbench.app.QMessageBox.question",
                        return_value=QMessageBox.StandardButton.Yes), \
                mock.patch("media_manglers_workbench.app.QMessageBox.information"):
            QTest.mouseClick(window.settings_clear_cache_button, Qt.MouseButton.LeftButton)
        self.assertEqual(app_cache.size_bytes(cache), 0)
        rows = raw_bin_library.list_recordings(window.raw_bin_page.connection())
        self.assertEqual(rows[0]["decision"], raw_bin_library.DECISION_DELETE)
        self.assertEqual(rows[0]["guess"], raw_bin_library.GUESS_KEEP, "guesses are not in the cache")


if __name__ == "__main__":
    unittest.main()
