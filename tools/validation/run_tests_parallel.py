"""Run the whole test suite as several pytest processes side by side (167).

Every collected test runs exactly once. Tests are kept together by class (or by file, for tests
outside a class) so a class's set-up runs once per process; a class with many tests is cut into
consecutive slices so no single process is left holding the longest file. Each process writes its
own log; the summary says how many tests passed and failed in total and whether every process ended
cleanly. Exit code 0 only when every process passed.

Usage, from the repository root:

    AREA51\\TEMP\\workbench-build\\python-3.12.10-embed-amd64\\python.exe tools\\validation\\run_tests_parallel.py

Options: --processes N (default: up to 6), --python PATH (default: this Python), --out FOLDER
(default: AREA51\\TEMP\\test-runs\\<time>), and any test paths to limit the run (default: tests).
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
from datetime import datetime
import os
from pathlib import Path
import re
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[2]
SLICE_ABOVE = 40   # a class with more tests than this is cut into slices


def group_key(node_id: str) -> str:
    """The unit kept together: ``file::Class`` for tests in a class, the file otherwise."""

    parts = node_id.split("::")
    return "::".join(parts[:2]) if len(parts) > 2 else parts[0]


def plan_buckets(node_ids: list[str], processes: int, slice_above: int = SLICE_ABOVE) -> list[list[str]]:
    """Share the tests out so each process gets about the same number, keeping classes together."""

    groups: "OrderedDict[str, list[str]]" = OrderedDict()
    for node in node_ids:
        groups.setdefault(group_key(node), []).append(node)
    units: list[list[str]] = []
    for members in groups.values():
        if len(members) > slice_above and processes > 1:
            size = -(-len(members) // processes)
            units.extend(members[i:i + size] for i in range(0, len(members), size))
        else:
            units.append(members)
    buckets: list[list[str]] = [[] for _ in range(max(1, processes))]
    for unit in sorted(units, key=len, reverse=True):
        min(buckets, key=len).extend(unit)
    return [bucket for bucket in buckets if bucket]


def collect(python: str, targets: list[str], env: dict[str, str]) -> list[str]:
    result = subprocess.run([python, "-m", "pytest", *targets, "--collect-only", "-q", "-p", "no:cacheprovider",
                             "-o", "pythonpath=."], cwd=REPO, env=env, capture_output=True, text=True)
    nodes = [line.strip() for line in result.stdout.splitlines() if "::" in line and not line.startswith(" ")]
    if result.returncode != 0 or not nodes:
        sys.exit(f"Collecting the tests failed:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
    return nodes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("targets", nargs="*", default=["tests"])
    parser.add_argument("--processes", type=int, default=min(6, os.cpu_count() or 1))
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)

    out = Path(args.out) if args.out else REPO / "AREA51" / "TEMP" / "test-runs" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    nodes = collect(args.python, args.targets, env)
    buckets = plan_buckets(nodes, args.processes)
    print(f"{len(nodes)} tests in {len(buckets)} processes; logs in {out}", flush=True)

    started = time.monotonic()
    running = []
    for number, bucket in enumerate(buckets):
        listing = out / f"process-{number}.txt"
        listing.write_text("\n".join(bucket) + "\n", encoding="utf-8")
        log = open(out / f"process-{number}.log", "w", encoding="utf-8")
        command = [args.python, "-u", "-m", "pytest", f"@{listing}", "-q", "-p", "no:cacheprovider", "-o", "pythonpath=."]
        running.append((number, len(bucket), subprocess.Popen(command, cwd=REPO, env=env, stdout=log,
                                                              stderr=subprocess.STDOUT), log))

    passed = failed = 0
    clean = True
    for number, size, process, log in running:
        code = process.wait()
        log.close()
        text = (out / f"process-{number}.log").read_text(encoding="utf-8", errors="replace")
        summaries = [line for line in text.splitlines() if re.search(r"\d+ (passed|failed|error)", line)]
        last = summaries[-1].strip("= ") if summaries else "(no summary line)"
        counted = re.sub(r"\d+ subtests? \w+", "", last)
        passed += sum(int(n) for n in re.findall(r"(\d+) passed", counted))
        failed += sum(int(n) for n in re.findall(r"(\d+) (?:failed|errors?)", counted))
        clean = clean and code == 0
        minutes = round((time.monotonic() - started) / 60, 1)
        print(f"process {number}: {size} tests, exit {code}, {last} (done after {minutes} min)", flush=True)
    minutes = round((time.monotonic() - started) / 60, 1)
    verdict = "PASSED" if clean and failed == 0 and passed >= len(nodes) else "FAILED"
    print(f"{verdict}: {passed} of {len(nodes)} tests passed, {failed} failed, in {minutes} min", flush=True)
    return 0 if verdict == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
