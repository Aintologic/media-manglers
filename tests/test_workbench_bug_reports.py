from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QListWidget, QMenu  # noqa: E402

from media_manglers_workbench import bug_reports  # noqa: E402
from media_manglers_workbench.app import PAGE_NAMES, WorkbenchWindow  # noqa: E402
from media_manglers_workbench.bug_reports import (  # noqa: E402
    PAGE_NAME,
    PLAY_LIST_LABEL,
    BugReportsPage,
    RecordingRow,
    RunSummary,
    build_bug_report_settings,
    newest_recordings,
    results_headline,
    summarize_package,
)
from media_manglers_workbench.play_targets import next_target  # noqa: E402
from media_manglers_workbench.resources import DependencyStatus, RuntimeResources  # noqa: E402
from media_manglers_workbench.runner import RunnerResult  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: E402
from media_manglers_workbench.theme import status_color  # noqa: E402

# 105: the one status colour rule; 237 moved its hex values to the UI rulebook tokens.
GREEN = status_color("completed").name()
RED = status_color("failed").name()
AMBER = status_color("completed with problems").name()

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PACKAGE = REPO_ROOT / "tests" / "fixtures" / "workbench" / "evidence_package"


def _resources() -> RuntimeResources:
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


class ScriptedBackend:
    """Stands in for Video Mangler.ps1: writes a package and prints its log."""

    instances: list["ScriptedBackend"] = []
    write_package = True
    exit_code = 0
    lines: list[str] = []
    visuals = {"moment_count": 3, "frame_count": 24, "clip_count": 3, "review_video_count": 1}

    def __init__(self) -> None:
        self.argv: list[str] = []
        ScriptedBackend.instances.append(self)

    def cancel(self) -> None:
        return None

    def run(self, command, on_log=None, *, cwd=None) -> RunnerResult:
        self.argv = list(command.argv)
        output = Path(self.argv[self.argv.index("-OutputFolder") + 1])
        if self.write_package:
            package = output / "codex-evidence-package"
            shutil.copytree(FIXTURE_PACKAGE, package)
            manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
            manifest["sources"] = [
                {"source_id": "a", "source_filename": "a.mkv", "status": "completed",
                 "transcript_quality": {"quality_status": "usable"}},
                {"source_id": "b", "source_filename": "b.mkv", "status": "no_narration",
                 "transcript_quality": {"quality_status": "no_narration_found"}},
            ]
            (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (package / "NARRATION_EVIDENCE.json").write_text(json.dumps(self.visuals), encoding="utf-8")
        stdout: list[str] = []
        for line in self.lines:
            stdout.append(line)
            if on_log:
                on_log("stdout", line)
        status = "succeeded" if self.exit_code == 0 else "failed"
        return RunnerResult(status=status, exit_code=self.exit_code, stdout_lines=stdout,
                            error="" if status == "succeeded" else stdout[-1] if stdout else "failed")


def _menu_texts(menu: QMenu) -> list[str]:
    return [action.text() for action in menu.actions() if not action.isSeparator()]


def _menu_entry(menu: QMenu, text: str):
    return next(action for action in menu.actions() if action.text() == text)


# What the opener puts at the top of a menu for one recording (125), and what
# the choose table's menu held before that. Every one of the old entries stays.
PLAY_ENTRIES = ["Play", "Play with", "Show in folder"]
TRACK_MENU_BEFORE_125 = [
    "Find my voice automatically",
    *[f"Always use Track {track}" for track in range(1, 9)],
    "Remove from this list",
    "Never use this recording",
]


class _HostWithoutAnOpener:
    """The least a host can be: what a stand-in host in another test looks like."""

    def __init__(self) -> None:
        self.app_settings: dict[str, object] = {}

    def open_current_log(self) -> None:
        return None


PROGRESS = 'MM_PROGRESS_V1 {"phase":"Transcription","source_name":"%s","activity":"%s"}'
OUTCOME = (
    'MM_PROGRESS_V1 {"schema":"MM_PROGRESS_V1","phase":"Transcription","source_name":"%s",'
    '"source_state":"%s","source_terminal":%s,"activity":"Transcription %s: %s"}'
)
RENDER = (
    'MM_PROGRESS_V1 {"schema":"MM_PROGRESS_V1","phase":"Rich rendering","source_name":"%s",'
    '"progress_kind":"work_units","completed":1,"total":2,"activity":"Rendering frame batch"}'
)


class BugReportsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window: WorkbenchWindow | None = None
        ScriptedBackend.instances = []
        ScriptedBackend.write_package = True
        ScriptedBackend.exit_code = 0
        ScriptedBackend.lines = []
        ScriptedBackend.visuals = {"moment_count": 3, "frame_count": 24, "clip_count": 3, "review_video_count": 1}
        self.recordings = self.root / "recordings"
        self.recordings.mkdir()
        for name in ("a.mkv", "b.mkv"):
            (self.recordings / name).write_bytes(b"not really video")

    def tearDown(self) -> None:
        if self.window:
            self.window._closing_after_smoke = True
            self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def _window(self) -> WorkbenchWindow:
        settings_path = self.root / "settings.json"
        repo_map = self.root / "repo-map.json"
        repo_map.write_text(json.dumps({"repos": {"owner/one": {}, "owner/two": {}}}), encoding="utf-8")
        settings_path.write_text(
            json.dumps(
                {
                    "schemaVersion": SETTINGS_SCHEMA_VERSION,
                    "settings": {
                        "log_folder": str(self.root / "logs"),
                        "temp_folder": str(self.root / "temp"),
                        "output_folder": str(self.root / "out"),
                        "review_source_folders": str(self.recordings),
                        "evidence_repo_map_path": str(repo_map),
                    },
                }
            ),
            encoding="utf-8",
        )
        self.window = WorkbenchWindow(
            settings_path=settings_path,
            profiles_dir=self.root / "profiles",
            runner_factory=ScriptedBackend,
            resources=_resources(),
        )
        self.window.show()
        self.app.processEvents()
        return self.window

    def _wait_for_results(self, page) -> None:
        deadline = time.monotonic() + 10
        while page.running and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.app.processEvents()
        self.assertFalse(page.running)
        self.assertIsNone(page.host.runner_thread)

    def test_front_door_is_on_home_and_in_navigation(self) -> None:
        window = self._window()
        self.assertEqual(PAGE_NAMES[1], PAGE_NAME)
        self.assertTrue(window.nav_buttons[PAGE_NAME].isVisible())
        # 152 (Wave 6, 220): the Inbox is back on the rail, below Find my bug reports, which stays
        # the front door (second button, the hero on Home).
        inbox = window.nav_buttons["Review Media Inbox"]
        self.assertTrue(inbox.isVisible())
        self.assertGreater(inbox.y(), window.nav_buttons[PAGE_NAME].y())
        window.home_bug_reports_button.click()
        self.assertIs(window.page_stack.currentWidget(), window.pages[PAGE_NAME])

    def test_choose_start_and_finish_on_results_with_prompt(self) -> None:
        window = self._window()
        page = window.bug_reports_page
        self.assertFalse(page.start_button.isEnabled())
        page.add_recordings([self.recordings / "a.mkv", self.recordings / "b.mkv", self.recordings / "a.mkv"])
        self.assertEqual(len(page.rows), 2)
        self.assertTrue(page.start_button.isEnabled())
        self.assertIn("2 projects", page.projects_label.text())
        # 196: a recording with no narration is reported on its own and is not a problem.
        ScriptedBackend.exit_code = 0
        ScriptedBackend.lines = [
            "  Listening to every audio track to find your voice: a.mkv",
            "  Voice found on Track 5.",
            PROGRESS % ("a.mkv", "Transcription completed: a.mkv"),
            "  Listening to every audio track to find your voice: b.mkv",
            "  No narration found in this recording: No track carries isolated speech.",
            PROGRESS % ("b.mkv", "Transcription no_narration: b.mkv"),
            "Recordings with no narration, so nothing to report from them:",
            "  - b.mkv: no narration found - your microphone was silent in this recording",
        ]
        page.start()
        self._wait_for_results(page)

        argv = ScriptedBackend.instances[-1].argv
        self.assertIn("-CodexEvidencePackage", argv)
        input_path = Path(argv[argv.index("-InputPath") + 1])
        self.assertEqual(input_path.suffix, ".mmlist")
        self.assertIn(str(self.recordings / "a.mkv"), input_path.read_text(encoding="utf-8"))
        self.assertEqual(argv[argv.index("-EvidenceHandoffMode") + 1], "Local")
        self.assertNotIn("-EvidenceAudioStreamSelectionConfirmed", argv)

        self.assertEqual(page.stack.currentIndex(), 2)
        self.assertIn("1 of 2 recordings had narration; 1 had none", page.results_headline.text())
        self.assertNotIn("could not be used", page.results_headline.text())
        self.assertIn("your voice was on Track 5", page.results_detail.text())
        self.assertIn("3 moments where you were talking, with 24 screenshots", page.results_detail.text())
        self.assertIn("left, center and right monitor", page.results_detail.text())
        self.assertIn("3 short video clips", page.results_detail.text())
        self.assertIn("1 small review video", page.results_detail.text())
        self.assertIn("b.mkv: no narration found", page.results_detail.text())
        self.assertTrue(page.copy_claude_button.isEnabled())
        page.copy_claude_button.click()
        copied = QApplication.clipboard().text()
        self.assertIn(str(page.summary.package_root), copied)
        self.assertIn("Prompt for Claude Code copied", page.copied_label.text())

    def test_narration_track_setting_reaches_the_backend_and_the_result_says_what_decided(self) -> None:
        # 196: the operator sets Track 2 to Narration and Tracks 3, 5 and 6 to Never narration on
        # the Settings page, by clicking, and saves. The run hands that to the backend, and the
        # track shown says what decided it.
        from tests.qt_input import bring_to_front

        window = self._window()
        panel = window.settings_track_roles
        bring_to_front(panel)
        window.show()
        self.app.processEvents()

        def choose(combo, text: str) -> None:
            # Click the box to open its list, then pick the entry with the keyboard, as the
            # operator would (an offscreen popup does not take a mouse click on an entry).
            QTest.mouseClick(combo, Qt.MouseButton.LeftButton)
            self.app.processEvents()
            view = combo.view()
            self.assertTrue(view.isVisible(), "the list did not open")
            for _step in range(combo.findText(text) - combo.currentIndex()):
                QTest.keyClick(view, Qt.Key.Key_Down)
            QTest.keyClick(view, Qt.Key.Key_Return)
            self.app.processEvents()
            self.assertEqual(combo.currentText(), text)

        self.assertEqual([combo.currentText() for combo in panel.combos.values()], ["Auto"] * 6)
        choose(panel.combos[2], "Narration")
        for number in (3, 5, 6):
            choose(panel.combos[number], "Never narration")
        save = next(button for button in window.findChildren(bug_reports.QPushButton) if button.text() == "Save settings")
        with patch("media_manglers_workbench.app.QMessageBox.information"):
            QTest.mouseClick(save, Qt.MouseButton.LeftButton)
        saved = json.loads((self.root / "settings.json").read_text(encoding="utf-8"))["settings"]
        self.assertEqual(saved["evidence_track_roles"], "2=narration,3=never,5=never,6=never")

        page = window.bug_reports_page
        page.add_recordings([self.recordings / "a.mkv", self.recordings / "b.mkv"])
        ScriptedBackend.lines = [
            "  Listening to every audio track to find your voice: a.mkv",
            "  Voice found on Track 2 (from track name).",
            PROGRESS % ("a.mkv", "Transcription completed: a.mkv"),
            "  Listening to every audio track to find your voice: b.mkv",
            "  Voice found on Track 2 (from your setting).",
            PROGRESS % ("b.mkv", "Transcription completed: b.mkv"),
        ]
        page.start()
        self.app.processEvents()
        self._wait_for_results(page)
        argv = ScriptedBackend.instances[-1].argv
        self.assertEqual(argv[argv.index("-EvidenceTrackRoles") + 1], "2=narration,3=never,5=never,6=never")
        cells = [page.working_table.item(row, 1).text() for row in range(page.working_table.rowCount())]
        self.assertEqual(cells, ["Track 2 (from track name)", "Track 2 (from your setting)"])
        self.assertIn("a.mkv: your voice was on Track 2 (from track name).", page.results_detail.text())
        self.assertIn("b.mkv: your voice was on Track 2 (from your setting).", page.results_detail.text())
        # The player is told the same when a recording is played from the results.
        target = page._play_target(page.rows[0], None)
        self.assertEqual((target.voice_track, target.voice_source), (2, "from track name"))

    def test_every_track_on_auto_sends_no_track_setting(self) -> None:
        window = self._window()
        page = window.bug_reports_page
        page.add_recordings([self.recordings / "a.mkv"])
        ScriptedBackend.lines = ["  Voice found on Track 2 (auto-detected)."]
        page.start()
        self._wait_for_results(page)
        self.assertNotIn("-EvidenceTrackRoles", ScriptedBackend.instances[-1].argv)

    def test_run_shows_on_progress_history_and_log_like_any_review(self) -> None:
        window = self._window()
        page = window.bug_reports_page
        page.add_recordings([self.recordings / "a.mkv", self.recordings / "b.mkv"])
        ScriptedBackend.lines = [
            PROGRESS % ("a.mkv", "Transcription completed: a.mkv"),
        ]
        page.start()
        # While it runs, Queue / Progress lists the recordings and the stage.
        self.assertIsNotNone(window.runner_thread)
        self.assertEqual(window.progress_workflow.text(), "Find my bug reports")
        self.assertEqual(window.progress_queue.text(), "2")
        self.assertEqual(
            window.progress_queue_items,
            [str((self.recordings / "a.mkv").resolve()), str((self.recordings / "b.mkv").resolve())],
        )
        self.assertTrue(window.cancel_button.isEnabled())
        self.assertFalse(window.start_review_button.isEnabled())
        page.full_progress_button.click()
        self.assertIs(window.page_stack.currentWidget(), window.pages["Queue / Progress"])
        self._wait_for_results(page)

        # Machine progress records stay out of the on-screen log but are in the file.
        self.assertNotIn("MM_PROGRESS_V1", window.progress_log.toPlainText())
        self.assertTrue(window.run_log_path.is_file())
        self.assertIn("Transcription completed: a.mkv", window.run_log_path.read_text(encoding="utf-8"))
        latest = window.recent_runs()[0]
        self.assertEqual(latest["workflow_title"], "Find my bug reports")
        self.assertEqual(latest["status"], "succeeded")
        self.assertEqual(latest["source"], "2 recordings")
        self.assertEqual(Path(latest["output"]), page.run_folder)
        self.assertEqual(latest["log"], str(window.run_log_path))
        self.assertTrue(window.history_list.item(0).text().endswith("2 recordings"))
        self.assertIn("ready for your AI agent", window.progress_completion_summary.text())
        # The operator's own output folder choice is left alone.
        self.assertEqual(window.app_settings["output_folder"], str(self.root / "out"))
        self.assertEqual(Path(window.app_settings["last_evidence_package"]), page.run_folder / "codex-evidence-package")

    def test_a_recording_with_no_narration_is_a_normal_outcome(self) -> None:
        # 196: a recording that simply has no narration is a correct result. The run is done,
        # not "completed with problems", and nothing about it is orange or red.
        window = self._window()
        page = window.bug_reports_page
        page.add_recordings([self.recordings / "a.mkv", self.recordings / "b.mkv"])
        ScriptedBackend.exit_code = 0
        ScriptedBackend.lines = [
            OUTCOME % ("a.mkv", "transcribed", "false", "completed", "a.mkv"),
            OUTCOME % ("b.mkv", "no_narration", "true", "no_narration", "b.mkv"),
            RENDER % "a.mkv",
            "Recordings with no narration, so nothing to report from them:",
            "  - b.mkv: no narration found - From your setting: Track 2 is your narration track, "
            "and it has no clear speech in this recording.",
        ]
        page.start()
        self._wait_for_results(page)

        self.assertEqual(page.summary.status, "complete")
        self.assertEqual(page.summary.problems, [])
        self.assertEqual(
            page.results_headline.text(),
            "Done. 1 of 2 recordings had narration; 1 had none, so nothing to report from it. "
            "Your narration is ready for your AI agent.",
        )
        self.assertEqual(page.results_headline.property("statusKind"), "completed")
        self.assertNotIn("Could not be used", page.results_detail.text())
        self.assertIn("No narration, so nothing to report:\n• b.mkv: no narration found", page.results_detail.text())
        self.assertFalse(page.fix_button.isVisible())
        self.assertTrue(page.copy_claude_button.isEnabled())
        # Progress and History say done, in green; the no-narration row is not orange.
        self.assertEqual(window.progress_state_banner.property("operatorState"), "completed")
        self.assertNotIn("problems", window.progress_state_banner.text().lower())
        rows = {window.progress_queue_table.item(row, 1).text(): window.progress_queue_table.item(row, 0)
                for row in range(window.progress_queue_table.rowCount())}
        self.assertEqual(rows["b.mkv"].text(), "No narration found")
        self.assertEqual(rows["b.mkv"].foreground().color().name(), GREEN)
        self.assertEqual(window.history_list.item(0).foreground().color().name(), GREEN)

    def test_a_damaged_whisper_model_and_the_slow_processor_fallback_are_said_on_screen(self) -> None:
        # 196: a run took 40 minutes because the speech model failed its checksum
        # and Whisper moved from the graphics card to the processor. Only the log said so.
        window = self._window()
        page = window.bug_reports_page
        page.add_recordings([self.recordings / "a.mkv"])
        self.assertFalse(page.whisper_notice.isVisibleTo(page))
        ScriptedBackend.lines = [
            "[2026-01-02 10:00:00] [WARN] [GPU->CPU] Local Whisper switched from GPU to CPU after 20s. GPU failure "
            "reason: Model has been downloaded but the SHA256 checksum does not not match. Please retry loading the "
            "model.. The helper restarted the full source on CPU, so the runtime budget was rebased from 45m 00s to "
            "3h 30m 00s; estimated total is now 1h 20m 00s.",
            OUTCOME % ("a.mkv", "transcribed", "false", "completed", "a.mkv"),
        ]
        page.start()
        self.app.processEvents()
        self._wait_for_results(page)
        model = Path.home() / ".cache" / "whisper" / "medium.pt"
        notice = page.whisper_notice.text()
        self.assertTrue(page.whisper_notice.isVisibleTo(page))
        self.assertIn("graphics card", notice)
        self.assertIn("much slower", notice)
        self.assertIn('speech model "medium" on this PC is damaged', notice)
        self.assertIn(f"rename {model} to medium.pt.bad", notice)
        self.assertIn(notice, page.results_detail.text())
        # A new run starts without the old notice.
        ScriptedBackend.lines = [OUTCOME % ("a.mkv", "transcribed", "false", "completed", "a.mkv")]
        page.start()
        self._wait_for_results(page)
        self.assertFalse(page.whisper_notice.isVisibleTo(page))

    def test_a_graphics_card_problem_is_said_on_screen_with_its_reason(self) -> None:
        window = self._window()
        page = window.bug_reports_page
        page.add_recordings([self.recordings / "a.mkv"])
        ScriptedBackend.lines = [
            "[2026-01-02 10:00:00] [WARN] [GPU->CPU] Local Whisper switched from GPU to CPU after 2m 00s. GPU failure "
            "reason: CUDA out of memory. Tried to allocate 20.00 MiB. The current timeout remains active because this "
            "run is using an explicit override.",
        ]
        page.start()
        self._wait_for_results(page)
        notice = page.whisper_notice.text()
        self.assertIn("graphics card could not be used", notice)
        self.assertIn("Reason: CUDA out of memory. Tried to allocate 20.00 MiB.", notice)
        self.assertIn("Settings > Dependencies", notice)
        self.assertNotIn("damaged", notice)

    def test_no_narration_in_every_recording_is_not_a_failure(self) -> None:
        window = self._window()
        page = window.bug_reports_page
        page.add_recordings([self.recordings / "b.mkv"])
        ScriptedBackend.write_package = False
        ScriptedBackend.exit_code = 1
        ScriptedBackend.lines = [
            OUTCOME % ("b.mkv", "no_narration", "true", "no_narration", "b.mkv"),
            "No usable narration transcript was produced, so no package was built. Recordings:",
            "  - b.mkv: no narration found - your microphone was silent in this recording",
        ]
        page.start()
        self._wait_for_results(page)
        self.assertEqual(page.summary.status, "nothing_usable")
        self.assertEqual(page.results_headline.property("statusKind"), "completed")
        self.assertEqual(window.progress_state_banner.property("operatorState"), "completed")
        self.assertFalse(page.fix_button.isVisible())
        # 199: Progress's Activity line, its Current step bar and its count say so too, not the
        # backend's exit code: a recording with no narration finished normally (1 of 1).
        self.assertEqual(window.progress_heartbeat.text(), "Complete")
        self.assertEqual(window.progress_bar.format(), "Complete")
        self.assertEqual(window.progress_bar.value(), window.progress_bar.maximum())
        self.assertEqual(window.progress_completed.text(), "1")
        self.assertEqual(window.progress_failed.text(), "0")
        # And History (and Home's recent runs) record it as completed, not failed.
        self.assertIn("|  completed  |", window.history_list.item(0).text())
        self.assertEqual(window.history_list.item(0).foreground().color().name(), GREEN)
        self.assertEqual(window.recent_runs()[0]["status"], "completed")

    def test_one_moment_is_one_moment(self) -> None:
        window = self._window()
        page = window.bug_reports_page
        page.add_recordings([self.recordings / "a.mkv"])
        ScriptedBackend.visuals = {"moment_count": 1, "frame_count": 4, "clip_count": 1, "review_video_count": 1}
        ScriptedBackend.lines = [OUTCOME % ("a.mkv", "transcribed", "false", "completed", "a.mkv")]
        page.start()
        self._wait_for_results(page)
        self.assertIn("1 moment where you were talking, with 4 screenshots", page.results_detail.text())
        self.assertIn("and 1 short video clip for your AI agent.", page.results_detail.text())

    def test_activity_says_complete_when_the_only_outcome_is_no_narration(self) -> None:
        # 199: the backend's own log line for a recording with no narration, as it prints it now.
        window = self._window()
        page = window.bug_reports_page
        page.add_recordings([self.recordings / "a.mkv", self.recordings / "b.mkv"])
        ScriptedBackend.lines = [
            OUTCOME % ("a.mkv", "transcribed", "false", "completed", "a.mkv"),
            "[2026-01-02 10:00:00] [INFO] No narration found for 'b.mkv': From your setting: Track 2 is your "
            "narration track, and it has no clear speech in this recording.",
            OUTCOME % ("b.mkv", "no_narration", "true", "no_narration", "b.mkv"),
            "Recordings with no narration, so nothing to report from them:",
            "  - b.mkv: no narration found - your microphone was silent in this recording",
        ]
        page.start()
        self._wait_for_results(page)
        self.assertEqual(window.progress_heartbeat.text(), "Complete")
        self.assertNotIn("warning", window.progress_heartbeat.text().lower())

    def test_partial_run_shows_each_recordings_real_outcome(self) -> None:
        """A 7-recording run: no-narration rows showed Completed, the last
        good recording showed Failed and History said failed (105)."""

        for name in ("c.mkv",):
            (self.recordings / name).write_bytes(b"not really video")
        window = self._window()
        page = window.bug_reports_page
        page.add_recordings([self.recordings / n for n in ("a.mkv", "b.mkv", "c.mkv")])
        ScriptedBackend.exit_code = 2
        ScriptedBackend.lines = [
            OUTCOME % ("a.mkv", "transcribed", "false", "completed", "a.mkv"),
            OUTCOME % ("b.mkv", "no_narration", "true", "no_narration", "b.mkv"),
            OUTCOME % ("c.mkv", "failed", "true", "failed", "c.mkv"),
            # Rendering the usable recording afterwards must not change any row.
            RENDER % "a.mkv",
            "Recordings that need attention:",
            "  - c.mkv: the microphone track could not be identified for this recording",
            "Recordings with no narration, so nothing to report from them:",
            "  - b.mkv: no narration found - your microphone was silent in this recording",
            "ERROR: 1 recording(s) could not be used; the package covers the rest.",
        ]
        page.start()
        self._wait_for_results(page)

        states = {Path(item).name: window.progress_item_states[item] for item in window.progress_queue_items}
        self.assertEqual(states, {"a.mkv": "completed", "b.mkv": "no_narration", "c.mkv": "failed"})
        labels = [window.progress_queue_table.item(row, 0).text() for row in range(3)]
        self.assertEqual(labels, ["Completed", "No narration found", "Failed"])
        # Colour coding: green done, red failed. No narration is a correct result, so it is not
        # orange (196).
        colours = [window.progress_queue_table.item(row, 0).foreground().color().name() for row in range(3)]
        self.assertEqual(colours, [GREEN, GREEN, RED])
        self.assertEqual(window.progress_state_banner.property("operatorState"), "completed_with_problems")
        self.assertEqual(window.overall_progress_bar.property("operatorState"), "attention")
        self.assertEqual(window.history_list.item(0).foreground().color().name(), AMBER)
        self.assertEqual(page.results_headline.property("statusKind"), "attention")
        # 199: b.mkv had no narration, a normal result, so it counts as completed with a.mkv.
        self.assertEqual(window.progress_completed.text(), "2")
        self.assertEqual(window.progress_failed.text(), "1")
        self.assertEqual(window.progress_remaining.text(), "0")
        self.assertIn("Completed with problems", window.progress_state_banner.text())
        self.assertEqual(window.progress_phase.text(), "Completed with problems")
        latest = window.recent_runs()[0]
        self.assertEqual(latest["status"], "completed with problems")
        self.assertIn("completed with problems", window.history_list.item(0).text())
        self.assertEqual(page.summary.status, "complete_with_problems")
        # 243: each recording's outcome is kept in the run, as the page's rows said it.
        kept = {Path(item["path"]).name: (item["outcome"], item["reported_by"])
                for item in window.records.run_items(latest["run_id"])}
        self.assertEqual(kept, {"a.mkv": ("completed", "Find my bug reports"),
                                "b.mkv": ("no_narration", "Find my bug reports"),
                                "c.mkv": ("failed", "Find my bug reports")})

    def test_a_stopped_run_keeps_what_each_recording_got_to(self) -> None:
        # 243: Stop used to leave nothing per recording; the rows' states are kept, and a recording the run
        # never got to is Cancelled.
        window = self._window()
        page = window.bug_reports_page
        page.add_recordings([self.recordings / n for n in ("a.mkv", "b.mkv")])
        run_id = window.records.open_run(kind="bug_reports", title="Find my bug reports",
                                         items=[str((self.recordings / n).resolve()) for n in ("a.mkv", "b.mkv")])
        page.running = True
        page.rows[0].state = bug_reports.ROW_DONE
        page.on_finished(RunnerResult(status="cancelled", exit_code=None, run_id=run_id))
        kept = {Path(item["path"]).name: item["outcome"] for item in window.records.run_items(run_id)}
        self.assertEqual(kept, {"a.mkv": "completed", "b.mkv": "cancelled"})

    def test_transcribed_recording_is_not_shown_as_finished_while_screenshots_run(self) -> None:
        """Operator: rows said Completed while the page still said Currently processing (105)."""

        window = self._window()
        window._initialize_progress_queue(["a.mkv", "b.mkv"])
        window._parse_progress_line(OUTCOME % ("a.mkv", "transcribed", "false", "completed", "a.mkv"))
        window._parse_progress_line(OUTCOME % ("b.mkv", "transcribed", "false", "completed", "b.mkv"))
        window._parse_progress_line(RENDER % "a.mkv")
        self.assertEqual(window.progress_item_states, {"a.mkv": "transcribed", "b.mkv": "transcribed"})
        self.assertEqual(window.progress_queue_table.item(0, 0).text(), "Transcribed, screenshots next")
        self.assertEqual(window.progress_completed.text(), "0")
        self.assertEqual(window.progress_remaining.text(), "2")
        self.assertIn("2 transcribed, making screenshots and clips", window.overall_progress_bar.format())
        self.assertEqual(window.progress_phase.text(), "Screenshots of flagged moments")
        window._finalize_progress_queue("succeeded")
        self.assertEqual(window.progress_item_states, {"a.mkv": "completed", "b.mkv": "completed"})

    def test_project_list_with_a_byte_order_mark_is_read(self) -> None:
        window = self._window()
        repo_map = Path(window.app_settings["evidence_repo_map_path"])
        repo_map.write_bytes(b"\xef\xbb\xbf" + json.dumps({"repos": {"a/b": {}, "c/d": {}, "e/f": {}}}).encode("utf-8"))
        page = window.bug_reports_page
        page._refresh_choose_state()
        self.assertIn("3 projects", page.projects_label.text())

    def test_run_keeps_the_operators_settings(self) -> None:
        rows = [RecordingRow(path=self.recordings / "a.mkv")]
        app_settings = {
            "output_folder": str(self.root / "out"),
            "temp_folder": str(self.root / "my-temp"),
            "log_folder": str(self.root / "my-logs"),
            "dependency_ffmpeg_path": "X:/tools/ffmpeg.exe",
            "whisper_model": "large-v3",
            "evidence_panel_crops": "Off",
        }
        settings = build_bug_report_settings(app_settings, rows, self.root / "run")
        self.assertEqual(settings["temp_folder"], str(self.root / "my-temp"))
        self.assertEqual(settings["log_folder"], str(self.root / "my-logs"))
        self.assertEqual(settings["dependency_ffmpeg_path"], "X:/tools/ffmpeg.exe")
        self.assertEqual(settings["whisper_model"], "large-v3")
        # The racing preset's evidence options still apply.
        self.assertEqual(settings["narration_speech_mode"], "Sparse")
        # A choice the preset leaves at its default stays the operator's.
        self.assertEqual(settings["evidence_panel_crops"], "Off")
        self.assertEqual(settings["output_folder"], str(self.root / "run"))

    def test_second_run_is_refused_while_one_is_active(self) -> None:
        window = self._window()
        page = window.bug_reports_page
        page.add_recordings([self.recordings / "a.mkv"])
        window.runner_thread = object()  # another review is running
        try:
            from unittest import mock

            with mock.patch("media_manglers_workbench.app.QMessageBox.information") as told:
                page.start()
            told.assert_called_once()
            self.assertFalse(page.running)
            self.assertEqual(page.stack.currentIndex(), 0)
        finally:
            window.runner_thread = None

    def test_no_narration_anywhere_is_reported_honestly(self) -> None:
        window = self._window()
        page = window.bug_reports_page
        page.add_recordings([self.recordings / "b.mkv"])
        ScriptedBackend.write_package = False
        ScriptedBackend.exit_code = 1
        ScriptedBackend.lines = [
            "No usable narration transcript was produced, so no package was built. Recordings:",
            "  - b.mkv: no narration found - your microphone was silent in this recording",
        ]
        page.start()
        self._wait_for_results(page)
        self.assertEqual(page.summary.status, "nothing_usable")
        self.assertIn("No narration was found", page.results_headline.text())
        self.assertFalse(page.copy_claude_button.isEnabled())

    def test_nothing_usable_because_a_track_must_be_chosen_is_not_called_no_narration(self) -> None:
        # 142: the recording is full of speech; the app only could not tell
        # which track is the microphone. Saying "no narration" would be false.
        window = self._window()
        page = window.bug_reports_page
        page.add_recordings([self.recordings / "a.mkv", self.recordings / "b.mkv"])
        ScriptedBackend.write_package = False
        ScriptedBackend.exit_code = 1
        ScriptedBackend.lines = [
            "No usable narration transcript was produced, so no package was built. Recordings:",
            "  - a.mkv: the app could not tell which track is your microphone - press Fix and continue, "
            "right-click this recording, choose the track with your voice, then press Continue",
            "  - b.mkv: no narration found - No audio track carries clear speech.",
        ]
        page.start()
        self._wait_for_results(page)
        self.assertEqual(page.summary.status, "nothing_usable")
        headline = page.results_headline.text()
        self.assertNotIn("No narration was found", headline)
        self.assertIn("Fix and continue", headline)
        self.assertIn("could not tell which track is your microphone", page.results_detail.text())

    def test_track_override_is_passed_as_operator_choice(self) -> None:
        rows = [RecordingRow(path=self.recordings / "a.mkv", track_override=2), RecordingRow(path=self.recordings / "b.mkv")]
        settings = build_bug_report_settings({"output_folder": str(self.root)}, rows, self.root / "run")
        selections = json.loads(settings["evidence_audio_stream_selections_json"])
        self.assertEqual(list(selections), [str(self.recordings / "a.mkv")])
        self.assertEqual(selections[str(self.recordings / "a.mkv")]["audioOrdinal"], 1)
        self.assertEqual(selections[str(self.recordings / "a.mkv")]["confirmationSource"], "operator")
        # The choice covers the recording it was made for, and only that one.
        # The run-wide switch would mark b.mkv confirmed too, so the backend
        # would skip listening to it and quietly use the usual track (142).
        self.assertFalse(settings["evidence_audio_stream_selection_confirmed"])
        # Not even when the switch is left on from another kind of review.
        inherited = build_bug_report_settings(
            {"output_folder": str(self.root), "evidence_audio_stream_selection_confirmed": True}, rows, self.root / "run"
        )
        self.assertFalse(inherited["evidence_audio_stream_selection_confirmed"])

    def test_newest_recordings_are_newest_first(self) -> None:
        older = self.recordings / "a.mkv"
        newer = self.recordings / "b.mkv"
        os.utime(older, (time.time() - 100, time.time() - 100))
        self.assertEqual(newest_recordings(self.recordings, 1), [newer])

    def test_headline_never_claims_success_without_a_package(self) -> None:
        self.assertIn("stopped", results_headline(RunSummary(status="failed", package_root=None)))
        summary = summarize_package(self.root / "missing", "failed", ["ERROR: ffmpeg is missing"])
        self.assertEqual(summary.status, "failed")
        self.assertEqual(summary.error, "ffmpeg is missing")

    # Playing a recording from this page (125) ---------------------------------

    def test_264_choosing_a_track_is_remembered_for_that_recording_and_automatic_clears_it(self) -> None:
        from media_manglers.core import speech_facts

        window = self._window()
        page = window.bug_reports_page
        path = (self.recordings / "a.mkv").resolve()
        page.add_recordings([path])
        _menu_entry(page._build_track_menu(0), "Always use Track 3").trigger()
        self.assertEqual(speech_facts.confirmed_track(path), 3)
        self.assertEqual(speech_facts.answer_for(path).by, "bugs_page")

        # Next time it is added: "Track 3 (you chose)", and the run forces it as any chosen track.
        page.rows.clear()
        page.add_recordings([path])
        self.assertEqual(page.rows[0].track_override, 3)
        self.assertEqual(page.table.item(0, 2).text(), "Track 3 (you chose)")
        self.assertEqual(json.loads(bug_reports.selections_json(page.rows))[str(path)]["audioOrdinal"], 2)

        _menu_entry(page._build_track_menu(0), "Find my voice automatically").trigger()
        self.assertIsNone(page.rows[0].track_override)
        self.assertEqual(page.table.item(0, 2).text(), "Automatic")
        self.assertIsNone(speech_facts.confirmed_track(path))
        self.assertEqual(speech_facts.answer_for(path).state, "cleared")
        page.rows.clear()
        page.add_recordings([path])
        self.assertIsNone(page.rows[0].track_override, "Automatic again, everywhere")

    def test_264_a_track_chosen_on_another_screen_shows_here_as_yours(self) -> None:
        from media_manglers.core import speech_facts

        window = self._window()
        page = window.bug_reports_page
        path = (self.recordings / "a.mkv").resolve()
        speech_facts.confirm_track(path, 4, by=speech_facts.ANSWERED_ON_EDITOR)
        page.add_recordings([path])
        self.assertEqual(page.table.item(0, 2).text(), "Track 4 (you chose)")

    def test_264_the_you_chose_line_is_on_the_row_with_no_warning_and_only_when_a_pick_is_stored(self) -> None:
        from media_manglers.core import speech_facts, voice_track

        window = self._window()
        page = window.bug_reports_page
        path = (self.recordings / "a.mkv").resolve()
        page.add_recordings([path])
        _menu_entry(page._build_track_menu(0), "Always use Track 3").trigger()
        self.assertEqual(page.table.item(0, 3).text(), "Ready", "no extra detection runs just to compare")
        speech_facts.record_measure(path, {
            "rule_version": voice_track.VOICE_RULE_VERSION, "status": "selected", "selected_ordinal": 1, "decided_by": "auto",
            "track_activity": {"2": {"silent": False, "moments": [[1.0, 2.0]]}}}, measured_by=speech_facts.BY_BUGS, titles={})
        page.rows.clear()
        page.add_recordings([path])
        self.assertEqual(page.table.item(0, 3).text(),
                         "Ready. You chose Track 3. The app heard your voice on Track 2. Your choice is used.")

    def test_264_the_page_sends_no_run_wide_tie_breaker_whatever_is_saved(self) -> None:
        window = self._window()
        page = window.bug_reports_page
        self.assertFalse(hasattr(page, "_usual_microphone_ordinal"), "the newest answer of any layout is not a pick for this one")
        window.layout_confirmation_store.path.write_text(json.dumps({"layouts": {
            "another-layout": {"audioOrdinal": 3, "confirmedAt": "2099-01-01"}}}), encoding="utf-8")
        page.add_recordings([self.recordings / "a.mkv"])
        page.run_folder = self.root / "run"
        page.run_folder.mkdir()
        page.build_command()
        self.assertEqual(page.run_settings["evidence_audio_stream_index"], 0)
        self.assertFalse(page.run_settings["evidence_audio_stream_selection_confirmed"])

    def test_right_click_menus_offer_play_and_keep_every_entry_they_had(self) -> None:
        window = self._window()
        page = window.bug_reports_page
        page.add_recordings([self.recordings / "a.mkv", self.recordings / "b.mkv"])

        menu = page._build_track_menu(1)
        self.assertEqual(_menu_texts(menu), [*PLAY_ENTRIES, *TRACK_MENU_BEFORE_125])
        self.assertEqual(
            _menu_texts(_menu_entry(menu, "Play with").menu()),
            ["Built-in player", "VLC", "Default video app"],
        )
        with patch.object(window.video_opener, "open", return_value=True) as opened:
            _menu_entry(menu, "Play").trigger()
        self.assertEqual(opened.call_args.args[0].path, (self.recordings / "b.mkv").resolve())
        self.assertEqual(
            [target.path.name for target in opened.call_args.kwargs["sequence"].targets],
            ["a.mkv", "b.mkv"],
        )
        # The old entries still do what they did.
        _menu_entry(menu, "Always use Track 3").trigger()
        self.assertEqual(page.rows[1].track_override, 3)

        # The working table: playing is always offered, skipping only while a
        # run is going, because skipping talks to the live run.
        self.assertEqual(_menu_texts(page._build_working_menu(0)), PLAY_ENTRIES)
        page.running = True
        try:
            self.assertEqual(
                _menu_texts(page._build_working_menu(0)), [*PLAY_ENTRIES, "Skip this recording"]
            )
        finally:
            page.running = False
        # A row that has gone since the click gets nothing, not an error.
        self.assertTrue(page._build_working_menu(7).isEmpty())
        self.assertEqual(page._targets_at(page.table.model().index(7, 0)), [])

    def test_a_host_with_no_opener_gets_no_play_entries_and_no_empty_menu(self) -> None:
        page = BugReportsPage(_HostWithoutAnOpener())
        try:
            page.add_recordings([self.recordings / "a.mkv"])
            self.assertEqual(_menu_texts(page._build_track_menu(0)), TRACK_MENU_BEFORE_125)
            self.assertTrue(page._build_working_menu(0).isEmpty())
            page.watch_a_recording()  # nothing to open it with: does nothing, raises nothing
        finally:
            page.deleteLater()

    def test_play_list_is_a_snapshot_in_row_order_that_outlives_its_rows(self) -> None:
        (self.recordings / "c.mkv").write_bytes(b"not really video")
        window = self._window()
        page = window.bug_reports_page
        names = ("c.mkv", "a.mkv", "b.mkv")
        page.add_recordings([self.recordings / name for name in names])
        page._set_override(1, 4)

        sequence = page._play_sequence()
        self.assertEqual(sequence.label, PLAY_LIST_LABEL)
        self.assertEqual([target.path.name for target in sequence.targets], list(names))
        # The track the operator forced is handed over as the voice track.
        self.assertEqual([target.voice_track for target in sequence.targets], [None, 4, None])
        # No run has finished, so there is no package to read a transcript from.
        self.assertEqual([target.package_root for target in sequence.targets], [None, None, None])

        # Double-click plays that row, with the whole list as it stands now.
        with patch.object(window.video_opener, "open", return_value=True) as opened:
            page.table.doubleClicked.emit(page.table.model().index(1, 0))
        self.assertEqual(opened.call_args.args[0].path.name, "a.mkv")
        self.assertEqual(opened.call_args.args[0].voice_track, 4)
        handed_over = opened.call_args.kwargs["sequence"]
        self.assertEqual(handed_over.targets, sequence.targets)
        self.assertEqual(handed_over.label, sequence.label)

        # Marking the first recording never-use removes its row. The list taken
        # earlier is untouched, and what came next is still found, by path.
        first = page.rows[0].path
        page.table.selectRow(0)
        page.never_use_selected()
        self.assertEqual([row.path.name for row in page.rows], ["a.mkv", "b.mkv"])
        self.assertEqual([target.path.name for target in sequence.targets], list(names))
        following, reason = next_target(sequence, first, page._excluded_keys())
        self.assertEqual((following.path.name, reason), ("a.mkv", "next"))

    def test_results_offer_the_runs_recordings_with_their_package(self) -> None:
        window = self._window()
        page = window.bug_reports_page
        page.add_recordings([self.recordings / "a.mkv", self.recordings / "b.mkv"])
        page._set_override(1, 2)
        ScriptedBackend.lines = [
            "  Listening to every audio track to find your voice: a.mkv",
            "  Voice found on Track 5.",
            PROGRESS % ("a.mkv", "Transcription completed: a.mkv"),
        ]
        page.start()
        self._wait_for_results(page)
        self.assertEqual(page.stack.currentIndex(), 2)
        # isHidden, not isVisible: a finished run leaves another page in front.
        self.assertFalse(page.watch_button.isHidden())
        self.assertTrue(page.watch_button.isEnabled())

        package_root = page.summary.package_root
        self.assertIsNotNone(package_root)
        menu = page._build_watch_menu(window.video_opener)
        # One entry for each recording of the run, named after it.
        self.assertEqual(_menu_texts(menu), ["a.mkv", "b.mkv"])
        with patch.object(window.video_opener, "open", return_value=True) as opened:
            for name in ("a.mkv", "b.mkv"):
                _menu_entry(_menu_entry(menu, name).menu(), "Play").trigger()
        played = [call.args[0] for call in opened.call_args_list]
        self.assertEqual([target.path.name for target in played], ["a.mkv", "b.mkv"])
        # The package is what lets the player show what was written down.
        self.assertEqual([target.package_root for target in played], [package_root, package_root])
        # What the run found, and what the operator forced.
        self.assertEqual([target.voice_track for target in played], [5, 2])
        self.assertEqual(
            [target.path.name for target in opened.call_args.kwargs["sequence"].targets],
            ["a.mkv", "b.mkv"],
        )

    def test_the_never_use_list_plays_a_recording_and_leaves_the_player_usable(self) -> None:
        window = self._window()
        page = window.bug_reports_page
        recording = self.recordings / "a.mkv"
        # 244: the never-use list lives in the library.
        window.records.set_never_use(recording, True, by="Find Bug Reports")
        seen: dict[str, object] = {}
        first_entries: list[str] = []

        def choose_the_first_entry(menu: QMenu, _where) -> None:
            # Stands in for showing the menu, and picks what the operator would.
            entry = menu.actions()[0]
            first_entries.append(entry.text())
            entry.trigger()

        def watch_from_the_list(dialog: QDialog) -> int:
            # Stands in for the modal loop, so no dialog is ever shown. Both
            # clicks go through the list itself: taking the attach line out of
            # manage_excluded has to fail here.
            seen["modality"] = dialog.windowModality()
            listing = dialog.findChild(QListWidget)
            index = listing.model().index(0, 0)
            listing.doubleClicked.emit(index)
            point = listing.visualRect(index).center()
            seen["aimed at row"] = listing.indexAt(point).row()
            listing.customContextMenuRequested.emit(point)
            return 0

        with (
            patch.object(window.video_opener, "open", return_value=True) as opened,
            patch.object(window.video_opener, "_exec_menu", side_effect=choose_the_first_entry),
            patch.object(QDialog, "exec", watch_from_the_list),
        ):
            page.manage_excluded()

        # Blocking this window only. Blocking the whole app, as a dialog does
        # when left alone, would open the built-in player dead to every click
        # and key until the list was closed.
        self.assertEqual(seen["modality"], Qt.WindowModality.WindowModal)
        self.assertEqual(seen["aimed at row"], 0)
        self.assertEqual(first_entries, ["Play"])
        self.assertEqual([call.args[0].path for call in opened.call_args_list], [recording, recording])
        # Not a play list: nothing is "next" after a recording watched here.
        self.assertEqual([call.kwargs["sequence"] for call in opened.call_args_list], [None, None])

    def test_the_page_leaves_the_workbenchs_own_sound_output_alone(self) -> None:
        # The built-in player has a sound output of its own (125). Nothing on
        # this page may reach for the narration preview's, whose volume and
        # owner the main window counts on.
        self.assertNotIn("audio_output", Path(bug_reports.__file__).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
