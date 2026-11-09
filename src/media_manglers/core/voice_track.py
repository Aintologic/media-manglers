"""Per-recording detection of the operator's microphone track (94).

OBS recordings carry several audio tracks (game mix, microphone, music,
spotter ...). The operator's voice is not always on the same track, so a
remembered track number goes stale. This module listens to every track of one
recording and picks the track that carries isolated human speech:

1. One ffmpeg pass decodes every audio track to 16 kHz mono PCM.
2. Each track gets a cheap level analysis: silent tracks are dropped, and the
   share of time the track is active tells a push-to-talk style microphone
   (mostly quiet, bursts of speech) from continuous music or game audio.
3. Whisper transcribes a bounded sample of each audible track. Only confident
   segments (low no-speech probability, reasonable log-probability, not the
   filler Whisper invents on silence) count as speech.
4. The track with the most confident speech that is also mostly quiet between
   phrases wins. When no such track exists the recording has no narration;
   when two tracks are too close the result is "uncertain" and the caller
   must not guess.

The module never modifies the source recording; decoded audio lives only in
the caller's work directory and is removed afterwards. When the caller asks,
the chosen track's audio (and the usual microphone track's) is moved out
first, so transcription does not read the recording a second time (196).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from typing import Any, Callable, Iterable, Sequence

from . import streaming_progress
from .activity_timeline import per_second_db
from .scratch import scratch_root
from .sparse_narration import is_silence_hallucination_text

SAMPLE_RATE = 16000
FRAME_SECONDS = 0.05
SILENT_PEAK_DBFS = -55.0
ACTIVE_ABOVE_FLOOR_DB = 12.0
ACTIVE_MIN_DBFS = -50.0
MERGE_GAP_SECONDS = 0.6
MIN_BURST_SECONDS = 0.3
MAX_BURST_SECONDS = 15.0
CONTINUOUS_ACTIVE_RATIO = 0.5
DEFAULT_PROBE_SECONDS = 120.0
MIN_CONFIDENT_WORDS = 3
SELECTION_CONFIDENCE = 0.7
SAME_SPEECH_CONTAINMENT = 0.6
COMPETING_SCORE_SHARE = 0.5
CONFIDENT_NO_SPEECH_PROB = 0.5
CONFIDENT_AVG_LOGPROB = -1.0
# Speech on a track that is busy with other sound is never chosen, but it is
# not nothing either (142). This many clear words in the sample is someone
# talking, not a line of game radio (measured across 24 real recordings, a
# busy track that was not the narrator's voice gave at most 57), so such a
# track is always put to the operator.
BUSY_TRACK_TALKING_WORDS = 100
# A remembered track never beats clear evidence (196).
# A remembered track loses its claim over a busy track that sounds like a
# microphone with this many times its words (196).
USUAL_OUTVOICED_BY_BUSY = 0.5
# When the remembered track has no speech, a busy track with this many clear
# words of its own is put to the operator, as it would be with no memory (196).
SILENT_USUAL_TALKING_WORDS = 10
# A microphone falls close to silence between words. Inside 2-second blocks
# that have sound, busy game audio, music and full mixes swing 3-16 dB between
# their loudest and quietest frames, as measured on real recordings; a voice that
# falls close to silence between phrases swings more. Many real microphone
# tracks swing less than this too, so a high swing proves a voice
# and a low one proves nothing (142, 196).
VOICE_SWING_DB = 20.0
SWING_BLOCK_FRAMES = 40
# A track is busy too when it is loud most of the time, even if its own floor is
# so high that few frames rise 12 dB above it (144): at least half of all its
# frames at or above -50 dBFS.
LOUD_FRAME_DBFS = -50.0
LOUD_SHARE = 0.5
# ... unless its level still swings this much inside its sounding stretches:
# a microphone with a noisy floor is loud most of the time as well, but it
# falls far between phrases, and a bed does not (196).
LOUD_BED_MAX_SWING_DB = 15.0
# Speech comes in phrases. A track whose sound comes in fewer than this many
# separate bursts per minute of sound is a steady bed, not a microphone (144).
MIN_PHRASES_PER_MINUTE = 4.0
# Which selection rule made a result (196). The backend saves results for reuse and trusts
# one only when it came from this rule, so any change to how a track is chosen bumps this,
# and "Video Mangler.ps1" Read-MMSavedVoiceDetection's $voiceRuleVersion with it.
VOICE_RULE_VERSION = 5
# How speech moments are measured from a track's sound (264): the frame length, and the level and burst constants
# at the top of this file. Any change to those makes every stored measure stale, so it bumps this
# (tests/test_speech_facts_routes.py pins them). Stale moments still work for jumps until they are measured again.
ACTIVITY_RULE_VERSION = 1

# Track roles (196). OBS lets the operator name each audio track and stores the names in the
# recording. Words in a track's name, found anywhere in it and ignoring case, say what the track
# carries. These three lists are the only place the words are kept; docs/workbench/FIND_BUG_REPORTS.md
# describes them for the operator.
# - A NARRATION word makes the track the operator's voice, whatever else the name says (199:
#   a track named "T2 - Narration / Discord" is a narration track).
# - Otherwise a NEVER word means the track is never narration.
# - A FULL_MIX phrase makes the track a last resort, used only when no other track qualifies.
# A recording whose track names have none of these words (one made before the tracks were named,
# or with OBS's own "Track1" names) has no track names as far as choosing the narration goes.
NARRATION_NAME_WORDS: tuple[str, ...] = ("narration",)
NEVER_NARRATION_NAME_WORDS: tuple[str, ...] = (
    "music", "game", "simulator", "spotter", "engineer", "system", "discord", "voice chat",
)
FULL_MIX_NAME_WORDS: tuple[str, ...] = ("full mix",)
# 220: of the never-narration words, these name the game-audio track, which the activity timeline
# listens to. "Game" stays a never-narration role everywhere: it is a kind of never, not a new role.
GAME_NAME_WORDS: tuple[str, ...] = ("game", "simulator")
# 226: of the never-narration words, these name sound that is never the game audio either (music, a
# spotter, an engineer, voice chat), so the "one track left" guess never takes such a track for the
# game: its sound must never reach a video as the game. "System" is left out on purpose, because
# desktop sound is often the game. Only the track's NAME counts: a track SET to Never narration in
# Track roles stays eligible (settings made before Wave 6 used that for the game track).
NOT_GAME_AUDIO_NAME_WORDS: tuple[str, ...] = tuple(
    word for word in NEVER_NARRATION_NAME_WORDS if word not in GAME_NAME_WORDS and word != "system"
)

# A track's role: from its name, or from the Workbench setting "Auto / Narration / Never narration"
# for a recording whose tracks have no names.
ROLE_AUTO = "auto"
ROLE_NARRATION = "narration"
ROLE_NEVER = "never"
ROLE_FULL_MIX = "full_mix"
# The setting's "Game audio" choice (220). For choosing the narration it is exactly ROLE_NEVER.
ROLE_GAME = "game"
# What decided the narration track, in that order, and how the result says so.
DECIDED_BY_NAME = "track_name"
DECIDED_BY_SETTING = "setting"
DECIDED_BY_AUTO = "auto"
DECIDED_BY_TEXT = {
    DECIDED_BY_NAME: "from track name",
    DECIDED_BY_SETTING: "from your setting",
    DECIDED_BY_AUTO: "auto-detected",
}

# Phrases a racing spotter (Crew Chief and similar) says. A bursty speech track
# made mostly of these is the spotter, not the operator.
SPOTTER_PHRASES: tuple[str, ...] = (
    "car left",
    "car right",
    "clear left",
    "clear right",
    "still there",
    "three wide",
    "green flag",
    "green green",
    "yellow flag",
    "blue flag",
    "pit window",
    "box this lap",
    "here comes your timed lap",
    "fastest lap",
    "last lap",
    "laps remaining",
    # Crew Chief race-engineer call-outs heard on real recordings.
    "pit speed",
    "pitspeed",
    "miles per hour",
    "exit's clear",
    "exit is clear",
    "go go go",
    "hold your line",
    "car inside",
    "car outside",
    # Short call-outs heard on real recordings (120).
    # Only distinctive multi-word phrases belong here: a bare word such as
    # "clear" or "service" also fires inside ordinary narration, and it
    # double-counts against the longer phrases above ("clear left"), which
    # inflates the spotter-word share and mislabels real narration as game
    # audio.
    "left side",
    "right side",
    "one more",
    "seconds remaining",
    "seconds left",
    "engine stall",
    "fuel pressure",
    "box box",
)


@dataclass
class TrackActivity:
    ordinal: int
    duration_seconds: float = 0.0
    peak_dbfs: float = -120.0
    noise_floor_dbfs: float = -120.0
    active_ratio: float = 0.0
    burst_seconds: float = 0.0
    silent: bool = True
    intervals: list[tuple[float, float]] = field(default_factory=list)
    # How far the level falls between words inside busy stretches, in dB (142).
    level_swing_db: float | None = None
    # Share of all frames at or above LOUD_FRAME_DBFS (144).
    loud_share: float | None = None
    # Per-frame activity (numpy bool array); used to tell whether two tracks
    # carry the same speech at the same moments. Not serialized.
    active_flags: Any = field(default=None, repr=False, compare=False)
    # The track's level for each second, in dBFS (220): the activity timeline and the player's
    # waveform strip read it, so neither reads the recording again. Not serialized.
    second_levels: Any = field(default=None, repr=False, compare=False)


@dataclass
class TrackProbe:
    ordinal: int
    confident_words: int = 0
    spotter_words: int = 0
    probed_seconds: float = 0.0
    sample_text: str = ""


@dataclass
class TrackVerdict:
    ordinal: int
    track_number: int
    title: str
    silent: bool
    continuous: bool
    active_ratio: float
    peak_dbfs: float
    confident_words: int
    spotter_words: int
    score: float
    reason: str
    sample_text: str = ""


def _dbfs(value: float) -> float:
    if value <= 0:
        return -120.0
    return max(-120.0, 20.0 * math.log10(value / 32768.0))


def level_swing(levels_db: Any, flags: Any) -> float | None:
    """Median, over 2-second blocks with sound at least half the time, of the
    90th minus the 10th percentile frame level in dB; None when too few blocks."""

    import numpy as np

    count = min(len(levels_db), len(flags)) // SWING_BLOCK_FRAMES * SWING_BLOCK_FRAMES
    if count == 0:
        return None
    levels = np.asarray(levels_db[:count], dtype=float).reshape(-1, SWING_BLOCK_FRAMES)
    sounding = np.asarray(flags[:count], dtype=bool).reshape(-1, SWING_BLOCK_FRAMES).mean(axis=1) >= 0.5
    if int(sounding.sum()) < 3:
        return None
    spread = np.percentile(levels[sounding], 90, axis=1) - np.percentile(levels[sounding], 10, axis=1)
    return round(float(np.median(spread)), 1)


def loud_share(levels_db: Any) -> float | None:
    """Share of all frames at or above LOUD_FRAME_DBFS; None without frames (144)."""

    import numpy as np

    levels = np.asarray(levels_db, dtype=float)
    if levels.size == 0:
        return None
    return round(float(np.mean(levels >= LOUD_FRAME_DBFS)), 4)


def busy_sound(activity: TrackActivity) -> bool:
    """Music, game audio or a full mix: sound most of the time, loud most of the
    time, or sound that does not come in phrases (144)."""

    if activity.active_ratio >= CONTINUOUS_ACTIVE_RATIO:
        return True
    if activity.silent:
        return False
    if (activity.loud_share or 0.0) >= LOUD_SHARE and (
        (activity.level_swing_db or 0.0) < LOUD_BED_MAX_SWING_DB
    ):
        return True
    minutes = activity.active_ratio * activity.duration_seconds / 60.0
    return minutes <= 0 or len(activity.intervals) / minutes < MIN_PHRASES_PER_MINUTE


def noise_floor_dbfs(levels_db: Iterable[float]) -> float:
    """A track's own quiet: the level the quietest 15% of its levels stay at or under. The one rule
    (226): the activity below uses it on 50 ms frames, the AI Video Editor on stored levels per second."""

    ordered = sorted(float(value) for value in levels_db)
    return ordered[max(0, int(len(ordered) * 0.15) - 1)]


def active_threshold_dbfs(floor_dbfs: float) -> float:
    """The level a track counts as active above: ACTIVE_ABOVE_FLOOR_DB over its own quiet, and never
    below ACTIVE_MIN_DBFS."""

    return max(ACTIVE_MIN_DBFS, float(floor_dbfs) + ACTIVE_ABOVE_FLOOR_DB)


def talk_threshold_dbfs(levels_db: Iterable[float] | None) -> float | None:
    """The level a microphone counts as talking above, worked out from its levels alone (226: the AI
    Video Editor's cut points on an analysis that did not store it), by the rule of ``analyze_track_wav``,
    to 0.1 dB. None without levels, or when the track is silent (never as loud as SILENT_PEAK_DBFS)."""

    values = [float(value) for value in levels_db or []]
    if not values or max(values) < SILENT_PEAK_DBFS:
        return None
    return round(active_threshold_dbfs(noise_floor_dbfs(values)), 1)


def analyze_track_wav(path: Path, ordinal: int) -> TrackActivity:
    """Level analysis of a 16-bit mono WAV in 50 ms frames."""

    import numpy as np

    with wave.open(str(path), "rb") as reader:
        sample_rate = reader.getframerate()
        channels = reader.getnchannels()
        frame_samples = max(1, int(sample_rate * FRAME_SECONDS))
        rms_db: list[float] = []
        peak = 0
        while True:
            raw = reader.readframes(frame_samples * 2400)
            if not raw:
                break
            samples = np.frombuffer(raw, dtype="<i2")
            if channels > 1:
                samples = samples[::channels]
            if samples.size == 0:
                continue
            peak = max(peak, int(np.max(np.abs(samples.astype(np.int32)))))
            usable = (samples.size // frame_samples) * frame_samples
            if usable == 0:
                continue
            blocks = samples[:usable].astype(np.float64).reshape(-1, frame_samples)
            rms = np.sqrt(np.mean(blocks * blocks, axis=1))
            rms_db.extend(_dbfs(float(value)) for value in rms)
    return activity_from_frames(rms_db, ordinal, peak)


def activity_from_frames(rms_db: list[float], ordinal: int, peak: float) -> TrackActivity:
    """What a track's sound says, from its level for each 50 ms frame and its loudest sample: the one rule for
    a decoded WAV (``analyze_track_wav``) and for the levels read as they stream (``stream_levels``, 264)."""

    import numpy as np

    activity = TrackActivity(ordinal=ordinal)
    activity.duration_seconds = round(len(rms_db) * FRAME_SECONDS, 3)
    activity.peak_dbfs = round(_dbfs(float(peak)), 2)
    activity.second_levels = per_second_db(rms_db, round(1.0 / FRAME_SECONDS))
    if not rms_db or activity.peak_dbfs < SILENT_PEAK_DBFS:
        return activity
    floor = noise_floor_dbfs(rms_db)
    threshold = active_threshold_dbfs(floor)
    flags = [value >= threshold for value in rms_db]
    active = sum(flags)
    activity.active_flags = np.array(flags, dtype=bool)
    activity.noise_floor_dbfs = round(floor, 2)
    activity.active_ratio = round(active / len(flags), 4)
    activity.level_swing_db = level_swing(rms_db, activity.active_flags)
    activity.loud_share = loud_share(rms_db)
    activity.silent = active < max(3, int(0.002 * len(flags)))
    if activity.silent:
        return activity
    intervals: list[tuple[float, float]] = []
    start: float | None = None
    last_active = -1.0
    for index, flag in enumerate(flags):
        time_s = index * FRAME_SECONDS
        if flag:
            if start is None:
                start = time_s
            elif time_s - last_active > MERGE_GAP_SECONDS:
                intervals.append((start, last_active + FRAME_SECONDS))
                start = time_s
            last_active = time_s
    if start is not None:
        intervals.append((start, last_active + FRAME_SECONDS))
    activity.intervals = [
        (round(a, 3), round(b, 3)) for a, b in intervals if b - a >= MIN_BURST_SECONDS
    ]
    activity.burst_seconds = round(
        sum(min(b - a, MAX_BURST_SECONDS) for a, b in activity.intervals), 3
    )
    return activity


def choose_probe_windows(
    activity: TrackActivity,
    *,
    max_seconds: float = DEFAULT_PROBE_SECONDS,
    window_seconds: float = 12.0,
) -> list[tuple[float, float]]:
    """Pick up to ``max_seconds`` of the track's active audio, spread over time."""

    if activity.silent or not activity.intervals:
        return []
    pieces: list[tuple[float, float]] = []
    for start, end in activity.intervals:
        cursor = max(0.0, start - 0.3)
        end = min(activity.duration_seconds, end + 0.3)
        while cursor < end:
            piece_end = min(end, cursor + window_seconds)
            if piece_end - cursor >= MIN_BURST_SECONDS:
                pieces.append((round(cursor, 3), round(piece_end, 3)))
            cursor = piece_end
    total = sum(b - a for a, b in pieces)
    if total <= max_seconds:
        return pieces
    # Spread the budget evenly across the recording instead of taking only
    # the first minutes: narration can happen anywhere in a long session.
    average = total / len(pieces)
    wanted = max(1, min(len(pieces), int(max_seconds / max(average, 0.1))))
    if wanted == 1:
        return [pieces[len(pieces) // 2]]
    indexes = sorted({round(index * (len(pieces) - 1) / (wanted - 1)) for index in range(wanted)})
    return [pieces[index] for index in indexes]


def write_probe_wav(source_wav: Path, windows: Iterable[tuple[float, float]], destination: Path) -> float:
    """Concatenate windows of a 16 kHz mono WAV with short silences between."""

    total = 0.0
    with wave.open(str(source_wav), "rb") as reader:
        rate = reader.getframerate()
        width = reader.getsampwidth()
        channels = reader.getnchannels()
        gap = b"\x00" * int(rate * 0.5) * width * channels
        destination.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(destination), "wb") as writer:
            writer.setnchannels(channels)
            writer.setsampwidth(width)
            writer.setframerate(rate)
            for start, end in windows:
                reader.setpos(min(reader.getnframes(), int(start * rate)))
                frames = reader.readframes(max(0, int((end - start) * rate)))
                writer.writeframes(frames)
                writer.writeframes(gap)
                total += end - start
    return round(total, 3)


def _normalize_words(text: str) -> str:
    return " ".join(re.findall(r"[a-z']+", text.lower()))


def count_spotter_words(text: str) -> int:
    normalized = _normalize_words(text)
    count = 0
    for phrase in SPOTTER_PHRASES:
        occurrences = len(re.findall(rf"(?<![a-z']){re.escape(phrase)}(?![a-z'])", normalized))
        count += occurrences * len(phrase.split())
    return count


def confident_speech(segments: Iterable[dict[str, Any]]) -> tuple[int, int, str]:
    """Return (confident words, spotter words, sample text) for Whisper segments."""

    words = 0
    spotter = 0
    texts: list[str] = []
    for segment in segments:
        text = str(segment.get("text") or "").strip()
        if not text or is_silence_hallucination_text(text):
            continue
        no_speech = float(segment.get("no_speech_prob") or 0.0)
        logprob = float(segment.get("avg_logprob") or 0.0)
        if no_speech >= CONFIDENT_NO_SPEECH_PROB or logprob <= CONFIDENT_AVG_LOGPROB:
            continue
        segment_words = len(re.findall(r"[A-Za-z0-9']+", text))
        words += segment_words
        spotter += min(segment_words, count_spotter_words(text))
        texts.append(text)
    return words, spotter, " ".join(texts)[:240]


def decide(
    activities: dict[int, TrackActivity],
    probes: dict[int, TrackProbe],
    titles: dict[int, str] | None = None,
    preferred_ordinals: Iterable[int] | None = None,
    shared_speech: Iterable[tuple[int, int]] | None = None,
) -> dict[str, Any]:
    """Pure decision step, kept separate so it can be tested without audio.

    ``shared_speech`` lists track pairs already proven to carry the same
    words (for example a game mix that also contains the microphone).
    """

    shared = {frozenset(pair) for pair in (shared_speech or [])}
    preferred_set = {int(value) for value in (preferred_ordinals or [])}

    titles = titles or {}
    verdicts: list[TrackVerdict] = []
    for ordinal in sorted(activities):
        activity = activities[ordinal]
        probe = probes.get(ordinal, TrackProbe(ordinal=ordinal))
        continuous = busy_sound(activity)
        own_words = max(0, probe.confident_words - probe.spotter_words)
        spotter_heavy = probe.confident_words > 0 and probe.spotter_words >= 0.4 * probe.confident_words
        # A talkative operator keeps their own microphone track busy; that alone
        # does not make it game audio. Other busy tracks stay excluded (142).
        voice_proof = (
            _busy_voice_proof(ordinal, activities, probes)
            if continuous and ordinal in preferred_set and not spotter_heavy
            and own_words >= MIN_CONFIDENT_WORDS
            else ""
        )
        if activity.silent:
            score = 0.0
            reason = "silent"
        elif continuous and not voice_proof:
            score = 0.0
            reason = (
                "continuous sound (music, game audio or a full mix)"
                + (f" containing {probe.confident_words} spoken words" if probe.confident_words else "")
            )
        elif spotter_heavy:
            score = own_words * 0.2
            reason = "speech is mostly spotter call-outs"
        else:
            isolation = max(0.0, 1.0 - activity.active_ratio)
            score = own_words * isolation * isolation
            reason = (
                f"{probe.confident_words} confident spoken words, quiet between phrases"
                if probe.confident_words
                else "audible but no clear speech"
            )
            if voice_proof:
                reason = (
                    f"{probe.confident_words} confident spoken words; it has sound most of the time, "
                    f"but it is your usual microphone track and {voice_proof}"
                )
        verdicts.append(
            TrackVerdict(
                ordinal=ordinal,
                track_number=ordinal + 1,
                title=str(titles.get(ordinal, "")),
                silent=activity.silent,
                continuous=continuous,
                active_ratio=activity.active_ratio,
                peak_dbfs=activity.peak_dbfs,
                confident_words=probe.confident_words,
                spotter_words=probe.spotter_words,
                score=round(score, 3),
                reason=reason,
                sample_text=probe.sample_text,
            )
        )
    ranked = sorted(verdicts, key=lambda item: item.score, reverse=True)
    tracks = [asdict(item) for item in ranked]
    best = ranked[0] if ranked else None
    if best is None:
        return {"status": "no_audio", "selected_ordinal": None, "confidence": 0.0, "tracks": tracks,
                "explanation": "The recording has no audio tracks."}
    # OBS often routes the same microphone to several tracks with different
    # gain. Tracks whose speech happens at the same moments are one source.
    contenders = [
        item for item in ranked
        if item.score > 0 and item.confident_words - item.spotter_words >= MIN_CONFIDENT_WORDS
    ]
    if not contenders:
        return {**_nothing_chosen(verdicts, preferred_set, activities), "tracks": tracks}
    groups: list[list[TrackVerdict]] = []
    for item in contenders:
        for group in groups:
            # A track with sound most of the time overlaps any voice by chance,
            # so for it only matching words prove the same voice (142).
            if any(frozenset((member.ordinal, item.ordinal)) in shared for member in group) or (
                not item.continuous and not group[0].continuous
                and same_speech(activities.get(group[0].ordinal), activities.get(item.ordinal))
            ):
                group.append(item)
                break
        else:
            groups.append([item])
    group_scores = [max(member.score for member in group) for group in groups]
    lead = groups[0]
    # Within one source, the fullest capture wins: most confident words, then
    # the quieter background, then the lowest track number.
    # When one voice reaches several tracks, the operator's usual microphone
    # track is the one to transcribe: the other copies are mixes that also
    # carry the spotter and voice chat (120).
    lead_usual = [member for member in lead if member.ordinal in preferred_set]
    pool = lead_usual or lead
    # A busy usual track (142) yields to a quiet copy of the same voice (196).
    if lead_usual and all(m.continuous for m in lead_usual) and any(not m.continuous for m in lead):
        pool = [m for m in lead if not m.continuous]
    representative = sorted(
        pool,
        key=lambda item: (-(item.confident_words - item.spotter_words), item.active_ratio, item.ordinal),
    )[0]
    usual_track_note = (
        " It is your usual microphone track."
        if representative.ordinal in preferred_set and len(lead) > 1
        else ""
    )
    competing = [
        (group, score) for group, score in zip(groups[1:], group_scores[1:])
        if score >= COMPETING_SCORE_SHARE * group_scores[0]
    ]
    same_source_note = (
        f" The same voice is also on Track {', '.join(str(item.track_number) for item in lead if item is not representative)}."
        if len(lead) > 1
        else ""
    )
    # The operator's usual microphone track wins whenever it carries speech of
    # its own, even when another track (a spotter or race engineer, a voice
    # chat, a full mix) says more words (105).
    if preferred_set and not any(member.ordinal in preferred_set for member in lead):
        for group in groups[1:]:
            usual = next(
                (
                    member
                    for member in group
                    if member.ordinal in preferred_set
                    and member.spotter_words < 0.4 * max(1, member.confident_words)
                ),
                None,
            )
            if usual is not None and usual.continuous:
                # A busy usual track does not win by memory over a quiet voice; ask,
                # and let the cross-check show whether they are one voice (196).
                return {
                    "status": "uncertain",
                    "uncertain_reason": "busy_usual",
                    "selected_ordinal": None,
                    "suggested_ordinal": representative.ordinal,
                    "confidence": 0.5,
                    "tracks": tracks,
                    "explanation": (
                        f"Track {usual.track_number} is your usual microphone track, but it has sound most of the "
                        f"time, and Track {representative.track_number} carries speech and is quiet between "
                        "phrases; the microphone cannot be chosen safely."
                    ),
                    "competing_ordinals": [usual.ordinal],
                }
            if usual is not None:
                louder = ", ".join(f"Track {item.track_number}" for item in lead)
                return {
                    "status": "selected",
                    "selected_ordinal": usual.ordinal,
                    "suggested_ordinal": usual.ordinal,
                    "confidence": round(SELECTION_CONFIDENCE, 3),
                    "tracks": tracks,
                    "explanation": (
                        f"Track {usual.track_number} is your usual microphone track and carries speech; "
                        f"{louder} also carries speech (for example a spotter or a mix) and was not used."
                    ),
                }
    # A busy usual track (142) that leads on score does not win by memory either
    # while a quiet track carries speech of its own: ask, and let the cross-check
    # show whether they are one voice; if they are, the quiet copy is used (196).
    if representative.ordinal in preferred_set and representative.continuous:
        quiet = sorted(
            (member for group in groups[1:] for member in group if not member.continuous),
            key=lambda member: -member.score,
        )
        if quiet and (
            (activities[representative.ordinal].level_swing_db or 0.0) < VOICE_SWING_DB
        ):
            return {
                "status": "uncertain",
                "uncertain_reason": "busy_usual",
                "selected_ordinal": None,
                "suggested_ordinal": quiet[0].ordinal,
                "confidence": 0.5,
                "tracks": tracks,
                "explanation": (
                    f"Track {representative.track_number} is your usual microphone track, but it has sound "
                    f"most of the time, and Track {quiet[0].track_number} carries speech and is quiet "
                    "between phrases; the microphone cannot be chosen safely."
                ),
                "competing_ordinals": [representative.ordinal],
            }
    if competing and preferred_set:
        for group in [lead, *[group for group, _score in competing]]:
            if any(member.ordinal in preferred_set for member in group):
                chosen = next(member for member in group if member.ordinal in preferred_set)
                if chosen.continuous and group is not lead:
                    return {
                        "status": "uncertain",
                        "uncertain_reason": "busy_usual",
                        "selected_ordinal": None,
                        "suggested_ordinal": representative.ordinal,
                        "confidence": 0.5,
                        "tracks": tracks,
                        "explanation": (
                            f"Track {chosen.track_number} is your usual microphone track, but it has sound most of the "
                            f"time, and Track {representative.track_number} carries speech and is quiet between "
                            "phrases; the microphone cannot be chosen safely."
                        ),
                        "competing_ordinals": [chosen.ordinal],
                    }
                return {
                    "status": "selected",
                    "selected_ordinal": chosen.ordinal,
                    "suggested_ordinal": chosen.ordinal,
                    "confidence": round(SELECTION_CONFIDENCE, 3),
                    "tracks": tracks,
                    "explanation": (
                        f"Track {chosen.track_number} carries speech and is your usual microphone track; "
                        "another track also carries different speech."
                    ),
                }
    total = sum(group_scores[: 1 + len(competing)])
    confidence = round(group_scores[0] / total, 3) if total > 0 else 0.0
    if competing:
        other = max(competing, key=lambda pair: pair[1])[0][0]
        return {
            "status": "uncertain",
            "uncertain_reason": "competing_voices",
            "selected_ordinal": None,
            "suggested_ordinal": representative.ordinal,
            "confidence": confidence,
            "tracks": tracks,
            "explanation": (
                f"Track {representative.track_number} and Track {other.track_number} carry different "
                "speech; the microphone cannot be chosen safely."
            ),
            "competing_ordinals": [group[0].ordinal for group, _score in competing],
        }
    # A busy track that falls silent between phrases is a voice too, just not one
    # the rule may choose; with that much speech it competes with the winner (142).
    busy_voices = [
        item.ordinal for item in verdicts
        if item.continuous and item.score <= 0 and _spoken(item)
        and (
            (activities[item.ordinal].level_swing_db or 0.0) >= VOICE_SWING_DB
            # A busy usual pick is a voice only by 142's proof, so any busy track
            # with that much speech of its own competes with it (196).
            or (representative.ordinal in preferred_set and representative.continuous)
        )
        and _own_words(item) >= (
            USUAL_OUTVOICED_BY_BUSY if representative.ordinal in preferred_set else COMPETING_SCORE_SHARE
        ) * _own_words(representative)
        and frozenset((item.ordinal, representative.ordinal)) not in shared
    ]
    # The usual track is asked about too when a busy voice clearly says more (196).
    if busy_voices:
        return {
            "status": "uncertain",
            "uncertain_reason": "busy_voice",
            "selected_ordinal": None,
            "suggested_ordinal": representative.ordinal,
            "confidence": 0.5,
            "tracks": tracks,
            "explanation": (
                f"Track {representative.track_number} carries speech"
                + (" and is your usual microphone track" if representative.ordinal in preferred_set
                   else " and is quiet between phrases")
                + ", but "
                f"Track {busy_voices[0] + 1} also carries a lot of speech and falls close to silence between "
                "phrases like a microphone, although it has sound most of the time; the microphone "
                "cannot be chosen safely."
            ),
            "competing_ordinals": busy_voices,
        }
    return {
        "status": "selected",
        "selected_ordinal": representative.ordinal,
        "suggested_ordinal": representative.ordinal,
        # One voice on several tracks and no usual track among them: the pick is
        # by track order, so it must not teach the run a usual track (142).
        "confidence": (
            SELECTION_CONFIDENCE if len(lead) > 1 and not lead_usual else max(confidence, SELECTION_CONFIDENCE)
        ),
        "tracks": tracks,
        "explanation": (
            f"Track {representative.track_number} carries your narration "
            f"({representative.reason}).{same_source_note}{usual_track_note}"
        ),
        "selection_reason": (
            "usual_microphone_track_in_shared_group"
            if representative.ordinal in preferred_set and len(lead) > 1
            else ("only_track_with_isolated_speech" if len(contenders) == 1 else "highest_isolated_speech_score")
        ),
    }


def _own_words(item: TrackVerdict) -> int:
    return max(0, item.confident_words - item.spotter_words)


def _spoken(item: TrackVerdict) -> bool:
    """The track carries clear speech of its own once spotter call-outs are taken off.

    A track that is mostly call-outs still counts when enough of its own words
    are left: a full mix carries the spotter AND the operator (142).
    """

    return not item.silent and _own_words(item) >= MIN_CONFIDENT_WORDS


def _join_tracks(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _nothing_chosen(
    verdicts: list[TrackVerdict], preferred: set[int], activities: dict[int, TrackActivity] | None = None
) -> dict[str, Any]:
    """No track can be chosen by the rule: ask, or say plainly why there is no narration (142).

    The rule above only chooses speech on a track that is quiet between
    phrases. Speech on a track that is busy with other sound as well (a full
    mix, game audio, music) is not chosen, and it is not nothing either: a
    recording may carry everything on one track and the microphone alone on
    another, and when the narrator talks a lot both are busy. So the recording
    is only called one with no narration when the speech that is left could not
    be the narrator's: the usual microphone track says nothing, and the other
    tracks carry no more than a little speech. Otherwise the operator is asked.
    Nothing is put forward to be picked for the operator, and "silent" is only
    said of a track that is.
    """

    speech = sorted((item for item in verdicts if _spoken(item)), key=lambda item: (-_own_words(item), item.ordinal))
    # A usual track this recording does not have is no usual track at all.
    usual = next((item for item in verdicts if item.ordinal in preferred), None)
    ask = [
        item
        for item in speech
        if usual is None
        or item is usual
        or _own_words(item) >= BUSY_TRACK_TALKING_WORDS
        # A busy track that falls close to silence between phrases is a voice (196).
        or (
            _own_words(item) >= SILENT_USUAL_TALKING_WORDS
            and ((activities or {}).get(item.ordinal) is not None)
            and ((activities[item.ordinal].level_swing_db or 0.0) >= VOICE_SWING_DB)
        )
        # Quiet between phrases, with speech of its own, and still not
        # chosen: the rule above could not settle it either.
        or not item.continuous
    ]
    if ask:
        # Counts are what each track said besides spotter call-outs: the same
        # number the choice is made on and the tracks are ordered by.
        named = [
            f"Track {item.track_number} ({_own_words(item)}{' clear words' if index == 0 else ''})"
            for index, item in enumerate(speech)
        ]
        # "Busy" is only said when it is true of every track named.
        busy = all(item.continuous for item in speech)
        if len(speech) == 1:
            only = speech[0]
            explanation = (
                f"Track {only.track_number} carries speech ({_own_words(only)} clear words), but "
                + (
                    "it is also busy with other sound (a full mix, game audio or music), so "
                    if busy
                    else ""
                )
                + "the app cannot tell whether it is your microphone."
            )
        else:
            explanation = f"{_join_tracks(named)} carry speech, but " + (
                "each of them is also busy with other sound (a full mix, game audio or music), so "
                if busy
                else ""
            ) + "the app cannot tell which one is your microphone."
        if usual is not None and usual in speech:
            explanation += f" Track {usual.track_number} is your usual microphone track."
        return {
            "status": "uncertain",
            "uncertain_reason": "speech_on_busy_tracks",
            "selected_ordinal": None,
            # Asking means asking. A suggestion would also start the search
            # for a shared voice in detect_voice_track, which cannot turn
            # "every speaking track is busy" into a choice.
            "suggested_ordinal": None,
            "confidence": 0.0,
            "competing_ordinals": [item.ordinal for item in speech],
            "explanation": explanation + " Choose the track with your voice.",
        }
    parts: list[str] = []
    if usual is not None:
        # The usual track has no speech of its own here: a track that has
        # some is always in ``ask`` above.
        own = _own_words(usual)
        if usual.silent:
            state = "is silent"
        elif usual.confident_words == 0:
            state = "has sound but no clear speech"
        elif own == 0:
            state = "carries only spotter call-outs"
        else:
            state = f"has only {own} clear word{'s' if own != 1 else ''} of speech"
        parts.append(f"Your usual microphone track, Track {usual.track_number}, {state}.")
    if speech:
        listed = ", ".join(f"Track {item.track_number} ({_own_words(item)} words)" for item in speech)
        parts.append(
            f"The only {'other ' if usual is not None else ''}speech is a little, on tracks that are busy with "
            f"other sound such as game audio: {listed}."
        )
    else:
        parts.insert(0, "No audio track carries clear speech.")
    return {
        "status": "no_narration_found",
        "selected_ordinal": None,
        "confidence": 0.0,
        "explanation": " ".join(parts),
    }


def _busy_voice_proof(ordinal: int, activities: dict[int, TrackActivity], probes: dict[int, TrackProbe]) -> str:
    """Why the words on a busy usual microphone track are a voice, or "" (142).

    Either its level falls close to silence between phrases, or another track
    has sound at the same moments with at most a tenth of its words, so the
    words are not part of that sound. A copy of game audio shows neither.
    """

    import numpy as np

    activity = activities[ordinal]
    if (activity.level_swing_db or 0.0) >= VOICE_SWING_DB:
        return "its level falls close to silence between phrases, as a microphone does"
    probe = probes.get(ordinal, TrackProbe(ordinal=ordinal))
    words = max(0, probe.confident_words - probe.spotter_words)
    mine = np.asarray(activity.active_flags if activity.active_flags is not None else [], dtype=bool)
    for other in sorted(activities):
        bed = activities[other]
        if other == ordinal or bed.silent or bed.active_flags is None or not mine.any():
            continue
        if probes.get(other, TrackProbe(ordinal=other)).confident_words > 0.1 * words:
            continue
        length = min(len(mine), len(bed.active_flags))
        together = np.logical_and(mine[:length], np.asarray(bed.active_flags[:length], dtype=bool)).sum()
        if together / max(1, int(mine[:length].sum())) >= SAME_SPEECH_CONTAINMENT:
            return (
                f"Track {other + 1} has sound at the same moments but not these words, "
                "so the words are not part of that sound"
            )
    return ""


def _word_set(segments: Iterable[dict[str, Any]]) -> set[str]:
    words: set[str] = set()
    for segment in segments:
        text = str(segment.get("text") or "")
        if is_silence_hallucination_text(text):
            continue
        words.update(word for word in re.findall(r"[a-z']+", text.lower()) if len(word) >= 3)
    return words


def shares_speech(lead_words: set[str], other_words: set[str], *, threshold: float = 0.4) -> bool:
    """True when another track repeats most of what the lead track said."""

    if len(lead_words) < 3 or not other_words:
        return False
    return len(lead_words & other_words) / len(lead_words) >= threshold


def same_speech(left: TrackActivity | None, right: TrackActivity | None) -> bool:
    """True when two tracks are active at the same moments (one microphone, two routes)."""

    if left is None or right is None:
        return False
    left_flags = left.active_flags
    right_flags = right.active_flags
    if left_flags is None or right_flags is None:
        return False
    length = min(len(left_flags), len(right_flags))
    if length == 0:
        return False
    import numpy as np

    a = np.asarray(left_flags[:length], dtype=bool)
    b = np.asarray(right_flags[:length], dtype=bool)
    smaller = min(int(a.sum()), int(b.sum()))
    if smaller == 0:
        return False
    return float(np.logical_and(a, b).sum()) / smaller >= SAME_SPEECH_CONTAINMENT


def _run(command: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
    )


def probe_audio_streams(ffprobe_exe: str, source: Path) -> tuple[list[dict[str, Any]], float]:
    result = _run(
        [
            ffprobe_exe, "-v", "error", "-select_streams", "a",
            "-show_entries", "stream=index,codec_name,channels:stream_tags=title,language",
            "-show_entries", "format=duration", "-of", "json", str(source),
        ],
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe could not read the recording: {result.stderr.strip()[:300]}")
    data = json.loads(result.stdout or "{}")
    streams = list(data.get("streams") or [])
    duration = float((data.get("format") or {}).get("duration") or 0.0)
    return streams, duration


# 145: a decode is stopped only when it stops moving, never for taking long. A large recording on a
# slow drive can take far longer than its own length to read, and that is fine while it progresses.
# 224 (Wave B2a): the one way of following such a read lives in streaming_progress; these names stay.
DECODE_STALL_SECONDS = streaming_progress.STALL_SECONDS
SUSPENDED_GAP_SECONDS = streaming_progress.SUSPENDED_GAP_SECONDS
# Decode position goes to the progress file at most this often.
DECODE_REPORT_SECONDS = streaming_progress.REPORT_SECONDS


def clock(seconds: float) -> str:
    """A time in a recording as people read it: "05:07", or "1:05:07" past the first hour. The one
    clock every feature writes (226: the AI Video Editor's digest uses it too)."""

    seconds = max(0, int(seconds))
    return f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}" if seconds >= 3600 else         f"{seconds // 60:02d}:{seconds % 60:02d}"


# Its name before 226, for everything that imports it so.
_clock = clock
_stop_tree = streaming_progress.stop_tree


def ffmpeg_position(line: str) -> float | None:
    """How far into the recording one line of FFmpeg's ``-progress`` output says it is, in seconds.

    FFmpeg 8 keeps printing the same position and "progress=continue" twice a second while its input is
    stuck; the reader counts only a later position as movement, so those lines prove nothing."""

    key, _, value = line.strip().partition("=")
    return int(value) / 1_000_000 if key == "out_time_us" and value.isdigit() else None


def run_while_progressing(
    command: list[str],
    *,
    stall_seconds: float,
    stderr_path: Path,
    on_progress: Callable[[float], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[int, float]:
    """Run an FFmpeg command that writes ``-progress pipe:1``, for as long as it keeps moving.

    Returns the exit code and how far into the recording it got, in seconds. Raises ``RuntimeError``
    with a plain reason when it makes no progress for ``stall_seconds``, after stopping it.
    ``on_progress`` is told each new position, in seconds.
    """

    finished = streaming_progress.run(
        command,
        read_line=ffmpeg_position,
        stall_message=lambda at: (
            f"Reading the recording's audio stopped making progress: nothing new for "
            f"{int(stall_seconds)} seconds, {_clock(at)} into the recording. "
            "The drive may have gone to sleep or been disconnected."
        ),
        stall_seconds=stall_seconds,
        stderr_path=stderr_path,
        on_progress=on_progress,
        clock=clock,
    )
    return finished.returncode, finished.position


# 214: a stream the caller names itself: "0:a:<n>" (the n-th audio track) or "0:<n>" (stream n of the file).
_STREAM_MAP = re.compile(r"^0:(?:a:)?\d+$")


def _pcm_output(map_spec: str, target: Path) -> list[str]:
    # The one WAV every feature transcribes: 16 kHz mono 16-bit PCM.
    return ["-map", map_spec, "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", str(target)]


def _mp3_output(map_spec: str, target: Path) -> list[str]:
    # 214: the package's listening copy (Package any video for AI, Transcript Only's kept audio).
    return ["-map", map_spec, "-vn", "-c:a", "libmp3lame", "-b:a", "192k", str(target)]


AUDIO_FORMATS = {"wav": _pcm_output, "mp3": _mp3_output}


def _decode(
    ffmpeg_exe: str,
    source: Path,
    outputs: list[str],
    work_dir: Path,
    *,
    stall_seconds: float,
    on_progress: Callable[[float], None] | None,
    input_options: Sequence[str] = (),
) -> None:
    """Run one FFmpeg read of ``source`` with these outputs, for as long as it keeps moving (145).

    ``input_options`` go just before ``-i`` (226: "decode only the keyframes" for a picture output in
    the same read). Without them the command is exactly what it was.
    """

    work_dir.mkdir(parents=True, exist_ok=True)
    command = [ffmpeg_exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-nostats", "-progress", "pipe:1",
               "-y", *[str(option) for option in input_options], "-i", str(source), *outputs]
    errors = work_dir / "decode-errors.txt"
    returncode, _reached = run_while_progressing(command, stall_seconds=stall_seconds, stderr_path=errors,
                                                 on_progress=on_progress)
    message = errors.read_text(encoding="utf-8", errors="replace").strip()
    errors.unlink(missing_ok=True)
    if returncode != 0:
        raise RuntimeError(f"ffmpeg could not decode the audio tracks: {message[:300]}")


def extract_all_tracks(
    ffmpeg_exe: str,
    source: Path,
    stream_count: int,
    work_dir: Path,
    *,
    duration_seconds: float = 0.0,
    stall_seconds: float = DECODE_STALL_SECONDS,
    on_progress: Callable[[float], None] | None = None,
    ordinals: Iterable[int] | None = None,
    input_options: Sequence[str] = (),
    extra_outputs: Sequence[str] = (),
) -> dict[int, Path]:
    """Decode every audio track (or only ``ordinals``) to its own 16 kHz mono WAV in one pass.

    There is no time limit: the decode goes on while FFmpeg is still moving through the recording,
    and is stopped only when it makes no progress for ``stall_seconds`` (145). ``on_progress`` is
    told how far into the recording the decode is, in seconds.

    226: ``input_options`` go before ``-i`` and ``extra_outputs`` after the tracks' outputs, so the
    same read can also write another output (the game picture's keyframes, for signal 2 of 217).
    The WAVs are byte for byte what they are without them, and without them the command is unchanged.
    """

    selected = range(stream_count) if ordinals is None else [int(value) for value in ordinals]
    outputs = {ordinal: work_dir / f"track-{ordinal}.wav" for ordinal in selected}
    arguments: list[str] = []
    for ordinal, target in outputs.items():
        arguments += _pcm_output(f"0:a:{ordinal}", target)
    arguments += [str(item) for item in extra_outputs]
    _decode(ffmpeg_exe, source, arguments, work_dir, stall_seconds=stall_seconds, on_progress=on_progress,
            input_options=input_options)
    return outputs


def decode_work_dir(destination: Path) -> Path:
    """Where ``extract_wav`` decodes before the WAV takes its own name."""

    destination = Path(destination)
    return destination.parent / f".{destination.stem}-decode"


def extract_wav(
    ffmpeg_exe: str,
    source: Path,
    destination: Path,
    *,
    ffmpeg_map: str | None = None,
    mix_ordinals: Iterable[int] | None = None,
    work_dir: Path | None = None,
    stall_seconds: float = DECODE_STALL_SECONDS,
    on_progress: Callable[[float], None] | None = None,
    audio_format: str = "wav",
    seek_seconds: float | None = None,
    limit_seconds: float | None = None,
) -> Path:
    """214: one 16 kHz mono WAV every feature transcribes, by the one decoder: no time limit while
    FFmpeg keeps moving, stopped when it makes no progress for ``stall_seconds`` (145).
    ``audio_format="mp3"`` makes the package's 192 kbit/s MP3 of one track the same way.

    ``ffmpeg_map`` names one stream ("0:a:1", or "0:2" by its absolute index); ``mix_ordinals``
    instead mixes those audio tracks into one (Full Review's all-tracks review mix). The decode is
    made in ``work_dir`` (next to the WAV by default, so the last step is a rename) and the WAV takes
    its name only when FFmpeg has finished: a decode that fails, stalls or is stopped from outside
    never leaves a part of the track under the WAV's name. What a stopped earlier run left in
    ``work_dir`` is removed first. ``seek_seconds`` and ``limit_seconds`` (264) read one short piece by seeking;
    without them the command is unchanged.
    """

    destination = Path(destination)
    output = AUDIO_FORMATS.get(str(audio_format or "wav").lower())
    if output is None:
        raise ValueError(f"Not an audio format the decoder makes: {audio_format!r}.")
    mix = [int(value) for value in (mix_ordinals or [])]
    if mix:
        pads = "".join(f"[0:a:{ordinal}]" for ordinal in mix)
        target_map = "[aout]"
        prefix = ["-filter_complex", f"{pads}amix=inputs={len(mix)}:duration=longest:normalize=0[aout]"]
    else:
        if ffmpeg_map is None or not _STREAM_MAP.match(str(ffmpeg_map).strip()):
            raise ValueError(f"Not an audio stream to read: {ffmpeg_map!r}. Expected 0:a:<n> or 0:<n>.")
        target_map = str(ffmpeg_map).strip()
        prefix = []
    folder = Path(work_dir) if work_dir is not None else decode_work_dir(destination)
    shutil.rmtree(folder, ignore_errors=True)
    decoded = folder / f"track.{str(audio_format or 'wav').lower()}"
    try:
        piece: list[str] = []
        if seek_seconds is not None:
            piece += ["-ss", f"{float(seek_seconds):.3f}"]
        if limit_seconds is not None:
            piece += ["-t", f"{float(limit_seconds):.3f}"]
        _decode(ffmpeg_exe, source, prefix + output(target_map, decoded), folder,
                stall_seconds=stall_seconds, on_progress=on_progress, input_options=piece)
        if not decoded.is_file():
            raise RuntimeError("ffmpeg finished but wrote no audio.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(decoded, destination)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return destination


def extract_track(
    ffmpeg_exe: str,
    source: Path,
    ordinal: int,
    destination: Path,
    *,
    stall_seconds: float = DECODE_STALL_SECONDS,
    on_progress: Callable[[float], None] | None = None,
) -> Path:
    """214: one audio track as the 16 kHz mono WAV every feature transcribes (``extract_wav``)."""

    return extract_wav(ffmpeg_exe, source, destination, ffmpeg_map=f"0:a:{int(ordinal)}",
                       stall_seconds=stall_seconds, on_progress=on_progress)


Transcriber = Callable[[Path], list[dict[str, Any]]]


def whisper_transcriber(model_name: str, prefer_gpu: bool, language_code: str, *,
                        word_timestamps: bool = False) -> Transcriber:
    # 214: the model is loaded where every other Whisper model is, in the shared helper.
    # 226: ``word_timestamps`` asks Whisper for each word's time too, and each segment keeps its
    # "words" (the AI Video Editor's cut points). The decode settings are the same either way.
    from media_manglers.providers.whisper_local import load_whisper_model, pick_whisper_device

    device = pick_whisper_device(prefer_gpu)
    model = load_whisper_model(model_name, device)

    def transcribe(path: Path) -> list[dict[str, Any]]:
        options: dict[str, Any] = {"word_timestamps": True} if word_timestamps else {}
        result = model.transcribe(
            str(path),
            language=language_code or None,
            task="transcribe",
            verbose=None,
            fp16=device == "cuda",
            condition_on_previous_text=False,
            temperature=0.0,
            **options,
        )
        return list(result.get("segments") or [])

    transcribe.device = device  # type: ignore[attr-defined]
    return transcribe


def role_from_name(title: str) -> str:
    """The role a track's name gives it: never narration, narration, full mix (last resort) or auto."""

    name = " ".join(str(title or "").casefold().split())
    if any(word in name for word in NARRATION_NAME_WORDS):
        return ROLE_NARRATION
    if any(word in name for word in NEVER_NARRATION_NAME_WORDS):
        return ROLE_NEVER
    if any(word in name for word in FULL_MIX_NAME_WORDS):
        return ROLE_FULL_MIX
    return ROLE_AUTO


def roles_from_text(value: Any) -> dict[str, str]:
    """The Track roles setting as the mapping the role rules here read (226: shared from the raw bin,
    so the AI Video Editor reads it the same way): the saved text "2=narration,3=game" (or a mapping
    already) as ``{"2": "narration", "3": "game"}``, keyed by track number. ``parse_track_roles`` and
    ``game_audio_track`` take what this gives."""

    if isinstance(value, dict):
        return {str(key): str(role) for key, role in value.items()}
    roles: dict[str, str] = {}
    for part in str(value or "").replace(";", ",").split(","):
        number, _, role = part.partition("=")
        if number.strip().isdigit() and role.strip():
            roles[number.strip()] = role.strip().casefold()
    return roles


def game_mix_roles_key(value: Any) -> str:
    """The Game audio and Full mix roles of the Track roles setting in one fixed form, "1=full_mix,3=game",
    to tell when idle time must be worked out again. Narration and Never narration are left out: the
    narration track is chosen by listening, so a change to those reaches a recording when it is read."""

    roles = roles_from_text(value)
    return ",".join(f"{number}={roles[number]}" for number in sorted(roles, key=int)
                    if roles[number] in (ROLE_GAME, ROLE_FULL_MIX))


def parse_track_roles(value: Any) -> dict[int, str]:
    """The Workbench setting as ``{ordinal: role}``, from ``{"2": "narration", ...}`` keyed by track
    number (1 = Track 1) or a list in track order. Auto and anything unknown are left out."""

    if isinstance(value, dict):
        items = list(value.items())
    elif isinstance(value, (list, tuple)):
        items = list(enumerate(value, start=1))
    else:
        return {}
    roles: dict[int, str] = {}
    for key, role in items:
        try:
            number = int(str(key).strip())
        except ValueError:
            continue
        role_value = str(role or "").strip().casefold()
        if role_value == ROLE_GAME:
            role_value = ROLE_NEVER  # the game track is never narration (220)
        # "Full mix" (220) is what a track named "Full Mix" is: narration only when nothing else qualifies.
        if number >= 1 and role_value in (ROLE_NARRATION, ROLE_NEVER, ROLE_FULL_MIX):
            roles[number - 1] = role_value
    return roles


def _setting_tracks(value: Any, wanted: str) -> set[int]:
    if isinstance(value, dict):
        items = list(value.items())
    elif isinstance(value, (list, tuple)):
        items = list(enumerate(value, start=1))
    else:
        return set()
    found: set[int] = set()
    for key, role in items:
        try:
            number = int(str(key).strip())
        except ValueError:
            continue
        if number >= 1 and str(role or "").strip().casefold() == wanted:
            found.add(number - 1)
    return found


def parse_game_tracks(value: Any) -> set[int]:
    """The ordinals the Workbench setting marks "Game audio" (220), from the same value as
    ``parse_track_roles``."""

    return _setting_tracks(value, ROLE_GAME)


def full_mix_track(titles: dict[int, str], *, setting_value: Any = None,
                   sounding: Iterable[int] | None = None, narration_ordinal: int | None = None) -> int | None:
    """The recording's full mix (220): the track named so, then the one Track roles marks "Full mix",
    then a recording's only track, or the only track with any sound (everything was recorded there).
    Those last two are never a track that is the narration, never narration or the game audio, by its
    name or the setting. None when it cannot tell."""

    ordinals = sorted(titles)
    named = [ordinal for ordinal in ordinals if role_from_name(titles[ordinal]) == ROLE_FULL_MIX]
    if named:
        return named[0]
    chosen = sorted(_setting_tracks(setting_value, ROLE_FULL_MIX) & set(ordinals))
    if chosen:
        return chosen[0]
    _source, roles = track_roles(titles, parse_track_roles(setting_value))
    taken = {ordinal for ordinal, role in roles.items() if role in (ROLE_NARRATION, ROLE_NEVER)}
    taken |= _setting_tracks(setting_value, ROLE_GAME) | ({narration_ordinal} if narration_ordinal is not None else set())
    free = [ordinal for ordinal in ordinals if ordinal not in taken]
    if len(ordinals) == 1:
        return free[0] if free else None
    heard = sorted(set(sounding or ()) & set(free))
    return heard[0] if len(heard) == 1 and len(set(sounding or ()) & set(ordinals)) == 1 else None


def game_audio_track(
    titles: dict[int, str],
    *,
    setting_value: Any = None,
    narration_ordinal: int | None = None,
    activities: dict[int, "TrackActivity"] | None = None,
) -> tuple[int | None, str]:
    """The game-audio track by its role (220), never by a fixed number, and what decided it.

    Track names come first ("Game", "Simulator"), then the setting's "Game audio" choice, then the
    one track left that is neither the narration track nor a full mix. A track that carries the
    narration's speech at the same moments is a mix, not the game. A track whose name says it is
    music, a spotter, an engineer, Discord or voice chat (``NOT_GAME_AUDIO_NAME_WORDS``) is never the
    track left either (226); a track only SET to Never narration still can be. Returns
    (None, reason) when it cannot tell. When the setting names the game track, no other track is ever
    picked instead: a recording without that track gets (None, the reason).
    """

    ordinals = sorted(titles)
    named = [ordinal for ordinal in ordinals
             if any(word in " ".join(str(titles[ordinal] or "").casefold().split()) for word in GAME_NAME_WORDS)
             and role_from_name(titles[ordinal]) != ROLE_NARRATION]
    if named:
        return named[0], DECIDED_BY_NAME
    wanted = sorted(parse_game_tracks(setting_value))
    chosen = [ordinal for ordinal in wanted if ordinal in set(ordinals)]
    if chosen:
        return chosen[0], DECIDED_BY_SETTING
    if wanted:
        count = len(ordinals)
        return None, (f"this recording has no Track {wanted[0] + 1}, your game audio "
                      f"(it has {count} audio track{'' if count == 1 else 's'})")
    mixes = _setting_tracks(setting_value, ROLE_FULL_MIX)
    left = [ordinal for ordinal in ordinals
            if ordinal != narration_ordinal and ordinal not in mixes
            and role_from_name(titles[ordinal]) not in (ROLE_FULL_MIX, ROLE_NARRATION)]
    if narration_ordinal is not None and activities:
        voice = activities.get(narration_ordinal)
        left = [ordinal for ordinal in left if not same_speech(voice, activities.get(ordinal))]
    if activities:
        left = [ordinal for ordinal in left if ordinal in activities and not activities[ordinal].silent]
    named_never = [ordinal for ordinal in left if not_game_audio_name(titles[ordinal])]
    if left and len(named_never) == len(left):
        return None, named_never_reason(titles, named_never)
    left = [ordinal for ordinal in left if ordinal not in named_never]
    if len(left) == 1:
        return left[0], DECIDED_BY_AUTO
    return None, ("no track is left once the narration and the full mix are set aside" if not left
                  else "more than one track could be the game audio; name it or set it in Settings")


def not_game_audio_name(title: str) -> bool:
    """True when a track's name says it never carries the game audio (226)."""

    name = " ".join(str(title or "").casefold().split())
    return any(word in name for word in NOT_GAME_AUDIO_NAME_WORDS)


def named_never_reason(titles: dict[int, str], ordinals: Iterable[int]) -> str:
    """Why no track is the game audio when every track left is named as never narration (226). The
    raw bin re-applies its stored automatic picks with exactly this text."""

    tracks = [f"Track {int(ordinal) + 1} ({str(titles.get(int(ordinal)) or '').strip()})" for ordinal in ordinals]
    if len(tracks) == 1:
        return f"the only track left, {tracks[0]}, is named as never narration"
    return f"the tracks left, {_join_tracks(tracks)}, are named as never narration"


def is_named_never_reason(reason: str) -> bool:
    """True for a reason ``named_never_reason`` wrote."""

    text = str(reason or "")
    return text.startswith(("the only track left, ", "the tracks left, ")) and text.endswith(" named as never narration")


def track_roles(titles: dict[int, str], setting_roles: dict[int, str] | None = None) -> tuple[str, dict[int, str]]:
    """What decides this recording's narration track, and each track's role (196).

    Track names in the recording come first. A recording without track names uses the setting.
    Otherwise every track is Auto and the track is detected.
    """

    named = {ordinal: role_from_name(title) for ordinal, title in titles.items()}
    if any(role != ROLE_AUTO for role in named.values()):
        return DECIDED_BY_NAME, named
    setting = {ordinal: (setting_roles or {}).get(ordinal, ROLE_AUTO) for ordinal in titles}
    if any(role != ROLE_AUTO for role in setting.values()):
        return DECIDED_BY_SETTING, setting
    return DECIDED_BY_AUTO, {ordinal: ROLE_AUTO for ordinal in titles}


def _numbers(ordinals: Iterable[int]) -> str:
    return _join_tracks([f"Track {int(ordinal) + 1}" for ordinal in ordinals])


CrossCheck = Callable[[int, list[int]], "list[tuple[int, int]] | None"]


def decide_with_roles(
    activities: dict[int, TrackActivity],
    probes: dict[int, TrackProbe],
    titles: dict[int, str] | None = None,
    preferred_ordinals: Iterable[int] | None = None,
    setting_roles: dict[int, str] | None = None,
    cross_check: CrossCheck | None = None,
) -> dict[str, Any]:
    """Choose the narration track by track names, then the setting, then detection (196).

    ``cross_check(lead, others)`` plays the lead track's speech moments from the other tracks and
    returns the pairs that carry the same words, or None when the lead has no speech to play. The
    result says what decided it in ``decided_by`` / ``decided_by_text`` and at the start of its
    explanation, so every place that shows the explanation shows that too.
    """

    titles = {ordinal: str((titles or {}).get(ordinal, "")) for ordinal in activities}
    preferred = [int(value) for value in (preferred_ordinals or [])]
    source, roles = track_roles(titles, setting_roles)
    ordinals = sorted(activities)
    narration = [ordinal for ordinal in ordinals if roles.get(ordinal) == ROLE_NARRATION]
    never = [ordinal for ordinal in ordinals if roles.get(ordinal) == ROLE_NEVER]
    mixes = [ordinal for ordinal in ordinals if roles.get(ordinal) == ROLE_FULL_MIX]

    def among(chosen: list[int]) -> dict[str, Any]:
        subset = set(chosen)
        acts = {ordinal: item for ordinal, item in activities.items() if ordinal in subset}
        heard = {ordinal: item for ordinal, item in probes.items() if ordinal in subset}
        usual = [ordinal for ordinal in preferred if ordinal in subset]
        decision = decide(acts, heard, titles, usual)
        shared: list[tuple[int, int]] = []
        checked: set[int] = set()
        while decision.get("status") == "uncertain" and cross_check is not None:
            lead = decision.get("suggested_ordinal")
            others = [int(value) for value in decision.get("competing_ordinals") or [] if int(value) not in checked]
            if lead is None or not others:
                break
            found = cross_check(int(lead), others)
            if found is None:
                break
            checked.update(others)
            shared.extend(found)
            decision = decide(acts, heard, titles, usual, shared)
        return decision

    def why(ordinal: int) -> str:
        if source == DECIDED_BY_NAME:
            return f'it is named "{titles.get(ordinal, "")}"'
        return "your setting says it carries your narration"

    if len(narration) == 1:
        ordinal = narration[0]
        probe = probes.get(ordinal, TrackProbe(ordinal=ordinal))
        own = max(0, probe.confident_words - probe.spotter_words)
        decision = {"tracks": decide(activities, probes, titles)["tracks"]}
        if activities[ordinal].silent or own < MIN_CONFIDENT_WORDS:
            decision.update({
                "status": "no_narration_found",
                "selected_ordinal": None,
                "confidence": 0.0,
                "explanation": (
                    f"Track {ordinal + 1} is your narration track ({why(ordinal)}), "
                    "and it has no clear speech in this recording."
                ),
            })
        else:
            decision.update({
                "status": "selected",
                "selected_ordinal": ordinal,
                "suggested_ordinal": ordinal,
                "confidence": 1.0,
                "explanation": f"Track {ordinal + 1} carries your narration: {why(ordinal)}.",
                "selection_reason": "named_narration_track" if source == DECIDED_BY_NAME else "narration_track_setting",
            })
        decided_by = source
    elif narration:
        # Several tracks are narration: the one with the operator's speech among them is detected.
        decision = among(narration)
        decided_by = source
    else:
        allowed = [ordinal for ordinal in ordinals if roles.get(ordinal, ROLE_AUTO) == ROLE_AUTO]
        decision = among(allowed) if allowed else {
            "status": "no_narration_found", "selected_ordinal": None, "confidence": 0.0, "tracks": [],
            "explanation": "No audio track may carry narration.",
        }
        # A full mix is used only when nothing else qualifies.
        if mixes and decision.get("status") in ("no_narration_found", "no_audio"):
            decision = among(allowed + mixes)
        decided_by = DECIDED_BY_AUTO
        left_out = never + ([ordinal for ordinal in mixes if ordinal != decision.get("selected_ordinal")]
                            if decision.get("status") == "selected" else [])
        if never:
            whose = "their names say" if source == DECIDED_BY_NAME else "your setting says"
            decision["explanation"] = (
                f"{decision.get('explanation', '')} {_numbers(never)} {'was' if len(never) == 1 else 'were'} "
                f"left out: {whose} {'it is' if len(never) == 1 else 'they are'} never narration."
            ).strip()
        listed = {int(item.get("ordinal", -1)) for item in decision.get("tracks") or []}
        everything = decide(activities, probes, titles)["tracks"]
        decision["tracks"] = list(decision.get("tracks") or []) + [
            item for item in everything if int(item["ordinal"]) in left_out and int(item["ordinal"]) not in listed
        ]
    label = DECIDED_BY_TEXT[decided_by]
    decision["decided_by"] = decided_by
    decision["decided_by_text"] = label
    decision["track_roles"] = {str(ordinal + 1): roles.get(ordinal, ROLE_AUTO) for ordinal in ordinals}
    decision["explanation"] = f"{label[0].upper()}{label[1:]}: {decision.get('explanation', '')}"
    return decision


def detect_voice_track(
    source: Path,
    *,
    ffmpeg_exe: str = "ffmpeg",
    ffprobe_exe: str = "ffprobe",
    work_dir: Path | None = None,
    transcriber: Transcriber | None = None,
    model_name: str = "base.en",
    prefer_gpu: bool = True,
    language_code: str = "en",
    probe_seconds: float = DEFAULT_PROBE_SECONDS,
    keep_work_dir: bool = False,
    preferred_ordinals: Iterable[int] | None = None,
    progress: Callable[[str], None] | None = None,
    keep_wavs_dir: Path | None = None,
    setting_roles: dict[int, str] | None = None,
    decoded: tuple[list[dict[str, Any]], float, dict[int, Path]] | None = None,
    library: bool = False,
    game_setting: Any = None,
    details: bool = False,
) -> dict[str, Any]:
    # ``setting_roles``: the Workbench's per-track setting, ``{ordinal: "narration" | "never"}``; it
    # is used only for a recording whose tracks have no names (196).
    # ``decoded``: (streams, duration, {ordinal: wav}) when the caller has already read the recording
    # once and decoded every track (the raw bin scan, 220); the recording is then not opened here.
    # ``library``: the raw bin's mode (220). Every track with sound is listened to, not only the
    # tracks that may be the narration, so speech on the wrong track is found; the choice itself is
    # made by exactly the same rules. The result also carries each track's activity, its short
    # listen, and its level for each second ("track_levels", kept out of anything saved as JSON).
    # ``details`` (264): the result carries the same three things, ``track_activity`` with each track's moments,
    # without widening who is listened to. They are personal: ``speech_facts`` stores them and takes them out of
    # what any feature keeps (``strip_details``).
    # ``keep_wavs_dir``: when a track is chosen or the operator is asked, the decoded audio of the
    # chosen track and of the usual microphone track is moved there and listed as
    # ``kept_track_wavs``, so the narration does not have to be read from the recording again.
    # ``progress`` hears each real step, in plain words. The backend shows it as the activity and
    # stops the helper only when nothing new arrives for a long time, so every step that can take
    # a while says so first. No message may start with "Transcription": the Workbench reads that
    # prefix as a recording's final state.
    def report(message: str) -> None:
        if progress is not None:
            progress(f"Finding your voice: {message}")

    last_decode_report = [-DECODE_REPORT_SECONDS]

    def decode_moved(at: float) -> None:
        if time.monotonic() - last_decode_report[0] < DECODE_REPORT_SECONDS:
            return
        last_decode_report[0] = time.monotonic()
        report(f"reading the audio, {_clock(at)} of {_clock(duration)}" if duration > 0 else
               f"reading the audio, {_clock(at)} in")

    # Read once: the usual track is needed again after the decision.
    preferred_ordinals = [int(value) for value in (preferred_ordinals or [])]
    report("looking at the audio tracks")
    if decoded is not None:
        streams, duration = list(decoded[0]), float(decoded[1] or 0.0)
    else:
        streams, duration = probe_audio_streams(ffprobe_exe, source)
    titles = {
        index: str((stream.get("tags") or {}).get("title") or "")
        for index, stream in enumerate(streams)
    }
    base = {"source_path": str(source), "audio_track_count": len(streams), "duration_seconds": duration,
            "rule_version": VOICE_RULE_VERSION}
    if not streams:
        return {**base, "status": "no_audio", "selected_ordinal": None, "confidence": 0.0, "tracks": [],
                "explanation": "The recording has no audio tracks.", "kept_track_wavs": []}
    owned_dir = work_dir is None
    root = Path(tempfile.mkdtemp(prefix=f"media_manglers_voice_helper_{os.getpid()}_", dir=str(scratch_root()))) if owned_dir \
        else Path(work_dir) / "voice-track-probe"
    try:
        if decoded is not None:
            wavs = dict(decoded[2])
        else:
            wavs = extract_all_tracks(ffmpeg_exe, source, len(streams), root, duration_seconds=duration,
                                      on_progress=decode_moved)
        activities: dict[int, TrackActivity] = {}
        for ordinal, path in wavs.items():
            report(f"measuring Track {ordinal + 1} of {len(wavs)}")
            activities[ordinal] = analyze_track_wav(path, ordinal)

        def piece_of_wav(ordinal: int, windows: list[tuple[float, float]], destination: Path) -> float:
            return write_probe_wav(wavs[ordinal], windows, destination)

        decision, probes, roles = _listen_and_decide(
            activities, titles, len(streams), preferred_ordinals, setting_roles, write_piece=piece_of_wav, root=root,
            transcriber=transcriber, load_transcriber=lambda: whisper_transcriber(model_name, prefer_gpu, language_code),
            report=report, probe_seconds=probe_seconds, library=library)
        kept: list[dict[str, Any]] = []
        if keep_wavs_dir is not None and decision.get("status") in ("selected", "uncertain"):
            wanted = {int(ordinal) for ordinal in preferred_ordinals if int(ordinal) in wavs}
            if decision.get("selected_ordinal") is not None:
                wanted.add(int(decision["selected_ordinal"]))
            if wanted:
                # A move to another drive is a copy, which takes a while on a long recording.
                report("keeping the decoded audio for the narration")
                kept = keep_track_wavs(wavs, sorted(wanted), Path(keep_wavs_dir))
        decision["kept_track_wavs"] = kept
        if library or details:
            decision.update(_library_details(activities, probes))
            decision["track_titles"] = {str(ordinal + 1): title for ordinal, title in titles.items()}
        if library:
            voice = decision.get("selected_ordinal")
            if voice is None:
                named = [ordinal for ordinal, role in roles.items() if role == ROLE_NARRATION]
                voice = named[0] if len(named) == 1 else None
            game, game_by = game_audio_track(titles, setting_value=game_setting,
                                             narration_ordinal=None if voice is None else int(voice),
                                             activities=activities)
            decision["game_ordinal"] = game
            decision["game_decided_by"] = game_by if game is not None else ""
            decision["game_reason"] = "" if game is not None else game_by
        report("done")
        return {**base, **decision}
    finally:
        if not keep_work_dir:
            shutil.rmtree(root, ignore_errors=True)


def _listen_and_decide(
    activities: dict[int, TrackActivity],
    titles: dict[int, str],
    stream_count: int,
    preferred_ordinals: list[int],
    setting_roles: dict[int, str] | None,
    *,
    write_piece: Callable[[int, list[tuple[float, float]], Path], float],
    root: Path,
    transcriber: Transcriber | None,
    load_transcriber: Callable[[], Transcriber],
    report: Callable[[str], None],
    probe_seconds: float = DEFAULT_PROBE_SECONDS,
    library: bool = False,
    stopped: Callable[[], bool] | None = None,
) -> tuple[dict[str, Any], dict[int, TrackProbe], dict[int, str]]:
    """Listen to the tracks that may be the narration and choose: the one rule, however the sound was read
    (``write_piece`` writes one track's windows to a WAV, from a decoded track or by short seeks, 264). ``stopped``
    is asked before each listen; when it says so, ``ListeningStopped`` ends the listening with nothing decided."""

    candidates = [ordinal for ordinal, activity in activities.items() if not activity.silent]
    # Only tracks that can be the narration are listened to: the narration track alone when
    # names or the setting give one, and never a track that is never narration (196).
    # The raw bin listens to every track with sound except a full mix (220).
    role_source, roles = track_roles(titles, setting_roles)
    narration = [ordinal for ordinal in candidates if roles.get(ordinal) == ROLE_NARRATION]
    named_narration = [ordinal for ordinal, role in roles.items() if role == ROLE_NARRATION]
    if library:
        candidates = [ordinal for ordinal in candidates if roles.get(ordinal) != ROLE_FULL_MIX]
    else:
        candidates = narration if named_narration else [
            ordinal for ordinal in candidates if roles.get(ordinal) != ROLE_NEVER
        ]
    probes: dict[int, TrackProbe] = {}
    if candidates and transcriber is None:
        report("loading the speech model")
        transcriber = load_transcriber()

    def check_stop() -> None:
        if stopped is not None and stopped():
            raise ListeningStopped()

    for position, ordinal in enumerate(candidates, start=1):
        windows = choose_probe_windows(activities[ordinal], max_seconds=probe_seconds)
        if not windows:
            continue
        check_stop()
        report(f"listening to Track {ordinal + 1} ({position} of {len(candidates)})")
        probe_wav = root / f"probe-{ordinal}.wav"
        seconds = write_piece(ordinal, windows, probe_wav)
        segments = transcriber(probe_wav) if transcriber else []
        words, spotter, sample = confident_speech(segments)
        probes[ordinal] = TrackProbe(
            ordinal=ordinal,
            confident_words=words,
            spotter_words=spotter,
            probed_seconds=seconds,
            sample_text=sample,
        )
    if stream_count == 1 and roles.get(0) == ROLE_NEVER:
        # The only track is never narration, by its name or the setting (196).
        why = f'it is named "{titles.get(0, "")}"' if role_source == DECIDED_BY_NAME else "your setting says so"
        label = DECIDED_BY_TEXT[role_source]
        decision = {
            "status": "no_narration_found",
            "selected_ordinal": None,
            "confidence": 0.0,
            "tracks": [],
            "explanation": f"{label[0].upper()}{label[1:]}: the only audio track is never narration ({why}).",
            "decided_by": role_source,
            "decided_by_text": label,
            "track_roles": {"1": ROLE_NEVER},
        }
    elif stream_count == 1:
        only = activities.get(0, TrackActivity(ordinal=0))
        probe = probes.get(0, TrackProbe(ordinal=0))
        if only.silent or probe.confident_words < MIN_CONFIDENT_WORDS:
            decision = {
                "status": "no_narration_found",
                "selected_ordinal": None,
                "confidence": 0.0,
                "tracks": [],
                "explanation": "Auto-detected: the only audio track has no clear speech.",
            }
        else:
            decision = {
                "status": "selected",
                "selected_ordinal": 0,
                "suggested_ordinal": 0,
                "confidence": 1.0,
                "tracks": [],
                "explanation": "Auto-detected: the recording has one audio track; it is used for narration.",
            }
        decision.update({"decided_by": DECIDED_BY_AUTO, "decided_by_text": DECIDED_BY_TEXT[DECIDED_BY_AUTO]})
    else:
        # A game or stream mix also contains the microphone. When two tracks
        # look like different voices, play the leading track's speech moments
        # from the other track: if the same words come back, they share the
        # operator's speech and are not competing voices.
        def cross_check(lead: int, others: list[int]) -> list[tuple[int, int]] | None:
            lead_windows = choose_probe_windows(activities[lead], max_seconds=40.0)
            if not lead_windows:
                return None
            check_stop()
            report(f"checking Track {lead + 1}'s speech against the other tracks")
            lead_probe = root / f"cross-{lead}-{lead}.wav"
            write_piece(lead, lead_windows, lead_probe)
            lead_words = _word_set(transcriber(lead_probe))
            found: list[tuple[int, int]] = []
            for other in others:
                check_stop()
                report(f"checking whether Track {lead + 1} and Track {other + 1} carry the same voice")
                other_probe = root / f"cross-{lead}-{other}.wav"
                write_piece(other, lead_windows, other_probe)
                if shares_speech(lead_words, _word_set(transcriber(other_probe))):
                    found.append((lead, other))
            return found

        decision = decide_with_roles(activities, probes, titles, preferred_ordinals, setting_roles,
                                     cross_check if transcriber is not None else None)
    decision["device"] = str(getattr(transcriber, "device", "")) if transcriber else ""
    return decision, probes, roles


class ListeningStopped(Exception):
    """Asked to stop while listening (``detect_from_activities``): nothing was decided."""


def detect_from_activities(
    source: Path,
    activities: dict[int, TrackActivity],
    streams: list[dict[str, Any]],
    duration: float,
    *,
    ffmpeg_exe: str,
    work_dir: Path,
    transcriber: Transcriber | None = None,
    model_name: str = "base.en",
    language_code: str = "en",
    setting_roles: dict[int, str] | None = None,
    preferred_ordinals: Iterable[int] | None = None,
    stopped: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Choose the narration track of a recording whose sound was measured as it streamed, with no decoded tracks
    kept (264, the background job): short pieces of the tracks that may be the narration are read by seeking, and
    listened to on the processor, never the graphics card, so a game running alongside has it to itself."""

    titles = {index: str((stream.get("tags") or {}).get("title") or "") for index, stream in enumerate(streams)}
    root = Path(work_dir) / "voice-listen"
    root.mkdir(parents=True, exist_ok=True)

    def piece_by_seeking(ordinal: int, windows: list[tuple[float, float]], destination: Path) -> float:
        total = 0.0
        with wave.open(str(destination), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(SAMPLE_RATE)
            gap = b"\x00" * int(SAMPLE_RATE * 0.5) * 2
            for start, end in windows:
                piece = root / "piece.wav"
                extract_wav(ffmpeg_exe, source, piece, ffmpeg_map=f"0:a:{int(ordinal)}", seek_seconds=start,
                            limit_seconds=end - start)
                with wave.open(str(piece), "rb") as reader:
                    writer.writeframes(reader.readframes(reader.getnframes()))
                writer.writeframes(gap)
                total += end - start
        return round(total, 3)

    try:
        decision, probes, _roles = _listen_and_decide(
            activities, titles, len(streams), [int(value) for value in (preferred_ordinals or [])], setting_roles,
            write_piece=piece_by_seeking, root=root, transcriber=transcriber,
            load_transcriber=lambda: whisper_transcriber(model_name, False, language_code),
            report=lambda _message: None, stopped=stopped)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return {"source_path": str(source), "audio_track_count": len(streams), "duration_seconds": duration,
            "rule_version": VOICE_RULE_VERSION, **decision, "kept_track_wavs": [],
            "track_titles": {str(ordinal + 1): title for ordinal, title in titles.items()},
            **_library_details(activities, probes)}


def track_details(activities: dict[int, TrackActivity]) -> dict[str, Any]:
    """What ``details`` adds to a result, for a read that listened to nothing (264, the AI Video Editor)."""

    return _library_details(activities, {})


def strip_details(result: dict[str, Any]) -> dict[str, Any]:
    """The result with its per-track details taken out, so moments and levels never reach anything a feature keeps
    (a package's saved result, a portable ZIP, a log, 264)."""

    return {key: value for key, value in result.items()
            if key not in ("track_activity", "track_probes", "track_levels", "track_titles")}


def _library_details(activities: dict[int, TrackActivity], probes: dict[int, TrackProbe]) -> dict[str, Any]:
    """What the raw bin keeps about each track (220), keyed by track number (1 = Track 1)."""

    activity: dict[str, Any] = {}
    heard: dict[str, Any] = {}
    levels: dict[int, list[float]] = {}
    for ordinal, item in sorted(activities.items()):
        activity[str(ordinal + 1)] = {
            "silent": bool(item.silent),
            "active_seconds": round(sum(end - start for start, end in item.intervals), 1),
            "active_ratio": item.active_ratio,
            "noise_floor_dbfs": item.noise_floor_dbfs,
            "peak_dbfs": item.peak_dbfs,
            "intervals": [[round(start, 1), round(end, 1)] for start, end in item.intervals],
            # 264: what ``speech_facts`` keeps: each moment to the frame, and what the choice of a track read.
            "moments": [[round(start, 2), round(end, 2)] for start, end in item.intervals],
            "level_swing_db": item.level_swing_db,
            "loud_share": item.loud_share,
        }
        levels[ordinal] = list(item.second_levels or [])
    for ordinal, probe in sorted(probes.items()):
        heard[str(ordinal + 1)] = {
            "confident_words": probe.confident_words,
            "spotter_words": probe.spotter_words,
            "own_words": max(0, probe.confident_words - probe.spotter_words),
            "probed_seconds": round(probe.probed_seconds, 1),
        }
    return {"track_activity": activity, "track_probes": heard, "track_levels": levels}


def keep_track_wavs(wavs: dict[int, Path], ordinals: Iterable[int], keep_dir: Path) -> list[dict[str, Any]]:
    """Move these tracks' decoded WAVs into ``keep_dir`` as ``track-<ordinal>.wav`` and list them.

    A track that cannot be read or moved is left out: keeping audio only saves work later, so it
    never fails the detection. The caller then reads that track from the recording as before.
    """

    kept: list[dict[str, Any]] = []
    for ordinal in ordinals:
        source = wavs.get(int(ordinal))
        if source is None or not source.is_file():
            continue
        target = keep_dir / f"track-{int(ordinal)}.wav"
        try:
            with wave.open(str(source), "rb") as audio:
                rate, channels, frames = audio.getframerate(), audio.getnchannels(), audio.getnframes()
            keep_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
        except (OSError, EOFError, wave.Error):
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        kept.append({
            "ordinal": int(ordinal),
            "track_number": int(ordinal) + 1,
            "path": str(target),
            "sample_rate_hz": rate,
            "channels": channels,
            "seconds": round(frames / rate, 3) if rate else 0.0,
        })
    return kept


def _progress_writer(path_value: str, first_message: str = "Finding your voice: starting") -> Callable[[str], None] | None:
    """Write each message where the backend's stall watchdog reads it.

    The plain format (message, elapsed time, UTC time) with no stage or device, so the Workbench
    shows the message as it is. The file is replaced whole, never half-written. A write can fail
    while the backend is reading the file; the next step writes again, so that is not an error.
    """

    if not path_value:
        return None
    path = Path(path_value)
    started = time.monotonic()

    def write(message: str, attempts: int = 1) -> None:
        state = {
            "message": message,
            "elapsed_seconds": round(time.monotonic() - started, 1),
            "updated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        temporary = path.with_name(path.name + ".tmp")
        for attempt in range(attempts):
            try:
                temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
                os.replace(temporary, path)
                return
            except OSError:
                if attempt + 1 < attempts:
                    time.sleep(0.2)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass

    # Written at once and retried briefly: until the first state arrives, the backend can only
    # count the helper's whole running time against it.
    write(first_message, attempts=10)
    return write


def detect_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    source_value = str(payload.get("source_path") or "").strip()
    if not source_value:
        raise ValueError("source_path is required.")
    ffmpeg_exe = str(payload.get("ffmpeg_exe") or "ffmpeg")
    ffprobe_exe = str(payload.get("ffprobe_exe") or "")
    if not ffprobe_exe:
        ffmpeg_path = Path(ffmpeg_exe)
        ffprobe_exe = str(ffmpeg_path.with_name(ffmpeg_path.name.replace("ffmpeg", "ffprobe"))) if ffmpeg_path.parent != Path(".") else "ffprobe"
    work_dir_value = str(payload.get("work_dir") or "").strip()
    keep_value = str(payload.get("keep_wavs_dir") or "").strip()
    return detect_voice_track(
        Path(source_value),
        ffmpeg_exe=ffmpeg_exe,
        ffprobe_exe=ffprobe_exe,
        work_dir=Path(work_dir_value) if work_dir_value else None,
        model_name=str(payload.get("model_name") or "base.en"),
        prefer_gpu=bool(payload.get("prefer_gpu", True)),
        language_code=str(payload.get("language_code") or "en"),
        probe_seconds=float(payload.get("probe_seconds") or DEFAULT_PROBE_SECONDS),
        preferred_ordinals=[
            int(value) for value in (payload.get("preferred_ordinals") or []) if str(value).strip().lstrip("-").isdigit()
        ],
        progress=_progress_writer(str(payload.get("progress_state_file_path") or "").strip()),
        keep_wavs_dir=Path(keep_value) if keep_value else None,
        setting_roles=parse_track_roles(payload.get("track_roles")),
        details=bool(payload.get("details")),
    )


def extract_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """214: the backend's narration WAV (Export-TranscriptSourceWav) and all-tracks mix, by the one decoder.

    Progress goes to ``progress_state_file_path`` in the plain format the backend relays and watches
    (message, elapsed time, UTC time), written as the decode moves. No message starts with
    "Transcription": the Workbench reads that prefix as a recording's final state.
    """

    source_value = str(payload.get("source_path") or "").strip()
    output_value = str(payload.get("output_path") or "").strip()
    if not source_value or not output_value:
        raise ValueError("source_path and output_path are required.")
    mix = [int(value) for value in (payload.get("mix_ordinals") or []) if str(value).strip().lstrip("-").isdigit()]
    ffmpeg_map = str(payload.get("ffmpeg_map") or "").strip() or None
    if not mix and ffmpeg_map is None:
        raise ValueError("ffmpeg_map or mix_ordinals is required.")
    duration = float(payload.get("duration_seconds") or 0.0)
    work_value = str(payload.get("work_dir") or "").strip()
    progress = _progress_writer(str(payload.get("progress_state_file_path") or "").strip(),
                                first_message="Reading the recording's audio: starting")
    last_report = [-DECODE_REPORT_SECONDS]

    def moved(at: float) -> None:
        if progress is None or time.monotonic() - last_report[0] < DECODE_REPORT_SECONDS:
            return
        last_report[0] = time.monotonic()
        progress(f"Reading the recording's audio, {_clock(at)} of {_clock(duration)}" if duration > 0 else
                 f"Reading the recording's audio, {_clock(at)} in")

    destination = extract_wav(
        str(payload.get("ffmpeg_exe") or "ffmpeg"),
        Path(source_value),
        Path(output_value),
        ffmpeg_map=None if mix else ffmpeg_map,
        mix_ordinals=mix or None,
        work_dir=Path(work_value) if work_value else None,
        stall_seconds=float(payload.get("stall_seconds") or DECODE_STALL_SECONDS),
        on_progress=moved,
        audio_format=str(payload.get("audio_format") or "wav"),
    )
    if progress is not None:
        progress("Reading the recording's audio: done")
    return {"output_path": str(destination), "bytes": destination.stat().st_size,
            "ffmpeg_map": "" if mix else str(ffmpeg_map), "mix_ordinals": mix}


# 125 Part 2, 135 (Wave 8): the sound level of every track, measured while the one decoder reads the
# recording, for the player's waveform lanes. Each track becomes exactly the 16 kHz mono 16-bit samples
# every feature transcribes (one conversion, as ``_pcm_output`` makes them), the tracks are merged
# into one stream on FFmpeg's output, and each second is measured as it arrives with the Raw bin's own
# rule: 50 ms frames as in ``analyze_track_wav``, then one level per second by power
# (``activity_timeline.per_second_db``). No WAV is written. While ``paused()`` is true nothing is read,
# so FFmpeg waits on its full output and stops reading the drive; ``stopped()`` ends the read with
# what was measured so far; a later read can start again at a second this one reached.
LEVELS_BLOCK_SECONDS = 5


def _levels_command(ffmpeg_exe: str, source: Path, ordinals: list[int], start_second: int,
                    duration: float | None = None) -> list[str]:
    # Merged tracks end with the shortest one, so each is padded with silence to the recording's
    # length: a track that stops early must not cut the others short.
    remaining = max(0.0, float(duration) - int(start_second)) if duration and len(ordinals) > 1 else 0.0
    pad = f",apad=whole_dur={remaining:.3f}" if remaining > 0 else ""
    pads = [f"[0:a:{ordinal}]aformat=sample_fmts=s16:sample_rates={SAMPLE_RATE}:channel_layouts=mono{pad}[a{place}]"
            for place, ordinal in enumerate(ordinals)]
    if len(pads) == 1:
        graph = pads[0].replace("[a0]", "[levels]")
    else:
        merged = "".join(f"[a{place}]" for place in range(len(pads)))
        graph = ";".join(pads) + f";{merged}amerge=inputs={len(pads)}[levels]"
    seek = ["-ss", str(int(start_second))] if start_second > 0 else []
    return [ffmpeg_exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-nostats", *seek, "-i", str(source),
            "-filter_complex", graph, "-map", "[levels]", "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1"]


def _frame_levels(samples: Any, channel: int, frame: int) -> list[float]:
    import numpy as np

    values = samples[:, channel]
    usable = (values.size // frame) * frame
    if usable == 0:
        return []
    blocks = values[:usable].astype(np.float64).reshape(-1, frame)
    return [_dbfs(float(value)) for value in np.sqrt(np.mean(blocks * blocks, axis=1))]


def stream_levels(
    ffmpeg_exe: str,
    source: Path,
    ordinals: Iterable[int],
    work_dir: Path,
    *,
    on_seconds: Callable[[int, dict[int, list[float]]], None],
    start_second: int = 0,
    paused: Callable[[], bool] | None = None,
    stopped: Callable[[], bool] | None = None,
    stall_seconds: float = DECODE_STALL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    duration: float | None = None,
    on_frames: Callable[[int, dict[int, list[float]], dict[int, int]], None] | None = None,
) -> tuple[int, bool]:
    """Measure every listed track, one level per second, in one read of ``source``.

    ``duration`` (the recording's length) lets a track that ends early be measured as silence to the
    end. ``on_seconds(first_second, {ordinal: levels})`` is told each new run of whole seconds.
    ``on_frames(first_second, {ordinal: 50 ms levels}, {ordinal: loudest sample})`` (264) is told the same run first,
    with what ``activity_from_frames`` reads, so a stopped read keeps both at the same place. Returns how
    many seconds were measured from ``start_second`` and whether the read was stopped on purpose.
    Raises ``RuntimeError`` with a plain reason when FFmpeg fails or makes no progress for
    ``stall_seconds`` while it is not paused (145); FFmpeg and anything it started are then stopped.
    """

    import queue

    import numpy as np

    from .activity_timeline import per_second_db

    tracks = [int(value) for value in ordinals]
    if not tracks:
        return 0, False
    channels = len(tracks)
    frame = int(SAMPLE_RATE * FRAME_SECONDS)
    frames_per_second = round(1.0 / FRAME_SECONDS)
    second_bytes = SAMPLE_RATE * channels * 2
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    errors = work_dir / "levels-errors.txt"
    blocks: queue.Queue[bytes | None] = queue.Queue(maxsize=2)
    measured = 0
    pending = b""
    was_stopped = False

    def emit(raw: bytes, *, last: bool) -> None:
        nonlocal measured
        whole = len(raw) if last else (len(raw) // second_bytes) * second_bytes
        if whole <= 0:
            return
        samples = np.frombuffer(raw[: whole - whole % (channels * 2)], dtype="<i2").reshape(-1, channels)
        frames = {ordinal: _frame_levels(samples, place, frame) for place, ordinal in enumerate(tracks)}
        found = {ordinal: per_second_db(values, frames_per_second) for ordinal, values in frames.items()}
        count = max((len(values) for values in found.values()), default=0)
        if count:
            if on_frames is not None:
                loudest = {ordinal: int(np.max(np.abs(samples[:, place].astype(np.int32)))) if samples.size else 0
                           for place, ordinal in enumerate(tracks)}
                on_frames(int(start_second) + measured, frames, loudest)
            on_seconds(int(start_second) + measured, found)
            measured += count

    flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) | int(getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))
    with errors.open("w", encoding="utf-8", errors="replace") as stderr:
        process = subprocess.Popen(_levels_command(ffmpeg_exe, source, tracks, int(start_second), duration),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=stderr,
                                   creationflags=flags)

        def read() -> None:
            stream = process.stdout
            try:
                while True:
                    chunk = stream.read(second_bytes * LEVELS_BLOCK_SECONDS) if stream is not None else b""
                    blocks.put(chunk or None)
                    if not chunk:
                        return
            except (OSError, ValueError):
                blocks.put(None)

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        moved = last_look = clock()
        try:
            while True:
                now = clock()
                if now - last_look > SUSPENDED_GAP_SECONDS:
                    moved = min(moved + (now - last_look), now)
                last_look = now
                if stopped is not None and stopped():
                    was_stopped = True
                    break
                if paused is not None and paused():
                    moved = now
                    time.sleep(0.2)
                    continue
                try:
                    chunk = blocks.get(timeout=0.2)
                except queue.Empty:
                    if now - moved > stall_seconds:
                        raise RuntimeError(
                            f"Reading the recording's audio stopped making progress: nothing new for "
                            f"{int(stall_seconds)} seconds, {_clock(int(start_second) + measured)} into the "
                            "recording. The drive may have gone to sleep or been disconnected."
                        )
                    continue
                moved = clock()
                if chunk is None:
                    emit(pending, last=True)
                    pending = b""
                    break
                pending += chunk
                whole = (len(pending) // second_bytes) * second_bytes
                emit(pending[:whole], last=False)
                pending = pending[whole:]
        except BaseException:
            _stop_tree(process)
            raise
        if was_stopped:
            _stop_tree(process)
        else:
            process.wait()
        deadline = time.monotonic() + 5
        while reader.is_alive() and time.monotonic() < deadline:
            # After a stop the reader may be waiting to hand over a block nobody will take now.
            try:
                while True:
                    blocks.get_nowait()
            except queue.Empty:
                pass
            reader.join(timeout=0.05)
    message = errors.read_text(encoding="utf-8", errors="replace").strip()
    errors.unlink(missing_ok=True)
    if not was_stopped and process.returncode not in (0, None) and measured == 0:
        raise RuntimeError(f"ffmpeg could not read the audio tracks: {message[:300]}")
    return measured, was_stopped
