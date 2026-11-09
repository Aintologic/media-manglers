"""Words heard on the narration track that another track carries at the same moment (199).

Music played out loud, the game, a spotter or a teammate on voice chat can reach the operator's
microphone. When the recording has a track that carries that sound on its own (one named, or set,
as never narration), each line of the narration transcript is played from that track too: if the
same words come back, the line came from that track, not from the operator, and it is dropped and
listed with the track it was heard on.

Two things show it. The line's loudest moments on the narration track are no louder than the
microphone's own quiet (CROSS_CHECK_QUIET_DBFS) while the other track is far louder at that moment:
the transcriber wrote the line down from faint sound reaching the microphone, not from the
operator speaking into it. Or the other track says the same words. Measured on real recordings,
spoken lines peak at -20 to -32 dBFS, and lines written down from music bleeding into the microphone
peak at -53 to -60 dBFS while the music track plays at about -20 dBFS.

The full mix is never compared: it carries the operator's own voice as well. Silent tracks and the
narration track itself are not compared either.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import os
import tempfile
from typing import Any, Callable, Iterable
import wave

from .scratch import scratch_root
# 226: the level measure and the near-silent cut-off live in sparse_narration, which the short-reaction
# rule shares them from; they are offered here as before.
from .sparse_narration import NEAR_SILENT_DBFS, PEAK_LOUD_SHARE, peak_dbfs
from .transcripts import write_transcript_files
from . import voice_track
from .voice_track import ROLE_NEVER, Transcriber, _run

# A line needs this many distinctive words to be compared; shorter ones are kept as they are.
CROSS_CHECK_MIN_WORDS = 3
# Words shorter than this ("the", "and", "you") match by chance and are not counted.
CROSS_CHECK_WORD_LENGTH = 4
# A line is the other track's when this share of its distinctive words, and at least
# CROSS_CHECK_MIN_WORDS of them, come back from that track at the same moment.
CROSS_CHECK_SHARE = 0.6
# The window played from the other track reaches this far past each end of the line.
CROSS_CHECK_PAD_SECONDS = 0.5
CROSS_CHECK_REASON = "heard_on_another_track"
# A line whose loudest moments on the narration track are this quiet or quieter...
CROSS_CHECK_QUIET_DBFS = -50.0
# ...while a compared track is this much louder at the same moment came from that track.
CROSS_CHECK_LOUDER_DB = 25.0
# "Loudest moments": this share of 50 ms frames is louder, so a short word still counts.
CROSS_CHECK_PEAK_SHARE = PEAK_LOUD_SHARE
# 203: a line whose loudest moments on the narration track are NEAR_SILENT_DBFS (-47) or quieter was
# not said into that microphone, whatever the other tracks did (see sparse_narration).
NEAR_SILENT_REASON = "narration_track_near_silent"

Extractor = Callable[[int, float, float, Path], Path]


def distinctive_words(text: Any) -> set[str]:
    return {word for word in re.findall(r"[a-z']+", str(text or "").lower()) if len(word) >= CROSS_CHECK_WORD_LENGTH}


def bled_from(line_dbfs: float, other_dbfs: float) -> bool:
    """The line was written down from faint sound while the other track was loud."""

    return line_dbfs <= CROSS_CHECK_QUIET_DBFS and other_dbfs - line_dbfs >= CROSS_CHECK_LOUDER_DB


def near_silent(line_dbfs: float) -> bool:
    return line_dbfs <= NEAR_SILENT_DBFS


def heard_elsewhere(line_words: set[str], other_words: set[str]) -> bool:
    if len(line_words) < CROSS_CHECK_MIN_WORDS or not other_words:
        return False
    shared = line_words & other_words
    return len(shared) >= CROSS_CHECK_MIN_WORDS and len(shared) / len(line_words) >= CROSS_CHECK_SHARE


def tracks_to_compare(detection: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The tracks of this recording that are never narration and have sound, from the voice-track
    result: their roles come from track names or the operator's setting."""

    detection = detection or {}
    roles = {str(key): str(value) for key, value in (detection.get("track_roles") or {}).items()}
    selected = detection.get("selected_ordinal")
    tracks: list[dict[str, Any]] = []
    for item in detection.get("tracks") or []:
        number = int(item.get("track_number") or int(item.get("ordinal", -1)) + 1)
        ordinal = number - 1
        if roles.get(str(number)) != ROLE_NEVER or item.get("silent") or ordinal == selected:
            continue
        tracks.append({"ordinal": ordinal, "track_number": number, "title": str(item.get("title") or "")})
    return sorted(tracks, key=lambda item: item["ordinal"])


def cross_check_segments(
    segments: Iterable[dict[str, Any]],
    tracks: list[dict[str, Any]],
    extract: Extractor,
    transcriber: Callable[[], Transcriber] | Transcriber,
    work_dir: Path,
    narration_ordinal: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep the lines no compared track carries; drop and list the others.

    ``transcriber`` may be a factory, so the speech model is loaded only when words are compared.
    With ``narration_ordinal`` the line's own level is measured too (see ``bled_from``).
    ``on_progress`` hears how many lines are checked, of how many, after each one (226: the AI Video
    Editor's Prepare shows it); without it nothing else changes.
    """

    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    listen: Transcriber | None = None
    segments = list(segments)
    for index, segment in enumerate(segments):
        line_words = distinctive_words(segment.get("text"))
        heard_on: dict[str, Any] | None = None
        how = ""
        # The level needs no words, so every line with any is measured; words are compared only
        # for a line with CROSS_CHECK_MIN_WORDS distinctive ones.
        near_silent_track: dict[str, Any] | None = None
        if (tracks or narration_ordinal is not None) and re.search(r"[A-Za-z]", str(segment.get("text") or "")):
            start = float(segment.get("start") or 0.0)
            end = max(float(segment.get("end") or start), start + 0.3)
            line_dbfs: float | None = None
            if narration_ordinal is not None:
                line_dbfs = peak_dbfs(extract(narration_ordinal, start, end - start,
                                              work_dir / f"line-{index}-{narration_ordinal}.wav"))
            if line_dbfs is not None and tracks:
                # The loudest compared track at that moment is the one the faint sound came from.
                levels = [
                    (peak_dbfs(extract(track["ordinal"], start, end - start,
                                       work_dir / f"level-{index}-{track['ordinal']}.wav")), track)
                    for track in tracks
                ]
                loudest_dbfs, loudest = max(levels, key=lambda item: item[0])
                if bled_from(line_dbfs, loudest_dbfs):
                    heard_on, how = loudest, "level"
            if heard_on is None and line_dbfs is not None and narration_ordinal is not None and near_silent(line_dbfs):
                near_silent_track = {"track_number": narration_ordinal + 1, "title": ""}
            compare_words = heard_on is None and near_silent_track is None and len(line_words) >= CROSS_CHECK_MIN_WORDS
            for track in tracks if compare_words else []:
                if listen is None:
                    listen = transcriber() if getattr(transcriber, "is_factory", False) else transcriber  # type: ignore[operator]
                padded = max(0.0, start - CROSS_CHECK_PAD_SECONDS)
                window = extract(track["ordinal"], padded, end + CROSS_CHECK_PAD_SECONDS - padded,
                                 work_dir / f"window-{index}-{track['ordinal']}.wav")
                other_words = distinctive_words(" ".join(str(item.get("text") or "") for item in listen(window)))
                if heard_elsewhere(line_words, other_words):
                    heard_on, how = track, "words"
                    break
        if near_silent_track is not None:
            dropped.append(
                {
                    "reason": NEAR_SILENT_REASON,
                    "track_number": near_silent_track["track_number"],
                    "track_title": near_silent_track["title"],
                    "found_by": "level",
                    "line_dbfs": round(float(line_dbfs), 1) if line_dbfs is not None else None,
                    "segment": dict(segment),
                }
            )
        elif heard_on is None:
            kept.append(segment)
        else:
            dropped.append(
                {
                    "reason": CROSS_CHECK_REASON,
                    "track_number": heard_on["track_number"],
                    "track_title": heard_on["title"],
                    # "level": written down from faint sound while that track was loud;
                    # "words": that track says the same words.
                    "found_by": how,
                    "segment": dict(segment),
                }
            )
        if on_progress is not None:
            on_progress(index + 1, len(segments))
    return kept, dropped


def ffmpeg_extractor(ffmpeg_exe: str, source: Path) -> Extractor:
    """A few seconds of one audio track of ``source`` as a 16 kHz mono WAV, read with one short seek into
    the recording (FFmpeg's ``-ss`` before ``-i``), so a long recording is never decoded whole. 226: the
    one window decoder; the AI Video Editor's cut points use it too."""

    def extract(ordinal: int, start: float, seconds: float, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        result = _run(
            [
                ffmpeg_exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-ss", f"{start:.3f}", "-t", f"{seconds:.3f}", "-i", str(source),
                "-map", f"0:a:{ordinal}", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(destination),
            ],
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg could not read Track {ordinal + 1}: {result.stderr.strip()[:300]}")
        return destination

    return extract


# The name it had before 226, kept for the callers that use it.
_ffmpeg_extractor = ffmpeg_extractor


def wav_slice_extractor(wavs: dict[int, Path]) -> Extractor:
    """226: cut each line's moments from tracks already decoded in the one read (16 kHz mono 16-bit
    WAVs from ``voice_track.extract_all_tracks``, by 0-based ordinal) instead of seeking into the
    recording for every line and track, as ``_ffmpeg_extractor`` does. The cut is written in the same
    format. A track that was not decoded is refused, with the reason."""

    def extract(ordinal: int, start: float, seconds: float, destination: Path) -> Path:
        source = wavs.get(int(ordinal))
        if source is None or not Path(source).is_file():
            raise RuntimeError(f"Track {int(ordinal) + 1} was not decoded, so its sound cannot be checked.")
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(source), "rb") as reader:
            rate, total = reader.getframerate(), reader.getnframes()
            first = min(total, max(0, int(round(float(start) * rate))))
            last = min(total, max(first, int(round((float(start) + max(0.0, float(seconds))) * rate))))
            reader.setpos(first)
            data = reader.readframes(last - first)
            channels, width = reader.getnchannels(), reader.getsampwidth()
        with wave.open(str(destination), "wb") as writer:
            writer.setnchannels(channels)
            writer.setsampwidth(width)
            writer.setframerate(rate)
            writer.writeframes(data)
        return destination

    return extract


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def rewrite_transcript(json_path: Path, transcript: dict[str, Any], kept: list[dict[str, Any]],
                       dropped: list[dict[str, Any]], counts: dict[str, int]) -> None:
    """Write a transcript again without the ``dropped`` lines: its .json, .srt and .txt hold ``kept``
    (numbered again), the .raw.json lists the dropped lines with their reasons after the lines left out
    before, and the .quality.json counts them, with ``counts`` set in it too. A missing .raw.json or
    .quality.json is left missing. Shared by this check and the AI Video Editor's short-reaction
    re-check (226)."""

    for segment_id, segment in enumerate(kept):
        segment["id"] = segment_id
    stem = json_path.name[: -len(".json")] if json_path.name.endswith(".json") else json_path.stem
    write_transcript_files(
        json_path.parent, json_path.name, f"{stem}.srt", f"{stem}.txt",
        {**transcript, "segments": kept, "text": " ".join(str(item.get("text") or "").strip() for item in kept).strip()},
    )
    raw_path = json_path.with_name(f"{stem}.raw.json")
    raw = _read_json(raw_path)
    if raw:
        raw["filtered_segments"] = list(raw.get("filtered_segments") or []) + dropped
        raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    quality_path = json_path.with_name(f"{stem}.quality.json")
    quality = _read_json(quality_path)
    if quality:
        quality["filtered_segment_count"] = int(quality.get("filtered_segment_count") or 0) + len(dropped)
        quality.update(counts)
        quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check_from_request(
    payload: dict[str, Any],
    *,
    compare_tracks: list[dict[str, Any]] | None = None,
    extractor: Extractor | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Compare each line of a narration transcript with the recording's never-narration tracks
    and rewrite the transcript without the lines another track carries.

    Payload: ``source_path``, ``ffmpeg_exe``, ``transcript_json_path`` (its ``.srt``, ``.txt``,
    ``.raw.json`` and ``.quality.json`` siblings are updated too), ``detection`` (the voice-track
    result), ``model_name``, ``prefer_gpu``, ``language_code``.

    226, for the AI Video Editor, which has read the recording once already: ``compare_tracks``
    (``{"ordinal", "track_number", "title"}`` each) are compared instead of the tracks the detection
    names, ``extractor`` cuts the lines' moments (``wav_slice_extractor`` on the decoded tracks)
    instead of seeking into the recording for each one, and ``on_progress`` hears how many lines are
    checked. Left out, the check is exactly what it was.
    """

    source = Path(str(payload.get("source_path") or ""))
    json_path = Path(str(payload.get("transcript_json_path") or ""))
    if compare_tracks is None:
        tracks = tracks_to_compare(payload.get("detection") if isinstance(payload.get("detection"), dict) else None)
    else:
        tracks = sorted((dict(item) for item in compare_tracks), key=lambda item: int(item["ordinal"]))
    transcript = _read_json(json_path)
    segments = [dict(item) for item in transcript.get("segments") or [] if isinstance(item, dict)]
    selected = (payload.get("detection") or {}).get("selected_ordinal") if isinstance(payload.get("detection"), dict) else None
    # 203: with a narration track, its own level is checked even when no other track is compared.
    if not segments or (not tracks and selected is None):
        return {"compared_tracks": [item["track_number"] for item in tracks], "dropped": [], "kept_count": len(segments)}

    def factory() -> Transcriber:
        # Looked up on the voice-track module, so whatever stands in for Whisper there (the
        # backend's tests) stands in here too.
        return voice_track.whisper_transcriber(str(payload.get("model_name") or "base.en"), bool(payload.get("prefer_gpu", True)),
                                   str(payload.get("language_code") or "en"))

    factory.is_factory = True  # type: ignore[attr-defined]
    # 201: named with this process's id, so a run after a Stop can remove what this one left.
    work_dir = Path(tempfile.mkdtemp(prefix=f"media_manglers_cross_check_{os.getpid()}_", dir=str(scratch_root())))
    try:
        selected = (payload.get("detection") or {}).get("selected_ordinal")
        extract = extractor if extractor is not None else _ffmpeg_extractor(str(payload.get("ffmpeg_exe") or "ffmpeg"), source)
        kept, dropped = cross_check_segments(
            segments, tracks, extract, factory, work_dir,
            narration_ordinal=int(selected) if selected is not None else None, on_progress=on_progress,
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    if dropped:
        rewrite_transcript(json_path, transcript, kept, dropped, {
            "heard_on_another_track_count": sum(1 for item in dropped if item["reason"] == CROSS_CHECK_REASON),
            "narration_near_silent_count": sum(1 for item in dropped if item["reason"] == NEAR_SILENT_REASON),
        })
    return {
        "compared_tracks": [item["track_number"] for item in tracks],
        "kept_count": len(kept),
        "dropped": [
            {
                "start": item["segment"].get("start"),
                "end": item["segment"].get("end"),
                "track_number": item["track_number"],
                "track_title": item["track_title"],
                "found_by": item["found_by"],
                "reason": item["reason"],
            }
            for item in dropped
        ],
    }
