"""Final-results contract and durable import for Review Media Inbox."""

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

from . import inbox_records, review_findings, review_ledger, review_targeted_evidence, safe_write


CONTRACT_VERSION = 1
DOCUMENT_VERSION = 1
DOCUMENT_TYPE = "review_media_inbox_final_results"
DISPOSITIONS = {
    "no_actionable_findings",
    "already_implemented",
    "existing_issue_matched",
    "duplicate_supporting_evidence",
    "new_issue_created",
    "existing_issue_updated",
    "uncertain_manual_review",
    "review_failure",
}
ISSUE_DISPOSITIONS = {
    "existing_issue_matched": "matched",
    "duplicate_supporting_evidence": "supporting_evidence",
    "new_issue_created": "created",
    "existing_issue_updated": "updated",
}
AUTHORIZED_ISSUE_ACTIONS = {"created", "updated"}
RESULT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_RESULTS = 300
MAX_TEXT = 8000
IMPORT_ELIGIBLE_BATCH_STATES = {"targeted_evidence_ready"}
REVALIDATION_STATES = {
    "targeted_evidence_ready",
    "results_received",
    "finalizing",
    "finalized_no_findings",
    "finalized_with_findings",
    "needs_manual_review",
    "retryable_failure",
}


class FinalResultsError(RuntimeError):
    """Raised when final results or their review basis cannot be trusted."""


def _read_ledger(ledger_path: Path) -> sqlite3.Connection:
    """The ledger opened for reading only (224, F4): one that is not there is an error here, never made."""

    connection = inbox_records.connect_read_only(ledger_path)
    if connection is None:
        raise FinalResultsError("The configured Review Media Inbox ledger does not exist.")
    return connection


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _atomic_bytes(path: Path, data: bytes) -> None:
    # 224 (Wave B1): the one safe writer replaces the file. The bytes stay exactly as given: the queue
    # recognises an untouched generated template by its hash (generated_final_results_template_sha256s).
    safe_write.write_bytes(path, data, wait=safe_write.INBOX_WAIT_SECONDS)


def _atomic_text(path: Path, text: str) -> None:
    _atomic_bytes(path, text.encode("utf-8"))


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _canonical_sha(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _within(root: Path, target: Path) -> bool:
    root_resolved = root.resolve()
    target_resolved = target.resolve()
    return target_resolved == root_resolved or root_resolved in target_resolved.parents


def _replace_section(text: str, begin: str, end: str, section: str) -> str:
    if begin in text and end in text:
        prefix = text.split(begin, 1)[0].rstrip()
        suffix = text.split(end, 1)[1].lstrip()
        return prefix + "\n\n" + section + ("\n" + suffix if suffix else "")
    return text.rstrip() + "\n\n" + section


def final_results_schema() -> dict[str, Any]:
    timestamp = {
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "at_seconds"],
                "properties": {"kind": {"const": "point"}, "at_seconds": {"type": "number", "minimum": 0}},
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
    }
    issue = {
        "oneOf": [
            {"type": "null"},
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["repository", "issue_number", "issue_url", "action", "authorization_note"],
                "properties": {
                    "repository": {"type": "string", "pattern": REPOSITORY_PATTERN.pattern},
                    "issue_number": {"type": "integer", "minimum": 1},
                    "issue_url": {"type": "string", "format": "uri"},
                    "action": {"enum": sorted(set(ISSUE_DISPOSITIONS.values()))},
                    "authorization_note": {"type": "string"},
                },
            },
        ]
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Review Media Inbox final results",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "contract_version",
            "document_version",
            "document_type",
            "batch_id",
            "preliminary_submission_sha256",
            "targeted_evidence_render_version",
            "targeted_evidence_identity",
            "reviewed_source_identities",
            "source_results",
            "operator_summary",
            "reviewer_notes",
        ],
        "properties": {
            "contract_version": {"const": CONTRACT_VERSION},
            "document_version": {"const": DOCUMENT_VERSION},
            "document_type": {"const": DOCUMENT_TYPE},
            "batch_id": {"type": "string", "minLength": 1},
            "preliminary_submission_sha256": {"type": "string", "pattern": SHA256_PATTERN.pattern},
            "targeted_evidence_render_version": {"type": "integer", "minimum": 1},
            "targeted_evidence_identity": {"type": "string", "pattern": SHA256_PATTERN.pattern},
            "reviewed_source_identities": {"type": "array", "uniqueItems": True, "items": {"type": "string"}},
            "source_results": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["source_identity", "source_summary", "notes", "targeted_request_acknowledgements", "results"],
                    "properties": {
                        "source_identity": {"type": "string"},
                        "source_summary": {"type": "string", "minLength": 1},
                        "notes": {"type": "string", "minLength": 1},
                        "targeted_request_acknowledgements": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["source_identity", "finding_id", "request_id", "render_signature", "reviewed"],
                                "properties": {
                                    "source_identity": {"type": "string"},
                                    "finding_id": {"type": "string"},
                                    "request_id": {"type": "string"},
                                    "render_signature": {"type": "string", "pattern": SHA256_PATTERN.pattern},
                                    "reviewed": {"const": True},
                                },
                            },
                        },
                        "results": {
                            "type": "array",
                            "minItems": 1,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": [
                                    "result_id",
                                    "finding_id",
                                    "acknowledged_preliminary_finding_ids",
                                    "acknowledged_request_ids",
                                    "timestamps",
                                    "disposition",
                                    "summary",
                                    "notes",
                                    "external_assertions",
                                    "issue",
                                ],
                                "properties": {
                                    "result_id": {"type": "string", "pattern": RESULT_ID_PATTERN.pattern},
                                    "finding_id": {"type": ["string", "null"]},
                                    "acknowledged_preliminary_finding_ids": {"type": "array", "uniqueItems": True, "items": {"type": "string"}},
                                    "acknowledged_request_ids": {"type": "array", "uniqueItems": True, "items": {"type": "string"}},
                                    "timestamps": {"type": "array", "items": timestamp},
                                    "disposition": {"enum": sorted(DISPOSITIONS)},
                                    "summary": {"type": "string", "minLength": 1},
                                    "notes": {"type": "string", "minLength": 1},
                                    "external_assertions": {"type": "array", "items": {"type": "string"}},
                                    "issue": issue,
                                },
                            },
                        },
                    },
                },
            },
            "operator_summary": {"type": "string", "minLength": 1},
            "reviewer_notes": {"type": "string", "minLength": 1},
        },
    }


def _material_basis(batch_root: Path, batch_manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], str, int, str]:
    sources = review_findings._source_summary(batch_root, batch_manifest)
    targeted = batch_manifest.get("targeted_evidence") if isinstance(batch_manifest.get("targeted_evidence"), dict) else {}
    preliminary_sha = str(targeted.get("preliminary_submission_sha256") or "")
    render_version = int(targeted.get("render_version") or review_targeted_evidence.RENDER_VERSION)
    acknowledgements: dict[str, list[dict[str, Any]]] = {str(item["source_identity"]): [] for item in sources}
    identity = ""
    if SHA256_PATTERN.fullmatch(preliminary_sha):
        submission = batch_root / "imports" / "preliminary-findings" / preliminary_sha[:24] / "preliminary-findings.json"
        try:
            if review_ledger.sha256_file(submission) == preliminary_sha:
                document = json.loads(submission.read_text(encoding="utf-8-sig"))
                source_problems: list[str] = []
                package_sources = review_findings._load_source_manifests(batch_root, batch_manifest, source_problems)
                context = {"sources": package_sources}
                requests, _no_requests = review_targeted_evidence._request_specs(batch_root, preliminary_sha, document, context)
                records = []
                for item in requests:
                    record = {
                        "source_identity": item["source_identity"],
                        "finding_id": item["finding_id"],
                        "request_id": item["request_id"],
                        "render_signature": item["render_signature"],
                        "reviewed": True,
                    }
                    acknowledgements.setdefault(str(item["source_identity"]), []).append(record)
                    records.append(record)
                identity = _canonical_sha(
                    {
                        "render_version": render_version,
                        "preliminary_submission_sha256": preliminary_sha,
                        "requests": sorted(records, key=lambda item: (item["source_identity"], item["finding_id"], item["request_id"])),
                    }
                )
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, ValueError):
            identity = ""
    for records in acknowledgements.values():
        records.sort(key=lambda item: (item["finding_id"], item["request_id"]))
    return [{**item, "acknowledgements": acknowledgements.get(str(item["source_identity"]), [])} for item in sources], preliminary_sha, render_version, identity


def _template_from_basis(
    batch_manifest: dict[str, Any],
    sources: list[dict[str, Any]],
    preliminary_sha: str,
    render_version: int,
    targeted_identity: str,
) -> dict[str, Any]:
    identities = [str(item["source_identity"]) for item in sources]
    return {
        "contract_version": CONTRACT_VERSION,
        "document_version": DOCUMENT_VERSION,
        "document_type": DOCUMENT_TYPE,
        "batch_id": str(batch_manifest["batch_id"]),
        "preliminary_submission_sha256": preliminary_sha,
        "targeted_evidence_render_version": render_version,
        "targeted_evidence_identity": targeted_identity,
        "reviewed_source_identities": identities,
        "source_results": [
            {
                "source_identity": item["source_identity"],
                "source_summary": "Summarize the complete external review of this source.",
                "notes": "Record uncertainty, cross-repository review context, and any operator decisions.",
                "targeted_request_acknowledgements": list(item.get("acknowledgements") or []),
                "results": [],
            }
            for item in sources
        ],
        "operator_summary": "Summarize the completed batch review for the operator.",
        "reviewer_notes": "Media Manglers validates identities, timestamps, contracts, and local evidence integrity only. GitHub statements remain external assertions.",
    }


def generated_final_results_templates(batch_root: Path, batch_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Return every deterministic template Media Manglers may have generated.

    The working final-results file is created with the initial prepared package
    and deliberately preserved when targeted evidence later refreshes the
    template.  Queue reconciliation therefore needs both exact generated shapes
    to distinguish untouched application output from external reviewer work.
    """

    batch_root = Path(batch_root)
    current_sources, preliminary_sha, render_version, targeted_identity = _material_basis(batch_root, batch_manifest)
    current = _template_from_basis(
        batch_manifest,
        current_sources,
        preliminary_sha,
        render_version,
        targeted_identity,
    )
    initial_sources = [
        {**item, "acknowledgements": []}
        for item in review_findings._source_summary(batch_root, batch_manifest)
    ]
    initial = _template_from_basis(
        batch_manifest,
        initial_sources,
        "",
        review_targeted_evidence.RENDER_VERSION,
        "",
    )
    templates: list[dict[str, Any]] = []
    for candidate in (initial, current):
        if candidate not in templates:
            templates.append(candidate)
    return templates


def generated_final_results_template_sha256s(batch_root: Path, batch_manifest: dict[str, Any]) -> set[str]:
    """Return exact on-disk SHA-256 values for generated final-results templates."""

    return {
        hashlib.sha256(
            (json.dumps(template, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        ).hexdigest()
        for template in generated_final_results_templates(batch_root, batch_manifest)
    }


def write_review_materials(batch_root: Path, batch_manifest: dict[str, Any]) -> dict[str, str]:
    """Create or refresh the final-results contract without overwriting reviewer work."""

    batch_root = Path(batch_root)
    sources, preliminary_sha, render_version, targeted_identity = _material_basis(batch_root, batch_manifest)
    template = _template_from_basis(
        batch_manifest,
        sources,
        preliminary_sha,
        render_version,
        targeted_identity,
    )
    outputs = {
        "schema": batch_root / "review-results.schema.json",
        "template": batch_root / "review-results.template.json",
        "submission": batch_root / "review-results.json",
    }
    _atomic_json(outputs["schema"], final_results_schema())
    _atomic_json(outputs["template"], template)
    if not outputs["submission"].exists():
        _atomic_json(outputs["submission"], template)

    ready = str(batch_manifest.get("status") or "") == "targeted_evidence_ready" and bool(targeted_identity)
    begin = "<!-- FINAL_RESULTS_BEGIN -->"
    end = "<!-- FINAL_RESULTS_END -->"
    readiness = (
        "The targeted evidence is complete. External Codex may now complete final review and write `review-results.json`."
        if ready
        else "Do not write final results until the batch reaches `targeted_evidence_ready` and this template contains complete targeted identities."
    )
    readme_section = f"""{begin}
## Final external review and structured results

{readiness}

External Codex must review every prepared source and every listed integrity-validated targeted request, then inspect relevant repositories and both open and closed GitHub issues externally. Issue creation or update may occur only after explicit operator approval. Record the exact batch, source, final finding, preliminary finding, targeted request, and issue identities in `review-results.json`.

Media Manglers does not make semantic decisions, inspect GitHub, confirm that an issue exists, create or update issues, or launch an agent. It validates only the local contract, identities, timestamp bounds, lifecycle state, and evidence integrity. Never edit manifests, integrity records, source identities, or ledger data.

`review-results.template.json` is a fresh reference. `review-results.json` is the working file and is never overwritten during material refresh. Accepted final results are immutable; this version does not support superseding an accepted submission.
{end}
"""
    prompt_section = f"""{begin}
## Final-results task

{readiness}

1. Review every prepared source and every integrity-validated targeted-evidence request.
2. Externally inspect relevant repositories plus open and closed GitHub issues.
3. Ask for explicit operator approval before creating or updating any issue.
4. Write final structured results to `review-results.json` using contract version {CONTRACT_VERSION}, document version {DOCUMENT_VERSION}, and exact batch/source/finding/request identities.
5. Put GitHub conclusions in `external_assertions`; Media Manglers will not independently verify issue existence or content.
6. Never edit any manifest, integrity record, source identity, or ledger file, and do not ask Media Manglers to make semantic decisions.
{end}
"""
    for name, section in (("README_FOR_REVIEW.md", readme_section), ("CODEX_REVIEW_PROMPT.md", prompt_section)):
        path = batch_root / name
        if path.is_file():
            _atomic_text(path, _replace_section(path.read_text(encoding="utf-8"), begin, end, section))
    return {key: str(path) for key, path in outputs.items()}


def _targeted_basis(
    ledger_path: Path,
    batch_root: Path,
    batch_id: str,
    preliminary_sha: str,
    *,
    allowed_states: set[str],
) -> tuple[dict[str, Any], list[str]]:
    problems: list[str] = []
    try:
        accepted_sha, preliminary, context = review_targeted_evidence._load_accepted_submission(
            ledger_path,
            batch_root,
            batch_id,
            preliminary_sha,
            allowed_batch_states=allowed_states,
            allowed_source_states=allowed_states,
        )
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        return {"sources": {}, "requests": [], "preliminary_submission_sha256": preliminary_sha}, [str(exc)]
    requests, no_request_sources = review_targeted_evidence._request_specs(batch_root, accepted_sha, preliminary, context)
    request_records: list[dict[str, Any]] = []
    connection = _read_ledger(ledger_path)
    try:
        for item in requests:
            final_root = Path(str(item["final_root"]))
            valid, integrity_problems = review_targeted_evidence._verify_integrity(final_root, str(item["render_signature"]))
            if not valid:
                problems.append(
                    f"Targeted evidence for finding {item['finding_id']!r}, request {item['request_id']!r} failed integrity: "
                    + " ".join(integrity_problems)
                )
                continue
            try:
                request_manifest = json.loads((final_root / "request-manifest.json").read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                problems.append(f"Targeted request manifest could not be revalidated: {exc}.")
                continue
            expected_fields = {
                "source_identity": item["source_identity"],
                "finding_id": item["finding_id"],
                "request_id": item["request_id"],
                "render_signature": item["render_signature"],
            }
            for field, expected in expected_fields.items():
                if str(request_manifest.get(field) or "") != str(expected):
                    problems.append(f"Targeted request manifest field {field!r} contradicts the accepted review basis.")
            if int(request_manifest.get("render_version") or 0) != review_targeted_evidence.RENDER_VERSION:
                problems.append("Targeted request manifest uses an unsupported render version.")
            attempt = connection.execute(
                """
                SELECT 1 FROM inbox_attempts
                WHERE batch_id = ? AND source_id = ? AND attempt_type = 'targeted_evidence_render'
                  AND status = 'completed' AND completed_utc IS NOT NULL AND settings_hash = ?
                LIMIT 1
                """,
                (batch_id, int(item["source_id"]), str(item["render_signature"])),
            ).fetchone()
            if attempt is None:
                problems.append(f"Targeted request {item['request_id']!r} has no completed ledger render attempt.")
            request_records.append(
                {
                    "source_identity": item["source_identity"],
                    "finding_id": item["finding_id"],
                    "request_id": item["request_id"],
                    "render_signature": item["render_signature"],
                    "request_manifest_sha256": review_ledger.sha256_file(final_root / "request-manifest.json"),
                    "integrity_sha256": review_ledger.sha256_file(final_root / "integrity.json"),
                    "reviewed": True,
                }
            )
        for item in no_request_sources:
            attempt = connection.execute(
                """
                SELECT 1 FROM inbox_attempts
                WHERE batch_id = ? AND source_id = ? AND attempt_type = 'targeted_evidence_accounting'
                  AND status = 'completed' AND completed_utc IS NOT NULL AND settings_hash = ?
                LIMIT 1
                """,
                (batch_id, int(item["source_id"]), str(item["accounting_signature"])),
            ).fetchone()
            if attempt is None:
                problems.append(f"Source {item['source_identity']} has no completed no-targeted-request accounting attempt.")
    finally:
        connection.close()
    request_records.sort(key=lambda item: (item["source_identity"], item["finding_id"], item["request_id"]))
    identity_records = [
        {
            "source_identity": item["source_identity"],
            "finding_id": item["finding_id"],
            "request_id": item["request_id"],
            "render_signature": item["render_signature"],
            "reviewed": True,
        }
        for item in request_records
    ]
    targeted_identity = _canonical_sha(
        {
            "render_version": review_targeted_evidence.RENDER_VERSION,
            "preliminary_submission_sha256": accepted_sha,
            "requests": identity_records,
        }
    )
    targeted_manifest = context.get("batch_manifest", {}).get("targeted_evidence")
    if not isinstance(targeted_manifest, dict) or targeted_manifest.get("complete") is not True:
        problems.append("batch-manifest.json does not record complete targeted evidence.")
    else:
        if str(targeted_manifest.get("preliminary_submission_sha256") or "") != accepted_sha:
            problems.append("Batch targeted-evidence metadata contradicts the accepted preliminary submission.")
        if int(targeted_manifest.get("render_version") or 0) != review_targeted_evidence.RENDER_VERSION:
            problems.append("Batch targeted-evidence metadata uses an unsupported render version.")
        if int(targeted_manifest.get("request_count") or 0) != len(requests):
            problems.append("Batch targeted-evidence metadata does not account for every accepted request.")
    preliminary_findings = {
        str(finding["finding_id"]): {
            "source_identity": str(finding["source_identity"]),
            "request_ids": {str(request["request_id"]) for request in finding.get("requests") or []},
        }
        for finding in preliminary.get("findings") or []
    }
    return {
        "batch_id": batch_id,
        "batch_root": batch_root,
        "context": context,
        "sources": context.get("sources", {}),
        "preliminary_submission_sha256": accepted_sha,
        "preliminary_findings": preliminary_findings,
        "requests": request_records,
        "request_identity_records": identity_records,
        "targeted_evidence_render_version": review_targeted_evidence.RENDER_VERSION,
        "targeted_evidence_identity": targeted_identity,
    }, problems


def _text(value: Any, path: str, problems: list[str], *, required: bool = True) -> str:
    if not isinstance(value, str) or (required and not value.strip()):
        problems.append(f"{path} must be a non-empty string." if required else f"{path} must be a string.")
        return ""
    if len(value) > MAX_TEXT:
        problems.append(f"{path} exceeds the {MAX_TEXT}-character limit.")
    return value.strip()


def _id(value: Any, path: str, problems: list[str], *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not RESULT_ID_PATTERN.fullmatch(value):
        problems.append(f"{path} must match {RESULT_ID_PATTERN.pattern!r}.")
        return None
    return value


def _timestamp_bounds(timestamps: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    starts: list[float] = []
    ends: list[float] = []
    for timestamp in timestamps:
        if timestamp.get("kind") == "point":
            starts.append(float(timestamp["at_seconds"]))
            ends.append(float(timestamp["at_seconds"]))
        else:
            starts.append(float(timestamp["start_seconds"]))
            ends.append(float(timestamp["end_seconds"]))
    return (min(starts), max(ends)) if starts else (None, None)


def validate_document(document: Any, basis: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if not isinstance(document, dict):
        return ["The final-results file must contain one JSON object."]
    required_top = {
        "contract_version",
        "document_version",
        "document_type",
        "batch_id",
        "preliminary_submission_sha256",
        "targeted_evidence_render_version",
        "targeted_evidence_identity",
        "reviewed_source_identities",
        "source_results",
        "operator_summary",
        "reviewer_notes",
    }
    unknown_top = set(document) - required_top
    missing_top = required_top - set(document)
    for field in sorted(missing_top):
        problems.append(f"$.{field} is required.")
    for field in sorted(unknown_top):
        problems.append(f"$.{field} is not supported by contract version {CONTRACT_VERSION}.")
    if document.get("contract_version") != CONTRACT_VERSION:
        problems.append(f"$.contract_version must be {CONTRACT_VERSION}.")
    if document.get("document_version") != DOCUMENT_VERSION:
        problems.append(f"$.document_version must be {DOCUMENT_VERSION}.")
    if document.get("document_type") != DOCUMENT_TYPE:
        problems.append(f"$.document_type must be {DOCUMENT_TYPE!r}.")
    if str(document.get("batch_id") or "") != str(basis.get("batch_id") or ""):
        problems.append("$.batch_id contradicts the selected ledger batch.")
    if str(document.get("preliminary_submission_sha256") or "") != str(basis.get("preliminary_submission_sha256") or ""):
        problems.append("$.preliminary_submission_sha256 contradicts the accepted preliminary submission.")
    if document.get("targeted_evidence_render_version") != basis.get("targeted_evidence_render_version"):
        problems.append("$.targeted_evidence_render_version contradicts the validated targeted-evidence basis.")
    if str(document.get("targeted_evidence_identity") or "") != str(basis.get("targeted_evidence_identity") or ""):
        problems.append("$.targeted_evidence_identity contradicts the validated targeted-evidence inventory.")
    _text(document.get("operator_summary"), "$.operator_summary", problems)
    _text(document.get("reviewer_notes"), "$.reviewer_notes", problems)
    expected_sources = set(str(item) for item in basis.get("sources", {}))
    reviewed = document.get("reviewed_source_identities")
    if not isinstance(reviewed, list) or any(not isinstance(item, str) for item in reviewed):
        problems.append("$.reviewed_source_identities must be an array of exact source identity strings.")
        reviewed_sources: list[str] = []
    else:
        reviewed_sources = [str(item) for item in reviewed]
        if len(reviewed_sources) != len(set(reviewed_sources)):
            problems.append("$.reviewed_source_identities contains duplicate identities.")
        if set(reviewed_sources) != expected_sources:
            problems.append("$.reviewed_source_identities must cover exactly every prepared source.")
    source_results = document.get("source_results")
    if not isinstance(source_results, list):
        problems.append("$.source_results must be an array covering every prepared source.")
        return problems
    if not source_results:
        problems.append("$.source_results cannot be empty; use an explicit no_actionable_findings result for each source.")
    seen_sources: set[str] = set()
    seen_result_ids: set[str] = set()
    seen_finding_ids: set[str] = set()
    total_results = 0
    request_records = basis.get("requests") or []
    expected_requests_by_source: dict[str, dict[str, dict[str, Any]]] = {}
    for record in request_records:
        expected_requests_by_source.setdefault(str(record["source_identity"]), {})[str(record["request_id"])] = record
    preliminary = basis.get("preliminary_findings") or {}
    for source_index, source_result in enumerate(source_results):
        path = f"$.source_results[{source_index}]"
        if not isinstance(source_result, dict):
            problems.append(f"{path} must be an object.")
            continue
        required_source = {"source_identity", "source_summary", "notes", "targeted_request_acknowledgements", "results"}
        for field in sorted(required_source - set(source_result)):
            problems.append(f"{path}.{field} is required.")
        for field in sorted(set(source_result) - required_source):
            problems.append(f"{path}.{field} is not supported.")
        identity = str(source_result.get("source_identity") or "")
        if identity not in expected_sources:
            problems.append(f"{path}.source_identity is unknown to the selected batch.")
        if identity in seen_sources:
            problems.append(f"{path}.source_identity duplicates another source result.")
        seen_sources.add(identity)
        _text(source_result.get("source_summary"), f"{path}.source_summary", problems)
        _text(source_result.get("notes"), f"{path}.notes", problems)
        acknowledgements = source_result.get("targeted_request_acknowledgements")
        submitted_acks: dict[str, dict[str, Any]] = {}
        if not isinstance(acknowledgements, list):
            problems.append(f"{path}.targeted_request_acknowledgements must be an array.")
        else:
            for ack_index, ack in enumerate(acknowledgements):
                ack_path = f"{path}.targeted_request_acknowledgements[{ack_index}]"
                if not isinstance(ack, dict):
                    problems.append(f"{ack_path} must be an object.")
                    continue
                required_ack = {"source_identity", "finding_id", "request_id", "render_signature", "reviewed"}
                if set(ack) != required_ack:
                    problems.append(f"{ack_path} must contain exactly source_identity, finding_id, request_id, render_signature, and reviewed.")
                request_id = str(ack.get("request_id") or "")
                if request_id in submitted_acks:
                    problems.append(f"{ack_path}.request_id duplicates another acknowledgement.")
                submitted_acks[request_id] = ack
                expected = expected_requests_by_source.get(identity, {}).get(request_id)
                if expected is None:
                    problems.append(f"{ack_path} references an unknown targeted request for this source.")
                else:
                    for field in ("source_identity", "finding_id", "request_id", "render_signature"):
                        if str(ack.get(field) or "") != str(expected[field]):
                            problems.append(f"{ack_path}.{field} contradicts the validated targeted request.")
                if ack.get("reviewed") is not True:
                    problems.append(f"{ack_path}.reviewed must be true after external review of the targeted evidence.")
        if set(submitted_acks) != set(expected_requests_by_source.get(identity, {})):
            missing = sorted(set(expected_requests_by_source.get(identity, {})) - set(submitted_acks))
            unknown = sorted(set(submitted_acks) - set(expected_requests_by_source.get(identity, {})))
            if missing:
                problems.append(f"{path} does not acknowledge every targeted request: {', '.join(missing)}.")
            if unknown:
                problems.append(f"{path} acknowledges unknown targeted requests: {', '.join(unknown)}.")
        results = source_result.get("results")
        if not isinstance(results, list) or not results:
            problems.append(f"{path}.results must contain at least one explicit final disposition.")
            continue
        duration = float((basis.get("sources", {}).get(identity) or {}).get("duration_seconds") or 0.0)
        for result_index, result in enumerate(results):
            total_results += 1
            result_path = f"{path}.results[{result_index}]"
            if not isinstance(result, dict):
                problems.append(f"{result_path} must be an object.")
                continue
            required_result = {
                "result_id",
                "finding_id",
                "acknowledged_preliminary_finding_ids",
                "acknowledged_request_ids",
                "timestamps",
                "disposition",
                "summary",
                "notes",
                "external_assertions",
                "issue",
            }
            for field in sorted(required_result - set(result)):
                problems.append(f"{result_path}.{field} is required.")
            for field in sorted(set(result) - required_result):
                problems.append(f"{result_path}.{field} is not supported.")
            result_id = _id(result.get("result_id"), f"{result_path}.result_id", problems)
            if result_id in seen_result_ids:
                problems.append(f"{result_path}.result_id duplicates another final result ID.")
            if result_id:
                seen_result_ids.add(result_id)
            disposition = str(result.get("disposition") or "")
            if disposition not in DISPOSITIONS:
                problems.append(f"{result_path}.disposition is unsupported; expected one of: {', '.join(sorted(DISPOSITIONS))}.")
            finding_id = _id(result.get("finding_id"), f"{result_path}.finding_id", problems, nullable=True)
            if finding_id in seen_finding_ids:
                problems.append(f"{result_path}.finding_id duplicates another final finding ID.")
            if finding_id:
                seen_finding_ids.add(finding_id)
            if disposition not in {"no_actionable_findings", "review_failure"} and not finding_id:
                problems.append(f"{result_path}.finding_id is required for this disposition.")
            if disposition in {"no_actionable_findings", "review_failure"} and finding_id is not None:
                problems.append(f"{result_path}.finding_id must be null for this disposition.")
            _text(result.get("summary"), f"{result_path}.summary", problems)
            _text(result.get("notes"), f"{result_path}.notes", problems)
            assertions = result.get("external_assertions")
            if not isinstance(assertions, list) or any(not isinstance(item, str) or not item.strip() for item in assertions):
                problems.append(f"{result_path}.external_assertions must be an array of non-empty external assertion strings.")
            preliminary_ids = result.get("acknowledged_preliminary_finding_ids")
            if not isinstance(preliminary_ids, list) or any(not isinstance(item, str) for item in preliminary_ids):
                problems.append(f"{result_path}.acknowledged_preliminary_finding_ids must be an array of finding IDs.")
                preliminary_ids = []
            elif len(preliminary_ids) != len(set(preliminary_ids)):
                problems.append(f"{result_path}.acknowledged_preliminary_finding_ids contains duplicates.")
            known_requests: set[str] = set()
            for preliminary_id in preliminary_ids:
                info = preliminary.get(preliminary_id)
                if info is None or str(info.get("source_identity") or "") != identity:
                    problems.append(f"{result_path} acknowledges unknown or contradictory preliminary finding {preliminary_id!r}.")
                else:
                    known_requests.update(str(item) for item in info.get("request_ids") or set())
            request_ids = result.get("acknowledged_request_ids")
            if not isinstance(request_ids, list) or any(not isinstance(item, str) for item in request_ids):
                problems.append(f"{result_path}.acknowledged_request_ids must be an array of request IDs.")
                request_ids = []
            elif len(request_ids) != len(set(request_ids)):
                problems.append(f"{result_path}.acknowledged_request_ids contains duplicates.")
            for request_id in request_ids:
                expected_request = expected_requests_by_source.get(identity, {}).get(request_id)
                if expected_request is None:
                    problems.append(f"{result_path} acknowledges unknown targeted request {request_id!r}.")
                elif preliminary_ids and request_id not in known_requests:
                    problems.append(f"{result_path} acknowledges request {request_id!r} without its matching preliminary finding.")
            timestamps = result.get("timestamps")
            valid_timestamps: list[dict[str, Any]] = []
            if not isinstance(timestamps, list):
                problems.append(f"{result_path}.timestamps must be an array.")
            else:
                for timestamp_index, timestamp in enumerate(timestamps):
                    timestamp_path = f"{result_path}.timestamps[{timestamp_index}]"
                    if not isinstance(timestamp, dict) or timestamp.get("kind") not in {"point", "range"}:
                        problems.append(f"{timestamp_path} must be a point or range timestamp object.")
                        continue
                    if timestamp.get("kind") == "point":
                        if set(timestamp) != {"kind", "at_seconds"} or not _is_number(timestamp.get("at_seconds")):
                            problems.append(f"{timestamp_path} must contain only a finite at_seconds value.")
                            continue
                        start = end = float(timestamp["at_seconds"])
                    else:
                        if set(timestamp) != {"kind", "start_seconds", "end_seconds"} or not _is_number(timestamp.get("start_seconds")) or not _is_number(timestamp.get("end_seconds")):
                            problems.append(f"{timestamp_path} must contain finite start_seconds and end_seconds values.")
                            continue
                        start = float(timestamp["start_seconds"])
                        end = float(timestamp["end_seconds"])
                        if end < start:
                            problems.append(f"{timestamp_path}.end_seconds must be greater than or equal to start_seconds.")
                    if start < 0 or end > duration:
                        problems.append(f"{timestamp_path} falls outside the source duration 0..{duration:g} seconds.")
                    valid_timestamps.append(timestamp)
            issue = result.get("issue")
            required_action = ISSUE_DISPOSITIONS.get(disposition)
            if required_action is None:
                if issue is not None:
                    problems.append(f"{result_path}.issue must be null for disposition {disposition!r}.")
            elif not isinstance(issue, dict):
                problems.append(f"{result_path}.issue is required for disposition {disposition!r}.")
            else:
                required_issue = {"repository", "issue_number", "issue_url", "action", "authorization_note"}
                if set(issue) != required_issue:
                    problems.append(f"{result_path}.issue must contain exactly repository, issue_number, issue_url, action, and authorization_note.")
                repository = str(issue.get("repository") or "")
                number = issue.get("issue_number")
                url = str(issue.get("issue_url") or "")
                action = str(issue.get("action") or "")
                authorization = str(issue.get("authorization_note") or "").strip()
                if not REPOSITORY_PATTERN.fullmatch(repository):
                    problems.append(f"{result_path}.issue.repository must use owner/repository form.")
                if not isinstance(number, int) or isinstance(number, bool) or number < 1:
                    problems.append(f"{result_path}.issue.issue_number must be a positive integer.")
                expected_url = f"https://github.com/{repository}/issues/{number}" if repository and isinstance(number, int) else ""
                if url.rstrip("/") != expected_url:
                    problems.append(f"{result_path}.issue.issue_url must exactly match its repository and issue number.")
                if action != required_action:
                    problems.append(f"{result_path}.issue.action must be {required_action!r} for this disposition.")
                if action in AUTHORIZED_ISSUE_ACTIONS and not authorization:
                    problems.append(f"{result_path}.issue.authorization_note must record explicit operator approval for created or updated issue actions.")
                if action not in AUTHORIZED_ISSUE_ACTIONS and authorization:
                    problems.append(f"{result_path}.issue.authorization_note must be empty when no issue creation/update was authorized.")
    if seen_sources != expected_sources:
        missing = sorted(expected_sources - seen_sources)
        unknown = sorted(seen_sources - expected_sources)
        if missing:
            problems.append("$.source_results is missing prepared sources: " + ", ".join(missing) + ".")
        if unknown:
            problems.append("$.source_results contains unknown sources: " + ", ".join(unknown) + ".")
    if total_results > MAX_RESULTS:
        problems.append(f"The submission may contain at most {MAX_RESULTS} final result records.")
    return list(dict.fromkeys(problems))


def _terminal_submission_state(ledger_path: Path, batch_id: str, submission_sha: str) -> tuple[str | None, list[str]]:
    connection = inbox_records.connect_read_only(ledger_path)
    if connection is None:
        return None, []
    try:
        rows = connection.execute(
            """
            SELECT status, error_message FROM inbox_attempts
            WHERE batch_id = ? AND attempt_type = 'final_results_import'
              AND status IN ('accepted', 'rejected') AND completed_utc IS NOT NULL AND settings_hash = ?
            ORDER BY attempt_id
            """,
            (batch_id, submission_sha),
        ).fetchall()
    finally:
        connection.close()
    statuses = {str(row["status"]) for row in rows}
    if len(statuses) > 1:
        raise FinalResultsError("The ledger contains contradictory accepted and rejected attempts for this final-results submission.")
    if "accepted" in statuses:
        return "accepted", []
    if "rejected" in statuses:
        details: list[str] = []
        for row in rows:
            for problem in str(row["error_message"] or "").splitlines():
                if problem and problem not in details:
                    details.append(problem)
        return "rejected", details
    return None, []


def _accepted_results_sha(connection: sqlite3.Connection, batch_id: str) -> str:
    source_count = int(connection.execute("SELECT COUNT(*) FROM inbox_batch_sources WHERE batch_id = ?", (batch_id,)).fetchone()[0])
    rows = connection.execute(
        """
        SELECT settings_hash, COUNT(DISTINCT source_id) AS source_count, MAX(attempt_id) AS latest
        FROM inbox_attempts
        WHERE batch_id = ? AND attempt_type = 'final_results_import' AND status = 'accepted' AND completed_utc IS NOT NULL
        GROUP BY settings_hash ORDER BY latest DESC
        """,
        (batch_id,),
    ).fetchall()
    complete = [str(row["settings_hash"] or "") for row in rows if int(row["source_count"] or 0) == source_count]
    return complete[0] if complete else ""


def _result_rows(document: dict[str, Any]) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    return [
        (str(source["source_identity"]), source, result)
        for source in document.get("source_results") or []
        for result in source.get("results") or []
    ]


def _reconcile_accepted_files(
    batch_root: Path,
    raw: bytes,
    validation_path: Path,
    validation: dict[str, Any],
    submission_sha: str,
) -> None:
    _atomic_bytes(batch_root / "review-results.json", raw)
    validation["accepted"] = True
    validation["import_phase"] = "accepted"
    validation["resulting_batch_state"] = "results_received"
    validation.setdefault("accepted_utc", _utc_now())
    _atomic_json(validation_path, validation)
    manifest_path = batch_root / "batch-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["status"] = "results_received"
    manifest["final_results"] = {
        "contract_version": CONTRACT_VERSION,
        "document_version": DOCUMENT_VERSION,
        "submission_sha256": submission_sha,
        "accepted": True,
        "updated_utc": _utc_now(),
    }
    _atomic_json(manifest_path, manifest)
    write_review_materials(batch_root, manifest)


def import_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Preserve, validate, and transactionally import one final-results submission."""

    ledger_path = Path(str(payload.get("ledger_path") or ""))
    batch_id = str(payload.get("expected_batch_id") or payload.get("batch_id") or "")
    results_path = Path(str(payload.get("results_path") or ""))
    supplied_batch = str(payload.get("batch_path") or "")
    if not batch_id:
        raise ValueError("expected_batch_id is required.")
    if not str(results_path) or str(results_path) == ".":
        raise ValueError("results_path is required.")
    try:
        batch_root = review_targeted_evidence._resolve_batch_root(ledger_path, batch_id, supplied_batch)
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        return {"contract_version": CONTRACT_VERSION, "action": "import_final_results", "accepted": False, "idempotent": False, "status": "rejected", "batch_id": batch_id, "problems": [str(exc)]}
    try:
        raw = results_path.read_bytes()
    except OSError as exc:
        return {"contract_version": CONTRACT_VERSION, "action": "import_final_results", "accepted": False, "idempotent": False, "status": "rejected", "batch_id": batch_id, "problems": [f"The review-results file could not be read: {exc}."]}
    submission_sha = hashlib.sha256(raw).hexdigest()
    history_root = batch_root / "imports" / "review-results" / submission_sha[:24]
    if not _within(batch_root, history_root):
        raise FinalResultsError("Final-results history must remain inside the batch.")
    submission_copy = history_root / "review-results.json"
    validation_path = history_root / "validation.json"
    existing = review_findings._existing_validation(validation_path)
    terminal_state, terminal_problems = _terminal_submission_state(ledger_path, batch_id, submission_sha)
    if terminal_state is not None:
        accepted = terminal_state == "accepted"
        validation = existing or {
            "contract_version": CONTRACT_VERSION,
            "document_version": DOCUMENT_VERSION,
            "submission_sha256": submission_sha,
            "expected_batch_id": batch_id,
            "validated_utc": _utc_now(),
        }
        problems = [] if accepted else list(validation.get("problems") or terminal_problems)
        validation.update(
            {
                "accepted": accepted,
                "import_phase": terminal_state,
                "resulting_batch_state": "results_received" if accepted else "rejected",
                "problems": problems,
                "reconciled_from_ledger_utc": _utc_now(),
            }
        )
        if accepted:
            _reconcile_accepted_files(batch_root, raw, validation_path, validation, submission_sha)
        else:
            _atomic_json(validation_path, validation)
        return {
            "contract_version": CONTRACT_VERSION,
            "action": "import_final_results",
            "accepted": accepted,
            "idempotent": True,
            "status": "results_received" if accepted else "rejected",
            "batch_id": batch_id,
            "submission_sha256": submission_sha,
            "problems": problems,
            "validation_record": str(validation_path),
        }
    if existing is not None:
        existing["accepted"] = False
        existing["import_phase"] = "staged"
        existing["resume_count"] = int(existing.get("resume_count") or 0) + 1
        existing["resumed_utc"] = _utc_now()
        _atomic_json(validation_path, existing)
    _atomic_bytes(submission_copy, raw)
    connection = _read_ledger(ledger_path)
    try:
        batch_state_row = connection.execute("SELECT status FROM inbox_batches WHERE batch_id = ?", (batch_id,)).fetchone()
        batch_state = str(batch_state_row["status"] or "") if batch_state_row else ""
        accepted_other = _accepted_results_sha(connection, batch_id)
    finally:
        connection.close()
    basis, basis_problems = _targeted_basis(
        ledger_path,
        batch_root,
        batch_id,
        "",
        allowed_states={batch_state} if batch_state else IMPORT_ELIGIBLE_BATCH_STATES,
    )
    parse_problems: list[str] = []
    document: dict[str, Any] | None = None
    try:
        parsed = json.loads(raw.decode("utf-8-sig"))
        if isinstance(parsed, dict):
            document = parsed
        else:
            parse_problems.append("The final-results file must contain one JSON object.")
    except UnicodeError as exc:
        parse_problems.append(f"The final-results file is not valid UTF-8 text: {exc}.")
    except json.JSONDecodeError as exc:
        parse_problems.append(f"Malformed JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}.")
    problems = [*basis_problems, *parse_problems]
    if batch_state not in IMPORT_ELIGIBLE_BATCH_STATES:
        problems.append("Final results may be imported only when the complete batch is targeted_evidence_ready.")
    if accepted_other and accepted_other != submission_sha:
        problems.append("A different final-results submission is already accepted and immutable; supersession is not supported in this contract version.")
    if document is not None:
        problems.extend(validate_document(document, basis))
    problems = list(dict.fromkeys(problems))
    source_results = list(document.get("source_results") or []) if document is not None and isinstance(document.get("source_results"), list) else []
    result_count = sum(len(source.get("results") or []) for source in source_results if isinstance(source, dict) and isinstance(source.get("results"), list))
    validation = {
        "contract_version": CONTRACT_VERSION,
        "document_version": DOCUMENT_VERSION,
        "submission_sha256": submission_sha,
        "expected_batch_id": batch_id,
        "validated_utc": _utc_now(),
        "staged_utc": str((existing or {}).get("staged_utc") or _utc_now()),
        "import_phase": "staged",
        "resume_count": int((existing or {}).get("resume_count") or 0),
        "accepted": False,
        "idempotent": False,
        "source_count": len(source_results),
        "result_count": result_count,
        "problems": problems,
        "resulting_batch_state": batch_state,
        "independently_validated": [
            "batch_identity",
            "source_identity_and_duration",
            "preliminary_submission_identity",
            "targeted_evidence_integrity",
            "timestamp_bounds",
            "contract_consistency",
        ] if not problems else [],
        "external_assertions_not_independently_verified": True,
    }
    _atomic_json(validation_path, validation)
    callback = payload.get("_after_validation_staged")
    if callable(callback):
        callback(validation)
    connection = inbox_records.connect(ledger_path, must_exist=True)
    try:
        connection.execute("BEGIN IMMEDIATE")
        source_ids = sorted(int(item["source_id"]) for item in basis.get("sources", {}).values())
        now = _utc_now()
        if problems:
            for source_id in source_ids:
                connection.execute(
                    "INSERT INTO inbox_attempts (source_id, batch_id, attempt_type, status, started_utc, completed_utc, settings_hash, error_message) VALUES (?, ?, 'final_results_import', 'rejected', ?, ?, ?, ?)",
                    (source_id, batch_id, now, now, submission_sha, "\n".join(problems)),
                )
            review_ledger._insert_lifecycle_event(
                connection,
                source_id=None,
                batch_id=batch_id,
                event_type="final_results_rejected",
                from_state=batch_state,
                to_state=batch_state,
                details={"submission_sha256": submission_sha, "problem_count": len(problems)},
            )
            connection.commit()
            validation.update({"import_phase": "rejected", "resulting_batch_state": "rejected", "rejected_utc": _utc_now()})
            _atomic_json(validation_path, validation)
            return {
                "contract_version": CONTRACT_VERSION,
                "action": "import_final_results",
                "accepted": False,
                "idempotent": False,
                "status": "rejected",
                "batch_id": batch_id,
                "submission_sha256": submission_sha,
                "source_count": len(source_results),
                "result_count": result_count,
                "problems": problems,
                "validation_record": str(validation_path),
            }
        if document is None:
            raise FinalResultsError("Validated final-results document is unavailable.")
        current_batch_state = str(connection.execute("SELECT status FROM inbox_batches WHERE batch_id = ?", (batch_id,)).fetchone()[0])
        if current_batch_state != "targeted_evidence_ready":
            raise FinalResultsError("The batch lifecycle changed before final-results import could commit.")
        if connection.execute("SELECT 1 FROM inbox_final_results WHERE batch_id = ? LIMIT 1", (batch_id,)).fetchone() is not None:
            raise FinalResultsError("Normalized final results already exist for this batch; silent replacement is forbidden.")
        for identity, source_result, result in _result_rows(document):
            source_id = int(basis["sources"][identity]["source_id"])
            finding_id = result.get("finding_id")
            start, end = _timestamp_bounds(list(result.get("timestamps") or []))
            if finding_id is not None:
                connection.execute(
                    """
                    INSERT INTO inbox_findings (finding_id, batch_id, source_id, stage, status, start_seconds, end_seconds, details_json, created_utc, updated_utc)
                    VALUES (?, ?, ?, 'final', ?, ?, ?, ?, ?, ?)
                    """,
                    (finding_id, batch_id, source_id, result["disposition"], start, end, json.dumps({"result_id": result["result_id"], "submission_sha256": submission_sha}, sort_keys=True), now, now),
                )
            issue = result.get("issue") if isinstance(result.get("issue"), dict) else {}
            details = {"source_result": source_result, "result": result, "external_assertions_not_independently_verified": True}
            connection.execute(
                """
                INSERT INTO inbox_final_results
                    (result_id, batch_id, source_id, finding_id, submission_sha256, preliminary_submission_sha256,
                     disposition, issue_repository, issue_number, issue_url, issue_action, authorization_note,
                     start_seconds, end_seconds, summary, notes, external_assertions_json, details_json, created_utc, updated_utc)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result["result_id"], batch_id, source_id, finding_id, submission_sha, basis["preliminary_submission_sha256"],
                    result["disposition"], issue.get("repository"), issue.get("issue_number"), issue.get("issue_url"),
                    issue.get("action"), issue.get("authorization_note"), start, end, result["summary"], result["notes"],
                    json.dumps(result.get("external_assertions") or [], sort_keys=True), json.dumps(details, sort_keys=True), now, now,
                ),
            )
        old_batch_state = current_batch_state
        for identity, source in basis["sources"].items():
            source_id = int(source["source_id"])
            old_source = str(connection.execute("SELECT lifecycle_state FROM inbox_sources WHERE source_id = ?", (source_id,)).fetchone()[0])
            connection.execute("UPDATE inbox_sources SET lifecycle_state = 'results_received', updated_utc = ? WHERE source_id = ?", (now, source_id))
            connection.execute("UPDATE inbox_batch_sources SET state = 'results_received', updated_utc = ? WHERE batch_id = ? AND source_id = ?", (now, batch_id, source_id))
            connection.execute(
                "INSERT INTO inbox_attempts (source_id, batch_id, attempt_type, status, started_utc, completed_utc, settings_hash) VALUES (?, ?, 'final_results_import', 'accepted', ?, ?, ?)",
                (source_id, batch_id, now, now, submission_sha),
            )
            review_ledger._insert_lifecycle_event(
                connection,
                source_id=source_id,
                batch_id=batch_id,
                event_type="final_results_imported",
                from_state=old_source,
                to_state="results_received",
                details={"submission_sha256": submission_sha, "source_identity": identity},
            )
        connection.execute("UPDATE inbox_batches SET status = 'results_received', updated_utc = ? WHERE batch_id = ?", (now, batch_id))
        review_ledger._insert_lifecycle_event(
            connection,
            source_id=None,
            batch_id=batch_id,
            event_type="final_results_imported",
            from_state=old_batch_state,
            to_state="results_received",
            details={"submission_sha256": submission_sha, "result_count": result_count},
        )
        foreign_keys = inbox_records.link_problems(connection)
        if foreign_keys:
            raise FinalResultsError(f"Foreign-key validation failed after final-results import: {foreign_keys!r}")
        connection.commit()
    except Exception as exc:
        connection.rollback()
        validation["problems"] = [*problems, f"Import failed safely: {exc}"]
        validation["import_error"] = str(exc)
        _atomic_json(validation_path, validation)
        return {
            "contract_version": CONTRACT_VERSION,
            "action": "import_final_results",
            "accepted": False,
            "idempotent": False,
            "status": "rejected",
            "batch_id": batch_id,
            "submission_sha256": submission_sha,
            "problems": validation["problems"],
            "validation_record": str(validation_path),
        }
    finally:
        connection.close()
    callback = payload.get("_after_ledger_commit")
    if callable(callback):
        callback(validation)
    validation.update({"accepted": True, "import_phase": "accepted", "resulting_batch_state": "results_received", "accepted_utc": _utc_now(), "problems": []})
    _reconcile_accepted_files(batch_root, raw, validation_path, validation, submission_sha)
    return {
        "contract_version": CONTRACT_VERSION,
        "document_version": DOCUMENT_VERSION,
        "action": "import_final_results",
        "accepted": True,
        "idempotent": False,
        "status": "results_received",
        "batch_id": batch_id,
        "submission_sha256": submission_sha,
        "source_count": len(source_results),
        "result_count": result_count,
        "problems": [],
        "validation_record": str(validation_path),
        "submission_record": str(submission_copy),
        "canonical_submission": str(batch_root / "review-results.json"),
    }


def load_accepted_results(
    ledger_path: Path,
    batch_root: Path,
    batch_id: str,
    expected_sha: str = "",
) -> tuple[str, dict[str, Any], dict[str, Any], Path, Path]:
    """Load and revalidate immutable accepted results for finalization."""

    connection = _read_ledger(ledger_path)
    try:
        accepted_sha = _accepted_results_sha(connection, batch_id)
        batch_row = connection.execute("SELECT status FROM inbox_batches WHERE batch_id = ?", (batch_id,)).fetchone()
    finally:
        connection.close()
    if batch_row is None:
        raise FinalResultsError(f"Batch {batch_id!r} is unknown to the Review Media Inbox ledger.")
    batch_state = str(batch_row[0])
    if not accepted_sha or expected_sha and expected_sha != accepted_sha:
        raise FinalResultsError("The batch has no matching completely accepted final-results submission.")
    history_root = batch_root / "imports" / "review-results" / accepted_sha[:24]
    submission = history_root / "review-results.json"
    validation_path = history_root / "validation.json"
    if not submission.is_file() or review_ledger.sha256_file(submission) != accepted_sha:
        raise FinalResultsError("Accepted final results are missing or their SHA-256 changed.")
    validation = review_findings._existing_validation(validation_path)
    if validation is None:
        raise FinalResultsError("Accepted final-results validation history is missing or malformed.")
    try:
        document = json.loads(submission.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FinalResultsError(f"Accepted final results cannot be parsed: {exc}.") from exc
    basis, basis_problems = _targeted_basis(
        ledger_path,
        batch_root,
        batch_id,
        str(document.get("preliminary_submission_sha256") or ""),
        allowed_states=REVALIDATION_STATES,
    )
    problems = [*basis_problems, *validate_document(document, basis)]
    if problems:
        raise FinalResultsError("Accepted final results failed complete revalidation: " + " ".join(problems))
    connection = _read_ledger(ledger_path)
    try:
        normalized_ids = {str(row[0]) for row in connection.execute("SELECT result_id FROM inbox_final_results WHERE batch_id = ? AND submission_sha256 = ?", (batch_id, accepted_sha)).fetchall()}
    finally:
        connection.close()
    document_ids = {str(result["result_id"]) for _identity, _source, result in _result_rows(document)}
    if normalized_ids != document_ids:
        raise FinalResultsError("Normalized final-result identities contradict accepted immutable history.")
    if validation.get("accepted") is not True or validation.get("import_phase") != "accepted":
        validation.update({"accepted": True, "import_phase": "accepted", "resulting_batch_state": "results_received", "reconciled_from_ledger_utc": _utc_now()})
        _atomic_json(validation_path, validation)
    return accepted_sha, document, basis, submission, validation_path
