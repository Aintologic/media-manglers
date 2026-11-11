"""Task-oriented PySide6 desktop application for Video Mangler."""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
import functools
from datetime import datetime
import hashlib
from html import escape
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import threading
import time
from typing import Any, Callable

from PySide6.QtCore import QByteArray, QModelIndex, QSignalBlocker, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QFont, QFontMetrics, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from media_manglers.core import (
    review_inbox,
    review_orchestration,
)
from media_manglers.core import app_cache, app_locks, inbox_move, inbox_records, recording_records, safe_write, speech_facts
from .track_roles import SETTING_KEY as TRACK_ROLES_SETTING_KEY
from media_manglers.core.recording_records import Records, import_legacy_settings
from media_manglers.core.user_folders import recordings_drive_problem, set_recordings_folders, temporary_folder_problem

from . import __version__, run_outcomes
from .audio_detection import (
    LayoutConfirmationStore,
    SAFE_CONFIDENCE_THRESHOLD,
    SourceAudioInspection,
    VoiceEnrollmentStore,
    analyze_wav,
    apply_selection_precedence,
    discover_media_files,
    extract_sample,
    inspect_source,
)
from .ai_video_editor import HOME_CARD_KEY as AI_VIDEO_EDITOR_HOME_CARD
from .ai_video_editor import NAV_LABEL as AI_VIDEO_EDITOR_NAV_LABEL
from .ai_video_editor import PAGE_NAME as AI_VIDEO_EDITOR_PAGE
from .ai_video_editor import AiVideoEditorPage, AiVideoEditorSettingsPanel, cli_command, home_card_frame
from .run_status import CANCELLED as RUN_CANCELLED, FAILED as RUN_FAILED, counts_as_warning, \
    decide as decide_run_status, never_ran as run_never_ran, stage_text as run_stage_text
from .raw_bin_page import HOME_CARD_KEY as RAW_BIN_HOME_CARD
from .raw_bin_page import NAV_LABEL as RAW_BIN_NAV_LABEL
from .raw_bin_page import PAGE_NAME as RAW_BIN_PAGE
from .raw_bin_page import RawBinPage, home_card_frame as raw_bin_home_card_frame, raw_bin_levels_path, watched_folders
from .spelling_words_panel import SpellingWordsPanel
from .track_roles import TrackRolesPanel
from .audio_widgets import format_hms
from .bug_reports import NAV_LABEL as BUG_REPORTS_NAV_LABEL
from .bug_reports import PAGE_NAME as BUG_REPORTS_PAGE
from .bug_reports import BugReportsPage
from .build_identity import resolve_build_identity
from .command_builder import CommandSpec, build_workflow_command, validate_effective_command
from .dependencies import (
    VOICE_MODEL,
    DependencyCheckStopped,
    DependencyPreflightResult,
    StoppableRunner,
    _end_process_tree,
    run_dependency_preflight,
    translation_needs_argos,
)
from media_manglers.contracts import write_json_file
from media_manglers.core.race_video.requests import quick_model as editor_quick_model
from .estimates import estimate_sampling
from .evidence import EvidenceCandidate, EvidencePackage, SessionMention, load_evidence_package
from .metadata import (
    ALL_WORKFLOWS,
    DEFAULT_WORKFLOW,
    METADATA_BY_KEY,
    SETTING_METADATA,
    WORKFLOW_ARCHIVE_CATALOG,
    WORKFLOW_BY_NUMBER,
    WORKFLOW_CODEX_EVIDENCE,
    WORKFLOW_FULL_REVIEW,
    WORKFLOW_REVIEW_NEW_VIDEOS,
    WORKFLOW_TRANSCRIPT_ONLY,
    WORKFLOWS,
    SettingMetadata,
    normalize_workflow,
)
from .prompts import (
    build_claude_prompt,
    build_codex_prompt,
    build_session_prompt,
    export_prompt_drafts,
    export_session_prompt_drafts,
)
from .levels_service import LevelsService, parked_threads as parked_levels_threads
from .recording_lists import held_in_settings, path_key
from .missing_tools_notice import MissingToolsNotice
# 125, 134 (Wave 8): the moment-time rule and the kind words now live beside the package readers.
from .review_package import moment_kind_text, moment_seconds as _moment_seconds, narration_files, recording_for_source
from .resources import DependencyStatus, RuntimeResources, discover_runtime_resources
from .review_inbox_dialogs import (
    ReviewInboxAllPendingDialog,
    ReviewInboxAudioChoiceDialog,
    ReviewInboxCleanupDialog,
    ReviewInboxSettingsDialog,
    ReviewInboxTechnicalDialog,
)
from .run_control import RunControl
from .main_settings import main_temp_folder, review_evidence_root, review_work_root, run_output_folder, track_choice_state
from .runner import FakeRunner, RunnerResult, SubprocessRunner, hidden_subprocess_creation_flags
from .settings import (
    BUG_REPORT_RECORDING_LIST_KEYS,
    BUG_REPORT_STOPPED_RUN_KEY,
    LoadedProfile,
    ProfileManager,
    build_default_settings,
    clean_workbench_owned_path,
    default_log_folder,
    default_profiles_dir,
    default_settings_path,
    default_temp_folder,
    export_settings_bundle,
    import_settings_bundle,
    load_settings,
    new_workbench_log_path,
    save_settings,
    starter_profile_settings,
)
from .tables import make_columns_resizable
from .theme import TEXT_SIZES, apply_theme, normalize_text_size, status_color, status_kind, step_text_size
from . import theme as ui_theme
from .ui_parts import (
    FlowLayout,
    JobBanner,
    JobInfo,
    InlineFeedback,
    Outcome,
    PageStack,
    SegmentedControl,
    WrappingTabStrip,
    bind_action,
    line_icon,
    polish_forms,
    polish_views,
    repolish,
    set_button_kind,
    set_work_bar,
    time_left_text,
    warn,
    work_done_text,
)
from .tool_sources import bundled_tool, needs_download, tool_source
from .video_open import (
    PlaySequence,
    PlayTarget,
    VideoOpener,
    VideoPlayerSettingsPanel,
    is_video_path,
    path_role_resolver,
)
from .widgets import WheelSafeComboBox, WheelSafeDoubleSpinBox, WheelSafeSpinBox


# 237 (design wave D1, approved 2026-10-23): the rail in four groups, with Settings and Help at the
# bottom (governance/UI_RULES.md section 9). Every page keeps its rail text and accessible name.
NAV_GROUPS = (
    ("Make", ("Home", BUG_REPORTS_PAGE, AI_VIDEO_EDITOR_PAGE, "New Review")),
    # 220: the raw bin library and the Inbox, side by side (152).
    ("Library", (RAW_BIN_PAGE, "Review Media Inbox")),
    ("Results", ("Evidence", "Session Review", "Prompt Drafts", "History")),
    ("Running", ("Queue / Progress",)),
)
NAV_BOTTOM = ("Settings", "Help")
# 237: each rail page's line icon (src/media_manglers_workbench/assets/nav).
NAV_ICONS = {
    "Home": "home",
    BUG_REPORTS_PAGE: "bugs",
    AI_VIDEO_EDITOR_PAGE: "editor",
    "New Review": "new",
    RAW_BIN_PAGE: "rawbin",
    "Review Media Inbox": "inbox",
    "Evidence": "evidence",
    "Session Review": "session",
    "Prompt Drafts": "drafts",
    "History": "history",
    "Queue / Progress": "progress",
    "Settings": "settings",
    "Help": "help",
}
PAGE_NAMES = tuple(name for _group, names in NAV_GROUPS for name in names) + NAV_BOTTOM
TEXT_SIZE_KEY = "text_size_percent"
# 237: the Home task cards, this many to a row.
HOME_CARD_COLUMNS = 3

NAV_LABELS = {
    "Home": "Home",
    BUG_REPORTS_PAGE: BUG_REPORTS_NAV_LABEL,
    "New Review": "New",
    RAW_BIN_PAGE: RAW_BIN_NAV_LABEL,
    "Review Media Inbox": "Inbox",
    "Queue / Progress": "Progress",
    "Evidence": "Evidence",
    "Session Review": "Session",
    "Prompt Drafts": "Drafts",
    "History": "History",
    AI_VIDEO_EDITOR_PAGE: AI_VIDEO_EDITOR_NAV_LABEL,
    "Settings": "Settings",
    "Help": "Help",
}

# 95 hid the Review Media Inbox from the rail; 152 (Wave 6, 220) brings it back, beside the raw bin
# library, because it does what Find my bug reports does not: watch folders and remember what is done.
HIDDEN_NAV_PAGES: set[str] = set()

# Plain names for the backend's processing phases on the Progress page.
PHASE_DISPLAY_NAMES = {
    "Transcription": "Finding your voice and writing down what you said",
    "Rich rendering": "Screenshots of flagged moments",
    "Narration visuals": "Screenshots and clips of everything you said",
    "Package": "Building the package",
}
TERMINAL_PROGRESS_ITEM_STATES = {"completed", "failed", "skipped", "cancelled", "no_narration"}

HELP_WORKFLOW_LABELS = {
    WORKFLOW_FULL_REVIEW: "1  Full Review",
    WORKFLOW_TRANSCRIPT_ONLY: "2  Transcript Only",
    WORKFLOW_CODEX_EVIDENCE: "3  AI / Ticket Evidence",
    WORKFLOW_ARCHIVE_CATALOG: "4  Archive Catalog",
    WORKFLOW_REVIEW_NEW_VIDEOS: "5  Review Media Inbox",
}

WORKBENCH_HELP_ROOT_URL = (
    "https://github.com/Aintologic/media-manglers/blob"
)
WORKBENCH_HELP_URL = "README.md"
WORKBENCH_TROUBLESHOOTING_URL = "TROUBLESHOOTING.md"
WORKFLOW_HELP_URLS = {
    WORKFLOW_FULL_REVIEW: "FULL_REVIEW.md",
    WORKFLOW_TRANSCRIPT_ONLY: "TRANSCRIPT_ONLY.md",
    WORKFLOW_CODEX_EVIDENCE: "CODEX_EVIDENCE.md",
    WORKFLOW_ARCHIVE_CATALOG: "ARCHIVE_CATALOG.md",
    WORKFLOW_REVIEW_NEW_VIDEOS: "REVIEW_NEW_VIDEOS.md",
}
DEPENDENCY_HELP_ANCHORS = {
    "backend_sidecar": "media-manglers-helpers",
    "powershell": "windows-powershell",
    "python": "python-whisper-and-pytorch",
    "helper_import": "media-manglers-helpers",
    "ffmpeg": "ffmpeg-and-ffprobe",
    "ffprobe": "ffmpeg-and-ffprobe",
    "ytdlp": "yt-dlp-and-web-video-urls",
    "whisper": "python-whisper-and-pytorch",
    "whisper_model": "whisper-model-downloads",
    "torch": "python-whisper-and-pytorch",
    "cuda": "cuda-and-cpu-fallback",
    "cpu_fallback": "cuda-and-cpu-fallback",
}

WORKFLOW_PURPOSES = {
    WORKFLOW_FULL_REVIEW: (
        "Build a complete human/AI review package with proxy video, timeline frames, transcripts, "
        "translations, and optional ticket evidence."
    ),
    WORKFLOW_TRANSCRIPT_ONLY: (
        "Create or search transcripts from local recordings without building the full visual package."
    ),
    WORKFLOW_CODEX_EVIDENCE: (
        "Review local recordings for likely ticket moments and prepare private evidence for an AI agent."
    ),
    WORKFLOW_ARCHIVE_CATALOG: (
        "Index local recordings for archive storage and later restoration."
    ),
    WORKFLOW_REVIEW_NEW_VIDEOS: (
        "Scan configured recording folders and prepare a small, resumable batch for external review. "
        "Originals are never changed or deleted."
    ),
}

WORKFLOW_SOURCE_LABELS = {
    WORKFLOW_FULL_REVIEW: "Local files, folders, or supported URLs",
    WORKFLOW_TRANSCRIPT_ONLY: "Local files and folders",
    WORKFLOW_CODEX_EVIDENCE: "Local recordings only",
    WORKFLOW_ARCHIVE_CATALOG: "Local folders or an existing catalog",
    WORKFLOW_REVIEW_NEW_VIDEOS: "Configured local recording folders",
}

BASIC_WORKFLOW_SETTINGS = {
    WORKFLOW_FULL_REVIEW: (
        "processing_mode",
        "include_codex_evidence_package",
        "create_ai_review_zip",
        "frame_interval_seconds",
    ),
    WORKFLOW_TRANSCRIPT_ONLY: (
        "whisper_model",
        "transcript_search_terms",
        "transcript_only_recurse",
        "overwrite_transcripts",
        "skip_transcript_only_audio",
    ),
    WORKFLOW_CODEX_EVIDENCE: (
        "fragmented_narration_mode",
        "visual_context_preset",
        "narration_context_preset",
        "evidence_panel_crops",
        "evidence_target_project",
        "evidence_target_repo",
        "evidence_handoff_mode",
    ),
    WORKFLOW_ARCHIVE_CATALOG: (
        "archive_action",
        "archive_search_terms",
        "archive_hash_mode",
        "archive_thumbnail_mode",
        "archive_max_thumbnails_per_video",
    ),
    WORKFLOW_REVIEW_NEW_VIDEOS: (
        "review_source_folders",
        "review_evidence_root",
        "review_local_work_root",
        "review_inbox_folder",
        "review_dedupe_mode",
        "review_no_recurse",
    ),
}

# 243: History shows every run, this many at a time (Show more adds the next page).
HISTORY_PAGE_SIZE = 200
# 243: the kind of run each New Review workflow is, as the library keeps it.
WIZARD_RUN_KINDS = {
    WORKFLOW_FULL_REVIEW: "full_review",
    WORKFLOW_TRANSCRIPT_ONLY: "transcript_only",
    WORKFLOW_CODEX_EVIDENCE: "ticket_evidence",
    WORKFLOW_ARCHIVE_CATALOG: "archive_catalog",
    WORKFLOW_REVIEW_NEW_VIDEOS: "inbox_process",
}

TRANSIENT_PROFILE_KEYS = {
    "input_kind",
    "input_path",
    "output_folder",
    "open_output_in_explorer",
    "default_input_folder",
    "repo_root",
    "script_path",
    "log_folder",
    "temp_folder",
    "review_inbox_exact_source_paths",
    # 224 (Wave B2b): the one Inbox folder its records in the library belong to; a profile never changes it.
    "review_inbox_folder",
    "cleanup_retention_days",
    "default_workflow",
    "default_profile",
    "startup_page",
    "restore_window_geometry",
    "theme",
    "window_geometry",
    "recent_output_folders",
    "recent_runs",
    "last_evidence_package",
    "dependency_python_path",
    "dependency_ffmpeg_path",
    "dependency_ffprobe_path",
    "dependency_ytdlp_path",
    "bundled_tools_question_answered",
    "whisper_model_download_approved",
    "evidence_audio_stream_index",
    "evidence_audio_stream_selection_confirmed",
    "evidence_audio_stream_selections_json",
    # 196: the per-track narration setting belongs to this operator's OBS layout, not to a profile.
    "evidence_track_roles",
    # 201: so do the words to spell right; one list, on Settings > General.
    "evidence_transcription_glossary_entries",
    # 125: which player opens a video, where VLC is, how loud the built-in
    # player is and where its window sits belong to this PC and this operator.
    # Applying a profile or changing workflow must never reset them.
    "video_player",
    "video_autoplay",
    "video_player_vlc_path",
    "review_player_geometry",
    "review_player_volume",
    "review_player_waveforms",
    # 114: applying a profile must never replace the never-use list or the
    # already-done map with whatever the profile happened to hold.
    *BUG_REPORT_RECORDING_LIST_KEYS,
    # 244: nor a stopped run, which Save profile as copied into custom profiles before.
    BUG_REPORT_STOPPED_RUN_KEY,
    # 150: the AI Video Editor's own settings stay out of workflow profiles.
    "race_video_output_folder",
    "race_video_budget",
    "race_video_claude_model",
    "race_video_codex_model",
    # 226: retired, and kept here so a value an older version saved never leaks into a profile.
    "race_video_voice_track",
    "race_video_game_track",
    "race_video_export_quality",
    "race_video_quick_whisper_model",
}

PROFILE_OPERATOR_DESCRIPTIONS = {
    "Archive Prep": "Prepare local recordings for searchable archive storage.",
    "Full Review + Evidence": "Create a complete review package and optional ticket-focused evidence.",
    "iRacing Long Explanation": "Use wider context for long spoken explanations in local recordings.",
    "iRacing Telemetry Detail": "Favor dense visual context around telemetry discussions.",
    "iRacing Ticket Evidence - Balanced": "Balanced ticket-focused review for local iRacing recordings.",
    "Review Media Inbox": "Use the bounded, resumable recording-inbox workflow.",
    "Review New Recordings": "Use the legacy recording-inbox preset.",
    "Ticket Evidence Run": "Find likely ticket moments in local recordings.",
    "Transcript Search": "Create or search transcripts without the full visual package.",
}


def _looks_like_url(value: str) -> bool:
    return re.match(r"(?i)^https?://", value.strip()) is not None


# What the two "Play this moment" buttons say about themselves (125). The
# default video app is named because it is the one player that cannot be told
# where to start; the right-click entries say the same thing.
PLAY_MOMENT_NOTHING_SELECTED = "Select an evidence item to play its moment."
PLAY_MOMENT_READY = (
    "Play the recording from this moment. Your computer's default video app, if that is your "
    "chosen player, can only start at the beginning."
)
PLAY_MOMENT_NO_RECORDING = "This package does not say which recording this moment is in."
# 134: an Evidence row that holds one recording's clips and small review copy, not a bug report.
CLIPS_ROW_PREFIX = "clips::"
CLIPS_ROW_TOOLTIP = "This row lists a recording's clips and small review copy. Select a bug report to use this."
# What a file row of the narration index is, and the recording a small review copy stands in for.
NARRATION_KIND_ROLE = Qt.ItemDataRole.UserRole + 1
NARRATION_RECORDING_ROLE = Qt.ItemDataRole.UserRole + 2

# A tool's own progress bar, such as Whisper's "  0%|          | 0/1372 [00:00<?, ?frames/s]":
# its numbers count audio frames, not recordings, so they never stand in for the queue.
_TOOL_PROGRESS_BAR = re.compile(r"^\s*\d{1,3}%\|")


def _parse_url_lines(value: str) -> tuple[list[str], list[str]]:
    urls: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for raw_line in str(value or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.fullmatch(r"(?i)https?://\S+", line) is None:
            invalid.append(line)
            continue
        key = line.casefold()
        if key not in seen:
            seen.add(key)
            urls.append(line)
    return urls, invalid


def _operator_error_text(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "Processing stopped without a specific error message."
    text = re.sub(r"(?i)(?:[a-z]:[\\/]|\\\\)[^\r\n]+", "<local path>", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text == "<local path>":
        return "Processing failed."
    return text


def _safe_stream_value(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _setting_range(key: str) -> tuple[float, float, float]:
    ranges = {
        "frame_interval_seconds": (0.1, 60.0, 0.1),
        "pre_context_seconds": (0, 7200, 1),
        "post_context_seconds": (0, 7200, 1),
        "narration_context_pre_seconds": (0, 14400, 1),
        "narration_context_post_seconds": (0, 14400, 1),
        "narration_pause_threshold_seconds": (0, 3600, 1),
        "evidence_frame_cadence_seconds": (0.1, 120.0, 0.1),
        "evidence_max_frames_per_candidate": (1, 10000, 1),
        "evidence_max_items": (1, 10000, 1),
        "evidence_audio_stream_index": (0, 128, 1),
        "preferred_narration_track_number": (0, 128, 1),
        "evidence_portable_zip_max_mb": (1, 102400, 1),
        "archive_max_thumbnails_per_video": (0, 1000, 1),
        "cleanup_retention_days": (0, 3650, 1),
    }
    return ranges.get(key, (-100000, 100000, 1))


def _make_setting_control(meta: SettingMetadata, parent: QWidget | None = None) -> QWidget:
    if meta.control_type == "bool":
        control = QCheckBox(parent)
    elif meta.control_type in {"choice", "workflow"}:
        control = WheelSafeComboBox(parent)
        if meta.control_type == "workflow":
            for workflow in WORKFLOWS:
                control.addItem(workflow.display_name, workflow.number)
        else:
            for value in meta.allowed_values:
                label = {
                    "PortableZip": "Portable agent ZIP",
                    "Both": "Local folder + portable ZIP",
                    "Local": "Local evidence folder",
                }.get(value, value or "Use configured default")
                control.addItem(label, value)
    elif meta.control_type == "int":
        control = WheelSafeSpinBox(parent)
        minimum, maximum, step = _setting_range(meta.key)
        control.setRange(int(minimum), int(maximum))
        control.setSingleStep(int(step))
    elif meta.control_type == "float":
        control = WheelSafeDoubleSpinBox(parent)
        minimum, maximum, step = _setting_range(meta.key)
        control.setRange(float(minimum), float(maximum))
        control.setSingleStep(float(step))
        control.setDecimals(2)
    elif meta.key in {"review_source_folders", "transcript_search_terms"}:
        control = QPlainTextEdit(parent)
        control.setMaximumHeight(76)
    else:
        control = QLineEdit(parent)
    control.setToolTip(meta.tooltip)
    return control


def _control_value(control: QWidget) -> Any:
    if isinstance(control, QCheckBox):
        return control.isChecked()
    if isinstance(control, QComboBox):
        data = control.currentData()
        return data if data is not None else control.currentText()
    if isinstance(control, WheelSafeSpinBox | WheelSafeDoubleSpinBox):
        return control.value()
    if isinstance(control, QPlainTextEdit):
        return control.toPlainText().strip()
    if isinstance(control, QLineEdit):
        return control.text().strip()
    return None


def _set_control_value(control: QWidget, value: Any) -> None:
    blocker = QSignalBlocker(control)
    if isinstance(control, QCheckBox):
        control.setChecked(bool(value))
    elif isinstance(control, QComboBox):
        index = control.findData(value)
        if index < 0:
            index = control.findText(str(value))
        if index >= 0:
            control.setCurrentIndex(index)
    elif isinstance(control, WheelSafeSpinBox):
        try:
            control.setValue(int(float(value)))
        except (TypeError, ValueError):
            pass
    elif isinstance(control, WheelSafeDoubleSpinBox):
        try:
            control.setValue(float(value))
        except (TypeError, ValueError):
            pass
    elif isinstance(control, QPlainTextEdit):
        control.setPlainText(str(value or ""))
    elif isinstance(control, QLineEdit):
        control.setText(str(value or ""))
    del blocker


def _connect_control(control: QWidget, callback: Callable[[], None]) -> None:
    invoke = lambda *_args: callback()
    if isinstance(control, QCheckBox):
        control.toggled.connect(invoke)
    elif isinstance(control, QComboBox):
        control.currentIndexChanged.connect(invoke)
    elif isinstance(control, WheelSafeSpinBox | WheelSafeDoubleSpinBox):
        control.valueChanged.connect(invoke)
    elif isinstance(control, QPlainTextEdit):
        control.textChanged.connect(invoke)
    elif isinstance(control, QLineEdit):
        control.textChanged.connect(invoke)


def _card() -> QFrame:
    frame = QFrame()
    frame.setProperty("card", True)
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    return frame


def _page_header(title: str, subtitle: str = "") -> tuple[QWidget, QVBoxLayout]:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(24, 20, 24, 20)
    layout.setSpacing(12)
    title_label = QLabel(title)
    title_label.setProperty("title", True)
    layout.addWidget(title_label)
    if subtitle:
        subtitle_label = QLabel(subtitle)
        subtitle_label.setWordWrap(True)
        subtitle_label.setProperty("muted", True)
        layout.addWidget(subtitle_label)
    return widget, layout



# Operator-facing label for every queue/row state on the Progress page.
PROGRESS_STATE_LABELS: dict[str, str] = {
    "pending": "Pending",
    "active": "Active",
    "completed": "Completed",
    "failed": "Failed",
    "skipped": "Skipped",
    "no_narration": "No narration found",
    "transcribed": "Transcribed, screenshots next",
    "cancelled": "Cancelled",
    "cancelling": "Cancelling",
    "waiting": "Waiting",
    "complete_with_warnings": "Complete with warnings",
    "completed_with_problems": "Completed with problems",
    "paused": "Paused",
}


class RunnerThread(QThread):
    log_line = Signal(str, str)
    finished_result = Signal(object)

    def __init__(
        self,
        command: CommandSpec,
        cwd: str | None,
        runner_factory: Callable[[], SubprocessRunner | FakeRunner],
    ) -> None:
        super().__init__()
        self.command = command
        self.cwd = cwd
        self.runner = runner_factory()

    def run(self) -> None:
        try:
            result = self.runner.run(self.command, self.log_line.emit, cwd=self.cwd)  # type: ignore[call-arg]
        except TypeError:
            result = self.runner.run(self.command, self.log_line.emit)
        self.finished_result.emit(result)

    def cancel(self) -> None:
        self.runner.cancel()


class ReviewInboxOperationThread(QThread):
    """Background final-results/finalization worker with operator-readable progress."""

    operation_ready = Signal(object)
    operation_failed = Signal(str)
    progress_ready = Signal(object)

    def __init__(
        self,
        payload: dict[str, Any],
        operation: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        super().__init__()
        self.payload = dict(payload)
        self.operation = operation

    def run(self) -> None:
        payload = dict(self.payload)
        payload["progress_callback"] = self.progress_ready.emit
        try:
            result = self.operation(payload)
        except Exception as exc:  # noqa: BLE001 - 224: a locked or damaged database must say so, not end silently
            self.operation_failed.emit(str(exc))
            return
        finally:
            # 224 (Wave B2b): this thread's own library connection; no other thread can close it.
            inbox_records.release()
        self.operation_ready.emit(result)


class AudioInspectionThread(QThread):
    inspection_started = Signal(int, int, int, str)
    inspection_ready = Signal(int, int, int, str, object)
    inspection_failed = Signal(int, int, int, str, str)
    batch_finished = Signal(int, bool)

    def __init__(
        self,
        generation: int,
        sources: list[Path],
        ffprobe_exe: str,
        ffmpeg_exe: str,
        temp_root: Path,
        voice_signature: tuple[float, ...] | None,
    ) -> None:
        super().__init__()
        self.generation = generation
        self.sources = sources
        self.ffprobe_exe = ffprobe_exe
        self.ffmpeg_exe = ffmpeg_exe
        self.temp_root = temp_root
        self.voice_signature = voice_signature

    def run(self) -> None:
        total = len(self.sources)
        for source_index, source in enumerate(self.sources, start=1):
            if self.isInterruptionRequested():
                break
            source_key = str(source.resolve())
            self.inspection_started.emit(
                self.generation, source_index, total, source.name
            )
            try:
                inspection = inspect_source(
                    self.ffprobe_exe,
                    self.ffmpeg_exe,
                    source,
                    self.temp_root,
                    voice_signature=self.voice_signature,
                    cancel_requested=self.isInterruptionRequested,
                )
            except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError) as exc:
                if not self.isInterruptionRequested():
                    self.inspection_failed.emit(
                        self.generation, source_index, total, source_key, str(exc)
                    )
                continue
            if self.isInterruptionRequested():
                break
            self.inspection_ready.emit(
                self.generation, source_index, total, source_key, inspection
            )
        self.batch_finished.emit(self.generation, self.isInterruptionRequested())

    def cancel(self) -> None:
        self.requestInterruption()


class DependencyCheckThread(QThread):
    check_ready = Signal(object)
    check_failed = Signal(str)

    def __init__(
        self,
        resources: RuntimeResources,
        selected_model: str,
        configured_python: str,
        configured_ffmpeg: str,
        configured_ffprobe: str,
        configured_ytdlp: str,
        configured_vlc: str = "",
        translation_needs_argos: bool = False,
        quick_model: str = "",
    ) -> None:
        super().__init__()
        self.quick_model = quick_model
        self.resources = resources
        self.selected_model = selected_model
        self.configured_python = configured_python
        self.configured_ffmpeg = configured_ffmpeg
        self.configured_ffprobe = configured_ffprobe
        self.configured_ytdlp = configured_ytdlp
        self.configured_vlc = configured_vlc
        self.translation_needs_argos = translation_needs_argos
        self._runner = StoppableRunner()

    @property
    def stopped(self) -> bool:
        return self._runner.stopped

    def cancel(self) -> None:
        # 193: ends the probe running now and every process it started; the check reports nothing.
        self._runner.stop()

    def run(self) -> None:
        try:
            result = run_dependency_preflight(
                self.resources,
                selected_model=self.selected_model,
                configured_python=self.configured_python,
                configured_ffmpeg=self.configured_ffmpeg,
                configured_ffprobe=self.configured_ffprobe,
                configured_ytdlp=self.configured_ytdlp,
                configured_vlc=self.configured_vlc,
                runner=self._runner,
                translation_needs_argos=self.translation_needs_argos,
                quick_model=self.quick_model,
            )
        except DependencyCheckStopped:
            return
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            if not self.stopped:
                self.check_failed.emit(str(exc))
            return
        if not self.stopped:
            self.check_ready.emit(result)


class ModelDownloadThread(QThread):
    """Installer plan, Stage 3: the Whisper model download the operator approved, and nothing else.

    It runs the helper's ``whisper-model-download`` in the Python that runs Whisper (ours, or one of yours kept
    under an exception), which writes each model to a partial file, checks it against the SHA-256 Whisper
    published and only then puts it in place. Progress comes from a small file the helper keeps up to date.
    Stopping (the Workbench closing) ends the helper; the partial file it leaves is removed at the next try."""

    progress_changed = Signal(str)
    download_finished = Signal(bool, str)

    def __init__(self, argv: list[str], request: Path, result: Path, progress: Path, models: list[str]) -> None:
        super().__init__()
        self.argv = list(argv)
        self.request, self.result, self.progress = request, result, progress
        self.models = list(models)
        self._stopped = threading.Event()
        self._process: subprocess.Popen[bytes] | None = None

    @property
    def stopped(self) -> bool:
        return self._stopped.is_set()

    def cancel(self) -> None:
        self._stopped.set()
        process = self._process
        if process is not None:
            _end_process_tree(process)  # type: ignore[arg-type]

    def _progress_text(self) -> str:
        try:
            data = json.loads(self.progress.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        done, total = int(data.get("done") or 0), int(data.get("total") or 0)
        name = str(data.get("model") or "")
        amount = f"{done / 1_000_000:,.0f} MB of {total / 1_000_000:,.0f} MB" if total else f"{done / 1_000_000:,.0f} MB"
        return f"{name}: {amount}" + (f" ({100 * done // total}%)" if total else "")

    def run(self) -> None:
        try:
            self.request.parent.mkdir(parents=True, exist_ok=True)
            write_json_file(self.request, {"payload": {"models": self.models, "progress_file": str(self.progress)}})
            self._process = subprocess.Popen(self.argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL,
                                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            self.download_finished.emit(False, f"The download could not start: {exc}")
            return
        shown = ""
        while self._process.poll() is None:
            if self.stopped:
                _end_process_tree(self._process)  # type: ignore[arg-type]
                return
            text = self._progress_text()
            if text and text != shown:
                shown = text
                self.progress_changed.emit(text)
            time.sleep(0.25)
        if self.stopped:
            return
        try:
            outcome = json.loads(self.result.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            outcome = {"ok": False, "error": "The download ended without saying how it went."}
        if outcome.get("ok"):
            names = ", ".join(str(item.get("name")) for item in (outcome.get("data") or {}).get("models") or [])
            self.download_finished.emit(True, f"Downloaded and checked: {names or ', '.join(self.models)}.")
        else:
            self.download_finished.emit(False, str(outcome.get("error") or "The download did not finish."))


class AdvancedSettingsDialog(QDialog):
    def __init__(
        self,
        settings: dict[str, Any],
        profile_values: dict[str, Any],
        app_defaults: dict[str, Any],
        workflow: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Advanced review settings")
        self.resize(760, 640)
        self.settings = settings
        self.profile_values = profile_values
        self.app_defaults = app_defaults
        self.controls: dict[str, QWidget] = {}
        rows: dict[str, QHBoxLayout] = {}
        root = QVBoxLayout(self)
        notice = QLabel(
            "Advanced values change processing cost, package size, or processing behavior. "
            "The current profile remains available as a reset point."
        )
        notice.setWordWrap(True)
        notice.setProperty("muted", True)
        root.addWidget(notice)
        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        categories: dict[str, list[SettingMetadata]] = {}
        # 224 (Wave B2b): the old ledger's path stays saved for an older build, and is never offered to change.
        excluded = TRANSIENT_PROFILE_KEYS | set(BASIC_WORKFLOW_SETTINGS.get(workflow, ())) | {"review_ledger_path"}
        for meta in SETTING_METADATA:
            if workflow not in meta.workflows or meta.key in excluded:
                continue
            categories.setdefault(meta.category, []).append(meta)
        for category, items in categories.items():
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            panel = QWidget()
            form = QFormLayout(panel)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            for meta in items:
                control = _make_setting_control(meta, panel)
                _set_control_value(control, settings.get(meta.key, meta.default))
                self.controls[meta.key] = control
                row = QWidget()
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.addWidget(control, 1)
                profile_reset = QToolButton()
                profile_reset.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
                profile_reset.setToolTip("Reset to profile value")
                profile_reset.clicked.connect(
                    lambda checked=False, key=meta.key: self._reset_control(
                        key, self.profile_values.get(key, METADATA_BY_KEY[key].default)
                    )
                )
                default_reset = QToolButton()
                default_reset.setText("D")
                default_reset.setToolTip("Reset to application default")
                default_reset.clicked.connect(
                    lambda checked=False, key=meta.key: self._reset_control(
                        key, self.app_defaults.get(key, METADATA_BY_KEY[key].default)
                    )
                )
                row_layout.addWidget(profile_reset)
                row_layout.addWidget(default_reset)
                rows[meta.key] = row_layout
                form.addRow(meta.display_label, row)
            scroll.setWidget(panel)
            tabs.addTab(scroll, category)
        # 214: Package any video for AI's track choice says whether it follows the main
        # narration-track setting (Settings > General) or overrides it.
        self.track_choice_state: QLabel | None = None
        if "transcript_audio_mode" in self.controls:
            self.track_choice_state = QLabel()
            self.track_choice_state.setProperty("muted", True)
            rows["transcript_audio_mode"].insertWidget(1, self.track_choice_state)
            for key in ("transcript_audio_mode", "transcript_audio_track_ordinal"):
                control = self.controls.get(key)
                if isinstance(control, QComboBox):
                    control.currentIndexChanged.connect(self._refresh_track_choice_state)
                elif isinstance(control, WheelSafeSpinBox):
                    control.valueChanged.connect(self._refresh_track_choice_state)
            self._refresh_track_choice_state()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _reset_control(self, key: str, value: Any) -> None:
        # The value is set with signals blocked, so every label that depends on a control
        # is refreshed here, once, after either reset button (220).
        _set_control_value(self.controls[key], value)
        self._refresh_dependent_labels()

    def _refresh_dependent_labels(self) -> None:
        self._refresh_track_choice_state()

    def _refresh_track_choice_state(self, *_args: object) -> None:
        if self.track_choice_state is None:
            return
        number = self.controls.get("transcript_audio_track_ordinal")
        self.track_choice_state.setText(track_choice_state(
            _control_value(self.controls["transcript_audio_mode"]),
            _control_value(number) if number is not None else 0,
        ))

    def values(self) -> dict[str, Any]:
        return {key: _control_value(control) for key, control in self.controls.items()}


class WorkbenchWindow(QMainWindow):
    # 220: one app-wide notice that a run started or ended, or the tool check started or
    # stopped. Every page whose buttons depend on either listens, so none is left stale.
    run_availability_changed = Signal()
    # 237: the job on the shared runner changed (started, moved on, finished); every page's job
    # banner and the rail's Queue / Progress badge follow it through job_snapshot().
    job_changed = Signal()

    def __init__(
        self,
        *,
        settings_path: Path | None = None,
        profiles_dir: Path | None = None,
        runner_factory: Callable[[], SubprocessRunner | FakeRunner] = SubprocessRunner,
        resources: RuntimeResources | None = None,
        # 224, F13: the only Inbox work the window runs itself is the reconcile; scanning, the imports and
        # finalization all run inside Process, through the PowerShell host.
        review_inbox_reconciler: Callable[[dict[str, Any]], dict[str, Any]] = review_orchestration.reconcile_from_request,
        review_inbox_exact_source_paths: list[str] | None = None,
        levels_runner_factory: Callable[[], Any] | None = None,
        library_root: Path | None = None,
    ) -> None:
        super().__init__()
        self.settings_path = settings_path or default_settings_path()
        self._resources_injected = resources is not None
        self.resources = resources if resources is not None else discover_runtime_resources()
        self.repo_root_path = str(self.resources.app_root)
        # 242, 243: the library's front door, opened before the settings are read. Every run is kept
        # there. When it cannot be opened (a newer build moved it on, a damaged file), the run history
        # stays in the settings for this session, as before, and the reason is logged.
        self.records: Records | None = None
        self.records_problem = ""
        # 275: why the library could not be opened, said on screen once (library_notice) and by every feature
        # that needs it (library_refusal). Any error counts: the Workbench still starts.
        self.library_problem = ""
        self._library_too_new = False
        self._library_hint = ""
        try:
            self.records = Records(library_root)
        except Exception as exc:  # noqa: BLE001 - 275: a library that cannot be opened never stops the start
            # 224 (Wave B2a, 5d): said in plain words on screen; the raw text stays in records_problem, for the log.
            self.records_problem = str(exc) or type(exc).__name__
            self.library_problem, self._library_hint = recording_records.plain_problem(exc, library_root)
            self._library_too_new = isinstance(exc, recording_records.LibraryTooNew)
        self._had_records = self.records is not None
        # 243, 244: the run history, Find my bug reports' two lists and its stopped run move from
        # settings.json into the library once, backed up first, before the settings are read; so do the
        # stray copies a custom profile holds. A move that could not happen leaves the files as they were,
        # and this session goes on reading them there.
        self.records_move: dict[str, Any] = {"status": "no library"}
        if self.records is not None:
            try:
                self.records_move = import_legacy_settings(self.records, self.settings_path,
                                                           profiles_dir or default_profiles_dir())
            except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
                self.records_move = {"status": "failed", "message": str(exc)}
        self.app_settings = load_settings(
            self.settings_path, repo_root=self.repo_root_path
        )
        # This qualification boundary is accepted only from the current
        # launch.  Ignore any stale or hand-authored settings-file value.
        self.app_settings.pop("review_inbox_exact_source_paths", None)
        if self._history_moved():
            # Moved, or moved with the cleaning left for the next start: never written back from here. That
            # is the run history (243), Find my bug reports' two lists and its stopped run (244).
            for key in recording_records.MOVED_SETTINGS_KEYS:
                self.app_settings.pop(key, None)
        if self.records is not None:
            # 242: the folders generated products live under, so a run's folder is kept relative to one.
            try:
                self.records.register_root("library", str(self.records.root))
                self.records.register_root("output", str(self.app_settings.get("output_folder") or ""))
            except (OSError, sqlite3.Error, ValueError) as exc:
                self.records_problem = str(exc)
        # 224 (Wave B2b): Review Media Inbox's records move from its ledger into the library once, before any page
        # or Inbox action exists; every later start finishes or undoes a move a crash cut off, or does nothing.
        # Until the move is complete the Inbox opens nothing, and its page says why (inbox_move_result).
        self.inbox_move_result: dict[str, Any] = {"status": "no library"}
        if self.records is not None:
            try:
                self.inbox_move_result = inbox_move.move_ledger(
                    self.records, self.app_settings, settings_path=self.settings_path,
                    profiles_dir=profiles_dir or default_profiles_dir(), version=__version__,
                    save_folder=self._save_inbox_folder).as_dict()
            except Exception as exc:  # noqa: BLE001 - the receipt says where it got to; the next start goes on from there
                self.inbox_move_result = {"status": "waiting", "message": inbox_records.MOVE_UNFINISHED,
                                          "error": str(exc) or type(exc).__name__}
        # 243: a run still marked running whose Workbench is gone (a crash, a close mid-run) is
        # Interrupted; a run another open Workbench is running is left alone.
        if self.records is not None:
            try:
                self.records.sweep_interrupted()
            except (OSError, sqlite3.Error, ValueError) as exc:
                self.records_problem = str(exc)
        self._last_external_run_id = ""
        self._last_external_run_entry: dict[str, Any] | None = None
        if not self._resources_injected:
            self.resources = discover_runtime_resources(self.app_settings)
            self.repo_root_path = str(self.resources.app_root)
        self.build_identity = resolve_build_identity(
            packaged=self.resources.packaged,
            repo_root=self.resources.app_root,
        )
        self.profile_manager = ProfileManager(profiles_dir=profiles_dir, repo_root=self.repo_root_path)
        self.profile_manager.ensure_starter_profiles()
        self.run_settings = deepcopy(self.app_settings)
        self.review_inbox_launch_exact_source_paths = list(
            dict.fromkeys(
                str(value).strip()
                for value in review_inbox_exact_source_paths or []
                if str(value).strip()
            )
        )
        if self.review_inbox_launch_exact_source_paths:
            self.run_settings["review_inbox_exact_source_paths"] = list(
                self.review_inbox_launch_exact_source_paths
            )
        self.runner_factory = runner_factory
        self.review_inbox_reconciler = review_inbox_reconciler
        self.current_workflow = normalize_workflow(self.app_settings.get("default_workflow", DEFAULT_WORKFLOW))
        self.current_profile = ""
        self.current_profile_metadata: LoadedProfile | None = None
        self.profile_values: dict[str, Any] = {}
        self.profile_baseline: dict[str, Any] = {}
        self.current_package: EvidencePackage | None = None
        self.current_item: EvidenceCandidate | None = None
        self.current_session_mention: SessionMention | None = None
        self.runner_thread: RunnerThread | None = None
        # A run started by another page (Find my bug reports) that still uses
        # the shared runner, Progress page, run log and History (103).
        self.external_run: dict[str, Any] | None = None
        # 214: the run going now as it was when it started: its own settings, its workflow,
        # whether Review Media Inbox started it, and the folder it writes to. What a run reports
        # (results location, Open output, History, the Inbox page) comes from here, never from
        # what a page shows now: New Review and the Inbox share run_settings and current_workflow.
        self.active_run: dict[str, Any] | None = None
        # The same for the run that finished last, so "Open output" opens that run's folder.
        self.last_run: dict[str, Any] | None = None
        # 114/115: skip and pause requests for the running bug-report run.
        self.run_control: RunControl | None = None
        # 214: the control file start_job made for this run, removed when it ends.
        self._own_run_control_path: Path | None = None
        self.review_inbox_reconcile_thread: ReviewInboxOperationThread | None = None
        self.review_inbox_scan_result: dict[str, Any] | None = None
        self.review_inbox_active_batch: dict[str, Any] | None = None
        self.review_inbox_restored_sources: list[dict[str, Any]] = []
        self.review_inbox_final_result: dict[str, Any] | None = None
        self.review_inbox_prepare_full_acknowledged = False
        self.review_inbox_stop_path: Path | None = None
        self.review_inbox_active_action = ""
        self.review_inbox_process_result: dict[str, Any] | None = None
        self.review_inbox_status_contract: dict[str, Any] = {
            "operator_status": "Done",
            "queue_counts": {
                "ready_for_codex_review": 0,
                "waiting_on_codex": 0,
                "additional_local_evidence": 0,
                "manual_review": 0,
                "done": 0,
            },
            "run_state": {},
        }
        self.review_inbox_decision_tokens: set[str] = set()
        self.review_inbox_dialog_active = False
        self.review_inbox_process_after_dependency_check = False
        self.standard_review_return_after_dependency_check = False
        self.standard_review_dependency_return_step = 4
        self.review_inbox_last_standard_workflow = (
            self.current_workflow
            if self.current_workflow != WORKFLOW_REVIEW_NEW_VIDEOS
            else WORKFLOW_CODEX_EVIDENCE
        )
        self.dependency_check_thread: DependencyCheckThread | None = None
        # Installer plan, Stage 3: the Whisper model download the operator approved, while it runs.
        self.model_download_thread: ModelDownloadThread | None = None
        self.run_started_monotonic = 0.0
        self.review_inbox_diagnostics: list[str] = []
        self.run_log_lines: list[str] = []
        self.run_log_path = new_workbench_log_path(
            Path(str(self.app_settings.get("log_folder") or default_log_folder()))
        )
        self.audio_inspections: dict[str, SourceAudioInspection] = {}
        self.audio_inspection_failures: dict[str, str] = {}
        self.audio_expected_sources: list[str] = []
        self.active_audio_source = ""
        self.audio_inspection_generation = 0
        self.audio_inspection_thread: AudioInspectionThread | None = None
        # 136: the recording and track the wizard's Preview track last asked the shared player for.
        self._preview_request: tuple[str, int] | None = None
        self._preview_window: Any | None = None
        private_settings_root = self.settings_path.parent
        self.layout_confirmation_store = LayoutConfirmationStore(
            private_settings_root / "narration-layouts.json"
        )
        self.voice_enrollment_store = VoiceEnrollmentStore(
            private_settings_root / "voice-enrollment.json"
        )
        set_recordings_folders(watched_folders({**self.app_settings}))
        self.last_progress_event_monotonic = 0.0
        self.last_progress_phase = ""
        self.structured_progress_seen = False
        self.progress_queue_items: list[str] = []
        self.progress_item_states: dict[str, str] = {}
        self.progress_active_item = ""
        self.progress_source_queue_known = False
        self.progress_warning_count = 0
        self._loading = False
        self._closing_after_smoke = False
        self.run_setting_controls: dict[str, QWidget] = {}
        self.nav_buttons: dict[str, QPushButton] = {}
        self.pages: dict[str, QWidget] = {}
        # 237: the job on the shared runner, as the job banners show it, and the parts of it the
        # Progress page does not keep.
        self._job: JobInfo | None = None
        self._job_number = 0
        self._job_eta_seconds: float | None = None
        # 125: every page hands its videos to this one opener, so it has to
        # exist before the pages are built (Find my bug reports attaches to it
        # in its own constructor). Making it opens no window and no player.
        self.video_opener = VideoOpener(self)
        # 125, 135 (Wave 8): the player's waveforms, measured one recording at a time in the
        # background. Off when a test hands the window its own resources, unless it hands a runner too.
        self.levels_service = LevelsService(
            resources=lambda: self.resources,
            settings=lambda: self.app_settings,
            # 264: the speech facts of what is opened and of what a run just used; the job reads them with the waveform.
            facts_lookup=lambda path: speech_facts.jump_points(path, track_roles=self.app_settings.get(TRACK_ROLES_SETTING_KEY)),
            facts_request=lambda: {"track_roles": str(self.app_settings.get(TRACK_ROLES_SETTING_KEY) or "")},
            is_idle=lambda: self.runner_thread is None and self.audio_inspection_thread is None,
            runner_factory=levels_runner_factory or (None if self._resources_injected else SubprocessRunner),
            availability_changed=self.run_availability_changed,
            log=lambda text: self._write_workbench_log(text),
            parent=self,
            # 225: the readiness check decides which Python and FFmpeg the helpers use.
            tools_ready=lambda: getattr(self, "dependency_check_thread", None) is None,
        )

        self.setWindowTitle("Video Mangler Workbench")
        self.setMinimumSize(980, 680)
        self.resize(1320, 880)
        if self.resources.icon_path:
            self.setWindowIcon(QIcon(str(self.resources.icon_path)))
        # 237: the saved text size is restored before anything is built, so every page starts at it.
        apply_theme(QApplication.instance(), str(self.app_settings.get("theme") or "Dark"),
                    normalize_text_size(self.app_settings.get(TEXT_SIZE_KEY)))

        self._build_shell()
        self._build_pages()
        self._build_shortcuts()
        self._apply_startup_profile()
        self._restore_window_geometry()
        self.refresh_dependency_status()
        self.refresh_home()
        self.refresh_wizard()
        self.refresh_history()
        self.run_availability_changed.connect(self._refresh_review_inbox_dashboard)
        self.run_availability_changed.connect(self.refresh_review_summary)
        self._restore_review_inbox_pending_batch()
        self.navigate(str(self.app_settings.get("startup_page") or "Home"))
        self._write_workbench_log("Workbench started.")
        if self.records is None:
            self._write_workbench_log(f"The library could not be opened, so runs are kept in the settings for "
                                      f"now: {self.records_problem}")
            self._show_library_notice()
        elif self.records_problem:
            # 275, F12: the library is open and runs go into it; only a later start-up step did not finish.
            self._write_workbench_log(f"The library is open, but a start-up step did not finish: {self.records_problem}")
        move = self.records_move
        if move.get("status") == "refused":
            # 243: settings.json could not be read. Nothing was moved, a copy of it is kept, and the
            # Workbench says so once, without stopping.
            self.records_notice = warn(self, "Your settings could not be read",
                                       "settings.json could not be read, so the Workbench started with its defaults "
                                       f"and moved nothing. A copy of the file is in {move.get('backup_folder')}.",
                                       wait=False)
        if move.get("status") not in {"nothing", "no library"}:
            counts = (move.get("counts") or {}).get("recent_runs") or {}
            self._write_workbench_log(
                f"Run history moved out of settings.json: {move.get('status')}; read {counts.get('read', 0)}, "
                f"added {counts.get('added', 0)}, already there {counts.get('already', 0)}."
                + (f" {move.get('message')}" if move.get("message") else ""))
            # 244: counts only, never a path (the lists are personal).
            moved = move.get("counts") or {}
            never = moved.get(recording_records.LEGACY_NEVER_USE_KEY) or {}
            done = moved.get(recording_records.LEGACY_DONE_KEY) or {}
            stopped = moved.get(recording_records.LEGACY_STOPPED_RUN_KEY) or {}
            profiles = moved.get("profiles") or {}
            self._write_workbench_log(
                f"Find my bug reports' lists moved out of settings.json: {move.get('status')}; never-use read "
                f"{never.get('read', 0)}, added {never.get('added', 0)}, already there {never.get('already', 0)}; "
                f"done read {done.get('read', 0)}, added {done.get('added', 0)} ({done.get('tied_to_a_recording', 0)} "
                f"tied to a recording, {done.get('old_list', 0)} kept as the old list), already there "
                f"{done.get('already', 0)}; stopped run read {stopped.get('read', 0)}, added {stopped.get('added', 0)}; "
                f"custom profiles cleaned {profiles.get('cleaned', 0)} of {profiles.get('with_strays', 0)}.")
        elif (move.get("counts") or {}).get("profiles"):
            # 244: settings.json had nothing left to move; only a custom profile still held a stray copy.
            profiles = move["counts"]["profiles"]
            self._write_workbench_log(
                f"Stray copies of Find my bug reports' lists taken out of custom profiles: cleaned "
                f"{profiles.get('cleaned', 0)} of {profiles.get('with_strays', 0)}.")
        self._log_inbox_move()

        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.setInterval(1000)
        self.elapsed_timer.timeout.connect(self._refresh_elapsed)
        if not self._resources_injected:
            QTimer.singleShot(0, self.start_dependency_check)
    # Shell and navigation

    def _build_shell(self) -> None:
        shell = QWidget()
        shell.setObjectName("appShell")
        root = QHBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        nav = QFrame()
        nav.setObjectName("navRail")
        self.nav_rail = nav
        ui_theme.keep_scaled(self, "_fit_nav_width", 200)
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(10, 14, 10, 12)
        nav_layout.setSpacing(1)
        brand = QLabel("Video Mangler")
        brand.setObjectName("navBrand")
        brand.setContentsMargins(10, 0, 4, 6)
        nav_layout.addWidget(brand)
        group = QButtonGroup(self)
        group.setExclusive(True)

        # 237: the groups scroll inside the rail if a large text size makes them taller than the
        # window; Settings, Help and the footer stay at the bottom.
        groups_panel = QWidget()
        groups_panel.setObjectName("navGroups")
        groups_layout = QVBoxLayout(groups_panel)
        groups_layout.setContentsMargins(0, 0, 0, 0)
        groups_layout.setSpacing(0)
        groups_scroll = QScrollArea()
        groups_scroll.setObjectName("navGroupsScroll")
        groups_scroll.setWidgetResizable(True)
        groups_scroll.setFrameShape(QFrame.Shape.NoFrame)
        groups_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        groups_scroll.setWidget(groups_panel)
        nav_layout.addWidget(groups_scroll, 1)

        def add_button(page_name: str, target: QVBoxLayout) -> None:
            button = QPushButton(NAV_LABELS[page_name])
            button.setObjectName("navButton")
            button.setCheckable(True)
            # 237: a click does not leave the focus ring on the rail; Tab still reaches every button.
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            button.setAccessibleName(page_name)
            button.setToolTip(page_name)
            button.clicked.connect(lambda checked=False, name=page_name: self.navigate(name))
            group.addButton(button)
            target.addWidget(button)
            button.setVisible(page_name not in HIDDEN_NAV_PAGES)
            self.nav_buttons[page_name] = button

        self.nav_group_labels: dict[str, QLabel] = {}
        for group_name, names in NAV_GROUPS:
            heading = QLabel(group_name.upper())
            heading.setProperty("navGroup", True)
            heading.setAccessibleName(f"{group_name} pages")
            groups_layout.addWidget(heading)
            self.nav_group_labels[group_name] = heading
            for page_name in names:
                add_button(page_name, groups_layout)
        self.nav_buttons[AI_VIDEO_EDITOR_PAGE].setToolTip("AI Video Editor")
        # 237: how many jobs are running or queued, on the Queue / Progress button; none when idle.
        progress_button = self.nav_buttons["Queue / Progress"]
        badge_row = QHBoxLayout(progress_button)
        badge_row.setContentsMargins(0, 0, 8, 0)
        badge_row.addStretch(1)
        self.progress_nav_badge = QLabel("")
        self.progress_nav_badge.setObjectName("navBadge")
        self.progress_nav_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_nav_badge.setVisible(False)
        badge_row.addWidget(self.progress_nav_badge)
        groups_layout.addStretch(1)
        for page_name in NAV_BOTTOM:
            add_button(page_name, nav_layout)
        privacy = QLabel("Evidence stays local\nuntil you approve sharing.")
        privacy.setObjectName("navFooter")
        privacy.setWordWrap(True)
        privacy.setContentsMargins(10, 8, 6, 2)
        nav_layout.addWidget(privacy)
        self.version_build_label = QLabel(self._visible_build_identity_text())
        self.version_build_label.setObjectName("versionBuildLabel")
        self.version_build_label.setWordWrap(True)
        self.version_build_label.setContentsMargins(10, 4, 6, 0)
        nav_layout.addWidget(self.version_build_label)
        ui_theme.keep_scaled(self, "_fit_nav_rows", 0)
        # 237: the rail's own line icons, redrawn when the theme or the text size changes.
        ui_theme.keep_scaled(self, "_draw_nav_icons", 0)
        self.page_stack = PageStack()
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self.page_stack, 1)
        # 188: the start-up notice for a missing tool floats over the top of every page, so no
        # page loses height; it is hidden unless the first readiness check of this launch finds
        # a required tool missing.
        self.missing_tools_notice = MissingToolsNotice(
            self.open_tool_download_page, self.open_dependency_setup, content
        )
        root.addWidget(nav)
        root.addWidget(content, 1)
        self.setCentralWidget(shell)
        # 237: the window opens with no control in focus, so no focus ring shows until Tab is pressed.
        shell.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        shell.setFocus(Qt.FocusReason.OtherFocusReason)

    def _build_pages(self) -> None:
        builders = {
            "Home": self._build_home_page,
            BUG_REPORTS_PAGE: self._build_bug_reports_page,
            "New Review": self._build_new_review_page,
            RAW_BIN_PAGE: self._build_raw_bin_page,
            "Review Media Inbox": self._build_review_inbox_page,
            "Queue / Progress": self._build_progress_page,
            "Evidence": self._build_evidence_page,
            "Session Review": self._build_session_page,
            "Prompt Drafts": self._build_prompts_page,
            "History": self._build_history_page,
            AI_VIDEO_EDITOR_PAGE: self._build_ai_video_editor_page,
            "Settings": self._build_settings_page,
            "Help": self._build_help_page,
        }
        for name in PAGE_NAMES:
            page = builders[name]()
            self.pages[name] = page
            self.page_stack.addWidget(page)
        # 237: every table's selected row has the accent bar, and rows are at least 32 px; every form
        # keeps a clear gap between its labels and fields.
        polish_views(self)
        polish_forms(self)
        self.job_changed.connect(self._refresh_progress_nav_badge)
        self.run_availability_changed.connect(self._refresh_progress_nav_badge)

    def _build_bug_reports_page(self) -> QWidget:
        self.bug_reports_page = BugReportsPage(self)
        return self.bug_reports_page

    def _build_ai_video_editor_page(self) -> QWidget:
        self.ai_video_editor_page = AiVideoEditorPage(self)
        return self.ai_video_editor_page

    def _build_raw_bin_page(self) -> QWidget:
        self.raw_bin_page = RawBinPage(self)
        return self.raw_bin_page

    def _build_shortcuts(self) -> None:
        new_review = QAction(self)
        new_review.setShortcut(QKeySequence("Ctrl+N"))
        new_review.triggered.connect(lambda: self.navigate("New Review"))
        self.addAction(new_review)
        open_evidence = QAction(self)
        open_evidence.setShortcut(QKeySequence("Ctrl+O"))
        open_evidence.triggered.connect(self.choose_evidence_package)
        self.addAction(open_evidence)
        # 237: Ctrl+Plus, Ctrl+Minus and Ctrl+0 change the text size on every page and in the player.
        self.text_size_actions: dict[int, QAction] = {}
        for step, keys in (
            (1, (QKeySequence("Ctrl++"), QKeySequence("Ctrl+="), QKeySequence(QKeySequence.StandardKey.ZoomIn))),
            (-1, (QKeySequence("Ctrl+-"), QKeySequence(QKeySequence.StandardKey.ZoomOut))),
            (0, (QKeySequence("Ctrl+0"),)),
        ):
            action = QAction(self)
            action.setShortcuts(list(dict.fromkeys(key for key in keys if not key.isEmpty())))
            action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            action.triggered.connect(lambda _checked=False, s=step: self.step_text_size(s))
            self.addAction(action)
            self.text_size_actions[step] = action

    # Text size (237) ------------------------------------------------------

    def _fit_nav_rows(self, _unused: int = 0) -> None:
        """237: rail rows as tall as their words plus a little room, the room shrinking as the text grows,
        so every page of the rail fits an 800 px tall window at 150%. The heights are in the stylesheet
        too (theme.nav_row_heights), so a text size changed while the app runs keeps them."""

        button_height, label_height = ui_theme.nav_row_heights()
        for button in self.nav_buttons.values():
            button.setFixedHeight(button_height)
        for label in self.nav_group_labels.values():
            label.setFixedHeight(label_height)

    def _draw_nav_icons(self, _unused: int = 0) -> None:
        """237: one set of line icons for the rail: the label colour, the accent on the chosen page,
        a little larger than the words beside them."""

        body = QFont(ui_theme.FONT_FAMILY)
        body.setPointSizeF(ui_theme.point_size("body"))
        size = int(round(QFontMetrics(body).height() * 0.9))
        normal, chosen = ui_theme.token("text_soft"), ui_theme.token("link")
        for page_name, button in self.nav_buttons.items():
            button.setIcon(line_icon(NAV_ICONS[page_name], normal, chosen, size))
            button.setIconSize(QSize(size, size))

    def _fit_nav_width(self, scaled: int) -> None:
        # The rail's words are short, so it grows less than the text: 200 px at 100%, 240 px at 150%,
        # which leaves the pages their width.
        self.nav_rail.setFixedWidth(int(200 + (scaled - 200) * 0.4))

    def text_size(self) -> int:
        return normalize_text_size(self.app_settings.get(TEXT_SIZE_KEY))

    def step_text_size(self, step: int) -> None:
        """One size larger (1), smaller (-1), or back to 100% (0)."""

        self.set_text_size(100 if step == 0 else step_text_size(self.text_size(), step))

    def set_text_size(self, size: Any) -> None:
        """Apply a text size to the whole app now and remember it for the next start."""

        size = normalize_text_size(size)
        changed = size != self.text_size() or abs(ui_theme.text_scale() * 100 - size) > 0.5
        self.app_settings[TEXT_SIZE_KEY] = size
        if hasattr(self, "settings_text_size"):
            self.settings_text_size.set_value(size)
        if changed:
            apply_theme(QApplication.instance(), str(self.app_settings.get("theme") or "Dark"), size)
        self.save_app_settings()
        if hasattr(self, "settings_text_size_feedback"):
            self.settings_text_size_feedback.done(f"Text size {size}%. Saved.")

    # Jobs on the shared runner (237) ---------------------------------------

    def job_snapshot(self) -> JobInfo | None:
        """The job going now, or the one that finished last, as the job banners show it."""

        return self._job

    def make_job_banner(self, origin: str) -> JobBanner:
        """A job banner for a page: it shows the jobs that page started."""

        banner = JobBanner()
        banner.follow(self.job_changed, self.job_snapshot, origin, self.open_job)
        return banner

    def open_job(self, token: str) -> None:
        """Open Queue / Progress on this job: its current recording is selected."""

        self.navigate("Queue / Progress")
        if self._job is None or self._job.token != token:
            return
        items = self.progress_queue_items
        if not items:
            return
        # The recording being worked on; else the first not finished yet; else the first.
        unfinished = [item for item in items if self.progress_item_states.get(item) not in TERMINAL_PROGRESS_ITEM_STATES]
        target = self.progress_active_item if self.progress_active_item in items else (unfinished or items)[0]
        row = items.index(target)
        self.progress_queue_table.selectRow(row)
        self.progress_queue_table.scrollToItem(self.progress_queue_table.item(row, 0))

    def _job_percent(self) -> int | None:
        """The job's percent for its banner; None while nothing is measured yet (224, Decision 6), so the banner
        shows the step's words instead of a frozen "0%"."""

        overall, stage = self.overall_progress_bar, self.progress_bar
        stage_fraction = stage.value() / stage.maximum() if stage.maximum() > 0 else None
        if overall.maximum() > 0:
            if stage_fraction is None and overall.value() <= 0:
                return None
            fraction = overall.value() / overall.maximum()
            if stage_fraction is not None and overall.value() < overall.maximum():
                fraction += stage_fraction / overall.maximum()
            return max(0, min(100, int(fraction * 100)))
        return None if stage_fraction is None else max(0, min(100, int(stage_fraction * 100)))

    @staticmethod
    def _job_state_for(progress_state: str) -> str:
        """The job state for a Progress page state: still going, or how it finished."""

        if progress_state in {"active", "waiting", "paused", "cancelling", "cancelled", "completed", "failed"}:
            return progress_state
        if progress_state in {"complete_with_warnings", "completed_with_problems"}:
            return "attention"
        return "active"

    def _job_update(self, state: str | None = None, detail: str | None = None) -> None:
        job = self._job
        if job is None:
            return
        state = job.state if state is None else state
        running = state in {"active", "waiting", "paused", "cancelling"}
        self._job = replace(
            job,
            state=state,
            detail=job.detail if detail is None else detail,
            percent=self._job_percent() if running else None,
            time_left=time_left_text(self._job_eta_seconds) if running else "",
        )
        self.job_changed.emit()

    def _refresh_progress_nav_badge(self) -> None:
        if not hasattr(self, "progress_nav_badge"):
            return
        # One runner: a job running is one job; nothing else waits in a queue of jobs.
        count = 1 if self.runner_thread is not None else 0
        self.progress_nav_badge.setText(str(count) if count else "")
        self.progress_nav_badge.setVisible(bool(count))
        self.progress_nav_badge.setAccessibleName(f"{count} job running" if count else "")
        self.nav_buttons["Queue / Progress"].setToolTip(
            "Queue / Progress" if not count else f"Queue / Progress: {count} job running")

    def navigate(self, page_name: str) -> None:
        if page_name not in self.pages:
            page_name = "Home"
        if (
            page_name == "New Review"
            and self.current_workflow == WORKFLOW_REVIEW_NEW_VIDEOS
        ):
            self.set_current_workflow(self.review_inbox_last_standard_workflow)
        self.page_stack.setCurrentWidget(self.pages[page_name])
        self.nav_buttons[page_name].setChecked(True)
        if page_name == "Prompt Drafts":
            self.refresh_prompt_previews()
        elif page_name == "Session Review":
            self.refresh_session_review()
        elif page_name == "Review Media Inbox":
            self._refresh_review_inbox_dashboard()
            self.start_review_inbox_reconcile()
        elif page_name == RAW_BIN_PAGE:
            # Reads the library only, never a recording: instant however large the drive.
            self.raw_bin_page.refresh()

    # Home

    def _build_home_page(self) -> QWidget:
        page, layout = _page_header(
            "Media review workbench",
            "Choose a review task. Video Mangler processes the selected media locally on this computer.",
        )
        self.home_build_identity = QLabel(self.version_build_label.text())
        self.home_build_identity.setProperty("small", True)
        layout.addWidget(self.home_build_identity, alignment=Qt.AlignmentFlag.AlignRight)
        hero = _card()
        hero.setObjectName("bugReportsHero")
        hero.setProperty("selectedWorkflow", True)
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(20, 18, 20, 18)
        hero_text = QVBoxLayout()
        hero_title = QLabel("Find my bug reports")
        hero_title.setProperty("title", True)
        hero_text.addWidget(hero_title)
        hero_body = QLabel(
            "Turn your narrated recordings into bug reports for your AI agent. Pick recordings, "
            "press one button, and copy a ready prompt for Claude Code or Codex."
        )
        hero_body.setWordWrap(True)
        hero_body.setProperty("muted", True)
        hero_text.addWidget(hero_body)
        hero_layout.addLayout(hero_text, 1)
        self.home_bug_reports_button = QPushButton("Choose recordings")
        self.home_bug_reports_button.setProperty("primary", True)
        self.home_bug_reports_button.setMinimumHeight(40)
        self.home_bug_reports_button.clicked.connect(lambda: self.navigate(BUG_REPORTS_PAGE))
        hero_layout.addWidget(self.home_bug_reports_button, alignment=Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(hero)
        other_title = QLabel("Other tasks")
        other_title.setProperty("sectionTitle", True)
        layout.addWidget(other_title)
        workflow_grid = QGridLayout()
        workflow_grid.setHorizontalSpacing(12)
        workflow_grid.setVerticalSpacing(12)
        self.home_workflow_cards: dict[str, QFrame] = {}
        self.home_profile_labels: dict[str, QLabel] = {}
        self.home_selection_labels: dict[str, QLabel] = {}
        for index, workflow in enumerate(WORKFLOWS):
            frame = _card()
            frame.setProperty("selectedWorkflow", False)
            frame.setMinimumHeight(176)
            frame_layout = QVBoxLayout(frame)
            frame_layout.setContentsMargins(16, 14, 16, 14)
            heading = QLabel(f"{workflow.number}  {workflow.title}")
            heading.setProperty("sectionTitle", True)
            frame_layout.addWidget(heading)
            selected_label = QLabel("READY TO START")
            selected_label.setProperty("selectionBadge", True)
            selected_label.setVisible(False)
            frame_layout.addWidget(selected_label, alignment=Qt.AlignmentFlag.AlignLeft)
            purpose = QLabel(WORKFLOW_PURPOSES[workflow.number])
            purpose.setWordWrap(True)
            purpose.setProperty("muted", True)
            frame_layout.addWidget(purpose)
            source = QLabel(WORKFLOW_SOURCE_LABELS[workflow.number])
            source.setProperty("accent", True)
            source.setWordWrap(True)
            frame_layout.addWidget(source)
            profile_label = QLabel("Recommended settings are ready; presets are optional")
            profile_label.setProperty("small", True)
            profile_label.setWordWrap(True)
            frame_layout.addWidget(profile_label)
            frame_layout.addStretch(1)
            start = QPushButton("Start")
            start.clicked.connect(
                lambda checked=False, number=workflow.number: self.start_workflow_from_home(number)
            )
            frame_layout.addWidget(start, alignment=Qt.AlignmentFlag.AlignRight)
            if workflow.number == WORKFLOW_CODEX_EVIDENCE:
                # Same job as the "Find my bug reports" hero (95); offered on New.
                frame.setVisible(False)
            else:
                # 152: Review Media Inbox has its card again (Wave 6, 220). 237: three cards a row,
                # so every card is on screen in the smallest window and at a large text size.
                visible_index = len([number for number in self.home_workflow_cards if number != WORKFLOW_CODEX_EVIDENCE])
                workflow_grid.addWidget(frame, *divmod(visible_index, HOME_CARD_COLUMNS))
            self.home_workflow_cards[workflow.number] = frame
            self.home_profile_labels[workflow.number] = profile_label
            self.home_selection_labels[workflow.number] = selected_label
        # 150: the AI Video Editor card, appended on a row of its own so the
        # existing cards keep their size. Start opens its page; it is not a workflow.
        editor_card, self.home_ai_video_editor_button = home_card_frame(
            lambda checked=False: self.navigate(AI_VIDEO_EDITOR_PAGE)
        )
        editor_card.setMinimumHeight(140)
        cards_so_far = len([number for number in self.home_workflow_cards if number != WORKFLOW_CODEX_EVIDENCE])
        workflow_grid.addWidget(editor_card, *divmod(cards_so_far, HOME_CARD_COLUMNS))
        self.home_workflow_cards[AI_VIDEO_EDITOR_HOME_CARD] = editor_card
        # 220: the raw bin library, beside the AI Video Editor card.
        raw_bin_card, self.home_raw_bin_button = raw_bin_home_card_frame(
            lambda checked=False: self.navigate(RAW_BIN_PAGE)
        )
        raw_bin_card.setMinimumHeight(140)
        workflow_grid.addWidget(raw_bin_card, *divmod(cards_so_far + 1, HOME_CARD_COLUMNS))
        for column in range(HOME_CARD_COLUMNS):
            workflow_grid.setColumnStretch(column, 1)
        self.home_workflow_cards[RAW_BIN_HOME_CARD] = raw_bin_card
        layout.addLayout(workflow_grid)

        lower = QHBoxLayout()
        recent_card = _card()
        recent_layout = QVBoxLayout(recent_card)
        recent_title = QLabel("Recent runs")
        recent_title.setProperty("sectionTitle", True)
        recent_layout.addWidget(recent_title)
        self.home_recent_list = QListWidget()
        ui_theme.keep_scaled(self.home_recent_list, "setMaximumHeight", 150)
        recent_layout.addWidget(self.home_recent_list)
        self._attach_run_list(self.home_recent_list, "Recent runs")
        lower.addWidget(recent_card, 2)
        status_card = _card()
        status_layout = QVBoxLayout(status_card)
        status_title = QLabel("Last evidence package")
        status_title.setProperty("sectionTitle", True)
        status_layout.addWidget(status_title)
        self.home_package_status = QLabel("No package opened yet")
        self.home_package_status.setWordWrap(True)
        self.home_package_status.setProperty("muted", True)
        status_layout.addWidget(self.home_package_status)
        self.home_unresolved = QLabel("Unresolved mentions: unknown")
        status_layout.addWidget(self.home_unresolved)
        status_buttons = QHBoxLayout()
        open_last = QPushButton("Open package")
        open_last.clicked.connect(self.open_last_evidence_package)
        open_output = QPushButton("Open output")
        status_buttons.addWidget(open_last)
        status_buttons.addWidget(open_output)
        status_layout.addLayout(status_buttons)
        # 237: "Opened" or why not, under the buttons.
        home_feedback = InlineFeedback()
        home_feedback.setObjectName("homePackageFeedback")
        status_layout.addWidget(home_feedback)
        bind_action(open_output, self.open_current_output, working="Opening…", done="Opened", feedback=home_feedback)
        status_layout.addStretch(1)
        lower.addWidget(status_card, 1)
        layout.addLayout(lower)
        layout.addStretch(1)
        return page

    def refresh_home(self) -> None:
        for workflow in WORKFLOWS:
            label = self.home_profile_labels.get(workflow.number)
            if label:
                label.setText(
                    "Uses saved Inbox settings"
                    if workflow.number == WORKFLOW_REVIEW_NEW_VIDEOS
                    else "Recommended settings are ready; presets are optional"
                )
            frame = self.home_workflow_cards.get(workflow.number)
            if frame:
                frame.setProperty("selectedWorkflow", False)
                badge = self.home_selection_labels.get(workflow.number)
                if badge:
                    badge.setVisible(False)
                frame.style().unpolish(frame)
                frame.style().polish(frame)
        self.home_recent_list.clear()
        for run in self.recent_runs(limit=5):
            item = QListWidgetItem(
                f"{run.get('timestamp', '')}  {run.get('workflow_title', 'Review')}  {run.get('status', '')}"
            )
            item.setData(Qt.ItemDataRole.UserRole, run)
            self.home_recent_list.addItem(item)
        if self.current_package:
            status = self.current_package.package_status.get("status", "opened")
            mentions = len(self.current_package.session_mentions)
            self.home_package_status.setText(f"{status.title()} | {mentions} timeline records\n{self.current_package.root}")
            self.home_unresolved.setText(
                f"Unassigned mentions: {len(self.current_package.unassigned_mention_ids)}"
            )
        else:
            path = str(self.app_settings.get("last_evidence_package") or "")
            self.home_package_status.setText(path or "No package opened yet")

    def start_workflow_from_home(self, workflow: str) -> None:
        workflow = normalize_workflow(workflow)
        if workflow == WORKFLOW_REVIEW_NEW_VIDEOS:
            self.set_current_workflow(workflow)
            self.navigate("Review Media Inbox")
            return
        self.use_recommended_settings(workflow)
        self.wizard_stack.setCurrentIndex(0)
        self.wizard_steps.setCurrentRow(0)
        self.navigate("New Review")

    # Review Media Inbox

    def _build_review_inbox_page(self) -> QWidget:
        """Build the one-click Workflow 5 surface without a primary scroll area."""

        page = QWidget()
        page.setObjectName("reviewInboxPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(10)

        heading_row = QHBoxLayout()
        title = QLabel("Review Media Inbox")
        title.setProperty("title", True)
        heading_row.addWidget(title)
        heading_row.addStretch(1)
        self.review_inbox_settings_button = QPushButton("Inbox settings")
        self.review_inbox_settings_button.setObjectName("reviewInboxSettingsButton")
        self.review_inbox_settings_button.clicked.connect(self._open_review_inbox_configuration)
        heading_row.addWidget(self.review_inbox_settings_button)
        layout.addLayout(heading_row)
        safety = QLabel(
            "Local preparation only. Original recordings are never changed or deleted."
        )
        safety.setWordWrap(True)
        safety.setProperty("muted", True)
        safety.setAccessibleName("Review Media Inbox local safety boundary")
        layout.addWidget(safety)
        self.review_inbox_restriction_banner = QLabel("")
        self.review_inbox_restriction_banner.setObjectName(
            "reviewInboxRestrictionBanner"
        )
        self.review_inbox_restriction_banner.setWordWrap(True)
        self.review_inbox_restriction_banner.setProperty("accent", True)
        self.review_inbox_restriction_banner.setAccessibleName(
            "Restricted qualification run"
        )
        launch_restriction_count = len(
            self.run_settings.get("review_inbox_exact_source_paths") or []
        )
        self.review_inbox_restriction_banner.setText(
            (
                "Restricted qualification run: "
                f"{launch_restriction_count} selected "
                f"{'source' if launch_restriction_count == 1 else 'sources'}."
            )
            if launch_restriction_count
            else ""
        )
        self.review_inbox_restriction_banner.setVisible(
            launch_restriction_count > 0
        )
        layout.addWidget(self.review_inbox_restriction_banner)

        workload = QGroupBox("Workload")
        workload_layout = QHBoxLayout(workload)
        self.review_inbox_workload_group = QButtonGroup(self)
        self.review_inbox_next3_radio = QRadioButton("Next 3")
        self.review_inbox_next3_radio.setObjectName("reviewInboxNext3Radio")
        self.review_inbox_next3_radio.setChecked(True)
        self.review_inbox_up_to_radio = QRadioButton("Up to")
        self.review_inbox_up_to_radio.setObjectName("reviewInboxUpToRadio")
        self.review_inbox_up_to_spin = WheelSafeSpinBox()
        self.review_inbox_up_to_spin.setObjectName("reviewInboxUpToSpin")
        self.review_inbox_up_to_spin.setRange(1, 9999)
        self.review_inbox_up_to_spin.setValue(10)
        self.review_inbox_up_to_spin.setVisible(False)
        self.review_inbox_all_pending_radio = QRadioButton("All pending")
        self.review_inbox_all_pending_radio.setObjectName("reviewInboxAllPendingRadio")
        if launch_restriction_count:
            self.review_inbox_all_pending_radio.setEnabled(False)
            self.review_inbox_all_pending_radio.setToolTip(
                "All pending is unavailable for a restricted qualification run."
            )
        for button in (
            self.review_inbox_next3_radio,
            self.review_inbox_up_to_radio,
            self.review_inbox_all_pending_radio,
        ):
            self.review_inbox_workload_group.addButton(button)
            button.toggled.connect(self._review_inbox_workload_changed)
        workload_layout.addWidget(self.review_inbox_next3_radio)
        workload_layout.addSpacing(12)
        workload_layout.addWidget(self.review_inbox_up_to_radio)
        workload_layout.addWidget(self.review_inbox_up_to_spin)
        workload_layout.addSpacing(12)
        workload_layout.addWidget(self.review_inbox_all_pending_radio)
        workload_layout.addStretch(1)
        layout.addWidget(workload)

        action_row = QHBoxLayout()
        self.review_inbox_process_button = QPushButton("Process new media")
        self.review_inbox_process_button.setObjectName("reviewInboxProcessButton")
        self.review_inbox_process_button.setProperty("primary", True)
        self.review_inbox_stop_button = QPushButton("Stop after current")
        self.review_inbox_stop_button.setObjectName("reviewInboxStopButton")
        self.review_inbox_stop_button.setEnabled(False)
        action_row.addWidget(self.review_inbox_process_button, 2)
        action_row.addWidget(self.review_inbox_stop_button, 1)
        layout.addLayout(action_row)
        # 237: what the click did, beside the buttons, and the run itself in a job banner.
        self.review_inbox_action_feedback = InlineFeedback()
        self.review_inbox_action_feedback.setObjectName("reviewInboxActionFeedback")
        layout.addWidget(self.review_inbox_action_feedback)
        bind_action(self.review_inbox_process_button, self._review_inbox_process_action, working="Starting…",
                    done="Started", feedback=self.review_inbox_action_feedback)
        bind_action(self.review_inbox_stop_button, self._review_inbox_stop_action, working="Asking…",
                    done="Stop requested", feedback=self.review_inbox_action_feedback)
        self.review_inbox_job_banner = self.make_job_banner("Review Media Inbox")
        layout.addWidget(self.review_inbox_job_banner)

        progress_card = _card()
        progress_layout = QVBoxLayout(progress_card)
        progress_layout.setContentsMargins(14, 10, 14, 10)
        self.review_inbox_operator_status = QLabel("Done")
        self.review_inbox_operator_status.setObjectName("reviewInboxOperatorStatus")
        self.review_inbox_operator_status.setProperty("sectionTitle", True)
        self.review_inbox_operator_status.setAccessibleName("Review Media Inbox status")
        progress_layout.addWidget(self.review_inbox_operator_status)
        self.review_inbox_progress_detail = QLabel(
            "No queued review work is currently known."
        )
        self.review_inbox_progress_detail.setObjectName("reviewInboxProgressDetail")
        self.review_inbox_progress_detail.setWordWrap(True)
        progress_layout.addWidget(self.review_inbox_progress_detail)
        self.review_inbox_progress_bar = QProgressBar()
        self.review_inbox_progress_bar.setObjectName("reviewInboxProgressBar")
        self.review_inbox_progress_bar.setRange(0, 1)
        self.review_inbox_progress_bar.setValue(0)
        self.review_inbox_progress_bar.setFormat("Idle")
        progress_layout.addWidget(self.review_inbox_progress_bar)
        self.review_inbox_attention = QLabel("")
        self.review_inbox_attention.setObjectName("reviewInboxAttention")
        self.review_inbox_attention.setWordWrap(True)
        self.review_inbox_attention.setVisible(False)
        progress_layout.addWidget(self.review_inbox_attention)
        layout.addWidget(progress_card)

        counts = QGridLayout()
        self.review_inbox_queue_count_labels: dict[str, QLabel] = {}
        definitions = (
            ("Ready for Codex review", "ready_for_codex_review"),
            ("Waiting on Codex", "waiting_on_codex"),
            ("Additional local evidence", "additional_local_evidence"),
            ("Done", "done"),
        )
        for column, (label_text, key) in enumerate(definitions):
            label = QLabel(label_text)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setProperty("muted", True)
            value = QLabel("0")
            value.setObjectName(
                "reviewInbox" + "".join(part.title() for part in key.split("_")) + "Count"
            )
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value.setProperty("sectionTitle", True)
            value.setAccessibleName(f"{label_text} count")
            counts.addWidget(label, 0, column)
            counts.addWidget(value, 1, column)
            counts.setColumnStretch(column, 1)
            self.review_inbox_queue_count_labels[key] = value
        layout.addLayout(counts)

        queue_actions = QHBoxLayout()
        self.review_inbox_open_queue_button = QPushButton("Open Codex review queue")
        self.review_inbox_open_queue_button.setObjectName("reviewInboxOpenQueueButton")
        self.review_inbox_open_queue_button.setEnabled(False)
        self.review_inbox_copy_prompt_button = QPushButton("Copy Codex prompt")
        self.review_inbox_copy_prompt_button.setObjectName("reviewInboxCopyPromptButton")
        self.review_inbox_copy_prompt_button.setEnabled(False)
        queue_actions.addWidget(self.review_inbox_open_queue_button, 1)
        queue_actions.addWidget(self.review_inbox_copy_prompt_button, 1)
        layout.addLayout(queue_actions)
        self.review_inbox_queue_feedback = InlineFeedback()
        self.review_inbox_queue_feedback.setObjectName("reviewInboxQueueFeedback")
        layout.addWidget(self.review_inbox_queue_feedback)
        bind_action(self.review_inbox_open_queue_button, self.open_review_inbox_queue, working="Opening…",
                    done="Opened", feedback=self.review_inbox_queue_feedback)
        bind_action(self.review_inbox_copy_prompt_button, self.copy_review_inbox_codex_prompt, working="Copying…",
                    done="Copied", feedback=self.review_inbox_queue_feedback)

        self.review_inbox_technical_button = QPushButton("Technical details")
        set_button_kind(self.review_inbox_technical_button, "link")
        self.review_inbox_technical_button.setObjectName("reviewInboxTechnicalButton")
        self.review_inbox_technical_button.clicked.connect(
            self.open_review_inbox_technical_details
        )
        layout.addWidget(
            self.review_inbox_technical_button,
            alignment=Qt.AlignmentFlag.AlignLeft,
        )
        layout.addStretch(1)
        return page

    @staticmethod
    def _split_review_source_folders(value: Any) -> list[str]:
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        return [item.strip() for item in re.split(r"[;\r\n]+", str(value or "")) if item.strip()]

    def _load_review_inbox_controls(self) -> None:
        self._loading = True
        try:
            _set_control_value(self.review_inbox_order_combo, str(self.run_settings.get("review_inbox_order") or "oldest"))
            self.review_inbox_max_files_spin.setValue(int(self.run_settings.get("review_inbox_max_files") or 3))
            self.review_inbox_max_duration_spin.setValue(int(self.run_settings.get("review_inbox_max_duration_minutes") or 240))
            _set_control_value(self.review_inbox_dedupe_combo, str(self.run_settings.get("review_dedupe_mode") or "Fast"))
            self.review_inbox_recurse_checkbox.setChecked(not bool(self.run_settings.get("review_no_recurse")))
            self.review_inbox_pending_limit_spin.setValue(int(self.run_settings.get("review_inbox_pending_batch_limit") or 1))
        finally:
            self._loading = False

    def _review_inbox_configuration_errors(self, *, preparation: bool = False) -> list[str]:
        # 275: the Inbox needs the library; while it cannot be opened, the page says so in one plain line and
        # Process new media is unavailable, and nothing is started or changed.
        refusal = self.library_refusal("Review Media Inbox")
        if refusal:
            return [refusal]
        # 224 (Wave B2b): until its records are in the library the Inbox opens nothing, and says why in one line.
        not_ready = self._review_inbox_not_ready()
        if not_ready:
            return [not_ready]
        errors: list[str] = []
        folders = self._split_review_source_folders(self.run_settings.get("review_source_folders"))
        if not folders:
            errors.append(
                "Use Inbox settings to choose at least one local source folder; "
                "no folder is guessed from the general input setting."
            )
        else:
            missing = [Path(item).name or item for item in folders if not Path(item).exists()]
            if missing:
                errors.append("Correct missing source folders: " + ", ".join(missing) + ".")
        if not self._review_inbox_folder():
            errors.append(
                "Use Inbox settings to choose the local Review Media Inbox folder."
            )
        if preparation:
            # 214: a blank Inbox folder uses the main one.
            evidence_root = review_evidence_root(self._with_main_folders(self.run_settings))
            if not evidence_root:
                errors.append(
                    "Use Inbox settings to choose an evidence root for prepared batches."
                )
            elif temporary_folder_problem(evidence_root, "evidence folder"):
                # 211: the one output-folder rule; the scratch / work root may be a temp folder.
                errors.append(temporary_folder_problem(evidence_root, "evidence folder"))
            if not review_work_root(self.run_settings):
                errors.append(
                    "Use Inbox settings to choose a separate scratch / work root."
                )
        return errors

    def _review_inbox_audio_state(self, source: dict[str, Any]) -> tuple[str, str]:
        path = str(source.get("path") or "")
        key = str(Path(path).resolve()) if path else ""
        if key in self.audio_inspection_failures:
            return "Inspection failed", "Correct the audio/tool error and retry inspection."
        inspection = self.audio_inspections.get(key)
        if inspection is None:
            return "Inspection required", "Inspect audio before preparation."
        if not inspection.streams and inspection.resolved:
            return "Ready — no audio", "Visual preparation can continue; transcript is not applicable."
        if inspection.confirmation_state == "single-stream":
            return "Ready — single stream", "The only audio stream is selected automatically."
        if inspection.confirmation_state == "confirmed-layout":
            return "Ready — saved exact layout", "Exact complete-layout confirmation was reused."
        if inspection.confirmation_state == "operator-confirmed":
            return "Ready — operator confirmed", "The selected narration stream is saved for this exact layout."
        if inspection.confirmation_state == "confirmed-recording":
            return "Ready — your answer", "You chose this track for this recording."
        return "Confirmation required", "Preview and confirm the narration stream; Track 1 is never assumed."

    def _review_inbox_selected_sources(self) -> list[dict[str, Any]]:
        return list((self.review_inbox_scan_result or {}).get("selected_sources") or [])

    def _review_inbox_selected_paths(self) -> list[str]:
        return [str(item.get("path") or "") for item in self._review_inbox_selected_sources() if str(item.get("path") or "")]

    def _review_inbox_audio_paths(self) -> list[str]:
        paths = self._review_inbox_selected_paths()
        paths.extend(
            str(item.get("path") or "")
            for item in self._review_inbox_resume_sources()
            if str(item.get("classification") or "") == "needs_audio_confirmation"
        )
        return list(dict.fromkeys(path for path in paths if path))

    def _refresh_review_inbox_source_table(self) -> None:
        if not hasattr(self, "review_inbox_source_table"):
            return
        result = self.review_inbox_scan_result or {}
        sources = list(result.get("sources") or self.review_inbox_restored_sources)
        selected_ids = {int(item.get("source_id") or 0) for item in result.get("selected_sources") or []}
        self.review_inbox_source_table.setRowCount(len(sources))
        eligible_states = review_inbox.ELIGIBLE_STATES
        for row, source in enumerate(sources):
            path = str(source.get("path") or "")
            classification = str(source.get("classification") or "unknown")
            source_id = int(source.get("source_id") or 0)
            selected = source_id in selected_ids
            excluded = bool(source.get("pending_batch_excluded"))
            audio_required = selected or (excluded and classification == "needs_audio_confirmation")
            audio_text, audio_reason = self._review_inbox_audio_state(source) if audio_required else ("Not required", "Audio is inspected only for selected or resumable preparation candidates.")
            eligible = classification in eligible_states and not excluded
            reason = (
                "Already belongs to an active unfinalized batch."
                if excluded
                else audio_reason if selected else "Selected after earlier eligible sources." if eligible else "Lifecycle state is not eligible for a new batch."
            )
            values = (
                Path(path).name or path,
                str(source.get("modified_utc") or ""),
                f"{int(source.get('size_bytes') or 0) / (1024 * 1024):.1f} MiB",
                classification,
                "Eligible" if eligible else "Excluded",
                audio_text,
                "Selected" if selected else "Active batch" if excluded else "Not selected",
                reason,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(path if column == 0 else value)
                item.setData(Qt.ItemDataRole.UserRole, source)
                self.review_inbox_source_table.setItem(row, column, item)
        counts = dict(result.get("classification_counts") or {})
        if not result:
            for source in sources:
                state = str(source.get("classification") or "unknown")
                counts[state] = counts.get(state, 0) + 1
        values = {
            "inventory": int(result.get("inventory_count") or len(sources)),
            "eligible": int(result.get("eligible_count") or 0),
            "selected": len(result.get("selected_sources") or []),
            "finalized": sum(int(counts.get(key, 0)) for key in ("finalized_no_findings", "finalized_with_findings")),
            "awaiting": int(counts.get("awaiting_external_review", 0)),
            "audio": int(counts.get("needs_audio_confirmation", 0)),
            "retryable": int(counts.get("retryable_failure", 0)),
            "changed": int(counts.get("source_changed", 0)),
            "duplicates": int(counts.get("duplicate", 0)),
            "batches": len(result.get("pending_batches") or ([self.review_inbox_active_batch] if self.review_inbox_active_batch else [])),
        }
        for key, label in self.review_inbox_count_labels.items():
            label.setText(str(values.get(key, 0)) if result or sources or key == "batches" else "—")

    def _review_inbox_prompt_path(self) -> Path | None:
        batch_value = str((self.review_inbox_active_batch or {}).get("package_path") or "").strip()
        if not batch_value:
            return None
        path = Path(batch_value) / "CODEX_REVIEW_PROMPT.md"
        return path if path.is_file() else None

    def _review_inbox_resume_sources(self) -> list[dict[str, Any]]:
        sources = list((self.review_inbox_scan_result or {}).get("sources") or self.review_inbox_restored_sources)
        return [
            item
            for item in sources
            if bool(item.get("pending_batch_excluded"))
            and str(item.get("classification") or "")
            in {"needs_audio_confirmation", "retryable_failure", "source_changed", "preparing"}
        ]

    def _review_inbox_resume_blockers(self) -> list[str]:
        blockers = self._review_inbox_configuration_errors(preparation=True)
        if self.review_inbox_scan_result is None:
            blockers.append("Rescan to load authoritative source state before resuming.")
            return blockers
        candidates = self._review_inbox_resume_sources()
        unresolved = [
            Path(str(item.get("path") or "")).name
            for item in candidates
            if str(item.get("classification") or "") == "needs_audio_confirmation"
            and self._review_inbox_audio_state(item)[0]
            in {"Inspection required", "Confirmation required", "Inspection failed"}
        ]
        if unresolved:
            blockers.append("Inspect and confirm narration audio for: " + ", ".join(unresolved) + ".")
        if not self.resources.backend_ready:
            blockers.append("Resolve required runtime dependencies in Settings > Dependencies.")
        if self.review_inbox_dedupe_combo.currentText() == "Full" and not self.review_inbox_prepare_full_acknowledged:
            blockers.append("Confirm the Full preparation inventory scan for this run; it may read multiple terabytes.")
        return list(dict.fromkeys(blockers))

    def _review_inbox_targeted_paths(self) -> list[Path]:
        batch_root = Path(str((self.review_inbox_active_batch or {}).get("package_path") or ""))
        sources_root = batch_root / "sources"
        if not sources_root.is_dir():
            return []
        return sorted(
            path
            for path in sources_root.glob("*/targeted-evidence")
            if path.is_dir() and any(path.glob("f-*/r-*/integrity.json"))
        )

    def _review_inbox_prepare_blockers(self) -> list[str]:
        blockers = self._review_inbox_configuration_errors(preparation=True)
        result = self.review_inbox_scan_result
        if result is None:
            blockers.append("Run a successful current scan.")
            return blockers
        if self.review_inbox_active_batch or bool(result.get("pending_batch_limit_reached")):
            blockers.append("Open or resume the oldest active batch; the pending-batch limit prevents a new batch.")
        selected = self._review_inbox_selected_sources()
        if not selected:
            blockers.append("No eligible source is selected by the current bounds.")
        unresolved = [Path(str(item.get("path") or "")).name for item in selected if self._review_inbox_audio_state(item)[0] in {"Inspection required", "Confirmation required", "Inspection failed"}]
        if unresolved:
            blockers.append("Inspect and confirm narration audio for: " + ", ".join(unresolved) + ".")
        if self.audio_inspection_thread is not None:
            blockers.append("Wait for audio inspection to finish or cancel it safely.")
        if not self.resources.backend_ready:
            blockers.append("Resolve required runtime dependencies in Settings > Dependencies.")
        if self.review_inbox_dedupe_combo.currentText() == "Full" and not self.review_inbox_prepare_full_acknowledged:
            blockers.append("Confirm the Full preparation inventory scan for this run; it may read multiple terabytes.")
        return list(dict.fromkeys(blockers))

    # One-click Review Media Inbox surface. These later definitions intentionally
    # supersede the staged GUI handlers above while leaving legacy CLI behavior alone.

    def _review_inbox_workload_changed(self, *_args: Any) -> None:
        if not hasattr(self, "review_inbox_up_to_spin"):
            return
        self.review_inbox_up_to_spin.setVisible(
            self.review_inbox_up_to_radio.isChecked()
        )

    def _review_inbox_workload_values(self) -> tuple[str, int]:
        if self.review_inbox_all_pending_radio.isChecked():
            return "all_pending", 0
        if self.review_inbox_up_to_radio.isChecked():
            return "up_to_n", int(self.review_inbox_up_to_spin.value())
        return "next_3", 3

    def _review_inbox_reconcile_payload(self) -> dict[str, Any]:
        return {
            "source_folders": self._split_review_source_folders(
                self.run_settings.get("review_source_folders")
            ),
            "evidence_root": review_evidence_root(self._with_main_folders(self.run_settings)),
            "local_work_root": review_work_root(self.run_settings),
            # 224 (Wave B2b): the Inbox folder; the ledger's name in it (a note since the move) is what the
            # Inbox's plans and journals have always carried.
            "inbox_folder": self._review_inbox_folder(),
            "ledger_path": str(Path(self._review_inbox_folder()) / inbox_records.LEDGER_NAME)
            if self._review_inbox_folder() else "",
            "recurse": not bool(self.run_settings.get("review_no_recurse")),
            "dedupe_mode": str(
                self.run_settings.get("review_dedupe_mode") or "Fast"
            ),
            "audio_confirmations_path": str(self.layout_confirmation_store.path),
            "allow_source_scan": False,
            "allow_media_processing": False,
            "allow_operator_prompts": False,
        }

    def _restore_review_inbox_pending_batch(self) -> None:
        """Reconcile queue state without scanning source media or opening dialogs."""

        self.start_review_inbox_reconcile()

    def start_review_inbox_reconcile(self) -> None:
        if (
            not hasattr(self, "review_inbox_process_button")
            or self.review_inbox_reconcile_thread is not None
            or self.runner_thread is not None
        ):
            return
        errors = self._review_inbox_configuration_errors(preparation=True)
        if errors:
            self._apply_review_inbox_status(
                {
                    "operator_status": "Needs attention",
                    "queue_counts": self._review_inbox_contract_counts(
                        self.review_inbox_status_contract
                    ),
                    "run_state": {},
                    "attention": {"message": " ".join(errors)},
                }
            )
            return
        thread = ReviewInboxOperationThread(
            self._review_inbox_reconcile_payload(),
            self.review_inbox_reconciler,
        )
        thread.operation_ready.connect(self._review_inbox_reconcile_ready)
        thread.operation_failed.connect(self._review_inbox_reconcile_failed)
        thread.finished.connect(
            lambda worker=thread: self._review_inbox_reconcile_stopped(worker)
        )
        self.review_inbox_reconcile_thread = thread
        self.review_inbox_operator_status.setText("Processing")
        self.review_inbox_progress_detail.setText(
            "Checking the local Codex queue for completed work…"
        )
        self.review_inbox_progress_bar.setRange(0, 0)
        self.review_inbox_progress_bar.setFormat("Checking local queue")
        self._refresh_review_inbox_dashboard()
        thread.start()

    def _review_inbox_reconcile_ready(self, result: dict[str, Any]) -> None:
        if not isinstance(result, dict):
            self._review_inbox_reconcile_failed(
                "The local queue returned an invalid status."
            )
            return
        held = result.get("lock_held_seconds")
        if isinstance(held, (int, float)) and not isinstance(held, bool):
            # 224 (Wave B2a, item 4): measured, so the command line's ten-second wait is checked against it.
            self._write_workbench_log(f"The Inbox's status check held its lock for {held:.2f} seconds.")
        self._apply_review_inbox_status(result)

    def _review_inbox_reconcile_failed(self, details: str) -> None:
        self._apply_review_inbox_status(
            {
                "operator_status": "Needs attention",
                "queue_counts": self._review_inbox_contract_counts(
                    self.review_inbox_status_contract
                ),
                "run_state": self._review_inbox_contract_run(
                    self.review_inbox_status_contract
                ),
                "attention": {
                    "message": "The local queue could not be checked safely.",
                    "details": details,
                },
            }
        )

    def _review_inbox_reconcile_stopped(
        self, worker: ReviewInboxOperationThread
    ) -> None:
        if self.review_inbox_reconcile_thread is worker:
            self.review_inbox_reconcile_thread = None
        worker.deleteLater()
        self._refresh_review_inbox_dashboard()
        if (
            self.review_inbox_process_after_dependency_check
            and self.dependency_check_thread is None
        ):
            QTimer.singleShot(
                0, self._resume_review_inbox_after_dependency_check
            )

    @staticmethod
    def _review_inbox_operator_status(value: Any) -> str:
        normalized = str(value or "").strip().replace("-", "_").replace(" ", "_").casefold()
        return {
            "processing": "Processing",
            "ready_for_codex_review": "Ready for Codex review",
            "awaiting_external_review": "Ready for Codex review",
            "waiting_on_codex": "Waiting on Codex",
            "targeted_evidence_ready": "Waiting on Codex",
            "manual_review_available": "Manual review available",
            "needs_audio_choice": "Needs audio choice",
            "needs_audio_confirmation": "Needs audio choice",
            "needs_attention": "Needs attention",
            "error": "Needs attention",
            "done": "Done",
            "completed": "Done",
            "idle": "Done",
        }.get(normalized, "Needs attention")

    @staticmethod
    def _review_inbox_attention_text(value: Any) -> tuple[str, str]:
        if isinstance(value, dict):
            message = str(
                value.get("message")
                or value.get("summary")
                or value.get("title")
                or ""
            ).strip()
            details = str(value.get("details") or value.get("error") or "").strip()
            return message, details
        return str(value or "").strip(), ""

    @staticmethod
    def _review_inbox_contract_counts(contract: dict[str, Any]) -> dict[str, Any]:
        value = contract.get("queue_counts")
        if not isinstance(value, dict):
            value = contract.get("counts")
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _review_inbox_contract_run(contract: dict[str, Any]) -> dict[str, Any]:
        value = contract.get("run_state")
        if not isinstance(value, dict):
            value = contract.get("run")
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _review_inbox_count(counts: dict[str, Any], key: str) -> int:
        try:
            return max(0, int(counts.get(key) or 0))
        except (TypeError, ValueError):
            return 0

    def _apply_review_inbox_status(self, contract: dict[str, Any]) -> None:
        if not isinstance(contract, dict):
            return
        self.review_inbox_status_contract = dict(contract)
        if not hasattr(self, "review_inbox_operator_status"):
            return
        status = self._review_inbox_operator_status(contract.get("operator_status"))
        counts = self._review_inbox_contract_counts(contract)
        manual_review_count = self._review_inbox_count(counts, "manual_review")
        manual_review_message = (
            (
                f"{manual_review_count} prior "
                f"{'item remains' if manual_review_count == 1 else 'items remain'} "
                "available for manual review. New media processing can continue."
            )
            if manual_review_count
            else ""
        )
        for key, label in self.review_inbox_queue_count_labels.items():
            label.setText(str(self._review_inbox_count(counts, key)))

        run = self._review_inbox_contract_run(contract)
        restriction_count = int(
            run.get("exact_source_restriction_count")
            or len(self.run_settings.get("review_inbox_exact_source_paths") or [])
            or 0
        )
        self.review_inbox_restriction_banner.setText(
            (
                "Restricted qualification run: "
                f"{restriction_count} selected "
                f"{'source' if restriction_count == 1 else 'sources'}."
            )
            if restriction_count
            else ""
        )
        self.review_inbox_restriction_banner.setVisible(restriction_count > 0)
        running = self.runner_thread is not None
        reconciling = self.review_inbox_reconcile_thread is not None
        checking_dependencies = self.review_inbox_process_after_dependency_check
        if running or reconciling or checking_dependencies:
            status = "Processing"
        elif self.dependency_check_thread is not None:
            # 220: the start-up tool check is still running; Process waits for it.
            status = "Checking tools"
        self.review_inbox_operator_status.setText(status)
        operator_state = {
            "Processing": "active",
            "Checking tools": "waiting",
            "Ready for Codex review": "ready",
            "Waiting on Codex": "waiting",
            "Manual review available": "attention",
            "Needs audio choice": "attention",
            "Needs attention": "error",
            "Done": "ready",
        }[status]
        self._set_operator_state(self.review_inbox_operator_status, operator_state)

        current_name = str(
            run.get("current_source_name")
            or run.get("current_source")
            or contract.get("message")
            or contract.get("detail")
            or ""
        ).strip()
        if current_name and re.search(r"[\\/]", current_name):
            current_name = Path(current_name).name
        ordinal = int(
            run.get("current_source_ordinal")
            or run.get("source_ordinal")
            or run.get("current_ordinal")
            or 0
        )
        total = int(
            run.get("current_source_total")
            or run.get("source_total")
            or run.get("total")
            or 0
        )
        activity = str(
            run.get("current_activity")
            or run.get("activity")
            or run.get("phase")
            or ""
        ).strip()
        detail_parts = [part for part in (current_name, f"{ordinal} of {total}" if ordinal and total else "", activity) if part]
        default_detail = {
            "Processing": "Working through local Review Media Inbox tasks sequentially.",
            "Checking tools": "Checking the configured local tools; Process is available when they are ready.",
            "Ready for Codex review": "Compact evidence is ready in the local Codex review queue.",
            "Waiting on Codex": "Local preparation is complete; waiting for external review results.",
            "Manual review available": manual_review_message,
            "Needs audio choice": "Choose the microphone track to continue this source.",
            "Needs attention": "Review the message below before processing new media.",
            "Done": manual_review_message or "No queued local work needs attention.",
        }[status]
        self.review_inbox_progress_detail.setText(
            " · ".join(detail_parts) if detail_parts else default_detail
        )

        completed = int(
            run.get("completed_count")
            or run.get("completed")
            or run.get("source_completed")
            or 0
        )
        if total > 0:
            self.review_inbox_progress_bar.setRange(0, total)
            self.review_inbox_progress_bar.setValue(max(0, min(total, completed)))
            self.review_inbox_progress_bar.setFormat(f"{completed} of {total}")
        elif status == "Processing":
            self.review_inbox_progress_bar.setRange(0, 0)
            self.review_inbox_progress_bar.setFormat("Processing")
        else:
            self.review_inbox_progress_bar.setRange(0, 1)
            self.review_inbox_progress_bar.setValue(1 if status == "Done" else 0)
            self.review_inbox_progress_bar.setFormat(status)
        # 224 (Wave B2a, 5d): a bar only while something is measured or running; otherwise the heading alone
        # says the state, so "Needs attention" is not said twice.
        self.review_inbox_progress_bar.setVisible(total > 0 or status == "Processing")

        attention, attention_details = self._review_inbox_attention_text(
            contract.get("attention")
        )
        if attention_details:
            self._record_review_inbox_diagnostic(attention_details)
        if status == "Needs attention" and not attention:
            attention = "The local queue reported a condition that needs correction."
        elif manual_review_message and not attention:
            attention = manual_review_message
        self.review_inbox_attention.setText(attention)
        # Raw diagnostics, paths, and exception text belong only in the
        # separate Technical details dialog, never on the primary page.
        self.review_inbox_attention.setToolTip("")
        self.review_inbox_attention.setVisible(bool(attention))
        self._set_operator_state(
            self.review_inbox_attention,
            "error" if status == "Needs attention" else "attention",
        )

        queue_root_value = str(contract.get("queue_root") or "").strip()
        prompt_value = str(contract.get("queue_prompt_path") or "").strip()
        queue_root = Path(queue_root_value) if queue_root_value else None
        prompt_path = Path(prompt_value) if prompt_value else None
        self.review_inbox_open_queue_button.setEnabled(
            bool(queue_root and queue_root.is_dir())
        )
        ready_for_codex = sum(
            self._review_inbox_count(counts, key)
            for key in ("ready_for_codex_review", "waiting_on_codex")
        )
        codex_work_ready = bool(contract.get("codex_work_ready")) or (
            ready_for_codex > 0
        )
        self.review_inbox_copy_prompt_button.setEnabled(
            bool(prompt_path and prompt_path.is_file() and codex_work_ready)
        )
        if codex_work_ready:
            self.review_inbox_copy_prompt_button.setToolTip(
                "Copy the instructions for the active Codex review queue."
            )
        else:
            self.review_inbox_copy_prompt_button.setToolTip(
                "No Codex review work is ready yet."
            )
            if status == "Done" and not detail_parts and not manual_review_message:
                self.review_inbox_progress_detail.setText(
                    "No Codex review work is ready yet. Process new media when you are ready."
                )

        locked = bool(
            run.get("active")
            or run.get("resumable")
            or running
            or checking_dependencies
        )
        workload = str(run.get("workload_mode") or "").strip().casefold()
        if not locked:
            workload = "next_3"
        if workload in {"next_3", "up_to_n", "all_pending"}:
            with (
                QSignalBlocker(self.review_inbox_next3_radio),
                QSignalBlocker(self.review_inbox_up_to_radio),
                QSignalBlocker(self.review_inbox_all_pending_radio),
            ):
                self.review_inbox_next3_radio.setChecked(workload == "next_3")
                self.review_inbox_up_to_radio.setChecked(workload == "up_to_n")
                self.review_inbox_all_pending_radio.setChecked(
                    workload == "all_pending"
                )
            if workload == "up_to_n":
                try:
                    self.review_inbox_up_to_spin.setValue(
                        max(1, min(9999, int(run.get("new_source_limit") or 10)))
                    )
                except (TypeError, ValueError):
                    self.review_inbox_up_to_spin.setValue(10)
            elif not locked:
                self.review_inbox_up_to_spin.setValue(10)
        self._review_inbox_workload_changed()
        for control in (
            self.review_inbox_next3_radio,
            self.review_inbox_up_to_radio,
            self.review_inbox_all_pending_radio,
            self.review_inbox_up_to_spin,
        ):
            control.setEnabled(not locked)
        self.review_inbox_all_pending_radio.setEnabled(
            not locked and restriction_count == 0
        )
        self.review_inbox_all_pending_radio.setToolTip(
            "All pending is unavailable for a restricted qualification run."
            if restriction_count
            else ""
        )

        errors = self._review_inbox_configuration_errors(preparation=True)
        dependencies_allow_start = (
            self.resources.backend_ready
            or not self.resources.preflight_complete
        )
        ready = (
            not errors
            and dependencies_allow_start
            and not running
            and not reconciling
            and self.dependency_check_thread is None
            and not checking_dependencies
        )
        self.review_inbox_process_button.setEnabled(ready)
        if not self.resources.preflight_complete:
            self.review_inbox_process_button.setToolTip(
                "Process will verify the configured local tools, then continue "
                "automatically when they are ready."
            )
        elif not self.resources.backend_ready:
            self.review_inbox_process_button.setToolTip(
                "Resolve required runtime dependencies in Settings > Dependencies."
            )
        else:
            self.review_inbox_process_button.setToolTip(
                "Process the selected bounded workload."
            )
        self.review_inbox_stop_button.setEnabled(
            running and self.review_inbox_stop_path is not None
        )
        self.review_inbox_settings_button.setEnabled(
            not running and not checking_dependencies
        )

    def _refresh_review_inbox_dashboard(self) -> None:
        if not hasattr(self, "review_inbox_process_button"):
            return
        contract = dict(self.review_inbox_status_contract)
        errors = self._review_inbox_configuration_errors(preparation=True)
        if errors and self.runner_thread is None:
            contract.update(
                {
                    "operator_status": "Needs attention",
                    "attention": {"message": " ".join(errors)},
                }
            )
        self._apply_review_inbox_status(contract)

    def _apply_review_inbox_structured_progress(
        self, payload: dict[str, Any]
    ) -> None:
        # 214: the Inbox page follows a run only when the Inbox started that run, decided when it
        # started; opening New Review during the run does not take its progress away.
        if not self._running_inbox() or not hasattr(self, "review_inbox_progress_bar"):
            return
        self.review_inbox_progress_bar.setVisible(True)
        self.review_inbox_operator_status.setText("Processing")
        self._set_operator_state(self.review_inbox_operator_status, "active")
        source = str(
            payload.get("source_name") or payload.get("source_id") or ""
        ).strip()
        if source and re.search(r"[\\/]", source):
            source = Path(source).name
        ordinal = int(payload.get("source_ordinal") or 0)
        source_total = int(payload.get("source_total") or 0)
        activity = self._operator_progress_activity(
            str(payload.get("activity") or payload.get("phase") or "")
        )
        parts = [
            value
            for value in (
                source,
                f"{ordinal} of {source_total}" if ordinal and source_total else "",
                activity,
            )
            if value
        ]
        self.review_inbox_progress_detail.setText(
            " · ".join(parts)
            if parts
            else "Processing local Review Media Inbox work…"
        )
        kind = str(payload.get("progress_kind") or "indeterminate")
        completed = int(payload.get("completed") or 0)
        total = int(payload.get("total") or 0)
        if kind == "work_units" and total > 0:
            set_work_bar(self.review_inbox_progress_bar, completed, total)
            self.review_inbox_progress_bar.setFormat(
                work_done_text(completed, total, str(payload.get("work_unit") or "")))
        else:
            self.review_inbox_progress_bar.setRange(0, 0)
            self.review_inbox_progress_bar.setFormat("Processing")
        self.review_inbox_stop_button.setEnabled(
            self.runner_thread is not None and self.review_inbox_stop_path is not None
        )

    def _refresh_review_inbox_batch(self) -> None:
        self._refresh_review_inbox_dashboard()

    def _open_review_inbox_configuration(self) -> None:
        if self.runner_thread is not None:
            return
        shown = deepcopy(self.run_settings)
        shown["review_inbox_folder"] = self._review_inbox_folder()
        dialog = ReviewInboxSettingsDialog(shown, self,
                                           main_output_folder=str(self.app_settings.get("output_folder") or "").strip(),
                                           main_temp_folder=main_temp_folder(self.app_settings))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self.run_settings.update(values)
        self.app_settings.update(values)
        self.save_app_settings()
        self.review_inbox_status_contract = {
            "operator_status": "Done",
            "queue_counts": {
                "ready_for_codex_review": 0,
                "waiting_on_codex": 0,
                "additional_local_evidence": 0,
                "done": 0,
            },
            "run_state": {},
        }
        self._refresh_review_inbox_dashboard()
        self.start_review_inbox_reconcile()

    def start_review_inbox_process(self, _checked: bool = False) -> None:
        if self.runner_thread is not None or self.review_inbox_reconcile_thread is not None:
            return
        errors = self._review_inbox_configuration_errors(preparation=True)
        if (
            not errors
            and not self.resources.backend_ready
            and not self.resources.preflight_complete
        ):
            self.review_inbox_process_after_dependency_check = True
            if self.dependency_check_thread is None:
                self.start_dependency_check()
            contract = dict(self.review_inbox_status_contract)
            contract.update(
                {
                    "operator_status": "Processing",
                    "message": (
                        "Checking configured local tools before processing; "
                        "no media has been opened."
                    ),
                }
            )
            self._apply_review_inbox_status(contract)
            return
        if not self.resources.backend_ready:
            errors.append(
                "Resolve required runtime dependencies in Settings > Dependencies."
            )
        if errors:
            self._apply_review_inbox_status(
                {
                    "operator_status": "Needs attention",
                    "queue_counts": self._review_inbox_contract_counts(
                        self.review_inbox_status_contract
                    ),
                    "run_state": self._review_inbox_contract_run(
                        self.review_inbox_status_contract
                    ),
                    "attention": {"message": " ".join(errors)},
                }
            )
            return
        full = str(self.run_settings.get("review_dedupe_mode") or "Fast") == "Full"
        if full:
            answer = warn(
                self,
                "Full inventory scan reads every source",
                review_inbox.FULL_SCAN_WARNING + "\n\nContinue with this Process run?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._launch_review_inbox_process(full_acknowledged=full)

    def _resume_review_inbox_after_dependency_check(self) -> None:
        if not self.review_inbox_process_after_dependency_check:
            return
        if self.review_inbox_reconcile_thread is not None:
            return
        if self.resources.backend_ready:
            self.review_inbox_process_after_dependency_check = False
            self.start_review_inbox_process()
            return
        self.review_inbox_process_after_dependency_check = False
        not_ready = [
            item.name
            for item in self.resources.dependencies
            if item.required and not item.ready
        ]
        suffix = f": {', '.join(not_ready)}." if not_ready else "."
        self._apply_review_inbox_status(
            {
                "operator_status": "Needs attention",
                "queue_counts": self._review_inbox_contract_counts(
                    self.review_inbox_status_contract
                ),
                "run_state": self._review_inbox_contract_run(
                    self.review_inbox_status_contract
                ),
                "attention": {
                    "message": (
                        "Resolve required runtime dependencies in "
                        f"Settings > Dependencies{suffix}"
                    )
                },
            }
        )

    def _launch_review_inbox_process(
        self,
        *,
        continuation: str = "",
        decision: dict[str, Any] | None = None,
        full_acknowledged: bool = False,
    ) -> None:
        if self.runner_thread is not None:
            return
        mode, limit = self._review_inbox_workload_values()
        control_root = (
            Path(str(self.app_settings.get("temp_folder") or default_temp_folder()))
            / "review-inbox-controls"
        )
        control_root.mkdir(parents=True, exist_ok=True)
        token = hashlib.sha256(
            f"{time.time_ns()}:{id(self)}".encode("ascii")
        ).hexdigest()[:16]
        self.review_inbox_stop_path = (
            control_root / f"stop-after-current-process-{token}.signal"
        )
        self.review_inbox_stop_path.unlink(missing_ok=True)
        self.review_inbox_process_result = None
        self.review_inbox_final_result = None
        self.review_inbox_active_action = "Process"
        self.current_workflow = WORKFLOW_REVIEW_NEW_VIDEOS
        self.run_settings.update(
            {
                "review_inbox_action": "Process",
                "review_inbox_workload_mode": mode,
                "review_inbox_new_source_limit": limit,
                "review_inbox_continuation": continuation,
                "review_inbox_decision_json": (
                    json.dumps(decision, ensure_ascii=False, separators=(",", ":"))
                    if decision
                    else ""
                ),
                "review_audio_confirmations_path": str(
                    self.layout_confirmation_store.path
                ),
                "review_stop_after_current_file_path": str(
                    self.review_inbox_stop_path
                ),
                "review_full_scan_acknowledged": full_acknowledged,
            }
        )
        self.start_job()
        self.run_settings.pop("review_inbox_continuation", None)
        self.run_settings.pop("review_inbox_decision_json", None)
        if self.runner_thread is not None:
            self.review_inbox_operator_status.setText("Processing")
            self.review_inbox_progress_detail.setText(
                "Starting local Review Media Inbox processing…"
            )
            self.review_inbox_progress_bar.setRange(0, 0)
            self.review_inbox_progress_bar.setFormat("Starting")
            self.review_inbox_stop_button.setEnabled(True)
        self._refresh_review_inbox_dashboard()

    def _review_inbox_process_action(self) -> Outcome:
        running_before = self.runner_thread is not None
        self.start_review_inbox_process()
        if self.runner_thread is not None and not running_before:
            return Outcome.done("Started")
        if self.review_inbox_process_after_dependency_check:
            return Outcome.done("Checking your tools first; it starts after that")
        if self.review_inbox_attention.isVisible() and self.review_inbox_attention.text():
            return Outcome.failed("Not started.", self.review_inbox_attention.text())
        return Outcome.quiet()

    def _review_inbox_stop_action(self) -> Outcome:
        if not self._running_inbox() or self.runner_thread is None:
            return Outcome.quiet()
        self.stop_review_inbox_after_current()
        return Outcome.done("Stop requested; the current recording finishes first")

    def stop_review_inbox_after_current(self) -> None:
        if (
            not self._running_inbox()
            or self.runner_thread is None
            or self.review_inbox_stop_path is None
        ):
            return
        self.review_inbox_stop_path.parent.mkdir(parents=True, exist_ok=True)
        self.review_inbox_stop_path.write_text(
            "Stop after the current operation reaches a safe boundary.\n",
            encoding="utf-8",
        )
        self.review_inbox_stop_button.setEnabled(False)
        self.review_inbox_stop_button.setText(
            "Stop requested — finishing current"
        )
        self.review_inbox_progress_detail.setText(
            "Stop requested. The current source or request may finish safely; nothing else will start."
        )

    def _review_inbox_queue_paths(self) -> tuple[Path | None, Path | None]:
        root_value = str(self.review_inbox_status_contract.get("queue_root") or "").strip()
        prompt_value = str(
            self.review_inbox_status_contract.get("queue_prompt_path") or ""
        ).strip()
        return (
            Path(root_value) if root_value else None,
            Path(prompt_value) if prompt_value else None,
        )

    def open_review_inbox_queue(self) -> Outcome:
        root, _prompt = self._review_inbox_queue_paths()
        return self._open_outcome(root, "Codex review queue")

    def copy_review_inbox_codex_prompt(self) -> Outcome:
        _root, prompt = self._review_inbox_queue_paths()
        counts = self._review_inbox_contract_counts(
            self.review_inbox_status_contract
        )
        codex_work_ready = bool(
            self.review_inbox_status_contract.get("codex_work_ready")
        ) or any(
            self._review_inbox_count(counts, key) > 0
            for key in ("ready_for_codex_review", "waiting_on_codex")
        )
        if not codex_work_ready:
            self.review_inbox_attention.setText(
                "No Codex review work is ready yet."
            )
            self.review_inbox_attention.setToolTip("")
            self.review_inbox_attention.setVisible(True)
            self._set_operator_state(self.review_inbox_attention, "attention")
            return Outcome.failed("No Codex review work is ready yet.", "Process new media first.")
        if prompt is None or not prompt.is_file():
            self.review_inbox_attention.setText(
                "The Codex queue prompt is not ready yet."
            )
            self.review_inbox_attention.setToolTip("")
            self.review_inbox_attention.setVisible(True)
            self._set_operator_state(self.review_inbox_attention, "attention")
            return Outcome.failed("The Codex queue prompt is not ready yet.", "Process new media first.")
        try:
            QApplication.clipboard().setText(prompt.read_text(encoding="utf-8"))
        except OSError as exc:
            self.review_inbox_attention.setText(
                "The Codex queue prompt could not be copied."
            )
            self.review_inbox_attention.setToolTip("")
            self.review_inbox_attention.setVisible(True)
            self._set_operator_state(self.review_inbox_attention, "error")
            self._record_review_inbox_diagnostic(
                "Codex queue prompt copy failed: "
                f"{type(exc).__name__}: {exc}"
            )
            return Outcome.failed("The Codex queue prompt could not be copied.", "Try again in a moment.")
        self.review_inbox_attention.setText(
            "Codex review instructions copied to the clipboard."
        )
        self.review_inbox_attention.setToolTip("")
        self.review_inbox_attention.setVisible(True)
        self._set_operator_state(self.review_inbox_attention, "ready")
        return Outcome.done("Copied. Paste it into Codex.")

    def open_review_inbox_technical_details(self) -> None:
        try:
            settings = deepcopy(self.run_settings)
            settings["review_inbox_action"] = "Process"
            command = build_workflow_command(
                settings,
                workflow=WORKFLOW_REVIEW_NEW_VIDEOS,
                powershell_exe=self.resources.powershell_exe or "powershell",
            ).preview
        except (OSError, ValueError) as exc:
            command = f"Command unavailable: {exc}"
        details = (
            command
            + "\n\nLast local queue status:\n"
            + json.dumps(
                self.review_inbox_status_contract,
                indent=2,
                ensure_ascii=False,
            )
            + (
                "\n\nReview Media Inbox diagnostics:\n"
                + "\n".join(self.review_inbox_diagnostics[-200:])
                if self.review_inbox_diagnostics
                else ""
            )
            + (
                "\n\nRecent Workbench output:\n" + "\n".join(self.run_log_lines[-200:])
                if self.run_log_lines
                else ""
            )
        )
        ReviewInboxTechnicalDialog(
            details,
            open_log=self.open_current_log,
            parent=self,
        ).exec()

    @staticmethod
    def _review_inbox_decision_token(
        kind: str, payload: dict[str, Any], continuation: str
    ) -> str:
        explicit = str(
            payload.get("token")
            or payload.get("confirmation_token")
            or payload.get("plan_set_token")
            or payload.get("plan_sha256")
            or continuation
            or ""
        )
        if explicit:
            return f"{kind}:{explicit}"
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode(
            "utf-8"
        )
        return f"{kind}:{hashlib.sha256(encoded).hexdigest()}"

    def _handle_review_inbox_process_decision(
        self, contract: dict[str, Any]
    ) -> None:
        if self.review_inbox_dialog_active:
            return
        continuation = str(contract.get("continuation") or "")
        candidates = (
            ("all_pending", contract.get("all_pending_confirmation")),
            ("audio_choice", contract.get("audio_choice")),
            ("cleanup", contract.get("cleanup_confirmation")),
        )
        selected = next(
            (
                (kind, value)
                for kind, value in candidates
                if isinstance(value, dict) and value
            ),
            None,
        )
        if selected is None:
            return
        kind, payload = selected
        decision_token = self._review_inbox_decision_token(
            kind, payload, continuation
        )
        if decision_token in self.review_inbox_decision_tokens:
            return
        self.review_inbox_dialog_active = True
        try:
            decision: dict[str, Any] | None = None
            if kind == "all_pending":
                dialog = ReviewInboxAllPendingDialog(payload, self)
                decision = {
                    "type": "all_pending",
                    "token": str(
                        payload.get("token")
                        or payload.get("confirmation_token")
                        or ""
                    ),
                    "confirmed": (
                        dialog.exec() == QDialog.DialogCode.Accepted
                    ),
                }
            elif kind == "audio_choice":
                dialog = ReviewInboxAudioChoiceDialog(
                    payload,
                    ffprobe_exe=self.resources.ffprobe_exe,
                    ffmpeg_exe=self.resources.ffmpeg_exe,
                    temp_root=Path(
                        str(
                            self.app_settings.get("temp_folder")
                            or default_temp_folder()
                        )
                    ),
                    confirmation_store=self.layout_confirmation_store,
                    voice_signature=self.voice_enrollment_store.load(),
                    preferred_track_number=self._preferred_narration_track_number(),
                    # 220: tracks are heard in the shared player, opened on top of the dialog.
                    player_opener=lambda target: self.video_opener.open_over(dialog, target),
                    levels_path_for=lambda path: raw_bin_levels_path(
                        path, cache_setting=str(self.app_settings.get("cache_folder") or "")),
                    parent=self,
                )
                dialog.diagnostic.connect(
                    self._record_review_inbox_diagnostic
                )
                # Whatever the player was doing stops while the dialog asks its question.
                self.video_opener.yield_audio()
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    decision = {
                        "type": "audio",
                        "token": str(payload.get("token") or ""),
                        "confirmed": True,
                        **(dialog.selected_result or {}),
                    }
            else:
                dialog = ReviewInboxCleanupDialog(payload, self)
                dialog.exec()
                decision = {
                    "type": "cleanup",
                    "token": str(
                        payload.get("token")
                        or payload.get("plan_set_token")
                        or ""
                    ),
                    "choice": dialog.decision,
                }
            if decision is None:
                return
            self.review_inbox_decision_tokens.add(decision_token)
            self._launch_review_inbox_process(
                continuation=continuation,
                decision=decision,
                full_acknowledged=True,
            )
        finally:
            self.review_inbox_dialog_active = False

    def _record_review_inbox_diagnostic(self, details: str) -> None:
        details = str(details or "").strip()
        if not details:
            return
        diagnostic = f"[review-inbox] {details}"
        if (
            self.review_inbox_diagnostics
            and self.review_inbox_diagnostics[-1] == diagnostic
        ):
            return
        self.review_inbox_diagnostics.append(diagnostic)
        self.run_log_lines.append(diagnostic)
        self._write_workbench_log(diagnostic)

    # New Review wizard

    def _build_new_review_page(self) -> QWidget:
        page, layout = _page_header(
            "New review",
            "Set up the task in five short steps. Technical command details stay hidden unless needed.",
        )
        content = QHBoxLayout()
        self.wizard_steps = QListWidget()
        ui_theme.keep_scaled(self.wizard_steps, "setFixedWidth", 220)
        for label in ("○ 1  Task\n   Not started", "○ 2  Source\n   Not started", "○ 3  Profile\n   Not started", "○ 4  Output\n   Not started", "○ 5  Review and run\n   Not started"):
            self.wizard_steps.addItem(label)
        self.wizard_steps.setCurrentRow(0)
        self.wizard_steps.currentRowChanged.connect(self._wizard_step_selected)
        content.addWidget(self.wizard_steps)
        self.wizard_stack = QStackedWidget()
        content.addWidget(self.wizard_stack, 1)
        self.wizard_stack.addWidget(self._build_wizard_task_step())
        self.wizard_stack.addWidget(self._build_wizard_source_step())
        self.wizard_stack.addWidget(self._build_wizard_profile_step())
        self.wizard_stack.addWidget(self._build_wizard_output_step())
        self.wizard_stack.addWidget(self._build_wizard_review_step())
        layout.addLayout(content, 1)
        nav = QHBoxLayout()
        self.wizard_back = QPushButton("Back")
        self.wizard_back.clicked.connect(lambda: self.change_wizard_step(-1))
        self.wizard_next = QPushButton("Next")
        self.wizard_next.setProperty("primary", True)
        self.wizard_next.clicked.connect(lambda: self.change_wizard_step(1))
        nav.addStretch(1)
        nav.addWidget(self.wizard_back)
        nav.addWidget(self.wizard_next)
        layout.addLayout(nav)
        self._refresh_wizard_navigation()
        return page

    def _step_panel(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 4, 18, 4)
        title_label = QLabel(title)
        title_label.setProperty("sectionTitle", True)
        layout.addWidget(title_label)
        subtitle_label = QLabel(subtitle)
        subtitle_label.setWordWrap(True)
        subtitle_label.setProperty("muted", True)
        layout.addWidget(subtitle_label)
        return panel, layout

    def _build_wizard_task_step(self) -> QWidget:
        panel, layout = self._step_panel("What do you want to do?", "This choice affects only the current review.")
        form = QFormLayout()
        self.workflow_selector = WheelSafeComboBox()
        for workflow in WORKFLOWS:
            if workflow.number == WORKFLOW_REVIEW_NEW_VIDEOS:
                continue
            self.workflow_selector.addItem(workflow.display_name, workflow.number)
        self.workflow_selector.currentIndexChanged.connect(
            lambda: self.set_current_workflow(str(self.workflow_selector.currentData() or DEFAULT_WORKFLOW))
        )
        form.addRow("Current review task", self.workflow_selector)
        layout.addLayout(form)
        self.workflow_description = QLabel()
        self.workflow_description.setWordWrap(True)
        description_card = _card()
        description_layout = QVBoxLayout(description_card)
        description_layout.addWidget(self.workflow_description)
        self.workflow_source_support = QLabel()
        self.workflow_source_support.setProperty("accent", True)
        description_layout.addWidget(self.workflow_source_support)
        layout.addWidget(description_card)
        layout.addStretch(1)
        return panel

    def _build_wizard_source_step(self) -> QWidget:
        panel, layout = self._step_panel("Select source", "Original media is read-only. Review output is written separately.")
        form = QFormLayout()
        self.source_kind_combo = WheelSafeComboBox()
        self.source_kind_combo.currentIndexChanged.connect(self._source_kind_changed)
        form.addRow("Source type", self.source_kind_combo)
        source_row = QWidget()
        source_row_layout = QHBoxLayout(source_row)
        source_row_layout.setContentsMargins(0, 0, 0, 0)
        self.source_input_stack = QStackedWidget()
        self.input_path_edit = QLineEdit()
        self.input_path_edit.setPlaceholderText("Choose one local file or folder")
        self.input_path_edit.textChanged.connect(self._source_changed)
        self.url_input_edit = QPlainTextEdit()
        self.url_input_edit.setPlaceholderText(
            "Paste one or more web-video URLs here, one per line"
        )
        ui_theme.keep_scaled(self.url_input_edit, "setMinimumHeight", 120)
        ui_theme.keep_scaled(self.url_input_edit, "setMaximumHeight", 190)
        self.url_input_edit.textChanged.connect(self._source_changed)
        self.source_input_stack.addWidget(self.input_path_edit)
        self.source_input_stack.addWidget(self.url_input_edit)
        self.browse_file_button = QPushButton("File")
        self.browse_file_button.clicked.connect(self.browse_input_file)
        self.browse_folder_button = QPushButton("Folder")
        self.browse_folder_button.clicked.connect(self.browse_input_folder)
        source_row_layout.addWidget(self.source_input_stack, 1)
        source_row_layout.addWidget(self.browse_file_button)
        source_row_layout.addWidget(self.browse_folder_button)
        form.addRow("Source", source_row)
        layout.addLayout(form)
        self.source_guidance = QLabel()
        self.source_guidance.setWordWrap(True)
        self.source_guidance.setProperty("muted", True)
        layout.addWidget(self.source_guidance)
        self.source_discovery_status = QLabel("Choose a source to discover supported recordings.")
        self.source_discovery_status.setWordWrap(True)
        self.source_discovery_status.setObjectName("sourceDiscoveryStatus")
        self.source_discovery_status.setProperty("operatorState", "pending")
        self.source_discovery_status.setAccessibleName("Source discovery status")
        layout.addWidget(self.source_discovery_status)
        self.audio_stream_panel = QGroupBox("Operator narration audio")
        audio_layout = QVBoxLayout(self.audio_stream_panel)
        mode_label = QLabel("Selection mode: Auto-detect and confirm")
        mode_label.setProperty("accent", True)
        audio_layout.addWidget(mode_label)
        self.audio_active_source_label = QLabel("Selected source: no source selected")
        self.audio_active_source_label.setWordWrap(False)
        self.audio_active_source_label.setProperty("sectionTitle", True)
        # 237: its fixed height grows with the text size, so the line is never cut off.
        ui_theme.keep_scaled(self.audio_active_source_label, "setMinimumHeight", 26)
        ui_theme.keep_scaled(self.audio_active_source_label, "setMaximumHeight", 26)
        self.audio_active_source_label.setAccessibleName("Source controlled by narration track choices")
        audio_layout.addWidget(self.audio_active_source_label)
        audio_row = QGridLayout()
        self.audio_stream_combo = WheelSafeComboBox()
        self.audio_stream_combo.addItem("Inspect a source file to list streams", -1)
        self.audio_stream_combo.setAccessibleName("Selected narration track for the active source")
        self.audio_stream_combo.currentIndexChanged.connect(self._audio_stream_selected)
        self.inspect_audio_streams_button = QPushButton("Inspect source files")
        self.inspect_audio_streams_button.setProperty("primary", True)
        self.inspect_audio_streams_button.setAccessibleName("Inspect selected source files")
        self.inspect_audio_streams_button.clicked.connect(self.inspect_source_audio_streams)
        self.cancel_audio_inspection_button = QPushButton("Cancel inspection")
        self.cancel_audio_inspection_button.clicked.connect(self.cancel_audio_inspection)
        self.cancel_audio_inspection_button.setVisible(False)
        audio_row.addWidget(self.audio_stream_combo, 0, 0, 1, 2)
        audio_row.addWidget(self.inspect_audio_streams_button, 1, 0)
        audio_row.addWidget(self.cancel_audio_inspection_button, 1, 1)
        audio_row.setColumnStretch(0, 1)
        audio_row.setColumnStretch(1, 1)
        audio_layout.addLayout(audio_row)
        inspection_explanation = QLabel(
            "Inspection reads audio-track metadata and short local samples to recommend the microphone track. "
            "It does not change the recordings."
        )
        inspection_explanation.setWordWrap(True)
        inspection_explanation.setProperty("muted", True)
        audio_layout.addWidget(inspection_explanation)
        self.audio_inspection_progress = QProgressBar()
        self.audio_inspection_progress.setRange(0, 1)
        self.audio_inspection_progress.setValue(0)
        self.audio_inspection_progress.setFormat("Audio inspection not started")
        self.audio_inspection_progress.setAccessibleName("Audio inspection progress")
        # 237: while the inspection runs, a job banner shows it beside Inspect source files; the bar
        # below keeps the result once it is done.
        self.audio_inspection_banner = JobBanner()
        self.audio_inspection_banner.setObjectName("audioInspectionBanner")
        self.audio_inspection_banner.set_link_visible(False)
        audio_layout.addWidget(self.audio_inspection_banner)
        self.audio_inspection_progress.valueChanged.connect(lambda _value: self._show_inspection_banner())
        audio_layout.addWidget(self.audio_inspection_progress)
        action_row = QGridLayout()
        self.preview_audio_stream_button = QPushButton("Preview track")
        self.preview_audio_stream_button.clicked.connect(self.preview_selected_audio_stream)
        self.confirm_audio_stream_button = QPushButton("Confirm microphone")
        self.confirm_audio_stream_button.clicked.connect(self.confirm_selected_audio_stream)
        self.confirm_matching_layouts_button = QPushButton("Confirm matching sources")
        self.confirm_matching_layouts_button.clicked.connect(self.confirm_all_matching_layouts)
        action_row.addWidget(self.preview_audio_stream_button, 0, 0)
        action_row.addWidget(self.confirm_audio_stream_button, 0, 1)
        action_row.addWidget(self.confirm_matching_layouts_button, 1, 0, 1, 2)
        action_row.setColumnStretch(0, 1)
        action_row.setColumnStretch(1, 1)
        audio_layout.addLayout(action_row)
        self.audio_preview_identity = QLabel("Previewing: no source or track loaded")
        self.audio_preview_identity.setObjectName("audioPreviewIdentity")
        self.audio_preview_identity.setProperty("operatorState", "pending")
        self.audio_preview_identity.setWordWrap(False)
        ui_theme.keep_scaled(self.audio_preview_identity, "setMinimumHeight", 30)
        ui_theme.keep_scaled(self.audio_preview_identity, "setMaximumHeight", 30)
        self.audio_preview_identity.setAccessibleName("Preview source and narration track")
        audio_layout.addWidget(self.audio_preview_identity)
        # 136 (Wave 8): Preview track plays in the shared built-in player, which has its own transport,
        # waveforms and volume; the region chosen here is where it starts.
        preview_row = QGridLayout()
        self.audio_preview_region_combo = WheelSafeComboBox()
        self.audio_preview_region_combo.addItem("Speech-dense region 1", 0)
        self.audio_preview_region_combo.setToolTip("Where Preview track starts playing in the built-in player.")
        preview_row.addWidget(QLabel("Preview region"), 0, 0)
        preview_row.addWidget(self.audio_preview_region_combo, 0, 1, 1, 3)
        preview_row.setColumnStretch(1, 1)
        audio_layout.addLayout(preview_row)
        self.preview_audio_stream_button.setToolTip(
            "Opens the built-in player on this track at the preview region and plays it."
        )
        enrollment_row = QGridLayout()
        self.voice_enrollment_status = QLabel("Optional local voice enrollment: not enrolled")
        self.voice_enrollment_status.setWordWrap(True)
        self.voice_enrollment_button = QPushButton("Choose voice sample")
        self.voice_enrollment_button.clicked.connect(self.select_voice_enrollment_sample)
        self.clear_voice_enrollment_button = QPushButton("Clear enrollment")
        self.clear_voice_enrollment_button.clicked.connect(self.clear_voice_enrollment)
        if self.voice_enrollment_store.load():
            self.voice_enrollment_status.setText(
                "Optional local voice enrollment is active (local ranking only; never exported)."
            )
        enrollment_row.addWidget(self.voice_enrollment_status, 0, 0, 1, 2)
        enrollment_row.addWidget(self.voice_enrollment_button, 1, 0)
        enrollment_row.addWidget(self.clear_voice_enrollment_button, 1, 1)
        enrollment_row.setColumnStretch(0, 1)
        enrollment_row.setColumnStretch(1, 1)
        audio_layout.addLayout(enrollment_row)
        self.audio_results_group = QGroupBox("Source files and narration status")
        results_layout = QVBoxLayout(self.audio_results_group)
        self.audio_batch_table = QTableWidget(0, 3)
        self.audio_batch_table.setHorizontalHeaderLabels(
            (
                "Source file",
                "Recommendation",
                "Status",
            )
        )
        self.audio_batch_table.setAccessibleName("Narration selection status for every source file")
        make_columns_resizable(self.audio_batch_table, widths={0: 360, 1: 220})
        self.audio_batch_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.audio_batch_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        ui_theme.keep_scaled(self.audio_batch_table, "setMinimumHeight", 118)
        ui_theme.keep_scaled(self.audio_batch_table, "setMaximumHeight", 160)
        self.audio_batch_table.itemSelectionChanged.connect(self._audio_batch_row_selected)
        results_layout.addWidget(self.audio_batch_table)
        # Every cell of a row carries the source as item data. A web address
        # resolves to nothing, so no Play entry is offered for it. This table
        # never had a double-click of its own, so double-click plays (125).
        self.video_opener.attach(
            self.audio_batch_table,
            path_role_resolver(),
            sequence=True,
            label="New review sources",
        )
        self.audio_selected_source_details = QLabel(
            "Select a source row after inspection to review its recommendation, selection, reason, and confirmation."
        )
        self.audio_selected_source_details.setWordWrap(True)
        ui_theme.keep_scaled(self.audio_selected_source_details, "setMinimumHeight", 76)
        self.audio_selected_source_details.setAccessibleName("Selected source narration details")
        results_layout.addWidget(self.audio_selected_source_details)
        audio_layout.addWidget(self.audio_results_group)
        self.audio_stream_status = QLabel(
            "Inspect every source. A recommendation is not confirmation; only a confirmed narration track can start review."
        )
        self.audio_stream_status.setWordWrap(True)
        self.audio_stream_status.setProperty("muted", True)
        audio_layout.addWidget(self.audio_stream_status)
        self.audio_technical_details_group = QGroupBox("Technical audio details")
        self.audio_technical_details_group.setCheckable(True)
        self.audio_technical_details_group.setChecked(False)
        audio_technical_layout = QVBoxLayout(self.audio_technical_details_group)
        self.audio_technical_details = QLabel(
            "Inspect a source to view internal stream mappings and recording-layout details."
        )
        self.audio_technical_details.setWordWrap(True)
        self.audio_technical_details.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.audio_technical_details.setVisible(False)
        self.audio_technical_details_group.toggled.connect(
            self.audio_technical_details.setVisible
        )
        audio_technical_layout.addWidget(self.audio_technical_details)
        audio_layout.addWidget(self.audio_technical_details_group)
        narration_help = QPushButton("Narration help")
        narration_help.clicked.connect(
            lambda checked=False: self.open_workflow_help(WORKFLOW_CODEX_EVIDENCE)
        )
        audio_layout.addWidget(
            narration_help,
            alignment=Qt.AlignmentFlag.AlignLeft,
        )
        layout.addWidget(self.audio_stream_panel)
        layout.addStretch(1)
        scroll = QScrollArea()
        self.source_scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(panel)
        return scroll

    def _build_wizard_profile_step(self) -> QWidget:
        panel, layout = self._step_panel(
            "Review options",
            "Recommended settings are ready to use. Choose an optional preset only when its plain-language purpose matches this review.",
        )
        profile_card = _card()
        profile_layout = QVBoxLayout(profile_card)
        selector_row = QGridLayout()
        self.profile_selector = WheelSafeComboBox()
        self.profile_selector.currentTextChanged.connect(self._profile_selector_changed)
        selector_row.addWidget(self.profile_selector, 0, 0, 1, 2)
        edit_button = QPushButton("Customize")
        edit_button.clicked.connect(self.edit_current_profile)
        save_as_button = QPushButton("Save as new")
        save_as_button.clicked.connect(self.save_profile_as)
        reset_button = QPushButton("Use recommended settings")
        reset_button.clicked.connect(lambda: self.use_recommended_settings(self.current_workflow))
        selector_row.addWidget(edit_button, 1, 0)
        selector_row.addWidget(save_as_button, 1, 1)
        selector_row.addWidget(reset_button, 2, 0, 1, 2)
        selector_row.setColumnStretch(0, 1)
        selector_row.setColumnStretch(1, 1)
        profile_layout.addLayout(selector_row)
        self.profile_state_label = QLabel("Recommended settings — no preset required")
        self.profile_state_label.setProperty("muted", True)
        profile_layout.addWidget(self.profile_state_label)
        layout.addWidget(profile_card)

        self.basic_settings_stack = QStackedWidget()
        self.basic_workflow_pages: dict[str, QWidget] = {}
        for workflow in ALL_WORKFLOWS:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            inner = QWidget()
            form = QFormLayout(inner)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            for key in BASIC_WORKFLOW_SETTINGS[workflow]:
                meta = METADATA_BY_KEY[key]
                control = _make_setting_control(meta, inner)
                self.run_setting_controls[key] = control
                _connect_control(control, lambda key=key: self._run_setting_changed(key))
                form.addRow(meta.display_label, control)
            if workflow == WORKFLOW_CODEX_EVIDENCE:
                self.sampling_estimate_label = QLabel()
                self.sampling_estimate_label.setWordWrap(True)
                self.sampling_estimate_label.setProperty("muted", True)
                form.addRow("Effective estimate", self.sampling_estimate_label)
            advanced = QPushButton("Advanced")
            advanced.setToolTip("Advanced settings")
            advanced.clicked.connect(self.open_advanced_settings)
            form.addRow("", advanced)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            scroll.setWidget(inner)
            self.basic_workflow_pages[workflow] = scroll
            self.basic_settings_stack.addWidget(scroll)
        layout.addWidget(self.basic_settings_stack, 1)
        return panel

    def _build_wizard_output_step(self) -> QWidget:
        panel, layout = self._step_panel(
            "Choose output",
            "Final packages go here. Temporary working files stay separate and are managed under Settings.",
        )
        form = QFormLayout()
        output_row = QWidget()
        output_row_layout = QVBoxLayout(output_row)
        output_row_layout.setContentsMargins(0, 0, 0, 0)
        field_row = QHBoxLayout()
        self.output_path_edit = QLineEdit()
        self.output_path_edit.textChanged.connect(self._output_changed)
        browse = QPushButton("Browse")
        browse.clicked.connect(self.browse_output_folder)
        field_row.addWidget(self.output_path_edit, 1)
        field_row.addWidget(browse)
        output_row_layout.addLayout(field_row)
        # 223: why the folder is refused, where it is chosen, in the one output-folder rule's own words.
        self.output_folder_problem_label = QLabel("")
        self.output_folder_problem_label.setWordWrap(True)
        self.output_folder_problem_label.setObjectName("outputFolderProblem")
        self.output_folder_problem_label.setAccessibleName("Output folder problem")
        self.output_folder_problem_label.setProperty("operatorState", "error")
        self.output_folder_problem_label.setVisible(False)
        output_row_layout.addWidget(self.output_folder_problem_label)
        form.addRow("Output folder", output_row)
        self.recent_output_combo = WheelSafeComboBox()
        self.recent_output_combo.currentIndexChanged.connect(self._recent_output_selected)
        form.addRow("Recent folders", self.recent_output_combo)
        self.open_output_checkbox = QCheckBox("Open output when done")
        self.open_output_checkbox.toggled.connect(self._output_changed)
        form.addRow("", self.open_output_checkbox)
        layout.addLayout(form)
        privacy = QLabel(
            "Private recordings, transcripts, frames, local paths, and ticket drafts remain in the selected local output. "
            "The Workbench does not create GitHub issues or upload evidence."
        )
        privacy.setWordWrap(True)
        privacy.setProperty("accent", True)
        layout.addWidget(privacy)
        layout.addStretch(1)
        return panel

    def _build_wizard_review_step(self) -> QWidget:
        panel, layout = self._step_panel("Review and run", "Confirm the task in ordinary language before processing starts.")
        self.review_summary = QTextBrowser()
        self.review_summary.setOpenExternalLinks(False)
        layout.addWidget(self.review_summary, 1)
        self.review_blocker_panel = QFrame()
        self.review_blocker_panel.setObjectName("reviewBlockerPanel")
        self.review_blocker_panel.setProperty("operatorState", "attention")
        blocker_layout = QVBoxLayout(self.review_blocker_panel)
        self.review_blocker_heading = QLabel("⚠ ACTION REQUIRED")
        self.review_blocker_heading.setProperty("sectionTitle", True)
        blocker_layout.addWidget(self.review_blocker_heading)
        self.run_warning_label = QLabel()
        self.run_warning_label.setWordWrap(True)
        blocker_layout.addWidget(self.run_warning_label)
        self.resolve_narration_button = QPushButton("Review and confirm narration tracks")
        self.resolve_narration_button.setProperty("operatorAction", "attention")
        self.resolve_narration_button.clicked.connect(self.review_and_confirm_narration_tracks)
        self.resolve_narration_button.setVisible(False)
        blocker_layout.addWidget(
            self.resolve_narration_button,
            alignment=Qt.AlignmentFlag.AlignLeft,
        )
        self.resolve_dependencies_button = QPushButton("Open dependency setup")
        self.resolve_dependencies_button.clicked.connect(self.open_dependency_setup)
        self.resolve_dependencies_button.setVisible(False)
        blocker_layout.addWidget(
            self.resolve_dependencies_button,
            alignment=Qt.AlignmentFlag.AlignLeft,
        )
        self.review_blocker_panel.setVisible(False)
        layout.addWidget(self.review_blocker_panel)
        self.technical_toggle = QToolButton()
        self.technical_toggle.setText("Technical details")
        self.technical_toggle.setCheckable(True)
        self.technical_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.technical_toggle.toggled.connect(self._toggle_technical_details)
        layout.addWidget(self.technical_toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        self.technical_panel = _card()
        technical_layout = QVBoxLayout(self.technical_panel)
        self.command_preview = QPlainTextEdit()
        self.command_preview.setReadOnly(True)
        ui_theme.keep_scaled(self.command_preview, "setMaximumHeight", 110)
        technical_layout.addWidget(self.command_preview)
        technical_buttons = QGridLayout()
        copy_button = QPushButton("Copy command")
        open_log = QPushButton("Open log")
        diagnostics = QPushButton("Open diagnostics")
        diagnostics.clicked.connect(lambda: self.navigate("Settings"))
        terminal = QPushButton("Open terminal")
        technical_buttons.addWidget(copy_button, 0, 0)
        technical_buttons.addWidget(open_log, 0, 1)
        technical_buttons.addWidget(diagnostics, 1, 0)
        technical_buttons.addWidget(terminal, 1, 1)
        technical_buttons.setColumnStretch(0, 1)
        technical_buttons.setColumnStretch(1, 1)
        technical_layout.addLayout(technical_buttons)
        # 237: one line under the technical buttons says what the last one did.
        technical_feedback = InlineFeedback()
        technical_feedback.setObjectName("technicalFeedback")
        technical_layout.addWidget(technical_feedback)
        for button, action, working, done in (
            (copy_button, self.copy_command, "Copying…", "Command copied"),
            (open_log, self.open_current_log, "Opening…", "Opened"),
            (terminal, self.open_diagnostic_terminal, "Opening…", "Terminal opened"),
        ):
            bind_action(button, action, working=working, done=done, feedback=technical_feedback)
        self.technical_panel.setVisible(False)
        layout.addWidget(self.technical_panel)
        self.start_review_button = QPushButton("Start review")
        self.start_review_button.setProperty("operatorAction", "ready")
        layout.addWidget(self.start_review_button, alignment=Qt.AlignmentFlag.AlignRight)
        bind_action(self.start_review_button, self._start_review_action, working="Starting…", done="Started")
        # 237: the review this page started, until it is done; Start review also opens Queue / Progress.
        self.new_review_job_banner = self.make_job_banner("New Review")
        layout.addWidget(self.new_review_job_banner)
        return panel

    def _start_review_action(self) -> Outcome:
        running_before = self.runner_thread is not None
        self.start_job()
        if self.runner_thread is not None and not running_before:
            return Outcome.done("Started; it shows on Queue / Progress")
        # A refusal ("Review is not ready") is said in its own dialog.
        return Outcome.quiet()

    def _wizard_step_selected(self, row: int) -> None:
        if 0 <= row < self.wizard_stack.count():
            self.wizard_stack.setCurrentIndex(row)
            if row == 4:
                self.refresh_review_summary()
        self._refresh_wizard_navigation()

    def change_wizard_step(self, delta: int) -> None:
        index = max(0, min(self.wizard_stack.count() - 1, self.wizard_stack.currentIndex() + delta))
        self.wizard_steps.setCurrentRow(index)

    def _refresh_wizard_navigation(self) -> None:
        if not hasattr(self, "wizard_stack"):
            return
        index = self.wizard_stack.currentIndex()
        self.wizard_back.setEnabled(index > 0)
        self.wizard_next.setVisible(index < self.wizard_stack.count() - 1)
        next_labels = ("Source", "Review options", "Output", "Review and run")
        if index < len(next_labels):
            self.wizard_next.setText(f"Next: {next_labels[index]}")
        can_continue = True
        blocked_reason = ""
        if index == 1:
            source = str(self.run_settings.get("input_path") or "").strip()
            if not source:
                can_continue = False
                blocked_reason = "Choose a source before continuing."
            elif self.current_workflow == WORKFLOW_CODEX_EVIDENCE and self._unresolved_audio_source_keys():
                count = len(self._unresolved_audio_source_keys())
                attention_verb = "needs" if count == 1 else "need"
                self.wizard_next.setText(
                    f"Next: Review options — {count} source{'s' if count != 1 else ''} {attention_verb} attention"
                )
        elif index == 3:
            output_value = str(self.run_settings.get("output_folder") or "").strip()
            output_problem = self._output_folder_problem()
            if self.current_workflow != WORKFLOW_REVIEW_NEW_VIDEOS and not output_value:
                can_continue = False
                blocked_reason = "Choose an output folder before continuing."
            elif output_problem:
                can_continue = False
                blocked_reason = output_problem
        self.wizard_next.setEnabled(can_continue)
        self.wizard_next.setToolTip(blocked_reason or f"Continue to {next_labels[index] if index < len(next_labels) else 'the next step'}.")
        self._refresh_wizard_step_states()

    def _output_folder_problem(self) -> str:
        """211: why the folder this run writes to cannot be used, by the one shared rule, or ""."""

        if self.current_workflow == WORKFLOW_REVIEW_NEW_VIDEOS:
            return temporary_folder_problem(review_evidence_root(self._with_main_folders(self.run_settings)), "evidence folder")
        return temporary_folder_problem(str(self.run_settings.get("output_folder") or "").strip())

    def _refresh_wizard_step_states(self, *, errors: list[str] | None = None) -> None:
        if not hasattr(self, "wizard_steps"):
            return
        source = str(self.run_settings.get("input_path") or "").strip()
        output = str(self.run_settings.get("output_folder") or "").strip()
        unresolved = (
            self._unresolved_audio_source_keys()
            if self.current_workflow == WORKFLOW_CODEX_EVIDENCE and source
            else []
        )
        if errors is None:
            errors = self.validate_current_run()
        output_problem = self._output_folder_problem()
        problem_label = getattr(self, "output_folder_problem_label", None)
        if problem_label is not None:
            problem_label.setText(output_problem)
            problem_label.setVisible(bool(output_problem))
        source_state = "not_started"
        if source:
            if self.audio_inspection_thread is not None:
                source_state = "attention"
            elif unresolved:
                source_state = "attention"
            else:
                source_state = "complete"
        states = [
            "complete",
            source_state,
            "complete",
            # 211: the same rule the run applies, so the badge never says Complete for a folder
            # the run then refuses.
            "blocked" if output_problem else (
                "complete" if output or self.current_workflow == WORKFLOW_REVIEW_NEW_VIDEOS else "not_started"),
            "complete" if not errors else ("attention" if unresolved else "blocked"),
        ]
        names = ("Task", "Source", "Review options", "Output", "Review and run")
        icon_for = {
            "not_started": "○",
            "complete": "✓",
            "attention": "⚠",
            "blocked": "✕",
        }
        text_for = {
            "not_started": "Not started",
            "complete": "Complete",
            "attention": "Action required",
            "blocked": "Blocked",
        }
        current = self.wizard_stack.currentIndex()
        with QSignalBlocker(self.wizard_steps):
            for index, (name, state) in enumerate(zip(names, states, strict=True)):
                item = self.wizard_steps.item(index)
                if item is None:
                    continue
                if index == current:
                    item.setText(
                        f"▶ {index + 1}  {name}\n   Current · {text_for[state]}"
                    )
                else:
                    item.setText(
                        f"{icon_for[state]} {index + 1}  {name}\n   {text_for[state]}"
                    )
                item.setData(Qt.ItemDataRole.UserRole, state)
                item.setToolTip(f"Step {index + 1}: {name}. Status: {text_for[state]}.")

    def _toggle_technical_details(self, checked: bool) -> None:
        self.technical_toggle.setArrowType(
            Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
        )
        self.technical_panel.setVisible(checked)

    def set_current_workflow(self, workflow: str) -> None:
        workflow = normalize_workflow(workflow)
        if self.current_workflow == workflow and not self._loading:
            self._refresh_workflow_surfaces()
            return
        self.current_workflow = workflow
        if self.current_profile_metadata is not None and self.current_profile_metadata.workflow != workflow:
            self.current_profile = ""
            self.current_profile_metadata = None
            self.profile_baseline = {}
        if workflow != WORKFLOW_REVIEW_NEW_VIDEOS:
            self.review_inbox_last_standard_workflow = workflow
        self._refresh_workflow_surfaces()
        self._update_profile_dirty_state()

    def _refresh_workflow_surfaces(self) -> None:
        if not hasattr(self, "workflow_selector"):
            return
        with QSignalBlocker(self.workflow_selector):
            index = self.workflow_selector.findData(self.current_workflow)
            if index >= 0:
                self.workflow_selector.setCurrentIndex(index)
        workflow = WORKFLOW_BY_NUMBER[self.current_workflow]
        self.workflow_description.setText(WORKFLOW_PURPOSES[self.current_workflow])
        self.workflow_source_support.setText(WORKFLOW_SOURCE_LABELS[self.current_workflow])
        self.basic_settings_stack.setCurrentWidget(self.basic_workflow_pages[self.current_workflow])
        self.refresh_profile_selector()
        self._refresh_source_kind_options()
        self.refresh_sampling_estimate()
        self.refresh_review_summary()

    def _refresh_source_kind_options(self) -> None:
        if not hasattr(self, "source_kind_combo"):
            return
        previous = str(self.run_settings.get("input_kind") or "local")
        with QSignalBlocker(self.source_kind_combo):
            self.source_kind_combo.clear()
            if self.current_workflow == WORKFLOW_FULL_REVIEW:
                self.source_kind_combo.addItem("Local file or folder", "local")
                self.source_kind_combo.addItem("URL", "url")
            elif self.current_workflow == WORKFLOW_ARCHIVE_CATALOG:
                self.source_kind_combo.addItem("Local folder or catalog", "local")
            elif self.current_workflow == WORKFLOW_REVIEW_NEW_VIDEOS:
                self.source_kind_combo.addItem("Configured recording folders", "configured")
            else:
                self.source_kind_combo.addItem("Local file or folder", "local")
            index = self.source_kind_combo.findData(previous)
            self.source_kind_combo.setCurrentIndex(max(index, 0))
        self.run_settings["input_kind"] = self.source_kind_combo.currentData()
        self._refresh_source_guidance()

    def _source_kind_changed(self) -> None:
        if self._loading:
            return
        kind = str(self.source_kind_combo.currentData() or "local")
        previous = str(self.run_settings.get("input_path") or "")
        self.run_settings["input_kind"] = kind
        if kind == "url" and _looks_like_url(previous) and not self.url_input_edit.toPlainText().strip():
            with QSignalBlocker(self.url_input_edit):
                self.url_input_edit.setPlainText(previous)
        elif kind != "url" and previous and not _looks_like_url(previous) and not self.input_path_edit.text().strip():
            with QSignalBlocker(self.input_path_edit):
                self.input_path_edit.setText(previous)
        self.run_settings["input_path"] = self._active_source_text()
        self._refresh_source_guidance()
        self._refresh_source_discovery()
        self.refresh_review_summary()
        self._refresh_wizard_navigation()

    def _active_source_text(self) -> str:
        if str(self.run_settings.get("input_kind") or "local") == "url":
            return self.url_input_edit.toPlainText().strip()
        return self.input_path_edit.text().strip()

    @staticmethod
    def _display_source_name(source_key: str, *, max_chars: int = 68) -> str:
        name = Path(source_key).name if source_key else "no source selected"
        if len(name) <= max_chars:
            return name
        left = max(12, (max_chars - 3) // 2)
        right = max(12, max_chars - 3 - left)
        return f"{name[:left]}…{name[-right:]}"

    def _set_operator_state(self, widget: QWidget, state: str) -> None:
        widget.setProperty("operatorState", state)
        # 224 (Wave B2a, 5d): the shared re-style, so a box style given now keeps its inner margin.
        repolish(widget)

    def _refresh_source_discovery(self) -> None:
        if not hasattr(self, "source_discovery_status"):
            return
        source_text = str(self.run_settings.get("input_path") or "").strip()
        if str(self.run_settings.get("input_kind") or "local") == "url":
            urls, invalid = _parse_url_lines(source_text)
            self.audio_expected_sources = []
            self.inspect_audio_streams_button.setText("Local audio inspection only")
            self.inspect_audio_streams_button.setEnabled(False)
            if invalid:
                self.source_discovery_status.setText(
                    f"⚠ Found {len(urls)} valid URL(s) and {len(invalid)} line(s) that are not complete URLs."
                )
                self._set_operator_state(self.source_discovery_status, "attention")
            elif urls:
                noun = "web video" if len(urls) == 1 else "web videos"
                self.source_discovery_status.setText(
                    f"✓ {len(urls)} {noun} queued in pasted order. Duplicates are removed automatically."
                )
                self._set_operator_state(self.source_discovery_status, "ready")
            else:
                self.source_discovery_status.setText("○ Paste one or more complete URLs, one per line.")
                self._set_operator_state(self.source_discovery_status, "pending")
            self._refresh_audio_batch_table()
            return
        source = Path(source_text) if source_text else None
        sources = discover_media_files(source) if source is not None and source.exists() else []
        self.audio_expected_sources = [str(item.resolve()) for item in sources]
        count = len(sources)
        if count:
            noun = "source file" if count == 1 else "source files"
            self.source_discovery_status.setText(
                f"✓ Found {count} supported {noun}. Next: inspect {count} {noun} to identify the microphone narration track."
            )
            self._set_operator_state(self.source_discovery_status, "ready")
            self.inspect_audio_streams_button.setText(f"Inspect {count} {noun}")
            self.inspect_audio_streams_button.setEnabled(self.audio_inspection_thread is None)
        elif source is not None and source.exists():
            self.source_discovery_status.setText(
                "✕ No supported local video files were found in this source. Choose a supported recording or folder."
            )
            self._set_operator_state(self.source_discovery_status, "error")
            self.inspect_audio_streams_button.setText("Inspect source files")
            self.inspect_audio_streams_button.setEnabled(False)
        else:
            self.source_discovery_status.setText("○ Choose a source to discover supported recordings.")
            self._set_operator_state(self.source_discovery_status, "pending")
            self.inspect_audio_streams_button.setText("Inspect source files")
            self.inspect_audio_streams_button.setEnabled(False)
        self._refresh_audio_batch_table()

    def _refresh_source_guidance(self) -> None:
        kind = str(self.source_kind_combo.currentData() or "local")
        if self.current_workflow == WORKFLOW_REVIEW_NEW_VIDEOS:
            text = "Recording folders are configured with the selected profile or under advanced settings."
        elif self.current_workflow == WORKFLOW_ARCHIVE_CATALOG:
            text = "Build mode uses a source folder; search mode uses the configured catalog and search terms."
        elif kind == "url":
            text = (
                "Paste one or more supported web-video URLs, one per line. Full Review processes the queue "
                "sequentially; no 'done' line is needed. AI / Ticket Evidence remains local-source only."
            )
        else:
            text = "Choose a local media file or folder. The source is never modified or deleted."
        self.source_guidance.setText(text)
        is_url = kind == "url"
        self.source_input_stack.setCurrentWidget(self.url_input_edit if is_url else self.input_path_edit)
        self.browse_file_button.setVisible(not is_url)
        self.browse_folder_button.setVisible(not is_url)
        if hasattr(self, "audio_stream_panel"):
            self.audio_stream_panel.setVisible(
                self.current_workflow in {WORKFLOW_CODEX_EVIDENCE, WORKFLOW_REVIEW_NEW_VIDEOS}
            )

    def _audio_stream_selected(self) -> None:
        if self._loading:
            return
        ordinal = self.audio_stream_combo.currentData()
        inspection = self.audio_inspections.get(self.active_audio_source)
        if not inspection or not isinstance(ordinal, int) or ordinal < 0:
            return
        self._cancel_audio_previews()
        inspection.selected_ordinal = ordinal
        if inspection.confirmation_state != "single-stream":
            inspection.confirmation_state = "unresolved"
            inspection.confirmation_source = (
                "heuristic recommendation"
                if inspection.recommendation
                and inspection.recommendation.stream.ordinal == ordinal
                else "unresolved"
            )
        stream = next(item for item in inspection.streams if item.ordinal == ordinal)
        self.audio_stream_status.setText(
            f"{stream.human_label} is selected but not confirmed. Preview it, then confirm it only if it contains your microphone narration."
        )
        self._populate_audio_preview_regions()
        self._refresh_preview_identity()
        self._sync_audio_selection_settings()
        self._refresh_audio_batch_table()
        self._refresh_audio_resolution_progress()
        self.refresh_review_summary()
        self._refresh_wizard_navigation()
        if self.current_workflow == WORKFLOW_REVIEW_NEW_VIDEOS:
            self._refresh_review_inbox_dashboard()

    def inspect_source_audio_streams(self) -> None:
        if self.audio_inspection_thread is not None:
            self.audio_stream_status.setText(
                "The previous inspection is still stopping. Start again when Inspect tracks is available."
            )
            return
        source_text = self.input_path_edit.text().strip()
        source = Path(source_text) if source_text else None
        if not source or not source.exists():
            self.audio_stream_status.setText("Choose a local media file or folder before inspecting audio tracks.")
            return
        if not self.resources.ffprobe_exe or not self.resources.ffmpeg_exe:
            self.audio_stream_status.setText("FFprobe and FFmpeg are required for local audio inspection.")
            return
        sources = discover_media_files(source)
        if not sources:
            self.audio_stream_status.setText("No supported local media files were found.")
            return
        self._start_audio_inspection_for_sources(sources)

    def _start_audio_inspection_for_sources(self, sources: list[Path]) -> None:
        """Start the shared exact-layout inspection for an explicit source queue."""

        if self.audio_inspection_thread is not None:
            self.audio_stream_status.setText(
                "The previous inspection is still stopping. Start again when Inspect tracks is available."
            )
            return
        if not self.resources.ffprobe_exe or not self.resources.ffmpeg_exe:
            self.audio_stream_status.setText("FFprobe and FFmpeg are required for local audio inspection.")
            return
        sources = [item for item in sources if item.is_file()]
        if not sources:
            self.audio_stream_status.setText("No supported local media files were found.")
            return
        self.audio_inspection_generation += 1
        generation = self.audio_inspection_generation
        self.audio_inspections.clear()
        self.audio_inspection_failures.clear()
        self.audio_expected_sources = [str(item.resolve()) for item in sources]
        self.active_audio_source = ""
        self._populate_audio_stream_combo()
        self._refresh_audio_batch_table()
        self._sync_audio_selection_settings()
        self.audio_inspection_progress.setRange(0, len(sources))
        self.audio_inspection_progress.setValue(0)
        self.audio_inspection_progress.setFormat(f"Preparing to inspect {len(sources)} file(s)…")
        self.audio_stream_status.setText(
            f"Preparing to inspect {len(sources)} file(s). You can keep using the Workbench or cancel safely."
        )
        self.inspect_audio_streams_button.setEnabled(False)
        self.cancel_audio_inspection_button.setVisible(True)
        thread = AudioInspectionThread(
            generation,
            sources,
            self.resources.ffprobe_exe,
            self.resources.ffmpeg_exe,
            Path(str(self.app_settings.get("temp_folder") or default_temp_folder())),
            self.voice_enrollment_store.load(),
        )
        thread.inspection_started.connect(self._audio_inspection_started)
        thread.inspection_ready.connect(self._audio_inspection_ready)
        thread.inspection_failed.connect(self._audio_inspection_failed)
        thread.batch_finished.connect(self._audio_inspection_batch_finished)
        thread.finished.connect(
            lambda worker=thread: self._audio_inspection_thread_stopped(worker)
        )
        self.audio_inspection_thread = thread
        thread.start()
        self._show_inspection_banner()
        self.refresh_review_summary()

    def cancel_audio_inspection(self) -> None:
        thread = self.audio_inspection_thread
        if thread is None:
            return
        thread.cancel()
        self.cancel_audio_inspection_button.setEnabled(False)
        self.audio_stream_status.setText(
            "Cancelling audio inspection… Results already completed will be kept."
        )
        self.audio_inspection_progress.setFormat("Cancelling safely…")

    def _audio_inspection_started(
        self, generation: int, source_index: int, total: int, source_name: str
    ) -> None:
        if generation != self.audio_inspection_generation:
            return
        self.audio_inspection_progress.setValue(source_index - 1)
        self.audio_inspection_progress.setFormat(
            f"Inspecting {source_index} of {total} files…"
        )
        self.audio_stream_status.setText(
            f"Inspecting {source_index} of {total} files: {source_name}. The Workbench remains available."
        )

    def _audio_inspection_ready(
        self,
        generation: int,
        source_index: int,
        total: int,
        source_key: str,
        inspection: SourceAudioInspection,
    ) -> None:
        if generation != self.audio_inspection_generation:
            return
        saved_layout = self.layout_confirmation_store.match(
            inspection.layout_fingerprint
        )
        apply_selection_precedence(
            inspection,
            saved_layout=saved_layout,
            preferred_track_number=self._preferred_narration_track_number(),
            confirmed_track=speech_facts.confirmed_track(source_key),
        )
        self.audio_inspections[source_key] = inspection
        self.audio_inspection_failures.pop(source_key, None)
        if not self.active_audio_source:
            self.active_audio_source = source_key
            self._populate_audio_stream_combo()
        self.audio_inspection_progress.setValue(source_index)
        self.audio_inspection_progress.setFormat(
            f"Inspected {source_index} of {total} files"
        )
        self._refresh_audio_batch_table()
        self._sync_audio_selection_settings()
        self.refresh_review_summary()
        if self.current_workflow == WORKFLOW_REVIEW_NEW_VIDEOS:
            self._refresh_review_inbox_dashboard()

    def _audio_inspection_failed(
        self,
        generation: int,
        source_index: int,
        total: int,
        source_key: str,
        details: str,
    ) -> None:
        if generation != self.audio_inspection_generation:
            return
        self.audio_inspection_failures[source_key] = details
        self.audio_inspection_progress.setValue(source_index)
        self.audio_inspection_progress.setFormat(
            f"Checked {source_index} of {total} files"
        )
        self._refresh_audio_batch_table()
        self.refresh_review_summary()
        if self.current_workflow == WORKFLOW_REVIEW_NEW_VIDEOS:
            self._refresh_review_inbox_dashboard()

    def _audio_inspection_batch_finished(
        self, generation: int, cancelled: bool
    ) -> None:
        if generation != self.audio_inspection_generation:
            return
        completed = len(self.audio_inspections)
        failed = len(self.audio_inspection_failures)
        unresolved = len(self._unresolved_audio_source_keys())
        if cancelled:
            self.audio_stream_status.setText(
                f"Inspection cancelled. Kept {completed} completed file result(s); "
                f"{unresolved} file(s) still need inspection or confirmation."
            )
            self.audio_inspection_progress.setFormat("Cancelled — completed results kept")
        elif failed:
            names = ", ".join(
                Path(item).name for item in self.audio_inspection_failures
            )
            self.audio_stream_status.setText(
                f"Inspection finished. {completed} file(s) completed; could not inspect {names}. "
                "Select a failed row for guidance, then retry after correcting the source or audio tools."
            )
            self.audio_inspection_progress.setFormat(
                f"Finished — {completed} completed, {failed} failed"
            )
        elif unresolved:
            self.audio_stream_status.setText(
                f"Inspected {completed} file(s); {unresolved} still require confirmation. "
                "Recommendations are advice and may be wrong when other voices or mixed audio are present."
            )
            self._refresh_audio_resolution_progress()
        else:
            self.audio_stream_status.setText(
                f"All {completed} file(s) resolved from an exact confirmed layout or a single audio stream."
            )
            self.audio_inspection_progress.setFormat("Finished — all files resolved")
        if completed or failed:
            self.source_scroll.ensureWidgetVisible(self.audio_results_group, 0, 36)
            self.audio_batch_table.setFocus(Qt.FocusReason.OtherFocusReason)
        self.refresh_review_summary()
        if self.current_workflow == WORKFLOW_REVIEW_NEW_VIDEOS:
            self._refresh_review_inbox_dashboard()

    def _audio_inspection_thread_stopped(
        self, worker: AudioInspectionThread
    ) -> None:
        worker.deleteLater()
        if self.audio_inspection_thread is not worker:
            return
        self.audio_inspection_thread = None
        self.inspect_audio_streams_button.setEnabled(bool(self.audio_expected_sources))
        self.cancel_audio_inspection_button.setEnabled(True)
        self.cancel_audio_inspection_button.setVisible(False)
        self.refresh_review_summary()
        self._refresh_wizard_navigation()
        if self.current_workflow == WORKFLOW_REVIEW_NEW_VIDEOS:
            self._refresh_review_inbox_dashboard()
        result = self.audio_inspection_progress.format().lower()
        self._show_inspection_banner(
            "cancelled" if "cancel" in result else
            "attention" if "failed" in result or "required" in result else "completed")

    def _preferred_narration_track_number(self) -> int:
        try:
            return max(
                0,
                int(self.run_settings.get("preferred_narration_track_number") or 0),
            )
        except (TypeError, ValueError):
            return 0

    def _current_audio_source_keys(self) -> list[str]:
        if self.current_workflow == WORKFLOW_REVIEW_NEW_VIDEOS and self.audio_expected_sources:
            return list(self.audio_expected_sources)
        source_text = str(self.run_settings.get("input_path") or "").strip()
        source = Path(source_text) if source_text else None
        if source is not None and source.exists():
            return [str(item.resolve()) for item in discover_media_files(source)]
        return list(self.audio_expected_sources)

    def _unresolved_audio_source_keys(self) -> list[str]:
        unresolved: list[str] = []
        for source_key in self._current_audio_source_keys():
            inspection = self.audio_inspections.get(source_key)
            if (
                source_key in self.audio_inspection_failures
                or inspection is None
                or not inspection.resolved
            ):
                unresolved.append(source_key)
        return unresolved

    def _refresh_audio_resolution_progress(self) -> None:
        """Keep the completed inspection banner in sync with operator choices."""
        source_keys = self._current_audio_source_keys()
        if not source_keys:
            source_keys = list(
                dict.fromkeys(
                    [*self.audio_inspections, *self.audio_inspection_failures]
                )
            )
        accounted_for = len(
            {
                source_key
                for source_key in source_keys
                if source_key in self.audio_inspections
                or source_key in self.audio_inspection_failures
            }
        )
        if not source_keys or accounted_for < len(source_keys):
            return
        failed = len(
            [
                source_key
                for source_key in source_keys
                if source_key in self.audio_inspection_failures
            ]
        )
        if failed:
            completed = len(
                [
                    source_key
                    for source_key in source_keys
                    if source_key in self.audio_inspections
                ]
            )
            self.audio_inspection_progress.setFormat(
                f"Finished — {completed} completed, {failed} failed"
            )
            return
        unresolved = len(self._unresolved_audio_source_keys())
        if unresolved:
            noun = "confirmation" if unresolved == 1 else "confirmations"
            self.audio_inspection_progress.setFormat(
                f"Finished — {unresolved} {noun} required"
            )
        else:
            self.audio_inspection_progress.setFormat("Finished — all files resolved")

    def _apply_profile_audio_preference(self) -> None:
        preferred_track = self._preferred_narration_track_number()
        for inspection in self.audio_inspections.values():
            if inspection.confirmation_state in {
                "operator-confirmed",
                "confirmed-recording",
                "confirmed-layout",
                "single-stream",
            }:
                continue
            apply_selection_precedence(
                inspection,
                preferred_track_number=preferred_track,
            )
        if self.active_audio_source:
            self._populate_audio_stream_combo()
        self._refresh_audio_batch_table()
        self._sync_audio_selection_settings()
        self._refresh_audio_resolution_progress()

    def _populate_audio_stream_combo(self) -> None:
        inspection = self.audio_inspections.get(self.active_audio_source)
        if hasattr(self, "audio_active_source_label"):
            source_name = self._display_source_name(self.active_audio_source)
            self.audio_active_source_label.setText(
                f"Selected source: {source_name}"
            )
            self.audio_active_source_label.setToolTip(self.active_audio_source)
            self.audio_active_source_label.setAccessibleDescription(self.active_audio_source)
        with QSignalBlocker(self.audio_stream_combo):
            self.audio_stream_combo.clear()
            if not inspection or not inspection.streams:
                self.audio_stream_combo.addItem("No audio streams detected", -1)
                return
            ranking = {item.stream.ordinal: item for item in inspection.ranked}
            for stream in inspection.streams:
                ranked = ranking.get(stream.ordinal)
                recommendation = " | recommended" if inspection.recommendation and inspection.recommendation.stream.ordinal == stream.ordinal else ""
                details = " | ".join(
                    value for value in (
                        stream.codec,
                        f"{stream.channels} ch" if stream.channels else "",
                        stream.channel_layout,
                        stream.language,
                        stream.title,
                    ) if value
                )
                confidence = f" | {ranked.confidence:.0%}" if ranked else ""
                self.audio_stream_combo.addItem(
                    f"{stream.human_label}{recommendation}{confidence} | {details}",
                    stream.ordinal,
                )
            selected = inspection.selected_ordinal
            self.audio_stream_combo.setCurrentIndex(max(0, self.audio_stream_combo.findData(selected)))
        self._populate_audio_preview_regions()
        self._refresh_selected_source_details()
        self._refresh_preview_identity()

    def _populate_audio_preview_regions(self) -> None:
        inspection = self.audio_inspections.get(self.active_audio_source)
        ordinal = self.audio_stream_combo.currentData() if hasattr(self, "audio_stream_combo") else -1
        regions = inspection.preview_regions.get(ordinal, []) if inspection and isinstance(ordinal, int) else []
        with QSignalBlocker(self.audio_preview_region_combo):
            self.audio_preview_region_combo.clear()
            if regions:
                for index, region in enumerate(regions):
                    self.audio_preview_region_combo.addItem(
                        f"{index + 1}: {region.start_seconds:.1f}s–{region.start_seconds + region.duration_seconds:.1f}s",
                        index,
                    )
            else:
                self.audio_preview_region_combo.addItem("Region 1: start of recording", 0)

    def _refresh_selected_source_details(self) -> None:
        if not hasattr(self, "audio_selected_source_details"):
            return
        source_key = self.active_audio_source
        inspection = self.audio_inspections.get(source_key)
        failure = self.audio_inspection_failures.get(source_key, "")
        if failure:
            self.audio_selected_source_details.setText(
                f"✕ BLOCKED — {self._display_source_name(source_key)} could not be inspected. "
                "Correct the source or audio-tool setup, then inspect again."
            )
            self._set_operator_state(self.audio_selected_source_details, "error")
            return
        if inspection is None:
            message = (
                f"⚠ REQUIRED — Inspect {self._display_source_name(source_key)} before choosing its microphone track."
                if source_key
                else "Select a source row to review its narration decision."
            )
            self.audio_selected_source_details.setText(message)
            self._set_operator_state(
                self.audio_selected_source_details,
                "attention" if source_key else "pending",
            )
            return
        recommendation = inspection.recommendation
        recommendation_text = (
            f"{recommendation.stream.human_label} ({recommendation.confidence:.0%})"
            if recommendation
            else "No recommendation"
        )
        selected_text = (
            f"Track {inspection.selected_ordinal + 1}"
            if inspection.selected_ordinal is not None
            else "No track selected"
        )
        status = "✓ CONFIRMED" if inspection.resolved else "⚠ REQUIRED"
        self.audio_selected_source_details.setText(
            f"{status} — {self._display_source_name(source_key)}\n"
            f"Recommendation: {recommendation_text}   |   Selected narration: {selected_text}\n"
            f"Why selected: {inspection.selection_reason}"
        )
        self.audio_selected_source_details.setToolTip(source_key)
        self._set_operator_state(
            self.audio_selected_source_details,
            "ready" if inspection.resolved else "attention",
        )

    def _refresh_preview_identity(self, *, state: str = "pending") -> None:
        if not hasattr(self, "audio_preview_identity"):
            return
        ordinal = self.audio_stream_combo.currentData() if hasattr(self, "audio_stream_combo") else -1
        if not self.active_audio_source or not isinstance(ordinal, int) or ordinal < 0:
            self.audio_preview_identity.setText("Previewing: no source or track loaded")
            self.audio_preview_identity.setToolTip("")
            self._set_operator_state(self.audio_preview_identity, "pending")
            return
        source_name = self._display_source_name(self.active_audio_source, max_chars=58)
        suffix_for = {
            "preparing": " — preparing…",
            "ready": " — ready",
            "error": " — preview unavailable",
            "pending": " — preview not loaded",
        }
        suffix = suffix_for.get(state, "")
        self.audio_preview_identity.setText(
            f"Previewing: {source_name} — Track {ordinal + 1}{suffix}"
        )
        self.audio_preview_identity.setToolTip(
            f"{self.active_audio_source} — Track {ordinal + 1}"
        )
        self.audio_preview_identity.setAccessibleDescription(
            f"{self.active_audio_source}, Track {ordinal + 1}"
        )
        operator_state_for = {
            "preparing": "active",
            "ready": "ready",
            "error": "error",
            "pending": "pending",
        }
        self._set_operator_state(
            self.audio_preview_identity,
            operator_state_for.get(state, "pending"),
        )

    @staticmethod
    def _audio_time_text(milliseconds: int) -> str:
        seconds = max(0, milliseconds // 1000)
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _refresh_audio_batch_table(self) -> None:
        if not hasattr(self, "audio_batch_table"):
            return
        source_keys = self._current_audio_source_keys()
        for source_key in self.audio_inspections:
            if source_key not in source_keys:
                source_keys.append(source_key)
        with QSignalBlocker(self.audio_batch_table):
            self.audio_batch_table.setRowCount(len(source_keys))
            for row, source_key in enumerate(source_keys):
                inspection = self.audio_inspections.get(source_key)
                failure = self.audio_inspection_failures.get(source_key, "")
                if inspection is None:
                    values = (
                        Path(source_key).name,
                        (
                            "Inspection failed"
                            if failure
                            else "Not inspected"
                        ),
                        "✕ BLOCKED" if failure else "⚠ REQUIRED",
                    )
                else:
                    recommendation = inspection.recommendation
                    recommendation_text = (
                        recommendation.stream.human_label
                        if recommendation
                        else "No audio recommendation"
                    )
                    if inspection.confirmation_state == "single-stream":
                        confirmation_text = "✓ CONFIRMED"
                    elif inspection.resolved:
                        confirmation_text = "✓ CONFIRMED"
                    elif (
                        recommendation
                        and recommendation.confidence < SAFE_CONFIDENCE_THRESHOLD
                    ):
                        confirmation_text = "⚠ REQUIRED"
                    else:
                        confirmation_text = "⚠ REQUIRED"
                    values = (
                        Path(source_key).name,
                        (
                            f"{recommendation_text} ({recommendation.confidence:.0%})"
                            if recommendation
                            else recommendation_text
                        ),
                        confirmation_text,
                    )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.ItemDataRole.UserRole, source_key)
                    if column == 0:
                        item.setToolTip(source_key)
                    if failure:
                        item.setToolTip(
                            "Inspection details (may include technical tool output): "
                            + failure
                        )
                    self.audio_batch_table.setItem(row, column, item)
                if source_key == self.active_audio_source:
                    self.audio_batch_table.selectRow(row)
        self.confirm_matching_layouts_button.setEnabled(self._can_confirm_all_matching_layouts())
        self._refresh_selected_source_details()
        self._refresh_audio_technical_details()

    def _refresh_audio_technical_details(self) -> None:
        if not hasattr(self, "audio_technical_details"):
            return
        details: list[str] = []
        for source_key in self._current_audio_source_keys():
            source_name = Path(source_key).name
            inspection = self.audio_inspections.get(source_key)
            if inspection is None:
                if source_key in self.audio_inspection_failures:
                    details.append(f"{source_name}: inspection failed; no stream mapping is available.")
                else:
                    details.append(f"{source_name}: not inspected yet.")
                continue
            selected = next(
                (
                    stream
                    for stream in inspection.streams
                    if stream.ordinal == inspection.selected_ordinal
                ),
                None,
            )
            if selected is None:
                details.append(
                    f"{source_name}: no active mapping; layout fingerprint {inspection.layout_fingerprint}."
                )
                continue
            details.append(
                f"{source_name}: {selected.human_label}; internal audio ordinal "
                f"{selected.ordinal}; FFmpeg mapping {selected.ffmpeg_map}; selection source "
                f"{inspection.confirmation_source or 'unresolved'}; layout fingerprint "
                f"{inspection.layout_fingerprint}."
            )
        self.audio_technical_details.setText(
            "\n".join(details)
            if details
            else "Inspect a source to view internal stream mappings and recording-layout details."
        )

    def _audio_batch_row_selected(self) -> None:
        row = self.audio_batch_table.currentRow()
        item = self.audio_batch_table.item(row, 0) if row >= 0 else None
        source_key = str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""
        if source_key and source_key != self.active_audio_source:
            self._cancel_audio_previews()
        if source_key and source_key in self.audio_inspections:
            self.active_audio_source = source_key
            self._populate_audio_stream_combo()
        elif source_key and source_key in self.audio_inspection_failures:
            self.active_audio_source = source_key
            self._populate_audio_stream_combo()
            self.audio_stream_status.setText(
                f"Could not inspect {Path(source_key).name}. Correct the source file or audio-tool setup, then choose Inspect tracks to retry."
            )
        elif source_key:
            self.active_audio_source = source_key
            self._populate_audio_stream_combo()
        self._refresh_selected_source_details()

    def _can_confirm_all_matching_layouts(self) -> bool:
        if self.audio_inspection_failures:
            return False
        expected = self._current_audio_source_keys()
        if expected and any(key not in self.audio_inspections for key in expected):
            return False
        unresolved = [item for item in self.audio_inspections.values() if not item.resolved]
        return bool(unresolved) and len({item.layout_fingerprint for item in self.audio_inspections.values()}) == 1

    def confirm_selected_audio_stream(self) -> None:
        inspection = self.audio_inspections.get(self.active_audio_source)
        ordinal = self.audio_stream_combo.currentData()
        if not inspection or not isinstance(ordinal, int) or ordinal < 0:
            self.audio_stream_status.setText("Select an inspected audio track before confirming it.")
            return
        inspection.selected_ordinal = ordinal
        inspection.confirmation_state = "operator-confirmed"
        inspection.confirmation_source = "operator"
        self.layout_confirmation_store.confirm(inspection, ordinal, profile_name=self.current_profile)
        # 264: Confirm microphone is your answer for this recording too, on every screen.
        speech_facts.confirm_track(self.active_audio_source, ordinal + 1, by=speech_facts.ANSWERED_IN_WIZARD)
        stream = next(item for item in inspection.streams if item.ordinal == ordinal)
        self.audio_stream_status.setText(
            f"{stream.human_label} is confirmed as operator narration for {Path(self.active_audio_source).name}."
        )
        self._sync_audio_selection_settings()
        self._refresh_audio_batch_table()
        self._refresh_audio_resolution_progress()
        self.refresh_review_summary()
        self._refresh_wizard_navigation()
        if self.current_workflow == WORKFLOW_REVIEW_NEW_VIDEOS:
            self._refresh_review_inbox_dashboard()

    def confirm_all_matching_layouts(self) -> None:
        if not self._can_confirm_all_matching_layouts():
            self.audio_stream_status.setText(
                "Confirm-all is available only when every source has the same detected recording layout. Review each source separately when layouts differ."
            )
            return
        active = self.audio_inspections.get(self.active_audio_source)
        ordinal = self.audio_stream_combo.currentData()
        if not active or not isinstance(ordinal, int) or ordinal < 0:
            return
        for inspection in self.audio_inspections.values():
            if not any(stream.ordinal == ordinal for stream in inspection.streams):
                return
            inspection.selected_ordinal = ordinal
            inspection.confirmation_state = "operator-confirmed"
            inspection.confirmation_source = "operator batch confirmation"
        self.layout_confirmation_store.confirm(active, ordinal, profile_name=self.current_profile)
        for source_key in self.audio_inspections:
            speech_facts.confirm_track(source_key, ordinal + 1, by=speech_facts.ANSWERED_IN_WIZARD)
        self.audio_stream_status.setText(
            f"Track {ordinal + 1} confirmed for all {len(self.audio_inspections)} sources with the matching layout."
        )
        self._sync_audio_selection_settings()
        self._refresh_audio_batch_table()
        self._refresh_audio_resolution_progress()
        self.refresh_review_summary()
        self._refresh_wizard_navigation()
        if self.current_workflow == WORKFLOW_REVIEW_NEW_VIDEOS:
            self._refresh_review_inbox_dashboard()

    def preview_selected_audio_stream(self) -> None:
        """136 (Wave 8): hear the chosen track in the shared built-in player, from the preview region.

        The wizard has no player of its own any more. The whole recording opens at full quality on the
        chosen track, with Previous / Next speech between the speech-dense regions, and it always opens
        in the built-in player, whatever Settings > Video player says: only it can play one track.
        """

        inspection = self.audio_inspections.get(self.active_audio_source)
        ordinal = self.audio_stream_combo.currentData()
        if not inspection or not isinstance(ordinal, int) or ordinal < 0:
            self.audio_stream_status.setText("Inspect and select an audio track before previewing it.")
            return
        source = Path(self.active_audio_source)
        regions = inspection.preview_regions.get(ordinal, [])
        index = max(0, int(self.audio_preview_region_combo.currentData() or 0))
        region = regions[min(index, len(regions) - 1)] if regions else None
        stretches = tuple((item.start_seconds, item.start_seconds + item.duration_seconds) for item in regions)
        target = PlayTarget(
            path=source,
            start_seconds=region.start_seconds if region else 0.0,
            label=f"Track {ordinal + 1}: is this your microphone?",
            hear_track=ordinal + 1,
            stretches=stretches,
            stretch_kind="speech" if stretches else "",
        )
        self._preview_request = (path_key(source), ordinal + 1)
        self._refresh_preview_identity(state="preparing")
        self.audio_stream_status.setText(
            f"Opening {self._display_source_name(self.active_audio_source)}, Track {ordinal + 1} in the built-in player…"
        )
        self._write_workbench_log(f"Narration preview opened in the built-in player: {source}; Track {ordinal + 1}.")
        self._watch_preview_window(self.video_opener.open_now(target))

    def _watch_preview_window(self, window: Any) -> None:
        if window is None or window is self._preview_window:
            return
        self._preview_window = window
        for name, slot in (("track_heard", self._on_preview_track_heard), ("cannot_play", self._on_preview_cannot_play)):
            signal = getattr(window, name, None)
            if signal is not None:
                signal.connect(slot)

    def _preview_matches(self, path: str) -> bool:
        request = self._preview_request
        return request is not None and request[0] == path_key(path) and path_key(self.active_audio_source) == request[0]

    def _on_preview_track_heard(self, path: str, track: int) -> None:
        """The shared player says which track it really plays; the "Previewing" line follows it."""

        if not self._preview_matches(path):
            return
        requested = self._preview_request[1] if self._preview_request else None
        if track != requested:
            self._refresh_preview_identity()
            return
        self._refresh_preview_identity(state="ready")
        self.audio_stream_status.setText(
            f"Playing {self._display_source_name(self.active_audio_source)}, Track {track} in the built-in player. "
            "Confirm it only if you hear your microphone narration."
        )
        self._write_workbench_log(f"Narration preview playing in the built-in player: {path}; Track {track}.")

    def _on_preview_cannot_play(self, path: str) -> None:
        if not self._preview_matches(path):
            return
        self._refresh_preview_identity(state="error")
        self.audio_stream_status.setText(
            "The built-in player can't play this recording. Choose the source again and try Preview track once more."
        )

    def _cancel_audio_previews(self) -> None:
        # 136: the one player pauses and keeps its place, as old playback stopped here before; it is
        # never released, so the recording does not have to be opened again. The next Preview track
        # plays whatever is chosen then.
        self._preview_request = None
        self.video_opener.yield_audio()
        self._refresh_preview_identity()

    def select_voice_enrollment_sample(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select a short clean recording of your microphone voice",
            str(self.app_settings.get("default_input_folder") or ""),
            "Audio or media (*.wav *.mp3 *.m4a *.aac *.flac *.mkv *.mp4 *.mov);;All files (*.*)",
        )
        if not path or not self.resources.ffmpeg_exe:
            return
        enrollment_temp = Path(str(self.app_settings.get("temp_folder") or default_temp_folder())) / "voice-enrollment-sample.wav"
        try:
            extract_sample(self.resources.ffmpeg_exe, Path(path), 0, enrollment_temp, duration_seconds=12.0)
            self.voice_enrollment_store.save_features(analyze_wav(enrollment_temp))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            self.voice_enrollment_status.setText(f"Optional enrollment failed: {exc}")
            return
        finally:
            if enrollment_temp.exists():
                enrollment_temp.unlink()
        self.voice_enrollment_status.setText(
            "Optional local voice enrollment is active. Only a small acoustic ranking vector is stored locally; no sample or path is exported."
        )

    def clear_voice_enrollment(self) -> None:
        self.voice_enrollment_store.clear()
        self.voice_enrollment_status.setText("Optional local voice enrollment: not enrolled")

    def _sync_audio_selection_settings(self) -> None:
        selections: dict[str, dict[str, Any]] = {}
        for source_key, inspection in self.audio_inspections.items():
            if inspection.resolved and inspection.selected_ordinal is not None:
                stream = next(item for item in inspection.streams if item.ordinal == inspection.selected_ordinal)
                selections[source_key] = {
                    "audioOrdinal": stream.ordinal,
                    "humanTrackNumber": stream.human_track_number,
                    "ffmpegMap": stream.ffmpeg_map,
                    "layoutFingerprint": inspection.layout_fingerprint,
                    "confirmationSource": inspection.confirmation_source,
                }
        all_resolved = bool(self.audio_inspections) and len(selections) == len(self.audio_inspections)
        self.run_settings["evidence_audio_stream_selection_confirmed"] = all_resolved
        self.run_settings["evidence_audio_stream_selections_json"] = json.dumps(selections, separators=(",", ":")) if all_resolved else ""
        ordinals = {value["audioOrdinal"] for value in selections.values()}
        if all_resolved and len(ordinals) == 1:
            self.run_settings["evidence_audio_stream_index"] = next(iter(ordinals))

    def _audio_summary_html(self) -> str:
        if not self.audio_inspections:
            return "<li><b>Operator narration:</b> Not inspected — blocking</li>"
        unresolved = self._unresolved_audio_source_keys()
        if unresolved:
            names = ", ".join(escape(Path(item).name) for item in unresolved)
            return (
                "<li><b>Operator narration:</b> Confirmation required — blocking</li>"
                f"<li><b>Files to resolve:</b> {names}</li>"
            )
        ordinals = {item.selected_ordinal for item in self.audio_inspections.values()}
        if len(ordinals) == 1:
            ordinal = next(iter(ordinals))
            sources = list(self.audio_inspections.values())
            state = "selected from confirmed recording layout" if all(item.confirmation_state == "confirmed-layout" for item in sources) else "confirmed"
            return (
                f"<li><b>Operator narration:</b> Track {ordinal + 1} — {state}</li>"
            )
        return "<li><b>Operator narration:</b> Per-file confirmed mappings (see the source table)</li>"

    def _source_changed(self) -> None:
        if self._loading:
            return
        self.run_settings["input_path"] = self._active_source_text()
        self.run_settings["evidence_audio_stream_selection_confirmed"] = False
        self.run_settings["evidence_audio_stream_selections_json"] = ""
        self.audio_inspection_generation += 1
        if self.audio_inspection_thread is not None:
            self.audio_inspection_thread.cancel()
            self.inspect_audio_streams_button.setEnabled(False)
            self.cancel_audio_inspection_button.setEnabled(False)
        self._cancel_audio_previews()
        self.audio_inspections.clear()
        self.audio_inspection_failures.clear()
        self.audio_expected_sources.clear()
        self.active_audio_source = ""
        if hasattr(self, "audio_stream_combo"):
            with QSignalBlocker(self.audio_stream_combo):
                self.audio_stream_combo.clear()
                self.audio_stream_combo.addItem("Inspect a source file to list streams", -1)
            self.audio_stream_status.setText(
                "Narration selection is unresolved. Inspect every source; an exact saved layout may be reused, otherwise confirmation is required."
            )
            self.audio_active_source_label.setText(
                "Selected source: no source selected"
            )
            self.audio_inspection_progress.setRange(0, 1)
            self.audio_inspection_progress.setValue(0)
            self.audio_inspection_progress.setFormat("Audio inspection not started")
            self._refresh_preview_identity()
            self._refresh_audio_technical_details()
        self._refresh_source_discovery()
        self.refresh_review_summary()
        self._refresh_wizard_navigation()

    def browse_input_file(self) -> None:
        start = self.input_path_edit.text().strip() or str(self.app_settings.get("default_input_folder") or "")
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose recording",
            start,
            "Media files (*.mp4 *.mkv *.mov *.avi *.webm *.m4v);;All files (*.*)",
        )
        if path:
            self.input_path_edit.setText(path)

    def browse_input_folder(self) -> None:
        start = self.input_path_edit.text().strip() or str(self.app_settings.get("default_input_folder") or "")
        path = QFileDialog.getExistingDirectory(self, "Choose source folder", start)
        if path:
            self.input_path_edit.setText(path)

    def _run_setting_changed(self, key: str) -> None:
        if self._loading:
            return
        control = self.run_setting_controls[key]
        self.run_settings[key] = _control_value(control)
        if key == "whisper_model":
            self.run_settings["whisper_model_download_approved"] = False
            self.resources.dependencies = [
                replace(
                    item,
                    name=f"Whisper model: {self.run_settings[key]}",
                    status="not_checked",
                    version="",
                    detail="The selected model changed. Refresh dependency readiness before starting.",
                    action_label="Check",
                    action_kind="check",
                )
                if item.key == "whisper_model"
                else item
                for item in self.resources.dependencies
            ]
            self.refresh_dependency_status()
        if key == "visual_context_preset":
            self._apply_visual_preset(str(self.run_settings[key]))
        elif key == "narration_context_preset":
            self._apply_narration_preset(str(self.run_settings[key]))
        elif key == "archive_action":
            self._refresh_source_guidance()
        self._update_profile_dirty_state()
        self.refresh_sampling_estimate()
        self.refresh_review_summary()

    def _apply_visual_preset(self, preset: str) -> None:
        values = {
            "Compact": (45, 60),
            "Balanced": (90, 120),
            "Extended": (120, 240),
        }.get(preset)
        if values:
            self.run_settings["pre_context_seconds"], self.run_settings["post_context_seconds"] = values

    def _apply_narration_preset(self, preset: str) -> None:
        values = {
            "Standard": (60, 240),
            "Driving / Extended": (120, 600),
        }.get(preset)
        if values:
            self.run_settings["narration_context_pre_seconds"], self.run_settings[
                "narration_context_post_seconds"
            ] = values

    def _output_changed(self) -> None:
        if self._loading:
            return
        self.run_settings["output_folder"] = self.output_path_edit.text().strip()
        self.run_settings["open_output_in_explorer"] = self.open_output_checkbox.isChecked()
        self.refresh_review_summary()
        self._refresh_wizard_navigation()

    def browse_output_folder(self) -> None:
        start = self.output_path_edit.text().strip() or str(self.app_settings.get("output_folder") or "")
        path = QFileDialog.getExistingDirectory(self, "Choose output folder", start)
        if path:
            self.output_path_edit.setText(path)

    def _recent_output_selected(self) -> None:
        value = self.recent_output_combo.currentData()
        if value:
            self.output_path_edit.setText(str(value))

    def refresh_wizard(self) -> None:
        self._loading = True
        try:
            source_text = str(self.run_settings.get("input_path") or "")
            if str(self.run_settings.get("input_kind") or "local") == "url":
                self.url_input_edit.setPlainText(source_text)
            else:
                self.input_path_edit.setText(source_text)
            self.output_path_edit.setText(str(self.run_settings.get("output_folder") or ""))
            self.open_output_checkbox.setChecked(bool(self.run_settings.get("open_output_in_explorer")))
            for key, control in self.run_setting_controls.items():
                _set_control_value(control, self.run_settings.get(key, METADATA_BY_KEY[key].default))
            self.recent_output_combo.clear()
            self.recent_output_combo.addItem("Choose a recent folder", "")
            for path in self.app_settings.get("recent_output_folders") or []:
                self.recent_output_combo.addItem(str(path), str(path))
            self.refresh_profile_selector()
            self._refresh_workflow_surfaces()
        finally:
            self._loading = False
        self._refresh_source_discovery()
        self._update_profile_dirty_state()
        self.refresh_review_summary()
        self._refresh_wizard_navigation()

    def refresh_sampling_estimate(self) -> None:
        if not hasattr(self, "sampling_estimate_label"):
            return
        estimate = estimate_sampling(self.run_settings)
        cap_note = "; frame cap will reduce cadence" if estimate.cadence_is_capped else ""
        package_note = " Large package likely." if estimate.large_package_warning else ""
        self.sampling_estimate_label.setText(
            f"Visual/audio {estimate.visual_audio_window_seconds:.0f}s | narration "
            f"{estimate.narration_context_seconds:.0f}s | up to "
            f"{estimate.estimated_saved_full_frames_per_candidate} full frames per mention"
            f"{cap_note}.{package_note}"
        )

    def validate_current_run(self) -> list[str]:
        errors: list[str] = []
        # 224, F1: the Inbox reads its own folders (Inbox settings), so New Review's source box, which may still
        # hold a web address from a Full Review, is not its input and is not checked for it.
        inbox = self.current_workflow == WORKFLOW_REVIEW_NEW_VIDEOS
        source = "" if inbox else str(self.run_settings.get("input_path") or "").strip()
        kind = "local" if inbox else str(self.run_settings.get("input_kind") or "local")
        if self.current_workflow in {
            WORKFLOW_FULL_REVIEW,
            WORKFLOW_TRANSCRIPT_ONLY,
            WORKFLOW_CODEX_EVIDENCE,
        } and not source:
            errors.append("Choose a source file, folder, or supported URL.")
        if kind == "url" and self.current_workflow != WORKFLOW_FULL_REVIEW:
            errors.append("URL input is supported only for Full Review.")
        if kind == "url" and source:
            urls, invalid = _parse_url_lines(source)
            if invalid:
                errors.append(
                    f"Remove or correct {len(invalid)} line(s) that are not complete http:// or https:// URLs."
                )
            if not urls:
                errors.append("Paste at least one complete http:// or https:// URL.")
        if self.current_workflow != WORKFLOW_FULL_REVIEW and _looks_like_url(source):
            errors.append("This workflow accepts local sources only.")
        if self.current_workflow == WORKFLOW_CODEX_EVIDENCE and source:
            if self.audio_inspection_thread is not None:
                errors.append(
                    "Wait for audio inspection to finish, or cancel it safely, before starting review."
                )
            unresolved_sources = self._unresolved_audio_source_keys()
            if unresolved_sources:
                names = ", ".join(Path(item).name for item in unresolved_sources)
                errors.append(
                    "Review and confirm narration tracks for: " + names + "."
                )
        if not str(self.run_settings.get("output_folder") or "").strip() and self.current_workflow != WORKFLOW_REVIEW_NEW_VIDEOS:
            errors.append("Choose an output folder.")
        # 127/211: results kept in a temp folder can be cleared without warning; the one rule.
        output_problem = self._output_folder_problem()
        if output_problem:
            errors.append(output_problem)
        if not self.resources.backend_ready:
            not_ready = [
                item
                for item in self.resources.dependencies
                if item.required and not item.ready
            ]
            names = ", ".join(item.name for item in not_ready)
            if any(item.status in {"not_checked", "checking", "info"} for item in not_ready):
                errors.append(
                    "Check dependency readiness in Settings before starting this review."
                )
            else:
                errors.append(
                    f"Resolve required dependency setup in Settings: {names}."
                )
        if self.resources.preflight_complete and self._workflow_needs_local_whisper():
            whisper = self._dependency_by_key("whisper")
            torch = self._dependency_by_key("torch")
            cpu = self._dependency_by_key("cpu_fallback")
            model = self._dependency_by_key("whisper_model")
            if whisper is not None and not whisper.ready:
                errors.append(
                    "Local Whisper needs setup. Open Settings > Dependencies for the install or repair guidance."
                )
            if torch is not None and not torch.ready:
                errors.append(
                    "PyTorch needs setup before Local Whisper can run. Open Settings > Dependencies."
                )
            if cpu is not None and not cpu.ready:
                errors.append(
                    "Neither CUDA nor CPU fallback is ready for Local Whisper. Repair the selected Python runtime."
                )
            # Installer plan, Stage 3: the selected model and base.en (voice detection) must be on this PC as Whisper
            # published them; only the approval in Settings > Dependencies downloads one.
            if model is not None and model.status == "not_checked":
                errors.append(
                    "The selected Whisper model has not been checked. Refresh readiness in Settings > Dependencies."
                )
            errors.extend(self.model_blockers([str(self.run_settings.get("whisper_model") or ""), VOICE_MODEL]))
        if kind == "url" and self.current_workflow == WORKFLOW_FULL_REVIEW and self.resources.preflight_complete:
            ytdlp = self._dependency_by_key("ytdlp")
            if ytdlp is None or not ytdlp.ready:
                if ytdlp is not None and ytdlp.status == "update_recommended":
                    errors.append(
                        "yt-dlp is too old for a dependable web-video review. Update it, then readiness will recheck automatically."
                    )
                else:
                    errors.append(
                        "yt-dlp needs setup before Full Review can download URLs. Open Settings > Dependencies."
                    )
        if self.current_workflow == WORKFLOW_CODEX_EVIDENCE:
            if (
                self.current_profile_metadata is not None
                and self.current_profile_metadata.profile_type == "built-in"
                and not self.is_profile_dirty()
            ):
                canonical = starter_profile_settings(repo_root=self.repo_root_path).get(self.current_profile)
                if canonical:
                    critical = (
                        "language",
                        "narration_speech_mode",
                        "evidence_render_density",
                        "evidence_frame_cadence_seconds",
                        "evidence_max_frames_per_candidate",
                        "evidence_profile_setup_name",
                    )
                    stale = [key for key in critical if self.run_settings.get(key) != canonical.get(key)]
                    if stale:
                        errors.append(
                            "The applied built-in profile is stale or incomplete ("
                            + ", ".join(stale)
                            + "). Reapply the profile or restart the Workbench so it can be migrated safely."
                        )
            try:
                command = self.build_command()
            except (ValueError, OSError) as exc:
                self._write_workbench_log(
                    f"Technical setup error while building the launch command: {exc}"
                )
                errors.append(
                    "The review processing setup is incomplete. Open Settings > Dependencies, choose Check readiness, then reapply the profile."
                )
            else:
                command_errors = validate_effective_command(
                    self.run_settings,
                    command,
                    workflow=self.current_workflow,
                )
                if command_errors:
                    for message in command_errors:
                        self._write_workbench_log(
                            f"Technical launch command mismatch: {message}"
                        )
                    errors.append(
                        "The review setup no longer matches the selected profile. Reapply the profile before starting."
                    )
        return errors

    def _dependency_by_key(self, key: str) -> Any:
        return next(
            (item for item in self.resources.dependencies if item.key == key),
            None,
        )

    def _workflow_needs_local_whisper(self) -> bool:
        if self.current_workflow in {
            WORKFLOW_TRANSCRIPT_ONLY,
            WORKFLOW_CODEX_EVIDENCE,
            WORKFLOW_REVIEW_NEW_VIDEOS,
        }:
            return True
        if self.current_workflow == WORKFLOW_FULL_REVIEW:
            return str(self.run_settings.get("processing_mode") or "Local") in {
                "",
                "Local",
                "Hybrid",
            }
        return False

    def refresh_review_summary(self) -> None:
        if not hasattr(self, "review_summary"):
            return
        workflow = WORKFLOW_BY_NUMBER[self.current_workflow]
        source_value = str(self.run_settings.get("input_path") or "")
        if str(self.run_settings.get("input_kind") or "local") == "url":
            urls, _invalid = _parse_url_lines(source_value)
            source = (
                f"{len(urls)} web video{'s' if len(urls) != 1 else ''} queued"
                if urls
                else "Not selected"
            )
        else:
            source = source_value or "Not selected"
        output = str(self.run_settings.get("output_folder") or "Not selected")
        profile = self.current_profile or "Recommended settings"
        profile_source = PROFILE_OPERATOR_DESCRIPTIONS.get(
            self.current_profile,
            "Your saved preset"
            if self.current_profile and not self.profile_manager.is_builtin(self.current_profile)
            else "Recommended settings"
            if not self.current_profile
            else "Built-in preset",
        )
        if self.is_profile_dirty():
            profile_source = f"Modified current run from {profile_source}"
        if self.current_workflow == WORKFLOW_CODEX_EVIDENCE:
            estimate = estimate_sampling(self.run_settings)
            creates = (
                "A canonical local evidence package, complete-session timeline, relationship hints, "
                "Codex/Claude drafts"
            )
            mode = str(self.run_settings.get("evidence_handoff_mode") or "Local")
            if mode in {"PortableZip", "Both"}:
                creates += ", and a text-first portable handoff ZIP"
            estimate_html = (
                f"<li><b>Visual/audio window:</b> {estimate.visual_audio_window_seconds:.0f} seconds</li>"
                f"<li><b>Narration window:</b> {estimate.narration_context_seconds:.0f} seconds</li>"
                f"<li><b>Estimated images:</b> up to {estimate.estimated_saved_full_frames_per_candidate} full frames "
                f"per richly rendered mention</li>"
                f"<li><b>Profile source:</b> {escape(profile_source)}</li>"
                f"<li><b>Language:</b> {escape(str(self.run_settings.get('language') or 'Auto'))}</li>"
                f"<li><b>Narration speech mode:</b> {escape(str(self.run_settings.get('narration_speech_mode') or 'Auto'))}</li>"
                f"<li><b>Render density:</b> {escape(str(self.run_settings.get('evidence_render_density') or 'Compact'))}</li>"
                f"<li><b>Frame cadence:</b> {escape(str(self.run_settings.get('evidence_frame_cadence_seconds')))} seconds</li>"
                f"<li><b>Frame cap:</b> {escape(str(self.run_settings.get('evidence_max_frames_per_candidate')))} per outcome</li>"
                f"{self._audio_summary_html()}"
            )
        elif self.current_workflow == WORKFLOW_FULL_REVIEW:
            creates = "A complete review package with proxy, frames, transcripts, translations, and selected add-ons"
            estimate_html = f"<li><b>Frame interval:</b> {self.run_settings.get('frame_interval_seconds')} seconds</li>"
        elif self.current_workflow == WORKFLOW_TRANSCRIPT_ONLY:
            creates = "Timestamped transcripts, indexes, and optional literal search results"
            estimate_html = "<li><b>Media retained:</b> controlled by the transcript audio-retention setting</li>"
        elif self.current_workflow == WORKFLOW_ARCHIVE_CATALOG:
            creates = "A local archive catalog, indexes, notes surfaces, and restore/upload preparation manifests"
            estimate_html = (
                f"<li><b>Archive mode:</b> {escape(str(self.run_settings.get('archive_action', 'build')))}</li>"
            )
        else:
            creates = "A local review ledger and only the evidence packages that need operator review"
            estimate_html = "<li><b>Scan:</b> configured recording folders with local deduplication</li>"
        self.review_summary.setHtml(
            "<h3>Current review</h3><ul>"
            f"<li><b>Task:</b> {escape(workflow.display_name)}</li>"
            f"<li><b>Source:</b> {escape(source)}</li>"
            f"<li><b>Profile:</b> {escape(profile)}</li>"
            f"<li><b>Output:</b> {escape(output)}</li>"
            f"<li><b>Creates:</b> {creates}</li>"
            f"{estimate_html}</ul>"
            "<p><b>Privacy:</b> No GitHub issue is created and no evidence is uploaded by the Workbench.</p>"
        )
        errors = self.validate_current_run()
        self.run_warning_label.setText("\n".join(errors))
        unresolved_audio = (
            self._unresolved_audio_source_keys()
            if self.current_workflow == WORKFLOW_CODEX_EVIDENCE
            else []
        )
        self.resolve_narration_button.setVisible(bool(unresolved_audio))
        if unresolved_audio:
            count = len(unresolved_audio)
            self.resolve_narration_button.setText(
                f"Confirm microphone for {count} file{'s' if count != 1 else ''}"
            )
        dependency_blocked = any(
            "dependenc" in error.casefold()
            or "whisper" in error.casefold()
            or "pytorch" in error.casefold()
            or "python runtime" in error.casefold()
            for error in errors
        )
        self.resolve_dependencies_button.setVisible(dependency_blocked)
        self.resolve_dependencies_button.setProperty(
            "operatorAction",
            "attention" if dependency_blocked and not unresolved_audio else "neutral",
        )
        self.resolve_dependencies_button.style().unpolish(self.resolve_dependencies_button)
        self.resolve_dependencies_button.style().polish(self.resolve_dependencies_button)
        self.review_blocker_panel.setVisible(bool(errors))
        if errors:
            self.review_blocker_heading.setText(
                "⚠ ACTION REQUIRED" if unresolved_audio else "✕ REVIEW BLOCKED"
            )
            self._set_operator_state(
                self.review_blocker_panel,
                "attention" if unresolved_audio else "error",
            )
        self.start_review_button.setEnabled(not errors and self.runner_thread is None)
        if self.runner_thread is not None:
            self.start_review_button.setText("Review already running")
            self.start_review_button.setProperty("operatorAction", "blocked")
            self.start_review_button.setToolTip(
                "A review is already running. Open Queue / Progress to monitor or cancel it."
            )
        elif errors:
            self.start_review_button.setText("Start review — blocked")
            self.start_review_button.setProperty("operatorAction", "blocked")
            self.start_review_button.setToolTip(
                "Resolve before starting:\n" + "\n".join(errors)
            )
        else:
            self.start_review_button.setText("✓ Start review")
            self.start_review_button.setProperty("operatorAction", "ready")
            self.start_review_button.setToolTip("Start this local review.")
        self.start_review_button.style().unpolish(self.start_review_button)
        self.start_review_button.style().polish(self.start_review_button)
        self._refresh_wizard_step_states(errors=errors)
        try:
            self.command_preview.setPlainText(self.build_command().preview)
        except (ValueError, OSError) as exc:
            self.command_preview.setPlainText(f"Command unavailable: {exc}")

    def review_and_confirm_narration_tracks(self) -> None:
        unresolved = self._unresolved_audio_source_keys()
        if not unresolved:
            return
        source_key = unresolved[0]
        self.wizard_steps.setCurrentRow(1)
        self.active_audio_source = source_key
        self._populate_audio_stream_combo()
        for row in range(self.audio_batch_table.rowCount()):
            item = self.audio_batch_table.item(row, 0)
            if item and str(item.data(Qt.ItemDataRole.UserRole) or "") == source_key:
                self.audio_batch_table.setCurrentCell(row, 0)
                break
        self.source_scroll.ensureWidgetVisible(self.audio_results_group, 0, 36)
        if source_key in self.audio_inspection_failures or source_key not in self.audio_inspections:
            self.audio_stream_status.setText(
                f"{Path(source_key).name} still needs a successful audio inspection. Correct the source or audio-tool setup, then choose Inspect tracks."
            )
            self.inspect_audio_streams_button.setFocus()
        else:
            self.audio_stream_status.setText(
                f"Confirm the selected narration track for {Path(source_key).name}. The recommendation is advice; preview another track if needed."
            )
            self.confirm_audio_stream_button.setFocus(Qt.FocusReason.OtherFocusReason)
        self._refresh_selected_source_details()

    def open_dependency_setup(self) -> None:
        if self.page_stack.currentWidget() is self.pages.get("New Review"):
            self.standard_review_return_after_dependency_check = True
            self.standard_review_dependency_return_step = self.wizard_steps.currentRow()
        self.navigate("Settings")
        self.settings_tabs.setCurrentIndex(2)
        self.dependency_check_button.setFocus(Qt.FocusReason.OtherFocusReason)

    # Profiles

    def _profile_snapshot(self, settings: dict[str, Any], workflow: str) -> dict[str, Any]:
        return {
            "workflow": normalize_workflow(workflow),
            **{
                key: settings.get(key)
                for key in sorted(settings)
                if key not in TRANSIENT_PROFILE_KEYS
            },
        }

    def is_profile_dirty(self) -> bool:
        if not self.current_profile or not self.profile_baseline:
            return False
        return self._profile_snapshot(self.run_settings, self.current_workflow) != self.profile_baseline

    def _update_profile_dirty_state(self) -> None:
        if not hasattr(self, "profile_state_label"):
            return
        if self.is_profile_dirty():
            self.profile_state_label.setText(f"Custom \N{EM DASH} modified from {self.current_profile}")
            self.profile_state_label.setProperty("accent", True)
        elif self.current_profile:
            description = PROFILE_OPERATOR_DESCRIPTIONS.get(
                self.current_profile,
                "Your saved preset" if not self.profile_manager.is_builtin(self.current_profile) else "Built-in preset",
            )
            self.profile_state_label.setText(f"{self.current_profile}: {description}")
            self.profile_state_label.setProperty("accent", False)
        else:
            self.profile_state_label.setText("Recommended settings — no preset required")
        self.profile_state_label.style().unpolish(self.profile_state_label)
        self.profile_state_label.style().polish(self.profile_state_label)

    def refresh_profile_selector(self) -> None:
        if not hasattr(self, "profile_selector"):
            return
        names = self.profile_manager.list_names()
        compatible: list[tuple[str, LoadedProfile]] = []
        for name in names:
            loaded = self.profile_manager.load_with_metadata(name)
            if loaded.workflow == self.current_workflow:
                compatible.append((name, loaded))
        with QSignalBlocker(self.profile_selector):
            self.profile_selector.clear()
            self.profile_selector.addItem(
                "Recommended settings — ready to use without a preset",
                "",
            )
            for name, loaded in compatible:
                description = PROFILE_OPERATOR_DESCRIPTIONS.get(
                    name,
                    "Your saved preset" if loaded.profile_type != "built-in" else "Optional built-in preset",
                )
                self.profile_selector.addItem(
                    f"{name} — {description}",
                    name,
                )
            index = self.profile_selector.findData(self.current_profile)
            if index >= 0:
                self.profile_selector.setCurrentIndex(index)
        if hasattr(self, "settings_default_profile_combo"):
            with QSignalBlocker(self.settings_default_profile_combo):
                self.settings_default_profile_combo.clear()
                # 158: an empty default stays empty; without this choice the list
                # showed its first profile and saving made it the default.
                self.settings_default_profile_combo.addItem("None", "")
                for name in names:
                    self.settings_default_profile_combo.addItem(name, name)
                index = self.settings_default_profile_combo.findData(
                    str(self.app_settings.get("default_profile") or "")
                )
                if index >= 0:
                    self.settings_default_profile_combo.setCurrentIndex(index)
        if hasattr(self, "profiles_list"):
            self.profiles_list.clear()
            for name in names:
                kind = "Built-in" if self.profile_manager.is_builtin(name) else "Custom"
                item = QListWidgetItem(f"{name}  ({kind})")
                item.setData(Qt.ItemDataRole.UserRole, name)
                self.profiles_list.addItem(item)

    def _profile_selector_changed(self, _text: str) -> None:
        if self._loading:
            return
        name = str(self.profile_selector.currentData() or "")
        if not name:
            if self.current_profile:
                self.use_recommended_settings(self.current_workflow)
            return
        if name and name != self.current_profile:
            accepted = self.apply_profile(name)
            if not accepted:
                with QSignalBlocker(self.profile_selector):
                    index = self.profile_selector.findData(self.current_profile)
                    if index >= 0:
                        self.profile_selector.setCurrentIndex(index)

    def apply_profile(
        self,
        name: str,
        *,
        force: bool = False,
        confirm_replace: Callable[[], bool] | None = None,
    ) -> bool:
        if self.is_profile_dirty() and not force:
            if confirm_replace is None:
                response = QMessageBox.question(
                    self,
                    "Apply this preset?",
                    f"You changed options in this current review after applying {self.current_profile}. "
                    f"Apply {name} and discard only those unsaved option changes? Your source and output stay unchanged.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                approved = response == QMessageBox.StandardButton.Yes
            else:
                approved = bool(confirm_replace())
            if not approved:
                return False
        loaded = self.profile_manager.load_with_metadata(name)
        transient = {key: deepcopy(self.run_settings.get(key)) for key in TRANSIENT_PROFILE_KEYS}
        self.run_settings.update(deepcopy(loaded.settings))
        self.run_settings.update(transient)
        self.current_profile = loaded.name
        self.current_profile_metadata = loaded
        self.current_workflow = loaded.workflow
        self.profile_values = deepcopy(loaded.settings)
        self.profile_baseline = self._profile_snapshot(self.run_settings, self.current_workflow)
        self._apply_profile_audio_preference()
        if hasattr(self, "profile_selector"):
            self.refresh_wizard()
            self.refresh_home()
        return True

    def _apply_startup_profile(self) -> None:
        name = str(self.app_settings.get("default_profile") or "")
        if name in self.profile_manager.list_names():
            self.apply_profile(name, force=True)
        else:
            self.refresh_wizard()

    def use_recommended_settings(self, workflow: str) -> None:
        workflow = normalize_workflow(workflow)
        defaults = build_default_settings(repo_root=self.repo_root_path)
        transient = {
            key: deepcopy(self.run_settings.get(key))
            for key in TRANSIENT_PROFILE_KEYS
        }
        for meta in SETTING_METADATA:
            if workflow in meta.workflows and meta.key not in TRANSIENT_PROFILE_KEYS:
                self.run_settings[meta.key] = deepcopy(defaults.get(meta.key, meta.default))
        self.run_settings.update(transient)
        self.run_settings["default_workflow"] = workflow
        self.current_workflow = workflow
        self.current_profile = ""
        self.current_profile_metadata = None
        self.profile_values = {
            key: deepcopy(value)
            for key, value in defaults.items()
            if key not in TRANSIENT_PROFILE_KEYS
        }
        self.profile_baseline = {}
        if hasattr(self, "profile_selector"):
            self.refresh_wizard()
            self.refresh_home()

    def save_profile_as(self) -> None:
        name, ok = QInputDialog.getText(self, "Save profile as", "Profile name")
        name = name.strip()
        if not ok or not name:
            return
        if name in self.profile_manager.list_names():
            warn(self, "Profile exists", "Choose a new profile name.")
            return
        profile_settings = deepcopy(self.run_settings)
        profile_settings.pop("review_inbox_exact_source_paths", None)
        self.profile_manager.save(
            name,
            profile_settings,
            workflow=self.current_workflow,
        )
        self.current_profile = name
        self.current_profile_metadata = self.profile_manager.load_with_metadata(name)
        self.profile_values = profile_settings
        self.profile_baseline = self._profile_snapshot(self.run_settings, self.current_workflow)
        self.refresh_profile_selector()
        self._update_profile_dirty_state()

    def edit_current_profile(self) -> None:
        self.open_advanced_settings()

    def open_advanced_settings(self) -> None:
        dialog = AdvancedSettingsDialog(
            deepcopy(self.run_settings),
            deepcopy(self.profile_values or self.run_settings),
            build_default_settings(repo_root=self.repo_root_path),
            self.current_workflow,
            self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.run_settings.update(dialog.values())
            self._apply_profile_audio_preference()
            self.refresh_wizard()

    # Command and runner

    def _with_main_folders(self, settings: dict[str, Any]) -> dict[str, Any]:
        """214: these settings with the main output folder from Settings, which a blank Inbox
        evidence folder uses (not the New Review wizard's output field)."""

        return {**settings, "main_output_folder": str(self.app_settings.get("output_folder") or "").strip()}

    def build_command(self, *, run_control_path: Path | None = None) -> CommandSpec:
        if not self.resources.script_path:
            raise ValueError("The packaged Video Mangler.ps1 backend could not be located.")
        settings = self._with_main_folders(deepcopy(self.run_settings))
        if run_control_path is not None:
            settings["run_control_path"] = str(run_control_path)
        settings["repo_root"] = str(self.resources.app_root)
        settings["script_path"] = str(self.resources.script_path)
        settings["python_exe"] = self.resources.python_exe
        settings["ffmpeg_path"] = self.resources.ffmpeg_exe
        settings["ffprobe_path"] = self.resources.ffprobe_exe
        settings["ytdlp_path"] = self.resources.ytdlp_exe
        if str(settings.get("input_kind") or "local") == "url":
            urls, _invalid = _parse_url_lines(str(settings.get("input_path") or ""))
            settings["input_path"] = "\n".join(urls)
        return build_workflow_command(
            settings,
            workflow=self.current_workflow,
            powershell_exe=self.resources.powershell_exe or "powershell",
        )

    def copy_command(self) -> None:
        QApplication.clipboard().setText(self.command_preview.toPlainText())

    def _show_inspection_banner(self, finished: str = "") -> None:
        """237: the audio inspection in the job banner beside Inspect source files."""

        bar = self.audio_inspection_progress
        running = self.audio_inspection_thread is not None and not finished
        if not running and not finished:
            return
        total = max(0, bar.maximum())
        percent = int(bar.value() * 100 / total) if total else None
        title = f"Inspecting {total} source file{'s' if total != 1 else ''}" if total else "Inspecting source files"
        self.audio_inspection_banner.show_job(JobInfo(
            token="audio-inspection", title=title, state="active" if running else finished,
            percent=percent if running else None, detail="" if running else bar.format()))
        bar.setVisible(not running)

    def start_job(self) -> None:
        if (
            self.current_workflow == WORKFLOW_REVIEW_NEW_VIDEOS
            and str(self.run_settings.get("review_inbox_action") or "Scan")
            not in {"Prepare", "TargetedEvidence", "Process"}
        ):
            self.navigate("Review Media Inbox")
            self._refresh_review_inbox_dashboard()
            return
        errors = self.validate_current_run()
        if errors:
            warn(self, "Review is not ready", "\n".join(errors))
            return
        if self.runner_thread is not None:
            return
        # 214: Pause and Skip on Queue / Progress for every run, as Find my bug reports has them.
        control_path = (
            Path(str(self.app_settings.get("temp_folder") or default_temp_folder()))
            / "run-controls"
            / f"run-control-{hashlib.sha256(f'{time.time_ns()}:{id(self)}'.encode('ascii')).hexdigest()[:16]}.json"
        )
        command = self.build_command(run_control_path=control_path)
        inbox = self.current_workflow == WORKFLOW_REVIEW_NEW_VIDEOS
        source = str(self.run_settings.get("input_path") or "Configured folders")
        kind = str(self.run_settings.get("input_kind") or "local")
        if inbox:
            # 224 (F1, then Wave B2a note 1, Decision 8): an Inbox run reads its own configured folders, so
            # whatever New Review's source box still holds (a web address, a local file or folder) is never
            # shown as its source or listed as its queue.
            source, kind = "Configured folders", "local"
        url_items, _invalid_url_items = _parse_url_lines(source)
        if kind == "url":
            source_label = f"{len(url_items)} web video{'s' if len(url_items) != 1 else ''}"
        else:
            source_label = source if inbox else Path(source).name
        source_path = Path(source) if source and not inbox and not _looks_like_url(source) else None
        queue_items: list[str] = []
        if source_path and source_path.exists():
            queue_items = [str(item.resolve()) for item in discover_media_files(source_path)]
        elif url_items:
            queue_items = url_items
        self.run_control = RunControl(control_path)
        self.run_control.write()
        self._own_run_control_path = control_path
        # 214: the run's own settings, as build_command read them; what the run reports later
        # comes from this snapshot, not from run_settings, which New Review keeps editing.
        snapshot = self._with_main_folders(deepcopy(self.run_settings))
        self._launch_run(
            command,
            workflow_label=WORKFLOW_BY_NUMBER[self.current_workflow].display_name,
            source_label=source_label,
            profile_label=self.current_profile or "Recommended settings",
            output_label=run_output_folder(snapshot, inbox=inbox),
            queue_items=queue_items,
            run_settings=snapshot,
            workflow=self.current_workflow,
            inbox=inbox,
            origin="Review Media Inbox" if inbox else "New Review",
            kind=WIZARD_RUN_KINDS.get(self.current_workflow, "other"),
            # 243: the Inbox lists its recordings only when it ends (its journal), never from the input box.
            record_items=[] if inbox else None,
        )
        self._refresh_run_control_buttons()
        if not (
            self.current_workflow == WORKFLOW_REVIEW_NEW_VIDEOS
            and str(self.run_settings.get("review_inbox_action") or "") == "Process"
        ):
            self.navigate("Queue / Progress")
        self.refresh_review_summary()

    def _launch_run(
        self,
        command: CommandSpec,
        *,
        workflow_label: str,
        source_label: str,
        profile_label: str,
        output_label: str,
        queue_items: list[str],
        run_settings: dict[str, Any],
        workflow: str,
        inbox: bool = False,
        origin: str = "",
        banner_title: str = "",
        kind: str = "",
        record_items: list[str] | None = None,
        run_id: str = "",
    ) -> None:
        """Start the backend on the shared runner and reset the Progress page.

        ``origin`` is the page that started it, whose job banner shows it (237); ``banner_title``
        is what that banner says is running, the workflow's name when left out. ``kind`` names the
        run in the library (243), and ``record_items`` are its recordings when ``queue_items`` are
        only the names Progress shows.
        """

        # 135: a waveform build never reads the disk alongside a run; it carries on afterwards.
        self.levels_service.stop_for_run()
        self.active_run = {
            "settings": run_settings,
            "workflow": workflow,
            "inbox": inbox,
            "output": output_label,
        }
        self.run_log_path = new_workbench_log_path(
            Path(str(self.app_settings.get("log_folder") or default_log_folder()))
        )
        # 243: the run is in the library before it starts, so a crash or a close cannot lose it.
        self.active_run["run_id"] = self._open_run_record(
            kind or "other", record_items if record_items is not None else queue_items, origin, run_id)
        self.run_log_lines = []
        self.run_started_monotonic = time.monotonic()
        self.run_started_wall = time.time()
        self._job_number += 1
        self._job_eta_seconds = None
        self._job = JobInfo(token=f"job-{self._job_number}", title=banner_title or workflow_label,
                            origin=origin, state="waiting")
        self._write_workbench_log(f"Command: {command.preview}")
        self._set_progress_state("Starting", "Preparing the local review")
        self._set_progress_operator_state(
            "waiting", "Waiting for the first processing update"
        )
        self.progress_workflow.setText(workflow_label)
        self.progress_source.setText(source_label)
        self.progress_profile.setText(profile_label)
        self.progress_output.setText(output_label)
        self._initialize_progress_queue(queue_items)
        known_total = len(queue_items)
        self.progress_queue.setText(str(known_total) if known_total else "Unknown")
        self.progress_completed.setText("0")
        self.progress_remaining.setText(str(known_total) if known_total else "Unknown")
        self.progress_blocked.setText("0")
        self.progress_failed.setText("0")
        self.progress_eta.setText("Estimating…")
        self.progress_outcomes.setText("0 / unknown")
        self.progress_artifacts.setText("0 / unknown")
        self.progress_heartbeat.setText("Waiting for processing")
        self.progress_current_file.setText("Waiting for the first item")
        self.progress_current_file.setToolTip("")
        self.progress_log.clear()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("Waiting for stage details")
        self.overall_progress_bar.setRange(0, 0)
        self.overall_progress_bar.setFormat(
            "Waiting for queue totals" if not known_total else "0 of %d items complete" % known_total
        )
        if known_total:
            self.overall_progress_bar.setRange(0, known_total)
            self.overall_progress_bar.setValue(0)
        self.structured_progress_seen = False
        self.progress_warning_count = 0
        self.progress_completion_summary.clear()
        self.progress_completion_summary.setVisible(False)
        self.last_progress_event_monotonic = time.monotonic()
        self.last_progress_phase = ""
        self.cancel_button.setEnabled(True)
        self.open_progress_evidence_button.setEnabled(False)
        self.runner_thread = RunnerThread(
            command,
            str(self.resources.app_root),
            self.runner_factory,
        )
        self.runner_thread.log_line.connect(self.on_log_line)
        self.runner_thread.finished_result.connect(self.on_job_finished)
        self.runner_thread.start()
        self.elapsed_timer.start()
        self._job_update()
        self.run_availability_changed.emit()

    def start_external_run(
        self,
        command: CommandSpec,
        *,
        title: str,
        settings: dict[str, Any],
        queue_items: list[str],
        listener: Any,
        evidence_package: bool = True,
        origin: str = "",
        banner_title: str = "",
        kind: str = "",
        record_items: list[str] | None = None,
        run_id: str = "",
    ) -> bool | str:
        """Run a command for another page on the shared runner.

        Returns the run's own number in the library (243), or True when the library could not be
        opened; False when another run is going. The page's ``on_finished`` gets the same number as
        ``result.run_id``, for writing each recording's outcome when it knows it.

        The run shows on Queue / Progress, writes the Workbench run log and is
        recorded in History like any other review. ``listener`` receives every
        log line (``on_log_line``) and the final result (``on_finished``).

        ``evidence_package=False`` is for runs whose output is not the
        operator's evidence package (the AI Video Editor, 150): a package they
        leave behind does not become the last evidence package and does not
        open on Evidence.
        """

        if self.runner_thread is not None:
            self.report_run_in_progress()
            return False
        if kind == "bug_reports":
            # Installer plan, Stage 3: Find my bug reports checks its Whisper models like the main Start does.
            blockers = self.model_blockers([str(settings.get("whisper_model") or ""), VOICE_MODEL])
            if blockers:
                warn(self, "The Whisper model is not ready", "\n\n".join(blockers))
                return False
        count = len(queue_items)
        self.external_run = {
            "title": title,
            "settings": dict(settings),
            "listener": listener,
            "source": queue_items[0] if count == 1 else f"{count} recordings",
            "queue_items": list(queue_items),
            "evidence_package": evidence_package,
        }
        control_path = str(settings.get("run_control_path") or "").strip()
        self.run_control = None
        if control_path:
            self.run_control = RunControl(Path(control_path))
            self.run_control.write()
        self._launch_run(
            command,
            workflow_label=title,
            source_label=(
                Path(queue_items[0]).name
                if count == 1
                else f"{count} recordings"
            ),
            profile_label=str(settings.get("evidence_profile_setup_name") or "Racing evidence preset"),
            output_label=run_output_folder(self.external_run["settings"]),
            queue_items=queue_items,
            run_settings=self.external_run["settings"],
            workflow=normalize_workflow(settings.get("default_workflow")),
            origin=origin,
            banner_title=banner_title,
            kind=kind,
            record_items=record_items,
            run_id=run_id,
        )
        self._refresh_run_control_buttons()
        self.refresh_review_summary()
        return str((self.active_run or {}).get("run_id") or "") or True

    # Skip and pause (114, 115) -------------------------------------------

    def _refresh_run_control_buttons(self) -> None:
        available = self.run_control is not None and self.runner_thread is not None
        self.pause_button.setEnabled(available)
        self.skip_button.setEnabled(available)
        paused = bool(self.run_control and self.run_control.paused)
        self.pause_button.setText("Resume" if paused else "Pause")

    def _notify_run_control_listener(self) -> None:
        if self.external_run is not None:
            listener = self.external_run.get("listener")
            callback = getattr(listener, "on_run_control_changed", None)
            if callable(callback):
                callback()

    def toggle_run_pause(self) -> None:
        if self.run_control is None or self.runner_thread is None:
            return
        paused = not self.run_control.paused
        self.run_control.set_paused(paused)
        if paused:
            self._set_progress_operator_state(
                "paused", "Your PC is free. Press Resume to continue where it was."
            )
        else:
            self._set_progress_operator_state("active", "Resuming")
        self._write_workbench_log("Paused by the operator." if paused else "Resumed by the operator.")
        self._refresh_run_control_buttons()
        self._notify_run_control_listener()

    def _source_path_for_queue_item(self, item: str) -> str:
        queue = list((self.external_run or {}).get("queue_items") or [])
        if item in queue:
            return item
        name = Path(item).name
        for candidate in queue:
            if Path(candidate).name == name:
                return candidate
        return item

    def skip_run_sources(self, sources: list[str]) -> list[str]:
        """Ask the running backend to skip these recordings."""

        if self.run_control is None or self.runner_thread is None:
            return []
        added = self.run_control.skip([self._source_path_for_queue_item(item) for item in sources])
        for source in added:
            self._write_workbench_log(f"Skip requested by the operator: {source}")
            for key in list(self.progress_item_states):
                if key == source or Path(key).name == Path(source).name:
                    if self.progress_item_states[key] in {"pending", "active", "transcribed"}:
                        self.progress_item_states[key] = "skipped"
        if added:
            self._refresh_progress_queue_table()
            self._notify_run_control_listener()
        return added

    def _progress_queue_selection_changed(self) -> None:
        if not self._progress_programmatic_select:
            self._progress_selection_by_user = bool(self.progress_queue_table.selectedIndexes())

    def _skip_selected_progress_items(self) -> Outcome:
        rows = sorted({index.row() for index in self.progress_queue_table.selectedIndexes()})
        items = [self.progress_queue_items[row] for row in rows if 0 <= row < len(self.progress_queue_items)]
        if not items:
            # 237: said beside Skip selected, not in a pop-up.
            return Outcome.failed("Nothing is selected.", "Select the recordings to skip first.")
        added = self.skip_run_sources(items)
        self._progress_selection_by_user = False
        return Outcome.done(f"Skipping {len(added)} recording{'s' if len(added) != 1 else ''}" if added
                            else "Already skipped")

    def _pause_action(self) -> Outcome:
        if self.run_control is None or self.runner_thread is None:
            return Outcome.quiet()
        self.toggle_run_pause()
        return Outcome.done("Paused; your PC is free" if self.run_control.paused else "Resumed")

    def _cancel_action(self) -> Outcome:
        if self.runner_thread is None:
            return Outcome.quiet()
        self.cancel_job()
        # The Inbox asks first; answered No, nothing changed.
        return Outcome.done("Stopping safely") if not self.cancel_button.isEnabled() else Outcome.quiet()

    def _progress_play_targets(self, rows: list[int]) -> list[PlayTarget]:
        """The recordings behind these Progress queue rows (125)."""

        targets: list[PlayTarget] = []
        for row in rows:
            if not 0 <= row < len(self.progress_queue_items):
                continue
            recording = Path(self._source_path_for_queue_item(self.progress_queue_items[row]))
            # A queue row can be a web address, a "Queued item N" stand-in, or
            # only the file name the backend reported. None of those is a file
            # the player could be pointed at, so they get no Play entry.
            if is_video_path(recording) and recording.is_absolute():
                targets.append(PlayTarget(path=recording, label=recording.name))
        return targets

    def _progress_play_sequence(self) -> PlaySequence | None:
        targets = self._progress_play_targets(list(range(len(self.progress_queue_items))))
        # A list of one has nothing next in it.
        return PlaySequence(tuple(targets), label="Progress queue") if len(targets) > 1 else None

    def _show_progress_queue_menu(self, point) -> None:
        row = self.progress_queue_table.indexAt(point).row()
        if row < 0:
            return
        if not self.progress_queue_table.item(row, 0) or not self.progress_queue_table.item(row, 0).isSelected():
            self.progress_queue_table.selectRow(row)
        rows = sorted({index.row() for index in self.progress_queue_table.selectedIndexes()}) or [row]
        menu = QMenu(self)
        # Playing is offered whether or not a run is going (125).
        self.video_opener.add_menu_actions(
            menu, self._progress_play_targets(rows), sequence=self._progress_play_sequence()
        )
        # Skipping only means something while a run is going (114).
        if self.run_control is not None and self.runner_thread is not None:
            if not menu.isEmpty():
                menu.addSeparator()
            action = menu.addAction("Skip this recording")
            action.triggered.connect(self._skip_selected_progress_items)
        # No run and nothing playable on this row: an empty menu would be a
        # small grey box that answers nothing.
        if not menu.isEmpty():
            menu.exec(self.progress_queue_table.viewport().mapToGlobal(point))
        menu.deleteLater()

    def report_run_in_progress(self) -> None:
        QMessageBox.information(
            self,
            "Another review is running",
            "Another review is already running. Watch it on Progress, or wait for it to finish before starting this one.",
        )

    def _active_run_settings(self) -> dict[str, Any]:
        if self.external_run is not None:
            return self.external_run["settings"]
        if self.active_run is not None:
            return self.active_run["settings"]
        return self.run_settings

    def _running_inbox(self) -> bool:
        """214: whether Review Media Inbox started the run going now, decided when it started.

        Opening New Review during an Inbox run switches current_workflow to a wizard workflow, so
        current_workflow cannot answer this while a run is going."""

        if self.active_run is not None:
            return bool(self.active_run.get("inbox"))
        return self.external_run is None and self.current_workflow == WORKFLOW_REVIEW_NEW_VIDEOS

    def _run_output(self) -> str:
        """214: the folder the run going now, or the one that finished last, wrote to."""

        run = self.active_run or self.last_run
        if run is not None:
            return str(run.get("output") or "")
        return run_output_folder(self._with_main_folders(self.run_settings),
                                 inbox=self.current_workflow == WORKFLOW_REVIEW_NEW_VIDEOS)

    def _note_run_output(self, contract: dict[str, Any]) -> None:
        """214: once the Inbox run says where it wrote (its queue, or the batch), that is its folder."""

        run = self.active_run
        if run is None or not run.get("inbox"):
            return
        written = run_output_folder(run["settings"], inbox=True, result=contract)
        if written:
            run["output"] = written
            self.progress_output.setText(written)

    def cancel_job(self) -> None:
        if self.runner_thread:
            inbox_run = self.external_run is None and self._running_inbox()
            if inbox_run:
                answer = warn(
                    self,
                    "Emergency cancellation may require recovery",
                    "Emergency cancel stops the local process immediately. The active operation may not finish cleanly, and crash recovery may be required. Use Stop after current for the normal safe boundary.\n\nCancel immediately?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            if self.run_control is not None and self.run_control.paused:
                # Wake suspended tools so they can be stopped cleanly.
                self.run_control.set_paused(False)
            self.cancel_button.setEnabled(False)
            self.cancel_button.setText("Emergency cancelling…" if inbox_run else "Cancelling…")
            self._set_progress_operator_state(
                "cancelling",
                "Stopping immediately; recovery may be required"
                if inbox_run
                else "Stopping the current review safely",
            )
            self._set_progress_state("Cancelling", "Stopping current processing")
            self.runner_thread.cancel()

    def on_log_line(self, stream: str, line: str) -> None:
        if line.startswith("MM_REVIEW_INBOX_PROCESS_RESULT_V1 "):
            try:
                parsed = json.loads(
                    line[len("MM_REVIEW_INBOX_PROCESS_RESULT_V1 ") :]
                )
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                self.review_inbox_process_result = parsed
                self.review_inbox_final_result = parsed
                self._note_run_output(parsed)
        elif line.startswith("MM_REVIEW_INBOX_RESULT_V1 "):
            try:
                parsed = json.loads(line[len("MM_REVIEW_INBOX_RESULT_V1 ") :])
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                self.review_inbox_final_result = parsed
                self._note_run_output(parsed)
        if self.external_run is not None:
            listener = self.external_run.get("listener")
            if listener is not None:
                listener.on_log_line(stream, line)
        formatted = f"[{stream}] {line}"
        self.run_log_lines.append(formatted)
        # Machine progress records drive the page and stay in the run log
        # file; on screen they would bury the readable lines (105).
        if not line.startswith("MM_PROGRESS_V1 "):
            self.progress_log.appendPlainText(formatted)
        self._write_workbench_log(formatted)
        # 213: only what the backend marks as a warning counts (run_status).
        if counts_as_warning(line):
            self.progress_warning_count += 1
        self._parse_progress_line(line)

    def _parse_progress_line(self, line: str) -> None:
        if line.startswith("MM_PROGRESS_V1 "):
            try:
                payload = json.loads(line[len("MM_PROGRESS_V1 ") :])
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict) and payload.get("schema") == "MM_PROGRESS_V1":
                self._apply_structured_progress(payload)
                return
        operator_activity = self._operator_progress_activity(line)
        phase_match = re.search(r"(?i)(?:phase|stage)\s*[:=-]\s*(.+)$", line)
        if phase_match and not self._is_technical_progress_text(line):
            self.progress_phase.setText(phase_match.group(1).strip())
        source_match = re.search(r"(?i)(?:processing|source|file)\s*[:=-]\s*(.+\.(?:mp4|mkv|mov|avi|webm))", line)
        fallback_source_name = ""
        if source_match:
            fallback_source_name = source_match.group(1).strip()
            self.progress_current_file.setText(Path(fallback_source_name).name)
            self.progress_current_file.setToolTip(fallback_source_name)
        count_match = re.search(r"(?:\[|\b)(\d+)\s*(?:/|of)\s*(\d+)(?:\]|\b)", line, flags=re.IGNORECASE)
        # A count in an ordinary log line stands in for the queue only for a backend that sends no
        # MM_PROGRESS_V1 records (they carry the real source_total), and a tool's own progress bar
        # never does: Whisper's "0/1372 frames" made a one-recording Inbox run show 1372 items.
        if (
            count_match
            and not self.progress_source_queue_known
            and not self.structured_progress_seen
            and not _TOOL_PROGRESS_BAR.search(line)
        ):
            current = int(count_match.group(1))
            total = max(current, int(count_match.group(2)))
            completed = max(0, current - 1)
            self.progress_queue.setText(str(total))
            self.progress_completed.setText(str(completed))
            self.progress_remaining.setText(str(max(0, total - completed)))
            self.overall_progress_bar.setRange(0, total)
            self.overall_progress_bar.setValue(completed)
            self.overall_progress_bar.setFormat(
                f"{completed} of {total} items complete"
            )
            self._update_progress_queue(
                fallback_source_name, completed, total
            )
        if operator_activity:
            self.progress_message.setText(operator_activity[:300])
            self._set_progress_operator_state(
                "active", self.progress_message.text()
            )

    @staticmethod
    def _is_technical_progress_text(text: str) -> bool:
        stripped = text.strip()
        lowered = stripped.casefold()
        return bool(
            stripped.startswith("[")
            or "command:" in lowered
            or "stage loading_model" in lowered
            or re.search(r"(?i)(?:[a-z]:\\|\\\\|/users/|/home/)", stripped)
            or re.search(r"(?i)\bdevice\s+(?:cuda|cpu)\b", stripped)
        )

    @classmethod
    def _operator_progress_activity(cls, text: str) -> str:
        stripped = text.strip()
        if not stripped:
            return ""
        lowered = stripped.casefold()
        if "loading_model" in lowered or "loading whisper" in lowered:
            return "Loading the transcription model"
        if "transcrib" in lowered:
            return "Transcribing the current source"
        if "processing" in lowered:
            return "Processing the current source"
        if "ffmpeg" in lowered or "ffprobe" in lowered or "extracting" in lowered:
            return "Preparing media for local review"
        if "command:" in lowered:
            return "Preparing local review tools"
        if "still working" in lowered or "heartbeat" in lowered:
            return "Processing is still active"
        if cls._is_technical_progress_text(stripped):
            return ""
        return stripped

    @staticmethod
    def _progress_state_label(state: str) -> str:
        return PROGRESS_STATE_LABELS.get(state, state.replace("_", " ").title())

    def _set_progress_operator_state(self, state: str, detail: str) -> None:
        label = self._progress_state_label(state)
        self.progress_state_banner.setText(
            f"{label} — {detail}" if detail else label
        )
        self.progress_state_banner.setProperty("operatorState", state)
        self.progress_state_banner.setAccessibleName(f"Review state: {label}")
        self.progress_state_banner.style().unpolish(self.progress_state_banner)
        self.progress_state_banner.style().polish(self.progress_state_banner)
        kind = status_kind(state)
        for widget in (
            getattr(self, "overall_progress_bar", None),
            getattr(self, "progress_bar", None),
            getattr(self, "progress_phase", None),
            getattr(self, "progress_heartbeat", None),
        ):
            if widget is None:
                continue
            widget.setProperty("operatorState" if isinstance(widget, QProgressBar) else "statusKind", kind)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        if self._job is not None and (self.runner_thread is not None or self._job.running):
            self._job_update(self._job_state_for(state), detail)

    def _initialize_progress_queue(self, source_items: list[str]) -> None:
        self.progress_queue_items = list(dict.fromkeys(source_items))
        self.progress_source_queue_known = bool(self.progress_queue_items)
        self.progress_item_states = {
            item: "pending" for item in self.progress_queue_items
        }
        self.progress_active_item = ""
        self._refresh_progress_queue_table()
        self._sync_source_queue_summary()

    def _progress_source_key(self, source_name: str) -> str:
        source_name = source_name.strip()
        if not source_name:
            return ""
        source_folded = source_name.casefold()
        source_basename = Path(source_name).name.casefold()
        for item in self.progress_queue_items:
            if item.casefold() == source_folded or Path(item).name.casefold() == source_basename:
                return item
        if self.progress_source_queue_known:
            return ""
        placeholder = next(
            (
                item
                for item in self.progress_queue_items
                if item.startswith("Queued item ")
                and self.progress_item_states.get(item) == "pending"
            ),
            "",
        )
        if placeholder:
            index = self.progress_queue_items.index(placeholder)
            self.progress_queue_items[index] = source_name
            self.progress_item_states.pop(placeholder, None)
            self.progress_item_states[source_name] = "pending"
            return source_name
        self.progress_queue_items.append(source_name)
        self.progress_item_states[source_name] = "pending"
        return source_name

    def _set_progress_item_state(self, source_key: str, state: str) -> None:
        if not source_key:
            return
        if source_key not in self.progress_queue_items:
            if self.progress_source_queue_known:
                return
            self.progress_queue_items.append(source_key)
        current = self.progress_item_states.get(source_key, "pending")
        if current in TERMINAL_PROGRESS_ITEM_STATES and state != current:
            self._write_workbench_log(
                f"Ignored invalid queue state transition for {source_key}: {current} -> {state}"
            )
            return
        self.progress_item_states[source_key] = state
        self._refresh_progress_queue_table()
        self._sync_source_queue_summary()

    def _sync_source_queue_summary(self) -> None:
        if not self.progress_source_queue_known or not self.progress_queue_items:
            return
        # 199: a recording with no narration finished normally, so it counts as completed.
        completed = sum(
            self.progress_item_states.get(item) in {"completed", "no_narration"}
            for item in self.progress_queue_items
        )
        finished = sum(
            self.progress_item_states.get(item) in TERMINAL_PROGRESS_ITEM_STATES
            for item in self.progress_queue_items
        )
        total = len(self.progress_queue_items)
        failed = sum(
            self.progress_item_states.get(item) == "failed"
            for item in self.progress_queue_items
        )
        self.progress_queue.setText(str(total))
        self.progress_completed.setText(str(completed))
        self.progress_failed.setText(str(failed))
        self.progress_failed.setProperty("statusKind", "failed" if failed else "")
        self.progress_failed.style().unpolish(self.progress_failed)
        self.progress_failed.style().polish(self.progress_failed)
        self.progress_remaining.setText(str(max(0, total - finished)))
        self.overall_progress_bar.setRange(0, total)
        self.overall_progress_bar.setValue(finished)
        transcribed = sum(
            self.progress_item_states.get(item) == "transcribed"
            for item in self.progress_queue_items
        )
        # A transcribed recording still gets screenshots and clips, so it is
        # not finished yet; say so instead of calling it complete (105).
        self.overall_progress_bar.setFormat(
            f"{finished} of {total} items finished"
            + (f" · {transcribed} transcribed, making screenshots and clips" if transcribed else "")
        )
        self._job_update()

    def _refresh_progress_queue_table(self) -> None:
        if not hasattr(self, "progress_queue_table"):
            return
        self.progress_queue_table.setRowCount(len(self.progress_queue_items))
        for row, source_key in enumerate(self.progress_queue_items):
            state = self.progress_item_states.get(source_key, "pending")
            state_item = QTableWidgetItem(self._progress_state_label(state))
            state_item.setData(Qt.ItemDataRole.UserRole, state)
            state_item.setForeground(status_color(state))
            bold = state_item.font()
            bold.setBold(state != "pending")
            state_item.setFont(bold)
            name = source_key if _looks_like_url(source_key) else Path(source_key).name
            name_item = QTableWidgetItem(name)
            name_item.setToolTip(source_key)
            self.progress_queue_table.setItem(row, 0, state_item)
            self.progress_queue_table.setItem(row, 1, name_item)
            self.progress_queue_table.setRowHidden(row, False)
            if source_key == self.progress_active_item and not self._progress_selection_by_user:
                # Follow the active recording unless the operator picked rows
                # (for example to skip them, 114).
                self._progress_programmatic_select = True
                try:
                    self.progress_queue_table.selectRow(row)
                finally:
                    self._progress_programmatic_select = False

    def _update_progress_queue(
        self,
        source_name: str,
        source_completed: int,
        source_total: int,
    ) -> None:
        source_key = self._progress_source_key(source_name) if source_name else ""
        if source_key:
            self.progress_active_item = source_key
            if self.progress_item_states.get(source_key) not in TERMINAL_PROGRESS_ITEM_STATES | {"transcribed"}:
                self.progress_item_states[source_key] = "active"
            display_name = source_name if _looks_like_url(source_name) else Path(source_name).name
            self.progress_current_file.setText(display_name)
            self.progress_current_file.setToolTip(source_name)
        if self.progress_source_queue_known:
            self._refresh_progress_queue_table()
            self._sync_source_queue_summary()
            return
        if source_total > len(self.progress_queue_items):
            for index in range(len(self.progress_queue_items), source_total):
                placeholder = f"Queued item {index + 1}"
                self.progress_queue_items.append(placeholder)
                self.progress_item_states[placeholder] = "pending"
        self._refresh_progress_queue_table()

    def _apply_structured_progress(self, payload: dict[str, Any]) -> None:
        self.structured_progress_seen = True
        self.last_progress_event_monotonic = time.monotonic()
        phase = str(payload.get("phase") or "Working")
        phase_changed = phase != self.last_progress_phase
        if phase_changed:
            self.last_progress_phase = phase
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("Stage in progress")
        self.progress_phase.setText(PHASE_DISPLAY_NAMES.get(phase, phase))
        source_name = str(payload.get("source_name") or payload.get("source_id") or "")
        source_ordinal = int(payload.get("source_ordinal") or 0)
        phase_index = int(payload.get("phase_index") or 0)
        phase_count = int(payload.get("phase_count") or 0)
        kind = str(payload.get("progress_kind") or "indeterminate")
        completed = int(payload.get("completed") or 0)
        total = int(payload.get("total") or 0)
        if kind == "work_units" and total > 0:
            set_work_bar(self.progress_bar, completed, total)
            # 224 (Wave B2a, 272): in what the step counts, "04:12 of 22:30" for a recording's seconds.
            unit = str(payload.get("work_unit") or "")
            self.progress_bar.setFormat(work_done_text(completed, total, unit) + ("" if unit else " stage units"))
        else:
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setFormat("Stage in progress — exact percentage unavailable")
        source_completed = int(payload.get("source_completed") or 0)
        source_total = int(payload.get("source_total") or 0)
        if self.progress_source_queue_known:
            self._sync_source_queue_summary()
        elif source_total:
            self.progress_queue.setText(str(source_total))
            self.progress_completed.setText(str(source_completed))
            self.progress_remaining.setText(str(max(0, source_total - source_completed)))
            self.overall_progress_bar.setRange(0, source_total)
            self.overall_progress_bar.setValue(
                max(0, min(source_total, source_completed))
            )
            self.overall_progress_bar.setFormat(
                f"{source_completed} of {source_total} items complete"
            )
        elif phase_count > 0:
            self.overall_progress_bar.setRange(0, phase_count)
            self.overall_progress_bar.setValue(
                max(0, min(phase_count, phase_index - 1))
            )
            self.overall_progress_bar.setFormat(
                f"Stage {max(1, phase_index)} of {phase_count}"
            )
        else:
            self.overall_progress_bar.setRange(0, 0)
            self.overall_progress_bar.setFormat(
                "Overall percentage unavailable"
            )
        self._update_progress_queue(source_name, source_completed, source_total)
        if source_name and source_ordinal and source_total:
            display_name = source_name if _looks_like_url(source_name) else Path(source_name).name
            self.progress_current_file.setText(f"{display_name} ({source_ordinal} of {source_total})")
        self.progress_blocked.setText(str(int(payload.get("blocked_count") or 0)))
        self.progress_failed.setText(str(int(payload.get("failed_count") or 0)))
        item_state = str(payload.get("source_state") or "")
        if source_name and item_state in {
            "pending",
            "active",
            "completed",
            "failed",
            "skipped",
            "cancelled",
            "waiting",
            "no_narration",
            "transcribed",
        }:
            source_terminal = bool(payload.get("source_terminal"))
            if item_state not in TERMINAL_PROGRESS_ITEM_STATES or source_terminal:
                self._set_progress_item_state(
                    self._progress_source_key(source_name), item_state
                )
        self._sync_source_queue_summary()
        outcome_completed = int(payload.get("outcome_completed") or 0)
        outcome_total = int(payload.get("outcome_total") or 0)
        artifact_completed = int(payload.get("artifact_completed") or 0)
        artifact_total = int(payload.get("artifact_total") or 0)
        self.progress_outcomes.setText(f"{outcome_completed} / {outcome_total or 'unknown'}")
        self.progress_artifacts.setText(f"{artifact_completed} / {artifact_total or 'unknown'}")
        eta_state = str(payload.get("eta_state") or "unavailable")
        self._job_eta_seconds = (float(payload["eta_seconds"]) if eta_state == "available"
                                 and payload.get("eta_seconds") is not None else None)
        if eta_state == "available" and payload.get("eta_seconds") is not None:
            self.progress_eta.setText(self._audio_time_text(int(float(payload["eta_seconds"]) * 1000)))
        elif eta_state == "estimating":
            self.progress_eta.setText("Estimating…")
        else:
            self.progress_eta.setText("Unavailable")
        terminal_state = str(payload.get("terminal_state") or "")
        self.progress_warning_count = max(
            self.progress_warning_count,
            int(payload.get("warning_count") or 0),
        )
        if terminal_state in {"succeeded", "succeeded_with_warnings", "complete_with_warnings"}:
            if terminal_state != "succeeded":
                self.progress_warning_count = max(1, self.progress_warning_count)
            self.progress_heartbeat.setText("Complete")
            self.progress_eta.setText("Unavailable")
            state = (
                "complete_with_warnings"
                if self.progress_warning_count
                else "completed"
            )
            self._set_progress_operator_state(
                state,
                "Processing finished; final results are being prepared",
            )
        elif terminal_state == "failed":
            self.progress_heartbeat.setText("Failed")
            self.progress_eta.setText("Unavailable")
            self._set_progress_operator_state(
                "failed", "Processing stopped before all items completed"
            )
        elif terminal_state == "cancelled":
            self.progress_heartbeat.setText(run_stage_text(RUN_CANCELLED))
            self.progress_eta.setText("Unavailable")
            self._set_progress_operator_state(
                "cancelled", "Processing stopped at the operator's request"
            )
        else:
            self.progress_heartbeat.setText("Active")
            state = (
                "waiting"
                if str(payload.get("activity_state") or "") == "waiting"
                else "active"
            )
            operator_activity = self._operator_progress_activity(
                str(payload.get("activity") or "")
            )
            self._set_progress_operator_state(
                state,
                operator_activity or phase.replace("_", " ") or "Processing",
            )
        activity = str(payload.get("activity") or "")
        operator_activity = self._operator_progress_activity(activity)
        if operator_activity:
            self.progress_message.setText(operator_activity[:300])
        latest = str(payload.get("latest_artifact_path") or "")
        if latest and self.latest_frame_preview_checkbox.isChecked() and Path(latest).is_file():
            pixmap = QPixmap(latest)
            if not pixmap.isNull():
                self.latest_frame_preview.setPixmap(
                    pixmap.scaled(640, 220, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                )
        self._apply_review_inbox_structured_progress(payload)
        self._job_update()

    def _set_progress_state(self, phase: str, message: str) -> None:
        self.progress_phase.setText(phase)
        self.progress_message.setText(message)

    def _refresh_elapsed(self) -> None:
        if self.run_started_monotonic:
            elapsed = max(0, int(time.monotonic() - self.run_started_monotonic))
            self.progress_elapsed.setText(f"{elapsed // 3600:02d}:{(elapsed % 3600) // 60:02d}:{elapsed % 60:02d}")
        if self.runner_thread is not None and self.structured_progress_seen:
            silence = time.monotonic() - self.last_progress_event_monotonic
            if silence > 30:
                self.progress_heartbeat.setText(f"Warning: no event for {int(silence)}s")
                self._set_progress_operator_state(
                    "waiting",
                    f"No processing update for {int(silence)} seconds; cancellation remains available",
                )

    def on_job_finished(self, result: RunnerResult) -> None:
        thread = self.runner_thread
        self.runner_thread = None
        self.run_control = None
        # 243: the page that started the run writes each recording's outcome into this run.
        result.run_id = str((self.active_run or {}).get("run_id") or "")
        own_control, self._own_run_control_path = self._own_run_control_path, None
        if own_control is not None:
            try:
                own_control.unlink(missing_ok=True)
            except OSError:
                pass
        self._refresh_run_control_buttons()
        self.elapsed_timer.stop()
        self._refresh_elapsed()
        # Exit code 2 means the backend wrote the package but some recordings
        # could not be used. That is a partial success, not a failed run (105).
        partial = (
            result.status == "failed"
            and result.exit_code == 2
            and self._discover_completed_evidence_package() is not None
        )
        # 243: what the backend itself reported for each recording, before the queue is closed and the
        # recordings it never reported on are given a state by the end of the run.
        reported_states = dict(self.progress_item_states)
        self._finalize_progress_queue("succeeded" if partial else result.status)
        self.progress_eta.setText("Unavailable")
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("Cancel review")
        self.cancel_button.setToolTip("")
        self.stop_after_current_button.setVisible(False)
        self.stop_after_current_button.setEnabled(False)
        self.stop_after_current_button.setText("Stop after current file")
        if result.status == "succeeded":
            # 213: the one status rule (run_status) for every feature.
            state = decide_run_status(succeeded=True, warnings=self.progress_warning_count)
            self._set_progress_operator_state(
                state,
                "Review completed; results are ready"
                if not self.progress_warning_count
                else f"Review completed with {self.progress_warning_count} warning(s); inspect the results before continuing",
            )
            self.progress_heartbeat.setText(run_stage_text(state))
            self._set_progress_state(
                run_stage_text(state),
                "Review completed; use Open output or Open evidence package for the next step",
            )
            if self.overall_progress_bar.maximum() > 0:
                self.overall_progress_bar.setValue(
                    self.overall_progress_bar.maximum()
                )
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(1)
            self.progress_bar.setFormat("Current stage complete")
        elif result.status == "cancelled":
            cancelled = run_stage_text(RUN_CANCELLED)
            self.progress_heartbeat.setText(cancelled)
            self._set_progress_operator_state(
                "cancelled", "Review stopped safely at the operator's request"
            )
            self._set_progress_state(cancelled, "The review was cancelled")
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat(cancelled)
        else:
            failure = _operator_error_text(result.error)
            completed_count = sum(
                state == "completed" for state in self.progress_item_states.values()
            )
            failed_count = sum(
                state == "failed" for state in self.progress_item_states.values()
            )
            if partial or (completed_count and failed_count):
                attention_count = sum(
                    state in {"failed", "no_narration"}
                    for state in self.progress_item_states.values()
                )
                self.progress_heartbeat.setText("Completed with problems")
                self._set_progress_operator_state(
                    "completed_with_problems",
                    f"{completed_count} item(s) completed and {attention_count} item(s) need attention",
                )
                self._set_progress_state(
                    "Completed with problems",
                    "Successful packages are ready. Review the failed item rows and open Technical details for their recorded errors.",
                )
            else:
                self.progress_heartbeat.setText("Failed")
                self._set_progress_operator_state(
                    "failed", failure[:240]
                )
                self._set_progress_state(
                    "Failed",
                    f"{failure} Open Technical details for the recorded log.",
                )
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat(
                "Completed with problems" if partial or (completed_count and failed_count) else "Failed"
            )
        technical_result = (
            f"Run finished: status={result.status}, "
            f"exit_code={result.exit_code}, error={result.error}"
        )
        self.progress_log.appendPlainText(technical_result)
        self._write_workbench_log(technical_result)
        self._record_recent_run(
            result, status="completed with problems" if partial else result.status
        )
        external = self.external_run
        inbox_run = external is None and self._running_inbox()
        claims_package = external is None or external.get("evidence_package", True)
        package_path = None if inbox_run or not claims_package else self._discover_completed_evidence_package()
        if external is None and not inbox_run:
            self._record_wizard_outcomes(result, reported_states, package_path, partial=partial)
        if package_path:
            self.app_settings["last_evidence_package"] = str(package_path)
            self.open_progress_evidence_button.setEnabled(True)
            if external is not None:
                # The page that started the run decides what to show; the
                # package still opens on Evidence like any other review.
                try:
                    self.load_package(package_path)
                except Exception:  # noqa: BLE001 - the listener reports package problems
                    pass
            elif result.status == "succeeded" or partial:
                self.load_package(package_path)
                self.navigate("Queue / Progress")
        self._remember_output_folder()
        self._queue_waveforms_after_run(result, partial=partial, external=external)
        self.last_run, self.active_run = self.active_run, None
        self.external_run = None
        self.save_app_settings()
        self.refresh_home()
        self.refresh_history()
        self.refresh_review_summary()
        if inbox_run:
            self._apply_review_inbox_completion(result)
        if external is not None and external.get("listener") is not None:
            external["listener"].on_finished(result)
        self.run_availability_changed.emit()
        if thread:
            thread.deleteLater()

    # 135: the workflows whose recordings get their waveforms built once the run has finished. Raw bin
    # scans already store their levels, and the AI Video Editor's runs are its own (Wave 7).
    _WAVEFORM_WORKFLOWS = (WORKFLOW_FULL_REVIEW, WORKFLOW_TRANSCRIPT_ONLY, WORKFLOW_CODEX_EVIDENCE,
                           WORKFLOW_REVIEW_NEW_VIDEOS)

    def _queue_waveforms_after_run(self, result: RunnerResult, *, partial: bool, external: dict[str, Any] | None) -> None:
        if not self.levels_service.enabled:
            return
        finished = result.status == "succeeded" or partial or any(
            state == "completed" for state in self.progress_item_states.values()
        )
        if not finished:
            return
        if external is not None:
            # Find my bug reports writes the evidence package; the Raw bin and the AI Video Editor do not.
            if not external.get("evidence_package", True):
                return
        elif (self.active_run or {}).get("workflow") not in self._WAVEFORM_WORKFLOWS:
            return
        paths = []
        for item in self.progress_queue_items:
            if self.progress_item_states.get(item) in {"skipped", "failed"}:
                continue
            recording = Path(self._source_path_for_queue_item(item))
            if is_video_path(recording) and recording.is_absolute():
                paths.append(recording)
        if paths:
            self.levels_service.queue(paths)

    def show_external_run_outcome(self, headline: str, *, state: str) -> None:
        """Let the page that started a run state its real outcome on Progress.

        ``state`` is ``completed``, ``completed_with_problems`` or ``failed``.
        """

        stage = run_stage_text(state)
        self._set_progress_state(stage, headline)
        self._set_progress_operator_state(state, headline[:240])
        # 199: the Activity line says the page's outcome too, not what the backend's exit code
        # or its log's warnings suggested ("Failed" or "Complete with warnings" for a run whose
        # only outcome was a recording with no narration).
        self.progress_heartbeat.setText(stage)
        # And the Current step bar, which the backend's exit code may have left at "Failed".
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1 if state == "completed" else 0)
        self.progress_bar.setFormat(stage)
        # And History: the run said what the exit code suggested; the page's outcome corrects it, in the
        # same run of the library (243), however late it comes.
        run_id = getattr(self, "_last_external_run_id", "")
        if self.records is not None and run_id:
            try:
                if self.records.finish_run(run_id, state, headline=headline[:500], reported_by="page"):
                    self.refresh_home()
                    self.refresh_history()
            except (OSError, sqlite3.Error, ValueError) as exc:
                self._write_workbench_log(f"The run's outcome could not be written to the library: {exc}")
        entry = getattr(self, "_last_external_run_entry", None)
        recorded = str((entry or {}).get("status") or "")
        corrected = {
            "completed": "" if recorded == "succeeded" else "completed",
            "completed_with_problems": "completed with problems" if recorded == "failed" else "",
        }.get(state, "")
        if entry is not None and corrected:
            entry["status"] = corrected
            self._last_external_run_entry = None
            self.save_app_settings()
            self.refresh_home()
            self.refresh_history()
        self.progress_completion_summary.setText(headline)
        self.progress_completion_summary.setVisible(True)

    def _record_inbox_outcomes(self, runner_result: RunnerResult, payload: dict[str, Any]) -> None:
        """243: each recording this Inbox run took, with where the Inbox's records in the library say it stands
        now (224, Wave B2b)."""

        run_id = str(getattr(runner_result, "run_id", "") or "")
        if self.records is None or not run_id:
            return
        if not payload:
            # The Inbox ended without a complete local queue status: nothing was assumed (the Inbox page
            # says Needs attention), and History says it did not finish.
            try:
                self.records.finish_run(run_id, "failed", headline="Processing ended without a complete local "
                                        "queue status. No completion was assumed.", reported_by="Review Media Inbox")
            except (OSError, sqlite3.Error, ValueError):
                pass
            return
        orchestration_run = str(self._review_inbox_contract_run(payload).get("run_id") or "")
        try:
            self.records.set_feature_ref(run_id, orchestration_run)
            outcomes = recording_records.inbox_run_outcomes(
                self.records.connection(), orchestration_run,
                already_counted=self.records.counted_in_earlier_runs(orchestration_run, run_id))
            if outcomes:
                self.records.record_outcomes(run_id, outcomes, reported_by="Review Media Inbox")
            if payload.get("attention"):
                attention = payload.get("attention")
                message = str(attention.get("message") if isinstance(attention, dict) else attention or "")
                self.records.finish_run(run_id, "completed_with_problems", headline=message[:500],
                                        reported_by="Review Media Inbox")
        except (OSError, sqlite3.Error, ValueError) as exc:
            self._write_workbench_log(f"The Inbox run's outcomes could not be written to the library: {exc}")

    def _apply_review_inbox_process_completion(
        self, runner_result: RunnerResult
    ) -> None:
        payload = self.review_inbox_process_result or {}
        if self.review_inbox_stop_path is not None:
            try:
                self.review_inbox_stop_path.unlink(missing_ok=True)
            except OSError:
                pass
        self.review_inbox_stop_path = None
        self.review_inbox_stop_button.setEnabled(False)
        self.review_inbox_stop_button.setText("Stop after current")
        self.review_inbox_active_action = ""
        self._record_inbox_outcomes(runner_result, payload)
        if not payload:
            self._apply_review_inbox_status(
                {
                    "operator_status": "Needs attention",
                    "queue_counts": self._review_inbox_contract_counts(
                        self.review_inbox_status_contract
                    ),
                    "run_state": self._review_inbox_contract_run(
                        self.review_inbox_status_contract
                    ),
                    "attention": {
                        "message": (
                            "Processing ended without a complete local queue status. "
                            "No completion was assumed."
                        ),
                        "details": runner_result.error or runner_result.status,
                    },
                }
            )
            return
        self._apply_review_inbox_status(payload)
        run = self._review_inbox_contract_run(payload)
        has_decision = any(
            isinstance(payload.get(key), dict) and bool(payload.get(key))
            for key in (
                "audio_choice",
                "cleanup_confirmation",
                "all_pending_confirmation",
            )
        )
        if not bool(run.get("active") or run.get("resumable")) and not has_decision:
            with QSignalBlocker(self.review_inbox_next3_radio):
                self.review_inbox_next3_radio.setChecked(True)
            self._review_inbox_workload_changed()
        if has_decision:
            QTimer.singleShot(
                0,
                lambda contract=dict(payload): self._handle_review_inbox_process_decision(
                    contract
                ),
            )

    def _apply_review_inbox_completion(self, runner_result: RunnerResult) -> None:
        payload = self.review_inbox_final_result or {}
        action = str(payload.get("action") or self.review_inbox_active_action or "Prepare")
        if (
            action.casefold() == "process"
            or self.review_inbox_process_result is not None
        ):
            self._apply_review_inbox_process_completion(runner_result)
            return
        if self.review_inbox_stop_path is not None:
            try:
                self.review_inbox_stop_path.unlink(missing_ok=True)
            except OSError:
                pass
        self.review_inbox_stop_path = None
        if payload and action == "targeted_evidence":
            status = str(payload.get("status") or runner_result.status)
            batch_id = str(payload.get("batch_id") or "")
            batch_path = str(payload.get("batch_path") or "")
            completed = int(payload.get("completed_request_count") or 0)
            total = int(payload.get("request_count") or 0)
            failed_requests = list(payload.get("failed_requests") or [])
            failed = len(failed_requests)
            failure_details = "; ".join(
                f"{str(item.get('finding_id') or 'source')}/{str(item.get('request_id') or 'resolution')}: {str(item.get('error') or 'failed safely')}"
                for item in failed_requests[:3]
                if isinstance(item, dict)
            )
            if status == "targeted_evidence_ready":
                next_action = "Open the integrity-checked targeted evidence and refreshed Codex prompt. External Codex completes issue work and final results; then import those results here."
            elif bool(payload.get("cooperative_stop")):
                next_action = "Rendering stopped after a safe request boundary. Use Render targeted evidence to resume remaining requests."
            else:
                next_action = "Review the failed request details, correct the source or renderer problem, then retry targeted rendering."
            self.review_inbox_completion_summary.setText(
                f"Targeted-evidence result: {status}. Batch {batch_id or 'unknown'} at {batch_path or 'not available'}. "
                f"Requests complete: {completed}/{total}; failed: {failed}. "
                + (f"Failures: {failure_details}. " if failure_details else "")
                + f"Next: {next_action}"
            )
            self.review_inbox_completion_summary.setVisible(True)
            self.progress_completion_summary.setText(self.review_inbox_completion_summary.text())
            self.progress_completion_summary.setVisible(True)
        elif payload:
            prepared = len(payload.get("prepared_sources") or [])
            blocked = len(payload.get("blocked_sources") or [])
            failed = len(payload.get("failed_sources") or [])
            status = str(payload.get("status") or runner_result.status)
            batch_id = str(payload.get("batch_id") or "")
            batch_path = str(payload.get("batch_path") or "")
            stop_reason = str(payload.get("stopped_reason") or "none")
            integrity = "complete" if status == "awaiting_external_review" else "incomplete or resumable"
            cleanup = "bounded working copy removed after each completed attempt"
            next_action = (
                "Open the prepared batch and use the generated External review instructions; validated results can return through this Workbench."
                if status == "awaiting_external_review"
                else "Review blocked or failed sources, resolve the listed action, then rescan or resume the active batch."
            )
            self.review_inbox_completion_summary.setText(
                f"Preparation result: {status}. Batch {batch_id or 'not created'} at {batch_path or 'not available'}. "
                f"Prepared: {prepared}; blocked: {blocked}; failed: {failed}; stop reason: {stop_reason}; "
                f"integrity: {integrity}; scratch cleanup: {cleanup}. Next: {next_action}"
            )
            self.review_inbox_completion_summary.setVisible(True)
            self.progress_completion_summary.setText(self.review_inbox_completion_summary.text())
            self.progress_completion_summary.setVisible(True)
            if batch_id:
                self.review_inbox_active_batch = {
                    "batch_id": batch_id,
                    "status": status,
                    "package_path": batch_path,
                    "created_utc": str(payload.get("updated_utc") or ""),
                    "source_count": prepared + blocked + failed,
                    "blocked_count": blocked,
                    "failed_count": failed,
                }
        else:
            risk = " Recovery may be required because emergency cancellation can interrupt an active attempt." if runner_result.status == "cancelled" else ""
            operation = "Targeted-evidence rendering" if action == "TargetedEvidence" else "Preparation"
            self.review_inbox_completion_summary.setText(
                f"{operation} process ended with status {runner_result.status}, but no complete Review Media Inbox result contract was returned.{risk} Rescan to recover authoritative ledger state."
            )
            self.review_inbox_completion_summary.setVisible(True)
        self.review_inbox_prepare_full_acknowledged = False
        self.review_inbox_active_action = ""
        self.review_inbox_scan_result = None
        self._restore_review_inbox_pending_batch()
        self._refresh_review_inbox_dashboard()
        final_status = str(payload.get("status") or runner_result.status)
        if final_status == "awaiting_external_review":
            self._set_progress_operator_state("completed", "Preparation complete; the batch is awaiting external review")
            self._set_progress_state("Awaiting external review", "Open the prepared batch and follow the external-review, targeted-evidence, and results flow")
        elif final_status == "targeted_evidence_ready":
            self._set_progress_operator_state("completed", "Targeted evidence is integrity-checked and ready for external Codex review")
            self._set_progress_state("Targeted evidence ready", "Open the targeted evidence and refreshed Codex prompt before final issue decisions")
        elif runner_result.status == "succeeded":
            self._set_progress_operator_state("waiting", "Preparation paused safely; the active batch remains resumable")
            self._set_progress_state("Batch paused", "Review blocked or pending sources, then rescan or resume")

    def _finalize_progress_queue(self, result_status: str) -> None:
        preserve_review_inbox_pending = (
            self.external_run is None
            and self._running_inbox()
            and result_status == "succeeded"
        )
        if preserve_review_inbox_pending:
            pass
        elif result_status == "succeeded":
            for item in self.progress_queue_items:
                if self.progress_item_states.get(item) in {"pending", "active", "transcribed"}:
                    self.progress_item_states[item] = "completed"
        elif result_status == "cancelled":
            for item in self.progress_queue_items:
                state = self.progress_item_states.get(item)
                if state == "transcribed":
                    self.progress_item_states[item] = "cancelled"
                elif state == "active":
                    self.progress_item_states[item] = (
                        "cancelled" if item == self.progress_active_item else "completed"
                    )
                elif state == "pending":
                    self.progress_item_states[item] = run_never_ran(RUN_CANCELLED)
        else:
            failed_assigned = any(
                value == "failed" for value in self.progress_item_states.values()
            )
            for item in self.progress_queue_items:
                state = self.progress_item_states.get(item)
                if state == "transcribed":
                    # Transcribed, but the run stopped before its screenshots.
                    self.progress_item_states[item] = "failed"
                    failed_assigned = True
                elif state == "active":
                    self.progress_item_states[item] = (
                        "failed" if item == self.progress_active_item else "completed"
                    )
                    failed_assigned = failed_assigned or item == self.progress_active_item
                elif state == "pending":
                    if not failed_assigned:
                        self.progress_item_states[item] = "failed"
                        failed_assigned = True
                    else:
                        self.progress_item_states[item] = run_never_ran(RUN_FAILED)
        counts = {
            state: sum(value == state for value in self.progress_item_states.values())
            for state in ("completed", "failed", "skipped", "cancelled", "no_narration")
        }
        if self.progress_queue_items:
            self.progress_queue.setText(str(len(self.progress_queue_items)))
            self.progress_completed.setText(str(counts["completed"] + counts["no_narration"]))
            remaining = sum(
                state in {"pending", "active", "waiting"}
                for state in self.progress_item_states.values()
            ) if preserve_review_inbox_pending else 0
            self.progress_remaining.setText(str(remaining))
        self._sync_source_queue_summary()
        # 214: the folder this run wrote to, as Open output and History say it.
        output = self._run_output() or "the selected output folder"
        parts = [f"{counts['completed']} completed"]
        if counts["failed"]:
            parts.append(f"{counts['failed']} failed")
        if counts["no_narration"]:
            parts.append(f"{counts['no_narration']} with no narration")
        if counts["skipped"]:
            parts.append(f"{counts['skipped']} skipped")
        if counts["cancelled"]:
            parts.append(f"{counts['cancelled']} cancelled")
        if self.progress_warning_count:
            parts.append(f"{self.progress_warning_count} warning(s)")
        self.progress_completion_summary.setText(
            "Result: "
            + ", ".join(parts)
            + f". Results location: {output}. Use Open output"
            + (" or Open evidence package" if self.open_progress_evidence_button.isEnabled() else "")
            + "."
        )
        self.progress_completion_summary.setVisible(True)
        self._refresh_progress_queue_table()

    def _run_history_fields(self) -> dict[str, str]:
        """What History shows for the run going now: the fields its list always had (214: the
        workflow, profile and folder the run started with, not what New Review shows now)."""

        settings = self._active_run_settings()
        external = self.external_run
        run = self.active_run or {}
        workflow = (
            normalize_workflow(settings.get("default_workflow"))
            if external is not None
            else normalize_workflow(run.get("workflow") or self.current_workflow)
        )
        if external is not None:
            source = str(external.get("source") or "")
        elif run.get("inbox"):
            # 243: an Inbox run reads the recordings folders, never New Review's input box.
            folders = watched_folders(settings)
            source = folders[0] if len(folders) == 1 else f"{len(folders)} folders" if folders else "Configured folders"
        else:
            source = str(settings.get("input_path") or "Configured folders")
        return {
            "workflow": workflow,
            "title": str(external.get("title")) if external is not None else WORKFLOW_BY_NUMBER[workflow].title,
            "profile": (str(settings.get("evidence_profile_setup_name") or "") if external is not None
                        else self.current_profile),
            "source": source,
            "output": self._run_output(),
            "log": str(self.run_log_path),
        }

    def _record_wizard_outcomes(self, result: RunnerResult, reported: dict[str, str], package_path: Path | None,
                                *, partial: bool) -> None:
        """243: New Review's own outcome for each recording: what the backend reported while it ran, else
        what this run's own files say (Transcript Only's manifest, the ticket package's), else Cancelled for
        one the run never reached, else not reported. The run's state is the one Progress shows (213)."""

        run_id = str(result.run_id or "")
        if self.records is None or not run_id:
            return
        workflow = str((self.active_run or {}).get("workflow") or "")
        since = float(getattr(self, "run_started_wall", 0.0) or 0.0)
        if workflow == WORKFLOW_TRANSCRIPT_ONLY:
            from_files = run_outcomes.transcript_only_outcomes(self._run_output(), since)
        elif workflow == WORKFLOW_CODEX_EVIDENCE:
            from_files = run_outcomes.package_outcomes(package_path, since)
        else:
            from_files = {}
        outcomes = run_outcomes.wizard_outcomes(list(self.progress_queue_items), reported,
                                                dict(self.progress_item_states), from_files)
        if result.status == "succeeded":
            state = decide_run_status(succeeded=True, warnings=self.progress_warning_count)
        elif result.status == "cancelled":
            state = RUN_CANCELLED
        else:
            states = list(self.progress_item_states.values())
            state = ("completed_with_problems" if partial or ("completed" in states and "failed" in states)
                     else "failed")
        try:
            if workflow != WORKFLOW_ARCHIVE_CATALOG:  # it catalogues folders: its run total is its outcome
                self.records.record_outcomes(run_id, outcomes, reported_by="run end")
            self.records.finish_run(run_id, state, reported_by="workbench")
        except (OSError, sqlite3.Error, ValueError) as exc:
            self._write_workbench_log(f"The run's outcomes could not be written to the library: {exc}")

    def _open_run_record(self, kind: str, items: list[str], origin: str, run_id: str = "") -> str:
        """243: write the run to the library as it starts; "" when the library is not open."""

        if self.records is None:
            return ""
        try:
            return self.records.open_run(kind=kind, origin=origin, items=list(items), run_id=run_id,
                                         **self._run_history_fields())
        except (OSError, sqlite3.Error, ValueError) as exc:
            self._write_workbench_log(f"The run could not be written to the library: {exc}")
            return ""

    def _record_recent_run(self, result: RunnerResult, *, status: str = "") -> None:
        """243: the run's process ended. The library keeps it, with what History shows; the page that
        started it states its real outcome afterwards (199). Only when the library could not be opened
        does the run go into the settings' short list, as before."""

        fields = self._run_history_fields()
        run_id = str((self.active_run or {}).get("run_id") or "")
        self._last_external_run_id = run_id if self.external_run is not None else ""
        if self.records is not None and run_id:
            try:
                self.records.end_run(run_id, process_status=result.status, exit_code=result.exit_code,
                                     partial=status == "completed with problems", **fields)
                self._last_external_run_entry = None
                return
            except (OSError, sqlite3.Error, ValueError) as exc:
                self._write_workbench_log(f"The run's end could not be written to the library: {exc}")
        if self._had_records:
            # The library was open in this session: the run is in it (or it ended after the window closed
            # the library, and the next start shows it Interrupted). Never a second copy in settings.json.
            self._last_external_run_entry = None
            return
        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "workflow": fields["workflow"],
            "workflow_title": fields["title"],
            "profile": fields["profile"],
            "source": fields["source"],
            "output": fields["output"],
            "log": fields["log"],
            "status": status or result.status,
        }
        recent = [entry, *list(self.app_settings.get("recent_runs") or [])]
        self.app_settings["recent_runs"] = recent[:30]
        self._last_external_run_entry = entry if self.external_run is not None else None

    def _history_moved(self) -> bool:
        """Whether the run history settings.json kept is in the library (243)."""

        return self.records is not None and str(self.records_move.get("status")) in {"moved", "imported", "nothing"}

    def lists_in_library(self) -> bool:
        """Whether Find my bug reports' lists and its stopped run are kept in the library this session (244):
        once the old ones were moved in, and when settings.json could not be read at all (then the library is
        all there is). While a move could not happen now (it did not check out, or another Workbench is
        moving them) they are read and written in the settings, as before, and moved at the next start."""

        return self.records is not None and str(self.records_move.get("status")) in {
            "moved", "imported", "nothing", "refused"}

    def _settings_history(self) -> list[dict[str, Any]]:
        runs = self.app_settings.get("recent_runs")
        return [run for run in runs if isinstance(run, dict)] if isinstance(runs, list) else []

    def recent_runs(self, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
        """History, newest first (243): every run, from the library, in pages. While the history in
        settings.json could not be moved yet, it is shown after the library's runs, which are newer."""

        if self.records is None:
            return self._settings_history()[offset:offset + limit]
        try:
            runs = self.records.list_runs(limit=limit, offset=offset)
            if self._history_moved() or len(runs) == limit:
                return runs
            older = self._settings_history()
            skip = max(0, offset - self.records.count_runs())
            return runs + older[skip:skip + limit - len(runs)]
        except (OSError, sqlite3.Error, ValueError):
            return []

    def recent_run_count(self) -> int:
        if self.records is None:
            return len(self._settings_history())
        try:
            count = self.records.count_runs()
        except (OSError, sqlite3.Error, ValueError):
            return 0
        return count if self._history_moved() else count + len(self._settings_history())

    def _remember_output_folder(self) -> None:
        if self.external_run is not None or self._running_inbox():
            # Bug-report runs write dated folders under the output folder, and the Inbox writes
            # beside its ledger; the operator's chosen output folder itself stays unchanged.
            return
        output = str(self._active_run_settings().get("output_folder") or "").strip()
        if not output:
            return
        recent = [output, *[str(value) for value in self.app_settings.get("recent_output_folders") or [] if str(value) != output]]
        self.app_settings["recent_output_folders"] = recent[:10]

    def _discover_completed_evidence_package(self) -> Path | None:
        candidates: list[Path] = []
        settings = self._active_run_settings()
        output = str(settings.get("output_folder") or "").strip()
        if output:
            root = Path(output)
            candidates.extend([root / "codex-evidence-package", root])
        evidence_root = "" if self.external_run is not None else review_evidence_root(self._with_main_folders(settings))
        if evidence_root:
            candidates.append(Path(evidence_root))
        for candidate in candidates:
            if (candidate / "CANDIDATE_TICKETS.json").exists() or (candidate / "SESSION_TIMELINE.json").exists():
                return candidate
        existing_roots = [path for path in candidates if path.exists() and path.is_dir()]
        found: list[Path] = []
        for root in existing_roots:
            try:
                found.extend(path.parent for path in root.rglob("PACKAGE_STATUS.json"))
            except OSError:
                continue
        return max(found, key=lambda path: path.stat().st_mtime) if found else None

    # Queue / Progress

    def _build_progress_page(self) -> QWidget:
        page, layout = _page_header(
            "Queue / Progress",
            "What is running now, and how far each recording has got.",
        )
        self.progress_state_banner = QLabel("Pending — no review is running")
        self.progress_state_banner.setObjectName("progressStateBanner")
        self.progress_state_banner.setProperty("operatorState", "pending")
        self.progress_state_banner.setProperty("sectionTitle", True)
        self.progress_state_banner.setWordWrap(True)
        self.progress_state_banner.setAccessibleName("Review state: Pending")
        layout.addWidget(self.progress_state_banner)

        metrics = _card()
        metrics_grid = QGridLayout(metrics)
        for index, (label, attribute) in enumerate(
            (
                ("Queue size", "progress_queue"),
                ("Completed", "progress_completed"),
                ("Remaining", "progress_remaining"),
                ("Blocked", "progress_blocked"),
                ("Failed", "progress_failed"),
                ("Activity", "progress_heartbeat"),
            )
        ):
            name = QLabel(label)
            name.setProperty("muted", True)
            value = QLabel("—")
            value.setProperty("sectionTitle", True)
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            setattr(self, attribute, value)
            # One compact row, so the whole page fits without scrolling.
            metrics_grid.addWidget(name, 0, index)
            metrics_grid.addWidget(value, 1, index)
            metrics_grid.setColumnStretch(index, 1)
        metrics_grid.setVerticalSpacing(2)
        layout.addWidget(metrics)

        current = _card()
        current_layout = QVBoxLayout(current)
        current_layout.addWidget(QLabel("Currently processing"))
        self.progress_current_file = QLabel("No item is active")
        self.progress_current_file.setProperty("sectionTitle", True)
        self.progress_current_file.setWordWrap(True)
        self.progress_current_file.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.progress_current_file.setAccessibleName("Currently processing item")
        current_layout.addWidget(self.progress_current_file)
        stage_grid = QGridLayout()
        self.progress_phase = QLabel("Pending")
        self.progress_phase.setProperty("accent", True)
        self.progress_phase.setWordWrap(True)
        self.progress_elapsed = QLabel("00:00:00")
        self.progress_eta = QLabel("Unavailable")
        stage_grid.addWidget(QLabel("Stage:"), 0, 0)
        stage_grid.addWidget(self.progress_phase, 0, 1, 1, 3)
        stage_grid.addWidget(QLabel("Elapsed:"), 1, 0)
        stage_grid.addWidget(self.progress_elapsed, 1, 1)
        stage_grid.addWidget(QLabel("ETA:"), 1, 2)
        stage_grid.addWidget(self.progress_eta, 1, 3)
        stage_grid.setColumnStretch(1, 1)
        current_layout.addLayout(stage_grid)
        self.progress_message = QLabel("No review is running")
        self.progress_message.setWordWrap(True)
        current_layout.addWidget(self.progress_message)
        current_layout.addWidget(QLabel("Recordings"))
        self.overall_progress_bar = QProgressBar()
        self.overall_progress_bar.setRange(0, 1)
        self.overall_progress_bar.setValue(0)
        self.overall_progress_bar.setFormat("Not started")
        self.overall_progress_bar.setAccessibleName("Overall queue progress")
        current_layout.addWidget(self.overall_progress_bar)
        current_layout.addWidget(QLabel("Current step"))
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Not started")
        self.progress_bar.setAccessibleName("Current-stage progress")
        current_layout.addWidget(self.progress_bar)
        layout.addWidget(current)

        queue_group = QGroupBox("Items in this review")
        queue_layout = QVBoxLayout(queue_group)
        self.progress_queue_table = QTableWidget(0, 2)
        self.progress_queue_table.setHorizontalHeaderLabels(("State", "Item"))
        make_columns_resizable(
            self.progress_queue_table,
            fit_texts={0: list(PROGRESS_STATE_LABELS.values())},
        )
        self.progress_queue_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.progress_queue_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.progress_queue_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.progress_queue_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._progress_selection_by_user = False
        self._progress_programmatic_select = False
        self.progress_queue_table.itemSelectionChanged.connect(self._progress_queue_selection_changed)
        self.progress_queue_table.customContextMenuRequested.connect(self._show_progress_queue_menu)
        # Double-click plays the row (125). The page keeps its own right-click
        # menu, and the resolver asks the disk nothing.
        self.video_opener.attach(
            self.progress_queue_table,
            lambda index: self._progress_play_targets([index.row()]),
            context_menu=False,
            sequence=True,
            label="Progress queue",
        )
        self.progress_queue_table.setMinimumHeight(110)
        self.progress_queue_table.setAccessibleName("Queued review items and states")
        queue_layout.addWidget(self.progress_queue_table)
        # The recordings list takes the spare height instead of empty space.
        layout.addWidget(queue_group, 1)

        preview_controls = QHBoxLayout()
        self.latest_frame_preview_checkbox = QCheckBox("Show latest frame preview (optional)")
        self.latest_frame_preview_checkbox.setChecked(False)
        preview_controls.addWidget(self.latest_frame_preview_checkbox)
        preview_controls.addStretch(1)
        layout.addLayout(preview_controls)
        self.latest_frame_preview = QLabel("Latest-frame preview is off")
        self.latest_frame_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.latest_frame_preview.setMinimumHeight(120)
        self.latest_frame_preview.setVisible(False)
        self.latest_frame_preview_checkbox.toggled.connect(self._set_latest_frame_preview_enabled)
        layout.addWidget(self.latest_frame_preview)

        self.progress_completion_summary = QLabel()
        self.progress_completion_summary.setWordWrap(True)
        self.progress_completion_summary.setProperty("accent", True)
        self.progress_completion_summary.setVisible(False)
        layout.addWidget(self.progress_completion_summary)

        technical_group = QGroupBox("Technical details and processing log")
        technical_group.setCheckable(True)
        technical_group.setChecked(False)
        technical_layout = QVBoxLayout(technical_group)
        technical_content = QWidget()
        technical_content_layout = QVBoxLayout(technical_content)
        technical_content_layout.setContentsMargins(0, 0, 0, 0)
        technical_grid = QGridLayout()
        for index, (label, attribute) in enumerate(
            (
                ("Workflow", "progress_workflow"),
                ("Source", "progress_source"),
                ("Profile", "progress_profile"),
                ("Output", "progress_output"),
                ("Flagged moments done", "progress_outcomes"),
                ("Screenshots / audio clips", "progress_artifacts"),
            )
        ):
            name = QLabel(label)
            name.setProperty("muted", True)
            value = QLabel("—")
            value.setWordWrap(True)
            value.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            setattr(self, attribute, value)
            technical_grid.addWidget(name, index, 0)
            technical_grid.addWidget(value, index, 1)
        technical_content_layout.addLayout(technical_grid)
        self.progress_log = QPlainTextEdit()
        self.progress_log.setReadOnly(True)
        self.progress_log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        ui_theme.keep_scaled(self.progress_log, "setMaximumHeight", 150)
        technical_content_layout.addWidget(self.progress_log)
        technical_layout.addWidget(technical_content)
        technical_content.setVisible(False)
        technical_group.toggled.connect(technical_content.setVisible)
        layout.addWidget(technical_group)

        # 237: the row wraps at a large text size; one line beside it says what the last button did.
        buttons = FlowLayout()
        self.stop_after_current_button = QPushButton("Stop after current file")
        self.stop_after_current_button.setVisible(False)
        self.stop_after_current_button.setEnabled(False)
        self.stop_after_current_button.setToolTip(
            "Requests a cooperative stop at the next safe source boundary; the active source may finish."
        )
        self.cancel_button = QPushButton("Cancel review")
        self.cancel_button.setEnabled(False)
        set_button_kind(self.cancel_button, "danger")
        # 115: pause frees the PC (the running tool is suspended) until Resume.
        self.pause_button = QPushButton("Pause")
        self.pause_button.setEnabled(False)
        self.pause_button.setToolTip("Pause the run so your PC is free; press Resume to continue where it was")
        # 114: skip recordings you do not need, including the one being worked on.
        self.skip_button = QPushButton("Skip selected")
        self.skip_button.setEnabled(False)
        self.skip_button.setToolTip("Skip the selected recordings; the one being worked on stops at once")
        open_log = QPushButton("Open log")
        open_output = QPushButton("Open output")
        self.open_progress_evidence_button = QPushButton("Open evidence package")
        self.open_progress_evidence_button.setEnabled(False)
        self.open_progress_evidence_button.clicked.connect(self.open_last_evidence_package)
        progress_help = QPushButton("Progress help")
        set_button_kind(progress_help, "link")
        progress_help.clicked.connect(
            lambda checked=False: self.open_workbench_help("queue-and-progress")
        )
        layout.addWidget(self.stop_after_current_button, alignment=Qt.AlignmentFlag.AlignLeft)
        for button in (
            self.pause_button,
            self.skip_button,
            self.cancel_button,
            open_log,
            open_output,
            self.open_progress_evidence_button,
            progress_help,
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.progress_actions_feedback = InlineFeedback()
        self.progress_actions_feedback.setObjectName("progressActionsFeedback")
        layout.addWidget(self.progress_actions_feedback)
        for button, action, working, done in (
            (self.stop_after_current_button, self._review_inbox_stop_action, "Asking…", "Stop requested"),
            (self.pause_button, self._pause_action, "Pausing…", "Done"),
            (self.skip_button, self._skip_selected_progress_items, "Skipping…", "Skip requested"),
            (self.cancel_button, self._cancel_action, "Cancelling…", "Stopping"),
            (open_log, self.open_current_log, "Opening…", "Opened"),
            (open_output, self.open_current_output, "Opening…", "Opened"),
        ):
            bind_action(button, action, working=working, done=done, feedback=self.progress_actions_feedback)
        self.open_progress_evidence_button.clicked.connect(self.open_last_evidence_package)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll

    def _set_latest_frame_preview_enabled(self, enabled: bool) -> None:
        self.latest_frame_preview.setVisible(enabled)
        pixmap = self.latest_frame_preview.pixmap()
        if enabled and (pixmap is None or pixmap.isNull()):
            self.latest_frame_preview.setText(
                "Preview enabled. Frames will appear when evidence rendering begins."
            )
        elif not enabled:
            self.latest_frame_preview.setText("Latest-frame preview is off")

    # Evidence browser

    def _build_evidence_page(self) -> QWidget:
        page, layout = _page_header(
            "Evidence",
            "Open a local evidence package and inspect every rendered, lightweight, or review-needed item.",
        )
        toolbar = QHBoxLayout()
        self.evidence_path_edit = QLineEdit()
        self.evidence_path_edit.setReadOnly(True)
        choose = QPushButton("Open package")
        # 237: one primary button per area, as in the approved mockup.
        choose.setProperty("primary", True)
        choose.clicked.connect(self.choose_evidence_package)
        open_folder = QPushButton("Open folder")
        toolbar.addWidget(self.evidence_path_edit, 1)
        toolbar.addWidget(choose)
        toolbar.addWidget(open_folder)
        layout.addLayout(toolbar)
        bind_action(open_folder, lambda: self._open_outcome(self.current_package.root if self.current_package else None,
                                                            "package folder"), working="Opening…", done="Opened")
        self.evidence_quality_status = QLabel("Open a package to view transcript quality status.")
        self.evidence_quality_status.setWordWrap(True)
        self.evidence_quality_status.setProperty("muted", True)
        layout.addWidget(self.evidence_quality_status)
        splitter = QSplitter()
        self.candidate_list = QListWidget()
        self.candidate_list.setMinimumWidth(260)
        self.candidate_list.currentItemChanged.connect(self.on_candidate_selected)
        splitter.addWidget(self.candidate_list)
        # Each row is one moment in one recording, not a list of recordings,
        # so there is nothing "next" to move on to after a never-use.
        self.video_opener.attach(self.candidate_list, self._candidate_play_targets)
        detail_panel = QWidget()
        detail_layout = QVBoxLayout(detail_panel)
        self.candidate_detail = QTextBrowser()
        detail_layout.addWidget(self.candidate_detail, 2)
        self.evidence_file_list = QListWidget()
        self.evidence_file_list.itemDoubleClicked.connect(self.open_evidence_file_item)
        detail_layout.addWidget(self.evidence_file_list, 1)
        self.evidence_image_preview = QLabel("Select an image to preview")
        self.evidence_image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.evidence_image_preview.setMinimumHeight(170)
        self.evidence_image_preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.evidence_file_list.currentItemChanged.connect(self.preview_evidence_file)
        detail_layout.addWidget(self.evidence_image_preview, 2)
        splitter.addWidget(detail_panel)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)
        actions = QGridLayout()
        self.open_candidate_button = QPushButton("Open evidence folder")
        self.open_candidate_button.setEnabled(False)
        self.open_candidate_button.setToolTip("Select an evidence item with an available local folder.")
        self.rerender_candidate_button = QPushButton("Rebuild evidence")
        self.rerender_candidate_button.setEnabled(False)
        self.rerender_candidate_button.setToolTip(
            "Select an evidence item before rebuilding it."
        )
        self.rerender_candidate_button.clicked.connect(self.prepare_candidate_rerender)
        self.export_candidate_prompts_button = QPushButton("Export drafts")
        self.export_candidate_prompts_button.setEnabled(False)
        self.export_candidate_prompts_button.setToolTip(
            "Select an evidence item before exporting its drafts."
        )
        # 125: a button as well as the right-click entry, because a right-click
        # alone would not be found.
        self.play_candidate_button = QPushButton("Play this moment")
        self.play_candidate_button.setProperty("primary", True)
        self.play_candidate_button.setEnabled(False)
        self.play_candidate_button.setToolTip(PLAY_MOMENT_NOTHING_SELECTED)
        evidence_help = QPushButton("Evidence help")
        set_button_kind(evidence_help, "link")
        evidence_help.clicked.connect(
            lambda checked=False: self.open_workbench_help("evidence-and-session-review")
        )
        actions.addWidget(self.open_candidate_button, 0, 0)
        actions.addWidget(self.rerender_candidate_button, 0, 1)
        # Side by side, so the new button takes no height from the lists above.
        actions.addWidget(self.play_candidate_button, 1, 0)
        actions.addWidget(self.export_candidate_prompts_button, 1, 1)
        actions.addWidget(evidence_help, 2, 0, 1, 2)
        actions.setColumnStretch(0, 1)
        actions.setColumnStretch(1, 1)
        layout.addLayout(actions)
        # 237: what the last of these buttons did, right under them.
        self.evidence_actions_feedback = InlineFeedback()
        self.evidence_actions_feedback.setObjectName("evidenceActionsFeedback")
        layout.addWidget(self.evidence_actions_feedback)
        for button, action, working, done in (
            (self.open_candidate_button, self.open_current_candidate_folder, "Opening…", "Opened"),
            (self.export_candidate_prompts_button, self.export_current_prompts, "Exporting…", "Exported"),
            (self.play_candidate_button, self.play_current_candidate_moment, "Opening…", "Playing in the player"),
        ):
            bind_action(button, action, working=working, done=done, feedback=self.evidence_actions_feedback)
        self.open_candidate_status = QLabel("Select an evidence item to open its local folder.")
        self.open_candidate_status.setProperty("muted", True)
        self.open_candidate_status.setWordWrap(True)
        layout.addWidget(self.open_candidate_status)
        return page

    def choose_evidence_package(self) -> None:
        start = str(self.app_settings.get("last_evidence_package") or self.run_settings.get("output_folder") or "")
        path = QFileDialog.getExistingDirectory(self, "Open evidence package", start)
        if path:
            self.load_package(Path(path))

    def load_package(self, path: str | Path) -> EvidencePackage:
        package = load_evidence_package(path)
        self.current_package = package
        self.current_item = None
        self.current_session_mention = None
        self.open_candidate_button.setEnabled(False)
        self.open_candidate_button.setToolTip(
            "Select an evidence item with an available local folder."
        )
        self.rerender_candidate_button.setEnabled(False)
        self.rerender_candidate_button.setToolTip(
            "Select an evidence item before rebuilding it."
        )
        self.export_candidate_prompts_button.setEnabled(False)
        self.export_candidate_prompts_button.setToolTip(
            "Select an evidence item before exporting its drafts."
        )
        self._refresh_play_moment_button(self.play_candidate_button, selected=False, playable=False)
        self.app_settings["last_evidence_package"] = str(package.root)
        self.evidence_path_edit.setText(str(package.root))
        quality = package.package_status.get("quality_summary") or package.manifest.get("quality_summary") or {}
        suspicious = int(quality.get("suspicious_source_count") or 0)
        source_count = int(quality.get("source_count") or 0)
        warning_text = "; ".join(package.package_status.get("warnings") or [])
        if suspicious:
            self.evidence_quality_status.setProperty("accent", True)
            self.evidence_quality_status.setText(
                f"Transcript quality warning: {suspicious} of {source_count or suspicious} source(s) need review. "
                f"{warning_text}".strip()
            )
        else:
            self.evidence_quality_status.setProperty("accent", False)
            self.evidence_quality_status.setText(
                f"Transcript quality: {source_count} source(s), no suspicious source reported."
            )
        self.evidence_quality_status.style().unpolish(self.evidence_quality_status)
        self.evidence_quality_status.style().polish(self.evidence_quality_status)
        self.candidate_list.clear()
        for candidate in package.candidates:
            item = QListWidgetItem(f"{candidate.item_id}  {candidate.title}")
            item.setData(Qt.ItemDataRole.UserRole, candidate.item_id)
            self.candidate_list.addItem(item)
        for candidate in package.unrendered_candidates:
            item = QListWidgetItem(f"{candidate.item_id}  [lightweight]  {candidate.title}")
            item.setData(Qt.ItemDataRole.UserRole, candidate.item_id)
            self.candidate_list.addItem(item)
        for candidate in package.review_needed:
            item = QListWidgetItem(f"{candidate.item_id}  [review needed]  {candidate.title}")
            item.setData(Qt.ItemDataRole.UserRole, candidate.item_id)
            self.candidate_list.addItem(item)
        # 134: after the bug reports, one row per recording with the clips and the small review copy
        # the package made, so they can be played even from a package with no bug reports at all.
        self._narration_files = narration_files(package.root)
        for index, files in enumerate(self._narration_files):
            if files.review_copy is None and not files.clips:
                continue
            item = QListWidgetItem(f"[clips]  {files.source_filename or files.source_id}")
            item.setData(Qt.ItemDataRole.UserRole, f"{CLIPS_ROW_PREFIX}{index}")
            self.candidate_list.addItem(item)
        if self.candidate_list.count():
            self.candidate_list.setCurrentRow(0)
        self.refresh_session_review()
        self.refresh_prompt_previews()
        self.refresh_home()
        self.save_app_settings()
        return package

    def _candidate_by_id(self, item_id: str) -> EvidenceCandidate | None:
        if not self.current_package:
            return None
        return next((item for item in self.current_package.all_items if item.item_id == item_id), None)

    # Playing the recording behind a moment (125). None of these touch the
    # disk: they run on every selection change, and whether the recording is
    # still where it was is the opener's question ("Find it…"), not theirs.

    def _package_recording_path(self, *source_ids: Any) -> str:
        """Where the open package's manifest says this source's recording is."""

        if self.current_package is None:
            return ""
        return recording_for_source(self.current_package.manifest, *source_ids)

    def _moment_play_targets(self, recording_text: str, start_seconds: float, label: str) -> list[PlayTarget]:
        if self.current_package is None or not recording_text or not is_video_path(recording_text):
            return []
        return [
            PlayTarget(
                path=Path(recording_text),
                start_seconds=start_seconds,
                # The package this moment came from is the one whose transcript
                # belongs beside it in the player.
                package_root=self.current_package.root,
                label=label,
            )
        ]

    def _play_targets_for_candidate(self, candidate: EvidenceCandidate | None) -> list[PlayTarget]:
        if candidate is None:
            return []
        raw = candidate.raw
        # The dataclass keeps only a file name; the path is in the record as
        # the backend wrote it, and failing that in the package's source list.
        recording_text = str(raw.get("source_path") or "").strip() or self._package_recording_path(
            raw.get("source_id"), raw.get("physical_source_id")
        )
        stretch_start = (raw.get("timestamp_start_seconds"), candidate.timestamp_start)
        remark = (raw.get("marker_timestamp_seconds"), candidate.marker_timestamp)
        if candidate.item_type == "review-needed":
            # No evidence stretch of its own, only the context around one
            # remark, so it starts at the remark.
            start_seconds = _moment_seconds(*remark, *stretch_start)
        else:
            # From the start of the stretch the evidence covers, so the
            # lead-up to "make this a ticket" is heard too.
            start_seconds = _moment_seconds(*stretch_start, *remark)
        # Either way this is where Session Review lands for the same item: its
        # record is built from these same numbers by the same rule.
        return self._moment_play_targets(recording_text, start_seconds, candidate.title)

    def _candidate_play_targets(self, index: QModelIndex) -> list[PlayTarget]:
        """Resolver for the Evidence list: its rows carry the item's id."""

        return self._play_targets_for_candidate(
            self._candidate_by_id(str(index.data(Qt.ItemDataRole.UserRole) or ""))
        )

    def _refresh_play_moment_button(self, button: QPushButton, *, selected: bool, playable: bool) -> None:
        button.setEnabled(selected and playable)
        if not selected:
            button.setToolTip(PLAY_MOMENT_NOTHING_SELECTED)
        else:
            button.setToolTip(PLAY_MOMENT_READY if playable else PLAY_MOMENT_NO_RECORDING)

    def play_current_candidate_moment(self) -> Outcome:
        targets = self._play_targets_for_candidate(self.current_item)
        if not targets:
            return Outcome.quiet()
        self.video_opener.open(targets[0])
        return Outcome.done("Playing in the player")

    def on_candidate_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if not current:
            self.current_item = None
            self.open_candidate_button.setEnabled(False)
            self.rerender_candidate_button.setEnabled(False)
            self.export_candidate_prompts_button.setEnabled(False)
            self._refresh_play_moment_button(self.play_candidate_button, selected=False, playable=False)
            self.open_candidate_status.setText(
                "Select an evidence item to view its available actions."
            )
            # 134: a package with nothing to select leaves nothing of the one before on screen.
            self.candidate_detail.clear()
            self.evidence_file_list.clear()
            return
        key = str(current.data(Qt.ItemDataRole.UserRole) or "")
        if key.startswith(CLIPS_ROW_PREFIX):
            self._show_narration_row(int(key[len(CLIPS_ROW_PREFIX):] or -1))
            return
        candidate = self._candidate_by_id(key)
        if not candidate:
            return
        self.current_item = candidate
        self._refresh_play_moment_button(
            self.play_candidate_button,
            selected=True,
            playable=bool(self._play_targets_for_candidate(candidate)),
        )
        self.rerender_candidate_button.setEnabled(True)
        self.rerender_candidate_button.setToolTip(
            "Prepare a new review that rebuilds this evidence item."
        )
        self.export_candidate_prompts_button.setEnabled(True)
        self.export_candidate_prompts_button.setToolTip(
            "Export local prompt drafts for this evidence item."
        )
        folder_ready = bool(candidate.evidence_folder and candidate.evidence_folder.is_dir())
        self.open_candidate_button.setEnabled(folder_ready)
        if folder_ready:
            self.open_candidate_button.setToolTip("Open this candidate's local evidence folder in Windows Explorer.")
            self.open_candidate_status.setText("Candidate folder is available locally.")
        else:
            self.open_candidate_button.setToolTip(
                "This item has no local candidate folder. Review-needed and lightweight records may be index-only."
            )
            self.open_candidate_status.setText(
                "Open is unavailable because this item has no local evidence folder. Its index and transcript excerpt remain visible here."
            )
        self.candidate_detail.setHtml(
            f"<h3>{escape(candidate.item_id)}: {escape(candidate.title)}</h3>"
            f"<p><b>Source:</b> {escape(candidate.source_filename or 'unknown')}<br>"
            f"<b>Timestamp:</b> {escape(candidate.marker_timestamp or candidate.timestamp_start or 'unknown')}<br>"
            f"<b>Status:</b> {escape(candidate.render_status)}<br>"
            f"<b>Likely project:</b> {escape(candidate.repo_hint)} ({escape(candidate.repo_confidence)})</p>"
            f"<p>{escape(candidate.transcript_excerpt or candidate.reason or 'No excerpt available.')}</p>"
            "<p><b>GitHub review is always required.</b></p>"
        )
        self.evidence_file_list.clear()
        for evidence_file in candidate.evidence_files:
            item = QListWidgetItem(f"{evidence_file.label}: {evidence_file.path.name}")
            item.setData(Qt.ItemDataRole.UserRole, str(evidence_file.path))
            if not evidence_file.path.exists():
                item.setText(item.text() + "  [missing]")
            self.evidence_file_list.addItem(item)
        # 134: and its recording's small review copy and the clips that overlap it. Shown only here:
        # the bug report's own files, drafts and handoff stay exactly as they were.
        self._add_candidate_narration_rows(candidate)
        self.refresh_prompt_previews()

    # Clips and small review copies (134) -----------------------------------------------------------

    def _show_narration_row(self, index: int) -> None:
        found = getattr(self, "_narration_files", [])
        files = found[index] if 0 <= index < len(found) else None
        self.current_item = None
        for button in (self.open_candidate_button, self.rerender_candidate_button,
                       self.export_candidate_prompts_button, self.play_candidate_button):
            button.setEnabled(False)
            button.setToolTip(CLIPS_ROW_TOOLTIP)
        self.evidence_file_list.clear()
        if files is None:
            self.candidate_detail.clear()
            return
        name = files.source_filename or files.source_id
        copy = ", and a small review copy of the whole recording" if files.review_copy is not None else ""
        self.candidate_detail.setHtml(
            f"<h3>Clips: {escape(name)}</h3><p>{len(files.clips)} clip(s) of the moments you were talking{copy}.</p>"
        )
        self.open_candidate_status.setText(f"The clips and small review copy of {name}. Double-click one to play it.")
        self._add_narration_rows(files, files.clips)
        self.refresh_prompt_previews()

    def _add_candidate_narration_rows(self, candidate: EvidenceCandidate) -> None:
        raw = candidate.raw
        ids = {str(raw.get(key) or "").strip() for key in ("source_id", "physical_source_id")} - {""}
        files = next((item for item in getattr(self, "_narration_files", []) if item.source_id in ids), None)
        if files is None:
            return
        start = _moment_seconds(raw.get("timestamp_start_seconds"), candidate.timestamp_start,
                                raw.get("marker_timestamp_seconds"), candidate.marker_timestamp)
        end = max(start, _moment_seconds(raw.get("timestamp_end_seconds"), candidate.timestamp_end))
        overlapping = [clip for clip in files.clips if start and clip.start_seconds <= end and clip.end_seconds >= start]
        self._add_narration_rows(files, overlapping)

    def _add_narration_rows(self, files: Any, clips: Any) -> None:
        # Numbered by the moment they show, the same way every time the recording's clips are listed.
        numbers = {seconds: number for number, seconds in enumerate(sorted({clip.seconds for clip in files.clips}), 1)}
        if files.review_copy is not None:
            self._add_narration_row(f"Small review copy: {files.review_copy.name}", files.review_copy, "review-copy",
                                    self._package_recording_path(files.source_id))
        for clip in clips:
            part = f" part {clip.part} of {clip.parts}" if clip.parts > 1 else ""
            self._add_narration_row(f"Clip {numbers.get(clip.seconds, 0)} ({format_hms(clip.seconds * 1000)}){part}: "
                                    f"{clip.path.name}", clip.path, "clip", "")

    def _add_narration_row(self, text: str, path: Path, kind: str, recording: str) -> None:
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, str(path))
        item.setData(NARRATION_KIND_ROLE, kind)
        item.setData(NARRATION_RECORDING_ROLE, recording)
        if not path.exists():
            item.setText(text + "  [missing]")
        self.evidence_file_list.addItem(item)

    def preview_evidence_file(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        self.evidence_image_preview.clear()
        if not current:
            self.evidence_image_preview.setText("Select an image to preview")
            return
        path = Path(str(current.data(Qt.ItemDataRole.UserRole) or ""))
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".webp"} or not path.exists():
            self.evidence_image_preview.setText("Double-click to open this evidence file")
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.evidence_image_preview.setText(
                "This image could not be previewed here. Double-click the file to open it."
            )
            return
        self.evidence_image_preview.setPixmap(
            pixmap.scaled(
                max(320, self.evidence_image_preview.width()),
                max(170, self.evidence_image_preview.height()),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def open_evidence_file_item(self, item: QListWidgetItem) -> None:
        path = Path(str(item.data(Qt.ItemDataRole.UserRole) or ""))
        kind = item.data(NARRATION_KIND_ROLE)
        if kind in ("review-copy", "clip"):
            if not path.exists():
                # 134: like any other missing evidence file, the folder it should be in.
                self._open_path_system(path)
                return
            recording = str(item.data(NARRATION_RECORDING_ROLE) or "")
            if kind == "review-copy" and recording:
                # The small review copy has the recording's own timeline, so the built-in player shows
                # that recording's transcript and moments beside it.
                package_root = self.current_package.root if self.current_package else None
                self.video_opener.open(PlayTarget(path=path, package_root=package_root, stands_in_for=Path(recording),
                                                  label=f"Small review copy of {Path(recording).name}"))
                return
        self._open_path(path)

    def open_current_candidate_folder(self) -> Outcome:
        if not self.current_item:
            self.open_candidate_status.setText("No evidence item is selected.")
            return Outcome.failed("No evidence item is selected.", "Select one in the list first.")
        folder = self.current_item.evidence_folder
        if not folder or not folder.is_dir():
            self.open_candidate_button.setEnabled(False)
            self.open_candidate_status.setText("Candidate folder is missing or was not rendered.")
            return Outcome.failed("This item's folder is missing or was not rendered.", "Press Rebuild evidence.")
        if self._open_path(folder):
            self.open_candidate_status.setText(f"Opened candidate folder: {folder}")
            return Outcome.done("Opened")
        self.open_candidate_status.setText("Windows could not open the candidate folder.")
        return Outcome.failed("Windows could not open the folder.", f"Open it yourself: {folder}")

    def prepare_candidate_rerender(self) -> None:
        if not self.current_item:
            return
        self._prepare_rerender(self.current_item.item_id, self.current_item.raw)

    def _prepare_rerender(self, candidate_id: str, raw: dict[str, Any]) -> None:
        self.run_settings["evidence_render_candidate_ids"] = candidate_id
        source_path = str(raw.get("source_path") or raw.get("source_identifier") or "")
        if source_path:
            self.run_settings["input_path"] = source_path
        self.current_workflow = WORKFLOW_CODEX_EVIDENCE
        self.refresh_wizard()
        self.wizard_steps.setCurrentRow(4)
        self.navigate("New Review")

    def export_current_prompts(self) -> Outcome:
        if not self.current_package or not self.current_item:
            return Outcome.quiet()
        paths = export_prompt_drafts(self.current_package, self.current_item)
        self._open_path(paths.codex_path.parent)
        return Outcome.done("Exported; the folder is open")

    # Session Review

    def _build_session_page(self) -> QWidget:
        page, layout = _page_header(
            "Session Review",
            "Relationship hints are suggestions. Codex, Claude, or the operator must decide whether mentions belong to the same ticket.",
        )
        self.session_status_label = QLabel("Open an evidence package to review its complete session.")
        self.session_status_label.setWordWrap(True)
        self.session_status_label.setProperty("accent", True)
        layout.addWidget(self.session_status_label)
        tabs = QTabWidget()
        self.session_timeline_table = QTableWidget(0, 7)
        self.session_timeline_table.setHorizontalHeaderLabels(
            ["Time", "Mention", "Type", "Source", "Evidence status", "Likely project", "Related"]
        )
        make_columns_resizable(
            self.session_timeline_table,
            widths={0: 90, 1: 320, 2: 120, 3: 220, 4: 150, 5: 170},
        )
        self.session_timeline_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.session_timeline_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.session_timeline_table.itemSelectionChanged.connect(self._session_timeline_selected)
        tabs.addTab(self.session_timeline_table, "Complete timeline")
        # 125: every row here is a moment, so right-click and double-click
        # play it. Moments are not a list of recordings: nothing is "next".
        self.video_opener.attach(self.session_timeline_table, self._mention_play_targets)
        thread_split = QSplitter()
        self.session_threads_list = QListWidget()
        self.session_threads_list.currentItemChanged.connect(self._session_thread_selected)
        self.video_opener.attach(self.session_threads_list, self._thread_play_targets)
        self.session_thread_detail = QTextBrowser()
        thread_split.addWidget(self.session_threads_list)
        thread_split.addWidget(self.session_thread_detail)
        thread_split.setStretchFactor(1, 1)
        tabs.addTab(thread_split, "Proposed ticket threads")
        self.session_unassigned_list = QListWidget()
        self.session_unassigned_list.currentItemChanged.connect(self._session_unassigned_selected)
        tabs.addTab(self.session_unassigned_list, "Unassigned mentions")
        self.video_opener.attach(self.session_unassigned_list, self._mention_play_targets)
        layout.addWidget(tabs, 1)
        self.session_mention_detail = QTextBrowser()
        self.session_mention_detail.setMaximumHeight(150)
        layout.addWidget(self.session_mention_detail)
        actions = QGridLayout()
        self.session_action_buttons: dict[str, QPushButton] = {}
        for index, (key, label, handler) in enumerate(
            (
                # 125: first, because watching the moment is the first thing
                # anyone wants to do with it.
                ("play", "Play this moment", self.play_current_session_moment),
                ("candidate", "Open evidence", self.open_session_candidate),
                ("narration", "Open narration", self.open_session_narration),
                ("transcript", "Open transcript", self.open_session_transcript),
                ("rerender", "Rebuild evidence", self.rerender_session_candidate),
                ("codex", "Export Codex prompt", lambda: self.export_session_prompt("codex")),
                ("claude", "Export Claude prompt", lambda: self.export_session_prompt("claude")),
            )
        ):
            button = QPushButton(label)
            if key == "rerender":
                # Opens New Review on its last step: the page change is what it does.
                button.clicked.connect(handler)
            button.setEnabled(False)
            button.setToolTip("Open an evidence package and select a mention first.")
            actions.addWidget(button, index // 2, index % 2)
            actions.setColumnStretch(index % 2, 1)
            self.session_action_buttons[key] = button
        # 237: Play this moment is the one primary button here, as in the approved mockup.
        self.session_action_buttons["play"].setProperty("primary", True)
        layout.addLayout(actions)
        self.session_actions_feedback = InlineFeedback()
        self.session_actions_feedback.setObjectName("sessionActionsFeedback")
        layout.addWidget(self.session_actions_feedback)
        for key, action, working, done in (
            ("play", self.play_current_session_moment, "Opening…", "Playing in the player"),
            ("candidate", self.open_session_candidate, "Opening…", "Opened"),
            ("narration", self.open_session_narration, "Opening…", "Opened"),
            ("transcript", self.open_session_transcript, "Opening…", "Opened"),
            ("codex", lambda: self.export_session_prompt("codex"), "Exporting…", "Exported"),
            ("claude", lambda: self.export_session_prompt("claude"), "Exporting…", "Exported"),
        ):
            bind_action(self.session_action_buttons[key], action, working=working, done=done,
                        feedback=self.session_actions_feedback)
        return page

    def refresh_session_review(self) -> None:
        if not hasattr(self, "session_timeline_table"):
            return
        self.session_timeline_table.setRowCount(0)
        self.session_threads_list.clear()
        self.session_unassigned_list.clear()
        package = self.current_package
        if not package:
            self.session_status_label.setText("Open an evidence package to review its complete session.")
            self._refresh_session_actions()
            return
        summary = package.session_timeline_payload.get("summary") or package.manifest.get("session_review_summary") or {}
        self.session_status_label.setText(
            f"Mentions: {summary.get('mention_count', len(package.session_mentions))} | "
            f"Rich: {summary.get('rendered_mention_count', len(package.candidates))} | "
            f"Lightweight: {summary.get('lightweight_mention_count', len(package.unrendered_candidates))} | "
            f"Proposed threads: {len(package.proposed_threads)} | "
            f"Unassigned: {len(package.unassigned_mention_ids)}"
        )
        for mention in package.session_mentions:
            row = self.session_timeline_table.rowCount()
            self.session_timeline_table.insertRow(row)
            values = (
                mention.timestamp,
                mention.mention_id,
                moment_kind_text(mention.record_type),
                mention.source_filename,
                mention.render_status,
                mention.repo_hint,
                ", ".join(mention.related_mention_ids),
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.ItemDataRole.UserRole, mention.mention_id)
                self.session_timeline_table.setItem(row, column, cell)
        for thread in package.proposed_threads:
            item = QListWidgetItem(
                f"{thread.thread_hint_id}: {', '.join(thread.mention_ids)}  [{thread.classification}]"
            )
            item.setData(Qt.ItemDataRole.UserRole, thread.thread_hint_id)
            self.session_threads_list.addItem(item)
        for mention_id in package.unassigned_mention_ids:
            mention = self._session_mention_by_id(mention_id)
            label = f"{mention.timestamp}  {mention_id}" if mention else mention_id
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, mention_id)
            self.session_unassigned_list.addItem(item)
        if self.session_timeline_table.rowCount():
            self.session_timeline_table.selectRow(0)
        self._refresh_session_actions()

    def _refresh_session_actions(self) -> None:
        if not hasattr(self, "session_action_buttons"):
            return
        package_ready = self.current_package is not None
        mention_ready = self.current_session_mention is not None
        for key, button in self.session_action_buttons.items():
            needs_mention = key in {"play", "candidate", "narration", "transcript", "rerender"}
            enabled = package_ready and (mention_ready or not needs_mention)
            button.setEnabled(enabled)
            if enabled:
                button.setToolTip("")
            elif not package_ready:
                button.setToolTip("Open an evidence package first.")
            else:
                button.setToolTip("Select a session mention first.")
        play_button = self.session_action_buttons.get("play")
        if play_button is not None and play_button.isEnabled():
            # A mention is selected. An older package may still not say which
            # recording it is in, and then there is nothing to play.
            self._refresh_play_moment_button(
                play_button,
                selected=True,
                playable=bool(self._play_targets_for_mention(self.current_session_mention)),
            )

    def _session_mention_by_id(self, mention_id: str) -> SessionMention | None:
        if not self.current_package:
            return None
        return next((mention for mention in self.current_package.session_mentions if mention.mention_id == mention_id), None)

    def _play_targets_for_mention(self, mention: SessionMention | None) -> list[PlayTarget]:
        if mention is None:
            return []
        # A timeline record names its recording by id, never by path. The
        # evidence item with the same id has the path; failing that, the
        # package's own source list does.
        candidate = self._candidate_by_id(mention.mention_id)
        recording_text = str(candidate.raw.get("source_path") or "").strip() if candidate else ""
        if not recording_text:
            recording_text = self._package_recording_path(mention.raw.get("source_id"))
        # A ticket mention carries the start of the stretch its evidence
        # covers; a bare marker only has the moment it was said.
        start_seconds = _moment_seconds(
            mention.raw.get("focused_start_seconds"),
            mention.timestamp_seconds,
            mention.timestamp,
        )
        label = f"{mention.mention_id} at {mention.timestamp}" if mention.timestamp else mention.mention_id
        return self._moment_play_targets(recording_text, start_seconds, label)

    def _mention_play_targets(self, index: QModelIndex) -> list[PlayTarget]:
        """Resolver for the timeline and the unassigned list: rows carry a mention id."""

        return self._play_targets_for_mention(
            self._session_mention_by_id(str(index.data(Qt.ItemDataRole.UserRole) or ""))
        )

    def _thread_play_targets(self, index: QModelIndex) -> list[PlayTarget]:
        """Resolver for proposed threads: one entry for each mention in the thread."""

        if self.current_package is None:
            return []
        thread_id = str(index.data(Qt.ItemDataRole.UserRole) or "")
        thread = next(
            (item for item in self.current_package.proposed_threads if item.thread_hint_id == thread_id),
            None,
        )
        targets: list[PlayTarget] = []
        for mention_id in thread.mention_ids if thread else []:
            targets.extend(self._play_targets_for_mention(self._session_mention_by_id(mention_id)))
        return targets

    def play_current_session_moment(self) -> Outcome:
        targets = self._play_targets_for_mention(self.current_session_mention)
        if not targets:
            return Outcome.quiet()
        self.video_opener.open(targets[0])
        return Outcome.done("Playing in the player")

    def _session_timeline_selected(self) -> None:
        items = self.session_timeline_table.selectedItems()
        if items:
            mention_id = str(items[0].data(Qt.ItemDataRole.UserRole) or "")
            self._set_current_session_mention(mention_id)

    def _session_unassigned_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current:
            self._set_current_session_mention(str(current.data(Qt.ItemDataRole.UserRole) or ""))

    def _set_current_session_mention(self, mention_id: str) -> None:
        mention = self._session_mention_by_id(mention_id)
        self.current_session_mention = mention
        self._refresh_session_actions()
        if not mention:
            self.session_mention_detail.clear()
            return
        relation_lines: list[str] = []
        if self.current_package:
            for relation in self.current_package.session_relationships:
                if mention_id in {relation.mention_a, relation.mention_b}:
                    other = relation.mention_b if relation.mention_a == mention_id else relation.mention_a
                    relation_lines.append(
                        f"{other}: {relation.classification} - {'; '.join(relation.reasons)}"
                    )
        relation_html = "<br>".join(escape(line) for line in relation_lines)
        self.session_mention_detail.setHtml(
            f"<h3>{escape(mention.mention_id)} at {escape(mention.timestamp or 'unknown')}</h3>"
            f"<p><b>Likely project:</b> {escape(mention.repo_hint)} | <b>Evidence status:</b> {escape(mention.render_status)} | "
            f"<b>Frames / audio:</b> {escape(str(mention.frame_available))} / {escape(str(mention.audio_available))}</p>"
            f"<p>{escape(mention.excerpt or 'No excerpt available.')}</p>"
            f"<p><b>Relationship reasons:</b><br>{relation_html or 'No non-unresolved hints.'}</p>"
        )

    def _session_thread_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if not current or not self.current_package:
            return
        thread_id = str(current.data(Qt.ItemDataRole.UserRole) or "")
        thread = next((item for item in self.current_package.proposed_threads if item.thread_hint_id == thread_id), None)
        if not thread:
            return
        thread_reasons_html = "<br>".join(escape(reason) for reason in thread.reasons)
        self.session_thread_detail.setHtml(
            f"<h3>{escape(thread.thread_hint_id)}</h3>"
            f"<p><b>Classification:</b> {escape(thread.classification)}</p>"
            f"<p><b>Mentions:</b> {escape(', '.join(thread.mention_ids))}</p>"
            f"<p><b>Reasons:</b><br>{thread_reasons_html}</p>"
            "<p><b>Operator review required:</b> this grouping is not a final ticket decision.</p>"
        )

    def open_session_candidate(self) -> Outcome:
        if not self.current_session_mention:
            return Outcome.quiet()
        candidate = self._candidate_by_id(self.current_session_mention.mention_id)
        return self._open_outcome(candidate.evidence_folder if candidate else None, "evidence folder")

    def open_session_narration(self) -> Outcome:
        return self._open_outcome(
            self.current_session_mention.narration_context_path if self.current_session_mention else None, "narration")

    def open_session_transcript(self) -> Outcome:
        if self.current_session_mention and self.current_session_mention.full_transcript_paths:
            return self._open_outcome(self.current_session_mention.full_transcript_paths[0], "transcript")
        return Outcome.failed("This mention has no transcript.", "Open evidence or narration instead.")

    def rerender_session_candidate(self) -> None:
        if not self.current_session_mention:
            return
        candidate = self._candidate_by_id(self.current_session_mention.mention_id)
        self._prepare_rerender(
            self.current_session_mention.mention_id,
            candidate.raw if candidate else self.current_session_mention.raw,
        )

    def export_session_prompt(self, tool: str) -> Outcome:
        if not self.current_package:
            return Outcome.quiet()
        paths = export_session_prompt_drafts(self.current_package)
        self._open_path(paths.codex_path if tool == "codex" else paths.claude_path)
        return Outcome.done("Exported; the draft is open")

    # Prompt Drafts

    def _build_prompts_page(self) -> QWidget:
        page, layout = _page_header(
            "Prompt Drafts",
            "Drafts reference local evidence. Copying text alone does not include the files, and no GitHub write occurs here.",
        )
        tabs = QTabWidget()
        self.codex_prompt_preview = QPlainTextEdit()
        self.codex_prompt_preview.setReadOnly(True)
        self.claude_prompt_preview = QPlainTextEdit()
        self.claude_prompt_preview.setReadOnly(True)
        self.session_prompt_preview = QPlainTextEdit()
        self.session_prompt_preview.setReadOnly(True)
        tabs.addTab(self.codex_prompt_preview, "Selected item - Codex")
        tabs.addTab(self.claude_prompt_preview, "Selected item - Claude")
        tabs.addTab(self.session_prompt_preview, "Complete session")
        self.prompt_tabs = tabs
        tabs.currentChanged.connect(lambda _index: self.refresh_prompt_previews())
        layout.addWidget(tabs, 1)
        actions = QGridLayout()
        self.copy_prompt_button = QPushButton("Copy draft")
        self.copy_prompt_button.setProperty("primary", True)
        self.copy_prompt_button.setEnabled(False)
        self.copy_prompt_button.setToolTip("Open an evidence package first.")
        self.export_item_prompts_button = QPushButton("Export item drafts")
        self.export_item_prompts_button.setEnabled(False)
        self.export_item_prompts_button.setToolTip(
            "Open a package and select an evidence item first."
        )
        self.export_session_prompts_button = QPushButton("Export session drafts")
        self.export_session_prompts_button.setEnabled(False)
        self.export_session_prompts_button.setToolTip(
            "Open an evidence package first."
        )
        actions.addWidget(self.copy_prompt_button, 0, 0)
        actions.addWidget(self.export_item_prompts_button, 0, 1)
        actions.addWidget(self.export_session_prompts_button, 1, 0, 1, 2)
        actions.setColumnStretch(0, 1)
        actions.setColumnStretch(1, 1)
        layout.addLayout(actions)
        # 237: "Copied" or "Exported" right under the buttons.
        self.drafts_feedback = InlineFeedback()
        self.drafts_feedback.setObjectName("draftsFeedback")
        layout.addWidget(self.drafts_feedback)
        for button, action, working, done in (
            (self.copy_prompt_button, self._copy_current_draft, "Copying…", "Copied"),
            (self.export_item_prompts_button, self.export_current_prompts, "Exporting…", "Exported"),
            (self.export_session_prompts_button, lambda: self.export_session_prompt("codex"), "Exporting…", "Exported"),
        ):
            bind_action(button, action, working=working, done=done, feedback=self.drafts_feedback)
        return page

    def _copy_current_draft(self) -> Outcome:
        QApplication.clipboard().setText(self.prompt_tabs.currentWidget().toPlainText())
        return Outcome.done(f"Copied: {self.prompt_tabs.tabText(self.prompt_tabs.currentIndex())}")

    def refresh_prompt_previews(self) -> None:
        if not hasattr(self, "codex_prompt_preview"):
            return
        if self.current_package and self.current_item:
            self.codex_prompt_preview.setPlainText(build_codex_prompt(self.current_package, self.current_item))
            self.claude_prompt_preview.setPlainText(build_claude_prompt(self.current_package, self.current_item))
        else:
            self.codex_prompt_preview.setPlainText("Select an evidence item first.")
            self.claude_prompt_preview.setPlainText("Select an evidence item first.")
        if self.current_package:
            self.session_prompt_preview.setPlainText(build_session_prompt(self.current_package, "Codex"))
        else:
            self.session_prompt_preview.setPlainText("Open an evidence package first.")
        item_ready = self.current_package is not None and self.current_item is not None
        package_ready = self.current_package is not None
        copy_ready = (
            package_ready if self.prompt_tabs.currentIndex() == 2 else item_ready
        )
        self.copy_prompt_button.setEnabled(copy_ready)
        self.copy_prompt_button.setToolTip(
            ""
            if copy_ready
            else (
                "Open an evidence package first."
                if not package_ready
                else "Select an evidence item first."
            )
        )
        self.export_item_prompts_button.setEnabled(item_ready)
        self.export_item_prompts_button.setToolTip(
            "" if item_ready else "Open a package and select an evidence item first."
        )
        self.export_session_prompts_button.setEnabled(package_ready)
        self.export_session_prompts_button.setToolTip(
            "" if package_ready else "Open an evidence package first."
        )

    # History

    def _build_history_page(self) -> QWidget:
        page, layout = _page_header("History", "Recent local runs and their logs or outputs.")
        self.history_status_label = QLabel(
            "No local review history yet. Complete a review to add it here."
        )
        self.history_status_label.setWordWrap(True)
        self.history_status_label.setProperty("muted", True)
        layout.addWidget(self.history_status_label)
        self.history_list = QListWidget()
        self.history_list.itemSelectionChanged.connect(self._refresh_history_actions)
        layout.addWidget(self.history_list, 1)
        self._attach_run_list(self.history_list, "History")
        # 243: every run is kept; History shows the newest in pages, and Show more adds the next page.
        self.history_shown_limit = HISTORY_PAGE_SIZE
        more_row = QHBoxLayout()
        self.history_more_button = QPushButton("Show more")
        self.history_more_button.setVisible(False)
        self.history_more_button.clicked.connect(self.show_more_history)
        more_row.addWidget(self.history_more_button)
        more_row.addStretch(1)
        layout.addLayout(more_row)
        actions = QHBoxLayout()
        # Made before the other two: _refresh_history_actions takes their
        # existence as its sign that this row of buttons has been built.
        self.history_play_button = QPushButton("Play recording")
        self.history_play_button.setProperty("primary", True)
        self.history_open_output_button = QPushButton("Open output")
        self.history_open_log_button = QPushButton("Open log")
        actions.addWidget(self.history_play_button)
        actions.addWidget(self.history_open_output_button)
        actions.addWidget(self.history_open_log_button)
        # 237: what the click did, beside the buttons.
        self.history_feedback = InlineFeedback()
        self.history_feedback.setObjectName("historyFeedback")
        actions.addWidget(self.history_feedback, 1)
        layout.addLayout(actions)
        for button, action, working, done in (
            (self.history_play_button, self.play_selected_history_recording, "Opening…", "Playing in the player"),
            (self.history_open_output_button, self.open_selected_history_output, "Opening…", "Opened"),
            (self.history_open_log_button, self.open_selected_history_log, "Opening…", "Opened"),
        ):
            bind_action(button, action, working=working, done=done, feedback=self.history_feedback)
        return page

    def refresh_history(self) -> None:
        if not hasattr(self, "history_list"):
            return
        self.history_list.clear()
        # 243: from the library, every run; the newest page first, Show more for the rest.
        for run in self.recent_runs(limit=self.history_shown_limit):
            item = QListWidgetItem(
                f"{run.get('timestamp', '')}  |  {run.get('workflow_title', '')}  |  "
                f"{run.get('status', '')}  |  {Path(str(run.get('source') or '')).name}"
            )
            item.setData(Qt.ItemDataRole.UserRole, run)
            item.setForeground(status_color(str(run.get("status") or "")))
            self.history_list.addItem(item)
        total = max(self.recent_run_count(), self.history_list.count())
        self.history_more_button.setVisible(total > self.history_list.count())
        self.history_status_label.setText(
            f"{total} local review(s). Select one to open its output or processing log."
            if self.history_list.count()
            else "No local review history yet. Complete a review to add it here."
        )
        self._refresh_history_actions()

    def show_more_history(self) -> None:
        """243: the next page of History, the rows already shown staying where they are."""

        self.history_shown_limit += HISTORY_PAGE_SIZE
        selected = self.history_list.currentRow()
        self.refresh_history()
        if selected >= 0:
            self.history_list.setCurrentRow(selected)

    def _refresh_history_actions(self) -> None:
        if not hasattr(self, "history_open_output_button"):
            return
        selected = bool(self.history_list.selectedItems())
        # Only "is a row selected" decides these. Working out what a run can
        # play reads its package from disk, which has no place in a handler
        # that runs on every change of selection; Play says so when pressed.
        for button in (
            self.history_play_button,
            self.history_open_output_button,
            self.history_open_log_button,
        ):
            button.setEnabled(selected)
            button.setToolTip("" if selected else "Select a review from History first.")

    # Playing the recording behind a run (125) ------------------------------

    # Nothing here asks the disk whether a recording or a folder is there. A
    # play list is built from every row of History at the moment a video is
    # opened, on the GUI thread, and the recordings live on drives that sleep
    # or are not plugged in: one question per row would freeze the Workbench.
    # Whether the recording exists is the opener's question, and which folder
    # holds the package is the player's, asked on its own thread.

    @staticmethod
    def _run_output_folder(run: dict[str, Any]) -> Path | None:
        """Where this run wrote, exactly as the run recorded it."""

        output = str(run.get("output") or "").strip()
        return Path(output) if output else None

    @staticmethod
    def _package_recordings(output: Path | None) -> list[Path]:
        """The recordings the package in a run's output folder names, in its order."""

        if output is None:
            return []
        manifest = None
        # Read, never looked for first: the package is a folder inside the
        # output folder, and for some runs it is the output folder itself.
        for folder in (output / "codex-evidence-package", output):
            try:
                manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            break
        sources = manifest.get("sources") if isinstance(manifest, dict) else None
        recordings: list[Path] = []
        seen: set[str] = set()
        for entry in sources if isinstance(sources, list) else []:
            text = str(entry.get("source_path") or "").strip() if isinstance(entry, dict) else ""
            # A source can also be a web address, which is not a file to play.
            if text and is_video_path(text) and path_key(text) not in seen:
                seen.add(path_key(text))
                recordings.append(Path(text))
        return recordings

    def _play_targets_for_run(self, run: dict[str, Any]) -> list[PlayTarget]:
        output = self._run_output_folder(run)
        # "source" is the recording itself only for a one-recording run. It is
        # also "3 recordings", "Configured folders", a folder or a web address.
        source = str(run.get("source") or "").strip()
        if is_video_path(source):
            named = Path(source)
            if named.is_absolute():
                # Taken at its word. One that has since moved is the opener's
                # business: it offers "Find it…".
                recordings = [named]
            else:
                # Only a file name. The package knows where that recording
                # was; anything else in there belongs to another run that
                # shared the output folder.
                wanted = named.name.lower()
                recordings = [item for item in self._package_recordings(output) if item.name.lower() == wanted]
        else:
            # Several recordings, so the run's own package has to say which:
            # one small file, read from the folder the Workbench wrote it to.
            recordings = self._package_recordings(output)
        return [
            # The output folder is enough for the player to find the package.
            PlayTarget(path=recording, package_root=output, label=recording.name)
            for recording in recordings
        ]

    def _run_play_targets(self, index: QModelIndex) -> list[PlayTarget]:
        """Resolver for History and Home's recent runs: a row carries its run."""

        run = index.data(Qt.ItemDataRole.UserRole)
        return self._play_targets_for_run(run) if isinstance(run, dict) else []

    def _run_play_targets_without_disk(self, index: QModelIndex) -> list[PlayTarget]:
        """The same, for the rows that were NOT clicked: never reads anything.

        The list "never use" moves along is built from every row at the moment
        a video opens, on the GUI thread. A row that names its recording in
        full is taken at its word; a row that would need its package read
        ("3 recordings", a bare file name) is simply left out of that list.
        """

        run = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(run, dict):
            return []
        source = str(run.get("source") or "").strip()
        if not is_video_path(source) or not Path(source).is_absolute():
            return []
        recording = Path(source)
        return [PlayTarget(path=recording, package_root=self._run_output_folder(run), label=recording.name)]

    def play_selected_history_recording(self) -> Outcome:
        index = self.history_list.currentIndex()
        targets = self._run_play_targets(index) if index.isValid() else []
        if not targets:
            QMessageBox.information(
                self,
                "Nothing to play",
                "This review does not say which recording it was made from, so there is nothing to "
                "play. Its output and its log are still here.",
            )
            return Outcome.quiet()
        # The same list a right-click hands over: every recording in History,
        # so "never use" in the player can move on to the next one.
        recordings: list[PlayTarget] = []
        opened_at = 0
        for row in range(self.history_list.count()):
            if row == index.row():
                # History has one row for each run, so one recording can be on
                # several rows. "Next" has to carry on from the row that was
                # chosen, not from the first row that shows the same recording.
                opened_at = len(recordings)
            # Only the chosen row may read its package; see
            # _run_play_targets_without_disk.
            row_index = self.history_list.model().index(row, 0)
            recordings.extend(
                targets if row == index.row() else self._run_play_targets_without_disk(row_index)
            )
        sequence = (
            PlaySequence(tuple(recordings), label="History", opened_at=opened_at)
            if len(recordings) > 1
            else None
        )
        if len(targets) == 1:
            self.video_opener.open(targets[0], sequence=sequence)
            return Outcome.done("Playing in the player")
        # A run of several recordings: ask which, under the button.
        menu = self.video_opener.build_menu(targets, self, sequence=sequence)
        chosen = menu.exec(self.history_play_button.mapToGlobal(self.history_play_button.rect().bottomLeft()))
        menu.deleteLater()
        return Outcome.done("Playing in the player") if chosen is not None else Outcome.quiet()

    def _selected_history_run(self) -> dict[str, Any]:
        item = self.history_list.currentItem()
        return dict(item.data(Qt.ItemDataRole.UserRole) or {}) if item else {}

    def _attach_run_list(self, view: QListWidget, label: str) -> None:
        """History and Home's recent runs: a row is a run (125).

        Double-click plays the run's recording, and asks which one when the run
        has several, as the Play recording button does. A run with nothing to
        play (a web address, configured folders) opens its output folder, which
        is what double-click did everywhere before. The right-click menu keeps
        the output folder and the log one click away.
        """

        self.video_opener.attach(
            view,
            self._run_play_targets,
            sequence=True,
            label=label,
            sequence_resolver=self._run_play_targets_without_disk,
            on_nothing_to_play=self._open_run_output_at,
            ask_among_several=True,
            extra_actions=self._add_run_folder_actions,
        )

    def _add_run_folder_actions(self, menu: QMenu, index: QModelIndex) -> None:
        run = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(run, dict):
            return
        output = str(run.get("output") or "").strip()
        log = str(run.get("log") or "").strip()
        if output:
            menu.addAction("Open output folder").triggered.connect(
                lambda _checked=False, path=Path(output): self._open_path(path)
            )
        if log:
            menu.addAction("Open log").triggered.connect(lambda _checked=False, path=Path(log): self._open_path(path))

    def _open_run_output_at(self, index: QModelIndex) -> None:
        run = index.data(Qt.ItemDataRole.UserRole)
        if isinstance(run, dict):
            self._open_run_output(run)

    def _open_run_output(self, run: dict[str, Any]) -> None:
        output = str(run.get("output") or "").strip()
        # An empty value would be Path("."), the app's own working folder.
        if output:
            self._open_path(Path(output))

    def open_history_item(self, item: QListWidgetItem) -> None:
        self._open_run_output(dict(item.data(Qt.ItemDataRole.UserRole) or {}))

    def open_selected_history_output(self) -> Outcome:
        value = str(self._selected_history_run().get("output") or "").strip()
        return self._open_outcome(Path(value) if value else None, "output folder")

    def open_selected_history_log(self) -> Outcome:
        value = str(self._selected_history_run().get("log") or "").strip()
        return self._open_outcome(Path(value) if value else None, "log")

    # Settings

    def _build_settings_page(self) -> QWidget:
        page, layout = _page_header(
            "Settings",
            "Startup defaults affect future launches. They do not replace the current review unless you reset it.",
        )
        tabs = QTabWidget()
        self.settings_tabs = tabs
        tabs.addTab(self._build_general_settings_tab(), "General / Startup")
        tabs.addTab(self._build_profiles_settings_tab(), "Profiles")
        tabs.addTab(self._build_dependency_settings_tab(), "Dependencies")
        tabs.addTab(self._build_identity_settings_tab(), "Build information")
        tabs.addTab(self._build_backend_settings_tab(), "Advanced / Diagnostics")
        # 125: put in by position, after Dependencies. Dependencies must stay
        # at index 2: open_dependency_setup, a GUI test and the help-screenshot
        # tool all go to it by number.
        self.video_player_settings = VideoPlayerSettingsPanel()
        tabs.insertTab(3, self.video_player_settings, "Video player")
        self.video_player_settings.load(self.app_settings)
        # 150: the AI Video Editor's own tab, added at the end so no tab moves.
        self.ai_video_editor_settings = AiVideoEditorSettingsPanel()
        tabs.addTab(self.ai_video_editor_settings, "AI Video Editor")
        self.ai_video_editor_settings.load(self.app_settings)
        # 237: the tab names wrap onto a second row at a large text size instead of hiding behind arrows.
        self.settings_tab_strip = WrappingTabStrip(tabs)
        layout.addWidget(self.settings_tab_strip)
        layout.addWidget(tabs, 1)
        actions = QHBoxLayout()
        export_bundle = QPushButton("Export settings")
        export_bundle.clicked.connect(self.export_settings_bundle_dialog)
        import_bundle = QPushButton("Import settings")
        import_bundle.clicked.connect(self.import_settings_bundle_dialog)
        save = QPushButton("Save settings")
        save.setProperty("primary", True)
        self.settings_save_button = save
        actions.addWidget(export_bundle)
        actions.addWidget(import_bundle)
        actions.addStretch(1)
        # 237: "Saved a moment ago" beside the button, not a pop-up to close.
        self.settings_save_feedback = InlineFeedback()
        self.settings_save_feedback.setObjectName("settingsSaveFeedback")
        actions.addWidget(self.settings_save_feedback)
        actions.addWidget(save)
        layout.addLayout(actions)
        bind_action(save, self.save_settings_from_page, working="Saving…", done="Saved a moment ago",
                    feedback=self.settings_save_feedback)
        return page

    def _build_general_settings_tab(self) -> QWidget:
        panel = QWidget()
        form = QFormLayout(panel)
        self.settings_startup_page_combo = WheelSafeComboBox()
        for name in PAGE_NAMES:
            self.settings_startup_page_combo.addItem(name, name)
        self.settings_default_workflow_combo = WheelSafeComboBox()
        for workflow in WORKFLOWS:
            self.settings_default_workflow_combo.addItem(workflow.display_name, workflow.number)
        self.settings_default_profile_combo = WheelSafeComboBox()
        self.settings_default_input_edit = QLineEdit()
        self.settings_default_output_edit = QLineEdit()
        self.settings_open_output = QCheckBox()
        self.settings_restore_geometry = QCheckBox()
        self.settings_debug_mode = QCheckBox()
        self.settings_debug_mode.toggled.connect(self._refresh_build_identity_disclosure)
        self.settings_theme_combo = WheelSafeComboBox()
        for value in ("Dark", "Light", "System"):
            self.settings_theme_combo.addItem(value, value)
        form.addRow("Startup page", self.settings_startup_page_combo)
        form.addRow("Default workflow", self.settings_default_workflow_combo)
        form.addRow("Default profile", self.settings_default_profile_combo)
        form.addRow("Default input folder", self.settings_default_input_edit)
        form.addRow("Default output folder", self.settings_default_output_edit)
        # 220: one cache folder for everything that can be rebuilt; clearing it loses no tag or decision.
        self.settings_cache_folder_edit = QLineEdit()
        self.settings_cache_folder_edit.setObjectName("settingsCacheFolder")
        self.settings_cache_folder_edit.setPlaceholderText(str(app_cache.default_cache_root()))
        self.settings_cache_folder_edit.setToolTip(METADATA_BY_KEY["cache_folder"].tooltip)
        form.addRow("Cache folder", self.settings_cache_folder_edit)
        cache_row = QHBoxLayout()
        self.settings_cache_size = WheelSafeSpinBox()
        self.settings_cache_size.setRange(1, 1000)
        self.settings_cache_size.setSuffix(" GB")
        self.settings_cache_size.setToolTip(METADATA_BY_KEY["cache_size_gb"].tooltip)
        cache_row.addWidget(self.settings_cache_size)
        cache_row.addStretch(1)
        form.addRow("Cache size cap", cache_row)
        # A row of the form's full width, with the usage wrapped beside it: the folder's path can be long.
        cache_tools = QWidget()
        tools_row = QHBoxLayout(cache_tools)
        tools_row.setContentsMargins(0, 0, 0, 0)
        self.settings_clear_cache_button = QPushButton("Clear cache")
        self.settings_clear_cache_button.setObjectName("settingsClearCache")
        bind_action(self.settings_clear_cache_button, lambda: (self.clear_cache(), Outcome.quiet())[1],
                    working="Clearing…", done="Done")
        tools_row.addWidget(self.settings_clear_cache_button)
        self.settings_cache_usage = QLabel("")
        self.settings_cache_usage.setProperty("muted", True)
        self.settings_cache_usage.setWordWrap(True)
        tools_row.addWidget(self.settings_cache_usage, 1)
        form.addRow(cache_tools)
        form.addRow("Open output after completion", self.settings_open_output)
        form.addRow("Restore last window size/position", self.settings_restore_geometry)
        self.settings_debug_mode.setToolTip(
            "Show technical build identity and include detailed troubleshooting information in the processing log."
        )
        form.addRow("Debug details", self.settings_debug_mode)
        form.addRow("Theme", self.settings_theme_combo)
        # 237: the text size, applied at once and kept for the next start; Ctrl+Plus, Ctrl+Minus and
        # Ctrl+0 change it on every page.
        self.settings_text_size = SegmentedControl([(size, f"{size}%") for size in TEXT_SIZES], name="Text size")
        self.settings_text_size.setObjectName("settingsTextSize")
        self.settings_text_size.setToolTip("Makes every word in the app larger or smaller. "
                                           "Ctrl+Plus and Ctrl+Minus change it on any page; Ctrl+0 goes back to 100%.")
        self.settings_text_size.changed.connect(self.set_text_size)
        self.settings_text_size_feedback = InlineFeedback()
        self.settings_text_size_feedback.setObjectName("settingsTextSizeFeedback")
        text_size_row = QHBoxLayout()
        text_size_row.addWidget(self.settings_text_size)
        text_size_row.addWidget(self.settings_text_size_feedback, 1)
        form.addRow("Text size", text_size_row)
        # 196: which track carries the narration, for recordings whose tracks have no names.
        self.settings_track_roles = TrackRolesPanel()
        # 237: the long label on a line of its own above its tracks, so at a large text size it can
        # never run into the Track 1 drop-down.
        track_roles_label = QLabel("Narration track, for recordings without track names")
        track_roles_label.setObjectName("settingsTrackRolesLabel")
        track_roles_label.setWordWrap(True)
        track_roles_label.setBuddy(self.settings_track_roles)
        form.addRow(track_roles_label)
        form.addRow(self.settings_track_roles)
        track_roles_note = QLabel(
            "Recordings with named tracks (named in OBS, for example \"T2 - Narration\") are read by "
            "their names. Leave every track on Auto to find your voice automatically."
        )
        track_roles_note.setWordWrap(True)
        form.addRow(track_roles_note)
        # 201: one list of words for Whisper and the transcript corrections.
        self.settings_spelling_words = SpellingWordsPanel()
        form.addRow("Words to spell right", self.settings_spelling_words)
        self._load_settings_controls()
        return panel

    def _build_profiles_settings_tab(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        self.profiles_list = QListWidget()
        layout.addWidget(self.profiles_list, 1)
        actions = QGridLayout()
        make_default = QPushButton("Use as default profile")
        make_workflow_default = QPushButton("Use workflow at startup")
        save_as = QPushButton("Save review as profile")
        save_as.clicked.connect(self.save_profile_as)
        delete = QPushButton("Delete custom profile")
        set_button_kind(delete, "danger")
        actions.addWidget(make_default, 0, 0)
        actions.addWidget(make_workflow_default, 0, 1)
        actions.addWidget(save_as, 1, 0)
        actions.addWidget(delete, 1, 1)
        actions.setColumnStretch(0, 1)
        actions.setColumnStretch(1, 1)
        layout.addLayout(actions)
        # 237: what the last button did, under them.
        profiles_feedback = InlineFeedback()
        profiles_feedback.setObjectName("profilesFeedback")
        layout.addWidget(profiles_feedback)
        for button, action, working, done in (
            (make_default, self.make_selected_profile_default, "Saving…", "Saved as the default profile"),
            (make_workflow_default, self.make_selected_profile_workflow_default, "Saving…",
             "Saved: this workflow opens at startup"),
            (delete, self.delete_selected_profile, "Deleting…", "Deleted"),
        ):
            bind_action(button, action, working=working, done=done, feedback=profiles_feedback)
        return panel

    def _build_dependency_settings_tab(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        explanation = QLabel(
            "Check the exact local runtime the Workbench will use. This preflight does not open media, install packages, change PATH, or download models."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.dependency_summary = QLabel("Readiness has not been checked yet.")
        self.dependency_summary.setProperty("accent", True)
        self.dependency_summary.setWordWrap(True)
        layout.addWidget(self.dependency_summary)
        self.dependency_table = QTableWidget(0, 5)
        self.dependency_table.setHorizontalHeaderLabels(
            ["Component", "Why it is needed", "State", "Version", "Action"]
        )
        make_columns_resizable(
            self.dependency_table,
            widths={0: 150, 1: 360, 2: 140, 3: 170},
        )
        self.dependency_table.setWordWrap(False)
        self.dependency_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.dependency_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.dependency_table.setAccessibleName("Dependency readiness and actions")
        self.dependency_table.itemSelectionChanged.connect(self._dependency_row_selected)
        self._dependency_actions_fit_pending = False
        self.dependency_table.horizontalHeader().sectionResized.connect(
            lambda column, _old, _new: column == 4 and self._fit_dependency_actions()
        )
        layout.addWidget(self.dependency_table, 1)
        self.dependency_get_panel = QWidget()
        get_layout = QHBoxLayout(self.dependency_get_panel)
        get_layout.setContentsMargins(0, 0, 0, 0)
        self.dependency_get_label = QLabel()
        self.dependency_get_label.setWordWrap(True)
        self.dependency_get_label.setTextFormat(Qt.TextFormat.RichText)
        self.dependency_get_label.setOpenExternalLinks(True)
        self.dependency_get_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        self.dependency_copy_winget_button = QPushButton("Copy winget command")
        self.dependency_copy_winget_button.setAccessibleName("Copy the winget install command")
        bind_action(self.dependency_copy_winget_button, self.copy_winget_command, working="Copying…",
                    done="Copied")
        get_layout.addWidget(self.dependency_get_label, 1)
        get_layout.addWidget(self.dependency_copy_winget_button)
        self.dependency_get_panel.setVisible(False)
        layout.addWidget(self.dependency_get_panel)
        self.dependency_details_group = QGroupBox("Technical details")
        details_layout = QVBoxLayout(self.dependency_details_group)
        self.dependency_details = QTextBrowser()
        self.dependency_details.setMaximumHeight(150)
        details_layout.addWidget(self.dependency_details)
        self.dependency_details_group.setCheckable(True)
        self.dependency_details_group.setChecked(False)
        self.dependency_details_group.toggled.connect(
            self.dependency_details.setVisible
        )
        self.dependency_details.setVisible(False)
        layout.addWidget(self.dependency_details_group)
        actions = QHBoxLayout()
        dependency_help = QPushButton("Setup help")
        dependency_help.clicked.connect(
            lambda checked=False: self.open_troubleshooting_help()
        )
        self.dependency_check_button = QPushButton("Check readiness")
        self.dependency_check_button.setProperty("primary", True)
        self.dependency_check_button.clicked.connect(self.start_dependency_check)
        set_button_kind(dependency_help, "link")
        actions.addWidget(dependency_help)
        actions.addStretch(1)
        actions.addWidget(self.dependency_check_button)
        # 237: the readiness check takes a few seconds; its banner says it is working and how it ended.
        self.dependency_check_banner = JobBanner()
        self.dependency_check_banner.setObjectName("dependencyCheckBanner")
        self.dependency_check_banner.set_link_visible(False)
        layout.addWidget(self.dependency_check_banner)
        layout.addLayout(actions)
        return panel

    def _build_identity_settings_tab(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        explanation = QLabel(
            "Complete technical identity for troubleshooting. This remains available when Debug is off."
        )
        explanation.setWordWrap(True)
        explanation.setProperty("muted", True)
        layout.addWidget(explanation)
        form_panel = QWidget()
        form = QFormLayout(form_panel)
        self.build_identity_labels: dict[str, QLabel] = {}
        for label_text, value in self.build_identity.details():
            value_label = QLabel(value)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value_label.setWordWrap(True)
            form.addRow(label_text, value_label)
            self.build_identity_labels[label_text] = value_label
        layout.addWidget(form_panel)
        copy = QPushButton("Copy build information")
        copy_row = QHBoxLayout()
        copy_row.addStretch(1)
        copy_row.addWidget(copy)
        layout.addLayout(copy_row)
        # 237: "Copied" beside the button.
        bind_action(copy, self.copy_build_information, working="Copying…", done="Copied")
        layout.addStretch(1)
        return panel

    def copy_build_information(self) -> None:
        QApplication.clipboard().setText(self.build_identity.diagnostic_text)

    def _visible_build_identity_text(self) -> str:
        return (
            self.build_identity.technical_identity
            if bool(self.app_settings.get("debug_mode", True))
            else self.build_identity.friendly_version
        )

    def _refresh_build_identity_disclosure(self, checked: bool | None = None) -> None:
        debug_enabled = (
            bool(checked)
            if checked is not None
            else bool(self.app_settings.get("debug_mode", True))
        )
        text = (
            self.build_identity.technical_identity
            if debug_enabled
            else self.build_identity.friendly_version
        )
        if hasattr(self, "version_build_label"):
            self.version_build_label.setText(text)
        if hasattr(self, "home_build_identity"):
            self.home_build_identity.setText(text)

    def _build_backend_settings_tab(self) -> QWidget:
        panel = QWidget()
        form = QFormLayout(panel)
        self.settings_repo_root = QLineEdit(str(self.resources.app_root))
        self.settings_repo_root.setReadOnly(True)
        self.settings_script_path = QLineEdit(str(self.resources.script_path or "Not found"))
        self.settings_script_path.setReadOnly(True)
        self.settings_log_folder = QLineEdit(str(self.app_settings.get("log_folder") or default_log_folder()))
        self.settings_temp_folder = QLineEdit(str(self.app_settings.get("temp_folder") or default_temp_folder()))
        self.settings_retention = WheelSafeSpinBox()
        self.settings_retention.setRange(0, 3650)
        self.settings_retention.setValue(int(self.app_settings.get("cleanup_retention_days") or 14))
        cleanup = QPushButton("Clean logs and temporary files")
        # 237: the result is said in its dialog, as before; while it works the button says so.
        bind_action(cleanup, lambda: (self.clean_workbench_files(), Outcome.quiet())[1], working="Cleaning…",
                    done="Done")
        form.addRow("Application root", self.settings_repo_root)
        form.addRow("Processing script", self.settings_script_path)
        form.addRow("Log folder", self.settings_log_folder)
        form.addRow("Temporary files folder", self.settings_temp_folder)
        form.addRow("Cleanup retention days", self.settings_retention)
        form.addRow("", cleanup)
        return panel

    def _load_settings_controls(self) -> None:
        if not hasattr(self, "settings_startup_page_combo"):
            return
        for control, value in (
            (self.settings_startup_page_combo, self.app_settings.get("startup_page", "Home")),
            (self.settings_default_workflow_combo, normalize_workflow(self.app_settings.get("default_workflow"))),
            (self.settings_theme_combo, self.app_settings.get("theme", "Dark")),
        ):
            _set_control_value(control, value)
        self.settings_text_size.set_value(self.text_size())
        self.settings_default_input_edit.setText(str(self.app_settings.get("default_input_folder") or ""))
        self.settings_default_output_edit.setText(str(self.app_settings.get("output_folder") or ""))
        self.settings_cache_folder_edit.setText(str(self.app_settings.get("cache_folder") or ""))
        self.settings_cache_size.setValue(int(self.app_settings.get("cache_size_gb") or 10))
        self._refresh_cache_usage()
        self.settings_open_output.setChecked(bool(self.app_settings.get("open_output_in_explorer")))
        self.settings_restore_geometry.setChecked(bool(self.app_settings.get("restore_window_geometry", True)))
        self.settings_debug_mode.setChecked(bool(self.app_settings.get("debug_mode", True)))
        self.settings_track_roles.load(self.app_settings)
        self.settings_spelling_words.load(self.app_settings)
        if hasattr(self, "video_player_settings"):
            # This method first runs from inside the General tab's builder,
            # before the later Settings tabs exist.
            self.video_player_settings.load(self.app_settings)
        if hasattr(self, "ai_video_editor_settings"):
            self.ai_video_editor_settings.load(self.app_settings)
        self.refresh_profile_selector()

    def _cache_root(self) -> Path:
        return app_cache.cache_root(str(self.app_settings.get("cache_folder") or ""))

    def _refresh_cache_usage(self) -> None:
        if not hasattr(self, "settings_cache_usage"):
            return
        used = app_cache.size_bytes(self._cache_root())
        self.settings_cache_usage.setText(f"Using {used / 1024 ** 3:.2f} GB in {self._cache_root()}")

    def clear_cache(self) -> None:
        """220: empty the cache folder, after saying how much it frees. Tags and decisions stay."""

        root = self._cache_root()
        used = app_cache.size_bytes(root)
        answer = QMessageBox.question(
            self,
            "Clear cache",
            f"Clear the cache and free {used / 1024 ** 3:.2f} GB?\n\nWaveforms and sound levels are "
            "removed and rebuilt when needed. Your tags, decisions and guesses are not in the cache and stay.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        freed = app_cache.clear(root)
        self._refresh_cache_usage()
        QMessageBox.information(self, "Cache cleared", f"Freed {freed / 1024 ** 3:.2f} GB.")

    def save_settings_from_page(self) -> Outcome:
        # 220: the one output-folder rule refuses the recordings drive for the output folder, and the
        # cache folder is never on it either (a cache in a temp folder is fine: it can be rebuilt).
        output = self.settings_default_output_edit.text().strip()
        cache = self.settings_cache_folder_edit.text().strip()
        problem = (temporary_folder_problem(output) if output else "") or (
            recordings_drive_problem(cache, "cache folder") if cache else "")
        if problem:
            # 237: said beside Save settings, until dismissed.
            return Outcome.failed(f"Not saved. {problem}", "Choose another folder, then press Save settings.")
        self.app_settings.update(
            {
                "cache_folder": self.settings_cache_folder_edit.text().strip(),
                "cache_size_gb": self.settings_cache_size.value(),
                "startup_page": self.settings_startup_page_combo.currentData(),
                "default_workflow": self.settings_default_workflow_combo.currentData(),
                "default_profile": self.settings_default_profile_combo.currentData(),
                "default_input_folder": self.settings_default_input_edit.text().strip(),
                "output_folder": self.settings_default_output_edit.text().strip(),
                "open_output_in_explorer": self.settings_open_output.isChecked(),
                "restore_window_geometry": self.settings_restore_geometry.isChecked(),
                "debug_mode": self.settings_debug_mode.isChecked(),
                "theme": self.settings_theme_combo.currentData(),
                "log_folder": self.settings_log_folder.text().strip(),
                "temp_folder": self.settings_temp_folder.text().strip(),
                "cleanup_retention_days": self.settings_retention.value(),
                # 196: Auto / Narration / Never narration per track.
                **self.settings_track_roles.values(),
                # 201: the words to spell right.
                **self.settings_spelling_words.values(),
                # 125: which player, autoplay, and where VLC is on this PC.
                **self.video_player_settings.values(),
                # 150: where edited videos go and the AI budget for a new one.
                **self.ai_video_editor_settings.values(),
            }
        )
        # 201: a review already open uses the saved words too, not the ones it started with.
        self.run_settings.update(self.settings_spelling_words.values())
        self.save_app_settings()
        self._refresh_build_identity_disclosure()
        apply_theme(QApplication.instance(), str(self.app_settings.get("theme") or "Dark"))
        # 237: said beside the button ("Saved a moment ago"), not in a pop-up. Not "Startup choices":
        # the Video player tab is saved here too, and it takes effect at once, not at the next launch.
        self.settings_save_button.setToolTip(
            "Settings saved. Tool readiness is checked automatically on every launch.")
        return Outcome.done("Saved a moment ago")

    def export_settings_bundle_dialog(self) -> None:
        include_response = QMessageBox.question(
            self,
            "Portable settings export",
            "The recommended export leaves out folders and tool paths so it can move safely to another computer.\n\n"
            "Include folders and tool paths from this PC — may not work on another computer?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        include_machine_paths = include_response == QMessageBox.StandardButton.Yes
        suggested = str(default_settings_path().parent / "VideoManglerWorkbench-settings.json")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Workbench settings",
            suggested,
            "JSON files (*.json)",
        )
        if not path:
            return
        try:
            exported = export_settings_bundle(
                Path(path),
                self.app_settings,
                self.profile_manager,
                repo_root=self.repo_root_path,
                include_machine_paths=include_machine_paths,
            )
        except (OSError, ValueError) as exc:
            warn(self, "Settings export failed", str(exc))
            return
        mode = "This-PC paths included" if include_machine_paths else "Portable (folders and tool paths omitted)"
        QMessageBox.information(
            self,
            "Settings exported",
            f"Settings bundle saved to:\n{exported}\n\nExport mode: {mode}",
        )

    def import_settings_bundle_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Workbench settings",
            str(default_settings_path().parent),
            "JSON files (*.json)",
        )
        if not path:
            return
        try:
            result = import_settings_bundle(
                Path(path),
                self.app_settings,
                self.profile_manager,
                repo_root=self.repo_root_path,
            )
        except (OSError, ValueError) as exc:
            warn(self, "Settings import failed", str(exc))
            return
        self.app_settings = result.settings
        self.save_app_settings()
        self._load_settings_controls()
        self._refresh_build_identity_disclosure()
        self.refresh_profile_selector()
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Information)
        message.setWindowTitle("Settings imported")
        message.setText(result.summary_text())
        message.setDetailedText(result.details_text())
        message.exec()

    def _selected_profile_name(self) -> str:
        item = self.profiles_list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""

    def make_selected_profile_default(self) -> Outcome:
        name = self._selected_profile_name()
        if not name:
            return Outcome.failed("No profile is selected.", "Select one in the list first.")
        self.app_settings["default_profile"] = name
        _set_control_value(self.settings_default_profile_combo, name)
        self.save_app_settings()
        return Outcome.done(f"Saved: {name} is the default profile")

    def make_selected_profile_workflow_default(self) -> Outcome:
        name = self._selected_profile_name()
        if not name:
            return Outcome.failed("No profile is selected.", "Select one in the list first.")
        workflow = self.profile_manager.load_with_metadata(name).workflow
        self.app_settings["default_workflow"] = workflow
        _set_control_value(self.settings_default_workflow_combo, workflow)
        self.save_app_settings()
        return Outcome.done("Saved: this workflow opens at startup")

    def delete_selected_profile(self) -> Outcome:
        name = self._selected_profile_name()
        if not name:
            return Outcome.failed("No profile is selected.", "Select one in the list first.")
        if self.profile_manager.is_builtin(name):
            warn(self, "Protected profile", "Built-in profiles cannot be deleted or overwritten.")
            return Outcome.quiet()
        response = QMessageBox.question(
            self,
            "Delete custom profile?",
            f"Delete the custom profile {name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if response == QMessageBox.StandardButton.Yes:
            self.profile_manager.delete(name)
            self.refresh_profile_selector()
            return Outcome.done(f"Deleted {name}")
        return Outcome.quiet()

    def refresh_dependency_status(self) -> None:
        if (
            not self._resources_injected
            and self.dependency_check_thread is None
            and not self.resources.preflight_complete
        ):
            self.resources = discover_runtime_resources(self.app_settings)
        if not hasattr(self, "dependency_table"):
            return
        dependencies = self.resources.dependencies
        self.dependency_table.setRowCount(len(dependencies))
        for row, dependency in enumerate(dependencies):
            values = (
                dependency.name,
                dependency.purpose or dependency.detail,
                dependency.display_status,
                dependency.version or "—",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, dependency.key or dependency.name)
                item.setToolTip(value)
                self.dependency_table.setItem(row, column, item)
            action = None
            if dependency.action_label:
                action = QPushButton(dependency.action_label)
                action.setAccessibleName(
                    f"{dependency.action_label} for {dependency.name}"
                )
                action.clicked.connect(
                    lambda checked=False, key=dependency.key: self._dependency_action(key)
                )
            # 188: a tool that is missing or outdated also offers its official page.
            download = None
            if needs_download(dependency):
                download = QPushButton("Download")
                download.setAccessibleName(f"Download {dependency.name}")
                download.setToolTip(f"Open the official {dependency.name} page in your browser")
                download.clicked.connect(
                    lambda checked=False, key=dependency.key: self.open_tool_download_page(key)
                )
            if action is not None and download is not None:
                cell = QWidget()
                cell_layout = QHBoxLayout(cell)
                cell_layout.setContentsMargins(0, 0, 0, 0)
                cell_layout.setSpacing(4)
                cell_layout.addWidget(action)
                cell_layout.addWidget(download)
                self.dependency_table.setCellWidget(row, 4, cell)
            elif action is not None or download is not None:
                self.dependency_table.setCellWidget(row, 4, action or download)
            else:
                # A row that had buttons before keeps them unless they are taken away.
                self.dependency_table.removeCellWidget(row, 4)
                self.dependency_table.setItem(row, 4, QTableWidgetItem("—"))
        if self.dependency_check_thread is not None:
            self.dependency_summary.setText(
                "Checking the local runtime… No media is being opened or processed."
            )
        elif not self.resources.preflight_complete:
            self.dependency_summary.setText(
                "Readiness is checked automatically at launch. You can refresh it here after changing a tool."
            )
        else:
            required_needing_setup = [
                item
                for item in dependencies
                if item.required and not item.ready
            ]
            optional_needing_setup = [
                item
                for item in dependencies
                if not item.required and item.status in {"needs_setup", "unavailable", "update_recommended"}
            ]
            if required_needing_setup:
                self.dependency_summary.setText(
                    f"Needs setup: {len(required_needing_setup)} required component(s). Use the action in each row."
                )
            elif optional_needing_setup:
                self.dependency_summary.setText(
                    "Required tools are ready. One or more transcription or acceleration choices still need attention."
                )
            else:
                self.dependency_summary.setText(
                    "Ready: required tools and the selected transcription runtime passed preflight."
                )
        self._dependency_actions_fit_pending = True
        self._fit_dependency_actions()
        self.dependency_table.resizeRowsToContents()
        if self.dependency_table.rowCount() and self.dependency_table.currentRow() < 0:
            self.dependency_table.setCurrentCell(0, 0)
        # 188: the details and "Get <tool>" panel follow the rewritten rows, not only a new selection.
        self._dependency_row_selected()

    def start_dependency_check(self) -> None:
        if self.dependency_check_thread is not None:
            return
        if not self._resources_injected:
            self.resources = discover_runtime_resources(self.app_settings)
        self.resources.dependencies = [
            replace(item, status="checking", action_label="", action_kind="")
            for item in self.resources.dependencies
        ]
        self.resources.preflight_complete = False
        self.dependency_check_button.setEnabled(False)
        self.dependency_check_button.setText("Checking…")
        self.dependency_check_banner.show_job(JobInfo(
            token="readiness-check", title="Checking the tools the Workbench uses", state="active",
            detail="Python, FFmpeg, Whisper and the rest; nothing is installed or changed"))
        selected_model = str(self.run_settings.get("whisper_model") or "base.en")
        thread = DependencyCheckThread(
            self.resources,
            selected_model,
            str(self.app_settings.get("dependency_python_path") or ""),
            str(self.app_settings.get("dependency_ffmpeg_path") or ""),
            str(self.app_settings.get("dependency_ffprobe_path") or ""),
            str(self.app_settings.get("dependency_ytdlp_path") or ""),
            str(self.app_settings.get("video_player_vlc_path") or ""),
            translation_needs_argos=translation_needs_argos(self.run_settings),
            # Installer plan, Stage 3: the AI Video Editor's quick-pass model gets its own row.
            quick_model=editor_quick_model(self.app_settings, {"model_name": selected_model}),
        )
        thread.check_ready.connect(self._dependency_check_ready)
        thread.check_failed.connect(self._dependency_check_failed)
        thread.finished.connect(
            lambda worker=thread: self._dependency_check_stopped(worker)
        )
        self.dependency_check_thread = thread
        self.refresh_dependency_status()
        self._write_workbench_log("Readiness check started.")
        thread.start()
        self.run_availability_changed.emit()

    def _dependency_check_ready(self, result: DependencyPreflightResult) -> None:
        self.resources.dependencies = result.dependencies
        self.resources.python_exe = result.python_exe
        self.resources.ffmpeg_exe = result.ffmpeg_exe
        self.resources.ffprobe_exe = result.ffprobe_exe
        self.resources.ytdlp_exe = result.ytdlp_exe
        self.resources.python_candidates = result.python_candidates
        self.resources.preflight_complete = True
        self.resources.last_dependency_check = result.checked_at
        # 188: what the check found is used, not saved. Only Choose path saves a path, so a saved
        # path always means one the operator chose; paths saved before keep working as chosen.
        self.refresh_dependency_status()
        self.refresh_review_summary()
        self.missing_tools_notice.show_once(self.resources.dependencies)
        self.ask_about_saved_tool_paths()

    # Installer plan, Stage 1: a path an earlier version saved may be one that version found on this PC, not one
    # the operator chose. Once, when such a path differs from the copy bundled with Media Manglers, the operator
    # is asked which to use; nothing changes silently, and "Keep my paths" is the default.
    SAVED_TOOL_PATHS = (
        ("ffmpeg", "dependency_ffmpeg_path"),
        ("ffprobe", "dependency_ffprobe_path"),
        ("python", "dependency_python_path"),
    )

    def saved_paths_differing_from_bundled(self) -> list[tuple[str, str]]:
        """(setting, saved path) for each saved tool path that differs from a copy bundled with Media Manglers."""

        bundled_dir = str(getattr(self.resources, "bundled_dir", "") or "")
        if not bundled_dir or self.app_settings.get("bundled_tools_question_answered"):
            return []
        differing: list[tuple[str, str]] = []
        for key, setting in self.SAVED_TOOL_PATHS:
            saved = str(self.app_settings.get(setting) or "").strip().strip('"')
            ours = bundled_tool(key, bundled_dir)
            if (saved and ours and Path(ours).is_file()
                    and os.path.normcase(os.path.abspath(saved)) != os.path.normcase(os.path.abspath(ours))):
                differing.append((setting, saved))
        return differing

    def _choose_bundled_tools(self, saved: list[str]) -> bool:
        """The question itself: True for the bundled copies, False to keep the saved paths."""

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Use the tools bundled with Media Manglers?")
        box.setText(
            "Media Manglers now comes with its own FFmpeg and Python. Your settings still point to these, saved "
            "by an earlier version:\n\n" + "\n".join(saved)
            + "\n\nUse the copies bundled with Media Manglers, or keep your paths? You are asked only once; "
            "Settings > Dependencies > Choose path changes it later.")
        use = box.addButton("Use the bundled copies", QMessageBox.ButtonRole.AcceptRole)
        keep = box.addButton("Keep my paths", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(keep)
        box.setEscapeButton(keep)
        box.exec()
        return box.clickedButton() is use

    def ask_about_saved_tool_paths(self) -> None:
        differing = self.saved_paths_differing_from_bundled()
        if not differing:
            return
        use_bundled = self._choose_bundled_tools([saved for _setting, saved in differing])
        self.app_settings["bundled_tools_question_answered"] = True
        if use_bundled:
            for setting, _saved in differing:
                self.app_settings[setting] = ""
        self.save_app_settings()
        self._write_workbench_log(
            "Saved tool paths replaced by the bundled copies." if use_bundled else "Saved tool paths kept.")
        if use_bundled:
            self.resources = discover_runtime_resources(self.app_settings)
            QTimer.singleShot(0, self.start_dependency_check)

    def _dependency_check_failed(self, _details: str) -> None:
        self.resources.dependencies = [
            replace(
                item,
                status="unavailable" if item.status == "checking" else item.status,
                detail="The readiness check could not finish. Select this row for troubleshooting guidance.",
                action_label="Refresh",
                action_kind="check",
            )
            for item in self.resources.dependencies
        ]
        self.resources.preflight_complete = True
        self.dependency_summary.setText(
            "The readiness check could not finish. No system changes were made; choose Refresh to try again."
        )
        self.refresh_dependency_status()

    def _dependency_check_stopped(self, worker: DependencyCheckThread) -> None:
        worker.deleteLater()
        if self.dependency_check_thread is worker:
            self.dependency_check_thread = None
        if getattr(worker, "stopped", False):
            # 193: stopped because the Workbench closed; nothing resumes or navigates.
            return
        self._write_workbench_log("Readiness check finished.")
        self.dependency_check_button.setEnabled(True)
        self.dependency_check_button.setText("Refresh readiness")
        missing = [item.name for item in self.resources.dependencies if item.required and not item.ready]
        self.dependency_check_banner.show_job(JobInfo(
            token="readiness-check", title="Readiness check", state="attention" if missing else "completed",
            detail=(f"Not ready: {', '.join(missing)}. Select a row below for what to do." if missing
                    else "Every required tool is ready.")))
        self.refresh_dependency_status()
        self.run_availability_changed.emit()
        if self.review_inbox_process_after_dependency_check:
            QTimer.singleShot(
                0, self._resume_review_inbox_after_dependency_check
            )
        elif self.standard_review_return_after_dependency_check:
            self.standard_review_return_after_dependency_check = False
            if self.resources.backend_ready:
                self.navigate("New Review")
                self.wizard_steps.setCurrentRow(
                    max(0, min(4, self.standard_review_dependency_return_step))
                )
                self.refresh_review_summary()

    def _dependency_row_selected(self) -> None:
        row = self.dependency_table.currentRow()
        key_item = self.dependency_table.item(row, 0) if row >= 0 else None
        key = str(key_item.data(Qt.ItemDataRole.UserRole) or "") if key_item else ""
        dependency = next(
            (
                item
                for item in self.resources.dependencies
                if (item.key or item.name) == key
            ),
            None,
        )
        if dependency is None:
            self.dependency_details.clear()
            self._show_tool_source(None)
            return
        found = f"<p><b>Found:</b> {escape(dependency.found_by)}</p>" if dependency.found_by else ""
        self.dependency_details.setHtml(
            f"<p><b>State:</b> {escape(dependency.display_status)}</p>"
            f"{found}"
            f"<p><b>Detected version:</b> {escape(dependency.version or 'Not available')}</p>"
            f"<p><b>Detected path:</b> {escape(dependency.path or 'Not available')}</p>"
            f"<p><b>Last checked:</b> {escape(dependency.last_checked or 'Not checked yet')}</p>"
            f"<p><b>Validation result:</b> {escape(dependency.detail or 'No additional detail')}</p>"
        )
        self._show_tool_source(dependency if needs_download(dependency) else None)

    def _fit_dependency_actions(self) -> None:
        # 188: a row can hold two buttons (its action and Download). The Action column fills what
        # is left of the table, so "Why it is needed" gives up just the room they need.
        table = self.dependency_table
        if not self._dependency_actions_fit_pending or not table.isVisible():
            return   # sizes are only real on screen; the header calls this again when it is laid out
        # Once per refresh: after that, the operator's own column widths are left alone.
        self._dependency_actions_fit_pending = False
        needed = max(
            (
                widget.sizeHint().width() + 8
                for row in range(table.rowCount())
                if (widget := table.cellWidget(row, 4)) is not None
            ),
            default=0,
        )
        shortfall = needed - table.horizontalHeader().sectionSize(4)
        if shortfall > 0:
            table.setColumnWidth(1, max(200, table.columnWidth(1) - shortfall))

    def _show_tool_source(self, dependency: DependencyStatus | None) -> None:
        # 188: where to get the selected tool, shown under the table while it is missing.
        source = tool_source(dependency.key) if dependency is not None else None
        self.dependency_get_panel.setVisible(source is not None)
        if source is None:
            self.dependency_get_label.clear()
            self.dependency_copy_winget_button.setEnabled(False)
            self.dependency_copy_winget_button.setProperty("wingetCommand", "")
            return
        text = (
            f"<b>Get {escape(dependency.name)}:</b> official page "
            f'<a href="{escape(source.page)}">{escape(source.page)}</a>'
        )
        if source.winget_command:
            text += (
                "<br>Or install it with Windows Package Manager: "
                f"<code>{escape(source.winget_command)}</code>"
            )
        else:
            text += "<br>It has no Windows Package Manager package; the official page says how to install it."
        self.dependency_get_label.setText(text)
        self.dependency_copy_winget_button.setEnabled(bool(source.winget_command))
        self.dependency_copy_winget_button.setProperty("wingetCommand", source.winget_command)

    def open_tool_download_page(self, key: str) -> None:
        source = tool_source(key)
        if source is None:
            return
        # Opens the page in the browser. The Workbench never downloads or installs anything.
        QDesktopServices.openUrl(QUrl(source.page))
        self._write_workbench_log(f"Opened the official {source.name} page: {source.page}")
        if hasattr(self, "dependency_summary"):
            self.dependency_summary.setText(
                f"Opened the official {source.name} page in your browser. "
                "Nothing was downloaded or installed; after installing it, choose Check readiness."
            )

    def copy_winget_command(self) -> None:
        command = str(self.dependency_copy_winget_button.property("wingetCommand") or "")
        if not command:
            return
        QApplication.clipboard().setText(command)
        self.dependency_summary.setText(
            f"Copied: {command}. Paste it into a terminal to install; the Workbench does not run it."
        )

    def _dependency_action(self, key: str) -> None:
        dependency = next(
            (item for item in self.resources.dependencies if item.key == key),
            None,
        )
        if dependency is None:
            return
        if dependency.action_kind == "check":
            self.start_dependency_check()
            return
        if dependency.action_kind.startswith("choose_"):
            labels = {
                "choose_python": ("Choose Python executable", "dependency_python_path"),
                "choose_ffmpeg": ("Choose FFmpeg executable", "dependency_ffmpeg_path"),
                "choose_ffprobe": ("Choose FFprobe executable", "dependency_ffprobe_path"),
                "choose_ytdlp": ("Choose yt-dlp executable", "dependency_ytdlp_path"),
            }
            title, setting_key = labels[dependency.action_kind]
            path, _ = QFileDialog.getOpenFileName(
                self,
                title,
                dependency.path,
                "Executable files (*.exe);;All files (*.*)",
            )
            if path:
                self.app_settings[setting_key] = path
                self.save_app_settings()
                self.resources = discover_runtime_resources(self.app_settings)
                self.start_dependency_check()
            return
        if dependency.action_kind == "approve_model_download":
            # Installer plan, Stage 3: the approval is the only way a Whisper model downloads, in every feature.
            model = dependency.model or str(self.run_settings.get("whisper_model") or "")
            response = QMessageBox.question(
                self,
                "Approve model download?",
                dependency.detail
                + f"\n\nDownload the Whisper model {model} now? It is saved in the Whisper model cache on this PC, "
                "checked against the file Whisper published, and can use substantial disk space. Nothing else is "
                "changed.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if response == QMessageBox.StandardButton.Yes:
                self.start_model_download([model])
            return
        guidance = {
            "repair_app": (
                "Use a complete Media Manglers application folder containing Video Mangler.ps1 and "
                "python-core\\src\\media_manglers. Re-extract or reinstall the same candidate, then choose Refresh readiness."
            ),
            "install_guide": (
                "Install or repair this component only in the Python/runtime you intend Media Manglers to use. "
                "The Workbench has not run an installer or changed PATH. After your approved setup, return here and choose Refresh readiness."
            ),
            "repair_runtime": (
                "Choose a Python runtime where both openai-whisper and PyTorch import successfully, or repair those packages in the selected runtime. "
                "The Workbench will not alter Python, CUDA, or PATH automatically."
            ),
            "learn_more": (
                "CUDA acceleration is optional when CPU fallback is Ready. A CUDA-capable result requires a compatible GPU plus a PyTorch build that reports CUDA available."
            ),
        }.get(
            dependency.action_kind,
            "Review the validation result under Technical details, correct the local setup, then choose Refresh readiness.",
        )
        QMessageBox.information(
            self,
            f"{dependency.name} guidance",
            guidance,
        )
        self.dependency_summary.setText(
            f"Guidance shown for {dependency.name}. No package, PATH, Python, CUDA, or system setting was changed."
        )
        self.open_troubleshooting_help(
            DEPENDENCY_HELP_ANCHORS.get(
                dependency.key,
                "dependency-readiness-and-preflight",
            )
        )

    def clean_workbench_files(self) -> None:
        owned_root = Path(str(self.app_settings.get("temp_folder") or default_temp_folder())).parent
        results = []
        for target in (
            Path(self.settings_log_folder.text().strip()),
            Path(self.settings_temp_folder.text().strip()),
        ):
            try:
                result = clean_workbench_owned_path(
                    target,
                    owned_root=owned_root,
                    retention_days=self.settings_retention.value(),
                )
                results.append(f"{target}: deleted {result.deleted_files} files")
            except ValueError as exc:
                results.append(str(exc))
        QMessageBox.information(self, "Cleanup result", "\n".join(results))

    # Help and utility

    def _build_help_page(self) -> QWidget:
        page, layout = _page_header(
            "Help",
            "Start with one short operator guide, or jump directly to the task on screen.",
        )
        help_actions = QGridLayout()
        getting_started = QPushButton("Getting started")
        getting_started.setProperty("primary", True)
        getting_started.setAccessibleName("Open the Getting started operator guide")
        online_help = QPushButton("Open exact-build online Help")
        local_help = QPushButton("Open packaged Help")
        troubleshooting = QPushButton("Setup and troubleshooting")
        help_actions.addWidget(getting_started, 0, 0, 1, 2)
        help_actions.addWidget(online_help, 1, 0)
        help_actions.addWidget(local_help, 1, 1)
        help_actions.addWidget(troubleshooting, 2, 0, 1, 2)
        help_actions.setColumnStretch(0, 1)
        help_actions.setColumnStretch(1, 1)
        layout.addLayout(help_actions)
        # 237: "Opening…" then "Opened" under the buttons; a guide that cannot open says why in a dialog.
        self.help_feedback = InlineFeedback()
        self.help_feedback.setObjectName("helpFeedback")
        layout.addWidget(self.help_feedback)

        def bind_help(button: QPushButton, opener: Callable[[], Any]) -> None:
            bind_action(button, lambda: self._opened(opener()), working="Opening…", done="Opened",
                        feedback=self.help_feedback)

        bind_help(getting_started, lambda: self.open_workbench_document("GETTING_STARTED.md", "Getting started guide"))
        bind_help(online_help, self.open_workbench_help)
        bind_help(local_help, self.open_local_help_landing)
        bind_help(troubleshooting, self.open_troubleshooting_help)
        content = QTextBrowser()
        content.setHtml(
            "<h3>New here?</h3>"
            "<p><b>Choose Getting started.</b> It shows the five review steps, what each state means, and where results go.</p>"
            "<h3>Need one workflow?</h3>"
            "<p>Choose its plainly named guide below. Codex Evidence includes the complete click-by-click microphone, blocker, progress, and results path.</p>"
            "<h3>Online and offline</h3>"
            "<p>Exact-build online Help uses this build's full Git commit instead of assuming candidate pages exist on main. "
            "If the exact identity is unavailable or the browser cannot open, the complete packaged copy is used and the reason is explained.</p>"
        )
        layout.addWidget(content, 1)
        workflow_help = QGroupBox("Workflow guides")
        workflow_help_layout = QGridLayout(workflow_help)
        for index, workflow in enumerate(WORKFLOWS):
            button = QPushButton(HELP_WORKFLOW_LABELS[workflow.number])
            button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogInfoView))
            button.setAccessibleName(
                f"Open help for {workflow.display_name}"
            )
            button.setToolTip(
                f"Open the GitHub guide for {workflow.display_name}; use the packaged guide if the link cannot launch."
            )
            bind_help(button, lambda number=workflow.number: self.open_workflow_help(number))
            workflow_help_layout.addWidget(button, index, 0)
            workflow_help_layout.setColumnStretch(0, 1)
        layout.addWidget(workflow_help)
        topic_help = QGroupBox("Common tasks")
        topic_layout = QGridLayout(topic_help)
        topics = (
            ("Progress and results", "PROGRESS_RESULTS.md"),
            ("Dependencies and setup", "DEPENDENCIES_SETUP.md"),
            ("Settings and migration", "SETTINGS_MIGRATION.md"),
            ("Technical reference", "TECHNICAL_REFERENCE.md"),
            # 234: one guide to every feature, added last so no button moves.
            ("Every feature in one guide", "FEATURE_GUIDE.md"),
        )
        for index, (label, document) in enumerate(topics):
            button = QPushButton(label)
            bind_help(button, lambda document=document, label=label: self.open_workbench_document(document, label))
            topic_layout.addWidget(button, index // 2, index % 2)
        topic_layout.setColumnStretch(0, 1)
        topic_layout.setColumnStretch(1, 1)
        layout.addWidget(topic_help)
        return page

    def _exact_build_help_url(self, document: str, anchor: str = "") -> str:
        commit = str(self.build_identity.full_commit or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            return ""
        suffix = f"#{anchor}" if anchor else ""
        return (
            f"{WORKBENCH_HELP_ROOT_URL}/{commit}/docs/workbench/{document}"
            f"{suffix}"
        )

    def _open_documentation_link(
        self,
        document: str,
        label: str,
        anchor: str = "",
    ) -> bool:
        """Open a guide online for this exact build, else the packaged copy. True when one opened."""

        local_path = self.resources.app_root / "docs" / "workbench" / document
        url = self._exact_build_help_url(document, anchor)
        if not url:
            if self._open_path(local_path):
                QMessageBox.information(
                    self,
                    "Opened packaged Help",
                    f"This build does not contain a trustworthy full Git commit for an exact online link. "
                    f"The packaged {label} was opened instead.",
                )
                self._write_workbench_log(
                    f"Exact-build identity unavailable; opened packaged guide: {local_path}"
                )
                return True
            warn(
                self,
                "Help could not open",
                f"The exact-build online {label} is unavailable because the full build commit is missing, "
                "and the packaged guide is also missing. Re-extract the complete application folder.",
            )
            return False
        if QDesktopServices.openUrl(QUrl(url)):
            self._write_workbench_log(f"Opened exact-build online {label}: {url}")
            return True
        if self._open_path(local_path):
            QMessageBox.information(
                self,
                "Online Help did not open",
                f"The exact-build online {label} could not be launched, so the packaged local guide was opened instead.",
            )
            self._write_workbench_log(
                f"Online {label} failed; opened packaged guide: {local_path}"
            )
            return True
        warn(
            self,
            "Help could not open",
            f"The exact-build online {label} could not be launched and the packaged guide is missing. "
            "Check the internet connection or re-extract the complete application folder, then try again.",
        )
        return False

    def open_workbench_help(self, anchor: str = "") -> bool:
        return self._open_documentation_link(
            WORKBENCH_HELP_URL,
            "Workbench Help",
            anchor,
        )

    def open_workbench_document(
        self, document: str, label: str, anchor: str = ""
    ) -> bool:
        return self._open_documentation_link(document, label, anchor)

    def open_local_help_landing(self) -> bool:
        guide = self.resources.app_root / "docs" / "workbench" / "README.md"
        if self._open_path(guide):
            self._write_workbench_log(f"Opened packaged Workbench Help: {guide}")
            return True
        warn(
            self,
            "Packaged Help is missing",
            "The local guide is not present. Re-extract the complete application folder or use Open online Help.",
        )
        return False

    def open_workflow_help(self, workflow: str) -> bool:
        workflow = normalize_workflow(workflow)
        return self._open_documentation_link(
            WORKFLOW_HELP_URLS[workflow],
            f"{WORKFLOW_BY_NUMBER[workflow].title} guide",
        )

    def open_troubleshooting_help(self, anchor: str = "dependency-readiness-and-preflight") -> bool:
        return self._open_documentation_link(
            WORKBENCH_TROUBLESHOOTING_URL,
            "setup and troubleshooting guide",
            anchor,
        )

    @staticmethod
    def _opened(result: Any) -> Outcome:
        """237: a Help button's line: "Opened", or nothing when a dialog already said why not."""

        return Outcome.done("Opened") if result else Outcome.quiet()

    def save_app_settings(self) -> None:
        save_settings(self.app_settings, self.settings_path, repo_root=self.repo_root_path)
        # 220: the recordings drive guard follows the recordings folders as soon as they change.
        set_recordings_folders(watched_folders({**self.app_settings, **{
            key: value for key, value in self.run_settings.items() if key == "review_source_folders" and value}}))

    def _write_workbench_log(self, message: str) -> None:
        try:
            self.run_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.run_log_path.open("a", encoding="utf-8") as handle:
                handle.write(message.rstrip() + "\n")
        except OSError:
            pass

    # 275: when the library cannot be opened ---------------------------------------------------------

    def _library_next_step(self) -> str:
        hint = getattr(self, "_library_hint", "")
        if hint:
            return hint
        if getattr(self, "_library_too_new", False):
            return "Use the newer version of the Workbench; this version does not change your library."
        return ("Close every Workbench window, then start the Workbench again. Your lists come back at the next "
                "start that opens the library.")

    def library_refusal(self, feature: str) -> str:
        """Why ``feature``, which needs the library, does nothing this session; "" while the library is open."""

        if getattr(self, "records", None) is not None or not getattr(self, "library_problem", ""):
            return ""
        return (f"{feature} needs your library, which could not be opened this session, so nothing was started "
                f"and nothing was changed. {self._library_next_step()}")

    # 224 (Wave B2b): Review Media Inbox's one-time move into the library ------------------------------

    def _save_inbox_folder(self, folder: Path) -> None:
        """Step 11 of the move: the settings name the Inbox folder (``review_inbox_folder``); the old
        ``review_ledger_path`` stays as it is, so an older Workbench finds the note and stops."""

        self.app_settings["review_inbox_folder"] = str(folder)
        save_settings(self.app_settings, self.settings_path, repo_root=self.repo_root_path)

    def _log_inbox_move(self) -> None:
        """One line in the log about the move, with counts and never a path (design 4.2, step 12)."""

        result = getattr(self, "inbox_move_result", {}) or {}
        status = str(result.get("status") or "")
        if status in {"nothing", "no library", ""}:
            return
        counts = result.get("counts") or {}
        tables = counts.get("before") or {}

        def rows(table: str) -> int:
            return int((tables.get(table) or {}).get("rows") or 0)

        if status == "moved":
            mined = counts.get("mined") or {}
            self._write_workbench_log(
                f"Review Media Inbox's records moved into the library: {rows('sources')} recordings, "
                f"{rows('batches')} batches, {rows('findings')} findings, {rows('final_results')} final results, "
                f"{rows('lifecycle_events')} lifecycle events; {counts.get('record_files', 0)} record files checked; "
                f"Mined by the Inbox: {mined.get('before', 0)} before, {mined.get('after', 0)} after "
                f"(receipt {result.get('receipt')}).")
            return
        detail = f" ({result.get('error')})" if result.get("error") else ""
        line = (f"Review Media Inbox's move into the library: {status}. "
                f"{result.get('message') or ''}{detail}".rstrip())
        named = str(self.app_settings.get("review_ledger_path") or "").strip()
        if named:  # the page says which folder; the log never does
            line = line.replace(str(Path(named).parent), "the Inbox folder")
        self._write_workbench_log(line)

    def _review_inbox_folder(self) -> str:
        """The Inbox folder (224, Q3): this run's setting, else the saved one."""

        return str(self.run_settings.get("review_inbox_folder") or self.app_settings.get("review_inbox_folder")
                   or "").strip()

    def _review_inbox_not_ready(self) -> str:
        """Why the Inbox opens nothing yet (224, design 4.1), in one plain line; "" when it may run."""

        result = getattr(self, "inbox_move_result", {}) or {}
        if str(result.get("status") or "") in {"waiting", "refused", "restored"} and result.get("message"):
            return str(result["message"])
        records = getattr(self, "records", None)
        if records is None:
            return ""
        folder = self._review_inbox_folder()
        try:
            found = inbox_records.status(records.connection(), folder or None)
        except (sqlite3.Error, ValueError) as exc:
            return f"The Inbox's records could not be read from the library, so nothing was started. ({exc})"
        return "" if found.ready else found.message

    def _show_library_notice(self) -> None:
        """One notice at start (275), without stopping: what could not be opened, why, and what to do."""

        if held_in_settings(self.app_settings):
            # 224 (Wave B2a, note 12): lists never moved into the library are still in the settings, and Find my
            # bug reports still reads them there, so they are not called unseen.
            opening = ("Your library could not be opened, so Review Media Inbox does not run this session. Your "
                       "never-use and already-done lists are still in your settings, so Find my bug reports uses "
                       "them as before.")
        else:
            opening = ("Your library could not be opened, so your never-use and already-done lists are not shown "
                       "this session, and Review Media Inbox does not run.")
        text = (f"{opening} Nothing was lost.\n\n"
                f"Why: {self.library_problem}\n\n{self._library_next_step()}")
        self.library_notice = warn(self, "Your library could not be opened", text, wait=False)

    def _open_path(self, path: Path | None) -> bool:
        # 125: a video plays in the player the operator chose instead of
        # being handed to Windows. Decided by the name alone, never by whether
        # the file is there: a recording that has moved must reach the
        # opener's "Find it…" message, not open its old folder in silence.
        if path and str(path) and is_video_path(path):
            # The loaded package goes along so a clip opened from its file list
            # is known to be a package file, not one of the operator's
            # recordings, even when the package folder was renamed or unzipped.
            package = getattr(self, "current_package", None)
            package_root = getattr(package, "root", None)
            return self.video_opener.open(PlayTarget(path=Path(path), package_root=package_root))
        return self._open_path_system(path)

    def _open_path_system(self, path: Path | None) -> bool:
        """Hand a file or folder to Windows. Everything that is not a video."""

        if not path or not str(path):
            return False
        target = path
        if not target.exists() and target.parent.exists():
            target = target.parent
        if target.exists():
            return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.resolve()))))
        return False

    def _open_outcome(self, path: Path | None, what: str) -> Outcome:
        """237: open a file or folder and say beside the button whether it opened."""

        if self._open_path(path):
            return Outcome.done("Opened")
        if not path or not str(path):
            return Outcome.failed(f"There is no {what} yet.", "Run a review first.")
        if path.exists() or path.parent.exists():
            return Outcome.failed(f"Windows did not open the {what}.", f"Open it yourself: {path}")
        return Outcome.failed(f"The {what} is not there any more.", "It may have been moved or deleted.")

    def open_current_log(self) -> Outcome:
        return self._open_outcome(self.run_log_path, "log")

    def open_current_output(self) -> Outcome:
        # 214: the folder the run wrote to, the one the results location and History name.
        path = self._run_output()
        return self._open_outcome(Path(path) if path else None, "output folder")

    def open_last_evidence_package(self) -> None:
        path = str(self.app_settings.get("last_evidence_package") or "")
        if path and Path(path).exists():
            self.load_package(path)
            self.navigate("Evidence")
        else:
            self.choose_evidence_package()

    def open_diagnostic_terminal(self) -> Outcome:
        powershell = self.resources.powershell_exe or "powershell"
        creation_flags = int(getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        try:
            subprocess.Popen(
                [powershell, "-NoExit", "-NoProfile", "-Command", f"Set-Location -LiteralPath '{str(self.resources.app_root).replace("'", "''")}'"],
                cwd=str(self.resources.app_root),
                creationflags=creation_flags,
            )
        except OSError as exc:
            warn(self, "Diagnostic terminal unavailable", str(exc))
            return Outcome.quiet()
        return Outcome.done("Terminal opened")

    def _restore_window_geometry(self) -> None:
        if not self.app_settings.get("restore_window_geometry", True):
            return
        encoded = str(self.app_settings.get("window_geometry") or "")
        if encoded:
            self.restoreGeometry(QByteArray.fromBase64(encoded.encode("ascii")))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        # 125: first, above everything. Six paths below refuse to close and
        # return early, and none of them may leave the built-in player holding
        # a recording's file open. This never waits and never asks anything.
        self.video_opener.release_media()
        if self.runner_thread and not self._closing_after_smoke:
            response = QMessageBox.question(
                self,
                "Review still running",
                (
                    "Emergency-cancel the active targeted-evidence request and close? Completed request packages reconcile on retry, but recovery may be required."
                    if self.review_inbox_active_action == "TargetedEvidence"
                    else (
                        "Emergency-cancel Review Media Inbox processing and close? "
                        "The current operation may not reach its safe boundary, and recovery may be required."
                    )
                )
                if self.external_run is None and self._running_inbox()
                else "Cancel the active review and close the Workbench?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if response != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.runner_thread.cancel()
            self.runner_thread.wait(5000)
        if self.review_inbox_reconcile_thread is not None:
            self.review_inbox_reconcile_thread.wait(5000)
            if self.review_inbox_reconcile_thread.isRunning():
                if hasattr(self, "review_inbox_attention"):
                    self.review_inbox_attention.setText(
                        "The local queue check is still finishing. Close after it completes."
                    )
                    self.review_inbox_attention.setVisible(True)
                self._write_workbench_log("Close refused: the Inbox's local queue check was still finishing.")
                event.ignore()
                return
        if self.app_settings.get("restore_window_geometry", True):
            self.app_settings["window_geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
        if self.audio_inspection_thread is not None:
            self.audio_inspection_thread.cancel()
            self.audio_inspection_thread.wait(5000)
        # 236: a video card's picture still being taken from a render is finished first, so no file stays open.
        editor = getattr(self, "ai_video_editor_page", None)
        if editor is not None:
            editor.thumbnails.stop(5000)
        # Before the settings are saved: closing the player is what writes its
        # window position and volume into them.
        if not self.video_opener.shutdown(5000):
            self._write_workbench_log(
                "Close refused: the built-in player was still looking for a recording or its transcript."
            )
            if self.video_opener.player_window is not None:
                # Said in the player's own window, which is brought forward.
                # Any page of this window may be the one showing, so a label
                # on one of them could go unseen and the X would seem dead.
                self.video_opener.say(
                    "The built-in player is still finishing. Close the Workbench again in a moment."
                )
            elif not self._closing_after_smoke:
                # No player window yet: the recording asked for is still being
                # looked for. Never shown to a close nobody is watching, which
                # it would hold up for good.
                QMessageBox.information(
                    self,
                    "Still looking for a recording",
                    "The Workbench is still looking for the recording you asked to play; its drive is "
                    "slow to answer. Close the Workbench again in a moment.",
                )
            event.ignore()
            return
        # 193: closing never waits for the readiness check. It is stopped, with any tool it
        # started, and runs again at the next launch. Last of the waits, so nothing after it can
        # refuse the close and leave the window open with the check stopped.
        if self.dependency_check_thread is not None:
            self._stop_dependency_check_for_close()
        # Installer plan, Stage 3: an approved model download stops with the window, like the readiness check;
        # its partial file never looks like a model and is removed at the next try.
        if self.model_download_thread is not None:
            download = self.model_download_thread
            download.cancel()
            if not download.wait(3000):
                _STILL_STOPPING.add(download)
                download.finished.connect(functools.partial(_STILL_STOPPING.discard, download))
            self._write_workbench_log("Whisper model download stopped because the Workbench closed.")
        # 135: a waveform build stops at once, keeping what it measured; it never holds the close up.
        self.levels_service.shutdown()
        # 220: the library's connection is closed so its write-ahead log is folded in.
        raw_bin = getattr(self, "raw_bin_page", None)
        if raw_bin is not None:
            raw_bin.close_library()
        self.save_app_settings()
        # 243: the Workbench's own connection too; letting go of its session tells the next start that
        # a run this Workbench left unfinished was cut off.
        if self.records is not None:
            self.records.close()
            self.records = None
        self._write_workbench_log("Workbench closed.")
        event.accept()

    def start_model_download(self, models: list[str]) -> bool:
        """Download the Whisper models the operator just approved, as a job with its banner on Settings >
        Dependencies; readiness is checked again when it ends (installer plan, Stage 3)."""

        models = [name for name in dict.fromkeys(str(item or "").strip() for item in models) if name]
        if not models or self.model_download_thread is not None:
            return False
        if not self.resources.python_exe or self.resources.backend_source_root is None:
            self.dependency_summary.setText(
                "The model cannot be downloaded until the Python that runs Whisper is ready. Fix the Python rows, "
                "then Refresh readiness.")
            return False
        work = Path(str(self.app_settings.get("temp_folder") or default_temp_folder())) / (
            f"model-download-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        request, result = work / "request.json", work / "result.json"
        argv = cli_command(self.resources, "whisper-model-download", request, result).argv
        thread = ModelDownloadThread(argv, request, result, work / "progress.json", models)
        names = ", ".join(models)
        thread.progress_changed.connect(lambda text: self.dependency_check_banner.show_job(JobInfo(
            token="model-download", title=f"Downloading the Whisper model {names}", state="active", detail=text)))
        thread.download_finished.connect(lambda ok, message, folder=work: self._model_download_finished(
            ok, message, folder))
        thread.finished.connect(lambda worker=thread: self._model_download_stopped(worker))
        self.model_download_thread = thread
        self.dependency_check_banner.show_job(JobInfo(
            token="model-download", title=f"Downloading the Whisper model {names}", state="active",
            detail="Approved by you; checked against the file Whisper published before it is used"))
        self.dependency_summary.setText(f"Downloading the Whisper model {names}. You can keep working meanwhile.")
        self._write_workbench_log(f"Whisper model download approved and started: {names}.")
        thread.start()
        return True

    def _model_download_finished(self, ok: bool, message: str, work: Path) -> None:
        self.dependency_check_banner.show_job(JobInfo(
            token="model-download", title="Whisper model download", state="completed" if ok else "attention",
            detail=message))
        self.dependency_summary.setText(message)
        self._write_workbench_log(f"Whisper model download {'finished' if ok else 'failed'}: {message}")
        try:
            safe_write.remove_disposable_tree(work, within=work.parent)
        except OSError:
            pass  # the Workbench's own temporary folder; clean-up removes it later
        if ok:
            QTimer.singleShot(0, self.start_dependency_check)

    def _model_download_stopped(self, worker: ModelDownloadThread) -> None:
        worker.deleteLater()
        if self.model_download_thread is worker:
            self.model_download_thread = None

    def model_blockers(self, models: list[str]) -> list[str]:
        """Installer plan, Stage 3: why each of ``models`` cannot be used yet, from its readiness row: missing or not
        matching the file Whisper published. A model not checked yet blocks nothing here; its run's own check
        refuses it in the same words."""

        reasons: list[str] = []
        for name in dict.fromkeys(str(item or "").strip() for item in models):
            row = next((item for item in self.resources.dependencies
                        if item.key.startswith("whisper_model") and item.model == name), None)
            if row is None or row.ready or row.status in {"not_checked", "checking", "info"}:
                continue
            reasons.append(f"Whisper model {name}: {row.detail} Open Settings > Dependencies to approve it.")
        return reasons

    def _stop_dependency_check_for_close(self) -> None:
        thread = self.dependency_check_thread
        if thread is None:
            return
        thread.cancel()
        if thread.wait(3000):
            self._write_workbench_log("Readiness check stopped because the Workbench closed.")
            return
        # Ending its processes did not end it. The close goes ahead; the thread is kept alive
        # until it ends, and the process may not wait for it at exit (see main).
        _STILL_STOPPING.add(thread)
        thread.finished.connect(functools.partial(_STILL_STOPPING.discard, thread))
        self._write_workbench_log(
            "Readiness check had not stopped 3 seconds after the Workbench closed; closing anyway."
        )


# 193: readiness checks still stopping when the window closed. main() waits for them briefly,
# then ends the process without them, so the exit can never hang on one.
_STILL_STOPPING: set[QThread] = set()


# 237: on Windows, text is drawn by GDI, not Qt's default DirectWrite. Measured on screen, DirectWrite draws
# Segoe UI softer at 110% to 150% text size (17% more soft edge pixels in body text at 125%); GDI snaps
# the letters to whole pixels at every size. At 100% the two draw the same.
WINDOWS_PLATFORM = "windows:fontengine=gdi"


def qt_arguments(arguments: list[str]) -> list[str]:
    """The arguments the Workbench's QApplication is made with: GDI text on Windows, unless a platform
    was chosen already (QT_QPA_PLATFORM, as the tests and the offscreen smoke launch do)."""

    if sys.platform == "win32" and not os.environ.get("QT_QPA_PLATFORM") and "-platform" not in arguments:
        return [*arguments, "-platform", WINDOWS_PLATFORM]
    return list(arguments)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--open-package", default="")
    parser.add_argument("--start-page", choices=PAGE_NAMES, default="")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--offscreen", action="store_true")
    parser.add_argument("--capture-screenshot", default="")
    parser.add_argument("--exit-after-ms", type=int, default=0)
    parser.add_argument(
        "--review-inbox-exact-source",
        action="append",
        default=[],
        help=(
            "Advanced run-scoped qualification restriction. Repeat for each "
            "exact source; this is not saved as an ordinary Workbench default."
        ),
    )
    return parser.parse_args(argv)


SMOKE_STACK_FILE = "smoke-launch-stacks.txt"
SMOKE_STACK_AFTER_SECONDS = 15   # the build waits 30 seconds, so the stacks are written by then


ALREADY_OPEN_TITLE = "Media Manglers is already open"
ALREADY_OPEN_TEXT = (
    "Media Manglers is already open in another window. Only one can run at a time, because both would use the "
    "same library and settings. Switch to the window that is open.")
ALREADY_OPEN_EXIT = 4


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    # 224 (Wave B2a): everything this Workbench starts (the host, the helpers, FFmpeg) inherits its process
    # number, so a file one of them holds counts as the app's own and is never waited for.
    safe_write.mark_app_process()
    # Installer plan, Stage 2: one Workbench at a time for the same data, and every running Media Manglers holds
    # the lock the installer looks for. A second Workbench says so and closes before it opens anything.
    if not app_locks.take_workbench_lock():
        if args.offscreen:
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        if not args.smoke_test:
            notice_app = QApplication.instance() or QApplication(qt_arguments(sys.argv[:1]))
            QMessageBox.information(None, ALREADY_OPEN_TITLE, ALREADY_OPEN_TEXT)
            del notice_app
        print(ALREADY_OPEN_TEXT, file=sys.stderr, flush=True)
        return ALREADY_OPEN_EXIT
    app_locks.hold_running_lock()
    # 159: the build's smoke launch sometimes never ends, and the app's log stops at "Workbench
    # started." If this launch is still running after the limit, every thread's Python stack is
    # written beside the app's logs, so the build can show where it was waiting. It is armed first,
    # before the window is built: a hang while building or showing it must be caught too.
    stack_file = None
    if args.smoke_test:
        import faulthandler

        logs = default_log_folder()
        logs.mkdir(parents=True, exist_ok=True)
        stack_file = open(logs / SMOKE_STACK_FILE, "w", encoding="utf-8")
        faulthandler.dump_traceback_later(SMOKE_STACK_AFTER_SECONDS, file=stack_file)
    if args.offscreen:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(qt_arguments(sys.argv[:1]))
    app.setApplicationName("Video Mangler Workbench")
    app.setOrganizationName("MediaManglers")
    window = WorkbenchWindow(
        review_inbox_exact_source_paths=list(args.review_inbox_exact_source)
    )
    if args.open_package:
        try:
            window.load_package(args.open_package)
            window.navigate("Evidence")
        except OSError:
            pass
    if args.start_page:
        window.navigate(args.start_page)
    window.show()

    def finish_smoke() -> None:
        if args.capture_screenshot:
            screenshot_path = Path(args.capture_screenshot)
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(screenshot_path))
        if args.smoke_test or args.exit_after_ms:
            window._closing_after_smoke = True
            # 159: closing no longer waits for the readiness check (193). If anything else
            # refuses the close, Qt cancels the quit and nothing would ask again, so the launch
            # would never end: it ends now with an error, and the log says what refused.
            if not window.close():
                window._write_workbench_log(
                    "Smoke launch: the window refused to close (see the line above); ending with an error."
                )
                app.exit(3)
                return
            app.quit()
        # The hang recorder stays armed until the process ends: a launch that ends in time writes
        # nothing, and one stuck while closing is caught too.

    delay = args.exit_after_ms or (1200 if args.smoke_test else 0)
    if args.capture_screenshot and not delay:
        delay = 1200
    if delay:
        QTimer.singleShot(delay, finish_smoke)
    code = app.exec()
    # 193: a readiness check that did not stop when the window closed may not hold the exit, and
    # nor may a waveform build that was ended hard when it closed (135).
    stopping = (*_STILL_STOPPING, *parked_levels_threads())
    for thread in stopping:
        thread.wait(2000)
    if any(thread.isRunning() for thread in stopping):
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
