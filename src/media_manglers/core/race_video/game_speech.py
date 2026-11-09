"""Other people's voices on the game track (172).

Voice chat, a spotter and race control all arrive on the game track, which carries engine noise the
whole race. A loudness check cannot tell a voice from an engine, so the game track is transcribed
with Whisper, and only the lines that look like real speech are kept: Whisper invents words over
engine noise, and the operator's own voice can bleed onto the game track too. The result goes into
the digest, so the AI editor and the sharing check see who else can be heard, and when.

226: the game track comes from Prepare's one read of the recording, already decoded, and Whisper
from the shared loader (``voice_track.whisper_transcriber``, loaded once by the caller). The track
is heard in five-minute pieces, so the Workbench hears how far it has got. Every line left out is
kept too, with the reason, in its own list, apart from the voices the AI editor reports.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Callable
import wave

from ..cross_track_check import wav_slice_extractor
from ..scratch import scratch_root
from ..sparse_narration import is_phrase_loop, is_silence_hallucination_text, normalize_segment_text
from .project import write_json_atomic

# A segment counts as speech only when Whisper is fairly sure of it. These are this feature's own bars,
# not voice_track.confident_speech's: that one counts confident words to choose the narration track, and
# leaves a line out at exactly the bar (no_speech_prob >= 0.5, avg_logprob <= -1.0) and never by its
# compression ratio. Here a line exactly at a bar is kept, and a repeated, highly compressible line
# ("go go go go go go") is left out; moving to the shared bars would change which voices the AI
# editor is told about (226). A line that loops a phrase is left out as repeated words by the shared
# loop rule (``sparse_narration.is_phrase_loop``, the one every transcript uses), whatever its
# compression ratio.
MAX_NO_SPEECH = 0.5
MIN_AVG_LOGPROB = -1.0
MAX_COMPRESSION = 2.4
# The operator's own voice bleeding onto the game track (``_operator_echo``) stays this feature's own
# check: the shared cross-track check (``cross_track_check``) asks the other way round, whether a line
# of the narration came from another track, by playing that track at the line's moment. Here the line
# is on the game track and the question is whether the narration said it; its words are compared
# with the narration transcript already written, so nothing is decoded or heard again.
SAME_AS_OPERATOR = 0.5   # share of words in common with the operator's narration at the same moment
# The game track is heard in pieces this long (226), each one a progress step.
PIECE_SECONDS = 300.0
# Each piece is cut with this much of the track before and after it, so a line said across a cut is
# heard whole; a line belongs to the piece its middle falls in, so it is kept once.
PIECE_OVERLAP_SECONDS = 5.0
# Bump when what is kept or left out changes, so a stored result is worked out again (2: a looped
# phrase is left out as repeated words, by the shared loop rule; 3: the pieces overlap).
RULES_VERSION = 3
# Why a line was left out.
LEFT_OUT_FILLER = "filler_whisper_writes_over_noise"
LEFT_OUT_NO_SPEECH = "probably_not_speech"
LEFT_OUT_UNSURE = "whisper_unsure_of_the_words"
LEFT_OUT_REPEATED = "repeated_words"
LEFT_OUT_OPERATOR = "the_drivers_own_voice"


def _words(text: str) -> set[str]:
    return set(normalize_segment_text(text).split())


def _operator_echo(segment: dict[str, Any], narration: list[dict[str, Any]]) -> bool:
    words = _words(str(segment.get("text") or ""))
    if not words:
        return False
    start, end = float(segment["start"]), float(segment["end"])
    for line in narration:
        if float(line["start"]) <= end + 1.0 and float(line["end"]) >= start - 1.0:
            theirs = _words(str(line.get("text") or ""))
            if theirs and len(words & theirs) / len(words) >= SAME_AS_OPERATOR:
                return True
    return False


def _left_out_reason(segment: dict[str, Any], text: str, narration: list[dict[str, Any]]) -> str:
    # The shared loop rule first: the filler check applies it too, but a looped phrase is repeated
    # words, not filler, and is listed so.
    if is_phrase_loop(text):
        return LEFT_OUT_REPEATED
    if is_silence_hallucination_text(text):
        return LEFT_OUT_FILLER
    if float(segment.get("no_speech_prob", 0.0)) > MAX_NO_SPEECH:
        return LEFT_OUT_NO_SPEECH
    if float(segment.get("avg_logprob", 0.0)) < MIN_AVG_LOGPROB:
        return LEFT_OUT_UNSURE
    if float(segment.get("compression_ratio", 0.0)) > MAX_COMPRESSION:
        return LEFT_OUT_REPEATED
    if _operator_echo(segment, narration):
        return LEFT_OUT_OPERATOR
    return ""


def sort_game_speech(segments: list[dict[str, Any]], narration: list[dict[str, Any]]
                     ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The game-track lines that are real speech by someone other than the operator, and every other
    line with the reason it was left out (226). A segment with no text is no line and is in neither."""

    kept: list[dict[str, Any]] = []
    left_out: list[dict[str, Any]] = []
    for segment in segments:
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        line = {"start": round(float(segment["start"]), 1), "end": round(float(segment["end"]), 1), "text": text}
        reason = _left_out_reason(segment, text, narration)
        if reason:
            left_out.append({**line, "reason": reason})
        else:
            kept.append(line)
    return kept, left_out


def find_game_speech(segments: list[dict[str, Any]], narration: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The game-track lines that are real speech by someone other than the operator."""

    return sort_game_speech(segments, narration)[0]


def stamp(*, model_name: str, language: str, prefer_gpu: bool, track: int, narration_sha256: str) -> dict[str, Any]:
    """What a stored result was worked out with (226): Prepare uses it again only when this matches."""

    return {"rules": RULES_VERSION, "model": str(model_name), "language": str(language), "prefer_gpu": bool(prefer_gpu),
            "track": int(track), "narration": str(narration_sha256)}


def stored_stamp(path: Path) -> dict[str, Any] | None:
    """The stamp of the result at ``path``, or None when there is none to use."""

    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data.get("stamp") if isinstance(data, dict) and isinstance(data.get("stamp"), dict) else None


def listen_to_game_track(game_wav: Path, out_dir: Path, narration_path: Path | None, *,
                         transcriber: Callable[[Path], list[dict[str, Any]]], track: int,
                         model_name: str = "small", language: str = "en", result_stamp: dict[str, Any] | None = None,
                         on_progress: Callable[[int, int], None] | None = None,
                         piece_seconds: float = PIECE_SECONDS) -> Path:
    """Hear the game track and keep the other voices; writes ``game.speech.json`` in ``out_dir``.

    ``game_wav`` is the game track (``track``, 0-based) as decoded in Prepare's one read, and
    ``transcriber`` the shared Whisper transcriber (``voice_track.whisper_transcriber``) for
    ``model_name`` and ``language``, which the caller loads once. The language is given, not detected:
    auto-detection on long stretches of engine noise is unreliable. Whisper's retries at higher
    temperatures are off; on a long recording dominated by engine noise they can multiply the
    processing time, and a line that needs them is not one to trust here anyway.

    The track is heard ``piece_seconds`` at a time, cut from the WAV with ``PIECE_OVERLAP_SECONDS``
    more on each side, each line placed at its time in the recording and kept only by the piece its
    middle falls in, so a line said across a cut is heard whole and listed once; ``on_progress`` hears
    how many pieces are done, of how many. The result keeps the voices (``segments``), every line left
    out with its reason (``left_out``), the model, language and track, and ``result_stamp``.
    """

    out_dir.mkdir(parents=True, exist_ok=True)
    with wave.open(str(game_wav), "rb") as audio:
        seconds = audio.getnframes() / float(audio.getframerate() or 1)
    length = float(piece_seconds)
    total = max(1, math.ceil(round(seconds / length, 6)))
    cut = wav_slice_extractor({int(track): Path(game_wav)})
    work = Path(tempfile.mkdtemp(prefix=f"media_manglers_race_video_game_{os.getpid()}_", dir=str(scratch_root())))
    heard: list[dict[str, Any]] = []
    try:
        for index in range(total):
            start = index * length
            last = index == total - 1
            cut_from = max(0.0, start - PIECE_OVERLAP_SECONDS)
            cut_to = seconds if last else min(seconds, start + length + PIECE_OVERLAP_SECONDS)
            piece = cut(int(track), cut_from, max(0.0, cut_to - cut_from), work / f"piece-{index:04d}.wav")
            for segment in transcriber(piece) or []:
                item = dict(segment)
                item["start"] = cut_from + float(item.get("start") or 0.0)
                item["end"] = cut_from + float(item.get("end") or 0.0)
                middle = (item["start"] + item["end"]) / 2
                if middle >= start and (last or middle < start + length):
                    heard.append(item)
            piece.unlink(missing_ok=True)
            if on_progress is not None:
                on_progress(index + 1, total)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    narration = []
    if narration_path and narration_path.exists():
        narration = json.loads(narration_path.read_text(encoding="utf-8")).get("segments") or []
    kept, left_out = sort_game_speech(heard, narration)
    target = out_dir / "game.speech.json"
    write_json_atomic(target, {"track": int(track), "model": str(model_name), "language": str(language),
                               "stamp": dict(result_stamp or {}), "segments": kept, "left_out": left_out})
    return target
