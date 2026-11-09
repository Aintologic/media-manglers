"""A feature run that opts out does not take over the last evidence package (150, Risk 1).

Today any run started from a feature page that leaves an evidence package behind becomes the
operator's "last evidence package" and opens on Evidence. The AI Video Editor's analysis reuses the
transcription stage, which writes such a package, so its runs ask the shared run service not to
claim it. Runs that do not ask (Find my bug reports) keep today's behaviour.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.command_builder import CommandSpec  # noqa: E402
from media_manglers_workbench.resources import DependencyStatus, RuntimeResources  # noqa: E402
from media_manglers_workbench.runner import RunnerResult  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PACKAGE = REPO_ROOT / "tests" / "fixtures" / "workbench" / "evidence_package"


def _resources() -> RuntimeResources:
    return RuntimeResources(
        app_root=REPO_ROOT, script_path=REPO_ROOT / "Video Mangler.ps1", backend_source_root=REPO_ROOT / "src",
        icon_path=REPO_ROOT / "assets" / "Video Mangler.ico", powershell_exe="powershell", python_exe="py",
        ffmpeg_exe="ffmpeg", ffprobe_exe="ffprobe", packaged=False,
        dependencies=[DependencyStatus("test backend", "ready")],
    )


class PackageWritingRunner:
    """Stands in for a run that leaves an evidence package in its output folder."""

    output: Path | None = None

    def cancel(self) -> None:
        return None

    def run(self, command, on_log=None, *, cwd=None) -> RunnerResult:
        shutil.copytree(FIXTURE_PACKAGE, self.output / "codex-evidence-package")
        if on_log:
            on_log("stdout", "analysis done")
        return RunnerResult(status="succeeded", exit_code=0, stdout_lines=["analysis done"], error="")


class Listener:
    def __init__(self) -> None:
        self.finished = None

    def on_log_line(self, *args) -> None:
        return None

    def on_finished(self, result) -> None:
        self.finished = result


class RunServiceOptOutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.mine = self.root / "my-bug-report-package"
        shutil.copytree(FIXTURE_PACKAGE, self.mine)
        settings = self.root / "settings.json"
        settings.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
            "log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
            "output_folder": str(self.root / "out"), "last_evidence_package": str(self.mine),
        }}), encoding="utf-8")
        self.window = WorkbenchWindow(settings_path=settings, profiles_dir=self.root / "profiles",
                                      runner_factory=PackageWritingRunner, resources=_resources())
        self.window.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.window._closing_after_smoke = True
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def _run(self, **kwargs) -> Listener:
        output = self.root / "video-project"
        output.mkdir()
        PackageWritingRunner.output = output
        listener = Listener()
        started = self.window.start_external_run(
            CommandSpec(argv=["analysis"], preview="analysis"), title="AI Video Editor: analysis",
            settings={"output_folder": str(output)}, queue_items=[str(self.root / "race.mkv")],
            listener=listener, **kwargs)
        self.assertTrue(started)
        deadline = time.monotonic() + 10
        while self.window.runner_thread is not None and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertIsNotNone(listener.finished)
        return listener

    def test_an_opted_out_run_leaves_the_last_package_and_evidence_alone(self) -> None:
        evidence_before = self.window.current_package
        self._run(evidence_package=False)
        self.assertEqual(self.window.app_settings["last_evidence_package"], str(self.mine))
        self.assertIs(self.window.current_package, evidence_before)
        history = self.window.recent_runs()
        self.assertTrue(any("AI Video Editor" in json.dumps(run) for run in history), "the run is still in History")

    def test_a_run_that_does_not_opt_out_behaves_as_before(self) -> None:
        self._run()
        self.assertEqual(Path(self.window.app_settings["last_evidence_package"]),
                         self.root / "video-project" / "codex-evidence-package")


if __name__ == "__main__":
    unittest.main()
