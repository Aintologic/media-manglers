"""Opening and saving the Workbench keeps every setting the operator has.

Guard for 150 (Product Continuity): a new feature may add settings of its own, but it must not
change, drop or reset existing ones. The test starts from a settings file where every value that
can be changed differs from the factory default, opens the main window, saves, and compares.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.resources import DependencyStatus, RuntimeResources  # noqa: E402
from media_manglers_workbench.runner import FakeRunner  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION, build_default_settings  # noqa: E402

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


def _changed(value, root: Path, key: str):
    """A value of the same type as ``value`` that differs from it."""

    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 3
    if isinstance(value, float):
        return value + 0.5
    if isinstance(value, str):
        if key.endswith(("_folder", "_path", "_dir")) or "folder" in key:
            return str(root / f"chosen-{key}")
        return value
    return value


class SettingsRoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_open_and_save_keeps_every_existing_setting(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            defaults = build_default_settings(repo_root=str(REPO_ROOT))
            mine = {key: _changed(value, root, key) for key, value in defaults.items()}
            mine.update({
                "log_folder": str(root / "logs"),
                "temp_folder": str(root / "temp"),
                "output_folder": str(root / "out"),
            })
            path = root / "settings.json"
            path.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": mine}), encoding="utf-8")
            before = json.loads(path.read_text(encoding="utf-8"))["settings"]
            non_default = [key for key in defaults if before[key] != defaults[key]]
            self.assertGreaterEqual(len(non_default), 50, "the test must start from an operator's own values")

            window = WorkbenchWindow(settings_path=path, profiles_dir=root / "profiles",
                                     runner_factory=FakeRunner, resources=_resources())
            try:
                window.show()
                self.app.processEvents()
                window.save_app_settings()
            finally:
                window._closing_after_smoke = True
                window.close()
                self.app.processEvents()

            after = json.loads(path.read_text(encoding="utf-8"))["settings"]
            missing = sorted(set(before) - set(after))
            changed = {key: (before[key], after[key]) for key in before if key in after and after[key] != before[key]}
            self.assertEqual(missing, [], "settings dropped on open and save")
            self.assertEqual(changed, {}, "settings changed on open and save")


if __name__ == "__main__":
    unittest.main()
