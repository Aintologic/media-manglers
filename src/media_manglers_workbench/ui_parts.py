"""The shared parts every screen uses (`governance/UI_RULES.md` section 7, 237).

- ``StatusPill``: one status word, coloured by the one status rule (``theme.status_kind``).
- ``InlineFeedback``: what a button is doing, next to the button: working, done for a few seconds,
  or failed with the next step until dismissed.
- ``bind_action``: wires a button to its action so the feedback shows within a quarter of a second
  and the button cannot be fired twice while it works.
- ``JobBanner``: a long job, on the page where it was started: what is running, a bar, percent and
  time left when known, and "Open in Queue / Progress", which opens that job.
- ``StepBar``: numbered steps, done / current / later.
- ``SegmentedControl``: two to four exclusive choices in one rounded box (the text size).
- ``PageStack``: the page area; each page sits in a scroll area, so large text scrolls instead of
  squeezing or cutting off controls.
- ``polish_views``: the selection bar and row height of tables and trees.
- ``warn``: every warning pop-up, shown as before and also written to the Workbench log (224, F1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QObject, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QBoxLayout,
    QButtonGroup,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QTreeView,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from media_manglers.core.voice_track import clock as recording_clock

from . import theme
from .theme import status_kind

# Section 7: how long a done confirmation stays before it goes.
DONE_SECONDS = 4.0
# Section 5: the four kinds of button.
BUTTON_KINDS = ("primary", "secondary", "danger", "link")
OPEN_IN_PROGRESS = "Open in Queue / Progress"
DEFAULT_NEXT_STEP = "Try again. If it keeps failing, open Settings > Advanced / Diagnostics for the logs."


def warn(parent: QWidget, title: str, text: str, buttons: Any = None, default: Any = None, *,
         wait: bool = True) -> Any:
    """Every warning pop-up (224, F1): the same box as before, and one line in the Workbench log, written before
    the box opens, so a run that never started still leaves its reason in the log. With ``buttons`` the answer
    is logged too and returned. ``wait=False`` is a notice that does not stop the window (243, 275): it opens
    once the window is shown, and the box is returned so its owner can keep it."""

    _log_in_workbench(parent, f"Warning shown: {title}: {' '.join(str(text).split())}")
    if not wait:
        notice = QMessageBox(QMessageBox.Icon.Warning, title, text, parent=parent)
        notice.setModal(False)
        QTimer.singleShot(0, notice.show)
        return notice
    if buttons is None:
        return QMessageBox.warning(parent, title, text)
    answer = QMessageBox.warning(parent, title, text, buttons,
                                 QMessageBox.StandardButton.NoButton if default is None else default)
    _log_in_workbench(parent, f"Warning answered: {title}: {getattr(answer, 'name', answer)}")
    return answer


def _log_in_workbench(widget: QWidget | None, line: str) -> None:
    """The Workbench window's log, found from any widget inside it (a page, or a dialog opened over one)."""

    current = widget
    while current is not None:
        write = getattr(current.window(), "_write_workbench_log", None)
        if callable(write):
            write(line)
            return
        current = current.parentWidget()


def repolish(widget: QWidget) -> None:
    """Style ``widget`` again after a property the stylesheet reads has changed.

    224 (Wave B2a, 5d): a label measures its border and padding only when it is first styled, so a box style
    given later drew its outline with the text pressed against it. The style-change event makes it measure
    again."""

    widget.style().unpolish(widget)
    widget.style().polish(widget)
    QCoreApplication.sendEvent(widget, QEvent(QEvent.Type.StyleChange))


_repolish = repolish


def _restyle(widget: QWidget, name: str, value: Any) -> None:
    """Set a style property, re-styling only when it changed (re-styling is not cheap)."""

    if widget.property(name) != value:
        widget.setProperty(name, value)
        _repolish(widget)


def set_button_kind(button: QAbstractButton, kind: str) -> None:
    """Make a button primary, secondary, danger or link (section 5). Primary keeps the old property."""

    if kind not in BUTTON_KINDS:
        raise ValueError(f"Unknown button kind: {kind}")
    button.setProperty("primary", kind == "primary")
    button.setProperty("kind", kind)
    if kind == "link":
        button.setCursor(Qt.CursorShape.PointingHandCursor)
    _repolish(button)


def button_kind(button: QAbstractButton) -> str:
    if button.property("primary"):
        return "primary"
    kind = str(button.property("kind") or "")
    return kind if kind in BUTTON_KINDS else "secondary"


class BoldSafeButton(QPushButton):
    """A button whose text turns bold when it is the chosen one (a tab, a segment): it is measured in
    the bold weight, so the chosen text is never cut off at either end."""

    def _bold_extra(self) -> int:
        bold = QFont(self.font())
        bold.setWeight(QFont.Weight.DemiBold)
        extra = QFontMetrics(bold).horizontalAdvance(self.text()) - self.fontMetrics().horizontalAdvance(self.text())
        return max(0, extra) + 2

    def sizeHint(self) -> QSize:  # noqa: N802
        hint = super().sizeHint()
        return QSize(hint.width() + self._bold_extra(), hint.height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        hint = super().minimumSizeHint()
        return QSize(hint.width() + self._bold_extra(), hint.height())


# Line icons -------------------------------------------------------------------------------------

NAV_ICON_FOLDER = theme._ASSETS / "nav"
# 236: the AI Video Editor's toolbar, its scenes' pen and its play buttons, drawn the same way.
TOOL_ICON_FOLDER = theme._ASSETS / "tools"


def _icon_pixmap(svg: str, colour: str, size: int, ratio: float) -> QPixmap:
    drawn = max(1, int(round(size * ratio)))
    text = svg.replace("currentColor", colour).replace('width="24" height="24"', f'width="{drawn}" height="{drawn}"')
    pixmap = QPixmap()
    pixmap.loadFromData(text.encode("utf-8"), "SVG")
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def line_icon(name: str, colour: str, chosen_colour: str, size: int, folder: Any = None) -> QIcon:
    """One of the app's own line icons (assets/nav, or ``folder``), in ``colour``, and ``chosen_colour``
    when its button is the chosen one (checked)."""

    svg = ((folder or NAV_ICON_FOLDER) / f"{name}.svg").read_text(encoding="utf-8")
    _dpi, ratio = theme.screen_metrics()
    icon = QIcon()
    for mode in (QIcon.Mode.Normal, QIcon.Mode.Active, QIcon.Mode.Selected):
        icon.addPixmap(_icon_pixmap(svg, colour, size, ratio), mode, QIcon.State.Off)
        icon.addPixmap(_icon_pixmap(svg, chosen_colour, size, ratio), mode, QIcon.State.On)
    return icon


# Status pill ------------------------------------------------------------------------------------


class StatusPill(QLabel):
    """One status word in a rounded pill; its colour comes from status_kind (105)."""

    def __init__(self, state: str = "", text: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.state = ""
        self.set_status(state, text)

    @property
    def kind(self) -> str:
        return str(self.property("pill") or "")

    def set_status(self, state: str, text: str | None = None) -> None:
        self.state = str(state or "")
        shown = text if text is not None else self.state.replace("_", " ").strip().capitalize()
        self.setText(shown)
        self.setProperty("pill", status_kind(self.state))
        self.setAccessibleName(f"Status: {shown}")
        _repolish(self)


# Feedback where you click -----------------------------------------------------------------------


class InlineFeedback(QWidget):
    """The line beside a button: working, done (goes after a few seconds), failed (stays until dismissed)."""

    dismissed = Signal()

    IDLE, WORKING, DONE, FAILED = "", "working", "done", "failed"

    def __init__(self, parent: QWidget | None = None, *, done_seconds: float = DONE_SECONDS) -> None:
        super().__init__(parent)
        self.done_seconds = done_seconds
        self.state = self.IDLE
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.px(6))
        self.label = QLabel("")
        self.label.setObjectName("inlineFeedbackText")
        self.label.setWordWrap(True)
        self.label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.label, 1)
        self.dismiss_button = QPushButton("Dismiss")
        self.dismiss_button.setObjectName("inlineFeedbackDismiss")
        set_button_kind(self.dismiss_button, "link")
        self.dismiss_button.setVisible(False)
        self.dismiss_button.clicked.connect(self.dismiss)
        layout.addWidget(self.dismiss_button)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.clear)
        self.setVisible(False)

    def text(self) -> str:
        return self.label.text()

    def _show(self, state: str, text: str) -> None:
        self._timer.stop()
        self.state = state
        self.label.setText(text)
        self.label.setProperty("feedback", state)
        self.label.setAccessibleName(text)
        _repolish(self.label)
        self.dismiss_button.setVisible(state == self.FAILED)
        self.setVisible(True)

    def working(self, text: str) -> None:
        self._show(self.WORKING, text)

    def done(self, text: str, seconds: float | None = None) -> None:
        self._show(self.DONE, text)
        wait = self.done_seconds if seconds is None else seconds
        if wait > 0:
            self._timer.start(int(wait * 1000))

    def failed(self, text: str, next_step: str = "") -> None:
        message = text.strip()
        if next_step:
            message = f"{message.rstrip('.')}. {next_step.strip()}" if message else next_step.strip()
        self._show(self.FAILED, message)

    def clear(self) -> None:
        self._timer.stop()
        self.state = self.IDLE
        self.label.setText("")
        self.label.setProperty("feedback", "")
        self.dismiss_button.setVisible(False)
        self.setVisible(False)

    def dismiss(self) -> None:
        self.clear()
        self.dismissed.emit()


@dataclass(frozen=True)
class Outcome:
    """What a button's action reports: done (with its own words), failed (with the next step), or
    quiet (nothing to say, for example a dialog the operator cancelled)."""

    kind: str
    text: str = ""
    next_step: str = ""

    @classmethod
    def done(cls, text: str = "") -> "Outcome":
        return cls("done", text)

    @classmethod
    def failed(cls, text: str, next_step: str = "") -> "Outcome":
        return cls("failed", text, next_step)

    @classmethod
    def quiet(cls) -> "Outcome":
        return cls("quiet")


def _layout_holding(layout: QLayout | None, widget: QWidget) -> QLayout | None:
    if layout is None:
        return None
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item is None:
            continue
        if item.widget() is widget:
            return layout
        found = _layout_holding(item.layout(), widget)
        if found is not None:
            return found
    return None


def place_beside(anchor: QWidget, widget: QWidget) -> bool:
    """Put ``widget`` right after ``anchor`` in the layout that holds it. False when it is in none yet."""

    parent = anchor.parentWidget()
    layout = _layout_holding(parent.layout() if parent is not None else None, anchor)
    if layout is None:
        return False
    if isinstance(layout, (QBoxLayout, FlowLayout)):
        layout.insertWidget(layout.indexOf(anchor) + 1, widget)
        return True
    # A grid or form row: the anchor and the feedback share one row of their own.
    holder = QWidget()
    holder.setObjectName("feedbackHolder")
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(theme.px(8))
    layout.replaceWidget(anchor, holder)
    row.addWidget(anchor)
    row.addWidget(widget, 1)
    holder.setSizePolicy(anchor.sizePolicy())
    return True


_SWALLOWED = {
    QEvent.Type.MouseButtonPress,
    QEvent.Type.MouseButtonRelease,
    QEvent.Type.MouseButtonDblClick,
    QEvent.Type.KeyPress,
    QEvent.Type.KeyRelease,
    QEvent.Type.Shortcut,
}


class ActionBinding(QObject):
    """A button wired to its action with feedback beside it (section 7). Made by ``bind_action``."""

    def __init__(
        self,
        button: QAbstractButton,
        handler: Callable[[], Any],
        *,
        working: str,
        done: str,
        failed: str,
        next_step: str,
        feedback: InlineFeedback | None,
    ) -> None:
        super().__init__(button)
        self.button = button
        self.handler = handler
        self.working_text = working
        self.done_text = done
        self.failed_text = failed
        self.next_step = next_step
        self.busy = False
        self.feedback = feedback or InlineFeedback()
        self._placed = feedback is not None
        button.installEventFilter(self)
        button.clicked.connect(self.run)
        if not self._placed:
            self._place()

    def _place(self, tries: int = 0) -> None:
        if self._placed:
            return
        if place_beside(self.button, self.feedback):
            self._placed = True
        elif tries < 20:
            # Not in a layout yet: placed as soon as the page is put together; never retried forever.
            QTimer.singleShot(0, lambda: self._place(tries + 1))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self.button and self.busy and event.type() in _SWALLOWED:
            return True
        return False

    def run(self, *_args: Any) -> Any:
        if self.busy:
            return None
        self._place()
        self.busy = True
        button = self.button
        original = button.text()
        width = button.width()
        button.setMinimumWidth(max(button.minimumWidth(), width))
        button.setText(self.working_text)
        button.setProperty("busy", True)
        _repolish(button)
        # 224 (Wave B2a, Decision 7): the button alone says what it is doing, so the word shows once; the line
        # beside it is cleared of an earlier result and speaks again when the work ends.
        self.feedback.clear()
        # Painted now, before the work starts, so the click never looks like it did nothing.
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        outcome: Any = None
        error: BaseException | None = None
        try:
            outcome = self.handler()
        except Exception as exc:  # noqa: BLE001 - every failure is said beside the button
            error = exc
        # Clicks made while it worked reach the button now, while it still refuses them.
        QCoreApplication.processEvents()
        if button.text() == self.working_text:
            button.setText(original)
        button.setMinimumWidth(0)
        button.setProperty("busy", False)
        _repolish(button)
        self.busy = False
        if error is not None:
            self.feedback.failed(f"{self.failed_text} {error}".strip(), self.next_step)
        elif isinstance(outcome, Outcome):
            if outcome.kind == "failed":
                self.feedback.failed(outcome.text or self.failed_text, outcome.next_step or self.next_step)
            elif outcome.kind == "quiet":
                self.feedback.clear()
            else:
                self.feedback.done(outcome.text or self.done_text)
        elif outcome is False:
            self.feedback.clear()
        else:
            self.feedback.done(self.done_text)
        return outcome


def bind_action(
    button: QAbstractButton,
    handler: Callable[[], Any],
    *,
    working: str,
    done: str,
    failed: str = "That did not work:",
    next_step: str = DEFAULT_NEXT_STEP,
    feedback: InlineFeedback | None = None,
) -> ActionBinding:
    """Connect ``button`` to ``handler`` with feedback beside it.

    The handler returns nothing or True (done), False or ``Outcome.quiet()`` (say nothing),
    ``Outcome.done(text)`` or ``Outcome.failed(text, next_step)``; an exception is a failure.
    ``feedback`` shares one line between buttons of a row; without it the line goes right after the
    button.
    """

    binding = ActionBinding(button, handler, working=working, done=done, failed=failed,
                            next_step=next_step, feedback=feedback)
    button.setProperty("feedbackBound", True)
    return binding


# Job banner -------------------------------------------------------------------------------------


# The job states that mean it is still going; every other state is a finished job.
RUNNING_STATES = {"active", "waiting", "paused", "cancelling"}


@dataclass(frozen=True)
class JobInfo:
    """A long job as the banner shows it.

    ``state`` is a status word (``theme.status_kind``): running is "active"; a finished job is
    "completed", "attention", "failed" or "cancelled". ``percent`` and ``time_left`` are None and ""
    when not known. ``token`` names the job, so "Open in Queue / Progress" opens that one.
    """

    token: str
    title: str
    origin: str = ""
    state: str = "active"
    percent: int | None = None
    time_left: str = ""
    detail: str = ""

    @property
    def running(self) -> bool:
        return self.state in RUNNING_STATES


def time_left_text(seconds: float | None) -> str:
    """'about 1 min left' style wording, '' when not known."""

    if seconds is None or seconds < 0:
        return ""
    seconds = int(round(seconds))
    if seconds < 60:
        return "less than a minute left"
    minutes = int(round(seconds / 60))
    if minutes < 90:
        return f"about {minutes} min left"
    hours, rest = divmod(minutes, 60)
    return f"about {hours} h {rest} min left" if rest else f"about {hours} h left"


def work_done_text(completed: int, total: int, unit: str = "") -> str:
    """How far a job has got, in what it counts (224, Wave B2a; 272 reuses it): "04:12 of 22:30" for
    seconds of a recording, "12.0 GB of 54.0 GB" for bytes, "3 of 5" for items."""

    completed, total = max(0, int(completed)), max(0, int(total))
    if unit == "seconds":
        return f"{recording_clock(completed)} of {recording_clock(total)}"
    if unit == "bytes":
        return f"{_size_text(completed)} of {_size_text(total)}"
    return f"{completed} of {total}"


def set_work_bar(bar: QProgressBar, completed: int, total: int) -> None:
    """A bar's range and value for work done of total. A bar holds at most about two thousand million, so
    larger counts (the bytes of a large recording) are scaled down together; its text says the real ones."""

    completed, total = max(0, int(completed)), max(1, int(total))
    step = max(1, -(-total // 2_000_000_000))
    bar.setRange(0, total // step)
    bar.setValue(min(total, completed) // step)


def _size_text(size: int) -> str:
    if size >= 1024**3:
        return f"{size / 1024**3:.1f} GB"
    return f"{size / 1024**2:.0f} MB"


FINISHED_TITLES = {"completed": "Done", "attention": "Finished, needs a look", "failed": "Failed",
                   "waiting": "Stopped"}


class JobBanner(QFrame):
    """A job that runs longer than about two seconds, shown on the page where it was started."""

    open_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None, *, link_text: str = OPEN_IN_PROGRESS,
                 done_seconds: float = 6.0) -> None:
        super().__init__(parent)
        self.setObjectName("jobBanner")
        self.setAccessibleName("Job")
        self.info: JobInfo | None = None
        self.done_seconds = done_seconds
        self._origin: str | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.px(16), theme.px(10), theme.px(16), theme.px(10))
        layout.setSpacing(theme.px(12))
        text = QVBoxLayout()
        text.setSpacing(theme.px(6))
        self.title_label = QLabel("")
        self.title_label.setObjectName("jobBannerTitle")
        self.title_label.setWordWrap(True)
        text.addWidget(self.title_label)
        self.bar = QProgressBar()
        self.bar.setObjectName("jobBannerBar")
        self.bar.setProperty("thin", True)
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 100)
        text.addWidget(self.bar)
        layout.addLayout(text, 1)
        self.numbers_label = QLabel("")
        self.numbers_label.setObjectName("jobBannerNumbers")
        self.numbers_label.setWordWrap(True)
        layout.addWidget(self.numbers_label)
        self.open_button = QPushButton(link_text)
        self.open_button.setObjectName("jobBannerOpen")
        set_button_kind(self.open_button, "link")
        self.open_button.clicked.connect(self._open)
        layout.addWidget(self.open_button)
        self.dismiss_button = QPushButton("Dismiss")
        self.dismiss_button.setObjectName("jobBannerDismiss")
        set_button_kind(self.dismiss_button, "link")
        self.dismiss_button.clicked.connect(self.dismiss)
        layout.addWidget(self.dismiss_button)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self.setVisible(False)

    def set_link_visible(self, visible: bool) -> None:
        self.open_button.setVisible(visible)

    def _open(self) -> None:
        if self.info is not None:
            self.open_requested.emit(self.info.token)

    def dismiss(self) -> None:
        self._timer.stop()
        self.setVisible(False)

    def show_job(self, info: JobInfo | None) -> None:
        """Show this job, or hide the banner for None."""

        if info is None:
            self.info = None
            self.dismiss()
            return
        if info == self.info:
            # Progress lines arrive often; nothing new to show.
            return
        same_finished = (self.info is not None and self.info.token == info.token and not self.info.running
                         and not info.running)
        self.info = info
        kind = status_kind(info.state)
        if info.running:
            self._timer.stop()
            self.title_label.setText(info.title)
            state = "active"
            if info.percent is None:
                self.bar.setRange(0, 0)
            else:
                self.bar.setRange(0, 100)
                self.bar.setValue(max(0, min(100, int(info.percent))))
            numbers = [f"{int(info.percent)}%"] if info.percent is not None else []
            if info.time_left:
                numbers.append(info.time_left)
            if not numbers and info.detail:
                numbers.append(info.detail)
            self.numbers_label.setText(" · ".join(numbers) or "Working…")
            self.dismiss_button.setVisible(False)
        else:
            state = "waiting" if info.state == "cancelled" else kind
            heading = FINISHED_TITLES.get(state, "Finished")
            self.title_label.setText(f"{heading}: {info.title}")
            self.bar.setRange(0, 100)
            self.bar.setValue(100 if state == "completed" else 0)
            self.numbers_label.setText(info.detail)
            self.dismiss_button.setVisible(True)
            if not same_finished:
                self._timer.stop()
                if state == "completed" and self.done_seconds > 0:
                    self._timer.start(int(self.done_seconds * 1000))
        self.numbers_label.setVisible(bool(self.numbers_label.text()))
        _restyle(self, "state", "" if state == "active" else state)
        _restyle(self.bar, "operatorState", "active" if state == "active" else state)
        self.setAccessibleName(f"Job: {self.title_label.text()}")
        if not same_finished:
            self.setVisible(True)

    def follow(self, changed: Any, snapshot: Callable[[], JobInfo | None], origin: str,
               open_job: Callable[[str], None] | None = None) -> None:
        """Show the jobs started from ``origin`` as ``snapshot`` reports them each time ``changed`` fires."""

        self._origin = origin
        self._snapshot = snapshot
        changed.connect(self.sync)
        if open_job is not None:
            self.open_requested.connect(open_job)
        self.sync()

    def sync(self) -> None:
        info = self._snapshot() if self._origin is not None else None
        if info is None or info.origin != self._origin:
            if self.info is not None:
                self.info = None
                self.dismiss()
            return
        self.show_job(info)


# Step bar ---------------------------------------------------------------------------------------


class StepBar(QFrame):
    """Numbered steps: done steps are ticks, the current one is filled, later ones are outlines.

    236: the steps wrap onto another line when they do not fit (a large text size, a small window),
    instead of making the page wider than the window."""

    DONE, CURRENT, LATER = "done", "current", "later"

    def __init__(self, steps: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("stepBar")
        self.setAccessibleName("Steps")
        self.steps = list(steps)
        self.marks: list[QLabel] = []
        self.texts: list[QLabel] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.px(16), theme.px(10), theme.px(16), theme.px(10))
        row = FlowLayout(spacing=16)
        for number, name in enumerate(self.steps, start=1):
            holder = QWidget()
            holder.setObjectName("stepBarStep")
            item = QHBoxLayout(holder)
            item.setContentsMargins(0, 0, 0, 0)
            item.setSpacing(theme.px(8))
            mark = QLabel(str(number))
            mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
            theme.keep_scaled(mark, "setFixedSize", (24, 24))
            text = QLabel(name)
            item.addWidget(mark)
            item.addWidget(text)
            row.addWidget(holder)
            self.marks.append(mark)
            self.texts.append(text)
        layout.addLayout(row, 1)
        self.set_current(0)

    def states(self) -> list[str]:
        return [str(mark.property("step") or "") for mark in self.marks]

    def set_states(self, states: list[str]) -> None:
        for number, (mark, text, state) in enumerate(zip(self.marks, self.texts, states, strict=True), start=1):
            mark.setText("✓" if state == self.DONE else str(number))
            mark.setProperty("step", state)
            text.setProperty("stepText", state)
            mark.setAccessibleName(f"Step {number}, {self.steps[number - 1]}: {state}")
            _repolish(mark)
            _repolish(text)

    def set_current(self, index: int) -> None:
        """Steps before ``index`` are done, ``index`` is current; ``len(steps)`` marks all done."""

        self.set_states([self.DONE if i < index else self.CURRENT if i == index else self.LATER
                         for i in range(len(self.steps))])


# Segmented control ------------------------------------------------------------------------------


class SegmentedControl(QFrame):
    """Two to four exclusive choices in one rounded box (section 6)."""

    changed = Signal(object)

    def __init__(self, options: list[tuple[Any, str]], parent: QWidget | None = None, *, name: str = "") -> None:
        super().__init__(parent)
        self.setObjectName("segmented")
        if name:
            self.setAccessibleName(name)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(3)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[Any, QPushButton] = {}
        for value, text in options:
            button = BoldSafeButton(text)
            button.setCheckable(True)
            button.setAccessibleName(f"{name} {text}".strip())
            button.clicked.connect(lambda _checked=False, v=value: self._chosen(v))
            self.group.addButton(button)
            layout.addWidget(button)
            self.buttons[value] = button
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def value(self) -> Any:
        for value, button in self.buttons.items():
            if button.isChecked():
                return value
        return None

    def set_value(self, value: Any) -> None:
        button = self.buttons.get(value)
        if button is not None:
            button.setChecked(True)

    def _chosen(self, value: Any) -> None:
        self.changed.emit(value)


# Button rows that wrap --------------------------------------------------------------------------


class FlowLayout(QLayout):
    """A row of buttons that wraps onto the next line when the page is narrow or the text is large,
    instead of pushing the page wider than the window (section 3: nothing cut off at 150%)."""

    def __init__(self, parent: QWidget | None = None, *, spacing: int = 8) -> None:
        super().__init__(parent)
        self._items: list[Any] = []
        self._spacing = spacing
        # The width it was last laid out at: its minimum height is the height of its lines at that width,
        # so a parent short of room can never squeeze wrapped lines on top of what comes next.
        self._width = 0
        self._height = 0
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: Any) -> None:  # noqa: N802
        self._items.append(item)

    def insertWidget(self, index: int, widget: QWidget) -> None:  # noqa: N802
        self.addChildWidget(widget)
        self._items.insert(max(0, min(index, len(self._items))), QWidgetItem(widget))
        self.invalidate()

    def indexOf(self, widget: Any) -> int:  # noqa: N802
        for index, item in enumerate(self._items):
            if item.widget() is widget:
                return index
        return -1

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> Any:  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> Any:  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def spacing(self) -> int:
        return theme.px(self._spacing)

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        height = self._arrange(rect, apply=True)
        self._width = rect.width()
        if height != self._height:
            self._height = height
            # The lines changed. Qt ignores a new size asked for while it is laying out, so the window is
            # laid out again straight after, with this row's new height.
            QTimer.singleShot(0, self._height_changed)

    def _height_changed(self) -> None:
        try:
            self.invalidate()
            # Up through every holder (splitters and scroll areas too, which are not layouts), each told
            # now that what it holds needs another size, so one pass settles the whole window.
            widget = self.parentWidget()
            while widget is not None:
                if widget.layout() is not None:
                    widget.layout().invalidate()
                    widget.layout().activate()
                widget.updateGeometry()
                QCoreApplication.sendEvent(widget, QEvent(QEvent.Type.LayoutRequest))
                if widget.isWindow():
                    break
                widget = widget.parentWidget()
        except RuntimeError:  # deleted with its page
            pass

    def sizeHint(self) -> QSize:  # noqa: N802
        width = sum(item.sizeHint().width() for item in self._visible()) + self.spacing() * max(0, len(self._visible()) - 1)
        height = max((item.sizeHint().height() for item in self._visible()), default=0)
        return QSize(width, height)

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._visible():
            size = size.expandedTo(item.minimumSize())
        if self._width > 0:
            size.setHeight(max(size.height(), self.heightForWidth(self._width)))
        return size

    def _visible(self) -> list[Any]:
        return [item for item in self._items if not (item.widget() is not None and item.widget().isHidden())]

    def _arrange(self, rect: QRect, *, apply: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        gap = self.spacing()
        for item in self._visible():
            hint = item.sizeHint()
            if x > rect.x() and x + hint.width() > rect.right() + 1:
                x, y, line = rect.x(), y + line + gap, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + gap
            line = max(line, hint.height())
        return y + line - rect.y()


class WrappingTabStrip(QWidget):
    """The tabs of a QTabWidget as a row that wraps onto a second line when they do not fit, so no tab
    is ever hidden behind scroll arrows at a large text size. The tab widget keeps its pages, names
    and current index; only its own bar is hidden."""

    def __init__(self, tabs: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tabStrip")
        self.tabs = tabs
        self.row = FlowLayout(self, spacing=2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: list[QPushButton] = []
        tabs.tabBar().hide()
        self.rebuild()
        tabs.currentChanged.connect(self._show_current)

    def rebuild(self) -> None:
        for button in self.buttons:
            self.group.removeButton(button)
            self.row.removeWidget(button)
            button.deleteLater()
        self.buttons = []
        for index in range(self.tabs.count()):
            button = BoldSafeButton(self.tabs.tabText(index))
            button.setObjectName("tabStripButton")
            button.setCheckable(True)
            button.setAccessibleName(f"{self.tabs.tabText(index)} tab")
            button.clicked.connect(lambda _checked=False, i=index: self.tabs.setCurrentIndex(i))
            self.group.addButton(button)
            self.row.addWidget(button)
            self.buttons.append(button)
        self._show_current(self.tabs.currentIndex())

    def _show_current(self, index: int) -> None:
        if 0 <= index < len(self.buttons):
            self.buttons[index].setChecked(True)


# Page area --------------------------------------------------------------------------------------


class PageStack(QStackedWidget):
    """The page area. Each page sits in its own scroll area, so at a large text size a page scrolls
    instead of squeezing its controls or cutting them off. ``currentWidget`` is still the page."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scroll_of: dict[int, QScrollArea] = {}

    def addWidget(self, page: QWidget) -> int:  # noqa: N802
        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().setObjectName("pageScrollViewport")
        scroll.setWidget(page)
        self._scroll_of[id(page)] = scroll
        return super().addWidget(scroll)

    def scroll_for(self, page: QWidget) -> QScrollArea | None:
        return self._scroll_of.get(id(page))

    def setCurrentWidget(self, page: QWidget) -> None:  # noqa: N802
        super().setCurrentWidget(self._scroll_of.get(id(page), page))

    def currentWidget(self) -> QWidget | None:  # noqa: N802
        current = super().currentWidget()
        if isinstance(current, QScrollArea) and self._scroll_of.get(id(current.widget())) is current:
            return current.widget()
        return current


# Tables and lists -------------------------------------------------------------------------------


class SelectionBarDelegate(QStyledItemDelegate):
    """Draws the 3 px accent bar on the left of a selected row (section 8)."""

    def paint(self, painter: Any, option: QStyleOptionViewItem, index: Any) -> None:
        super().paint(painter, option, index)
        if not option.state & QStyle.StateFlag.State_Selected:
            return
        view = self.parent()
        header = view.horizontalHeader() if isinstance(view, QTableView) else (
            view.header() if isinstance(view, QTreeView) else None)
        first = header.logicalIndex(0) if header is not None else 0
        if index.column() == first:
            rect = QRect(option.rect.left(), option.rect.top(), 3, option.rect.height())
            painter.fillRect(rect, QColor(theme.token("accent")))


def polish_forms(root: QWidget) -> None:
    """A clear gap between every form's labels and their fields (16 px at 100%, growing with the text),
    so a long label never reads as one phrase with what follows it (237)."""

    for form in root.findChildren(QFormLayout):
        if form.property("formsPolished"):
            continue
        form.setProperty("formsPolished", True)
        theme.keep_scaled(form, "setHorizontalSpacing", 16)


def polish_views(root: QWidget) -> None:
    """Give every plain table and tree under ``root`` the selection bar, row rules and 32 px rows."""

    for view in root.findChildren(QTableView) + root.findChildren(QTreeView):
        if view.property("viewsPolished"):
            continue
        view.setProperty("viewsPolished", True)
        if type(view.itemDelegate()) is QStyledItemDelegate:
            view.setItemDelegate(SelectionBarDelegate(view))
        if isinstance(view, QTableView):
            view.setShowGrid(False)
            header = view.verticalHeader()
            if header.defaultSectionSize() <= theme.px(32):
                theme.keep_scaled(header, "setDefaultSectionSize", 32)
