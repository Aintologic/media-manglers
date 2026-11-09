"""Design wave D1 (237): the whole app's look and its shared parts, checked on the real window.

- Text size: a Settings choice, applied at once, saved as its own key, restored at start-up;
  Ctrl+Plus, Ctrl+Minus and Ctrl+0 on every page. Old settings files load unchanged.
- The rail: four groups, and a badge on Queue / Progress while a job runs.
- Long jobs: a banner on the page that started the job, whose link opens that job.
- One primary button per area, as in the approved mockups.
- Nothing wider than the window, and every rail button on screen, at 150% in 1280x800.

Clicks and keys go through real input events on a shown window (tests/qt_input.py).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from media_manglers_workbench import theme  # noqa: E402
from media_manglers_workbench.app import NAV_GROUPS, PAGE_NAMES, TEXT_SIZE_KEY, WorkbenchWindow  # noqa: E402
from media_manglers_workbench.command_builder import CommandSpec  # noqa: E402
from media_manglers_workbench.resources import DependencyStatus, RuntimeResources  # noqa: E402
from media_manglers_workbench.runner import FakeRunner, RunnerResult  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION, load_settings  # noqa: E402
from tests.qt_input import bring_to_front, click  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]


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


def _progress(**fields: object) -> str:
    event = {"schema": "MM_PROGRESS_V1", "phase": "Rendering", "progress_kind": "work_units", "completed": 21,
             "total": 50, "source_name": "race.mkv", "source_completed": 0, "source_total": 1, "source_ordinal": 1,
             "source_state": "active", "eta_state": "available", "eta_seconds": 65, **fields}
    return "MM_PROGRESS_V1 " + json.dumps(event)


class HeldRunner:
    """A run that prints one progress line, then waits until the test lets it finish."""

    instances: list["HeldRunner"] = []

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        HeldRunner.instances.append(self)

    def cancel(self) -> None:
        self.release.set()

    def run(self, command, on_log=None, *, cwd=None) -> RunnerResult:
        on_log("stdout", _progress())
        self.started.set()
        self.release.wait(30)
        return RunnerResult(status="succeeded", exit_code=0, stdout_lines=[], error="")


class _Listener:
    def __init__(self) -> None:
        self.finished: list[RunnerResult] = []

    def on_log_line(self, _stream: str, _line: str) -> None:
        pass

    def on_finished(self, result: RunnerResult) -> None:
        self.finished.append(result)


class DesignWaveD1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings_path = self.root / "settings.json"
        self.windows: list[WorkbenchWindow] = []
        HeldRunner.instances = []

    def tearDown(self) -> None:
        for runner in HeldRunner.instances:
            runner.release.set()
        for window in self.windows:
            if window.runner_thread is not None:
                window.runner_thread.wait(10000)
                self.app.processEvents()
            window._closing_after_smoke = True
            window.close()
        self.app.processEvents()
        theme.apply_theme(self.app, "Dark", 100)
        self.temp.cleanup()

    def _write_settings(self, **settings: object) -> None:
        self.settings_path.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
            "log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
            "output_folder": str(self.root / "out"), "race_video_output_folder": str(self.root / "videos"),
            **settings}}), encoding="utf-8")

    def _window(self, size: tuple[int, int] = (1400, 900), runner=FakeRunner, **settings: object) -> WorkbenchWindow:
        if not self.settings_path.exists() or settings:
            self._write_settings(**settings)
        window = WorkbenchWindow(settings_path=self.settings_path, profiles_dir=self.root / "profiles",
                                 runner_factory=runner, resources=_resources())
        window.resize(*size)
        window.show()
        self.app.processEvents()
        self.windows.append(window)
        return window

    def _close(self, window: WorkbenchWindow) -> None:
        window._closing_after_smoke = True
        window.close()
        self.windows.remove(window)
        self.app.processEvents()

    # Text size ------------------------------------------------------------------------------

    def test_text_size_is_chosen_in_settings_applies_at_once_and_comes_back_at_start_up(self) -> None:
        window = self._window()
        click(window.nav_buttons["Settings"])
        control = window.settings_text_size
        self.assertEqual([control.buttons[size].text() for size in (100, 110, 125, 150)],
                         ["100%", "110%", "125%", "150%"])
        self.assertTrue(control.buttons[100].isChecked(), "a settings file without the key opens at 100%")
        click(control.buttons[125])
        body = theme.whole_pixel_pt(theme.FONT_SIZES["body"], 1.25)
        self.assertIn(f"font-size: {body}pt", self.app.styleSheet(), "applied at once, with no Save")
        self.assertAlmostEqual(theme.text_scale(), 1.25)
        self.assertEqual(window.settings_text_size_feedback.text(), "Text size 125%. Saved.")
        saved = json.loads(self.settings_path.read_text(encoding="utf-8"))["settings"]
        self.assertEqual(saved[TEXT_SIZE_KEY], 125)
        self._close(window)
        theme.apply_theme(self.app, "Dark", 100)

        restarted = self._window()
        self.assertAlmostEqual(theme.text_scale(), 1.25, msg="restored at start-up")
        self.assertTrue(restarted.settings_text_size.buttons[125].isChecked())

    def test_an_old_settings_file_loads_unchanged(self) -> None:
        old = {"schemaVersion": 7, "settings": {"theme": "Light", "startup_page": "History", "debug_mode": False,
                                                "output_folder": str(self.root / "out")}}
        self.settings_path.write_text(json.dumps(old), encoding="utf-8")
        loaded = load_settings(self.settings_path)
        self.assertEqual((loaded["theme"], loaded["startup_page"], loaded["debug_mode"]), ("Light", "History", False))
        self.assertEqual(loaded[TEXT_SIZE_KEY], 100)

    def test_ctrl_plus_ctrl_minus_and_ctrl_0_work_on_every_page(self) -> None:
        window = self._window()
        window.activateWindow()
        QTest.qWaitForWindowActive(window, 2000)
        sizes = []
        for page, keys in (("Home", "Ctrl++"), ("AI Video Editor", "Ctrl++"), ("Evidence", "Ctrl+-"),
                           ("Queue / Progress", "Ctrl+="), ("Help", "Ctrl+0")):
            with self.subTest(page=page, keys=keys):
                click(window.nav_buttons[page])
                action = {"Ctrl++": 1, "Ctrl+=": 1, "Ctrl+-": -1, "Ctrl+0": 0}[keys]
                self.assertIn(keys, [shortcut.toString() for shortcut in window.text_size_actions[action].shortcuts()])
                QTest.keySequence(window, keys)
                self.app.processEvents()
                sizes.append(window.text_size())
        self.assertEqual(sizes, [110, 125, 110, 125, 100])
        saved = json.loads(self.settings_path.read_text(encoding="utf-8"))["settings"]
        self.assertEqual(saved[TEXT_SIZE_KEY], 100)

    def test_on_windows_text_is_drawn_by_gdi_unless_a_platform_was_chosen(self) -> None:
        from unittest import mock

        from media_manglers_workbench.app import WINDOWS_PLATFORM, qt_arguments

        with mock.patch("media_manglers_workbench.app.sys.platform", "win32"), \
                mock.patch.dict(os.environ, {"QT_QPA_PLATFORM": ""}):
            self.assertEqual(qt_arguments(["app.exe"]), ["app.exe", "-platform", WINDOWS_PLATFORM])
        with mock.patch("media_manglers_workbench.app.sys.platform", "win32"), \
                mock.patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen"}):
            self.assertEqual(qt_arguments(["app.exe"]), ["app.exe"], "the tests and the smoke launch keep theirs")
        with mock.patch("media_manglers_workbench.app.sys.platform", "linux"), \
                mock.patch.dict(os.environ, {"QT_QPA_PLATFORM": ""}):
            self.assertEqual(qt_arguments(["app"]), ["app"])
        self.assertEqual(WINDOWS_PLATFORM, "windows:fontengine=gdi")

    def test_the_narration_label_has_its_own_line_and_forms_keep_a_gap(self) -> None:
        from PySide6.QtWidgets import QFormLayout, QLabel

        window = self._window(**{TEXT_SIZE_KEY: 125})
        click(window.nav_buttons["Settings"])
        label = window.findChild(QLabel, "settingsTrackRolesLabel")
        self.assertEqual(label.text(), "Narration track, for recordings without track names")
        panel = window.settings_track_roles
        bottom = label.mapTo(window, label.rect().bottomLeft()).y()
        self.assertLessEqual(bottom, panel.mapTo(window, panel.rect().topLeft()).y(), "the label is above the tracks")
        for form in window.findChildren(QFormLayout):
            self.assertGreaterEqual(form.horizontalSpacing(), theme.px(16))

    def test_the_bug_report_tables_start_their_words_at_the_left_and_recording_is_widest(self) -> None:
        from PySide6.QtWidgets import QHeaderView

        window = self._window()
        for table in (window.bug_reports_page.table, window.bug_reports_page.working_table):
            header = table.horizontalHeader()
            with self.subTest(table=table.objectName() or type(table).__name__):
                self.assertTrue(header.defaultAlignment() & Qt.AlignmentFlag.AlignLeft)
                self.assertFalse(header.stretchLastSection())
                for column in range(table.columnCount()):
                    # 112: every column can still be dragged.
                    self.assertEqual(header.sectionResizeMode(column), QHeaderView.ResizeMode.Interactive)
        click(window.nav_buttons["Find Bug Reports"])
        table = window.bug_reports_page.table
        widths = [table.columnWidth(column) for column in range(table.columnCount())]
        # Recording takes all the width the others leave (in real fonts that makes it the widest).
        self.assertGreaterEqual(widths[0] + sum(widths[1:]), table.viewport().width() - 2, widths)
        # Size, Voice track and Status are as wide as what they show now; Recording gets the rest.
        status = table.fontMetrics().horizontalAdvance("Could not be used last time")
        self.assertLess(widths[3], status, "no room kept for a status that is not shown")

    def test_every_rail_button_has_its_icon_and_keeps_its_height_after_a_live_change(self) -> None:
        window = self._window(size=(1280, 800))
        for page, button in window.nav_buttons.items():
            self.assertFalse(button.icon().isNull(), page)
        click(window.nav_buttons["Settings"])
        click(window.settings_text_size.buttons[150])
        QTest.qWait(50)
        expected, _label = theme.nav_row_heights()
        for page, button in window.nav_buttons.items():
            self.assertEqual(button.height(), expected, page)

    # The rail -------------------------------------------------------------------------------

    def test_the_progress_badge_counts_the_running_job_and_is_gone_when_idle(self) -> None:
        window = self._window(runner=HeldRunner)
        badge = window.progress_nav_badge
        self.assertFalse(badge.isVisible())
        self.assertTrue(window.start_external_run(CommandSpec(["backend"], "backend"), title="AI Video Editor: preview",
                                                  settings={"output_folder": str(self.root / "out")},
                                                  queue_items=["race v002"], listener=_Listener(),
                                                  evidence_package=False, origin="AI Video Editor",
                                                  banner_title="Rendering a preview of race v002"))
        HeldRunner.instances[-1].started.wait(5)
        self.app.processEvents()
        self.assertTrue(badge.isVisible())
        self.assertEqual(badge.text(), "1")
        self.assertEqual(window.nav_buttons["Queue / Progress"].text(), "Progress", "its rail text is kept")
        HeldRunner.instances[-1].release.set()
        window.runner_thread.wait(10000)
        self.app.processEvents()
        self.assertFalse(badge.isVisible())

    def test_the_rail_groups_are_the_rulebook_groups(self) -> None:
        self.assertEqual([group for group, _pages in NAV_GROUPS], ["Make", "Library", "Results", "Running"])
        self.assertEqual(PAGE_NAMES[-2:], ("Settings", "Help"))

    # Job banners ----------------------------------------------------------------------------

    def test_a_long_job_shows_a_banner_on_its_own_page_whose_link_opens_that_job(self) -> None:
        window = self._window(runner=HeldRunner)
        click(window.nav_buttons["AI Video Editor"])
        listener = _Listener()
        window.start_external_run(CommandSpec(["backend"], "backend"), title="AI Video Editor: preview",
                                  settings={"output_folder": str(self.root / "out")}, queue_items=["race v002"],
                                  listener=listener, evidence_package=False, origin="AI Video Editor",
                                  banner_title="Rendering a preview of race v002")
        HeldRunner.instances[-1].started.wait(5)
        QTest.qWait(100)
        banner = window.ai_video_editor_page.job_banner
        self.assertTrue(banner.isVisible())
        self.assertEqual(banner.title_label.text(), "Rendering a preview of race v002")
        self.assertIn("%", banner.numbers_label.text())
        self.assertIn("about 1 min left", banner.numbers_label.text())
        # Only the page that started it shows it.
        self.assertIsNone(window.raw_bin_page.job_banner.info)
        self.assertIsNone(window.bug_reports_page.job_banner.info)
        click(banner.open_button)
        self.assertIs(window.page_stack.currentWidget(), window.pages["Queue / Progress"])
        selected = {index.row() for index in window.progress_queue_table.selectedIndexes()}
        self.assertEqual(selected, {0}, "that job's recording is the one selected")
        HeldRunner.instances[-1].release.set()
        window.runner_thread.wait(10000)
        self.app.processEvents()
        self.assertEqual(banner.info.state, "completed")
        self.assertTrue(banner.title_label.text().startswith("Done: "))
        self.assertEqual(len(listener.finished), 1)

    # One primary button per area ------------------------------------------------------------

    def test_each_area_has_the_one_primary_button_of_the_mockups(self) -> None:
        window = self._window()
        expected = {
            "Home": {"Choose recordings"},
            "Find Bug Reports": {"Find bug reports", "Copy prompt for Claude Code"},
            # 236: the start view's card, each step's card, the player's place, the header, the notes box and
            # the two dialogs the page owns (Approve and export…, See the prompt first) are an area each. The
            # player's place shows one of its own at a time: the picture's main play choice, Render a preview
            # for a version with no video, or the next step of a video with no version yet (fix round).
            "AI Video Editor": {"Make a video from a recording", "Prepare for the AI editor", "Copy prompt for Claude Code",
                                "Play the final (full quality)", "Render a preview", "Prepare for the AI editor…",
                                "Approve and export…", "Save notes, copy prompt for Claude Code", "Export",
                                "Copy this prompt"},
            "Raw Bin": {"Scan now"},
            "Review Media Inbox": {"Process new media"},
            "Evidence": {"Open package", "Play this moment"},
            "Session Review": {"Play this moment"},
            "Prompt Drafts": {"Copy draft"},
            "History": {"Play recording"},
            "Queue / Progress": set(),
            "Settings": {"Save settings", "Check readiness"},
            "Help": {"Getting started"},
        }
        for page, texts in expected.items():
            with self.subTest(page=page):
                # A card that is one big button says what it does in its accessible name (236).
                primaries = {button.text() or button.accessibleName() for button in window.pages[page].findChildren(QPushButton)
                             if button.property("primary") and button.objectName() != "navButton"}
                self.assertEqual(primaries, texts)
        # Find my bug reports: its choose screen and its finished screen each have their own one. New Review:
        # Next in the wizard's own row, Inspect source files on the Source step, and Start review on the last
        # step, which takes the primary look while it is ready.
        self.assertTrue(window.wizard_next.property("primary"))
        self.assertTrue(window.inspect_audio_streams_button.property("primary"))
        self.assertIn('QPushButton[operatorAction="ready"]', self.app.styleSheet().split("{")[0] + self.app.styleSheet())

    def test_queue_controls_are_secondary_danger_and_link(self) -> None:
        window = self._window()
        self.assertEqual(window.cancel_button.property("kind"), "danger")
        helps = [button for button in window.pages["Queue / Progress"].findChildren(QPushButton)
                 if button.text() == "Progress help"]
        self.assertEqual(helps[0].property("kind"), "link")

    # 150% in 1280x800 -----------------------------------------------------------------------

    def test_at_every_text_size_nothing_is_cut_off_or_wider_than_a_1280x800_window(self) -> None:
        # In a process of its own with the real Windows fonts: this run's offscreen Qt draws every letter as a
        # wide box, which is no measure of what fits.
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        if not (fonts / "segoeui.ttf").is_file():
            self.skipTest("Segoe UI is not installed here")
        for size in theme.TEXT_SIZES:
            with self.subTest(text_size=size):
                folder = self.root / f"fit-{size}"
                folder.mkdir()
                done = subprocess.run([sys.executable, str(REPO_ROOT / "tests" / "design_fit_check.py"), str(folder),
                                       str(size)], capture_output=True, text=True, timeout=300, cwd=str(REPO_ROOT))
                lines = [line for line in done.stdout.splitlines() if line.startswith("FIT-REPORT ")]
                self.assertTrue(lines, done.stdout[-2000:] + done.stderr[-2000:])
                report = json.loads(lines[-1][len("FIT-REPORT "):])
                self.assertEqual(report["size"], [1280, 800])
                self.assertEqual(report["sideways"], [], "no page scrolls sideways")
                self.assertEqual(report["cut"], [], "no words cut off")
                self.assertEqual(report["rail_off_screen"], [])
                self.assertFalse(report["rail_scrolls"], "the whole rail is on screen")
                self.assertEqual(report["tabs_off_screen"], [])


if __name__ == "__main__":
    unittest.main()
