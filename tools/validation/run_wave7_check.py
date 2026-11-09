"""Part 1 of the Wave 7 acceptance test (226): headless checks of a packaged build.

Every folder, recording and settings file is an argument; nothing here names a real one. Each step
writes a JSON result (``--json``, else ``<work>/results/<step>.json``) and, with ``--report``, adds
plain-English lines to that markdown file.

    environment --work DIR --settings FILE --recordings-folder FOLDER
        Makes the test folders under DIR and a COPY of the settings FILE whose output, editor, Inbox,
        ledger, work, cache, temporary and log folders point into DIR (FILE is only read; its SHA-256 is
        taken before and after). Prints the test environment; every later step that is given the same
        --work runs its programs with it.
    listing --folder DIR --out CSV          every file under DIR, hidden ones too: path, size, modified (UTC);
                                            exit 1 when anything could not be read
    compare --before CSV --after CSV        exit 1 when a file that existed before changed or went;
                                            new files are listed on their own, not counted
    smoke --dist DIST --clip CLIP --work DIR
        Features 1-3 through the packaged backend, each command built the way its page builds it, all
        four on one copy of CLIP in the work folder.
    editor (--dist DIST | --backend-src SRC) --recording FILE --work DIR [--copy-name NAME]
           [--scripted-minutes M] [--qualities youtube,highest,smaller] [--validation-size WxH] [--fps-copies]
           [--voice-track N] [--game-track N] [--compare-quick-models]
        The AI Video Editor's Prepare, a scripted test edit (written here, not by an AI), its renders,
        exports (one as the page makes it, then each of --qualities, each kept in <work>/exports) and a
        validation render, with the reads of the recording measured. A work folder that already has a
        project for the recording is refused. --voice-track and --game-track (Track 1 is 1; 0, the
        default, is Auto) are sent as the page sends a track picked by hand, for the recording and the
        frame-rate copies. After each Prepare the step stops (exit 2) when the game track it used is
        silent for the whole recording, rather than make renders that fail on dead air.
        --compare-quick-models prepares the recording a second time, into a fresh project, with the quick
        passes on the main Whisper model, and reports how long each model listened for other voices on
        the game track and what each kept and left out.
    compare-analysis --baseline-src DIR --recording FILE --work DIR [--dist DIST | --backend-src SRC]
           [--voice-track N] [--game-track N] [--baseline-label TEXT]
        Prepares the recording, transcript skipped, with this build (DIST, SRC, else this worktree's src)
        and with the backend in DIR (the src folder of ``git archive 9e065e4 src``) through its own
        command line, on the same tracks, each into a fresh project, and lists every difference in talk
        stretches, game-sound spikes and track rows. Differences are listed, not failed.
    dead-time-frames --project PROJECT --recording FILE --out DIR
        A frame from the middle of each dead-time stretch and an overview sheet (a frame every 5 minutes),
        of the centre game panel only; nothing is written unless FILE is the project's own recording and
        the layout and the masks check out.
    rawbin-spike --recording FILE --work DIR
        Times the raw bin's own read path, sound only and then sound plus the game picture.

A --backend-src (the tool's own tests) is taken from the folder the tool is started in, and refused
unless it is inside DIST or this tool's own worktree: the backend starts in another folder, where a
relative path would run some other copy of the code.

Exit codes: 0 when everything passed; 1 for a failed check, a listing difference, a listing that could
not read everything, or a refusal; 2 when a step stopped (and then its result file says why). No work
folder, listing or frames folder may be inside, or on the drive of, a recordings folder.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import copy as shallow_copy
import csv
import ctypes
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
import traceback
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from media_manglers.core import frame_render, user_folders, voice_track  # noqa: E402

NO_WINDOW = 0x08000000
ENVIRONMENT_NAME = "environment.json"
MB = 1024 * 1024
SCRIPTED = "scripted test edit, not an AI edit"
EDITOR_LABEL = "wave7-check"
QUALITY_NAMES = ("youtube", "highest", "smaller")
# The frame rates the editor step's copies are made at (--fps-copies).
FPS_RATES = ("30", "60000/1001")
# A read of at least this share of the file counts as a full read of the recording.
FULL_READ_SHARE = 0.9
# Settings the copy empties: a resume folder would be a real run's, and features 1-3 would resume from it.
CLEARED_SETTINGS = ("evidence_resume_root",)
DECIDED = {"setting": "from the Narration track setting", "track_name": "from the track name",
           "override": "chosen by hand", "auto": "found by listening"}
SIGNALS = {"game_audio": "the game sound quiet", "game_picture": "the game picture still"}


def _found_by(signals: list[str] | None) -> str:
    return " and ".join(SIGNALS.get(signal, signal) for signal in (signals or ["game_audio"]))


class StepFailed(RuntimeError):
    pass


class Refused(StepFailed):
    """A folder the step may not write to (beside the recording, inside or on the drive of a recordings
    folder, or inside the folder listed)."""


# Small helpers ---------------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(MB), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _clock(seconds: float) -> str:
    whole = int(max(0.0, float(seconds)))
    hours, rest = divmod(whole, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else f"{rest // 60}:{rest % 60:02d}"


def _inside(path: Path, folder: Path) -> bool:
    try:
        Path(os.path.abspath(path)).relative_to(Path(os.path.abspath(folder)))
        return True
    except ValueError:
        return False


def _guard(path: Path, what: str, *folders: Any) -> None:
    """Refuse ``path`` when it is inside, or anywhere on the drive of, ``folders`` or the test
    environment's recordings folders, by the shared output-folder rule
    (``user_folders.recordings_drive_problem``; on the system drive only the folders themselves)."""

    watched = [str(item) for item in folders if str(item or "").strip()]
    if user_folders.RECORDINGS_FOLDERS_ENV in os.environ:
        watched += user_folders.recordings_folders()
    problem = user_folders.recordings_drive_problem(path, what, watched) if watched else ""
    if problem:
        raise Refused(problem)


def _report(path: str | None, lines: list[str]) -> None:
    text = "\n".join(lines).rstrip() + "\n\n"
    print(text, end="", flush=True)
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with Path(path).open("a", encoding="utf-8") as handle:
            handle.write(text)


def _finish(args: argparse.Namespace, name: str, result: dict[str, Any], lines: list[str], code: int) -> int:
    target = Path(args.json) if args.json else (Path(args.work) / "results" / f"{name}.json"
                                                 if getattr(args, "work", None) else None)
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
        lines = [*lines, f"- Full result: `{target}`"]
    _report(args.report, lines)
    return code


# The test environment --------------------------------------------------------------------------


def _folders(work: Path) -> dict[str, Path]:
    return {"scratch": work / "scratch", "library": work / "test-library", "cache": work / "test-cache",
            "output": work / "test-output", "appdata": work / "gui-appdata"}


def _settings_redirects(work: Path) -> dict[str, Path]:
    """The settings the copy points into the work folder."""

    out, inbox = work / "test-output", work / "inbox"
    return {"output_folder": out / "Media Mangler", "race_video_output_folder": out / "editor",
            "review_evidence_root": inbox / "evidence",
            "review_ledger_path": inbox / "evidence" / "review-inbox" / "review-ledger.sqlite",
            # 224 (Wave B2b): the Inbox folder; a copy never names the operator's real one.
            "review_inbox_folder": inbox / "evidence" / "review-inbox",
            "review_local_work_root": inbox / "work", "review_source_folders": inbox / "source",
            "cache_folder": work / "test-cache", "temp_folder": work / "app-temp",
            # Saved settings name the real log folder; the Workbench launched on the copy writes its logs here.
            "log_folder": work / "logs"}


def environment_block(work: Path, recordings_folder: str) -> dict[str, str]:
    folders = {key: str(value) for key, value in _folders(work).items()}
    return {"TEMP": folders["scratch"], "TMP": folders["scratch"], "MEDIA_MANGLERS_SCRATCH_ROOT": folders["scratch"],
            "MEDIA_MANGLERS_LIBRARY_ROOT": folders["library"], "MEDIA_MANGLERS_CACHE_ROOT": folders["cache"],
            "MEDIA_MANGLERS_VIDEOS_FOLDER": folders["output"], "MEDIA_MANGLERS_MUSIC_FOLDER": folders["output"],
            "MEDIA_MANGLERS_WORKBENCH_APPDATA": folders["appdata"],
            "MEDIA_MANGLERS_WORKBENCH_LOCALAPPDATA": folders["appdata"],
            "MEDIA_MANGLERS_ALLOW_TEMP_OUTPUT": "1", "MEDIA_MANGLERS_RECORDINGS_FOLDERS": str(recordings_folder)}


def settings_copy_path(work: Path) -> Path:
    """Where the Workbench and core look for their settings under the test environment."""

    before = os.environ.get("MEDIA_MANGLERS_WORKBENCH_APPDATA")
    os.environ["MEDIA_MANGLERS_WORKBENCH_APPDATA"] = str(_folders(work)["appdata"])
    try:
        core = user_folders.workbench_settings_file()
        from media_manglers_workbench.settings import default_settings_path  # noqa: PLC0415

        workbench = default_settings_path()
    finally:
        if before is None:
            os.environ.pop("MEDIA_MANGLERS_WORKBENCH_APPDATA", None)
        else:
            os.environ["MEDIA_MANGLERS_WORKBENCH_APPDATA"] = before
    if os.path.normcase(str(core)) != os.path.normcase(str(workbench)):
        raise StepFailed(f"The Workbench ({workbench}) and core ({core}) would read different settings files.")
    return core


def apply_environment(work: Path) -> dict[str, str]:
    """The test environment the environment step wrote, applied to this process (so every program it
    starts has it too)."""

    block = _read_json(Path(work) / ENVIRONMENT_NAME).get("environment")
    if not isinstance(block, dict) or not block:
        raise StepFailed(f"No test environment in {work}: run the environment step first.")
    os.environ.update({str(key): str(value) for key, value in block.items()})
    return dict(block)


def _saved(work: Path) -> dict[str, Any]:
    data = _read_json(settings_copy_path(work))
    block = data.get("settings") if "settings" in data else data
    return dict(block) if isinstance(block, dict) else {}


def environment(args: argparse.Namespace) -> int:
    work, source = Path(args.work).resolve(), Path(args.settings).resolve()
    _guard(work, "work folder", args.recordings_folder)
    target = settings_copy_path(work)
    if os.path.normcase(str(target.resolve())) == os.path.normcase(str(source)):
        raise StepFailed("The settings copy would replace the settings file it is made from.")
    before = _sha256(source)
    data = json.loads(source.read_text(encoding="utf-8-sig"))
    block = data.get("settings") if isinstance(data, dict) and isinstance(data.get("settings"), dict) else data
    if not isinstance(block, dict):
        raise StepFailed("The settings file holds no settings.")
    redirects = _settings_redirects(work)
    for key, path in redirects.items():
        block[key] = str(path)
        (path.parent if key == "review_ledger_path" else path).mkdir(parents=True, exist_ok=True)
    for key in CLEARED_SETTINGS:
        block[key] = ""
    for folder in _folders(work).values():
        folder.mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    after = _sha256(source)
    outside = sorted(key for key, value in block.items() if isinstance(value, str)
                     and re.match(r"^(?:[A-Za-z]:[\\/]|\\\\)", value.strip()) and not _inside(Path(value.strip()), work))
    env = environment_block(work, args.recordings_folder)
    result = {"environment": env, "settings_copy": str(target), "redirected": sorted(redirects),
              "cleared": list(CLEARED_SETTINGS), "source_sha256_before": before, "source_sha256_after": after,
              "source_unchanged": before == after, "keys_still_outside": outside}
    (work / ENVIRONMENT_NAME).write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(env, indent=1))
    lines = ["## Test environment", "",
             f"- Work folder: `{work}`. Settings copy: `{target}`.",
             f"- Pointed into the work folder: {', '.join(sorted(redirects))}. Emptied: {', '.join(CLEARED_SETTINGS)}.",
             f"- The source settings file was {'not changed' if before == after else 'CHANGED'} "
             f"(SHA-256 {before[:12]} before, {after[:12]} after).",
             f"- Other settings that name a folder outside the work folder (tool paths and the like): "
             f"{', '.join(outside) or 'none'}.",
             f"- Recordings-drive guard armed with: `{args.recordings_folder}`."]
    return _finish(args, "environment", result, lines, 0 if before == after else 1)


# Listing and compare ---------------------------------------------------------------------------


def _modified_utc(ns: int) -> str:
    return f"{datetime.fromtimestamp(ns // 10 ** 9, timezone.utc):%Y-%m-%dT%H:%M:%S}.{ns % 10 ** 9:09d}Z"


def listing(args: argparse.Namespace) -> int:
    folder, out = Path(args.folder), Path(args.out)
    if not folder.is_dir():
        # An offline drive or a mistyped path would otherwise list no files, and compare no differences.
        raise StepFailed(f"{folder} is not a folder that can be read.")
    if _inside(out, folder):
        raise Refused("The listing must be written outside the folder it lists.")
    _guard(out, "listing", folder)
    rows: list[tuple[str, int, str]] = []
    errors: list[OSError] = []
    for current, _folders_here, files in os.walk(folder, onerror=errors.append):   # hidden files too
        for name in files:
            try:
                stat = os.lstat(os.path.join(current, name))
            except OSError as exc:
                errors.append(exc)
                continue
            rows.append((os.path.join(current, name), int(stat.st_size), _modified_utc(stat.st_mtime_ns)))
    unreadable = len(errors)
    rows.sort()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["path", "size", "modified_utc"])
        writer.writerows(rows)
    total = sum(row[1] for row in rows)
    result = {"folder": str(folder), "csv": str(out), "files": len(rows), "bytes": total, "unreadable": unreadable,
              "unreadable_paths": [str(getattr(error, "filename", "") or error) for error in errors[:50]]}
    lines = [f"## Listing of `{folder}`", "",
             f"- {len(rows)} files, {total / 1024 ** 3:.2f} GB, written to `{out}`; {unreadable} could not be read"
             f"{': the listing is INCOMPLETE' if unreadable else ''}."]
    lines += [f"  - could not be read: `{path}`" for path in result["unreadable_paths"]]
    return _finish(args, "listing", result, lines, 1 if unreadable else 0)


def compare(args: argparse.Namespace) -> int:
    def read(path: str) -> dict[str, tuple[str, str]]:
        with Path(path).open("r", encoding="utf-8", newline="") as handle:
            return {row["path"]: (row["size"], row["modified_utc"]) for row in csv.DictReader(handle)}

    old, new = read(args.before), read(args.after)
    if not old:
        raise StepFailed(f"The before listing ({args.before}) has no files, so there is nothing to compare against.")
    removed = sorted(set(old) - set(new))
    changed = sorted(path for path in set(old) & set(new) if old[path] != new[path])
    added = sorted(set(new) - set(old))
    result = {"before": len(old), "after": len(new), "removed": removed, "changed": changed, "new_files": added,
              "differences": len(removed) + len(changed)}
    lines = ["## Before and after", "",
             f"- {len(old)} files before, {len(new)} after. Files that existed before: {len(changed)} changed, "
             f"{len(removed)} gone. {'No differences.' if not removed and not changed else 'DIFFERENCES FOUND.'}"]
    lines += [f"  - changed: `{path}`" for path in changed[:50]] + [f"  - gone: `{path}`" for path in removed[:50]]
    lines.append(f"- New files (reported, not counted as differences): {len(added)}.")
    lines += [f"  - new: `{path}`" for path in added[:50]]
    return _finish(args, "compare", result, lines, 1 if removed or changed else 0)


# Running programs ------------------------------------------------------------------------------


PROGRESS_MARKER = "MM_PROGRESS_V1 "


def status_record(line: str) -> dict[str, Any] | None:
    """The status line (MM_PROGRESS_V1) in an output line, wherever it starts, or None (226). The
    error output is read with the normal output, and Whisper's progress bar leaves a partial line
    there, so a status line can arrive glued after a bar ("...frames/s]MM_PROGRESS_V1 {...}")."""

    at = line.find(PROGRESS_MARKER)
    if at < 0:
        return None
    try:
        record, _end = json.JSONDecoder().raw_decode(line[at + len(PROGRESS_MARKER):].lstrip())
    except ValueError:
        return None
    return record if isinstance(record, dict) else None


def _run(argv: list[str], log: Path, *, cwd: Path) -> dict[str, Any]:
    """Run one program with this process's environment, every output line logged with its time and
    the status lines (MM_PROGRESS_V1) kept, a status line glued after a progress bar too."""

    log.parent.mkdir(parents=True, exist_ok=True)
    (log.parent / "argv.json").write_text(json.dumps(argv, indent=1), encoding="utf-8")
    started = time.monotonic()
    progress: list[dict[str, Any]] = []
    process = subprocess.Popen(argv, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="replace", creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    with log.open("w", encoding="utf-8") as out:
        for line in process.stdout:  # type: ignore[union-attr]
            at = time.monotonic() - started
            out.write(f"{at:9.2f} {line.rstrip()}\n")
            record = status_record(line)
            if record is not None:
                progress.append({"t": round(at, 2), "phase": record.get("phase"), "activity": record.get("activity"),
                                 "completed": record.get("completed"), "total": record.get("total")})
    code = process.wait()
    return {"exit_code": code, "seconds": round(time.monotonic() - started, 1), "progress": progress, "log": str(log)}


def progress_summary(progress: list[dict[str, Any]], seconds: float) -> dict[str, Any]:
    """The longest silence (from the start to the end, and between status lines) and the time per step."""

    times = [0.0, *[float(item["t"]) for item in progress], float(seconds)]
    gaps = [(later - earlier, earlier) for earlier, later in zip(times, times[1:])]
    longest, at = max(gaps) if gaps else (0.0, 0.0)
    between = [later - earlier for earlier, later in zip(times[1:-1], times[2:-1])]
    firsts: dict[str, float] = {}
    for item in progress:
        firsts.setdefault(str(item.get("phase") or ""), float(item["t"]))
    ordered = sorted(firsts.items(), key=lambda pair: pair[1])
    phases = [{"phase": name, "started_at": round(start, 1),
               "seconds": round((ordered[index + 1][1] if index + 1 < len(ordered) else seconds) - start, 1)}
              for index, (name, start) in enumerate(ordered)]
    return {"lines": len(progress), "longest_silence_seconds": round(longest, 1), "longest_silence_at": round(at, 1),
            "longest_gap_between_lines": round(max(between), 1) if between else None, "phases": phases}


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in ("ReadOperationCount", "WriteOperationCount",
                                                         "OtherOperationCount", "ReadTransferCount",
                                                         "WriteTransferCount", "OtherTransferCount")]


class _ProcessEntry(ctypes.Structure):
    _fields_ = [("dwSize", ctypes.c_ulong), ("cntUsage", ctypes.c_ulong), ("th32ProcessID", ctypes.c_ulong),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", ctypes.c_ulong),
                ("cntThreads", ctypes.c_ulong), ("th32ParentProcessID", ctypes.c_ulong),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", ctypes.c_ulong), ("szExeFile", ctypes.c_wchar * 260)]


class ReadWatch:
    """How much of the recording each FFmpeg run read. Every ``seconds`` the FFmpeg processes are listed;
    each new one is opened at once and its command line read, and one that names the recording is kept
    open, so its ReadTransferCount (the counter Win32_Process reports) is read once it has ended. A run
    that read at least FULL_READ_SHARE of the file is a full read, whatever its options; otherwise one
    with -ss before -i is a still seek. Runs that do not name the recording are remembered by process
    number and start time, so a later run given the same number is still looked at. A still seek that
    starts and ends between two looks is missed, so the still-seek count is a minimum."""

    def __init__(self, recording: Path, exe_name: str = "ffmpeg.exe", seconds: float = 0.1) -> None:
        self.recording, self.size = recording, recording.stat().st_size
        self.needle, self.exe, self.seconds = str(recording).casefold(), exe_name.casefold(), float(seconds)
        self.seen: dict[int, dict[str, Any]] = {}
        self.others: dict[int, int | None] = {}   # process number: its start time (None when it cannot be opened)
        self.polls = 0
        self._stop = threading.Event()
        kernel = self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = kernel.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.CreateToolhelp32Snapshot.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
        kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ProcessEntry)]
        kernel.GetProcessIoCounters.argtypes = [ctypes.c_void_p, ctypes.POINTER(_IoCounters)]
        kernel.GetProcessTimes.argtypes = [ctypes.c_void_p, *[ctypes.POINTER(ctypes.c_ulonglong)] * 4]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self._ntdll = ctypes.WinDLL("ntdll")
        self._ntdll.NtQueryInformationProcess.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p,
                                                          ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]

    def _command_line(self, handle: int) -> str:
        needed = ctypes.c_ulong(0)
        self._ntdll.NtQueryInformationProcess(handle, 60, None, 0, ctypes.byref(needed))   # ProcessCommandLineInformation
        if not needed.value:
            return ""
        buffer = ctypes.create_string_buffer(needed.value)
        if self._ntdll.NtQueryInformationProcess(handle, 60, buffer, needed.value, ctypes.byref(needed)) != 0:
            return ""
        length = ctypes.c_ushort.from_buffer(buffer, 0).value   # a UNICODE_STRING, its text inside the buffer
        return ctypes.wstring_at(ctypes.c_void_p.from_buffer(buffer, ctypes.sizeof(ctypes.c_void_p)).value, length // 2)

    def _started(self, handle: int) -> int | None:
        times = [ctypes.c_ulonglong(0) for _ in range(4)]   # creation, exit, kernel and user time (FILETIMEs)
        if not self._kernel.GetProcessTimes(handle, *(ctypes.byref(item) for item in times)):
            return None
        return int(times[0].value)

    def _consider(self, pid: int) -> None:
        handle = self._kernel.OpenProcess(0x1000, 0, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        started = self._started(handle) if handle else None
        if pid in self.others and self.others[pid] == started:
            if handle:
                self._kernel.CloseHandle(handle)
            return
        command = self._command_line(handle) if handle else ""
        if handle and self.needle in command.casefold():
            # Held open until the end, so the number cannot pass to another process meanwhile.
            self.seen[pid] = {"pid": pid, "cmd": command, "handle": handle, "found_at": time.monotonic()}
        else:
            self.others[pid] = started
            if handle:
                self._kernel.CloseHandle(handle)

    def _look(self) -> None:
        snapshot = self._kernel.CreateToolhelp32Snapshot(0x2, 0)
        if not snapshot or snapshot == ctypes.c_void_p(-1).value:
            return
        try:
            entry = _ProcessEntry()
            entry.dwSize = ctypes.sizeof(_ProcessEntry)
            found = self._kernel.Process32FirstW(snapshot, ctypes.byref(entry))
            while found:
                pid = int(entry.th32ProcessID)
                if entry.szExeFile.casefold() == self.exe and pid not in self.seen:
                    self._consider(pid)
                found = self._kernel.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            self._kernel.CloseHandle(snapshot)
        self.polls += 1

    def _watch(self) -> None:
        while not self._stop.is_set():
            self._look()
            self._stop.wait(self.seconds)

    def start(self) -> "ReadWatch":
        self._look()
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        self._thread.join(timeout=30)
        processes = []
        for item in self.seen.values():
            counters = _IoCounters()
            read = int(counters.ReadTransferCount) if self._kernel.GetProcessIoCounters(
                item["handle"], ctypes.byref(counters)) else 0
            self._kernel.CloseHandle(item["handle"])
            command = f" {item['cmd']} "
            seek, given = command.find(" -ss "), command.find(" -i ")
            kind = "still seek" if seek != -1 and (given == -1 or seek < given) else "read"
            processes.append({"pid": item["pid"], "kind": kind, "bytes_read": read,
                              "full": read >= FULL_READ_SHARE * self.size,
                              "share_of_file": round(read / self.size, 3) if self.size else None})
        full = [item for item in processes if item["full"]]
        reads = [item for item in processes if not item["full"] and item["kind"] == "read"]
        seeks = [item for item in processes if not item["full"] and item["kind"] == "still seek"]
        read_bytes = sum(item["bytes_read"] for item in [*full, *reads])
        return {"file_bytes": self.size, "poll_seconds": self.seconds, "polls": self.polls,
                "full_reads": len(full), "part_reads": len(reads), "still_seeks": len(seeks),
                "still_seeks_are_a_minimum": True,
                "read_bytes": read_bytes, "read_share": round(read_bytes / self.size, 3) if self.size else None,
                "seek_bytes": sum(item["bytes_read"] for item in seeks), "processes": processes}


# Features 1-3 ----------------------------------------------------------------------------------


def _fresh(folder: Path, work: Path) -> Path:
    if not _inside(folder, work):
        raise StepFailed(f"{folder} is not inside the work folder.")
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    return folder


def backend_source(dist: Path | None, backend_src: str = "") -> Path | None:
    """The backend's source folder: the build's own, else ``backend_src`` (the tool's own tests). That is
    taken from the folder the tool was started in, since the backend starts in another, where a relative
    path would find some other copy of the code, and refused unless it is inside ``dist`` or this tool's
    own worktree (226)."""

    if not backend_src:
        return dist / "python-core" / "src" if dist else None
    source = Path(backend_src).resolve()
    allowed = [folder for folder in (dist, REPO) if folder is not None]
    if not any(_inside(source, folder) for folder in allowed):
        raise StepFailed(f"The backend source {source} is outside {' and '.join(str(item) for item in allowed)}; "
                         "give one inside the build or this worktree.")
    return source


def _resources(work: Path, dist: Path | None, backend_src: str = "") -> tuple[dict[str, Any], Any]:
    from media_manglers_workbench.resources import discover_runtime_resources  # noqa: PLC0415
    from media_manglers_workbench.settings import load_settings  # noqa: PLC0415

    source = backend_source(dist, backend_src)
    app = load_settings(settings_copy_path(work))
    resources = discover_runtime_resources(app)
    if source is None or not (source / "media_manglers" / "__main__.py").is_file():
        raise StepFailed(f"No packaged backend at {source}.")
    resources.backend_source_root = source
    return app, resources


def _cli(resources: Any, command: str, payload: dict[str, Any], folder: Path, cwd: Path,
         watch: ReadWatch | None = None, dry: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    """One core command the way the pages start it (``ai_video_editor.cli_command``); ``dry`` only
    writes the request and the command."""

    from media_manglers_workbench.ai_video_editor import cli_command  # noqa: PLC0415

    folder.mkdir(parents=True, exist_ok=True)
    request, result = folder / "request.json", folder / "result.json"
    request.write_text(json.dumps({"payload": payload}, indent=2), encoding="utf-8")
    spec = cli_command(resources, command, request, result)
    if dry:
        (folder / "argv.json").write_text(json.dumps(list(spec.argv), indent=1), encoding="utf-8")
        return {"exit_code": None, "dry_run": True, "argv": str(folder / "argv.json")}, {}
    run = _run(list(spec.argv), folder / "log.txt", cwd=cwd)
    if watch is not None:
        run["reads"] = watch.stop()
    return run, _read_json(result)


def smoke(args: argparse.Namespace) -> int:
    from media_manglers_workbench.bug_reports import RecordingRow, build_bug_report_settings  # noqa: PLC0415
    from media_manglers_workbench.command_builder import build_workflow_command  # noqa: PLC0415
    from media_manglers_workbench.metadata import (  # noqa: PLC0415
        WORKFLOW_CODEX_EVIDENCE, WORKFLOW_FULL_REVIEW, WORKFLOW_REVIEW_NEW_VIDEOS)
    from media_manglers.core import raw_bin_library, whisper_options  # noqa: PLC0415

    work, dist, clip = Path(args.work).resolve(), Path(args.dist).resolve(), Path(args.clip).resolve()
    apply_environment(work)
    _guard(work, "work folder", clip.parent)
    app, resources = _resources(work, dist, args.backend_src)
    tools = {"repo_root": str(dist), "script_path": str(dist / "Video Mangler.ps1"), "python_exe": resources.python_exe,
             "ffmpeg_path": resources.ffmpeg_exe, "ffprobe_path": resources.ffprobe_exe, "ytdlp_path": resources.ytdlp_exe}
    powershell = resources.powershell_exe or "powershell"
    base, results = work / "smoke", {}
    # One copy of the clip in the work folder, which all four use: no backend ever works on the clip itself
    # (it may be the read-only test clip, or a recording on the recordings drive).
    copy = base / "clip" / clip.name
    copy.parent.mkdir(parents=True, exist_ok=True)
    if not copy.is_file() or copy.stat().st_size != clip.stat().st_size:
        shutil.copyfile(clip, copy)

    def run(argv: list[str], folder: Path) -> dict[str, Any]:
        if args.dry_run:
            (folder / "argv.json").write_text(json.dumps(argv, indent=1), encoding="utf-8")
            return {"exit_code": None, "dry_run": True}
        outcome = _run(argv, folder / "backend-stdout.txt", cwd=dist)
        return {"exit_code": outcome["exit_code"], "minutes": round(outcome["seconds"] / 60, 1)}

    folder = _fresh(base / "full-review", work)
    settings = {**app, **tools, "default_workflow": WORKFLOW_FULL_REVIEW, "input_kind": "local", "input_path": str(copy),
                "output_folder": str(folder / "out"), "transcript_audio_mode": "Auto", "open_output_in_explorer": False}
    result = run(list(build_workflow_command(settings, workflow=WORKFLOW_FULL_REVIEW, powershell_exe=powershell).argv), folder)
    result["ai_review_zip"] = [str(p) for p in (folder / "out").rglob("ai_review_package.zip")][:1]
    results["1 Full Review"] = result

    folder = _fresh(base / "bug-reports", work)
    settings = build_bug_report_settings(app, [RecordingRow(path=copy)], folder, repo_root=str(dist))
    settings.update(tools)
    result = run(list(build_workflow_command(settings, workflow=WORKFLOW_CODEX_EVIDENCE, powershell_exe=powershell).argv),
                 folder)
    tickets = folder / "codex-evidence-package" / "CANDIDATE_TICKETS.json"
    result["tickets"] = len(_read_json(tickets).get("candidates") or []) if tickets.exists() else None
    results["2 Find my bug reports"] = result

    folder = _fresh(base / "inbox", work)
    settings = {**app, **tools, "default_workflow": WORKFLOW_REVIEW_NEW_VIDEOS, "review_source_folders": str(copy.parent),
                "review_evidence_root": str(folder / "evidence"), "review_local_work_root": str(folder / "work"),
                "review_ledger_path": str(folder / "evidence" / "review-inbox" / "review-ledger.sqlite"),
                "review_inbox_folder": str(folder / "evidence" / "review-inbox"),
                "review_inbox_action": "Process", "review_inbox_workload_mode": "next_3", "output_folder": str(folder / "out")}
    result = run(list(build_workflow_command(settings, workflow=WORKFLOW_REVIEW_NEW_VIDEOS, powershell_exe=powershell).argv),
                 folder)
    log, marker = folder / "backend-stdout.txt", "MM_REVIEW_INBOX_PROCESS_RESULT_V1 "
    contract = [line.split(marker, 1)[1] for line in
                (log.read_text(encoding="utf-8", errors="replace").splitlines() if log.exists() else []) if marker in line]
    if contract:
        data = json.loads(contract[-1])
        result.update({"operator_status": data.get("operator_status"), "queue_counts": data.get("queue_counts")})
    results["3 Review Media Inbox"] = result

    # The raw bin page's scan, of the folder holding the copy of the clip, into the test library.
    whisper = whisper_options.from_settings(app)
    payload = {"folders": [str(copy.parent)], "ffmpeg": str(resources.ffmpeg_exe or "ffmpeg"),
               "ffprobe": str(resources.ffprobe_exe or "ffprobe"), "model_name": whisper["model_name"],
               "prefer_gpu": whisper["prefer_gpu"], "language": whisper["language_code"],
               "track_roles": str(app.get("evidence_track_roles") or ""), "cache_folder": str(app.get("cache_folder") or ""),
               "cache_cap_bytes": int(app.get("cache_size_gb") or 10) * 1024 ** 3}
    runs = raw_bin_library.library_root() / "runs" / f"{datetime.now():%Y%m%d-%H%M%S}-scan"
    result, data = _cli(resources, "raw-bin-scan", payload, runs, dist, dry=args.dry_run)
    if not args.dry_run:
        result = {"exit_code": result["exit_code"], "minutes": round(result["seconds"] / 60, 1),
                  **{key: (data.get("data") or {}).get(key) for key in ("status", "files_read", "failed")}}
        database = raw_bin_library.database_path()
        if database.is_file():
            connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
            try:
                rows = connection.execute("SELECT guess, idle_status, speech_seconds FROM recordings").fetchall()
            finally:
                connection.close()
            result["library_rows"] = [{"guess": a, "idle_status": b, "speech_seconds": c} for a, b, c in rows]
    result["library"] = str(raw_bin_library.library_root())
    results["3 Raw bin scan"] = result

    lines = ["## Features 1-3 through the packaged backend", "",
             f"- Every feature worked on one copy of the clip in the work folder: `{copy}`."]
    for name, item in results.items():
        if item.get("dry_run"):
            lines.append(f"- {name}: command built, not run (dry run).")
            continue
        extra = {key: value for key, value in item.items() if key not in ("exit_code", "minutes")}
        lines.append(f"- {name}: exit code {item['exit_code']} after {item['minutes']} min. {json.dumps(extra)}")
    failed = [name for name, item in results.items() if not item.get("dry_run") and item.get("exit_code") != 0]
    return _finish(args, "smoke", results, lines, 1 if failed else 0)


# The AI Video Editor ---------------------------------------------------------------------------


def scripted_scenes(duration: float, active: list[Any], idle: list[Any], minutes: float) -> list[tuple[float, float, bool]]:
    """(in, out, inside dead time) for a scripted test edit of about ``minutes``: scenes spread evenly
    over the active stretches, and one in the middle of the longest dead-time stretch when there is one."""

    end = max(1.0, float(duration) - 0.2)
    spans = [(max(0.0, float(a)), min(end, float(b))) for a, b in active if min(end, float(b)) - max(0.0, float(a)) >= 2.0]
    spans = spans or [(0.0, end)]
    room = sum(b - a for a, b in spans)
    total = max(4.0, float(minutes) * 60.0)
    count = max(2, round(total / 15.0))
    length = max(1.0, min(total / count, room / count))
    picked: list[tuple[float, float, bool]] = []
    for index in range(count):
        point = (index + 0.5) * room / count
        for a, b in spans:
            if point <= b - a:
                break
            point -= b - a
        start = max(a, min(a + point - length / 2, b - length))
        picked.append((round(start, 1), round(min(b, start + length), 1), False))
    dead = [(float(a), float(b)) for a, b in idle if float(b) - float(a) >= 4.0]
    if dead:
        a, b = max(dead, key=lambda span: span[1] - span[0])
        half = max(1.0, min(length, b - a - 2.0) / 2)
        picked.append((round((a + b) / 2 - half, 1), round((a + b) / 2 + half, 1), True))
    scenes: list[tuple[float, float, bool]] = []
    for start, stop, in_dead in sorted(picked):
        if scenes and start < scenes[-1][1]:
            start = scenes[-1][1]
        if stop - start >= 1.0:
            scenes.append((start, stop, in_dead))
    return scenes


def scripted_timeline(source: Path, tracks: dict[str, int], scenes: list[tuple[float, float, bool]],
                      voice: float, game: float) -> dict[str, Any]:
    from media_manglers.core.race_video.timeline import SCHEMA  # noqa: PLC0415

    rows = []
    for number, (start, stop, in_dead) in enumerate(scenes, start=1):
        scene: dict[str, Any] = {"id": f"s{number:02d}", "beat": "dead time" if in_dead else "scripted",
                                 "reason": SCRIPTED + (", placed inside dead time on purpose" if in_dead else ""),
                                 "in": start, "out": stop, "view": "center", "audio": {"voice": voice, "game": game}}
        if number == 1 and stop - start > 2.6:
            scene["title"] = {"text": "Scripted test edit, not an AI edit", "start": 0.2,
                              "dur": round(min(3.0, stop - start - 0.4), 1), "style": "label"}
        if number == 2 and stop - start > 1.5 and scenes[0][1] - scenes[0][0] > 1.5:
            scene.update({"transition_in": "dissolve", "transition_dur": 0.5})
        rows.append(scene)
    return {"schema": SCHEMA, "source": str(source), "tracks": {"voice": int(tracks["voice"]), "game": int(tracks["game"])},
            "scenes": rows}


def _line_key(segment: Any) -> tuple[float, float]:
    """A line's start and end, as the short-reaction rule matches them (``sparse_narration._line_key``)."""

    segment = segment if isinstance(segment, dict) else {}
    try:
        return round(float(segment.get("start") or 0), 3), round(float(segment.get("end") or 0), 3)
    except (TypeError, ValueError):
        return (-1.0, -1.0)


def _transcript(project: Path) -> dict[str, Any]:
    folder = project / "analysis" / "transcript"
    kept = _read_json(folder / "narration.transcript.json").get("segments")
    raw = _read_json(folder / "narration.transcript.raw.json")
    quality = _read_json(folder / "narration.transcript.quality.json")
    dropped = []
    for item in raw.get("filtered_segments") or []:
        segment = item.get("segment") if isinstance(item.get("segment"), dict) else item
        dropped.append({"reason": str(item.get("reason") or "unknown"), "start": segment.get("start"),
                        "end": segment.get("end"), "text": str(segment.get("text") or "").strip()})
    by_reason = dict(Counter(item["reason"] for item in dropped))
    # raw.json's list is what Whisper's pass kept; the cross-track check and the re-anchoring may take a
    # reaction out after it (into filtered_segments only), so only those still in the transcript count.
    present = {_line_key(segment) for segment in kept or []}
    reactions = [{"start": (item.get("segment") or {}).get("start"), "text": str((item.get("segment") or {}).get("text") or "")
                  .strip(), "line_dbfs": item.get("line_dbfs")} for item in raw.get("short_reactions_kept") or []
                 if _line_key(item.get("segment")) in present]
    heard = _read_json(folder / "game.speech.json")
    left_out = dict(Counter(str(item.get("reason") or "unknown") for item in heard.get("left_out") or []))
    return {"written": kept is not None, "lines_kept": len(kept or []), "dropped_by_reason": by_reason, "dropped": dropped,
            "short_reactions_kept": reactions,
            "short_reactions_kept_count_in_quality": quality.get("short_reactions_kept_count"),
            "words_corrected": len(raw.get("glossary_corrections") or []),
            "game_voices_listened": bool(heard), "game_voices_kept": len(heard.get("segments") or []),
            "game_voices_left_out": left_out, "game_voices_model": heard.get("model")}


def _rendered(run: dict[str, Any], data: dict[str, Any], what: str) -> dict[str, Any]:
    if not data.get("ok"):
        raise StepFailed(f"{what} failed: {data.get('error') or 'exit code ' + str(run['exit_code'])} (log {run['log']})")
    body = data.get("data") or {}
    report, qc = body.get("render") or {}, body.get("technical_check") or {}
    output = Path(str(body.get("export") or report.get("output") or ""))
    size = output.stat().st_size if output.is_file() else 0
    length = float(report.get("expected_duration") or 0)
    shape = report.get("output_format") or {}
    readable = str(report.get("readable_name") or "")
    return {"seconds": run["seconds"], "file": str(output), "mb": round(size / MB, 1),
            "mb_per_minute": round(size / MB / (length / 60), 1) if length else None, "length_seconds": length,
            "fps": shape.get("fps"), "fps_reason": shape.get("fps_reason"), "size": [shape.get("width"), shape.get("height")],
            "encoder": report.get("encoder"), "export_quality": report.get("export_quality"),
            "export_quality_source": report.get("export_quality_source"),
            "picture_renders": report.get("scenes_rendered"), "pictures_reused": report.get("scenes_reused"),
            "sound_renders": report.get("scene_sounds_rendered"),
            "joined_picture": ((report.get("join") or {}).get("picture") or {}).get("state"),
            "readable_name": readable, "readable_present": bool(readable) and Path(readable).is_file(),
            "readable_note": report.get("readable_note"), "check_passed": bool(qc.get("passed")),
            "check_failures": {str(item.get("check")): item.get("detail") for item in qc.get("checks") or []
                               if not item.get("pass")},
            "export": body.get("export"), "masks_applied": report.get("privacy_masks_applied")}


class _Editor:
    """The editor runs for one recording, each through the page's command."""

    def __init__(self, resources: Any, settings: dict[str, Any], root: Path, cwd: Path) -> None:
        self.resources, self.settings, self.root, self.cwd = resources, settings, root, cwd
        self.ffmpeg = str(resources.ffmpeg_exe or "ffmpeg")
        self.ffprobe = str(resources.ffprobe_exe or "ffprobe")
        self.count = 0

    def call(self, kind: str, command: str, payload: dict[str, Any], watch: ReadWatch | None = None
             ) -> tuple[dict[str, Any], dict[str, Any]]:
        self.count += 1
        folder = self.root / "race-videos" / ".runs" / f"{datetime.now():%Y%m%d-%H%M%S}-{self.count:02d}-{kind}"
        return _cli(self.resources, command, {"ffmpeg": self.ffmpeg, "ffprobe": self.ffprobe, **payload}, folder,
                    self.cwd, watch)

    def prepare(self, source: Path, skip: bool, poll: float | None = None, tracks: dict[str, int] | None = None,
                extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Prepare, with the payload the page sends: its engine settings, and the tracks picked by hand
        (``tracks``, 0-based; a track left out is Auto's, 226). ``extra`` changes payload keys."""

        from media_manglers.core.race_video.requests import ENGINE_SETTING_KEYS  # noqa: PLC0415

        payload = {"source": str(source), "output_root": str(self.root),
                   "budget": str(self.settings.get("race_video_budget") or "standard"),
                   **{key: self.settings.get(saved, "") for key, saved in ENGINE_SETTING_KEYS.items()},
                   "progress_label": source.name, **(extra or {})}
        if tracks:
            payload["tracks"] = dict(tracks)
        if skip:
            payload["skip_transcript"] = True
        watch = ReadWatch(source, Path(self.ffmpeg).name if Path(self.ffmpeg).suffix else "ffmpeg.exe", poll).start() \
            if poll else None
        run, data = self.call("prepare", "race-video-prepare", payload, watch)
        if not data.get("ok"):
            raise StepFailed(f"Prepare failed: {data.get('error') or run['exit_code']} (log {run['log']})")
        project = Path(data["data"]["project"])
        meta, analysis = _read_json(project / "project.json"), _read_json(project / "analysis" / "analysis.json")
        return {"project": str(project), "seconds": run["seconds"],
                "progress": progress_summary(run["progress"], run["seconds"]), "progress_lines": run["progress"],
                "reads": run.get("reads"), "sent_tracks": dict(tracks or {}),
                "tracks": meta.get("tracks"), "sounding": meta.get("sounding"), "video": meta.get("video"),
                "privacy_masked": analysis.get("privacy_masked"), "duration": analysis.get("duration"),
                "activity": analysis.get("activity") or {}, "talk_stretches": len(analysis.get("talking") or []),
                "game_sound_spikes": len(analysis.get("game_sound_spikes") or []), "transcript": _transcript(project),
                "log": run["log"]}

    def add(self, project: str, timeline: dict[str, Any], story: str, parent: int | None) -> dict[str, Any]:
        payload = {"project": project, "timeline": timeline, "story": story, "editor_label": EDITOR_LABEL}
        if parent:
            payload["parent"] = parent
        run, data = self.call("add-version", "race-video-add-version", payload)
        if not data.get("ok"):
            raise StepFailed(f"Adding a version failed: {data.get('error')} (log {run['log']})")
        return data["data"]

    def render(self, project: str, version: int, kind: str, **extra: Any) -> dict[str, Any]:
        command = "race-video-export" if kind == "export" else "race-video-render"
        run, data = self.call(kind, command, {"project": project, "version": version,
                                              "progress_label": f"{Path(project).name} v{version:03d}", **extra})
        return _rendered(run, data, f"{kind} of v{version:03d}")


def _fps_copy(ffmpeg: str, source: Path, rate: str, target: Path, seconds: float) -> str:
    """A copy of the start of ``source`` at ``rate`` frames a second, every audio track kept as it is."""

    gop = str(max(1, round(2 * float(Fraction(rate)))))
    for codec in (["-c:v", "hevc_nvenc", "-preset", "p4", "-cq", "23"],
                  ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]):
        done = subprocess.run([ffmpeg, "-hide_banner", "-v", "error", "-y", "-t", f"{seconds}", "-i", str(source),
                               "-map", "0:v:0", "-map", "0:a", "-r", rate, "-fps_mode", "cfr", *codec, "-g", gop,
                               "-c:a", "copy", str(target)], capture_output=True, text=True, creationflags=NO_WINDOW)
        if done.returncode == 0:
            return codec[1]
    raise StepFailed(f"Could not make the {rate} fps copy: {done.stderr.strip()[-300:]}")


def _existing_project(root: Path, source: Path) -> str:
    """The project folder a Prepare of ``source`` would reopen, when it is already there (226): a second
    run into the same work folder would add its versions after the first run's and test those."""

    from media_manglers.core.race_video.project import slug  # noqa: PLC0415

    folder = root / "race-videos" / slug(source.stem)
    return str(folder) if (folder / "project.json").exists() else ""


def chosen_tracks(voice: int, game: int) -> dict[str, int]:
    """--voice-track and --game-track (Track 1 is 1, 0 is Auto) as the page sends tracks picked by hand:
    0-based, and only those picked (226)."""

    picked: dict[str, int] = {}
    for name, number in (("voice", voice), ("game", game)):
        if int(number or 0) < 0:
            raise StepFailed(f"--{name}-track is a track number (Track 1 is 1) or 0 for Auto, not {number}.")
        if number:
            picked[name] = int(number) - 1
    return picked


def silent_game_track(prepared: dict[str, Any]) -> str:
    """Why the game track a Prepare used makes every render fail, or "" (226): it is not among the
    tracks with sound (project.json "sounding") and its loudness per second is silent by the analysis's
    own rule (``activity_timeline.is_silent``). A steady engine sound is left out of "sounding" too (it
    never rises above its own floor), but it is sound, and its renders pass."""

    from media_manglers.core import activity_timeline  # noqa: PLC0415

    tracks, sounding = prepared.get("tracks") or {}, prepared.get("sounding")
    game = tracks.get("game")
    if not isinstance(game, int) or not isinstance(sounding, list) or game in sounding:
        return ""
    analysis = _read_json(Path(prepared["project"]) / "analysis" / "analysis.json")
    levels = (analysis.get("loudness_per_second") or {}).get(str(game))
    if isinstance(levels, list) and not activity_timeline.is_silent(levels):
        return ""
    return (f"Track {game + 1}, the game track Prepare used for {Path(prepared['project']).name}, is silent for the "
            "whole recording, so an edit would have no game sound and its renders would fail on dead air; choose the "
            "game track with --game-track N.")


def _listening(prepared: dict[str, Any]) -> dict[str, Any]:
    """How long a Prepare listened for other voices on the game track (its "Listening for other voices"
    step, the model's loading included) and what it kept and left out."""

    from media_manglers.core.race_video.requests import LISTENING  # noqa: PLC0415

    phases = [item for item in (prepared.get("progress") or {}).get("phases") or [] if item["phase"] == LISTENING]
    words = prepared.get("transcript") or {}
    return {"project": prepared["project"], "model": words.get("game_voices_model"),
            "listening_seconds": phases[0]["seconds"] if phases else None, "prepare_seconds": prepared["seconds"],
            "kept": words.get("game_voices_kept"), "left_out": words.get("game_voices_left_out") or {},
            "listened": bool(words.get("game_voices_listened"))}


def compare_quick_models(resources: Any, settings: dict[str, Any], root: Path, cwd: Path, recording: Path, skip: bool,
                         prepared: dict[str, Any], problems: list[str]) -> dict[str, Any]:
    """The quick passes on the main Whisper model against the settings copy's (226, decision C): a second
    Prepare of the recording into a fresh project under ``root``, on the tracks the first one used,
    with ``race_video_quick_whisper_model`` "main". Each model's time listening for other voices on the
    game track, and what it kept and left out. The first Prepare's project is not touched."""

    from media_manglers.core.race_video.requests import QUICK_MODEL_KEY, QUICK_MODEL_MAIN  # noqa: PLC0415

    first = _listening(prepared)
    if skip:
        problems.append("the quick passes' models were not compared: the transcript was skipped")
        return {"compared": False, "reason": "the transcript was skipped", "settings_model": first}
    if str(settings.get(QUICK_MODEL_KEY) or "").strip().casefold() == QUICK_MODEL_MAIN:
        problems.append("the quick passes' models were not compared: the settings copy already sets them to the "
                        "main Whisper model, so both runs would use the same one")
        return {"compared": False, "reason": "both runs would use the main model", "settings_model": first}
    tracks = prepared.get("tracks") or {}
    same = {name: int(tracks[name]) for name in ("voice", "game") if isinstance(tracks.get(name), int)}
    again = _Editor(resources, settings, root, cwd).prepare(recording, False, tracks=same,
                                                            extra={QUICK_MODEL_KEY: QUICK_MODEL_MAIN})
    silent = silent_game_track(again)
    if silent:
        raise StepFailed(silent)
    main = _listening(again)
    if not (first["listened"] and main["listened"]):
        problems.append("the quick passes' models were not compared: a Prepare did not listen for other voices")
    elif first["model"] and first["model"] == main["model"]:
        problems.append(f"the quick passes' models were not compared: both runs used Whisper {first['model']}")
    return {"compared": True, "tracks": same, "settings_model": first, "main_model": main}


def _keep(item: dict[str, Any], folder: Path, label: str) -> dict[str, Any]:
    """A copy of an export as it is now, as ``<label>-<its name>`` in ``folder``, with its SHA-256: the next
    export of the same version replaces the export file. A copy, not a link, because the export is itself
    a hard link to the final render."""

    export = Path(str(item.get("export") or ""))
    if not item.get("export") or not export.is_file():
        return {"kept": "", "kept_sha256": ""}
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{label}-{export.name}"
    shutil.copyfile(export, target)
    return {"kept": str(target), "kept_sha256": _sha256(target)}


def editor(args: argparse.Namespace) -> int:
    from media_manglers_workbench.ai_video_editor import editor_output_root  # noqa: PLC0415

    work, recording = Path(args.work).resolve(), Path(args.recording).resolve()
    if _inside(work, recording.parent):
        raise Refused("The work folder is beside the recording; nothing may be written next to it.")
    apply_environment(work)
    _guard(work, "work folder", recording.parent)
    qualities = [item.strip() for item in args.qualities.split(",") if item.strip()]
    unknown = [quality for quality in qualities if quality not in QUALITY_NAMES]
    if unknown:
        raise StepFailed(f"Unknown export quality {unknown[0]!r}: choose from {', '.join(QUALITY_NAMES)}.")
    dist = Path(args.dist).resolve() if args.dist else None
    app, resources = _resources(work, dist, args.backend_src)
    root = editor_output_root(app)
    if not _inside(root, work):
        raise StepFailed(f"The settings copy's editor folder {root} is not inside the work folder.")
    cwd = dist or work
    copy = work / "clip" / args.copy_name if args.copy_name else None
    fps_targets = {rate: work / "fps-copies" / f"fps-{rate.split('/')[0]}.mkv" for rate in FPS_RATES} \
        if args.fps_copies else {}
    # The second Prepare's own folder, so its project is a fresh one (--compare-quick-models).
    quick_root = work / "quick-models" / "main"
    result: dict[str, Any] = {"recording": str(recording), "name": (copy or recording).name, "label": SCRIPTED}
    problems: list[str] = []
    try:
        picked = chosen_tracks(args.voice_track, args.game_track)
        result["chosen_tracks"] = picked
        existing = [found for found in (_existing_project(root, path) for path in (copy or recording, *fps_targets.values()))
                    if found]
        if args.compare_quick_models:
            existing += [found for found in [_existing_project(quick_root, copy or recording)] if found]
        if existing:
            raise StepFailed(f"The work folder already has a project for this recording ({existing[0]}); a second run "
                             "would add its versions after the first run's. Use a new work folder.")
        if copy is not None:
            copy.parent.mkdir(parents=True, exist_ok=True)
            if not copy.is_file() or copy.stat().st_size != recording.stat().st_size:
                shutil.copyfile(recording, copy)
            recording = copy
            result["copy"] = str(copy)
        skip = bool(args.skip_transcript)
        if not skip and subprocess.run([str(resources.python_exe), "-c", "import importlib.util,sys; "
                                        "sys.exit(0 if importlib.util.find_spec('whisper') else 1)"],
                                       creationflags=NO_WINDOW).returncode != 0:
            skip, result["transcript_skipped"] = True, f"Whisper is not installed in {resources.python_exe}"
        runner = _Editor(resources, app, root, cwd)
        prepared = runner.prepare(recording, skip, args.poll_seconds, tracks=picked)
        result["prepare"] = prepared
        silent = silent_game_track(prepared)
        if silent:
            raise StepFailed(silent)
        project, tracks = prepared["project"], prepared["tracks"]
        if args.compare_quick_models:
            result["quick_models"] = compare_quick_models(resources, app, quick_root, cwd, recording, skip, prepared,
                                                          problems)
        activity = prepared["activity"]
        scenes = scripted_scenes(float(prepared["duration"] or 0), activity.get("active_stretches") or [],
                                 activity.get("idle_stretches") or [], args.scripted_minutes)
        story = (f"{SCRIPTED[0].upper()}{SCRIPTED[1:]}: written by the Wave 7 validation tool from the analysis, "
                 "scenes spread over the active stretches, one inside dead time when there is any.")
        versions: dict[str, Any] = {}
        # In the result from here on, so a run that stops part way still reports what it did.
        result.update({"scenes": [{"in": a, "out": b, "dead_time": c} for a, b, c in scenes],
                       "scripted_seconds": round(sum(b - a for a, b, _ in scenes), 1), "versions": versions,
                       "problems": problems})
        # Each version is used by the number add-version gives it.
        first = runner.add(project, scripted_timeline(recording, tracks, scenes, 1.0, 0.6), story, None)
        one = int(first["version"])
        versions["v001"] = {"version": one, "notes": first.get("notes"),
                            "preview": runner.render(project, one, "preview", profile="preview")}
        _cmd, kit = runner.call("review-kit", "race-video-review-kit",
                                {"project": project, "version": one, "profile": "preview", "transcribe": False})
        versions["v001"]["pacing_in_dead_time"] = [row for row in (kit.get("data") or {}).get("pacing") or []
                                                   if float(row.get("idle_seconds") or 0) > 0]
        versions["v001"]["review_kit_error"] = "" if kit.get("ok") else str(kit.get("error") or "it did not run")
        if versions["v001"]["review_kit_error"]:
            problems.append(f"review kit: {versions['v001']['review_kit_error']}")
        two = int(runner.add(project, scripted_timeline(recording, tracks, scenes, 1.25, 0.4), "Sound only: gains changed.",
                             one)["version"])
        versions["v002"] = {"version": two, "preview": runner.render(project, two, "preview", profile="preview")}
        three = int(runner.add(project, scripted_timeline(recording, tracks, scenes, 1.1, 0.5),
                               "Sound only, stored unrendered.", two)["version"])
        versions["v003"] = {"version": three, "stored_not_rendered": True}
        # As the page exports it, with no quality in the request (the video's own choice, else the main
        # setting), then each quality asked for; each export is kept before the next replaces it.
        kept = work / "exports"
        as_set = runner.render(project, two, "export")
        versions["v002"]["export_as_set"] = {**as_set, **_keep(as_set, kept, "as-set")}
        exports: dict[str, Any] = {}
        versions["v002"]["exports"] = exports
        for quality in qualities:
            done = runner.render(project, two, "export", export_quality=quality)
            exports[quality] = {**done, **_keep(done, kept, quality)}
        if args.validation_size:
            width, height = (int(value) for value in args.validation_size.lower().split("x"))
            versions["v002"]["validation"] = runner.render(project, two, "validation", profile="final",
                                                           validation_size=[width, height])
        if fps_targets:
            copies: dict[str, Any] = {}
            result["fps_copies"] = copies
            for rate, target in fps_targets.items():
                target.parent.mkdir(parents=True, exist_ok=True)
                codec = _fps_copy(runner.ffmpeg, recording, rate, target, args.fps_copy_seconds)
                streams, _length = voice_track.probe_audio_streams(runner.ffprobe, target)
                # The copies keep every track, so the tracks picked for the recording are theirs too.
                ready = runner.prepare(target, skip, tracks=picked)
                copies[rate] = {"copy": str(target), "encoder": codec, "prepare_tracks": ready["tracks"],
                                "sent_tracks": ready["sent_tracks"]}
                silent = silent_game_track(ready)
                if silent:
                    raise StepFailed(silent)
                length = float(ready["duration"] or 0)
                added = runner.add(ready["project"], scripted_timeline(target, ready["tracks"], scripted_scenes(
                    length, [[0, length]], [], min(length, 20.0) / 60), 1.0, 0.6), "Frame-rate check.", None)
                done = runner.render(ready["project"], int(added["version"]), "export", export_quality="youtube")
                probed = frame_render.probe_video(runner.ffprobe, Path(done["file"])) if done["file"] else {}
                copies[rate].update({"titles": [str((s.get("tags") or {}).get("title") or "") for s in streams],
                                     "recording_fps": (ready["video"] or {}).get("avg_frame_rate"), "export": done,
                                     "exported_fps": probed.get("frame_rate_text")})
        renders = [*[item for version in versions.values() for item in (version.get("preview"), version.get("validation"))
                     if item], versions["v002"]["export_as_set"], *exports.values(),
                   *[item["export"] for item in (result.get("fps_copies") or {}).values() if "export" in item]]
        result["failed_checks"] = sorted({name for item in renders for name in item["check_failures"]})
        code = 1 if result["failed_checks"] or problems else 0
    except StepFailed as exc:
        result["failed"], code = str(exc), 2
    except Exception as exc:  # noqa: BLE001 - an unexpected stop still writes the result file
        result.update({"failed": f"unexpected {type(exc).__name__}: {exc}", "traceback": traceback.format_exc()})
        code = 2
    return _finish(args, f"editor-{(copy or recording).stem}", result, _editor_lines(result), code)


def _editor_lines(result: dict[str, Any]) -> list[str]:
    lines = [f"## AI Video Editor: `{result.get('name') or Path(result['recording']).name}`", ""]
    prepared = result.get("prepare") or {}
    if prepared:
        tracks, reads, progress = prepared.get("tracks") or {}, prepared.get("reads") or {}, prepared["progress"]
        voice, game = (DECIDED.get(str(tracks.get(f"{name}_decided_by")), "?") for name in ("voice", "game"))
        lines.append(f"- Prepare took {_clock(prepared['seconds'])} ({prepared['seconds']} s). Your voice: Track "
                     f"{int(tracks.get('voice', -1)) + 1} ({voice}); the game sound: Track {int(tracks.get('game', -1)) + 1} "
                     f"({game}). Privacy masks applied to the stills: {prepared.get('privacy_masked')}.")
        if reads:
            lines.append(f"- Reads of the recording: {reads['full_reads']} full read(s), {reads['part_reads']} part read(s), "
                         f"at least {reads['still_seeks']} still seek(s) (one that starts and ends between two looks is "
                         f"missed); FFmpeg read {reads['read_bytes'] / MB:.0f} MB in its reads ({reads['read_share']}x the "
                         f"file) and {reads['seek_bytes'] / MB:.0f} MB in still seeks.")
        lines.append(f"- Progress: {progress['lines']} status lines; the longest silence was "
                     f"{progress['longest_silence_seconds']} s (at {_clock(progress['longest_silence_at'])}). Per step: " +
                     "; ".join(f"{item['phase']} {item['seconds']} s" for item in progress["phases"]) + ".")
        words = prepared["transcript"]
        if words["written"]:
            reasons = ", ".join(f"{count} {reason}" for reason, count in sorted(words["dropped_by_reason"].items()))
            lines.append(f"- Narration: {words['lines_kept']} lines kept; {len(words['dropped'])} left out "
                         f"({reasons or 'none'}); {len(words['short_reactions_kept'])} short reaction(s) kept in the "
                         f"transcript; {words['words_corrected']} word(s) corrected by the word list.")
            lines += [f"  - left out [{_clock(item['start'] or 0)}] {item['reason']}: {item['text']}"
                      for item in words["dropped"]]
            lines += [f"  - reaction kept [{_clock(item['start'] or 0)}] {item['text']}"
                      for item in words["short_reactions_kept"]]
        else:
            lines.append(f"- Narration: not written ({result.get('transcript_skipped') or 'skipped'}).")
        if words["game_voices_listened"]:
            lines.append(f"- Other voices on the game track: {words['game_voices_kept']} kept, left out: "
                         f"{json.dumps(words['game_voices_left_out'])}.")
        quick = result.get("quick_models") or {}
        if quick.get("compared"):
            lines.append("- The quick passes' models, each in its own Prepare of the recording (the second, into a "
                         "fresh project, read the recording again); listening includes loading the model:")
            for label, item in (("settings copy's model", quick["settings_model"]), ("main model", quick["main_model"])):
                lines.append(f"  - {label} ({item['model'] or 'none stored'}): listening for other voices "
                             f"{item['listening_seconds']} s, Prepare {item['prepare_seconds']} s; {item['kept']} kept, "
                             f"left out: {json.dumps(item['left_out'])}.")
        elif quick:
            lines.append(f"- The quick passes' models were not compared: {quick.get('reason')}.")
        activity = prepared["activity"]
        stretches, found = activity.get("idle_stretches") or [], activity.get("idle_by") or []
        lines.append(f"- Dead time ({activity.get('status')}): {len(stretches)} stretch(es). Talk stretches "
                     f"{prepared['talk_stretches']}, game-sound spikes {prepared['game_sound_spikes']}.")
        for position, (start, end) in enumerate(stretches):
            by = found[position] if position < len(found) else []
            lines.append(f"  - {_clock(start)}-{_clock(end)}: found by {_found_by(by)}"
                         f"{' (one signal only)' if len(by) < 2 else ''}")
    versions = result.get("versions") or {}
    first, second = versions.get("v001") or {}, versions.get("v002") or {}
    if "scenes" in result:
        dead = [scene for scene in result["scenes"] if scene["dead_time"]]
        lines.append(f"- Scripted test edit (written by this tool, not an AI edit): {len(result['scenes'])} scenes, "
                     f"{result['scripted_seconds']} s, {'one inside dead time' if dead else 'none inside dead time'}. "
                     f"Notes when added: {len(first.get('notes') or [])}; pacing rows in dead time: "
                     f"{len(first.get('pacing_in_dead_time') or [])}.")
    if first.get("review_kit_error"):
        lines.append(f"- The review kit did not run: {first['review_kit_error']}")

    def said(name: str, item: dict[str, Any], extra: str = "") -> str:
        failed = "; ".join(f"{check}: {detail}" for check, detail in item["check_failures"].items())
        check = "passed" if item["check_passed"] else f"FAILED ({failed})"
        readable = (f"readable name present: {Path(item['readable_name']).name}" if item["readable_present"] else
                    f"no readable name ({item.get('readable_note') or 'missing'})")
        return (f"- {name}: {item['seconds']} s, {item['picture_renders']} picture render(s), joined picture "
                f"{item['joined_picture']}, {item['fps']} fps, {item['mb']} MB ({item['mb_per_minute']} MB per minute), "
                f"technical check {check}{extra}, {readable}.")

    def exported(item: dict[str, Any]) -> str:
        name = Path(str(item.get("export") or "")).name or "MISSING"
        copy = (f", kept as `{Path(item['kept']).name}` (SHA-256 {item['kept_sha256'][:12]})" if item.get("kept")
                else ", not kept (no export file)")
        return f", export file {name}{copy}"

    if first.get("preview"):
        lines.append(said(f"v{first['version']:03d} preview", first["preview"]))
    if second.get("preview"):
        lines.append(said(f"v{second['version']:03d} preview (sound only)", second["preview"]))
    if versions.get("v003"):
        lines.append(f"- v{versions['v003']['version']:03d} (sound only) is stored and not rendered.")
    if second.get("export_as_set"):
        item = second["export_as_set"]
        lines.append(said(f"v{second['version']:03d} export as the page makes it (no quality in the request): "
                          f"{item['export_quality']}, from {item['export_quality_source']}", item, exported(item)))
    for quality, item in (second.get("exports") or {}).items():
        lines.append(said(f"v{second['version']:03d} export, {quality} (from {item['export_quality_source']})", item,
                          exported(item)))
    if second.get("validation"):
        check = second["validation"]
        lines.append(said(f"v{second['version']:03d} validation render {check['size']}", check))
    for rate, item in (result.get("fps_copies") or {}).items():
        if "export" not in item:
            lines.append(f"- {rate} fps copy ({item['encoder']}): prepared, not exported.")
            continue
        lines.append(f"- {rate} fps copy ({item['encoder']}, tracks {item['titles']}): recording {item['recording_fps']}, "
                     f"exported at {item['exported_fps']}, check {'passed' if item['export']['check_passed'] else 'FAILED'}.")
    if "failed_checks" in result:
        lines.append(f"- Every render passed its technical check: "
                     f"{'yes' if not result['failed_checks'] else 'NO, failed: ' + ', '.join(result['failed_checks'])}.")
    if result.get("problems"):
        lines.append(f"- The step FAILED: {'; '.join(result['problems'])}.")
    if result.get("failed"):
        lines.append(f"- STOPPED: {result['failed']}")
    return lines


# The analysis against an older backend ---------------------------------------------------------


def pair_stretches(old: list[Any], new: list[Any]) -> list[dict[str, Any]]:
    """Every stretch of the older analysis and of this one, by time: the same, moved (paired with the
    stretch of the other it overlaps most, each used once), or in one only. A spike that keeps its times
    but not its peak is "peak changed"."""

    def span(item: Any) -> tuple[float, float]:
        return float(item["start"]), float(item["end"])

    rows: list[dict[str, Any]] = []
    left, right = list(old or []), list(new or [])
    for item in list(left):
        twin = next((other for other in right if span(other) == span(item)), None)
        if twin is not None:
            left.remove(item)
            right.remove(twin)
            same = item.get("peak_db") == twin.get("peak_db")
            rows.append({"kind": "same" if same else "peak changed", "old": item, "new": twin})
    overlaps = sorted(((min(span(a)[1], span(b)[1]) - max(span(a)[0], span(b)[0]), index, other)
                       for index, a in enumerate(left) for other, b in enumerate(right)
                       if min(span(a)[1], span(b)[1]) > max(span(a)[0], span(b)[0])), reverse=True)
    paired_left: set[int] = set()
    paired_right: set[int] = set()
    for _overlap, index, other in overlaps:
        if index in paired_left or other in paired_right:
            continue
        paired_left.add(index)
        paired_right.add(other)
        rows.append({"kind": "moved", "old": left[index], "new": right[other]})
    rows += [{"kind": "only_old", "old": item, "new": None} for index, item in enumerate(left) if index not in paired_left]
    rows += [{"kind": "only_new", "old": None, "new": item} for other, item in enumerate(right) if other not in paired_right]
    return sorted(rows, key=lambda row: span(row["old"] or row["new"]))


def track_row_differences(old: list[Any], new: list[Any]) -> list[dict[str, Any]]:
    """Every field of the per-track rows (name, role, median level, share audible) that differs, by track."""

    before = {int(row["track"]): row for row in old or [] if isinstance(row, dict) and "track" in row}
    after = {int(row["track"]): row for row in new or [] if isinstance(row, dict) and "track" in row}
    found = []
    for track in sorted(set(before) | set(after)):
        if track not in after or track not in before:
            found.append({"track": track, "field": "row", "old": before.get(track), "new": after.get(track)})
            continue
        for field in sorted(set(before[track]) | set(after[track])):
            if before[track].get(field) != after[track].get(field):
                found.append({"track": track, "field": field, "old": before[track].get(field),
                              "new": after[track].get(field)})
    return found


def compare_analysis(args: argparse.Namespace) -> int:
    """Prepare the recording with this build and with an older backend, transcript skipped, on the same
    tracks, and list every difference in talk stretches, game-sound spikes and track rows (226)."""

    work, recording = Path(args.work).resolve(), Path(args.recording).resolve()
    if _inside(work, recording.parent):
        raise Refused("The work folder is beside the recording; nothing may be written next to it.")
    apply_environment(work)
    _guard(work, "work folder", recording.parent)
    baseline = Path(args.baseline_src).resolve()
    if not (baseline / "media_manglers" / "cli.py").is_file():
        raise StepFailed(f"No media_manglers/cli.py in {baseline}: give the src folder of `git archive 9e065e4 src`.")
    dist = Path(args.dist).resolve() if args.dist else None
    app, resources = _resources(work, dist, args.backend_src or ("" if dist else str(REPO / "src")))
    old_resources = shallow_copy(resources)
    old_resources.backend_source_root = baseline
    cwd = dist or work
    roots = {"new": work / "compare-analysis" / "this-build", "old": work / "compare-analysis" / "baseline"}
    existing = [found for found in (_existing_project(root, recording) for root in roots.values()) if found]
    if existing:
        raise StepFailed(f"The work folder already has a compared project for this recording ({existing[0]}). Use a new "
                         "work folder.")
    label = args.baseline_label
    result: dict[str, Any] = {"recording": str(recording), "baseline_src": str(baseline), "baseline_label": label,
                              "this_build_src": str(resources.backend_source_root)}
    try:
        runner = _Editor(resources, app, roots["new"], cwd)
        new = runner.prepare(recording, True, tracks=chosen_tracks(args.voice_track, args.game_track))
        result["this_build"] = {key: new[key] for key in ("project", "seconds", "tracks", "talk_stretches",
                                                          "game_sound_spikes", "log")}
        silent = silent_game_track(new)
        if silent:
            raise StepFailed(silent)
        tracks = {name: int(new["tracks"][name]) for name in ("voice", "game")}
        # The older backend has no track choice of its own, so it is given the tracks this build used.
        payload = {"ffmpeg": runner.ffmpeg, "ffprobe": runner.ffprobe, "source": str(recording),
                   "output_root": str(roots["old"]), "budget": str(app.get("race_video_budget") or "standard"),
                   "skip_transcript": True, "tracks": tracks, "progress_label": recording.name}
        run, data = _cli(old_resources, "race-video-prepare", payload,
                         roots["old"] / "race-videos" / ".runs" / "prepare", cwd)
        if not data.get("ok"):
            raise StepFailed(f"The {label} Prepare failed: {data.get('error') or run['exit_code']} (log {run['log']})")
        old_project = Path(data["data"]["project"])
        old_analysis = _read_json(old_project / "analysis" / "analysis.json")
        new_analysis = _read_json(Path(new["project"]) / "analysis" / "analysis.json")
        result["baseline"] = {"project": str(old_project), "seconds": run["seconds"], "tracks": tracks,
                              "log": run["log"], "talk_stretches": len(old_analysis.get("talking") or []),
                              "game_sound_spikes": len(old_analysis.get("game_sound_spikes") or [])}
        result["talking"] = pair_stretches(old_analysis.get("talking"), new_analysis.get("talking"))
        result["game_sound_spikes"] = pair_stretches(old_analysis.get("game_sound_spikes"),
                                                     new_analysis.get("game_sound_spikes"))
        result["track_rows"] = track_row_differences(old_analysis.get("tracks"), new_analysis.get("tracks"))
        result["differences"] = (sum(1 for name in ("talking", "game_sound_spikes") for row in result[name]
                                     if row["kind"] != "same") + len(result["track_rows"]))
        code = 0
    except StepFailed as exc:
        result["failed"], code = str(exc), 2
    return _finish(args, f"compare-analysis-{recording.stem}", result, _compare_lines(result), code)


def _compare_lines(result: dict[str, Any]) -> list[str]:
    label = result["baseline_label"]
    lines = [f"## The analysis against {label}: `{Path(result['recording']).name}`", ""]
    if "differences" not in result:
        return [*lines, f"- STOPPED: {result.get('failed') or 'it did not finish'}"]
    new, old = result["this_build"], result["baseline"]
    tracks = old["tracks"]
    lines.append(f"- Both Prepares used Track {tracks['voice'] + 1} as your voice and Track {tracks['game'] + 1} as the "
                 f"game sound, transcript skipped. This build: {new['talk_stretches']} talk stretch(es), "
                 f"{new['game_sound_spikes']} game-sound spike(s); {label}: {old['talk_stretches']} and "
                 f"{old['game_sound_spikes']}. Differences: {result['differences']} (listed, not failed).")

    def stretch(item: dict[str, Any] | None) -> str:
        text = f"{_clock(item['start'])}-{_clock(item['end'])}" if item else ""
        return f"{text} (peak {item['peak_db']} dB)" if item and "peak_db" in item else text

    for name, title in (("talking", "Talk stretches"), ("game_sound_spikes", "Game-sound spikes")):
        rows = [row for row in result[name] if row["kind"] != "same"]
        lines.append(f"- {title}: {len(result[name]) - len(rows)} the same, {len(rows)} different.")
        for row in rows:
            if row["kind"] == "only_old":
                lines.append(f"  - only in {label}: {stretch(row['old'])}")
            elif row["kind"] == "only_new":
                lines.append(f"  - only in this build: {stretch(row['new'])}")
            else:
                lines.append(f"  - {row['kind']}: {stretch(row['old'])} in {label}, {stretch(row['new'])} in this build")
    lines.append(f"- Track rows: {len(result['track_rows'])} difference(s).")
    lines += [f"  - Track {item['track']} {item['field']}: {item['old']!r} in {label}, {item['new']!r} in this build"
              for item in result["track_rows"]]
    return lines


# Dead-time frames ------------------------------------------------------------------------------


def _tools(args: argparse.Namespace) -> tuple[str, str]:
    saved = _saved(Path(args.work)) if getattr(args, "work", None) else {}
    return (str(saved.get("dependency_ffmpeg_path") or shutil.which("ffmpeg") or "ffmpeg"),
            str(saved.get("dependency_ffprobe_path") or shutil.which("ffprobe") or "ffprobe"))


def _not_its_recording(project: Path, meta: dict[str, Any], recording: Path) -> str:
    """Why ``recording`` is not the one ``project`` was prepared from, or "" (226): by the editor's own
    same-recording check (``project.source_fingerprint``: name, size and modified time), else by path."""

    from media_manglers.core.race_video.project import source_fingerprint  # noqa: PLC0415

    if not meta:
        return f"{project} holds no project.json"
    if not recording.is_file():
        return f"{recording} is not a file"
    source, stored = str(meta.get("source") or ""), meta.get("source_fingerprint")
    same_path = bool(source) and os.path.normcase(os.path.abspath(source)) == os.path.normcase(os.path.abspath(recording))
    if isinstance(stored, dict) and stored:
        if stored == source_fingerprint(recording):
            return ""
        if same_path:
            return f"{recording} has changed since the project was prepared from it"
    elif same_path:
        return ""
    return f"the project was prepared from {source or 'another recording'}, not {recording}"


def dead_time_frames(args: argparse.Namespace) -> int:
    from media_manglers.core.race_video import privacy  # noqa: PLC0415

    if args.work:
        apply_environment(Path(args.work))
    project, recording, out = Path(args.project), Path(args.recording), Path(args.out)
    _guard(out, "frames folder", recording.parent)
    ffmpeg, ffprobe = _tools(args)
    meta, analysis = _read_json(project / "project.json"), _read_json(project / "analysis" / "analysis.json")
    layout = meta.get("layout") if isinstance(meta.get("layout"), dict) else analysis.get("layout") or {}
    panels = layout.get("panels") or {}
    video: dict[str, Any] = {}
    # Checked before anything is written: frames of another recording would be the wrong pictures.
    problem = _not_its_recording(project, meta, recording)
    if not problem and os.environ.get("MEDIA_MANGLERS_RACE_VIDEO_PRIVACY"):
        problem = "MEDIA_MANGLERS_RACE_VIDEO_PRIVACY is set, so the stored privacy masks cannot be checked"
    if not problem:
        video = frame_render.probe_video(ffprobe, recording)
        if (int(video.get("width") or 0), int(video.get("height") or 0)) != (int(layout.get("width") or -1),
                                                                           int(layout.get("height") or -1)):
            problem = (f"the recording is {video.get('width')}x{video.get('height')}, but the project's layout is "
                       f"{layout.get('width')}x{layout.get('height')}")
        elif "center" not in panels:
            problem = "the project's layout has no center panel"
        else:
            masks = privacy.load_masks(privacy.default_store())
            missing = [panel for panel in ("left", "right") if panel not in masks]
            if missing:
                problem = f"no stored privacy mask for the {' and '.join(missing)} camera"
            elif any(privacy.overlaps(panels["center"], panels[name]) for name in ("left", "right") if name in panels):
                problem = "the center panel overlaps a masked camera panel"
    if problem:
        result = {"written": False, "reason": problem}
        lines = ["## Dead-time frames", "", f"- No frames were written: {problem}."]
        return _finish(args, "dead-time-frames", result, lines, 1)
    centre = [int(value) for value in panels["center"]]
    activity = analysis.get("activity") or {}
    stretches, found = activity.get("idle_stretches") or [], activity.get("idle_by") or []
    middles = [round((float(a) + float(b)) / 2, 2) for a, b in stretches]
    duration = float(analysis.get("duration") or video.get("duration") or 0)
    times = [float(t) for t in range(0, max(1, int(duration)), 300)]
    sheet = out / "overview-every-5-minutes.jpg"
    created = not out.exists()
    try:
        out.mkdir(parents=True, exist_ok=True)
        frames = frame_render.render_stills(ffmpeg, recording, middles, out, crop=centre, stamp=True, quality=3, workers=2,
                                            name="dead-time-{index:02d}.jpg", start_index=1, reuse=False) if middles else []
        stills = out / "overview-stills"
        frame_render.render_stills(ffmpeg, recording, times, stills, crop=centre, scale=(640, 360), stamp=True, workers=2,
                                   reuse=False)
        columns = min(5, len(times))
        frame_render.contact_sheets(ffmpeg, stills, len(times), 0.0, 300.0, (0, 0, 640, 360), out / "overview",
                                    tile=(480, 270), columns=columns, rows=math.ceil(len(times) / columns), label=False)
        os.replace(out / "overview" / "sheet-01.jpg", sheet)
        shutil.rmtree(out / "overview", ignore_errors=True)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        if created:
            shutil.rmtree(out, ignore_errors=True)
        raise StepFailed(f"The frames could not be made: {exc}") from exc
    rows = [{"file": str(path), "at": at, "stretch": [a, b], "found_by": found[index] if index < len(found) else []}
            for index, (path, at, (a, b)) in enumerate(zip(frames, middles, stretches))]
    result = {"written": True, "centre_panel": centre, "frames": rows, "overview": str(sheet), "overview_times": times}
    (out / "frames.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    lines = ["## Dead-time frames", "", f"- {len(rows)} frame(s), one from the middle of each dead-time stretch, and an "
             f"overview sheet with a frame every 5 minutes ({len(times)} frames), of the centre game panel only "
             f"({centre}), in `{out}`."]
    lines += [f"  - `{Path(row['file']).name}`: {_clock(row['at'])}, stretch {_clock(row['stretch'][0])}-"
              f"{_clock(row['stretch'][1])}, found by {_found_by(row['found_by'])}" for row in rows]
    return _finish(args, "dead-time-frames", result, lines, 0)


# The raw bin's read path -----------------------------------------------------------------------


def rawbin_spike(args: argparse.Namespace) -> int:
    from media_manglers.core import raw_bin_library  # noqa: PLC0415

    work, recording = Path(args.work).resolve(), Path(args.recording).resolve()
    if _inside(work, recording.parent):
        raise Refused("The work folder is beside the recording; nothing may be written next to it.")
    apply_environment(work)
    _guard(work, "work folder", recording.parent)
    ffmpeg, ffprobe = _tools(args)
    with recording.open("rb") as handle:
        head = handle.read(raw_bin_library.HEAD_BYTES)
    streams, duration = raw_bin_library._probe_bytes(ffprobe, head)
    video = frame_render.probe_video(ffprobe, recording)
    found = frame_render.picture_region(int(video.get("width") or 0), int(video.get("height") or 0))
    if not streams or found is None:
        raise StepFailed("The recording has no audio tracks or no picture to measure.")
    box, region = found
    runs = []
    for label, picture in (("sound only", False), ("sound and the game picture", True)):
        folder = _fresh(work / "rawbin-spike" / ("picture" if picture else "sound"), work)
        wavs = {ordinal: folder / f"track-{ordinal}.wav" for ordinal in range(len(streams))}
        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                   *(frame_render.picture_input_options() if picture else []), "-i", "pipe:0"]
        for ordinal, target in wavs.items():
            command += voice_track._pcm_output(f"0:a:{ordinal}", target)
        frames, times = folder / "picture-samples.raw", folder / "picture-sample-times.txt"
        if picture:
            command += frame_render.picture_output(box, frames, times)
        started = time.monotonic()
        with (folder / "errors.txt").open("w", encoding="utf-8") as errors, recording.open("rb") as source:
            # Below normal priority, as the real scan starts its FFmpeg, so the timings compare with a scan's.
            process = subprocess.Popen(command, cwd=str(folder), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                       stderr=errors, creationflags=raw_bin_library._no_window())
            try:
                for block in iter(lambda: source.read(raw_bin_library.READ_CHUNK_BYTES), b""):
                    process.stdin.write(block)  # type: ignore[union-attr]
                process.stdin.close()  # type: ignore[union-attr]
            except OSError:
                pass   # FFmpeg stopped reading; its exit code and errors.txt say why
            code = process.wait()
        seconds = time.monotonic() - started
        row: dict[str, Any] = {"run": label, "exit_code": code, "seconds": round(seconds, 1),
                               "wav_sha256": {str(o): _sha256(p) for o, p in wavs.items() if p.is_file()}}
        if picture and code == 0:
            sample_times, _frames = frame_render.read_picture_samples(frames, times)
            gaps = [b - a for a, b in zip(sorted(sample_times), sorted(sample_times)[1:])]
            row.update({"samples": len(sample_times), "region": region,
                        "keyframe_spacing_seconds": round(statistics.median(gaps), 3) if gaps else None,
                        "widest_gap_seconds": round(max(gaps), 3) if gaps else None})
        shutil.rmtree(folder, ignore_errors=True)
        runs.append(row)
    extra = round(runs[1]["seconds"] - runs[0]["seconds"], 1)
    same = runs[0]["wav_sha256"] == runs[1]["wav_sha256"] and bool(runs[0]["wav_sha256"])
    result = {"recording_bytes": recording.stat().st_size, "duration": duration, "tracks": len(streams), "runs": runs,
              "extra_seconds": extra, "wavs_identical": same}
    lines = ["## Raw bin read path: sound alone against sound plus the game picture", "",
             f"- Sound only: {runs[0]['seconds']} s (exit {runs[0]['exit_code']}). With the game picture: "
             f"{runs[1]['seconds']} s (exit {runs[1]['exit_code']}): {extra:+} s for {_clock(duration)} of recording.",
             f"- Keyframes found {runs[1].get('keyframe_spacing_seconds')} s apart (widest gap "
             f"{runs[1].get('widest_gap_seconds')} s), {runs[1].get('samples')} samples of the {region}.",
             f"- The sound files of the two runs are {'identical' if same else 'NOT identical'}."]
    return _finish(args, "rawbin-spike", result, lines, 0 if all(row["exit_code"] == 0 for row in runs) else 1)


# Command line ----------------------------------------------------------------------------------

_TESTS_ONLY = "a backend source folder instead of the build's (the tool's own tests)"
_TRACK_HELP = "a track picked by hand, as on the page: Track 1 is 1; 0 (the default) is Auto"
# Each step's own arguments: (name, options); a name ending in "!" is required, "?" is a switch.
STEPS: dict[str, list[tuple[str, dict[str, Any]]]] = {
    "environment": [("--work!", {}), ("--settings!", {}), ("--recordings-folder!", {})],
    "listing": [("--folder!", {}), ("--out!", {})],
    "compare": [("--before!", {}), ("--after!", {})],
    "smoke": [("--dist!", {}), ("--clip!", {}), ("--work!", {}), ("--backend-src", {"default": "", "help": _TESTS_ONLY}),
              ("--dry-run?", {"help": "build every command and write it; run nothing"})],
    "editor": [("--dist", {}), ("--backend-src", {"default": "", "help": _TESTS_ONLY}), ("--recording!", {}),
               ("--work!", {}), ("--copy-name", {"default": ""}), ("--scripted-minutes", {"type": float, "default": 2.0}),
               ("--qualities", {"default": ",".join(QUALITY_NAMES)}), ("--validation-size", {"default": ""}),
               ("--fps-copies?", {}), ("--fps-copy-seconds", {"type": float, "default": 60.0}), ("--skip-transcript?", {}),
               ("--poll-seconds", {"type": float, "default": 0.1, "help": "how often new FFmpeg runs are looked for"}),
               ("--voice-track", {"type": int, "default": 0, "help": _TRACK_HELP}),
               ("--game-track", {"type": int, "default": 0, "help": _TRACK_HELP}),
               ("--compare-quick-models?", {"help": "prepare again with the quick passes on the main Whisper model"})],
    "compare-analysis": [("--baseline-src!", {"help": "the src folder of `git archive 9e065e4 src`"}),
                         ("--recording!", {}), ("--work!", {}), ("--dist", {}),
                         ("--backend-src", {"default": "", "help": _TESTS_ONLY}),
                         ("--voice-track", {"type": int, "default": 0, "help": _TRACK_HELP}),
                         ("--game-track", {"type": int, "default": 0, "help": _TRACK_HELP}),
                         ("--baseline-label", {"default": "9e065e4"})],
    "dead-time-frames": [("--project!", {}), ("--recording!", {}), ("--out!", {}), ("--work", {"default": ""})],
    "rawbin-spike": [("--recording!", {}), ("--work!", {})],
}


def main(argv: list[str] | None = None) -> int:
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--report", help="markdown file the plain-English lines are added to")
    shared.add_argument("--json", help="where the JSON result goes (default <work>/results/<step>.json)")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    steps = parser.add_subparsers(dest="step", required=True)
    for step, options in STEPS.items():
        sub = steps.add_parser(step, parents=[shared])
        for name, extra in options:
            if name.endswith("?"):
                sub.add_argument(name[:-1], action="store_true", **extra)
            else:
                sub.add_argument(name.rstrip("!"), required=name.endswith("!"), **extra)
    args = parser.parse_args(argv)
    if args.step == "editor" and not (args.dist or args.backend_src):
        parser.error("editor needs --dist or --backend-src")
    handlers = {"environment": environment, "listing": listing, "compare": compare, "smoke": smoke, "editor": editor,
                "compare-analysis": compare_analysis, "dead-time-frames": dead_time_frames, "rawbin-spike": rawbin_spike}
    try:
        return handlers[args.step](args)
    except StepFailed as exc:
        return _stopped(args, exc)
    except Exception as exc:  # noqa: BLE001 - every stop is reported, with its result file, as exit 2
        print(traceback.format_exc(), file=sys.stderr, flush=True)
        return _stopped(args, exc, traceback.format_exc())


def _stopped(args: argparse.Namespace, exc: Exception, trace: str = "") -> int:
    """A step that stopped: exit 2, the reason in the report and in the step's result file. A refusal to
    use a folder writes no result file, since that would go into the folder refused."""

    reason = str(exc) if isinstance(exc, StepFailed) else f"{type(exc).__name__}: {exc}"
    lines = [f"## {args.step}", "", f"- STOPPED{' (unexpected)' if trace else ''}: {reason}"]
    if isinstance(exc, Refused):
        _report(args.report, lines)
        return 2
    result = {"failed": reason, **({"unexpected": True, "traceback": trace} if trace else {})}
    try:
        return _finish(args, args.step, result, lines, 2)
    except OSError:
        _report(args.report, lines)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
