"""Deterministic one-click orchestration for Review Media Inbox.

The normalized ledger and existing batch contracts remain authoritative.  This
module stores only transient Process-run state in a checksummed file beside the
ledger.  It deliberately performs at most one bounded local action per call so
the PowerShell host can remain responsive, execute Workflow 3 targeted renders,
and call back into the coordinator while ``continue_automatically`` is true.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import statistics
import time
from typing import Any, Callable
import uuid

from . import inbox_records, safe_write


CONTRACT_VERSION = 1
RUN_JOURNAL_VERSION = 1
QUEUE_COUNT_KEYS = (
    "ready_for_codex_review",
    "waiting_on_codex",
    "additional_local_evidence",
    "manual_review",
    "done",
)
WORKLOAD_LIMITS = {
    "next_3": 3,
    "up_to_n": None,
    "all_pending": None,
}
SOFT_LIMIT_MINUTES = 240.0
MAX_UP_TO_N = 9_999
HIDDEN_BATCH_SIZE = 3


class OrchestrationError(RuntimeError):
    """Raised when transient orchestration state cannot be trusted."""


class ExactSourceRestrictionError(OrchestrationError):
    """Raised when a run-scoped exact-source restriction cannot be trusted."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    # 224 (Wave B1): the one safe writer replaces the file with the same compact bytes. It retries only the
    # brief hold a virus scanner or an indexer puts on it; every other failure leaves the prior journal.
    safe_write.write_bytes(path, _canonical_bytes(value), wait=safe_write.INBOX_WAIT_SECONDS)


def _write_journal(path: Path, run: dict[str, Any]) -> None:
    safe_run = _json_safe(run)
    _atomic_json(
        path,
        {
            "journal_version": RUN_JOURNAL_VERSION,
            "run": safe_run,
            "run_sha256": _sha256(safe_run),
        },
    )


def _read_journal(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OrchestrationError(f"The active Process run journal cannot be read: {exc}.") from exc
    if not isinstance(envelope, dict) or envelope.get("journal_version") != RUN_JOURNAL_VERSION:
        raise OrchestrationError("The active Process run journal has an unsupported version.")
    run = envelope.get("run")
    if not isinstance(run, dict) or str(envelope.get("run_sha256") or "") != _sha256(run):
        raise OrchestrationError("The active Process run journal checksum does not match its content.")
    return run


def _ledger_path(payload: dict[str, Any]) -> Path:
    cli = payload.get("cli") if isinstance(payload.get("cli"), dict) else {}
    value = str(payload.get("ledger_path") or cli.get("ledger_path") or "").strip()
    if not value:
        raise ValueError("ledger_path is required for Review Media Inbox orchestration.")
    return Path(value)


def _orchestration_paths(ledger_path: Path) -> dict[str, Path]:
    root = inbox_records.orchestration_folder(ledger_path)
    return {
        "root": root,
        "active": root / "active-run.json",
        "completed": root / "completed-runs",
        "lock": root / inbox_records.LOCK_NAME,
        "stop": root / "stop.requested",
    }


def _refresh_queue(payload: dict[str, Any], *, import_external: bool) -> dict[str, Any]:
    # Import lazily so source-only tests can patch this seam and so packaging can
    # report a precise missing-sidecar error rather than fail module discovery.
    from media_manglers.core import review_queue

    result = review_queue.refresh_queue(payload, import_external=import_external)
    if not isinstance(result, dict):
        raise OrchestrationError("Review queue refresh returned no usable contract.")
    return result


def _scan_inventory(payload: dict[str, Any]) -> dict[str, Any]:
    from media_manglers.core import review_inbox

    scan_payload = dict(payload)
    cli = dict(scan_payload.get("cli") or {}) if isinstance(scan_payload.get("cli"), dict) else {}
    for key, value in {
        "order": "oldest",
        "max_files": MAX_UP_TO_N,
        "pending_batch_limit": MAX_UP_TO_N,
    }.items():
        scan_payload[key] = value
        if cli:
            cli[key] = value
    # Inbox settings owns Fast/Full.  Process defaults safely to Fast, but an
    # explicitly acknowledged Full request must survive orchestration.
    dedupe_mode = str(
        scan_payload.get("dedupe_mode") or cli.get("dedupe_mode") or "Fast"
    )
    scan_payload["dedupe_mode"] = dedupe_mode
    if cli:
        cli["dedupe_mode"] = dedupe_mode
    if cli:
        scan_payload["cli"] = cli
    requested_exact_paths = _normalise_exact_source_paths(payload)
    prohibited_full_hashes: list[str] = []
    if requested_exact_paths:
        allowed_full_hashes: set[str] = set()
        for value in requested_exact_paths:
            try:
                resolved = Path(value).resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            allowed_full_hashes.add(os.path.normcase(str(resolved)))
        supplied_full_hasher = payload.get("full_hasher")
        base_full_hasher = (
            supplied_full_hasher
            if callable(supplied_full_hasher)
            else review_inbox.full_sha256_file
        )

        def restricted_full_hasher(path: Path) -> str:
            try:
                key = os.path.normcase(str(Path(path).resolve(strict=True)))
            except (OSError, RuntimeError) as exc:
                raise ExactSourceRestrictionError(
                    "A source requested a complete hash but could not be resolved."
                ) from exc
            if key not in allowed_full_hashes:
                prohibited_full_hashes.append(str(path))
                raise ExactSourceRestrictionError(
                    "The Fast scan required a complete hash outside the exact-source "
                    "qualification boundary."
                )
            return str(base_full_hasher(path))

        scan_payload["full_hasher"] = restricted_full_hasher
    result = review_inbox.scan_from_request(scan_payload)
    if prohibited_full_hashes:
        raise ExactSourceRestrictionError(
            "The complete Fast scan required a prohibited full hash for a source "
            "outside the exact-source qualification boundary."
        )
    scan_errors = [
        item
        for item in result.get("scan_errors") or []
        if isinstance(item, dict)
    ]
    if scan_errors:
        first = scan_errors[0]
        location = str(first.get("path") or "an inbox source")
        details = str(first.get("error") or "the source could not be inspected")
        raise OrchestrationError(
            f"Inbox scanning reported {len(scan_errors)} error(s); "
            f"first error for {location}: {details}"
        )
    eligible_states = set(review_inbox.ELIGIBLE_STATES)
    sources = [
        dict(item)
        for item in result.get("sources") or []
        if isinstance(item, dict)
        and str(item.get("classification") or "") in eligible_states
        and not bool(item.get("pending_batch_excluded"))
    ]
    sources.sort(
        key=lambda item: (
            str(item.get("modified_utc") or ""),
            str(item.get("path") or "").casefold(),
            int(item.get("source_id") or 0),
        )
    )
    return {**result, "eligible_sources": sources}


def _prepare_selected(payload: dict[str, Any]) -> dict[str, Any]:
    from media_manglers.core import review_preparation

    prepare = getattr(review_preparation, "prepare_selected_from_request", None)
    if not callable(prepare):
        raise OrchestrationError(
            "The bounded selected-source preparation adapter is unavailable."
        )
    result = prepare(payload)
    if not isinstance(result, dict):
        raise OrchestrationError("Selected-source preparation returned no usable result.")
    return result


def _preview_finalization(payload: dict[str, Any]) -> dict[str, Any]:
    from media_manglers.core import review_finalization

    return review_finalization.preview_from_request(payload)


def _finalize(payload: dict[str, Any]) -> dict[str, Any]:
    from media_manglers.core import review_finalization

    return review_finalization.finalize_from_request(payload)


# The Inbox's one lock (process.lock) and its stand-in for the PowerShell host's own lock live in the Inbox's
# store since Wave B1 (224): ``inbox_records.ProcessLock`` and ``inbox_records.CoordinatorOwnedLock``.


def _queue_counts(queue: dict[str, Any]) -> dict[str, int]:
    supplied = queue.get("counts") if isinstance(queue.get("counts"), dict) else {}
    return {key: max(0, int(supplied.get(key) or 0)) for key in QUEUE_COUNT_KEYS}


def _queue_batches(queue: dict[str, Any]) -> list[dict[str, Any]]:
    value = queue.get("internal_batches")
    if not isinstance(value, list):
        value = queue.get("batches")
    return [item for item in value or [] if isinstance(item, dict)]


def _queue_root(queue: dict[str, Any], ledger_path: Path) -> str:
    return str(queue.get("queue_root") or inbox_records.workspace(ledger_path))


def _attention(
    queue: dict[str, Any],
    *,
    resumable_preparation_batch_id: str = "",
) -> dict[str, Any] | None:
    values = queue.get("attention")
    if isinstance(values, list) and values:
        for item in values:
            if not isinstance(item, dict):
                return {"message": str(item)}
            states = {
                str(state)
                for state in item.get("states") or []
                if str(state)
            }
            retryable_for_active_batch = (
                bool(resumable_preparation_batch_id)
                and str(item.get("batch_id") or "")
                == resumable_preparation_batch_id
                and str(item.get("code") or "") == "batch_needs_attention"
                and bool(states)
                and states.issubset({"retryable_failure", "source_changed"})
            )
            if retryable_for_active_batch:
                continue
            return _json_safe(item)
        return None
    if isinstance(values, dict) and values:
        states = {
            str(state)
            for state in values.get("states") or []
            if str(state)
        }
        if (
            resumable_preparation_batch_id
            and str(values.get("batch_id") or "")
            == resumable_preparation_batch_id
            and str(values.get("code") or "") == "batch_needs_attention"
            and bool(states)
            and states.issubset({"retryable_failure", "source_changed"})
        ):
            return None
        return _json_safe(values)
    return None


def _safe_attention(
    code: str,
    message: str,
    *,
    details: Any = "",
    **fields: Any,
) -> dict[str, Any]:
    """Build an operator-safe attention item with diagnostics kept separate."""

    result = {
        "code": code,
        **{key: _json_safe(value) for key, value in fields.items()},
        "message": message,
    }
    diagnostic = str(details or "").strip()
    if diagnostic:
        result["details"] = diagnostic
    return result


def _exception_attention(
    code: str,
    message: str,
    exc: BaseException,
    **fields: Any,
) -> dict[str, Any]:
    return _safe_attention(
        code,
        message,
        details=f"{type(exc).__name__}: {exc}",
        **fields,
    )


def _operator_status(queue: dict[str, Any], *, fallback: str = "Done") -> str:
    status = str(queue.get("operator_status") or "")
    if status in {
        "Processing",
        "Ready for Codex review",
        "Waiting on Codex",
        "Manual review available",
        "Needs audio choice",
        "Needs attention",
        "Done",
    }:
        return status
    counts = _queue_counts(queue)
    if counts["additional_local_evidence"]:
        return "Processing"
    if counts["ready_for_codex_review"]:
        return "Ready for Codex review"
    if counts["waiting_on_codex"]:
        return "Waiting on Codex"
    if counts["manual_review"]:
        return "Manual review available"
    return fallback


def _run_summary(run: dict[str, Any] | None) -> dict[str, Any]:
    if not run:
        return {
            "run_id": "",
            "status": "idle",
            "workload_mode": "next_3",
            "new_source_limit": 3,
            "active": False,
            "selected_count": 0,
            "completed_count": 0,
            "remaining_count": 0,
            "current_batch_id": "",
            "current_source_id": None,
            "current_source_name": "",
            "current_source_ordinal": 0,
            "current_source_total": 0,
            "current_activity": "",
            "elapsed_seconds": 0.0,
            "total_elapsed_seconds": 0.0,
            "stop_requested": False,
            "resumable": False,
        }
    snapshot = list(run.get("snapshot") or [])
    selected_count = len(snapshot)
    cursor = min(selected_count, max(0, int(run.get("cursor") or 0)))
    completed_source_ids = {
        str(value)
        for value in run.get("completed_source_ids") or []
        if str(value)
    }
    # Early run-journal v1 writers persisted only the assigned-source cursor.
    # Preserve their progress on upgrade while retaining exact prepared-source
    # accounting for current journals, including partial failures.
    completed_count = min(
        selected_count,
        (
            len(completed_source_ids)
            if "completed_source_ids" in run
            else cursor
        ),
    )
    status = str(run.get("status") or "running")
    workload = (
        dict(run.get("workload") or {})
        if isinstance(run.get("workload"), dict)
        else {}
    )
    pending = (
        dict(run.get("pending_resume") or {})
        if isinstance(run.get("pending_resume"), dict)
        else {}
    )
    current_sources = list(
        pending.get("selected_sources")
        or run.get("inflight_chunk")
        or []
    )
    current_source: dict[str, Any] = {}
    for candidate in current_sources:
        if not isinstance(candidate, dict):
            continue
        source_id = str(candidate.get("source_id") or "")
        if not source_id or source_id not in completed_source_ids:
            current_source = candidate
            break
    if not current_source and current_sources and isinstance(current_sources[0], dict):
        current_source = current_sources[0]
    current_ordinal = 0
    if current_source:
        current_id = str(current_source.get("source_id") or "")
        current_path = str(current_source.get("path") or "").casefold()
        for index, item in enumerate(snapshot, start=1):
            if not isinstance(item, dict):
                continue
            if current_id and str(item.get("source_id") or "") == current_id:
                current_ordinal = index
                break
            if current_path and str(item.get("path") or "").casefold() == current_path:
                current_ordinal = index
                break
    resumable = status in {
        "running",
        "preparing",
        "waiting_external_review",
        "paused_after_current",
        "paused_soft_limit",
        "needs_audio_choice",
        "needs_attention",
        "awaiting_all_pending_confirmation",
        "awaiting_cleanup_confirmation",
        "finalizing",
    }
    summary = {
        "run_id": str(run.get("run_id") or ""),
        "status": status,
        "workload_mode": str(workload.get("mode") or "next_3"),
        "new_source_limit": workload.get("requested_limit"),
        "active": resumable,
        "selected_count": selected_count,
        "completed_count": completed_count,
        "remaining_count": max(0, selected_count - completed_count),
        "current_batch_id": str(
            pending.get("batch_id")
            or run.get("inflight_batch_id")
            or ""
        ),
        "current_source_id": current_source.get("source_id"),
        "current_source_name": str(
            current_source.get("name")
            or Path(str(current_source.get("path") or "")).name
        ),
        "current_source_ordinal": current_ordinal,
        "current_source_total": selected_count,
        "current_activity": str(run.get("current_activity") or ""),
        "elapsed_seconds": float(run.get("elapsed_seconds") or 0.0),
        "total_elapsed_seconds": float(run.get("total_elapsed_seconds") or 0.0),
        "stop_requested": bool(run.get("stop_requested")),
        "resumable": resumable,
    }
    restriction = (
        dict(run.get("exact_source_restriction") or {})
        if isinstance(run.get("exact_source_restriction"), dict)
        else {}
    )
    pending_restriction = [
        value
        for value in run.get("pending_exact_source_paths") or []
        if str(value).strip()
    ]
    if restriction or pending_restriction:
        summary["exact_source_restriction"] = True
        summary["exact_source_restriction_count"] = len(
            restriction.get("selected_source_ids") or pending_restriction
        )
    return summary


def _continuation(run: dict[str, Any] | None) -> str:
    if not run:
        return ""
    # Keep the token stable across harmless queue refreshes and timestamp
    # updates, while invalidating it when the actionable run gate changes.
    basis = {
        "run_id": str(run.get("run_id") or ""),
        "status": str(run.get("status") or ""),
        "cursor": int(run.get("cursor") or 0),
        "all_pending_confirmation_token": str(
            run.get("all_pending_confirmation_token") or ""
        ),
        "cleanup_preview_token": str(run.get("cleanup_preview_token") or ""),
        "stop_requested": bool(run.get("stop_requested")),
    }
    return _sha256(basis)


def _result(
    *,
    action: str,
    ledger_path: Path,
    queue: dict[str, Any],
    run: dict[str, Any] | None,
    operator_status: str | None = None,
    continue_automatically: bool = False,
    next_action: dict[str, Any] | None = None,
    attention: dict[str, Any] | None = None,
    audio_choice: dict[str, Any] | None = None,
    cleanup_confirmation: dict[str, Any] | None = None,
    all_pending_confirmation: dict[str, Any] | None = None,
    recovery: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    workload = dict(run.get("workload") or {}) if run else {
        "mode": "next_3",
        "requested_limit": 3,
        "eligible_snapshot_count": 0,
    }
    return {
        "contract_version": CONTRACT_VERSION,
        "document_type": "review_media_inbox_process_result",
        "action": action,
        "operator_status": operator_status or _operator_status(queue),
        "queue_counts": _queue_counts(queue),
        "queue_root": _queue_root(queue, ledger_path),
        "queue_prompt_path": str(queue.get("queue_prompt_path") or ""),
        "queue_index_path": str(queue.get("queue_index_path") or ""),
        "manual_review": _json_safe(queue.get("manual_review") or []),
        "workload": workload,
        "run_state": _run_summary(run),
        "attention": attention,
        "audio_choice": audio_choice,
        "cleanup_confirmation": cleanup_confirmation,
        "all_pending_confirmation": all_pending_confirmation,
        "continuation": _continuation(run),
        "continue_automatically": bool(continue_automatically),
        "next_action": _json_safe(next_action) if next_action else None,
        "recovery": _json_safe(recovery or []),
    }


def _archive_run(paths: dict[str, Path], run: dict[str, Any]) -> None:
    paths["completed"].mkdir(parents=True, exist_ok=True)
    destination = paths["completed"] / f"{run['run_id']}.json"
    _write_journal(destination, run)
    # 224 (Wave B2a): through the one antivirus-safe removal, as every Inbox delete.
    safe_write.remove(paths["active"], wait=safe_write.INBOX_WAIT_SECONDS)
    safe_write.remove(paths["stop"], wait=safe_write.INBOX_WAIT_SECONDS)


def _write_active(paths: dict[str, Path], run: dict[str, Any]) -> None:
    run["updated_utc"] = _utc_now()
    _write_journal(paths["active"], run)


def _normalise_workload(payload: dict[str, Any]) -> tuple[str, int | None]:
    raw = str(payload.get("workload_mode") or payload.get("workload") or "next_3")
    token = raw.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "next3": "next_3",
        "next_3": "next_3",
        "upton": "up_to_n",
        "up_to_n": "up_to_n",
        "allpending": "all_pending",
        "all_pending": "all_pending",
    }
    mode = aliases.get(token)
    if mode not in WORKLOAD_LIMITS:
        raise ValueError("workload_mode must be next_3, up_to_n, or all_pending.")
    if mode == "next_3":
        return mode, 3
    if mode == "all_pending":
        return mode, None
    value = payload.get("new_source_limit", payload.get("up_to_n", 10))
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("new_source_limit must be a positive integer.")
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped.isdigit():
            raise ValueError("new_source_limit must be a positive integer.")
        limit = int(value)
    else:
        limit = value
    if limit < 1 or limit > MAX_UP_TO_N:
        raise ValueError(f"new_source_limit must be between 1 and {MAX_UP_TO_N}.")
    return mode, limit


def _normalise_exact_source_paths(payload: dict[str, Any]) -> list[str]:
    """Return a deduplicated absolute run-scoped exact-source request."""

    cli = payload.get("cli") if isinstance(payload.get("cli"), dict) else {}
    value = payload.get("exact_source_paths", cli.get("exact_source_paths"))
    if value is None or value == "":
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = list(value)
    else:
        raise ExactSourceRestrictionError(
            "exact_source_paths must be a list of absolute local source paths."
        )

    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw or "").strip()
        if not text:
            continue
        path = Path(text)
        if not path.is_absolute():
            raise ExactSourceRestrictionError(
                "Every exact-source restriction must be an absolute local path."
            )
        absolute = os.path.abspath(str(path))
        key = os.path.normcase(absolute)
        if key in seen:
            continue
        seen.add(key)
        result.append(absolute)
    return result


def _restriction_paths_for_initialization(
    run: dict[str, Any] | None,
    payload: dict[str, Any],
) -> list[str]:
    incoming = _normalise_exact_source_paths(payload)
    pending = [
        str(value)
        for value in (run or {}).get("pending_exact_source_paths") or []
        if str(value).strip()
    ]
    if incoming and pending:
        incoming_keys = {os.path.normcase(os.path.abspath(value)) for value in incoming}
        pending_keys = {os.path.normcase(os.path.abspath(value)) for value in pending}
        if incoming_keys != pending_keys:
            raise ExactSourceRestrictionError(
                "The exact-source restriction does not match the saved Process run."
            )
    return incoming or pending


def _payload_with_pending_restriction(
    run: dict[str, Any] | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Restore a journaled restriction before any resumed inventory scan."""

    if _normalise_exact_source_paths(payload):
        return payload
    pending = [
        str(value)
        for value in (run or {}).get("pending_exact_source_paths") or []
        if str(value).strip()
    ]
    if not pending:
        return payload
    return {**payload, "exact_source_paths": pending}


def _verify_active_restriction_request(
    run: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    incoming = _normalise_exact_source_paths(payload)
    if not incoming:
        return
    restriction = (
        dict(run.get("exact_source_restriction") or {})
        if isinstance(run.get("exact_source_restriction"), dict)
        else {}
    )
    if not restriction:
        pending = [
            str(value)
            for value in run.get("pending_exact_source_paths") or []
            if str(value).strip()
        ]
        if not pending:
            raise ExactSourceRestrictionError(
                "An active unrestricted Process run cannot accept an exact-source restriction."
            )
        stored = pending
    else:
        stored = [
            str(value)
            for value in restriction.get("requested_paths") or []
            if str(value).strip()
        ]
    incoming_keys = {os.path.normcase(os.path.abspath(value)) for value in incoming}
    stored_keys = {os.path.normcase(os.path.abspath(value)) for value in stored}
    if incoming_keys != stored_keys:
        raise ExactSourceRestrictionError(
            "The exact-source restriction does not match the saved Process run."
        )


def _source_within_configured_roots(
    source: Path,
    roots: list[Path],
    *,
    recurse: bool,
) -> bool:
    for root in roots:
        if root.is_file():
            if os.path.normcase(str(source)) == os.path.normcase(str(root)):
                return True
            continue
        try:
            relative = source.relative_to(root)
        except ValueError:
            continue
        if recurse or len(relative.parts) == 1:
            return True
    return False


def _restricted_snapshot(
    payload: dict[str, Any],
    inventory: dict[str, Any],
    *,
    run: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Resolve an optional exact-source request against the complete scan."""

    requested = _restriction_paths_for_initialization(run, payload)
    eligible = [
        dict(item)
        for item in inventory.get("eligible_sources") or []
        if isinstance(item, dict)
    ]
    if not requested:
        mode, limit = _normalise_workload(payload)
        return (eligible if limit is None else eligible[:limit]), None

    mode, limit = _normalise_workload(payload)
    if mode == "all_pending":
        raise ExactSourceRestrictionError(
            "An exact-source restriction cannot be combined with All pending."
        )

    settings = (
        dict(inventory.get("settings") or {})
        if isinstance(inventory.get("settings"), dict)
        else {}
    )
    configured_values = settings.get("source_folders") or payload.get("source_folders")
    if not isinstance(configured_values, (list, tuple)) or not configured_values:
        raise ExactSourceRestrictionError(
            "The complete scan did not report configured source roots."
        )
    recurse = bool(settings.get("recurse", payload.get("recurse", True)))
    configured_roots: list[Path] = []
    for value in configured_values:
        try:
            configured_roots.append(Path(str(value)).expanduser().resolve(strict=True))
        except (OSError, RuntimeError) as exc:
            raise ExactSourceRestrictionError(
                "A configured source root could not be resolved after the scan."
            ) from exc

    scanned = [
        dict(item)
        for item in inventory.get("sources") or []
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    ]
    scanned_by_path = {
        os.path.normcase(os.path.abspath(str(item["path"]))): item for item in scanned
    }
    eligible_ids = {
        int(item["source_id"])
        for item in eligible
        if isinstance(item.get("source_id"), int)
        and not isinstance(item.get("source_id"), bool)
        and int(item["source_id"]) > 0
    }

    matched_ids: set[int] = set()
    canonical_requests: list[str] = []
    bound_by_source_id: dict[int, dict[str, Any]] = {}
    canonical_seen: set[str] = set()
    for requested_path in requested:
        requested_key = os.path.normcase(os.path.abspath(requested_path))
        source = scanned_by_path.get(requested_key)
        if source is None:
            raise ExactSourceRestrictionError(
                "A requested exact source was not present in the complete configured-folder scan."
            )
        try:
            canonical_requested = Path(requested_path).resolve(strict=True)
            canonical_scanned = Path(str(source["path"])).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ExactSourceRestrictionError(
                "A requested exact source could not be resolved after the scan."
            ) from exc
        canonical_key = os.path.normcase(str(canonical_requested))
        if canonical_key in canonical_seen:
            continue
        canonical_seen.add(canonical_key)
        if canonical_key != os.path.normcase(str(canonical_scanned)):
            raise ExactSourceRestrictionError(
                "A requested exact source did not resolve to the canonical scanned path."
            )
        if not _source_within_configured_roots(
            canonical_scanned,
            configured_roots,
            recurse=recurse,
        ):
            raise ExactSourceRestrictionError(
                "A requested exact source is outside the configured source roots or recurse boundary."
            )

        source_id = source.get("source_id")
        if (
            isinstance(source_id, bool)
            or not isinstance(source_id, int)
            or source_id <= 0
        ):
            raise ExactSourceRestrictionError(
                "A requested exact source is missing its scanned source identity."
            )
        if source_id not in eligible_ids or bool(source.get("pending_batch_excluded")):
            lifecycle = str(source.get("classification") or "unknown")
            raise ExactSourceRestrictionError(
                "A requested exact source is not eligible for this Process run "
                f"(current lifecycle: {lifecycle})."
            )
        size_bytes = source.get("size_bytes")
        modified_ns = source.get("modified_ns")
        if (
            isinstance(size_bytes, bool)
            or not isinstance(size_bytes, int)
            or isinstance(modified_ns, bool)
            or not isinstance(modified_ns, int)
        ):
            raise ExactSourceRestrictionError(
                "A requested exact source is missing stable scan metadata."
            )
        try:
            current = canonical_scanned.stat()
        except OSError as exc:
            raise ExactSourceRestrictionError(
                "A requested exact source could not be rechecked before snapshot creation."
            ) from exc
        if current.st_size != size_bytes or current.st_mtime_ns != modified_ns:
            raise ExactSourceRestrictionError(
                "A requested exact source changed between the scan and snapshot creation."
            )

        identity = str(source.get("identity") or "").strip()
        if not identity:
            raise ExactSourceRestrictionError(
                "A requested exact source is missing its scanned identity."
            )
        matched_ids.add(source_id)
        canonical_requests.append(str(canonical_scanned))
        bound = {
            "source_id": source_id,
            "identity": identity,
            "path": str(canonical_scanned),
            "size_bytes": size_bytes,
            "modified_ns": modified_ns,
        }
        for key in ("sampled_sha256", "content_sha256"):
            value = str(source.get(key) or "").strip()
            if value:
                bound[key] = value
        bound_by_source_id[source_id] = bound

    selected = [
        item for item in eligible if int(item.get("source_id") or 0) in matched_ids
    ]
    if len(selected) != len(matched_ids):
        raise ExactSourceRestrictionError(
            "The restricted scanned sources could not be ordered safely."
        )
    if limit is not None and len(selected) > limit:
        raise ExactSourceRestrictionError(
            "The exact-source restriction exceeds the selected workload limit."
        )
    bound_sources = [
        bound_by_source_id[int(item["source_id"])]
        for item in selected
    ]

    restriction = {
        "requested_paths": canonical_requests,
        "selected_source_ids": [int(item["source_id"]) for item in selected],
        "bound_sources": bound_sources,
        "selection_sha256": _sha256(bound_sources),
        "scanned_inventory_count": int(
            inventory.get("inventory_count")
            if isinstance(inventory.get("inventory_count"), int)
            and not isinstance(inventory.get("inventory_count"), bool)
            else len(scanned)
        ),
        "scan_classification_counts": _json_safe(
            inventory.get("classification_counts") or {}
        ),
    }
    return selected, restriction


def _restricted_run_is_terminal(ledger_path: Path, run: dict[str, Any]) -> bool:
    restriction = (
        dict(run.get("exact_source_restriction") or {})
        if isinstance(run.get("exact_source_restriction"), dict)
        else {}
    )
    source_ids = [
        int(value)
        for value in restriction.get("selected_source_ids") or []
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    ]
    if not source_ids:
        return True
    placeholders = ",".join("?" for _value in source_ids)
    # A reader (224, F4): with no ledger, none of the run's recordings has finished, and none is made here.
    connection = inbox_records.connect_read_only(ledger_path)
    if connection is None:
        return False
    try:
        rows = connection.execute(
            f"SELECT source_id, lifecycle_state FROM inbox_sources WHERE source_id IN ({placeholders})",
            source_ids,
        ).fetchall()
    finally:
        connection.close()
    states = {int(row[0]): str(row[1] or "") for row in rows}
    terminal = {
        "finalized_no_findings",
        "finalized_with_findings",
        "needs_manual_review",
    }
    return len(states) == len(source_ids) and all(
        states.get(source_id) in terminal for source_id in source_ids
    )


def _new_run(
    payload: dict[str, Any],
    inventory: dict[str, Any],
) -> dict[str, Any]:
    mode, limit = _normalise_workload(payload)
    eligible = list(inventory.get("eligible_sources") or [])
    selected, restriction = _restricted_snapshot(payload, inventory)
    run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    status = "awaiting_all_pending_confirmation" if mode == "all_pending" and selected else "running"
    run = {
        "run_journal_version": RUN_JOURNAL_VERSION,
        "run_id": run_id,
        "created_utc": _utc_now(),
        "updated_utc": _utc_now(),
        "status": status,
        "workload": {
            "mode": mode,
            "requested_limit": limit,
            "eligible_snapshot_count": len(eligible),
        },
        "workload_pending_initialization": False,
        "snapshot": _json_safe(selected),
        "scan_settings": _json_safe(inventory.get("settings") or {}),
        "cursor": 0,
        "completed_source_ids": [],
        "inflight_chunk": [],
        "inflight_batch_id": "",
        "batches": [],
        "elapsed_seconds": 0.0,
        "total_elapsed_seconds": 0.0,
        "stop_requested": False,
        "last_queue_counts": {},
        "cleanup_decision": None,
    }
    if restriction is not None:
        run["exact_source_restriction"] = restriction
        run["workload"]["restricted_source_count"] = len(selected)
        run["workload"]["scanned_inventory_count"] = restriction[
            "scanned_inventory_count"
        ]
    if mode == "all_pending" and selected:
        run["all_pending_confirmation_token"] = _sha256(
            {
                "run_id": run_id,
                "sources": [
                    {
                        "source_id": item.get("source_id"),
                        "identity": item.get("identity"),
                        "size_bytes": item.get("size_bytes"),
                        "modified_utc": item.get("modified_utc"),
                    }
                    for item in selected
                ],
            }
        )
    return run


def _initialise_pending_workload(
    run: dict[str, Any],
    payload: dict[str, Any],
    inventory: dict[str, Any],
) -> None:
    """Attach the operator-selected new-source workload after existing work."""

    initialization_payload = dict(payload)
    pending_restriction = [
        str(value)
        for value in run.get("pending_exact_source_paths") or []
        if str(value).strip()
    ]
    saved_workload = (
        dict(run.get("workload") or {})
        if isinstance(run.get("workload"), dict)
        else {}
    )
    if pending_restriction:
        saved_mode = str(saved_workload.get("mode") or "").strip()
        if saved_mode:
            initialization_payload["workload_mode"] = saved_mode
        if saved_mode == "up_to_n":
            initialization_payload["new_source_limit"] = saved_workload.get(
                "requested_limit"
            )
    mode, limit = _normalise_workload(initialization_payload)
    eligible = list(inventory.get("eligible_sources") or [])
    selected, restriction = _restricted_snapshot(
        initialization_payload,
        inventory,
        run=run,
    )
    run["workload"] = {
        "mode": mode,
        "requested_limit": limit,
        "eligible_snapshot_count": len(eligible),
    }
    if restriction is not None:
        run["exact_source_restriction"] = restriction
        run["workload"]["restricted_source_count"] = len(selected)
        run["workload"]["scanned_inventory_count"] = restriction[
            "scanned_inventory_count"
        ]
    else:
        run.pop("exact_source_restriction", None)
    run.pop("pending_exact_source_paths", None)
    run["snapshot"] = _json_safe(selected)
    run["scan_settings"] = _json_safe(inventory.get("settings") or {})
    run["cursor"] = 0
    run["completed_source_ids"] = []
    run["inflight_chunk"] = []
    run["inflight_batch_id"] = ""
    run["workload_pending_initialization"] = False
    run.pop("all_pending_confirmation_token", None)
    if mode == "all_pending" and selected:
        run["status"] = "awaiting_all_pending_confirmation"
        run["all_pending_confirmation_token"] = _sha256(
            {
                "run_id": str(run.get("run_id") or ""),
                "sources": [
                    {
                        "source_id": item.get("source_id"),
                        "identity": item.get("identity"),
                        "size_bytes": item.get("size_bytes"),
                        "modified_utc": item.get("modified_utc"),
                    }
                    for item in selected
                ],
            }
        )
    else:
        run["status"] = "running"


def _settings_from_payload(
    payload: dict[str, Any],
    ledger_path: Path,
) -> dict[str, Any]:
    """Build the minimum persisted scan settings needed for exact recovery."""

    cli = payload.get("cli") if isinstance(payload.get("cli"), dict) else {}
    settings: dict[str, Any] = {}
    for key in (
        "source_folders",
        "evidence_root",
        "scratch_root",
        "local_work_root",
        "recurse",
        "dedupe_mode",
        "order",
    ):
        value = payload.get(key, cli.get(key))
        if value is not None:
            settings[key] = _json_safe(value)
    settings.update(
        {
            "ledger_path": str(ledger_path),
            "order": "oldest",
            "dedupe_mode": str(settings.get("dedupe_mode") or "Fast"),
            "max_files": HIDDEN_BATCH_SIZE,
            "pending_batch_limit": MAX_UP_TO_N,
            "max_duration_minutes": SOFT_LIMIT_MINUTES,
        }
    )
    return settings


def _new_recovery_run(
    payload: dict[str, Any],
    ledger_path: Path,
    batch: dict[str, Any],
) -> dict[str, Any]:
    """Create a run that resumes existing work before initializing its budget."""

    run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    batch_id = str(batch.get("batch_id") or "")
    mode, limit = _normalise_workload(payload)
    run = {
        "run_journal_version": RUN_JOURNAL_VERSION,
        "run_id": run_id,
        "created_utc": _utc_now(),
        "updated_utc": _utc_now(),
        "status": (
            "needs_audio_choice"
            if str(batch.get("status") or "") == "needs_audio_confirmation"
            else "running"
        ),
        "workload": {
            "mode": mode,
            "requested_limit": limit,
            "eligible_snapshot_count": 0,
        },
        "workload_pending_initialization": True,
        "snapshot": [],
        "scan_settings": _settings_from_payload(payload, ledger_path),
        "cursor": 0,
        "completed_source_ids": [],
        "inflight_chunk": [],
        "inflight_batch_id": "",
        "pending_resume": {
            "batch_id": batch_id,
            "selected_sources": [],
        },
        "batches": [
            {
                "batch_id": batch_id,
                "source_count": max(0, int(batch.get("source_count") or 0)),
                "status": str(batch.get("status") or ""),
            }
        ],
        "elapsed_seconds": 0.0,
        "total_elapsed_seconds": 0.0,
        "stop_requested": False,
        "last_queue_counts": {},
        "cleanup_decision": None,
    }
    requested = _normalise_exact_source_paths(payload)
    if requested:
        run["pending_exact_source_paths"] = requested
    return run


def _new_maintenance_run(
    payload: dict[str, Any],
    ledger_path: Path,
    queue: dict[str, Any],
) -> dict[str, Any]:
    """Create a run that finishes queue work before initializing its budget."""

    run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    mode, limit = _normalise_workload(payload)
    run = {
        "run_journal_version": RUN_JOURNAL_VERSION,
        "run_id": run_id,
        "created_utc": _utc_now(),
        "updated_utc": _utc_now(),
        "status": "running",
        "workload": {
            "mode": mode,
            "requested_limit": limit,
            "eligible_snapshot_count": 0,
        },
        "workload_pending_initialization": True,
        "snapshot": [],
        "scan_settings": _settings_from_payload(payload, ledger_path),
        "cursor": 0,
        "completed_source_ids": [],
        "inflight_chunk": [],
        "inflight_batch_id": "",
        "batches": [],
        "elapsed_seconds": 0.0,
        "total_elapsed_seconds": 0.0,
        "stop_requested": False,
        "last_queue_counts": _queue_counts(queue),
        "cleanup_decision": None,
    }
    requested = _normalise_exact_source_paths(payload)
    if requested:
        run["pending_exact_source_paths"] = requested
    return run


def _adopt_mutable_batch(
    run: dict[str, Any],
    batch: dict[str, Any],
) -> None:
    """Attach interrupted local preparation to the active exact run."""

    batch_id = str(batch.get("batch_id") or "")
    if not batch_id:
        return
    pending = (
        dict(run.get("pending_resume") or {})
        if isinstance(run.get("pending_resume"), dict)
        else {}
    )
    if str(pending.get("batch_id") or "") == batch_id:
        return
    selected = []
    consumes_assigned_quota = str(run.get("inflight_batch_id") or "") == batch_id
    if consumes_assigned_quota:
        selected = list(run.get("inflight_chunk") or [])
    run["pending_resume"] = {
        "batch_id": batch_id,
        "selected_sources": _json_safe(selected),
        "consume_assigned_quota": consumes_assigned_quota,
    }
    if str(batch.get("status") or "") == "needs_audio_confirmation":
        run["status"] = "needs_audio_choice"


def _disk_free(path_value: str, probe: Callable[[Path], int] | None) -> int | None:
    if not path_value:
        return None
    path = Path(path_value)
    try:
        if probe is not None:
            return int(probe(path))
        existing = path
        while not existing.exists() and existing != existing.parent:
            existing = existing.parent
        return int(shutil.disk_usage(existing).free)
    except (OSError, ValueError):
        return None


def _recent_duration_estimate(
    ledger_path: Path,
    payload: dict[str, Any],
    source_count: int,
) -> dict[str, Any]:
    supplied = payload.get("recent_preparation_durations_seconds")
    durations: list[float] = []
    if isinstance(supplied, list):
        for value in supplied:
            try:
                duration = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(duration) and duration >= 0.0:
                durations.append(duration)
    else:
        try:
            connection = inbox_records.connect_read_only(ledger_path)
            rows = []
            if connection is not None:
                # 224, F4: closed whatever the query does.
                try:
                    rows = connection.execute(
                        """
                        SELECT started_utc, completed_utc
                        FROM inbox_attempts
                        WHERE attempt_type = 'prepare' AND status = 'prepared'
                          AND started_utc IS NOT NULL AND completed_utc IS NOT NULL
                        ORDER BY attempt_id DESC LIMIT 21
                        """
                    ).fetchall()
                finally:
                    connection.close()
            for started, completed in rows:
                start = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
                end = datetime.fromisoformat(str(completed).replace("Z", "+00:00"))
                if end >= start:
                    durations.append((end - start).total_seconds())
        except (OSError, sqlite3.Error, TypeError, ValueError):
            durations = []
    if len(durations) < 3:
        return {
            "estimated_seconds": None,
            "basis": "No reliable time estimate yet",
        }
    median_seconds = float(statistics.median(durations))
    return {
        "estimated_seconds": median_seconds * source_count,
        "median_source_seconds": median_seconds,
        "sample_count": len(durations),
        "basis": "Median recent successful preparation duration",
    }


def _all_pending_confirmation(
    ledger_path: Path,
    payload: dict[str, Any],
    run: dict[str, Any],
) -> dict[str, Any]:
    from media_manglers.core import review_preparation

    sources = list(run.get("snapshot") or [])
    total_bytes = sum(max(0, int(item.get("size_bytes") or 0)) for item in sources)
    largest_source = max(
        (item for item in sources if isinstance(item, dict)),
        key=lambda item: max(0, int(item.get("size_bytes") or 0)),
        default={},
    )
    largest = max(0, int(largest_source.get("size_bytes") or 0))
    # Discovery intentionally stays lightweight, so duration is normally not
    # available yet. Use the canonical soft-run boundary as a conservative
    # planning duration and the same storage estimator enforced immediately
    # before each source after media probing.
    duration_seconds = max(
        0.0,
        float(
            largest_source.get("duration_seconds")
            or (SOFT_LIMIT_MINUTES * 60.0)
        ),
    )
    storage = review_preparation.estimate_storage(
        largest,
        duration_seconds,
        review_preparation.timeline_frame_count(duration_seconds),
        0,
    )
    scan_settings = (
        dict(run.get("scan_settings") or {})
        if isinstance(run.get("scan_settings"), dict)
        else {}
    )
    scratch = str(
        payload.get("scratch_root")
        or payload.get("local_work_root")
        or scan_settings.get("scratch_root")
        or ""
    )
    # Prepared packages are retained beside the canonical ledger, regardless
    # of a legacy evidence_root setting carried for compatibility.
    evidence = str(inbox_records.workspace(ledger_path))
    probe = payload.get("space_probe") if callable(payload.get("space_probe")) else None
    return {
        "token": str(run.get("all_pending_confirmation_token") or ""),
        "eligible_source_count": len(sources),
        "total_source_bytes": total_bytes,
        "scratch_free_bytes": _disk_free(scratch, probe),
        "evidence_free_bytes": _disk_free(evidence, probe),
        "estimated_peak_temporary_bytes": storage["scratch_required_bytes"],
        "time_estimate": _recent_duration_estimate(ledger_path, payload, len(sources)),
        "message": (
            f"All pending includes {len(sources)} source(s). "
            "Confirm before any new source preparation begins."
        ),
    }


def _decision(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("decision")
    return dict(value) if isinstance(value, dict) else {}


def _decision_authorized(
    payload: dict[str, Any],
    run: dict[str, Any],
    *,
    expected_type: str,
    expected_token: str,
) -> dict[str, Any] | None:
    decision = _decision(payload)
    if not decision:
        return None
    if str(payload.get("continuation") or "") != _continuation(run):
        raise OrchestrationError("The Process continuation changed before the operator decision was applied.")
    if str(decision.get("type") or "") != expected_type:
        raise OrchestrationError(f"The Process decision must have type {expected_type!r}.")
    if str(decision.get("token") or "") != expected_token:
        raise OrchestrationError("The Process decision token does not match the current confirmation.")
    return decision


def _audio_choice(queue: dict[str, Any]) -> dict[str, Any] | None:
    for batch in _queue_batches(queue):
        if not isinstance(batch, dict) or str(batch.get("status") or "") != "needs_audio_confirmation":
            continue
        choice: dict[str, Any] = {
            "batch_id": str(batch.get("batch_id") or ""),
            "batch_path": str(batch.get("batch_path") or ""),
        }
        manifest_path = Path(choice["batch_path"]) / "batch-manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            blocked = [
                item
                for item in manifest.get("blocked_sources") or []
                if isinstance(item, dict) and str(item.get("state") or "") == "needs_audio_confirmation"
            ]
            if not blocked:
                continue
            blocked_source = blocked[0]
            # A saved pre-audibility confirmation is deliberately stale.  The
            # normal preparation resume path must re-inspect it before the UI
            # can offer any track choice.
            if int(
                blocked_source.get("audibility_contract_version") or 0
            ) < 1:
                continue
            if (
                str(
                    blocked_source.get("audio_audibility_state")
                    or ""
                )
                != "audible_candidates"
            ):
                continue
            choice.update(_json_safe(blocked_source))
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
            continue
        choice["token"] = _sha256(
            {
                "batch_id": choice.get("batch_id"),
                "source_id": choice.get("source_id"),
                "layout_fingerprint": choice.get("layout_fingerprint"),
            }
        )
        return choice
    return None


def _preliminary_sha(ledger_path: Path, batch_id: str) -> str:
    connection = inbox_records.connect_read_only(ledger_path)
    if connection is None:
        return ""
    try:
        row = connection.execute(
            """
            SELECT settings_hash
            FROM inbox_attempts
            WHERE batch_id = ?
              AND attempt_type = 'preliminary_findings_import'
              AND status = 'accepted'
            ORDER BY attempt_id DESC LIMIT 1
            """,
            (batch_id,),
        ).fetchone()
    finally:
        connection.close()
    return str(row[0] or "") if row else ""


def _targeted_action(queue: dict[str, Any], ledger_path: Path) -> dict[str, Any] | None:
    for batch in _queue_batches(queue):
        if not isinstance(batch, dict) or str(batch.get("status") or "") != "preliminary_findings_received":
            continue
        batch_id = str(batch.get("batch_id") or "")
        return {
            "type": "render_targeted",
            "batch_id": batch_id,
            "batch_path": str(batch.get("batch_path") or ""),
            "preliminary_submission_sha256": _preliminary_sha(ledger_path, batch_id),
        }
    return None


def _recover_finalizing(queue: dict[str, Any], ledger_path: Path) -> bool:
    from media_manglers.core import review_finalization

    recovered = False
    for batch in _queue_batches(queue):
        if not isinstance(batch, dict) or str(batch.get("status") or "") != "finalizing":
            continue
        batch_path = Path(str(batch.get("batch_path") or ""))
        # 224 (F10): the journal the records name for this batch, not the last file name.
        try:
            recorded = review_finalization.recorded_journal(ledger_path, str(batch.get("batch_id") or ""), batch_path)
        except review_finalization.FinalizationError as exc:
            raise OrchestrationError(str(exc)) from exc
        if recorded is None:
            raise OrchestrationError(
                f"Batch {batch.get('batch_id')!r} is finalizing but has no recoverable journal."
            )
        _journal_path, plan_sha = recorded
        plan_path = batch_path / ".finalization" / f"plan-{plan_sha[:24]}.json"
        _finalize(
            {
                "ledger_path": str(ledger_path),
                "plan_path": str(plan_path),
                "plan_sha256": plan_sha,
                "operator_confirmed": True,
            }
        )
        recovered = True
    return recovered


def _recover_preparation_staging(
    queue: dict[str, Any],
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Classify interrupted preparation staging without scanning source media."""

    scratch_value = str(
        payload.get("scratch_root") or payload.get("local_work_root") or ""
    ).strip()
    if not scratch_value:
        return []
    from media_manglers.core import review_preparation

    actions: list[dict[str, Any]] = []
    scratch_root = Path(scratch_value)
    for batch in _queue_batches(queue):
        if not isinstance(batch, dict) or str(batch.get("status") or "") not in {
            "preparing",
            "needs_audio_confirmation",
        }:
            continue
        batch_root = Path(str(batch.get("batch_path") or ""))
        if not batch_root.is_dir():
            continue
        recovered = review_preparation.recover_staging(batch_root, scratch_root)
        for item in recovered:
            actions.append(
                {
                    "batch_id": str(batch.get("batch_id") or ""),
                    **_json_safe(item),
                }
            )
    return actions


def _cleanup_previews(
    queue: dict[str, Any],
    ledger_path: Path,
    *,
    retention_policy: str,
) -> list[dict[str, Any]]:
    previews: list[dict[str, Any]] = []
    for batch in _queue_batches(queue):
        if not isinstance(batch, dict) or str(batch.get("status") or "") != "results_received":
            continue
        previews.append(
            _preview_finalization(
                {
                    "ledger_path": str(ledger_path),
                    "expected_batch_id": str(batch.get("batch_id") or ""),
                    "batch_path": str(batch.get("batch_path") or ""),
                    "retention_policy": retention_policy,
                }
            )
        )
    previews.sort(key=lambda item: str(item.get("batch_id") or ""))
    return previews


def _cleanup_token(previews: list[dict[str, Any]]) -> str:
    return _sha256(
        [
            {
                "batch_id": item.get("batch_id"),
                "plan_sha256": item.get("plan_sha256"),
                "disposable_bytes": item.get("disposable_bytes"),
            }
            for item in previews
        ]
    )


def _execute_cleanup(
    ledger_path: Path,
    compact_previews: list[dict[str, Any]],
    choice: str,
    *,
    stop_requested: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    if choice not in {"keep_generated", "remove_temporary"}:
        raise OrchestrationError("Cleanup choice must be keep_generated or remove_temporary.")
    previews = compact_previews
    if choice == "keep_generated":
        queue = {
            "batches": [
                {
                    "batch_id": item["batch_id"],
                    "batch_path": item["batch_root"],
                    "status": "results_received",
                }
                for item in compact_previews
            ]
        }
        previews = _cleanup_previews(queue, ledger_path, retention_policy="keep_generated")
    results: list[dict[str, Any]] = []
    for preview in previews:
        results.append(
            _finalize(
                {
                    "ledger_path": str(ledger_path),
                    "plan_path": str(preview["plan_path"]),
                    "plan_sha256": str(preview["plan_sha256"]),
                    "operator_confirmed": True,
                }
            )
        )
        if stop_requested is not None and stop_requested():
            break
    return results


def _ordered_subset(values: list[str], complete: list[str]) -> bool:
    if not values:
        return True
    position = 0
    for value in values:
        try:
            position = complete.index(value, position) + 1
        except ValueError:
            return False
    return True


def _handle_external_work(
    *,
    ledger_path: Path,
    payload: dict[str, Any],
    paths: dict[str, Path],
    queue: dict[str, Any],
    run: dict[str, Any] | None,
    audio_decision_applied: bool = False,
    resumable_preparation_batch_id: str = "",
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any]]:
    """Handle one highest-priority external/recovery action.

    Returns ``(terminal_result, possibly_updated_run, possibly_updated_queue)``.
    """

    if run is None and _normalise_exact_source_paths(payload):
        run = _new_maintenance_run(payload, ledger_path, queue)
        _write_active(paths, run)

    attention = _attention(
        queue,
        resumable_preparation_batch_id=resumable_preparation_batch_id,
    )
    if attention is not None:
        if run:
            run["status"] = "needs_attention"
            _write_active(paths, run)
        return (
            _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status="Needs attention",
                attention=attention,
            ),
            run,
            queue,
        )

    if run is not None and _stop_was_requested(paths, payload):
        run["status"] = "paused_after_current"
        run["stop_requested"] = True
        _write_active(paths, run)
        return (
            _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status="Processing",
            ),
            run,
            queue,
        )

    audio = None if audio_decision_applied else _audio_choice(queue)
    if audio is not None:
        if run:
            run["status"] = "needs_audio_choice"
            _write_active(paths, run)
        return (
            _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status="Needs audio choice",
                audio_choice=audio,
            ),
            run,
            queue,
        )

    targeted = _targeted_action(queue, ledger_path)
    if targeted is not None:
        if run is None:
            run = _new_maintenance_run(payload, ledger_path, queue)
            _write_active(paths, run)
        if _stop_was_requested(paths, payload):
            run["status"] = "paused_after_current"
            run["stop_requested"] = True
            _write_active(paths, run)
            return (
                _result(
                    action="process",
                    ledger_path=ledger_path,
                    queue=queue,
                    run=run,
                    operator_status="Processing",
                ),
                run,
                queue,
            )
        return (
            _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status="Processing",
                continue_automatically=True,
                next_action=targeted,
            ),
            run,
            queue,
        )

    previews = _cleanup_previews(queue, ledger_path, retention_policy="compact")
    if not previews:
        return None, run, queue

    total_disposable = sum(int(item.get("disposable_bytes") or 0) for item in previews)
    current_token = _cleanup_token(previews)
    current_plan_sha256 = [str(item["plan_sha256"]) for item in previews]
    if run is None:
        run = _new_maintenance_run(payload, ledger_path, queue)
    if _stop_was_requested(paths, payload):
        run["status"] = "paused_after_current"
        run["stop_requested"] = True
        _write_active(paths, run)
        return (
            _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status="Processing",
            ),
            run,
            queue,
        )

    recorded_decision = (
        dict(run.get("cleanup_decision") or {})
        if isinstance(run.get("cleanup_decision"), dict)
        else {}
    )
    recorded_plans = [
        str(value)
        for value in run.get("cleanup_plan_sha256") or []
        if str(value)
    ]
    recorded_token = str(recorded_decision.get("token") or "")
    can_reuse_recorded = (
        bool(recorded_decision)
        and recorded_token == str(run.get("cleanup_preview_token") or "")
        and str(recorded_decision.get("choice") or "")
        in {"keep_generated", "remove_temporary"}
        and _ordered_subset(current_plan_sha256, recorded_plans)
    )
    if can_reuse_recorded:
        token = recorded_token
        decision: dict[str, Any] | None = recorded_decision
    else:
        token = current_token
        run["cleanup_preview_token"] = token
        run["cleanup_plan_sha256"] = current_plan_sha256
        if recorded_decision:
            run["cleanup_decision"] = None
        decision = _decision_authorized(
            payload,
            run,
            expected_type="cleanup",
            expected_token=token,
        )
    if total_disposable > 0 and decision is None:
        run["status"] = "awaiting_cleanup_confirmation"
        _write_active(paths, run)
        confirmation = {
            "token": token,
            "batch_count": len(previews),
            "source_count": sum(len(item.get("sources") or []) for item in previews),
            "disposable_bytes": total_disposable,
            "message": (
                f"Review is complete. Remove {total_disposable} bytes of temporary "
                "generated evidence? Original recordings will not be touched."
            ),
            "default_choice": "keep_generated",
            "choices": ["keep_generated", "remove_temporary"],
        }
        return (
            _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status="Processing",
                cleanup_confirmation=confirmation,
            ),
            run,
            queue,
        )

    choice = (
        "remove_temporary"
        if total_disposable == 0
        else str((decision or {}).get("choice") or "")
    )
    if not can_reuse_recorded:
        run["cleanup_decision"] = {
            "token": token,
            "choice": choice,
            "recorded_utc": _utc_now(),
        }
    run["status"] = "finalizing"
    _write_active(paths, run)
    _execute_cleanup(
        ledger_path,
        previews,
        choice,
        stop_requested=lambda: _stop_was_requested(paths, payload),
    )
    queue = _refresh_queue(payload, import_external=True)
    remaining_cleanup = any(
        isinstance(item, dict)
        and str(item.get("status") or "") == "results_received"
        for item in _queue_batches(queue)
    )
    if _stop_was_requested(paths, payload) and remaining_cleanup:
        run["status"] = "paused_after_current"
        run["stop_requested"] = True
        _write_active(paths, run)
        return (
            _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status="Processing",
            ),
            run,
            queue,
        )
    run["status"] = "running"
    _write_active(paths, run)
    return None, run, queue


def _stop_was_requested(
    paths: dict[str, Path],
    payload: dict[str, Any],
) -> bool:
    callback = payload.get("stop_requested")
    supplied_path = str(payload.get("stop_after_current_file_path") or "").strip()
    return (
        paths["stop"].exists()
        or bool(supplied_path and Path(supplied_path).exists())
        or (callable(callback) and bool(callback()))
    )


def _pause_before_next_source(
    paths: dict[str, Path],
    run: dict[str, Any],
) -> None:
    prior_status = str(run.get("status") or "running")
    run["resume_status"] = (
        prior_status
        if prior_status == "awaiting_all_pending_confirmation"
        else "running"
    )
    run["status"] = "paused_after_current"
    run["stop_requested"] = True
    _write_active(paths, run)


def _record_completed_sources(
    run: dict[str, Any],
    prepared: dict[str, Any],
    inflight: list[dict[str, Any]],
) -> None:
    prepared_items = [
        item
        for item in prepared.get("prepared_sources") or []
        if isinstance(item, dict)
    ]
    if "prepared_sources" not in prepared and str(prepared.get("status") or "") == (
        "awaiting_external_review"
    ):
        # Compatibility for injected/legacy preparation adapters that report a
        # terminal batch without the source-detail arrays added by the current
        # preparation contract.
        prepared_items = [item for item in inflight if isinstance(item, dict)]

    snapshot_ids = {
        str(item.get("source_id") or "")
        for item in run.get("snapshot") or []
        if isinstance(item, dict) and str(item.get("source_id") or "")
    }
    completed = {
        str(value)
        for value in run.get("completed_source_ids") or []
        if str(value)
    }
    for item in prepared_items:
        source_id = str(item.get("source_id") or "")
        if source_id and (not snapshot_ids or source_id in snapshot_ids):
            completed.add(source_id)
    run["completed_source_ids"] = sorted(
        completed,
        key=lambda value: (not value.isdigit(), int(value) if value.isdigit() else value),
    )


def _preallocated_batch_id(run: dict[str, Any], cursor: int) -> str:
    token = hashlib.sha256(
        f"{run.get('run_id', '')}:{cursor}".encode("utf-8")
    ).hexdigest()[:16]
    return f"batch-process-{token}"


def _process_scan_result(
    run: dict[str, Any],
    queue: dict[str, Any],
    ledger_path: Path,
    *,
    max_duration_minutes: float,
) -> dict[str, Any]:
    settings = dict(run.get("scan_settings") or {})
    settings.setdefault("ledger_path", str(ledger_path))
    settings.setdefault("order", "oldest")
    settings.setdefault("dedupe_mode", "Fast")
    settings["max_files"] = HIDDEN_BATCH_SIZE
    # Preparation subtracts prior_elapsed_seconds from its clock origin, so its
    # comparison must use the full run boundary rather than a second
    # already-reduced remainder.
    settings["max_duration_minutes"] = max_duration_minutes
    settings["pending_batch_limit"] = MAX_UP_TO_N
    return {
        "contract_version": 1,
        "scan_only": True,
        "complete": True,
        "cancelled": False,
        "settings": settings,
        "sources": list(run.get("snapshot") or []),
        "selected_sources": [],
        "pending_batches": [
            {
                "batch_id": str(item.get("batch_id") or ""),
                "status": str(item.get("status") or ""),
                "package_path": str(item.get("batch_path") or ""),
            }
            for item in _queue_batches(queue)
            if str(item.get("status") or "")
            not in {
                "finalized_no_findings",
                "finalized_with_findings",
                "needs_manual_review",
            }
        ],
    }


def _mutable_preparation_batch(queue: dict[str, Any]) -> dict[str, Any] | None:
    for batch in _queue_batches(queue):
        if str(batch.get("status") or "") in {
            "preparing",
            "needs_audio_confirmation",
        }:
            return batch
    return None


def _reconcile_committed_inflight_batch(
    run: dict[str, Any],
    queue: dict[str, Any],
) -> bool:
    """Consume a preallocated chunk already committed before a host crash."""

    batch_id = str(run.get("inflight_batch_id") or "")
    inflight = [
        item
        for item in run.get("inflight_chunk") or []
        if isinstance(item, dict)
    ]
    if not batch_id or not inflight:
        return False
    committed_statuses = {
        "awaiting_external_review",
        "preliminary_findings_received",
        "targeted_evidence_ready",
        "results_received",
        "finalizing",
        "finalized_no_findings",
        "finalized_with_findings",
        "needs_manual_review",
    }
    batch = next(
        (
            item
            for item in _queue_batches(queue)
            if str(item.get("batch_id") or "") == batch_id
            and str(item.get("status") or "") in committed_statuses
        ),
        None,
    )
    if batch is None:
        return False
    expected_ids = [
        int(item["source_id"])
        for item in inflight
        if item.get("source_id") is not None
    ]
    if len(expected_ids) != len(inflight):
        raise OrchestrationError(
            "The committed inflight chunk is missing a source identity."
        )
    source_count = int(batch.get("source_count") or 0)
    if source_count != len(expected_ids):
        raise OrchestrationError(
            "The committed preallocated batch does not match its inflight chunk."
        )
    snapshot = [
        item
        for item in run.get("snapshot") or []
        if isinstance(item, dict)
    ]
    cursor = min(len(snapshot), max(0, int(run.get("cursor") or 0)))
    snapshot_ids = [
        int(item["source_id"])
        for item in snapshot[cursor : cursor + len(inflight)]
        if item.get("source_id") is not None
    ]
    if snapshot_ids != expected_ids:
        raise OrchestrationError(
            "The committed inflight chunk no longer matches the run snapshot."
        )

    run["cursor"] = cursor + len(inflight)
    completed = {
        str(value)
        for value in run.get("completed_source_ids") or []
        if str(value)
    }
    completed.update(str(value) for value in expected_ids)
    run["completed_source_ids"] = sorted(
        completed,
        key=lambda value: (
            not value.isdigit(),
            int(value) if value.isdigit() else value,
        ),
    )
    record = {
        "batch_id": batch_id,
        "source_count": len(inflight),
        "status": str(batch.get("status") or ""),
    }
    existing = [
        item
        for item in run.get("batches") or []
        if isinstance(item, dict)
        and str(item.get("batch_id") or "") == batch_id
    ]
    if existing:
        existing[0].update(record)
    else:
        run.setdefault("batches", []).append(record)
    run["inflight_chunk"] = []
    run["inflight_batch_id"] = ""
    run["status"] = "running"
    return True


def _read_existing_queue_index(ledger_path: Path) -> dict[str, Any]:
    """Read the last published queue projection without reconciling or writing."""

    queue_root = inbox_records.workspace(ledger_path)
    index_path = queue_root / "queue-index.json"
    prompt_path = queue_root / "CODEX_REVIEW_QUEUE_PROMPT.md"
    queue: dict[str, Any] = {}
    try:
        value = json.loads(index_path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            queue = value
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass
    return {
        **queue,
        "queue_root": str(queue_root),
        "queue_index_path": str(index_path),
        "queue_prompt_path": str(prompt_path),
        "counts": (
            dict(queue.get("counts") or {})
            if isinstance(queue.get("counts"), dict)
            else {}
        ),
    }


def _attach_result(
    ledger_path: Path,
    paths: dict[str, Path],
) -> dict[str, Any]:
    queue = _read_existing_queue_index(ledger_path)
    try:
        run = _read_journal(paths["active"])
    except Exception as exc:
        return _result(
            action="process",
            ledger_path=ledger_path,
            queue=queue,
            run=None,
            operator_status="Needs attention",
            attention=_exception_attention(
                "run_journal_error",
                (
                    "Saved Process state could not be verified. "
                    "Open Technical details for diagnostic information."
                ),
                exc,
            ),
        )
    if run and not str(queue.get("document_type") or ""):
        queue["counts"] = dict(run.get("last_queue_counts") or {})
    return _result(
        action="process",
        ledger_path=ledger_path,
        queue=queue,
        run=run,
        operator_status="Processing" if run else _operator_status(queue),
        attention={
            "code": "process_already_running",
            "message": "Review Media Inbox is already processing this queue.",
        },
    )


def reconcile_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Reconcile stable external returns without scanning or preparing media."""

    ledger_path = _ledger_path(payload)
    paths = _orchestration_paths(ledger_path)
    # Launch reconciliation may overlap a Process action owned by another
    # Workbench/PowerShell host. In that case it must remain a read-only status
    # attachment: importing returns, rewriting queue artifacts, or recovering a
    # journal concurrently would violate the single-coordinator boundary.
    with inbox_records.process_lock(ledger_path) as process_lock:
        if not process_lock.acquired:
            return _attach_result(ledger_path, paths)

        held_from = time.monotonic()
        result = _reconcile_holding_lock(payload, ledger_path, paths)
        # 224 (Wave B2a, item 4): how long the status check held the lock. The Workbench writes it to its log,
        # so the command line's ten-second wait is checked against a measurement, not a guess.
        result["lock_held_seconds"] = round(time.monotonic() - held_from, 3)
    return result


def _reconcile_holding_lock(payload: dict[str, Any], ledger_path: Path, paths: dict[str, Path]) -> dict[str, Any]:
    queue = _read_existing_queue_index(ledger_path)
    run: dict[str, Any] | None = None
    try:
        # 224 (Wave B1): an older ledger is moved up once, here, holding the lock; every read below is
        # read-only and never makes a ledger.
        inbox_records.settle(ledger_path)
        run = _read_journal(paths["active"])
        queue = _refresh_queue(payload, import_external=False)
        recovery = _recover_preparation_staging(queue, payload)
        if _recover_finalizing(queue, ledger_path):
            recovery.append({"kind": "finalization", "classification": "recovered"})
        queue = _refresh_queue(payload, import_external=True)
    except Exception as exc:
        if run:
            run["status"] = "needs_attention"
            run["last_queue_counts"] = _queue_counts(queue)
            _write_active(paths, run)
        return _result(
            action="reconcile",
            ledger_path=ledger_path,
            queue=queue,
            run=run,
            operator_status="Needs attention",
            attention=_exception_attention(
                "recovery_error",
                (
                    "Launch reconciliation stopped safely. "
                    "Open Technical details for diagnostic information."
                ),
                exc,
            ),
        )
    if run:
        run["last_queue_counts"] = _queue_counts(queue)
        _write_active(paths, run)
    attention = _attention(queue)
    audio = _audio_choice(queue)
    return _result(
        action="reconcile",
        ledger_path=ledger_path,
        queue=queue,
        run=run,
        operator_status=(
            "Needs attention"
            if attention
            else "Needs audio choice"
            if audio
            else _operator_status(queue)
        ),
        attention=attention,
        audio_choice=audio,
        recovery=recovery,
    )


def process_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Perform one deterministic local Process action and return its next gate."""

    ledger_path = _ledger_path(payload)
    paths = _orchestration_paths(ledger_path)

    # A second PowerShell host can use this read-only path after its exclusive
    # host lock fails.  It must not import returns, rewrite queue projections,
    # or create orchestration directories while the owning host is active.
    if bool(payload.get("attach_only")):
        return _attach_result(ledger_path, paths)

    paths["root"].mkdir(parents=True, exist_ok=True)

    if bool(payload.get("request_stop") or payload.get("stop_after_current")):
        queue = _read_existing_queue_index(ledger_path)
        try:
            run = _read_journal(paths["active"])
        except Exception as exc:
            return _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=None,
                operator_status="Needs attention",
                attention=_exception_attention(
                    "run_journal_error",
                    (
                        "Saved Process state could not be verified. "
                        "Open Technical details for diagnostic information."
                    ),
                    exc,
                ),
            )
        if run:
            _atomic_json(
                paths["stop"],
                {
                    "schema_version": 1,
                    "run_id": str(run.get("run_id") or ""),
                    "requested_utc": _utc_now(),
                },
            )
        # The owning coordinator records stop_requested at its next safe
        # boundary. Do not race its atomic run-journal update from this
        # signalling path.
        if run and not str(queue.get("document_type") or ""):
            queue["counts"] = dict(run.get("last_queue_counts") or {})
        return _result(
            action="process",
            ledger_path=ledger_path,
            queue=queue,
            run=run,
            operator_status="Processing" if run else "Done",
        )

    lock_context = inbox_records.process_lock(
        ledger_path, coordinator_lock_held=bool(payload.get("coordinator_lock_held"))
    )

    with lock_context as process_lock:
        if not process_lock.acquired:
            return _attach_result(ledger_path, paths)

        queue = _read_existing_queue_index(ledger_path)
        run: dict[str, Any] | None = None
        try:
            # 224 (Wave B1): as in reconcile, an older ledger is moved up once, here, holding the lock.
            inbox_records.settle(ledger_path)
            # 224 (Wave B2a, Decision 3): what an earlier run could not clean up is removed now.
            inbox_records.sweep_leftovers(ledger_path)
            run = _read_journal(paths["active"])
            if run and str(run.get("status") or "") in {"complete", "cancelled"}:
                _archive_run(paths, run)
                run = None

            if run:
                _verify_active_restriction_request(run, payload)

            if run and str(payload.get("continuation") or ""):
                if str(payload.get("continuation")) != _continuation(run):
                    raise OrchestrationError(
                        "The supplied Process continuation is stale."
                    )

            if run and str(run.get("status") or "") in {
                "paused_after_current",
                "paused_soft_limit",
            }:
                run["status"] = str(
                    run.pop("resume_status", "running") or "running"
                )
                run["stop_requested"] = False
                run["elapsed_seconds"] = 0.0
                safe_write.remove(paths["stop"], wait=safe_write.INBOX_WAIT_SECONDS)
                _write_active(paths, run)

            queue = _refresh_queue(payload, import_external=False)
            _recover_preparation_staging(queue, payload)
            _recover_finalizing(queue, ledger_path)
            queue = _refresh_queue(payload, import_external=True)
            if run:
                _reconcile_committed_inflight_batch(run, queue)
        except Exception as exc:
            # Never replace an unreadable journal with a fresh maintenance run:
            # preserving the failed document is required for diagnosis and
            # recovery. A refresh failure without an active journal may safely
            # use a new maintenance run to retain the ordinary status contract.
            restriction_error = isinstance(exc, ExactSourceRestrictionError)
            if (
                not restriction_error
                and run is None
                and not paths["active"].exists()
            ):
                run = _new_maintenance_run(payload, ledger_path, queue)
            if run is not None:
                run["status"] = "needs_attention"
                run["last_queue_counts"] = _queue_counts(queue)
                _write_active(paths, run)
            return _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status="Needs attention",
                attention=_exception_attention(
                    (
                        "exact_source_restriction_error"
                        if restriction_error
                        else "recovery_error"
                    ),
                    (
                        "The restricted qualification run does not match the "
                        "saved Process state. Open Technical details for "
                        "diagnostic information."
                        if restriction_error
                        else
                        "Existing Review Media Inbox work could not be recovered "
                        "safely. Open Technical details for diagnostic information."
                    ),
                    exc,
                ),
            )
        mutable_batch = _mutable_preparation_batch(queue)
        mutable_batch_id = (
            str(mutable_batch.get("batch_id") or "")
            if isinstance(mutable_batch, dict)
            else ""
        )
        if mutable_batch is not None:
            if run is None:
                run = _new_recovery_run(payload, ledger_path, mutable_batch)
            else:
                _adopt_mutable_batch(run, mutable_batch)
        if run:
            run["last_queue_counts"] = _queue_counts(queue)
            _write_active(paths, run)

        audio_decision_applied = False
        queued_audio = _audio_choice(queue)
        decision = _decision(payload)
        if (
            run
            and queued_audio is not None
            and str(decision.get("type") or "") == "audio"
        ):
            try:
                accepted = _decision_authorized(
                    payload,
                    run,
                    expected_type="audio",
                    expected_token=str(queued_audio["token"]),
                )
            except Exception as exc:
                return _result(
                    action="process",
                    ledger_path=ledger_path,
                    queue=queue,
                    run=run,
                    operator_status="Needs attention",
                    attention=_exception_attention(
                        "process_decision_error",
                        (
                            "This confirmation is no longer current. "
                            "Retry Process from the latest inbox status."
                        ),
                        exc,
                    ),
                )
            audio_decision_applied = bool(accepted and accepted.get("confirmed"))
            if not audio_decision_applied:
                run["status"] = "needs_audio_choice"
                _write_active(paths, run)
                return _result(
                    action="process",
                    ledger_path=ledger_path,
                    queue=queue,
                    run=run,
                    operator_status="Needs audio choice",
                    audio_choice=queued_audio,
                )
            run["status"] = "running"
            _write_active(paths, run)

        try:
            external_result, run, queue = _handle_external_work(
                ledger_path=ledger_path,
                payload=payload,
                paths=paths,
                queue=queue,
                run=run,
                audio_decision_applied=audio_decision_applied,
                resumable_preparation_batch_id=mutable_batch_id,
            )
        except Exception as exc:
            if run is None:
                run = _new_maintenance_run(payload, ledger_path, queue)
            run["status"] = "needs_attention"
            _write_active(paths, run)
            return _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status="Needs attention",
                attention=_exception_attention(
                    "external_work_error",
                    (
                        "Existing queued work could not be completed safely. "
                        "Open Technical details for diagnostic information."
                    ),
                    exc,
                ),
            )
        if external_result is not None:
            return external_result

        pending_resume_before_scan = (
            isinstance((run or {}).get("pending_resume"), dict)
            and bool(((run or {}).get("pending_resume") or {}).get("batch_id"))
        )
        should_initialise_workload = bool(
            run is not None
            and run.get("workload_pending_initialization")
            and not pending_resume_before_scan
            and not run.get("inflight_chunk")
        )
        if run is None or should_initialise_workload:
            try:
                scan_payload = _payload_with_pending_restriction(run, payload)
                inventory = _scan_inventory(scan_payload)
                scan_settings = inventory.get("settings")
                if isinstance(scan_settings, dict):
                    payload = {**payload, "_scan_settings": scan_settings}
                if run is None:
                    run = _new_run(payload, inventory)
                else:
                    _initialise_pending_workload(run, payload, inventory)
            except Exception as exc:
                restriction_error = isinstance(exc, ExactSourceRestrictionError)
                if run is None and not restriction_error:
                    run = _new_maintenance_run(payload, ledger_path, queue)
                if run is not None:
                    run["status"] = "needs_attention"
                    _write_active(paths, run)
                return _result(
                    action="process",
                    ledger_path=ledger_path,
                    queue=queue,
                    run=run,
                    operator_status="Needs attention",
                    attention=_exception_attention(
                        (
                            "exact_source_restriction_error"
                            if restriction_error
                            else "scan_error"
                        ),
                        (
                            "The requested exact source could not be selected "
                            "safely from the complete inbox scan. Open Technical "
                            "details for diagnostic information."
                            if restriction_error
                            else
                            "The inbox inventory could not be built safely. "
                            "Open Technical details for diagnostic information."
                        ),
                        exc,
                    ),
                )
            run["last_queue_counts"] = _queue_counts(queue)
            _write_active(paths, run)

        if str(run.get("status") or "") == "awaiting_all_pending_confirmation":
            token = str(run.get("all_pending_confirmation_token") or "")
            try:
                decision = _decision_authorized(
                    payload,
                    run,
                    expected_type="all_pending",
                    expected_token=token,
                )
            except Exception as exc:
                return _result(
                    action="process",
                    ledger_path=ledger_path,
                    queue=queue,
                    run=run,
                    operator_status="Needs attention",
                    attention=_exception_attention(
                        "process_decision_error",
                        (
                            "This confirmation is no longer current. "
                            "Retry Process from the latest inbox status."
                        ),
                        exc,
                    ),
                )
            if decision is None:
                confirmation = _all_pending_confirmation(ledger_path, payload, run)
                return _result(
                    action="process",
                    ledger_path=ledger_path,
                    queue=queue,
                    run=run,
                    operator_status="Processing",
                    all_pending_confirmation=confirmation,
                )
            if not bool(decision.get("confirmed")):
                run["status"] = "cancelled"
                run["cancelled_utc"] = _utc_now()
                _write_active(paths, run)
                result = _result(
                    action="process",
                    ledger_path=ledger_path,
                    queue=queue,
                    run=run,
                    operator_status=_operator_status(queue),
                )
                _archive_run(paths, run)
                return result
            run["status"] = "running"
            run["all_pending_confirmed_utc"] = _utc_now()
            _write_active(paths, run)

        snapshot = list(run.get("snapshot") or [])
        cursor = min(len(snapshot), max(0, int(run.get("cursor") or 0)))
        has_pending_resume = bool(
            isinstance(run.get("pending_resume"), dict)
            and (
                (run.get("pending_resume") or {}).get("batch_id")
                or (run.get("pending_resume") or {}).get("selected_sources")
            )
        )
        if cursor >= len(snapshot) and not has_pending_resume:
            if (
                isinstance(run.get("exact_source_restriction"), dict)
                and not _restricted_run_is_terminal(ledger_path, run)
            ):
                run["status"] = "waiting_external_review"
                _write_active(paths, run)
                return _result(
                    action="process",
                    ledger_path=ledger_path,
                    queue=queue,
                    run=run,
                    operator_status=_operator_status(queue),
                )
            run["status"] = "complete"
            run["completed_utc"] = _utc_now()
            _write_active(paths, run)
            result = _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status=_operator_status(queue),
            )
            _archive_run(paths, run)
            return result

        if _stop_was_requested(paths, payload):
            _pause_before_next_source(paths, run)
            return _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status="Processing",
            )

        soft_limit_seconds = float(
            payload.get("max_duration_minutes", SOFT_LIMIT_MINUTES)
        ) * 60.0
        if float(run.get("elapsed_seconds") or 0.0) >= soft_limit_seconds:
            run["status"] = "paused_soft_limit"
            _write_active(paths, run)
            return _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status="Processing",
            )

        pending_resume = (
            dict(run.get("pending_resume") or {})
            if isinstance(run.get("pending_resume"), dict)
            else {}
        )
        resuming_batch = bool(str(pending_resume.get("batch_id") or ""))
        inflight = list(pending_resume.get("selected_sources") or [])
        if not resuming_batch and not inflight:
            inflight = list(run.get("inflight_chunk") or [])
        if not resuming_batch and not inflight:
            inflight = snapshot[cursor : cursor + HIDDEN_BATCH_SIZE]
            run["inflight_chunk"] = inflight
            run["inflight_batch_id"] = _preallocated_batch_id(run, cursor)
            run["status"] = "preparing"
            _write_active(paths, run)
        elif not resuming_batch and not str(run.get("inflight_batch_id") or ""):
            run["inflight_batch_id"] = _preallocated_batch_id(run, cursor)
            _write_active(paths, run)

        clock = payload.get("clock") if callable(payload.get("clock")) else time.monotonic
        started = float(clock())
        elapsed_before = max(0.0, float(run.get("elapsed_seconds") or 0.0))
        max_duration_minutes = soft_limit_seconds / 60.0
        prepare_payload = dict(payload)
        prepare_payload.update(
            {
                "ledger_path": str(ledger_path),
                "selected_sources": _json_safe(inflight),
                "selected_source_ids": [
                    int(item["source_id"])
                    for item in inflight
                    if isinstance(item, dict) and item.get("source_id") is not None
                ],
                "max_files": len(inflight),
                "orchestration_run_id": str(run["run_id"]),
                "stop_requested": lambda: _stop_was_requested(paths, payload),
                "max_duration_minutes": max_duration_minutes,
                "prior_elapsed_seconds": elapsed_before,
                "orchestration_prior_elapsed_seconds": elapsed_before,
                "scan_result": _process_scan_result(
                    run,
                    queue,
                    ledger_path,
                    max_duration_minutes=max_duration_minutes,
                ),
            }
        )
        if resuming_batch:
            prepare_payload["resume_batch_id"] = str(pending_resume.get("batch_id") or "")
        else:
            prepare_payload["preallocated_batch_id"] = str(
                run.get("inflight_batch_id") or ""
            )
        try:
            prepared = _prepare_selected(prepare_payload)
        except Exception as exc:
            run["status"] = "needs_attention"
            _write_active(paths, run)
            try:
                queue = _refresh_queue(payload, import_external=False)
                run["last_queue_counts"] = _queue_counts(queue)
                _write_active(paths, run)
            except Exception:
                # Preserve the already trusted queue projection if even a
                # read-only-status refresh cannot be formed.
                pass
            return _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status="Needs attention",
                attention=_exception_attention(
                    "preparation_error",
                    (
                        "Media preparation stopped safely. "
                        "Open Technical details for diagnostic information."
                    ),
                    exc,
                    batch_id=str(
                        pending_resume.get("batch_id")
                        or run.get("inflight_batch_id")
                        or ""
                    ),
                ),
            )
        finished = float(clock())
        duration = max(0.0, finished - started)
        run["elapsed_seconds"] = float(run.get("elapsed_seconds") or 0.0) + duration
        run["total_elapsed_seconds"] = float(run.get("total_elapsed_seconds") or 0.0) + duration
        prepared_status = str(prepared.get("status") or "")
        prepared_batch_id = str(prepared.get("batch_id") or "")
        _record_completed_sources(run, prepared, inflight)

        if prepared_status == "local_work_pending":
            pending_batches = [
                item
                for item in prepared.get("pending_batches") or []
                if isinstance(item, dict) and str(item.get("batch_id") or "")
            ]
            if pending_batches:
                run["pending_resume"] = {
                    "batch_id": str(pending_batches[0]["batch_id"]),
                    "selected_sources": [],
                }
                run["status"] = "running"
                _write_active(paths, run)
                queue = _refresh_queue(payload, import_external=True)
                run["last_queue_counts"] = _queue_counts(queue)
                _write_active(paths, run)
                return _result(
                    action="process",
                    ledger_path=ledger_path,
                    queue=queue,
                    run=run,
                    operator_status="Processing",
                    continue_automatically=True,
                    next_action={"type": "continue_processing"},
                )
            run["status"] = "needs_attention"
            _write_active(paths, run)
            return _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status="Needs attention",
                attention=_safe_attention(
                    "local_work_pending",
                    "Existing local work must be recovered before a new source starts.",
                    details=prepared.get("message"),
                ),
            )

        if prepared_status in {"resume_batch_unavailable", "nothing_eligible"}:
            run["status"] = "needs_attention"
            _write_active(paths, run)
            return _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status="Needs attention",
                attention=_safe_attention(
                    prepared_status,
                    "The exact queued work could not be continued safely.",
                    details=prepared.get("message"),
                    batch_id=prepared_batch_id,
                ),
            )

        if not resuming_batch and not prepared_batch_id:
            run["status"] = "needs_attention"
            _write_active(paths, run)
            return _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status="Needs attention",
                attention={
                    "code": "preparation_missing_batch",
                    "message": "Preparation did not identify the assigned hidden batch.",
                },
            )

        # Assignment consumes the new-source quota only after the selected
        # sources have a durable batch identity.  A resume never consumes it a
        # second time.
        if not resuming_batch:
            run["cursor"] = cursor + len(inflight)
        elif bool(pending_resume.get("consume_assigned_quota")):
            run["cursor"] = cursor + len(inflight)
        run["inflight_chunk"] = []
        run["inflight_batch_id"] = ""
        if prepared_batch_id:
            record = {
                "batch_id": prepared_batch_id,
                "source_count": len(inflight),
                "status": prepared_status,
            }
            existing = [
                item
                for item in run.get("batches") or []
                if isinstance(item, dict)
                and str(item.get("batch_id") or "") == prepared_batch_id
            ]
            if existing:
                existing[0].update(record)
            else:
                run.setdefault("batches", []).append(record)
        run["status"] = "running"
        _write_active(paths, run)

        queue = _refresh_queue(payload, import_external=True)
        run["last_queue_counts"] = _queue_counts(queue)
        _write_active(paths, run)

        failed_sources = [
            item
            for item in prepared.get("failed_sources") or []
            if isinstance(item, dict)
        ]
        terminal_fields_present = any(
            key in prepared
            for key in ("prepared_sources", "blocked_sources", "failed_sources")
        )
        terminal_count = sum(
            len(
                [
                    item
                    for item in prepared.get(key) or []
                    if isinstance(item, dict)
                ]
            )
            for key in ("prepared_sources", "blocked_sources", "failed_sources")
        )
        incomplete_assignment = bool(
            inflight
            and terminal_fields_present
            and terminal_count < len(inflight)
        )
        if incomplete_assignment:
            run["pending_resume"] = {
                "batch_id": prepared_batch_id,
                "selected_sources": _json_safe(inflight),
            }
            _write_active(paths, run)
        if failed_sources:
            first_failure = failed_sources[0]
            run["pending_resume"] = {
                "batch_id": prepared_batch_id,
                "selected_sources": _json_safe(inflight),
            }
            run["status"] = "needs_attention"
            _write_active(paths, run)
            return _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status="Needs attention",
                attention=_safe_attention(
                    str(
                        first_failure.get("state")
                        or first_failure.get("status")
                        or "preparation_failed"
                    ),
                    (
                        "A source could not be prepared safely. Correct the "
                        "reported condition before processing more media."
                    ),
                    details=(
                        first_failure.get("message")
                        or first_failure.get("error")
                    ),
                    batch_id=prepared_batch_id,
                    source_id=first_failure.get("source_id"),
                ),
            )

        attention = _attention(queue)
        if attention is not None:
            run["status"] = "needs_attention"
            _write_active(paths, run)
            return _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status="Needs attention",
                attention=attention,
            )

        audio = _audio_choice(queue)
        if audio is not None or str(prepared.get("status") or "") == "needs_audio_confirmation":
            audio = audio or {
                "batch_id": str(prepared.get("batch_id") or ""),
                "batch_path": str(prepared.get("batch_path") or ""),
                "blocked_sources": _json_safe(prepared.get("blocked_sources") or []),
            }
            audio["token"] = str(
                audio.get("token")
                or _sha256(
                    {
                        "batch_id": audio.get("batch_id"),
                        "blocked_sources": audio.get("blocked_sources"),
                    }
                )
            )
            run["pending_resume"] = {
                "batch_id": str(prepared.get("batch_id") or pending_resume.get("batch_id") or ""),
                "selected_sources": _json_safe(inflight),
            }
            run["status"] = "needs_audio_choice"
            _write_active(paths, run)
            return _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status="Needs audio choice",
                audio_choice=audio,
            )

        if incomplete_assignment and prepared_status != "preparing":
            run["pending_resume"] = {
                "batch_id": prepared_batch_id,
                "selected_sources": _json_safe(inflight),
            }
            run["status"] = "needs_attention"
            _write_active(paths, run)
            return _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status="Needs attention",
                attention={
                    "code": "preparation_incomplete",
                    "batch_id": prepared_batch_id,
                    "message": (
                        "The assigned hidden batch has unfinished sources and "
                        "will resume before any new source is allocated."
                    ),
                },
            )

        if prepared_status == "preparing":
            run["pending_resume"] = {
                "batch_id": prepared_batch_id,
                "selected_sources": _json_safe(inflight),
            }
            stopped_reason = str(prepared.get("stopped_reason") or "")
            if stopped_reason == "soft_duration_boundary":
                run["status"] = "paused_soft_limit"
                _write_active(paths, run)
                return _result(
                    action="process",
                    ledger_path=ledger_path,
                    queue=queue,
                    run=run,
                    operator_status="Processing",
                )
            if _stop_was_requested(paths, payload):
                run["status"] = "paused_after_current"
                run["stop_requested"] = True
                _write_active(paths, run)
                return _result(
                    action="process",
                    ledger_path=ledger_path,
                    queue=queue,
                    run=run,
                    operator_status="Processing",
                )
            run["status"] = "needs_attention"
            _write_active(paths, run)
            return _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status="Needs attention",
                attention=_safe_attention(
                    stopped_reason or "preparation_incomplete",
                    (
                        "The current batch remains incomplete and must be "
                        "recovered before new media starts."
                    ),
                    details=prepared.get("message"),
                    batch_id=prepared_batch_id,
                ),
            )

        run.pop("pending_resume", None)
        _write_active(paths, run)

        if _stop_was_requested(paths, payload):
            run["status"] = "paused_after_current"
            run["stop_requested"] = True
            _write_active(paths, run)
            return _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status="Processing",
            )

        if float(run.get("elapsed_seconds") or 0.0) >= soft_limit_seconds:
            run["status"] = "paused_soft_limit"
            _write_active(paths, run)
            return _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status="Processing",
            )

        if bool(run.get("workload_pending_initialization")):
            try:
                scan_payload = _payload_with_pending_restriction(run, payload)
                inventory = _scan_inventory(scan_payload)
                _initialise_pending_workload(run, payload, inventory)
            except Exception as exc:
                restriction_error = isinstance(exc, ExactSourceRestrictionError)
                run["status"] = "needs_attention"
                _write_active(paths, run)
                return _result(
                    action="process",
                    ledger_path=ledger_path,
                    queue=queue,
                    run=run,
                    operator_status="Needs attention",
                    attention=_exception_attention(
                        (
                            "exact_source_restriction_error"
                            if restriction_error
                            else "scan_error"
                        ),
                        (
                            "The requested exact source could not be selected "
                            "safely after existing work completed. Open Technical "
                            "details for diagnostic information."
                            if restriction_error
                            else
                            "The inbox inventory could not be built safely after "
                            "existing work completed. Open Technical details for "
                            "diagnostic information."
                        ),
                        exc,
                    ),
                )
            run["last_queue_counts"] = _queue_counts(queue)
            _write_active(paths, run)
            if not run.get("snapshot"):
                run["status"] = "complete"
                run["completed_utc"] = _utc_now()
                _write_active(paths, run)
                result = _result(
                    action="process",
                    ledger_path=ledger_path,
                    queue=queue,
                    run=run,
                    operator_status=_operator_status(queue),
                )
                _archive_run(paths, run)
                return result
            if run.get("snapshot") and _stop_was_requested(paths, payload):
                _pause_before_next_source(paths, run)
                return _result(
                    action="process",
                    ledger_path=ledger_path,
                    queue=queue,
                    run=run,
                    operator_status="Processing",
                )
            return _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status="Processing",
                continue_automatically=True,
                next_action={"type": "continue_processing"},
            )

        if int(run["cursor"]) < len(snapshot):
            return _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status="Processing",
                continue_automatically=True,
                next_action={"type": "continue_processing"},
            )

        if (
            isinstance(run.get("exact_source_restriction"), dict)
            and not _restricted_run_is_terminal(ledger_path, run)
        ):
            run["status"] = "waiting_external_review"
            _write_active(paths, run)
            return _result(
                action="process",
                ledger_path=ledger_path,
                queue=queue,
                run=run,
                operator_status=_operator_status(queue),
            )

        run["status"] = "complete"
        run["completed_utc"] = _utc_now()
        _write_active(paths, run)
        result = _result(
            action="process",
            ledger_path=ledger_path,
            queue=queue,
            run=run,
            operator_status=_operator_status(queue),
        )
        _archive_run(paths, run)
        return result
