"""214: a run reports what it really did, whatever page the operator opens while it runs.

In a GUI test one recording went through Review Media Inbox's "Process new media", and
Queue / Progress then said 1372 items, all completed, listed "Queued item 2" to "Queued item 1372",
read "164 of 165 items complete", and gave the Full Review wizard's folder as the results location.

- The numbers were Whisper's own progress bars ("0/1372 frames", "165/165 frames"), which the
  Workbench read as the queue because the Inbox does not list its recordings before it starts.
- The run's folder, and whether it was an Inbox run, were read from what the pages showed when the
  run ended. New Review and the Inbox share those, and opening New Review during the run switched
  them to the wizard's.

Every run now reports from its own settings, taken when it started; for the Inbox that is the
folder its queue and batches are written to, which its result names.
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
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.main_settings import run_output_folder  # noqa: E402
from media_manglers_workbench.metadata import WORKFLOW_FULL_REVIEW, WORKFLOW_REVIEW_NEW_VIDEOS  # noqa: E402
from media_manglers_workbench.runner import RunnerResult  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: E402
from tests.qt_input import bring_to_front  # noqa: E402
from tests.test_workbench_review_media_inbox import _ready_resources, _status  # noqa: E402

RECORDING = "race.mkv"


def _progress(**fields: object) -> str:
    event = {
        "schema": "MM_PROGRESS_V1",
        "phase": "Transcribing",
        "progress_kind": "indeterminate",
        "source_name": RECORDING,
        "source_completed": 0,
        "source_total": 1,
        "source_ordinal": 1,
        "source_state": "active",
        "source_terminal": False,
        "activity": "Extracting confirmed narration audio and creating a local transcript",
        **fields,
    }
    return "MM_PROGRESS_V1 " + json.dumps(event)


# Whisper progress bars in the shape and order the Inbox's Whisper prints them.
WHISPER_BARS = [
    "  0%|          | 0/59 [00:00<?, ?frames/s]",
    "100%|\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588| 59/59 [00:01<00:00, 53.09frames/s]",
    "  0%|          | 0/1372 [00:00<?, ?frames/s]",
    "100%|\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588| 1372/1372 [00:01<00:00, 838.79frames/s]",
    "  0%|          | 0/165 [00:00<?, ?frames/s]",
    "100%|\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588| 165/165 [00:00<00:00, 444.00frames/s]",
]


class HeldInboxBackend:
    """Stands in for the Inbox's Process run: it starts, waits while the test uses other pages,
    then prints Whisper's bars and the Inbox's result."""

    instances: list["HeldInboxBackend"] = []
    queue_root = ""
    # The bars can also come before the Inbox's first progress line.
    bars_first = False

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        HeldInboxBackend.instances.append(self)

    def cancel(self) -> None:
        self.release.set()

    def run(self, command, on_log=None, *, cwd=None) -> RunnerResult:
        if self.bars_first:
            for line in WHISPER_BARS:
                on_log("stdout", line)
        on_log("stdout", _progress(phase="Validating source"))
        self.started.set()
        self.release.wait(30)
        for line in [] if self.bars_first else WHISPER_BARS:
            on_log("stdout", line)
        on_log("stdout", _progress(phase="Source prepared", source_state="completed", source_terminal=True,
                                   source_completed=1, prepared_count=1))
        contract = _status(operator_status="Ready for Codex review", queue_root=self.queue_root,
                           queue_prompt_path=str(Path(self.queue_root) / "CODEX_REVIEW_QUEUE_PROMPT.md"))
        contract["queue_counts"]["ready_for_codex_review"] = 1
        on_log("stdout", "MM_REVIEW_INBOX_PROCESS_RESULT_V1 " + json.dumps(contract))
        return RunnerResult(status="succeeded", exit_code=0, stdout_lines=[], error="")


class HeldFullReviewBackend:
    instances: list["HeldFullReviewBackend"] = []

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        HeldFullReviewBackend.instances.append(self)

    def cancel(self) -> None:
        self.release.set()

    def run(self, command, on_log=None, *, cwd=None) -> RunnerResult:
        self.started.set()
        self.release.wait(30)
        return RunnerResult(status="succeeded", exit_code=0, stdout_lines=[], error="")


class RunOutputFolderRuleTests(unittest.TestCase):
    def test_one_rule_for_every_feature(self) -> None:
        root = Path("C:/runs")
        settings = {"output_folder": str(root / "main"), "review_evidence_root": "",
                    "review_inbox_folder": str(root / "inbox")}
        self.assertEqual(run_output_folder(settings), str(root / "main"))
        self.assertEqual(run_output_folder({**settings, "review_inbox_action": "Process"}, inbox=True),
                         os.path.normpath(str(root / "inbox")))
        # 224 (F9): the command-line Prepare keeps its batches in the one Inbox folder too.
        self.assertEqual(run_output_folder({**settings, "review_inbox_action": "Prepare"}, inbox=True),
                         os.path.normpath(str(root / "inbox")))
        self.assertEqual(run_output_folder({**settings, "review_inbox_folder": "", "review_inbox_action": "Prepare"},
                                           inbox=True), os.path.join(str(root / "main"), "review-inbox"))
        self.assertEqual(
            run_output_folder({**settings, "review_inbox_action": "Process"}, inbox=True,
                              result={"queue_root": str(root / "queue")}),
            str(root / "queue"),
            "what the run says it wrote wins",
        )

    def test_a_blank_inbox_folder_uses_the_main_folder_from_settings_not_the_wizard(self) -> None:
        from media_manglers_workbench.main_settings import review_evidence_root

        settings = {"output_folder": "C:/runs/wizard-field", "main_output_folder": "C:/runs/main", "review_evidence_root": ""}
        self.assertEqual(review_evidence_root(settings), "C:/runs/main")


class RunReportsItsOwnFolderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window: WorkbenchWindow | None = None
        HeldInboxBackend.instances = []
        HeldFullReviewBackend.instances = []
        self.main_output = self.root / "main-output"
        self.inbox_root = self.root / "inbox"
        self.wizard_output = self.root / "wizard-output"
        for folder in (self.main_output, self.inbox_root, self.wizard_output):
            folder.mkdir()
        self.opened: list[str] = []

    def tearDown(self) -> None:
        for backend in [*HeldInboxBackend.instances, *HeldFullReviewBackend.instances]:
            backend.release.set()
        if self.window:
            self._wait(lambda: self.window.runner_thread is None)
            self.window._closing_after_smoke = True
            self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def _wait(self, condition, seconds: float = 10.0) -> bool:
        deadline = time.monotonic() + seconds
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(20)
        return condition()

    def _window(self, runner) -> WorkbenchWindow:
        settings_path = self.root / "settings.json"
        settings_path.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
            "log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
            "output_folder": str(self.main_output)}}), encoding="utf-8")
        self.window = WorkbenchWindow(settings_path=settings_path, profiles_dir=self.root / "profiles",
                                      runner_factory=runner, resources=_ready_resources(),
                                      review_inbox_reconciler=lambda _payload: _status())
        self.window._open_path = lambda path: (self.opened.append(str(path)), True)[1]
        self.window.show()
        self.app.processEvents()
        return self.window

    def _click(self, widget) -> None:
        bring_to_front(widget)
        self.assertTrue(widget.isEnabled(), f"{widget.text() if hasattr(widget, 'text') else widget} is not enabled")
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        self.app.processEvents()

    def _type_wizard_output(self, window: WorkbenchWindow, folder: Path) -> None:
        self._click(window.nav_buttons["New Review"])
        bring_to_front(window.output_path_edit)
        QTest.mouseClick(window.output_path_edit, Qt.MouseButton.LeftButton)
        QTest.keyClick(window.output_path_edit, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(window.output_path_edit, str(folder))
        self.app.processEvents()
        self.assertEqual(window.run_settings.get("output_folder"), str(folder), "the wizard took the folder")

    def _open_output(self, window: WorkbenchWindow) -> None:
        button = next(item for item in window.pages["Queue / Progress"].findChildren(QPushButton)
                      if item.text() == "Open output")
        self._click(button)

    def _start_inbox(self) -> tuple[WorkbenchWindow, HeldInboxBackend]:
        HeldInboxBackend.queue_root = str(self.inbox_root)
        window = self._window(HeldInboxBackend)
        sources = self.root / "recordings"
        sources.mkdir()
        (sources / RECORDING).write_bytes(b"x")
        window.run_settings.update({
            "review_source_folders": str(sources),
            "review_evidence_root": "",  # the main output folder
            "review_local_work_root": str(self.root / "work"),
            "review_inbox_folder": str(self.inbox_root),
            "review_dedupe_mode": "Fast",
        })
        window.set_current_workflow(WORKFLOW_REVIEW_NEW_VIDEOS)
        window.navigate("Review Media Inbox")
        self.assertTrue(self._wait(lambda: window.review_inbox_reconcile_thread is None))
        window._refresh_review_inbox_dashboard()
        self._click(window.review_inbox_process_button)
        self.assertTrue(self._wait(lambda: bool(HeldInboxBackend.instances) and HeldInboxBackend.instances[-1].started.is_set()),
                        "the Inbox run did not start")
        return window, HeldInboxBackend.instances[-1]

    def _assert_one_recording(self, window: WorkbenchWindow) -> None:
        rows = [window.progress_queue_items[row] for row in range(window.progress_queue_table.rowCount())]
        self.assertEqual(rows, [RECORDING], "one row: the recording, no 'Queued item' placeholders")
        self.assertEqual(window.progress_queue.text(), "1")
        self.assertEqual(window.progress_completed.text(), "1")
        self.assertEqual(window.progress_remaining.text(), "0")
        self.assertNotIn("165", window.overall_progress_bar.format())
        self.assertNotIn("1372", window.progress_completion_summary.text())

    def test_an_inbox_run_never_takes_new_reviews_input_box_as_its_recordings(self) -> None:
        # 243: the Inbox names its recordings in its own journal when it ends; New Review's input box,
        # left pointing at another folder, is not them.
        wizard = self.root / "wizard-recordings"
        wizard.mkdir()
        (wizard / "wizard-only.mkv").write_bytes(b"x")
        plain_window = self._window

        def window_with_a_box(runner):
            window = plain_window(runner)
            window.run_settings["input_path"] = str(wizard)
            return window

        self._window = window_with_a_box
        window, backend = self._start_inbox()
        backend.release.set()
        self.assertTrue(self._wait(lambda: window.runner_thread is None))
        run = window.recent_runs()[0]
        names = [Path(str(item["path"] or item["name"] or "")).name for item in window.records.run_items(run["run_id"])]
        self.assertNotIn("wizard-only.mkv", names)

    def test_whisper_progress_bars_are_not_the_queue(self) -> None:
        window, backend = self._start_inbox()
        backend.release.set()
        self.assertTrue(self._wait(lambda: window.runner_thread is None))
        self._assert_one_recording(window)
        self.assertEqual(window.review_inbox_operator_status.text(), "Ready for Codex review")

    def test_whisper_bars_before_any_progress_line_are_not_the_queue(self) -> None:
        HeldInboxBackend.bars_first = True
        try:
            window, backend = self._start_inbox()
            backend.release.set()
            self.assertTrue(self._wait(lambda: window.runner_thread is None))
        finally:
            HeldInboxBackend.bars_first = False
        self._assert_one_recording(window)

    def test_the_folder_the_inbox_says_it_wrote_wins(self) -> None:
        elsewhere = self.root / "queue-elsewhere"
        elsewhere.mkdir()
        window, backend = self._start_inbox()
        HeldInboxBackend.queue_root = str(elsewhere)  # read when the run reports, after it started
        backend.release.set()
        self.assertTrue(self._wait(lambda: window.runner_thread is None))
        self.assertIn(f"Results location: {elsewhere}.", window.progress_completion_summary.text())
        self.assertEqual(window.progress_output.text(), str(elsewhere))
        self.assertEqual(window.recent_runs()[0]["output"], str(elsewhere))
        self._open_output(window)
        self.assertEqual(self.opened, [str(elsewhere)])

    def test_inbox_result_is_the_inbox_folder_when_the_wizard_changes_during_the_run(self) -> None:
        window, backend = self._start_inbox()
        self.assertEqual(window.progress_output.text(), str(self.inbox_root),
                         "Process writes in its Inbox folder, and says so from the start")
        # The operator sets up a Full Review while the Inbox works.
        self._type_wizard_output(window, self.wizard_output)
        backend.release.set()
        self.assertTrue(self._wait(lambda: window.runner_thread is None))

        self._assert_one_recording(window)
        summary = window.progress_completion_summary.text()
        self.assertIn(f"Results location: {self.inbox_root}.", summary)
        self.assertNotIn(str(self.wizard_output), summary)
        self.assertEqual(window.progress_output.text(), str(self.inbox_root))
        entry = window.recent_runs()[0]
        self.assertEqual(entry["output"], str(self.inbox_root))
        self.assertEqual(entry["workflow"], WORKFLOW_REVIEW_NEW_VIDEOS)
        self.assertNotIn(str(self.wizard_output), window.app_settings.get("recent_output_folders") or [])
        self.assertEqual(window.review_inbox_operator_status.text(), "Ready for Codex review",
                         "the Inbox page shows its own run's outcome")
        self._open_output(window)
        self.assertEqual(self.opened, [str(self.inbox_root)])

    def test_full_review_reports_the_folder_it_started_with(self) -> None:
        window = self._window(HeldFullReviewBackend)
        recording = self.root / "recordings" / "a.mkv"
        recording.parent.mkdir()
        recording.write_bytes(b"not really video")
        started_output = self.root / "full-review-output"
        started_output.mkdir()
        window.start_workflow_from_home(WORKFLOW_FULL_REVIEW)
        window.run_settings["input_path"] = str(recording)
        window.run_settings["output_folder"] = str(started_output)
        refused = mock.Mock(side_effect=lambda _parent, title, text, *rest: self.fail(f"{title}: {text}"))
        with mock.patch("media_manglers_workbench.app.QMessageBox.warning", refused), \
                mock.patch("media_manglers_workbench.app.QMessageBox.information", refused):
            window.start_job()
        self.assertTrue(self._wait(lambda: bool(HeldFullReviewBackend.instances) and HeldFullReviewBackend.instances[-1].started.is_set()))
        # The operator sets up the next review while this one runs.
        self._type_wizard_output(window, self.wizard_output)
        HeldFullReviewBackend.instances[-1].release.set()
        self.assertTrue(self._wait(lambda: window.runner_thread is None))

        self.assertIn(f"Results location: {started_output}.", window.progress_completion_summary.text())
        self.assertEqual(window.recent_runs()[0]["output"], str(started_output))
        self.assertEqual(window.recent_runs()[0]["workflow"], WORKFLOW_FULL_REVIEW)
        self._open_output(window)
        self.assertEqual(self.opened, [str(started_output)])


if __name__ == "__main__":
    unittest.main()
