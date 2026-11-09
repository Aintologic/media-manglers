"""Workbench backends for running generated commands."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
import subprocess
import threading
import time
from typing import Callable, Iterable

from .command_builder import CommandSpec


LogCallback = Callable[[str, str], None]


def _failure_summary(stdout_lines: list[str], stderr_lines: list[str]) -> str:
    lines = [line.strip() for line in [*stderr_lines, *stdout_lines] if line.strip()]
    for pattern in (
        r"(?i)^ERROR:\s*(.+)$",
        r"(?i)^FAIL(?:URE)?\s*:?[ \t]+(.+)$",
        r"(?i)^\[[^\]]*FAIL[^\]]*\]\s*(.+)$",
        r"(?i)^(.+failed with exit code\s+\d+.*)$",
        r"(?i)^(.+HTTP Error\s+\d+.*)$",
    ):
        for line in reversed(lines):
            match = re.match(pattern, line)
            if match:
                return match.group(1).strip()
    return lines[-1] if lines else "The processing command exited without an error message."


def hidden_subprocess_creation_flags() -> int:
    """Return Windows flags that keep normal backend runs out of a console window."""

    if os.name != "nt":
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


@dataclass(slots=True)
class RunnerResult:
    status: str
    exit_code: int | None
    stdout_lines: list[str] = field(default_factory=list)
    stderr_lines: list[str] = field(default_factory=list)
    error: str = ""
    # 243: the run's own number in the library, set by the Workbench when the run ends.
    run_id: str = ""


class FakeRunner:
    """Deterministic test backend that never invokes PowerShell."""

    def __init__(
        self,
        *,
        exit_code: int = 0,
        stdout: Iterable[str] | None = None,
        stderr: Iterable[str] | None = None,
        delay_seconds: float = 0.0,
        start_error: str = "",
    ) -> None:
        self.exit_code = exit_code
        self.stdout = list(stdout or [])
        self.stderr = list(stderr or [])
        self.delay_seconds = delay_seconds
        self.start_error = start_error
        self._cancel_requested = threading.Event()

    def cancel(self) -> None:
        self._cancel_requested.set()

    def run(self, command: CommandSpec | list[str], on_log: LogCallback | None = None) -> RunnerResult:
        _ = command
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        if self.start_error:
            return RunnerResult(status="failed", exit_code=None, error=self.start_error)

        for stream, lines, captured in (
            ("stdout", self.stdout, stdout_lines),
            ("stderr", self.stderr, stderr_lines),
        ):
            for line in lines:
                if self._cancel_requested.is_set():
                    return RunnerResult(
                        status="cancelled",
                        exit_code=None,
                        stdout_lines=stdout_lines,
                        stderr_lines=stderr_lines,
                    )
                captured.append(line)
                if on_log:
                    on_log(stream, line)
                if self.delay_seconds:
                    time.sleep(self.delay_seconds)

        if self._cancel_requested.is_set():
            status = "cancelled"
            exit_code = None
        elif self.exit_code == 0:
            status = "succeeded"
            exit_code = 0
        else:
            status = "failed"
            exit_code = self.exit_code
        return RunnerResult(
            status=status,
            exit_code=exit_code,
            stdout_lines=stdout_lines,
            stderr_lines=stderr_lines,
            error=(
                _failure_summary(stdout_lines, stderr_lines)
                if status == "failed"
                else ""
            ),
        )


class SubprocessRunner:
    """Real backend for manual operator runs."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None
        self._cancel_requested = threading.Event()
        self._lock = threading.Lock()

    def cancel(self) -> None:
        self._cancel_requested.set()
        with self._lock:
            process = self._process
        if process and process.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    creationflags=hidden_subprocess_creation_flags(),
                )
            else:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    def run(
        self,
        command: CommandSpec | list[str],
        on_log: LogCallback | None = None,
        *,
        cwd: str | None = None,
    ) -> RunnerResult:
        argv = command.argv if isinstance(command, CommandSpec) else list(command)
        self._cancel_requested.clear()
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        try:
            process = subprocess.Popen(
                argv,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=hidden_subprocess_creation_flags(),
            )
        except OSError as exc:
            return RunnerResult(status="failed", exit_code=None, error=str(exc))

        with self._lock:
            self._process = process

        def reader(stream_name: str, stream: object, captured: list[str]) -> None:
            if stream is None:
                return
            for raw_line in stream:  # type: ignore[operator]
                line = str(raw_line).rstrip("\r\n")
                captured.append(line)
                if on_log:
                    on_log(stream_name, line)

        stdout_thread = threading.Thread(target=reader, args=("stdout", process.stdout, stdout_lines), daemon=True)
        stderr_thread = threading.Thread(target=reader, args=("stderr", process.stderr, stderr_lines), daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        exit_code = process.wait()
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)

        with self._lock:
            self._process = None

        if self._cancel_requested.is_set():
            return RunnerResult(
                status="cancelled",
                exit_code=exit_code,
                stdout_lines=stdout_lines,
                stderr_lines=stderr_lines,
            )
        return RunnerResult(
            status="succeeded" if exit_code == 0 else "failed",
            exit_code=exit_code,
            stdout_lines=stdout_lines,
            stderr_lines=stderr_lines,
            error="" if exit_code == 0 else _failure_summary(stdout_lines, stderr_lines),
        )
