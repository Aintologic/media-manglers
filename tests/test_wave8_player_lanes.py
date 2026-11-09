"""125 Part 2 (Wave 8): the built-in player's waveform lanes, sounds and moments.

Built on the player test fakes, so the real window is driven through real clicks and keys. The levels
come from a stand-in for the shared levels job; the moments from a real package load on a synthetic
package.
"""

from __future__ import annotations

import json
from pathlib import Path
import time

from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton, QWidget

from media_manglers.core.track_levels import Levels
from media_manglers_workbench.audio_widgets import LANE_LABEL_WIDTH, LANES_HEIGHT, _merge_moments, level_columns
from media_manglers_workbench.recording_lists import path_key
from media_manglers_workbench.review_package import Moment, source_digest
from media_manglers_workbench import review_player

# The transcript lines' full height; read from the module so the test fails, not errors, on code
# from before it was named.
LINES_HEIGHT = getattr(review_player, "LINES_HEIGHT", 150)
from media_manglers_workbench.review_player import (  # noqa: E402
    MEASURE_AGAIN_LIBRARY_TOOLTIP,
    MEASURE_AGAIN_TEXT,
    WAVEFORMS_KEY,
)

# Read from the module so this file still loads, and the test fails, on code without them.
NO_WAVEFORMS_CLIP_TEXT = getattr(review_player, "NO_WAVEFORMS_CLIP_TEXT",
                                 "No waveforms for a clip from a package. Open the recording itself to see every track.")
NO_WAVEFORMS_REVIEW_COPY_TEXT = getattr(
    review_player, "NO_WAVEFORMS_REVIEW_COPY_TEXT",
    "No waveforms for a small review copy. Open the recording itself to see every track.")
from media_manglers_workbench.theme import apply_theme
from tests.test_review_player import SESSION_ONE, SESSION_TWO, TEN_MINUTES_MS, WindowTestCase

SIX_TITLES = ("Full mix", "Narration", "Game", "Spotter", "Teammate", "Music")


def quiet_with_sound(seconds: int, *stretches: tuple[int, int]) -> list[float]:
    levels = [-70.0] * seconds
    for start, end in stretches:
        for second in range(start, end):
            levels[second] = -25.0
    return levels


class FakeLevelsService(QObject):
    """Stands in for the shared levels job: the window only asks, listens and holds."""

    levels_changed = Signal(str)
    state_changed = Signal(str)
    facts_changed = Signal(str)
    enabled = True

    def __init__(self) -> None:
        super().__init__()
        self.facts: dict[str, object] = {}
        self.levels: dict[str, Levels] = {}
        self.states: dict[str, str] = {}
        self.wanted: list[Path] = []
        self.again: list[Path] = []
        self.holds = 0

    def levels_for(self, path):
        return self.levels.get(path_key(path))

    def state_for(self, path) -> str:
        return self.states.get(path_key(path), "")

    def facts_for(self, path):
        return self.facts.get(path_key(path))

    def deliver_facts(self, path, points) -> None:
        self.facts[path_key(path)] = points
        self.facts_changed.emit(path_key(path))

    def want(self, path) -> None:
        self.wanted.append(Path(path))

    def hold(self) -> None:
        self.holds += 1

    def measure_again(self, path) -> None:
        self.again.append(Path(path))
        self.levels.pop(path_key(path), None)
        self.say(path, "Measuring the sound of every track…")

    def deliver(self, path, tracks: dict[int, list[float]], *, complete: bool = True, duration: float = 600.0,
                origin: str = "measured") -> None:
        key = path_key(path)
        self.levels[key] = Levels(tracks=tracks, duration_seconds=duration, complete=complete, origin=origin)
        self.levels_changed.emit(key)

    def say(self, path, text: str) -> None:
        key = path_key(path)
        self.states[key] = text
        self.state_changed.emit(key)


class NextSpeechTests(WindowTestCase):
    """264: Next speech and Previous speech for any recording, from what the library knows, without reopening."""

    def setUp(self) -> None:
        super().setUp()
        self.service = FakeLevelsService()
        self.host.levels_service = self.service

    def _points(self, **values):
        from media_manglers.core import speech_facts

        return speech_facts.JumpPoints(**{"track": 2, "stretches": ((100.0, 120.0), (300.0, 310.0)), "measured": True,
                                          "decided_by": "auto", **values})

    def _player(self, **values):
        window = self._window()
        window.show()
        player = self._open(window, loaded=False, **values)
        player.report_loaded(duration_ms=TEN_MINUTES_MS, titles=SIX_TITLES)
        return window, player

    def test_the_buttons_appear_without_reopening_and_page_down_jumps_without_changing_the_track(self) -> None:
        window, player = self._player()
        self.assertFalse(window.next_stretch_button.isVisible(), "nothing known yet")
        heard = window._heard_track()
        self.service.deliver_facts(self._target().path, self._points())
        self.assertTrue(window.next_stretch_button.isVisible())
        self.assertEqual(window.next_stretch_button.text(), "Next speech")
        self.assertEqual(window.previous_stretch_button.text(), "Previous speech")
        player.arrive()
        QTest.mouseClick(window.next_stretch_button, Qt.MouseButton.LeftButton)
        player.arrive()
        self.assertEqual(player.set_positions[-1], 100000)
        player.arrive()
        # Page Down and Page Up are the same actions as the buttons, wired since 220.
        self.assertEqual(window.next_stretch_action.shortcut().toString(), "PgDown")
        window.next_stretch_action.trigger()
        player.arrive()
        self.assertEqual(player.set_positions[-1], 300000)
        self.assertEqual(window.previous_stretch_action.shortcut().toString(), "PgUp")
        window.previous_stretch_action.trigger()
        player.arrive()
        self.assertEqual(player.set_positions[-1], 100000)
        self.assertEqual(window._heard_track(), heard, "a jump does not change the track you hear")

    def test_a_pages_own_stretches_stay(self) -> None:
        # The Inbox's and the wizard's answer "is this your microphone?", not "where did I speak?".
        window, player = self._player(stretches=((5.0, 8.0),), stretch_kind="speech")
        self.service.deliver_facts(self._target().path, self._points())
        player.arrive()
        QTest.mouseClick(window.next_stretch_button, Qt.MouseButton.LeftButton)
        player.arrive()
        self.assertEqual(player.set_positions[-1], 5000)

    def test_the_raw_bins_coarse_stretches_give_way_to_the_finer_ones_and_stay_so(self) -> None:
        window, player = self._player(stretches=((90.0, 400.0),), stretch_kind="speech", refine_stretches=True)
        self.service.deliver_facts(self._target().path, self._points())
        player.arrive()
        QTest.mouseClick(window.next_stretch_button, Qt.MouseButton.LeftButton)
        player.arrive()
        self.assertEqual(player.set_positions[-1], 100000)
        window.open_target(self._target(stretches=((90.0, 400.0),), stretch_kind="speech", refine_stretches=True))
        self.assertEqual(window._target.stretches, ((100.0, 120.0), (300.0, 310.0)))

    def test_a_page_opening_its_own_stretches_over_a_refined_recording_keeps_them(self) -> None:
        window, player = self._player(stretches=((90.0, 400.0),), stretch_kind="speech", refine_stretches=True)
        self.service.deliver_facts(self._target().path, self._points())
        window.open_target(self._target(stretches=((5.0, 8.0),), stretch_kind="speech"))
        self.assertEqual(window._target.stretches, ((5.0, 8.0),))
        self.service.deliver_facts(self._target().path, self._points())
        self.assertEqual(window._target.stretches, ((5.0, 8.0),), "the job finishing changes nothing")

    def test_with_no_facts_the_raw_bins_stretches_keep_working(self) -> None:
        window, player = self._player(stretches=((90.0, 400.0),), stretch_kind="speech", refine_stretches=True)
        player.arrive()
        QTest.mouseClick(window.next_stretch_button, Qt.MouseButton.LeftButton)
        player.arrive()
        self.assertEqual(player.set_positions[-1], 90000)

    def test_the_waveform_area_says_why_there_is_no_next_speech(self) -> None:
        from media_manglers.core import speech_facts

        window, _player = self._player()
        self.service.deliver(self._target().path, {1: quiet_with_sound(600, (10, 20))})
        self.service.deliver_facts(self._target().path, self._points(track=None, stretches=(), reason=speech_facts.NO_TRACK_REASON))
        self.assertFalse(window.next_stretch_button.isVisible())
        self.assertEqual(window.track_lanes._message, speech_facts.NO_TRACK_REASON)

    def test_your_voice_is_named_and_the_you_chose_line_shown_calmly(self) -> None:
        line = "You chose Track 3. The app heard your voice on Track 2. Your choice is used."
        window, _player = self._player()
        self.assertFalse(window.choice_label.isVisible())
        self.service.deliver_facts(self._target().path, self._points(track=3, decided_by="confirmed", you_chose=line))
        self.assertEqual(window.choice_label.text(), line)
        self.assertTrue(window.choice_label.isVisible())
        self.assertIsNone(window._target.voice_track, "the lanes and the track box say what they always did")
        self.assertEqual(window.choice_label.styleSheet(), "", "the status rule treats it as information")

    def test_another_recordings_facts_change_nothing_here(self) -> None:
        window, _player = self._player()
        self.service.deliver_facts(self.root / "another.mkv", self._points())
        self.assertFalse(window.next_stretch_button.isVisible())


class LanesTestCase(WindowTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.service = FakeLevelsService()
        self.host.levels_service = self.service

    def _six_lane_window(self, **values):
        window = self._window()
        window.show()
        player = self._open(window, loaded=False, **values)
        player.report_loaded(duration_ms=TEN_MINUTES_MS, titles=SIX_TITLES)
        tracks = {track: quiet_with_sound(600, (100 + track, 120 + track)) for track in range(1, 7)}
        tracks[2] = quiet_with_sound(600, (100, 120), (300, 310))
        tracks[1] = quiet_with_sound(600, (50, 60))
        self.service.deliver(self._target().path, tracks)
        return window, player

    def _press(self, window, key, modifier=Qt.KeyboardModifier.NoModifier) -> None:
        # A key reaches the window's shortcuts the way the operator's keyboard does: through the window.
        window.activateWindow()
        QTest.qWaitForWindowActive(window, 1000)
        QTest.keyClick(window.windowHandle(), key, modifier)
        self.app.processEvents()

    def _click_lane_name(self, window, track: int) -> None:
        lanes = window.track_lanes
        height = LANES_HEIGHT / len(lanes.tracks())
        QTest.mouseClick(lanes, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(10, int((track - 1) * height + height / 2)))
        self.app.processEvents()


class LanesFromTheLevelsJobTests(LanesTestCase):
    def test_a_lane_for_every_track_appears_and_fills_in_while_the_sound_is_measured(self) -> None:
        window = self._window()
        window.show()
        player = self._open(window, loaded=False, hear_track=2)
        player.report_loaded(duration_ms=TEN_MINUTES_MS, titles=SIX_TITLES)
        self.assertEqual(self.service.wanted, [self._target().path], "the player asked for this recording")
        self.assertFalse(window.track_lanes.isVisible(), "nothing to show yet")
        self.service.say(self._target().path, "Measuring the sound of every track: 10% (0:01:00 of 0:10:00).")
        self.assertTrue(window.track_lanes.isVisible())
        self.service.deliver(self._target().path, {track: [-40.0] * 60 for track in range(1, 7)}, complete=False)
        lanes = window.track_lanes
        self.assertEqual(lanes.tracks(), [1, 2, 3, 4, 5, 6])
        self.assertEqual(lanes._heard, 2)
        self.assertIn("Measuring", lanes._message)
        self.assertEqual(lanes._labels[2], "2 Narration")
        self.service.say(self._target().path, "")
        self.service.deliver(self._target().path, {track: [-40.0] * 600 for track in range(1, 7)})
        self.assertEqual(lanes._message, "")
        self.assertEqual(lanes.height(), LANES_HEIGHT, "six lanes share one fixed band")

    def _right_click_lanes_and_choose_the_first_entry(self, window) -> list[tuple[str, bool, str]]:
        seen: list[tuple[str, bool, str]] = []

        def choose_the_first_entry(menu, _where) -> None:
            action = menu.actions()[0]
            seen.append((action.text(), action.isEnabled(), action.toolTip()))
            if action.isEnabled():
                action.trigger()

        lanes = window.track_lanes
        point = QPoint(lanes.width() // 2, lanes.height() // 2)
        window._exec_menu = choose_the_first_entry
        QApplication.sendEvent(lanes, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, lanes.mapToGlobal(point)))
        self.app.processEvents()
        return seen

    def test_measure_the_sound_again_from_the_lanes_right_click(self) -> None:
        window, player = self._six_lane_window(hear_track=2, start_seconds=10.0)
        player.arrive()
        seen = self._right_click_lanes_and_choose_the_first_entry(window)
        self.assertEqual(seen[0][:2], (MEASURE_AGAIN_TEXT, True))
        self.assertEqual(self.service.again, [self._target().path])
        self.assertTrue(window.track_lanes.isVisible(), "the lanes stay, saying they are measuring")
        self.assertIn("Measuring", window.track_lanes._message)
        self.assertEqual(window.track_lanes._levels, {}, "the old waveforms are not shown as if they were new")
        self.assertEqual(player.position(), 10_000, "nothing else changes")

    def test_the_raw_bins_waveforms_are_not_measured_again_here(self) -> None:
        window = self._window()
        window.show()
        player = self._open(window, loaded=False, hear_track=2)
        player.report_loaded(duration_ms=TEN_MINUTES_MS, titles=SIX_TITLES)
        self.service.deliver(self._target().path, {track: [-40.0] * 600 for track in range(1, 7)}, origin="library")
        seen = self._right_click_lanes_and_choose_the_first_entry(window)
        self.assertEqual(seen, [(MEASURE_AGAIN_TEXT, False, MEASURE_AGAIN_LIBRARY_TOOLTIP)])
        self.assertEqual(self.service.again, [])

    def test_levels_for_another_recording_change_nothing(self) -> None:
        window = self._window()
        window.show()
        self._open(window)
        self.service.deliver(self.root / SESSION_TWO, {1: [-20.0] * 600})
        self.assertFalse(window.track_lanes.isVisible())

    def test_a_clip_or_a_small_copy_standing_in_gets_no_lanes_and_asks_for_none(self) -> None:
        package = self.root / "run" / "codex-evidence-package"
        clip = package / "artifacts" / "narration" / "clip_1.mp4"
        window = self._window()
        window.show()
        window.open_target(self._target(str(clip.relative_to(self.root)), package_root=package))
        self.factory.players[-1].report_loaded(titles=("Narration",))
        window.open_target(self._target("copy.mp4", stands_in_for=self.root / SESSION_ONE))
        self.factory.players[-1].report_loaded(titles=("Narration",))
        self.assertEqual(self.service.wanted, [])
        self.service.deliver(self.root / "copy.mp4", {1: [-20.0] * 600})
        self.assertFalse(window.track_lanes.isVisible())
        self.assertFalse(window.next_sound_button.isVisible())


class SoundTests(LanesTestCase):
    def test_next_and_previous_sound_jump_on_the_track_you_hear(self) -> None:
        window, player = self._six_lane_window(hear_track=2, start_seconds=10.0)
        player.arrive()
        self.assertTrue(window.next_sound_button.isVisible())
        QTest.mouseClick(window.next_sound_button, Qt.MouseButton.LeftButton)
        player.arrive()
        self.assertEqual(player.set_positions[-1], 100_000)
        self._press(window, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
        player.arrive()
        self.assertEqual(player.set_positions[-1], 300_000)
        QTest.mouseClick(window.next_sound_button, Qt.MouseButton.LeftButton)
        self.assertIn("last sound on Track 2", window.status_label.text())
        self._press(window, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
        player.arrive()
        self.assertEqual(player.set_positions[-1], 100_000)

    def test_a_click_on_a_tracks_name_hears_it_and_the_sounds_follow(self) -> None:
        window, player = self._six_lane_window(hear_track=2, start_seconds=10.0)
        player.arrive()
        self._click_lane_name(window, 1)
        self.assertEqual(player.activeAudioTrack(), 0, "Track 1 is heard now")
        self.assertEqual(window.track_lanes._heard, 1)
        QTest.mouseClick(window.next_sound_button, Qt.MouseButton.LeftButton)
        player.arrive()
        self.assertEqual(player.set_positions[-1], 50_000, "Track 1's sound, not Track 2's")

    def test_a_seek_lets_the_measuring_wait_so_the_picture_comes_first(self) -> None:
        window, player = self._six_lane_window(hear_track=2)
        before = self.service.holds
        QTest.mouseClick(window.forward_five_button, Qt.MouseButton.LeftButton)
        self.assertGreater(self.service.holds, before)


class WaveformsButtonTests(LanesTestCase):
    def test_the_waveforms_button_hides_and_shows_them_while_playing_and_changes_nothing_else(self) -> None:
        window, player = self._six_lane_window(hear_track=2, start_seconds=10.0)
        player.arrive()
        player.move_to(42_000)
        seeks, plays, pauses, track = len(player.set_positions), player.play_calls, player.pause_calls, player.activeAudioTrack()
        saves = self.host.save_calls
        QTest.mouseClick(window.waveforms_button, Qt.MouseButton.LeftButton)
        self.assertFalse(window.track_lanes.isVisible())
        self.assertIs(self.host.app_settings[WAVEFORMS_KEY], False)
        self.assertGreater(self.host.save_calls, saves, "remembered")
        self.assertEqual((len(player.set_positions), player.play_calls, player.pause_calls, player.activeAudioTrack()),
                         (seeks, plays, pauses, track), "never seeks, pauses, plays or changes the track")
        self.assertEqual(player.position(), 42_000)
        self.assertTrue(window.next_sound_button.isVisible(), "Next sound still works with the lanes hidden")
        QTest.mouseClick(window.next_sound_button, Qt.MouseButton.LeftButton)
        player.arrive()
        self.assertEqual(player.set_positions[-1], 100_000)
        self._press(window, Qt.Key.Key_W)
        self.assertTrue(window.track_lanes.isVisible())
        self.assertIs(self.host.app_settings[WAVEFORMS_KEY], True)

    def test_with_nothing_to_show_the_button_is_greyed_and_w_says_why(self) -> None:
        # Found on screen: a clip or a small review copy has no lanes, yet Waveforms and W still
        # switched them and the line said "Waveforms shown".
        package = self.root / "run" / "codex-evidence-package"
        clip = package / "artifacts" / "narration" / "clip_1.mp4"
        window = self._window()
        window.show()
        for target, reason in (
            (self._target(str(clip.relative_to(self.root)), package_root=package), NO_WAVEFORMS_CLIP_TEXT),
            (self._target("copy.mp4", stands_in_for=self.root / SESSION_ONE), NO_WAVEFORMS_REVIEW_COPY_TEXT),
        ):
            with self.subTest(reason=reason):
                window.open_target(target)
                self.factory.players[-1].report_loaded(titles=("Narration",))
                self.assertFalse(window.waveforms_button.isEnabled())
                self.assertIn(reason, window.waveforms_button.toolTip())
                saves = self.host.save_calls
                self._press(window, Qt.Key.Key_W)
                self.assertEqual(window.status_label.text(), reason)
                self.assertEqual(self.host.save_calls, saves, "the remembered choice is not touched")
                self.assertNotIn(WAVEFORMS_KEY, self.host.app_settings)
        window, _player = self._six_lane_window()
        self.assertTrue(window.waveforms_button.isEnabled(), "a recording has its waveforms again")
        self._press(window, Qt.Key.Key_W)
        self.assertIn("Waveforms hidden", window.status_label.text())

    def test_a_hidden_choice_is_kept_for_the_next_recording(self) -> None:
        self.host.app_settings[WAVEFORMS_KEY] = False
        window, _player = self._six_lane_window()
        self.assertFalse(window.track_lanes.isVisible())
        self.assertTrue(window.next_sound_button.isVisible())


class MomentTests(LanesTestCase):
    def _package(self) -> Path:
        recording = self.root / SESSION_ONE
        root = self.root / "run" / "codex-evidence-package"
        source_id = f"{recording.stem}-{source_digest(recording)}"
        root.mkdir(parents=True)
        (root / "manifest.json").write_text(json.dumps({"sources": [
            {"source_id": source_id, "physical_source_id": source_id, "source_path": str(recording),
             "source_filename": recording.name}]}), encoding="utf-8")
        (root / "SESSION_TIMELINE.json").write_text(json.dumps({"records": [
            {"record_type": "ticket_mention", "mention_id": "C1", "source_id": source_id, "timestamp_seconds": 130.0,
             "focused_start_seconds": 125.0, "excerpt": "make the fuel number bigger"},
            {"record_type": "review_needed", "mention_id": "R1", "source_id": source_id, "timestamp_seconds": 400.0,
             "focused_start_seconds": 0.0, "excerpt": "not sure"},
        ]}), encoding="utf-8")
        (root / "NARRATION_EVIDENCE.json").write_text(json.dumps({"sources": [
            {"source_id": source_id, "moments": [{"start_seconds": 60.0, "text": "here we go"}]}]}), encoding="utf-8")
        return root

    def _window_with_moments(self):
        package = self._package()
        window = self._window()
        window.show()
        player = self._open(window, package_root=package)
        deadline = time.monotonic() + 5
        while not window._moments and time.monotonic() < deadline:
            QTest.qWait(20)
        return window, player

    def test_the_packages_moments_show_on_the_time_bar_and_a_click_goes_there(self) -> None:
        window, player = self._window_with_moments()
        self.assertEqual([(m.seconds, m.text) for m in window._moments],
                         [(60.0, "you were talking"), (125.0, "ticket mention"), (400.0, "review needed")])
        self.assertTrue(window.next_moment_button.isVisible())
        timeline = window.timeline
        self.app.processEvents()
        mark = next(item for item in timeline.moment_marks() if item.seconds == 125.0)
        self.assertTrue(mark.strong)
        QTest.mouseClick(timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(round(mark.x), timeline._ruler_bottom + 3))
        player.arrive()
        self.assertEqual(player.set_positions[-1], 125_000, "the moment exactly, not the pixel")
        self.assertIn("ticket mention at 0:02:05: make the fuel number bigger", window.status_label.text())

    def test_the_ruler_above_a_moment_still_drags_the_playhead(self) -> None:
        # Only the moments' own band under the ruler goes to a moment; the ruler drags as before.
        window, _player = self._window_with_moments()
        timeline = window.timeline
        self.app.processEvents()
        mark = next(item for item in timeline.moment_marks() if item.seconds == 125.0)
        point = QPoint(round(mark.x), max(1, timeline._ruler_bottom - 5))
        QTest.mousePress(timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        self.assertTrue(timeline._scrubbing, "a press on the ruler starts a drag")
        QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        self.assertNotIn("ticket mention", window.status_label.text())

    def test_next_and_previous_moment_by_key(self) -> None:
        window, player = self._window_with_moments()
        player.arrive()
        self._press(window, Qt.Key.Key_BracketRight)
        player.arrive()
        self.assertEqual(player.set_positions[-1], 60_000)
        self._press(window, Qt.Key.Key_BracketRight)
        player.arrive()
        self.assertEqual(player.set_positions[-1], 125_000)
        self._press(window, Qt.Key.Key_BracketLeft)
        player.arrive()
        self.assertEqual(player.set_positions[-1], 60_000)

    def test_a_new_recording_clears_the_moments(self) -> None:
        window, _player = self._window_with_moments()
        self._open(window, SESSION_TWO)
        self.assertEqual(window._moments, ())
        self.assertEqual(window.timeline.moment_marks(), [])


class DrawingRuleTests(LanesTestCase):
    def test_a_short_burst_on_a_long_recording_still_shows(self) -> None:
        # Three hours on 300 columns: 36 seconds a column, and the loudest of them is drawn.
        levels = [-70.0] * 10_800
        levels[5_400] = -12.0
        columns = level_columns(levels, 10_800.0, 300)
        self.assertEqual(len(columns), 300)
        self.assertEqual(columns[150], -12.0)
        self.assertEqual(max(value for value in columns if value is not None), -12.0)
        self.assertEqual(columns[149], -70.0)
        # Not measured yet: nothing to draw, so the lane stays dark there.
        self.assertEqual(level_columns([-40.0] * 60, 600.0, 10)[1:], [None] * 9)

    def test_moments_that_would_overlap_become_one_mark_that_lists_each(self) -> None:
        marks = _merge_moments([(100.0, True, "ticket mention at 0:01:40"), (101.0, True, "review needed at 0:01:41"),
                                (100.5, False, "you were talking at 0:01:40"), (900.0, True, "ticket mention at 0:15:00")],
                               3_600.0, 600)
        strong = [mark for mark in marks if mark.strong]
        self.assertEqual([mark.count for mark in strong], [2, 1])
        self.assertIn("ticket mention at 0:01:40", strong[0].tooltip())
        self.assertIn("review needed at 0:01:41", strong[0].tooltip())
        self.assertEqual([mark.count for mark in marks if not mark.strong], [1], "a moment of talking keeps its own mark")


class SmallScreenTests(LanesTestCase):
    def _busiest(self):
        window, player = self._six_lane_window(hear_track=2)
        self.host.runner_thread = object()
        self.host.skip_run_sources = lambda sources: list(sources)
        window._show_moments([Moment(60.0, "narration", "you were talking", "here", finding=False),
                              Moment(125.0, "ticket_mention", "ticket mention", "fuel")])
        self._show_lines(window, track_explanation="Track 2 carries your narration.", transcribed_track=2)
        window.show_numbers_checkbox.setChecked(True)
        window.never_use_current()
        self.app.processEvents()
        return window

    def test_the_busiest_window_with_six_lanes_fits_a_small_laptop_in_the_apps_own_look(self) -> None:
        # Measured in the app's theme: its stylesheet makes every button taller and wider than Qt's
        # plain look, and a fit checked without it says nothing about the real window.
        previous = self.app.styleSheet()
        apply_theme(self.app, "Dark")
        try:
            window = self._busiest()
            for widget in (window.track_lanes, window.next_sound_button, window.next_moment_button,
                           window.skip_button, window.undo_banner, window.waveforms_button):
                self.assertTrue(widget.isVisible(), widget)
            # Normal sizes are as before: a 2560x1440 screen opens the player at 1100x860, and there
            # the lanes and the transcript lines keep their full heights.
            window.resize(1100, 860)
            self.app.processEvents()
            self.assertEqual(window.track_lanes.height(), LANES_HEIGHT)
            self.assertEqual(window.lines_scroll.height(), LINES_HEIGHT)
            # A 1366x768 laptop opens the player at 1100x680 (test_a_first_time_window_is_no_bigger...):
            # on a window that short, the lanes and the lines give up height; nothing is cut off.
            hint = window.minimumSizeHint()
            self.assertLessEqual(hint.height(), 680)
            self.assertLessEqual(hint.width(), 1366 - 16)
            window.resize(max(1100, hint.width()), 680)
            self.app.processEvents()
            self.assertLess(window.track_lanes.height(), LANES_HEIGHT)
            self.assertLess(window.lines_scroll.height(), LINES_HEIGHT)
            for widget in (window.legend_label, window.never_use_button, window.status_label):
                bottom = widget.mapTo(window, QPoint(0, widget.height())).y()
                self.assertLessEqual(bottom, window.height(), widget)
            for control in window.findChildren(QWidget):
                if isinstance(control, (QPushButton, QCheckBox)) and control.isVisible() and control.text().strip():
                    with self.subTest(control=control.text()):
                        self.assertGreaterEqual(control.width() + 2, control.minimumSizeHint().width())
        finally:
            self.app.setStyleSheet(previous)
