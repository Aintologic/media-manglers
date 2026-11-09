"""Tracked local Whisper helpers for the phased migration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from media_manglers.core.sparse_narration import (
    SHORT_REACTION_REASON,
    add_short_reactions,
    chunk_repetition_metrics,
    chunk_repetition_requires_retry,
    detect_speech_intervals,
    drop_phrase_loops,
    filter_sparse_decoder_segments,
    is_phrase_loop,
    is_silence_hallucination_text,
    offset_segments,
    repetition_is_blocking,
    repetition_metrics,
    rms_dbfs,
    select_short_reactions,
    silence_hallucination_metrics,
    span_peak_dbfs,
    words_per_minute,
    write_pcm_chunk,
)
from media_manglers.core.transcripts import write_transcript_files
from media_manglers.core.whisper_runtime import build_runtime_plan


def _log(message: str) -> None:
    print(message, flush=True)


def _configure_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _write_progress(
    progress_file: str,
    *,
    stage: str,
    message: str,
    started_at: float,
    extra: dict[str, Any] | None = None,
) -> None:
    if not progress_file:
        return

    payload: dict[str, Any] = {
        "stage": stage,
        "message": message,
        "elapsed_seconds": round(max(0.0, time.time() - started_at), 1),
        "updated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if extra:
        payload.update(extra)

    temp_path = progress_file + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(temp_path, progress_file)
    except Exception:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass


def _collect_cuda_device_names(torch_module: Any, device_count: int) -> list[str]:
    device_names: list[str] = []
    device_name_getter = getattr(getattr(torch_module, "cuda", None), "get_device_name", None)
    if not callable(device_name_getter):
        return device_names

    for index in range(max(0, device_count)):
        try:
            device_name = str(device_name_getter(index) or "").strip()
        except Exception:
            continue
        if device_name:
            device_names.append(device_name)

    return device_names


def _classify_probe_environment(result: dict[str, Any]) -> None:
    whisper_import_ok = bool(result.get("whisper_import_ok"))
    torch_import_ok = bool(result.get("torch_import_ok"))
    cuda_available = bool(result.get("cuda_available"))
    cuda_device_count = int(result.get("cuda_device_count") or 0)
    cuda_device_names = [
        str(name).strip()
        for name in (result.get("cuda_device_names") or [])
        if str(name).strip()
    ]

    classification_code = "misconfigured_or_uncertain"
    classification_label = "Local Whisper runtime misconfigured or uncertain"
    classification_summary = (
        "The selected Python runtime is not ready for a trustworthy Local Whisper run yet."
    )
    classification_action = (
        "Fix the selected Python runtime before starting a long Local Whisper run."
    )
    can_run_local_whisper = False

    if whisper_import_ok and torch_import_ok and cuda_available:
        if cuda_device_count > 0 or cuda_device_names:
            classification_code = "gpu_capable_for_whisper"
            classification_label = "GPU-capable for Local Whisper"
            classification_summary = (
                "This machine can run Local Whisper on CUDA in the selected Python runtime."
            )
            classification_action = (
                "You can use this box for real CUDA Local Whisper runs."
            )
            can_run_local_whisper = True
        else:
            classification_summary = (
                "PyTorch reported CUDA available, but no CUDA devices were reported by "
                "the selected Python runtime."
            )
            classification_action = (
                "Treat this machine as uncertain and repair the Python/CUDA runtime "
                "before a long Local Whisper run."
            )
    elif whisper_import_ok and torch_import_ok:
        classification_code = "cpu_only_for_whisper"
        classification_label = "CPU-only for Local Whisper"
        classification_summary = (
            "This machine can run Local Whisper on CPU, but CUDA is not available in "
            "the selected Python runtime."
        )
        classification_action = (
            "CPU-only validation is fine here. Use a separate GPU-capable box for real "
            "CUDA sign-off."
        )
        can_run_local_whisper = True
    elif whisper_import_ok and not torch_import_ok:
        classification_summary = (
            "Whisper imported, but PyTorch did not import cleanly in the selected "
            "Python runtime."
        )
        classification_action = (
            "Repair the PyTorch install or pick a different Python interpreter before "
            "starting Local Whisper."
        )
    elif torch_import_ok and not whisper_import_ok:
        classification_summary = (
            "PyTorch imported, but whisper did not import cleanly in the selected "
            "Python runtime."
        )
        classification_action = (
            "Install or repair openai-whisper before starting Local Whisper."
        )
    else:
        classification_summary = (
            "The selected Python runtime could not import whisper or PyTorch cleanly."
        )
        classification_action = (
            "Repair the Local Whisper Python runtime before starting a long run."
        )

    result["classification_code"] = classification_code
    result["classification_label"] = classification_label
    result["classification_summary"] = classification_summary
    result["classification_action"] = classification_action
    result["can_run_local_whisper"] = can_run_local_whisper


def probe_environment(*, emit_logs: bool = True) -> dict[str, Any]:
    _configure_stdio()
    result: dict[str, Any] = {
        "python_path": sys.executable,
        "python_version": sys.version.split()[0],
        "whisper_import_ok": False,
        "torch_import_ok": False,
        "cuda_available": False,
        "device": "cpu",
        "selected_device": "cpu",
        "selected_device_name": "",
        "cuda_device_count": 0,
        "cuda_device_names": [],
        "torch_version": "",
        "cuda_version": "",
        "error": "",
    }

    try:
        if emit_logs:
            _log("[PY-PROBE] Importing whisper...")
        __import__("whisper")
        result["whisper_import_ok"] = True
    except Exception as exc:
        result["error"] = f"whisper import failed: {exc}"

    try:
        if emit_logs:
            _log("[PY-PROBE] Importing torch...")
        import torch

        result["torch_import_ok"] = True
        result["torch_version"] = str(getattr(torch, "__version__", "") or "")
        result["cuda_version"] = str(getattr(torch.version, "cuda", "") or "")
        result["cuda_available"] = bool(torch.cuda.is_available())
        result["selected_device"] = "cuda" if result["cuda_available"] else "cpu"
        result["device"] = result["selected_device"]
        device_count_getter = getattr(getattr(torch, "cuda", None), "device_count", None)
        if callable(device_count_getter):
            try:
                result["cuda_device_count"] = max(0, int(device_count_getter()))
            except Exception:
                result["cuda_device_count"] = 0
        if result["cuda_available"] and result["cuda_device_count"] > 0:
            result["cuda_device_names"] = _collect_cuda_device_names(
                torch,
                result["cuda_device_count"],
            )
            if result["cuda_device_names"]:
                result["selected_device_name"] = result["cuda_device_names"][0]
    except Exception as exc:
        if result["error"]:
            result["error"] += f" | torch import failed: {exc}"
        else:
            result["error"] = f"torch import failed: {exc}"

    _classify_probe_environment(result)
    return result


def _run_transcription(
    audio_path: str,
    model_name: str,
    language_code: str,
    task_name: str,
    prefer_gpu: bool,
    initial_prompt: str = "",
    narration_speech_mode: str = "Auto",
    audit_dir: str = "",
    progress_callback: Callable[[str, str, str, dict[str, Any] | None], None] | None = None,
    keep_short_reactions: bool = False,
    report_work_units: bool = False,
) -> tuple[dict[str, Any], str, bool, str]:
    import whisper

    torch = None
    gpu_error = ""
    requested_device = "cuda" if prefer_gpu else "cpu"
    if prefer_gpu:
        try:
            import torch as imported_torch

            torch = imported_torch
        except Exception as exc:
            _log(f"[PY] Torch import failed. GPU path disabled. {exc}")

    def run(device_name: str, *, allow_fp16: bool = True) -> tuple[dict[str, Any], bool]:
        fp16 = device_name == "cuda" and allow_fp16
        if progress_callback:
            progress_callback(
                "loading_model",
                f"Loading Whisper model '{model_name}' on {device_name}",
                device_name,
                {"requested_device": requested_device},
            )
        _log(f"[PY] Loading model '{model_name}' on device '{device_name}'...")
        model = load_whisper_model(model_name, device_name)
        transcribing_message = f"Running Whisper {task_name} on {device_name}"

        def report_chunks(done: int, total: int) -> None:
            # 226: with progress_work_units, how many stretches of speech are decoded so far.
            if report_work_units and progress_callback:
                progress_callback("transcribing", transcribing_message, device_name,
                                  {"requested_device": requested_device, "work_units": (done, total)})

        if progress_callback:
            progress_callback(
                "transcribing",
                transcribing_message,
                device_name,
                # 226: no count yet (a run after a fall-back to the CPU starts again).
                {"requested_device": requested_device, **({"work_units": None} if report_work_units else {})},
            )
        _log(f"[PY] Starting {task_name} on {device_name}...")
        transcribe_kwargs: dict[str, Any] = {
            "language": language_code or None,
            "task": task_name,
            "verbose": False,
            "fp16": fp16,
        }
        if str(initial_prompt or "").strip():
            transcribe_kwargs["initial_prompt"] = str(initial_prompt).strip()
        speech_mode = str(narration_speech_mode or "Auto").strip().lower()
        if speech_mode == "sparse":
            intervals, vad_audit = detect_speech_intervals(audio_path)
            chunk_root = Path(audit_dir or Path(audio_path).parent) / ".sparse-chunks"
            accepted_segments: list[dict[str, Any]] = []
            raw_attempts: list[dict[str, Any]] = []
            rejected_chunks: list[dict[str, Any]] = []
            filtered_segments: list[dict[str, Any]] = []
            rescued_segments: list[dict[str, Any]] = []
            # 226: the attempt used for each chunk, for the short-reaction rule.
            used_attempts: list[dict[str, Any]] = []
            detected_language = language_code or ""
            report_chunks(0, len(intervals))
            for index, interval in enumerate(intervals, start=1):
                chunk_path = write_pcm_chunk(
                    audio_path,
                    chunk_root / f"chunk-{index:04d}.wav",
                    interval,
                )
                sparse_kwargs = {
                    **transcribe_kwargs,
                    "condition_on_previous_text": False,
                    "no_speech_threshold": 0.6,
                    "logprob_threshold": -1.0,
                    "compression_ratio_threshold": 2.4,
                    "temperature": (0.0, 0.2, 0.4),
                }
                seed_whisper_decoder()
                first = model.transcribe(str(chunk_path), **sparse_kwargs)
                detected_language = str(first.get("language") or detected_language)
                raw_first_segments = offset_segments(first.get("segments") or [], interval.start_seconds)
                first_segments, first_filtered = filter_sparse_decoder_segments(
                    raw_first_segments, context_segments=accepted_segments,
                    prompt_text=sparse_kwargs.get("initial_prompt", ""),
                )
                filtered_segments.extend(
                    {"chunk_index": index, "attempt": 1, **item} for item in first_filtered
                )
                first_metrics = chunk_repetition_metrics(accepted_segments, first_segments)
                raw_attempts.append(
                    {
                        "chunk_index": index,
                        "attempt": 1,
                        "interval": interval.to_dict(),
                        "metrics": first_metrics,
                        "segments": raw_first_segments,
                        "filtered_segments": first_filtered,
                    }
                )
                used_attempt: dict[str, Any] | None = raw_attempts[-1]
                selected = first_segments
                selected_attempt = 1
                if chunk_repetition_requires_retry(first_metrics):
                    # 201: the retry keeps the operator's words to spell right. Only when
                    # Whisper loops with them as well does a last attempt leave them out,
                    # in case the words themselves are what it keeps repeating.
                    retry_plans = [{"temperature": 0.0}]
                    if "initial_prompt" in sparse_kwargs:
                        retry_plans.append({"temperature": 0.0, "initial_prompt": None})
                    for attempt_number, changes in enumerate(retry_plans, start=2):
                        retry_kwargs = {**sparse_kwargs, **changes}
                        if retry_kwargs.get("initial_prompt") is None:
                            retry_kwargs.pop("initial_prompt", None)
                        seed_whisper_decoder()
                        retry = model.transcribe(str(chunk_path), **retry_kwargs)
                        raw_retry_segments = offset_segments(retry.get("segments") or [], interval.start_seconds)
                        retry_segments, retry_filtered = filter_sparse_decoder_segments(
                            raw_retry_segments, context_segments=accepted_segments,
                            prompt_text=sparse_kwargs.get("initial_prompt", ""),
                        )
                        filtered_segments.extend(
                            {"chunk_index": index, "attempt": attempt_number, **item} for item in retry_filtered
                        )
                        retry_metrics = chunk_repetition_metrics(accepted_segments, retry_segments)
                        raw_attempts.append(
                            {
                                "chunk_index": index,
                                "attempt": attempt_number,
                                "interval": interval.to_dict(),
                                "metrics": retry_metrics,
                                "segments": raw_retry_segments,
                                "filtered_segments": retry_filtered,
                            }
                        )
                        if not chunk_repetition_requires_retry(retry_metrics):
                            break
                    if chunk_repetition_requires_retry(retry_metrics):
                        rejected_chunks.append(
                            {
                                "chunk_index": index,
                                "reason": "repetition_persisted_after_retry",
                                "interval": interval.to_dict(),
                                "first_metrics": first_metrics,
                                "retry_metrics": retry_metrics,
                            }
                        )
                        selected = []
                        used_attempt = None
                    else:
                        selected = retry_segments
                        selected_attempt = attempt_number
                        used_attempt = raw_attempts[-1]
                accepted_segments.extend(selected)
                if used_attempt is not None:
                    used_attempts.append(used_attempt)
                # 133: a segment kept only because it sat next to real narration
                # is written to the audit. Without this the rescue happens in
                # memory and nobody can check it from the package. Only the attempt
                # that was actually used is listed, and the entries hold the same
                # dictionaries as the transcript, so they get the final ids below.
                rescued_segments.extend(
                    {
                        "chunk_index": index,
                        "attempt": selected_attempt,
                        "reason": "low_information_kept_near_narration",
                        "segment": segment,
                    }
                    for segment in selected
                    if segment.get("low_information_kept_near_narration")
                )
                report_chunks(index, len(intervals))
            # 226: the short reactions the request asks to keep, chosen before the cross-chunk loop
            # check from the attempts that were used, and added after it (add_short_reactions).
            prompt_text = str(transcribe_kwargs.get("initial_prompt") or "")
            short_reactions: list[dict[str, Any]] = []
            if keep_short_reactions:
                short_reactions = select_short_reactions(
                    used_attempts, accepted_segments,
                    lambda start, end: span_peak_dbfs(audio_path, start, end),
                    rms_dbfs(vad_audit.get("noise_floor")),
                    prompt_text=prompt_text,
                )
            # 199: a loop split over neighbouring lines, even across chunks.
            rejected_indexes = {int(item["chunk_index"]) for item in rejected_chunks}
            thrown_out = [
                segment
                for attempt in raw_attempts
                if int(attempt["chunk_index"]) in rejected_indexes and int(attempt["attempt"]) >= 2
                for segment in attempt.get("segments") or []
            ]
            accepted_segments, loop_filtered = drop_phrase_loops(accepted_segments, context_segments=thrown_out)
            filtered_segments.extend(loop_filtered)
            reactions_kept: list[dict[str, Any]] = []
            if keep_short_reactions:
                accepted_segments, reactions_left_out, reactions_kept = add_short_reactions(
                    accepted_segments, short_reactions, context_segments=thrown_out, prompt_text=prompt_text,
                )
                # A kept reaction is in the transcript, so it leaves the list of dropped lines. A reaction
                # considered and left out is listed once, with why it was left out (reactions_left_out),
                # not also as the sampled guess it was dropped as first. The attempt's own record
                # (raw_attempts) still shows what the filter did.
                back = {(item["chunk_index"], item["attempt"], item["segment"].get("start"), item["segment"].get("end"))
                        for item in [*reactions_kept, *reactions_left_out]}
                filtered_segments = [
                    item for item in filtered_segments
                    if not (item.get("reason") == SHORT_REACTION_REASON
                            and (item.get("chunk_index"), item.get("attempt"), (item.get("segment") or {}).get("start"),
                                 (item.get("segment") or {}).get("end")) in back)
                ]
                filtered_segments.extend(reactions_left_out)
            for segment_id, segment in enumerate(accepted_segments):
                segment["id"] = segment_id
            working_metrics = repetition_metrics(accepted_segments)
            result = {
                "language": language_code or detected_language,
                "segments": accepted_segments,
                "text": " ".join(str(item.get("text") or "").strip() for item in accepted_segments).strip(),
                "sparse_narration": {
                    "schema_version": 1,
                    "mode": "Sparse",
                    "vad": vad_audit,
                    "raw_attempts": raw_attempts,
                    "filtered_segments": filtered_segments,
                    "rescued_segments": rescued_segments,
                    **({"short_reactions_kept": [
                        {"chunk_index": item["chunk_index"], "attempt": item["attempt"], "segment": item["segment"],
                         "line_dbfs": item["line_dbfs"], "anchor_start": item["anchor_start"]}
                        for item in reactions_kept
                    ]} if keep_short_reactions else {}),
                    "rejected_chunks": rejected_chunks,
                    "working_repetition": working_metrics,
                    "quality_blocking": bool(rejected_chunks) or repetition_is_blocking(working_metrics),
                    "recording_wpm": words_per_minute(accepted_segments, float(vad_audit.get("duration_seconds") or 0.0)),
                    "active_speech_wpm": words_per_minute(accepted_segments, float(vad_audit.get("active_speech_seconds") or 0.0)),
                },
            }
            try:
                for item in chunk_root.glob("*.wav"):
                    item.unlink()
                chunk_root.rmdir()
            except OSError:
                pass
        else:
            seed_whisper_decoder()
            result = model.transcribe(audio_path, **transcribe_kwargs)
            # 199: lines Whisper invents (stock phrases, phrase loops) are dropped here too, by
            # their words only. Decoder numbers alone never drop a line in this mode, so quiet
            # narration that scores like noise is kept.
            continuous_filtered: list[dict[str, Any]] = []
            kept_segments: list[dict[str, Any]] = []
            for segment in result.get("segments") or []:
                text = segment.get("text") if isinstance(segment, dict) else ""
                if is_phrase_loop(text):
                    continuous_filtered.append({"reason": "phrase_loop", "segment": dict(segment)})
                elif is_silence_hallucination_text(text):
                    continuous_filtered.append({"reason": "known_filler_phrase", "segment": dict(segment)})
                else:
                    kept_segments.append(segment)
            kept_segments, loop_filtered = drop_phrase_loops(kept_segments)
            continuous_filtered.extend(loop_filtered)
            if continuous_filtered:
                for segment_id, segment in enumerate(kept_segments):
                    segment["id"] = segment_id
                result["segments"] = kept_segments
                result["text"] = " ".join(str(item.get("text") or "").strip() for item in kept_segments).strip()
            metrics = repetition_metrics(result.get("segments") or [])
            result["sparse_narration"] = {
                "schema_version": 1,
                "mode": "Continuous" if speech_mode == "continuous" else "Auto",
                "vad": {},
                "raw_attempts": [],
                "filtered_segments": continuous_filtered,
                "rejected_chunks": [],
                "working_repetition": metrics,
                "quality_blocking": repetition_is_blocking(metrics),
            }
        return result, fp16

    if prefer_gpu and torch is not None and torch.cuda.is_available():
        try:
            try:
                result, fp16 = run("cuda")
            except Exception as half_exc:
                # Half precision can produce NaN logits on long, quiet audio
                # ("Expected parameter logits ... Categorical"). Retry on the
                # GPU in full precision before giving up on the GPU (94).
                if "logits" not in str(half_exc) and "nan" not in str(half_exc).lower():
                    raise
                _log(f"[PY] GPU half precision failed; retrying on GPU in full precision. {half_exc}")
                result, fp16 = run("cuda", allow_fp16=False)
            return result, "cuda", fp16, gpu_error
        except Exception as exc:
            gpu_error = str(exc)
            _log(f"[PY] GPU transcription failed. Retrying on CPU. {exc}")
            if progress_callback:
                progress_callback(
                    "fallback_to_cpu",
                    f"GPU failed. Retrying on CPU. {gpu_error}",
                    "cpu",
                    {
                        "requested_device": requested_device,
                        "device_event": "gpu_to_cpu_fallback",
                        "device_switch_count": 1,
                        "gpu_error": gpu_error,
                        "selected_device": "cpu",
                    },
                )

    result, fp16 = run("cpu")
    return result, "cpu", fp16, gpu_error


def pick_whisper_device(prefer_gpu: bool) -> str:
    """cuda when asked for and available, otherwise cpu."""

    if not prefer_gpu:
        return "cpu"
    try:
        import torch  # type: ignore[import-not-found]

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


WHISPER_DECODER_SEED = 0


def seed_whisper_decoder(seed: int = WHISPER_DECODER_SEED) -> None:
    """214: the same recording gives the same transcript every run.

    When the plain decode of a stretch fails Whisper's checks, it samples at random (temperature
    0.2, then 0.4), and nothing seeded that: each run wrote different text there. Seeded before
    every decode, a run is repeatable; which sampled lines are kept is decided by the filters.
    """

    import random

    random.seed(seed)
    try:
        import numpy  # type: ignore[import-not-found]

        numpy.random.seed(seed)
    except Exception:
        pass
    try:
        import torch  # type: ignore[import-not-found]

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    except Exception:
        pass


def load_whisper_model(model_name: str, device: str) -> Any:
    """214: the one place a Whisper model is loaded, for transcription and for voice probes alike."""

    import whisper  # type: ignore[import-not-found]

    return whisper.load_model(model_name, device=device)


def _apply_glossary_corrections(result: dict[str, Any], glossary_entries: Any) -> list[dict[str, Any]]:
    """Corrects the delivered segments in place; returns what Whisper wrote for each change."""

    if not glossary_entries:
        return []
    from media_manglers.core.transcript_corrections import correct_text, load_transcription_glossary

    values = [glossary_entries] if isinstance(glossary_entries, str) else list(glossary_entries)
    entries = load_transcription_glossary({"transcription_glossary_entries": values})["entries"]
    corrections: list[dict[str, Any]] = []
    for segment in result.get("segments") or []:
        before = str(segment.get("text") or "")
        after, changes = correct_text(before, entries)
        if not changes:
            continue
        # Keep Whisper's leading space, which the transcript writers rely on.
        segment["text"] = (" " if before.startswith(" ") else "") + after
        corrections.append({"segment_id": segment.get("id"), "start": segment.get("start"),
                            "before": before, "after": segment["text"], "changes": changes})
    if corrections:
        result["text"] = "".join(str(item.get("text") or "") for item in result.get("segments") or []).strip()
    return corrections


def transcribe_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    _configure_stdio()
    audio_path = str(payload.get("audio_path") or "")
    output_dir = str(payload.get("output_dir") or "")
    model_name = str(payload.get("model_name") or "")
    language_code = str(payload.get("language_code") or "")
    ffmpeg_dir = str(payload.get("ffmpeg_dir") or "")
    prefer_gpu = bool(payload.get("prefer_gpu", False))
    task_name = str(payload.get("task_name") or "transcribe")
    initial_prompt = str(payload.get("initial_prompt") or "")
    narration_speech_mode = str(payload.get("narration_speech_mode") or "Auto")
    # 226: both off unless the request asks; without them every file is written exactly as before.
    keep_short_reactions = bool(payload.get("keep_short_reactions", False))
    progress_work_units = bool(payload.get("progress_work_units", False))
    json_name = str(payload.get("json_name") or "transcript.json")
    srt_name = str(payload.get("srt_name") or "transcript.srt")
    text_name = str(payload.get("text_name") or "transcript.txt")
    progress_file = str(payload.get("progress_file") or "")
    heartbeat_interval_seconds = max(10, int(payload.get("heartbeat_interval_seconds") or 15))

    if not audio_path:
        raise ValueError("audio_path is required.")
    if not model_name:
        raise ValueError("model_name is required.")

    if ffmpeg_dir:
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

    heartbeat_stop = threading.Event()
    started_at = time.time()
    requested_device = "cuda" if prefer_gpu else "cpu"
    progress_state: dict[str, Any] = {
        "stage": "starting",
        "message": "Preparing Whisper helper",
        "device": "pending",
        "selected_device": "pending",
        "requested_device": requested_device,
        "device_event": "starting",
        "device_switch_count": 0,
        "gpu_error": "",
    }

    def set_progress(
        stage: str,
        message: str,
        device: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        progress_state["stage"] = stage
        progress_state["message"] = message
        if device:
            progress_state["device"] = device
            progress_state["selected_device"] = device
        if extra:
            progress_state.update(extra)
        written = {
            "device": progress_state["device"],
            "selected_device": progress_state["selected_device"],
            "requested_device": progress_state["requested_device"],
            "device_event": progress_state["device_event"],
            "device_switch_count": progress_state["device_switch_count"],
            "gpu_error": progress_state["gpu_error"],
            "model_name": model_name,
            "task_name": task_name,
            "audio_path": audio_path,
        }
        # 226: while decoding, the stretches of speech done of all of them, as work units.
        units = progress_state.get("work_units") if progress_work_units else None
        if units and progress_state["stage"] == "transcribing":
            written.update({"progress_kind": "work_units", "completed": int(units[0]), "total": int(units[1])})
        _write_progress(
            progress_file,
            stage=progress_state["stage"],
            message=progress_state["message"],
            started_at=started_at,
            extra=written,
        )

    def heartbeat() -> None:
        while not heartbeat_stop.wait(heartbeat_interval_seconds):
            elapsed = time.time() - started_at
            _log(
                f"[PY] heartbeat: transcription process alive, "
                f"elapsed={elapsed:.0f}s, stage={progress_state['stage']}"
            )
            set_progress(progress_state["stage"], progress_state["message"], progress_state["device"])

    heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()

    try:
        set_progress("starting", "Preparing Whisper transcription helper")
        _log(f"[PY] Audio input: {audio_path}")
        _log(f"[PY] Output dir: {output_dir}")
        runtime_probe = probe_environment(emit_logs=False)
        _log(f"[PY] Python executable: {runtime_probe['python_path']}")
        _log(f"[PY] Python version: {runtime_probe['python_version']}")
        _log(f"[PY] Torch version: {runtime_probe['torch_version'] or 'unavailable'}")
        _log(f"[PY] Torch CUDA version: {runtime_probe['cuda_version'] or 'unavailable'}")
        _log(f"[PY] CUDA available: {runtime_probe['cuda_available']}")
        _log(f"[PY] CUDA device count: {runtime_probe['cuda_device_count']}")
        if runtime_probe["cuda_device_names"]:
            _log(f"[PY] CUDA devices: {', '.join(runtime_probe['cuda_device_names'])}")
        _log(f"[PY] Requested device: {requested_device}")
        _log(f"[PY] Selected device before run: {runtime_probe['selected_device']}")
        _log(f"[PY] Whisper runtime health: {runtime_probe['classification_label']}")
        _log(f"[PY] Whisper runtime summary: {runtime_probe['classification_summary']}")
        if runtime_probe["error"]:
            _log(f"[PY] Runtime probe notes: {runtime_probe['error']}")
        set_progress("importing_whisper", "Importing Whisper runtime")
        result, device, fp16, gpu_error = _run_transcription(
            audio_path=audio_path,
            model_name=model_name,
            language_code=language_code,
            task_name=task_name,
            prefer_gpu=prefer_gpu,
            initial_prompt=initial_prompt,
            narration_speech_mode=narration_speech_mode,
            audit_dir=output_dir,
            progress_callback=set_progress,
            keep_short_reactions=keep_short_reactions,
            report_work_units=progress_work_units,
        )
        if gpu_error:
            progress_state["gpu_error"] = gpu_error
        set_progress("writing_outputs", "Writing transcript files", device)
        _log("[PY] Writing transcript files...")
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        sparse_audit = dict(result.get("sparse_narration") or {})
        # Text Whisper invents on silence ("Thank you for watching!" x8) must
        # never be delivered as a usable transcript (94).
        silence_audit = silence_hallucination_metrics(result.get("segments") or [])
        if silence_audit["silence_hallucination_segment_count"] >= 3 and silence_audit["no_narration_found"]:
            sparse_audit["quality_blocking"] = True
            _log(
                "[PY] Transcript looks like text invented on silence "
                f"({silence_audit['silence_hallucination_segment_count']} filler segments); "
                "it is marked quality-blocking."
            )
        # 206: the operator's words to spell right, for callers that write the transcript as it
        # is delivered (Full Review, Transcript Only, Review Media Inbox). Find my bug reports
        # corrects later, in its package, and does not ask for this.
        glossary_corrections = _apply_glossary_corrections(result, payload.get("glossary_entries"))
        raw_json_path = output_path / f"{Path(json_name).stem}.raw.json"
        vad_json_path = output_path / f"{Path(json_name).stem}.vad.json"
        quality_json_path = output_path / f"{Path(json_name).stem}.quality.json"
        raw_json_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "language": result.get("language", ""),
                    "mode": sparse_audit.get("mode", narration_speech_mode),
                    "raw_attempts": sparse_audit.get("raw_attempts", []),
                    "filtered_segments": sparse_audit.get("filtered_segments", []),
                    "rescued_segments": sparse_audit.get("rescued_segments", []),
                    # 226: the short reactions kept, only when the request asked for them.
                    **({"short_reactions_kept": sparse_audit.get("short_reactions_kept", [])}
                       if keep_short_reactions else {}),
                    "rejected_chunks": sparse_audit.get("rejected_chunks", []),
                    "glossary_corrections": glossary_corrections,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        vad_json_path.write_text(
            json.dumps(sparse_audit.get("vad", {}), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        quality_json_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "mode": sparse_audit.get("mode", narration_speech_mode),
                    "quality_blocking": bool(sparse_audit.get("quality_blocking", False)),
                    **silence_audit,
                    "working_repetition": sparse_audit.get("working_repetition", {}),
                    "recording_wpm": sparse_audit.get("recording_wpm", 0.0),
                    "active_speech_wpm": sparse_audit.get("active_speech_wpm", 0.0),
                    "rejected_chunk_count": len(sparse_audit.get("rejected_chunks", [])),
                    "filtered_segment_count": len(sparse_audit.get("filtered_segments", [])),
                    "rescued_segment_count": len(sparse_audit.get("rescued_segments", [])),
                    **({"short_reactions_kept_count": len(sparse_audit.get("short_reactions_kept", []))}
                       if keep_short_reactions else {}),
                    "glossary_correction_count": len(glossary_corrections),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        json_path, srt_path, text_path = write_transcript_files(
            output_dir=output_dir,
            json_name=json_name,
            srt_name=srt_name,
            text_name=text_name,
            result=result,
        )
        _log("[PY] Transcript files written successfully.")
        set_progress("complete", "Transcript files written successfully", device)
        return {
            "device": device,
            "fp16": fp16,
            "json_path": str(json_path),
            "srt_path": str(srt_path),
            "text_path": str(text_path),
            "language": str(result.get("language", "") or ""),
            "segments_count": len(result.get("segments") or []),
            "raw_json_path": str(raw_json_path),
            "vad_json_path": str(vad_json_path),
            "quality_json_path": str(quality_json_path),
            "quality_blocking": bool(sparse_audit.get("quality_blocking", False)),
            "silence_hallucination_suspected": bool(
                silence_audit["silence_hallucination_segment_count"] >= 3 and silence_audit["no_narration_found"]
            ),
            "no_narration_found": bool(silence_audit["no_narration_found"]),
            "narration_word_count": int(silence_audit["narration_word_count"]),
            "recording_wpm": float(sparse_audit.get("recording_wpm") or 0.0),
            "active_speech_wpm": float(sparse_audit.get("active_speech_wpm") or 0.0),
            "gpu_error": gpu_error,
            "requested_device": requested_device,
            "selected_device": progress_state["selected_device"],
            "device_switch_count": int(progress_state["device_switch_count"] or 0),
            "python_path": runtime_probe["python_path"],
            "python_version": runtime_probe["python_version"],
            "torch_version": runtime_probe["torch_version"],
            "cuda_version": runtime_probe["cuda_version"],
            "cuda_available": runtime_probe["cuda_available"],
            "cuda_device_count": int(runtime_probe["cuda_device_count"] or 0),
            "cuda_device_names": list(runtime_probe["cuda_device_names"] or []),
            "classification_code": runtime_probe["classification_code"],
            "classification_label": runtime_probe["classification_label"],
            **({"short_reactions_kept_count": len(sparse_audit.get("short_reactions_kept", []))}
               if keep_short_reactions else {}),
        }
    finally:
        heartbeat_stop.set()


def build_runtime_plan_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    calibration_payload = payload.get("calibration")
    calibration = calibration_payload if isinstance(calibration_payload, dict) else None

    return build_runtime_plan(
        source_duration_seconds=payload.get("source_duration_seconds", 0),
        effective_duration_seconds=payload.get("effective_duration_seconds", 0),
        audio_track_count=int(payload.get("audio_track_count") or 0),
        transcript_audio_mode=str(payload.get("transcript_audio_mode") or ""),
        model_name=str(payload.get("model_name") or ""),
        gpu_capable=bool(payload.get("gpu_capable", False)),
        heartbeat_seconds=int(payload.get("heartbeat_seconds") or 10),
        explicit_timeout_seconds=int(payload.get("explicit_timeout_seconds") or 0),
        task_name=str(payload.get("task_name") or "transcribe"),
        calibration=calibration,
    )
