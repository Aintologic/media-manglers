"""211: one output-folder rule, applied the same way before any feature starts.

The setup check marked a temporary output folder "Complete", then the run refused it. Now the
wizard's Output step, Find my bug reports and Review Media Inbox all use the one rule the run uses
(media_manglers.core.user_folders), and say why before anything starts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from media_manglers.core.user_folders import RECORDINGS_FOLDERS_ENV, recordings_drive_problem, temporary_folder_problem  # noqa: E402
from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.metadata import WORKFLOW_FULL_REVIEW, WORKFLOW_REVIEW_NEW_VIDEOS  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: E402
from tests.qt_input import bring_to_front, row_point  # noqa: E402
from tests.test_workbench_bug_reports import ScriptedBackend, _resources  # noqa: E402

TEMP_FOLDER = r"C:\work\temp\_VIDEO_OUTPUT"
KEPT_FOLDER = r"D:\Kept\Media Mangler"
# 223: a kept folder on the system drive, never created; nothing in these tests looks at D:.
KEPT_ON_C = r"C:\Kept\Media Mangler"
NO_OVERRIDE = {key: value for key, value in os.environ.items() if key != "MEDIA_MANGLERS_ALLOW_TEMP_OUTPUT"}


class OneFolderRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window: WorkbenchWindow | None = None
        ScriptedBackend.instances = []
        ScriptedBackend.lines = []
        self.recording = self.root / "recordings" / "a.mkv"
        self.recording.parent.mkdir()
        self.recording.write_bytes(b"not really video")

    def tearDown(self) -> None:
        if self.window:
            self.window._closing_after_smoke = True
            self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def _window(self, output_folder: str) -> WorkbenchWindow:
        settings_path = self.root / "settings.json"
        settings_path.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
            "log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
            "output_folder": output_folder}}), encoding="utf-8")
        self.window = WorkbenchWindow(settings_path=settings_path, profiles_dir=self.root / "profiles",
                                      runner_factory=ScriptedBackend, resources=_resources())
        self.window.show()
        self.app.processEvents()
        return self.window

    def _output_step_state(self, window: WorkbenchWindow) -> str:
        window._refresh_wizard_step_states()
        return str(window.wizard_steps.item(3).data(Qt.ItemDataRole.UserRole))

    def test_the_output_step_is_blocked_for_a_folder_the_run_would_refuse(self) -> None:
        with patch.dict(os.environ, NO_OVERRIDE, clear=True):
            window = self._window(TEMP_FOLDER)
            window.start_workflow_from_home(WORKFLOW_FULL_REVIEW)
            window.run_settings["output_folder"] = TEMP_FOLDER
            blocked = self._output_step_state(window)
            window.run_settings["output_folder"] = KEPT_FOLDER
            complete = self._output_step_state(window)
        self.assertEqual((blocked, complete), ("blocked", "complete"))

    def test_find_my_bug_reports_refuses_a_temporary_output_folder_before_it_starts(self) -> None:
        with patch.dict(os.environ, NO_OVERRIDE, clear=True):
            window = self._window(TEMP_FOLDER)
            page = window.bug_reports_page
            page.add_recordings([self.recording])
            with patch("media_manglers_workbench.bug_reports.QMessageBox.warning") as warning:
                QTest.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
                self.app.processEvents()
        self.assertEqual(ScriptedBackend.instances, [])
        self.assertIn("is a temporary folder", warning.call_args[0][2])

    def test_the_inbox_refuses_a_temporary_evidence_folder_but_not_a_temporary_scratch_folder(self) -> None:
        with patch.dict(os.environ, NO_OVERRIDE, clear=True):
            window = self._window(KEPT_FOLDER)
            window.start_workflow_from_home(WORKFLOW_REVIEW_NEW_VIDEOS)
            window.run_settings.update({"review_evidence_root": TEMP_FOLDER, "review_local_work_root": TEMP_FOLDER})
            refused = window._review_inbox_configuration_errors(preparation=True)
            window.run_settings["review_evidence_root"] = KEPT_FOLDER
            kept = window._review_inbox_configuration_errors(preparation=True)
            badge = self._output_step_state(window)
        self.assertTrue(any("evidence folder" in error and "temporary folder" in error for error in refused), refused)
        self.assertFalse(any("temporary folder" in error for error in kept), kept)
        self.assertEqual(badge, "complete")


class OutputStepSaysWhyTests(unittest.TestCase):
    """223: the Output step shows why a folder is refused, in the one rule's own words."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window: WorkbenchWindow | None = None

    def tearDown(self) -> None:
        if self.window:
            self.window._closing_after_smoke = True
            self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def _window(self, **settings: str) -> WorkbenchWindow:
        settings_path = self.root / "settings.json"
        settings_path.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
            "log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
            "output_folder": KEPT_ON_C, **settings}}), encoding="utf-8")
        self.window = WorkbenchWindow(settings_path=settings_path, profiles_dir=self.root / "profiles",
                                      runner_factory=ScriptedBackend, resources=_resources())
        self.window.resize(1400, 900)
        self.window.show()
        self.app.processEvents()
        return self.window

    def _go_to_output_step(self, window: WorkbenchWindow) -> None:
        QTest.mouseClick(window.nav_buttons["New Review"], Qt.MouseButton.LeftButton)
        self.app.processEvents()
        steps = window.wizard_steps
        QTest.mouseClick(steps.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         row_point(steps, steps.model().index(3, 0)))
        self.app.processEvents()
        self.assertEqual(window.wizard_stack.currentIndex(), 3, "the Output step is in front")

    def _type_output(self, window: WorkbenchWindow, folder: str) -> None:
        bring_to_front(window.output_path_edit)
        QTest.mouseClick(window.output_path_edit, Qt.MouseButton.LeftButton)
        QTest.keyClick(window.output_path_edit, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(window.output_path_edit, folder)
        self.app.processEvents()

    def _shown_on_the_output_step(self, window: WorkbenchWindow) -> list[str]:
        step = window.wizard_stack.widget(3)
        return [label.text() for label in step.findChildren(QLabel) if label.isVisible() and label.text()]

    def test_the_output_step_says_why_a_temporary_folder_is_refused(self) -> None:
        with patch.dict(os.environ, NO_OVERRIDE, clear=True):
            window = self._window()
            self._go_to_output_step(window)
            self._type_output(window, TEMP_FOLDER)
            reason = temporary_folder_problem(TEMP_FOLDER)
            self.assertIn("temporary folder", reason)
            self.assertIn(reason, self._shown_on_the_output_step(window))
            self.assertEqual(window.wizard_next.toolTip(), reason, "the same words as Next's tooltip")
            self.assertIn(reason, window.validate_current_run(), "and the same words as step 5")
            self.assertEqual(window.wizard_steps.item(3).data(Qt.ItemDataRole.UserRole), "blocked")

            self._type_output(window, KEPT_ON_C)
            self.assertNotIn(reason, self._shown_on_the_output_step(window))
            self.assertFalse(any("temporary folder" in text for text in self._shown_on_the_output_step(window)))

    def test_the_output_step_says_why_the_recordings_drive_is_refused(self) -> None:
        recordings = self.root / "recordings"
        recordings.mkdir()
        inside = str(recordings / "out")
        with patch.dict(os.environ, {RECORDINGS_FOLDERS_ENV: ""}):
            window = self._window(review_source_folders=str(recordings))
            self._go_to_output_step(window)
            self._type_output(window, inside)
            reason = recordings_drive_problem(inside, "output folder")
            self.assertIn("read-only to Media Manglers", reason)
            self.assertEqual(window._output_folder_problem(), reason)
            self.assertIn(reason, self._shown_on_the_output_step(window))
            self.assertEqual(window.wizard_next.toolTip(), reason)

            self._type_output(window, str(self.root / "kept"))
            self.assertFalse(any("read-only" in text for text in self._shown_on_the_output_step(window)))


if __name__ == "__main__":
    unittest.main()
