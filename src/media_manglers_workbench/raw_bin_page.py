"""The raw bin library page (215, 216, 217): every recording, its tags and the operator's decisions.

The list comes from the library database the scan fills (``media_manglers.core.raw_bin_library``),
so opening the page reads no recording: it is instant however large the drive. The scan itself runs on
the shared runner, so Queue / Progress shows it with Pause, Skip and Stop like every other run.

Three kinds of tag stay apart here as in the database: the app's guess (only scans write it), the
operator's decision (Keep / Delete candidate / Undecided) and any number of purpose labels.

The app only marks. Nothing here writes to, moves or deletes anything on the recordings drive.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any
import uuid

from PySide6.QtCore import QItemSelection, QItemSelectionModel, QModelIndex, QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from media_manglers.core import activity_timeline, app_cache, raw_bin_library, recording_records, whisper_options
from media_manglers.core.user_folders import recordings_folders

from .ai_video_editor import cli_command
from .play_targets import PLAYER_INTERNAL, PlayTarget
from .spelling_words import SETTING_KEY as SPELLING_WORDS_KEY, split_words
from .tables import make_columns_resizable
from .ui_parts import FlowLayout, InlineFeedback, Outcome, bind_action
from .widgets import WheelSafeComboBox

PAGE_NAME = "Raw Bin"
NAV_LABEL = "Raw bin"
HOME_CARD_KEY = "raw-bin"
HOME_CARD_TITLE = "Raw bin library"
HOME_CARD_PURPOSE = (
    "Every recording in your recordings folders: what the app thinks is in it, how much of it is idle, "
    "and what you decided to keep. Nothing on the recordings drive is ever changed."
)
RUN_TITLE = "Raw bin scan"
DEEP_RUN_TITLE = "Raw bin Deep scan"

# 244 (operator decision Q2): "Mined" says which feature mined a recording for tickets, Review Media Inbox
# or Find my bug reports, in one column (it was "Inbox").
COLUMNS = ("Recording", "Guess", "Speech (min)", "Idle", "Decision", "Labels", "Mined", "Flags",
           "Length (min)", "Size (GB)", "First seen", "Folder")
COL_NAME, COL_GUESS, COL_SPEECH, COL_IDLE, COL_DECISION, COL_LABELS, COL_MINED, COL_FLAGS, \
    COL_LENGTH, COL_SIZE, COL_SEEN, COL_FOLDER = range(len(COLUMNS))
MINED_TIPS = {
    "old_list": "Find my bug reports' old list has this path. The library could not prove it is this "
                "recording, so it is matched by its path, as the old list was.",
    "no_narration": "Find my bug reports found no narration in it.",
}
# 224 (F11, Decision 9): the summary's one note while the library cannot say what Review Media Inbox reviewed
# (before its records have moved in): a blank Mined is then "not known", not "not reviewed".
INBOX_NOT_KNOWN = "whether Review Media Inbox reviewed each recording is not known yet"
ANY = "__any__"
GUESS_ORDER = {raw_bin_library.GUESS_KEEP: 0, raw_bin_library.GUESS_CHECK: 1,
               raw_bin_library.GUESS_NOTHING: 2, raw_bin_library.GUESS_EMPTY: 3}


def watched_folders(settings: dict[str, Any]) -> list[str]:
    """The recordings folders: one setting, shared with Review Media Inbox."""

    value = str(settings.get("review_source_folders") or "")
    return [part.strip() for part in value.replace("\n", ";").split(";") if part.strip()]


def raw_bin_levels_path(source: Path, *, cache_setting: str = "") -> Path | None:
    """The cached sound levels of a recording the library knows, for the player's waveform lanes.

    Read from the library alone, so the page never waits on the recordings drive. The player's own
    lookup (``track_levels.cached_levels``, off the screen's thread) also checks the file's size and
    time, and its answer replaces these when the file changed since the scan.
    """

    # Asked of the library's front door, which reads it read-only (242).
    row = recording_records.current_copy(source)
    if not row or not row["content_sha256"]:
        return None
    path = app_cache.item_path(app_cache.cache_root(cache_setting), "levels", str(row["content_sha256"]))
    return path if path.is_file() else None


class _NumberItem(QTableWidgetItem):
    """Sorts by its number, not its text."""

    def __init__(self, text: str, number: float) -> None:
        super().__init__(text)
        self.setData(Qt.ItemDataRole.UserRole + 1, float(number))

    def __lt__(self, other: QTableWidgetItem) -> bool:  # noqa: D105
        mine = self.data(Qt.ItemDataRole.UserRole + 1)
        theirs = other.data(Qt.ItemDataRole.UserRole + 1)
        if mine is None or theirs is None:
            return super().__lt__(other)
        return float(mine) < float(theirs)


class RawBinPage(QWidget):
    """The library: a sortable, filterable list, decisions, labels, Play, Deep scan and export."""

    def __init__(self, host: Any) -> None:
        super().__init__()
        self.host = host
        self.rows: list[dict[str, Any]] = []
        self.shown: list[dict[str, Any]] = []
        self.running = ""
        self.run_folder: Path | None = None
        self._connection: sqlite3.Connection | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        title = QLabel(HOME_CARD_TITLE)
        title.setProperty("title", True)
        layout.addWidget(title)
        intro = QLabel(HOME_CARD_PURPOSE)
        intro.setWordWrap(True)
        intro.setProperty("muted", True)
        layout.addWidget(intro)

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        top = FlowLayout()
        self.scan_button = QPushButton("Scan now")
        self.scan_button.setProperty("primary", True)
        self.scan_button.setToolTip("Reads only recordings that are new or changed since the last scan.")
        top.addWidget(self.scan_button)
        self.deep_button = QPushButton("Deep scan")
        self.deep_button.setToolTip(
            "Transcribes the selected recordings to find your \"flag for AI\" requests. Slow; Scan now never "
            "transcribes."
        )
        top.addWidget(self.deep_button)
        self.export_button = QPushButton("Export view…")
        self.export_button.setToolTip("Saves the recordings shown now as a CSV or JSON file.")
        top.addWidget(self.export_button)
        # 237: what each button did, beside it; a scan running shows in the job banner under them.
        self.top_feedback = InlineFeedback()
        self.top_feedback.setObjectName("rawBinTopFeedback")
        top.addWidget(self.top_feedback)
        layout.addLayout(top)
        for button, action, working, done in (
            (self.scan_button, self.start_scan, "Starting…", "Started"),
            (self.deep_button, self.start_deep_scan, "Starting…", "Started"),
            (self.export_button, self.export_view, "Exporting…", "Exported"),
        ):
            bind_action(button, action, working=working, done=done, feedback=self.top_feedback)
        maker = getattr(host, "make_job_banner", None)
        self.job_banner = maker(PAGE_NAME) if callable(maker) else None
        if self.job_banner is not None:
            layout.addWidget(self.job_banner)

        # Two rows, so every control keeps its full width in the smallest window.
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search names and folders")
        self.search_edit.textChanged.connect(self._apply_filters)
        layout.addWidget(self.search_edit)
        filters = QHBoxLayout()
        self.guess_filter = WheelSafeComboBox()
        self.guess_filter.addItem("Any guess", ANY)
        for code in GUESS_ORDER:
            self.guess_filter.addItem(raw_bin_library.GUESS_TEXT[code], code)
        self.guess_filter.currentIndexChanged.connect(self._apply_filters)
        filters.addWidget(self.guess_filter)
        self.decision_filter = WheelSafeComboBox()
        self.decision_filter.addItem("Any decision", ANY)
        for code, text in raw_bin_library.DECISION_TEXT.items():
            self.decision_filter.addItem(text, code)
        self.decision_filter.currentIndexChanged.connect(self._apply_filters)
        filters.addWidget(self.decision_filter)
        self.label_filter = WheelSafeComboBox()
        self.label_filter.currentIndexChanged.connect(self._apply_filters)
        filters.addWidget(self.label_filter)
        self.missing_check = QCheckBox("Show missing")
        self.missing_check.setToolTip("Recordings no longer in your folders keep their tags; show them too.")
        self.missing_check.toggled.connect(self._apply_filters)
        filters.addWidget(self.missing_check)
        filters.addStretch(1)
        layout.addLayout(filters)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setObjectName("rawBinTable")
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._show_selection)
        make_columns_resizable(self.table, widths={COL_NAME: 260, COL_FOLDER: 220},
                               fit_texts={COL_GUESS: list(raw_bin_library.GUESS_TEXT.values()),
                                          COL_DECISION: list(raw_bin_library.DECISION_TEXT.values()),
                                          COL_IDLE: ["100% (estimated)", "unknown"],
                                          COL_MINED: ["Inbox + Bugs (old list)", "Bugs: no narration"]})
        layout.addWidget(self.table, 1)
        opener = getattr(host, "video_opener", None)
        if opener is not None:
            opener.attach(self.table, self._targets_for, label="Raw bin")

        actions = QHBoxLayout()
        self.play_button = QPushButton("Play")
        self.play_button.setToolTip("Opens the recording in the built-in player at its first speech, on the "
                                    "narration track.")
        actions.addWidget(self.play_button)
        decisions = QHBoxLayout()
        decisions.addWidget(QLabel("Decision:"))
        self.decision_buttons: dict[str, QPushButton] = {}
        for code in (raw_bin_library.DECISION_KEEP, raw_bin_library.DECISION_DELETE, raw_bin_library.DECISION_UNDECIDED):
            button = QPushButton(raw_bin_library.DECISION_TEXT[code])
            button.setObjectName(f"rawBinDecision-{code}")
            decisions.addWidget(button)
            self.decision_buttons[code] = button
        self.actions_feedback = InlineFeedback()
        self.actions_feedback.setObjectName("rawBinActionsFeedback")
        decisions.addWidget(self.actions_feedback)
        for code, button in self.decision_buttons.items():
            bind_action(button, lambda value=code: self.set_decision(value), working="Saving…", done="Saved",
                        feedback=self.actions_feedback)
        bind_action(self.play_button, self.play_selected, working="Opening…", done="Playing in the player",
                    feedback=self.actions_feedback)
        decisions.addStretch(1)
        self.labels_button = QToolButton()
        self.labels_button.setText("Labels")
        self.labels_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.labels_menu = QMenu(self.labels_button)
        self.labels_menu.aboutToShow.connect(self._fill_labels_menu)
        self.labels_button.setMenu(self.labels_menu)
        actions.addWidget(self.labels_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addLayout(decisions)

        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setProperty("muted", True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.detail)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        changed = getattr(host, "run_availability_changed", None)
        if changed is not None:
            changed.connect(self._refresh_buttons)
        self._refresh_buttons()

    # The library ------------------------------------------------------------------------------

    def connection(self) -> sqlite3.Connection:
        """The Workbench's own library connection (242); a page without one opens its own the first time
        it is used, which is also when today's backup is taken."""

        records = self._records()
        if records is not None:
            return records.connection()
        if self._connection is None:
            self._connection = recording_records.connect()
        return self._connection

    def _records(self) -> recording_records.Records | None:
        records = getattr(self.host, "records", None)
        return records if isinstance(records, recording_records.Records) else None

    def _library_root(self) -> Path:
        records = self._records()
        return Path(records.root) if records is not None else recording_records.library_root()

    def close_library(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def refresh(self) -> None:
        try:
            # 244: asked of the front door, which adds what mined each recording (the Inbox's part from the
            # Inbox's records in the same library since 224).
            self.rows = recording_records.list_library(self.connection())
        except (OSError, sqlite3.Error, ValueError) as exc:
            self.rows = []
            self._say(f"The library could not be opened: {exc}", "failed")
        self._fill_label_filter()
        self._apply_filters()
        folders = watched_folders(self._settings())
        last = self._last_scan()
        missing = sum(1 for row in self.rows if row.get("missing"))
        parts = [f"{len(self.rows) - missing} recordings"]
        if missing:
            parts.append(f"{missing} missing")
        parts.append(f"last scan {last}" if last else "not scanned yet")
        if not folders:
            parts.append("no recordings folder set: set it in Review Media Inbox's settings")
        if self.rows and not all(row.get("inbox_known", True) for row in self.rows):
            # 224 (F11, Decision 9): "not known" is never shown as "not reviewed".
            parts.append(INBOX_NOT_KNOWN)
        self.summary.setText(", ".join(parts) + ".")
        self._refresh_buttons()

    def _settings(self) -> dict[str, Any]:
        merged = dict(self.host.app_settings)
        for key in ("review_source_folders",):
            if self.host.run_settings.get(key):
                merged[key] = self.host.run_settings.get(key)
        return merged

    def _last_scan(self) -> str:
        try:
            finished = recording_records.last_scan_finished(self.connection())
        except (OSError, sqlite3.Error, ValueError):
            return ""
        if not finished:
            return ""
        try:
            return datetime.fromisoformat(finished.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return finished

    # Filters and the table ---------------------------------------------------------------------

    def _fill_label_filter(self) -> None:
        current = self.label_filter.currentData()
        self.label_filter.blockSignals(True)
        self.label_filter.clear()
        self.label_filter.addItem("Any label", ANY)
        try:
            names = raw_bin_library.label_names(self.connection())
        except sqlite3.Error:
            names = []
        for name in names:
            self.label_filter.addItem(name, name)
        position = self.label_filter.findData(current)
        self.label_filter.setCurrentIndex(max(0, position))
        self.label_filter.blockSignals(False)

    def _matches(self, row: dict[str, Any]) -> bool:
        if row.get("missing") and not self.missing_check.isChecked():
            return False
        guess = self.guess_filter.currentData()
        if guess not in (None, ANY) and row.get("guess") != guess:
            return False
        decision = self.decision_filter.currentData()
        if decision not in (None, ANY) and row.get("decision") != decision:
            return False
        label = self.label_filter.currentData()
        if label not in (None, ANY) and label not in (row.get("labels") or []):
            return False
        words = self.search_edit.text().strip().casefold()
        return not words or words in str(row.get("path") or "").casefold()

    def _apply_filters(self, *_args: Any) -> None:
        # 222: the rows are written again in the library's own order and then sorted, so a selection
        # left to Qt would stay on the old row number and land on another recording. The selection is
        # taken by recording id first and put back on the same recordings, or cleared when they are no
        # longer listed; the line under the list is told once, when the list is final.
        keep = set(self.selected_ids())
        self.shown = [row for row in self.rows if self._matches(row)]
        with QSignalBlocker(self.table):
            self.table.clearSelection()
            self._fill_rows()
            self._select_ids(keep)
        self._show_selection()

    def _fill_rows(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.shown))
        for index, row in enumerate(self.shown):
            path = Path(str(row.get("path") or ""))
            exported = raw_bin_library.export_row(row)
            name = QTableWidgetItem(path.name or "(unknown)")
            name.setData(Qt.ItemDataRole.UserRole, int(row["recording_id"]))
            name.setToolTip(str(path))
            self.table.setItem(index, COL_NAME, name)
            self.table.setItem(index, COL_GUESS, _NumberItem(exported["guess"], GUESS_ORDER.get(row.get("guess"), 9)))
            self.table.setItem(index, COL_SPEECH, _NumberItem(str(exported["minutes_of_speech"]),
                                                               float(exported["minutes_of_speech"] or 0)))
            share = row.get("idle_share")
            idle_text = exported["idle_share"] or "unknown"
            if row.get("idle_status") == activity_timeline.STATUS_ESTIMATED:
                idle_text += " (estimated)"
            idle = _NumberItem(idle_text, -1 if share is None else float(share))
            idle.setToolTip(str(row.get("idle_reason") or ""))
            self.table.setItem(index, COL_IDLE, idle)
            self.table.setItem(index, COL_DECISION, QTableWidgetItem(exported["decision"]))
            self.table.setItem(index, COL_LABELS, QTableWidgetItem(exported["labels"]))
            mined = QTableWidgetItem(str(row.get("mined") or ""))
            mined.setToolTip(MINED_TIPS.get(str(row.get("bugs_mined") or ""), ""))
            self.table.setItem(index, COL_MINED, mined)
            flags = row.get("flag_count")
            self.table.setItem(index, COL_FLAGS, _NumberItem("" if flags is None else str(flags),
                                                              -1 if flags is None else float(flags)))
            self.table.setItem(index, COL_LENGTH, _NumberItem(str(exported["duration_minutes"]),
                                                               float(exported["duration_minutes"] or 0)))
            self.table.setItem(index, COL_SIZE, _NumberItem(str(exported["size_gb"]), float(exported["size_gb"] or 0)))
            self.table.setItem(index, COL_SEEN, QTableWidgetItem(str(row.get("first_seen_utc") or "")[:10]))
            folder = QTableWidgetItem(("Missing: " if row.get("missing") else "") + str(path.parent))
            self.table.setItem(index, COL_FOLDER, folder)
        self.table.setSortingEnabled(True)

    def _select_ids(self, ids: set[int]) -> None:
        """Select the rows of these recordings, make the first one current and bring it into view."""

        model = self.table.selectionModel()
        selection = QItemSelection()
        first: int | None = None
        for index in range(self.table.rowCount()):
            item = self.table.item(index, COL_NAME)
            if item is None or item.data(Qt.ItemDataRole.UserRole) not in ids:
                continue
            selection.select(self.table.model().index(index, 0),
                             self.table.model().index(index, self.table.columnCount() - 1))
            if first is None:
                first = index
        if first is None:
            model.clearCurrentIndex()
            return
        model.select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect
                     | QItemSelectionModel.SelectionFlag.Rows)
        model.setCurrentIndex(self.table.model().index(first, COL_NAME), QItemSelectionModel.SelectionFlag.NoUpdate)
        self.table.scrollToItem(self.table.item(first, COL_NAME))

    def selected_ids(self) -> list[int]:
        ids = []
        for index in self.table.selectionModel().selectedRows(COL_NAME) if self.table.selectionModel() else []:
            item = self.table.item(index.row(), COL_NAME)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) is not None:
                ids.append(int(item.data(Qt.ItemDataRole.UserRole)))
        return ids

    def _row_for(self, recording_id: int) -> dict[str, Any] | None:
        return next((row for row in self.rows if int(row["recording_id"]) == int(recording_id)), None)

    def _show_selection(self) -> None:
        ids = self.selected_ids()
        row = self._row_for(ids[0]) if len(ids) == 1 else None
        if row is None:
            self.detail.setText(f"{len(ids)} recordings selected." if ids else "")
        else:
            parts = [str(row.get("guess_reason") or "")]
            if row.get("idle_status") == activity_timeline.STATUS_ESTIMATED:
                reason = str(row.get("idle_reason") or "Estimated from the full mix.")
                parts.append(f"Idle time {reason[0].lower()}{reason[1:]}")
            elif row.get("idle_status") == activity_timeline.STATUS_UNKNOWN:
                reason = str(row.get("idle_reason") or "No game-audio track was found.")
                parts.append(f"Idle time unknown: {reason[0].lower()}{reason[1:]}")
            if row.get("flags"):
                parts.append("Flag for AI: " + "; ".join(f"{int(item['start']) // 60}:{int(item['start']) % 60:02d} "
                                                         f"{item['text'][:80]}" for item in row["flags"][:5]))
            parts.append(str(row.get("path") or ""))
            self.detail.setText("  ".join(part for part in parts if part))
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        ids = self.selected_ids() if hasattr(self, "table") else []
        busy = bool(self.running) or getattr(self.host, "runner_thread", None) is not None
        if not hasattr(self, "play_button"):
            return
        self.play_button.setEnabled(len(ids) == 1)
        for button in self.decision_buttons.values():
            button.setEnabled(bool(ids))
        self.labels_button.setEnabled(bool(ids))
        self.scan_button.setEnabled(not busy)
        self.deep_button.setEnabled(bool(ids) and not busy)
        # 237: while a scan runs, its button says so.
        self.scan_button.setText("Scanning…" if self.running == "scan" else "Scan now")
        self.deep_button.setText("Deep scanning…" if self.running == "deep" else "Deep scan")

    # Decisions and labels -----------------------------------------------------------------------

    def set_decision(self, decision: str) -> Outcome:
        ids = self.selected_ids()
        if not ids:
            return Outcome.quiet()
        try:
            raw_bin_library.set_decision(self.connection(), ids, decision)
        except sqlite3.Error as exc:
            self._say(f"The decision was not saved: {exc}. Try again in a moment.", "failed")
            return Outcome.failed(f"Not saved: {exc}.", "Try again in a moment.")
        text = f"{raw_bin_library.DECISION_TEXT[decision]}: {len(ids)} recording{'s' if len(ids) != 1 else ''}."
        self._say(text, "completed")
        self._reload_keeping_selection(ids)
        return Outcome.done(f"Saved. {text}")

    def _fill_labels_menu(self) -> None:
        self.labels_menu.clear()
        ids = self.selected_ids()
        rows = [row for row in (self._row_for(item) for item in ids) if row is not None]
        try:
            names = raw_bin_library.label_names(self.connection())
        except sqlite3.Error:
            names = []
        for name in names:
            action = self.labels_menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(bool(rows) and all(name in (row.get("labels") or []) for row in rows))
            action.toggled.connect(lambda on, label=name: self.set_label(label, on))
        self.labels_menu.addSeparator()
        self.labels_menu.addAction("New label…").triggered.connect(self.new_label)

    def set_label(self, name: str, on: bool) -> None:
        ids = self.selected_ids()
        if not ids:
            return
        try:
            raw_bin_library.set_label(self.connection(), ids, name, on)
        except (sqlite3.Error, ValueError) as exc:
            self._say(f"The label was not saved: {exc}", "failed")
            return
        self._reload_keeping_selection(ids)

    def new_label(self) -> None:
        name, ok = QInputDialog.getText(self, "New label", "Label name:")
        if ok and str(name).strip():
            self.set_label(str(name).strip(), True)

    def _reload_keeping_selection(self, ids: list[int]) -> None:
        # 222: every reload keeps the selection by recording id, so the line under the list no longer
        # shows another recording for a moment before the selection is put back.
        self.refresh()
        if set(self.selected_ids()) != set(ids):
            with QSignalBlocker(self.table):
                self.table.clearSelection()
                self._select_ids(set(ids))
            self._show_selection()

    # Play ---------------------------------------------------------------------------------------

    def target_for(self, row: dict[str, Any]) -> PlayTarget:
        """The recording at its first speech on the narration track, or its first active stretch."""

        speech = [tuple(item) for item in row.get("speech_stretches") or []]
        active = [tuple(item) for item in row.get("active_stretches") or []]
        stretches, kind = (speech, "speech") if speech else (active, "active")
        start = stretches[0][0] if stretches else 0.0
        hear = row.get("narration_track") or row.get("other_speech_track")
        levels = None
        if row.get("content_sha256"):
            candidate = app_cache.item_path(app_cache.cache_root(str(self.host.app_settings.get("cache_folder") or "")),
                                            "levels", str(row["content_sha256"]))
            levels = candidate if candidate.is_file() else None
        return PlayTarget(
            path=Path(str(row.get("path") or "")),
            start_seconds=float(start),
            label=f"Raw bin: {raw_bin_library.GUESS_TEXT.get(str(row.get('guess')), '')}",
            voice_track=row.get("narration_track"),
            voice_source="raw bin" if row.get("narration_track") else "",
            hear_track=hear,
            stretches=tuple(stretches),
            stretch_kind=kind if stretches else "",
            levels_path=levels,
            # 264 (Q2): the player looks up the finer jumps off the screen's thread, once this recording is measured.
            refine_stretches=True,
        )

    def _targets_for(self, index: QModelIndex) -> list[PlayTarget]:
        item = self.table.item(index.row(), COL_NAME)
        row = self._row_for(int(item.data(Qt.ItemDataRole.UserRole))) if item is not None else None
        return [self.target_for(row)] if row is not None and not row.get("missing") else []

    def play_selected(self) -> Outcome:
        ids = self.selected_ids()
        row = self._row_for(ids[0]) if len(ids) == 1 else None
        opener = getattr(self.host, "video_opener", None)
        if row is None or opener is None:
            return Outcome.quiet()
        if row.get("missing"):
            self._say("That recording is missing from your folders.", "attention")
            return Outcome.failed("That recording is missing from your folders.",
                                  "Tick Show missing off, or put the recording back in its folder.")
        opener.open(self.target_for(row), player=PLAYER_INTERNAL)
        return Outcome.done("Playing in the player")

    # Scans --------------------------------------------------------------------------------------

    def _run_folder(self, kind: str) -> Path:
        folder = self._library_root() / "runs" / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{kind}"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _payload(self) -> dict[str, Any]:
        settings = self._settings()
        resources = self.host.resources
        # 226: the one Whisper settings rule: model, graphics card and language from the main settings.
        whisper = whisper_options.from_settings(settings)
        return {
            "folders": watched_folders(settings),
            "ffmpeg": str(getattr(resources, "ffmpeg_exe", "") or "ffmpeg"),
            "ffprobe": str(getattr(resources, "ffprobe_exe", "") or "ffprobe"),
            "model_name": whisper["model_name"],
            "prefer_gpu": whisper["prefer_gpu"],
            "language": whisper["language_code"],
            "track_roles": str(settings.get("evidence_track_roles") or ""),
            "cache_folder": str(settings.get("cache_folder") or ""),
            "cache_cap_bytes": int(settings.get("cache_size_gb") or 10) * 1024 ** 3,
            # 242: the scan opens the same library the Workbench has open.
            "library_root": str(self._library_root()),
        }

    def _start(self, kind: str, command: str, payload: dict[str, Any], title: str, items: list[str],
               record_items: list[str] | None = None) -> Outcome:
        if not payload.get("folders"):
            QMessageBox.information(self, "No recordings folder", "Set your recordings folder first: Review Media "
                                    "Inbox > Settings > Review source folders.")
            return Outcome.quiet()
        folder = self._run_folder(kind)
        control = folder / "run-control.json"
        # 243: the run's number in the library, named here so the scan can write each recording's
        # outcome into it as it stores it.
        run_id = uuid.uuid4().hex
        payload = {**payload, "run_control_path": str(control), "records_run_id": run_id}
        request, result = folder / "request.json", folder / "result.json"
        request.write_text(json.dumps({"payload": payload}, indent=2), encoding="utf-8")
        settings = dict(self.host.app_settings)
        settings["output_folder"] = str(self._library_root())
        settings["run_control_path"] = str(control)
        spec = cli_command(self.host.resources, command, request, result)
        banner = {"origin": PAGE_NAME, "banner_title": title} if hasattr(self.host, "make_job_banner") else {}
        if not self.host.start_external_run(spec, title=title, settings=settings, queue_items=items,
                                            listener=self, evidence_package=False, **banner,
                                            **({"kind": "raw_deep_scan" if kind == "deep" else "raw_scan",
                                                "run_id": run_id, "record_items": record_items}
                                               if self._records() is not None else {})):
            return Outcome.quiet()
        self.running, self.run_folder = kind, folder
        # 237: the job banner shows how far it has got; Pause and Stop are on Queue / Progress.
        self._say(f"{title} started. You can pause or stop it on Queue / Progress.", "active")
        self._refresh_buttons()
        return Outcome.done("Started")

    def start_scan(self) -> Outcome:
        payload = self._payload()
        return self._start("scan", "raw-bin-scan", payload, RUN_TITLE, list(payload.get("folders") or []))

    def start_deep_scan(self) -> Outcome:
        ids = self.selected_ids()
        if not ids:
            return Outcome.quiet()
        # The words to spell right, the one list every transcript uses (201).
        payload = {**self._payload(), "recording_ids": ids,
                   "glossary_entries": split_words(self.host.app_settings.get(SPELLING_WORDS_KEY))}
        paths = [str((self._row_for(item) or {}).get("path") or "") for item in ids]
        return self._start("deep", "raw-bin-deep-scan", payload, DEEP_RUN_TITLE, [Path(path).name for path in paths],
                           record_items=[path for path in paths if path])

    def on_log_line(self, _stream: str, line: str) -> None:
        text = str(line).strip()
        if text and not text.startswith("MM_PROGRESS_V1"):
            self.status.setText(text[:300])

    def on_finished(self, result: Any) -> None:
        kind, self.running = self.running, ""
        outcome: dict[str, Any] = {}
        if self.run_folder is not None:
            try:
                outcome = json.loads((self.run_folder / "result.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                outcome = {}
        data = outcome.get("data") or {}
        status = str(getattr(result, "status", "") or "")
        if status == "cancelled":
            self._say("Stopped. What was finished is kept; the next scan carries on from there.", "cancelled")
        elif not outcome.get("ok"):
            self._say(f"The {'Deep scan' if kind == 'deep' else 'scan'} did not finish: "
                      f"{outcome.get('error') or 'open it in Queue / Progress for the log'}", "failed")
        elif kind == "scan" and data.get("status") in {"drive_not_reachable", "model_not_approved"}:
            # Installer plan, Stage 3: a Whisper model not approved stops the scan once, with what to do.
            self._say(str(data.get("message") or "Recordings drive not reachable."), "attention")
        elif kind == "scan":
            self._say(f"Scan finished: {data.get('files_read', 0)} read, {data.get('unchanged', 0)} unchanged, "
                      f"{data.get('missing_marked', 0)} newly missing.", "completed")
        else:
            found = sum(int(item.get("flag_count") or 0) for item in data.get("results") or [])
            self._say(f"Deep scan finished: {found} flag-for-AI request{'s' if found != 1 else ''} found.", "completed")
        self._record_outcome(result, kind, outcome)
        self.refresh()

    def _record_outcome(self, result: Any, kind: str, outcome: dict[str, Any]) -> None:
        """243: the scan's real result in History (a drive that could not be reached is Failed, 213), and
        each recording's outcome: a scan writes its own as it stores each recording; a Deep scan's come
        from its result here."""

        records = self._records()
        run_id = str(getattr(result, "run_id", "") or "")
        if records is None or not run_id or str(getattr(result, "status", "") or "") == "cancelled":
            return
        data = outcome.get("data") or {}
        try:
            if not outcome.get("ok"):
                records.finish_run(run_id, "failed", headline=str(outcome.get("error") or "The scan did not finish."),
                                   reported_by=PAGE_NAME)
            elif kind == "scan":
                counts = {key: data.get(key, 0) for key in ("files_seen", "files_read", "unchanged", "in_use",
                                                             "skipped", "failed", "missing_marked")}
                if data.get("status") in {"drive_not_reachable", "model_not_approved"}:
                    records.finish_run(run_id, "failed", headline=str(data.get("message") or "Drive not reachable."),
                                       reported_by=PAGE_NAME, counts=counts)
                else:
                    state = "completed_with_problems" if int(data.get("failed") or 0) else "completed"
                    records.finish_run(run_id, state, headline=self.status.text(), reported_by=PAGE_NAME,
                                       counts=counts)
            else:
                outcomes = []
                for item in data.get("results") or []:
                    row = self._row_for(int(item.get("recording_id") or 0)) or {}
                    status = str(item.get("status") or "")
                    outcomes.append({
                        "item": str(row.get("path") or f"recording {item.get('recording_id')}"),
                        "recording_id": item.get("recording_id"),
                        "outcome": {"transcribed": "completed", "no_track": "no_narration"}.get(status, "failed"),
                        "reason": (f"{item.get('flag_count') or 0} flag-for-AI request(s)" if status == "transcribed"
                                   else str(item.get("message") or item.get("error") or "")),
                    })
                records.record_outcomes(run_id, outcomes, reported_by=PAGE_NAME)
                failed = any(entry["outcome"] == "failed" for entry in outcomes)
                records.finish_run(run_id, "completed_with_problems" if failed else "completed",
                                   headline=self.status.text(), reported_by=PAGE_NAME)
        except (OSError, sqlite3.Error, ValueError):
            pass

    def on_run_control_changed(self) -> None:
        return None

    # Export -------------------------------------------------------------------------------------

    def export_view(self) -> Outcome:
        start = str(Path(str(self.host.app_settings.get("output_folder") or "")) / "raw-bin.csv")
        path, _chosen = QFileDialog.getSaveFileName(self, "Export the recordings shown", start,
                                                    "CSV (*.csv);;JSON (*.json)")
        if not path:
            return Outcome.quiet()
        written = self.export_to(Path(path))
        # A refusal is said in its own dialog.
        return Outcome.done(f"Exported {len(self.shown)} recordings") if written else Outcome.quiet()

    def export_to(self, path: Path) -> Path | None:
        try:
            written = raw_bin_library.export(self.shown, path, recordings_folders=recordings_folders()
                                             or watched_folders(self._settings()))
        except (OSError, ValueError) as exc:
            QMessageBox.information(self, "Not exported", str(exc))
            return None
        self._say(f"Exported {len(self.shown)} recordings to {written}.", "completed")
        return written

    def _say(self, text: str, state: str = "") -> None:
        from .ai_video_editor import _show_kind  # noqa: PLC0415

        self.status.setText(text)
        _show_kind(self.status, state)


def home_card_frame(on_start: Any) -> tuple[QFrame, QPushButton]:
    """The Home card under "Other tasks". Start opens the page; it is not a workflow."""

    frame = QFrame()
    frame.setProperty("card", True)
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    layout = QVBoxLayout(frame)
    heading = QLabel(HOME_CARD_TITLE)
    heading.setProperty("sectionTitle", True)
    layout.addWidget(heading)
    purpose = QLabel(HOME_CARD_PURPOSE)
    purpose.setWordWrap(True)
    purpose.setProperty("muted", True)
    layout.addWidget(purpose)
    layout.addStretch(1)
    row = QHBoxLayout()
    row.addStretch(1)
    start = QPushButton("Start")
    start.clicked.connect(on_start)
    row.addWidget(start)
    layout.addLayout(row)
    return frame, start
