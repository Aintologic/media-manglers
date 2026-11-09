"""Preliminary-findings contracts and lifecycle import for Review Media Inbox."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Any
import uuid

from . import inbox_records, review_ledger, safe_write


CONTRACT_VERSION = 1
DOCUMENT_TYPE = "review_media_inbox_preliminary_findings"
REQUEST_TYPE = "targeted_evidence"
MAX_FINDINGS = 100
MAX_REQUESTS_PER_FINDING = 20
MAX_REQUESTS_PER_SUBMISSION = 100
MAX_RANGE_SECONDS = 300.0
MAX_CONTEXT_SECONDS = 60.0
MAX_FRAMES_PER_REQUEST = 24
MAX_PANELS_PER_REQUEST = 3
MAX_REVIEWER_NOTES = 4000
MAX_CONFIDENCE_RATIONALE = 2000
FINDING_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
ALLOWED_BATCH_STATES = {"awaiting_external_review", "preliminary_findings_received"}
LEDGER_MISSING_PROBLEM = "The configured Review Media Inbox ledger does not exist."


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _atomic_bytes(path: Path, data: bytes) -> None:
    # 224 (Wave B1): the one safe writer replaces the file; the bytes are exactly the ones given, as before.
    safe_write.write_bytes(path, data, wait=safe_write.INBOX_WAIT_SECONDS)


def _atomic_text(path: Path, text: str) -> None:
    _atomic_bytes(path, text.encode("utf-8"))


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _is_within(root: Path, target: Path) -> bool:
    root_resolved = root.resolve()
    target_resolved = target.resolve()
    return target_resolved == root_resolved or root_resolved in target_resolved.parents


def _read_json(path: Path, problems: list[str], label: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        problems.append(f"{label} is missing: {path.name}.")
        return None
    except (OSError, UnicodeError) as exc:
        problems.append(f"{label} could not be read: {exc}.")
        return None
    except json.JSONDecodeError as exc:
        problems.append(f"{label} contains malformed JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}.")
        return None
    if not isinstance(payload, dict):
        problems.append(f"{label} must contain one JSON object.")
        return None
    return payload


def preliminary_findings_schema() -> dict[str, Any]:
    """Return the public JSON Schema for a bounded preliminary submission."""

    bounded_context = {
        "type": "object",
        "additionalProperties": False,
        "required": ["requested", "before_seconds", "after_seconds"],
        "properties": {
            "requested": {"type": "boolean"},
            "before_seconds": {"type": "number", "minimum": 0, "maximum": MAX_CONTEXT_SECONDS},
            "after_seconds": {"type": "number", "minimum": 0, "maximum": MAX_CONTEXT_SECONDS},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://schemas.example.invalid/media-manglers/review-media-inbox/preliminary-findings-v1.json",
        "title": "Review Media Inbox preliminary findings",
        "description": "A preliminary request for bounded local evidence. This is not a final review disposition.",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "contract_version",
            "document_type",
            "batch_id",
            "reviewed_source_identities",
            "findings",
            "reviewer_notes",
        ],
        "properties": {
            "contract_version": {"const": CONTRACT_VERSION},
            "document_type": {"const": DOCUMENT_TYPE},
            "batch_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "reviewed_source_identities": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
            },
            "findings": {
                "type": "array",
                "maxItems": MAX_FINDINGS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "finding_id",
                        "source_identity",
                        "request_type",
                        "requests",
                        "reviewer_notes",
                        "confidence",
                    ],
                    "properties": {
                        "finding_id": {"type": "string", "pattern": FINDING_ID_PATTERN.pattern},
                        "source_identity": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                        "request_type": {"const": REQUEST_TYPE},
                        "reviewer_notes": {"type": "string", "minLength": 1, "maxLength": MAX_REVIEWER_NOTES},
                        "confidence": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["level", "rationale"],
                            "properties": {
                                "level": {"enum": ["low", "medium", "high", "unknown"]},
                                "rationale": {"type": "string", "maxLength": MAX_CONFIDENCE_RATIONALE},
                            },
                        },
                        "requests": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": MAX_REQUESTS_PER_FINDING,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["request_id", "timestamp", "frames", "panels", "audio"],
                                "properties": {
                                    "request_id": {"type": "string", "pattern": FINDING_ID_PATTERN.pattern},
                                    "timestamp": {
                                        "oneOf": [
                                            {
                                                "type": "object",
                                                "additionalProperties": False,
                                                "required": ["kind", "at_seconds"],
                                                "properties": {
                                                    "kind": {"const": "point"},
                                                    "at_seconds": {"type": "number", "minimum": 0},
                                                },
                                            },
                                            {
                                                "type": "object",
                                                "additionalProperties": False,
                                                "required": ["kind", "start_seconds", "end_seconds"],
                                                "properties": {
                                                    "kind": {"const": "range"},
                                                    "start_seconds": {"type": "number", "minimum": 0},
                                                    "end_seconds": {"type": "number", "minimum": 0},
                                                },
                                            },
                                        ]
                                    },
                                    "frames": {
                                        **bounded_context,
                                        "required": ["requested", "before_seconds", "after_seconds", "max_frames"],
                                        "properties": {
                                            **bounded_context["properties"],
                                            "max_frames": {"type": "integer", "minimum": 0, "maximum": MAX_FRAMES_PER_REQUEST},
                                        },
                                    },
                                    "panels": {
                                        **bounded_context,
                                        "required": ["requested", "panel_ids", "before_seconds", "after_seconds"],
                                        "properties": {
                                            **bounded_context["properties"],
                                            "panel_ids": {
                                                "type": "array",
                                                "uniqueItems": True,
                                                "maxItems": MAX_PANELS_PER_REQUEST,
                                                "items": {"type": "string", "minLength": 1, "maxLength": 64},
                                            },
                                        },
                                    },
                                    "audio": bounded_context,
                                },
                            },
                        },
                    },
                },
            },
            "reviewer_notes": {"type": "string", "maxLength": MAX_REVIEWER_NOTES},
        },
    }


def _load_source_manifests(batch_root: Path, batch_manifest: dict[str, Any], problems: list[str]) -> dict[str, dict[str, Any]]:
    sources: dict[str, dict[str, Any]] = {}
    prepared = batch_manifest.get("prepared_sources")
    if not isinstance(prepared, list) or not prepared:
        problems.append("batch-manifest.json must list at least one prepared source.")
        return sources
    for index, record in enumerate(prepared):
        if not isinstance(record, dict):
            problems.append(f"batch-manifest.json prepared_sources[{index}] must be an object.")
            continue
        identity = str(record.get("source_identity") or "")
        token = str(record.get("source_token") or "")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", identity):
            problems.append(f"batch-manifest.json prepared_sources[{index}] has no valid stable source identity.")
            continue
        if not token or not re.fullmatch(r"[0-9a-f]{16}", token):
            problems.append(f"batch-manifest.json prepared_sources[{index}] has an invalid source token.")
            continue
        source_root = batch_root / "sources" / token
        if not _is_within(batch_root, source_root):
            problems.append(f"Prepared source {identity} resolves outside the batch.")
            continue
        source_problems: list[str] = []
        try:
            # Import lazily because preparation also uses this module to write
            # the generated review contracts after a package is complete.
            from . import review_preparation

            review_preparation._validate_source_package(source_root)
        except Exception as exc:
            source_problems.append(
                f"Prepared package reconciliation failed for {identity}: "
                f"{type(exc).__name__}: {exc}"
            )
        source_manifest = _read_json(source_root / "source-manifest.json", source_problems, f"Source manifest for {identity}")
        integrity = _read_json(source_root / "integrity.json", source_problems, f"Integrity record for {identity}")
        if source_manifest is not None and str(source_manifest.get("source_identity") or "") != identity:
            source_problems.append(f"Source manifest identity for {identity} contradicts the batch manifest.")
        if integrity is not None:
            records = integrity.get("files")
            if integrity.get("complete") is not True or not isinstance(records, list):
                source_problems.append(f"Integrity record for {identity} is incomplete.")
            else:
                for artifact_index, artifact in enumerate(records):
                    if not isinstance(artifact, dict):
                        source_problems.append(f"Integrity record {artifact_index} for {identity} is malformed.")
                        continue
                    artifact_path = source_root / str(artifact.get("path") or "")
                    if not _is_within(source_root, artifact_path):
                        source_problems.append(f"Integrity artifact {artifact_index} for {identity} resolves outside its package.")
                        continue
                    if not artifact_path.is_file():
                        source_problems.append(f"Prepared artifact is missing for {identity}: {artifact_path.name}.")
                        continue
                    expected_size = artifact.get("size_bytes")
                    expected_sha = str(artifact.get("sha256") or "")
                    if not isinstance(expected_size, int) or artifact_path.stat().st_size != expected_size:
                        source_problems.append(f"Prepared artifact size changed for {identity}: {artifact_path.name}.")
                    elif not re.fullmatch(r"[0-9a-f]{64}", expected_sha) or review_ledger.sha256_file(artifact_path) != expected_sha:
                        source_problems.append(f"Prepared artifact hash changed for {identity}: {artifact_path.name}.")
        problems.extend(source_problems)
        if source_manifest is None:
            continue
        media = source_manifest.get("media_metadata") if isinstance(source_manifest.get("media_metadata"), dict) else {}
        duration = media.get("duration_seconds")
        if not _is_number(duration) or float(duration) < 0:
            problems.append(f"Source {identity} has no valid non-negative duration.")
            duration = 0.0
        visuals = source_manifest.get("visuals") if isinstance(source_manifest.get("visuals"), dict) else {}
        panel_records = visuals.get("panels") if isinstance(visuals.get("panels"), list) else []
        supported_panel_ids = visuals.get("supported_panel_ids")
        if isinstance(supported_panel_ids, list):
            panel_ids = sorted(
                {
                    str(item).strip()
                    for item in supported_panel_ids
                    if isinstance(item, str) and str(item).strip()
                }
            )
        else:
            panel_ids = sorted(
                {
                    str(item.get("panel") or "")
                    for item in panel_records
                    if isinstance(item, dict) and str(item.get("panel") or "")
                }
            )
        audio_selection = source_manifest.get("audio_selection") if isinstance(source_manifest.get("audio_selection"), dict) else {}
        sources[identity] = {
            "source_id": int(record.get("source_id") or 0),
            "source_token": token,
            "duration_seconds": float(duration),
            "panel_ids": panel_ids,
            "audio_available": audio_selection.get("selected_ordinal") is not None,
            "source_manifest": source_manifest,
        }
    return sources


def _batch_context(
    ledger_path: Path,
    batch_root: Path,
    expected_batch_id: str,
    *,
    allowed_batch_states: set[str] | None = None,
    allowed_source_states: set[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    accepted_batch_states = allowed_batch_states or ALLOWED_BATCH_STATES
    accepted_source_states = allowed_source_states or ALLOWED_BATCH_STATES
    problems: list[str] = []
    context: dict[str, Any] = {
        "batch_id": expected_batch_id,
        "batch_root": batch_root,
        "batch_status": "",
        "sources": {},
    }
    try:
        connection = inbox_records.connect_read_only(ledger_path)
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        return context, [f"The Review Media Inbox ledger could not be opened: {exc}."]
    if connection is None:
        return context, [LEDGER_MISSING_PROBLEM]
    try:
        row = connection.execute(
            "SELECT batch_id, status, package_path FROM inbox_batches WHERE batch_id = ?",
            (expected_batch_id,),
        ).fetchone()
        if row is None:
            problems.append(f"Expected batch {expected_batch_id!r} is unknown to the ledger.")
            return context, problems
        ledger_batch_root = Path(str(row["package_path"] or ""))
        if not ledger_batch_root.is_dir():
            problems.append("The ledger batch package path is missing or unavailable.")
        elif ledger_batch_root.resolve() != batch_root.resolve():
            problems.append("The selected batch folder contradicts the ledger package path.")
        context["batch_status"] = str(row["status"] or "")
        if context["batch_status"] not in accepted_batch_states:
            problems.append(
                f"Batch state {context['batch_status']!r} is not eligible for this review operation; expected one of: "
                + ", ".join(sorted(accepted_batch_states))
                + "."
            )
        rows = connection.execute(
            """
            SELECT bs.source_id, bs.state, s.stable_identity
            FROM inbox_batch_sources bs JOIN inbox_sources s ON s.source_id = bs.source_id
            WHERE bs.batch_id = ? ORDER BY bs.ordinal
            """,
            (expected_batch_id,),
        ).fetchall()
        ledger_sources: dict[str, dict[str, Any]] = {}
        for source in rows:
            identity = str(source["stable_identity"] or "")
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", identity):
                problems.append(f"Ledger source {int(source['source_id'])} has no stable SHA-256 identity.")
                continue
            state = str(source["state"] or "")
            if state not in accepted_source_states:
                problems.append(
                    f"Ledger source {identity} is in state {state!r}, which is not eligible for this review operation."
                )
            ledger_sources[identity] = {"source_id": int(source["source_id"]), "state": state}
        batch_manifest = _read_json(batch_root / "batch-manifest.json", problems, "Batch manifest")
        if batch_manifest is None:
            return context, problems
        if str(batch_manifest.get("batch_id") or "") != expected_batch_id:
            problems.append("batch-manifest.json contradicts the expected batch identity.")
        package_sources = _load_source_manifests(batch_root, batch_manifest, problems)
        if set(package_sources) != set(ledger_sources):
            missing = sorted(set(ledger_sources) - set(package_sources))
            unknown = sorted(set(package_sources) - set(ledger_sources))
            if missing:
                problems.append("Prepared packages are missing ledger source identities: " + ", ".join(missing) + ".")
            if unknown:
                problems.append("Prepared packages contain source identities unknown to the batch ledger: " + ", ".join(unknown) + ".")
        for identity in set(package_sources) & set(ledger_sources):
            package_sources[identity].update(ledger_sources[identity])
        context["sources"] = package_sources
        context["batch_manifest"] = batch_manifest
        return context, problems
    finally:
        connection.close()


def _object_fields(
    value: Any,
    *,
    path: str,
    required: set[str],
    allowed: set[str],
    problems: list[str],
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        problems.append(f"{path} must be an object.")
        return None
    for key in sorted(required - set(value)):
        problems.append(f"{path}.{key} is required.")
    for key in sorted(set(value) - allowed):
        problems.append(f"{path}.{key} is not supported in a preliminary-findings document.")
    return value


def _bounded_context(value: Any, path: str, problems: list[str], *, frame: bool = False, panels: bool = False) -> dict[str, Any] | None:
    required = {"requested", "before_seconds", "after_seconds"}
    if frame:
        required.add("max_frames")
    if panels:
        required.add("panel_ids")
    context = _object_fields(value, path=path, required=required, allowed=required, problems=problems)
    if context is None:
        return None
    if not isinstance(context.get("requested"), bool):
        problems.append(f"{path}.requested must be true or false.")
    for field in ("before_seconds", "after_seconds"):
        item = context.get(field)
        if not _is_number(item) or not 0 <= float(item) <= MAX_CONTEXT_SECONDS:
            problems.append(f"{path}.{field} must be between 0 and {MAX_CONTEXT_SECONDS:g} seconds.")
    if frame:
        maximum = context.get("max_frames")
        if not isinstance(maximum, int) or isinstance(maximum, bool) or not 0 <= maximum <= MAX_FRAMES_PER_REQUEST:
            problems.append(f"{path}.max_frames must be an integer from 0 through {MAX_FRAMES_PER_REQUEST}.")
        elif context.get("requested") is True and maximum < 1:
            problems.append(f"{path}.max_frames must be at least 1 when frames are requested.")
    if panels:
        panel_ids = context.get("panel_ids")
        if not isinstance(panel_ids, list) or not all(isinstance(item, str) and item for item in panel_ids):
            problems.append(f"{path}.panel_ids must be a list of panel identifiers.")
        else:
            if len(panel_ids) != len(set(panel_ids)):
                problems.append(f"{path}.panel_ids must not contain duplicates.")
            if len(panel_ids) > MAX_PANELS_PER_REQUEST:
                problems.append(f"{path}.panel_ids may contain at most {MAX_PANELS_PER_REQUEST} panels.")
            if context.get("requested") is True and not panel_ids:
                problems.append(f"{path}.panel_ids must name at least one supported panel when panels are requested.")
    return context


def validate_document(document: Any, context: dict[str, Any]) -> list[str]:
    """Collect every actionable contract problem without mutating lifecycle state."""

    problems: list[str] = []
    top = _object_fields(
        document,
        path="$",
        required={"contract_version", "document_type", "batch_id", "reviewed_source_identities", "findings", "reviewer_notes"},
        allowed={"contract_version", "document_type", "batch_id", "reviewed_source_identities", "findings", "reviewer_notes"},
        problems=problems,
    )
    if top is None:
        return problems
    if top.get("contract_version") != CONTRACT_VERSION:
        problems.append(f"$.contract_version must be {CONTRACT_VERSION}.")
    if top.get("document_type") != DOCUMENT_TYPE:
        problems.append(f"$.document_type must be {DOCUMENT_TYPE!r}; preliminary findings are not final dispositions.")
    expected_batch_id = str(context.get("batch_id") or "")
    if top.get("batch_id") != expected_batch_id:
        problems.append(f"$.batch_id must exactly match the active batch {expected_batch_id!r}.")
    expected_sources = set(context.get("sources") or {})
    reviewed = top.get("reviewed_source_identities")
    if not isinstance(reviewed, list) or not all(isinstance(item, str) for item in reviewed):
        problems.append("$.reviewed_source_identities must be a list of stable source identities.")
        reviewed_set: set[str] = set()
    else:
        reviewed_set = set(reviewed)
        if len(reviewed) != len(reviewed_set):
            problems.append("$.reviewed_source_identities must not contain duplicates.")
        unknown_reviewed = sorted(reviewed_set - expected_sources)
        missing_reviewed = sorted(expected_sources - reviewed_set)
        if unknown_reviewed:
            problems.append("$.reviewed_source_identities contains unknown sources: " + ", ".join(unknown_reviewed) + ".")
        if missing_reviewed:
            problems.append("The preliminary review is partial; these prepared sources are not listed as reviewed: " + ", ".join(missing_reviewed) + ".")
    reviewer_notes = top.get("reviewer_notes")
    if not isinstance(reviewer_notes, str) or len(reviewer_notes) > MAX_REVIEWER_NOTES:
        problems.append(f"$.reviewer_notes must be text no longer than {MAX_REVIEWER_NOTES} characters.")
    findings = top.get("findings")
    if not isinstance(findings, list):
        problems.append("$.findings must be a list; use an empty list when no targeted evidence is requested.")
        return problems
    if len(findings) > MAX_FINDINGS:
        problems.append(f"$.findings may contain at most {MAX_FINDINGS} findings.")
    finding_ids: set[str] = set()
    total_requests = 0
    for finding_index, raw_finding in enumerate(findings):
        finding_path = f"$.findings[{finding_index}]"
        finding = _object_fields(
            raw_finding,
            path=finding_path,
            required={"finding_id", "source_identity", "request_type", "requests", "reviewer_notes", "confidence"},
            allowed={"finding_id", "source_identity", "request_type", "requests", "reviewer_notes", "confidence"},
            problems=problems,
        )
        if finding is None:
            continue
        finding_id = finding.get("finding_id")
        if not isinstance(finding_id, str) or FINDING_ID_PATTERN.fullmatch(finding_id) is None:
            problems.append(f"{finding_path}.finding_id must use 1-64 letters, numbers, dots, underscores, or hyphens.")
        elif finding_id in finding_ids:
            problems.append(f"{finding_path}.finding_id duplicates {finding_id!r}.")
        else:
            finding_ids.add(finding_id)
        identity = finding.get("source_identity")
        if not isinstance(identity, str) or identity not in expected_sources:
            problems.append(f"{finding_path}.source_identity is unknown to the active batch.")
            source_context: dict[str, Any] = {"duration_seconds": 0.0, "panel_ids": [], "audio_available": False}
        else:
            source_context = context["sources"][identity]
        if finding.get("request_type") != REQUEST_TYPE:
            problems.append(f"{finding_path}.request_type must be {REQUEST_TYPE!r}.")
        notes = finding.get("reviewer_notes")
        if not isinstance(notes, str) or not notes.strip() or len(notes) > MAX_REVIEWER_NOTES:
            problems.append(f"{finding_path}.reviewer_notes must contain 1-{MAX_REVIEWER_NOTES} characters.")
        confidence = _object_fields(
            finding.get("confidence"),
            path=f"{finding_path}.confidence",
            required={"level", "rationale"},
            allowed={"level", "rationale"},
            problems=problems,
        )
        if confidence is not None:
            if confidence.get("level") not in {"low", "medium", "high", "unknown"}:
                problems.append(f"{finding_path}.confidence.level must be low, medium, high, or unknown.")
            rationale = confidence.get("rationale")
            if not isinstance(rationale, str) or len(rationale) > MAX_CONFIDENCE_RATIONALE:
                problems.append(f"{finding_path}.confidence.rationale must be text no longer than {MAX_CONFIDENCE_RATIONALE} characters.")
        requests = finding.get("requests")
        if not isinstance(requests, list) or not requests:
            problems.append(f"{finding_path}.requests must contain at least one bounded timestamp request.")
            continue
        if len(requests) > MAX_REQUESTS_PER_FINDING:
            problems.append(f"{finding_path}.requests may contain at most {MAX_REQUESTS_PER_FINDING} requests.")
        total_requests += len(requests)
        request_ids: set[str] = set()
        for request_index, raw_request in enumerate(requests):
            request_path = f"{finding_path}.requests[{request_index}]"
            request = _object_fields(
                raw_request,
                path=request_path,
                required={"request_id", "timestamp", "frames", "panels", "audio"},
                allowed={"request_id", "timestamp", "frames", "panels", "audio"},
                problems=problems,
            )
            if request is None:
                continue
            request_id = request.get("request_id")
            if not isinstance(request_id, str) or FINDING_ID_PATTERN.fullmatch(request_id) is None:
                problems.append(f"{request_path}.request_id must use 1-64 letters, numbers, dots, underscores, or hyphens.")
            elif request_id in request_ids:
                problems.append(f"{request_path}.request_id duplicates {request_id!r} within its finding.")
            else:
                request_ids.add(request_id)
            timestamp = _object_fields(
                request.get("timestamp"),
                path=f"{request_path}.timestamp",
                required={"kind"},
                allowed={"kind", "at_seconds", "start_seconds", "end_seconds"},
                problems=problems,
            )
            duration = float(source_context.get("duration_seconds") or 0.0)
            if timestamp is not None:
                kind = timestamp.get("kind")
                if kind == "point":
                    if set(timestamp) != {"kind", "at_seconds"}:
                        problems.append(f"{request_path}.timestamp point requests require only kind and at_seconds.")
                    at_seconds = timestamp.get("at_seconds")
                    if not _is_number(at_seconds) or not 0 <= float(at_seconds) <= duration:
                        problems.append(f"{request_path}.timestamp.at_seconds must be between 0 and the source duration ({duration:g} seconds).")
                elif kind == "range":
                    if set(timestamp) != {"kind", "start_seconds", "end_seconds"}:
                        problems.append(f"{request_path}.timestamp range requests require only kind, start_seconds, and end_seconds.")
                    start = timestamp.get("start_seconds")
                    end = timestamp.get("end_seconds")
                    if not _is_number(start) or float(start) < 0:
                        problems.append(f"{request_path}.timestamp.start_seconds must be a non-negative number.")
                    if not _is_number(end) or float(end) < 0:
                        problems.append(f"{request_path}.timestamp.end_seconds must be a non-negative number.")
                    if _is_number(start) and _is_number(end):
                        if float(end) <= float(start):
                            problems.append(f"{request_path}.timestamp.end_seconds must be greater than start_seconds.")
                        if float(start) > duration:
                            problems.append(f"{request_path}.timestamp.start_seconds exceeds the source duration ({duration:g} seconds).")
                        if float(end) > duration:
                            problems.append(f"{request_path}.timestamp.end_seconds exceeds the source duration ({duration:g} seconds).")
                        if float(end) - float(start) > MAX_RANGE_SECONDS:
                            problems.append(f"{request_path}.timestamp range may span at most {MAX_RANGE_SECONDS:g} seconds.")
                else:
                    problems.append(f"{request_path}.timestamp.kind must be 'point' or 'range'.")
            frames = _bounded_context(request.get("frames"), f"{request_path}.frames", problems, frame=True)
            panels = _bounded_context(request.get("panels"), f"{request_path}.panels", problems, panels=True)
            audio = _bounded_context(request.get("audio"), f"{request_path}.audio", problems)
            requested = [context_item for context_item in (frames, panels, audio) if context_item and context_item.get("requested") is True]
            if not requested:
                problems.append(f"{request_path} must request at least one of frames, panels, or audio.")
            if panels is not None and panels.get("requested") is True and isinstance(panels.get("panel_ids"), list):
                supported = set(source_context.get("panel_ids") or [])
                unsupported = sorted(set(panels["panel_ids"]) - supported)
                if unsupported:
                    problems.append(
                        f"{request_path}.panels.panel_ids contains unsupported panels for this source: " + ", ".join(unsupported) + "."
                    )
            if audio is not None and audio.get("requested") is True and not source_context.get("audio_available"):
                problems.append(f"{request_path}.audio cannot be requested because this prepared source has no selected audio stream.")
    if total_requests > MAX_REQUESTS_PER_SUBMISSION:
        problems.append(f"The submission may contain at most {MAX_REQUESTS_PER_SUBMISSION} timestamp requests in total.")
    return problems


def _source_summary(batch_root: Path, batch_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    problems: list[str] = []
    sources = _load_source_manifests(batch_root, batch_manifest, problems)
    if problems:
        raise RuntimeError("Cannot generate review materials until prepared package integrity is complete: " + " ".join(problems))
    return [
        {
            "source_identity": identity,
            "source_token": source["source_token"],
            "duration_seconds": source["duration_seconds"],
            "supported_panel_ids": source["panel_ids"],
            "audio_available": source["audio_available"],
        }
        for identity, source in sources.items()
    ]


def write_review_materials(batch_root: Path, batch_manifest: dict[str, Any]) -> dict[str, str]:
    """Create or refresh batch-local instructions and preliminary contracts."""

    batch_root = Path(batch_root)
    if str(batch_manifest.get("batch_id") or "") != batch_root.name:
        raise ValueError("Batch manifest identity must match the batch folder name before review materials are generated.")
    sources = _source_summary(batch_root, batch_manifest)
    identities = [item["source_identity"] for item in sources]
    template = {
        "contract_version": CONTRACT_VERSION,
        "document_type": DOCUMENT_TYPE,
        "batch_id": str(batch_manifest["batch_id"]),
        "reviewed_source_identities": identities,
        "findings": [],
        "reviewer_notes": "Review every prepared source. Add findings only when bounded targeted evidence is needed.",
    }
    source_lines = "\n".join(
        f"- `{item['source_identity']}` — duration {item['duration_seconds']:g}s; "
        f"panels: {', '.join(item['supported_panel_ids']) if item['supported_panel_ids'] else 'none'}; "
        f"audio: {'available' if item['audio_available'] else 'not available'}"
        for item in sources
    )
    readme = f"""# Review Media Inbox batch

Batch: `{batch_manifest['batch_id']}`

This local package is awaiting external review. Media Manglers prepared evidence and validates contracts, but it does not make semantic decisions, inspect repositories or GitHub, create issues, or launch an agent.

## External review flow

1. Review every prepared source and its complete transcript or explicit no-audible-narration status, neutral timeline visuals, supported panel definitions, and metadata. A visual-only source still requires review.
2. Externally inspect relevant repositories plus open and closed GitHub issues.
3. If richer local evidence is needed, edit `preliminary-findings.json` using the exact batch and source identities below, then return to Media Manglers to validate and import it.
4. Request only bounded timestamp points or ranges and the frame, supported panel crop, or audio context actually needed. Panel crops are generated only after a validated bounded request.
5. Do not write final results, make final issue decisions, or perform issue creation/update until requested targeted evidence has been rendered and reviewed.
6. Never edit `batch-manifest.json`, a source manifest, an integrity record, or an identity value.

An empty `findings` list means no targeted evidence was requested. It is still preliminary and is not a final disposition.

## Prepared source identities

{source_lines}

## Contract files

- `preliminary-findings.schema.json` — machine-readable contract.
- `preliminary-findings.template.json` — fresh batch-specific template.
- `preliminary-findings.json` — working submission file; Media Manglers never treats it as final results.
- `CODEX_REVIEW_PROMPT.md` — ready-to-use external review instructions.
"""
    prompt = f"""# External review instructions for Review Media Inbox

Review batch `{batch_manifest['batch_id']}` completely.

You are the external semantic reviewer. Media Manglers itself must not inspect repositories or GitHub and must not make issue decisions. You should:

1. Review every prepared source in this batch, including its transcript or explicit no-audible-narration status, source manifest, neutral timeline visuals, and supported panel definitions. A visual-only source still requires review.
2. Inspect relevant repositories and both open and closed GitHub issues externally before making any eventual issue decision.
3. When more local evidence is needed, write only a preliminary evidence request to `preliminary-findings.json` using contract version {CONTRACT_VERSION}, document type `{DOCUMENT_TYPE}`, batch ID `{batch_manifest['batch_id']}`, and the exact source identities listed below.
4. Use unique finding and request IDs. Request bounded timestamp points or ranges and explicitly select frame, supported panel-crop, and/or audio context. Panel crops are generated only after a validated bounded request. Keep uncertainty or confidence information and reviewer notes in each finding.
5. Do not write final results or perform final issue creation/update decisions until Media Manglers has validated the request, rendered the later targeted-evidence package, and you have reviewed that evidence.
6. Never edit batch/source manifests, integrity files, source identities, or ledger material.

Prepared source identities:

{source_lines}

The preliminary contract is not a final source disposition. If no targeted evidence is needed, leave `findings` empty; final-results work occurs in a later phase.
"""
    outputs = {
        "schema": batch_root / "preliminary-findings.schema.json",
        "template": batch_root / "preliminary-findings.template.json",
        "submission": batch_root / "preliminary-findings.json",
        "readme": batch_root / "README_FOR_REVIEW.md",
        "prompt": batch_root / "CODEX_REVIEW_PROMPT.md",
    }
    _atomic_json(outputs["schema"], preliminary_findings_schema())
    _atomic_json(outputs["template"], template)
    if not outputs["submission"].exists():
        _atomic_json(outputs["submission"], template)
    _atomic_text(outputs["readme"], readme)
    _atomic_text(outputs["prompt"], prompt)
    # Import locally to avoid a module cycle: final-results reuses this module's
    # prepared-package and preliminary-history validators.
    from . import review_results

    outputs.update(review_results.write_review_materials(batch_root, batch_manifest))
    return {key: str(path) for key, path in outputs.items()}


def _existing_validation(record_path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _terminal_submission_state(
    ledger_path: Path,
    batch_id: str,
    submission_sha: str,
) -> tuple[str | None, list[str]]:
    """Return the committed terminal import state and recorded rejection problems."""

    connection = inbox_records.connect_read_only(ledger_path)
    if connection is None:
        return None, []
    try:
        rows = connection.execute(
            """
            SELECT status, error_message
            FROM inbox_attempts
            WHERE batch_id = ?
              AND attempt_type = 'preliminary_findings_import'
              AND status IN ('accepted', 'rejected')
              AND completed_utc IS NOT NULL
              AND settings_hash = ?
            ORDER BY attempt_id
            """,
            (batch_id, submission_sha),
        ).fetchall()
    finally:
        connection.close()
    statuses = {str(row["status"]) for row in rows}
    if "accepted" in statuses and "rejected" in statuses:
        raise RuntimeError(
            "The ledger contains contradictory accepted and rejected terminal attempts for this preliminary-findings submission."
        )
    if "accepted" in statuses:
        return "accepted", []
    if "rejected" in statuses:
        problems: list[str] = []
        for row in rows:
            for problem in str(row["error_message"] or "").splitlines():
                if problem and problem not in problems:
                    problems.append(problem)
        return "rejected", problems
    return None, []


def _timestamp_bounds(finding: dict[str, Any]) -> tuple[float | None, float | None]:
    starts: list[float] = []
    ends: list[float] = []
    for request in finding.get("requests") or []:
        timestamp = request.get("timestamp") if isinstance(request, dict) else None
        if not isinstance(timestamp, dict):
            continue
        if timestamp.get("kind") == "point":
            starts.append(float(timestamp["at_seconds"]))
            ends.append(float(timestamp["at_seconds"]))
        elif timestamp.get("kind") == "range":
            starts.append(float(timestamp["start_seconds"]))
            ends.append(float(timestamp["end_seconds"]))
    return (min(starts), max(ends)) if starts else (None, None)


def import_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate, preserve, and transactionally import one preliminary submission."""

    ledger_path = Path(str(payload.get("ledger_path") or ""))
    batch_root = Path(str(payload.get("batch_path") or ""))
    expected_batch_id = str(payload.get("expected_batch_id") or "")
    findings_path = Path(str(payload.get("findings_path") or ""))
    if not expected_batch_id:
        raise ValueError("expected_batch_id is required.")
    if not str(batch_root) or str(batch_root) == ".":
        raise ValueError("batch_path is required.")
    if not str(findings_path) or str(findings_path) == ".":
        raise ValueError("findings_path is required.")

    context, package_problems = _batch_context(ledger_path, batch_root, expected_batch_id)
    # 224, F5: with no ledger, nothing is copied, recorded or written: the import stops here, as it does for a
    # batch the ledger does not know. (A ledger that is there but busy still fails at its write, as before.)
    if not batch_root.is_dir() or LEDGER_MISSING_PROBLEM in package_problems or package_problems and any("unknown to the ledger" in item or "contradicts the ledger" in item for item in package_problems):
        return {
            "contract_version": CONTRACT_VERSION,
            "action": "import_preliminary_findings",
            "accepted": False,
            "idempotent": False,
            "status": "rejected",
            "batch_id": expected_batch_id,
            "problems": package_problems or ["The selected batch folder does not exist."],
        }
    try:
        raw = findings_path.read_bytes()
    except OSError as exc:
        return {
            "contract_version": CONTRACT_VERSION,
            "action": "import_preliminary_findings",
            "accepted": False,
            "idempotent": False,
            "status": "rejected",
            "batch_id": expected_batch_id,
            "problems": [f"The preliminary-findings file could not be read: {exc}."],
        }
    submission_sha = hashlib.sha256(raw).hexdigest()
    history_root = batch_root / "imports" / "preliminary-findings" / submission_sha[:24]
    if not _is_within(batch_root, history_root):
        raise ValueError("Preliminary-findings history must remain inside the batch.")
    submission_copy = history_root / "preliminary-findings.json"
    validation_path = history_root / "validation.json"
    existing = _existing_validation(validation_path)
    if existing is not None:
        terminal_state, terminal_problems = _terminal_submission_state(ledger_path, expected_batch_id, submission_sha)
        if terminal_state is not None:
            accepted = terminal_state == "accepted"
            recorded_problems = [] if accepted else list(existing.get("problems") or terminal_problems)
            expected_resulting_state = "preliminary_findings_received" if accepted else "rejected"
            needs_reconciliation = (
                bool(existing.get("accepted")) != accepted
                or str(existing.get("import_phase") or "") != terminal_state
                or str(existing.get("resulting_batch_state") or "") != expected_resulting_state
                or list(existing.get("problems") or []) != recorded_problems
            )
            if needs_reconciliation:
                existing["accepted"] = accepted
                existing["import_phase"] = terminal_state
                existing["resulting_batch_state"] = expected_resulting_state
                existing["problems"] = recorded_problems
                existing["reconciled_from_ledger_utc"] = _utc_now()
                _atomic_json(validation_path, existing)
            return {
                "contract_version": CONTRACT_VERSION,
                "action": "import_preliminary_findings",
                "accepted": accepted,
                "idempotent": True,
                "status": expected_resulting_state,
                "batch_id": expected_batch_id,
                "submission_sha256": submission_sha,
                "finding_count": int(existing.get("finding_count") or 0),
                "request_count": int(existing.get("request_count") or 0),
                "problems": recorded_problems,
                "validation_record": str(validation_path),
            }
        existing["accepted"] = False
        existing["import_phase"] = "staged"
        existing["resulting_batch_state"] = str(context.get("batch_status") or "")
        existing["resume_count"] = int(existing.get("resume_count") or 0) + 1
        existing["resumed_utc"] = _utc_now()
        if "reconciled_from_ledger_utc" in existing:
            del existing["reconciled_from_ledger_utc"]
        _atomic_json(validation_path, existing)
    _atomic_bytes(submission_copy, raw)
    document: dict[str, Any] | None = None
    parse_problems: list[str] = []
    try:
        parsed = json.loads(raw.decode("utf-8-sig"))
        if isinstance(parsed, dict):
            document = parsed
        else:
            parse_problems.append("The preliminary-findings file must contain one JSON object.")
    except UnicodeError as exc:
        parse_problems.append(f"The preliminary-findings file is not valid UTF-8 text: {exc}.")
    except json.JSONDecodeError as exc:
        parse_problems.append(f"Malformed JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}.")
    problems = [*package_problems, *parse_problems]
    if document is not None:
        problems.extend(validate_document(document, context))
    findings = list(document.get("findings") or []) if document is not None and isinstance(document.get("findings"), list) else []
    request_count = sum(len(item.get("requests") or []) for item in findings if isinstance(item, dict) and isinstance(item.get("requests"), list))
    submitted_finding_ids = [str(item.get("finding_id")) for item in findings if isinstance(item, dict) and isinstance(item.get("finding_id"), str)]
    history_connection = inbox_records.connect_read_only(ledger_path) if submitted_finding_ids else None
    if history_connection is not None:
        try:
            placeholders = ",".join("?" for _item in submitted_finding_ids)
            historical_ids = {
                str(row[0])
                for row in history_connection.execute(
                    f"SELECT finding_id FROM inbox_findings WHERE finding_id IN ({placeholders})",
                    submitted_finding_ids,
                ).fetchall()
            }
        finally:
            history_connection.close()
        if historical_ids:
            problems.append(
                "Finding IDs already exist in immutable ledger history; use new IDs for a corrected submission: "
                + ", ".join(sorted(historical_ids))
                + "."
            )
    staged_utc = str((existing or {}).get("staged_utc") or (existing or {}).get("validated_utc") or _utc_now())
    validation = {
        "contract_version": CONTRACT_VERSION,
        "submission_sha256": submission_sha,
        "expected_batch_id": expected_batch_id,
        "submitted_batch_id": str(document.get("batch_id") or "") if document is not None else "",
        "validated_utc": _utc_now(),
        "import_phase": "staged",
        "staged_utc": staged_utc,
        "resume_count": int((existing or {}).get("resume_count") or 0),
        "accepted": False,
        "idempotent": False,
        "finding_count": len(findings),
        "request_count": request_count,
        "problems": problems,
        "resulting_batch_state": str(context.get("batch_status") or "rejected"),
    }
    _atomic_json(validation_path, validation)

    connection = inbox_records.connect(ledger_path, must_exist=True)
    try:
        connection.execute("BEGIN IMMEDIATE")
        reviewed_source_ids = sorted(
            {
                int(item["source_id"])
                for item in context.get("sources", {}).values()
                if int(item.get("source_id") or 0) > 0
            }
        )
        now = _utc_now()
        if problems:
            for source_id in reviewed_source_ids:
                connection.execute(
                    "INSERT INTO inbox_attempts (source_id, batch_id, attempt_type, status, started_utc, completed_utc, settings_hash, error_message) VALUES (?, ?, 'preliminary_findings_import', 'rejected', ?, ?, ?, ?)",
                    (source_id, expected_batch_id, now, now, submission_sha, "\n".join(problems)),
                )
            review_ledger._insert_lifecycle_event(
                connection,
                source_id=None,
                batch_id=expected_batch_id,
                event_type="preliminary_findings_rejected",
                from_state=str(context.get("batch_status") or ""),
                to_state=str(context.get("batch_status") or ""),
                details={"submission_sha256": submission_sha, "problem_count": len(problems)},
            )
            connection.commit()
            validation["import_phase"] = "rejected"
            validation["resulting_batch_state"] = "rejected"
            validation["rejected_utc"] = _utc_now()
            _atomic_json(validation_path, validation)
            return {
                "contract_version": CONTRACT_VERSION,
                "action": "import_preliminary_findings",
                "accepted": False,
                "idempotent": False,
                "status": "rejected",
                "batch_id": expected_batch_id,
                "submission_sha256": submission_sha,
                "finding_count": len(findings),
                "request_count": request_count,
                "problems": problems,
                "validation_record": str(validation_path),
            }
        for finding in findings:
            finding_id = str(finding["finding_id"])
            existing_finding = connection.execute("SELECT batch_id FROM inbox_findings WHERE finding_id = ?", (finding_id,)).fetchone()
            if existing_finding is not None:
                raise RuntimeError(f"Finding ID {finding_id!r} already exists in ledger history; use a new unique ID for a corrected submission.")
        old_batch_state = str(connection.execute("SELECT status FROM inbox_batches WHERE batch_id = ?", (expected_batch_id,)).fetchone()[0])
        affected_sources: dict[int, str] = {}
        for finding in findings:
            identity = str(finding["source_identity"])
            source_id = int(context["sources"][identity]["source_id"])
            affected_sources[source_id] = identity
            start, end = _timestamp_bounds(finding)
            details = dict(finding)
            details["submission_sha256"] = submission_sha
            connection.execute(
                """
                INSERT INTO inbox_findings (finding_id, batch_id, source_id, stage, status, start_seconds, end_seconds, details_json, created_utc, updated_utc)
                VALUES (?, ?, ?, 'preliminary', 'evidence_requested', ?, ?, ?, ?, ?)
                """,
                (str(finding["finding_id"]), expected_batch_id, source_id, start, end, json.dumps(details, sort_keys=True), now, now),
            )
        for source_id in reviewed_source_ids:
            connection.execute(
                "INSERT INTO inbox_attempts (source_id, batch_id, attempt_type, status, started_utc, completed_utc, settings_hash) VALUES (?, ?, 'preliminary_findings_import', 'accepted', ?, ?, ?)",
                (source_id, expected_batch_id, now, now, submission_sha),
            )
        for source_id, identity in affected_sources.items():
            old_source_state = str(connection.execute("SELECT lifecycle_state FROM inbox_sources WHERE source_id = ?", (source_id,)).fetchone()[0])
            connection.execute("UPDATE inbox_sources SET lifecycle_state = 'preliminary_findings_received', updated_utc = ? WHERE source_id = ?", (now, source_id))
            connection.execute("UPDATE inbox_batch_sources SET state = 'preliminary_findings_received', updated_utc = ? WHERE batch_id = ? AND source_id = ?", (now, expected_batch_id, source_id))
            review_ledger._insert_lifecycle_event(
                connection,
                source_id=source_id,
                batch_id=expected_batch_id,
                event_type="preliminary_findings_imported",
                from_state=old_source_state,
                to_state="preliminary_findings_received",
                details={"submission_sha256": submission_sha, "source_identity": identity},
            )
        connection.execute("UPDATE inbox_batches SET status = 'preliminary_findings_received', updated_utc = ? WHERE batch_id = ?", (now, expected_batch_id))
        review_ledger._insert_lifecycle_event(
            connection,
            source_id=None,
            batch_id=expected_batch_id,
            event_type="preliminary_findings_imported",
            from_state=old_batch_state,
            to_state="preliminary_findings_received",
            details={"submission_sha256": submission_sha, "finding_count": len(findings), "request_count": request_count},
        )
        foreign_keys = inbox_records.link_problems(connection)
        if foreign_keys:
            raise RuntimeError(f"Foreign-key validation failed after preliminary-findings import: {foreign_keys!r}")
        connection.commit()
    except Exception as exc:
        connection.rollback()
        validation["problems"] = [*problems, f"Import failed safely: {exc}"]
        validation["import_error"] = str(exc)
        _atomic_json(validation_path, validation)
        return {
            "contract_version": CONTRACT_VERSION,
            "action": "import_preliminary_findings",
            "accepted": False,
            "idempotent": False,
            "status": "rejected",
            "batch_id": expected_batch_id,
            "submission_sha256": submission_sha,
            "finding_count": len(findings),
            "request_count": request_count,
            "problems": validation["problems"],
            "validation_record": str(validation_path),
        }
    finally:
        connection.close()
    canonical_path = batch_root / "preliminary-findings.json"
    if canonical_path.resolve() != findings_path.resolve():
        _atomic_bytes(canonical_path, raw)
    validation["accepted"] = True
    validation["import_phase"] = "accepted"
    validation["resulting_batch_state"] = "preliminary_findings_received"
    validation["accepted_utc"] = _utc_now()
    _atomic_json(validation_path, validation)
    return {
        "contract_version": CONTRACT_VERSION,
        "action": "import_preliminary_findings",
        "accepted": True,
        "idempotent": False,
        "status": "preliminary_findings_received",
        "batch_id": expected_batch_id,
        "submission_sha256": submission_sha,
        "finding_count": len(findings),
        "request_count": request_count,
        "problems": [],
        "validation_record": str(validation_path),
        "submission_record": str(submission_copy),
        "canonical_submission": str(canonical_path),
    }
