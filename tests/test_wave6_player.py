"""220: the shared built-in player in Wave 6.

- It starts on the track the transcript came from (212), or on the track a page asks it to play,
  and never overrides a track the operator picked.
- Next / Previous speech jump between the stretches the raw bin found.
- The raw bin scan's levels show across the whole recording, and a click on them moves there. Wave 8
  (125 Part 2) turned the one strip into a lane per track, the heard one highlighted.

Built on the player test fakes, so the real window is driven through real clicks and keys.
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from tests.test_review_player import TEN_MINUTES_MS, WindowTestCase, _transcript


class StartingTrackTests(WindowTestCase):
    def test_it_starts_on_the_track_the_transcript_came_from(self) -> None:
        # 212: the transcript said Track 2, and the sound stayed on Track 1.
        window = self._window()
        player = self._open(window, loaded=False)
        player.report_loaded(titles=("Full mix", "Narration", "Game"))
        self._show_lines(window, transcribed_track=2)
        self.assertEqual(player.activeAudioTrack(), 1)
        self.assertEqual(window.track_combo.currentData(), 1)

    def test_it_says_which_track_it_really_plays_once_loaded_and_never_for_a_file_it_cannot_load(self) -> None:
        heard: list[tuple[str, int]] = []
        window = self._window()
        window.track_heard.connect(lambda path, track: heard.append((path, track)))
        player = self._open(window, loaded=False, hear_track=2)
        self.assertEqual(heard, [], "nothing is said before the recording has loaded")
        player.report_loaded(titles=("Full mix", "Narration"))
        self.assertEqual(heard[-1], (str(self._target().path), 2))
        heard.clear()
        broken = self._open(window, "other.mkv", loaded=False, hear_track=2)
        broken.fail("synthetic decode failure")
        self.assertEqual(heard, [])

    def test_a_track_to_hear_wins_and_the_operators_own_pick_is_kept(self) -> None:
        window = self._window()
        player = self._open(window, loaded=False, hear_track=3)
        player.report_loaded(titles=("Full mix", "Narration", "Game"))
        self.assertEqual(player.activeAudioTrack(), 2)
        window.show()
        window.track_combo.setFocus()
        QTest.keyClick(window.track_combo, Qt.Key.Key_Up)  # the operator picks Track 2
        self.assertEqual(player.activeAudioTrack(), 1)
        self._show_lines(window, transcribed_track=1)  # a transcript arriving later does not undo it
        self.assertEqual(player.activeAudioTrack(), 1)


class StretchTests(WindowTestCase):
    def test_next_and_previous_speech_jump_between_the_stretches(self) -> None:
        window = self._window()
        window.show()
        player = self._open(window, stretches=((30.0, 40.0), (120.0, 150.0), (300.0, 310.0)),
                            stretch_kind="speech", start_seconds=30.0)
        self.assertTrue(window.next_stretch_button.isVisible())
        self.assertEqual(window.next_stretch_button.text(), "Next speech")
        player.arrive()
        QTest.mouseClick(window.next_stretch_button, Qt.MouseButton.LeftButton)
        player.arrive()
        self.assertEqual(player.set_positions[-1], 120_000)
        QTest.mouseClick(window.next_stretch_button, Qt.MouseButton.LeftButton)
        player.arrive()
        self.assertEqual(player.set_positions[-1], 300_000)
        QTest.mouseClick(window.previous_stretch_button, Qt.MouseButton.LeftButton)
        player.arrive()
        self.assertEqual(player.set_positions[-1], 120_000)

    def test_previous_speech_goes_to_the_speech_before_the_one_playing(self) -> None:
        # The GUI run (220): a few seconds into a stretch, Previous speech went back to the start of
        # the same stretch, every time, so it never reached the speech before.
        window = self._window()
        window.show()
        player = self._open(window, stretches=((30.0, 40.0), (120.0, 150.0), (300.0, 310.0)),
                            stretch_kind="speech", start_seconds=120.0)
        player.arrive()
        player.move_to(124_000)  # four seconds into the second stretch
        QTest.mouseClick(window.previous_stretch_button, Qt.MouseButton.LeftButton)
        player.arrive()
        self.assertEqual(player.set_positions[-1], 30_000)
        player.move_to(160_000)  # after a stretch has ended, Previous goes to the one just heard
        QTest.mouseClick(window.previous_stretch_button, Qt.MouseButton.LeftButton)
        player.arrive()
        self.assertEqual(player.set_positions[-1], 120_000)

    def test_a_second_quick_press_counts_from_the_jump_not_from_where_the_player_still_says_it_is(self) -> None:
        # A long recording on a USB drive: the seek is accepted, but for a moment the player still
        # reports where it was. A second press must go on from the stretch it just jumped to.
        window = self._window()
        window.show()
        player = self._open(window, stretches=((30.0, 40.0), (120.0, 150.0), (300.0, 310.0)),
                            stretch_kind="speech", start_seconds=300.0)
        player.arrive()
        player.move_to(305_000)
        QTest.mouseClick(window.previous_stretch_button, Qt.MouseButton.LeftButton)
        player.arrive()
        self.assertEqual(player.set_positions[-1], 120_000)
        player._position = 306_000  # the old place, still reported
        QTest.mouseClick(window.previous_stretch_button, Qt.MouseButton.LeftButton)
        player.arrive()
        self.assertEqual(player.set_positions[-1], 30_000)
        player._position = 31_000
        QTest.mouseClick(window.next_stretch_button, Qt.MouseButton.LeftButton)
        player.arrive()
        self.assertEqual(player.set_positions[-1], 120_000)
        player._position = 31_000  # still the old place
        QTest.mouseClick(window.next_stretch_button, Qt.MouseButton.LeftButton)
        player.arrive()
        self.assertEqual(player.set_positions[-1], 300_000)

    def test_a_recording_without_stretches_shows_no_stretch_buttons(self) -> None:
        window = self._window()
        window.show()
        self._open(window)
        self.assertFalse(window.next_stretch_button.isVisible())
        self.assertFalse(window.previous_stretch_button.isVisible())


class OverADialogTests(WindowTestCase):
    def test_the_player_takes_the_input_while_a_modal_dialog_waits_and_lets_go_after(self) -> None:
        # 220: the Inbox's "which track is your voice" dialog is modal; its Play opens the shared
        # player on top, which must take clicks and keys until it is closed.
        from PySide6.QtWidgets import QDialog

        from media_manglers_workbench.video_open import VideoOpener

        window = self._window()
        opener = VideoOpener(self.host, player_factory=lambda _host, _opener: window)
        dialog = QDialog()
        try:
            opened = opener.open_over(dialog, self._target(hear_track=2, start_seconds=12.0))
            self.assertIs(opened, window)
            self.assertEqual(window.windowModality(), Qt.WindowModality.ApplicationModal)
            self.assertEqual(self.factory.players[-1].source().toLocalFile(), str(self._target().path).replace("\\", "/"))
            dialog.done(0)
            self.assertEqual(window.windowModality(), Qt.WindowModality.NonModal)
        finally:
            dialog.deleteLater()


class LevelStripTests(WindowTestCase):
    def test_the_raw_bins_levels_show_with_the_heard_track_highlighted_and_a_click_moves_there(self) -> None:
        from media_manglers_workbench.audio_widgets import LANE_LABEL_WIDTH

        levels = self.root / "levels.json"
        levels.write_text(json.dumps({"1": [-30.0] * 600, "2": [-20.0] * 300 + [-80.0] * 300}), encoding="utf-8")
        window = self._window()
        window.show()
        player = self._open(window, loaded=False, hear_track=2, levels_path=levels)
        player.report_loaded(duration_ms=TEN_MINUTES_MS, titles=("Full mix", "Narration"))
        lanes = window.track_lanes
        self.assertTrue(lanes.isVisible())
        self.assertEqual(lanes.tracks(), [1, 2])
        self.assertEqual(lanes._heard, 2)
        middle = LANE_LABEL_WIDTH + (lanes.width() - LANE_LABEL_WIDTH) // 2
        QTest.mouseClick(lanes, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(middle, lanes.height() // 2))
        player.arrive()
        self.assertAlmostEqual(player.set_positions[-1], TEN_MINUTES_MS // 2, delta=TEN_MINUTES_MS // 50)

    def test_no_levels_means_no_lanes(self) -> None:
        window = self._window()
        window.show()
        self._open(window)
        self.assertFalse(window.track_lanes.isVisible())
