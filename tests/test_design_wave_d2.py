"""Design wave D2 (236): the AI Video Editor in the approved "player first" layout, clicked like an
operator would.

The start view (Make a video from a recording, Continue: <last video>, Your videos as picture cards with a
plain status), the one-video view (the version plays on the page in the app's one player; its story is a
strip of scenes under it; the notes box at the bottom; Approve and export… top right), and issue 236's items
inside it. The fix round after hand testing the first build: a labelled toolbar instead of the ⋯ menu, the play
choices on the picture, a plain message before the first version, a picture that fills its box, scene names
never cut off, and every control saying what it did.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QPoint, QRect, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QAbstractButton, QApplication, QMessageBox, QPushButton, QWidget  # noqa: E402

from media_manglers.core import app_cache, frame_render, raw_bin_library  # noqa: E402
from media_manglers.core.race_video.project import add_version, create_project  # noqa: E402
from media_manglers.core.race_video.prompt import APP_LABELS  # noqa: E402
from media_manglers.core.race_video.render import RenderOptions, render_version  # noqa: E402
from media_manglers.core.race_video.timeline import SCHEMA  # noqa: E402
from media_manglers_workbench.ai_video_editor import PAGE_NAME, PLAYING_PICTURE_LEAST, TOOL_PANELS, TOOLS  # noqa: E402
from media_manglers_workbench.play_targets import PlayTarget  # noqa: E402
from tests.qt_input import click, widget_point  # noqa: E402
from tests import test_workbench_ai_video_editor as editor_tests  # noqa: E402

FFMPEG, FFPROBE, LAYOUT = editor_tests.FFMPEG, editor_tests.FFPROBE, editor_tests.LAYOUT

REPO_ROOT = Path(__file__).resolve().parents[1]
BEATS = ("start", "start", "battle", "pit stop", "finish")


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class DesignWaveD2Tests(editor_tests.AiVideoEditorPageTests):
    """The editor page tests' window, recordings and runner, with tests of their own."""

    def _video(self, window, name: str = "race", *, versions: int = 2, preview: bool = True, label: str = "") -> Path:
        project = create_project(self.root / "out", self.source, name)
        scenes = [{"id": f"s{index + 1:02d}", "beat": beat, "reason": "test", "in": 1.0 + index * 2,
                   "out": 2.5 + index * 2, "view": "center", "audio": {"voice": 1.0, "game": 0.5}}
                  for index, beat in enumerate(BEATS)]
        for _number in range(versions):
            add_version(project, {"schema": SCHEMA, "source": str(self.source), "source_layout": LAYOUT,
                                  "tracks": {"voice": 0, "game": 1}, "scenes": scenes},
                        story="# Story — A test race\n\n## In short\n\nThe driver holds second all race.",
                        source_duration=12.0, audio_streams=2, editor_label=label)
        (project / "analysis" / "analysis.json").write_text(json.dumps({"settings": {"budget": "light"}}),
                                                             encoding="utf-8")
        if versions and preview:
            render_version(project, versions, "preview", RenderOptions(ffmpeg=FFMPEG, ffprobe=FFPROBE, masks={},
                                                                        encoder="x264", hwaccel="none"))
        window.ai_video_editor_page.refresh()
        return project

    def _with_a_final(self, window, project: Path, number: int = 2) -> Path:
        renders = project / "versions" / f"v{number:03d}" / "renders"
        (renders / "final.mp4").write_bytes((renders / "preview.mp4").read_bytes())
        window.ai_video_editor_page.refresh()
        return renders

    # The start view --------------------------------------------------------------------------

    def test_the_start_view_shows_each_video_as_a_card_with_a_plain_status(self) -> None:
        window = self._window()
        page = self._open_page(window)
        self.assertTrue(page.no_videos.isVisible(), "an empty start view says what to do")
        self.assertEqual(page.no_videos.text(), "No videos yet. Make a video from a recording to start.")
        self.assertIsNone(page.continue_card)
        ready = self._video(window, "ready")
        waiting = self._video(window, "waiting", versions=0)
        not_prepared = create_project(self.root / "out", self.titled, "new")
        page.refresh()
        cards = page._cards
        self.assertEqual({folder: (card.pill.text(), card.pill.property("pill"), card.count_label.text())
                          for folder, card in cards.items()}, {
            str(ready): ("Ready to watch", "completed", "2 versions"),
            str(waiting): ("Waiting for your AI agent", "attention", "No versions yet"),
            str(not_prepared): ("Not prepared yet", "waiting", "No versions yet"),
        })
        self.assertEqual(cards[str(ready)].story_label.text(), "A test race")
        # Continue: the video something happened in last.
        self.assertEqual(page.continue_card.name_label.text(), "Continue: new")
        meta = json.loads((ready / "project.json").read_text(encoding="utf-8"))
        meta["versions"][-1]["created"] = "2099-01-01T00:00:00+00:00"
        (ready / "project.json").write_text(json.dumps(meta), encoding="utf-8")
        page.refresh()
        self.assertEqual(page.continue_card.name_label.text(), "Continue: ready")
        self.assertEqual(page.continue_card.line_label.text(), "Version 2 is ready to watch.")
        click(page.continue_card)
        self.assertEqual(page.current_project()["folder"], str(ready))
        self.assertEqual([tab.text() for tab in page.version_tabs], ["v001", "v002 · newest"])
        self.assertTrue(page.version_tabs[1].isChecked(), "the newest version is chosen")

    def test_editor_settings_opens_the_ai_video_editor_tab_of_settings(self) -> None:
        window = self._window()
        page = self._open_page(window)
        click(page.editor_settings_button)
        self.assertIs(window.page_stack.currentWidget(), window.pages["Settings"])
        self.assertIs(window.settings_tabs.currentWidget(), window.ai_video_editor_settings)

    def test_a_card_picture_comes_from_the_masked_preview_and_is_kept_in_the_cache(self) -> None:
        window = self._window()
        taken = []
        real = frame_render.render_stills

        def watched(ffmpeg, source, *args, **kwargs):
            taken.append(Path(source))
            return real(ffmpeg, source, *args, **kwargs)

        with patch.object(frame_render, "render_stills", watched):
            project = self._video(window, "ready")
            page = self._open_page(window)
            card = page._cards[str(project)]
            deadline = time.monotonic() + 60
            while card._picture is None and time.monotonic() < deadline:
                QTest.qWait(50)
        preview = project / "versions" / "v002" / "renders" / "preview.mp4"
        self.assertEqual(taken, [preview], "only ever the render, which has the privacy masks applied")
        picture = Path(card._picture)
        self.assertEqual(picture.parent, app_cache.cache_root("") / "editor-thumbnails")
        self.assertTrue(picture.is_file())
        page.refresh()
        self.assertEqual(taken, [preview], "a picture made once is reused")
        self.assertEqual(page._cards[str(project)]._picture, str(picture))

    # The one-video view ----------------------------------------------------------------------

    def test_approve_and_export_is_top_right_and_everything_else_is_on_a_labelled_toolbar(self) -> None:
        # Fix round, finding 1: a hidden "⋯" menu hid everything. Nothing is reachable only through one now.
        window = self._window()
        project = self._video(window)
        page = self._open_page(window)
        self._open_video(page, project)
        view = page.video_view
        left = lambda widget: widget.mapTo(view, QPoint(0, 0)).x()  # noqa: E731
        right = lambda widget: widget.mapTo(view, QPoint(widget.width(), 0)).x()  # noqa: E731
        top = lambda widget: widget.mapTo(view, QPoint(0, 0)).y()  # noqa: E731
        self.assertLess(right(page.project_title), left(page.export_button))
        self.assertGreater(right(page.export_button), view.width() - 40, "Approve and export… is top right")
        self.assertTrue(page.export_button.property("primary"))
        self.assertEqual([button for button in page.findChildren(QPushButton) if button.text() in ("⋯", "...", "More")],
                         [], "no hidden menu")
        # Under the title: the version tabs, a divider, then one labelled button with an icon for each group.
        self.assertEqual([button.text() for button in page.tool_buttons.values()],
                         ["Video settings", "Prompt", "Story & review", "Files"])
        # The walk on the real screen found "Story _review": a single & marks a keyboard letter in Qt.
        self.assertEqual(QPushButton.text(page.tool_buttons["story"]), "Story && review", "the & itself shows")
        self.assertEqual(page.tool_buttons["story"].accessibleName(), "Story & review")
        self.assertGreater(top(page.tabs_frame), top(page.export_button))
        # In reading order after the tabs, on their row (the row wraps onto another when it does not fit; the
        # real-font fit check measures it with Windows' own fonts).
        places = [(top(page.tabs_frame), left(page.tabs_frame))]
        for button in page.tool_buttons.values():
            with self.subTest(tool=button.text()):
                self.assertFalse(button.icon().isNull())
                self.assertIs(button.parentWidget(), page.toolbar)
                self.assertGreater((top(button), left(button)), places[-1])
                places.append((top(button), left(button)))
        for tool, words, _icon in TOOLS:
            with self.subTest(panel=words):
                click(page.tool_buttons[tool])
                panel = page.tool_panels[tool]
                self.assertTrue(panel.isVisible(), "a click opens it")
                self.assertTrue(page.tool_buttons[tool].property("open"), "its button shows it is open")
                below = page.tool_buttons[tool].mapToGlobal(QPoint(0, page.tool_buttons[tool].height()))
                self.assertGreaterEqual(panel.y(), below.y(), "the panel opens under its button")
                offered = [button.text() for button in panel.buttons.values() if not button.text().startswith("Play")]
                expected = [entry[1] for entry in TOOL_PANELS[tool] if entry and not entry[1].startswith("Play")]
                if tool == "files":
                    expected[expected.index("Export quality"):expected.index("Export quality") + 1] = [
                        "YouTube (recommended)", "Highest quality", "Smaller file"]
                self.assertEqual(offered, expected)
                widths = {button.width() for button in panel.buttons.values() if button.isVisibleTo(panel)}
                self.assertEqual(len(widths), 1, "full-width labelled buttons")
                panel.hide()
                self.assertFalse(page.tool_buttons[tool].property("open"))
        click(page.back_button)
        self.assertIs(page.views.currentWidget(), page.start_view)

    def test_play_shows_the_version_on_the_page_in_the_apps_one_player(self) -> None:
        window = self._window()
        players = self._fake_player(window)
        project = self._video(window)
        page = self._open_page(window)
        self._open_video(page, project)
        self.assertIs(page.stage.currentWidget(), page.poster_page)
        self.assertIsNone(window.video_opener.player_window, "no player is made just to show a version")
        click(page.play_button)
        player = window.video_opener.player_window
        self.assertIs(player.docked_in, page.player_page)
        self.assertIs(player.parentWidget(), page.player_page)
        self.assertTrue(player.isVisible())
        self.assertFalse(player.details_box.isVisible(), "no transcript or never-use for an edit")
        self.assertFalse(player.track_combo.isVisible(), "an edit has one track, the finished mix")
        self.assertEqual({action.shortcutContext() for action in player.actions()},
                         {Qt.ShortcutContext.WidgetWithChildrenShortcut}, "typing in the notes never plays or jumps")
        self.assertEqual(player.open_path(), project / "versions" / "v002" / "renders" / "preview.mp4")
        self.assertIn("Playing the preview of v002", page.playing_label.text())
        # Another page: the one player goes back to being its own window, paused, hidden.
        click(window.nav_buttons["Home"])
        self.assertIsNone(player.docked_in)
        self.assertTrue(player.isWindow())
        self.assertFalse(player.isVisible())
        self.assertEqual(player.details_box.isVisibleTo(player), True)
        self.assertEqual({action.shortcutContext() for action in player.actions()}, {Qt.ShortcutContext.WindowShortcut})
        # Back on the page, Play docks the same window again; a Play from anywhere else takes it away again.
        self._open_page(window)
        click(page.play_button)
        self.assertIs(window.video_opener.player_window, player)
        self.assertIs(player.docked_in, page.player_page)
        window.video_opener._open_internal(PlayTarget(path=self.source), None)
        self.assertIsNone(player.docked_in)
        self.assertTrue(player.isVisible() and player.isWindow())
        self.assertEqual(len(players.players), 2, "one player for the version, one for the other recording")

    def test_a_scene_of_the_strip_jumps_the_player_there_and_goes_into_the_notes(self) -> None:
        window = self._window()
        players = self._fake_player(window)
        project = self._video(window)
        page = self._open_page(window)
        self._open_video(page, project)
        self.assertEqual([block.block["name"] for block in page.scene_strip.blocks], ["Start", "Battle", "Pit stop", "Finish"])
        self.assertEqual([block.block["start"] for block in page.scene_strip.blocks], [0.0, 3.0, 4.5, 6.0])
        click(page.scene_strip.blocks[2])
        player = window.video_opener.player_window
        self.assertIs(player.docked_in, page.player_page, "a scene plays on the page")
        players.players[-1].report_loaded(9000)
        self.app.processEvents()
        self.assertIn(4500, players.players[-1].set_positions, "the player starts at the scene")
        players.players[-1].arrive()   # the picture of that moment arrives; the next seek may go
        self.app.processEvents()
        click(page.scene_strip.blocks[3])
        self.assertIn(6000, players.players[-1].set_positions, "and moves to the next one chosen")
        # The pen on a scene writes a note about it.
        click(page.scene_strip.blocks[2].pen)
        self.assertEqual([chip.text() for chip in page.chips], ["Note on: Pit stop  ✕"])
        self.assertEqual(page.feedback_edit.toPlainText(), "Pit stop: ")
        QTest.keyClicks(page.feedback_edit, "too long.")
        click(page.save_notes_button)
        saved = (project / "feedback" / "v002.md").read_text(encoding="utf-8")
        self.assertEqual(saved, "Pit stop: too long.\n\nScenes these notes are about:\n"
                                "- Pit stop: scene s04, from 0:04 to 0:06 of the video\n")
        prompt = QApplication.clipboard().text()
        self.assertIn("The operator's notes name these scenes of version 2", prompt)
        self.assertIn("- Pit stop: scene s04, from 0:04 to 0:06 of the video", prompt)
        # Back to this version later: the notes and their scene are there again, once.
        click(page.version_tabs[0])
        self.assertEqual(page.chips, [])
        click(page.version_tabs[1])
        self.assertEqual(page.feedback_edit.toPlainText(), "Pit stop: too long.")
        self.assertEqual([chip.text() for chip in page.chips], ["Note on: Pit stop  ✕"])
        click(page.chips[0])
        self.assertEqual(page.chips, [])
        self.assertEqual(page.feedback_edit.toPlainText(), "Pit stop: too long.", "the words stay")

    def test_a_double_click_on_a_version_tab_plays_it(self) -> None:
        # UI rules section 8: double-click plays, as it did on the versions list.
        window = self._window()
        self._fake_player(window)
        project = self._video(window, versions=2)
        render_version(project, 1, "preview", RenderOptions(ffmpeg=FFMPEG, ffprobe=FFPROBE, masks={}, encoder="x264",
                                                             hwaccel="none"))
        page = self._open_page(window)
        page.refresh()
        self._open_video(page, project)
        QTest.mouseDClick(page.version_tabs[0], Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertEqual(page.version_number, 1)
        self.assertEqual(window.video_opener.player_window.open_path(),
                         project / "versions" / "v001" / "renders" / "preview.mp4")
        self.assertEqual(page.play_feedback.text(), "Playing")

    def test_the_status_words_of_a_video_and_what_a_run_changed(self) -> None:
        from media_manglers_workbench.ai_video_editor import AiVideoEditorPage  # noqa: PLC0415
        from media_manglers_workbench.ai_video_editor_parts import continue_text, status_of  # noqa: PLC0415

        prepared = {"analysed": True, "versions": []}
        self.assertEqual(status_of(prepared, "prepare"), ("Getting ready…", "active"))
        self.assertEqual(continue_text(prepared, "prepare", 40), "Getting it ready for your AI agent: 40%.")
        self.assertEqual(status_of(prepared), ("Waiting for your AI agent", "complete_with_warnings"))
        version = {"version": 3, "label": "v003", "files": [], "exported": False}
        self.assertEqual(status_of({"analysed": True, "versions": [version]}), ("Needs a preview", "complete_with_warnings"))
        self.assertEqual(continue_text({"analysed": True, "versions": [version]}), "Version 3 has no preview yet.")
        said = AiVideoEditorPage._success_text
        report = {"technical_check": {"passed": True}, "render": {"scenes_rendered": 1, "scenes_reused": 14}}
        self.assertEqual(said("preview", report, {"label": "v003", "preview": True}),
                         "Preview ready: press Play the preview. It replaced the earlier preview of v003 "
                         "(1 scene rendered, 14 reused).")
        self.assertEqual(said("preview", report, {"label": "v003", "preview": False}),
                         "Preview ready: press Play the preview. It is the first preview of v003 (1 scene rendered, 14 reused).")
        self.assertEqual(said("export", {"export": "C:/x/race-v003.mp4"}, {"exported": True}),
                         "Exported and checked: race-v003.mp4 (replaced the earlier export). Nothing was uploaded.")

    def test_new_versions_appear_by_themselves_and_typed_notes_are_kept(self) -> None:
        window = self._window()
        project = self._video(window, versions=1)
        page = self._open_page(window)
        self._open_video(page, project)
        self.assertTrue(page.watch_timer.isActive(), "the page looks for new versions while it is shown")
        page.feedback_edit.setFocus()
        QTest.keyClicks(page.feedback_edit, "Half a thought")
        add_version(project, {"schema": SCHEMA, "source": str(self.source), "source_layout": LAYOUT,
                              "tracks": {"voice": 0, "game": 1},
                              "scenes": [{"id": "s01", "beat": "start", "reason": "t", "in": 1.0, "out": 4.0}]},
                    source_duration=12.0, audio_streams=2)
        page._watch_disk()
        self.assertEqual([tab.text() for tab in page.version_tabs], ["v001", "v002 · newest"])
        self.assertEqual(page.version_number, 1, "the version being written about stays chosen")
        self.assertEqual(page.feedback_edit.toPlainText(), "Half a thought", "nothing typed is lost")
        click(page.back_button)
        self.assertEqual(page._cards[str(project)].count_label.text(), "2 versions")
        # Opened again from its card, the video shows its newest version; the words wait on v001.
        click(page._cards[str(project)])
        self.assertEqual(page.version_number, 2)
        self.assertTrue(page.version_tabs[1].isChecked())
        self.assertEqual(page.feedback_edit.toPlainText(), "")
        click(page.version_tabs[0])
        self.assertEqual(page.feedback_edit.toPlainText(), "Half a thought")
        click(window.nav_buttons["Home"])
        self.assertFalse(page.watch_timer.isActive(), "it stops looking when the page is left")

    def test_a_prepare_that_ends_while_another_video_is_open_leaves_that_video_alone(self) -> None:
        # The review of 236: the page used to jump to the prepared video when the run ended, and write
        # that video's notes over the words being typed for another.
        window = self._window(evidence_track_roles="1=game,2=narration")
        first = self._video(window, "race", preview=False)
        second = self._video(window, "other", versions=1)
        page = self._open_page(window)
        self._open_video(page, first)
        self.assertEqual(window.app_settings["race_video_budget"], "standard")
        self._choose(page, "settings", "AI budget")
        self._wait_for_tracks(page)
        self.assertEqual(page.budget_combo.currentText(), "Light", "the budget this video was prepared with")
        click(page.prepare_button)
        self.assertTrue(page.running)
        click(page.back_button)
        click(page._cards[str(second)])
        self.assertEqual(page.export_button.text(), APP_LABELS["approve"], "the other video is not exporting")
        page.feedback_edit.setFocus()
        QTest.keyClicks(page.feedback_edit, "Notes for the other video")
        self._wait(page)
        self.assertEqual(page.current_project()["folder"], str(second))
        self.assertEqual(page.feedback_edit.toPlainText(), "Notes for the other video")
        self.assertTrue(page.status_sentence.text().startswith("race: Ready for the AI editor"),
                        page.status_sentence.text())
        self.assertFalse(page.mask_warning.isVisible(), "the warning is about the video prepared")
        self.assertEqual(window.app_settings["race_video_budget"], "standard",
                         "preparing a video again leaves the budget for a new video alone")
        click(page.back_button)
        click(page._cards[str(first)])
        self.assertTrue(page.mask_warning.isVisible(), "no masks were drawn: said on the video, over its player")
        self.assertIs(page.stage.currentWidget(), page.poster_page)

    def test_a_fresh_edit_started_while_a_version_plays_stops_the_player(self) -> None:
        window = self._window()
        players = self._fake_player(window)
        project = self._video(window)
        page = self._open_page(window)
        self._open_video(page, project)
        click(page.play_button)
        player = window.video_opener.player_window
        with patch("media_manglers_workbench.ai_video_editor.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.Yes):
            self._choose(page, "prompt", "Start a fresh edit")
        self.assertIs(page.stage.currentWidget(), page.empty_page, "the fresh edit has no version yet")
        self.assertIsNone(player.docked_in, "nothing plays out of sight")
        self.assertFalse(player.isVisible())
        self.assertGreater(players.players[-1].pause_calls, 0)

    def test_a_file_played_from_the_files_list_keeps_playing_through_a_refresh(self) -> None:
        window = self._window()
        players = self._fake_player(window)
        project = self._video(window)
        renders = project / "versions" / "v002" / "renders"
        (renders / "my-own-cut.mp4").write_bytes((renders / "preview.mp4").read_bytes())
        page = self._open_page(window)
        page.refresh()
        self._open_video(page, project)
        self._choose(page, "files", "This version's files")
        rows = [page.files_dialog.table.item(row, 0).text() for row in range(page.files_dialog.table.rowCount())]
        page.files_dialog.table.selectRow(rows.index("my-own-cut.mp4"))
        click(page.files_dialog.play_button)
        page.files_dialog.close()
        pauses = players.players[-1].pause_calls
        page.refresh()
        self.assertIs(page.stage.currentWidget(), page.player_page)
        self.assertEqual(window.video_opener.player_window.open_path(), renders / "my-own-cut.mp4")
        self.assertEqual(players.players[-1].pause_calls, pauses, "a refresh never stops what plays")

    def test_render_a_preview_lets_go_of_the_video_playing_first(self) -> None:
        # Windows cannot replace a file a player holds open.
        window = self._window()
        self._fake_player(window)
        project = self._video(window)
        page = self._open_page(window)
        self._open_video(page, project)
        click(page.play_button)
        player = window.video_opener.player_window
        self.assertIsNotNone(player.open_path())
        self._choose(page, "files", "Render a preview")
        self.assertIsNone(player.open_path(), "the preview's file is let go before it is made again")
        self._wait(page)
        self.assertIn("It replaced the earlier preview of v002", page.status_sentence.text())

    def test_the_strip_keeps_the_chosen_scene_through_a_refresh(self) -> None:
        window = self._window()
        self._fake_player(window)
        project = self._video(window)
        page = self._open_page(window)
        self._open_video(page, project)
        click(page.scene_strip.blocks[1])
        page.refresh()
        self.assertTrue(page.scene_strip.blocks[1].isChecked())
        self.assertEqual(page.scene_strip.chosen["name"], "Battle")

    def test_see_the_prompt_first_belongs_to_the_video_it_was_opened_for(self) -> None:
        window = self._window()
        first = self._video(window, "race", versions=0)
        second = self._video(window, "other", versions=0)
        page = self._open_page(window)
        self._open_video(page, first)
        self._choose(page, "prompt", "See the prompt first")
        self.assertTrue(page.prompt_dialog.isVisible())
        click(page.back_button)
        self.assertFalse(page.prompt_dialog.isVisible(), "it goes with its video")
        click(page._cards[str(second)])
        self._choose(page, "prompt", "See the prompt first")
        self.assertIn(str(second / "analysis" / "digest.md"), page.prompt_dialog.editor.toPlainText())
        click(page.prompt_dialog.tool_choice.buttons["codex"])
        self.assertIn(str(second / "analysis" / "digest.md"), page.prompt_dialog.editor.toPlainText())

    # Issue 236 items ------------------------------------------------------------------------

    def test_choosing_a_recording_shows_what_the_raw_bin_and_inbox_know(self) -> None:
        # Item 1: the Raw bin's guess, your speech, idle time, your decision and labels, read without
        # changing the library; the Windows file picker is still one click away.
        library = Path(tempfile.mkdtemp(dir=self.root))
        with patch.dict(os.environ, {raw_bin_library.LIBRARY_ROOT_ENV: str(library)}):
            connection = raw_bin_library.connect(library, backup=False)
            with connection:
                connection.execute(
                    "INSERT INTO recordings (recording_id, size_bytes, duration_seconds, guess, guess_reason, speech_seconds,"
                    " idle_share, decision, first_seen_utc) VALUES (1, 100, 2700, 'keep_likely', 'lots of talk', 750,"
                    " 0.08, 'keep', '2026-10-20T00:00:00Z')")
                connection.execute(
                    "INSERT INTO locations (recording_id, path, path_key, root_key, size_bytes, modified_ns,"
                    " first_seen_utc, last_seen_utc) VALUES (1, ?, ?, 'root', 100, 0, 'x', 'x')",
                    (str(self.titled), raw_bin_library.path_key(self.titled)))
                label = connection.execute("SELECT label_id FROM labels WHERE name = 'YouTube'").fetchone()[0]
                connection.execute("INSERT INTO recording_labels VALUES (1, ?)", (label,))
            connection.close()
            before = (library / raw_bin_library.DATABASE_NAME).stat().st_mtime_ns
            window = self._window()
            page = self._open_page(window)
            seen = {}

            def answer() -> None:
                dialog = page.choose_dialog
                seen["rows"] = [[dialog.table.item(0, column).text() for column in range(dialog.table.columnCount())]]
                dialog.table.selectRow(0)
                click(dialog.choose_button)

            QTimer.singleShot(200, answer)
            click(page.make_video_button)
            self._wait_for_tracks(page)
            self.assertEqual(seen["rows"], [["titled.mkv", "45 min", "Raw bin: Keep likely (12 min of your speech, 8% idle) · "
                                                                    "you marked it Keep · labels: YouTube"]])
            self.assertEqual(page.recording, self.titled)
            self.assertTrue(page.knowledge_label.isVisible())
            self.assertEqual(page.knowledge_label.text(), "What the app knows about it: Raw bin: Keep likely (12 min of "
                                                         "your speech, 8% idle) · you marked it Keep · labels: YouTube")
            self.assertEqual((library / raw_bin_library.DATABASE_NAME).stat().st_mtime_ns, before,
                             "the library is only read")

            def browse() -> None:
                click(page.choose_dialog.browse_button)

            QTimer.singleShot(200, browse)
            with patch("media_manglers_workbench.ai_video_editor.QFileDialog.getOpenFileName",
                       return_value=(str(self.source), "")) as picker:
                click(page.choose_button)
            picker.assert_called_once()
            self._wait_for_tracks(page)
            self.assertEqual(page.recording, self.source)
            self.assertFalse(page.knowledge_label.isVisible(), "the Raw bin knows nothing about this one")

    def test_a_replaced_recording_s_old_decision_is_not_shown_for_the_one_there_now(self) -> None:
        # 268: another recording saved under a name the Raw bin knew is a new entry; the old one keeps its
        # decision and labels and is Missing, and is not what the app knows about the file there now.
        from tests.test_raw_bin_library import HearingTranscriber, make_recording  # noqa: PLC0415

        library = Path(tempfile.mkdtemp(dir=self.root))
        raw = self.root / "raw"
        path = make_recording(raw / "session.mkv")

        def scan() -> None:
            result = raw_bin_library.scan(raw_bin_library.ScanOptions(
                folders=[str(raw)], ffmpeg=FFMPEG, ffprobe=FFPROBE, transcriber=HearingTranscriber({2}),
                library_root=str(library), cache_folder=str(self.root / "cache"), stable_after_seconds=0))
            self.assertEqual(result["status"], "completed", result)

        with patch.dict(os.environ, {raw_bin_library.LIBRARY_ROOT_ENV: str(library)}):
            scan()
            connection = raw_bin_library.connect(library)
            first = raw_bin_library.list_recordings(connection)[0]["recording_id"]
            raw_bin_library.set_decision(connection, [first], raw_bin_library.DECISION_KEEP)
            raw_bin_library.set_label(connection, [first], "YouTube", True)
            connection.close()
            path.unlink()
            make_recording(path, seconds=200, game_idle=(10, 40))
            scan()
            window = self._window()
            page = self._open_page(window)
            seen = {}

            def answer() -> None:
                dialog = page.choose_dialog
                seen["rows"] = [dialog.table.item(row, 0).text() for row in range(dialog.table.rowCount())]
                dialog.table.selectRow(0)
                click(dialog.choose_button)

            QTimer.singleShot(200, answer)
            click(page.make_video_button)
            self._wait_for_tracks(page)
            self.assertEqual(seen["rows"], ["session.mkv"], "a Missing recording is not offered")
            self.assertEqual(page.recording, path)
            text = page.knowledge_label.text()
            self.assertTrue(page.knowledge_label.isVisible(), text)
            self.assertIn("Raw bin:", text)
            self.assertNotIn("you marked it Keep", text, "the old recording's decision is not this one's")
            self.assertNotIn("YouTube", text, "nor its labels")

    def test_the_ai_budget_says_what_it_changes(self) -> None:
        # Item 2.
        window = self._window()
        page = self._open_page(window)
        self._choose_recording(page, self.source)
        self.assertTrue(page.budget_words.isVisible())
        for choice, words in (("Light", "every 15 seconds"), ("Thorough", "every 5 seconds")):
            with self.subTest(choice=choice):
                from tests.qt_input import choose_in_combo  # noqa: PLC0415

                choose_in_combo(page.budget_combo, choice)
                self.assertTrue(page.budget_words.text().startswith(f"{choice}: Prepare takes a picture of the race {words}"))
        self.assertIn("use more of your AI plan", page.budget_intro.text())

    def test_see_the_prompt_first_shows_it_ready_to_change_with_its_introduction_apart(self) -> None:
        # Item 3.
        window = self._window()
        project = self._video(window, versions=0)
        page = self._open_page(window)
        self._open_video(page, project)
        self._choose(page, "prompt", "See the prompt first")
        dialog = page.prompt_dialog
        self.assertTrue(dialog.isVisible())
        made = dialog.editor.toPlainText()
        self.assertTrue(made.startswith("MODEL: Opus 5.5"))
        self.assertIn("Paste it into Claude Code", dialog.intro.text())
        self.assertNotIn(dialog.intro.text()[:40], made, "the introduction is not part of the prompt")
        self.assertFalse(dialog.notes_check.isVisible(), "no notes saved for this video")
        dialog.editor.moveCursor(dialog.editor.textCursor().MoveOperation.End)
        QTest.keyClicks(dialog.editor, "Keep the pit stop.")
        click(dialog.copy_button)
        self.assertEqual(QApplication.clipboard().text(), made + "Keep the pit stop.")
        self.assertEqual(dialog.feedback.text(), "Copied with your changes. Paste it into Claude Code.")
        click(dialog.reset_button)
        self.assertEqual(dialog.editor.toPlainText(), made)
        click(dialog.tool_choice.buttons["codex"])
        self.assertTrue(dialog.editor.toPlainText().startswith("MODEL: GPT-6.1 Sol"))
        self.assertIn("Paste it into Codex", dialog.intro.text())

    def test_the_story_and_the_review_open_short_summary_first(self) -> None:
        # Item 5.
        window = self._window()
        project = self._video(window)
        folder = project / "versions" / "v002"
        (folder / "review.md").write_text("# Review of v002\n\n## In short\n\nGood to watch.\n\n## What works\n\nThe start."
                                          "\n\n## What changed\n\n- Shorter start.\n\n## Concerns\n\n- The end is abrupt.",
                                          encoding="utf-8")
        (folder / "technical.md").write_text("# Technical\n\nThe check passed at -14.0 LUFS.", encoding="utf-8")
        page = self._open_page(window)
        page.refresh()
        self._open_video(page, project)
        self._choose(page, "story", "The editor's own review")
        reader = page.review_reader
        summary = reader.summary_view.toPlainText()
        for words in ("In short", "Good to watch.", "Key changes", "Shorter start.", "Concerns", "The end is abrupt."):
            self.assertIn(words, summary)
        self.assertNotIn("The start.", summary, "the rest is one click away")
        self.assertFalse(reader.full_view.isVisible())
        click(reader.full_button)
        self.assertTrue(reader.full_view.isVisible())
        self.assertIn("The start.", reader.full_view.toPlainText())
        click(reader.technical_button)
        self.assertIn("-14.0 LUFS", reader.technical_view.toPlainText())
        reader.close()
        self._choose(page, "story", "The story")
        self.assertIn("The driver holds second all race.", page.story_reader.summary_view.toPlainText())
        self.assertFalse(page.story_reader.technical_button.isVisible())

    def test_a_versions_files_say_what_play_opens_and_what_the_agent_made(self) -> None:
        # Item 6.
        window = self._window()
        self._fake_player(window)
        project = self._video(window, label="claude-opus-5.5")
        renders = project / "versions" / "v002" / "renders"
        (renders / "preview-peak-repair.mp4").write_bytes((renders / "preview.mp4").read_bytes())
        page = self._open_page(window)
        page.refresh()
        self._open_video(page, project)
        self.assertEqual(page.playing_label.text(), "Press Play on the picture to watch v002 here.")
        self.assertEqual(page.files_summary.text(), "v002 has: Preview ✓ · Final — · Export — · 1 video your AI agent made")
        self.assertEqual(page.play_button.text(), "Play the preview")
        self.assertFalse(page.play_preview_button.isVisible(), "there is no final to play instead")
        self._choose(page, "files", "This version's files")
        dialog = page.files_dialog
        rows = [[dialog.table.item(row, column).text() for column in range(3)] for row in range(dialog.table.rowCount())]
        self.assertEqual(rows, [
            ["preview.mp4", "Preview: a quick, smaller render to watch", "The app"],
            ["race-v002-claude-opus-5.5-preview.mp4", "A readable name for the same render (the same file as the preview)",
             "The app"],
            ["preview-peak-repair.mp4", "Made by your AI agent itself", "Your AI agent"],
        ])
        self.assertIn("Render a preview makes this version's preview again and replaces the one there",
                      dialog.actions_words.text())
        self.assertIn("v002 has no export yet: it will be made at YouTube (recommended).", dialog.actions_words.text())
        dialog.table.selectRow(2)
        click(dialog.play_button)
        self.assertEqual(window.video_opener.player_window.open_path(), renders / "preview-peak-repair.mp4")
        self.assertEqual(page.playing_label.text(), "Playing preview-peak-repair.mp4, a video your AI agent made itself.")
        dialog.close()
        # With a final, the picture offers it first, and the preview beside it; while one plays, the other is
        # one click away under Files.
        self._with_a_final(window, project)
        click(page.back_button)
        click(page._cards[str(project)])
        self.assertEqual(page.play_button.text(), "Play the final (full quality)")
        self.assertEqual(page.play_preview_button.text(), "Play the preview (quick, smaller)")
        click(page.play_button)
        self.assertEqual(window.video_opener.player_window.open_path(), renders / "final.mp4")
        self.assertTrue(page.playing_label.text().startswith("Playing the final of v002 (1920×1080): the full-quality"))
        self._choose(page, "files", "Play the preview (quick, smaller)")
        self.assertEqual(window.video_opener.player_window.open_path(), renders / "preview.mp4")
        self.assertEqual(page.playing_label.text(), "Playing the preview of v002 (1280×720, 30 fps): a quick, smaller "
                                                    "render to judge the edit.")
        self.assertEqual(page.actions_feedback.text(), "Playing")

    # The fix round after hand testing (236) -------------------------------------------------------

    def test_the_play_choices_are_on_the_picture_and_play_at_once(self) -> None:
        # Finding 2: "Play the final instead" sat at the bottom, far from Play, and before Play it only
        # changed a line of text. Finding 3: on a video with no final the choices were confusing.
        window = self._window()
        self._fake_player(window)
        project = self._video(window)
        renders = self._with_a_final(window, project)
        page = self._open_page(window)
        self._open_video(page, project)
        self.assertIs(page.stage.currentWidget(), page.poster_page)
        picture = page.poster.picture_rect()
        for button in (page.play_button, page.play_preview_button):
            with self.subTest(button=button.text()):
                self.assertTrue(button.isVisible())
                place = QRect(button.mapTo(page.poster, QPoint(0, 0)), button.size())
                self.assertTrue(picture.contains(place), f"{button.text()} is on the picture")
        self.assertTrue(page.play_button.property("primary"), "the final is the main choice")
        self.assertFalse(page.play_preview_button.property("primary"))
        self.assertEqual(page.poster_chip.text(), "v002 · 0:08 · final 1920×1080 · preview 1280×720")
        self.assertEqual([button for button in page.findChildren(QAbstractButton)
                          if button.text() in ("Play the final instead", "Play the preview instead")], [],
                         "no switch far from the picture")
        click(page.play_preview_button)
        player = window.video_opener.player_window
        self.assertIs(player.docked_in, page.player_page, "it plays at once, on the page")
        self.assertEqual(player.open_path(), renders / "preview.mp4")
        self.assertIn("Playing the preview of v002 (1280×720", page.playing_label.text())
        # A version with only a preview offers just "Play the preview".
        click(page.version_tabs[0])
        self.assertEqual(page.version_number, 1)
        self.assertIsNone(player.docked_in, "another version waits on its own picture")
        self.assertFalse(page.play_button.isVisible(), "v001 has no video yet")
        self.assertEqual(page.no_video_label.text(), "v001 has no video yet.")
        self.assertTrue(page.poster_render_button.isVisible())
        click(page.version_tabs[1])
        render_version(project, 1, "preview", RenderOptions(ffmpeg=FFMPEG, ffprobe=FFPROBE, masks={}, encoder="x264",
                                                             hwaccel="none"))
        page.refresh()
        click(page.version_tabs[0])
        self.assertEqual(page.play_button.text(), "Play the preview")
        self.assertFalse(page.play_preview_button.isVisible())

    def test_a_video_with_no_version_says_so_and_offers_the_one_next_step(self) -> None:
        # Finding 4: on a video waiting for the AI agent there was nothing to play and no clear next step.
        window = self._window()
        waiting = self._video(window, "waiting", versions=0)
        not_prepared = create_project(self.root / "out", self.titled, "new")
        page = self._open_page(window)
        page.refresh()
        self._open_video(page, waiting)
        self.assertIs(page.stage.currentWidget(), page.empty_page, "never an empty player")
        self.assertEqual(page.empty_title.text(), "Your AI agent hasn't made a version yet")
        self.assertTrue(page.empty_copy_button.isVisible())
        self.assertFalse(page.empty_prepare_button.isVisible())
        self.assertIn("version 1 then appears here by itself", page.empty_words.text())
        self.assertFalse(page.scene_strip.isVisible())
        self.assertFalse(page.export_button.isVisible(), "nothing to approve before the first version")
        self.assertTrue(page.toolbar.isVisible(), "the toolbar is there for every video")
        # A choice that cannot be used yet is greyed out, and its panel says why in words.
        click(page.tool_buttons["story"])
        self.assertFalse(page.tool_actions["story"].isEnabled())
        self.assertEqual(page.tool_panels["story"].note.text(), "Your AI agent has not made a version of this video yet.")
        self.assertTrue(page.tool_panels["story"].note.isVisible())
        page.tool_panels["story"].hide()
        click(page.empty_copy_button)
        self.assertIn(str(waiting / "analysis" / "digest.md"), QApplication.clipboard().text())
        self.assertEqual(page.empty_feedback.text(), "Copied. Paste it into Claude Code.")
        click(page.back_button)
        click(page._cards[str(not_prepared)])
        self.assertIs(page.stage.currentWidget(), page.empty_page)
        self.assertTrue(page.empty_prepare_button.isVisible())
        self.assertEqual(page.empty_prepare_button.text(), "Prepare for the AI editor…")
        self.assertFalse(page.empty_copy_button.isVisible())
        self.assertIn("writes down what you said", page.empty_words.text())
        self._wait_for_tracks(page)
        click(page.empty_prepare_button)
        self.assertIs(page.stage.currentWidget(), page.step_page, "the first step: its tracks and its Prepare")
        self.assertTrue(page.prepare_button.isVisible())
        click(page.back_to_player_button)
        self.assertIs(page.stage.currentWidget(), page.empty_page)

    def test_the_picture_and_the_player_fill_their_box(self) -> None:
        # Finding 5: the picture floated small in a large empty box.
        window = self._window()
        self._fake_player(window)
        project = self._video(window)
        page = self._open_page(window)
        self._open_video(page, project)
        for size in ((1280, 800), (1600, 1000)):
            with self.subTest(size=size):
                window.resize(*size)
                QTest.qWait(80)
                box, picture = page.poster.rect(), page.poster.picture_rect()
                self.assertTrue(picture.width() == box.width() or picture.height() == box.height(),
                                f"the picture {picture.getRect()} fills its box {box.getRect()} one way")
                self.assertTrue(box.contains(picture))
                overlay = page.poster.overlay.geometry()
                self.assertTrue(picture.contains(overlay), "what is on the picture stays on it")
        click(page.play_button)
        QTest.qWait(80)
        player = window.video_opener.player_window
        self.assertIs(player.parentWidget(), page.player_page)
        for size in ((1280, 800), (1600, 1000)):
            with self.subTest(playing=size):
                window.resize(*size)
                QTest.qWait(80)
                geometry = player.geometry()
                self.assertTrue(page.player_page.rect().contains(geometry))
                self.assertEqual(geometry.height(), page.player_page.height(), "the player takes the box's height")
                self.assertLessEqual(abs((page.player_page.width() - geometry.right() - 1) - geometry.left()), 1, "centred")
                # The walk found the picture small while playing: its buttons had wrapped onto more lines.
                self.assertGreaterEqual(geometry.width(), page.player_page.controls_width(player), "the buttons never wrap")
                # The walk found the time readout alone on a line under the buttons: the player's margins counted.
                self.assertEqual(player.time_label.y(), player.step_back_button.y(), "the time is on the buttons' line")
                self.assertGreaterEqual(player.video_stack.height(), PLAYING_PICTURE_LEAST, "the picture is never small")

    def test_pressing_play_never_scrolls_the_page(self) -> None:
        # The walk on the real screen at 150%: the Play pressed went out of sight with the picture, Qt handed the
        # keyboard to the player's next control and scrolled the page there, taking the title and the toolbar
        # out of sight.
        window = self._window()
        self._fake_player(window)
        project = self._video(window)
        page = self._open_page(window)
        self._open_video(page, project)
        window.resize(1280, 640)
        QTest.qWait(80)
        bar = window.page_stack.scroll_for(page).verticalScrollBar()
        self.assertGreater(bar.maximum(), 0, "the page is taller than the window here")
        point = widget_point(page.play_button)
        before = bar.value()
        QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        QTest.qWait(80)
        self.assertIs(page.stage.currentWidget(), page.player_page)
        self.assertEqual(bar.value(), before, "the title and the toolbar stay where they were")

    def test_a_video_opens_at_its_top_and_back_returns_to_the_list_where_it_was(self) -> None:
        # The walk on the real screen at 150%: a card reached by scrolling opened the video scrolled down, its
        # name and toolbar out of sight.
        window = self._window()
        # Versions without a preview: the video's page is taller than the window too, and nothing is rendered.
        projects = [self._video(window, f"race-{number}", versions=1, preview=False) for number in range(8)]
        page = self._open_page(window)
        window.resize(1280, 640)
        QTest.qWait(80)
        bar = window.page_stack.scroll_for(page).verticalScrollBar()
        self.assertGreater(bar.maximum(), 0, "the list is taller than the window here")
        # The card lowest in the list: the list is scrolled to it first, as the operator does.
        card = max((page._cards[str(project)] for project in projects), key=lambda item: item.mapTo(page, QPoint()).y())
        point = widget_point(card)
        listed = bar.value()
        self.assertGreater(listed, 0, "the list was scrolled to reach the card")
        QTest.mouseClick(card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        self.assertIs(page.views.currentWidget(), page.video_view)
        QTest.qWait(50)
        self.assertGreater(bar.maximum(), 0, "the video's page is taller than the window too")
        self.assertEqual(bar.value(), 0, "the video's name and toolbar are in sight")
        click(page.back_button)
        QTest.qWait(50)
        self.assertEqual(bar.value(), listed, "back where the list was left")

    def test_a_toolbar_panel_stays_inside_the_window(self) -> None:
        # The walk at 150%: Files sits near the window's right edge, and its panel hung past it.
        from media_manglers_workbench.ai_video_editor_parts import ToolbarButton, ToolPanel  # noqa: PLC0415

        holder = QWidget()
        holder.setGeometry(100, 100, 420, 300)
        button = ToolbarButton("Files", "files", holder)
        button.setGeometry(340, 10, 70, 30)
        panel = ToolPanel("Files", holder)
        panel.add_button("refresh", "Refresh", lambda: None)
        holder.show()
        QTest.qWait(50)
        panel.open_under(button)
        self.assertTrue(panel.isVisible())
        self.assertLessEqual(panel.frameGeometry().right(), holder.frameGeometry().right(), "not past its right edge")
        self.assertGreaterEqual(panel.y(), button.mapToGlobal(QPoint(0, button.height())).y(), "under its button")
        panel.hide()
        holder.close()

    def test_the_pen_on_a_scene_already_in_the_notes_goes_on_at_the_end_of_its_line(self) -> None:
        # The walk at 150%: the words typed after the pen on a scene already noted went in front of the notes.
        window = self._window()
        self._fake_player(window)
        project = self._video(window)
        page = self._open_page(window)
        self._open_video(page, project)
        strip, edit = page.scene_strip, page.feedback_edit
        click(strip.blocks[1].pen)
        QTest.keyClicks(edit, "too long")
        click(strip.blocks[2].pen)
        QTest.keyClicks(edit, "cut it")
        click(strip.blocks[1].pen)
        QTest.keyClicks(edit, ", really")
        self.assertEqual(edit.toPlainText(), "Battle: too long, really\nPit stop: cut it")
        self.assertEqual([chip.text() for chip in page.chips], ["Note on: Battle  ✕", "Note on: Pit stop  ✕"])

    def test_the_scenes_stay_whole_when_the_text_size_changes(self) -> None:
        # The walk at 150%: the scenes grew with the text size after the strip had measured them, and their
        # length line was cut off under the sideways scroll bar.
        window = self._window()
        project = self._video(window)
        page = self._open_page(window)
        strip = page.scene_strip
        try:
            for size in (150, 100):
                with self.subTest(text_size=size):
                    # The text size first, then the video opened, as on the real screen.
                    window.set_text_size(size)
                    QTest.qWait(100)
                    self._open_video(page, project)
                    QTest.qWait(100)
                    for block in strip.blocks:
                        self.assertGreaterEqual(block.height(), block.sizeHint().height(), block.block["name"])
                        self.assertGreaterEqual(strip.scroll.viewport().height(), block.height(),
                                                f"{block.block['name']} is whole, not cut off at the bottom")
        finally:
            window.set_text_size(100)

    def test_the_play_choices_stay_round_at_every_text_size(self) -> None:
        # The walk at 150%: the main play choice came out square; a corner wider than half the button is dropped.
        import re  # noqa: PLC0415

        from media_manglers_workbench import theme  # noqa: PLC0415

        for size in (100, 110, 125, 150):
            sheet = theme.build_stylesheet("dark", size)
            for name in ("posterPlay", "posterPlaySecondary"):
                with self.subTest(text_size=size, button=name):
                    rule = re.search(r"QPushButton#" + name + r" [{]([^}]*)[}]", sheet).group(1)
                    number = lambda key: int(re.search(key + r": (\d+)px", rule).group(1))  # noqa: E731
                    border = 2 if "border: 1px" in rule else 0
                    height = number("min-height") + 2 * number("padding") + border
                    self.assertLessEqual(2 * number("border-radius"), height)

    def test_scene_names_are_never_cut_and_each_scene_has_a_pen(self) -> None:
        # Finding 5: names were cut off ("Conseq…", "Incid…") with an empty block at the end of the strip.
        window = self._window()
        self._fake_player(window)
        project = create_project(self.root / "out", self.source, "many")
        beats = ("set-up", "conflict", "consequence", "start", "rain race", "pay-off", "pit stop", "grind",
                 "incident", "white flag", "chase", "finish", "verdict")
        scenes = [{"id": f"s{index + 1:02d}", "beat": beat, "reason": "test", "in": 0.2 + index * 0.8,
                   "out": 0.9 + index * 0.8, "view": "center", "audio": {"voice": 1.0, "game": 0.5}}
                  for index, beat in enumerate(beats)]
        add_version(project, {"schema": SCHEMA, "source": str(self.source), "source_layout": LAYOUT,
                              "tracks": {"voice": 0, "game": 1}, "scenes": scenes}, source_duration=12.0, audio_streams=2)
        (project / "analysis" / "analysis.json").write_text(json.dumps({"settings": {"budget": "light"}}), encoding="utf-8")
        page = self._open_page(window)
        page.refresh()
        self._open_video(page, project)
        strip = page.scene_strip
        self.assertEqual([block.block["name"] for block in strip.blocks],
                         ["Set-up", "Conflict", "Consequence", "Start", "Rain race", "Pay-off", "Pit stop", "Grind",
                          "Incident", "White flag", "Chase", "Finish", "Verdict"], "one block per scene, none empty")
        self.assertEqual(strip.HINT, "The story, scene by scene. Click a scene to jump there. Right-click, or the pen on "
                                     "a scene, to write a note about it.")
        QTest.qWait(50)   # as the screen shows it, once the window has been laid out
        for block in strip.blocks:
            with self.subTest(scene=block.block["name"]):
                self.assertGreaterEqual(block.width(), block.sizeHint().width(), "as wide as its words")
                self.assertTrue(block.pen.isVisible())
                self.assertFalse(block.pen.icon().isNull())
        # Too many to fit: the strip scrolls sideways instead of squeezing them, and the wheel scrolls it.
        window.resize(1280, 800)
        QTest.qWait(80)
        bar = strip.scroll.horizontalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        self.assertGreaterEqual(strip.scroll.viewport().height(), strip.blocks[0].height(), "the bar never covers them")
        click(strip.blocks[-1])
        self.assertGreater(bar.value(), 0, "a scene clicked is scrolled into sight")
        # The right-click offers the same note.
        strip.blocks[4].customContextMenuRequested.emit(QPoint(5, 5))
        self.assertEqual([action.text() for action in strip.blocks[4].menu.actions()],
                         ["Jump here", "Write a note about this scene"])
        strip.blocks[4].menu.actions()[1].trigger()
        strip.blocks[4].menu.hide()
        self.assertEqual([chip.text() for chip in page.chips], ["Note on: Rain race  ✕"])

    def test_every_control_says_what_it_did(self) -> None:
        # Fix E (UI rules section 7): every choice of the toolbar, and every button of the page, gives visible
        # feedback when it is clicked; none can look as if it did nothing.
        window = self._window()
        self._fake_player(window)
        project = self._video(window)
        self._with_a_final(window, project)
        page = self._open_page(window)
        self._open_video(page, project)
        seen: dict[str, str] = {}
        dialogs = {"see_prompt": page.prompt_dialog, "story": page.story_reader, "review": page.review_reader,
                   "files": page.files_dialog}
        with patch("media_manglers_workbench.ai_video_editor.QDesktopServices.openUrl", return_value=True), \
                patch("media_manglers_workbench.privacy_mask_editor.PrivacyMaskDialog.exec",
                      lambda dialog: seen.__setitem__("masks", dialog.windowTitle())), \
                patch("media_manglers_workbench.ai_video_editor.QMessageBox.question",
                      side_effect=lambda *args, **kwargs: seen.__setitem__("fresh", args[1]) or
                      QMessageBox.StandardButton.No):
            for tool, _words, _icon in TOOLS:
                for key, button in list(page.tool_panels[tool].buttons.items()):
                    if key.startswith("quality:") or key == "render":
                        continue
                    with self.subTest(choice=button.text()):
                        page.back_to_player()
                        self._open_video(page, project)
                        page.actions_feedback.clear()
                        page._refresh_state()
                        if not button.isEnabled():
                            # Greyed out: its panel says why, in words, where it can be read.
                            click(page.tool_buttons[tool])
                            self.assertTrue(page.tool_panels[tool].note.isVisible())
                            self.assertIn(button.toolTip(), page.tool_panels[tool].note.text())
                            page.tool_panels[tool].hide()
                            continue
                        self._choose(page, tool, button.text())
                        if key in dialogs:
                            self.assertTrue(dialogs[key].isVisible(), "its window opens")
                            dialogs[key].hide()
                        elif key in ("voice", "game", "budget"):
                            self.assertIs(page.stage.currentWidget(), page.step_page, "its box is shown")
                        elif key in ("masks", "fresh"):
                            self.assertIn(key, seen, "its window opens")
                        else:
                            self.assertTrue(page.actions_feedback.isVisible() and page.actions_feedback.text(),
                                            "it says what it did beside the toolbar")
            # Render a preview: said beside the toolbar, and the job banner shows it running.
            page.back_to_player()
            self._choose(page, "files", "Render a preview")
            self.assertEqual(page.actions_feedback.text(), "Started")
            self._wait(page)
        # The picture's buttons and the notes' buttons say what they did beside themselves.
        click(page.play_button)
        self.assertEqual(page.play_feedback.text(), "Playing")
        click(page.save_notes_codex_button)
        self.assertEqual(page.notes_feedback.text(), "No notes yet. Write what should change in the box first.")

    def test_the_brief_s_words_are_the_page_s_own(self) -> None:
        # Item 4g: every button, box and menu item the brief tells the operator to use is on the page.
        window = self._window()
        project = self._video(window)
        page = self._open_page(window)
        self._open_video(page, project)
        self._with_a_final(window, project)
        texts = {button.text() for button in page.findChildren(QPushButton)}
        texts |= {page.feedback_edit.accessibleName(), PAGE_NAME, page.videos_title.text(),
                  page.continue_card.name_label.text() if page.continue_card else ""}
        for key, words in APP_LABELS.items():
            with self.subTest(label=key):
                self.assertTrue(any(text == words or text.startswith(words) for text in texts), words)
        self.assertIn(APP_LABELS["page"], window.nav_buttons[PAGE_NAME].accessibleName() + PAGE_NAME)

    def test_at_every_text_size_every_state_fits_a_1280x800_window(self) -> None:
        # With the real Windows fonts, in a process of its own (see tests/design_fit_check_d2.py).
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        if not (fonts / "segoeui.ttf").is_file():
            self.skipTest("Segoe UI is not installed here")
        for size in (100, 150):
            with self.subTest(text_size=size):
                folder = self.root / f"fit-{size}"
                folder.mkdir()
                done = subprocess.run([sys.executable, str(REPO_ROOT / "tests" / "design_fit_check_d2.py"), str(folder),
                                       str(size)], capture_output=True, text=True, timeout=600, cwd=str(REPO_ROOT))
                lines = [line for line in done.stdout.splitlines() if line.startswith("FIT-REPORT ")]
                self.assertTrue(lines, done.stdout[-2000:] + done.stderr[-2000:])
                report = json.loads(lines[-1][len("FIT-REPORT "):])
                self.assertEqual(report["size"], [1280, 800])
                self.assertEqual(len(report["states"]), 16)
                for state, found in report["states"].items():
                    with self.subTest(state=state):
                        self.assertFalse(found["sideways"], f"{state} scrolls sideways")
                        self.assertEqual(found["cut"], [])
                        self.assertEqual(found.get("dialog_cut", []), [])


# The inherited tests are the editor page's own and run in tests/test_workbench_ai_video_editor.py.
for _name in [name for name in vars(editor_tests.AiVideoEditorPageTests) if name.startswith("test_")]:
    setattr(DesignWaveD2Tests, _name, None)


if __name__ == "__main__":
    unittest.main()
