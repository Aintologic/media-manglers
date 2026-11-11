"""The two locks every Media Manglers program takes (installer plan, Stage 2).

- ``MediaManglers.Running``: every entry point holds it while it runs (the Workbench, every helper run through
  ``media_manglers.cli.main``, and ``Video Mangler.ps1``), so the installer can see that Media Manglers is
  running and ask for it to be closed before it updates or removes anything. It never stops a program from
  starting; any number may hold it.
- ``MediaManglers.Workbench``: one Workbench window at a time, because the portable and the installed editions
  share one library and one settings folder. A second Workbench is told that one is already open and closes.
  A Workbench pointed at test data folders (the ``MEDIA_MANGLERS_WORKBENCH_*`` overrides, as the tests and the
  build's start-up check use) takes a lock of its own for those folders, so it never collides with the operator's.

Both are Windows named mutexes, held through an open handle for the life of the process; Windows lets go of
them when the process ends, however it ends, so a lock is never left behind. Elsewhere they do nothing.
"""

from __future__ import annotations

import hashlib
import os
import threading

RUNNING_LOCK = "MediaManglers.Running"
WORKBENCH_LOCK = "MediaManglers.Workbench"
DATA_OVERRIDES = ("MEDIA_MANGLERS_WORKBENCH_APPDATA", "MEDIA_MANGLERS_WORKBENCH_LOCALAPPDATA",
                  "MEDIA_MANGLERS_LIBRARY_ROOT")
_ERROR_ALREADY_EXISTS = 183
_SYNCHRONIZE = 0x00100000

_guard = threading.Lock()
_running_handle: int | None = None
_workbench_handle: int | None = None


def _kernel32():
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenMutexW.restype = wintypes.HANDLE
    kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    return ctypes, kernel32


def _create(name: str) -> tuple[int | None, bool]:
    """A handle on the named mutex, and whether it already existed (another process holds it)."""

    if os.name != "nt":
        return None, False
    ctypes, kernel32 = _kernel32()
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, False, name)
    existed = ctypes.get_last_error() == _ERROR_ALREADY_EXISTS
    return (int(handle) if handle else None), existed


def _close(handle: int | None) -> None:
    if handle and os.name == "nt":
        _ctypes, kernel32 = _kernel32()
        kernel32.CloseHandle(handle)


def is_held(name: str) -> bool:
    """Whether any process holds the lock ``name`` now."""

    if os.name != "nt":
        return False
    _ctypes, kernel32 = _kernel32()
    handle = kernel32.OpenMutexW(_SYNCHRONIZE, False, name)
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True


def hold_running_lock() -> bool:
    """Hold ``MediaManglers.Running`` for the rest of this process's life (once; later calls change nothing)."""

    global _running_handle
    with _guard:
        if _running_handle is None:
            _running_handle, _existed = _create(RUNNING_LOCK)
        return _running_handle is not None


def holding_running_lock() -> bool:
    """Whether this process holds ``MediaManglers.Running``."""

    return _running_handle is not None


def workbench_lock_name(environ: dict[str, str] | None = None) -> str:
    """``MediaManglers.Workbench``, or one of its own for a Workbench pointed at test data folders."""

    environ = dict(os.environ) if environ is None else environ
    overrides = [f"{key}={os.path.normcase(str(environ.get(key) or '').strip())}" for key in DATA_OVERRIDES
                 if str(environ.get(key) or "").strip()]
    if not overrides:
        return WORKBENCH_LOCK
    digest = hashlib.sha256("\n".join(overrides).encode("utf-8")).hexdigest()[:16]
    return f"{WORKBENCH_LOCK}.{digest}"


def take_workbench_lock(name: str | None = None) -> bool:
    """Take the one-Workbench lock for this process. False when another Workbench for the same data holds it."""

    global _workbench_handle
    with _guard:
        if _workbench_handle is not None:
            return True
        handle, existed = _create(name or workbench_lock_name())
        if existed:
            _close(handle)
            return False
        _workbench_handle = handle
        return True


def release_workbench_lock() -> None:
    """Let go of the one-Workbench lock (for tests; a closing Workbench lets go when its process ends)."""

    global _workbench_handle
    with _guard:
        _close(_workbench_handle)
        _workbench_handle = None
