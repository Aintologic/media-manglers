"""125 Part 2, 135 (Wave 8): one waveform build at a time, in the background.

The service is driven as the app drives it: the player asks for the open recording, a finished run
hands over its recordings, a run starting stops the build (what it measured is kept) and closing
stops it at once. Measuring runs the real ``track-levels`` helper on generated recordings.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from media_manglers.core import app_cache, raw_bin_library, speech_facts, track_levels  # noqa: E402
from media_manglers.core.whisper_models import MISSING, ModelNotApproved  # noqa: E402
from media_manglers_workbench.levels_service import STATE_WAITING_FOR_RUN, LevelsService  # noqa: E402
from media_manglers_workbench.recording_lists import path_key  # noqa: E402
from media_manglers_workbench.runner import RunnerResult  # noqa: E402
from tests.test_wave8_track_levels import FFMPEG, FFPROBE, NOISE, TONE_10_TO_20, make_tracks  # noqa: E402
from tests.test_workbench_bug_reports import _resources  # noqa: E402
from tests.wave8_helpers import CountingLevelsRunner, helper_resources  # noqa: E402


class Availability(QObject):
    changed = Signal()


class Batch:
    def __init__(self) -> None:
        self.told: list[tuple[int, int, bool]] = []

    def on_waveforms(self, ready: int, total: int, working: bool) -> None:
        self.told.append((ready, total, working))


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg is required")
class SpeechFactsJobTests(unittest.TestCase):
    """264: the same queue measures speech facts, with everything the queue already does."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        from media_manglers.core import speech_facts

        self.speech_facts = speech_facts
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = mock.patch.dict(os.environ, {
            raw_bin_library.LIBRARY_ROOT_ENV: str(self.root / "library"),
            app_cache.CACHE_ROOT_ENV: str(self.root / "cache"),
        })
        self.environment.start()
        self.idle = True
        self.availability = Availability()
        resources = helper_resources(_resources(), FFMPEG, FFPROBE)
        self.service = LevelsService(resources=lambda: resources, settings=lambda: {}, is_idle=lambda: self.idle,
                                     runner_factory=CountingLevelsRunner, availability_changed=self.availability.changed,
                                     facts_lookup=lambda path: speech_facts.jump_points(path),
                                     facts_request=lambda: {"track_roles": ""})
        self.told: list[str] = []
        self.service.facts_changed.connect(self.told.append)
        CountingLevelsRunner.runs = []
        CountingLevelsRunner.payloads = []

    def tearDown(self) -> None:
        self.service.shutdown()
        self.app.processEvents()
        self.environment.stop()
        self.temp.cleanup()

    def _wait(self, condition, seconds: float = 90.0) -> None:
        deadline = time.monotonic() + seconds
        while not condition() and time.monotonic() < deadline:
            QTest.qWait(25)
        self.assertTrue(condition(), "waited too long")

    def _named(self, name: str, seconds: int) -> Path:
        path = self.root / name
        command = [FFMPEG, "-hide_banner", "-v", "error", "-y"]
        for source in (NOISE, TONE_10_TO_20):
            command += ["-f", "lavfi", "-i", source.format(s=seconds)]
        for index, title in enumerate(("Game", "My Narration")):
            command += ["-map", str(index), f"-metadata:s:a:{index}", f"title={title}"]
        subprocess.run([*command, "-c:a", "aac", "-b:a", "96k", "-t", str(seconds), str(path)], check=True)
        old = time.time() - 3600
        os.utime(path, (old, old))
        return path

    def _stretches(self, path: Path):
        facts = self.service.facts_for(path)
        return facts.stretches if facts is not None else ()

    def test_opening_a_recording_measures_it_and_the_facts_arrive_without_reopening(self) -> None:
        source = self._named("rec.mkv", 40)
        self.service.want(source)
        self._wait(lambda: bool(self._stretches(source)))
        self.assertEqual(self.service.facts_for(source).track, 2)
        self.assertEqual(self.service.facts_for(source).stretches, ((9.5, 20.05),))
        self.assertIn(path_key(source), self.told)
        self.assertEqual(len(CountingLevelsRunner.runs), 1, "the waveform and the facts come from one read")

    def test_a_recording_with_a_whole_waveform_gets_one_read_then_never_again(self) -> None:
        source = self._named("rec.mkv", 40)
        track_levels.measure(source, ffmpeg=FFMPEG, ffprobe=FFPROBE, cache=self.root / "cache")
        self.service.want(source)
        self._wait(lambda: bool(self._stretches(source)))
        self.assertEqual(len(CountingLevelsRunner.runs), 1)
        self.service.want(source)
        self._wait(lambda: path_key(source) in self.service._looked_up and path_key(source) not in self.service._looking)
        QTest.qWait(300)
        self.assertEqual(len(CountingLevelsRunner.runs), 1, "once per recording")

    def test_nothing_is_measured_during_a_run(self) -> None:
        source = self._named("rec.mkv", 40)
        self.idle = False
        self.service.want(source)
        self._wait(lambda: self.service.state_for(source) == STATE_WAITING_FOR_RUN)
        self.assertEqual(CountingLevelsRunner.runs, [])
        self.idle = True
        self.availability.changed.emit()
        self._wait(lambda: bool(self._stretches(source)))

    def test_a_run_starting_stops_the_job_and_it_carries_on_from_its_checkpoint(self) -> None:
        source = self._named("rec.mkv", 3000)
        self.service.want(source)
        self._wait(lambda: self.service.levels_for(source) is not None and self.service.levels_for(source).seconds > 10)
        self.idle = False
        self.service.stop_for_run()
        self._wait(lambda: self.service._build is None)
        kinds = [path.suffix for path in (self.root / "cache" / track_levels.FRAMES_KIND).glob("*")]
        self.assertEqual(sorted(kinds), [".bin", ".json"], "the place is kept")
        self.assertIsNone(self.speech_facts.known_measure(source))
        self.assertEqual(self.service.state_for(source), STATE_WAITING_FOR_RUN)
        reached = self.service.levels_for(source).seconds
        self.idle = True
        self.availability.changed.emit()
        self._wait(lambda: bool(self._stretches(source)), 240)
        self.assertEqual(len(CountingLevelsRunner.runs), 2)
        self.assertGreater(reached, 0)
        self.assertEqual(list((self.root / "cache" / track_levels.FRAMES_KIND).glob("*")), [])

    def test_closing_never_waits_on_the_job(self) -> None:
        source = self._named("rec.mkv", 3000)
        self.service.want(source)
        self._wait(lambda: self.service.levels_for(source) is not None and self.service.levels_for(source).seconds > 10)
        started = time.monotonic()
        self.service.shutdown()
        self.assertLess(time.monotonic() - started, 5.0)

    def test_only_what_is_opened_or_a_run_just_used_is_measured(self) -> None:
        opened = self._named("opened.mkv", 40)
        self._named("never-opened.mkv", 40)
        ran = self._named("ran.mkv", 40)
        self.service.want(opened)
        self.service.queue([ran])
        self._wait(lambda: bool(self._stretches(opened)) and bool(self._stretches(ran)))
        names = {Path(payload["paths"][0]).name for payload in CountingLevelsRunner.payloads}
        self.assertEqual(names, {"opened.mkv", "ran.mkv"}, "no sweep of the whole library")

    def test_a_recording_that_has_its_facts_is_not_read_for_them(self) -> None:
        source = self._named("rec.mkv", 40)
        self.service.want(source)
        self._wait(lambda: bool(self._stretches(source)))
        CountingLevelsRunner.payloads.clear()
        self.service.queue([source])
        QTest.qWait(300)
        self.assertEqual(CountingLevelsRunner.payloads, [])


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg is required")
class LevelsServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = mock.patch.dict(os.environ, {
            raw_bin_library.LIBRARY_ROOT_ENV: str(self.root / "library"),
            app_cache.CACHE_ROOT_ENV: str(self.root / "cache"),
        })
        self.environment.start()
        self.idle = True
        self.availability = Availability()
        resources = helper_resources(_resources(), FFMPEG, FFPROBE)
        self.changes: list[str] = []
        self.service = LevelsService(resources=lambda: resources, settings=lambda: {}, is_idle=lambda: self.idle,
                                     runner_factory=CountingLevelsRunner,
                                     availability_changed=self.availability.changed)
        self.service.levels_changed.connect(self.changes.append)
        CountingLevelsRunner.runs = []
        CountingLevelsRunner.payloads = []

    def tearDown(self) -> None:
        self.service.shutdown()
        self.app.processEvents()
        self.environment.stop()
        self.temp.cleanup()

    def _wait(self, condition, seconds: float = 60.0) -> None:
        deadline = time.monotonic() + seconds
        while not condition() and time.monotonic() < deadline:
            QTest.qWait(25)
        self.assertTrue(condition(), "waited too long")

    def _complete(self, path: Path) -> bool:
        levels = self.service.levels_for(path)
        return levels is not None and levels.complete

    def test_the_players_recording_is_measured_and_its_lanes_fill_in_as_it_goes(self) -> None:
        source = make_tracks(self.root / "rec.mkv", [NOISE, TONE_10_TO_20], 600)
        self.service.want(source)
        self._wait(lambda: self._complete(source))
        levels = self.service.levels_for(source)
        self.assertEqual(sorted(levels.tracks), [1, 2])
        self.assertEqual(levels.seconds, 600)
        self.assertGreater(len(self.changes), 2, "the levels arrived part by part, not only at the end")
        self.assertTrue(track_levels.cached_levels(source, cache=self.root / "cache").complete)
        self.service.want(source)
        self.assertEqual(len(CountingLevelsRunner.runs), 1, "a measured recording is never read again")

    def test_measure_the_sound_again_measures_the_whole_recording_from_the_start(self) -> None:
        source = make_tracks(self.root / "rec.mkv", [NOISE, TONE_10_TO_20], 120)
        self.service.want(source)
        self._wait(lambda: self._complete(source))
        self.service.measure_again(source)
        self.assertIsNone(self.service.levels_for(source), "the old waveforms are put away at once")
        self.assertTrue(self.service.state_for(source).startswith("Measuring the sound of every track"))
        self._wait(lambda: len(CountingLevelsRunner.payloads) == 2)
        self.assertFalse(self._complete(source), "the old waveforms do not come back while it measures again")
        self._wait(lambda: self._complete(source) and self.service._build is None)
        self.assertEqual([payload["fresh_paths"] for payload in CountingLevelsRunner.payloads], [[], [str(source)]])
        self.assertEqual(self.service.levels_for(source).seconds, 120)
        self.assertEqual(self.service.state_for(source), "")

    def test_the_measuring_line_says_how_long_is_left(self) -> None:
        from media_manglers_workbench.levels_service import _time_left

        self.assertEqual(_time_left(20), "less than a minute left")
        self.assertEqual(_time_left(80), "about 1 minute left")
        self.assertEqual(_time_left(130), "about 2 minutes left")
        # The helper's progress lines, as a long recording sends them, on a clock the test moves: a
        # synthetic file measures too fast to see a real estimate.
        source = self.root / "long.mkv"
        key = path_key(source)
        self.service._paths[key] = source
        self.service._building = key
        clock = [100.0]

        def line(first: int, seconds: int) -> str:
            return track_levels.PROGRESS_PREFIX + json.dumps(
                {"first": first, "seconds": seconds, "duration": 6000.0, "tracks": {"1": [-40.0] * (seconds - first)}})

        with mock.patch("media_manglers_workbench.levels_service.time.monotonic", side_effect=lambda: clock[0]):
            self.service._on_line(line(0, 60))
            self.assertEqual(self.service.state_for(source), "Measuring the sound of every track: 1%.",
                             "no guess from the first line")
            clock[0] = 104.0
            self.service._on_line(line(60, 120))
        # 60 seconds measured in 4 s: 5,880 seconds left take 392 s.
        self.assertEqual(self.service.state_for(source),
                         "Measuring the sound of every track: 2% (about 7 minutes left).")
        self.service._building = None

    def test_a_run_that_ends_before_the_build_has_stopped_does_not_leave_the_queue_waiting(self) -> None:
        # A short run (a scan with nothing new, one that fails at once) is over before the helper has
        # finished stopping, so no later "the app is idle" notice comes. Measuring must carry on anyway.
        source = make_tracks(self.root / "long.mkv", [NOISE, TONE_10_TO_20], 1800)
        self.service.want(source)
        self._wait(lambda: (self.service.levels_for(source) or track_levels.Levels()).seconds > 0)
        self.service.stop_for_run()  # the run starts and ends at once: the app is idle throughout
        self._wait(lambda: self._complete(source), 60)
        self.assertEqual(len(CountingLevelsRunner.runs), 2)

    def test_a_build_waits_for_its_lookup_so_a_checkpoint_is_carried_on_in_place(self) -> None:
        source = make_tracks(self.root / "long.mkv", [NOISE, TONE_10_TO_20], 900)
        control = self.root / "control.json"
        control.write_text(json.dumps({"pause": False, "skip": []}), encoding="utf-8")

        def stop_after_first(_event):
            control.write_text(json.dumps({"pause": False, "skip": [str(source)]}), encoding="utf-8")

        track_levels.measure(source, ffmpeg=FFMPEG, ffprobe=FFPROBE, cache=self.root / "cache",
                             control_path=str(control), report=stop_after_first)
        checkpoint = track_levels.cached_levels(source, cache=self.root / "cache")
        self.assertFalse(checkpoint.complete)
        seen: list[int] = []
        self.service.levels_changed.connect(
            lambda _key: seen.append((self.service.levels_for(source) or track_levels.Levels()).seconds))
        # The app and the results page both hand over a finished run's recordings, in the same moment.
        self.service.queue([source])
        self.service.queue([source])
        self._wait(lambda: self._complete(source), 120)
        shown = [seconds for seconds in seen if seconds]
        self.assertGreaterEqual(min(shown), checkpoint.seconds, f"the lanes never lost the part measured: {shown[:5]}")
        self.assertEqual(self.service.levels_for(source).seconds, 900)

    def test_nothing_is_measured_while_a_run_is_going(self) -> None:
        source = make_tracks(self.root / "rec.mkv", [NOISE], 30)
        self.idle = False
        self.service.want(source)
        self._wait(lambda: self.service.state_for(source) == STATE_WAITING_FOR_RUN)
        QTest.qWait(300)
        self.assertEqual(CountingLevelsRunner.runs, [])
        self.idle = True
        self.availability.changed.emit()
        self._wait(lambda: self._complete(source))

    def test_a_run_starting_stops_the_build_which_keeps_its_part_and_carries_on_later(self) -> None:
        source = make_tracks(self.root / "long.mkv", [NOISE, TONE_10_TO_20], 1800)
        self.service.want(source)
        self._wait(lambda: (self.service.levels_for(source) or track_levels.Levels()).seconds > 0)
        self.idle = False
        self.service.stop_for_run()
        self._wait(lambda: self.service._build is None, 10)
        partial = track_levels.cached_levels(source, cache=self.root / "cache")
        self.assertIsNotNone(partial, "the part measured was saved")
        self.assertFalse(partial.complete)
        self.assertEqual(len(CountingLevelsRunner.runs), 1)
        QTest.qWait(300)
        self.assertEqual(len(CountingLevelsRunner.runs), 1, "no build starts while the run is going")
        self.idle = True
        self.availability.changed.emit()
        # The rest of a 30-minute recording: allow for a PC busy with other work (a parallel suite).
        self._wait(lambda: self._complete(source), 180)
        self.assertEqual(self.service.levels_for(source).seconds, 1800)

    def test_a_finished_runs_recordings_are_built_one_at_a_time_and_counted(self) -> None:
        sources = [make_tracks(self.root / f"rec{index}.mkv", [NOISE], 40) for index in range(2)]
        batch = Batch()
        self.service.queue(sources, listener=batch)
        self._wait(lambda: batch.told and batch.told[-1] == (2, 2, False))
        self.assertEqual(len(CountingLevelsRunner.runs), 2)
        self.assertIn((1, 2, True), batch.told)

    def test_the_player_goes_before_a_background_build(self) -> None:
        background = make_tracks(self.root / "background.mkv", [NOISE, TONE_10_TO_20], 1800)
        wanted = make_tracks(self.root / "wanted.mkv", [NOISE], 60)
        self.service.queue([background])
        self._wait(lambda: (self.service.levels_for(background) or track_levels.Levels()).seconds > 0)
        self.service.want(wanted)
        self._wait(lambda: self._complete(wanted))
        self.assertFalse(self._complete(background), "the background build gave way")
        self._wait(lambda: self._complete(background), 120)

    def test_closing_during_a_build_stops_it_at_once(self) -> None:
        source = make_tracks(self.root / "long.mkv", [NOISE, TONE_10_TO_20], 1800)
        self.service.want(source)
        self._wait(lambda: (self.service.levels_for(source) or track_levels.Levels()).seconds > 0)
        build, folder = self.service._build, self.service._build_folder
        self.assertTrue((folder / "work").is_dir(), "the helper works inside the build's own folder")
        started = time.monotonic()
        self.service.shutdown()
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertFalse(build.isRunning())
        self.assertFalse(folder.exists(), "nothing is left in the temporary folder")
        self.service.want(source)
        self.assertEqual(len(CountingLevelsRunner.runs), 1, "nothing starts after closing")

    def test_measuring_waits_quietly_while_the_tools_are_being_checked(self) -> None:
        # The start-up readiness check decides which Python and FFmpeg the helpers use (225); a build
        # started before its answer could use an unchecked one. Nothing is said: it is a few seconds.
        source = make_tracks(self.root / "rec.mkv", [NOISE], 30)
        checking = {"now": True}
        resources = helper_resources(_resources(), FFMPEG, FFPROBE)
        service = LevelsService(resources=lambda: resources, settings=lambda: {}, is_idle=lambda: True,
                                runner_factory=CountingLevelsRunner, availability_changed=self.availability.changed,
                                tools_ready=lambda: not checking["now"])
        try:
            service.want(source)
            QTest.qWait(1500)
            self.assertEqual(CountingLevelsRunner.runs, [], "no build while the tools are being checked")
            self.assertEqual(service.state_for(source), "")
            checking["now"] = False
            self.availability.changed.emit()
            self._wait(lambda: (service.levels_for(source) or track_levels.Levels()).complete)
        finally:
            service.shutdown()

    def test_without_a_runner_nothing_happens(self) -> None:
        source = make_tracks(self.root / "rec.mkv", [NOISE], 10)
        service = LevelsService(resources=_resources, settings=lambda: {}, is_idle=lambda: True, runner_factory=None)
        service.want(source)
        service.queue([source])
        QTest.qWait(200)
        self.assertIsNone(service.levels_for(source))
        self.assertEqual(CountingLevelsRunner.runs, [])


# What the player's lanes say while Next speech waits for an approved Whisper model (installer plan, Stage 3).
NOTE_BASE_EN = "No Next speech yet: it needs the Whisper model base.en. Approve its download in Settings > Dependencies."


def _helper_skip_line() -> str:
    """The note the real ``track-levels`` helper prints when its listening waits for a model that is not approved."""

    frames = mock.Mock()
    frames.read.return_value = {0: []}
    frames.ordinals = [0]
    frames.peaks = {}
    printed = io.StringIO()
    with mock.patch.object(track_levels.speech_facts, "record_measure", return_value=True), \
            mock.patch.object(track_levels.speech_facts, "jump_points", return_value=mock.Mock(needs_listen=True)), \
            mock.patch.object(track_levels.voice_track, "activity_from_frames", return_value={}), \
            mock.patch.object(track_levels.voice_track, "track_details", return_value={}), \
            mock.patch.object(track_levels.voice_track, "detect_from_activities",
                              side_effect=ModelNotApproved("base.en", MISSING)), \
            contextlib.redirect_stdout(printed):
        track_levels._store_facts(Path("recording.mkv"), frames, [{}], 60.0, ffmpeg="ffmpeg", facts={},
                                  stopped=lambda: False, work=Path("work"))
    lines = [line for line in printed.getvalue().splitlines() if "listening_skipped" in line]
    assert len(lines) == 1, printed.getvalue()
    return lines[0]


class _HelperStandIn:
    """Stands in for the ``track-levels`` helper process: hands the service the lines a measure prints, and its
    result. The waveform is whole; the listening for Next speech is skipped with the helper's own note until the
    test approves the model."""

    def __init__(self, test: "ListeningSkippedTests") -> None:
        self.test = test

    def run(self, command, on_log=None, *, cwd=None) -> RunnerResult:
        argv = list(command.argv)
        payload = json.loads(Path(argv[argv.index("--request-file") + 1]).read_text(encoding="utf-8"))["payload"]
        self.test.payloads.append(payload)
        lines = [track_levels.PROGRESS_PREFIX + json.dumps(
            {"first": 0, "seconds": 10, "duration": 10.0, "tracks": {"1": [-30.0] * 10, "2": [-30.0] * 10}})]
        if "facts" in payload:
            if self.test.approved:
                self.test.listened = True
            else:
                lines.append(self.test.skip_line)
        for line in lines:
            if on_log is not None:
                on_log("stdout", line)
        self.test.gate.wait(30)
        Path(argv[argv.index("--result-file") + 1]).write_text(json.dumps(
            {"ok": True, "data": {"results": [{"status": track_levels.STATUS_READY}]}, "error": ""}), encoding="utf-8")
        return RunnerResult(status="succeeded", exit_code=0)

    def cancel(self) -> None:
        self.test.gate.set()


class ListeningSkippedTests(unittest.TestCase):
    """A background job never asks for a Whisper model: it skips the listening with a note. The note reaches the
    player's lanes and the Workbench log, and the recording is listened to again once a model is approved."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.skip_line = _helper_skip_line()

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = mock.patch.dict(os.environ, {
            raw_bin_library.LIBRARY_ROOT_ENV: str(self.root / "library"),
            app_cache.CACHE_ROOT_ENV: str(self.root / "cache"),
        })
        self.environment.start()
        self.source = self.root / "rec.mkv"
        self.source.write_bytes(b"\0" * 64)
        self.payloads: list[dict] = []
        self.log: list[str] = []
        self.approved = False
        self.listened = False
        self.gate = threading.Event()
        self.gate.set()
        resources = types.SimpleNamespace(ffmpeg_exe="ffmpeg", ffprobe_exe="ffprobe", app_root=str(self.root),
                                          backend_source_root=str(self.root), python_exe="python")
        self.service = LevelsService(resources=lambda: resources, settings=lambda: {}, is_idle=lambda: True,
                                     runner_factory=lambda: _HelperStandIn(self), log=self.log.append,
                                     facts_lookup=self._facts, facts_request=lambda: {"track_roles": ""})

    def tearDown(self) -> None:
        self.gate.set()
        self.service.shutdown()
        self.app.processEvents()
        self.environment.stop()
        self.temp.cleanup()

    def _facts(self, _path: Path) -> speech_facts.JumpPoints:
        # What the library says about the recording's speech: it still has to be listened to until it was.
        if self.listened:
            return speech_facts.JumpPoints(track=2, stretches=((1.0, 3.0),), measured=True)
        return speech_facts.JumpPoints(measured=True, needs_listen=True)

    def _wait(self, condition, seconds: float = 20.0) -> None:
        deadline = time.monotonic() + seconds
        while not condition() and time.monotonic() < deadline:
            QTest.qWait(25)
        self.assertTrue(condition(), "waited too long")

    def _settled(self, runs: int) -> bool:
        service = self.service
        return (len(self.payloads) == runs and service._build is None and not service._looking
                and not service._queue and service._done.get(path_key(self.source)) == track_levels.STATUS_READY)

    def _stretches(self):
        facts = self.service.facts_for(self.source)
        return facts.stretches if facts is not None else ()

    def test_a_skipped_listening_says_why_on_the_lanes_and_in_the_log(self) -> None:
        self.service.want(self.source)
        self._wait(lambda: self._settled(1))
        self.assertIn("facts", self.payloads[0], "the build was asked to listen")
        self.assertEqual(self.service.state_for(self.source), NOTE_BASE_EN)
        said = [line for line in self.log if "base.en" in line]
        self.assertEqual(len(said), 1, self.log)
        self.assertIn("rec.mkv", said[0])
        self.assertIn("Approve its download in Settings > Dependencies", said[0])
        # Opened again before the model is approved: the note stays, and nothing is read again in a loop.
        self.service.want(self.source)
        self._wait(lambda: self._settled(1))
        QTest.qWait(400)
        self.assertEqual(len(self.payloads), 1)
        self.assertEqual(self.service.state_for(self.source), NOTE_BASE_EN)

    def test_a_skipped_recording_is_listened_to_again_once_the_model_is_approved(self) -> None:
        self.service.want(self.source)
        self._wait(lambda: self._settled(1))
        self.assertEqual(self._stretches(), ())
        # The operator approves base.en in Settings > Dependencies; the Workbench says so once it has downloaded.
        self.approved = True
        self.service.model_approved()
        self._wait(lambda: bool(self._stretches()))
        self._wait(lambda: self._settled(2))
        self.assertIn("facts", self.payloads[1], "read again for its speech facts")
        self.assertEqual(self._stretches(), ((1.0, 3.0),))
        self.assertEqual(self.service.state_for(self.source), "", "the note is gone")
        QTest.qWait(400)
        self.assertEqual(len(self.payloads), 2, "listened to once more, never in a loop")

    def test_a_model_approved_while_its_recording_is_measured_is_still_listened_to(self) -> None:
        # The note can arrive just before the approved download finishes, while the helper has not ended yet.
        self.gate.clear()
        self.service.want(self.source)
        self._wait(lambda: any("base.en" in line for line in self.log))
        self.approved = True
        self.service.model_approved()
        self.gate.set()
        self._wait(lambda: bool(self._stretches()))
        self._wait(lambda: self._settled(2))
        self.assertEqual(self.service.state_for(self.source), "")

    def test_approving_a_model_with_nothing_skipped_reads_nothing(self) -> None:
        self.approved = True
        self.service.want(self.source)
        self._wait(lambda: self._settled(1) and bool(self._stretches()))
        self.service.model_approved()
        QTest.qWait(400)
        self.assertEqual(len(self.payloads), 1)
        self.assertEqual(self.service.state_for(self.source), "")


if __name__ == "__main__":
    unittest.main()
