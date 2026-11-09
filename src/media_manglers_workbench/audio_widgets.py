"""Small local audio-preview widgets used by the Workbench."""

from __future__ import annotations

from collections.abc import Sequence
import math

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontInfo,
    QFontMetricsF,
    QHelpEvent,
    QHideEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QPolygonF,
    QResizeEvent,
)
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget


class WaveformSeekWidget(QWidget):
    seek_requested = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._envelope: tuple[float, ...] = ()
        self._position_ratio = 0.0
        self.setMinimumHeight(54)
        self.setToolTip("Click or drag to seek within the selected speech-dense preview region.")

    def set_envelope(self, envelope: tuple[float, ...] | list[float]) -> None:
        self._envelope = tuple(max(0.0, float(value)) for value in envelope)
        self.update()

    def set_position_ratio(self, value: float) -> None:
        self._position_ratio = max(0.0, min(1.0, float(value)))
        self.update()

    def _request_at(self, x_position: float) -> None:
        ratio = max(0.0, min(1.0, x_position / max(1, self.width())))
        self.set_position_ratio(ratio)
        self.seek_requested.emit(ratio)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._request_at(event.position().x())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._request_at(event.position().x())

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#17202a"))
        if self._envelope:
            peak = max(max(self._envelope), 1e-9)
            center = self.height() / 2.0
            painter.setPen(QPen(QColor("#57c7ff"), 1))
            for x in range(max(1, self.width())):
                index = min(len(self._envelope) - 1, int(x * len(self._envelope) / max(1, self.width())))
                height = (self._envelope[index] / peak) * (self.height() * 0.44)
                painter.drawLine(x, int(center - height), x, int(center + height))
        position_x = int(self._position_ratio * self.width())
        painter.setPen(QPen(QColor("#ffcc66"), 2))
        painter.drawLine(position_x, 0, position_x, self.height())


# --- Built-in player timeline (125) -----------------------------------------
# WaveformSeekWidget above speaks in 0..1 ratios of a short preview region and
# is left exactly as it was. The built-in player works on whole recordings, so
# everything below speaks in seconds.

TIMELINE_BACKGROUND = "#17202a"
PLAYHEAD_COLOR = "#ffcc66"
TICK_KEPT = "#57c7ff"
TICK_LEFT_OUT = "#ffb454"
RULER_TEXT_COLOR = "#9aa6b2"
RULER_MARK_COLOR = "#3a444f"

TIMELINE_MIN_HEIGHT = 46
# Ruler labels may only sit this many seconds apart, so the times read as
# round numbers whatever the recording's length and the window's width.
RULER_STEPS_SECONDS = (1, 5, 10, 30, 60, 300, 600, 1800, 3600)
# A rejected stretch is often a few pixels of a multi-hour recording; below
# this width it could not be told apart from an ordinary mark.
REJECTED_SPAN_MIN_WIDTH = 6

_RULER_MIN_HEIGHT = 16
_RULER_LABEL_OFFSET = 3
_RULER_LABEL_GAP = 10
_MINOR_MARK_MIN_SPACING = 4
# Alignment and text flags are different enums, so they are joined as numbers.
# TextDontClip: a digit a hair wider than the measured one is not cut in half.
_RULER_LABEL_FLAGS = (
    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
).value | Qt.TextFlag.TextDontClip.value
_TICK_KINDS = ("kept", "left_out", "rejected_span")


def _finite(value: object) -> float | None:
    """``value`` as a float, or None when it is not a usable number."""

    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def format_hms(milliseconds: int | float, *, tenths: bool = False) -> str:
    """``H:MM:SS`` (or ``H:MM:SS.t``) for a position in a recording.

    Hours are always shown, because recordings run for hours and a readout
    that changes shape part-way through is harder to scan. The value is cut
    off, never rounded up: a clock must not show a time that has not been
    reached yet. Anything below zero or not a number reads as ``0:00:00``.
    """

    number = _finite(milliseconds)
    total_tenths = int(max(0.0, number or 0.0)) // 100
    total_seconds, tenth = divmod(total_tenths, 10)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    text = f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{text}.{tenth}" if tenths else text


def _ruler_step_seconds(duration: float, width: int, label_width: float) -> int:
    """Seconds between ruler labels so that neighbouring labels never touch.

    ``label_width`` is the room one label needs, in pixels, gap included.
    Returns 0 when there is nothing to measure.
    """

    if duration <= 0 or width <= 0 or label_width <= 0:
        return 0
    seconds_per_label = duration * label_width / width
    for step in RULER_STEPS_SECONDS:
        if step >= seconds_per_label:
            return step
    # Longer than the ladder covers (a very long recording in a narrow bar):
    # keep to whole hours rather than let the labels collide.
    return 3600 * math.ceil(seconds_per_label / 3600)


def _minor_step_seconds(major_step: int) -> int:
    """The next rung down that divides ``major_step`` evenly, or 0."""

    smaller = [step for step in RULER_STEPS_SECONDS if step < major_step and major_step % step == 0]
    return smaller[-1] if smaller else 0


class TimelineBar(QWidget):
    """The built-in player's timeline: ruler, transcript marks and playhead.

    The ruler and the marks never change while a recording plays, and a long
    recording has thousands of marks, so they are drawn once into a cached
    pixmap. Only the playhead is drawn on every paint.
    """

    seek_requested = Signal(float)  # seconds into the recording
    scrub_started = Signal()
    scrub_finished = Signal()
    # 125 Part 2: a click on a moment's mark, with the index of the first moment it stands for.
    moment_clicked = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._duration = 0.0
        self._position = 0.0
        self._ticks: tuple[tuple[float, str, float], ...] = ()
        self._moments: tuple[tuple[float, bool, str], ...] = ()
        self._moment_marks: list[_MomentMark] | None = None
        self._ruler_bottom = _RULER_MIN_HEIGHT
        self._scrubbing = False
        self._last_scrub_seconds: float | None = None
        self._tick_layer: QPixmap | None = None
        self._tick_layer_renders = 0
        self.setMinimumHeight(TIMELINE_MIN_HEIGHT)
        # Extra window height belongs to the picture, not to the timeline.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # The player window owns every shortcut; a click here must not take
        # keyboard focus away from it.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip(
            "Click or drag to move through the recording. Blue marks are transcript lines; "
            "amber marks are lines that were left out."
        )

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(640, TIMELINE_MIN_HEIGHT)

    def set_duration(self, seconds: float) -> None:
        duration = max(0.0, _finite(seconds) or 0.0)
        if duration == self._duration:
            return
        self._duration = duration
        self._invalidate_tick_layer()

    def set_position(self, seconds: float) -> None:
        # Only the lower bound is applied here. The player sets a start
        # position before the recording has reported how long it is, and
        # clamping against a duration of 0 would throw that position away.
        # The upper bound is applied wherever the position is read.
        before = self._playhead_x()
        self._position = max(0.0, _finite(seconds) or 0.0)
        # The player reports a position for every frame; across a multi-hour
        # recording almost none of those move the playhead by a whole pixel.
        if self._playhead_x() != before:
            self.update()

    def set_ticks(self, ticks: Sequence[tuple[float, str] | tuple[float, str, float]]) -> None:
        """Replace the transcript marks: ``(seconds, kind)`` per line.

        ``kind`` is ``"kept"``, ``"left_out"`` or ``"rejected_span"``. A
        rejected span may carry its end as a third value so the bar can show
        its true length; without one it is drawn at the minimum width.
        Anything else - an unknown kind, a time that is not a number - is
        skipped, so a newer package can never stop the recording opening.
        """

        cleaned: list[tuple[float, str, float]] = []
        for tick in ticks or ():
            try:
                start = _finite(tick[0])
                kind = tick[1]
                end = _finite(tick[2]) if len(tick) > 2 else None
            except (TypeError, IndexError, KeyError):
                continue
            if start is None or kind not in _TICK_KINDS:
                continue
            start = max(0.0, start)
            cleaned.append((start, kind, max(start, end if end is not None else start)))
        marks = tuple(cleaned)
        if marks == self._ticks:
            return
        self._ticks = marks
        self._invalidate_tick_layer()

    def set_moments(self, moments: Sequence[tuple[float, bool, str]]) -> None:
        """125 Part 2: what the package found, as ``(seconds, is_a_finding, words)`` in time order.

        A finding (a bug-report moment) is drawn strong, a moment of talking pale. Kept apart from the
        transcript marks, so a kind ``set_ticks`` does not know is still skipped there.
        """

        cleaned: list[tuple[float, bool, str]] = []
        for moment in moments or ():
            try:
                seconds = _finite(moment[0])
                strong = bool(moment[1])
                words = str(moment[2] or "")
            except (TypeError, IndexError):
                continue
            if seconds is not None:
                cleaned.append((max(0.0, seconds), strong, words))
        marks = tuple(cleaned)
        if marks == self._moments:
            return
        self._moments = marks
        self._invalidate_tick_layer()

    def moment_marks(self) -> list["_MomentMark"]:
        """Where each moment's mark is drawn; moments of one kind closer than a few pixels share one."""

        if self._moment_marks is None:
            self._moment_marks = _merge_moments(self._moments, self._duration, max(1, self.width()))
        return self._moment_marks

    def _moment_near(self, x: float, y: float | None = None) -> "_MomentMark | None":
        # Only the moments' own band under the ruler: the ruler itself drags the playhead as before.
        if y is not None and not self._ruler_bottom <= y <= self._ruler_bottom + MOMENT_BAND_HEIGHT + 4:
            return None
        near = [mark for mark in self.moment_marks() if abs(mark.x - x) <= MOMENT_HIT_PX]
        return min(near, key=lambda mark: (abs(mark.x - x), not mark.strong)) if near else None

    def event(self, event: QEvent) -> bool:  # noqa: D102
        if event.type() == QEvent.Type.ToolTip and isinstance(event, QHelpEvent):
            mark = self._moment_near(event.position().x(), event.position().y())
            if mark is not None:
                QToolTip.showText(event.globalPos(), mark.tooltip(), self)
                return True
        return super().event(event)

    def seconds_at(self, x: float) -> float:
        ratio = (_finite(x) or 0.0) / max(1, self.width())
        return max(0.0, min(1.0, ratio)) * self._duration

    def position_seconds(self) -> float:
        return min(self._position, self._duration)

    def _playhead_x(self) -> int:
        if self._duration <= 0:
            return 0
        width = max(1, self.width())
        # Kept one pixel inside each edge so the 2 px line is whole at 0:00:00
        # and at the very end.
        return max(1, min(width - 1, round(self.position_seconds() / self._duration * width)))

    def _invalidate_tick_layer(self) -> None:
        # Rebuilt by the next paint, so several changes in a row cost one render.
        self._tick_layer = None
        self._moment_marks = None
        self.update()

    def _seek_to(self, x: float) -> None:
        if self._duration <= 0:
            return
        seconds = self.seconds_at(x)
        self._last_scrub_seconds = seconds
        self.set_position(seconds)
        self.seek_requested.emit(seconds)

    def _finish_scrub(self, x: float | None = None) -> None:
        if not self._scrubbing:
            return
        self._scrubbing = False
        if x is not None:
            self._seek_to(x)
        # Always sent once a scrub has started, even when the recording went
        # away mid-drag: the player pauses on scrub_started and would stay
        # paused for good without the matching finish.
        self.scrub_finished.emit()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        if self._duration <= 0:
            return
        # 125 Part 2: a click on a moment's mark goes to that moment exactly, not to the pixel.
        mark = None if self._scrubbing else self._moment_near(event.position().x(), event.position().y())
        if mark is not None:
            self.set_position(mark.seconds)
            self.seek_requested.emit(mark.seconds)
            self.moment_clicked.emit(mark.first)
            return
        # A release can be lost (the window lost the mouse mid-drag). That
        # scrub is still open as far as the player knows, so carry on with it
        # rather than start a second one that would never be finished.
        if not self._scrubbing:
            self._scrubbing = True
            self.scrub_started.emit()
        self._seek_to(event.position().x())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._scrubbing:
            return
        if not event.buttons() & Qt.MouseButton.LeftButton:
            # Only reachable with mouse tracking on: a move with no button
            # held means the release went somewhere else.
            self._finish_scrub()
            return
        x_position = event.position().x()
        # Up-and-down wobble lands on the same moment; asking the player to
        # seek there again would only slow the preview picture down.
        if self.seconds_at(x_position) == self._last_scrub_seconds:
            return
        self._seek_to(x_position)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        self._finish_scrub(event.position().x())

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802
        # No release can arrive once the bar is hidden.
        self._finish_scrub()
        super().hideEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._invalidate_tick_layer()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        layer = self._tick_layer
        # Dragging the window to a screen with a different scale changes the
        # size in real pixels without a resize event.
        if layer is None or layer.devicePixelRatio() != self.devicePixelRatioF():
            layer = self._tick_layer = self._render_tick_layer()
        painter = QPainter(self)
        painter.drawPixmap(0, 0, layer)
        if self._duration <= 0:
            return
        position_x = self._playhead_x()
        color = QColor(PLAYHEAD_COLOR)
        painter.fillRect(QRectF(position_x - 1, 0, 2, self.height()), color)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(position_x - 5, 0),
                    QPointF(position_x + 5, 0),
                    QPointF(position_x, 7),
                ]
            )
        )

    def _render_tick_layer(self) -> QPixmap:
        ratio = self.devicePixelRatioF()
        width = max(1, self.width())
        height = max(1, self.height())
        layer = QPixmap(math.ceil(width * ratio), math.ceil(height * ratio))
        layer.setDevicePixelRatio(ratio)
        layer.fill(QColor(TIMELINE_BACKGROUND))
        painter = QPainter(layer)
        try:
            ruler_height = self._paint_ruler(painter, width, height)
            self._ruler_bottom = ruler_height
            self._paint_ticks(painter, width, height, ruler_height)
            self._paint_moments(painter, ruler_height)
        finally:
            painter.end()
        self._tick_layer_renders += 1
        return layer

    def _paint_ruler(self, painter: QPainter, width: int, height: int) -> int:
        font = QFont(self.font())
        # 237: a whole number of pixels, so the ruler's numbers are drawn sharp at every text size.
        font.setPixelSize(max(8, int(round(QFontInfo(self.font()).pixelSize() * 0.8))))
        metrics = QFontMetricsF(font)
        # A large system font gets a taller ruler, but never so tall that the
        # transcript marks below it are squeezed out.
        ruler_height = max(_RULER_MIN_HEIGHT, min(math.ceil(metrics.height()) + 2, height - 24))
        mark_color = QColor(RULER_MARK_COLOR)
        painter.fillRect(QRectF(0, ruler_height - 1, width, 1), mark_color)
        if self._duration <= 0:
            return ruler_height
        # Every label is measured as the widest one: the last label is the
        # longest, and "8" is as wide as any digit gets.
        widest = "".join("8" if char.isdigit() else char for char in format_hms(self._duration * 1000))
        text_width = metrics.horizontalAdvance(widest)
        step = _ruler_step_seconds(
            self._duration, width, text_width + _RULER_LABEL_OFFSET + _RULER_LABEL_GAP
        )
        if step <= 0:
            return ruler_height
        minor = _minor_step_seconds(step)
        if minor and minor * width / self._duration >= _MINOR_MARK_MIN_SPACING:
            for index in range(int(self._duration // minor) + 1):
                if (index * minor) % step:
                    x_position = math.floor(index * minor / self._duration * width)
                    painter.fillRect(QRectF(x_position, ruler_height - 5, 1, 4), mark_color)
        painter.setFont(font)
        painter.setPen(QPen(QColor(RULER_TEXT_COLOR)))
        for index in range(int(self._duration // step) + 1):
            x_position = math.floor(index * step / self._duration * width)
            painter.fillRect(QRectF(x_position, 0, 1, ruler_height), mark_color)
            text_x = x_position + _RULER_LABEL_OFFSET
            # A label that would run off the right edge is dropped rather
            # than shown cut in half; its mark stays.
            if text_x + text_width <= width:
                painter.drawText(
                    QRectF(text_x, 0, text_width + 1, ruler_height - 2),
                    _RULER_LABEL_FLAGS,
                    format_hms(index * step * 1000),
                )
        return ruler_height

    def _paint_ticks(self, painter: QPainter, width: int, height: int, ruler_height: int) -> None:
        if self._duration <= 0 or not self._ticks:
            return
        lane_top = ruler_height + 3
        lane_height = max(5, height - 8 - lane_top)
        kept_color = QColor(TICK_KEPT)
        left_out_color = QColor(TICK_LEFT_OUT)
        # Drawn kind by kind, kept lines first, and the left-out marks are
        # wider and taller: on a crowded timeline the amber marks are the ones
        # the operator is hunting for, so they must not vanish under the blue.
        for kind in _TICK_KINDS:
            for start, tick_kind, end in self._ticks:
                if tick_kind != kind or start > self._duration:
                    continue
                x_position = math.floor(start / self._duration * width)
                if kind == "kept":
                    painter.fillRect(
                        QRectF(min(x_position, width - 1), lane_top + 4, 1, lane_height - 4),
                        kept_color,
                    )
                elif kind == "left_out":
                    painter.fillRect(
                        QRectF(min(x_position, width - 2), lane_top, 2, lane_height),
                        left_out_color,
                    )
                else:
                    # A whole rejected stretch: a thin bar under the marks,
                    # starting where the stretch starts.
                    span_end = min(end, self._duration) / self._duration * width
                    span_width = max(REJECTED_SPAN_MIN_WIDTH, math.ceil(span_end) - x_position)
                    x_position = max(0, min(x_position, width - REJECTED_SPAN_MIN_WIDTH))
                    painter.fillRect(
                        QRectF(x_position, height - 5, min(span_width, width - x_position), 3),
                        left_out_color,
                    )

    def _paint_moments(self, painter: QPainter, ruler_height: int) -> None:
        # 125 Part 2: a small mark under the ruler for each moment the package found, drawn last so
        # the transcript marks never hide one. Findings are strong, moments of talking pale.
        if self._duration <= 0 or not self._moments:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        top = ruler_height + 1
        for mark in sorted(self.moment_marks(), key=lambda item: item.strong):
            painter.setBrush(QColor(MOMENT_FINDING if mark.strong else MOMENT_TALK))
            half = MOMENT_MARK_WIDTH / 2
            painter.drawPolygon(QPolygonF([
                QPointF(mark.x - half, top),
                QPointF(mark.x + half, top),
                QPointF(mark.x, top + MOMENT_BAND_HEIGHT),
            ]))
            if mark.count > 1:
                painter.fillRect(QRectF(mark.x - half, top + MOMENT_BAND_HEIGHT + 1, MOMENT_MARK_WIDTH, 2),
                                 QColor(MOMENT_FINDING if mark.strong else MOMENT_TALK))
        painter.restore()


# --- Waveform lanes and moments (125 Part 2, Wave 8) -------------------------------------------
# The lanes are one row per audio track under the timeline, across the whole recording, from the
# levels the shared levels job measured (one value per second). Each column shows the loudest second
# it covers, on one fixed scale for every track, so a short burst on a multi-hour recording still
# shows and a quiet track looks quiet.

LANES_HEIGHT = 60
LANES_MIN_HEIGHT = 42
LANE_LABEL_WIDTH = 112
LANE_GAP = 1
LANE_FLOOR_DBFS = -60.0
LANE_BACKGROUND = "#141b23"
LANE_UNMEASURED = "#0f151b"
LANE_WAVE = "#3d6a87"
LANE_WAVE_HEARD = "#57c7ff"
LANE_LABEL = "#8c98a5"
LANE_LABEL_HEARD = "#ffcc66"
LANE_MESSAGE = "#c8d2dc"
LANES_TOOLTIP = "Each track's sound across the whole recording. Click a lane to go there; click a track's name to hear it."
MOMENT_FINDING = "#ff7a90"
MOMENT_TALK = "#7f8fa0"
MOMENT_MARK_WIDTH = 8
MOMENT_BAND_HEIGHT = 7
MOMENT_MERGE_PX = 6
MOMENT_HIT_PX = 5
MOMENT_TOOLTIP_LINES = 8


class _MomentMark:
    """One mark on the timeline: one moment, or several of one kind that would overlap."""

    __slots__ = ("x", "seconds", "strong", "first", "texts")

    def __init__(self, x: float, seconds: float, strong: bool, first: int, text: str) -> None:
        self.x = x
        self.seconds = seconds
        self.strong = strong
        self.first = first
        self.texts = [text]

    @property
    def count(self) -> int:
        return len(self.texts)

    def tooltip(self) -> str:
        shown = self.texts[:MOMENT_TOOLTIP_LINES]
        more = len(self.texts) - len(shown)
        return "\n".join(shown + ([f"…and {more} more here"] if more > 0 else []))


def _merge_moments(moments: Sequence[tuple[float, bool, str]], duration: float, width: int) -> list[_MomentMark]:
    marks: list[_MomentMark] = []
    if duration <= 0 or width <= 0:
        return marks
    last: dict[bool, _MomentMark] = {}
    for index, (seconds, strong, text) in enumerate(moments):
        if seconds > duration:
            continue
        x = min(width - 1.0, max(0.0, seconds / duration * width))
        previous = last.get(strong)
        if previous is not None and x - previous.x < MOMENT_MERGE_PX:
            previous.texts.append(text)
            continue
        mark = last[strong] = _MomentMark(x, seconds, strong, index, text)
        marks.append(mark)
    return marks


def level_columns(levels: Sequence[float], duration: float, width: int) -> list[float | None]:
    """The loudest level (dBFS) under each of ``width`` columns; None where nothing is measured yet."""

    if width <= 0 or duration <= 0:
        return []
    count = len(levels)
    columns: list[float | None] = []
    for column in range(width):
        start = int(column * duration / width)
        end = max(start + 1, int((column + 1) * duration / width))
        if start >= count:
            columns.append(None)
            continue
        columns.append(max(float(value) for value in levels[start:min(end, count)]))
    return columns


class TrackLanes(QWidget):
    """The built-in player's waveform lanes, one per audio track (125 Part 2).

    Drawn once into a cached picture whenever the levels or the size change; only the playhead is
    drawn on every paint. A click or drag on a lane moves through the recording; a click on a
    track's name asks to hear that track. While the sound is still being measured, the part not
    measured yet stays dark and a short message says how far it is.
    """

    seek_requested = Signal(float)  # seconds into the recording
    lane_chosen = Signal(int)  # 1-based track number

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._labels: dict[int, str] = {}
        self._levels: dict[int, list[float]] = {}
        self._duration = 0.0
        self._position = 0.0
        self._heard: int | None = None
        self._message = ""
        self._layer: QPixmap | None = None
        self._renders = 0
        self._dragging = False
        # Their full band everywhere but on a short window (a 1366x768 laptop), where they give some up.
        self.setMinimumHeight(LANES_MIN_HEIGHT)
        self.setMaximumHeight(LANES_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        # The player window owns every shortcut; a click here must not take the keyboard.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip(LANES_TOOLTIP)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(640, LANES_HEIGHT)

    # What the player hands over ------------------------------------------------------------

    def set_tracks(self, labels: dict[int, str]) -> None:
        """The lanes, in order: track number -> its name on screen."""

        cleaned = {int(track): str(text) for track, text in labels.items()}
        if cleaned != self._labels:
            self._labels = cleaned
            self._invalidate()

    def set_levels(self, levels: dict[int, list[float]], duration_seconds: float) -> None:
        self._levels = {int(track): list(values) for track, values in levels.items()}
        self._duration = max(0.0, _finite(duration_seconds) or 0.0)
        self._invalidate()

    def set_heard(self, track: int | None) -> None:
        if track != self._heard:
            self._heard = track
            self._invalidate()

    def set_message(self, text: str) -> None:
        text = str(text or "")
        if text != self._message:
            self._message = text
            self._invalidate()

    def set_position(self, seconds: float) -> None:
        before = self._playhead_x()
        self._position = max(0.0, _finite(seconds) or 0.0)
        if self._playhead_x() != before:
            self.update()

    def tracks(self) -> list[int]:
        return list(self._labels)

    # Geometry --------------------------------------------------------------------------------

    def _lane_rects(self) -> list[tuple[int, QRectF]]:
        tracks = list(self._labels)
        if not tracks:
            return []
        height = (self.height() - LANE_GAP * (len(tracks) - 1)) / len(tracks)
        return [(track, QRectF(0, index * (height + LANE_GAP), self.width(), height))
                for index, track in enumerate(tracks)]

    def lane_at(self, y: float) -> int | None:
        for track, rect in self._lane_rects():
            if rect.top() <= y < rect.bottom() + LANE_GAP:
                return track
        return None

    def _wave_width(self) -> int:
        return max(1, self.width() - LANE_LABEL_WIDTH)

    def seconds_at(self, x: float) -> float:
        ratio = ((_finite(x) or 0.0) - LANE_LABEL_WIDTH) / self._wave_width()
        return max(0.0, min(1.0, ratio)) * self._duration

    def _playhead_x(self) -> int:
        if self._duration <= 0:
            return -1
        ratio = min(self._position, self._duration) / self._duration
        return LANE_LABEL_WIDTH + round(ratio * self._wave_width())

    # Mouse -----------------------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        x = event.position().x()
        if x < LANE_LABEL_WIDTH:
            track = self.lane_at(event.position().y())
            if track is not None:
                self.lane_chosen.emit(track)
            return
        if self._duration > 0:
            self._dragging = True
            self._seek_to(x)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self._seek_to(event.position().x())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._dragging = False
        super().mouseReleaseEvent(event)

    def _seek_to(self, x: float) -> None:
        seconds = self.seconds_at(x)
        self.set_position(seconds)
        self.seek_requested.emit(seconds)

    def event(self, event: QEvent) -> bool:  # noqa: D102
        if event.type() == QEvent.Type.ToolTip and isinstance(event, QHelpEvent):
            track = self.lane_at(event.position().y())
            if track is not None:
                QToolTip.showText(event.globalPos(), f"{self._labels.get(track, '')}\n{LANES_TOOLTIP}", self)
                return True
        return super().event(event)

    # Drawing ---------------------------------------------------------------------------------

    def _invalidate(self) -> None:
        self._layer = None
        self.update()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._invalidate()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        layer = self._layer
        if layer is None or layer.devicePixelRatio() != self.devicePixelRatioF():
            layer = self._layer = self._render()
        painter = QPainter(self)
        painter.drawPixmap(0, 0, layer)
        x = self._playhead_x()
        if x >= LANE_LABEL_WIDTH:
            painter.fillRect(QRectF(x - 1, 0, 2, self.height()), QColor(PLAYHEAD_COLOR))

    def _render(self) -> QPixmap:
        ratio = self.devicePixelRatioF()
        width, height = max(1, self.width()), max(1, self.height())
        layer = QPixmap(math.ceil(width * ratio), math.ceil(height * ratio))
        layer.setDevicePixelRatio(ratio)
        layer.fill(QColor(TIMELINE_BACKGROUND))
        painter = QPainter(layer)
        try:
            wave_width = self._wave_width()
            font = QFont(self.font())
            rects = self._lane_rects()
            lane_height = rects[0][1].height() if rects else 0
            font.setPixelSize(max(7, min(11, int(lane_height))))
            painter.setFont(font)
            metrics = QFontMetricsF(font)
            for track, rect in rects:
                heard = track == self._heard
                painter.fillRect(QRectF(LANE_LABEL_WIDTH, rect.top(), wave_width, rect.height()), QColor(LANE_BACKGROUND))
                columns = level_columns(self._levels.get(track, []), self._duration, wave_width)
                color = QColor(LANE_WAVE_HEARD if heard else LANE_WAVE)
                dark = QColor(LANE_UNMEASURED)
                for column, value in enumerate(columns):
                    x = LANE_LABEL_WIDTH + column
                    if value is None:
                        painter.fillRect(QRectF(x, rect.top(), 1, rect.height()), dark)
                        continue
                    share = (max(LANE_FLOOR_DBFS, min(0.0, value)) - LANE_FLOOR_DBFS) / -LANE_FLOOR_DBFS
                    bar = share * rect.height()
                    if bar >= 0.5:
                        painter.fillRect(QRectF(x, rect.bottom() - bar, 1, bar), color)
                painter.setPen(QPen(QColor(LANE_LABEL_HEARD if heard else LANE_LABEL)))
                label = metrics.elidedText(self._labels.get(track, ""), Qt.TextElideMode.ElideRight, LANE_LABEL_WIDTH - 6)
                painter.drawText(QRectF(3, rect.top(), LANE_LABEL_WIDTH - 6, rect.height()),
                                 int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label)
            if self._message:
                painter.setPen(QPen(QColor(LANE_MESSAGE)))
                message_font = QFont(self.font())
                message_font.setPixelSize(11)
                painter.setFont(message_font)
                painter.drawText(QRectF(LANE_LABEL_WIDTH + 6, 0, wave_width - 12, height),
                                 int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), self._message)
        finally:
            painter.end()
        self._renders += 1
        return layer
