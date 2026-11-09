"""Every run, kept in the library (243, Wave A1).

History and Home's Recent runs read a list inside settings.json capped at 30: the 31st run pushed out the
first, and a run cut off by a crash or by closing the app left nothing at all, because the only record
was written when the run finished. Now a run is written to the library when it is launched (by the one
place every run goes through, ``_launch_run``), closed when the process ends, and each feature writes its
own final outcome per recording when it knows it; a later correction updates the same run.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.command_builder import CommandSpec  # noqa: E402
from media_manglers_workbench.runner import FakeRunner  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: E402
from tests.test_workbench_review_media_inbox import _ready_resources  # noqa: E402

try:
    from media_manglers.core import recording_records  # noqa: E402
    from media_manglers.core.recording_records import Records  # noqa: E402
except ImportError:  # shown failing on the code before the library kept runs
    recording_records = None  # type: ignore[assignment]
    Records = None  # type: ignore[assignment]


class Listener:
    def __init__(self) -> None:
        self.results: list[object] = []

    def on_log_line(self, _stream: str, _line: str) -> None:
        return None

    def on_finished(self, result: object) -> None:
        self.results.append(result)


class RecordsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="run-records-"))
        self.records = Records(self.root / "library")
        self.addCleanup(self.records.close)
        self.recording = self.root / "race.mkv"
        self.recording.write_bytes(b"recording bytes")

    def test_a_library_whose_session_lock_fails_is_closed_again(self) -> None:
        # 224 (Wave B2a, note 3): the library was opened before the session lock and left open when the lock
        # step failed, so the app itself kept the file open (which the antivirus-safe moves treat as a fault).
        opened: list[sqlite3.Connection] = []
        real_connect = recording_records.connect

        def connect(root: Path) -> sqlite3.Connection:
            opened.append(real_connect(root))
            return opened[-1]

        other = self.root / "other-library"
        with mock.patch.object(recording_records, "connect", side_effect=connect), \
                mock.patch.object(recording_records, "_lock_now", side_effect=OSError(33, "lock refused")):
            with self.assertRaises(OSError):
                Records(other)
        self.assertEqual(len(opened), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            opened[0].execute("SELECT 1")
        self.assertEqual(list((other / recording_records.SESSIONS).glob("*.lock")), [],
                         "the session file is let go and removed too")

    def test_a_run_is_written_before_it_starts_with_each_recording_noted(self) -> None:
        missing = self.root / "not-there.mkv"
        run_id = self.records.open_run(kind="bug_reports", title="Find my bug reports", origin="Bugs",
                                       items=[str(self.recording), str(missing)])
        run = self.records.get_run(run_id)
        self.assertEqual(run["process_status"], "running")
        items = self.records.run_items(run_id)
        self.assertEqual([item["path"] for item in items], [str(self.recording), str(missing)])
        self.assertEqual(items[0]["size_bytes"], self.recording.stat().st_size)
        self.assertEqual(items[0]["modified_ns"], self.recording.stat().st_mtime_ns)
        self.assertIsNone(items[1]["size_bytes"])
        self.assertEqual({item["outcome"] for item in items}, {"not_reported"})
        self.assertEqual(self.records.list_runs(), [], "a run still going is not History yet")

    def test_history_entries_keep_the_shape_history_always_read(self) -> None:
        run_id = self.records.open_run(kind="full_review", title="Full Review", workflow="1", profile="Mine",
                                       source=str(self.recording), output=str(self.root / "out"),
                                       log=str(self.root / "run.log"), items=[str(self.recording)])
        self.records.end_run(run_id, process_status="succeeded", exit_code=0)
        entry = self.records.list_runs()[0]
        self.assertEqual({key: entry[key] for key in ("workflow", "workflow_title", "profile", "source", "output",
                                                      "log", "status")},
                         {"workflow": "1", "workflow_title": "Full Review", "profile": "Mine",
                          "source": str(self.recording), "output": str(self.root / "out"),
                          "log": str(self.root / "run.log"), "status": "succeeded"})
        self.assertRegex(entry["timestamp"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")

    def test_the_usual_history_words_stay_the_same(self) -> None:
        cases = [("succeeded", 0, False, "succeeded"), ("failed", 1, False, "failed"),
                 ("cancelled", None, False, "cancelled"), ("failed", 2, True, "completed with problems")]
        for process, code, partial, word in cases:
            with self.subTest(process=process, partial=partial):
                run_id = self.records.open_run(kind="full_review", title=f"{process}-{partial}")
                self.records.end_run(run_id, process_status=process, exit_code=code, partial=partial)
                self.assertEqual(self.records.get_history_entry(run_id)["status"], word)

    def test_outcomes_written_twice_change_nothing_and_a_later_one_corrects(self) -> None:
        run_id = self.records.open_run(kind="bug_reports", title="Bugs", items=[str(self.recording)])
        done = [{"item": str(self.recording), "outcome": "completed"}]
        self.records.record_outcomes(run_id, done, reported_by="bugs page")
        self.records.record_outcomes(run_id, done, reported_by="bugs page")
        self.assertEqual(len(self.records.run_items(run_id)), 1)
        self.records.record_outcomes(run_id, [{"item": str(self.recording), "outcome": "no_narration"}],
                                     reported_by="bugs page")
        item = self.records.run_items(run_id)[0]
        self.assertEqual((item["outcome"], item["reported_by"]), ("no_narration", "bugs page"))

    def test_a_late_correction_updates_the_same_run_and_keeps_the_earlier_status(self) -> None:
        run_id = self.records.open_run(kind="bug_reports", title="Bugs")
        self.records.end_run(run_id, process_status="failed", exit_code=1)
        self.records.finish_run(run_id, "completed", headline="2 tickets", reported_by="bugs page")
        self.records.finish_run(run_id, "completed", headline="2 tickets", reported_by="bugs page")
        run = self.records.get_run(run_id)
        self.assertEqual((run["state"], run["state_source"]), ("completed", "bugs page"))
        self.assertEqual(self.records.get_history_entry(run_id)["status"], "completed")
        self.assertEqual([(event["old_state"], event["new_state"]) for event in self.records.run_events(run_id)],
                         [("failed", "completed")])
        self.assertEqual(len(self.records.list_runs()), 1)

    def test_a_run_left_running_by_a_closed_app_becomes_interrupted(self) -> None:
        run_id = self.records.open_run(kind="full_review", title="Cut off")
        self.records.close()  # the app is gone; its run never ended
        again = Records(self.root / "library")
        self.addCleanup(again.close)
        self.assertEqual(again.sweep_interrupted(), 1)
        self.assertEqual(again.get_run(run_id)["state"], "interrupted")
        self.assertEqual(again.list_runs()[0]["status"], "interrupted")

    def test_another_open_workbenchs_run_is_left_alone(self) -> None:
        other = Records(self.root / "library")
        self.addCleanup(other.close)
        run_id = other.open_run(kind="full_review", title="Still going elsewhere")
        self.assertEqual(self.records.sweep_interrupted(), 0)
        self.assertEqual(self.records.get_run(run_id)["process_status"], "running")

    def test_history_is_newest_first_and_comes_in_pages(self) -> None:
        for number in range(1, 36):
            run_id = self.records.open_run(kind="full_review", title=f"Run {number}")
            self.records.end_run(run_id, process_status="succeeded", exit_code=0)
        self.assertEqual(self.records.count_runs(), 35)
        first_page = self.records.list_runs(limit=30)
        self.assertEqual(first_page[0]["workflow_title"], "Run 35")
        self.assertEqual(self.records.list_runs(limit=30, offset=30)[-1]["workflow_title"], "Run 1")


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="run-records-window-"))
        self.settings_path = self.root / "settings.json"
        self.settings_path.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
            "log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
            "output_folder": str(self.root / "output")}}), encoding="utf-8")
        self.window: WorkbenchWindow | None = None

    def tearDown(self) -> None:
        if self.window is not None:
            # A run still going would ask whether to cancel it; let it end, and close without asking.
            self._wait(lambda: self.window.runner_thread is None, 15.0)
            self.window._closing_after_smoke = True
            self.window.close()
            self.window.deleteLater()
            self.app.processEvents()

    def _wait(self, condition, seconds: float = 10.0) -> bool:
        deadline = time.monotonic() + seconds
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        return condition()

    def _open(self, runner=FakeRunner) -> WorkbenchWindow:
        self.window = WorkbenchWindow(settings_path=self.settings_path, profiles_dir=self.root / "profiles",
                                      runner_factory=runner, resources=_ready_resources())
        return self.window

    def _run(self, window: WorkbenchWindow, title: str) -> Listener:
        listener = Listener()
        started = window.start_external_run(CommandSpec(argv=["fake"], preview="fake"), title=title,
                                            settings=dict(window.app_settings), queue_items=[str(self.root / "a.mkv")],
                                            listener=listener, evidence_package=False)
        self.assertTrue(started)
        self.assertTrue(self._wait(lambda: window.runner_thread is None and bool(listener.results)))
        return listener

    def test_a_31st_run_does_not_push_out_the_first(self) -> None:
        window = self._open()
        for number in range(1, 32):
            self._run(window, f"Run {number}")
        window.refresh_history()
        shown = [window.history_list.item(row).text() for row in range(window.history_list.count())]
        self.assertEqual(len(shown), 31)
        self.assertIn("Run 31", shown[0])
        self.assertIn("Run 1", shown[-1])
        self.assertEqual(window.home_recent_list.count(), 5)

    def test_settings_json_holds_no_run_history_after_a_run(self) -> None:
        window = self._open()
        self._run(window, "One run")
        window.save_app_settings()
        saved = json.loads(self.settings_path.read_text(encoding="utf-8"))["settings"]
        self.assertFalse(saved.get("recent_runs"), "run history stays out of settings.json")
        self.assertEqual(window.history_list.item(0).text().split("  |  ")[1], "One run")

    def test_a_run_ending_after_the_window_closed_is_never_written_into_settings_and_shows_once(self) -> None:
        # Closing mid-run cancels the run; its end can arrive after the window has closed its library.
        held = lambda: FakeRunner(stdout=[f"line {number}" for number in range(40)], delay_seconds=0.25)  # noqa: E731
        window = self._open(held)
        listener = Listener()
        window.start_external_run(CommandSpec(argv=["fake"], preview="fake"), title="Cut off", settings=dict(window.app_settings),
                                  queue_items=[str(self.root / "a.mkv")], listener=listener, evidence_package=False)
        with mock.patch("media_manglers_workbench.app.QMessageBox.question",
                        return_value=QMessageBox.StandardButton.Yes):
            window.close()
        self.assertTrue(self._wait(lambda: bool(listener.results)), "the run's end arrives after the close")
        self.window = None
        saved = json.loads(self.settings_path.read_text(encoding="utf-8"))["settings"]
        self.assertNotIn("recent_runs", saved)
        again = self._open()
        titles = [again.history_list.item(row).text() for row in range(again.history_list.count())]
        self.assertEqual(len(titles), 1, titles)
        self.assertIn("Cut off", titles[0])
        self.assertIn("interrupted", titles[0])

    def test_the_run_is_in_the_library_while_it_runs(self) -> None:
        held = lambda: FakeRunner(stdout=["working", "still working"], delay_seconds=0.4)  # noqa: E731
        window = self._open(held)
        listener = Listener()
        window.start_external_run(CommandSpec(argv=["fake"], preview="fake"), title="Held run",
                                  settings=dict(window.app_settings), queue_items=[str(self.root / "a.mkv")],
                                  listener=listener, evidence_package=False)
        library = Path(os.environ["MEDIA_MANGLERS_LIBRARY_ROOT"]) / "raw-bin-library.sqlite"
        connection = sqlite3.connect(f"{library.as_uri()}?mode=ro", uri=True)
        try:
            running = connection.execute("SELECT title FROM runs WHERE process_status = 'running'").fetchall()
        finally:
            connection.close()
        self.assertEqual(running, [("Held run",)])
        self.assertTrue(self._wait(lambda: window.runner_thread is None and bool(listener.results)))
        self.assertTrue(getattr(listener.results[0], "run_id", ""), "the page learns the run's own number")


if __name__ == "__main__":
    unittest.main()
