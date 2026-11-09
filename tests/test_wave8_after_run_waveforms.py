"""135 (Wave 8): the waveforms are built after a Find my bug reports run, before anyone opens them.

The run is clicked on the real page with the scripted backend; the waveforms are then measured by the
real ``track-levels`` helper, as its own process, from generated recordings. Starting another run
stops the build (what it measured is kept), and no build starts while that run is going.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from media_manglers.core import app_cache, raw_bin_library, track_levels  # noqa: E402
from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.bug_reports import PAGE_NAME as BUG_REPORTS_PAGE, RecordingRow, RunSummary  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: E402
from tests.test_wave8_track_levels import FFMPEG, FFPROBE, NOISE, TONE_10_TO_20, make_tracks  # noqa: E402
from tests.test_workbench_bug_reports import ScriptedBackend, _resources  # noqa: E402
from tests.wave8_helpers import CountingLevelsRunner, helper_resources  # noqa: E402


class HeldBackend(ScriptedBackend):
    """The scripted backend, held until the test lets the run finish."""

    release = threading.Event()

    def run(self, command, on_log=None, *, cwd=None):
        HeldBackend.release.wait(60)
        return super().run(command, on_log, cwd=cwd)


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg is required")
class AfterRunWaveformsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cache = self.root / "cache"
        self.environment = mock.patch.dict(os.environ, {
            raw_bin_library.LIBRARY_ROOT_ENV: str(self.root / "library"),
            app_cache.CACHE_ROOT_ENV: str(self.cache),
        })
        self.environment.start()
        self.recordings = self.root / "recordings"
        ScriptedBackend.instances = []
        ScriptedBackend.write_package = True
        ScriptedBackend.exit_code = 0
        ScriptedBackend.lines = []
        HeldBackend.release.set()
        CountingLevelsRunner.runs = []
        self.window: WorkbenchWindow | None = None

    def tearDown(self) -> None:
        HeldBackend.release.set()
        if self.window is not None:
            self.window._closing_after_smoke = True
            self.window.close()
        self.app.processEvents()
        self.environment.stop()
        self.temp.cleanup()

    def _window(self) -> WorkbenchWindow:
        settings_path = self.root / "settings.json"
        settings_path.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
            "log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
            "output_folder": str(self.root / "out")}}), encoding="utf-8")
        self.window = WorkbenchWindow(settings_path=settings_path, profiles_dir=self.root / "profiles",
                                      runner_factory=HeldBackend, levels_runner_factory=CountingLevelsRunner,
                                      resources=helper_resources(_resources(), FFMPEG, FFPROBE))
        self.window.resize(1400, 900)
        self.window.show()
        self.app.processEvents()
        return self.window

    def _wait(self, condition, seconds: float = 90.0) -> None:
        deadline = time.monotonic() + seconds
        while not condition() and time.monotonic() < deadline:
            QTest.qWait(25)
        self.assertTrue(condition(), "waited too long")

    def _run(self, window, paths) -> None:
        page = window.bug_reports_page
        QTest.mouseClick(window.nav_buttons[BUG_REPORTS_PAGE], Qt.MouseButton.LeftButton)
        page.add_recordings(paths)
        QTest.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
        self.app.processEvents()

    def _complete(self, path: Path) -> bool:
        levels = track_levels.cached_levels(path, cache=self.cache)
        return levels is not None and levels.complete

    def test_after_the_run_the_waveforms_are_ready_without_the_player_being_opened(self) -> None:
        recordings = [make_tracks(self.recordings / name, [NOISE, TONE_10_TO_20], 90) for name in ("a.mkv", "b.mkv")]
        window = self._window()
        page = window.bug_reports_page
        self._run(window, recordings)
        self._wait(lambda: not page.running and window.runner_thread is None, 20)
        self._wait(lambda: page.waveforms_label.text() == "Waveforms ready for 2 of 2 recordings.")
        self.assertTrue(page.waveforms_label.isVisible())
        self.assertTrue(all(self._complete(path) for path in recordings))
        self.assertIsNone(window.video_opener.player_window, "the player was never opened")
        self.assertEqual(len(CountingLevelsRunner.runs), 2, "one build at a time, one per recording")

    def test_a_new_run_stops_the_build_which_keeps_its_part_and_none_starts_while_it_runs(self) -> None:
        recordings = [make_tracks(self.recordings / name, [NOISE, TONE_10_TO_20], 1800) for name in ("a.mkv", "b.mkv")]
        window = self._window()
        page = window.bug_reports_page
        service = window.levels_service
        self._run(window, recordings)
        self._wait(lambda: not page.running and window.runner_thread is None, 20)
        self._wait(lambda: service._building is not None
                   and (service.levels_for(service._paths[service._building]) or track_levels.Levels()).seconds > 0)
        building = service._paths[service._building]

        HeldBackend.release.clear()
        page.start_over()
        self._run(window, recordings)
        self.assertIsNotNone(window.runner_thread, "the second run is going")
        self._wait(lambda: service._build is None, 15)
        partial = track_levels.cached_levels(building, cache=self.cache)
        self.assertIsNotNone(partial, "what was measured is kept")
        self.assertFalse(partial.complete)
        runs = len(CountingLevelsRunner.runs)
        QTest.qWait(1500)
        self.assertEqual(len(CountingLevelsRunner.runs), runs, "no build starts while a run is going")

        HeldBackend.release.set()
        self._wait(lambda: window.runner_thread is None, 20)
        self._wait(lambda: all(self._complete(path) for path in recordings), 120)

    def test_measuring_waits_for_the_windows_readiness_check(self) -> None:
        window = self._window()
        service = window.levels_service
        checking = window.dependency_check_thread
        try:
            window.dependency_check_thread = object()
            self.assertFalse(service._tools_ready(), "a readiness check is going")
            window.dependency_check_thread = None
            self.assertTrue(service._tools_ready())
        finally:
            window.dependency_check_thread = checking

    def test_a_late_word_from_an_earlier_runs_build_leaves_the_results_line_alone(self) -> None:
        # The levels job tells each run's listener as its recordings are measured; an earlier run's
        # recordings can finish after a later run's results are on screen.
        listeners: list = []

        class Service:
            enabled = True

            def queue(self, paths, listener=None) -> None:
                listeners.append(listener)

        window = self._window()
        page = window.bug_reports_page
        real, window.levels_service = window.levels_service, Service()
        try:
            page.rows = [RecordingRow(path=self.root / "a.mkv"), RecordingRow(path=self.root / "b.mkv")]
            page._build_waveforms(RunSummary(status="completed", package_root=None))
            page.rows = [RecordingRow(path=self.root / "c.mkv")]
            page._build_waveforms(RunSummary(status="completed", package_root=None))
            listeners[1].on_waveforms(1, 1, False)
            self.assertEqual(page.waveforms_label.text(), "Waveforms ready for 1 of 1 recording.")
            listeners[0].on_waveforms(1, 2, True)
            self.assertEqual(page.waveforms_label.text(), "Waveforms ready for 1 of 1 recording.")
        finally:
            window.levels_service = real

    def test_an_earlier_runs_waveforms_never_take_over_the_line_of_the_run_after_it(self) -> None:
        earlier = [make_tracks(self.recordings / name, [NOISE, TONE_10_TO_20], 1800) for name in ("a.mkv", "b.mkv")]
        later = make_tracks(self.recordings / "c.mkv", [NOISE], 30)
        window = self._window()
        page = window.bug_reports_page
        service = window.levels_service
        self._run(window, earlier)
        self._wait(lambda: not page.running and window.runner_thread is None, 20)
        self._wait(lambda: service._building is not None)
        QTest.mouseClick(page.again_button, Qt.MouseButton.LeftButton)
        self._run(window, [later])
        shown: list[str] = []

        def everything_measured() -> bool:
            shown.append(page.waveforms_label.text())
            return all(self._complete(path) for path in [*earlier, later]) and service._build is None

        self._wait(everything_measured, 180)
        QTest.qWait(500)
        shown.append(page.waveforms_label.text())
        self.assertFalse([text for text in shown if "of 2" in text], "the line spoke of the run before")
        self.assertEqual(page.waveforms_label.text(), "Waveforms ready for 1 of 1 recording.")


if __name__ == "__main__":
    unittest.main()
