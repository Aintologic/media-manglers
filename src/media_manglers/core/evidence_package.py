"""Codex evidence package detection and output helpers."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any

from ..contracts import EvidenceNarrationSettings
from .narration_evidence import INDEX_JSON as NARRATION_INDEX_JSON, INDEX_MARKDOWN as NARRATION_INDEX_MARKDOWN
from .panel_layout import (
    PANEL_CROP_MODE_DEFAULT,
    PANEL_CROP_MODES,
    THREE_PANEL_COMPOSITE_HEIGHT,
    THREE_PANEL_COMPOSITE_WIDTH,
    THREE_PANEL_CROP_HEIGHT,
    THREE_PANEL_CROP_WIDTH,
    THREE_PANEL_DEFINITIONS,
    detect_three_panel_layout,
    normalize_panel_crop_mode,
    panel_crop_configuration,
    resolve_panel_definitions,
)
from .session_review import (
    PORTABLE_ZIP_FILENAME,
    build_portable_agent_zip,
    build_session_review,
    local_io_path,
    write_session_review_artifacts,
)
from .transcript_corrections import (
    build_correction_markdown,
    build_whisper_initial_prompt,
    correct_segments,
    load_transcription_glossary,
)
from .sparse_narration import silence_hallucination_metrics
from .voice_track import count_spotter_words
from .transcripts import write_transcript_files


CONFIDENCE_RANK = {
    # 199: a word said in passing ("ticket", "bug", "fix this"). It never makes a ticket on its
    # own; the moment is listed under "Mentioned, not asked for" for the operator to decide.
    "mention": 0,
    "supporting": 0,
    "weak": 1,
    "likely": 2,
    "explicit": 3,
}

MARKERS = [
    # 151: a request handed straight to the agent, without a ticket word. Multi-word phrases only;
    # "AI" is written "AI" or "A.I." by Whisper.
    {"phrase": "instructions for ai", "confidence": "explicit"},
    {"phrase": "instructions for the ai", "confidence": "explicit"},
    {"phrase": "instructions for a.i", "confidence": "explicit"},
    {"phrase": "instruction for ai", "confidence": "explicit"},
    {"phrase": "note for ai", "confidence": "explicit"},
    {"phrase": "note for the ai", "confidence": "explicit"},
    {"phrase": "note for a.i", "confidence": "explicit"},
    {"phrase": "feature request", "confidence": "explicit"},
    {"phrase": "this needs to be a ticket", "confidence": "explicit"},
    {"phrase": "that needs to be a ticket", "confidence": "explicit"},
    {"phrase": "this needs a ticket", "confidence": "explicit"},
    {"phrase": "that needs a ticket", "confidence": "explicit"},
    {"phrase": "this should become a ticket", "confidence": "explicit"},
    {"phrase": "that should become a ticket", "confidence": "explicit"},
    {"phrase": "we should make this a ticket", "confidence": "explicit"},
    {"phrase": "we should make that a ticket", "confidence": "explicit"},
    {"phrase": "make that like a maintenance ticket", "confidence": "explicit"},
    {"phrase": "maintenance ticket", "confidence": "explicit"},
    {"phrase": "make that a ticket", "confidence": "explicit"},
    {"phrase": "make this a ticket", "confidence": "explicit"},
    {"phrase": "put this in a ticket", "confidence": "explicit"},
    {"phrase": "file this as a ticket", "confidence": "explicit"},
    {"phrase": "create a ticket", "confidence": "explicit"},
    # 199: the other ways of asking for one, now that a ticket word alone is only a mention.
    {"phrase": "make a ticket", "confidence": "explicit"},
    {"phrase": "make me a ticket", "confidence": "explicit"},
    {"phrase": "open a ticket", "confidence": "explicit"},
    {"phrase": "add a ticket", "confidence": "explicit"},
    {"phrase": "file a ticket", "confidence": "explicit"},
    {"phrase": "log a ticket", "confidence": "explicit"},
    {"phrase": "raise a ticket", "confidence": "explicit"},
    {"phrase": "write a ticket", "confidence": "explicit"},
    {"phrase": "write up a ticket", "confidence": "explicit"},
    {"phrase": "here is a ticket", "confidence": "explicit"},
    {"phrase": "open an issue", "confidence": "explicit"},
    {"phrase": "file an issue", "confidence": "explicit"},
    {"phrase": "log an issue", "confidence": "explicit"},
    {"phrase": "raise an issue", "confidence": "explicit"},
    {"phrase": "add an issue", "confidence": "explicit"},
    {"phrase": "file a bug", "confidence": "explicit"},
    {"phrase": "log a bug", "confidence": "explicit"},
    {"phrase": "raise a bug", "confidence": "explicit"},
    {"phrase": "create some tickets", "confidence": "explicit"},
    {"phrase": "here's a ticket", "confidence": "explicit"},
    {"phrase": "heres a ticket", "confidence": "explicit"},
    {"phrase": "another ticket", "confidence": "explicit"},
    {"phrase": "whole new ticket", "confidence": "explicit"},
    {"phrase": "new ticket", "confidence": "explicit"},
    {"phrase": "that should be a ticket", "confidence": "explicit"},
    {"phrase": "this should be a ticket", "confidence": "explicit"},
    {"phrase": "here's a ticket for a new feature", "confidence": "explicit"},
    {"phrase": "make this a to-do item", "confidence": "explicit"},
    {"phrase": "make an issue ticket", "confidence": "explicit"},
    {"phrase": "create an issue ticket", "confidence": "explicit"},
    {"phrase": "make an issue", "confidence": "explicit"},
    {"phrase": "create an issue", "confidence": "explicit"},
    {"phrase": "open a GitHub issue", "confidence": "explicit"},
    {"phrase": "add this to GitHub", "confidence": "explicit"},
    {"phrase": "add this to the todo", "confidence": "explicit"},
    {"phrase": "add this to the to-do", "confidence": "explicit"},
    {"phrase": "add this to my todo", "confidence": "explicit"},
    {"phrase": "add this to my to-do", "confidence": "explicit"},
    {"phrase": "make this a todo", "confidence": "explicit"},
    {"phrase": "make this a to-do", "confidence": "explicit"},
    {"phrase": "create a todo", "confidence": "explicit"},
    {"phrase": "create a to-do", "confidence": "explicit"},
    {"phrase": "add this as a task", "confidence": "explicit"},
    {"phrase": "make this a task", "confidence": "explicit"},
    {"phrase": "track this", "confidence": "explicit"},
    {"phrase": "capture this", "confidence": "explicit"},
    {"phrase": "that's gotta be a bug", "confidence": "explicit"},
    {"phrase": "thats gotta be a bug", "confidence": "explicit"},
    {"phrase": "that's a bug", "confidence": "explicit"},
    {"phrase": "thats a bug", "confidence": "explicit"},
    {"phrase": "this needs to be fixed", "confidence": "likely"},
    {"phrase": "that needs to be fixed", "confidence": "likely"},
    {"phrase": "this needs fixed", "confidence": "likely"},
    {"phrase": "that needs fixed", "confidence": "likely"},
    {"phrase": "this needs work", "confidence": "likely"},
    {"phrase": "that needs work", "confidence": "likely"},
    {"phrase": "this should be fixed", "confidence": "likely"},
    {"phrase": "that should be fixed", "confidence": "likely"},
    {"phrase": "we need to fix this", "confidence": "likely"},
    {"phrase": "we need to fix that", "confidence": "likely"},
    {"phrase": "we need to fix", "confidence": "likely"},
    {"phrase": "can we fix this", "confidence": "likely"},
    {"phrase": "can we fix that", "confidence": "likely"},
    {"phrase": "need to fix this", "confidence": "likely"},
    {"phrase": "need to fix that", "confidence": "likely"},
    {"phrase": "fix that", "confidence": "mention"},
    {"phrase": "fix it", "confidence": "mention"},
    {"phrase": "this is a problem", "confidence": "likely"},
    {"phrase": "that is a problem", "confidence": "likely"},
    {"phrase": "this is an issue", "confidence": "likely"},
    {"phrase": "that is an issue", "confidence": "likely"},
    {"phrase": "change i want to make", "confidence": "likely"},
    {"phrase": "new feature", "confidence": "likely"},
    {"phrase": "maintenance run", "confidence": "likely"},
    {"phrase": "this is all for that same ticket", "confidence": "likely"},
    {"phrase": "back to the previous ticket", "confidence": "likely"},
    {"phrase": "ticket", "confidence": "mention"},
    {"phrase": "tickets", "confidence": "mention"},
    {"phrase": "issue", "confidence": "mention"},
    {"phrase": "issues", "confidence": "mention"},
    {"phrase": "bug", "confidence": "mention"},
    {"phrase": "bugs", "confidence": "mention"},
    {"phrase": "todo", "confidence": "mention"},
    {"phrase": "to-do", "confidence": "mention"},
    {"phrase": "task", "confidence": "mention"},
    {"phrase": "fix this", "confidence": "mention"},
    {"phrase": "this is broken", "confidence": "likely"},
    {"phrase": "broken", "confidence": "mention"},
    {"phrase": "this is wrong", "confidence": "likely"},
    {"phrase": "wrong", "confidence": "mention"},
    {"phrase": "codex should", "confidence": "likely"},
    {"phrase": "chatgpt should", "confidence": "likely"},
    {"phrase": "next thing", "confidence": "weak"},
    {"phrase": "add this", "confidence": "weak"},
    {"phrase": "change this", "confidence": "weak"},
    {"phrase": "remove this", "confidence": "weak"},
    {"phrase": "remember this", "confidence": "weak"},
    {"phrase": "follow up on this", "confidence": "weak"},
    {"phrase": "follow-up on this", "confidence": "weak"},
    {"phrase": "remind me to fix this", "confidence": "weak"},
    {"phrase": "remind me to look at this", "confidence": "weak"},
    {"phrase": "look at this later", "confidence": "weak"},
    {"phrase": "come back to this", "confidence": "weak"},
    {"phrase": "dashboard", "confidence": "supporting"},
    {"phrase": "dashboards", "confidence": "supporting"},
    {"phrase": "simhub", "confidence": "supporting"},
    {"phrase": "sim hub", "confidence": "supporting"},
    {"phrase": "codex", "confidence": "supporting"},
]

WINDOW_SPLIT_HINTS = (
    "instructions for ai",
    "instructions for the ai",
    "instructions for a.i",
    "instruction for ai",
    "note for ai",
    "note for the ai",
    "note for a.i",
    "feature request",
    "this needs to be a ticket",
    "that needs to be a ticket",
    "this needs a ticket",
    "that needs a ticket",
    "this should become a ticket",
    "that should become a ticket",
    "this is a separate ticket",
    "that is a separate ticket",
    "next ticket",
    "another ticket",
    "here's a ticket",
    "heres a ticket",
    "here is a ticket",
    "make that a ticket",
    "make this a ticket",
    "make an issue",
    "create an issue",
    "make an issue ticket",
    "add this to the todo",
    "open a GitHub issue",
    "this needs to be fixed",
    "track this",
    "capture this",
    "maintenance ticket",
    "new feature",
    "that's a bug",
    "thats a bug",
    "that's gotta be a bug",
    "thats gotta be a bug",
    "next thing",
    "next issue",
    "another issue",
    "that's another issue",
    "thats another issue",
    "another bug",
    "change i want to make",
    "create some tickets",
    "new ticket",
    "whole new ticket",
)

WINDOW_MERGE_HINTS = (
    "this is all for that same ticket",
    "same ticket",
    "back to the previous ticket",
    "back to that ticket",
    "previous ticket",
)

CONTINUATION_PHRASES = (
    "same ticket",
    "this is the same ticket",
    "that is the same ticket",
    "still the same ticket",
    "continuing the same ticket",
    "back to the previous ticket",
    "back to that ticket",
    "back to this ticket",
)

NEW_TICKET_BOUNDARY_PHRASES = (
    "new ticket",
    "another ticket",
    "next issue",
    "another issue",
    "that's another issue",
    "thats another issue",
    "another bug",
    "this is a separate ticket",
    "that is a separate ticket",
    "this is another ticket",
    "that is another ticket",
    "next ticket",
    "separate ticket",
)

CLOSING_BOUNDARY_PHRASES = (
    "end ticket",
    "end of ticket",
    "that is all for this ticket",
    "that's all for this ticket",
    "thats all for this ticket",
    "done with that ticket",
    "done with this ticket",
    "this is all for that same ticket",
)

QUALITY_MARKER_TERMS = [
    "ticket",
    "tickets",
    "dashboard",
    "dashboards",
    "simhub",
    "sim hub",
    "maintenance",
    "bug",
    "bugs",
    "issue",
    "issues",
    "todo",
    "to-do",
    "task",
    "fix",
    "new feature",
    "change i want to make",
    "create some tickets",
    "codex",
]

REVIEW_NEEDED_IMPLICIT_PHRASES = (
    "not showing",
    "isn't showing",
    "isnt showing",
    "doesn't show",
    "doesnt show",
    "can't see",
    "cant see",
    "not visible",
    "missing",
    "hard to read",
    "too small",
    "too big",
    "confusing",
    "not clear",
    "not right",
    "looks wrong",
    "looks bad",
    "should show",
    "needs to show",
    "off screen",
    "cut off",
    "flickering",
    "jitter",
)

REVIEW_NEEDED_ACTION_PHRASES = (
    "we need to",
    "needs to",
    "should add",
    "should change",
    "should remove",
    "should show",
    "want to add",
    "want to change",
    "want to remove",
    "would like to add",
    "would like to change",
    "add an",
    "add a",
    "remove the",
    "change the",
)

REVIEW_NEEDED_DOMAIN_TERMS = (
    "dashboard",
    "dashboards",
    "simhub",
    "sim hub",
    "racelogic",
    "race logic",
    "overlay",
    "hud",
    "incident",
    "incident bar",
    "ui",
    "button",
    "menu",
    "panel",
    "display",
    "screen",
    "widget",
    "sector",
    "sectors",
    "zone",
    "delta",
    "lap",
    "color",
    "purple",
    "green",
    "red",
    "yellow",
)

AUDIT_MARKER_PHRASES = [
    "instructions for ai",
    "note for ai",
    "feature request",
    "this needs to be a ticket",
    "that needs to be a ticket",
    "this needs a ticket",
    "that needs a ticket",
    "another ticket",
    "here's a ticket",
    "heres a ticket",
    "make that a ticket",
    "make this a ticket",
    "make an issue",
    "create an issue",
    "make an issue ticket",
    "create an issue ticket",
    "add this to the todo",
    "this needs to be fixed",
    "open a GitHub issue",
    "track this",
    "capture this",
    "maintenance ticket",
    "new feature",
    "that's a bug",
    "thats a bug",
    "change i want to make",
    "next thing",
    "create some tickets",
    "ticket",
    "tickets",
    "bug",
]

PAUSE_THRESHOLD_SECONDS = 30.0
MERGE_GAP_SECONDS = 90.0
AUDIO_SNIPPET_MAX_SECONDS = 300.0
FRAME_CADENCE_SECONDS = 10.0
MAX_FRAMES_PER_CANDIDATE = 60
EVIDENCE_PACKAGE_SCHEMA_VERSION = 2
NARRATION_CONTEXT_PRE_SECONDS = 120.0
NARRATION_CONTEXT_POST_SECONDS = 600.0
NARRATION_PAUSE_THRESHOLD_SECONDS = 30.0
REPO_HINT_UNKNOWN = "UNKNOWN"
REPO_HINT_REVIEW_WARNING = (
    "Repo routing hint only. Confirm with GitHub issue lookup before creating or updating tickets."
)
REPO_HINT_MODES = {"auto", "target-only", "off"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


def _normalize_panel_crop_mode(value: Any) -> str:
    return normalize_panel_crop_mode(value)


def _panel_crop_configuration(mode: str, panel_definitions: Any = None) -> dict[str, Any]:
    return panel_crop_configuration(mode, panel_definitions)


def _load_panel_role_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    direct = payload.get("panel_role_mapping") or payload.get("evidence_panel_role_mapping")
    path_value = _safe_text(
        payload.get("panel_role_map_path") or payload.get("evidence_panel_role_map_path")
    )
    warning = ""
    if direct:
        value = direct
    elif path_value:
        path = Path(path_value)
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            value = None
            warning = f"Panel role map could not be read: {exc}"
    else:
        value = None
    return {
        "definitions": [dict(item) for item in resolve_panel_definitions(value)],
        "source_path": path_value,
        "warning": warning,
    }


def _format_timestamp(seconds: Any) -> str:
    total_ms = max(0, int(round(_coerce_float(seconds) * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds_part, millis = divmod(remainder, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds_part:02}.{millis:03}"


def _format_filename_timestamp(seconds: Any) -> str:
    total_ms = max(0, int(round(_coerce_float(seconds) * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds_part, millis = divmod(remainder, 1_000)
    return f"{hours:02}-{minutes:02}-{seconds_part:02}-{millis:03}"


def _artifact_identity(kind: str, source_id: str, *parts: Any) -> str:
    normalized = [re.sub(r"[^A-Za-z0-9_.-]+", "-", _safe_text(part)).strip("-") for part in parts]
    suffix = ":".join(part for part in normalized if part)
    return f"{kind}:{source_id}:{suffix}" if suffix else f"{kind}:{source_id}"


WINDOWS_LEGACY_ARTIFACT_PATH_BUDGET = 240


def _bounded_transcript_physical_source_id(
    output_dir: Path,
    source_id: str,
) -> tuple[str, bool]:
    """Return a deterministic physical token sized against full transcript paths.

    The logical source ID remains unchanged in manifests. Only filenames use
    this token when the output root plus the longest generated suffix would
    cross the Windows compatibility budget.
    """

    logical_source_id = _safe_text(source_id) or "source"
    fixed_paths = (
        output_dir / "transcript" / "sources" / ".transcript.quality.json",
        output_dir / "transcript" / "sources" / ".transcript.raw.json",
        output_dir / "transcript" / "raw" / "sources" / ".transcript.json",
        output_dir / "audio" / ".audio.wav",
        output_dir / "audio" / ".audio.flac",
    )
    maximum_fixed_length = max(len(str(path)) for path in fixed_paths)
    maximum_source_id_length = (
        WINDOWS_LEGACY_ARTIFACT_PATH_BUDGET - maximum_fixed_length
    )
    if maximum_source_id_length < 16:
        raise ValueError(
            "The selected output root is too long for safe transcript artifacts "
            f"within the {WINDOWS_LEGACY_ARTIFACT_PATH_BUDGET}-character Windows "
            f"compatibility budget: {output_dir}"
        )
    if len(logical_source_id) <= maximum_source_id_length:
        return logical_source_id, False

    digest = hashlib.sha256(logical_source_id.encode("utf-8")).hexdigest()[:12]
    prefix_length = max(1, maximum_source_id_length - len(digest) - 1)
    prefix = logical_source_id[:prefix_length].rstrip("._-") or "s"
    return f"{prefix}-{digest}", True


def _bounded_artifact_relative_path(
    output_dir: Path,
    verbose_relative_path: str,
    compact_relative_path: str,
) -> tuple[str, bool]:
    """Keep generated artifacts below the legacy Windows filesystem boundary.

    Windows PowerShell 5.1 cannot reliably inspect or move ordinary paths near
    MAX_PATH even when FFmpeg successfully writes them.  The manifest retains
    the verbose logical path and artifact identity; only the physical package
    location is shortened when the final destination would exceed this budget.
    """

    verbose_path = output_dir / Path(verbose_relative_path)
    if len(str(verbose_path)) <= WINDOWS_LEGACY_ARTIFACT_PATH_BUDGET:
        return verbose_relative_path, False
    return compact_relative_path, True


def _compact_artifact_source_token(source_id: str) -> str:
    digest = hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:12]
    return f"s-{digest}"


def _compact_artifact_role(role: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", role).strip("-._") or "panel"
    if len(normalized) <= 24:
        return normalized
    digest = hashlib.sha256(role.encode("utf-8")).hexdigest()[:8]
    return f"{normalized[:15]}-{digest}"


def _v092_artifact_path_alias(value: Any) -> str:
    path = _safe_text(value)
    return re.sub(r"-(\d{3})(?=(?:_[^/\\]+)?\.jpg$)", "", path, count=1)


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_marker_text(value: Any) -> str:
    return (
        _safe_text(value)
        .lower()
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )


def _coerce_phrase_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, dict):
        values = value.values()
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = []
    phrases: list[str] = []
    seen: set[str] = set()
    for item in values:
        phrase = _safe_text(item.get("phrase") if isinstance(item, dict) else item)
        normalized = _normalize_marker_text(phrase)
        if not normalized or normalized in seen:
            continue
        phrases.append(phrase)
        seen.add(normalized)
    return phrases


def _extend_phrases(base: list[str] | tuple[str, ...], extra: Any) -> list[str]:
    phrases = list(base)
    seen = {_normalize_marker_text(phrase) for phrase in phrases}
    for phrase in _coerce_phrase_values(extra):
        normalized = _normalize_marker_text(phrase)
        if normalized in seen:
            continue
        phrases.append(phrase)
        seen.add(normalized)
    return phrases


def _custom_marker_entries(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if isinstance(value, (str, dict)):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = []
    markers: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in values:
        if isinstance(item, dict):
            phrase = _safe_text(item.get("phrase"))
            confidence = _safe_text(item.get("confidence")).lower() or "supporting"
        else:
            phrase = _safe_text(item)
            confidence = "supporting"
        normalized = _normalize_marker_text(phrase)
        if not normalized or normalized in seen:
            continue
        if confidence not in CONFIDENCE_RANK:
            confidence = "supporting"
        markers.append({"phrase": phrase, "confidence": confidence})
        seen.add(normalized)
    return markers


def _extend_markers(base: list[dict[str, str]], extra: Any) -> list[dict[str, str]]:
    markers = [dict(marker) for marker in base]
    seen = {_normalize_marker_text(marker.get("phrase")) for marker in markers}
    for marker in _custom_marker_entries(extra):
        normalized = _normalize_marker_text(marker.get("phrase"))
        if normalized in seen:
            continue
        markers.append(marker)
        seen.add(normalized)
    return markers


def _payload_first(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload.get(key) not in (None, ""):
            return payload.get(key)
    return None


def _build_detection_terms(payload: dict[str, Any]) -> dict[str, Any]:
    custom_markers = _payload_first(payload, "custom_markers", "evidence_custom_markers")
    custom_domain_terms = _payload_first(payload, "custom_domain_terms", "evidence_custom_domain_terms")
    custom_marker_entries = _custom_marker_entries(custom_markers)
    markers = _extend_markers(MARKERS, custom_marker_entries)
    review_needed_domain_terms = tuple(_extend_phrases(REVIEW_NEEDED_DOMAIN_TERMS, custom_domain_terms))
    return {
        "markers": markers,
        "quality_marker_terms": _extend_phrases(QUALITY_MARKER_TERMS, [marker["phrase"] for marker in custom_marker_entries]),
        "review_needed_domain_terms": review_needed_domain_terms,
        "custom_marker_count": max(0, len(markers) - len(MARKERS)),
        "custom_domain_term_count": max(0, len(review_needed_domain_terms) - len(REVIEW_NEEDED_DOMAIN_TERMS)),
    }


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _read_transcript_payload(path_value: str) -> dict[str, Any]:
    path = Path(path_value)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _skipped_by_operator(source: dict[str, Any]) -> bool:
    """114/196: the operator skipped this recording, so nothing from it is in the package."""

    return _safe_text(source.get("status")).lower() == "operator_skipped"


def _read_transcript_segments(path_value: str) -> list[dict[str, Any]]:
    payload = _read_transcript_payload(path_value)
    return _normalize_transcript_segments(payload.get("segments") or [])


def _whisper_transcript_path(path_value: str) -> str:
    """Where Whisper's own wording is, for a transcript path.

    A transcript reused on Continue is this package's corrected copy
    (``transcript/sources``, written with a correction_count and without
    each segment's raw text); what Whisper heard is in the raw copy beside
    it (``transcript/raw/sources``). Any other path is Whisper's output.
    """

    if not path_value:
        return path_value
    path = Path(path_value)
    if path.parent.name != "sources" or path.parent.parent.name != "transcript":
        return path_value
    if "correction_count" not in _read_transcript_payload(path_value):
        return path_value
    raw_copy = path.parent.parent / "raw" / "sources" / path.name
    return str(raw_copy) if local_io_path(raw_copy).is_file() else path_value


def _normalize_transcript_segments(value: Any) -> list[dict[str, Any]]:
    segments = []
    for index, segment in enumerate(value or [], start=1):
        if not isinstance(segment, dict):
            continue
        text = _safe_text(segment.get("text"))
        if not text:
            continue
        start = max(0.0, _coerce_float(segment.get("start"), 0.0))
        end = max(start, _coerce_float(segment.get("end"), start))
        segments.append(
            {
                "id": segment.get("id", index),
                "start": start,
                "end": end,
                "timestamp_start": _format_timestamp(start),
                "timestamp_end": _format_timestamp(end),
                "text": text,
                **(
                    {"raw_text": _safe_text(segment.get("raw_text"))}
                    if _safe_text(segment.get("raw_text"))
                    else {}
                ),
            }
        )
    return segments


def _word_tokens(text: str) -> list[str]:
    return [match.group(0).lower() for match in re.finditer(r"[A-Za-z0-9]+", text)]


def _word_count(text: str) -> int:
    return len(_word_tokens(text))


def _count_phrase(text: str, phrase: str) -> int:
    lower_text = _normalize_marker_text(text)
    lower_phrase = _normalize_marker_text(phrase)
    if not lower_phrase:
        return 0
    return len(re.findall(_phrase_pattern(lower_phrase), lower_text, flags=re.IGNORECASE))


def _source_transcript_text(source: dict[str, Any]) -> str:
    segment_text = " ".join(_safe_text(segment.get("text")) for segment in source.get("segments", []))
    if segment_text.strip():
        return segment_text.strip()
    txt_value = _safe_text(source.get("transcript_txt_path"))
    txt_path = Path(txt_value) if txt_value else None
    if txt_path is not None and txt_path.is_file():
        return txt_path.read_text(encoding="utf-8-sig").strip()
    return ""


def _top_repeated_words(words: list[str], limit: int = 12) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for word in words:
        counts[word] = counts.get(word, 0) + 1
    return [
        {"word": word, "count": count}
        for word, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _build_marker_counts(text: str, terms: list[str] | tuple[str, ...] = QUALITY_MARKER_TERMS) -> dict[str, int]:
    return {term: _count_phrase(text, term) for term in terms}


def _normalized_segment_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _safe_text(value).lower()).strip()


def _transcript_repetition_metrics(source: dict[str, Any]) -> dict[str, Any]:
    texts = [
        _normalized_segment_text(segment.get("text"))
        for segment in source.get("segments") or []
        if _normalized_segment_text(segment.get("text"))
    ]
    counts: dict[str, int] = {}
    for text in texts:
        counts[text] = counts.get(text, 0) + 1
    duplicate_groups = [
        {"text": text[:180], "count": count}
        for text, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if count > 1
    ]
    repeated_segment_count = sum(item["count"] - 1 for item in duplicate_groups)
    max_consecutive = 0
    current = 0
    previous = ""
    near_duplicate_pairs = 0
    for index, text in enumerate(texts):
        if text == previous:
            current += 1
        else:
            current = 1
            previous = text
        max_consecutive = max(max_consecutive, current)
        if index and text != texts[index - 1] and min(len(text), len(texts[index - 1])) >= 24:
            if SequenceMatcher(None, texts[index - 1], text).ratio() >= 0.92:
                near_duplicate_pairs += 1
    return {
        "segment_count": len(texts),
        "repeated_segment_count": repeated_segment_count,
        "repeated_segment_ratio": round(repeated_segment_count / len(texts), 4) if texts else 0.0,
        "near_duplicate_segment_pairs": near_duplicate_pairs,
        "max_consecutive_identical_segments": max_consecutive,
        "duplicate_segment_groups": duplicate_groups[:12],
    }


def _transcript_language_metrics(source: dict[str, Any], text: str) -> dict[str, Any]:
    letters = [character for character in text if character.isalpha()]
    non_ascii_letters = [character for character in letters if ord(character) > 127]
    non_ascii_ratio = len(non_ascii_letters) / len(letters) if letters else 0.0
    declared = _safe_text(source.get("transcript_language")).lower()
    inconsistent = bool(declared.startswith("en") and len(letters) >= 80 and non_ascii_ratio >= 0.12)
    return {
        "declared_language": declared or "unknown",
        "non_ascii_letter_ratio": round(non_ascii_ratio, 4),
        "language_inconsistency_detected": inconsistent,
    }


def _transcript_gibberish_metrics(source: dict[str, Any]) -> dict[str, Any]:
    suspicious_segments: list[dict[str, Any]] = []
    for segment in source.get("segments") or []:
        text = _safe_text(segment.get("text"))
        words = re.findall(r"[A-Za-z]+", text)
        if not words:
            continue
        vowel_free = [word for word in words if len(word) >= 5 and not re.search(r"[aeiouy]", word, re.I)]
        very_long = [word for word in words if len(word) >= 24]
        ratio = len(vowel_free) / len(words)
        if (len(words) >= 8 and ratio >= 0.35) or very_long:
            suspicious_segments.append(
                {
                    "segment_id": segment.get("id"),
                    "timestamp": segment.get("timestamp_start"),
                    "vowel_free_word_ratio": round(ratio, 4),
                    "very_long_word_count": len(very_long),
                }
            )
    return {
        "gibberish_like_segment_count": len(suspicious_segments),
        "gibberish_like_segments": suspicious_segments[:20],
    }


def _silence_hallucination_metrics(source: dict[str, Any]) -> dict[str, Any]:
    segments = [segment for segment in source.get("segments") or [] if isinstance(segment, dict)]
    fallback = 0 if segments else len(_word_tokens(_source_transcript_text(source)))
    return silence_hallucination_metrics(segments, fallback_word_count=fallback)


def _game_audio_metrics(source: dict[str, Any], text: str) -> dict[str, Any]:
    phrases = (
        "car left",
        "car right",
        "clear left",
        "clear right",
        "still there",
        "pit lane",
        "green flag",
        "yellow flag",
    )
    counts = {phrase: _count_phrase(text, phrase) for phrase in phrases}
    total = sum(counts.values())
    # Share of the transcript that reads like spotter or race-engineer speech.
    # The operator's own narration never sounds like this, so a high share
    # means the wrong track was transcribed (120).
    transcript_words = max(1, len(re.findall(r"[A-Za-z0-9']+", text)))
    spotter_words = count_spotter_words(text)
    spotter_share = spotter_words / transcript_words
    selected = source.get("selected_audio_stream") or {}
    stream_label = " ".join(
        _safe_text(selected.get(key)) for key in ("title", "language", "channel_layout")
    ).lower()
    role = _safe_text(source.get("transcript_audio_role"))
    likely_contamination = bool(
        role == "supporting_audio"
        or "spotter" in stream_label
        or "game" in stream_label
        or total >= 8
        or (spotter_words >= 5 and spotter_share >= 0.10)
    )
    return {
        "game_spotter_phrase_counts": counts,
        "game_spotter_phrase_count": total,
        "game_spotter_word_count": spotter_words,
        "game_spotter_word_share": round(spotter_share, 4),
        "game_spotter_contamination_suspected": likely_contamination,
    }


def _classify_transcript_quality_risk(
    *,
    warning_reasons: list[str],
    duration_seconds: float,
    word_count: int,
    total_marker_count: int,
) -> dict[str, str]:
    if not warning_reasons:
        return {
            "risk_classification": "usable",
            "risk_reason": "Transcript passed automated quality checks.",
            "recommended_action": "Review candidate tickets normally.",
        }
    if duration_seconds <= 300 and total_marker_count == 0:
        return {
            "risk_classification": "suspicious_low_risk_short_clip",
            "risk_reason": "Short or tiny source has a suspicious transcript but no ticket marker terms.",
            "recommended_action": "Low-risk for ticket recall; spot-check only if the source is known to matter.",
        }
    if duration_seconds < 600 and total_marker_count == 0:
        return {
            "risk_classification": "suspicious_low_risk_no_marker_terms",
            "risk_reason": "Suspicious transcript has no ticket marker terms and the source is not a long recording.",
            "recommended_action": "Do not treat as a package-wide failure; spot-check if candidate count seems too low.",
        }
    if word_count < 50 and total_marker_count == 0:
        return {
            "risk_classification": "suspicious_low_risk_no_marker_terms",
            "risk_reason": "Transcript is very small and contains no ticket marker terms.",
            "recommended_action": "Low-risk unless the recording should contain spoken ticket requests.",
        }
    return {
        "risk_classification": "suspicious_high_risk",
        "risk_reason": "Long or marker-bearing source has transcript quality warnings.",
        "recommended_action": "Inspect this source manually or rerun transcription before trusting missing candidates.",
    }


def _build_transcript_quality(
    source: dict[str, Any],
    quality_marker_terms: list[str] | tuple[str, ...] = QUALITY_MARKER_TERMS,
) -> dict[str, Any]:
    text = _source_transcript_text(source)
    words = _word_tokens(text)
    unique_words = set(words)
    word_count = len(words)
    unique_word_count = len(unique_words)
    duration_seconds = _coerce_float(source.get("duration_seconds"), 0.0)
    duration_minutes = duration_seconds / 60.0 if duration_seconds > 0 else 0.0
    words_per_minute = (word_count / duration_minutes) if duration_minutes > 0 else 0.0
    unique_word_ratio = (unique_word_count / word_count) if word_count > 0 else 0.0
    top_repeated_words = _top_repeated_words(words)
    dominant_word = top_repeated_words[0] if top_repeated_words else {"word": "", "count": 0}
    dominant_word_ratio = (int(dominant_word["count"]) / word_count) if word_count > 0 else 0.0
    marker_counts = _build_marker_counts(text, quality_marker_terms)
    total_marker_count = sum(marker_counts.values())
    repetition = _transcript_repetition_metrics(source)
    language = _transcript_language_metrics(source, text)
    gibberish = _transcript_gibberish_metrics(source)
    silence = _silence_hallucination_metrics(source)
    game_audio = _game_audio_metrics(source, text)

    warning_reasons: list[str] = []
    source_status = _safe_text(source.get("status")).lower()
    # Sparse narration is the normal shape of a racing recording: the operator
    # speaks in short bursts across a long session, so word counts measured
    # against source duration say nothing about transcript quality (118).
    sparse_narration = _safe_text(source.get("narration_speech_mode")).lower() == "sparse"
    detected_no_narration = source_status == "no_narration"
    # 114: the operator skipped this recording on purpose; it is neither a
    # failure nor a quality problem.
    skipped_by_operator = source_status == "operator_skipped"
    if source_status not in {"completed", "skipped", "no_narration", "operator_skipped"}:
        warning_reasons.append("source transcription did not complete")
    if not sparse_narration and duration_seconds >= 600 and word_count < 300:
        warning_reasons.append("long video has very low transcript word count")
    if not sparse_narration and duration_seconds >= 600 and words_per_minute < 20:
        warning_reasons.append("transcript is unexpectedly short for source duration")
    if word_count >= 100 and unique_word_ratio < 0.08:
        warning_reasons.append("very low unique-word ratio")
    if word_count >= 100 and dominant_word_ratio >= 0.45:
        warning_reasons.append(
            "one word dominates the transcript: "
            f"{dominant_word['word']} ({dominant_word['count']} of {word_count} words)"
        )
    if word_count >= 100 and total_marker_count == 0 and dominant_word_ratio >= 0.35:
        warning_reasons.append("no ticket markers found and transcript is mostly repeated filler")
    if (
        bool(source.get("raw_video_transcription_used"))
        and _coerce_int(source.get("audio_stream_count"), 0) > 1
    ):
        warning_reasons.append("raw video transcription was used on a multi-audio-stream source")
    if (
        not detected_no_narration
        and _coerce_int(source.get("audio_stream_count"), 0) > 1
        and not _coerce_bool(source.get("audio_stream_selection_confirmed"), False)
    ):
        warning_reasons.append("operator narration stream selection is uncertain")
    if repetition["repeated_segment_count"] >= 2:
        warning_reasons.append(
            f"repeated transcript segments detected ({repetition['repeated_segment_count']})"
        )
    if repetition["near_duplicate_segment_pairs"] >= 2:
        warning_reasons.append(
            f"near-identical adjacent transcript segments detected ({repetition['near_duplicate_segment_pairs']})"
        )
    if repetition["max_consecutive_identical_segments"] >= 3:
        warning_reasons.append("long consecutive transcript repetition loop detected")
    if language["language_inconsistency_detected"]:
        warning_reasons.append("transcript script/language is inconsistent with declared English")
    if gibberish["gibberish_like_segment_count"]:
        warning_reasons.append(
            f"gibberish-like transcript passages detected ({gibberish['gibberish_like_segment_count']})"
        )
    if game_audio["game_spotter_contamination_suspected"]:
        warning_reasons.append("game or spotter audio contamination is suspected")
    if silence["silence_hallucination_suspected"]:
        warning_reasons.append(
            "transcript contains filler Whisper invents on silence "
            f"({silence['silence_hallucination_segment_count']} segments such as 'Thank you for watching')"
        )
    if silence.get("suspect_line_count"):
        # 214: even one kept line that looks invented is worth a look ("A" over 24 seconds).
        first = silence["suspect_lines"][0]
        minutes, seconds = divmod(int(float(first.get("start") or 0.0)), 60)
        warning_reasons.append(
            f"transcript keeps {silence['suspect_line_count']} line(s) that look invented "
            f"(for example '{_safe_text(first.get('text'))[:60]}' at {minutes:02d}:{seconds:02d})"
        )

    failed = source_status not in {"completed", "skipped", "no_narration", "operator_skipped"}
    # 142: the backend could not tell which track is the operator's
    # microphone, so it transcribed nothing and asked the operator. The recording can be
    # full of speech: its narration is missing, not empty.
    needs_track_choice = failed and _safe_text(source.get("error_message")).startswith("Multiple audio tracks:")
    if failed:
        # Nothing was transcribed, so nothing is known about narration in it.
        silence = {**silence, "no_narration_found": False}
    no_narration = bool(not failed and not skipped_by_operator and (detected_no_narration or silence["no_narration_found"]))
    # What voice detection heard, in its own words ("Your usual microphone
    # track, Track 2, is silent. ..."): no track was selected, so "the
    # selected microphone track" would name one that was never used.
    detection_said = _safe_text(source.get("error_message")) if detected_no_narration else ""
    if skipped_by_operator:
        warning_reasons = ["skipped by the operator; nothing from this recording is in the package"]
    if needs_track_choice:
        # Word counts of a transcript that was never made say nothing.
        warning_reasons = ["not transcribed yet: the operator has to choose which audio track is the microphone"]
    if no_narration:
        if detected_no_narration:
            warning_reasons.append(f"no narration found: {detection_said or 'no audio track carries clear speech'}")
        else:
            warning_reasons.append(
                "no narration found: the selected microphone track is silent, or it is the wrong track"
            )
    # 214: a kept line that looks invented is worth a look, but does not make the transcript suspect.
    only_safe_repetition_warnings = bool(warning_reasons) and all(
        reason.startswith(("repeated transcript segments detected", "transcript keeps")) for reason in warning_reasons
    ) and repetition["repeated_segment_ratio"] <= 0.10 and repetition["max_consecutive_identical_segments"] <= 3
    suspicious = bool(
        repetition["max_consecutive_identical_segments"] > 3
        or repetition["repeated_segment_ratio"] > 0.10
        or gibberish["gibberish_like_segment_count"] >= 2
        or language["language_inconsistency_detected"]
        or game_audio["game_spotter_contamination_suspected"]
        or (warning_reasons and not only_safe_repetition_warnings)
    )
    if skipped_by_operator:
        quality_status = "skipped_by_operator"
    elif needs_track_choice:
        quality_status = "needs_track_choice"
    elif failed:
        quality_status = "failed_needs_retranscription"
    elif no_narration:
        quality_status = "no_narration_found"
    elif suspicious:
        quality_status = "suspicious"
    else:
        quality_status = "usable_with_warnings" if warning_reasons else "usable"
    appears_usable = quality_status in {"usable", "usable_with_warnings"}
    if needs_track_choice:
        risk = {
            "risk_classification": "needs_track_choice",
            "risk_reason": (
                "Not transcribed: the app could not tell which audio track is the operator's microphone, "
                "so nothing from this recording is in this package."
            ),
            "recommended_action": (
                "This recording's narration is missing, not empty: do not conclude that nothing was reported in it. "
                "Tell the operator it still needs a voice-track choice (Find my bug reports, Fix and continue)."
            ),
        }
    elif failed:
        # A transcript that does not exist cannot be "low risk" because it
        # contains no marker words (118).
        risk = {
            "risk_classification": "failed_transcription",
            "risk_reason": "This recording produced no usable transcript, so nothing about it can be judged.",
            "recommended_action": "Re-run this recording, choosing its microphone track if the app could not.",
        }
    elif skipped_by_operator:
        risk = {
            "risk_classification": "skipped_by_operator",
            "risk_reason": "The operator skipped this recording.",
            "recommended_action": "Nothing to do: ignore this recording.",
        }
    elif no_narration and detected_no_narration:
        risk = {
            "risk_classification": "no_narration_found",
            "risk_reason": f"No narration was found. {detection_said or 'No audio track carries clear speech.'}",
            "recommended_action": (
                "If you spoke during this recording, choose its voice track in Find my bug reports "
                "(Fix and continue). If you did not, nothing needs to be done."
            ),
        }
    elif no_narration:
        risk = {
            "risk_classification": "no_narration_found",
            "risk_reason": "No narration was found on the selected microphone track.",
            "recommended_action": (
                "Check that the right microphone track was used for this recording. "
                "If you did not speak during it, nothing needs to be done."
            ),
        }
    else:
        risk = _classify_transcript_quality_risk(
            warning_reasons=[] if appears_usable else warning_reasons,
            duration_seconds=duration_seconds,
            word_count=word_count,
            total_marker_count=total_marker_count,
        )
    if quality_status == "usable_with_warnings":
        risk["risk_reason"] = "Transcript passed blocking quality checks with non-blocking warnings."
        risk["recommended_action"] = "Review the recorded warnings during normal candidate review."
    return {
        "transcript_text_length": len(text),
        "word_count": word_count,
        "unique_word_count": unique_word_count,
        "unique_word_ratio": round(unique_word_ratio, 4),
        "words_per_minute": round(words_per_minute, 3),
        "top_repeated_words": top_repeated_words,
        "dominant_word": dominant_word["word"],
        "dominant_word_count": int(dominant_word["count"]),
        "dominant_word_ratio": round(dominant_word_ratio, 4),
        "ticket_marker_counts": marker_counts,
        "total_marker_count": total_marker_count,
        "appears_usable": appears_usable,
        "warning_reasons": warning_reasons,
        "quality_status": quality_status,
        **repetition,
        **language,
        **gibberish,
        **silence,
        **game_audio,
        **risk,
    }


def _normalize_audio_stream_entry(stream: Any, index: int) -> dict[str, Any] | None:
    if isinstance(stream, dict):
        data = stream
    elif hasattr(stream, "items"):
        data = dict(stream.items())
    else:
        return None
    return {
        "ordinal": _coerce_int(data.get("ordinal"), index),
        "ffmpeg_map": _safe_text(data.get("ffmpeg_map")) or f"0:a:{index}",
        "stream_index": _coerce_int(data.get("stream_index"), index),
        "codec_name": _safe_text(data.get("codec_name")),
        "channels": _coerce_int(data.get("channels"), 0),
        "channel_layout": _safe_text(data.get("channel_layout")),
        "language": _safe_text(data.get("language")),
        "title": _safe_text(data.get("title")),
    }


def _normalize_audio_streams(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict) or hasattr(value, "items"):
        raw_streams = [value]
    elif isinstance(value, str):
        raw_streams = []
    else:
        raw_streams = list(value or [])
    streams: list[dict[str, Any]] = []
    for index, stream in enumerate(raw_streams):
        normalized = _normalize_audio_stream_entry(stream, index)
        if normalized is not None:
            streams.append(normalized)
    return streams


def _normalize_selected_audio_stream(value: Any) -> dict[str, Any]:
    # No stream recorded means none was chosen; an empty value must not
    # become a made-up stream with the default map 0:a:0.
    if not value:
        return {}
    streams = _normalize_audio_streams(value)
    return streams[0] if streams else {}


def _audio_stream_selection_status(
    selected_audio_stream: dict[str, Any], confirmed: bool, confirmation_source: str
) -> str:
    """Who chose the transcribed track, as the package reports it."""

    if not selected_audio_stream:
        return "not_chosen"
    if not confirmed:
        return "uncertain"
    if confirmation_source.lower().startswith("automatic voice detection"):
        return "automatic"
    return "operator_selected"


def _normalize_source(
    source: dict[str, Any],
    quality_marker_terms: list[str] | tuple[str, ...] = QUALITY_MARKER_TERMS,
    glossary_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    audio_streams = _normalize_audio_streams(source.get("audio_streams") or [])
    selected_audio_stream = _normalize_selected_audio_stream(source.get("selected_audio_stream") or {})
    selected_audio_stream_index = _coerce_int(source.get("selected_audio_stream_index"), 0)
    selection_confirmed = _coerce_bool(source.get("audio_stream_selection_confirmed"), False)
    confirmation_source = _safe_text(source.get("audio_stream_confirmation_source"))
    # Without a selected stream the index is only the usual track the run
    # started from, so no stream is the operator's narration.
    for stream in audio_streams:
        stream["role"] = (
            "operator_narration"
            if selected_audio_stream
            and _coerce_int(stream.get("ordinal"), -1) == selected_audio_stream_index
            else "supporting_audio"
        )
    if selected_audio_stream:
        selected_audio_stream["role"] = "operator_narration"
    # 196: a skipped recording's transcript is never read, whenever it was
    # skipped and whatever an earlier run left of it, so none of its words
    # reach candidates, timelines, the marker audit or the transcript files.
    skipped_by_operator = _skipped_by_operator(source)
    transcript_payload = (
        {} if skipped_by_operator else _read_transcript_payload(_safe_text(source.get("transcript_json_path")))
    )
    normalized = {
        "source_id": _safe_text(source.get("source_id")),
        "physical_source_id": _safe_text(source.get("physical_source_id")),
        "physical_source_id_shortened": _coerce_bool(
            source.get("physical_source_id_shortened"), False
        ),
        "source_identifier": _safe_text(source.get("source_identifier")),
        "source_path": _safe_text(source.get("source_path")),
        "source_filename": _safe_text(source.get("source_filename")),
        "duration_seconds": _coerce_float(source.get("duration_seconds"), 0.0),
        "status": _safe_text(source.get("status")),
        "error_message": _safe_text(source.get("error_message")),
        "audio_path": _safe_text(source.get("audio_path")),
        "audio_status": _safe_text(source.get("audio_status")),
        "audio_error_message": _safe_text(source.get("audio_error_message")),
        "audio_method": _safe_text(source.get("audio_method")),
        "audio_stream_count": _coerce_int(source.get("audio_stream_count"), len(audio_streams)),
        "audio_streams": audio_streams,
        "selected_audio_stream_index": selected_audio_stream_index,
        "selected_audio_stream": selected_audio_stream,
        "audio_stream_selection_confirmed": selection_confirmed,
        "audio_stream_selection_status": _audio_stream_selection_status(
            selected_audio_stream, selection_confirmed, confirmation_source
        ),
        "audio_stream_confirmation_source": confirmation_source,
        "narration_speech_mode": _safe_text(source.get("narration_speech_mode")),
        "transcript_audio_role": _safe_text(source.get("transcript_audio_role")) or "operator_narration",
        "transcription_input_path": _safe_text(source.get("transcription_input_path")),
        "transcription_input_method": _safe_text(source.get("transcription_input_method")),
        "transcript_reuse_status": _safe_text(source.get("transcript_reuse_status")),
        "reused_transcript_json_path": _safe_text(source.get("reused_transcript_json_path")),
        "reused_transcript_srt_path": _safe_text(source.get("reused_transcript_srt_path")),
        "reused_transcript_txt_path": _safe_text(source.get("reused_transcript_txt_path")),
        "raw_video_transcription_used": bool(source.get("raw_video_transcription_used")),
        "transcript_json_path": _safe_text(source.get("transcript_json_path")),
        "transcript_srt_path": _safe_text(source.get("transcript_srt_path")),
        "transcript_txt_path": _safe_text(source.get("transcript_txt_path")),
        "transcript_language": _safe_text(
            source.get("transcript_language") or transcript_payload.get("language")
        ),
    }
    embedded_raw = source.get("raw_segments")
    embedded_segments = source.get("segments")
    if skipped_by_operator:
        raw_segments = []
    elif embedded_raw:
        raw_segments = _normalize_transcript_segments(embedded_raw)
    elif embedded_segments and source.get("transcript_corrections"):
        raw_segments = _normalize_transcript_segments(
            [
                {**dict(segment), "text": segment.get("raw_text") or segment.get("text")}
                for segment in embedded_segments
                if isinstance(segment, dict)
            ]
        )
    else:
        raw_segments = _read_transcript_segments(
            _whisper_transcript_path(normalized["transcript_json_path"])
        )
    corrected_segments, correction_records = correct_segments(
        raw_segments,
        glossary_entries or [],
        source_id=normalized["source_id"],
        source_filename=normalized["source_filename"],
    )
    normalized["raw_segments"] = raw_segments
    normalized["segments"] = corrected_segments
    normalized["transcript_corrections"] = correction_records
    normalized["transcript_correction_count"] = sum(
        int(record.get("replacement_count") or 0) for record in correction_records
    )
    normalized["transcript_quality"] = _build_transcript_quality(normalized, quality_marker_terms)
    return normalized


def _normalize_repo_hint_mode(value: Any) -> str:
    mode = _safe_text(value).lower()
    return mode if mode in REPO_HINT_MODES else "auto"


def _normalize_repo_name(value: Any) -> str:
    text = _safe_text(value).strip().strip("/")
    if not text or text.upper() == REPO_HINT_UNKNOWN:
        return ""
    return text


def _repo_hint_candidate_paths() -> list[Path]:
    return [
        Path.cwd() / "config" / "evidence_repo_hints.json",
        Path.cwd() / "evidence_repo_hints.json",
    ]


def _normalize_repo_keywords(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_keywords = [value]
    else:
        raw_keywords = list(value or [])
    keywords: list[str] = []
    seen: set[str] = set()
    for keyword in raw_keywords:
        text = _safe_text(keyword)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        keywords.append(text)
    return keywords


def _load_repo_hint_map(path_value: Any) -> dict[str, Any]:
    explicit_path = _safe_text(path_value)
    warnings: list[str] = []
    candidate_paths = [Path(explicit_path)] if explicit_path else [
        path for path in _repo_hint_candidate_paths() if path.exists()
    ]
    if not candidate_paths:
        return {
            "repos": {},
            "repo_map_path": "",
            "repo_map_loaded": False,
            "repo_map_error": "",
            "warnings": [],
        }

    raw_path = candidate_paths[0].expanduser()
    path = raw_path if raw_path.is_absolute() else (Path.cwd() / raw_path)
    try:
        path = path.resolve()
    except OSError:
        path = path.absolute()

    if not path.exists():
        warnings.append(f"Repo hint map not found: {path}")
        return {
            "repos": {},
            "repo_map_path": str(path),
            "repo_map_loaded": False,
            "repo_map_error": warnings[-1],
            "warnings": warnings,
        }

    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001 - map errors should be warning-only.
        warnings.append(f"Repo hint map could not be loaded: {path} ({exc})")
        return {
            "repos": {},
            "repo_map_path": str(path),
            "repo_map_loaded": False,
            "repo_map_error": warnings[-1],
            "warnings": warnings,
        }

    repos_payload = payload.get("repos") if isinstance(payload, dict) else None
    if not isinstance(repos_payload, dict):
        warnings.append(f"Repo hint map has no usable 'repos' object: {path}")
        return {
            "repos": {},
            "repo_map_path": str(path),
            "repo_map_loaded": False,
            "repo_map_error": warnings[-1],
            "warnings": warnings,
        }

    repos: dict[str, dict[str, Any]] = {}
    for repo_name, entry in repos_payload.items():
        normalized_repo = _normalize_repo_name(repo_name)
        if not normalized_repo:
            continue
        entry_data = entry if isinstance(entry, dict) else {}
        keywords = _normalize_repo_keywords(entry_data.get("keywords") if entry_data else [])
        repos[normalized_repo] = {
            "project_label": _safe_text(entry_data.get("project_label") if entry_data else ""),
            "keywords": keywords,
        }

    if not repos:
        warnings.append(f"Repo hint map loaded but contained no usable repo entries: {path}")

    return {
        "repos": repos,
        "repo_map_path": str(path),
        "repo_map_loaded": bool(repos),
        "repo_map_error": "",
        "warnings": warnings,
    }


def _configured_projects(configuration: dict[str, Any]) -> dict[str, Any]:
    """The operator's project map for the agent prompt.

    At write time the repo-map settings live under ``repo_hinting``; reading
    only the top level silently dropped the whole project list (94).
    """

    hinting = configuration.get("repo_hinting") or {}
    payload = {
        "repo_hint_mode": hinting.get("mode") or configuration.get("repo_hint_mode"),
        "repo_map_path": hinting.get("repo_map_path") or configuration.get("repo_map_path"),
        "target_repo": hinting.get("target_repo") or configuration.get("target_repo"),
    }
    return _build_repo_hint_context(payload).get("repos") or {}


def _build_repo_hint_context(payload: dict[str, Any]) -> dict[str, Any]:
    mode = _normalize_repo_hint_mode(payload.get("repo_hint_mode"))
    target_repo = _normalize_repo_name(payload.get("target_repo") or payload.get("evidence_target_repo"))
    map_result = (
        {"repos": {}, "repo_map_path": "", "repo_map_loaded": False, "repo_map_error": "", "warnings": []}
        if mode in {"off", "target-only"}
        else _load_repo_hint_map(payload.get("repo_map_path") or payload.get("evidence_repo_map_path"))
    )
    return {
        "mode": mode,
        "target_repo": target_repo,
        "repos": map_result.get("repos", {}),
        "repo_map_path": _safe_text(map_result.get("repo_map_path")),
        "repo_map_loaded": bool(map_result.get("repo_map_loaded")),
        "repo_map_error": _safe_text(map_result.get("repo_map_error")),
        "warnings": list(map_result.get("warnings") or []),
    }


def _public_repo_hint_config(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": context.get("mode", "auto"),
        "target_repo": context.get("target_repo", ""),
        "target_repo_override": context.get("target_repo", ""),
        "repo_map_path": context.get("repo_map_path", ""),
        "repo_map_loaded": bool(context.get("repo_map_loaded")),
        "repo_map_repo_count": len(context.get("repos") or {}),
        "repo_map_error": context.get("repo_map_error", ""),
        "warnings": list(context.get("warnings") or []),
        "review_warning": REPO_HINT_REVIEW_WARNING,
    }


# Run metadata the operator types about the project itself. Everything else
# in run metadata (profile name, app version) is the tool describing itself;
# scoring it routed ordinary narration to this repository (109).
REPO_HINT_OPERATOR_METADATA_KEYS = ("target_project", "target_repository", "test_conditions")


def _candidate_repo_hint_text(candidate: dict[str, Any]) -> str:
    """Only what the operator said or typed; never file names or tool text."""

    run_metadata = candidate.get("run_metadata") or {}
    parts: list[str] = [
        candidate.get("suggested_issue_title", ""),
        candidate.get("transcript_excerpt", ""),
        *(run_metadata.get(key, "") for key in REPO_HINT_OPERATOR_METADATA_KEYS),
        " ".join(candidate.get("detected_marker_phrases", []) or []),
        " ".join(candidate.get("supporting_marker_phrases", []) or []),
    ]
    for event in candidate.get("marker_events", []) or []:
        parts.append(event.get("segment_text", ""))
        parts.append(" ".join(event.get("detected_marker_phrases", []) or []))
    return "\n".join(_safe_text(part) for part in parts if _safe_text(part))


def _keyword_match_count(text: str, keyword: str) -> int:
    normalized_text = _normalize_marker_text(text)
    normalized_keyword = re.sub(r"\s+", " ", _normalize_marker_text(keyword)).strip()
    if not normalized_text or not normalized_keyword:
        return 0
    if re.search(r"[a-z0-9]", normalized_keyword):
        pattern = r"(?<![A-Za-z0-9])" + r"\s+".join(
            re.escape(part) for part in normalized_keyword.split()
        ) + r"(?![A-Za-z0-9])"
        return len(re.findall(pattern, normalized_text, flags=re.IGNORECASE))
    return normalized_text.count(normalized_keyword)


def _score_repo_map(candidate: dict[str, Any], repos: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    text = _candidate_repo_hint_text(candidate)
    scored: list[dict[str, Any]] = []
    for repo_name, entry in repos.items():
        matched_keywords: list[dict[str, Any]] = []
        score = 0
        for keyword in entry.get("keywords", []) or []:
            count = _keyword_match_count(text, keyword)
            if count <= 0:
                continue
            keyword_word_count = max(1, len(_word_tokens(keyword)))
            weight = 3 if keyword_word_count > 1 else 1
            keyword_score = count * weight
            score += keyword_score
            matched_keywords.append(
                {
                    "keyword": keyword,
                    "count": count,
                    "score": keyword_score,
                }
            )
        if score > 0:
            scored.append(
                {
                    "repo": repo_name,
                    "target_project_label": entry.get("project_label", ""),
                    "score": score,
                    "matched_keywords": matched_keywords,
                    "reason": ", ".join(
                        f"{item['keyword']} x{item['count']}" for item in matched_keywords
                    ),
                }
            )
    return sorted(scored, key=lambda item: (-_coerce_int(item.get("score")), item.get("repo", "")))


def _repo_confidence_from_scores(top: dict[str, Any], second: dict[str, Any] | None) -> str:
    top_score = _coerce_int(top.get("score"))
    second_score = _coerce_int(second.get("score")) if second else 0
    match_count = sum(_coerce_int(item.get("count")) for item in top.get("matched_keywords", []))
    clear_lead = second_score == 0 or top_score >= second_score + 2
    if top_score >= 4 and match_count >= 2 and clear_lead:
        return "high"
    if top_score >= 2 and top_score > second_score:
        return "medium"
    return "low"


def _repo_project_label(repo_name: str, context: dict[str, Any]) -> str:
    repos = context.get("repos") or {}
    return _safe_text((repos.get(repo_name) or {}).get("project_label"))


def _set_unknown_repo_hint(candidate: dict[str, Any], reason: str, source: str = "none") -> None:
    candidate.update(
        {
            "likely_target_repo": REPO_HINT_UNKNOWN,
            "repo_confidence": "unknown",
            "repo_hint_reason": [reason],
            "alternate_repos": [],
            "requires_github_review": True,
            "repo_hint_source": source,
            "target_project_label": "",
            "repo_hint_is_ambiguous": False,
            "repo_hint_review_note": REPO_HINT_REVIEW_WARNING,
        }
    )


def _apply_repo_hints(candidates: list[dict[str, Any]], context: dict[str, Any]) -> None:
    mode = context.get("mode", "auto")
    target_repo = context.get("target_repo", "")
    repos = context.get("repos") or {}
    for candidate in candidates:
        if mode == "off":
            _set_unknown_repo_hint(candidate, "Repo hinting disabled by EvidenceRepoHintMode=off.")
            continue

        scores = _score_repo_map(candidate, repos) if mode == "auto" and repos else []
        if target_repo:
            alternates = [score for score in scores if score.get("repo") != target_repo]
            reason = [f"Operator-specified target repo: {target_repo}"]
            target_score = next((score for score in scores if score.get("repo") == target_repo), None)
            if target_score:
                reason.append(f"Repo map also matched: {target_score.get('reason')}")
            candidate.update(
                {
                    "likely_target_repo": target_repo,
                    "repo_confidence": "operator_specified",
                    "repo_hint_reason": reason,
                    "alternate_repos": alternates,
                    "requires_github_review": True,
                    "repo_hint_source": "operator_target",
                    "target_project_label": _repo_project_label(target_repo, context),
                    "repo_hint_is_ambiguous": False,
                    "repo_hint_review_note": REPO_HINT_REVIEW_WARNING,
                }
            )
            continue

        if mode == "target-only":
            _set_unknown_repo_hint(
                candidate,
                "EvidenceRepoHintMode=target-only but no EvidenceTargetRepo was provided.",
            )
            continue

        if not scores:
            reason = "No EvidenceTargetRepo or repo-map keyword match was available."
            if context.get("warnings"):
                reason = "; ".join(context.get("warnings") or [reason])
            _set_unknown_repo_hint(candidate, reason)
            continue

        top = scores[0]
        second = scores[1] if len(scores) > 1 else None
        ambiguous = bool(second and _coerce_int(top.get("score")) <= _coerce_int(second.get("score")) + 1)
        candidate.update(
            {
                "likely_target_repo": top.get("repo") or REPO_HINT_UNKNOWN,
                "repo_confidence": _repo_confidence_from_scores(top, second),
                "repo_hint_reason": [
                    f"Matched repo-map keywords: {top.get('reason') or 'none'}",
                ],
                "alternate_repos": scores[1:],
                "requires_github_review": True,
                "repo_hint_source": "repo_map",
                "target_project_label": top.get("target_project_label", ""),
                "repo_hint_is_ambiguous": ambiguous,
                "repo_hint_review_note": REPO_HINT_REVIEW_WARNING,
            }
        )


def _ensure_repo_hint_fields(candidates: list[dict[str, Any]]) -> None:
    for candidate in candidates:
        if "likely_target_repo" not in candidate:
            _set_unknown_repo_hint(candidate, "Repo hint fields were not present in the incoming candidate payload.")
        else:
            candidate["requires_github_review"] = True
            candidate["repo_hint_review_note"] = candidate.get("repo_hint_review_note") or REPO_HINT_REVIEW_WARNING


def _repo_hint_summary(candidates: list[dict[str, Any]], configuration: dict[str, Any]) -> dict[str, Any]:
    target_counts: dict[str, int] = {}
    confidence_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    for candidate in candidates:
        repo = candidate.get("likely_target_repo") or REPO_HINT_UNKNOWN
        confidence = candidate.get("repo_confidence") or "unknown"
        source = candidate.get("repo_hint_source") or "none"
        target_counts[repo] = target_counts.get(repo, 0) + 1
        confidence_counts[confidence] = confidence_counts.get(confidence, 0) + 1
        source_counts[source] = source_counts.get(source, 0) + 1
    return {
        "review_warning": REPO_HINT_REVIEW_WARNING,
        "candidate_count": len(candidates),
        "requires_github_review_count": sum(1 for candidate in candidates if candidate.get("requires_github_review")),
        "unknown_candidate_count": sum(
            1 for candidate in candidates if candidate.get("likely_target_repo") == REPO_HINT_UNKNOWN
        ),
        "ambiguous_candidate_count": sum(1 for candidate in candidates if candidate.get("repo_hint_is_ambiguous")),
        "target_repo_counts": target_counts,
        "confidence_counts": confidence_counts,
        "source_counts": source_counts,
        "repo_hinting": dict(configuration.get("repo_hinting") or {}),
    }


def _phrase_pattern(normalized_phrase: str) -> str:
    """A marker phrase as whole words (151).

    Phrases used to match anywhere inside the text, so "there's a ticket" counted as "here's a
    ticket" and "racetrack this" as "track this". A phrase of several words may still end in a
    plural ("new features"); a single word matches exactly, as before, because the lists hold both
    "ticket" and "tickets".
    """

    start = r"(?<![A-Za-z0-9])" if normalized_phrase[:1].isalnum() else ""
    plural = "s?" if " " in normalized_phrase else ""
    end = plural + r"(?![A-Za-z0-9])" if normalized_phrase[-1:].isalnum() else ""
    return start + re.escape(normalized_phrase) + end


def _phrase_occurs(text: Any, phrase: Any) -> bool:
    normalized_text = _normalize_marker_text(text)
    normalized_phrase = _normalize_marker_text(phrase)
    if not normalized_text or not normalized_phrase:
        return False
    return re.search(_phrase_pattern(normalized_phrase), normalized_text, flags=re.IGNORECASE) is not None


def _matching_control_phrases(text: Any, phrases: tuple[str, ...]) -> list[str]:
    return [phrase for phrase in phrases if _phrase_occurs(text, phrase)]


# 199: "Ticket." or "Bug:" said as a heading at the start of a sentence announces a request, the
# way "Ticket. Put the dashboards at the top of the menu" does. Inside a sentence ("the ticket
# price", "that corner was a bug") the same word is only a mention.
HEADING_REQUEST = re.compile(
    r"(?:^|[.!?]\s+)(?:new\s+)?(ticket|bug|issue|task|todo|to-do)\s*[.:!,\u2013\u2014-](?=\s|$)",
    re.IGNORECASE,
)


def _marker_matches(text: str, markers: list[dict[str, str]] = MARKERS) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    seen: set[str] = set()
    heading = HEADING_REQUEST.search(str(text or "").strip())
    if heading:
        phrase = f"{heading.group(1).lower()} (said as a heading)"
        seen.add(phrase)
        matches.append({"phrase": phrase, "confidence": "likely"})
    for marker in markers:
        phrase = marker["phrase"]
        lower_phrase = _normalize_marker_text(phrase)
        if _phrase_occurs(text, phrase) and lower_phrase not in seen:
            seen.add(lower_phrase)
            matches.append({"phrase": phrase, "confidence": marker["confidence"]})
    return matches


def _has_primary_marker(matches: list[dict[str, str]]) -> bool:
    return any(CONFIDENCE_RANK.get(match.get("confidence", ""), 0) >= CONFIDENCE_RANK["weak"] for match in matches)


def find_requests(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """220: the "flag for AI" requests in a transcript, found by the same marker rules Find my bug
    reports uses, one entry per transcript line that carries one: its time, text and phrases."""

    found: list[dict[str, Any]] = []
    for segment in segments or []:
        text = str(segment.get("text") or "").strip()
        matches = _marker_matches(text)
        if text and _has_primary_marker(matches):
            found.append({
                "start": float(segment.get("start") or 0.0),
                "end": float(segment.get("end") or segment.get("start") or 0.0),
                "text": text,
                "phrases": [match["phrase"] for match in matches],
            })
    return found


def _highest_confidence(values: list[str]) -> str:
    primary_values = [value for value in values if CONFIDENCE_RANK.get(value, 0) >= CONFIDENCE_RANK["weak"]]
    if not primary_values:
        return "weak"
    return max(primary_values, key=lambda item: CONFIDENCE_RANK.get(item, 0))


def _clean_title(text: str, fallback: str, markers: list[dict[str, str]] = MARKERS) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip(" .,:;-")
    marker_phrases = sorted(
        (
            marker["phrase"]
            for marker in markers
            if marker.get("confidence") != "supporting" and _word_count(marker.get("phrase", "")) >= 2
        ),
        key=len,
        reverse=True,
    )
    for phrase in marker_phrases:
        cleaned = re.sub(
            r"^(?:please\s+)?" + re.escape(phrase) + r"(?:\s+(?:for|about|that))?\s*",
            "",
            cleaned,
            count=1,
            flags=re.IGNORECASE,
        ).strip(" .,:;-")
    cleaned = re.sub(
        r"^(?:please\s+)?(?:next issue|another issue|another bug|new ticket|next ticket)\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip(" .,:;-")
    cleaned = re.sub(r"^(?:actually,?\s+)?(?:i(?:'m| am) sorry,?\s+)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(?:we\s+)?(?:need|want|would like)\s+to\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,:;-")
    if cleaned.lower().startswith(("for the ", "for a ", "for an ")):
        cleaned = "Fix " + cleaned[4:]
    elif cleaned.lower().startswith("to "):
        cleaned = cleaned[3:]
    if not cleaned:
        cleaned = fallback
    if len(cleaned) > 90:
        cleaned = cleaned[:87].rstrip() + "..."
    return cleaned[0:1].upper() + cleaned[1:]


def _build_candidate_title(
    first_event: dict[str, Any],
    segments: list[dict[str, Any]],
    fallback: str,
    markers: list[dict[str, str]] = MARKERS,
) -> str:
    marker_time = _coerce_float(first_event.get("marker_time"), 0.0)
    first_title = _clean_title(first_event.get("segment_text", ""), "", markers)
    if _word_count(first_title) >= 4:
        return first_title
    for segment in segments:
        if _coerce_float(segment.get("start"), 0.0) + 0.001 < marker_time:
            continue
        title = _clean_title(segment.get("text", ""), "", markers)
        if _word_count(title) >= 4:
            return title
    return fallback


def _segments_in_window(source: dict[str, Any], start: float, end: float) -> list[dict[str, Any]]:
    return [
        segment
        for segment in source.get("segments", [])
        if _coerce_float(segment.get("end")) >= start and _coerce_float(segment.get("start")) <= end
    ]


def _candidate_word_count(segments: list[dict[str, Any]]) -> int:
    return sum(len(re.findall(r"\S+", segment.get("text", ""))) for segment in segments)


def _segment_event_parts(segment: dict[str, Any]) -> list[dict[str, Any]]:
    text = _safe_text(segment.get("text"))
    raw_text = _safe_text(segment.get("raw_text")) or text
    if not text:
        return []
    boundary_pattern = re.compile(
        r"(?<![A-Za-z0-9])(?:"
        + "|".join(
            re.escape(phrase)
            for phrase in sorted(NEW_TICKET_BOUNDARY_PHRASES, key=len, reverse=True)
        )
        + r")(?![A-Za-z0-9])",
        flags=re.IGNORECASE,
    )
    starts = [0]
    starts.extend(match.start() for match in boundary_pattern.finditer(text) if match.start() > 0)
    starts = sorted(set(starts))
    segment_start = _coerce_float(segment.get("start"), 0.0)
    segment_end = max(segment_start, _coerce_float(segment.get("end"), segment_start))
    duration = segment_end - segment_start
    parts: list[dict[str, Any]] = []
    for index, start_index in enumerate(starts):
        end_index = starts[index + 1] if index + 1 < len(starts) else len(text)
        part_text = text[start_index:end_index].strip(" ,.;:-")
        if not part_text:
            continue
        fraction = start_index / max(1, len(text))
        part_start = segment_start + (duration * fraction)
        parts.append(
            {
                **dict(segment),
                "id": f"{segment.get('id')}.{index + 1}" if len(starts) > 1 else segment.get("id"),
                "start": part_start,
                "timestamp_start": _format_timestamp(part_start),
                "text": part_text,
                "raw_segment_text": raw_text,
                "boundary_phrases": _matching_control_phrases(
                    part_text,
                    NEW_TICKET_BOUNDARY_PHRASES,
                ),
            }
        )
    return parts


def _cluster_duplicate_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clustered: list[dict[str, Any]] = []
    for event in sorted(events, key=lambda item: (item["source_id"], item["marker_time"])):
        normalized = _normalized_segment_text(event.get("segment_text"))
        duplicate: dict[str, Any] | None = None
        for prior in reversed(clustered):
            if prior["source_id"] != event["source_id"]:
                continue
            delta = abs(_coerce_float(event.get("marker_time")) - _coerce_float(prior.get("marker_time")))
            if delta > 15.0:
                break
            prior_normalized = _normalized_segment_text(prior.get("segment_text"))
            same = bool(normalized and normalized == prior_normalized)
            near = bool(
                normalized
                and prior_normalized
                and min(len(normalized), len(prior_normalized)) >= 24
                and SequenceMatcher(None, normalized, prior_normalized).ratio() >= 0.94
            )
            if same or near:
                duplicate = prior
                break
        if duplicate is None:
            event["duplicate_occurrences"] = []
            clustered.append(event)
            continue
        duplicate.setdefault("duplicate_occurrences", []).append(
            {
                "segment_id": event.get("segment_id"),
                "marker_time": event.get("marker_time"),
                "marker_timestamp": event.get("marker_timestamp"),
                "segment_text": event.get("segment_text"),
            }
        )
        existing = {
            (_safe_text(match.get("phrase")), _safe_text(match.get("confidence")))
            for match in duplicate.get("matches") or []
        }
        for match in event.get("matches") or []:
            key = (_safe_text(match.get("phrase")), _safe_text(match.get("confidence")))
            if key not in existing:
                duplicate.setdefault("matches", []).append(match)
                existing.add(key)
        duplicate["confidence"] = _highest_confidence(
            [duplicate.get("confidence", "weak"), event.get("confidence", "weak")]
        )
    return clustered


def _build_events(
    sources: list[dict[str, Any]],
    pre_context: float,
    post_context: float,
    markers: list[dict[str, str]] = MARKERS,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for source in sources:
        if source["status"] not in {"completed", "skipped"}:
            continue
        for source_segment in source.get("segments", []):
            for segment in _segment_event_parts(source_segment):
                continuation_phrases = _matching_control_phrases(segment["text"], CONTINUATION_PHRASES)
                closing_phrases = _matching_control_phrases(segment["text"], CLOSING_BOUNDARY_PHRASES)
                new_ticket_phrases = _matching_control_phrases(segment["text"], NEW_TICKET_BOUNDARY_PHRASES)
                if (continuation_phrases or closing_phrases) and not new_ticket_phrases:
                    continue
                matches = _marker_matches(segment["text"], markers)
                if not matches or not _has_primary_marker(matches):
                    continue
                marker_time = _coerce_float(segment.get("start"), 0.0)
                start = max(0.0, marker_time - pre_context)
                end = marker_time + post_context
                if source["duration_seconds"] > 0:
                    end = min(source["duration_seconds"], end)
                end = max(start, end)
                events.append(
                    {
                        "source_id": source["source_id"],
                        "source": source,
                        "start": start,
                        "end": end,
                        "marker_time": marker_time,
                        "marker_timestamp": _format_timestamp(marker_time),
                        "segment_id": segment.get("id"),
                        "segment_text": segment["text"],
                        "raw_segment_text": segment.get("raw_segment_text") or segment.get("raw_text") or segment["text"],
                        "matches": matches,
                        "boundary_phrases": new_ticket_phrases,
                        "confidence": _highest_confidence([match["confidence"] for match in matches]),
                    }
                )
    return _cluster_duplicate_events(events)


MENTIONED_NOT_ASKED_JSON = "MENTIONED_NOT_ASKED.json"
MENTIONED_NOT_ASKED_MARKDOWN = "MENTIONED_NOT_ASKED.md"


def build_mentioned_not_asked(
    sources: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    markers: list[dict[str, str]] = MARKERS,
) -> list[dict[str, Any]]:
    """Moments where the operator said a word like "ticket" or "fix this" without asking for
    anything (199). They never become a ticket, and they are never hidden: each is listed for the
    operator to decide, a remark seconds after a real request included. (Its evidence window does
    not make it part of that request.)"""

    items: list[dict[str, Any]] = []
    for source in sources:
        if source.get("status") not in {"completed", "skipped"}:
            continue
        for source_segment in source.get("segments", []):
            for segment in _segment_event_parts(source_segment):
                continuation_phrases = _matching_control_phrases(segment["text"], CONTINUATION_PHRASES)
                closing_phrases = _matching_control_phrases(segment["text"], CLOSING_BOUNDARY_PHRASES)
                new_ticket_phrases = _matching_control_phrases(segment["text"], NEW_TICKET_BOUNDARY_PHRASES)
                if (continuation_phrases or closing_phrases) and not new_ticket_phrases:
                    continue
                matches = _marker_matches(segment["text"], markers)
                words = [match["phrase"] for match in matches if match.get("confidence") == "mention"]
                if not words or _has_primary_marker(matches):
                    continue
                marker_time = _coerce_float(segment.get("start"), 0.0)
                items.append(
                    {
                        "source_id": source.get("source_id"),
                        "source_filename": source.get("source_filename"),
                        "source_identifier": source.get("source_identifier"),
                        "timestamp_seconds": round(marker_time, 3),
                        "timestamp": _format_timestamp(marker_time),
                        "segment_id": segment.get("id"),
                        "words": words,
                        "text": _safe_text(segment.get("raw_segment_text") or segment["text"]),
                    }
                )
    return items


def _mentioned_not_asked_markdown(items: list[dict[str, Any]]) -> str:
    lines = [
        "# Mentioned, not asked for",
        "",
        'Moments where the operator said a word like "ticket", "bug" or "fix this" without',
        "asking for anything. None of them is a ticket. Show this list with your drafted issues so",
        "the operator decides about each one; never draft or file an issue from it on your own.",
        "",
    ]
    if not items:
        lines.append("Nothing was mentioned without being asked for.")
    for item in items:
        lines.extend(
            [
                f"## {item.get('source_filename') or item.get('source_id')} {item.get('timestamp')}",
                "",
                f"- Words: {', '.join(item.get('words') or [])}",
                "",
                f"> {item.get('text')}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _merge_events(events: list[dict[str, Any]], merge_gap: float) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for event in events:
        if current is not None and _should_merge_event(current, event, merge_gap):
            current["end"] = max(current["end"], event["end"])
            current["events"].append(event)
            continue
        if current is not None:
            windows.append(current)
        current = {
            "source_id": event["source_id"],
            "source": event["source"],
            "start": event["start"],
            "end": event["end"],
            "events": [event],
        }
    if current is not None:
        windows.append(current)
    return windows


def _has_window_hint(event: dict[str, Any], hints: tuple[str, ...]) -> bool:
    text = _normalize_marker_text(event.get("segment_text"))
    return any(_normalize_marker_text(hint) in text for hint in hints)


def _should_merge_event(current: dict[str, Any], event: dict[str, Any], merge_gap: float) -> bool:
    if current["source_id"] != event["source_id"]:
        return False
    previous = (current.get("events") or [{}])[-1]
    marker_gap = _coerce_float(event.get("marker_time")) - _coerce_float(previous.get("marker_time"))
    if marker_gap > merge_gap:
        return False
    if _has_window_hint(event, WINDOW_MERGE_HINTS):
        return True
    if current.get("events") and _has_window_hint(event, WINDOW_SPLIT_HINTS):
        return False
    return marker_gap <= min(45.0, merge_gap)


def _is_boundary_event(event: dict[str, Any]) -> bool:
    if _has_window_hint(event, WINDOW_SPLIT_HINTS):
        return True
    return any(
        _normalize_marker_text(match.get("phrase")) in {_normalize_marker_text(item) for item in WINDOW_SPLIT_HINTS}
        for match in event.get("matches", [])
    )


def _normalize_offsets(value: Any) -> list[float]:
    if value is None:
        return [-60.0, -30.0, 0.0, 30.0, 90.0, 120.0]
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",")]
    else:
        items = list(value)
    offsets = [_coerce_float(item) for item in items if _safe_text(item) != ""]
    return offsets or [-60.0, -30.0, 0.0, 30.0, 90.0, 120.0]


def _clamp_frame_time(frame_time: float, window: dict[str, Any], duration: float) -> float:
    frame_time = max(_coerce_float(window["start"]), min(_coerce_float(window["end"]), frame_time))
    if duration > 0:
        max_frame_time = max(0.0, duration - 0.25)
        frame_time = max(0.0, min(max_frame_time, frame_time))
    return frame_time


def _sample_evenly(values: list[float], limit: int) -> list[float]:
    if limit <= 0:
        return []
    if len(values) <= limit:
        return values
    if limit == 1:
        return [values[0]]
    max_index = len(values) - 1
    selected: list[float] = []
    seen_indexes: set[int] = set()
    for position in range(limit):
        index = int(round(position * max_index / (limit - 1)))
        if index in seen_indexes:
            continue
        seen_indexes.add(index)
        selected.append(values[index])
    return selected


def _build_frame_panel_entries(
    output_dir: Path,
    base_rel: str,
    source_id: str,
    timestamp_text: str,
    panel_crop_mode: str,
    panel_definitions: list[dict[str, Any]] | tuple[dict[str, Any], ...] = THREE_PANEL_DEFINITIONS,
) -> list[dict[str, Any]]:
    if _normalize_panel_crop_mode(panel_crop_mode) == "off":
        return []

    panels: list[dict[str, Any]] = []
    for panel in panel_definitions:
        role = panel["role"]
        panel_rel = f"{base_rel}/frames/panels/{role}/{source_id}_{timestamp_text}_{role}.jpg"
        panels.append(
            {
                **dict(panel),
                "relative_path": panel_rel,
                "path": str(output_dir / panel_rel),
                "status": "pending",
                "error_message": "",
                "panel_image_width": "",
                "panel_image_height": "",
            }
        )
    return panels


def _build_frame_entries(
    *,
    output_dir: Path,
    base_rel: str,
    source: dict[str, Any],
    window: dict[str, Any],
    marker_time: float,
    frame_offsets: list[float],
    frame_cadence_seconds: float,
    max_frames_per_candidate: int,
    panel_crop_mode: str,
    panel_definitions: list[dict[str, Any]] | tuple[dict[str, Any], ...] = THREE_PANEL_DEFINITIONS,
) -> list[dict[str, Any]]:
    frame_entries: list[dict[str, Any]] = []
    seen_frame_times: set[int] = set()
    duration = _coerce_float(source.get("duration_seconds"), 0.0)
    max_frames = max(0, max_frames_per_candidate)
    normalized_panel_crop_mode = _normalize_panel_crop_mode(panel_crop_mode)

    def add_frame(frame_time: float, role: str, offset: float | None = None) -> None:
        if max_frames > 0 and len(frame_entries) >= max_frames:
            return
        clamped = _clamp_frame_time(frame_time, window, duration)
        frame_key = int(round(clamped * 1000))
        if frame_key in seen_frame_times:
            return
        seen_frame_times.add(frame_key)
        timestamp_text = _format_filename_timestamp(clamped)
        frame_rel = f"{base_rel}/frames/full/{source['source_id']}_{timestamp_text}.jpg"
        frame_entries.append(
            {
                "artifact_id": _artifact_identity("frame", source["source_id"], f"{frame_key}ms"),
                "timestamp_seconds": round(clamped, 3),
                "timestamp": _format_timestamp(clamped),
                "offset_seconds": offset,
                "role": role,
                "relative_path": frame_rel,
                "path": str(output_dir / frame_rel),
                "full_frame_relative_path": frame_rel,
                "full_frame_path": str(output_dir / frame_rel),
                "full_frame_width": "",
                "full_frame_height": "",
                "panel_crop_mode": normalized_panel_crop_mode,
                "panel_detection": "disabled" if normalized_panel_crop_mode == "off" else "pending",
                "panels": _build_frame_panel_entries(
                    output_dir,
                    base_rel,
                    source["source_id"],
                    timestamp_text,
                    normalized_panel_crop_mode,
                    panel_definitions,
                ),
                "status": "pending",
                "error_message": "",
            }
        )

    for offset in frame_offsets:
        add_frame(marker_time + offset, "offset", offset)

    if max_frames == 0 or frame_cadence_seconds <= 0:
        return frame_entries

    remaining = max_frames - len(frame_entries)
    if remaining <= 0:
        return frame_entries

    start = _coerce_float(window["start"])
    end = _coerce_float(window["end"])
    if end < start:
        return frame_entries
    cadence_times: list[float] = []
    current = start
    while current <= end + 0.001:
        cadence_times.append(current)
        current += frame_cadence_seconds
    if not cadence_times or abs(cadence_times[-1] - end) > 0.5:
        cadence_times.append(end)
    for frame_time in _sample_evenly(cadence_times, remaining):
        add_frame(frame_time, "cadence", None)
    return sorted(frame_entries, key=lambda item: item["timestamp_seconds"])


def _canonicalize_source_artifacts(
    candidates: list[dict[str, Any]],
    output_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Move repeated visual/audio requests into a source-level artifact index."""
    frame_registry: dict[tuple[str, int], dict[str, Any]] = {}
    frame_tasks: list[dict[str, Any]] = []
    audio_registry: dict[tuple[str, int, int, int], dict[str, Any]] = {}
    audio_tasks: list[dict[str, Any]] = []

    for candidate in candidates:
        source_id = _safe_text(candidate.get("source_id")) or "source"
        source_path = _safe_text(candidate.get("source_path"))
        compact_source = _compact_artifact_source_token(source_id)
        canonical_frames: list[dict[str, Any]] = []
        for frame in candidate.get("frames") or []:
            timestamp_seconds = round(_coerce_float(frame.get("timestamp_seconds")), 3)
            key = (source_id, int(round(timestamp_seconds * 1000)))
            canonical = frame_registry.get(key)
            if canonical is None:
                timestamp_text = _format_filename_timestamp(timestamp_seconds)
                timestamp_ms = int(round(timestamp_seconds * 1000))
                logical_relative_path = (
                    f"artifacts/sources/{source_id}/frames/full/"
                    f"{source_id}_{timestamp_text}.jpg"
                )
                relative_path, physical_path_shortened = _bounded_artifact_relative_path(
                    output_dir,
                    logical_relative_path,
                    f"artifacts/sources/{compact_source}/f/f-{timestamp_text}.jpg",
                )
                canonical = {
                    **dict(frame),
                    "artifact_id": _artifact_identity("frame", source_id, f"{timestamp_ms}ms"),
                    "logical_relative_path": logical_relative_path,
                    "physical_path_shortened": physical_path_shortened,
                    "relative_path": relative_path,
                    "path": str(output_dir / relative_path),
                    "full_frame_relative_path": relative_path,
                    "full_frame_path": str(output_dir / relative_path),
                    "canonical_source_artifact": True,
                    "panels": [],
                }
                for panel in frame.get("panels") or []:
                    role = _safe_text(panel.get("role")) or "panel"
                    logical_panel_relative = (
                        f"artifacts/sources/{source_id}/frames/panels/{role}/"
                        f"{source_id}_{timestamp_text}_{role}.jpg"
                    )
                    compact_role = _compact_artifact_role(role)
                    panel_relative, panel_path_shortened = _bounded_artifact_relative_path(
                        output_dir,
                        logical_panel_relative,
                        (
                            f"artifacts/sources/{compact_source}/p/{compact_role}/"
                            f"p-{timestamp_text}-{compact_role}.jpg"
                        ),
                    )
                    canonical["panels"].append(
                        {
                            **dict(panel),
                            "artifact_id": _artifact_identity(
                                "panel", source_id, f"{timestamp_ms}ms", role
                            ),
                            "logical_relative_path": logical_panel_relative,
                            "physical_path_shortened": panel_path_shortened,
                            "relative_path": panel_relative,
                            "path": str(output_dir / panel_relative),
                        }
                    )
                frame_registry[key] = canonical
                frame_tasks.append(
                    {
                        "evidence_id": candidate["evidence_id"],
                        "source_id": source_id,
                        "source_path": source_path,
                        **canonical,
                    }
                )
            panel_references: list[dict[str, Any]] = []
            for legacy_panel, canonical_panel in zip(
                frame.get("panels") or [], canonical.get("panels") or []
            ):
                panel_references.append(
                    {
                        **dict(legacy_panel),
                        "artifact_id": canonical_panel["artifact_id"],
                        "legacy_relative_path": legacy_panel.get("relative_path", ""),
                        "legacy_v092_relative_path": _v092_artifact_path_alias(
                            legacy_panel.get("relative_path", "")
                        ),
                        "path": canonical_panel["path"],
                        "logical_relative_path": canonical_panel[
                            "logical_relative_path"
                        ],
                        "physical_path_shortened": canonical_panel[
                            "physical_path_shortened"
                        ],
                        "relative_path": canonical_panel["relative_path"],
                        "canonical_source_relative_path": canonical_panel["relative_path"],
                        "canonical_source_artifact": True,
                    }
                )
            canonical_frames.append(
                {
                    **dict(frame),
                    "artifact_id": canonical["artifact_id"],
                    "legacy_relative_path": frame.get("relative_path", ""),
                    "legacy_v092_relative_path": _v092_artifact_path_alias(
                        frame.get("relative_path", "")
                    ),
                    "legacy_full_frame_relative_path": frame.get(
                        "full_frame_relative_path", ""
                    ),
                    "path": canonical["path"],
                    "logical_relative_path": canonical["logical_relative_path"],
                    "physical_path_shortened": canonical[
                        "physical_path_shortened"
                    ],
                    "relative_path": canonical["relative_path"],
                    "full_frame_path": canonical["full_frame_path"],
                    "full_frame_relative_path": canonical["full_frame_relative_path"],
                    "canonical_source_relative_path": canonical["relative_path"],
                    "canonical_source_artifact": True,
                    "referenced_by_evidence_id": candidate["evidence_id"],
                    "panels": panel_references,
                }
            )
        candidate["frames"] = canonical_frames

        snippets = [
            candidate.get("audio_snippet") or {},
            *(candidate.get("supporting_audio_snippets") or []),
        ]
        for snippet in snippets:
            if snippet.get("status") != "pending":
                continue
            audio_ordinal = _coerce_int(snippet.get("audio_stream_index"), 0)
            start_seconds = round(_coerce_float(snippet.get("start_seconds")), 3)
            duration_seconds = round(_coerce_float(snippet.get("duration_seconds")), 3)
            key = (
                source_id,
                audio_ordinal,
                int(round(start_seconds * 1000)),
                int(round(duration_seconds * 1000)),
            )
            existing = audio_registry.get(key)
            if existing is not None:
                snippet["legacy_relative_path"] = snippet.get("relative_path", "")
                snippet["artifact_id"] = existing["artifact_id"]
                snippet["path"] = existing["path"]
                snippet["logical_relative_path"] = existing[
                    "logical_relative_path"
                ]
                snippet["physical_path_shortened"] = existing[
                    "physical_path_shortened"
                ]
                snippet["relative_path"] = existing["relative_path"]
                snippet["canonical_source_relative_path"] = existing["relative_path"]
                snippet["canonical_source_artifact"] = True
                continue
            start_text = _format_filename_timestamp(start_seconds)
            start_ms = int(round(start_seconds * 1000))
            duration_ms = int(round(duration_seconds * 1000))
            logical_relative_path = (
                f"artifacts/sources/{source_id}/audio/"
                f"{source_id}_{start_text}_{duration_ms}ms_a{audio_ordinal}.mp3"
            )
            relative_path, physical_path_shortened = _bounded_artifact_relative_path(
                output_dir,
                logical_relative_path,
                (
                    f"artifacts/sources/{compact_source}/a/"
                    f"a-{start_text}-{duration_ms}ms-a{audio_ordinal}.mp3"
                ),
            )
            snippet.update(
                {
                    "legacy_relative_path": snippet.get("relative_path", ""),
                    "artifact_id": _artifact_identity(
                        "audio", source_id, f"{start_ms}ms", f"{duration_ms}ms", f"a{audio_ordinal}"
                    ),
                    "logical_relative_path": logical_relative_path,
                    "physical_path_shortened": physical_path_shortened,
                    "path": str(output_dir / relative_path),
                    "relative_path": relative_path,
                    "canonical_source_relative_path": relative_path,
                    "canonical_source_artifact": True,
                }
            )
            task = {
                "evidence_id": candidate["evidence_id"],
                "source_id": source_id,
                "source_path": source_path,
                "audio_input_path": snippet.get("input_path")
                or candidate.get("audio_input_path", ""),
                **snippet,
                "relative_path": relative_path,
            }
            audio_registry[key] = task
            audio_tasks.append(task)
    return frame_tasks, audio_tasks


def _canonical_source_key(candidate: dict[str, Any]) -> str:
    stem = Path(_safe_text(candidate.get("source_filename")) or _safe_text(candidate.get("source_path"))).stem
    return re.sub(r"[^a-z0-9]+", "", stem.lower())


def _excerpt_fingerprint(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    sample = " ".join(normalized.split()[:80])
    return hashlib.sha1(sample.encode("utf-8")).hexdigest()[:12] if sample else ""


def _annotate_duplicate_candidates(candidates: list[dict[str, Any]]) -> None:
    representatives: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate["canonical_source_key"] = _canonical_source_key(candidate)
        candidate["transcript_excerpt_fingerprint"] = _excerpt_fingerprint(candidate.get("transcript_excerpt", ""))
        candidate["duplicate_role"] = "primary"
        candidate["duplicate_of"] = ""
        candidate["duplicate_group_id"] = candidate["evidence_id"]
        candidate["supporting_duplicate_evidence_ids"] = []

        duplicate_of: dict[str, Any] | None = None
        for representative in representatives:
            same_source_family = (
                candidate["canonical_source_key"]
                and candidate["canonical_source_key"] == representative.get("canonical_source_key")
            )
            nearby_marker = abs(
                _coerce_float(candidate.get("marker_timestamp_seconds"))
                - _coerce_float(representative.get("marker_timestamp_seconds"))
            ) <= 5.0
            same_excerpt = (
                candidate["transcript_excerpt_fingerprint"]
                and candidate["transcript_excerpt_fingerprint"]
                == representative.get("transcript_excerpt_fingerprint")
            )
            if (same_source_family and nearby_marker) or same_excerpt:
                duplicate_of = representative
                break

        if duplicate_of is None:
            representatives.append(candidate)
            continue

        candidate["duplicate_role"] = "supporting_duplicate"
        candidate["duplicate_of"] = duplicate_of["evidence_id"]
        candidate["duplicate_group_id"] = duplicate_of["duplicate_group_id"]
        duplicate_of.setdefault("supporting_duplicate_evidence_ids", []).append(candidate["evidence_id"])


def _normalize_candidate_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_values = re.split(r"[,;\r\n]+", value)
    else:
        raw_values = list(value or [])
    values: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        candidate_id = _safe_text(raw_value)
        if not candidate_id or candidate_id in seen:
            continue
        values.append(candidate_id)
        seen.add(candidate_id)
    return values


_NEGATIVE_OUTCOME_PATTERNS = (
    r"\bno other (?:issues?|bugs?|tickets?)\b",
    r"\bnothing else\b",
    r"\bno more (?:issues?|bugs?|tickets?)\b",
)
_SETUP_OUTCOME_PATTERNS = (
    r"\b(?:i am|i'm|we are|we're) (?:going|about) to (?:talk|describe|cover|list|observe|tell)\b",
    r"\bstart talking about\b",
    r"\bwant to talk about\b",
)
_CORRECTION_OUTCOME_PATTERNS = (
    r"\bscratch that\b",
    r"\bcorrection\b",
    r"\bi mean\b",
    r"\bnot (?:a )?fix\b",
    r"\brather than\b",
    r"\bbest way to explain (?:my )?overall\b",
)
_VALIDATION_OUTCOME_PATTERNS = (
    r"\buse (?:(?:the|this) )?(?:replay|telemetry)\b",
    r"\b(?:test|verify|validate|prove) (?:that|this|those|it)\b",
    r"\btesting evidence\b",
    r"\bsupporting example\b",
    r"\bfor example\b",
)
_VALIDATION_MODE_PATTERNS = (
    r"\buse (?:(?:the|this) )?(?:replay|telemetry)\b",
    r"\bvalidation[- ]only (?:session|run|phase)\b",
    r"\bshadow(?:ing)? (?:this |the )?(?:race|session)\b",
)
_CONTEXT_OUTCOME_PATTERNS = (
    r"\bjust context\b",
    r"\bfor background\b",
    r"\bcontext only\b",
)
_ACTION_PATTERN = re.compile(
    r"\b(?:add|build|change|create|disable|enable|fix|gate|implement|increase|make|must|need|needs|remove|rename|replace|show|should|standardize|tell|use|warn)\b",
    flags=re.IGNORECASE,
)


def _candidate_discourse_text(candidate: dict[str, Any], *, include_pre_marker: bool = True) -> str:
    narration = candidate.get("narration_context") or {}
    narration_text = " ".join(
        _safe_text(item.get("text"))
        for item in narration.get("entries") or []
        if item.get("kind") == "speech"
        and (include_pre_marker or item.get("label") != "pre_marker_explanation")
    )
    return _truncate_excerpt(narration_text or _safe_text(candidate.get("transcript_excerpt")), 2400)


def _candidate_focus_text(candidate: dict[str, Any]) -> str:
    values = [_safe_text(candidate.get("suggested_issue_title"))]
    values.extend(
        _safe_text(item.get("text"))
        for item in (candidate.get("narration_context") or {}).get("entries") or []
        if item.get("kind") == "speech" and item.get("label") == "ticket_marker"
    )
    focused = _truncate_excerpt(" ".join(dict.fromkeys(value for value in values if value)), 640)
    return focused or _candidate_discourse_text(candidate, include_pre_marker=False)


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _action_clauses(text: str) -> list[str]:
    sentences = [part.strip(" ,.;:-") for part in re.split(r"(?<=[.!?])\s+|\b(?:and then|also|separately)\b", text)]
    clauses = [re.sub(r"\s+", " ", part).strip() for part in sentences if _ACTION_PATTERN.search(part)]
    result: list[str] = []
    seen: set[str] = set()
    for clause in clauses:
        normalized = re.sub(r"[^a-z0-9]+", " ", clause.lower()).strip()
        if len(normalized.split()) < 3 or normalized in seen:
            continue
        result.append(_truncate_excerpt(clause, 320))
        seen.add(normalized)
    return result


def _topic_tokens(text: str) -> set[str]:
    ignored = {
        "about", "add", "again", "also", "another", "because", "change", "could", "create",
        "fix", "issue", "like", "made", "make", "much", "must", "need", "please", "replace", "same",
        "should", "standardize", "still", "that", "their", "them", "there", "these", "they", "thing",
        "this", "those", "ticket", "use", "want", "when", "where", "with", "would",
    }
    result: set[str] = set()
    for raw_token in re.findall(r"[a-z0-9]+", text.lower()):
        token = raw_token[:-1] if len(raw_token) > 4 and raw_token.endswith("s") else raw_token
        if len(token) >= 4 and token not in ignored:
            result.add(token)
    return result


def _group_action_clauses(clauses: list[str]) -> list[str]:
    groups: list[list[str]] = []
    bridge_tokens = {"button", "dashboard", "icon", "page", "screen", "zone"}
    for clause in clauses:
        clause_tokens = _topic_tokens(clause)
        target: list[str] | None = None
        for group in groups:
            group_tokens = set().union(*(_topic_tokens(item) for item in group))
            sequence = max(
                SequenceMatcher(None, item.lower(), clause.lower()).ratio()
                for item in group
            )
            shared = group_tokens & clause_tokens
            naming_related = bool(
                re.search(r"\b(?:call|name|refer|term)\w*\b", clause, re.IGNORECASE)
                and any(re.search(r"\b(?:call|name|refer|term)\w*\b", item, re.IGNORECASE) for item in group)
            )
            if (bool(shared - bridge_tokens) and len(shared) >= 2) or naming_related or sequence >= 0.48:
                target = group
                break
        if target is None:
            groups.append([clause])
        else:
            target.append(clause)
    return [_truncate_excerpt("; ".join(group), 320) for group in groups]


def _generic_action_clause(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    if re.search(r"\b(?:i should say|i don t need to say) (?:am|pm)\b", normalized) or re.search(
        r"\b\d{4}\b.*\bi should say\b", normalized
    ):
        return True
    return bool(
        len(normalized.split()) <= 16
        and re.search(
            r"\b(?:fix (?:[a-z]+\s+){0,3}(?:bugs?|issues?)|do (?:some )?bug fixes|create tickets?|update tickets?|generate a ticket to fix the following|that should be a ticket|that s not fix the following)\b",
            normalized,
        )
    )


def _outcome_matches(outcome: dict[str, Any], clause: str) -> bool:
    left = _safe_text(outcome.get("intent_summary"))
    left_tokens = _topic_tokens(left)
    right_tokens = _topic_tokens(clause)
    shared = left_tokens & right_tokens
    smaller = min(len(left_tokens), len(right_tokens))
    token_match = len(shared) >= 3 and smaller > 0 and len(shared) / smaller >= 0.45
    return _outcome_similarity(outcome, clause) >= 0.65 or token_match


def _outcome_similarity(left: dict[str, Any], right_text: str) -> float:
    left_text = _safe_text(left.get("intent_summary"))
    left_tokens = _topic_tokens(left_text)
    right_tokens = _topic_tokens(right_text)
    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / len(union) if union else 0.0
    sequence = SequenceMatcher(None, left_text.lower(), right_text.lower()).ratio()
    return max(jaccard, sequence)


def consolidate_candidate_outcomes(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create explainable local outcomes before any rich artifact task is emitted."""
    outcomes: list[dict[str, Any]] = []
    last_primary_by_source: dict[str, str] = {}
    recent_outcomes_by_source: dict[str, list[str]] = {}
    validation_only_sources: set[str] = set()
    candidate_by_id = {item.get("evidence_id"): item for item in candidates}

    def register_recent(source_id: str, outcome_ids: list[str]) -> None:
        recent = recent_outcomes_by_source.setdefault(source_id, [])
        for outcome_id in outcome_ids:
            if outcome_id in recent:
                recent.remove(outcome_id)
            recent.append(outcome_id)
        del recent[:-6]

    def attach_candidate(
        outcome: dict[str, Any],
        candidate: dict[str, Any],
        role: str,
    ) -> None:
        candidate_id = _safe_text(candidate.get("evidence_id"))
        if candidate_id and candidate_id != outcome.get("primary_candidate_id"):
            if candidate_id not in outcome["supporting_candidate_ids"]:
                outcome["supporting_candidate_ids"].append(candidate_id)
        if not any(
            mention.get("candidate_id") == candidate_id and mention.get("role") == role
            for mention in outcome["source_mentions"]
        ):
            outcome["source_mentions"].append(
                {
                    "candidate_id": candidate_id,
                    "source_id": candidate.get("source_id"),
                    "timestamp_seconds": candidate.get("marker_timestamp_seconds"),
                    "timestamp": _format_timestamp(candidate.get("marker_timestamp_seconds")),
                    "role": role,
                }
            )
        outcome["linked_evidence_candidate_ids"] = list(
            dict.fromkeys(
                [
                    outcome.get("primary_candidate_id"),
                    *(outcome.get("supporting_candidate_ids") or []),
                ]
            )
        )
        outcome["source_mention_ids"] = [
            mention.get("candidate_id") for mention in outcome["source_mentions"]
        ]
        outcome["source_timestamps"] = [
            mention.get("timestamp") for mention in outcome["source_mentions"]
        ]
        references = outcome.setdefault("transcript_and_narration_references", [])
        if not any(item.get("candidate_id") == candidate_id for item in references):
            references.append(
                {
                    "candidate_id": candidate_id,
                    "role": role,
                    "transcript_window_path": candidate.get("transcript_window_path", ""),
                    "narration_context_path": candidate.get("narration_context_path", ""),
                    "full_transcript_paths": candidate.get("full_transcript_paths", {}),
                }
            )

    def append_outcome(
        candidate: dict[str, Any],
        summary: str,
        classification: str = "actionable",
        *,
        primary_candidate: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        primary = primary_candidate or candidate
        primary_id = _safe_text(primary.get("evidence_id"))
        confidence = candidate.get("confidence", "weak")
        confidence_reason = (
            f"derived from {candidate.get('evidence_id')} using deterministic discourse rules"
        )
        outcome = {
            "outcome_id": f"outcome-{len(outcomes) + 1:03d}",
            "record_label": "PROVISIONAL EVIDENCE CLUSTER",
            "semantic_authority": "evidence_preparation_only",
            "final_ticket_decision": False,
            "provisional_title": candidate.get("suggested_issue_title") or summary,
            "intent_summary": summary,
            "summary_is_provisional": True,
            "classification": classification,
            "confidence": confidence,
            "confidence_reasons": [confidence_reason],
            "source_mentions": [
                {
                    "candidate_id": primary_id,
                    "source_id": primary.get("source_id"),
                    "timestamp_seconds": primary.get("marker_timestamp_seconds"),
                    "timestamp": _format_timestamp(primary.get("marker_timestamp_seconds")),
                    "role": "primary" if classification == "actionable" else "supporting",
                }
            ],
            "source_mention_ids": [primary_id] if primary_id else [],
            "source_timestamps": [
                _format_timestamp(primary.get("marker_timestamp_seconds"))
            ],
            "primary_candidate_id": primary_id if classification == "actionable" else "",
            "primary_choice_reason": (
                "Selected by deterministic discourse order as the actionable source mention for this provisional cluster."
                if classification == "actionable"
                else "No rich-evidence primary was selected because this record is text-first."
            ),
            "supporting_candidate_ids": [],
            "linked_evidence_candidate_ids": [primary_id] if primary_id else [],
            "transcript_and_narration_references": [
                {
                    "candidate_id": primary_id,
                    "role": "primary" if classification == "actionable" else "supporting",
                    "transcript_window_path": primary.get("transcript_window_path", ""),
                    "narration_context_path": primary.get("narration_context_path", ""),
                    "full_transcript_paths": primary.get("full_transcript_paths", {}),
                }
            ],
            "corrections": [],
            "split_from_candidate_id": primary_id if classification == "actionable" else "",
            "split_sibling_outcome_ids": [],
            "merged_from_outcome_ids": [],
            "render_eligible": classification == "actionable" and candidate.get("confidence") != "weak",
            "render_skip_reason": "" if classification == "actionable" and candidate.get("confidence") != "weak" else classification,
            "target_project": candidate.get("suggested_project", ""),
            "target_repository": candidate.get("suggested_repo", ""),
            "repository_suggestion": {
                "project": candidate.get("suggested_project", ""),
                "repository": candidate.get("suggested_repo", ""),
                "review_required": True,
            },
            "unresolved_questions": [],
            "operator_confirmation_state": "unconfirmed",
        }
        outcomes.append(outcome)
        if primary is not candidate:
            attach_candidate(outcome, candidate, "supporting")
        if classification == "actionable":
            last_primary_by_source[_safe_text(primary.get("source_id"))] = outcome["outcome_id"]
        return outcome

    def candidate_clauses(candidate: dict[str, Any], full_text: str) -> list[str]:
        post_marker_text = _candidate_discourse_text(candidate, include_pre_marker=False)
        marker_entries = [
            item
            for item in (candidate.get("narration_context") or {}).get("entries") or []
            if item.get("kind") == "speech" and item.get("label") == "ticket_marker"
        ]
        has_embedded_boundary = any(item.get("new_ticket_phrases") for item in marker_entries)
        marker_has_action = any(_ACTION_PATTERN.search(_safe_text(item.get("text"))) for item in marker_entries)
        preferred_text = full_text if has_embedded_boundary and marker_has_action else post_marker_text
        clauses = [item for item in _action_clauses(preferred_text) if not _generic_action_clause(item)]
        if not clauses:
            clauses = [item for item in _action_clauses(full_text) if not _generic_action_clause(item)]
        grouped = _group_action_clauses(clauses)
        focus_text = _candidate_focus_text(candidate)
        focus_tokens = _topic_tokens(focus_text)
        if (
            len(focus_tokens) >= 2
            and re.search(r"\b(?:bugs?|feature request|ticket)\b", focus_text, re.IGNORECASE)
            and not _generic_action_clause(focus_text)
            and not re.search(r"\b(?:enough|end) of (?:the )?(?:bugs?|issues?)\b", focus_text, re.IGNORECASE)
            and not any(_outcome_matches({"intent_summary": item}, focus_text) for item in grouped)
        ):
            grouped.append(_truncate_excerpt(focus_text, 320))
        return grouped

    def fallback_summary(candidate: dict[str, Any], full_text: str, focus_text: str) -> str:
        if re.search(r"\b(?:enough|end) of (?:the )?(?:bugs?|issues?)\b", focus_text, re.IGNORECASE):
            cleaned = re.sub(
                r"(?i)(?:i hope you enjoyed[^.]*\.|please (?:like|subscribe)[^.]*\.|thanks for watching[!.]?)",
                " ",
                full_text,
            )
            return _truncate_excerpt(re.sub(r"\s+", " ", cleaned).strip(), 320)
        return _truncate_excerpt(focus_text or full_text, 320)

    def link_siblings(outcome_ids: list[str]) -> None:
        unique_ids = list(dict.fromkeys(outcome_ids))
        if len(unique_ids) < 2:
            return
        for outcome_id in unique_ids:
            outcome = next(item for item in outcomes if item["outcome_id"] == outcome_id)
            existing = list(outcome.get("split_sibling_outcome_ids") or [])
            outcome["split_sibling_outcome_ids"] = list(
                dict.fromkeys([*existing, *(item for item in unique_ids if item != outcome_id)])
            )

    for candidate in candidates:
        text = _candidate_discourse_text(candidate)
        focus_text = _candidate_focus_text(candidate)
        normalized_focus = focus_text.lower()
        source_id = _safe_text(candidate.get("source_id"))
        candidate["discourse_text"] = text
        if source_id in validation_only_sources:
            candidate["outcome_classification"] = "validation_followup"
            candidate["render_eligible"] = False
            candidate["render_skip_reason"] = "validation_followup_requires_confirmation"
            candidate["outcome_ids"] = []
            continue
        if _matches_any(normalized_focus, _NEGATIVE_OUTCOME_PATTERNS):
            candidate["outcome_classification"] = "negative_no_ticket"
            candidate["render_eligible"] = False
            candidate["outcome_ids"] = []
            continue
        if _matches_any(normalized_focus, _VALIDATION_OUTCOME_PATTERNS):
            candidate["outcome_classification"] = "supporting_validation"
            candidate["render_eligible"] = False
            candidate["outcome_ids"] = []
            if _matches_any(normalized_focus, _VALIDATION_MODE_PATTERNS):
                validation_only_sources.add(source_id)
            continue
        if _matches_any(normalized_focus, _CONTEXT_OUTCOME_PATTERNS):
            candidate["outcome_classification"] = "context_only"
            candidate["render_eligible"] = False
            candidate["outcome_ids"] = []
            continue
        if _matches_any(normalized_focus, _CORRECTION_OUTCOME_PATTERNS):
            correction_text = _candidate_discourse_text(candidate, include_pre_marker=False) or text
            recent = list(recent_outcomes_by_source.get(source_id, []))
            multi_target = bool(
                re.search(r"\b(?:multiple tickets?|bug and (?:a )?feature request|all in the same)\b", text, re.IGNORECASE)
            )
            target_ids = recent[-2:] if multi_target else recent[-1:]
            if not target_ids and candidate.get("duplicate_of"):
                target_ids = [
                    item["outcome_id"]
                    for item in outcomes
                    if item.get("primary_candidate_id") == candidate.get("duplicate_of")
                ]
            for target_id in target_ids:
                prior = next((item for item in outcomes if item["outcome_id"] == target_id), None)
                if not prior:
                    continue
                if len(target_ids) == 1:
                    if "original_intent_summary" not in prior:
                        prior["original_intent_summary"] = prior.get("intent_summary", "")
                    prior["intent_summary"] = _truncate_excerpt(correction_text, 320)
                prior["corrections"].append(
                    {"candidate_id": candidate["evidence_id"], "text": _truncate_excerpt(correction_text, 320)}
                )
                attach_candidate(prior, candidate, "correction")
            candidate["outcome_classification"] = "correction"
            candidate["render_eligible"] = False
            candidate["outcome_ids"] = target_ids
            register_recent(source_id, target_ids)
            continue
        if _matches_any(normalized_focus, _SETUP_OUTCOME_PATTERNS):
            candidate["outcome_classification"] = "transition_setup"
            candidate["render_eligible"] = False
            candidate["outcome_ids"] = []
            continue

        clauses = candidate_clauses(candidate, text)
        if candidate.get("duplicate_role") == "supporting_duplicate":
            primary_candidate = candidate_by_id.get(candidate.get("duplicate_of")) or candidate
            linked_ids = [
                item["outcome_id"]
                for item in outcomes
                if item.get("primary_candidate_id") == primary_candidate.get("evidence_id")
            ]
            for outcome_id in linked_ids:
                target = next(item for item in outcomes if item["outcome_id"] == outcome_id)
                attach_candidate(target, candidate, "duplicate_support")
            for clause in clauses:
                matches = [item for item in outcomes if _outcome_matches(item, clause)]
                if matches:
                    for match in matches:
                        attach_candidate(match, candidate, "duplicate_support")
                        linked_ids.append(match["outcome_id"])
                    continue
                linked_ids.append(
                    append_outcome(
                        candidate,
                        clause,
                        primary_candidate=primary_candidate,
                    )["outcome_id"]
                )
            linked_ids = list(dict.fromkeys(linked_ids))
            primary_candidate["outcome_ids"] = list(
                dict.fromkeys([*(primary_candidate.get("outcome_ids") or []), *linked_ids])
            )
            link_siblings(primary_candidate["outcome_ids"])
            candidate["outcome_classification"] = "duplicate_supporting"
            candidate["render_eligible"] = False
            candidate["outcome_ids"] = linked_ids
            register_recent(source_id, linked_ids)
            continue

        if not clauses:
            fallback = fallback_summary(candidate, text, focus_text)
            clauses = [fallback] if fallback else []
        if not clauses:
            candidate["outcome_classification"] = "context_only"
            candidate["render_eligible"] = False
            candidate["outcome_ids"] = []
            continue

        candidate["outcome_classification"] = "actionable"
        candidate["render_eligible"] = candidate.get("confidence") != "weak"
        created: list[str] = []
        for clause in clauses:
            matches = [item for item in outcomes if _outcome_matches(item, clause)]
            if matches:
                for match in matches:
                    attach_candidate(match, candidate, "supporting")
                    created.append(match["outcome_id"])
                continue
            created.append(append_outcome(candidate, clause)["outcome_id"])
        created = list(dict.fromkeys(created))
        candidate["outcome_ids"] = created
        link_siblings(created)
        register_recent(source_id, created)
    return outcomes


def _apply_outcome_render_policy(
    candidates: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    requested_outcome_ids: list[str],
    requested_candidate_ids: list[str],
    *,
    stop_after: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    requested = set(_normalize_candidate_ids(requested_outcome_ids))
    candidate_aliases = set(_normalize_candidate_ids(requested_candidate_ids))
    if candidate_aliases:
        requested.update(
            _safe_text(outcome.get("outcome_id"))
            for outcome in outcomes
            if outcome.get("primary_candidate_id") in candidate_aliases
        )
    outcome_by_id = {outcome.get("outcome_id"): outcome for outcome in outcomes}
    render_candidate_ids = {
        outcome.get("primary_candidate_id")
        for outcome in outcomes
        if (outcome.get("render_eligible") or outcome.get("outcome_id") in requested)
        and (not requested or outcome.get("outcome_id") in requested)
    }
    for outcome in outcomes:
        if outcome.get("outcome_id") in requested and not outcome.get("render_eligible"):
            outcome["operator_confirmation_state"] = "explicit_render_selection"
    rendered: list[dict[str, Any]] = []
    unrendered: list[dict[str, Any]] = []
    for candidate in candidates:
        legacy_selected = candidate.get("render_status") == "rendered"
        candidate["legacy_render_selected"] = legacy_selected
        is_primary = candidate.get("evidence_id") in render_candidate_ids
        allowed = is_primary and (bool(requested) or legacy_selected)
        allowed = allowed and stop_after.lower() == "package"
        if allowed:
            candidate["render_status"] = "rendered"
            candidate["render_skip_reason"] = ""
            candidate["provisional_evidence_role"] = "primary"
            rendered.append(candidate)
        else:
            candidate["frames"] = []
            candidate["audio_snippet"]["status"] = "not_rendered"
            for snippet in candidate.get("supporting_audio_snippets") or []:
                snippet["status"] = "not_rendered"
            candidate["render_status"] = "unrendered"
            candidate["render_skip_reason"] = (
                "pipeline_stopped_before_render"
                if stop_after.lower() != "package"
                else (
                    candidate.get("render_skip_reason")
                    if not legacy_selected and candidate.get("render_skip_reason")
                    else (
                        "supporting_or_non_primary_text_only"
                        if not is_primary
                        else candidate.get("outcome_classification", "not_selected_for_rich_render")
                    )
                )
            )
            candidate["provisional_evidence_role"] = (
                "primary_text_only" if is_primary else "supporting_text_only"
            )
            unrendered.append(candidate)
    return rendered, unrendered


def _full_transcript_paths(
    source_id: str,
    physical_source_id: str = "",
) -> dict[str, str]:
    physical_token = _safe_text(physical_source_id) or source_id
    source_base = f"transcript/sources/{physical_token}.transcript"
    return {
        "logical_source_id": source_id,
        "physical_source_id": physical_token,
        "source_json": f"{source_base}.json",
        "source_srt": f"{source_base}.srt",
        "source_txt": f"{source_base}.txt",
        "full_transcript_json": "transcript/full_transcript.json",
        "full_transcript_markdown": "transcript/full_transcript.md",
    }


def _next_candidate_marker_time(windows: list[dict[str, Any]], index: int) -> float | None:
    source_id = windows[index].get("source_id")
    for next_window in windows[index + 1 :]:
        if next_window.get("source_id") != source_id:
            continue
        events = next_window.get("events") or []
        if events:
            return _coerce_float(events[0].get("marker_time"), 0.0)
    return None


def _build_narration_context(
    *,
    candidate: dict[str, Any],
    source: dict[str, Any],
    fragmented_narration_mode: bool,
    narration_context_pre_seconds: float,
    narration_context_post_seconds: float,
    narration_pause_threshold_seconds: float,
    narration_stop_at_next_ticket_boundary: bool,
    next_candidate_marker_time: float | None,
) -> dict[str, Any]:
    marker_time = _coerce_float(candidate.get("marker_timestamp_seconds"), 0.0)
    focused_start = _coerce_float(candidate.get("timestamp_start_seconds"), marker_time)
    focused_end = _coerce_float(candidate.get("timestamp_end_seconds"), marker_time)
    duration = _coerce_float(source.get("duration_seconds"), 0.0)
    if fragmented_narration_mode:
        context_start = max(0.0, marker_time - narration_context_pre_seconds)
        horizon_end = marker_time + narration_context_post_seconds
    else:
        context_start = focused_start
        horizon_end = focused_end
    if duration > 0:
        horizon_end = min(duration, horizon_end)
    horizon_end = max(context_start, horizon_end)

    boundary_type = ""
    boundary_timestamp_seconds: float | None = None
    boundary_phrases: list[str] = []
    boundary_include_segment = False
    source_segments = list(source.get("segments") or [])

    for segment in source_segments:
        start = _coerce_float(segment.get("start"), 0.0)
        if start <= marker_time + 0.001 or start > horizon_end + 0.001:
            continue
        new_ticket_phrases = _matching_control_phrases(segment.get("text"), NEW_TICKET_BOUNDARY_PHRASES)
        closing_phrases = _matching_control_phrases(segment.get("text"), CLOSING_BOUNDARY_PHRASES)
        if new_ticket_phrases and narration_stop_at_next_ticket_boundary:
            boundary_type = "new_ticket"
            boundary_timestamp_seconds = start
            boundary_phrases = new_ticket_phrases
            boundary_include_segment = False
            break
        if closing_phrases:
            boundary_type = "closing"
            boundary_timestamp_seconds = _coerce_float(segment.get("end"), start)
            boundary_phrases = closing_phrases
            boundary_include_segment = True
            break

    if (
        narration_stop_at_next_ticket_boundary
        and next_candidate_marker_time is not None
        and marker_time + 0.001 < next_candidate_marker_time <= horizon_end + 0.001
        and (boundary_timestamp_seconds is None or next_candidate_marker_time < boundary_timestamp_seconds)
    ):
        boundary_type = "next_explicit_ticket_marker"
        boundary_timestamp_seconds = next_candidate_marker_time
        boundary_phrases = []
        boundary_include_segment = False

    context_end = boundary_timestamp_seconds if boundary_timestamp_seconds is not None else horizon_end
    context_end = max(context_start, context_end)
    segments: list[dict[str, Any]] = []
    for segment in source_segments:
        start = _coerce_float(segment.get("start"), 0.0)
        end = _coerce_float(segment.get("end"), start)
        if end < context_start or start > context_end:
            continue
        if boundary_timestamp_seconds is not None and not boundary_include_segment and start >= context_end - 0.001:
            continue
        segments.append(segment)

    entries: list[dict[str, Any]] = []
    previous_end: float | None = None
    after_driving_pause = False
    pause_count = 0
    continuation_phrases_found: list[str] = []
    new_ticket_phrases_found: list[str] = list(boundary_phrases if boundary_type == "new_ticket" else [])
    closing_phrases_found: list[str] = list(boundary_phrases if boundary_type == "closing" else [])
    has_followup_after_pause = False
    has_pre_marker_explanation = False

    for segment in segments:
        start = _coerce_float(segment.get("start"), 0.0)
        end = _coerce_float(segment.get("end"), start)
        if previous_end is not None:
            gap = max(0.0, start - previous_end)
            if gap >= narration_pause_threshold_seconds:
                pause_count += 1
                after_driving_pause = True
                entries.append(
                    {
                        "kind": "pause",
                        "duration_seconds": round(gap, 3),
                        "start_seconds": round(previous_end, 3),
                        "end_seconds": round(start, 3),
                        "label": "driving_pause",
                    }
                )

        continuation_phrases = _matching_control_phrases(segment.get("text"), CONTINUATION_PHRASES)
        new_ticket_phrases = _matching_control_phrases(segment.get("text"), NEW_TICKET_BOUNDARY_PHRASES)
        closing_phrases = _matching_control_phrases(segment.get("text"), CLOSING_BOUNDARY_PHRASES)
        continuation_phrases_found.extend(
            phrase for phrase in continuation_phrases if phrase not in continuation_phrases_found
        )
        new_ticket_phrases_found.extend(
            phrase for phrase in new_ticket_phrases if phrase not in new_ticket_phrases_found
        )
        closing_phrases_found.extend(
            phrase for phrase in closing_phrases if phrase not in closing_phrases_found
        )

        if start <= marker_time <= end + 0.001:
            label = "ticket_marker"
        elif end <= marker_time + 0.001:
            label = "pre_marker_explanation"
            has_pre_marker_explanation = True
        elif closing_phrases:
            label = "closing_boundary"
        elif continuation_phrases:
            label = "explicit_continuation_cue"
            if after_driving_pause:
                has_followup_after_pause = True
        elif after_driving_pause:
            label = "possible_continuation_after_driving_pause"
            has_followup_after_pause = True
        else:
            label = "post_marker_explanation"

        entries.append(
            {
                "kind": "speech",
                "segment_id": segment.get("id"),
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "timestamp_start": segment.get("timestamp_start") or _format_timestamp(start),
                "timestamp_end": segment.get("timestamp_end") or _format_timestamp(end),
                "text": _safe_text(segment.get("text")),
                "label": label,
                "continuation_phrases": continuation_phrases,
                "new_ticket_phrases": new_ticket_phrases,
                "closing_phrases": closing_phrases,
            }
        )
        previous_end = end

    source_end_reached = duration > 0 and context_end >= duration - 0.001
    reached_horizon = bool(
        fragmented_narration_mode
        and boundary_timestamp_seconds is None
        and not source_end_reached
    )
    speech_entries = [entry for entry in entries if entry.get("kind") == "speech"]
    last_speech_end = max((_coerce_float(entry.get("end_seconds")) for entry in speech_entries), default=0.0)
    next_segment_start = next(
        (
            _coerce_float(segment.get("start"), 0.0)
            for segment in source_segments
            if _coerce_float(segment.get("start"), 0.0) > context_end + 0.001
        ),
        None,
    )
    may_still_continue = bool(
        reached_horizon
        and (
            last_speech_end >= context_end - narration_pause_threshold_seconds
            or (
                next_segment_start is not None
                and next_segment_start <= context_end + narration_pause_threshold_seconds
            )
        )
    )
    warning = (
        "Narration horizon ended while speech may still be continuing. Inspect the shared full transcript."
        if may_still_continue
        else ""
    )

    return {
        "schema_version": EVIDENCE_PACKAGE_SCHEMA_VERSION,
        "source_filename": candidate.get("source_filename", ""),
        "source_identifier": candidate.get("source_identifier", ""),
        "source_id": candidate.get("source_id", ""),
        "ticket_marker_timestamp_seconds": round(marker_time, 3),
        "ticket_marker_timestamp": _format_timestamp(marker_time),
        "focused_window": {
            "start_seconds": round(focused_start, 3),
            "end_seconds": round(focused_end, 3),
            "start": _format_timestamp(focused_start),
            "end": _format_timestamp(focused_end),
        },
        "narration_window": {
            "start_seconds": round(context_start, 3),
            "end_seconds": round(context_end, 3),
            "start": _format_timestamp(context_start),
            "end": _format_timestamp(context_end),
        },
        "settings": {
            "fragmented_narration_mode": fragmented_narration_mode,
            "narration_context_pre_seconds": narration_context_pre_seconds,
            "narration_context_post_seconds": narration_context_post_seconds,
            "narration_pause_threshold_seconds": narration_pause_threshold_seconds,
            "narration_stop_at_next_ticket_boundary": narration_stop_at_next_ticket_boundary,
        },
        "boundary": {
            "type": boundary_type
            or (
                "source_end"
                if source_end_reached
                else ("horizon" if fragmented_narration_mode else "focused_window_end")
            ),
            "timestamp_seconds": (
                round(boundary_timestamp_seconds, 3) if boundary_timestamp_seconds is not None else None
            ),
            "timestamp": (
                _format_timestamp(boundary_timestamp_seconds)
                if boundary_timestamp_seconds is not None
                else ""
            ),
            "phrases": boundary_phrases,
        },
        "segment_count": len(speech_entries),
        "pause_count": pause_count,
        "has_pre_marker_explanation": has_pre_marker_explanation,
        "has_followup_after_pause": has_followup_after_pause,
        "continuation_phrases": continuation_phrases_found,
        "new_ticket_phrases": new_ticket_phrases_found,
        "closing_phrases": closing_phrases_found,
        "reached_horizon": reached_horizon,
        "warning": warning,
        "entries": entries,
        "full_transcript_paths": _full_transcript_paths(
            _safe_text(candidate.get("source_id")),
            _safe_text(candidate.get("physical_source_id")),
        ),
    }


def _build_candidates(
    windows: list[dict[str, Any]],
    output_dir: Path,
    frame_offsets: list[float],
    max_items: int,
    frame_cadence_seconds: float,
    max_frames_per_candidate: int,
    panel_crop_mode: str,
    panel_definitions: list[dict[str, Any]] | tuple[dict[str, Any], ...] = THREE_PANEL_DEFINITIONS,
    markers: list[dict[str, str]] = MARKERS,
    fragmented_narration_mode: bool = True,
    narration_context_pre_seconds: float = NARRATION_CONTEXT_PRE_SECONDS,
    narration_context_post_seconds: float = NARRATION_CONTEXT_POST_SECONDS,
    narration_pause_threshold_seconds: float = NARRATION_PAUSE_THRESHOLD_SECONDS,
    narration_stop_at_next_ticket_boundary: bool = True,
    render_candidate_ids: list[str] | None = None,
    preserve_supporting_audio: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    all_candidates: list[dict[str, Any]] = []
    candidate_ids = [f"ticket-{index:03d}" for index in range(1, len(windows) + 1)]
    requested_ids = _normalize_candidate_ids(render_candidate_ids)
    if requested_ids:
        selected_ids = [candidate_id for candidate_id in candidate_ids if candidate_id in set(requested_ids)]
    else:
        selected_ids = list(candidate_ids)
    if max_items > 0:
        selected_ids = selected_ids[:max_items]
    selected_id_set = set(selected_ids)

    for index, window in enumerate(windows, start=1):
        evidence_id = f"ticket-{index:03d}"
        rendered = evidence_id in selected_id_set
        source = window["source"]
        events = window["events"]
        first_event = events[0]
        phrases = sorted(
            {
                match["phrase"]
                for event in events
                for match in event.get("matches", [])
            },
            key=str.lower,
        )
        primary_phrases = [
            phrase
            for phrase in phrases
            if CONFIDENCE_RANK.get(
                next((marker["confidence"] for marker in markers if marker["phrase"] == phrase), ""),
                0,
            )
            >= CONFIDENCE_RANK["weak"]
        ]
        supporting_phrases = [phrase for phrase in phrases if phrase not in primary_phrases]
        confidence = _highest_confidence([event["confidence"] for event in events])
        segments = _segments_in_window(source, window["start"], window["end"])
        word_count = _candidate_word_count(segments)
        transcript_excerpt = " ".join(segment["text"] for segment in segments)
        if len(transcript_excerpt) > 1600:
            transcript_excerpt = transcript_excerpt[:1597].rstrip() + "..."
        fallback_title = f"Review {source['source_filename'] or source['source_id']} at {_format_timestamp(first_event['marker_time'])}"
        title = _build_candidate_title(first_event, segments, fallback_title, markers)
        not_enough = confidence == "weak" or word_count < 12
        base_rel = f"evidence_items/{evidence_id}"
        marker_time = _coerce_float(first_event["marker_time"])
        frame_entries = (
            _build_frame_entries(
                output_dir=output_dir,
                base_rel=base_rel,
                source=source,
                window=window,
                marker_time=marker_time,
                frame_offsets=frame_offsets,
                frame_cadence_seconds=frame_cadence_seconds,
                max_frames_per_candidate=max_frames_per_candidate,
                panel_crop_mode=panel_crop_mode,
                panel_definitions=panel_definitions,
            )
            if rendered
            else []
        )

        audio_duration = max(0.0, window["end"] - window["start"])
        was_capped = audio_duration > AUDIO_SNIPPET_MAX_SECONDS
        audio_duration = min(audio_duration, AUDIO_SNIPPET_MAX_SECONDS)
        audio_rel = f"{base_rel}/audio_snippet.mp3"
        audio_input_path = source.get("audio_path") or source.get("source_path") or ""
        selected_audio_ordinal = _coerce_int(source.get("selected_audio_stream_index"), 0)
        supporting_audio_snippets = [
            {
                "relative_path": f"{base_rel}/supporting_audio/stream-{_coerce_int(stream.get('ordinal'), 0)}.mp3",
                "path": str(
                    output_dir
                    / f"{base_rel}/supporting_audio/stream-{_coerce_int(stream.get('ordinal'), 0)}.mp3"
                ),
                "status": "pending" if rendered and audio_duration > 0 else "not_rendered",
                "error_message": "",
                "start_seconds": round(window["start"], 3),
                "duration_seconds": round(audio_duration, 3),
                "was_capped": was_capped,
                "input_path": source.get("source_path") or "",
                "input_method": "source_video_stream",
                "audio_stream_index": _coerce_int(stream.get("ordinal"), 0),
                "audio_role": "supporting_audio",
                "stream_metadata": dict(stream),
            }
            for stream in source.get("audio_streams") or []
            if preserve_supporting_audio
            and _coerce_int(stream.get("ordinal"), -1) != selected_audio_ordinal
        ]
        marker_events = [
            {
                "marker_timestamp": event["marker_timestamp"],
                "marker_time_seconds": round(_coerce_float(event["marker_time"]), 3),
                "segment_id": event.get("segment_id"),
                "segment_text": event.get("segment_text", ""),
                "raw_segment_text": event.get("raw_segment_text", ""),
                "detected_marker_phrases": [match["phrase"] for match in event.get("matches", [])],
                "confidence": event["confidence"],
                "duplicate_occurrences": list(event.get("duplicate_occurrences") or []),
            }
            for event in events
        ]
        boundary_marker_events = [
            marker_event
            for marker_event, event in zip(marker_events, events)
            if _is_boundary_event(event)
        ]
        candidate = {
                "evidence_id": evidence_id,
                "source_id": source["source_id"],
                "physical_source_id": source.get("physical_source_id", ""),
                "physical_source_id_shortened": source.get(
                    "physical_source_id_shortened", False
                ),
                "source_identifier": source["source_identifier"],
                "source_filename": source["source_filename"],
                "source_path": source["source_path"],
                "audio_input_path": audio_input_path,
                "timestamp_start_seconds": round(window["start"], 3),
                "timestamp_end_seconds": round(window["end"], 3),
                "timestamp_start": _format_timestamp(window["start"]),
                "timestamp_end": _format_timestamp(window["end"]),
                "marker_timestamp_seconds": round(marker_time, 3),
                "marker_timestamp": _format_timestamp(marker_time),
                "detected_marker_phrases": primary_phrases,
                "supporting_marker_phrases": supporting_phrases,
                "confidence": confidence,
                "transcript_excerpt": transcript_excerpt,
                "transcript_window_path": f"{base_rel}/transcript_window.md",
                "narration_context_path": f"{base_rel}/narration_context.md",
                "narration_context_json_path": f"{base_rel}/narration_context.json",
                "metadata_path": f"{base_rel}/metadata.json",
                "ticket_path": f"{base_rel}/ticket.md",
                "frame_index_path": f"{base_rel}/frame_index.csv",
                "frames": frame_entries,
                "audio_snippet": {
                    "relative_path": audio_rel,
                    "path": str(output_dir / audio_rel),
                    "status": (
                        "pending"
                        if rendered and audio_duration > 0 and audio_input_path
                        else ("not_available" if rendered else "not_rendered")
                    ),
                    "error_message": "",
                    "start_seconds": round(window["start"], 3),
                    "duration_seconds": round(audio_duration, 3),
                    "was_capped": was_capped,
                    "input_path": audio_input_path,
                    "input_method": "extracted_audio" if source.get("audio_path") else "source_video",
                    "audio_stream_index": 0,
                    "audio_role": "operator_narration",
                },
                "supporting_audio_snippets": supporting_audio_snippets,
                "suggested_issue_title": title,
                "original_title_text": first_event.get("raw_segment_text") or first_event.get("segment_text", ""),
                "not_enough_evidence": not_enough,
                "notes_for_ai_reviewer": (
                    "Review transcript and frames together. Candidate tickets are extraction hints, "
                    "not the full truth. Ask for operator clarification when evidence is insufficient."
                ),
                "marker_events": marker_events,
                "boundary_marker_events": boundary_marker_events,
                "segment_count": len(segments),
                "word_count": word_count,
                "source_transcript_quality": source.get("transcript_quality", {}),
                "render_status": "rendered" if rendered else "unrendered",
                "render_skip_reason": (
                    ""
                    if rendered
                    else (
                        "not_selected_for_rich_render"
                        if requested_ids and evidence_id not in set(requested_ids)
                        else "rich_evidence_limit"
                    )
                ),
                "full_transcript_paths": _full_transcript_paths(
                    source["source_id"], source.get("physical_source_id", "")
                ),
            }
        narration_context = _build_narration_context(
            candidate=candidate,
            source=source,
            fragmented_narration_mode=fragmented_narration_mode,
            narration_context_pre_seconds=narration_context_pre_seconds,
            narration_context_post_seconds=narration_context_post_seconds,
            narration_pause_threshold_seconds=narration_pause_threshold_seconds,
            narration_stop_at_next_ticket_boundary=narration_stop_at_next_ticket_boundary,
            next_candidate_marker_time=_next_candidate_marker_time(windows, index - 1),
        )
        candidate["narration_context"] = narration_context
        candidate.update(
            {
                "narration_context_start_seconds": narration_context["narration_window"]["start_seconds"],
                "narration_context_end_seconds": narration_context["narration_window"]["end_seconds"],
                "narration_context_segment_count": narration_context["segment_count"],
                "narration_context_pause_count": narration_context["pause_count"],
                "narration_context_has_pre_marker_explanation": narration_context[
                    "has_pre_marker_explanation"
                ],
                "narration_context_has_followup_after_pause": narration_context[
                    "has_followup_after_pause"
                ],
                "narration_context_boundary_type": narration_context["boundary"]["type"],
                "narration_context_boundary_timestamp_seconds": narration_context["boundary"][
                    "timestamp_seconds"
                ],
                "narration_context_boundary_timestamp": narration_context["boundary"]["timestamp"],
                "narration_context_reached_horizon": narration_context["reached_horizon"],
                "narration_context_warning": narration_context["warning"],
            }
        )
        all_candidates.append(candidate)
    _annotate_duplicate_candidates(all_candidates)
    rendered_candidates = [candidate for candidate in all_candidates if candidate["render_status"] == "rendered"]
    unrendered_candidates = [
        candidate for candidate in all_candidates if candidate["render_status"] == "unrendered"
    ]
    return rendered_candidates, unrendered_candidates, all_candidates


def _matched_review_terms(text: str, phrases: tuple[str, ...]) -> list[str]:
    normalized = _normalize_marker_text(text)
    matches: list[str] = []
    seen: set[str] = set()
    for phrase in phrases:
        normalized_phrase = _normalize_marker_text(phrase)
        if not normalized_phrase:
            continue
        matched = re.search(_phrase_pattern(normalized_phrase), normalized, flags=re.IGNORECASE) is not None
        if matched and normalized_phrase not in seen:
            matches.append(phrase)
            seen.add(normalized_phrase)
    return matches


def _review_context_segments(
    source: dict[str, Any],
    segment: dict[str, Any],
    context_seconds: float = 30.0,
) -> list[dict[str, Any]]:
    marker_time = _coerce_float(segment.get("start"), 0.0)
    return _segments_in_window(
        source,
        max(0.0, marker_time - context_seconds),
        marker_time + context_seconds,
    )


def _truncate_excerpt(text: str, limit: int = 900) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _candidate_ids_covering_time(source_id: str, timestamp_seconds: float, candidates: list[dict[str, Any]]) -> list[str]:
    return [
        candidate["evidence_id"]
        for candidate in candidates
        if candidate.get("source_id") == source_id
        and _coerce_float(candidate.get("timestamp_start_seconds")) <= timestamp_seconds <= _coerce_float(candidate.get("timestamp_end_seconds"))
    ]


def _build_review_needed_items(
    sources: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    pre_context: float,
    post_context: float,
    domain_terms_config: tuple[str, ...] = REVIEW_NEEDED_DOMAIN_TERMS,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, int, str]] = set()

    def add_item(
        *,
        source: dict[str, Any],
        segment: dict[str, Any] | None,
        reason: str,
        implicit_phrases: list[str],
        domain_terms: list[str],
        excerpt_segments: list[dict[str, Any]],
    ) -> None:
        marker_time = _coerce_float((segment or {}).get("start"), 0.0)
        marker_bucket = int(round(marker_time / 10.0))
        key = (source["source_id"], marker_bucket, reason)
        if key in seen_keys:
            return
        seen_keys.add(key)
        start = max(0.0, marker_time - pre_context)
        end = marker_time + post_context
        if source["duration_seconds"] > 0:
            end = min(source["duration_seconds"], end)
        end = max(start, end)
        candidate_ids = _candidate_ids_covering_time(source["source_id"], marker_time, candidates)
        excerpt = " ".join(_safe_text(item.get("text")) for item in excerpt_segments)
        review_id = f"review-{len(items) + 1:03d}"
        items.append(
            {
                "review_id": review_id,
                "source_id": source["source_id"],
                "source_identifier": source["source_identifier"],
                "source_filename": source["source_filename"],
                "source_path": source["source_path"],
                "timestamp_start_seconds": round(start, 3),
                "timestamp_end_seconds": round(end, 3),
                "timestamp_start": _format_timestamp(start),
                "timestamp_end": _format_timestamp(end),
                "marker_timestamp_seconds": round(marker_time, 3),
                "marker_timestamp": _format_timestamp(marker_time),
                "segment_id": (segment or {}).get("id"),
                "confidence": "review-needed",
                "reason": reason,
                "promotion_status": (
                    "unassigned_ticket_mention"
                    if reason == "uncandidated_actionable_request" and not candidate_ids
                    else "unresolved_review_group"
                ),
                "implicit_phrases": implicit_phrases,
                "domain_terms": domain_terms,
                "candidate_ids_covering_time": candidate_ids,
                "visual_followup_required": True,
                "transcript_excerpt": _truncate_excerpt(excerpt),
                "notes_for_reviewer": (
                    "Review-needed items are lower-confidence evidence hints. Inspect transcript, frames, "
                    "and panel crops before deciding whether this is a new issue, an update to an existing issue, "
                    "or context only."
                ),
                "source_transcript_quality": source.get("transcript_quality", {}),
            }
        )

    for source in sources:
        if source["status"] not in {"completed", "skipped"}:
            continue
        for segment in source.get("segments", []):
            segment_text = _safe_text(segment.get("text"))
            if not segment_text:
                continue
            if _has_primary_marker(_marker_matches(segment_text)):
                continue
            context_segments = _review_context_segments(source, segment)
            context_text = " ".join(_safe_text(item.get("text")) for item in context_segments)
            implicit_phrases = _matched_review_terms(context_text, REVIEW_NEEDED_IMPLICIT_PHRASES)
            domain_terms = _matched_review_terms(context_text, domain_terms_config)
            action_phrases = _matched_review_terms(context_text, REVIEW_NEEDED_ACTION_PHRASES)
            direct_domain_terms = _matched_review_terms(segment_text, domain_terms_config)
            direct_action_phrases = _matched_review_terms(segment_text, REVIEW_NEEDED_ACTION_PHRASES)
            if direct_domain_terms and direct_action_phrases:
                add_item(
                    source=source,
                    segment=segment,
                    reason="uncandidated_actionable_request",
                    implicit_phrases=action_phrases or direct_action_phrases,
                    domain_terms=direct_domain_terms,
                    excerpt_segments=context_segments,
                )
            elif implicit_phrases and domain_terms:
                add_item(
                    source=source,
                    segment=segment,
                    reason="implicit_issue_with_ui_or_domain_context",
                    implicit_phrases=implicit_phrases,
                    domain_terms=domain_terms,
                    excerpt_segments=context_segments,
                )

        quality = source.get("transcript_quality", {})
        risk_classification = quality.get("risk_classification") or (
            "usable" if quality.get("appears_usable") else "suspicious_high_risk"
        )
        if risk_classification == "usable":
            continue
        source_text = _source_transcript_text(source)
        domain_terms = _matched_review_terms(source_text, domain_terms_config)
        if not domain_terms:
            continue
        first_domain_segment = next(
            (
                segment
                for segment in source.get("segments", [])
                if _matched_review_terms(_safe_text(segment.get("text")), domain_terms_config)
            ),
            (source.get("segments") or [{}])[0],
        )
        add_item(
            source=source,
            segment=first_domain_segment,
            reason="transcript_quality_visual_followup",
            implicit_phrases=[],
            domain_terms=domain_terms,
            excerpt_segments=_review_context_segments(source, first_domain_segment),
        )

    return _group_review_needed_items(items)


def _group_review_needed_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: list[dict[str, Any]] = []
    for item in sorted(
        items,
        key=lambda value: (
            value.get("source_filename", ""),
            _coerce_float(value.get("marker_timestamp_seconds")),
            value.get("reason", ""),
        ),
    ):
        target: dict[str, Any] | None = None
        for prior in reversed(grouped):
            if prior.get("source_id") != item.get("source_id"):
                continue
            marker_gap = _coerce_float(item.get("marker_timestamp_seconds")) - _coerce_float(
                prior.get("last_marker_timestamp_seconds", prior.get("marker_timestamp_seconds"))
            )
            if marker_gap > 60.0:
                break
            shared_domain = set(prior.get("domain_terms") or []) & set(item.get("domain_terms") or [])
            windows_overlap = _coerce_float(item.get("timestamp_start_seconds")) <= _coerce_float(
                prior.get("timestamp_end_seconds")
            )
            if shared_domain and windows_overlap:
                target = prior
                break
        if target is None:
            grouped.append(
                {
                    **dict(item),
                    "grouped_occurrence_count": 1,
                    "grouped_segment_ids": [item.get("segment_id")],
                    "grouped_reasons": [item.get("reason")],
                    "last_marker_timestamp_seconds": item.get("marker_timestamp_seconds"),
                }
            )
            continue
        target["grouped_occurrence_count"] += 1
        target["last_marker_timestamp_seconds"] = item.get("marker_timestamp_seconds")
        target["timestamp_end_seconds"] = max(
            _coerce_float(target.get("timestamp_end_seconds")),
            _coerce_float(item.get("timestamp_end_seconds")),
        )
        target["timestamp_end"] = _format_timestamp(target["timestamp_end_seconds"])
        for key in ("implicit_phrases", "domain_terms", "candidate_ids_covering_time"):
            target[key] = sorted(set(target.get(key) or []) | set(item.get(key) or []))
        if item.get("segment_id") not in target["grouped_segment_ids"]:
            target["grouped_segment_ids"].append(item.get("segment_id"))
        if item.get("reason") not in target["grouped_reasons"]:
            target["grouped_reasons"].append(item.get("reason"))
        if item.get("promotion_status") == "unassigned_ticket_mention":
            target["promotion_status"] = "unassigned_ticket_mention"
            target["reason"] = "uncandidated_actionable_request"
        if len(_safe_text(item.get("transcript_excerpt"))) > len(
            _safe_text(target.get("transcript_excerpt"))
        ):
            target["transcript_excerpt"] = item.get("transcript_excerpt")

    for index, item in enumerate(grouped, start=1):
        item["review_id"] = f"review-{index:03d}"
        item.pop("last_marker_timestamp_seconds", None)
    return grouped


def _review_needed_summary(review_needed: list[dict[str, Any]]) -> dict[str, Any]:
    reason_counts: dict[str, int] = {}
    for item in review_needed:
        reason = item.get("reason") or "unknown"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return {
        "review_needed_count": len(review_needed),
        "visual_followup_required_count": sum(1 for item in review_needed if item.get("visual_followup_required")),
        "reason_counts": reason_counts,
    }


def _build_review_needed_markdown(review_needed: list[dict[str, Any]]) -> str:
    lines = [
        "# Review Needed",
        "",
        "These are lower-confidence evidence hints. They are not candidate tickets by themselves.",
        "Review transcript, frames, and panel crops before deciding whether to create or update any issue.",
        "",
        f"Review-needed items: {len(review_needed)}",
        "",
    ]
    if not review_needed:
        lines.append("No lower-confidence review-needed items were detected.")
        return "\n".join(lines).rstrip() + "\n"
    for item in review_needed:
        lines.extend(
            [
                f"## {item.get('review_id')}: {item.get('source_filename')} {item.get('marker_timestamp')}",
                "",
                f"- Timestamp window: {item.get('timestamp_start')} - {item.get('timestamp_end')}",
                f"- Reason: {item.get('reason')}",
                f"- Implicit issue phrases: {', '.join(item.get('implicit_phrases') or []) or 'none'}",
                f"- UI/domain terms: {', '.join(item.get('domain_terms') or []) or 'none'}",
                f"- Candidate IDs already covering this time: {', '.join(item.get('candidate_ids_covering_time') or []) or 'none'}",
                "- Visual follow-up required: true",
                "",
                item.get("transcript_excerpt") or "",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _marker_snippet(text: str, start: int, end: int, context: int = 120) -> str:
    snippet_start = max(0, start - context)
    snippet_end = min(len(text), end + context)
    prefix = "..." if snippet_start > 0 else ""
    suffix = "..." if snippet_end < len(text) else ""
    return prefix + re.sub(r"\s+", " ", text[snippet_start:snippet_end]).strip() + suffix


def _iter_audit_marker_hits(segment: dict[str, Any]) -> list[dict[str, Any]]:
    text = _safe_text(segment.get("text"))
    normalized_text = _normalize_marker_text(text)
    hits: list[dict[str, Any]] = []
    for phrase in AUDIT_MARKER_PHRASES:
        normalized_phrase = _normalize_marker_text(phrase)
        for match in re.finditer(_phrase_pattern(normalized_phrase), normalized_text, flags=re.IGNORECASE):
            hits.append(
                {
                    "marker_phrase": phrase,
                    "match_start": match.start(),
                    "match_end": match.end(),
                    "snippet": _marker_snippet(text, match.start(), match.end()),
                }
            )
    return sorted(hits, key=lambda item: (item["match_start"], -len(item["marker_phrase"]), item["marker_phrase"]))


def _candidate_ids_covering_marker(source_id: str, marker_time: float, candidates: list[dict[str, Any]]) -> list[str]:
    return [
        candidate["evidence_id"]
        for candidate in candidates
        if candidate.get("source_id") == source_id
        and _coerce_float(candidate.get("timestamp_start_seconds")) <= marker_time <= _coerce_float(candidate.get("timestamp_end_seconds"))
    ]


def _build_marker_audit(
    sources: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    unrendered_candidates: list[dict[str, Any]] | None = None,
    mentioned: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    unrendered_candidates = list(unrendered_candidates or [])
    mentioned_times = {
        (_safe_text(item.get("source_id")), round(_coerce_float(item.get("timestamp_seconds"), 0.0), 3))
        for item in (mentioned or [])
    }
    hits: list[dict[str, Any]] = []
    for source in sources:
        quality = source.get("transcript_quality", {})
        risk_classification = quality.get("risk_classification") or (
            "usable" if quality.get("appears_usable") else "suspicious_high_risk"
        )
        for segment in source.get("segments", []):
            marker_time = _coerce_float(segment.get("start"), 0.0)
            candidate_ids = _candidate_ids_covering_marker(source["source_id"], marker_time, candidates)
            unrendered_candidate_ids = _candidate_ids_covering_marker(
                source["source_id"], marker_time, unrendered_candidates
            )
            for hit in _iter_audit_marker_hits(segment):
                if risk_classification != "usable":
                    status = "suspicious-source"
                    reason = f"Source transcript classification is {risk_classification}."
                elif candidate_ids:
                    status = "covered"
                    reason = "Marker timestamp is covered by one or more fully rendered candidate windows."
                elif unrendered_candidate_ids:
                    status = "indexed-unrendered"
                    reason = (
                        "Marker timestamp is preserved in the all-candidates index but rich frame/audio "
                        "evidence was not rendered in this run."
                    )
                elif (_safe_text(source.get("source_id")), round(marker_time, 3)) in mentioned_times:
                    status = "mentioned_not_asked"
                    reason = (
                        f"Said in passing, not asked for: listed in {MENTIONED_NOT_ASKED_MARKDOWN} for the "
                        "operator to decide."
                    )
                else:
                    status = "uncovered"
                    reason = "UNCOVERED EXPLICIT MARKER: no candidate window covers this marker timestamp."
                hits.append(
                    {
                        "source_filename": source.get("source_filename"),
                        "source_id": source.get("source_id"),
                        "timestamp_seconds": round(marker_time, 3),
                        "timestamp": _format_timestamp(marker_time),
                        "segment_id": segment.get("id"),
                        "marker_phrase": hit["marker_phrase"],
                        "surrounding_transcript_snippet": hit["snippet"],
                        "candidate_ids": [*candidate_ids, *unrendered_candidate_ids],
                        "rendered_candidate_ids": candidate_ids,
                        "unrendered_candidate_ids": unrendered_candidate_ids,
                        "status": status,
                        "reason": reason,
                        "risk_classification": risk_classification,
                    }
                )
    status_counts = {
        status: sum(1 for hit in hits if hit["status"] == status)
        for status in ("covered", "indexed-unrendered", "uncovered", "suspicious-source", "mentioned_not_asked")
    }
    by_source: dict[str, dict[str, Any]] = {}
    for hit in hits:
        source_key = _safe_text(hit.get("source_id")) or _safe_text(hit.get("source_filename"))
        if source_key not in by_source:
            by_source[source_key] = {
                "source_filename": hit.get("source_filename"),
                "source_id": hit.get("source_id"),
                "explicit_marker_hits": 0,
                "covered_marker_hits": 0,
                "indexed_unrendered_marker_hits": 0,
                "uncovered_marker_hits": 0,
                "suspicious_source_marker_hits": 0,
            }
        by_source[source_key]["explicit_marker_hits"] += 1
        if hit["status"] == "covered":
            by_source[source_key]["covered_marker_hits"] += 1
        elif hit["status"] == "indexed-unrendered":
            by_source[source_key]["indexed_unrendered_marker_hits"] += 1
        elif hit["status"] == "uncovered":
            by_source[source_key]["uncovered_marker_hits"] += 1
        elif hit["status"] == "suspicious-source":
            by_source[source_key]["suspicious_source_marker_hits"] += 1
    summary = {
        "explicit_marker_hits": len(hits),
        "covered_marker_hits": status_counts["covered"],
        "indexed_unrendered_marker_hits": status_counts["indexed-unrendered"],
        "uncovered_marker_hits": status_counts["uncovered"],
        "suspicious_source_marker_hits": status_counts["suspicious-source"],
        "mentioned_not_asked_marker_hits": status_counts["mentioned_not_asked"],
        "status_counts": status_counts,
        "source_count_with_marker_hits": len(by_source),
        "by_source": list(by_source.values()),
    }
    return {
        "generated_at": _utc_now(),
        "summary": summary,
        "markers": hits,
    }


def _marker_audit_summary_lines(summary: dict[str, Any]) -> list[str]:
    return [
        "## Marker Coverage",
        "",
        f"- Explicit marker hits: {summary.get('explicit_marker_hits', 0)}",
        f"- Covered marker hits: {summary.get('covered_marker_hits', 0)}",
        f"- Indexed but not richly rendered marker hits: {summary.get('indexed_unrendered_marker_hits', 0)}",
        f"- Uncovered marker hits: {summary.get('uncovered_marker_hits', 0)}",
        f"- Suspicious-source marker hits: {summary.get('suspicious_source_marker_hits', 0)}",
        f"- Review-needed items: {summary.get('review_needed_count', 0)}",
        f"- Visual follow-up required: {summary.get('visual_followup_required_count', 0)}",
        "",
    ]


def _build_marker_audit_markdown(marker_audit: dict[str, Any]) -> str:
    summary = marker_audit.get("summary", {})
    lines = ["# Marker Audit", "", *_marker_audit_summary_lines(summary)]
    if summary.get("uncovered_marker_hits", 0):
        lines.extend(
            [
                "UNCOVERED EXPLICIT MARKER hits exist. Inspect these before trusting candidate count.",
                "",
            ]
        )
    if summary.get("indexed_unrendered_marker_hits", 0):
        lines.extend(
            [
                "Some marker hits are indexed but do not have rich frame/audio evidence in this run. Review `ALL_CANDIDATES.md` or rerun selected IDs.",
                "",
            ]
        )
    markers = marker_audit.get("markers", [])
    if not markers:
        lines.append("No explicit marker hits were found in the available transcript segments.")
        return "\n".join(lines).rstrip() + "\n"
    for hit in markers:
        marker_label = "UNCOVERED EXPLICIT MARKER: " if hit.get("status") == "uncovered" else ""
        if hit.get("status") == "indexed-unrendered":
            marker_label = "INDEXED, NOT RICHLY RENDERED: "
        lines.extend(
            [
                f"## {marker_label}{hit.get('source_filename')} {hit.get('timestamp')}",
                "",
                f"- Source ID: {hit.get('source_id')}",
                f"- Marker phrase: {hit.get('marker_phrase')}",
                f"- Status: {hit.get('status')}",
                f"- Candidate IDs: {', '.join(hit.get('candidate_ids') or []) or 'none'}",
                f"- Reason: {hit.get('reason')}",
                "",
                hit.get("surrounding_transcript_snippet") or "",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _source_transcript_is_scannable(source: dict[str, Any]) -> bool:
    """Only scan text that is the operator's narration (94).

    Failed or quality-blocked transcripts, silent microphone tracks and text
    Whisper invented on silence must not become ticket candidates.
    """

    if _safe_text(source.get("status")).lower() not in {"completed", "skipped"}:
        return False
    quality = source.get("transcript_quality") or {}
    if quality.get("quality_status") == "no_narration_found":
        return False
    return True


def detect_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    output_dir_value = _safe_text(payload.get("output_dir"))
    if not output_dir_value:
        raise ValueError("output_dir is required.")
    output_dir = Path(output_dir_value)
    pre_context = max(0.0, _coerce_float(payload.get("pre_context_seconds"), 120.0))
    post_context = max(0.0, _coerce_float(payload.get("post_context_seconds"), 240.0))
    merge_gap = max(0.0, _coerce_float(payload.get("merge_gap_seconds"), MERGE_GAP_SECONDS))
    max_items = max(0, _coerce_int(payload.get("max_items"), 50))
    frame_offsets = _normalize_offsets(payload.get("frame_offsets_seconds"))
    frame_cadence = max(0.0, _coerce_float(payload.get("frame_cadence_seconds"), FRAME_CADENCE_SECONDS))
    max_frames = max(0, _coerce_int(payload.get("max_frames_per_candidate"), MAX_FRAMES_PER_CANDIDATE))
    narration_settings = EvidenceNarrationSettings.from_payload(payload)
    fragmented_narration_mode = narration_settings.fragmented_narration_mode
    narration_context_pre = narration_settings.narration_context_pre_seconds
    narration_context_post = narration_settings.narration_context_post_seconds
    narration_pause_threshold = narration_settings.narration_pause_threshold_seconds
    narration_stop_at_next_ticket_boundary = (
        narration_settings.narration_stop_at_next_ticket_boundary
    )
    render_candidate_ids = _normalize_candidate_ids(payload.get("render_candidate_ids"))
    render_outcome_ids = _normalize_candidate_ids(payload.get("render_outcome_ids"))
    stop_after = _safe_text(payload.get("stop_after")) or "Package"
    preserve_supporting_audio = _coerce_bool(
        payload.get("preserve_supporting_audio")
        or payload.get("evidence_preserve_supporting_audio"),
        False,
    )
    evidence_handoff_mode = _safe_text(payload.get("evidence_handoff_mode")) or "Local"
    if evidence_handoff_mode.lower() not in {"local", "portablezip", "both"}:
        evidence_handoff_mode = "Local"
    portable_zip_max_mb = max(1, _coerce_int(payload.get("evidence_portable_zip_max_mb"), 100))
    panel_crop_mode = _normalize_panel_crop_mode(payload.get("panel_crop_mode", PANEL_CROP_MODE_DEFAULT))
    panel_role_mapping = _load_panel_role_mapping(payload)
    raw_run_metadata = payload.get("run_metadata") or {}
    run_metadata = (
        {
            key: _safe_text(raw_run_metadata.get(key))
            for key in (
                "target_project",
                "target_repository",
                "application_version",
                "profile_setup_name",
                "dashboard_revision",
                "test_conditions",
                "configuration_notes",
            )
        }
        if isinstance(raw_run_metadata, dict)
        else {}
    )
    repo_hint_context = _build_repo_hint_context(payload)
    detection_terms = _build_detection_terms(payload)
    transcription_glossary = load_transcription_glossary(payload)
    sources = [
        _normalize_source(
            dict(source),
            detection_terms["quality_marker_terms"],
            transcription_glossary["entries"],
        )
        for source in (payload.get("sources") or [])
    ]
    narration_sources = [
        source
        for source in sources
        if source.get("transcript_audio_role") != "supporting_audio"
        and _source_transcript_is_scannable(source)
    ]
    events = _build_events(narration_sources, pre_context, post_context, detection_terms["markers"])
    windows = _merge_events(events, merge_gap)
    candidates, unrendered_candidates, all_candidates = _build_candidates(
        windows,
        output_dir,
        frame_offsets,
        max_items,
        frame_cadence,
        max_frames,
        panel_crop_mode,
        panel_role_mapping["definitions"],
        detection_terms["markers"],
        fragmented_narration_mode,
        narration_context_pre,
        narration_context_post,
        narration_pause_threshold,
        narration_stop_at_next_ticket_boundary,
        render_candidate_ids,
        preserve_supporting_audio,
    )
    legacy_truncated_candidate_count = len(unrendered_candidates)
    for candidate in all_candidates:
        candidate["run_metadata"] = dict(run_metadata)
    _apply_repo_hints(all_candidates, repo_hint_context)
    outcomes = consolidate_candidate_outcomes(all_candidates)
    render_candidates, unrendered_candidates = _apply_outcome_render_policy(
        all_candidates,
        outcomes,
        render_outcome_ids,
        render_candidate_ids,
        stop_after=stop_after,
    )
    legacy_candidates = [
        candidate for candidate in all_candidates if candidate.get("legacy_render_selected")
    ]
    review_needed = _build_review_needed_items(
        narration_sources,
        all_candidates,
        pre_context,
        post_context,
        detection_terms["review_needed_domain_terms"],
    )
    source_by_id = {source.get("source_id"): source for source in narration_sources}
    candidate_by_id = {candidate.get("evidence_id"): candidate for candidate in all_candidates}
    requested_outcomes = set(render_outcome_ids)
    for outcome in outcomes:
        if (
            outcome.get("render_eligible")
            or outcome.get("outcome_id") in requested_outcomes
            or outcome.get("primary_candidate_id") in set(render_candidate_ids)
        ):
            continue
        candidate = candidate_by_id.get(outcome.get("primary_candidate_id")) or {}
        source = source_by_id.get(candidate.get("source_id")) or {}
        marker_time = _coerce_float(candidate.get("marker_timestamp_seconds"))
        review_needed.append(
            {
                "review_id": f"review-{len(review_needed) + 1:03d}",
                "source_id": candidate.get("source_id", ""),
                "source_identifier": source.get("source_identifier", ""),
                "source_filename": source.get("source_filename", candidate.get("source_filename", "")),
                "source_path": source.get("source_path", candidate.get("source_path", "")),
                "timestamp_start_seconds": marker_time,
                "timestamp_end_seconds": marker_time,
                "timestamp_start": _format_timestamp(marker_time),
                "timestamp_end": _format_timestamp(marker_time),
                "marker_timestamp_seconds": marker_time,
                "marker_timestamp": _format_timestamp(marker_time),
                "confidence": outcome.get("confidence", "weak"),
                "reason": "low_confidence_outcome_requires_selection",
                "promotion_status": "outcome_confirmation_required",
                "implicit_phrases": [],
                "domain_terms": [],
                "candidate_ids_covering_time": [outcome.get("primary_candidate_id")],
                "outcome_id": outcome.get("outcome_id"),
                "visual_followup_required": False,
                "transcript_excerpt": outcome.get("intent_summary", ""),
                "notes_for_reviewer": "This outcome remains text-only until the operator explicitly selects it for rendering.",
                "source_transcript_quality": source.get("transcript_quality", {}),
            }
        )
    review_summary = _review_needed_summary(review_needed)
    mentioned_not_asked = build_mentioned_not_asked(narration_sources, all_candidates, detection_terms["markers"])
    marker_audit = _build_marker_audit(
        narration_sources, legacy_candidates, unrendered_candidates, mentioned_not_asked
    )
    marker_audit["summary"].update(review_summary)
    frame_tasks, audio_tasks = _canonicalize_source_artifacts(render_candidates, output_dir)
    confidence_counts = {
        confidence: sum(
            1 for candidate in legacy_candidates if candidate["confidence"] == confidence
        )
        for confidence in ("explicit", "likely", "weak")
    }
    detected_confidence_counts = {
        confidence: sum(1 for candidate in all_candidates if candidate["confidence"] == confidence)
        for confidence in ("explicit", "likely", "weak")
    }
    quality_summary = _quality_summary(sources)
    repo_hint_config = _public_repo_hint_config(repo_hint_context)
    repo_summary = _repo_hint_summary(all_candidates, {"repo_hinting": repo_hint_config})
    return {
        "schema_version": EVIDENCE_PACKAGE_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "output_dir": str(output_dir),
        "configuration": {
            "pre_context_seconds": pre_context,
            "post_context_seconds": post_context,
            "merge_gap_seconds": merge_gap,
            "frame_offsets_seconds": frame_offsets,
            "frame_cadence_seconds": frame_cadence,
            "max_frames_per_candidate": max_frames,
            "max_items": max_items,
            "render_candidate_ids": render_candidate_ids,
            "render_outcome_ids": render_outcome_ids,
            "stop_after": stop_after,
            "evidence_handoff_mode": evidence_handoff_mode,
            "evidence_portable_zip_max_mb": portable_zip_max_mb,
            "pause_threshold_seconds": PAUSE_THRESHOLD_SECONDS,
            "fragmented_narration_mode": fragmented_narration_mode,
            "narration_context_pre_seconds": narration_context_pre,
            "narration_context_post_seconds": narration_context_post,
            "narration_pause_threshold_seconds": narration_pause_threshold,
            "narration_stop_at_next_ticket_boundary": narration_stop_at_next_ticket_boundary,
            "audio_snippet_max_seconds": AUDIO_SNIPPET_MAX_SECONDS,
            "panel_crops": _panel_crop_configuration(
                panel_crop_mode,
                panel_role_mapping["definitions"],
            ),
            "panel_role_mapping_source_path": panel_role_mapping["source_path"],
            "panel_role_mapping_warning": panel_role_mapping["warning"],
            "invocation_mode": _safe_text(payload.get("invocation_mode")) or "standalone",
            "repo_hinting": repo_hint_config,
            "custom_marker_count": detection_terms["custom_marker_count"],
            "custom_domain_term_count": detection_terms["custom_domain_term_count"],
            "transcription_glossary": transcription_glossary,
            "whisper_initial_prompt": build_whisper_initial_prompt(
                transcription_glossary["entries"]
            ),
            "operator_narration_source_count": len(narration_sources),
            "supporting_audio_source_count": len(sources) - len(narration_sources),
            "preserve_supporting_audio": preserve_supporting_audio,
            "require_artifact_integrity": True,
            "run_metadata": run_metadata,
        },
        "sources": sources,
        # `candidates` remains the backward-compatible detection-budget view.
        # New writers and renderers must use `render_candidates`.
        "candidates": legacy_candidates,
        "render_candidates": render_candidates,
        "unrendered_candidates": unrendered_candidates,
        "all_candidates": all_candidates,
        "outcomes": outcomes,
        "outcome_count": len(outcomes),
        "review_needed": review_needed,
        "candidate_count": len(legacy_candidates),
        "rendered_primary_candidate_count": len(render_candidates),
        "detected_candidate_count": len(all_candidates),
        "unrendered_candidate_count": len(unrendered_candidates),
        "review_needed_count": len(review_needed),
        "mentioned_not_asked": mentioned_not_asked,
        "visual_followup_required_count": review_summary["visual_followup_required_count"],
        "detected_window_count": len(windows),
        "truncated_candidates_count": legacy_truncated_candidate_count,
        "confidence_counts": confidence_counts,
        "detected_confidence_counts": detected_confidence_counts,
        "quality_summary": quality_summary,
        "repo_hint_summary": repo_summary,
        "marker_audit": marker_audit,
        "marker_audit_summary": marker_audit["summary"],
        "transcript_corrections": _transcript_correction_audit(
            sources,
            transcription_glossary,
        ),
        "frame_tasks": frame_tasks,
        "audio_tasks": audio_tasks,
    }


def _apply_artifact_results(candidates: list[dict[str, Any]], artifact_results: dict[str, Any]) -> None:
    frame_updates = {
        _safe_text(item.get("relative_path")): item
        for item in artifact_results.get("frames", [])
        if _safe_text(item.get("relative_path"))
    }
    audio_updates = {
        _safe_text(item.get("relative_path")): item
        for item in artifact_results.get("audio", [])
        if _safe_text(item.get("relative_path"))
    }
    for candidate in candidates:
        for frame in candidate.get("frames", []):
            update = frame_updates.get(_safe_text(frame.get("canonical_source_relative_path"))) or frame_updates.get(
                _safe_text(frame.get("relative_path"))
            ) or frame_updates.get(_safe_text(frame.get("legacy_relative_path"))) or frame_updates.get(
                _safe_text(frame.get("legacy_v092_relative_path"))
            )
            if update:
                frame["status"] = _safe_text(update.get("status")) or frame.get("status", "")
                frame["error_message"] = _safe_text(update.get("error_message"))
                frame["path"] = _safe_text(update.get("path")) or frame.get("path", "")
                frame["full_frame_path"] = _safe_text(update.get("full_frame_path")) or frame.get("full_frame_path", frame.get("path", ""))
                frame["full_frame_width"] = update.get("full_frame_width", frame.get("full_frame_width", ""))
                frame["full_frame_height"] = update.get("full_frame_height", frame.get("full_frame_height", ""))
                if "panel_crop_mode" in update:
                    frame["panel_crop_mode"] = _safe_text(update.get("panel_crop_mode")) or frame.get("panel_crop_mode", "")
                frame["panel_detection"] = _safe_text(update.get("panel_detection")) or frame.get("panel_detection", "")
                if "panels" in update:
                    panel_updates = {
                        _safe_text(panel.get("role")): panel
                        for panel in update.get("panels", [])
                        if _safe_text(panel.get("role"))
                    }
                    for panel in frame.get("panels", []):
                        panel_update = panel_updates.get(_safe_text(panel.get("role")))
                        if not panel_update:
                            continue
                        panel["status"] = _safe_text(panel_update.get("status")) or panel.get("status", "")
                        panel["error_message"] = _safe_text(panel_update.get("error_message"))
                        panel["path"] = _safe_text(panel_update.get("path")) or panel.get("path", "")
                        panel["relative_path"] = _safe_text(panel_update.get("relative_path")) or panel.get("relative_path", "")
                        for field in (
                            "crop_x",
                            "crop_y",
                            "crop_width",
                            "crop_height",
                            "panel_image_width",
                            "panel_image_height",
                        ):
                            if field in panel_update:
                                panel[field] = panel_update.get(field, panel.get(field, ""))
        audio = candidate.get("audio_snippet") or {}
        for audio in [audio, *(candidate.get("supporting_audio_snippets") or [])]:
            update = audio_updates.get(_safe_text(audio.get("canonical_source_relative_path"))) or audio_updates.get(
                _safe_text(audio.get("relative_path"))
            ) or audio_updates.get(_safe_text(audio.get("legacy_relative_path")))
            if update:
                audio["status"] = _safe_text(update.get("status")) or audio.get("status", "")
                audio["error_message"] = _safe_text(update.get("error_message"))
                audio["path"] = _safe_text(update.get("path")) or audio.get("path", "")


def _artifact_integrity_report(
    output_dir: Path,
    candidates: list[dict[str, Any]],
    artifact_results: dict[str, Any],
    *,
    enforce: bool,
) -> dict[str, Any]:
    categories: dict[str, dict[str, dict[str, Any]]] = {
        "frames": {},
        "panels": {},
        "audio": {},
    }
    planned_reference_counts = {name: 0 for name in categories}

    def register(category: str, item: dict[str, Any], candidate_id: str) -> None:
        relative_path = _safe_text(
            item.get("canonical_source_relative_path") or item.get("relative_path")
        ).replace("\\", "/")
        if not relative_path:
            relative_path = f"missing-reference/{category}/{candidate_id}"
        planned_reference_counts[category] += 1
        record = categories[category].setdefault(
            relative_path,
            {
                "artifact_id": _safe_text(item.get("artifact_id")),
                "relative_path": relative_path,
                "status": _safe_text(item.get("status")) or "pending",
                "error_message": _safe_text(item.get("error_message")),
                "candidate_ids": [],
            },
        )
        if candidate_id not in record["candidate_ids"]:
            record["candidate_ids"].append(candidate_id)
        if _safe_text(item.get("status")):
            record["status"] = _safe_text(item.get("status"))
        if _safe_text(item.get("error_message")):
            record["error_message"] = _safe_text(item.get("error_message"))

    for candidate in candidates:
        candidate_id = _safe_text(candidate.get("evidence_id"))
        for frame in candidate.get("frames") or []:
            register("frames", frame, candidate_id)
            for panel in frame.get("panels") or []:
                register("panels", panel, candidate_id)
        for snippet in [
            candidate.get("audio_snippet") or {},
            *(candidate.get("supporting_audio_snippets") or []),
        ]:
            if _safe_text(snippet.get("status")) != "not_rendered":
                register("audio", snippet, candidate_id)

    result_paths: dict[str, set[str]] = {name: set() for name in categories}
    for result in artifact_results.get("frames") or []:
        relative = _safe_text(result.get("relative_path")).replace("\\", "/")
        if relative:
            result_paths["frames"].add(relative)
        for panel in result.get("panels") or []:
            panel_relative = _safe_text(panel.get("relative_path")).replace("\\", "/")
            if panel_relative:
                result_paths["panels"].add(panel_relative)
    for result in artifact_results.get("audio") or []:
        relative = _safe_text(result.get("relative_path")).replace("\\", "/")
        if relative:
            result_paths["audio"].add(relative)

    category_summaries: dict[str, dict[str, Any]] = {}
    missing_required: list[dict[str, str]] = []
    counter_disagreements: list[str] = []
    compatibility_reference_issues: list[dict[str, str]] = []
    for category, records_by_path in categories.items():
        records = list(records_by_path.values())
        successful_statuses = {"completed", "created", "generated"}
        for record in records:
            local_path = output_dir / record["relative_path"]
            record["exists"] = local_io_path(local_path).is_file()
            status = record["status"].lower()
            if enforce and (status not in successful_statuses | {"skipped"} or not record["exists"]):
                missing_required.append(
                    {
                        "artifact_id": record["artifact_id"],
                        "relative_path": record["relative_path"],
                        "status": record["status"],
                    }
                )
        written = sum(
            1
            for record in records
            if record["status"].lower() in successful_statuses and record["exists"]
        )
        skipped = sum(1 for record in records if record["status"].lower() == "skipped")
        failed = sum(
            1
            for record in records
            if record["status"].lower() == "failed"
            or (
                enforce
                and record["status"].lower() in successful_statuses
                and not record["exists"]
            )
        )
        pending = sum(
            1
            for record in records
            if record["status"].lower() not in successful_statuses | {"skipped", "failed"}
        )
        if enforce and len(records) != len(result_paths[category]):
            counter_disagreements.append(
                f"{category}: deduplicated plan {len(records)} != renderer results {len(result_paths[category])}"
            )
        category_summaries[category] = {
            "planned_reference_count": planned_reference_counts[category],
            "deduplicated_count": len(records),
            "renderer_result_count": len(result_paths[category]),
            "written_count": written,
            "skipped_count": skipped,
            "failed_count": failed,
            "pending_count": pending,
            "artifacts": records,
        }

    for candidate in candidates:
        candidate_id = _safe_text(candidate.get("evidence_id"))
        for frame in candidate.get("frames") or []:
            canonical = _safe_text(frame.get("canonical_source_relative_path")).replace("\\", "/")
            for field in ("relative_path", "full_frame_relative_path"):
                value = _safe_text(frame.get(field)).replace("\\", "/")
                if canonical and value and value != canonical:
                    compatibility_reference_issues.append(
                        {"candidate_id": candidate_id, "field": field, "relative_path": value}
                    )
            for panel in frame.get("panels") or []:
                canonical_panel = _safe_text(panel.get("canonical_source_relative_path")).replace("\\", "/")
                relative_panel = _safe_text(panel.get("relative_path")).replace("\\", "/")
                if canonical_panel and relative_panel and relative_panel != canonical_panel:
                    compatibility_reference_issues.append(
                        {
                            "candidate_id": candidate_id,
                            "field": "panel.relative_path",
                            "relative_path": relative_panel,
                        }
                    )

    totals = {
        field: sum(int(summary[field]) for summary in category_summaries.values())
        for field in (
            "planned_reference_count",
            "deduplicated_count",
            "renderer_result_count",
            "written_count",
            "skipped_count",
            "failed_count",
            "pending_count",
        )
    }
    passed = bool(
        enforce
        and not missing_required
        and not counter_disagreements
        and not compatibility_reference_issues
    )
    return {
        "schema_version": 1,
        "generated_at": _utc_now(),
        "status": "passed" if passed else ("failed" if enforce else "not_evaluated"),
        "enforced": enforce,
        "primary_render_candidate_count": len(candidates),
        "categories": category_summaries,
        "totals": totals,
        "missing_required_artifacts": missing_required,
        "counter_disagreements": counter_disagreements,
        "compatibility_reference_issues": compatibility_reference_issues,
        "all_required_paths_exist": not missing_required,
        "counters_reconciled": not counter_disagreements,
    }


def _artifact_integrity_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Evidence Integrity Report",
        "",
        f"Status: **{str(report.get('status') or 'unknown').upper()}**",
        "",
        "Counts describe planned references, deduplicated artifacts, renderer results, files written, skipped items, and failures separately.",
        "",
    ]
    for name in ("frames", "panels", "audio"):
        summary = (report.get("categories") or {}).get(name) or {}
        lines.append(
            f"- {name}: planned references {summary.get('planned_reference_count', 0)}; "
            f"deduplicated {summary.get('deduplicated_count', 0)}; "
            f"renderer results {summary.get('renderer_result_count', 0)}; "
            f"written {summary.get('written_count', 0)}; skipped {summary.get('skipped_count', 0)}; "
            f"failed {summary.get('failed_count', 0)}; pending {summary.get('pending_count', 0)}"
        )
    if report.get("counter_disagreements"):
        lines.extend(["", "## Counter disagreements", ""])
        lines.extend(f"- {item}" for item in report["counter_disagreements"])
    if report.get("missing_required_artifacts"):
        lines.extend(["", "## Missing required artifacts", ""])
        lines.extend(
            f"- {item.get('artifact_id') or 'unknown'}: `{item.get('relative_path')}` ({item.get('status')})"
            for item in report["missing_required_artifacts"]
        )
    return "\n".join(lines).rstrip() + "\n"


def _is_one_folder_name(name: str) -> bool:
    return bool(name) and name not in {".", ".."} and not any(char in name for char in '<>:"/\\|?*\0')


def _remove_skipped_source_files(output_dir: Path, physical_source_id: str, source_id: str = "") -> None:
    """Every file of the package made from one recording: transcripts, their side files, audio,
    and its rendered media (screenshots, audio excerpts, narration clips and review video), also
    when an earlier run of this package or a skip made while it was built left them (196)."""

    if _is_one_folder_name(source_id):
        artifacts = output_dir / "artifacts"
        for folder in (
            artifacts / "sources" / source_id,
            artifacts / "sources" / _compact_artifact_source_token(source_id),
            artifacts / "narration" / source_id,
        ):
            folder_path = local_io_path(folder)
            if folder_path.is_dir():
                shutil.rmtree(folder_path)
    if not physical_source_id:
        return
    # Matched by name, not glob: a source id may hold characters glob reads as patterns.
    folders_and_names = (
        (output_dir / "transcript" / "sources", (f"{physical_source_id}.transcript.", f"{physical_source_id}.voice.json")),
        (output_dir / "transcript" / "raw" / "sources", (f"{physical_source_id}.transcript.",)),
        (output_dir / "audio", (f"{physical_source_id}.audio.",)),
    )
    for folder, prefixes in folders_and_names:
        folder_path = local_io_path(folder)
        if not folder_path.is_dir():
            continue
        for path in folder_path.iterdir():
            if path.is_file() and any(path.name.startswith(prefix) for prefix in prefixes):
                path.unlink()


def _remove_stale_ticket_folders(output_dir: Path, evidence_ids: set[str]) -> None:
    """196: ticket folders an earlier writing of this package left that are not tickets now.

    When a recording is skipped the tickets are numbered again, so a folder beyond the new count
    is an old ticket, possibly of the skipped recording, that must not be handed on."""

    evidence_root = local_io_path(output_dir / "evidence_items")
    if not evidence_root.is_dir():
        return
    for folder in evidence_root.iterdir():
        if folder.is_dir() and folder.name not in evidence_ids:
            shutil.rmtree(folder)


def _remove_stale_portable_zip(output_dir: Path) -> None:
    """196: a portable ZIP an earlier run made, and its reports, when this run makes none.

    Only called when a recording was skipped: the old ZIP holds it and would be offered as current."""

    for name in (PORTABLE_ZIP_FILENAME, "PORTABLE_PRIVACY_REPORT.json", "OMITTED_MEDIA.json", "OMITTED_MEDIA.md"):
        path = local_io_path(output_dir / name)
        if path.is_file():
            path.unlink()


def _remove_stale_narration_index(output_dir: Path) -> None:
    """196: the narration visuals' index and plan an earlier writing of this package left.

    Only called when a recording was skipped: they quote every recording's narration, the skipped
    one's too. The portable ZIP is made before the narration visuals are written again (and Stop
    after Consolidation makes none), so it would take them as they are."""

    for path in (
        output_dir / NARRATION_INDEX_JSON,
        output_dir / NARRATION_INDEX_MARKDOWN,
        output_dir / "artifacts" / "narration" / "plan.json",
    ):
        path = local_io_path(path)
        if path.is_file():
            path.unlink()


def _remove_stale_operator_drafts(output_dir: Path) -> None:
    """196: prompt drafts the Workbench's Export prompts wrote into the package.

    Only called when a recording was skipped: a ticket's draft quotes its recording, and after the
    skip the tickets are numbered again. The session drafts are written again with the package."""

    drafts = local_io_path(output_dir / "operator-drafts")
    if drafts.is_dir():
        shutil.rmtree(drafts)


# 201: where a recording's transcripts were; blank in the manifest once it is skipped.
SKIPPED_SOURCE_TRANSCRIPT_PATH_KEYS = (
    "transcript_json_path",
    "transcript_srt_path",
    "transcript_txt_path",
    "raw_transcript_json_path",
    "raw_transcript_srt_path",
    "raw_transcript_txt_path",
    "reused_transcript_json_path",
    "reused_transcript_srt_path",
    "reused_transcript_txt_path",
    "transcript_raw_json_path",
    "transcript_vad_json_path",
    "transcript_quality_json_path",
)


def _copy_transcript_sources(output_dir: Path, sources: list[dict[str, Any]]) -> None:
    sources_dir = output_dir / "transcript" / "sources"
    raw_sources_dir = output_dir / "transcript" / "raw" / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    raw_sources_dir.mkdir(parents=True, exist_ok=True)
    for source in sources:
        source_id = source.get("source_id") or "source"
        physical_source_id, physical_source_id_shortened = (
            _bounded_transcript_physical_source_id(output_dir, source_id)
        )
        source["physical_source_id"] = physical_source_id
        source["physical_source_id_shortened"] = physical_source_id_shortened
        if _skipped_by_operator(source):
            # 196: no copy and no empty placeholder, and nothing an earlier
            # run of this package left of it (Continue) stays behind.
            _remove_skipped_source_files(output_dir, physical_source_id, _safe_text(source_id))
            # Its audio was removed with it, whenever it was skipped; the
            # manifest must not point at it or call it extracted.
            source.update({"audio_path": "", "audio_status": "not_in_package", "transcription_input_path": ""})
            # 201: nor at its transcripts, which went too.
            source.update({key: "" for key in SKIPPED_SOURCE_TRANSCRIPT_PATH_KEYS if key in source})
            continue
        # When a package is written again (Continue), a reused transcript
        # points at this package's own corrected copy, which this function
        # wrote last time with a correction_count. Copying it would replace
        # what Whisper heard with the corrected wording, so the raw copy is
        # kept, or rebuilt below from each segment's raw_text if it is missing.
        transcript_json = Path(_safe_text(source.get("transcript_json_path")))
        if (
            transcript_json.name
            and transcript_json.resolve()
            == (sources_dir / f"{physical_source_id}.transcript.json").resolve()
            and "correction_count" in _read_transcript_payload(str(transcript_json))
        ):
            copy_keys: tuple[tuple[str, str], ...] = ()
        else:
            copy_keys = (
                ("transcript_json_path", ".transcript.json"),
                ("transcript_srt_path", ".transcript.srt"),
                ("transcript_txt_path", ".transcript.txt"),
            )
        for key, suffix in copy_keys:
            source_path = Path(_safe_text(source.get(key)))
            if not local_io_path(source_path).is_file():
                continue
            raw_destination = raw_sources_dir / f"{physical_source_id}{suffix}"
            if source_path.resolve() != raw_destination.resolve():
                shutil.copyfile(source_path, raw_destination)

        raw_result = {
            "language": source.get("transcript_language", ""),
            "segments": [
                {**dict(segment), "text": segment.get("raw_text") or segment.get("text", "")}
                for segment in source.get("raw_segments") or []
            ],
        }
        raw_json = raw_sources_dir / f"{physical_source_id}.transcript.json"
        raw_srt = raw_sources_dir / f"{physical_source_id}.transcript.srt"
        raw_txt = raw_sources_dir / f"{physical_source_id}.transcript.txt"
        if not all(local_io_path(path).is_file() for path in (raw_json, raw_srt, raw_txt)):
            write_transcript_files(
                raw_sources_dir,
                raw_json.name,
                raw_srt.name,
                raw_txt.name,
                raw_result,
            )

        corrected_json, corrected_srt, corrected_txt = write_transcript_files(
            sources_dir,
            f"{physical_source_id}.transcript.json",
            f"{physical_source_id}.transcript.srt",
            f"{physical_source_id}.transcript.txt",
            {
                "language": source.get("transcript_language", ""),
                "correction_count": source.get("transcript_correction_count", 0),
                "segments": source.get("segments") or [],
            },
        )
        source.update(
            {
                "raw_transcript_json_path": str(raw_json),
                "raw_transcript_srt_path": str(raw_srt),
                "raw_transcript_txt_path": str(raw_txt),
                "transcript_json_path": str(corrected_json),
                "transcript_srt_path": str(corrected_srt),
                "transcript_txt_path": str(corrected_txt),
            }
        )


def _raw_transcript_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw_sources: list[dict[str, Any]] = []
    for source in sources:
        raw_source = dict(source)
        raw_source["segments"] = [
            {**dict(segment), "text": segment.get("raw_text") or segment.get("text", "")}
            for segment in source.get("raw_segments") or []
        ]
        raw_source["transcript_json_path"] = source.get("raw_transcript_json_path", "")
        raw_source["transcript_srt_path"] = source.get("raw_transcript_srt_path", "")
        raw_source["transcript_txt_path"] = source.get("raw_transcript_txt_path", "")
        raw_sources.append(raw_source)
    return raw_sources


def _build_full_transcript_json(sources: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "generated_at": _utc_now(),
        "sources": [
            {
                key: source.get(key)
                for key in (
                    "source_id",
                    "physical_source_id",
                    "physical_source_id_shortened",
                    "source_identifier",
                    "source_filename",
                    "source_path",
                    "duration_seconds",
                    "status",
                    "error_message",
                    "audio_path",
                    "audio_status",
                    "audio_method",
                    "selected_audio_stream_index",
                    "audio_stream_count",
                    "transcription_input_method",
                    "transcript_reuse_status",
                    "transcript_quality",
                    "transcript_json_path",
                    "transcript_srt_path",
                    "transcript_txt_path",
                )
            }
            for source in sources
        ],
        "segments": [
            {
                "source_id": source["source_id"],
                "source_filename": source["source_filename"],
                **segment,
            }
            for source in sources
            for segment in source.get("segments", [])
        ],
    }


def _build_full_transcript_markdown(sources: list[dict[str, Any]]) -> str:
    lines = ["# Full Transcript", ""]
    for source in sources:
        quality = source.get("transcript_quality", {})
        lines.extend(
            [
                f"## {source.get('source_filename') or source.get('source_id')}",
                "",
                f"- Source ID: {source.get('source_id')}",
                f"- Source: {source.get('source_identifier') or source.get('source_path')}",
                f"- Transcript quality: {quality.get('risk_classification') or ('usable' if quality.get('appears_usable') else 'SUSPICIOUS')}",
            ]
        )
        if quality.get("warning_reasons"):
            lines.append(f"- Quality warnings: {'; '.join(quality.get('warning_reasons', []))}")
        lines.append("")
        if not source.get("segments"):
            lines.append("(No transcript segments available.)")
            lines.append("")
            continue
        for segment in source["segments"]:
            lines.append(f"[{segment['timestamp_start']} - {segment['timestamp_end']}] {segment['text']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _window_segments_for_candidate(candidate: dict[str, Any], sources_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    source = sources_by_id.get(candidate["source_id"], {})
    return _segments_in_window(
        source,
        _coerce_float(candidate.get("timestamp_start_seconds")),
        _coerce_float(candidate.get("timestamp_end_seconds")),
    )


def _build_transcript_window_markdown(candidate: dict[str, Any], segments: list[dict[str, Any]]) -> str:
    lines = [
        f"# Transcript Window: {candidate['evidence_id']}",
        "",
        f"- Source: {candidate['source_filename']}",
        f"- Window: {candidate['timestamp_start']} - {candidate['timestamp_end']}",
        f"- Marker: {candidate['marker_timestamp']}",
        f"- Confidence: {candidate['confidence']}",
        f"- Detected markers: {', '.join(candidate['detected_marker_phrases'])}",
        f"- Supporting terms: {', '.join(candidate.get('supporting_marker_phrases', [])) or 'none'}",
        f"- Duplicate role: {candidate.get('duplicate_role', 'primary')}",
        "",
    ]
    if candidate.get("duplicate_of"):
        lines.append(f"- Duplicate/supporting evidence for: {candidate['duplicate_of']}")
        lines.append("")
    previous_end: float | None = None
    for segment in segments:
        start = _coerce_float(segment.get("start"))
        if previous_end is not None:
            gap = start - previous_end
            if gap >= PAUSE_THRESHOLD_SECONDS:
                lines.append(f"[pause: {gap:.1f} seconds]")
        lines.append(f"[{segment['timestamp_start']} - {segment['timestamp_end']}] {segment['text']}")
        previous_end = _coerce_float(segment.get("end"))
    if not segments:
        lines.append("(No transcript segments available in this window.)")
    return "\n".join(lines).rstrip() + "\n"


def _narration_label_text(value: Any) -> str:
    labels = {
        "pre_marker_explanation": "pre-marker explanation",
        "ticket_marker": "ticket marker",
        "post_marker_explanation": "post-marker explanation",
        "possible_continuation_after_driving_pause": "possible continuation after driving pause",
        "explicit_continuation_cue": "explicit continuation cue",
        "closing_boundary": "closing boundary",
    }
    key = _safe_text(value)
    return labels.get(key, key.replace("_", " ") or "speech")


def _candidate_relative_transcript_reference(path: Any) -> str:
    value = _safe_text(path).replace("\\", "/")
    return f"../../{value}" if value else ""


def _build_narration_context_markdown(candidate: dict[str, Any]) -> str:
    context = dict(candidate.get("narration_context") or {})
    focused = dict(context.get("focused_window") or {})
    narration = dict(context.get("narration_window") or {})
    settings = dict(context.get("settings") or {})
    boundary = dict(context.get("boundary") or {})
    full_paths = dict(context.get("full_transcript_paths") or candidate.get("full_transcript_paths") or {})
    lines = [
        f"# Narration Context: {candidate.get('evidence_id', 'candidate')}",
        "",
        f"- Source filename: {candidate.get('source_filename') or 'unknown'}",
        f"- Source identifier: {candidate.get('source_identifier') or candidate.get('source_path') or 'unknown'}",
        f"- Source ID: {candidate.get('source_id') or 'unknown'}",
        f"- Ticket marker timestamp: {context.get('ticket_marker_timestamp') or candidate.get('marker_timestamp') or 'unknown'}",
        f"- Focused visual/audio evidence window: {focused.get('start') or candidate.get('timestamp_start')} - {focused.get('end') or candidate.get('timestamp_end')}",
        f"- Longer narration-context window: {narration.get('start') or 'unknown'} - {narration.get('end') or 'unknown'}",
        f"- Rich evidence status: {candidate.get('render_status', 'rendered')}",
        "",
        "## Narration Settings",
        "",
        f"- Fragmented narration mode: {str(bool(settings.get('fragmented_narration_mode'))).lower()}",
        f"- Narration pre seconds: {settings.get('narration_context_pre_seconds')}",
        f"- Narration post seconds: {settings.get('narration_context_post_seconds')}",
        f"- Driving-pause threshold seconds: {settings.get('narration_pause_threshold_seconds')}",
        f"- Stop at next explicit ticket boundary: {str(bool(settings.get('narration_stop_at_next_ticket_boundary'))).lower()}",
        "- This transcript-only context does not add screenshots or extend the primary audio snippet.",
        "",
        "## Boundary And Continuation Signals",
        "",
        f"- Boundary type: {boundary.get('type') or 'none'}",
        f"- Boundary timestamp: {boundary.get('timestamp') or 'none'}",
        f"- Boundary phrases: {', '.join(boundary.get('phrases') or []) or 'none'}",
        f"- Continuation phrases: {', '.join(context.get('continuation_phrases') or []) or 'none'}",
        f"- New-ticket phrases: {', '.join(context.get('new_ticket_phrases') or []) or 'none'}",
        f"- Closing phrases: {', '.join(context.get('closing_phrases') or []) or 'none'}",
        "",
        "Speech after a driving pause is preserved as possible continuation. It is not automatically asserted to belong to this ticket.",
        "",
        "## Transcript",
        "",
    ]
    entries = list(context.get("entries") or [])
    if not entries:
        lines.append("(No transcript segments available in this narration window.)")
    for entry in entries:
        if entry.get("kind") == "pause":
            lines.append(f"**[driving pause: {_coerce_float(entry.get('duration_seconds')):.1f} seconds]**")
            continue
        label = _narration_label_text(entry.get("label"))
        lines.append(
            f"[{entry.get('timestamp_start')} - {entry.get('timestamp_end')}] "
            f"[{label}] {entry.get('text', '')}"
        )

    lines.extend(
        [
            "",
            "## Related Transcript Files",
            "",
            "- Focused transcript window: `transcript_window.md`",
        ]
    )
    for label, key in (
        ("Source transcript JSON", "source_json"),
        ("Source transcript SRT", "source_srt"),
        ("Source transcript TXT", "source_txt"),
        ("Full transcript JSON", "full_transcript_json"),
        ("Full transcript Markdown", "full_transcript_markdown"),
    ):
        reference = _candidate_relative_transcript_reference(full_paths.get(key))
        if reference:
            lines.append(f"- {label}: `{reference}`")
    if context.get("warning"):
        lines.extend(["", f"WARNING: {context['warning']}"])
    return "\n".join(lines).rstrip() + "\n"


def _repo_hint_reason_text(candidate: dict[str, Any]) -> str:
    return "; ".join(_safe_text(reason) for reason in candidate.get("repo_hint_reason", []) if _safe_text(reason)) or "none"


def _repo_hint_alternates_text(candidate: dict[str, Any]) -> str:
    alternates = candidate.get("alternate_repos", []) or []
    if not alternates:
        return "none"
    return "; ".join(
        f"{item.get('repo', REPO_HINT_UNKNOWN)} (score {item.get('score', 0)}"
        + (f", {item.get('reason')}" if item.get("reason") else "")
        + ")"
        for item in alternates
    )


def _repo_hint_markdown_lines(candidate: dict[str, Any]) -> list[str]:
    return [
        "## Repo Routing Hint",
        "",
        REPO_HINT_REVIEW_WARNING,
        "",
        f"- Likely target repo: {candidate.get('likely_target_repo') or REPO_HINT_UNKNOWN}",
        f"- Target project label: {candidate.get('target_project_label') or 'none'}",
        f"- Repo confidence: {candidate.get('repo_confidence') or 'unknown'}",
        f"- Repo hint source: {candidate.get('repo_hint_source') or 'none'}",
        f"- Repo hint reason: {_repo_hint_reason_text(candidate)}",
        f"- Alternate repos: {_repo_hint_alternates_text(candidate)}",
        f"- Ambiguous repo hint: {str(bool(candidate.get('repo_hint_is_ambiguous'))).lower()}",
        f"- Requires GitHub review: {str(bool(candidate.get('requires_github_review', True))).lower()}",
    ]


def _frame_rows(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for frame in candidate.get("frames", []):
        full_frame_path = frame.get("full_frame_relative_path") or frame.get("relative_path", "")
        base_row = {
            "timestamp_seconds": frame.get("timestamp_seconds", ""),
            "timestamp": frame.get("timestamp", ""),
            "frame_role": frame.get("role", ""),
            "offset_seconds": "" if frame.get("offset_seconds") is None else frame.get("offset_seconds"),
            "full_frame_path": full_frame_path,
            "full_frame_width": frame.get("full_frame_width", ""),
            "full_frame_height": frame.get("full_frame_height", ""),
            "panel_crop_mode": frame.get("panel_crop_mode", ""),
            "panel_detection": frame.get("panel_detection", ""),
        }
        panels = frame.get("panels") or []
        if panels:
            for panel in panels:
                rows.append(
                    {
                        **base_row,
                        "panel_role": panel.get("role", ""),
                        "panel_crop_path": panel.get("relative_path", ""),
                        "panel_crop_x": panel.get("crop_x", ""),
                        "panel_crop_y": panel.get("crop_y", ""),
                        "panel_crop_width": panel.get("crop_width", ""),
                        "panel_crop_height": panel.get("crop_height", ""),
                        "panel_image_width": panel.get("panel_image_width", ""),
                        "panel_image_height": panel.get("panel_image_height", ""),
                        "status": panel.get("status", ""),
                        "error_message": panel.get("error_message", ""),
                    }
                )
        else:
            rows.append(
                {
                    **base_row,
                    "panel_role": "",
                    "panel_crop_path": "",
                    "panel_crop_x": "",
                    "panel_crop_y": "",
                    "panel_crop_width": "",
                    "panel_crop_height": "",
                    "panel_image_width": "",
                    "panel_image_height": "",
                    "status": frame.get("status", ""),
                    "error_message": frame.get("error_message", ""),
                }
            )
    return rows


def _build_ticket_markdown(candidate: dict[str, Any]) -> str:
    all_frames = list(candidate.get("frames") or [])
    marker_time = _coerce_float(candidate.get("marker_timestamp_seconds"), 0.0)
    ranked_frames = sorted(
        all_frames,
        key=lambda frame: (
            abs(_coerce_float(frame.get("timestamp_seconds")) - marker_time),
            _coerce_float(frame.get("timestamp_seconds")),
        ),
    )
    representative_frames: list[dict[str, Any]] = []
    for frame in [*ranked_frames[:1], *all_frames[:1], *all_frames[-1:]]:
        path = _safe_text(frame.get("full_frame_relative_path") or frame.get("relative_path"))
        if path and not any(
            _safe_text(existing.get("full_frame_relative_path") or existing.get("relative_path")) == path
            for existing in representative_frames
        ):
            representative_frames.append(frame)
    representative_frames = representative_frames[:3]
    frame_lines: list[str] = []
    crop_guidance: dict[str, tuple[str, str]] = {}
    for frame in representative_frames:
        dimensions = ""
        if frame.get("full_frame_width") and frame.get("full_frame_height"):
            dimensions = f", {frame.get('full_frame_width')}x{frame.get('full_frame_height')}"
        frame_lines.append(
            f"- Full frame: {frame.get('full_frame_relative_path') or frame.get('relative_path', '')} "
            f"({frame['timestamp']}, {frame.get('role', 'frame')}, {frame['status']}{dimensions})"
            + (f" - {frame['error_message']}" if frame.get("error_message") else "")
        )
        if frame.get("panel_detection") == "three_panel_5760x1080":
            frame_lines.append("  Source-aware panel crops:")
            for panel in frame.get("panels", []):
                role = _safe_text(panel.get("role"))
                crop_guidance[role] = (
                    _safe_text(panel.get("purpose")),
                    ", ".join(panel.get("expected_evidence_types") or []),
                )
                panel_dimensions = ""
                if panel.get("panel_image_width") and panel.get("panel_image_height"):
                    panel_dimensions = f", {panel.get('panel_image_width')}x{panel.get('panel_image_height')}"
                frame_lines.append(
                    f"  - {panel.get('label', panel.get('role', 'panel'))}: {panel.get('relative_path', '')} "
                    f"({panel.get('status', '')}{panel_dimensions})"
                    + (f" - {panel.get('error_message')}" if panel.get("error_message") else "")
                )
        elif frame.get("panel_detection") == "not_applicable":
            frame_lines.append(
                "  Panel crops: skipped because this frame size is not exact 5760x1080."
            )
        elif frame.get("panel_detection") == "disabled":
            frame_lines.append("  Panel crops: disabled by package settings.")
    audio = candidate.get("audio_snippet") or {}
    supporting_audio = list(candidate.get("supporting_audio_snippets") or [])
    run_metadata = candidate.get("run_metadata") or {}
    lines = [
        f"# {candidate['evidence_id']}: {candidate['suggested_issue_title']}",
        "",
        "## Summary",
        "",
        candidate.get("suggested_issue_title") or "Review the detected issue.",
        "",
        "## Requested Action",
        "",
        candidate.get("suggested_issue_title") or "Determine the requested action from the transcript context.",
        "",
        "## Evidence Details",
        "",
        f"- Source: {candidate['source_filename']}",
        f"- Source ID: {candidate['source_id']}",
        f"- Timestamp window: {candidate['timestamp_start']} - {candidate['timestamp_end']}",
        f"- Marker timestamp: {candidate['marker_timestamp']}",
        f"- Confidence: {candidate['confidence']}",
        f"- Detected markers: {', '.join(candidate['detected_marker_phrases'])}",
        f"- Supporting terms: {', '.join(candidate.get('supporting_marker_phrases', [])) or 'none'}",
        f"- Duplicate role: {candidate.get('duplicate_role', 'primary')}",
        f"- Duplicate/supporting evidence for: {candidate.get('duplicate_of') or 'none'}",
        f"- Supporting duplicate evidence IDs: {', '.join(candidate.get('supporting_duplicate_evidence_ids', [])) or 'none'}",
        f"- Not enough evidence: {str(bool(candidate.get('not_enough_evidence'))).lower()}",
        f"- Rich evidence status: {candidate.get('render_status', 'rendered')}",
        f"- Rich evidence skip reason: {candidate.get('render_skip_reason') or 'none'}",
        f"- Repo routing hint: {candidate.get('likely_target_repo') or REPO_HINT_UNKNOWN} ({candidate.get('repo_confidence') or 'unknown'}; source: {candidate.get('repo_hint_source') or 'none'}; GitHub review required: {str(bool(candidate.get('requires_github_review', True))).lower()})",
        f"- Original marker/title text: {candidate.get('original_title_text') or 'not recorded'}",
        f"- Target project: {run_metadata.get('target_project') or 'not provided'}",
        f"- Application version: {run_metadata.get('application_version') or 'not provided'}",
        f"- Profile/setup: {run_metadata.get('profile_setup_name') or 'not provided'}",
        f"- Dashboard revision: {run_metadata.get('dashboard_revision') or 'not provided'}",
        f"- Test conditions: {run_metadata.get('test_conditions') or 'not provided'}",
        f"- Configuration notes: {run_metadata.get('configuration_notes') or 'not provided'}",
        "",
        *_repo_hint_markdown_lines(candidate),
        "",
        "## Required Transcript Review",
        "",
        "This file contains only a shortened excerpt. Do not rely on it alone.",
        "Read `transcript_window.md`, then `narration_context.md`, and inspect the shared full transcript when narration may continue outside the focused window.",
        "",
        "## Transcript Excerpt",
        "",
        candidate.get("transcript_excerpt") or "(No transcript excerpt available.)",
        "",
        "## Visual Evidence",
        "",
        "For detailed inspection, review the panel crops first when available, then the representative full frames. Use each crop's configured purpose; no physical panel is assumed to contain a particular dashboard or UI.",
        "",
        *(frame_lines or ["- No representative frames were planned."]),
        f"- Exhaustive frame inventory: `{candidate.get('frame_index_path') or 'frame_index.csv'}` ({len(all_frames)} planned frame(s))",
        "",
        "## Crop Role Guidance",
        "",
        *(
            [
                f"- {role}: {purpose or 'No purpose configured'}"
                + (f"; expected evidence: {expected}" if expected else "")
                for role, (purpose, expected) in sorted(crop_guidance.items())
            ]
            or ["- No source-aware crop-role metadata was available."]
        ),
        "",
        "## Audio Evidence",
        "",
        f"- {audio.get('relative_path', '')} ({audio.get('status', 'not_available')})"
        + (f" - {audio.get('error_message')}" if audio.get("error_message") else ""),
        "- Role: operator narration used for ticket detection; other detected streams remain supporting metadata.",
        *(
            [
                f"- Supporting stream {item.get('audio_stream_index')}: {item.get('relative_path')} ({item.get('status')})"
                + (f" - {item.get('error_message')}" if item.get("error_message") else "")
                for item in supporting_audio
            ]
            or ["- Supporting audio snippets: not requested."]
        ),
        "",
        "## Transcript Audit",
        "",
        "- Corrected transcript text is used for detection and this title.",
        "- See `../../TRANSCRIPT_CORRECTIONS.md` and `../../transcript/raw/` for the audit trail.",
        "",
        "## Notes For ChatGPT/Codex",
        "",
        candidate.get("notes_for_ai_reviewer", ""),
    ]
    return "\n".join(lines).rstrip() + "\n"


def _quality_summary(sources: list[dict[str, Any]]) -> dict[str, Any]:
    skipped = [
        source
        for source in sources
        if source.get("transcript_quality", {}).get("quality_status") == "skipped_by_operator"
    ]
    suspicious = [
        source
        for source in sources
        if not source.get("transcript_quality", {}).get("appears_usable") and source not in skipped
    ]
    risk_counts = {
        "usable": 0,
        "suspicious_high_risk": 0,
        "suspicious_low_risk_short_clip": 0,
        "suspicious_low_risk_no_marker_terms": 0,
    }
    for source in sources:
        classification = source.get("transcript_quality", {}).get("risk_classification") or (
            "usable" if source.get("transcript_quality", {}).get("appears_usable") else "suspicious_high_risk"
        )
        risk_counts[classification] = risk_counts.get(classification, 0) + 1
    no_narration = [
        source
        for source in sources
        if source.get("transcript_quality", {}).get("quality_status") == "no_narration_found"
    ]
    needs_track_choice = [
        source
        for source in sources
        if source.get("transcript_quality", {}).get("quality_status") == "needs_track_choice"
    ]
    return {
        "source_count": len(sources),
        "no_narration_source_count": len(no_narration),
        # 142: never transcribed, because the app could not tell which track
        # is the microphone. Missing narration, not an empty recording.
        "needs_track_choice_source_count": len(needs_track_choice),
        "skipped_by_operator_source_count": len(skipped),
        "usable_source_count": len(sources) - len(suspicious) - len(skipped),
        "suspicious_source_count": len(suspicious),
        "suspicious_high_risk_source_count": risk_counts.get("suspicious_high_risk", 0),
        "suspicious_low_risk_short_clip_source_count": risk_counts.get("suspicious_low_risk_short_clip", 0),
        "suspicious_low_risk_no_marker_terms_source_count": risk_counts.get("suspicious_low_risk_no_marker_terms", 0),
        "risk_classification_counts": risk_counts,
        "all_sources_suspicious": bool(sources) and len(suspicious) == len(sources) - len(skipped) and len(suspicious) > 0,
    }


def _transcript_correction_audit(
    sources: list[dict[str, Any]],
    glossary: dict[str, Any],
) -> dict[str, Any]:
    corrections = [
        dict(record)
        for source in sources
        for record in source.get("transcript_corrections") or []
    ]
    return {
        "schema_version": 1,
        "generated_at": _utc_now(),
        "glossary_entry_count": int(glossary.get("entry_count") or 0),
        "glossary_alias_count": int(glossary.get("alias_count") or 0),
        "corrected_segment_count": sum(
            1
            for source in sources
            for segment in source.get("segments") or []
            if int(segment.get("correction_count") or 0) > 0
        ),
        "correction_record_count": len(corrections),
        "warnings": list(glossary.get("warnings") or []),
        "corrections": corrections,
    }


def _build_readme(
    candidates: list[dict[str, Any]],
    review_needed: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    configuration: dict[str, Any],
    marker_audit_summary: dict[str, Any],
    unrendered_candidates: list[dict[str, Any]] | None = None,
    outcomes: list[dict[str, Any]] | None = None,
) -> str:
    unrendered_candidates = list(unrendered_candidates or [])
    outcomes = list(outcomes or [])
    quality = _quality_summary(sources)
    warning_lines: list[str] = []
    if quality["suspicious_source_count"]:
        warning_lines = [
            "## Quality Warning",
            "",
            f"{quality['suspicious_source_count']} source transcript(s) were flagged as suspicious.",
            f"High-risk suspicious sources: {quality.get('suspicious_high_risk_source_count', 0)}.",
            f"Low-risk suspicious sources: {quality.get('suspicious_low_risk_short_clip_source_count', 0) + quality.get('suspicious_low_risk_no_marker_terms_source_count', 0)}.",
            "Do not assume no tickets exist in suspicious sources.",
            "",
        ]
    if not candidates and quality["suspicious_source_count"]:
        warning_lines.extend(
            [
                "No candidate tickets were generated, but one or more transcripts were suspicious. Treat this as a transcription-quality failure, not as proof that the recordings contain no ticket requests.",
                "",
            ]
        )
    if quality.get("needs_track_choice_source_count"):
        count = quality["needs_track_choice_source_count"]
        warning_lines.extend(
            [
                "## Recordings Not In This Package Yet",
                "",
                f"{count} recording(s) were not transcribed: the app could not tell which audio track is the "
                "operator's microphone. Their narration is missing, not empty. Do not conclude that nothing was reported "
                "in them; tell the operator those recordings still need a voice-track choice (Find my bug reports, Fix and continue). "
                "See EVIDENCE_QUALITY_REPORT.md for which ones.",
                "",
            ]
        )
    return "\n".join(
        [
            "# Evidence Package Reference",
            "",
            "**Start with `START_HERE_FOR_TICKET_AGENT.md`.** It is the only reading order for this package; this file is background reference.",
            "",
            "This package prepares and organizes evidence. `CONSOLIDATED_OUTCOMES.json` contains PROVISIONAL EVIDENCE CLUSTERS, not final tickets or semantic decisions.",
            "Each provisional cluster records source mentions and timestamps, evidence roles, linked supporting/correction records, confidence and reasons, a deterministic primary-choice reason, unresolved questions, and a repository suggestion for reviewer confirmation.",
            "If a short summary is imperfect, preserve the operator's compound details by following the linked source evidence before recommending ticket work.",
            "",
            *warning_lines,
            "Reference notes:",
            "Check `EVIDENCE_QUALITY_REPORT.md` and `MARKER_AUDIT.md`, especially if uncovered explicit marker hits are reported.",
            "Review `REPO_ROUTING_HINTS.md` before deciding the target repo.",
            "Treat Media Manglers repo hints as suggestions only.",
            "Confirm the target repo and new-vs-existing decision using GitHub issue lookup.",
            "Do not create issues until the operator approves the drafted list.",
            "If a repo hint is UNKNOWN or ambiguous, ask the operator or classify it as needs clarification.",
            "If any source is flagged suspicious, do not assume no tickets exist in that source.",
            "Review `CANDIDATE_TICKETS.md` next.",
            "Review `ALL_CANDIDATES.md` for every detection, including candidates whose rich frame/audio evidence was not rendered.",
            "Review `REVIEW_NEEDED.md` for lower-confidence UI/domain evidence that needs visual follow-up before ticket decisions.",
            "The full transcripts under `transcript/` are the source of truth; the candidate lists come from a keyword scan that misses plain-language bug descriptions.",
            "For each candidate, read `transcript_window.md` and `narration_context.md`; do not rely only on the shortened excerpt in `ticket.md`.",
            "A driving pause is not automatically the end of a ticket. Post-pause speech is labeled as possible continuation for reviewer judgment.",
            "Candidate tickets are extraction hints, not the full truth.",
            "Do not collapse separate tickets just because they came from the same recording; decide based on distinct requested actions.",
            "When a candidate references an existing issue, say whether it should be a new issue or an update to an existing issue.",
            "Review transcript and frames together.",
            "Do not invent facts not supported by evidence.",
            "Quote source video names and timestamps.",
            "Ask for operator clarification when evidence is insufficient.",
            "",
            "Frame review guidance:",
            "- For 5760x1080 sim-racing frames, review the panel crops first when they exist.",
            "- Follow the purpose and expected-evidence metadata recorded for each crop role.",
            "- Driver View crops remain available in the default layout, but their configured purpose does not guarantee that dashboard UI is physically present there.",
            "- Do not assume a dashboard or UI is always on one physical panel; inspect the configured dashboard-monitor role when present.",
            "- Do not judge small UI text from a preview or composite when full frames or source-aware crops exist.",
            "",
            "This package was built from completed recordings as a post-processing workflow. It does not require operator interaction while driving or recording.",
            "",
            f"Candidate tickets: {len(candidates)}",
            f"Provisional evidence clusters: {len(outcomes)}",
            f"All detected candidates: {len(candidates) + len(unrendered_candidates)}",
            f"Indexed without rich frame/audio evidence: {len(unrendered_candidates)}",
            f"Review-needed items: {len(review_needed)}",
            "",
            *_marker_audit_summary_lines(marker_audit_summary),
            f"Pre-context seconds: {configuration.get('pre_context_seconds')}",
            f"Post-context seconds: {configuration.get('post_context_seconds')}",
            f"Fragmented narration mode: {str(bool(configuration.get('fragmented_narration_mode', True))).lower()}",
            f"Narration pre seconds: {configuration.get('narration_context_pre_seconds')}",
            f"Narration post seconds: {configuration.get('narration_context_post_seconds')}",
            f"Narration pause threshold seconds: {configuration.get('narration_pause_threshold_seconds')}",
            f"Stop narration at next ticket boundary: {str(bool(configuration.get('narration_stop_at_next_ticket_boundary', True))).lower()}",
            f"Frame cadence seconds: {configuration.get('frame_cadence_seconds')}",
            f"Max frames per candidate: {configuration.get('max_frames_per_candidate')}",
            "",
            "Full Review add-on runs can reuse the already-created Full Review transcript/audio when the reuse guard proves those files are present. Broader transcript/audio reuse remains tracked separately.",
            "",
            "Open the matching evidence item folders when you need transcript windows, frame indexes, frames, or audio snippets.",
            "",
            f"Invocation mode: {configuration.get('invocation_mode', 'standalone')}",
            f"Panel crop mode: {(configuration.get('panel_crops') or {}).get('mode', 'auto')}",
            f"Panel crop rule: {(configuration.get('panel_crops') or {}).get('source_dimension_rule', 'Only exact 5760x1080 source frames are split into panel crops.')}",
        ]
    ).rstrip() + "\n"


def _build_candidate_tickets_markdown(candidates: list[dict[str, Any]], marker_audit_summary: dict[str, Any]) -> str:
    lines = ["# Candidate Tickets", "", *_marker_audit_summary_lines(marker_audit_summary)]
    if marker_audit_summary.get("indexed_unrendered_marker_hits", 0):
        lines.extend(
            [
                "Additional candidates are preserved in `ALL_CANDIDATES.md` but were not richly rendered in this run.",
                "",
            ]
        )
    if marker_audit_summary.get("uncovered_marker_hits", 0):
        lines.extend(
            [
                "Uncovered explicit marker hits exist. Inspect `MARKER_AUDIT.md` before trusting candidate count.",
                "",
            ]
        )
    if not candidates:
        lines.append("No candidate ticket moments were detected. Check `EVIDENCE_QUALITY_REPORT.md` before treating this as a clean result.")
        return "\n".join(lines) + "\n"
    for candidate in candidates:
        duplicate_note = ""
        if candidate.get("duplicate_of"):
            duplicate_note = f"Supporting duplicate of {candidate['duplicate_of']}; do not treat as a separate issue unless the transcript describes a different requested action."
        elif candidate.get("supporting_duplicate_evidence_ids"):
            duplicate_note = f"Primary candidate with supporting duplicate evidence: {', '.join(candidate['supporting_duplicate_evidence_ids'])}."
        lines.extend(
            [
                f"## {candidate['evidence_id']}: {candidate['suggested_issue_title']}",
                "",
                f"- Source: {candidate['source_filename']}",
                f"- Timestamp: {candidate['timestamp_start']} - {candidate['timestamp_end']}",
                f"- Marker: {candidate['marker_timestamp']}",
                f"- Confidence: {candidate['confidence']}",
                f"- Markers: {', '.join(candidate['detected_marker_phrases'])}",
                f"- Supporting terms: {', '.join(candidate.get('supporting_marker_phrases', [])) or 'none'}",
                f"- Duplicate role: {candidate.get('duplicate_role', 'primary')}",
                f"- Duplicate note: {duplicate_note or 'none'}",
                f"- Not enough evidence: {str(bool(candidate.get('not_enough_evidence'))).lower()}",
                f"- Repo routing hint: {candidate.get('likely_target_repo') or REPO_HINT_UNKNOWN} ({candidate.get('repo_confidence') or 'unknown'}; source: {candidate.get('repo_hint_source') or 'none'}; GitHub review required: {str(bool(candidate.get('requires_github_review', True))).lower()})",
                f"- Repo hint reason: {_repo_hint_reason_text(candidate)}",
                f"- Alternate repos: {_repo_hint_alternates_text(candidate)}",
                f"- Evidence folder: evidence_items/{candidate['evidence_id']}",
                f"- Frame index: {candidate.get('frame_index_path', '')}",
                "",
            ]
        )
        if candidate.get("boundary_marker_events"):
            lines.extend(["Strong boundary markers inside this candidate:", ""])
            for event in candidate.get("boundary_marker_events", []):
                lines.append(
                    f"- {event.get('marker_timestamp')}: {', '.join(event.get('detected_marker_phrases', []))} - {event.get('segment_text', '')}"
                )
            lines.append("")
        lines.extend([candidate.get("transcript_excerpt", ""), ""])
    return "\n".join(lines).rstrip() + "\n"


def _all_candidate_index_rows(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "evidence_id": candidate.get("evidence_id", ""),
            "source_id": candidate.get("source_id", ""),
            "source_identifier": candidate.get("source_identifier", ""),
            "source_filename": candidate.get("source_filename", ""),
            "marker_timestamp_seconds": candidate.get("marker_timestamp_seconds"),
            "marker_timestamp": candidate.get("marker_timestamp", ""),
            "focused_window_start_seconds": candidate.get("timestamp_start_seconds"),
            "focused_window_end_seconds": candidate.get("timestamp_end_seconds"),
            "focused_window_start": candidate.get("timestamp_start", ""),
            "focused_window_end": candidate.get("timestamp_end", ""),
            "confidence": candidate.get("confidence", ""),
            "suggested_issue_title": candidate.get("suggested_issue_title", ""),
            "detected_marker_phrases": list(candidate.get("detected_marker_phrases") or []),
            "transcript_excerpt": candidate.get("transcript_excerpt", ""),
            "render_status": candidate.get("render_status", "rendered"),
            "render_skip_reason": candidate.get("render_skip_reason", ""),
            "transcript_window_path": candidate.get("transcript_window_path", ""),
            "narration_context_path": candidate.get("narration_context_path", ""),
            "narration_context_json_path": candidate.get("narration_context_json_path", ""),
            "narration_context_boundary_type": candidate.get("narration_context_boundary_type", ""),
            "narration_context_boundary_timestamp": candidate.get(
                "narration_context_boundary_timestamp", ""
            ),
            "narration_context_warning": candidate.get("narration_context_warning", ""),
            "full_transcript_paths": dict(candidate.get("full_transcript_paths") or {}),
            "likely_target_repo": candidate.get("likely_target_repo", REPO_HINT_UNKNOWN),
            "repo_confidence": candidate.get("repo_confidence", "unknown"),
            "requires_github_review": bool(candidate.get("requires_github_review", True)),
        }
        for candidate in candidates
    ]


def _build_all_candidates_markdown(candidates: list[dict[str, Any]]) -> str:
    rendered_count = sum(1 for candidate in candidates if candidate.get("render_status") == "rendered")
    unrendered_count = len(candidates) - rendered_count
    lines = [
        "# All Detected Candidates",
        "",
        f"- Detected candidates: {len(candidates)}",
        f"- Fully rendered candidates: {rendered_count}",
        f"- Indexed without rich frame/audio evidence: {unrendered_count}",
        "",
        "EvidenceMaxItems limits fully rendered frame/audio packages. Every detection remains indexed here with transcript and narration-context references.",
        "Use EvidenceRenderCandidateIds on a later run to request specific stable candidate IDs.",
        "",
    ]
    if not candidates:
        lines.append("No candidate ticket moments were detected.")
        return "\n".join(lines).rstrip() + "\n"
    for candidate in candidates:
        lines.extend(
            [
                f"## {candidate.get('evidence_id')}: {candidate.get('suggested_issue_title')}",
                "",
                f"- Source: {candidate.get('source_filename')}",
                f"- Marker timestamp: {candidate.get('marker_timestamp')}",
                f"- Focused window: {candidate.get('timestamp_start')} - {candidate.get('timestamp_end')}",
                f"- Confidence: {candidate.get('confidence')}",
                f"- Marker phrases: {', '.join(candidate.get('detected_marker_phrases') or []) or 'none'}",
                f"- Render status: {candidate.get('render_status', 'rendered')}",
                f"- Not rendered reason: {candidate.get('render_skip_reason') or 'none'}",
                f"- Narration context: {candidate.get('narration_context_path')}",
                f"- Narration context JSON: {candidate.get('narration_context_json_path')}",
                "",
                candidate.get("transcript_excerpt") or "(No transcript excerpt available.)",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _markdown_cell(value: Any) -> str:
    return re.sub(r"\s+", " ", _safe_text(value)).replace("|", "\\|") or "none"


def _repo_hint_candidate_rows(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "evidence_id": candidate.get("evidence_id", ""),
            "suggested_issue_title": candidate.get("suggested_issue_title", ""),
            "source_filename": candidate.get("source_filename", ""),
            "marker_timestamp": candidate.get("marker_timestamp", ""),
            "likely_target_repo": candidate.get("likely_target_repo") or REPO_HINT_UNKNOWN,
            "target_project_label": candidate.get("target_project_label", ""),
            "repo_confidence": candidate.get("repo_confidence") or "unknown",
            "repo_hint_source": candidate.get("repo_hint_source") or "none",
            "repo_hint_reason": list(candidate.get("repo_hint_reason", []) or []),
            "alternate_repos": list(candidate.get("alternate_repos", []) or []),
            "repo_hint_is_ambiguous": bool(candidate.get("repo_hint_is_ambiguous")),
            "requires_github_review": bool(candidate.get("requires_github_review", True)),
            "review_note": candidate.get("repo_hint_review_note") or REPO_HINT_REVIEW_WARNING,
        }
        for candidate in candidates
    ]


def _build_repo_routing_hints_markdown(
    candidates: list[dict[str, Any]],
    configuration: dict[str, Any],
    summary: dict[str, Any],
) -> str:
    repo_hinting = dict(configuration.get("repo_hinting") or {})
    warnings = list(repo_hinting.get("warnings") or [])
    lines = [
        "# Repo Routing Hints",
        "",
        REPO_HINT_REVIEW_WARNING,
        "",
        "Media Manglers suggests likely target repos/projects from local deterministic inputs only. Final GitHub-aware routing remains with Codex/ChatGPT review.",
        "",
        "## Hint Source",
        "",
        f"- Mode: {repo_hinting.get('mode', 'auto')}",
        f"- Target repo override: {repo_hinting.get('target_repo_override') or 'none'}",
        f"- Repo map source: {repo_hinting.get('repo_map_path') or 'none'}",
        f"- Repo map loaded: {str(bool(repo_hinting.get('repo_map_loaded'))).lower()}",
        f"- Repo map repo count: {repo_hinting.get('repo_map_repo_count', 0)}",
        "",
        "## Summary",
        "",
        f"- Candidate count: {summary.get('candidate_count', 0)}",
        f"- Requires GitHub review: {summary.get('requires_github_review_count', 0)}",
        f"- UNKNOWN repo hints: {summary.get('unknown_candidate_count', 0)}",
        f"- Ambiguous repo hints: {summary.get('ambiguous_candidate_count', 0)}",
        f"- Target repo counts: {json.dumps(summary.get('target_repo_counts', {}), ensure_ascii=False, sort_keys=True)}",
        f"- Confidence counts: {json.dumps(summary.get('confidence_counts', {}), ensure_ascii=False, sort_keys=True)}",
        "",
    ]
    if warnings:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
        lines.append("")

    rows = _repo_hint_candidate_rows(candidates)
    lines.extend(
        [
            "## Per-Candidate Hints",
            "",
            "| Candidate | Title | Likely repo | Confidence | Source | Project label | GitHub review |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    if rows:
        for row in rows:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _markdown_cell(row["evidence_id"]),
                        _markdown_cell(row["suggested_issue_title"]),
                        _markdown_cell(row["likely_target_repo"]),
                        _markdown_cell(row["repo_confidence"]),
                        _markdown_cell(row["repo_hint_source"]),
                        _markdown_cell(row["target_project_label"]),
                        _markdown_cell(str(row["requires_github_review"]).lower()),
                    ]
                )
                + " |"
            )
    else:
        lines.append("| none | none | UNKNOWN | unknown | none | none | true |")
    lines.append("")

    unknown_rows = [row for row in rows if row["likely_target_repo"] == REPO_HINT_UNKNOWN]
    lines.extend(["## Candidates With UNKNOWN Repo", ""])
    if unknown_rows:
        for row in unknown_rows:
            lines.append(f"- {row['evidence_id']}: {row['suggested_issue_title']}")
    else:
        lines.append("None.")
    lines.append("")

    ambiguous_rows = [row for row in rows if row["repo_hint_is_ambiguous"]]
    lines.extend(["## Candidates With Ambiguous Repo Hints", ""])
    if ambiguous_rows:
        for row in ambiguous_rows:
            alternates = "; ".join(
                f"{item.get('repo', REPO_HINT_UNKNOWN)} score {item.get('score', 0)}"
                for item in row.get("alternate_repos", [])
            )
            lines.append(f"- {row['evidence_id']}: {row['likely_target_repo']} with alternates {alternates or 'none'}")
    else:
        lines.append("None.")
    lines.extend(
        [
            "",
            "## Reviewer Instruction",
            "",
            "- Start with `EVIDENCE_QUALITY_REPORT.md` and `MARKER_AUDIT.md`.",
            "- Use these repo hints as suggestions only.",
            "- Check GitHub repos and open issues before deciding new issue vs existing issue update/link.",
            "- Report each item as new issue, existing issue update/link, clarification, context only, or Media Manglers tooling follow-up.",
            "- If the hint is UNKNOWN or ambiguous, ask the operator or classify as needs clarification.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _build_repo_routing_hints_json(
    candidates: list[dict[str, Any]],
    configuration: dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "generated_at": _utc_now(),
        "review_warning": REPO_HINT_REVIEW_WARNING,
        "repo_hinting": dict(configuration.get("repo_hinting") or {}),
        "summary": summary,
        "candidates": _repo_hint_candidate_rows(candidates),
    }


def _build_session_timeline(
    sources: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    review_needed: list[dict[str, Any]] | None = None,
) -> str:
    review_needed = list(review_needed or [])
    lines = ["# Session Timeline", "", "## Sources", ""]
    for source in sources:
        quality = source.get("transcript_quality", {})
        label = quality.get("risk_classification") or ("usable" if quality.get("appears_usable") else "SUSPICIOUS")
        detail = ""
        if quality.get("warning_reasons"):
            detail = f" - warnings: {'; '.join(quality['warning_reasons'])}"
        lines.append(f"- {source.get('source_filename') or source.get('source_id')} ({source.get('status')}, transcript {label}){detail}")
    lines.extend(["", "## Candidate Moments", ""])
    if not candidates:
        lines.append("No candidate moments detected. Check `EVIDENCE_QUALITY_REPORT.md` before assuming this is clean.")
    else:
        for candidate in sorted(candidates, key=lambda item: (item["source_filename"], item["timestamp_start_seconds"])):
            duplicate = ""
            if candidate.get("duplicate_of"):
                duplicate = f" [supporting duplicate of {candidate['duplicate_of']}]"
            lines.append(
                f"- {candidate['source_filename']} {candidate['timestamp_start']} - {candidate['timestamp_end']}: "
                f"{candidate['evidence_id']} ({candidate['confidence']}) {candidate['suggested_issue_title']}{duplicate}"
            )
    lines.extend(["", "## Review Needed", ""])
    if not review_needed:
        lines.append("No lower-confidence review-needed moments detected.")
        return "\n".join(lines).rstrip() + "\n"
    for item in sorted(review_needed, key=lambda entry: (entry["source_filename"], entry["timestamp_start_seconds"])):
        lines.append(
            f"- {item['source_filename']} {item['timestamp_start']} - {item['timestamp_end']}: "
            f"{item['review_id']} ({item['reason']}) visual follow-up required"
        )
    return "\n".join(lines).rstrip() + "\n"


def _build_quality_report(
    sources: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    configuration: dict[str, Any],
    review_needed: list[dict[str, Any]] | None = None,
    unrendered_candidates: list[dict[str, Any]] | None = None,
) -> str:
    review_needed = list(review_needed or [])
    unrendered_candidates = list(unrendered_candidates or [])
    summary = _quality_summary(sources)
    lines = [
        "# Evidence Quality Report",
        "",
        f"- Sources: {summary['source_count']}",
        f"- Usable transcripts: {summary['usable_source_count']}",
        f"- Suspicious transcripts: {summary['suspicious_source_count']}",
        f"- Suspicious high-risk transcripts: {summary.get('suspicious_high_risk_source_count', 0)}",
        f"- Suspicious low-risk short clips: {summary.get('suspicious_low_risk_short_clip_source_count', 0)}",
        f"- Suspicious low-risk no-marker transcripts: {summary.get('suspicious_low_risk_no_marker_terms_source_count', 0)}",
        f"- Waiting for a voice-track choice: {summary.get('needs_track_choice_source_count', 0)}",
        f"- Candidate tickets: {len(candidates)}",
        f"- All detected candidates: {len(candidates) + len(unrendered_candidates)}",
        f"- Indexed without rich frame/audio evidence: {len(unrendered_candidates)}",
        f"- Review-needed items: {len(review_needed)}",
        f"- Visual follow-up required: {sum(1 for item in review_needed if item.get('visual_followup_required'))}",
        f"- Context: {configuration.get('pre_context_seconds')}s before / {configuration.get('post_context_seconds')}s after",
        f"- Merge gap: {configuration.get('merge_gap_seconds')}s",
        f"- Frame cadence: {configuration.get('frame_cadence_seconds')}s",
        f"- Max frames per candidate: {configuration.get('max_frames_per_candidate')}",
        f"- Fragmented narration mode: {str(bool(configuration.get('fragmented_narration_mode', True))).lower()}",
        f"- Narration context: {configuration.get('narration_context_pre_seconds')}s before / {configuration.get('narration_context_post_seconds')}s after",
        f"- Narration pause threshold: {configuration.get('narration_pause_threshold_seconds')}s",
        f"- Invocation mode: {configuration.get('invocation_mode', 'standalone')}",
        f"- Panel crop mode: {(configuration.get('panel_crops') or {}).get('mode', 'auto')}",
        f"- Panel crop rule: {(configuration.get('panel_crops') or {}).get('source_dimension_rule', 'Only exact 5760x1080 source frames are split into panel crops.')}",
        "",
    ]
    if summary["all_sources_suspicious"]:
        lines.extend(
            [
                "All source transcripts were flagged suspicious. Treat missing or low candidate counts as a transcription-quality failure.",
                "",
            ]
        )
    elif summary["suspicious_source_count"]:
        lines.extend(
            [
                "One or more source transcripts were flagged suspicious. Review the source rows below before trusting candidate coverage.",
                "",
            ]
        )

    for source in sources:
        quality = source.get("transcript_quality", {})
        marker_counts = quality.get("ticket_marker_counts", {})
        top_words = ", ".join(
            f"{item['word']}={item['count']}" for item in quality.get("top_repeated_words", [])[:8]
        )
        audio_streams = source.get("audio_streams", [])
        selected_stream = source.get("selected_audio_stream") or {}
        lines.extend(
            [
                f"## {source.get('source_filename') or source.get('source_id')}",
                "",
                f"- Source ID: {source.get('source_id')}",
                f"- Duration seconds: {source.get('duration_seconds')}",
                f"- Status: {source.get('status')}",
                f"- Transcript appears usable: {str(bool(quality.get('appears_usable'))).lower()}",
                f"- Transcript quality status: {quality.get('quality_status') or 'unknown'}",
                f"- Risk classification: {quality.get('risk_classification') or 'unknown'}",
                f"- Risk reason: {quality.get('risk_reason') or 'unknown'}",
                f"- Recommended action: {quality.get('recommended_action') or 'Review manually if needed.'}",
                f"- Warning reasons: {'; '.join(quality.get('warning_reasons', [])) or 'none'}",
                f"- Transcript text length: {quality.get('transcript_text_length', 0)}",
                f"- Word count: {quality.get('word_count', 0)}",
                f"- Unique word count: {quality.get('unique_word_count', 0)}",
                f"- Words per minute: {quality.get('words_per_minute', 0)}",
                f"- Unique-word ratio: {quality.get('unique_word_ratio', 0)}",
                f"- Dominant word: {quality.get('dominant_word', '')} ({quality.get('dominant_word_count', 0)}, ratio {quality.get('dominant_word_ratio', 0)})",
                f"- Top repeated words: {top_words or 'none'}",
                f"- Total marker count: {quality.get('total_marker_count', 0)}",
                f"- Ticket marker counts: {json.dumps(marker_counts, ensure_ascii=False, sort_keys=True)}",
                f"- Audio method: {source.get('audio_method') or 'unknown'}",
                f"- Audio path: {source.get('audio_path') or 'not available'}",
                f"- Transcription input method: {source.get('transcription_input_method') or 'unknown'}",
                f"- Transcript reuse status: {source.get('transcript_reuse_status') or 'not_reused'}",
                f"- Raw video transcription used: {str(bool(source.get('raw_video_transcription_used'))).lower()}",
                f"- Audio stream count: {source.get('audio_stream_count', len(audio_streams))}",
                f"- Selected audio stream index: {source.get('selected_audio_stream_index')}",
                f"- Selected audio stream: {json.dumps(selected_stream, ensure_ascii=False, sort_keys=True) if selected_stream else 'not recorded'}",
                f"- Audio stream selection confirmed: {str(bool(source.get('audio_stream_selection_confirmed'))).lower()}",
                f"- Audio stream selection: {source.get('audio_stream_selection_status') or 'unknown'}"
                + (
                    f" ({source.get('audio_stream_confirmation_source')})"
                    if source.get("audio_stream_confirmation_source")
                    else ""
                ),
                f"- Transcript audio role: {source.get('transcript_audio_role') or 'unknown'}",
                f"- Repeated transcript segments: {quality.get('repeated_segment_count', 0)}",
                f"- Near-duplicate segment pairs: {quality.get('near_duplicate_segment_pairs', 0)}",
                f"- Gibberish-like segments: {quality.get('gibberish_like_segment_count', 0)}",
                f"- Language inconsistency detected: {str(bool(quality.get('language_inconsistency_detected'))).lower()}",
                f"- Game/spotter contamination suspected: {str(bool(quality.get('game_spotter_contamination_suspected'))).lower()}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _manifest_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = (
        "source_id",
        "physical_source_id",
        "physical_source_id_shortened",
        "source_identifier",
        "source_filename",
        "source_path",
        "duration_seconds",
        "status",
        "error_message",
        "audio_path",
        "audio_status",
        "audio_error_message",
        "audio_method",
        "audio_stream_count",
        "audio_streams",
        "selected_audio_stream_index",
        "selected_audio_stream",
        "audio_stream_selection_confirmed",
        "audio_stream_selection_status",
        "audio_stream_confirmation_source",
        "narration_speech_mode",
        "transcript_audio_role",
        "transcription_input_path",
        "transcription_input_method",
        "transcript_reuse_status",
        "reused_transcript_json_path",
        "reused_transcript_srt_path",
        "reused_transcript_txt_path",
        "raw_video_transcription_used",
        "transcript_quality",
        "transcript_language",
        "transcript_correction_count",
        "transcript_corrections",
        "raw_transcript_json_path",
        "raw_transcript_srt_path",
        "raw_transcript_txt_path",
        "transcript_json_path",
        "transcript_srt_path",
        "transcript_txt_path",
    )
    return [{key: source.get(key) for key in keys} for source in sources]


def write_outputs_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    output_dir_value = _safe_text(payload.get("output_dir"))
    if not output_dir_value:
        raise ValueError("output_dir is required.")
    output_dir = Path(output_dir_value)
    output_dir.mkdir(parents=True, exist_ok=True)
    configuration = dict(payload.get("configuration") or {})
    transcription_glossary = dict(configuration.get("transcription_glossary") or {})
    if not transcription_glossary:
        transcription_glossary = load_transcription_glossary(payload)
    glossary_entries = list(transcription_glossary.get("entries") or [])
    sources = [
        _normalize_source(dict(source), glossary_entries=glossary_entries)
        for source in (payload.get("sources") or [])
    ]
    candidates = [dict(candidate) for candidate in (payload.get("candidates") or [])]
    legacy_candidate_count = max(
        len(candidates), _coerce_int(payload.get("legacy_candidate_count"), len(candidates))
    )
    unrendered_candidates = [
        dict(candidate) for candidate in (payload.get("unrendered_candidates") or [])
    ]
    all_candidates = [*candidates, *unrendered_candidates]
    review_needed = [dict(item) for item in (payload.get("review_needed") or [])]
    outcomes = [dict(item) for item in (payload.get("outcomes") or [])]
    artifact_results = dict(payload.get("artifact_results") or {})
    _ensure_repo_hint_fields(all_candidates)

    _copy_transcript_sources(output_dir, sources)
    _apply_artifact_results(candidates, artifact_results)
    sources_by_id = {source["source_id"]: source for source in sources}

    transcript_dir = output_dir / "transcript"
    # 196: a skipped recording has no transcript in the package, so the
    # transcript files do not list it; the manifest and the quality report say
    # it was skipped.
    transcript_sources = [source for source in sources if not _skipped_by_operator(source)]
    _write_json(transcript_dir / "full_transcript.json", _build_full_transcript_json(transcript_sources))
    _write_text(transcript_dir / "full_transcript.md", _build_full_transcript_markdown(transcript_sources))
    raw_transcript_sources = _raw_transcript_sources(transcript_sources)
    raw_transcript_dir = transcript_dir / "raw"
    _write_json(
        raw_transcript_dir / "full_transcript.json",
        _build_full_transcript_json(raw_transcript_sources),
    )
    _write_text(
        raw_transcript_dir / "full_transcript.md",
        _build_full_transcript_markdown(raw_transcript_sources),
    )
    correction_audit = _transcript_correction_audit(sources, transcription_glossary)
    _write_json(output_dir / "TRANSCRIPT_CORRECTIONS.json", correction_audit)
    _write_text(
        output_dir / "TRANSCRIPT_CORRECTIONS.md",
        build_correction_markdown(correction_audit),
    )

    _remove_stale_ticket_folders(
        output_dir, {_safe_text(candidate.get("evidence_id")) for candidate in all_candidates}
    )
    if any(_skipped_by_operator(source) for source in sources):
        _remove_stale_narration_index(output_dir)
        _remove_stale_operator_drafts(output_dir)
    for candidate in all_candidates:
        source = sources_by_id.get(candidate.get("source_id"), {})
        candidate["full_transcript_paths"] = _full_transcript_paths(
            _safe_text(candidate.get("source_id")),
            _safe_text(source.get("physical_source_id")),
        )
        narration_context = dict(candidate.get("narration_context") or {})
        if not narration_context:
            narration_context = _build_narration_context(
                candidate=candidate,
                source=source,
                fragmented_narration_mode=_coerce_bool(
                    configuration.get("fragmented_narration_mode"), True
                ),
                narration_context_pre_seconds=max(
                    0.0,
                    _coerce_float(
                        configuration.get("narration_context_pre_seconds"),
                        NARRATION_CONTEXT_PRE_SECONDS,
                    ),
                ),
                narration_context_post_seconds=max(
                    0.0,
                    _coerce_float(
                        configuration.get("narration_context_post_seconds"),
                        NARRATION_CONTEXT_POST_SECONDS,
                    ),
                ),
                narration_pause_threshold_seconds=max(
                    0.0,
                    _coerce_float(
                        configuration.get("narration_pause_threshold_seconds"),
                        NARRATION_PAUSE_THRESHOLD_SECONDS,
                    ),
                ),
                narration_stop_at_next_ticket_boundary=_coerce_bool(
                    configuration.get("narration_stop_at_next_ticket_boundary"), True
                ),
                next_candidate_marker_time=None,
            )
            candidate["narration_context"] = narration_context
        narration_context["full_transcript_paths"] = candidate["full_transcript_paths"]
        segments = _window_segments_for_candidate(candidate, sources_by_id)
        base_dir = output_dir / "evidence_items" / candidate["evidence_id"]
        _write_text(base_dir / "transcript_window.md", _build_transcript_window_markdown(candidate, segments))
        _write_text(base_dir / "narration_context.md", _build_narration_context_markdown(candidate))
        _write_json(base_dir / "narration_context.json", narration_context)
        _write_text(base_dir / "ticket.md", _build_ticket_markdown(candidate))
        _write_json(base_dir / "metadata.json", candidate)
        _write_csv(
            base_dir / "frame_index.csv",
            _frame_rows(candidate),
            [
                "timestamp_seconds",
                "timestamp",
                "frame_role",
                "offset_seconds",
                "full_frame_path",
                "full_frame_width",
                "full_frame_height",
                "panel_crop_mode",
                "panel_detection",
                "panel_role",
                "panel_crop_path",
                "panel_crop_x",
                "panel_crop_y",
                "panel_crop_width",
                "panel_crop_height",
                "panel_image_width",
                "panel_image_height",
                "status",
                "error_message",
            ],
        )

    integrity_enforced = (
        _coerce_bool(configuration.get("require_artifact_integrity"), False)
        and _coerce_bool(artifact_results.get("integrity_enforced"), False)
        and "frames" in artifact_results
        and "audio" in artifact_results
    )
    integrity_report = _artifact_integrity_report(
        output_dir,
        candidates,
        artifact_results,
        enforce=integrity_enforced,
    )
    _write_json(output_dir / "EVIDENCE_INTEGRITY_REPORT.json", integrity_report)
    _write_text(
        output_dir / "EVIDENCE_INTEGRITY_REPORT.md",
        _artifact_integrity_markdown(integrity_report),
    )

    confidence_counts = {
        confidence: sum(1 for candidate in candidates if candidate["confidence"] == confidence)
        for confidence in ("explicit", "likely", "weak")
    }
    detected_confidence_counts = {
        confidence: sum(1 for candidate in all_candidates if candidate["confidence"] == confidence)
        for confidence in ("explicit", "likely", "weak")
    }
    review_summary = _review_needed_summary(review_needed)
    quality_summary = _quality_summary(sources)
    # 199: words said in passing are listed, never ticketed and never hidden. Only recordings the
    # operator did not skip, and only narration that was scanned for requests.
    mentioned_not_asked = build_mentioned_not_asked(
        [
            source
            for source in transcript_sources
            if source.get("transcript_audio_role") != "supporting_audio" and _source_transcript_is_scannable(source)
        ],
        all_candidates,
    )
    _write_json(
        output_dir / MENTIONED_NOT_ASKED_JSON,
        {"schema_version": 1, "generated_at": _utc_now(), "items": mentioned_not_asked},
    )
    _write_text(output_dir / MENTIONED_NOT_ASKED_MARKDOWN, _mentioned_not_asked_markdown(mentioned_not_asked))
    marker_audit = _build_marker_audit(sources, candidates, unrendered_candidates, mentioned_not_asked)
    marker_audit_summary = marker_audit["summary"]
    marker_audit_summary.update(review_summary)
    session_review = build_session_review(
        candidates=all_candidates,
        review_needed=review_needed,
        marker_audit=marker_audit,
    )
    repo_summary = _repo_hint_summary(all_candidates, configuration)
    manifest = {
        "schema_version": EVIDENCE_PACKAGE_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "package_type": "codex-evidence-package",
        "semantic_authority": "evidence_preparation_only",
        "consolidated_record_label": "PROVISIONAL EVIDENCE CLUSTER",
        "github_write_authorized": False,
        "configuration": configuration,
        "source_count": len(sources),
        "candidate_count": len(candidates),
        "legacy_detection_budget_candidate_count": legacy_candidate_count,
        "detected_candidate_count": len(all_candidates),
        "unrendered_candidate_count": len(unrendered_candidates),
        "review_needed_count": len(review_needed),
        # 199: words said in passing, listed for the operator to decide; never tickets.
        "mentioned_not_asked_count": len(mentioned_not_asked),
        "mentioned_not_asked_markdown_path": MENTIONED_NOT_ASKED_MARKDOWN,
        "mentioned_not_asked_json_path": MENTIONED_NOT_ASKED_JSON,
        "outcome_count": len(outcomes),
        "visual_followup_required_count": review_summary["visual_followup_required_count"],
        "confidence_counts": confidence_counts,
        "detected_confidence_counts": detected_confidence_counts,
        "truncated_candidates_count": len(unrendered_candidates),
        "quality_summary": quality_summary,
        "review_needed_summary": review_summary,
        "marker_audit_summary": marker_audit_summary,
        "session_review_summary": session_review["summary"],
        "repo_hint_summary": repo_summary,
        "artifact_integrity": {
            "status": integrity_report["status"],
            "enforced": integrity_report["enforced"],
            "totals": integrity_report["totals"],
            "categories": {
                name: {
                    key: value
                    for key, value in summary.items()
                    if key != "artifacts"
                }
                for name, summary in integrity_report["categories"].items()
            },
            "report_json_path": "EVIDENCE_INTEGRITY_REPORT.json",
            "report_markdown_path": "EVIDENCE_INTEGRITY_REPORT.md",
        },
        "transcript_correction_summary": {
            key: correction_audit[key]
            for key in (
                "glossary_entry_count",
                "glossary_alias_count",
                "corrected_segment_count",
                "correction_record_count",
            )
        },
        "sources": _manifest_sources(sources),
        "review_needed": review_needed,
        "outcomes": outcomes,
    }
    quality_report = _build_quality_report(
        sources,
        candidates,
        configuration,
        review_needed,
        unrendered_candidates,
    )
    _write_text(
        output_dir / "README_FOR_AI.md",
        _build_readme(
            candidates,
            review_needed,
            sources,
            configuration,
            marker_audit_summary,
            unrendered_candidates,
            outcomes,
        ),
    )
    _write_text(output_dir / "CANDIDATE_TICKETS.md", _build_candidate_tickets_markdown(candidates, marker_audit_summary))
    _write_text(output_dir / "ALL_CANDIDATES.md", _build_all_candidates_markdown(all_candidates))
    _write_json(
        output_dir / "CONSOLIDATED_OUTCOMES.json",
        {
            "schema_version": EVIDENCE_PACKAGE_SCHEMA_VERSION,
            "generated_at": _utc_now(),
            "outcome_count": len(outcomes),
            "outcomes": outcomes,
        },
    )
    _write_json(
        output_dir / "ALL_CANDIDATES.json",
        {
            "schema_version": EVIDENCE_PACKAGE_SCHEMA_VERSION,
            "generated_at": _utc_now(),
            "detected_candidate_count": len(all_candidates),
            "rendered_candidate_count": len(candidates),
            "unrendered_candidate_count": len(unrendered_candidates),
            "candidates": _all_candidate_index_rows(all_candidates),
        },
    )
    _write_text(output_dir / "REVIEW_NEEDED.md", _build_review_needed_markdown(review_needed))
    _write_json(
        output_dir / "REVIEW_NEEDED.json",
        {
            "generated_at": _utc_now(),
            "summary": review_summary,
            "review_needed": review_needed,
            "outcomes": outcomes,
        },
    )
    _write_text(output_dir / "REPO_ROUTING_HINTS.md", _build_repo_routing_hints_markdown(all_candidates, configuration, repo_summary))
    _write_text(output_dir / "EVIDENCE_QUALITY_REPORT.md", quality_report)
    _write_text(output_dir / "MARKER_AUDIT.md", _build_marker_audit_markdown(marker_audit))
    _write_json(output_dir / "MARKER_AUDIT.json", marker_audit)
    _write_json(
        output_dir / "REPO_ROUTING_HINTS.json",
        _build_repo_routing_hints_json(all_candidates, configuration, repo_summary),
    )
    _write_json(
        output_dir / "CANDIDATE_TICKETS.json",
        {
            "review_warning": REPO_HINT_REVIEW_WARNING,
            "repo_hint_summary": repo_summary,
            "candidates": candidates,
            "unrendered_candidates": unrendered_candidates,
            "review_needed": review_needed,
        },
    )
    handoff_mode = _safe_text(configuration.get("evidence_handoff_mode")) or "Local"
    portable_zip_max_mb = max(
        1,
        _coerce_int(configuration.get("evidence_portable_zip_max_mb"), 100),
    )
    session_status = write_session_review_artifacts(
        output_dir,
        session_review,
        portable_mode=handoff_mode,
        portable_zip_max_mb=portable_zip_max_mb,
        outcomes=outcomes,
        integrity_report=integrity_report,
        projects=_configured_projects(configuration),
    )
    session_status["quality_summary"] = quality_summary
    # The package is only plainly "ready" when every recording produced
    # something usable; anything else says so in one word (118).
    unusable_sources = (
        int(quality_summary.get("source_count") or 0)
        - int(quality_summary.get("usable_source_count") or 0)
    )
    if unusable_sources > 0:
        session_status["status"] = "ready_with_problems"
        session_status["unusable_source_count"] = unusable_sources
    session_status["artifact_integrity"] = manifest["artifact_integrity"]
    if quality_summary.get("suspicious_source_count"):
        session_status.setdefault("warnings", []).append(
            "One or more source transcripts are suspicious or usable only with warnings. Review EVIDENCE_QUALITY_REPORT.md."
        )
    if quality_summary.get("needs_track_choice_source_count"):
        session_status.setdefault("warnings", []).append(
            "One or more recordings were not transcribed because their voice track still needs the operator's "
            "voice-track choice. Their narration is missing, not empty."
        )
    session_status["transcript_correction_summary"] = manifest[
        "transcript_correction_summary"
    ]
    _write_json(output_dir / "PACKAGE_STATUS.json", session_status)
    portable_enabled = handoff_mode.lower() in {"portablezip", "both"}
    if not portable_enabled and any(_skipped_by_operator(source) for source in sources):
        _remove_stale_portable_zip(output_dir)
    manifest["session_review"] = {
        "summary": session_review["summary"],
        "start_here_path": "START_HERE_FOR_TICKET_AGENT.md",
        "timeline_markdown_path": "SESSION_TIMELINE.md",
        "timeline_json_path": "SESSION_TIMELINE.json",
        "thread_hints_markdown_path": "TICKET_THREAD_HINTS.md",
        "thread_hints_json_path": "TICKET_THREAD_HINTS.json",
        "unassigned_mentions_markdown_path": "UNASSIGNED_MENTIONS.md",
        "unassigned_mentions_json_path": "UNASSIGNED_MENTIONS.json",
        "package_status_path": "PACKAGE_STATUS.json",
        "portable_mode": handoff_mode,
        "portable_zip_path": PORTABLE_ZIP_FILENAME if portable_enabled else "",
    }
    _write_json(output_dir / "manifest.json", manifest)
    if integrity_report["status"] == "failed":
        session_status["status"] = "failed_integrity"
        session_status.setdefault("warnings", []).append(
            "Required primary evidence artifacts are missing or artifact counters do not reconcile."
        )
        _write_json(output_dir / "PACKAGE_STATUS.json", session_status)
        raise RuntimeError(
            "Evidence package integrity failed. Review EVIDENCE_INTEGRITY_REPORT.md before retrying."
        )
    portable_result: dict[str, Any] = {}
    if portable_enabled:
        portable_result = build_portable_agent_zip(
            output_dir,
            max_size_mb=portable_zip_max_mb,
        )
        try:
            session_status = json.loads(
                (output_dir / "PACKAGE_STATUS.json").read_text(encoding="utf-8-sig")
            )
        except (OSError, json.JSONDecodeError):
            pass

    return {
        "output_dir": str(output_dir),
        "readme_path": str(output_dir / "README_FOR_AI.md"),
        "session_timeline_path": str(output_dir / "SESSION_TIMELINE.md"),
        "candidate_tickets_markdown_path": str(output_dir / "CANDIDATE_TICKETS.md"),
        "candidate_tickets_json_path": str(output_dir / "CANDIDATE_TICKETS.json"),
        "all_candidates_markdown_path": str(output_dir / "ALL_CANDIDATES.md"),
        "all_candidates_json_path": str(output_dir / "ALL_CANDIDATES.json"),
        "review_needed_markdown_path": str(output_dir / "REVIEW_NEEDED.md"),
        "review_needed_json_path": str(output_dir / "REVIEW_NEEDED.json"),
        "repo_routing_hints_markdown_path": str(output_dir / "REPO_ROUTING_HINTS.md"),
        "repo_routing_hints_json_path": str(output_dir / "REPO_ROUTING_HINTS.json"),
        "quality_report_path": str(output_dir / "EVIDENCE_QUALITY_REPORT.md"),
        "transcript_corrections_markdown_path": str(output_dir / "TRANSCRIPT_CORRECTIONS.md"),
        "transcript_corrections_json_path": str(output_dir / "TRANSCRIPT_CORRECTIONS.json"),
        "marker_audit_markdown_path": str(output_dir / "MARKER_AUDIT.md"),
        "marker_audit_json_path": str(output_dir / "MARKER_AUDIT.json"),
        "integrity_report_markdown_path": str(output_dir / "EVIDENCE_INTEGRITY_REPORT.md"),
        "integrity_report_json_path": str(output_dir / "EVIDENCE_INTEGRITY_REPORT.json"),
        "manifest_path": str(output_dir / "manifest.json"),
        "full_transcript_markdown_path": str(transcript_dir / "full_transcript.md"),
        "full_transcript_json_path": str(transcript_dir / "full_transcript.json"),
        "raw_full_transcript_markdown_path": str(raw_transcript_dir / "full_transcript.md"),
        "raw_full_transcript_json_path": str(raw_transcript_dir / "full_transcript.json"),
        "session_timeline_json_path": str(output_dir / "SESSION_TIMELINE.json"),
        "ticket_thread_hints_json_path": str(output_dir / "TICKET_THREAD_HINTS.json"),
        "unassigned_mentions_json_path": str(output_dir / "UNASSIGNED_MENTIONS.json"),
        "package_status_path": str(output_dir / "PACKAGE_STATUS.json"),
        "portable_zip_path": portable_result.get("zip_path", ""),
        "session_review_summary": session_review["summary"],
        "package_status": session_status,
        "candidate_count": len(candidates),
        "detected_candidate_count": len(all_candidates),
        "unrendered_candidate_count": len(unrendered_candidates),
        "review_needed_count": len(review_needed),
        "visual_followup_required_count": review_summary["visual_followup_required_count"],
        "confidence_counts": confidence_counts,
        "detected_confidence_counts": detected_confidence_counts,
        "quality_summary": quality_summary,
        "repo_hint_summary": repo_summary,
        "marker_audit_summary": marker_audit_summary,
        "transcript_correction_summary": manifest["transcript_correction_summary"],
        "artifact_integrity": manifest["artifact_integrity"],
    }


def build_package_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    detected = detect_from_request(payload)
    write_payload = {
        "output_dir": detected["output_dir"],
        "sources": detected["sources"],
        "candidates": detected["render_candidates"],
        "legacy_candidate_count": detected["candidate_count"],
        "unrendered_candidates": detected["unrendered_candidates"],
        "review_needed": detected["review_needed"],
        "configuration": detected["configuration"],
        "truncated_candidates_count": detected["truncated_candidates_count"],
        "artifact_results": payload.get("artifact_results") or {},
        "outcomes": detected["outcomes"],
    }
    written = write_outputs_from_request(write_payload)
    return {
        **detected,
        **written,
        "candidate_count": detected["candidate_count"],
        "rendered_primary_candidate_count": written["candidate_count"],
    }
