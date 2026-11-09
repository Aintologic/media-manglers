from __future__ import annotations

import ast
import gc
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QThread, QUrl  # noqa: E402
from PySide6.QtMultimedia import QMediaPlayer  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from media_manglers_workbench import play_targets, video_open  # noqa: E402
from media_manglers_workbench.review_player import ReviewPlayerWindow  # noqa: E402
from media_manglers_workbench.video_open import (  # noqa: E402
    LocateResult,
    LocateThread,
    PlaySequence,
    PlayTarget,
    VideoOpener,
    VideoPlayerSettingsPanel,
    locate_recording,
    next_target,
    path_role_resolver,
)
from media_manglers_workbench.widgets import WheelSafeComboBox  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
OPENER_SOURCE = REPO_ROOT / "src" / "media_manglers_workbench" / "video_open.py"

# Invented places and names. Nothing here is ever looked for on a disk: every
# opener in this file is given a stand-in for "does this exist".
CAPTURES = Path(r"Q:\Captured Sessions")
SESSION_ONE = CAPTURES / "synthetic-session-one.mkv"
SESSION_TWO = CAPTURES / "synthetic-session-two.mkv"
SESSION_THREE = CAPTURES / "synthetic-session-three.mkv"
MOVED_ONE = Path(r"Q:\Moved Sessions") / "synthetic-session-one.mkv"
PACKAGE = Path(r"Q:\Reviews\synthetic-run\codex-evidence-package")
REVIEW_COPY = PACKAGE / "narration" / "review_video_synthetic-session-one.mp4"
SYNTHETIC_VLC = r"Q:\Synthetic Programs\VideoLAN\VLC\vlc.exe"

# Words the contract keeps off the screen: they describe how the player is
# built, not what the operator sees.
BANNED_WORDS = ("envelope", "backend", "libvlc", "qmediaplayer", "coalesce")

COMBO_TEXTS = [
    "Built-in player — transcript lines, choose which track you hear",
    "VLC — plays the video only",
    "Your computer's default video app — plays the video only",
]
NOTES = {
    # 125 Part 2 (Wave 8): the waveforms and the moments joined what only the built-in player has.
    "internal": (
        "The video opens inside the Workbench. You can read what the transcriber wrote at the moment "
        "you are hearing it, including lines it left out and why, choose which audio track you hear, "
        "see every track's waveform, jump between the sounds on the track you hear and between the "
        "moments a package found, and mark a recording as never-use."
    ),
    "vlc": (
        "The video opens in VLC. Transcript lines, track choice, waveforms, jumping between sounds, "
        "moments and never-use marking are only in the built-in player. Playing a moment still starts "
        "VLC at the right time."
    ),
    "system": (
        "The video opens in whatever app your computer normally uses for videos. Transcript lines, "
        "track choice, waveforms, jumping between sounds, moments and never-use marking are only in "
        "the built-in player. This choice always starts at the beginning, and that app decides whether "
        "it starts playing."
    ),
}
VLC_FOUND = "VLC found."
VLC_NOT_FOUND = (
    "VLC was not found on this computer. Videos open in the built-in player until you install VLC "
    "or press Find VLC."
)
# What the built-in player says when it opened a video because VLC, the usual
# choice, is not on this computer. It is what makes the sentence above true.
VLC_FALLBACK_NOTE = (
    "VLC was not found, so this opened in the built-in player. To use VLC, go to "
    "Settings > Video player and press Find VLC…"
)
PLAY_FROM_START = "Play from the start (your default video app can't jump to a moment)"
OPEN_MOMENT_INTERNAL = "Open this moment in the built-in player"
PLAY_WITH_ENTRIES = ["Built-in player", "VLC", "Default video app"]


class _Signal:
    """Minimal signal: the opener only ever connects to it."""

    def __init__(self) -> None:
        self.slots: list = []

    def connect(self, slot) -> None:
        self.slots.append(slot)

    def emit(self, *args) -> None:
        for slot in list(self.slots):
            slot(*args)


class FakeWindow:
    """Stands in for the built-in player window and notes what it is told."""

    def __init__(self, host, opener) -> None:
        self.host = host
        self.opener = opener
        self.opened: list[tuple[PlayTarget, PlaySequence | None, bool]] = []
        # One per video opened: what the status line was to say, "" for nothing.
        self.notes: list[str] = []
        self.said: list[str] = []
        self.calls: list[str] = []
        self.threads_stop = True
        self.diagnostic = _Signal()

    def open_target(self, target, *, sequence=None, autoplay=True, note="") -> None:
        self.opened.append((target, sequence, autoplay))
        self.notes.append(note)

    def show_note(self, text) -> None:
        self.said.append(text)

    def release_media(self) -> None:
        self.calls.append("release_media")

    def yield_audio(self) -> None:
        self.calls.append("yield_audio")

    def shutdown(self, wait_ms: int = 5000) -> bool:
        self.calls.append(f"shutdown:{wait_ms}")
        return self.threads_stop

    def close(self) -> bool:
        self.calls.append("close")
        return True

    def deleteLater(self) -> None:  # noqa: N802
        self.calls.append("deleteLater")


class WindowFactory:
    def __init__(self) -> None:
        self.windows: list[FakeWindow] = []

    def __call__(self, host, opener) -> FakeWindow:
        window = FakeWindow(host, opener)
        self.windows.append(window)
        return window


class FakeHost:
    """The duck-typed host: only what the opener may use."""

    def __init__(self, **settings) -> None:
        self.app_settings: dict = dict(settings)
        self.audio_player = None
        self.saves = 0
        self.save_error: OSError | None = None
        self.log: list[str] = []

    def save_app_settings(self) -> None:
        self.saves += 1
        if self.save_error is not None:
            raise self.save_error

    def _write_workbench_log(self, message: str) -> None:
        self.log.append(message)


class Launcher:
    """Stands in for subprocess.Popen: nothing is ever started."""

    def __init__(self, error: OSError | None = None) -> None:
        self.error = error
        self.started: list[tuple[list[str], dict]] = []

    def __call__(self, command, **options):
        self.started.append((list(command), options))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(pid=0)

    @property
    def commands(self) -> list[list[str]]:
        return [command for command, _options in self.started]


class Desktop:
    """Stands in for the computer's own "open this" and notes what it was given."""

    def __init__(self, opens: bool = True) -> None:
        self.opens = opens
        self.opened: list[Path] = []

    def __call__(self, path) -> bool:
        self.opened.append(Path(path))
        return self.opens


class Disk:
    """What exists, by exact text. Notes every question it was asked."""

    def __init__(self, *present) -> None:
        self.present = {str(item) for item in present}
        self.asked: list[str] = []

    def __call__(self, path) -> bool:
        self.asked.append(str(path))
        return str(path) in self.present


class Operator:
    """Answers the opener's messages from a script, so no box is ever shown."""

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.asked: list[tuple[str, str, tuple[str, ...]]] = []

    def __call__(self, title, text, choices=()) -> str:
        self.asked.append((title, text, tuple(choices)))
        return self.answers.pop(0) if self.answers else ""


def _opener_answering_at_once(host, **options) -> VideoOpener:
    """An opener whose questions to the disk are answered on the spot.

    The real one asks on a thread and carries on when the answer comes back
    through the event loop. Here the same questions go to the same stand-in
    disk on the calling thread, so a test still reads from top to bottom.
    """

    made: list[VideoOpener] = []

    def at_once(target, on_result) -> None:
        on_result(made[0].locate_now(target))

    made.append(VideoOpener(host, locate_runner=at_once, **options))
    return made[0]


class HeldAnswers:
    """A locate runner that keeps every question until the test answers it."""

    def __init__(self) -> None:
        self.asked: list[tuple[PlayTarget, object]] = []

    def __call__(self, target, on_result) -> None:
        self.asked.append((target, on_result))


class FakeLocateThread:
    """Stands in for LocateThread: never starts anything, answers when told to."""

    instances: list["FakeLocateThread"] = []

    def __init__(self, generation, target, moved, exists) -> None:
        self.generation = generation
        self.target = target
        self.moved = moved
        self.exists = exists
        self.located = _Signal()
        self.failed = _Signal()
        self.finished = _Signal()
        self.started = False
        self.done = False
        self.cancel_calls = 0
        self.waits: list[int] = []
        self.deleted = False
        FakeLocateThread.instances.append(self)

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancel_calls += 1

    def isRunning(self) -> bool:  # noqa: N802
        return self.started and not self.done

    def isFinished(self) -> bool:  # noqa: N802
        return self.done

    def wait(self, milliseconds: int) -> bool:
        self.waits.append(milliseconds)
        return self.done

    def deleteLater(self) -> None:  # noqa: N802
        self.deleted = True

    def finish(self) -> None:
        self.done = True
        self.finished.emit()


class FakePreviewPlayer:
    def __init__(self, state) -> None:
        self._state = state
        self.pause_calls = 0

    def playbackState(self):  # noqa: N802
        return self._state

    def pause(self) -> None:
        self.pause_calls += 1


def _texts(menu: QMenu) -> list[str]:
    return ["---" if action.isSeparator() else action.text() for action in menu.actions()]


def _entry(menu: QMenu, text: str):
    return next(action for action in menu.actions() if action.text() == text)


class QtTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _flush_deleted(self) -> None:
        self.app.processEvents()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def _pump_until(self, done, seconds: float = 10.0) -> bool:
        """Run the event loop until ``done()``: a thread's answer arrives through it."""

        deadline = time.monotonic() + seconds
        while not done() and time.monotonic() < deadline:
            self.app.processEvents()
            QThread.msleep(2)
        return bool(done())


class OpenerTestCase(QtTestCase):
    def setUp(self) -> None:
        self.host = FakeHost()
        self.factory = WindowFactory()
        self.launcher = Launcher()
        self.desktop = Desktop()
        self.disk = Disk(SESSION_ONE, SESSION_TWO, SESSION_THREE)
        self.found_vlc = SYNTHETIC_VLC
        self.vlc_asked: list[str] = []
        self.operator = Operator()
        self.widgets: list[QWidget] = []

    def tearDown(self) -> None:
        for widget in self.widgets:
            widget.deleteLater()
        self._flush_deleted()

    def _find_vlc(self, configured: str = "") -> str:
        self.vlc_asked.append(configured)
        return self.found_vlc

    def _opener(self, *answers: str) -> VideoOpener:
        opener = _opener_answering_at_once(
            self.host,
            player_factory=self.factory,
            process_launcher=self.launcher,
            desktop_opener=self.desktop,
            vlc_finder=self._find_vlc,
            exists=self.disk,
        )
        self.operator = Operator(*answers)
        opener.ask_operator = self.operator
        return opener

    def _keep(self, widget):
        self.widgets.append(widget)
        return widget


class ModuleShapeTests(unittest.TestCase):
    """Rules that a future edit must not be able to break quietly."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = ast.parse(OPENER_SOURCE.read_text(encoding="utf-8"))

    def test_the_play_target_names_can_be_imported_from_the_opener(self) -> None:
        for name in (
            "PLAYER_INTERNAL",
            "PLAYER_VLC",
            "PLAYER_SYSTEM",
            "PLAYER_CHOICES",
            "PlayTarget",
            "PlaySequence",
            "VIDEO_SUFFIXES",
            "is_video_path",
            "normalize_player_choice",
            "find_vlc",
            "build_vlc_command",
            "next_target",
            "NEXT_FOUND",
            "NEXT_NO_LIST",
            "NEXT_END_OF_LIST",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(video_open, name), getattr(play_targets, name))
                self.assertIn(name, video_open.__all__)
        for name in ("VideoOpener", "VideoPlayerSettingsPanel", "path_role_resolver"):
            self.assertIn(name, video_open.__all__)
        for name in video_open.__all__:
            self.assertTrue(hasattr(video_open, name), name)

    def test_imports_are_at_the_top_so_the_packaged_build_holds_the_player(self) -> None:
        relative: set[str] = set()
        for node in self.tree.body:
            if isinstance(node, ast.ImportFrom) and node.level:
                relative.add(node.module or "")
        # The player is imported here and nowhere lower, and nothing that
        # imports the opener (the main window, Find my bug reports) is
        # imported back, which would be a cycle.
        self.assertEqual(
            relative,
            {"metadata", "play_targets", "recording_lists", "review_package", "review_player", "widgets"},
        )
        nested = [
            node.lineno
            for node in ast.walk(self.tree)
            if isinstance(node, (ast.Import, ast.ImportFrom)) and node not in self.tree.body
        ]
        self.assertEqual(nested, [], "An import inside a function escapes the packaged build.")

    def test_the_hosts_shared_sound_output_is_never_touched(self) -> None:
        # The main window's narration preview owns that output. The built-in
        # player has one of its own and is guarded in its own test file; the
        # opener has none and has no business naming the host's, in code, in a
        # getattr string or anywhere else.
        source = OPENER_SOURCE.read_text(encoding="utf-8")
        offenders = [
            number
            for number, line in enumerate(source.splitlines(), start=1)
            if re.search(r"\baudio_output\b", line)
        ]
        self.assertEqual(offenders, [])

    def test_only_the_locate_step_ever_asks_the_disk(self) -> None:
        # Recordings sit on drives that go to sleep. One question to such a
        # drive on the GUI thread freezes the whole Workbench, so the opener
        # hands its questions to locate_recording, which a thread runs.
        disk_calls = {"exists", "_exists", "is_file", "is_dir", "isfile", "isdir", "resolve", "stat", "samefile"}
        offenders: list[str] = []
        functions = [
            node for node in ast.walk(self.tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        for function in functions:
            if function.name == "locate_recording":
                continue
            for node in ast.walk(function):
                if isinstance(node, ast.Name) and node.id == "review_copy_for":
                    offenders.append(f"{function.name}:{node.lineno} review_copy_for")
                if not isinstance(node, ast.Call):
                    continue
                called = node.func
                name = called.attr if isinstance(called, ast.Attribute) else getattr(called, "id", "")
                if name in disk_calls:
                    offenders.append(f"{function.name}:{node.lineno} {name}()")
        self.assertEqual(offenders, [])
        # And the step itself is there, asking what it is meant to ask.
        step = next(node for node in functions if node.name == "locate_recording")
        asked = {
            getattr(node.func, "id", "") for node in ast.walk(step) if isinstance(node, ast.Call)
        }
        self.assertTrue({"exists", "review_copy_for"} <= asked, asked)

    def test_the_words_on_screen_are_the_operators_words(self) -> None:
        shown: list[str] = []
        for name, value in vars(video_open).items():
            if not name.isupper():
                continue
            if isinstance(value, str):
                shown.append(value)
            elif isinstance(value, dict):
                shown.extend(str(item) for item in value.values())
        self.assertGreater(len(shown), 20)
        for text in shown:
            for word in BANNED_WORDS:
                with self.subTest(text=text[:30], word=word):
                    self.assertNotIn(word, text.lower())

    def test_the_menu_and_message_captions_are_the_agreed_ones(self) -> None:
        self.assertEqual(video_open.PLAY_TEXT, "Play")
        self.assertEqual(video_open.PLAY_MOMENT_TEXT, "Play this moment")
        self.assertEqual(video_open.PLAY_WITH_TEXT, "Play with")
        self.assertEqual(video_open.SHOW_IN_FOLDER_TEXT, "Show in folder")
        self.assertEqual(video_open.PLAY_FROM_START_TEXT, PLAY_FROM_START)
        self.assertEqual(video_open.OPEN_MOMENT_INTERNAL_TEXT, OPEN_MOMENT_INTERNAL)
        self.assertEqual([video_open.PLAYER_NAMES[choice] for choice in video_open.PLAYER_CHOICES], PLAY_WITH_ENTRIES)
        self.assertEqual(video_open.FIND_IT_TEXT, "Find it…")
        self.assertEqual(video_open.PLAY_REVIEW_COPY_TEXT, "Play the small review copy instead")
        self.assertEqual(video_open.FIND_VLC_TEXT, "Find VLC…")
        self.assertEqual(video_open.PLAY_HERE_TEXT, "Play here instead")


class ConstructionTests(OpenerTestCase):
    def test_making_an_opener_makes_no_window(self) -> None:
        class Tripwire:
            def __init__(self, *_args, **_kwargs) -> None:
                raise AssertionError("The built-in player was made before any video was opened.")

        before = set(QApplication.topLevelWidgets())
        # The real defaults, as every main window in the test suite uses them.
        with patch.object(video_open, "ReviewPlayerWindow", Tripwire):
            opener = VideoOpener(SimpleNamespace(app_settings={}))
            self.assertIsNone(opener.player_window)
            opener.release_media()
            opener.yield_audio()
            opener.say("synthetic words for a window that is not there")
            self.assertIs(opener.shutdown(), True)
            self.assertIsNone(opener.player_window)
            # No thread either: one is only made to ask the disk about a video.
            self.assertEqual(opener._locate_threads, set())
        self.assertEqual(set(QApplication.topLevelWidgets()), before)

    def test_nothing_is_asked_of_the_host_the_disk_or_vlc_until_a_video_is_opened(self) -> None:
        opener = self._opener()
        self.assertIsNone(opener.player_window)
        self.assertEqual(self.factory.windows, [])
        self.assertEqual(self.disk.asked, [])
        self.assertEqual(self.vlc_asked, [])
        self.assertEqual(self.launcher.started, [])
        self.assertEqual(self.host.saves, 0)

    def test_release_yield_and_shutdown_are_free_before_any_open(self) -> None:
        opener = self._opener()
        opener.release_media()
        opener.yield_audio()
        self.assertIs(opener.shutdown(0), True)
        self.assertIs(opener.shutdown(), True)
        self.assertEqual(self.factory.windows, [])

    def test_a_host_that_is_a_qt_object_owns_the_opener(self) -> None:
        owner = QObject()
        owner.app_settings = {}
        self.assertIs(VideoOpener(owner).parent(), owner)
        self.assertIsNone(self._opener().parent())
        owner.deleteLater()

    def test_the_default_factory_makes_the_real_window_lazily_with_host_and_opener(self) -> None:
        made: list[tuple] = []

        class StandIn(FakeWindow):
            def __init__(self, host, opener) -> None:
                super().__init__(host, opener)
                made.append((host, opener))

        opener = _opener_answering_at_once(self.host, exists=self.disk)
        # Swapped in AFTER the opener was made: the class is looked up when
        # the window is needed, which is what lets a test stand in for it.
        with patch.object(video_open, "ReviewPlayerWindow", StandIn):
            self.assertTrue(opener.open(PlayTarget(path=SESSION_ONE)))
            self.assertTrue(opener.open(PlayTarget(path=SESSION_TWO)))
        self.assertEqual(made, [(self.host, opener)])
        self.assertEqual([target.path for target, _s, _a in opener.player_window.opened], [SESSION_ONE, SESSION_TWO])


class RealWindowTests(QtTestCase):
    def test_the_real_built_in_player_is_what_the_opener_makes(self) -> None:
        host = SimpleNamespace(app_settings={}, save_app_settings=lambda: None)
        opener = VideoOpener(host)
        window = opener._ensure_window()
        try:
            self.assertIsInstance(window, ReviewPlayerWindow)
            self.assertIs(opener.player_window, window)
            self.assertIs(opener._ensure_window(), window)
            # Its own top-level window, so the main window's layout checks
            # never walk into it.
            self.assertIsNone(window.parent())
        finally:
            self.assertIs(opener.shutdown(5000), True)
            self._flush_deleted()
        self.assertIsNone(opener.player_window)


class DispatchTests(OpenerTestCase):
    def test_the_built_in_player_is_the_choice_when_nothing_is_stored(self) -> None:
        opener = self._opener()
        sequence = PlaySequence((PlayTarget(path=SESSION_ONE), PlayTarget(path=SESSION_TWO)), label="synthetic list")
        target = PlayTarget(path=SESSION_ONE, start_seconds=12.5, package_root=PACKAGE, voice_track=2)

        self.assertIs(opener.open(target, sequence=sequence), True)

        window = opener.player_window
        self.assertIs(window, self.factory.windows[0])
        self.assertIs(window.host, self.host)
        self.assertIs(window.opener, opener)
        self.assertEqual(window.opened, [(target, sequence, True)])
        self.assertEqual(self.launcher.started, [])
        self.assertEqual(self.desktop.opened, [])
        self.assertEqual(self.operator.asked, [])

    def test_one_window_is_made_and_reused(self) -> None:
        opener = self._opener()
        opener.open(PlayTarget(path=SESSION_ONE))
        opener.open(PlayTarget(path=SESSION_TWO))
        self.assertEqual(len(self.factory.windows), 1)
        self.assertEqual([target.path for target, _s, _a in self.factory.windows[0].opened], [SESSION_ONE, SESSION_TWO])

    def test_autoplay_follows_the_setting_at_the_moment_of_opening(self) -> None:
        opener = self._opener()
        self.host.app_settings["video_autoplay"] = False
        opener.open(PlayTarget(path=SESSION_ONE))
        # The main window swaps its settings for new ones when a bundle is imported.
        self.host.app_settings = {"video_autoplay": True}
        opener.open(PlayTarget(path=SESSION_TWO))
        self.assertEqual([autoplay for _t, _s, autoplay in self.factory.windows[0].opened], [False, True])

    def test_the_stored_choice_decides_who_gets_the_video(self) -> None:
        opener = self._opener()
        target = PlayTarget(path=SESSION_ONE)

        self.host.app_settings["video_player"] = "vlc"
        self.assertIs(opener.open(target), True)
        self.assertEqual(self.launcher.commands, [[SYNTHETIC_VLC, str(SESSION_ONE)]])

        self.host.app_settings["video_player"] = "system"
        self.assertIs(opener.open(target), True)
        self.assertEqual(self.desktop.opened, [SESSION_ONE])

        # Neither of them needed the built-in player, so it was never made.
        self.assertIsNone(opener.player_window)
        self.assertEqual(self.factory.windows, [])

    def test_a_stored_choice_that_means_nothing_is_the_built_in_player(self) -> None:
        for stored in ("quicktime", "", None, 7, ["vlc"]):
            with self.subTest(stored=stored):
                self.setUp()
                opener = self._opener()
                self.host.app_settings["video_player"] = stored
                self.assertIs(opener.open(PlayTarget(path=SESSION_ONE)), True)
                self.assertEqual(len(self.factory.windows[0].opened), 1)
                self.assertEqual(self.launcher.started, [])
                self.assertEqual(self.desktop.opened, [])

    def test_a_player_named_for_this_one_time_wins_over_the_stored_choice(self) -> None:
        opener = self._opener()
        target = PlayTarget(path=SESSION_ONE, start_seconds=30)

        self.host.app_settings["video_player"] = "vlc"
        self.assertIs(opener.open(target, player="internal"), True)
        self.assertEqual(self.factory.windows[0].opened, [(target, None, True)])
        self.assertEqual(self.launcher.started, [])

        self.host.app_settings["video_player"] = "internal"
        self.assertIs(opener.open(target, player="system"), True)
        self.assertEqual(self.desktop.opened, [SESSION_ONE])
        self.assertIs(opener.open(target, player="vlc"), True)
        self.assertEqual(len(self.launcher.started), 1)
        self.assertEqual(len(self.factory.windows[0].opened), 1)

        # A name that means nothing is the built-in player, not the stored choice.
        self.host.app_settings["video_player"] = "system"
        self.assertIs(opener.open(target, player="quicktime"), True)
        self.assertEqual(len(self.factory.windows[0].opened), 2)

    def test_a_choice_spelt_by_hand_is_read_the_way_the_rest_of_the_app_reads_it(self) -> None:
        opener = self._opener()
        # A settings file edited by hand: the one rule for reading the choice
        # is play_targets', and the opener must not have a second one.
        self.host.app_settings["video_player"] = " VLC "
        self.assertIs(opener.open(PlayTarget(path=SESSION_ONE)), True)
        self.assertEqual(len(self.launcher.started), 1)
        self.assertIs(opener.open(PlayTarget(path=SESSION_ONE), player="System"), True)
        self.assertEqual(self.desktop.opened, [SESSION_ONE])
        self.assertEqual(self.factory.windows, [])

    def test_a_host_with_no_settings_at_all_still_opens_in_the_built_in_player(self) -> None:
        opener = _opener_answering_at_once(SimpleNamespace(), player_factory=self.factory, exists=self.disk)
        self.assertIs(opener.open(PlayTarget(path=SESSION_ONE)), True)
        self.assertEqual(self.factory.windows[0].opened[0][2], True)

    def test_something_that_is_no_recording_is_refused_without_troubling_the_disk(self) -> None:
        opener = self._opener()
        for nothing in (None, str(SESSION_ONE), PlayTarget(path=Path("")), PlayTarget(path=Path("Q:\\"))):
            with self.subTest(nothing=nothing):
                self.assertIs(opener.open(nothing), False)  # type: ignore[arg-type]
                self.assertIs(opener.show_in_folder(nothing), False)  # type: ignore[arg-type]
        self.assertEqual(self.disk.asked, [])
        self.assertEqual(self.factory.windows, [])
        self.assertEqual(self.operator.asked, [])

    def test_what_the_player_cannot_say_on_screen_goes_to_the_log(self) -> None:
        opener = self._opener()
        opener.open(PlayTarget(path=SESSION_ONE))
        self.factory.windows[0].diagnostic.emit("synthetic player detail")
        self.assertIn("synthetic player detail", self.host.log)
        # And the opener's own lines carry the full path there, never to a message.
        self.assertTrue(any(str(SESSION_ONE) in line for line in self.host.log))


class VlcTests(OpenerTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.host.app_settings["video_player"] = "vlc"

    def test_vlc_is_started_at_the_moment_and_paused_when_autoplay_is_off(self) -> None:
        opener = self._opener()
        self.host.app_settings["video_autoplay"] = False
        self.host.app_settings["video_player_vlc_path"] = r"Q:\Stored\vlc.exe"

        self.assertIs(opener.open(PlayTarget(path=SESSION_ONE, start_seconds=754.5)), True)

        # The stored place is what the finder is asked about first.
        self.assertEqual(self.vlc_asked, [r"Q:\Stored\vlc.exe"])
        command, options = self.launcher.started[0]
        self.assertEqual(command, [SYNTHETIC_VLC, "--start-time=754.500", "--start-paused", str(SESSION_ONE)])
        # A list, never one quoted string, and nothing of VLC's is read back.
        self.assertEqual(options["stdin"], subprocess.DEVNULL)
        self.assertEqual(options["stdout"], subprocess.DEVNULL)
        self.assertEqual(options["stderr"], subprocess.DEVNULL)
        self.assertNotIn("shell", options)

    def test_vlc_gets_only_the_file_when_there_is_no_moment_and_autoplay_is_on(self) -> None:
        opener = self._opener()
        opener.open(PlayTarget(path=SESSION_ONE))
        self.assertEqual(self.launcher.commands, [[SYNTHETIC_VLC, str(SESSION_ONE)]])

    def test_vlc_as_the_usual_choice_and_not_found_opens_here_without_asking_and_says_why(self) -> None:
        # Settings says: "Videos open in the built-in player until you install
        # VLC or press Find VLC." This is that sentence being true.
        self.assertEqual(video_open.VLC_NOT_FOUND_TEXT, VLC_NOT_FOUND)
        self.found_vlc = ""
        opener = self._opener()
        sequence = PlaySequence((PlayTarget(path=SESSION_ONE), PlayTarget(path=SESSION_TWO)))
        target = PlayTarget(path=SESSION_ONE, start_seconds=41)

        self.assertIs(opener.open(target, sequence=sequence), True)

        # No question on every Play: the video simply opens, and the player's
        # status line says why it is here and not in VLC.
        self.assertEqual(self.operator.asked, [])
        self.assertEqual(self.launcher.started, [])
        window = self.factory.windows[0]
        self.assertEqual(window.opened, [(target, sequence, True)])
        self.assertEqual(window.notes, [VLC_FALLBACK_NOTE])
        self.assertTrue(any("VLC was not found" in line for line in self.host.log))

        # The menu's own play entry is the usual choice too.
        _entry(opener.build_menu([target], self._keep(QWidget())), "Play this moment").trigger()
        self.assertEqual(self.operator.asked, [])
        self.assertEqual(window.notes, [VLC_FALLBACK_NOTE, VLC_FALLBACK_NOTE])

    def test_a_video_opened_in_the_built_in_player_on_purpose_carries_no_note(self) -> None:
        self.found_vlc = ""
        opener = self._opener()
        opener.open(PlayTarget(path=SESSION_ONE), player="internal")
        self.assertEqual(self.factory.windows[0].notes, [""])

    def test_play_with_vlc_not_found_asks_and_play_here_instead_opens_the_built_in_player(self) -> None:
        self.found_vlc = ""
        opener = self._opener("Play here instead")
        sequence = PlaySequence((PlayTarget(path=SESSION_ONE), PlayTarget(path=SESSION_TWO)))
        target = PlayTarget(path=SESSION_ONE, start_seconds=41)

        # "Play with > VLC": the operator asked for VLC by name, so is answered.
        self.assertIs(opener.open(target, player="vlc", sequence=sequence), True)

        self.assertEqual(len(self.operator.asked), 1)
        title, text, choices = self.operator.asked[0]
        self.assertEqual(title, "VLC was not found")
        self.assertIn("VLC was not found on this computer", text)
        self.assertEqual(choices, ("Find VLC…", "Play here instead"))
        self.assertEqual(self.launcher.started, [])
        self.assertEqual(self.factory.windows[0].opened, [(target, sequence, True)])
        # Chosen in the message, so there is nothing left to explain.
        self.assertEqual(self.factory.windows[0].notes, [""])

    def test_play_with_vlc_from_the_menu_asks_even_when_vlc_is_the_usual_choice(self) -> None:
        self.found_vlc = ""
        opener = self._opener("")
        menu = opener.build_menu([PlayTarget(path=SESSION_ONE)], self._keep(QWidget()))
        _entry(_entry(menu, "Play with").menu(), "VLC").trigger()
        self.assertEqual([title for title, _text, _choices in self.operator.asked], ["VLC was not found"])
        self.assertEqual(self.factory.windows, [])

    def test_play_with_vlc_not_found_and_cancel_opens_nothing(self) -> None:
        self.found_vlc = ""
        opener = self._opener("")
        # Taken, which is all open() can say before the disk has answered.
        self.assertIs(opener.open(PlayTarget(path=SESSION_ONE), player="vlc"), True)
        self.assertEqual(len(self.operator.asked), 1)
        self.assertEqual(self.launcher.started, [])
        self.assertEqual(self.factory.windows, [])
        self.assertEqual(self.desktop.opened, [])

    def test_the_built_in_player_is_not_offered_for_a_file_it_has_just_said_it_cannot_play(self) -> None:
        # The card "The built-in player can't play this file." sends the file
        # on with allow_internal_fallback=False. "Play here instead" would
        # only lead back to that card.
        self.found_vlc = ""
        for player in ("vlc", None):
            with self.subTest(player=player):
                self.setUp()
                self.found_vlc = ""
                opener = self._opener("")
                opener.open(PlayTarget(path=SESSION_ONE), player=player, allow_internal_fallback=False)
                title, text, choices = self.operator.asked[0]
                self.assertEqual(title, "VLC was not found")
                self.assertEqual(text, "VLC was not found on this computer. Press Find VLC… to point to it.")
                self.assertEqual(choices, ("Find VLC…",))
                self.assertEqual(self.factory.windows, [])

        # VLC that is there but will not start: the same rule.
        self.setUp()
        self.launcher.error = OSError("synthetic launch failure")
        opener = self._opener("Play here instead")
        opener.open(PlayTarget(path=SESSION_ONE), player="vlc", allow_internal_fallback=False)
        title, text, choices = self.operator.asked[0]
        self.assertEqual(title, "VLC did not start")
        self.assertEqual(text, "VLC could not be started. Press Find VLC… to point to it again.")
        self.assertEqual(choices, ("Find VLC…",))
        # Even an answer nobody was offered opens nothing here.
        self.assertEqual(self.factory.windows, [])

    def test_find_vlc_still_works_for_a_file_the_built_in_player_cannot_play(self) -> None:
        self.found_vlc = ""
        opener = self._opener("Find VLC…")
        with patch.object(video_open.QFileDialog, "getOpenFileName", return_value=(SYNTHETIC_VLC, "")):
            opener.open(PlayTarget(path=SESSION_ONE), player="vlc", allow_internal_fallback=False)
        self.assertEqual(self.launcher.commands, [[SYNTHETIC_VLC, str(SESSION_ONE)]])

    def test_find_vlc_keeps_the_place_saves_it_and_plays(self) -> None:
        self.found_vlc = ""
        told: list[str] = []
        self.host.video_player_settings = SimpleNamespace(set_vlc_path=told.append)
        opener = self._opener("Find VLC…")

        with patch.object(video_open.QFileDialog, "getOpenFileName", return_value=(SYNTHETIC_VLC, "")) as dialog:
            self.assertIs(opener.open(PlayTarget(path=SESSION_ONE, start_seconds=5), player="vlc"), True)

        dialog.assert_called_once()
        self.assertEqual(dialog.call_args.args[1], "Find VLC")
        self.assertEqual(self.host.app_settings["video_player_vlc_path"], SYNTHETIC_VLC)
        self.assertEqual(self.host.saves, 1)
        # The Settings page is told too, or its next Save would undo this.
        self.assertEqual(told, [SYNTHETIC_VLC])
        self.assertEqual(self.launcher.commands, [[SYNTHETIC_VLC, "--start-time=5.000", str(SESSION_ONE)]])
        self.assertEqual(len(self.operator.asked), 1)

    def test_find_vlc_given_up_on_opens_nothing(self) -> None:
        self.found_vlc = ""
        opener = self._opener("Find VLC…")
        with patch.object(video_open.QFileDialog, "getOpenFileName", return_value=("", "")):
            opener.open(PlayTarget(path=SESSION_ONE), player="vlc")
        self.assertNotIn("video_player_vlc_path", self.host.app_settings)
        self.assertEqual(self.host.saves, 0)
        self.assertEqual(self.launcher.started, [])
        self.assertEqual(self.factory.windows, [])

    def test_a_vlc_place_that_could_not_be_saved_still_plays_this_time(self) -> None:
        self.host.save_error = OSError("synthetic disk failure")
        opener = self._opener()
        self.assertIs(opener.set_vlc_path(f"  {SYNTHETIC_VLC} "), False)
        self.assertEqual(self.host.app_settings["video_player_vlc_path"], SYNTHETIC_VLC)
        self.assertTrue(any("synthetic disk failure" in line for line in self.host.log))

        self.host.save_error = None
        self.assertIs(opener.set_vlc_path(SYNTHETIC_VLC), True)
        # A host that cannot save says so as well; it is never None.
        self.assertIs(VideoOpener(SimpleNamespace(app_settings={})).set_vlc_path(SYNTHETIC_VLC), False)

    def test_vlc_that_will_not_start_is_said_and_can_be_played_here(self) -> None:
        self.launcher.error = OSError("synthetic launch failure")
        opener = self._opener("Play here instead")

        self.assertIs(opener.open(PlayTarget(path=SESSION_ONE)), True)

        title, _text, choices = self.operator.asked[0]
        self.assertEqual(title, "VLC did not start")
        self.assertEqual(choices, ("Find VLC…", "Play here instead"))
        self.assertEqual(len(self.factory.windows[0].opened), 1)
        # What went wrong is for the log; the message keeps to what can be done.
        self.assertTrue(any("synthetic launch failure" in line for line in self.host.log))
        self.assertNotIn("synthetic launch failure", self.operator.asked[0][1])

    def test_a_second_failure_ends_with_one_last_message_and_never_loops(self) -> None:
        self.launcher.error = OSError("synthetic launch failure")
        opener = self._opener("Find VLC…", "Find VLC…", "Find VLC…")
        with patch.object(video_open.QFileDialog, "getOpenFileName", return_value=(SYNTHETIC_VLC, "")):
            opener.open(PlayTarget(path=SESSION_ONE))
        self.assertEqual(len(self.launcher.started), 2)
        self.assertEqual(len(self.operator.asked), 2)
        self.assertEqual(self.operator.asked[1][2], ())
        self.assertEqual(self.factory.windows, [])

    def test_another_player_starting_pauses_what_the_workbench_is_playing(self) -> None:
        # 136 (Wave 8): the built-in player is the Workbench's only player, so it is the one
        # that gives way. An old preview player on the host is no longer looked at.
        leftover = FakePreviewPlayer(QMediaPlayer.PlaybackState.PlayingState)
        self.host.audio_player = leftover
        opener = self._opener()
        opener.open(PlayTarget(path=SESSION_ONE), player="internal")
        window = self.factory.windows[0]
        self.assertEqual(window.calls, [])

        opener.open(PlayTarget(path=SESSION_TWO))
        self.assertEqual(window.calls, ["yield_audio"])

        opener.open(PlayTarget(path=SESSION_TWO), player="system")
        self.assertEqual(window.calls, ["yield_audio", "yield_audio"])
        self.assertEqual(leftover.pause_calls, 0)


class SystemPlayerTests(OpenerTestCase):
    def test_the_default_video_app_is_handed_the_file_and_no_moment(self) -> None:
        opener = self._opener()
        self.assertIs(opener.open(PlayTarget(path=SESSION_ONE, start_seconds=90), player="system"), True)
        self.assertEqual(self.desktop.opened, [SESSION_ONE])
        self.assertEqual(self.launcher.started, [])

    def test_a_computer_that_opens_nothing_is_said_and_can_be_played_here(self) -> None:
        self.desktop.opens = False
        opener = self._opener("Play here instead")
        target = PlayTarget(path=SESSION_ONE)
        self.assertIs(opener.open(target, player="system"), True)
        self.assertEqual(self.operator.asked[0][2], ("Play here instead",))
        self.assertEqual(self.factory.windows[0].opened, [(target, None, True)])

        opener.ask_operator = Operator("")
        opener.open(target, player="system")
        self.assertEqual(len(self.factory.windows[0].opened), 1)

    def test_a_file_the_built_in_player_cannot_play_is_not_offered_back_to_it(self) -> None:
        self.desktop.opens = False
        opener = self._opener("Play here instead")
        opener.open(PlayTarget(path=SESSION_ONE), player="system", allow_internal_fallback=False)
        title, _text, choices = self.operator.asked[0]
        self.assertEqual(title, "The video did not open")
        # Said, with nothing to choose: there is no other player left to offer.
        self.assertEqual(choices, ())
        self.assertEqual(self.factory.windows, [])

    def test_the_default_opener_asks_qt_for_the_file_itself(self) -> None:
        opener = _opener_answering_at_once(self.host, exists=self.disk)
        with patch.object(video_open.QDesktopServices, "openUrl", return_value=True) as open_url:
            self.assertIs(opener.open(PlayTarget(path=SESSION_ONE), player="system"), True)
        open_url.assert_called_once_with(QUrl.fromLocalFile(str(SESSION_ONE)))


class MissingFileTests(OpenerTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.disk = Disk(SESSION_TWO, MOVED_ONE, REVIEW_COPY)

    def test_a_missing_recording_is_said_and_its_folder_is_never_opened(self) -> None:
        for choice in ("internal", "vlc", "system"):
            with self.subTest(choice=choice):
                self.setUp()
                self.host.app_settings["video_player"] = choice
                opener = self._opener("")

                # Taken, which is all open() can say before the disk has answered.
                self.assertIs(opener.open(PlayTarget(path=SESSION_ONE, start_seconds=12)), True)

                self.assertEqual(len(self.operator.asked), 1)
                title, text, choices = self.operator.asked[0]
                self.assertEqual(title, "Recording not found")
                self.assertIn('"synthetic-session-one.mkv"', text)
                self.assertEqual(choices, ("Find it…",))
                # Nothing at all was opened, and above all not the folder.
                self.assertEqual(self.desktop.opened, [])
                self.assertEqual(self.launcher.started, [])
                self.assertEqual(self.factory.windows, [])
                # One quick question about the file, none about its folder.
                self.assertEqual(self.disk.asked, [str(SESSION_ONE)])
                # The folder is for the log, not for the message.
                self.assertNotIn("Captured Sessions", text)
                self.assertTrue(any(str(SESSION_ONE) in line for line in self.host.log))

    def test_the_real_desktop_opener_is_never_reached_for_a_missing_recording(self) -> None:
        opener = _opener_answering_at_once(
            self.host, player_factory=self.factory, process_launcher=self.launcher, exists=self.disk
        )
        opener.ask_operator = Operator("")
        with patch.object(video_open.QDesktopServices, "openUrl", return_value=True) as open_url:
            opener.open(PlayTarget(path=SESSION_ONE), player="system")
        open_url.assert_not_called()
        self.assertEqual(len(opener.ask_operator.asked), 1)

    def test_the_small_review_copy_is_offered_when_the_package_has_one(self) -> None:
        asked: list[tuple[Path, Path]] = []

        def review_copy(package_root, recording):
            asked.append((Path(package_root), Path(recording)))
            return REVIEW_COPY

        sequence = PlaySequence((PlayTarget(path=SESSION_ONE), PlayTarget(path=SESSION_TWO)))
        opener = self._opener("Play the small review copy instead")
        with patch.object(video_open, "review_copy_for", review_copy):
            opened = opener.open(
                PlayTarget(path=SESSION_ONE, start_seconds=63.0, package_root=PACKAGE, label="synthetic moment"),
                sequence=sequence,
            )

        self.assertIs(opened, True)
        self.assertEqual(asked, [(PACKAGE, SESSION_ONE)])
        _title, text, choices = self.operator.asked[0]
        self.assertEqual(choices, ("Find it…", "Play the small review copy instead"))
        self.assertIn("small review copy", text)
        target, passed_sequence, _autoplay = self.factory.windows[0].opened[0]
        # The whole recording in small, so the moment is the same moment.
        self.assertEqual(target.path, REVIEW_COPY)
        self.assertEqual(target.start_seconds, 63.0)
        self.assertEqual(target.package_root, PACKAGE)
        self.assertEqual(target.label, "synthetic moment")
        # The copy plays, but it is the RECORDING that never-use, skip and the
        # transcript are about. Left unsaid, the copy's own path went on the
        # never-use list and the real recording stayed allowed.
        self.assertEqual(target.stands_in_for, SESSION_ONE)
        self.assertEqual(target.recording_path, SESSION_ONE)
        self.assertFalse(target.is_package_file)
        # So it keeps its place in the list it was opened from: what is next
        # after the copy is what was next after the recording.
        self.assertIs(passed_sequence, sequence)
        self.assertEqual(next_target(passed_sequence, target.recording_path, set())[0].path, SESSION_TWO)

    def test_a_stand_in_that_is_missing_too_is_looked_up_by_its_recording(self) -> None:
        asked: list[tuple[Path, Path]] = []

        def review_copy(package_root, recording):
            asked.append((Path(package_root), Path(recording)))
            return None

        opener = self._opener("")
        gone_copy = PACKAGE / "narration" / "review_video_synthetic-gone.mp4"
        with patch.object(video_open, "review_copy_for", review_copy):
            opener.open(PlayTarget(path=gone_copy, package_root=PACKAGE, stands_in_for=SESSION_ONE))
        self.assertEqual(asked, [(PACKAGE, SESSION_ONE)])

    def test_no_copy_is_offered_without_one_and_none_is_looked_for_without_a_package(self) -> None:
        opener = self._opener("", "")
        with patch.object(video_open, "review_copy_for", return_value=None) as review_copy:
            opener.open(PlayTarget(path=SESSION_ONE, package_root=PACKAGE))
            self.assertEqual(review_copy.call_count, 1)
            opener.open(PlayTarget(path=SESSION_ONE))
            self.assertEqual(review_copy.call_count, 1)
        self.assertEqual([choices for _t, _x, choices in self.operator.asked], [("Find it…",), ("Find it…",)])

    def test_find_it_opens_the_recording_where_it_is_now_and_remembers(self) -> None:
        opener = self._opener("Find it…")
        sequence = PlaySequence(
            (PlayTarget(path=SESSION_ONE), PlayTarget(path=SESSION_TWO)), label="Find my bug reports list"
        )
        target = PlayTarget(path=SESSION_ONE, start_seconds=20, voice_track=3)

        with patch.object(video_open.QFileDialog, "getOpenFileName", return_value=(str(MOVED_ONE), "")) as dialog:
            self.assertIs(opener.open(target, sequence=sequence), True)

        # The dialog is about that one file: its name in the title and first
        # in the filter, with any video as the way out.
        _parent, title, _folder, name_filter = dialog.call_args.args
        self.assertEqual(title, "Find synthetic-session-one.mkv")
        self.assertTrue(name_filter.startswith("synthetic-session-one.mkv (synthetic-session-one.mkv);;"))
        self.assertIn("*.mkv", name_filter)
        self.assertTrue(name_filter.endswith("All files (*)"))

        opened, passed_sequence, _autoplay = self.factory.windows[0].opened[0]
        self.assertEqual(opened.path, MOVED_ONE)
        self.assertEqual((opened.start_seconds, opened.voice_track), (20.0, 3))
        # The list names it where it is now, so the player can still find its
        # place in it; the rest of the list is untouched.
        self.assertEqual([entry.path for entry in passed_sequence.targets], [MOVED_ONE, SESSION_TWO])
        self.assertEqual(passed_sequence.label, "Find my bug reports list")
        self.assertEqual([entry.path for entry in sequence.targets], [SESSION_ONE, SESSION_TWO])

        # Asked for again under its old name this session: no second message.
        self.assertIs(opener.open(PlayTarget(path=Path(str(SESSION_ONE).upper())), player="vlc"), True)
        self.assertEqual(len(self.operator.asked), 1)
        self.assertEqual(self.launcher.commands, [[SYNTHETIC_VLC, str(MOVED_ONE)]])

        # And from its list again, which still names the old place.
        self.assertIs(opener.open(PlayTarget(path=SESSION_ONE), sequence=sequence), True)
        again, again_sequence, _autoplay = self.factory.windows[0].opened[1]
        self.assertEqual(again.path, MOVED_ONE)
        self.assertEqual([entry.path for entry in again_sequence.targets], [MOVED_ONE, SESSION_TWO])
        self.assertEqual(len(self.operator.asked), 1)

    def test_a_recording_that_is_back_where_it_was_is_used_from_there(self) -> None:
        opener = self._opener()
        opener.relocate_target(PlayTarget(path=SESSION_ONE), MOVED_ONE)
        self.disk.present.add(str(SESSION_ONE))
        opener.open(PlayTarget(path=SESSION_ONE))
        self.assertEqual(self.factory.windows[0].opened[0][0].path, SESSION_ONE)

    def test_a_moved_recording_keeps_the_row_its_list_was_opened_on(self) -> None:
        opener = self._opener()
        opener.relocate_target(PlayTarget(path=SESSION_ONE), MOVED_ONE)
        sequence = PlaySequence(
            (PlayTarget(path=SESSION_TWO), PlayTarget(path=SESSION_ONE)), label="synthetic list", opened_at=1
        )
        opener.open(PlayTarget(path=SESSION_ONE), sequence=sequence)
        _target, passed_sequence, _autoplay = self.factory.windows[0].opened[0]
        self.assertEqual([entry.path for entry in passed_sequence.targets], [SESSION_TWO, MOVED_ONE])
        self.assertEqual((passed_sequence.label, passed_sequence.opened_at), ("synthetic list", 1))

    def test_find_it_given_up_on_opens_nothing(self) -> None:
        opener = self._opener("Find it…")
        with patch.object(video_open.QFileDialog, "getOpenFileName", return_value=("", "")) as dialog:
            opener.open(PlayTarget(path=SESSION_ONE))
        self.assertEqual(self.factory.windows, [])
        self.assertEqual(self.desktop.opened, [])
        # The dialog starts in the folder the recording was in, and whether
        # that folder is still there is left to the dialog: the disk was asked
        # about the file and about nothing else.
        self.assertEqual(dialog.call_args.args[2], str(CAPTURES))
        self.assertEqual(self.disk.asked, [str(SESSION_ONE)])

    def test_a_file_name_with_spaces_and_brackets_still_makes_one_filter_pattern(self) -> None:
        name_filter = video_open._file_name_filter("synthetic session (one) [a];b.mkv")
        first = name_filter.split(";;")[0]
        self.assertEqual(first, "synthetic?session??one???a??b.mkv (synthetic?session??one???a??b.mkv)")
        # Qt only takes a filter apart the usual way when it holds plain characters.
        self.assertTrue(video_open._file_name_filter("synthetic’s café+1.mkv").startswith("synthetic?s?caf??1.mkv ("))
        self.assertEqual(video_open._file_name_filter("  ").split(";;")[0][:16], "Video recordings")


class ShowInFolderTests(OpenerTestCase):
    def test_windows_selects_the_recording_in_its_folder(self) -> None:
        opener = self._opener()
        opener._platform = "win32"
        self.assertIs(opener.show_in_folder(PlayTarget(path=SESSION_ONE)), True)
        command, options = self.launcher.started[0]
        self.assertEqual(command, ["explorer", "/select,", str(SESSION_ONE)])
        self.assertEqual(options["creationflags"], int(getattr(subprocess, "CREATE_NO_WINDOW", 0)))
        self.assertEqual(self.desktop.opened, [])

    def test_elsewhere_the_folder_is_opened(self) -> None:
        opener = self._opener()
        opener._platform = "linux"
        self.assertIs(opener.show_in_folder(PlayTarget(path=SESSION_ONE)), True)
        self.assertEqual(self.desktop.opened, [CAPTURES])
        self.assertEqual(self.launcher.started, [])

    def test_a_recording_found_again_is_shown_where_it_is_now(self) -> None:
        self.disk = Disk(MOVED_ONE)
        opener = self._opener()
        opener._platform = "win32"
        opener.relocate_target(PlayTarget(path=SESSION_ONE), MOVED_ONE)
        opener.show_in_folder(PlayTarget(path=SESSION_ONE))
        self.assertEqual(self.launcher.commands, [["explorer", "/select,", str(MOVED_ONE)]])

    def test_a_missing_recording_still_shows_its_folder_because_that_was_asked_for(self) -> None:
        self.disk = Disk()
        opener = self._opener()
        opener._platform = "win32"
        self.assertIs(opener.show_in_folder(PlayTarget(path=SESSION_ONE)), True)
        self.assertEqual(self.desktop.opened, [CAPTURES])
        self.assertEqual(self.operator.asked, [])
        self.assertEqual(self.launcher.started, [])
        # Whether the folder is there is for the computer to say when it is
        # asked to open it. The disk was asked about the file and nothing else.
        self.assertEqual(self.disk.asked, [str(SESSION_ONE)])

    def test_a_folder_that_is_gone_too_is_said(self) -> None:
        self.disk = Disk()
        self.desktop.opens = False
        opener = self._opener()
        opener.show_in_folder(PlayTarget(path=SESSION_ONE))
        self.assertEqual(self.desktop.opened, [CAPTURES])
        self.assertEqual(self.operator.asked[0][0], "Folder not found")
        self.assertEqual(self.operator.asked[0][2], ())

    def test_no_review_copy_is_looked_for_to_show_a_folder(self) -> None:
        self.disk = Disk()
        opener = self._opener()
        with patch.object(video_open, "review_copy_for", return_value=REVIEW_COPY) as review_copy:
            opener.show_in_folder(PlayTarget(path=SESSION_ONE, package_root=PACKAGE))
        review_copy.assert_not_called()
        self.assertEqual(self.desktop.opened, [CAPTURES])

    def test_the_disk_is_asked_about_the_folder_away_from_the_gui_thread_too(self) -> None:
        held = HeldAnswers()
        opener = VideoOpener(
            self.host, process_launcher=self.launcher, desktop_opener=self.desktop, exists=self.disk, locate_runner=held
        )
        opener._platform = "win32"
        self.assertIs(opener.show_in_folder(PlayTarget(path=SESSION_ONE)), True)
        self.assertEqual((self.disk.asked, self.launcher.started, self.desktop.opened), ([], [], []))
        held.asked[0][1](LocateResult(found=SESSION_ONE))
        self.assertEqual(self.launcher.commands, [["explorer", "/select,", str(SESSION_ONE)]])


class MenuTests(OpenerTestCase):
    def _menu(self, opener: VideoOpener, targets, **options) -> QMenu:
        parent = self._keep(QWidget())
        return opener.build_menu(targets, parent, **options)

    def test_a_recording_gets_play_play_with_and_show_in_folder_in_that_order(self) -> None:
        opener = self._opener()
        menu = self._menu(opener, [PlayTarget(path=SESSION_ONE)])

        self.assertEqual(_texts(menu), ["Play", "Play with", "Show in folder"])
        # The submenu has to outlive the code that built it. Made the short
        # way (menu.addMenu("Play with")) it was deleted at once, and this
        # line is what caught it.
        gc.collect()
        self.assertEqual(_texts(_entry(menu, "Play with").menu()), PLAY_WITH_ENTRIES)
        # Built, never shown: where it appears is the caller's business.
        self.assertFalse(menu.isVisible())
        self.assertEqual(self.factory.windows, [])
        self.assertEqual(self.disk.asked, [])

    def test_a_moment_says_so(self) -> None:
        for choice in ("internal", "vlc"):
            with self.subTest(choice=choice):
                self.host.app_settings["video_player"] = choice
                menu = self._menu(self._opener(), [PlayTarget(path=SESSION_ONE, start_seconds=41.5)])
                self.assertEqual(_texts(menu), ["Play this moment", "Play with", "Show in folder"])

    def test_the_default_video_app_cannot_jump_to_a_moment_and_the_menu_says_so(self) -> None:
        self.host.app_settings["video_player"] = "system"
        opener = self._opener()
        target = PlayTarget(path=SESSION_ONE, start_seconds=41.5, package_root=PACKAGE)
        menu = self._menu(opener, [target])

        self.assertEqual(_texts(menu), [PLAY_FROM_START, OPEN_MOMENT_INTERNAL, "Play with", "Show in folder"])

        _entry(menu, PLAY_FROM_START).trigger()
        self.assertEqual(self.desktop.opened, [SESSION_ONE])
        self.assertEqual(self.factory.windows, [])

        _entry(menu, OPEN_MOMENT_INTERNAL).trigger()
        self.assertEqual(self.factory.windows[0].opened, [(target, None, True)])

        # Without a moment there is nothing to be honest about.
        plain = self._menu(opener, [PlayTarget(path=SESSION_ONE)])
        self.assertEqual(_texts(plain), ["Play", "Play with", "Show in folder"])

    def test_play_uses_the_stored_choice_and_play_with_overrides_it(self) -> None:
        self.host.app_settings["video_player"] = "vlc"
        opener = self._opener()
        sequence = PlaySequence((PlayTarget(path=SESSION_ONE), PlayTarget(path=SESSION_TWO)))
        target = PlayTarget(path=SESSION_ONE)
        menu = self._menu(opener, [target], sequence=sequence)

        _entry(menu, "Play").trigger()
        self.assertEqual(self.launcher.commands, [[SYNTHETIC_VLC, str(SESSION_ONE)]])

        play_with = _entry(menu, "Play with").menu()
        _entry(play_with, "Built-in player").trigger()
        self.assertEqual(self.factory.windows[0].opened, [(target, sequence, True)])
        _entry(play_with, "Default video app").trigger()
        self.assertEqual(self.desktop.opened, [SESSION_ONE])
        _entry(play_with, "VLC").trigger()
        self.assertEqual(len(self.launcher.started), 2)

    def test_show_in_folder_is_wired(self) -> None:
        opener = self._opener()
        opener._platform = "win32"
        _entry(self._menu(opener, [PlayTarget(path=SESSION_ONE)]), "Show in folder").trigger()
        self.assertEqual(self.launcher.commands, [["explorer", "/select,", str(SESSION_ONE)]])

    def test_entries_are_added_to_a_menu_that_already_has_some(self) -> None:
        opener = self._opener()
        menu = QMenu(self._keep(QWidget()))
        menu.addAction("Find my voice automatically")
        menu.addSeparator()
        menu.addAction("Never use this recording")

        opener.add_menu_actions(menu, [PlayTarget(path=SESSION_ONE)])

        self.assertEqual(
            _texts(menu),
            ["Find my voice automatically", "---", "Never use this recording", "Play", "Play with", "Show in folder"],
        )

    def test_nothing_to_play_adds_nothing(self) -> None:
        opener = self._opener()
        menu = QMenu(self._keep(QWidget()))
        opener.add_menu_actions(menu, [])
        opener.add_menu_actions(menu, [None, "synthetic-session-one.mkv"])  # type: ignore[list-item]
        self.assertTrue(menu.isEmpty())
        self.assertTrue(self._menu(opener, []).isEmpty())

    def test_several_recordings_get_one_named_entry_each(self) -> None:
        opener = self._opener()
        sequence = PlaySequence((PlayTarget(path=SESSION_ONE), PlayTarget(path=SESSION_TWO)))
        menu = self._menu(
            opener,
            [PlayTarget(path=SESSION_ONE), PlayTarget(path=SESSION_TWO, label="synthetic laps & pit stops")],
            sequence=sequence,
        )

        # "&&" is how a menu shows one "&" instead of underlining a letter.
        self.assertEqual(_texts(menu), ["synthetic-session-one.mkv", "synthetic laps && pit stops"])
        second = menu.actions()[1].menu()
        self.assertEqual(_texts(second), ["Play", "Play with", "Show in folder"])
        _entry(second, "Play").trigger()
        opened, passed_sequence, _autoplay = self.factory.windows[0].opened[0]
        self.assertEqual(opened.path, SESSION_TWO)
        self.assertIs(passed_sequence, sequence)


class AttachTests(OpenerTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.resolved: list[tuple[int, int, object]] = []
        self.shown: list[list[str]] = []
        self.menus: list[QMenu] = []

    def _resolver(self, index) -> list[PlayTarget]:
        self.resolved.append((index.row(), index.column(), index.data(Qt.ItemDataRole.UserRole)))
        return path_role_resolver()(index)

    def _attached(self, view, resolver=None, **options) -> VideoOpener:
        opener = self._opener()

        def exec_menu(menu: QMenu, _where) -> None:
            self.menus.append(menu)
            self.shown.append(_texts(menu))

        opener._exec_menu = exec_menu
        opener.attach(view, resolver or self._resolver, **options)
        return opener

    def _list(self, *paths) -> QListWidget:
        view = self._keep(QListWidget())
        view.resize(320, 240)
        for path in paths:
            item = QListWidgetItem(Path(str(path)).name)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            view.addItem(item)
        return view

    def _table(self, *paths) -> QTableWidget:
        view = self._keep(QTableWidget(len(paths), 3))
        view.resize(480, 240)
        for row, path in enumerate(paths):
            for column in range(3):
                item = QTableWidgetItem(f"{row}:{column}")
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                view.setItem(row, column, item)
        return view

    def test_a_list_gets_the_menu_for_the_row_that_was_right_clicked(self) -> None:
        view = self._list(SESSION_ONE, SESSION_TWO, SESSION_THREE)
        opener = self._attached(view)
        self.assertEqual(view.contextMenuPolicy(), Qt.ContextMenuPolicy.CustomContextMenu)

        view.customContextMenuRequested.emit(view.visualItemRect(view.item(1)).center())

        self.assertEqual(self.resolved, [(1, 0, str(SESSION_TWO))])
        self.assertEqual(self.shown, [["Play", "Play with", "Show in folder"]])
        _entry(self.menus[0], "Play").trigger()
        self.assertEqual(self.factory.windows[0].opened, [(PlayTarget(path=SESSION_TWO), None, True)])
        self.assertIs(opener.player_window, self.factory.windows[0])

    def test_a_table_is_resolved_by_the_cell_that_was_right_clicked(self) -> None:
        view = self._table(SESSION_ONE, SESSION_TWO)
        self._attached(view)

        view.customContextMenuRequested.emit(view.visualItemRect(view.item(1, 2)).center())

        self.assertEqual(self.resolved, [(1, 2, str(SESSION_TWO))])
        self.assertEqual(self.shown, [["Play", "Play with", "Show in folder"]])

    def test_a_row_with_nothing_to_play_shows_no_menu(self) -> None:
        view = self._list(SESSION_ONE, "https://example.invalid/synthetic.mp4", CAPTURES / "synthetic-notes.md")
        self._attached(view)
        for row in (1, 2):
            view.customContextMenuRequested.emit(view.visualItemRect(view.item(row)).center())
        self.assertEqual(len(self.resolved), 2)
        self.assertEqual(self.shown, [])

        # Below the last row there is no row to ask about at all.
        view.customContextMenuRequested.emit(QPoint(10, 230))
        self.assertEqual(len(self.resolved), 2)
        self.assertEqual(self.shown, [])

    def test_double_click_plays_the_row(self) -> None:
        view = self._table(SESSION_ONE, SESSION_TWO)
        self._attached(view)

        view.doubleClicked.emit(view.model().index(1, 1))

        self.assertEqual(self.resolved, [(1, 1, str(SESSION_TWO))])
        self.assertEqual(self.factory.windows[0].opened, [(PlayTarget(path=SESSION_TWO), None, True)])
        self.assertEqual(self.shown, [])

    def test_double_click_is_left_alone_where_a_view_already_uses_it(self) -> None:
        view = self._list(SESSION_ONE, SESSION_TWO)
        already: list[str] = []
        view.itemDoubleClicked.connect(lambda item: already.append(item.text()))
        self._attached(view, double_click=False)

        view.doubleClicked.emit(view.model().index(0, 0))

        # What the view did with a double-click before, it still does, and
        # the opener did not join in.
        self.assertEqual(already, ["synthetic-session-one.mkv"])
        self.assertEqual(self.factory.windows, [])
        self.assertEqual(self.resolved, [])
        # The menu is still there.
        view.customContextMenuRequested.emit(view.visualItemRect(view.item(0)).center())
        self.assertEqual(len(self.shown), 1)

    def test_a_view_with_its_own_menu_keeps_it(self) -> None:
        view = self._list(SESSION_ONE)
        policy = view.contextMenuPolicy()
        self._attached(view, context_menu=False)
        self.assertEqual(view.contextMenuPolicy(), policy)

        view.customContextMenuRequested.emit(view.visualItemRect(view.item(0)).center())
        self.assertEqual(self.shown, [])
        view.doubleClicked.emit(view.model().index(0, 0))
        self.assertEqual(len(self.factory.windows[0].opened), 1)

    def test_without_a_list_nothing_is_next(self) -> None:
        view = self._list(SESSION_ONE, SESSION_TWO)
        self._attached(view)
        view.doubleClicked.emit(view.model().index(0, 0))
        self.assertIsNone(self.factory.windows[0].opened[0][1])
        # Only the row that was asked about was resolved.
        self.assertEqual(len(self.resolved), 1)

    def test_the_list_is_every_row_in_order_frozen_when_the_video_opens(self) -> None:
        view = self._list(SESSION_ONE, CAPTURES / "synthetic-notes.md", SESSION_TWO)
        self._attached(view, sequence=True, label="Find my bug reports list")

        view.customContextMenuRequested.emit(view.visualItemRect(view.item(0)).center())
        # Showing the menu asked about one row. A resolver may read a file
        # per row, and a right-click must not pay for the whole view.
        self.assertEqual(len(self.resolved), 1)

        # A row that arrives before Play is pressed is in the list...
        late = QListWidgetItem(SESSION_THREE.name)
        late.setData(Qt.ItemDataRole.UserRole, str(SESSION_THREE))
        view.addItem(late)
        _entry(self.menus[0], "Play").trigger()
        self.assertEqual(len(self.resolved), 1 + 4)

        target, sequence, _autoplay = self.factory.windows[0].opened[0]
        self.assertEqual(target.path, SESSION_ONE)
        self.assertIsInstance(sequence, PlaySequence)
        self.assertIsInstance(sequence.targets, tuple)
        # ...in view order, without the row that has nothing to play.
        self.assertEqual([entry.path for entry in sequence.targets], [SESSION_ONE, SESSION_TWO, SESSION_THREE])
        self.assertEqual(sequence.label, "Find my bug reports list")
        self.assertEqual(sequence.opened_at, 0)

        # ...and what the view does afterwards cannot reach the player's copy.
        view.takeItem(0)
        view.clear()
        self.assertEqual([entry.path for entry in sequence.targets], [SESSION_ONE, SESSION_TWO, SESSION_THREE])
        with self.assertRaises(AttributeError):
            sequence.targets = ()  # type: ignore[misc]

    def test_double_click_carries_the_list_too_and_rows_with_several_moments_are_flattened(self) -> None:
        view = self._table(SESSION_ONE, SESSION_TWO)

        def two_moments(index) -> list[PlayTarget]:
            path = Path(index.data(Qt.ItemDataRole.UserRole))
            return [PlayTarget(path=path, start_seconds=10), PlayTarget(path=path, start_seconds=20)]

        self._attached(view, two_moments, sequence=True)
        view.doubleClicked.emit(view.model().index(1, 0))

        target, sequence, _autoplay = self.factory.windows[0].opened[0]
        self.assertEqual((target.path, target.start_seconds), (SESSION_TWO, 10.0))
        self.assertEqual(
            [(entry.path, entry.start_seconds) for entry in sequence.targets],
            [(SESSION_ONE, 10.0), (SESSION_ONE, 20.0), (SESSION_TWO, 10.0), (SESSION_TWO, 20.0)],
        )
        # The first moment of the row that was opened: a place in the
        # flattened list, which is not the row's number in the view.
        self.assertEqual(sequence.opened_at, 2)

    def test_the_list_remembers_which_row_was_opened_when_a_recording_is_on_several(self) -> None:
        # History has one row per run, so one recording can be on rows that
        # are not next to each other.
        view = self._list(SESSION_ONE, SESSION_TWO, SESSION_ONE, SESSION_THREE)
        self._attached(view, sequence=True)

        view.doubleClicked.emit(view.model().index(2, 0))

        target, sequence, _autoplay = self.factory.windows[0].opened[0]
        self.assertEqual(sequence.opened_at, 2)
        # "Next" goes on from the row that was opened. Found by path alone it
        # went back up to the second row.
        self.assertEqual(next_target(sequence, target.path, set())[0].path, SESSION_THREE)

    def test_rows_with_nothing_to_play_do_not_shift_the_opened_place(self) -> None:
        view = self._list(CAPTURES / "synthetic-notes.md", SESSION_ONE, SESSION_TWO)
        self._attached(view, sequence=True)
        view.doubleClicked.emit(view.model().index(2, 0))
        _target, sequence, _autoplay = self.factory.windows[0].opened[0]
        self.assertEqual([entry.path for entry in sequence.targets], [SESSION_ONE, SESSION_TWO])
        self.assertEqual(sequence.opened_at, 1)

    def test_the_clicked_row_is_followed_while_the_menu_is_up(self) -> None:
        view = self._list(SESSION_ONE, SESSION_TWO, SESSION_THREE)
        self._attached(view, sequence=True)
        view.customContextMenuRequested.emit(view.visualItemRect(view.item(1)).center())

        # A row arrives ABOVE the clicked one before Play is pressed.
        session_four = CAPTURES / "synthetic-session-four.mkv"
        early = QListWidgetItem(session_four.name)
        early.setData(Qt.ItemDataRole.UserRole, str(session_four))
        view.insertItem(0, early)
        _entry(self.menus[0], "Play").trigger()

        target, sequence, _autoplay = self.factory.windows[0].opened[0]
        self.assertEqual(target.path, SESSION_TWO)
        self.assertEqual(sequence.targets[sequence.opened_at].path, SESSION_TWO)
        self.assertEqual(sequence.opened_at, 2)

    def test_a_clicked_row_that_has_gone_leaves_the_place_to_be_found_by_path(self) -> None:
        view = self._list(SESSION_ONE, SESSION_TWO, SESSION_THREE)
        self._attached(view, sequence=True)
        view.customContextMenuRequested.emit(view.visualItemRect(view.item(2)).center())
        view.takeItem(2)
        _entry(self.menus[0], "Play").trigger()

        target, sequence, _autoplay = self.factory.windows[0].opened[0]
        self.assertEqual(target.path, SESSION_THREE)
        self.assertEqual([entry.path for entry in sequence.targets], [SESSION_ONE, SESSION_TWO])
        self.assertEqual(sequence.opened_at, 0)

    def test_a_view_of_one_recording_is_not_a_list(self) -> None:
        view = self._list(SESSION_ONE)
        self._attached(view, sequence=True)
        view.doubleClicked.emit(view.model().index(0, 0))
        self.assertIsNone(self.factory.windows[0].opened[0][1])


class PathRoleResolverTests(QtTestCase):
    def setUp(self) -> None:
        self.view = QListWidget()

    def tearDown(self) -> None:
        self.view.deleteLater()
        self._flush_deleted()

    def _index(self, value, role=Qt.ItemDataRole.UserRole):
        item = QListWidgetItem("synthetic row")
        item.setData(role, value)
        self.view.addItem(item)
        return self.view.model().index(self.view.count() - 1, 0)

    def test_a_row_that_carries_a_video_path_can_be_played(self) -> None:
        resolve = path_role_resolver()
        self.assertEqual(resolve(self._index(str(SESSION_ONE))), [PlayTarget(path=SESSION_ONE)])
        self.assertEqual(resolve(self._index(f"  {SESSION_TWO} ")), [PlayTarget(path=SESSION_TWO)])
        self.assertEqual(resolve(self._index(SESSION_THREE)), [PlayTarget(path=SESSION_THREE)])

    def test_anything_else_resolves_to_nothing(self) -> None:
        resolve = path_role_resolver()
        for value in (
            None,
            "",
            "   ",
            7,
            {"source": str(SESSION_ONE)},
            "Queued item 3",
            "https://example.invalid/synthetic.mp4",
            str(CAPTURES / "synthetic-notes.md"),
            str(CAPTURES),
        ):
            with self.subTest(value=value):
                self.assertEqual(resolve(self._index(value)), [])

    def test_the_role_can_be_chosen(self) -> None:
        role = Qt.ItemDataRole.UserRole + 1
        index = self._index(str(SESSION_ONE), role)
        self.assertEqual(path_role_resolver(role)(index), [PlayTarget(path=SESSION_ONE)])
        self.assertEqual(path_role_resolver()(index), [])


class LocateRecordingTests(OpenerTestCase):
    """The questions put to the disk, which only ever run away from the GUI thread."""

    def test_a_recording_that_is_there_costs_one_question(self) -> None:
        with patch.object(video_open, "review_copy_for", side_effect=AssertionError("not missing")):
            result = locate_recording(
                PlayTarget(path=SESSION_ONE, package_root=PACKAGE), moved=MOVED_ONE, exists=self.disk
            )
        self.assertEqual(result, LocateResult(found=SESSION_ONE))
        self.assertEqual(self.disk.asked, [str(SESSION_ONE)])

    def test_a_recording_found_again_earlier_is_looked_for_where_it_was_found(self) -> None:
        self.disk = Disk(MOVED_ONE)
        result = locate_recording(PlayTarget(path=SESSION_ONE), moved=MOVED_ONE, exists=self.disk)
        self.assertEqual(result, LocateResult(found=MOVED_ONE))
        # The file, then the file where it was found again. Never a folder.
        self.assertEqual(self.disk.asked, [str(SESSION_ONE), str(MOVED_ONE)])

    def test_the_review_copy_is_looked_for_only_when_the_recording_is_missing_and_a_package_is_named(self) -> None:
        self.disk = Disk()
        with patch.object(video_open, "review_copy_for", return_value=REVIEW_COPY) as review_copy:
            self.assertEqual(locate_recording(PlayTarget(path=SESSION_ONE), exists=self.disk), LocateResult())
            review_copy.assert_not_called()
            result = locate_recording(PlayTarget(path=SESSION_ONE, package_root=PACKAGE), exists=self.disk)
        self.assertEqual(result, LocateResult(found=None, review_copy=REVIEW_COPY))
        review_copy.assert_called_once_with(PACKAGE, SESSION_ONE)

    def test_nothing_more_is_asked_once_it_has_been_called_off(self) -> None:
        self.disk = Disk()
        with patch.object(video_open, "review_copy_for", return_value=REVIEW_COPY) as review_copy:
            target = PlayTarget(path=SESSION_ONE, package_root=PACKAGE)
            # Called off before it began: a sleeping drive is left asleep.
            self.assertEqual(
                locate_recording(target, moved=MOVED_ONE, exists=self.disk, cancelled=lambda: True), LocateResult()
            )
            self.assertEqual(self.disk.asked, [])

            # Called off while the first question was out: that one cannot be
            # taken back, and nothing follows it.
            answers = iter([False, True, True])
            result = locate_recording(target, moved=MOVED_ONE, exists=self.disk, cancelled=lambda: next(answers))
        self.assertEqual(result, LocateResult())
        self.assertEqual(self.disk.asked, [str(SESSION_ONE)])
        review_copy.assert_not_called()


class LocateThreadTests(OpenerTestCase):
    """run() is called on the test's own thread here; what it does is the same."""

    def _run(self, thread: LocateThread) -> list[tuple]:
        seen: list[tuple] = []
        thread.located.connect(lambda generation, result: seen.append(("located", generation, result)))
        thread.failed.connect(lambda generation, details: seen.append(("failed", generation, details)))
        thread.run()
        thread.deleteLater()
        return seen

    def test_one_answer_with_its_generation_first(self) -> None:
        self.disk = Disk(MOVED_ONE)
        seen = self._run(LocateThread(7, PlayTarget(path=SESSION_ONE), MOVED_ONE, self.disk))
        self.assertEqual(seen, [("located", 7, LocateResult(found=MOVED_ONE))])

    def test_a_disk_that_cannot_even_be_asked_still_gives_exactly_one_answer(self) -> None:
        def broken(_path: str) -> bool:
            raise OSError("synthetic device failure")

        seen = self._run(LocateThread(3, PlayTarget(path=SESSION_ONE), None, broken))
        self.assertEqual(seen, [("failed", 3, "OSError: synthetic device failure")])

        # Anything at all, not only the errors a disk is known to raise.
        def stranger(_path: str) -> bool:
            raise RuntimeError("synthetic surprise")

        seen = self._run(LocateThread(4, PlayTarget(path=SESSION_ONE), None, stranger))
        self.assertEqual(seen, [("failed", 4, "RuntimeError: synthetic surprise")])

    def test_a_thread_called_off_before_it_ran_still_answers_once_and_asks_nothing(self) -> None:
        thread = LocateThread(5, PlayTarget(path=SESSION_ONE, package_root=PACKAGE), MOVED_ONE, self.disk)
        thread.cancel()
        with patch.object(video_open, "review_copy_for", side_effect=AssertionError("called off")):
            seen = self._run(thread)
        self.assertEqual(seen, [("located", 5, LocateResult())])
        self.assertEqual(self.disk.asked, [])


class OffTheGuiThreadTests(OpenerTestCase):
    def _held(self) -> tuple[VideoOpener, HeldAnswers]:
        held = HeldAnswers()
        opener = VideoOpener(self.host, player_factory=self.factory, exists=self.disk, locate_runner=held)
        self.operator = Operator()
        opener.ask_operator = self.operator
        return opener, held

    def test_open_says_taken_and_asks_the_disk_nothing_itself(self) -> None:
        opener, held = self._held()
        target = PlayTarget(path=SESSION_ONE, package_root=PACKAGE)
        with patch.object(video_open, "review_copy_for", side_effect=AssertionError("GUI thread")):
            self.assertIs(opener.open(target), True)
        self.assertEqual(self.disk.asked, [])
        self.assertEqual(self.factory.windows, [])
        self.assertEqual([asked for asked, _answer in held.asked], [target])

        held.asked[0][1](LocateResult(found=SESSION_ONE))
        self.assertEqual(self.factory.windows[0].opened, [(target, None, True)])
        self.assertEqual(self.disk.asked, [])

    def test_the_missing_message_waits_for_the_answer_and_uses_the_copy_it_names(self) -> None:
        opener, held = self._held()
        opener.ask_operator = self.operator = Operator("Play the small review copy instead")
        with patch.object(video_open, "review_copy_for", side_effect=AssertionError("GUI thread")):
            opener.open(PlayTarget(path=SESSION_ONE, package_root=PACKAGE))
            self.assertEqual(self.operator.asked, [])
            held.asked[0][1](LocateResult(review_copy=REVIEW_COPY))
        self.assertEqual(self.operator.asked[0][2], ("Find it…", "Play the small review copy instead"))
        self.assertEqual(self.factory.windows[0].opened[0][0].path, REVIEW_COPY)

    def test_a_newer_open_takes_the_place_of_one_still_waiting(self) -> None:
        opener, held = self._held()
        opener.open(PlayTarget(path=SESSION_ONE))
        opener.open(PlayTarget(path=SESSION_TWO))
        (_first, answer_first), (_second, answer_second) = held.asked

        # The first answer comes back late, as it does from a drive that was
        # asleep. The operator has asked for something else since.
        answer_first(LocateResult(found=SESSION_ONE))
        self.assertEqual(self.factory.windows, [])
        answer_first(LocateResult())
        self.assertEqual(self.operator.asked, [])

        answer_second(LocateResult(found=SESSION_TWO))
        self.assertEqual([target.path for target, _s, _a in self.factory.windows[0].opened], [SESSION_TWO])
        # The same answer given twice does not open it twice.
        answer_second(LocateResult(found=SESSION_TWO))
        self.assertEqual(len(self.factory.windows[0].opened), 1)

    def test_an_answer_that_is_no_answer_is_a_recording_that_was_not_found(self) -> None:
        opener, held = self._held()
        opener.open(PlayTarget(path=SESSION_ONE))
        held.asked[0][1](None)
        self.assertEqual([title for title, _text, _choices in self.operator.asked], ["Recording not found"])

    def test_the_thread_is_given_plain_values_and_an_older_one_is_called_off(self) -> None:
        FakeLocateThread.instances = []
        opener = VideoOpener(self.host, player_factory=self.factory, exists=self.disk)
        opener.ask_operator = self.operator
        opener.relocate_target(PlayTarget(path=SESSION_ONE), MOVED_ONE)
        with patch.object(video_open, "LocateThread", FakeLocateThread):
            self.assertIs(opener.open(PlayTarget(path=SESSION_ONE)), True)
            self.assertIs(opener.open(PlayTarget(path=SESSION_TWO)), True)
        first, second = FakeLocateThread.instances
        self.assertTrue(first.started and second.started)
        # Where it was found again goes along as a value: the thread never
        # reads the opener.
        self.assertEqual((first.target.path, first.moved, first.exists), (SESSION_ONE, MOVED_ONE, self.disk))
        self.assertEqual((second.target.path, second.moved), (SESSION_TWO, None))
        self.assertNotEqual(first.generation, second.generation)
        # Asked to stop, never waited for.
        self.assertEqual((first.cancel_calls, first.waits), (1, []))
        self.assertEqual(second.cancel_calls, 0)

        first.located.emit(first.generation, LocateResult(found=MOVED_ONE))
        first.finish()
        self.assertEqual(self.factory.windows, [])
        self.assertTrue(first.deleted)

        second.located.emit(second.generation, LocateResult(found=SESSION_TWO))
        second.finish()
        self.assertEqual([target.path for target, _s, _a in self.factory.windows[0].opened], [SESSION_TWO])
        self.assertEqual(opener._locate_threads, set())
        self.assertEqual(self.disk.asked, [])

    def test_a_thread_that_failed_is_a_recording_that_was_not_found_with_the_details_in_the_log(self) -> None:
        FakeLocateThread.instances = []
        opener = VideoOpener(self.host, player_factory=self.factory, exists=self.disk)
        opener.ask_operator = self.operator
        with patch.object(video_open, "LocateThread", FakeLocateThread):
            opener.open(PlayTarget(path=SESSION_ONE))
        thread = FakeLocateThread.instances[0]
        thread.failed.emit(thread.generation, r"OSError: synthetic failure at Q:\Captured Sessions")
        thread.finish()
        title, text, _choices = self.operator.asked[0]
        self.assertEqual(title, "Recording not found")
        # A full path is for the log, never for a message.
        self.assertNotIn("Captured Sessions", text)
        self.assertTrue(any("synthetic failure" in line for line in self.host.log))
        self.assertEqual(self.factory.windows, [])

    def test_a_real_thread_asks_the_disk_and_the_video_opens_when_it_answers(self) -> None:
        asked_on: list[int] = []

        def exists(_path: str) -> bool:
            asked_on.append(threading.get_ident())
            return True

        opener = VideoOpener(self.host, player_factory=self.factory, exists=exists)
        try:
            self.assertIs(opener.open(PlayTarget(path=SESSION_ONE)), True)
            # The answer comes back through the event loop, so nothing has
            # opened by the time open() returns.
            self.assertEqual(self.factory.windows, [])
            self.assertTrue(self._pump_until(lambda: self.factory.windows))
            self.assertEqual([target.path for target, _s, _a in self.factory.windows[0].opened], [SESSION_ONE])
            self.assertEqual(len(asked_on), 1)
            self.assertNotEqual(asked_on[0], threading.get_ident())
        finally:
            self.assertIs(opener.shutdown(10000), True)
        self.assertEqual(opener._locate_threads, set())


class SayTests(OpenerTestCase):
    def test_nothing_is_said_and_no_window_is_made_when_there_is_none(self) -> None:
        opener = self._opener()
        opener.say("synthetic words")
        self.assertIsNone(opener.player_window)
        self.assertEqual(self.factory.windows, [])

    def test_the_words_go_to_the_players_status_line(self) -> None:
        opener = self._opener()
        opener.open(PlayTarget(path=SESSION_ONE))
        opener.say("synthetic words")
        self.assertEqual(self.factory.windows[0].said, ["synthetic words"])

    def test_the_window_is_brought_forward_and_stays_maximised(self) -> None:
        class NoteWindow(QWidget):
            def __init__(self, _host, _opener) -> None:
                super().__init__()
                self.said: list[str] = []

            def show_note(self, text: str) -> None:
                self.said.append(text)

            def open_target(self, _target, **_options) -> None:
                pass

            def shutdown(self, _wait_ms: int = 5000) -> bool:
                return True

        opener = _opener_answering_at_once(self.host, player_factory=NoteWindow, exists=self.disk)
        opener.open(PlayTarget(path=SESSION_ONE))
        window = opener.player_window
        try:
            self.assertFalse(window.isVisible())
            opener.say("synthetic words")
            self.assertEqual(window.said, ["synthetic words"])
            self.assertTrue(window.isVisible())

            window.showMaximized()
            window.showMinimized()
            self.assertTrue(window.isMinimized())
            opener.say("synthetic words again")
            self.assertFalse(window.isMinimized())
            self.assertTrue(window.isMaximized())
            self.assertTrue(window.isVisible())
        finally:
            self.assertIs(opener.shutdown(), True)
            self._flush_deleted()


class ShutdownTests(OpenerTestCase):
    def test_a_question_still_out_is_called_off_and_waited_for(self) -> None:
        FakeLocateThread.instances = []
        opener = VideoOpener(self.host, player_factory=self.factory, exists=self.disk)
        with patch.object(video_open, "LocateThread", FakeLocateThread):
            opener.open(PlayTarget(path=SESSION_ONE))
        thread = FakeLocateThread.instances[0]

        # Still asking the disk when the wait runs out: the close is refused.
        self.assertIs(opener.shutdown(1234), False)
        self.assertEqual(thread.cancel_calls, 1)
        self.assertEqual(len(thread.waits), 1)
        self.assertLessEqual(thread.waits[0], 1234)
        self.assertFalse(thread.deleted)
        # Parked, so it outlives the opener if that goes first.
        self.assertIn(thread, video_open._PARKED_THREADS)

        # Its answer arrives after all. Nobody is listening any more.
        thread.located.emit(thread.generation, LocateResult(found=SESSION_ONE))
        self.assertEqual(self.factory.windows, [])

        thread.done = True
        self.assertIs(opener.shutdown(), True)
        self.assertTrue(thread.deleted)
        self.assertNotIn(thread, video_open._PARKED_THREADS)
        self.assertEqual(opener._locate_threads, set())

    def test_the_wait_is_shared_between_the_question_and_the_window(self) -> None:
        FakeLocateThread.instances = []
        opener = VideoOpener(self.host, player_factory=self.factory, exists=self.disk)
        with patch.object(video_open, "LocateThread", FakeLocateThread):
            opener.open(PlayTarget(path=SESSION_ONE))
            FakeLocateThread.instances[0].located.emit(
                FakeLocateThread.instances[0].generation, LocateResult(found=SESSION_ONE)
            )
            FakeLocateThread.instances[0].finish()
            opener.open(PlayTarget(path=SESSION_TWO))
        window = self.factory.windows[0]
        thread = FakeLocateThread.instances[1]

        def wait(milliseconds: int) -> bool:
            thread.waits.append(milliseconds)
            thread.done = True
            return True

        thread.wait = wait
        with patch.object(video_open.time, "monotonic", side_effect=[100.0, 100.0, 101.5]):
            self.assertIs(opener.shutdown(4000), True)
        # One wait_ms for the whole of shutdown: the question had all of it,
        # and the window gets what the question left.
        self.assertEqual(thread.waits, [4000])
        self.assertEqual(window.calls, ["shutdown:2500", "close", "deleteLater"])

    def test_a_real_thread_held_up_by_the_disk_refuses_the_close_until_it_is_done(self) -> None:
        asking = threading.Event()
        let_go = threading.Event()

        def exists(_path: str) -> bool:
            asking.set()
            let_go.wait(30)
            return True

        opener = VideoOpener(self.host, player_factory=self.factory, exists=exists)
        try:
            opener.open(PlayTarget(path=SESSION_ONE))
            self.assertTrue(asking.wait(10))
            started = time.monotonic()
            self.assertIs(opener.shutdown(50), False)
            self.assertLess(time.monotonic() - started, 5)
        finally:
            let_go.set()
        self.assertIs(opener.shutdown(10000), True)
        self.assertEqual(opener._locate_threads, set())
        # The answer was already on its way back when the opener shut down.
        self.app.processEvents()
        self.assertEqual(self.factory.windows, [])

    def test_shutdown_closes_the_window_once_its_threads_have_stopped(self) -> None:
        opener = self._opener()
        opener.open(PlayTarget(path=SESSION_ONE))
        window = self.factory.windows[0]

        self.assertIs(opener.shutdown(1234), True)

        self.assertEqual(window.calls, ["shutdown:1234", "close", "deleteLater"])
        self.assertIsNone(opener.player_window)
        # Nothing is left to do a second time.
        self.assertIs(opener.shutdown(), True)
        self.assertEqual(len(window.calls), 3)

        # A video opened after that gets a window of its own.
        opener.open(PlayTarget(path=SESSION_TWO))
        self.assertEqual(len(self.factory.windows), 2)
        self.assertIs(opener.player_window, self.factory.windows[1])

    def test_a_thread_that_is_still_running_is_reported_and_the_window_is_kept(self) -> None:
        opener = self._opener()
        opener.open(PlayTarget(path=SESSION_ONE))
        window = self.factory.windows[0]
        window.threads_stop = False

        self.assertIs(opener.shutdown(), False)
        self.assertEqual(window.calls, ["shutdown:5000"])
        self.assertIs(opener.player_window, window)

        window.threads_stop = True
        self.assertIs(opener.shutdown(), True)
        self.assertEqual(window.calls, ["shutdown:5000", "shutdown:5000", "close", "deleteLater"])

    def test_release_and_yield_reach_the_window(self) -> None:
        opener = self._opener()
        opener.open(PlayTarget(path=SESSION_ONE))
        opener.yield_audio()
        opener.release_media()
        opener.release_media()
        self.assertEqual(self.factory.windows[0].calls, ["yield_audio", "release_media", "release_media"])


class AskOperatorTests(QtTestCase):
    """The one method every message goes through, with the modal loop stood in for."""

    def setUp(self) -> None:
        self.opener = VideoOpener(SimpleNamespace(app_settings={}))
        self.seen: dict = {}

    def _press(self, caption: str):
        def stand_in(box: QMessageBox) -> int:
            self.seen = {
                "title": box.windowTitle(),
                "text": box.text(),
                "format": box.textFormat(),
                "icon": box.icon(),
                "buttons": sorted(button.text() for button in box.buttons()),
                "default": box.defaultButton().text() if box.defaultButton() else "",
            }
            next(button for button in box.buttons() if caption in button.text()).click()
            return 0

        return patch.object(QMessageBox, "exec", stand_in)

    def test_the_caption_that_was_pressed_comes_back(self) -> None:
        with self._press("Play here instead"):
            answer = self.opener.ask_operator("VLC was not found", "synthetic <b>text</b>", ("Find VLC…", "Play here instead"))
        self.assertEqual(answer, "Play here instead")
        self.assertEqual(self.seen["title"], "VLC was not found")
        self.assertEqual(self.seen["text"], "synthetic <b>text</b>")
        # A file name is shown as it is, never read as markup.
        self.assertEqual(self.seen["format"], Qt.TextFormat.PlainText)
        self.assertEqual(self.seen["icon"], QMessageBox.Icon.Question)
        self.assertEqual(len(self.seen["buttons"]), 3)
        self.assertEqual(self.seen["default"], "Find VLC…")

    def test_cancel_is_no_answer(self) -> None:
        with self._press("ancel"):
            self.assertEqual(self.opener.ask_operator("synthetic", "synthetic", ("Find it…",)), "")

    def test_a_message_with_nothing_to_choose_has_one_button(self) -> None:
        with self._press("OK"):
            self.assertEqual(self.opener.ask_operator("synthetic", "synthetic"), "")
        self.assertEqual(len(self.seen["buttons"]), 1)
        self.assertEqual(self.seen["icon"], QMessageBox.Icon.Information)


class SettingsPanelTests(QtTestCase):
    def setUp(self) -> None:
        self.vlc_asked: list[str] = []
        self.found_vlc = ""
        self.widgets: list[QWidget] = []

    def tearDown(self) -> None:
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        self._flush_deleted()

    def _find_vlc(self, configured: str = "") -> str:
        self.vlc_asked.append(configured)
        return self.found_vlc

    def _panel(self) -> VideoPlayerSettingsPanel:
        panel = VideoPlayerSettingsPanel(vlc_finder=self._find_vlc)
        self.widgets.append(panel)
        return panel

    @staticmethod
    def _screen_text(panel: VideoPlayerSettingsPanel) -> str:
        parts: list[str] = []
        for widget in panel.findChildren(QWidget):
            parts.append(widget.toolTip())
            text = getattr(widget, "text", None)
            if callable(text):
                parts.append(str(text()))
        combo = panel.player_combo
        parts.extend(combo.itemText(index) for index in range(combo.count()))
        return "\n".join(parts)

    def test_a_new_panel_shows_the_defaults_and_does_not_look_for_vlc(self) -> None:
        panel = self._panel()
        self.assertEqual(
            panel.values(),
            {"video_player": "internal", "video_autoplay": True, "video_player_vlc_path": ""},
        )
        self.assertIsInstance(panel.player_combo, WheelSafeComboBox)
        combo = panel.player_combo
        self.assertEqual([combo.itemText(index) for index in range(combo.count())], COMBO_TEXTS)
        self.assertEqual([combo.itemData(index) for index in range(combo.count())], ["internal", "vlc", "system"])
        self.assertTrue(panel.vlc_row.isHidden())
        # Every main window builds this panel; finding VLC reads the registry.
        self.assertEqual(self.vlc_asked, [])

    def test_the_labels_are_the_ones_the_help_pages_use(self) -> None:
        panel = self._panel()
        labels = [label.text() for label in panel.findChildren(QLabel)]
        self.assertIn("Play videos with", labels)
        self.assertEqual(panel.autoplay_checkbox.text(), "Start playing straight away")
        # The explanation is a label of its own, so the check box stays short.
        self.assertEqual(panel.autoplay_note.text(), "Off: the video opens paused on the first picture.")
        self.assertTrue(panel.autoplay_note.wordWrap())
        self.assertTrue(panel.player_note.wordWrap())
        self.assertTrue(panel.autoplay_checkbox.toolTip())
        self.assertTrue(panel.player_combo.toolTip())

    def test_what_is_loaded_is_what_comes_back(self) -> None:
        panel = self._panel()
        for stored in (
            {"video_player": "vlc", "video_autoplay": False, "video_player_vlc_path": SYNTHETIC_VLC},
            {"video_player": "system", "video_autoplay": True, "video_player_vlc_path": ""},
            {"video_player": "internal", "video_autoplay": False, "video_player_vlc_path": SYNTHETIC_VLC},
        ):
            with self.subTest(stored=stored):
                panel.load({**stored, "theme": "Dark"})
                self.assertEqual(panel.values(), stored)

    def test_stored_values_that_mean_nothing_show_as_the_defaults(self) -> None:
        panel = self._panel()
        panel.load({"video_player": "vlc", "video_autoplay": False, "video_player_vlc_path": SYNTHETIC_VLC})
        panel.load({"video_player": "quicktime", "video_player_vlc_path": ["not", "text"]})
        self.assertEqual(
            panel.values(),
            {"video_player": "internal", "video_autoplay": True, "video_player_vlc_path": ""},
        )
        self.assertTrue(panel.vlc_row.isHidden())
        # A hand-edited file may spell the choice in capitals, and may hold
        # nothing a panel can read at all.
        panel.load({"video_player": " VLC "})
        self.assertEqual(panel.values()["video_player"], "vlc")
        panel.load(None)  # type: ignore[arg-type]
        self.assertEqual(panel.values()["video_player"], "internal")

    def test_the_note_under_the_choice_says_what_that_choice_gives(self) -> None:
        panel = self._panel()
        self.assertEqual(panel.player_note.text(), NOTES["internal"])
        for position, choice in enumerate(("internal", "vlc", "system")):
            with self.subTest(choice=choice):
                panel.player_combo.setCurrentIndex(position)
                self.assertEqual(panel.player_note.text(), NOTES[choice])
                self.assertEqual(panel.vlc_row.isHidden(), choice != "vlc")
        panel.load({"video_player": "system"})
        self.assertEqual(panel.player_note.text(), NOTES["system"])

    def test_the_vlc_line_says_whether_vlc_was_found(self) -> None:
        panel = self._panel()
        panel.load({"video_player": "vlc", "video_player_vlc_path": r"Q:\Stored\vlc.exe"})
        self.assertFalse(panel.vlc_row.isHidden())
        self.assertEqual(self.vlc_asked, [r"Q:\Stored\vlc.exe"])
        self.assertEqual(panel.vlc_status_label.text(), VLC_NOT_FOUND)
        self.assertEqual(panel.vlc_status_label.property("statusKind"), "attention")
        self.assertEqual(panel.find_vlc_button.text(), "Find VLC…")

        self.found_vlc = SYNTHETIC_VLC
        with patch.object(video_open.QFileDialog, "getOpenFileName", return_value=(SYNTHETIC_VLC, "")) as dialog:
            panel.find_vlc_button.click()
        dialog.assert_called_once()
        self.assertEqual(self.vlc_asked[-1], SYNTHETIC_VLC)
        self.assertEqual(panel.vlc_status_label.text(), VLC_FOUND)
        self.assertEqual(panel.vlc_status_label.property("statusKind"), "")
        self.assertEqual(panel.values()["video_player_vlc_path"], SYNTHETIC_VLC)
        # Looking for VLC changed nothing else the operator had chosen.
        self.assertEqual(panel.values()["video_player"], "vlc")

    def test_find_vlc_given_up_on_keeps_what_was_there(self) -> None:
        panel = self._panel()
        panel.load({"video_player": "vlc", "video_player_vlc_path": r"Q:\Stored\vlc.exe"})
        with patch.object(video_open.QFileDialog, "getOpenFileName", return_value=("", "")):
            panel.browse_for_vlc()
        self.assertEqual(panel.values()["video_player_vlc_path"], r"Q:\Stored\vlc.exe")

    def test_a_place_found_from_a_message_leaves_the_other_choices_alone(self) -> None:
        panel = self._panel()
        panel.load({"video_player": "internal", "video_autoplay": True})
        panel.autoplay_checkbox.setChecked(False)
        panel.player_combo.setCurrentIndex(2)

        panel.set_vlc_path(f" {SYNTHETIC_VLC} ")

        self.assertEqual(
            panel.values(),
            {"video_player": "system", "video_autoplay": False, "video_player_vlc_path": SYNTHETIC_VLC},
        )

    def test_nothing_on_the_tab_uses_a_builders_word_and_part_two_is_named_as_built_in_only(self) -> None:
        panel = self._panel()
        panel.load({"video_player": "vlc"})
        shown = self._screen_text(panel).lower()
        for word in BANNED_WORDS:
            with self.subTest(word=word):
                self.assertNotIn(word, shown)
        # 125 Part 2 (Wave 8): the waveforms exist now, and VLC is told plainly not to have them.
        self.assertIn("waveforms, jumping between sounds, moments and never-use marking are only in the built-in player", shown)

    def test_buttons_and_check_boxes_fit_and_the_tab_stays_narrow(self) -> None:
        # The main window's own layout check walks every Settings tab at its
        # smallest size, 980 wide, where a tab gets about 740 of it.
        holder = QWidget()
        self.widgets.append(holder)
        layout = QVBoxLayout(holder)
        panel = VideoPlayerSettingsPanel(vlc_finder=self._find_vlc)
        layout.addWidget(panel)
        holder.resize(700, 480)
        holder.show()
        for choice in ("internal", "vlc", "system"):
            panel.load({"video_player": choice})
            self.app.processEvents()
            controls = [
                control
                for control in panel.findChildren(QWidget)
                if isinstance(control, (QPushButton, QCheckBox)) and control.isVisible() and control.text().strip()
            ]
            self.assertEqual(
                sorted(control.text() for control in controls),
                ["Find VLC…", "Start playing straight away"] if choice == "vlc" else ["Start playing straight away"],
            )
            for control in controls:
                with self.subTest(choice=choice, control=control.text()):
                    self.assertGreaterEqual(control.width() + 2, control.minimumSizeHint().width())
            # A wide minimum here would squeeze the buttons on every other
            # Settings tab, because the tabs share one width.
            with self.subTest(choice=choice):
                self.assertLessEqual(panel.minimumSizeHint().width(), 640)


if __name__ == "__main__":
    unittest.main()
