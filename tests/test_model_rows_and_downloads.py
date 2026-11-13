"""The Whisper model rows in Settings > Dependencies and the approved downloads (M2, M3, M6 and M8 of the Wave I-A
review).

- M2: Find my bug reports, the raw bin's scans and the AI Video Editor load the main model saved in Settings, which
  can differ from New Review's; it gets a row of its own (with Approve download), the editor's quick model is worked
  out from it, and a feature refuses a model readiness never checked instead of starting and failing every recording.
- M3: when the checksum probe does not finish, a model file that is merely there is never called valid.
- M6: a second approval while another model downloads is kept and started after it, never dropped.
- M8: a download that finished and was checked, but stopped at its last step, is put in place, never fetched again;
  and while a model downloads, readiness does not read it and no feature starts that would load it.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers.core import downloads  # noqa: E402
from media_manglers_workbench import dependencies  # noqa: E402
from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.resources import DependencyStatus, RuntimeResources  # noqa: E402


def _probe(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {"python_version": "3.12.10", "helper_import_ok": True, "whisper_import_ok": True,
                                  "torch_import_ok": True, "cuda_available": False, "argos_available": False,
                                  "model_known": True, "model_cached": True, "model_cache_path": "medium.pt"}
    payload.update(overrides)
    return payload


class _Runner:
    """The Python that runs Whisper: its probe answers; the models' checksum probe answers ``states``, or fails."""

    def __init__(self, python: str, states: dict[str, str] | None, probe: dict[str, object] | None = None) -> None:
        self.python = str(Path(python).resolve())
        self.states = states
        self.probe = probe or _probe()
        self.checked: list[list[str]] = []

    def __call__(self, argv: list[str], _timeout: int, _env: object) -> subprocess.CompletedProcess[str]:
        if str(Path(argv[0]).resolve()) != self.python:
            return subprocess.CompletedProcess(argv, 1, "", "synthetic")
        if "-c" in argv and argv[argv.index("-c") + 1] == dependencies._MODEL_PROBE:
            names = argv[argv.index("-c") + 2:]
            self.checked.append(list(names))
            if self.states is None:
                return subprocess.CompletedProcess(argv, 1, "", "the checksum probe timed out")
            return subprocess.CompletedProcess(argv, 0, json.dumps(
                {name: {"state": self.states.get(name, "valid"), "path": f"{name}.pt"} for name in names}), "")
        return subprocess.CompletedProcess(argv, 0, json.dumps({**self.probe, "python_path": self.python}), "")


class RowsCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.python = self.root / "Python312" / "python.exe"
        self.python.parent.mkdir(parents=True)
        self.python.write_bytes(b"placeholder")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _rows(self, runner: _Runner, **options: object) -> dict[str, DependencyStatus]:
        resources = RuntimeResources(app_root=REPO_ROOT, script_path=None, backend_source_root=None, icon_path=None,
                                     powershell_exe="", python_exe=str(self.python), ffmpeg_exe="", ffprobe_exe="",
                                     packaged=False)
        result = dependencies.run_dependency_preflight(resources, runner=runner, **options)
        return {item.key: item for item in result.dependencies if item.key.startswith("whisper_model")}


class MainModelRowTests(RowsCase):
    def test_the_main_model_saved_in_settings_gets_its_own_row_with_approve_download(self) -> None:
        runner = _Runner(str(self.python), {"small": "valid", "medium": "missing", "base.en": "valid"})
        rows = self._rows(runner, selected_model="small", main_model="medium", quick_model="small")
        self.assertEqual(rows["whisper_model"].model, "small")
        self.assertEqual(rows["whisper_model_main"].model, "medium")
        self.assertEqual(rows["whisper_model_main"].action_kind, "approve_model_download")
        self.assertIn("Find my bug reports", rows["whisper_model_main"].purpose)

    def test_the_rows_follow_the_settings_model_the_features_load(self) -> None:
        host = types.SimpleNamespace(run_settings={"whisper_model": "small"}, app_settings={"whisper_model": "medium"})
        selected, main, quick = WorkbenchWindow.readiness_models(host)
        self.assertEqual((selected, main, quick), ("small", "medium", "small"))
        host.app_settings["race_video_quick_whisper_model"] = "main"
        self.assertEqual(WorkbenchWindow.readiness_models(host)[2], "medium", "the editor's quick model, from main")

    def test_a_feature_refuses_a_model_readiness_never_checked(self) -> None:
        rows = [DependencyStatus("Whisper model: small", "ready", key="whisper_model", model="small"),
                DependencyStatus("Whisper model: base.en", "ready", key="whisper_model_voice", model="base.en")]
        host = types.SimpleNamespace(resources=types.SimpleNamespace(dependencies=rows, preflight_complete=True),
                                     model_download_thread=None, app_settings={"whisper_model": "medium"})
        reasons = WorkbenchWindow.model_blockers(host, WorkbenchWindow.run_models(host, "bug_reports",
                                                                                   {"whisper_model": "medium"}))
        self.assertEqual(len(reasons), 1)
        self.assertIn("medium", reasons[0])
        self.assertIn("Refresh readiness", reasons[0])

    def test_every_feature_that_loads_whisper_checks_its_models_before_it_starts(self) -> None:
        host = types.SimpleNamespace(app_settings={"whisper_model": "medium"})
        self.assertEqual(WorkbenchWindow.run_models(host, "raw_scan", {}), ["medium"])
        self.assertEqual(WorkbenchWindow.run_models(host, "raw_deep_scan", {}), ["medium"])
        self.assertEqual(WorkbenchWindow.run_models(host, "editor_prepare", {}), ["medium", "base.en", "small"])
        self.assertEqual(WorkbenchWindow.run_models(host, "bug_reports", {"whisper_model": "large-v3"}),
                         ["large-v3", "base.en"])


class UnfinishedCheckTests(RowsCase):
    def test_a_model_file_that_is_merely_there_is_never_called_valid(self) -> None:
        runner = _Runner(str(self.python), None, _probe(model_cached=True))
        rows = self._rows(runner, selected_model="medium")
        row = rows["whisper_model"]
        self.assertNotEqual(row.status, "ready")
        self.assertEqual(row.status, "not_checked")
        self.assertNotIn("matches the file Whisper published", row.detail)
        self.assertIn("not checked", row.detail)
        self.assertEqual(row.action_kind, "approve_model_download", "Approve download stays offered")
        host = types.SimpleNamespace(resources=types.SimpleNamespace(dependencies=list(rows.values()),
                                                                     preflight_complete=True),
                                     model_download_thread=None)
        self.assertEqual(WorkbenchWindow.model_blockers(host, ["medium"]), [],
                         "not blocking: the run checks the model before it uses it")


class _Thread:
    def __init__(self, models: list[str]) -> None:
        self.models = models


class SecondApprovalTests(unittest.TestCase):
    def test_a_second_approval_while_a_model_downloads_is_kept_and_started_after_it(self) -> None:
        summary = mock.Mock()
        host = types.SimpleNamespace(model_download_thread=_Thread(["medium"]), queued_model_downloads=[],
                                     dependency_summary=summary, _write_workbench_log=mock.Mock())
        self.assertTrue(WorkbenchWindow.start_model_download(host, ["base.en"]))
        self.assertEqual(host.queued_model_downloads, ["base.en"])
        text = summary.setText.call_args.args[0]
        self.assertIn("medium is downloading now", text)
        self.assertIn("base.en will download", text)
        # When the first ends, the waiting one starts.
        worker = host.model_download_thread
        worker.deleteLater = mock.Mock()
        host.start_model_download = mock.Mock()
        host.start_dependency_check = mock.Mock()
        with mock.patch("media_manglers_workbench.app.QTimer.singleShot", side_effect=lambda _ms, call: call()):
            WorkbenchWindow._model_download_stopped(host, worker)
        host.start_model_download.assert_called_once_with(["base.en"])
        self.assertEqual(host.queued_model_downloads, [])


class DownloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _opener(body: bytes, calls: list[str]):
        class Response(io.BytesIO):
            headers = {"Content-Length": str(len(body))}

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                self.close()

        def opener(url: str, _timeout: float):
            calls.append(url)
            return Response(body)

        return opener

    def test_a_finished_checked_download_left_at_its_last_step_is_put_in_place_not_fetched_again(self) -> None:
        body = b"the published model" * 1000
        target = self.root / "cache" / "medium.pt"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"damaged")
        partial = target.with_name(target.name + downloads.PARTIAL_SUFFIX)
        partial.write_bytes(body)  # the last try finished and was checked, then the old file was held
        calls: list[str] = []
        downloads.download_file("https://models.invalid/medium.pt", target, hashlib.sha256(body).hexdigest(),
                                replace=True, opener=self._opener(body, calls))
        self.assertEqual(calls, [], "nothing was downloaded again")
        self.assertEqual(target.read_bytes(), body)
        self.assertFalse(partial.exists())

    def test_a_partial_download_that_does_not_match_is_never_used(self) -> None:
        body = b"the published model" * 1000
        target = self.root / "cache" / "medium.pt"
        target.parent.mkdir(parents=True)
        partial = target.with_name(target.name + downloads.PARTIAL_SUFFIX)
        partial.write_bytes(body[:100])  # cut off part-way
        calls: list[str] = []
        downloads.download_file("https://models.invalid/medium.pt", target, hashlib.sha256(body).hexdigest(),
                                opener=self._opener(body, calls))
        self.assertEqual(len(calls), 1, "downloaded again from the start")
        self.assertEqual(target.read_bytes(), body)


class DownloadingModelTests(RowsCase):
    def test_readiness_never_reads_a_model_while_it_downloads(self) -> None:
        runner = _Runner(str(self.python), {"medium": "damaged", "base.en": "valid"})
        rows = self._rows(runner, selected_model="medium", downloading_models=["medium"])
        self.assertNotIn("medium", [name for names in runner.checked for name in names])
        self.assertEqual(rows["whisper_model"].status, "not_checked")
        self.assertIn("Downloading now", rows["whisper_model"].detail)

    def test_no_feature_starts_that_would_load_a_model_while_it_downloads(self) -> None:
        rows = [DependencyStatus("Whisper model: medium", "needs_setup", key="whisper_model", model="medium",
                                 detail="Not on this PC yet.")]
        host = types.SimpleNamespace(resources=types.SimpleNamespace(dependencies=rows, preflight_complete=True),
                                     model_download_thread=_Thread(["medium"]))
        reasons = WorkbenchWindow.model_blockers(host, ["medium"])
        self.assertEqual(len(reasons), 1)
        self.assertIn("downloading now", reasons[0])


if __name__ == "__main__":
    unittest.main()
