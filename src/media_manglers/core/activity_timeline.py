"""When is someone actually driving? The shared activity timeline (217).

One engine job for every feature that needs to tell active stretches from dead time: the raw bin
library (idle time and sorting), later the AI Video Editor (cutting dead time) and Find my bug reports
(skipping it). Wave 6 uses the cheapest signal only, signal 1: the game-audio track, chosen by its
role (never by a fixed track number), staying quiet for a long time. The game paused, a menu, or the
operator away from the rig all leave the game track near its own floor.

Input is the game track's level for each second, in dBFS, from the same one-pass decode that voice
detection already makes, so the recording is not read again. Output is the idle and active stretches
with their times, and the share of the recording that was idle.

Wave 7 (226) adds signal 2: the game picture not changing. Small gray pictures of the game region
(64x36, from the recording's keyframes, read in the same pass as the sound) give each second the
share of the picture that changed; a minute or more of still picture is idle, and "black" when the
screen is dark. ``combined_timeline`` joins the two signals: idle when either finds a minute or more,
each stretch saying which signal found it. Signal 1 and its results are unchanged. Everything here is
pure: the decoding is done by the callers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import re
from typing import Any, Iterable, Sequence

# A second is quiet when the game track sits within this many dB of its own floor (the 15th
# percentile of its seconds) and below an absolute ceiling: a game that is running is never this
# quiet for long, and a quiet track floor alone is not proof (a constant engine drone has a high one).
IDLE_ABOVE_FLOOR_DB = 6.0
IDLE_CEILING_DBFS = -40.0
# Quiet for at least this long is idle time; shorter gaps (a slow corner, a pit stop) are driving.
IDLE_MIN_SECONDS = 60
# Seconds of sound inside a quiet stretch shorter than this do not break it (a menu click, a beep).
IDLE_BRIDGE_SECONDS = 5
# A track with no level at all.
SILENT_DBFS = -120.0
# A track is silent the whole recording when fewer than this many seconds rise above the idle ceiling:
# it would read as all idle, which cannot be told from a track that recorded nothing (220).
SOUND_MIN_SECONDS = 3
# Signal 1's rule, as stamped on every game-audio timeline; the raw bin's stored values come from it.
TIMELINE_RULE_VERSION = 2
STATUS_MEASURED = "measured"
# Measured from the full mix because the game-audio track is missing or silent (220).
STATUS_ESTIMATED = "estimated"
STATUS_UNKNOWN = "unknown"

# Signal 2, the game picture (226). Each sample is the game region shrunk to 64x36 gray: a cell is
# 30x30 pixels of a 1920x1080 panel, so compression noise averages out and a small overlay (an OBS
# camera, a clock) covers only a few cells.
PICTURE_SAMPLE_WIDTH = 64
PICTURE_SAMPLE_HEIGHT = 36
# Each sample is compared with the latest one at least this much earlier, so how densely keyframes
# come (or a sample repeated to fill a second) never makes a moving picture read as unchanged.
PICTURE_COMPARE_SECONDS = 1.0
# A cell changed when its gray level moved by more than this, of 255...
PICTURE_CELL_CHANGE_LEVEL = 8
# ...and the picture is still when at most this share of its cells changed.
PICTURE_STILL_MAX_SHARE = 0.01
# A second covered only by two samples farther apart than this is not measured.
PICTURE_MAX_GAP_SECONDS = 10.0
# Less of the recording measured than this, and the picture signal is unknown.
PICTURE_MIN_MEASURED_SHARE = 0.8
# A still stretch whose middle gray level is at or below this is a black screen.
PICTURE_BLACK_LUMA = 24
# Each signal keeps its own rule version; the joined rule has its own.
GAME_AUDIO_RULE_VERSION = 2
GAME_PICTURE_RULE_VERSION = 1
COMBINED_RULE_VERSION = 3
SIGNAL_GAME_AUDIO = "game_audio"
SIGNAL_GAME_PICTURE = "game_picture"
PICTURE_STILL = "still"
PICTURE_BLACK = "black"

# Speech closer together than this is one stretch for "jump to speech" (the raw bin, 220), and a
# stretch shorter than this is left out.
SPEECH_MERGE_SECONDS = 10.0
SPEECH_MIN_SECONDS = 2.0


def spans(flags: Sequence[bool], gap: int) -> list[tuple[int, int]]:
    """Runs of ``True`` seconds as ``(start, end)``; runs closer than ``gap`` seconds are joined.

    Shared by the AI Video Editor's talk and sound-spike detection and the activity timeline.
    """

    found: list[tuple[int, int]] = []
    start = last = None
    for second, on in enumerate(flags):
        if not on:
            continue
        if start is None or second - last > gap:
            if start is not None:
                found.append((start, last + 1))
            start = second
        last = second
    if start is not None:
        found.append((start, last + 1))
    return found


@dataclass
class ActivityTimeline:
    status: str  # "measured", "estimated" (from the full mix), or "unknown" with the reason
    duration_seconds: int = 0
    idle_seconds: int = 0
    idle_share: float | None = None
    idle_stretches: list[tuple[int, int]] = field(default_factory=list)
    active_stretches: list[tuple[int, int]] = field(default_factory=list)
    game_track: int | None = None  # 0-based ordinal
    reason: str = ""
    rule_version: int = TIMELINE_RULE_VERSION
    # 226, signal 2 and the joined timeline. Each is empty on a game-audio timeline.
    idle_by: list[list[str]] = field(default_factory=list)  # which signal(s) found each idle stretch
    picture_kinds: list[str] = field(default_factory=list)  # "still", "black", or "" (sound only), per stretch
    signals: dict[str, dict[str, Any]] = field(default_factory=dict)  # each signal's own status and reason
    region: str = ""  # the part of the picture measured: "center panel", "whole frame"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["idle_stretches"] = [list(item) for item in self.idle_stretches]
        data["active_stretches"] = [list(item) for item in self.active_stretches]
        return data


def unknown(reason: str, duration_seconds: float = 0.0) -> ActivityTimeline:
    return ActivityTimeline(status=STATUS_UNKNOWN, duration_seconds=int(duration_seconds), reason=reason)


def is_silent(levels: Sequence[float]) -> bool:
    """True when a track has no sound worth measuring for the whole recording (220)."""

    return sum(1 for value in levels if float(value) > IDLE_CEILING_DBFS) < SOUND_MIN_SECONDS


def _floor(levels: Sequence[float]) -> float:
    ordered = sorted(levels)
    return ordered[max(0, int(len(ordered) * 0.15) - 1)]


def game_audio_timeline(levels: Sequence[float], *, game_track: int | None = None) -> ActivityTimeline:
    """Idle and active stretches from the game-audio track's level for each second (signal 1)."""

    values = [max(SILENT_DBFS, float(value)) for value in levels]
    if not values:
        return unknown("The game-audio track has no sound to measure.")
    threshold = min(IDLE_CEILING_DBFS, _floor(values) + IDLE_ABOVE_FLOOR_DB)
    quiet = [value <= threshold for value in values]
    idle = [(start, end) for start, end in spans(quiet, IDLE_BRIDGE_SECONDS) if end - start >= IDLE_MIN_SECONDS]
    active: list[tuple[int, int]] = []
    cursor = 0
    for start, end in idle:
        if start > cursor:
            active.append((cursor, start))
        cursor = end
    if cursor < len(values):
        active.append((cursor, len(values)))
    idle_seconds = sum(end - start for start, end in idle)
    return ActivityTimeline(
        status=STATUS_MEASURED,
        duration_seconds=len(values),
        idle_seconds=idle_seconds,
        idle_share=round(idle_seconds / len(values), 4),
        idle_stretches=idle,
        active_stretches=active,
        game_track=game_track,
    )


def per_second_db(frame_db: Iterable[float], frames_per_second: int) -> list[float]:
    """Average a track's short-frame levels (dBFS) into one level per second, by power."""

    seconds: list[float] = []
    bucket: list[float] = []
    for value in frame_db:
        bucket.append(10 ** (max(SILENT_DBFS, float(value)) / 10.0))
        if len(bucket) == frames_per_second:
            seconds.append(_power_db(sum(bucket) / len(bucket)))
            bucket = []
    if bucket:
        seconds.append(_power_db(sum(bucket) / len(bucket)))
    return seconds


def _power_db(power: float) -> float:
    return round(SILENT_DBFS if power <= 0 else max(SILENT_DBFS, 10.0 * math.log10(power)), 1)


def speech_stretches(intervals: Iterable[Iterable[float]], *, gap: float = SPEECH_MERGE_SECONDS,
                     shortest: float = SPEECH_MIN_SECONDS) -> list[list[float]]:
    """Speech moments joined into stretches for "jump to speech" (220; shared from here, 226)."""

    merged: list[list[float]] = []
    for start, end in sorted((float(a), float(b)) for a, b in intervals):
        if merged and start - merged[-1][1] <= gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [[round(a, 1), round(b, 1)] for a, b in merged if b - a >= shortest]


# Signal 2: the game picture not changing (226) -------------------------------------------------

# Sample times closer than this to a limit count as at the limit (times come from frame timestamps).
_TIME_SLACK = 1e-6


def _same_size(a: bytes, b: bytes) -> int:
    if len(a) != len(b):
        raise ValueError(f"Two pictures of different sizes cannot be compared ({len(a)} and {len(b)} bytes).")
    return len(a)


def mean_abs_difference(a: bytes, b: bytes) -> float:
    """How different two gray pictures of the same size are: each pixel's difference, averaged (0-255).

    The one picture-difference score: the AI Video Editor's "sharp picture changes" use it as well.
    """

    size = _same_size(a, b)
    if not size:
        return 0.0
    try:
        import numpy
    except ImportError:
        return sum(abs(x - y) for x, y in zip(a, b)) / size
    first = numpy.frombuffer(bytes(a), dtype=numpy.uint8).astype(numpy.int32)
    second = numpy.frombuffer(bytes(b), dtype=numpy.uint8).astype(numpy.int32)
    return int(numpy.abs(first - second).sum()) / size


def changed_share(a: bytes, b: bytes, level: int = PICTURE_CELL_CHANGE_LEVEL) -> float:
    """The share of cells (pixels of the small gray picture) whose level moved by more than ``level``."""

    size = _same_size(a, b)
    if not size:
        return 0.0
    try:
        import numpy
    except ImportError:
        return sum(1 for x, y in zip(a, b) if abs(x - y) > level) / size
    first = numpy.frombuffer(bytes(a), dtype=numpy.uint8).astype(numpy.int16)
    second = numpy.frombuffer(bytes(b), dtype=numpy.uint8).astype(numpy.int16)
    return int((numpy.abs(first - second) > level).sum()) / size


def _mean_level(frame: bytes) -> float:
    return sum(frame) / len(frame) if frame else 0.0


def picture_change_per_second(times: Sequence[float], frames: Sequence[bytes], *, duration: float
                              ) -> tuple[list[float | None], list[float | None]]:
    """For each second of the recording: the share of the game picture that changed, and its gray
    level (0-255); None for a second that was not measured.

    ``times`` are the samples' times in seconds and ``frames`` the small gray pictures taken then
    (keyframes, however densely they come). Each sample is compared with the latest sample at least
    PICTURE_COMPARE_SECONDS earlier, never with the one next to it, so a sample repeated to fill a
    second, or keyframes a quarter-second apart, never read as no change. A second gets the value of
    the pair of samples around its middle when they are at most PICTURE_MAX_GAP_SECONDS apart (the
    largest change, when several pairs are around it); otherwise it is not measured.
    """

    count = max(0, math.ceil(round(float(duration or 0.0), 3)))
    changes: list[float | None] = [None] * count
    levels: list[float | None] = [None] * count
    samples = sorted(zip((float(value) for value in times), frames), key=lambda item: item[0])
    means = [_mean_level(frame) for _at, frame in samples]
    reference = -1
    for index, (at, frame) in enumerate(samples):
        while reference + 1 < index and samples[reference + 1][0] <= at - PICTURE_COMPARE_SECONDS + _TIME_SLACK:
            reference += 1
        if reference < 0:
            continue
        start = samples[reference][0]
        if at - start > PICTURE_MAX_GAP_SECONDS + _TIME_SLACK:
            continue
        value = changed_share(samples[reference][1], frame, PICTURE_CELL_CHANGE_LEVEL)
        level = (means[reference] + means[index]) / 2
        # The seconds whose middle lies between the two samples.
        for second in range(max(0, math.ceil(start - 0.5)), min(count - 1, math.floor(at - 0.5)) + 1):
            current = changes[second]
            if current is None or value > current:
                changes[second] = value
                levels[second] = level
    return changes, levels


def _between(idle: list[tuple[int, int]], length: int) -> list[tuple[int, int]]:
    active: list[tuple[int, int]] = []
    cursor = 0
    for start, end in idle:
        if start > cursor:
            active.append((cursor, start))
        cursor = end
    if cursor < length:
        active.append((cursor, length))
    return active


def _picture_kind(luma: Sequence[float | None] | None, start: int, end: int) -> str:
    import statistics

    values = [float(value) for value in (luma or [])[start:end] if value is not None]
    if values and statistics.median(values) <= PICTURE_BLACK_LUMA:
        return PICTURE_BLACK
    return PICTURE_STILL


def game_picture_timeline(changes: Sequence[float | None], *, luma: Sequence[float | None] | None = None,
                          region: str = "") -> ActivityTimeline:
    """Idle and active stretches from the game picture (signal 2): ``changes`` and ``luma`` are what
    ``picture_change_per_second`` gives; ``region`` says which part of the picture was measured.

    A second is still when at most PICTURE_STILL_MAX_SHARE of the picture changed. A minute or more
    of still seconds (a few moving ones inside do not break it, as with the sound) is idle time,
    "black" when its middle gray level is that of a dark screen. With less than
    PICTURE_MIN_MEASURED_SHARE of the seconds measured the signal is unknown, with the reason.
    """

    values = list(changes)
    seconds = len(values)
    measured = sum(1 for value in values if value is not None)
    signal: dict[str, Any] = {"status": STATUS_MEASURED, "region": region,
                              "measured_share": round(measured / seconds, 4) if seconds else 0.0,
                              "rule_version": GAME_PICTURE_RULE_VERSION, "reason": ""}
    reason = ""
    if not measured:
        reason = "The game picture has no samples to measure."
    elif measured / seconds < PICTURE_MIN_MEASURED_SHARE:
        reason = (f"Only {math.floor(measured * 100 / seconds)}% of the recording's game picture could be measured; "
                  f"at least {round(PICTURE_MIN_MEASURED_SHARE * 100)}% is needed.")
    if reason:
        signal.update({"status": STATUS_UNKNOWN, "reason": reason})
        return ActivityTimeline(status=STATUS_UNKNOWN, duration_seconds=seconds, reason=reason,
                                rule_version=GAME_PICTURE_RULE_VERSION, signals={SIGNAL_GAME_PICTURE: signal},
                                region=region)
    still = [value is not None and value <= PICTURE_STILL_MAX_SHARE for value in values]
    idle = [(start, end) for start, end in spans(still, IDLE_BRIDGE_SECONDS) if end - start >= IDLE_MIN_SECONDS]
    idle_seconds = sum(end - start for start, end in idle)
    signal["idle_seconds"] = idle_seconds
    return ActivityTimeline(
        status=STATUS_MEASURED,
        duration_seconds=seconds,
        idle_seconds=idle_seconds,
        idle_share=round(idle_seconds / seconds, 4),
        idle_stretches=idle,
        active_stretches=_between(idle, seconds),
        rule_version=GAME_PICTURE_RULE_VERSION,
        idle_by=[[SIGNAL_GAME_PICTURE] for _stretch in idle],
        picture_kinds=[_picture_kind(luma, start, end) for start, end in idle],
        signals={SIGNAL_GAME_PICTURE: signal},
        region=region,
    )


def _clause(text: str) -> str:
    """A reason to follow a colon: no closing full stop, and an ordinary first word in lower case."""

    text = str(text or "").strip().rstrip(".").strip()
    first = text.split(" ", 1)[0]
    if first[:1].isupper() and first[1:].islower() and first != "Track":
        text = text[:1].lower() + text[1:]
    return text


# How an estimate's reason begins (``raw_bin_library.idle_from_levels``): "Estimated from the full mix
# (Track 1): <why the game track could not be used>."
_ESTIMATE_PREFIX = re.compile(r"^\s*Estimated from the full mix \(Track \d+\):\s*", re.IGNORECASE)


def _sentence(text: str) -> str:
    text = str(text or "").strip()
    if not text:
        return text
    text = text[:1].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else f"{text}."


def _signal_entry(name: str, timeline: ActivityTimeline) -> dict[str, Any]:
    entry = dict(timeline.signals.get(name) or {})
    entry.update({"status": timeline.status, "reason": timeline.reason,
                  "idle_seconds": None if timeline.status == STATUS_UNKNOWN else timeline.idle_seconds})
    if name == SIGNAL_GAME_AUDIO:
        entry.update({"game_track": timeline.game_track, "rule_version": timeline.rule_version})
    else:
        entry.update({"region": timeline.region, "rule_version": GAME_PICTURE_RULE_VERSION})
    return entry


def combined_timeline(audio: ActivityTimeline | None, picture: ActivityTimeline | None) -> ActivityTimeline:
    """Idle time from both signals (226): idle when the game sound is quiet OR the game picture is
    still for at least a minute. Each stretch says which signal(s) found it (``idle_by``) and, when the
    picture found it, whether the screen was still or black (``picture_kinds``).

    When one signal is not measured the other is used alone, and the reason says so. A sound measured
    only on the full mix ("estimated") is used only when the picture is not measured: then the result
    is today's estimate. When the picture is measured, the reason says the game sound was not used and
    why, without the estimate, which is not used either. With neither, idle time is unknown, with both
    reasons.
    """

    sound = audio if audio is not None else unknown("The game sound was not measured.")
    seen = picture if picture is not None else unknown("the game picture was not read")
    sound_measured = sound.status == STATUS_MEASURED
    picture_measured = seen.status == STATUS_MEASURED
    signals = {SIGNAL_GAME_AUDIO: _signal_entry(SIGNAL_GAME_AUDIO, sound),
               SIGNAL_GAME_PICTURE: _signal_entry(SIGNAL_GAME_PICTURE, seen)}
    not_measured = f"Game picture not measured: {_clause(seen.reason or 'the game picture was not read')}."
    sources: list[tuple[str, ActivityTimeline]] = []
    if picture_measured:
        if sound_measured:
            sources.append((SIGNAL_GAME_AUDIO, sound))
        sources.append((SIGNAL_GAME_PICTURE, seen))
        status = STATUS_MEASURED
        if sound_measured:
            reason = ""
        elif sound.status == STATUS_ESTIMATED:
            # The full mix's estimate is not used here, so the reason leaves it out and says why the game
            # sound was not used.
            why = _clause(_ESTIMATE_PREFIX.sub("", str(sound.reason or "")))
            reason = (f"From the game picture only; the game sound was not used ({why})." if why
                      else "From the game picture only; the game sound was not used.")
        else:
            reason = f"From the game picture only: {_clause(sound.reason or 'the game sound was not measured')}."
    elif sound_measured or sound.status == STATUS_ESTIMATED:
        sources.append((SIGNAL_GAME_AUDIO, sound))
        status = sound.status
        reason = not_measured if sound_measured else f"{_sentence(sound.reason)} {not_measured}"
    else:
        return ActivityTimeline(
            status=STATUS_UNKNOWN,
            duration_seconds=max(sound.duration_seconds, seen.duration_seconds),
            reason=f"{_sentence(sound.reason or 'The game sound was not measured.')} {not_measured}",
            rule_version=COMBINED_RULE_VERSION,
            signals=signals,
            region=seen.region,
        )
    length = max(source.duration_seconds for _name, source in sources)
    flags = [False] * length
    for _name, source in sources:
        for start, end in source.idle_stretches:
            for second in range(max(0, int(start)), min(length, int(end))):
                flags[second] = True
    idle = [(start, end) for start, end in spans(flags, IDLE_BRIDGE_SECONDS) if end - start >= IDLE_MIN_SECONDS]
    picture_kinds = (list(seen.picture_kinds) or [PICTURE_STILL] * len(seen.idle_stretches)) if picture_measured else []
    found_by: list[list[str]] = []
    kinds: list[str] = []
    for start, end in idle:
        found_by.append([name for name, source in sources
                         if any(a < end and b > start for a, b in source.idle_stretches)])
        # The picture's kind of the still stretch that overlaps this one most; "" when only the sound found it.
        overlaps = [(min(end, b) - max(start, a), kind)
                    for (a, b), kind in zip(seen.idle_stretches if picture_measured else [], picture_kinds)
                    if a < end and b > start]
        kinds.append(max(overlaps)[1] if overlaps else "")
    idle_seconds = sum(end - start for start, end in idle)
    return ActivityTimeline(
        status=status,
        duration_seconds=length,
        idle_seconds=idle_seconds,
        idle_share=round(idle_seconds / length, 4) if length else None,
        idle_stretches=idle,
        active_stretches=_between(idle, length),
        game_track=sound.game_track if any(name == SIGNAL_GAME_AUDIO for name, _source in sources) else None,
        reason=reason,
        rule_version=COMBINED_RULE_VERSION,
        idle_by=found_by,
        picture_kinds=kinds,
        signals=signals,
        region=seen.region,
    )


# 125 Part 2 (Wave 8): where a track has sound, for the player's Next / Previous sound. A second is
# sound when it rises clearly above that track's own quiet floor (the same floor as the idle rule) and
# above a level no recording hiss reaches; sounds closer together than SOUND_JOIN_SECONDS are one.
SOUND_ABOVE_FLOOR_DB = 12.0
SOUND_MIN_DBFS = -60.0
SOUND_JOIN_SECONDS = 2


def sound_stretches(levels: Sequence[float]) -> list[tuple[int, int]]:
    """The stretches of sound on one track, as ``(start, end)`` seconds, from its level for each second."""

    values = [max(SILENT_DBFS, float(value)) for value in levels]
    if not values or max(values) < SOUND_MIN_DBFS:
        return []
    threshold = max(SOUND_MIN_DBFS, _floor(values) + SOUND_ABOVE_FLOOR_DB)
    return spans([value >= threshold for value in values], SOUND_JOIN_SECONDS)
