"""A stand-in for an antivirus scan, the search indexer or Explorer's thumbnails (224, Wave B2a): a separate
program that holds a file, a folder or the Inbox's lock open the way they do, until the test lets it go.

Run as a program it opens ``path`` with no delete sharing (a folder with its own handle; with ``--lock`` the one
locked byte the Inbox's lock uses; with ``--exclusive`` no sharing at all, as the PowerShell host holds the
Inbox's lock), prints ``HELD <process number>`` once the hold is real, and lets go when a
line arrives on its input (or after ``--seconds``), printing ``RELEASED``. With ``--forever`` it never lets go
until it is ended. With ``--outside`` it is started by a short-lived launcher that ends at once, so it is not a
child of the test: the app's file helpers must count it as another program, not as the app itself.

With ``--watch-folder`` (installer plan, Stage 2) it behaves like an on-access virus scanner: it watches ``path``,
a folder, and opens every new file that appears in it (and below it) for ``--hold-ms`` milliseconds with no delete
sharing, one after another, until it is let go; at the end it prints ``SCANNED <count>``. It says ``HELD`` only once
its watcher has really started looking (a test that makes files before that would race it under load), and prints
``OPENED <count>`` each time it opens a file, so a test can wait until the scanner has its hands on one.

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


class _Scanner:
    """Opens each new file under a folder for a moment, as an on-access scanner does."""

    def __init__(self, folder: Path, hold_ms: int) -> None:
        self.folder = folder
        self.hold = max(0, hold_ms) / 1000.0
        self.seen = {str(path) for path in folder.rglob("*")} if folder.is_dir() else set()
        self.count = 0
        self.stop = threading.Event()
        self.watching = threading.Event()
        self.thread = threading.Thread(target=self._watch, daemon=True)
        self.thread.start()
        # Ready only once the watcher's own thread runs: under heavy load it may otherwise start after the test's steps.
        self.watching.wait(30)

    def _watch(self) -> None:
        self.watching.set()
        while not self.stop.is_set():
            try:
                found = [path for path in self.folder.rglob("*") if str(path) not in self.seen]
            except OSError:
                found = []
            for path in found:
                self.seen.add(str(path))
                if not path.is_file():
                    continue
                try:
                    held = _hold_handle(path)
                except OSError:
                    continue  # already moved or removed: a scanner simply misses it
                self.count += 1
                print(f"OPENED {self.count}", flush=True)
                time.sleep(self.hold)
                held.close()
            time.sleep(0.01)

    def close(self) -> None:
        self.stop.set()
        self.thread.join(5)


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
    parser.add_argument("--watch-folder", action="store_true")
    parser.add_argument("--hold-ms", type=int, default=300)
    args = parser.parse_args(argv)
    if args.outside:
        # The launcher: start the holder with this program's own input and output, and end at once.
        forwarded = [value for value in (argv if argv is not None else sys.argv[1:]) if value != "--outside"]
        subprocess.Popen([sys.executable, str(HERE), *forwarded], stdin=sys.stdin, stdout=sys.stdout,
                         stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        return 0
    path = Path(args.path)
    if args.watch_folder:
        scanner = _Scanner(path, args.hold_ms)
        print(f"HELD {os.getpid()}", flush=True)
        if args.seconds > 0:
            time.sleep(args.seconds)
        else:
            sys.stdin.readline()
        scanner.close()
        print(f"SCANNED {scanner.count}", flush=True)
        print("RELEASED", flush=True)
        return 0
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


def _wait_ended(pid: int, seconds: float) -> None:
    """Return once process ``pid`` has ended (or after ``seconds``)."""

    if os.name != "nt":
        return
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not handle:
        return  # already gone
    try:
        kernel32.WaitForSingleObject(handle, int(seconds * 1000))
    finally:
        kernel32.CloseHandle(handle)


class OutsideHolder:
    """Start the holder on ``path`` and wait until the hold is real. ``outside=False`` starts it as a child of
    the test, which the app counts as its own."""

    def __init__(self, path: Path | str, *, outside: bool = True, folder: bool = False, lock: bool = False,
                 exclusive: bool = False, share_delete: bool = False, forever: bool = False,
                 seconds: float = 0.0, watch_folder: bool = False, hold_ms: int = 300) -> None:
        command = [sys.executable, str(HERE), str(path)]
        command += ["--outside"] if outside else []
        command += ["--folder"] if folder else []
        command += ["--lock"] if lock else []
        command += ["--exclusive"] if exclusive else []
        command += ["--share-delete"] if share_delete else []
        command += ["--forever"] if forever else []
        command += ["--seconds", str(seconds)] if seconds else []
        command += ["--watch-folder", "--hold-ms", str(hold_ms)] if watch_folder else []
        self.scanned = -1
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
        while line.startswith("OPENED "):
            line = self._line(15)
        if line.startswith("SCANNED "):
            # A watcher reports how many files it opened before it lets go.
            self.scanned = int(line.split()[1])
            line = self._line(15)
        if line != "RELEASED":
            raise RuntimeError(f"The holder did not let go: {line!r}")
        self.released = True

    def wait_opened(self, seconds: float = 30) -> None:
        """For a watcher: return once it has opened a new file (it is holding it now, or has just let it go)."""

        line = self._line(seconds)
        if not line.startswith("OPENED "):
            raise RuntimeError(f"The scanner opened no new file in time: {line!r}")

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
            # Ending a process is not instant, and the holder is not this object's child (the launcher is): wait until
            # it has really ended and let go, so a test's clean-up never meets the file still held.
            _wait_ended(self.pid, 15)
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
