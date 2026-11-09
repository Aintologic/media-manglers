from __future__ import annotations

import ast
import faulthandler
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QEvent, QEventLoop, QMetaMethod, QPoint, QRect, Qt, QTimer, QUrl  # noqa: E402
from PySide6.QtMultimedia import (  # noqa: E402
    QAudioDevice,
    QAudioOutput,
    QMediaDevices,
    QMediaMetaData,
    QMediaPlayer,
)
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QPushButton, QWidget  # noqa: E402

from media_manglers_workbench import review_player  # noqa: E402
from media_manglers_workbench.play_targets import PlaySequence, PlayTarget  # noqa: E402
from media_manglers_workbench.recording_lists import EXCLUDED_KEY, PROCESSED_KEY, excluded_paths  # noqa: E402
from media_manglers_workbench.review_package import (  # noqa: E402
    RecordingTranscript,
    TranscriptLine,
    source_digest,
)
from media_manglers_workbench.review_player import (  # noqa: E402
    PackageLoadThread,
    ReviewPlayerWindow,
    SeekCoalescer,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PLAYER_SOURCE = REPO_ROOT / "src" / "media_manglers_workbench" / "review_player.py"

SESSION_ONE = "synthetic-session-one.mkv"
SESSION_TWO = "synthetic-session-two.mkv"
SESSION_THREE = "synthetic-session-three.mkv"

TEN_MINUTES_MS = 600_000
FOUR_HOURS_MS = 4 * 60 * 60 * 1000

# Words the contract keeps off the screen: they describe how the player is
# built, not what the operator sees.
BANNED_WORDS = ("envelope", "backend", "libvlc", "qmediaplayer", "coalesce")

FILLER_REASON = (
    "Left out: a stock phrase the transcriber tends to invent over silence or engine noise, "
    'like "thanks for watching".'
)
REJECTED_REASON = (
    "This whole stretch (0:00:40–0:01:10) was thrown out: the transcriber kept repeating itself "
    "even on a second try."
)


class _Signal:
    """Minimal signal: the window only ever connects, disconnects and is told."""

    def __init__(self) -> None:
        self.slots: list = []

    def connect(self, slot) -> None:
        self.slots.append(slot)

    def disconnect(self, slot=None) -> None:
        if slot is None:
            self.slots.clear()
        elif slot in self.slots:
            self.slots.remove(slot)

    def emit(self, *args) -> None:
        for slot in list(self.slots):
            slot(*args)


class FakeAudioOutput:
    def __init__(self, volume: float = 0.8) -> None:
        self._volume = volume
        self._muted = False
        self.mute_changes: list[bool] = []

    def volume(self) -> float:
        return self._volume

    def setVolume(self, volume: float) -> None:  # noqa: N802
        self._volume = volume

    def isMuted(self) -> bool:  # noqa: N802
        return self._muted

    def setMuted(self, muted: bool) -> None:  # noqa: N802
        self._muted = muted
        self.mute_changes.append(muted)


class FakePlayer:
    """Duck-typed stand-in for the real player, with the trap that was measured.

    A position set before the recording has been reported as loaded is
    silently ignored, exactly as the real player does it: no error, and the
    recording stays at 0:00:00.
    """

    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events if events is not None else []
        self._source = QUrl()
        self._position = 0
        self._duration = 0
        self._state = QMediaPlayer.PlaybackState.StoppedState
        self._status = QMediaPlayer.MediaStatus.NoMedia
        self._loaded_reported = False
        self._tracks: list[QMediaMetaData] = []
        self._active_track = -1
        self._error_string = ""
        self.calls: list[str] = []
        self.set_positions: list[int] = []
        self.ignored_positions: list[int] = []
        self.rates: list[float] = []
        self.play_calls = 0
        self.pause_calls = 0
        self.stop_calls = 0
        self.deleted = False
        self.audio_output = None
        self.video_output = None
        self.positionChanged = _Signal()
        self.durationChanged = _Signal()
        self.playbackStateChanged = _Signal()
        self.mediaStatusChanged = _Signal()
        self.errorOccurred = _Signal()
        self.tracksChanged = _Signal()

    # What the window calls -------------------------------------------------------

    def setSource(self, source_url: QUrl) -> None:  # noqa: N802
        self.calls.append("setSource")
        self._source = source_url
        self._status = (
            QMediaPlayer.MediaStatus.NoMedia if source_url.isEmpty() else QMediaPlayer.MediaStatus.LoadingMedia
        )

    def source(self) -> QUrl:
        return self._source

    def setAudioOutput(self, output) -> None:  # noqa: N802
        self.audio_output = output

    def setVideoOutput(self, output) -> None:  # noqa: N802
        self.video_output = output

    def play(self) -> None:
        self.calls.append("play")
        self.events.append("play")
        self.play_calls += 1
        self._state = QMediaPlayer.PlaybackState.PlayingState
        self.playbackStateChanged.emit(self._state)

    def pause(self) -> None:
        self.calls.append("pause")
        self.events.append("pause")
        self.pause_calls += 1
        self._state = QMediaPlayer.PlaybackState.PausedState
        self.playbackStateChanged.emit(self._state)

    def stop(self) -> None:
        # The window must never call this: the real player was measured to
        # freeze in it straight after a change of audio track. It is kept, and
        # counted, so every window test can prove it was not called.
        self.calls.append("stop")
        self.events.append("stop")
        self.stop_calls += 1
        self._state = QMediaPlayer.PlaybackState.StoppedState
        self.playbackStateChanged.emit(self._state)

    def setPosition(self, milliseconds: int) -> None:  # noqa: N802
        self.calls.append(f"setPosition:{int(milliseconds)}")
        self.set_positions.append(int(milliseconds))
        if not self._loaded_reported:
            self.ignored_positions.append(int(milliseconds))
            return
        self._position = int(milliseconds)

    def position(self) -> int:
        return self._position

    def duration(self) -> int:
        return self._duration

    def playbackState(self):  # noqa: N802
        return self._state

    def mediaStatus(self):  # noqa: N802
        return self._status

    def error(self):
        return QMediaPlayer.Error.NoError

    def errorString(self) -> str:  # noqa: N802
        return self._error_string

    def setPlaybackRate(self, rate: float) -> None:  # noqa: N802
        self.rates.append(rate)

    def audioTracks(self) -> list[QMediaMetaData]:  # noqa: N802
        return list(self._tracks)

    def activeAudioTrack(self) -> int:  # noqa: N802
        return self._active_track

    def setActiveAudioTrack(self, index: int) -> None:  # noqa: N802
        self.calls.append(f"setActiveAudioTrack:{index}")
        self._active_track = index

    def deleteLater(self) -> None:  # noqa: N802
        self.deleted = True

    # What a test makes the "recording" do -----------------------------------------

    def report_loaded(self, duration_ms: int = TEN_MINUTES_MS, titles: tuple[str, ...] = ()) -> None:
        self._duration = duration_ms
        self.durationChanged.emit(duration_ms)
        if titles:
            self._tracks = []
            for title in titles:
                metadata = QMediaMetaData()
                if title:
                    metadata.insert(QMediaMetaData.Key.Title, title)
                self._tracks.append(metadata)
            self._active_track = 0
            self.tracksChanged.emit()
        self._loaded_reported = True
        self._status = QMediaPlayer.MediaStatus.LoadedMedia
        self.mediaStatusChanged.emit(self._status)

    def move_to(self, milliseconds: int) -> None:
        """The clock reaches a moment, as it does during playback."""

        self._position = milliseconds
        self.positionChanged.emit(milliseconds)

    def arrive(self) -> None:
        """The picture for the last accepted seek turns up."""

        self.positionChanged.emit(self._position)

    def fail(self, details: str) -> None:
        self._error_string = details
        self._status = QMediaPlayer.MediaStatus.InvalidMedia
        self.errorOccurred.emit(QMediaPlayer.Error.FormatError, details)
        self.mediaStatusChanged.emit(self._status)


class PlayerFactory:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.players: list[FakePlayer] = []

    def __call__(self) -> FakePlayer:
        player = FakePlayer(self.events)
        self.players.append(player)
        return player


class RecordingSettings(dict):
    """Settings that note the moment the never-use list is written."""

    def __init__(self, events: list[str], *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.events = events

    def __setitem__(self, key, value) -> None:
        if key == EXCLUDED_KEY:
            self.events.append("write")
        super().__setitem__(key, value)


class FakePage:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.changes = 0

    def recording_lists_changed(self) -> None:
        self.events.append("page")
        self.changes += 1


class FakeHost:
    """The duck-typed host: only what the contract says the player may use."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.app_settings = RecordingSettings(events, {"video_autoplay": True})
        self.audio_output = FakeAudioOutput(0.8)
        self.audio_player = None
        self.bug_reports_page = None
        self.runner_thread = None
        self.current_package = None
        self.fail_save = False
        self.save_calls = 0

    def save_app_settings(self) -> None:
        self.events.append("save")
        self.save_calls += 1
        if self.fail_save:
            raise OSError("synthetic disk failure")


class FakeOpener:
    def __init__(self) -> None:
        self.opened: list[tuple[PlayTarget, str | None]] = []
        self.fallbacks: list[bool] = []

    def open(
        self,
        target: PlayTarget,
        *,
        player: str | None = None,
        sequence=None,
        allow_internal_fallback: bool = True,
    ) -> bool:
        self.opened.append((target, player))
        self.fallbacks.append(allow_internal_fallback)
        return True


def _line(start: float, end: float, text: str, kind: str = "kept", **extra) -> TranscriptLine:
    return TranscriptLine(start=start, end=end, text=text, kind=kind, **extra)


# Invented lines: two kept, one left out, a stretch thrown out whole, a
# rescued line and a spotter line, with gaps between them.
SYNTHETIC_LINES = (
    _line(
        10.0, 12.0, "synthetic kept line one",
        original_text="synthetic kept line won",
        numbers=(("no_speech_prob", 0.02), ("avg_logprob", -0.21), ("compression_ratio", 1.4)),
    ),
    _line(
        20.0, 22.0, "synthetic stock phrase", kind="left_out",
        reason_code="known_filler_phrase", reason_text=FILLER_REASON,
        numbers=(("no_speech_prob", 0.91),),
    ),
    _line(30.0, 33.0, "synthetic kept line two"),
    _line(
        40.0, 70.0, "synthetic repeated words", kind="rejected_span",
        reason_code="repetition_persisted_after_retry", reason_text=REJECTED_REASON,
    ),
    _line(80.0, 82.0, "synthetic rescued line", rescued=True),
    _line(90.0, 92.0, "synthetic spotter line", spotter=True),
)


def _transcript(root: Path, lines=SYNTHETIC_LINES, **overrides) -> RecordingTranscript:
    values = {
        "lines": tuple(lines),
        "mode": "Sparse",
        "filtering_ran": True,
        "audit_available": True,
        "rescued_known": True,
        "track_explanation": "",
        "transcribed_track": None,
        "contamination_suspected": False,
        "package_root": root / "synthetic-run" / "codex-evidence-package",
        "source_id": "synthetic-session-one-0123456789",
        "physical_source_id": "synthetic-session-one-0123456789",
    }
    values.update(overrides)
    return RecordingTranscript(**values)


def _write_package(folder: Path, recording: Path) -> Path:
    """The smallest package that lists ``recording`` and has one kept line."""

    root = folder / "codex-evidence-package"
    source_id = f"{recording.stem}-{source_digest(recording)}"
    (root / "transcript" / "sources").mkdir(parents=True)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sources": [
                    {
                        "source_id": source_id,
                        "physical_source_id": source_id,
                        "source_filename": recording.name,
                        "source_path": str(recording),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "transcript" / "sources" / f"{source_id}.transcript.json").write_text(
        json.dumps({"segments": [{"id": 0, "start": 1.0, "end": 3.0, "text": "synthetic package line"}]}),
        encoding="utf-8",
    )
    return root


class QtTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _wait_until(self, predicate, timeout_ms: int = 5000) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertTrue(predicate(), "Timed out while waiting for the player state change")

    def _flush_deleted(self) -> None:
        self.app.processEvents()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()


class SeekCoalescerTests(QtTestCase):
    def setUp(self) -> None:
        self.sent: list[int] = []
        self.coalescer = SeekCoalescer(self.sent.append)

    def tearDown(self) -> None:
        self.coalescer.reset()
        self.coalescer.deleteLater()
        self._flush_deleted()

    def test_a_flood_of_requests_sends_one_then_only_the_newest(self) -> None:
        for target in range(1_000, 61_000, 1_000):
            self.coalescer.request(target)
        # The drag passed through 60 places; the player heard about one.
        self.assertEqual(self.sent, [1_000])

        self.coalescer.frame_arrived(1_000)
        self.assertEqual(self.sent, [1_000, 60_000])

        self.coalescer.frame_arrived(60_000)
        self.assertEqual(self.sent, [1_000, 60_000])
        self.assertIsNone(self.coalescer.requested_ms())

    def test_a_frame_far_from_the_target_does_not_count(self) -> None:
        self.coalescer.request(50_000)
        self.coalescer.request(90_000)
        # Frames from before the jump are still arriving.
        for stale in (12_000, 12_040, 49_899, 50_101):
            self.coalescer.frame_arrived(stale)
        self.assertEqual(self.sent, [50_000])

        self.coalescer.frame_arrived(50_100)
        self.assertEqual(self.sent, [50_000, 90_000])

    def test_the_tolerance_can_be_set(self) -> None:
        sent: list[int] = []
        strict = SeekCoalescer(sent.append, tolerance_ms=10)
        strict.request(5_000)
        strict.request(6_000)
        strict.frame_arrived(5_011)
        self.assertEqual(sent, [5_000])
        strict.frame_arrived(5_010)
        self.assertEqual(sent, [5_000, 6_000])
        strict.reset()
        strict.deleteLater()

    def test_the_timeout_lets_the_next_request_through(self) -> None:
        self.coalescer.request(10_000)
        self.coalescer.request(20_000)
        timer = self.coalescer._timer
        self.assertTrue(timer.isActive())
        self.assertTrue(timer.isSingleShot())
        self.assertEqual(timer.interval(), 700)

        # No frame ever arrives (the end of a recording, a sound-only file).
        # The timer is fired by hand so the test does not wait for it.
        timer.timeout.emit()
        self.assertEqual(self.sent, [10_000, 20_000])
        self.assertTrue(timer.isActive())

        timer.timeout.emit()
        self.assertEqual(self.sent, [10_000, 20_000])
        self.assertIsNone(self.coalescer.requested_ms())
        self.assertFalse(timer.isActive())

    def test_the_timeout_is_a_setting_and_really_fires(self) -> None:
        sent: list[int] = []
        quick = SeekCoalescer(sent.append, timeout_ms=20)
        quick.request(1_000)
        quick.request(2_000)
        self._wait_until(lambda: sent == [1_000, 2_000], timeout_ms=2000)
        quick.reset()
        quick.deleteLater()

    def test_requested_ms_is_the_last_place_asked_for(self) -> None:
        self.assertIsNone(self.coalescer.requested_ms())
        self.coalescer.request(7_000)
        self.assertEqual(self.coalescer.requested_ms(), 7_000)
        self.coalescer.request(8_000)
        self.coalescer.request(9_000)
        self.assertEqual(self.coalescer.requested_ms(), 9_000)
        self.coalescer.frame_arrived(7_000)
        # 9000 is with the player now and is still what the operator asked for.
        self.assertEqual(self.coalescer.requested_ms(), 9_000)
        self.coalescer.frame_arrived(9_000)
        self.assertIsNone(self.coalescer.requested_ms())

    def test_asking_again_for_the_place_being_fetched_sends_nothing_more(self) -> None:
        # A plain click on the timeline asks for the same second twice.
        self.coalescer.request(30_000)
        self.coalescer.request(30_000)
        self.coalescer.frame_arrived(30_000)
        self.assertEqual(self.sent, [30_000])

        self.coalescer.request(40_000)
        self.coalescer.request(45_000)
        self.coalescer.request(40_000)
        self.coalescer.frame_arrived(40_000)
        self.assertEqual(self.sent, [30_000, 40_000])

    def test_a_report_from_inside_set_position_finds_its_request(self) -> None:
        sent: list[int] = []

        def set_position(milliseconds: int) -> None:
            sent.append(milliseconds)
            eager.frame_arrived(milliseconds)

        eager = SeekCoalescer(set_position)
        eager.request(1_000)
        eager.request(2_000)
        self.assertEqual(sent, [1_000, 2_000])
        self.assertIsNone(eager.requested_ms())
        self.assertFalse(eager._timer.isActive())
        eager.deleteLater()

    def test_reset_forgets_everything(self) -> None:
        self.coalescer.request(1_000)
        self.coalescer.request(2_000)
        self.coalescer.reset()
        self.assertIsNone(self.coalescer.requested_ms())
        self.assertFalse(self.coalescer._timer.isActive())
        self.coalescer.frame_arrived(1_000)
        self.assertEqual(self.sent, [1_000])

    def test_nonsense_is_survived(self) -> None:
        self.coalescer.request(-500)
        self.assertEqual(self.sent, [0])
        for nonsense in (None, "soon", float("nan"), float("inf")):
            self.coalescer.frame_arrived(nonsense)  # type: ignore[arg-type]
        self.assertEqual(self.coalescer.requested_ms(), 0)


class PackageLoadThreadTests(QtTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.recording = self.root / "captures" / SESSION_ONE
        self.loaded: list[tuple[int, object]] = []
        self.failed: list[tuple[int, str]] = []
        self.threads: list[PackageLoadThread] = []

    def tearDown(self) -> None:
        for thread in self.threads:
            thread.cancel()
            self.assertTrue(thread.wait(5000))
            thread.deleteLater()
        self._flush_deleted()
        self.temp.cleanup()

    def _thread(self, generation: int, package_root: Path | None, hints: list[str]) -> PackageLoadThread:
        thread = PackageLoadThread(generation, self.recording, package_root, hints, None)
        thread.loaded.connect(lambda number, transcript: self.loaded.append((number, transcript)))
        thread.failed.connect(lambda number, details: self.failed.append((number, details)))
        self.threads.append(thread)
        return thread

    def test_a_package_that_lists_the_recording_is_loaded(self) -> None:
        _write_package(self.root / "synthetic-run", self.recording)
        # run() is called directly: same code, no second thread to wait for.
        self._thread(4, None, [str(self.root / "elsewhere"), str(self.root / "synthetic-run")]).run()

        self.assertEqual(self.failed, [])
        self.assertEqual(len(self.loaded), 1)
        generation, transcript = self.loaded[0]
        self.assertEqual(generation, 4)
        self.assertIsInstance(transcript, RecordingTranscript)
        self.assertEqual([line.text for line in transcript.lines], ["synthetic package line"])

    def test_the_named_package_is_tried_before_the_hints(self) -> None:
        asked: list[str] = []

        def fake_load(package_root, recording, *, duration_seconds=None):
            asked.append(f"load:{Path(package_root).name}")
            return None

        def fake_find(recording, hints, *, duration_seconds=None, cancelled=lambda: False):
            asked.append("find:" + ",".join(Path(hint).name for hint in hints))
            return None

        named = self.root / "named-run"
        with (
            patch.object(review_player, "load_transcript", fake_load),
            patch.object(review_player, "find_package_for_recording", fake_find),
        ):
            self._thread(1, named, [str(named), str(self.root / "older-run")]).run()

        # The named package is not asked a second time through the hints.
        self.assertEqual(asked, ["load:named-run", "find:older-run"])
        self.assertEqual(self.loaded, [(1, None)])

    def test_nothing_found_is_still_exactly_one_signal(self) -> None:
        self._thread(2, None, [str(self.root / "no-such-run")]).run()
        self.assertEqual(self.loaded, [(2, None)])
        self.assertEqual(self.failed, [])

    def test_a_loader_that_raises_is_reported_once_and_never_escapes(self) -> None:
        def broken(*_args, **_kwargs):
            raise TypeError("synthetic loader failure")

        with patch.object(review_player, "load_transcript", broken):
            self._thread(9, self.root / "synthetic-run", []).run()

        self.assertEqual(self.loaded, [])
        self.assertEqual(self.failed, [(9, "TypeError: synthetic loader failure")])

    def test_a_finder_that_raises_is_reported_once(self) -> None:
        def broken(*_args, **_kwargs):
            raise RuntimeError("synthetic finder failure")

        with patch.object(review_player, "find_package_for_recording", broken):
            self._thread(5, None, [str(self.root)]).run()

        self.assertEqual(self.loaded, [])
        self.assertEqual(self.failed, [(5, "RuntimeError: synthetic finder failure")])

    def test_cancel_stops_a_running_search_with_one_signal(self) -> None:
        entered = threading.Event()

        def slow_find(recording, hints, *, duration_seconds=None, cancelled=lambda: False):
            entered.set()
            deadline = time.monotonic() + 10
            while not cancelled() and time.monotonic() < deadline:
                time.sleep(0.005)
            return None

        with patch.object(review_player, "find_package_for_recording", slow_find):
            thread = self._thread(3, None, [str(self.root)])
            thread.start()
            self.assertTrue(entered.wait(5))
            thread.cancel()
            self.assertTrue(thread.wait(5000))
            self._wait_until(lambda: bool(self.loaded or self.failed))

        self.assertEqual(self.loaded, [(3, None)])
        self.assertEqual(self.failed, [])
        self.assertFalse(thread.isRunning())

    def test_cancel_before_the_thread_has_started_is_remembered(self) -> None:
        asked: list[str] = []

        def fake_find(*_args, **_kwargs):
            asked.append("find")
            return None

        thread = self._thread(6, None, [str(self.root)])
        thread.cancel()
        with patch.object(review_player, "find_package_for_recording", fake_find):
            thread.run()
        self.assertEqual(asked, [])
        self.assertEqual(self.loaded, [(6, None)])

    def test_hints_are_copied_as_plain_text(self) -> None:
        hints = [self.root / "synthetic-run"]
        thread = self._thread(1, None, hints)  # type: ignore[arg-type]
        hints.clear()
        self.assertEqual(thread.hints, [str(self.root / "synthetic-run")])


class PlayerSourceGuardTests(unittest.TestCase):
    """Rules that a future edit must not be able to break quietly."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = ast.parse(PLAYER_SOURCE.read_text(encoding="utf-8"))
        cls.functions = {
            node.name: node for node in ast.walk(cls.tree) if isinstance(node, ast.FunctionDef)
        }
        # Every signal the real player has, asked of Qt itself. A list typed
        # in by hand went stale once already: it missed three of them.
        meta = QMediaPlayer.staticMetaObject
        cls.PLAYER_SIGNAL_NAMES = frozenset(
            bytes(meta.method(index).name()).decode("ascii")
            for index in range(meta.methodOffset(), meta.methodCount())
            if meta.method(index).methodType() == QMetaMethod.MethodType.Signal
        )

    def test_the_signal_names_really_came_from_qt(self) -> None:
        # The guards below would pass on an empty list.
        self.assertGreaterEqual(len(self.PLAYER_SIGNAL_NAMES), 19)
        self.assertLessEqual(set(review_player._PLAYER_SIGNALS), self.PLAYER_SIGNAL_NAMES)
        self.assertIn("sourceChanged", self.PLAYER_SIGNAL_NAMES)
        # A slot or a plain method must not be taken for a signal.
        self.assertNotIn("play", self.PLAYER_SIGNAL_NAMES)
        self.assertNotIn("setSource", self.PLAYER_SIGNAL_NAMES)

    def _player_connects(self, tree: ast.AST | None = None) -> list[tuple[str, ast.Call]]:
        found = []
        for node in ast.walk(self.tree if tree is None else tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "connect"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr in self.PLAYER_SIGNAL_NAMES
            ):
                found.append((node.func.value.attr, node))
        return found

    def _sideways_connects(self, tree: ast.AST) -> list[str]:
        """Ways of connecting a player signal that the plain check cannot see."""

        direct = {id(call.func.value) for _signal, call in self._player_connects(tree)}
        # The one place a signal may be named as text: the list used to
        # disconnect them all.
        listed: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "_PLAYER_SIGNALS" for target in node.targets
            ):
                listed = {id(constant) for constant in ast.walk(node.value)}
        offenders: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in self.PLAYER_SIGNAL_NAMES:
                # "signal = player.seekableChanged" and then signal.connect(...)
                if id(node) not in direct:
                    offenders.append(f"{node.lineno} {node.attr} is used without .connect(partial(...))")
            elif isinstance(node, ast.Constant) and node.value in self.PLAYER_SIGNAL_NAMES:
                # getattr(player, "sourceChanged").connect(...)
                if id(node) not in listed:
                    offenders.append(f"{node.lineno} {node.value!r} is named as text")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "connect"
            ):
                receiver = node.func.value
                if isinstance(receiver, ast.Call) and ast.unparse(receiver.func) == "getattr":
                    # getattr(player, name).connect(...)
                    offenders.append(f"{node.lineno} connect on a getattr() result")
                elif ast.unparse(receiver).split(".")[-1] == "QObject":
                    # QObject.connect(player, SIGNAL("..."), slot)
                    offenders.append(f"{node.lineno} QObject.connect")
        return offenders

    @staticmethod
    def _is_generation_partial(call: ast.Call) -> bool:
        if len(call.args) != 1 or not isinstance(call.args[0], ast.Call):
            return False
        wrapper = call.args[0]
        named_partial = (
            isinstance(wrapper.func, ast.Attribute)
            and wrapper.func.attr == "partial"
            and isinstance(wrapper.func.value, ast.Name)
            and wrapper.func.value.id == "functools"
        ) or (isinstance(wrapper.func, ast.Name) and wrapper.func.id == "partial")
        return (
            named_partial
            and len(wrapper.args) >= 2
            and isinstance(wrapper.args[1], ast.Name)
            and wrapper.args[1].id == "generation"
        )

    def test_every_player_signal_is_connected_with_the_generation(self) -> None:
        connects = self._player_connects()
        offenders = [
            f"{PLAYER_SOURCE.name}:{call.lineno} {signal}"
            for signal, call in connects
            if not self._is_generation_partial(call)
        ]
        self.assertEqual(
            offenders,
            [],
            "A player signal must be connected as "
            "signal.connect(functools.partial(self._slot, generation)), so a report from a "
            "player that has been replaced cannot move the screen.",
        )
        # The guard must not pass because it found nothing to check.
        self.assertGreaterEqual(len(connects), 6)

    def test_no_player_signal_is_connected_by_a_side_door(self) -> None:
        self.assertEqual(self._sideways_connects(self.tree), [])

    def test_the_player_is_wired_up_with_nothing_but_numbered_connections(self) -> None:
        connects = [
            node
            for node in ast.walk(self.functions["_create_player"])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "connect"
        ]
        self.assertEqual(len(connects), len(review_player._PLAYER_SIGNALS))
        for call in connects:
            with self.subTest(line=call.lineno):
                self.assertTrue(self._is_generation_partial(call), ast.unparse(call))

    def test_the_guards_catch_every_spelling_that_was_tried_on_them(self) -> None:
        # Each of these was added to a copy of the player in review and only
        # some were caught. Here each must be, so the guards above can fail.
        numbered = "player.positionChanged.connect(functools.partial(self._on_position_changed, generation))"
        self.assertEqual(self._sideways_connects(ast.parse(numbered)), [])
        (accepted,) = self._player_connects(ast.parse(numbered))
        self.assertTrue(self._is_generation_partial(accepted[1]))

        unnumbered = (
            "player.metaDataChanged.connect(self._on_metadata)",
            "player.metaDataChanged.connect(lambda: self._on_metadata())",
            "player.metaDataChanged.connect(functools.partial(self._on_metadata, self._player_generation))",
        )
        for source in unnumbered:
            with self.subTest(source=source):
                connects = self._player_connects(ast.parse(source))
                self.assertEqual(len(connects), 1)
                self.assertFalse(self._is_generation_partial(connects[0][1]))

        side_doors = (
            "signal = player.seekableChanged\nsignal.connect(self._on_seekable)",
            'getattr(player, "sourceChanged").connect(self._on_source)',
            "for name in names:\n    getattr(player, name).connect(self._on_anything)",
            'QObject.connect(player, SIGNAL("positionChanged(qint64)"), self._on_position)',
            'QtCore.QObject.connect(player, SIGNAL("positionChanged(qint64)"), self._on_position)',
        )
        for source in side_doors:
            with self.subTest(source=source):
                self.assertNotEqual(self._sideways_connects(ast.parse(source)), [])

    def test_what_is_connected_is_what_is_disconnected(self) -> None:
        connected = sorted(signal for signal, _call in self._player_connects())
        self.assertEqual(connected, sorted(review_player._PLAYER_SIGNALS))

    def test_every_generation_slot_starts_by_checking_it(self) -> None:
        slots = {
            call.args[0].args[0].attr: "self._player_generation"
            for _signal, call in self._player_connects()
            if self._is_generation_partial(call) and isinstance(call.args[0].args[0], ast.Attribute)
        }
        # The loader thread hands its number over inside the signal, and that
        # number counts transcript lookups, not players: one recording can be
        # looked up twice, and the first answer must not replace the second.
        slots |= {
            "_on_package_loaded": "self._package_generation",
            "_on_package_failed": "self._package_generation",
        }
        self.assertGreaterEqual(len(slots), 8)
        for name, counter in sorted(slots.items()):
            with self.subTest(slot=name):
                function = self.functions[name]
                self.assertEqual(function.args.args[1].arg, "generation")
                body = [
                    statement
                    for statement in function.body
                    if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant))
                ]
                first = body[0]
                self.assertIsInstance(first, ast.If)
                self.assertEqual(ast.unparse(first.test), f"generation != {counter}")
                self.assertIsInstance(first.body[0], ast.Return)

    @staticmethod
    def _stop_calls(tree: ast.AST) -> list[str]:
        """Every ``.stop()`` in the source that is not plainly a timer's."""

        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "stop":
                receiver = ast.unparse(node.func.value)
                if not receiver.lower().endswith("timer"):
                    offenders.append(f"{node.lineno} {receiver}.stop()")
            # getattr(player, "stop")() would be the same call in disguise.
            if isinstance(node, ast.Constant) and node.value == "stop":
                offenders.append(f"{node.lineno} 'stop' named as text")
        return offenders

    def test_a_player_is_never_told_to_stop(self) -> None:
        # Measured with the real player on a multi-hour six-track recording:
        # stop() straight after a change of audio track never returns and
        # freezes the whole app. A player is let go of with pause() and an
        # empty source; only timers are ever stopped.
        self.assertEqual(self._stop_calls(self.tree), [])
        self.assertFalse(hasattr(review_player, "TRACK_SWITCH_SETTLE_SECONDS"))

        # The guard itself can fail, and leaves the timers alone.
        self.assertEqual(self._stop_calls(ast.parse("self._step_timer.stop()\nself._timer.stop()")), [])
        for source in ("player.stop()", "self._player.stop()", 'getattr(player, "stop")()'):
            with self.subTest(source=source):
                self.assertNotEqual(self._stop_calls(ast.parse(source)), [])

    def test_a_transcript_is_only_ever_read_through_the_small_reader(self) -> None:
        # The full evidence-package loader reads far more than a transcript
        # and was never meant to run for every recording that is opened.
        self.assertNotIn("load_evidence_package", PLAYER_SOURCE.read_text(encoding="utf-8"))

    def test_sender_is_never_used(self) -> None:
        offenders = [
            node.lineno
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Attribute) and node.attr == "sender"
        ]
        self.assertEqual(offenders, [])

    def test_the_hosts_shared_sound_output_is_never_touched(self) -> None:
        offenders = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Attribute) and node.attr == "audio_output":
                if not (isinstance(node.value, ast.Name) and node.value.id == "self"):
                    offenders.append(node.lineno)
            if isinstance(node, ast.Constant) and node.value == "audio_output":
                offenders.append(node.lineno)
        self.assertEqual(offenders, [])

    def test_imports_are_at_the_top_and_never_reach_the_opener(self) -> None:
        top_level: set[str] = set()
        for node in self.tree.body:
            if isinstance(node, ast.ImportFrom):
                top_level.add(("." * node.level) + (node.module or ""))
            elif isinstance(node, ast.Import):
                top_level.update(alias.name for alias in node.names)
        # Top-level, so the packaged build bundles both and its smoke run
        # exercises them.
        self.assertIn("PySide6.QtMultimedia", top_level)
        self.assertIn("PySide6.QtMultimediaWidgets", top_level)
        # video_open imports this module; the other way round is a cycle.
        self.assertNotIn(".video_open", top_level)
        self.assertNotIn("video_open", PLAYER_SOURCE.read_text(encoding="utf-8"))

        nested = [
            node.lineno
            for node in ast.walk(self.tree)
            if isinstance(node, (ast.Import, ast.ImportFrom)) and node not in self.tree.body
        ]
        self.assertEqual(nested, [], "An import inside a function escapes the packaged build.")


class WindowTestCase(QtTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        # Resolved, because the never-use list stores resolved paths and a
        # temp folder can be handed out under a short or linked spelling.
        self.root = Path(self.temp.name).resolve()
        self.events: list[str] = []
        self.host = FakeHost(self.events)
        self.factory = PlayerFactory(self.events)
        self.opener = FakeOpener()
        self.windows: list[ReviewPlayerWindow] = []
        self.diagnostics: list[str] = []

    def tearDown(self) -> None:
        # The window has no Qt parent, so nothing else will close it. Closed
        # FIRST, and its loader threads waited for, before the temp folder goes.
        for window in self.windows:
            window.close()
            self.assertTrue(window.shutdown(5000))
            window.deleteLater()
        self._flush_deleted()
        self.temp.cleanup()
        # Whatever the test did - opened, replaced, released, closed - no
        # player was ever told to stop (the real one can freeze in it).
        self.assertEqual([player.stop_calls for player in self.factory.players if player.stop_calls], [])

    def _window(self, **overrides) -> ReviewPlayerWindow:
        arguments = {
            "video_surface_factory": QWidget,
            "player_factory": self.factory,
            "audio_output_factory": FakeAudioOutput,
        }
        arguments.update(overrides)
        window = ReviewPlayerWindow(self.host, self.opener, **arguments)
        window.diagnostic.connect(self.diagnostics.append)
        self.windows.append(window)
        return window

    def _target(self, name: str = SESSION_ONE, **values) -> PlayTarget:
        return PlayTarget(path=self.root / name, **values)

    def _sequence(self, *names: str) -> PlaySequence:
        return PlaySequence(tuple(self._target(name) for name in names), label="Find my bug reports list")

    def _open(self, window: ReviewPlayerWindow, name: str = SESSION_ONE, *, loaded: bool = True, **values):
        autoplay = values.pop("autoplay", True)
        sequence = values.pop("sequence", None)
        note = values.pop("note", "")
        window.open_target(self._target(name, **values), sequence=sequence, autoplay=autoplay, note=note)
        player = self.factory.players[-1]
        if loaded:
            player.report_loaded()
        return player

    def _show_lines(self, window: ReviewPlayerWindow, **overrides) -> None:
        window._on_package_loaded(window._package_generation, _transcript(self.root, **overrides))

    @staticmethod
    def _screen_text(window: ReviewPlayerWindow) -> str:
        parts = [window.windowTitle()]
        for widget in window.findChildren(QWidget):
            parts.append(widget.toolTip())
            text = getattr(widget, "text", None)
            if callable(text):
                parts.append(str(text()))
        return "\n".join(parts)


class WindowBasicsTests(WindowTestCase):
    def test_the_window_stands_alone_and_does_not_keep_the_app_open(self) -> None:
        window = self._window()
        self.assertIsNone(window.parent())
        self.assertTrue(window.isWindow())
        self.assertFalse(window.testAttribute(Qt.WidgetAttribute.WA_QuitOnClose))
        self.assertEqual(window.windowTitle(), "Built-in player")

        self._open(window)
        self.assertEqual(window.windowTitle(), f"{SESSION_ONE} — Built-in player")

    def test_its_sound_output_is_its_own(self) -> None:
        window = self._window()
        player = self._open(window)

        self.assertIsNot(window.audio_output, self.host.audio_output)
        self.assertIs(player.audio_output, window.audio_output)

        window.volume_slider.setValue(30)
        self.assertAlmostEqual(window.audio_output.volume(), 0.3)
        # The narration preview players share the host's output; it is 0.8
        # and must stay 0.8 whatever happens here.
        self.assertEqual(self.host.audio_output.volume(), 0.8)
        self.assertEqual(self.host.audio_output.mute_changes, [])

    def test_the_default_sound_output_is_a_real_one_owned_by_the_window(self) -> None:
        window = self._window(audio_output_factory=None)
        self.assertIsInstance(window.audio_output, QAudioOutput)
        self.assertIs(window.audio_output.parent(), window)
        self.assertAlmostEqual(window.audio_output.volume(), 0.8, places=5)
        default_device = QMediaDevices.defaultAudioOutput()
        if default_device.isNull():
            self.skipTest("Qt reported no default audio output device.")
        self.assertEqual(bytes(window.audio_output.device().id()), bytes(default_device.id()))

    def test_the_stored_volume_is_used_and_nonsense_is_not(self) -> None:
        self.host.app_settings["review_player_volume"] = 0.35
        window = self._window()
        self.assertAlmostEqual(window.audio_output.volume(), 0.35)
        self.assertEqual(window.volume_slider.value(), 35)

        for nonsense in ("loud", None, True, 7, float("nan")):
            with self.subTest(stored=nonsense):
                self.host.app_settings["review_player_volume"] = nonsense
                other = self._window()
                self.assertTrue(0.0 <= other.audio_output.volume() <= 1.0)

    def test_the_layout_has_everything_the_operator_was_promised(self) -> None:
        window = self._window()
        self.assertEqual(window.video_surface.minimumHeight(), review_player.VIDEO_MINIMUM_HEIGHT)
        # The whole window has to fit a 1366x768 laptop (about 728 px usable).
        self.assertLessEqual(review_player.VIDEO_MINIMUM_HEIGHT, 140)
        self.assertEqual(window.step_back_button.text(), "Step back")
        self.assertEqual(window.play_button.text(), "Play")
        self.assertEqual(window.step_forward_button.text(), "Step forward")
        self.assertEqual(window.back_five_button.text(), "-5 s")
        self.assertEqual(window.forward_five_button.text(), "+5 s")
        self.assertEqual(window.time_label.text(), "0:00:00 / 0:00:00")
        self.assertEqual(
            [window.speed_combo.itemText(index) for index in range(window.speed_combo.count())],
            ["1x", "2x", "4x"],
        )
        self.assertEqual(
            [window.line_filter_combo.itemText(index) for index in range(window.line_filter_combo.count())],
            ["All lines", "Kept only", "Left out only"],
        )
        self.assertEqual(window.previous_line_button.text(), "Previous line")
        self.assertEqual(window.next_line_button.text(), "Next line")
        self.assertEqual(window.show_numbers_checkbox.text(), "Show the numbers")
        self.assertEqual(window.hear_track_button.text(), "Hear this track")
        self.assertEqual(window.never_use_button.text(), "Never use this recording")
        self.assertEqual(window.skip_button.text(), "Skip this recording")
        self.assertEqual(window.undo_button.text(), "Undo")
        self.assertEqual(
            window.legend_label.text(),
            "Space play or pause  ·  Up/Down previous or next line  ·  Left/Right 5 seconds  ·  W waveforms",
        )
        labels = {label.text() for label in window.findChildren(QLabel)}
        self.assertIn("Hear:", labels)
        self.assertIn("This recording:", labels)
        for combo in (window.speed_combo, window.track_combo, window.line_filter_combo):
            self.assertEqual(type(combo).__name__, "WheelSafeComboBox")

    def test_keys_live_on_actions_and_every_tooltip_ends_with_its_key(self) -> None:
        window = self._window()
        expected = (
            (window.play_action, window.play_button, "Space", "Space", False),
            (window.step_back_action, window.step_back_button, ",", ", (comma)", False),
            (window.step_forward_action, window.step_forward_button, ".", ". (period)", False),
            (window.back_five_action, window.back_five_button, "Left", "Left", True),
            (window.forward_five_action, window.forward_five_button, "Right", "Right", True),
            (window.previous_line_action, window.previous_line_button, "Up", "Up", False),
            (window.next_line_action, window.next_line_button, "Down", "Down", False),
            # 220: jump between the raw bin's speech or active stretches.
            (window.previous_stretch_action, window.previous_stretch_button, "PgUp", "Page Up", False),
            (window.next_stretch_action, window.next_stretch_button, "PgDown", "Page Down", False),
            # 125 Part 2 (Wave 8): the waveforms, the sounds on the track you hear and the moments.
            (window.waveforms_action, window.waveforms_button, "W", "W", False),
            (window.previous_sound_action, window.previous_sound_button, "Ctrl+Left", "Ctrl+Left", False),
            (window.next_sound_action, window.next_sound_button, "Ctrl+Right", "Ctrl+Right", False),
            (window.previous_moment_action, window.previous_moment_button, "[", "[", False),
            (window.next_moment_action, window.next_moment_button, "]", "]", False),
        )
        for action, button, keys, key_name, repeats in expected:
            with self.subTest(button=button.text()):
                self.assertEqual(action.shortcut().toString(), keys)
                # Holding a key only makes sense for the 5 second jumps.
                self.assertEqual(action.autoRepeat(), repeats)
                self.assertTrue(button.toolTip().endswith(f"Key: {key_name}"), button.toolTip())
        with_keys = [action for action in window.actions() if not action.shortcut().isEmpty()]
        self.assertEqual(len(with_keys), len(expected))
        self.assertTrue(window.step_forward_button.toolTip().startswith("Moves forward a frame or two."))

    def test_nothing_on_screen_uses_the_builders_words(self) -> None:
        window = self._window()
        player = self._open(window, sequence=self._sequence(SESSION_ONE, SESSION_TWO))
        self._show_lines(window, mode="Continuous", filtering_ran=False)
        window.show_numbers_checkbox.setChecked(True)
        # Read while a line's scores are showing, a rescued line's badge is
        # up, and again once the banner and the can't-play card are.
        player.move_to(10_500)
        text = self._screen_text(window)
        player.move_to(81_000)
        text += self._screen_text(window)
        window.never_use_current()
        self.factory.players[-1].fail("synthetic decode failure")
        text = (text + self._screen_text(window)).lower()

        for word in BANNED_WORDS:
            with self.subTest(word=word):
                self.assertNotIn(word, text)
        # A name with an underscore in it is a programmer's name for something
        # (the package calls the scores no_speech_prob, avg_logprob, ...).
        self.assertNotIn("_", text)
        self.assertIn("how sure it was of the words", text)

    def _busiest_window(self) -> ReviewPlayerWindow:
        # A run going (Skip shown), a banner with Undo, a transcript with its
        # track button and the numbers showing.
        window = self._window()
        self.host.runner_thread = object()
        self.host.skip_run_sources = lambda sources: list(sources)
        player = self._open(window, sequence=self._sequence(SESSION_ONE, SESSION_TWO))
        window.never_use_current()
        self.factory.players[-1].report_loaded(titles=("Track1", "Microphone"))
        self._show_lines(window, track_explanation="Track 2 carries your narration.", transcribed_track=2)
        window.show_numbers_checkbox.setChecked(True)
        self.assertFalse(player is self.factory.players[-1])
        return window

    def test_every_button_fits_in_a_window_a_small_screen_can_show(self) -> None:
        window = self._busiest_window()
        for state in ("never use", "allow again"):
            if state == "allow again":
                window.never_use_current()
            self.app.processEvents()
            # The upper bound is what lets this test fail. A caption that
            # grows only makes the window ASK for more room, and a window that
            # is given all it asks for always fits its buttons.
            self.assertLessEqual(window.minimumSizeHint().width(), 1000)
            self.assertLessEqual(window.minimumSizeHint().height(), 800)
            window.resize(1000, 700)
            self.app.processEvents()
            self.assertEqual(window.width(), 1000)
            checked = 0
            for control in window.findChildren(QWidget):
                if not isinstance(control, (QPushButton, QCheckBox)):
                    continue
                if not control.isVisible() or not control.text().strip():
                    continue
                checked += 1
                with self.subTest(state=state, control=control.text()):
                    self.assertGreaterEqual(control.width() + 2, control.minimumSizeHint().width())
            self.assertGreaterEqual(checked, 11)
        self.assertEqual(window.never_use_button.text(), "Allow again")

    def test_the_size_check_notices_a_caption_that_is_far_too_long(self) -> None:
        # The check above passed for a 300-character caption before it had an
        # upper bound. This is that caption.
        window = self._busiest_window()
        self.assertLessEqual(window.minimumSizeHint().width(), 1000)
        window.never_use_button.setText("synthetic caption " * 17)
        # 237: measured at once. The player puts its own caption back on its next refresh, and the rows
        # that wrap measure what they hold now rather than what a layout remembered.
        self.assertGreater(window.minimumSizeHint().width(), 1000)

    def test_a_first_time_window_is_no_bigger_than_the_screen_can_show(self) -> None:
        window = self._window()
        for screen_size, expected in (
            ((2560, 1440), (1100, 860)),
            # 1080p at 125 % scaling, and an old 1366 x 768 laptop: the
            # default height would put the bottom rows off the screen.
            ((1536, 824), (1100, 776)),
            ((1366, 728), (1100, 680)),
            ((1024, 728), (1008, 680)),
        ):
            with self.subTest(screen=screen_size):
                screen = SimpleNamespace(availableGeometry=lambda size=screen_size: QRect(0, 0, *size))
                with patch.object(window, "screen", return_value=screen):
                    size = window._first_size()
                self.assertEqual((size.width(), size.height()), expected)
        with patch.object(window, "screen", return_value=None):
            size = window._first_size()
        self.assertEqual((size.width(), size.height()), (1100, 860))

    def test_a_pc_with_no_sound_device_still_gets_a_sound_output_of_its_own(self) -> None:
        made: list[tuple] = []

        class NoSoundDevices:
            @staticmethod
            def defaultAudioOutput() -> QAudioDevice:  # noqa: N802
                return QAudioDevice()  # a null device is what Qt hands back when there is none

        def recording_output(*arguments):
            made.append(arguments)
            return QAudioOutput(*arguments)

        with (
            patch.object(review_player, "QMediaDevices", NoSoundDevices),
            patch.object(review_player, "QAudioOutput", recording_output),
        ):
            window = self._window(audio_output_factory=None)

        # Made with the window alone; the null device is never handed over.
        self.assertEqual(len(made), 1)
        self.assertEqual(len(made[0]), 1)
        self.assertIs(made[0][0], window)
        self.assertIsInstance(window.audio_output, QAudioOutput)
        self.assertIs(window.audio_output.parent(), window)
        self.assertAlmostEqual(window.audio_output.volume(), 0.8, places=5)
        # And a recording still opens on it.
        player = self._open(window)
        self.assertIs(player.audio_output, window.audio_output)

    def test_a_sound_device_that_exists_is_named_when_the_output_is_made(self) -> None:
        made: list[tuple] = []
        device = SimpleNamespace(isNull=lambda: False)

        def recording_output(*arguments):
            made.append(arguments)
            return FakeAudioOutput()

        with (
            patch.object(review_player, "QMediaDevices", SimpleNamespace(defaultAudioOutput=lambda: device)),
            patch.object(review_player, "QAudioOutput", recording_output),
        ):
            window = self._window(audio_output_factory=None)

        self.assertEqual(len(made), 1)
        self.assertIs(made[0][0], device)
        self.assertIs(made[0][1], window)

    def test_a_drag_cut_short_by_another_window_does_not_leave_the_video_paused(self) -> None:
        window = self._window()
        player = self._open(window, autoplay=True)
        window.timeline.scrub_started.emit()
        self.assertEqual((player.play_calls, player.pause_calls), (1, 1))

        # Any other kind of change event is not the window losing its place.
        with patch.object(window, "isActiveWindow", return_value=False):
            QApplication.sendEvent(window, QEvent(QEvent.Type.WindowTitleChange))
        self.assertEqual(player.play_calls, 1)

        # Another window takes over mid-drag, so the mouse release that ends
        # the drag never arrives.
        with patch.object(window, "isActiveWindow", return_value=False):
            QApplication.sendEvent(window, QEvent(QEvent.Type.ActivationChange))
        self.assertEqual(player.play_calls, 2)

        # A release that does turn up later must not start it a second time.
        window.timeline.scrub_finished.emit()
        self.assertEqual(player.play_calls, 2)

        # Losing the window while nothing was being dragged changes nothing.
        with patch.object(window, "isActiveWindow", return_value=False):
            QApplication.sendEvent(window, QEvent(QEvent.Type.ActivationChange))
        self.assertEqual(player.play_calls, 2)

    def test_coming_back_to_the_window_brings_the_this_recording_row_up_to_date(self) -> None:
        window = self._window()
        self._open(window)
        self.assertTrue(window.skip_button.isHidden())
        self.assertEqual(window.never_use_button.text(), "Never use this recording")

        # While this window was behind: a run started, and the recording was
        # put on the never-use list from the Find my bug reports page.
        self.host.runner_thread = object()
        self.host.skip_run_sources = lambda sources: list(sources)
        self.host.app_settings[EXCLUDED_KEY] = [str(self.root / SESSION_ONE)]
        self.assertTrue(window.skip_button.isHidden())

        with patch.object(window, "isActiveWindow", return_value=True):
            QApplication.sendEvent(window, QEvent(QEvent.Type.ActivationChange))
        self.assertFalse(window.skip_button.isHidden())
        self.assertEqual(window.never_use_button.text(), "Allow again")
        self.assertEqual(window.recording_status_label.text(), "On your never-use list")

    def test_opening_a_recording_does_not_shrink_a_maximized_window(self) -> None:
        window = self._window()
        self._open(window)
        window.showMaximized()
        window.showMinimized()
        self.assertTrue(window.isMinimized())

        self._open(window, SESSION_TWO)
        self.assertFalse(window.isMinimized())
        self.assertTrue(window.isMaximized())
        self.assertTrue(window.isVisible())

        # A window that was only minimized comes back as it was, not maximized.
        window.showNormal()
        window.showMinimized()
        self._open(window, SESSION_THREE)
        self.assertFalse(window.isMinimized())
        self.assertFalse(window.isMaximized())

    def test_a_note_can_be_put_in_the_status_line_from_outside(self) -> None:
        window = self._window()
        window.show_note("Still looking for this recording's transcript.")
        self.assertEqual(window.status_label.text(), "Still looking for this recording's transcript.")
        window.show_note("")
        self.assertEqual(window.status_label.text(), "")

    def test_release_and_yield_are_safe_before_anything_was_opened(self) -> None:
        window = self._window()
        window.yield_audio()
        window.release_media()
        window.release_media()
        self.assertTrue(window.shutdown(100))
        self.assertEqual(self.factory.players, [])
        # Play with nothing open does nothing and does not raise.
        window.play_action.trigger()
        window.forward_five_action.trigger()
        window.next_line_action.trigger()
        window.step_forward_action.trigger()
        self.assertEqual(self.factory.players, [])

    def test_the_window_remembers_where_it_was(self) -> None:
        first = self._window()
        first.show()
        first.resize(790, 640)
        self.app.processEvents()
        remembered = (first.width(), first.height())
        first.volume_slider.setValue(55)
        first.close()

        stored = self.host.app_settings["review_player_geometry"]
        self.assertIsInstance(stored, str)
        self.assertTrue(stored)
        self.assertEqual(self.host.app_settings["review_player_volume"], 0.55)
        # Saved, not only remembered in memory.
        self.assertGreaterEqual(self.host.save_calls, 1)

        with patch.object(ReviewPlayerWindow, "restoreGeometry") as restore:
            second = self._window()
        restore.assert_called_once()
        self.assertEqual(bytes(restore.call_args.args[0].toBase64()).decode("ascii"), stored)
        self.assertEqual(second.volume_slider.value(), 55)

        # The size itself can only be compared when the screen can hold it:
        # the offscreen platform pretends to an 800 x 800 screen, a theme left
        # behind by another test file can make the smallest window wider than
        # that, and Qt will not restore a window to a size its screen lacks.
        screen = self.app.primaryScreen().availableGeometry()
        if remembered[0] <= screen.width() and remembered[1] <= screen.height():
            third = self._window()
            self.assertEqual((third.width(), third.height()), remembered)

        # A hand-edited value is survived, and a good one is left alone when
        # the operator has turned "restore window position" off.
        self.host.app_settings["review_player_geometry"] = "not base64 at all !!"
        self._window()
        self.host.app_settings["review_player_geometry"] = 12
        self._window()
        self.host.app_settings["restore_window_geometry"] = False
        self.host.app_settings["review_player_geometry"] = stored
        with patch.object(ReviewPlayerWindow, "restoreGeometry") as restore:
            self._window()
        restore.assert_not_called()

    def test_a_host_with_no_settings_at_all_still_gets_a_player(self) -> None:
        window = ReviewPlayerWindow(
            SimpleNamespace(),
            None,
            video_surface_factory=QWidget,
            player_factory=self.factory,
            audio_output_factory=FakeAudioOutput,
        )
        self.windows.append(window)
        window.open_target(self._target())
        self.factory.players[-1].report_loaded()
        window.never_use_current()
        # Nothing can be saved, so nothing is claimed.
        self.assertIn("Could not save that — try again", window.banner_label.text())


class OpeningTests(WindowTestCase):
    def test_the_start_waits_until_the_recording_has_loaded_autoplay_off(self) -> None:
        window = self._window()
        player = self._open(window, loaded=False, start_seconds=2_467.3, autoplay=False)

        # Still loading: a position set now would be silently dropped.
        self.assertEqual(player.set_positions, [])
        self.assertEqual(player.play_calls, 0)
        # The screen already shows where it is going.
        self.assertEqual(window.time_label.text(), "0:41:07 / 0:00:00")

        player.report_loaded(FOUR_HOURS_MS)
        self.assertEqual(player.ignored_positions, [])
        self.assertEqual(player.position(), 2_467_300)
        # Pause first (that alone puts the first picture up), then the seek.
        self.assertEqual(player.calls, ["setSource", "pause", "setPosition:2467300"])
        self.assertEqual(player.play_calls, 0)
        self.assertEqual(window.play_button.text(), "Play")
        self.assertEqual(window.time_label.text(), "0:41:07 / 4:00:00")
        self.assertAlmostEqual(window.timeline.position_seconds(), 2_467.3)

    def test_the_start_waits_until_the_recording_has_loaded_autoplay_on(self) -> None:
        window = self._window()
        player = self._open(window, loaded=False, start_seconds=95.0, autoplay=True)
        self.assertEqual(player.calls, ["setSource"])
        self.assertEqual(window.play_button.text(), "Pause")

        player.report_loaded()
        self.assertEqual(player.ignored_positions, [])
        self.assertEqual(player.position(), 95_000)
        self.assertEqual(player.calls, ["setSource", "setPosition:95000", "play"])
        self.assertEqual(window.play_button.text(), "Pause")

    def test_no_start_time_means_no_seek_at_all(self) -> None:
        window = self._window()
        player = self._open(window, autoplay=True)
        self.assertEqual(player.calls, ["setSource", "play"])
        paused = self._open(window, SESSION_TWO, autoplay=False)
        self.assertEqual(paused.calls, ["setSource", "pause"])

    def test_buffered_counts_as_loaded_and_only_the_first_report_applies(self) -> None:
        window = self._window()
        player = self._open(window, loaded=False, start_seconds=12.0, autoplay=False)
        player._loaded_reported = True
        player._status = QMediaPlayer.MediaStatus.BufferedMedia
        player.mediaStatusChanged.emit(player._status)
        self.assertEqual(player.set_positions, [12_000])

        player.arrive()
        player.move_to(300_000)
        # The player reports "buffered" again after every stall.
        player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.BufferedMedia)
        player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.LoadedMedia)
        self.assertEqual(player.set_positions, [12_000])
        self.assertEqual(player.pause_calls, 1)

    def test_the_readout_is_hours_minutes_seconds_for_a_four_hour_recording(self) -> None:
        window = self._window()
        player = self._open(window, loaded=False, autoplay=False)
        player.report_loaded(FOUR_HOURS_MS)
        self.assertEqual(window.time_label.text(), "0:00:00 / 4:00:00")
        player.move_to(FOUR_HOURS_MS - 1_000)
        self.assertEqual(window.time_label.text(), "3:59:59 / 4:00:00")
        player.move_to(59_999)
        self.assertEqual(window.time_label.text(), "0:00:59 / 4:00:00")

    def test_a_new_recording_gets_a_new_player_and_the_old_one_is_let_go(self) -> None:
        window = self._window()
        first = self._open(window)
        first_generation = window._player_generation
        second = self._open(window, SESSION_TWO)

        self.assertIsNot(first, second)
        self.assertGreater(window._player_generation, first_generation)
        self.assertEqual(Path(second.source().toLocalFile()), self.root / SESSION_TWO)
        self.assertIs(second.video_output, window.video_surface)
        # The old player: paused, source dropped (that frees the file), every
        # signal disconnected, deleted - and never told to stop.
        self.assertEqual(first.stop_calls, 0)
        self.assertTrue(first.source().isEmpty())
        self.assertEqual(first.calls[-2:], ["pause", "setSource"])
        for name in review_player._PLAYER_SIGNALS:
            self.assertEqual(getattr(first, name).slots, [], name)
        self.assertTrue(first.deleted)
        self.assertFalse(second.deleted)

    def test_a_late_report_from_a_replaced_player_moves_nothing(self) -> None:
        window = self._window()
        first = self._open(window)
        # Kept as they were connected: a report already on its way is not
        # stopped by disconnecting.
        late = {name: list(getattr(first, name).slots) for name in review_player._PLAYER_SIGNALS}
        second = self._open(window, SESSION_TWO, autoplay=False)
        second.report_loaded(FOUR_HOURS_MS)
        second.move_to(65_000)
        before = (
            window.time_label.text(),
            window.timeline.position_seconds(),
            window.play_button.text(),
            window.status_label.text(),
            window.video_stack.currentWidget(),
            window.track_combo.count(),
        )

        first._tracks = [QMediaMetaData(), QMediaMetaData(), QMediaMetaData()]
        first._position = 3_000_000
        for slot in late["positionChanged"]:
            slot(3_000_000)
        for slot in late["durationChanged"]:
            slot(5)
        for slot in late["playbackStateChanged"]:
            slot(QMediaPlayer.PlaybackState.PlayingState)
        for slot in late["mediaStatusChanged"]:
            slot(QMediaPlayer.MediaStatus.LoadedMedia)
            slot(QMediaPlayer.MediaStatus.InvalidMedia)
        for slot in late["errorOccurred"]:
            slot(QMediaPlayer.Error.FormatError, "synthetic late failure")
        for slot in late["tracksChanged"]:
            slot()

        after = (
            window.time_label.text(),
            window.timeline.position_seconds(),
            window.play_button.text(),
            window.status_label.text(),
            window.video_stack.currentWidget(),
            window.track_combo.count(),
        )
        self.assertEqual(after, before)
        self.assertEqual(second.play_calls, 0)
        self.assertEqual(self.diagnostics, [])

    def test_the_same_recording_is_only_seeked_never_reloaded(self) -> None:
        window = self._window()
        player = self._open(window, autoplay=False)
        player.move_to(500_000)
        generation = window._player_generation

        # Same file, spelled in another case, from a different view.
        again = PlayTarget(path=Path(str(self.root / SESSION_ONE).upper()), start_seconds=61.5)
        window.open_target(again, autoplay=False)

        self.assertEqual(len(self.factory.players), 1)
        self.assertEqual(window._player_generation, generation)
        self.assertEqual(player.calls.count("setSource"), 1)
        self.assertEqual(player.stop_calls, 0)
        self.assertEqual(player.set_positions, [61_500])
        self.assertEqual(window._coalescer.requested_ms(), 61_500)
        self.assertEqual(window.time_label.text(), "0:01:01 / 0:10:00")

        # A plain Play of the open recording keeps the operator's place.
        player.arrive()
        window.open_target(self._target(), autoplay=True)
        self.assertEqual(player.set_positions, [61_500])
        self.assertEqual(player.play_calls, 1)
        self.assertEqual(len(self.factory.players), 1)

    def test_the_same_recording_while_still_loading_replaces_what_is_waiting(self) -> None:
        window = self._window()
        player = self._open(window, loaded=False, start_seconds=10.0, autoplay=True)
        window.open_target(self._target(start_seconds=200.0), autoplay=False)

        self.assertEqual(len(self.factory.players), 1)
        self.assertEqual(player.set_positions, [])
        player.report_loaded()
        self.assertEqual(player.ignored_positions, [])
        self.assertEqual(player.calls, ["setSource", "pause", "setPosition:200000"])

    def test_the_list_it_was_opened_from_survives_a_moment_of_the_same_recording(self) -> None:
        window = self._window()
        sequence = self._sequence(SESSION_ONE, SESSION_TWO)
        self._open(window, sequence=sequence)
        # An evidence moment of the recording that is already open has no list.
        window.open_target(self._target(start_seconds=30.0), autoplay=False)
        self.assertEqual(window._sequence, sequence)

    def test_starting_to_play_reaches_into_no_other_player(self) -> None:
        # 136 (Wave 8): the New Review wizard's own preview player is gone, folded into this
        # window, so there is no other Workbench player for this one to pause any more. An old
        # attribute of that name on the host is left alone.
        leftover = FakePlayer()
        leftover.play()
        self.host.audio_player = leftover
        window = self._window()
        player = self._open(window, loaded=False, autoplay=True)
        player.report_loaded()
        self.assertEqual(leftover.pause_calls, 0)
        self.assertEqual(player.play_calls, 1)

    def test_yield_audio_pauses_and_keeps_the_place(self) -> None:
        window = self._window()
        player = self._open(window, autoplay=True)
        player.move_to(77_000)
        window.yield_audio()

        self.assertEqual(player.pause_calls, 1)
        self.assertEqual(player.stop_calls, 0)
        self.assertFalse(player.source().isEmpty())
        self.assertEqual(player.position(), 77_000)
        self.assertEqual(window.play_button.text(), "Play")

    def test_yield_audio_while_loading_cancels_the_waiting_autoplay(self) -> None:
        window = self._window()
        player = self._open(window, loaded=False, autoplay=True)
        window.yield_audio()
        player.report_loaded()
        self.assertEqual(player.play_calls, 0)

    def test_release_lets_go_of_the_file_and_play_picks_it_up_again(self) -> None:
        window = self._window()
        player = self._open(window, autoplay=True)
        player.move_to(125_000)

        window.release_media()
        window.release_media()
        self.assertTrue(player.source().isEmpty())
        self.assertEqual(player.calls[-2:], ["pause", "setSource"])
        self.assertEqual(player.stop_calls, 0)
        self.assertTrue(player.deleted)
        # The screen still says where the recording was, and what Play does.
        self.assertEqual(window.time_label.text(), "0:02:05 / 0:10:00")
        self.assertEqual(window.play_button.text(), "Play")
        self.assertEqual(window.status_label.text(), "Stopped. Press Play to carry on from 0:02:05.")

        # The main window asked for the file and then did not close after all.
        window.play_action.trigger()
        self.assertEqual(len(self.factory.players), 2)
        again = self.factory.players[-1]
        self.assertEqual(Path(again.source().toLocalFile()), self.root / SESSION_ONE)
        again.report_loaded()
        self.assertEqual(again.calls, ["setSource", "setPosition:125000", "play"])
        self.assertNotIn("Stopped.", window.status_label.text())

    def test_release_in_the_middle_of_a_transcript_search_does_not_go_on_claiming_to_look(self) -> None:
        seen: list[str] = []

        def slow_find(recording, hints, *, duration_seconds=None, cancelled=lambda: False):
            seen.append(Path(recording).name)
            deadline = time.monotonic() + 10
            while not cancelled() and time.monotonic() < deadline:
                time.sleep(0.005)
            return None

        with patch.object(review_player, "find_package_for_recording", slow_find):
            window = self._window()
            window.open_target(self._target(package_root=self.root / "synthetic-run"), autoplay=True)
            player = self.factory.players[-1]
            player.report_loaded()
            player.move_to(125_000)
            self._wait_until(lambda: seen == [SESSION_ONE])
            self.assertEqual(window.transcript_note.text(), "Looking for a transcript…")
            (thread,) = tuple(window._package_threads)

            # What the main window does first, every time it is asked to close.
            window.release_media()
            released_note = "The transcript will be looked for again when you press Play."
            self.assertEqual(window.transcript_note.text(), released_note)
            self.assertFalse(window.transcript_note.isHidden())
            self.assertEqual(window.status_label.text(), "Stopped. Press Play to carry on from 0:02:05.")

            # The cancelled search still reports once ("nothing found"). That
            # late report must change nothing.
            self.assertTrue(thread.wait(5000))
            self._wait_until(lambda: thread not in window._package_threads)
            self.assertEqual(window.transcript_note.text(), released_note)

            # The main window did not close after all. Play reloads the
            # recording at the saved place and looks again.
            window.play_action.trigger()
            again = self.factory.players[-1]
            self.assertIsNot(again, player)
            again.report_loaded()
            self.assertEqual(again.calls, ["setSource", "setPosition:125000", "play"])
            self._wait_until(lambda: seen == [SESSION_ONE, SESSION_ONE])
            self.assertEqual(window.transcript_note.text(), "Looking for a transcript…")

    def test_release_leaves_a_transcript_that_was_found_on_screen(self) -> None:
        window = self._window()
        self._open(window, autoplay=False)
        self._show_lines(window)
        window.release_media()
        self.assertEqual(window.transcript_header.text(), "Transcript from: synthetic-run")
        self.assertTrue(window.transcript_note.isHidden())

    def test_shutdown_releases_the_source_and_reports_success(self) -> None:
        window = self._window()
        player = self._open(window)
        self.assertTrue(window.shutdown(5000))
        self.assertEqual(player.stop_calls, 0)
        self.assertTrue(player.source().isEmpty())
        self.assertTrue(player.deleted)
        self.assertEqual(window._package_threads, set())
        self.assertIsInstance(self.host.app_settings["review_player_geometry"], str)

    def test_a_change_of_track_then_another_recording_never_stops_the_player(self) -> None:
        # Measured with the real player: stop() straight after a change of
        # audio track never returns, and that freezes the whole app. However
        # short or long ago the change was, the player is paused and its
        # source emptied, and nothing else.
        window = self._window()
        first = self._open(window, loaded=False)
        first.report_loaded(titles=("Track1", "Microphone"))
        for index in (1, 0, 1, 0, 1):
            window.track_combo.setCurrentIndex(index)
        self.assertEqual(first.calls.count("setActiveAudioTrack:1"), 3)

        self._open(window, SESSION_TWO)
        self.assertEqual(first.stop_calls, 0)
        self.assertEqual(first.calls[-3:], ["setActiveAudioTrack:1", "pause", "setSource"])
        self.assertTrue(first.source().isEmpty())
        self.assertTrue(first.deleted)

    def test_a_note_is_said_once_the_recording_is_open(self) -> None:
        window = self._window()
        player = self._open(window, loaded=False, label="synthetic moment label", note="Synthetic note.")
        self.assertEqual(window.status_label.text(), f"Opening {SESSION_ONE}…")
        player.report_loaded()
        self.assertEqual(window.status_label.text(), "Synthetic note.")

        # No note: the target's own label, as before.
        other = self._open(window, SESSION_TWO, label="synthetic moment label")
        self.assertEqual(window.status_label.text(), "synthetic moment label")

        # The recording that is already open says it at once.
        window.open_target(self._target(SESSION_TWO, start_seconds=5.0), autoplay=False, note="Second note.")
        self.assertEqual(len(self.factory.players), 2)
        self.assertEqual(window.status_label.text(), "Second note.")
        self.assertEqual(other.set_positions, [5_000])

    def test_a_note_for_a_recording_still_loading_waits_with_the_start(self) -> None:
        window = self._window()
        player = self._open(window, loaded=False)
        window.open_target(self._target(start_seconds=9.0), autoplay=False, note="Synthetic note.")
        self.assertEqual(window.status_label.text(), f"Opening {SESSION_ONE}…")
        player.report_loaded()
        self.assertEqual(window.status_label.text(), "Synthetic note.")


class TransportTests(WindowTestCase):
    def test_jumps_add_up_from_where_the_operator_asked_to_be(self) -> None:
        window = self._window()
        player = self._open(window, autoplay=False)
        player.move_to(60_000)

        for _press in range(3):
            window.forward_five_action.trigger()
        # One seek is with the player; the rest waited and were merged.
        self.assertEqual(player.set_positions, [65_000])
        self.assertEqual(window._coalescer.requested_ms(), 75_000)
        # The screen does not wait for the player.
        self.assertEqual(window.time_label.text(), "0:01:15 / 0:10:00")
        self.assertAlmostEqual(window.timeline.position_seconds(), 75.0)

        player.arrive()
        self.assertEqual(player.set_positions, [65_000, 75_000])
        window.back_five_button.click()
        self.assertEqual(window._coalescer.requested_ms(), 70_000)
        player.arrive()
        player.arrive()
        self.assertEqual(player.position(), 70_000)
        self.assertIsNone(window._coalescer.requested_ms())

    def test_the_player_position_does_not_flicker_onto_the_screen_mid_seek(self) -> None:
        window = self._window()
        player = self._open(window, autoplay=False)
        player.move_to(60_000)
        window.forward_five_action.trigger()
        window.forward_five_action.trigger()
        # A frame from before the jump reports the old place.
        player.positionChanged.emit(60_040)
        self.assertEqual(window.time_label.text(), "0:01:10 / 0:10:00")
        self.assertAlmostEqual(window.timeline.position_seconds(), 70.0)
        self.assertEqual(player.set_positions, [65_000])

    def test_jumps_stay_inside_the_recording(self) -> None:
        window = self._window()
        player = self._open(window, autoplay=False)
        window.back_five_action.trigger()
        self.assertEqual(player.set_positions, [0])
        player.arrive()
        player.move_to(TEN_MINUTES_MS - 2_000)
        window.forward_five_action.trigger()
        self.assertEqual(player.set_positions[-1], TEN_MINUTES_MS)

    def test_a_jump_while_loading_moves_the_waiting_start(self) -> None:
        window = self._window()
        player = self._open(window, loaded=False, start_seconds=100.0, autoplay=False)
        window.forward_five_action.trigger()
        window.forward_five_action.trigger()
        self.assertEqual(player.set_positions, [])
        self.assertEqual(window.time_label.text(), "0:01:50 / 0:00:00")
        player.report_loaded()
        self.assertEqual(player.position(), 110_000)

    def test_a_scrub_pauses_a_playing_video_and_resumes_it(self) -> None:
        window = self._window()
        player = self._open(window, autoplay=True)
        self.assertEqual((player.play_calls, player.pause_calls), (1, 0))

        window.timeline.scrub_started.emit()
        self.assertEqual(player.pause_calls, 1)
        window.timeline.seek_requested.emit(120.0)
        window.timeline.seek_requested.emit(180.0)
        window.timeline.seek_requested.emit(240.0)
        self.assertEqual(player.set_positions, [120_000])
        self.assertEqual(player.play_calls, 1)

        window.timeline.scrub_finished.emit()
        self.assertEqual(player.play_calls, 2)
        player.arrive()
        self.assertEqual(player.set_positions, [120_000, 240_000])

    def test_a_scrub_of_a_paused_video_leaves_it_paused(self) -> None:
        window = self._window()
        player = self._open(window, autoplay=False)
        window.timeline.scrub_started.emit()
        window.timeline.seek_requested.emit(90.0)
        window.timeline.scrub_finished.emit()
        self.assertEqual(player.play_calls, 0)
        self.assertEqual(player.pause_calls, 1)  # only the one from opening paused

    def test_a_real_drag_on_the_timeline_goes_through_the_seek_queue(self) -> None:
        window = self._window()
        player = self._open(window, autoplay=True)
        window.resize(1000, 800)
        self.app.processEvents()
        bar = window.timeline
        middle = QPoint(bar.width() // 2, bar.height() // 2)
        later = QPoint(bar.width() * 3 // 4, bar.height() // 2)

        QTest.mousePress(bar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, middle)
        try:
            self.assertEqual(player.pause_calls, 1)
            QTest.mouseMove(bar, later)
        finally:
            QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, later)

        self.assertEqual(len(player.set_positions), 1)
        self.assertAlmostEqual(player.set_positions[0] / 1000, bar.seconds_at(middle.x()), delta=0.002)
        self.assertAlmostEqual(
            window._coalescer.requested_ms() / 1000, bar.seconds_at(later.x()), delta=0.002
        )
        self.assertEqual(player.play_calls, 2)

    def test_play_and_pause(self) -> None:
        window = self._window()
        player = self._open(window, autoplay=False)
        window.play_button.click()
        self.assertEqual(player.play_calls, 1)
        self.assertEqual(window.play_button.text(), "Pause")
        window.play_action.trigger()
        self.assertEqual(player.pause_calls, 2)
        self.assertEqual(window.play_button.text(), "Play")

    def test_play_while_loading_is_remembered_not_sent(self) -> None:
        window = self._window()
        player = self._open(window, loaded=False, autoplay=False)
        window.play_action.trigger()
        self.assertEqual(player.calls, ["setSource"])
        self.assertEqual(window.play_button.text(), "Pause")
        player.report_loaded()
        self.assertEqual(player.play_calls, 1)

    def test_step_forward_plays_until_the_next_picture_and_stays_silent(self) -> None:
        window = self._window()
        player = self._open(window, autoplay=False)
        player.move_to(10_000)

        window.step_forward_action.trigger()
        self.assertEqual(player.play_calls, 1)
        self.assertTrue(window.audio_output.isMuted())
        # A frame or two of playing is not "playing": no flash to Pause.
        self.assertEqual(window.play_button.text(), "Play")
        # The picture already on screen is shown again first; that is no step.
        player.positionChanged.emit(10_000)
        self.assertEqual(player.pause_calls, 1)

        player.move_to(10_040)
        self.assertEqual(player.pause_calls, 2)
        self.assertFalse(window.audio_output.isMuted())
        self.assertEqual(window.play_button.text(), "Play")

    def test_play_pressed_in_the_middle_of_a_step_keeps_playing(self) -> None:
        window = self._window()
        player = self._open(window, autoplay=False)
        window.step_forward_action.trigger()
        window.play_action.trigger()
        player.move_to(40)
        self.assertEqual(player.pause_calls, 1)  # only the one from opening paused
        self.assertEqual(player.play_calls, 1)
        self.assertFalse(window.audio_output.isMuted())
        self.assertEqual(window.play_button.text(), "Pause")

    def test_step_forward_gives_up_when_no_picture_comes(self) -> None:
        window = self._window()
        player = self._open(window, autoplay=False)
        window.step_forward_action.trigger()
        self.assertTrue(window._step_timer.isActive())
        window._step_timer.timeout.emit()
        self.assertEqual(player.pause_calls, 2)
        self.assertFalse(window.audio_output.isMuted())

    def test_step_back_is_one_frame_through_the_seek_queue(self) -> None:
        window = self._window()
        player = self._open(window, autoplay=True)
        player.move_to(10_000)
        window.step_back_action.trigger()
        # The fake names no frame rate, so the 33 ms fallback applies.
        self.assertEqual(player.set_positions, [9_967])
        self.assertEqual(player.pause_calls, 1)
        self.assertEqual(window._coalescer.requested_ms(), 9_967)

    def test_speed_is_applied_now_and_to_the_next_recording(self) -> None:
        window = self._window()
        player = self._open(window)
        self.assertEqual(player.rates, [1.0])
        window.speed_combo.setCurrentIndex(2)
        self.assertEqual(player.rates, [1.0, 4.0])
        following = self._open(window, SESSION_TWO)
        self.assertEqual(following.rates, [4.0])

    def test_tracks_are_named_for_the_operator(self) -> None:
        window = self._window()
        player = self._open(window, loaded=False, voice_track=3)
        player.report_loaded(titles=("Track1", "Game and spotter", "Microphone", "", "track 5"))
        self.assertEqual(
            [window.track_combo.itemText(index) for index in range(window.track_combo.count())],
            [
                "Track 1",
                "Track 2 - Game and spotter",
                "Track 3 - Microphone - your voice",
                "Track 4",
                "Track 5",
            ],
        )
        self.assertTrue(window.track_combo.isEnabled())
        # Filling the list is not the operator choosing a track.
        self.assertNotIn("setActiveAudioTrack:0", player.calls)

        window.track_combo.setCurrentIndex(2)
        self.assertEqual(player.activeAudioTrack(), 2)
        self.assertEqual(window.status_label.text(), "Hearing Track 3.")

    def test_one_track_leaves_nothing_to_choose(self) -> None:
        window = self._window()
        player = self._open(window, loaded=False)
        player.report_loaded(titles=("Track1",))
        self.assertEqual(window.track_combo.count(), 1)
        self.assertFalse(window.track_combo.isEnabled())


class TranscriptPanelTests(WindowTestCase):
    def _ready(self, **overrides):
        window = self._window()
        player = self._open(window, autoplay=False)
        self._show_lines(window, **overrides)
        return window, player

    def test_no_transcript_is_a_plain_sentence_and_the_player_carries_on(self) -> None:
        window = self._window()
        player = self._open(window, autoplay=False)
        # No package anywhere to ask, so no thread is even started.
        self.assertEqual(window._package_threads, set())
        self.assertEqual(
            window.transcript_note.text(),
            "No transcript found for this recording. Run Find my bug reports on it to get one.",
        )
        self.assertTrue(window.transcript_header.isHidden())
        self.assertFalse(window.next_line_button.isEnabled())
        self.assertFalse(window.line_filter_combo.isEnabled())
        self.assertEqual(window.current_line_label.text(), "")
        self.assertTrue(window.hear_track_button.isHidden())

        window.next_line_action.trigger()
        window.play_action.trigger()
        self.assertEqual(player.play_calls, 1)
        self.assertEqual(player.set_positions, [])

    def test_the_header_names_the_run_folder(self) -> None:
        window, _player = self._ready()
        self.assertEqual(window.transcript_header.text(), "Transcript from: synthetic-run")
        self.assertFalse(window.transcript_header.isHidden())
        self.assertTrue(window.transcript_note.isHidden())
        self.assertTrue(window.next_line_button.isEnabled())

    def test_a_recording_that_was_not_filtered_says_so(self) -> None:
        window, _player = self._ready(mode="Continuous", filtering_ran=False)
        self.assertEqual(
            window.transcript_note.text(),
            "No filtering ran for this recording — it was transcribed in Continuous mode.",
        )
        self.assertNotIn("left out", window.transcript_note.text().lower())

        self._show_lines(window, mode="Auto", filtering_ran=False)
        self.assertIn("transcribed in Auto mode.", window.transcript_note.text())
        self._show_lines(window, mode="", filtering_ran=False)
        self.assertEqual(window.transcript_note.text(), "This package does not say whether any filtering ran.")

    def test_an_older_package_says_left_out_lines_were_not_recorded(self) -> None:
        # No audit also means no mode, and this is the sentence that matters.
        window, _player = self._ready(mode="", filtering_ran=False, audit_available=False, rescued_known=False)
        self.assertEqual(
            window.transcript_note.text(),
            "This package was made before left-out lines were recorded.",
        )

    def test_a_package_from_before_rescues_were_recorded_says_so(self) -> None:
        window, _player = self._ready(rescued_known=False)
        self.assertEqual(
            window.transcript_note.text(),
            "This package does not say which lines were kept only for sitting next to real speech.",
        )

    def test_between_lines_says_when_the_next_one_is(self) -> None:
        window, player = self._ready()
        self.assertEqual(
            window.current_line_label.text(), "Nothing transcribed here. Next line at 0:00:10."
        )
        self.assertEqual(window.previous_line_label.text(), "")
        self.assertEqual(window.next_line_label.text(), "0:00:10  synthetic kept line one")

        player.move_to(15_000)
        self.assertEqual(
            window.current_line_label.text(), "Nothing transcribed here. Next line at 0:00:20."
        )
        self.assertEqual(window.previous_line_label.text(), "0:00:10  synthetic kept line one")
        self.assertEqual(window.line_badge_label.text(), "")
        self.assertTrue(window.line_reason_label.isHidden())

        player.move_to(200_000)
        self.assertEqual(
            window.current_line_label.text(),
            "Nothing transcribed here. There are no more lines after this.",
        )

    def test_a_kept_line_is_shown_large_with_its_neighbours_dimmed(self) -> None:
        window, player = self._ready()
        player.move_to(31_000)
        self.assertEqual(window.current_line_label.text(), "synthetic kept line two")
        self.assertEqual(window.previous_line_label.text(), "0:00:20  synthetic stock phrase")
        self.assertEqual(window.next_line_label.text(), "0:00:40  synthetic repeated words")
        self.assertEqual(window.line_time_label.text(), "0:00:30–0:00:33")
        self.assertEqual(window.line_badge_label.text(), "")
        self.assertTrue(window.line_reason_label.isHidden())
        # Also true with the app's theme applied, whose stylesheet overrides
        # any font that is merely set in code.
        for label in (window.current_line_label, window.previous_line_label):
            label.ensurePolished()
        self.assertEqual(window.current_line_label.font().pointSize(), review_player.CURRENT_LINE_POINT_SIZE)
        self.assertGreater(
            window.current_line_label.font().pointSizeF(), window.previous_line_label.font().pointSizeF()
        )
        self.assertTrue(window.previous_line_label.property("muted"))
        self.assertTrue(window.next_line_label.property("muted"))
        self.assertNotEqual(window.current_line_label.property("statusKind"), "attention")

    def test_a_left_out_line_is_amber_with_its_badge_and_reason(self) -> None:
        window, player = self._ready()
        player.move_to(20_500)
        self.assertEqual(window.current_line_label.text(), "synthetic stock phrase")
        self.assertEqual(window.current_line_label.property("statusKind"), "attention")
        self.assertEqual(window.line_badge_label.text(), "Left out")
        self.assertEqual(window.line_badge_label.property("statusKind"), "attention")
        self.assertEqual(window.line_reason_label.text(), FILLER_REASON)
        self.assertFalse(window.line_reason_label.isHidden())

        # On to a kept line and the amber goes again.
        player.move_to(31_000)
        self.assertEqual(window.current_line_label.property("statusKind"), "")
        self.assertTrue(window.line_reason_label.isHidden())

    def test_a_stretch_thrown_out_whole_shows_what_had_been_written(self) -> None:
        window, player = self._ready()
        player.move_to(55_000)
        self.assertEqual(window.current_line_label.text(), "synthetic repeated words")
        self.assertEqual(window.line_badge_label.text(), "Left out")
        self.assertEqual(window.line_reason_label.text(), REJECTED_REASON)
        self.assertEqual(window.line_time_label.text(), "0:00:40–0:01:10")

    def test_rescued_and_spotter_lines_get_their_badges(self) -> None:
        window, player = self._ready()
        player.move_to(81_000)
        # Said in plain words on the badge, and explained where the mouse rests.
        self.assertEqual(window.line_badge_label.text(), "Kept — it sits next to real speech")
        self.assertEqual(
            window.line_badge_label.toolTip(),
            "The transcriber was unsure of this line. It was kept only because it sits next to real speech.",
        )
        self.assertEqual(window.current_line_label.property("statusKind"), "")
        self.assertTrue(window.line_reason_label.isHidden())

        player.move_to(91_000)
        self.assertEqual(window.line_badge_label.text(), "Sounds like the spotter, not you")
        self.assertEqual(window.line_badge_label.property("statusKind"), "attention")
        # The explanation belongs to the badge it explains and goes with it.
        self.assertEqual(window.line_badge_label.toolTip(), "")
        player.move_to(81_000)
        player.move_to(85_000)
        self.assertEqual(window.line_badge_label.toolTip(), "")

    def test_a_left_out_line_with_no_words_still_shows_something(self) -> None:
        lines = (_line(5.0, 6.0, "", kind="left_out", reason_text="Left out: there were no words in it."),)
        window, player = self._ready(lines=lines)
        player.move_to(5_500)
        self.assertEqual(window.current_line_label.text(), "(no words)")
        self.assertEqual(window.line_reason_label.text(), "Left out: there were no words in it.")

    def test_show_the_numbers_reveals_the_figures_and_the_original_wording(self) -> None:
        window, player = self._ready()
        player.move_to(10_500)
        self.assertTrue(window.line_numbers_label.isHidden())

        window.show_numbers_checkbox.setChecked(True)
        self.assertFalse(window.line_numbers_label.isHidden())
        # One plain line per score: no field names, and never a bare negative
        # figure presented as a "confidence".
        self.assertEqual(
            window.line_numbers_label.text().split("\n"),
            [
                "Chance nobody was speaking: 2%",
                "How sure it was of the words: high (-0.21)",
                "How much it repeated itself: 1.40 (above 2.4 means it was looping)",
                "Before your glossary: synthetic kept line won",
            ],
        )

        # A left-out line that only carries one of the three scores.
        player.move_to(20_500)
        self.assertEqual(window.line_numbers_label.text(), "Chance nobody was speaking: 91%")

        player.move_to(31_000)
        self.assertEqual(window.line_numbers_label.text(), "This package recorded no numbers for this line.")
        window.show_numbers_checkbox.setChecked(False)
        self.assertTrue(window.line_numbers_label.isHidden())

    def test_how_sure_the_transcriber_was_is_said_in_a_word(self) -> None:
        for figure, word in (
            (0.0, "high"),
            (-0.3, "high"),
            (-0.31, "medium"),
            (-0.6, "medium"),
            (-0.61, "low"),
            (-2.5, "low"),
        ):
            with self.subTest(figure=figure):
                self.assertEqual(
                    review_player._number_lines((("avg_logprob", figure),)),
                    [f"How sure it was of the words: {word} ({figure:.2f})"],
                )
        self.assertEqual(
            review_player._number_lines((("no_speech_prob", 0.5), ("compression_ratio", 0.5))),
            [
                "Chance nobody was speaking: 50%",
                "How much it repeated itself: 0.50 (above 2.4 means it was looping)",
            ],
        )
        # A score this window has no words for is left out, not shown by its
        # programmer's name; nonsense is survived.
        self.assertEqual(
            review_player._number_lines(
                (("synthetic_new_score", 1.0), ("avg_logprob", float("nan")), ("no_speech_prob", "high"))
            ),
            [],
        )

    def test_the_show_the_numbers_tooltip_is_in_plain_words(self) -> None:
        window = self._window()
        tooltip = window.show_numbers_checkbox.toolTip()
        self.assertIn("the chance nobody was speaking", tooltip)
        self.assertIn("before your glossary was applied", tooltip)
        self.assertNotIn("_", tooltip)

    def test_the_timeline_is_marked_where_the_lines_are(self) -> None:
        window, _player = self._ready()
        self.assertEqual(
            [(start, kind) for start, kind, _end in window.timeline._ticks],
            [
                (10.0, "kept"),
                (20.0, "left_out"),
                (30.0, "kept"),
                (40.0, "rejected_span"),
                (80.0, "kept"),
                (90.0, "kept"),
            ],
        )
        # A stretch thrown out whole is drawn to its real length.
        self.assertEqual(window.timeline._ticks[3], (40.0, "rejected_span", 70.0))

        window.line_filter_combo.setCurrentIndex(2)
        self.assertEqual([kind for _start, kind, _end in window.timeline._ticks], ["left_out", "rejected_span"])
        window.line_filter_combo.setCurrentIndex(1)
        self.assertEqual({kind for _start, kind, _end in window.timeline._ticks}, {"kept"})

    def test_next_and_previous_line_follow_the_filter(self) -> None:
        window, player = self._ready()
        window.next_line_action.trigger()
        self.assertEqual(player.set_positions, [10_000])
        player.arrive()
        window.next_line_button.click()
        self.assertEqual(player.set_positions, [10_000, 20_000])
        player.arrive()
        self.assertEqual(window.current_line_label.text(), "synthetic stock phrase")

        # Kept only: the left-out line and the thrown-out stretch are skipped.
        window.line_filter_combo.setCurrentIndex(1)
        self.assertEqual(
            window.current_line_label.text(), "Nothing transcribed here. Next line at 0:00:30."
        )
        window.next_line_action.trigger()
        player.arrive()
        window.next_line_action.trigger()
        self.assertEqual(player.set_positions[-2:], [30_000, 80_000])
        player.arrive()

        # Left out only, going backwards.
        window.line_filter_combo.setCurrentIndex(2)
        window.previous_line_action.trigger()
        self.assertEqual(player.set_positions[-1], 40_000)
        player.arrive()
        window.previous_line_button.click()
        self.assertEqual(player.set_positions[-1], 20_000)
        player.arrive()
        window.previous_line_action.trigger()
        # Nothing before the first line: it starts that line again.
        self.assertEqual(player.set_positions[-1], 20_000)

    def test_previous_line_restarts_a_line_that_is_well_under_way(self) -> None:
        window, player = self._ready()
        player.move_to(31_500)
        window.previous_line_action.trigger()
        self.assertEqual(player.set_positions, [30_000])
        player.arrive()
        player.move_to(30_400)
        window.previous_line_action.trigger()
        self.assertEqual(player.set_positions, [30_000, 20_000])

    def test_quick_presses_walk_down_the_lines_without_waiting_for_the_player(self) -> None:
        window, player = self._ready()
        for _press in range(3):
            window.next_line_action.trigger()
        self.assertEqual(player.set_positions, [10_000])
        self.assertEqual(window._coalescer.requested_ms(), 30_000)
        self.assertEqual(window.current_line_label.text(), "synthetic kept line two")

    def test_the_ends_of_the_list_are_said_not_wrapped(self) -> None:
        window, player = self._ready()
        window.previous_line_action.trigger()
        self.assertEqual(window.status_label.text(), "There is no line before this.")
        player.move_to(300_000)
        window.next_line_action.trigger()
        self.assertEqual(window.status_label.text(), "There are no more lines after this.")
        self.assertEqual(player.set_positions, [])

    def test_a_line_start_lands_on_the_line_not_just_before_it(self) -> None:
        lines = (_line(12.3, 14.0, "synthetic line at an awkward time"), _line(20.0007, 21.0, "synthetic next"))
        window, player = self._ready(lines=lines)
        window.next_line_action.trigger()
        self.assertEqual(player.set_positions, [12_300])
        player.arrive()
        self.assertEqual(window.current_line_label.text(), "synthetic line at an awkward time")
        window.next_line_action.trigger()
        self.assertEqual(player.set_positions[-1], 20_001)
        player.arrive()
        self.assertEqual(window.current_line_label.text(), "synthetic next")

    def test_a_filter_with_nothing_in_it_says_so(self) -> None:
        window, _player = self._ready(lines=(_line(10.0, 12.0, "synthetic kept line one"),))
        window.line_filter_combo.setCurrentIndex(2)
        self.assertEqual(window.current_line_label.text(), "No lines to show with this filter.")

    def test_the_saved_track_explanation_comes_with_hear_this_track(self) -> None:
        window = self._window()
        player = self._open(window, loaded=False, autoplay=False)
        player.report_loaded(titles=("Track1", "Microphone"))
        self._show_lines(window, track_explanation="Track 2 carries your narration.", transcribed_track=2)

        self.assertEqual(window.track_explanation_label.text(), "Track 2 carries your narration.")
        self.assertFalse(window.hear_track_button.isHidden())
        self.assertTrue(window.hear_track_button.isEnabled())
        # 212: the player already starts on the track the transcript came from.
        self.assertEqual(player.activeAudioTrack(), 1)
        self.assertEqual(window.track_combo.currentIndex(), 1)

        window.hear_track_button.click()
        self.assertEqual(window.status_label.text(), "You are already hearing Track 2.")
        self.assertEqual(player.calls.count("setActiveAudioTrack:1"), 1)

        # Back on Track 1 by the operator's choice, the button brings the transcript's track back.
        window.track_combo.setCurrentIndex(0)
        window.hear_track_button.click()
        self.assertEqual(player.activeAudioTrack(), 1)
        self.assertEqual(window.status_label.text(), "Hearing Track 2.")

    def test_a_known_track_without_an_explanation_is_still_offered(self) -> None:
        window = self._window()
        player = self._open(window, loaded=False, autoplay=False)
        player.report_loaded(titles=("Track1", "Microphone"))
        self._show_lines(window, transcribed_track=2)
        self.assertEqual(window.track_explanation_label.text(), "This transcript was made from Track 2.")

        # A transcript that names a track this recording does not have.
        self._show_lines(window, transcribed_track=6)
        self.assertFalse(window.hear_track_button.isEnabled())

    def test_the_voice_track_says_what_decided_it(self) -> None:
        # 196: a track found by a run is marked with what decided it.
        recording = self.root / SESSION_ONE
        window = self._window()
        player = self._open(window, loaded=False, autoplay=False)
        player.report_loaded(titles=("Track1", "Microphone"))
        window.open_target(PlayTarget(path=recording, voice_track=2, voice_source="from track name"), autoplay=False)
        self.assertEqual(window.track_combo.itemText(1), "Track 2 - Microphone - your voice (from track name)")
        # A target that names no track keeps what is known.
        window.open_target(PlayTarget(path=recording), autoplay=False)
        self.assertEqual(window.track_combo.itemText(1), "Track 2 - Microphone - your voice (from track name)")

    def test_a_transcript_for_a_recording_that_is_no_longer_open_is_dropped(self) -> None:
        window = self._window()
        self._open(window, autoplay=False)
        stale = window._package_generation
        self._open(window, SESSION_TWO, autoplay=False)
        self.assertNotEqual(window._package_generation, stale)
        window._on_package_loaded(stale, _transcript(self.root))
        self.assertIsNone(window._transcript)
        window._on_package_failed(stale, "synthetic stale failure")
        self.assertEqual(self.diagnostics, [])

    def test_the_open_recording_opened_again_with_a_package_gets_its_transcript(self) -> None:
        recording = self.root / SESSION_ONE
        window = self._window()
        player = self._open(window, loaded=False, autoplay=False)
        player.report_loaded(titles=("Track1", "Microphone"))
        # Opened before any run: there is no package anywhere to ask.
        self.assertEqual(
            window.transcript_note.text(),
            "No transcript found for this recording. Run Find my bug reports on it to get one.",
        )
        first_lookup = window._package_generation

        # Find my bug reports has run since, and the recording is opened again
        # from the results, which name the package and the voice track.
        package = _write_package(self.root / "synthetic-run", recording)
        window.open_target(
            PlayTarget(path=recording, package_root=package, voice_track=2, start_seconds=2.0),
            autoplay=False,
        )

        # The recording itself is not reloaded...
        self.assertEqual(len(self.factory.players), 1)
        self.assertEqual(player.calls.count("setSource"), 1)
        self.assertEqual(player.set_positions, [2_000])
        # ...but what the new target says is kept, and looked up.
        self.assertEqual(window._target.package_root, package)
        self.assertEqual(window._target.voice_track, 2)
        self.assertEqual(window.track_combo.itemText(1), "Track 2 - Microphone - your voice")
        self.assertNotEqual(window._package_generation, first_lookup)
        self._wait_until(lambda: window._transcript is not None)
        self.assertEqual(window.transcript_header.text(), "Transcript from: synthetic-run")
        self.assertNotIn("No transcript found", window.transcript_note.text())
        player.move_to(2_000)
        self.assertEqual(window.current_line_label.text(), "synthetic package line")

        # The first lookup answers late ("nothing found"). It is not listened to.
        window._on_package_loaded(first_lookup, None)
        window._on_package_failed(first_lookup, "synthetic late failure")
        self.assertIsNotNone(window._transcript)
        self.assertEqual(window.transcript_header.text(), "Transcript from: synthetic-run")
        self.assertEqual(self.diagnostics, [])

        # A plain Play of it afterwards forgets nothing and looks nowhere.
        settled = window._package_generation
        window.open_target(PlayTarget(path=recording), autoplay=False)
        self.assertEqual(window._target.package_root, package)
        self.assertEqual(window._target.voice_track, 2)
        self.assertEqual(window._package_generation, settled)
        self.assertIsNotNone(window._transcript)
        self._wait_until(lambda: window._package_threads == set())

    def test_a_search_still_running_is_overtaken_by_the_one_that_names_the_package(self) -> None:
        recording = self.root / SESSION_ONE
        package = _write_package(self.root / "synthetic-run", recording)
        self.host.app_settings["recent_runs"] = [{"output": str(self.root / "synthetic-older-run")}]
        entered = threading.Event()

        def slow_find(recording, hints, *, duration_seconds=None, cancelled=lambda: False):
            entered.set()
            deadline = time.monotonic() + 10
            while not cancelled() and time.monotonic() < deadline:
                time.sleep(0.005)
            return None

        with patch.object(review_player, "find_package_for_recording", slow_find):
            window = self._window()
            self._open(window, autoplay=False)
            self.assertTrue(entered.wait(5))
            (first_thread,) = tuple(window._package_threads)
            self.assertEqual(window.transcript_note.text(), "Looking for a transcript…")

            # The same recording, now with its package named: the named
            # package is read straight away, and the slow search is cancelled.
            window.open_target(PlayTarget(path=recording, package_root=package), autoplay=False)
            self.assertTrue(first_thread.wait(5000))
            self._wait_until(lambda: window._package_threads == set())

        # Whichever of the two reported last, the transcript is what is shown:
        # the cancelled search's "nothing found" was for an older question.
        self.assertIsNotNone(window._transcript)
        self.assertEqual(window.transcript_header.text(), "Transcript from: synthetic-run")
        self.assertEqual(len(self.factory.players), 1)

    def test_opening_the_open_recording_again_does_not_restart_a_search_that_is_going(self) -> None:
        self.host.app_settings["recent_runs"] = [{"output": str(self.root / "synthetic-older-run")}]
        searches: list[str] = []
        release = threading.Event()

        def slow_find(recording, hints, *, duration_seconds=None, cancelled=lambda: False):
            searches.append(Path(recording).name)
            deadline = time.monotonic() + 10
            while not cancelled() and not release.is_set() and time.monotonic() < deadline:
                time.sleep(0.005)
            return None

        try:
            with patch.object(review_player, "find_package_for_recording", slow_find):
                window = self._window()
                self._open(window, autoplay=False)
                self._wait_until(lambda: searches == [SESSION_ONE])
                going = window._package_generation
                # Nothing new is said about it, so the search is left to finish.
                window.open_target(self._target(start_seconds=12.0), autoplay=False)
                self.assertEqual(window._package_generation, going)
                self.assertEqual(len(window._package_threads), 1)
                release.set()
                self._wait_until(lambda: window._package_threads == set())
                self.assertEqual(searches, [SESSION_ONE])
        finally:
            release.set()

    def test_a_failed_load_reads_as_no_transcript_and_keeps_the_details_off_screen(self) -> None:
        window = self._window()
        self._open(window, autoplay=False)
        private_detail = r"OSError: Q:\Captured Sessions\synthetic-run: access denied"
        window._on_package_failed(window._player_generation, private_detail)
        self.assertEqual(
            window.transcript_note.text(),
            "No transcript found for this recording. Run Find my bug reports on it to get one.",
        )
        self.assertNotIn("access denied", self._screen_text(window))
        self.assertIn(private_detail, self.diagnostics[-1])

    def test_package_hints_are_plain_text_newest_first_and_capped(self) -> None:
        window = self._window()
        self.host.current_package = SimpleNamespace(root=self.root / "open-run" / "codex-evidence-package")
        self.host.app_settings["last_evidence_package"] = str(self.root / "last-run")
        runs: list[object] = [{"output": str(self.root / f"run-{index:02d}")} for index in range(40)]
        runs[1] = {"output": str(self.root / "last-run")}  # a repeat
        runs[2] = {"output": None}
        runs[3] = "not a run"
        self.host.app_settings["recent_runs"] = runs

        target = self._target(package_root=self.root / "named-run")
        hints = window._package_hints(target)

        self.assertTrue(all(type(hint) is str for hint in hints))
        self.assertEqual(
            hints[:4],
            [
                str(self.root / "named-run"),
                str(self.root / "open-run" / "codex-evidence-package"),
                str(self.root / "last-run"),
                str(self.root / "run-00"),
            ],
        )
        self.assertEqual(len(hints), len(set(hints)))
        # Only the 30 newest runs are asked; three of those were unusable.
        self.assertEqual(hints[-1], str(self.root / "run-29"))
        self.assertNotIn(str(self.root / "run-30"), hints)

        self.host.app_settings["recent_runs"] = "corrupt"
        self.host.app_settings["last_evidence_package"] = 7
        self.assertEqual(
            window._package_hints(self._target()),
            [str(self.root / "open-run" / "codex-evidence-package")],
        )

    def test_a_real_package_is_found_and_shown_by_the_loader_thread(self) -> None:
        recording = self.root / SESSION_ONE
        _write_package(self.root / "synthetic-run", recording)
        self.host.app_settings["recent_runs"] = [{"output": str(self.root / "synthetic-run")}]
        window = self._window()
        player = self._open(window, loaded=False, autoplay=False)
        self.assertEqual(window._package_threads, set())

        # The search starts once the recording has loaded, so its length can
        # be checked against the package.
        player.report_loaded()
        self._wait_until(lambda: window._transcript is not None)
        self.assertEqual(window.transcript_header.text(), "Transcript from: synthetic-run")
        self.assertEqual(window.timeline._ticks, ((1.0, "kept", 1.0),))
        player.move_to(2_000)
        self.assertEqual(window.current_line_label.text(), "synthetic package line")
        self._wait_until(lambda: window._package_threads == set())


class ClosingTests(WindowTestCase):
    def test_closing_the_window_never_waits_for_the_loader_thread(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        def stuck_find(recording, hints, *, duration_seconds=None, cancelled=lambda: False):
            entered.set()
            # Deaf to cancel on purpose: a read from a disk that has gone away.
            release.wait(20)
            return None

        try:
            with patch.object(review_player, "find_package_for_recording", stuck_find):
                window = self._window()
                window.open_target(self._target(package_root=self.root / "synthetic-run"), autoplay=False)
                player = self.factory.players[-1]
                player.report_loaded()
                self.assertTrue(entered.wait(5))
                self.assertEqual(window.transcript_note.text(), "Looking for a transcript…")
                (thread,) = tuple(window._package_threads)

                started = time.monotonic()
                window.close()
                elapsed = time.monotonic() - started

                self.assertLess(elapsed, 2.0)
                self.assertTrue(thread.isRunning(), "close() must not wait for the thread")
                self.assertTrue(player.source().isEmpty())
                self.assertEqual(player.stop_calls, 0)

                # shutdown() is where the waiting happens, and it says so
                # when the thread will not stop in time.
                self.assertFalse(window.shutdown(50))
                self.assertIn(thread, review_player._PARKED_THREADS)
                release.set()
                self.assertTrue(window.shutdown(5000))
                self.assertFalse(thread.isRunning())
                self.assertNotIn(thread, review_player._PARKED_THREADS)
        finally:
            release.set()

    def test_shutdown_cancels_the_search_waits_for_it_and_reports_success(self) -> None:
        entered = threading.Event()
        cancelled_seen = threading.Event()

        def slow_find(recording, hints, *, duration_seconds=None, cancelled=lambda: False):
            entered.set()
            deadline = time.monotonic() + 20
            while not cancelled() and time.monotonic() < deadline:
                time.sleep(0.005)
            if cancelled():
                cancelled_seen.set()
            return None

        with patch.object(review_player, "find_package_for_recording", slow_find):
            window = self._window()
            window.open_target(self._target(package_root=self.root / "synthetic-run"), autoplay=False)
            player = self.factory.players[-1]
            player.report_loaded()
            self.assertTrue(entered.wait(5))
            (thread,) = tuple(window._package_threads)

            self.assertTrue(window.shutdown(5000))

        self.assertTrue(cancelled_seen.is_set())
        self.assertFalse(thread.isRunning())
        self.assertEqual(window._package_threads, set())
        self.assertTrue(player.source().isEmpty())

    def test_opening_another_recording_cancels_the_search_for_the_last_one(self) -> None:
        seen: list[str] = []
        release = threading.Event()

        def slow_find(recording, hints, *, duration_seconds=None, cancelled=lambda: False):
            seen.append(Path(recording).name)
            deadline = time.monotonic() + 10
            while not cancelled() and not release.is_set() and time.monotonic() < deadline:
                time.sleep(0.005)
            return None

        try:
            with patch.object(review_player, "find_package_for_recording", slow_find):
                window = self._window()
                window.open_target(self._target(package_root=self.root / "synthetic-run"), autoplay=False)
                self.factory.players[-1].report_loaded()
                self._wait_until(lambda: seen == [SESSION_ONE])
                (first_thread,) = tuple(window._package_threads)

                self._open(window, SESSION_TWO, autoplay=False)
                self.assertTrue(first_thread.wait(5000))
                self._wait_until(lambda: first_thread not in window._package_threads)
                # Its late "nothing found" is for a recording no longer open.
                self.assertEqual(
                    window.transcript_note.text(),
                    "No transcript found for this recording. Run Find my bug reports on it to get one.",
                )
        finally:
            release.set()


class UnplayableTests(WindowTestCase):
    def test_a_file_the_player_cannot_play_gets_a_card_with_two_ways_out(self) -> None:
        window = self._window()
        player = self._open(window, loaded=False, start_seconds=42.0)
        self.assertIs(window.video_stack.currentWidget(), window.video_surface)
        private_detail = r"Q:\Captured Sessions\synthetic-session-one.mkv: decode failed"
        player.fail(private_detail)

        self.assertIs(window.video_stack.currentWidget(), window.unplayable_card)
        self.assertEqual(window.unplayable_label.text(), "The built-in player can't play this file.")
        self.assertEqual(window.open_in_vlc_button.text(), "Open in VLC")
        self.assertEqual(window.open_in_default_button.text(), "Open in the default video app")
        self.assertFalse(window.play_button.isEnabled())
        self.assertEqual(player.play_calls, 0)
        # What went wrong can name a folder: log only, never the screen.
        self.assertNotIn("decode failed", self._screen_text(window))
        self.assertEqual(len(self.diagnostics), 1)
        self.assertIn(private_detail, self.diagnostics[0])

        window.open_in_vlc_button.click()
        window.open_in_default_button.click()
        self.assertEqual([choice for _target, choice in self.opener.opened], ["vlc", "system"])
        for target, _choice in self.opener.opened:
            self.assertEqual(target.path, self.root / SESSION_ONE)
            self.assertEqual(target.start_seconds, 42.0)
        # This player has just said it cannot play the file, so the opener is
        # told not to offer "play it here instead" when VLC is missing: that
        # would only lead back to this card.
        self.assertEqual(self.opener.fallbacks, [False, False])

        # A recording that does play brings the picture back.
        self._open(window, SESSION_TWO)
        self.assertIs(window.video_stack.currentWidget(), window.video_surface)
        self.assertTrue(window.play_button.isEnabled())

    def test_without_an_opener_the_ways_out_are_greyed(self) -> None:
        window = self._window()
        window._opener = None
        self._open(window, loaded=False).fail("synthetic failure")
        self.assertFalse(window.open_in_vlc_button.isEnabled())
        self.assertFalse(window.open_in_default_button.isEnabled())

    def test_opening_the_unplayable_recording_again_tries_again(self) -> None:
        window = self._window()
        self._open(window, loaded=False).fail("synthetic failure")
        self._open(window)
        self.assertEqual(len(self.factory.players), 2)
        self.assertIs(window.video_stack.currentWidget(), window.video_surface)


class NeverUseTests(WindowTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.page = FakePage(self.events)
        self.host.bug_reports_page = self.page
        self.requested: list[str] = []

    def _window(self, **overrides) -> ReviewPlayerWindow:
        window = super()._window(**overrides)
        window.never_use_requested.connect(self.requested.append)
        return window

    def test_playback_stops_before_the_list_is_written_and_the_next_one_opens(self) -> None:
        window = self._window()
        sequence = self._sequence(SESSION_ONE, SESSION_TWO, SESSION_THREE)
        player = self._open(window, sequence=sequence, autoplay=True)
        player.move_to(83_000)
        self.events.clear()

        window.never_use_button.click()

        # 1 pause, 2 write + save, 3 the page, 4 the next recording.
        self.assertEqual(self.events[:4], ["pause", "write", "save", "page"])
        self.assertEqual(excluded_paths(self.host.app_settings), [str(self.root / SESSION_ONE)])
        self.assertEqual(self.requested, [str(self.root / SESSION_ONE)])
        self.assertEqual(self.page.changes, 1)

        self.assertEqual(len(self.factory.players), 2)
        following = self.factory.players[-1]
        self.assertEqual(Path(following.source().toLocalFile()), self.root / SESSION_TWO)
        self.assertTrue(player.deleted)
        self.assertEqual(window.windowTitle(), f"{SESSION_TWO} — Built-in player")
        self.assertEqual(window.banner_label.text(), f'You marked "{SESSION_ONE}" never-use.')
        self.assertFalse(window.undo_banner.isHidden())
        self.assertFalse(window.undo_button.isHidden())
        # The list it came from goes with it, and knows which row is open now.
        self.assertEqual(window._sequence.targets, sequence.targets)
        self.assertEqual(window._sequence.opened_at, 1)
        self.assertEqual(window.never_use_button.text(), "Never use this recording")

        following.report_loaded()
        self.assertEqual(following.play_calls, 1)

    def test_the_next_recording_honours_the_autoplay_setting(self) -> None:
        self.host.app_settings["video_autoplay"] = False
        window = self._window()
        self._open(window, sequence=self._sequence(SESSION_ONE, SESSION_TWO), autoplay=True)
        window.never_use_current()
        following = self.factory.players[-1]
        following.report_loaded()
        self.assertEqual(following.play_calls, 0)
        self.assertEqual(following.pause_calls, 1)

    def test_a_failed_save_is_reported_and_does_not_advance(self) -> None:
        window = self._window()
        player = self._open(window, sequence=self._sequence(SESSION_ONE, SESSION_TWO), autoplay=True)
        self.host.fail_save = True
        self.events.clear()

        window.never_use_current()

        self.assertEqual(self.events, ["pause", "write", "save", "write"])
        self.assertIn("Could not save that — try again", window.banner_label.text())
        self.assertFalse(window.undo_banner.isHidden())
        self.assertTrue(window.undo_button.isHidden())
        # Not advanced, not claimed, and what is in memory matches the disk.
        self.assertEqual(len(self.factory.players), 1)
        self.assertFalse(player.deleted)
        self.assertEqual(player.play_calls, 1)
        self.assertEqual(window.windowTitle(), f"{SESSION_ONE} — Built-in player")
        self.assertEqual(excluded_paths(self.host.app_settings), [])
        self.assertEqual(self.requested, [])
        self.assertEqual(self.page.changes, 0)
        self.assertEqual(window.never_use_button.text(), "Never use this recording")

        # Trying again once the disk is back works, and the complaint goes.
        self.host.fail_save = False
        window.never_use_current()
        self.assertEqual(len(self.factory.players), 2)
        self.assertEqual(window.banner_label.text(), f'You marked "{SESSION_ONE}" never-use.')

    def test_a_recording_opened_on_its_own_has_nothing_next(self) -> None:
        window = self._window()
        player = self._open(window, autoplay=True)
        window.never_use_current()

        self.assertEqual(
            window.banner_label.text(),
            "Marked never-use. There is nothing next — this recording was opened on its own.",
        )
        self.assertEqual(len(self.factory.players), 1)
        self.assertEqual(player.pause_calls, 1)
        self.assertEqual(excluded_paths(self.host.app_settings), [str(self.root / SESSION_ONE)])
        self.assertEqual(window.never_use_button.text(), "Allow again")
        self.assertEqual(window.recording_status_label.text(), "On your never-use list")
        self.assertFalse(window.undo_button.isHidden())

    def test_the_last_recording_in_the_list_says_so_and_does_not_wrap(self) -> None:
        window = self._window()
        self._open(window, SESSION_TWO, sequence=self._sequence(SESSION_ONE, SESSION_TWO))
        window.never_use_current()
        self.assertEqual(
            window.banner_label.text(),
            "Marked never-use. That was the last recording in this list.",
        )
        self.assertEqual(len(self.factory.players), 1)

    def test_recordings_already_on_the_list_are_stepped_over(self) -> None:
        self.host.app_settings[EXCLUDED_KEY] = [str(self.root / SESSION_TWO).upper()]
        window = self._window()
        self._open(window, sequence=self._sequence(SESSION_ONE, SESSION_TWO, SESSION_THREE))
        window.never_use_current()
        self.assertEqual(
            Path(self.factory.players[-1].source().toLocalFile()), self.root / SESSION_THREE
        )

    def test_undo_allows_it_again_and_reopens_it_paused_where_it_was_stopped(self) -> None:
        window = self._window()
        sequence = self._sequence(SESSION_ONE, SESSION_TWO)
        player = self._open(window, sequence=sequence, autoplay=True)
        player.move_to(83_000)
        window.never_use_current()
        following = self.factory.players[-1]
        following.report_loaded()
        self.events.clear()

        window.undo_button.click()

        self.assertEqual(self.events[:4], ["pause", "write", "save", "page"])
        self.assertEqual(excluded_paths(self.host.app_settings), [])
        self.assertTrue(following.deleted)
        self.assertEqual(len(self.factory.players), 3)
        back = self.factory.players[-1]
        self.assertEqual(Path(back.source().toLocalFile()), self.root / SESSION_ONE)
        self.assertEqual(window.windowTitle(), f"{SESSION_ONE} — Built-in player")
        self.assertTrue(window.undo_banner.isHidden())
        # Back on the row it was opened from.
        self.assertEqual(window._sequence, sequence)

        back.report_loaded()
        self.assertEqual(back.calls, ["setSource", "pause", "setPosition:83000"])
        self.assertEqual(back.play_calls, 0)
        self.assertEqual(back.position(), 83_000)
        self.assertEqual(window.never_use_button.text(), "Never use this recording")

        # Nothing left to undo.
        window.undo_never_use()
        self.assertEqual(len(self.factory.players), 3)

    def test_undo_with_nothing_next_keeps_the_recording_that_is_already_open(self) -> None:
        window = self._window()
        player = self._open(window, autoplay=True)
        player.move_to(40_000)
        window.never_use_current()
        window.undo_never_use()

        self.assertEqual(len(self.factory.players), 1)
        self.assertEqual(excluded_paths(self.host.app_settings), [])
        self.assertEqual(player.set_positions, [40_000])
        self.assertEqual(player.play_calls, 1)
        self.assertEqual(window.never_use_button.text(), "Never use this recording")

    def test_an_undo_that_cannot_be_saved_changes_nothing_and_can_be_tried_again(self) -> None:
        window = self._window()
        self._open(window, sequence=self._sequence(SESSION_ONE, SESSION_TWO))
        window.never_use_current()
        self.host.fail_save = True
        window.undo_never_use()

        self.assertIn("Could not save that — try again", window.banner_label.text())
        self.assertFalse(window.undo_button.isHidden())
        self.assertEqual(excluded_paths(self.host.app_settings), [str(self.root / SESSION_ONE)])
        self.assertEqual(len(self.factory.players), 2)

        self.host.fail_save = False
        window.undo_never_use()
        self.assertEqual(excluded_paths(self.host.app_settings), [])
        self.assertEqual(len(self.factory.players), 3)

    def test_allow_again_takes_the_open_recording_off_the_list(self) -> None:
        self.host.app_settings[EXCLUDED_KEY] = [str(self.root / SESSION_ONE)]
        window = self._window()
        self._open(window)
        self.assertEqual(window.never_use_button.text(), "Allow again")

        window.never_use_button.click()
        self.assertEqual(excluded_paths(self.host.app_settings), [])
        self.assertEqual(self.page.changes, 1)
        self.assertEqual(self.host.save_calls, 1)
        self.assertEqual(window.never_use_button.text(), "Never use this recording")
        self.assertEqual(len(self.factory.players), 1)

    def test_the_status_is_the_one_find_my_bug_reports_shows(self) -> None:
        window = self._window()
        self.assertEqual(window.recording_status_label.text(), "No recording is open.")
        self.assertFalse(window.never_use_button.isEnabled())

        self._open(window)
        self.assertEqual(window.recording_status_label.text(), "Ready")
        self.host.app_settings[PROCESSED_KEY] = {str(self.root / SESSION_ONE): "2026-09-20"}
        window.refresh_recording_row()
        self.assertEqual(window.recording_status_label.text(), "Done on 2026-09-20")

    def test_a_page_without_the_new_method_is_not_a_problem(self) -> None:
        self.host.bug_reports_page = SimpleNamespace()
        window = self._window()
        self._open(window)
        window.never_use_current()
        self.assertEqual(excluded_paths(self.host.app_settings), [str(self.root / SESSION_ONE)])

    def test_a_failed_save_on_a_second_never_use_keeps_the_undo_for_the_first(self) -> None:
        window = self._window()
        self._open(window, sequence=self._sequence(SESSION_ONE, SESSION_TWO, SESSION_THREE))
        window.never_use_current()
        first_banner = f'You marked "{SESSION_ONE}" never-use.'
        self.assertEqual(window.banner_label.text(), first_banner)
        second = self.factory.players[-1]
        second.report_loaded()

        self.host.fail_save = True
        window.never_use_current()

        # The second recording was not marked and nothing moved on...
        self.assertEqual(excluded_paths(self.host.app_settings), [str(self.root / SESSION_ONE)])
        self.assertEqual(len(self.factory.players), 2)
        self.assertEqual(window.windowTitle(), f"{SESSION_TWO} — Built-in player")
        self.assertEqual(window.status_label.text(), "Could not save that — try again")
        self.assertEqual(window.status_label.property("operatorState"), "error")
        # ...and the first mark, which DID reach the disk, can still be undone.
        self.assertEqual(window.banner_label.text(), first_banner)
        self.assertFalse(window.undo_banner.isHidden())
        self.assertFalse(window.undo_button.isHidden())

        self.host.fail_save = False
        window.undo_button.click()
        self.assertEqual(excluded_paths(self.host.app_settings), [])
        self.assertEqual(window.windowTitle(), f"{SESSION_ONE} — Built-in player")

    def test_a_failed_allow_again_keeps_the_undo_for_an_earlier_never_use(self) -> None:
        self.host.app_settings[EXCLUDED_KEY] = [str(self.root / SESSION_TWO)]
        window = self._window()
        self._open(window, sequence=self._sequence(SESSION_ONE, SESSION_THREE))
        window.never_use_current()
        self._open(window, SESSION_TWO)
        self.assertEqual(window.never_use_button.text(), "Allow again")

        self.host.fail_save = True
        window.never_use_button.click()

        self.assertEqual(window.status_label.text(), "Could not save that — try again")
        self.assertEqual(window.banner_label.text(), f'You marked "{SESSION_ONE}" never-use.')
        self.assertFalse(window.undo_button.isHidden())
        self.assertEqual(
            sorted(excluded_paths(self.host.app_settings)),
            sorted([str(self.root / SESSION_ONE), str(self.root / SESSION_TWO)]),
        )

    def test_an_undo_covered_by_a_complaint_comes_back_with_the_next_recording(self) -> None:
        window = self._window()
        self._open(window, sequence=self._sequence(SESSION_ONE, SESSION_TWO))
        window.never_use_current()
        self.host.fail_save = True
        window.undo_never_use()
        self.assertIn("Could not save that — try again", window.banner_label.text())

        # Opening something else takes the complaint away, not the Undo.
        self.host.fail_save = False
        self._open(window, SESSION_THREE)
        self.assertEqual(window.banner_label.text(), f'You marked "{SESSION_ONE}" never-use.')
        self.assertFalse(window.undo_button.isHidden())
        window.undo_never_use()
        self.assertEqual(excluded_paths(self.host.app_settings), [])

    def test_next_carries_on_from_the_row_that_was_opened(self) -> None:
        # History has a row per run, so one recording can be on several rows.
        # Opened from the third row, "next" is the fourth - never the second.
        window = self._window()
        rows = self._sequence(SESSION_ONE, SESSION_TWO, SESSION_ONE, SESSION_THREE)
        opened_from_row_three = PlaySequence(rows.targets, rows.label, opened_at=2)
        self._open(window, sequence=opened_from_row_three)
        self.assertEqual(window._sequence.opened_at, 2)

        window.never_use_current()

        following = self.factory.players[-1]
        self.assertEqual(Path(following.source().toLocalFile()), self.root / SESSION_THREE)
        self.assertEqual(window._sequence.opened_at, 3)
        self.assertEqual(window._sequence.targets, rows.targets)

        # Undo goes back to the row it was opened from, not to the first row
        # that shows the same recording.
        window.undo_never_use()
        self.assertEqual(window._sequence.opened_at, 2)
        window.never_use_current()
        self.assertEqual(
            Path(self.factory.players[-1].source().toLocalFile()), self.root / SESSION_THREE
        )

    def test_a_list_opened_without_a_row_finds_the_recording_by_its_path(self) -> None:
        window = self._window()
        self._open(window, SESSION_TWO, sequence=self._sequence(SESSION_ONE, SESSION_TWO, SESSION_THREE))
        self.assertEqual(window._sequence.opened_at, 1)
        # A moment of the open recording, handed over with the same list.
        window.open_target(
            self._target(SESSION_TWO, start_seconds=30.0),
            sequence=self._sequence(SESSION_ONE, SESSION_TWO, SESSION_THREE),
            autoplay=False,
        )
        self.assertEqual(window._sequence.opened_at, 1)

    def test_the_list_holds_the_path_the_way_find_my_bug_reports_spells_it(self) -> None:
        # A view can spell a recording through a mapped drive or a linked
        # folder. Find my bug reports only ever compares resolved paths.
        as_spelled = Path("Q:/Captured Sessions") / SESSION_ONE
        resolved = Path("//synthetic-server/captures") / SESSION_ONE
        asked: list[Path] = []

        def resolver(path: Path) -> Path:
            asked.append(path)
            return resolved if path == as_spelled else path

        window = self._window(path_resolver=resolver)
        window.open_target(PlayTarget(path=as_spelled))
        self.factory.players[-1].report_loaded()

        window.never_use_current()
        self.assertEqual(excluded_paths(self.host.app_settings), [str(resolved)])
        self.assertEqual(self.requested, [str(resolved)])
        # This window knows it as the same recording under either spelling.
        self.assertEqual(window.never_use_button.text(), "Allow again")
        self.assertEqual(window.recording_status_label.text(), "On your never-use list")
        # The disk is asked once per recording, not at every refresh.
        window.refresh_recording_row()
        self.assertEqual(asked, [as_spelled])

        window.undo_never_use()
        self.assertEqual(excluded_paths(self.host.app_settings), [])

        # An entry made under the view's spelling (by an older build) still
        # counts, and Allow again clears every spelling.
        self.host.app_settings[EXCLUDED_KEY] = [str(as_spelled), str(resolved)]
        window.refresh_recording_row()
        self.assertEqual(window.never_use_button.text(), "Allow again")
        window.never_use_button.click()
        self.assertEqual(excluded_paths(self.host.app_settings), [])

        # "Done on" is kept under the resolved spelling too.
        self.host.app_settings[PROCESSED_KEY] = {str(resolved): "2026-09-20"}
        window.refresh_recording_row()
        self.assertEqual(window.recording_status_label.text(), "Done on 2026-09-20")

    def test_a_path_that_cannot_be_resolved_is_stored_as_it_was_given(self) -> None:
        self.assertEqual(
            review_player._resolved_text(Path("Q:/Captured Sessions") / SESSION_ONE, lambda path: path / "deeper"),
            str(Path("Q:/Captured Sessions") / SESSION_ONE / "deeper"),
        )
        for problem in (OSError("synthetic drive gone"), RuntimeError("synthetic link loop"), ValueError("nul")):
            with self.subTest(problem=type(problem).__name__):

                def broken(_path: Path, problem=problem) -> Path:
                    raise problem

                self.assertEqual(
                    review_player._resolved_text(Path("Q:/Captured Sessions") / SESSION_ONE, broken),
                    str(Path("Q:/Captured Sessions") / SESSION_ONE),
                )

        def gone(_path: Path) -> Path:
            raise OSError("synthetic drive gone")

        window = self._window(path_resolver=gone)
        self._open(window)
        window.never_use_current()
        self.assertEqual(excluded_paths(self.host.app_settings), [str(self.root / SESSION_ONE)])


class PackageFileTests(WindowTestCase):
    """A clip or a small copy from a package is not one of the operator's recordings."""

    def setUp(self) -> None:
        super().setUp()
        self.page = FakePage(self.events)
        self.host.bug_reports_page = self.page
        self.package = self.root / "synthetic-run" / "codex-evidence-package"
        self.clip = self.package / "clips" / "synthetic-moment-clip.mp4"
        self.review_copy = self.package / "review" / "review_video_synthetic-session-one-0123456789.mp4"

    def test_a_clip_cannot_be_marked_never_use_or_skipped_and_has_no_transcript(self) -> None:
        searches: list[str] = []

        def recording_find(recording, hints, *, duration_seconds=None, cancelled=lambda: False):
            searches.append(Path(recording).name)
            return None

        self.host.runner_thread = object()
        self.host.skip_run_sources = lambda sources: list(sources)
        self.host.app_settings["recent_runs"] = [{"output": str(self.root / "synthetic-run")}]
        window = self._window()
        with patch.object(review_player, "find_package_for_recording", recording_find):
            window.open_target(
                PlayTarget(path=self.clip, package_root=self.package),
                sequence=PlaySequence((PlayTarget(path=self.clip), self._target(SESSION_TWO))),
            )
            player = self.factory.players[-1]
            player.report_loaded()

            self.assertFalse(window.never_use_button.isEnabled())
            self.assertEqual(window.never_use_button.text(), "Never use this recording")
            self.assertEqual(
                window.never_use_button.toolTip(),
                "This is a clip or a small copy made for a package, not one of your recordings, "
                "so it cannot be marked never-use.",
            )
            self.assertEqual(window.recording_status_label.text(), "A clip or a small copy from a package")
            # A run is going and the host can skip, and Skip is still not offered.
            self.assertTrue(window.skip_button.isHidden())

            # No package is asked about a clip, and the advice to run Find my
            # bug reports on it is not given.
            self.assertEqual(window._package_threads, set())
            self.assertEqual(
                window.transcript_note.text(),
                "This is a clip or a small copy from a package, so there is no transcript to show for it.",
            )
            self.assertNotIn("Run Find my bug reports", self._screen_text(window))

            # Even asked directly, nothing is written and nothing moves on.
            window.never_use_current()
            window.never_use_button.click()
            window.allow_current_again()
            window.skip_current()
            self.assertEqual(excluded_paths(self.host.app_settings), [])
            self.assertEqual(self.host.save_calls, 0)
            self.assertEqual(self.page.changes, 0)
            self.assertEqual(len(self.factory.players), 1)
            self.assertEqual(player.pause_calls, 0)
            self.assertTrue(window.undo_banner.isHidden())

            # The same clip opened again, and let go of, still looks nowhere.
            window.open_target(PlayTarget(path=self.clip, package_root=self.package, start_seconds=1.0))
            window.release_media()
            self.assertEqual(
                window.transcript_note.text(),
                "This is a clip or a small copy from a package, so there is no transcript to show for it.",
            )
        self.assertEqual(searches, [])
        self.assertEqual(window._package_threads, set())

        # One of the operator's recordings after it gets its buttons back.
        self._open(window, SESSION_TWO)
        self.assertTrue(window.never_use_button.isEnabled())
        self.assertNotIn("clip", window.never_use_button.toolTip())
        self.assertFalse(window.skip_button.isHidden())

    def test_a_small_copy_standing_in_marks_the_recording_not_the_copy(self) -> None:
        recording = self.root / SESSION_ONE
        skipped: list[list[str]] = []
        self.host.runner_thread = object()
        self.host.skip_run_sources = lambda sources: skipped.append(list(sources)) or list(sources)
        self.host.app_settings[PROCESSED_KEY] = {str(recording): "2026-09-20"}
        requested: list[str] = []
        window = self._window()
        window.never_use_requested.connect(requested.append)
        sequence = self._sequence(SESSION_ONE, SESSION_TWO)

        window.open_target(
            PlayTarget(path=self.review_copy, package_root=self.package, stands_in_for=recording),
            sequence=sequence,
        )
        player = self.factory.players[-1]
        # The copy is what is played...
        self.assertEqual(Path(player.source().toLocalFile()), self.review_copy)
        player.report_loaded()
        # ...and everything else is about the recording it stands in for.
        self.assertEqual(window.windowTitle(), f"{SESSION_ONE} — Built-in player")
        self.assertEqual(window.status_label.text(), f"Playing the small review copy of {SESSION_ONE}.")
        self.assertEqual(window.recording_status_label.text(), "Done on 2026-09-20")
        self.assertTrue(window.never_use_button.isEnabled())
        self.assertFalse(window.skip_button.isHidden())

        window.skip_button.click()
        self.assertEqual(skipped, [[str(recording)]])
        self.assertFalse(window.skip_button.isEnabled())

        window.never_use_button.click()
        self.assertEqual(excluded_paths(self.host.app_settings), [str(recording)])
        self.assertEqual(requested, [str(recording)])
        self.assertEqual(window.banner_label.text(), f'You marked "{SESSION_ONE}" never-use.')
        # Found in the list by the recording, so the next one opens.
        self.assertEqual(
            Path(self.factory.players[-1].source().toLocalFile()), self.root / SESSION_TWO
        )

        # Undo brings the copy back, still standing in for the recording.
        window.undo_never_use()
        self.assertEqual(excluded_paths(self.host.app_settings), [])
        self.assertEqual(Path(self.factory.players[-1].source().toLocalFile()), self.review_copy)
        self.assertEqual(window._target.stands_in_for, recording)

    def test_the_transcript_of_a_stand_in_is_looked_up_for_the_recording(self) -> None:
        recording = self.root / SESSION_ONE
        package = _write_package(self.root / "synthetic-run", recording)
        made: list[tuple[Path, float | None]] = []
        real_thread = review_player.PackageLoadThread

        def recording_thread(generation, looked_for, package_root, hints, duration_seconds):
            made.append((Path(looked_for), duration_seconds))
            return real_thread(generation, looked_for, package_root, hints, duration_seconds)

        window = self._window()
        with patch.object(review_player, "PackageLoadThread", recording_thread):
            window.open_target(
                PlayTarget(path=self.review_copy, package_root=package, stands_in_for=recording),
                autoplay=False,
            )
            self.factory.players[-1].report_loaded()
        # Matched by the recording's path, and without the copy's length: a
        # small copy need not be exactly as long as the recording.
        self.assertEqual(made, [(recording, None)])
        self._wait_until(lambda: window._transcript is not None)
        self.assertEqual(window.transcript_header.text(), "Transcript from: synthetic-run")
        self._wait_until(lambda: window._package_threads == set())

    def test_a_note_and_the_stand_in_sentence_are_both_said_but_never_twice(self) -> None:
        recording = self.root / SESSION_ONE
        target = PlayTarget(path=self.review_copy, stands_in_for=recording)
        window = self._window()
        window.open_target(target, note="Synthetic note.")
        self.factory.players[-1].report_loaded()
        self.assertEqual(
            window.status_label.text(),
            f"Synthetic note. Playing the small review copy of {SESSION_ONE}.",
        )
        already = f"Playing the small review copy of {SESSION_ONE}."
        window.open_target(target, note=already)
        self.assertEqual(window.status_label.text(), already)

    def test_the_missing_recording_is_not_asked_of_the_disk_until_a_button_is_pressed(self) -> None:
        recording = Path("Q:/Captured Sessions") / SESSION_ONE
        asked: list[Path] = []

        def resolver(path: Path) -> Path:
            asked.append(path)
            return path

        window = self._window(path_resolver=resolver)
        window.open_target(PlayTarget(path=self.review_copy, stands_in_for=recording))
        self.factory.players[-1].report_loaded()
        window.refresh_recording_row()
        # The recording a copy stands in for is missing; asking the disk about
        # it can take as long as a drive takes to give up.
        self.assertEqual(asked, [])
        window.never_use_current()
        self.assertEqual(asked, [recording])
        self.assertEqual(excluded_paths(self.host.app_settings), [str(recording)])


class SkipTests(WindowTestCase):
    def test_skip_is_only_offered_while_a_run_is_going(self) -> None:
        window = self._window()
        self._open(window)
        self.assertTrue(window.skip_button.isHidden())

        # A run, but a host that cannot skip.
        self.host.runner_thread = object()
        window.refresh_recording_row()
        self.assertTrue(window.skip_button.isHidden())

        # A host that can skip, but no run.
        self.host.runner_thread = None
        self.host.skip_run_sources = lambda sources: list(sources)
        window.refresh_recording_row()
        self.assertTrue(window.skip_button.isHidden())

        self.host.runner_thread = object()
        window.refresh_recording_row()
        self.assertFalse(window.skip_button.isHidden())
        self.assertEqual(
            window.skip_button.toolTip(),
            "Skips it in the run that is going now. This cannot be taken back for this run.",
        )

        self.host.runner_thread = None
        window.refresh_recording_row()
        self.assertTrue(window.skip_button.isHidden())

    def test_skip_asks_the_host_once_and_cannot_be_pressed_twice(self) -> None:
        asked: list[list[str]] = []

        def skip(sources: list[str]) -> list[str]:
            asked.append(list(sources))
            return list(sources)

        self.host.runner_thread = object()
        self.host.skip_run_sources = skip
        window = self._window()
        player = self._open(window)

        window.skip_button.click()
        self.assertEqual(asked, [[str(self.root / SESSION_ONE)]])
        self.assertFalse(window.skip_button.isEnabled())
        self.assertEqual(
            window.status_label.text(), "This recording will be skipped in the run that is going now."
        )
        # Skipping is about the run; the recording stays open and playing.
        self.assertEqual(len(self.factory.players), 1)
        self.assertEqual(player.pause_calls, 0)
        self.assertEqual(excluded_paths(self.host.app_settings), [])

        # Another recording in the same run can still be skipped.
        self._open(window, SESSION_TWO)
        self.assertTrue(window.skip_button.isEnabled())

    def test_a_recording_the_run_does_not_know_is_said_plainly(self) -> None:
        self.host.runner_thread = object()
        self.host.skip_run_sources = lambda sources: []
        window = self._window()
        self._open(window)
        window.skip_current()
        self.assertEqual(
            window.status_label.text(), "This recording is not waiting in the run that is going now."
        )
        self.assertTrue(window.skip_button.isEnabled())

    def test_a_run_that_ended_meanwhile_is_not_asked(self) -> None:
        asked: list[list[str]] = []
        self.host.runner_thread = object()
        self.host.skip_run_sources = asked.append
        window = self._window()
        self._open(window)
        self.host.runner_thread = None
        window.skip_current()
        self.assertEqual(asked, [])
        self.assertTrue(window.skip_button.isHidden())


class RealPlayerTests(QtTestCase):
    """One pass with the real player and a real file, silent and off screen."""

    # If the real player ever hangs, end the test run with a traceback rather
    # than leave it stuck for good.
    WATCHDOG_SECONDS = 120

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window: ReviewPlayerWindow | None = None

    def tearDown(self) -> None:
        faulthandler.cancel_dump_traceback_later()
        if self.window is not None:
            self.window.close()
            self.assertTrue(self.window.shutdown(5000))
            self.window.deleteLater()
        self._flush_deleted()
        self.window = None
        self.temp.cleanup()

    def _wait(self, predicate, timeout: float = 10.0) -> None:
        # A real event loop: the real player makes no progress without one.
        if predicate():
            return
        loop = QEventLoop()
        poll = QTimer()
        poll.setInterval(10)
        poll.timeout.connect(lambda: loop.quit() if predicate() else None)
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        poll.start()
        deadline.start(int(timeout * 1000))
        loop.exec()
        poll.stop()
        deadline.stop()
        self.assertTrue(predicate())

    def _synthesise(self, ffmpeg: str, destination: Path) -> None:
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=160x120:rate=25:duration=4",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
            "-f", "lavfi", "-i", "sine=frequency=880:duration=4",
            "-map", "0:v", "-map", "1:a", "-map", "2:a",
            "-c:v", "mpeg4", "-c:a", "aac",
            "-metadata:s:a:0", "title=Track1",
            "-metadata:s:a:1", "title=Microphone",
            str(destination),
        ]  # fmt: skip
        try:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=120,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.skipTest(f"ffmpeg could not be run: {type(exc).__name__}")
        if result.returncode != 0 or not destination.is_file():
            self.skipTest("ffmpeg could not make the synthetic two-track recording.")

    def test_a_two_track_recording_opens_at_its_moment_and_plays_in_silence(self) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            self.skipTest("ffmpeg is not on PATH.")
        if QMediaDevices.defaultAudioOutput().isNull():
            self.skipTest("Qt reported no default audio output device.")
        first = self.root / "synthetic-two-track-one.mkv"
        second = self.root / "synthetic-two-track-two.mkv"
        self._synthesise(ffmpeg, first)
        shutil.copyfile(first, second)
        try:
            # The real stderr: the one pytest swaps in may have no file handle.
            faulthandler.dump_traceback_later(self.WATCHDOG_SECONDS, exit=True, file=sys.__stderr__)
        except (AttributeError, OSError, ValueError):
            pass  # nowhere to write to; carry on without the safety net

        host = SimpleNamespace(app_settings={}, save_app_settings=lambda: None)
        window = self.window = ReviewPlayerWindow(host, None)
        # Silent from before the first sound could be made.
        window.audio_output.setMuted(True)
        window.open_target(PlayTarget(path=first, start_seconds=2.0, voice_track=2), autoplay=False)
        self._wait(lambda: window._media_ready)
        player = window._player

        self.assertEqual(len(player.audioTracks()), 2)
        self.assertEqual(
            [window.track_combo.itemText(index) for index in range(window.track_combo.count())],
            ["Track 1", "Track 2 - Microphone - your voice"],
        )
        # The start was applied once loaded, the seek was released by a real
        # frame, and the recording opened paused.
        self._wait(lambda: window._coalescer.requested_ms() is None, 3.0)
        self.assertEqual(player.position(), 2_000)
        self.assertEqual(player.playbackState(), QMediaPlayer.PlaybackState.PausedState)
        self.assertEqual(window.time_label.text(), "0:00:02 / 0:00:04")

        shown = window._last_frame_ms
        window.step_forward_action.trigger()
        self._wait(lambda: not window._step_pending, 3.0)
        self.assertGreater(window._last_frame_ms, shown)
        self.assertLessEqual(window._last_frame_ms - shown, 130)
        self.assertEqual(player.playbackState(), QMediaPlayer.PlaybackState.PausedState)
        self.assertTrue(window.audio_output.isMuted())

        started_at = player.position()
        window.play_action.trigger()
        self._wait(lambda: player.position() > started_at + 300)
        self.assertTrue(window.audio_output.isMuted())

        # Straight from a track change into another recording: the sequence
        # that froze the real player while it was still being told to stop().
        window.track_combo.setCurrentIndex(1)
        self.assertEqual(player.activeAudioTrack(), 1)
        window.open_target(PlayTarget(path=second), autoplay=True)
        self._wait(lambda: window._media_ready)
        self.assertIsNot(window._player, player)
        self._wait(lambda: window._player.position() > 200)

        self.assertTrue(window.shutdown(5000))
        self.assertIsNone(window._player)
        # Both files were let go of: Windows refuses to delete an open one.
        self._flush_deleted()
        first.unlink()
        second.unlink()


if __name__ == "__main__":
    unittest.main()
