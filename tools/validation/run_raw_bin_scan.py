"""Headless runs of the raw bin library scan for the Wave 6 acceptance test (220).

Runs the scan through the packaged build's backend, at low priority and with no window, and writes a
plain report the operator can read. Every folder is an argument: nothing here names a real folder.

    run_raw_bin_scan.py snapshot <root> <out.csv>
        Every file and folder under <root>, hidden ones too: path, size, modified time.
    run_raw_bin_scan.py compare <before.csv> <after.csv>
        Exit code 1 and a list when anything was added, removed or changed.
    run_raw_bin_scan.py estimate --folder <recordings folder> --report <report.md> [--files 3]
        Scans a few recordings of different sizes into the library and writes how long the whole
        folder will take, and when it would finish if started now.
    run_raw_bin_scan.py scan --folder <recordings folder> --report <report.md> [--interrupt-after N]
        The full scan. With --interrupt-after, after N recordings it is paused, then stopped hard (as a
        power cut would), then started again, and the report says what was kept and what was redone.
    run_raw_bin_scan.py summary --report <report.md>
        Counts per guess, the idle share, 15 rows to check, and the measured speed.

The packaged backend (``dist\\VideoManglerWorkbench\\python-core\\src``) and the Python, FFmpeg and
Whisper settings come from the Workbench's own settings file, as the app itself would use them.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from typing import Any

REPO = Path(__file__).resolve().parents[2]
DIST_SRC = REPO / "dist" / "VideoManglerWorkbench" / "python-core" / "src"
BELOW_NORMAL = 0x00004000
NO_WINDOW = 0x08000000


def _settings() -> dict[str, Any]:
    path = Path(os.environ.get("APPDATA", "")) / "MediaManglers" / "workbench" / "settings.json"
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")).get("settings") or {})
    except (OSError, ValueError):
        return {}


def _report(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text.rstrip() + "\n")
    print(text, flush=True)


def _library_root() -> Path:
    override = os.environ.get("MEDIA_MANGLERS_LIBRARY_ROOT", "").strip()
    if override:
        return Path(override)
    return Path(os.environ.get("LOCALAPPDATA", "")) / "MediaManglers" / "Workbench" / "library"


# Snapshots ---------------------------------------------------------------------------------------


def snapshot(root: Path, out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["path", "kind", "size", "modified_ns"])
        for folder, folders, files in os.walk(root, onerror=lambda error: None):
            for name in sorted(folders):
                path = Path(folder) / name
                try:
                    stat = path.stat()
                except OSError:
                    continue
                writer.writerow([str(path), "folder", 0, stat.st_mtime_ns])
                count += 1
            for name in sorted(files):
                path = Path(folder) / name
                try:
                    stat = path.stat()
                except OSError:
                    continue
                writer.writerow([str(path), "file", stat.st_size, stat.st_mtime_ns])
                count += 1
    print(f"{count} entries written to {out}")
    return 0


def compare(before: Path, after: Path) -> int:
    def read(path: Path) -> dict[str, tuple[str, str, str]]:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return {row["path"]: (row["kind"], row["size"], row["modified_ns"]) for row in csv.DictReader(handle)}

    old, new = read(before), read(after)
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(path for path in set(old) & set(new) if old[path] != new[path])
    print(f"before {len(old)}, after {len(new)}: {len(added)} added, {len(removed)} removed, {len(changed)} changed")
    for label, items in (("ADDED", added), ("REMOVED", removed), ("CHANGED", changed)):
        for item in items[:50]:
            print(f"{label} {item}")
    return 1 if added or removed or changed else 0


# Running the scan --------------------------------------------------------------------------------


def _payload(folder: Path, settings: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "folders": [str(folder)],
        "ffmpeg": str(settings.get("dependency_ffmpeg_path") or "ffmpeg"),
        "ffprobe": str(settings.get("dependency_ffprobe_path") or "ffprobe"),
        "model_name": str(settings.get("whisper_model") or "medium"),
        "prefer_gpu": str(settings.get("whisper_device") or "Auto") != "CPU",
        "language": str(settings.get("language") or "en"),
        "track_roles": str(settings.get("evidence_track_roles") or ""),
        "cache_folder": str(settings.get("cache_folder") or ""),
        "cache_cap_bytes": int(settings.get("cache_size_gb") or 10) * 1024 ** 3,
        **extra,
    }


def _start(payload: dict[str, Any], run_folder: Path, settings: dict[str, Any]) -> tuple[subprocess.Popen, Path]:
    run_folder.mkdir(parents=True, exist_ok=True)
    request, result = run_folder / "request.json", run_folder / "result.json"
    request.write_text(json.dumps({"payload": payload}, indent=2), encoding="utf-8")
    python = str(settings.get("dependency_python_path") or sys.executable)
    source = str(DIST_SRC if DIST_SRC.is_dir() else REPO / "src")
    bootstrap = (f"import sys; sys.path.insert(0, {source!r}); "
                 "from media_manglers.cli import main; raise SystemExit(main(sys.argv[1:]))")
    process = subprocess.Popen(
        [python, "-c", bootstrap, "raw-bin-scan", "--request-file", str(request), "--result-file", str(result)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        creationflags=BELOW_NORMAL | NO_WINDOW,
    )
    return process, result


def _kill_tree(process: subprocess.Popen) -> None:
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True, check=False,
                   creationflags=NO_WINDOW)
    process.wait(timeout=60)


def _follow(process: subprocess.Popen, report: Path, *, stop_after: int | None = None,
            control: Path | None = None) -> dict[str, Any]:
    """Read the scan's lines; every 10 recordings a progress line goes into the report."""

    done = 0
    for line in process.stdout:  # type: ignore[union-attr]
        line = line.rstrip()
        if not line.startswith("Scanned "):
            continue
        done += 1
        print(line, flush=True)
        if done % 10 == 0:
            _report(report, f"- {datetime.now():%Y-%m-%d %H:%M} {line}")
        if stop_after is not None and done >= stop_after:
            if control is not None:
                control.write_text(json.dumps({"pause": True, "skip": []}), encoding="utf-8")
                _report(report, f"- {datetime.now():%H:%M:%S} Paused after {done} recordings.")
                time.sleep(20)
                control.write_text(json.dumps({"pause": False, "skip": []}), encoding="utf-8")
                _report(report, f"- {datetime.now():%H:%M:%S} Resumed.")
            # Let the next recording start, then cut the power on it.
            time.sleep(15)
            _kill_tree(process)
            _report(report, f"- {datetime.now():%H:%M:%S} Stopped hard during recording {done + 1}.")
            return {"interrupted_after": done}
    process.wait()
    return {"completed": done}


def _rows(root: Path) -> list[dict[str, Any]]:
    database = root / "raw-bin-library.sqlite"
    if not database.is_file():
        return []
    connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute(
            "SELECT r.*, l.path AS path FROM recordings r LEFT JOIN locations l ON l.recording_id = r.recording_id "
            "AND l.is_current = 1 ORDER BY r.recording_id")]
    finally:
        connection.close()


def estimate(folder: Path, report: Path, files: int) -> int:
    settings = _settings()
    candidates = sorted((path for path in folder.rglob("*") if path.is_file()
                         and path.suffix.lower() in {".mkv", ".mov", ".mp4"}), key=lambda item: item.stat().st_size)
    if not candidates:
        _report(report, "No recordings found to measure.")
        return 1
    known = {Path(str(row["path"])) for row in _rows(_library_root()) if row.get("path")}
    fresh = [path for path in candidates if path not in known] or candidates
    picks = sorted({fresh[0], fresh[len(fresh) // 2], fresh[-1]} if len(fresh) >= 3 else set(fresh),
                   key=lambda item: item.stat().st_size)[:files]
    run = _library_root() / "runs" / f"{datetime.now():%Y%m%d-%H%M%S}-estimate"
    started = time.monotonic()
    process, result = _start(_payload(folder, settings, only_paths=[str(path) for path in picks]), run, settings)
    _follow(process, report)
    seconds = time.monotonic() - started
    data = json.loads(result.read_text(encoding="utf-8")).get("data") or {}
    measured_bytes = int(data.get("bytes_read") or 0)
    total_bytes = sum(path.stat().st_size for path in candidates)
    rate = measured_bytes / seconds if seconds > 0 and measured_bytes else 0
    remaining = max(0, total_bytes - measured_bytes)
    eta = remaining / rate if rate else 0
    finish = datetime.now() + timedelta(seconds=eta)
    _report(report, "\n".join([
        "## Estimate before the full scan",
        "",
        f"- Measured {len(picks)} recordings ({measured_bytes / 1024 ** 3:.1f} GB) in {seconds / 60:.1f} minutes: "
        f"{rate / 1024 ** 2:.0f} MB/s.",
        f"- Whole folder: {len(candidates)} recordings, {total_bytes / 1024 ** 4:.2f} TB.",
        f"- Estimated time for the rest: {eta / 3600:.1f} hours. If started now it would finish about "
        f"{finish:%Y-%m-%d %H:%M}.",
        f"- {'Over 2 hours: run it overnight.' if eta > 7200 else 'Under 2 hours: it can run now.'}",
        "",
    ]))
    return 0


def scan(folder: Path, report: Path, interrupt_after: int | None) -> int:
    settings = _settings()
    root = _library_root()
    _report(report, f"## Full scan, started {datetime.now():%Y-%m-%d %H:%M}\n")
    started = time.monotonic()
    before = len(_rows(root))
    if interrupt_after:
        run = root / "runs" / f"{datetime.now():%Y%m%d-%H%M%S}-scan-interrupted"
        control = run / "run-control.json"
        run.mkdir(parents=True, exist_ok=True)
        control.write_text(json.dumps({"pause": False, "skip": []}), encoding="utf-8")
        process, _result = _start(_payload(folder, settings, run_control_path=str(control)), run, settings)
        outcome = _follow(process, report, stop_after=interrupt_after, control=control)
        kept = len(_rows(root)) - before
        _report(report, f"- After the hard stop the library kept {kept} new recordings "
                        f"({outcome.get('interrupted_after')} finished before the stop).")
    run = root / "runs" / f"{datetime.now():%Y%m%d-%H%M%S}-scan"
    process, result = _start(_payload(folder, settings), run, settings)
    _follow(process, report)
    seconds = time.monotonic() - started
    try:
        data = json.loads(result.read_text(encoding="utf-8")).get("data") or {}
    except (OSError, ValueError):
        data = {}
    _report(report, "\n".join([
        "",
        f"- Scan status: {data.get('status', 'unknown')}. Read {data.get('files_read', 0)} recordings, "
        f"{data.get('unchanged', 0)} unchanged (not read again), {data.get('failed', 0)} could not be read, "
        f"{data.get('in_use', 0)} still being written.",
        f"- Wall time: {seconds / 3600:.2f} hours.",
        "",
    ]))
    return 0 if data.get("status") == "completed" else 1


def summary(report: Path) -> int:
    rows = [row for row in _rows(_library_root()) if row.get("path")]
    if not rows:
        _report(report, "The library is empty.")
        return 1
    names = {"keep_likely": "Keep likely", "check": "Check", "probably_nothing": "Probably nothing", "empty": "Empty"}
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row.get("guess"))] = counts.get(str(row.get("guess")), 0) + 1
    seconds = sum(float(row.get("duration_seconds") or 0) for row in rows)
    idle = sum(float(row.get("idle_seconds") or 0) for row in rows if row.get("idle_status") == "measured")
    measured = sum(float(row.get("duration_seconds") or 0) for row in rows if row.get("idle_status") == "measured")
    read = [row for row in rows if int(row.get("bytes_read") or 0) > 0]
    once = sum(1 for row in read if int(row["bytes_read"]) == int(row["size_bytes"]))
    lines = ["## Summary", "", "| Guess | Recordings |", "|---|---|"]
    lines += [f"| {names.get(key, key)} | {value} |" for key, value in sorted(counts.items())]
    lines += ["", f"- Video in the library: {seconds / 3600:.1f} hours.",
              f"- Idle share where the game track was found: {idle / measured:.0%}." if measured else
              "- Idle share: no game-audio track found in any recording.",
              f"- Read exactly once (bytes read = file size): {once} of {len(read)} recordings read in this scan.",
              "", "### 15 recordings to check", "",
              "| Guess | Recording | Speech (min) | Idle | Idle stretches (min) | Why |", "|---|---|---|---|---|---|"]
    for guess in ("keep_likely", "probably_nothing", "check"):
        for row in [item for item in rows if item.get("guess") == guess][:5]:
            stretches = json.loads(row.get("idle_stretches_json") or "[]")
            spans = ", ".join(f"{int(a) // 60}-{int(b) // 60}" for a, b in stretches[:4])
            share = "" if row.get("idle_share") is None else f"{float(row['idle_share']):.0%}"
            lines.append(f"| {names[guess]} | {Path(str(row['path'])).name} | "
                         f"{float(row.get('speech_seconds') or 0) / 60:.1f} | {share} | {spans} | "
                         f"{str(row.get('guess_reason') or '')[:90]} |")
    _report(report, "\n".join(lines) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    one = commands.add_parser("snapshot")
    one.add_argument("root")
    one.add_argument("out")
    two = commands.add_parser("compare")
    two.add_argument("before")
    two.add_argument("after")
    three = commands.add_parser("estimate")
    three.add_argument("--folder", required=True)
    three.add_argument("--report", required=True)
    three.add_argument("--files", type=int, default=3)
    four = commands.add_parser("scan")
    four.add_argument("--folder", required=True)
    four.add_argument("--report", required=True)
    four.add_argument("--interrupt-after", type=int, default=0)
    five = commands.add_parser("summary")
    five.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    if args.command == "snapshot":
        return snapshot(Path(args.root), Path(args.out))
    if args.command == "compare":
        return compare(Path(args.before), Path(args.after))
    if args.command == "estimate":
        return estimate(Path(args.folder), Path(args.report), args.files)
    if args.command == "scan":
        return scan(Path(args.folder), Path(args.report), args.interrupt_after or None)
    return summary(Path(args.report))


if __name__ == "__main__":
    raise SystemExit(main())
