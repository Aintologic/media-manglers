"""Deterministic, auditable corrections for transcription terminology."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Iterable


BUILT_IN_GLOSSARY: tuple[dict[str, Any], ...] = (
    {
        "canonical": "iRacing",
        "aliases": ["I Racing", "i racing"],
        "scope": "application",
    },
    {
        "canonical": "SimHub",
        "aliases": ["Sim Hub"],
        "scope": "application",
    },
    {
        "canonical": "Crew Chief",
        "aliases": ["CrewChief"],
        "scope": "application",
    },
)


def _safe_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _value_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, dict)):
        return [value]
    if isinstance(value, Iterable):
        return list(value)
    return []


def _parse_compact_entry(value: str, scope: str) -> dict[str, Any] | None:
    text = _safe_text(value)
    if not text:
        return None
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        return dict(payload) if isinstance(payload, dict) else None
    canonical, separator, aliases = text.partition("=")
    if not separator:
        return {"canonical": canonical, "aliases": [], "scope": scope}
    return {
        "canonical": canonical,
        "aliases": [item.strip() for item in aliases.split("|") if item.strip()],
        "scope": scope,
    }


def normalize_glossary_entries(value: Any, *, default_scope: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for raw in _value_list(value):
        if isinstance(raw, str):
            item = _parse_compact_entry(raw, default_scope)
        elif isinstance(raw, dict):
            item = dict(raw)
        else:
            item = None
        if not item or item.get("enabled", True) is False:
            continue
        canonical = _safe_text(item.get("canonical") or item.get("term"))
        if not canonical:
            continue
        aliases = []
        seen_aliases: set[str] = set()
        for alias_value in _value_list(item.get("aliases") or item.get("recognized_aliases")):
            alias = _safe_text(alias_value)
            normalized = alias.casefold()
            if not alias or normalized == canonical.casefold() or normalized in seen_aliases:
                continue
            aliases.append(alias)
            seen_aliases.add(normalized)
        entries.append(
            {
                "canonical": canonical,
                "aliases": aliases,
                "scope": _safe_text(item.get("scope")) or default_scope,
                "project": _safe_text(item.get("project")),
                "repository": _safe_text(item.get("repository") or item.get("repo")),
                "source": _safe_text(item.get("source")) or default_scope,
            }
        )
    return entries


def _read_glossary_file(path_value: Any) -> dict[str, Any]:
    path_text = _safe_text(path_value)
    if not path_text:
        return {}
    path = Path(path_text)
    if not path.is_file():
        return {"warning": f"Transcription glossary file was not found: {path_text}"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"warning": f"Transcription glossary could not be read: {exc}"}
    if isinstance(payload, list):
        return {"entries": payload, "path": path_text}
    if isinstance(payload, dict):
        return {**payload, "path": path_text}
    return {"warning": "Transcription glossary root must be an object or array."}


def _project_entries(payload: dict[str, Any], glossary_file: dict[str, Any]) -> list[Any]:
    values: list[Any] = []
    values.extend(_value_list(payload.get("project_transcription_glossary")))
    values.extend(_value_list(glossary_file.get("project")))
    projects = glossary_file.get("projects")
    if not isinstance(projects, dict):
        return values
    target = _safe_text(
        payload.get("target_repo")
        or payload.get("evidence_target_repo")
        or payload.get("target_project")
    ).casefold()
    if target and target in {str(key).casefold() for key in projects}:
        for key, project_value in projects.items():
            if str(key).casefold() == target:
                values.extend(_value_list(project_value))
                break
    return values


def load_transcription_glossary(payload: dict[str, Any]) -> dict[str, Any]:
    """Merge glossary scopes without leaking local file content into defaults."""

    glossary_file = _read_glossary_file(
        payload.get("transcription_glossary_path")
        or payload.get("evidence_transcription_glossary_path")
    )
    entries: list[dict[str, Any]] = []
    entries.extend(normalize_glossary_entries(BUILT_IN_GLOSSARY, default_scope="application"))
    entries.extend(
        normalize_glossary_entries(
            payload.get("application_transcription_glossary")
            or glossary_file.get("application")
            or glossary_file.get("entries"),
            default_scope="application",
        )
    )
    entries.extend(
        normalize_glossary_entries(
            payload.get("profile_transcription_glossary")
            or payload.get("transcription_glossary_entries")
            or payload.get("evidence_transcription_glossary_entries")
            or glossary_file.get("profile"),
            default_scope="profile",
        )
    )
    entries.extend(
        normalize_glossary_entries(
            _project_entries(payload, glossary_file),
            default_scope="project",
        )
    )

    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for entry in entries:
        key = entry["canonical"].casefold()
        if key not in merged:
            merged[key] = dict(entry)
            merged[key]["aliases"] = []
            order.append(key)
        target = merged[key]
        existing = {str(alias).casefold() for alias in target["aliases"]}
        for alias in entry["aliases"]:
            if alias.casefold() not in existing:
                target["aliases"].append(alias)
                existing.add(alias.casefold())
        if entry.get("scope") in {"profile", "project"}:
            target.update({key: value for key, value in entry.items() if key != "aliases"})

    normalized_entries = [merged[key] for key in order]
    return {
        "schema_version": 1,
        "entries": normalized_entries,
        "entry_count": len(normalized_entries),
        "alias_count": sum(len(entry["aliases"]) for entry in normalized_entries),
        "source_path": _safe_text(glossary_file.get("path")),
        "warnings": [glossary_file["warning"]] if glossary_file.get("warning") else [],
    }


def build_whisper_initial_prompt(entries: Iterable[dict[str, Any]]) -> str:
    canonical_terms: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        canonical = _safe_text(entry.get("canonical"))
        if canonical and canonical.casefold() not in seen:
            canonical_terms.append(canonical)
            seen.add(canonical.casefold())
    return "Preferred terminology: " + ", ".join(canonical_terms) if canonical_terms else ""


def _alias_pattern(alias: str) -> re.Pattern[str]:
    # 201: Whisper writes an apostrophe straight or curly; "ain't" matches either way.
    escaped = re.sub("['‘’]", lambda _match: "['‘’]", re.escape(alias))
    prefix = r"(?<![A-Za-z0-9])" if alias[:1].isalnum() else ""
    suffix = r"(?![A-Za-z0-9])" if alias[-1:].isalnum() else ""
    return re.compile(prefix + escaped + suffix, flags=re.IGNORECASE)


def correct_text(text: Any, entries: Iterable[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    raw_text = _safe_text(text)
    corrected = raw_text
    corrections: list[dict[str, Any]] = []
    rules = sorted(
        (
            (alias, _safe_text(entry.get("canonical")), entry)
            for entry in entries
            for alias in entry.get("aliases") or []
            if _safe_text(alias) and _safe_text(entry.get("canonical"))
        ),
        key=lambda item: (-len(item[0]), item[0].casefold()),
    )
    for alias, canonical, entry in rules:
        pattern = _alias_pattern(alias)
        matches = list(pattern.finditer(corrected))
        if not matches:
            continue
        corrected = pattern.sub(lambda _match: canonical, corrected)
        corrections.append(
            {
                "matched_alias": alias,
                "canonical_term": canonical,
                "scope": _safe_text(entry.get("scope")) or "application",
                "method": "deterministic_exact_alias",
                "replacement_count": len(matches),
            }
        )
    return corrected, corrections


def correct_segments(
    segments: Iterable[dict[str, Any]],
    entries: Iterable[dict[str, Any]],
    *,
    source_id: str,
    source_filename: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    corrected_segments: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for segment in segments:
        output = dict(segment)
        raw_text = _safe_text(segment.get("raw_text") or segment.get("text"))
        corrected_text, changes = correct_text(raw_text, entries)
        output["raw_text"] = raw_text
        output["text"] = corrected_text
        output["correction_count"] = sum(int(change["replacement_count"]) for change in changes)
        corrected_segments.append(output)
        for change in changes:
            audit.append(
                {
                    "source_id": source_id,
                    "source_filename": source_filename,
                    "segment_id": output.get("id"),
                    "timestamp_seconds": output.get("start", 0.0),
                    "timestamp": output.get("timestamp_start", ""),
                    "raw_text": raw_text,
                    "corrected_text": corrected_text,
                    **change,
                }
            )
    return corrected_segments, audit


def build_correction_markdown(audit: dict[str, Any]) -> str:
    lines = [
        "# Transcript Corrections",
        "",
        "Corrections are deterministic exact-alias substitutions. Raw transcript text remains available for audit.",
        "",
        f"- Corrected segments: {audit.get('corrected_segment_count', 0)}",
        f"- Replacement records: {audit.get('correction_record_count', 0)}",
        f"- Glossary entries: {audit.get('glossary_entry_count', 0)}",
        "",
    ]
    for warning in audit.get("warnings") or []:
        lines.append(f"- Warning: {warning}")
    if audit.get("warnings"):
        lines.append("")
    if not audit.get("corrections"):
        lines.append("No configured aliases required correction.")
        return "\n".join(lines).rstrip() + "\n"
    for index, correction in enumerate(audit["corrections"], start=1):
        lines.extend(
            [
                f"## Correction {index:03d}",
                "",
                f"- Source: {correction.get('source_filename') or correction.get('source_id') or 'unknown'}",
                f"- Timestamp: {correction.get('timestamp') or 'unknown'}",
                f"- Alias: {correction.get('matched_alias')}",
                f"- Canonical term: {correction.get('canonical_term')}",
                f"- Scope: {correction.get('scope')}",
                f"- Method: {correction.get('method')}",
                f"- Replacements: {correction.get('replacement_count', 1)}",
                "",
                f"Raw: {correction.get('raw_text', '')}",
                "",
                f"Corrected: {correction.get('corrected_text', '')}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
