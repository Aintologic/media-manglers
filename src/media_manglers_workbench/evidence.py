"""JSON-first evidence package parser for the workbench."""

from __future__ import annotations

from dataclasses import dataclass, field
import csv
import json
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class EvidenceFile:
    label: str
    path: Path
    kind: str


@dataclass(slots=True)
class EvidenceCandidate:
    item_id: str
    item_type: str
    title: str
    source_filename: str = ""
    timestamp_start: str = ""
    timestamp_end: str = ""
    marker_timestamp: str = ""
    confidence: str = ""
    repo_hint: str = "UNKNOWN"
    repo_confidence: str = "unknown"
    requires_github_review: bool = True
    transcript_excerpt: str = ""
    transcript_window_text: str = ""
    narration_context_text: str = ""
    render_status: str = "rendered"
    reason: str = ""
    evidence_folder: Path | None = None
    transcript_window_path: Path | None = None
    narration_context_path: Path | None = None
    narration_context_json_path: Path | None = None
    ticket_markdown_path: Path | None = None
    metadata_path: Path | None = None
    frame_index_path: Path | None = None
    frame_paths: list[Path] = field(default_factory=list)
    panel_crop_paths: list[Path] = field(default_factory=list)
    audio_paths: list[Path] = field(default_factory=list)
    full_transcript_paths: list[Path] = field(default_factory=list)
    evidence_files: list[EvidenceFile] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SessionMention:
    mention_id: str
    record_type: str
    source_filename: str = ""
    timestamp: str = ""
    timestamp_seconds: float = 0.0
    excerpt: str = ""
    confidence: str = ""
    render_status: str = ""
    repo_hint: str = "UNKNOWN"
    frame_available: bool = False
    audio_available: bool = False
    related_mention_ids: list[str] = field(default_factory=list)
    narration_context_path: Path | None = None
    full_transcript_paths: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SessionRelationship:
    mention_a: str
    mention_b: str
    classification: str
    reasons: list[str] = field(default_factory=list)
    shared_terms: list[str] = field(default_factory=list)
    intervening_boundary: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SessionThread:
    thread_hint_id: str
    mention_ids: list[str]
    classification: str
    reasons: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvidencePackage:
    root: Path
    manifest: dict[str, Any] = field(default_factory=dict)
    candidate_payload: dict[str, Any] = field(default_factory=dict)
    review_needed_payload: dict[str, Any] = field(default_factory=dict)
    repo_routing_payload: dict[str, Any] = field(default_factory=dict)
    all_candidates_payload: dict[str, Any] = field(default_factory=dict)
    session_timeline_payload: dict[str, Any] = field(default_factory=dict)
    ticket_thread_hints_payload: dict[str, Any] = field(default_factory=dict)
    unassigned_mentions_payload: dict[str, Any] = field(default_factory=dict)
    package_status: dict[str, Any] = field(default_factory=dict)
    candidates: list[EvidenceCandidate] = field(default_factory=list)
    unrendered_candidates: list[EvidenceCandidate] = field(default_factory=list)
    review_needed: list[EvidenceCandidate] = field(default_factory=list)
    session_mentions: list[SessionMention] = field(default_factory=list)
    session_relationships: list[SessionRelationship] = field(default_factory=list)
    proposed_threads: list[SessionThread] = field(default_factory=list)
    unassigned_mention_ids: list[str] = field(default_factory=list)
    # 199: words said in passing, listed for the operator to decide; never tickets.
    mentioned_not_asked: list[dict[str, Any]] = field(default_factory=list)
    start_here_path: Path | None = None
    session_codex_prompt_path: Path | None = None
    session_claude_prompt_path: Path | None = None
    portable_zip_path: Path | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def all_items(self) -> list[EvidenceCandidate]:
        return [*self.candidates, *self.unrendered_candidates, *self.review_needed]


def _read_json(path: Path, warnings: list[str], *, optional: bool = True) -> dict[str, Any]:
    if not path.exists():
        if optional:
            warnings.append(f"Missing optional evidence JSON: {path.name}")
        else:
            warnings.append(f"Missing evidence JSON: {path.name}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        warnings.append(f"Could not parse {path.name}: {exc}")
        return {}


def _read_text(path: Path | None, warnings: list[str]) -> str:
    if not path or not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        warnings.append(f"Could not read {path.name}: {exc}")
        return ""


def _coerce_timestamp(raw: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _read_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def _coerce_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return default


def _resolve_path(root: Path, value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    if path.is_absolute():
        return path
    return root / text.replace("/", "\\")


def _append_unique(paths: list[Path], path: Path | None) -> None:
    if path and path not in paths:
        paths.append(path)


def _candidate_repo_rows(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in payload.get("candidates") or []:
        if isinstance(row, dict) and row.get("evidence_id"):
            rows[str(row["evidence_id"])] = row
    return rows


def _parse_frame_index(root: Path, frame_index_path: Path | None, frame_paths: list[Path], panel_paths: list[Path]) -> None:
    if not frame_index_path or not frame_index_path.exists():
        return
    with frame_index_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            _append_unique(frame_paths, _resolve_path(root, row.get("full_frame_path")))
            _append_unique(frame_paths, _resolve_path(root, row.get("relative_path")))
            _append_unique(panel_paths, _resolve_path(root, row.get("panel_crop_path")))


def _collect_candidate_paths(root: Path, raw: dict[str, Any], candidate_id: str) -> tuple[list[Path], list[Path], list[Path]]:
    frame_paths: list[Path] = []
    panel_paths: list[Path] = []
    audio_paths: list[Path] = []
    for frame in raw.get("frames") or []:
        if not isinstance(frame, dict):
            continue
        _append_unique(frame_paths, _resolve_path(root, frame.get("relative_path")))
        _append_unique(frame_paths, _resolve_path(root, frame.get("full_frame_path")))
        for panel in frame.get("panels") or []:
            if not isinstance(panel, dict):
                continue
            _append_unique(panel_paths, _resolve_path(root, panel.get("relative_path")))
            _append_unique(panel_paths, _resolve_path(root, panel.get("panel_crop_path")))
    audio = raw.get("audio_snippet") or {}
    if isinstance(audio, dict):
        _append_unique(audio_paths, _resolve_path(root, audio.get("relative_path")))
        _append_unique(audio_paths, _resolve_path(root, audio.get("path")))
    for supporting_audio in raw.get("supporting_audio_snippets") or []:
        if isinstance(supporting_audio, dict):
            _append_unique(audio_paths, _resolve_path(root, supporting_audio.get("relative_path")))
            _append_unique(audio_paths, _resolve_path(root, supporting_audio.get("path")))
    if candidate_id:
        _append_unique(audio_paths, root / "evidence_items" / candidate_id / "audio_snippet.mp3")
    return frame_paths, panel_paths, audio_paths


def _build_evidence_files(candidate: EvidenceCandidate) -> list[EvidenceFile]:
    files: list[EvidenceFile] = []
    for label, path, kind in (
        ("Transcript window", candidate.transcript_window_path, "transcript"),
        ("Narration context", candidate.narration_context_path, "narration"),
        ("Narration context JSON", candidate.narration_context_json_path, "narration-json"),
        ("Ticket markdown", candidate.ticket_markdown_path, "ticket"),
        ("Metadata", candidate.metadata_path, "metadata"),
        ("Frame index", candidate.frame_index_path, "frames"),
    ):
        if path:
            files.append(EvidenceFile(label=label, path=path, kind=kind))
    files.extend(EvidenceFile(label="Frame", path=path, kind="frame") for path in candidate.frame_paths)
    files.extend(EvidenceFile(label="Panel crop", path=path, kind="panel") for path in candidate.panel_crop_paths)
    files.extend(EvidenceFile(label="Audio snippet", path=path, kind="audio") for path in candidate.audio_paths)
    files.extend(
        EvidenceFile(label="Full transcript", path=path, kind="full-transcript")
        for path in candidate.full_transcript_paths
    )
    return files


def _parse_candidate(root: Path, raw: dict[str, Any], repo_rows: dict[str, dict[str, Any]], warnings: list[str]) -> EvidenceCandidate:
    candidate_id = str(raw.get("evidence_id") or raw.get("id") or raw.get("candidate_id") or "candidate")
    repo_row = repo_rows.get(candidate_id, {})
    evidence_folder = root / "evidence_items" / candidate_id
    transcript_window_path = _resolve_path(root, raw.get("transcript_window_path")) or evidence_folder / "transcript_window.md"
    narration_context_path = _resolve_path(root, raw.get("narration_context_path")) or evidence_folder / "narration_context.md"
    narration_context_json_path = _resolve_path(root, raw.get("narration_context_json_path")) or evidence_folder / "narration_context.json"
    ticket_markdown_path = _resolve_path(root, raw.get("ticket_markdown_path")) or evidence_folder / "ticket.md"
    metadata_path = _resolve_path(root, raw.get("metadata_path")) or evidence_folder / "metadata.json"
    frame_index_path = _resolve_path(root, raw.get("frame_index_path")) or evidence_folder / "frame_index.csv"
    frame_paths, panel_paths, audio_paths = _collect_candidate_paths(root, raw, candidate_id)
    _parse_frame_index(root, frame_index_path, frame_paths, panel_paths)
    full_transcript_paths: list[Path] = []
    raw_full_paths = raw.get("full_transcript_paths") or {}
    if isinstance(raw_full_paths, dict):
        for value in raw_full_paths.values():
            _append_unique(full_transcript_paths, _resolve_path(root, value))

    render_status = str(raw.get("render_status") or "rendered")

    candidate = EvidenceCandidate(
        item_id=candidate_id,
        item_type="candidate" if render_status == "rendered" else "unrendered-candidate",
        title=str(raw.get("suggested_issue_title") or raw.get("title") or candidate_id),
        source_filename=str(raw.get("source_filename") or raw.get("source_path") or ""),
        timestamp_start=_coerce_timestamp(raw, "timestamp_start", "start_timestamp"),
        timestamp_end=_coerce_timestamp(raw, "timestamp_end", "end_timestamp"),
        marker_timestamp=_coerce_timestamp(raw, "marker_timestamp", "marker"),
        confidence=str(raw.get("confidence") or ""),
        repo_hint=str(raw.get("likely_target_repo") or repo_row.get("likely_target_repo") or "UNKNOWN"),
        repo_confidence=str(raw.get("repo_confidence") or repo_row.get("repo_confidence") or "unknown"),
        requires_github_review=_coerce_bool(raw.get("requires_github_review"), True),
        transcript_excerpt=str(raw.get("transcript_excerpt") or ""),
        transcript_window_text=_read_text(transcript_window_path, warnings),
        narration_context_text=_read_text(narration_context_path, warnings),
        render_status=render_status,
        evidence_folder=evidence_folder,
        transcript_window_path=transcript_window_path,
        narration_context_path=narration_context_path,
        narration_context_json_path=narration_context_json_path,
        ticket_markdown_path=ticket_markdown_path,
        metadata_path=metadata_path,
        frame_index_path=frame_index_path,
        frame_paths=frame_paths,
        panel_crop_paths=panel_paths,
        audio_paths=audio_paths,
        full_transcript_paths=full_transcript_paths,
        raw=dict(raw),
    )
    candidate.evidence_files = _build_evidence_files(candidate)
    return candidate


def _parse_review_item(root: Path, raw: dict[str, Any], warnings: list[str]) -> EvidenceCandidate:
    review_id = str(raw.get("review_id") or raw.get("id") or "review-needed")
    transcript_window_path = _resolve_path(root, raw.get("transcript_window_path"))
    item = EvidenceCandidate(
        item_id=review_id,
        item_type="review-needed",
        title=str(raw.get("title") or raw.get("reason") or review_id),
        source_filename=str(raw.get("source_filename") or raw.get("source_path") or ""),
        timestamp_start=_coerce_timestamp(raw, "timestamp_start", "start_timestamp"),
        timestamp_end=_coerce_timestamp(raw, "timestamp_end", "end_timestamp"),
        marker_timestamp=_coerce_timestamp(raw, "marker_timestamp", "marker"),
        confidence=str(raw.get("confidence") or "review-needed"),
        repo_hint=str(raw.get("likely_target_repo") or "UNKNOWN"),
        repo_confidence=str(raw.get("repo_confidence") or "unknown"),
        requires_github_review=_coerce_bool(raw.get("requires_github_review"), True),
        transcript_excerpt=str(raw.get("transcript_excerpt") or ""),
        transcript_window_text=_read_text(transcript_window_path, warnings),
        reason=str(raw.get("reason") or ""),
        transcript_window_path=transcript_window_path,
        raw=dict(raw),
    )
    item.evidence_files = _build_evidence_files(item)
    return item


def _parse_session_mention(root: Path, raw: dict[str, Any]) -> SessionMention:
    full_transcript_paths: list[Path] = []
    raw_full_paths = raw.get("full_transcript_paths") or {}
    if isinstance(raw_full_paths, dict):
        for value in raw_full_paths.values():
            _append_unique(full_transcript_paths, _resolve_path(root, value))
    try:
        seconds = float(raw.get("timestamp_seconds") or 0)
    except (TypeError, ValueError):
        seconds = 0.0
    return SessionMention(
        mention_id=str(raw.get("mention_id") or "mention"),
        record_type=str(raw.get("record_type") or "ticket_mention"),
        source_filename=str(raw.get("source_filename") or raw.get("source_id") or ""),
        timestamp=str(raw.get("timestamp") or ""),
        timestamp_seconds=seconds,
        excerpt=str(raw.get("excerpt") or ""),
        confidence=str(raw.get("confidence") or ""),
        render_status=str(raw.get("render_status") or ""),
        repo_hint=str(raw.get("repo_hint") or "UNKNOWN"),
        frame_available=bool(raw.get("frame_available")),
        audio_available=bool(raw.get("audio_available")),
        related_mention_ids=[str(value) for value in raw.get("possible_related_mention_ids") or []],
        narration_context_path=_resolve_path(root, raw.get("narration_context_path")),
        full_transcript_paths=full_transcript_paths,
        warnings=[str(value) for value in raw.get("warnings") or []],
        raw=dict(raw),
    )


def _parse_session_relationship(raw: dict[str, Any]) -> SessionRelationship:
    return SessionRelationship(
        mention_a=str(raw.get("mention_a") or ""),
        mention_b=str(raw.get("mention_b") or ""),
        classification=str(raw.get("classification") or "unresolved"),
        reasons=[str(value) for value in raw.get("reasons") or []],
        shared_terms=[str(value) for value in raw.get("distinctive_shared_terms") or []],
        intervening_boundary=bool(raw.get("intervening_new_ticket_boundary")),
        raw=dict(raw),
    )


def _parse_session_thread(raw: dict[str, Any]) -> SessionThread:
    return SessionThread(
        thread_hint_id=str(raw.get("thread_hint_id") or "thread-hint"),
        mention_ids=[str(value) for value in raw.get("mention_ids") or []],
        classification=str(raw.get("classification") or "unresolved"),
        reasons=[str(value) for value in raw.get("reasons") or []],
        raw=dict(raw),
    )


def resolve_evidence_package_root(path: str | Path) -> Path:
    root = Path(path)
    if root.name.lower() == "codex-evidence-package":
        return root
    child = root / "codex-evidence-package"
    if child.exists():
        return child
    return root


def _raw_items(
    candidate_payload: dict[str, Any],
    review_needed_payload: dict[str, Any],
    manifest: dict[str, Any],
    all_candidates_payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """The candidate, unrendered-candidate and review-needed records, wherever the package keeps them."""

    raw_candidates = [dict(item) for item in candidate_payload.get("candidates") or [] if isinstance(item, dict)]
    raw_unrendered = candidate_payload.get("unrendered_candidates") or []
    if not raw_unrendered and all_candidates_payload:
        raw_unrendered = [
            item
            for item in (all_candidates_payload.get("candidates") or [])
            if isinstance(item, dict) and item.get("render_status") == "unrendered"
        ]
    raw_review_needed = (
        review_needed_payload.get("review_needed")
        or candidate_payload.get("review_needed")
        or manifest.get("review_needed")
        or []
    )
    return (
        raw_candidates,
        [dict(item) for item in raw_unrendered if isinstance(item, dict)],
        [dict(item) for item in raw_review_needed if isinstance(item, dict)],
    )


def read_session_mentions(path: str | Path) -> list[SessionMention]:
    """125 (Wave 8): only the Session timeline's records, for the player's moments; nothing else is read."""

    root = resolve_evidence_package_root(path)
    payload = _read_optional_json(root / "SESSION_TIMELINE.json")
    return [_parse_session_mention(root, dict(item)) for item in payload.get("records") or [] if isinstance(item, dict)]


def read_item_records(path: str | Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """125 (Wave 8): the raw candidate and review-needed records of a package made before the Session
    timeline, for the player's moments. Only the JSON files are read, no evidence item's own files."""

    root = resolve_evidence_package_root(path)
    candidates, unrendered, review_needed = _raw_items(
        _read_optional_json(root / "CANDIDATE_TICKETS.json"),
        _read_optional_json(root / "REVIEW_NEEDED.json"),
        _read_optional_json(root / "manifest.json"),
        _read_optional_json(root / "ALL_CANDIDATES.json"),
    )
    return [*candidates, *unrendered], review_needed


def load_evidence_package(path: str | Path) -> EvidencePackage:
    root = resolve_evidence_package_root(path)
    warnings: list[str] = []
    manifest = _read_json(root / "manifest.json", warnings, optional=True)
    candidate_payload = _read_json(root / "CANDIDATE_TICKETS.json", warnings, optional=True)
    review_needed_payload = _read_json(root / "REVIEW_NEEDED.json", warnings, optional=True)
    repo_routing_payload = _read_json(root / "REPO_ROUTING_HINTS.json", warnings, optional=True)
    all_candidates_path = root / "ALL_CANDIDATES.json"
    all_candidates_payload = _read_json(all_candidates_path, warnings, optional=True) if all_candidates_path.exists() else {}
    session_timeline_payload = _read_optional_json(root / "SESSION_TIMELINE.json")
    ticket_thread_hints_payload = _read_optional_json(root / "TICKET_THREAD_HINTS.json")
    unassigned_mentions_payload = _read_optional_json(root / "UNASSIGNED_MENTIONS.json")
    mentioned_not_asked_payload = _read_optional_json(root / "MENTIONED_NOT_ASKED.json")
    package_status = _read_optional_json(root / "PACKAGE_STATUS.json")
    if not manifest.get("artifact_integrity"):
        warnings.append(
            "Legacy package: no v0.9.3 artifact-integrity attestation is available; paths and counts were not revalidated."
        )
    if (root / "ticket-agent-handoff.zip").exists() and not manifest.get("portable_privacy"):
        warnings.append(
            "Legacy package: the portable ZIP has no v0.9.3 fail-closed privacy attestation."
        )

    repo_rows = _candidate_repo_rows(repo_routing_payload)
    raw_candidates, raw_unrendered_candidates, raw_review_needed = _raw_items(
        candidate_payload, review_needed_payload, manifest, all_candidates_payload
    )
    candidates = [
        _parse_candidate(root, dict(candidate), repo_rows, warnings)
        for candidate in raw_candidates
        if isinstance(candidate, dict)
    ]
    rendered_ids = {candidate.item_id for candidate in candidates}
    unrendered_candidates = [
        _parse_candidate(root, dict(candidate), repo_rows, warnings)
        for candidate in raw_unrendered_candidates
        if isinstance(candidate, dict)
        and str(candidate.get("evidence_id") or candidate.get("candidate_id") or "") not in rendered_ids
    ]
    review_needed = [
        _parse_review_item(root, dict(item), warnings)
        for item in raw_review_needed
        if isinstance(item, dict)
    ]
    session_mentions = [
        _parse_session_mention(root, dict(item))
        for item in session_timeline_payload.get("records") or []
        if isinstance(item, dict)
    ]
    session_relationships = [
        _parse_session_relationship(dict(item))
        for item in ticket_thread_hints_payload.get("relationships") or []
        if isinstance(item, dict)
    ]
    proposed_threads = [
        _parse_session_thread(dict(item))
        for item in ticket_thread_hints_payload.get("proposed_threads") or []
        if isinstance(item, dict)
    ]
    unassigned_mention_ids = [
        str(item.get("mention_id"))
        for item in unassigned_mentions_payload.get("mentions") or []
        if isinstance(item, dict) and item.get("mention_id")
    ]
    start_here_path = root / "START_HERE_FOR_TICKET_AGENT.md"
    codex_prompt_path = root / "operator-drafts" / "session.codex.md"
    claude_prompt_path = root / "operator-drafts" / "session.claude.md"
    portable_zip_path = root / "ticket-agent-handoff.zip"
    return EvidencePackage(
        root=root,
        manifest=manifest,
        candidate_payload=candidate_payload,
        review_needed_payload=review_needed_payload,
        repo_routing_payload=repo_routing_payload,
        all_candidates_payload=all_candidates_payload,
        session_timeline_payload=session_timeline_payload,
        ticket_thread_hints_payload=ticket_thread_hints_payload,
        unassigned_mentions_payload=unassigned_mentions_payload,
        package_status=package_status,
        candidates=candidates,
        unrendered_candidates=unrendered_candidates,
        review_needed=review_needed,
        session_mentions=session_mentions,
        session_relationships=session_relationships,
        proposed_threads=proposed_threads,
        unassigned_mention_ids=unassigned_mention_ids,
        mentioned_not_asked=[
            dict(item) for item in mentioned_not_asked_payload.get("items") or [] if isinstance(item, dict)
        ],
        start_here_path=start_here_path if start_here_path.exists() else None,
        session_codex_prompt_path=codex_prompt_path if codex_prompt_path.exists() else None,
        session_claude_prompt_path=claude_prompt_path if claude_prompt_path.exists() else None,
        portable_zip_path=portable_zip_path if portable_zip_path.exists() else None,
        warnings=warnings,
    )
