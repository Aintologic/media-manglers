"""Targeted-evidence planning, integrity, recovery, and lifecycle handling."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
from typing import Any, Callable
import uuid

from . import inbox_records, panel_layout, review_findings, review_ledger, review_preparation, safe_write


CONTRACT_VERSION = 1
RENDER_VERSION = 1
PANEL_ONLY_MAX_FRAMES = 6
SUCCESS_RENDER_STATUSES = {"created", "completed", "generated"}
TARGET_BATCH_STATES = {"preliminary_findings_received", "targeted_evidence_ready"}
TARGET_SOURCE_STATES = {
    "awaiting_external_review",
    "preliminary_findings_received",
    "targeted_evidence_ready",
    "retryable_failure",
    "source_changed",
}


class TargetedEvidenceError(RuntimeError):
    """Raised when targeted evidence cannot be planned or completed safely."""


class SourceResolutionError(TargetedEvidenceError):
    def __init__(self, message: str, state: str) -> None:
        super().__init__(message)
        self.state = state


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    review_findings._atomic_json(path, payload)


def _atomic_text(path: Path, text: str) -> None:
    review_findings._atomic_text(path, text)


def _within(root: Path, target: Path) -> bool:
    return review_findings._is_within(root, target)


def _require_within(root: Path, target: Path, label: str) -> None:
    if not _within(root, target):
        raise TargetedEvidenceError(f"{label} resolves outside its approved root.")


def _safe_remove_tree(root: Path, target: Path, leftovers: Path | None = None) -> None:
    _require_within(root, target, "Targeted-evidence staging path")
    if target.resolve() == root.resolve():
        raise TargetedEvidenceError("Refusing to remove the targeted-evidence staging root itself.")
    # 224 (Wave B2a): through the one antivirus-safe helper (a bounded wait for another program, never for the
    # app itself; renamed to a trash name first, so a delete cut short never looks like evidence).
    safe_write.remove_disposable_tree(target, within=root, leftovers=leftovers)


def _modified_utc(stat: os.stat_result) -> str:
    return datetime.fromtimestamp(stat.st_mtime_ns / 1_000_000_000, timezone.utc).isoformat().replace("+00:00", "Z")


def _stat_record(stat: os.stat_result) -> dict[str, Any]:
    return {
        "size_bytes": int(stat.st_size),
        "modified_ns": int(stat.st_mtime_ns),
        "modified_utc": _modified_utc(stat),
    }


def _token(*values: str, length: int = 16) -> str:
    return hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest()[:length]


def _canonical_sha(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_ledger(ledger_path: Path) -> sqlite3.Connection:
    """The ledger opened for reading only (224, F4): one that is not there is an error here, never made."""

    connection = inbox_records.connect_read_only(ledger_path)
    if connection is None:
        raise TargetedEvidenceError("The configured Review Media Inbox ledger does not exist.")
    return connection


def _resolve_batch_root(ledger_path: Path, expected_batch_id: str, supplied: str = "") -> Path:
    connection = _read_ledger(ledger_path)
    try:
        row = connection.execute("SELECT package_path FROM inbox_batches WHERE batch_id = ?", (expected_batch_id,)).fetchone()
    finally:
        connection.close()
    if row is None:
        raise TargetedEvidenceError(f"Batch {expected_batch_id!r} is unknown to the Review Media Inbox ledger.")
    root = Path(str(row["package_path"] or ""))
    if supplied and root.resolve() != Path(supplied).resolve():
        raise TargetedEvidenceError("The supplied batch path contradicts the ledger package path.")
    if not root.is_dir():
        raise TargetedEvidenceError("The prepared batch folder is missing or unavailable.")
    return root


def _accepted_submission_sha(connection: sqlite3.Connection, batch_id: str, expected: str) -> str:
    source_count = int(
        connection.execute("SELECT COUNT(*) FROM inbox_batch_sources WHERE batch_id = ?", (batch_id,)).fetchone()[0]
    )
    rows = connection.execute(
        """
        SELECT settings_hash, COUNT(DISTINCT source_id) AS source_count, MAX(attempt_id) AS latest_attempt
        FROM inbox_attempts
        WHERE batch_id = ?
          AND attempt_type = 'preliminary_findings_import'
          AND status = 'accepted'
          AND completed_utc IS NOT NULL
        GROUP BY settings_hash
        ORDER BY latest_attempt DESC
        """,
        (batch_id,),
    ).fetchall()
    complete = [str(row["settings_hash"] or "") for row in rows if int(row["source_count"] or 0) == source_count]
    if expected:
        normalized = expected.strip().lower()
        if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
            raise TargetedEvidenceError("preliminary_submission_sha256 must be 64 lowercase hexadecimal characters.")
        if normalized not in complete:
            raise TargetedEvidenceError("The requested preliminary submission is not completely accepted in the ledger.")
        return normalized
    if not complete:
        raise TargetedEvidenceError("The batch has no completely accepted preliminary-findings submission.")
    return complete[0]


def _load_accepted_submission(
    ledger_path: Path,
    batch_root: Path,
    batch_id: str,
    expected_sha: str,
    *,
    allowed_batch_states: set[str] | None = None,
    allowed_source_states: set[str] | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    connection = _read_ledger(ledger_path)
    try:
        submission_sha = _accepted_submission_sha(connection, batch_id, expected_sha)
    finally:
        connection.close()
    history_root = batch_root / "imports" / "preliminary-findings" / submission_sha[:24]
    _require_within(batch_root, history_root, "Preliminary-findings history")
    submission_path = history_root / "preliminary-findings.json"
    validation_path = history_root / "validation.json"
    if not submission_path.is_file() or review_ledger.sha256_file(submission_path) != submission_sha:
        raise TargetedEvidenceError("The accepted preliminary-findings submission is missing or its SHA-256 no longer matches.")
    terminal_state, _terminal_problems = review_findings._terminal_submission_state(ledger_path, batch_id, submission_sha)
    if terminal_state != "accepted":
        raise TargetedEvidenceError("The preliminary-findings submission has no committed accepted ledger attempt.")
    validation = review_findings._existing_validation(validation_path)
    if validation is None:
        raise TargetedEvidenceError("The accepted preliminary-findings validation record is missing or malformed.")
    if validation.get("accepted") is not True or str(validation.get("import_phase") or "") != "accepted":
        validation["accepted"] = True
        validation["import_phase"] = "accepted"
        validation["resulting_batch_state"] = "preliminary_findings_received"
        validation["reconciled_from_ledger_utc"] = _utc_now()
        _atomic_json(validation_path, validation)
    try:
        document = json.loads(submission_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TargetedEvidenceError(f"The accepted preliminary-findings submission cannot be parsed: {exc}.") from exc
    context, problems = review_findings._batch_context(
        ledger_path,
        batch_root,
        batch_id,
        allowed_batch_states=allowed_batch_states or TARGET_BATCH_STATES,
        allowed_source_states=allowed_source_states or TARGET_SOURCE_STATES,
    )
    problems.extend(review_findings.validate_document(document, context))
    if problems:
        raise TargetedEvidenceError("Accepted preliminary findings failed revalidation: " + " ".join(problems))
    expected_finding_ids = {str(item["finding_id"]) for item in document.get("findings") or []}
    connection = _read_ledger(ledger_path)
    try:
        rows = connection.execute(
            "SELECT finding_id, details_json FROM inbox_findings WHERE batch_id = ? AND stage = 'preliminary'",
            (batch_id,),
        ).fetchall()
    finally:
        connection.close()
    ledger_finding_ids: set[str] = set()
    for row in rows:
        try:
            details = json.loads(str(row["details_json"] or "{}"))
        except json.JSONDecodeError:
            continue
        if str(details.get("submission_sha256") or "") == submission_sha:
            ledger_finding_ids.add(str(row["finding_id"]))
    if ledger_finding_ids != expected_finding_ids:
        raise TargetedEvidenceError("Accepted preliminary finding identities contradict the normalized ledger history.")
    return submission_sha, document, context


def _request_interval(request: dict[str, Any], duration: float) -> dict[str, Any]:
    timestamp = dict(request["timestamp"])
    if timestamp["kind"] == "point":
        requested_start = requested_end = float(timestamp["at_seconds"])
    else:
        requested_start = float(timestamp["start_seconds"])
        requested_end = float(timestamp["end_seconds"])
    frames = dict(request["frames"])
    panels = dict(request["panels"])
    audio = dict(request["audio"])
    visual_contexts = [item for item in (frames, panels) if item.get("requested") is True]
    visual_before = max((float(item["before_seconds"]) for item in visual_contexts), default=0.0)
    visual_after = max((float(item["after_seconds"]) for item in visual_contexts), default=0.0)
    audio_before = float(audio["before_seconds"]) if audio.get("requested") is True else 0.0
    audio_after = float(audio["after_seconds"]) if audio.get("requested") is True else 0.0
    visual_unclipped = (requested_start - visual_before, requested_end + visual_after)
    audio_unclipped = (requested_start - audio_before, requested_end + audio_after)
    visual_effective = (max(0.0, visual_unclipped[0]), min(duration, visual_unclipped[1]))
    audio_effective = (max(0.0, audio_unclipped[0]), min(duration, audio_unclipped[1]))
    requested_types = [name for name, value in (("frames", frames), ("panels", panels), ("audio", audio)) if value.get("requested") is True]
    intervals = []
    if visual_contexts:
        intervals.append(visual_effective)
    if audio.get("requested") is True:
        intervals.append(audio_effective)
    effective = (min(item[0] for item in intervals), max(item[1] for item in intervals))
    warnings: list[str] = []
    if visual_contexts and visual_unclipped != visual_effective:
        warnings.append("Visual context was clipped to the validated source duration.")
    if audio.get("requested") is True and audio_unclipped != audio_effective:
        warnings.append("Audio context was clipped to the validated source duration.")
    return {
        "submitted_timestamp": timestamp,
        "requested_interval": {"start_seconds": requested_start, "end_seconds": requested_end},
        "visual_interval": {"start_seconds": visual_effective[0], "end_seconds": visual_effective[1]},
        "audio_interval": {"start_seconds": audio_effective[0], "end_seconds": audio_effective[1]},
        "effective_interval": {"start_seconds": effective[0], "end_seconds": effective[1]},
        "requested_evidence_types": requested_types,
        "warnings": warnings,
    }


def deterministic_frame_timestamps(
    effective_start: float,
    effective_end: float,
    requested_start: float,
    requested_end: float,
    maximum: int,
) -> list[float]:
    """Return deterministic bounded samples while preserving requested boundaries."""

    limit = max(1, int(maximum))
    if limit == 1:
        return [round((requested_start + requested_end) / 2.0, 3)]
    priority = [requested_start]
    if requested_end != requested_start:
        priority.append(requested_end)
    priority.extend([effective_start, effective_end])
    span = max(0.0, effective_end - effective_start)
    dense_count = max(limit * 4, 2)
    candidates = [effective_start + (span * index / (dense_count - 1)) for index in range(dense_count)]
    selected: list[float] = []
    seen: set[int] = set()
    for value in [*priority, *candidates]:
        clipped = max(effective_start, min(effective_end, float(value)))
        key = int(round(clipped * 1000))
        if key in seen:
            continue
        seen.add(key)
        selected.append(round(clipped, 3))
        if len(selected) == limit:
            break
    return sorted(selected)


def _request_contract(
    submission_sha: str,
    source_identity: str,
    finding: dict[str, Any],
    request: dict[str, Any],
    source_manifest: dict[str, Any],
) -> dict[str, Any]:
    audio_selection = source_manifest.get("audio_selection") if isinstance(source_manifest.get("audio_selection"), dict) else {}
    return {
        "render_version": RENDER_VERSION,
        "preliminary_submission_sha256": submission_sha,
        "source_identity": source_identity,
        "finding_id": str(finding["finding_id"]),
        "request_id": str(request["request_id"]),
        "timestamp": request["timestamp"],
        "frames": request["frames"],
        "panels": request["panels"],
        "audio": request["audio"],
        "selected_audio_ordinal": audio_selection.get("selected_ordinal"),
        "selected_audio_layout_identity": str(
            (source_manifest.get("media_metadata") or {}).get("audio_layout_fingerprint") or ""
        ),
        "renderer_profile": {
            "shared_task_shape": "workflow3_codex_evidence",
            "frame_quality": 3,
            "audio_codec": "libmp3lame",
            "audio_bitrate": "192k",
            "panel_layout": "three_panel_5760x1080",
        },
    }


def _request_final_root(batch_root: Path, source_token: str, finding_id: str, request_id: str) -> tuple[Path, str, str]:
    finding_token = "f-" + _token(finding_id, length=16)
    request_token = "r-" + _token(finding_id, request_id, length=16)
    root = batch_root / "sources" / source_token / "targeted-evidence" / finding_token / request_token
    _require_within(batch_root, root, "Targeted-evidence request path")
    return root, finding_token, request_token


def _verify_integrity(root: Path, expected_signature: str) -> tuple[bool, list[str]]:
    problems: list[str] = []
    manifest_path = root / "request-manifest.json"
    integrity_path = root / "integrity.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, [f"Targeted-evidence manifest/integrity could not be read: {exc}."]
    if not isinstance(manifest, dict) or not isinstance(integrity, dict):
        return False, ["Targeted-evidence manifest/integrity must contain JSON objects."]
    if manifest.get("complete") is not True or str(manifest.get("render_signature") or "") != expected_signature:
        problems.append("Targeted-evidence request manifest is incomplete or has the wrong render signature.")
    if integrity.get("complete") is not True or str(integrity.get("render_signature") or "") != expected_signature:
        problems.append("Targeted-evidence integrity record is incomplete or has the wrong render signature.")

    root_resolved = root.resolve()

    def inventory_target(raw_path: object, label: str) -> tuple[str, Path, str] | None:
        if not isinstance(raw_path, str) or not raw_path.strip():
            problems.append(f"{label} has an empty or non-string path.")
            return None
        relative = Path(raw_path)
        if relative.is_absolute():
            problems.append(f"{label} path must be relative to the request package: {raw_path}.")
            return None
        target = (root / relative).resolve()
        if not _within(root_resolved, target):
            problems.append(f"{label} path escapes the request package: {raw_path}.")
            return None
        canonical = target.relative_to(root_resolved).as_posix()
        if canonical in {"", ".", "integrity.json"}:
            problems.append(f"{label} contains an invalid package path: {raw_path}.")
            return None
        return os.path.normcase(canonical), target, canonical

    expected: dict[str, tuple[Path, str]] = {
        os.path.normcase("request-manifest.json"): (manifest_path.resolve(), "request-manifest.json")
    }
    artifact_inventory = manifest.get("artifact_inventory")
    if not isinstance(artifact_inventory, list):
        problems.append("Targeted-evidence request manifest artifact inventory is missing.")
        artifact_inventory = []
    for artifact in artifact_inventory:
        if not isinstance(artifact, dict):
            problems.append("Targeted-evidence request manifest contains a malformed artifact record.")
            continue
        parsed = inventory_target(artifact.get("path"), "Manifest artifact")
        if parsed is None:
            continue
        key, target, canonical = parsed
        if key in expected:
            problems.append(f"Targeted-evidence request manifest contains a duplicate artifact path: {canonical}.")
            continue
        expected[key] = (target, canonical)

    records = integrity.get("files")
    if not isinstance(records, list):
        problems.append("Targeted-evidence integrity file inventory is missing.")
        return False, problems
    recorded: dict[str, tuple[dict[str, Any], Path, str]] = {}
    for record in records:
        if not isinstance(record, dict):
            problems.append("Targeted-evidence integrity inventory contains a malformed record.")
            continue
        parsed = inventory_target(record.get("path"), "Integrity record")
        if parsed is None:
            continue
        key, target, canonical = parsed
        if key in recorded:
            problems.append(f"Targeted-evidence integrity inventory contains a duplicate path: {canonical}.")
            continue
        recorded[key] = (record, target, canonical)

    expected_keys = set(expected)
    recorded_keys = set(recorded)
    for key in sorted(expected_keys - recorded_keys):
        problems.append(f"Targeted-evidence integrity inventory omits a required file: {expected[key][1]}.")
    for key in sorted(recorded_keys - expected_keys):
        problems.append(f"Targeted-evidence integrity inventory contains an unexplained file: {recorded[key][2]}.")

    actual: dict[str, tuple[Path, str]] = {}
    try:
        package_files = sorted((path for path in root.rglob("*") if path.is_file()), key=lambda path: str(path).casefold())
    except OSError as exc:
        problems.append(f"Targeted-evidence package file inventory could not be enumerated: {exc}.")
        package_files = []
    for path in package_files:
        lexical_relative = path.relative_to(root).as_posix()
        if os.path.normcase(lexical_relative) == os.path.normcase("integrity.json"):
            continue
        if path.is_symlink():
            problems.append(f"Targeted-evidence package contains an unsupported symbolic link: {lexical_relative}.")
            continue
        resolved = path.resolve()
        if not _within(root_resolved, resolved):
            problems.append(f"Targeted-evidence package file escapes the request package: {lexical_relative}.")
            continue
        canonical = resolved.relative_to(root_resolved).as_posix()
        key = os.path.normcase(canonical)
        if key in actual:
            problems.append(f"Targeted-evidence package contains duplicate physical paths: {canonical}.")
            continue
        actual[key] = (resolved, canonical)

    actual_keys = set(actual)
    for key in sorted(expected_keys - actual_keys):
        problems.append(f"Targeted-evidence package is missing a manifest-declared file: {expected[key][1]}.")
    for key in sorted(actual_keys - expected_keys):
        problems.append(f"Targeted-evidence package contains an unexplained file: {actual[key][1]}.")
    for key in sorted(recorded_keys - actual_keys):
        problems.append(f"Targeted-evidence integrity record references a missing file: {recorded[key][2]}.")
    for key in sorted(actual_keys - recorded_keys):
        problems.append(f"Targeted-evidence package file is not recorded by integrity: {actual[key][1]}.")

    for key in sorted(expected_keys & recorded_keys & actual_keys):
        record, _record_target, canonical = recorded[key]
        target = actual[key][0]
        try:
            expected_size = int(record.get("size_bytes"))
        except (TypeError, ValueError):
            problems.append(f"Targeted-evidence integrity size is invalid: {canonical}.")
            continue
        if target.stat().st_size != expected_size:
            problems.append(f"Targeted-evidence artifact size changed: {canonical}.")
            continue
        expected_sha = str(record.get("sha256") or "")
        if review_ledger.sha256_file(target) != expected_sha:
            problems.append(f"Targeted-evidence artifact hash changed: {canonical}.")
    return not problems, problems


def _resolve_source_location(
    ledger_path: Path,
    source_id: int,
    stable_identity: str,
    hasher: Callable[[Path], str],
) -> dict[str, Any]:
    expected_sha = stable_identity.removeprefix("sha256:")
    connection = _read_ledger(ledger_path)
    try:
        rows = connection.execute(
            """
            SELECT location_id, original_path, normalized_path, is_current
            FROM inbox_source_locations
            WHERE source_id = ?
            ORDER BY is_current DESC, last_seen_utc DESC, location_id DESC
            """,
            (source_id,),
        ).fetchall()
    finally:
        connection.close()
    mismatched = False
    unstable = False
    for row in rows:
        path = Path(str(row["original_path"] or ""))
        try:
            if not path.is_file() or not os.access(path, os.R_OK):
                continue
            before = path.stat()
            digest = str(hasher(path)).lower()
            after = path.stat()
        except OSError:
            continue
        if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
            unstable = True
            continue
        if digest != expected_sha:
            mismatched = True
            continue
        connection = inbox_records.connect(ledger_path, must_exist=True)
        try:
            now = _utc_now()
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("UPDATE inbox_source_locations SET is_current = 0 WHERE source_id = ?", (source_id,))
            connection.execute(
                """
                UPDATE inbox_source_locations
                SET is_current = 1, size_bytes = ?, modified_ns = ?, modified_utc = ?, last_seen_utc = ?
                WHERE location_id = ?
                """,
                (before.st_size, before.st_mtime_ns, _modified_utc(before), now, int(row["location_id"])),
            )
            connection.commit()
        finally:
            connection.close()
        return {
            "source_id": source_id,
            "source_path": str(path),
            "source_name": path.name,
            "stable_identity": stable_identity,
            "content_sha256": digest,
            "location_id": int(row["location_id"]),
            "relocated": not bool(row["is_current"]),
            "before": _stat_record(before),
            "after_hash": _stat_record(after),
        }
    if unstable:
        raise SourceResolutionError("The source changed while its stable identity was being verified; retry after it is stable.", "source_changed")
    if mismatched:
        raise SourceResolutionError("No recorded source location matches the accepted stable SHA-256 identity.", "source_changed")
    raise SourceResolutionError("No readable recorded location is currently available for this source.", "retryable_failure")


def _upsert_failure(
    ledger_path: Path,
    batch_id: str,
    source_id: int,
    signature: str,
    state: str,
    message: str,
    details: dict[str, Any],
) -> None:
    connection = inbox_records.connect(ledger_path, must_exist=True)
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            """
            SELECT attempt_id FROM inbox_attempts
            WHERE source_id = ? AND batch_id = ? AND attempt_type = 'targeted_evidence_render' AND settings_hash = ?
              AND status IN ('retryable_failure', 'source_changed')
            ORDER BY attempt_id DESC LIMIT 1
            """,
            (source_id, batch_id, signature),
        ).fetchone()
        now = _utc_now()
        if existing is None:
            connection.execute(
                """
                INSERT INTO inbox_attempts
                    (source_id, batch_id, attempt_type, status, started_utc, completed_utc, settings_hash, error_message)
                VALUES (?, ?, 'targeted_evidence_render', ?, ?, ?, ?, ?)
                """,
                (source_id, batch_id, state, now, now, signature, message),
            )
        else:
            connection.execute(
                "UPDATE inbox_attempts SET status = ?, completed_utc = ?, error_message = ? WHERE attempt_id = ?",
                (state, now, message, int(existing["attempt_id"])),
            )
        old_source = str(connection.execute("SELECT lifecycle_state FROM inbox_sources WHERE source_id = ?", (source_id,)).fetchone()[0])
        old_batch_source = str(
            connection.execute("SELECT state FROM inbox_batch_sources WHERE batch_id = ? AND source_id = ?", (batch_id, source_id)).fetchone()[0]
        )
        connection.execute("UPDATE inbox_sources SET lifecycle_state = ?, updated_utc = ? WHERE source_id = ?", (state, now, source_id))
        connection.execute("UPDATE inbox_batch_sources SET state = ?, updated_utc = ? WHERE batch_id = ? AND source_id = ?", (state, now, batch_id, source_id))
        if old_source != state or old_batch_source != state:
            review_ledger._insert_lifecycle_event(
                connection,
                source_id=source_id,
                batch_id=batch_id,
                event_type="targeted_evidence_failed",
                from_state=old_source,
                to_state=state,
                details={**details, "render_signature": signature, "error": message},
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _source_manifest(context: dict[str, Any], identity: str) -> dict[str, Any]:
    value = context["sources"][identity].get("source_manifest")
    if not isinstance(value, dict):
        raise TargetedEvidenceError(f"Prepared source manifest is unavailable for {identity}.")
    return value


def _request_specs(
    batch_root: Path,
    submission_sha: str,
    document: dict[str, Any],
    context: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    requests: list[dict[str, Any]] = []
    requested_sources: set[str] = set()
    for finding in document.get("findings") or []:
        identity = str(finding["source_identity"])
        requested_sources.add(identity)
        source_info = context["sources"][identity]
        source_manifest = _source_manifest(context, identity)
        duration = float(source_info["duration_seconds"])
        source_token = str(source_info["source_token"])
        for request in finding.get("requests") or []:
            interval = _request_interval(request, duration)
            signature_contract = _request_contract(submission_sha, identity, finding, request, source_manifest)
            signature = _canonical_sha(signature_contract)
            final_root, finding_token, request_token = _request_final_root(
                batch_root,
                source_token,
                str(finding["finding_id"]),
                str(request["request_id"]),
            )
            requests.append(
                {
                    "source_id": int(source_info["source_id"]),
                    "source_identity": identity,
                    "source_token": source_token,
                    "finding_id": str(finding["finding_id"]),
                    "request_id": str(request["request_id"]),
                    "finding_token": finding_token,
                    "request_token": request_token,
                    "render_signature": signature,
                    "render_signature_contract": signature_contract,
                    "request": request,
                    "interval": interval,
                    "duration_seconds": duration,
                    "final_root": str(final_root),
                }
            )
    no_request_sources = [
        {
            "source_id": int(context["sources"][identity]["source_id"]),
            "source_identity": identity,
            "source_token": str(context["sources"][identity]["source_token"]),
            "accounting_signature": _canonical_sha(
                {
                    "render_version": RENDER_VERSION,
                    "preliminary_submission_sha256": submission_sha,
                    "source_identity": identity,
                    "targeted_evidence_requested": False,
                }
            ),
        }
        for identity in document.get("reviewed_source_identities") or []
        if identity not in requested_sources
    ]
    return requests, no_request_sources


def _panel_definitions(requested_ids: list[str]) -> list[dict[str, Any]]:
    definitions = {str(item["role"]): dict(item) for item in panel_layout.resolve_panel_definitions()}
    unsupported = [item for item in requested_ids if item not in definitions]
    if unsupported:
        raise TargetedEvidenceError("Requested panel definitions are no longer supported: " + ", ".join(unsupported) + ".")
    return [definitions[item] for item in requested_ids]


def _build_stage_plan(
    batch_root: Path,
    request_spec: dict[str, Any],
    resolved_source: dict[str, Any],
) -> dict[str, Any]:
    signature = str(request_spec["render_signature"])
    targeted_staging = batch_root / ".staging" / "targeted-evidence"
    stage_root = targeted_staging / "requests" / signature[:24]
    _require_within(targeted_staging, stage_root, "Targeted-evidence request staging")
    if stage_root.exists():
        _safe_remove_tree(targeted_staging, stage_root)
    stage_root.mkdir(parents=True, exist_ok=True)
    request = dict(request_spec["request"])
    interval = dict(request_spec["interval"])
    frames_requested = bool(request["frames"]["requested"])
    panels_requested = bool(request["panels"]["requested"])
    audio_requested = bool(request["audio"]["requested"])
    if frames_requested:
        maximum = int(request["frames"]["max_frames"])
    else:
        maximum = PANEL_ONLY_MAX_FRAMES
    visual = interval["visual_interval"]
    requested = interval["requested_interval"]
    timestamps = (
        deterministic_frame_timestamps(
            float(visual["start_seconds"]),
            float(visual["end_seconds"]),
            float(requested["start_seconds"]),
            float(requested["end_seconds"]),
            maximum,
        )
        if frames_requested or panels_requested
        else []
    )
    panels = _panel_definitions(list(request["panels"]["panel_ids"])) if panels_requested else []
    frame_tasks: list[dict[str, Any]] = []
    for index, timestamp in enumerate(timestamps, 1):
        frame_relative = f"frames/frame-{index:03d}.jpg"
        panel_tasks = []
        for panel in panels:
            panel_relative = f"panels/{panel['role']}/panel-{index:03d}.jpg"
            panel_tasks.append(
                {
                    **panel,
                    "relative_path": panel_relative,
                    "path": str(stage_root / panel_relative),
                }
            )
        frame_tasks.append(
            {
                "evidence_id": f"{request_spec['finding_id']}:{request_spec['request_id']}",
                "source_id": request_spec["source_token"],
                "source_path": resolved_source["source_path"],
                "timestamp_seconds": timestamp,
                "relative_path": frame_relative,
                "path": str(stage_root / frame_relative),
                "panel_crop_mode": "on" if panels_requested else "off",
                "panels": panel_tasks,
                "retain_full_frame": frames_requested,
            }
        )
    audio_tasks: list[dict[str, Any]] = []
    source_manifest = request_spec["source_manifest"]
    audio_selection = source_manifest.get("audio_selection") if isinstance(source_manifest.get("audio_selection"), dict) else {}
    if audio_requested:
        selected = audio_selection.get("selected_ordinal")
        streams = list((source_manifest.get("media_metadata") or {}).get("audio_streams") or [])
        if selected is None or not any(int(item.get("ordinal", -1)) == int(selected) for item in streams if isinstance(item, dict)):
            raise TargetedEvidenceError("Requested audio cannot be rendered because the prepared selected-audio ordinal is missing or invalid.")
        audio_interval = interval["audio_interval"]
        start = float(audio_interval["start_seconds"])
        end = float(audio_interval["end_seconds"])
        audio_relative = "audio/selected-audio.mp3"
        audio_tasks.append(
            {
                "evidence_id": f"{request_spec['finding_id']}:{request_spec['request_id']}",
                "source_id": request_spec["source_token"],
                "source_path": resolved_source["source_path"],
                "audio_input_path": resolved_source["source_path"],
                "audio_stream_index": int(selected),
                "start_seconds": start,
                "duration_seconds": end - start,
                "relative_path": audio_relative,
                "path": str(stage_root / audio_relative),
            }
        )
    manifest = {
        "contract_version": CONTRACT_VERSION,
        "render_version": RENDER_VERSION,
        "batch_id": request_spec["batch_id"],
        "preliminary_submission_sha256": request_spec["submission_sha256"],
        "source_identity": request_spec["source_identity"],
        "source_token": request_spec["source_token"],
        "finding_id": request_spec["finding_id"],
        "request_id": request_spec["request_id"],
        "finding_token": request_spec["finding_token"],
        "request_token": request_spec["request_token"],
        "requested": request,
        **interval,
        "deterministic_frame_timestamps": timestamps,
        "selected_audio_ordinal": audio_selection.get("selected_ordinal"),
        "selected_audio_layout_identity": str((source_manifest.get("media_metadata") or {}).get("audio_layout_fingerprint") or ""),
        "render_signature": signature,
        "render_signature_contract": request_spec["render_signature_contract"],
        "source_verification_before": {
            "source_identity": resolved_source["stable_identity"],
            "size_bytes": resolved_source["before"]["size_bytes"],
            "modified_ns": resolved_source["before"]["modified_ns"],
            "full_sha256": resolved_source["content_sha256"],
            "relocated": bool(resolved_source.get("relocated")),
        },
        "artifact_inventory": [],
        "warnings": list(interval.get("warnings") or []),
        "complete": False,
        "created_utc": _utc_now(),
    }
    _atomic_json(stage_root / "request-manifest.json", manifest)
    return {
        **request_spec,
        "stage_root": str(stage_root),
        "frame_tasks": frame_tasks,
        "audio_tasks": audio_tasks,
        "existing_complete": False,
        "source_verification_before": resolved_source,
    }


def _quarantine_invalid_request(batch_root: Path, final_root: Path, signature: str) -> str:
    quarantine_root = batch_root / ".staging" / "targeted-evidence" / "quarantine"
    quarantine_root.mkdir(parents=True, exist_ok=True)
    target = quarantine_root / f"{signature[:16]}-{uuid.uuid4().hex[:8]}"
    _require_within(batch_root / ".staging", target, "Invalid targeted-evidence quarantine")
    safe_write.move(final_root, target)
    return str(target)


def _write_plan(batch_root: Path, plan: dict[str, Any]) -> tuple[Path, str]:
    root = batch_root / ".staging" / "targeted-evidence"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"render-plan-{str(plan['preliminary_submission_sha256'])[:16]}.json"
    _atomic_json(path, plan)
    return path, review_ledger.sha256_file(path)


def _completed_attempt_exists(connection: sqlite3.Connection, batch_id: str, source_id: int, signature: str) -> bool:
    return connection.execute(
        """
        SELECT 1 FROM inbox_attempts
        WHERE batch_id = ? AND source_id = ? AND attempt_type = 'targeted_evidence_render'
          AND settings_hash = ? AND status = 'completed' AND completed_utc IS NOT NULL
        LIMIT 1
        """,
        (batch_id, source_id, signature),
    ).fetchone() is not None


def _all_ledger_requests_complete(ledger_path: Path, batch_id: str, request_specs: list[dict[str, Any]]) -> bool:
    connection = _read_ledger(ledger_path)
    try:
        return all(
            _completed_attempt_exists(connection, batch_id, int(item["source_id"]), str(item["render_signature"]))
            for item in request_specs
        )
    finally:
        connection.close()


def _mark_recovery_pending(ledger_path: Path, batch_id: str, source_ids: set[int], submission_sha: str) -> None:
    """Downgrade stale ready state when a required final package is missing or invalid."""

    if not source_ids:
        return
    connection = inbox_records.connect(ledger_path, must_exist=True)
    try:
        connection.execute("BEGIN IMMEDIATE")
        now = _utc_now()
        for source_id in sorted(source_ids):
            state_row = connection.execute(
                """
                SELECT s.lifecycle_state AS source_state, bs.state AS batch_source_state
                FROM inbox_sources s
                JOIN inbox_batch_sources bs ON bs.source_id = s.source_id AND bs.batch_id = ?
                WHERE s.source_id = ?
                """,
                (batch_id, source_id),
            ).fetchone()
            if state_row is None:
                raise TargetedEvidenceError("Targeted-evidence recovery could not resolve the affected batch source.")
            source_state = str(state_row["source_state"])
            batch_source_state = str(state_row["batch_source_state"])
            if source_state != "targeted_evidence_ready" and batch_source_state != "targeted_evidence_ready":
                continue
            connection.execute(
                "UPDATE inbox_sources SET lifecycle_state = 'preliminary_findings_received', updated_utc = ? WHERE source_id = ?",
                (now, source_id),
            )
            connection.execute(
                "UPDATE inbox_batch_sources SET state = 'preliminary_findings_received', updated_utc = ? WHERE batch_id = ? AND source_id = ?",
                (now, batch_id, source_id),
            )
            review_ledger._insert_lifecycle_event(
                connection,
                source_id=source_id,
                batch_id=batch_id,
                event_type="targeted_evidence_recovery_needed",
                from_state="targeted_evidence_ready",
                to_state="preliminary_findings_received",
                details={
                    "preliminary_submission_sha256": submission_sha,
                    "previous_source_state": source_state,
                    "previous_batch_source_state": batch_source_state,
                },
            )
        old_batch = str(connection.execute("SELECT status FROM inbox_batches WHERE batch_id = ?", (batch_id,)).fetchone()[0])
        if old_batch == "targeted_evidence_ready":
            connection.execute(
                "UPDATE inbox_batches SET status = 'preliminary_findings_received', updated_utc = ? WHERE batch_id = ?",
                (now, batch_id),
            )
            review_ledger._insert_lifecycle_event(
                connection,
                source_id=None,
                batch_id=batch_id,
                event_type="targeted_evidence_recovery_needed",
                from_state=old_batch,
                to_state="preliminary_findings_received",
                details={"preliminary_submission_sha256": submission_sha},
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def plan_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate accepted findings, resolve stable sources, and build Workflow 3 render tasks."""

    ledger_path = Path(str(payload.get("ledger_path") or ""))
    batch_id = str(payload.get("expected_batch_id") or payload.get("batch_id") or "")
    # 224 (Wave B2b): the records are asked, not the file (the ledger's name holds a note since the move).
    _read_ledger(ledger_path).close()
    if not batch_id:
        raise TargetedEvidenceError("expected_batch_id is required for targeted rendering.")
    batch_root = _resolve_batch_root(ledger_path, batch_id, str(payload.get("batch_path") or ""))
    submission_sha, document, context = _load_accepted_submission(
        ledger_path,
        batch_root,
        batch_id,
        str(payload.get("preliminary_submission_sha256") or ""),
    )
    request_specs, no_request_sources = _request_specs(batch_root, submission_sha, document, context)
    for item in request_specs:
        item["batch_id"] = batch_id
        item["submission_sha256"] = submission_sha
        item["source_manifest"] = _source_manifest(context, str(item["source_identity"]))
    existing_plans: list[dict[str, Any]] = []
    unresolved_by_source: dict[str, list[dict[str, Any]]] = {}
    warnings: list[str] = []
    for item in request_specs:
        final_root = Path(str(item["final_root"]))
        if final_root.exists():
            valid, integrity_problems = _verify_integrity(final_root, str(item["render_signature"]))
            if valid:
                existing_plans.append({**item, "existing_complete": True, "stage_root": "", "frame_tasks": [], "audio_tasks": []})
                continue
            quarantine = _quarantine_invalid_request(batch_root, final_root, str(item["render_signature"]))
            warnings.append(
                f"An invalid existing targeted-evidence package was preserved in batch staging quarantine: {Path(quarantine).name}. "
                + " ".join(integrity_problems)
            )
        unresolved_by_source.setdefault(str(item["source_identity"]), []).append(item)
    connection = _read_ledger(ledger_path)
    try:
        batch_state_row = connection.execute("SELECT status FROM inbox_batches WHERE batch_id = ?", (batch_id,)).fetchone()
        batch_already_ready = batch_state_row is not None and str(batch_state_row["status"]) == "targeted_evidence_ready"
    finally:
        connection.close()
    if unresolved_by_source:
        _mark_recovery_pending(
            ledger_path,
            batch_id,
            {int(context["sources"][identity]["source_id"]) for identity in unresolved_by_source},
            submission_sha,
        )
        batch_already_ready = False
    if (
        batch_already_ready
        and not unresolved_by_source
        and _all_ledger_requests_complete(ledger_path, batch_id, request_specs)
    ):
        plan = {
            "contract_version": CONTRACT_VERSION,
            "render_version": RENDER_VERSION,
            "action": "targeted_evidence",
            "status": "targeted_evidence_ready",
            "batch_id": batch_id,
            "batch_path": str(batch_root),
            "preliminary_submission_sha256": submission_sha,
            "finding_count": len(document.get("findings") or []),
            "request_count": len(request_specs),
            "completed_request_count": len(request_specs),
            "request_plans": existing_plans,
            "no_request_sources": no_request_sources,
            "source_failures": [],
            "warnings": warnings,
            "idempotent": True,
        }
        _refresh_review_materials(batch_root, plan)
        return plan
    hasher = payload.get("full_hasher") if callable(payload.get("full_hasher")) else review_ledger.sha256_file
    request_plans = list(existing_plans)
    source_failures: list[dict[str, Any]] = []
    for identity, source_requests in unresolved_by_source.items():
        source_info = context["sources"][identity]
        source_id = int(source_info["source_id"])
        failure_signature = _canonical_sha(
            {
                "render_version": RENDER_VERSION,
                "submission_sha256": submission_sha,
                "source_identity": identity,
                "stage": "source_resolution",
            }
        )
        try:
            resolved = _resolve_source_location(ledger_path, source_id, identity, hasher)
            for item in source_requests:
                request_plans.append(_build_stage_plan(batch_root, item, resolved))
        except (SourceResolutionError, TargetedEvidenceError) as exc:
            state = exc.state if isinstance(exc, SourceResolutionError) else "retryable_failure"
            failure = {
                "source_id": source_id,
                "source_identity": identity,
                "state": state,
                "error": str(exc),
                "render_signature": failure_signature,
            }
            source_failures.append(failure)
            _upsert_failure(
                ledger_path,
                batch_id,
                source_id,
                failure_signature,
                state,
                str(exc),
                {"preliminary_submission_sha256": submission_sha, "stage": "source_resolution"},
            )
    request_plans.sort(key=lambda item: (int(item["source_id"]), str(item["finding_id"]), str(item["request_id"])))
    plan = {
        "contract_version": CONTRACT_VERSION,
        "render_version": RENDER_VERSION,
        "action": "targeted_evidence",
        "status": "ready_to_render" if any(not item.get("existing_complete") for item in request_plans) or no_request_sources else "reconcile_ready",
        "batch_id": batch_id,
        "batch_path": str(batch_root),
        "ledger_path": str(ledger_path),
        "preliminary_submission_sha256": submission_sha,
        "finding_count": len(document.get("findings") or []),
        "request_count": len(request_specs),
        "request_plans": request_plans,
        "no_request_sources": no_request_sources,
        "source_failures": source_failures,
        "warnings": warnings,
        "created_utc": _utc_now(),
    }
    plan_path, plan_sha = _write_plan(batch_root, plan)
    return {
        **plan,
        "plan_path": str(plan_path),
        "plan_sha256": plan_sha,
        "frame_task_count": sum(len(item.get("frame_tasks") or []) for item in request_plans),
        "audio_task_count": sum(len(item.get("audio_tasks") or []) for item in request_plans),
        "completed_request_count": sum(bool(item.get("existing_complete")) for item in request_plans),
        "idempotent": False,
    }


def _load_plan(payload: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    plan_path = Path(str(payload.get("plan_path") or ""))
    expected_sha = str(payload.get("plan_sha256") or "").lower()
    if not plan_path.is_file() or len(expected_sha) != 64:
        raise TargetedEvidenceError("A valid targeted-evidence render plan path and SHA-256 are required.")
    if review_ledger.sha256_file(plan_path) != expected_sha:
        raise TargetedEvidenceError("The targeted-evidence render plan changed after validation.")
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TargetedEvidenceError(f"The targeted-evidence render plan cannot be read: {exc}.") from exc
    ledger_path = Path(str(plan.get("ledger_path") or ""))
    batch_id = str(plan.get("batch_id") or "")
    # 224 (Wave B2b): the plan's authority is the Inbox's records for its folder, which _resolve_batch_root
    # reads next; the file at the ledger's name is a note since the move.
    if not str(plan.get("ledger_path") or "").strip() or not batch_id:
        raise TargetedEvidenceError("The targeted-evidence render plan has no valid ledger/batch authority.")
    batch_root = _resolve_batch_root(ledger_path, batch_id, str(plan.get("batch_path") or ""))
    _require_within(batch_root / ".staging", plan_path, "Targeted-evidence render plan")
    for item in plan.get("request_plans") or []:
        if not isinstance(item, dict):
            raise TargetedEvidenceError("The targeted-evidence render plan contains a malformed request.")
        final_root = Path(str(item.get("final_root") or ""))
        _require_within(batch_root / "sources", final_root, "Targeted-evidence final request path")
        if not item.get("existing_complete"):
            stage_root = Path(str(item.get("stage_root") or ""))
            _require_within(batch_root / ".staging" / "targeted-evidence", stage_root, "Targeted-evidence request staging")
            for task in [*(item.get("frame_tasks") or []), *(item.get("audio_tasks") or [])]:
                _require_within(stage_root, Path(str(task.get("path") or "")), "Targeted-evidence artifact path")
                for panel in task.get("panels") or []:
                    _require_within(stage_root, Path(str(panel.get("path") or "")), "Targeted-evidence panel path")
    return plan_path, plan


def _result_maps(payload: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    frame_results: dict[str, dict[str, Any]] = {}
    panel_results: dict[str, dict[str, Any]] = {}
    for item in payload.get("frame_results") or []:
        if not isinstance(item, dict):
            continue
        if item.get("path"):
            frame_results[str(Path(str(item["path"])).resolve())] = item
        for panel in item.get("panels") or []:
            if isinstance(panel, dict) and panel.get("path"):
                panel_results[str(Path(str(panel["path"])).resolve())] = panel
    audio_results = {
        str(Path(str(item["path"])).resolve()): item
        for item in payload.get("audio_results") or []
        if isinstance(item, dict) and item.get("path")
    }
    return frame_results | panel_results, audio_results


def _render_result_ok(results: dict[str, dict[str, Any]], path: Path) -> bool:
    result = results.get(str(path.resolve()))
    return bool(result and str(result.get("status") or "").lower() in SUCCESS_RENDER_STATUSES and path.is_file())


def _verify_source_after(plan_item: dict[str, Any]) -> dict[str, Any]:
    before = dict(plan_item["source_verification_before"])
    path = Path(str(before["source_path"]))
    try:
        stat_before_hash = path.stat()
        digest = review_ledger.sha256_file(path)
        after = path.stat()
    except OSError as exc:
        raise SourceResolutionError(f"The source became unavailable after rendering: {exc}.", "retryable_failure") from exc
    expected_stat = dict(before["before"])
    if (
        stat_before_hash.st_size != int(expected_stat["size_bytes"])
        or stat_before_hash.st_mtime_ns != int(expected_stat["modified_ns"])
        or after.st_size != stat_before_hash.st_size
        or after.st_mtime_ns != stat_before_hash.st_mtime_ns
        or digest != str(before["content_sha256"])
    ):
        raise SourceResolutionError("The source changed while targeted evidence was being rendered.", "source_changed")
    return {"before_post_hash": _stat_record(stat_before_hash), "after_post_hash": _stat_record(after), "content_sha256": digest}


def _finalize_request_stage(
    batch_root: Path,
    plan_item: dict[str, Any],
    frame_and_panel_results: dict[str, dict[str, Any]],
    audio_results: dict[str, dict[str, Any]],
    source_after: dict[str, Any],
    *,
    leftovers: Path | None = None,
    cleanup_warnings: list[str] | None = None,
) -> tuple[bool, str, list[dict[str, Any]]]:
    if plan_item.get("existing_complete"):
        valid, problems = _verify_integrity(Path(str(plan_item["final_root"])), str(plan_item["render_signature"]))
        return valid, " ".join(problems), []
    stage_root = Path(str(plan_item["stage_root"]))
    _require_within(batch_root / ".staging", stage_root, "Targeted-evidence request staging")
    request = dict(plan_item["request"])
    inventory: list[dict[str, Any]] = []
    for task in plan_item.get("frame_tasks") or []:
        frame_path = Path(str(task["path"]))
        if not _render_result_ok(frame_and_panel_results, frame_path):
            return False, f"Requested frame was not rendered successfully: {frame_path.name}.", []
        if bool(task.get("retain_full_frame")):
            inventory.append(
                {
                    "artifact_id": f"frame:{float(task['timestamp_seconds']):.3f}",
                    "kind": "frame",
                    "timestamp_seconds": task["timestamp_seconds"],
                    "path": task["relative_path"],
                }
            )
        for panel in task.get("panels") or []:
            panel_path = Path(str(panel["path"]))
            if not _render_result_ok(frame_and_panel_results, panel_path):
                return False, f"Requested panel {panel['role']} was not rendered successfully.", []
            inventory.append(
                {
                    "artifact_id": f"panel:{panel['role']}:{float(task['timestamp_seconds']):.3f}",
                    "kind": "panel",
                    "panel_id": panel["role"],
                    "timestamp_seconds": task["timestamp_seconds"],
                    "path": panel["relative_path"],
                }
            )
        if not bool(task.get("retain_full_frame")):
            _require_within(stage_root, frame_path, "Disposable panel-source frame")
            safe_write.remove(frame_path, wait=safe_write.INBOX_WAIT_SECONDS)
    for task in plan_item.get("audio_tasks") or []:
        audio_path = Path(str(task["path"]))
        if not _render_result_ok(audio_results, audio_path):
            return False, "Requested selected-stream audio was not rendered successfully.", []
        inventory.append(
            {
                "artifact_id": f"audio:selected:{float(task['start_seconds']):.3f}:{float(task['duration_seconds']):.3f}",
                "kind": "audio",
                "selected_audio_ordinal": task["audio_stream_index"],
                "start_seconds": task["start_seconds"],
                "duration_seconds": task["duration_seconds"],
                "path": task["relative_path"],
            }
        )
    manifest_path = stage_root / "request-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifact_inventory"] = inventory
    manifest["source_verification_after"] = source_after
    manifest["complete"] = True
    manifest["completion_state"] = "complete"
    manifest["integrity_state"] = "verified"
    manifest["completed_utc"] = _utc_now()
    _atomic_json(manifest_path, manifest)
    records = review_preparation._hash_files(stage_root)
    _atomic_json(
        stage_root / "integrity.json",
        {
            "schema_version": 1,
            "render_version": RENDER_VERSION,
            "render_signature": plan_item["render_signature"],
            "complete": True,
            "files": records,
        },
    )
    valid, problems = _verify_integrity(stage_root, str(plan_item["render_signature"]))
    if not valid:
        return False, " ".join(problems), []
    final_root = Path(str(plan_item["final_root"]))
    _require_within(batch_root / "sources", final_root, "Targeted-evidence final request path")
    final_root.parent.mkdir(parents=True, exist_ok=True)
    if final_root.exists():
        existing_valid, existing_problems = _verify_integrity(final_root, str(plan_item["render_signature"]))
        if not existing_valid:
            return False, "A conflicting final request package failed integrity: " + " ".join(existing_problems), []
        # The verified package is already in place: this staged copy is a leftover (224, Decision 3).
        try:
            _safe_remove_tree(batch_root / ".staging", stage_root, leftovers)
        except (safe_write.FileInUse, safe_write.FileStepRefused) as exc:
            if cleanup_warnings is not None:
                cleanup_warnings.append(f"The result was kept. {exc} It is removed at the next run.")
    else:
        safe_write.move(stage_root, final_root)
    return True, "", inventory


def _record_completion(
    ledger_path: Path,
    plan: dict[str, Any],
    completed: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> str:
    batch_id = str(plan["batch_id"])
    now = _utc_now()
    connection = inbox_records.connect(ledger_path, must_exist=True)
    try:
        connection.execute("BEGIN IMMEDIATE")
        for item in completed:
            source_id = int(item["source_id"])
            signature = str(item["render_signature"])
            if _completed_attempt_exists(connection, batch_id, source_id, signature):
                continue
            connection.execute(
                """
                INSERT INTO inbox_attempts
                    (source_id, batch_id, attempt_type, status, started_utc, completed_utc, settings_hash)
                VALUES (?, ?, 'targeted_evidence_render', 'completed', ?, ?, ?)
                """,
                (source_id, batch_id, now, now, signature),
            )
            current_state = str(connection.execute("SELECT lifecycle_state FROM inbox_sources WHERE source_id = ?", (source_id,)).fetchone()[0])
            review_ledger._insert_lifecycle_event(
                connection,
                source_id=source_id,
                batch_id=batch_id,
                event_type="targeted_evidence_request_completed",
                from_state=current_state,
                to_state=current_state,
                details={
                    "preliminary_submission_sha256": plan["preliminary_submission_sha256"],
                    "finding_id": item["finding_id"],
                    "request_id": item["request_id"],
                    "render_signature": signature,
                },
            )
        for failure in failures:
            source_id = int(failure["source_id"])
            signature = str(failure["render_signature"])
            failure_state = str(failure.get("state") or "retryable_failure")
            if failure_state not in {"retryable_failure", "source_changed"}:
                failure_state = "retryable_failure"
            existing = connection.execute(
                """
                SELECT attempt_id FROM inbox_attempts
                WHERE source_id = ? AND batch_id = ? AND attempt_type = 'targeted_evidence_render'
                  AND settings_hash = ? AND status IN ('retryable_failure', 'source_changed')
                ORDER BY attempt_id DESC LIMIT 1
                """,
                (source_id, batch_id, signature),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO inbox_attempts
                        (source_id, batch_id, attempt_type, status, started_utc, completed_utc, settings_hash, error_message)
                    VALUES (?, ?, 'targeted_evidence_render', ?, ?, ?, ?, ?)
                    """,
                    (source_id, batch_id, failure_state, now, now, signature, failure["error"]),
                )
            else:
                connection.execute(
                    "UPDATE inbox_attempts SET completed_utc = ?, error_message = ? WHERE attempt_id = ?",
                    (now, failure["error"], int(existing["attempt_id"])),
                )
            old = str(connection.execute("SELECT lifecycle_state FROM inbox_sources WHERE source_id = ?", (source_id,)).fetchone()[0])
            connection.execute("UPDATE inbox_sources SET lifecycle_state = ?, updated_utc = ? WHERE source_id = ?", (failure_state, now, source_id))
            connection.execute(
                "UPDATE inbox_batch_sources SET state = ?, updated_utc = ? WHERE batch_id = ? AND source_id = ?",
                (failure_state, now, batch_id, source_id),
            )
            if old != failure_state:
                review_ledger._insert_lifecycle_event(
                    connection,
                    source_id=source_id,
                    batch_id=batch_id,
                    event_type="targeted_evidence_source_changed" if failure_state == "source_changed" else "targeted_evidence_failed",
                    from_state=old,
                    to_state=failure_state,
                    details={"render_signature": signature, "error": failure["error"]},
                )
        request_plans = list(plan.get("request_plans") or [])
        by_source: dict[int, list[dict[str, Any]]] = {}
        for item in request_plans:
            by_source.setdefault(int(item["source_id"]), []).append(item)
        for no_request in plan.get("no_request_sources") or []:
            source_id = int(no_request["source_id"])
            signature = str(no_request["accounting_signature"])
            exists = connection.execute(
                """
                SELECT 1 FROM inbox_attempts
                WHERE source_id = ? AND batch_id = ? AND attempt_type = 'targeted_evidence_accounting'
                  AND settings_hash = ? AND status = 'completed'
                LIMIT 1
                """,
                (source_id, batch_id, signature),
            ).fetchone()
            old = str(connection.execute("SELECT lifecycle_state FROM inbox_sources WHERE source_id = ?", (source_id,)).fetchone()[0])
            if exists is None:
                connection.execute(
                    """
                    INSERT INTO inbox_attempts
                        (source_id, batch_id, attempt_type, status, started_utc, completed_utc, settings_hash)
                    VALUES (?, ?, 'targeted_evidence_accounting', 'completed', ?, ?, ?)
                    """,
                    (source_id, batch_id, now, now, signature),
                )
                review_ledger._insert_lifecycle_event(
                    connection,
                    source_id=source_id,
                    batch_id=batch_id,
                    event_type="targeted_evidence_not_requested",
                    from_state=old,
                    to_state="targeted_evidence_ready",
                    details={
                        "preliminary_submission_sha256": plan["preliminary_submission_sha256"],
                        "accounting_signature": signature,
                    },
                )
            connection.execute("UPDATE inbox_sources SET lifecycle_state = 'targeted_evidence_ready', updated_utc = ? WHERE source_id = ?", (now, source_id))
            connection.execute(
                "UPDATE inbox_batch_sources SET state = 'targeted_evidence_ready', updated_utc = ? WHERE batch_id = ? AND source_id = ?",
                (now, batch_id, source_id),
            )
        for source_id, items in by_source.items():
            if any(int(failure["source_id"]) == source_id for failure in failures):
                continue
            all_complete = all(
                _completed_attempt_exists(connection, batch_id, source_id, str(item["render_signature"]))
                for item in items
            )
            if not all_complete:
                continue
            old = str(connection.execute("SELECT lifecycle_state FROM inbox_sources WHERE source_id = ?", (source_id,)).fetchone()[0])
            if old != "targeted_evidence_ready":
                connection.execute("UPDATE inbox_sources SET lifecycle_state = 'targeted_evidence_ready', updated_utc = ? WHERE source_id = ?", (now, source_id))
                connection.execute(
                    "UPDATE inbox_batch_sources SET state = 'targeted_evidence_ready', updated_utc = ? WHERE batch_id = ? AND source_id = ?",
                    (now, batch_id, source_id),
                )
                review_ledger._insert_lifecycle_event(
                    connection,
                    source_id=source_id,
                    batch_id=batch_id,
                    event_type="targeted_evidence_ready",
                    from_state=old,
                    to_state="targeted_evidence_ready",
                    details={
                        "preliminary_submission_sha256": plan["preliminary_submission_sha256"],
                        "render_signatures": [str(item["render_signature"]) for item in items],
                    },
                )
        states = [
            str(row[0])
            for row in connection.execute("SELECT state FROM inbox_batch_sources WHERE batch_id = ? ORDER BY ordinal", (batch_id,)).fetchall()
        ]
        batch_ready = bool(states) and all(state == "targeted_evidence_ready" for state in states)
        old_batch = str(connection.execute("SELECT status FROM inbox_batches WHERE batch_id = ?", (batch_id,)).fetchone()[0])
        if batch_ready:
            connection.execute("UPDATE inbox_batches SET status = 'targeted_evidence_ready', updated_utc = ? WHERE batch_id = ?", (now, batch_id))
            if old_batch != "targeted_evidence_ready":
                review_ledger._insert_lifecycle_event(
                    connection,
                    source_id=None,
                    batch_id=batch_id,
                    event_type="targeted_evidence_ready",
                    from_state=old_batch,
                    to_state="targeted_evidence_ready",
                    details={"preliminary_submission_sha256": plan["preliminary_submission_sha256"]},
                )
        connection.execute("PRAGMA foreign_keys = ON")
        violations = inbox_records.link_problems(connection)
        if violations:
            raise TargetedEvidenceError(f"Foreign-key validation failed after targeted-evidence lifecycle update: {violations!r}")
        connection.commit()
        return "targeted_evidence_ready" if batch_ready else "preliminary_findings_received"
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _targeted_section(plan: dict[str, Any]) -> str:
    lines = [
        "<!-- TARGETED_EVIDENCE_BEGIN -->",
        "## Targeted evidence ready for external review",
        "",
        "Review every requested targeted-evidence package below before making any final issue decision.",
        "After that review, follow the generated final-results contract. Create or update an issue only after explicit operator approval.",
        "Record GitHub conclusions as external assertions; Media Manglers validates local identities and evidence integrity only.",
        "Never modify manifests, integrity files, identities, or ledger data.",
        "",
    ]
    for item in plan.get("request_plans") or []:
        relative = Path(str(item["final_root"])).relative_to(Path(str(plan["batch_path"]))).as_posix()
        lines.append(f"- Finding `{item['finding_id']}`, request `{item['request_id']}`: `{relative}`")
    if plan.get("no_request_sources"):
        lines.append("")
        lines.append(f"- {len(plan['no_request_sources'])} reviewed source(s) explicitly requested no targeted evidence.")
    lines.extend(["", "<!-- TARGETED_EVIDENCE_END -->", ""])
    return "\n".join(lines)


def _replace_targeted_section(text: str, section: str) -> str:
    begin = "<!-- TARGETED_EVIDENCE_BEGIN -->"
    end = "<!-- TARGETED_EVIDENCE_END -->"
    if begin in text and end in text:
        prefix = text.split(begin, 1)[0].rstrip()
        suffix = text.split(end, 1)[1].lstrip()
        return prefix + "\n\n" + section + ("\n" + suffix if suffix else "")
    return text.rstrip() + "\n\n" + section


def _refresh_review_materials(batch_root: Path, plan: dict[str, Any]) -> None:
    manifest_path = batch_root / "batch-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TargetedEvidenceError(f"Batch manifest cannot be refreshed after targeted rendering: {exc}.") from exc
    manifest["status"] = "targeted_evidence_ready"
    manifest["targeted_evidence"] = {
        "render_version": RENDER_VERSION,
        "preliminary_submission_sha256": plan["preliminary_submission_sha256"],
        "finding_count": int(plan.get("finding_count") or 0),
        "request_count": int(plan.get("request_count") or len(plan.get("request_plans") or [])),
        "completed_request_count": len(plan.get("request_plans") or []),
        "no_request_source_count": len(plan.get("no_request_sources") or []),
        "complete": True,
        "updated_utc": _utc_now(),
    }
    _atomic_json(manifest_path, manifest)
    review_findings.write_review_materials(batch_root, manifest)
    section = _targeted_section(plan)
    for name in ("README_FOR_REVIEW.md", "CODEX_REVIEW_PROMPT.md"):
        path = batch_root / name
        text = path.read_text(encoding="utf-8")
        _atomic_text(path, _replace_targeted_section(text, section))


def complete_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Verify rendered artifacts, promote requests atomically, and commit lifecycle state."""

    _plan_path, plan = _load_plan(payload)
    batch_root = Path(str(plan["batch_path"]))
    ledger_path = Path(str(plan["ledger_path"]))
    processed = set(str(item) for item in payload.get("processed_request_signatures") or [])
    stopped = bool(payload.get("cooperative_stop", False))
    frame_results, audio_results = _result_maps(payload)
    post_source: dict[int, dict[str, Any]] = {}
    source_failures: dict[int, dict[str, Any]] = {}
    for item in plan.get("request_plans") or []:
        if item.get("existing_complete") or str(item["render_signature"]) not in processed:
            continue
        source_id = int(item["source_id"])
        if source_id in post_source or source_id in source_failures:
            continue
        try:
            post_source[source_id] = _verify_source_after(item)
        except SourceResolutionError as exc:
            source_failures[source_id] = {
                "source_id": source_id,
                "source_identity": item["source_identity"],
                "state": exc.state,
                "error": str(exc),
                "render_signature": _canonical_sha(
                    {
                        "render_version": RENDER_VERSION,
                        "source_identity": item["source_identity"],
                        "stage": "post_render_source_verification",
                        "submission_sha256": plan["preliminary_submission_sha256"],
                    }
                ),
            }
    completed: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = list(plan.get("source_failures") or [])
    failures.extend(source_failures.values())
    leftovers = inbox_records.leftovers_file(ledger_path)
    cleanup_warnings: list[str] = []
    for item in plan.get("request_plans") or []:
        signature = str(item["render_signature"])
        source_id = int(item["source_id"])
        if source_id in source_failures:
            continue
        if item.get("existing_complete"):
            valid, problems = _verify_integrity(Path(str(item["final_root"])), signature)
            if valid:
                completed.append(item)
            else:
                failures.append({**item, "error": " ".join(problems)})
            continue
        if signature not in processed:
            continue
        valid, error, inventory = _finalize_request_stage(
            batch_root,
            item,
            frame_results,
            audio_results,
            post_source[source_id],
            leftovers=leftovers,
            cleanup_warnings=cleanup_warnings,
        )
        if valid:
            completed.append({**item, "artifact_inventory": inventory})
            callback = payload.get("_after_promotion")
            if callable(callback):
                callback(item)
        else:
            failures.append({**item, "error": error})
    lifecycle_status = _record_completion(ledger_path, plan, completed, failures)
    callback = payload.get("_after_ledger_commit")
    if callable(callback):
        callback(plan)
    completed_signatures = {str(item["render_signature"]) for item in completed}
    unresolved = [
        item
        for item in plan.get("request_plans") or []
        if str(item["render_signature"]) not in completed_signatures
        and not _all_ledger_requests_complete(ledger_path, str(plan["batch_id"]), [item])
    ]
    status = lifecycle_status
    if status != "targeted_evidence_ready":
        status = "cooperative_stop" if stopped and not failures else "retryable_failure" if failures else "partial"
    result = {
        "contract_version": CONTRACT_VERSION,
        "render_version": RENDER_VERSION,
        "action": "targeted_evidence",
        "status": status,
        "batch_id": plan["batch_id"],
        "batch_path": str(batch_root),
        "preliminary_submission_sha256": plan["preliminary_submission_sha256"],
        "finding_count": int(plan.get("finding_count") or 0),
        "request_count": int(plan.get("request_count") or 0),
        "completed_request_count": int(plan.get("request_count") or 0) - len(unresolved),
        "unresolved_request_count": len(unresolved),
        "failed_requests": [
            {
                "source_identity": item.get("source_identity"),
                "finding_id": item.get("finding_id", ""),
                "request_id": item.get("request_id", ""),
                "error": item.get("error", "Targeted evidence failed safely."),
            }
            for item in failures
        ],
        "cooperative_stop": stopped,
        "warnings": [*list(plan.get("warnings") or []), *cleanup_warnings],
        "updated_utc": _utc_now(),
    }
    if lifecycle_status == "targeted_evidence_ready":
        _refresh_review_materials(batch_root, {**plan, **result})
        result["prompt_path"] = str(batch_root / "CODEX_REVIEW_PROMPT.md")
        result["targeted_evidence_root"] = str(batch_root / "sources")
    return result
