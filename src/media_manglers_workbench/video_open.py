"""One way to open a video, from anywhere in the Workbench (125).

Every list that shows a recording, or a moment inside one, hands it to the one
``VideoOpener`` the main window owns. The opener decides which player gets it
(the built-in player, VLC, or the computer's default video app), says so
plainly when the recording or VLC cannot be found, and builds the same
right-click entries everywhere, so "Play" means the same thing on every page.

Every main window makes an opener, including every one a test builds, so
making it has to cost nothing: the built-in player window, and with it the
picture surface, the sound output and the loader threads, only comes into
being the first time a video is really opened in it.

Recordings live on drives that go to sleep and on folders that may be out of
reach, where one question to the disk can take many seconds. So the opener
never asks the disk anything on the GUI thread: whether a recording is there is
asked by ``LocateThread``, and the video opens when it has answered.

``play_targets`` holds the rules that need no window. Its names are re-exported
here so a caller that already imports the opener needs one import line.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, replace
import functools
import os
from pathlib import Path, PurePath
import re
import subprocess
import sys
import time
from typing import Any

from PySide6.QtCore import (
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPoint,
    QSignalBlocker,
    Qt,
    QThread,
    QUrl,
    Signal,
)
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListView,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .metadata import METADATA_BY_KEY
from .play_targets import (
    NEXT_END_OF_LIST,
    NEXT_FOUND,
    NEXT_NO_LIST,
    PLAYER_CHOICES,
    PLAYER_INTERNAL,
    PLAYER_SYSTEM,
    PLAYER_VLC,
    VIDEO_SUFFIXES,
    PlaySequence,
    PlayTarget,
    build_vlc_command,
    find_vlc,
    is_video_path,
    next_target,
    normalize_player_choice,
)
from .recording_lists import path_key
from .review_package import review_copy_for
# At the top on purpose. Imported inside a function, the player would be left
# out of the packaged build and out of its smoke run.
from .review_player import ReviewPlayerWindow
from .widgets import WheelSafeComboBox

__all__ = [
    "NEXT_END_OF_LIST",
    "NEXT_FOUND",
    "NEXT_NO_LIST",
    "PLAYER_CHOICES",
    "PLAYER_INTERNAL",
    "PLAYER_SYSTEM",
    "PLAYER_VLC",
    "VIDEO_SUFFIXES",
    "LocateResult",
    "LocateThread",
    "PlaySequence",
    "PlayTarget",
    "VideoOpener",
    "VideoPlayerSettingsPanel",
    "build_vlc_command",
    "find_vlc",
    "is_video_path",
    "locate_recording",
    "next_target",
    "normalize_player_choice",
    "path_role_resolver",
]

PLAYER_SETTING_KEY = "video_player"
AUTOPLAY_SETTING_KEY = "video_autoplay"
VLC_PATH_SETTING_KEY = "video_player_vlc_path"

# The right-click entries, the same on every page.
PLAY_TEXT = "Play"
PLAY_MOMENT_TEXT = "Play this moment"
PLAY_FROM_START_TEXT = "Play from the start (your default video app can't jump to a moment)"
OPEN_MOMENT_INTERNAL_TEXT = "Open this moment in the built-in player"
PLAY_WITH_TEXT = "Play with"
SHOW_IN_FOLDER_TEXT = "Show in folder"
PLAYER_NAMES = {
    PLAYER_INTERNAL: "Built-in player",
    PLAYER_VLC: "VLC",
    PLAYER_SYSTEM: "Default video app",
}

# The answers a message can offer. ``ask_operator`` hands back the one pressed.
FIND_IT_TEXT = "Find it…"
PLAY_REVIEW_COPY_TEXT = "Play the small review copy instead"
FIND_VLC_TEXT = "Find VLC…"
PLAY_HERE_TEXT = "Play here instead"

MISSING_TITLE = "Recording not found"
MISSING_TEXT = (
    '"{name}" is not where it was. It may have been moved or renamed, or its drive is not connected.'
)
REVIEW_COPY_NOTE = (
    "This package holds a small review copy of it, which is enough to hear what was said and see "
    "what was on screen."
)
VLC_MISSING_TITLE = "VLC was not found"
VLC_MISSING_TEXT = (
    "VLC was not found on this computer. Point to it with Find VLC…, or play this video in the "
    "built-in player."
)
VLC_FAILED_TITLE = "VLC did not start"
VLC_FAILED_TEXT = (
    "VLC could not be started. Point to it again with Find VLC…, or play this video in the "
    "built-in player."
)
# The same two messages for a file the built-in player has just said it cannot
# play: offering that player again would only lead back to the same card.
VLC_MISSING_FIND_ONLY_TEXT = "VLC was not found on this computer. Press Find VLC… to point to it."
VLC_FAILED_FIND_ONLY_TEXT = "VLC could not be started. Press Find VLC… to point to it again."
VLC_STILL_FAILED_TEXT = "VLC could not be started from the place you chose."
# Shown in the built-in player's status line when VLC is the usual choice and
# is not on this computer. It is what makes VLC_NOT_FOUND_TEXT below true.
VLC_FALLBACK_NOTE = (
    "VLC was not found, so this opened in the built-in player. To use VLC, go to "
    "Settings > Video player and press Find VLC…"
)
SYSTEM_FAILED_TITLE = "The video did not open"
SYSTEM_FAILED_TEXT = (
    "Your computer did not open this video. It may have no app set up for this kind of file."
)
FOLDER_MISSING_TITLE = "Folder not found"
FOLDER_MISSING_TEXT = "The folder this recording was in is not there any more, or its drive is not connected."

# The Settings tab. Truthful for this release: nothing here promises more than
# the built-in player does today.
PLAYER_COMBO_TEXT = {
    PLAYER_INTERNAL: "Built-in player — transcript lines, choose which track you hear",
    PLAYER_VLC: "VLC — plays the video only",
    PLAYER_SYSTEM: "Your computer's default video app — plays the video only",
}
PLAYER_NOTES = {
    PLAYER_INTERNAL: (
        "The video opens inside the Workbench. You can read what the transcriber wrote at the moment "
        "you are hearing it, including lines it left out and why, choose which audio track you hear, "
        "see every track's waveform, jump between the sounds on the track you hear and between the "
        "moments a package found, and mark a recording as never-use."
    ),
    PLAYER_VLC: (
        "The video opens in VLC. Transcript lines, track choice, waveforms, jumping between sounds, "
        "moments and never-use marking are only in the built-in player. Playing a moment still starts "
        "VLC at the right time."
    ),
    PLAYER_SYSTEM: (
        "The video opens in whatever app your computer normally uses for videos. Transcript lines, "
        "track choice, waveforms, jumping between sounds, moments and never-use marking are only in "
        "the built-in player. This choice always starts at the beginning, and that app decides whether "
        "it starts playing."
    ),
}
VLC_FOUND_TEXT = "VLC found."
VLC_NOT_FOUND_TEXT = (
    "VLC was not found on this computer. Videos open in the built-in player until you install VLC "
    "or press Find VLC."
)
AUTOPLAY_OFF_NOTE = "Off: the video opens paused on the first picture."

VLC_FILE_FILTER = "VLC (vlc.exe vlc VLC);;Programs (*.exe);;All files (*)"

# A file-dialog filter is picky: a space ends a pattern, brackets and
# semicolons mean something to it, and Qt only takes a filter apart the usual
# way when it holds characters from a short list. So everything but plain
# letters, digits and ". _ -" becomes "?", which stands for exactly one
# character: the filter still only fits the file being looked for.
_FILTER_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def _file_name_filter(name: str) -> str:
    """A file-dialog filter that shows the named file first, then any video."""

    pattern = _FILTER_UNSAFE.sub("?", name.strip())
    videos = " ".join(f"*{suffix}" for suffix in sorted(VIDEO_SUFFIXES))
    wanted = f"{pattern} ({pattern});;" if pattern else ""
    return f"{wanted}Video recordings ({videos});;All files (*)"


def _vlc_browse_folder() -> str:
    # Where VLC's installer puts it, so the operator starts next to it.
    return str(os.environ.get("ProgramFiles") or "") if sys.platform == "win32" else ""


def _menu_caption(target: PlayTarget) -> str:
    # A menu reads "&" as "underline the next letter"; a file name means it.
    return (target.label or target.path.name).replace("&", "&&")


def _add_submenu(menu: QMenu, title: str) -> QMenu:
    # Made with its parent, not with menu.addMenu(title). Measured here: once
    # its entries were connected, the menu that call hands back was deleted
    # the moment its Python name went out of scope, and "Play with" was left
    # pointing at nothing. One made with a parent belongs to that parent.
    submenu = QMenu(title, menu)
    menu.addMenu(submenu)
    return submenu


def _no_sequence(_clicked: QModelIndex | QPersistentModelIndex | None = None) -> PlaySequence | None:
    return None


def _never_cancelled() -> bool:
    return False


@dataclass(frozen=True, slots=True)
class LocateResult:
    """What the disk said about one recording."""

    found: Path | None = None  # where its file is now; None when it is nowhere
    review_copy: Path | None = None  # the package's small copy; only looked for when the recording is missing


def locate_recording(
    target: PlayTarget,
    *,
    moved: Path | None = None,
    exists: Callable[[str], bool] = os.path.exists,
    cancelled: Callable[[], bool] = _never_cancelled,
) -> LocateResult:
    """Ask the disk where ``target`` is. Slow on a sleeping drive: never for the GUI thread.

    ``moved`` is where "Find it…" found this recording earlier in the session.
    Only the file itself is asked about, never its folder.
    """

    if cancelled():
        # Called off before it began, so a sleeping drive is left asleep.
        return LocateResult()
    if exists(str(target.path)):
        return LocateResult(found=target.path)
    if moved is not None and not cancelled() and exists(str(moved)):
        return LocateResult(found=Path(moved))
    if target.package_root is None or cancelled():
        return LocateResult()
    # Reads the package's own files, and works out the recording's full path
    # on the way, so it waits on the same slow disks as the questions above.
    return LocateResult(review_copy=review_copy_for(target.package_root, target.recording_path))


# A locate thread that shutdown() gave up waiting for is parked here until it
# finishes. A thread object that is destroyed while it is still running ends
# the whole process, and the opener that owned it may be gone by then.
_PARKED_THREADS: set[QThread] = set()


def _park_thread(thread: QThread) -> None:
    if thread not in _PARKED_THREADS:
        _PARKED_THREADS.add(thread)
        thread.finished.connect(functools.partial(_PARKED_THREADS.discard, thread))


class LocateThread(QThread):
    """Asks the disk where a recording is, so the GUI thread never waits for it.

    Everything it needs is handed over as plain values; it never looks at the
    opener, the host or the settings.
    """

    located = Signal(int, object)  # generation, LocateResult
    failed = Signal(int, str)  # generation, details for the log

    def __init__(
        self,
        generation: int,
        target: PlayTarget,
        moved: Path | None,
        exists: Callable[[str], bool],
    ) -> None:
        super().__init__()
        self.generation = generation
        self.target = target
        self.moved = Path(moved) if moved else None
        self._exists = exists
        self._cancel_requested = False

    def cancel(self) -> None:
        # Qt ignores an interruption request made before the thread is really
        # running, so the wish to stop is remembered here as well. A question
        # the disk is already answering cannot be called off; what is skipped
        # is every question after it.
        self._cancel_requested = True
        self.requestInterruption()

    def _cancelled(self) -> bool:
        return self._cancel_requested or self.isInterruptionRequested()

    def run(self) -> None:
        # Exactly one of the two signals, whatever happens. The opener has
        # already said "accepted", so a thread that died quietly would leave a
        # double-click that never does anything.
        try:
            result = locate_recording(
                self.target, moved=self.moved, exists=self._exists, cancelled=self._cancelled
            )
        except Exception as exc:  # noqa: BLE001 - see above
            self.failed.emit(self.generation, f"{type(exc).__name__}: {exc}")
            return
        self.located.emit(self.generation, result)


def path_role_resolver(
    role: Qt.ItemDataRole = Qt.ItemDataRole.UserRole,
) -> Callable[[QModelIndex], list[PlayTarget]]:
    """A resolver for views whose rows carry the recording's path as item data.

    Rows that hold something else (a web address, a placeholder, a document)
    resolve to nothing, so no Play entry is offered for them.
    """

    def resolve(index: QModelIndex) -> list[PlayTarget]:
        value = index.data(role)
        if not isinstance(value, (str, PurePath)):
            return []
        text = str(value).strip()
        if not text or not is_video_path(text):
            return []
        return [PlayTarget(path=Path(text))]

    return resolve


class VideoOpener(QObject):
    """Opens a recording in the player the operator chose. ``host`` is duck-typed.

    ``host`` is read at call time and never cached: ``app_settings``,
    ``save_app_settings()``, and when present
    ``video_player_settings`` and ``_write_workbench_log``. The built-in player
    window reads the rest of what it needs from the same host.

    ``locate_runner(target, on_result)`` gets the disk asked where ``target``
    is and calls ``on_result`` with a ``LocateResult``. The one used when none
    is given starts a ``LocateThread``. A test hands in one that answers on the
    spot: ``on_result(opener.locate_now(target))``.
    """

    def __init__(
        self,
        host: Any,
        *,
        player_factory: Callable[[Any, "VideoOpener"], Any] | None = None,
        process_launcher: Callable[..., Any] = subprocess.Popen,
        desktop_opener: Callable[[Path], bool] | None = None,
        vlc_finder: Callable[[str], str] = find_vlc,
        exists: Callable[[str], bool] | None = None,
        locate_runner: Callable[[PlayTarget, Callable[[LocateResult], None]], None] | None = None,
    ) -> None:
        # Owned by the main window when there is one, so it goes when that does.
        super().__init__(host if isinstance(host, QObject) else None)
        self._host = host
        self._player_factory = player_factory or self._default_player_window
        self._process_launcher = process_launcher
        self._desktop_opener = desktop_opener or self._default_desktop_opener
        self._vlc_finder = vlc_finder
        self._exists = exists or os.path.exists
        self._locate_runner = locate_runner or self._locate_on_a_thread
        self._platform = sys.platform
        # Nothing else is made here, and above all no window and no thread:
        # see the module docstring.
        self._window: Any | None = None
        # Where "Find it…" found a recording that had moved, by path key. Kept
        # for this session only: nothing on disk is rewritten to name the new
        # place, so after a restart it is asked again rather than trusted.
        self._relocations: dict[str, Path] = {}
        # One question to the disk counts at a time, the newest. Every answer
        # carries the number it was asked under, and any other number is
        # ignored: the operator has asked for something else since.
        self._locate_generation = 0
        self._locate_threads: set[LocateThread] = set()
        self._locate_callback: Callable[[LocateResult], None] | None = None

    # Host access ------------------------------------------------------------------

    def _settings(self) -> Mapping[str, Any]:
        # Read from the host every time. The main window replaces its settings
        # when a bundle is imported, and a copy taken earlier would be stale.
        settings = getattr(self._host, "app_settings", None)
        return settings if isinstance(settings, Mapping) else {}

    def _chosen_player(self) -> str:
        return normalize_player_choice(self._settings().get(PLAYER_SETTING_KEY))

    def _autoplay(self) -> bool:
        return bool(self._settings().get(AUTOPLAY_SETTING_KEY, True))

    def _log(self, message: str) -> None:
        """Details for the Workbench log. Full paths go here, never on screen."""

        writer = getattr(self._host, "_write_workbench_log", None)
        if callable(writer):
            writer(message)

    def _dialog_parent(self) -> QWidget | None:
        # Whichever window the operator is looking at, so a message opened
        # from the player window does not come up behind it.
        active = QApplication.activeWindow()
        if active is not None:
            return active
        return self._host if isinstance(self._host, QWidget) else None

    # The built-in player window ---------------------------------------------------

    @property
    def player_window(self) -> Any | None:
        """The built-in player window; None until a video is first opened in it."""

        return self._window

    def _default_player_window(self, host: Any, opener: "VideoOpener") -> Any:
        # Looked up by name when it is needed, so a test can put a stand-in
        # for the window class in this module.
        return ReviewPlayerWindow(host, opener)

    def _ensure_window(self) -> Any:
        if self._window is None:
            self._window = self._player_factory(self._host, self)
            # What the player cannot say on screen (error text, full paths)
            # belongs in the log.
            connect = getattr(getattr(self._window, "diagnostic", None), "connect", None)
            if callable(connect):
                connect(self._log)
        return self._window

    def dock(self, holder: QWidget) -> Any:
        """236: show the one built-in player inside ``holder``, a page's player area, and return it.

        The AI Video Editor plays the chosen version on its page this way: the same window, never a
        second player. Anything else that opens the player afterwards (a Play on another page, a track
        preview) gets it back as its own window first (``undock``).
        """

        self._cancel_locates()
        window = self._ensure_window()
        dock = getattr(window, "dock_into", None)
        if callable(dock):
            dock(holder)
        return window

    def undock(self, holder: QWidget | None = None) -> None:
        """236: give the player back its own window, paused; with ``holder``, only when it is docked there."""

        docked = self.docked_in()
        if docked is None or (holder is not None and docked is not holder):
            return
        undock = getattr(self._window, "undock", None)
        if callable(undock):
            undock()

    def docked_in(self) -> QWidget | None:
        """The page area the player is shown in now, None when it is its own window (or not made yet)."""

        docked = getattr(self._window, "docked_in", None) if self._window is not None else None
        # A stand-in window in a test answers anything; only a real page area counts.
        return docked if isinstance(docked, QWidget) else None

    def open_over(self, dialog: QWidget, target: PlayTarget) -> Any:
        """220: open the built-in player on top of a modal dialog that is waiting for an answer.

        A modal dialog takes every click and key from other windows, so the player is made modal
        itself while it serves the dialog: it takes the input until it is closed, and then the dialog
        has it again. When the dialog ends, the player goes back to being an ordinary window.
        """

        self.undock()
        window = self._ensure_window()
        if window.windowModality() != Qt.WindowModality.ApplicationModal:
            if window.isVisible():
                window.hide()
            window.setWindowModality(Qt.WindowModality.ApplicationModal)

            def release(*_args: Any) -> None:
                if window.windowModality() == Qt.WindowModality.NonModal:
                    return
                visible = window.isVisible()
                if visible:
                    window.hide()
                window.setWindowModality(Qt.WindowModality.NonModal)
                if visible:
                    window.show()

            finished = getattr(dialog, "finished", None)
            if finished is not None:
                finished.connect(release)
        return self.open_now(target)

    def open_now(self, target: PlayTarget) -> Any:
        """136 (Wave 8): open the built-in player now, playing, on the track ``target`` asks for.

        For a page that needs one track heard (the New Review wizard's Preview track, the Inbox's track
        choice): always the built-in player, whatever Settings > Video player says, because only it can
        play a chosen track; never made modal, because a page is not a dialog; and the asked-for track
        wins even over one picked earlier for the same recording. The window is returned so the page can
        listen to it. A Play still waiting for its drive is called off: this open is the newer wish.
        """

        self._cancel_locates()
        self.undock()
        window = self._ensure_window()
        window.open_target(target, autoplay=True, insist_on_track=True)
        return window

    def release_media(self) -> None:
        """Let go of the recording's file. Safe, and free, when nothing is open."""

        if self._window is not None:
            self._window.release_media()

    def yield_audio(self) -> None:
        """Pause the built-in player, keeping its place."""

        if self._window is not None:
            self._window.yield_audio()

    def say(self, text: str) -> None:
        """Say ``text`` in the built-in player's window and bring that window forward.

        For something the operator has to see when no page of the main window
        can be counted on to be the one showing. Does nothing when there is no
        player window: one is never made just to say something.
        """

        window = self._window
        if window is None:
            return
        show_note = getattr(window, "show_note", None)
        if callable(show_note):
            show_note(str(text))
        if isinstance(window, QWidget):
            if window.isMinimized():
                # Not showNormal(): that would also undo a maximised window.
                window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized)
            window.show()
            window.raise_()
            window.activateWindow()

    def shutdown(self, wait_ms: int = 5000) -> bool:
        """Close the built-in player for good; False while a thread still runs."""

        deadline = time.monotonic() + max(0, wait_ms) / 1000
        # Whatever the disk is still being asked is no longer wanted.
        self._cancel_locates()
        waited = False
        for thread in tuple(self._locate_threads):
            if thread.isRunning():
                waited = True
                remaining = max(0, round((deadline - time.monotonic()) * 1000))
                if not thread.wait(remaining):
                    # Still held here, and parked in case the opener goes first.
                    _park_thread(thread)
                    continue
            self._locate_threads.discard(thread)
            _PARKED_THREADS.discard(thread)
            thread.deleteLater()
        if self._locate_threads:
            # The same answer as for a player thread below: the main window
            # refuses to close, and the operator tries again.
            return False
        window = self._window
        if window is None:
            # Every main window a test builds comes through here on close.
            return True
        # 236: a player shown on a page is its own window again first, so closing it never reaches into
        # the page that is closing with the main window.
        self.undock()
        if waited:
            # One wait_ms for the whole of shutdown, not one for each wait.
            wait_ms = max(0, round((deadline - time.monotonic()) * 1000))
        if not window.shutdown(wait_ms):
            # The main window refuses to close on this answer and the operator
            # tries again, so the player stays as it is until then.
            return False
        window.close()
        # The window has no Qt parent, so nothing else would ever delete it.
        self._window = None
        delete_later = getattr(window, "deleteLater", None)
        if callable(delete_later):
            delete_later()
        return True

    # Opening ------------------------------------------------------------------------

    def open(
        self,
        target: PlayTarget,
        *,
        player: str | None = None,
        sequence: PlaySequence | None = None,
        allow_internal_fallback: bool = True,
    ) -> bool:
        """Take ``target`` to be opened; True when it was taken, not when it plays.

        The disk is asked where the recording is away from the GUI thread, and
        the video, or the message that it cannot be found, follows when the
        disk has answered. Asked for again before then, only the newest counts.

        ``player`` overrides the operator's usual choice for this one time.
        ``allow_internal_fallback`` is False when the built-in player itself
        sends the file on because it cannot play it, so no message offers it.
        """

        if not self._can_be_asked_for(target):
            return False
        self._begin_locate(
            target,
            functools.partial(self._open_located, target, player, sequence, allow_internal_fallback),
        )
        return True

    @staticmethod
    def _can_be_asked_for(target: Any) -> bool:
        # A path with no file name (nothing, a folder's ".", a bare drive) is
        # no recording, and the disk is not troubled about it.
        return isinstance(target, PlayTarget) and bool(target.path.name)

    # Asking the disk ----------------------------------------------------------------

    def locate_now(self, target: PlayTarget) -> LocateResult:
        """Ask the disk on the calling thread. For a ``locate_runner`` that must not start one."""

        return locate_recording(
            target, moved=self._relocations.get(path_key(target.path)), exists=self._exists
        )

    def _begin_locate(self, target: PlayTarget, then: Callable[[LocateResult], None]) -> None:
        self._cancel_locates()
        self._locate_runner(target, functools.partial(self._on_located, self._locate_generation, then))

    def _cancel_locates(self) -> None:
        # Asked to stop, never waited for: this runs while a video is being
        # opened. A new number, so an answer that is already on its way back
        # finds nobody listening.
        self._locate_generation += 1
        self._locate_callback = None
        for thread in tuple(self._locate_threads):
            thread.cancel()
        self._forget_finished_locates()

    def _locate_on_a_thread(self, target: PlayTarget, on_result: Callable[[LocateResult], None]) -> None:
        # The thread is told where the recording was found again as a plain
        # value: it must never read the opener.
        thread = LocateThread(
            self._locate_generation, target, self._relocations.get(path_key(target.path)), self._exists
        )
        # Bound methods of this object, so Qt delivers both on the GUI thread.
        thread.located.connect(self._on_thread_located)
        thread.failed.connect(self._on_thread_failed)
        thread.finished.connect(self._forget_finished_locates)
        self._locate_threads.add(thread)
        self._locate_callback = on_result
        thread.start()

    def _on_thread_located(self, generation: int, result: Any) -> None:
        if generation != self._locate_generation:
            return
        callback, self._locate_callback = self._locate_callback, None
        if callback is not None:
            callback(result)

    def _on_thread_failed(self, generation: int, details: str) -> None:
        if generation != self._locate_generation:
            return
        # The details can hold a full path, so they go to the log only. A disk
        # that cannot even be asked is, to the operator, a recording that is
        # not there, and that message says what to do about it.
        self._log(f"Could not look for the recording: {details}")
        self._on_thread_located(generation, LocateResult())

    def _forget_finished_locates(self) -> None:
        for thread in tuple(self._locate_threads):
            if thread.isFinished():
                self._locate_threads.discard(thread)
                _PARKED_THREADS.discard(thread)
                thread.deleteLater()

    def _on_located(self, generation: int, then: Callable[[LocateResult], None], result: Any) -> None:
        if generation != self._locate_generation:
            return
        # Answered. A new number, so the same answer given twice cannot open
        # the video twice.
        self._locate_generation += 1
        then(result if isinstance(result, LocateResult) else LocateResult())

    def _open_located(
        self,
        target: PlayTarget,
        player: str | None,
        sequence: PlaySequence | None,
        allow_internal_fallback: bool,
        result: LocateResult,
    ) -> None:
        if result.found is None:
            self._open_missing(target, player, sequence, allow_internal_fallback, result.review_copy)
            return
        if path_key(result.found) != path_key(target.path):
            sequence = self._sequence_with(sequence, target.path, result.found)
            target = replace(target, path=result.found)
        self._dispatch(target, player, sequence, allow_internal_fallback)

    def _dispatch(
        self,
        target: PlayTarget,
        player: str | None,
        sequence: PlaySequence | None,
        allow_internal_fallback: bool,
    ) -> bool:
        # An unknown choice, stored or handed in, means the built-in player.
        choice = normalize_player_choice(player) if player is not None else self._chosen_player()
        if choice == PLAYER_VLC:
            return self._open_in_vlc(
                target,
                sequence,
                asked_for=player is not None,
                allow_internal_fallback=allow_internal_fallback,
            )
        if choice == PLAYER_SYSTEM:
            return self._open_in_system(target, sequence, allow_internal_fallback=allow_internal_fallback)
        return self._open_internal(target, sequence)

    @staticmethod
    def _sequence_with(sequence: PlaySequence | None, old: Path, new: Path) -> PlaySequence | None:
        """The same list with the moved recording named where it is now.

        The player finds its place in the list by path; left alone, a moved
        recording would no longer be in its own list and nothing would be next.
        """

        if sequence is None:
            return None
        old_key = path_key(old)
        # replace(), so the row the list was opened on stays the row it was.
        return replace(
            sequence,
            targets=tuple(
                replace(entry, path=new) if path_key(entry.path) == old_key else entry
                for entry in sequence.targets
            ),
        )

    def _open_internal(self, target: PlayTarget, sequence: PlaySequence | None, *, note: str = "") -> bool:
        self._log(f"Opening in the built-in player: {target.path}")
        # 236: a Play from anywhere opens the player as its own window, even when a page was showing it.
        self.undock()
        # Named only when there is one, so a stand-in for the window that
        # knows nothing of notes still opens every video that has none.
        said = {"note": note} if note else {}
        self._ensure_window().open_target(target, sequence=sequence, autoplay=self._autoplay(), **said)
        return True

    def _open_in_vlc(
        self,
        target: PlayTarget,
        sequence: PlaySequence | None,
        *,
        asked_for: bool,
        allow_internal_fallback: bool,
    ) -> bool:
        vlc = self._vlc_finder(str(self._settings().get(VLC_PATH_SETTING_KEY) or ""))
        if vlc and self._launch_vlc(vlc, target):
            return True
        if not vlc and not asked_for and allow_internal_fallback:
            # VLC is the usual choice and is not on this computer. Settings
            # says videos open in the built-in player until it is, so that is
            # what happens, without a question on every Play. "Play with >
            # VLC" is the operator asking for VLC by name, and is answered.
            self._log("VLC was not found; opening in the built-in player instead.")
            return self._open_internal(target, sequence, note=VLC_FALLBACK_NOTE)
        if vlc:
            title = VLC_FAILED_TITLE
            text = VLC_FAILED_TEXT if allow_internal_fallback else VLC_FAILED_FIND_ONLY_TEXT
        else:
            title = VLC_MISSING_TITLE
            text = VLC_MISSING_TEXT if allow_internal_fallback else VLC_MISSING_FIND_ONLY_TEXT
        choices = (FIND_VLC_TEXT, PLAY_HERE_TEXT) if allow_internal_fallback else (FIND_VLC_TEXT,)
        answer = self.ask_operator(title, text, choices)
        if answer == PLAY_HERE_TEXT and allow_internal_fallback:
            return self._open_internal(target, sequence)
        if answer != FIND_VLC_TEXT:
            return False
        vlc = self.browse_for_vlc()
        if not vlc:
            return False
        if self._launch_vlc(vlc, target):
            return True
        # One try with the operator's own choice, then the last word: asking
        # again and again would be a loop with no way out but Cancel.
        self.ask_operator(VLC_FAILED_TITLE, VLC_STILL_FAILED_TEXT)
        return False

    def _launch_vlc(self, vlc: str, target: PlayTarget) -> bool:
        self._quiet_the_workbench()
        command = build_vlc_command(vlc, target, autoplay=self._autoplay())
        self._log("Opening in VLC: " + " ".join(command))
        return self._launch(command)

    def _open_in_system(
        self, target: PlayTarget, sequence: PlaySequence | None, *, allow_internal_fallback: bool
    ) -> bool:
        self._quiet_the_workbench()
        # The default video app cannot be told where to start, so it is only
        # ever handed the file.
        self._log(f"Opening in the default video app: {target.path}")
        if self._desktop_opener(target.path):
            return True
        if not allow_internal_fallback:
            # The built-in player has just said it cannot play this file, so
            # there is no other player left to offer: said, with no choice.
            self.ask_operator(SYSTEM_FAILED_TITLE, SYSTEM_FAILED_TEXT)
            return False
        if self.ask_operator(SYSTEM_FAILED_TITLE, SYSTEM_FAILED_TEXT, (PLAY_HERE_TEXT,)) == PLAY_HERE_TEXT:
            return self._open_internal(target, sequence)
        return False

    def _open_missing(
        self,
        target: PlayTarget,
        player: str | None,
        sequence: PlaySequence | None,
        allow_internal_fallback: bool,
        review_copy: Path | None,
    ) -> bool:
        # The name is enough on screen; where it was goes to the log.
        self._log(f"Recording not found: {target.path}")
        text = MISSING_TEXT.format(name=target.path.name)
        choices = [FIND_IT_TEXT]
        if review_copy is not None:
            text = f"{text}\n\n{REVIEW_COPY_NOTE}"
            choices.append(PLAY_REVIEW_COPY_TEXT)
        answer = self.ask_operator(MISSING_TITLE, text, choices)
        if answer == FIND_IT_TEXT:
            found = self.browse_for_missing(target)
            if found is None:
                return False
            # Straight to the player. The operator has just pointed at the
            # file; asking whether it exists could only ask them again.
            return self._dispatch(
                replace(target, path=found),
                player,
                self._sequence_with(sequence, target.path, found),
                allow_internal_fallback,
            )
        if answer == PLAY_REVIEW_COPY_TEXT and review_copy is not None:
            # The copy plays, and everything that is about the recording
            # (never-use, skip, which transcript, what is next in the list)
            # stays about the recording it stands in for. Without that the
            # copy's own path would go on the never-use list.
            return self._dispatch(
                replace(target, path=review_copy, stands_in_for=target.recording_path),
                player,
                sequence,
                allow_internal_fallback,
            )
        return False

    def _quiet_the_workbench(self) -> None:
        # Two things playing at once cannot be judged. The built-in player is the Workbench's only
        # player since 136, so pausing it quiets the Workbench before another app plays.
        self.yield_audio()

    def _launch(self, command: list[str], **options: Any) -> bool:
        try:
            # The pipes are closed on purpose: the other program outlives this
            # call, and nothing here ever reads what it prints.
            self._process_launcher(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **options,
            )
        except OSError as exc:
            self._log(f"Could not start {command[0]}: {type(exc).__name__}: {exc}")
            return False
        return True

    def _default_desktop_opener(self, path: Path) -> bool:
        # Not the main window's own opener: that one opens the parent folder
        # when the file is missing, which is never right for a video.
        return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))

    # Messages and file dialogs --------------------------------------------------------

    def ask_operator(self, title: str, text: str, choices: Sequence[str] = ()) -> str:
        """Show one message; the caption of the button pressed, or ``""``.

        Every message this module shows comes through here, so a test that
        must not meet a modal box replaces this one method.
        """

        box = QMessageBox(self._dialog_parent())
        box.setIcon(QMessageBox.Icon.Question if choices else QMessageBox.Icon.Information)
        box.setWindowTitle(title)
        # A file name is shown as it is, whatever characters it holds.
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(text)
        offered = [(box.addButton(choice, QMessageBox.ButtonRole.ActionRole), choice) for choice in choices]
        if offered:
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(offered[0][0])
        else:
            box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        clicked = box.clickedButton()
        answer = next((choice for button, choice in offered if button is clicked), "")
        box.deleteLater()
        return answer

    def browse_for_missing(self, target: PlayTarget) -> Path | None:
        """Thin dialog wrapper; what is done with the answer is ``relocate_target``."""

        # The folder it was in is only a place to start. Whether that folder
        # is still there is for the dialog to cope with: asking here would be
        # one more wait on a drive that may be asleep.
        chosen, _selected = QFileDialog.getOpenFileName(
            self._dialog_parent(),
            f"Find {target.path.name}",
            str(target.path.parent),
            _file_name_filter(target.path.name),
        )
        return self.relocate_target(target, Path(chosen)) if chosen else None

    def relocate_target(self, target: PlayTarget, found: Path) -> Path:
        """Remember, for this session, where a recording that moved is now."""

        found = Path(found)
        self._relocations[path_key(target.path)] = found
        self._log(f"Recording found again: {target.path} is now {found}")
        return found

    def browse_for_vlc(self) -> str:
        """Thin dialog wrapper around ``set_vlc_path``; ``""`` when cancelled."""

        chosen, _selected = QFileDialog.getOpenFileName(
            self._dialog_parent(), "Find VLC", _vlc_browse_folder(), VLC_FILE_FILTER
        )
        if not chosen:
            return ""
        self.set_vlc_path(chosen)
        return chosen

    def set_vlc_path(self, vlc: str) -> bool:
        """Keep where VLC is on this PC; True when that reached the disk."""

        vlc = str(vlc).strip()
        settings = getattr(self._host, "app_settings", None)
        if isinstance(settings, MutableMapping):
            settings[VLC_PATH_SETTING_KEY] = vlc
        # The Settings page saves what its controls show. Left showing the old
        # place, its next Save would put that back over this one.
        show = getattr(getattr(self._host, "video_player_settings", None), "set_vlc_path", None)
        if callable(show):
            show(vlc)
        saver = getattr(self._host, "save_app_settings", None)
        if not callable(saver):
            return False
        try:
            saver()
        except OSError as exc:
            # Still good for this session; only the next start forgets it.
            self._log(f"Could not save where VLC is: {type(exc).__name__}: {exc}")
            return False
        return True

    def show_in_folder(self, target: PlayTarget) -> bool:
        """Open the folder that holds the recording, with it selected where possible.

        True when the request was taken. As with ``open``, the disk is asked
        away from the GUI thread and the folder opens when it has answered.
        """

        if not self._can_be_asked_for(target):
            return False
        # No package named: a review copy is of no use to a folder window, so
        # none is looked for.
        self._begin_locate(
            replace(target, package_root=None), functools.partial(self._show_located_folder, target)
        )
        return True

    def _show_located_folder(self, target: PlayTarget, result: LocateResult) -> None:
        if result.found is not None:
            if self._platform == "win32":
                # Explorer takes the file as its own argument after "/select,".
                self._launch(
                    ["explorer", "/select,", str(result.found)],
                    creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
                )
            else:
                self._desktop_opener(result.found.parent)
            return
        # The operator asked for the folder itself, so a recording that has
        # gone is no reason to refuse it. Whether the folder is still there is
        # for the computer to say when it is asked to open it.
        if not self._desktop_opener(target.path.parent):
            self.ask_operator(FOLDER_MISSING_TITLE, FOLDER_MISSING_TEXT)

    # Menus ---------------------------------------------------------------------------

    def add_menu_actions(
        self,
        menu: QMenu,
        targets: Sequence[PlayTarget],
        *,
        sequence: PlaySequence | None = None,
    ) -> None:
        """Append the play entries to ``menu``. Adds nothing for no targets."""

        self._add_actions(menu, targets, lambda: sequence)

    def build_menu(
        self,
        targets: Sequence[PlayTarget],
        parent: QWidget,
        *,
        sequence: PlaySequence | None = None,
    ) -> QMenu:
        """A menu of the play entries. The caller decides where it is shown."""

        menu = QMenu(parent)
        self.add_menu_actions(menu, targets, sequence=sequence)
        return menu

    def _add_actions(
        self,
        menu: QMenu,
        targets: Sequence[PlayTarget],
        sequence_source: Callable[[], PlaySequence | None],
    ) -> None:
        playable = [target for target in targets if isinstance(target, PlayTarget)]
        if len(playable) == 1:
            self._add_target_actions(menu, playable[0], sequence_source)
            return
        # Several recordings at once (rows selected together, or a run's
        # recordings under one button): one named entry each.
        for target in playable:
            self._add_target_actions(_add_submenu(menu, _menu_caption(target)), target, sequence_source)

    def _add_target_actions(
        self,
        menu: QMenu,
        target: PlayTarget,
        sequence_source: Callable[[], PlaySequence | None],
    ) -> None:
        def add(owner: QMenu, text: str, player: str | None) -> None:
            owner.addAction(text).triggered.connect(
                functools.partial(self._open_from_menu, target, sequence_source, player)
            )

        has_moment = target.start_seconds > 0
        if has_moment and self._chosen_player() == PLAYER_SYSTEM:
            # The default video app cannot jump to a moment. The entry says
            # so rather than promising a moment it will not reach, and the
            # built-in player is offered for the moment itself.
            add(menu, PLAY_FROM_START_TEXT, None)
            add(menu, OPEN_MOMENT_INTERNAL_TEXT, PLAYER_INTERNAL)
        else:
            add(menu, PLAY_MOMENT_TEXT if has_moment else PLAY_TEXT, None)
        play_with = _add_submenu(menu, PLAY_WITH_TEXT)
        for choice in PLAYER_CHOICES:
            add(play_with, PLAYER_NAMES[choice], choice)
        menu.addAction(SHOW_IN_FOLDER_TEXT).triggered.connect(
            functools.partial(self._show_in_folder_from_menu, target)
        )

    def _open_from_menu(
        self,
        target: PlayTarget,
        sequence_source: Callable[[], PlaySequence | None],
        player: str | None,
        _checked: bool = False,
    ) -> None:
        self.open(target, player=player, sequence=sequence_source())

    def _show_in_folder_from_menu(self, target: PlayTarget, _checked: bool = False) -> None:
        self.show_in_folder(target)

    # Views ---------------------------------------------------------------------------

    def attach(
        self,
        view: QAbstractItemView,
        resolver: Callable[[QModelIndex], Sequence[PlayTarget]],
        *,
        context_menu: bool = True,
        double_click: bool = True,
        sequence: bool = False,
        label: str = "",
        sequence_resolver: Callable[[QModelIndex], Sequence[PlayTarget]] | None = None,
        on_nothing_to_play: Callable[[QModelIndex], object] | None = None,
        ask_among_several: bool = False,
        extra_actions: Callable[[QMenu, QModelIndex], object] | None = None,
    ) -> None:
        """Give ``view`` the play entries, and double-click to play.

        ``resolver`` turns a row into what it can play, or into nothing. With
        ``sequence`` the view's rows are the list the player moves along after
        a never-use, and the list remembers which of its rows was opened.

        Double-click plays wherever a recording is shown (125). A row with
        nothing to play calls ``on_nothing_to_play`` instead, so a list whose
        double-click used to do something else still does it there. With
        ``ask_among_several`` a row that holds several recordings (a History
        run, say) asks which one, as its right-click menu does, instead of
        always opening the first. ``extra_actions`` adds a list's own entries
        to its right-click menu, after the play entries; with it a row that has
        nothing to play still gets a menu.

        A resolver used with ``sequence`` must not touch the disk. It is run
        for every row of the view, on the GUI thread, at the moment a video is
        opened; one look at a sleeping drive per row would freeze the
        Workbench. It works from what the row already holds, and leaves
        finding packages and transcripts to the player's own thread.

        Where the full ``resolver`` does have to read something (History reads
        a run's small package list when the row does not name one recording),
        pass a ``sequence_resolver`` that never does. It is used for every row
        except the one that was clicked, which has been resolved already.
        """

        sequence_source: Callable[[QModelIndex | QPersistentModelIndex], PlaySequence | None] = (
            functools.partial(self._sequence_from_view, view, resolver, label, sequence_resolver)
            if sequence
            else _no_sequence
        )
        if context_menu:
            view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            view.customContextMenuRequested.connect(
                functools.partial(self._show_view_menu, view, resolver, sequence_source, extra_actions)
            )
        if double_click:
            view.doubleClicked.connect(
                functools.partial(
                    self._open_from_view,
                    view,
                    resolver,
                    sequence_source,
                    on_nothing_to_play,
                    ask_among_several,
                )
            )

    @staticmethod
    def _resolve(
        resolver: Callable[[QModelIndex], Sequence[PlayTarget]], index: QModelIndex
    ) -> list[PlayTarget]:
        return [target for target in (resolver(index) or ()) if isinstance(target, PlayTarget)]

    def _sequence_from_view(
        self,
        view: QAbstractItemView,
        resolver: Callable[[QModelIndex], Sequence[PlayTarget]],
        label: str,
        other_rows: Callable[[QModelIndex], Sequence[PlayTarget]] | None,
        clicked: QModelIndex | QPersistentModelIndex,
    ) -> PlaySequence | None:
        """Every row of the view, in order, frozen at the moment a video opens.

        Built only when a video is really opened, never to show the menu:
        right-clicking must not cost one resolver call per row.
        """

        model = view.model()
        if model is None:
            return None
        root = view.rootIndex()
        column = view.modelColumn() if isinstance(view, QListView) else 0
        # The row that was clicked, where it is NOW: rows can arrive or go
        # while the menu is up. -1 when it has gone, or was never one of these.
        clicked_row = clicked.row() if clicked.isValid() and clicked.parent() == root else -1
        targets: list[PlayTarget] = []
        opened_at = 0
        for row in range(model.rowCount(root)):
            if row == clicked_row:
                # A place in this frozen list, not in the view. One recording
                # can be on several rows, and "next" has to go on from the
                # row that was opened, not from the first one that shows it.
                opened_at = len(targets)
            # The clicked row was resolved in full to be opened at all; every
            # other row gets the resolver that is promised never to read a disk.
            row_resolver = resolver if row == clicked_row or other_rows is None else other_rows
            targets.extend(self._resolve(row_resolver, model.index(row, column, root)))
        if opened_at >= len(targets):
            # The clicked row was the last one and now holds nothing to play.
            opened_at = 0
        # A list of one has nothing next in it.
        return PlaySequence(tuple(targets), label=label, opened_at=opened_at) if len(targets) > 1 else None

    def _show_view_menu(
        self,
        view: QAbstractItemView,
        resolver: Callable[[QModelIndex], Sequence[PlayTarget]],
        sequence_source: Callable[[QModelIndex | QPersistentModelIndex], PlaySequence | None],
        extra_actions: Callable[[QMenu, QModelIndex], object] | None,
        point: QPoint,
    ) -> None:
        index = view.indexAt(point)
        if not index.isValid():
            return
        targets = self._resolve(resolver, index)
        menu = QMenu(view)
        if targets:
            # A persistent index follows its row while the menu is up; a plain
            # one would name whatever row has that number by the time Play is
            # pressed.
            self._add_actions(menu, targets, functools.partial(sequence_source, QPersistentModelIndex(index)))
        if extra_actions is not None:
            if not menu.isEmpty():
                menu.addSeparator()
            extra_actions(menu, index)
        if menu.isEmpty():
            # Nothing on this row, so no menu: an empty one would be a small
            # grey box that answers nothing.
            menu.deleteLater()
            return
        self._exec_menu(menu, view.viewport().mapToGlobal(point))
        menu.deleteLater()

    def _exec_menu(self, menu: QMenu, where: QPoint) -> None:
        menu.exec(where)

    def _open_from_view(
        self,
        view: QAbstractItemView,
        resolver: Callable[[QModelIndex], Sequence[PlayTarget]],
        sequence_source: Callable[[QModelIndex | QPersistentModelIndex], PlaySequence | None],
        on_nothing_to_play: Callable[[QModelIndex], object] | None,
        ask_among_several: bool,
        index: QModelIndex,
    ) -> None:
        if not index.isValid():
            return
        targets = self._resolve(resolver, index)
        if not targets:
            if on_nothing_to_play is not None:
                on_nothing_to_play(index)
            return
        if ask_among_several and len(targets) > 1:
            # Which one: the same menu a right-click gives, under the row.
            menu = QMenu(view)
            self._add_actions(menu, targets, functools.partial(sequence_source, QPersistentModelIndex(index)))
            self._exec_menu(menu, view.viewport().mapToGlobal(view.visualRect(index).center()))
            menu.deleteLater()
            return
        self.open(targets[0], sequence=sequence_source(index))


def _set_status_kind(label: QLabel, kind: str) -> None:
    if label.property("statusKind") == kind:
        return
    label.setProperty("statusKind", kind)
    # The theme colours a label by this property, and a stylesheet only looks
    # at a property again when the widget is re-polished.
    label.style().unpolish(label)
    label.style().polish(label)


class VideoPlayerSettingsPanel(QWidget):
    """The "Video player" tab of Settings.

    It owns no settings. ``load`` shows what is stored and ``values`` hands
    back what is on screen; the Settings page saves that with everything else.
    """

    def __init__(
        self,
        *,
        vlc_finder: Callable[[str], str] = find_vlc,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._vlc_finder = vlc_finder
        self._vlc_path = ""
        player_meta = METADATA_BY_KEY[PLAYER_SETTING_KEY]
        autoplay_meta = METADATA_BY_KEY[AUTOPLAY_SETTING_KEY]

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        chooser = QHBoxLayout()
        chooser.addWidget(QLabel(player_meta.display_label))
        self.player_combo = WheelSafeComboBox()
        for choice in PLAYER_CHOICES:
            self.player_combo.addItem(PLAYER_COMBO_TEXT[choice], choice)
        # The entries are whole sentences. Sized to fit them, the combo would
        # set a minimum width for the entire Settings page and squeeze the
        # buttons on its other tabs at the smallest window size. Its smallest
        # and its preferred width come from a short length instead, and it
        # takes whatever width is there.
        self.player_combo.setMinimumContentsLength(16)
        self.player_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.player_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.player_combo.setToolTip(player_meta.tooltip)
        chooser.addWidget(self.player_combo, 1)
        layout.addLayout(chooser)

        self.player_note = QLabel("")
        self.player_note.setProperty("muted", True)
        self.player_note.setWordWrap(True)
        layout.addWidget(self.player_note)

        # Only there while VLC is the choice: whether VLC is installed is of
        # no interest to anyone who does not use it.
        self.vlc_row = QWidget()
        vlc_layout = QHBoxLayout(self.vlc_row)
        vlc_layout.setContentsMargins(0, 0, 0, 0)
        self.vlc_status_label = QLabel("")
        self.vlc_status_label.setWordWrap(True)
        vlc_layout.addWidget(self.vlc_status_label, 1)
        self.find_vlc_button = QPushButton(FIND_VLC_TEXT)
        self.find_vlc_button.setToolTip("Point to the VLC program yourself. It is remembered on this PC.")
        self.find_vlc_button.clicked.connect(self.browse_for_vlc)
        vlc_layout.addWidget(self.find_vlc_button)
        layout.addWidget(self.vlc_row)

        # A short caption, with the explanation beside it as a label: a label
        # wraps, and a check box with a long caption does not fit the smallest
        # window.
        self.autoplay_checkbox = QCheckBox(autoplay_meta.display_label)
        self.autoplay_checkbox.setToolTip(autoplay_meta.tooltip)
        self.autoplay_checkbox.setChecked(True)
        layout.addWidget(self.autoplay_checkbox)
        self.autoplay_note = QLabel(AUTOPLAY_OFF_NOTE)
        self.autoplay_note.setProperty("muted", True)
        self.autoplay_note.setWordWrap(True)
        layout.addWidget(self.autoplay_note)
        layout.addStretch(1)

        self.player_combo.currentIndexChanged.connect(self._on_player_chosen)
        self._refresh_for_choice()

    def load(self, settings: Mapping[str, Any]) -> None:
        """Show what ``settings`` holds. Anything unknown shows as the built-in player."""

        stored = settings if isinstance(settings, Mapping) else {}
        vlc = stored.get(VLC_PATH_SETTING_KEY)
        self._vlc_path = vlc.strip() if isinstance(vlc, str) else ""
        position = self.player_combo.findData(normalize_player_choice(stored.get(PLAYER_SETTING_KEY)))
        # Blocked while it is set: showing a stored choice is not the operator
        # making one, and the refresh below covers it.
        with QSignalBlocker(self.player_combo):
            self.player_combo.setCurrentIndex(max(0, position))
        self.autoplay_checkbox.setChecked(bool(stored.get(AUTOPLAY_SETTING_KEY, True)))
        self._refresh_for_choice()

    def values(self) -> dict[str, Any]:
        return {
            PLAYER_SETTING_KEY: normalize_player_choice(self.player_combo.currentData()),
            AUTOPLAY_SETTING_KEY: self.autoplay_checkbox.isChecked(),
            VLC_PATH_SETTING_KEY: self._vlc_path,
        }

    def set_vlc_path(self, vlc: str) -> None:
        """Where the operator says VLC is. The other choices are left as they are."""

        self._vlc_path = str(vlc).strip()
        self._refresh_for_choice()

    def browse_for_vlc(self, _checked: bool = False) -> None:
        """Thin dialog wrapper; what is done with the answer is ``set_vlc_path``."""

        chosen, _selected = QFileDialog.getOpenFileName(self, "Find VLC", _vlc_browse_folder(), VLC_FILE_FILTER)
        if chosen:
            self.set_vlc_path(chosen)

    def _on_player_chosen(self, _index: int = 0) -> None:
        self._refresh_for_choice()

    def _refresh_for_choice(self) -> None:
        choice = normalize_player_choice(self.player_combo.currentData())
        self.player_note.setText(PLAYER_NOTES[choice])
        uses_vlc = choice == PLAYER_VLC
        self.vlc_row.setVisible(uses_vlc)
        if not uses_vlc:
            return
        # Looked for only now. Finding VLC reads PATH, the disk and the
        # registry, which is nothing anyone who never picks VLC should pay for.
        found = self._vlc_finder(self._vlc_path)
        self.vlc_status_label.setText(VLC_FOUND_TEXT if found else VLC_NOT_FOUND_TEXT)
        # The place it was found is a tooltip: useful to check, too long to show.
        self.vlc_status_label.setToolTip(str(found or ""))
        _set_status_kind(self.vlc_status_label, "" if found else "attention")
