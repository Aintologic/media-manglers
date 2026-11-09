"""Workbench themes, built from the tokens of the UI rulebook (`governance/UI_RULES.md`, 237).

Every colour, font size, spacing step and corner radius the stylesheet uses comes from the token
tables below, so one change here reaches every screen. The text size setting (100%, 110%, 125%,
150%) scales every font, and the few sizes pages fix in pixels follow it through ``keep_scaled``.
"""

from __future__ import annotations

from pathlib import Path
from string import Template
from typing import Any

from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QWidget


# One colour per kind of status, used on every screen (105):
# green = done, orange = needs a look, red = failed, grey = waiting; running uses the accent (237).
# These are the dark theme's; the light theme keeps the meanings with darker text (LIGHT_STATUS_COLORS).
STATUS_COLORS = {
    "active": "#2BB5C9",
    "completed": "#6EE7A0",
    "attention": "#F5B94A",
    "failed": "#F08A7E",
    "waiting": "#A3ACBA",
}

LIGHT_STATUS_COLORS = {
    "active": "#127C8C",
    "completed": "#1D7A45",
    "attention": "#8A5A00",
    "failed": "#B3261E",
    "waiting": "#5A6472",
}

_STATE_KIND = {
    "active": "active",
    "transcribing": "active",
    "listening": "active",
    "transcribed": "active",
    "completed": "completed",
    "complete": "completed",
    "succeeded": "completed",
    "done": "completed",
    "complete_with_warnings": "attention",
    "completed_with_problems": "attention",
    "completed with problems": "attention",
    # 196: a recording with no narration is a correct result, not a problem.
    "no_narration": "completed",
    "no narration found": "completed",
    "skipped": "attention",
    "cancelled": "attention",
    # 243: a run cut off by a crash or a close, like one cancelled.
    "interrupted": "attention",
    "cancelling": "attention",
    "waiting": "waiting",
    "failed": "failed",
    "could not be used": "failed",
    "pending": "waiting",
    # 114/115: the operator's own choices are not problems.
    "skipped by you": "waiting",
    "skipping…": "waiting",
    "paused": "attention",
}


def status_kind(state: str) -> str:
    """Map any status word the app shows to active/completed/attention/failed/waiting."""

    return _STATE_KIND.get(str(state or "").strip().lower(), "waiting")


def status_color(state: str) -> QColor:
    colors = LIGHT_STATUS_COLORS if _STATE["theme"] == "light" else STATUS_COLORS
    return QColor(colors[status_kind(state)])


# The rulebook's tokens (section 2). A few come from the approved mockups rather than the table:
# the disabled button, the checkbox and step outlines, the segmented control's chosen part, the
# danger button and the link's hover colour.
DARK_TOKENS = {
    "ground": "#0E1014",
    "nav": "#12151B",
    "card": "#161A21",
    "card_border": "#232833",
    "inner": "#12151B",
    "input": "#0E1014",
    "input_border": "#2B313C",
    "text": "#E8EAED",
    "text_strong": "#FFFFFF",
    "text_soft": "#C9CED6",
    "muted": "#A3ACBA",
    "label": "#8C95A5",
    "footer": "#6B7484",
    "accent": "#2BB5C9",
    "on_accent": "#0B1418",
    "link": "#5FD3E3",
    "link_hover": "#9BE6F0",
    "selection": "#1D2A33",
    "running": "#11262C",
    "running_border": "#1F5561",
    "running_text": "#BFE9F0",
    "bar_track": "#1F3A42",
    "done": "#6EE7A0",
    "done_bg": "#1E3B2E",
    "attention": "#F5B94A",
    "attention_bg": "#2A2113",
    "attention_border": "#5C4518",
    "failed": "#F08A7E",
    "failed_bg": "#3A1E1C",
    "failed_strong": "#B4413C",
    "waiting": "#A3ACBA",
    "waiting_bg": "#232833",
    "divider": "#1C2029",
    "segment_on": "#26303C",
    "outline": "#3A4250",
    "check_border": "#4A5261",
    "disabled": "#1A1E25",
    "danger_border": "#6B2E2A",
    "danger_text": "#F2A79E",
    "tooltip": "#E8EAED",
    "tooltip_text": "#0E1014",
    "video": "#05070A",
}

LIGHT_TOKENS = {
    "ground": "#F5F7FA",
    "nav": "#EDF0F4",
    "card": "#FFFFFF",
    "card_border": "#D9DEE5",
    "inner": "#F5F7FA",
    "input": "#FFFFFF",
    "input_border": "#C5CCD6",
    "text": "#14181F",
    "text_strong": "#0B0E13",
    "text_soft": "#2E3640",
    "muted": "#5A6472",
    "label": "#5F6A79",
    "footer": "#6B7484",
    "accent": "#127C8C",
    "on_accent": "#FFFFFF",
    "link": "#0E6E7C",
    "link_hover": "#0A5560",
    "selection": "#E3F3F5",
    "running": "#E3F3F5",
    "running_border": "#9CD3DB",
    "running_text": "#0E4F59",
    "bar_track": "#CDE8EC",
    "done": "#1D7A45",
    "done_bg": "#DDF3E6",
    "attention": "#8A5A00",
    "attention_bg": "#FFF1D6",
    "attention_border": "#E8C27A",
    "failed": "#B3261E",
    "failed_bg": "#FBE3E0",
    "failed_strong": "#B4413C",
    "waiting": "#5A6472",
    "waiting_bg": "#E6EAF0",
    "divider": "#E6EAF0",
    "segment_on": "#DCE3EB",
    "outline": "#B8C0CC",
    "check_border": "#9AA4B2",
    "disabled": "#EEF1F5",
    "danger_border": "#E3A29A",
    "danger_text": "#B3261E",
    "tooltip": "#14181F",
    "tooltip_text": "#FFFFFF",
    "video": "#05070A",
}

# Section 3: point sizes at 100% text size. Each is used at the nearest size that is a whole number of
# screen pixels (whole_pixel_pt), at every text size: a font between two pixel sizes is drawn soft.
FONT_SIZES = {"body": 11.0, "small": 9.5, "section": 12.5, "title": 18.0}
FONT_FAMILY = "Segoe UI"

# Section 3: the text size setting, in percent. 100 is the default; Ctrl+0 goes back to it.
TEXT_SIZES = (100, 110, 125, 150)
DEFAULT_TEXT_SIZE = 100

_ASSETS = Path(__file__).resolve().parent / "assets"

# What apply_theme last applied, so a text size change keeps the theme and the reverse.
_STATE: dict[str, Any] = {"theme": "dark", "scale": 1.0, "dpi": 96.0, "dpr": 1.0}
# Sizes a page fixes in pixels, kept in step with the text size: (widget, setter name, size at 100%).
_SCALED: list[tuple[QWidget, str, Any]] = []


def normalize_text_size(value: Any) -> int:
    """The nearest allowed text size; anything unreadable is 100%."""

    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return DEFAULT_TEXT_SIZE
    return min(TEXT_SIZES, key=lambda size: (abs(size - number), size))


def step_text_size(current: Any, step: int) -> int:
    """One text size larger (step 1) or smaller (step -1), stopping at the ends."""

    index = TEXT_SIZES.index(normalize_text_size(current))
    return TEXT_SIZES[max(0, min(len(TEXT_SIZES) - 1, index + step))]


def text_scale() -> float:
    return float(_STATE["scale"])


def current_theme() -> str:
    return str(_STATE["theme"])


def tokens() -> dict[str, str]:
    """The colour tokens of the theme in use."""

    return LIGHT_TOKENS if _STATE["theme"] == "light" else DARK_TOKENS


def token(name: str) -> str:
    return tokens()[name]


def px(size: float) -> int:
    """A pixel size at 100% text size, at the text size in use."""

    return int(round(size * text_scale()))


def screen_metrics() -> tuple[float, float]:
    """The main screen's logical dots per inch and device pixel ratio (96 and 1 with no screen)."""

    app = QGuiApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    if screen is None:
        return 96.0, 1.0
    return float(screen.logicalDotsPerInch() or 96.0), float(screen.devicePixelRatio() or 1.0)


def whole_pixel_pt(base_pt: float, scale: float | None = None, dpi: float | None = None,
                   dpr: float | None = None) -> float:
    """The point size nearest ``base_pt`` at the text size in use that is a whole number of screen pixels.

    Windows draws a font between two pixel sizes soft (237: 11 pt at 125% is 18.33 px at 96 dpi), so
    every size is rounded to whole pixels on the screen, then turned back into points for the stylesheet.
    """

    scale = text_scale() if scale is None else scale
    dpi = float(_STATE["dpi"]) if dpi is None else dpi
    dpr = float(_STATE["dpr"]) if dpr is None else dpr
    pixels = max(1, int(round(base_pt * scale * dpi / 72.0 * dpr)))
    return round(pixels * 72.0 / (dpi * dpr), 4)


def point_size(kind: str = "body") -> float:
    return whole_pixel_pt(FONT_SIZES[kind])


def _line_height(point: float) -> int:
    from PySide6.QtGui import QFont, QFontMetrics  # noqa: PLC0415

    if QGuiApplication.instance() is None:
        return int(round(point * float(_STATE["dpi"]) / 72.0 * 1.33))
    font = QFont(FONT_FAMILY)
    font.setPointSizeF(point)
    return QFontMetrics(font).height()


def nav_row_heights(scale: float | None = None) -> tuple[int, int]:
    """The rail's button and group-label heights: their words plus a little room that shrinks as the
    text grows, so the whole rail fits an 800 px tall window at 150%."""

    scale = text_scale() if scale is None else scale
    room = max(4, int(round(14 - 20 * (scale - 1))))
    body = _line_height(whole_pixel_pt(FONT_SIZES["body"], scale))
    small = _line_height(whole_pixel_pt(FONT_SIZES["small"], scale))
    return body + room, small + max(3, room // 2)


def keep_scaled(widget: QWidget, setter: str, size: Any) -> None:
    """Set a pixel size now and again whenever the text size changes.

    ``size`` is the size at 100%: a number, or a tuple for setters that take several (setFixedSize).
    """

    _SCALED.append((widget, setter, size))
    _apply_scaled_one(widget, setter, size)


def _apply_scaled_one(widget: QWidget, setter: str, size: Any) -> bool:
    try:
        from shiboken6 import isValid
    except ImportError:  # pragma: no cover - shiboken ships with PySide6
        isValid = None  # noqa: N806
    if isValid is not None and not isValid(widget):
        return False
    values = size if isinstance(size, tuple) else (size,)
    getattr(widget, setter)(*(px(value) for value in values))
    return True


def _apply_scaled() -> None:
    _SCALED[:] = [entry for entry in _SCALED if _apply_scaled_one(*entry)]


def asset_url(name: str) -> str:
    """A stylesheet url() for one of the theme's own images, in quotes so a space in the path is fine."""

    return '"' + (_ASSETS / name).as_posix() + '"'


_STYLESHEET = Template("""
QWidget { font-family: "$family"; font-size: ${body}pt; color: $text; }
QMainWindow, QDialog { background: $ground; color: $text; }
QWidget#appShell, QStackedWidget, QScrollArea#pageScroll, QWidget#pageScrollViewport { background: $ground; }
QScrollArea { background: transparent; border: 0; }
QLabel, QCheckBox, QRadioButton { background: transparent; }
QMessageBox { color: $text; }
QMessageBox QLabel { color: $text; }

QFrame#navRail { background: $nav; border: 0; border-right: 1px solid $card_border; }
QFrame#navRail QLabel { color: $text_soft; }
QScrollArea#navGroupsScroll, QScrollArea#navGroupsScroll QWidget#qt_scrollarea_viewport, QWidget#navGroups { background: $nav; }
QLabel#navBrand { color: $text; font-size: ${section}pt; font-weight: 700; }
QLabel[navGroup="true"] { color: $label; font-size: ${small}pt; font-weight: 600; padding: ${navpad}px ${p10}px 1px ${p10}px; min-height: ${navlabel}px; max-height: ${navlabel}px; }
QPushButton#navButton { text-align: left; padding: 0px ${p10}px; min-height: ${navrow}px; max-height: ${navrow}px; border: 0; border-radius: ${p8}px; background: transparent; color: $text_soft; }
QPushButton#navButton:hover { background: $card_border; color: $text_strong; }
QPushButton#navButton:checked { background: $selection; color: $text_strong; font-weight: 600; border-left: 3px solid $accent; border-top-left-radius: 0; border-bottom-left-radius: 0; }
QPushButton#navButton:focus { border: 2px solid $accent; }
QLabel#navBadge { background: $accent; color: $on_accent; font-size: ${small}pt; font-weight: 700; border-radius: ${p9}px; padding: 0 ${p6}px; min-width: ${p8}px; }
QLabel#navFooter { color: $label; font-size: ${small}pt; }
QLabel#versionBuildLabel { color: $footer; font-size: ${small}pt; }

QFrame[card="true"], QGroupBox { background: $card; border: 1px solid $card_border; border-radius: 12px; }
QFrame[card="true"][selectedWorkflow="true"] { background: $running; border: 1px solid $running_border; }
QGroupBox { margin-top: ${p14}px; padding: ${p16}px ${p12}px ${p12}px ${p12}px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: ${p12}px; padding: 0 ${p6}px; color: $text; }
QGroupBox::indicator { width: ${p16}px; height: ${p16}px; border: 1px solid $check_border; border-radius: 4px; background: $input; }
QGroupBox::indicator:checked { background: $accent; border-color: $accent; image: url($check); }

QLabel[muted="true"] { color: $muted; }
QLabel[small="true"] { color: $label; font-size: ${small}pt; }
QLabel[title="true"] { font-size: ${title}pt; font-weight: 700; color: $text_strong; }
QLabel[sectionTitle="true"] { font-size: ${section}pt; font-weight: 600; color: $text_strong; }
QLabel[accent="true"] { color: $link; font-weight: 600; }
QLabel[selectionBadge="true"] { color: $on_accent; background: $accent; border-radius: 6px; padding: ${p2}px ${p8}px; font-weight: 700; }
QLabel[statusKind="active"] { color: $accent; font-weight: 600; }
QLabel[statusKind="completed"] { color: $done; font-weight: 600; }
QLabel[statusKind="attention"] { color: $attention; font-weight: 600; }
QLabel[statusKind="failed"] { color: $failed; font-weight: 600; }

QLabel#progressStateBanner { padding: ${p10}px ${p14}px; border: 1px solid $card_border; border-radius: 12px; background: $card; font-weight: 600; }
QLabel#progressStateBanner[operatorState="active"] { border-color: $running_border; background: $running; }
QLabel#progressStateBanner[operatorState="waiting"], QLabel#progressStateBanner[operatorState="cancelling"], QLabel#progressStateBanner[operatorState="paused"] { border-color: $attention_border; background: $attention_bg; }
QLabel#progressStateBanner[operatorState="completed"] { border-color: $done; background: $done_bg; }
QLabel#progressStateBanner[operatorState="complete_with_warnings"], QLabel#progressStateBanner[operatorState="completed_with_problems"], QLabel#progressStateBanner[operatorState="cancelled"] { border-color: $attention_border; background: $attention_bg; }
QLabel#progressStateBanner[operatorState="failed"] { border-color: $failed_strong; background: $failed_bg; }
QLabel#sourceDiscoveryStatus, QLabel#audioPreviewIdentity, QLabel[operatorState="attention"], QLabel[operatorState="ready"], QLabel[operatorState="error"] { padding: ${p8}px ${p10}px; border: 1px solid $card_border; border-radius: 8px; background: $inner; }
QLabel[operatorState="active"] { border-color: $running_border; background: $running; color: $running_text; }
QLabel[operatorState="attention"] { border-color: $attention_border; background: $attention_bg; color: $attention; }
QLabel[operatorState="ready"] { border-color: $done; background: $done_bg; color: $done; }
QLabel[operatorState="error"] { border-color: $failed_strong; background: $failed_bg; color: $failed; }
QFrame#reviewBlockerPanel { padding: ${p10}px; border: 1px solid $attention_border; border-radius: 12px; background: $attention_bg; }
QFrame#reviewBlockerPanel[operatorState="error"] { border-color: $failed_strong; background: $failed_bg; }
QFrame#missingToolsNotice { border: 0; border-bottom: 1px solid $attention_border; background: $attention_bg; }

QPushButton { min-height: ${p24}px; padding: ${p6}px ${p14}px; border: 1px solid $input_border; border-radius: 10px; background: transparent; color: $text; }
QPushButton:hover { background: $card_border; border-color: $outline; }
QPushButton:pressed { background: $ground; }
QPushButton:focus { border: 2px solid $accent; padding: ${p5}px ${p13}px; }
QPushButton:disabled { color: $footer; background: $disabled; border-color: $card_border; }
QPushButton[busy="true"] { color: $muted; border-style: dashed; }
QPushButton[primary="true"], QPushButton[operatorAction="ready"] { min-height: ${p28}px; background: $accent; border: 1px solid $accent; color: $on_accent; font-weight: 700; }
QPushButton[primary="true"]:hover, QPushButton[operatorAction="ready"]:hover { background: $link; border-color: $link; }
QPushButton[primary="true"]:pressed, QPushButton[operatorAction="ready"]:pressed { background: $accent; border-color: $link_hover; }
QPushButton[primary="true"]:focus, QPushButton[operatorAction="ready"]:focus { border: 2px solid $link_hover; }
QPushButton[primary="true"][busy="true"] { color: $on_accent; border-style: dashed; }
QPushButton[primary="true"]:disabled, QPushButton[operatorAction="blocked"] { color: $footer; background: $disabled; border: 1px solid $card_border; font-weight: 600; }
QPushButton[operatorAction="attention"] { background: $attention_bg; border-color: $attention_border; color: $attention; font-weight: 700; }
QPushButton[operatorAction="attention"]:hover { border-color: $attention; }
QPushButton[kind="danger"] { background: transparent; border-color: $danger_border; color: $danger_text; }
QPushButton[kind="danger"]:hover { border-color: $failed; color: $failed; background: $failed_bg; }
QPushButton[kind="danger"]:disabled { color: $footer; border-color: $card_border; background: transparent; }
QPushButton[kind="link"] { background: transparent; border-color: transparent; color: $link; padding-left: ${p6}px; padding-right: ${p6}px; }
QPushButton[kind="link"]:hover { color: $link_hover; background: transparent; border-color: transparent; }
QPushButton[kind="link"]:focus { border: 2px solid $accent; }
QPushButton[kind="link"]:disabled { color: $footer; background: transparent; border-color: transparent; }
QWidget#reviewPlayer QPushButton { min-height: ${p20}px; padding: ${p4}px ${p6}px; }
QWidget#reviewPlayer QPushButton:focus { padding: ${p3}px ${p5}px; }
QWidget#reviewPlayer QPushButton[primary="true"] { min-height: ${p20}px; }
QWidget#reviewPlayer QComboBox { padding: ${p4}px ${p22}px ${p4}px ${p8}px; }
QWidget#reviewPlayer QComboBox::drop-down { width: ${p20}px; }
QWidget#reviewPlayer QComboBox:focus, QWidget#reviewPlayer QComboBox:on { padding: ${p3}px ${p21}px ${p3}px ${p7}px; }
QToolButton { border: 1px solid transparent; border-radius: 8px; padding: ${p4}px; background: transparent; color: $text; }
QToolButton:hover { background: $card_border; }
QToolButton:focus { border: 2px solid $accent; }

QLineEdit, QTextEdit, QPlainTextEdit, QTextBrowser, QListWidget, QListView, QTreeWidget, QTreeView, QTableWidget, QTableView, QComboBox, QSpinBox, QDoubleSpinBox {
    background: $input; color: $text; border: 1px solid $input_border; border-radius: 8px; padding: ${p6}px;
    selection-background-color: $selection; selection-color: $text_strong;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QTextBrowser:focus, QSpinBox:focus, QDoubleSpinBox:focus, QListWidget:focus, QListView:focus, QTreeView:focus, QTableView:focus { border: 2px solid $accent; padding: ${p5}px; }
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled { color: $footer; background: $disabled; border-color: $card_border; }
QLineEdit[readOnly="true"] { color: $text_soft; background: $inner; }
QAbstractSpinBox QLineEdit, QComboBox QLineEdit { padding: 0px; border: 0px; background: transparent; }

QComboBox { padding: ${p6}px ${p30}px ${p6}px ${p10}px; }
QComboBox:hover { border-color: $outline; }
QComboBox:focus, QComboBox:on { border: 2px solid $accent; padding: ${p5}px ${p29}px ${p5}px ${p9}px; }
QComboBox:disabled { color: $footer; background: $disabled; border-color: $card_border; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right; width: ${p26}px; border: 0; background: transparent; }
QComboBox::down-arrow { image: url($chevron_down); width: ${p14}px; height: ${p14}px; }
QComboBox::down-arrow:disabled { image: url($chevron_down); }
QComboBox QAbstractItemView { background: $card; color: $text; border: 1px solid $input_border; border-radius: 8px; padding: ${p4}px; outline: 0; selection-background-color: $selection; selection-color: $text_strong; }
QSpinBox, QDoubleSpinBox { padding-right: ${p26}px; }
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: ${p22}px; border: 0; background: transparent; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: ${p22}px; border: 0; background: transparent; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url($chevron_up); width: ${p12}px; height: ${p12}px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url($chevron_down); width: ${p12}px; height: ${p12}px; }
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover { background: $card_border; }

QCheckBox, QRadioButton { spacing: ${p8}px; color: $text_soft; }
QCheckBox::indicator, QRadioButton::indicator { width: ${p16}px; height: ${p16}px; border: 1px solid $check_border; background: $input; }
QCheckBox::indicator { border-radius: 4px; }
QRadioButton::indicator { border-radius: ${p8}px; }
QCheckBox::indicator:hover, QRadioButton::indicator:hover { border-color: $accent; }
QCheckBox::indicator:focus, QRadioButton::indicator:focus { border: 2px solid $accent; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; image: url($check); }
QRadioButton::indicator:checked { border-color: $accent; background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 $accent, stop:0.45 $accent, stop:0.55 $input, stop:1 $input); }
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled { background: $disabled; border-color: $card_border; }
QCheckBox:disabled, QRadioButton:disabled { color: $footer; }

QListWidget::item, QListView::item { padding: ${p6}px ${p8}px; border: 0; border-left: 3px solid transparent; }
QListWidget::item:hover, QListView::item:hover { background: $inner; }
QListWidget::item:selected, QListView::item:selected { background: $selection; color: $text_strong; border-left: 3px solid $accent; }
QTreeView::item, QTableView::item { padding: ${p4}px ${p6}px; border: 0; border-bottom: 1px solid $divider; }
QTreeView::item:selected, QTableView::item:selected { background: $selection; color: $text_strong; }
QTableView, QTreeView { gridline-color: $divider; alternate-background-color: $inner; }
QHeaderView { background: transparent; border: 0; }
QHeaderView::section { background: $card; color: $label; font-size: ${small}pt; font-weight: 600; border: 0; border-bottom: 1px solid $card_border; padding: ${p6}px ${p8}px; }
QTableCornerButton::section { background: $card; border: 0; }

QTabWidget::pane { border: 0; border-top: 1px solid $card_border; background: transparent; top: -1px; }
QTabBar::tab { background: transparent; color: $muted; padding: ${p10}px ${p12}px; border: 0; border-bottom: 3px solid transparent; }
QTabBar::tab:hover { color: $text; }
QTabBar::tab:selected { color: $text_strong; font-weight: 600; border-bottom: 3px solid $accent; }
QTabBar::tab:focus { color: $text_strong; }
QPushButton#tabStripButton { background: transparent; border: 0; border-bottom: 3px solid transparent; border-radius: 0; color: $muted; padding: ${p8}px ${p12}px; }
QPushButton#tabStripButton:hover { color: $text; background: transparent; }
QPushButton#tabStripButton:checked { color: $text_strong; font-weight: 600; border-bottom: 3px solid $accent; }
QPushButton#tabStripButton:focus { color: $text_strong; border: 2px solid $accent; border-bottom: 3px solid $accent; padding: ${p6}px ${p10}px; }

QScrollBar:vertical { width: ${p12}px; background: transparent; margin: 0; }
QScrollBar::handle:vertical { background: $outline; min-height: ${p28}px; border-radius: ${p5}px; margin: 2px; }
QScrollBar:horizontal { height: ${p12}px; background: transparent; margin: 0; }
QScrollBar::handle:horizontal { background: $outline; min-width: ${p28}px; border-radius: ${p5}px; margin: 2px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QSplitter::handle { background: $card_border; }
QSplitter::handle:horizontal { width: 1px; }
QSplitter::handle:vertical { height: 1px; }

QProgressBar { border: 0; border-radius: ${p4}px; background: $bar_track; color: $text; text-align: center; min-height: ${p16}px; }
QProgressBar::chunk { background: $accent; border-radius: ${p4}px; }
QProgressBar[operatorState="active"]::chunk { background: $accent; }
QProgressBar[operatorState="completed"]::chunk { background: $done; }
QProgressBar[operatorState="attention"]::chunk { background: $attention; }
QProgressBar[operatorState="failed"]::chunk { background: $failed; }
QProgressBar[thin="true"] { min-height: ${p6}px; max-height: ${p6}px; border-radius: 3px; }
QProgressBar[thin="true"]::chunk { border-radius: 3px; }

QLabel[pill="active"], QLabel[pill="completed"], QLabel[pill="attention"], QLabel[pill="failed"], QLabel[pill="waiting"] { font-size: ${small}pt; font-weight: 600; border-radius: ${p10}px; padding: ${p1}px ${p10}px; }
QLabel[pill="active"] { color: $accent; background: $running; border: 1px solid $running_border; }
QLabel[pill="completed"] { color: $done; background: $done_bg; border: 1px solid $done_bg; }
QLabel[pill="attention"] { color: $attention; background: $attention_bg; border: 1px solid $attention_border; }
QLabel[pill="failed"] { color: $failed; background: $failed_bg; border: 1px solid $failed_strong; }
QLabel[pill="waiting"] { color: $waiting; background: $waiting_bg; border: 1px solid $waiting_bg; }

QLabel[feedback="working"] { color: $link; }
QLabel[feedback="done"] { color: $done; font-weight: 600; }
QLabel[feedback="failed"] { color: $failed; font-weight: 600; }

QFrame#jobBanner { background: $running; border: 1px solid $running_border; border-radius: 12px; }
QFrame#jobBanner[state="completed"] { background: $done_bg; border-color: $done; }
QFrame#jobBanner[state="attention"] { background: $attention_bg; border-color: $attention_border; }
QFrame#jobBanner[state="failed"] { background: $failed_bg; border-color: $failed_strong; }
QFrame#jobBanner QLabel#jobBannerTitle { font-weight: 600; color: $text_strong; }
QFrame#jobBanner QLabel#jobBannerNumbers { color: $running_text; }

QFrame#stepBar { background: $card; border: 1px solid $card_border; border-radius: 12px; }
QLabel[step="done"] { color: $done; background: $done_bg; border-radius: ${p12}px; font-weight: 700; }
QLabel[step="current"] { color: $on_accent; background: $accent; border-radius: ${p12}px; font-weight: 700; }
QLabel[step="later"] { color: $muted; background: transparent; border: 1px solid $outline; border-radius: ${p12}px; }
QLabel[stepText="done"] { color: $text_soft; }
QLabel[stepText="current"] { color: $text_strong; font-weight: 600; }
QLabel[stepText="later"] { color: $muted; }

QFrame#segmented { background: $input; border: 1px solid $input_border; border-radius: 10px; }
QFrame#segmented QPushButton { min-height: ${p20}px; min-width: ${p48}px; padding: ${p4}px ${p10}px; border: 0; border-radius: 7px; background: transparent; color: $muted; }
QFrame#segmented QPushButton:hover { color: $text; background: $card_border; }
QFrame#segmented QPushButton:checked { background: $segment_on; color: $text_strong; font-weight: 600; }
QFrame#segmented QPushButton:focus { border: 2px solid $accent; }

QPushButton#makeVideoCard { background: $accent; border: 1px solid $accent; border-radius: 14px; padding: 0px; text-align: left; }
QPushButton#makeVideoCard:hover { background: $link; border-color: $link; }
QPushButton#makeVideoCard:focus { border: 2px solid $link_hover; padding: 0px; }
QPushButton#makeVideoCard QLabel { color: $on_accent; }
QLabel#makeVideoTitle { font-size: ${title}pt; font-weight: 700; }
QLabel#makeVideoPlus { font-size: ${title}pt; border-radius: ${p22}px; background: $running_border; color: $on_accent; }
QPushButton#videoCard, QPushButton#continueCard { background: $card; border: 1px solid $card_border; border-radius: 12px; padding: 0px; text-align: left; }
QPushButton#videoCard:hover, QPushButton#continueCard:hover { background: $card; border-color: $outline; }
QPushButton#videoCard:focus, QPushButton#continueCard:focus { border: 2px solid $accent; padding: 0px; }
QPushButton#videoCard:pressed, QPushButton#continueCard:pressed { background: $inner; }
QLabel#videoThumb { background: $inner; border: 0; border-top-left-radius: 11px; border-top-right-radius: 11px; }
QPushButton#continueCard QLabel#videoThumb { border-radius: 8px; }
QLabel#videoCardName { font-weight: 600; color: $text_strong; }
QFrame#versionTabs { background: $card; border: 1px solid $card_border; border-radius: 10px; }
QPushButton#versionTab { border: 0; border-radius: 8px; background: transparent; color: $muted; padding: ${p4}px ${p12}px; min-height: ${p24}px; }
QPushButton#versionTab:hover { color: $text; background: $card_border; }
QPushButton#versionTab:checked { background: $segment_on; color: $text_strong; font-weight: 600; }
QPushButton#versionTab:focus { border: 2px solid $accent; padding: ${p2}px ${p10}px; }
QPushButton#editorTool { min-height: ${p24}px; padding: ${p6}px ${p12}px; border: 1px solid $input_border; border-radius: 9px; background: $card; color: $text; }
QPushButton#editorTool:hover { background: $card_border; border-color: $outline; }
QPushButton#editorTool[open="true"] { background: $selection; border-color: $accent; color: $text_strong; }
QPushButton#editorTool:focus { border: 2px solid $accent; padding: ${p5}px ${p11}px; }
QFrame#toolbarDivider { background: $input_border; margin: ${p5}px 0px; }
QFrame#toolPanel { background: $card; border: 1px solid $input_border; border-radius: 10px; }
QLabel#toolPanelHeading { color: $label; padding: ${p4}px ${p4}px 0px ${p4}px; }
QFrame#toolPanelDivider { background: $card_border; }
QLabel#toolPanelNote { color: $muted; padding: ${p2}px ${p4}px; }
QPushButton#toolPanelButton { text-align: left; min-height: ${p22}px; padding: ${p6}px ${p12}px; background: $inner; border: 1px solid $card_border; border-radius: 8px; color: $text; }
QPushButton#toolPanelButton:hover { background: $selection; border-color: $outline; color: $text_strong; }
QPushButton#toolPanelButton:checked { background: $selection; border-color: $accent; color: $text_strong; font-weight: 600; }
QPushButton#toolPanelButton:focus { border: 2px solid $accent; padding: ${p5}px ${p11}px; }
QPushButton#toolPanelButton:disabled { color: $footer; background: $disabled; border-color: $card_border; }
QWidget#posterOverlay { background: transparent; }
QPushButton#posterPlay { min-height: ${p38}px; padding: ${p6}px ${p22}px; border: 0; border-radius: ${p24}px; background: $accent; color: $on_accent; font-weight: 700; }
QPushButton#posterPlay:hover { background: $link; }
QPushButton#posterPlay:focus { border: 2px solid $link_hover; padding: ${p4}px ${p20}px; }
QPushButton#posterPlay[busy="true"] { border: 2px dashed $on_accent; }
QPushButton#posterPlaySecondary { min-height: ${p38}px; padding: ${p6}px ${p20}px; border: 1px solid rgba(255, 255, 255, 90); border-radius: ${p24}px; background: rgba(0, 0, 0, 115); color: #FFFFFF; }
QPushButton#posterPlaySecondary:hover { background: rgba(0, 0, 0, 170); border-color: #FFFFFF; }
QPushButton#posterPlaySecondary:focus { border: 2px solid $accent; padding: ${p5}px ${p19}px; }
QLabel#posterChip { color: #C9CED6; background: rgba(0, 0, 0, 128); border-radius: ${p10}px; padding: ${p2}px ${p10}px; font-size: ${small}pt; }
QLabel#posterMessage { color: #FFFFFF; background: rgba(0, 0, 0, 128); border-radius: ${p10}px; padding: ${p4}px ${p12}px; }
QWidget#posterOverlay QLabel#inlineFeedbackText { background: rgba(0, 0, 0, 150); border-radius: ${p8}px; padding: ${p2}px ${p8}px; }
QFrame#aiVideoEditorEmpty { background: $card; border: 1px solid $card_border; border-radius: 14px; }
QToolButton#scenePen { border: 1px solid transparent; border-radius: 6px; padding: ${p2}px; background: transparent; }
QToolButton#scenePen:hover { background: $card_border; border-color: $outline; }
QToolButton#scenePen:focus { border: 2px solid $accent; }
QScrollArea#sceneStripScroll, QWidget#sceneStripInner { background: transparent; border: 0; }
QPushButton#sceneBlock { background: $inner; border: 1px solid $card_border; border-radius: 8px; padding: 0px; }
QPushButton#sceneBlock:hover { border-color: $outline; background: $inner; }
QPushButton#sceneBlock:checked { background: $selection; border: 2px solid $accent; }
QPushButton#sceneBlock:focus { border: 2px solid $accent; padding: 0px; }
QPushButton#sceneChip { min-height: ${p16}px; border: 1px solid $input_border; border-radius: ${p10}px; padding: ${p1}px ${p8}px; color: $text_soft; font-size: ${small}pt; }
QPushButton#sceneChip:focus { border: 2px solid $accent; padding: 0px ${p7}px; }
QFrame#notesBox { background: $card; border: 1px solid $input_border; border-radius: 14px; }

QMenu { background: $card; color: $text; border: 1px solid $input_border; border-radius: 8px; padding: ${p4}px; }
QMenu::item { padding: ${p6}px ${p16}px; border-radius: 6px; }
QMenu::item:selected { background: $selection; color: $text_strong; }
QMenu::item:disabled { color: $footer; }
QMenu::separator { height: 1px; background: $card_border; margin: ${p4}px ${p8}px; }
QToolTip { background: $tooltip; color: $tooltip_text; border: 1px solid $outline; padding: ${p6}px; border-radius: 6px; }
QSlider::groove:horizontal { height: ${p4}px; background: $bar_track; border-radius: 2px; }
QSlider::handle:horizontal { background: $accent; width: ${p14}px; margin: -${p5}px 0; border-radius: ${p7}px; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 2px; }
""")


def build_stylesheet(theme: str = "dark", text_size: Any = DEFAULT_TEXT_SIZE, *, dpi: float | None = None,
                     dpr: float | None = None) -> str:
    """The whole stylesheet for a theme ("dark" or "light") at a text size in percent.

    Font sizes land on whole screen pixels for ``dpi`` and ``dpr`` (the screen in use when left out).
    """

    scale = normalize_text_size(text_size) / 100.0
    values: dict[str, Any] = dict(LIGHT_TOKENS if theme == "light" else DARK_TOKENS)
    values.update({name: whole_pixel_pt(size, scale, dpi, dpr) for name, size in FONT_SIZES.items()})
    values["family"] = FONT_FAMILY
    for step in range(0, 49):
        values[f"p{step}"] = int(round(step * scale))
    # The rail's row padding shrinks as the text grows (6 px at 100%, 3 px at 150%), so all of its
    # pages stay on screen in an 800 px tall window.
    values["navpad"] = int(round(6 - 6 * (scale - 1)))
    values["navrow"], values["navlabel"] = nav_row_heights(scale)
    suffix = "light" if theme == "light" else "dark"
    values["chevron_down"] = asset_url(f"chevron-down-{suffix}.svg")
    values["chevron_up"] = asset_url(f"chevron-up-{suffix}.svg")
    values["check"] = asset_url(f"check-{suffix}.svg")
    return _STYLESHEET.substitute(values)


# The stylesheets at 100% text size, as earlier versions exported them.
DARK_STYLESHEET = build_stylesheet("dark")
LIGHT_STYLESHEET = build_stylesheet("light")


def _palette(values: dict[str, str]) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(values["ground"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(values["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(values["input"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(values["inner"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(values["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(values["card"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(values["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(values["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(values["on_accent"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(values["tooltip"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(values["tooltip_text"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(values["label"]))
    palette.setColor(QPalette.ColorRole.Link, QColor(values["link"]))
    return palette


def _light_palette() -> QPalette:
    return _palette(LIGHT_TOKENS)


def apply_theme(app: QApplication, theme: str, text_size: Any = None) -> None:
    """Apply a theme ("Dark", "Light" or "System") at a text size; ``None`` keeps the text size in use."""

    app.setStyle("Fusion")
    _STATE["dpi"], _STATE["dpr"] = screen_metrics()
    if text_size is not None:
        _STATE["scale"] = normalize_text_size(text_size) / 100.0
    percent = int(round(text_scale() * 100))
    resolved = (theme or "Dark").strip().lower()
    if resolved == "system":
        # The system's own colours and controls; only the text size follows the setting.
        _STATE["theme"] = "dark" if app.styleHints().colorScheme().name == "Dark" else "light"
        app.setPalette(app.style().standardPalette())
        app.setStyleSheet(f'QWidget {{ font-family: "{FONT_FAMILY}"; font-size: {point_size("body")}pt; }}')
    else:
        _STATE["theme"] = "light" if resolved == "light" else "dark"
        app.setPalette(_palette(tokens()))
        app.setStyleSheet(build_stylesheet(_STATE["theme"], percent))
    _apply_scaled()


def apply_text_size(app: QApplication, theme: str, text_size: Any) -> None:
    """Change only the text size, live."""

    apply_theme(app, theme, text_size)
