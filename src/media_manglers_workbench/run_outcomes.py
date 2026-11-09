"""Each recording's outcome in a run, read from what the feature itself reported (243).

The library keeps every run with each recording's outcome, and each feature writes its own when it knows
it. For New Review that is what the backend reported while it ran (its per-recording progress lines) and
what the run's own files say once it ended: Transcript Only's manifest, a ticket package's manifest. A
file is only believed when this run wrote it (modified after the run started), and a recording nothing
reported on stays "not reported": nothing is guessed.

``PROCESSING_SUMMARY.csv`` (Full Review) is not read: the backend appends to it run after run in the same
output folder, so a row cannot be tied to this run. Full Review's per-recording progress lines are.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from media_manglers.core.recording_records import (
    OUTCOME_CANCELLED,
    OUTCOME_COMPLETED,
    OUTCOME_FAILED,
    OUTCOME_NO_NARRATION,
    OUTCOME_NOT_REPORTED,
    OUTCOME_SKIPPED,
    path_key,
)

# The Progress page's item states the backend reported itself; anything else was assumed at the end.
REPORTED_STATES = {
    "completed": OUTCOME_COMPLETED,
    "failed": OUTCOME_FAILED,
    "skipped": OUTCOME_SKIPPED,
    "cancelled": OUTCOME_CANCELLED,
    "no_narration": OUTCOME_NO_NARRATION,
}
SKIPPED_BY_YOU = "Skipped by you."


def _written_since(path: Path, since: float) -> bool:
    try:
        return path.is_file() and path.stat().st_mtime >= since - 1.0
    except OSError:
        return False


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def transcript_only_outcomes(output_folder: str | Path, since: float) -> dict[str, tuple[str, str]]:
    """Transcript Only's own word on each recording, from this run's ``transcript_manifest.json``:
    {path key: (outcome, reason)}."""

    manifest = Path(output_folder) / "transcript-only" / "transcript_manifest.json"
    if not str(output_folder or "").strip() or not _written_since(manifest, since):
        return {}
    entries = _read_json(manifest)
    found: dict[str, tuple[str, str]] = {}
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or not entry.get("source_path"):
            continue
        status = str(entry.get("status") or "").strip().lower()
        message = str(entry.get("error_message") or "").strip()
        if status == "completed":
            outcome, reason = OUTCOME_COMPLETED, ""
        elif status == "failed":
            outcome, reason = OUTCOME_FAILED, message
        elif status == "skipped" and message == SKIPPED_BY_YOU:
            outcome, reason = OUTCOME_SKIPPED, SKIPPED_BY_YOU
        elif status == "skipped":
            outcome, reason = OUTCOME_COMPLETED, "Its transcript was already there."
        else:
            continue
        found[path_key(str(entry["source_path"]))] = (outcome, reason)
    return found


def package_outcomes(package_root: str | Path | None, since: float) -> dict[str, tuple[str, str]]:
    """A ticket package's own word on each recording, from this run's ``manifest.json``:
    {path key: (outcome, reason)}. The same words Find my bug reports reads (196: no narration is a
    correct result)."""

    if not package_root:
        return {}
    manifest = Path(package_root) / "manifest.json"
    if not _written_since(manifest, since):
        return {}
    data = _read_json(manifest)
    found: dict[str, tuple[str, str]] = {}
    for source in (data.get("sources") or []) if isinstance(data, dict) else []:
        if not isinstance(source, dict) or not source.get("source_path"):
            continue
        status = str(source.get("status") or "").strip().lower()
        quality = str((source.get("transcript_quality") or {}).get("quality_status") or "")
        if status == "no_narration" or (status in {"completed", "skipped"} and quality == "no_narration_found"):
            outcome, reason = OUTCOME_NO_NARRATION, ""
        elif status in {"completed", "skipped"}:
            outcome, reason = OUTCOME_COMPLETED, ""
        elif status == "operator_skipped":
            outcome, reason = OUTCOME_SKIPPED, SKIPPED_BY_YOU
        elif status in {"failed", "quality_blocked"}:
            outcome, reason = OUTCOME_FAILED, str(source.get("error") or status)
        else:
            continue
        found[path_key(str(source["source_path"]))] = (outcome, reason)
    return found


def wizard_outcomes(items: list[str], reported: dict[str, str], final: dict[str, str],
                    from_files: dict[str, tuple[str, str]]) -> list[dict[str, str]]:
    """One outcome per queue item of a New Review run. ``reported`` are the item states the backend sent
    before the run ended, ``final`` the states after the Workbench closed the queue (a recording the run
    never reached is Cancelled then), ``from_files`` what the run's own files say."""

    outcomes: list[dict[str, str]] = []
    for item in items:
        before = str(reported.get(item) or "")
        key = path_key(item) if "://" not in item else item
        if before in REPORTED_STATES:
            outcome, reason, by = REPORTED_STATES[before], "", "progress lines"
        elif key in from_files:
            (outcome, reason), by = from_files[key], "run files"
        elif final.get(item) == "cancelled":
            outcome, reason, by = OUTCOME_CANCELLED, "The run stopped before it reached this one.", "run end"
        else:
            outcome, reason, by = OUTCOME_NOT_REPORTED, "", "run end"
        outcomes.append({"item": item, "outcome": outcome, "reason": reason, "reported_by": by})
    return outcomes
