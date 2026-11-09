from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QImage, QMouseEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from media_manglers_workbench.audio_widgets import (  # noqa: E402
    PLAYHEAD_COLOR,
    REJECTED_SPAN_MIN_WIDTH,
    RULER_MARK_COLOR,
    RULER_STEPS_SECONDS,
    TICK_KEPT,
    TICK_LEFT_OUT,
    TIMELINE_BACKGROUND,
    TIMELINE_MIN_HEIGHT,
    TimelineBar,
    WaveformSeekWidget,
    _ruler_step_seconds,
    format_hms,
)


# An invented length: 3 h 57 min 04.85 s, long enough to need the hour ruler.
SYNTHETIC_DURATION_SECONDS = 14_224.85
BAR_WIDTH = 400


class FormatHmsTests(unittest.TestCase):
    def test_hours_are_always_shown(self) -> None:
        self.assertEqual(format_hms(0), "0:00:00")
        self.assertEqual(format_hms(59_999), "0:00:59")
        self.assertEqual(format_hms(3_600_000), "1:00:00")
        self.assertEqual(format_hms(14_224_850), "3:57:04")

    def test_a_time_is_cut_off_never_rounded_up(self) -> None:
        # 59.999 s has not reached the minute yet, so the clock must not say so.
        self.assertEqual(format_hms(59_999, tenths=True), "0:00:59.9")
        self.assertEqual(format_hms(999), "0:00:00")

    def test_tenths(self) -> None:
        self.assertEqual(format_hms(0, tenths=True), "0:00:00.0")
        self.assertEqual(format_hms(2_467_300, tenths=True), "0:41:07.3")
        self.assertEqual(format_hms(3_600_000, tenths=True), "1:00:00.0")
        self.assertEqual(format_hms(14_224_850, tenths=True), "3:57:04.8")

    def test_negative_and_unusable_input_reads_as_zero(self) -> None:
        self.assertEqual(format_hms(-1), "0:00:00")
        self.assertEqual(format_hms(-5_000_000, tenths=True), "0:00:00.0")
        self.assertEqual(format_hms(float("nan")), "0:00:00")
        self.assertEqual(format_hms(float("inf")), "0:00:00")
        self.assertEqual(format_hms(None), "0:00:00")  # type: ignore[arg-type]

    def test_floats_and_long_recordings(self) -> None:
        self.assertEqual(format_hms(2_467_300.9), "0:41:07")
        self.assertEqual(format_hms(36_000_000), "10:00:00")
        self.assertEqual(format_hms(360_000_000 + 61_000), "100:01:01")


class RulerStepTests(unittest.TestCase):
    def test_labels_never_overlap_at_any_length_or_width(self) -> None:
        label_width = 58.0
        for duration in (0.4, 7.0, 95.0, 600.0, 3_599.0, SYNTHETIC_DURATION_SECONDS, 86_400.0, 900_000.0):
            for width in (120, 400, 980, 5_760):
                with self.subTest(duration=duration, width=width):
                    step = _ruler_step_seconds(duration, width, label_width)
                    self.assertGreater(step, 0)
                    self.assertGreaterEqual(step / duration * width, label_width)

    def test_the_smallest_round_step_that_fits_is_chosen(self) -> None:
        # One hour across 400 px: a 58 px label covers 522 s, so 600 s is the
        # first round step that fits.
        self.assertEqual(_ruler_step_seconds(3_600.0, 400, 58.0), 600)
        self.assertEqual(_ruler_step_seconds(10.0, 980, 58.0), 1)
        self.assertEqual(_ruler_step_seconds(SYNTHETIC_DURATION_SECONDS, 980, 58.0), 1_800)
        for duration in (30.0, 600.0, 3_600.0, SYNTHETIC_DURATION_SECONDS):
            self.assertIn(_ruler_step_seconds(duration, 980, 58.0), RULER_STEPS_SECONDS)

    def test_a_recording_too_long_for_the_ladder_uses_whole_hours(self) -> None:
        step = _ruler_step_seconds(900_000.0, 400, 58.0)
        self.assertGreater(step, 3_600)
        self.assertEqual(step % 3_600, 0)

    def test_nothing_to_measure(self) -> None:
        self.assertEqual(_ruler_step_seconds(0.0, 400, 58.0), 0)
        self.assertEqual(_ruler_step_seconds(60.0, 0, 58.0), 0)


class TimelineBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.bar = TimelineBar()
        self.bar.resize(BAR_WIDTH, TIMELINE_MIN_HEIGHT)
        self.bar.show()
        self.app.processEvents()
        self.events: list[tuple[str, float | None]] = []
        self.bar.scrub_started.connect(lambda: self.events.append(("started", None)))
        self.bar.seek_requested.connect(lambda seconds: self.events.append(("seek", seconds)))
        self.bar.scrub_finished.connect(lambda: self.events.append(("finished", None)))

    def tearDown(self) -> None:
        self.bar.close()
        self.bar.deleteLater()
        self.app.processEvents()

    def _names(self) -> list[str]:
        return [name for name, _seconds in self.events]

    def _seeks(self) -> list[float]:
        return [seconds for name, seconds in self.events if name == "seek" and seconds is not None]

    def _painted(self) -> QImage:
        return self.bar.grab().toImage()

    def _column_has(self, image: QImage, x: int, color: str) -> bool:
        return any(image.pixelColor(x, y).name() == color for y in range(image.height()))

    def test_basics(self) -> None:
        self.assertEqual(self.bar.minimumHeight(), 46)
        self.assertEqual(self.bar.focusPolicy(), Qt.FocusPolicy.NoFocus)
        self.assertEqual(
            self.bar.toolTip(),
            "Click or drag to move through the recording. Blue marks are transcript lines; "
            "amber marks are lines that were left out.",
        )
        self.assertEqual(
            (TIMELINE_BACKGROUND, PLAYHEAD_COLOR, TICK_KEPT, TICK_LEFT_OUT),
            ("#17202a", "#ffcc66", "#57c7ff", "#ffb454"),
        )
        self.assertEqual(self.bar.position_seconds(), 0.0)

    def test_click_in_the_middle_asks_for_half_way_in_seconds(self) -> None:
        self.bar.set_duration(SYNTHETIC_DURATION_SECONDS)
        QTest.mouseClick(
            self.bar, Qt.MouseButton.LeftButton, pos=QPoint(BAR_WIDTH // 2, TIMELINE_MIN_HEIGHT // 2)
        )
        one_pixel = SYNTHETIC_DURATION_SECONDS / BAR_WIDTH
        seeks = self._seeks()
        self.assertTrue(seeks)
        for seconds in seeks:
            self.assertAlmostEqual(seconds, SYNTHETIC_DURATION_SECONDS / 2, delta=one_pixel)
        # Seconds, not the 0..1 ratio the older waveform widget speaks.
        self.assertGreater(seeks[0], 1.0)
        self.assertAlmostEqual(self.bar.position_seconds(), SYNTHETIC_DURATION_SECONDS / 2, delta=one_pixel)

    def test_press_drag_release_signal_order(self) -> None:
        self.bar.set_duration(100.0)
        QTest.mousePress(self.bar, Qt.MouseButton.LeftButton, pos=QPoint(100, 20))
        self.assertEqual(self.events, [("started", None), ("seek", 25.0)])

        QTest.mouseMove(self.bar, QPoint(200, 20))
        QTest.mouseMove(self.bar, QPoint(300, 22))
        self.assertEqual(self._names(), ["started", "seek", "seek", "seek"])
        self.assertEqual(self._seeks(), [25.0, 50.0, 75.0])
        self.assertEqual(self.bar.position_seconds(), 75.0)

        QTest.mouseRelease(self.bar, Qt.MouseButton.LeftButton, pos=QPoint(320, 20))
        self.assertEqual(self._names(), ["started", "seek", "seek", "seek", "seek", "finished"])
        self.assertEqual(self._seeks()[-1], 80.0)
        self.assertEqual(self.bar.position_seconds(), 80.0)

        # A move with no button held is not a drag.
        QTest.mouseMove(self.bar, QPoint(50, 20))
        self.assertEqual(self._names().count("seek"), 4)

    def test_wobble_on_the_same_moment_does_not_ask_again(self) -> None:
        self.bar.set_duration(100.0)
        QTest.mousePress(self.bar, Qt.MouseButton.LeftButton, pos=QPoint(100, 20))
        QTest.mouseMove(self.bar, QPoint(100, 30))
        QTest.mouseMove(self.bar, QPoint(100, 12))
        self.assertEqual(self._seeks(), [25.0])
        QTest.mouseRelease(self.bar, Qt.MouseButton.LeftButton, pos=QPoint(100, 12))
        self.assertEqual(self._names(), ["started", "seek", "seek", "finished"])

    def test_dragging_past_either_end_clamps(self) -> None:
        self.bar.set_duration(100.0)
        QTest.mousePress(self.bar, Qt.MouseButton.LeftButton, pos=QPoint(10, 20))
        QTest.mouseMove(self.bar, QPoint(BAR_WIDTH + 250, 20))
        self.assertEqual(self._seeks()[-1], 100.0)
        QTest.mouseMove(self.bar, QPoint(-90, 20))
        self.assertEqual(self._seeks()[-1], 0.0)
        QTest.mouseRelease(self.bar, Qt.MouseButton.LeftButton, pos=QPoint(-90, 20))
        self.assertEqual(self._names()[-1], "finished")

    def test_no_duration_means_no_signal_at_all(self) -> None:
        QTest.mousePress(self.bar, Qt.MouseButton.LeftButton, pos=QPoint(100, 20))
        QTest.mouseMove(self.bar, QPoint(200, 20))
        QTest.mouseRelease(self.bar, Qt.MouseButton.LeftButton, pos=QPoint(200, 20))
        QTest.mouseClick(self.bar, Qt.MouseButton.LeftButton, pos=QPoint(300, 20))
        self.assertEqual(self.events, [])
        self.assertEqual(self.bar.position_seconds(), 0.0)

    def test_other_mouse_buttons_do_nothing(self) -> None:
        self.bar.set_duration(100.0)
        QTest.mouseClick(self.bar, Qt.MouseButton.RightButton, pos=QPoint(100, 20))
        QTest.mouseClick(self.bar, Qt.MouseButton.MiddleButton, pos=QPoint(100, 20))
        self.assertEqual(self.events, [])

    def test_a_scrub_always_finishes_even_when_the_recording_goes_away(self) -> None:
        self.bar.set_duration(100.0)
        QTest.mousePress(self.bar, Qt.MouseButton.LeftButton, pos=QPoint(100, 20))
        self.bar.set_duration(0.0)
        QTest.mouseMove(self.bar, QPoint(200, 20))
        QTest.mouseRelease(self.bar, Qt.MouseButton.LeftButton, pos=QPoint(200, 20))
        self.assertEqual(self._names(), ["started", "seek", "finished"])

    def test_hiding_the_bar_ends_a_scrub(self) -> None:
        self.bar.set_duration(100.0)
        QTest.mousePress(self.bar, Qt.MouseButton.LeftButton, pos=QPoint(100, 20))
        self.bar.hide()
        self.assertEqual(self._names(), ["started", "seek", "finished"])
        # The release that follows must not finish it a second time.
        QTest.mouseRelease(self.bar, Qt.MouseButton.LeftButton, pos=QPoint(100, 20))
        self.assertEqual(self._names().count("finished"), 1)

    def test_a_lost_release_does_not_open_a_second_scrub(self) -> None:
        self.bar.set_duration(100.0)
        QTest.mousePress(self.bar, Qt.MouseButton.LeftButton, pos=QPoint(100, 20))
        # The window lost the mouse, so the release never came. The next press
        # carries on with the scrub the player already knows about.
        QTest.mousePress(self.bar, Qt.MouseButton.LeftButton, pos=QPoint(200, 20))
        self.assertEqual(self._names(), ["started", "seek", "seek"])
        QTest.mouseRelease(self.bar, Qt.MouseButton.LeftButton, pos=QPoint(200, 20))
        self.assertEqual(self._names(), ["started", "seek", "seek", "seek", "finished"])

    def test_a_lost_release_ends_the_scrub_on_the_next_move_when_tracking(self) -> None:
        # Without mouse tracking Qt never delivers a move with no button held,
        # so this only matters to a future caller that turns tracking on.
        self.bar.setMouseTracking(True)
        self.bar.set_duration(100.0)
        QTest.mousePress(self.bar, Qt.MouseButton.LeftButton, pos=QPoint(100, 20))
        move = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(200, 20),
            QPointF(200, 20),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(self.bar, move)
        self.assertEqual(self._names(), ["started", "seek", "finished"])
        self.assertEqual(self.bar.position_seconds(), 25.0)
        # Put QTest's own button state back, and prove nothing more is sent.
        QTest.mouseRelease(self.bar, Qt.MouseButton.LeftButton, pos=QPoint(200, 20))
        self.assertEqual(self._names(), ["started", "seek", "finished"])

    def test_a_double_click_leaves_no_scrub_open(self) -> None:
        self.bar.set_duration(100.0)
        # What Qt really delivers for a double click: press, release,
        # double-click, release. QTest.mouseDClick sends only the third.
        QTest.mouseClick(self.bar, Qt.MouseButton.LeftButton, pos=QPoint(100, 20))
        QTest.mouseDClick(self.bar, Qt.MouseButton.LeftButton, pos=QPoint(100, 20))
        QTest.mouseRelease(self.bar, Qt.MouseButton.LeftButton, pos=QPoint(100, 20))
        self.assertEqual(
            self._names(),
            ["started", "seek", "seek", "finished", "started", "seek", "seek", "finished"],
        )
        self.assertEqual(set(self._seeks()), {25.0})

    def test_seconds_at_clamps(self) -> None:
        self.assertEqual(self.bar.seconds_at(200), 0.0)  # no duration yet
        self.bar.set_duration(100.0)
        self.assertEqual(self.bar.seconds_at(0), 0.0)
        self.assertEqual(self.bar.seconds_at(100), 25.0)
        self.assertEqual(self.bar.seconds_at(BAR_WIDTH), 100.0)
        self.assertEqual(self.bar.seconds_at(-40), 0.0)
        self.assertEqual(self.bar.seconds_at(BAR_WIDTH * 3), 100.0)
        self.assertEqual(self.bar.seconds_at(float("nan")), 0.0)

    def test_set_position_clamps(self) -> None:
        self.bar.set_duration(100.0)
        self.bar.set_position(42.5)
        self.assertEqual(self.bar.position_seconds(), 42.5)
        self.bar.set_position(250.0)
        self.assertEqual(self.bar.position_seconds(), 100.0)
        self.bar.set_position(-3.0)
        self.assertEqual(self.bar.position_seconds(), 0.0)
        self.bar.set_position(float("nan"))
        self.assertEqual(self.bar.position_seconds(), 0.0)
        # Moving the playhead is not a request to seek.
        self.assertEqual(self.events, [])

    def test_a_position_set_before_the_duration_is_known_is_kept(self) -> None:
        # The player sets the start moment before the recording has loaded.
        self.bar.set_position(61.0)
        self.assertEqual(self.bar.position_seconds(), 0.0)
        self.bar.set_duration(100.0)
        self.assertEqual(self.bar.position_seconds(), 61.0)

    def test_set_duration_tolerates_bad_values(self) -> None:
        for value in (-5.0, float("nan"), float("inf"), None):
            with self.subTest(value=value):
                self.bar.set_duration(100.0)
                self.bar.set_duration(value)  # type: ignore[arg-type]
                self.assertEqual(self.bar.seconds_at(200), 0.0)

    def test_set_ticks_tolerates_unknown_kinds_and_bad_entries(self) -> None:
        self.bar.set_duration(100.0)
        self.bar.set_ticks(
            [
                (25.0, "kept"),
                (50.0, "left_out"),
                (75.0, "rejected_span"),
                (10.0, "moment"),  # a kind from a newer version
                (12.0, None),  # type: ignore[list-item]
                ("soon", "kept"),  # type: ignore[list-item]
                (float("nan"), "kept"),
                (30.0,),  # type: ignore[list-item]
                None,  # type: ignore[list-item]
                (-4.0, "kept"),
            ]
        )
        image = self._painted()
        self.assertEqual(
            [(start, kind) for start, kind, _end in self.bar._ticks],
            [(25.0, "kept"), (50.0, "left_out"), (75.0, "rejected_span"), (0.0, "kept")],
        )
        # The unknown kind painted nothing at its place (x = 40).
        self.assertFalse(self._column_has(image, 40, TICK_KEPT))
        self.assertFalse(self._column_has(image, 40, TICK_LEFT_OUT))
        self.bar.set_ticks(None)  # type: ignore[arg-type]
        self.assertEqual(self.bar._ticks, ())

    def test_paints_ruler_marks_and_playhead_on_top(self) -> None:
        self.bar.set_duration(100.0)
        self.bar.set_ticks([(25.0, "kept"), (50.0, "left_out"), (75.0, "rejected_span")])
        self.bar.set_position(10.0)
        image = self._painted()

        self.assertEqual(image.pixelColor(BAR_WIDTH - 3, TIMELINE_MIN_HEIGHT - 1).name(), TIMELINE_BACKGROUND)
        self.assertTrue(self._column_has(image, 0, RULER_MARK_COLOR))
        self.assertTrue(self._column_has(image, 100, TICK_KEPT))
        self.assertFalse(self._column_has(image, 100, TICK_LEFT_OUT))
        self.assertTrue(self._column_has(image, 200, TICK_LEFT_OUT))
        self.assertFalse(self._column_has(image, 200, TICK_KEPT))

        # The rejected stretch is a bar from its start, never narrower than 6 px.
        self.assertEqual(REJECTED_SPAN_MIN_WIDTH, 6)
        for x in range(300, 306):
            self.assertTrue(self._column_has(image, x, TICK_LEFT_OUT), x)
        self.assertFalse(self._column_has(image, 299, TICK_LEFT_OUT))
        self.assertFalse(self._column_has(image, 306, TICK_LEFT_OUT))
        # It is a thin bar, not a tall mark like a left-out line.
        span_rows = [y for y in range(image.height()) if image.pixelColor(303, y).name() == TICK_LEFT_OUT]
        line_rows = [y for y in range(image.height()) if image.pixelColor(200, y).name() == TICK_LEFT_OUT]
        self.assertLessEqual(len(span_rows), 4)
        self.assertGreater(len(line_rows), len(span_rows) * 3)

        # The playhead runs the whole height at 10 s (x = 40).
        self.assertEqual(image.pixelColor(40, TIMELINE_MIN_HEIGHT - 1).name(), PLAYHEAD_COLOR)
        self.assertEqual(image.pixelColor(40, TIMELINE_MIN_HEIGHT // 2).name(), PLAYHEAD_COLOR)

        # ... and is drawn over a mark that sits at the same place.
        self.bar.set_position(50.0)
        image = self._painted()
        for y in range(TIMELINE_MIN_HEIGHT):
            self.assertEqual(image.pixelColor(200, y).name(), PLAYHEAD_COLOR, y)

    def test_a_rejected_span_with_an_end_is_drawn_to_its_length(self) -> None:
        self.bar.set_duration(100.0)
        self.bar.set_ticks([(25.0, "rejected_span", 50.0)])
        image = self._painted()
        for x in (100, 150, 199):
            self.assertTrue(self._column_has(image, x, TICK_LEFT_OUT), x)
        self.assertFalse(self._column_has(image, 99, TICK_LEFT_OUT))
        self.assertFalse(self._column_has(image, 201, TICK_LEFT_OUT))

    def test_no_playhead_before_a_recording_is_loaded(self) -> None:
        image = self._painted()
        for x in range(0, BAR_WIDTH, 7):
            self.assertFalse(self._column_has(image, x, PLAYHEAD_COLOR), x)

    def test_moving_the_playhead_does_not_redraw_the_marks(self) -> None:
        self.bar.set_duration(SYNTHETIC_DURATION_SECONDS)
        self.bar.set_ticks([(float(second), "kept") for second in range(0, 14_000, 7)])
        self._painted()
        layer = self.bar._tick_layer
        cache_key = layer.cacheKey()
        renders = self.bar._tick_layer_renders
        self.assertIsNotNone(layer)
        self.assertGreaterEqual(renders, 1)

        for seconds in (1.0, 900.0, 7_000.0, SYNTHETIC_DURATION_SECONDS):
            self.bar.set_position(seconds)
            self._painted()
        QTest.mouseClick(self.bar, Qt.MouseButton.LeftButton, pos=QPoint(123, 20))
        self._painted()
        self.assertIs(self.bar._tick_layer, layer)
        self.assertEqual(self.bar._tick_layer.cacheKey(), cache_key)
        self.assertEqual(self.bar._tick_layer_renders, renders)

    def test_marks_are_redrawn_only_for_new_ticks_duration_or_size(self) -> None:
        self.bar.set_duration(100.0)
        self.bar.set_ticks([(25.0, "kept")])
        self._painted()
        renders = self.bar._tick_layer_renders

        # The same values again change nothing.
        self.bar.set_duration(100.0)
        self.bar.set_ticks([(25.0, "kept")])
        self._painted()
        self.assertEqual(self.bar._tick_layer_renders, renders)

        self.bar.set_ticks([(25.0, "kept"), (60.0, "left_out")])
        self._painted()
        self.assertEqual(self.bar._tick_layer_renders, renders + 1)

        self.bar.set_duration(200.0)
        self._painted()
        self.assertEqual(self.bar._tick_layer_renders, renders + 2)

        self.bar.resize(BAR_WIDTH + 100, TIMELINE_MIN_HEIGHT)
        self.app.processEvents()
        self._painted()
        self.assertEqual(self.bar._tick_layer_renders, renders + 3)
        self.assertEqual(self.bar._tick_layer.width(), BAR_WIDTH + 100)

        # Several changes before the next paint cost one render, not three.
        self.bar.set_duration(300.0)
        self.bar.set_ticks([(1.0, "kept")])
        self.bar.set_ticks([(2.0, "kept")])
        self._painted()
        self.assertEqual(self.bar._tick_layer_renders, renders + 4)

    def test_paints_at_any_width_and_recording_length(self) -> None:
        for duration in (0.4, 42.0, SYNTHETIC_DURATION_SECONDS, 900_000.0):
            for width in (60, BAR_WIDTH, 2_400):
                with self.subTest(duration=duration, width=width):
                    self.bar.resize(width, TIMELINE_MIN_HEIGHT)
                    self.bar.set_duration(duration)
                    self.bar.set_ticks(
                        [(duration / 3, "kept"), (duration / 2, "rejected_span"), (duration, "left_out")]
                    )
                    self.bar.set_position(duration)
                    image = self._painted()
                    self.assertEqual(image.width(), width)
                    # Marks and playhead at the very end stay inside the bar.
                    self.assertTrue(self._column_has(image, width - 1, PLAYHEAD_COLOR))
                    self.bar.set_position(0.0)
                    image = self._painted()
                    self.assertTrue(self._column_has(image, width - 1, TICK_LEFT_OUT))
                    self.assertTrue(self._column_has(image, 0, PLAYHEAD_COLOR))


class WaveformSeekWidgetGuardTests(unittest.TestCase):
    """The older waveform keeps its 0..1 ratio API; two screens depend on it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.waveform = WaveformSeekWidget()
        self.sought: list[float] = []
        self.waveform.seek_requested.connect(self.sought.append)
        self.waveform.resize(400, 60)

    def tearDown(self) -> None:
        self.waveform.deleteLater()
        self.app.processEvents()

    def test_click_still_emits_a_ratio(self) -> None:
        QTest.mouseClick(self.waveform, Qt.MouseButton.LeftButton, pos=QPoint(300, 30))
        self.assertTrue(self.sought)
        self.assertAlmostEqual(self.sought[-1], 0.75, places=2)
        for ratio in self.sought:
            self.assertGreaterEqual(ratio, 0.0)
            self.assertLessEqual(ratio, 1.0)

    def test_drag_still_emits_clamped_ratios(self) -> None:
        QTest.mousePress(self.waveform, Qt.MouseButton.LeftButton, pos=QPoint(100, 30))
        QTest.mouseMove(self.waveform, QPoint(200, 30))
        QTest.mouseMove(self.waveform, QPoint(900, 30))
        QTest.mouseRelease(self.waveform, Qt.MouseButton.LeftButton, pos=QPoint(900, 30))
        self.assertEqual(self.sought, [0.25, 0.5, 1.0])

    def test_envelope_api_and_look_are_unchanged(self) -> None:
        self.waveform.set_envelope([0.1, -0.4, 0.9])
        self.waveform.set_position_ratio(1.7)
        self.assertEqual(self.waveform._envelope, (0.1, 0.0, 0.9))
        self.assertEqual(self.waveform._position_ratio, 1.0)
        self.assertEqual(self.waveform.minimumHeight(), 54)
        self.assertEqual(
            self.waveform.toolTip(),
            "Click or drag to seek within the selected speech-dense preview region.",
        )
        self.assertFalse(hasattr(self.waveform, "scrub_started"))


if __name__ == "__main__":
    unittest.main()
