"""The "Find my bug reports" front door (95).

One screen does the whole job: choose recordings, press one button, and end
on a results screen with the prompt for Claude Code or Codex. The voice track
is found automatically for each recording by the backend (94), so there is
no microphone confirmation step.

The page drives the existing Workflow 3 backend (``Video Mangler.ps1
-CodexEvidencePackage``). Several hand-picked recordings are passed as one
``.mmlist`` file so they become one package without copying the media.

The run goes through the Workbench's shared runner (103): it shows on
Queue / Progress, writes the normal run log, lands in History and opens its
package on Evidence, exactly like a run started from New.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import time
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QModelIndex, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from media_manglers.core import speech_facts
from media_manglers.core.user_folders import temporary_folder_problem
from media_manglers.core.recording_records import (
    OUTCOME_CANCELLED,
    OUTCOME_COMPLETED,
    OUTCOME_FAILED,
    OUTCOME_NO_NARRATION,
    OUTCOME_NOT_REPORTED,
    OUTCOME_SKIPPED,
    Records,
)

from . import run_status
from .command_builder import CommandSpec, build_workflow_command
from .evidence import load_evidence_package
from .metadata import WORKFLOW_CODEX_EVIDENCE
from .play_targets import PlaySequence, PlayTarget
from .prompts import build_session_prompt
from .review_package import read_narration_index
from .recording_lists import (
    add_excluded,
    excluded_entries,
    excluded_keys,
    excluded_paths,
    held_in_settings,
    in_library,
    lists_of,
    mark_processed,
    path_key,
    processed_dates,
    remove_excluded,
    set_stopped_run,
    stopped_run,
)
from .runner import RunnerResult, hidden_subprocess_creation_flags
from .settings import build_default_settings, default_output_folder, starter_profile_settings
from .tables import grow_to_contents, make_columns_resizable
from .theme import status_color
from .ui_parts import FlowLayout, InlineFeedback, Outcome, bind_action, warn
from .video_open import path_role_resolver

if TYPE_CHECKING:  # pragma: no cover
    from .app import WorkbenchWindow

PAGE_NAME = "Find Bug Reports"
NAV_LABEL = "Bugs"
BASE_PROFILE = "iRacing Ticket Evidence - Balanced"
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".mov", ".avi", ".m4v", ".webm"}
PROGRESS_PREFIX = "MM_PROGRESS_V1 "
PROBLEM_LINE = re.compile(r"^\s+-\s+(.+?\.(?:mkv|mp4|mov|avi|m4v|webm):\s.+)$", re.IGNORECASE)

# 196: the backend's log line when Whisper moved from the graphics card to the processor, and the
# text Whisper gives for a speech model file that failed its SHA-256 check.
GPU_FALLBACK_LINE = re.compile(
    r"\[GPU->CPU\].*?GPU failure reason:\s*(?P<reason>.*?)(?:\.\s+The (?:helper|current timeout)\b.*)?$"
)
MODEL_CHECKSUM_TEXT = "sha256 checksum does not"


def whisper_model_file(model_name: str) -> Path:
    """Where Whisper keeps a downloaded speech model for this Windows account."""

    return Path.home() / ".cache" / "whisper" / f"{model_name or 'medium'}.pt"


def whisper_notice(lines: list[str], model_name: str) -> str:
    """A plain-English note, with the fix, when the speech model is damaged or the graphics card
    could not be used; empty when neither happened (196)."""

    damaged = any(MODEL_CHECKSUM_TEXT in line.lower() for line in lines)
    fallback = next((match for match in (GPU_FALLBACK_LINE.search(line) for line in lines) if match), None)
    model = whisper_model_file(model_name)
    parts: list[str] = []
    if damaged:
        parts.append(
            f'The Whisper speech model "{model.stem}" on this PC is damaged: it failed its checksum check'
            + (", so your graphics card could not be used and speech is being written down on the processor, "
               "which is much slower." if fallback else ".")
            + f" To fix it, when this run ends rename {model} to {model.name}.bad and run again; Whisper then "
            "downloads a fresh copy."
        )
    elif fallback:
        reason = fallback.group("reason").strip().rstrip(".")
        parts.append(
            "Your graphics card could not be used for writing down speech, so this run uses the processor and is "
            f"much slower. Reason: {reason}. To fix it, check Settings > Dependencies, where CUDA should say Ready, "
            "then run again."
        )
    return " ".join(parts)


ROW_WAITING = "Waiting"
ROW_LISTENING = "Finding your voice"
ROW_TRANSCRIBING = "Transcribing"
ROW_DONE = "Done"
ROW_NO_NARRATION = "No narration found"
ROW_FAILED = "Could not be used"
ROW_SKIPPING = "Skipping…"
ROW_SKIPPED = "Skipped by you"
# A recording this long is usually a session left running; ask before
# spending an hour or more on it (114).
LONG_RECORDING_SECONDS = 2 * 60 * 60
# Colour of each row status: green while working or done, orange for no
# narration, red when a recording could not be used.
ROW_STATUS_KIND = {
    ROW_WAITING: "waiting",
    ROW_LISTENING: "active",
    ROW_TRANSCRIBING: "active",
    ROW_DONE: "completed",
    ROW_NO_NARRATION: "no_narration",
    ROW_FAILED: "failed",
    ROW_SKIPPING: "waiting",
    ROW_SKIPPED: "waiting",
}
FINISHED_ROW_STATES = {ROW_DONE, ROW_NO_NARRATION, ROW_FAILED, ROW_SKIPPED}
# What the built-in player calls the list it was opened from (125).
PLAY_LIST_LABEL = "Find my bug reports list"


@dataclass
class RecordingRow:
    path: Path
    track_override: int | None = None
    state: str = ROW_WAITING
    voice_track: int | None = None
    # What decided the voice track (196): "from track name", "from your setting" or
    # "auto-detected", as the backend's "Voice found on Track N (...)" line says.
    voice_source: str = ""
    note: str = ""
    # 264: the "You chose Track 3. ..." line, when your answer differs from a stored automatic pick.
    choice_line: str = ""


def voice_track_text(row: RecordingRow) -> str:
    """"Track 2 (from track name)": the voice track and what decided it, when the backend said."""

    return f"Track {row.voice_track} ({row.voice_source})" if row.voice_source else f"Track {row.voice_track}"


class _WaveformsListener:
    """One run's word from the levels job (135): it reaches the page only while that run's line is shown."""

    def __init__(self, page: Any) -> None:
        self.page = page

    def on_waveforms(self, ready: int, total: int, working: bool) -> None:
        if getattr(self.page, "_waveforms_listener", None) is self:
            self.page.on_waveforms(ready, total, working)


@dataclass
class RunSummary:
    status: str
    package_root: Path | None
    usable: int = 0
    total: int = 0
    problems: list[str] = field(default_factory=list)
    flagged_moments: int = 0
    error: str = ""
    narration_moments: int = 0
    screenshots: int = 0
    clips: int = 0
    review_videos: int = 0
    skipped: int = 0
    # 196: recordings that simply had no narration. A correct result, not a problem.
    no_narration: list[str] = field(default_factory=list)

    @property
    def outcome_kind(self) -> str:
        """completed, attention or failed: orange and red are for real problems only (196)."""

        if self.status == "complete" and not self.error:
            return "completed"
        if self.status == "nothing_usable" and self.no_narration and not self.problems and not self.error:
            return "completed"
        if self.status == "complete_with_problems":
            return "attention"
        return "failed"


def _is_no_narration(problem: str) -> bool:
    return "no narration found" in problem.lower()


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit in {"B", "KB"} else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def format_duration(seconds: float) -> str:
    minutes = int(round(seconds / 60))
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"


def probe_duration_seconds(ffprobe: str, path: Path) -> float | None:
    """Length of a recording in seconds, or None when it cannot be read."""

    if not ffprobe:
        return None
    try:
        completed = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=hidden_subprocess_creation_flags(),
        )
        return float(completed.stdout.strip().splitlines()[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def newest_recordings(folder: Path, count: int, *, leave_out: set[str] | None = None) -> list[Path]:
    """Newest video files in one folder (not subfolders); read-only listing.

    ``leave_out`` holds recordings the operator excluded or already turned
    into a package, so "Add newest" offers new recordings only (114).
    """

    try:
        files = [
            item
            for item in folder.iterdir()
            if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS
        ]
    except OSError:
        return []
    files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    if leave_out:
        files = [item for item in files if _path_key(item) not in leave_out]
    return files[: max(0, count)]


# One rule for "is this the same recording", shared with recording_lists so the
# built-in player, the never-use list and this page can never disagree (125).
_path_key = path_key


def write_recording_list(paths: list[Path], destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "# Recordings for one bug-report package\n" + "\n".join(str(path) for path in paths) + "\n",
        encoding="utf-8",
    )
    return destination


def selections_json(rows: list[RecordingRow]) -> str:
    overrides = {
        str(row.path): {
            "audioOrdinal": int(row.track_override) - 1,
            "humanTrackNumber": int(row.track_override),
            "ffmpegMap": f"0:a:{int(row.track_override) - 1}",
            "confirmationSource": "operator",
        }
        for row in rows
        if row.track_override
    }
    return json.dumps(overrides) if overrides else ""


def preset_evidence_options(repo_root: str = "") -> dict[str, Any]:
    """The options the racing preset sets on top of the factory defaults."""

    defaults = build_default_settings(repo_root=repo_root)
    preset = starter_profile_settings(repo_root).get(BASE_PROFILE, {})
    return {
        key: value
        for key, value in preset.items()
        if key not in defaults or defaults[key] != value or key == "evidence_profile_setup_name"
    }


def build_bug_report_settings(
    app_settings: dict[str, Any],
    rows: list[RecordingRow],
    run_folder: Path,
    *,
    repo_root: str = "",
) -> dict[str, Any]:
    """Settings for one run: the operator's Settings, the racing evidence
    preset's evidence options, and this run's inputs.

    The preset is built on the factory defaults, so only the options the
    preset itself changes are applied. Folders, tool paths and every other
    Setting the operator chose stay as they are (103).
    """

    settings = dict(app_settings)
    settings.update(preset_evidence_options(repo_root))
    list_path = write_recording_list([row.path for row in rows], run_folder / "recordings.mmlist")
    settings["default_workflow"] = WORKFLOW_CODEX_EVIDENCE
    settings["input_kind"] = "local"
    settings["input_path"] = str(list_path)
    settings["output_folder"] = str(run_folder)
    # The portable ZIP fails closed on any URL in the text; the prompt uses the
    # real local folder, so the local package is all the agent needs.
    settings["evidence_handoff_mode"] = "Local"
    settings["evidence_repo_map_path"] = str(app_settings.get("evidence_repo_map_path") or "")
    settings["whisper_model"] = str(app_settings.get("whisper_model") or "medium")
    settings["whisper_device"] = str(app_settings.get("whisper_device") or "Auto")
    settings["open_output_in_explorer"] = False
    # The usual microphone track is only a tie-breaker, and 264 makes it each recording's own: the backend asks
    # voice-track-known for the saved answer for that recording's track layout. A run-wide number here could
    # not say which layout it came from, nor tell Track 1 from no preference.
    settings["evidence_audio_stream_index"] = 0
    # A forced track confirms that one recording through the list below. The
    # run-wide switch would confirm every other recording as well, and the
    # backend would then skip listening to them and use the usual track
    # without saying so (142). It is off even if another review left it on.
    settings["evidence_audio_stream_selections_json"] = selections_json(rows)
    settings["evidence_audio_stream_selection_confirmed"] = False
    return settings


def parse_progress_line(line: str) -> dict[str, Any] | None:
    if not line.startswith(PROGRESS_PREFIX):
        return None
    try:
        payload = json.loads(line[len(PROGRESS_PREFIX):])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def summarize_package(package_root: Path, runner_status: str, stdout: list[str]) -> RunSummary:
    """Read what the backend actually produced; never assume success."""

    manifest_path = package_root / "manifest.json"
    listed = list(
        dict.fromkeys(
            match.group(1).strip()
            for match in (PROBLEM_LINE.match(line) for line in stdout)
            if match
        )
    )
    # 196: a recording with no narration is listed by the backend, but it is not a problem.
    no_narration = [line for line in listed if _is_no_narration(line)]
    problems = [line for line in listed if not _is_no_narration(line)]
    if not manifest_path.is_file():
        if listed:
            return RunSummary(status="nothing_usable", package_root=None, total=len(listed), problems=problems,
                              no_narration=no_narration)
        error = next(
            (line.split("ERROR:", 1)[1].strip() for line in reversed(stdout) if "ERROR:" in line),
            "",
        ) or next((line.strip() for line in reversed(stdout) if line.strip()), "No package was written.")
        return RunSummary(status="failed", package_root=None, problems=problems, error=error,
                          no_narration=no_narration)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources = list(manifest.get("sources") or [])
    skipped = sum(1 for source in sources if str(source.get("status") or "") == "operator_skipped")
    usable = sum(
        1
        for source in sources
        if str(source.get("status") or "") in {"completed", "skipped"}
        and (source.get("transcript_quality") or {}).get("quality_status") != "no_narration_found"
    )
    flagged = int(manifest.get("detected_candidate_count") or 0) + int(manifest.get("review_needed_count") or 0)
    status = "complete" if runner_status == "succeeded" and not problems else "complete_with_problems"
    if usable == 0:
        status = "nothing_usable"
    # 134: the one reader of the narration index, the same one the Evidence page lists clips from.
    visuals = read_narration_index(package_root) or {}
    return RunSummary(
        status=status,
        package_root=package_root,
        usable=usable,
        total=len(sources) - skipped,
        skipped=skipped,
        problems=problems,
        no_narration=no_narration,
        flagged_moments=flagged,
        narration_moments=int(visuals.get("moment_count") or 0),
        screenshots=int(visuals.get("frame_count") or 0),
        clips=int(visuals.get("clip_count") or 0),
        review_videos=int(visuals.get("review_video_count") or 0),
    )


def results_headline(summary: RunSummary) -> str:
    if summary.status == "failed":
        return "The run stopped before a package was built."
    if summary.status == "nothing_usable":
        # Only when that is what the backend said about every recording: one
        # whose voice track could not be told apart is full of speech (142).
        if not summary.problems:
            return "No narration was found in these recordings, so there is nothing to hand to your AI agent."
        count = len(summary.problems) + len(summary.no_narration)
        return (
            f"Nothing is ready for your AI agent yet: {count} recording{'s' if count != 1 else ''} could not be "
            "used (see below). Where the app could not tell which track is your voice, press Fix and continue "
            "and choose it."
        )
    recordings = f"{summary.usable} of {summary.total} recording{'s' if summary.total != 1 else ''}"
    if summary.no_narration:
        none = len(summary.no_narration)
        headline = (
            f"Done. {recordings} had narration; {none} had none, so nothing to report from "
            f"{'it' if none == 1 else 'them'}. Your narration is ready for your AI agent."
        )
    else:
        headline = f"Done. Your narration from {recordings} is ready for your AI agent."
    if summary.problems:
        headline += f" {len(summary.problems)} recording{'s' if len(summary.problems) != 1 else ''} could not be used (see below)."
    if summary.skipped:
        headline += f" {summary.skipped} skipped by you."
    return headline


def _fit_to_what_they_show(table: QTableWidget) -> None:
    """237: every column but Recording as wide as what it shows now (and its header), so Recording,
    the widest, gets the rest instead of space kept for a message that may never appear. Every column
    can still be dragged (112)."""

    grow_to_contents(table, range(1, table.columnCount()), fill=0)


class RecordingTable(QTableWidget):
    """Recording list that accepts dropped video files."""

    files_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__(0, 4)
        self.setHorizontalHeaderLabels(["Recording", "Size", "Voice track", "Status"])
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        # 237: each column as wide as what it shows; Recording, the widest, takes the rest.
        make_columns_resizable(self, widths={0: 280}, stretch_last=False, stretch=0)
        _fit_to_what_they_show(self)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class BugReportsPage(QWidget):
    """Choose recordings -> Start -> Results with the agent prompt."""

    def __init__(self, host: "WorkbenchWindow") -> None:
        super().__init__()
        self.host = host
        self.rows: list[RecordingRow] = []
        self.running = False
        self.run_settings: dict[str, Any] = {}
        self.stdout_lines: list[str] = []
        self.current_source = ""
        self.run_folder: Path | None = None
        self.summary: RunSummary | None = None
        self.started = 0.0
        self.prompts: dict[str, str] = {}
        # 115: a stopped run can be continued into the same package folder;
        # finished transcripts, voice-track picks, screenshots and clips are reused.
        self.continue_folder: Path | None = None
        self._last_run_id = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        title = QLabel("Find my bug reports")
        title.setProperty("title", True)
        layout.addWidget(title)
        self.status_sentence = QLabel()
        self.status_sentence.setObjectName("bugReportsStatus")
        self.status_sentence.setProperty("accent", True)
        self.status_sentence.setWordWrap(True)
        layout.addWidget(self.status_sentence)
        # 196: a damaged speech model or a run that fell back to the processor, said on screen.
        self.whisper_notice = QLabel()
        self.whisper_notice.setObjectName("bugReportsWhisperNotice")
        self.whisper_notice.setProperty("statusKind", "attention")
        self.whisper_notice.setWordWrap(True)
        self.whisper_notice.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.whisper_notice.setVisible(False)
        layout.addWidget(self.whisper_notice)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        self.stack.addWidget(self._build_choose_view())
        self.stack.addWidget(self._build_working_view())
        self.stack.addWidget(self._build_results_view())

        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.setInterval(1000)
        self.elapsed_timer.timeout.connect(self._refresh_elapsed)
        self._restore_stopped_run()
        self._refresh_choose_state()

    # Views ---------------------------------------------------------------

    def _build_choose_view(self) -> QWidget:
        view = QWidget()
        layout = QVBoxLayout(view)
        layout.setContentsMargins(0, 0, 0, 0)
        intro = QLabel(
            "Pick the recordings where you talked about bugs or changes. The app finds your "
            "voice in each recording, writes down what you said, and builds one package plus a "
            "prompt for Claude Code or Codex. Your AI agent reads everything, shows you the issues "
            "it would open, and opens them only after you approve. Your recordings are only read, never changed."
        )
        intro.setWordWrap(True)
        intro.setProperty("muted", True)
        layout.addWidget(intro)

        buttons = QHBoxLayout()
        self.add_button = QPushButton("Add recordings…")
        self.add_button.clicked.connect(self.browse_recordings)
        buttons.addWidget(self.add_button)
        self.add_newest_button = QPushButton("Add newest")
        self.add_newest_button.setToolTip("Add the newest recordings from your recordings folder")
        buttons.addWidget(self.add_newest_button)
        self.newest_count = QSpinBox()
        self.newest_count.setRange(1, 20)
        self.newest_count.setValue(1)
        self.newest_count.setToolTip("How many of the newest recordings to add from your recordings folder")
        buttons.addWidget(self.newest_count)
        buttons.addStretch(1)
        self.remove_button = QPushButton("Remove")
        buttons.addWidget(self.remove_button)
        layout.addLayout(buttons)
        # 237: what each button did, said beside it.
        bind_action(self.add_newest_button, self._add_newest_action, working="Adding…", done="Added")
        bind_action(self.remove_button, self._remove_action, working="Removing…", done="Removed")
        # Second row so the first still fits the minimum window width (114).
        housekeeping = QHBoxLayout()
        self.include_done_check = QCheckBox("Include ones already done")
        self.include_done_check.setToolTip(
            "Add newest normally leaves out recordings you already turned into a package or chose never to use"
        )
        housekeeping.addWidget(self.include_done_check)
        housekeeping.addStretch(1)
        self.excluded_button = QPushButton("Never-use list…")
        self.excluded_button.setToolTip("Recordings you chose never to use; allow them again here")
        self.excluded_button.clicked.connect(self.manage_excluded)
        housekeeping.addWidget(self.excluded_button)
        layout.addLayout(housekeeping)

        self.table = RecordingTable()
        self.table.files_dropped.connect(self.add_recordings)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_track_menu)
        layout.addWidget(self.table, 1)
        opener = self._video_opener()
        if opener is not None:
            # Double-click plays (125). The right-click menu stays this page's
            # own, so the opener is told not to put one of its own on the table;
            # _show_track_menu adds the play entries to it instead.
            opener.attach(
                self.table, self._targets_at, context_menu=False, sequence=True, label=PLAY_LIST_LABEL
            )
        hint = QLabel(
            "Drag recordings here, or use Add. Voice track is found automatically. Right-click a "
            "recording to force its track, remove it, or never use it again. "
            "Double-click a recording to play it."
        )
        hint.setProperty("muted", True)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        continue_row = QHBoxLayout()
        self.continue_label = QLabel()
        self.continue_label.setWordWrap(True)
        self.continue_label.setProperty("accent", True)
        continue_row.addWidget(self.continue_label, 1)
        self.start_fresh_button = QPushButton("Start a new package instead")
        self.start_fresh_button.clicked.connect(self.forget_stopped_run)
        continue_row.addWidget(self.start_fresh_button)
        layout.addLayout(continue_row)

        footer = QHBoxLayout()
        self.projects_label = QLabel()
        self.projects_label.setProperty("muted", True)
        self.projects_label.setWordWrap(True)
        footer.addWidget(self.projects_label, 1)
        self.start_button = QPushButton("Find bug reports")
        self.start_button.setObjectName("bugReportsStart")
        self.start_button.setProperty("primary", True)
        self.start_button.setMinimumHeight(38)
        footer.addWidget(self.start_button)
        layout.addLayout(footer)
        bind_action(self.start_button, self.start, working="Starting…", done="Started")
        return view

    def _build_working_view(self) -> QWidget:
        view = QWidget()
        layout = QVBoxLayout(view)
        layout.setContentsMargins(0, 0, 0, 0)
        # 237: the run on this page, with its percent, time left and a way to open it in Queue / Progress.
        maker = getattr(self.host, "make_job_banner", None)
        self.job_banner = maker(PAGE_NAME) if callable(maker) else None
        if self.job_banner is not None:
            layout.addWidget(self.job_banner)
        self.working_table = QTableWidget(0, 3)
        self.working_table.setHorizontalHeaderLabels(["Recording", "Voice track", "Status"])
        self.working_table.verticalHeader().setVisible(False)
        self.working_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.working_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.working_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.working_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.working_table.customContextMenuRequested.connect(self._show_working_menu)
        opener = self._video_opener()
        if opener is not None:
            # Double-click plays here too (125): this is the list on screen
            # for the whole of a run. Its rows are self.rows, as the choose
            # table's are, and they are not reordered while a run is going.
            opener.attach(
                self.working_table, self._targets_at, context_menu=False, sequence=True, label=PLAY_LIST_LABEL
            )
        make_columns_resizable(
            self.working_table,
            widths={0: 280},
            stretch_last=False,
            stretch=0,
        )
        _fit_to_what_they_show(self.working_table)
        layout.addWidget(self.working_table, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)
        self.activity_label = QLabel("Starting…")
        self.activity_label.setProperty("muted", True)
        self.activity_label.setWordWrap(True)
        layout.addWidget(self.activity_label)
        row = QHBoxLayout()
        self.elapsed_label = QLabel("")
        self.elapsed_label.setProperty("muted", True)
        row.addWidget(self.elapsed_label)
        row.addStretch(1)
        self.full_progress_button = QPushButton("Show full progress")
        self.full_progress_button.setToolTip("Open Queue / Progress: stages, the live log and the latest frame")
        self.full_progress_button.clicked.connect(lambda: self.host.navigate("Queue / Progress"))
        row.addWidget(self.full_progress_button)
        self.skip_button = QPushButton("Skip selected")
        self.skip_button.setToolTip("Skip the selected recordings. The one being worked on stops at once.")
        row.addWidget(self.skip_button)
        self.pause_button = QPushButton("Pause")
        self.pause_button.setToolTip("Pause so your PC is free (for a game, say). Resume carries on where it was.")
        row.addWidget(self.pause_button)
        self.cancel_button = QPushButton("Stop")
        self.cancel_button.setProperty("kind", "danger")
        row.addWidget(self.cancel_button)
        layout.addLayout(row)
        # 237: Skip, Pause and Stop say beside them what they did.
        self.run_controls_feedback = InlineFeedback()
        self.run_controls_feedback.setObjectName("bugReportsRunControlsFeedback")
        row.insertWidget(1, self.run_controls_feedback)
        for button, action, working in ((self.skip_button, self.skip_selected, "Skipping…"),
                                        (self.pause_button, self._pause_action, "Pausing…"),
                                        (self.cancel_button, self._stop_action, "Stopping…")):
            bind_action(button, action, working=working, done="Done", feedback=self.run_controls_feedback)
        return view

    def _build_results_view(self) -> QWidget:
        view = QWidget()
        layout = QVBoxLayout(view)
        layout.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setProperty("card", True)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        self.results_headline = QLabel()
        self.results_headline.setObjectName("bugReportsHeadline")
        self.results_headline.setProperty("sectionTitle", True)
        self.results_headline.setWordWrap(True)
        card_layout.addWidget(self.results_headline)
        self.results_detail = QLabel()
        self.results_detail.setWordWrap(True)
        self.results_detail.setProperty("muted", True)
        self.results_detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        card_layout.addWidget(self.results_detail)
        # 237: the row wraps at a large text size instead of making the page wider than the window.
        actions = FlowLayout()
        self.copy_claude_button = QPushButton("Copy prompt for Claude Code")
        self.copy_claude_button.setProperty("primary", True)
        self.copy_claude_button.setMinimumHeight(38)
        actions.addWidget(self.copy_claude_button)
        self.copy_codex_button = QPushButton("Copy prompt for Codex")
        self.copy_codex_button.setMinimumHeight(38)
        actions.addWidget(self.copy_codex_button)
        self.open_folder_button = QPushButton("Open package folder")
        actions.addWidget(self.open_folder_button)
        self.open_log_button = QPushButton("Open log")
        self.open_log_button.setToolTip("The full processing log for this run (also in History)")
        actions.addWidget(self.open_log_button)
        card_layout.addLayout(actions)
        # 237: "Prompt for Claude Code copied", "Opened" or what went wrong, beside these buttons.
        self.copied_label = InlineFeedback()
        self.copied_label.setObjectName("bugReportsCopied")
        actions.addWidget(self.copied_label)
        for button, action, working, done in (
            (self.copy_claude_button, lambda: self.copy_prompt("Claude Code"), "Copying…", "Copied"),
            (self.copy_codex_button, lambda: self.copy_prompt("Codex"), "Copying…", "Copied"),
            (self.open_folder_button, self.open_package_folder, "Opening…", "Opened"),
            (self.open_log_button, self._open_log_action, "Opening…", "Opened"),
        ):
            bind_action(button, action, working=working, done=done, feedback=self.copied_label)
        # 125: on a row of its own. A fifth button in the row above would not
        # fit the smallest window, and this page's width is the width of every
        # page in the stack.
        watch_row = QHBoxLayout()
        self.watch_button = QPushButton("Watch a recording…")
        self.watch_button.setToolTip(
            "Play one of this run's recordings and read what was written down for it, line by line"
        )
        self.watch_button.clicked.connect(self.watch_a_recording)
        watch_row.addWidget(self.watch_button)
        watch_row.addStretch(1)
        card_layout.addLayout(watch_row)
        # 135: the waveforms of this run's recordings, built in the background once the run is done.
        self.waveforms_label = QLabel("")
        self.waveforms_label.setObjectName("bugReportsWaveforms")
        self.waveforms_label.setProperty("muted", True)
        self.waveforms_label.setWordWrap(True)
        self.waveforms_label.hide()
        card_layout.addWidget(self.waveforms_label)
        self._waveforms_listener: _WaveformsListener | None = None
        layout.addWidget(card)
        next_steps = QLabel(
            "Next: paste the prompt into Claude Code or Codex. It reads your narration, shows you "
            "the issues it proposes for each of your projects, and opens them only after you say yes."
        )
        next_steps.setWordWrap(True)
        next_steps.setProperty("muted", True)
        layout.addWidget(next_steps)
        layout.addStretch(1)
        again = QHBoxLayout()
        again.addStretch(1)
        self.fix_button = QPushButton("Fix and continue…")
        self.fix_button.setToolTip(
            "Go back to the list for this package, choose a voice track for a recording that could not be used, "
            "and continue. Everything already finished is reused."
        )
        self.fix_button.clicked.connect(self.fix_and_continue)
        again.addWidget(self.fix_button)
        self.again_button = QPushButton("Start over with other recordings")
        self.again_button.clicked.connect(self.start_over)
        again.addWidget(self.again_button)
        layout.addLayout(again)
        return view

    # Choosing recordings ---------------------------------------------------

    def _recordings_folder(self) -> Path | None:
        raw = str(self.host.app_settings.get("review_source_folders") or "").strip()
        first = raw.splitlines()[0].split(";")[0].strip() if raw else ""
        candidate = first or str(self.host.app_settings.get("default_input_folder") or "")
        return Path(candidate) if candidate else None

    def browse_recordings(self) -> None:
        folder = self._recordings_folder()
        files, _selected = QFileDialog.getOpenFileNames(
            self,
            "Choose recordings",
            str(folder) if folder and folder.exists() else "",
            "Video recordings (*.mkv *.mp4 *.mov *.avi *.m4v *.webm)",
        )
        self.add_recordings([Path(item) for item in files])

    def add_newest_recordings(self) -> None:
        folder = self._recordings_folder()
        if not folder or not folder.is_dir():
            QMessageBox.information(
                self,
                "Recordings folder not found",
                "Set your recordings folder in Settings, or use Add recordings.",
            )
            return
        leave_out: set[str] = set()
        if not self.include_done_check.isChecked():
            leave_out = self._excluded_keys() | set(self._processed().keys())
        found = newest_recordings(folder, self.newest_count.value(), leave_out=leave_out)
        if not found and leave_out:
            self.status_sentence.setText(
                "No new recordings: the newest ones are already done or on your never-use list. "
                "Tick Include ones already done to add them anyway."
            )
            return
        self.add_recordings(found)

    def _add_newest_action(self) -> Outcome:
        before = len(self.rows)
        self.add_newest_recordings()
        added = len(self.rows) - before
        if added:
            return Outcome.done(f"Added {added} recording{'s' if added != 1 else ''}")
        if self.status_sentence.text().startswith("No new recordings"):
            return Outcome.failed("No new recordings were added.", "Tick Include ones already done to add them anyway.")
        return Outcome.quiet()

    def _remove_action(self) -> Outcome:
        before = len(self.rows)
        if not self.table.selectedIndexes():
            return Outcome.failed("Nothing is selected.", "Select the recordings to remove, then press Remove.")
        self.remove_selected()
        removed = before - len(self.rows)
        return Outcome.done(f"Removed {removed} recording{'s' if removed != 1 else ''}")

    def _lists_unreadable(self) -> bool:
        """275: the never-use and already-done lists live in the library; while it cannot be opened they are
        not known this session, unless they were never moved out of the settings (224, Wave B2a, note 12)."""

        return (getattr(self.host, "records", True) is None and bool(getattr(self.host, "library_problem", ""))
                and not held_in_settings(getattr(self.host, "app_settings", None)))

    def _add_anyway(self) -> bool:
        answer = warn(
            self,
            "Your lists could not be read",
            "Your library could not be opened, so your never-use and already-done lists are not shown this "
            "session. Some of these recordings may already be done, or on your never-use list.\n\nAdd them anyway?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def add_recordings(self, paths: list[Path], *, _asked: bool = False) -> None:
        # 275: no recording is offered as new while the lists cannot be read, unless the operator says so.
        if not _asked and paths and self._lists_unreadable() and not self._add_anyway():
            return
        excluded = self._excluded_keys()
        left_out = 0
        known = {row.path.resolve() for row in self.rows}
        for path in paths:
            path = Path(path)
            if path.is_dir():
                children = sorted(
                    child for child in path.iterdir() if child.is_file() and child.suffix.lower() in VIDEO_EXTENSIONS
                )
                self.add_recordings(children, _asked=True)
                continue
            if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            resolved = path.resolve()
            if resolved in known:
                continue
            if _path_key(resolved) in excluded:
                left_out += 1
                continue
            known.add(resolved)
            self.rows.append(self._row_with_answer(RecordingRow(path=resolved)))
        self._render_choose_table()
        if left_out:
            noun = "recordings are" if left_out != 1 else "recording is"
            self.status_sentence.setText(
                f"{left_out} {noun} on your never-use list, so left out. "
                "Use Never-use list… to allow them again."
            )

    def remove_selected(self) -> None:
        selected = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for index in selected:
            if 0 <= index < len(self.rows):
                del self.rows[index]
        self._render_choose_table()

    def _show_track_menu(self, point) -> None:
        index = self.table.indexAt(point).row()
        if index < 0 or index >= len(self.rows):
            return
        menu = self._build_track_menu(index)
        menu.exec(self.table.viewport().mapToGlobal(point))
        # It belongs to the page, so without this every right-click would
        # leave one more menu behind for as long as the app runs.
        menu.deleteLater()

    def _build_track_menu(self, index: int) -> QMenu:
        """The choose table's right-click menu for one row; never shows it."""

        menu = QMenu(self)
        self._add_play_actions(menu, index)
        auto = menu.addAction("Find my voice automatically")
        auto.triggered.connect(lambda: self._set_override(index, None))
        for track in range(1, 9):
            action = menu.addAction(f"Always use Track {track}")
            action.triggered.connect(lambda checked=False, value=track: self._set_override(index, value))
        menu.addSeparator()
        remove = menu.addAction("Remove from this list")
        remove.triggered.connect(self.remove_selected)
        never = menu.addAction("Never use this recording")
        never.setToolTip("Leave it out now and in future runs; undo with Never-use list…")
        never.triggered.connect(self.never_use_selected)
        return menu

    # Playing a recording (125) --------------------------------------------

    def _video_opener(self) -> Any:
        """The Workbench's one video opener, or None for a host without one."""

        return getattr(self.host, "video_opener", None)

    def _package_root(self) -> Path | None:
        """The package that holds what was written down for these recordings."""

        if self.summary is not None and self.summary.package_root is not None:
            return self.summary.package_root
        # A stopped run waiting to be continued already holds the transcripts
        # of the recordings it finished. Named, never looked for: this is
        # asked once for every row when a play list is built, on the GUI
        # thread. A run stopped before it wrote a package leaves nothing
        # there, and the player, which looks on a thread of its own, then
        # simply finds no transcript.
        if self.continue_folder is not None:
            return self.continue_folder / "codex-evidence-package"
        return None

    def _play_target(self, row: RecordingRow, package_root: Path | None) -> PlayTarget:
        return PlayTarget(
            path=row.path,
            package_root=package_root,
            label=row.path.name,
            # The track the operator forced comes first: it is what they
            # believe is their voice. What a run found is the next best thing.
            voice_track=row.track_override or row.voice_track,
            # Said only for a track the run found, not one the operator forced (196).
            voice_source="" if row.track_override else row.voice_source,
        )

    def _targets_at(self, index: QModelIndex) -> list[PlayTarget]:
        """Resolver for the choose and working tables: their rows mirror ``self.rows`` one for one."""

        position = index.row()
        # A click can arrive after rows were dropped, so the index is checked.
        if not 0 <= position < len(self.rows):
            return []
        return [self._play_target(self.rows[position], self._package_root())]

    def _play_sequence(self) -> PlaySequence:
        """Every recording on the page, in row order, frozen now.

        A snapshot, never a view of ``self.rows``: marking a recording
        never-use in the player removes its row here, and the player still
        has to find what came after it. It finds its place by path, not by
        row number.
        """

        package_root = self._package_root()
        return PlaySequence(
            tuple(self._play_target(row, package_root) for row in self.rows), label=PLAY_LIST_LABEL
        )

    def _add_play_actions(self, menu: QMenu, index: int) -> None:
        """Put the opener's play entries at the top of one of this page's menus."""

        opener = self._video_opener()
        if opener is None or not 0 <= index < len(self.rows):
            return
        # The list is taken now, as the menu is built, so what it holds is what
        # the operator was looking at when they chose Play.
        sequence = self._play_sequence()
        opener.add_menu_actions(menu, [sequence.targets[index]], sequence=sequence)
        if not menu.isEmpty():
            menu.addSeparator()

    def watch_a_recording(self) -> None:
        """The run's recordings, each pointed at the package the run built, so
        the built-in player can show what was written down for it."""

        opener = self._video_opener()
        if opener is None or not self.rows:
            return
        menu = self._build_watch_menu(opener)
        menu.exec(self.watch_button.mapToGlobal(self.watch_button.rect().bottomLeft()))
        menu.deleteLater()

    def _build_watch_menu(self, opener: Any) -> QMenu:
        sequence = self._play_sequence()
        return opener.build_menu(list(sequence.targets), self, sequence=sequence)

    # Never-use list and already-done recordings (114) ---------------------

    # The lists themselves live in recording_lists (125) so the built-in
    # player reads and writes them by the same rules. Where they are kept (the
    # library since 244, the settings while they could not be moved in) is
    # asked of the host on every call: the host replaces its settings
    # dictionary when settings are imported, so it is never cached here.

    def _lists(self) -> Any:
        return lists_of(self.host)

    def _excluded(self) -> list[str]:
        return excluded_paths(self._lists())

    def _excluded_keys(self) -> set[str]:
        return excluded_keys(self._lists())

    def _processed(self) -> dict[str, str]:
        return processed_dates(self._lists())

    def _save_lists(self, lists: Any) -> bool:
        """Save the lists where they are kept: the library saved each change as it was made; the
        settings are saved now."""

        return True if in_library(lists) else self._save_settings()

    def _save_settings(self) -> bool:
        """True only when the settings really reached disk.

        Callers on this page carry on either way, as they always have. The
        built-in player must not move on to the next recording after a
        never-use that was never saved (125), so a host that cannot save at
        all counts as a failed save too.
        """

        saver = getattr(self.host, "save_app_settings", None)
        if not callable(saver):
            return False
        try:
            saver()
        except OSError:
            return False
        return True

    def never_use_selected(self) -> None:
        selected = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        if not selected:
            return
        lists = self._lists()
        # Highest index first, so each del leaves the indexes still to come valid.
        for index in selected:
            if 0 <= index < len(self.rows):
                try:
                    add_excluded(lists, str(self.rows[index].path), by=PAGE_NAME)
                except OSError:
                    # The library could not keep it: nothing changed, so the row stays.
                    continue
                del self.rows[index]
        self._save_lists(lists)
        self._render_choose_table()

    def manage_excluded(self) -> None:
        entries = excluded_entries(self._lists())
        excluded = [entry["path"] for entry in entries]
        dialog = QDialog(self)
        dialog.setWindowTitle("Never-use list")
        layout = QVBoxLayout(dialog)
        label = QLabel(
            "These recordings are left out of Find my bug reports. Select any you want to use again "
            "and press Allow again. The recordings themselves are never changed."
            if excluded
            else "Your never-use list is empty. Right-click a recording and choose Never use this recording to add it."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        listing = QListWidget()
        listing.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        for entry in entries:
            path = entry["path"]
            item = QListWidgetItem(Path(path).name)
            item.setToolTip(path)
            item.setData(Qt.ItemDataRole.UserRole, path)
            # 244: the library's own entry, so Allow again takes off exactly this one.
            item.setData(Qt.ItemDataRole.UserRole + 1, entry["mark_id"])
            listing.addItem(item)
        opener = self._video_opener()
        if opener is not None:
            # 125: watch a recording before deciding to allow it again. Each
            # item already carries its path in the role this resolver reads.
            # Not a play list: nothing here is "next" after the one watched.
            opener.attach(listing, path_role_resolver())
            # Blocks this Workbench window only. Left as it was, the dialog
            # would block every window of the app, and the built-in player
            # would open but take no clicks or keys until this was closed.
            dialog.setWindowModality(Qt.WindowModality.WindowModal)
        layout.addWidget(listing, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        allow = buttons.addButton("Allow again", QDialogButtonBox.ButtonRole.ActionRole)
        allow.setEnabled(bool(excluded))

        def allow_selected() -> None:
            chosen = listing.selectedItems()
            lists = self._lists()
            for item in chosen:
                try:
                    remove_excluded(lists, item.data(Qt.ItemDataRole.UserRole), by=PAGE_NAME,
                                    mark_id=item.data(Qt.ItemDataRole.UserRole + 1))
                except OSError:
                    pass
            self._save_lists(lists)
            for item in chosen:
                listing.takeItem(listing.row(item))

        allow.clicked.connect(allow_selected)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.resize(560, 360)
        dialog.exec()
        # Allow again only takes a recording off the list. Putting it back in
        # the table is the operator's choice, so nothing is re-added here.
        self.recording_lists_changed()

    def recording_lists_changed(self) -> None:
        """The never-use list changed, here or in the built-in player (125).

        Never-use is about FUTURE runs. While a run is going, ``self.rows`` is
        what the working table, the Queue / Progress items and the skip
        selection all index into, so it is left exactly as it is and only the
        "Never-use list (n)…" caption is brought up to date. Skip this
        recording is the way to affect the run that is going now.

        When idle, rows are dropped BY PATH KEY, never by index. The player has
        its own window, and this list is rebuilt, reordered and deleted from in
        several places, so an index remembered from earlier means nothing.
        """

        if self.running:
            self._refresh_choose_state()
            return
        gone = self._excluded_keys()
        self.rows = [row for row in self.rows if _path_key(row.path) not in gone]
        self._render_choose_table()

    def _record_outcomes(self, result: RunnerResult, rows: list[tuple[Path, str, str]], *, cancelled: bool) -> None:
        """243: each recording's outcome in this run, kept in the library as the rows show it. A
        recording the run never got to is Cancelled after Stop, and "not reported" otherwise."""

        records = getattr(self.host, "records", None)
        run_id = str(getattr(result, "run_id", "") or "")
        if not isinstance(records, Records) or not run_id:
            return
        outcomes = []
        for path, state, note in rows:
            if state == ROW_DONE:
                outcome, reason = OUTCOME_COMPLETED, ""
            elif state == ROW_NO_NARRATION:
                outcome, reason = OUTCOME_NO_NARRATION, ""
            elif state == ROW_FAILED:
                outcome, reason = OUTCOME_FAILED, str(note or "")
            elif state in {ROW_SKIPPED, ROW_SKIPPING}:
                outcome, reason = OUTCOME_SKIPPED, "Skipped by you."
            elif cancelled:
                outcome, reason = OUTCOME_CANCELLED, "The run was stopped before it got to this one."
            else:
                outcome, reason = OUTCOME_NOT_REPORTED, ""
            outcomes.append({"item": str(Path(path).resolve()), "outcome": outcome, "reason": reason})
        try:
            records.record_outcomes(run_id, outcomes, reported_by="Find my bug reports")
        except (OSError, sqlite3.Error, ValueError):
            pass

    def _mark_processed(self, run_id: str = "") -> None:
        stamp = datetime.now().strftime("%Y-%m-%d")
        # 244: "No narration found" is kept as its own outcome, with the run it came from.
        rows = [(str(row.path), "no_narration" if row.state == ROW_NO_NARRATION else "done")
                for row in self.rows if row.state in {ROW_DONE, ROW_NO_NARRATION}]
        lists = self._lists()
        try:
            mark_processed(lists, rows, day=stamp, run_id=run_id, by=PAGE_NAME)
        except OSError:
            pass
        self._save_lists(lists)

    def _row_with_answer(self, row: RecordingRow) -> RecordingRow:
        """264: your answer for this recording, from any screen, and the line when it differs from what the app heard."""

        answer = speech_facts.narration_answer(row.path, explicit=row.track_override)
        if answer.decided_by == speech_facts.DECIDED_CONFIRMED:
            row.track_override = answer.track
        row.choice_line = answer.you_chose
        return row

    def _set_override(self, index: int, track: int | None) -> None:
        if 0 <= index < len(self.rows):
            row = self.rows[index]
            row.track_override = track
            # 264 (Q4): choosing a track is your answer for this recording, on every screen; Automatic clears it.
            if track:
                speech_facts.confirm_track(row.path, int(track), by=speech_facts.ANSWERED_ON_BUGS)
            else:
                speech_facts.clear_track(row.path, by=speech_facts.ANSWERED_ON_BUGS)
            self._row_with_answer(row)
            self._render_choose_table()

    def _render_choose_table(self) -> None:
        processed = self._processed()
        self.table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            try:
                size = format_size(row.path.stat().st_size)
            except OSError:
                size = "missing"
            track = f"Track {row.track_override} (you chose)" if row.track_override else "Automatic"
            done_on = processed.get(_path_key(row.path))
            if row.state == ROW_FAILED:
                ready = "Could not be used last time"
            elif done_on:
                ready = f"Done on {done_on}"
            else:
                ready = "Ready"
            if row.choice_line:
                ready = f"{ready}. {row.choice_line}"
            for column, text in enumerate((row.path.name, size, track, ready)):
                item = QTableWidgetItem(text)
                if column == 0:
                    item.setToolTip(str(row.path))
                self.table.setItem(index, column, item)
        _fit_to_what_they_show(self.table)
        self._refresh_choose_state()

    def _projects_text(self) -> str:
        path_value = str(self.host.app_settings.get("evidence_repo_map_path") or "").strip()
        if not path_value:
            return "My projects: not set up yet, so your AI agent will ask which repository each issue belongs to."
        try:
            # Windows editors often save JSON with a byte-order mark (105).
            payload = json.loads(Path(path_value).read_text(encoding="utf-8-sig"))
            repos = payload.get("repos") or {}
            count = len(repos)
        except (OSError, ValueError, AttributeError):
            return "My projects: the project list could not be read; your AI agent will ask which repository to use."
        return f"My projects: {count} project{'s' if count != 1 else ''} will be listed in the prompt."

    def _refresh_choose_state(self) -> None:
        count = len(self.rows)
        self.start_button.setEnabled(count > 0 and not self.running)
        self.remove_button.setEnabled(count > 0)
        continuing = self.continue_folder is not None
        self.start_button.setText("Continue" if continuing else "Find bug reports")
        self.continue_label.setVisible(continuing)
        self.start_fresh_button.setVisible(continuing)
        if continuing:
            self.continue_label.setText(
                "Continuing the stopped package. Finished transcripts, voice tracks, screenshots and clips "
                "are reused, so only the rest is done."
            )
        excluded_count = len(self._excluded())
        self.excluded_button.setText(f"Never-use list ({excluded_count})…" if excluded_count else "Never-use list…")
        self.projects_label.setText(self._projects_text())
        if self.stack.currentIndex() == 0:
            if count:
                total = 0
                for row in self.rows:
                    try:
                        total += row.path.stat().st_size
                    except OSError:
                        pass
                self.status_sentence.setText(
                    f"{count} recording{'s' if count != 1 else ''} ready ({format_size(total)}). Press Find bug reports when you are ready."
                )
            else:
                self.status_sentence.setText("Choose the recordings you narrated.")

    # Running -------------------------------------------------------------------

    def _new_run_folder(self) -> Path:
        root = Path(str(self.host.app_settings.get("output_folder") or default_output_folder()))
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        folder = root / "bug-reports" / stamp
        suffix = 1
        while folder.exists():
            suffix += 1
            folder = root / "bug-reports" / f"{stamp}_{suffix}"
        return folder

    def build_command(self) -> CommandSpec:
        resources = self.host.resources
        if not resources.script_path:
            raise ValueError("The Video Mangler.ps1 backend could not be located.")
        assert self.run_folder is not None
        settings = build_bug_report_settings(
            self.host.app_settings,
            self.rows,
            self.run_folder,
            repo_root=str(resources.app_root),
        )
        settings["repo_root"] = str(resources.app_root)
        settings["script_path"] = str(resources.script_path)
        settings["python_exe"] = resources.python_exe
        settings["ffmpeg_path"] = resources.ffmpeg_exe
        settings["ffprobe_path"] = resources.ffprobe_exe
        settings["ytdlp_path"] = resources.ytdlp_exe
        # 114/115: skip/pause requests reach the backend through this file.
        settings["run_control_path"] = str(self.run_folder / "run-control.json")
        self.run_settings = settings
        return build_workflow_command(
            settings,
            workflow=WORKFLOW_CODEX_EVIDENCE,
            powershell_exe=resources.powershell_exe or "powershell",
        )

    def _confirm_long_recordings(self) -> bool:
        """Offer to skip very long recordings before any work starts (114)."""

        ffprobe = str(getattr(self.host.resources, "ffprobe_exe", "") or "")
        long_rows: list[tuple[RecordingRow, float]] = []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for row in self.rows:
                seconds = probe_duration_seconds(ffprobe, row.path)
                if seconds is not None and seconds >= LONG_RECORDING_SECONDS:
                    long_rows.append((row, seconds))
        finally:
            QApplication.restoreOverrideCursor()
        if not long_rows:
            return True
        listing = "\n".join(f"• {row.path.name} ({format_duration(seconds)})" for row, seconds in long_rows)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Very long recordings")
        box.setText(
            f"{len(long_rows)} recording{'s are' if len(long_rows) != 1 else ' is'} over "
            f"{LONG_RECORDING_SECONDS // 3600} hours long. Sessions left running are often long and mostly "
            f"idle, and each can take an hour or more to process.\n\n{listing}"
        )
        skip = box.addButton("Leave them out", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Include them", QMessageBox.ButtonRole.YesRole)
        cancel = box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(skip)
        box.exec()
        clicked = box.clickedButton()
        if clicked is cancel:
            return False
        if clicked is skip:
            long_paths = {row.path for row, _seconds in long_rows}
            self.rows = [row for row in self.rows if row.path not in long_paths]
            self._render_choose_table()
            if not self.rows:
                return False
        return True

    def start(self) -> Outcome:
        # 237: a refusal is said in a dialog, as before, so the line beside the button stays quiet;
        # once it starts, the page itself changes to the running screen.
        if not self.rows or self.running:
            return Outcome.quiet()
        if self.host.runner_thread is not None:
            self.host.report_run_in_progress()
            return Outcome.quiet()
        # 211: the one output-folder rule, before anything starts, as every feature does.
        folder_problem = temporary_folder_problem(str(self.host.app_settings.get("output_folder") or default_output_folder()))
        if folder_problem:
            warn(self, "Cannot start", folder_problem)
            return Outcome.quiet()
        if not self._confirm_long_recordings():
            return Outcome.quiet()
        if self.continue_folder is not None and self.continue_folder.is_dir():
            self.run_folder = self.continue_folder
        else:
            self.run_folder = self._new_run_folder()
        try:
            command = self.build_command()
        except (OSError, ValueError) as exc:
            warn(self, "Cannot start", str(exc))
            return Outcome.quiet()
        queue_items = [str(row.path.resolve()) for row in self.rows]
        self._clear_waveforms_line()
        self.stdout_lines = []
        self.whisper_notice.clear()
        self.whisper_notice.setVisible(False)
        self.current_source = ""
        self.summary = None
        count = len(self.rows)
        if not self.host.start_external_run(
            command,
            title="Find my bug reports",
            settings=self.run_settings,
            queue_items=queue_items,
            listener=self,
            kind="bug_reports",
            **({"origin": PAGE_NAME,
                "banner_title": f"Finding bug reports in {count} recording{'s' if count != 1 else ''}"}
               if hasattr(self.host, "make_job_banner") else {}),
        ):
            return Outcome.quiet()
        self.running = True
        self.continue_folder = None
        self._remember_stopped_run(None)
        for row in self.rows:
            row.state = ROW_WAITING
            row.voice_track = row.track_override
            row.voice_source = ""
            row.note = ""
        self.pause_button.setText("Pause")
        self.pause_button.setEnabled(True)
        self.skip_button.setEnabled(True)
        self._render_working_table()
        self.progress.setRange(0, len(self.rows) * 2)
        self.progress.setValue(0)
        self.activity_label.setText("Starting…")
        self.cancel_button.setEnabled(True)
        self.stack.setCurrentIndex(1)
        self.status_sentence.setText(f"Working on {len(self.rows)} recording{'s' if len(self.rows) != 1 else ''}…")
        self.started = time.monotonic()
        self.elapsed_timer.start()
        self._refresh_choose_state()
        return Outcome.quiet()

    def cancel(self) -> None:
        if self.running:
            self.cancel_button.setEnabled(False)
            self.pause_button.setEnabled(False)
            self.skip_button.setEnabled(False)
            self.activity_label.setText("Stopping…")
            self.host.cancel_job()

    # Skip and pause while running (114, 115) ---------------------------------

    def _selected_working_rows(self) -> list[RecordingRow]:
        indexes = sorted({index.row() for index in self.working_table.selectedIndexes()})
        return [self.rows[index] for index in indexes if 0 <= index < len(self.rows)]

    def skip_selected(self) -> Outcome:
        rows = [row for row in self._selected_working_rows() if row.state not in FINISHED_ROW_STATES]
        if not rows:
            # 237: said beside Skip selected, not in a pop-up.
            return Outcome.failed("Nothing to skip.",
                                  "Select one or more recordings that are not finished yet, then press Skip selected.")
        self.host.skip_run_sources([str(row.path) for row in rows])
        return Outcome.done(f"Skipping {len(rows)} recording{'s' if len(rows) != 1 else ''}")

    def toggle_pause(self) -> None:
        self.host.toggle_run_pause()

    def _pause_action(self) -> Outcome:
        self.toggle_pause()
        control = getattr(self.host, "run_control", None)
        return Outcome.done("Paused" if control is not None and control.paused else "Resumed")

    def _stop_action(self) -> Outcome:
        if not self.running:
            return Outcome.quiet()
        self.cancel()
        return Outcome.done("Stopping; nothing is sent anywhere")

    def _show_working_menu(self, point) -> None:
        index = self.working_table.indexAt(point).row()
        if index < 0 or index >= len(self.rows):
            return
        if not self.working_table.item(index, 0) or not self.working_table.item(index, 0).isSelected():
            self.working_table.selectRow(index)
        menu = self._build_working_menu(index)
        # No run and nothing to play with: no menu at all, as before.
        if not menu.isEmpty():
            menu.exec(self.working_table.viewport().mapToGlobal(point))
        menu.deleteLater()

    def _build_working_menu(self, index: int) -> QMenu:
        """The working table's right-click menu for one row; never shows it."""

        menu = QMenu(self)
        # Playing is offered whether or not a run is going (125).
        self._add_play_actions(menu, index)
        # Skipping only means something while the run is going: skip_selected
        # talks to the live run, and there is none otherwise.
        if self.running and 0 <= index < len(self.rows):
            action = menu.addAction("Skip this recording")
            action.setEnabled(self.rows[index].state not in FINISHED_ROW_STATES)
            action.triggered.connect(self.skip_selected)
        return menu

    def on_run_control_changed(self) -> None:
        control = getattr(self.host, "run_control", None)
        if control is None:
            return
        for row in self.rows:
            if control.is_skipped(row.path) and row.state not in FINISHED_ROW_STATES:
                row.state = ROW_SKIPPING
        self.pause_button.setText("Resume" if control.paused else "Pause")
        if control.paused:
            self.status_sentence.setText("Paused. Your PC is free; press Resume to carry on where it was.")
        else:
            self.status_sentence.setText(f"Working on {len(self.rows)} recording{'s' if len(self.rows) != 1 else ''}…")
        self._render_working_table()

    # Continue a stopped run (115) -------------------------------------------------

    def _remember_stopped_run(self, folder: Path | None) -> None:
        # 244: kept in the library (the settings while the lists could not be moved in), with the run it
        # came from; the record itself is the same as before.
        record = None if folder is None else {
            "folder": str(folder),
            "recordings": [str(row.path) for row in self.rows],
            "tracks": {str(row.path): row.track_override for row in self.rows if row.track_override},
        }
        lists = self._lists()
        try:
            set_stopped_run(lists, record, run_id=self._last_run_id if record is not None else "")
        except OSError:
            pass
        self._save_lists(lists)

    def _restore_stopped_run(self) -> None:
        lists = self._lists()
        saved = stopped_run(lists)
        if not isinstance(saved, dict):
            return
        folder = Path(str(saved.get("folder") or ""))
        if not str(saved.get("folder") or "") or not folder.is_dir():
            try:
                set_stopped_run(lists, None)
            except OSError:
                pass
            return
        tracks = saved.get("tracks") or {}
        # The record is only rewritten when a run stops, so it can still name
        # a recording that was marked never-use afterwards (125).
        excluded = self._excluded_keys()
        rows = []
        for value in saved.get("recordings") or []:
            path = Path(str(value))
            if _path_key(path) not in excluded and path.is_file():
                override = tracks.get(str(value)) if isinstance(tracks, dict) else None
                rows.append(self._row_with_answer(RecordingRow(path=path, track_override=int(override) if override else None)))
        if rows:
            self.rows = rows
            self.continue_folder = folder
            self._render_choose_table()

    def forget_stopped_run(self) -> None:
        self.continue_folder = None
        self._remember_stopped_run(None)
        self._refresh_choose_state()

    def _enter_continue_mode(self, *, keep_failed_note: bool) -> None:
        skipped = [row for row in self.rows if row.state in {ROW_SKIPPED, ROW_SKIPPING}]
        self.rows = [row for row in self.rows if row not in skipped]
        for row in self.rows:
            if not (keep_failed_note and row.state == ROW_FAILED):
                row.state = ROW_WAITING
        self.continue_folder = self.run_folder
        self._remember_stopped_run(self.run_folder)
        self._render_choose_table()
        self.stack.setCurrentIndex(0)
        self._refresh_choose_state()

    def fix_and_continue(self) -> None:
        if self.run_folder is None:
            return
        self._enter_continue_mode(keep_failed_note=True)
        self.status_sentence.setText(
            "Right-click a recording marked Could not be used, choose its microphone track, then press Continue."
        )

    def _row_for_name(self, name: str) -> RecordingRow | None:
        for row in self.rows:
            if row.path.name == name:
                return row
        return None

    def on_log_line(self, stream: str, line: str) -> None:
        self.stdout_lines.append(line)
        if "[GPU->CPU]" in line or MODEL_CHECKSUM_TEXT in line.lower():
            self._refresh_whisper_notice()
        progress = parse_progress_line(line)
        if progress is not None:
            name = str(progress.get("source_name") or "")
            if name:
                self.current_source = name
            activity = str(progress.get("activity") or "")
            phase = str(progress.get("phase") or "")
            if activity:
                self.activity_label.setText(activity)
            row = self._row_for_name(self.current_source)
            if row and phase == "Transcription":
                if activity.startswith("Transcription operator_skipped"):
                    row.state = ROW_SKIPPED
                elif activity.startswith(("Transcription completed", "Transcription skipped")):
                    row.state = ROW_DONE
                elif activity.startswith("Transcription no_narration"):
                    row.state = ROW_NO_NARRATION
                elif activity.startswith(("Transcription failed", "Transcription quality_blocked")):
                    row.state = ROW_FAILED
                elif row.state == ROW_WAITING and "Preparing" not in activity and "Paused" not in activity and "Resumed" not in activity:
                    row.state = ROW_TRANSCRIBING
            if phase and phase != "Transcription":
                for item in self.rows:
                    if item.state in {ROW_TRANSCRIBING}:
                        item.state = ROW_DONE
                    elif item.state == ROW_SKIPPING:
                        item.state = ROW_SKIPPED
                self.status_sentence.setText("Building your package…")
            self._render_working_table()
            return
        stripped = line.strip()
        row = self._row_for_name(self.current_source)
        if stripped.startswith("Listening to every audio track"):
            name = stripped.split(":", 1)[1].strip() if ":" in stripped else ""
            row = self._row_for_name(name) or row
            if row:
                self.current_source = row.path.name
                row.state = ROW_LISTENING
                self.status_sentence.setText(f"Finding your voice in {row.path.name}…")
        elif stripped.startswith("Voice found on Track") and row:
            match = re.search(r"Track (\d+)(?: \(([^)]+)\))?", stripped)
            row.voice_track = int(match.group(1)) if match else None
            row.voice_source = (match.group(2) or "") if match else ""
            row.state = ROW_TRANSCRIBING
            self.status_sentence.setText(f"Writing down what you said in {row.path.name}…")
        elif stripped.startswith("No narration found in this recording") and row:
            row.state = ROW_NO_NARRATION
            row.note = "No narration found"
        elif stripped.startswith("FAIL Codex evidence transcript") and row:
            row.state = ROW_FAILED
        elif stripped.startswith("SKIPPED by you:"):
            name = stripped.split(":", 1)[1].strip()
            skipped_row = self._row_for_name(name) or row
            if skipped_row:
                skipped_row.state = ROW_SKIPPED
        self._render_working_table()

    def _refresh_whisper_notice(self) -> None:
        notice = whisper_notice(self.stdout_lines, str(self.host.app_settings.get("whisper_model") or "medium"))
        self.whisper_notice.setText(notice)
        self.whisper_notice.setVisible(bool(notice))

    def _render_working_table(self) -> None:
        self.working_table.setRowCount(len(self.rows))
        finished = 0
        for index, row in enumerate(self.rows):
            track = voice_track_text(row) if row.voice_track else ("—" if row.state in {ROW_NO_NARRATION, ROW_SKIPPED} else "…")
            for column, text in enumerate((row.path.name, track, row.state)):
                cell = QTableWidgetItem(text)
                if column == 2:
                    cell.setForeground(status_color(ROW_STATUS_KIND.get(row.state, "waiting")))
                self.working_table.setItem(index, column, cell)
            finished += {ROW_WAITING: 0, ROW_LISTENING: 0, ROW_TRANSCRIBING: 1, ROW_SKIPPING: 1}.get(row.state, 2)
        _fit_to_what_they_show(self.working_table)
        if self.progress.maximum() > 0:
            self.progress.setValue(min(self.progress.maximum(), finished))

    def _refresh_elapsed(self) -> None:
        seconds = int(time.monotonic() - self.started)
        self.elapsed_label.setText(f"Running for {seconds // 60} min {seconds % 60:02d} s")

    def on_finished(self, result: RunnerResult) -> None:
        self.elapsed_timer.stop()
        self.running = False
        # 244: the run a stopped run or a "done" mark came from.
        self._last_run_id = str(getattr(result, "run_id", "") or "")
        # 243: each recording's outcome as the rows show it now, before the rows are changed for the
        # never-use list or for Continue.
        finished_rows = [(row.path, row.state, row.note) for row in self.rows]
        # 125: a recording marked never-use in the built-in player while this
        # run was going was left in the rows, because everything indexed into
        # them. Nothing does now, so it goes here, before the rows become the
        # Continue list and the saved stopped-run record. Otherwise Continue
        # would process a recording the operator said never to use.
        self.recording_lists_changed()
        self.cancel_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.skip_button.setEnabled(False)
        if result.status == "cancelled":
            self._record_outcomes(result, finished_rows, cancelled=True)
            if self.run_folder is not None and self.run_folder.is_dir():
                self._enter_continue_mode(keep_failed_note=True)
                self.status_sentence.setText(
                    "Stopped. Nothing was sent anywhere. Press Continue to pick up where it stopped, "
                    "or start a new package instead."
                )
            else:
                self.status_sentence.setText("Stopped. Nothing was sent anywhere; you can start again.")
                self.stack.setCurrentIndex(0)
                self._refresh_choose_state()
            return
        for row in self.rows:
            if row.state == ROW_SKIPPING:
                row.state = ROW_SKIPPED
        self._record_outcomes(result, finished_rows, cancelled=False)
        package_root = (self.run_folder or Path(".")) / "codex-evidence-package"
        try:
            summary = summarize_package(package_root, result.status, self.stdout_lines + list(result.stdout_lines or []))
        except (OSError, ValueError) as exc:
            summary = RunSummary(status="failed", package_root=None, error=str(exc))
        if summary.status == "failed" and result.error and not summary.error:
            summary.error = result.error
        self.summary = summary
        if summary.status in {"complete", "complete_with_problems"}:
            # 114: "Add newest" leaves these out next time.
            self._mark_processed(str(getattr(result, "run_id", "") or ""))
        self.prompts = {}
        if summary.package_root is not None and summary.status != "nothing_usable":
            try:
                package = load_evidence_package(summary.package_root)
                self.prompts = {
                    tool: build_session_prompt(package, tool) for tool in ("Claude Code", "Codex")
                }
                self.host.app_settings["last_evidence_package"] = str(summary.package_root)
            except Exception as exc:  # noqa: BLE001 - shown to the operator
                summary.error = f"The package was written but could not be opened: {exc}"
        self._show_results()
        self._build_waveforms(summary)
        # 213: the shared status words (run_status).
        outcome = {"completed": run_status.COMPLETED, "attention": run_status.COMPLETED_WITH_PROBLEMS}.get(
            summary.outcome_kind, run_status.FAILED)
        self.host.show_external_run_outcome(results_headline(summary), state=outcome)

    def _build_waveforms(self, summary: RunSummary) -> None:
        """135: ask the shared levels job for this run's recordings, and say when they are ready."""

        self._clear_waveforms_line()
        service = getattr(self.host, "levels_service", None)
        if service is None or not getattr(service, "enabled", False) or summary.status == "failed":
            return
        paths = []
        for row in self.rows:
            if row.state in {ROW_SKIPPED, ROW_FAILED}:
                continue
            try:
                paths.append(row.path.resolve())
            except (OSError, RuntimeError, ValueError):
                paths.append(row.path)
        if paths:
            self._waveforms_listener = _WaveformsListener(self)
            service.queue(paths, listener=self._waveforms_listener)

    def on_waveforms(self, ready: int, total: int, working: bool) -> None:
        if working:
            text = f"Building the waveforms for the player ({min(ready + 1, total)} of {total})…"
        else:
            text = f"Waveforms ready for {ready} of {total} recording{'s' if total != 1 else ''}."
        self.waveforms_label.setText(text)
        self.waveforms_label.setVisible(True)

    def _clear_waveforms_line(self) -> None:
        # An earlier run's recordings can still be measured; what they say is no longer this line's.
        self._waveforms_listener = None
        self.waveforms_label.setText("")
        self.waveforms_label.hide()

    def _show_results(self) -> None:
        summary = self.summary
        assert summary is not None
        self.results_headline.setText(results_headline(summary))
        self.results_headline.setProperty("statusKind", summary.outcome_kind)
        self.results_headline.style().unpolish(self.results_headline)
        self.results_headline.style().polish(self.results_headline)
        details: list[str] = []
        for row in self.rows:
            if row.state == ROW_SKIPPED:
                details.append(f"{row.path.name}: skipped by you.")
            elif row.voice_track and row.state not in {ROW_NO_NARRATION, ROW_FAILED}:
                details.append(f"{row.path.name}: your voice was on {voice_track_text(row)}.")
        if summary.narration_moments:
            moments = summary.narration_moments
            details.append(
                f"{moments} moment{'s' if moments != 1 else ''} where you were talking, with "
                f"{summary.screenshots} screenshot{'s' if summary.screenshots != 1 else ''} "
                "(full width plus left, center and right monitor) "
                f"and {summary.clips} short video clip{'s' if summary.clips != 1 else ''} for your AI agent."
            )
        if summary.review_videos:
            details.append(
                f"{summary.review_videos} small review video{'s' if summary.review_videos != 1 else ''} "
                "of the whole recording for context."
            )
        if summary.problems:
            details.append("")
            details.append("Could not be used:")
            details.extend(f"• {problem}" for problem in summary.problems)
        if summary.no_narration:
            details.append("")
            details.append("No narration, so nothing to report:")
            details.extend(f"• {line}" for line in summary.no_narration)
        if summary.error:
            details.append("")
            details.append(summary.error)
        if self.whisper_notice.text():
            details.append("")
            details.append(self.whisper_notice.text())
        if summary.package_root is not None:
            details.append("")
            details.append(f"Package folder: {summary.package_root}")
        self.results_detail.setText("\n".join(details).strip())
        has_prompt = bool(self.prompts)
        self.fix_button.setVisible(any(row.state == ROW_FAILED for row in self.rows) or bool(summary.problems))
        self.copy_claude_button.setEnabled(has_prompt)
        self.copy_codex_button.setEnabled(has_prompt)
        self.open_folder_button.setEnabled(summary.package_root is not None)
        # Not there at all for a host with no opener, so this card looks the
        # way it always did there.
        self.watch_button.setVisible(self._video_opener() is not None)
        self.watch_button.setEnabled(bool(self.rows))
        self.copied_label.clear()
        self.stack.setCurrentIndex(2)
        self.status_sentence.setText(
            "Ready: copy the prompt and paste it into your AI agent."
            if has_prompt
            else "Finished, but there is no prompt to copy."
        )

    # Results actions -------------------------------------------------------------

    def copy_prompt(self, tool: str) -> Outcome:
        text = self.prompts.get(tool, "")
        if not text:
            return Outcome.failed("There is no prompt to copy.", "Run Find bug reports again.")
        QApplication.clipboard().setText(text)
        message = f"Prompt for {tool} copied. Paste it into {tool}."
        self.copied_label.done(message)
        return Outcome.done(message)

    def open_package_folder(self) -> Outcome:
        root = self.summary.package_root if self.summary else None
        if root is None or not Path(root).is_dir():
            return Outcome.failed("The package folder is not there any more.",
                                  "It may have been moved or deleted; run Find bug reports again.")
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(root))):
            return Outcome.failed("Windows did not open the package folder.", f"Open it yourself: {root}")
        return Outcome.done("Opened")

    def _open_log_action(self) -> Outcome:
        result = self.host.open_current_log()
        return result if isinstance(result, Outcome) else Outcome.done("Opened")

    def start_over(self) -> None:
        self.continue_folder = None
        self._remember_stopped_run(None)
        self._clear_waveforms_line()
        self.rows = []
        self.summary = None
        self.prompts = {}
        self._render_choose_table()
        self.stack.setCurrentIndex(0)
        self._refresh_choose_state()
