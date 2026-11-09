"""Bounded, resumable preparation backend for Review Media Inbox.

This module prepares only local evidence.  It does not perform semantic review,
contact GitHub, create review-result contracts, or alter original media.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import time
from typing import Any, Callable
import uuid

from media_manglers.core import cross_track_check, frame_render, inbox_records, panel_layout, review_findings, review_inbox, review_ledger, safe_write, speech_facts, streaming_progress, voice_track, whisper_options
from media_manglers.providers import whisper_local
from media_manglers_workbench.audio_detection import (
    AUDIBILITY_CONTRACT_VERSION,
    AudioStreamInfo,
    SourceAudioInspection,
    inspect_source,
    layout_fingerprint,
)


CONTRACT_VERSION = 1
# Part of every package's preparation signature (224, design 3.2): always 2, whatever holds the records.
PREPARATION_SIGNATURE_LEDGER_VERSION = 2
TEN_GIB = 10 * 1024**3
SHOWINFO_TIMESTAMP = frame_render.SHOWINFO_TIMESTAMP
class SourceChangedError(RuntimeError):
    """Raised when an original changes across a bounded preparation operation."""


class SkippedByOperatorError(RuntimeError):
    """214: the operator skipped this recording from Queue / Progress."""


def _skip_requested(run_control_path: Path | None, source: Path) -> bool:
    """Whether the Workbench's run-control file asks to skip ``source`` (a full path or its name)."""

    if run_control_path is None:
        return False
    try:
        requested = json.loads(run_control_path.read_text(encoding="utf-8")).get("skip") or []
    except (OSError, ValueError, AttributeError):
        return False
    full = os.path.normcase(str(source))
    for item in requested:
        text = str(item or "").strip()
        if not text:
            continue
        if os.path.normcase(text) == full or (Path(text).name == text and os.path.normcase(text) == os.path.normcase(source.name)):
            return True
    return False


class AudioAudibilityInconclusiveError(RuntimeError):
    """Raised when decoded audio cannot be classified safely."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    # 224 (Wave B1): the one safe writer replaces the file, with this module's text as before. It keeps the
    # short sibling name a deep evidence folder needs, and retries only the brief refusal Windows gives while
    # PowerShell reads the progress document.
    safe_write.write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                          wait=safe_write.INBOX_WAIT_SECONDS)


def _is_within(root: Path, target: Path) -> bool:
    root_resolved = root.resolve()
    target_resolved = target.resolve()
    return target_resolved == root_resolved or root_resolved in target_resolved.parents


def _require_within(root: Path, target: Path, label: str) -> None:
    if not _is_within(root, target):
        raise ValueError(f"{label} must remain beneath its configured root.")


def _safe_remove(root: Path, target: Path, leftovers: Path | None = None) -> None:
    # 224 (Wave B2a): through the one antivirus-safe helper, which waits a bounded time for another program
    # holding the file and never for the app itself.
    _require_within(root, target, "Cleanup target")
    safe_write.remove_disposable_tree(target, within=root, leftovers=leftovers)


def _tidy(root: Path, target: Path, leftovers: Path | None, warnings: list[str]) -> str:
    """Clean-up after a step already succeeded (224, Decision 3): another program still holding the copy never
    undoes the result. It is said in plain words, and the next run removes the leftover. Returns the warning."""

    try:
        _safe_remove(root, target, leftovers)
    except (safe_write.FileInUse, safe_write.FileStepRefused) as exc:
        # 224 (Wave B2a review): whatever Windows refuses here, the step's result stands; the leftover is noted.
        warning = f"The result was kept. {exc} It is removed at the next run."
        warnings.append(warning)
        return warning
    return ""


def _prune_empty_parents(root: Path, start: Path) -> None:
    current = start
    while current != root and _is_within(root, current):
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _run(command: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"Command exited with {completed.returncode}.")
    return completed


def probe_media(
    ffprobe_exe: str,
    source: Path,
    *,
    on_report: Callable[[float, float], None] | None = None,
) -> dict[str, Any]:
    """What the recording holds, with the time of every picture in it (88).

    ``on_report`` hears how far the frame check has got, as (seconds checked, recording length), every
    couple of seconds on this thread; what it raises (a Skip) stops the check (224, Wave B2a)."""

    completed = _run(
        [
            ffprobe_exe,
            "-v", "error",
            "-show_entries",
            "format=format_name,duration,size,bit_rate:format_tags=encoder,writing_application,application,name:"
            "stream=index,codec_type,codec_name,width,height,pix_fmt,r_frame_rate,channels,channel_layout,sample_rate,bit_rate:"
            "stream_tags=language,title,handler_name",
            "-of", "json",
            str(source),
        ],
        timeout=60,
    )
    raw = json.loads(completed.stdout or "{}")
    streams_raw = [item for item in raw.get("streams", []) if isinstance(item, dict)]
    format_info = raw.get("format") if isinstance(raw.get("format"), dict) else {}
    format_tags = format_info.get("tags") if isinstance(format_info.get("tags"), dict) else {}
    recorder_profile = next(
        (str(format_tags.get(key) or "").strip() for key in ("writing_application", "application", "encoder", "name") if format_tags.get(key)),
        str(format_info.get("format_name") or "unknown"),
    )
    audio_streams: list[AudioStreamInfo] = []
    video_streams: list[dict[str, Any]] = []
    audio_ordinal = 0
    for raw_stream in streams_raw:
        kind = str(raw_stream.get("codec_type") or "")
        tags = raw_stream.get("tags") if isinstance(raw_stream.get("tags"), dict) else {}
        if kind == "audio":
            audio_streams.append(
                AudioStreamInfo(
                    ordinal=audio_ordinal,
                    stream_index=int(raw_stream.get("index") or 0),
                    title=str(tags.get("title") or tags.get("handler_name") or "").strip(),
                    language=str(tags.get("language") or "").strip(),
                    codec=str(raw_stream.get("codec_name") or "").strip(),
                    channels=int(raw_stream.get("channels") or 0),
                    channel_layout=str(raw_stream.get("channel_layout") or "").strip(),
                    sample_rate=int(raw_stream.get("sample_rate") or 0),
                    bit_rate=int(raw_stream.get("bit_rate") or 0),
                )
            )
            audio_ordinal += 1
        elif kind == "video":
            video_streams.append(
                {
                    "stream_index": int(raw_stream.get("index") or 0),
                    "codec": str(raw_stream.get("codec_name") or ""),
                    "width": int(raw_stream.get("width") or 0),
                    "height": int(raw_stream.get("height") or 0),
                    "pixel_format": str(raw_stream.get("pix_fmt") or ""),
                    "frame_rate": str(raw_stream.get("r_frame_rate") or ""),
                }
            )
    try:
        duration = max(0.0, float(format_info.get("duration") or 0.0))
    except (TypeError, ValueError):
        duration = 0.0
    video_frame_timestamps = (
        _probe_decodable_video_timestamps(
            ffprobe_exe,
            source,
            on_report=(lambda at: on_report(at, duration)) if on_report is not None else None,
        )
        if video_streams
        else []
    )
    return {
        "duration_seconds": duration,
        "container": str(format_info.get("format_name") or ""),
        "bit_rate": int(format_info.get("bit_rate") or 0),
        "recorder_profile": recorder_profile,
        "video_streams": video_streams,
        "video_frame_timestamps": video_frame_timestamps,
        "audio_streams": [asdict(stream) | {"ffmpeg_map": stream.ffmpeg_map} for stream in audio_streams],
        "audio_layout_fingerprint": layout_fingerprint(audio_streams, recorder_profile),
    }


class _PacketTimes(list):
    """Frame times read from the packets (224, Wave B2a): ``_render_visuals`` falls back to the full frame
    check once when a screenshot made from one fails. Written out exactly as a plain list."""

    from_packets = True


def _read_video_times(
    ffprobe_exe: str,
    source: Path,
    *,
    full: bool,
    on_report: Callable[[float], None] | None,
) -> list[float] | None:
    """The first video stream's times, read as FFprobe prints them, through the one streaming reader.

    Without ``full`` they are the stored packets' times, which no picture is unpacked for: None when a packet
    has no time or is marked damaged, or the first one is not a keyframe (the pictures before a recording's
    first keyframe cannot be unpacked), so the caller unpacks every frame instead. Packets the decoder is told
    to drop (FFprobe's "D" flag) never become a picture, so they are left out. With ``full`` every frame is
    unpacked (88), as before. Both stop only when nothing moves for 180 seconds (no longer a fixed 300 s
    limit a 1.3 GB recording could reach), with a plain reason. How far they have got is counted from the
    first time seen, as a recording's own clock may not start at zero."""

    entries = "frame=best_effort_timestamp_time" if full else "packet=pts_time,flags"
    command = [ffprobe_exe, "-v", "error", "-select_streams", "v:0", *(["-show_frames"] if full else []),
               "-show_entries", entries, "-of", "compact=p=0", "--", str(source)]
    values: list[float] = []
    usable = [True]

    def read_line(line: str) -> float | None:
        fields = dict(part.partition("=")[::2] for part in line.split("|") if "=" in part)
        raw = fields.get("best_effort_timestamp_time" if full else "pts_time")
        if raw is None:
            return None
        if not full:
            flags = fields.get("flags", "")
            if "C" in flags:
                usable[0] = False
            if "D" in flags:
                return None
            if not values and "K" not in flags:
                usable[0] = False
        try:
            value = float(raw)
        except ValueError:
            # "N/A": a frame the full check cannot time is skipped, as before; a packet without one sends the
            # recording to the full check.
            usable[0] = usable[0] and full
            return None
        values.append(value)
        return max(0.0, value - values[0])

    finished = streaming_progress.run(
        command,
        read_line=read_line,
        stall_message=lambda at: (
            f"Checking the video stopped making progress: nothing new for "
            f"{int(streaming_progress.STALL_SECONDS)} seconds, "
            f"{voice_track.clock(values[0] + at if values else at)} into the recording. "
            "The drive may have gone to sleep or been disconnected."
        ),
        stall_seconds=streaming_progress.STALL_SECONDS,
        on_report=on_report,
        report_seconds=streaming_progress.REPORT_SECONDS,
    )
    if finished.returncode != 0:
        raise RuntimeError(finished.errors or f"Command exited with {finished.returncode}.")
    if not finished.complete:
        raise RuntimeError("FFprobe's list of video frames could not be read to the end.")
    return values if usable[0] else None


def _unique_frame_times(raw: list[float]) -> list[float]:
    values: list[float] = []
    seen: set[int] = set()
    for timestamp in raw:
        if not math.isfinite(timestamp) or timestamp < 0:
            continue
        # FFprobe commonly reports six fractional digits.  Quantizing at one
        # microsecond removes container duplicates without collapsing distinct
        # frames merely because the old manifest rounded to milliseconds.
        key = int(round(timestamp * 1_000_000))
        if key in seen:
            continue
        seen.add(key)
        values.append(key / 1_000_000.0)
    return sorted(values)


def _probe_decodable_video_timestamps(
    ffprobe_exe: str,
    source: Path,
    *,
    full: bool = False,
    on_report: Callable[[float], None] | None = None,
) -> list[float]:
    """Return ordered, unique timestamps for frames FFprobe can decode.

    224 (Wave B2a): read from the packets the file already stores, which carry the same times without
    unpacking a picture; the screenshot step unpacks and checks each frame it uses. A recording whose packets
    cannot all be timed is checked frame by frame, as before (``full``)."""

    if not full:
        packets = _read_video_times(ffprobe_exe, source, full=False, on_report=on_report)
        if packets is not None:
            return _PacketTimes(_unique_frame_times(packets))
    return _unique_frame_times(_read_video_times(ffprobe_exe, source, full=True, on_report=on_report) or [])


def timeline_frame_count(duration_seconds: float) -> int:
    return min(24, max(6, int(math.ceil(max(0.0, duration_seconds) / 300.0))))


def timeline_timestamps(
    duration_seconds: float,
    decodable_timestamps: list[float] | None = None,
) -> list[float]:
    """Choose deterministic requested times from verified decodable frames.

    Callers that have not yet probed frames may omit ``decodable_timestamps``;
    that compatibility path returns a provisional mathematical plan.  Package
    rendering always supplies verified frame timestamps.
    """

    count = timeline_frame_count(duration_seconds)
    if decodable_timestamps is None:
        if duration_seconds <= 0:
            return []
        provisional = [
            ((index + 0.5) * duration_seconds) / count
            for index in range(count)
        ]
        result: list[float] = []
        seen: set[int] = set()
        for value in provisional:
            # Never round a legal pre-end request up to nominal duration.
            bounded = min(value, math.nextafter(duration_seconds, 0.0))
            key = int(math.floor(max(0.0, bounded) * 1_000_000))
            if key in seen:
                continue
            seen.add(key)
            result.append(key / 1_000_000.0)
        return result

    verified: list[float] = []
    seen: set[int] = set()
    for raw in decodable_timestamps:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or value < 0:
            continue
        if duration_seconds > 0 and value >= duration_seconds:
            continue
        key = int(round(value * 1_000_000))
        if key in seen:
            continue
        seen.add(key)
        verified.append(key / 1_000_000.0)
    verified.sort()
    if len(verified) <= count:
        return verified

    selected: list[float] = []
    selected_keys: set[int] = set()
    for index in range(count):
        frame_index = min(
            len(verified) - 1,
            int(math.floor(((index + 0.5) * len(verified)) / count)),
        )
        value = verified[frame_index]
        key = int(round(value * 1_000_000))
        if key not in selected_keys:
            selected_keys.add(key)
            selected.append(value)
    return selected


def estimate_storage(size_bytes: int, duration_seconds: float, frame_count: int, panel_count: int) -> dict[str, int]:
    audio_bytes = int(max(0.0, duration_seconds) * 32_000)
    transcript_bytes = max(1_048_576, int(max(0.0, duration_seconds) * 512))
    visual_bytes = frame_count * 2_000_000 * max(1, panel_count + 1)
    retained = transcript_bytes + visual_bytes + 4_194_304
    peak = int(size_bytes) + audio_bytes + retained
    reserve = max(TEN_GIB, int(math.ceil(peak * 0.10)))
    return {
        "source_copy_bytes": int(size_bytes),
        "planned_audio_bytes": audio_bytes,
        "planned_transcript_bytes": transcript_bytes,
        "planned_visual_bytes": visual_bytes,
        "estimated_peak_bytes": peak,
        "scratch_required_bytes": peak + reserve,
        "scratch_reserve_bytes": reserve,
        "retained_required_bytes": retained,
    }


def stream_verified_copy(source: Path, destination: Path, *, chunk_bytes: int = 4 * 1024 * 1024) -> dict[str, Any]:
    before = source.stat()
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    copied = 0
    with source.open("rb") as reader, destination.open("xb") as writer:
        while True:
            chunk = reader.read(chunk_bytes)
            if not chunk:
                break
            writer.write(chunk)
            digest.update(chunk)
            copied += len(chunk)
        writer.flush()
        os.fsync(writer.fileno())
    after = source.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise SourceChangedError("Source changed while its verified working copy was streamed.")
    if copied != before.st_size or destination.stat().st_size != before.st_size:
        raise SourceChangedError("Verified working-copy size does not match the source size.")
    return {
        "sha256": digest.hexdigest(),
        "bytes_copied": copied,
        "before": {"size_bytes": before.st_size, "modified_ns": before.st_mtime_ns},
        "after": {"size_bytes": after.st_size, "modified_ns": after.st_mtime_ns},
    }


def _injected_probe_audibility(media: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible test seam for an explicitly injected media probe."""

    streams = list(media.get("audio_streams") or [])
    return {
        "contract_version": AUDIBILITY_CONTRACT_VERSION,
        "source_state": "audible_candidates" if streams else "no_audio",
        "threshold_policy": {"test_dependency_injection": True},
        "full_source_check_completed": not streams,
        "streams": [
            {
                "operator_track_number": int(stream["ordinal"]) + 1,
                "audio_ordinal": int(stream["ordinal"]),
                "ffprobe_stream_index": int(stream["stream_index"]),
                "ffmpeg_map": str(stream["ffmpeg_map"]),
                "bounded_state": "audible_signal",
                "full_source_checked": False,
                "decode_succeeded": True,
                "final_state": "audible_signal",
                "preview_regions": [],
            }
            for stream in streams
        ],
    }


def _validate_audibility_mapping(
    media: dict[str, Any],
    audibility: dict[str, Any],
) -> None:
    media_mapping = [
        (
            int(stream["ordinal"]),
            int(stream["stream_index"]),
            str(stream["ffmpeg_map"]),
        )
        for stream in media.get("audio_streams") or []
    ]
    audibility_mapping = [
        (
            int(stream["audio_ordinal"]),
            int(stream["ffprobe_stream_index"]),
            str(stream["ffmpeg_map"]),
        )
        for stream in audibility.get("streams") or []
    ]
    if media_mapping != audibility_mapping:
        raise RuntimeError(
            "Audio audibility inspection changed the Track-to-stream mapping."
        )


def _audio_selection(media: dict[str, Any], confirmations: dict[str, Any], confirmed_track: int | None = None) -> dict[str, Any]:
    streams = list(media["audio_streams"])
    fingerprint = str(media["audio_layout_fingerprint"])
    audibility = (
        dict(media.get("audio_audibility") or {})
        if isinstance(media.get("audio_audibility"), dict)
        else {}
    )
    source_audibility = str(audibility.get("source_state") or "")
    if source_audibility == "no_audible_narration":
        return {
            "state": "no_audible_narration",
            "selected_ordinal": None,
            "selected_ffmpeg_map": "",
            "confirmation_source": (
                "every complete decoded audio stream is silent or below the "
                "conservative codec-noise floor"
            ),
            "audibility_contract_version": int(
                audibility.get("contract_version")
                or AUDIBILITY_CONTRACT_VERSION
            ),
        }
    if source_audibility == "inconclusive":
        return {
            "state": "audibility_inconclusive",
            "selected_ordinal": None,
            "selected_ffmpeg_map": "",
            "confirmation_source": (
                "decoded audio could not be classified safely"
            ),
            "audibility_contract_version": int(
                audibility.get("contract_version")
                or AUDIBILITY_CONTRACT_VERSION
            ),
        }
    if not streams:
        return {"state": "no_audio", "selected_ordinal": None, "selected_ffmpeg_map": "", "confirmation_source": "no audio streams"}
    audible_ordinals = {
        int(record["audio_ordinal"])
        for record in audibility.get("streams") or []
        if str(record.get("final_state") or "") == "audible_signal"
    }
    if not audibility:
        audible_ordinals = {int(stream["ordinal"]) for stream in streams}
    if len(audible_ordinals) == 1:
        ordinal = next(iter(audible_ordinals))
        stream = next(
            item
            for item in streams
            if int(item["ordinal"]) == ordinal
        )
        return {
            "state": (
                "single-stream"
                if len(streams) == 1
                else "single-audible-stream"
            ),
            "selected_ordinal": ordinal,
            "selected_ffmpeg_map": str(stream["ffmpeg_map"]),
            "confirmation_source": (
                "single audio stream"
                if len(streams) == 1
                else "only one stream contains meaningful audible signal"
            ),
        }
    # 264: your confirmed answer for this recording comes before your saved answer for its layout (design 2.5).
    if confirmed_track is not None and int(confirmed_track) - 1 in audible_ordinals:
        stream = next((item for item in streams if int(item["ordinal"]) == int(confirmed_track) - 1), None)
        if stream is not None:
            return {
                "state": "confirmed-recording",
                "selected_ordinal": int(stream["ordinal"]),
                "selected_ffmpeg_map": str(stream["ffmpeg_map"]),
                "confirmation_source": "your answer for this recording",
            }
    saved = confirmations.get(fingerprint) if isinstance(confirmations, dict) else None
    if isinstance(saved, dict) and str(saved.get("layoutFingerprint") or fingerprint) == fingerprint:
        try:
            ordinal = int(saved.get("audioOrdinal", -1))
        except (TypeError, ValueError):
            ordinal = -1
        stream = next((item for item in streams if int(item["ordinal"]) == ordinal), None)
        if stream is not None and ordinal in audible_ordinals:
            return {
                "state": "confirmed-layout",
                "selected_ordinal": ordinal,
                "selected_ffmpeg_map": str(stream["ffmpeg_map"]),
                "confirmation_source": str(saved.get("confirmationSource") or "exact saved-layout match"),
                "confirmed_utc": str(saved.get("confirmedUtc") or ""),
            }
    return {
        "state": "needs_audio_confirmation",
        "selected_ordinal": None,
        "selected_ffmpeg_map": "",
        "confirmation_source": "unknown or changed multi-track layout",
        "audibility_contract_version": int(
            audibility.get("contract_version")
            or AUDIBILITY_CONTRACT_VERSION
        ),
        "audibility_state": source_audibility or "audible_candidates",
        "audible_ordinals": sorted(audible_ordinals),
    }


def _detection_for_filters(
    media: dict[str, Any],
    audibility: dict[str, Any],
    selection_info: dict[str, Any],
    setting_roles: dict[int, str],
) -> dict[str, Any]:
    """214: the voice-track result the shared invented-line filters read, for a track the Inbox
    chose itself (the only audible track, or your saved answer): each track's role from its name
    or the main track setting, and which tracks are silent."""

    titles = {int(stream["ordinal"]): str(stream.get("title") or "") for stream in media.get("audio_streams") or []}
    _decided_by, roles = voice_track.track_roles(titles, setting_roles)
    audible = {
        int(record["audio_ordinal"])
        for record in audibility.get("streams") or []
        if str(record.get("final_state") or "") == "audible_signal"
    }
    return {
        "selected_ordinal": selection_info.get("selected_ordinal"),
        "track_roles": {str(ordinal + 1): role for ordinal, role in roles.items()},
        "tracks": [
            {"ordinal": ordinal, "track_number": ordinal + 1, "title": titles[ordinal],
             "silent": bool(audibility.get("streams")) and ordinal not in audible}
            for ordinal in sorted(titles)
        ],
    }


def _transcript_result_status(result: dict[str, Any]) -> str:
    """Name what the transcript really is instead of always "complete" (94)."""

    if bool(result.get("silence_hallucination_suspected")) or bool(result.get("quality_blocking")):
        return "unusable_quality_blocked"
    if bool(result.get("no_narration_found")):
        return "no_narration_found"
    return "complete"


def _transcript_result_warning(result: dict[str, Any]) -> str:
    status = _transcript_result_status(result)
    if status == "unusable_quality_blocked":
        return (
            "The transcript looks invented (for example 'Thank you for watching' on "
            "silence) and must not be used as narration. The selected microphone "
            "track is probably silent or wrong."
        )
    if status == "no_narration_found":
        return (
            "No narration was found on the selected microphone track. It is silent, "
            "or it is the wrong track."
        )
    return ""


def _default_transcriber(audio_path: Path, transcript_dir: Path, settings: dict[str, Any]) -> dict[str, Any]:
    # 226: the one Whisper settings rule. The backend has already worked out this request's language,
    # speech mode and GPU choice from the main settings, so they are used as given.
    whisper = whisper_options.from_settings(settings, default_model="base.en", resolved=True)
    return whisper_local.transcribe_from_request(
        {
            "audio_path": str(audio_path),
            "output_dir": str(transcript_dir),
            "model_name": whisper["model_name"],
            "language_code": whisper["language_code"],
            "ffmpeg_dir": str(Path(str(settings.get("ffmpeg_exe") or "ffmpeg")).parent),
            # The Inbox never passed a GPU preference, so it always ran on the
            # CPU (94). Prefer the GPU; whisper_local falls back to the CPU
            # when CUDA is unavailable or fails.
            "prefer_gpu": whisper["prefer_gpu"],
            "narration_speech_mode": whisper["narration_speech_mode"],
            # 206: the operator's words to spell right, as hint and as corrections.
            "initial_prompt": str(settings.get("initial_prompt") or ""),
            "glossary_entries": list(settings.get("glossary_entries") or []),
            "json_name": "transcript.json",
            "srt_name": "transcript.srt",
            "text_name": "transcript.txt",
        }
    )


def _render_visuals(
    ffmpeg_exe: str,
    source: Path,
    media: dict[str, Any],
    visual_dir: Path,
    *,
    include_panel_crops: bool = True,
    ffprobe_exe: str = "ffprobe",
    on_report: Callable[[float, float], None] | None = None,
) -> dict[str, Any]:
    """The package's timeline screenshots, contact sheet and panel crops. ``on_report`` hears how far the
    frame-by-frame check has got when it has to run again (224, Wave B2a), as ``probe_media`` reports."""

    frames_dir = visual_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    def requested_times() -> list[float]:
        chosen = timeline_timestamps(
            float(media["duration_seconds"]),
            [
                float(value)
                for value in media.get("video_frame_timestamps") or []
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            ],
        )
        if not chosen:
            raise RuntimeError(
                "No unique decodable video frame timestamp is available; "
                "the visual package was not completed."
            )
        return chosen

    timestamps = requested_times()
    index: list[dict[str, Any]] = []
    video = media["video_streams"][0] if media["video_streams"] else {}
    expected_width = int(video.get("width") or 0)
    expected_height = int(video.get("height") or 0)

    def keep(frame: dict[str, Any]) -> None:
        # Each frame is checked as soon as it is made, before the next is read.
        target = Path(frame["path"])
        image = _validate_rendered_image(
            ffprobe_exe,
            visual_dir,
            target,
            expected_width=expected_width,
            expected_height=expected_height,
        )
        index.append(
            {
                "ordinal": frame["ordinal"],
                "requested_timestamp_seconds": frame["requested_timestamp_seconds"],
                "actual_timestamp_seconds": frame["actual_timestamp_seconds"],
                # Keep the original field for backward-compatible readers.  It
                # now records the achieved timestamp rather than an optimistic
                # planning value.
                "timestamp_seconds": frame["actual_timestamp_seconds"],
                "path": f"frames/{target.name}",
                **image,
            }
        )

    def render(requested: list[float]) -> None:
        index.clear()
        # 214: made by the one frame renderer, as every screenshot is: each frame read on its own,
        # with the time it really shows.
        frame_render.render_exact(
            ffmpeg_exe,
            source,
            requested,
            frames_dir,
            run=lambda command, **options: _run(command, **options),
            on_frame=keep,
        )

    # 224 (Wave B2a): times read from the packets are checked by the screenshots made from them. When one
    # fails, or shows another picture than its packet's, the recording's frames are all unpacked once, as
    # before; the screenshots are taken again only when that list differs, else the failure stands.
    from_packets = bool(getattr(media.get("video_frame_timestamps"), "from_packets", False))
    failure: RuntimeError | None = None
    try:
        render(timestamps)
        # Half a millisecond: far below the gap between two pictures, even at 240 frames a second.
        doubtful = from_packets and any(
            abs(float(item["actual_timestamp_seconds"]) - float(item["requested_timestamp_seconds"])) > 0.0005
            for item in index
        )
    except RuntimeError as exc:
        if not from_packets:
            raise
        failure, doubtful = exc, True
    if doubtful:
        length = float(media.get("duration_seconds") or 0.0)
        unpacked = _probe_decodable_video_timestamps(
            ffprobe_exe, source, full=True,
            on_report=(lambda at: on_report(at, length)) if on_report is not None else None)
        if list(unpacked) != list(media.get("video_frame_timestamps") or []):
            media["video_frame_timestamps"] = unpacked
            timestamps = requested_times()
            safe_write.remove_disposable_tree(frames_dir, within=visual_dir)
            frames_dir.mkdir(parents=True, exist_ok=True)
            render(timestamps)
        elif failure is not None:
            raise failure
    columns = min(4, len(index))
    rows = int(math.ceil(len(index) / columns))
    contact_sheet = visual_dir / "contact-sheet.jpg"
    _run([ffmpeg_exe, "-y", "-v", "error", "-framerate", "1", "-start_number", "1", "-i", str(frames_dir / "frame-%03d.jpg"), "-frames:v", "1", "-vf", f"scale=480:-1,tile={columns}x{rows}", "-q:v", "3", "-pix_fmt", "yuvj420p", str(contact_sheet)], timeout=300)
    _validate_rendered_image(ffprobe_exe, visual_dir, contact_sheet)
    panel_outputs: list[dict[str, Any]] = []
    layout = panel_layout.detect_three_panel_layout(int(video.get("width") or 0), int(video.get("height") or 0))
    supported_panel_ids = [str(panel["role"]) for panel in layout["panels"]]
    if include_panel_crops and layout["panels"]:
        panel_root = visual_dir / "panels"
        for frame in index:
            source_frame = visual_dir / str(frame["path"])
            for panel in layout["panels"]:
                panel_dir = panel_root / str(panel["role"])
                panel_dir.mkdir(parents=True, exist_ok=True)
                target = panel_dir / f"frame-{int(frame['ordinal']):03d}.jpg"
                # 214: cut by the one frame renderer, as every panel is.
                frame_render.crop_panel(
                    ffmpeg_exe,
                    source_frame,
                    {**panel, "path": str(target)},
                    run=lambda command, **options: _run(command, **options),
                    pix_fmt="yuvj420p",
                )
                image = _validate_rendered_image(
                    ffprobe_exe,
                    visual_dir,
                    target,
                    expected_width=int(panel["crop_width"]),
                    expected_height=int(panel["crop_height"]),
                )
                panel_outputs.append(
                    {
                        "panel": panel["role"],
                        "timestamp_seconds": frame["actual_timestamp_seconds"],
                        "path": str(target.relative_to(visual_dir)).replace("\\", "/"),
                        **image,
                    }
                )
    _atomic_json(
        visual_dir / "timeline-index.json",
        {
            "schema_version": 1,
            "frame_count": len(index),
            "frames": index,
            "supported_panel_ids": supported_panel_ids,
            "panels": panel_outputs,
        },
    )
    return {
        "frame_count": len(index),
        "frames": index,
        "contact_sheet": "contact-sheet.jpg",
        "supported_panel_ids": supported_panel_ids,
        "panels": panel_outputs,
    }


def _validate_rendered_image(
    ffprobe_exe: str,
    root: Path,
    target: Path,
    *,
    expected_width: int = 0,
    expected_height: int = 0,
) -> dict[str, Any]:
    _require_within(root, target, "Rendered image path")
    if target.is_symlink() or not target.is_file():
        raise RuntimeError(
            f"FFmpeg reported success but did not create a regular image: {target.name}"
        )
    size = target.stat().st_size
    if size <= 0:
        raise RuntimeError(f"Rendered image is empty: {target.name}")
    completed = _run(
        [
            ffprobe_exe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_type,width,height",
            "-of",
            "json",
            str(target),
        ],
        timeout=60,
    )
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Rendered image is not probeable: {target.name}") from exc
    streams = [
        item
        for item in payload.get("streams") or []
        if isinstance(item, dict) and str(item.get("codec_type") or "") == "video"
    ]
    if len(streams) != 1:
        raise RuntimeError(f"Rendered image is not a readable single image: {target.name}")
    width = int(streams[0].get("width") or 0)
    height = int(streams[0].get("height") or 0)
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Rendered image dimensions are invalid: {target.name}")
    if expected_width > 0 and width != expected_width:
        raise RuntimeError(
            f"Rendered image width is {width}, expected {expected_width}: {target.name}"
        )
    if expected_height > 0 and height != expected_height:
        raise RuntimeError(
            f"Rendered image height is {height}, expected {expected_height}: {target.name}"
        )
    return {
        "size_bytes": size,
        "sha256": review_ledger.sha256_file(target),
        "width": width,
        "height": height,
    }


def _hash_files(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: str(item).casefold()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        records.append({"path": str(path.relative_to(root)).replace("\\", "/"), "size_bytes": path.stat().st_size, "sha256": digest})
    return records


def _normalise_artifact_path(root: Path, value: Any, label: str) -> tuple[str, Path]:
    raw = str(value or "")
    if (
        not raw
        or raw != raw.strip()
        or "\\" in raw
        or ":" in raw
        or PurePosixPath(raw).is_absolute()
        or any(part in {"", ".", ".."} for part in PurePosixPath(raw).parts)
    ):
        raise RuntimeError(f"{label} path is malformed: {raw!r}")
    canonical = PurePosixPath(raw).as_posix()
    if canonical != raw:
        raise RuntimeError(f"{label} path is not canonical: {raw!r}")
    target = root.joinpath(*PurePosixPath(canonical).parts)
    _require_within(root, target, label)
    return canonical, target


def _validated_record_map(
    root: Path,
    records: Any,
    *,
    label: str,
) -> dict[str, dict[str, Any]]:
    if not isinstance(records, list):
        raise RuntimeError(f"{label} must be a list.")
    result: dict[str, dict[str, Any]] = {}
    physical: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise RuntimeError(f"{label} record is malformed.")
        path, target = _normalise_artifact_path(root, record.get("path"), label)
        key = path.casefold()
        resolved = os.path.normcase(str(target.resolve()))
        if key in result or resolved in physical:
            raise RuntimeError(f"{label} contains a duplicate path: {path}")
        physical.add(resolved)
        recorded_size = record.get("size_bytes")
        if (
            isinstance(recorded_size, bool)
            or not isinstance(recorded_size, int)
            or recorded_size < 0
        ):
            raise RuntimeError(f"{label} size is malformed: {path}")
        digest = str(record.get("sha256") or "").lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise RuntimeError(f"{label} SHA-256 is malformed: {path}")
        if target.is_symlink() or not target.is_file():
            raise RuntimeError(f"{label} artifact is missing or unsafe: {path}")
        if target.stat().st_size != recorded_size:
            raise RuntimeError(f"{label} artifact size changed: {path}")
        if review_ledger.sha256_file(target) != digest:
            raise RuntimeError(f"{label} artifact hash changed: {path}")
        result[key] = {
            "path": path,
            "target": target,
            "size_bytes": recorded_size,
            "sha256": digest,
        }
    return result


def _declared_legacy_artifact_paths(manifest: dict[str, Any]) -> list[str]:
    """Extract paths explicitly named by the original version-1 manifest."""

    declared: list[str] = []
    visuals = manifest.get("visuals")
    if not isinstance(visuals, dict):
        return declared
    for frame in visuals.get("frames") or []:
        if isinstance(frame, dict) and str(frame.get("path") or ""):
            declared.append(f"visuals/{frame['path']}")
    contact = str(visuals.get("contact_sheet") or "")
    if contact:
        declared.append(f"visuals/{contact}")
    for panel in visuals.get("panels") or []:
        if isinstance(panel, dict) and str(panel.get("path") or ""):
            declared.append(f"visuals/{panel['path']}")
    return declared


def _actual_package_files(
    root: Path,
    *,
    ignore_prefixes: tuple[str, ...] = ("targeted-evidence/",),
) -> dict[str, Path]:
    actual: dict[str, Path] = {}
    physical: set[str] = set()
    for target in sorted(root.rglob("*"), key=lambda item: str(item).casefold()):
        if target.is_symlink():
            raise RuntimeError(f"Prepared source package contains a symbolic link: {target.name}")
        if not target.is_file():
            continue
        path = str(target.relative_to(root)).replace("\\", "/")
        if any(path.startswith(prefix) for prefix in ignore_prefixes):
            # Targeted evidence has its own versioned manifest and integrity
            # contract and is appended only after preliminary review.  It is
            # therefore explained but intentionally absent from the immutable
            # base preparation inventory.
            continue
        key = path.casefold()
        resolved = os.path.normcase(str(target.resolve()))
        if key in actual or resolved in physical:
            raise RuntimeError(f"Prepared source package contains a duplicate file: {path}")
        physical.add(resolved)
        actual[key] = target
    return actual


def _validate_source_package(root: Path) -> int:
    integrity_path = root / "integrity.json"
    manifest_path = root / "source-manifest.json"
    if integrity_path.is_symlink() or not integrity_path.is_file():
        raise RuntimeError(f"Prepared source integrity contract is missing: {root.name}")
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise RuntimeError(f"Prepared source manifest is missing: {root.name}")
    payload = json.loads(integrity_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = payload.get("files") if isinstance(payload, dict) else None
    if payload.get("complete") is not True or not isinstance(records, list):
        raise RuntimeError(f"Prepared source integrity contract is incomplete: {root.name}")
    if not isinstance(manifest, dict):
        raise RuntimeError(f"Prepared source manifest is malformed: {root.name}")

    integrity = _validated_record_map(root, records, label="Integrity inventory")
    actual = _actual_package_files(root)
    expected_actual = set(integrity) | {"integrity.json"}
    if set(actual) != expected_actual:
        missing = sorted(expected_actual - set(actual))
        extra = sorted(set(actual) - expected_actual)
        raise RuntimeError(
            "Prepared source actual-file set disagrees with integrity inventory"
            f"; missing={missing}, extra={extra}"
        )
    if "source-manifest.json" not in integrity:
        raise RuntimeError("Prepared source manifest is omitted from integrity inventory.")

    visual_paths: set[str] = set()
    for raw in _declared_legacy_artifact_paths(manifest):
        path, _target = _normalise_artifact_path(
            root,
            raw,
            "Source manifest declared visual artifact",
        )
        visual_paths.add(path.casefold())
    for key in visual_paths:
        record = integrity.get(key)
        if record is not None and int(record["size_bytes"]) <= 0:
            raise RuntimeError(
                f"Prepared visual artifact is empty: {record['path']}"
            )

    declared_records = manifest.get("artifact_inventory")
    if declared_records is not None:
        declared = _validated_record_map(
            root,
            declared_records,
            label="Source manifest artifact inventory",
        )
        expected_declared = set(actual) - {"source-manifest.json", "integrity.json"}
        if set(declared) != expected_declared:
            missing = sorted(expected_declared - set(declared))
            extra = sorted(set(declared) - expected_declared)
            raise RuntimeError(
                "Source manifest artifact inventory disagrees with the package"
                f"; missing={missing}, extra={extra}"
            )
        for key, record in declared.items():
            integrity_record = integrity.get(key)
            if integrity_record is None:
                raise RuntimeError(
                    f"Source manifest artifact is omitted from integrity inventory: {record['path']}"
                )
            if (
                record["size_bytes"] != integrity_record["size_bytes"]
                or record["sha256"] != integrity_record["sha256"]
            ):
                raise RuntimeError(
                    f"Source manifest and integrity metadata disagree: {record['path']}"
                )
    else:
        # Version-1 packages predate the additive complete artifact inventory.
        # Keep them readable, but still require every path they explicitly name
        # (especially timeline frames) to exist in integrity and on disk.
        seen_declared: set[str] = set()
        for raw in _declared_legacy_artifact_paths(manifest):
            path, _target = _normalise_artifact_path(
                root,
                raw,
                "Source manifest declared artifact",
            )
            key = path.casefold()
            if key in seen_declared:
                raise RuntimeError(f"Source manifest contains a duplicate path: {path}")
            seen_declared.add(key)
            if key not in integrity:
                raise RuntimeError(
                    f"Source manifest artifact is omitted from integrity inventory: {path}"
                )
    return len(integrity)


def _complete_source_package(
    root: Path,
    manifest: dict[str, Any],
) -> None:
    """Write a truthful manifest/integrity pair after deriving completeness."""

    if (root / "source-manifest.json").exists() or (root / "integrity.json").exists():
        raise RuntimeError("Package completion requires a fresh staging directory.")
    manifest["artifact_inventory"] = _hash_files(root)
    _atomic_json(root / "source-manifest.json", manifest)
    integrity = _hash_files(root)

    # Prove the candidate record set against the filesystem before emitting a
    # complete flag.  The final validator then proves the cross-document rules.
    _validated_record_map(root, integrity, label="Candidate integrity inventory")
    actual = _actual_package_files(root)
    if set(actual) != {
        str(record["path"]).casefold()
        for record in integrity
    }:
        raise RuntimeError("Candidate integrity inventory does not cover the staged package.")
    _atomic_json(
        root / "integrity.json",
        {"schema_version": 1, "complete": True, "files": integrity},
    )
    _validate_source_package(root)


def validate_batch_packages(
    batch_root: Path,
    *,
    expected_source_count: int = 0,
) -> dict[str, Any]:
    """Read-only proof that every batch source package is internally complete."""

    batch_root = Path(batch_root)
    manifest_path = batch_root / "batch-manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise RuntimeError("Prepared batch manifest is missing or unsafe.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise RuntimeError("Prepared batch manifest is malformed.")
    prepared = manifest.get("prepared_sources")
    if not isinstance(prepared, list) or not prepared:
        raise RuntimeError("Prepared batch manifest has no prepared source inventory.")
    if expected_source_count > 0 and len(prepared) != expected_source_count:
        raise RuntimeError(
            "Prepared batch source count disagrees with the ledger "
            f"({len(prepared)} != {expected_source_count})."
        )

    sources_root = batch_root / "sources"
    expected_roots: dict[str, Path] = {}
    validated: list[dict[str, Any]] = []
    source_ids: set[int] = set()
    for item in prepared:
        if not isinstance(item, dict):
            raise RuntimeError("Prepared batch contains a malformed source record.")
        source_id = item.get("source_id")
        if isinstance(source_id, bool) or not isinstance(source_id, int) or source_id < 1:
            raise RuntimeError("Prepared batch contains an invalid source ID.")
        if source_id in source_ids:
            raise RuntimeError(f"Prepared batch repeats source ID {source_id}.")
        source_ids.add(source_id)
        package_value = str(item.get("package_path") or "").strip()
        package_root = Path(package_value) if package_value else Path()
        if (
            not package_value
            or package_root.parent.resolve() != sources_root.resolve()
            or not _is_within(sources_root, package_root)
        ):
            raise RuntimeError(
                f"Prepared source {source_id} package is outside the batch source root."
            )
        key = os.path.normcase(str(package_root.resolve()))
        if key in expected_roots:
            raise RuntimeError("Prepared batch repeats a physical source package.")
        expected_roots[key] = package_root
        validated.append(
            {
                "source_id": source_id,
                "package_path": str(package_root),
                "integrity_file_count": _validate_source_package(package_root),
            }
        )

    actual_roots = {
        os.path.normcase(str(path.resolve())): path
        for path in sources_root.iterdir()
        if path.is_dir() and not path.is_symlink()
    }
    if set(actual_roots) != set(expected_roots):
        raise RuntimeError(
            "Prepared batch manifest and physical source-package directories disagree."
        )
    return {
        "batch_id": str(manifest.get("batch_id") or ""),
        "source_count": len(validated),
        "sources": validated,
        "complete": True,
    }


def _tree_sha256(root: Path) -> str:
    records = _hash_files(root)
    encoded = json.dumps(
        records,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_salvageable_source_package(root: Path) -> dict[str, Any]:
    """Validate every existing byte while allowing a false-complete manifest."""

    integrity_path = root / "integrity.json"
    manifest_path = root / "source-manifest.json"
    if integrity_path.is_symlink() or not integrity_path.is_file():
        raise RuntimeError("The prior package has no safe integrity inventory.")
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise RuntimeError("The prior package has no safe source manifest.")
    integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(integrity, dict) or integrity.get("complete") is not True:
        raise RuntimeError("The prior package did not claim a completed integrity inventory.")
    if not isinstance(manifest, dict):
        raise RuntimeError("The prior source manifest is malformed.")
    records = _validated_record_map(
        root,
        integrity.get("files"),
        label="Prior integrity inventory",
    )
    actual = _actual_package_files(root)
    if set(actual) != set(records) | {"integrity.json"}:
        raise RuntimeError(
            "The prior package has unverified or absent physical files and cannot be salvaged."
        )
    return manifest


def _repair_journals(batch_root: Path, token: str) -> list[Path]:
    root = batch_root / ".repairs" / token
    if not root.is_dir():
        return []
    return sorted(root.glob("*/repair-journal.json"))


def _repair_attempt(
    connection: sqlite3.Connection,
    *,
    source_id: int,
    batch_id: str,
    settings_hash: str,
) -> int:
    row = connection.execute(
        """
        SELECT attempt_id FROM inbox_attempts
        WHERE source_id = ? AND batch_id = ? AND attempt_type = 'repair'
          AND settings_hash = ?
        ORDER BY attempt_id DESC LIMIT 1
        """,
        (source_id, batch_id, settings_hash),
    ).fetchone()
    if row is not None:
        return int(row[0])
    cursor = connection.execute(
        """
        INSERT INTO inbox_attempts
            (source_id, batch_id, attempt_type, status, started_utc, settings_hash)
        VALUES (?, ?, 'repair', 'preparing', ?, ?)
        """,
        (source_id, batch_id, _utc_now(), settings_hash),
    )
    return int(cursor.lastrowid)


def _repair_external_work_exists(
    connection: sqlite3.Connection,
    batch_id: str,
    batch_root: Path,
) -> bool:
    external_root = batch_root / "external-returns"
    if external_root.is_dir() and any(path.is_file() for path in external_root.rglob("*")):
        return True
    for table in ("inbox_findings", "inbox_final_results", "inbox_finalization_runs"):
        count = int(
            connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()[0]
        )
        if count:
            return True
    return False


def _repair_snapshot(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "source_id": int(row["source_id"]),
        "path": str(row["original_path"] or ""),
        "size_bytes": int(row["size_bytes"]),
        "modified_ns": int(row["modified_ns"]),
        "content_sha256": str(row["content_sha256"] or "").lower(),
        "stable_identity": str(row["stable_identity"] or ""),
    }


def _repair_source_row(
    connection: sqlite3.Connection,
    batch_id: str,
    source_id: int,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT bs.source_id, bs.state, bs.preparation_signature,
               s.stable_identity, s.content_sha256, s.size_bytes,
               l.original_path, l.modified_ns
        FROM inbox_batch_sources bs
        JOIN inbox_sources s ON s.source_id = bs.source_id
        JOIN inbox_source_locations l
          ON l.source_id = bs.source_id AND l.is_current = 1
        WHERE bs.batch_id = ? AND bs.source_id = ?
        ORDER BY l.last_seen_utc DESC LIMIT 1
        """,
        (batch_id, source_id),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Repair source {source_id} has no exact ledger record.")
    return row


def _call_repair_fault(payload: dict[str, Any], phase: str) -> None:
    callback = payload.get("repair_fault_injector")
    if callable(callback):
        callback(phase)


def _prepare_repair_stage(
    *,
    payload: dict[str, Any],
    batch_root: Path,
    source_root: Path,
    history_root: Path,
    stage_root: Path,
    working_copy: Path,
    old_tree_sha256: str,
) -> tuple[Path, dict[str, Any]]:
    package_stage = stage_root / "source"
    if package_stage.is_dir():
        try:
            _validate_source_package(package_stage)
            manifest = json.loads(
                (package_stage / "source-manifest.json").read_text(encoding="utf-8")
            )
            return package_stage, manifest
        except Exception:
            _safe_remove(stage_root, package_stage)
    seed_root = source_root if source_root.is_dir() else history_root
    if not seed_root.is_dir():
        raise RuntimeError("The repair has neither a promoted package nor retained repair history.")
    prior_manifest = _validate_salvageable_source_package(seed_root)
    package_stage.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(seed_root, package_stage)
    for relative in ("visuals", "source-manifest.json", "integrity.json"):
        target = package_stage / relative
        if target.exists():
            _safe_remove(package_stage, target)
    (package_stage / "visuals").mkdir(parents=True, exist_ok=True)

    ffprobe_exe = str(payload.get("ffprobe_exe") or "ffprobe")
    ffmpeg_exe = str(payload.get("ffmpeg_exe") or "ffmpeg")
    supplied_probe = payload.get("media_probe")
    media = (
        supplied_probe(working_copy)
        if callable(supplied_probe)
        else probe_media(ffprobe_exe, working_copy)
    )
    if not isinstance(media, dict):
        raise RuntimeError("Repair media probing returned no usable metadata.")
    renderer = payload.get("visual_renderer")
    if callable(renderer):
        visuals = renderer(working_copy, media, package_stage / "visuals")
    else:
        visuals = _render_visuals(
            ffmpeg_exe,
            working_copy,
            media,
            package_stage / "visuals",
            include_panel_crops=False,
            ffprobe_exe=ffprobe_exe,
        )
    if not isinstance(visuals, dict):
        raise RuntimeError("Repair visual rendering returned no usable manifest.")
    _call_repair_fault(payload, "during_rerender")

    manifest = dict(prior_manifest)
    prior_media = (
        dict(prior_manifest.get("media_metadata") or {})
        if isinstance(prior_manifest.get("media_metadata"), dict)
        else {}
    )
    frame_times = [
        float(value)
        for value in media.get("video_frame_timestamps") or []
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    manifest["media_metadata"] = {
        **prior_media,
        "duration_seconds": float(media.get("duration_seconds") or 0.0),
        "video_streams": list(media.get("video_streams") or []),
        "video_timeline_basis": {
            "decodable_frame_count": len(frame_times),
            "first_decodable_timestamp_seconds": frame_times[0] if frame_times else None,
            "last_decodable_timestamp_seconds": frame_times[-1] if frame_times else None,
        },
    }
    manifest["visuals"] = visuals
    manifest["repair"] = {
        "schema_version": 1,
        "reason": "prepared_package_integrity_reconciliation",
        "prior_package_tree_sha256": old_tree_sha256,
        "preserved_nonvisual_artifacts": True,
        "repaired_utc": _utc_now(),
    }
    manifest.pop("artifact_inventory", None)
    _complete_source_package(package_stage, manifest)
    return package_stage, manifest


def repair_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Detect and repair inconsistent prepared packages without a new run/batch."""

    ledger_value = str(payload.get("ledger_path") or "").strip()
    batch_id = str(payload.get("batch_id") or "").strip()
    scratch_value = str(
        payload.get("scratch_root") or payload.get("local_work_root") or ""
    ).strip()
    if not ledger_value or not batch_id or not scratch_value:
        raise ValueError("ledger_path, batch_id, and scratch_root are required for repair.")
    ledger_path = Path(ledger_value)
    scratch_root = Path(scratch_value)
    # A repair works on a batch the records already hold, so it never makes an empty ledger (224, F4).
    connection = inbox_records.connect(str(ledger_path), must_exist=True)
    repaired: list[dict[str, Any]] = []
    attempts_to_finish: list[int] = []
    leftovers = inbox_records.leftovers_file(ledger_path)
    cleanup_warnings: list[str] = []
    try:
        batch = connection.execute(
            "SELECT status, package_path FROM inbox_batches WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()
        if batch is None:
            raise RuntimeError("The requested repair batch does not exist.")
        batch_root = Path(str(batch["package_path"] or ""))
        if not batch_root.is_dir():
            raise RuntimeError("The requested repair batch package is missing.")
        if str(batch["status"] or "") not in {"awaiting_external_review", "preparing"}:
            raise RuntimeError(
                "Only a prepared or already-scheduled package can be repaired safely."
            )
        if _repair_external_work_exists(connection, batch_id, batch_root):
            raise RuntimeError(
                "External review work already exists; automatic package repair is refused."
            )

        rows = connection.execute(
            """
            SELECT bs.source_id, bs.state, s.stable_identity
            FROM inbox_batch_sources bs
            JOIN inbox_sources s ON s.source_id = bs.source_id
            WHERE bs.batch_id = ? ORDER BY bs.ordinal
            """,
            (batch_id,),
        ).fetchall()
        targets: list[dict[str, Any]] = []
        for item in rows:
            source_id = int(item["source_id"])
            stable = str(item["stable_identity"] or "")
            if not stable:
                raise RuntimeError(f"Repair source {source_id} has no stable identity.")
            token = _source_token(stable)
            package_root = batch_root / "sources" / token
            validation_error = ""
            try:
                _validate_source_package(package_root)
            except Exception as exc:
                validation_error = f"{type(exc).__name__}: {exc}"
            journals = _repair_journals(batch_root, token)
            active_journal: Path | None = None
            current_tree = (
                _tree_sha256(package_root)
                if validation_error and package_root.is_dir()
                else ""
            )
            journal_records: list[tuple[Path, dict[str, Any]]] = []
            for candidate in journals:
                try:
                    record = json.loads(candidate.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if isinstance(record, dict):
                    journal_records.append((candidate, record))
            if current_tree:
                active_journal = next(
                    (
                        path
                        for path, record in journal_records
                        if str(record.get("prior_package_tree_sha256") or "")
                        == current_tree
                    ),
                    None,
                )
            if active_journal is None and str(item["state"] or "") != "awaiting_external_review":
                active_journal = next(
                    (
                        path
                        for path, record in reversed(journal_records)
                        if str(record.get("status") or "") != "committed"
                    ),
                    journal_records[-1][0] if journal_records else None,
                )
            if validation_error or (
                str(item["state"] or "") != "awaiting_external_review"
                and active_journal is not None
            ):
                targets.append(
                    {
                        "source_id": source_id,
                        "token": token,
                        "package_root": package_root,
                        "validation_error": validation_error,
                        "journal_path": active_journal,
                    }
                )

        if not targets:
            validation = validate_batch_packages(
                batch_root,
                expected_source_count=len(rows),
            )
            return {
                "contract_version": CONTRACT_VERSION,
                "action": "repair",
                "status": "already_valid",
                "batch_id": batch_id,
                "batch_path": str(batch_root),
                "repaired_sources": [],
                "validation": validation,
            }

        for target in targets:
            source_id = int(target["source_id"])
            token = str(target["token"])
            source_root = Path(target["package_root"])
            journal_path = target.get("journal_path")
            journal: dict[str, Any] = {}
            if isinstance(journal_path, Path) and journal_path.is_file():
                journal = json.loads(journal_path.read_text(encoding="utf-8"))
            if journal:
                old_tree_sha256 = str(journal.get("prior_package_tree_sha256") or "")
            elif source_root.is_dir():
                old_tree_sha256 = _tree_sha256(source_root)
            else:
                raise RuntimeError(
                    f"Repair source {source_id} has no package or recovery journal."
                )
            if len(old_tree_sha256) != 64:
                raise RuntimeError("Repair package tree identity is malformed.")
            repair_key = old_tree_sha256[:24]
            repair_root = batch_root / ".repairs" / token / repair_key
            journal_path = repair_root / "repair-journal.json"
            history_root = (
                batch_root
                / "repair-history"
                / token
                / repair_key
                / "package"
            )
            settings_hash = hashlib.sha256(
                f"repair-v1:{batch_id}:{source_id}:{old_tree_sha256}".encode("utf-8")
            ).hexdigest()
            connection.execute("BEGIN IMMEDIATE")
            attempt_id = _repair_attempt(
                connection,
                source_id=source_id,
                batch_id=batch_id,
                settings_hash=settings_hash,
            )
            now = _utc_now()
            connection.execute(
                "UPDATE inbox_attempts SET status = 'preparing', completed_utc = NULL, "
                "error_message = NULL WHERE attempt_id = ?",
                (attempt_id,),
            )
            connection.execute(
                "UPDATE inbox_batch_sources SET state = 'retryable_failure', updated_utc = ? "
                "WHERE batch_id = ? AND source_id = ?",
                (now, batch_id, source_id),
            )
            connection.execute(
                "UPDATE inbox_sources SET lifecycle_state = 'retryable_failure', updated_utc = ? "
                "WHERE source_id = ?",
                (now, source_id),
            )
            connection.execute(
                "UPDATE inbox_batches SET status = 'preparing', updated_utc = ? WHERE batch_id = ?",
                (now, batch_id),
            )
            prior_event = connection.execute(
                """
                SELECT 1 FROM inbox_lifecycle_events
                WHERE batch_id = ? AND source_id = ?
                  AND event_type = 'prepared_package_repair_started'
                  AND details_json LIKE ?
                LIMIT 1
                """,
                (batch_id, source_id, f"%{old_tree_sha256}%"),
            ).fetchone()
            if prior_event is None:
                _event(
                    connection,
                    source_id,
                    batch_id,
                    "prepared_package_repair_started",
                    "awaiting_external_review",
                    "retryable_failure",
                    {
                        "prior_package_tree_sha256": old_tree_sha256,
                        "reason": str(target.get("validation_error") or ""),
                    },
                )
            connection.commit()
            repair_root.mkdir(parents=True, exist_ok=True)
            journal = {
                **journal,
                "schema_version": 1,
                "batch_id": batch_id,
                "source_id": source_id,
                "source_token": token,
                "attempt_id": attempt_id,
                "settings_hash": settings_hash,
                "prior_package_tree_sha256": old_tree_sha256,
                "history_path": str(history_root),
                "package_path": str(source_root),
                "status": str(journal.get("status") or "scheduled"),
                "updated_utc": _utc_now(),
            }
            _atomic_json(journal_path, journal)
            _call_repair_fault(payload, "after_repair_scheduled")

            try:
                current_valid = False
                if source_root.is_dir():
                    try:
                        _validate_source_package(source_root)
                        current_valid = True
                    except Exception:
                        current_valid = False
                if not current_valid:
                    row = _repair_source_row(connection, batch_id, source_id)
                    snapshot = _repair_snapshot(row)
                    source = Path(snapshot["path"])
                    if not snapshot["content_sha256"]:
                        raise SourceChangedError(
                            "Repair requires the source's complete SHA-256 identity."
                        )
                    before = source.stat()
                    if (
                        before.st_size != snapshot["size_bytes"]
                        or before.st_mtime_ns != snapshot["modified_ns"]
                    ):
                        raise SourceChangedError(
                            "Source size or modification time changed before repair."
                        )
                    working_root = (
                        scratch_root
                        / "review-inbox-repair"
                        / batch_id
                        / token
                        / f"attempt-{attempt_id}"
                    )
                    working_copy = (
                        working_root
                        / "source"
                        / f"source{source.suffix.lower() or '.media'}"
                    )
                    _require_within(scratch_root, working_root, "Repair working-copy path")
                    if working_copy.is_file():
                        if (
                            working_copy.stat().st_size != before.st_size
                            or review_ledger.sha256_file(working_copy)
                            != snapshot["content_sha256"]
                        ):
                            _safe_remove(scratch_root, working_root)
                    if not working_copy.is_file():
                        copied = stream_verified_copy(source, working_copy)
                        if str(copied["sha256"]).lower() != snapshot["content_sha256"]:
                            raise SourceChangedError(
                                "Repair working copy does not match the full source identity."
                            )
                    after = source.stat()
                    if (
                        after.st_size != before.st_size
                        or after.st_mtime_ns != before.st_mtime_ns
                    ):
                        raise SourceChangedError("Source changed while repair copy was verified.")
                    journal["status"] = "source_verified"
                    journal["updated_utc"] = _utc_now()
                    _atomic_json(journal_path, journal)

                    stage_root = batch_root / ".staging" / (
                        f"repair-{token}-{repair_key}"
                    )
                    _require_within(batch_root, stage_root, "Repair staging path")
                    stage_root.mkdir(parents=True, exist_ok=True)
                    package_stage, repaired_manifest = _prepare_repair_stage(
                        payload=payload,
                        batch_root=batch_root,
                        source_root=source_root,
                        history_root=history_root,
                        stage_root=stage_root,
                        working_copy=working_copy,
                        old_tree_sha256=old_tree_sha256,
                    )
                    _validate_source_package(package_stage)
                    journal["status"] = "staging_verified"
                    journal["staged_package_tree_sha256"] = _tree_sha256(package_stage)
                    journal["updated_utc"] = _utc_now()
                    _atomic_json(journal_path, journal)
                    _call_repair_fault(payload, "after_staging_verified")

                    if source_root.is_dir():
                        history_root.parent.mkdir(parents=True, exist_ok=True)
                        if history_root.exists():
                            if _tree_sha256(history_root) != old_tree_sha256:
                                raise RuntimeError(
                                    "Retained repair history does not match the detected package."
                                )
                        else:
                            safe_write.move(source_root, history_root)
                    if not history_root.is_dir() or _tree_sha256(history_root) != old_tree_sha256:
                        raise RuntimeError("Prior package was not retained intact before repair.")
                    journal["status"] = "prior_package_retained"
                    journal["updated_utc"] = _utc_now()
                    _atomic_json(journal_path, journal)
                    _call_repair_fault(payload, "after_prior_package_retained")

                    if not source_root.exists():
                        safe_write.move(package_stage, source_root)
                    _validate_source_package(source_root)
                    journal["status"] = "promoted"
                    journal["promoted_package_tree_sha256"] = _tree_sha256(source_root)
                    journal["updated_utc"] = _utc_now()
                    _atomic_json(journal_path, journal)
                    _call_repair_fault(payload, "after_promotion")
                    if working_root.exists():
                        _tidy(scratch_root, working_root, leftovers, cleanup_warnings)
                        _prune_empty_parents(scratch_root, working_root.parent)
                else:
                    repaired_manifest = json.loads(
                        (source_root / "source-manifest.json").read_text(encoding="utf-8")
                    )

                attempts_to_finish.append(attempt_id)
                repaired.append(
                    {
                        "source_id": source_id,
                        "source_token": token,
                        "package_path": str(source_root),
                        "history_path": str(history_root),
                        "prior_package_tree_sha256": old_tree_sha256,
                        "corrected_package_tree_sha256": _tree_sha256(source_root),
                        "frame_count": int(
                            ((repaired_manifest.get("visuals") or {}).get("frame_count") or 0)
                        ),
                        "journal_path": str(journal_path),
                    }
                )
            except Exception as exc:
                journal["status"] = "retryable_failure"
                journal["error"] = f"{type(exc).__name__}: {exc}"
                journal["updated_utc"] = _utc_now()
                _atomic_json(journal_path, journal)
                connection.execute(
                    "UPDATE inbox_attempts SET status = 'retryable_failure', error_message = ? "
                    "WHERE attempt_id = ?",
                    (str(exc), attempt_id),
                )
                connection.commit()
                raise

        batch_manifest_path = batch_root / "batch-manifest.json"
        batch_manifest = json.loads(batch_manifest_path.read_text(encoding="utf-8"))
        if not isinstance(batch_manifest, dict):
            raise RuntimeError("Batch manifest became malformed during repair.")
        repair_records = [
            item
            for item in batch_manifest.get("repairs") or []
            if isinstance(item, dict)
        ]
        existing_keys = {
            (int(item.get("source_id") or 0), str(item.get("prior_package_tree_sha256") or ""))
            for item in repair_records
        }
        for item in repaired:
            key = (int(item["source_id"]), str(item["prior_package_tree_sha256"]))
            if key not in existing_keys:
                repair_records.append(
                    {
                        "source_id": item["source_id"],
                        "prior_package_tree_sha256": item["prior_package_tree_sha256"],
                        "corrected_package_tree_sha256": item[
                            "corrected_package_tree_sha256"
                        ],
                        "history_path": item["history_path"],
                        "repaired_utc": _utc_now(),
                    }
                )
                existing_keys.add(key)
        batch_manifest["repairs"] = repair_records
        batch_manifest["status"] = "awaiting_external_review"
        batch_manifest["updated_utc"] = _utc_now()
        _atomic_json(batch_manifest_path, batch_manifest)
        review_findings.write_review_materials(batch_root, batch_manifest)
        validation = validate_batch_packages(
            batch_root,
            expected_source_count=len(rows),
        )

        connection.execute("BEGIN IMMEDIATE")
        now = _utc_now()
        for item in repaired:
            source_id = int(item["source_id"])
            prior_state = str(
                connection.execute(
                    "SELECT state FROM inbox_batch_sources WHERE batch_id = ? AND source_id = ?",
                    (batch_id, source_id),
                ).fetchone()[0]
            )
            connection.execute(
                "UPDATE inbox_batch_sources SET state = 'awaiting_external_review', updated_utc = ? "
                "WHERE batch_id = ? AND source_id = ?",
                (now, batch_id, source_id),
            )
            connection.execute(
                "UPDATE inbox_sources SET lifecycle_state = 'awaiting_external_review', "
                "updated_utc = ? WHERE source_id = ?",
                (now, source_id),
            )
            event_exists = connection.execute(
                """
                SELECT 1 FROM inbox_lifecycle_events
                WHERE batch_id = ? AND source_id = ?
                  AND event_type = 'prepared_package_repaired'
                  AND details_json LIKE ?
                LIMIT 1
                """,
                (
                    batch_id,
                    source_id,
                    f"%{item['prior_package_tree_sha256']}%",
                ),
            ).fetchone()
            if event_exists is None:
                _event(
                    connection,
                    source_id,
                    batch_id,
                    "prepared_package_repaired",
                    prior_state,
                    "awaiting_external_review",
                    {
                        "prior_package_tree_sha256": item["prior_package_tree_sha256"],
                        "corrected_package_tree_sha256": item[
                            "corrected_package_tree_sha256"
                        ],
                    },
                )
        unfinished = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM inbox_batch_sources
                WHERE batch_id = ? AND state != 'awaiting_external_review'
                """,
                (batch_id,),
            ).fetchone()[0]
        )
        if unfinished:
            raise RuntimeError("Repair cannot advance a batch with unfinished source packages.")
        connection.execute(
            "UPDATE inbox_batches SET status = 'awaiting_external_review', updated_utc = ? "
            "WHERE batch_id = ?",
            (now, batch_id),
        )
        for attempt_id in sorted(set(attempts_to_finish)):
            connection.execute(
                "UPDATE inbox_attempts SET status = 'prepared', completed_utc = ?, "
                "error_message = NULL WHERE attempt_id = ?",
                (now, attempt_id),
            )
        connection.commit()
        for item in repaired:
            journal_path = Path(str(item["journal_path"]))
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            journal["status"] = "committed"
            journal["updated_utc"] = _utc_now()
            _atomic_json(journal_path, journal)
        _call_repair_fault(payload, "after_ledger_commit")
        return {
            "contract_version": CONTRACT_VERSION,
            "action": "repair",
            "status": "awaiting_external_review",
            "batch_id": batch_id,
            "batch_path": str(batch_root),
            "repaired_sources": repaired,
            "validation": validation,
            "cleanup_warnings": cleanup_warnings,
        }
    finally:
        connection.close()


def _merge_source_records(existing: list[dict[str, Any]], current: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for item in [*existing, *current]:
        if isinstance(item, dict) and item.get("source_id") is not None:
            merged[int(item["source_id"])] = item
    return [merged[key] for key in sorted(merged)]


def _source_token(identity: str) -> str:
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def _space_available(path: Path) -> int:
    path.mkdir(parents=True, exist_ok=True)
    return int(shutil.disk_usage(path).free)


def _source_from_ledger(connection: sqlite3.Connection, source_id: int) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT s.*, l.original_path, l.normalized_path, l.modified_ns, l.modified_utc
        FROM inbox_sources s JOIN inbox_source_locations l ON l.source_id = s.source_id
        WHERE s.source_id = ? AND l.is_current = 1 ORDER BY l.last_seen_utc DESC LIMIT 1
        """,
        (source_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Source {source_id} has no current ledger location.")
    return {key: row[key] for key in row.keys()}


def _event(connection: sqlite3.Connection, source_id: int | None, batch_id: str, event: str, before: str, after: str, details: dict[str, Any] | None = None) -> None:
    review_ledger._insert_lifecycle_event(connection, source_id=source_id, batch_id=batch_id, event_type=event, from_state=before, to_state=after, details=details)


def _set_state(connection: sqlite3.Connection, source_id: int, batch_id: str, state: str, *, details: dict[str, Any] | None = None) -> None:
    old = connection.execute("SELECT lifecycle_state FROM inbox_sources WHERE source_id = ?", (source_id,)).fetchone()[0]
    now = _utc_now()
    connection.execute("UPDATE inbox_sources SET lifecycle_state = ?, updated_utc = ? WHERE source_id = ?", (state, now, source_id))
    connection.execute("UPDATE inbox_batch_sources SET state = ?, updated_utc = ? WHERE batch_id = ? AND source_id = ?", (state, now, batch_id, source_id))
    _event(connection, source_id, batch_id, "preparation_state_changed", str(old), state, details)


def _create_batch(
    connection: sqlite3.Connection,
    package_path: Path,
    selected: list[dict[str, Any]],
    *,
    batch_id: str = "",
) -> str:
    batch_id = batch_id or f"batch-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    if not batch_id.startswith("batch-") or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in batch_id):
        raise ValueError("A preallocated Review Media Inbox batch ID is malformed.")
    now = _utc_now()
    connection.execute("INSERT INTO inbox_batches (batch_id, status, package_path, is_legacy, created_utc, updated_utc) VALUES (?, 'preparing', ?, 0, ?, ?)", (batch_id, str(package_path), now, now))
    for ordinal, item in enumerate(selected, 1):
        connection.execute("INSERT INTO inbox_batch_sources (batch_id, source_id, ordinal, state, added_utc, updated_utc) VALUES (?, ?, ?, 'pending', ?, ?)", (batch_id, int(item["source_id"]), ordinal, now, now))
        _event(connection, int(item["source_id"]), batch_id, "source_added_to_batch", str(item.get("classification") or "pending"), "pending")
    connection.commit()
    return batch_id


def _batch_sources(connection: sqlite3.Connection, batch_id: str) -> list[dict[str, Any]]:
    rows = connection.execute("SELECT source_id, ordinal, state FROM inbox_batch_sources WHERE batch_id = ? AND state NOT IN ('prepared', 'awaiting_external_review') ORDER BY ordinal", (batch_id,)).fetchall()
    return [_source_from_ledger(connection, int(row["source_id"])) | {"ordinal": int(row["ordinal"]), "batch_state": str(row["state"])} for row in rows]


def _refresh_legacy_resume_snapshot(
    connection: sqlite3.Connection,
    item: dict[str, Any],
    sample_hasher: Callable[[Path], str],
    full_hasher: Callable[[Path], str],
) -> dict[str, Any]:
    """Re-establish one missing foundation-era source boundary in place."""

    source_id = int(item["source_id"])
    source_value = str(item.get("original_path") or "").strip()
    if not source_value:
        raise RuntimeError(
            f"Legacy resumable source {source_id} has no current path."
        )
    source = Path(source_value)
    before = source.stat()
    expected_content = str(item.get("content_sha256") or "").strip().lower()
    stable_identity = str(item.get("stable_identity") or "").strip().lower()
    if stable_identity:
        if not stable_identity.startswith("sha256:"):
            raise SourceChangedError(
                f"Legacy resumable source {source_id} has an invalid stable identity."
            )
        stable_digest = stable_identity.removeprefix("sha256:")
        if (
            len(stable_digest) != 64
            or any(character not in "0123456789abcdef" for character in stable_digest)
        ):
            raise SourceChangedError(
                f"Legacy resumable source {source_id} has an invalid stable identity."
            )
        if expected_content and expected_content != stable_digest:
            raise SourceChangedError(
                f"Legacy resumable source {source_id} has conflicting full identities."
            )
        expected_content = stable_digest
    if expected_content and (
        len(expected_content) != 64
        or any(character not in "0123456789abcdef" for character in expected_content)
    ):
        raise SourceChangedError(
            f"Legacy resumable source {source_id} has an invalid full identity."
        )
    sampled = str(sample_hasher(source) or "").lower()
    measured_content = (
        str(full_hasher(source) or "").strip().lower()
        if expected_content
        else ""
    )
    after = source.stat()
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise SourceChangedError(
            f"Legacy resumable source {source_id} changed during identity refresh."
        )
    if expected_content and measured_content != expected_content:
        raise SourceChangedError(
            f"Legacy resumable source {source_id} does not match its full SHA-256 identity."
        )
    modified_utc = (
        datetime.fromtimestamp(before.st_mtime, timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )
    now = _utc_now()
    connection.execute(
        """
        UPDATE inbox_source_locations
        SET size_bytes = ?, modified_utc = ?, modified_ns = ?, last_seen_utc = ?
        WHERE source_id = ? AND is_current = 1
        """,
        (before.st_size, modified_utc, before.st_mtime_ns, now, source_id),
    )
    connection.execute(
        """
        UPDATE inbox_sources
        SET sampled_sha256 = ?, size_bytes = ?, updated_utc = ?
        WHERE source_id = ?
        """,
        (sampled, before.st_size, now, source_id),
    )
    connection.commit()
    identity = (
        stable_identity
        or (
            review_ledger.stable_identity(expected_content)
            if expected_content
            else str(item.get("provisional_identity") or "")
        )
    )
    return {
        "source_id": source_id,
        "path": str(source),
        "size_bytes": before.st_size,
        "modified_utc": modified_utc,
        "modified_ns": before.st_mtime_ns,
        "identity": identity,
        "identity_kind": "stable" if expected_content else "provisional",
        "sampled_sha256": sampled,
        "content_sha256": expected_content,
    }


def _attempt_start(connection: sqlite3.Connection, source_id: int, batch_id: str, settings_hash: str) -> int:
    cursor = connection.execute("INSERT INTO inbox_attempts (source_id, batch_id, attempt_type, status, started_utc, settings_hash) VALUES (?, ?, 'prepare', 'preparing', ?, ?)", (source_id, batch_id, _utc_now(), settings_hash))
    connection.commit()
    return int(cursor.lastrowid)


def _attempt_finish(connection: sqlite3.Connection, attempt_id: int, status: str, error: str = "") -> None:
    connection.execute("UPDATE inbox_attempts SET status = ?, completed_utc = ?, error_message = ? WHERE attempt_id = ?", (status, _utc_now(), error or None, attempt_id))
    connection.commit()


def recover_staging(
    batch_root: Path,
    scratch_root: Path,
    *,
    process_checker: Callable[[int], bool] | None = None,
) -> list[dict[str, Any]]:
    """Classify live/stale atomic attempt files and validate reusable copies."""
    def default_checker(pid: int, written: float) -> bool:
        # 224 (Wave B1): asked the way the AI Video Editor asks, never with os.kill(pid, 0). On Windows signal 0
        # is Ctrl+C: for a running process it is sent to the processes sharing this console, which ends this
        # very Process run (and its PowerShell host). After a crash Windows may also have given the number to
        # another program: one that started after the attempt last wrote its state is not the attempt.
        from media_manglers.core.race_video.render import (  # noqa: PLC0415
            PROCESS_START_TOLERANCE,
            process_alive,
            process_start_time,
        )

        if not process_alive(pid):
            return False
        started = process_start_time(pid)
        return started is None or started <= written + PROCESS_START_TOLERANCE

    def checker(pid: int, state_path: Path) -> bool:
        if process_checker is not None:
            return process_checker(pid)
        return default_checker(pid, state_path.stat().st_mtime)

    actions: list[dict[str, Any]] = []
    staging = batch_root / ".staging"
    if not staging.exists():
        return actions
    for state_path in staging.glob("*/attempt-state.json"):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            working_value = str(state.get("working_copy_path") or "")
            working = Path(working_value) if working_value else None
            common = {
                "attempt": state_path.parent.name,
                "source_id": state.get("source_id"),
                "working_copy_path": working_value,
                "expected_size": state.get("expected_size"),
                "expected_sha256": str(state.get("expected_sha256") or ""),
            }
            if str(state.get("status")) in {"prepared", "needs_audio_confirmation", "retryable_failure", "source_changed"}:
                actions.append({**common, "classification": "complete", "reusable": False})
                continue
            pid = int(state.get("process_id") or 0)
            if str(state.get("status")) == "preparing" and pid > 0 and checker(pid, state_path):
                actions.append({**common, "classification": "still_live", "reusable": False})
                continue
            reusable = False
            if working is not None and working.is_file() and _is_within(scratch_root, working):
                expected_size = int(state.get("expected_size") or -1)
                expected_sha = str(state.get("expected_sha256") or "")
                reusable = working.stat().st_size == expected_size and bool(expected_sha) and review_ledger.sha256_file(working) == expected_sha
            classification = "stale_reusable" if reusable else "stale_restart_required"
            state["status"] = classification
            state["reusable"] = reusable
            state["recovered_utc"] = _utc_now()
            _atomic_json(state_path, state)
            actions.append({**common, "classification": classification, "reusable": reusable})
        except (OSError, ValueError, json.JSONDecodeError):
            actions.append({"attempt": state_path.parent.name, "classification": "invalid_restart_required", "reusable": False})
    return actions


def prepare_selected_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Prepare one explicit Process-mode chunk without changing legacy Prepare behavior."""

    selected_ids = payload.get("selected_source_ids")
    if selected_ids is None:
        selected_ids = []
    if not isinstance(selected_ids, list):
        raise ValueError("selected_source_ids must be a list.")
    normalized_ids: list[int] = []
    for value in selected_ids:
        if isinstance(value, bool):
            raise ValueError("selected_source_ids must contain positive integers.")
        source_id = int(value)
        if source_id < 1:
            raise ValueError("selected_source_ids must contain positive integers.")
        if source_id not in normalized_ids:
            normalized_ids.append(source_id)
    if len(normalized_ids) > 3:
        raise ValueError("Process-mode preparation chunks may contain at most three sources.")
    if not normalized_ids and not str(payload.get("resume_batch_id") or "").strip():
        raise ValueError("Process-mode preparation requires selected_source_ids or resume_batch_id.")
    request = dict(payload)
    request["selected_source_ids"] = normalized_ids
    request["_process_mode"] = True
    return prepare_from_request(request)


def prepare_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Scan and prepare one bounded batch, or return the existing active batch."""
    process_mode = bool(payload.get("_process_mode"))
    evidence_value = str(payload.get("evidence_root") or "").strip()
    scratch_value = str(payload.get("scratch_root") or payload.get("local_work_root") or "").strip()
    if not evidence_value:
        raise ValueError("evidence_root is required for preparation.")
    if not scratch_value:
        raise ValueError("scratch_root is required for preparation.")
    evidence_root = Path(evidence_value)
    scratch_root = Path(scratch_value)
    supplied_scan = payload.get("scan_result")
    if isinstance(supplied_scan, dict) and isinstance(supplied_scan.get("settings"), dict):
        scan_result = supplied_scan
    else:
        scan_payload = dict(payload)
        scan_payload.pop("action", None)
        scan_result = review_inbox.scan_from_request(scan_payload)
    ledger_path = str(scan_result["settings"]["ledger_path"])
    # 224 (F9): every batch lives in the one Inbox folder, the queue's own, whether Process or the command-line
    # Prepare made it. Batches an older command-line Prepare left under <evidence root>\review-inbox stay where they
    # are; the move counts them.
    inbox_root = inbox_records.workspace(ledger_path)
    batches_root = inbox_root / "batches"
    batches_root.mkdir(parents=True, exist_ok=True)
    scratch_root.mkdir(parents=True, exist_ok=True)
    # 224 (Wave B2a, Decision 3): what another program kept this run from cleaning up is noted for the next.
    leftovers = inbox_records.leftovers_file(ledger_path)
    cleanup_warnings: list[str] = []
    space_probe = payload.get("space_probe") if callable(payload.get("space_probe")) else _space_available
    clock = payload.get("clock") if callable(payload.get("clock")) else time.monotonic
    stop_path_value = str(payload.get("stop_after_current_file_path") or "").strip()
    stop_path = Path(stop_path_value) if stop_path_value else None
    if callable(payload.get("stop_requested")):
        stop_requested = payload["stop_requested"]
    else:
        stop_requested = lambda: bool(stop_path and stop_path.exists())
    progress_callback = payload.get("progress_callback") if callable(payload.get("progress_callback")) else None
    # 214: Pause and Skip from Queue / Progress. A pause suspends this process from the backend; a
    # skip is seen here at the next step of the recording being prepared.
    run_control_value = str(payload.get("run_control_path") or "").strip()
    run_control_path = Path(run_control_value) if run_control_value else None
    skip_watch: dict[str, Path | None] = {"source": None}
    emit_progress = bool(payload.get("emit_progress"))
    progress_state_value = str(payload.get("progress_state_file_path") or "").strip()
    progress_state_path = Path(progress_state_value) if progress_state_value else None

    def progress(
        phase: str,
        *,
        source_name: str = "",
        source_index: int = 0,
        source_total: int = 0,
        source_state: str = "active",
        source_terminal: bool = False,
        prepared_count: int = 0,
        blocked_count: int = 0,
        failed_count: int = 0,
        activity: str = "",
        terminal_state: str = "",
        work: tuple[int, int, str] | None = None,
    ) -> None:
        watched = skip_watch["source"]
        if watched is not None and _skip_requested(run_control_path, watched):
            skip_watch["source"] = None
            raise SkippedByOperatorError(f"Skipped by you ({watched.name}).")
        event = {
            "schema": "MM_PROGRESS_V1",
            "updated_at_utc": _utc_now(),
            "phase": phase,
            # 224 (Wave B2a, 272): a step that can say how far it has got reports work done of total, and
            # in what ("seconds" of a recording); the others say only that they are working.
            "progress_kind": "work_units" if work is not None and work[1] > 0 else "indeterminate",
            "source_name": source_name,
            "source_completed": prepared_count + blocked_count + failed_count,
            "source_total": source_total,
            "source_ordinal": source_index,
            "source_state": source_state,
            "source_terminal": source_terminal,
            "prepared_count": prepared_count,
            "blocked_count": blocked_count,
            "failed_count": failed_count,
            "activity": activity or phase,
            "terminal_state": terminal_state,
        }
        if event["progress_kind"] == "work_units" and work is not None:
            event.update({"completed": int(work[0]), "total": int(work[1]), "work_unit": work[2]})
        if progress_state_path is not None:
            _atomic_json(progress_state_path, event)
        if progress_callback is not None:
            progress_callback(event)
        elif emit_progress:
            print("MM_PROGRESS_V1 " + json.dumps(event, ensure_ascii=False, separators=(",", ":")), flush=True)
    injected_media_probe = callable(payload.get("media_probe"))
    if injected_media_probe:
        probe = lambda path, on_report=None: payload["media_probe"](path)  # noqa: E731
    else:
        probe = lambda path, on_report=None: probe_media(  # noqa: E731
            str(payload.get("ffprobe_exe") or "ffprobe"), path, on_report=on_report)
    supplied_audibility_inspector = payload.get("audibility_inspector")
    if callable(supplied_audibility_inspector):
        audibility_inspector = supplied_audibility_inspector
    elif injected_media_probe:
        audibility_inspector = (
            lambda _source, media, _temp_root: _injected_probe_audibility(media)
        )
    else:
        audibility_inspector = (
            lambda source, _media, temp_root: inspect_source(
                str(payload.get("ffprobe_exe") or "ffprobe"),
                str(payload.get("ffmpeg_exe") or "ffmpeg"),
                source,
                temp_root,
            )
        )
    copier = payload.get("copy_file") if callable(payload.get("copy_file")) else stream_verified_copy
    process_sample_hasher = (
        payload.get("sample_hasher")
        if callable(payload.get("sample_hasher"))
        else review_inbox.sampled_sha256_file
    )
    process_full_hasher = (
        payload.get("full_hasher")
        if callable(payload.get("full_hasher"))
        else review_inbox.full_sha256_file
    )
    # 224 (Wave B2a): how the screenshot step's frame-by-frame check, when it has to run again, reports on the
    # recording being prepared; set for each recording below.
    render_report: dict[str, Callable[[float, float], None] | None] = {"call": None}
    renderer = (
        payload.get("visual_renderer")
        if callable(payload.get("visual_renderer"))
        else lambda source, media, output: _render_visuals(
            str(payload.get("ffmpeg_exe") or "ffmpeg"),
            source,
            media,
            output,
            include_panel_crops=not process_mode,
            ffprobe_exe=str(payload.get("ffprobe_exe") or "ffprobe"),
            on_report=render_report["call"],
        )
    )
    transcriber = payload.get("transcriber") if callable(payload.get("transcriber")) else _default_transcriber
    ffmpeg_value = str(payload.get("ffmpeg_exe") or "ffmpeg")
    # 214: the narration audio is read by the shared extractor, which has no time limit while
    # FFmpeg keeps moving (this copy had a one-hour limit).
    audio_extractor = payload.get("audio_extractor") if callable(payload.get("audio_extractor")) else lambda source, ordinal, output: voice_track.extract_track(ffmpeg_value, source, ordinal, output)
    # 214: when several tracks could be the narration and you have not said which, the shared
    # engine chooses, as for every other feature; you are asked only when it cannot tell.
    setting_roles = voice_track.parse_track_roles(payload.get("track_roles"))
    if callable(payload.get("voice_detector")):
        voice_detector = payload["voice_detector"]
    elif injected_media_probe:
        voice_detector = None
    else:
        def voice_detector(source: Path, work_dir: Path, keep_dir: Path) -> dict[str, Any]:
            found = voice_track.detect_voice_track(
                source,
                ffmpeg_exe=ffmpeg_value,
                ffprobe_exe=str(payload.get("ffprobe_exe") or "ffprobe"),
                work_dir=work_dir,
                model_name=str(payload.get("whisper_model") or "base.en"),
                prefer_gpu=bool(payload.get("prefer_gpu", True)),
                language_code=str(payload.get("language_code") or "en"),
                keep_wavs_dir=keep_dir,
                setting_roles=setting_roles,
                details=True,
            )
            # 264: kept in the library right after detection; nothing per track goes on into the package.
            speech_facts.record_measure(source, found, measured_by=speech_facts.BY_INBOX, setting_roles=setting_roles,
                                        duration=float(found.get("duration_seconds") or 0.0))
            return voice_track.strip_details(found)
    # 214: and the shared invented-line filters: lines another track carries, and lines the
    # narration track is near silent for, are dropped from the transcript.
    if callable(payload.get("line_checker")):
        line_checker = payload["line_checker"]
    elif callable(payload.get("transcriber")):
        line_checker = None
    else:
        line_checker = cross_track_check.check_from_request
    confirmations = payload.get("audio_confirmations") if isinstance(payload.get("audio_confirmations"), dict) else {}
    confirmation_path = str(payload.get("audio_confirmations_path") or "").strip()
    if not confirmations and confirmation_path:
        try:
            saved_payload = json.loads(Path(confirmation_path).read_text(encoding="utf-8-sig"))
            layouts = saved_payload.get("layouts") if isinstance(saved_payload, dict) else None
            confirmations = layouts if isinstance(layouts, dict) else {}
        except (OSError, json.JSONDecodeError):
            confirmations = {}
    settings_hash = hashlib.sha256(json.dumps(scan_result["settings"], sort_keys=True, default=str).encode("utf-8")).hexdigest()
    connection = inbox_records.connect(ledger_path)
    batch_id = ""
    try:
        active = list(scan_result["pending_batches"])
        process_snapshots = {
            int(item["source_id"]): dict(item)
            for item in scan_result.get("sources") or []
            if process_mode
            and isinstance(item, dict)
            and item.get("source_id") is not None
        }

        def freeze_process_selection(
            items: list[dict[str, Any]],
        ) -> list[dict[str, Any]]:
            frozen: list[dict[str, Any]] = []
            for item in items:
                source_id = int(item["source_id"])
                snapshot = process_snapshots.get(source_id)
                if snapshot is None:
                    # Existing pre-Process batches have no run snapshot. Freeze
                    # their current ledger identity for this recovery attempt
                    # without changing legacy Scan or Prepare behavior.
                    if item.get("modified_ns") is None:
                        snapshot = _refresh_legacy_resume_snapshot(
                            connection,
                            item,
                            process_sample_hasher,
                            process_full_hasher,
                        )
                    else:
                        snapshot = {
                            "source_id": source_id,
                            "path": str(item.get("original_path") or ""),
                            "size_bytes": item.get("size_bytes"),
                            "modified_utc": str(item.get("modified_utc") or ""),
                            "modified_ns": item.get("modified_ns"),
                            "identity": str(
                                item.get("stable_identity")
                                or item.get("provisional_identity")
                                or ""
                            ),
                            "identity_kind": (
                                "stable" if item.get("stable_identity") else "provisional"
                            ),
                            "sampled_sha256": str(item.get("sampled_sha256") or ""),
                            "content_sha256": str(item.get("content_sha256") or ""),
                        }
                snapshot_path = str(snapshot.get("path") or "").strip()
                snapshot_size = snapshot.get("size_bytes")
                snapshot_modified_ns = snapshot.get("modified_ns")
                snapshot_identity = str(snapshot.get("identity") or "").strip()
                if (
                    not snapshot_path
                    or isinstance(snapshot_size, bool)
                    or not isinstance(snapshot_size, int)
                    or snapshot_size < 0
                    or isinstance(snapshot_modified_ns, bool)
                    or not isinstance(snapshot_modified_ns, int)
                    or snapshot_modified_ns < 0
                    or not snapshot_identity
                ):
                    raise RuntimeError(
                        f"Process source {source_id} is missing its immutable "
                        "path, size, modification time, or identity snapshot."
                    )
                frozen.append({**item, "_process_snapshot": snapshot})
            return frozen

        resume_batch_id = str(payload.get("resume_batch_id") or "")
        if process_mode and resume_batch_id:
            active_ids = {str(item["batch_id"]) for item in active}
            if resume_batch_id not in active_ids:
                return {
                    "contract_version": CONTRACT_VERSION,
                    "action": "prepare_selected",
                    "status": "resume_batch_unavailable",
                    "batch_id": resume_batch_id,
                    "prepared_sources": [],
                    "message": "The exact resumable preparation batch is no longer available.",
                }
            batch_id = resume_batch_id
            selected = freeze_process_selection(
                _batch_sources(connection, batch_id)
            )
            package_row = connection.execute(
                "SELECT package_path FROM inbox_batches WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
            if package_row is None:
                raise RuntimeError("The exact resumable preparation batch disappeared.")
            batch_root = Path(str(package_row[0]))
        elif process_mode:
            locally_actionable = [
                item
                for item in active
                if str(item.get("status") or "")
                not in {
                    "awaiting_external_review",
                    "targeted_evidence_ready",
                    "needs_manual_review",
                }
            ]
            if locally_actionable:
                return {
                    "contract_version": CONTRACT_VERSION,
                    "action": "prepare_selected",
                    "status": "local_work_pending",
                    "pending_batches": locally_actionable,
                    "prepared_sources": [],
                    "message": "Existing local Review Media Inbox work must be resolved before another batch is created.",
                }
            requested_ids = [int(value) for value in payload.get("selected_source_ids") or []]
            inventory_by_id = {
                int(item["source_id"]): item
                for item in scan_result.get("sources") or []
                if isinstance(item, dict) and item.get("source_id") is not None
            }
            selected = []
            for source_id in requested_ids:
                item = inventory_by_id.get(source_id)
                if item is None:
                    raise RuntimeError(f"Selected source {source_id} is no longer present in the current eligible inventory.")
                if str(item.get("classification") or "") not in review_inbox.ELIGIBLE_STATES or bool(item.get("pending_batch_excluded")):
                    raise RuntimeError(f"Selected source {source_id} is no longer eligible for preparation.")
                selected.append(item)
            if not selected:
                return {
                    "contract_version": CONTRACT_VERSION,
                    "action": "prepare_selected",
                    "status": "nothing_eligible",
                    "pending_batches": active,
                    "prepared_sources": [],
                }
            selected = freeze_process_selection(selected)
            preallocated_batch_id = str(payload.get("preallocated_batch_id") or "").strip()
            if not preallocated_batch_id:
                raise ValueError("preallocated_batch_id is required for Process-mode preparation.")
            batch_id = _create_batch(
                connection,
                batches_root / preallocated_batch_id,
                selected,
                batch_id=preallocated_batch_id,
            )
            batch_root = batches_root / batch_id
        elif active:
            if not resume_batch_id or resume_batch_id not in {str(item["batch_id"]) for item in active}:
                return {
                    "contract_version": CONTRACT_VERSION,
                    "action": "prepare",
                    "status": "pending_batch_limit_reached",
                    "pending_batches": active,
                    "prepared_sources": [],
                    "message": "An unfinalized Review Media Inbox batch already exists; no second batch was created.",
                }
            batch_id = resume_batch_id
            selected = _batch_sources(connection, batch_id)
            batch_root = batches_root / batch_id
        else:
            selected = list(scan_result["selected_sources"])
            if not selected:
                return {"contract_version": CONTRACT_VERSION, "action": "prepare", "status": "nothing_eligible", "pending_batches": [], "prepared_sources": []}
            batch_id_placeholder = f"pending-{uuid.uuid4().hex}"
            batch_root_placeholder = batches_root / batch_id_placeholder
            batch_id = _create_batch(connection, batch_root_placeholder, selected)
            batch_root = batches_root / batch_id
            connection.execute("UPDATE inbox_batches SET package_path = ?, updated_utc = ? WHERE batch_id = ?", (str(batch_root), _utc_now(), batch_id))
            connection.commit()
        batch_root.mkdir(parents=True, exist_ok=True)
        (batch_root / "sources").mkdir(exist_ok=True)
        (batch_root / "logs").mkdir(exist_ok=True)
        (batch_root / ".staging").mkdir(exist_ok=True)
        recovery_actions = recover_staging(batch_root, scratch_root)
        live_attempts = [
            item
            for item in recovery_actions
            if str(item.get("classification") or "") == "still_live"
        ]
        if live_attempts:
            raise RuntimeError(
                "Another live preparation attempt still owns this batch; "
                "no recovery work was started."
            )

        def recovery_attempt_id(item: dict[str, Any]) -> int:
            token = str(item.get("attempt") or "")
            try:
                return int(token.rsplit("-", 1)[1])
            except (IndexError, ValueError):
                return 0

        def recovery_work_root(item: dict[str, Any]) -> Path | None:
            value = str(item.get("working_copy_path") or "").strip()
            if not value:
                return None
            working = Path(value)
            candidate = working.parent.parent
            expected_root = scratch_root / "review-inbox" / batch_id
            if not _is_within(scratch_root, working) or not _is_within(
                expected_root, candidate
            ):
                return None
            return candidate

        reusable_by_source: dict[int, dict[str, Any]] = {}
        for item in recovery_actions:
            if str(item.get("classification") or "") != "stale_reusable":
                continue
            try:
                source_id = int(item.get("source_id"))
            except (TypeError, ValueError):
                continue
            prior = reusable_by_source.get(source_id)
            if prior is None or recovery_attempt_id(item) > recovery_attempt_id(prior):
                reusable_by_source[source_id] = item

        # Keep at most one verified stale working copy per resumable source.
        # Complete, invalid, restart-required, and superseded copies are
        # bounded scratch artifacts and are removed before any new copy starts.
        chosen_attempts = {
            str(item.get("attempt") or "")
            for item in reusable_by_source.values()
        }
        chosen_work_roots = {
            os.path.normcase(str(root.resolve()))
            for root in (
                recovery_work_root(item)
                for item in reusable_by_source.values()
            )
            if root is not None
        }
        for item in recovery_actions:
            attempt_id = recovery_attempt_id(item)
            classification = str(item.get("classification") or "")
            chosen = str(item.get("attempt") or "") in chosen_attempts
            if attempt_id > 0 and classification in {
                "stale_reusable",
                "stale_restart_required",
                "invalid_restart_required",
            }:
                connection.execute(
                    """
                    UPDATE inbox_attempts
                    SET status = ?, completed_utc = ?, error_message = ?
                    WHERE attempt_id = ? AND status = 'preparing'
                    """,
                    (
                        "recovered_reused" if chosen else "recovered_restart_required",
                        _utc_now(),
                        (
                            "A verified stale working copy was adopted by a new attempt."
                            if chosen
                            else "Stale scratch state was removed before a bounded retry."
                        ),
                        attempt_id,
                    ),
                )
        # 224 (Wave B2a, note 5): an attempt that ended (a crash, a power cut) after it started but before its
        # first state file has nothing for recover_staging to find. No live attempt owns this batch (checked
        # above), so every attempt of it still "preparing" is one of those, and is closed the same way.
        found_attempts = {recovery_attempt_id(item) for item in recovery_actions}
        orphaned = [
            int(row[0])
            for row in connection.execute(
                "SELECT attempt_id FROM inbox_attempts WHERE batch_id = ? AND attempt_type = 'prepare' "
                "AND status = 'preparing' ORDER BY attempt_id",
                (batch_id,),
            ).fetchall()
            if int(row[0]) not in found_attempts
        ]
        for orphaned_id in orphaned:
            connection.execute(
                "UPDATE inbox_attempts SET status = 'recovered_restart_required', completed_utc = ?, error_message = ? "
                "WHERE attempt_id = ? AND status = 'preparing'",
                (_utc_now(), "The attempt ended before it wrote its state; its scratch was removed before a bounded "
                             "retry.", orphaned_id),
            )
        # 224 (Wave B1): the attempts are closed in one short commit, and the stale scratch copies are removed
        # after it, never inside it. A crash in between repeats nothing: the update only touches attempts still
        # "preparing", and the next run finds the same stale folders again.
        connection.commit()
        staging_root = batch_root / ".staging"
        for item in recovery_actions:
            attempt_name = str(item.get("attempt") or "")
            if attempt_name and str(item.get("classification") or "") in {
                "stale_reusable", "stale_restart_required", "invalid_restart_required"
            }:
                # 224 (Wave B2a, note 5): the half-built package of an attempt that ended after its copy. A new
                # attempt always builds its own.
                stage_package = staging_root / attempt_name / "source"
                if stage_package.exists():
                    _tidy(staging_root, stage_package, leftovers, cleanup_warnings)
            if attempt_name in chosen_attempts:
                continue
            old_root = recovery_work_root(item)
            if (
                old_root is not None
                and os.path.normcase(str(old_root.resolve())) not in chosen_work_roots
                and old_root.exists()
            ):
                _tidy(scratch_root, old_root, leftovers, cleanup_warnings)
                _prune_empty_parents(scratch_root, old_root.parent)
        for orphaned_id in orphaned:
            orphaned_stage = staging_root / f"attempt-{orphaned_id}"
            if orphaned_stage.exists():
                _tidy(staging_root, orphaned_stage, leftovers, cleanup_warnings)
            orphaned_scratch = scratch_root / "review-inbox" / batch_id / f"attempt-{orphaned_id}"
            if orphaned_scratch.exists():
                _tidy(scratch_root, orphaned_scratch, leftovers, cleanup_warnings)
                _prune_empty_parents(scratch_root, orphaned_scratch.parent)
        prior_elapsed_seconds = max(0.0, float(payload.get("prior_elapsed_seconds") or 0.0)) if process_mode else 0.0
        started = float(clock()) - prior_elapsed_seconds
        prepared: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        skipped_by_operator: list[dict[str, Any]] = []
        stopped_reason = ""
        source_total = len(selected)
        progress("Preparing batch", source_total=source_total, source_state="waiting", activity=f"Queued {source_total} source(s) for bounded preparation")
        for source_index, selection in enumerate(selected, start=1):
            if process_mode and stop_requested():
                stopped_reason = "cooperative_stop_after_current_source"
                break
            if prepared or blocked or failures:
                if process_mode and (blocked or failures):
                    stopped_reason = (
                        "needs_audio_confirmation"
                        if blocked
                        else str(failures[-1].get("state") or "source_requires_attention")
                    )
                    break
                elapsed_minutes = (float(clock()) - started) / 60.0
                if elapsed_minutes >= float(scan_result["settings"]["max_duration_minutes"]):
                    stopped_reason = "soft_duration_boundary"
                    break
                if stop_requested():
                    stopped_reason = "cooperative_stop_after_current_source"
                    break
            source_id = int(selection["source_id"])
            source_record = _source_from_ledger(connection, source_id)
            process_snapshot = (
                dict(selection.get("_process_snapshot") or {})
                if process_mode
                and isinstance(selection.get("_process_snapshot"), dict)
                else {}
            )
            source = Path(
                str(
                    process_snapshot.get("path")
                    or source_record["original_path"]
                )
            )
            source_name = source.name
            attempt_id = _attempt_start(connection, source_id, batch_id, settings_hash)
            attempt_token = f"attempt-{attempt_id}"
            stage_root = batch_root / ".staging" / attempt_token
            package_stage = stage_root / "source"
            scratch_suffix = source.suffix.lower() or ".media"
            reusable_action = reusable_by_source.pop(source_id, None)
            if reusable_action is not None:
                working_copy = Path(str(reusable_action["working_copy_path"]))
                working_root = working_copy.parent.parent
            else:
                working_root = scratch_root / "review-inbox" / batch_id / attempt_token
                working_copy = working_root / "source" / f"source{scratch_suffix}"
            _require_within(batch_root, stage_root, "Package staging path")
            _require_within(scratch_root, working_root, "Working-copy path")
            stage_root.mkdir(parents=True, exist_ok=True)
            state_path = stage_root / "attempt-state.json"
            skip_watch["source"] = source
            try:
                progress("Validating source", source_name=source_name, source_index=source_index, source_total=source_total, prepared_count=len(prepared), blocked_count=len(blocked), failed_count=len(failures), activity="Rechecking source stability and media metadata")
                before = source.stat()
                if process_mode:
                    recorded_size = int(process_snapshot["size_bytes"])
                    recorded_modified_ns = int(process_snapshot["modified_ns"])
                    if (
                        before.st_size != recorded_size
                        or before.st_mtime_ns != recorded_modified_ns
                    ):
                        raise SourceChangedError(
                            "Source size or modification time changed after the Process workload snapshot was recorded."
                        )
                def checking(phase: str, words: str) -> Callable[[float, float], None]:
                    # 224 (Wave B2a, 5a): real progress while the video is checked; a Skip stops the check. With
                    # no known length (a recording cut off by a crash) it says how far, with no percent.
                    def report(at: float, length: float) -> None:
                        if length > 0:
                            total_seconds = max(1, int(math.ceil(length)))
                            done = max(0, min(total_seconds, int(at)))
                            activity = (f"{words}: {voice_track.clock(done)} of {voice_track.clock(length)} "
                                        f"checked ({done * 100 // total_seconds}%)")
                            work: tuple[int, int, str] | None = (done, total_seconds, "seconds")
                        else:
                            activity, work = f"{words}: {voice_track.clock(at)} checked", None
                        progress(phase, source_name=source_name, source_index=source_index, source_total=source_total,
                                 prepared_count=len(prepared), blocked_count=len(blocked), failed_count=len(failures),
                                 activity=activity, work=work)

                    return report

                render_report["call"] = checking("Rendering neutral visuals",
                                                 "Checking the video again, picture by picture")
                media = probe(source, on_report=checking("Validating source", "Checking the video"))
                video = media["video_streams"][0] if media.get("video_streams") else {}
                detected_panels = panel_layout.detect_three_panel_layout(int(video.get("width") or 0), int(video.get("height") or 0))["panels"]
                panel_count = 0 if process_mode else len(detected_panels)
                progress("Checking storage", source_name=source_name, source_index=source_index, source_total=source_total, prepared_count=len(prepared), blocked_count=len(blocked), failed_count=len(failures), activity="Validating scratch and retained-output capacity")
                storage = estimate_storage(before.st_size, float(media.get("duration_seconds") or 0.0), timeline_frame_count(float(media.get("duration_seconds") or 0.0)), panel_count)
                scratch_free = int(space_probe(scratch_root))
                retained_free = int(space_probe(inbox_root))
                if scratch_free < storage["scratch_required_bytes"] or retained_free < storage["retained_required_bytes"]:
                    raise RuntimeError(f"Insufficient storage before copy: scratch {scratch_free}/{storage['scratch_required_bytes']} bytes; retained {retained_free}/{storage['retained_required_bytes']} bytes.")
                progress(
                    "Inspecting audio",
                    source_name=source_name,
                    source_index=source_index,
                    source_total=source_total,
                    prepared_count=len(prepared),
                    blocked_count=len(blocked),
                    failed_count=len(failures),
                    activity=(
                        "Checking bounded regions and, when needed, decoding "
                        "complete audio streams before any track choice"
                    ),
                )
                inspected = audibility_inspector(
                    source,
                    media,
                    working_root / "audibility-inspection",
                )
                if isinstance(inspected, SourceAudioInspection):
                    audio_audibility = inspected.audibility_manifest()
                elif isinstance(inspected, dict):
                    audio_audibility = dict(inspected)
                else:
                    raise RuntimeError(
                        "Audio audibility inspection did not return a valid record."
                    )
                if int(audio_audibility.get("contract_version") or 0) != AUDIBILITY_CONTRACT_VERSION:
                    raise RuntimeError(
                        "Audio audibility inspection returned an unsupported contract."
                    )
                _validate_audibility_mapping(media, audio_audibility)
                media = dict(media)
                media["audio_audibility"] = audio_audibility
                after_audio_inspection = source.stat()
                if (
                    after_audio_inspection.st_size != before.st_size
                    or after_audio_inspection.st_mtime_ns != before.st_mtime_ns
                ):
                    raise SourceChangedError(
                        "Source changed while complete audio audibility was inspected."
                    )
                selection_info = _audio_selection(media, confirmations, speech_facts.confirmed_track(source))
                detection: dict[str, Any] | None = None
                kept_narration_wav: Path | None = None
                if selection_info["state"] == "needs_audio_confirmation" and voice_detector is not None:
                    # 264: the stored automatic pick answers first; only then does the Inbox listen.
                    # Your answer got its say in ``_audio_selection``: it is not here only when that track is silent.
                    known = speech_facts.narration_answer(source, track_roles=payload.get("track_roles"))
                    if known.final and known.detection is not None and known.decided_by != speech_facts.DECIDED_CONFIRMED:
                        detection = dict(known.detection)
                    else:
                        progress("Finding your voice", source_name=source_name, source_index=source_index, source_total=source_total, prepared_count=len(prepared), blocked_count=len(blocked), failed_count=len(failures), activity="Choosing the narration track the way every feature does")
                        detection = dict(voice_detector(source, working_root / "voice-track", working_root / "voice-track-kept") or {})
                    chosen = detection.get("selected_ordinal") if detection.get("status") == "selected" else None
                    stream = next((item for item in media["audio_streams"] if chosen is not None and int(item["ordinal"]) == int(chosen)), None)
                    if stream is not None:
                        selection_info = {
                            "state": "voice-detected",
                            "selected_ordinal": int(stream["ordinal"]),
                            "selected_ffmpeg_map": str(stream["ffmpeg_map"]),
                            "confirmation_source": str(detection.get("explanation") or "the shared voice detection"),
                            "decided_by": str(detection.get("decided_by") or ""),
                        }
                        kept = next((item for item in detection.get("kept_track_wavs") or [] if int(item.get("ordinal", -1)) == int(stream["ordinal"])), None)
                        kept_narration_wav = Path(str(kept["path"])) if kept else None
                if selection_info["state"] == "audibility_inconclusive":
                    raise AudioAudibilityInconclusiveError(
                        "Audio audibility is inconclusive after bounded and "
                        "complete-stream decoding. No track was selected."
                    )
                if selection_info["state"] == "no_audible_narration":
                    progress(
                        "No audible narration",
                        source_name=source_name,
                        source_index=source_index,
                        source_total=source_total,
                        prepared_count=len(prepared),
                        blocked_count=len(blocked),
                        failed_count=len(failures),
                        activity=(
                            "No audible narration; speech transcription will "
                            "be skipped and visual evidence will continue"
                        ),
                    )
                if selection_info["state"] == "needs_audio_confirmation":
                    _set_state(
                        connection,
                        source_id,
                        batch_id,
                        "needs_audio_confirmation",
                        details={
                            "layout_fingerprint": media[
                                "audio_layout_fingerprint"
                            ],
                            "audio_audibility_state": audio_audibility.get(
                                "source_state"
                            ),
                            "audibility_contract_version": (
                                AUDIBILITY_CONTRACT_VERSION
                            ),
                        },
                    )
                    _attempt_finish(connection, attempt_id, "needs_audio_confirmation", "Exact operator-confirmed multi-track mapping is required.")
                    blocked.append(
                        {
                            "source_id": source_id,
                            "source_name": source.name,
                            "source_path": str(source),
                            "state": "needs_audio_confirmation",
                            "reason": "More than one audio track could contain the operator microphone.",
                            "layout_fingerprint": media["audio_layout_fingerprint"],
                            "audio_streams": media["audio_streams"],
                            "audio_audibility": audio_audibility,
                            "audio_audibility_state": audio_audibility.get(
                                "source_state"
                            ),
                            "audibility_contract_version": (
                                AUDIBILITY_CONTRACT_VERSION
                            ),
                        }
                    )
                    _atomic_json(state_path, {"status": "needs_audio_confirmation", "process_id": os.getpid(), "source_id": source_id, "audio": selection_info})
                    skip_watch["source"] = None
                    progress("Audio confirmation required", source_name=source_name, source_index=source_index, source_total=source_total, source_state="waiting", source_terminal=True, prepared_count=len(prepared), blocked_count=len(blocked), failed_count=len(failures), activity="Source paused until its narration track is confirmed")
                    continue
                _set_state(connection, source_id, batch_id, "preparing")
                _atomic_json(state_path, {"status": "preparing", "process_id": os.getpid(), "source_id": source_id, "working_copy_path": str(working_copy), "expected_size": before.st_size, "expected_sha256": str(source_record.get("content_sha256") or "")})
                # 224 (Wave B1): "preparing" is committed before the recording is copied and hashed, so no
                # write transaction is open across the copy (it can take minutes). The attempt-state file is
                # written first, so a committed "preparing" always has one: after a crash the next run's
                # recovery (recover_staging) closes the attempt from it and picks the source up again.
                connection.commit()
                progress("Copying and hashing", source_name=source_name, source_index=source_index, source_total=source_total, prepared_count=len(prepared), blocked_count=len(blocked), failed_count=len(failures), activity="Streaming a verified scratch copy while measuring full SHA-256")
                if reusable_action is not None:
                    recovered_size = int(reusable_action.get("expected_size") or -1)
                    recovered_sha = str(
                        reusable_action.get("expected_sha256") or ""
                    ).lower()
                    if (
                        not working_copy.is_file()
                        or working_copy.stat().st_size != recovered_size
                        or recovered_size != before.st_size
                        or not recovered_sha
                        or review_ledger.sha256_file(working_copy) != recovered_sha
                    ):
                        raise SourceChangedError(
                            "The verified recovery working copy changed before it could be adopted."
                        )
                    copy_result = {
                        "sha256": recovered_sha,
                        "bytes_copied": recovered_size,
                        "before": {
                            "size_bytes": before.st_size,
                            "modified_ns": before.st_mtime_ns,
                        },
                        "after": {
                            "size_bytes": before.st_size,
                            "modified_ns": before.st_mtime_ns,
                        },
                        "recovered_verified_copy": True,
                    }
                else:
                    copy_result = copier(source, working_copy)
                full_sha = str(copy_result["sha256"]).lower()
                after_copy = source.stat()
                if before.st_size != after_copy.st_size or before.st_mtime_ns != after_copy.st_mtime_ns:
                    raise SourceChangedError("Source changed while its preparation copy was produced.")
                if not working_copy.is_file() or working_copy.stat().st_size != before.st_size:
                    raise SourceChangedError("Working-copy size validation failed after streaming copy.")
                measured_working_sha = review_ledger.sha256_file(working_copy)
                if measured_working_sha != full_sha:
                    raise SourceChangedError("Working-copy SHA-256 validation failed after streaming copy.")
                if process_mode:
                    snapshot_sampled_sha = str(
                        process_snapshot.get("sampled_sha256") or ""
                    ).lower()
                    if (
                        snapshot_sampled_sha
                        and review_inbox.sampled_sha256_file(working_copy)
                        != snapshot_sampled_sha
                    ):
                        raise SourceChangedError(
                            "Verified working-copy sample does not match the "
                            "fixed Process workload snapshot."
                        )
                    snapshot_content_sha = str(
                        process_snapshot.get("content_sha256") or ""
                    ).lower()
                    if snapshot_content_sha and full_sha != snapshot_content_sha:
                        raise SourceChangedError(
                            "Verified working-copy SHA-256 does not match the "
                            "fixed Process workload snapshot."
                        )
                    snapshot_identity = str(
                        process_snapshot.get("identity") or ""
                    )
                    if (
                        str(process_snapshot.get("identity_kind") or "")
                        == "stable"
                        and review_ledger.stable_identity(full_sha)
                        != snapshot_identity
                    ):
                        raise SourceChangedError(
                            "Verified working-copy identity does not match the "
                            "fixed Process workload snapshot."
                        )
                _atomic_json(state_path, {"status": "preparing", "process_id": os.getpid(), "source_id": source_id, "working_copy_path": str(working_copy), "expected_size": int(copy_result["bytes_copied"]), "expected_sha256": full_sha, "copy_validated": True})
                known_sha = str(source_record.get("content_sha256") or "").lower()
                if known_sha and known_sha != full_sha:
                    raise SourceChangedError("Verified working-copy SHA-256 does not match the ledger identity.")
                signature_contract = {
                    "schema_version": 1,
                    "content_sha256": full_sha,
                    "audio_layout_fingerprint": str(media["audio_layout_fingerprint"]),
                    "selected_audio_ordinal": selection_info["selected_ordinal"],
                    "audio_audibility_contract_version": (
                        AUDIBILITY_CONTRACT_VERSION
                    ),
                    "audio_audibility_state": str(
                        audio_audibility.get("source_state") or ""
                    ),
                    "whisper_model": str(payload.get("whisper_model") or "base.en"),
                    "language_code": str(payload.get("language_code") or ""),
                    "narration_speech_mode": str(payload.get("narration_speech_mode") or "Auto"),
                    "preparation_contract_version": CONTRACT_VERSION,
                    # 224: the ledger's structure version when packages were first signed. It stays 2 when the
                    # records move into the library, so a package prepared before the move is not taken for
                    # a changed one.
                    "ledger_schema_version": PREPARATION_SIGNATURE_LEDGER_VERSION,
                }
                preparation_signature = hashlib.sha256(json.dumps(signature_contract, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
                connection.execute("UPDATE inbox_sources SET stable_identity = ?, content_sha256 = ?, size_bytes = ?, updated_utc = ? WHERE source_id = ?", (review_ledger.stable_identity(full_sha), full_sha, int(copy_result["bytes_copied"]), _utc_now(), source_id))
                connection.execute("UPDATE inbox_batch_sources SET preparation_signature = ?, updated_utc = ? WHERE batch_id = ? AND source_id = ?", (preparation_signature, _utc_now(), batch_id, source_id))
                connection.commit()
                identity = review_ledger.stable_identity(full_sha)
                token = _source_token(identity)
                final_source_root = batch_root / "sources" / token
                if final_source_root.exists():
                    # Atomic promotion intentionally precedes ledger mutation.
                    # If the prior process died in that narrow window, validate
                    # and reconcile the exact promoted package instead of
                    # treating it as a duplicate or rendering it again.
                    _validate_source_package(final_source_root)
                    promoted_manifest_path = (
                        final_source_root / "source-manifest.json"
                    )
                    promoted_manifest = json.loads(
                        promoted_manifest_path.read_text(encoding="utf-8")
                    )
                    promoted_copy = (
                        promoted_manifest.get("copy_validation")
                        if isinstance(promoted_manifest, dict)
                        else None
                    )
                    if (
                        not isinstance(promoted_manifest, dict)
                        or int(promoted_manifest.get("source_id") or 0) != source_id
                        or str(promoted_manifest.get("source_identity") or "")
                        != identity
                        or int(promoted_manifest.get("original_size_bytes") or -1)
                        != before.st_size
                        or int(promoted_manifest.get("original_modified_ns") or -1)
                        != before.st_mtime_ns
                        or not isinstance(promoted_copy, dict)
                        or str(promoted_copy.get("sha256") or "").lower()
                        != full_sha
                        or str(
                            promoted_manifest.get("preparation_signature") or ""
                        )
                        != preparation_signature
                    ):
                        raise RuntimeError(
                            "An existing promoted source package does not match "
                            "the exact source identity being recovered."
                        )
                    promoted_audio = promoted_manifest.get("audio_selection")
                    promoted_audio_state = (
                        str(promoted_audio.get("state") or "")
                        if isinstance(promoted_audio, dict)
                        else ""
                    )
                    _set_state(
                        connection,
                        source_id,
                        batch_id,
                        "prepared",
                        details={
                            "source_token": token,
                            "sha256": full_sha,
                            "recovered_promoted_package": True,
                        },
                    )
                    _attempt_finish(
                        connection,
                        attempt_id,
                        "prepared",
                        "Reconciled an integrity-valid package promoted before a prior crash.",
                    )
                    _atomic_json(
                        state_path,
                        {
                            "status": "prepared",
                            "process_id": os.getpid(),
                            "source_id": source_id,
                            "working_copy_path": str(working_copy),
                            "expected_size": int(copy_result["bytes_copied"]),
                            "expected_sha256": full_sha,
                            "recovered_promoted_package": True,
                        },
                    )
                    prepared.append(
                        {
                            "source_id": source_id,
                            "source_identity": identity,
                            "source_token": token,
                            "package_path": str(final_source_root),
                            "audio_state": promoted_audio_state,
                            "recovered_promoted_package": True,
                        }
                    )
                    progress(
                        "Source prepared",
                        source_name=source_name,
                        source_index=source_index,
                        source_total=source_total,
                        source_state="completed",
                        source_terminal=True,
                        prepared_count=len(prepared),
                        blocked_count=len(blocked),
                        failed_count=len(failures),
                        activity="Recovered an integrity-valid promoted package",
                    )
                    continue
                for name in ("transcript", "media", "visuals", "hints"):
                    (package_stage / name).mkdir(parents=True, exist_ok=True)
                transcript_result: dict[str, Any]
                if selection_info["selected_ordinal"] is None:
                    if selection_info["state"] == "no_audible_narration":
                        transcript_result = {
                            "status": "not_applicable_no_audible_narration",
                            "segments_count": 0,
                            "transcription_skipped": True,
                            "warning": (
                                "Every complete decoded audio stream was silent "
                                "or below the conservative codec-noise floor. "
                                "No speech transcript was attempted; visual "
                                "preparation continued."
                            ),
                        }
                    else:
                        transcript_result = {
                            "status": "not_applicable_no_audio",
                            "segments_count": 0,
                            "transcription_skipped": True,
                            "warning": (
                                "Source contains no audio stream; visual "
                                "preparation continued."
                            ),
                        }
                    _atomic_json(package_stage / "transcript" / "transcript-status.json", transcript_result)
                else:
                    progress("Transcribing", source_name=source_name, source_index=source_index, source_total=source_total, prepared_count=len(prepared), blocked_count=len(blocked), failed_count=len(failures), activity="Extracting confirmed narration audio and creating a local transcript")
                    extracted_audio = working_root / "audio" / "selected-audio.wav"
                    if kept_narration_wav is not None and kept_narration_wav.is_file():
                        # 214: the voice detection already read this track; it is not read again.
                        extracted_audio.parent.mkdir(parents=True, exist_ok=True)
                        # A reused working copy may still hold the audio an earlier attempt decoded.
                        safe_write.remove(extracted_audio, wait=safe_write.INBOX_WAIT_SECONDS)
                        safe_write.move(kept_narration_wav, extracted_audio)
                    else:
                        audio_extractor(working_copy, int(selection_info["selected_ordinal"]), extracted_audio)
                    transcript_result = transcriber(extracted_audio, package_stage / "transcript", payload)
                    if line_checker is not None and transcript_result.get("json_path"):
                        progress("Checking the transcript", source_name=source_name, source_index=source_index, source_total=source_total, prepared_count=len(prepared), blocked_count=len(blocked), failed_count=len(failures), activity="Dropping lines another track carries or the microphone did not hear")
                        checked = line_checker({
                            "source_path": str(working_copy),
                            "ffmpeg_exe": ffmpeg_value,
                            "transcript_json_path": str(transcript_result["json_path"]),
                            "detection": detection or _detection_for_filters(media, audio_audibility, selection_info, setting_roles),
                            "model_name": str(payload.get("whisper_model") or "base.en"),
                            "prefer_gpu": bool(payload.get("prefer_gpu", True)),
                            "language_code": str(payload.get("language_code") or "en"),
                        })
                        transcript_result = {
                            **transcript_result,
                            "lines_dropped": [dict(item) for item in checked.get("dropped") or []],
                            "compared_tracks": list(checked.get("compared_tracks") or []),
                        }
                    transcript_result = {
                        **transcript_result,
                        "status": _transcript_result_status(transcript_result),
                    }
                    if transcript_result["status"] != "complete":
                        transcript_result["warning"] = _transcript_result_warning(transcript_result)
                progress(
                    "Rendering neutral visuals",
                    source_name=source_name,
                    source_index=source_index,
                    source_total=source_total,
                    prepared_count=len(prepared),
                    blocked_count=len(blocked),
                    failed_count=len(failures),
                    activity=(
                        "Rendering sparse timeline frames; panel crops remain available by bounded request"
                        if process_mode
                        else "Rendering sparse timeline frames and supported panel crops"
                    ),
                )
                visuals = renderer(working_copy, media, package_stage / "visuals")
                if not isinstance(visuals, dict):
                    raise RuntimeError("Visual preparation did not return a valid manifest.")
                visuals = dict(visuals)
                visuals.setdefault("panels", [])
                visuals.setdefault("supported_panel_ids", [str(panel["role"]) for panel in detected_panels])
                (package_stage / "hints" / "README.txt").write_text("Neutral navigation hints only. No semantic decisions were made.\n", encoding="utf-8")
                manifest_media = dict(media)
                frame_times = [
                    float(value)
                    for value in manifest_media.pop("video_frame_timestamps", []) or []
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                ]
                manifest_media["video_timeline_basis"] = {
                    "decodable_frame_count": len(frame_times),
                    "first_decodable_timestamp_seconds": (
                        frame_times[0] if frame_times else None
                    ),
                    "last_decodable_timestamp_seconds": (
                        frame_times[-1] if frame_times else None
                    ),
                }
                manifest = {
                    "schema_version": 1,
                    "source_id": source_id,
                    "source_identity": identity,
                    "source_token": token,
                    "original_location": str(source),
                    "original_size_bytes": before.st_size,
                    "original_modified_ns": before.st_mtime_ns,
                    "copy_validation": copy_result,
                    "media_metadata": manifest_media,
                    "audio_selection": selection_info,
                    "transcription": transcript_result,
                    "visuals": visuals,
                    "storage_gate": storage | {"scratch_free_bytes": scratch_free, "retained_free_bytes": retained_free},
                    "preparation_settings_hash": settings_hash,
                    "preparation_signature": preparation_signature,
                    "preparation_signature_contract": signature_contract,
                    "prepared_utc": _utc_now(),
                }
                progress("Validating integrity", source_name=source_name, source_index=source_index, source_total=source_total, prepared_count=len(prepared), blocked_count=len(blocked), failed_count=len(failures), activity="Hashing prepared artifacts before promotion")
                _complete_source_package(package_stage, manifest)
                # Past this point the package is promoted, so a skip no longer applies.
                skip_watch["source"] = None
                progress("Promoting package", source_name=source_name, source_index=source_index, source_total=source_total, prepared_count=len(prepared), blocked_count=len(blocked), failed_count=len(failures), activity="Atomically promoting the validated source package")
                safe_write.move(package_stage, final_source_root)
                _set_state(connection, source_id, batch_id, "prepared", details={"source_token": token, "sha256": full_sha})
                _attempt_finish(connection, attempt_id, "prepared")
                _atomic_json(state_path, {"status": "prepared", "process_id": os.getpid(), "source_id": source_id, "working_copy_path": str(working_copy), "expected_size": int(copy_result["bytes_copied"]), "expected_sha256": full_sha})
                prepared.append({"source_id": source_id, "source_identity": identity, "source_token": token, "package_path": str(final_source_root), "audio_state": selection_info["state"], "transcript_status": str(transcript_result.get("status") or "")})
                prepared_activity = "Prepared source passed integrity checks"
                if transcript_result.get("status") in {"unusable_quality_blocked", "no_narration_found"}:
                    prepared_activity = "Prepared, but " + str(transcript_result.get("warning") or "the transcript is not usable narration")
                progress("Source prepared", source_name=source_name, source_index=source_index, source_total=source_total, source_state="completed", source_terminal=True, prepared_count=len(prepared), blocked_count=len(blocked), failed_count=len(failures), activity=prepared_activity)
            except SkippedByOperatorError as exc:
                # 214: not a failure. The recording goes back to waiting, for a later run.
                _set_state(connection, source_id, batch_id, "pending", details={"reason": "skipped_by_operator"})
                _attempt_finish(connection, attempt_id, "skipped_by_operator", str(exc))
                skipped_by_operator.append({"source_id": source_id, "source_name": source_name, "source_path": str(source)})
                progress("Skipped by you", source_name=source_name, source_index=source_index, source_total=source_total, source_state="skipped", source_terminal=True, prepared_count=len(prepared), blocked_count=len(blocked), failed_count=len(failures), activity=str(exc))
            except AudioAudibilityInconclusiveError as exc:
                # 224 (Wave B2a, note 6): a Skip arriving while the failure is reported never ends the run.
                skip_watch["source"] = None
                _set_state(
                    connection,
                    source_id,
                    batch_id,
                    "retryable_failure",
                    details={
                        "error": str(exc),
                        "attention_code": "audio_audibility_inconclusive",
                    },
                )
                _attempt_finish(
                    connection,
                    attempt_id,
                    "retryable_failure",
                    str(exc),
                )
                failures.append(
                    {
                        "source_id": source_id,
                        "state": "retryable_failure",
                        "attention_code": "audio_audibility_inconclusive",
                        "error": str(exc),
                    }
                )
                progress(
                    "Audio needs attention",
                    source_name=source_name,
                    source_index=source_index,
                    source_total=source_total,
                    source_state="failed",
                    source_terminal=True,
                    prepared_count=len(prepared),
                    blocked_count=len(blocked),
                    failed_count=len(failures),
                    activity=(
                        "Audio could not be classified safely; no track was "
                        "selected"
                    ),
                )
            except SourceChangedError as exc:
                skip_watch["source"] = None
                if not process_mode:
                    connection.execute(
                        "UPDATE inbox_source_locations SET modified_ns = NULL "
                        "WHERE source_id = ? AND is_current = 1",
                        (source_id,),
                    )
                    connection.commit()
                _set_state(connection, source_id, batch_id, "source_changed", details={"error": str(exc)})
                _attempt_finish(connection, attempt_id, "source_changed", str(exc))
                failures.append({"source_id": source_id, "state": "source_changed", "error": str(exc)})
                progress("Source changed", source_name=source_name, source_index=source_index, source_total=source_total, source_state="failed", source_terminal=True, prepared_count=len(prepared), blocked_count=len(blocked), failed_count=len(failures), activity=str(exc))
            except Exception as exc:
                skip_watch["source"] = None
                _set_state(connection, source_id, batch_id, "retryable_failure", details={"error": str(exc)})
                _attempt_finish(connection, attempt_id, "retryable_failure", str(exc))
                failures.append({"source_id": source_id, "state": "retryable_failure", "error": str(exc)})
                progress("Retryable failure", source_name=source_name, source_index=source_index, source_total=source_total, source_state="failed", source_terminal=True, prepared_count=len(prepared), blocked_count=len(blocked), failed_count=len(failures), activity=str(exc))
            finally:
                skip_watch["source"] = None
                if working_root.exists():
                    prepared_ids = {int(item["source_id"]) for item in prepared}
                    blocked_ids = {int(item["source_id"]) for item in blocked}
                    failed_ids = {int(item["source_id"]) for item in failures}
                    skipped_ids = {int(item["source_id"]) for item in skipped_by_operator}
                    cleanup_state = (
                        "skipped"
                        if source_id in skipped_ids
                        else "completed"
                        if source_id in prepared_ids
                        else "waiting"
                        if source_id in blocked_ids
                        else "failed"
                        if source_id in failed_ids
                        else "active"
                    )
                    progress("Cleaning scratch", source_name=source_name, source_index=source_index, source_total=source_total, source_state=cleanup_state, source_terminal=cleanup_state in {"completed", "failed"}, prepared_count=len(prepared), blocked_count=len(blocked), failed_count=len(failures), activity="Removing the verified working copy from bounded scratch storage")
                    held = _tidy(scratch_root, working_root, leftovers, cleanup_warnings)
                    if held:
                        progress("Cleaning scratch", source_name=source_name, source_index=source_index, source_total=source_total, source_state=cleanup_state, source_terminal=cleanup_state in {"completed", "failed"}, prepared_count=len(prepared), blocked_count=len(blocked), failed_count=len(failures), activity=held)
                    _prune_empty_parents(scratch_root, working_root.parent)
        states = [str(row[0]) for row in connection.execute("SELECT state FROM inbox_batch_sources WHERE batch_id = ? ORDER BY ordinal", (batch_id,)).fetchall()]
        all_integrity_complete = bool(states) and all(state in {"prepared", "awaiting_external_review"} for state in states)
        if all_integrity_complete:
            package_rows = connection.execute("SELECT s.stable_identity FROM inbox_batch_sources bs JOIN inbox_sources s ON s.source_id = bs.source_id WHERE bs.batch_id = ? ORDER BY bs.ordinal", (batch_id,)).fetchall()
            for package_row in package_rows:
                stable = str(package_row[0] or "")
                if not stable:
                    raise RuntimeError("Prepared source is missing its stable SHA-256 identity.")
                _validate_source_package(batch_root / "sources" / _source_token(stable))
        existing_manifest: dict[str, Any] = {}
        batch_manifest_path = batch_root / "batch-manifest.json"
        if batch_manifest_path.is_file():
            try:
                existing_manifest = json.loads(batch_manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing_manifest = {}
        merged_prepared = _merge_source_records(list(existing_manifest.get("prepared_sources") or []), prepared)
        prepared_ids = {int(item["source_id"]) for item in merged_prepared}
        merged_blocked = [item for item in _merge_source_records(list(existing_manifest.get("blocked_sources") or []), blocked) if int(item["source_id"]) not in prepared_ids]
        merged_failures = [item for item in _merge_source_records(list(existing_manifest.get("failed_sources") or []), failures) if int(item["source_id"]) not in prepared_ids]
        prospective_status = "awaiting_external_review" if all_integrity_complete else ("needs_audio_confirmation" if any(state == "needs_audio_confirmation" for state in states) else "preparing")
        manifest = {
            "schema_version": 1,
            "batch_id": batch_id,
            "status": prospective_status,
            "bounds": {
                "max_files": scan_result["settings"]["max_files"],
                "concurrency": 1,
                "max_duration_minutes": scan_result["settings"]["max_duration_minutes"],
                "soft_source_boundary": True,
                "duration_meaning": "Once elapsed time reaches the limit, do not start another source; allow the current source to finish safely.",
                "hard_wall_clock": False,
            },
            "prepared_sources": merged_prepared,
            "blocked_sources": merged_blocked,
            "failed_sources": merged_failures,
            "stopped_reason": stopped_reason,
            "updated_utc": _utc_now(),
        }
        if all_integrity_complete:
            manifest["review_materials"] = {
                "readme": "README_FOR_REVIEW.md",
                "codex_prompt": "CODEX_REVIEW_PROMPT.md",
                "preliminary_findings_schema": "preliminary-findings.schema.json",
                "preliminary_findings_template": "preliminary-findings.template.json",
                "preliminary_findings_submission": "preliminary-findings.json",
            }
        _atomic_json(batch_manifest_path, manifest)
        if all_integrity_complete:
            review_findings.write_review_materials(batch_root, manifest)
        with (batch_root / "logs" / "preparation.log").open("a", encoding="utf-8") as log_handle:
            log_handle.write(json.dumps(manifest, sort_keys=True) + "\n")
        if all_integrity_complete:
            prior_batch_status = str(connection.execute("SELECT status FROM inbox_batches WHERE batch_id = ?", (batch_id,)).fetchone()[0])
            now = _utc_now()
            connection.execute("UPDATE inbox_batch_sources SET state = 'awaiting_external_review', updated_utc = ? WHERE batch_id = ?", (now, batch_id))
            connection.execute("UPDATE inbox_sources SET lifecycle_state = 'awaiting_external_review', updated_utc = ? WHERE source_id IN (SELECT source_id FROM inbox_batch_sources WHERE batch_id = ?)", (now, batch_id))
            connection.execute("UPDATE inbox_batches SET status = 'awaiting_external_review', updated_utc = ? WHERE batch_id = ?", (now, batch_id))
            batch_status = "awaiting_external_review"
            if prior_batch_status != batch_status:
                _event(connection, None, batch_id, "batch_integrity_complete", prior_batch_status, batch_status, {"source_count": len(states)})
        else:
            batch_status = "needs_audio_confirmation" if any(state == "needs_audio_confirmation" for state in states) else "preparing"
            connection.execute("UPDATE inbox_batches SET status = ?, updated_utc = ? WHERE batch_id = ?", (batch_status, _utc_now(), batch_id))
        connection.commit()
        progress("Awaiting external review" if batch_status == "awaiting_external_review" else "Batch paused", source_total=source_total, source_state="completed" if batch_status == "awaiting_external_review" else "waiting", prepared_count=len(merged_prepared), blocked_count=len(merged_blocked), failed_count=len(merged_failures), activity="Prepared batch is awaiting external review" if batch_status == "awaiting_external_review" else "Batch remains resumable", terminal_state="succeeded" if batch_status == "awaiting_external_review" else "succeeded_with_warnings")
        result = {
            "contract_version": CONTRACT_VERSION,
            "action": "prepare_selected" if process_mode else "prepare",
            "batch_id": batch_id,
            "batch_path": str(batch_root),
            **manifest,
            "status": batch_status,
            "skipped_by_operator": skipped_by_operator,
            "cleanup_warnings": cleanup_warnings,
        }
        if process_mode:
            result["elapsed_seconds"] = max(0.0, float(clock()) - started)
        return result
    finally:
        connection.close()
