"""217 signal 2 (226): the game picture not changing, beside signal 1, the game sound quiet.

The rule is pure: it takes small gray pictures of the game region and their times, and gives each
second the share of the picture that changed. A stretch where the picture stays still for a minute
is idle, and "black" when the screen is dark. The two signals are joined into one timeline: idle when
either finds a minute or more, each stretch saying which signal found it.

The sound's "estimated" timeline is the one the raw bin makes (``raw_bin_library.idle_from_levels``),
and the last test feeds the rule real keyframes that the shared sampler (``frame_render.sample_picture``)
reads from a synthetic recording.
"""

from __future__ import annotations

from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core import activity_timeline as timeline  # noqa: E402
from media_manglers.core import frame_render, raw_bin_library, voice_track  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
SIZE = timeline.PICTURE_SAMPLE_WIDTH * timeline.PICTURE_SAMPLE_HEIGHT
GAME, PICTURE = timeline.SIGNAL_GAME_AUDIO, timeline.SIGNAL_GAME_PICTURE


def scene(seed: int) -> bytes:
    """A 64x36 gray picture that differs almost everywhere from any other seed's."""

    return random.Random(seed).randbytes(SIZE)


def flat(level: int) -> bytes:
    return bytes([level]) * SIZE


def with_cells_changed(picture: bytes, count: int, by: int) -> bytes:
    data = bytearray(picture)
    for index in range(count):
        data[index] = min(255, data[index] + by)
    return bytes(data)


def changes_for(still: list[tuple[int, int]], seconds: int, moving: float = 0.4) -> list[float | None]:
    return [0.0 if any(start <= second < end for start, end in still) else moving for second in range(seconds)]


class PictureDifferenceTests(unittest.TestCase):
    def test_mean_abs_difference_is_the_editors_picture_difference(self) -> None:
        # The AI Video Editor's "sharp picture changes" measure, 32x18 gray stills (analysis.picture_changes).
        for seed in range(5):
            first, second = random.Random(seed).randbytes(576), random.Random(seed + 100).randbytes(576)
            editor = sum(abs(a - b) for a, b in zip(second, first)) / 576
            self.assertEqual(timeline.mean_abs_difference(second, first), editor)
        self.assertEqual(timeline.mean_abs_difference(flat(10), flat(10)), 0.0)
        self.assertEqual(timeline.mean_abs_difference(flat(10), flat(50)), 40.0)

    def test_a_cell_changed_only_when_it_moved_by_more_than_the_level(self) -> None:
        base = flat(100)
        self.assertEqual(timeline.changed_share(base, with_cells_changed(base, 23, 9), 8), 23 / SIZE)
        self.assertEqual(timeline.changed_share(base, with_cells_changed(base, 50, 8), 8), 0.0)
        self.assertEqual(timeline.changed_share(base, base, timeline.PICTURE_CELL_CHANGE_LEVEL), 0.0)
        with self.assertRaises(ValueError):
            timeline.changed_share(base, base[:-1], 8)

    def test_the_measures_are_the_same_without_numpy(self) -> None:
        pairs = [(scene(seed), with_cells_changed(scene(seed), seed * 40, 9 + seed)) for seed in range(6)]
        pairs.append((scene(1), scene(2)))
        quick = [(timeline.changed_share(a, b, 8), timeline.mean_abs_difference(a, b)) for a, b in pairs]
        with mock.patch.dict(sys.modules, {"numpy": None}):
            plain = [(timeline.changed_share(a, b, 8), timeline.mean_abs_difference(a, b)) for a, b in pairs]
        self.assertEqual(quick, plain)


class PerSecondTests(unittest.TestCase):
    def test_a_still_picture_reads_still_and_a_moving_one_changes(self) -> None:
        times = [2.0 * index for index in range(31)]  # a keyframe every 2 s, 0-60 s
        changes, luma = timeline.picture_change_per_second(times, [flat(120)] * 31, duration=60)
        self.assertEqual(changes, [0.0] * 60)
        self.assertEqual(luma, [120.0] * 60)
        changes, _luma = timeline.picture_change_per_second(times, [scene(index) for index in range(31)], duration=60)
        self.assertEqual(len(changes), 60)
        self.assertTrue(all(value is not None and value > 0.5 for value in changes), changes)

    def test_dense_or_duplicated_samples_never_read_as_zero_change(self) -> None:
        # The trap: a frame rate filter after keyframe-only decoding repeats each keyframe to fill
        # the second. The game picture here changes every second, sampled 4 times a second, and
        # every sample is there twice with the same time.
        times: list[float] = []
        frames: list[bytes] = []
        for quarter in range(4 * 90):
            at = quarter / 4
            times += [at, at]
            frames += [scene(int(at))] * 2
        naive = [timeline.changed_share(frames[index - 1], frames[index], 8) for index in range(1, len(frames))]
        self.assertGreater(naive.count(0.0), len(naive) // 2, "next-to-next comparison would read it as still")
        changes, _luma = timeline.picture_change_per_second(times, frames, duration=90)
        measured = [value for value in changes if value is not None]
        self.assertGreaterEqual(len(measured), 89)
        self.assertTrue(all(value > 0.5 for value in measured), changes)
        idle = timeline.game_picture_timeline(changes)
        self.assertEqual((idle.status, idle.idle_stretches), (timeline.STATUS_MEASURED, []))
        # The same density on a still picture does read still.
        still, _luma = timeline.picture_change_per_second(times, [flat(90)] * len(times), duration=90)
        self.assertEqual(still, [0.0] * 90)

    def test_seconds_more_than_ten_seconds_from_a_pair_of_samples_are_not_measured(self) -> None:
        times = [float(t) for t in range(0, 41, 2)] + [float(t) for t in range(52, 101, 2)]
        changes, luma = timeline.picture_change_per_second(times, [flat(60)] * len(times), duration=100)
        self.assertEqual(changes[:40], [0.0] * 40)
        self.assertEqual(changes[40:52], [None] * 12, "the keyframes at 40 s and 52 s are 12 s apart")
        self.assertEqual(luma[40:52], [None] * 12)
        self.assertEqual(changes[52:], [0.0] * 48)
        # Ten seconds apart is still measured.
        times = [float(t) for t in range(0, 41, 2)] + [float(t) for t in range(50, 101, 2)]
        changes, _luma = timeline.picture_change_per_second(times, [flat(60)] * len(times), duration=100)
        self.assertEqual(changes, [0.0] * 100)

    def test_seconds_outside_the_samples_are_not_measured(self) -> None:
        changes, _luma = timeline.picture_change_per_second([10.0, 12.0, 14.0], [flat(5)] * 3, duration=20)
        self.assertEqual(changes, [None] * 10 + [0.0] * 4 + [None] * 6)
        self.assertEqual(timeline.picture_change_per_second([], [], duration=5), ([None] * 5, [None] * 5))


class PictureTimelineTests(unittest.TestCase):
    def test_a_minute_of_still_picture_is_idle_time(self) -> None:
        changes = changes_for([(30, 100)], 130)
        result = timeline.game_picture_timeline(changes, luma=[120.0] * 130, region="center panel")
        self.assertEqual(result.status, timeline.STATUS_MEASURED)
        self.assertEqual(result.idle_stretches, [(30, 100)])
        self.assertEqual(result.active_stretches, [(0, 30), (100, 130)])
        self.assertEqual((result.idle_seconds, result.idle_share, result.duration_seconds), (70, round(70 / 130, 4), 130))
        self.assertEqual(result.idle_by, [[PICTURE]])
        self.assertEqual(result.picture_kinds, [timeline.PICTURE_STILL])
        self.assertEqual((result.region, result.rule_version), ("center panel", timeline.GAME_PICTURE_RULE_VERSION))
        self.assertEqual(result.signals[PICTURE]["status"], timeline.STATUS_MEASURED)
        self.assertEqual(result.signals[PICTURE]["measured_share"], 1.0)
        self.assertEqual(result.to_dict()["idle_stretches"], [[30, 100]])

    def test_a_dark_still_screen_is_black(self) -> None:
        luma = [16.0 if 30 <= second < 100 else 120.0 for second in range(130)]
        result = timeline.game_picture_timeline(changes_for([(30, 100)], 130), luma=luma)
        self.assertEqual(result.picture_kinds, [timeline.PICTURE_BLACK])
        bright = [timeline.PICTURE_BLACK_LUMA + 1.0] * 130
        self.assertEqual(timeline.game_picture_timeline(changes_for([(30, 100)], 130), luma=bright).picture_kinds,
                         [timeline.PICTURE_STILL])

    def test_a_short_still_is_driving_and_a_click_inside_a_long_one_does_not_break_it(self) -> None:
        self.assertEqual(timeline.game_picture_timeline(changes_for([(10, 69)], 100)).idle_stretches, [])
        # Four moving seconds inside are bridged; six are not, and neither half is a minute.
        self.assertEqual(timeline.game_picture_timeline(changes_for([(10, 50), (54, 94)], 120)).idle_stretches,
                         [(10, 94)])
        self.assertEqual(timeline.game_picture_timeline(changes_for([(10, 50), (56, 96)], 120)).idle_stretches, [])

    def test_still_means_at_most_one_percent_of_the_picture_changed(self) -> None:
        at_the_bar = [timeline.PICTURE_STILL_MAX_SHARE] * 70
        self.assertEqual(timeline.game_picture_timeline(at_the_bar).idle_stretches, [(0, 70)])
        over = [timeline.PICTURE_STILL_MAX_SHARE + 0.0001] * 70
        self.assertEqual(timeline.game_picture_timeline(over).idle_stretches, [])

    def test_too_little_of_the_recording_measured_is_unknown_with_the_reason(self) -> None:
        changes: list[float | None] = [0.0] * 100
        for second in range(0, 100, 4):
            changes[second] = None  # 75% measured
        result = timeline.game_picture_timeline(changes)
        self.assertEqual(result.status, timeline.STATUS_UNKNOWN)
        self.assertEqual((result.idle_stretches, result.idle_share), ([], None))
        self.assertIn("75%", result.reason)
        self.assertIn("80%", result.reason)
        self.assertEqual(result.signals[PICTURE]["status"], timeline.STATUS_UNKNOWN)
        enough: list[float | None] = [0.0] * 100
        for second in range(0, 100, 5):
            enough[second] = None  # 80% measured
        self.assertEqual(timeline.game_picture_timeline(enough).status, timeline.STATUS_MEASURED)
        self.assertEqual(timeline.game_picture_timeline([]).status, timeline.STATUS_UNKNOWN)


class CombinedTimelineTests(unittest.TestCase):
    """The status table of 217 signal 2, row by row."""

    @staticmethod
    def levels(quiet: list[tuple[int, int]], seconds: int = 600) -> list[float]:
        return [-80.0 if any(start <= second < end for start, end in quiet) else -20.0 for second in range(seconds)]

    @staticmethod
    def audio(quiet: list[tuple[int, int]], seconds: int = 600) -> timeline.ActivityTimeline:
        return timeline.game_audio_timeline(CombinedTimelineTests.levels(quiet, seconds), game_track=2)

    def estimated(self, quiet: list[tuple[int, int]]) -> timeline.ActivityTimeline:
        # Made by the raw bin's own rule (220): Track 3 is named the game audio but is silent for the
        # whole recording, so idle time is estimated from the full mix (Track 1), which sounds.
        titles = {0: "Full Mix", 1: "Narration", 2: "Game"}
        levels = {0: self.levels(quiet), 1: [-20.0] * 600, 2: [-120.0] * 600}
        game, decided_by = voice_track.game_audio_track(titles)
        result = raw_bin_library.idle_from_levels(titles, levels, 600, game=game, decided_by=decided_by, reason="",
                                                  setting_value="")
        self.assertEqual((game, decided_by), (2, voice_track.DECIDED_BY_NAME))
        self.assertEqual((result.status, result.game_track), (timeline.STATUS_ESTIMATED, None))
        return result

    @staticmethod
    def picture(still: list[tuple[int, int]], seconds: int = 600) -> timeline.ActivityTimeline:
        return timeline.game_picture_timeline(changes_for(still, seconds), luma=[100.0] * seconds, region="whole frame")

    UNKNOWN_SOUND = "More than one track could be the game audio."
    UNKNOWN_PICTURE = "keyframes are more than 10 s apart"

    def test_measured_sound_and_picture_give_the_union(self) -> None:
        result = timeline.combined_timeline(self.audio([(100, 200), (500, 570)]),
                                            self.picture([(203, 280), (400, 470)]))
        self.assertEqual(result.status, timeline.STATUS_MEASURED)
        self.assertEqual(result.reason, "")
        # 200-203 is bridged: the sound's and the picture's stretches are one.
        self.assertEqual(result.idle_stretches, [(100, 280), (400, 470), (500, 570)])
        self.assertEqual(result.idle_by, [[GAME, PICTURE], [PICTURE], [GAME]])
        self.assertEqual(result.picture_kinds, [timeline.PICTURE_STILL, timeline.PICTURE_STILL, ""])
        self.assertEqual(result.active_stretches, [(0, 100), (280, 400), (470, 500), (570, 600)])
        self.assertEqual((result.idle_seconds, result.idle_share), (320, round(320 / 600, 4)))
        self.assertEqual((result.game_track, result.region), (2, "whole frame"))
        self.assertEqual(result.rule_version, timeline.COMBINED_RULE_VERSION)
        self.assertEqual({name: item["status"] for name, item in result.signals.items()},
                         {GAME: timeline.STATUS_MEASURED, PICTURE: timeline.STATUS_MEASURED})
        self.assertTrue(all(end - start >= timeline.IDLE_MIN_SECONDS for start, end in result.idle_stretches))

    def test_measured_sound_and_unknown_picture_use_the_sound(self) -> None:
        result = timeline.combined_timeline(self.audio([(100, 200)]), timeline.unknown(self.UNKNOWN_PICTURE))
        self.assertEqual(result.status, timeline.STATUS_MEASURED)
        self.assertEqual(result.idle_stretches, [(100, 200)])
        self.assertEqual(result.idle_by, [[GAME]])
        self.assertEqual(result.reason, "Game picture not measured: keyframes are more than 10 s apart.")
        self.assertEqual(result.signals[PICTURE]["status"], timeline.STATUS_UNKNOWN)

    def test_estimated_sound_and_measured_picture_use_the_picture_only(self) -> None:
        result = timeline.combined_timeline(self.estimated([(100, 200)]), self.picture([(300, 400)]))
        self.assertEqual(result.status, timeline.STATUS_MEASURED)
        self.assertEqual(result.idle_stretches, [(300, 400)], "the full mix's quiet stretch is not used")
        self.assertEqual(result.idle_by, [[PICTURE]])
        # 226: the full mix's estimate was not used either, so the reason does not mention it.
        self.assertEqual(result.reason, "From the game picture only; the game sound was not used (Track 3, your game "
                                        "audio, is silent for the whole recording).")
        self.assertNotIn("full mix", result.reason)
        self.assertEqual(result.signals[GAME]["status"], timeline.STATUS_ESTIMATED)
        self.assertTrue(result.signals[GAME]["reason"].startswith("Estimated from the full mix (Track 1)"),
                        "the sound's own entry keeps its reason")

    def test_unknown_sound_and_measured_picture_use_the_picture(self) -> None:
        result = timeline.combined_timeline(timeline.unknown(self.UNKNOWN_SOUND, 600), self.picture([(300, 400)]))
        self.assertEqual(result.status, timeline.STATUS_MEASURED)
        self.assertEqual(result.idle_stretches, [(300, 400)])
        self.assertEqual(result.reason, "From the game picture only: more than one track could be the game audio.")
        self.assertIsNone(result.game_track)

    def test_estimated_sound_and_unknown_picture_keep_todays_estimate(self) -> None:
        sound = self.estimated([(100, 200)])
        result = timeline.combined_timeline(sound, timeline.unknown(self.UNKNOWN_PICTURE))
        self.assertEqual(result.status, timeline.STATUS_ESTIMATED)
        self.assertEqual((result.idle_stretches, result.idle_seconds, result.idle_share),
                         (sound.idle_stretches, sound.idle_seconds, sound.idle_share))
        self.assertEqual(result.idle_by, [[GAME]])
        self.assertEqual(result.reason, sound.reason + " Game picture not measured: keyframes are more than 10 s apart.")

    def test_unknown_sound_and_picture_are_unknown_with_both_reasons(self) -> None:
        result = timeline.combined_timeline(timeline.unknown(self.UNKNOWN_SOUND, 600),
                                            timeline.unknown(self.UNKNOWN_PICTURE))
        self.assertEqual(result.status, timeline.STATUS_UNKNOWN)
        self.assertEqual((result.idle_stretches, result.idle_share), ([], None))
        self.assertEqual(result.reason, "More than one track could be the game audio. "
                                        "Game picture not measured: keyframes are more than 10 s apart.")
        self.assertEqual(result.duration_seconds, 600)
        missing = timeline.combined_timeline(None, None)
        self.assertEqual(missing.status, timeline.STATUS_UNKNOWN)
        self.assertTrue(missing.reason)
        self.assertEqual(timeline.combined_timeline(self.audio([(100, 200)]), None).idle_stretches, [(100, 200)])
        self.assertEqual(timeline.combined_timeline(None, self.picture([(300, 400)])).idle_stretches, [(300, 400)])


class SignalOneUnchangedTests(unittest.TestCase):
    def test_the_game_audio_timeline_gives_what_it_gave_before(self) -> None:
        levels = [-20.0] * 300 + [-80.0] * 120 + [-20.0] * 175 + [-80.0] * 65 + [-35.5] * 40
        self.assertEqual(timeline.game_audio_timeline(levels, game_track=2).to_dict(), {
            "status": "measured", "duration_seconds": 700, "idle_seconds": 185, "idle_share": 0.2643,
            "idle_stretches": [[300, 420], [595, 660]], "active_stretches": [[0, 300], [420, 595], [660, 700]],
            "game_track": 2, "reason": "", "rule_version": 2,
            "idle_by": [], "picture_kinds": [], "signals": {}, "region": "",
        })
        self.assertEqual(timeline.TIMELINE_RULE_VERSION, 2)
        self.assertEqual((timeline.GAME_AUDIO_RULE_VERSION, timeline.GAME_PICTURE_RULE_VERSION,
                          timeline.COMBINED_RULE_VERSION), (2, 1, 3))


@unittest.skipUnless(FFMPEG, "FFmpeg is required")
class RealKeyframeTests(unittest.TestCase):
    def test_a_frozen_and_a_black_game_picture_are_found_from_real_keyframes(self) -> None:
        # 260 s with a keyframe every 2 s: moving, the picture frozen 40-120 s, moving, black 150-230 s,
        # moving. A small box blinks in a corner all the time (a clock, an overlay): a few cells only,
        # so a frozen game still reads still.
        video = ("testsrc2=size=320x180:rate=30:duration=260,split[a][b];"
                 "[a][b]freezeframes=first=1200:last=3599:replace=1200,"
                 "drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='between(t,150,230)',"
                 "drawbox=x=4:y=4:w=10:h=10:color=white:t=fill:enable='lt(mod(t,3),1.5)'[out0]")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", video,
                            "-c:v", "libx264", "-preset", "ultrafast", "-g", "60", "-keyint_min", "60",
                            "-sc_threshold", "0", "-pix_fmt", "yuv420p", "synthetic-race.mkv"],
                           cwd=root, check=True)
            # The shared sampler, as a feature reads an existing recording's picture on its own.
            sampled = frame_render.sample_picture(FFMPEG, root / "synthetic-race.mkv", (0, 0, 320, 180), root / "work")
        self.assertTrue(sampled["ok"], sampled)
        times, frames = sampled["times"], sampled["frames"]
        self.assertEqual(len(frames), len(times))
        self.assertEqual(len(times), 130, "keyframes only")
        self.assertEqual({len(frame) for frame in frames}, {SIZE})
        self.assertEqual(sampled["median_spacing_seconds"], 2.0)
        changes, luma = timeline.picture_change_per_second(times, frames, duration=260)
        result = timeline.game_picture_timeline(changes, luma=luma, region="whole frame")
        self.assertEqual(result.status, timeline.STATUS_MEASURED)
        self.assertEqual(len(result.idle_stretches), 2, result.idle_stretches)
        (frozen_start, frozen_end), (black_start, black_end) = result.idle_stretches
        self.assertLessEqual(abs(frozen_start - 40), 2)
        self.assertLessEqual(abs(frozen_end - 120), 2)
        self.assertLessEqual(abs(black_start - 150), 2)
        self.assertLessEqual(abs(black_end - 230), 2)
        self.assertEqual(result.picture_kinds, [timeline.PICTURE_STILL, timeline.PICTURE_BLACK])


if __name__ == "__main__":
    unittest.main()
