from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers_workbench.dependencies import (  # noqa: E402
    DependencyCheckStopped,
    StoppableRunner,
    run_dependency_preflight,
)
from media_manglers_workbench.resources import RuntimeResources  # noqa: E402


def _status(result, key: str):
    return next(item for item in result.dependencies if item.key == key)


def _running(pid: int) -> bool:
    listed = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return f'"{pid}"' in listed


class FakeDependencyRunner:
    def __init__(self, python_payloads: dict[str, dict[str, object]]) -> None:
        self.python_payloads = python_payloads

    def __call__(
        self,
        argv: list[str],
        _timeout: int,
        _env: dict[str, str] | None,
    ) -> subprocess.CompletedProcess[str]:
        executable = str(Path(argv[0]).resolve())
        if executable in self.python_payloads and "-c" in argv:
            payload = {**self.python_payloads[executable], "python_path": executable}
            return subprocess.CompletedProcess(argv, 0, json.dumps(payload) + "\n", "")
        name = Path(argv[0]).name.casefold()
        if "powershell" in name:
            return subprocess.CompletedProcess(argv, 0, "5.1.22621.4391\n", "")
        if "ffprobe" in name:
            return subprocess.CompletedProcess(argv, 0, "ffprobe version synthetic-7.1\n", "")
        if "ffmpeg" in name:
            return subprocess.CompletedProcess(argv, 0, "ffmpeg version synthetic-7.1\n", "")
        if "yt-dlp" in name:
            return subprocess.CompletedProcess(argv, 0, "2026.07.01\n", "")
        return subprocess.CompletedProcess(argv, 1, "", "synthetic command failure")


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "python_version": "3.12.4",
        "helper_import_ok": True,
        "whisper_import_ok": True,
        "whisper_version": "20250625",
        "torch_import_ok": True,
        "torch_version": "2.7.1",
        "cuda_version": "12.8",
        "cuda_available": True,
        "cuda_device_count": 1,
        "model_known": True,
        "model_cached": True,
        "model_cache_path": r"C:\SyntheticCache\medium.pt",
        "error": "",
    }
    payload.update(overrides)
    return payload


class WorkbenchDependencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.python = self._exe("python-ready.exe")
        self.powershell = self._exe("powershell.exe")
        self.ffmpeg = self._exe("ffmpeg.exe")
        self.ffprobe = self._exe("ffprobe.exe")
        self.ytdlp = self._exe("yt-dlp.exe")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _exe(self, relative: str) -> str:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic executable placeholder")
        return str(path.resolve())

    def _resources(self, *, packaged: bool = False) -> RuntimeResources:
        return RuntimeResources(
            app_root=REPO_ROOT,
            script_path=REPO_ROOT / "Video Mangler.ps1",
            backend_source_root=REPO_ROOT / "src",
            icon_path=REPO_ROOT / "assets" / "Video Mangler.ico",
            powershell_exe=self.powershell,
            python_exe=self.python,
            ffmpeg_exe=self.ffmpeg,
            ffprobe_exe=self.ffprobe,
            packaged=packaged,
            ytdlp_exe=self.ytdlp,
        )

    def _run(
        self,
        payloads: dict[str, dict[str, object]] | None = None,
        *,
        resources: RuntimeResources | None = None,
        candidates: list[str] | None = None,
        configured_python: str = "",
    ):
        if payloads is None:
            payloads = {self.python: _payload()}
        return run_dependency_preflight(
            resources or self._resources(),
            selected_model="medium",
            configured_python=configured_python,
            python_candidates=list(payloads) if candidates is None else candidates,
            runner=FakeDependencyRunner(payloads),
            checked_at="2026-07-16T12:00:00+00:00",
        )

    def test_fully_ready_cuda_runtime_reports_exact_components(self) -> None:
        result = self._run()
        for key in (
            "backend_sidecar",
            "ytdlp",
            "powershell",
            "python",
            "python_helper",
            "ffmpeg",
            "ffprobe",
            "whisper",
            "whisper_model",
            "torch",
            "cuda",
            "cpu_fallback",
        ):
            self.assertEqual(_status(result, key).status, "ready", key)
        self.assertEqual(result.python_exe, self.python)
        self.assertEqual(_status(result, "python").last_checked, "2026-07-16T12:00:00+00:00")
        self.assertEqual(result.ytdlp_exe, self.ytdlp)

    def test_old_ytdlp_is_actionable_before_url_review(self) -> None:
        class OldYtDlpRunner(FakeDependencyRunner):
            def __call__(self, argv, timeout, env):
                if "yt-dlp" in Path(argv[0]).name.casefold():
                    return subprocess.CompletedProcess(argv, 0, "2026.01.01\n", "")
                return super().__call__(argv, timeout, env)

        result = run_dependency_preflight(
            self._resources(),
            selected_model="medium",
            python_candidates=[self.python],
            runner=OldYtDlpRunner({self.python: _payload()}),
            checked_at="2026-07-16T12:00:00+00:00",
        )
        ytdlp = _status(result, "ytdlp")
        self.assertEqual(ytdlp.status, "update_recommended")
        self.assertEqual(ytdlp.action_kind, "install_guide")
        self.assertIn("update", ytdlp.detail.casefold())

    def test_cpu_only_is_ready_with_cuda_optional(self) -> None:
        result = self._run(
            {self.python: _payload(cuda_available=False, cuda_device_count=0, cuda_version="")}
        )
        self.assertEqual(_status(result, "cuda").status, "optional")
        self.assertEqual(_status(result, "cpu_fallback").status, "ready")
        self.assertIn("CPU", _status(result, "cpu_fallback").detail)

    def test_multiple_python_installations_select_healthiest_runtime(self) -> None:
        other = self._exe("python-cpu.exe")
        result = self._run(
            {
                other: _payload(cuda_available=False, cuda_device_count=0),
                self.python: _payload(cuda_available=True, cuda_device_count=1),
            }
        )
        self.assertEqual(result.python_exe, self.python)
        self.assertIn("2 usable Python", _status(result, "python").detail)

    def test_windows_store_alias_only_needs_real_python_path(self) -> None:
        alias = self._exe(r"Microsoft\WindowsApps\python.exe")
        result = self._run({}, candidates=[alias])
        self.assertEqual(_status(result, "python").status, "needs_setup")
        self.assertIn("Windows Store alias", _status(result, "python").detail)
        self.assertEqual(_status(result, "python").action_kind, "choose_python")

    def test_helper_whisper_torch_and_model_failures_are_distinct(self) -> None:
        result = self._run(
            {
                self.python: _payload(
                    helper_import_ok=False,
                    whisper_import_ok=False,
                    whisper_version="",
                    torch_import_ok=False,
                    torch_version="",
                    cuda_available=False,
                    cuda_device_count=0,
                    model_known=False,
                    model_cached=False,
                    error="synthetic imports unavailable",
                )
            }
        )
        self.assertEqual(_status(result, "python").status, "ready")
        self.assertEqual(_status(result, "python_helper").status, "needs_setup")
        self.assertEqual(_status(result, "whisper").status, "needs_setup")
        self.assertEqual(_status(result, "torch").status, "needs_setup")
        self.assertEqual(_status(result, "cpu_fallback").status, "unavailable")
        self.assertEqual(_status(result, "whisper_model").status, "needs_setup")

    def test_missing_model_requires_explicit_download_approval_action(self) -> None:
        result = self._run({self.python: _payload(model_cached=False)})
        model = _status(result, "whisper_model")
        self.assertEqual(model.status, "needs_setup")
        self.assertEqual(model.action_kind, "approve_model_download")
        self.assertIn("1.5 GB", model.detail)

    def test_missing_ffmpeg_and_ffprobe_are_independent(self) -> None:
        resources = self._resources()
        resources.ffmpeg_exe = str(self.root / "missing-ffmpeg.exe")
        resources.ffprobe_exe = str(self.root / "missing-ffprobe.exe")
        result = self._run(resources=resources)
        self.assertEqual(_status(result, "ffmpeg").status, "needs_setup")
        self.assertEqual(_status(result, "ffprobe").status, "needs_setup")
        self.assertEqual(_status(result, "ffmpeg").action_kind, "choose_ffmpeg")
        self.assertEqual(_status(result, "ffprobe").action_kind, "choose_ffprobe")

    def test_inaccessible_configured_python_does_not_fall_back_silently(self) -> None:
        missing = str(self.root / "configured-missing-python.exe")
        result = run_dependency_preflight(
            self._resources(),
            selected_model="medium",
            configured_python=missing,
            runner=FakeDependencyRunner({}),
            checked_at="2026-07-16T12:00:00+00:00",
        )
        self.assertEqual(_status(result, "python").status, "needs_setup")
        self.assertEqual(result.python_exe, "")

    def test_refresh_after_tool_correction_becomes_ready(self) -> None:
        resources = self._resources()
        missing_ffmpeg = self.root / "corrected-ffmpeg.exe"
        resources.ffmpeg_exe = str(missing_ffmpeg)
        first = self._run(resources=resources)
        self.assertEqual(_status(first, "ffmpeg").status, "needs_setup")
        missing_ffmpeg.write_bytes(b"synthetic executable placeholder")
        second = self._run(resources=resources)
        self.assertEqual(_status(second, "ffmpeg").status, "ready")

    def test_stopping_a_probe_ends_it_and_the_process_it_started(self) -> None:
        # 193: closing the Workbench stops the readiness check at once. A probe that starts a
        # process of its own (the py launcher does) is ended with that process.
        pids = self.root / "probe-pids.txt"
        probe = (
            "import os, subprocess, sys, time; "
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
            f"open({str(pids)!r}, 'w').write(f'{{os.getpid()}} {{child.pid}}'); "
            "time.sleep(60)"
        )
        runner = StoppableRunner()
        outcome: list[BaseException] = []

        def run() -> None:
            try:
                runner([sys.executable, "-c", probe], 120, None)
            except BaseException as exc:  # noqa: BLE001 - the test records what ended the call
                outcome.append(exc)

        worker = threading.Thread(target=run)
        worker.start()
        deadline = time.monotonic() + 30
        while not pids.is_file() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(pids.is_file(), "the probe started")
        started = time.monotonic()
        runner.stop()
        worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(len(outcome), 1)
        self.assertIsInstance(outcome[0], DependencyCheckStopped)
        for pid in pids.read_text(encoding="utf-8").split():
            self.assertFalse(_running(int(pid)), f"process {pid} was left running")
        with self.assertRaises(DependencyCheckStopped):
            runner([sys.executable, "-c", "pass"], 30, None)

    def test_a_probe_past_its_time_is_ended_without_waiting_on_its_children(self) -> None:
        # subprocess.run waits without a limit for a child the probe started; this may not.
        probe = (
            "import subprocess, sys, time; "
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
            "time.sleep(60)"
        )
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            StoppableRunner()([sys.executable, "-c", probe], 3, None)
        self.assertLess(time.monotonic() - started, 15)

    def test_a_stopped_check_reports_nothing(self) -> None:
        runner = StoppableRunner()
        runner.stop()
        with self.assertRaises(DependencyCheckStopped):
            run_dependency_preflight(
                self._resources(),
                selected_model="medium",
                python_candidates=[self.python],
                runner=runner,
                checked_at="2026-07-16T12:00:00+00:00",
            )

    def test_source_and_packaged_preflight_report_consistent_truth(self) -> None:
        source = self._run(resources=self._resources(packaged=False))
        packaged = self._run(resources=self._resources(packaged=True))
        source_states = [(item.key, item.status, item.version) for item in source.dependencies]
        packaged_states = [(item.key, item.status, item.version) for item in packaged.dependencies]
        self.assertEqual(source_states, packaged_states)


if __name__ == "__main__":
    unittest.main()
