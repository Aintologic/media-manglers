"""Deterministic local queue projection for Review Media Inbox.

This module owns local queue files and external-return reconciliation only.  It
does not scan source folders, render media, inspect repositories or GitHub, or
make semantic review decisions.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable
import uuid

from . import inbox_records, review_findings, review_ledger, review_results, safe_write


CONTRACT_VERSION = 1
DOCUMENT_TYPE = "review_media_inbox_queue"
QUEUE_PROMPT_NAME = "CODEX_REVIEW_QUEUE_PROMPT.md"
QUEUE_INDEX_NAME = "queue-index.json"
EXTERNAL_RETURNS_DIR = "external-returns"
PRELIMINARY_RETURN_NAME = "preliminary-findings.json"
FINAL_RESULTS_RETURN_NAME = "review-results.json"

FINALIZED_STATES = {"finalized_no_findings", "finalized_with_findings"}
PRELIMINARY_IMPORT_STATES = {"awaiting_external_review"}
FINAL_RESULTS_IMPORT_STATES = {"targeted_evidence_ready"}
EXTERNAL_REVIEW_STATES = PRELIMINARY_IMPORT_STATES | FINAL_RESULTS_IMPORT_STATES
BLOCKING_ATTENTION_STATES = {"retryable_failure", "source_changed"}
MANUAL_REVIEW_STATE = "needs_manual_review"


def queue_root_for_ledger(ledger_path: str | Path) -> Path:
    """Return the canonical queue root without creating it: the Inbox's workspace (``inbox_records``)."""

    value = str(ledger_path or "").strip()
    if not value:
        raise ValueError("ledger_path is required for Review Media Inbox queue reconciliation.")
    return inbox_records.workspace(value)


def _atomic_bytes(path: Path, data: bytes) -> None:
    # 224 (Wave B1): the one safe writer replaces the file; the bytes are the queue's own, as before.
    safe_write.write_bytes(path, data, wait=safe_write.INBOX_WAIT_SECONDS)


def _atomic_text(path: Path, text: str) -> None:
    _atomic_bytes(path, text.encode("utf-8"))


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def read_stable_candidate(path: str | Path) -> dict[str, Any]:
    """Read one exact return path only when size and mtime remain unchanged."""

    candidate = Path(path)
    result: dict[str, Any] = {
        "path": str(candidate),
        "exists": False,
        "stable": False,
        "size_bytes": 0,
        "modified_ns": 0,
        "sha256": "",
        "content": b"",
        "error": "",
    }
    try:
        if candidate.is_symlink():
            return {
                **result,
                "exists": True,
                "error": "Symbolic links are not accepted as external Review Media Inbox returns.",
            }
        if not candidate.is_file():
            return result
        before = candidate.stat()
        content = candidate.read_bytes()
        after = candidate.stat()
    except FileNotFoundError:
        return result
    except OSError as exc:
        try:
            exists = candidate.exists()
        except OSError:
            exists = False
        return {**result, "exists": exists, "error": str(exc)}
    result.update(
        {
            "exists": True,
            "size_bytes": int(after.st_size),
            "modified_ns": int(after.st_mtime_ns),
        }
    )
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        return result
    result.update(
        {
            "stable": True,
            "sha256": hashlib.sha256(content).hexdigest(),
            "content": content,
        }
    )
    return result


def _relative_path(root: Path, target: Path) -> str:
    try:
        return target.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return ""


def _batch_rows(ledger_path: Path) -> tuple[list[dict[str, Any]], int]:
    # A reader (224, F4): with no ledger yet there is nothing queued, and none is made here.
    connection = inbox_records.connect_read_only(ledger_path)
    if connection is None:
        return [], 0
    try:
        rows = connection.execute(
            """
            SELECT b.batch_id, b.status, b.package_path, b.created_utc, b.updated_utc,
                   COUNT(bs.source_id) AS source_count
            FROM inbox_batches b
            LEFT JOIN inbox_batch_sources bs ON bs.batch_id = b.batch_id
            GROUP BY b.batch_id
            ORDER BY b.created_utc, b.batch_id
            """
        ).fetchall()
        batches: list[dict[str, Any]] = []
        for row in rows:
            source_states = [
                str(item[0])
                for item in connection.execute(
                    "SELECT state FROM inbox_batch_sources WHERE batch_id = ? ORDER BY ordinal",
                    (str(row["batch_id"]),),
                ).fetchall()
            ]
            batches.append(
                {
                    "batch_id": str(row["batch_id"]),
                    "status": str(row["status"] or ""),
                    "batch_path": str(row["package_path"] or ""),
                    "source_count": int(row["source_count"] or 0),
                    "source_states": source_states,
                    "created_utc": str(row["created_utc"] or ""),
                    "updated_utc": str(row["updated_utc"] or ""),
                }
            )
        done_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM inbox_sources WHERE lifecycle_state IN ('finalized_no_findings', 'finalized_with_findings')"
            ).fetchone()[0]
        )
        return batches, done_count
    finally:
        connection.close()


def _operator_state(status: str) -> str:
    if status == "awaiting_external_review":
        return "ready_for_codex_review"
    if status == "targeted_evidence_ready":
        return "waiting_on_codex"
    if status == "preliminary_findings_received":
        return "additional_local_evidence"
    if status in FINALIZED_STATES:
        return "done"
    if status == "needs_audio_confirmation":
        return "needs_audio_choice"
    if status in BLOCKING_ATTENTION_STATES:
        return "needs_attention"
    if status == MANUAL_REVIEW_STATE:
        return "manual_review"
    return "processing"


def _batch_entry(queue_root: Path, row: dict[str, Any]) -> dict[str, Any]:
    batch_value = str(row.get("batch_path") or "").strip()
    batch_root = Path(batch_value) if batch_value else Path()
    status = str(row.get("status") or "")
    relative = _relative_path(queue_root, batch_root) if batch_value else ""
    package_contained = bool(relative and relative not in {".", ".."})
    returns_root = batch_root / EXTERNAL_RETURNS_DIR if package_contained else Path()
    returns_relative = (
        _relative_path(batch_root, returns_root) if package_contained else ""
    )
    returns_contained = bool(
        package_contained and returns_relative and returns_relative not in {".", ".."}
    )
    preliminary_path = (
        returns_root / PRELIMINARY_RETURN_NAME
        if returns_contained
        else Path()
    )
    final_path = (
        returns_root / FINAL_RESULTS_RETURN_NAME
        if returns_contained
        else Path()
    )
    operator_state = _operator_state(status)
    source_states = [str(item) for item in row.get("source_states") or []]
    if "needs_audio_confirmation" in source_states:
        operator_state = "needs_audio_choice"
    elif any(state in BLOCKING_ATTENTION_STATES for state in source_states):
        operator_state = "needs_attention"
    elif MANUAL_REVIEW_STATE in source_states:
        operator_state = "manual_review"
    if status not in FINALIZED_STATES and (
        not package_contained or not returns_contained
    ):
        operator_state = "needs_attention"
    package_integrity_valid = True
    package_integrity_error = ""
    if (
        status in EXTERNAL_REVIEW_STATES
        and package_contained
        and batch_root.is_dir()
    ):
        try:
            from . import review_preparation

            review_preparation.validate_batch_packages(
                batch_root,
                expected_source_count=int(row.get("source_count") or 0),
            )
        except Exception as exc:
            package_integrity_valid = False
            package_integrity_error = f"{type(exc).__name__}: {exc}"
            operator_state = "needs_attention"
    return {
        **row,
        "operator_state": operator_state,
        "package_integrity_valid": package_integrity_valid,
        "package_integrity_error": package_integrity_error,
        "package_contained": package_contained,
        "returns_contained": returns_contained,
        "batch_relative_path": relative if package_contained else "",
        "preliminary_return_path": str(preliminary_path) if returns_contained else "",
        "final_results_return_path": str(final_path) if returns_contained else "",
    }


def _attention(
    batch_id: str,
    code: str,
    message: str,
    *,
    path: str = "",
    sha256: str = "",
    problems: list[str] | None = None,
    states: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "batch_id": batch_id,
        "code": code,
        "message": message,
        "path": path,
        "sha256": sha256,
        "problems": list(problems or []),
        "states": list(states or []),
    }


def _generated_preliminary_sha(batch_root: Path) -> str:
    template = read_stable_candidate(batch_root / "preliminary-findings.template.json")
    if not template["stable"]:
        detail = str(template["error"] or "the generated template is missing or changing")
        raise ValueError(f"The preliminary generated baseline is unavailable: {detail}.")
    return str(template["sha256"])


def _generated_final_shas(batch_root: Path) -> set[str]:
    manifest_path = batch_root / "batch-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict):
        raise ValueError("batch-manifest.json must contain one JSON object.")
    return review_results.generated_final_results_template_sha256s(batch_root, manifest)


def _submission_candidate(
    entry: dict[str, Any],
    kind: str,
) -> tuple[dict[str, Any] | None, str, dict[str, Any] | None]:
    batch_id = str(entry["batch_id"])
    batch_root = Path(str(entry["batch_path"]))
    if kind == "preliminary":
        external_path = Path(str(entry["preliminary_return_path"]))
        legacy_path = batch_root / PRELIMINARY_RETURN_NAME
    else:
        external_path = Path(str(entry["final_results_return_path"]))
        legacy_path = batch_root / FINAL_RESULTS_RETURN_NAME

    external = read_stable_candidate(external_path)
    if external["exists"]:
        if external["stable"]:
            return external, "external_returns", None
        if external["error"]:
            return None, "", _attention(
                batch_id,
                "external_return_unreadable",
                "An external return exists but could not be read safely.",
                path=str(external_path),
                problems=[str(external["error"])],
            )
        return None, "", None

    legacy = read_stable_candidate(legacy_path)
    if not legacy["exists"] or not legacy["stable"]:
        if legacy["error"]:
            return None, "", _attention(
                batch_id,
                "legacy_return_unreadable",
                "A legacy working return exists but could not be read safely.",
                path=str(legacy_path),
                problems=[str(legacy["error"])],
            )
        return None, "", None
    try:
        generated = (
            {_generated_preliminary_sha(batch_root)}
            if kind == "preliminary"
            else _generated_final_shas(batch_root)
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
        return None, "", _attention(
            batch_id,
            "generated_baseline_unavailable",
            "Media Manglers could not safely distinguish the legacy working file from generated template output.",
            path=str(legacy_path),
            sha256=str(legacy["sha256"]),
            problems=[str(exc)],
        )
    generated.discard("")
    if str(legacy["sha256"]) in generated:
        return None, "", None
    return legacy, "legacy_working_file", None


def _import_candidate(
    ledger_path: Path,
    entry: dict[str, Any],
    kind: str,
    candidate: dict[str, Any],
    source: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    batch_id = str(entry["batch_id"])
    batch_root = Path(str(entry["batch_path"]))
    candidate_path = str(candidate["path"])
    candidate_sha = str(candidate.get("sha256") or "")
    content = candidate.get("content")
    if not isinstance(content, bytes) or hashlib.sha256(content).hexdigest() != candidate_sha:
        return None, _attention(
            batch_id,
            "external_return_changed",
            "The external return changed after detection and will be retried later.",
            path=candidate_path,
            sha256=candidate_sha,
        )
    staging_root = batch_root / ".queue-import"
    if not _relative_path(batch_root, staging_root):
        return None, _attention(
            batch_id,
            "external_return_staging_unsafe",
            "Media Manglers could not create a bounded internal import staging path.",
            path=candidate_path,
            sha256=candidate_sha,
        )
    staged_path = staging_root / f".mm-import-{uuid.uuid4().hex[:16]}.json"
    try:
        _atomic_bytes(staged_path, content)
        staged = read_stable_candidate(staged_path)
        if not staged["stable"] or str(staged["sha256"]) != candidate_sha:
            raise RuntimeError("The bounded import staging copy did not preserve the detected return bytes.")
        if kind == "preliminary":
            result = review_findings.import_from_request(
                {
                    "ledger_path": str(ledger_path),
                    "batch_path": str(batch_root),
                    "expected_batch_id": batch_id,
                    "findings_path": str(staged_path),
                }
            )
        else:
            result = review_results.import_from_request(
                {
                    "ledger_path": str(ledger_path),
                    "batch_path": str(batch_root),
                    "expected_batch_id": batch_id,
                    "results_path": str(staged_path),
                }
            )
    except Exception as exc:
        return None, _attention(
            batch_id,
            "external_return_import_failed",
            "The external return could not be imported safely.",
            path=candidate_path,
            sha256=str(candidate["sha256"]),
            problems=[str(exc)],
        )
    finally:
        try:
            # 224 (Wave B2a): the one antivirus-safe removal; a copy still held at the deadline stays, as before.
            safe_write.remove(staged_path, wait=safe_write.INBOX_WAIT_SECONDS)
        except OSError:
            pass
        try:
            staging_root.rmdir()
        except OSError:
            pass
    if bool(result.get("accepted")):
        return {
            "batch_id": batch_id,
            "kind": kind,
            "source": source,
            "path": candidate_path,
            "sha256": str(candidate["sha256"]),
            "idempotent": bool(result.get("idempotent")),
            "status": str(result.get("status") or ""),
        }, None
    problems = [str(item) for item in result.get("problems") or []]
    return None, _attention(
        batch_id,
        "invalid_external_return",
        "A stable external return was rejected safely. Replace it with a corrected file.",
        path=candidate_path,
        sha256=str(candidate["sha256"]),
        problems=problems,
    )


def _reconcile_external(
    ledger_path: Path,
    entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    imported: list[dict[str, Any]] = []
    attention: list[dict[str, Any]] = []
    work: tuple[tuple[str, set[str]], ...] = (
        ("final_results", FINAL_RESULTS_IMPORT_STATES),
        ("preliminary", PRELIMINARY_IMPORT_STATES),
    )
    for kind, eligible_states in work:
        for entry in entries:
            if str(entry["status"]) not in eligible_states:
                continue
            if not bool(entry.get("package_integrity_valid", True)):
                continue
            if not bool(entry.get("package_contained")) or not bool(
                entry.get("returns_contained")
            ):
                continue
            candidate, source, candidate_attention = _submission_candidate(entry, kind)
            if candidate_attention is not None:
                attention.append(candidate_attention)
                continue
            if candidate is None:
                continue
            imported_item, import_attention = _import_candidate(
                ledger_path,
                entry,
                kind,
                candidate,
                source,
            )
            if imported_item is not None:
                imported.append(imported_item)
            if import_attention is not None:
                attention.append(import_attention)
    return imported, attention


def _base_attention(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    attention: list[dict[str, Any]] = []
    for entry in entries:
        status = str(entry["status"])
        batch_id = str(entry["batch_id"])
        batch_path = str(entry["batch_path"])
        if status not in FINALIZED_STATES and not bool(entry.get("package_contained")):
            attention.append(
                _attention(
                    batch_id,
                    "batch_package_outside_queue",
                    "The active batch package is not contained by the canonical Review Media Inbox queue root.",
                    path=batch_path,
                )
            )
        elif status not in FINALIZED_STATES and not bool(
            entry.get("returns_contained")
        ):
            attention.append(
                _attention(
                    batch_id,
                    "external_returns_outside_batch",
                    "The external-return location is not contained by its active batch package.",
                    path=str(Path(batch_path) / EXTERNAL_RETURNS_DIR),
                )
            )
        elif status not in FINALIZED_STATES and (not batch_path or not Path(batch_path).is_dir()):
            attention.append(
                _attention(
                    batch_id,
                    "batch_package_missing",
                    "The ledger batch package is missing or unavailable.",
                    path=batch_path,
                )
            )
        elif not bool(entry.get("package_integrity_valid", True)):
            attention.append(
                _attention(
                    batch_id,
                    "prepared_package_integrity_failed",
                    (
                        "A prepared package no longer agrees with its manifest, "
                        "integrity inventory, and actual files. It is not available "
                        "for external review."
                    ),
                    path=batch_path,
                    problems=[str(entry.get("package_integrity_error") or "")],
                )
            )
        attention_states = sorted(
            {
                state
                for state in [status, *[str(item) for item in entry.get("source_states") or []]]
                if state in BLOCKING_ATTENTION_STATES
            }
        )
        if attention_states:
            attention.append(
                _attention(
                    batch_id,
                    "batch_needs_attention",
                    "The batch contains work paused in state "
                    + ", ".join(attention_states)
                    + ".",
                    path=batch_path,
                    states=attention_states,
                )
            )
    return attention


def _deduplicate_attention(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in items:
        key = (
            str(item.get("batch_id") or ""),
            str(item.get("code") or ""),
            str(item.get("sha256") or ""),
        )
        unique[key] = item
    return [
        unique[key]
        for key in sorted(unique, key=lambda value: (value[0], value[1], value[2]))
    ]


def _counts(entries: list[dict[str, Any]], done_count: int) -> dict[str, int]:
    result = {
        "ready_for_codex_review": 0,
        "waiting_on_codex": 0,
        "additional_local_evidence": 0,
        "manual_review": 0,
        "done": int(done_count),
    }
    for entry in entries:
        status = str(entry["status"])
        states = [str(item) for item in entry.get("source_states") or []]
        manual_count = states.count(MANUAL_REVIEW_STATE)
        if not manual_count and status == MANUAL_REVIEW_STATE:
            manual_count = max(0, int(entry.get("source_count") or 0))
        result["manual_review"] += manual_count
        if status == "awaiting_external_review":
            if bool(entry.get("package_integrity_valid", True)):
                result["ready_for_codex_review"] += states.count("awaiting_external_review")
        elif status == "targeted_evidence_ready":
            result["waiting_on_codex"] += states.count("targeted_evidence_ready")
        elif status == "preliminary_findings_received":
            result["additional_local_evidence"] += states.count(
                "preliminary_findings_received"
            )
    return result


def _operator_status(
    entries: list[dict[str, Any]],
    counts: dict[str, int],
    attention: list[dict[str, Any]],
) -> str:
    if any(str(entry["operator_state"]) == "needs_audio_choice" for entry in entries):
        return "Needs audio choice"
    if attention or any(str(entry["operator_state"]) == "needs_attention" for entry in entries):
        return "Needs attention"
    if any(
        str(entry["operator_state"]) in {"processing", "additional_local_evidence"}
        for entry in entries
    ):
        return "Processing"
    if counts["ready_for_codex_review"]:
        return "Ready for Codex review"
    if counts["waiting_on_codex"]:
        return "Waiting on Codex"
    if counts["manual_review"]:
        return "Manual review available"
    return "Done"


def _externally_reviewable_entries(
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        entry
        for entry in entries
        if str(entry.get("status") or "") in EXTERNAL_REVIEW_STATES
        and bool(entry.get("package_integrity_valid", True))
        and bool(entry.get("package_contained"))
        and bool(entry.get("returns_contained"))
        and Path(str(entry.get("batch_path") or "")).is_dir()
    ]


def _manual_review_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return sanitized retained-work pointers without exposing source paths."""

    retained: list[dict[str, Any]] = []
    for entry in entries:
        status = str(entry.get("status") or "")
        states = [str(item) for item in entry.get("source_states") or []]
        manual_count = states.count(MANUAL_REVIEW_STATE)
        if not manual_count and status == MANUAL_REVIEW_STATE:
            manual_count = max(0, int(entry.get("source_count") or 0))
        if not manual_count:
            continue
        retained.append(
            {
                "batch_id": str(entry.get("batch_id") or ""),
                "status": status,
                "manual_review_count": manual_count,
                "batch_relative_path": str(entry.get("batch_relative_path") or ""),
                "package_contained": bool(entry.get("package_contained")),
            }
        )
    return retained


def _queue_prompt(entries: list[dict[str, Any]]) -> str:
    active = _externally_reviewable_entries(entries)
    batch_sections: list[str] = []
    for entry in active:
        batch_sections.append(
            "\n".join(
                [
                    f"### Batch `{entry['batch_id']}`",
                    "",
                    f"- Current local state: `{entry['status']}`",
                    f"- Prepared package: `{entry['batch_path']}`",
                    f"- Preliminary return: `{entry['preliminary_return_path']}`",
                    f"- Final-results return: `{entry['final_results_return_path']}`",
                ]
            )
        )
    batches = "\n\n".join(batch_sections) if batch_sections else "No batches currently require external review."
    return f"""# Codex Review Queue

Review every active queued batch listed below. Media Manglers performs local preparation and contract validation only; it does not make semantic decisions, inspect repositories or GitHub, create issues, or launch an agent.

For each batch:

1. Review every prepared source and its available transcript or explicit no-audible-narration status, neutral visuals, metadata, and targeted evidence. A visual-only source is still a complete review item.
2. Inspect the relevant repositories plus both open and closed GitHub issues.
3. Identify bugs, requested features, completed work, duplicates, and useful supporting evidence.
4. Create or update an issue only when the operator has explicitly authorized that action.
5. When bounded additional local evidence is needed, write the preliminary contract to the exact Preliminary return path.
6. After requested evidence is ready and completely reviewed, write final structured results to the exact Final-results return path.
7. Write a temporary sibling first, validate it, and atomically replace the exact return path.
8. Never modify manifests, integrity records, source identities, the ledger, original media, `queue-index.json`, or `.orchestration`.

## Active batches

{batches}
"""


def refresh_queue(payload: dict[str, Any], *, import_external: bool = True) -> dict[str, Any]:
    """Reconcile stable external returns and atomically refresh queue artifacts."""

    ledger_value = str(payload.get("ledger_path") or "").strip()
    queue_root = queue_root_for_ledger(ledger_value)
    ledger_path = Path(ledger_value)
    queue_root.mkdir(parents=True, exist_ok=True)

    rows, done_count = _batch_rows(ledger_path)
    entries = [_batch_entry(queue_root, row) for row in rows]
    for entry in entries:
        batch_path = str(entry["batch_path"])
        if (
            batch_path
            and bool(entry.get("package_contained"))
            and bool(entry.get("returns_contained"))
            and bool(entry.get("package_integrity_valid", True))
            and str(entry["status"]) in EXTERNAL_REVIEW_STATES
            and Path(batch_path).is_dir()
        ):
            (Path(batch_path) / EXTERNAL_RETURNS_DIR).mkdir(parents=True, exist_ok=True)

    imported: list[dict[str, Any]] = []
    import_attention: list[dict[str, Any]] = []
    if import_external:
        imported, import_attention = _reconcile_external(ledger_path, entries)
        if imported:
            rows, done_count = _batch_rows(ledger_path)
            entries = [_batch_entry(queue_root, row) for row in rows]

    attention = _deduplicate_attention([*_base_attention(entries), *import_attention])
    counts = _counts(entries, done_count)
    operator_status = _operator_status(entries, counts, attention)
    public_entries = _externally_reviewable_entries(entries)
    manual_review = _manual_review_entries(entries)
    index_path = queue_root / QUEUE_INDEX_NAME
    prompt_path = queue_root / QUEUE_PROMPT_NAME
    queue_index = {
        "contract_version": CONTRACT_VERSION,
        "document_type": DOCUMENT_TYPE,
        "counts": counts,
        "operator_status": operator_status,
        "batches": public_entries,
        "manual_review": manual_review,
        "attention": attention,
    }
    _atomic_json(index_path, queue_index)
    _atomic_text(prompt_path, _queue_prompt(entries))
    return {
        **queue_index,
        "queue_root": str(queue_root),
        "queue_prompt_path": str(prompt_path),
        "queue_index_path": str(index_path),
        "imported": imported,
        "internal_batches": entries,
    }
