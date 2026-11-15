"""A Workbench that crashes takes its runs with it (M15 of the Wave I-A review).

The Workbench's runs used to keep going, hidden, after a crash or an end from Task Manager; a paused one waited for a
Resume that could never come, kept its tool frozen and held ``MediaManglers.Running`` for good. Now every run and
download the Workbench starts is in a job object that Windows ends with the Workbench, and a paused run whose
Workbench is gone ends itself. Each test kills a stand-in Workbench, as Task Manager would.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers.core import app_locks  # noqa: E402

SCRIPT = REPO_ROOT / "Video Mangler.ps1"

STAND_IN_WORKBENCH = textwrap.dedent("""
    import os, subprocess, sys
    sys.path.insert(0, {src!r})
    from media_manglers.core import safe_write
    from media_manglers_workbench.child_jobs import keep_with_workbench
    # A run, which itself starts a tool, as the backend starts FFmpeg.
    run = subprocess.Popen([sys.executable, "-c", "import subprocess, sys, time; "
                            "tool = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']); "
                            "print(tool.pid, flush=True); time.sleep(120)"], stdout=subprocess.PIPE, text=True)
    kept = keep_with_workbench(run)
    tool = run.stdout.readline().strip()
    print(kept, run.pid, tool, flush=True)
    sys.stdin.readline()
""")


def _alive(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _wait_gone(pids: list[int], seconds: float) -> list[int]:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        alive = [pid for pid in pids if _alive(pid)]
        if not alive:
            return []
        time.sleep(0.2)
    return [pid for pid in pids if _alive(pid)]


@unittest.skipUnless(os.name == "nt", "Windows job objects")
class RunsEndWithTheWorkbenchTests(unittest.TestCase):
    def test_a_run_and_the_tools_it_started_end_when_the_workbench_is_killed(self) -> None:
        workbench = subprocess.Popen([sys.executable, "-c", STAND_IN_WORKBENCH.format(src=str(REPO_ROOT / "src"))],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            kept, run, tool = workbench.stdout.readline().split()
            self.assertEqual(kept, "True")
            self.assertTrue(_alive(int(run)) and _alive(int(tool)))
            workbench.kill()  # as Task Manager ends it
            workbench.wait(10)
            self.assertEqual(_wait_gone([int(run), int(tool)], 10), [], "the run and its tool ended with it")
        finally:
            if workbench.poll() is None:
                workbench.kill()


@unittest.skipUnless(os.name == "nt", "the backend runs on Windows")
class PausedRunEndsTests(unittest.TestCase):
    FUNCTIONS = ("Get-MMRunControl", "Test-MMSourceSkipRequested", "Test-MMPauseRequested", "Get-MMProcessTreeIds",
                 "Stop-MMProcessTree", "Set-MMProcessTreeSuspended", "Format-DurationHuman",
                 "Test-MMStartingAppAlive", "Wait-MMWhilePaused")

    def test_a_paused_run_ends_and_lets_go_of_the_running_lock_when_its_workbench_is_gone(self) -> None:
        lock = f"MediaManglers.Running.test-{os.getpid()}-{time.monotonic_ns()}"
        with tempfile.TemporaryDirectory() as temp:
            control = Path(temp) / "run-control.json"
            control.write_text('{"pause": true, "skip": []}', encoding="utf-8")
            workbench = subprocess.Popen(
                [sys.executable, "-c", "import os, sys; sys.path.insert(0, %r); "
                 "from media_manglers.core import safe_write; "
                 "print('%%d:%%d' %% (os.getpid(), safe_write._process_start_time(os.getpid())), flush=True); "
                 "sys.stdin.readline()" % str(REPO_ROOT / "src")],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            marker = workbench.stdout.readline().strip()
            names = ",".join(f"'{name}'" for name in self.FUNCTIONS)
            harness = Path(temp) / "harness.ps1"
            harness.write_text(textwrap.dedent(f"""
                $ErrorActionPreference = 'Stop'
                $held = New-Object System.Threading.Mutex($false, '{lock}')
                $tokens = $null; $parseErrors = $null
                $ast = [System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', [ref]$tokens, [ref]$parseErrors)
                $wanted = @({names})
                foreach ($node in $ast.FindAll({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $wanted -contains $n.Name }}, $true)) {{
                    Invoke-Expression $node.Extent.Text
                }}
                function Write-Log {{ param($Message, $Level) [Console]::Out.WriteLine("LOG: $Message") }}
                function Write-MMProgressV1 {{ }}
                $script:MMRunControlPath = '{control}'
                $script:MMRunControlCache = $null
                $script:MMRunControlReadAt = [datetime]::MinValue
                $script:MMCurrentSourcePath = ''
                $script:MMBackgroundReviewVideos = $null
                $tool = Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-Command', 'Start-Sleep -Seconds 120') -PassThru -WindowStyle Hidden
                [Console]::Out.WriteLine("TOOL $($tool.Id)")
                $null = Wait-MMWhilePaused -Process $tool -Where 'test'
                [Console]::Out.WriteLine('RESUMED')
            """).strip(), encoding="utf-8")
            run = subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   env={**os.environ, "MEDIA_MANGLERS_APP_PROCESS": marker})
            try:
                tool = int(run.stdout.readline().split()[1])
                time.sleep(2)
                self.assertIsNone(run.poll(), "still paused while its Workbench runs")
                self.assertTrue(app_locks.is_held(lock))
                workbench.kill()
                workbench.wait(10)
                started = time.monotonic()
                try:
                    out, _err = run.communicate(timeout=20)
                except subprocess.TimeoutExpired:
                    run.kill()
                    self.fail("the paused run waited on after its Workbench was gone")
                self.assertLess(time.monotonic() - started, 10)
            finally:
                if workbench.poll() is None:
                    workbench.kill()
                if run.poll() is None:
                    run.kill()
            self.assertEqual(run.returncode, 3)
            self.assertIn("has closed, so the paused run ends here", out)
            self.assertNotIn("RESUMED", out)
            self.assertEqual(_wait_gone([tool], 10), [], "the frozen tool ended too")
            self.assertFalse(app_locks.is_held(lock), "the running lock is free again")


class PausedScanEndsTests(unittest.TestCase):
    def test_a_paused_raw_bin_scan_ends_when_its_workbench_is_gone(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            control = Path(temp) / "run-control.json"
            control.write_text('{"pause": true, "skip": []}', encoding="utf-8")
            workbench = subprocess.Popen(
                [sys.executable, "-c", "import os, sys; sys.path.insert(0, %r); "
                 "from media_manglers.core import safe_write; "
                 "print('%%d:%%d' %% (os.getpid(), safe_write._process_start_time(os.getpid())), flush=True); "
                 "sys.stdin.readline()" % str(REPO_ROOT / "src")],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            marker = workbench.stdout.readline().strip()
            code = ("import sys; sys.path.insert(0, %r); from media_manglers.core import raw_bin_library as r; "
                    "r._Control(%r).wait_while_paused(); print('RESUMED')" % (str(REPO_ROOT / "src"), str(control)))
            scan = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, env={**os.environ, "MEDIA_MANGLERS_APP_PROCESS": marker})
            try:
                time.sleep(3)
                self.assertIsNone(scan.poll(), "still paused while its Workbench runs")
                workbench.kill()
                workbench.wait(10)
                out, err = scan.communicate(timeout=20)
            finally:
                for process in (workbench, scan):
                    if process.poll() is None:
                        process.kill()
            self.assertEqual(scan.returncode, 3, err)
            self.assertIn("has closed, so the paused scan ends here", err)
            self.assertNotIn("RESUMED", out)


if __name__ == "__main__":
    unittest.main()
