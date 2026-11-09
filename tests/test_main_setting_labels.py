"""214: one main setting per shared job; a feature's own value is an override, and says so.

Package any video for AI's track choice follows the main narration-track setting while it is Auto,
and Review Media Inbox's evidence and scratch folders follow the main output folder and the app's
temporary folder while left blank. Beside each, the app shows "Using main setting" or "Overridden".
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from media_manglers_workbench import main_settings  # noqa: E402
from media_manglers_workbench.app import AdvancedSettingsDialog  # noqa: E402
from media_manglers_workbench.command_builder import build_workflow_command  # noqa: E402
from media_manglers_workbench.metadata import WORKFLOW_FULL_REVIEW, WORKFLOW_REVIEW_NEW_VIDEOS  # noqa: E402
from media_manglers_workbench.review_inbox_dialogs import ReviewInboxSettingsDialog  # noqa: E402
from media_manglers_workbench.settings import build_default_settings  # noqa: E402

MAIN_OUTPUT = r"D:\Kept\Media Mangler"
MAIN_TEMP = r"C:\Work\Media Mangler temp"


def _values(argv: list[str], flag: str) -> list[str]:
    return [argv[index + 1] for index, token in enumerate(argv) if token == flag]


class RuleTests(unittest.TestCase):
    def test_a_folder_follows_the_main_one_when_blank_or_the_same(self) -> None:
        self.assertEqual(main_settings.folder_state("", MAIN_OUTPUT), main_settings.USING_MAIN_SETTING)
        self.assertEqual(main_settings.folder_state(MAIN_OUTPUT.lower() + "\\", MAIN_OUTPUT), main_settings.USING_MAIN_SETTING)
        self.assertEqual(main_settings.folder_state(r"E:\Inbox evidence", MAIN_OUTPUT), main_settings.OVERRIDDEN)

    def test_the_track_choice_follows_the_main_setting_only_on_auto(self) -> None:
        self.assertEqual(main_settings.track_choice_state("Auto", 0), main_settings.USING_MAIN_SETTING)
        self.assertEqual(main_settings.track_choice_state("Track", 3), main_settings.OVERRIDDEN)
        self.assertEqual(main_settings.track_choice_state("Auto", 3), main_settings.OVERRIDDEN)
        self.assertEqual(main_settings.track_choice_state("All", 0), main_settings.OVERRIDDEN)

    def test_blank_inbox_folders_are_sent_as_the_main_ones(self) -> None:
        settings = {**build_default_settings(), "output_folder": MAIN_OUTPUT, "temp_folder": MAIN_TEMP,
                    "review_evidence_root": "", "review_local_work_root": "", "review_inbox_action": "Scan"}
        argv = build_workflow_command(settings, workflow=WORKFLOW_REVIEW_NEW_VIDEOS).argv
        self.assertEqual(_values(argv, "-ReviewEvidenceRoot"), [MAIN_OUTPUT])
        self.assertEqual(_values(argv, "-ReviewLocalWorkRoot"), [MAIN_TEMP])
        own = build_workflow_command({**settings, "review_evidence_root": r"E:\Inbox evidence"},
                                     workflow=WORKFLOW_REVIEW_NEW_VIDEOS).argv
        self.assertEqual(_values(own, "-ReviewEvidenceRoot"), [r"E:\Inbox evidence"])


class LabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_full_reviews_track_choice_says_whether_it_uses_the_main_setting(self) -> None:
        defaults = build_default_settings()
        dialog = AdvancedSettingsDialog(dict(defaults), dict(defaults), dict(defaults), WORKFLOW_FULL_REVIEW)
        try:
            self.assertEqual(dialog.track_choice_state.text(), "Using main setting")
            mode = dialog.controls["transcript_audio_mode"]
            number = dialog.controls["transcript_audio_track_ordinal"]
            mode.setCurrentIndex(mode.findText("Track"))
            number.setValue(3)
            self.assertEqual(dialog.track_choice_state.text(), "Overridden")
            mode.setCurrentIndex(mode.findText("Auto"))
            number.setValue(0)
            self.assertEqual(dialog.track_choice_state.text(), "Using main setting")
        finally:
            dialog.close()

    def test_the_reset_buttons_bring_back_using_main_setting(self) -> None:
        # 220: both reset buttons set the value with signals blocked, so the label kept
        # saying "Overridden" after Track/3 was reset to Auto/0. Click the real buttons.
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QToolButton

        defaults = build_default_settings()
        for tooltip in ("Reset to application default", "Reset to profile value"):
            with self.subTest(button=tooltip):
                dialog = AdvancedSettingsDialog(dict(defaults), dict(defaults), dict(defaults), WORKFLOW_FULL_REVIEW)
                try:
                    dialog.show()
                    mode = dialog.controls["transcript_audio_mode"]
                    number = dialog.controls["transcript_audio_track_ordinal"]
                    mode.setCurrentIndex(mode.findText("Track"))
                    number.setValue(3)
                    self.assertEqual(dialog.track_choice_state.text(), "Overridden")
                    for control in (mode, number):
                        reset = next(button for button in control.parentWidget().findChildren(QToolButton)
                                     if button.toolTip() == tooltip)
                        QTest.mouseClick(reset, Qt.MouseButton.LeftButton)
                    self.assertEqual(mode.currentText(), "Auto")
                    self.assertEqual(dialog.track_choice_state.text(), "Using main setting")
                finally:
                    dialog.close()

    def test_transcript_onlys_track_choice_says_it_too(self) -> None:
        from media_manglers_workbench.metadata import WORKFLOW_TRANSCRIPT_ONLY

        defaults = build_default_settings()
        dialog = AdvancedSettingsDialog(dict(defaults), dict(defaults), dict(defaults), WORKFLOW_TRANSCRIPT_ONLY)
        try:
            self.assertEqual(dialog.track_choice_state.text(), "Using main setting")
            mode = dialog.controls["transcript_audio_mode"]
            mode.setCurrentIndex(mode.findText("Track"))
            dialog.controls["transcript_audio_track_ordinal"].setValue(2)
            self.assertEqual(dialog.track_choice_state.text(), "Overridden")
        finally:
            dialog.close()

    def test_the_inbox_folders_say_whether_they_use_the_main_ones(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            dialog = ReviewInboxSettingsDialog({"review_evidence_root": "", "review_local_work_root": ""},
                                               main_output_folder=MAIN_OUTPUT, main_temp_folder=MAIN_TEMP)
            try:
                dialog.show()
                self.assertEqual(dialog.evidence_root_state.text(), "Using main setting")
                self.assertEqual(dialog.work_root_state.text(), "Using main setting")
                self.assertIn(MAIN_OUTPUT, dialog.evidence_root.placeholderText())
                QTest.keyClicks(dialog.evidence_root, temp)
                self.assertEqual(dialog.evidence_root_state.text(), "Overridden")
                dialog.evidence_root.clear()
                QTest.keyClicks(dialog.evidence_root, MAIN_OUTPUT)
                self.assertEqual(dialog.evidence_root_state.text(), "Using main setting")
                self.assertEqual(dialog.values()["review_local_work_root"], "")
            finally:
                dialog.close()


if __name__ == "__main__":
    unittest.main()
