"""Product inventory of the AI Video Editor (feature 4, 226): every button, list, box and Settings
field of its page and its Settings tab is there, can be reached by the mouse, and says what it is.

Like tests/test_product_inventory.py for the whole app, this pins what the operator can see and use. A
control that goes missing, ends up hidden or covered, or loses its words fails here. Adding a control
means adding it to the lists below in the same pull request.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton,
    QApplication,
    QComboBox,
    QFormLayout,
    QLabel,
    QLayout,
    QWidget,
)

from media_manglers.core.race_video.project import add_version, create_project  # noqa: E402
from media_manglers.core.race_video.render import RenderOptions, render_version  # noqa: E402
from media_manglers.core.race_video.timeline import SCHEMA  # noqa: E402
from media_manglers_workbench.ai_video_editor import PAGE_NAME  # noqa: E402
from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.metadata import SETTING_METADATA  # noqa: E402
from media_manglers_workbench.runner import FakeRunner  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: E402
from tests.qt_input import bring_to_front, choose_in_combo, click, widget_point  # noqa: E402
from tests.test_workbench_ai_video_editor import LAYOUT, _resources  # noqa: E402

FFMPEG = shutil.which("ffmpeg")

# The page, view by view (236: the start view, a video's first steps, the video with a version, and its
# dialogs): (attribute, what it says). A button says its text; a box, a list or a text field says its label
# (the form's label beside it, or its accessible name).
START_BUTTONS = (
    ("editor_settings_button", "Editor settings"),
    ("refresh_button", "Refresh"),
    # 242 (Wave C2): shown while a video is not linked to its recording; the page's video here is made unlinked.
    ("link_button", "Link recordings…"),
)
STEP_BUTTONS = (
    ("choose_button", "Choose a recording…"),
    ("voice_reset_button", "Reset to Auto"),
    ("game_reset_button", "Reset to Auto"),
    ("masks_button", "Privacy masks…"),
    ("prepare_button", "Prepare for the AI editor"),
    ("back_button", "← Your videos"),
)
# 236 fix round: the video's toolbar, under its name, instead of a ⋯ menu.
TOOL_BUTTONS = (
    ("tool_buttons.settings", "Video settings"),
    ("tool_buttons.prompt", "Prompt"),
    ("tool_buttons.story", "Story & review"),
    ("tool_buttons.files", "Files"),
)
PROMPT_BUTTONS = (
    ("copy_claude_button", "Copy prompt for Claude Code"),
    ("copy_codex_button", "Copy prompt for Codex"),
    ("see_prompt_button", "See the prompt first"),
)
VIDEO_BUTTONS = (
    ("back_button", "← Your videos"),
    ("export_button", "Approve and export…"),
    *TOOL_BUTTONS,
    # On the picture: a version with only a preview offers the preview alone.
    ("play_button", "Play the preview"),
    ("save_notes_button", "Save notes, copy prompt for Claude Code"),
    ("save_notes_codex_button", "…for Codex"),
)
STEP_FIELDS = (
    ("voice_combo", "Your voice"),
    ("game_combo", "Game sound"),
    ("budget_combo", "AI budget"),
)
VIDEO_FIELDS = (
    ("tabs_frame", "Versions"),
    ("feedback_edit", "What should change?"),
)
# What each toolbar button's panel offers, in its order, for a version with a preview only (the play choices
# show in Files once the version has a final too). The export quality is a heading and its choices.
TOOL_PANELS = {
    "settings": ["Your voice", "Game sound", "AI budget", "Privacy masks…"],
    "prompt": ["Copy prompt for Claude Code", "Copy prompt for Codex", "See the prompt first", "Start a fresh edit"],
    "story": ["The story", "The editor's own review"],
    "files": ["This version's files", "Render a preview", "Export quality: YouTube (recommended) · Using main setting",
              "YouTube (recommended)", "Highest quality", "Smaller file", "Open project folder", "Open export folder",
              "Refresh", "Nothing is exported yet: Approve and export… makes the export."],
}
# What the boxes offer, in order. The track boxes start with Auto (226, decision A).
PAGE_CHOICES = {
    "voice_combo": ["Auto", "Track 1", "Track 2"],
    "game_combo": ["Auto", "Track 1", "Track 2"],
    "budget_combo": ["Light", "Standard", "Thorough"],
    "export_quality_combo": ["YouTube (recommended)", "Highest quality", "Smaller file"],
}
# Sentences the page shows once there is something to say: (attribute, words it holds then).
PAGE_SENTENCES = (
    ("status_sentence", "Check the tracks"),
    ("recording_label", "2 audio tracks"),
    ("voice_state", "Auto: Track 2, narration, from your Narration track setting"),
    ("game_state", "Auto: Track 1, game sound, from your Narration track setting"),
    ("budget_words", "Prepare takes a picture of the race every"),
)

# Settings > AI Video Editor, top to bottom.
SETTINGS_BUTTONS = (("browse_button", "Browse…"),)
SETTINGS_FIELDS = (
    ("folder_edit", "Folder for edited videos"),
    ("budget_combo", "AI budget for a new video"),
    ("model_edits.claude", "Claude Code model named in the prompt"),
    ("model_edits.codex", "Codex model named in the prompt"),
    ("quality_combo", "Export quality"),
    ("quick_combo", "Quick passes"),
)
SETTINGS_CHOICES = {
    "budget_combo": ["Light", "Standard", "Thorough"],
    "quality_combo": ["YouTube (recommended)", "Highest quality", "Smaller file"],
    "quick_combo": ["Whisper small (faster)", "Use main setting"],
}
SETTINGS_SENTENCES = (
    ("quick_state", "Overridden"),
    ("note", "Narration track setting"),
)


def _attribute(owner: object, name: str) -> QWidget:
    value: object = owner
    for part in name.split("."):
        value = value[part] if isinstance(value, dict) else getattr(value, part)
    assert isinstance(value, QWidget), name
    return value


def _holds(layout: QLayout, widget: QWidget) -> bool:
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item.widget() is widget or (item.layout() is not None and _holds(item.layout(), widget)):
            return True
    return False


def _label(widget: QWidget) -> str:
    """The words beside ``widget``: its form's label, else its accessible name."""

    holder = widget.parentWidget()
    while holder is not None:
        for form in holder.findChildren(QFormLayout):
            for row in range(form.rowCount()):
                label = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
                field = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
                if label is None or field is None or not isinstance(label.widget(), QLabel):
                    continue
                if field.widget() is widget or (field.layout() is not None and _holds(field.layout(), widget)):
                    return label.widget().text()
        holder = holder.parentWidget()
    return widget.accessibleName()


@unittest.skipUnless(FFMPEG and shutil.which("ffprobe"), "FFmpeg and FFprobe are required")
class AiVideoEditorInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.temp_class = tempfile.TemporaryDirectory()
        cls.source = Path(cls.temp_class.name) / "race.mkv"
        subprocess.run([
            FFMPEG, "-hide_banner", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=s=960x180:r=30:d=4",
            "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:duration=4",
            "-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.05:sample_rate=48000:duration=4",
            "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-shortest", str(cls.source),
        ], check=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp_class.cleanup()

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        path = self.root / "settings.json"
        path.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
            "log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
            "output_folder": str(self.root / "out"), "evidence_track_roles": "1=game,2=narration"}}), encoding="utf-8")
        self.window = WorkbenchWindow(settings_path=path, profiles_dir=self.root / "profiles",
                                      runner_factory=FakeRunner, resources=_resources())
        self.window.resize(1400, 900)
        self.window.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.window._closing_after_smoke = True
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def _page_with_a_video(self):
        """The page with a prepared video that has a version."""

        project = create_project(self.root / "out", self.source, "race")
        timeline = {"schema": SCHEMA, "source": str(self.source), "source_layout": LAYOUT,
                    "tracks": {"voice": 1, "game": 0},
                    "scenes": [{"id": "s01", "beat": "start", "reason": "test", "in": 0.5, "out": 3.0, "view": "center",
                                "audio": {"voice": 1.0, "game": 0.5}}]}
        add_version(project, timeline, story="# Story\n\nA made-up race.", source_duration=4.0, audio_streams=2)
        (project / "analysis" / "analysis.json").write_text(json.dumps({"settings": {"budget": "light"}}), encoding="utf-8")
        # Approve and export… needs a version with a preview.
        render_version(project, 1, "preview", RenderOptions(ffmpeg=FFMPEG, ffprobe=shutil.which("ffprobe"), masks={},
                                                             encoder="x264", hwaccel="none"))
        window = self.window
        QTest.mouseClick(window.nav_buttons[PAGE_NAME], Qt.MouseButton.LeftButton)
        page = window.ai_video_editor_page
        self.assertIs(window.page_stack.currentWidget(), page)
        QTest.mouseClick(page.refresh_button, Qt.MouseButton.LeftButton)
        self.assertEqual([project["name"] for project in page.projects], ["race"])
        return page, project

    def _choose(self, page) -> None:
        with patch("media_manglers_workbench.ai_video_editor.QFileDialog.getOpenFileName",
                   return_value=(str(self.source), "")):
            click(page.make_video_button)
        deadline = time.monotonic() + 60
        while page.probing and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertFalse(page.probing)

    def _check(self, owner: object, buttons, fields, choices, sentences) -> None:
        for name, words in buttons:
            with self.subTest(button=name):
                widget = _attribute(owner, name)
                self.assertIsInstance(widget, QAbstractButton)
                bring_to_front(widget)
                widget_point(widget)
                self.assertEqual(widget.text(), words)
        for name, words in fields:
            with self.subTest(field=name):
                widget = _attribute(owner, name)
                bring_to_front(widget)
                widget_point(widget)
                self.assertEqual(_label(widget), words)
                if isinstance(widget, QComboBox):
                    self.assertTrue(widget.toolTip().strip(), f"{name} explains itself")
        for name, offered in choices.items():
            with self.subTest(choices=name):
                combo = _attribute(owner, name)
                self.assertEqual([combo.itemText(i) for i in range(combo.count())], offered)
        for name, words in sentences:
            with self.subTest(sentence=name):
                widget = _attribute(owner, name)
                bring_to_front(widget)
                widget_point(widget)
                self.assertIn(words, widget.text())

    def test_264_a_voice_track_picked_here_is_your_answer_and_auto_clears_it(self) -> None:
        from media_manglers.core import speech_facts

        page, _project = self._page_with_a_video()
        self._choose(page)
        recording = page.recording
        choose_in_combo(page.voice_combo, "Track 2")
        self.assertEqual(speech_facts.confirmed_track(recording), 2)
        self.assertEqual(speech_facts.answer_for(recording).by, "editor_page")
        choose_in_combo(page.game_combo, "Track 1")
        self.assertEqual(speech_facts.confirmed_track(recording), 2, "the game sound is not your voice")
        QTest.mouseClick(page.voice_reset_button, Qt.MouseButton.LeftButton)
        self.assertIsNone(speech_facts.confirmed_track(recording))
        self.assertEqual(speech_facts.answer_for(recording).state, "cleared")

    def test_264_what_the_app_knows_says_when_your_answer_differs_from_what_it_heard(self) -> None:
        from media_manglers.core import speech_facts, voice_track

        page, _project = self._page_with_a_video()
        self._choose(page)
        recording = page.recording
        speech_facts.record_measure(recording, {
            "rule_version": voice_track.VOICE_RULE_VERSION, "status": "selected", "selected_ordinal": 0, "decided_by": "auto",
            "track_activity": {"1": {"silent": False, "moments": [[1.0, 2.0]]}}}, measured_by=speech_facts.BY_BUGS, titles={})
        choose_in_combo(page.voice_combo, "Track 2")
        self.assertIn("You chose Track 2. The app heard your voice on Track 1. Your choice is used.", page.knowledge_label.text())
        QTest.mouseClick(page.voice_reset_button, Qt.MouseButton.LeftButton)
        self.assertNotIn("You chose", page.knowledge_label.text())

    def test_264_the_voice_box_follows_your_answer_from_any_screen(self) -> None:
        from media_manglers.core import speech_facts

        page, _project = self._page_with_a_video()
        self._choose(page)
        recording = page.recording
        speech_facts.confirm_track(recording, 2, by=speech_facts.ANSWERED_ON_BUGS)
        page._on_tracks_read(page._probe_number, (page.track_titles, {"picked": {"voice": 0}}))
        self.assertEqual(page.voice_combo.currentText(), "Track 1", "what the read handed over is what the box shows")
        self._choose(page)
        self.assertEqual(page.voice_combo.currentText(), "Track 2")
        speech_facts.clear_track(recording, by=speech_facts.ANSWERED_ON_BUGS)
        self._choose(page)
        self.assertEqual(page.voice_combo.currentText(), "Auto", "Automatic returns everywhere")

    def test_every_control_of_the_page_is_there_reachable_and_labelled(self) -> None:
        page, project = self._page_with_a_video()
        # The start view: the big way in (a card that says what it does), Continue, the links.
        self._check(page, START_BUTTONS, (), {}, ())
        widget_point(page.make_video_button)
        self.assertEqual(page.make_video_button.accessibleName(), "Make a video from a recording")
        self.assertTrue(page.continue_card.isVisible())
        self.assertEqual(page.continue_card.name_label.text(), "Continue: race")
        self.assertEqual(page.video_cards.accessibleName(), "Your videos")
        widget_point(page._cards[str(project)])

        # A video's first step, for the recording chosen: every box of Prepare.
        self._choose(page)
        for combo in (page.voice_combo, page.game_combo):
            choose_in_combo(combo, "Track 2" if combo is page.voice_combo else "Track 1")
        self._check(page, STEP_BUTTONS + TOOL_BUTTONS, STEP_FIELDS,
                    {key: PAGE_CHOICES[key] for key in ("voice_combo", "game_combo", "budget_combo")},
                    PAGE_SENTENCES[:2] + PAGE_SENTENCES[4:])
        for name, combo in (("voice_reset_button", page.voice_combo), ("game_reset_button", page.game_combo)):
            QTest.mouseClick(_attribute(page, name), Qt.MouseButton.LeftButton)
            self.assertEqual(combo.currentText(), "Auto")
        self._check(page, (), (), {}, PAGE_SENTENCES[2:4])
        # The warnings are said only once there is something to warn of; each is in its place: the tracks
        # warning beside the boxes and Prepare; the masks and silent-track warnings of the last Prepare under
        # the video's status sentence, in sight over its steps and over its player.
        self.assertFalse(page.mask_warning.isVisible())
        self.assertIs(page.mask_warning.parentWidget(), page.video_view)
        self.assertFalse(page.tracks_warning.isVisible())
        self.assertIs(page.tracks_warning.parentWidget(), page.prepare_button.parentWidget())
        self.assertFalse(page.sound_warning.isVisible())
        self.assertIs(page.sound_warning.parentWidget(), page.video_view)
        layout = page.video_view.layout()
        self.assertEqual([layout.indexOf(widget) for widget in (page.status_sentence, page.mask_warning, page.sound_warning)],
                         [layout.indexOf(page.status_sentence) + step for step in range(3)])
        # This recording's video is prepared, so its second step shows: the prompts.
        self.assertTrue(page.prompt_card.isVisible())
        self._check(page, PROMPT_BUTTONS, (), {}, ())

        # The video with its version: the header, the toolbar, the player's place, the notes.
        click(page.back_button)
        click(page._cards[str(project)])
        self._check(page, VIDEO_BUTTONS, VIDEO_FIELDS, {}, ())
        self.assertEqual([tab.text() for tab in page.version_tabs], ["v001 · newest"])
        self.assertTrue(page.scene_strip.isVisible())
        self.assertEqual([block.block["name"] for block in page.scene_strip.blocks], ["Start"])
        widget_point(page.scene_strip.blocks[0].pen)
        self.assertEqual(page.scene_strip.blocks[0].pen.accessibleName(), "Write a note about Start")
        # Each toolbar button opens its panel; every choice in it is in sight, reachable and says what it is.
        for tool, offered in TOOL_PANELS.items():
            with self.subTest(panel=tool):
                click(page.tool_buttons[tool])
                panel = page.tool_panels[tool]
                self.assertTrue(panel.isVisible())
                shown = [widget for widget in panel.findChildren(QWidget)
                         if isinstance(widget, (QAbstractButton, QLabel)) and widget.isVisibleTo(panel)]
                self.assertEqual([widget.text() for widget in shown], offered)
                for widget in shown:
                    if isinstance(widget, QAbstractButton):
                        widget_point(widget)
                        self.assertTrue(widget.toolTip().strip(), f"{widget.text()} explains itself")
                panel.hide()
        # Approve and export…: the export quality, labelled on screen and for a screen reader.
        click(page.export_button)
        self.assertTrue(page.export_dialog.isVisible())
        self._check(page.export_dialog, (("export_button", "Export v001"), ("cancel_button", "Cancel")),
                    (("quality_combo", "Export quality"),), {"quality_combo": PAGE_CHOICES["export_quality_combo"]},
                    (("quality_state", "Using main setting"),))
        self.assertEqual(page.export_quality_combo.accessibleName(), "Export quality for this video")
        page.export_dialog.reject()

    def test_every_field_of_the_settings_tab_is_there_reachable_and_labelled(self) -> None:
        window = self.window
        QTest.mouseClick(window.nav_buttons["Settings"], Qt.MouseButton.LeftButton)
        panel = window.ai_video_editor_settings
        tabs = window.settings_tabs
        self.assertEqual(tabs.tabText(tabs.indexOf(panel)), "AI Video Editor")
        bring_to_front(panel)
        self._check(panel, SETTINGS_BUTTONS, SETTINGS_FIELDS, SETTINGS_CHOICES, SETTINGS_SENTENCES)

    def test_the_tab_saves_every_setting_of_the_editor_and_nothing_else(self) -> None:
        # Every setting in the AI Video Editor's group has its field on the tab, and the tab writes no other.
        group = {item.key for item in SETTING_METADATA if item.category == "AI Video Editor"}
        self.assertEqual(set(self.window.ai_video_editor_settings.values()), group)
        self.assertEqual(group, {"race_video_output_folder", "race_video_budget", "race_video_claude_model",
                                 "race_video_codex_model", "race_video_export_quality", "race_video_quick_whisper_model"})


if __name__ == "__main__":
    unittest.main()
