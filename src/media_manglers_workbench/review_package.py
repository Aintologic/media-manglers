"""One recording's transcript, read out of an evidence package (125).

The built-in player shows what was said at the playhead: the lines that went
into the package and the lines the transcript filter left out, each with the
reason. Everything needed is already on disk inside the package. This module
joins a recording to the right package and turns those files into one list of
lines in time order.

Two rules run through all of it:

* Show nothing rather than the wrong transcript. Runs can share one output
  folder, so a History row can point at a package a later run replaced. A
  recording is therefore always confirmed against the package's own
  ``manifest.json`` before a single line is read.
* Never raise. These are JSON files that an interrupted run, a hand edit or an
  older build can leave missing, cut short or shaped differently. Anything
  unreadable is treated as absent, and an entry that cannot be placed on the
  timeline is skipped.

No Qt here, so every rule is testable in milliseconds and the loader can run
on a worker thread without touching a widget.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

from media_manglers.core.voice_track import count_spotter_words

from .evidence import read_item_records, read_session_mentions, resolve_evidence_package_root

KIND_KEPT = "kept"
KIND_LEFT_OUT = "left_out"
KIND_REJECTED_SPAN = "rejected_span"

SHOW_ALL = "all"
SHOW_KEPT = "kept"
SHOW_LEFT_OUT = "left_out"

# The reason codes the sparse filter writes (core/sparse_narration.py and the
# sparse loop in providers/whisper_local.py). A code that is not listed here is
# shown to the operator as recorded rather than hidden.
REASON_FILLER = "known_filler_phrase"
REASON_COMPRESSION = "compression_ratio_threshold"
REASON_LOW_INFORMATION = "combined_low_speech_information"
REASON_REJECTED = "repetition_persisted_after_retry"
REASON_PHRASE_LOOP = "phrase_loop"
REASON_OTHER_TRACK = "heard_on_another_track"
REASON_NEAR_SILENT = "narration_track_near_silent"  # 203
# 214
REASON_SAMPLED = "sampled_low_confidence"
REASON_TOO_THIN = "too_few_words_for_its_length"
REASON_PROMPT_ECHO = "prompt_echo"

MODE_SPARSE = "Sparse"
_MODES = {"sparse": MODE_SPARSE, "continuous": "Continuous", "auto": "Auto"}

# Lines are matched across files by start time, never by id: the backend
# renumbers segment ids after filtering, and the glossary pass only ever
# changes text. Every file holds the SAME segment with its start written to
# the millisecond, so a true match has the same start. Anything wider pairs a
# line with its neighbour: the transcriber stamps lines as little as 0.02 s
# apart, and an ordinary line would then be shown as rescued.
SAME_START_SECONDS = 0.0005
# A line with no length still has to be landed on and lit up, so it counts as
# lasting this long. The player uses the same figure.
START_MATCH_SECONDS = 0.05
# The same length, give or take: ffprobe and the player's own clock can differ
# by a frame or two. A bigger difference means a different recording, whatever
# its path or name says.
DURATION_MATCH_SECONDS = 1.5
# A seek to a line's start can land a frame early. Without this margin "Next
# line" would offer the line the operator just jumped to.
NEXT_LINE_MARGIN_SECONDS = 0.05
# Previous line works like a CD player: further than this into a line it
# restarts that line, otherwise it goes to the one before.
RESTART_LINE_SECONDS = 1.0
# A kept line gets the spotter badge when at least this share of its words
# belongs to spotter call-outs.
SPOTTER_WORD_SHARE = 0.6

_NUMBER_KEYS = ("no_speech_prob", "avg_logprob", "compression_ratio")
# The backend's own idea of a word (sparse_narration.segment_word_count).
_WORD = re.compile(r"[A-Za-z0-9']+")
# The filter decides "no words" on plain a-z letters only (sparse_narration
# .is_silence_hallucination_text), so the explanation uses the same test.
_LETTER = re.compile(r"[A-Za-z]")


@dataclass(frozen=True, slots=True)
class TranscriptLine:
    start: float  # seconds into the SOURCE recording
    end: float
    text: str  # delivered (glossary-corrected) text for kept lines; the transcriber's text otherwise
    kind: str  # "kept" | "left_out" | "rejected_span"
    reason_code: str = ""  # "" for kept
    reason_text: str = ""  # plain words for the player
    original_text: str = ""  # the transcriber's wording when it differs from `text` (kept lines)
    numbers: tuple[tuple[str, float], ...] = ()  # no_speech_prob, avg_logprob, compression_ratio when known
    rescued: bool = False  # kept only because it sat next to real speech (119 / 133)
    spotter: bool = False  # mostly spotter call-outs


@dataclass(frozen=True, slots=True)
class RecordingTranscript:
    lines: tuple[TranscriptLine, ...]  # merged, sorted by (start, kind)
    mode: str  # "Sparse" | "Continuous" | "Auto" | ""
    filtering_ran: bool  # False when the mode is not Sparse
    audit_available: bool  # False when there is no .transcript.raw.json (older package)
    rescued_known: bool  # True when the audit carries "rescued_segments"
    track_explanation: str  # the saved plain-English explanation, "" when absent
    transcribed_track: int | None  # 1-based Track N, None when unknown
    contamination_suspected: bool
    package_root: Path
    source_id: str
    physical_source_id: str


# ---------------------------------------------------------------------------
# Tolerant readers
# ---------------------------------------------------------------------------


def _read_json_object(path: Path) -> dict[str, Any] | None:
    """The JSON object in a file, or None for anything else at all.

    A missing file, a locked or unreadable one, text that is not JSON and
    JSON that is not an object all mean the same thing to the player: this
    part of the package is not there.
    """

    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, ValueError):
        # ValueError covers bytes that are not UTF-8 and a path Windows
        # refuses outright (an embedded null from a damaged manifest).
        return None
    try:
        payload = json.loads(text)
    except (ValueError, RecursionError):
        return None
    return payload if isinstance(payload, dict) else None


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except (OSError, ValueError):
        return False


def _text(value: Any) -> str:
    # Only real text counts. Turning null or a number into text would invent
    # ids and file names such as "None".
    return value.strip() if isinstance(value, str) else ""


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _seconds(value: Any) -> float | None:
    """A point in time, or None when the value cannot be one."""

    # bool is an int in Python; true/false is never a timestamp.
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _positive(value: Any) -> float | None:
    number = _seconds(value)
    return number if number is not None and number > 0 else None


def _whole_number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return None


def _span(start: Any, end: Any) -> tuple[float, float] | None:
    """(start, end) clamped onto the timeline, or None to skip the entry."""

    begin = _seconds(start)
    finish = _seconds(end)
    if begin is None or finish is None:
        return None
    begin = max(0.0, begin)
    return begin, max(begin, finish)


def _numbers(segment: Mapping[str, Any]) -> tuple[tuple[str, float], ...]:
    found: list[tuple[str, float]] = []
    for key in _NUMBER_KEYS:
        number = _seconds(segment.get(key))
        if number is not None:
            found.append((key, number))
    return tuple(found)


def _wording(text: str) -> str:
    # How the same words are recognised in two files: the transcriber pads its
    # text with a space and the delivered copy is trimmed.
    return text.strip().casefold()


def _segment_key(start: float, text: str) -> tuple[int, str]:
    # How one segment is recognised in two lists of the same file. Both lists
    # hold the very same start, so whole milliseconds are exact here.
    return round(start * 1000), _wording(text)


class _StartIndex:
    """What another file recorded against each segment's start time.

    An entry is ``(start, the segment's text, value)``. The text is kept
    because a start does not always name one segment: the transcriber now and
    then writes a line with no length at the very start of the next one.
    """

    __slots__ = ("_starts", "_entries")

    def __init__(self, entries: Iterable[tuple[float, str, Any]]) -> None:
        ordered = sorted(entries, key=lambda entry: entry[0])
        self._starts = [start for start, _text, _value in ordered]
        self._entries = [(_wording(text), value) for _start, text, value in ordered]

    def _at(self, start: float) -> list[tuple[str, Any]]:
        low = bisect_left(self._starts, start - SAME_START_SECONDS)
        high = bisect_right(self._starts, start + SAME_START_SECONDS)
        return self._entries[low:high]

    def only(self, start: float, alone: bool) -> Any | None:
        """The value at this start, when the start alone says whose it is.

        ``alone`` is whether the line asking is the only kept line there.
        """

        entries = self._at(start)
        return entries[0][1] if alone and len(entries) == 1 else None

    def for_line(self, start: float, wording: str, alone: bool) -> Any | None:
        """The value recorded for the kept line that starts here, or None."""

        entries = self._at(start)
        if alone and len(entries) == 1:
            return entries[0][1]
        # Several segments share this start, so the start no longer says which
        # is which. The words still do; when they do not either, nothing is
        # better than another line's facts.
        wanted = _wording(wording)
        return next((value for text, value in entries if text == wanted), None)


# ---------------------------------------------------------------------------
# The right package or none
# ---------------------------------------------------------------------------


def source_digest(path: Path | str) -> str:
    """The 10-hex ending the backend gives the source id of this path.

    Only this part of ``make_safe_source_id`` is reproduced. The stem in front
    of it is tidied and cut to length by the backend and is not needed to
    recognise a recording.
    """

    normalized = str(path).replace("\\", "/").lower()
    return hashlib.sha1(normalized.encode("utf-8", errors="replace")).hexdigest()[:10]


def _path_spellings(recording: Path | str) -> list[str]:
    """The recording's path as given and as the disk resolves it."""

    spellings = [str(recording)]
    try:
        resolved = str(Path(recording).resolve())
    except (OSError, RuntimeError, ValueError):
        resolved = ""
    if resolved and resolved not in spellings:
        spellings.append(resolved)
    return spellings


def _path_norm(text: str) -> str:
    return text.replace("\\", "/").rstrip("/").lower()


def _file_name(text: str) -> str:
    # Split by hand so a Windows path is read the same way whatever is reading
    # it, and compare without case because Windows file names ignore it.
    return _path_norm(text).rsplit("/", 1)[-1]


def _entry_file_name(entry: Mapping[str, Any]) -> str:
    return _file_name(_text(entry.get("source_filename")) or _text(entry.get("source_path")))


def _unless_another_length(
    entry: Mapping[str, Any],
    duration_seconds: float | None,
) -> dict[str, Any] | None:
    """A copy of the entry, or None when the lengths say it is another recording.

    Only two known lengths can disagree. A length nobody wrote down proves
    nothing either way.
    """

    known = _positive(duration_seconds)
    declared = _positive(entry.get("duration_seconds"))
    if (
        known is not None
        and declared is not None
        and abs(known - declared) > DURATION_MATCH_SECONDS
    ):
        return None
    return dict(entry)


def _match_entries(
    sources: Sequence[dict[str, Any]],
    spellings: Sequence[str],
    duration_seconds: float | None,
    *,
    allow_file_name: bool = True,
) -> dict[str, Any] | None:
    if not sources or not spellings:
        return None
    # The length is checked under every rule, the path included: a recording
    # can be recorded over or replaced where it sits, and the package then
    # describes a file that is gone.
    wanted_paths = {_path_norm(text) for text in spellings}
    for entry in sources:
        declared = _text(entry.get("source_path"))
        if declared and _path_norm(declared) in wanted_paths:
            return _unless_another_length(entry, duration_seconds)
    # The logical id always ends with the path hash. The physical id does too
    # unless the backend had to shorten it to fit the Windows path budget.
    endings = tuple("-" + source_digest(text) for text in spellings)
    for entry in sources:
        for key in ("source_id", "physical_source_id"):
            if _text(entry.get(key)).endswith(endings):
                return _unless_another_length(entry, duration_seconds)
    if not allow_file_name:
        return None
    # Last resort, for a recording that was moved since the run: its file
    # name, but only when that name cannot mean two recordings and the length
    # does not contradict it.
    name = _file_name(spellings[0])
    same_name = [entry for entry in sources if name and _entry_file_name(entry) == name]
    if len(same_name) != 1:
        return None
    return _unless_another_length(same_name[0], duration_seconds)


def match_source(
    manifest: Mapping[str, Any],
    recording: Path,
    *,
    duration_seconds: float | None = None,
) -> dict[str, Any] | None:
    """The manifest's ``sources[]`` entry for this recording, or None.

    Tried in order: the exact path, the path hash on the end of the source id,
    then a file name no other source shares. Whichever rule finds the entry,
    it is refused when ``duration_seconds`` and the manifest's own length are
    both known and differ: that is another recording under the same name.
    """

    if not isinstance(manifest, Mapping):
        return None
    return _match_entries(
        _dict_items(manifest.get("sources")),
        _path_spellings(recording),
        duration_seconds,
    )


def _package_root(folder: Path | str) -> Path | None:
    text = str(folder or "").strip()
    if not text:
        return None
    try:
        return resolve_evidence_package_root(text)
    except (OSError, ValueError):
        return None


def find_package_for_recording(
    recording: Path,
    hints: Sequence[Path | str],
    *,
    duration_seconds: float | None = None,
    cancelled: Callable[[], bool] = lambda: False,
) -> Path | None:
    """The first hinted package whose manifest lists this recording.

    A hint is a run's output folder or the ``codex-evidence-package`` folder
    itself. Hints are tried in the order given, so the caller decides which
    package wins when several hold the same recording. Each hint costs a disk
    read, which is why ``cancelled`` is asked before every one.
    """

    spellings = _path_spellings(recording)
    seen: set[str] = set()
    for hint in hints:
        if cancelled():
            return None
        root = _package_root(hint)
        if root is None:
            continue
        key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        manifest = _read_json_object(root / "manifest.json")
        if manifest is None:
            continue
        entry = _match_entries(_dict_items(manifest.get("sources")), spellings, duration_seconds)
        if entry is not None:
            return root
    return None


# ---------------------------------------------------------------------------
# Plain words
# ---------------------------------------------------------------------------


def _hms(seconds: float) -> str:
    # audio_widgets.format_hms is the player's formatter, but that module is
    # Qt and this one must stay importable without it.
    total = int(seconds) if math.isfinite(seconds) and seconds > 0 else 0
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def reason_text(code: str, segment_text: str = "", *, start: float = 0.0, end: float = 0.0, track: str = "") -> str:
    """Why a line was left out, in words the operator can act on."""

    if code == REASON_FILLER:
        # The filter files a segment with no letters under this same code. It
        # would be untrue to blame a stock phrase for an empty line.
        if not _LETTER.search(str(segment_text or "")):
            return "Left out: there were no words in it."
        return (
            "Left out: a stock phrase the transcriber tends to invent over silence "
            'or engine noise, like "thanks for watching".'
        )
    if code == REASON_COMPRESSION:
        return (
            "Left out: the transcriber was repeating itself here, which usually "
            "means it was making text up."
        )
    if code == REASON_OTHER_TRACK:
        return f"Left out: written down from sound on {track or 'another track'}, not from you."
    if code == REASON_NEAR_SILENT:
        return "Left out: your microphone track was nearly silent here, so these words were not yours."
    if code == REASON_PHRASE_LOOP:
        return "Left out: one phrase said over and over, which the transcriber tends to invent over music."
    if code == REASON_LOW_INFORMATION:
        return "Left out: the transcriber was not confident anyone was speaking here."
    if code == REASON_SAMPLED:
        return "Left out: a guess. The transcriber could not make out this stretch and wrote what it guessed."
    if code == REASON_TOO_THIN:
        return "Left out: one word stretched over a long time, which the transcriber invents over quiet stretches."
    if code == REASON_PROMPT_ECHO:
        return "Left out: the transcriber wrote back your words to spell right, not anything said."
    if code == REASON_REJECTED:
        return (
            f"This whole stretch ({_hms(start)}–{_hms(end)}) was thrown out: the "
            "transcriber kept repeating itself even on a second try."
        )
    return f'Left out — reason recorded as "{code}".'


def _mostly_spotter(text: str) -> bool:
    words = len(_WORD.findall(text))
    if not words:
        return False
    return count_spotter_words(text) >= max(1, SPOTTER_WORD_SHARE * words)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Audit:
    left_out: list[TranscriptLine]
    kept_numbers: _StartIndex
    rescued: _StartIndex
    rescued_known: bool


def _read_audit(audit: Mapping[str, Any] | None) -> _Audit:
    """Left-out lines and per-line facts from ``.transcript.raw.json``."""

    if audit is None:
        return _Audit([], _StartIndex(()), _StartIndex(()), False)

    # A chunk that repeated itself is transcribed a second time. The highest
    # attempt on file is the one the backend went on to use.
    latest: dict[int, tuple[int, dict[str, Any]]] = {}
    for entry in _dict_items(audit.get("raw_attempts")):
        chunk = _whole_number(entry.get("chunk_index"))
        attempt = _whole_number(entry.get("attempt"))
        if chunk is None or attempt is None:
            continue
        if chunk not in latest or attempt > latest[chunk][0]:
            latest[chunk] = (attempt, entry)

    rejected_entries = _dict_items(audit.get("rejected_chunks"))
    rejected = {
        chunk
        for entry in rejected_entries
        if (chunk := _whole_number(entry.get("chunk_index"))) is not None
    }

    filtered = _dict_items(audit.get("filtered_segments"))
    # Only consulted for a chunk that raw_attempts does not list at all.
    highest_filtered: dict[int, int] = {}
    for entry in filtered:
        chunk = _whole_number(entry.get("chunk_index"))
        attempt = _whole_number(entry.get("attempt"))
        if chunk is not None and attempt is not None:
            highest_filtered[chunk] = max(attempt, highest_filtered.get(chunk, attempt))

    lines: list[TranscriptLine] = []
    # (start in milliseconds, wording) of every left-out line, counted, so the
    # same segments can be passed over when the kept lines' numbers are read.
    left_out_keys: Counter[tuple[int, str]] = Counter()
    for entry in filtered:
        chunk = _whole_number(entry.get("chunk_index"))
        if chunk is not None:
            if chunk in rejected:
                # The whole stretch is shown as one span below; listing its
                # drops as well would say the same thing twice.
                continue
            used = latest[chunk][0] if chunk in latest else highest_filtered.get(chunk)
            attempt = _whole_number(entry.get("attempt"))
            if used is not None and attempt is not None and attempt != used:
                # Dropped from a try the backend threw away, so it says
                # nothing about the transcript that was delivered.
                continue
        segment = entry.get("segment")
        if not isinstance(segment, dict):
            continue
        span = _span(segment.get("start"), segment.get("end"))
        if span is None:
            continue
        text = _text(segment.get("text"))
        code = _text(entry.get("reason"))
        number = _whole_number(entry.get("track_number"))
        title = _text(entry.get("track_title"))
        track = (f"Track {number} ({title})" if title else f"Track {number}") if number else ""
        left_out_keys[_segment_key(span[0], text)] += 1
        lines.append(
            TranscriptLine(
                start=span[0],
                end=span[1],
                text=text,
                kind=KIND_LEFT_OUT,
                reason_code=code,
                reason_text=reason_text(code, text, start=span[0], end=span[1], track=track),
                numbers=_numbers(segment),
            )
        )

    for entry in rejected_entries:
        chunk = _whole_number(entry.get("chunk_index"))
        attempt_entry = latest[chunk][1] if chunk in latest else {}
        interval = entry.get("interval")
        if not isinstance(interval, dict):
            interval = attempt_entry.get("interval")
        if not isinstance(interval, dict):
            continue
        span = _span(interval.get("start_seconds"), interval.get("end_seconds"))
        if span is None:
            continue
        # Nothing from this stretch reached the transcript, so what the
        # transcriber wrote for it survives only in the attempt itself.
        discarded = " ".join(
            text
            for segment in _dict_items(attempt_entry.get("segments"))
            if (text := _text(segment.get("text")))
        )
        code = _text(entry.get("reason")) or REASON_REJECTED
        lines.append(
            TranscriptLine(
                start=span[0],
                end=span[1],
                text=discarded,
                kind=KIND_REJECTED_SPAN,
                reason_code=code,
                reason_text=reason_text(code, discarded, start=span[0], end=span[1]),
            )
        )

    kept_numbers: list[tuple[float, str, Any]] = []
    for chunk, (_attempt, entry) in latest.items():
        if chunk in rejected:
            continue
        for segment in _dict_items(entry.get("segments")):
            start = _seconds(segment.get("start"))
            if start is None:
                continue
            start = max(0.0, start)
            text = _text(segment.get("text"))
            # An attempt lists what was dropped from it as well. A dropped
            # segment can start exactly where a kept line does, and its
            # scores must not be shown as that line's.
            key = _segment_key(start, text)
            if left_out_keys[key] > 0:
                left_out_keys[key] -= 1
                continue
            numbers = _numbers(segment)
            if numbers:
                kept_numbers.append((start, text, numbers))

    rescued_value = audit.get("rescued_segments")
    rescued: list[tuple[float, str, Any]] = []
    for entry in _dict_items(rescued_value):
        segment = entry.get("segment")
        start = _seconds(segment.get("start")) if isinstance(segment, dict) else None
        if start is not None:
            rescued.append((max(0.0, start), _text(segment.get("text")), True))

    return _Audit(
        left_out=lines,
        kept_numbers=_StartIndex(kept_numbers),
        rescued=_StartIndex(rescued),
        # Packages written before 133 do not carry the key. That is "the
        # package does not say", which is not the same as "nothing was rescued".
        rescued_known=isinstance(rescued_value, list),
    )


def _declared_file(root: Path, value: Any) -> Path | None:
    """A path the manifest names, when a file is really there."""

    declared = _text(value)
    if not declared:
        return None
    try:
        path = Path(declared)
        if not path.is_absolute():
            path = root / path
    except (OSError, ValueError):
        return None
    return path if _is_file(path) else None


def _original_wording(root: Path, source: Mapping[str, Any], file_name: str) -> _StartIndex:
    """The transcriber's wording by start time, from the package's raw copy.

    The raw copy is only the transcriber's wording after the FIRST write of a
    package. Written again over the same folder with the transcript reused,
    the backend copies the already-corrected file over it (evidence_package
    ``_copy_transcript_sources``) and the first wording is gone from the
    package. What is always true is the manifest's count of what the glossary
    changed in the write that made these files, so the raw copy is believed
    only when that count says something was changed. Otherwise a difference
    between the two files has some other cause and is not shown as "before
    your glossary".
    """

    if _positive(source.get("transcript_correction_count")) is None:
        return _StartIndex(())
    path = _declared_file(root, source.get("raw_transcript_json_path"))
    if path is None:
        path = root / "transcript" / "raw" / "sources" / file_name
    payload = _read_json_object(path) or {}
    entries: list[tuple[float, str, Any]] = []
    for segment in _dict_items(payload.get("segments")):
        start = _seconds(segment.get("start"))
        text = _text(segment.get("text"))
        if start is not None and text:
            entries.append((max(0.0, start), text, text))
    return _StartIndex(entries)


def _mode(payload: Mapping[str, Any] | None) -> str:
    # Anything but the three names the transcriber writes reads as "not known".
    return _MODES.get(_text(payload.get("mode")).lower(), "") if payload else ""


def _voice_details(path: Path, source: Mapping[str, Any]) -> tuple[str, int | None]:
    """(saved explanation, 1-based transcribed track) for one source."""

    payload = _read_json_object(path) or {}
    detection = payload.get("detection")
    if not isinstance(detection, dict):
        detection = {}
    # ``selection_reason`` is deliberately never read: only one of the
    # detector's return shapes carries it.
    explanation = _text(detection.get("explanation"))
    detected = _whole_number(detection.get("selected_ordinal"))
    selected = _whole_number(source.get("selected_audio_stream_index"))
    if selected is not None and selected < 0:
        selected = None
    if detected is not None and detected < 0:
        detected = None
    # The saved result can be older than the run that made this transcript:
    # when the operator picks the track by hand, detection is not run again.
    # An explanation naming a different track than the one transcribed would
    # mislead, so it is dropped.
    if selected is not None and detected is not None and selected != detected:
        explanation = ""
    # Detection asked instead of choosing, or found no narration (142), then
    # the operator chose the track and the recording was transcribed from it:
    # the saved verdict is out of date, and "no narration" beside the operator's own words
    # would be false. Until they have answered, the question is what there is to
    # read.
    # A transcript blocked as invented was still made, from a known track.
    transcribed = _text(source.get("status")) in {"", "completed", "skipped", "quality_blocked"}
    unsettled = _text(detection.get("status")) in {"uncertain", "no_narration_found"}
    if transcribed and selected is not None and detected is None and unsettled:
        explanation = ""
    # A recording that was never transcribed has no transcribed track: its
    # manifest index is only the usual track the run started from.
    ordinal = (selected if selected is not None else detected) if transcribed else None
    return explanation, (ordinal + 1 if ordinal is not None else None)


def load_transcript(
    package_root: Path,
    recording: Path,
    *,
    duration_seconds: float | None = None,
) -> RecordingTranscript | None:
    """Everything the player shows for one recording, or None.

    None means "no transcript to show": the package does not list this
    recording, or its transcript file is missing or unreadable. Only the
    manifest and this one source's own files are read, never the whole
    package, so a large package costs no more than a small one.
    """

    root = _package_root(package_root)
    if root is None:
        return None
    manifest = _read_json_object(root / "manifest.json")
    if manifest is None:
        return None
    source = match_source(manifest, recording, duration_seconds=duration_seconds)
    if source is None:
        return None

    source_id = _text(source.get("source_id"))
    # Files are named after the physical id: the backend shortens a long id so
    # the paths fit, and the logical id then names no file at all.
    file_id = _text(source.get("physical_source_id")) or source_id
    transcript_path = _declared_file(root, source.get("transcript_json_path"))
    if transcript_path is None:
        if not file_id:
            return None
        transcript_path = root / "transcript" / "sources" / f"{file_id}.transcript.json"
    delivered = _read_json_object(transcript_path)
    if delivered is None:
        return None

    # The transcriber names its side files from the transcript's own stem
    # ("<id>.transcript" + ".raw.json"), and the backend keeps the voice
    # result beside them under the bare id.
    stem = Path(transcript_path.name).stem
    bare_id = stem[: -len(".transcript")] if stem.endswith(".transcript") else stem
    audit_payload = _read_json_object(transcript_path.with_name(f"{stem}.raw.json"))
    audit = _read_audit(audit_payload)
    originals = _original_wording(root, source, transcript_path.name)

    kept: list[tuple[tuple[float, float], str]] = []
    for segment in _dict_items(delivered.get("segments")):
        span = _span(segment.get("start"), segment.get("end"))
        text = _text(segment.get("text"))
        if span is not None and text:
            kept.append((span, text))
    kept_starts = sorted(span[0] for span, _words in kept)

    lines = list(audit.left_out)
    for span, text in kept:
        start = span[0]
        alone = (
            bisect_right(kept_starts, start + SAME_START_SECONDS)
            - bisect_left(kept_starts, start - SAME_START_SECONDS)
        ) == 1
        # Where two kept lines share a start, nothing says which raw wording
        # belongs to which, so neither is shown.
        original = originals.only(start, alone) or ""
        if original == text:
            original = ""
        # The audit holds the transcriber's words, not the glossary's.
        said = original or text
        lines.append(
            TranscriptLine(
                start=start,
                end=span[1],
                text=text,
                kind=KIND_KEPT,
                original_text=original,
                numbers=audit.kept_numbers.for_line(start, said, alone) or (),
                rescued=bool(audit.rescued.for_line(start, said, alone)),
                spotter=_mostly_spotter(text),
            )
        )
    lines.sort(key=lambda line: (line.start, line.kind))

    # The audit names the mode. The quality file is only opened when the audit
    # does not say, because every read here can be from a slow disk.
    mode = _mode(audit_payload) or _mode(
        _read_json_object(transcript_path.with_name(f"{stem}.quality.json"))
    )
    explanation, track = _voice_details(transcript_path.with_name(f"{bare_id}.voice.json"), source)
    quality = source.get("transcript_quality")
    return RecordingTranscript(
        lines=tuple(lines),
        mode=mode,
        # Only the sparse path filters anything. For every other mode the
        # player says "No filtering ran", not "nothing was left out".
        filtering_ran=mode == MODE_SPARSE,
        audit_available=audit_payload is not None,
        rescued_known=audit.rescued_known,
        track_explanation=explanation,
        transcribed_track=track,
        contamination_suspected=(
            isinstance(quality, dict)
            and quality.get("game_spotter_contamination_suspected") is True
        ),
        package_root=root,
        source_id=source_id,
        physical_source_id=file_id,
    )


def review_copy_for(package_root: Path, recording: Path) -> Path | None:
    """The package's small review video of this recording, when the file exists.

    Offered when the recording itself has gone missing, so nothing here asks
    whether the recording exists or touches its drive at all: a recording is
    most often missing because its drive is asleep or unplugged, and asking
    Windows to resolve a path there can hang until the network gives up, with
    the window that asked frozen for as long.

    With the recording gone its length cannot be checked, so a shared file
    name is not enough here. Only the path the package recorded, or the path
    hash on its source id, offers a copy; otherwise the operator could be
    handed the small copy of some other recording with the same name.
    """

    root = _package_root(package_root)
    if root is None:
        return None
    index = read_narration_index(root)
    if index is None:
        return None
    entries = _dict_items(index.get("sources"))
    spellings = [str(recording)]
    manifest = _read_json_object(root / "manifest.json")
    if manifest is not None:
        source = _match_entries(
            _dict_items(manifest.get("sources")), spellings, None, allow_file_name=False
        )
        wanted = _text(source.get("source_id")) if source else ""
        entry = next(
            (item for item in entries if wanted and _text(item.get("source_id")) == wanted),
            None,
        )
    else:
        # The index carries source ids of its own, so the same join still
        # holds without a manifest.
        entry = _match_entries(entries, spellings, None, allow_file_name=False)
    if entry is None:
        return None
    candidate = _inside_package(root, entry.get("review_video"))
    return candidate if candidate is not None and _is_file(candidate) else None


def _inside_package(root: Path, value: Any) -> Path | None:
    """A package-relative path the backend wrote, or None for anything that leaves the package."""

    relative = _text(value)
    if not relative:
        return None
    try:
        relative_path = Path(relative)
        # The backend only ever writes a path inside the package. Anything
        # else did not come from it and is not played.
        if relative_path.is_absolute() or relative_path.drive or ".." in relative_path.parts:
            return None
        return root / relative_path
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Moving through the lines
#
# Every function below expects lines in time order, which is how
# ``RecordingTranscript.lines`` and ``visible_lines`` hand them over.
# ---------------------------------------------------------------------------


def visible_lines(lines: Sequence[TranscriptLine], show: str) -> list[TranscriptLine]:
    """The lines the filter combo asks for: "all", "kept" or "left_out"."""

    if show == SHOW_KEPT:
        return [line for line in lines if line.kind == KIND_KEPT]
    if show == SHOW_LEFT_OUT:
        # A stretch thrown out whole is left out too.
        return [line for line in lines if line.kind != KIND_KEPT]
    return list(lines)


def _line_start(line: TranscriptLine) -> float:
    return line.start


def _started_count(lines: Sequence[TranscriptLine], seconds: float) -> int:
    # How many lines have started by ``seconds``. The player asks on every
    # tick of the clock, so this is a binary search, not a walk down the list.
    return bisect_right(lines, seconds, key=_line_start)


def line_index_at(lines: Sequence[TranscriptLine], seconds: float) -> int | None:
    """The line being spoken at ``seconds``, or None between lines."""

    # Backwards from the last line to have started: when a span and a line
    # overlap, the one that started last is the one being spoken.
    for index in range(_started_count(lines, seconds) - 1, -1, -1):
        line = lines[index]
        # A line with no length still has to be reachable, and a line's end is
        # the next one's start, so the end itself belongs to the next line.
        if seconds < max(line.end, line.start + START_MATCH_SECONDS):
            return index
    return None


def next_line_index(lines: Sequence[TranscriptLine], seconds: float) -> int | None:
    index = _started_count(lines, seconds + NEXT_LINE_MARGIN_SECONDS)
    return index if index < len(lines) else None


def previous_line_index(lines: Sequence[TranscriptLine], seconds: float) -> int | None:
    """Where Previous line goes; None when no line has started yet."""

    current = _started_count(lines, seconds) - 1
    if current < 0:
        return None
    if seconds - lines[current].start > RESTART_LINE_SECONDS:
        return current
    # On the very first line there is nothing before it, and restarting it is
    # more use than doing nothing.
    return max(0, current - 1)


def upcoming_line(lines: Sequence[TranscriptLine], seconds: float) -> TranscriptLine | None:
    """The next line to start, for "Next line at H:MM:SS"."""

    index = _started_count(lines, seconds)
    return lines[index] if index < len(lines) else None


# ---------------------------------------------------------------------------
# What the package found, and its clips (125 Part 2, 134; Wave 8)
#
# The player marks a recording's moments on its time bar, and the Evidence page
# lists a package's clips and small review copies. Both read the package the
# same tolerant way as the transcript, and only for the recording asked about.
# ---------------------------------------------------------------------------

NARRATION_INDEX = "NARRATION_EVIDENCE.json"
# The word for a moment the operator was talking in, beside Session Review's own words for the rest.
NARRATION_MOMENT_TEXT = "you were talking"
MOMENT_NARRATION = "narration"
# An explicit marker the audit found covered by a ticket mention is the same request said twice.
_COVERED_MARKER_STATUSES = {"covered", "indexed-unrendered"}
EXCERPT_LIMIT = 160
_MOMENT_TEXT = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:\.\d+)?)$")


def moment_seconds(*values: Any) -> float:
    """The first of these that names a moment after the very start, in seconds.

    A package writes every moment twice, as a number of seconds and as
    "HH:MM:SS.mmm" text, and an older record can lack the number. Anything
    that is not a moment (nothing, zero, other text) is passed over, so the
    caller lists what it prefers first.
    """

    for value in values:
        seconds = 0.0
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            seconds = float(value)
        elif isinstance(value, str) and value.strip():
            text = value.strip()
            match = _MOMENT_TEXT.match(text)
            try:
                if match:
                    hours, minutes, rest = match.groups()
                    seconds = int(hours or 0) * 3600 + int(minutes) * 60 + float(rest)
                else:
                    seconds = float(text)
            except ValueError:
                continue
        # Written this way round so "not a number" fails both comparisons.
        if 0.0 < seconds < float("inf"):
            return seconds
    return 0.0


def moment_kind_text(record_type: str) -> str:
    """A Session timeline record's kind in the words Session Review shows: "ticket mention" and so on."""

    return str(record_type or "").replace("_", " ")


def recording_for_source(manifest: Mapping[str, Any] | None, *source_ids: Any) -> str:
    """Where a package's manifest says the recording of this source id is, or ""."""

    wanted = {str(value).strip() for value in source_ids if str(value or "").strip()}
    if not wanted or not isinstance(manifest, Mapping):
        return ""
    for entry in _dict_items(manifest.get("sources")):
        names = {_text(entry.get(key)) for key in ("source_id", "physical_source_id")}
        if wanted & names:
            return _text(entry.get("source_path"))
    return ""


def read_narration_index(package_root: Path) -> dict[str, Any] | None:
    """The one reader of a package's NARRATION_EVIDENCE.json; None when it is missing or unreadable."""

    root = _package_root(package_root)
    return _read_json_object(root / NARRATION_INDEX) if root is not None else None


@dataclass(frozen=True, slots=True)
class Moment:
    """One thing the package found in a recording, at a time on the recording's own timeline."""

    seconds: float
    kind: str  # a Session timeline record type, or "narration"
    text: str  # the kind in plain words
    excerpt: str = ""
    finding: bool = True  # a bug-report moment (drawn strong); False for a moment of talking


@dataclass(frozen=True, slots=True)
class NarrationClip:
    path: Path
    seconds: float  # where the moment starts in the recording
    start_seconds: float  # where the clip starts (a few seconds before the moment)
    end_seconds: float
    part: int = 1
    parts: int = 1


@dataclass(frozen=True, slots=True)
class NarrationFiles:
    """One recording's clips and small review copy, as the package's narration index lists them."""

    source_id: str
    source_filename: str
    review_copy: Path | None
    clips: tuple[NarrationClip, ...]


def _excerpt(value: Any) -> str:
    text = " ".join(_text(value).split())
    return text if len(text) <= EXCERPT_LIMIT else text[: EXCERPT_LIMIT - 1].rstrip() + "…"


def _clip_seconds(value: Any) -> float:
    # A clip that starts at the very start of the recording is a real time, so 0 counts here.
    if isinstance(value, str) and _MOMENT_TEXT.match(value.strip()):
        return moment_seconds(value)
    number = _seconds(value)
    return max(0.0, number) if number is not None else 0.0


def narration_files(package_root: Path) -> list[NarrationFiles]:
    """Every recording's clips and small review copy in the package, in the index's order.

    Paths stay inside the package; a file the index lists but the disk no longer has is kept, so the
    page can mark it missing. An absent or partial index is normal and gives what it can.
    """

    root = _package_root(package_root)
    index = read_narration_index(root) if root is not None else None
    if root is None or index is None:
        return []
    found: list[NarrationFiles] = []
    for source in _dict_items(index.get("sources")):
        clips: list[NarrationClip] = []
        for moment in _dict_items(source.get("moments")):
            listed = [item for item in _dict_items(moment.get("clips")) if _inside_package(root, item.get("path"))]
            at = moment_seconds(moment.get("start_seconds"), moment.get("start"))
            for item in listed:
                part = _whole_number(item.get("part")) or 1
                clips.append(NarrationClip(
                    path=_inside_package(root, item.get("path")),  # type: ignore[arg-type]
                    seconds=at,
                    start_seconds=_clip_seconds(item.get("start")),
                    end_seconds=_clip_seconds(item.get("end")),
                    part=part,
                    parts=len(listed),
                ))
        found.append(NarrationFiles(
            source_id=_text(source.get("source_id")),
            source_filename=_text(source.get("source_filename")),
            review_copy=_inside_package(root, source.get("review_video")),
            clips=tuple(sorted(clips, key=lambda clip: (clip.seconds, clip.part))),
        ))
    return found


def load_moments(
    package_root: Path,
    recording: Path,
    *,
    duration_seconds: float | None = None,
) -> tuple[Moment, ...]:
    """The moments a package found in this recording, in time order; () when there are none.

    The recording is confirmed against the package's own manifest first, as for the transcript, so
    another recording's findings are never shown. Bug-report moments come from the Session timeline
    (or, in a package made before it, from the candidate and review-needed files); the moments the
    operator was talking come from the narration index.
    """

    root = _package_root(package_root)
    manifest = _read_json_object(root / "manifest.json") if root is not None else None
    source = match_source(manifest, recording, duration_seconds=duration_seconds) if manifest else None
    if root is None or source is None:
        return ()
    ids = {value for value in (_text(source.get("source_id")), _text(source.get("physical_source_id"))) if value}
    moments: list[Moment] = []
    mentions = read_session_mentions(root)
    for mention in mentions:
        raw = mention.raw
        if _text(raw.get("source_id")) not in ids:
            continue
        if mention.record_type == "explicit_marker" and mention.render_status in _COVERED_MARKER_STATUSES:
            continue
        # The same start Session Review's Play this moment uses for the record.
        at = moment_seconds(raw.get("focused_start_seconds"), mention.timestamp_seconds, mention.timestamp)
        moments.append(Moment(at, mention.record_type, moment_kind_text(mention.record_type), _excerpt(mention.excerpt)))
    if not mentions:
        candidates, review_needed = read_item_records(root)
        for record_type, records in (("ticket_mention", candidates), ("review_needed", review_needed)):
            for raw in records:
                if not ids & {_text(raw.get("source_id")), _text(raw.get("physical_source_id"))}:
                    continue
                start = (raw.get("timestamp_start_seconds"), raw.get("timestamp_start"))
                remark = (raw.get("marker_timestamp_seconds"), raw.get("marker_timestamp"))
                # The same start the Evidence page's Play this moment uses.
                at = moment_seconds(*remark, *start) if record_type == "review_needed" else moment_seconds(*start, *remark)
                words = raw.get("transcript_excerpt") or raw.get("suggested_issue_title") or raw.get("title")
                moments.append(Moment(at, record_type, moment_kind_text(record_type), _excerpt(words)))
    index = read_narration_index(root)
    for entry in _dict_items(index.get("sources")) if index else []:
        if _text(entry.get("source_id")) not in ids:
            continue
        for moment in _dict_items(entry.get("moments")):
            at = moment_seconds(moment.get("start_seconds"), moment.get("start"))
            moments.append(Moment(at, MOMENT_NARRATION, NARRATION_MOMENT_TEXT, _excerpt(moment.get("text")), finding=False))
    unique: dict[tuple[str, float], Moment] = {}
    for moment in moments:
        unique.setdefault((moment.kind, round(moment.seconds, 1)), moment)
    return tuple(sorted(unique.values(), key=lambda moment: (moment.seconds, not moment.finding)))
