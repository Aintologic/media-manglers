"""264 (Wave C1): one rule for how speech moments are measured, and the background job that measures them.

The file route (a decoded WAV) and the streaming route (levels read as FFmpeg decodes) work from one inner function, and
give identical moments on the same audio. A change to the constants of that rule without a new ``ACTIVITY_RULE_VERSION``
fails here. The job reads a recording once, keeps its place in a checkpoint, and never needs the graphics card. Every
recording is generated with FFmpeg, and the facts go to a library of the test's own.
"""

from __future__ import annotations

import inspect
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

from media_manglers.core import app_cache, recording_records, track_levels, voice_track  # noqa: E402
from tests.outside_holder import OutsideHolder  # noqa: E402
from tests.test_wave8_track_levels import FFMPEG, FFPROBE, NOISE, SILENCE, TONE_10_TO_20, make_tracks  # noqa: E402

# Sound in bursts, the way speech comes: 2 seconds on, 8 off, then a stretch with shorter bursts. The other track's
# bursts come between them, as a different voice's would.
BURSTS = ("sine=frequency=300:sample_rate=48000:duration={s},"
          "volume='if(lt(mod(t,10),2),1,if(between(t,40,50)*lt(mod(t,3),0.8),0.5,0.001))':eval=frame")

OFFSET_BURSTS = BURSTS.replace("300", "700").replace("mod(t,10),2", "mod(t+5,10),2")


def facts():
    from media_manglers.core import speech_facts

    return speech_facts


class RuleConstantsTests(unittest.TestCase):
    def test_the_moments_rule_is_pinned_so_a_change_must_bump_its_version(self) -> None:
        # If this fails, the way moments are measured changed: bump ACTIVITY_RULE_VERSION, then these numbers.
        self.assertEqual(
            (voice_track.ACTIVITY_RULE_VERSION, voice_track.FRAME_SECONDS, voice_track.SILENT_PEAK_DBFS,
             voice_track.ACTIVE_ABOVE_FLOOR_DB, voice_track.ACTIVE_MIN_DBFS, voice_track.MERGE_GAP_SECONDS,
             voice_track.MIN_BURST_SECONDS, voice_track.MAX_BURST_SECONDS, voice_track.SAMPLE_RATE),
            (1, 0.05, -55.0, 12.0, -50.0, 0.6, 0.3, 15.0, 16000))

    def test_the_detection_rule_number_and_its_backend_copy_have_not_moved(self) -> None:
        self.assertEqual(voice_track.VOICE_RULE_VERSION, 5)

    def test_frames_give_the_same_answer_as_before_the_rule_was_split_out(self) -> None:
        # 40 quiet frames, a burst of 20, then quiet: worked out by hand from the rule's own numbers.
        frames = [-80.0] * 40 + [-20.0] * 20 + [-80.0] * 40
        activity = voice_track.activity_from_frames(frames, 3, 3276.8)
        self.assertEqual(activity.ordinal, 3)
        self.assertEqual(activity.intervals, [(2.0, 3.0)])
        self.assertEqual(activity.peak_dbfs, -20.0)
        self.assertEqual(activity.noise_floor_dbfs, -80.0)
        self.assertEqual(activity.active_ratio, 0.2)
        self.assertFalse(activity.silent)

    def test_details_do_not_widen_who_is_listened_to(self) -> None:
        source = inspect.getsource(voice_track.detect_voice_track)
        self.assertIn("library=library", source)
        self.assertNotIn("library=library or details", source)


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg is required")
class TwoRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_the_file_route_and_the_streaming_route_give_identical_moments(self) -> None:
        source = make_tracks(self.root / "rec.mkv", [BURSTS, NOISE, TONE_10_TO_20, SILENCE], 61)
        wavs = voice_track.extract_all_tracks(FFMPEG, source, 4, self.root / "wavs")
        by_file = {ordinal: voice_track.analyze_track_wav(path, ordinal) for ordinal, path in wavs.items()}
        frames: dict[int, list[float]] = {ordinal: [] for ordinal in range(4)}
        peaks: dict[int, int] = {ordinal: 0 for ordinal in range(4)}

        def got_frames(first, found, loudest):
            for ordinal, values in found.items():
                frames[ordinal].extend(values)
                peaks[ordinal] = max(peaks[ordinal], loudest[ordinal])

        voice_track.stream_levels(FFMPEG, source, range(4), self.root / "work", on_seconds=lambda first, found: None,
                                  on_frames=got_frames)
        for ordinal in range(4):
            with self.subTest(track=ordinal + 1):
                streamed = voice_track.activity_from_frames(frames[ordinal], ordinal, peaks[ordinal])
                expected = by_file[ordinal]
                self.assertEqual(streamed.intervals, expected.intervals)
                self.assertEqual(streamed.silent, expected.silent)
                self.assertEqual(streamed.active_ratio, expected.active_ratio)
                self.assertEqual(streamed.noise_floor_dbfs, expected.noise_floor_dbfs)
                self.assertEqual(streamed.peak_dbfs, expected.peak_dbfs)
                self.assertEqual(streamed.level_swing_db, expected.level_swing_db)
                self.assertEqual(streamed.loud_share, expected.loud_share)
        self.assertTrue(by_file[0].intervals, "the burst track has moments, so the comparison means something")

    def test_a_short_piece_read_by_seeking_is_that_piece_of_the_track(self) -> None:
        source = make_tracks(self.root / "rec.mkv", [SILENCE, TONE_10_TO_20], 30)
        piece = voice_track.extract_wav(FFMPEG, source, self.root / "piece.wav", ffmpeg_map="0:a:1", seek_seconds=12.0,
                                        limit_seconds=4.0)
        activity = voice_track.analyze_track_wav(piece, 1)
        self.assertAlmostEqual(activity.duration_seconds, 4.0, delta=0.1)
        self.assertGreater(activity.peak_dbfs, -20.0, "the tone is there from second 10 to 20")


def stub_transcriber(words: dict[int, str]):
    """Hears a fixed line per track: the track is in the probe file's name."""

    def transcribe(path: Path):
        ordinal = int(Path(path).stem.split("-")[-1])
        text = words.get(ordinal, "")
        return [{"text": text, "no_speech_prob": 0.01, "avg_logprob": -0.2}] if text else []

    transcribe.device = "cpu"  # type: ignore[attr-defined]
    return transcribe


SPOKEN = " ".join(["this is me talking about the race and the car"] * 6)
OTHER_VOICE = " ".join(["somebody else entirely describing weather forecasts tomorrow morning"] * 6)


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg is required")
class BackgroundJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = self.root / "library"
        self.cache = self.root / "cache"
        patcher = mock.patch.dict(os.environ, {recording_records.LIBRARY_ROOT_ENV: str(self.library)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _named(self, path: Path, sources: list[str], titles: list[str], seconds: int) -> Path:
        command = [FFMPEG, "-hide_banner", "-v", "error", "-y"]
        for source in sources:
            command += ["-f", "lavfi", "-i", source.format(s=seconds)]
        for index, title in enumerate(titles):
            command += ["-map", str(index), f"-metadata:s:a:{index}", f"title={title}"]
        command += ["-c:a", "aac", "-b:a", "96k", "-t", str(seconds), str(path)]
        subprocess.run(command, check=True)
        old = time.time() - 3600
        os.utime(path, (old, old))
        return path

    def _measure(self, source: Path, *, roles: str = "", transcriber=None, **options):
        request = {"track_roles": roles}
        if transcriber is not None:
            request["transcriber"] = transcriber
        return track_levels.measure(source, ffmpeg=FFMPEG, ffprobe=FFPROBE, cache=self.cache, facts=request, **options)

    def test_a_named_recording_gets_its_jumps_with_no_listening(self) -> None:
        source = self._named(self.root / "rec.mkv", [NOISE, BURSTS], ["Game", "My Narration"], 61)
        with mock.patch.object(voice_track, "whisper_transcriber", side_effect=AssertionError("listened")):
            outcome = self._measure(source)
        self.assertEqual(outcome["status"], track_levels.STATUS_READY)
        self.assertEqual(outcome["facts"], "stored")
        points = facts().jump_points(source)
        self.assertEqual((points.track, points.decided_by), (2, "track_name"))
        self.assertTrue(points.stretches)
        self.assertLess(points.stretches[0][0], points.stretches[0][1])
        measure = facts().known_measure(source)
        self.assertEqual(measure.measured_by, "background")
        self.assertEqual(sorted(measure.tracks), [1, 2], "every track's moments, so a later answer needs no read")

    def test_the_levels_are_the_same_as_without_the_facts(self) -> None:
        source = make_tracks(self.root / "a.mkv", [NOISE, BURSTS], 31)
        plain = self.root / "b.mkv"
        shutil.copy2(source, plain)
        self._measure(source, transcriber=stub_transcriber({}))
        track_levels.measure(plain, ffmpeg=FFMPEG, ffprobe=FFPROBE, cache=self.cache)
        self.assertEqual(track_levels.cached_levels(source, cache=self.cache).tracks,
                         track_levels.cached_levels(plain, cache=self.cache).tracks)

    def test_an_unnamed_recording_is_listened_to_on_the_processor_and_the_pick_is_stored(self) -> None:
        source = make_tracks(self.root / "rec.mkv", [NOISE, BURSTS], 61)
        loaded: list[tuple] = []

        def load(model_name, prefer_gpu, language_code):
            loaded.append((model_name, prefer_gpu, language_code))
            return stub_transcriber({1: SPOKEN})

        with mock.patch.object(voice_track, "whisper_transcriber", load):
            outcome = self._measure(source)
        self.assertEqual(outcome["facts"], "stored")
        self.assertEqual(loaded, [("base.en", False, "en")], "the processor, never the graphics card")
        points = facts().jump_points(source)
        self.assertEqual((points.track, points.decided_by), (2, "auto"))
        self.assertTrue(points.stretches)
        self.assertFalse(points.needs_listen or points.needs_read)

    def test_an_uncertain_result_gives_no_jumps_and_says_why(self) -> None:
        source = make_tracks(self.root / "rec.mkv", [BURSTS, OFFSET_BURSTS], 61)
        self._measure(source, transcriber=stub_transcriber({0: SPOKEN, 1: OTHER_VOICE}))
        points = facts().jump_points(source)
        self.assertEqual(points.stretches, ())
        self.assertEqual(points.reason, facts().NO_TRACK_REASON)
        self.assertFalse(points.needs_listen, "it is not asked again on every open")

    def _control(self, source: Path) -> tuple[Path, callable]:
        control = self.root / "control.json"
        control.write_text("{}", encoding="utf-8")

        def stop() -> None:
            control.write_text(json.dumps({"skip": [str(source)]}), encoding="utf-8")

        return control, stop

    def test_a_stop_keeps_its_place_and_the_next_measure_does_not_read_from_the_start(self) -> None:
        source = self._named(self.root / "rec.mkv", [NOISE, BURSTS], ["Game", "My Narration"], 1800)
        control, stop = self._control(source)
        reads: list[int] = []
        real = voice_track.stream_levels

        def counted(*args, **kwargs):
            reads.append(int(kwargs.get("start_second") or 0))
            return real(*args, **kwargs)

        saw: list[dict] = []

        def seen(event: dict) -> None:
            saw.append(event)
            if len(saw) == 2:
                stop()

        with mock.patch.object(voice_track, "stream_levels", counted):
            stopped = self._measure(source, control_path=str(control), report=seen)
            self.assertEqual(stopped["status"], track_levels.STATUS_STOPPED)
            self.assertIsNone(facts().known_measure(source), "nothing is stored until the read is whole")
            kept = list((self.cache / track_levels.FRAMES_KIND).glob("*"))
            self.assertEqual(sorted(path.suffix for path in kept), [".bin", ".json"])
            control.write_text("{}", encoding="utf-8")
            finished = self._measure(source, control_path=str(control))
        self.assertEqual(finished["status"], track_levels.STATUS_READY)
        self.assertEqual(reads[0], 0)
        self.assertGreater(reads[1], 0, "it carried on from where it was")
        self.assertEqual(list((self.cache / track_levels.FRAMES_KIND).glob("*")), [], "the checkpoint goes once the facts are stored")
        whole = voice_track.extract_all_tracks(FFMPEG, source, 2, self.root / "wavs")
        expected = voice_track.analyze_track_wav(whole[1], 1).intervals
        got = facts().known_measure(source).tracks[2]["moments"]
        self.assertEqual(len(got), len(expected), "a stopped and resumed read finds the same moments as one read")
        for found, wanted in zip(got, expected):
            self.assertAlmostEqual(found[0], wanted[0], delta=0.051)

    def test_a_stop_while_listening_keeps_the_read_and_nothing_is_read_again(self) -> None:
        # A real recording ends part way through a second.
        source = make_tracks(self.root / "rec.mkv", [BURSTS, OFFSET_BURSTS], 61)
        trimmed = self.root / "trimmed.mkv"
        subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-i", str(source), "-map", "0", "-c", "copy", "-t", "60.45", str(trimmed)], check=True)
        os.utime(trimmed, (time.time() - 3600, time.time() - 3600))
        source = trimmed
        control, stop = self._control(source)
        heard = []

        def stops_at_once(path):
            heard.append(path)
            stop()
            return []

        stops_at_once.device = "cpu"
        first = self._measure(source, control_path=str(control), transcriber=stops_at_once)
        self.assertEqual(first["status"], track_levels.STATUS_STOPPED)
        self.assertEqual(first["facts"], "stopped")
        self.assertEqual(len(heard), 1)
        control.write_text("{}", encoding="utf-8")
        with mock.patch.object(voice_track, "stream_levels", side_effect=AssertionError("read again")):
            second = self._measure(source, control_path=str(control), transcriber=stub_transcriber({1: SPOKEN}))
        self.assertEqual(second["status"], track_levels.STATUS_READY)
        self.assertEqual(facts().jump_points(source).track, 2)

    def test_a_recording_with_a_whole_waveform_gets_one_more_read_and_its_lanes_stay(self) -> None:
        source = self._named(self.root / "rec.mkv", [NOISE, BURSTS], ["Game", "My Narration"], 31)
        track_levels.measure(source, ffmpeg=FFMPEG, ffprobe=FFPROBE, cache=self.cache)
        before = track_levels.cached_levels(source, cache=self.cache)
        told: list[dict] = []
        outcome = self._measure(source, report=told.append)
        self.assertEqual(outcome["facts"], "stored")
        self.assertEqual(track_levels.cached_levels(source, cache=self.cache).tracks, before.tracks)
        self.assertFalse(any(event.get("tracks") for event in told), "the lanes are not told to start again")
        told.clear()
        with mock.patch.object(voice_track, "stream_levels", side_effect=AssertionError("read again")):
            self.assertEqual(self._measure(source)["status"], track_levels.STATUS_READY, "once per recording")

    def test_a_listening_failure_never_fails_the_waveform(self) -> None:
        source = make_tracks(self.root / "rec.mkv", [BURSTS, OFFSET_BURSTS], 31)
        trimmed = self.root / "trimmed.mkv"
        subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-i", str(source), "-map", "0", "-c", "copy", "-t", "30.45", str(trimmed)], check=True)
        os.utime(trimmed, (time.time() - 3600, time.time() - 3600))
        source = trimmed
        with mock.patch.object(voice_track, "whisper_transcriber", side_effect=RuntimeError("no Whisper here")):
            outcome = self._measure(source)
        self.assertEqual(outcome["status"], track_levels.STATUS_READY)
        self.assertEqual(outcome["facts"], "not_stored")
        self.assertTrue(track_levels.cached_levels(source, cache=self.cache).complete)
        with mock.patch.object(voice_track, "stream_levels", side_effect=AssertionError("read again")):
            again = self._measure(source, transcriber=stub_transcriber({1: SPOKEN}))
        self.assertEqual(again["facts"], "stored", "a later try listens with nothing read again")
        self.assertEqual(list((self.cache / track_levels.FRAMES_KIND).glob("*")), [])

    def test_the_checkpoint_holds_numbers_only_and_clear_cache_takes_it(self) -> None:
        source = self._named(self.root / "secret-session.mkv", [NOISE, BURSTS], ["Game", "My Narration"], 1800)
        control, stop = self._control(source)
        saw: list[dict] = []

        def seen(event: dict) -> None:
            saw.append(event)
            if len(saw) == 2:
                stop()

        self._measure(source, control_path=str(control), report=seen)
        notes = next((self.cache / track_levels.FRAMES_KIND).glob("*.json"))
        text = notes.read_text(encoding="utf-8")
        self.assertNotIn("secret", text + notes.name)
        self.assertEqual(sorted(json.loads(text)), ["complete", "mtime_ns", "peaks", "rule", "seconds", "size", "tracks"])
        app_cache.clear(self.cache)
        self.assertEqual(list((self.cache / track_levels.FRAMES_KIND).glob("*")) if (self.cache / track_levels.FRAMES_KIND).exists() else [], [])

    def test_a_held_checkpoint_never_fails_the_waveform(self) -> None:
        # Antivirus rule: a scanner holding the checkpoint for a moment. Windows refuses its removal while it is held;
        # the shared helper waits a bounded time, and whatever comes of it the waveform and the facts stand.
        source = self._named(self.root / "rec.mkv", [NOISE, BURSTS], ["Game", "My Narration"], 31)
        real = track_levels.safe_write.remove
        held: list[Path] = []

        def remove_while_held(path, **options):
            path = Path(path)
            if path.suffix == ".bin" and not held:
                held.append(path)
                with OutsideHolder(path):
                    return real(path, **options)
            return real(path, **options)

        with mock.patch.object(track_levels.safe_write, "remove", remove_while_held):
            outcome = self._measure(source)
        self.assertTrue(held, "the holder really held it")
        self.assertEqual(outcome["status"], track_levels.STATUS_READY)
        self.assertEqual(outcome["facts"], "stored")
        self.assertTrue(track_levels.cached_levels(source, cache=self.cache).complete)
        self.assertTrue(facts().jump_points(source).stretches)

    def test_a_file_that_changes_during_the_read_stores_nothing(self) -> None:
        source = self._named(self.root / "rec.mkv", [NOISE, BURSTS], ["Game", "My Narration"], 31)
        real = voice_track.stream_levels

        def changed(*args, **kwargs):
            result = real(*args, **kwargs)
            later = time.time() - 60
            os.utime(source, (later, later))
            return result

        with mock.patch.object(voice_track, "stream_levels", changed):
            outcome = self._measure(source)
        self.assertEqual(outcome["status"], track_levels.STATUS_CHANGED)
        self.assertIsNone(facts().known_measure(source))

    def test_without_facts_the_measure_is_what_it_always_was(self) -> None:
        source = make_tracks(self.root / "rec.mkv", [NOISE, BURSTS], 31)
        outcome = track_levels.measure(source, ffmpeg=FFMPEG, ffprobe=FFPROBE, cache=self.cache)
        self.assertNotIn("facts", outcome)
        self.assertIsNone(facts().known_measure(source))


if __name__ == "__main__":
    unittest.main()
