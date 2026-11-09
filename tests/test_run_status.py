"""213: one status rule for every feature; notices that need no action never turn a run yellow."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from media_manglers_workbench import run_status  # noqa: E402
from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.command_builder import build_workflow_command  # noqa: E402
from media_manglers_workbench.metadata import WORKFLOW_FULL_REVIEW  # noqa: E402
from media_manglers_workbench.runner import RunnerResult  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION, build_default_settings  # noqa: E402
from tests.test_workbench_bug_reports import ScriptedBackend, _resources  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
# A clean Full Review's notices, as the backend now logs them, and a transcript line with the word in it.
CLEAN_RUN = [
    "[2026-01-02 10:00:00] [INFO] OpenAiProject Private was provided, but OpenAiProject only applies in AI or Hybrid mode.",
    "[2026-01-02 10:00:20] [INFO] Whisper estimate uses a GPU heuristic rather than a transcription benchmark so estimation can never kill the real run.",
    "[2026-01-02 10:05:00] [INFO] Codex evidence package mode uses Local Whisper transcription only.",
    "  The pit limiter warning light stays on after the stop.",
]


class StatusRuleTests(unittest.TestCase):
    def test_only_what_the_backend_marks_as_a_warning_counts(self) -> None:
        for line in CLEAN_RUN + ["Saved warning-signs.mkv"]:
            self.assertFalse(run_status.counts_as_warning(line), line)
        for line in ("[2026-01-02 10:00:00] [WARN] Voice track detection could not run.",
                     "WARNING: The input folder C:\\x is a temporary folder."):
            self.assertTrue(run_status.counts_as_warning(line), line)

    def test_the_states_and_their_words(self) -> None:
        self.assertEqual(run_status.decide(succeeded=True), "completed")
        self.assertEqual(run_status.decide(succeeded=True, warnings=1), "complete_with_warnings")
        self.assertEqual(run_status.decide(succeeded=True, problems=1), "completed_with_problems")
        self.assertEqual(run_status.decide(succeeded=False, partial=True), "completed_with_problems")
        self.assertEqual(run_status.decide(succeeded=False), "failed")
        self.assertEqual([run_status.stage_text(state) for state in
                          ("completed", "complete_with_warnings", "completed_with_problems", "failed", "?")],
                         ["Complete", "Complete with warnings", "Completed with problems", "Failed", "Failed"])

    def test_the_backend_logs_these_notices_as_information(self) -> None:
        text = (REPO_ROOT / "Video Mangler.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('Write-Log $warning "INFO"', text)
        self.assertIn('Write-Log $openAiProjectResolutionNote "INFO"', text)
        self.assertIn('ResolutionNoteLevel  = "INFO"', text)
        self.assertIn("Nothing from this recording goes into the package.\" -f $video.FullName) \"INFO\"", text)

    def test_the_openai_project_is_sent_only_where_it_means_something(self) -> None:
        settings = {**build_default_settings(), "input_path": "C:\\in\\a.mkv", "open_ai_project": "Project"}
        local = build_workflow_command({**settings, "processing_mode": "Local"}, workflow=WORKFLOW_FULL_REVIEW).argv
        ai = build_workflow_command({**settings, "processing_mode": "AI"}, workflow=WORKFLOW_FULL_REVIEW).argv
        self.assertNotIn("-OpenAiProject", local)
        self.assertIn("-OpenAiProject", ai)


class CleanRunIsGreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_a_clean_run_with_notices_ends_green_and_a_real_warning_yellow(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = root / "settings.json"
            settings.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
                "log_folder": str(root / "logs"), "temp_folder": str(root / "temp"),
                "output_folder": str(root / "out")}}), encoding="utf-8")
            window = WorkbenchWindow(settings_path=settings, profiles_dir=root / "profiles",
                                     runner_factory=ScriptedBackend, resources=_resources())
            try:
                states = []
                for extra in ([], ["[2026-01-02 10:10:00] [WARN] Voice track detection could not run."]):
                    window._initialize_progress_queue([str(root / "a.mkv")])
                    window.progress_warning_count = 0
                    for line in CLEAN_RUN + extra:
                        window.on_log_line("stdout", line)
                    with patch.object(window, "_discover_completed_evidence_package", return_value=None):
                        window.on_job_finished(RunnerResult(status="succeeded", exit_code=0))
                    states.append(window.progress_heartbeat.text())
            finally:
                window._closing_after_smoke = True
                window.close()
                self.app.processEvents()
        self.assertEqual(states, ["Complete", "Complete with warnings"])


if __name__ == "__main__":
    unittest.main()
