from __future__ import annotations

import ast
from dataclasses import replace
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QPoint, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QColor, QPalette, QWheelEvent  # noqa: E402
from PySide6.QtMultimedia import QMediaPlayer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QDialog,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from media_manglers.core.session_review import build_session_review, write_session_review_artifacts  # noqa: E402
from media_manglers_workbench.app import (  # noqa: E402
    TRANSIENT_PROFILE_KEYS,
    WorkbenchWindow,
    _moment_seconds,
    _parse_url_lines,
)
from media_manglers_workbench.audio_detection import (  # noqa: E402
    AudioSampleFeatures,
    AudioStreamInfo,
    RankedAudioStream,
    SourceAudioInspection,
)
from media_manglers_workbench.dependencies import DependencyCheckStopped, DependencyPreflightResult  # noqa: E402
from media_manglers_workbench.evidence import load_evidence_package  # noqa: E402
from media_manglers_workbench.prompts import export_session_prompt_drafts  # noqa: E402
from media_manglers_workbench.resources import (  # noqa: E402
    DependencyStatus,
    RuntimeResources,
    discover_runtime_resources,
)
from media_manglers_workbench.runner import (  # noqa: E402
    FakeRunner,
    RunnerResult,
    hidden_subprocess_creation_flags,
)
from media_manglers_workbench.settings import (  # noqa: E402
    SETTINGS_SCHEMA_VERSION,
    ProfileManager,
    _profile_fingerprint,
    build_default_settings,
    load_settings,
)
from media_manglers_workbench.theme import LIGHT_TOKENS, apply_theme  # noqa: E402
from media_manglers_workbench.video_open import (  # noqa: E402
    PlaySequence,
    PlayTarget,
    VideoOpener,
    VideoPlayerSettingsPanel,
    next_target,
)
from media_manglers_workbench.widgets import (  # noqa: E402
    WheelSafeComboBox,
    WheelSafeDoubleSpinBox,
    WheelSafeSpinBox,
)
from tests.qt_input import (  # noqa: E402
    bring_to_front,
    click,
    double_click_row,
    double_click_row_with_a_gap,
    right_click_row,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PACKAGE = REPO_ROOT / "tests" / "fixtures" / "workbench" / "evidence_package"


def _ready_resources() -> RuntimeResources:
    return RuntimeResources(
        app_root=REPO_ROOT,
        script_path=REPO_ROOT / "Video Mangler.ps1",
        backend_source_root=REPO_ROOT / "src",
        icon_path=REPO_ROOT / "assets" / "Video Mangler.ico",
        powershell_exe="powershell",
        python_exe="py",
        ffmpeg_exe="ffmpeg",
        ffprobe_exe="ffprobe",
        packaged=False,
        dependencies=[DependencyStatus("test backend", "ready")],
    )


def _session_candidate(candidate_id: str, minute: int, text: str) -> dict[str, object]:
    seconds = minute * 60
    return {
        "evidence_id": candidate_id,
        "source_id": "session",
        "source_filename": "private-session.mkv",
        "marker_timestamp_seconds": seconds,
        "marker_timestamp": f"00:{minute:02d}:00.000",
        "timestamp_start_seconds": seconds - 30,
        "timestamp_end_seconds": seconds + 60,
        "detected_marker_phrases": ["make this a ticket"],
        "confidence": "explicit",
        "transcript_excerpt": text,
        "suggested_issue_title": text,
        "render_status": "rendered",
        "frames": [{"status": "completed"}],
        "audio_snippet": {"status": "completed"},
        "likely_target_repo": "owner/repo",
        "narration_context_path": f"evidence_items/{candidate_id}/narration_context.md",
        "full_transcript_paths": {"full_transcript_markdown": "transcript/full_transcript.md"},
        "narration_context": {"entries": [{"kind": "speech", "text": text}]},
    }


class _StubReviewPlayerWindow:
    """Stands in for the built-in player window (125): no picture, no sound, no thread.

    ``source`` is the recording it holds open, the way the real window's player
    holds the file, and ``events`` is everything asked of it, in order.
    """

    instances: list["_StubReviewPlayerWindow"] = []

    def __init__(self, *_args, **_kwargs) -> None:
        self.events: list[str] = []
        self.source = ""
        self.shutdown_result = True
        _StubReviewPlayerWindow.instances.append(self)

    def open_target(self, target, *, sequence=None, autoplay=True, note="") -> None:
        self.source = str(target.path)
        self.events.append("open")

    def show_note(self, text: str) -> None:
        self.events.append(f"note: {text}")

    def release_media(self) -> None:
        self.source = ""
        self.events.append("release")

    def yield_audio(self) -> None:
        self.events.append("yield")

    def shutdown(self, wait_ms: int = 5000) -> bool:
        self.events.append("shutdown")
        return self.shutdown_result

    def close(self) -> bool:
        self.events.append("close")
        return True


class VideoWiringRuleTests(unittest.TestCase):
    """The rules of the 125 wiring that need no window, so they cost nothing."""

    def test_video_player_choices_are_never_part_of_a_profile(self) -> None:
        # Left out of this set, applying a profile or changing workflow would
        # put the player choice back to its default behind the operator's back.
        self.assertLessEqual(
            {
                "video_player",
                "video_autoplay",
                "video_player_vlc_path",
                "review_player_geometry",
                "review_player_volume",
            },
            TRANSIENT_PROFILE_KEYS,
        )

    def test_video_moment_is_read_from_seconds_or_from_their_text_twin(self) -> None:
        self.assertEqual(_moment_seconds(270, 300), 270.0)
        self.assertEqual(_moment_seconds(None, 0, 0.0, "", 300.5), 300.5)
        self.assertEqual(_moment_seconds(None, "00:25:00.000"), 1500.0)
        self.assertEqual(_moment_seconds("01:02:03.250"), 3723.25)
        self.assertEqual(_moment_seconds("02:03"), 123.0)
        self.assertEqual(_moment_seconds(" 41.5 "), 41.5)
        # Not moments: nothing, zero, below zero, other words, true/false and
        # numbers that are not numbers. The next value is tried instead.
        self.assertEqual(
            _moment_seconds(None, "", "soon", True, -5, float("nan"), float("inf"), "00:00:00.000", 12),
            12.0,
        )
        self.assertEqual(_moment_seconds(), 0.0)

    def test_video_close_lets_go_first_and_saves_after_the_player_has_closed(self) -> None:
        # Read from the source, because no run of closeEvent can show it: six
        # paths refuse to close and return early, and a new one added ABOVE
        # the release would leave the player holding the recording's file.
        source = textwrap.dedent(inspect.getsource(WorkbenchWindow.closeEvent))
        close_event = ast.parse(source).body[0]
        self.assertIsInstance(close_event, ast.FunctionDef)
        self.assertEqual(ast.unparse(close_event.body[0]), "self.video_opener.release_media()")
        # Closing the player writes its window position and volume into the
        # settings; saved before that, they would never reach the disk.
        self.assertEqual(source.count("self.save_app_settings()"), 1)
        self.assertLess(source.index("video_opener.shutdown("), source.index("self.save_app_settings()"))
        # What a refused close says is said in the player's own window.
        self.assertLess(source.index("video_opener.shutdown("), source.index("video_opener.say("))
        self.assertLess(source.index("video_opener.say("), source.index("self.save_app_settings()"))


class WorkbenchGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window: WorkbenchWindow | None = None

    def tearDown(self) -> None:
        if self.window:
            self.window._closing_after_smoke = True
            self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def _window(self, runner_factory=FakeRunner) -> WorkbenchWindow:
        settings_path = self.root / "settings.json"
        if not settings_path.exists():
            settings_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": SETTINGS_SCHEMA_VERSION,
                        "settings": {
                            "log_folder": str(self.root / "logs"),
                            "temp_folder": str(self.root / "temp"),
                        },
                    }
                ),
                encoding="utf-8",
            )
        self.window = WorkbenchWindow(
            settings_path=settings_path,
            profiles_dir=self.root / "profiles",
            runner_factory=runner_factory,
            resources=_ready_resources(),
        )
        self.window.show()
        self.app.processEvents()
        return self.window

    def _apply_evidence_profile(self, window: WorkbenchWindow) -> None:
        self.assertTrue(
            window.apply_profile("iRacing Ticket Evidence - Balanced", force=True)
        )

    def _wait_until(self, predicate, timeout_ms: int = 5000) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertTrue(predicate(), "Timed out while waiting for the Workbench state change")

    def test_profile_selection_auto_applies_workflow_and_dirty_replacement_is_safe(self) -> None:
        window = self._window()
        self.assertEqual(window.current_profile, "")
        self.assertEqual(window.current_workflow, "1")
        self._apply_evidence_profile(window)
        self.assertEqual(window.current_profile, "iRacing Ticket Evidence - Balanced")
        self.assertEqual(window.current_workflow, "3")
        self.assertEqual(window.run_settings["narration_context_post_seconds"], 600)
        self.assertEqual(window.run_settings["language"], "en")
        self.assertEqual(window.run_settings["narration_speech_mode"], "Sparse")
        self.assertEqual(window.run_settings["evidence_render_density"], "Compact")
        self.assertEqual(window.run_settings["evidence_frame_cadence_seconds"], 15.0)
        self.assertEqual(window.run_settings["evidence_max_frames_per_candidate"], 24)
        self.assertIn("Balanced ticket-focused review", window.profile_state_label.text())

        cadence = window.run_settings["evidence_frame_cadence_seconds"]
        window.run_settings["evidence_frame_cadence_seconds"] = cadence + 1
        window._update_profile_dirty_state()
        self.assertTrue(window.is_profile_dirty())
        self.assertFalse(
            window.apply_profile("Transcript Search", confirm_replace=lambda: False)
        )
        self.assertEqual(window.current_profile, "iRacing Ticket Evidence - Balanced")
        self.assertTrue(window.apply_profile("Transcript Search", confirm_replace=lambda: True))
        self.assertEqual(window.current_workflow, "2")
        self.assertFalse(window.is_profile_dirty())

    def test_packaged_workbench_loads_and_migrates_builtin_profile(self) -> None:
        profiles_dir = self.root / "profiles"
        profiles_dir.mkdir()
        name = "iRacing Ticket Evidence - Balanced"
        legacy_settings = {
            "default_workflow": "3",
            "language": "",
            "evidence_frame_cadence_seconds": 1.0,
            "evidence_max_frames_per_candidate": 220,
        }
        (profiles_dir / f"{name}.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 2,
                    "profileName": name,
                    "profileType": "built-in",
                    "workflow": "3",
                    "builtInVersion": 1,
                    "builtInDefaultsHash": _profile_fingerprint(legacy_settings, "3"),
                    "settings": legacy_settings,
                }
            ),
            encoding="utf-8",
        )
        packaged = _ready_resources()
        packaged.packaged = True
        settings_path = self.root / "settings.json"
        settings_path.write_text(
            json.dumps(
                {
                    "schemaVersion": SETTINGS_SCHEMA_VERSION,
                    "settings": {
                        "default_workflow": "3",
                        "default_profile": name,
                        "log_folder": str(self.root / "logs"),
                        "temp_folder": str(self.root / "temp"),
                    },
                }
            ),
            encoding="utf-8",
        )

        self.window = WorkbenchWindow(
            settings_path=settings_path,
            profiles_dir=profiles_dir,
            runner_factory=FakeRunner,
            resources=packaged,
        )

        self.assertTrue(self.window.resources.packaged)
        self.assertEqual(self.window.current_profile_metadata.migration_status, "migrated-built-in")
        self.assertEqual(self.window.run_settings["language"], "en")
        self.assertEqual(self.window.run_settings["narration_speech_mode"], "Sparse")
        self.assertEqual(self.window.run_settings["evidence_render_density"], "Compact")

    def test_profile_control_change_marks_custom_and_prompts_before_replacement(self) -> None:
        window = self._window()
        self._apply_evidence_profile(window)
        visual_preset = window.run_setting_controls["visual_context_preset"]
        visual_preset.setCurrentText("Extended")
        self.app.processEvents()

        self.assertEqual(window.run_settings["visual_context_preset"], "Extended")
        self.assertTrue(window.is_profile_dirty())
        self.assertEqual(
            window.profile_state_label.text(),
            "Custom \N{EM DASH} modified from iRacing Ticket Evidence - Balanced",
        )

        transcript_index = window.profile_selector.findData("Ticket Evidence Run")
        with patch(
            "media_manglers_workbench.app.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ) as confirm:
            window.profile_selector.setCurrentIndex(transcript_index)
            self.app.processEvents()

        confirm.assert_called_once()
        self.assertEqual(window.current_profile, "iRacing Ticket Evidence - Balanced")
        self.assertEqual(window.profile_selector.currentData(), window.current_profile)
        self.assertEqual(window.run_settings["visual_context_preset"], "Extended")

    def test_light_theme_resets_dark_palette_for_labels_and_dialog_text(self) -> None:
        apply_theme(self.app, "Dark")
        apply_theme(self.app, "Light")
        palette = self.app.palette()
        # 237: the light theme's text token from the UI rulebook.
        text = LIGHT_TOKENS["text"]
        self.assertEqual(palette.color(QPalette.ColorRole.WindowText), QColor(text))
        self.assertEqual(palette.color(QPalette.ColorRole.Text), QColor(text))
        self.assertIn(f"QMessageBox {{ color: {text}; }}", self.app.styleSheet())
        apply_theme(self.app, "Dark")

    def test_no_load_profile_action_and_startup_workflow_exists_only_in_settings(self) -> None:
        window = self._window()
        button_text = [button.text() for button in window.findChildren(type(window.start_review_button))]
        review_text = "\n".join(
            str(widget.text())
            for widget in window.pages["New Review"].findChildren(QWidget)
            if callable(getattr(widget, "text", None))
        )
        self.assertNotIn("Load Profile", button_text)
        self.assertTrue(window.pages["Settings"].isAncestorOf(window.settings_default_workflow_combo))
        self.assertFalse(window.pages["New Review"].isAncestorOf(window.settings_default_workflow_combo))
        self.assertTrue(window.pages["New Review"].isAncestorOf(window.workflow_selector))
        self.assertNotIn("Application default workflow next launch", review_text)

    def test_rich_text_escapes_local_paths_and_dependency_refresh_rediscovers(self) -> None:
        window = self._window()
        source = str(self.root / "private <session&name>.mkv")
        window.run_settings["input_path"] = source
        window.refresh_review_summary()
        self.assertIn(source, window.review_summary.toPlainText())
        self.assertIn("&lt;session&amp;name&gt;", window.review_summary.toHtml())

        refreshed = _ready_resources()
        refreshed.dependencies = [DependencyStatus("refreshed dependency", "ready")]
        window._resources_injected = False
        with patch("media_manglers_workbench.app.discover_runtime_resources", return_value=refreshed):
            window.refresh_dependency_status()
        self.assertIs(window.resources, refreshed)
        self.assertEqual(window.dependency_table.item(0, 0).text(), "refreshed dependency")

    def test_dependency_preflight_is_async_and_renders_plain_actionable_states(self) -> None:
        window = self._window()
        checked = [
            DependencyStatus(
                "Python runtime",
                "ready",
                r"C:\Synthetic\python.exe",
                "The selected runtime started successfully.",
                key="python",
                purpose="Runs local helper and transcription code.",
                version="ffmpeg version 8.1-full_build-www.synthetic.example with a deliberately long build configuration",
                last_checked="2026-07-16T12:00:00+00:00",
            ),
            DependencyStatus(
                "Whisper model: medium",
                "needs_setup",
                r"C:\SyntheticCache\medium.pt",
                "The model is not cached; first use may download about 1.5 GB.",
                required=False,
                key="whisper_model",
                purpose="Controls transcription accuracy and local storage.",
                action_label="Approve download",
                action_kind="approve_model_download",
                last_checked="2026-07-16T12:00:00+00:00",
            ),
        ]
        result = DependencyPreflightResult(
            checked,
            r"C:\Synthetic\python.exe",
            "ffmpeg",
            "ffprobe",
            [r"C:\Synthetic\python.exe"],
            "2026-07-16T12:00:00+00:00",
        )
        with patch(
            "media_manglers_workbench.app.run_dependency_preflight",
            return_value=result,
        ):
            window.start_dependency_check()
            self.assertIsNotNone(window.dependency_check_thread)
            window.workflow_description.setText("Responsive during dependency check")
            self.app.processEvents()
            self.assertEqual(
                window.workflow_description.text(),
                "Responsive during dependency check",
            )
            self._wait_until(lambda: window.dependency_check_thread is None)
        self.assertEqual(window.dependency_table.item(0, 2).text(), "Ready")
        self.assertEqual(window.dependency_table.item(1, 2).text(), "Needs setup")
        self.assertEqual(
            window.dependency_table.cellWidget(1, 4).text(), "Approve download"
        )
        self.assertNotIn(r"C:\Synthetic", window.dependency_table.item(0, 1).text())
        header = window.dependency_table.horizontalHeader()
        # Every column can be dragged by the operator (112).
        self.assertEqual(header.sectionResizeMode(1), QHeaderView.ResizeMode.Interactive)
        self.assertEqual(header.sectionResizeMode(3), QHeaderView.ResizeMode.Interactive)
        self.assertLessEqual(window.dependency_table.columnWidth(3), 200)
        self.assertFalse(window.dependency_table.wordWrap())
        self.assertIn("deliberately long", window.dependency_table.item(0, 3).toolTip())
        window.dependency_table.setCurrentCell(0, 0)
        window._dependency_row_selected()
        self.assertIn(r"C:\Synthetic\python.exe", window.dependency_details.toPlainText())

    def test_closing_during_the_readiness_check_closes_at_once_and_stops_it(self) -> None:
        # 193: no wait and no "close again after it completes". The check is stopped, with the
        # tool it was running, and it reports nothing: it runs again at the next launch.
        window = self._window()
        pid_file = self.root / "probe-pid.txt"
        probe = f"import os, time; open({str(pid_file)!r}, 'w').write(str(os.getpid())); time.sleep(60)"
        stopped: list[str] = []
        marker = DependencyPreflightResult(
            [DependencyStatus("From the stopped check", "ready", key="python")],
            r"C:\FromStoppedCheck\python.exe", "", "", [], "2026-10-21T12:00:00+00:00",
        )

        def slow_check(*_args, runner, **_kwargs):
            # A check that carries on after being stopped and still hands back a result: only the
            # thread's own guard can keep it from the window.
            try:
                runner([sys.executable, "-c", probe], 120, None)
            except DependencyCheckStopped:
                stopped.append("stopped")
            return marker

        with patch("media_manglers_workbench.app.run_dependency_preflight", side_effect=slow_check):
            window.start_dependency_check()
            self._wait_until(pid_file.is_file, timeout_ms=30000)
            settings_before = (self.root / "settings.json").read_bytes()
            started = time.monotonic()
            self.assertTrue(window.close())
            closed_in = time.monotonic() - started
        self.window = None
        self.assertLess(closed_in, 4, "closing may not wait for the check")
        self._wait_until(lambda: window.dependency_check_thread is None or not window.dependency_check_thread.isRunning())
        self.app.processEvents()
        self.assertEqual(stopped, ["stopped"], "the probe was stopped, not left to finish")
        self.assertFalse(window.resources.preflight_complete, "a stopped check's result is not used")
        self.assertNotEqual(window.resources.python_exe, r"C:\FromStoppedCheck\python.exe")
        self.assertNotIn("still finishing", window.dependency_summary.text())
        listed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid_file.read_text(encoding='utf-8')}", "/NH", "/FO", "CSV"],
            capture_output=True, text=True, check=False,
        ).stdout
        self.assertNotIn(f'"{pid_file.read_text(encoding="utf-8")}"', listed, "the probe was left running")
        log = window.run_log_path.read_text(encoding="utf-8")
        self.assertIn("Readiness check stopped because the Workbench closed.", log)
        # The paths saved before the close are what is saved after it: nothing from the stopped check.
        saved = json.loads((self.root / "settings.json").read_text(encoding="utf-8"))["settings"]
        before = json.loads(settings_before.decode("utf-8"))["settings"]
        for key in ("dependency_python_path", "dependency_ffmpeg_path", "dependency_ffprobe_path", "dependency_ytdlp_path"):
            self.assertEqual(saved.get(key, ""), before.get(key, ""), key)

    def test_dependency_model_approval_and_repair_help_make_no_system_change(self) -> None:
        window = self._window()
        model = DependencyStatus(
            "Whisper model: medium",
            "needs_setup",
            detail="First use may download about 1.5 GB.",
            required=False,
            key="whisper_model",
            purpose="Controls transcription accuracy and local storage.",
            action_label="Approve download",
            action_kind="approve_model_download",
            model="medium",
        )
        repair = DependencyStatus(
            "Media Manglers helpers",
            "needs_setup",
            detail="The helper sidecar is missing.",
            key="backend_sidecar",
            purpose="Runs local helper operations.",
            action_label="Repair",
            action_kind="repair_app",
        )
        window.resources.dependencies = [model, repair]
        window.resources.preflight_complete = True
        window.refresh_dependency_status()
        # Installer plan, Stage 3: approving is what downloads the model, at once, and only the approved model; a
        # "No" downloads nothing.
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No), \
                patch.object(window, "start_model_download") as download:
            window._dependency_action("whisper_model")
        download.assert_not_called()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
                patch.object(window, "start_model_download") as download:
            window._dependency_action("whisper_model")
        download.assert_called_once_with(["medium"])
        with (
            patch.object(QMessageBox, "information") as information,
            patch.object(window, "open_troubleshooting_help") as help_opener,
        ):
            window._dependency_action("backend_sidecar")
        information.assert_called_once()
        help_opener.assert_called_once_with("media-manglers-helpers")
        self.assertIn("No package", window.dependency_summary.text())

    def test_review_blocker_distinguishes_unchecked_runtime_from_model_download(self) -> None:
        window = self._window()
        window.resources.dependencies = [
            DependencyStatus(
                "Python runtime",
                "not_checked",
                key="python",
                purpose="Runs local helpers.",
            )
        ]
        unchecked = window.validate_current_run()
        self.assertTrue(any("Check dependency readiness" in item for item in unchecked))

        window.resources.dependencies = [
            DependencyStatus("Python runtime", "ready", key="python"),
            DependencyStatus("Local Whisper", "ready", required=False, key="whisper"),
            DependencyStatus("PyTorch", "ready", required=False, key="torch"),
            DependencyStatus("CPU fallback", "ready", required=False, key="cpu_fallback"),
            DependencyStatus(
                "Whisper model: medium",
                "needs_setup",
                detail="Not on this PC yet. Approve its download (about 1.5 GB) to use it.",
                required=False,
                key="whisper_model",
                model="medium",
            ),
            DependencyStatus("Whisper model: base.en", "ready", required=False, key="whisper_model_voice",
                             model="base.en"),
        ]
        window.resources.preflight_complete = True
        window.run_settings["whisper_model"] = "medium"
        # Installer plan, Stage 3: a model not on this PC blocks the start until its approved download is done;
        # approving no longer lets the run download it.
        window.run_settings["whisper_model_download_approved"] = True
        model_blocked = window.validate_current_run()
        self.assertTrue(any("Whisper model medium" in item and "Approve its download" in item
                            for item in model_blocked))
        window.resources.dependencies[-2] = replace(window.resources.dependencies[-2], status="ready")
        ready = window.validate_current_run()
        self.assertFalse(any("Whisper model" in item for item in ready))
        # base.en, which every review's voice detection uses, blocks too when it is missing.
        window.resources.dependencies[-1] = replace(window.resources.dependencies[-1], status="needs_setup",
                                                    detail="Not on this PC yet.")
        voice_blocked = window.validate_current_run()
        self.assertTrue(any("Whisper model base.en" in item for item in voice_blocked))

    def test_review_summary_shows_effective_profile_values_and_modified_source(self) -> None:
        window = self._window()
        self._apply_evidence_profile(window)
        window.refresh_review_summary()
        summary = window.review_summary.toPlainText()
        self.assertIn("Profile source: Balanced ticket-focused review", summary)
        self.assertIn("Language: en", summary)
        self.assertIn("Narration speech mode: Sparse", summary)
        self.assertIn("Render density: Compact", summary)
        self.assertIn("Frame cadence: 15.0 seconds", summary)
        self.assertIn("Frame cap: 24 per outcome", summary)

        window.run_settings["evidence_frame_cadence_seconds"] = 20.0
        window._update_profile_dirty_state()
        window.refresh_review_summary()
        self.assertIn("Modified current run from Balanced ticket-focused review", window.review_summary.toPlainText())

    def test_stale_clean_builtin_profile_blocks_launch_with_actionable_error(self) -> None:
        window = self._window()
        self._apply_evidence_profile(window)
        window.run_settings["narration_speech_mode"] = "Auto"
        window.profile_baseline = window._profile_snapshot(window.run_settings, window.current_workflow)

        errors = window.validate_current_run()

        self.assertTrue(any("built-in profile is stale or incomplete" in error for error in errors))
        self.assertTrue(any("Reapply the profile or restart" in error for error in errors))

    def test_saving_untouched_settings_changes_nothing(self) -> None:
        # 158: with no default profile, pressing Save settings must not pick one.
        window = self._window()
        self.assertFalse(window.app_settings.get("default_profile"))
        window.navigate("Settings")
        bring_to_front(window)
        self.app.processEvents()
        before = json.loads(json.dumps(window.app_settings))
        save = next(button for button in window.findChildren(QPushButton)
                    if button.text() == "Save settings" and button.isVisible())

        with patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok), \
                patch("media_manglers_workbench.app.apply_theme"):
            QTest.mouseClick(save, Qt.MouseButton.LeftButton)
        self.app.processEvents()

        self.assertEqual(window.settings_default_profile_combo.currentText(), "None")
        persisted = load_settings(self.root / "settings.json", repo_root=str(REPO_ROOT))
        changed = {key: (before.get(key), persisted.get(key)) for key in before
                   if before.get(key) != persisted.get(key)}
        self.assertEqual(changed, {})

    def test_output_folder_in_a_temp_folder_blocks_launch(self) -> None:
        # 127: results kept in a temp folder can be cleared without warning.
        window = self._window()
        allowed = {key: value for key, value in os.environ.items() if key != "MEDIA_MANGLERS_ALLOW_TEMP_OUTPUT"}
        with patch.dict(os.environ, allowed, clear=True):
            window.run_settings["output_folder"] = r"C:\work\temp\_VIDEO_OUTPUT"
            refused = window.validate_current_run()
            window.run_settings["output_folder"] = r"D:\Kept\Media Mangler"
            kept = window.validate_current_run()

        self.assertTrue(any("is a temporary folder" in error for error in refused), refused)
        self.assertFalse(any("temporary folder" in error for error in kept), kept)

    def test_builtin_profiles_are_protected_from_overwrite_and_delete(self) -> None:
        manager = ProfileManager(self.root / "profiles", repo_root=str(REPO_ROOT))
        manager.ensure_starter_profiles()
        settings = build_default_settings(repo_root=str(REPO_ROOT))
        with self.assertRaises(ValueError):
            manager.save("iRacing Ticket Evidence - Balanced", settings)
        with self.assertRaises(ValueError):
            manager.delete("iRacing Ticket Evidence - Balanced")

    def _wheel_event(self, target: QWidget, delta: int) -> QWheelEvent:
        center = QPointF(target.rect().center())
        return QWheelEvent(
            center,
            QPointF(target.mapToGlobal(target.rect().center())),
            QPoint(),
            QPoint(0, delta),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.ScrollUpdate,
            False,
        )

    def test_hover_wheel_preserves_values_scrolls_page_and_clicked_spin_changes(self) -> None:
        scroll = QScrollArea()
        scroll.resize(420, 240)
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setMinimumHeight(1200)
        layout = QVBoxLayout(content)
        layout.addSpacing(420)
        combo = WheelSafeComboBox()
        combo.addItems(["One", "Two", "Three"])
        combo.setCurrentIndex(1)
        spin = WheelSafeSpinBox()
        spin.setRange(0, 20)
        spin.setValue(10)
        double = WheelSafeDoubleSpinBox()
        double.setRange(0, 20)
        double.setValue(10)
        layout.addWidget(combo)
        layout.addWidget(spin)
        layout.addWidget(double)
        layout.addStretch(1)
        scroll.setWidget(content)
        scroll.show()
        self.app.processEvents()
        scrollbar = scroll.verticalScrollBar()
        scrollbar.setValue(500)
        before_scroll = scrollbar.value()
        before_values = (combo.currentIndex(), spin.value(), double.value())

        QApplication.sendEvent(combo, self._wheel_event(combo, 120))
        QApplication.sendEvent(spin, self._wheel_event(spin, 120))
        QApplication.sendEvent(double, self._wheel_event(double, 120))
        self.app.processEvents()

        self.assertEqual(before_values, (combo.currentIndex(), spin.value(), double.value()))
        self.assertNotEqual(before_scroll, scrollbar.value())
        QTest.mouseClick(spin, Qt.MouseButton.LeftButton)
        QApplication.sendEvent(spin, self._wheel_event(spin, 120))
        self.assertNotEqual(spin.value(), 10)
        spin.setFocus()
        previous = spin.value()
        QTest.keyClick(spin, Qt.Key.Key_Up)
        self.assertEqual(spin.value(), previous + 1)
        scroll.close()

    def test_url_local_restrictions_and_handoff_flags(self) -> None:
        window = self._window()
        window.run_settings.update(
            {
                "input_path": "https://example.invalid/video",
                "input_kind": "url",
                "output_folder": str(self.root / "out"),
                "evidence_handoff_mode": "Both",
                "evidence_portable_zip_max_mb": 25,
            }
        )
        window.current_workflow = "3"
        self.assertTrue(any("URL" in error for error in window.validate_current_run()))
        window.current_workflow = "1"
        self.assertFalse(window.validate_current_run())
        window.run_settings["input_kind"] = "local"
        window.run_settings["input_path"] = str(self.root / "clip.mkv")
        window.current_workflow = "3"
        command = window.build_command()
        self.assertIn("-EvidenceHandoffMode", command.argv)
        self.assertIn("Both", command.argv)
        self.assertIn("-EvidencePortableZipMaxMb", command.argv)

    def test_full_review_accepts_a_pasted_multi_url_queue_without_a_profile(self) -> None:
        first = "https://www.youtube.com/watch?v=first123"
        second = "https://www.youtube.com/watch?v=second456"
        window = self._window()
        window.resources.preflight_complete = True
        window.resources.dependencies = [
            DependencyStatus("test backend", "ready", key="backend_sidecar"),
            DependencyStatus("yt-dlp", "ready", key="ytdlp", required=False),
        ]
        window.use_recommended_settings("1")
        window.run_settings["input_kind"] = "url"
        window.run_settings["output_folder"] = str(self.root / "multi-url-output")
        window.refresh_wizard()
        window.url_input_edit.setPlainText(f"{first}\n{second}\n{first}\n")
        self.app.processEvents()

        urls, invalid = _parse_url_lines(window.url_input_edit.toPlainText())
        self.assertEqual(urls, [first, second])
        self.assertEqual(invalid, [])
        self.assertEqual(window.current_profile, "")
        self.assertIn("2 web videos queued", window.review_summary.toPlainText())
        self.assertFalse(window.validate_current_run())
        command = window.build_command()
        input_index = command.argv.index("-InputUrl") + 1
        self.assertEqual(command.argv[input_index], f"{first}\n{second}")

        window.start_job()
        self._wait_until(lambda: window.runner_thread is None)
        self.assertEqual(window.progress_queue_items, [first, second])
        self.assertEqual(window.progress_item_states[first], "completed")
        self.assertEqual(window.progress_item_states[second], "completed")

    def test_multi_url_input_reports_invalid_lines_plainly(self) -> None:
        urls, invalid = _parse_url_lines(
            "https://example.invalid/one\nnot a URL\nhttps://example.invalid/two"
        )
        self.assertEqual(len(urls), 2)
        self.assertEqual(invalid, ["not a URL"])

    def test_workflows_one_through_four_keep_runner_and_five_routes_to_dedicated_inbox(self) -> None:
        runs: list[FakeRunner] = []

        def factory() -> FakeRunner:
            runner = FakeRunner(stdout=["Phase: synthetic", "Processing: clip.mkv"])
            runs.append(runner)
            return runner

        window = self._window(factory)
        for workflow in ("1", "2", "3", "4"):
            window.current_workflow = workflow
            window.run_settings.update(
                {
                    "input_path": str(self.root / "clip.mkv"),
                    "input_kind": "local",
                    "output_folder": str(self.root / f"out-{workflow}"),
                }
            )
            if workflow == "3":
                source_key = str((self.root / "clip.mkv").resolve())
                stream = AudioStreamInfo(0, 1, title="Microphone", channels=1)
                window.audio_inspections = {
                    source_key: SourceAudioInspection(
                        Path(source_key),
                        [stream],
                        [RankedAudioStream(stream, 3.0, 1.0, ("only stream",), AudioSampleFeatures())],
                        "single-stream-layout",
                        "synthetic recorder",
                        60.0,
                        selected_ordinal=0,
                        confirmation_state="single-stream",
                        confirmation_source="single audio stream",
                    )
                }
                window.active_audio_source = source_key
                window._sync_audio_selection_settings()
            window.start_job()
            deadline = time.monotonic() + 3
            while window.runner_thread is not None and time.monotonic() < deadline:
                self.app.processEvents()
                QTest.qWait(10)
            self.assertIsNone(window.runner_thread, workflow)
            self.assertEqual(window.progress_phase.text(), "Complete")
        self.assertEqual(len(runs), 4)
        window.current_workflow = "5"
        window.run_settings["review_inbox_action"] = "Scan"
        window.start_job()
        self.assertEqual(window.page_stack.currentWidget(), window.pages["Review Media Inbox"])
        self.assertEqual(len(runs), 4)

    def test_session_parser_and_session_exports(self) -> None:
        root = self.root / "package"
        shutil.copytree(FIXTURE_PACKAGE, root)
        candidates = [
            _session_candidate("ticket-001", 5, "relative delta overlay sector colors reset"),
            _session_candidate("ticket-002", 25, "relative delta overlay sector colors reset again"),
        ]
        session = build_session_review(candidates=candidates, review_needed=[], marker_audit={})
        write_session_review_artifacts(root, session)
        package = load_evidence_package(root)
        paths = export_session_prompt_drafts(package)

        self.assertEqual(len(package.session_mentions), 2)
        self.assertTrue(package.session_relationships)
        self.assertTrue(package.proposed_threads)
        self.assertTrue(paths.codex_path.exists())
        self.assertTrue(paths.claude_path.exists())
        codex_text = paths.codex_path.read_text(encoding="utf-8")
        self.assertIn("find the operator's bug reports in this session", codex_text)

        # issue 94: the session prompt must locate the package absolutely, so a
        # pasted hand-off resolves, and must not present the marker scan as the
        # finding or write to GitHub before the operator approves.
        self.assertIn(str(root.resolve()), codex_text)
        self.assertNotIn("`../START_HERE_FOR_TICKET_AGENT.md`", codex_text)
        self.assertIn("hint, not the finding", codex_text)
        self.assertIn("Produce **draft GitHub issues**", codex_text)
        self.assertIn("until the operator approves the list", codex_text)

        handoff = json.loads(paths.handoff_path.read_text(encoding="utf-8"))
        self.assertTrue(handoff["privacy_review_required_before_public_write"])
        self.assertEqual(handoff["schema_version"], 2)
        self.assertEqual(handoff["evidence_package_root"], str(root.resolve()))
        self.assertFalse(handoff["detection_is_authoritative"])

    def test_packaged_resource_override_finds_backend_sidecars(self) -> None:
        root = self.root / "distribution"
        backend = root / "python-core" / "src" / "media_manglers"
        backend.mkdir(parents=True)
        (root / "Video Mangler.ps1").write_text("param()", encoding="utf-8")
        (backend / "__main__.py").write_text("print('ok')", encoding="utf-8")
        with patch.dict(os.environ, {"MEDIA_MANGLERS_WORKBENCH_ROOT": str(root)}, clear=False):
            resources = discover_runtime_resources()
        self.assertEqual(resources.script_path, root / "Video Mangler.ps1")
        self.assertEqual(resources.backend_source_root, root / "python-core" / "src")
        self.assertTrue(resources.dependencies[0].ready)

    def test_windows_hidden_subprocess_flag_is_enabled(self) -> None:
        if os.name == "nt":
            self.assertNotEqual(hidden_subprocess_creation_flags(), 0)

    def test_version_debug_default_and_selected_workflow_are_visible(self) -> None:
        window = self._window()
        self.assertIn("v", window.version_build_label.text())
        self.assertIn("SOURCE", window.version_build_label.text())
        full_commit = window.build_identity_labels["Full Git commit SHA"].text()
        self.assertRegex(full_commit, r"^[0-9a-f]{40}$")
        self.assertIn(full_commit[:7], window.version_build_label.text())
        self.assertIn(window.build_identity_labels["Clean/dirty build state"].text(), {"CLEAN", "DIRTY"})
        self.assertTrue(window.settings_debug_mode.isChecked())
        self.assertEqual(window.current_workflow, "1")
        self.assertTrue(
            all(
                not frame.property("selectedWorkflow")
                for frame in window.home_workflow_cards.values()
            )
        )
        self.assertTrue(
            all(not label.isVisible() for label in window.home_selection_labels.values())
        )

    def test_debug_off_hides_technical_identity_but_build_information_remains(self) -> None:
        window = self._window()
        self.assertTrue(window.settings_debug_mode.isChecked())
        self.assertIn("SOURCE", window.version_build_label.text())
        self.assertIn(window.build_identity.worktree_state, window.version_build_label.text())

        window.settings_debug_mode.setChecked(False)
        self.app.processEvents()
        self.assertEqual(window.version_build_label.text(), window.build_identity.friendly_version)
        self.assertEqual(window.home_build_identity.text(), window.build_identity.friendly_version)
        self.assertNotIn("SOURCE", window.version_build_label.text())
        self.assertNotIn(window.build_identity.short_commit, window.version_build_label.text())
        self.assertEqual(
            window.build_identity_labels["Full Git commit SHA"].text(),
            window.build_identity.full_commit,
        )
        window.copy_build_information()
        self.assertIn(window.build_identity.full_commit, QApplication.clipboard().text())

        with patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok):
            window.save_settings_from_page()
        persisted = load_settings(self.root / "settings.json", repo_root=str(REPO_ROOT))
        self.assertFalse(persisted["debug_mode"])

        window._closing_after_smoke = True
        window.close()
        self.window = None
        restarted = self._window()
        self.assertFalse(restarted.settings_debug_mode.isChecked())
        self.assertEqual(restarted.version_build_label.text(), restarted.build_identity.friendly_version)

        restarted.settings_debug_mode.setChecked(True)
        self.app.processEvents()
        self.assertIn("SOURCE", restarted.version_build_label.text())
        self.assertIn(restarted.build_identity.short_commit, restarted.version_build_label.text())
        self.assertIn(restarted.build_identity.worktree_state, restarted.version_build_label.text())

    def test_dropdown_styles_cover_visible_interaction_states(self) -> None:
        window = self._window()
        stylesheet = self.app.styleSheet()
        self.assertIn("QComboBox::drop-down", stylesheet)
        self.assertIn("QComboBox:hover", stylesheet)
        self.assertIn("QComboBox:focus", stylesheet)
        self.assertIn("QComboBox:disabled", stylesheet)
        self.assertIsInstance(window.workflow_selector, WheelSafeComboBox)

    def test_progress_parser_reports_queue_completed_and_remaining(self) -> None:
        window = self._window()
        window.progress_bar.setRange(0, 0)
        window._parse_progress_line("[3/8] Processing: synthetic-03.mkv")
        self.assertEqual(window.progress_queue.text(), "8")
        self.assertEqual(window.progress_completed.text(), "2")
        self.assertEqual(window.progress_remaining.text(), "6")
        self.assertEqual(window.overall_progress_bar.maximum(), 8)
        self.assertEqual(window.overall_progress_bar.value(), 2)
        self.assertEqual(window.progress_bar.maximum(), 0)
        self.assertIn("Active", window.progress_state_banner.text())

    def test_raw_backend_details_stay_out_of_primary_progress_text(self) -> None:
        window = self._window()
        raw_command = (
            r"[INFO] Command: C:\SyntheticUser\Tools\powershell.exe "
            r"-File C:\SyntheticUser\Media\Video-Mangler.ps1"
        )
        raw_model = "[GPU]; stage loading_model; Loading Whisper model; device cuda"

        window.on_log_line("stdout", raw_command)
        window.on_log_line("stdout", raw_model)

        primary = "\n".join(
            (window.progress_state_banner.text(), window.progress_message.text())
        )
        for private_detail in (
            "[INFO] Command",
            r"C:\SyntheticUser",
            "[GPU]",
            "stage loading_model",
            "device cuda",
        ):
            self.assertNotIn(private_detail, primary)
        self.assertIn("Loading the transcription model", primary)
        technical_log = window.progress_log.toPlainText()
        self.assertIn(raw_command, technical_log)
        self.assertIn(raw_model, technical_log)

        structured = {
            "schema": "MM_PROGRESS_V1",
            "phase": "Transcription",
            "progress_kind": "indeterminate",
            "activity": raw_model,
        }
        window._parse_progress_line("MM_PROGRESS_V1 " + json.dumps(structured))
        structured_primary = "\n".join(
            (window.progress_state_banner.text(), window.progress_message.text())
        )
        self.assertIn("Loading the transcription model", structured_primary)
        self.assertNotIn("device cuda", structured_primary)

    def test_real_source_queue_ignores_internal_work_unit_totals(self) -> None:
        window = self._window()
        sources = [
            str(self.root / "source-alpha.mkv"),
            str(self.root / "source-bravo.mkv"),
        ]
        window._initialize_progress_queue(sources)
        event = {
            "schema": "MM_PROGRESS_V1",
            "phase": "Rich rendering",
            "phase_index": 4,
            "phase_count": 4,
            "progress_kind": "work_units",
            "completed": 1400,
            "total": 1401,
            "source_completed": 1400,
            "source_total": 1401,
            "source_name": sources[0],
            "source_state": "active",
            "activity": "Rendering review evidence",
        }
        window._parse_progress_line("MM_PROGRESS_V1 " + json.dumps(event))

        self.assertEqual(window.progress_queue_table.rowCount(), 2)
        self.assertEqual(window.progress_queue.text(), "2")
        self.assertEqual(window.overall_progress_bar.maximum(), 2)
        self.assertEqual(window.overall_progress_bar.value(), 0)
        self.assertNotIn(
            "Queued item",
            "\n".join(window.progress_queue_items),
        )

        window._parse_progress_line(
            "MM_PROGRESS_V1 "
            + json.dumps({**event, "source_name": sources[1]})
        )
        self.assertEqual(window.overall_progress_bar.value(), 0)
        window._parse_progress_line(
            "MM_PROGRESS_V1 "
            + json.dumps({**event, "source_name": sources[0]})
        )
        self.assertEqual(window.progress_queue_table.rowCount(), 2)

        private_error = r"C:\SyntheticUser\private\failure.log"
        with patch.object(window, "_discover_completed_evidence_package", return_value=None):
            window.on_job_finished(
                RunnerResult(status="failed", exit_code=1, error=private_error)
            )
        self.assertEqual(window.progress_queue_table.rowCount(), 2)
        self.assertIn("1 completed", window.progress_completion_summary.text())
        self.assertIn("1 failed", window.progress_completion_summary.text())
        self.assertNotIn("skipped", window.progress_completion_summary.text())
        self.assertNotIn(private_error, window.progress_message.text())
        self.assertIn(private_error, window.progress_log.toPlainText())

    def test_structured_progress_resets_phase_and_reports_eta_and_heartbeat(self) -> None:
        window = self._window()
        first = {
            "schema": "MM_PROGRESS_V1", "phase": "Transcription", "phase_index": 1,
            "phase_count": 4, "progress_kind": "work_units", "completed": 12, "total": 20,
            "source_completed": 1, "source_total": 2, "outcome_completed": 0, "outcome_total": 0,
            "artifact_completed": 0, "artifact_total": 0, "eta_state": "available", "eta_seconds": 90,
            "source_name": "source-a.mkv", "activity": "Transcribing source A",
        }
        window._parse_progress_line("MM_PROGRESS_V1 " + json.dumps(first))
        self.assertEqual(window.progress_bar.value(), 12)
        self.assertEqual(window.overall_progress_bar.maximum(), 2)
        self.assertEqual(window.overall_progress_bar.value(), 1)
        self.assertEqual(window.progress_eta.text(), "01:30")
        second = {**first, "phase": "Outcome consolidation", "phase_index": 2, "progress_kind": "indeterminate", "completed": 0, "total": 0, "eta_state": "unavailable"}
        window._parse_progress_line("MM_PROGRESS_V1 " + json.dumps(second))
        self.assertEqual(window.progress_phase.text(), "Outcome consolidation")
        self.assertEqual(window.progress_bar.maximum(), 0)
        self.assertEqual(window.progress_eta.text(), "Unavailable")
        self.assertEqual(window.progress_heartbeat.text(), "Active")

        terminal = {
            **second,
            "phase": "Rich rendering",
            "phase_index": 4,
            "progress_kind": "work_units",
            "completed": 7,
            "total": 7,
            "terminal_state": "succeeded",
        }
        window._parse_progress_line("MM_PROGRESS_V1 " + json.dumps(terminal))
        self.assertEqual(window.progress_heartbeat.text(), "Complete")
        self.assertEqual(window.progress_eta.text(), "Unavailable")

    def test_progress_queue_preserves_long_names_and_explicit_states_when_resized(self) -> None:
        window = self._window()
        long_name = (
            "synthetic-session-with-a-deliberately-long-readable-filename-"
            "for-responsive-layout-validation-001.mkv"
        )
        sources = [str(self.root / long_name), str(self.root / "second-source.mkv")]
        window._initialize_progress_queue(sources)
        window._update_progress_queue(sources[0], 0, 2)
        self.app.processEvents()

        self.assertEqual(window.progress_queue_table.rowCount(), 2)
        self.assertEqual(window.progress_queue_table.item(0, 0).text(), "Active")
        self.assertEqual(window.progress_queue_table.item(1, 0).text(), "Pending")
        self.assertEqual(window.progress_queue_table.item(0, 1).toolTip(), sources[0])
        self.assertTrue(window.progress_current_file.wordWrap())
        self.assertEqual(window.progress_current_file.toolTip(), sources[0])

        for width in (640, 1280, 760):
            window.resize(width, 720)
            self.app.processEvents()
            self.assertEqual(window.progress_queue_table.item(0, 0).text(), "Active")
            self.assertEqual(window.progress_state_banner.accessibleName(), "Review state: Pending")
            self.assertGreater(window.progress_queue_table.columnWidth(0), 0)

    def test_progress_supports_every_terminal_item_state(self) -> None:
        window = self._window()
        sources = [str(self.root / f"source-{index}.mkv") for index in range(4)]
        window._initialize_progress_queue(sources)
        window.progress_item_states.update(
            {
                sources[0]: "completed",
                sources[1]: "failed",
                sources[2]: "skipped",
                sources[3]: "cancelled",
            }
        )
        window._refresh_progress_queue_table()
        self.assertEqual(
            [window.progress_queue_table.item(row, 0).text() for row in range(4)],
            ["Completed", "Failed", "Skipped", "Cancelled"],
        )

        window.progress_item_states.update(
            {
                sources[0]: "pending",
                sources[1]: "active",
                sources[2]: "waiting",
                sources[3]: "cancelling",
            }
        )
        window._refresh_progress_queue_table()
        self.assertEqual(
            [window.progress_queue_table.item(row, 0).text() for row in range(4)],
            ["Pending", "Active", "Waiting", "Cancelling"],
        )
        self.assertEqual(
            window._progress_state_label("complete_with_warnings"),
            "Complete with warnings",
        )

    def test_progress_terminal_source_states_are_monotonic(self) -> None:
        window = self._window()
        source = str(self.root / "source-alpha.mkv")
        window._initialize_progress_queue([source])

        window._set_progress_item_state(source, "active")
        window._set_progress_item_state(source, "completed")
        window._set_progress_item_state(source, "active")

        self.assertEqual(window.progress_item_states[source], "completed")
        self.assertEqual(window.progress_queue_table.item(0, 0).text(), "Completed")
        self.assertIn(
            "completed -> active",
            window.run_log_path.read_text(encoding="utf-8"),
        )

        event = {
            "schema": "MM_PROGRESS_V1",
            "phase": "Rich rendering",
            "progress_kind": "indeterminate",
            "source_name": source,
            "source_state": "completed",
            "source_terminal": False,
        }
        window._initialize_progress_queue([source])
        window._parse_progress_line("MM_PROGRESS_V1 " + json.dumps(event))
        self.assertEqual(window.progress_item_states[source], "active")
        window._parse_progress_line(
            "MM_PROGRESS_V1 "
            + json.dumps({**event, "source_terminal": True})
        )
        self.assertEqual(window.progress_item_states[source], "completed")

    def test_progress_cancel_and_liveness_states_remain_actionable(self) -> None:
        window = self._window()

        class CancelProbe:
            cancelled = False

            def cancel(self) -> None:
                self.cancelled = True

        probe = CancelProbe()
        window.runner_thread = probe  # type: ignore[assignment]
        window.cancel_button.setEnabled(True)
        window.cancel_job()
        self.assertTrue(probe.cancelled)
        self.assertEqual(window.cancel_button.text(), "Cancelling…")
        self.assertIn("Cancelling", window.progress_state_banner.text())

        window.structured_progress_seen = True
        window.run_started_monotonic = 1.0
        window.last_progress_event_monotonic = 10.0
        with patch("media_manglers_workbench.app.time.monotonic", return_value=45.0):
            window._refresh_elapsed()
        self.assertIn("Waiting", window.progress_state_banner.text())
        self.assertIn("35s", window.progress_heartbeat.text())
        self.assertIn("cancellation remains available", window.progress_state_banner.text())
        window.runner_thread = None

    def test_progress_completion_summarizes_warnings_failure_and_cancellation(self) -> None:
        window = self._window()
        sources = [str(self.root / f"source-{index}.mkv") for index in range(3)]
        window.run_settings["output_folder"] = str(self.root / "review-output")

        window._initialize_progress_queue(sources)
        window.progress_warning_count = 2
        with patch.object(window, "_discover_completed_evidence_package", return_value=None):
            window.on_job_finished(RunnerResult(status="succeeded", exit_code=0))
        self.assertIn("Complete with warnings", window.progress_state_banner.text())
        self.assertIn("3 completed", window.progress_completion_summary.text())
        self.assertIn("2 warning(s)", window.progress_completion_summary.text())
        self.assertIn(str(self.root / "review-output"), window.progress_completion_summary.text())
        self.assertIn("Open output", window.progress_completion_summary.text())
        self.assertEqual(window.progress_eta.text(), "Unavailable")

        window._initialize_progress_queue(sources)
        window.progress_item_states[sources[0]] = "completed"
        window.progress_item_states[sources[1]] = "active"
        window.progress_active_item = sources[1]
        window.progress_warning_count = 0
        with patch.object(window, "_discover_completed_evidence_package", return_value=None):
            window.on_job_finished(RunnerResult(status="failed", exit_code=1))
        self.assertIn("Completed with problems", window.progress_state_banner.text())
        self.assertIn("1 completed", window.progress_completion_summary.text())
        self.assertIn("1 failed", window.progress_completion_summary.text())
        # 220: the item the failed run never reached is "cancelled"; skipped means the operator skipped it.
        self.assertIn("1 cancelled", window.progress_completion_summary.text())
        self.assertNotIn("skipped", window.progress_completion_summary.text())

        window._initialize_progress_queue(sources)
        window.progress_item_states[sources[0]] = "active"
        window.progress_active_item = sources[0]
        with patch.object(window, "_discover_completed_evidence_package", return_value=None):
            window.on_job_finished(RunnerResult(status="failed", exit_code=1))
        self.assertIn("Failed", window.progress_state_banner.text())

        window._initialize_progress_queue(sources)
        window.progress_item_states[sources[0]] = "active"
        window.progress_active_item = sources[0]
        with patch.object(window, "_discover_completed_evidence_package", return_value=None):
            window.on_job_finished(RunnerResult(status="cancelled", exit_code=None))
        self.assertIn("Cancelled", window.progress_state_banner.text())
        # 220: after Stop, one word: items that never started say what the headline says.
        self.assertIn("3 cancelled", window.progress_completion_summary.text())
        self.assertNotIn("skipped", window.progress_completion_summary.text())

    def test_latest_frame_preview_uses_truthful_waiting_copy(self) -> None:
        window = self._window()
        window.latest_frame_preview_checkbox.setChecked(True)
        self.app.processEvents()
        self.assertEqual(
            window.latest_frame_preview.text(),
            "Preview enabled. Frames will appear when evidence rendering begins.",
        )
        window.latest_frame_preview_checkbox.setChecked(False)
        self.assertEqual(window.latest_frame_preview.text(), "Latest-frame preview is off")

    def test_compact_audio_results_are_interactive(self) -> None:
        # 136 (Wave 8): the wizard's own little waveform went with its own player; the track preview
        # plays in the shared built-in player (tests/test_wave8_wizard_preview.py).
        window = self._window()
        self.assertEqual(window.audio_batch_table.columnCount(), 3)
        # Columns can be dragged wider (112); the last one fills spare width.
        header = window.audio_batch_table.horizontalHeader()
        for column in range(3):
            self.assertEqual(header.sectionResizeMode(column), QHeaderView.ResizeMode.Interactive)
        self.assertTrue(header.stretchLastSection())

    def test_audio_stream_inspection_recommends_then_requires_explicit_confirmation(self) -> None:
        window = self._window()
        self._apply_evidence_profile(window)
        source = self.root / "synthetic.mkv"
        source.write_bytes(b"synthetic")
        window.input_path_edit.setText(str(source))
        game = AudioStreamInfo(0, 1, title="Game", codec="aac", channels=2)
        microphone = AudioStreamInfo(1, 2, title="Microphone", codec="aac", channels=1)
        inspection = SourceAudioInspection(
            source=source,
            streams=[game, microphone],
            ranked=[
                RankedAudioStream(microphone, 3.0, 0.91, ("metadata suggests a microphone",), AudioSampleFeatures()),
                RankedAudioStream(game, -2.0, 0.30, ("metadata suggests game audio",), AudioSampleFeatures()),
            ],
            layout_fingerprint="stable-six-track-layout",
            recorder_profile="synthetic recorder",
            duration_seconds=60.0,
            selected_ordinal=1,
        )
        with patch(
            "media_manglers_workbench.app.inspect_source",
            return_value=inspection,
        ):
            window.inspect_source_audio_streams()
            self.assertIsNotNone(window.audio_inspection_thread)
            self.assertFalse(window.cancel_audio_inspection_button.isHidden())
            self._wait_until(lambda: window.audio_inspection_thread is None)
        self.assertEqual(window.audio_stream_combo.count(), 2)
        self.app.processEvents()
        self.assertEqual(window.audio_stream_combo.currentData(), 1)
        self.assertFalse(window.run_settings["evidence_audio_stream_selection_confirmed"])
        self.assertIn("require confirmation", window.audio_stream_status.text())
        self.assertTrue(any("Review and confirm narration tracks" in error for error in window.validate_current_run()))
        window.confirm_selected_audio_stream()
        self.assertEqual(window.run_settings["evidence_audio_stream_index"], 1)
        self.assertTrue(window.run_settings["evidence_audio_stream_selection_confirmed"])
        self.assertIn("confirmed as operator narration", window.audio_stream_status.text())
        # 264 (Q4): Confirm microphone is your answer for this recording too, and it answers next time.
        from media_manglers.core import speech_facts

        self.assertEqual(speech_facts.confirmed_track(source), 2)
        self.assertEqual(speech_facts.answer_for(source).by, "wizard")
        inspection.selected_ordinal = 0
        inspection.confirmation_state = "unresolved"
        window.layout_confirmation_store.path.unlink()
        window.audio_inspection_generation = 7
        window._audio_inspection_ready(7, 1, 1, str(source), inspection)
        self.assertEqual((inspection.selected_ordinal, inspection.confirmation_state), (1, "confirmed-recording"))
        self.assertEqual(inspection.selection_reason, "your answer for this recording")

    def test_mixed_layout_batch_requires_per_file_confirmation(self) -> None:
        window = self._window()
        self._apply_evidence_profile(window)
        first_path = str((self.root / "first.mkv").resolve())
        second_path = str((self.root / "second.mkv").resolve())
        stream = AudioStreamInfo(1, 2, title="Microphone", channels=1)

        def inspection(path: str, fingerprint: str) -> SourceAudioInspection:
            return SourceAudioInspection(
                Path(path),
                [AudioStreamInfo(0, 1, title="Mix", channels=2), stream],
                [RankedAudioStream(stream, 3.0, 0.90, ("microphone metadata",), AudioSampleFeatures())],
                fingerprint,
                "synthetic recorder",
                60.0,
                selected_ordinal=1,
            )

        window.audio_inspections = {
            first_path: inspection(first_path, "layout-a"),
            second_path: inspection(second_path, "layout-b"),
        }
        window.audio_expected_sources = [first_path, second_path]
        window.active_audio_source = first_path
        window.run_settings["input_path"] = str(self.root / "synthetic-source")
        window.wizard_stack.setCurrentIndex(1)
        window._populate_audio_stream_combo()
        window._refresh_audio_batch_table()
        window._refresh_audio_resolution_progress()
        window._refresh_wizard_navigation()
        self.assertIn("2 confirmations required", window.audio_inspection_progress.format())
        self.assertEqual(
            window.wizard_next.text(),
            "Next: Review options — 2 sources need attention",
        )
        self.assertFalse(window.confirm_matching_layouts_button.isEnabled())
        window.confirm_selected_audio_stream()
        self.assertIn("1 confirmation required", window.audio_inspection_progress.format())
        self.assertEqual(
            window.wizard_next.text(),
            "Next: Review options — 1 source needs attention",
        )
        self.assertFalse(window.run_settings["evidence_audio_stream_selection_confirmed"])
        window.active_audio_source = second_path
        window._populate_audio_stream_combo()
        window.confirm_selected_audio_stream()
        self.assertIn("all files resolved", window.audio_inspection_progress.format())
        self.assertEqual(window.wizard_next.text(), "Next: Review options")
        self.assertTrue(window.run_settings["evidence_audio_stream_selection_confirmed"])
        window.audio_stream_combo.setCurrentIndex(0)
        self.assertIn("1 confirmation required", window.audio_inspection_progress.format())
        self.assertEqual(
            window.wizard_next.text(),
            "Next: Review options — 1 source needs attention",
        )
        window.audio_inspections[second_path].layout_fingerprint = "layout-a"
        window.confirm_all_matching_layouts()
        self.assertIn("all files resolved", window.audio_inspection_progress.format())
        self.assertEqual(window.wizard_next.text(), "Next: Review options")
        self.assertTrue(window.run_settings["evidence_audio_stream_selection_confirmed"])

    def test_saved_layout_inspection_refreshes_navigation_after_worker_stops(self) -> None:
        window = self._window()
        self._apply_evidence_profile(window)
        source_folder = self.root / "saved-layout-sources"
        source_folder.mkdir()
        first = source_folder / "first.mkv"
        second = source_folder / "second.mkv"
        first.write_bytes(b"synthetic")
        second.write_bytes(b"synthetic")
        mix = AudioStreamInfo(0, 1, title="Game", channels=2)
        microphone = AudioStreamInfo(1, 2, title="Microphone", channels=1)

        def inspection(source: Path) -> SourceAudioInspection:
            return SourceAudioInspection(
                source,
                [mix, microphone],
                [
                    RankedAudioStream(
                        microphone,
                        3.0,
                        0.97,
                        ("microphone metadata",),
                        AudioSampleFeatures(),
                    )
                ],
                "saved-layout-fingerprint",
                "synthetic recorder",
                60.0,
                selected_ordinal=1,
            )

        window.layout_confirmation_store.confirm(
            inspection(first),
            1,
            profile_name=window.current_profile,
        )
        window.input_path_edit.setText(str(source_folder))
        window.wizard_stack.setCurrentIndex(1)
        window._refresh_wizard_navigation()
        self.assertEqual(
            window.wizard_next.text(),
            "Next: Review options — 2 sources need attention",
        )

        with patch(
            "media_manglers_workbench.app.inspect_source",
            side_effect=lambda _probe, _ffmpeg, source, _temp, **_kwargs: inspection(Path(source)),
        ):
            window.inspect_source_audio_streams()
            self._wait_until(lambda: window.audio_inspection_thread is None)

        self.assertTrue(
            all(
                item.confirmation_state == "confirmed-layout"
                for item in window.audio_inspections.values()
            )
        )
        self.assertTrue(window.run_settings["evidence_audio_stream_selection_confirmed"])
        self.assertEqual(window.wizard_next.text(), "Next: Review options")
        self.assertIn("Current · Complete", window.wizard_steps.item(1).text())

    def test_audio_inspection_is_async_reports_progress_and_preserves_partial_failure(self) -> None:
        window = self._window()
        source_folder = self.root / "sources"
        source_folder.mkdir()
        first = source_folder / "first-synthetic.mkv"
        second = source_folder / "second-synthetic.mkv"
        first.write_bytes(b"synthetic")
        second.write_bytes(b"synthetic")
        window.input_path_edit.setText(str(source_folder))
        stream = AudioStreamInfo(0, 1, title="Microphone", channels=1)

        def inspect(_probe, _ffmpeg, source, _temp, **_kwargs):
            time.sleep(0.05)
            if Path(source).name.startswith("second"):
                raise OSError("synthetic unreadable audio")
            return SourceAudioInspection(
                Path(source),
                [stream],
                [RankedAudioStream(stream, 3.0, 1.0, ("only stream",), AudioSampleFeatures())],
                "layout-a",
                "synthetic recorder",
                30.0,
                selected_ordinal=0,
                confirmation_state="single-stream",
                confirmation_source="single audio stream",
            )

        with patch("media_manglers_workbench.app.inspect_source", side_effect=inspect):
            window.inspect_source_audio_streams()
            self.assertIsNotNone(window.audio_inspection_thread)
            window.workflow_description.setText("UI remained responsive")
            self.app.processEvents()
            self.assertEqual(window.workflow_description.text(), "UI remained responsive")
            self._wait_until(
                lambda: "Inspecting" in window.audio_inspection_progress.format()
                or window.audio_inspection_progress.value() > 0
            )
            self._wait_until(lambda: window.audio_inspection_thread is None)

        self.assertEqual(len(window.audio_inspections), 1)
        self.assertEqual(len(window.audio_inspection_failures), 1)
        self.assertEqual(window.audio_batch_table.rowCount(), 2)
        self.assertIn("1 completed, 1 failed", window.audio_inspection_progress.format())
        self.assertIn("could not inspect", window.audio_stream_status.text())

    def test_audio_inspection_cancellation_keeps_ui_responsive_and_rejects_late_result(self) -> None:
        window = self._window()
        source = self.root / "slow-synthetic.mkv"
        source.write_bytes(b"synthetic")
        window.input_path_edit.setText(str(source))
        stream = AudioStreamInfo(0, 1, title="Microphone", channels=1)

        def inspect(*_args, **kwargs):
            cancel_requested = kwargs["cancel_requested"]
            deadline = time.monotonic() + 1.0
            while not cancel_requested() and time.monotonic() < deadline:
                time.sleep(0.01)
            if cancel_requested():
                raise OSError("synthetic operation cancelled")
            return SourceAudioInspection(
                source,
                [stream],
                [],
                "slow-layout",
                "synthetic recorder",
                30.0,
                selected_ordinal=0,
                confirmation_state="single-stream",
            )

        with patch("media_manglers_workbench.app.inspect_source", side_effect=inspect):
            window.inspect_source_audio_streams()
            self._wait_until(lambda: window.audio_inspection_thread is not None)
            window.cancel_audio_inspection()
            window.workflow_description.setText("Responsive while cancelling")
            self.app.processEvents()
            self.assertEqual(window.workflow_description.text(), "Responsive while cancelling")
            self._wait_until(lambda: window.audio_inspection_thread is None)

        self.assertFalse(window.audio_inspections)
        self.assertIn("cancelled", window.audio_stream_status.text().lower())

    def test_source_discovery_counts_supported_files_before_inspection(self) -> None:
        window = self._window()
        source_folder = self.root / "source-discovery"
        source_folder.mkdir()
        (source_folder / "session-alpha.mkv").write_bytes(b"synthetic")
        (source_folder / "session-bravo.mp4").write_bytes(b"synthetic")
        (source_folder / "notes.txt").write_text("not media", encoding="utf-8")

        window.input_path_edit.setText(str(source_folder))
        self.app.processEvents()

        self.assertIn("Found 2 supported source files", window.source_discovery_status.text())
        self.assertEqual(window.inspect_audio_streams_button.text(), "Inspect 2 source files")
        self.assertTrue(window.inspect_audio_streams_button.property("primary"))
        self.assertTrue(window.inspect_audio_streams_button.isEnabled())
        self.assertEqual(window.audio_batch_table.rowCount(), 2)
        self.assertEqual(window.audio_batch_table.columnCount(), 3)
        self.assertEqual(window.audio_batch_table.item(0, 1).text(), "Not inspected")
        self.assertEqual(window.audio_batch_table.item(0, 2).text(), "⚠ REQUIRED")

    def test_source_change_invalidates_in_flight_audio_inspection(self) -> None:
        window = self._window()
        original = self.root / "original-synthetic.mkv"
        replacement = self.root / "replacement-synthetic.mkv"
        original.write_bytes(b"synthetic")
        replacement.write_bytes(b"synthetic")
        window.input_path_edit.setText(str(original))
        stream = AudioStreamInfo(0, 1, title="Microphone", channels=1)

        def inspect(*_args, **_kwargs):
            time.sleep(0.10)
            return SourceAudioInspection(
                original,
                [stream],
                [],
                "original-layout",
                "synthetic recorder",
                30.0,
                selected_ordinal=0,
                confirmation_state="single-stream",
            )

        with patch("media_manglers_workbench.app.inspect_source", side_effect=inspect):
            window.inspect_source_audio_streams()
            window.input_path_edit.setText(str(replacement))
            self._wait_until(lambda: window.audio_inspection_thread is None)

        self.assertFalse(window.audio_inspections)
        self.assertFalse(window.audio_inspection_failures)
        self.assertEqual(window.run_settings["input_path"], str(replacement))

    # 136 (Wave 8): the three tests of the wizard's own preview player (its clip preparation, its fresh
    # player per clip and its play-after-load) went with that player. What they guarded now lives in
    # tests/test_wave8_wizard_preview.py: a stale source never plays, and the shared player says what it plays.

    def test_recommendation_active_selection_and_confirmation_are_distinct(self) -> None:
        window = self._window()
        source = self.root / "selection-model.mkv"
        source.write_bytes(b"synthetic")
        source_key = str(source.resolve())
        game = AudioStreamInfo(0, 1, title="Game", channels=2)
        microphone = AudioStreamInfo(1, 2, title="Microphone", channels=1)
        inspection = SourceAudioInspection(
            source,
            [game, microphone],
            [RankedAudioStream(microphone, 4.0, 0.92, ("clean mic",), AudioSampleFeatures())],
            "selection-layout",
            "synthetic recorder",
            30.0,
            selected_ordinal=0,
            confirmation_state="profile-preference",
            confirmation_source="profile preference",
        )
        window.input_path_edit.setText(str(source))
        window.audio_expected_sources = [source_key]
        window.audio_inspections = {source_key: inspection}
        window.active_audio_source = source_key
        window._populate_audio_stream_combo()
        window._refresh_audio_batch_table()
        self.assertEqual(window.audio_batch_table.item(0, 1).text(), "Track 2 (92%)")
        self.assertEqual(window.audio_batch_table.item(0, 2).text(), "⚠ REQUIRED")
        details = window.audio_selected_source_details.text()
        self.assertIn("Recommendation: Track 2 (92%)", details)
        self.assertIn("Selected narration: Track 1", details)
        self.assertIn("Why selected: profile preference", details)
        self.assertIn(source.name, window.audio_active_source_label.text())

    def test_review_page_resolves_first_unconfirmed_source_directly(self) -> None:
        window = self._window()
        self._apply_evidence_profile(window)
        source = self.root / "needs-confirmation.mkv"
        source.write_bytes(b"synthetic")
        source_key = str(source.resolve())
        stream = AudioStreamInfo(0, 1, title="Narration", channels=1)
        window.input_path_edit.setText(str(source))
        window.audio_expected_sources = [source_key]
        window.audio_inspections = {
            source_key: SourceAudioInspection(
                source,
                [stream, AudioStreamInfo(1, 2, title="Game", channels=2)],
                [RankedAudioStream(stream, 3.0, 0.80, ("voice",), AudioSampleFeatures())],
                "unconfirmed-layout",
                "synthetic recorder",
                30.0,
                selected_ordinal=0,
                confirmation_source="heuristic recommendation",
            )
        }
        window.active_audio_source = source_key
        window._populate_audio_stream_combo()
        window._refresh_audio_batch_table()
        window.wizard_steps.setCurrentRow(4)
        window.navigate("New Review")
        window.refresh_review_summary()
        self.assertFalse(window.start_review_button.isEnabled())
        self.assertEqual(window.start_review_button.property("operatorAction"), "blocked")
        self.assertEqual(window.start_review_button.text(), "Start review — blocked")
        self.assertTrue(window.review_blocker_panel.isVisible())
        self.assertTrue(window.resolve_narration_button.isVisible())
        self.assertEqual(window.resolve_narration_button.text(), "Confirm microphone for 1 file")
        self.assertEqual(window.resolve_narration_button.property("operatorAction"), "attention")
        self.assertIn(source.name, window.run_warning_label.text())
        window.resolve_narration_button.click()
        self.assertEqual(window.wizard_steps.currentRow(), 1)
        self.assertEqual(window.active_audio_source, source_key)
        self.assertIn(source.name, window.audio_stream_status.text())

        window.confirm_selected_audio_stream()
        output = self.root / "ready-output"
        window.output_path_edit.setText(str(output))
        window.wizard_steps.setCurrentRow(4)
        window.refresh_review_summary()
        self.assertTrue(window.start_review_button.isEnabled())
        self.assertEqual(window.start_review_button.property("operatorAction"), "ready")
        self.assertEqual(window.start_review_button.text(), "✓ Start review")
        self.assertFalse(window.review_blocker_panel.isVisible())

    def test_packaged_two_file_wizard_flow_requires_independent_confirmation(self) -> None:
        resources = _ready_resources()
        resources.packaged = True
        self.window = WorkbenchWindow(
            settings_path=self.root / "packaged-settings.json",
            profiles_dir=self.root / "packaged-profiles",
            runner_factory=FakeRunner,
            resources=resources,
        )
        window = self.window
        window.show()
        self.app.processEvents()
        source_folder = self.root / "packaged-two-file-source"
        source_folder.mkdir()
        first = source_folder / "operator-session-one.mkv"
        second = source_folder / "operator-session-two.mkv"
        first.write_bytes(b"synthetic")
        second.write_bytes(b"synthetic")
        window.input_path_edit.setText(str(source_folder))
        microphone = AudioStreamInfo(1, 2, title="Microphone", channels=1)

        def inspect(_probe, _ffmpeg, source, _temp, **_kwargs):
            return SourceAudioInspection(
                Path(source),
                [AudioStreamInfo(0, 1, title="Game", channels=2), microphone],
                [RankedAudioStream(microphone, 4.0, 0.91, ("clean mic",), AudioSampleFeatures())],
                "layout-" + Path(source).stem,
                "synthetic recorder",
                30.0,
                selected_ordinal=1,
                confirmation_source="heuristic recommendation",
            )

        with patch("media_manglers_workbench.app.inspect_source", side_effect=inspect):
            window.inspect_source_audio_streams()
            self._wait_until(lambda: window.audio_inspection_thread is None)
        self.assertTrue(window.resources.packaged)
        self.assertEqual(window.audio_batch_table.rowCount(), 2)
        window.confirm_selected_audio_stream()
        self.assertFalse(window.run_settings["evidence_audio_stream_selection_confirmed"])
        window.audio_batch_table.setCurrentCell(1, 0)
        self.app.processEvents()
        window.confirm_selected_audio_stream()
        self.assertTrue(window.run_settings["evidence_audio_stream_selection_confirmed"])
        window.wizard_steps.setCurrentRow(4)
        window.refresh_review_summary()
        self.assertNotIn(
            "Review and confirm narration tracks",
            window.run_warning_label.text(),
        )

    def test_open_candidate_button_explains_missing_and_reports_success(self) -> None:
        window = self._window()
        window.load_package(FIXTURE_PACKAGE)
        self.assertTrue(window.open_candidate_button.isEnabled())
        with patch(
            "media_manglers_workbench.app.QDesktopServices.openUrl",
            return_value=True,
        ):
            window.open_current_candidate_folder()
        self.assertIn("Opened candidate folder", window.open_candidate_status.text())

        window.current_item.evidence_folder = self.root / "missing-candidate"
        window.open_current_candidate_folder()
        self.assertFalse(window.open_candidate_button.isEnabled())
        self.assertIn("missing", window.open_candidate_status.text().lower())

    def test_operator_copy_keeps_audio_mappings_behind_disclosure(self) -> None:
        window = self._window()
        self._apply_evidence_profile(window)
        source = self.root / "synthetic-session.mkv"
        source.write_bytes(b"synthetic")
        source_key = str(source.resolve())
        window.input_path_edit.setText(source_key)
        microphone = AudioStreamInfo(1, 2, title="Microphone", channels=1)
        inspection = SourceAudioInspection(
            source,
            [AudioStreamInfo(0, 1, title="Game", channels=2), microphone],
            [
                RankedAudioStream(
                    microphone,
                    4.0,
                    0.91,
                    ("clean mic",),
                    AudioSampleFeatures(),
                )
            ],
            "synthetic-layout-fingerprint",
            "synthetic recorder",
            30.0,
            selected_ordinal=1,
            confirmation_source="heuristic recommendation",
        )
        window.audio_inspections[source_key] = inspection
        window.active_audio_source = source_key
        window._populate_audio_stream_combo()
        window._refresh_audio_batch_table()
        window._audio_stream_selected()

        self.assertNotIn("FFmpeg", window.audio_stream_status.text())
        self.assertNotIn("audio ordinal", window.audio_stream_status.text())
        self.assertFalse(window.audio_technical_details_group.isChecked())
        self.assertFalse(window.audio_technical_details.isVisible())
        self.assertIn("FFmpeg mapping 0:a:1", window.audio_technical_details.text())
        self.assertIn("internal audio ordinal 1", window.audio_technical_details.text())
        self.assertIn("layout fingerprint", window.audio_technical_details.text())

        window.confirm_selected_audio_stream()
        self.assertIn("confirmed as operator narration", window.audio_stream_status.text())
        self.assertNotIn("Technical mapping", window.review_summary.toPlainText())
        self.assertIn("0:a:1", window.command_preview.toPlainText())

    def test_empty_state_actions_explain_their_prerequisites(self) -> None:
        window = self._window()
        window.refresh_review_summary()
        self.assertFalse(window.start_review_button.isEnabled())
        self.assertIn("Choose a source", window.start_review_button.toolTip())
        self.assertFalse(window.rerender_candidate_button.isEnabled())
        self.assertIn("Select an evidence item", window.rerender_candidate_button.toolTip())
        self.assertFalse(window.export_candidate_prompts_button.isEnabled())
        self.assertFalse(window.copy_prompt_button.isEnabled())
        self.assertFalse(window.export_item_prompts_button.isEnabled())
        self.assertFalse(window.export_session_prompts_button.isEnabled())
        self.assertFalse(window.history_open_output_button.isEnabled())
        self.assertIn("Select a review", window.history_open_output_button.toolTip())
        self.assertTrue(
            all(not button.isEnabled() for button in window.session_action_buttons.values())
        )
        self.assertTrue(
            all(button.toolTip() for button in window.session_action_buttons.values())
        )

        window.resources.dependencies = [
            DependencyStatus(
                "Media Manglers helpers",
                "needs_setup",
                key="backend_sidecar",
                purpose="Runs local review operations.",
            )
        ]
        window.resources.preflight_complete = True
        window.navigate("New Review")
        window.wizard_steps.setCurrentRow(4)
        window.refresh_review_summary()
        self.assertTrue(window.resolve_dependencies_button.isVisible())
        window.open_dependency_setup()
        self.assertIs(window.page_stack.currentWidget(), window.pages["Settings"])
        self.assertEqual(window.settings_tabs.currentIndex(), 2)

        window.load_package(FIXTURE_PACKAGE)
        self.assertTrue(window.rerender_candidate_button.isEnabled())
        self.assertTrue(window.export_candidate_prompts_button.isEnabled())
        self.assertTrue(window.copy_prompt_button.isEnabled())
        self.assertTrue(window.export_item_prompts_button.isEnabled())
        self.assertTrue(window.export_session_prompts_button.isEnabled())
        self.assertTrue(window.session_action_buttons["codex"].isEnabled())
        self.assertTrue(window.session_action_buttons["claude"].isEnabled())

    def test_primary_labels_are_plain_and_dense_actions_fit_minimum_window(self) -> None:
        window = self._window()
        tab_labels = {
            tabs.tabText(index)
            for tabs in window.findChildren(QTabWidget)
            for index in range(tabs.count())
        }
        self.assertIn("Advanced / Diagnostics", tab_labels)
        self.assertNotIn("Advanced backend", tab_labels)
        self.assertIsInstance(window.wizard_stack.widget(1), QScrollArea)
        self.assertEqual(window.nav_buttons["Queue / Progress"].text(), "Progress")
        self.assertEqual(
            window.nav_buttons["Queue / Progress"].accessibleName(),
            "Queue / Progress",
        )
        home_text = " ".join(
            label.text() for label in window.pages["Home"].findChildren(QLabel)
        )
        self.assertNotIn("backend", home_text.lower())

        window.navigate("Session Review")
        window.resize(980, 680)
        self.app.processEvents()
        for button in window.session_action_buttons.values():
            self.assertGreaterEqual(button.width(), button.minimumSizeHint().width())
            self.assertNotIn("backend", button.text().lower())
        self.assertEqual(
            window.session_timeline_table.horizontalHeaderItem(5).text(),
            "Likely project",
        )

        for page_name in window.pages:
            window.navigate(page_name)
            if page_name == "New Review":
                states = [("wizard", index) for index in range(window.wizard_stack.count())]
            elif page_name == "Settings":
                states = [("settings", index) for index in range(window.settings_tabs.count())]
            else:
                states = [("page", -1)]
            for state_kind, state_index in states:
                if state_kind == "wizard":
                    window.wizard_steps.setCurrentRow(state_index)
                    window.technical_toggle.setChecked(state_index == 4)
                elif state_kind == "settings":
                    window.settings_tabs.setCurrentIndex(state_index)
                self.app.processEvents()
                for control in window.findChildren(QWidget):
                    if not isinstance(control, (QPushButton, QCheckBox)):
                        continue
                    if not control.isVisible() or not control.text().strip():
                        continue
                    with self.subTest(
                        page=page_name,
                        state=state_index,
                        control=control.text(),
                    ):
                        self.assertGreaterEqual(
                            control.width() + 2,
                            control.minimumSizeHint().width(),
                        )
        window.technical_toggle.setChecked(False)

        window.settings_debug_mode.setChecked(False)
        self.app.processEvents()
        self.assertEqual(window.version_build_label.text(), window.build_identity.friendly_version)
        self.assertEqual(
            window.build_identity_labels["Full Git commit SHA"].text(),
            window.build_identity.full_commit,
        )

    def test_help_page_prefers_online_and_falls_back_to_packaged_guide(self) -> None:
        window = self._window()
        guide = REPO_ROOT / "docs" / "workbench" / "CODEX_EVIDENCE.md"
        self.assertTrue(guide.is_file())
        with (
            patch(
                "media_manglers_workbench.app.QDesktopServices.openUrl",
                return_value=True,
            ) as online,
            patch.object(window, "_open_path", return_value=True) as packaged,
        ):
            window.open_workflow_help("3")
        self.assertEqual(
            online.call_args.args[0].toString(),
            "https://github.com/Aintologic/media-manglers/blob/"
            + window.build_identity.full_commit
            + "/docs/workbench/CODEX_EVIDENCE.md",
        )
        self.assertNotIn("/main/", online.call_args.args[0].toString())
        packaged.assert_not_called()

        with (
            patch(
                "media_manglers_workbench.app.QDesktopServices.openUrl",
                return_value=False,
            ),
            patch.object(window, "_open_path", return_value=True) as packaged,
            patch.object(QMessageBox, "information") as information,
        ):
            window.open_workflow_help("3")
        packaged.assert_called_once_with(guide)
        information.assert_called_once()

        window.build_identity = replace(
            window.build_identity,
            full_commit="",
            short_commit="UNKNOWN",
        )
        landing = REPO_ROOT / "docs" / "workbench" / "README.md"
        with (
            patch(
                "media_manglers_workbench.app.QDesktopServices.openUrl",
                return_value=True,
            ) as online,
            patch.object(window, "_open_path", return_value=True) as packaged,
            patch.object(QMessageBox, "information") as information,
        ):
            window.open_workbench_help()
        online.assert_not_called()
        packaged.assert_called_once_with(landing)
        information.assert_called_once()

    def test_help_page_opens_the_feature_guide(self) -> None:
        """234: Help's Common tasks open the one guide to every feature, at this build's commit."""
        window = self._window()
        window.navigate("Help")
        guide = REPO_ROOT / "docs" / "workbench" / "FEATURE_GUIDE.md"
        self.assertTrue(guide.is_file())
        buttons = [
            button
            for button in window.pages["Help"].findChildren(QPushButton)
            if button.text() == "Every feature in one guide"
        ]
        self.assertEqual(len(buttons), 1)
        with (
            patch(
                "media_manglers_workbench.app.QDesktopServices.openUrl",
                return_value=True,
            ) as online,
            patch.object(window, "_open_path", return_value=True) as packaged,
        ):
            click(buttons[0])
        self.assertEqual(
            online.call_args.args[0].toString(),
            "https://github.com/Aintologic/media-manglers/blob/"
            + window.build_identity.full_commit
            + "/docs/workbench/FEATURE_GUIDE.md",
        )
        packaged.assert_not_called()

    # Playing a video from anywhere in the Workbench (125). Every fixture here
    # is invented: a folder called "Captured Sessions" in the test's own
    # temporary folder, and recordings called synthetic-session-*.mkv.

    def test_video_opener_exists_before_the_pages_and_every_route_reaches_it(self) -> None:
        seen: list[bool] = []
        build_pages = WorkbenchWindow._build_pages

        def spy(window_self: WorkbenchWindow) -> None:
            # Find my bug reports attaches to the opener in its constructor,
            # which runs from here. An opener made later would be missed in
            # silence: no error, just no double-click to play.
            seen.append(isinstance(getattr(window_self, "video_opener", None), VideoOpener))
            build_pages(window_self)

        with patch.object(WorkbenchWindow, "_build_pages", spy):
            window = self._window()
        self.assertEqual(seen, [True])
        opener = window.video_opener
        self.assertIsNone(opener.player_window, "making the opener must not make a player window")
        page = window.bug_reports_page
        self.assertIs(page._video_opener(), opener)

        sessions = self.root / "Captured Sessions"
        sessions.mkdir()
        recording = sessions / "synthetic-session-one.mkv"
        recording.write_bytes(b"not really video")
        moved = sessions / "synthetic-session-moved.mkv"
        page.add_recordings([recording])

        with (
            patch.object(opener, "open", return_value=True) as opened,
            patch(
                "media_manglers_workbench.app.QDesktopServices.openUrl",
                return_value=True,
            ) as handed_to_windows,
        ):
            page.table.doubleClicked.emit(page.table.model().index(0, 0))
            self.assertEqual(opened.call_args.args[0].path, recording.resolve())
            opened.reset_mock()

            # A video goes to the opener by its NAME. One that has moved must
            # get there too: handing it to Windows would open its old folder
            # and say nothing.
            self.assertTrue(window._open_path(recording))
            self.assertTrue(window._open_path(moved))
            self.assertEqual(
                [call.args[0] for call in opened.call_args_list],
                [PlayTarget(path=recording), PlayTarget(path=moved)],
            )
            handed_to_windows.assert_not_called()
            opened.reset_mock()

            self.assertTrue(window._open_path(sessions))
            opened.assert_not_called()
            self.assertEqual(
                handed_to_windows.call_args.args[0],
                QUrl.fromLocalFile(str(sessions.resolve())),
            )
            self.assertFalse(window._open_path(None))

        # Queue / Progress: only a row that names a real file gets a Play entry.
        window.progress_queue_items = [
            str(recording),
            "https://example.invalid/synthetic-clip.mp4",
            "Queued item 3",
            "synthetic-name-only.mkv",
        ]
        self.assertEqual(
            [target.path for target in window._progress_play_targets([0, 1, 2, 3, 9])],
            [recording],
        )

        # Resetting the narration previews pauses the video and keeps its place.
        with (
            patch.object(opener, "yield_audio") as yielded,
            patch.object(opener, "release_media") as released,
        ):
            window._cancel_audio_previews()
        yielded.assert_called_once_with()
        released.assert_not_called()

    def test_video_history_and_home_rows_resolve_to_the_runs_recordings(self) -> None:
        window = self._window()
        # None of these is ever created. Working out what a run plays asks the
        # disk nothing about a recording, so one that has moved, or whose drive
        # is asleep, still reaches the opener's "Find it…" and freezes nothing.
        sessions = self.root / "Captured Sessions"
        recording = sessions / "synthetic-session-one.mkv"
        second = sessions / "synthetic-session-two.mkv"
        moved = sessions / "synthetic-session-moved.mkv"

        def package(folder: Path, sources: list[object]) -> Path:
            root = folder / "codex-evidence-package"
            root.mkdir(parents=True)
            (root / "manifest.json").write_text(json.dumps({"sources": sources}), encoding="utf-8")
            return root

        one = package(self.root / "review-one", [{"source_id": "one", "source_path": str(recording)}])
        many = package(
            self.root / "review-many",
            [
                {"source_id": "one", "source_path": str(recording)},
                {"source_id": "web", "source_path": "https://example.invalid/synthetic-clip.mp4"},
                {"source_id": "one-again", "source_path": str(recording).upper()},
                {"source_id": "two", "source_path": str(second)},
                "not a source",
            ],
        )

        def run(source: str, output: Path) -> dict[str, str]:
            return {
                "timestamp": "2026-09-20 14:05",
                "workflow_title": "Codex Evidence",
                "status": "succeeded",
                "source": source,
                "output": str(output),
            }

        window.records.import_legacy_runs([
            run(str(recording), one.parent),
            run("3 recordings", many.parent),
            run("Configured folders", self.root / "review-gone"),
            # Moved since, and its output folder was used again by another run.
            run(str(moved), many.parent),
            # Only a file name: the run's package says where that recording was.
            run(second.name, many.parent),
            # History has a row for each run, so a recording can be there twice.
            run(str(recording), one.parent),
        ])
        window.refresh_history()
        window.refresh_home()

        def targets(view, row: int) -> list[PlayTarget]:
            return window._run_play_targets(view.model().index(row, 0))

        # is_file(), exists() and is_dir() all go through stat(). A play list
        # is built from every row on the GUI thread, so none of them may ask.
        with patch.object(Path, "stat", side_effect=AssertionError("asked the disk about a path")) as asked:
            history = [targets(window.history_list, row) for row in range(window.history_list.count())]
            home = targets(window.home_recent_list, 0)
        asked.assert_not_called()

        # The package is named by the run's output folder, as the run recorded
        # it. Which folder inside holds the package is the player's to find.
        from_the_run = [PlayTarget(path=recording, package_root=one.parent, label=recording.name)]
        self.assertEqual(history[0], from_the_run)
        self.assertEqual(home, from_the_run)
        self.assertEqual(
            [(target.path, target.package_root) for target in history[1]],
            [(recording, many.parent), (second, many.parent)],
        )
        self.assertEqual(history[2], [])
        self.assertEqual(history[3], [PlayTarget(path=moved, package_root=many.parent, label=moved.name)])
        self.assertEqual(history[4], [PlayTarget(path=second, package_root=many.parent, label=second.name)])
        self.assertEqual(history[5], from_the_run)

        self.assertFalse(window.history_play_button.isEnabled())
        self.assertIn("Select a review", window.history_play_button.toolTip())
        window.history_list.setCurrentRow(0)
        self.assertTrue(window.history_play_button.isEnabled())
        with patch.object(window.video_opener, "open", return_value=True) as opened:
            window.history_play_button.click()
        self.assertEqual(opened.call_args.args[0], from_the_run[0])
        sequence = opened.call_args.kwargs["sequence"]
        self.assertIsInstance(sequence, PlaySequence)
        self.assertEqual(sequence.label, "History")
        # The list "never use" moves along is built on the GUI thread from
        # every row. Only the chosen row may read its package; every other row
        # counts only when it names its recording in full, so "3 recordings",
        # "Configured folders" and the bare file name are left out of it.
        self.assertEqual([target.path for target in sequence.targets], [recording, moved, recording])
        self.assertEqual(sequence.opened_at, 0)
        self.assertEqual(next_target(sequence, recording, ())[0].path, moved)

        # Building that list for the rows that were not chosen asks the disk
        # nothing at all: no stat, and no package file read either.
        with (
            patch.object(Path, "stat", side_effect=AssertionError("asked the disk about a path")) as asked,
            patch.object(Path, "read_text", side_effect=AssertionError("read a file")) as read,
        ):
            quiet = [
                window._run_play_targets_without_disk(window.history_list.model().index(row, 0))
                for row in range(window.history_list.count())
            ]
        asked.assert_not_called()
        read.assert_not_called()
        self.assertEqual([[target.path for target in row] for row in quiet], [[recording], [], [], [moved], [], [recording]])

        # The same recording opened from its LAST row: the list knows which row
        # that was, so "next" does not go back up to the rows above it.
        window.history_list.setCurrentRow(5)
        with patch.object(window.video_opener, "open", return_value=True) as opened:
            window.history_play_button.click()
        sequence = opened.call_args.kwargs["sequence"]
        # Its place in the frozen list, which has fewer entries than History
        # has rows because some rows were left out of it.
        self.assertEqual([target.path for target in sequence.targets], [recording, moved, recording])
        self.assertEqual(sequence.opened_at, 2)
        self.assertEqual(next_target(sequence, recording, ()), (None, "end_of_list"))

        window.history_list.setCurrentRow(2)
        with (
            patch.object(QMessageBox, "information") as told,
            patch.object(window.video_opener, "open") as opened,
        ):
            window.history_play_button.click()
        told.assert_called_once()
        opened.assert_not_called()

    def _synthetic_moments_package(self) -> tuple[Path, Path]:
        """A package of invented moments in one invented recording: (package, recording)."""

        # Never created: working out what a moment plays must not touch the disk.
        recording = self.root / "Captured Sessions" / "synthetic-session-one.mkv"
        root = self.root / "review" / "codex-evidence-package"
        shutil.copytree(FIXTURE_PACKAGE, root)
        with_path = _session_candidate("ticket-001", 5, "synthetic overlay sector colors reset")
        with_path.update(source_filename=recording.name, source_path=str(recording))
        # An older record: no path and no seconds, only the source's id and the
        # "HH:MM:SS.mmm" text.
        text_only = _session_candidate("ticket-002", 25, "synthetic overlay sector colors reset again")
        text_only["source_filename"] = recording.name
        del text_only["timestamp_start_seconds"], text_only["marker_timestamp_seconds"]
        unknown = _session_candidate("ticket-003", 40, "synthetic pit board text is too small")
        unknown.update(source_filename="synthetic-session-unknown.mkv", source_id="not-in-this-package")
        # For another project than the rest, so it joins no proposed thread and
        # the list of unassigned mentions has a moment that can be played.
        on_its_own = _session_candidate("ticket-004", 55, "synthetic fuel readout flickers at night")
        on_its_own.update(source_filename=recording.name, likely_target_repo="owner/another-repo")
        review_item = {
            "review_id": "review-001",
            "source_id": "session",
            "source_filename": recording.name,
            "timestamp_start_seconds": 1080,
            "marker_timestamp_seconds": 1200,
            "marker_timestamp": "00:20:00.000",
            "reason": "synthetic remark that needs a look",
        }
        candidates = [with_path, text_only, unknown, on_its_own]
        (root / "CANDIDATE_TICKETS.json").write_text(json.dumps({"candidates": candidates}), encoding="utf-8")
        (root / "REVIEW_NEEDED.json").write_text(json.dumps({"review_needed": [review_item]}), encoding="utf-8")
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        manifest["sources"] = [
            {"source_id": "session", "source_filename": recording.name, "source_path": str(recording)}
        ]
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        write_session_review_artifacts(
            root,
            build_session_review(candidates=candidates, review_needed=[review_item], marker_audit={}),
        )
        return root, recording

    def test_video_moments_resolve_to_the_recording_the_start_and_the_package(self) -> None:
        root, recording = self._synthetic_moments_package()
        window = self._window()
        window.load_package(root)
        package_root = window.current_package.root

        def resolve(view, resolver, item_id: str) -> list[tuple[Path, float, Path | None]]:
            model = view.model()
            index = next(
                model.index(row, 0)
                for row in range(model.rowCount())
                if model.index(row, 0).data(Qt.ItemDataRole.UserRole) == item_id
            )
            return [(target.path, target.start_seconds, target.package_root) for target in resolver(index)]

        expected = {
            # The start of the stretch its evidence covers (marker 300 s less 30).
            "ticket-001": [(recording, 270.0, package_root)],
            # Path from the package's source list, start from "00:25:00.000".
            "ticket-002": [(recording, 1500.0, package_root)],
            # The package does not say which recording this is in.
            "ticket-003": [],
            "ticket-004": [(recording, 3270.0, package_root)],
            # A review-needed item starts at the remark, on both pages.
            "review-001": [(recording, 1200.0, package_root)],
        }
        for item_id, targets in expected.items():
            with self.subTest(item=item_id):
                self.assertEqual(
                    resolve(window.candidate_list, window._candidate_play_targets, item_id), targets
                )
                self.assertEqual(
                    resolve(window.session_timeline_table, window._mention_play_targets, item_id), targets
                )

        self.assertTrue(window.current_package.proposed_threads)
        thread = window._thread_play_targets(window.session_threads_list.model().index(0, 0))
        self.assertGreaterEqual(len(thread), 2)
        self.assertTrue(all(target.package_root == package_root for target in thread))

        # The two visible buttons follow the selection.
        window.candidate_list.setCurrentRow(0)
        window._set_current_session_mention("ticket-001")
        self.assertTrue(window.play_candidate_button.isEnabled())
        self.assertTrue(window.session_action_buttons["play"].isEnabled())
        with patch.object(window.video_opener, "open", return_value=True) as opened:
            window.play_candidate_button.click()
            window.session_action_buttons["play"].click()
        self.assertEqual(
            [(call.args[0].path, call.args[0].start_seconds) for call in opened.call_args_list],
            [(recording, 270.0), (recording, 270.0)],
        )
        window.candidate_list.setCurrentRow(2)
        window._set_current_session_mention("ticket-003")
        for button in (window.play_candidate_button, window.session_action_buttons["play"]):
            self.assertFalse(button.isEnabled())
            self.assertIn("does not say which recording", button.toolTip())

    def test_video_every_attached_view_plays_from_its_own_clicks(self) -> None:
        """Every ``attach`` line in the main window is live.

        The resolvers have tests of their own. This one goes through each
        view's own double-click and right-click, the way the operator does, so
        taking an attach line out fails here instead of Play quietly going
        missing from a page.
        """

        root, recording = self._synthetic_moments_package()
        window = self._window()
        window.load_package(root)
        output = self.root / "review-one"
        window.records.import_legacy_runs([
            {
                "timestamp": "2026-09-20 14:05",
                "workflow_title": "Codex Evidence",
                "status": "succeeded",
                "source": str(recording),
                "output": str(output),
            }
        ])
        window.refresh_history()
        window.refresh_home()
        # The source list is only on screen for the evidence workflow, on the
        # source step, so that is where the operator is when they click it.
        window.use_recommended_settings("3")
        window.wizard_steps.setCurrentRow(1)
        window.audio_expected_sources = [str(recording)]
        window._refresh_audio_batch_table()

        first_entries: list[str] = []

        def choose_the_first_entry(menu, _where) -> None:
            # Stands in for showing the menu: nothing pops up, and the first
            # entry is chosen as the operator would. Several moments on one
            # row get a named entry each, with the play entries inside it.
            entry = menu.actions()[0]
            if entry.menu() is not None:
                entry = entry.menu().actions()[0]
            first_entries.append(entry.text())
            entry.trigger()

        def first_playable(name: str, view, resolver):
            model = view.model()
            for row in range(model.rowCount()):
                if resolver(model.index(row, 0)):
                    return model.index(row, 0)
            self.fail(f"the synthetic package gives {name} nothing to play")

        def right_click(view, index) -> None:
            # The event a mouse gives the list, aimed at the part of the row
            # that is on screen; it fails if the row is hidden or covered.
            right_click_row(view, index)

        moment_views = (
            ("Evidence items", window.candidate_list, window._candidate_play_targets),
            ("Complete timeline", window.session_timeline_table, window._mention_play_targets),
            ("Proposed ticket threads", window.session_threads_list, window._thread_play_targets),
            ("Unassigned mentions", window.session_unassigned_list, window._mention_play_targets),
        )
        run_views = (
            ("History", window.history_list),
            ("Recent runs", window.home_recent_list),
        )
        with (
            patch.object(window.video_opener, "open", return_value=True) as opened,
            patch.object(window.video_opener, "_exec_menu", side_effect=choose_the_first_entry),
            patch.object(window, "_open_path", return_value=True) as opened_by_windows,
        ):
            for name, view, resolver in moment_views:
                index = first_playable(name, view, resolver)
                bring_to_front(view)
                with self.subTest(view=name, click="double"):
                    opened.reset_mock()
                    double_click_row(view, index)
                    opened.assert_called_once()
                    self.assertEqual(opened.call_args.args[0].path, recording)
                    self.assertGreater(opened.call_args.args[0].start_seconds, 0)
                    # A moment is not one of a list of recordings.
                    self.assertIsNone(opened.call_args.kwargs["sequence"])
                with self.subTest(view=name, click="right"):
                    opened.reset_mock()
                    first_entries.clear()
                    right_click(view, index)
                    self.assertEqual(first_entries, ["Play this moment"])
                    opened.assert_called_once()
                    self.assertEqual(opened.call_args.args[0].path, recording)

            for name, view in (*run_views, ("New review sources", window.audio_batch_table)):
                index = view.model().index(0, 0)
                bring_to_front(view)
                with self.subTest(view=name, click="right"):
                    opened.reset_mock()
                    first_entries.clear()
                    right_click(view, index)
                    self.assertEqual(first_entries, ["Play"])
                    opened.assert_called_once()
                    self.assertEqual(opened.call_args.args[0].path, recording)
                with self.subTest(view=name, click="double"):
                    # Double-click plays here too (125): these rows are
                    # recordings, and the approved design plays them on click
                    # from anywhere one appears.
                    opened.reset_mock()
                    opened_by_windows.reset_mock()
                    double_click_row(view, index)
                    opened.assert_called_once()
                    self.assertEqual(opened.call_args.args[0].path, recording)
                    opened_by_windows.assert_not_called()

    def test_video_a_real_double_click_plays_from_every_list_that_shows_a_recording(self) -> None:
        """Mouse events on each list, with its page in front (125).

        The lists here had right-click Play but no double-click to play: the
        Find my bug reports table shown while a run is going, Queue / Progress,
        History and Home's recent runs. The two that are redrawn while the
        operator watches them are also double-clicked across a redraw.
        """

        window = self._window()
        sessions = self.root / "Captured Sessions"
        sessions.mkdir()
        recording = sessions / "synthetic-session-one.mkv"
        second = sessions / "synthetic-session-two.mkv"
        for path in (recording, second):
            path.write_bytes(b"not really video")
        output = self.root / "review-one"
        many = self.root / "review-many"
        (many / "codex-evidence-package").mkdir(parents=True)
        (many / "codex-evidence-package" / "manifest.json").write_text(
            json.dumps({"sources": [{"source_path": str(recording)}, {"source_path": str(second)}]}),
            encoding="utf-8",
        )
        nothing_to_play = self.root / "review-folders"

        def run(source: str, folder: Path) -> dict[str, str]:
            return {
                "timestamp": "2026-09-20 14:05",
                "workflow_title": "Find my bug reports",
                "status": "succeeded",
                "source": source,
                "output": str(folder),
            }

        window.records.import_legacy_runs([
            run(str(recording), output),
            run("2 recordings", many),
            run("Configured folders", nothing_to_play),
        ])
        window.refresh_history()
        window.refresh_home()
        page = window.bug_reports_page
        page.add_recordings([recording, second])
        page._render_working_table()
        window.progress_queue_items = [str(recording), str(second)]
        window._refresh_progress_queue_table()

        lists = (
            ("Find my bug reports, while a run is going", page.working_table),
            ("Find my bug reports, choosing", page.table),
            ("Queue / Progress", window.progress_queue_table),
            ("History", window.history_list),
            ("Home, recent runs", window.home_recent_list),
        )
        redrawn = {
            # Redrawn on every line the backend prints, and on every progress update.
            "Find my bug reports, while a run is going": page._render_working_table,
            "Queue / Progress": window._refresh_progress_queue_table,
            "Find my bug reports, choosing": page._render_choose_table,
        }
        menus: list[list[str]] = []

        def choose_the_first_recording(menu, _where) -> None:
            # Stands in for showing the menu, and picks what the operator would.
            menus.append([action.text() for action in menu.actions()])
            menu.actions()[0].menu().actions()[0].trigger()

        with (
            patch.object(window.video_opener, "open", return_value=True) as opened,
            patch.object(window.video_opener, "_exec_menu", side_effect=choose_the_first_recording),
            patch.object(window, "_open_path_system", return_value=True) as handed_to_windows,
        ):
            for name, view in lists:
                bring_to_front(view)
                with self.subTest(view=name):
                    opened.reset_mock()
                    double_click_row(view, view.model().index(0, 0))
                    opened.assert_called_once()
                    self.assertEqual(opened.call_args.args[0].path, recording)
                    handed_to_windows.assert_not_called()
                if name in redrawn:
                    with self.subTest(view=name, across="a redraw between the two clicks"):
                        opened.reset_mock()
                        double_click_row_with_a_gap(view, view.model().index(1, 0), redrawn[name])
                        opened.assert_called_once()
                        self.assertEqual(opened.call_args.args[0].path, second)

            for view in (window.history_list, window.home_recent_list):
                bring_to_front(view)
                with self.subTest(view=view.objectName() or "runs", row="a run of two recordings"):
                    # It asks which one, as the Play recording button does,
                    # instead of always opening the first.
                    opened.reset_mock()
                    menus.clear()
                    double_click_row(view, view.model().index(1, 0))
                    self.assertEqual(menus, [["synthetic-session-one.mkv", "synthetic-session-two.mkv"]])
                    opened.assert_called_once()
                    self.assertEqual(opened.call_args.args[0].path, recording)
                with self.subTest(view=view.objectName() or "runs", row="a run with nothing to play"):
                    # Double-click still does what it always did here: the
                    # run's output folder.
                    opened.reset_mock()
                    handed_to_windows.reset_mock()
                    double_click_row(view, view.model().index(2, 0))
                    opened.assert_not_called()
                    handed_to_windows.assert_called_once_with(nothing_to_play)

    def test_video_history_and_home_menus_still_open_the_output_folder_and_log(self) -> None:
        """Double-click plays now, so the run's own folder is one right-click away (125)."""

        window = self._window()
        recording = self.root / "Captured Sessions" / "synthetic-session-one.mkv"
        output = self.root / "review-one"
        log = self.root / "logs" / "synthetic-run.log"
        window.records.import_legacy_runs([
            {
                "timestamp": "2026-09-20 14:05",
                "workflow_title": "Codex Evidence",
                "status": "succeeded",
                "source": str(recording),
                "output": str(output),
                "log": str(log),
            },
            {
                "timestamp": "2026-09-20 15:05",
                "workflow_title": "Codex Evidence",
                "status": "failed",
                "source": "Configured folders",
                "output": str(self.root / "review-two"),
                "log": str(log),
            },
        ])
        window.refresh_history()
        window.refresh_home()
        entries: list[list[str]] = []

        def open_folder_entry(menu, _where) -> None:
            entries.append([action.text() for action in menu.actions() if not action.isSeparator()])
            next(action for action in menu.actions() if action.text() == "Open output folder").trigger()

        for view in (window.history_list, window.home_recent_list):
            bring_to_front(view)
            with (
                patch.object(window.video_opener, "_exec_menu", side_effect=open_folder_entry),
                patch.object(window, "_open_path", return_value=True) as opened_path,
            ):
                entries.clear()
                right_click_row(view, view.model().index(0, 0))
                self.assertEqual(entries[0][0], "Play")
                self.assertEqual(entries[0][-2:], ["Open output folder", "Open log"])
                opened_path.assert_called_once_with(output)
                # A run with nothing to play still gets its folder entries,
                # rather than no menu at all.
                entries.clear()
                opened_path.reset_mock()
                right_click_row(view, view.model().index(1, 0))
                self.assertEqual(entries, [["Open output folder", "Open log"]])

    def test_the_video_is_paused_before_the_inbox_track_choice_plays(self) -> None:
        """Two things sounding at once cannot be judged (125).

        136 (Wave 8): the wizard's own preview player is gone, so the built-in player is the
        Workbench's only player. The Review Media Inbox "which track is you" dialog still pauses it
        before the dialog's Play opens it on the track to judge.
        """

        window = self._window()
        events: list[str] = []
        source = self.root / "synthetic-session-one.mkv"
        source.write_bytes(b"not really video")

        class AudioChoiceDialog:
            def __init__(self, *_args, **_kwargs) -> None:
                self.diagnostic = SimpleNamespace(connect=lambda _callback: None)

            def exec(self) -> int:
                events.append("sound")
                return int(QDialog.DialogCode.Rejected)

        def paused() -> None:
            events.append("video paused")

        with (
            patch.object(window.video_opener, "yield_audio", side_effect=paused),
            patch("media_manglers_workbench.app.ReviewInboxAudioChoiceDialog", AudioChoiceDialog),
        ):
            window._handle_review_inbox_process_decision(
                {
                    "audio_choice": {"source_path": str(source), "token": "synthetic-audio-token"},
                    "continuation": "synthetic-continuation",
                }
            )
        self.assertEqual(events, ["video paused", "sound"])

    def test_video_player_settings_tab_keeps_dependencies_at_index_two_and_round_trips(self) -> None:
        settings_path = self.root / "settings.json"
        settings_path.write_text(
            json.dumps(
                {
                    "schemaVersion": SETTINGS_SCHEMA_VERSION,
                    "settings": {
                        "log_folder": str(self.root / "logs"),
                        "temp_folder": str(self.root / "temp"),
                        # A hand-edited file: not one of the three players.
                        "video_player": "betamax",
                        "video_autoplay": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        window = self._window()
        tabs = window.settings_tabs
        self.assertEqual(
            [tabs.tabText(index) for index in range(tabs.count())],
            [
                "General / Startup",
                "Profiles",
                "Dependencies",
                "Video player",
                "Build information",
                "Advanced / Diagnostics",
                # 150 Phase 3: the AI Video Editor's own tab, added last.
                "AI Video Editor",
            ],
        )
        panel = window.video_player_settings
        self.assertIsInstance(panel, VideoPlayerSettingsPanel)
        self.assertIs(tabs.widget(3), panel)
        window.open_dependency_setup()
        self.assertEqual(tabs.tabText(tabs.currentIndex()), "Dependencies")

        # An unknown stored player shows, and saves, as the built-in player.
        self.assertEqual(panel.values()["video_player"], "internal")
        self.assertFalse(panel.values()["video_autoplay"])

        panel.player_combo.setCurrentIndex(panel.player_combo.findData("system"))
        panel.autoplay_checkbox.setChecked(True)
        # 237: Save settings says "Saved a moment ago" beside the button, not in a pop-up; the longer
        # sentence is its tooltip. Not "Startup choices": the Video player tab takes effect at once.
        with patch.object(QMessageBox, "information") as told:
            click(window.settings_save_button)
        told.assert_not_called()
        self.assertEqual(window.settings_save_feedback.text(), "Saved a moment ago")
        self.assertIn("Settings saved.", window.settings_save_button.toolTip())
        self.assertNotIn("Startup choices", window.settings_save_button.toolTip())
        self.assertEqual(window.app_settings["video_player"], "system")
        self.assertTrue(window.app_settings["video_autoplay"])
        persisted = load_settings(settings_path, repo_root=str(REPO_ROOT))
        self.assertEqual(persisted["video_player"], "system")
        self.assertTrue(persisted["video_autoplay"])
        self.assertEqual(persisted["video_player_vlc_path"], "")

        # Re-reading the settings (an imported bundle does this) shows them again.
        window.app_settings.update(video_player="internal", video_autoplay=False)
        window._load_settings_controls()
        self.assertEqual(panel.values()["video_player"], "internal")
        self.assertFalse(panel.values()["video_autoplay"])

    def test_video_close_releases_the_recording_before_any_refusal(self) -> None:
        window = self._window()
        recording = self.root / "synthetic-session-one.mkv"
        recording.write_bytes(b"not really video")

        # No player window yet, and a recording still being looked for on a
        # drive that is slow to answer: the refusal is said in a message, as
        # there is no player window to say it in.
        with (
            patch.object(window.video_opener, "shutdown", return_value=False),
            patch.object(QMessageBox, "information") as told,
        ):
            self.assertFalse(window.close())
        self.assertTrue(window.isVisible())
        told.assert_called_once()
        self.assertIn("Close the Workbench again in a moment", told.call_args.args[2])

        _StubReviewPlayerWindow.instances = []
        with patch("media_manglers_workbench.video_open.ReviewPlayerWindow", _StubReviewPlayerWindow):
            self.assertTrue(window.video_opener.open(PlayTarget(path=recording)))
            # The disk is asked where the recording is away from this thread,
            # so the player window follows a moment after open() returns.
            self._wait_until(lambda: bool(_StubReviewPlayerWindow.instances))
        stub = _StubReviewPlayerWindow.instances[-1]
        self.assertIs(window.video_opener.player_window, stub)
        self.assertEqual(stub.source, str(recording))
        # 136 (Wave 8): the main window has no sound output or player of its own; the built-in player
        # is the one player.
        self.assertFalse(hasattr(window, "audio_output"))
        self.assertFalse(hasattr(window, "audio_player"))

        def refuse(*_args, **_kwargs) -> QMessageBox.StandardButton:
            stub.events.append("asked")
            return QMessageBox.StandardButton.No

        # The first of the paths that refuse to close: a review is running and
        # the operator says no. The recording is let go of before the question.
        window.runner_thread = object()
        try:
            with patch.object(QMessageBox, "question", side_effect=refuse):
                self.assertFalse(window.close())
        finally:
            window.runner_thread = None
        self.assertTrue(window.isVisible())
        self.assertEqual(stub.events, ["open", "release", "asked"])
        self.assertEqual(stub.source, "")

        # A player that is still finishing refuses the close, and says so in
        # its own window: whichever page this window shows, that one is seen.
        stub.events.clear()
        stub.shutdown_result = False
        window._closing_after_smoke = True
        review_state = window.progress_state_banner.text()
        self.assertFalse(window.close())
        self.assertTrue(window.isVisible())
        self.assertEqual(
            stub.events,
            [
                "release",
                "shutdown",
                "note: The built-in player is still finishing. Close the Workbench again in a moment.",
            ],
        )
        # The Progress page's banner is the state of the review, nothing else.
        self.assertEqual(window.progress_state_banner.text(), review_state)

        # Closing the player is what writes its window position and volume
        # into the settings, so they are saved after it, never before.
        save_app_settings = window.save_app_settings

        def save_and_say_so() -> None:
            stub.events.append("save")
            save_app_settings()

        stub.events.clear()
        stub.shutdown_result = True
        with patch.object(window, "save_app_settings", side_effect=save_and_say_so):
            self.assertTrue(window.close())
        self.assertEqual(stub.events, ["release", "shutdown", "close", "save"])
        self.assertIsNone(window.video_opener.player_window)
        self.window = None


if __name__ == "__main__":
    unittest.main()
