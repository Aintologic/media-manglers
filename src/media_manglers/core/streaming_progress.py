"""Follow a long tool run by what it prints, and stop it only when it stops moving (145, 224, 272).

One copy for every job that reads a whole recording through FFmpeg or FFprobe: the audio decode (145) and
the Inbox's frame check (224, Wave B2a) use it, and 272 reuses it for the Raw bin scan. The caller gives
a line parser that turns one printed line into a position: how far the job has got, in its own measure
(seconds into a recording, bytes read). Only a later position is movement.

- A run is stopped only when nothing moves for the stall limit, never for taking long. A large recording on
  a slow drive can take far longer than its own length to read, and that is fine while it moves.
- Time the whole tool spent suspended (Pause in the Workbench suspends the backend and everything it
  started) is not a stall.
- ``on_progress`` hears every new position, on the thread that reads the tool's output. Reporting progress
  never stops the run, so what it raises is ignored.
- ``on_report`` hears the position on the caller's own thread, at most every ``report_seconds``. Whatever it
  raises stops the tool and everything it started, and is raised again: that is how a Skip from Queue /
  Progress reaches a long read.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any, Callable

# 145: a read is stopped only when it stops moving for this long.
STALL_SECONDS = 180.0
# The loop looks every 0.2 s. A far longer gap between two looks means the whole tool was suspended (Pause in
# the Workbench), and time spent suspended is not a stall.
SUSPENDED_GAP_SECONDS = 5.0
LOOK_SECONDS = 0.2
# How often ``on_report`` hears the position, by default: the progress file is written at most this often.
REPORT_SECONDS = 2.0
# After the tool exits, its last lines are read for at most this long.
DRAIN_SECONDS = 30.0
# What a run without its own error file keeps of what the tool wrote to its error output: the last lines.
ERROR_LINES_KEPT = 200


class Stalled(RuntimeError):
    """The tool made no progress for the stall limit, so it and everything it started were stopped."""


@dataclass(frozen=True)
class Finished:
    """How a followed run ended: the tool's exit code, how far it got, what it wrote to its error output (when
    no error file was given), and whether every line it printed was read."""

    returncode: int
    position: float
    errors: str = ""
    complete: bool = True


def stop_tree(process: subprocess.Popen[Any]) -> None:
    """Stop the tool and anything it started (145): a launcher or package-manager shim in front of the real
    FFmpeg would otherwise leave it reading the recording. The backend's Stop-MMProcessTree does the same for
    the processes it starts."""

    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True, timeout=30,
                           check=False, creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)))
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        process.kill()
    except OSError:
        pass
    process.wait()


def run(
    command: list[str],
    *,
    read_line: Callable[[str], float | None],
    stall_message: Callable[[float], str],
    stall_seconds: float = STALL_SECONDS,
    stderr_path: Path | None = None,
    on_progress: Callable[[float], None] | None = None,
    on_report: Callable[[float], None] | None = None,
    report_seconds: float = REPORT_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> Finished:
    """Run ``command`` for as long as it keeps moving; see the module's note.

    ``read_line`` is told every line the tool prints (without its line ending) and returns the position that
    line shows, or None. It may also keep what it needs from the lines; it runs on the reading thread, and has
    seen every line once this returns with ``complete``. ``stall_message`` gives the plain reason for a
    ``Stalled`` from the position reached. The tool's error output goes to ``stderr_path`` when given, else
    its last lines come back in ``Finished.errors``.
    """

    state = {"at": 0.0, "moved": clock()}

    def follow(stream: Any) -> None:
        for line in stream:
            try:
                position = read_line(line.rstrip("\r\n"))
            except Exception:  # noqa: BLE001 - a line the parser cannot read is not movement
                position = None
            if position is None or position <= state["at"]:
                continue
            state["at"] = float(position)
            state["moved"] = clock()
            if on_progress is not None:
                try:
                    on_progress(state["at"])
                except Exception:  # noqa: BLE001 - reporting progress must never stop the run
                    pass

    kept: deque[str] = deque(maxlen=ERROR_LINES_KEPT)

    def keep_errors(stream: Any) -> None:
        for line in stream:
            kept.append(line.rstrip("\r\n"))

    stderr_file = stderr_path.open("w", encoding="utf-8", errors="replace") if stderr_path is not None else None
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=stderr_file if stderr_file is not None else subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
        )
        readers = [threading.Thread(target=follow, args=(process.stdout,), daemon=True)]
        if stderr_file is None:
            readers.append(threading.Thread(target=keep_errors, args=(process.stderr,), daemon=True))
        for reader in readers:
            reader.start()
        last_look = clock()
        last_report = last_look
        try:
            while process.poll() is None:
                now = clock()
                if now - last_look > SUSPENDED_GAP_SECONDS:
                    state["moved"] = min(state["moved"] + (now - last_look), now)
                last_look = now
                if now - state["moved"] > stall_seconds:
                    raise Stalled(stall_message(state["at"]))
                if on_report is not None and now - last_report >= report_seconds:
                    last_report = now
                    on_report(state["at"])
                time.sleep(LOOK_SECONDS)
        except BaseException:
            stop_tree(process)
            raise
        deadline = time.monotonic() + DRAIN_SECONDS
        for reader in readers:
            reader.join(timeout=max(0.0, deadline - time.monotonic()))
        complete = not any(reader.is_alive() for reader in readers)
    finally:
        if stderr_file is not None:
            stderr_file.close()
    return Finished(returncode=int(process.returncode), position=state["at"], errors="\n".join(kept).strip(),
                    complete=complete)
