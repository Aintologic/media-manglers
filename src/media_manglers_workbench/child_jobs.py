"""The Workbench's runs end with the Workbench (M15 of the Wave I-A review).

A review, a scan, Prepare and the downloads run in programs the Workbench starts (the PowerShell backend, the helper,
and the tools they start). Closing the Workbench already stops them. If the Workbench crashes, or is ended from Task
Manager, they used to keep going, hidden: a paused run then waited for a Resume that could never come, kept its tool
frozen, and held the ``MediaManglers.Running`` lock for good, so the installer would keep saying Media Manglers is
running with no window to close.

``keep_with_workbench`` puts such a program into one Windows job object that this Workbench alone holds, set to end
every program in it when its last handle closes: when the Workbench ends, however it ends, Windows ends them all,
with the programs they started. Programs the Workbench opens for the operator (the video player, Explorer) are not
put in it and are never ended with it.
"""

from __future__ import annotations

import os
import subprocess
import threading
from typing import Any

_JOB_LIMIT_KILL_ON_CLOSE = 0x2000
_JOB_EXTENDED_LIMIT_INFORMATION = 9
_lock = threading.Lock()
_job: Any = None


def _workbench_job() -> Any:
    """This Workbench's one job object, made on first use; None where Windows will not make one."""

    global _job
    with _lock:
        if _job is not None or os.name != "nt":
            return _job
        import ctypes  # noqa: PLC0415
        from ctypes import wintypes  # noqa: PLC0415

        class BasicLimits(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount",
                "WriteTransferCount", "OtherTransferCount")]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        # Not inheritable: only this Workbench holds the job, so it closes when the Workbench ends.
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = _JOB_LIMIT_KILL_ON_CLOSE
        if not kernel32.SetInformationJobObject(job, _JOB_EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits),
                                                ctypes.sizeof(limits)):
            kernel32.CloseHandle(wintypes.HANDLE(job))
            return None
        _job = job
        return _job


def keep_with_workbench(process: subprocess.Popen[Any]) -> bool:
    """Put ``process`` (just started by the Workbench) into the Workbench's job, so it and every program it starts
    end when the Workbench ends. False where that is not possible; the run then still works as before."""

    job = _workbench_job()
    handle = getattr(process, "_handle", None)
    if job is None or handle is None:
        return False
    try:
        import ctypes  # noqa: PLC0415
        from ctypes import wintypes  # noqa: PLC0415

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        return bool(kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(int(handle))))
    except Exception:  # noqa: BLE001 - the run itself goes ahead either way
        return False
