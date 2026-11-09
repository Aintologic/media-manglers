"""A stand-in for an antivirus scan, the search indexer or Explorer's thumbnails (224, Wave B2a): a separate
program that holds a file, a folder or the Inbox's lock open the way they do, until the test lets it go.

Run as a program it opens ``path`` with no delete sharing (a folder with its own handle; with ``--lock`` the one
locked byte the Inbox's lock uses; with ``--exclusive`` no sharing at all, as the PowerShell host holds the
Inbox's lock), prints ``HELD <process number>`` once the hold is real, and lets go when a
line arrives on its input (or after ``--seconds``), printing ``RELEASED``. With ``--forever`` it never lets go
until it is ended. With ``--outside`` it is started by a short-lived launcher that ends at once, so it is not a
child of the test: the app's file helpers must count it as another program, not as the app itself.

``OutsideHolder`` starts and drives it from a test.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from typing import Any

HERE = Path(__file__).resolve()


def _hold_handle(path: Path, *, folder: bool = False, share: int = 0x1 | 0x2) -> Any:
    """A Windows handle on ``path``: a folder's own handle, or a file opened with ``share`` (0 shares nothing,
    as the PowerShell host's Process loop holds the Inbox's lock)."""

    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                     wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    list_directory, read_write, open_existing, backup_semantics = 0x1, 0xC0000000, 3, 0x02000000
    handle = kernel32.CreateFileW(str(path), list_directory if folder else read_write, share, None, open_existing,
                                  backup_semantics if folder else 0x80, None)
    if not handle or handle == wintypes.HANDLE(-1).value:
        raise OSError(ctypes.get_last_error(), "could not open it", str(path))

    class Held:
        def close(self) -> None:
            kernel32.CloseHandle(wintypes.HANDLE(handle))

    return Held()


def _hold_lock(path: Path) -> Any:
    import msvcrt  # noqa: PLC0415

    handle = open(path, "r+b", buffering=0)  # noqa: SIM115 - held until released
    handle.seek(0)
    deadline = time.monotonic() + 10
    while True:
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            break
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.02)

    class Lock:
        def close(self) -> None:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            handle.close()

    return Lock()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--folder", action="store_true")
    parser.add_argument("--lock", action="store_true")
    parser.add_argument("--exclusive", action="store_true")
    parser.add_argument("--share-delete", action="store_true")
    parser.add_argument("--forever", action="store_true")
    parser.add_argument("--seconds", type=float, default=0.0)
    parser.add_argument("--outside", action="store_true")
    args = parser.parse_args(argv)
    if args.outside:
        # The launcher: start the holder with this program's own input and output, and end at once.
        forwarded = [value for value in (argv if argv is not None else sys.argv[1:]) if value != "--outside"]
        subprocess.Popen([sys.executable, str(HERE), *forwarded], stdin=sys.stdin, stdout=sys.stdout,
                         stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        return 0
    path = Path(args.path)
    if args.lock:
        held = _hold_lock(path)
    elif args.folder:
        held = _hold_handle(path, folder=True)
    elif args.exclusive:
        held = _hold_handle(path, share=0)
    elif args.share_delete:
        # As a virus scan often opens a file: deleting it is allowed but only completes when the scan lets go,
        # and until then Windows refuses to remove its folder ("the directory is not empty").
        held = _hold_handle(path, share=0x1 | 0x2 | 0x4)
    else:
        held = open(path, "rb")  # noqa: SIM115 - Python opens files with no delete sharing on Windows
    print(f"HELD {os.getpid()}", flush=True)
    if args.forever:
        while True:
            time.sleep(1)
    if args.seconds > 0:
        time.sleep(args.seconds)
    else:
        sys.stdin.readline()
    held.close()
    print("RELEASED", flush=True)
    return 0


class OutsideHolder:
    """Start the holder on ``path`` and wait until the hold is real. ``outside=False`` starts it as a child of
    the test, which the app counts as its own."""

    def __init__(self, path: Path | str, *, outside: bool = True, folder: bool = False, lock: bool = False,
                 exclusive: bool = False, share_delete: bool = False, forever: bool = False,
                 seconds: float = 0.0) -> None:
        command = [sys.executable, str(HERE), str(path)]
        command += ["--outside"] if outside else []
        command += ["--folder"] if folder else []
        command += ["--lock"] if lock else []
        command += ["--exclusive"] if exclusive else []
        command += ["--share-delete"] if share_delete else []
        command += ["--forever"] if forever else []
        command += ["--seconds", str(seconds)] if seconds else []
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                                        stderr=subprocess.DEVNULL)
        line = self._line(15)
        if not line.startswith("HELD "):
            self.process.kill()
            raise RuntimeError(f"The holder did not start: {line!r}")
        self.pid = int(line.split()[1])
        self.released = False

    def _line(self, seconds: float) -> str:
        found: list[str] = []
        reader = threading.Thread(target=lambda: found.append(self.process.stdout.readline()), daemon=True)
        reader.start()
        reader.join(seconds)
        return found[0].strip() if found else ""

    def release(self) -> None:
        """Let go, and return only once the holder says it has."""

        if self.released:
            return
        self.process.stdin.write("release\n")
        self.process.stdin.flush()
        line = self._line(15)
        if line != "RELEASED":
            raise RuntimeError(f"The holder did not let go: {line!r}")
        self.released = True

    def wait_released(self, seconds: float = 15) -> None:
        """For a timed hold: return once the holder says it let go."""

        if self._line(seconds) != "RELEASED":
            raise RuntimeError("The holder did not let go in time.")
        self.released = True

    def close(self) -> None:
        if not self.released:
            try:
                os.kill(self.pid, signal.SIGTERM)  # TerminateProcess on Windows
            except OSError:
                pass
            self.released = True
        for stream in (self.process.stdin, self.process.stdout):
            try:
                stream.close()
            except OSError:
                pass
        try:
            self.process.wait(5)
        except subprocess.TimeoutExpired:
            self.process.kill()

    def __enter__(self) -> "OutsideHolder":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


if __name__ == "__main__":
    raise SystemExit(main())
