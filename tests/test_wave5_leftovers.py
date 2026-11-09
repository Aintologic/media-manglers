"""220: GUI glitches left over from the Wave 5 acceptance run.

- The AI Video Editor's Prepare stayed disabled after another feature's run ended, until the clip
  was chosen again: no page heard that a run it did not start had finished.
- After Stop, a recording the run had not reached said "Skipped" and the summary counted it as
  skipped, while the headline said "Cancelled". One status rule means one word.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.metadata import WORKFLOW_FULL_REVIEW  # noqa: E402
from media_manglers_workbench.runner import RunnerResult  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: E402
from tests.test_workbench_bug_reports import _resources  # noqa: E402


class StoppableBackend:
    """Stands in for Video Mangler.ps1: runs until released, or ends cancelled when stopped."""

    instances: list["StoppableBackend"] = []

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.cancelled = False
        StoppableBackend.instances.append(self)

    def cancel(self) -> None:
        self.cancelled = True
        self.release.set()

    def run(self, command, on_log=None, *, cwd=None) -> RunnerResult:
        self.started.set()
        self.release.wait(30)
        if self.cancelled:
            return RunnerResult(status="cancelled", exit_code=None, stdout_lines=[], error="")
        return RunnerResult(status="succeeded", exit_code=0, stdout_lines=[], error="")


class LeftoverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window: WorkbenchWindow | None = None
        StoppableBackend.instances = []
        self.recording = self.root / "recordings" / "a.mkv"
        self.recording.parent.mkdir()
        self.recording.write_bytes(b"not really video")

    def tearDown(self) -> None:
        for backend in StoppableBackend.instances:
            backend.release.set()
        if self.window:
            self._wait(lambda: self.window.runner_thread is None)
            self.window._closing_after_smoke = True
            self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def _wait(self, condition, seconds: float = 10.0) -> bool:
        for _ in range(int(seconds * 20)):
            if condition():
                return True
            self.app.processEvents()
            QTest.qWait(50)
        return condition()

    def _window(self) -> WorkbenchWindow:
        settings_path = self.root / "settings.json"
        settings_path.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
            "log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
            "output_folder": str(self.root / "out")}}), encoding="utf-8")
        self.window = WorkbenchWindow(settings_path=settings_path, profiles_dir=self.root / "profiles",
                                      runner_factory=StoppableBackend, resources=_resources())
        self.window.show()
        self.app.processEvents()
        return self.window

    def _start_full_review(self, window: WorkbenchWindow) -> StoppableBackend:
        window.start_workflow_from_home(WORKFLOW_FULL_REVIEW)
        window.run_settings["input_path"] = str(self.recording)
        window.run_settings["output_folder"] = str(self.root / "out")
        refused = mock.Mock(side_effect=lambda _parent, title, text, *rest: self.fail(f"{title}: {text}"))
        with mock.patch("media_manglers_workbench.app.QMessageBox.warning", refused), \
                mock.patch("media_manglers_workbench.app.QMessageBox.information", refused):
            window.start_job()
        self.assertTrue(self._wait(lambda: bool(StoppableBackend.instances)
                                   and StoppableBackend.instances[-1].started.is_set()), "the run did not start")
        return StoppableBackend.instances[-1]

    def test_the_editors_prepare_comes_back_when_another_features_run_ends(self) -> None:
        for ending in ("finishes", "is stopped"):
            with self.subTest(ending=ending):
                window = self._window()
                backend = self._start_full_review(window)
                editor = window.ai_video_editor_page
                with mock.patch("media_manglers_workbench.ai_video_editor.audio_tracks",
                                return_value=["Track 1", "Track 2", "Track 3"]):
                    editor.set_recording(self.recording)
                # 226: the tracks are read on a thread of their own, and Prepare waits for that too; only
                # once they are read does a disabled Prepare show it waits for the other run.
                self.assertTrue(self._wait(lambda: not editor.probing), "the recording's tracks were read")
                self.assertEqual(editor.track_titles, ["Track 1", "Track 2", "Track 3"])
                self.assertFalse(editor.prepare_button.isEnabled(), "Prepare waits while another run is busy")
                if ending == "finishes":
                    backend.release.set()
                else:
                    window.navigate("Queue / Progress")
                    QTest.mouseClick(window.cancel_button, Qt.MouseButton.LeftButton)
                self.assertTrue(self._wait(lambda: window.runner_thread is None))
                self.assertTrue(editor.prepare_button.isEnabled(),
                                "Prepare is enabled again without choosing the clip a second time")
                window._closing_after_smoke = True
                window.close()
                self.window = None

    def test_after_stop_every_place_says_cancelled(self) -> None:
        window = self._window()
        self._start_full_review(window)
        window.navigate("Queue / Progress")
        # Stopped before the recording's first progress line, as in the acceptance run.
        QTest.mouseClick(window.cancel_button, Qt.MouseButton.LeftButton)
        self.assertTrue(self._wait(lambda: window.runner_thread is None))
        states = set(window.progress_item_states.values())
        self.assertEqual(states, {"cancelled"})
        summary = window.progress_completion_summary.text()
        self.assertIn("0 completed", summary)
        self.assertIn("1 cancelled", summary)
        self.assertNotIn("skipped", summary.lower())
        self.assertIn("Cancelled", window.progress_state_banner.text())


if __name__ == "__main__":
    unittest.main()
