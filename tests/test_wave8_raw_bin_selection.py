"""222: after a reload, the line under the Raw bin list always describes the highlighted row.

Three real recordings are scanned into a library of the test's own. The list is sorted by name with a
click on its header, so the order on screen differs from the library's own order; then a recording is
clicked and Scan now is pressed. The scan runs for real (on a scripted runner that calls the library
scan in the test process), the list reloads, and the highlighted row, the line under the list, Play
and the decision buttons must all still be about the recording that was clicked, or about nothing.
"""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from media_manglers.core import app_cache, raw_bin_library  # noqa: E402
from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.runner import RunnerResult  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: E402
from tests.qt_input import row_point  # noqa: E402
from tests.test_raw_bin_library import FFMPEG, FFPROBE, HearingTranscriber, make_recording  # noqa: E402
from tests.test_workbench_bug_reports import _resources  # noqa: E402


class LibraryScanRunner:
    """Runs the real library scan the page asked for, in this process, with a transcriber that hears."""

    def cancel(self) -> None:
        return None

    def run(self, command, on_log=None, **_kwargs) -> RunnerResult:
        argv = list(command.argv)
        request = Path(argv[argv.index("--request-file") + 1])
        result = Path(argv[argv.index("--result-file") + 1])
        payload = json.loads(request.read_text(encoding="utf-8"))["payload"]
        options = dataclasses.replace(raw_bin_library._options_from(payload), transcriber=HearingTranscriber({2}),
                                      stable_after_seconds=0, report=None)
        data = raw_bin_library.scan(options)
        result.write_text(json.dumps({"ok": True, "data": data, "error": ""}), encoding="utf-8")
        return RunnerResult(status="succeeded", exit_code=0)


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg is required")
class RawBinSelectionAfterReloadTests(unittest.TestCase):
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
        # The library numbers recordings in the order it first meets them, so the first one scanned
        # alone ("middle") gets the first id and the name order differs from the library order.
        make_recording(self.raw / "middle.mkv", seconds=40)
        self._scan()
        make_recording(self.raw / "alpha.mkv", seconds=40)
        make_recording(self.raw / "zulu.mkv", seconds=40)
        self._scan()
        self.window: WorkbenchWindow | None = None

    def tearDown(self) -> None:
        if self.window is not None:
            self.window._closing_after_smoke = True
            self.window.close()
        self.app.processEvents()
        self.environment.stop()
        self.temp.cleanup()

    def _scan(self) -> None:
        summary = raw_bin_library.scan(raw_bin_library.ScanOptions(
            folders=[str(self.raw)], ffmpeg=FFMPEG, ffprobe=FFPROBE, transcriber=HearingTranscriber({2}),
            stable_after_seconds=0))
        self.assertEqual(summary["failed"], 0, summary["errors"])

    def _window(self) -> WorkbenchWindow:
        settings_path = self.root / "settings.json"
        settings_path.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
            "log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
            "output_folder": str(self.root / "out"), "review_source_folders": str(self.raw)}}), encoding="utf-8")
        self.window = WorkbenchWindow(settings_path=settings_path, profiles_dir=self.root / "profiles",
                                      runner_factory=LibraryScanRunner, resources=_resources())
        self.window.resize(1400, 900)
        self.window.show()
        self.app.processEvents()
        QTest.mouseClick(self.window.nav_buttons["Raw Bin"], Qt.MouseButton.LeftButton)
        self.app.processEvents()
        return self.window

    def _sort_by_name(self, page) -> None:
        header = page.table.horizontalHeader()
        x = header.sectionViewportPosition(0) + header.sectionSize(0) // 2
        QTest.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(x, header.height() // 2))
        self.app.processEvents()

    def _names(self, page) -> list[str]:
        return [page.table.item(row, 0).text() for row in range(page.table.rowCount())]

    def _click_name(self, page, name: str) -> None:
        row = self._names(page).index(name)
        index = page.table.model().index(row, 0)
        QTest.mouseClick(page.table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         row_point(page.table, index))
        self.app.processEvents()

    def _a_name_that_moves(self, page) -> str:
        """A recording whose place on screen differs from its place in the library's own order."""

        library_order = [Path(str(row.get("path"))).name for row in page.shown]
        on_screen = self._names(page)
        moved = [name for row, name in enumerate(on_screen) if library_order[row] != name]
        self.assertTrue(moved, (library_order, on_screen))
        return moved[0]

    def _press_scan_now(self, page) -> None:
        QTest.mouseClick(page.scan_button, Qt.MouseButton.LeftButton)
        deadline = time.monotonic() + 120
        while (self.window.runner_thread is not None or page.running) and time.monotonic() < deadline:
            QTest.qWait(50)
        self.assertIsNone(self.window.runner_thread, "the scan finished")
        self.app.processEvents()

    def _highlighted(self, page) -> list[str]:
        rows = page.table.selectionModel().selectedRows(0)
        return [page.table.item(index.row(), 0).text() for index in rows]

    def test_a_scan_keeps_the_highlight_and_the_line_under_the_list_on_the_clicked_recording(self) -> None:
        page = self._window().raw_bin_page
        self._sort_by_name(page)
        name = self._a_name_that_moves(page)
        self._click_name(page, name)
        self.assertTrue(page.detail.text().endswith(name), page.detail.text())

        self._press_scan_now(page)

        self.assertEqual(self._highlighted(page), [name])
        self.assertTrue(page.detail.text().endswith(name), page.detail.text())
        row = self._names(page).index(name)
        self.assertEqual(page.table.currentRow(), row)
        rect = page.table.visualRect(page.table.model().index(row, 0))
        self.assertTrue(page.table.viewport().rect().intersects(rect), "the highlighted row is on screen")

    def test_play_and_the_decisions_act_on_the_highlighted_recording_after_a_scan(self) -> None:
        window = self._window()
        page = window.raw_bin_page
        self._sort_by_name(page)
        name = self._a_name_that_moves(page)
        self._click_name(page, name)
        self._press_scan_now(page)

        with mock.patch.object(window.video_opener, "open", return_value=True) as opened:
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
        self.assertEqual(opened.call_args.args[0].path.name, name)

        QTest.mouseClick(page.decision_buttons[raw_bin_library.DECISION_KEEP], Qt.MouseButton.LeftButton)
        decided = {Path(str(row["path"])).name: row["decision"]
                   for row in raw_bin_library.list_recordings(page.connection())}
        self.assertEqual(decided[name], raw_bin_library.DECISION_KEEP)
        self.assertEqual([other for other, decision in decided.items() if decision == raw_bin_library.DECISION_KEEP],
                         [name], "only the highlighted recording is kept")
        self.assertEqual(self._highlighted(page), [name], "Keep leaves the same recording highlighted")

    def test_a_recording_no_longer_listed_after_a_scan_is_no_longer_selected(self) -> None:
        page = self._window().raw_bin_page
        self._sort_by_name(page)
        name = self._a_name_that_moves(page)
        self._click_name(page, name)
        (self.raw / name).unlink()

        self._press_scan_now(page)

        self.assertNotIn(name, self._names(page), "a missing recording is hidden while Show missing is off")
        self.assertEqual(self._highlighted(page), [])
        self.assertEqual(page.detail.text(), "")
        self.assertFalse(page.play_button.isEnabled())
        self.assertFalse(any(button.isEnabled() for button in page.decision_buttons.values()))

    def test_coming_back_to_the_raw_bin_keeps_the_selection(self) -> None:
        window = self._window()
        page = window.raw_bin_page
        self._sort_by_name(page)
        name = self._a_name_that_moves(page)
        self._click_name(page, name)
        QTest.mouseClick(window.nav_buttons["Queue / Progress"], Qt.MouseButton.LeftButton)
        self.app.processEvents()
        QTest.mouseClick(window.nav_buttons["Raw Bin"], Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertEqual(self._highlighted(page), [name])
        self.assertTrue(page.detail.text().endswith(name), page.detail.text())

    def test_a_search_keeps_or_clears_the_selection(self) -> None:
        page = self._window().raw_bin_page
        self._sort_by_name(page)
        name = self._a_name_that_moves(page)
        self._click_name(page, name)
        page.search_edit.setFocus()
        QTest.keyClicks(page.search_edit, name[:3])
        self.app.processEvents()
        self.assertEqual(self._highlighted(page), [name])
        QTest.keyClicks(page.search_edit, "no-such-recording")
        self.app.processEvents()
        self.assertEqual(self._highlighted(page), [])
        self.assertEqual(page.detail.text(), "")


if __name__ == "__main__":
    unittest.main()
