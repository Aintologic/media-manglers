"""Shared stand-ins for the Wave 8 tests (227).

The waveform builds run the real ``track-levels`` helper as its own process, exactly as the app does:
measuring inside the test process would compete with the test for Python itself and crawl.
"""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys
import threading

from media_manglers_workbench.runner import RunnerResult, SubprocessRunner

REPO_ROOT = Path(__file__).resolve().parents[1]


class CountingLevelsRunner(SubprocessRunner):
    """The app's own runner, counting the helper runs it starts."""

    runs: list[list[str]] = []
    # Each run's request payload, read before the service removes the run's folder.
    payloads: list[dict] = []
    lock = threading.Lock()

    def run(self, command, on_log=None, *, cwd=None) -> RunnerResult:
        argv = list(command.argv)
        with self.lock:
            CountingLevelsRunner.runs.append(argv)
            if "--request-file" in argv:
                request = Path(argv[argv.index("--request-file") + 1])
                CountingLevelsRunner.payloads.append(json.loads(request.read_text(encoding="utf-8"))["payload"])
        return super().run(command, on_log, cwd=cwd)


def helper_resources(resources, ffmpeg: str, ffprobe: str):
    """Test resources whose helper commands run with this Python and this checkout's source."""

    return replace(resources, python_exe=sys.executable, backend_source_root=REPO_ROOT / "src",
                   ffmpeg_exe=ffmpeg, ffprobe_exe=ffprobe)
