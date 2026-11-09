"""The built-in player: watch a recording, read what was said, judge it (125).

One window, made once and reused for every recording. It shows the picture, a
timeline with a mark for every transcript line, the line being spoken at the
playhead (including the lines the transcript filter left out, and why), a
choice of which audio track to hear, and a one-click way to put the recording
on the never-use list.

Three rules shape the code, each one learned by measuring a real multi-hour
recording before any of this was written:

* A fresh player per recording, and every report from a player carries the
  number of the player it was made for. A player that has been replaced can
  still deliver a late report; without the number it would move the screen for
  a recording that is no longer open.
* Seeks take turns. A player asked to move on every mouse move of a drag shows
  no picture at all, because each request throws away the frame the last one
  was about to show.
* A seek asked for while the recording is still loading is silently dropped.
  The starting moment is therefore kept back until the player says it is ready.

The window has the Workbench's one sound output for playing recordings (136:
the New Review wizard's own preview player was folded into this one), and
nothing in here asks the operator a question that could stop the main window
closing.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass, replace
import functools
import json
import math
from pathlib import Path, PurePath
import re
import time
from typing import Any

from PySide6.QtCore import QByteArray, QEvent, QObject, QSignalBlocker, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaMetaData, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from media_manglers.core.activity_timeline import sound_stretches
from media_manglers.core.track_levels import MAX_TRACKS

from .audio_widgets import TimelineBar, TrackLanes, format_hms
from .play_targets import (
    NEXT_END_OF_LIST,
    NEXT_FOUND,
    PLAYER_SYSTEM,
    PLAYER_VLC,
    PlaySequence,
    PlayTarget,
    next_target,
)
from .recording_lists import (
    add_excluded,
    excluded_keys,
    in_library,
    lists_of,
    path_key,
    processed_on,
    recording_status_text,
    remove_excluded,
)
from .review_package import (
    KIND_KEPT,
    KIND_REJECTED_SPAN,
    SHOW_ALL,
    SHOW_KEPT,
    SHOW_LEFT_OUT,
    START_MATCH_SECONDS,
    Moment,
    RecordingTranscript,
    TranscriptLine,
    find_package_for_recording,
    line_index_at,
    load_moments,
    load_transcript,
    next_line_index,
    previous_line_index,
    visible_lines,
)
from .track_roles import ROLE_CHOICES, SETTING_KEY as TRACK_ROLES_KEY, parse_roles
from .widgets import WheelSafeComboBox
from . import theme as ui_theme
from .ui_parts import FlowLayout, InlineFeedback, bind_action

WINDOW_TITLE = "Built-in player"
LEGEND_TEXT = "Space play or pause  ·  Up/Down previous or next line  ·  Left/Right 5 seconds  ·  W waveforms"

LOOKING_FOR_TRANSCRIPT_TEXT = "Looking for a transcript…"
NO_TRANSCRIPT_TEXT = "No transcript found for this recording. Run Find my bug reports on it to get one."
NO_AUDIT_TEXT = "This package was made before left-out lines were recorded."
NO_RESCUE_RECORD_TEXT = "This package does not say which lines were kept only for sitting next to real speech."
UNKNOWN_MODE_TEXT = "This package does not say whether any filtering ran."
UNPLAYABLE_TEXT = "The built-in player can't play this file."
# Just after a Next / Previous jump a long recording can still report the place it left for a moment
# (220); within this long, a position that close to that old place counts as the jump's target.
STRETCH_JUMP_SETTLE_SECONDS = 3.0
STRETCH_JUMP_STALE_SECONDS = 2.0
PACKAGE_FILE_TRANSCRIPT_TEXT = (
    "This is a clip or a small copy from a package, so there is no transcript to show for it."
)
RELEASED_TRANSCRIPT_TEXT = "The transcript will be looked for again when you press Play."

BADGE_LEFT_OUT = "Left out"
BADGE_RESCUED = "Kept — it sits next to real speech"
BADGE_RESCUED_TOOLTIP = (
    "The transcriber was unsure of this line. It was kept only because it sits next to real speech."
)
BADGE_SPOTTER = "Sounds like the spotter, not you"

NEVER_USE_TEXT = "Never use this recording"
ALLOW_AGAIN_TEXT = "Allow again"
# 244: who set or took off a never-use mark, as the library keeps it.
PLAYER_NAME = "Built-in player"
PACKAGE_FILE_STATUS_TEXT = "A clip or a small copy from a package"
PACKAGE_FILE_NEVER_USE_TOOLTIP = (
    "This is a clip or a small copy made for a package, not one of your recordings, "
    "so it cannot be marked never-use."
)
SKIP_TEXT = "Skip this recording"
SKIP_TOOLTIP = "Skips it in the run that is going now. This cannot be taken back for this run."
SAVE_FAILED_TEXT = "Could not save that — try again"
NO_LIST_TEXT = "Marked never-use. There is nothing next — this recording was opened on its own."
END_OF_LIST_TEXT = "Marked never-use. That was the last recording in this list."
STEP_FORWARD_TOOLTIP = "Moves forward a frame or two."

GEOMETRY_KEY = "review_player_geometry"
VOLUME_KEY = "review_player_volume"
AUTOPLAY_KEY = "video_autoplay"
# 125 Part 2: whether the waveform lanes are shown, remembered for the operator; shown by default.
WAVEFORMS_KEY = "review_player_waveforms"
# 125 Part 2: the lanes' right-click.
MEASURE_AGAIN_TEXT = "Measure the sound again"
# A clip or a small review copy has one track that is not the recording's, so it has no lanes: the
# Waveforms button is greyed out and W says why.
NO_WAVEFORMS_CLIP_TEXT = "No waveforms for a clip from a package. Open the recording itself to see every track."
NO_WAVEFORMS_REVIEW_COPY_TEXT = "No waveforms for a small review copy. Open the recording itself to see every track."
MEASURE_AGAIN_LIBRARY_TOOLTIP = (
    "These waveforms come from the Raw bin's scan of this recording. The Raw bin measures them again "
    "by itself when the recording changes."
)
DEFAULT_VOLUME = 0.8
_ROLE_WORDS = dict(ROLE_CHOICES)

JUMP_MS = 5_000
# The line being spoken is read at a glance from across the desk.
CURRENT_LINE_POINT_SIZE = 14
# Used for Step back when the recording does not say how fast its picture runs.
FALLBACK_FRAME_MS = 33
# Step forward plays until the next picture arrives. At the very end of a
# recording none does, and the player must not be left running.
STEP_TIMEOUT_MS = 500
# Only the newest runs are asked about a recording; each one costs a disk read.
MAX_RECENT_RUN_HINTS = 30
# The size a first-time window opens at, and what is left free around it for
# the title bar and the window's edges when the screen is smaller than that.
DEFAULT_WINDOW_SIZE = QSize(1100, 860)
WINDOW_FRAME_ALLOWANCE = QSize(16, 48)

# Every player signal the window listens to. ``_create_player`` connects each
# one and ``_retire_player`` disconnects each one; a test keeps the two equal.
_PLAYER_SIGNALS = (
    "positionChanged",
    "durationChanged",
    "playbackStateChanged",
    "mediaStatusChanged",
    "errorOccurred",
    "tracksChanged",
)

# Recorders name a track "Track1" when nobody gave it a name. Repeating that
# after "Track 1" tells the operator nothing.
_TITLE_IS_ONLY_A_NUMBER = re.compile(r"^\s*track\s*[-_#]?\s*\d+\s*$", re.IGNORECASE)

_FILTER_CHOICES = (
    ("All lines", SHOW_ALL),
    ("Kept only", SHOW_KEPT),
    ("Left out only", SHOW_LEFT_OUT),
)
_SPEED_CHOICES = (("1x", 1.0), ("2x", 2.0), ("4x", 4.0))

_READY_STATUSES = (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia)

# A loader thread that shutdown() gave up waiting for is parked here until it
# finishes. A thread object that is destroyed while it is still running ends
# the whole process, and the window that owned it may be gone by then.
_PARKED_THREADS: set[QThread] = set()


def _park_thread(thread: QThread) -> None:
    if thread not in _PARKED_THREADS:
        _PARKED_THREADS.add(thread)
        thread.finished.connect(functools.partial(_PARKED_THREADS.discard, thread))


def _set_property(widget: QWidget, name: str, value: str) -> None:
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    # The theme picks colours from these properties, and a stylesheet only
    # looks at a property again when the widget is re-polished.
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _line_start_ms(line: TranscriptLine) -> int:
    # Rounded up so the playhead lands ON the line, never a hair before it
    # (which would read as "between lines"). The inner round removes float
    # noise first, so 12.3 s is 12300 ms and not 12301.
    return math.ceil(round(line.start * 1000, 3))


VIDEO_MINIMUM_HEIGHT = 140
# The transcript lines' height, and the least they give up to on a short window (125 Part 2).
LINES_HEIGHT = 150
LINES_MIN_HEIGHT = 66


class _TellingLayout(QVBoxLayout):
    """A box's layout that tells the window at once when what it holds needs another size (236): the
    rows it holds were the window's own rows before, and the window measured them straight away."""

    def invalidate(self) -> None:
        super().invalidate()
        holder = self.parentWidget()
        if holder is not None:
            holder.updateGeometry()


class _LinesArea(QScrollArea):
    """The transcript lines' scroll area. It always asks for its full height, whatever the lines
    say, so a change of text never moves the picture; only a short window makes it smaller."""

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(super().sizeHint().width(), LINES_HEIGHT)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(super().minimumSizeHint().width(), LINES_MIN_HEIGHT)
# 125 Part 2: Next / Previous sound and moment count from just after the place they land.
JUMP_MARGIN_SECONDS = 0.5
# Previous moment within this long after a moment goes to the one before it.
RESTART_MOMENT_SECONDS = 1.5


def _resolved_text(path: Path | str, resolve: Callable[[Path], Path] = Path.resolve) -> str:
    """The path spelled the way Find my bug reports spells it: resolved.

    That page only ever compares resolved paths against the never-use list.
    A recording stored here as a view happened to spell it (a mapped drive
    letter, a folder reached through a link) would say "never-use" in this
    window and still be offered there.
    """

    try:
        return str(resolve(Path(path)))
    except (OSError, RuntimeError, ValueError):
        # A drive that has gone away, a loop of links, a name Windows will
        # not take. The spelling that was given is the best there is.
        return str(path)


def _number_lines(numbers: tuple[tuple[str, float], ...]) -> list[str]:
    """The transcriber's scores for one line, in words the operator can judge.

    The package names them the way the transcriber does; none of those names,
    and no bare negative figure, means anything on screen.
    """

    lines: list[str] = []
    for name, value in numbers:
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            continue
        if name == "no_speech_prob":
            lines.append(f"Chance nobody was speaking: {max(0.0, min(1.0, value)):.0%}")
        elif name == "avg_logprob":
            # The closer to 0 the surer it was. -0.6 is where the transcript
            # filter starts to doubt a line; the figure stays for comparing.
            sure = "high" if value >= -0.3 else "medium" if value >= -0.6 else "low"
            lines.append(f"How sure it was of the words: {sure} ({value:.2f})")
        elif name == "compression_ratio":
            lines.append(f"How much it repeated itself: {value:.2f} (above 2.4 means it was looping)")
        # A score this window has no words for is left out, not shown by its
        # file name.
    return lines


class SeekCoalescer(QObject):
    """Lets one seek finish before the next one is sent to the player.

    Measured on a real recording: a drag that seeks on every mouse move shows
    0 pictures a second, because each request cancels the frame the one before
    was about to show. One request at a time, always followed by the NEWEST
    one that came in meanwhile, shows about 3 a second.

    A seek counts as finished when a frame close to its target arrives. If
    none does (the end of the recording, a sound-only file) the timeout lets
    the next request through, so the player can never get stuck.
    """

    def __init__(
        self,
        set_position: Callable[[int], None],
        *,
        timeout_ms: int = 700,
        tolerance_ms: int = 100,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._set_position = set_position
        self._tolerance_ms = max(0, int(tolerance_ms))
        self._in_flight: int | None = None
        self._pending: int | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(max(1, int(timeout_ms)))
        self._timer.timeout.connect(self._release)

    def request(self, milliseconds: int) -> None:
        target = max(0, int(milliseconds))
        if self._in_flight is None:
            self._issue(target)
            return
        # Only the newest request matters; the ones in between were places
        # the mouse passed through. Asking again for the place already being
        # fetched adds nothing, so that clears the queue instead.
        self._pending = None if target == self._in_flight else target

    def frame_arrived(self, frame_start_ms: float) -> None:
        if self._in_flight is None:
            return
        try:
            moment = float(frame_start_ms)
        except (TypeError, ValueError):
            return
        # A frame from before the jump is still on its way when the seek is
        # sent. Counting it would let the next request through too early and
        # bring the flood back.
        if not math.isfinite(moment) or abs(moment - self._in_flight) > self._tolerance_ms:
            return
        self._release()

    def requested_ms(self) -> int | None:
        """Where the operator last asked to be, while any seek is unfinished."""

        return self._pending if self._pending is not None else self._in_flight

    def reset(self) -> None:
        self._timer.stop()
        self._in_flight = None
        self._pending = None

    def _issue(self, target: int) -> None:
        # Marked as in flight BEFORE the player is asked: a player may report
        # the new position from inside setPosition, and that report has to
        # find the request it answers.
        self._in_flight = target
        self._timer.start()
        self._set_position(target)

    def _release(self) -> None:
        self._timer.stop()
        pending, self._pending = self._pending, None
        self._in_flight = None
        if pending is not None:
            self._issue(pending)


class PackageLoadThread(QThread):
    """Finds the package that holds a recording's transcript and reads it.

    Packages sit on the same slow disks as the recordings, so none of this may
    run on the GUI thread. Everything the thread needs is handed over as plain
    values; it never looks at the window, the host or the settings.
    """

    loaded = Signal(int, object)  # generation, RecordingTranscript | None
    failed = Signal(int, str)  # generation, details for the log
    # 125 Part 2: generation, the moments the package found in this recording (sent after ``loaded``).
    moments_found = Signal(int, object)

    def __init__(
        self,
        generation: int,
        recording: Path,
        package_root: Path | None,
        hints: list[str],
        duration_seconds: float | None,
    ) -> None:
        super().__init__()
        self.generation = generation
        self.recording = Path(recording)
        self.package_root = Path(package_root) if package_root else None
        self.hints = [str(hint) for hint in hints]
        self.duration_seconds = duration_seconds
        self._cancel_requested = False
        self._found_root: Path | None = None

    def cancel(self) -> None:
        # Qt ignores an interruption request made before the thread is really
        # running, so the wish to stop is remembered here as well.
        self._cancel_requested = True
        self.requestInterruption()

    def _cancelled(self) -> bool:
        return self._cancel_requested or self.isInterruptionRequested()

    def run(self) -> None:
        # Exactly one of the two signals, whatever happens. The window shows
        # "Looking for a transcript…" until one arrives, so a thread that died
        # quietly would leave that on screen for good.
        try:
            transcript = self._find_and_load()
            moments = self._moments_for(transcript)
        except Exception as exc:  # noqa: BLE001 - see above
            self.failed.emit(self.generation, f"{type(exc).__name__}: {exc}")
            return
        self.loaded.emit(self.generation, transcript)
        self.moments_found.emit(self.generation, moments)

    def _moments_for(self, transcript: RecordingTranscript | None) -> tuple[Moment, ...]:
        # The package that gave the transcript, else the one that lists the recording without one.
        root = transcript.package_root if transcript is not None else self._found_root
        if root is None or self._cancelled():
            return ()
        try:
            return load_moments(root, self.recording, duration_seconds=self.duration_seconds)
        except Exception:  # noqa: BLE001 - a package's odd moments never cost the transcript
            return ()

    def _find_and_load(self) -> RecordingTranscript | None:
        self._found_root = self.package_root
        if self.package_root is not None and not self._cancelled():
            transcript = load_transcript(
                self.package_root, self.recording, duration_seconds=self.duration_seconds
            )
            if transcript is not None:
                return transcript
        if self._cancelled():
            return None
        # Runs can share an output folder, so the package named by a History
        # row may since have been replaced. Every other package the app knows
        # of is asked too; each is checked against its own manifest, so a
        # wrong one is never shown.
        named = str(self.package_root) if self.package_root is not None else ""
        root = find_package_for_recording(
            self.recording,
            [hint for hint in self.hints if hint != named],
            duration_seconds=self.duration_seconds,
            cancelled=self._cancelled,
        )
        if root is None or self._cancelled():
            return None
        self._found_root = root
        return load_transcript(root, self.recording, duration_seconds=self.duration_seconds)


@dataclass(frozen=True, slots=True)
class _NeverUseUndo:
    """What Undo needs to put a never-use recording back on screen."""

    target: PlayTarget
    position_ms: int
    sequence: PlaySequence | None
    # What the banner said, so it can be put back after something else
    # (a complaint about a failed save) has borrowed the banner.
    message: str = ""


class ReviewPlayerWindow(QWidget):
    """The built-in player window. ``host`` and ``opener`` are duck-typed.

    ``host`` is read at call time and never cached: ``app_settings``,
    ``save_app_settings()``, and when present
    ``bug_reports_page``, ``current_package``, ``levels_service`` (125 Part 2:
    the waveforms, measured in the background), ``runner_thread`` and
    ``skip_run_sources``. ``opener`` only needs
    ``open(target, player=..., allow_internal_fallback=...)``.
    """

    never_use_requested = Signal(str)  # the recording's path, once it is on the saved list
    diagnostic = Signal(str)  # details for the log; never shown on screen
    # 220: the recording's path and the 1-based track now playing, sent once the recording has loaded
    # and whenever the heard track changes. A recording that cannot load never sends it.
    track_heard = Signal(str, int)
    # 136: the recording's path, when this window cannot play it (the New Review wizard's preview says so).
    cannot_play = Signal(str)

    def __init__(
        self,
        host: Any,
        opener: Any,
        *,
        video_surface_factory: Callable[[], QWidget] | None = None,
        player_factory: Callable[[], Any] | None = None,
        audio_output_factory: Callable[[], Any] | None = None,
        path_resolver: Callable[[Path], Path] | None = None,
    ) -> None:
        # No Qt parent: a child window would stay on top of the main window
        # and would be walked by the main window's layout checks.
        super().__init__(None)
        self._ui_ready = False
        # Closing the main window must end the app even while this one is open.
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle(WINDOW_TITLE)
        # 237: the player is a dense toolbar (UI rulebook section 5): its buttons use the compact size.
        self.setObjectName("reviewPlayer")
        self._host = host
        self._opener = opener
        self._player_factory = player_factory or self._default_player
        self._resolve_path = path_resolver or Path.resolve
        # Resolving a path reads the disk, so each recording is resolved once.
        self._resolved_texts: dict[str, str] = {}
        # What the never-use button's caption currently says; the click obeys it.
        self._row_shows_excluded = False
        self._fallback_settings: dict[str, Any] = {}

        self._player: Any | None = None
        self._player_generation = 0
        self._target: PlayTarget | None = None
        # The stretch the last Next / Previous jumped to, and when (220): just after a seek a long
        # recording can still report its old place, so a quick second press counts from the jump.
        self._stretch_jump: tuple[float, float, float] | None = None  # (target, old place, when)
        self._sequence: PlaySequence | None = None
        self._media_ready = False
        self._unplayable = False
        # The starting moment and the play-or-pause decision wait here until
        # the player reports the recording as loaded (see _apply_queued_start).
        self._pending_start_ms = 0
        self._pending_autoplay = False
        # Said in the status line once the recording is open (see open_target).
        self._pending_note = ""
        self._resume_after_scrub = False
        self._step_pending = False
        self._step_from_ms = 0.0
        self._last_frame_ms: float | None = None
        self._muted_before_step = False
        # Where a released recording was, so Play can pick it up again.
        self._resume_ms = 0

        self._transcript: RecordingTranscript | None = None
        self._lines: list[TranscriptLine] = []
        self._line_starts: list[float] = []
        # The stretch of the recording the transcript panel is already right
        # for, so the per-frame clock costs nothing while a line is spoken.
        self._panel_valid: tuple[float, float] | None = None
        self._package_threads: set[PackageLoadThread] = set()
        # Transcript lookups are numbered on their own, not with the player's
        # number: one recording can be looked up twice (a package named later),
        # and the first lookup's late answer must not replace the second's.
        self._package_generation = 0
        self._package_lookup_running = False

        self._undo: _NeverUseUndo | None = None
        self._skipped_keys: set[str] = set()
        # 212, 220: the player starts on the track to hear, or on the transcript's track, until the
        # operator picks one; their pick then always wins.
        self._operator_chose_track = False
        # 220, 125 Part 2: each track's level per second (track number -> dB values), for the lanes and
        # Next / Previous sound; and the moments the package found in this recording.
        self._levels: dict[int, list[float]] = {}
        self._levels_duration = 0.0
        self._sounds: tuple[int, int, list[tuple[int, int]]] | None = None  # (track, seconds known, stretches)
        self._moments: tuple[Moment, ...] = ()
        self._levels_service: Any | None = None
        # 264: why there is no Next speech, and whether the stretches came from the speech facts.
        self._no_speech_reason = ""
        self._finer_stretches = False
        # 236: the page area the player is shown in instead of its own window (``dock_into``), or None.
        self.docked_in: QWidget | None = None

        # The window's OWN sound output, made by the window and never shared:
        # a volume change here changes nothing else in the Workbench.
        self.audio_output = (audio_output_factory or self._default_audio_output)()
        self.audio_output.setVolume(self._stored_volume())

        self._coalescer = SeekCoalescer(self._set_player_position, parent=self)
        self._step_timer = QTimer(self)
        self._step_timer.setSingleShot(True)
        self._step_timer.setInterval(STEP_TIMEOUT_MS)
        self._step_timer.timeout.connect(self._finish_step)

        self._build_ui(video_surface_factory or QVideoWidget)
        self._build_actions()
        self._ui_ready = True

        self.resize(self._first_size())
        self._restore_geometry()
        self._show_no_recording()

    # Construction ---------------------------------------------------------------

    def _first_size(self) -> QSize:
        # Never taller or wider than the screen can show: on a small or a
        # scaled-up screen the default would put the legend and the This
        # recording row off the bottom, where they cannot be reached.
        screen = self.screen()
        if screen is None:
            return DEFAULT_WINDOW_SIZE
        room = screen.availableGeometry().size() - WINDOW_FRAME_ALLOWANCE
        return DEFAULT_WINDOW_SIZE.boundedTo(room)

    def _default_player(self) -> QMediaPlayer:
        return QMediaPlayer(self)

    def _default_audio_output(self) -> QAudioOutput:
        # Bound to the default device explicitly: the parent-only form gave no
        # sound on a Windows test machine (136). A PC with no sound
        # device at all reports a null one, and the player must still open there.
        device = QMediaDevices.defaultAudioOutput()
        return QAudioOutput(device, self) if not device.isNull() else QAudioOutput(self)

    def _build_ui(self, surface_factory: Callable[[], QWidget]) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(6)

        self.video_surface = surface_factory()
        # Small enough that the whole window - down to the never-use row and the
        # key legend - still fits on a 1366x768 laptop. The picture takes all
        # the spare height on anything bigger.
        self.video_surface.setMinimumHeight(VIDEO_MINIMUM_HEIGHT)
        # Spare window height goes to the picture, nowhere else.
        self.video_surface.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        keep_aspect = getattr(self.video_surface, "setAspectRatioMode", None)
        if callable(keep_aspect):
            keep_aspect(Qt.AspectRatioMode.KeepAspectRatio)
        self.video_stack = QStackedWidget()
        self.video_stack.addWidget(self.video_surface)
        self.video_stack.addWidget(self._build_unplayable_card())
        root.addWidget(self.video_stack, 1)

        # The surface outlives every player, so its frames are listened to
        # once, here, and not per player. Frame times are what tell the seek
        # queue that a seek has really finished.
        sink_getter = getattr(self.video_surface, "videoSink", None)
        self._video_sink = sink_getter() if callable(sink_getter) else None
        if self._video_sink is not None:
            self._video_sink.videoFrameChanged.connect(self._on_video_frame)

        self.timeline = TimelineBar()
        self.timeline.seek_requested.connect(self._on_timeline_seek)
        self.timeline.scrub_started.connect(self._on_scrub_started)
        self.timeline.scrub_finished.connect(self._on_scrub_finished)
        self.timeline.moment_clicked.connect(self._on_moment_clicked)
        root.addWidget(self.timeline)

        # 125 Part 2 (Wave 8): one lane per audio track across the whole recording, the heard track
        # highlighted, from levels the shared levels job measured (never read from the recording on
        # this thread). A click on a lane moves there; a click on a track's name hears that track.
        self.track_lanes = TrackLanes()
        self.track_lanes.seek_requested.connect(self._on_lanes_seek)
        self.track_lanes.lane_chosen.connect(self._on_lane_chosen)
        self.track_lanes.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.track_lanes.customContextMenuRequested.connect(self._show_lanes_menu)
        self.track_lanes.hide()
        root.addWidget(self.track_lanes)

        root.addLayout(self._build_transport_row())
        root.addLayout(self._build_sound_row())
        # 236: what is about a recording, not about watching (its transcript, the line controls, never-use),
        # in one box, so a page that shows the player for its own video can leave it out (``dock_into``).
        self.details_box = QWidget()
        self.details_box.setObjectName("reviewPlayerDetails")
        details = _TellingLayout(self.details_box)
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(root.spacing())
        details.addWidget(self._build_transcript_panel())
        details.addLayout(self._build_line_row())
        details.addWidget(self._build_undo_banner())
        details.addLayout(self._build_recording_row())
        root.addWidget(self.details_box)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        self.legend_label = QLabel(LEGEND_TEXT)
        self.legend_label.setProperty("muted", True)
        self.legend_label.setWordWrap(True)
        root.addWidget(self.legend_label)

    def _build_unplayable_card(self) -> QWidget:
        self.unplayable_card = QFrame()
        self.unplayable_card.setProperty("card", True)
        layout = QVBoxLayout(self.unplayable_card)
        layout.addStretch(1)
        self.unplayable_label = QLabel(UNPLAYABLE_TEXT)
        self.unplayable_label.setProperty("sectionTitle", True)
        self.unplayable_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.unplayable_label.setWordWrap(True)
        layout.addWidget(self.unplayable_label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.open_in_vlc_button = QPushButton("Open in VLC")
        buttons.addWidget(self.open_in_vlc_button)
        self.open_in_default_button = QPushButton("Open in the default video app")
        buttons.addWidget(self.open_in_default_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        # 237: another program can take a few seconds to appear; the line says it is on its way.
        self.open_elsewhere_feedback = InlineFeedback()
        self.open_elsewhere_feedback.setObjectName("playerOpenElsewhereFeedback")
        layout.addWidget(self.open_elsewhere_feedback, alignment=Qt.AlignmentFlag.AlignHCenter)
        for button, choice, done in ((self.open_in_vlc_button, PLAYER_VLC, "Opening in VLC"),
                                     (self.open_in_default_button, PLAYER_SYSTEM, "Opening in your video app")):
            bind_action(button, functools.partial(self._open_elsewhere, choice), working="Opening…", done=done,
                        feedback=self.open_elsewhere_feedback)
        layout.addStretch(1)
        return self.unplayable_card

    def _build_transport_row(self) -> FlowLayout:
        # 237: wraps when the window is narrow, so the text size never pushes the player wider than a
        # small screen.
        row = FlowLayout()
        self.step_back_button = QPushButton("Step back")
        self.play_button = QPushButton("Play")
        self.play_button.setProperty("primary", True)
        self.step_forward_button = QPushButton("Step forward")
        self.back_five_button = QPushButton("-5 s")
        self.forward_five_button = QPushButton("+5 s")
        # 220: jump between the stretches the raw bin found (speech, or active driving).
        self.previous_stretch_button = QPushButton("Previous stretch")
        self.next_stretch_button = QPushButton("Next stretch")
        # 125 Part 2: show or hide the waveform lanes, at any time, even while playing.
        self.waveforms_button = QPushButton("Waveforms")
        for button in (
            self.step_back_button,
            self.play_button,
            self.step_forward_button,
            self.back_five_button,
            self.forward_five_button,
            self.previous_stretch_button,
            self.next_stretch_button,
            self.waveforms_button,
        ):
            row.addWidget(button)
        self.previous_stretch_button.hide()
        self.next_stretch_button.hide()
        self.time_label = QLabel("0:00:00 / 0:00:00")
        self.time_label.setProperty("accent", True)
        row.addWidget(self.time_label)
        return row

    def _build_sound_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Speed"))
        self.speed_combo = WheelSafeComboBox()
        for text, rate in _SPEED_CHOICES:
            self.speed_combo.addItem(text, rate)
        self.speed_combo.setToolTip("How fast the recording plays.")
        self.speed_combo.currentIndexChanged.connect(self._on_speed_chosen)
        row.addWidget(self.speed_combo)

        row.addSpacing(8)
        row.addWidget(QLabel("Volume"))
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setFixedWidth(120)
        self.volume_slider.setValue(round(self._stored_volume() * 100))
        self.volume_slider.setToolTip("How loud the built-in player is. Nothing else in the Workbench changes.")
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        row.addWidget(self.volume_slider)

        row.addSpacing(8)
        self.hear_label = QLabel("Hear:")
        row.addWidget(self.hear_label)
        self.track_combo = WheelSafeComboBox()
        self.track_combo.setMinimumWidth(180)
        self.track_combo.setToolTip("Which of the recording's audio tracks you hear.")
        self.track_combo.setEnabled(False)
        self.track_combo.currentIndexChanged.connect(self._on_track_chosen)
        row.addWidget(self.track_combo, 1)
        # 125 Part 2: jump between the sounds on the track you hear.
        self.previous_sound_button = QPushButton("Previous sound")
        self.next_sound_button = QPushButton("Next sound")
        for button in (self.previous_sound_button, self.next_sound_button):
            button.hide()
            row.addWidget(button)
        # 236: the spare room when the track box is not shown (on a page), so nothing else stretches.
        row.addStretch(0)
        return row

    def _build_transcript_panel(self) -> QWidget:
        panel = QFrame()
        panel.setProperty("card", True)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        self.transcript_header = QLabel("")
        self.transcript_header.setProperty("muted", True)
        self.transcript_header.setWordWrap(True)
        layout.addWidget(self.transcript_header)

        track_row = QHBoxLayout()
        self.track_explanation_label = QLabel("")
        self.track_explanation_label.setWordWrap(True)
        track_row.addWidget(self.track_explanation_label, 1)
        self.hear_track_button = QPushButton("Hear this track")
        self.hear_track_button.setToolTip("Switches the sound to the track this transcript was made from.")
        self.hear_track_button.clicked.connect(self._hear_transcribed_track)
        track_row.addWidget(self.hear_track_button)
        layout.addLayout(track_row)

        self.transcript_note = QLabel("")
        self.transcript_note.setWordWrap(True)
        layout.addWidget(self.transcript_note)

        # The lines live in a scroll area of a fixed height. Their text changes
        # many times a minute; without this every change would resize the
        # panel and make the picture above it jump.
        lines_widget = QWidget()
        lines_layout = QVBoxLayout(lines_widget)
        lines_layout.setContentsMargins(0, 0, 0, 0)
        lines_layout.setSpacing(3)
        self.previous_line_label = QLabel("")
        self.previous_line_label.setProperty("muted", True)
        self.previous_line_label.setWordWrap(True)
        lines_layout.addWidget(self.previous_line_label)

        badge_row = QHBoxLayout()
        self.line_time_label = QLabel("")
        self.line_time_label.setProperty("muted", True)
        badge_row.addWidget(self.line_time_label)
        self.line_badge_label = QLabel("")
        badge_row.addWidget(self.line_badge_label)
        badge_row.addStretch(1)
        lines_layout.addLayout(badge_row)

        self.current_line_label = QLabel("")
        self.current_line_label.setWordWrap(True)
        # Large through a stylesheet of its own, not setFont(): the theme's
        # stylesheet fixes every widget at 10pt, and a font set in code loses
        # to it. Colour is left to the theme, so the amber still applies.
        # 237: the line being said follows the text size like every other word.
        ui_theme.keep_scaled(self, "_set_current_line_point_size", CURRENT_LINE_POINT_SIZE)
        lines_layout.addWidget(self.current_line_label)

        self.line_reason_label = QLabel("")
        self.line_reason_label.setProperty("statusKind", "attention")
        self.line_reason_label.setWordWrap(True)
        lines_layout.addWidget(self.line_reason_label)
        self.line_numbers_label = QLabel("")
        self.line_numbers_label.setProperty("muted", True)
        self.line_numbers_label.setWordWrap(True)
        lines_layout.addWidget(self.line_numbers_label)

        self.next_line_label = QLabel("")
        self.next_line_label.setProperty("muted", True)
        self.next_line_label.setWordWrap(True)
        lines_layout.addWidget(self.next_line_label)
        lines_layout.addStretch(1)

        self.lines_scroll = _LinesArea()
        self.lines_scroll.setWidgetResizable(True)
        self.lines_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.lines_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 125 Part 2 (Wave 8): its full height everywhere but on a short window (a 1366x768 laptop),
        # where it gives some up so the rows below stay on screen; it scrolls there.
        self.lines_scroll.setMinimumHeight(LINES_MIN_HEIGHT)
        self.lines_scroll.setMaximumHeight(LINES_HEIGHT)
        self.lines_scroll.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.lines_scroll.setWidget(lines_widget)
        layout.addWidget(self.lines_scroll)
        return panel

    def _build_line_row(self) -> FlowLayout:
        # 237: the row wraps when the window is narrow, so the text size never pushes the player wider
        # than a small screen.
        row = FlowLayout()
        self.line_filter_combo = WheelSafeComboBox()
        for text, show in _FILTER_CHOICES:
            self.line_filter_combo.addItem(text, show)
        self.line_filter_combo.setToolTip(
            "Which lines are shown, marked on the timeline and visited by Previous line and Next line."
        )
        self.line_filter_combo.currentIndexChanged.connect(self._on_filter_chosen)
        row.addWidget(self.line_filter_combo)
        self.previous_line_button = QPushButton("Previous line")
        row.addWidget(self.previous_line_button)
        self.next_line_button = QPushButton("Next line")
        row.addWidget(self.next_line_button)
        # 125 Part 2: jump between the moments the package found.
        self.previous_moment_button = QPushButton("Previous moment")
        self.next_moment_button = QPushButton("Next moment")
        for button in (self.previous_moment_button, self.next_moment_button):
            button.hide()
            row.addWidget(button)
        self.show_numbers_checkbox = QCheckBox("Show the numbers")
        self.show_numbers_checkbox.setToolTip(
            "Shows the transcriber's own scores for the line — the chance nobody was speaking, how sure "
            "it was of the words and how much it repeated itself — and its wording before your glossary "
            "was applied."
        )
        self.show_numbers_checkbox.toggled.connect(self._on_show_numbers_toggled)
        row.addWidget(self.show_numbers_checkbox)
        return row

    def _build_undo_banner(self) -> QWidget:
        self.undo_banner = QFrame()
        row = QHBoxLayout(self.undo_banner)
        row.setContentsMargins(0, 0, 0, 0)
        self.banner_label = QLabel("")
        self.banner_label.setWordWrap(True)
        row.addWidget(self.banner_label, 1)
        self.undo_button = QPushButton("Undo")
        self.undo_button.setToolTip("Allows the recording again and reopens it, paused, where you stopped.")
        self.undo_button.clicked.connect(self.undo_never_use)
        row.addWidget(self.undo_button)
        self.undo_banner.hide()
        return self.undo_banner

    def _build_recording_row(self) -> FlowLayout:
        # 237: wraps when the window is narrow, like the transport row.
        row = FlowLayout()
        row.addWidget(QLabel("This recording:"))
        self.recording_status_label = QLabel("")
        row.addWidget(self.recording_status_label)
        # 264: the one calm line when your answer for this recording differs from what the app heard.
        self.choice_label = QLabel("")
        self.choice_label.setObjectName("reviewPlayerChoiceLine")
        self.choice_label.setVisible(False)
        row.addWidget(self.choice_label)
        self.never_use_button = QPushButton(NEVER_USE_TEXT)
        self.never_use_button.clicked.connect(self._never_use_or_allow)
        row.addWidget(self.never_use_button)
        self.skip_button = QPushButton(SKIP_TEXT)
        self.skip_button.setToolTip(SKIP_TOOLTIP)
        self.skip_button.clicked.connect(self.skip_current)
        self.skip_button.hide()
        row.addWidget(self.skip_button)
        return row

    def _build_actions(self) -> None:
        # The actions carry the keys, so a key works whichever control has the
        # keyboard focus. Holding a key down only makes sense for the 5 second
        # jumps; a held Space would flicker between play and pause.
        self.play_action = self._add_action(
            "Play or pause", "Space", self._toggle_play, self.play_button,
            "Plays or pauses the recording.", "Space",
        )
        self.step_back_action = self._add_action(
            "Step back", ",", self._step_back, self.step_back_button,
            "Moves back one frame.", ", (comma)",
        )
        self.step_forward_action = self._add_action(
            "Step forward", ".", self._step_forward, self.step_forward_button,
            STEP_FORWARD_TOOLTIP, ". (period)",
        )
        self.back_five_action = self._add_action(
            "Back 5 seconds", "Left", functools.partial(self._jump, -JUMP_MS), self.back_five_button,
            "Goes back 5 seconds. Hold the key to keep going.", "Left", auto_repeat=True,
        )
        self.forward_five_action = self._add_action(
            "Forward 5 seconds", "Right", functools.partial(self._jump, JUMP_MS), self.forward_five_button,
            "Goes forward 5 seconds. Hold the key to keep going.", "Right", auto_repeat=True,
        )
        self.previous_line_action = self._add_action(
            "Previous line", "Up", self._go_to_previous_line, self.previous_line_button,
            "Goes back to the start of this line, or to the line before when this one has only just started.",
            "Up",
        )
        self.next_line_action = self._add_action(
            "Next line", "Down", self._go_to_next_line, self.next_line_button,
            "Goes to the next line.", "Down",
        )
        self.previous_stretch_action = self._add_action(
            "Previous stretch", "PgUp", self._go_to_previous_stretch, self.previous_stretch_button,
            "Goes back to the start of the stretch before this one.", "Page Up",
        )
        self.next_stretch_action = self._add_action(
            "Next stretch", "PgDown", self._go_to_next_stretch, self.next_stretch_button,
            "Goes to the start of the next stretch.", "Page Down",
        )
        self.waveforms_action = self._add_action(
            "Waveforms", "W", self._toggle_waveforms, self.waveforms_button,
            "Shows or hides the waveform of every track. Playing carries on.", "W",
        )
        self._waveforms_tooltip = self.waveforms_button.toolTip()
        self.previous_sound_action = self._add_action(
            "Previous sound", "Ctrl+Left", self._go_to_previous_sound, self.previous_sound_button,
            "Goes back to the start of the sound before this one, on the track you hear.", "Ctrl+Left",
        )
        self.next_sound_action = self._add_action(
            "Next sound", "Ctrl+Right", self._go_to_next_sound, self.next_sound_button,
            "Goes to the start of the next sound on the track you hear.", "Ctrl+Right",
        )
        self.previous_moment_action = self._add_action(
            "Previous moment", "[", self._go_to_previous_moment, self.previous_moment_button,
            "Goes back to the moment before this one that the package found.", "[",
        )
        self.next_moment_action = self._add_action(
            "Next moment", "]", self._go_to_next_moment, self.next_moment_button,
            "Goes to the next moment the package found.", "]",
        )

    def _add_action(
        self,
        text: str,
        keys: str,
        slot: Callable[..., None],
        button: QPushButton,
        tooltip: str,
        key_name: str,
        *,
        auto_repeat: bool = False,
    ) -> QAction:
        action = QAction(text, self)
        action.setShortcut(QKeySequence(keys))
        action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        action.setAutoRepeat(auto_repeat)
        action.triggered.connect(slot)
        self.addAction(action)
        button.clicked.connect(action.trigger)
        # Every tooltip ends with its key, so the keys can be learned from
        # the buttons as well as from the legend.
        button.setToolTip(f"{tooltip} Key: {key_name}")
        return action

    # Host access ------------------------------------------------------------------

    def _settings(self) -> MutableMapping[str, Any]:
        # Read from the host every time. The main window replaces and reloads
        # its settings, and a copy taken earlier would write to a dead one.
        settings = getattr(self._host, "app_settings", None)
        return settings if isinstance(settings, MutableMapping) else self._fallback_settings

    def _stored_volume(self) -> float:
        value = self._settings().get(VOLUME_KEY, DEFAULT_VOLUME)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return DEFAULT_VOLUME
        return max(0.0, min(1.0, float(value)))

    def _autoplay_setting(self) -> bool:
        return bool(self._settings().get(AUTOPLAY_KEY, True))

    def _save_settings(self) -> bool:
        """True only when the settings really reached disk."""

        saver = getattr(self._host, "save_app_settings", None)
        if not callable(saver):
            return False
        try:
            saver()
        except OSError:
            return False
        return True

    def _lists(self) -> Any:
        """Where the never-use list and the already-done map are kept now (244): the host's library, or
        its settings while they could not be moved in. Asked every time, like the settings."""

        return lists_of(self._host, self._fallback_settings)

    def _save_lists(self, lists: Any) -> bool:
        """True only when the change really reached disk: the library saved it as it was made."""

        return True if in_library(lists) else self._save_settings()

    def _notify_lists_changed(self) -> None:
        page = getattr(self._host, "bug_reports_page", None)
        changed = getattr(page, "recording_lists_changed", None)
        if callable(changed):
            changed()

    def _package_hints(self, target: PlayTarget) -> list[str]:
        """Folders that may hold this recording's package, most likely first.

        Built here, on the GUI thread, as plain text: the loader thread must
        never reach into the host or its settings.
        """

        hints: list[str] = []

        def add(value: Any) -> None:
            if isinstance(value, (str, PurePath)):
                text = str(value).strip()
                if text and text not in hints:
                    hints.append(text)

        add(target.package_root)
        add(getattr(getattr(self._host, "current_package", None), "root", None))
        settings = self._settings()
        add(settings.get("last_evidence_package"))
        # 243: the runs come from the library, through the Workbench, newest first; a host without one
        # still has its settings' list.
        recent = getattr(self._host, "recent_runs", None)
        runs = recent(limit=MAX_RECENT_RUN_HINTS) if callable(recent) else settings.get("recent_runs")
        if isinstance(runs, list):
            # Stored newest first, which is also the order to ask in.
            for run in runs[:MAX_RECENT_RUN_HINTS]:
                if isinstance(run, Mapping):
                    add(run.get("output"))
        return hints

    # Opening and closing -----------------------------------------------------------

    def open_target(
        self,
        target: PlayTarget,
        *,
        sequence: PlaySequence | None = None,
        autoplay: bool = True,
        note: str = "",
        insist_on_track: bool = False,
    ) -> None:
        """Open ``target``; ``note`` is said in the status line once it is open.

        ``insist_on_track`` (136): the page needs this very track heard (a track preview), so it wins
        even over a track the operator picked earlier for the same recording, and the window says once
        more which track it plays.
        """

        start_ms = max(0, round(target.start_seconds * 1000))
        same_recording = (
            self._player is not None
            and self._target is not None
            and not self._unplayable
            and path_key(target.path) == path_key(self._target.path)
        )
        if same_recording:
            # Already open: reloading a multi-hour recording to move inside it
            # would throw away the picture, the transcript and the place.
            if sequence is not None:
                self._sequence = sequence.opened_on(target)
            self._pending_note = str(note or "")
            if insist_on_track and target.hear_track is not None:
                self._operator_chose_track = False
            look_again = self._take_what_is_new(target)
            if insist_on_track and self._media_ready:
                self._follow_starting_track()
                self._announce_heard_track()
            if not self._media_ready:
                # Still loading, so a seek now would be dropped. Replace what
                # is waiting instead. The transcript is looked for once the
                # recording has loaded, with whatever the target then says.
                self._pending_start_ms = start_ms
                self._pending_autoplay = autoplay
                self._refresh_position_display()
            else:
                # A plain "Play" of the recording that is already open keeps
                # the operator's place; only a moment moves the playhead.
                if start_ms > 0:
                    self._seek_to(start_ms)
                if autoplay:
                    self._play()
                else:
                    self._pause_now()
                if look_again:
                    self._start_package_load()
                if self._pending_note:
                    self._say_what_is_open()
            self._bring_to_front()
            return

        self._retire_player()
        self._cancel_package_loads()
        self._player_generation += 1
        generation = self._player_generation
        self._target = target
        # The place in the list goes with the recording, so "next" carries on
        # from the row that was opened even when the recording is on several.
        self._sequence = sequence.opened_on(target) if sequence is not None else None
        self._unplayable = False
        self._pending_start_ms = start_ms
        self._pending_autoplay = autoplay
        self._pending_note = str(note or "")
        self._resume_ms = start_ms
        self._operator_chose_track = False
        self._no_speech_reason = ""
        self._finer_stretches = False
        self.choice_label.setText("")
        self.choice_label.setVisible(False)
        self._load_levels()
        self._refresh_stretch_buttons()
        if self._banner_is_problem():
            self._restore_undo_banner()

        self.setWindowTitle(f"{target.recording_path.name} — {WINDOW_TITLE}")
        self.video_stack.setCurrentWidget(self.video_surface)
        self._set_transport_enabled(True)
        self._clear_tracks()
        self._show_transcript_waiting(PACKAGE_FILE_TRANSCRIPT_TEXT if target.is_package_file else "")
        self.timeline.set_duration(0)
        self.timeline.set_ticks(())
        self._show_moments(())
        self._say(f"Opening {target.path.name}…")

        self._player = self._create_player(generation)
        self._player.setSource(QUrl.fromLocalFile(str(target.path)))
        self._refresh_play_button()
        self._refresh_position_display()
        self._refresh_recording_row()
        self._bring_to_front()

    def _take_what_is_new(self, target: PlayTarget) -> bool:
        """Keep what a second open of the open recording adds; True to look again.

        The same recording is opened before a run (no package yet) and again
        from the results (package named), or as a moment from a package. The
        file stays loaded, but the package, the voice track and the label the
        new target names must not be thrown away with it.
        """

        current = self._target
        if current is None:
            return False
        # Only what the new target really says replaces what is known: a plain
        # Play from a list that names no package must not forget the package.
        merged = replace(
            current,
            package_root=target.package_root or current.package_root,
            voice_track=target.voice_track if target.voice_track is not None else current.voice_track,
            voice_source=target.voice_source if target.voice_track is not None else current.voice_source,
            label=target.label or current.label,
            stands_in_for=target.stands_in_for or current.stands_in_for,
            hear_track=target.hear_track if target.hear_track is not None else current.hear_track,
            stretches=(current.stretches if self._finer_stretches and target.refine_stretches
                       else target.stretches or current.stretches),
            stretch_kind=(current.stretch_kind if self._finer_stretches and target.refine_stretches
                          else target.stretch_kind or current.stretch_kind),
            levels_path=target.levels_path or current.levels_path,
            refine_stretches=target.refine_stretches if target.stretches else current.refine_stretches,
        )
        if target.stretches and not target.refine_stretches:
            # A page's own stretches, over the same recording: they stay until another page says otherwise.
            self._finer_stretches = False
        if target.hear_track is not None and target.hear_track != current.hear_track:
            # A new open that names a track to hear is a fresh ask, not the operator's old choice.
            self._operator_chose_track = False
        package_is_new = merged.package_root != current.package_root
        self._target = merged
        if merged.levels_path != current.levels_path:
            self._load_levels()
        if merged.stretches != current.stretches:
            self._refresh_stretch_buttons()
        if merged != current:
            # "your voice" follows the track the new target names.
            if self._media_ready:
                self._populate_tracks()
            self.setWindowTitle(f"{merged.recording_path.name} — {WINDOW_TITLE}")
            self._refresh_recording_row()
        if merged.is_package_file:
            return False
        # Looked for again when a package was named, and when the last look
        # found nothing: a run may have made one since. A look that is still
        # going for the same package is left to finish.
        return package_is_new or (self._transcript is None and not self._package_lookup_running)

    def _create_player(self, generation: int) -> Any:
        player = self._player_factory()
        player.setAudioOutput(self.audio_output)
        player.setVideoOutput(self.video_surface)
        # One line per signal, each carrying the number of the player it was
        # made for. tests/test_review_player.py reads this file and fails if a
        # player signal is ever connected without that number.
        player.positionChanged.connect(functools.partial(self._on_position_changed, generation))
        player.durationChanged.connect(functools.partial(self._on_duration_changed, generation))
        player.playbackStateChanged.connect(functools.partial(self._on_playback_state_changed, generation))
        player.mediaStatusChanged.connect(functools.partial(self._on_media_status_changed, generation))
        player.errorOccurred.connect(functools.partial(self._on_error, generation))
        player.tracksChanged.connect(functools.partial(self._on_tracks_changed, generation))
        return player

    def _retire_player(self) -> None:
        player = self._player
        self._player = None
        # A new number even when nothing replaces the player: a report that is
        # already on its way from the old one must find nobody listening.
        self._player_generation += 1
        self._media_ready = False
        self._resume_after_scrub = False
        self._last_frame_ms = None
        self._coalescer.reset()
        self._cancel_step()
        if player is None:
            return
        try:
            # The player is NEVER told to stop. Measured with the real player
            # (PySide6 6.11.1) on a multi-hour recording with six audio tracks:
            # stop() straight after a change of audio track never returns and
            # freezes the whole app (2 of 2). It did return when called 10 ms
            # or more later, but waiting out a race is no defence against it,
            # so a test fails if this file ever calls stop() on a player.
            # Measured safe instead: pause() then an empty source straight
            # after a switch (about 104 ms, 3 of 3), the same after five quick
            # switches (3 of 3), and an empty source followed by deleteLater()
            # (3 of 3). pause() ends the sound at once; the empty source is
            # what makes the player let go of the file.
            player.pause()
            player.setSource(QUrl())
        except RuntimeError:
            pass  # the Qt object is already gone; there is nothing left to release
        for name in _PLAYER_SIGNALS:
            try:
                getattr(player, name).disconnect()
            except (AttributeError, RuntimeError, TypeError):
                pass
        try:
            player.deleteLater()
        except RuntimeError:
            pass

    def release_media(self) -> None:
        """Let go of the recording's file. Safe at any time; never waits."""

        was_open = self._player is not None
        if was_open:
            self._resume_ms = self._display_ms()
        self._retire_player()
        self._cancel_package_loads()
        if not self._ui_ready:
            return
        self._refresh_play_button()
        target = self._target
        if not was_open or target is None or self._unplayable:
            return
        # The main window asks for this at the start of every attempt to
        # close, including the ones the operator then calls off, so the
        # window may well stay on screen. It must say what Play will do, and
        # must not go on claiming to look for a transcript nobody is looking
        # for any more.
        self._say(f"Stopped. Press Play to carry on from {format_hms(self._resume_ms)}.")
        if self._transcript is None and not target.is_package_file:
            self._show_transcript_waiting(RELEASED_TRANSCRIPT_TEXT)

    def yield_audio(self) -> None:
        """Pause, keeping the place, because something else is about to play."""

        self._pause_now()

    def shutdown(self, wait_ms: int = 5000) -> bool:
        """Release everything; False when a loader thread is still running."""

        self._remember_window_state()
        self.release_media()
        deadline = time.monotonic() + max(0, wait_ms) / 1000
        stopped = True
        for thread in tuple(self._package_threads):
            remaining = max(0, round((deadline - time.monotonic()) * 1000))
            if thread.isRunning() and not thread.wait(remaining):
                # Still held here, and parked in case this window goes first.
                _park_thread(thread)
                stopped = False
                continue
            self._package_threads.discard(thread)
            _PARKED_THREADS.discard(thread)
            thread.deleteLater()
        return stopped

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        # Nothing here may wait or ask a question: the main window closes this
        # window from its own closeEvent. Loader threads are told to stop and
        # are waited for in shutdown(), not here.
        changed = self._remember_window_state()
        self.release_media()
        if changed:
            self._save_settings()
        event.accept()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        super().changeEvent(event)
        # Qt sends change events while the window is still being built.
        if not getattr(self, "_ui_ready", False) or event.type() != QEvent.Type.ActivationChange:
            return
        if self.isActiveWindow():
            # A run may have started or ended, or the never-use list changed
            # on the Find my bug reports page, while this window was behind.
            self._refresh_recording_row()
        elif self._resume_after_scrub:
            # The mouse release that ends a drag is lost when another window
            # takes over mid-drag. Without this the video would stay paused.
            self._resume_after_scrub = False
            self._play()

    def _bring_to_front(self) -> None:
        if self.docked_in is not None:
            # 236: on a page the player is already where the operator looks.
            self.show()
            return
        # Only the minimized flag is cleared. showNormal() clears the
        # maximized one as well, and a window the operator had maximized and
        # then minimized would come back at its old small size.
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    # On a page (236) ----------------------------------------------------------------

    def dock_into(self, holder: QWidget) -> None:
        """Show this one player inside ``holder`` (a page's player area, whose layout takes it, or which
        places it itself when it has none) instead of as its own window: the AI Video Editor plays the
        chosen version on its page this way, so the app keeps one player (236). Only the picture, the timeline and the playing controls show; the
        transcript, the line controls and never-use are about a recording, not about watching an edit.
        The keys work while the player has the keyboard, so typing elsewhere on the page never plays or
        jumps. ``undock`` gives the window back.
        """

        if self.docked_in is holder:
            self.show()
            return
        if self.docked_in is not None:
            self.undock()
        else:
            # Its place as a window is kept for when it is one again.
            self._remember_window_state()
        self.hide()
        self.docked_in = holder
        self.setParent(holder, Qt.WindowType.Widget)
        layout = holder.layout()
        if layout is not None:
            layout.addWidget(self)
        self._show_page_parts(False)
        for action in self.actions():
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.show()

    def _show_page_parts(self, shown: bool) -> None:
        """What a player on a page leaves out (236): an edited video has one track, the finished mix, so
        there is no track to choose and no waveform lane per track; its transcript, line controls and
        never-use are about a recording."""

        self.details_box.setVisible(shown)
        self.legend_label.setVisible(shown)
        for widget in (self.hear_label, self.track_combo, self.waveforms_button):
            widget.setVisible(shown)
        self._refresh_lanes()

    def undock(self) -> None:
        """Be the player's own window again, paused where it was, hidden until something opens it."""

        holder = self.docked_in
        if holder is None:
            return
        self._pause_now()
        self.hide()
        layout = holder.layout()
        if layout is not None:
            layout.removeWidget(self)
        self.docked_in = None
        self.setParent(None, Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self._show_page_parts(True)
        for action in self.actions():
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.resize(self._first_size())
        self._restore_geometry()

    def seek_seconds(self, seconds: float, *, play: bool = False) -> None:
        """Move to ``seconds`` into the open video (a scene of the AI Video Editor's story strip, 236);
        a seek asked for while it still loads waits until it has loaded, as the start of a target does."""

        milliseconds = max(0, round(float(seconds) * 1000))
        if self._player is None or not self._media_ready:
            self._pending_start_ms = milliseconds
            self._pending_autoplay = self._pending_autoplay or play
            return
        self._seek_to(milliseconds)
        if play:
            self._play()

    def open_path(self) -> Path | None:
        """The file open in the player now, None when nothing is."""

        return self._target.path if self._target is not None and self._player is not None else None

    def playing(self) -> bool:
        """Whether the open video is playing now (236)."""

        return self._player is not None and self._is_playing()

    def _restore_geometry(self) -> None:
        settings = self._settings()
        if not settings.get("restore_window_geometry", True):
            return
        encoded = settings.get(GEOMETRY_KEY)
        if not isinstance(encoded, str) or not encoded:
            return
        try:
            self.restoreGeometry(QByteArray.fromBase64(encoded.encode("ascii")))
        except (UnicodeEncodeError, ValueError):
            pass  # a hand-edited value; the default size is used instead

    def _remember_window_state(self) -> bool:
        """Put the window's place and volume into the settings; True if new."""

        settings = self._settings()
        # 236: a player shown on a page has no window place of its own; its window's place is kept as it was.
        geometry = (str(settings.get(GEOMETRY_KEY) or "") if self.docked_in is not None
                    else bytes(self.saveGeometry().toBase64()).decode("ascii"))
        volume = round(self.volume_slider.value() / 100, 2)
        changed = settings.get(GEOMETRY_KEY) != geometry or settings.get(VOLUME_KEY) != volume
        settings[GEOMETRY_KEY] = geometry
        settings[VOLUME_KEY] = volume
        return changed

    # Player reports -------------------------------------------------------------------
    #
    # Every slot below is connected with the player's number in front and
    # drops a report from any player but the current one. sender() is not
    # used: it is None for a call that did not come through a signal, and it
    # names a Qt object that may already be deleted.

    def _on_position_changed(self, generation: int, position: int) -> None:
        if generation != self._player_generation:
            return
        if not self._frames_expected():
            # No picture to wait for, so the clock stands in for it.
            self._frame_tick(position)
        self._refresh_position_display()

    def _on_duration_changed(self, generation: int, duration: int) -> None:
        if generation != self._player_generation:
            return
        self.timeline.set_duration(max(0, duration) / 1000)
        self._refresh_lanes()
        self._refresh_position_display()

    def _on_playback_state_changed(self, generation: int, _state: Any = None) -> None:
        if generation != self._player_generation:
            return
        self._refresh_play_button()

    def _on_media_status_changed(self, generation: int, status: Any = None) -> None:
        if generation != self._player_generation:
            return
        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._show_unplayable(self._player_error_text())
            return
        if status in _READY_STATUSES and not self._media_ready:
            self._media_ready = True
            self._apply_queued_start()
            self._populate_tracks()
            self._start_package_load()
            # The drive is awake now, so the row may look the recording up
            # under its resolved spelling as well (see _refresh_recording_row).
            self._refresh_recording_row()

    def _on_error(self, generation: int, error: Any = None, error_string: str = "") -> None:
        if generation != self._player_generation:
            return
        if error == QMediaPlayer.Error.NoError:
            return
        self._show_unplayable(str(error_string or "") or self._player_error_text())

    def _on_tracks_changed(self, generation: int) -> None:
        if generation != self._player_generation:
            return
        self._populate_tracks()

    def _on_video_frame(self, frame: Any) -> None:
        # Not numbered like the player slots: the sink belongs to this
        # window's own picture surface and only ever carries the current
        # player's frames. A stray frame could at worst let one queued seek
        # through early, and the queue is reset for every new recording.
        if self._player is None or not frame.isValid():
            return
        start = frame.startTime()  # microseconds; -1 when the frame carries no time
        self._frame_tick(start / 1000 if start >= 0 else self._player.position())

    def _frames_expected(self) -> bool:
        if self._video_sink is None or self._player is None:
            return False
        has_video = getattr(self._player, "hasVideo", None)
        return bool(has_video()) if callable(has_video) else True

    def _frame_tick(self, milliseconds: float) -> None:
        self._last_frame_ms = milliseconds
        self._coalescer.frame_arrived(milliseconds)
        # Measured: the first frame after play() is the one already on screen,
        # shown again. Only a LATER frame is a step.
        if self._step_pending and milliseconds > self._step_from_ms:
            self._finish_step()

    def _player_error_text(self) -> str:
        text = getattr(self._player, "errorString", None)
        try:
            return str(text() or "") if callable(text) else ""
        except RuntimeError:
            return ""

    def _apply_queued_start(self) -> None:
        """Apply the start and the play-or-pause decision kept back at open.

        Measured in a real window: a position set while the recording is still
        loading is silently dropped, with no error, and the recording opens at
        0:00:00. So both waited until now.
        """

        player = self._player
        if player is None:
            return
        start_ms, autoplay = self._pending_start_ms, self._pending_autoplay
        self._apply_speed()
        if autoplay:
            if start_ms > 0:
                self._seek_to(start_ms)
            self._play()
        else:
            # pause() on its own is what puts the first picture on screen
            # (measured), so a recording opened paused is not a black box.
            player.pause()
            if start_ms > 0:
                self._seek_to(start_ms)
        self._say_what_is_open()

    def _say_what_is_open(self) -> None:
        """The status line for a recording that has just opened."""

        target = self._target
        note, self._pending_note = self._pending_note, ""
        parts = [note] if note else []
        if target is not None and target.stands_in_for is not None:
            # The operator asked for the recording and is watching a copy of
            # it; every button below still acts on the recording.
            standing_in = f"Playing the small review copy of {target.stands_in_for.name}."
            if standing_in not in note:
                parts.append(standing_in)
        self._say(" ".join(parts) or (target.label if target is not None else ""))

    # Transport --------------------------------------------------------------------------

    def _set_player_position(self, milliseconds: int) -> None:
        if self._player is not None:
            self._player.setPosition(milliseconds)

    def _display_ms(self) -> int:
        """Where the operator is, which is not always where the player is."""

        if self._player is None:
            return self._resume_ms
        if not self._media_ready:
            return self._pending_start_ms
        # While a seek is unfinished the player still reports the old place.
        # Showing that would make the playhead jump back under the mouse.
        requested = self._coalescer.requested_ms()
        return requested if requested is not None else max(0, int(self._player.position()))

    def _duration_ms(self) -> int:
        return max(0, int(self._player.duration())) if self._player is not None else 0

    def _seek_to(self, milliseconds: int) -> None:
        """The one way the playhead is moved."""

        if self._player is None:
            return
        target = max(0, int(milliseconds))
        duration = self._duration_ms()
        if duration > 0:
            target = min(target, duration)
        if self._media_ready:
            self._coalescer.request(target)
            # 125 Part 2: a waveform being measured from this drive waits a moment, so the picture comes first.
            self._hold_measuring()
        else:
            # The player would drop it; it is applied once the recording loads.
            self._pending_start_ms = target
        self._refresh_position_display()

    def _jump(self, delta_ms: int, _checked: bool = False) -> None:
        # From where the operator ASKED to be, so three quick presses move
        # 15 seconds even though the player has not caught up with the first.
        self._seek_to(self._display_ms() + delta_ms)

    def _play(self) -> None:
        player = self._player
        if player is None:
            return
        if player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia:
            self._seek_to(0)
        player.play()

    def _pause_now(self) -> None:
        self._resume_after_scrub = False
        self._cancel_step()
        if self._player is None:
            return
        # A recording that is still loading must not start by itself later.
        self._pending_autoplay = False
        self._player.pause()
        self._refresh_play_button()

    def _is_playing(self) -> bool:
        # A step forward plays for a frame or two; that is not "playing", and
        # the Play button must not flash to Pause for it.
        if self._player is None or self._step_pending:
            return False
        if not self._media_ready:
            return self._pending_autoplay
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def _toggle_play(self) -> None:
        if self._player is None:
            if self._target is not None and not self._unplayable:
                # The file was let go of (the main window asked). Pick the
                # recording up again where it was.
                self.open_target(
                    replace(self._target, start_seconds=self._resume_ms / 1000),
                    sequence=self._sequence,
                    autoplay=True,
                )
            return
        if self._unplayable:
            return
        if not self._media_ready:
            # Nothing to play yet; remember the wish for when it has loaded.
            self._pending_autoplay = not self._pending_autoplay
            self._refresh_play_button()
            return
        if self._step_pending:
            # Play pressed in the middle of a step: the player is already
            # running, so the step simply does not pause it again.
            self._cancel_step()
            self._refresh_play_button()
            return
        if self._is_playing():
            self._pause_now()
        else:
            self._play()

    def _refresh_play_button(self) -> None:
        self.play_button.setText("Pause" if self._is_playing() else "Play")

    def _frame_ms(self) -> int:
        player = self._player
        try:
            tracks = list(player.videoTracks())
            active = player.activeVideoTrack()
            metadata = tracks[active] if 0 <= active < len(tracks) else player.metaData()
            rate = float(metadata.value(QMediaMetaData.Key.VideoFrameRate))
        except (AttributeError, IndexError, RuntimeError, TypeError, ValueError):
            return FALLBACK_FRAME_MS
        if not math.isfinite(rate) or rate <= 0:
            return FALLBACK_FRAME_MS
        return max(1, round(1000 / rate))

    def _step_back(self) -> None:
        if self._player is None or not self._media_ready:
            return
        if self._is_playing():
            self._pause_now()
        self._seek_to(self._display_ms() - self._frame_ms())

    def _step_forward(self) -> None:
        player = self._player
        if player is None or not self._media_ready or self._step_pending:
            return
        if self._is_playing():
            self._pause_now()
            return
        # The player has no "next frame". Playing until the next picture
        # arrives and pausing on it lands one or two frames on (measured).
        # Muted meanwhile, or every step would click.
        self._step_pending = True
        shown = self._last_frame_ms
        self._step_from_ms = shown if shown is not None else float(player.position())
        self._muted_before_step = bool(self.audio_output.isMuted())
        self.audio_output.setMuted(True)
        self._step_timer.start()
        player.play()

    def _finish_step(self) -> None:
        if not self._step_pending:
            return
        if self._player is not None:
            self._player.pause()
        self._cancel_step()

    def _cancel_step(self) -> None:
        self._step_timer.stop()
        if self._step_pending:
            self._step_pending = False
            self.audio_output.setMuted(self._muted_before_step)

    def _on_timeline_seek(self, seconds: float) -> None:
        self._seek_to(round(seconds * 1000))

    def _on_scrub_started(self) -> None:
        self._hold_measuring()
        # A playing video fights a drag: every picture the drag asks for is
        # replaced at once by playback moving on.
        if self._media_ready and self._is_playing():
            self._player.pause()
            self._resume_after_scrub = True

    def _on_scrub_finished(self) -> None:
        if self._resume_after_scrub:
            self._resume_after_scrub = False
            self._play()

    def _on_speed_chosen(self, _index: int = 0) -> None:
        self._apply_speed()

    def _apply_speed(self) -> None:
        rate = self.speed_combo.currentData()
        set_rate = getattr(self._player, "setPlaybackRate", None)
        if callable(set_rate) and isinstance(rate, float):
            set_rate(rate)

    def _on_volume_changed(self, value: int) -> None:
        self.audio_output.setVolume(max(0, min(100, value)) / 100)

    def _set_transport_enabled(self, enabled: bool) -> None:
        for widget in (
            self.step_back_button,
            self.play_button,
            self.step_forward_button,
            self.back_five_button,
            self.forward_five_button,
            self.timeline,
        ):
            widget.setEnabled(enabled)

    def _refresh_position_display(self) -> None:
        position = self._display_ms()
        duration = self._duration_ms()
        self.time_label.setText(f"{format_hms(position)} / {format_hms(duration)}")
        self.timeline.set_position(position / 1000)
        if self.track_lanes.isVisible():
            self.track_lanes.set_position(position / 1000)
        self._update_line_panel(position / 1000)

    # Stretches (220) ---------------------------------------------------------------------

    def _refresh_stretch_buttons(self) -> None:
        target = self._target
        stretches = target.stretches if target is not None else ()
        what = "speech" if target is not None and target.stretch_kind == "speech" else "stretch"
        self.previous_stretch_button.setText(f"Previous {what}")
        self.next_stretch_button.setText(f"Next {what}")
        for button in (self.previous_stretch_button, self.next_stretch_button):
            button.setVisible(bool(stretches))
            button.setEnabled(bool(stretches))

    def _stretch_now(self) -> float:
        now = self._display_ms() / 1000
        jump = self._stretch_jump
        if (jump is not None and time.monotonic() - jump[2] < STRETCH_JUMP_SETTLE_SECONDS
                and abs(now - jump[1]) <= STRETCH_JUMP_STALE_SECONDS):
            return jump[0]  # the player still reports the place it left
        return now

    def _jump_to_stretch(self, start: float) -> None:
        self._stretch_jump = (float(start), self._display_ms() / 1000, time.monotonic())
        self._seek_to(round(float(start) * 1000))

    @staticmethod
    def _next_start(stretches: Any, now: float) -> float | None:
        upcoming = [start for start, _end in stretches if start > now + JUMP_MARGIN_SECONDS]
        return upcoming[0] if upcoming else None

    @staticmethod
    def _previous_start(stretches: Any, now: float) -> float | None:
        # The stretch before the one playing (or, between stretches, the one just heard), never the
        # start of the same stretch again (220).
        if not stretches:
            return None
        current = next((start for start, end in stretches if start - JUMP_MARGIN_SECONDS <= now < end), None)
        before = (current if current is not None else now) - JUMP_MARGIN_SECONDS
        earlier = [start for start, _end in stretches if start < before]
        return earlier[-1] if earlier else stretches[0][0]

    def _go_to_next_stretch(self) -> None:
        target = self._target
        if target is None or not target.stretches:
            return
        start = self._next_start(target.stretches, self._stretch_now())
        if start is None:
            self._say("That was the last stretch.")
            return
        self._jump_to_stretch(start)

    def _go_to_previous_stretch(self) -> None:
        target = self._target
        if target is None or not target.stretches:
            return
        self._jump_to_stretch(self._previous_start(target.stretches, self._stretch_now()))

    # The waveform lanes and Next / Previous sound (125 Part 2) --------------------------------

    def _levels_wanted(self) -> bool:
        # A clip or a small copy has one track that is not the recording's, so it gets no lanes; nor does
        # an edited video shown on a page (236): its one track is the finished mix.
        target = self._target
        return (target is not None and not target.is_package_file and target.stands_in_for is None
                and self.docked_in is None)

    def _service(self) -> Any | None:
        service = getattr(self._host, "levels_service", None)
        if service is None or not getattr(service, "enabled", False):
            return None
        if self._levels_service is not service:
            self._levels_service = service
            service.levels_changed.connect(self._on_service_levels)
            service.state_changed.connect(self._on_service_state)
            facts_changed = getattr(service, "facts_changed", None)
            if facts_changed is not None:
                facts_changed.connect(self._on_service_facts)
        return service

    def _load_levels(self) -> None:
        """This recording's levels: the raw bin's file a page handed over, else the shared levels job."""

        self._levels = {}
        self._levels_duration = 0.0
        self._sounds = None
        target = self._target
        if self._levels_wanted() and target is not None and target.levels_path is not None:
            try:
                data = json.loads(Path(target.levels_path).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            if isinstance(data, dict):
                self._levels = {int(key): [float(value) for value in values] for key, values in data.items()
                                if str(key).isdigit() and 0 < int(key) <= MAX_TRACKS and isinstance(values, list)}
        service = self._service() if self._levels_wanted() else None
        if service is not None and target is not None:
            known = service.levels_for(target.path)
            if known is not None and known.seconds >= max((len(values) for values in self._levels.values()), default=0):
                self._take_levels(known)
            # Always asked, even with the raw bin's levels in hand: the shared lookup also checks that
            # the file is still the one the raw bin scanned, and its answer replaces them if not.
            service.want(target.path)
        self._refresh_lanes()

    def _take_levels(self, levels: Any) -> None:
        self._levels = {int(track): list(values) for track, values in levels.tracks.items()}
        self._levels_duration = float(getattr(levels, "duration_seconds", 0.0) or 0.0)
        self._sounds = None

    def _on_service_levels(self, key: str) -> None:
        target, service = self._target, self._levels_service
        if target is None or service is None or not self._levels_wanted() or path_key(target.path) != key:
            return
        known = service.levels_for(target.path)
        if known is not None:
            self._take_levels(known)
        self._refresh_lanes()

    def _on_service_state(self, key: str) -> None:
        target = self._target
        if target is not None and path_key(target.path) == key:
            self._refresh_lanes()

    def _on_service_facts(self, key: str) -> None:
        """264: what the library knows about this recording's speech, as soon as it is known: the buttons appear
        without reopening. A page's own stretches stay unless they are the raw bin's coarse ones (Q2). A jump never
        changes the track you hear."""

        target, service = self._target, self._levels_service
        if target is None or service is None or not self._levels_wanted() or path_key(target.path) != key:
            return
        facts = service.facts_for(target.path)
        if facts is None:
            return
        changes: dict[str, Any] = {}
        reason = ""
        if facts.stretches and (not target.stretches or target.refine_stretches):
            changes.update(stretches=tuple(facts.stretches), stretch_kind="speech")
            self._finer_stretches = True
        elif facts.reason and not target.stretches:
            reason = facts.reason
        self._no_speech_reason = reason
        self.choice_label.setText(facts.you_chose)
        self.choice_label.setVisible(bool(facts.you_chose))
        if changes:
            self._target = replace(target, **changes)
            self._refresh_stretch_buttons()
        self._refresh_lanes()

    def _hold_measuring(self) -> None:
        service = self._levels_service
        if service is not None:
            service.hold()

    def _heard_track(self) -> int | None:
        index = self.track_combo.currentData()
        if isinstance(index, int):
            return index + 1
        target = self._target
        return target.hear_track if target is not None else None

    def _lane_labels(self) -> dict[int, str]:
        tracks = sorted(self._levels) or [index + 1 for index in range(self.track_combo.count())]
        roles = parse_roles(self._settings().get(TRACK_ROLES_KEY))
        metadata = self._audio_tracks()
        labels: dict[int, str] = {}
        for track in tracks:
            try:
                title = str(metadata[track - 1].stringValue(QMediaMetaData.Key.Title) or "").strip()
            except (AttributeError, IndexError, RuntimeError, TypeError):
                title = ""
            if not title or _TITLE_IS_ONLY_A_NUMBER.match(title):
                title = _ROLE_WORDS.get(roles.get(track, ""), "")
            label = f"{track} {title}".strip() if title else f"Track {track}"
            if self._target is not None and self._target.voice_track == track:
                label += " · your voice"
            labels[track] = label
        return labels

    def _waveforms_shown(self) -> bool:
        return bool(self._settings().get(WAVEFORMS_KEY, True))

    def _refresh_lanes(self) -> None:
        target = self._target
        service = self._levels_service
        message = service.state_for(target.path) if service is not None and target is not None else ""
        message = message or self._no_speech_reason
        duration = self._duration_ms() / 1000 or self._levels_duration
        known = bool(self._levels) or bool(message)
        if not self._levels_wanted() or not known or duration <= 0:
            self.track_lanes.hide()
        else:
            self.track_lanes.set_tracks(self._lane_labels())
            self.track_lanes.set_levels(self._levels, duration)
            self.track_lanes.set_heard(self._heard_track())
            self.track_lanes.set_message(message)
            self.track_lanes.set_position(self._display_ms() / 1000)
            self.track_lanes.setVisible(self._waveforms_shown())
        sounds = bool(self._levels.get(self._heard_track() or 0))
        for button in (self.previous_sound_button, self.next_sound_button):
            # Next / Previous sound keep working while the lanes are hidden: they use the levels.
            button.setVisible(sounds and self._levels_wanted())
        reason = self._no_waveforms_reason()
        self.waveforms_button.setEnabled(not reason)
        self.waveforms_button.setToolTip(reason or self._waveforms_tooltip)

    def _no_waveforms_reason(self) -> str:
        target = self._target
        if target is None or self._levels_wanted():
            return ""
        return NO_WAVEFORMS_REVIEW_COPY_TEXT if target.stands_in_for is not None else NO_WAVEFORMS_CLIP_TEXT

    def _toggle_waveforms(self) -> None:
        # W still answers when there is nothing to show (the button is greyed out): it says why.
        reason = self._no_waveforms_reason()
        if reason:
            self._say(reason)
            return
        # Never pauses, seeks or changes the track: only the lanes are shown or hidden.
        settings = self._settings()
        settings[WAVEFORMS_KEY] = not self._waveforms_shown()
        self._save_settings()
        self._refresh_lanes()
        self._say("Waveforms shown." if self._waveforms_shown() else "Waveforms hidden. Press W to show them again.")

    def _levels_from_library(self) -> bool:
        target, service = self._target, self._levels_service
        if target is None:
            return False
        known = service.levels_for(target.path) if service is not None else None
        if known is not None:
            return known.origin == "library"
        return target.levels_path is not None

    def _build_lanes_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        action = menu.addAction(MEASURE_AGAIN_TEXT)
        action.triggered.connect(self._measure_again)
        if self._levels_from_library():
            action.setEnabled(False)
            action.setToolTip(MEASURE_AGAIN_LIBRARY_TOOLTIP)
        else:
            action.setEnabled(self._service() is not None and self._levels_wanted())
        return menu

    def _show_lanes_menu(self, point: Any) -> None:
        menu = self._build_lanes_menu()
        try:
            self._exec_menu(menu, self.track_lanes.mapToGlobal(point))
        finally:
            menu.deleteLater()

    def _exec_menu(self, menu: QMenu, where: Any) -> None:
        menu.exec(where)

    def _measure_again(self, _checked: bool = False) -> None:
        service, target = self._service(), self._target
        if service is None or target is None or not self._levels_wanted() or self._levels_from_library():
            return
        self._levels = {}
        self._levels_duration = 0.0
        self._sounds = None
        service.measure_again(target.path)
        self._refresh_lanes()

    def _on_lanes_seek(self, seconds: float) -> None:
        self._seek_to(round(seconds * 1000))

    def _on_lane_chosen(self, track: int) -> None:
        position = self.track_combo.findData(int(track) - 1)
        if position < 0:
            return
        if position == self.track_combo.currentIndex():
            self._say(f"You are already hearing Track {track}.")
            return
        self.track_combo.setCurrentIndex(position)

    def _sound_stretches(self, track: int) -> list[tuple[int, int]]:
        levels = self._levels.get(track) or []
        cached = self._sounds
        if cached is None or cached[0] != track or cached[1] != len(levels):
            cached = self._sounds = (track, len(levels), sound_stretches(levels))
        return cached[2]

    def _go_to_next_sound(self) -> None:
        track = self._heard_track()
        if track is None or not self._levels.get(track):
            return
        start = self._next_start(self._sound_stretches(track), self._stretch_now())
        if start is None:
            measured = len(self._levels.get(track) or [])
            whole = self._duration_ms() / 1000
            self._say(f"No more sound measured yet on Track {track}." if whole and measured < whole - 1
                      else f"That was the last sound on Track {track}.")
            return
        self._jump_to_stretch(start)

    def _go_to_previous_sound(self) -> None:
        track = self._heard_track()
        if track is None or not self._levels.get(track):
            return
        start = self._previous_start(self._sound_stretches(track), self._stretch_now())
        if start is None:
            self._say(f"There is no sound on Track {track}.")
            return
        self._jump_to_stretch(start)

    # Moments the package found (125 Part 2) ---------------------------------------------------

    @staticmethod
    def _moment_words(moment: Moment) -> str:
        words = f"{moment.text} at {format_hms(moment.seconds * 1000)}"
        return f"{words}: {moment.excerpt}" if moment.excerpt else words

    def _show_moments(self, moments: Any) -> None:
        self._moments = tuple(item for item in moments or () if isinstance(item, Moment))
        self.timeline.set_moments([(item.seconds, item.finding, self._moment_words(item)) for item in self._moments])
        for button in (self.previous_moment_button, self.next_moment_button):
            button.setVisible(bool(self._moments))

    def _on_moments_found(self, generation: int, moments: Any) -> None:
        if generation != self._package_generation:
            return
        self._show_moments(moments)

    def _on_moment_clicked(self, index: int) -> None:
        if 0 <= index < len(self._moments):
            self._say(self._moment_words(self._moments[index]))

    def _go_to_moment(self, index: int | None, nothing: str) -> None:
        if index is None:
            self._say(nothing)
            return
        moment = self._moments[index]
        self._jump_to_stretch(moment.seconds)
        self._say(self._moment_words(moment))

    def _go_to_next_moment(self) -> None:
        if not self._moments:
            return
        now = self._stretch_now()
        index = next((place for place, item in enumerate(self._moments)
                      if item.seconds > now + JUMP_MARGIN_SECONDS), None)
        self._go_to_moment(index, "That was the last moment.")

    def _go_to_previous_moment(self) -> None:
        if not self._moments:
            return
        now = self._stretch_now()
        started = [place for place, item in enumerate(self._moments) if item.seconds <= now + JUMP_MARGIN_SECONDS]
        if started and now - self._moments[started[-1]].seconds <= RESTART_MOMENT_SECONDS:
            started = started[:-1]
        self._go_to_moment(started[-1] if started else (0 if self._moments else None), "There is no moment before this.")

    def _follow_starting_track(self) -> None:
        """Start on the track to hear, else on the track the transcript came from (212), unless the
        operator has picked one. The choice is made quietly: no "Hearing Track N" line for it."""

        if self._player is None or self._operator_chose_track:
            return
        target = self._target
        wanted = target.hear_track if target is not None else None
        if wanted is None and self._transcript is not None:
            wanted = self._transcript.transcribed_track
        if wanted is None:
            return
        position = self.track_combo.findData(int(wanted) - 1)
        if position < 0 or position == self.track_combo.currentIndex():
            return
        with QSignalBlocker(self.track_combo):
            self.track_combo.setCurrentIndex(position)
        self._player.setActiveAudioTrack(int(wanted) - 1)
        self._refresh_lanes()
        self._announce_heard_track()

    # Audio tracks ---------------------------------------------------------------------

    def _audio_tracks(self) -> list[Any]:
        tracks = getattr(self._player, "audioTracks", None)
        try:
            return list(tracks()) if callable(tracks) else []
        except RuntimeError:
            return []

    def _clear_tracks(self) -> None:
        with QSignalBlocker(self.track_combo):
            self.track_combo.clear()
        self.track_combo.setEnabled(False)

    def _track_label(self, index: int, metadata: Any) -> str:
        label = f"Track {index + 1}"
        try:
            title = str(metadata.stringValue(QMediaMetaData.Key.Title) or "").strip()
        except (AttributeError, RuntimeError, TypeError):
            title = ""
        if title and not _TITLE_IS_ONLY_A_NUMBER.match(title):
            label += f" - {title}"
        if self._target is not None and self._target.voice_track == index + 1:
            label += " - your voice"
            if self._target.voice_source:
                label += f" ({self._target.voice_source})"
        return label

    def _populate_tracks(self) -> None:
        tracks = self._audio_tracks()
        active = self._player.activeAudioTrack() if tracks else -1
        # Blocked while it is rebuilt: filling the list is not the operator
        # choosing a track.
        with QSignalBlocker(self.track_combo):
            self.track_combo.clear()
            for index, metadata in enumerate(tracks):
                self.track_combo.addItem(self._track_label(index, metadata), index)
            if tracks:
                self.track_combo.setCurrentIndex(active if 0 <= active < len(tracks) else 0)
        self.track_combo.setEnabled(len(tracks) > 1)
        self._refresh_track_explanation()
        self._follow_starting_track()
        self._refresh_lanes()
        self._announce_heard_track()

    def _announce_heard_track(self) -> None:
        index = self.track_combo.currentData()
        if self._media_ready and self._target is not None and isinstance(index, int):
            self.track_heard.emit(str(self._target.recording_path), index + 1)

    def _on_track_chosen(self, _index: int = 0) -> None:
        index = self.track_combo.currentData()
        if self._player is None or not isinstance(index, int):
            return
        self._operator_chose_track = True
        self._player.setActiveAudioTrack(index)
        self._say(f"Hearing Track {index + 1}.")
        self._refresh_lanes()
        self._announce_heard_track()

    def _hear_transcribed_track(self) -> None:
        track = self._transcript.transcribed_track if self._transcript is not None else None
        if track is None:
            return
        position = self.track_combo.findData(track - 1)
        if position < 0:
            self._say(f"This recording has no Track {track}.", "attention")
            return
        if position == self.track_combo.currentIndex():
            self._say(f"You are already hearing Track {track}.")
            return
        self.track_combo.setCurrentIndex(position)

    # Transcript -----------------------------------------------------------------------

    def _start_package_load(self) -> None:
        # Whatever was being looked for is no longer wanted, and its answer
        # must find nobody listening: this look gets a number of its own.
        self._cancel_package_loads()
        generation = self._package_generation
        target = self._target
        if target is None:
            return
        if target.is_package_file:
            # A clip or a small copy has no recording for a package to list.
            self._show_transcript_waiting(PACKAGE_FILE_TRANSCRIPT_TEXT)
            return
        hints = self._package_hints(target)
        if not hints:
            # Nowhere to look, so there is nothing to start a thread for.
            self._show_transcript(None)
            return
        duration = self._duration_ms()
        # The length is only evidence about the file it was measured on. A
        # small review copy standing in for the recording need not be exactly
        # as long, and a wrong length would turn the right package away.
        measured_on_recording = target.stands_in_for is None and duration > 0
        thread = PackageLoadThread(
            generation,
            target.recording_path,
            target.package_root,
            hints,
            duration / 1000 if measured_on_recording else None,
        )
        thread.loaded.connect(self._on_package_loaded)
        thread.moments_found.connect(self._on_moments_found)
        thread.failed.connect(self._on_package_failed)
        thread.finished.connect(self._on_package_thread_finished)
        self._package_threads.add(thread)
        self._package_lookup_running = True
        self._show_transcript_waiting(LOOKING_FOR_TRANSCRIPT_TEXT)
        thread.start()

    def _cancel_package_loads(self) -> None:
        # Asked to stop, never waited for: this runs while a recording is
        # being opened and from closeEvent. A cancelled thread still reports
        # once ("nothing found"); the new number is what makes that report
        # arrive too late to be shown.
        self._package_generation += 1
        self._package_lookup_running = False
        for thread in tuple(self._package_threads):
            thread.cancel()

    def _on_package_loaded(self, generation: int, transcript: Any) -> None:
        if generation != self._package_generation:
            return
        self._package_lookup_running = False
        self._show_transcript(transcript if isinstance(transcript, RecordingTranscript) else None)

    def _on_package_failed(self, generation: int, details: str) -> None:
        if generation != self._package_generation:
            return
        self._package_lookup_running = False
        # The details can hold a full path, so they go to the log only.
        self.diagnostic.emit(f"Built-in player could not read a transcript: {details}")
        self._show_transcript(None)

    def _on_package_thread_finished(self) -> None:
        for thread in tuple(self._package_threads):
            if thread.isFinished():
                self._package_threads.discard(thread)
                thread.deleteLater()

    def _show_transcript_waiting(self, note: str) -> None:
        self._transcript = None
        self._lines = []
        self._line_starts = []
        self._panel_valid = None
        self.timeline.set_ticks(())
        self.transcript_header.setText("")
        self.transcript_header.setVisible(False)
        self.transcript_note.setText(note)
        self.transcript_note.setVisible(bool(note))
        self._refresh_track_explanation()
        self._clear_line_labels()
        self._set_line_controls_enabled(False)

    def _show_transcript(self, transcript: RecordingTranscript | None) -> None:
        if transcript is None:
            # A plain sentence, and the player carries on without one.
            self._show_transcript_waiting(NO_TRANSCRIPT_TEXT)
            return
        self._transcript = transcript
        root = transcript.package_root
        # The package folder always has the same name; the run folder around
        # it is the one the operator chose and recognises.
        folder = root.parent.name if root.name.lower() == "codex-evidence-package" and root.parent.name else root.name
        self.transcript_header.setText(f"Transcript from: {folder}")
        self.transcript_header.setVisible(True)
        notes: list[str] = []
        if not transcript.audit_available:
            notes.append(NO_AUDIT_TEXT)
        elif not transcript.filtering_ran:
            # "No filtering ran" is not "nothing was left out", and the
            # operator must not be told the second when the first is true.
            notes.append(
                f"No filtering ran for this recording — it was transcribed in {transcript.mode} mode."
                if transcript.mode
                else UNKNOWN_MODE_TEXT
            )
        elif not transcript.rescued_known:
            notes.append(NO_RESCUE_RECORD_TEXT)
        self.transcript_note.setText(" ".join(notes))
        self.transcript_note.setVisible(bool(notes))
        self._refresh_track_explanation()
        self._set_line_controls_enabled(True)
        self._apply_line_filter()
        self._follow_starting_track()

    def _refresh_track_explanation(self) -> None:
        transcript = self._transcript
        track = transcript.transcribed_track if transcript is not None else None
        text = transcript.track_explanation if transcript is not None else ""
        if not text and track is not None:
            text = f"This transcript was made from Track {track}."
        self.track_explanation_label.setText(text)
        self.track_explanation_label.setVisible(bool(text))
        self.hear_track_button.setVisible(track is not None)
        self.hear_track_button.setEnabled(track is not None and self.track_combo.findData(track - 1) >= 0)

    def _set_line_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.line_filter_combo,
            self.previous_line_button,
            self.next_line_button,
            self.show_numbers_checkbox,
        ):
            widget.setEnabled(enabled)

    def _on_filter_chosen(self, _index: int = 0) -> None:
        self._apply_line_filter()

    def _on_show_numbers_toggled(self, _checked: bool = False) -> None:
        self._update_line_panel(self._display_ms() / 1000, force=True)

    def _apply_line_filter(self) -> None:
        transcript = self._transcript
        if transcript is None:
            return
        show = self.line_filter_combo.currentData() or SHOW_ALL
        self._lines = visible_lines(transcript.lines, show)
        self._line_starts = [line.start for line in self._lines]
        # The marks follow the filter, so what can be stepped through is
        # what can be seen. A stretch thrown out whole carries its end so the
        # bar can show how long it was.
        self.timeline.set_ticks(
            [
                (line.start, line.kind, line.end) if line.kind == KIND_REJECTED_SPAN else (line.start, line.kind)
                for line in self._lines
            ]
        )
        self._update_line_panel(self._display_ms() / 1000, force=True)

    def _clear_line_labels(self) -> None:
        for label in (
            self.previous_line_label,
            self.line_time_label,
            self.line_badge_label,
            self.current_line_label,
            self.line_reason_label,
            self.line_numbers_label,
            self.next_line_label,
        ):
            label.setText("")
        self.line_badge_label.setToolTip("")
        self.line_reason_label.setVisible(False)
        self.line_numbers_label.setVisible(False)

    def _update_line_panel(self, seconds: float, *, force: bool = False) -> None:
        if self._transcript is None:
            return
        valid = self._panel_valid
        if not force and valid is not None and valid[0] <= seconds < valid[1]:
            return
        lines = self._lines
        started = bisect_right(self._line_starts, seconds)
        next_start = self._line_starts[started] if started < len(lines) else math.inf
        index = line_index_at(lines, seconds)
        following = lines[started] if started < len(lines) else None
        if index is None:
            # Right until the next line starts, whatever the clock does.
            self._panel_valid = (seconds, next_start)
            self._show_gap(lines[started - 1] if started > 0 else None, following)
            return
        line = lines[index]
        spoken_until = max(line.end, line.start + START_MATCH_SECONDS)
        self._panel_valid = (seconds, min(spoken_until, next_start))
        self._show_line(line, lines[index - 1] if index > 0 else None, following)

    @staticmethod
    def _dimmed_text(line: TranscriptLine | None) -> str:
        if line is None:
            return ""
        return f"{format_hms(line.start * 1000)}  {line.text or '(no words)'}"

    def _show_gap(self, previous: TranscriptLine | None, following: TranscriptLine | None) -> None:
        self._clear_line_labels()
        self.previous_line_label.setText(self._dimmed_text(previous))
        self.next_line_label.setText(self._dimmed_text(following))
        if not self._lines:
            text = "No lines to show with this filter."
        elif following is not None:
            text = f"Nothing transcribed here. Next line at {format_hms(following.start * 1000)}."
        else:
            text = "Nothing transcribed here. There are no more lines after this."
        self.current_line_label.setText(text)
        _set_property(self.current_line_label, "statusKind", "")
        _set_property(self.current_line_label, "muted", "true")

    def _show_line(
        self,
        line: TranscriptLine,
        previous: TranscriptLine | None,
        following: TranscriptLine | None,
    ) -> None:
        left_out = line.kind != KIND_KEPT
        self.previous_line_label.setText(self._dimmed_text(previous))
        self.next_line_label.setText(self._dimmed_text(following))
        self.line_time_label.setText(f"{format_hms(line.start * 1000)}–{format_hms(line.end * 1000)}")
        badges: list[str] = []
        if left_out:
            badges.append(BADGE_LEFT_OUT)
        if line.rescued:
            badges.append(BADGE_RESCUED)
        if line.spotter:
            badges.append(BADGE_SPOTTER)
        self.line_badge_label.setText("  ·  ".join(badges))
        # The badge is short; why such a line deserves a second look is here.
        self.line_badge_label.setToolTip(BADGE_RESCUED_TOOLTIP if line.rescued else "")
        # Amber for anything the operator should doubt, the same amber as the
        # left-out marks on the timeline.
        _set_property(self.line_badge_label, "statusKind", "attention" if left_out or line.spotter else "")
        _set_property(self.line_badge_label, "accent", "" if left_out or line.spotter else "true")
        self.current_line_label.setText(line.text or "(no words)")
        _set_property(self.current_line_label, "muted", "")
        _set_property(self.current_line_label, "statusKind", "attention" if left_out else "")
        self.line_reason_label.setText(line.reason_text)
        self.line_reason_label.setVisible(bool(line.reason_text))
        details: list[str] = []
        if self.show_numbers_checkbox.isChecked():
            details.extend(_number_lines(line.numbers))
            if line.original_text:
                details.append(f"Before your glossary: {line.original_text}")
            if not details:
                details.append("This package recorded no numbers for this line.")
        self.line_numbers_label.setText("\n".join(details))
        self.line_numbers_label.setVisible(bool(details))

    def _go_to_line(self, finder: Callable[[list[TranscriptLine], float], int | None], nothing: str) -> None:
        if self._transcript is None or self._player is None:
            return
        # From where the operator asked to be, like the 5 second jumps, so
        # quick presses walk down the lines one by one.
        index = finder(self._lines, self._display_ms() / 1000)
        if index is None:
            self._say(nothing)
            return
        self._seek_to(_line_start_ms(self._lines[index]))

    def _go_to_previous_line(self) -> None:
        self._go_to_line(previous_line_index, "There is no line before this.")

    def _go_to_next_line(self) -> None:
        self._go_to_line(next_line_index, "There are no more lines after this.")

    # This recording ---------------------------------------------------------------------
    #
    # Everything below is about the operator's RECORDING, target.recording_path,
    # which is not always the file being played: a package's small review copy
    # can stand in for a recording that has gone missing, and marking the copy
    # would leave the real recording allowed.

    def refresh_recording_row(self) -> None:
        """Bring the This recording row up to date with the lists and the run."""

        self._refresh_recording_row()

    def _recording_texts(self, target: PlayTarget, *, resolve: bool = True) -> tuple[str, ...]:
        """The recording's path as the lists may hold it; the one to store first.

        Find my bug reports stores and compares RESOLVED paths, while a view
        hands this window whatever spelling it has. Both are looked for, and
        the resolved one is what gets stored.
        """

        given = str(target.recording_path)
        resolved = self._resolved_texts.get(given)
        if resolved is None:
            if not resolve:
                return (given,)
            resolved = _resolved_text(target.recording_path, self._resolve_path)
            self._resolved_texts[given] = resolved
        return (resolved,) if path_key(resolved) == path_key(given) else (resolved, given)

    def _on_never_use_list(self, target: PlayTarget, *, resolve: bool = True) -> bool:
        keys = excluded_keys(self._lists())
        return any(path_key(text) in keys for text in self._recording_texts(target, resolve=resolve))

    def _refresh_recording_row(self) -> None:
        target = self._target
        if target is None or target.is_package_file:
            # A clip or a small copy made for a package is not one of the
            # operator's recordings: there is nothing of theirs to put on the
            # never-use list and nothing in a run to skip.
            self.recording_status_label.setText(
                "No recording is open." if target is None else PACKAGE_FILE_STATUS_TEXT
            )
            self._row_shows_excluded = False
            self.never_use_button.setText(NEVER_USE_TEXT)
            self.never_use_button.setEnabled(False)
            self.never_use_button.setToolTip("" if target is None else PACKAGE_FILE_NEVER_USE_TOOLTIP)
            self.skip_button.setVisible(False)
            return
        lists = self._lists()
        # Resolving a path asks the disk, and this runs on the GUI thread. It
        # is only done once the recording has actually loaded, because then the
        # drive is known to be awake. It is never done for a recording that a
        # small copy stands in for: that one is missing, and a missing file on
        # a sleeping or unplugged drive can take as long as the drive takes to
        # give up. Until then the row goes by the spelling it was given, and
        # the library does not look at the file either (244).
        resolve = target.stands_in_for is None and self._media_ready
        texts = self._recording_texts(target, resolve=resolve)
        excluded = self._on_never_use_list(target, resolve=resolve)
        # The click does what THIS caption says. Deciding again at click time,
        # with a differently spelled path, once let a button reading "Never use
        # this recording" take the recording off the list instead.
        self._row_shows_excluded = excluded
        dated = next((text for text in texts if processed_on(lists, text, look=resolve)), texts[0])
        self.recording_status_label.setText(
            "On your never-use list" if excluded else recording_status_text(lists, dated, look=resolve)
        )
        self.never_use_button.setEnabled(True)
        self.never_use_button.setText(ALLOW_AGAIN_TEXT if excluded else NEVER_USE_TEXT)
        self.never_use_button.setToolTip(
            "Takes this recording off your never-use list. The recording itself is never changed."
            if excluded
            else "Stops playback, leaves this recording out of Find my bug reports from now on, and opens "
            "the next recording in the list. The recording itself is never changed."
        )
        # Skip is about the run that is going NOW, so it is only offered
        # while there is one and the host has a way to ask for it.
        running = getattr(self._host, "runner_thread", None) is not None
        can_skip = callable(getattr(self._host, "skip_run_sources", None))
        self.skip_button.setVisible(running and can_skip)
        self.skip_button.setEnabled(path_key(target.recording_path) not in self._skipped_keys)

    def _never_use_or_allow(self) -> None:
        if self._row_shows_excluded:
            self.allow_current_again()
        else:
            self.never_use_current()

    def never_use_current(self) -> None:
        target = self._target
        if target is None or target.is_package_file:
            return
        # 1. Picture and sound stop FIRST. The operator has just said this
        #    recording is of no use; nothing that follows (a disk write, the
        #    next recording loading) may leave it playing meanwhile.
        position_ms = self._display_ms()
        self._pause_now()
        # 2. The list, saved. A never-use that did not reach the disk would
        #    be forgotten at the next start, so it is not acted on either.
        #    Stored the way Find my bug reports spells a recording (resolved),
        #    or that page would go on offering it.
        lists = self._lists()
        stored = self._recording_texts(target)[0]
        try:
            added = not self._on_never_use_list(target) and add_excluded(lists, stored, by=PLAYER_NAME)
            saved = self._save_lists(lists)
        except OSError:
            # The library could not keep it, and changed nothing.
            added, saved = False, False
        if not saved:
            if added:
                remove_excluded(lists, stored)
            self._report_save_failed()
            self._refresh_recording_row()
            return
        # 3. Find my bug reports drops the recording from its list.
        self._notify_lists_changed()
        self.never_use_requested.emit(stored)
        # 4. On to the next one in the list this recording was opened from.
        #    The place is a position in that list's own frozen copy, checked
        #    against the recording's path; no row of a live table is ever
        #    remembered, because step 3 has just removed this recording's row.
        sequence = self._sequence
        recording = target.recording_path
        following, reason = next_target(sequence, recording, excluded_keys(lists))
        if reason == NEXT_FOUND and following is not None:
            message = f'You marked "{recording.name}" never-use.'
            self.open_target(following, sequence=sequence, autoplay=self._autoplay_setting())
        elif reason == NEXT_END_OF_LIST:
            message = END_OF_LIST_TEXT
        else:
            message = NO_LIST_TEXT
        self._undo = _NeverUseUndo(target, position_ms, sequence, message)
        self._show_banner(message, undo=True)
        self._refresh_recording_row()

    def undo_never_use(self) -> None:
        undo = self._undo
        if undo is None:
            return
        # The recording that was opened next may be playing.
        self._pause_now()
        lists = self._lists()
        try:
            removed = [text for text in self._recording_texts(undo.target)
                       if remove_excluded(lists, text, by=PLAYER_NAME)]
            saved = self._save_lists(lists)
        except OSError:
            removed, saved = [], False
        if not saved:
            for text in removed:
                add_excluded(lists, text)
            self._show_banner(SAVE_FAILED_TEXT, undo=True, problem=True)
            return
        self._undo = None
        self._hide_banner()
        self._notify_lists_changed()
        # Back where it was stopped, and paused: the operator is deciding
        # about it, not watching it.
        self.open_target(
            replace(undo.target, start_seconds=undo.position_ms / 1000),
            sequence=undo.sequence,
            autoplay=False,
        )
        self._refresh_recording_row()

    def allow_current_again(self) -> None:
        target = self._target
        if target is None or target.is_package_file:
            return
        lists = self._lists()
        try:
            removed = [text for text in self._recording_texts(target) if remove_excluded(lists, text, by=PLAYER_NAME)]
            saved = self._save_lists(lists)
        except OSError:
            removed, saved = [], False
        if not saved:
            for text in removed:
                add_excluded(lists, text)
            self._report_save_failed()
            self._refresh_recording_row()
            return
        undo = self._undo
        if undo is not None and path_key(undo.target.recording_path) == path_key(target.recording_path):
            self._undo = None
            self._hide_banner()
        self._notify_lists_changed()
        self._refresh_recording_row()
        self._say(f'"{target.recording_path.name}" can be used again.')

    def skip_current(self) -> None:
        target = self._target
        skip = getattr(self._host, "skip_run_sources", None)
        if (
            target is None
            or target.is_package_file
            or not callable(skip)
            or getattr(self._host, "runner_thread", None) is None
        ):
            self._refresh_recording_row()
            return
        try:
            accepted = skip([str(target.recording_path)])
        except (OSError, RuntimeError, ValueError):
            accepted = None
        if accepted:
            self._skipped_keys.add(path_key(target.recording_path))
            self._say("This recording will be skipped in the run that is going now.")
        else:
            self._say("This recording is not waiting in the run that is going now.", "attention")
        self._refresh_recording_row()

    def _show_banner(self, text: str, *, undo: bool, problem: bool = False) -> None:
        self.banner_label.setText(text)
        _set_property(self.banner_label, "operatorState", "error" if problem else "attention")
        self.undo_button.setVisible(undo)
        self.undo_banner.setVisible(True)

    def _hide_banner(self) -> None:
        self.banner_label.setText("")
        self.undo_banner.setVisible(False)

    def _banner_is_problem(self) -> bool:
        return not self.undo_banner.isHidden() and self.banner_label.property("operatorState") == "error"

    def _report_save_failed(self) -> None:
        if self._undo is None:
            self._show_banner(SAVE_FAILED_TEXT, undo=False, problem=True)
            return
        # An earlier never-use DID reach the disk, and its Undo is on offer in
        # the banner. This complaint is about something else and must not take
        # that Undo away, so it goes in the status line.
        self._show_banner(self._undo.message, undo=True)
        self._say(SAVE_FAILED_TEXT, "error")

    def _restore_undo_banner(self) -> None:
        """Take a complaint off the banner, putting back any Undo it covered."""

        if self._undo is None:
            self._hide_banner()
        else:
            self._show_banner(self._undo.message, undo=True)

    # Status and the unplayable card ------------------------------------------------------

    def show_note(self, text: str) -> None:
        """Say something in the status line on behalf of the opener or the main window."""

        self._say(str(text or ""))

    def _say(self, text: str, state: str = "") -> None:
        self.status_label.setText(text)
        _set_property(self.status_label, "operatorState", state)

    def _show_no_recording(self) -> None:
        self._set_transport_enabled(False)
        self._show_transcript_waiting("")
        self._refresh_recording_row()

    def _show_unplayable(self, details: str) -> None:
        if self._unplayable:
            return
        self._unplayable = True
        self._pending_autoplay = False
        self._coalescer.reset()
        self._cancel_step()
        target = self._target
        # What went wrong names the file and can name its folder, so it goes
        # to the log. The card says only what the operator can do about it.
        self.diagnostic.emit(
            f"Built-in player could not play {target.path if target is not None else 'the recording'}: "
            f"{details or 'no details were given'}"
        )
        can_open = callable(getattr(self._opener, "open", None))
        self.open_in_vlc_button.setEnabled(can_open)
        self.open_in_default_button.setEnabled(can_open)
        self.video_stack.setCurrentWidget(self.unplayable_card)
        self._set_transport_enabled(False)
        self._refresh_play_button()
        self._say(UNPLAYABLE_TEXT, "attention")
        if target is not None:
            self.cannot_play.emit(str(target.recording_path))

    def _set_current_line_point_size(self, _scaled: int) -> None:
        # 237: on whole screen pixels at every text size, like every other font.
        self.current_line_label.setStyleSheet(f"font-size: {ui_theme.whole_pixel_pt(CURRENT_LINE_POINT_SIZE)}pt;")

    def _open_elsewhere(self, player_choice: str, _checked: bool = False) -> None:
        opener = getattr(self._opener, "open", None)
        if self._target is None or not callable(opener):
            return
        # This player has just said it cannot play the file. If the other one
        # turns out to be missing, "play it here instead" must not be offered:
        # it would only bring the operator back to this same card.
        opener(
            replace(self._target, start_seconds=self._display_ms() / 1000),
            player=player_choice,
            allow_internal_fallback=False,
        )
