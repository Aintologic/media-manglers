"""Capture deterministic, sanitized Workbench Help screenshots.

This script uses the normal Windows Qt renderer and a temporary settings root,
library and local data folder. It does not open media, run a review, call the
network, or read operator history. Follow the repository foreground protocol
before running it.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys
import tempfile


os.environ.setdefault("QT_QPA_PLATFORM", "windows")

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from PySide6.QtCore import QSignalBlocker  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QAbstractButton,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QTableWidget,
    QTextBrowser,
    QWidget,
)

from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.audio_detection import (  # noqa: E402
    AudioSampleFeatures,
    AudioStreamInfo,
    RankedAudioStream,
    SourceAudioInspection,
)
from media_manglers_workbench.resources import (  # noqa: E402
    DependencyStatus,
    RuntimeResources,
)
from media_manglers_workbench.runner import FakeRunner  # noqa: E402
from media_manglers_workbench.metadata import WORKFLOW_CODEX_EVIDENCE  # noqa: E402
from media_manglers_workbench.bug_reports import (  # noqa: E402
    PAGE_NAME as BUG_REPORTS_PAGE,
    ROW_DONE,
    ROW_NO_NARRATION,
    RecordingRow,
    RunSummary,
)
from PySide6.QtWidgets import QTableWidgetItem  # noqa: E402


DEMO_ROOT = Path(r"C:\MM-DEMO")
SCREENSHOT_NAMES = (
    "workbench-home.png",
    "find-bug-reports.png",
    "find-bug-reports-results.png",
    "new-review-narration.png",
    "review-and-run-blockers.png",
    "queue-and-progress.png",
    "dependency-readiness.png",
)


def _ready_resources() -> RuntimeResources:
    return RuntimeResources(
        app_root=REPO_ROOT,
        script_path=REPO_ROOT / "Video Mangler.ps1",
        backend_source_root=REPO_ROOT / "src",
        icon_path=REPO_ROOT / "assets" / "Video Mangler.ico",
        powershell_exe="powershell.exe",
        python_exe="python.exe",
        ffmpeg_exe="ffmpeg.exe",
        ffprobe_exe="ffprobe.exe",
        packaged=True,
        dependencies=[
            DependencyStatus(
                "Media Manglers helpers",
                "ready",
                purpose="Runs local review operations.",
                key="backend_sidecar",
            )
        ],
        preflight_complete=True,
    )


def _visible_text(window: WorkbenchWindow) -> str:
    values: list[str] = []
    for widget in window.findChildren(QWidget):
        if not widget.isVisibleTo(window):
            continue
        if isinstance(widget, (QLabel, QAbstractButton, QLineEdit, QGroupBox)):
            if isinstance(widget, QGroupBox):
                values.append(widget.title())
            else:
                values.append(widget.text())
        elif isinstance(widget, (QTextBrowser, QPlainTextEdit)):
            values.append(widget.toPlainText())
        elif isinstance(widget, QComboBox):
            values.append(widget.currentText())
        elif isinstance(widget, QListWidget):
            values.extend(widget.item(index).text() for index in range(widget.count()))
        elif isinstance(widget, QTableWidget):
            for row in range(widget.rowCount()):
                for column in range(widget.columnCount()):
                    item = widget.item(row, column)
                    if item is not None:
                        values.append(item.text())
    return "\n".join(value for value in values if value)


def _assert_sanitized(window: WorkbenchWindow, screenshot_name: str) -> None:
    text = _visible_text(window)
    folded = text.casefold()
    forbidden = {
        str(Path.home()),
        os.environ.get("USERNAME", ""),
        os.environ.get("COMPUTERNAME", ""),
    }
    leaks = sorted(
        value
        for value in forbidden
        if value and len(value) >= 3 and value.casefold() in folded
    )
    non_demo_paths = [
        match.group(0)
        for match in re.finditer(r"[A-Za-z]:\\[^\s<>|\"]+", text)
        if not match.group(0).casefold().startswith(str(DEMO_ROOT).casefold())
    ]
    if leaks or non_demo_paths:
        raise RuntimeError(
            f"Refusing to capture {screenshot_name}; visible text failed sanitization: "
            f"identity={leaks}, paths={non_demo_paths}"
        )


def _capture(
    app: QApplication,
    window: WorkbenchWindow,
    output_dir: Path,
    name: str,
) -> None:
    app.processEvents()
    _assert_sanitized(window, name)
    destination = output_dir / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not window.grab().save(str(destination), "PNG"):
        raise RuntimeError(f"Qt could not save {destination}")


def _inspection(
    source: Path,
    *,
    microphone_ordinal: int,
    confirmation_state: str,
    confirmation_source: str,
    confidence: float,
) -> SourceAudioInspection:
    microphone = AudioStreamInfo(
        microphone_ordinal,
        microphone_ordinal + 1,
        title="Microphone",
        codec="aac",
        channels=1,
    )
    game_ordinal = 1 if microphone_ordinal == 0 else 0
    game = AudioStreamInfo(
        game_ordinal,
        game_ordinal + 1,
        title="Game and radio",
        codec="aac",
        channels=2,
    )
    return SourceAudioInspection(
        source=source,
        streams=sorted([game, microphone], key=lambda stream: stream.ordinal),
        ranked=[
            RankedAudioStream(
                microphone,
                4.2,
                confidence,
                ("clean speech with limited continuous background",),
                AudioSampleFeatures(speech_activity=0.82, background_likelihood=0.08),
            ),
            RankedAudioStream(
                game,
                -1.8,
                0.24,
                ("continuous background and mixed voices",),
                AudioSampleFeatures(speech_activity=0.55, background_likelihood=0.88),
            ),
        ],
        layout_fingerprint=f"synthetic-layout-{source.stem}",
        recorder_profile="Synthetic recorder",
        duration_seconds=90.0,
        selected_ordinal=microphone_ordinal,
        confirmation_state=confirmation_state,
        confirmation_source=confirmation_source,
    )


BUG_REPORT_RECORDINGS = (
    ("2026-01-06_19-00-00.mkv", "3.8 GB", 2),
    ("2026-01-06_20-30-00.mkv", "2.9 GB", 2),
    ("2026-01-07_21-15-00.mkv", "4.1 GB", None),
)


def _stage_bug_reports_chosen(window: WorkbenchWindow) -> None:
    """Show the Find my bug reports screen with three synthetic recordings chosen.

    The rows are populated directly (not via add_recordings) so no demo file has
    to exist on disk; the table shows the same columns the operator sees.
    """
    page = window.bug_reports_page
    page.rows = [
        RecordingRow(path=DEMO_ROOT / "recordings" / name)
        for name, _size, _track in BUG_REPORT_RECORDINGS
    ]
    page.table.setRowCount(len(page.rows))
    for index, (name, size, _track) in enumerate(BUG_REPORT_RECORDINGS):
        for column, text in enumerate((name, size, "Automatic", "Ready")):
            page.table.setItem(index, column, QTableWidgetItem(text))
    page.stack.setCurrentIndex(0)
    page.start_button.setEnabled(True)
    page.remove_button.setEnabled(True)
    page.projects_label.setText("My projects: 4 projects will be listed in the prompt.")
    page.status_sentence.setText(
        "3 recordings ready (10.8 GB). Press Find bug reports when you are ready."
    )
    window.navigate(BUG_REPORTS_PAGE)


def _stage_bug_reports_results(window: WorkbenchWindow) -> None:
    """Show the finished state: one recording had no narration, two were usable."""
    page = window.bug_reports_page
    for row, (_name, _size, track) in zip(page.rows, BUG_REPORT_RECORDINGS):
        row.voice_track = track
        row.state = ROW_DONE if track else ROW_NO_NARRATION
        row.note = "" if track else "No narration found"
    package_root = (
        DEMO_ROOT / "output" / "bug-reports" / "2026-01-07_22-00-00" / "codex-evidence-package"
    )
    page.summary = RunSummary(
        status="complete_with_problems",
        package_root=package_root,
        usable=2,
        total=3,
        problems=[
            "2026-01-07_21-15-00.mkv: no narration found - your microphone was silent "
            "in this recording, or it was not recorded on its own track"
        ],
        narration_moments=7,
        screenshots=28,
        clips=7,
        review_videos=2,
    )
    page.prompts = {"Claude Code": "(demo prompt)", "Codex": "(demo prompt)"}
    page._show_results()
    window.navigate(BUG_REPORTS_PAGE)


def capture_all(output_dir: Path) -> tuple[Path, ...]:
    app = QApplication.instance() or QApplication([])
    captured: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="mm-help-screenshots-") as temp:
        settings_root = Path(temp)
        # Every folder the app keeps per user (the library with its run history, local and roaming data,
        # the cache, the Videos and Music folders) lives in the temporary folder too, so the capture
        # never opens, upgrades, reads or shows the operator's own.
        for name, folder in (("MEDIA_MANGLERS_LIBRARY_ROOT", "library"),
                             ("MEDIA_MANGLERS_WORKBENCH_LOCALAPPDATA", "local"),
                             ("MEDIA_MANGLERS_WORKBENCH_APPDATA", "roaming"),
                             ("MEDIA_MANGLERS_CACHE_ROOT", "cache"),
                             ("MEDIA_MANGLERS_VIDEOS_FOLDER", "videos"),
                             ("MEDIA_MANGLERS_MUSIC_FOLDER", "music")):
            os.environ[name] = str(settings_root / folder)
        window = WorkbenchWindow(
            settings_path=settings_root / "settings.json",
            profiles_dir=settings_root / "profiles",
            runner_factory=FakeRunner,
            resources=_ready_resources(),
        )
        window.app_settings["debug_mode"] = False
        window._refresh_build_identity_disclosure(False)
        window.resize(1320, 1000)
        window.show()

        _capture(app, window, output_dir, "workbench-home.png")
        captured.append(output_dir / "workbench-home.png")

        _stage_bug_reports_chosen(window)
        _capture(app, window, output_dir, "find-bug-reports.png")
        captured.append(output_dir / "find-bug-reports.png")

        _stage_bug_reports_results(window)
        _capture(app, window, output_dir, "find-bug-reports-results.png")
        captured.append(output_dir / "find-bug-reports-results.png")

        first = DEMO_ROOT / "recordings" / "session-alpha.mkv"
        second = (
            DEMO_ROOT
            / "recordings"
            / "session-bravo-long-synthetic-recording-name.mkv"
        )
        window.set_current_workflow(WORKFLOW_CODEX_EVIDENCE)
        with QSignalBlocker(window.input_path_edit):
            window.input_path_edit.setText(str(DEMO_ROOT / "recordings"))
        window.run_settings["input_path"] = str(DEMO_ROOT / "recordings")
        window.run_settings["output_folder"] = str(DEMO_ROOT / "output")
        window.audio_expected_sources = [str(first), str(second)]
        window.audio_inspections = {
            str(first): _inspection(
                first,
                microphone_ordinal=1,
                confirmation_state="confirmed-layout",
                confirmation_source="exact saved-layout match",
                confidence=0.94,
            ),
            str(second): _inspection(
                second,
                microphone_ordinal=0,
                confirmation_state="unresolved",
                confirmation_source="heuristic recommendation",
                confidence=0.97,
            ),
        }
        window.active_audio_source = str(second)
        window._populate_audio_stream_combo()
        window._refresh_audio_batch_table()
        window.source_discovery_status.setText(
            "✓ Found 2 supported source files. Next: inspect 2 source files to identify the microphone narration track."
        )
        window._set_operator_state(window.source_discovery_status, "ready")
        window.inspect_audio_streams_button.setText("Inspect 2 source files")
        window.inspect_audio_streams_button.setEnabled(True)
        window._refresh_preview_identity(state="ready")
        window.audio_inspection_progress.setRange(0, 2)
        window.audio_inspection_progress.setValue(2)
        window.audio_inspection_progress.setFormat("Finished — 1 confirmation required")
        window.audio_stream_status.setText(
            "Two files inspected; session-bravo-long-synthetic-recording-name.mkv still requires confirmation."
        )
        window.navigate("New Review")
        window.wizard_steps.setCurrentRow(1)
        source_scroll = window.wizard_stack.currentWidget()
        if hasattr(source_scroll, "verticalScrollBar"):
            source_scroll.verticalScrollBar().setValue(100)
        _capture(app, window, output_dir, "new-review-narration.png")
        captured.append(output_dir / "new-review-narration.png")

        window.wizard_steps.setCurrentRow(4)
        window.refresh_review_summary()
        _capture(app, window, output_dir, "review-and-run-blockers.png")
        captured.append(output_dir / "review-and-run-blockers.png")

        queue = [str(first), str(second)]
        window.run_settings["output_folder"] = str(DEMO_ROOT / "output")
        window._initialize_progress_queue(queue)
        window._set_progress_item_state(str(first), "completed")
        window._apply_structured_progress(
            {
                "schema": "MM_PROGRESS_V1",
                "phase": "Transcription",
                "phase_index": 2,
                "phase_count": 4,
                "progress_kind": "work_units",
                "completed": 42,
                "total": 100,
                "source_completed": 1,
                "source_total": 2,
                "source_name": str(second),
                "activity": "Transcribing the active recording locally",
                "eta_state": "available",
                "eta_seconds": 95,
            }
        )
        window.progress_elapsed.setText("00:03:20")
        window.navigate("Queue / Progress")
        _capture(app, window, output_dir, "queue-and-progress.png")
        captured.append(output_dir / "queue-and-progress.png")

        checked_at = "2026-07-16 10:30 local"
        window.resources.dependencies = [
            DependencyStatus("Media Manglers helpers", "ready", purpose="Runs local review operations.", version="0.9.4", key="backend_sidecar", last_checked=checked_at),
            DependencyStatus("Windows PowerShell", "ready", purpose="Runs the proven Video Mangler workflow.", version="5.1", key="powershell", last_checked=checked_at),
            DependencyStatus("Python", "ready", purpose="Runs helpers and Local Whisper.", version="3.14", key="python", last_checked=checked_at),
            DependencyStatus("FFmpeg", "needs_setup", purpose="Reads audio, frames, and clips.", key="ffmpeg", action_label="Choose path", action_kind="choose_ffmpeg", last_checked=checked_at),
            DependencyStatus("FFprobe", "ready", purpose="Inspects media and audio tracks.", version="8.1", key="ffprobe", last_checked=checked_at),
            DependencyStatus("Whisper", "ready", purpose="Creates local transcripts.", version="20250625", key="whisper", last_checked=checked_at),
            DependencyStatus("Whisper model: medium", "needs_setup", purpose="Controls transcription accuracy and local storage.", required=False, key="whisper_model", action_label="Approve download", action_kind="approve_model_download", last_checked=checked_at),
            DependencyStatus("PyTorch", "ready", purpose="Runs Whisper on CPU or GPU.", version="2.10", key="torch", last_checked=checked_at),
            DependencyStatus("CUDA acceleration", "optional", purpose="Speeds transcription when compatible.", required=False, key="cuda", action_label="Learn more", action_kind="learn_more", last_checked=checked_at),
            DependencyStatus("CPU fallback", "ready", purpose="Keeps Local Whisper usable without CUDA.", key="cpu_fallback", last_checked=checked_at),
        ]
        window.resources.preflight_complete = True
        window.refresh_dependency_status()
        window.navigate("Settings")
        window.settings_tabs.setCurrentIndex(2)
        _capture(app, window, output_dir, "dependency-readiness.png")
        captured.append(output_dir / "dependency-readiness.png")

        window._closing_after_smoke = True
        window.close()
        app.processEvents()
    return tuple(captured)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "docs" / "workbench" / "images",
    )
    args = parser.parse_args()
    captured = capture_all(args.output_dir.resolve())
    for path in captured:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
