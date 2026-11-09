"""Find my bug reports: skip, pause, continue and the never-use list (114, 115)."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_workbench_bug_reports as base  # noqa: E402
from media_manglers_workbench.bug_reports import ROW_SKIPPED, ROW_SKIPPING, ROW_WAITING  # noqa: E402
from media_manglers_workbench.run_control import RunControl  # noqa: E402
from media_manglers_workbench.runner import RunnerResult  # noqa: E402


class StoppedBackend(base.ScriptedBackend):
    """The operator pressed Stop part-way through."""

    def run(self, command, on_log=None, *, cwd=None) -> RunnerResult:
        self.argv = list(command.argv)
        return RunnerResult(status="cancelled", exit_code=1, stdout_lines=[], error="")


class _Runner:
    def cancel(self) -> None:
        return None


class BugReportsControlTests(unittest.TestCase):
    setUpClass = classmethod(base.BugReportsPageTests.setUpClass.__func__)
    setUp = base.BugReportsPageTests.setUp
    tearDown = base.BugReportsPageTests.tearDown
    _window = base.BugReportsPageTests._window
    _wait_for_results = base.BugReportsPageTests._wait_for_results

    def _pretend_running(self, window, page) -> RunControl:
        page.add_recordings([self.recordings / "a.mkv", self.recordings / "b.mkv"])
        page.run_folder = self.root / "run"
        page.running = True
        for row in page.rows:
            row.state = ROW_WAITING
        page._render_working_table()
        page.stack.setCurrentIndex(1)
        window.runner_thread = _Runner()
        window.external_run = {
            "listener": page,
            "settings": {},
            "queue_items": [str(row.path) for row in page.rows],
        }
        window.run_control = RunControl.for_folder(page.run_folder)
        return window.run_control

    def test_skip_and_pause_reach_the_backend(self) -> None:
        window = self._window()
        page = window.bug_reports_page
        control = self._pretend_running(window, page)
        try:
            page.working_table.selectRow(1)
            page.skip_selected()
            payload = json.loads(control.path.read_text(encoding="utf-8"))
            self.assertEqual(payload["skip"], [str(page.rows[1].path)])
            self.assertEqual(page.rows[1].state, ROW_SKIPPING)
            self.assertEqual(page.rows[0].state, ROW_WAITING)

            page.toggle_pause()
            self.assertTrue(json.loads(control.path.read_text(encoding="utf-8"))["pause"])
            self.assertEqual(page.pause_button.text(), "Resume")
            self.assertEqual(window.pause_button.text(), "Resume")
            self.assertIn("Paused", page.status_sentence.text())
            window.toggle_run_pause()
            self.assertFalse(json.loads(control.path.read_text(encoding="utf-8"))["pause"])
            self.assertEqual(page.pause_button.text(), "Pause")

            # Skipping from Queue / Progress works the same way.
            window._initialize_progress_queue([str(row.path) for row in page.rows])
            window.skip_run_sources([str(page.rows[0].path)])
            self.assertEqual(len(json.loads(control.path.read_text(encoding="utf-8"))["skip"]), 2)
            self.assertEqual(window.progress_item_states[str(page.rows[0].path)], "skipped")
        finally:
            window.runner_thread = None
            window.run_control = None
            page.running = False

    def test_run_passes_control_file_and_shows_operator_skips(self) -> None:
        window = self._window()
        page = window.bug_reports_page
        page.add_recordings([self.recordings / "a.mkv", self.recordings / "b.mkv"])
        base.ScriptedBackend.lines = [
            base.OUTCOME % ("a.mkv", "skipped", "true", "operator_skipped", "a.mkv"),
            "SKIPPED by you: a.mkv",
            base.PROGRESS % ("b.mkv", "Transcription completed: b.mkv"),
        ]
        page.start()
        self._wait_for_results(page)
        argv = base.ScriptedBackend.instances[-1].argv
        self.assertEqual(Path(argv[argv.index("-RunControlPath") + 1]), page.run_folder / "run-control.json")
        self.assertIn("-LowPriority", argv)
        self.assertEqual(page.rows[0].state, ROW_SKIPPED)
        self.assertIn("a.mkv: skipped by you", page.results_detail.text())

    def test_stopped_run_continues_into_the_same_package(self) -> None:
        window = self._window()
        window.runner_factory = StoppedBackend
        page = window.bug_reports_page
        page.add_recordings([self.recordings / "a.mkv", self.recordings / "b.mkv"])
        page.start()
        first_folder = page.run_folder
        first_folder.mkdir(parents=True, exist_ok=True)
        self._wait_for_results(page)
        self.assertEqual(page.stack.currentIndex(), 0)
        self.assertEqual(page.continue_folder, first_folder)
        self.assertEqual(page.start_button.text(), "Continue")
        # 244: the stopped run is kept in the library, not in the settings.
        self.assertEqual(window.records.stopped_bug_run()["folder"], str(first_folder))
        self.assertNotIn("bug_report_stopped_run", window.app_settings)

        window.runner_factory = base.ScriptedBackend
        page.start()
        self._wait_for_results(page)
        argv = base.ScriptedBackend.instances[-1].argv
        self.assertEqual(Path(argv[argv.index("-OutputFolder") + 1]), first_folder)
        self.assertIsNone(window.records.stopped_bug_run())
        self.assertIsNone(page.continue_folder)

    def test_never_use_list_and_done_recordings_are_left_out(self) -> None:
        window = self._window()
        page = window.bug_reports_page
        page.add_recordings([self.recordings / "a.mkv", self.recordings / "b.mkv"])
        page.table.selectRow(0)
        page.never_use_selected()
        self.assertEqual([row.path.name for row in page.rows], ["b.mkv"])
        # 244: the lists are kept in the library.
        self.assertEqual(len(window.records.never_use_entries()), 1)
        page.add_recordings([self.recordings / "a.mkv"])
        self.assertEqual([row.path.name for row in page.rows], ["b.mkv"])
        self.assertIn("never-use list", page.status_sentence.text())

        base.ScriptedBackend.lines = [base.PROGRESS % ("b.mkv", "Transcription completed: b.mkv")]
        page.start()
        self._wait_for_results(page)
        self.assertTrue(window.records.done_on(page.rows[0].path))

        page.start_over()
        page.newest_count.setValue(5)
        page.add_newest_recordings()
        self.assertEqual(page.rows, [], "done and never-use recordings are not offered again")
        page.include_done_check.setChecked(True)
        page.add_newest_recordings()
        self.assertEqual([row.path.name for row in page.rows], ["b.mkv"], "never-use still wins")


if __name__ == "__main__":
    unittest.main()
