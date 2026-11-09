"""The build's start-up check and the tests keep away from the operator's own raw bin library (242).

The build's smoke launch gives the Workbench's two app-data folders a throwaway place, but the raw bin
library followed the real local app data folder whatever they said. Once the Workbench opens the library
when it starts (Wave A1), every build would have opened, upgraded and backed up the operator's own
library. The library now follows the Workbench's local app data override, and the build's launch gives
the library, the cache and the privacy masks throwaway folders of their own too.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core import raw_bin_library  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPO_ROOT / "tools" / "gui" / "Build-VideoManglerWorkbench.ps1"
TEST_ROOT = Path(os.environ["MEDIA_MANGLERS_VIDEOS_FOLDER"]).parent
LOCAL_OVERRIDE = "MEDIA_MANGLERS_WORKBENCH_LOCALAPPDATA"
# Every per-user folder the packaged Workbench reads or writes at start-up.
SMOKE_FOLDER_VARIABLES = (
    "MEDIA_MANGLERS_WORKBENCH_APPDATA",
    LOCAL_OVERRIDE,
    "MEDIA_MANGLERS_LIBRARY_ROOT",
    "MEDIA_MANGLERS_CACHE_ROOT",
    "MEDIA_MANGLERS_RACE_VIDEO_PRIVACY",
)


class LibraryRootTests(unittest.TestCase):
    def test_the_library_follows_the_workbench_local_data_override(self) -> None:
        throwaway = TEST_ROOT / "isolation" / "Local"
        with mock.patch.dict(os.environ, {LOCAL_OVERRIDE: str(throwaway)}):
            os.environ.pop(raw_bin_library.LIBRARY_ROOT_ENV, None)
            self.assertEqual(raw_bin_library.library_root(),
                             throwaway / "MediaManglers" / "Workbench" / "library")
            self.assertEqual(raw_bin_library.database_path().parent, raw_bin_library.library_root())

    def test_the_library_override_still_wins(self) -> None:
        chosen = TEST_ROOT / "isolation" / "chosen-library"
        with mock.patch.dict(os.environ, {LOCAL_OVERRIDE: str(TEST_ROOT / "isolation" / "Local"),
                                          raw_bin_library.LIBRARY_ROOT_ENV: str(chosen)}):
            self.assertEqual(raw_bin_library.library_root(), chosen)

    def test_without_an_override_the_library_is_in_local_app_data(self) -> None:
        local = TEST_ROOT / "isolation" / "windows-local-app-data"
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(local)}):
            os.environ.pop(raw_bin_library.LIBRARY_ROOT_ENV, None)
            os.environ.pop(LOCAL_OVERRIDE, None)
            if sys.platform == "win32":
                self.assertEqual(raw_bin_library.library_root(),
                                 local / "MediaManglers" / "Workbench" / "library")


class SmokeLaunchFolderTests(unittest.TestCase):
    def _smoke_block(self) -> str:
        script = BUILD_SCRIPT.read_text(encoding="utf-8")
        return script[script.index("    if ($SmokeTest) {"):script.index("$versionInfo = ")]

    def test_the_builds_smoke_launch_gives_every_per_user_folder_a_throwaway_place(self) -> None:
        # The build's own folder list, run by PowerShell with a smoke folder of the test's own.
        block = self._smoke_block()
        start = block.index("$smokeFolders = [ordered]@{")
        end = block.index("}", start) + 1
        smoke_root = TEST_ROOT / "isolation" / "smoke-appdata"
        command = "\n".join((
            f"$smokeRoot = '{smoke_root}'",
            block[start:end],
            "$smokeFolders | ConvertTo-Json -Compress",
        ))
        completed = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                                   capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        folders = json.loads(completed.stdout)
        for name in SMOKE_FOLDER_VARIABLES:
            with self.subTest(variable=name):
                self.assertIn(name, folders)
                self.assertTrue(Path(folders[name]).is_relative_to(smoke_root), folders[name])

    def test_the_folders_are_set_before_the_launch_and_put_back_after_it(self) -> None:
        block = self._smoke_block()
        launch = block.index("Start-Process -FilePath $targetExe")
        setting = block.index('[Environment]::SetEnvironmentVariable($name, $smokeFolders[$name], "Process")')
        self.assertLess(setting, launch)
        cleanup = block[block.index("        finally {"):]
        self.assertIn('[Environment]::SetEnvironmentVariable($name, $oldFolders[$name], "Process")', cleanup)
        # The old two-variable form is gone, so no folder is left out of the restore.
        self.assertNotIn("$oldRoaming", block)
        self.assertNotIn("$oldLocal", block)


if __name__ == "__main__":
    unittest.main()
