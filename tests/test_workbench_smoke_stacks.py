"""A stuck smoke launch writes where every thread was waiting (159).

The build's smoke launch sometimes never ends, and the app's log says only "Workbench started."
If a smoke launch is still running after the limit, the app writes each thread's Python stack
beside its logs, so the build can show where it was stuck. A launch that ends in time writes none.
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

REPO = Path(__file__).resolve().parents[1]

SCRIPT = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, {src!r})
    from PySide6.QtCore import QTimer
    from media_manglers_workbench import app
    app.SMOKE_STACK_AFTER_SECONDS = {limit}
    if {stuck} == "slow-check":
        # A probe that runs a minute and starts a process of its own, as the py launcher does.
        PROBE = ("import os, subprocess, sys, time; "
                 "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
                 "open(os.environ['PROBE_PIDS'], 'w').write(f'{{os.getpid()}} {{child.pid}}'); "
                 "time.sleep(60)")
        def slow_check(*args, runner=None, **kwargs):
            from media_manglers_workbench import dependencies
            (runner or dependencies._default_runner)([sys.executable, "-c", PROBE], 120, None)
            raise OSError("no real readiness check in this test")
        app.run_dependency_preflight = slow_check
        # The close may only stop the check once the probe has started and recorded its child,
        # however slowly this PC starts Python; otherwise there would be nothing to prove ended.
        import os
        closing = app.WorkbenchWindow.closeEvent
        def close_after_probe(self, event):
            pids, deadline = os.environ["PROBE_PIDS"], time.monotonic() + 20
            while time.monotonic() < deadline and not (os.path.isfile(pids) and os.path.getsize(pids) > 0):
                time.sleep(0.05)
            closing(self, event)
        app.WorkbenchWindow.closeEvent = close_after_probe
    else:
        app.WorkbenchWindow.start_dependency_check = lambda self: None   # no readiness check in this test
    if {stuck} == "running":
        QTimer.singleShot(0, lambda: time.sleep(20))  # the main thread blocked well past the limit
    if {stuck} == "building":
        built = app.WorkbenchWindow.__init__
        def slow_build(self, *args, **kwargs):
            built(self, *args, **kwargs)
            time.sleep(20)                             # stuck while the window is being built
        app.WorkbenchWindow.__init__ = slow_build
    code = app.main(["--offscreen", "--smoke-test"])
    if {stuck} == "after":
        time.sleep(20)                                 # stuck after the window has closed
    sys.exit(code)
""")


class SmokeStackTests(unittest.TestCase):
    def _launch(self, stuck: str, limit: int = 12, timeout: int = 120) -> str:
        with tempfile.TemporaryDirectory() as temp:
            local = Path(temp) / "Local"
            self.probe_pids = Path(temp) / "probe-pids.txt"
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
                       MEDIA_MANGLERS_WORKBENCH_APPDATA=str(Path(temp) / "Roaming"),
                       MEDIA_MANGLERS_WORKBENCH_LOCALAPPDATA=str(local),
                       PROBE_PIDS=str(self.probe_pids))
            started = time.monotonic()
            result = subprocess.run([sys.executable, "-c", SCRIPT.format(src=str(REPO / "src"), stuck=repr(stuck), limit=limit)],
                                    cwd=temp, env=env, capture_output=True, text=True, timeout=timeout)
            self.seconds = time.monotonic() - started
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            self.pids = self.probe_pids.read_text(encoding="utf-8").split() if self.probe_pids.is_file() else []
            stacks = list(local.rglob("smoke-launch-stacks.txt"))
            self.assertEqual(len(stacks), 1, "the file is made beside the app's logs")
            return stacks[0].read_text(encoding="utf-8")

    def test_a_stuck_launch_writes_where_each_thread_waited(self) -> None:
        text = self._launch(stuck="running")
        self.assertIn("Thread", text)
        self.assertIn("in <lambda>", text, "the stack shows the code the main thread was stuck in")

    def test_a_launch_that_ends_in_time_writes_nothing(self) -> None:
        # A generous limit: a busy machine (six test processes at once) can take seconds to build the window.
        self.assertEqual(self._launch(stuck="", limit=30).strip(), "")

    def test_a_launch_stuck_while_building_its_window_is_caught_too(self) -> None:
        # The last recorded hang wrote nothing: the recorder used to start after the window was shown.
        text = self._launch(stuck="building")
        self.assertIn("in slow_build", text)

    def test_a_launch_stuck_after_closing_is_caught_too(self) -> None:
        # The recorder used to be switched off when the smoke test asked the app to close.
        text = self._launch(stuck="after")
        self.assertIn("in <module>", text)

    def test_a_slow_readiness_check_does_not_keep_the_launch_open(self) -> None:
        # The cause of 159: closing waited 5 s for the start-up readiness check and then refused,
        # quitting asked once more, and after that nothing did, so the launch ran until the build
        # gave up. Closing now stops the check (193): the launch ends long before the probe would,
        # and the probe and the process it started are both gone.
        self._launch(stuck="slow-check", limit=60, timeout=90)
        self.assertLess(self.seconds, 30, "the probe runs 60 s; the launch may not wait for it")
        self.assertEqual(len(self.pids), 2, "the probe started and recorded its child")
        for pid in self.pids:
            self.assertFalse(_running(int(pid)), f"process {pid} was left running")


def _running(pid: int) -> bool:
    listed = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                            capture_output=True, text=True, check=False).stdout
    return f'"{pid}"' in listed


if __name__ == "__main__":
    unittest.main()
