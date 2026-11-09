"""Adaptive runtime planning for local Whisper runs."""

from __future__ import annotations

import math
from typing import Any


_RUNTIME_PROFILES: dict[str, dict[str, dict[str, float]]] = {
    "cpu": {
        "tiny": {"rtf": 0.75, "startup_seconds": 15.0},
        "base": {"rtf": 1.00, "startup_seconds": 20.0},
        "small": {"rtf": 1.40, "startup_seconds": 30.0},
        "medium": {"rtf": 2.60, "startup_seconds": 45.0},
        "large": {"rtf": 5.50, "startup_seconds": 75.0},
        "turbo": {"rtf": 1.10, "startup_seconds": 25.0},
        "default": {"rtf": 3.00, "startup_seconds": 45.0},
    },
    "gpu": {
        "tiny": {"rtf": 0.15, "startup_seconds": 10.0},
        "base": {"rtf": 0.20, "startup_seconds": 12.0},
        "small": {"rtf": 0.28, "startup_seconds": 20.0},
        "medium": {"rtf": 0.45, "startup_seconds": 30.0},
        "large": {"rtf": 0.90, "startup_seconds": 45.0},
        "turbo": {"rtf": 0.22, "startup_seconds": 18.0},
        "default": {"rtf": 0.60, "startup_seconds": 30.0},
    },
}

_LONG_RUN_PROMPT_SECONDS = 45.0 * 60.0
_SHORT_GPU_LARGE_CALIBRATION_TRIGGER_SECONDS = 5.0 * 60.0
_SHORT_GPU_LARGE_GUARDRAIL_RTF = 1.35
_SHORT_GPU_LARGE_MIN_SAMPLE_SECONDS = 45.0
_HARD_BUDGET_MULTIPLIER = 2.50
_HARD_BUDGET_MIN_MARGIN_SECONDS = 30.0 * 60.0


def _coerce_non_negative_float(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _coerce_non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def normalize_model_family(model_name: str) -> str:
    normalized = (model_name or "").strip().lower()
    if normalized.endswith(".en"):
        normalized = normalized[:-3]

    for family in ("tiny", "base", "small", "medium", "large", "turbo"):
        if normalized == family or normalized.startswith(family + "-") or normalized.startswith(family + ".") or normalized.startswith(family + "_"):
            return family

    return "default"


def get_runtime_profile(model_name: str, gpu_capable: bool) -> dict[str, float | str]:
    runtime_key = "gpu" if gpu_capable else "cpu"
    model_family = normalize_model_family(model_name)
    profile = _RUNTIME_PROFILES[runtime_key].get(model_family) or _RUNTIME_PROFILES[runtime_key]["default"]
    return {
        "runtime_key": runtime_key,
        "runtime_path_label": "GPU-capable" if gpu_capable else "CPU-only",
        "model_family": model_family,
        "rtf": float(profile["rtf"]),
        "startup_seconds": float(profile["startup_seconds"]),
    }


def _task_multiplier(task_name: str) -> float:
    normalized = (task_name or "").strip().lower()
    return 1.05 if normalized == "translate" else 1.00


def _status_is_warning_worthy(status: str) -> bool:
    normalized = (status or "").strip().lower()
    if not normalized:
        return False

    benign_markers = (
        "short enough",
        "not long enough",
        "used short-sample calibration",
        "explicit -whispertimeoutseconds override",
    )
    return not any(marker in normalized for marker in benign_markers)


def recommend_calibration(
    *,
    source_duration_seconds: float,
    estimated_runtime_seconds: float,
    model_name: str,
    gpu_capable: bool,
) -> dict[str, Any]:
    duration = _coerce_non_negative_float(source_duration_seconds)
    estimated = _coerce_non_negative_float(estimated_runtime_seconds)
    model_family = normalize_model_family(model_name)

    if duration <= 0:
        return {
            "recommended": False,
            "sample_seconds": 0,
            "reason": "source duration was unavailable",
        }

    short_gpu_large_guardrail = gpu_capable and model_family == "large" and duration >= _SHORT_GPU_LARGE_CALIBRATION_TRIGGER_SECONDS

    if duration < 15.0 * 60.0 and not short_gpu_large_guardrail:
        return {
            "recommended": False,
            "sample_seconds": 0,
            "reason": "source media is short enough that a calibration pass would add unnecessary overhead",
        }

    should_force = (not gpu_capable) and model_family == "large" and duration >= 10.0 * 60.0
    if not should_force and not short_gpu_large_guardrail and estimated < 30.0 * 60.0:
        return {
            "recommended": False,
            "sample_seconds": 0,
            "reason": "the heuristic estimate is not long enough to justify a separate calibration sample",
        }

    min_sample_seconds = _SHORT_GPU_LARGE_MIN_SAMPLE_SECONDS if short_gpu_large_guardrail else 30.0
    sample_seconds = int(round(min(60.0, max(min_sample_seconds, duration * 0.02))))
    reason = (
        "large GPU runs on this source length benefit from a short machine-local calibration sample"
        if short_gpu_large_guardrail
        else "long local runs benefit from a short machine-local calibration sample"
    )
    return {
        "recommended": True,
        "sample_seconds": sample_seconds,
        "reason": reason,
    }


def build_runtime_plan(
    *,
    source_duration_seconds: float,
    model_name: str,
    gpu_capable: bool,
    heartbeat_seconds: int = 10,
    explicit_timeout_seconds: int = 0,
    task_name: str = "transcribe",
    calibration: dict[str, Any] | None = None,
    effective_duration_seconds: float | None = None,
    audio_track_count: int = 0,
    transcript_audio_mode: str = "",
) -> dict[str, Any]:
    source_duration = _coerce_non_negative_float(source_duration_seconds)
    effective_duration = _coerce_non_negative_float(effective_duration_seconds)
    if effective_duration <= 0:
        effective_duration = source_duration
    duration = effective_duration
    heartbeat = max(1, _coerce_non_negative_int(heartbeat_seconds))
    explicit_timeout = _coerce_non_negative_int(explicit_timeout_seconds)
    track_count = _coerce_non_negative_int(audio_track_count)
    profile = get_runtime_profile(model_name=model_name, gpu_capable=gpu_capable)
    fallback_rtf = float(profile["rtf"]) * _task_multiplier(task_name)
    startup_seconds = float(profile["startup_seconds"])

    if duration > 0:
        fallback_estimate_seconds = max(30.0, startup_seconds + (duration * fallback_rtf))
    else:
        fallback_estimate_seconds = max(30.0, startup_seconds + (15.0 * 60.0 * fallback_rtf))

    estimate_seconds = fallback_estimate_seconds
    estimate_source = "heuristic_profile"
    calibration_used = False
    calibration_status = ""
    observed_rtf = 0.0
    calibration_clip_seconds = 0.0
    calibration_elapsed_seconds = 0.0

    if calibration:
        calibration_clip_seconds = _coerce_non_negative_float(calibration.get("sample_duration_seconds"))
        calibration_elapsed_seconds = _coerce_non_negative_float(calibration.get("elapsed_seconds"))
        calibration_reason = str(calibration.get("reason") or "").strip()
        if calibration_clip_seconds > 0 and calibration_elapsed_seconds > 0:
            raw_processing_seconds = max(calibration_clip_seconds * 0.25, calibration_elapsed_seconds - startup_seconds)
            observed_rtf = max(fallback_rtf * 0.80, raw_processing_seconds / calibration_clip_seconds)
            estimate_seconds = max(
                fallback_estimate_seconds * 0.90,
                startup_seconds + (duration * observed_rtf),
            )
            estimate_source = "sample_calibration"
            calibration_used = True
            calibration_status = "used short-sample calibration"
        elif calibration_reason:
            calibration_status = calibration_reason

    if not calibration_used and gpu_capable and profile["model_family"] == "large" and duration >= _SHORT_GPU_LARGE_CALIBRATION_TRIGGER_SECONDS:
        estimate_seconds = max(
            estimate_seconds,
            startup_seconds + (duration * _SHORT_GPU_LARGE_GUARDRAIL_RTF),
        )

    calibration_recommendation = recommend_calibration(
        source_duration_seconds=duration,
        estimated_runtime_seconds=estimate_seconds,
        model_name=model_name,
        gpu_capable=gpu_capable,
    )

    budget_margin_seconds = max(
        _HARD_BUDGET_MIN_MARGIN_SECONDS,
        estimate_seconds * (_HARD_BUDGET_MULTIPLIER - 1.0),
    )
    adaptive_timeout_seconds = int(math.ceil(estimate_seconds + budget_margin_seconds))
    resolved_timeout_seconds = explicit_timeout if explicit_timeout > 0 else adaptive_timeout_seconds

    base_stall_seconds = max(240, heartbeat * 12)
    if resolved_timeout_seconds > 120:
        stall_timeout_seconds = max(60, min(base_stall_seconds, resolved_timeout_seconds - 30))
    else:
        stall_timeout_seconds = max(30, min(base_stall_seconds, max(30, resolved_timeout_seconds - 10)))

    warnings: list[str] = []
    if calibration_used:
        warnings.append("Adaptive hard runtime budget was refined with a short calibration sample and still includes conservative padding.")
    elif _status_is_warning_worthy(calibration_status):
        warnings.append(f"Calibration skipped or unavailable: {calibration_status}.")
    if explicit_timeout > 0:
        warnings.append("Explicit -WhisperTimeoutSeconds override is active and wins over the adaptive hard runtime budget.")

    return {
        "source_duration_seconds": int(round(source_duration)),
        "effective_duration_seconds": int(round(effective_duration)),
        "audio_track_count": track_count,
        "transcript_audio_mode": str(transcript_audio_mode or ""),
        "model_name": model_name,
        "model_family": profile["model_family"],
        "runtime_path": profile["runtime_key"],
        "runtime_path_label": profile["runtime_path_label"],
        "task_name": task_name,
        "estimated_runtime_seconds": int(math.ceil(estimate_seconds)),
        "fallback_estimate_seconds": int(math.ceil(fallback_estimate_seconds)),
        "adaptive_timeout_seconds": adaptive_timeout_seconds,
        "resolved_timeout_seconds": resolved_timeout_seconds,
        "stall_timeout_seconds": int(stall_timeout_seconds),
        "budget_margin_seconds": int(math.ceil(resolved_timeout_seconds - estimate_seconds)),
        "heartbeat_seconds": heartbeat,
        "estimate_source": estimate_source,
        "timeout_source": "explicit_override" if explicit_timeout > 0 else "adaptive_runtime_budget",
        "fallback_rtf": round(fallback_rtf, 3),
        "startup_seconds": int(round(startup_seconds)),
        "calibration_used": calibration_used,
        "calibration_status": calibration_status,
        "calibration_clip_seconds": int(round(calibration_clip_seconds)),
        "calibration_elapsed_seconds": int(math.ceil(calibration_elapsed_seconds)),
        "observed_rtf": round(observed_rtf, 3),
        "calibration_recommended": bool(calibration_recommendation["recommended"]),
        "calibration_sample_seconds": int(calibration_recommendation["sample_seconds"]),
        "calibration_recommendation_reason": str(calibration_recommendation["reason"]),
        "long_run_prompt_recommended": bool(duration > 0 and estimate_seconds >= _LONG_RUN_PROMPT_SECONDS),
        "warnings": warnings,
    }
