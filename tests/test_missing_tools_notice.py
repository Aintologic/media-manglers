"""A missing tool says what is missing and where to get it (188); saved tool paths keep working.

Every button here is clicked, never emitted. The readiness check runs on its own thread as at a
real launch, with its probes answered by a fake runner, so no real tool on this PC is used,
hidden or moved.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QFrame, QPushButton, QWidget  # noqa: E402

from media_manglers_workbench import dependencies  # noqa: E402
from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.resources import DependencyStatus, RuntimeResources  # noqa: E402
from media_manglers_workbench.runner import FakeRunner  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: E402
from tests.qt_input import row_point  # noqa: E402
from tests.test_workbench_dependencies import FakeDependencyRunner, _payload  # noqa: E402

KEYS = ("dependency_python_path", "dependency_ffmpeg_path", "dependency_ffprobe_path", "dependency_ytdlp_path")


class MissingToolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window: WorkbenchWindow | None = None
        self.opened: list[str] = []
        opener = patch(
            "media_manglers_workbench.app.QDesktopServices.openUrl",
            side_effect=lambda url: self.opened.append(url.toString()) or True,
        )
        opener.start()
        self.addCleanup(opener.stop)

    def tearDown(self) -> None:
        if self.window is not None:
            self.window._closing_after_smoke = True
            self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def _exe(self, name: str) -> str:
        path = self.root / "tools" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test executable")
        return str(path.resolve())

    def _window(self, saved: dict[str, str] | None = None) -> WorkbenchWindow:
        settings = {"log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp")}
        settings.update(saved or {})
        self.settings_path = self.root / "settings.json"
        self.settings_path.write_text(
            json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": settings}), encoding="utf-8"
        )
        self.powershell = self._exe("powershell.exe")
        resources = RuntimeResources(
            app_root=REPO_ROOT,
            script_path=REPO_ROOT / "Video Mangler.ps1",
            backend_source_root=REPO_ROOT / "src",
            icon_path=None,
            powershell_exe=self.powershell,
            python_exe="",
            ffmpeg_exe=str(self.root / "missing" / "ffmpeg.exe"),
            ffprobe_exe=str(self.root / "missing" / "ffprobe.exe"),
            packaged=False,
            dependencies=[DependencyStatus("test backend", "ready")],
        )
        self.window = WorkbenchWindow(
            settings_path=self.settings_path,
            profiles_dir=self.root / "profiles",
            runner_factory=FakeRunner,
            resources=resources,
        )
        self.window.show()
        self.app.processEvents()
        return self.window

    def _wait_until(self, predicate, timeout_ms: int = 10000) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertTrue(predicate(), "timed out waiting for the Workbench")

    def _check(self, window: WorkbenchWindow, python: str, *, force_candidates: bool = True,
               missing: tuple[str, ...] = (), vlc: str = "") -> list[dict[str, object]]:
        """One readiness check on its own thread; the probes are answered by the fake runner.

        With force_candidates=False the check finds Python itself, from the chosen path, as at a
        real launch. `missing` names tools whose version probe fails.
        """
        calls: list[dict[str, object]] = []
        self.probed: list[str] = []
        real = dependencies.run_dependency_preflight
        fake = FakeDependencyRunner({python: _payload()} if python else {})

        def runner(argv, timeout, env):
            self.probed.append(str(Path(argv[0]).resolve()))
            if any(name in Path(argv[0]).name for name in missing):
                return subprocess.CompletedProcess(argv, 1, "", "not installed in this test")
            return fake(argv, timeout, env)

        def preflight(resources, **kwargs):
            calls.append(dict(kwargs))
            kwargs["runner"] = runner
            kwargs["vlc_finder"] = lambda _chosen: vlc
            if python and force_candidates:
                kwargs["python_candidates"] = [python]
            return real(resources, **kwargs)

        with patch("media_manglers_workbench.app.run_dependency_preflight", side_effect=preflight):
            window.start_dependency_check()
            self._wait_until(lambda: window.dependency_check_thread is None)
        return calls

    def _click(self, button: QPushButton) -> None:
        self.assertTrue(button.isVisible(), button.text())
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.app.processEvents()

    def _row(self, window: WorkbenchWindow, key: str) -> int:
        table = window.dependency_table
        return next(
            row for row in range(table.rowCount())
            if table.item(row, 0).data(Qt.ItemDataRole.UserRole) == key
        )

    def _cell_buttons(self, window: WorkbenchWindow, key: str) -> dict[str, QPushButton]:
        cell = window.dependency_table.cellWidget(self._row(window, key), 4)
        self.assertIsInstance(cell, QWidget)
        buttons = [cell] if isinstance(cell, QPushButton) else cell.findChildren(QPushButton)
        return {button.text(): button for button in buttons}

    def test_start_up_notice_names_the_missing_tools_and_opens_their_page(self) -> None:
        window = self._window()
        python = self._exe("python.exe")
        self._check(window, python)
        notice = window.missing_tools_notice
        self.assertTrue(notice.isVisible())
        self.assertIn("FFmpeg and FFprobe", notice.message.text())
        self.assertEqual(sorted(notice.download_buttons), ["ffmpeg", "ffprobe"])
        # One row, one button tall, and Home still has room for every card at the default size.
        self.assertLessEqual(notice.height(), notice.not_now_button.sizeHint().height() + 12)
        self.assertEqual(notice.message.toolTip(), notice.message.text())
        window.navigate("Home")
        self.app.processEvents()
        cards = [frame for frame in window.pages["Home"].findChildren(QFrame)
                 if frame.property("card") and frame.isVisible()]
        boxes = [QRect(card.mapTo(window, QPoint(0, 0)), card.size()) for card in cards]
        overlapping = [(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1:] if a.intersects(b)]
        self.assertEqual(overlapping, [], "the bar may not squeeze Home's cards over each other")
        self._click(notice.download_buttons["ffmpeg"])
        self.assertEqual(self.opened, ["https://ffmpeg.org/download.html"])
        self.assertIn("Nothing was downloaded or installed", window.dependency_summary.text())
        self._click(notice.not_now_button)
        self.assertFalse(notice.isVisible())
        # Once per launch: a later check never brings it back.
        self._check(window, python)
        self.assertFalse(notice.isVisible())

    def test_the_notice_opens_settings_dependencies(self) -> None:
        window = self._window()
        self._check(window, self._exe("python.exe"))
        self._click(window.missing_tools_notice.settings_button)
        self.assertFalse(window.missing_tools_notice.isVisible())
        self.assertIs(window.page_stack.currentWidget(), window.pages["Settings"])
        self.assertEqual(window.settings_tabs.tabText(window.settings_tabs.currentIndex()), "Dependencies")

    def test_no_notice_when_every_required_tool_is_there(self) -> None:
        python = self._exe("python.exe")
        window = self._window({
            "dependency_ffmpeg_path": self._exe("ffmpeg.exe"),
            "dependency_ffprobe_path": self._exe("ffprobe.exe"),
        })
        self._check(window, python)
        self.assertFalse(window.missing_tools_notice.isVisible())

    def test_dependencies_row_offers_download_and_the_winget_command(self) -> None:
        window = self._window()
        self._check(window, self._exe("python.exe"))
        window.navigate("Settings")
        window.settings_tabs.setCurrentIndex(2)
        self.app.processEvents()
        buttons = self._cell_buttons(window, "ffmpeg")
        self.assertEqual(sorted(buttons), ["Choose path", "Download"], "the existing button stays")
        cell = window.dependency_table.cellWidget(self._row(window, "ffmpeg"), 4)
        self.assertGreaterEqual(window.dependency_table.columnWidth(4), cell.sizeHint().width(),
                                "both buttons fit in the Action column")
        self._click(buttons["Download"])
        self.assertEqual(self.opened, ["https://ffmpeg.org/download.html"])
        table = window.dependency_table
        index = table.model().index(self._row(window, "ffmpeg"), 0)
        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         row_point(table, index))
        self.app.processEvents()
        self.assertTrue(window.dependency_get_panel.isVisible())
        self.assertIn("https://ffmpeg.org/download.html", window.dependency_get_label.text())
        self.assertIn("winget install --id Gyan.FFmpeg -e", window.dependency_get_label.text())
        self._click(window.dependency_copy_winget_button)
        self.assertEqual(QApplication.clipboard().text(), "winget install --id Gyan.FFmpeg -e")
        # A ready row offers no Download and hides the panel.
        index = table.model().index(self._row(window, "powershell"), 0)
        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         row_point(table, index))
        self.app.processEvents()
        self.assertFalse(window.dependency_get_panel.isVisible())
        self.assertIsNone(table.cellWidget(self._row(window, "powershell"), 4))

    def test_saved_tool_paths_keep_working_exactly_as_before(self) -> None:
        # The four paths an operator's settings already hold are used first, as chosen paths, are
        # passed to the scripts, and the check leaves the settings file byte for byte as it was.
        saved = {
            "dependency_python_path": self._exe(r"pythoncore-3.14-64\python.exe"),
            "dependency_ffmpeg_path": self._exe(r"Links\ffmpeg.exe"),
            "dependency_ffprobe_path": self._exe(r"Links\ffprobe.exe"),
            "dependency_ytdlp_path": self._exe(r"Links\yt-dlp.exe"),
        }
        window = self._window(saved)
        before = self.settings_path.read_bytes()
        calls = self._check(window, saved["dependency_python_path"], force_candidates=False)
        pythons = [path for path in self.probed if "python" in Path(path).name]
        # Installer plan, Stage 3: the saved Python is asked twice (its own check, then its Whisper models'), and
        # no other Python is tried.
        self.assertEqual(sorted(set(pythons)), [saved["dependency_python_path"]], "only the saved Python is tried")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["configured_python"], saved["dependency_python_path"])
        self.assertEqual(calls[0]["configured_ffmpeg"], saved["dependency_ffmpeg_path"])
        self.assertEqual(calls[0]["configured_ffprobe"], saved["dependency_ffprobe_path"])
        self.assertEqual(calls[0]["configured_ytdlp"], saved["dependency_ytdlp_path"])
        self.assertEqual(window.resources.python_exe, saved["dependency_python_path"])
        self.assertEqual(window.resources.ffmpeg_exe, saved["dependency_ffmpeg_path"])
        self.assertEqual(window.resources.ffprobe_exe, saved["dependency_ffprobe_path"])
        self.assertEqual(window.resources.ytdlp_exe, saved["dependency_ytdlp_path"])
        self.assertEqual(self.settings_path.read_bytes(), before, "the check writes nothing")
        argv = window.build_command().argv
        for flag, key in (("-FFmpegPath", "dependency_ffmpeg_path"), ("-FFprobePath", "dependency_ffprobe_path"),
                          ("-PythonExe", "dependency_python_path"), ("-YtDlpPath", "dependency_ytdlp_path")):
            self.assertEqual(argv[argv.index(flag) + 1], saved[key], flag)
        self.assertFalse(window.missing_tools_notice.isVisible())

    def test_a_later_check_updates_the_bar_and_the_rows(self) -> None:
        # The bar names only what is still missing, and a row that becomes ready loses its
        # Download button and its "Get" panel.
        python = self._exe("python.exe")
        window = self._window({"dependency_ffmpeg_path": self._exe("ffmpeg.exe"),
                               "dependency_ffprobe_path": self._exe("ffprobe.exe")})
        self._check(window, python, missing=("ffmpeg", "ffprobe"))
        notice = window.missing_tools_notice
        self.assertEqual(sorted(notice.download_buttons), ["ffmpeg", "ffprobe"])
        window.navigate("Settings")
        window.settings_tabs.setCurrentIndex(2)
        self.app.processEvents()
        table = window.dependency_table
        index = table.model().index(self._row(window, "ffprobe"), 0)
        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         row_point(table, index))
        self.app.processEvents()
        self.assertTrue(window.dependency_get_panel.isVisible())
        self._check(window, python, missing=("ffmpeg",))
        self.assertTrue(notice.isVisible())
        self.assertEqual(sorted(notice.download_buttons), ["ffmpeg"])
        self.assertIn("Missing: FFmpeg.", notice.message.text())
        self.assertEqual(sorted(self._cell_buttons(window, "ffprobe")), ["Choose path"], "no Download once ready")
        self.assertFalse(window.dependency_get_panel.isVisible(), "the Get panel follows the ready row")
        self.assertEqual(sorted(self._cell_buttons(window, "vlc")), ["Download"], "VLC not found yet")
        self._check(window, python, vlc=self._exe("vlc.exe"))
        self.assertFalse(notice.isVisible())
        row = self._row(window, "vlc")
        self.assertIsNone(table.cellWidget(row, 4), "a row with nothing to do keeps no old buttons")
        self.assertEqual(table.item(row, 4).text(), "—")

    def test_found_paths_are_not_saved_as_chosen(self) -> None:
        window = self._window({"dependency_ffmpeg_path": self._exe("ffmpeg.exe"),
                               "dependency_ffprobe_path": self._exe("ffprobe.exe")})
        before = self.settings_path.read_bytes()
        self._check(window, self._exe("python.exe"))
        saved = json.loads(self.settings_path.read_text(encoding="utf-8"))["settings"]
        self.assertEqual(saved.get("dependency_python_path", ""), "", "a Python the check found is not saved")
        self.assertEqual(self.settings_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
