"""125 Part 2, 135 (Wave 8): the sound level of every track, measured once and kept.

Every recording here is generated with FFmpeg. The streaming read must give the very values the Raw
bin's decode-to-WAV path gives (one rule), keep nothing private in the cache, save what it has when
it is stopped and carry on from there, wait while it is paused without calling that a stall, and
refuse a cache folder on the recordings drive.
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
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers import cli  # noqa: E402
from media_manglers.core import app_cache, raw_bin_library, track_levels, voice_track  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def make_tracks(path: Path, sources: list[str], seconds: int) -> Path:
    """One audio track per lavfi source, AAC in Matroska, ``seconds`` long."""

    command = [FFMPEG, "-hide_banner", "-v", "error", "-y"]
    for source in sources:
        command += ["-f", "lavfi", "-i", source.format(s=seconds)]
    for index in range(len(sources)):
        command += ["-map", str(index)]
    command += ["-c:a", "aac", "-b:a", "96k", "-t", str(seconds), str(path)]
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(command, check=True)
    old = time.time() - 3600
    os.utime(path, (old, old))
    return path


SILENCE = "anullsrc=r=48000:cl=mono:d={s}"
NOISE = "anoisesrc=color=pink:amplitude=0.3:sample_rate=48000:duration={s}"
TONE_10_TO_20 = "sine=frequency=440:sample_rate=48000:duration={s},volume='if(between(t,10,20),1,0)':eval=frame"
STEREO_SPEECHY = "sine=frequency=300:sample_rate=48000:duration={s},volume='if(lt(mod(t,4),1.2),1,0)':eval=frame,aformat=channel_layouts=stereo"


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg is required")
class TrackLevelsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cache = self.root / "cache"
        self.environment = mock.patch.dict(os.environ, {raw_bin_library.LIBRARY_ROOT_ENV: str(self.root / "library")})
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temp.cleanup()

    def _measure(self, source: Path, **options):
        return track_levels.measure(source, ffmpeg=FFMPEG, ffprobe=FFPROBE, cache=self.cache, **options)

    def test_the_streaming_read_gives_the_raw_bins_own_values(self) -> None:
        source = make_tracks(self.root / "rec.mkv", [NOISE, STEREO_SPEECHY, TONE_10_TO_20], 37)
        wavs = voice_track.extract_all_tracks(FFMPEG, source, 3, self.root / "wavs")
        expected = {ordinal: voice_track.analyze_track_wav(path, ordinal).second_levels for ordinal, path in wavs.items()}
        found: dict[int, list[float]] = {0: [], 1: [], 2: []}

        def got(first, levels):
            for ordinal, values in levels.items():
                self.assertEqual(len(found[ordinal]), first, "seconds arrive in order with nothing missing")
                found[ordinal].extend(values)

        measured, stopped = voice_track.stream_levels(FFMPEG, source, [0, 1, 2], self.root / "work", on_seconds=got)
        self.assertFalse(stopped)
        self.assertEqual(measured, len(expected[0]))
        for ordinal in range(3):
            self.assertEqual(len(found[ordinal]), len(expected[ordinal]))
            worst = max(abs(a - b) for a, b in zip(found[ordinal], expected[ordinal], strict=True))
            self.assertLessEqual(worst, 0.1, f"track {ordinal + 1} differs by {worst} dB")

    def test_a_tone_shows_only_where_it_plays_and_silence_sits_at_the_floor(self) -> None:
        source = make_tracks(self.root / "rec.mkv", [SILENCE, TONE_10_TO_20], 30)
        result = self._measure(source)
        self.assertEqual(result["status"], track_levels.STATUS_READY)
        levels = track_levels.cached_levels(source, cache=self.cache)
        self.assertTrue(levels.complete)
        self.assertEqual(sorted(levels.tracks), [1, 2])
        self.assertTrue(all(value <= -100 for value in levels.tracks[1]), levels.tracks[1][:5])
        loud = [second for second, value in enumerate(levels.tracks[2]) if value > -30]
        self.assertEqual((loud[0], loud[-1]), (10, 19), loud)

    def test_the_cache_holds_numbers_only_and_a_second_measure_reads_nothing(self) -> None:
        source = make_tracks(self.root / "My private session name.mkv", [NOISE, TONE_10_TO_20], 20)
        self._measure(source)
        files = [path for path in self.cache.rglob("*") if path.is_file()]
        self.assertEqual(len(files), 1)
        self.assertNotIn("private", files[0].name.lower())
        text = files[0].read_text(encoding="utf-8")
        self.assertNotIn("private", text.lower())
        self.assertNotIn(str(self.root).lower(), text.lower())
        with mock.patch.object(voice_track, "stream_levels", side_effect=AssertionError("read again")):
            again = self._measure(source)
        self.assertEqual(again["status"], track_levels.STATUS_READY)

    def test_a_stop_keeps_what_was_measured_and_the_next_measure_carries_on(self) -> None:
        source = make_tracks(self.root / "long.mkv", [NOISE, TONE_10_TO_20], 900)
        control = self.root / "run-control.json"
        control.write_text(json.dumps({"pause": False, "skip": []}), encoding="utf-8")

        def stop_after_first(_event):
            control.write_text(json.dumps({"pause": False, "skip": [str(source)]}), encoding="utf-8")

        first = self._measure(source, control_path=str(control), report=stop_after_first)
        self.assertEqual(first["status"], track_levels.STATUS_STOPPED)
        partial = track_levels.cached_levels(source, cache=self.cache)
        self.assertFalse(partial.complete)
        self.assertGreater(partial.seconds, 0)
        self.assertLess(partial.seconds, 900)

        starts = []
        real = voice_track.stream_levels

        def record(*args, **kwargs):
            starts.append(kwargs.get("start_second"))
            return real(*args, **kwargs)

        control.write_text(json.dumps({"pause": False, "skip": []}), encoding="utf-8")
        with mock.patch.object(voice_track, "stream_levels", side_effect=record):
            second = self._measure(source, control_path=str(control))
        self.assertEqual(second["status"], track_levels.STATUS_READY)
        self.assertEqual(starts, [partial.seconds], "the next measure starts where the stop left off")
        done = track_levels.cached_levels(source, cache=self.cache)
        self.assertTrue(done.complete)
        self.assertEqual(done.seconds, 900)
        loud = [second for second, value in enumerate(done.tracks[2]) if value > -30]
        self.assertEqual((loud[0], loud[-1]), (10, 19))
        self.assertFalse(any(path.name.startswith("media_manglers_track_levels") for path in self.root.iterdir()))

    def test_a_track_that_ends_early_does_not_cut_the_others_short(self) -> None:
        # Track 2 stops after 30 s of a 60 s recording. Reading the tracks together must still measure
        # all 60 s of Track 1, and Track 2 is silent after its end.
        source = make_tracks(self.root / "rec.mkv", [NOISE, "sine=frequency=440:sample_rate=48000:duration=30"], 60)
        result = self._measure(source)
        self.assertEqual(result["status"], track_levels.STATUS_READY)
        levels = track_levels.cached_levels(source, cache=self.cache)
        self.assertGreaterEqual(len(levels.tracks[1]), 59, "Track 1 is measured to the end")
        self.assertTrue(all(value > -40 for value in levels.tracks[1][:59]))
        self.assertTrue(all(value > -40 for value in levels.tracks[2][1:29]))
        self.assertTrue(all(value <= -90 for value in levels.tracks[2][31:59]), levels.tracks[2][28:40])

    def test_a_stop_ends_at_once_even_while_measuring_waits(self) -> None:
        # A stop that comes while the read is paused: FFmpeg's output has filled up, and nothing more
        # is taken from it. The stop must not then sit waiting for the reader.
        source = make_tracks(self.root / "rec.mkv", [NOISE, NOISE], 600)
        state = {"paused": False, "stopped": False}

        def got(_first, _levels):
            state["paused"] = True

        def stop_after_a_while() -> bool:
            if state["paused"] and not state.get("since"):
                state["since"] = time.monotonic()
            return bool(state.get("since")) and time.monotonic() - state["since"] > 1.0

        started = time.monotonic()
        _measured, stopped = voice_track.stream_levels(
            FFMPEG, source, [0, 1], self.root / "work", on_seconds=got,
            paused=lambda: state["paused"], stopped=stop_after_a_while)
        self.assertTrue(stopped)
        self.assertLess(time.monotonic() - started, 4.5, "the stop does not wait out the reader")

    def test_a_pause_is_waited_out_and_never_called_a_stall(self) -> None:
        source = make_tracks(self.root / "rec.mkv", [NOISE], 60)
        clock = {"paused_until": time.monotonic() + 2.0}
        measured, stopped = voice_track.stream_levels(
            FFMPEG, source, [0], self.root / "work", on_seconds=lambda *_args: None,
            paused=lambda: time.monotonic() < clock["paused_until"], stall_seconds=0.5)
        self.assertFalse(stopped)
        self.assertEqual(measured, 60)

    def test_a_file_that_changed_is_measured_again(self) -> None:
        source = make_tracks(self.root / "rec.mkv", [NOISE], 10)
        self._measure(source)
        self.assertIsNotNone(track_levels.cached_levels(source, cache=self.cache))
        newer = time.time() - 600
        os.utime(source, (newer, newer))
        self.assertIsNone(track_levels.cached_levels(source, cache=self.cache))

    def test_a_file_still_being_recorded_is_not_measured(self) -> None:
        source = make_tracks(self.root / "rec.mkv", [NOISE], 10)
        os.utime(source, None)
        result = self._measure(source)
        self.assertEqual(result["status"], track_levels.STATUS_IN_USE)
        self.assertFalse(self.cache.exists() and any(self.cache.rglob("*.json")))

    def test_a_cache_on_the_recordings_drive_is_refused(self) -> None:
        recordings = self.root / "recordings"
        source = make_tracks(recordings / "rec.mkv", [NOISE], 10)
        with self.assertRaises(ValueError) as refused:
            track_levels.measure(source, ffmpeg=FFMPEG, ffprobe=FFPROBE, cache=recordings / "cache",
                                 recordings_folders=[str(recordings)])
        self.assertIn("read-only", str(refused.exception))
        self.assertFalse((recordings / "cache").exists())

    def test_the_raw_bins_levels_count_only_while_its_row_is_still_this_file(self) -> None:
        from tests.test_raw_bin_library import HearingTranscriber, make_recording

        raw = self.root / "raw"
        source = make_recording(raw / "session.mkv", seconds=40)
        old = time.time() - 3600
        os.utime(source, (old, old))
        with mock.patch.dict(os.environ, {app_cache.CACHE_ROOT_ENV: str(self.cache)}):
            raw_bin_library.scan(raw_bin_library.ScanOptions(
                folders=[str(raw)], ffmpeg=FFMPEG, ffprobe=FFPROBE, transcriber=HearingTranscriber({2}),
                stable_after_seconds=0))
        found = track_levels.cached_levels(source, cache=self.cache)
        self.assertEqual(found.origin, "library")
        self.assertEqual(sorted(found.tracks), [1, 2, 3])
        later = old + 60
        os.utime(source, (later, later))
        self.assertIsNone(track_levels.cached_levels(source, cache=self.cache),
                          "a file changed since the scan does not borrow the scan's levels")

    def test_the_helper_command_measures_each_recording_and_reports_progress(self) -> None:
        sources = [make_tracks(self.root / f"rec{index}.mkv", [NOISE, TONE_10_TO_20], 25) for index in range(2)]
        request, result = self.root / "request.json", self.root / "result.json"
        request.write_text(json.dumps({"payload": {
            "paths": [str(item) for item in sources], "ffmpeg": FFMPEG, "ffprobe": FFPROBE,
            "cache_folder": str(self.root / "chosen")}}), encoding="utf-8")
        with mock.patch.object(track_levels.raw_bin_library, "below_normal_priority"), \
                mock.patch("builtins.print") as printed:
            self.assertEqual(cli.main(["track-levels", "--request-file", str(request), "--result-file", str(result)]), 0)
        data = json.loads(result.read_text(encoding="utf-8"))["data"]
        self.assertEqual([item["status"] for item in data["results"]], ["ready", "ready"])
        lines = [str(call.args[0]) for call in printed.call_args_list]
        self.assertTrue(any(line.startswith(track_levels.PROGRESS_PREFIX) and '"done"' in line for line in lines))
        chosen = app_cache.cache_root(str(self.root / "chosen"))
        for source in sources:
            self.assertTrue(track_levels.cached_levels(source, cache=chosen).complete)

    def test_measure_the_sound_again_starts_from_the_beginning_and_replaces_the_entry(self) -> None:
        source = make_tracks(self.root / "rec.mkv", [SILENCE, TONE_10_TO_20], 30)
        # The helper's own cache folder, the one a chosen cache folder becomes.
        cache = app_cache.cache_root(str(self.root / "chosen"))
        track_levels.measure(source, ffmpeg=FFMPEG, ffprobe=FFPROBE, cache=cache)
        # A wrong entry (an older build, a damaged file): a normal measure trusts it and reads nothing.
        wrong = track_levels.Levels(tracks={1: [-5.0] * 30, 2: [-5.0] * 30}, duration_seconds=30.0, complete=True)
        track_levels._save(cache, source, source.stat(), wrong)
        with mock.patch.object(voice_track, "stream_levels", side_effect=AssertionError("read again")):
            track_levels.measure(source, ffmpeg=FFMPEG, ffprobe=FFPROBE, cache=cache)
        request, result = self.root / "request.json", self.root / "result.json"
        request.write_text(json.dumps({"payload": {
            "paths": [str(source)], "fresh_paths": [str(source)], "ffmpeg": FFMPEG, "ffprobe": FFPROBE,
            "cache_folder": str(self.root / "chosen")}}), encoding="utf-8")
        starts = []
        real = voice_track.stream_levels

        def record(*args, **kwargs):
            starts.append(kwargs.get("start_second"))
            return real(*args, **kwargs)

        with mock.patch.object(track_levels.raw_bin_library, "below_normal_priority"), \
                mock.patch.object(voice_track, "stream_levels", side_effect=record), mock.patch("builtins.print"):
            self.assertEqual(cli.main(["track-levels", "--request-file", str(request), "--result-file", str(result)]), 0)
        self.assertEqual(starts, [0], "measured again from the first second")
        again = track_levels.cached_levels(source, cache=cache)
        self.assertTrue(again.complete)
        loud = [second for second, value in enumerate(again.tracks[2]) if value > -30]
        self.assertEqual((loud[0], loud[-1]), (10, 19))
        self.assertTrue(all(value <= -100 for value in again.tracks[1]))


class SoundStretchesTests(unittest.TestCase):
    """The one "is there sound" rule, next to the idle rule in the activity timeline."""

    def test_speech_over_a_quiet_floor_is_sound_and_short_gaps_join(self) -> None:
        from media_manglers.core.activity_timeline import sound_stretches

        levels = [-70.0] * 30
        for second in (5, 6, 7, 9, 10, 20, 21):
            levels[second] = -30.0
        self.assertEqual(sound_stretches(levels), [(5, 11), (20, 22)])

    def test_a_silent_track_and_hiss_have_no_sound(self) -> None:
        from media_manglers.core.activity_timeline import sound_stretches

        self.assertEqual(sound_stretches([-120.0] * 50), [])
        self.assertEqual(sound_stretches([-75.0 + (second % 3) for second in range(50)]), [])
        self.assertEqual(sound_stretches([]), [])

    def test_a_track_loud_all_the_time_counts_only_what_stands_out(self) -> None:
        from media_manglers.core.activity_timeline import sound_stretches

        levels = [-25.0] * 40
        levels[30] = levels[31] = -8.0
        self.assertEqual(sound_stretches(levels), [(30, 32)])


if __name__ == "__main__":
    unittest.main()
