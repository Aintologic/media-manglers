from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import sys
import unicodedata
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from media_manglers.providers.hybrid_text import (  # noqa: E402
    detect_assistant_meta_contamination,
    detect_mojibake,
    detect_repeated_or_fragmented_garbage,
)


RESULT_FIELD_ORDER = [
    "benchmark_run_id",
    "suite_id",
    "suite_label",
    "source_id",
    "source_label",
    "source_url",
    "video_id",
    "topic_class",
    "app_surface",
    "app_version",
    "lane_id",
    "lane_label",
    "expected_language",
    "detected_language",
    "target_language",
    "source_duration_seconds",
    "embedded_english_subtitles",
    "requested_processing_mode",
    "requested_translate_to",
    "requested_whisper_model",
    "requested_whisper_device",
    "requested_openai_project",
    "requested_openai_model",
    "requested_openai_transcription_model",
    "requested_protected_terms_profile",
    "processing_mode",
    "openai_project",
    "transcription_provider",
    "transcription_model",
    "translation_provider_name",
    "translation_model",
    "protected_terms_profile",
    "validation_status",
    "package_status",
    "run_exit_code",
    "run_duration_seconds",
    "real_time_factor",
    "whisper_mode",
    "whisper_requested_device",
    "whisper_selected_device",
    "whisper_device_switch_count",
    "estimated_openai_text_cost_usd",
    "output_root",
    "package_output_path",
    "summary_csv_path",
    "validation_report_path",
    "source_transcript_txt",
    "source_transcript_json",
    "translated_transcript_txt",
    "translated_transcript_json",
    "lane_meta_path",
    "translation_requested",
    "translation_performed",
    "translation_skipped_reason",
    "validation_warning_count",
    "contamination_count",
    "mojibake_count",
    "encoding_artifact_count",
    "compression_warning_count",
    "garbage_pattern_count",
    "failed_translated_segment_count",
    "named_entity_required_count",
    "named_entity_source_present_count",
    "named_entity_translation_present_count",
    "named_entity_source_substitution_count",
    "named_entity_translation_substitution_count",
    "named_entity_source_missing_count",
    "named_entity_translation_missing_count",
    "named_entity_issue_count",
    "brooklands_source_variant_flag",
    "brooklands_to_brooklyn_flag",
    "benchmark_accuracy_penalty",
    "benchmark_speed_penalty",
    "benchmark_cost_penalty",
    "benchmark_score",
    "benchmark_status",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in ("", None):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        if value in ("", None):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _read_csv_first_row(path: Path | None) -> dict[str, str]:
    if not path or not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            return {str(key): str(value or "") for key, value in row.items()}
    return {}


def _read_text_file(path: Path | None) -> str:
    if not path or not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _read_transcript_text(text_path: Path | None, json_path: Path | None) -> str:
    text = _read_text_file(text_path)
    if text.strip():
        return text
    payload = _load_json(json_path)
    segments = payload.get("segments") or []
    joined = "\n".join(
        str(segment.get("text") or "").strip()
        for segment in segments
        if str(segment.get("text") or "").strip()
    )
    return joined.strip()


def _search_normalized(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(character for character in normalized.casefold() if not unicodedata.combining(character))


def _contains_term(text: str, term: str) -> bool:
    if not text or not term:
        return False
    if term.casefold() in text.casefold():
        return True
    return _search_normalized(term) in _search_normalized(text)


def _collect_bad_form_matches(text: str, bad_forms: list[str]) -> list[str]:
    if not text:
        return []
    matches: list[str] = []
    matched_norms: list[str] = []
    original_index = {value: index for index, value in enumerate(bad_forms)}
    for value in sorted(bad_forms, key=lambda item: len(_search_normalized(item)), reverse=True):
        if not _contains_term(text, value):
            continue
        normalized_value = _search_normalized(value)
        if any(normalized_value in existing for existing in matched_norms):
            continue
        matches.append(value)
        matched_norms.append(normalized_value)
    return sorted(matches, key=lambda item: original_index.get(item, 0))


def build_named_entity_checks(
    source_entry: dict[str, Any],
    *,
    source_text: str,
    translation_text: str,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    brooklands_source_variant_flag = False
    brooklands_to_brooklyn_flag = False
    expectations = source_entry.get("expected_named_entities") or []

    for item in expectations:
        term = str(item.get("term") or "").strip()
        if not term:
            continue
        expected_in_source = bool(item.get("expected_in_source"))
        expected_in_translation = bool(item.get("expected_in_translation"))
        bad_forms = [str(value).strip() for value in (item.get("bad_forms") or []) if str(value).strip()]
        source_bad_form_matches = _collect_bad_form_matches(source_text, bad_forms)
        translation_bad_form_matches = _collect_bad_form_matches(translation_text, bad_forms)
        source_present = _contains_term(source_text, term)
        translation_available = bool(translation_text.strip())
        translation_present = translation_available and _contains_term(translation_text, term)
        issues: list[str] = []
        source_issue = ""
        translation_issue = ""

        # Treat close-form matches as substitutions only when the expected term
        # is absent. This lets manifests record noisy variants without turning
        # mixed transcripts into false benchmark warnings.
        if expected_in_source and source_bad_form_matches and not source_present:
            source_issue = "substituted variant in source transcript"
            issues.append(source_issue)
        elif expected_in_source and not source_present:
            source_issue = "missing from source transcript"
            issues.append(source_issue)

        if translation_available and expected_in_translation and translation_bad_form_matches and not translation_present:
            translation_issue = "substituted variant in English translation"
            issues.append(translation_issue)
        elif translation_available and expected_in_translation and not translation_present:
            translation_issue = "missing from English translation"
            issues.append(translation_issue)

        if term.casefold() == "brooklands" and any(value.casefold().startswith("brooklyn") for value in source_bad_form_matches):
            brooklands_source_variant_flag = True
        if term.casefold() == "brooklands" and any(value.casefold().startswith("brooklyn") for value in translation_bad_form_matches):
            brooklands_to_brooklyn_flag = True

        checks.append(
            {
                "term": term,
                "category": str(item.get("category") or ""),
                "source_present": source_present,
                "translation_present": translation_present,
                "source_bad_form_matches": source_bad_form_matches,
                "translation_bad_form_matches": translation_bad_form_matches,
                "bad_form_matches": translation_bad_form_matches,
                "source_issue": source_issue,
                "translation_issue": translation_issue,
                "issue": "; ".join(issues),
            }
        )

    return {
        "checks": checks,
        "named_entity_required_count": len(checks),
        "named_entity_source_present_count": sum(1 for item in checks if item["source_present"]),
        "named_entity_translation_present_count": sum(1 for item in checks if item["translation_present"]),
        "named_entity_source_substitution_count": sum(1 for item in checks if item["source_bad_form_matches"]),
        "named_entity_translation_substitution_count": sum(1 for item in checks if item["translation_bad_form_matches"]),
        "named_entity_source_missing_count": sum(1 for item in checks if item["source_issue"] == "missing from source transcript"),
        "named_entity_translation_missing_count": sum(1 for item in checks if item["translation_issue"] == "missing from English translation"),
        "named_entity_issue_count": sum(
            1
            for item in checks
            if item["issue"]
        ),
        "brooklands_source_variant_flag": brooklands_source_variant_flag,
        "brooklands_to_brooklyn_flag": brooklands_to_brooklyn_flag,
    }


def _summarize_translation_skip(row: dict[str, Any]) -> str:
    combined = " | ".join(
        [
            str(row.get("translation_status") or ""),
            str(row.get("translation_notes") or ""),
            str(row.get("openai_translation_summary") or ""),
        ]
    ).casefold()
    if "source already english" in combined and "cop" in combined:
        return "source already English; original transcript copied"
    return ""


def _score_result(row: dict[str, Any]) -> tuple[float, float, float, float, str]:
    accuracy_penalty = (
        row["validation_warning_count"] * 3.0
        + row["contamination_count"] * 25.0
        + row["mojibake_count"] * 18.0
        + row["encoding_artifact_count"] * 18.0
        + row["compression_warning_count"] * 6.0
        + row["garbage_pattern_count"] * 10.0
        + row["failed_translated_segment_count"] * 8.0
        + row["named_entity_issue_count"] * 20.0
    )
    if row["brooklands_to_brooklyn_flag"]:
        accuracy_penalty += 100.0

    speed_penalty = 0.0
    real_time_factor = row["real_time_factor"]
    if real_time_factor > 0:
        speed_penalty = min(20.0, max(0.0, (real_time_factor - 0.75) * 8.0))

    cost_penalty = min(15.0, row["estimated_openai_text_cost_usd"] * 1000.0)
    score = max(0.0, 100.0 - accuracy_penalty - speed_penalty - cost_penalty)

    package_status = str(row["package_status"]).upper()
    if row["benchmark_status"] == "deferred":
        status = "deferred"
        score = 0.0
    elif row["run_exit_code"] != 0 or "FAIL" in package_status:
        status = "rejected"
        score = 0.0
    elif row["brooklands_to_brooklyn_flag"] or row["contamination_count"] > 0 or row["mojibake_count"] > 0:
        status = "rejected"
    elif row["named_entity_issue_count"] > 0 or row["compression_warning_count"] > 0 or row["validation_warning_count"] > 0:
        status = "warning"
    else:
        status = "accepted"

    return (
        round(accuracy_penalty, 3),
        round(speed_penalty, 3),
        round(cost_penalty, 3),
        round(score, 3),
        status,
    )


def _build_result_row(
    *,
    suite_entry: dict[str, Any],
    source_entry: dict[str, Any],
    lane_entry: dict[str, Any],
    lane_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    meta = lane_meta or {}
    output_root = Path(str(meta.get("output_root") or "")).resolve() if meta.get("output_root") else None
    summary_csv_path = Path(str(meta.get("summary_csv_path") or "")).resolve() if meta.get("summary_csv_path") else None
    summary_row = _read_csv_first_row(summary_csv_path)

    if not summary_row and output_root:
        fallback_summary = output_root / "PROCESSING_SUMMARY.csv"
        if fallback_summary.exists():
            summary_csv_path = fallback_summary
            summary_row = _read_csv_first_row(summary_csv_path)

    validation_report_path = Path(summary_row.get("translation_validation_report") or "").resolve() if summary_row.get("translation_validation_report") else None
    validation_report = _load_json(validation_report_path)

    source_txt_path = Path(summary_row.get("transcript_original_txt") or summary_row.get("transcript_txt") or "").resolve() if (summary_row.get("transcript_original_txt") or summary_row.get("transcript_txt")) else None
    source_json_path = Path(summary_row.get("transcript_original_json") or summary_row.get("transcript_json") or "").resolve() if (summary_row.get("transcript_original_json") or summary_row.get("transcript_json")) else None
    translated_txt_path = Path(summary_row.get("translation_transcript_txt") or "").resolve() if summary_row.get("translation_transcript_txt") else None
    translated_json_path = Path(summary_row.get("translation_transcript_json") or "").resolve() if summary_row.get("translation_transcript_json") else None

    source_text = _read_transcript_text(source_txt_path, source_json_path)
    translation_text = _read_transcript_text(translated_txt_path, translated_json_path)

    contamination_count = max(
        _coerce_int(summary_row.get("contamination_count")),
        _coerce_int(validation_report.get("contamination_count")),
        len(detect_assistant_meta_contamination(translation_text)),
    )
    mojibake_count = max(
        _coerce_int(validation_report.get("mojibake_count")),
        _coerce_int(summary_row.get("encoding_artifact_count")),
        len(detect_mojibake(translation_text)),
    )
    garbage_pattern_count = max(
        _coerce_int(validation_report.get("garbage_pattern_count")),
        len(detect_repeated_or_fragmented_garbage(translation_text, source_text=source_text)),
    )
    encoding_artifact_count = max(
        _coerce_int(summary_row.get("encoding_artifact_count")),
        _coerce_int(validation_report.get("encoding_artifact_count")),
    )
    validation_warning_count = max(
        _coerce_int(summary_row.get("validation_warning_count")),
        _coerce_int(validation_report.get("warning_count")),
    )
    compression_warning_count = max(
        _coerce_int(summary_row.get("compression_warning_count")),
        _coerce_int(validation_report.get("compression_warning_count")),
    )
    failed_translated_segment_count = max(
        _coerce_int(summary_row.get("failed_translated_segment_count")),
        _coerce_int(validation_report.get("failed_segment_count")),
    )

    named_entity_summary = build_named_entity_checks(
        source_entry,
        source_text=source_text,
        translation_text=translation_text,
    )
    translation_skipped_reason = _summarize_translation_skip(summary_row)
    translation_requested = bool(lane_entry.get("translate_to") or summary_row.get("translation_targets"))
    translation_performed = bool(translation_text.strip()) and not bool(translation_skipped_reason)

    row: dict[str, Any] = {
        "benchmark_run_id": meta.get("benchmark_run_id") or f"{suite_entry['suite_id']}__{source_entry['source_id']}__{lane_entry['lane_id']}",
        "suite_id": suite_entry["suite_id"],
        "suite_label": suite_entry.get("suite_label") or suite_entry["suite_id"],
        "source_id": source_entry["source_id"],
        "source_label": source_entry.get("title") or source_entry["source_id"],
        "source_url": source_entry.get("url") or "",
        "video_id": source_entry.get("video_id") or "",
        "topic_class": source_entry.get("topic_class") or "",
        "app_surface": summary_row.get("app_surface") or lane_entry.get("app_surface") or meta.get("app_surface") or "",
        "app_version": summary_row.get("app_version") or "",
        "lane_id": lane_entry["lane_id"],
        "lane_label": lane_entry.get("label") or lane_entry["lane_id"],
        "expected_language": source_entry.get("expected_language") or "",
        "detected_language": summary_row.get("detected_language") or "",
        "target_language": summary_row.get("target_language") or lane_entry.get("translate_to") or "",
        "source_duration_seconds": _coerce_float(summary_row.get("source_duration_seconds")),
        "embedded_english_subtitles": source_entry.get("embedded_english_subtitles") or "",
        "requested_processing_mode": lane_entry.get("processing_mode") or "",
        "requested_translate_to": lane_entry.get("translate_to") or "",
        "requested_whisper_model": lane_entry.get("whisper_model") or "",
        "requested_whisper_device": lane_entry.get("whisper_device") or "",
        "requested_openai_project": lane_entry.get("openai_project") or "",
        "requested_openai_model": lane_entry.get("openai_model") or "",
        "requested_openai_transcription_model": lane_entry.get("openai_transcription_model") or "",
        "requested_protected_terms_profile": lane_entry.get("protected_terms_profile") or "",
        "processing_mode": summary_row.get("processing_mode") or "",
        "openai_project": summary_row.get("openai_project") or "",
        "transcription_provider": summary_row.get("transcription_provider") or "",
        "transcription_model": summary_row.get("transcription_model") or "",
        "translation_provider_name": summary_row.get("translation_provider_name") or "",
        "translation_model": summary_row.get("translation_model") or "",
        "protected_terms_profile": summary_row.get("protected_terms_profile") or summary_row.get("glossary_profile") or "",
        "validation_status": summary_row.get("translation_validation_status") or str(validation_report.get("status") or ""),
        "package_status": summary_row.get("package_status") or "",
        "run_exit_code": _coerce_int(meta.get("run_exit_code")),
        "run_duration_seconds": _coerce_float(meta.get("run_duration_seconds")),
        "real_time_factor": 0.0,
        "whisper_mode": summary_row.get("whisper_mode") or "",
        "whisper_requested_device": summary_row.get("whisper_requested_device") or "",
        "whisper_selected_device": summary_row.get("whisper_selected_device") or "",
        "whisper_device_switch_count": _coerce_int(summary_row.get("whisper_device_switch_count")),
        "estimated_openai_text_cost_usd": _coerce_float(summary_row.get("estimated_openai_text_cost_usd")),
        "output_root": str(output_root) if output_root else "",
        "package_output_path": summary_row.get("output_path") or str(output_root or ""),
        "summary_csv_path": str(summary_csv_path) if summary_csv_path else "",
        "validation_report_path": str(validation_report_path) if validation_report_path else "",
        "source_transcript_txt": str(source_txt_path) if source_txt_path else "",
        "source_transcript_json": str(source_json_path) if source_json_path else "",
        "translated_transcript_txt": str(translated_txt_path) if translated_txt_path else "",
        "translated_transcript_json": str(translated_json_path) if translated_json_path else "",
        "lane_meta_path": str(Path(str(meta.get("lane_meta_path") or "")).resolve()) if meta.get("lane_meta_path") else "",
        "translation_requested": translation_requested,
        "translation_performed": translation_performed,
        "translation_skipped_reason": translation_skipped_reason,
        "validation_warning_count": validation_warning_count,
        "contamination_count": contamination_count,
        "mojibake_count": mojibake_count,
        "encoding_artifact_count": encoding_artifact_count,
        "compression_warning_count": compression_warning_count,
        "garbage_pattern_count": garbage_pattern_count,
        "failed_translated_segment_count": failed_translated_segment_count,
        "named_entity_required_count": named_entity_summary["named_entity_required_count"],
        "named_entity_source_present_count": named_entity_summary["named_entity_source_present_count"],
        "named_entity_translation_present_count": named_entity_summary["named_entity_translation_present_count"],
        "named_entity_source_substitution_count": named_entity_summary["named_entity_source_substitution_count"],
        "named_entity_translation_substitution_count": named_entity_summary["named_entity_translation_substitution_count"],
        "named_entity_source_missing_count": named_entity_summary["named_entity_source_missing_count"],
        "named_entity_translation_missing_count": named_entity_summary["named_entity_translation_missing_count"],
        "named_entity_issue_count": named_entity_summary["named_entity_issue_count"],
        "brooklands_source_variant_flag": named_entity_summary["brooklands_source_variant_flag"],
        "brooklands_to_brooklyn_flag": named_entity_summary["brooklands_to_brooklyn_flag"],
        "benchmark_accuracy_penalty": 0.0,
        "benchmark_speed_penalty": 0.0,
        "benchmark_cost_penalty": 0.0,
        "benchmark_score": 0.0,
        "benchmark_status": "deferred" if not meta else "",
        "named_entity_checks": named_entity_summary["checks"],
    }

    if row["source_duration_seconds"] > 0 and row["run_duration_seconds"] > 0:
        row["real_time_factor"] = round(row["run_duration_seconds"] / row["source_duration_seconds"], 4)

    penalties = _score_result(row)
    row["benchmark_accuracy_penalty"] = penalties[0]
    row["benchmark_speed_penalty"] = penalties[1]
    row["benchmark_cost_penalty"] = penalties[2]
    row["benchmark_score"] = penalties[3]
    row["benchmark_status"] = penalties[4]
    return row


def _build_deferred_row(
    *,
    suite_entry: dict[str, Any],
    source_entry: dict[str, Any],
    lane_entry: dict[str, Any],
) -> dict[str, Any]:
    return _build_result_row(
        suite_entry=suite_entry,
        source_entry=source_entry,
        lane_entry=lane_entry,
        lane_meta={},
    )


def _load_lane_metas(run_root: Path) -> dict[tuple[str, str], dict[str, Any]]:
    results: dict[tuple[str, str], dict[str, Any]] = {}
    for meta_path in sorted(run_root.rglob("lane-meta.json")):
        payload = _load_json(meta_path)
        if not payload:
            continue
        payload["lane_meta_path"] = str(meta_path)
        key = (str(payload.get("source_id") or "").strip(), str(payload.get("lane_id") or "").strip())
        if key[0] and key[1]:
            results[key] = payload
    return results


def collect_results(
    *,
    run_root: Path,
    suite_manifest_path: Path,
    lane_manifest_path: Path,
    selected_source_ids: list[str] | None = None,
    selected_lane_ids: list[str] | None = None,
    include_deferred: bool = False,
) -> dict[str, Any]:
    suite_manifest = _load_json(suite_manifest_path)
    lane_manifest = _load_json(lane_manifest_path)
    suite_sources = {item["source_id"]: item for item in suite_manifest.get("sources") or []}
    lane_sources = {item["lane_id"]: item for item in lane_manifest.get("lanes") or []}

    source_ids = selected_source_ids or list(suite_sources.keys())
    lane_ids = selected_lane_ids or list(lane_sources.keys())
    lane_metas = _load_lane_metas(run_root)

    rows: list[dict[str, Any]] = []
    for source_id in source_ids:
        source_entry = suite_sources[source_id]
        for lane_id in lane_ids:
            lane_entry = lane_sources[lane_id]
            meta = lane_metas.get((source_id, lane_id))
            if meta:
                row = _build_result_row(
                    suite_entry=suite_manifest,
                    source_entry=source_entry,
                    lane_entry=lane_entry,
                    lane_meta=meta,
                )
                rows.append(row)
            elif include_deferred:
                rows.append(
                    _build_deferred_row(
                        suite_entry=suite_manifest,
                        source_entry=source_entry,
                        lane_entry=lane_entry,
                    )
                )

    lane_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["benchmark_status"] != "deferred":
            lane_groups[row["lane_id"]].append(row)

    lane_rollups: list[dict[str, Any]] = []
    for lane_id, group in sorted(lane_groups.items()):
        lane_entry = lane_sources.get(lane_id, {})
        accepted_like = [row for row in group if row["benchmark_status"] in {"accepted", "warning"}]
        avg_score = round(sum(row["benchmark_score"] for row in group) / len(group), 3)
        avg_runtime = round(sum(row["run_duration_seconds"] for row in group) / len(group), 3)
        total_cost = round(sum(row["estimated_openai_text_cost_usd"] for row in group), 6)
        status = "accepted"
        if any(row["benchmark_status"] == "rejected" for row in group):
            status = "warning"
        if not accepted_like:
            status = "rejected"
        lane_rollups.append(
            {
                "lane_id": lane_id,
                "lane_label": lane_entry.get("label") or lane_id,
                "completed_runs": len(group),
                "average_score": avg_score,
                "average_runtime_seconds": avg_runtime,
                "total_estimated_openai_text_cost_usd": total_cost,
                "lane_status": status,
            }
        )

    best_local = None
    best_accuracy = None
    best_speed = None
    local_rollups = [item for item in lane_rollups if item["lane_id"].startswith("local-") and item["lane_status"] in {"accepted", "warning"}]
    accepted_rollups = [item for item in lane_rollups if item["lane_status"] in {"accepted", "warning"}]
    if local_rollups:
        best_local = max(local_rollups, key=lambda item: (item["average_score"], -item["average_runtime_seconds"]))
    if accepted_rollups:
        best_accuracy = max(accepted_rollups, key=lambda item: (item["average_score"], -item["average_runtime_seconds"]))
        best_speed = min(accepted_rollups, key=lambda item: item["average_runtime_seconds"])

    payload = {
        "generated_at_utc": _utc_now(),
        "run_root": str(run_root.resolve()),
        "suite_manifest_path": str(suite_manifest_path.resolve()),
        "lane_manifest_path": str(lane_manifest_path.resolve()),
        "suite": {
            "suite_id": suite_manifest.get("suite_id") or "",
            "suite_label": suite_manifest.get("suite_label") or suite_manifest.get("suite_id") or "",
            "tier": suite_manifest.get("tier") or "",
        },
        "selected_source_ids": source_ids,
        "selected_lane_ids": lane_ids,
        "results": rows,
        "lane_rollups": lane_rollups,
        "best_lanes": {
            "best_local_lane": best_local,
            "best_accuracy_lane": best_accuracy,
            "best_speed_lane": best_speed,
        },
    }
    return payload


def _write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELD_ORDER)
        writer.writeheader()
        for row in rows:
            slim_row = {field: row.get(field, "") for field in RESULT_FIELD_ORDER}
            writer.writerow(slim_row)


def _format_lane_line(value: dict[str, Any] | None) -> str:
    if not value:
        return "not established in this pilot"
    return (
        f"{value['lane_id']} ({value['lane_label']}) "
        f"[avg score {value['average_score']}, avg runtime {value['average_runtime_seconds']}s]"
    )


def _write_markdown_summary(path: Path, payload: dict[str, Any]) -> None:
    rows = payload["results"]
    accepted = sum(1 for row in rows if row["benchmark_status"] == "accepted")
    warnings = sum(1 for row in rows if row["benchmark_status"] == "warning")
    rejected = sum(1 for row in rows if row["benchmark_status"] == "rejected")
    deferred = sum(1 for row in rows if row["benchmark_status"] == "deferred")
    lines = [
        "# Benchmark Summary",
        "",
        f"- Generated: {payload['generated_at_utc']}",
        f"- Suite: {payload['suite']['suite_label']} ({payload['suite']['suite_id']})",
        f"- Run root: `{payload['run_root']}`",
        f"- Result counts: accepted={accepted}, warning={warnings}, rejected={rejected}, deferred={deferred}",
        "",
        "## Best Current Lanes",
        "",
        f"- Best local lane: {_format_lane_line(payload['best_lanes']['best_local_lane'])}",
        f"- Best accuracy lane: {_format_lane_line(payload['best_lanes']['best_accuracy_lane'])}",
        f"- Best speed lane: {_format_lane_line(payload['best_lanes']['best_speed_lane'])}",
        "",
        "## Lane Rollups",
        "",
        "| Lane | Completed | Avg Score | Avg Runtime (s) | Cost USD | Status |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for lane in payload["lane_rollups"]:
        lines.append(
            f"| `{lane['lane_id']}` | {lane['completed_runs']} | {lane['average_score']} | "
            f"{lane['average_runtime_seconds']} | {lane['total_estimated_openai_text_cost_usd']} | {lane['lane_status']} |"
        )

    lines.extend(
        [
            "",
            "## Run Rows",
            "",
            "| Source | Lane | Status | Score | Runtime (s) | Cost USD | Notes |",
            "| --- | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for row in rows:
        notes: list[str] = []
        if row["brooklands_to_brooklyn_flag"]:
            notes.append("translation Brooklands->Brooklyn")
        if row["brooklands_source_variant_flag"]:
            notes.append("source Brooklands variant")
        if row["translation_skipped_reason"]:
            notes.append(row["translation_skipped_reason"])
        if row["named_entity_source_substitution_count"] > 0 and not row["brooklands_source_variant_flag"]:
            notes.append(f"source substitutions={row['named_entity_source_substitution_count']}")
        if row["named_entity_source_missing_count"] > 0:
            notes.append(f"source missing={row['named_entity_source_missing_count']}")
        if row["named_entity_translation_substitution_count"] > 0 and not row["brooklands_to_brooklyn_flag"]:
            notes.append(f"translation substitutions={row['named_entity_translation_substitution_count']}")
        if row["named_entity_translation_missing_count"] > 0:
            notes.append(f"translation missing={row['named_entity_translation_missing_count']}")
        if row["named_entity_issue_count"] > 0 and not (
            row["brooklands_to_brooklyn_flag"]
            or row["brooklands_source_variant_flag"]
            or row["named_entity_source_substitution_count"] > 0
            or row["named_entity_source_missing_count"] > 0
            or row["named_entity_translation_substitution_count"] > 0
            or row["named_entity_translation_missing_count"] > 0
        ):
            notes.append(f"named-entity issues={row['named_entity_issue_count']}")
        if row["validation_warning_count"] > 0:
            notes.append(f"validation warnings={row['validation_warning_count']}")
        if row["compression_warning_count"] > 0:
            notes.append(f"compression={row['compression_warning_count']}")
        lines.append(
            f"| `{row['source_id']}` | `{row['lane_id']}` | {row['benchmark_status']} | "
            f"{row['benchmark_score']} | {row['run_duration_seconds']} | {row['estimated_openai_text_cost_usd']} | "
            f"{'; '.join(notes)} |"
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate Media Manglers benchmark outputs.")
    parser.add_argument("--run-root", required=True, help="Benchmark run root containing lane-meta.json files.")
    parser.add_argument("--suite-manifest", required=True, help="Suite manifest JSON path.")
    parser.add_argument("--lane-manifest", required=True, help="Lane manifest JSON path.")
    parser.add_argument("--lane-ids", default="", help="Comma-separated lane ids to report.")
    parser.add_argument("--source-ids", default="", help="Comma-separated source ids to report.")
    parser.add_argument("--include-deferred", action="store_true", help="Include deferred rows for selected combos not run.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    run_root = Path(args.run_root)
    suite_manifest_path = Path(args.suite_manifest)
    lane_manifest_path = Path(args.lane_manifest)
    selected_lane_ids = [item.strip() for item in args.lane_ids.split(",") if item.strip()]
    selected_source_ids = [item.strip() for item in args.source_ids.split(",") if item.strip()]

    payload = collect_results(
        run_root=run_root,
        suite_manifest_path=suite_manifest_path,
        lane_manifest_path=lane_manifest_path,
        selected_source_ids=selected_source_ids or None,
        selected_lane_ids=selected_lane_ids or None,
        include_deferred=args.include_deferred,
    )

    summary_dir = run_root / "summary"
    summary_csv_path = summary_dir / "benchmark-summary.csv"
    summary_json_path = summary_dir / "benchmark-results.json"
    summary_md_path = summary_dir / "benchmark-summary.md"
    _write_summary_csv(summary_csv_path, payload["results"])
    _write_json(summary_json_path, payload)
    _write_markdown_summary(summary_md_path, payload)

    print(f"[benchmark-report] Wrote {summary_csv_path}")
    print(f"[benchmark-report] Wrote {summary_json_path}")
    print(f"[benchmark-report] Wrote {summary_md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
