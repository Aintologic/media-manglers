"""Deterministic Workflow 3 sampling and output estimates."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from typing import Any, Mapping


AUDIO_SNIPPET_MAX_SECONDS = 300.0
LARGE_PACKAGE_IMAGE_THRESHOLD = 3_000


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return default if value is None else bool(value)


def parse_frame_offsets(value: Any) -> list[float]:
    if isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = re.split(r"[,;\r\n]+", str(value or ""))
    offsets: list[float] = []
    for raw_value in values:
        text = str(raw_value).strip()
        if not text:
            continue
        try:
            offsets.append(float(text))
        except ValueError:
            continue
    return offsets


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


def _cadence_times(duration: float, cadence: float) -> list[float]:
    if cadence <= 0 or duration < 0:
        return []
    count = int(math.floor((duration + 0.001) / cadence)) + 1
    values = [min(duration, index * cadence) for index in range(max(0, count))]
    if not values or abs(values[-1] - duration) > 0.5:
        values.append(duration)
    return values


@dataclass(frozen=True, slots=True)
class SamplingEstimate:
    visual_audio_window_seconds: float
    narration_context_seconds: float
    fixed_offset_frame_count: int
    requested_cadence_frame_count: int
    max_frames_per_candidate: int
    estimated_saved_full_frames_per_candidate: int
    panel_crop_image_multiplier: int
    total_image_multiplier: int
    max_fully_rendered_items: int
    worst_case_image_count: int | None
    cadence_is_capped: bool
    audio_would_exceed_cap: bool
    narration_extends_beyond_visual_audio: bool
    large_package_warning: bool
    warnings: tuple[str, ...] = field(default_factory=tuple)


def estimate_sampling(settings: Mapping[str, Any]) -> SamplingEstimate:
    pre_seconds = max(0.0, _as_float(settings.get("pre_context_seconds"), 0.0))
    post_seconds = max(0.0, _as_float(settings.get("post_context_seconds"), 0.0))
    visual_duration = pre_seconds + post_seconds
    fragmented = _as_bool(settings.get("fragmented_narration_mode"), True)
    narration_pre = max(0.0, _as_float(settings.get("narration_context_pre_seconds"), 0.0))
    narration_post = max(0.0, _as_float(settings.get("narration_context_post_seconds"), 0.0))
    narration_duration = narration_pre + narration_post if fragmented else visual_duration
    cadence = max(0.0, _as_float(settings.get("evidence_frame_cadence_seconds"), 0.0))
    max_frames = max(0, _as_int(settings.get("evidence_max_frames_per_candidate"), 0))
    max_items = max(0, _as_int(settings.get("evidence_max_items"), 0))

    marker_position = pre_seconds
    fixed_times: list[float] = []
    fixed_keys: set[int] = set()
    for offset in parse_frame_offsets(settings.get("evidence_frame_offsets")):
        timestamp = max(0.0, min(visual_duration, marker_position + offset))
        key = int(round(timestamp * 1_000))
        if key in fixed_keys:
            continue
        if max_frames > 0 and len(fixed_times) >= max_frames:
            break
        fixed_keys.add(key)
        fixed_times.append(timestamp)

    cadence_times = _cadence_times(visual_duration, cadence)
    requested_cadence_count = len(cadence_times)
    possible_keys = set(fixed_keys)
    for timestamp in cadence_times:
        possible_keys.add(int(round(timestamp * 1_000)))
    possible_full_frame_count = len(possible_keys)

    saved_keys = set(fixed_keys)
    if max_frames > 0 and cadence > 0:
        remaining = max(0, max_frames - len(saved_keys))
        for timestamp in _sample_evenly(cadence_times, remaining):
            saved_keys.add(int(round(timestamp * 1_000)))
    saved_full_frames = len(saved_keys)
    cadence_is_capped = max_frames > 0 and possible_full_frame_count > max_frames

    panel_mode = str(settings.get("evidence_panel_crops") or "Auto").strip().lower()
    panel_multiplier = 0 if panel_mode == "off" else 3
    total_multiplier = 1 + panel_multiplier
    worst_case_images = saved_full_frames * total_multiplier * max_items if max_items > 0 else None
    audio_would_exceed = visual_duration > AUDIO_SNIPPET_MAX_SECONDS
    narration_extends = fragmented and (
        narration_pre > pre_seconds or narration_post > post_seconds
    )
    large_package = worst_case_images is None or worst_case_images > LARGE_PACKAGE_IMAGE_THRESHOLD

    warnings: list[str] = []
    if cadence_is_capped:
        warnings.append("Cadence requests more frames than the per-candidate cap; effective sampling will be sparser.")
    if audio_would_exceed:
        warnings.append("The visual/audio window exceeds the 300-second primary audio cap.")
    if narration_extends:
        warnings.append("Narration context extends beyond visual/audio evidence but does not add frames or audio duration.")
    if panel_multiplier:
        warnings.append("Exact 5760x1080 triple-screen frames can add three panel crops per saved full frame.")
    if max_items == 0:
        warnings.append("Max evidence items is unlimited, so a finite worst-case package image count cannot be estimated.")
    elif large_package:
        warnings.append("These settings can create a very large evidence package.")

    return SamplingEstimate(
        visual_audio_window_seconds=visual_duration,
        narration_context_seconds=narration_duration,
        fixed_offset_frame_count=len(fixed_times),
        requested_cadence_frame_count=requested_cadence_count,
        max_frames_per_candidate=max_frames,
        estimated_saved_full_frames_per_candidate=saved_full_frames,
        panel_crop_image_multiplier=panel_multiplier,
        total_image_multiplier=total_multiplier,
        max_fully_rendered_items=max_items,
        worst_case_image_count=worst_case_images,
        cadence_is_capped=cadence_is_capped,
        audio_would_exceed_cap=audio_would_exceed,
        narration_extends_beyond_visual_audio=narration_extends,
        large_package_warning=large_package,
        warnings=tuple(warnings),
    )
