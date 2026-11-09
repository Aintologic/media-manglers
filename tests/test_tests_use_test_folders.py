"""The test run never writes into the operator's own Workbench folders (226).

Some tests start the Workbench without pointing its folders anywhere. Every full run then left its
"Workbench started" logs in the real logs folder. The shared test setup (tests/conftest.py) now gives
every test folders of the run's own for the Workbench's app data, its local app data (where the logs
go), the raw bin library, the cache and the scratch folder.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from media_manglers_workbench import settings as workbench_settings  # noqa: E402
from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.resources import DependencyStatus, RuntimeResources  # noqa: E402
from media_manglers_workbench.runner import FakeRunner  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
# The run's own folders sit beside these two, which the setup has always pointed at a scratch folder.
TEST_ROOT = Path(os.environ["MEDIA_MANGLERS_VIDEOS_FOLDER"]).parent
FOLDER_VARIABLES = (
    workbench_settings.APPDATA_OVERRIDE_ENV,
    workbench_settings.LOCALAPPDATA_OVERRIDE_ENV,
    "MEDIA_MANGLERS_LIBRARY_ROOT",
    "MEDIA_MANGLERS_CACHE_ROOT",
    "MEDIA_MANGLERS_SCRATCH_ROOT",
)


def _real_folders() -> list[Path]:
    """The operator's own app data folders, as Windows names them."""

    return [Path(os.environ[name]) for name in ("APPDATA", "LOCALAPPDATA") if os.environ.get(name)]


def _inside(path: Path, folder: Path) -> bool:
    try:
        return Path(path).resolve().is_relative_to(Path(folder).resolve())
    except (OSError, ValueError):
        return False


class TestFoldersTests(unittest.TestCase):
    def test_every_workbench_folder_points_at_a_folder_of_the_test_run(self) -> None:
        for name in FOLDER_VARIABLES:
            with self.subTest(variable=name):
                value = os.environ.get(name, "")
                self.assertTrue(value, f"{name} is not set for the test run")
                for real in _real_folders():
                    self.assertFalse(_inside(Path(value), real), f"{name} points into {real}")

    def test_the_workbench_logs_and_settings_go_into_the_test_run(self) -> None:
        for folder in (workbench_settings.default_log_folder(), workbench_settings.default_temp_folder(),
                       workbench_settings.default_settings_root()):
            with self.subTest(folder=str(folder)):
                for real in _real_folders():
                    self.assertFalse(_inside(folder, real), f"{folder} is in the operator's own {real}")

    def test_a_workbench_started_without_folders_logs_into_the_test_run(self) -> None:
        # The way the tests that wrote the stray logs start it: no log folder in its settings.
        app = QApplication.instance() or QApplication([])
        settings_path = TEST_ROOT / "workbench-start-test" / "settings.json"
        window = WorkbenchWindow(settings_path=settings_path, profiles_dir=settings_path.parent / "profiles",
                                 runner_factory=FakeRunner, resources=RuntimeResources(
                                     app_root=REPO_ROOT, script_path=REPO_ROOT / "Video Mangler.ps1",
                                     backend_source_root=REPO_ROOT / "src", icon_path=REPO_ROOT / "assets" / "Video Mangler.ico",
                                     powershell_exe="powershell", python_exe="py", ffmpeg_exe="ffmpeg", ffprobe_exe="ffprobe",
                                     packaged=False, dependencies=[DependencyStatus("test backend", "ready")]))
        try:
            app.processEvents()
            log = Path(window.run_log_path)
            for real in _real_folders():
                self.assertFalse(_inside(log, real), f"the Workbench's log {log} is in the operator's own {real}")
            self.assertTrue(_inside(log, TEST_ROOT), log)
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    unittest.main()
