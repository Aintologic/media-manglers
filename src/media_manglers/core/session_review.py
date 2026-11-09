"""Deterministic complete-session review artifacts for evidence packages."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from pathlib import PureWindowsPath
import re
from typing import Any, Iterable
import zipfile

from .zip_writer import list_files, local_io_path, write_zip


SESSION_REVIEW_SCHEMA_VERSION = 1
PORTABLE_ZIP_FILENAME = "ticket-agent-handoff.zip"

GENERIC_TOPIC_TERMS = {
    "about",
    "after",
    "again",
    "also",
    "another",
    "because",
    "before",
    "being",
    "between",
    "broken",
    "could",
    "dashboard",
    "does",
    "doing",
    "done",
    "during",
    "feature",
    "fixed",
    "generate",
    "generated",
    "getting",
    "from",
    "going",
    "have",
    "here",
    "issue",
    "just",
    "like",
    "make",
    "maybe",
    "needs",
    "problem",
    "requested",
    "review",
    "really",
    "same",
    "should",
    "something",
    "still",
    "that",
    "their",
    "there",
    "these",
    "thing",
    "this",
    "ticket",
    "tickets",
    "video",
    "window",
    "want",
    "when",
    "where",
    "which",
    "while",
    "with",
    "would",
}

MEDIA_EXTENSIONS = {
    ".aac",
    ".avi",
    ".bmp",
    ".flac",
    ".gif",
    ".jpeg",
    ".jpg",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".png",
    ".wav",
    ".webm",
    ".webp",
}

TEXT_EXTENSIONS = {".csv", ".json", ".jsonl", ".md", ".srt", ".txt"}

ROOT_PRIORITY = (
    "START_HERE_FOR_TICKET_AGENT.md",
    "AGENT_REVIEW_MANIFEST.json",
    "PACKAGE_STATUS.json",
    "CONSOLIDATED_OUTCOMES.json",
    "EVIDENCE_INTEGRITY_REPORT.md",
    "EVIDENCE_INTEGRITY_REPORT.json",
    "PORTABLE_PRIVACY_REPORT.json",
    "SESSION_TIMELINE.md",
    "SESSION_TIMELINE.json",
    "TICKET_THREAD_HINTS.md",
    "TICKET_THREAD_HINTS.json",
    "UNASSIGNED_MENTIONS.md",
    "UNASSIGNED_MENTIONS.json",
    "ALL_CANDIDATES.md",
    "ALL_CANDIDATES.json",
    "EVIDENCE_QUALITY_REPORT.md",
    "TRANSCRIPT_CORRECTIONS.md",
    "TRANSCRIPT_CORRECTIONS.json",
    "MARKER_AUDIT.md",
    "MARKER_AUDIT.json",
    "CANDIDATE_TICKETS.md",
    "CANDIDATE_TICKETS.json",
    "README_FOR_AI.md",
    "REPO_ROUTING_HINTS.md",
    "REPO_ROUTING_HINTS.json",
    "OMITTED_MEDIA.md",
    "OMITTED_MEDIA.json",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _text_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _narration_text(candidate: dict[str, Any]) -> str:
    entries = (candidate.get("narration_context") or {}).get("entries") or []
    return " ".join(
        _safe_text(entry.get("text"))
        for entry in entries
        if isinstance(entry, dict) and entry.get("kind") == "speech"
    )


def distinctive_topic_terms(candidate: dict[str, Any]) -> list[str]:
    """Return explainable non-generic terms used for cross-session hints."""

    text = " ".join(
        value
        for value in (
            _safe_text(candidate.get("suggested_issue_title")),
            _safe_text(candidate.get("transcript_excerpt")),
            _narration_text(candidate),
        )
        if value
    ).lower()
    terms: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[a-z][a-z0-9_-]{3,}", text):
        normalized = token.strip("_-")
        if not normalized or normalized in GENERIC_TOPIC_TERMS or normalized in seen:
            continue
        if normalized.isdigit():
            continue
        terms.append(normalized)
        seen.add(normalized)
    return terms[:30]


def requested_outcome_terms(candidate: dict[str, Any]) -> list[str]:
    title = _safe_text(candidate.get("suggested_issue_title")).lower()
    terms: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[a-z][a-z0-9_-]{3,}", title):
        normalized = token.strip("_-")
        if not normalized or normalized in GENERIC_TOPIC_TERMS or normalized in seen:
            continue
        terms.append(normalized)
        seen.add(normalized)
    return terms[:20]


def _frame_audio_status(candidate: dict[str, Any]) -> tuple[bool, bool, list[str]]:
    failures: list[str] = []
    frames = list(candidate.get("frames") or [])
    frame_available = False
    for frame in frames:
        status = _safe_text(frame.get("status")).lower()
        if status in {"created", "complete", "completed", "ok", "success"}:
            frame_available = True
        elif status in {"failed", "error"}:
            failures.append(_safe_text(frame.get("error_message")) or "frame rendering failed")
    audio = dict(candidate.get("audio_snippet") or {})
    audio_status = _safe_text(audio.get("status")).lower()
    audio_available = audio_status in {"created", "complete", "completed", "ok", "success"}
    if audio_status in {"failed", "error"}:
        failures.append(_safe_text(audio.get("error_message")) or "audio rendering failed")
    return frame_available, audio_available, failures


def _timeline_record_defaults(record_type: str, mention_id: str) -> dict[str, Any]:
    return {
        "record_type": record_type,
        "mention_id": mention_id,
        "source_id": "",
        "source_filename": "",
        "timestamp_seconds": 0.0,
        "timestamp": "",
        "focused_start_seconds": 0.0,
        "focused_end_seconds": 0.0,
        "marker_phrase": "",
        "marker_phrases": [],
        "confidence": "unknown",
        "excerpt": "",
        "ticket_path": "",
        "transcript_window_path": "",
        "narration_context_path": "",
        "narration_context_json_path": "",
        "full_transcript_paths": {},
        "render_status": "not-rendered",
        "render_skip_reason": "",
        "frame_available": False,
        "audio_available": False,
        "rendering_failures": [],
        "repo_hint": "UNKNOWN",
        "repo_confidence": "unknown",
        "distinctive_topic_terms": [],
        "requested_outcome_terms": [],
        "continuation_phrases": [],
        "split_phrases": [],
        "new_ticket_phrases": [],
        "closing_phrases": [],
        "narration_boundary_type": "",
        "narration_warning": "",
        "possible_related_mention_ids": [],
        "candidate_ids": [],
        "warnings": [],
        "transcript_quality_status": "unknown",
    }


def _candidate_record(candidate: dict[str, Any]) -> dict[str, Any]:
    narration = dict(candidate.get("narration_context") or {})
    frame_available, audio_available, failures = _frame_audio_status(candidate)
    full_paths = dict(candidate.get("full_transcript_paths") or narration.get("full_transcript_paths") or {})
    marker_phrases = list(candidate.get("detected_marker_phrases") or [])
    split_phrases = list(narration.get("new_ticket_phrases") or [])
    transcript_quality = dict(candidate.get("source_transcript_quality") or {})
    record = _timeline_record_defaults("ticket_mention", _safe_text(candidate.get("evidence_id")))
    record.update({
        "source_id": _safe_text(candidate.get("source_id")),
        "source_filename": _safe_text(candidate.get("source_filename")),
        "timestamp_seconds": _as_float(candidate.get("marker_timestamp_seconds")),
        "timestamp": _safe_text(candidate.get("marker_timestamp")),
        "focused_start_seconds": _as_float(candidate.get("timestamp_start_seconds")),
        "focused_end_seconds": _as_float(candidate.get("timestamp_end_seconds")),
        "marker_phrase": _safe_text(marker_phrases[0]) if marker_phrases else "",
        "marker_phrases": marker_phrases,
        "confidence": _safe_text(candidate.get("confidence")),
        "excerpt": _safe_text(candidate.get("transcript_excerpt")),
        "ticket_path": _safe_text(candidate.get("ticket_path")),
        "transcript_window_path": _safe_text(candidate.get("transcript_window_path")),
        "narration_context_path": _safe_text(candidate.get("narration_context_path")),
        "narration_context_json_path": _safe_text(candidate.get("narration_context_json_path")),
        "full_transcript_paths": full_paths,
        "render_status": _safe_text(candidate.get("render_status")) or "rendered",
        "render_skip_reason": _safe_text(candidate.get("render_skip_reason")),
        "frame_available": frame_available,
        "audio_available": audio_available,
        "rendering_failures": failures,
        "repo_hint": _safe_text(candidate.get("likely_target_repo")) or "UNKNOWN",
        "repo_confidence": _safe_text(candidate.get("repo_confidence")) or "unknown",
        "distinctive_topic_terms": distinctive_topic_terms(candidate),
        "requested_outcome_terms": requested_outcome_terms(candidate),
        "continuation_phrases": list(narration.get("continuation_phrases") or []),
        "split_phrases": split_phrases,
        "new_ticket_phrases": split_phrases,
        "closing_phrases": list(narration.get("closing_phrases") or []),
        "narration_boundary_type": _safe_text(candidate.get("narration_context_boundary_type")),
        "narration_warning": _safe_text(candidate.get("narration_context_warning")),
        "possible_related_mention_ids": [],
        "transcript_quality_status": _safe_text(transcript_quality.get("quality_status")) or "unknown",
        "warnings": [
            warning
            for warning in (
                _safe_text(candidate.get("narration_context_warning")),
                _safe_text(candidate.get("render_skip_reason")),
                *[_safe_text(value) for value in transcript_quality.get("warning_reasons") or []],
                *failures,
            )
            if warning
        ],
    })
    return record


def _review_record(item: dict[str, Any]) -> dict[str, Any]:
    transcript_quality = dict(item.get("source_transcript_quality") or {})
    record = _timeline_record_defaults("review_needed", _safe_text(item.get("review_id")))
    record.update({
        "source_id": _safe_text(item.get("source_id")),
        "source_filename": _safe_text(item.get("source_filename")),
        "timestamp_seconds": _as_float(
            item.get("marker_timestamp_seconds"),
            _as_float(item.get("timestamp_start_seconds")),
        ),
        "timestamp": _safe_text(item.get("marker_timestamp") or item.get("timestamp_start")),
        "marker_phrases": [],
        "confidence": _safe_text(item.get("confidence")) or "review-needed",
        "excerpt": _safe_text(item.get("transcript_excerpt")),
        "render_status": "review-needed",
        "frame_available": False,
        "audio_available": False,
        "repo_hint": _safe_text(item.get("likely_target_repo")) or "UNKNOWN",
        "distinctive_topic_terms": distinctive_topic_terms(
            {
                "suggested_issue_title": item.get("reason"),
                "transcript_excerpt": item.get("transcript_excerpt"),
            }
        ),
        "possible_related_mention_ids": [],
        "promotion_status": _safe_text(item.get("promotion_status")) or "unresolved_review_group",
        "grouped_occurrence_count": int(item.get("grouped_occurrence_count") or 1),
        "transcript_quality_status": _safe_text(transcript_quality.get("quality_status")) or "unknown",
        "warnings": [
            value
            for value in (
                _safe_text(item.get("reason")) or "Operator review is required for this timeline item.",
                *[_safe_text(reason) for reason in transcript_quality.get("warning_reasons") or []],
            )
            if value
        ],
    })
    return record


def _marker_record(hit: dict[str, Any], index: int) -> dict[str, Any]:
    marker_phrase = _safe_text(hit.get("marker_phrase"))
    excerpt = _safe_text(hit.get("surrounding_transcript_snippet"))
    record = _timeline_record_defaults("explicit_marker", f"marker-{index:04d}")
    record.update({
        "source_id": _safe_text(hit.get("source_id")),
        "source_filename": _safe_text(hit.get("source_filename")),
        "timestamp_seconds": _as_float(hit.get("timestamp_seconds")),
        "timestamp": _safe_text(hit.get("timestamp")),
        "marker_phrase": marker_phrase,
        "marker_phrases": [marker_phrase] if marker_phrase else [],
        "confidence": "explicit-marker",
        "excerpt": excerpt,
        "render_status": _safe_text(hit.get("status")) or "marker-only",
        "repo_hint": _safe_text(hit.get("likely_target_repo")) or "UNKNOWN",
        "distinctive_topic_terms": distinctive_topic_terms(
            {
                "suggested_issue_title": marker_phrase,
                "transcript_excerpt": excerpt,
            }
        ),
        "candidate_ids": list(hit.get("candidate_ids") or []),
        "warnings": [_safe_text(hit.get("reason"))] if _safe_text(hit.get("reason")) else [],
    })
    return record


def _repo_compatible(a: dict[str, Any], b: dict[str, Any]) -> tuple[bool, str]:
    repo_a = _safe_text(a.get("repo_hint")) or "UNKNOWN"
    repo_b = _safe_text(b.get("repo_hint")) or "UNKNOWN"
    if repo_a == "UNKNOWN" or repo_b == "UNKNOWN":
        return True, "At least one repo hint is unknown."
    if repo_a == repo_b:
        return True, f"Both mentions suggest repository {repo_a}."
    return False, f"Repo hints conflict: {repo_a} vs {repo_b}."


def _has_intervening_boundary(mentions: list[dict[str, Any]], left_index: int, right_index: int) -> bool:
    right = mentions[right_index]
    right_markers = " ".join(right.get("marker_phrases") or []).lower()
    if any(phrase in right_markers for phrase in ("new ticket", "another ticket", "separate ticket", "next ticket")):
        return True
    return any(
        mentions[index].get("new_ticket_phrases")
        or mentions[index].get("narration_boundary_type") in {"new_ticket", "next_explicit_ticket_marker"}
        for index in range(left_index, right_index)
    )


def _relationship_record(
    mentions: list[dict[str, Any]],
    left_index: int,
    right_index: int,
    explicit_target: str | None,
) -> dict[str, Any]:
    a = mentions[left_index]
    b = mentions[right_index]
    shared_terms = sorted(set(a.get("distinctive_topic_terms") or []) & set(b.get("distinctive_topic_terms") or []))
    shared_outcome_terms = sorted(
        set(a.get("requested_outcome_terms") or [])
        & set(b.get("requested_outcome_terms") or [])
    )
    repo_compatible, repo_reason = _repo_compatible(a, b)
    repo_a = _safe_text(a.get("repo_hint")) or "UNKNOWN"
    repo_b = _safe_text(b.get("repo_hint")) or "UNKNOWN"
    confirmed_repo_match = repo_a != "UNKNOWN" and repo_a == repo_b
    intervening_boundary = _has_intervening_boundary(mentions, left_index, right_index)
    reasons: list[str] = []
    classification = "unresolved"
    score = 0

    if explicit_target == a.get("mention_id"):
        classification = "explicit link"
        score = 100
        reasons.append(
            "The later mention contains explicit continuation language: "
            + ", ".join(b.get("continuation_phrases") or ["same/previous ticket"])
            + "."
        )
    elif intervening_boundary:
        score = -100
        reasons.append("An explicit new-ticket boundary blocks an automatic relationship.")
    elif not repo_compatible:
        score = -10
        reasons.append(repo_reason)
    else:
        score += min(3, len(shared_terms))
        score += len(shared_outcome_terms) * 3
        if confirmed_repo_match:
            score += 2
            reasons.append(repo_reason)
        elif repo_a == "UNKNOWN" or repo_b == "UNKNOWN":
            reasons.append("UNKNOWN repository hints contribute zero relationship points.")
        if shared_outcome_terms:
            reasons.append("The requested outcomes share distinctive terms.")
        if shared_terms:
            reasons.append("The mentions share non-generic topic terms.")
        if score >= 6 and (len(shared_outcome_terms) >= 2 or confirmed_repo_match):
            classification = "strong possible relation"
        elif score >= 2:
            classification = "weak possible relation"
        else:
            reasons.append("No explicit link or meaningful shared requested outcome was found.")

    if intervening_boundary:
        reasons.append("An explicit new-ticket boundary appears between or at the later mention.")
        if classification != "explicit link":
            classification = "unresolved"

    return {
        "mention_a": a.get("mention_id"),
        "mention_b": b.get("mention_id"),
        "timestamp_a": a.get("timestamp"),
        "timestamp_b": b.get("timestamp"),
        "timestamp_seconds_a": a.get("timestamp_seconds"),
        "timestamp_seconds_b": b.get("timestamp_seconds"),
        "classification": classification,
        "reasons": reasons,
        "distinctive_shared_terms": shared_terms,
        "shared_requested_outcome_terms": shared_outcome_terms,
        "relationship_score": score,
        "confirmed_repo_match": confirmed_repo_match,
        "intervening_new_ticket_boundary": intervening_boundary,
        "agent_review_required": True,
        "warning": (
            "Relationship hint only. Codex, Claude, or the operator must decide whether these mentions describe one ticket."
        ),
    }


def _thread_hints(mentions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not mentions:
        return [], []
    ordered = sorted(
        mentions,
        key=lambda item: (
            _safe_text(item.get("source_filename")),
            _as_float(item.get("timestamp_seconds")),
            _safe_text(item.get("mention_id")),
        ),
    )
    explicit_targets: dict[str, str] = {}
    for index, mention in enumerate(ordered):
        if index and mention.get("continuation_phrases"):
            mention_terms = set(mention.get("distinctive_topic_terms") or [])
            outcome_terms = set(mention.get("requested_outcome_terms") or [])
            ranked_prior = sorted(
                ordered[:index],
                key=lambda prior: (
                    len(outcome_terms & set(prior.get("requested_outcome_terms") or [])),
                    len(mention_terms & set(prior.get("distinctive_topic_terms") or [])),
                    _safe_text(prior.get("source_filename")) == _safe_text(mention.get("source_filename")),
                    _as_float(prior.get("timestamp_seconds")),
                ),
                reverse=True,
            )
            explicit_targets[_safe_text(mention.get("mention_id"))] = _safe_text(
                ranked_prior[0].get("mention_id")
            )

    relationships: list[dict[str, Any]] = []
    unresolved_by_mention: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for left_index in range(len(ordered)):
        for right_index in range(left_index + 1, len(ordered)):
            right_id = _safe_text(ordered[right_index].get("mention_id"))
            relation = _relationship_record(
                ordered,
                left_index,
                right_index,
                explicit_targets.get(right_id),
            )
            if relation["classification"] == "unresolved":
                unresolved_by_mention[_safe_text(relation["mention_a"])].append(relation)
                unresolved_by_mention[_safe_text(relation["mention_b"])].append(relation)
            else:
                relationships.append(relation)

    represented_unresolved: set[tuple[str, str]] = set()
    for mention in ordered:
        mention_id = _safe_text(mention.get("mention_id"))
        candidates = sorted(
            unresolved_by_mention.get(mention_id, []),
            key=lambda relation: abs(
                _as_float(relation.get("timestamp_seconds_b"))
                - _as_float(relation.get("timestamp_seconds_a"))
            ),
        )
        if candidates:
            relation = candidates[0]
            key = tuple(sorted((_safe_text(relation["mention_a"]), _safe_text(relation["mention_b"]))))
            if key not in represented_unresolved:
                relationships.append(relation)
                represented_unresolved.add(key)

    relationships.sort(
        key=lambda item: (
            _as_float(item.get("timestamp_seconds_a")),
            _as_float(item.get("timestamp_seconds_b")),
            _safe_text(item.get("mention_a")),
        )
    )

    strong_relations = [
        relation
        for relation in relationships
        if relation["classification"] in {"explicit link", "strong possible relation"}
    ]
    strong_pairs = {
        frozenset((_safe_text(relation["mention_a"]), _safe_text(relation["mention_b"])))
        for relation in strong_relations
    }
    groups: list[set[str]] = []
    for relation in strong_relations:
        left = _safe_text(relation["mention_a"])
        right = _safe_text(relation["mention_b"])
        placed = False
        for group in groups:
            existing = left if left in group else (right if right in group else "")
            candidate = right if existing == left else left
            if existing and all(frozenset((candidate, member)) in strong_pairs for member in group):
                group.add(candidate)
                placed = True
                break
        if not placed:
            groups.append({left, right})

    proposed_threads: list[dict[str, Any]] = []
    for index, mention_ids in enumerate(
        sorted((sorted(ids) for ids in groups if len(ids) > 1), key=lambda ids: ids[0]),
        start=1,
    ):
        related = [
            relation
            for relation in relationships
            if relation["mention_a"] in mention_ids
            and relation["mention_b"] in mention_ids
            and relation["classification"] in {"explicit link", "strong possible relation"}
        ]
        proposed_threads.append(
            {
                "thread_hint_id": f"thread-hint-{index:03d}",
                "mention_ids": mention_ids,
                "classification": (
                    "explicit link"
                    if any(item["classification"] == "explicit link" for item in related)
                    else "strong possible relation"
                ),
                "reasons": sorted({reason for item in related for reason in item.get("reasons") or []}),
                "agent_review_required": True,
                "warning": "This is a proposed grouping, not a final ticket decision.",
            }
        )

    related_ids: dict[str, set[str]] = defaultdict(set)
    for relation in relationships:
        if relation["classification"] == "unresolved":
            continue
        a = _safe_text(relation["mention_a"])
        b = _safe_text(relation["mention_b"])
        related_ids[a].add(b)
        related_ids[b].add(a)
    for mention in ordered:
        mention["possible_related_mention_ids"] = sorted(related_ids[_safe_text(mention.get("mention_id"))])

    return relationships, proposed_threads


def build_session_review(
    *,
    candidates: Iterable[dict[str, Any]],
    review_needed: Iterable[dict[str, Any]],
    marker_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mentions = [_candidate_record(dict(candidate)) for candidate in candidates]
    relationships, proposed_threads = _thread_hints(mentions)
    threaded_ids = {
        mention_id
        for thread in proposed_threads
        for mention_id in thread.get("mention_ids") or []
    }
    review_records = [_review_record(dict(item)) for item in review_needed]
    unassigned = [mention for mention in mentions if mention.get("mention_id") not in threaded_ids]
    unassigned.extend(
        record
        for record in review_records
        if record.get("promotion_status") == "unassigned_ticket_mention"
    )
    marker_records = [
        _marker_record(dict(hit), index)
        for index, hit in enumerate((marker_audit or {}).get("markers") or [], start=1)
    ]
    timeline = sorted(
        [*mentions, *review_records, *marker_records],
        key=lambda item: (
            _safe_text(item.get("source_filename")),
            _as_float(item.get("timestamp_seconds")),
            {"explicit_marker": 0, "ticket_mention": 1, "review_needed": 2}.get(
                _safe_text(item.get("record_type")), 9
            ),
            _safe_text(item.get("mention_id")),
        ),
    )
    rendering_failure_count = sum(
        1 for mention in mentions if mention.get("rendering_failures")
    )
    return {
        "schema_version": SESSION_REVIEW_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "warning": (
            "Relationship hints are suggestions. Codex, Claude, or the operator must decide whether mentions belong to the same ticket."
        ),
        "summary": {
            "mention_count": len(mentions),
            "rendered_mention_count": sum(
                1 for mention in mentions if mention.get("render_status") == "rendered"
            ),
            "lightweight_mention_count": sum(
                1 for mention in mentions if mention.get("render_status") != "rendered"
            ),
            "review_needed_count": len(review_records),
            "explicit_marker_count": len(marker_records),
            "relationship_hint_count": len(relationships),
            "proposed_thread_count": len(proposed_threads),
            "unassigned_mention_count": len(unassigned),
            "rendering_failure_count": rendering_failure_count,
            "transcript_warning_record_count": sum(
                1
                for mention in [*mentions, *review_records]
                if mention.get("transcript_quality_status") not in {"", "unknown", "usable"}
            ),
        },
        "mentions": mentions,
        "timeline": timeline,
        "relationships": relationships,
        "proposed_threads": proposed_threads,
        "unassigned_mentions": unassigned,
    }


def _start_here_markdown(
    session: dict[str, Any], outcomes: list[dict[str, Any]] | None = None
) -> str:
    summary = session["summary"]
    outcome_count = len(outcomes or [])
    return f"""# Start Here For Ticket Agent

This is a complete-session evidence-preparation package. It contains {summary['mention_count']} detected mentions and {outcome_count} **PROVISIONAL EVIDENCE CLUSTERS**. These are not automatically approved GitHub tickets and are not final semantic decisions.

Read `CONSOLIDATED_OUTCOMES.json` for each provisional cluster's source mentions, timestamps, evidence roles, deterministic primary-choice reason, linked supporting or correction evidence, confidence and reasons, unresolved questions, and repository suggestion. Correct any imperfect summary from the linked source evidence before recommending ticket work.

## Required Review Procedure

This file is the only reading order for this package. The operator narrated
while driving; your job is to find every bug, fix or feature request they
described and draft one GitHub issue per requested change.

1. Read the full timestamped transcripts under `transcript/` end to end first. They are the source of truth.
2. The marker scan behind the candidate lists is a hint: it finds requests by phrases (a ticket word, or a hand-off such as "instructions for AI"), so it misses defects and requests described in plain words, and flags racing chatter. Do not create one ticket per marker automatically.
3. Compare mentions across all timestamps and source files.
4. Combine mentions only when they concern the same defect or requested action.
5. Keep separate requested actions as separate tickets.
6. Read ticket.md, transcript_window.md, narration_context.md, frames, panel crops, and audio where relevant.
7. Review EVIDENCE_QUALITY_REPORT.md and TRANSCRIPT_CORRECTIONS.md; compare transcript/raw when a correction affects meaning.
8. Treat driving pauses as expected and not as automatic ticket endings.
9. Search earlier and later transcript regions for additional details.
10. Check existing GitHub issues before proposing a new issue.
11. Propose an update to an existing issue rather than a duplicate where appropriate.
12. Cite source filenames and timestamps.
13. Report uncertainty where mention relationships are ambiguous.
14. `MENTIONED_NOT_ASKED.md` lists moments where the operator said a word like "ticket", "bug" or "fix this" without asking for anything. None of them is a request. Show that list with your drafted issues so the operator decides about each one; never draft or file an issue from it on your own.
15. Present the drafted issues to the operator and STOP. Create or update issues only after the operator approves them; then report what was created, what was updated, and what stayed unresolved.

Before any GitHub write, remove unrelated personal content and machine-local paths from the proposed ticket text. Evidence stays local unless the operator explicitly approves a specific attachment or excerpt for publication.

## Read In This Order

1. Full timestamped transcripts under `transcript/`
2. `NARRATION_EVIDENCE.md` (screenshots and a clip for every stretch of narration; the operator's projects are on-screen, so check the screens for every issue)
3. `SESSION_TIMELINE.md` (every flagged moment in time order)
4. `CONSOLIDATED_OUTCOMES.json`, `TICKET_THREAD_HINTS.md` and `UNASSIGNED_MENTIONS.md`
5. `MENTIONED_NOT_ASKED.md` (said in passing, not asked for: show it to the operator, never file from it)
6. `ALL_CANDIDATES.md` and the candidate evidence folders for frames and audio
7. `REPO_ROUTING_HINTS.md` and `EVIDENCE_QUALITY_REPORT.md`
8. `PACKAGE_STATUS.json` and `AGENT_REVIEW_MANIFEST.json` (machine-readable status only)

WARNING: {session['warning']}
"""


def _timeline_markdown(session: dict[str, Any]) -> str:
    lines = ["# Complete Session Timeline", "", session["warning"], ""]
    for item in session["timeline"]:
        lines.extend(
            [
                f"## {item.get('timestamp') or 'unknown'} - {item.get('mention_id')}",
                "",
                f"- Type: {item.get('record_type')}",
                f"- Source: {item.get('source_filename') or item.get('source_id') or 'unknown'}",
                f"- Marker phrase: {', '.join(item.get('marker_phrases') or []) or 'none'}",
                f"- Confidence: {item.get('confidence') or 'unknown'}",
                f"- Render status: {item.get('render_status') or 'unknown'}",
                f"- Frames available: {str(bool(item.get('frame_available'))).lower()}",
                f"- Audio available: {str(bool(item.get('audio_available'))).lower()}",
                f"- Repo hint: {item.get('repo_hint') or 'UNKNOWN'}",
                f"- Transcript quality: {item.get('transcript_quality_status') or 'unknown'}",
                f"- Promotion status: {item.get('promotion_status') or 'not applicable'}",
                f"- Distinctive terms: {', '.join(item.get('distinctive_topic_terms') or []) or 'none'}",
                f"- Possible related mentions: {', '.join(item.get('possible_related_mention_ids') or []) or 'none'}",
                f"- Narration context: {item.get('narration_context_path') or 'not applicable'}",
                f"- Warnings: {'; '.join(item.get('warnings') or []) or 'none'}",
                "",
                item.get("excerpt") or "(No excerpt available.)",
                "",
            ]
        )
    return "\n".join(lines)


def _thread_markdown(session: dict[str, Any]) -> str:
    lines = ["# Ticket Thread Hints", "", session["warning"], ""]
    if session["proposed_threads"]:
        lines.append("## Proposed Thread Groups")
        lines.append("")
        for thread in session["proposed_threads"]:
            lines.extend(
                [
                    f"### {thread['thread_hint_id']}",
                    "",
                    f"- Mentions: {', '.join(thread['mention_ids'])}",
                    f"- Classification: {thread['classification']}",
                    f"- Reasons: {'; '.join(thread['reasons'])}",
                    f"- Warning: {thread['warning']}",
                    "",
                ]
            )
    else:
        lines.extend(["No explicit or strong proposed thread groups were found.", ""])
    lines.extend(["## Pairwise Relationship Hints", ""])
    for relation in session["relationships"]:
        lines.extend(
            [
                f"### {relation['mention_a']} <-> {relation['mention_b']}",
                "",
                f"- Classification: {relation['classification']}",
                f"- Relationship score: {relation.get('relationship_score', 0)}",
                f"- Timestamps: {relation['timestamp_a']} / {relation['timestamp_b']}",
                f"- Shared terms: {', '.join(relation['distinctive_shared_terms']) or 'none'}",
                f"- Shared requested-outcome terms: {', '.join(relation.get('shared_requested_outcome_terms') or []) or 'none'}",
                f"- Confirmed repo match: {str(bool(relation.get('confirmed_repo_match'))).lower()}",
                f"- Intervening new-ticket boundary: {str(relation['intervening_new_ticket_boundary']).lower()}",
                f"- Reasons: {'; '.join(relation['reasons'])}",
                f"- Warning: {relation['warning']}",
                "",
            ]
        )
    return "\n".join(lines)


def _unassigned_markdown(session: dict[str, Any]) -> str:
    lines = ["# Unassigned Mentions", "", session["warning"], ""]
    if not session["unassigned_mentions"]:
        lines.append("Every mention participates in at least one explicit or strong proposed thread group.")
    for mention in session["unassigned_mentions"]:
        lines.extend(
            [
                f"## {mention.get('mention_id')} at {mention.get('timestamp') or 'unknown'}",
                "",
                f"- Source: {mention.get('source_filename') or 'unknown'}",
                f"- Repo hint: {mention.get('repo_hint') or 'UNKNOWN'}",
                f"- Distinctive terms: {', '.join(mention.get('distinctive_topic_terms') or []) or 'none'}",
                "",
                mention.get("excerpt") or "(No excerpt available.)",
                "",
            ]
        )
    return "\n".join(lines)


DETECTION_CAVEAT = """## How This Package Was Built (read this first)

The candidate list here was produced by a deterministic marker scan: it looks
for words such as "bug", "ticket", "issue", "wrong" and "broken" in the
transcript. That scan is a **hint, not the finding**. It is known to:

- miss defects the operator described in plain language without those words;
- promote non-software remarks (driving notes, setup talk) that happen to
  contain a marker word;
- emit titles that are raw transcript fragments.

Therefore: **do not treat the candidate list as the list of issues.** Read the
full transcripts end to end and decide for yourself what the operator actually
reported. Expect to find defects the scan missed, and expect to discard some it
flagged."""


OUTPUT_CONTRACT = """## What To Produce

Produce **draft GitHub issues**, not a narrative recommendation.

For each defect you are confident the operator reported, give:

1. **Repository** - one of the repositories listed above.
2. **Title** - written by you, in plain imperative English. Never a transcript
   fragment.
3. **Body** - what the operator observed, when (source file + timestamp), expected versus
   actual behaviour where they stated it, and any later clarification.
4. **Evidence** - the package-relative paths of the screenshots and the clip
   (from `NARRATION_EVIDENCE.md`) that show the problem; say which ones you
   propose to attach to the issue.
5. **Confidence** - and what would raise it.

Then:

- Search existing issues in the target repository and say, per draft, whether
  it is new or a comment on an existing issue (give the number).
- List separately anything you discarded from the candidate list, with why.
- List separately anything you found that the marker scan missed.
- List anything too ambiguous to file, with the question you need answered.

**Present all of this to the operator and stop. Do not create, edit or comment
on any GitHub issue until the operator approves the list.**

Before any public write, strip machine-local paths and unrelated personal
content. Do not upload evidence files unless the operator approves a specific
attachment."""


def _projects_section(projects: dict[str, Any] | None) -> str:
    if not projects:
        return (
            "## My Projects\n\n"
            "No operator repo map was available when this package was built, so every "
            "item is likely to say `UNKNOWN`. Ask the operator which repository each "
            "item belongs to before opening anything.\n"
        )
    lines = [
        "## My Projects",
        "",
        "These are the operator's repositories and the words used for each one while "
        "narrating. Route each proposed issue to one of these. If an item matches none "
        "of them, say so and ask rather than guessing.",
        "",
        "| Repository | Project | The operator might call it |",
        "|---|---|---|",
    ]
    for name, entry in projects.items():
        data = entry if isinstance(entry, dict) else {}
        label = str(data.get("project_label") or "").strip() or name
        keywords = data.get("keywords") or []
        if isinstance(keywords, str):
            keywords = [keywords]
        spoken = ", ".join(str(k) for k in list(keywords)[:14]) or "-"
        lines.append(f"| `{name}` | {label} | {spoken} |")
    lines.append("")
    return "\n".join(lines)


def _session_prompt(
    session: dict[str, Any],
    agent_name: str,
    outcomes: list[dict[str, Any]] | None = None,
    package_root: str = "",
    projects: dict[str, Any] | None = None,
) -> str:
    root_block = package_root or "(unknown - ask the operator where the package is)"
    return f"""# {agent_name}: find the operator's bug reports in this session

The operator recorded a sim-racing session and narrated aloud. Somewhere in that
narration they described defects in software they wrote. Find them all and draft the
GitHub issues.

## Package Location

The evidence package is on this machine at:

```
{root_block}
```

Follow `START_HERE_FOR_TICKET_AGENT.md`; it is the only reading order. In short:
read `transcript/full_transcript.md` end to end first, then use the session
timeline, `CONSOLIDATED_OUTCOMES.json`, the candidate transcript windows and
narration contexts to locate evidence. All paths are relative to the directory
above.

Two things to know about the evidence:

- The transcripts drop very low-confidence stretches to avoid text Whisper
  invents over engine noise. If a sentence seems cut short, check
  `filtered_segments` in `transcript/sources/*.transcript.raw.json` for that
  timestamp before concluding the operator said nothing. The same file lists, under
  `rescued_segments`, short lines the transcriber was unsure of that were kept
  only because they sit next to real narration; read those with more caution.
- `NARRATION_EVIDENCE.md` lists every stretch where the operator is talking with
  screenshots (full screen and each monitor) and a short video clip, whether or
  not the keyword scan flagged it. The operator's projects are on-screen overlays, so use
  it for every issue: find the moment whose time range contains the timestamp,
  look at the screenshots, and cite the ones that show the problem.
- Keyword-flagged moments also have frames under `artifacts/sources/<source-id>/`
  (see each `evidence_items/<id>/frame_index.csv`).

{DETECTION_CAVEAT}

The full transcripts are the source of truth. Work through them end to end.

{_projects_section(projects)}
## Session Summary (from the marker scan)

- Mentions flagged: {session['summary']['mention_count']}
- Provisional evidence clusters: {len(outcomes or [])}
- Proposed thread groups: {session['summary']['proposed_thread_count']}
- Unassigned mentions: {session['summary']['unassigned_mention_count']}
- Review-needed items: {session['summary']['review_needed_count']}

These counts describe the scan's output, not the number of real defects.

## Grouping

Do not create one issue per marker. Relationship hints, summaries, confidence
and repository suggestions are deterministic aids, not conclusions. Preserve
compound details through linked source mentions even when a summary is
incomplete. Combine mentions only when they concern the same defect or the same
requested change; keep genuinely separate actions separate. Cite the source
filename and timestamp for every claim.

{OUTPUT_CONTRACT}
"""


def write_session_review_artifacts(
    output_dir: Path,
    session: dict[str, Any],
    *,
    portable_mode: str = "Both",
    portable_zip_max_mb: int = 100,
    outcomes: list[dict[str, Any]] | None = None,
    integrity_report: dict[str, Any] | None = None,
    projects: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    outcomes = list(outcomes or [])
    integrity_report = dict(integrity_report or {})
    timeline_payload = {
        "schema_version": SESSION_REVIEW_SCHEMA_VERSION,
        "generated_at": session["generated_at"],
        "warning": session["warning"],
        "summary": session["summary"],
        "records": session["timeline"],
    }
    hints_payload = {
        "schema_version": SESSION_REVIEW_SCHEMA_VERSION,
        "generated_at": session["generated_at"],
        "warning": session["warning"],
        "relationships": session["relationships"],
        "proposed_threads": session["proposed_threads"],
    }
    unassigned_payload = {
        "schema_version": SESSION_REVIEW_SCHEMA_VERSION,
        "generated_at": session["generated_at"],
        "warning": session["warning"],
        "mentions": session["unassigned_mentions"],
    }
    manifest = {
        "schema_version": SESSION_REVIEW_SCHEMA_VERSION,
        "generated_at": session["generated_at"],
        "package_root": ".",
        "canonical_local_folder": True,
        "required_start_file": "START_HERE_FOR_TICKET_AGENT.md",
        "session_summary": session["summary"],
        "mention_ids": [mention.get("mention_id") for mention in session["mentions"]],
        "root_review_files": list(ROOT_PRIORITY[:9]),
        "agent_review_required": True,
        "semantic_authority": "evidence_preparation_only",
        "provisional_evidence_cluster_count": len(outcomes),
        "provisional_outcome_path": "CONSOLIDATED_OUTCOMES.json",
        "integrity_report_path": "EVIDENCE_INTEGRITY_REPORT.json",
        "warning": session["warning"],
    }
    status = {
        "schema_version": SESSION_REVIEW_SCHEMA_VERSION,
        "generated_at": session["generated_at"],
        "status": "ready",
        "canonical_local_folder": ".",
        "portable_mode": portable_mode,
        "portable_zip_max_mb": portable_zip_max_mb,
        "portable_zip_path": "",
        "portable_zip_size_bytes": 0,
        "semantic_authority": "evidence_preparation_only",
        "provisional_evidence_cluster_count": len(outcomes),
        "artifact_integrity_status": integrity_report.get("status", "not_available"),
        "portable_privacy_status": "not_run",
        "selected_media_count": 0,
        "omitted_media_count": 0,
        **session["summary"],
        "transcript_warning_record_count": session["summary"].get(
            "transcript_warning_record_count", 0
        ),
        "warnings": [
            session["warning"],
            *(
                [
                    "One or more timeline records have transcript-quality warnings. Review EVIDENCE_QUALITY_REPORT.md before trusting ticket recall."
                ]
                if session["summary"].get("transcript_warning_record_count")
                else []
            ),
        ],
    }

    _text_write(
        output_dir / "START_HERE_FOR_TICKET_AGENT.md",
        _start_here_markdown(session, outcomes),
    )
    _json_write(output_dir / "AGENT_REVIEW_MANIFEST.json", manifest)
    _text_write(output_dir / "SESSION_TIMELINE.md", _timeline_markdown(session))
    _json_write(output_dir / "SESSION_TIMELINE.json", timeline_payload)
    _text_write(output_dir / "TICKET_THREAD_HINTS.md", _thread_markdown(session))
    _json_write(output_dir / "TICKET_THREAD_HINTS.json", hints_payload)
    _text_write(output_dir / "UNASSIGNED_MENTIONS.md", _unassigned_markdown(session))
    _json_write(output_dir / "UNASSIGNED_MENTIONS.json", unassigned_payload)
    _json_write(output_dir / "PACKAGE_STATUS.json", status)

    drafts_dir = output_dir / "operator-drafts"
    try:
        absolute_root = str(output_dir.resolve())
    except OSError:
        absolute_root = str(output_dir.absolute())
    _text_write(
        drafts_dir / "session.codex.md",
        _session_prompt(session, "Codex", outcomes, absolute_root, projects),
    )
    _text_write(
        drafts_dir / "session.claude.md",
        _session_prompt(session, "Claude Code", outcomes, absolute_root, projects),
    )
    _json_write(
        drafts_dir / "session.handoff.json",
        {
            "schema_version": SESSION_REVIEW_SCHEMA_VERSION,
            "package_root": absolute_root,
            "start_file": "START_HERE_FOR_TICKET_AGENT.md",
            "projects": projects or {},
            "detection_method": "deterministic_marker_scan",
            "detection_is_authoritative": False,
            "agent_must_present_before_writing": True,
            "session_summary": session["summary"],
            "local_evidence_access_required": True,
            "agent_review_required": True,
            "semantic_authority": "evidence_preparation_only",
            "provisional_evidence_cluster_count": len(outcomes),
            "provisional_outcome_path": "../CONSOLIDATED_OUTCOMES.json",
            "integrity_report_path": "../EVIDENCE_INTEGRITY_REPORT.json",
            "warning": session["warning"],
        },
    )
    return status


def _relative_files(root: Path) -> list[Path]:
    # 197/209: through the one ZIP writer's long-path-safe listing.
    return list_files(root, exclude_names={PORTABLE_ZIP_FILENAME})


def _priority_key(root: Path, path: Path) -> tuple[int, str]:
    relative = path.relative_to(root).as_posix()
    try:
        root_index = ROOT_PRIORITY.index(relative)
    except ValueError:
        root_index = len(ROOT_PRIORITY)
    return root_index, relative.lower()


def _mention_timestamps(root: Path) -> dict[str, str]:
    try:
        payload = json.loads(
            local_io_path(root / "SESSION_TIMELINE.json").read_text(encoding="utf-8-sig")
        )
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        _safe_text(record.get("mention_id")): _safe_text(record.get("timestamp"))
        for record in payload.get("records") or []
        if isinstance(record, dict) and _safe_text(record.get("mention_id"))
    }


def _media_omission_entry(
    root: Path,
    path: Path,
    reason: str,
    timestamps: dict[str, str],
) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    match = re.search(r"evidence_items/([^/]+)", relative, flags=re.IGNORECASE)
    mention_id = match.group(1) if match else "session"
    return {
        "candidate_or_mention_id": mention_id,
        "timestamp": timestamps.get(mention_id, ""),
        "omitted_artifact": path.name,
        "local_relative_path": relative,
        "reason": reason,
        "canonical_folder_location": relative,
    }


def _omitted_markdown(items: list[dict[str, Any]]) -> str:
    lines = [
        "# Omitted Media",
        "",
        "The canonical local evidence folder remains complete. These media files were omitted from the portable ZIP so required instructions, indexes, transcripts, and maps remain available first.",
        "",
    ]
    if not items:
        lines.append("No media files were omitted.")
    for item in items:
        lines.extend(
            [
                f"- {item['candidate_or_mention_id']} | {item['omitted_artifact']}",
                f"  - Local path: `{item['local_relative_path']}`",
                f"  - Reason: {item['reason']}",
            ]
        )
    return "\n".join(lines)


_PORTABLE_REDACTED = "[excluded from portable package]"
_PORTABLE_SENSITIVE_KEY_PATTERNS = {
    "recorder_private_identifier": re.compile(
        r"(?:layout|stream|recorder).*(?:fingerprint|signature)|(?:fingerprint|signature).*(?:layout|stream|recorder)",
        re.IGNORECASE,
    ),
    "biometric_local_identifier": re.compile(
        r"(?:voice|speaker).*(?:enrollment|signature|vector|embedding)|(?:enrollment|signature|vector|embedding).*(?:voice|speaker)",
        re.IGNORECASE,
    ),
    "secret_material": re.compile(
        r"(?:api[_-]?key|authorization|bearer|password|secret|access[_-]?token|refresh[_-]?token)",
        re.IGNORECASE,
    ),
    "command_invocation": re.compile(r"(?:command|command_line|invocation_command|arguments?)", re.IGNORECASE),
}


def _portable_match_counts(text: str, root: Path) -> dict[str, int]:
    normalized = text.replace("\\\\", "\\").replace("/", "\\")
    username = _safe_text(os.environ.get("USERNAME") or Path.home().name)
    temp_roots = {
        _safe_text(os.environ.get(name)).replace("/", "\\").lower().rstrip("\\")
        for name in ("TEMP", "TMP", "APPDATA", "LOCALAPPDATA")
        if _safe_text(os.environ.get(name))
    }
    root_text = str(root.resolve()).replace("/", "\\").lower().rstrip("\\")
    counts = {
        "local_path": len(re.findall(r"(?i)(?:[a-z]:\\|\\\\[^\\\s]+\\)", normalized)),
        "local_user": 0,
        "temporary_storage": 0,
        "command_invocation": len(
            re.findall(r"(?im)^\s*(?:command|command line|invocation)\s*[:=]", normalized)
        ),
        "recorder_private_identifier": len(
            re.findall(r"(?i)(?:layout|stream|recorder)[_ -]?(?:fingerprint|signature)", normalized)
        ),
        "biometric_local_identifier": len(
            re.findall(r"(?i)(?:voice|speaker)[_ -]?(?:enrollment|signature|vector|embedding)", normalized)
        ),
        "secret_material": len(
            re.findall(
                r"(?i)(?:api[_-]?key|authorization\s*[:=]|bearer\s+[a-z0-9._-]+|password\s*[:=]|(?:access|refresh)[_-]?token\s*[:=])",
                normalized,
            )
        ),
    }
    lowered = normalized.lower()
    if username:
        counts["local_user"] = len(
            re.findall(rf"(?i)(?:\\users\\|\b){re.escape(username)}(?:\\|\b)", normalized)
        )
    counts["temporary_storage"] = sum(lowered.count(value) for value in temp_roots)
    if root_text:
        counts["temporary_storage"] += lowered.count(root_text)
    return counts


def _sanitize_portable_string(value: str, root: Path, removed: dict[str, int]) -> str:
    original = value
    normalized = value.replace("/", "\\")
    root_text = str(root.resolve()).replace("/", "\\").rstrip("\\")
    if re.match(r"(?i)^[a-z]:\\", normalized) or normalized.startswith("\\\\"):
        if normalized.lower().startswith(root_text.lower() + "\\"):
            value = normalized[len(root_text) + 1 :].replace("\\", "/")
        else:
            value = PureWindowsPath(normalized).name or _PORTABLE_REDACTED
        removed["local_path"] += 1
    else:
        value, path_count = re.subn(
            r"`(?:[a-zA-Z]:\\|\\\\)[^`\r\n]+`",
            _PORTABLE_REDACTED,
            value,
        )
        value, token_path_count = re.subn(
            r"(?i)(?:[a-z]:\\|\\\\)[^\s,;\)\]\}\"']+",
            _PORTABLE_REDACTED,
            value,
        )
        removed["local_path"] += path_count + token_path_count
    username = _safe_text(os.environ.get("USERNAME") or Path.home().name)
    if username:
        value, user_count = re.subn(re.escape(username), "[local user removed]", value, flags=re.IGNORECASE)
        removed["local_user"] += user_count
    lines: list[str] = []
    for line in value.splitlines(keepends=True):
        if re.match(r"(?i)^\s*(?:command|command line|invocation)\s*[:=]", line):
            removed["command_invocation"] += 1
            lines.append(_PORTABLE_REDACTED + ("\n" if line.endswith("\n") else ""))
        else:
            lines.append(line)
    value = "".join(lines)
    if original and not value:
        return _PORTABLE_REDACTED
    return value


def _sanitize_portable_json_value(
    value: Any,
    root: Path,
    removed: dict[str, int],
    *,
    key: str = "",
) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for item_key, item_value in value.items():
            item_key_text = str(item_key)
            sensitive_category = next(
                (
                    category
                    for category, pattern in _PORTABLE_SENSITIVE_KEY_PATTERNS.items()
                    if pattern.search(item_key_text)
                ),
                "",
            )
            if sensitive_category:
                removed[sensitive_category] += 1
                continue
            sanitized[item_key_text] = _sanitize_portable_json_value(
                item_value,
                root,
                removed,
                key=item_key_text,
            )
        return sanitized
    if isinstance(value, list):
        return [
            _sanitize_portable_json_value(item, root, removed, key=key) for item in value
        ]
    if isinstance(value, str):
        return _sanitize_portable_string(value, root, removed)
    return value


def _portable_text_payload(
    path: Path,
    root: Path,
    removed: dict[str, int],
) -> bytes:
    text = local_io_path(path).read_text(encoding="utf-8-sig", errors="replace")
    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            sanitized = _sanitize_portable_string(text, root, removed)
        else:
            sanitized_payload = _sanitize_portable_json_value(payload, root, removed)
            sanitized = json.dumps(sanitized_payload, ensure_ascii=False, indent=2) + "\n"
    elif path.suffix.lower() == ".jsonl":
        lines: list[str] = []
        for line in text.splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                lines.append(_sanitize_portable_string(line, root, removed))
            else:
                sanitized_payload = _sanitize_portable_json_value(payload, root, removed)
                lines.append(json.dumps(sanitized_payload, ensure_ascii=False))
        sanitized = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    else:
        sanitized = _sanitize_portable_string(text, root, removed)
    return sanitized.encode("utf-8")


def _portable_binary_text_probe(payload: bytes) -> str:
    """Return only contiguous printable metadata for privacy inspection.

    Decoding compressed media with ``errors="ignore"`` can remove arbitrary
    bytes between printable fragments and manufacture path-looking strings
    that never existed in the file.  Printable runs preserve byte adjacency,
    while still exposing embedded filenames, paths, usernames, and metadata.
    """

    return "\n".join(
        match.group(0).decode("ascii")
        for match in re.finditer(rb"[\x20-\x7e]{4,}", payload)
    )


def _portable_binary_match_counts(text: str, root: Path) -> dict[str, int]:
    """Inspect real printable binary metadata without rewriting separators."""

    username = _safe_text(os.environ.get("USERNAME") or Path.home().name)
    drive_paths = re.findall(
        r"(?i)(?<![a-z0-9])[a-z]:[\\/][a-z0-9._ $()\-]{2,}[\\/][a-z0-9._ $()\-]{2,}(?:[\\/][a-z0-9._ $()\-]+)*",
        text,
    )
    unc_candidates = re.findall(
        r"(?i)\\\\[a-z0-9][a-z0-9._-]{1,63}\\[a-z0-9$][a-z0-9$._ -]{0,63}(?:\\[a-z0-9$._ -]+)*",
        text,
    )
    unc_paths = [value for value in unc_candidates if len(value) >= 12]
    counts = {
        "local_path": len(drive_paths) + len(unc_paths),
        "local_user": 0,
        "temporary_storage": 0,
        "command_invocation": len(
            re.findall(r"(?im)^\s*(?:command|command line|invocation)\s*[:=]", text)
        ),
        "recorder_private_identifier": len(
            re.findall(r"(?i)(?:layout|stream|recorder)[_ -]?(?:fingerprint|signature)", text)
        ),
        "biometric_local_identifier": len(
            re.findall(r"(?i)(?:voice|speaker)[_ -]?(?:enrollment|signature|vector|embedding)", text)
        ),
        "secret_material": len(
            re.findall(
                r"(?i)(?:api[_-]?key|authorization\s*[:=]|bearer\s+[a-z0-9._-]+|password\s*[:=]|(?:access|refresh)[_-]?token\s*[:=])",
                text,
            )
        ),
    }
    if username:
        counts["local_user"] = len(
            re.findall(rf"(?i)(?:[\\/]users[\\/]|\b){re.escape(username)}(?:[\\/]|\b)", text)
        )
    lowered = text.lower()
    for name in ("TEMP", "TMP", "APPDATA", "LOCALAPPDATA"):
        value = _safe_text(os.environ.get(name))
        if value:
            counts["temporary_storage"] += lowered.count(value.lower())
            counts["temporary_storage"] += lowered.count(value.replace("\\", "/").lower())
    root_text = str(root.resolve())
    counts["temporary_storage"] += lowered.count(root_text.lower())
    counts["temporary_storage"] += lowered.count(root_text.replace("\\", "/").lower())
    return counts


def build_portable_agent_zip(
    output_dir: Path,
    *,
    max_size_mb: int = 100,
    zip_name: str = PORTABLE_ZIP_FILENAME,
) -> dict[str, Any]:
    """Build a sanitized text-first ZIP and fail closed on local/private residue."""

    output_dir = output_dir.resolve()
    max_bytes = max(1, int(max_size_mb)) * 1024 * 1024
    all_files = _relative_files(output_dir)
    excluded_logs = [path for path in all_files if path.suffix.lower() == ".log"]
    files = [
        path
        for path in all_files
        if path.suffix.lower() != ".log" and path.name != "PORTABLE_PRIVACY_REPORT.json"
    ]
    required_text = sorted(
        [path for path in files if path.suffix.lower() in TEXT_EXTENSIONS],
        key=lambda path: _priority_key(output_dir, path),
    )
    media = sorted(
        [path for path in files if path.suffix.lower() in MEDIA_EXTENSIONS],
        key=lambda path: path.relative_to(output_dir).as_posix().lower(),
    )
    other = [path for path in files if path not in required_text and path not in media]
    required_text.extend(sorted(other, key=lambda path: path.relative_to(output_dir).as_posix().lower()))

    required_bytes = sum(local_io_path(path).stat().st_size for path in required_text)
    reserve_bytes = 256 * 1024
    remaining = max(0, max_bytes - required_bytes - reserve_bytes)
    selected_media: list[Path] = []
    omitted_media: list[dict[str, Any]] = []
    timestamps = _mention_timestamps(output_dir)
    for path in media:
        size = local_io_path(path).stat().st_size
        if size <= remaining:
            selected_media.append(path)
            remaining -= size
        else:
            omitted_media.append(
                _media_omission_entry(
                    output_dir,
                    path,
                    "Portable ZIP size budget reserved required text, JSON, transcript maps, and indexes first.",
                    timestamps,
                )
            )

    _json_write(
        output_dir / "OMITTED_MEDIA.json",
        {
            "schema_version": SESSION_REVIEW_SCHEMA_VERSION,
            "generated_at": _utc_now(),
            "canonical_local_folder": ".",
            "omitted_media": omitted_media,
        },
    )
    _text_write(output_dir / "OMITTED_MEDIA.md", _omitted_markdown(omitted_media))

    status_path = output_dir / "PACKAGE_STATUS.json"
    try:
        status = json.loads(local_io_path(status_path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        status = {"schema_version": SESSION_REVIEW_SCHEMA_VERSION, "status": "ready"}
    status.update(
        {
            "portable_zip_path": zip_name,
            "portable_zip_size_bytes": 0,
            "portable_zip_size_is_estimate": True,
            "portable_zip_size_note": (
                "The ZIP copy contains a preflight size estimate because PACKAGE_STATUS.json is inside the archive. "
                "The canonical local PACKAGE_STATUS.json records the exact final size."
            ),
            "selected_media_count": len(selected_media),
            "omitted_media_count": len(omitted_media),
            "portable_required_text_bytes": required_bytes,
            "portable_size_budget_bytes": max_bytes,
            "portable_privacy_status": "preflight",
            "portable_excluded_log_count": len(excluded_logs),
        }
    )
    if required_bytes > max_bytes:
        status.setdefault("warnings", []).append(
            "Required text and index files exceed the configured ZIP budget; they were retained anyway."
        )
    _json_write(status_path, status)

    zip_path = output_dir / zip_name
    privacy_categories = (
        "local_path",
        "local_user",
        "temporary_storage",
        "command_invocation",
        "recorder_private_identifier",
        "biometric_local_identifier",
        "secret_material",
    )
    removed = {category: 0 for category in privacy_categories}

    def included_files() -> list[Path]:
        return [
            path
            for path in _relative_files(output_dir)
            if path.suffix.lower() != ".log"
            and path.name != "PORTABLE_PRIVACY_REPORT.json"
            and (path.suffix.lower() not in MEDIA_EXTENSIONS or path in selected_media)
        ]

    def payload_for(path: Path, removed_counts: dict[str, int]) -> bytes:
        if path.suffix.lower() in TEXT_EXTENSIONS:
            return _portable_text_payload(path, output_dir, removed_counts)
        return local_io_path(path).read_bytes()

    preflight_payloads: dict[str, bytes] = {}
    residual = {category: 0 for category in privacy_categories}
    for path in included_files():
        relative = path.relative_to(output_dir).as_posix()
        payload_bytes = payload_for(path, removed)
        preflight_payloads[relative] = payload_bytes
        is_text = path.suffix.lower() in TEXT_EXTENSIONS
        text_probe = (
            payload_bytes.decode("utf-8", errors="replace")
            if is_text
            else _portable_binary_text_probe(payload_bytes)
        )
        match_counts = (
            _portable_match_counts(text_probe, output_dir)
            if is_text
            else _portable_binary_match_counts(text_probe, output_dir)
        )
        for category, count in match_counts.items():
            residual[category] += count

    privacy_report = {
        "schema_version": 1,
        "generated_at": _utc_now(),
        "status": "passed" if not any(residual.values()) else "failed",
        "policy": "portable_handoff_fail_closed",
        "sanitized_value_count_by_category": removed,
        "residual_match_count_by_category": residual,
        "excluded_log_count": len(excluded_logs),
        "included_file_count": len(preflight_payloads) + 1,
        "matched_values_recorded": False,
    }
    privacy_path = output_dir / "PORTABLE_PRIVACY_REPORT.json"
    _json_write(privacy_path, privacy_report)
    if any(residual.values()):
        status["status"] = "failed_privacy"
        status["portable_privacy_status"] = "failed"
        status.setdefault("warnings", []).append(
            "Portable ZIP creation was blocked because sanitized content still contained a forbidden local or private category."
        )
        _json_write(status_path, status)
        if zip_path.exists():
            zip_path.unlink()
        raise RuntimeError(
            "Portable ZIP privacy preflight failed. Review PORTABLE_PRIVACY_REPORT.json."
        )

    status["portable_privacy_status"] = "passed"
    _json_write(status_path, status)
    manifest_path = output_dir / "manifest.json"
    try:
        package_manifest = json.loads(
            local_io_path(manifest_path).read_text(encoding="utf-8-sig")
        )
    except (OSError, json.JSONDecodeError):
        package_manifest = None
    if isinstance(package_manifest, dict):
        package_manifest["portable_privacy"] = {
            "status": "passed",
            "fail_closed": True,
            "logs_excluded": True,
            "report_path": "PORTABLE_PRIVACY_REPORT.json",
            "matched_values_recorded": False,
        }
        _json_write(manifest_path, package_manifest)

    def write_archive() -> int:
        # 209: written by the one ZIP writer, as every feature's ZIP is.
        fresh_removed = {category: 0 for category in privacy_categories}
        entries = [
            {"name": path.relative_to(output_dir).as_posix(),
             "data": (lambda path=path: payload_for(path, fresh_removed))}
            for path in sorted(included_files(), key=lambda item: _priority_key(output_dir, item))
        ]
        entries.append({"name": "PORTABLE_PRIVACY_REPORT.json",
                        "data": json.dumps(privacy_report, ensure_ascii=False, indent=2) + "\n"})
        return int(write_zip(zip_path, entries)["size_bytes"])

    preliminary_size = write_archive()
    status["portable_zip_size_bytes"] = preliminary_size
    _json_write(status_path, status)
    actual_size = write_archive()
    status["portable_zip_size_bytes"] = actual_size
    status["portable_zip_size_is_estimate"] = False
    status["portable_zip_size_note"] = "Exact size of the completed portable ZIP."
    _json_write(status_path, status)
    return {
        "zip_path": str(zip_path),
        "zip_size_bytes": actual_size,
        "selected_media_count": len(selected_media),
        "omitted_media_count": len(omitted_media),
        "required_text_count": len(required_text),
        "required_text_bytes": required_bytes,
        "omitted_media": omitted_media,
        "privacy_report_path": str(privacy_path),
        "privacy_status": privacy_report["status"],
        "excluded_log_count": len(excluded_logs),
    }
