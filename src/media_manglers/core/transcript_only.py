"""Transcript-only batch manifest, index, and search helpers."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any


MANIFEST_FIELDS = [
    "source_id",
    "source_identifier",
    "source_path",
    "source_filename",
    "audio_path",
    "audio_status",
    "audio_error_message",
    "transcript_json_path",
    "transcript_srt_path",
    "transcript_txt_path",
    "duration_seconds",
    "status",
    "error_message",
]

SEARCH_FIELDS = [
    "query",
    "matched_term",
    "source_filename",
    "source_id",
    "timestamp_range",
    "snippet",
    "transcript_path",
]

ALIAS_TERMS = [
    "ticket",
    "tickets",
    "issue",
    "issues",
    "todo",
    "to-do",
    "make this a ticket",
    "create a ticket",
    "make this a to-do item",
]


def make_safe_source_id(source_path: str, source_filename: str = "") -> str:
    stem = Path(source_filename or source_path).stem
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    if not safe_stem:
        safe_stem = "source"
    safe_stem = safe_stem[:80]
    normalized = str(source_path or source_filename).replace("\\", "/").lower()
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
    return f"{safe_stem}-{digest}"


def format_timestamp(seconds: Any) -> str:
    try:
        total_ms = int(round(float(seconds) * 1000))
    except (TypeError, ValueError):
        total_ms = 0
    total_ms = max(0, total_ms)
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds_part, millis = divmod(remainder, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds_part:02}.{millis:03}"


def expand_search_terms(queries: list[str]) -> list[dict[str, str]]:
    expanded: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw_query in queries:
        query = str(raw_query or "").strip()
        if not query:
            continue
        normalized = query.lower()
        terms = [query]
        if any(alias in normalized for alias in ALIAS_TERMS):
            terms = ALIAS_TERMS
        for term in terms:
            key = (query.lower(), term.lower())
            if key not in seen:
                seen.add(key)
                expanded.append({"query": query, "term": term})
    return expanded


def _read_json(path: str) -> dict[str, Any]:
    if not path:
        return {}
    json_path = Path(path)
    if not json_path.exists():
        return {}
    return json.loads(json_path.read_text(encoding="utf-8"))


def _segments_from_entry(entry: dict[str, Any]) -> list[dict[str, Any]]:
    payload = _read_json(str(entry.get("transcript_json_path") or ""))
    segments = payload.get("segments") or []
    normalized: list[dict[str, Any]] = []
    for index, segment in enumerate(segments, start=1):
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        normalized.append(
            {
                "id": segment.get("id", index),
                "start": segment.get("start", 0),
                "end": segment.get("end", segment.get("start", 0)),
                "text": text,
            }
        )
    return normalized


def _relative_to_output(path_value: str, output_dir: Path) -> str:
    if not path_value:
        return ""
    path = Path(path_value)
    try:
        return str(path.resolve().relative_to(output_dir.resolve()))
    except ValueError:
        return path.name


def _normalize_entry(entry: dict[str, Any]) -> dict[str, str]:
    normalized = {field: str(entry.get(field, "") or "") for field in MANIFEST_FIELDS}
    if not normalized["source_id"]:
        normalized["source_id"] = make_safe_source_id(
            normalized["source_path"],
            normalized["source_filename"],
        )
    if not normalized["source_identifier"]:
        normalized["source_identifier"] = normalized["source_id"]
    return normalized


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _build_combined_markdown(entries: list[dict[str, str]], output_dir: Path) -> str:
    lines = [
        "# Transcript-Only Index",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}",
        "",
    ]
    for entry in entries:
        if entry["status"] not in {"completed", "skipped"}:
            continue
        transcript_path = entry["transcript_json_path"]
        segments = _segments_from_entry(entry)
        relative_transcript = _relative_to_output(transcript_path, output_dir)
        audio_path = entry.get("audio_path", "")
        relative_audio = _relative_to_output(audio_path, output_dir) if audio_path else ""
        lines.extend(
            [
                f"## {entry['source_filename'] or entry['source_id']}",
                "",
                f"- Source ID: {entry['source_id']}",
                f"- Source: {entry['source_identifier']}",
                f"- Audio: {relative_audio if relative_audio else 'not saved'}",
                f"- Transcript: {relative_transcript}",
                "",
            ]
        )
        if segments:
            for segment in segments:
                start = format_timestamp(segment.get("start", 0))
                end = format_timestamp(segment.get("end", segment.get("start", 0)))
                lines.append(f"[{start} - {end}] {segment['text']}")
        else:
            text_path = Path(entry["transcript_txt_path"])
            if text_path.exists():
                lines.append(text_path.read_text(encoding="utf-8").strip())
            else:
                lines.append("(No transcript text available.)")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _snippet_for_match(text: str, term: str, radius: int = 90) -> str:
    lower_text = text.lower()
    lower_term = term.lower()
    index = lower_text.find(lower_term)
    if index < 0:
        return text[: radius * 2].strip()
    start = max(0, index - radius)
    end = min(len(text), index + len(term) + radius)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"


def _search_entries(entries: list[dict[str, str]], output_dir: Path, queries: list[str]) -> list[dict[str, str]]:
    expanded = expand_search_terms(queries)
    if not expanded:
        return []
    results: list[dict[str, str]] = []
    for entry in entries:
        if entry["status"] not in {"completed", "skipped"}:
            continue
        segments = _segments_from_entry(entry)
        for segment in segments:
            text = segment["text"]
            lower_text = text.lower()
            for search in expanded:
                term = search["term"]
                if term.lower() not in lower_text:
                    continue
                timestamp_range = (
                    f"{format_timestamp(segment.get('start', 0))} - "
                    f"{format_timestamp(segment.get('end', segment.get('start', 0)))}"
                )
                results.append(
                    {
                        "query": search["query"],
                        "matched_term": term,
                        "source_filename": entry["source_filename"],
                        "source_id": entry["source_id"],
                        "timestamp_range": timestamp_range,
                        "snippet": _snippet_for_match(text, term),
                        "transcript_path": _relative_to_output(
                            entry["transcript_json_path"],
                            output_dir,
                        ),
                    }
                )
                break
    return results


def _build_search_markdown(results: list[dict[str, str]]) -> str:
    lines = ["# Transcript Search Results", ""]
    if not results:
        lines.append("No matches found.")
        return "\n".join(lines) + "\n"
    for row in results:
        lines.extend(
            [
                f"## {row['source_filename']} @ {row['timestamp_range']}",
                "",
                f"- Query: {row['query']}",
                f"- Matched term: {row['matched_term']}",
                f"- Source ID: {row['source_id']}",
                f"- Transcript: {row['transcript_path']}",
                "",
                row["snippet"],
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _build_per_source_search_text(
    entry: dict[str, str],
    results: list[dict[str, str]],
    output_dir: Path,
) -> str:
    lines = [
        f"Transcript Search Results: {entry['source_filename'] or entry['source_id']}",
        "",
        f"Source ID: {entry['source_id']}",
        f"Source: {entry['source_identifier']}",
        f"Audio: {_relative_to_output(entry.get('audio_path', ''), output_dir) if entry.get('audio_path') else 'not saved'}",
        f"Transcript: {_relative_to_output(entry.get('transcript_json_path', ''), output_dir)}",
        "",
    ]
    if not results:
        lines.append("No matches found for the supplied search terms.")
        return "\n".join(lines).rstrip() + "\n"

    for index, result in enumerate(results, start=1):
        lines.extend(
            [
                f"{index}. {result['query']} -> {result['matched_term']}",
                f"   Time: {result['timestamp_range'] or 'unknown'}",
                f"   Snippet: {result['snippet']}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _write_per_source_search_results(
    output_dir: Path,
    entries: list[dict[str, str]],
    results: list[dict[str, str]],
) -> list[str]:
    search_dir = output_dir / "search_results"
    search_dir.mkdir(parents=True, exist_ok=True)
    results_by_source: dict[str, list[dict[str, str]]] = {}
    for result in results:
        results_by_source.setdefault(result["source_id"], []).append(result)

    written_paths: list[str] = []
    for entry in entries:
        if entry["status"] not in {"completed", "skipped"}:
            continue
        source_id = entry["source_id"]
        path = search_dir / f"{source_id}.search_results.txt"
        path.write_text(
            _build_per_source_search_text(
                entry,
                results_by_source.get(source_id, []),
                output_dir,
            ),
            encoding="utf-8",
        )
        written_paths.append(str(path))
    return written_paths


def _build_ai_search_results_markdown(
    entries: list[dict[str, str]],
    results: list[dict[str, str]],
    output_dir: Path,
    search_terms: list[str],
) -> str:
    lines = [
        "# ChatGPT Search Results Handoff",
        "",
        "Use this file to paste transcript search hits into ChatGPT or another review tool.",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}",
        f"Search terms: {', '.join(search_terms)}",
        f"Total matches: {len(results)}",
        "",
    ]
    if not results:
        lines.append("No matches found for the supplied search terms.")
        return "\n".join(lines).rstrip() + "\n"

    entries_by_source = {entry["source_id"]: entry for entry in entries}
    results_by_source: dict[str, list[dict[str, str]]] = {}
    for result in results:
        results_by_source.setdefault(result["source_id"], []).append(result)

    for source_id in sorted(results_by_source):
        source_results = results_by_source[source_id]
        entry = entries_by_source.get(source_id, {})
        lines.extend(
            [
                f"## {entry.get('source_filename') or source_results[0]['source_filename'] or source_id}",
                "",
                f"- Source ID: {source_id}",
                f"- Source: {entry.get('source_identifier', source_id)}",
                f"- Audio: {_relative_to_output(entry.get('audio_path', ''), output_dir) if entry.get('audio_path') else 'not saved'}",
                f"- Transcript: {_relative_to_output(entry.get('transcript_json_path', ''), output_dir) if entry.get('transcript_json_path') else source_results[0]['transcript_path']}",
                "",
            ]
        )
        for index, result in enumerate(source_results, start=1):
            lines.extend(
                [
                    f"### Match {index}: {result['query']} -> {result['matched_term']}",
                    "",
                    f"- Time: {result['timestamp_range'] or 'unknown'}",
                    f"- Snippet: {result['snippet']}",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def write_outputs_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    output_dir_value = str(payload.get("output_dir") or "").strip()
    if not output_dir_value:
        raise ValueError("output_dir is required.")
    output_dir = Path(output_dir_value)
    output_dir.mkdir(parents=True, exist_ok=True)

    entries = [
        _normalize_entry(dict(entry))
        for entry in (payload.get("manifest_entries") or [])
    ]
    search_terms = [str(term) for term in (payload.get("search_terms") or [])]

    manifest_json = output_dir / "transcript_manifest.json"
    manifest_csv = output_dir / "transcript_manifest.csv"
    combined_md = output_dir / "TRANSCRIPTS_ALL.md"

    _write_json(manifest_json, entries)
    _write_csv(manifest_csv, entries, MANIFEST_FIELDS)
    combined_md.write_text(_build_combined_markdown(entries, output_dir), encoding="utf-8")

    search_csv = ""
    search_md = ""
    ai_search_md = ""
    search_count = 0
    per_source_search_paths: list[str] = []
    if search_terms:
        results = _search_entries(entries, output_dir, search_terms)
        search_count = len(results)
        search_csv_path = output_dir / "transcript_search_results.csv"
        search_md_path = output_dir / "transcript_search_results.md"
        ai_search_md_path = output_dir / "AI_SEARCH_RESULTS.md"
        _write_csv(search_csv_path, results, SEARCH_FIELDS)
        search_md_path.write_text(_build_search_markdown(results), encoding="utf-8")
        per_source_search_paths = _write_per_source_search_results(output_dir, entries, results)
        ai_search_md_path.write_text(
            _build_ai_search_results_markdown(
                entries,
                results,
                output_dir,
                search_terms,
            ),
            encoding="utf-8",
        )
        search_csv = str(search_csv_path)
        search_md = str(search_md_path)
        ai_search_md = str(ai_search_md_path)

    return {
        "manifest_json_path": str(manifest_json),
        "manifest_csv_path": str(manifest_csv),
        "combined_markdown_path": str(combined_md),
        "search_csv_path": search_csv,
        "search_markdown_path": search_md,
        "ai_search_markdown_path": ai_search_md,
        "per_source_search_result_paths": per_source_search_paths,
        "manifest_json": str(manifest_json),
        "manifest_csv": str(manifest_csv),
        "combined_markdown": str(combined_md),
        "search_csv": search_csv,
        "search_markdown": search_md,
        "ai_search_markdown": ai_search_md,
        "search_results_dir": str(output_dir / "search_results") if search_terms else "",
        "manifest_count": len(entries),
        "search_match_count": search_count,
        "search_results_count": search_count,
        "per_source_search_result_count": len(per_source_search_paths),
    }
