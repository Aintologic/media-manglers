"""Local, explainable operator-narration stream inspection.

The detector intentionally recommends rather than authenticates a speaker.  It
uses container metadata and short PCM samples, and exact saved-layout matches
may reuse a prior human confirmation.  No transcript is produced here.
"""

from __future__ import annotations

from array import array
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import struct
import subprocess
import sys
import time
import wave
from typing import Any, Callable, Iterable


SUPPORTED_MEDIA_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}
SAFE_CONFIDENCE_THRESHOLD = 0.78
SAMPLE_SECONDS = 20.0
ACTIVITY_SCAN_SECONDS = 4.0
MAX_ACTIVITY_SCAN_WINDOWS = 12
AUDIBILITY_CONTRACT_VERSION = 1

# The boundary is deliberately conservative.  Signal at or above either
# audible threshold is retained as meaningful, including quiet speech.  Only
# material below both noise-floor limits is treated as ignorable codec noise.
# Values between the two boundaries are inconclusive and stop preparation.
AUDIBLE_PEAK_DBFS = -72.0
AUDIBLE_RMS_DBFS = -84.0
NOISE_FLOOR_PEAK_DBFS = -78.0
NOISE_FLOOR_RMS_DBFS = -90.0


@dataclass(frozen=True, slots=True)
class AudioStreamInfo:
    ordinal: int
    stream_index: int
    title: str = ""
    language: str = ""
    codec: str = ""
    channels: int = 0
    channel_layout: str = ""
    sample_rate: int = 0
    bit_rate: int = 0

    @property
    def human_track_number(self) -> int:
        return self.ordinal + 1

    @property
    def human_label(self) -> str:
        return f"Track {self.human_track_number}"

    @property
    def ffmpeg_map(self) -> str:
        return f"0:a:{self.ordinal}"


@dataclass(frozen=True, slots=True)
class AudioSampleFeatures:
    speech_activity: float = 0.0
    active_ratio: float = 0.0
    continuity: float = 0.0
    music_noise_likelihood: float = 0.0
    background_likelihood: float = 0.0
    dynamic_range_db: float = 0.0
    zero_crossing_rate: float = 0.0
    rms_db: float = -90.0
    envelope: tuple[float, ...] = ()
    sample_count: int = 0
    nonzero_sample_count: int = 0
    peak_dbfs: float = -120.0
    audibility_state: str = "inconclusive"

    def voice_vector(self) -> tuple[float, ...]:
        return (
            self.speech_activity,
            self.active_ratio,
            self.dynamic_range_db / 60.0,
            self.zero_crossing_rate * 8.0,
            max(0.0, min(1.0, (self.rms_db + 60.0) / 60.0)),
        )

    @property
    def meaningfully_audible(self) -> bool:
        return self.audibility_state == "audible_signal"

    @property
    def silent_candidate(self) -> bool:
        return self.audibility_state in {
            "digital_silence",
            "below_noise_floor",
        }


@dataclass(frozen=True, slots=True)
class DecodedAudioMetrics:
    """Bounded-memory decoded-PCM audibility evidence for one audio stream."""

    sample_count: int
    nonzero_sample_count: int
    peak_absolute: int
    peak_dbfs: float
    rms_dbfs: float
    decoded_duration_seconds: float
    audibility_state: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RankedAudioStream:
    stream: AudioStreamInfo
    score: float
    confidence: float
    reasons: tuple[str, ...]
    features: AudioSampleFeatures = field(default_factory=AudioSampleFeatures)
    voice_match: float | None = None


@dataclass(frozen=True, slots=True)
class AudioPreviewRegion:
    start_seconds: float
    duration_seconds: float
    score: float
    speech_activity: float
    label: str


@dataclass(slots=True)
class SourceAudioInspection:
    source: Path
    streams: list[AudioStreamInfo]
    ranked: list[RankedAudioStream]
    layout_fingerprint: str
    recorder_profile: str
    duration_seconds: float
    preview_regions: dict[int, list[AudioPreviewRegion]] = field(default_factory=dict)
    selected_ordinal: int | None = None
    confirmation_state: str = "unresolved"
    confirmation_source: str = ""
    audibility_state: str = "inconclusive"
    stream_audibility: dict[int, dict[str, Any]] = field(default_factory=dict)
    audibility_contract_version: int = AUDIBILITY_CONTRACT_VERSION

    @property
    def recommendation(self) -> RankedAudioStream | None:
        return self.ranked[0] if self.ranked else None

    @property
    def resolved(self) -> bool:
        if self.confirmation_state == "no-audio" and not self.streams:
            return True
        if self.confirmation_state == "no-audible-narration":
            return True
        return self.selected_ordinal is not None and self.confirmation_state in {
            "operator-confirmed",
            "confirmed-recording",
            "confirmed-layout",
            "single-stream",
        }

    @property
    def selection_reason(self) -> str:
        if self.confirmation_state == "operator-confirmed":
            return "operator confirmed"
        if self.confirmation_state == "confirmed-recording":
            return "your answer for this recording"
        if self.confirmation_state == "confirmed-layout":
            return "exact saved-layout match"
        if self.confirmation_state == "profile-preference":
            return "profile preference"
        if (
            self.selected_ordinal is not None
            and self.recommendation is not None
            and self.selected_ordinal == self.recommendation.stream.ordinal
        ):
            return "heuristic recommendation"
        return "unresolved"

    @property
    def confirmation_required(self) -> bool:
        return not self.resolved

    def stream_is_audible(self, ordinal: int) -> bool:
        if not self.stream_audibility:
            # Backward compatibility for callers constructing the pre-v1
            # inspection shape.  Production inspections always populate the
            # explicit audibility records.
            return any(stream.ordinal == int(ordinal) for stream in self.streams)
        record = self.stream_audibility.get(int(ordinal), {})
        return str(record.get("final_state") or "") == "audible_signal"

    def audibility_manifest(self) -> dict[str, Any]:
        return {
            "contract_version": self.audibility_contract_version,
            "source_state": self.audibility_state,
            "threshold_policy": {
                "sample_format": "decoded signed 16-bit PCM mono at 16000 Hz",
                "exact_zero_is_silent": True,
                "audible_peak_dbfs_minimum": AUDIBLE_PEAK_DBFS,
                "audible_rms_dbfs_minimum": AUDIBLE_RMS_DBFS,
                "codec_noise_peak_dbfs_maximum": NOISE_FLOOR_PEAK_DBFS,
                "codec_noise_rms_dbfs_maximum": NOISE_FLOOR_RMS_DBFS,
                "boundary_behavior": "Values between the codec-noise and audible boundaries are inconclusive.",
            },
            "audibility_resolution_completed": self.audibility_state
            in {
                "no_audio",
                "audible_candidates",
                "no_audible_narration",
            },
            "full_source_check_completed": bool(self.streams)
            and all(
                bool(record.get("full_source_checked"))
                for record in self.stream_audibility.values()
            ),
            "streams": [
                dict(self.stream_audibility.get(stream.ordinal) or {})
                for stream in self.streams
            ],
        }


def apply_selection_precedence(
    inspection: SourceAudioInspection,
    *,
    saved_layout: dict[str, Any] | None = None,
    preferred_track_number: int = 0,
    confirmed_track: int | None = None,
) -> SourceAudioInspection:
    """Apply your answer for this recording (264), saved-layout, profile, then heuristic selection without
    conflating confirmation. A track that is not there, or has no audible sound, cannot be the answer."""

    if inspection.confirmation_state in {
        "single-stream",
        "no-audio",
        "no-audible-narration",
        "audibility-inconclusive",
    }:
        return inspection
    if confirmed_track is not None:
        ordinal = int(confirmed_track) - 1
        if any(stream.ordinal == ordinal for stream in inspection.streams) and inspection.stream_is_audible(ordinal):
            inspection.selected_ordinal = ordinal
            inspection.confirmation_state = "confirmed-recording"
            inspection.confirmation_source = "your answer for this recording"
            return inspection
    if saved_layout is not None:
        try:
            ordinal = int(saved_layout.get("audioOrdinal", -1))
        except (TypeError, ValueError):
            ordinal = -1
        if (
            any(stream.ordinal == ordinal for stream in inspection.streams)
            and inspection.stream_is_audible(ordinal)
        ):
            inspection.selected_ordinal = ordinal
            inspection.confirmation_state = "confirmed-layout"
            inspection.confirmation_source = "exact saved-layout match"
            return inspection
    if preferred_track_number > 0:
        preferred = next(
            (
                stream
                for stream in inspection.streams
                if stream.human_track_number == preferred_track_number
            ),
            None,
        )
        if (
            preferred is not None
            and inspection.stream_is_audible(preferred.ordinal)
        ):
            inspection.selected_ordinal = preferred.ordinal
            inspection.confirmation_state = "profile-preference"
            inspection.confirmation_source = "profile preference"
            return inspection
    if inspection.recommendation is not None:
        inspection.selected_ordinal = inspection.recommendation.stream.ordinal
        inspection.confirmation_state = "unresolved"
        inspection.confirmation_source = "heuristic recommendation"
    else:
        inspection.selected_ordinal = None
        inspection.confirmation_state = "unresolved"
        inspection.confirmation_source = ""
    return inspection


def discover_media_files(source: Path, *, recurse: bool = True) -> list[Path]:
    if source.is_file():
        return [source] if source.suffix.lower() in SUPPORTED_MEDIA_EXTENSIONS else []
    iterator = source.rglob("*") if recurse else source.glob("*")
    return sorted(path for path in iterator if path.is_file() and path.suffix.lower() in SUPPORTED_MEDIA_EXTENSIONS)


class AudioInspectionCancelled(OSError):
    """Raised when the operator safely cancels an active audio subprocess."""


def _run(
    command: list[str],
    *,
    timeout: int = 60,
    cancel_requested: Callable[[], bool] | None = None,
) -> subprocess.CompletedProcess[str]:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if cancel_requested is None:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            creationflags=creationflags,
        )
    else:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creationflags,
        )
        deadline = time.monotonic() + timeout
        while True:
            if cancel_requested():
                process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                raise AudioInspectionCancelled("Audio inspection was cancelled.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                stdout, stderr = process.communicate()
                raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr)
            try:
                stdout, stderr = process.communicate(timeout=min(0.1, remaining))
            except subprocess.TimeoutExpired:
                continue
            completed = subprocess.CompletedProcess(
                command, process.returncode, stdout, stderr
            )
            break
    if completed.returncode != 0:
        raise OSError(completed.stderr.strip() or f"Command exited with {completed.returncode}")
    return completed


def probe_source(
    ffprobe_exe: str,
    source: Path,
    *,
    cancel_requested: Callable[[], bool] | None = None,
) -> tuple[list[AudioStreamInfo], float, str, dict[str, Any]]:
    completed = _run(
        [
            ffprobe_exe,
            "-v", "error",
            "-select_streams", "a",
            "-show_entries",
            "format=format_name,duration:format_tags=encoder,writing_application,application,name:"
            "stream=index,codec_name,channels,channel_layout,sample_rate,bit_rate:"
            "stream_tags=language,title,handler_name,encoder",
            "-of", "json",
            str(source),
        ],
        timeout=45,
        cancel_requested=cancel_requested,
    )
    payload = json.loads(completed.stdout or "{}")
    streams: list[AudioStreamInfo] = []
    for ordinal, raw in enumerate(payload.get("streams") or []):
        if not isinstance(raw, dict):
            continue
        tags = raw.get("tags") if isinstance(raw.get("tags"), dict) else {}
        streams.append(
            AudioStreamInfo(
                ordinal=ordinal,
                stream_index=int(raw.get("index") or 0),
                title=str(tags.get("title") or tags.get("handler_name") or "").strip(),
                language=str(tags.get("language") or "").strip(),
                codec=str(raw.get("codec_name") or "").strip(),
                channels=int(raw.get("channels") or 0),
                channel_layout=str(raw.get("channel_layout") or "").strip(),
                sample_rate=int(raw.get("sample_rate") or 0),
                bit_rate=int(raw.get("bit_rate") or 0),
            )
        )
    format_info = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    format_tags = format_info.get("tags") if isinstance(format_info.get("tags"), dict) else {}
    recorder_profile = next(
        (str(format_tags.get(key) or "").strip() for key in ("writing_application", "application", "encoder", "name") if format_tags.get(key)),
        str(format_info.get("format_name") or "unknown"),
    )
    try:
        duration = float(format_info.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    return streams, duration, recorder_profile, format_info


def layout_fingerprint(streams: Iterable[AudioStreamInfo], recorder_profile: str = "") -> str:
    normalized = {
        "recorder_profile": recorder_profile.strip().lower(),
        "streams": [
            {
                "ordinal": stream.ordinal,
                "title": stream.title.strip().lower(),
                "language": stream.language.strip().lower(),
                "codec": stream.codec.strip().lower(),
                "channels": stream.channels,
                "channel_layout": stream.channel_layout.strip().lower(),
                "sample_rate": stream.sample_rate,
            }
            for stream in streams
        ],
    }
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def extract_sample(
    ffmpeg_exe: str,
    source: Path,
    ordinal: int,
    destination: Path,
    *,
    duration_seconds: float = SAMPLE_SECONDS,
    source_duration_seconds: float = 0.0,
    start_seconds: float | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    start = max(0.0, float(start_seconds or 0.0))
    if source_duration_seconds > 0:
        start = min(start, max(0.0, source_duration_seconds - duration_seconds))
    _run(
        [
            ffmpeg_exe, "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{start:.3f}", "-t", f"{duration_seconds:.3f}",
            "-i", str(source), "-map", f"0:a:{ordinal}", "-vn",
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(destination),
        ],
        timeout=90,
        cancel_requested=cancel_requested,
    )
    return destination


def _amplitude_dbfs(value: float) -> float:
    if value <= 0:
        return -120.0
    return max(-120.0, 20.0 * math.log10(value / 32768.0))


def classify_decoded_audibility(
    *,
    sample_count: int,
    nonzero_sample_count: int,
    peak_absolute: int,
    rms_dbfs: float,
) -> str:
    """Classify decoded PCM without interpreting content or speaker identity."""

    if sample_count <= 0:
        return "inconclusive"
    if nonzero_sample_count <= 0 or peak_absolute <= 0:
        return "digital_silence"
    peak_dbfs = _amplitude_dbfs(float(peak_absolute))
    if peak_dbfs >= AUDIBLE_PEAK_DBFS or rms_dbfs >= AUDIBLE_RMS_DBFS:
        return "audible_signal"
    if (
        peak_dbfs <= NOISE_FLOOR_PEAK_DBFS
        and rms_dbfs <= NOISE_FLOOR_RMS_DBFS
    ):
        return "below_noise_floor"
    return "inconclusive"


def _decoded_metrics(
    *,
    sample_count: int,
    nonzero_sample_count: int,
    peak_absolute: int,
    sum_squares: int,
    sample_rate: int,
) -> DecodedAudioMetrics:
    mean_square = sum_squares / sample_count if sample_count > 0 else 0.0
    rms_absolute = math.sqrt(mean_square)
    rms_dbfs = _amplitude_dbfs(rms_absolute)
    state = classify_decoded_audibility(
        sample_count=sample_count,
        nonzero_sample_count=nonzero_sample_count,
        peak_absolute=peak_absolute,
        rms_dbfs=rms_dbfs,
    )
    return DecodedAudioMetrics(
        sample_count=sample_count,
        nonzero_sample_count=nonzero_sample_count,
        peak_absolute=peak_absolute,
        peak_dbfs=round(_amplitude_dbfs(float(peak_absolute)), 3),
        rms_dbfs=round(rms_dbfs, 3),
        decoded_duration_seconds=round(
            sample_count / max(1, sample_rate),
            6,
        ),
        audibility_state=state,
    )


def analyze_wav(path: Path) -> AudioSampleFeatures:
    with wave.open(str(path), "rb") as reader:
        channels = reader.getnchannels()
        sample_width = reader.getsampwidth()
        sample_rate = reader.getframerate()
        frames = reader.readframes(reader.getnframes())
    if sample_width != 2:
        raise ValueError("Audio inspection expects 16-bit PCM samples.")
    values = struct.unpack(f"<{len(frames) // 2}h", frames)
    if channels > 1:
        values = tuple(values[index] for index in range(0, len(values), channels))
    sample_count = len(values)
    nonzero_sample_count = sum(value != 0 for value in values)
    peak_absolute = max((abs(value) for value in values), default=0)
    sum_squares = sum(value * value for value in values)
    decoded = _decoded_metrics(
        sample_count=sample_count,
        nonzero_sample_count=nonzero_sample_count,
        peak_absolute=peak_absolute,
        sum_squares=sum_squares,
        sample_rate=sample_rate,
    )
    frame_size = max(1, int(sample_rate * 0.02))
    rms_values: list[float] = []
    zcr_values: list[float] = []
    for offset in range(0, len(values), frame_size):
        block = values[offset : offset + frame_size]
        if len(block) < frame_size // 2:
            continue
        rms_values.append(math.sqrt(sum(value * value for value in block) / len(block)) / 32768.0)
        crossings = sum(1 for left, right in zip(block, block[1:]) if (left < 0) != (right < 0))
        zcr_values.append(crossings / max(1, len(block) - 1))
    if not rms_values:
        return AudioSampleFeatures(
            sample_count=decoded.sample_count,
            nonzero_sample_count=decoded.nonzero_sample_count,
            peak_dbfs=decoded.peak_dbfs,
            rms_db=decoded.rms_dbfs,
            audibility_state=decoded.audibility_state,
        )
    sorted_rms = sorted(rms_values)
    floor = sorted_rms[max(0, int(len(sorted_rms) * 0.15) - 1)]
    peak_reference = sorted_rms[min(len(sorted_rms) - 1, int(len(sorted_rms) * 0.95))]
    active_threshold = max(0.0015, floor * 2.5, peak_reference * 0.08)
    active_flags = [value >= active_threshold for value in rms_values]
    active_ratio = sum(active_flags) / len(active_flags)
    transitions = sum(left != right for left, right in zip(active_flags, active_flags[1:]))
    continuity = 1.0 - (transitions / max(1, len(active_flags) - 1))
    mean_rms = statistics.fmean(rms_values)
    rms_db = 20.0 * math.log10(max(mean_rms, 1e-9))
    dynamic_range = 20.0 * math.log10(max(peak_reference, 1e-9) / max(floor, 1e-9))
    zcr = statistics.fmean(zcr_values) if zcr_values else 0.0
    speech_activity = max(0.0, 1.0 - abs(active_ratio - 0.32) / 0.45)
    speech_activity *= max(0.2, min(1.0, dynamic_range / 24.0))
    music_noise = max(0.0, min(1.0, (active_ratio - 0.50) * 1.6 + (0.18 - min(dynamic_range, 18.0) / 100.0)))
    background = max(0.0, min(1.0, active_ratio * continuity * (1.1 - min(1.0, dynamic_range / 30.0))))
    envelope = tuple(round(value, 7) for value in rms_values)
    return AudioSampleFeatures(
        speech_activity=round(speech_activity, 4),
        active_ratio=round(active_ratio, 4),
        continuity=round(continuity, 4),
        music_noise_likelihood=round(music_noise, 4),
        background_likelihood=round(background, 4),
        dynamic_range_db=round(dynamic_range, 3),
        zero_crossing_rate=round(zcr, 5),
        rms_db=round(rms_db, 3),
        envelope=envelope,
        sample_count=decoded.sample_count,
        nonzero_sample_count=decoded.nonzero_sample_count,
        peak_dbfs=decoded.peak_dbfs,
        audibility_state=decoded.audibility_state,
    )


def preview_region_score(features: AudioSampleFeatures) -> float:
    return round(
        features.speech_activity * 2.0
        + min(1.0, features.dynamic_range_db / 30.0) * 0.45
        - features.music_noise_likelihood * 0.8
        - features.background_likelihood * 0.7,
        4,
    )


def aggregate_region_features(regions: Iterable[AudioSampleFeatures]) -> AudioSampleFeatures:
    values = list(regions)
    if not values:
        return AudioSampleFeatures()
    envelope: list[float] = []
    for item in values:
        envelope.extend(item.envelope[:: max(1, len(item.envelope) // 200)])
    mean = lambda name: statistics.fmean(float(getattr(item, name)) for item in values)
    states = {item.audibility_state for item in values}
    if "audible_signal" in states:
        audibility_state = "audible_signal"
    elif states and states.issubset({"digital_silence", "below_noise_floor"}):
        audibility_state = (
            "digital_silence"
            if states == {"digital_silence"}
            else "below_noise_floor"
        )
    else:
        audibility_state = "inconclusive"
    return AudioSampleFeatures(
        speech_activity=round(mean("speech_activity"), 4),
        active_ratio=round(mean("active_ratio"), 4),
        continuity=round(mean("continuity"), 4),
        music_noise_likelihood=round(mean("music_noise_likelihood"), 4),
        background_likelihood=round(mean("background_likelihood"), 4),
        dynamic_range_db=round(mean("dynamic_range_db"), 3),
        zero_crossing_rate=round(mean("zero_crossing_rate"), 5),
        rms_db=round(mean("rms_db"), 3),
        envelope=tuple(envelope),
        sample_count=sum(item.sample_count for item in values),
        nonzero_sample_count=sum(item.nonzero_sample_count for item in values),
        peak_dbfs=max(item.peak_dbfs for item in values),
        audibility_state=audibility_state,
    )


def activity_scan_starts(duration_seconds: float) -> list[float]:
    if duration_seconds <= ACTIVITY_SCAN_SECONDS:
        return [0.0]
    usable = max(0.0, duration_seconds - ACTIVITY_SCAN_SECONDS)
    count = min(MAX_ACTIVITY_SCAN_WINDOWS, max(3, int(math.ceil(duration_seconds / 120.0))))
    if count <= 1:
        return [0.0]
    return [round(usable * index / (count - 1), 3) for index in range(count)]


def _correlation(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    length = min(len(left), len(right))
    if length < 4:
        return 0.0
    left = left[:length]
    right = right[:length]
    mean_left = statistics.fmean(left)
    mean_right = statistics.fmean(right)
    numerator = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    denominator = math.sqrt(
        sum((a - mean_left) ** 2 for a in left) * sum((b - mean_right) ** 2 for b in right)
    )
    return max(0.0, min(1.0, numerator / denominator)) if denominator else 0.0


def _cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    denominator = math.sqrt(sum(a * a for a in left) * sum(b * b for b in right))
    return max(0.0, min(1.0, numerator / denominator)) if denominator else 0.0


def rank_streams(
    streams: list[AudioStreamInfo],
    features: dict[int, AudioSampleFeatures],
    *,
    voice_signature: tuple[float, ...] | None = None,
) -> list[RankedAudioStream]:
    overlaps: dict[int, float] = {}
    for stream in streams:
        own = features.get(stream.ordinal, AudioSampleFeatures()).envelope
        peers = [
            _correlation(own, features.get(peer.ordinal, AudioSampleFeatures()).envelope)
            for peer in streams
            if peer.ordinal != stream.ordinal
        ]
        overlaps[stream.ordinal] = statistics.fmean(peers) if peers else 0.0

    scored: list[tuple[AudioStreamInfo, float, list[str], AudioSampleFeatures, float | None]] = []
    for stream in streams:
        sample = features.get(stream.ordinal, AudioSampleFeatures())
        metadata = f"{stream.title} {stream.language}".lower()
        score = 0.0
        reasons: list[str] = []
        if any(word in metadata for word in ("microphone", " mic", "mic ", "voice", "narration")):
            score += 3.0
            reasons.append("metadata suggests a microphone or voice source")
        if any(word in metadata for word in ("combined", "mix", "desktop", "game", "music", "output", "speaker")):
            score -= 2.6
            reasons.append("metadata suggests mixed, game, music, or desktop audio")
        score += sample.speech_activity * 1.35
        if sample.speech_activity >= 0.45:
            reasons.append("the sample has speech-like pauses and level changes")
        score -= sample.music_noise_likelihood * 1.35
        if sample.music_noise_likelihood >= 0.45:
            reasons.append("the sample is relatively continuous and may contain music or noise")
        score -= sample.background_likelihood * 1.15
        if sample.background_likelihood >= 0.45:
            reasons.append("continuous background or game-engine sound is likely")
        overlap = overlaps.get(stream.ordinal, 0.0)
        score -= overlap * 0.85
        if overlap >= 0.55:
            reasons.append("the level pattern overlaps other tracks and may be a combined mix")
        if stream.channels == 1 or "mono" in stream.channel_layout.lower():
            score += 0.35
            reasons.append("the channel layout is microphone-like mono")
        voice_match = None
        if voice_signature:
            voice_match = _cosine_similarity(sample.voice_vector(), voice_signature)
            score += max(0.0, voice_match - 0.70) * 2.0
            if voice_match >= 0.88:
                reasons.append("optional local voice characteristics are similar")
        if not reasons:
            reasons.append("metadata and the short sample do not strongly distinguish this track")
        scored.append((stream, score, reasons, sample, voice_match))
    scored.sort(key=lambda item: item[1], reverse=True)
    if not scored:
        return []
    top = scored[0][1]
    second = scored[1][1] if len(scored) > 1 else top - 3.0
    gap = max(0.0, top - second)
    evidence_strength = min(1.0, max(0.0, (top + 1.5) / 4.5))
    confidence = min(0.97, 0.42 + gap * 0.14 + evidence_strength * 0.22)
    if len(scored) == 1:
        confidence = 1.0
    return [
        RankedAudioStream(
            stream=item[0],
            score=round(item[1], 4),
            confidence=round(confidence if index == 0 else max(0.05, confidence - 0.18 - index * 0.05), 3),
            reasons=tuple(item[2]),
            features=item[3],
            voice_match=None if item[4] is None else round(item[4], 3),
        )
        for index, item in enumerate(scored)
    ]


def decode_full_stream_audibility(
    ffmpeg_exe: str,
    source: Path,
    ordinal: int,
    *,
    sample_rate: int = 16000,
    timeout: float = 7200.0,
    cancel_requested: Callable[[], bool] | None = None,
) -> DecodedAudioMetrics:
    """Decode one complete stream to a pipe and retain only aggregate metrics."""

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    command = [
        ffmpeg_exe,
        "-hide_banner",
        "-loglevel",
        "error",
        "-xerror",
        "-nostdin",
        "-i",
        str(source),
        "-map",
        f"0:a:{ordinal}",
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "s16le",
        "pipe:1",
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    )
    if process.stdout is None or process.stderr is None:
        process.kill()
        raise OSError("FFmpeg did not expose decoded-audio pipes.")
    started = time.monotonic()
    carry = b""
    sample_count = 0
    nonzero_sample_count = 0
    peak_absolute = 0
    sum_squares = 0
    try:
        while True:
            if cancel_requested is not None and cancel_requested():
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise AudioInspectionCancelled("Audio inspection was cancelled.")
            if time.monotonic() - started > timeout:
                process.kill()
                process.wait()
                raise subprocess.TimeoutExpired(command, timeout)
            # About two seconds of mono 16 kHz s16 PCM.  This keeps memory
            # bounded and gives cooperative cancellation a practical cadence.
            chunk = process.stdout.read(64 * 1024)
            if not chunk:
                break
            data = carry + chunk
            if len(data) % 2:
                carry = data[-1:]
                data = data[:-1]
            else:
                carry = b""
            if not data:
                continue
            samples = array("h")
            samples.frombytes(data)
            if sys.byteorder != "little":
                samples.byteswap()
            sample_count += len(samples)
            for value in samples:
                absolute = abs(value)
                if absolute:
                    nonzero_sample_count += 1
                    if absolute > peak_absolute:
                        peak_absolute = absolute
                sum_squares += value * value
        return_code = process.wait(timeout=10)
        stderr = process.stderr.read().decode("utf-8", errors="replace").strip()
        if return_code != 0:
            raise OSError(stderr or f"FFmpeg exited with {return_code}.")
        if carry:
            raise OSError("FFmpeg returned an incomplete PCM sample.")
        if sample_count <= 0:
            raise OSError("FFmpeg decoded no PCM samples.")
        return _decoded_metrics(
            sample_count=sample_count,
            nonzero_sample_count=nonzero_sample_count,
            peak_absolute=peak_absolute,
            sum_squares=sum_squares,
            sample_rate=sample_rate,
        )
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()
        process.stderr.close()


def inspect_source(
    ffprobe_exe: str,
    ffmpeg_exe: str,
    source: Path,
    temp_root: Path,
    *,
    voice_signature: tuple[float, ...] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> SourceAudioInspection:
    source_before = source.stat()
    streams, duration, recorder_profile, _format_info = probe_source(
        ffprobe_exe,
        source,
        cancel_requested=cancel_requested,
    )
    sample_root = temp_root / "audio-inspection" / hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:16]
    features: dict[int, AudioSampleFeatures] = {}
    preview_regions: dict[int, list[AudioPreviewRegion]] = {}
    try:
        for stream in streams:
            scanned: list[tuple[float, AudioSampleFeatures, float]] = []
            for scan_index, start in enumerate(activity_scan_starts(duration)):
                scan_path = sample_root / f"track-{stream.human_track_number}-scan-{scan_index + 1}.wav"
                extract_sample(
                    ffmpeg_exe, source, stream.ordinal, scan_path,
                    duration_seconds=ACTIVITY_SCAN_SECONDS,
                    source_duration_seconds=duration,
                    start_seconds=start,
                    cancel_requested=cancel_requested,
                )
                scan_features = analyze_wav(scan_path)
                scanned.append((start, scan_features, preview_region_score(scan_features)))
            selected: list[AudioPreviewRegion] = []
            for start, scan_features, score in sorted(
                scanned,
                key=lambda item: (
                    item[1].meaningfully_audible,
                    item[2],
                ),
                reverse=True,
            ):
                preview_start = max(0.0, min(start - (SAMPLE_SECONDS - ACTIVITY_SCAN_SECONDS) / 2.0, max(0.0, duration - SAMPLE_SECONDS)))
                if any(abs(preview_start - existing.start_seconds) < SAMPLE_SECONDS for existing in selected):
                    continue
                label = (
                    f"Audible region {len(selected) + 1}"
                    if scan_features.meaningfully_audible
                    else f"Silent candidate region {len(selected) + 1}"
                    if scan_features.silent_candidate
                    else f"Inconclusive region {len(selected) + 1}"
                )
                selected.append(
                    AudioPreviewRegion(
                        start_seconds=round(preview_start, 3),
                        duration_seconds=round(min(SAMPLE_SECONDS, max(0.1, duration - preview_start)), 3),
                        score=score,
                        speech_activity=scan_features.speech_activity,
                        label=label,
                    )
                )
                if len(selected) == 3:
                    break
            if not selected:
                selected = [AudioPreviewRegion(0.0, min(SAMPLE_SECONDS, max(0.1, duration)), 0.0, 0.0, "Preview region 1")]
            region_features: list[AudioSampleFeatures] = []
            for region_index, region in enumerate(selected):
                sample_path = sample_root / f"track-{stream.human_track_number}-region-{region_index + 1}.wav"
                extract_sample(
                    ffmpeg_exe, source, stream.ordinal, sample_path,
                    duration_seconds=region.duration_seconds,
                    source_duration_seconds=duration,
                    start_seconds=region.start_seconds,
                    cancel_requested=cancel_requested,
                )
                region_features.append(analyze_wav(sample_path))
            preview_regions[stream.ordinal] = selected
            features[stream.ordinal] = aggregate_region_features(region_features)
    finally:
        cleanup_preview_files(sample_root)

    stream_audibility: dict[int, dict[str, Any]] = {}
    for stream in streams:
        bounded = features.get(stream.ordinal, AudioSampleFeatures())
        record: dict[str, Any] = {
            "operator_track_number": stream.human_track_number,
            "audio_ordinal": stream.ordinal,
            "ffprobe_stream_index": stream.stream_index,
            "ffmpeg_map": stream.ffmpeg_map,
            "bounded_state": bounded.audibility_state,
            "bounded_sample_count": bounded.sample_count,
            "bounded_nonzero_sample_count": bounded.nonzero_sample_count,
            "bounded_peak_dbfs": bounded.peak_dbfs,
            "bounded_rms_dbfs": bounded.rms_db,
            "full_source_checked": False,
            "decode_succeeded": True,
            "final_state": bounded.audibility_state,
            "preview_regions": [
                asdict(region)
                for region in preview_regions.get(stream.ordinal, [])
            ],
        }
        if not bounded.meaningfully_audible:
            record["full_source_checked"] = True
            try:
                full = decode_full_stream_audibility(
                    ffmpeg_exe,
                    source,
                    stream.ordinal,
                    cancel_requested=cancel_requested,
                )
            except AudioInspectionCancelled:
                raise
            except (OSError, subprocess.SubprocessError) as exc:
                record["decode_succeeded"] = False
                record["final_state"] = "inconclusive"
                record["decode_error"] = f"{type(exc).__name__}: {exc}"
            else:
                record["full_source_metrics"] = full.as_dict()
                record["final_state"] = full.audibility_state
        stream_audibility[stream.ordinal] = record

    final_states = {
        str(record.get("final_state") or "inconclusive")
        for record in stream_audibility.values()
    }
    if not streams:
        source_audibility = "no_audio"
    elif "audible_signal" in final_states:
        source_audibility = "audible_candidates"
    elif final_states and final_states.issubset(
        {"digital_silence", "below_noise_floor"}
    ):
        source_audibility = "no_audible_narration"
    else:
        source_audibility = "inconclusive"

    audible_streams = [
        stream
        for stream in streams
        if str(
            stream_audibility.get(stream.ordinal, {}).get("final_state") or ""
        )
        == "audible_signal"
    ]
    ranked = rank_streams(
        audible_streams,
        features,
        voice_signature=voice_signature,
    )
    inspection = SourceAudioInspection(
        source=source,
        streams=streams,
        ranked=ranked,
        layout_fingerprint=layout_fingerprint(streams, recorder_profile),
        recorder_profile=recorder_profile,
        duration_seconds=duration,
        preview_regions=preview_regions,
        audibility_state=source_audibility,
        stream_audibility=stream_audibility,
    )
    if source_audibility == "no_audio":
        inspection.confirmation_state = "no-audio"
        inspection.confirmation_source = "no audio streams"
    elif source_audibility == "no_audible_narration":
        inspection.confirmation_state = "no-audible-narration"
        inspection.confirmation_source = (
            "every complete decoded audio stream is silent or below the "
            "conservative codec-noise floor"
        )
    elif source_audibility == "inconclusive":
        inspection.confirmation_state = "audibility-inconclusive"
        inspection.confirmation_source = (
            "decoded audio falls between the conservative silence and "
            "audible-signal boundaries or could not be decoded completely"
        )
    elif len(streams) == 1 and inspection.stream_is_audible(0):
        inspection.selected_ordinal = 0
        inspection.confirmation_state = "single-stream"
        inspection.confirmation_source = "single audio stream"
    elif ranked:
        inspection.selected_ordinal = ranked[0].stream.ordinal

    source_after = source.stat()
    if (
        source_after.st_size != source_before.st_size
        or source_after.st_mtime_ns != source_before.st_mtime_ns
    ):
        raise OSError("Source changed while audio audibility was inspected.")
    return inspection


class LayoutConfirmationStore:
    """Local-only exact-layout confirmations; not part of profiles or exports."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _read(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return {"schemaVersion": 1, "layouts": {}}
        return payload if isinstance(payload, dict) else {"schemaVersion": 1, "layouts": {}}

    def match(self, fingerprint: str) -> dict[str, Any] | None:
        layouts = self._read().get("layouts") or {}
        value = layouts.get(fingerprint) if isinstance(layouts, dict) else None
        return value if isinstance(value, dict) else None

    def confirm(self, inspection: SourceAudioInspection, ordinal: int, *, profile_name: str = "") -> None:
        stream = next((item for item in inspection.streams if item.ordinal == ordinal), None)
        if stream is None:
            raise ValueError(f"Audio ordinal {ordinal} is not present in this layout.")
        if inspection.stream_audibility and not inspection.stream_is_audible(ordinal):
            raise ValueError(
                f"Track {stream.human_track_number} has no confirmed audible signal."
            )
        payload = self._read()
        layouts = payload.setdefault("layouts", {})
        layouts[inspection.layout_fingerprint] = {
            "recorderProfile": inspection.recorder_profile,
            "streamCount": len(inspection.streams),
            "layoutFingerprint": inspection.layout_fingerprint,
            "humanTrackNumber": stream.human_track_number,
            "audioOrdinal": stream.ordinal,
            "ffmpegMap": stream.ffmpeg_map,
            "confirmedAt": datetime.now(timezone.utc).isoformat(),
            "confirmationSource": "operator",
            "workbenchProfile": profile_name,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class VoiceEnrollmentStore:
    """Stores only a small local acoustic ranking vector, never source audio/path."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> tuple[float, ...] | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
            vector = payload.get("voiceVector")
            if isinstance(vector, list) and vector:
                return tuple(float(value) for value in vector)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
        return None

    def save_features(self, features: AudioSampleFeatures) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schemaVersion": 1,
            "purpose": "optional-local-ranking-only",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "voiceVector": list(features.voice_vector()),
        }
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


def cleanup_preview_files(preview_root: Path) -> None:
    if preview_root.exists():
        shutil.rmtree(preview_root)
