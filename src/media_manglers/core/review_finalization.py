"""Crash-safe finalization, retention, and recovery for Review Media Inbox."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Callable
import uuid

from . import inbox_records, review_ledger, review_results, review_targeted_evidence, safe_write


PLAN_VERSION = 1
JOURNAL_VERSION = 1
FINALIZATION_VERSION = 1
JOURNAL_PHASES = {
    "planned",
    "quarantined",
    "history_staged",
    "history_promoted",
    "ledger_committed",
    "cleanup_complete",
}
DISPOSABLE_PREFIXES = {"visuals", "targeted-evidence", "hints"}


class FinalizationError(RuntimeError):
    """Raised when finalization cannot continue without risking retained data."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_sha(payload: dict[str, Any]) -> str:
    return review_results._canonical_sha(payload)


def _within(root: Path, target: Path) -> bool:
    root_resolved = root.resolve()
    target_resolved = target.resolve()
    return target_resolved == root_resolved or root_resolved in target_resolved.parents


def _require_within(root: Path, target: Path, label: str) -> None:
    if not _within(root, target):
        raise FinalizationError(f"{label} must remain beneath its approved root.")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    # 224 (Wave B1): the one safe writer replaces the file, with this module's text as before (written as
    # text, so lines end the way this system ends them).
    safe_write.write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                          wait=safe_write.INBOX_WAIT_SECONDS)


def _replace(source: Path, destination: Path) -> None:
    # 224 (Wave B2a): the one antivirus-safe move, in place of this module's own short loop. It waits up to ten
    # seconds for another program holding the file, never for the app itself, and never writes over anything.
    destination.parent.mkdir(parents=True, exist_ok=True)
    safe_write.move(source, destination)


def _tidy(plan: dict[str, Any], payload: dict[str, Any], root: Path, target: Path, warnings: list[str]) -> None:
    """Clean-up after a step already succeeded (224, Decision 3): another program still holding the copy never
    undoes the result. It is said in plain words, and the next Inbox run removes the leftover."""

    try:
        safe_write.remove_disposable_tree(target, within=root,
                                          leftovers=inbox_records.leftovers_file(Path(str(plan["ledger_path"]))))
    except (safe_write.FileInUse, safe_write.FileStepRefused) as exc:
        # 224 (Wave B2a review): whatever Windows refuses here, the step's result stands; the leftover is noted.
        warning = f"The result was kept. {exc} It is removed at the next run."
        warnings.append(warning)
        _progress(payload, "cleanup", None, warning)


def _progress(payload: dict[str, Any], stage: str, source: dict[str, Any] | None = None, detail: str = "") -> None:
    callback = payload.get("progress_callback")
    if callable(callback):
        callback(
            {
                "stage": stage,
                "source_identity": "" if source is None else str(source.get("source_identity") or ""),
                "source_token": "" if source is None else str(source.get("source_token") or ""),
                "history_destination": "" if source is None else str(source.get("history_destination") or ""),
                "detail": detail,
            }
        )


def _source_state(dispositions: set[str]) -> str:
    if "review_failure" in dispositions:
        return "retryable_failure"
    if "uncertain_manual_review" in dispositions:
        return "needs_manual_review"
    if dispositions == {"no_actionable_findings"}:
        return "finalized_no_findings"
    return "finalized_with_findings"


def _batch_state(source_states: list[str]) -> str:
    if any(state == "retryable_failure" for state in source_states):
        return "retryable_failure"
    if any(state == "needs_manual_review" for state in source_states):
        return "needs_manual_review"
    if all(state in {"finalized_no_findings", "finalized_with_findings"} for state in source_states):
        return "finalized_with_findings" if "finalized_with_findings" in source_states else "finalized_no_findings"
    return "retryable_failure"


def _source_results(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["source_identity"]): item for item in document.get("source_results") or []}


def _enumerate_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*"), key=lambda item: str(item).casefold()):
        if path.is_symlink():
            raise FinalizationError(f"Symbolic links are not permitted in finalization inputs: {path.name}.")
        if path.is_file():
            _require_within(root, path, "Finalization input")
            files.append(path)
    return files


def _file_record(path: Path, relative: str, destination: str = "") -> dict[str, Any]:
    return {
        "batch_relative_path": relative,
        "history_relative_path": destination,
        "size_bytes": path.stat().st_size,
        "sha256": review_ledger.sha256_file(path),
    }


def _review_records(
    batch_root: Path,
    preliminary_sha: str,
    results_sha: str,
) -> list[tuple[Path, str]]:
    preliminary_root = batch_root / "imports" / "preliminary-findings" / preliminary_sha[:24]
    results_root = batch_root / "imports" / "review-results" / results_sha[:24]
    candidates = [
        (preliminary_root / "preliminary-findings.json", "review/preliminary-findings.json"),
        (preliminary_root / "validation.json", "review/preliminary-validation.json"),
        (results_root / "review-results.json", "review/review-results.json"),
        (results_root / "validation.json", "review/final-results-validation.json"),
        (batch_root / "batch-manifest.json", "review/batch-manifest.json"),
        (batch_root / "README_FOR_REVIEW.md", "review/README_FOR_REVIEW.md"),
        (batch_root / "CODEX_REVIEW_PROMPT.md", "review/CODEX_REVIEW_PROMPT.md"),
    ]
    missing = [str(path.name) for path, _destination in candidates if not path.is_file()]
    if missing:
        raise FinalizationError("Required retained review records are missing: " + ", ".join(missing) + ".")
    return candidates


def _read_ledger(ledger_path: Path) -> sqlite3.Connection:
    """The ledger opened for reading only (224, F4): one that is not there is an error here, never made."""

    connection = inbox_records.connect_read_only(ledger_path)
    if connection is None:
        raise FinalizationError("The configured Review Media Inbox ledger does not exist.")
    return connection


def _original_locations(ledger_path: Path, batch_id: str) -> list[Path]:
    connection = _read_ledger(ledger_path)
    try:
        rows = connection.execute(
            """
            SELECT sl.original_path FROM inbox_source_locations sl
            JOIN inbox_batch_sources bs ON bs.source_id = sl.source_id
            WHERE bs.batch_id = ?
            """,
            (batch_id,),
        ).fetchall()
    finally:
        connection.close()
    return [Path(str(row[0])) for row in rows if str(row[0] or "")]


def _assert_not_original(target: Path, originals: list[Path]) -> None:
    target_resolved = target.resolve()
    for original in originals:
        original_resolved = original.resolve()
        if target_resolved == original_resolved or target_resolved in original_resolved.parents:
            raise FinalizationError("A cleanup action resolves to an original source location or its parent.")


def preview_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a deterministic, immutable operator-readable finalization plan."""

    retention_policy = str(payload.get("retention_policy") or "compact").strip().lower()
    if retention_policy not in {"compact", "keep_generated"}:
        raise ValueError("retention_policy must be compact or keep_generated.")
    ledger_path = Path(str(payload.get("ledger_path") or ""))
    batch_id = str(payload.get("expected_batch_id") or payload.get("batch_id") or "")
    supplied_batch = str(payload.get("batch_path") or "")
    if not batch_id:
        raise ValueError("expected_batch_id is required.")
    batch_root = review_targeted_evidence._resolve_batch_root(ledger_path, batch_id, supplied_batch)
    connection = _read_ledger(ledger_path)
    try:
        batch_state = str(connection.execute("SELECT status FROM inbox_batches WHERE batch_id = ?", (batch_id,)).fetchone()[0])
    finally:
        connection.close()
    if batch_state != "results_received":
        raise FinalizationError("A new finalization preview requires a completely validated results_received batch.")
    try:
        results_sha, document, basis, _submission, validation_path = review_results.load_accepted_results(
            ledger_path, batch_root, batch_id, str(payload.get("results_submission_sha256") or "")
        )
    except review_results.FinalResultsError as exc:
        raise FinalizationError(str(exc)) from exc
    preliminary_sha = str(basis["preliminary_submission_sha256"])
    inbox_root = inbox_records.workspace(ledger_path)
    history_root = inbox_root / "history" / "sources"
    if history_root.resolve() == inbox_root.resolve() or not _within(inbox_root, history_root):
        raise FinalizationError("Retained history root must be a bounded child of the Review Media Inbox root.")
    originals = _original_locations(ledger_path, batch_id)
    review_records = _review_records(batch_root, preliminary_sha, results_sha)
    result_by_source = _source_results(document)
    source_plans: list[dict[str, Any]] = []
    for identity, source in sorted(basis["sources"].items(), key=lambda item: int(item[1]["source_id"])):
        source_token = str(source["source_token"])
        source_root = batch_root / "sources" / source_token
        _require_within(batch_root / "sources", source_root, "Prepared source package")
        if not source_root.is_dir():
            raise FinalizationError(f"Prepared source package is unavailable for {identity}.")
        final_source_results = result_by_source[identity]
        dispositions = {str(result["disposition"]) for result in final_source_results["results"]}
        resulting_state = _source_state(dispositions)
        retain_complete = retention_policy == "keep_generated" or resulting_state != "finalized_no_findings"
        history_destination = history_root / source_token / batch_id
        _require_within(history_root, history_destination, "Retained source history")
        if history_destination.exists():
            raise FinalizationError(f"Retained history destination already exists for source {source_token}; use recovery instead of a new preview.")
        retain_actions: list[dict[str, Any]] = []
        cleanup_actions: list[dict[str, Any]] = []
        for path in _enumerate_files(source_root):
            relative_to_source = path.relative_to(source_root).as_posix()
            batch_relative = path.relative_to(batch_root).as_posix()
            top = relative_to_source.split("/", 1)[0]
            if not retain_complete and top in DISPOSABLE_PREFIXES:
                _assert_not_original(path, originals)
                cleanup_actions.append(_file_record(path, batch_relative))
            else:
                retain_actions.append(_file_record(path, batch_relative, f"package/{relative_to_source}"))
        for record_path, history_relative in review_records:
            _require_within(batch_root, record_path, "Retained review record")
            retain_actions.append(_file_record(record_path, record_path.relative_to(batch_root).as_posix(), history_relative))
        if resulting_state == "retryable_failure":
            logs_root = batch_root / "logs"
            if logs_root.is_dir():
                for log_path in _enumerate_files(logs_root):
                    retain_actions.append(
                        _file_record(log_path, log_path.relative_to(batch_root).as_posix(), f"logs/{log_path.relative_to(logs_root).as_posix()}")
                    )
        seen_destinations: set[str] = set()
        for action in retain_actions:
            destination = str(action["history_relative_path"])
            if destination in seen_destinations:
                raise FinalizationError(f"Retention plan contains a duplicate history destination: {destination}.")
            seen_destinations.add(destination)
        retained_bytes = sum(int(item["size_bytes"]) for item in retain_actions)
        disposable_bytes = sum(int(item["size_bytes"]) for item in cleanup_actions)
        warnings: list[str] = []
        if resulting_state == "needs_manual_review":
            warnings.append("This source remains available for manual review and is not represented as fully finalized.")
        if resulting_state == "retryable_failure":
            warnings.append("Review failed; no generated evidence is scheduled for destructive cleanup.")
        source_plans.append(
            {
                "source_id": int(source["source_id"]),
                "source_identity": identity,
                "source_token": source_token,
                "dispositions": sorted(dispositions),
                "result_ids": [str(result["result_id"]) for result in final_source_results["results"]],
                "resulting_state": resulting_state,
                "history_destination": str(history_destination),
                "retained_bytes": retained_bytes,
                "disposable_bytes": disposable_bytes,
                "retain_actions": retain_actions,
                "cleanup_actions": cleanup_actions,
                "warnings": warnings,
            }
        )
    source_states = [str(item["resulting_state"]) for item in source_plans]
    plan_without_hash = {
        "plan_version": PLAN_VERSION,
        "finalization_version": FINALIZATION_VERSION,
        "action": "review_media_inbox_finalization",
        "batch_id": batch_id,
        "batch_root": str(batch_root),
        "ledger_path": str(ledger_path),
        "history_root": str(history_root),
        "results_submission_sha256": results_sha,
        "preliminary_submission_sha256": preliminary_sha,
        "targeted_evidence_render_version": int(basis["targeted_evidence_render_version"]),
        "targeted_evidence_identity": str(basis["targeted_evidence_identity"]),
        "accepted_results_validation_sha256": review_ledger.sha256_file(validation_path),
        "resulting_batch_state": _batch_state(source_states),
        "sources": source_plans,
        "retained_bytes": sum(int(item["retained_bytes"]) for item in source_plans),
        "disposable_bytes": sum(int(item["disposable_bytes"]) for item in source_plans),
        "operator_confirmation": {
            "required": True,
            "originals_unchanged": "Original source media will never be changed or deleted.",
            "bounded_cleanup": "Only generated batch files explicitly listed in cleanup_actions may be quarantined and removed.",
            "evidence_retention": "Issue-related and uncertain evidence is retained in durable history.",
            "recovery": "Finalization is journaled and recoverable after interruption.",
        },
    }
    plan_sha = _canonical_sha(plan_without_hash)
    plan = {**plan_without_hash, "plan_sha256": plan_sha}
    finalization_root = batch_root / ".finalization"
    _require_within(batch_root, finalization_root, "Finalization metadata")
    plan_path = finalization_root / f"plan-{plan_sha[:24]}.json"
    if plan_path.exists():
        existing = json.loads(plan_path.read_text(encoding="utf-8"))
        if existing != plan:
            raise FinalizationError("An existing finalization plan path contains different content.")
    else:
        _atomic_json(plan_path, plan)
    return {
        **plan,
        "status": "awaiting_operator_confirmation",
        "plan_path": str(plan_path),
        "preview": [
            {
                "source_identity": item["source_identity"],
                "dispositions": item["dispositions"],
                "resulting_state": item["resulting_state"],
                "retained_file_count": len(item["retain_actions"]),
                "disposable_file_count": len(item["cleanup_actions"]),
                "retained_bytes": item["retained_bytes"],
                "disposable_bytes": item["disposable_bytes"],
                "history_destination": item["history_destination"],
                "warnings": item["warnings"],
            }
            for item in source_plans
        ],
    }


def _load_plan(payload: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    plan_path = Path(str(payload.get("plan_path") or ""))
    expected_sha = str(payload.get("plan_sha256") or "")
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FinalizationError(f"The finalization plan cannot be read: {exc}.") from exc
    if not isinstance(plan, dict) or plan.get("plan_version") != PLAN_VERSION:
        raise FinalizationError("The finalization plan is malformed or uses an unsupported version.")
    recorded_sha = str(plan.get("plan_sha256") or "")
    content = {key: value for key, value in plan.items() if key != "plan_sha256"}
    actual_sha = _canonical_sha(content)
    if recorded_sha != actual_sha or expected_sha and expected_sha != actual_sha:
        raise FinalizationError("The finalization plan SHA-256 does not match its immutable content.")
    batch_root = Path(str(plan.get("batch_root") or ""))
    _require_within(batch_root / ".finalization", plan_path, "Finalization plan")
    return plan_path, plan


def _journal_checksum(journal: dict[str, Any]) -> str:
    return _canonical_sha({key: value for key, value in journal.items() if key != "journal_checksum"})


def _write_journal(path: Path, journal: dict[str, Any]) -> None:
    journal["journal_checksum"] = _journal_checksum(journal)
    _atomic_json(path, journal)


def _load_journal(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        journal = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FinalizationError(f"The finalization journal is corrupted: {exc}.") from exc
    if not isinstance(journal, dict) or journal.get("journal_version") != JOURNAL_VERSION:
        raise FinalizationError("The finalization journal is malformed or uses an unsupported version.")
    if str(journal.get("phase") or "") not in JOURNAL_PHASES:
        raise FinalizationError("The finalization journal contains an unknown recovery phase.")
    if str(journal.get("journal_checksum") or "") != _journal_checksum(journal):
        raise FinalizationError("The finalization journal checksum is invalid; manual review is required.")
    return journal


def _action_source(batch_root: Path, action: dict[str, Any]) -> Path:
    target = batch_root / str(action["batch_relative_path"])
    _require_within(batch_root, target, "Finalization source action")
    return target


def _verify_file(path: Path, action: dict[str, Any], label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise FinalizationError(f"{label} is missing or is not a regular file: {path.name}.")
    if path.stat().st_size != int(action["size_bytes"]) or review_ledger.sha256_file(path) != str(action["sha256"]):
        raise FinalizationError(f"{label} changed after the finalization preview: {path.name}.")


def _quarantine_root(plan: dict[str, Any]) -> Path:
    batch_root = Path(str(plan["batch_root"]))
    root = batch_root / ".finalization" / "quarantine" / str(plan["plan_sha256"])[:24]
    _require_within(batch_root / ".finalization", root, "Finalization quarantine")
    return root


def _quarantine_destination(plan: dict[str, Any], action: dict[str, Any]) -> Path:
    """Use a short content-addressed quarantine name to avoid Windows path limits."""

    quarantine = _quarantine_root(plan)
    relative = str(action["batch_relative_path"])
    suffix = Path(relative).suffix[:16]
    destination = quarantine / f"{review_ledger._sha256_text(relative)[:32]}{suffix}"
    _require_within(quarantine, destination, "Quarantined generated file")
    return destination


def _move_cleanup_to_quarantine(plan: dict[str, Any], payload: dict[str, Any]) -> None:
    batch_root = Path(str(plan["batch_root"]))
    quarantine = _quarantine_root(plan)
    moved = 0
    for source in plan["sources"]:
        _progress(payload, "quarantine", source, "Moving only previewed disposable generated files into recoverable quarantine")
        for action in source["cleanup_actions"]:
            current = _action_source(batch_root, action)
            destination = _quarantine_destination(plan, action)
            if current.exists() and destination.exists():
                raise FinalizationError("A cleanup file exists in both its batch and quarantine locations.")
            if current.exists():
                _verify_file(current, action, "Disposable generated file")
                _replace(current, destination)
                moved += 1
                callback = payload.get("_during_quarantine_movement")
                if moved == 1 and callable(callback):
                    callback(source)
            else:
                _verify_file(destination, action, "Quarantined generated file")


def _history_staging_root(plan: dict[str, Any], source: dict[str, Any]) -> Path:
    history_root = Path(str(plan["history_root"]))
    staging = history_root.parent / ".staging" / str(plan["plan_sha256"])[:24] / str(source["source_token"])
    _require_within(history_root.parent, staging, "Retained-history staging")
    return staging


def _hash_inventory(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in _enumerate_files(root):
        relative = path.relative_to(root).as_posix()
        if relative == "integrity.json":
            continue
        records.append({"path": relative, "size_bytes": path.stat().st_size, "sha256": review_ledger.sha256_file(path)})
    return records


def _verify_history(root: Path, plan_sha: str, source_identity: str) -> str:
    manifest_path = root / "retained-history-manifest.json"
    integrity_path = root / "integrity.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FinalizationError(f"Retained-history integrity cannot be read: {exc}.") from exc
    if str(manifest.get("plan_sha256") or "") != plan_sha or str(manifest.get("source_identity") or "") != source_identity:
        raise FinalizationError("Retained-history manifest contradicts the finalization plan.")
    records = integrity.get("files") if isinstance(integrity, dict) else None
    if integrity.get("complete") is not True or not isinstance(records, list):
        raise FinalizationError("Retained-history integrity inventory is incomplete.")
    recorded: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise FinalizationError("Retained-history integrity contains a malformed record.")
        path = root / str(record["path"])
        _require_within(root, path, "Retained-history artifact")
        key = os.path.normcase(path.resolve().relative_to(root.resolve()).as_posix())
        if key in recorded:
            raise FinalizationError("Retained-history integrity contains duplicate paths.")
        recorded[key] = record
        _verify_file(path, record, "Retained-history artifact")
    actual = {
        os.path.normcase(path.resolve().relative_to(root.resolve()).as_posix())
        for path in _enumerate_files(root)
        if path.resolve().relative_to(root.resolve()).as_posix() != "integrity.json"
    }
    if actual != set(recorded):
        raise FinalizationError("Retained-history actual files do not match the integrity inventory.")
    return review_ledger.sha256_file(integrity_path)


def _prepare_history(plan: dict[str, Any], payload: dict[str, Any]) -> None:
    batch_root = Path(str(plan["batch_root"]))
    copied = 0
    for source in plan["sources"]:
        stage = _history_staging_root(plan, source)
        stage.mkdir(parents=True, exist_ok=True)
        _progress(payload, "history_staging", source, "Preparing and verifying retained history")
        for action in source["retain_actions"]:
            current = _action_source(batch_root, action)
            destination = stage / str(action["history_relative_path"])
            _require_within(stage, destination, "Retained-history destination")
            _verify_file(current, action, "Retained generated file")
            if destination.exists():
                _verify_file(destination, action, "Staged retained file")
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                # 224 (Wave B2a): checked under a partial name first, so a copy cut short never sits at the
                # staged name, where the next try would refuse it.
                safe_write.copy_file(current, destination)
                _verify_file(destination, action, "Staged retained file")
            copied += 1
            callback = payload.get("_during_history_staging")
            if copied == 1 and callable(callback):
                callback(source)
        manifest = {
            "schema_version": 1,
            "plan_sha256": plan["plan_sha256"],
            "batch_id": plan["batch_id"],
            "source_id": source["source_id"],
            "source_identity": source["source_identity"],
            "source_token": source["source_token"],
            "results_submission_sha256": plan["results_submission_sha256"],
            "preliminary_submission_sha256": plan["preliminary_submission_sha256"],
            "targeted_evidence_identity": plan["targeted_evidence_identity"],
            "dispositions": source["dispositions"],
            "result_ids": source["result_ids"],
            "resulting_state": source["resulting_state"],
            "retained_bytes": source["retained_bytes"],
            "disposable_bytes": source["disposable_bytes"],
            "retained_files": source["retain_actions"],
            "cleanup_files": source["cleanup_actions"],
            "complete": True,
        }
        _atomic_json(stage / "retained-history-manifest.json", manifest)
        integrity_path = stage / "integrity.json"
        if integrity_path.exists():
            safe_write.remove(integrity_path, wait=safe_write.INBOX_WAIT_SECONDS)
        _atomic_json(
            integrity_path,
            {"schema_version": 1, "plan_sha256": plan["plan_sha256"], "complete": True, "files": _hash_inventory(stage)},
        )
        _verify_history(stage, str(plan["plan_sha256"]), str(source["source_identity"]))


def _promote_history(plan: dict[str, Any], payload: dict[str, Any], warnings: list[str]) -> None:
    for source in plan["sources"]:
        stage = _history_staging_root(plan, source)
        destination = Path(str(source["history_destination"]))
        _require_within(Path(str(plan["history_root"])), destination, "Retained-history promotion")
        _progress(payload, "history_promotion", source, "Promoting verified retained history")
        if destination.exists():
            _verify_history(destination, str(plan["plan_sha256"]), str(source["source_identity"]))
            if stage.exists():
                # The verified history is already in place; this staged copy of it is a leftover.
                _tidy(plan, payload, Path(str(plan["history_root"])).parent / ".staging", stage, warnings)
        else:
            _verify_history(stage, str(plan["plan_sha256"]), str(source["source_identity"]))
            destination.parent.mkdir(parents=True, exist_ok=True)
            _replace(stage, destination)
            _verify_history(destination, str(plan["plan_sha256"]), str(source["source_identity"]))


def _mark_finalizing(plan: dict[str, Any], journal_path: Path) -> None:
    ledger_path = Path(str(plan["ledger_path"]))
    connection = inbox_records.connect(ledger_path, must_exist=True)
    try:
        connection.execute("BEGIN IMMEDIATE")
        now = _utc_now()
        existing = connection.execute(
            "SELECT plan_sha256, status FROM inbox_finalization_runs WHERE batch_id = ?",
            (plan["batch_id"],),
        ).fetchone()
        if existing is not None and str(existing["plan_sha256"]) != str(plan["plan_sha256"]):
            raise FinalizationError("A different finalization plan already governs this batch.")
        if existing is None:
            connection.execute(
                """
                INSERT INTO inbox_finalization_runs
                    (plan_sha256, batch_id, results_submission_sha256, preliminary_submission_sha256, status, journal_path, created_utc, updated_utc)
                VALUES (?, ?, ?, ?, 'planned', ?, ?, ?)
                """,
                (
                    plan["plan_sha256"],
                    plan["batch_id"],
                    plan["results_submission_sha256"],
                    plan["preliminary_submission_sha256"],
                    str(journal_path),
                    now,
                    now,
                ),
            )
        elif str(existing["status"] or "") in {"ledger_committed", "cleanup_complete"}:
            connection.commit()
            return
        else:
            connection.execute(
                "UPDATE inbox_finalization_runs SET journal_path = ?, updated_utc = ? WHERE plan_sha256 = ?",
                (str(journal_path), now, plan["plan_sha256"]),
            )
        for source in plan["sources"]:
            source_id = int(source["source_id"])
            old = str(connection.execute("SELECT lifecycle_state FROM inbox_sources WHERE source_id = ?", (source_id,)).fetchone()[0])
            if old != "finalizing":
                connection.execute("UPDATE inbox_sources SET lifecycle_state = 'finalizing', updated_utc = ? WHERE source_id = ?", (now, source_id))
                connection.execute("UPDATE inbox_batch_sources SET state = 'finalizing', updated_utc = ? WHERE batch_id = ? AND source_id = ?", (now, plan["batch_id"], source_id))
                review_ledger._insert_lifecycle_event(
                    connection,
                    source_id=source_id,
                    batch_id=plan["batch_id"],
                    event_type="finalization_started",
                    from_state=old,
                    to_state="finalizing",
                    details={"plan_sha256": plan["plan_sha256"]},
                )
        old_batch = str(connection.execute("SELECT status FROM inbox_batches WHERE batch_id = ?", (plan["batch_id"],)).fetchone()[0])
        if old_batch != "finalizing":
            connection.execute("UPDATE inbox_batches SET status = 'finalizing', updated_utc = ? WHERE batch_id = ?", (now, plan["batch_id"]))
            review_ledger._insert_lifecycle_event(
                connection,
                source_id=None,
                batch_id=plan["batch_id"],
                event_type="finalization_started",
                from_state=old_batch,
                to_state="finalizing",
                details={"plan_sha256": plan["plan_sha256"]},
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _commit_ledger(plan: dict[str, Any]) -> str:
    ledger_path = Path(str(plan["ledger_path"]))
    # 224 (Wave B1): every source's retained history is read and hashed first, with no write transaction
    # open; the commit below only writes. This check stays even when an earlier run promoted the history:
    # on a recovery that starts at "history_promoted" it is the only one.
    verified = {
        int(source["source_id"]): _verify_history(
            Path(str(source["history_destination"])), str(plan["plan_sha256"]), str(source["source_identity"])
        )
        for source in plan["sources"]
    }
    connection = inbox_records.connect(ledger_path, must_exist=True)
    try:
        connection.execute("BEGIN IMMEDIATE")
        now = _utc_now()
        final_state = str(plan["resulting_batch_state"])
        for source in plan["sources"]:
            source_id = int(source["source_id"])
            history = Path(str(source["history_destination"]))
            integrity_sha = verified[source_id]
            existing_retention = connection.execute(
                "SELECT * FROM inbox_retention_records WHERE plan_sha256 = ? AND source_id = ?",
                (plan["plan_sha256"], source_id),
            ).fetchone()
            if existing_retention is None:
                connection.execute(
                    """
                    INSERT INTO inbox_retention_records
                        (plan_sha256, batch_id, source_id, resulting_state, history_path, retained_bytes, disposable_bytes, history_integrity_sha256, created_utc)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        plan["plan_sha256"], plan["batch_id"], source_id, source["resulting_state"], str(history),
                        source["retained_bytes"], source["disposable_bytes"], integrity_sha, now,
                    ),
                )
            else:
                expected = (str(source["resulting_state"]), str(history), int(source["retained_bytes"]), int(source["disposable_bytes"]), integrity_sha)
                recorded = (
                    str(existing_retention["resulting_state"]), str(existing_retention["history_path"]),
                    int(existing_retention["retained_bytes"]), int(existing_retention["disposable_bytes"]),
                    str(existing_retention["history_integrity_sha256"]),
                )
                if expected != recorded:
                    raise FinalizationError("Existing retention ledger record contradicts verified history.")
            attempt = connection.execute(
                "SELECT 1 FROM inbox_attempts WHERE source_id = ? AND batch_id = ? AND attempt_type = 'finalization' AND settings_hash = ? AND status = 'completed' LIMIT 1",
                (source_id, plan["batch_id"], plan["plan_sha256"]),
            ).fetchone()
            if attempt is None:
                connection.execute(
                    "INSERT INTO inbox_attempts (source_id, batch_id, attempt_type, status, started_utc, completed_utc, settings_hash) VALUES (?, ?, 'finalization', 'completed', ?, ?, ?)",
                    (source_id, plan["batch_id"], now, now, plan["plan_sha256"]),
                )
            old = str(connection.execute("SELECT lifecycle_state FROM inbox_sources WHERE source_id = ?", (source_id,)).fetchone()[0])
            state = str(source["resulting_state"])
            connection.execute("UPDATE inbox_sources SET lifecycle_state = ?, updated_utc = ? WHERE source_id = ?", (state, now, source_id))
            connection.execute("UPDATE inbox_batch_sources SET state = ?, updated_utc = ? WHERE batch_id = ? AND source_id = ?", (state, now, plan["batch_id"], source_id))
            if old != state:
                review_ledger._insert_lifecycle_event(
                    connection,
                    source_id=source_id,
                    batch_id=plan["batch_id"],
                    event_type="finalization_completed" if state.startswith("finalized_") else "finalization_requires_attention",
                    from_state=old,
                    to_state=state,
                    details={"plan_sha256": plan["plan_sha256"], "history_path": str(history)},
                )
        old_batch = str(connection.execute("SELECT status FROM inbox_batches WHERE batch_id = ?", (plan["batch_id"],)).fetchone()[0])
        connection.execute("UPDATE inbox_batches SET status = ?, updated_utc = ? WHERE batch_id = ?", (final_state, now, plan["batch_id"]))
        if old_batch != final_state:
            review_ledger._insert_lifecycle_event(
                connection,
                source_id=None,
                batch_id=plan["batch_id"],
                event_type="finalization_completed" if final_state.startswith("finalized_") else "finalization_requires_attention",
                from_state=old_batch,
                to_state=final_state,
                details={"plan_sha256": plan["plan_sha256"]},
            )
        connection.execute(
            "UPDATE inbox_finalization_runs SET status = 'ledger_committed', updated_utc = ? WHERE plan_sha256 = ?",
            (now, plan["plan_sha256"]),
        )
        violations = inbox_records.link_problems(connection)
        if violations:
            raise FinalizationError(f"Foreign-key validation failed during finalization: {violations!r}")
        connection.commit()
        return final_state
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _reconcile_batch_manifest(plan: dict[str, Any], final_state: str) -> None:
    batch_root = Path(str(plan["batch_root"]))
    manifest_path = batch_root / "batch-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["status"] = final_state
    manifest["finalization"] = {
        "version": FINALIZATION_VERSION,
        "plan_sha256": plan["plan_sha256"],
        "results_submission_sha256": plan["results_submission_sha256"],
        "status": final_state,
        "history_destinations": [str(item["history_destination"]) for item in plan["sources"]],
        "updated_utc": _utc_now(),
    }
    _atomic_json(manifest_path, manifest)


def _delete_quarantine(plan: dict[str, Any], payload: dict[str, Any], warnings: list[str]) -> None:
    quarantine = _quarantine_root(plan)
    if quarantine.exists():
        quarantine_parent = Path(str(plan["batch_root"])) / ".finalization" / "quarantine"
        _require_within(quarantine_parent, quarantine, "Quarantine cleanup")
        # The records and the retained history are already committed: this is the clean-up after success.
        _tidy(plan, payload, quarantine_parent, quarantine, warnings)


def _validate_before_movement(plan: dict[str, Any]) -> None:
    ledger_path = Path(str(plan["ledger_path"]))
    batch_root = Path(str(plan["batch_root"]))
    try:
        accepted_sha, _document, basis, _submission, validation_path = review_results.load_accepted_results(
            ledger_path, batch_root, str(plan["batch_id"]), str(plan["results_submission_sha256"])
        )
    except review_results.FinalResultsError as exc:
        raise FinalizationError(str(exc)) from exc
    if accepted_sha != str(plan["results_submission_sha256"]):
        raise FinalizationError("The accepted final-results identity changed after preview.")
    if str(basis["targeted_evidence_identity"]) != str(plan["targeted_evidence_identity"]):
        raise FinalizationError("The targeted-evidence identity changed after preview.")
    if review_ledger.sha256_file(validation_path) != str(plan["accepted_results_validation_sha256"]):
        raise FinalizationError("The accepted final-results validation record changed after preview.")
    for source in plan["sources"]:
        for action in [*source["retain_actions"], *source["cleanup_actions"]]:
            _verify_file(_action_source(batch_root, action), action, "Previewed finalization file")


def finalize_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute or resume one explicitly confirmed immutable finalization plan."""

    _plan_path, plan = _load_plan(payload)
    batch_root = Path(str(plan["batch_root"]))
    journal_path = batch_root / ".finalization" / f"journal-{str(plan['plan_sha256'])[:24]}.json"
    _require_within(batch_root / ".finalization", journal_path, "Finalization journal")
    journal = _load_journal(journal_path)
    if journal is not None and str(journal.get("plan_sha256") or "") != str(plan["plan_sha256"]):
        raise FinalizationError("The finalization journal references a different immutable plan.")
    if journal is None and not bool(payload.get("operator_confirmed")):
        return {
            "action": "finalize_review_media_inbox",
            "status": "awaiting_operator_confirmation",
            "batch_id": plan["batch_id"],
            "plan_sha256": plan["plan_sha256"],
            "operator_confirmation": plan["operator_confirmation"],
        }
    if journal is None and bool(payload.get("cancel_before_start")):
        return {"action": "finalize_review_media_inbox", "status": "cancelled_before_execution", "batch_id": plan["batch_id"], "plan_sha256": plan["plan_sha256"]}
    if journal is None:
        _validate_before_movement(plan)
        journal = {
            "journal_version": JOURNAL_VERSION,
            "plan_sha256": plan["plan_sha256"],
            "batch_id": plan["batch_id"],
            "phase": "planned",
            "created_utc": _utc_now(),
            "updated_utc": _utc_now(),
            "recovery_count": 0,
        }
        _write_journal(journal_path, journal)
        callback = payload.get("_after_journal_planned")
        if callable(callback):
            callback(plan)
        _mark_finalizing(plan, journal_path)
        callback = payload.get("_before_movement")
        if callable(callback):
            callback(plan)
    else:
        journal["recovery_count"] = int(journal.get("recovery_count") or 0) + 1
        journal["updated_utc"] = _utc_now()
        _write_journal(journal_path, journal)
    _mark_finalizing(plan, journal_path)
    phase = str(journal["phase"])
    cleanup_warnings: list[str] = []
    quarantine = _quarantine_root(plan)
    movement_started = quarantine.exists() and any(path.is_file() for path in quarantine.rglob("*"))
    if phase == "planned" and not movement_started:
        _validate_before_movement(plan)
    if phase == "planned":
        _move_cleanup_to_quarantine(plan, payload)
        callback = payload.get("_after_quarantine_movement")
        if callable(callback):
            callback(plan)
        journal.update({"phase": "quarantined", "updated_utc": _utc_now()})
        _write_journal(journal_path, journal)
        phase = "quarantined"
    if phase == "quarantined":
        _prepare_history(plan, payload)
        journal.update({"phase": "history_staged", "updated_utc": _utc_now()})
        _write_journal(journal_path, journal)
        phase = "history_staged"
    if phase == "history_staged":
        _promote_history(plan, payload, cleanup_warnings)
        callback = payload.get("_after_history_promotion")
        if callable(callback):
            callback(plan)
        journal.update({"phase": "history_promoted", "updated_utc": _utc_now()})
        _write_journal(journal_path, journal)
        phase = "history_promoted"
    final_state = str(plan["resulting_batch_state"])
    if phase == "history_promoted":
        _progress(payload, "ledger_commit", None, "Committing final lifecycle and retention records")
        final_state = _commit_ledger(plan)
        _reconcile_batch_manifest(plan, final_state)
        callback = payload.get("_after_ledger_commit")
        if callable(callback):
            callback(plan)
        journal.update({"phase": "ledger_committed", "updated_utc": _utc_now(), "resulting_batch_state": final_state})
        _write_journal(journal_path, journal)
        phase = "ledger_committed"
    if phase == "ledger_committed":
        _progress(payload, "cleanup", None, "Removing only verified quarantine after durable ledger and history commit")
        _delete_quarantine(plan, payload, cleanup_warnings)
        callback = payload.get("_after_cleanup")
        if callable(callback):
            callback(plan)
        connection = inbox_records.connect(Path(str(plan["ledger_path"])), must_exist=True)
        try:
            connection.execute("UPDATE inbox_finalization_runs SET status = 'cleanup_complete', updated_utc = ? WHERE plan_sha256 = ?", (_utc_now(), plan["plan_sha256"]))
            connection.commit()
        finally:
            connection.close()
        journal.update({"phase": "cleanup_complete", "updated_utc": _utc_now(), "cleanup_completed_utc": _utc_now()})
        _write_journal(journal_path, journal)
    _progress(payload, "complete", None, f"Finalization finished with truthful batch state {final_state}")
    return {
        "action": "finalize_review_media_inbox",
        "status": final_state,
        "batch_id": plan["batch_id"],
        "batch_path": plan["batch_root"],
        "plan_sha256": plan["plan_sha256"],
        "journal_path": str(journal_path),
        "journal_phase": "cleanup_complete",
        "retained_bytes": plan["retained_bytes"],
        "disposable_bytes": plan["disposable_bytes"],
        "history_destinations": [str(item["history_destination"]) for item in plan["sources"]],
        "sources": [
            {
                "source_identity": item["source_identity"],
                "resulting_state": item["resulting_state"],
                "history_destination": item["history_destination"],
                "retained_bytes": item["retained_bytes"],
                "disposable_bytes": item["disposable_bytes"],
            }
            for item in plan["sources"]
        ],
        "idempotent": int(journal.get("recovery_count") or 0) > 0,
        "cleanup_warnings": cleanup_warnings,
    }


NEEDS_A_LOOK = ("Batch {batch} needs a look: {reason} Nothing was changed; recovery waits until the batch's "
                "finalization journal and its records agree.")


def recorded_journal(ledger_path: Path, batch_id: str, batch_root: Path) -> tuple[Path, str] | None:
    """The finalization journal the Inbox's records name for this batch, and its plan (224, F10): the records
    say which journal belongs to the batch (one finalization per batch), not the order of the journals' file
    names, which are hash prefixes. None when no finalization is recorded. A recorded journal that is missing,
    outside the batch, damaged or for another plan stops with "needs a look" instead of guessing."""

    connection = _read_ledger(ledger_path)
    try:
        row = connection.execute(
            "SELECT plan_sha256, journal_path FROM inbox_finalization_runs WHERE batch_id = ?", (batch_id,)).fetchone()
    finally:
        connection.close()
    if row is None:
        return None
    plan_sha, journal_path = str(row[0] or ""), Path(str(row[1] or ""))
    if not _within(batch_root / ".finalization", journal_path):
        raise FinalizationError(NEEDS_A_LOOK.format(
            batch=batch_id, reason="its records name a finalization journal outside the batch."))
    journal = _load_journal(journal_path)
    if journal is None:
        raise FinalizationError(NEEDS_A_LOOK.format(
            batch=batch_id, reason="the finalization journal its records name is missing."))
    if str(journal.get("plan_sha256") or "") != plan_sha:
        raise FinalizationError(NEEDS_A_LOOK.format(
            batch=batch_id, reason="its finalization journal is for a different plan than its records."))
    return journal_path, plan_sha


def status_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    ledger_path = Path(str(payload.get("ledger_path") or ""))
    batch_id = str(payload.get("expected_batch_id") or payload.get("batch_id") or "")
    batch_root = review_targeted_evidence._resolve_batch_root(ledger_path, batch_id, str(payload.get("batch_path") or ""))
    recorded = recorded_journal(ledger_path, batch_id, batch_root)
    if recorded is None:
        return {"action": "finalization_status", "status": "not_started", "batch_id": batch_id, "recovery_required": False}
    journal_path, _plan_sha = recorded
    journal = _load_journal(journal_path)
    if journal is None:
        raise FinalizationError("Finalization journal disappeared during status inspection.")
    phase = str(journal["phase"])
    connection = _read_ledger(ledger_path)
    try:
        batch_state = str(connection.execute("SELECT status FROM inbox_batches WHERE batch_id = ?", (batch_id,)).fetchone()[0])
        history = [str(row[0]) for row in connection.execute("SELECT history_path FROM inbox_retention_records WHERE batch_id = ? ORDER BY source_id", (batch_id,)).fetchall()]
    finally:
        connection.close()
    return {
        "action": "finalization_status",
        "status": phase,
        "batch_id": batch_id,
        "batch_state": batch_state,
        "plan_sha256": journal["plan_sha256"],
        "journal_path": str(journal_path),
        "recovery_required": phase != "cleanup_complete",
        "history_destinations": history,
        "recovery_count": int(journal.get("recovery_count") or 0),
    }
