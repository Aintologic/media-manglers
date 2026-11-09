"""Deterministic speech gating and repetition guards for sparse narration."""

from __future__ import annotations

from array import array
from dataclasses import asdict, dataclass
import math
from pathlib import Path
import re
import statistics
import wave
from typing import Any, Callable, Iterable


@dataclass(frozen=True)
class SpeechInterval:
    start_seconds: float
    end_seconds: float

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def normalize_segment_text(value: Any) -> str:
    text = re.sub(r"[^a-z0-9']+", " ", str(value or "").lower())
    return " ".join(text.split())


def repetition_metrics(segments: Iterable[dict[str, Any]]) -> dict[str, Any]:
    texts = [normalize_segment_text(item.get("text")) for item in segments]
    texts = [text for text in texts if text]
    counts: dict[str, int] = {}
    max_consecutive = 0
    current_text = ""
    current_run = 0
    for text in texts:
        counts[text] = counts.get(text, 0) + 1
        if text == current_text:
            current_run += 1
        else:
            current_text = text
            current_run = 1
        max_consecutive = max(max_consecutive, current_run)
    repeated = sum(max(0, count - 1) for count in counts.values())
    return {
        "segment_count": len(texts),
        "repeated_segment_count": repeated,
        "repeated_segment_ratio": round(repeated / len(texts), 4) if texts else 0.0,
        "max_consecutive_identical_segments": max_consecutive,
    }


def repetition_requires_retry(metrics: dict[str, Any]) -> bool:
    return bool(
        int(metrics.get("max_consecutive_identical_segments") or 0) >= 3
        or float(metrics.get("repeated_segment_ratio") or 0.0) > 0.20
    )


def chunk_repetition_metrics(
    prior_segments: Iterable[dict[str, Any]],
    candidate_segments: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Measure repetition inside a chunk and where it joins accepted output.

    Whisper hallucinations in sparse recordings often appear once per VAD
    chunk. Measuring each chunk in isolation misses that cross-chunk loop. The
    cumulative ratio therefore considers exact phrases of at least three words
    across accepted output; short acknowledgements are excluded because
    operators naturally repeat them during a long recording.
    """
    prior = list(prior_segments)
    candidate = list(candidate_segments)
    metrics = repetition_metrics(candidate)
    prior_texts = [normalize_segment_text(item.get("text")) for item in prior]
    prior_texts = [text for text in prior_texts if text]
    candidate_texts = [normalize_segment_text(item.get("text")) for item in candidate]
    candidate_texts = [text for text in candidate_texts if text]
    combined_segments = [
        item
        for item in [*prior, *candidate]
        if len(normalize_segment_text(item.get("text")).split()) >= 3
    ]
    combined = repetition_metrics(combined_segments)
    boundary_segments = [
        {"text": text}
        for text in [*prior_texts[-2:], *candidate_texts]
    ]
    boundary = repetition_metrics(boundary_segments)
    metrics.update(
        {
            "cumulative_repeated_segment_ratio": combined["repeated_segment_ratio"],
            "boundary_max_consecutive_identical_segments": boundary[
                "max_consecutive_identical_segments"
            ],
        }
    )
    return metrics


def chunk_repetition_requires_retry(metrics: dict[str, Any]) -> bool:
    return bool(
        repetition_requires_retry(metrics)
        or int(metrics.get("boundary_max_consecutive_identical_segments") or 0) >= 3
        or float(metrics.get("cumulative_repeated_segment_ratio") or 0.0) > 0.20
    )


def segment_word_count(value: Any) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", str(value or "")))


def _segment_start(segment: dict[str, Any]) -> float:
    try:
        return float(segment.get("start") or 0.0)
    except (TypeError, ValueError):
        return 0.0


# 214: Whisper's own confidence bar (logprob_threshold in whisper_local's sparse decode). When the
# plain decode fails it, Whisper samples at random (temperature 0.2, then 0.4) and keeps the last
# sample even when that fails the bar too. Such a line is a guess: on one recording every run kept
# a different invented line there, and the one real-looking line among them was invented as well.
SAMPLED_LOGPROB_THRESHOLD = -1.0
# 214: one word (or none) stretched over this long is not narration ("A" over 24 seconds). A real
# short line can be stretched too (a whole sentence over 18 seconds), so only one word counts.
LONG_STRETCH_SECONDS = 8.0


def _float(segment: dict[str, Any], key: str) -> float:
    try:
        return float(segment.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def is_sampled_low_confidence(segment: dict[str, Any]) -> bool:
    """A line Whisper sampled at random and itself rates below its confidence bar."""

    return _float(segment, "temperature") > 0.0 and _float(segment, "avg_logprob") < SAMPLED_LOGPROB_THRESHOLD


def is_one_word_over_a_long_stretch(segment: dict[str, Any]) -> bool:
    """One word, or none, over a long stretch: a line too thin for its length."""

    duration = _float(segment, "end") - _float(segment, "start")
    return duration >= LONG_STRETCH_SECONDS and segment_word_count(segment.get("text")) <= 1


def is_prompt_echo(segment: dict[str, Any], prompt_text: Any) -> bool:
    """214: Whisper writing its own prompt back ("..., iRacing, SimHub, Crew Chief") as a line:
    two or more words, every one of them from the prompt."""

    prompt_words = set(re.findall(r"[a-z0-9']+", str(prompt_text or "").lower()))
    words = re.findall(r"[a-z0-9']+", str(segment.get("text") or "").lower())
    return bool(prompt_words) and len(words) >= 2 and all(word in prompt_words for word in words)


def suspect_line_reason(segment: dict[str, Any], prompt_text: Any = "") -> str:
    """Why a line is not to be trusted as narration, or ""."""

    if is_prompt_echo(segment, prompt_text):
        return "prompt_echo"
    if is_sampled_low_confidence(segment):
        return "sampled_low_confidence"
    if is_one_word_over_a_long_stretch(segment):
        return "too_few_words_for_its_length"
    return ""


def _is_real_narration(segment: dict[str, Any]) -> bool:
    text = segment.get("text")
    return segment_word_count(text) >= NEIGHBOUR_NARRATION_WORDS and not is_silence_hallucination_text(text)


def filter_sparse_decoder_segments(
    segments: Iterable[dict[str, Any]],
    *,
    context_segments: Iterable[dict[str, Any]] = (),
    prompt_text: Any = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Remove low-information decoder output while retaining an explainable audit.

    Two corrections over plain threshold filtering (119):

    * text Whisper invents over silence and engine noise ("thanks for
      watching", "sorry for the poor quality of the audio") is dropped even
      when its decoder statistics look healthy; and
    * a short segment sitting next to real narration is kept, because a
      narrator's short asides ("brake bias up") score like noise on their own.
    """

    neighbours = [
        segment for segment in context_segments if _is_real_narration(segment)
    ]
    accepted: list[dict[str, Any]] = []
    filtered: list[dict[str, Any]] = []
    pending: list[tuple[dict[str, Any], str]] = []
    for raw in segments:
        segment = dict(raw)
        compression = float(segment.get("compression_ratio") or 0.0)
        no_speech = float(segment.get("no_speech_prob") or 0.0)
        average_log_probability = float(segment.get("avg_logprob") or 0.0)
        reason = ""
        if is_phrase_loop(segment.get("text")):
            reason = "phrase_loop"
        elif is_silence_hallucination_text(segment.get("text")):
            reason = "known_filler_phrase"
        elif suspect_line_reason(segment, prompt_text):
            # 214: never kept, never rescued, and never counted as narration that rescues others.
            reason = suspect_line_reason(segment, prompt_text)
        elif compression > 2.4:
            reason = "compression_ratio_threshold"
        elif no_speech >= 0.20 and average_log_probability <= -0.60 and compression < 1.0:
            reason = "combined_low_speech_information"
        if reason:
            pending.append((segment, reason))
            continue
        accepted.append(segment)
        if _is_real_narration(segment):
            neighbours.append(segment)
    for segment, reason in pending:
        if reason == "combined_low_speech_information" and _near_narration(segment, neighbours):
            segment["low_information_kept_near_narration"] = True
            accepted.append(segment)
            continue
        filtered.append({"reason": reason, "segment": segment})
    accepted.sort(key=_segment_start)
    return accepted, filtered


def _near_narration(segment: dict[str, Any], neighbours: list[dict[str, Any]]) -> bool:
    if segment_word_count(segment.get("text")) < 1:
        return False
    start = _segment_start(segment)
    for neighbour in neighbours:
        if abs(_segment_start(neighbour) - start) <= NEIGHBOUR_NARRATION_SECONDS:
            return True
    return False


def repetition_is_blocking(metrics: dict[str, Any]) -> bool:
    """Apply the stricter final working-transcript acceptance threshold."""
    return bool(
        int(metrics.get("max_consecutive_identical_segments") or 0) > 3
        or float(metrics.get("repeated_segment_ratio") or 0.0) > 0.10
    )


def _pcm16_mono(path: str | Path) -> tuple[int, array]:
    with wave.open(str(path), "rb") as reader:
        channels = reader.getnchannels()
        sample_width = reader.getsampwidth()
        sample_rate = reader.getframerate()
        frames = reader.readframes(reader.getnframes())
    if sample_width != 2:
        raise ValueError("Sparse narration expects 16-bit PCM WAV audio.")
    samples = array("h")
    samples.frombytes(frames)
    if channels > 1:
        mono = array("h")
        for offset in range(0, len(samples), channels):
            block = samples[offset : offset + channels]
            mono.append(int(sum(block) / max(1, len(block))))
        samples = mono
    return sample_rate, samples


def detect_speech_intervals(
    path: str | Path,
    *,
    block_seconds: float = 0.020,
    padding_seconds: float = 0.350,
    merge_gap_seconds: float = 0.800,
    max_chunk_seconds: float = 30.0,
) -> tuple[list[SpeechInterval], dict[str, Any]]:
    sample_rate, samples = _pcm16_mono(path)
    block_size = max(1, int(round(sample_rate * block_seconds)))
    levels: list[float] = []
    for offset in range(0, len(samples), block_size):
        block = samples[offset : offset + block_size]
        if len(block) < max(1, block_size // 2):
            continue
        rms = math.sqrt(sum(float(value) ** 2 for value in block) / len(block)) / 32768.0
        levels.append(rms)
    duration = len(samples) / sample_rate if sample_rate else 0.0
    if not levels:
        return [], {
            "sample_rate": sample_rate,
            "duration_seconds": round(duration, 3),
            "noise_floor": 0.0,
            "active_threshold": 0.0,
            "active_speech_seconds": 0.0,
            "interval_count": 0,
        }

    ordered = sorted(levels)
    floor_index = min(len(ordered) - 1, max(0, int(len(ordered) * 0.20)))
    noise_floor = ordered[floor_index]
    peak_reference = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    threshold = max(0.0012, noise_floor * 2.8, peak_reference * 0.03)
    active = [level >= threshold for level in levels]

    raw: list[tuple[float, float]] = []
    start_index: int | None = None
    for index, is_active in enumerate([*active, False]):
        if is_active and start_index is None:
            start_index = index
        elif not is_active and start_index is not None:
            start = max(0.0, start_index * block_seconds - padding_seconds)
            end = min(duration, index * block_seconds + padding_seconds)
            if end - start >= 0.18:
                raw.append((start, end))
            start_index = None

    merged: list[list[float]] = []
    for start, end in raw:
        if merged and start - merged[-1][1] <= merge_gap_seconds:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    intervals: list[SpeechInterval] = []
    for start, end in merged:
        cursor = start
        while end - cursor > max_chunk_seconds:
            intervals.append(SpeechInterval(round(cursor, 3), round(cursor + max_chunk_seconds, 3)))
            cursor += max_chunk_seconds
        if end - cursor >= 0.18:
            intervals.append(SpeechInterval(round(cursor, 3), round(end, 3)))

    active_seconds = sum(interval.duration_seconds for interval in intervals)
    return intervals, {
        "sample_rate": sample_rate,
        "duration_seconds": round(duration, 3),
        "block_seconds": block_seconds,
        "padding_seconds": padding_seconds,
        "merge_gap_seconds": merge_gap_seconds,
        "max_chunk_seconds": max_chunk_seconds,
        "noise_floor": round(noise_floor, 7),
        "active_threshold": round(threshold, 7),
        "active_speech_seconds": round(active_seconds, 3),
        "interval_count": len(intervals),
        "intervals": [interval.to_dict() for interval in intervals],
    }


def write_pcm_chunk(
    source: str | Path,
    destination: str | Path,
    interval: SpeechInterval,
) -> Path:
    with wave.open(str(source), "rb") as reader:
        params = reader.getparams()
        start_frame = max(0, int(round(interval.start_seconds * params.framerate)))
        frame_count = max(0, int(round(interval.duration_seconds * params.framerate)))
        reader.setpos(min(start_frame, params.nframes))
        frames = reader.readframes(frame_count)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), "wb") as writer:
        writer.setparams(params)
        writer.writeframes(frames)
    return destination


# How loud a line's "loudest moments" are, in dBFS: the 50 ms frame that only PEAK_LOUD_SHARE of the
# line's frames are louder than, so a short word still counts (199, 203). The cross-track check and
# the short-reaction rule share this one measure (226: it moved here from cross_track_check, which
# still offers it, so this module needs nothing from that one).
PEAK_FRAME_SECONDS = 0.05
PEAK_LOUD_SHARE = 0.1
# 203: a line whose loudest moments on the narration track are this quiet or quieter was not said
# into that microphone, whatever the other tracks did. Measured on sample recordings: the narrator's
# lines peak at -20 to -32 dBFS (-45.4 for a quiet aside); lines Whisper invented over quiet
# stretches at -48 to -49 dBFS.
NEAR_SILENT_DBFS = -47.0


def _loud_frame_dbfs(samples: array, rate: int) -> float:
    size = max(1, int(rate * PEAK_FRAME_SECONDS))
    levels = sorted(
        math.sqrt(sum(value * value for value in samples[start : start + size]) / size)
        for start in range(0, max(len(samples) - size + 1, 1), size)
        if samples[start : start + size]
    )
    if not levels:
        return -120.0
    loud = levels[min(len(levels) - 1, int(len(levels) * (1.0 - PEAK_LOUD_SHARE)))]
    return max(-120.0, 20.0 * math.log10(loud / 32768.0)) if loud > 0 else -120.0


def peak_dbfs(path: str | Path) -> float:
    """The level of a 16-bit WAV's loudest moments, in dBFS: the frame (50 ms) that only
    PEAK_LOUD_SHARE of the frames are louder than."""

    with wave.open(str(path), "rb") as reader:
        rate = reader.getframerate()
        samples = array("h", reader.readframes(reader.getnframes()))
    return _loud_frame_dbfs(samples, rate)


def span_peak_dbfs(path: str | Path, start_seconds: float, end_seconds: float) -> float:
    """226: ``peak_dbfs`` of one stretch of a 16-bit WAV, read straight from the file: the same frames
    as ``cross_track_check.wav_slice_extractor`` cuts for that stretch, without writing them out."""

    with wave.open(str(path), "rb") as reader:
        rate, total = reader.getframerate(), reader.getnframes()
        first = min(total, max(0, int(round(float(start_seconds) * rate))))
        seconds = max(0.0, float(end_seconds) - float(start_seconds))
        last = min(total, max(first, int(round((float(start_seconds) + seconds) * rate))))
        reader.setpos(first)
        samples = array("h", reader.readframes(last - first))
    return _loud_frame_dbfs(samples, rate)


def rms_dbfs(value: Any) -> float:
    """An RMS level (0-1 of full scale, as the VAD audit's noise_floor) in dBFS; -120 for silence."""

    try:
        level = float(value or 0.0)
    except (TypeError, ValueError):
        level = 0.0
    return max(-120.0, 20.0 * math.log10(level)) if level > 0 else -120.0


def offset_segments(
    segments: Iterable[dict[str, Any]],
    offset_seconds: float,
) -> list[dict[str, Any]]:
    adjusted: list[dict[str, Any]] = []
    for index, raw in enumerate(segments):
        segment = dict(raw)
        segment["id"] = len(adjusted)
        segment["start"] = round(float(segment.get("start") or 0.0) + offset_seconds, 3)
        segment["end"] = round(float(segment.get("end") or 0.0) + offset_seconds, 3)
        adjusted.append(segment)
    return adjusted


def words_per_minute(segments: Iterable[dict[str, Any]], duration_seconds: float) -> float:
    words = sum(len(str(item.get("text") or "").split()) for item in segments)
    return round(words / (duration_seconds / 60.0), 3) if duration_seconds > 0 else 0.0


# Phrases Whisper is known to invent when it is fed silence, music or engine
# noise. A transcript made mostly of these is not the operator's narration (94).
SILENCE_HALLUCINATION_PHRASES: tuple[str, ...] = (
    "thank you for watching",
    "thanks for watching",
    "please subscribe",
    "like and subscribe",
    "subscribe to my channel",
    "see you in the next video",
    "see you next time",
    "subtitles by",
    "subtitled by",
    "captions by",
    "transcribed by",
    "amara org",
    "thank you",
    "thank you very much",
    "thanks",
    "hello",
    "bye",
    "bye bye",
    "you",
    "okay",
    "music",
    "applause",
    "silence",
)
# Longer lines Whisper invents from YouTube-style training data. These are
# matched anywhere in a segment, because they also appear repeated inside one
# segment ("I'm sorry for the poor quality of the audio, I'm sorry for...").
VIDEO_FILLER_PHRASES: tuple[str, ...] = (
    "sorry for the poor quality of the audio",
    "sorry for the bad audio",
    "sorry about the quality of this video",
    "welcome to my channel",
    "leave a like comment and subscribe",
    "please leave a like",
    "subscribe to my channel",
    "link in the description",
    "click on the link in the description",
    "check out my other videos",
    "if you want to see more of this video",
    "i hope you enjoyed this video",
    "i hope you like this video",
    "thanks for watching",
    "thank you for watching",
    "if you did please leave a like",
    "this video is a work of fiction",
    # 199: invented over music in real recordings.
    "not sure how to translate this",
    "it s something that s been said",
    # 201: invented over a quiet stretch of a real recording. Said once, the sign-off in the last
    # entry can be real; said twice back to back it is Whisper's.
    "like comment and subscribe",
    "subscribe to the channel",
    "i hope you enjoyed it i hope you enjoyed it",
)
# 199: a line Whisper invents over music often loops one phrase ("a sample phrase, a sample phrase,
# a sample phrase"). A phrase of at least PHRASE_LOOP_MIN_WORDS words, with at least two different
# words, said PHRASE_LOOP_REPEATS times or more back to back, that makes up at least
# PHRASE_LOOP_SHARE of the line is a loop. Real narration that repeats a word ("no, no, no"), a
# phrase inside a longer sentence, or a phrase with other words between ("make this a ticket for
# item A, make this a ticket for item B") is not. Lines no more than
# PHRASE_LOOP_GAP_SECONDS apart count as one run.
PHRASE_LOOP_MIN_WORDS = 3
PHRASE_LOOP_MAX_WORDS = 6
PHRASE_LOOP_REPEATS = 3
PHRASE_LOOP_SHARE = 0.5
PHRASE_LOOP_GAP_SECONDS = 10.0
MINIMUM_NARRATION_WORDS = 1
# A short low-information segment is kept when real narration sits this close
# to it; a narrator speaks in bursts with long quiet stretches between (119).
NEIGHBOUR_NARRATION_SECONDS = 120.0
NEIGHBOUR_NARRATION_WORDS = 4


def _loop_words(value: Any) -> list[str]:
    return re.findall(r"[a-z]+", str(value or "").lower())


def _phrase_counts(words: list[str]) -> dict[tuple[str, ...], int]:
    """Each phrase of PHRASE_LOOP_MIN_WORDS..PHRASE_LOOP_MAX_WORDS words, with at least two
    different words, and the most times it is said back to back without overlapping itself."""

    counts: dict[tuple[str, ...], int] = {}
    for size in range(PHRASE_LOOP_MIN_WORDS, PHRASE_LOOP_MAX_WORDS + 1):
        positions: dict[tuple[str, ...], list[int]] = {}
        for start in range(len(words) - size + 1):
            phrase = tuple(words[start : start + size])
            if len(set(phrase)) >= 2:
                positions.setdefault(phrase, []).append(start)
        for phrase, starts in positions.items():
            best, run, last_end = 0, 0, -1
            for start in starts:
                if start < last_end:
                    continue
                run = run + 1 if start == last_end else 1
                last_end = start + size
                best = max(best, run)
            counts[phrase] = best
    return counts


def is_phrase_loop(value: Any) -> bool:
    """True when one phrase said over and over makes up most of the line (199)."""

    words = _loop_words(value)
    return any(
        count >= PHRASE_LOOP_REPEATS and count * len(phrase) >= PHRASE_LOOP_SHARE * len(words)
        for phrase, count in _phrase_counts(words).items()
    )


def drop_phrase_loops(
    segments: Iterable[dict[str, Any]],
    *,
    context_segments: Iterable[dict[str, Any]] = (),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Drop lines that loop a phrase on their own, or together with neighbouring lines (199).

    ``context_segments`` (lines already thrown out, such as a chunk rejected for repeating
    itself) count as neighbours but are never returned. Returns the kept lines in their order,
    and the dropped ones as ``{"reason": "phrase_loop", "segment": ...}``.
    """

    items = [dict(segment) for segment in segments]
    delivered = len(items)
    items += [dict(segment) for segment in context_segments]
    order = sorted(range(len(items)), key=lambda index: _segment_start(items[index]))
    looping: set[int] = {index for index in order if is_phrase_loop(items[index].get("text"))}
    # A phrase that fills most of each of several neighbouring lines, and is said
    # PHRASE_LOOP_REPEATS times or more across them, is one loop split over lines.
    holders: dict[tuple[str, ...], list[tuple[int, int]]] = {}
    for index in order:
        words = _loop_words(items[index].get("text"))
        for phrase, count in _phrase_counts(words).items():
            if count * len(phrase) >= PHRASE_LOOP_SHARE * len(words):
                holders.setdefault(phrase, []).append((index, count))
    for members in holders.values():
        run: list[tuple[int, int]] = []
        for member in members + [(-1, 0)]:
            index, _count = member
            if run and (index < 0 or _segment_start(items[index]) - _segment_start(items[run[-1][0]])
                        > PHRASE_LOOP_GAP_SECONDS):
                if len(run) >= 2 and sum(count for _index, count in run) >= PHRASE_LOOP_REPEATS:
                    looping.update(index for index, _count in run)
                run = []
            if index >= 0:
                run.append(member)
    kept = [items[index] for index in range(delivered) if index not in looping]
    dropped = [{"reason": "phrase_loop", "segment": items[index]} for index in order
               if index in looping and index < delivered]
    return kept, dropped


def is_silence_hallucination_text(value: Any) -> bool:
    normalized = " ".join(re.findall(r"[a-z]+", str(value or "").lower()))
    if not normalized:
        return True
    if is_phrase_loop(normalized):
        return True
    words = normalized.split()
    for phrase in VIDEO_FILLER_PHRASES:
        if phrase in normalized:
            return True
    for phrase in SILENCE_HALLUCINATION_PHRASES:
        if normalized == phrase:
            return True
        phrase_words = phrase.split()
        if len(phrase_words) >= 3 and phrase in normalized and len(words) <= len(phrase_words) + 4:
            return True
    return False


def silence_hallucination_metrics(
    segments: Iterable[dict[str, Any]],
    *,
    fallback_word_count: int = 0,
) -> dict[str, Any]:
    """Separate real narration from text Whisper invents on silent audio."""

    hallucinated = 0
    spoken = 0
    narration_words = 0
    seen_segment = False
    # 214: a kept line of one word over a long stretch counts as invented, and each is listed. (The
    # filters drop such lines in narrated recordings; this catches one in any other transcript.)
    suspect_lines: list[dict[str, Any]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        seen_segment = True
        text = str(segment.get("text") or "")
        if not re.search(r"[A-Za-z]", text):
            continue
        spoken += 1
        if is_silence_hallucination_text(text):
            hallucinated += 1
            continue
        suspect = "too_few_words_for_its_length" if is_one_word_over_a_long_stretch(segment) else ""
        if suspect:
            hallucinated += 1
            suspect_lines.append({"start": _float(segment, "start"), "end": _float(segment, "end"),
                                  "text": text.strip(), "reason": suspect})
            continue
        narration_words += len(re.findall(r"[A-Za-z0-9']+", text))
    if not seen_segment:
        narration_words = int(fallback_word_count)
    ratio = (hallucinated / spoken) if spoken else 0.0
    return {
        "silence_hallucination_segment_count": hallucinated,
        "silence_hallucination_ratio": round(ratio, 4),
        "narration_word_count": narration_words,
        "silence_hallucination_suspected": bool(hallucinated >= 3 and ratio >= 0.5),
        "no_narration_found": narration_words < MINIMUM_NARRATION_WORDS,
        "suspect_line_count": len(suspect_lines),
        "suspect_lines": suspect_lines,
    }


# 226: the AI Video Editor's "keep short reactions" rule, on only for a request that asks for it
# (keep_short_reactions). The sampled-guess bar (214) also drops the operator's real short reactions,
# an exclamation said once, on its own, while driving. Such a line comes back only when all hold:
# - its one fault is that bar: it is no filler, loop, prompt echo, one word over a long stretch or
#   over-compressed line, and it comes from the Whisper attempt that was used for its stretch;
# - it is its own short burst: at most SHORT_REACTION_MAX_WORDS words over at most
#   SHORT_REACTION_MAX_SECONDS, in a stretch of sound (one VAD chunk) of at most
#   SHORT_REACTION_MAX_CHUNK_SECONDS that Whisper wrote at most SHORT_REACTION_MAX_CHUNK_SEGMENTS lines for;
# - the microphone is really loud then: the line's loudest moments (``peak_dbfs``) are above
#   NEAR_SILENT_DBFS and at least SHORT_REACTION_OVER_FLOOR_DB over the recording's own quiet (the VAD
#   noise floor);
# - a real line (NEIGHBOUR_NARRATION_WORDS words or more, kept on its own merits) starts or ends within
#   SHORT_REACTION_ANCHOR_SECONDS of it.
# On the recorded runs Whisper's guesses fill long stretches (the shape rules them out) or sit over a
# quiet microphone (the level rules them out); together the two let none of the known invented lines
# back. No word list is used. A kept reaction is never narration that keeps another line, and never
# makes another line go. Features 1-3 leave the rule off: a ticket or a review package needs words,
# not exclamations.
SHORT_REACTION_MAX_WORDS = 3
SHORT_REACTION_MAX_SECONDS = 3.0
SHORT_REACTION_MAX_CHUNK_SECONDS = 3.0
SHORT_REACTION_MAX_CHUNK_SEGMENTS = 2
SHORT_REACTION_OVER_FLOOR_DB = 12.0
SHORT_REACTION_ANCHOR_SECONDS = 15.0
# The shortest stretch a line's level is measured over, as the cross-track check measures a line.
SHORT_REACTION_MIN_LEVEL_SECONDS = 0.3
SHORT_REACTION_REASON = "sampled_low_confidence"
SHORT_REACTION_NO_ANCHOR_REASON = "short_reaction_without_anchor"
# The mark on a kept reaction's line, in memory and in raw.json's short_reactions_kept.
SHORT_REACTION_MARK = "short_reaction_kept"


def _line_key(segment: dict[str, Any]) -> tuple[float, float]:
    return round(_float(segment, "start"), 3), round(_float(segment, "end"), 3)


def only_fault_is_the_sampled_bar(segment: dict[str, Any], prompt_text: Any = "") -> bool:
    """The line was dropped only for being a sampled guess below Whisper's bar: it is no filler, phrase
    loop, prompt echo, one word over a long stretch or over-compressed line. (A low-information line is
    kept near narration as before; a short reaction always has narration near it.)"""

    text = segment.get("text")
    return (
        suspect_line_reason(segment, prompt_text) == SHORT_REACTION_REASON
        and not is_phrase_loop(text)
        and not is_silence_hallucination_text(text)
        and not is_one_word_over_a_long_stretch(segment)
        and _float(segment, "compression_ratio") <= 2.4
    )


def is_short_burst(segment: dict[str, Any], chunk_seconds: float, chunk_segment_count: int) -> bool:
    """At most SHORT_REACTION_MAX_WORDS words over at most SHORT_REACTION_MAX_SECONDS, in a VAD chunk of
    at most SHORT_REACTION_MAX_CHUNK_SECONDS that holds at most SHORT_REACTION_MAX_CHUNK_SEGMENTS lines."""

    seconds = round(_float(segment, "end") - _float(segment, "start"), 3)
    return (
        segment_word_count(segment.get("text")) <= SHORT_REACTION_MAX_WORDS
        and seconds <= SHORT_REACTION_MAX_SECONDS
        and round(float(chunk_seconds), 3) <= SHORT_REACTION_MAX_CHUNK_SECONDS
        and int(chunk_segment_count) <= SHORT_REACTION_MAX_CHUNK_SEGMENTS
    )


def is_live_microphone(line_dbfs: float, noise_floor_dbfs: float) -> bool:
    """The microphone was really heard: above NEAR_SILENT_DBFS and SHORT_REACTION_OVER_FLOOR_DB or more
    over the recording's quiet."""

    return line_dbfs > NEAR_SILENT_DBFS and line_dbfs >= noise_floor_dbfs + SHORT_REACTION_OVER_FLOOR_DB


def _can_anchor(segment: dict[str, Any], prompt_text: Any = "") -> bool:
    text = segment.get("text")
    return (
        segment_word_count(text) >= NEIGHBOUR_NARRATION_WORDS
        and not is_silence_hallucination_text(text)
        and not suspect_line_reason(segment, prompt_text)
        and not segment.get("low_information_kept_near_narration")
        and not segment.get(SHORT_REACTION_MARK)
    )


def short_reaction_anchor(
    segment: dict[str, Any],
    lines: Iterable[dict[str, Any]],
    prompt_text: Any = "",
) -> dict[str, Any] | None:
    """The nearest real line that starts or ends within SHORT_REACTION_ANCHOR_SECONDS of ``segment``, or
    None. A real line has NEIGHBOUR_NARRATION_WORDS words or more, is no filler or suspect line, and was
    kept on its own merits: not only for sitting near narration, and not as a short reaction."""

    start, end = _float(segment, "start"), _float(segment, "end")
    best: dict[str, Any] | None = None
    best_gap = 0.0
    for other in lines:
        if other is segment or not _can_anchor(other, prompt_text):
            continue
        gap = round(max(_float(other, "start") - end, start - _float(other, "end"), 0.0), 3)
        if gap <= SHORT_REACTION_ANCHOR_SECONDS and (best is None or gap < best_gap):
            best, best_gap = other, gap
    return best


def select_short_reactions(
    used_attempts: Iterable[dict[str, Any]],
    lines: list[dict[str, Any]],
    line_dbfs: Callable[[float, float], float | None],
    noise_floor_dbfs: float,
    *,
    prompt_text: Any = "",
) -> list[dict[str, Any]]:
    """The short reactions to keep from one transcription, in time order (the rule above).

    ``used_attempts``: for each chunk, the Whisper attempt that was used (``raw_attempts`` entries with
    ``interval``, ``segments`` and ``filtered_segments``); a discarded attempt or a thrown-out chunk is
    never passed. ``lines``: the lines kept so far. ``line_dbfs(start, end)``: the narration track's
    level over that stretch (``span_peak_dbfs``), or None when it is not known.
    ``noise_floor_dbfs``: the recording's quiet, from the VAD audit (``rms_dbfs``).
    Returns ``{"chunk_index", "attempt", "segment", "line_dbfs", "anchor_start"}`` for each, ``segment``
    being the dropped line as that attempt holds it.
    """

    found: list[dict[str, Any]] = []
    for attempt in used_attempts:
        interval = attempt.get("interval") or {}
        chunk_seconds = _float(interval, "end_seconds") - _float(interval, "start_seconds")
        chunk_segments = len(attempt.get("segments") or [])
        for item in attempt.get("filtered_segments") or []:
            segment = item.get("segment") or {}
            if item.get("reason") != SHORT_REACTION_REASON or not only_fault_is_the_sampled_bar(segment, prompt_text):
                continue
            if not is_short_burst(segment, chunk_seconds, chunk_segments):
                continue
            anchor = short_reaction_anchor(segment, lines, prompt_text)
            if anchor is None:
                continue
            start, end = _float(segment, "start"), _float(segment, "end")
            level = line_dbfs(start, max(end, start + SHORT_REACTION_MIN_LEVEL_SECONDS))
            if level is None or not is_live_microphone(float(level), float(noise_floor_dbfs)):
                continue
            found.append({"chunk_index": attempt.get("chunk_index"), "attempt": attempt.get("attempt"),
                          "segment": segment, "line_dbfs": round(float(level), 1),
                          "anchor_start": _float(anchor, "start")})
    found.sort(key=lambda item: _segment_start(item["segment"]))
    return found


def add_short_reactions(
    lines: list[dict[str, Any]],
    reactions: Iterable[dict[str, Any]],
    *,
    context_segments: Iterable[dict[str, Any]] = (),
    prompt_text: Any = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """The kept lines with the short reactions added, in time order (226).

    A reaction that loops a phrase with the lines around it (``drop_phrase_loops``, with
    ``context_segments`` as there), or whose real line nearby is gone, is left out. The other lines are
    returned as they are: adding a reaction never takes another line away. Returns (the lines, the
    reactions left out, the reactions added). Each added reaction's ``segment`` is a copy of the line
    marked SHORT_REACTION_MARK, the same dictionary as in the lines. Each reaction left out is
    ``{"chunk_index", "attempt", "reason", "segment"}`` (the chunk and attempt it came from, when the
    reaction names them) and its ``segment`` is a copy of the line without the mark: it was not kept.
    """

    marked: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for item in reactions:
        segment = dict(item["segment"])
        segment[SHORT_REACTION_MARK] = True
        marked.append((item, segment))
    if not marked:
        return list(lines), [], []
    _kept, looped = drop_phrase_loops([*lines, *(segment for _item, segment in marked)],
                                      context_segments=context_segments)
    looping = {_line_key(entry["segment"]) for entry in looped if entry["segment"].get(SHORT_REACTION_MARK)}

    def left_out(item: dict[str, Any], segment: dict[str, Any], reason: str) -> dict[str, Any]:
        where = {key: item[key] for key in ("chunk_index", "attempt") if key in item}
        line = {key: value for key, value in segment.items() if key != SHORT_REACTION_MARK}
        return {**where, "reason": reason, "segment": line}

    dropped: list[dict[str, Any]] = []
    added: list[dict[str, Any]] = []
    for item, segment in marked:
        if _line_key(segment) in looping:
            dropped.append(left_out(item, segment, "phrase_loop"))
            continue
        anchor = short_reaction_anchor(segment, lines, prompt_text)
        if anchor is None:
            dropped.append(left_out(item, segment, SHORT_REACTION_NO_ANCHOR_REASON))
            continue
        added.append({**item, "segment": segment, "anchor_start": _float(anchor, "start")})
    # Each reaction goes in before the first later line; the other lines keep their order.
    merged = list(lines)
    for item in added:
        start = _segment_start(item["segment"])
        position = next((index for index, other in enumerate(merged) if _segment_start(other) > start), len(merged))
        merged.insert(position, item["segment"])
    return merged, dropped, added


def reanchor_short_reactions(
    segments: Iterable[dict[str, Any]],
    reactions: Iterable[dict[str, Any]],
    *,
    not_anchors: Iterable[dict[str, Any]] = (),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """226: after a later filter took lines out (the editor's cross-track and near-silent checks), the
    kept short reactions whose real line nearby went with them go too.

    ``segments``: the transcript's lines now (start, end and text are enough). ``reactions``: raw.json's
    ``short_reactions_kept``; a line is one of them when its start and end match. ``not_anchors``: lines
    that may not anchor a reaction, such as raw.json's ``rescued_segments`` (kept only for sitting near
    narration), as entries or lines, matched the same way. Returns (the lines kept, in their order; the
    reactions dropped as ``{"reason": SHORT_REACTION_NO_ANCHOR_REASON, "segment": ...}``).
    """

    lines = list(segments)
    reaction_keys = {_line_key(item.get("segment") or {}) for item in reactions}
    barred = {
        _line_key(item["segment"] if isinstance(item.get("segment"), dict) else item) for item in not_anchors
    }
    anchors = [line for line in lines if _line_key(line) not in reaction_keys and _line_key(line) not in barred]
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for line in lines:
        if _line_key(line) in reaction_keys and short_reaction_anchor(line, anchors) is None:
            dropped.append({"reason": SHORT_REACTION_NO_ANCHOR_REASON, "segment": dict(line)})
        else:
            kept.append(line)
    return kept, dropped
