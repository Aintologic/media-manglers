"""The raw bin library (215, 216, 217): every recording in the watched folders, kept and shown.

One SQLite database in the app's local data folder (never on the recordings drive), backed up once a
day with SQLite's own backup call. For each recording it keeps three separate kinds of tag:

1. The app's guess (Empty / Probably nothing / Check / Keep likely), minutes of speech and idle time.
   Written only by scans. When the rules or the Track roles setting change, the stored guesses and idle
   times are worked out again from what the library already keeps (``reapply_rules``): the speech
   seconds and every track's levels in the cache. Nothing is read from the recordings drive for that.
2. The operator's decision: Keep / Delete candidate / Undecided. A scan never changes it.
3. Purpose labels, any number per recording.

Scanning is built for a large USB drive:

- A recording is known by its content (``recording_identity``): tags follow it when it is renamed or
  moved, and an unchanged file (same path, size and modified time) is not read at all.
- Other content at a known path is another recording (268): it gets its own entry, and the recording
  that was there keeps its decision and labels and is shown Missing, by the path it had.
- A new or changed file is read from the recordings drive exactly once. The same bytes feed both
  hashes and FFmpeg's decode of every audio track; voice detection, the game-audio level and the
  waveform data all come from that one decode. A file FFmpeg cannot decode from a stream (an MOV or
  MP4 with its index at the end) is copied once to scratch and decoded from the copy.
- Each finished recording is committed on its own, so a power cut, a restart or the drive dropping off
  loses at most the recording in progress, and the next scan carries on from there.
- A watched folder that cannot be reached stops the scan; it never marks a whole drive Missing.

The app only marks. Nothing here writes, moves, renames or deletes anything on the recordings drive.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Iterable, Iterator

from . import activity_timeline, app_cache, recording_identity, recording_records, speech_facts, voice_track
from .exports import write_csv, write_json
from .recording_records import (  # noqa: F401 - the library's storage, kept under its old names here
    BACKUP_KEEP,
    BUILTIN_LABELS,
    BUSY_TIMEOUT_MS,
    DATABASE_NAME,
    LIBRARY_ROOT_ENV,
    SCHEMA_VERSION,
    WORKBENCH_LOCALAPPDATA_ENV,
    _lock_now,
    connect,
    daily_backup,
    database_path,
    inbox_reviewed,
    library_root,
    path_key,
)
from .review_inbox import SUPPORTED_EXTENSIONS, iter_media_files
from .scratch import scratch_root
from .user_folders import recordings_drive_problem, set_recordings_folders

# What a scan reads from a recording. A change here reads every recording again, so it changes only
# when what is read changes; rules that work from what was read are RULES_VERSION.
SCAN_RULE_VERSION = 1
# The guess and idle rules that work from stored data (220): a change is applied without reading.
# 3 (226): the "one track left" guess never takes a track named as never narration for the game audio.
RULES_VERSION = 3

GUESS_EMPTY = "empty"
GUESS_NOTHING = "probably_nothing"
GUESS_CHECK = "check"
GUESS_KEEP = "keep_likely"
GUESS_TEXT = {
    GUESS_KEEP: "Keep likely",
    GUESS_CHECK: "Check",
    GUESS_NOTHING: "Probably nothing",
    GUESS_EMPTY: "Empty",
}
DECISION_UNDECIDED = "undecided"
DECISION_KEEP = "keep"
DECISION_DELETE = "delete_candidate"
DECISION_TEXT = {DECISION_UNDECIDED: "Undecided", DECISION_KEEP: "Keep", DECISION_DELETE: "Delete candidate"}

# Empty: nothing worth reading.
EMPTY_MAX_BYTES = 1_000_000
EMPTY_MAX_SECONDS = 2.0
# A file changed this recently may still be recording; it waits for the next scan.
STABLE_AFTER_SECONDS = 120
# Another track counts as "someone talking" with this many clear words of its own in its short listen,
# the engine's own measure (142). Spotter call-outs do not count.
OTHER_TRACK_TALKING_WORDS = voice_track.BUSY_TRACK_TALKING_WORDS
# Speech closer together than this is one stretch for "jump to speech" (kept in the activity timeline, 226).
SPEECH_MERGE_SECONDS = activity_timeline.SPEECH_MERGE_SECONDS
SPEECH_MIN_SECONDS = activity_timeline.SPEECH_MIN_SECONDS
# Keep likely needs at least this much speech on the narration track (220); less is Check.
KEEP_MIN_SPEECH_SECONDS = 60.0
READ_CHUNK_BYTES = 8 * 1024 * 1024
HEAD_BYTES = 16 * 1024 * 1024
STREAMABLE_EXTENSIONS = {".mkv", ".webm", ".ts", ".mts", ".m2ts", ".mpg", ".mpeg"}
CONTROL_CHECK_SECONDS = 1.0


class ScanStopped(Exception):
    """The scan stopped on purpose: the operator asked, or a watched folder went away."""


class RecordingSkipped(Exception):
    """The operator skipped the recording being read."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# Storage ---------------------------------------------------------------------------------------
#
# The library is opened, made, moved up a structure step and backed up by the front door
# (``recording_records``, 242); ``connect``, ``library_root``, ``database_path``, ``daily_backup`` and
# ``path_key`` above are its, under the names the scan has always used.


@contextmanager
def scan_lock(root: Path) -> Iterator[None]:
    """One scan at a time. The lock is held by an open file the system releases if the scan dies."""

    path = Path(root) / "scan.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    try:
        try:
            _lock_now(handle)
        except OSError as exc:
            raise ScanStopped("Another raw bin scan is already running.") from exc
        yield
    finally:
        handle.close()


WORK_LOCK_NAME = "in-use.lock"


@contextmanager
def _work_in_use(work: Path) -> Iterator[None]:
    """Mark a scan's work folder as in use for as long as it reads into it (220). The system releases
    the mark if the scan dies, so its folder is then a leftover like any other."""

    handle = open(Path(work) / WORK_LOCK_NAME, "a+b")
    try:
        _lock_now(handle)
        yield
    finally:
        handle.close()


# The guess -------------------------------------------------------------------------------------


@dataclass
class Guess:
    guess: str
    reason: str
    narration_track: int | None = None  # 1-based
    speech_seconds: float = 0.0
    other_speech_track: int | None = None


def decide_guess(size_bytes: int, duration_seconds: float | None, detection: dict[str, Any] | None,
                 error: str = "") -> Guess:
    """The app's first guess at whether a recording is worth keeping (216)."""

    if size_bytes < EMPTY_MAX_BYTES:
        return Guess(GUESS_EMPTY, "The file is almost empty.")
    if duration_seconds is not None and 0 < float(duration_seconds) < EMPTY_MAX_SECONDS:
        return Guess(GUESS_EMPTY, f"The recording is {float(duration_seconds):.1f} seconds long.")
    if error:
        return Guess(GUESS_CHECK, f"It could not be read: {error}")
    detection = detection or {}
    status = str(detection.get("status") or "")
    if status == "no_audio":
        return Guess(GUESS_NOTHING, "The recording has no audio tracks.")
    activity = detection.get("track_activity") or {}
    probes = detection.get("track_probes") or {}
    roles = detection.get("track_roles") or {}
    if status == "selected" and detection.get("selected_ordinal") is not None:
        number = int(detection["selected_ordinal"]) + 1
        return narration_guess(number, float((activity.get(str(number)) or {}).get("active_seconds") or 0.0))
    if status == "uncertain":
        return Guess(GUESS_CHECK, "The engine is not sure which track has your voice. "
                     + str(detection.get("explanation") or "").strip())
    narration = detection.get("selected_ordinal")
    talking = [
        int(number) for number, probe in probes.items()
        if int(probe.get("own_words") or 0) >= OTHER_TRACK_TALKING_WORDS
        and roles.get(str(number)) not in (voice_track.ROLE_NARRATION, voice_track.ROLE_FULL_MIX)
        and (narration is None or int(number) != int(narration) + 1)
    ]
    if talking:
        number = sorted(talking)[0]
        return Guess(GUESS_CHECK, f"Your narration track is silent, but Track {number} has someone talking: "
                     "the audio may be on the wrong track.", None, 0.0, number)
    if status in ("no_narration_found", ""):
        return Guess(GUESS_NOTHING, "No speech on the narration track for the whole recording.")
    return Guess(GUESS_CHECK, str(detection.get("explanation") or "The engine could not decide."))


def narration_guess(number: int, seconds: float) -> Guess:
    """A recording whose narration track was found: Keep likely with at least a minute of speech on it,
    otherwise Check (220). The narration track is kept either way, for jump to speech."""

    seconds = round(float(seconds or 0.0), 1)
    if seconds >= KEEP_MIN_SPEECH_SECONDS:
        return Guess(GUESS_KEEP, f"Track {number} has your narration.", number, seconds)
    return Guess(GUESS_CHECK, f"Only {seconds:.0f} seconds of speech on Track {number}, your narration track; "
                 "Keep likely needs at least a minute.", number, seconds)


def idle_from_levels(titles: dict[int, str], levels: dict[int, list[float]], duration: float | None, *,
                     game: int | None, decided_by: str, reason: str, setting_value: Any,
                     narration: int | None = None) -> activity_timeline.ActivityTimeline:
    """Idle time from each track's level per second, for a scan and for re-applying the rules (220).

    ``game`` and ``decided_by`` are what ``voice_track.game_audio_track`` chose; ``narration`` is the
    narration track (0-based), which is never taken for the full mix. When the track names or
    Track roles say which track is the game audio, that track is used and never another one. When the
    recording has no such track, or it is silent the whole recording, idle time is estimated from the
    full mix, and says so; without a full mix it is unknown, with the reason. With no role set the
    automatic guess stands, as before. When the guess finds no game track because every track left
    is named as never narration (226), idle time is estimated from the full mix the same way.
    """

    sounding = {int(ordinal) for ordinal, values in levels.items() if not activity_timeline.is_silent(values)}
    role_set = decided_by in (voice_track.DECIDED_BY_NAME, voice_track.DECIDED_BY_SETTING) or (
        game is None and bool(voice_track.parse_game_tracks(setting_value)))
    if game is not None and (not role_set or int(game) in sounding):
        return activity_timeline.game_audio_timeline(levels.get(int(game)) or [], game_track=int(game))
    if not role_set and not (game is None and voice_track.is_named_never_reason(reason)):
        return activity_timeline.unknown(reason or "No game-audio track was found.", duration or 0.0)
    if levels and not sounding:
        return activity_timeline.unknown("Every audio track is silent for the whole recording.", duration or 0.0)
    if game is not None:
        why = f"Track {int(game) + 1}, your game audio, is silent for the whole recording"
    else:
        why = reason or "this recording has no game-audio track"
    mix = voice_track.full_mix_track(titles, setting_value=setting_value, sounding=sounding,
                                     narration_ordinal=narration)
    if mix is None or mix not in sounding:
        what = ("there is no full mix to estimate it from" if mix is None
                else f"the full mix (Track {mix + 1}) is silent too, so there is nothing to estimate it from")
        return activity_timeline.unknown(f"{why[0].upper()}{why[1:]}, and {what}.", duration or 0.0)
    timeline = activity_timeline.game_audio_timeline(levels.get(mix) or [])
    timeline.status = activity_timeline.STATUS_ESTIMATED
    timeline.reason = f"Estimated from the full mix (Track {mix + 1}): {why}."
    return timeline


# Speech moments joined into stretches for "jump to speech": one shared helper in the activity
# timeline (226), under its old name here for everything that imports it from the raw bin.
speech_stretches = activity_timeline.speech_stretches


# Reading a recording once ------------------------------------------------------------------------


@dataclass
class ScanOptions:
    folders: list[str]
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    model_name: str = "base.en"
    prefer_gpu: bool = True
    language: str = "en"
    track_roles: Any = ""  # the Workbench's per-track setting, "2=narration,3=game"
    cache_folder: str = ""
    cache_cap_bytes: int = app_cache.DEFAULT_CAP_BYTES
    control_path: str = ""
    library_root: str = ""
    transcriber: Any = None  # tests hand one in; otherwise the shared Whisper loader is used once
    report: Callable[[dict[str, Any]], None] | None = None
    clock: Callable[[], float] = time.time
    stable_after_seconds: float = STABLE_AFTER_SECONDS
    # Only these recordings (a time measurement before a long scan). Nothing is marked Missing then.
    only_paths: list[str] = field(default_factory=list)
    # 243: the Workbench's run this scan is, in the library: each recording read is written into it.
    records_run_id: str = ""


class _Control:
    """The Workbench's Pause and Skip, read from the run's control file about once a second."""

    def __init__(self, path: str, clock: Callable[[], float] = time.monotonic) -> None:
        self.path = Path(path) if path else None
        self.clock = clock
        self.checked = -1e9
        self.state: dict[str, Any] = {"pause": False, "skip": []}

    def _read(self) -> None:
        if self.path is None or self.clock() - self.checked < CONTROL_CHECK_SECONDS:
            return
        self.checked = self.clock()
        try:
            self.state = json.loads(self.path.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            pass

    def skipped(self, source: Path) -> bool:
        self._read()
        key = os.path.normcase(str(source))
        return any(os.path.normcase(str(item)) == key for item in self.state.get("skip") or [])

    def wait_while_paused(self, source: Path | None = None) -> None:
        self._read()
        while bool(self.state.get("pause")):
            time.sleep(0.5)
            self.checked = -1e9
            self._read()
            if source is not None and self.skipped(source):
                raise RecordingSkipped()


def _no_window() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) | int(getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))


def _probe_bytes(ffprobe: str, head: bytes) -> tuple[list[dict[str, Any]], float]:
    """The audio tracks and length from the start of the file, already read: no extra read."""

    result = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index,codec_name,channels:stream_tags=title,language",
         "-show_entries", "format=duration", "-of", "json", "-i", "pipe:0"],
        input=head, capture_output=True, timeout=120, check=False, creationflags=_no_window(),
    )
    try:
        data = json.loads((result.stdout or b"{}").decode("utf-8", errors="replace") or "{}")
    except ValueError:
        data = {}
    streams = list(data.get("streams") or [])
    try:
        duration = float((data.get("format") or {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    if not streams and result.returncode != 0:
        raise RuntimeError("FFprobe could not read the recording's tracks: "
                           + (result.stderr or b"").decode("utf-8", errors="replace").strip()[:200])
    return streams, duration


def _decode_from_stream(source: Path, size: int, options: ScanOptions, work: Path,
                        control: _Control) -> tuple[list[dict[str, Any]], float, dict[int, Path], recording_identity.StreamingIdentity]:
    identity = recording_identity.StreamingIdentity(size)
    try:
        handle = source.open("rb")
    except OSError as exc:
        raise ScanStopped(f"The recordings drive is not reachable: {exc}") from exc
    with handle:
        try:
            head = handle.read(HEAD_BYTES)
        except OSError as exc:
            raise ScanStopped(f"The recordings drive is not reachable: {exc}") from exc
        identity.update(head)
        streams, duration = _probe_bytes(options.ffprobe, head)
        wavs = {ordinal: work / f"track-{ordinal}.wav" for ordinal in range(len(streams))}
        process = None
        if streams:
            command = [options.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", "pipe:0"]
            for ordinal, target in wavs.items():
                command += voice_track._pcm_output(f"0:a:{ordinal}", target)
            errors = (work / "decode-errors.txt").open("w", encoding="utf-8", errors="replace")
            try:
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors,
                                           creationflags=_no_window())
            except OSError:
                errors.close()
                raise
        try:
            data = head
            while True:
                if process is not None and data:
                    try:
                        process.stdin.write(data)  # type: ignore[union-attr]
                    except (BrokenPipeError, OSError) as exc:
                        raise RuntimeError(f"FFmpeg stopped reading the recording: {exc}") from exc
                control.wait_while_paused(source)
                if control.skipped(source):
                    raise RecordingSkipped()
                try:
                    data = handle.read(READ_CHUNK_BYTES)
                except OSError as exc:
                    raise ScanStopped(f"The recordings drive is not reachable: {exc}") from exc
                if not data:
                    break
                identity.update(data)
            if process is not None:
                process.stdin.close()  # type: ignore[union-attr]
                code = process.wait()
                errors.close()
                if code != 0:
                    message = (work / "decode-errors.txt").read_text(encoding="utf-8", errors="replace").strip()
                    raise RuntimeError(f"FFmpeg could not decode the audio: {message[:200]}")
        finally:
            if process is not None and process.poll() is None:
                voice_track._stop_tree(process)  # type: ignore[arg-type]
                errors.close()
    return streams, duration, wavs, identity


def _decode_from_copy(source: Path, size: int, options: ScanOptions, work: Path,
                      control: _Control) -> tuple[list[dict[str, Any]], float, dict[int, Path], recording_identity.StreamingIdentity]:
    free = shutil.disk_usage(work).free
    if size > free * 0.8:
        raise RuntimeError("There is not enough free space on the scratch drive to copy it for the one-read scan.")
    identity = recording_identity.StreamingIdentity(size)
    copy = work / f"copy{source.suffix.lower()}"
    try:
        with source.open("rb") as reader, copy.open("wb") as writer:
            while True:
                control.wait_while_paused(source)
                if control.skipped(source):
                    raise RecordingSkipped()
                data = reader.read(READ_CHUNK_BYTES)
                if not data:
                    break
                identity.update(data)
                writer.write(data)
    except OSError as exc:
        if not source.exists():
            raise ScanStopped(f"The recordings drive is not reachable: {exc}") from exc
        raise
    streams, duration = voice_track.probe_audio_streams(options.ffprobe, copy)
    wavs = voice_track.extract_all_tracks(options.ffmpeg, copy, len(streams), work / "tracks") if streams else {}
    copy.unlink(missing_ok=True)
    return streams, duration, wavs, identity


def examine(source: Path, options: ScanOptions, *, control: _Control | None = None,
            transcriber_holder: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read one recording once and work out everything the library keeps about it."""

    control = control or _Control(options.control_path)
    holder = transcriber_holder if transcriber_holder is not None else {}
    before = source.stat()
    size = int(before.st_size)
    result: dict[str, Any] = {"size_bytes": size, "modified_ns": int(before.st_mtime_ns), "bytes_read": 0}
    if size < EMPTY_MAX_BYTES:
        guess = decide_guess(size, None, None)
        result.update({"guess": guess, "detection": None, "timeline": None, "levels": {}})
        return result
    work = Path(tempfile.mkdtemp(prefix="media_manglers_raw_bin_", dir=str(scratch_root())))
    try:
        # Marked in use, so a scan starting alongside never takes it for a leftover (220).
        with _work_in_use(work):
            streamable = source.suffix.lower() in STREAMABLE_EXTENSIONS
            reader = _decode_from_stream if streamable else _decode_from_copy
            streams, duration, wavs, identity = reader(source, size, options, work, control)
            result["bytes_read"] = identity.bytes_read
            sampled, content = identity.finish()
            after = source.stat()
            if int(after.st_size) != size or int(after.st_mtime_ns) != int(before.st_mtime_ns):
                raise RuntimeError("The recording changed while it was being read; it is read again next time.")
            result.update({"sampled_sha256": sampled, "content_sha256": content, "duration_seconds": duration,
                           "audio_tracks": len(streams),
                           "track_titles": {str(index + 1): str((stream.get("tags") or {}).get("title") or "")
                                            for index, stream in enumerate(streams)}})
            if 0 < duration < EMPTY_MAX_SECONDS:
                result.update({"guess": decide_guess(size, duration, None), "detection": None, "timeline": None,
                               "levels": {}})
                return result
            if not streams:
                result.update({"guess": decide_guess(size, duration, {"status": "no_audio"}), "detection": None,
                               "timeline": None, "levels": {}})
                return result
            if holder.get("transcriber") is None:
                holder["transcriber"] = options.transcriber or voice_track.whisper_transcriber(
                    options.model_name, options.prefer_gpu, options.language)
            detection = voice_track.detect_voice_track(
                source, ffmpeg_exe=options.ffmpeg, ffprobe_exe=options.ffprobe, work_dir=work,
                transcriber=holder["transcriber"], setting_roles=voice_track.parse_track_roles(_roles_value(options.track_roles)),
                decoded=(streams, duration, wavs), library=True, game_setting=_roles_value(options.track_roles),
            )
            levels = detection.pop("track_levels", {}) or {}
            game = detection.get("game_ordinal")
            timeline = idle_from_levels(
                {index: str((stream.get("tags") or {}).get("title") or "") for index, stream in enumerate(streams)},
                {int(ordinal): values for ordinal, values in levels.items()}, duration,
                game=None if game is None else int(game), decided_by=str(detection.get("game_decided_by") or ""),
                reason=str(detection.get("game_reason") or ""), setting_value=_roles_value(options.track_roles),
                narration=None if detection.get("selected_ordinal") is None else int(detection["selected_ordinal"]))
            result.update({"guess": decide_guess(size, duration, detection), "detection": detection,
                           "timeline": timeline, "levels": levels})
            return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


# The setting text "2=narration,3=game" as the mapping ``voice_track`` reads: one parser in core (226),
# under its old name here.
_roles_value = voice_track.roles_from_text


roles_key = voice_track.game_mix_roles_key


# Writing what was found --------------------------------------------------------------------------


def _location(connection: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM locations WHERE path_key = ?", (key,)).fetchone()


# 268: the start of the key a place keeps once another recording holds its path; no path starts so.
REPLACED_KEY_PREFIX = "replaced:"


def _keep_as_missing(connection: sqlite3.Connection, location: sqlite3.Row) -> None:
    """268: another recording now holds this place's path. The recording that was there keeps the place
    in the library, shown Missing by the path it had, with its decision and labels, as a recording that
    disappeared is (215). Its key becomes one no path can have, so the recording there now takes the
    path's own key."""

    connection.execute("UPDATE locations SET path_key = ?, missing = 1 WHERE location_id = ?",
                       (f"{REPLACED_KEY_PREFIX}{int(location['location_id'])}:{location['path_key']}",
                        int(location["location_id"])))


def _other_live_location(connection: sqlite3.Connection, recording_id: int, key: str) -> bool:
    for row in connection.execute(
        "SELECT path FROM locations WHERE recording_id = ? AND is_current = 1 AND missing = 0 AND path_key <> ?",
        (recording_id, key),
    ):
        if Path(row["path"]).exists():
            return True
    return False


def _store(connection: sqlite3.Connection, source: Path, root_key: str, found: dict[str, Any],
           cache: Path | None, *, run_id: str = "") -> int:
    """Commit one recording on its own (220): an interruption loses at most the one in progress.

    268: content that is not the content a known path had (another size, or another full hash) is
    never given that path's recording, its decision or its labels: it is a recording found elsewhere
    (moved, or a copy) or a new one, and the recording that was at the path is kept as Missing
    (``_keep_as_missing``). When the size is the same and one of the two hashes is unknown (a file too
    small to hash, or one that could not be read), nothing says the content changed, and the path keeps
    its recording as before."""

    now = _now()
    key = path_key(source)
    guess: Guess = found["guess"]
    detection = found.get("detection") or {}
    timeline: activity_timeline.ActivityTimeline | None = found.get("timeline")
    content = found.get("content_sha256")
    narration = guess.narration_track
    speech: list[list[float]] = []
    if narration is not None:
        intervals = ((detection.get("track_activity") or {}).get(str(narration)) or {}).get("intervals") or []
        speech = speech_stretches(intervals)
    with connection:
        existing_location = _location(connection, key)
        matches = connection.execute(
            "SELECT * FROM recordings WHERE content_sha256 = ? ORDER BY recording_id", (content,)
        ).fetchall() if content else []
        own = next((row for row in matches if existing_location is not None
                    and int(row["recording_id"]) == int(existing_location["recording_id"])), None)
        # Of several recordings with this content, the one whose old place is gone is the one that moved.
        moved = next((row for row in matches
                      if not _other_live_location(connection, int(row["recording_id"]), key)), None)
        recording_id: int | None = None
        duplicate_of = None
        before = None if existing_location is None else connection.execute(
            "SELECT content_sha256, size_bytes FROM recordings WHERE recording_id = ?",
            (int(existing_location["recording_id"]),)).fetchone()
        existing_recording = 0 if existing_location is None else int(existing_location["recording_id"])
        replaced = before is not None and (
            int(before["size_bytes"] or 0) != int(found["size_bytes"])
            or bool(before["content_sha256"] and content and before["content_sha256"] != content))
        # 244: a copy Find my bug reports or the player marked before any scan read it (never read, so no
        # hash) is this file when its size is the same. When it is a known recording renamed or moved here,
        # that recording takes the path and the marks (``recording_records.absorb_copy``); otherwise it is a
        # copy of its own and keeps its marks, even when an identical copy is known elsewhere.
        unread = existing_location is not None and recording_records.is_stand_in(connection, existing_location)
        stand_in: int | None = None
        if unread and moved is not None and not replaced:
            recording_id = int(moved["recording_id"])
            stand_in = int(existing_location["recording_id"])
            connection.execute("UPDATE locations SET is_current = 0 WHERE recording_id = ? AND path_key <> ?",
                               (recording_id, key))
        elif existing_location is not None and (own is not None or ((not matches or unread) and not replaced)):
            recording_id = int(existing_location["recording_id"])
        elif moved is not None:
            # Renamed or moved: the same content, and its old place is gone. Tags follow it.
            recording_id = int(moved["recording_id"])
            connection.execute("UPDATE locations SET is_current = 0 WHERE recording_id = ? AND path_key <> ?",
                               (recording_id, key))
        elif matches:
            duplicate_of = int(matches[0]["recording_id"])
        if recording_id is None:
            recording_id = int(connection.execute(
                "INSERT INTO recordings(first_seen_utc, duplicate_of) VALUES (?, ?)", (now, duplicate_of)
            ).lastrowid)
        connection.execute(
            """
            UPDATE recordings SET content_sha256 = COALESCE(?, content_sha256), sampled_sha256 = COALESCE(?, sampled_sha256),
                size_bytes = ?, duration_seconds = ?, audio_tracks = ?, track_titles_json = ?, guess = ?, guess_reason = ?,
                narration_track = ?, speech_seconds = ?, speech_stretches_json = ?, other_speech_track = ?,
                game_track = ?, game_track_decided_by = ?, idle_status = ?, idle_seconds = ?, idle_share = ?,
                idle_stretches_json = ?, active_stretches_json = ?,
                scanned_utc = ?, scan_rule_version = ?, bytes_read = ?, scan_error = ?, idle_reason = ?,
                rules_version = ?, rules_roles = ?
            WHERE recording_id = ?
            """,
            (
                content, found.get("sampled_sha256"), int(found["size_bytes"]), found.get("duration_seconds"),
                found.get("audio_tracks"), json.dumps(found.get("track_titles") or {}), guess.guess, guess.reason,
                narration, round(guess.speech_seconds, 1), json.dumps(speech), guess.other_speech_track,
                (timeline.game_track + 1) if timeline is not None and timeline.game_track is not None else None,
                detection.get("game_decided_by"),
                timeline.status if timeline is not None else None,
                timeline.idle_seconds if timeline is not None and timeline.status != activity_timeline.STATUS_UNKNOWN
                else None,
                timeline.idle_share if timeline is not None else None,
                json.dumps([list(item) for item in timeline.idle_stretches]) if timeline is not None else "[]",
                json.dumps([list(item) for item in timeline.active_stretches]) if timeline is not None else "[]",
                now, SCAN_RULE_VERSION, int(found.get("bytes_read") or 0), found.get("error") or None,
                (timeline.reason or None) if timeline is not None else None, RULES_VERSION,
                str(found.get("rules_roles") or ""), recording_id,
            ),
        )
        if existing_location is not None and int(existing_location["recording_id"]) != recording_id \
                and stand_in is None:
            _keep_as_missing(connection, existing_location)
            existing_location = None
        if existing_location is not None:
            connection.execute(
                "UPDATE locations SET recording_id = ?, path = ?, root_key = ?, size_bytes = ?, modified_ns = ?, "
                "is_current = 1, missing = 0, last_seen_utc = ?, registered_by = 'scan' WHERE location_id = ?",
                (recording_id, str(source), root_key, int(found["size_bytes"]), int(found["modified_ns"]), now,
                 int(existing_location["location_id"])),
            )
        else:
            connection.execute(
                "INSERT INTO locations(recording_id, path, path_key, root_key, size_bytes, modified_ns, is_current, "
                "missing, first_seen_utc, last_seen_utc) VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?)",
                (recording_id, str(source), key, root_key, int(found["size_bytes"]), int(found["modified_ns"]), now, now),
            )
        if content:
            # 244: each confirmed content once, as the scan reads it.
            connection.execute("INSERT OR IGNORE INTO contents(content_sha256, size_bytes, first_confirmed_utc) "
                               "VALUES (?, ?, ?)", (content, int(found["size_bytes"]), now))
        if stand_in is not None:
            recording_records.absorb_copy(connection, stand_in, recording_id, by="raw bin scan",
                                          size=int(found["size_bytes"]), modified=int(found["modified_ns"]))
        # 264: what the one read measured, in the same transaction; what the file's copy already held becomes shared.
        speech_facts.keep_with_scan(
            connection, recording_id=recording_id, previous=None if before is None else int(existing_recording),
            content=str(content or ""), size=int(found["size_bytes"]), modified=int(found["modified_ns"]), detection=detection,
            run_id=run_id, titles={int(number) - 1: str(title) for number, title in (found.get("track_titles") or {}).items()},
            duration=found.get("duration_seconds"), setting_roles=found.get("setting_roles"))
        if run_id:
            # 243: this recording's outcome in the run, in the same transaction that stores it.
            error = found.get("error")
            recording_records.write_outcomes(connection, run_id, [{
                "item": str(source), "recording_id": recording_id, "outcome": "failed" if error else "completed",
                "reason": str(error)[:300] if error else GUESS_TEXT.get(guess.guess, "")}], reported_by="raw bin scan")
    levels = found.get("levels") or {}
    if cache is not None and content and levels:
        app_cache.put_json(cache, "levels", content, {str(int(ordinal) + 1): values for ordinal, values in levels.items()})
    return recording_id


def _moved_candidates(connection: sqlite3.Connection, size: int, key: str) -> list[sqlite3.Row]:
    """Known recordings of this exact size whose every place is gone: what a new path may be, moved."""

    rows = connection.execute(
        "SELECT * FROM recordings WHERE size_bytes = ? AND content_sha256 IS NOT NULL AND scan_error IS NULL",
        (int(size),),
    ).fetchall()
    return [row for row in rows if not _other_live_location(connection, int(row["recording_id"]), key)]


def _reattach(connection: sqlite3.Connection, source: Path, root_key: str, stat: os.stat_result,
              control: _Control) -> tuple[int, int] | None:
    """220: a recording that was renamed or moved (its drive letter changed, say) is known again by a
    hash-only read: no decode and no listening, and its guess, decision and labels carry over.
    Returns (recording_id, bytes read), or None when it is not a known recording after all."""

    candidates = _moved_candidates(connection, int(stat.st_size), path_key(source))
    if not candidates:
        return None
    sampled = recording_identity.sampled_sha256_file(source)
    candidates = [row for row in candidates if row["sampled_sha256"] == sampled]
    if not candidates:
        return None
    identity = recording_identity.StreamingIdentity(int(stat.st_size))
    try:
        with source.open("rb") as handle:
            while True:
                control.wait_while_paused(source)
                if control.skipped(source):
                    raise RecordingSkipped()
                data = handle.read(READ_CHUNK_BYTES)
                if not data:
                    break
                identity.update(data)
    except OSError as exc:
        raise ScanStopped(f"The recordings drive is not reachable: {exc}") from exc
    _sampled, content = identity.finish()
    match = next((row for row in candidates if row["content_sha256"] == content), None)
    if match is None:
        return None
    recording_id, now, key = int(match["recording_id"]), _now(), path_key(source)
    with connection:
        # 244: a list may have marked the file here before this scan (a stand-in copy); it is this recording.
        before = _location(connection, key)
        stand_in = int(before["recording_id"]) if recording_records.is_stand_in(connection, before) else None
        connection.execute("UPDATE locations SET is_current = 0 WHERE recording_id = ? AND path_key <> ?",
                           (recording_id, key))
        connection.execute(
            "INSERT INTO locations(recording_id, path, path_key, root_key, size_bytes, modified_ns, is_current, missing, "
            "first_seen_utc, last_seen_utc) VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?) ON CONFLICT(path_key) DO UPDATE SET "
            "recording_id = excluded.recording_id, path = excluded.path, root_key = excluded.root_key, "
            "size_bytes = excluded.size_bytes, modified_ns = excluded.modified_ns, is_current = 1, missing = 0, "
            "last_seen_utc = excluded.last_seen_utc, registered_by = 'scan'",
            (recording_id, str(source), key, root_key, int(stat.st_size), int(stat.st_mtime_ns), now, now),
        )
        connection.execute("INSERT OR IGNORE INTO contents(content_sha256, size_bytes, first_confirmed_utc) "
                           "VALUES (?, ?, ?)", (content, int(stat.st_size), now))
        if stand_in is not None:
            recording_records.absorb_copy(connection, stand_in, recording_id, by="raw bin scan",
                                          size=int(stat.st_size), modified=int(stat.st_mtime_ns))
    return recording_id, identity.bytes_read


def _reapplied_idle(row: sqlite3.Row, titles: dict[int, str], roles: dict[str, str],
                    cache: Path) -> tuple[dict[str, Any], bool]:
    """One recording's idle columns under the current rules and roles, from its cached levels, and
    whether the levels were missing from the cache."""

    narration = None if row["narration_track"] is None else int(row["narration_track"]) - 1
    stored_by = str(row["game_track_decided_by"] or "")
    named_game = any(word in title.casefold() for title in titles.values() for word in voice_track.GAME_NAME_WORDS)
    role_now = bool(voice_track.parse_game_tracks(roles)) or named_game
    role_before = "=game" in str(row["rules_roles"] or "") or stored_by in (voice_track.DECIDED_BY_NAME,
                                                                             voice_track.DECIDED_BY_SETTING)
    stored = app_cache.get_json(cache, "levels", str(row["content_sha256"])) or {}
    levels = {int(number) - 1: list(values or []) for number, values in stored.items()}
    if not role_now and not role_before and row["idle_status"] != activity_timeline.STATUS_ESTIMATED:
        # No game role, then or now: the automatic guess the scan made stands (it heard every track)...
        game = None if row["game_track"] is None else int(row["game_track"]) - 1
        by, reason = stored_by, str(row["idle_reason"] or "")
        if game is not None and by == voice_track.DECIDED_BY_AUTO and voice_track.not_game_audio_name(titles.get(game, "")):
            # ...except that a track named as never narration is no longer the one left (226): the
            # guess had only that track, so now it has none, as a scan with the new rule finds.
            game, by, reason = None, "", voice_track.named_never_reason(titles, [game])
            if not levels:
                why = f"{reason[0].upper()}{reason[1:]}"
                return {"game_track": None, "game_track_decided_by": "", "idle_status": activity_timeline.STATUS_UNKNOWN,
                        "idle_seconds": None, "idle_share": None, "idle_stretches_json": "[]",
                        "active_stretches_json": "[]",
                        "idle_reason": f"{why}, and this recording's sound levels are no longer in the cache, so "
                                       "its idle time cannot be worked out again without reading it."}, True
        if not levels:
            return {}, True
    else:
        # Names and the setting need only the titles. The automatic guess (a role taken away) hears which
        # tracks have sound from their levels; it cannot compare speech moments as a scan does.
        activities = {ordinal: voice_track.TrackActivity(
            ordinal=ordinal, silent=activity_timeline.is_silent(levels.get(ordinal) or []))
            for ordinal in titles} if levels else None
        game, by = voice_track.game_audio_track(titles, setting_value=roles, narration_ordinal=narration,
                                                activities=activities)
        reason = "" if game is not None else by
        by = by if game is not None else ""
        if not levels:
            if str(row["rules_roles"] or "") == roles_key(roles) and stored_by != voice_track.DECIDED_BY_AUTO:
                # Only the rule version moved (226). A track name or Track roles decided this row, and the
                # named-never rule never changes those, so the stored idle time and its reason hold.
                return {}, True
            if (game is not None and row["idle_status"] == activity_timeline.STATUS_MEASURED
                    and row["game_track"] == game + 1):
                return {"game_track_decided_by": by}, True  # the same track: the stored idle time holds
            if str(row["rules_roles"] or "") == roles_key(roles):
                # The Track roles are the same; only the game-track rules moved (226).
                why = f"{reason[0].upper()}{reason[1:]}" if reason else "The game-track rules changed"
            else:
                why = "Track roles changed"
            return {"game_track": None, "game_track_decided_by": by, "idle_status": activity_timeline.STATUS_UNKNOWN,
                    "idle_seconds": None, "idle_share": None, "idle_stretches_json": "[]",
                    "active_stretches_json": "[]",
                    "idle_reason": f"{why}, and this recording's sound levels are no longer in the cache, so its "
                                   "idle time cannot be worked out again without reading it."}, True
    timeline = idle_from_levels(titles, levels, row["duration_seconds"], game=game, decided_by=by, reason=reason,
                                setting_value=roles, narration=narration)
    return {
        "game_track": None if timeline.game_track is None else timeline.game_track + 1,
        "game_track_decided_by": by,
        "idle_status": timeline.status,
        "idle_seconds": None if timeline.status == activity_timeline.STATUS_UNKNOWN else timeline.idle_seconds,
        "idle_share": timeline.idle_share,
        "idle_stretches_json": json.dumps([list(item) for item in timeline.idle_stretches]),
        "active_stretches_json": json.dumps([list(item) for item in timeline.active_stretches]),
        "idle_reason": timeline.reason or None,
    }, False


def reapply_rules(connection: sqlite3.Connection, *, track_roles: Any, cache: Path,
                  report: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Work the guess and idle time out again for every recording whose stored ones were made with older
    rules or other Track roles (220), from what the library keeps: the narration track and its speech
    seconds in the database, every track's levels per second in the cache. Nothing is read from the
    recordings drive. A recording whose levels are no longer in the cache keeps its idle time when the
    game track is the same, or when only the rule version moved and its track names or Track roles (not
    the automatic guess) chose the game track (226); otherwise its idle time becomes unknown, with the
    reason."""

    key = roles_key(track_roles)
    roles = _roles_value(track_roles)
    summary: dict[str, Any] = {"recordings": 0, "guess_changed": 0, "idle_changed": 0, "levels_missing": 0}
    rows = connection.execute(
        "SELECT * FROM recordings WHERE scan_error IS NULL AND content_sha256 IS NOT NULL "
        "AND (rules_version IS NULL OR rules_version <> ? OR COALESCE(rules_roles, '') <> ?)", (RULES_VERSION, key)
    ).fetchall()
    for index, row in enumerate(rows, start=1):
        summary["recordings"] += 1
        update: dict[str, Any] = {"rules_version": RULES_VERSION, "rules_roles": key}
        if row["narration_track"] is not None and row["guess"] in (GUESS_KEEP, GUESS_CHECK):
            guess = narration_guess(int(row["narration_track"]), float(row["speech_seconds"] or 0.0))
            if (guess.guess, guess.reason) != (row["guess"], row["guess_reason"]):
                summary["guess_changed"] += 1
            update.update({"guess": guess.guess, "guess_reason": guess.reason})
        try:
            titles = {int(number) - 1: str(title) for number, title in json.loads(row["track_titles_json"] or "{}").items()}
        except (TypeError, ValueError):
            titles = {}
        if titles and row["guess"] != GUESS_EMPTY:
            idle, missing = _reapplied_idle(row, titles, roles, cache)
            summary["levels_missing"] += int(missing)
            if any(name in idle and idle[name] != row[name]
                   for name in ("game_track", "idle_status", "idle_seconds", "idle_share")):
                summary["idle_changed"] += 1
            update.update(idle)
        with connection:
            connection.execute(
                f"UPDATE recordings SET {', '.join(f'{name} = ?' for name in update)} WHERE recording_id = ?",
                (*update.values(), int(row["recording_id"])),
            )
        if report is not None:
            report({"kind": "reapplied", "index": index, "total": len(rows), "recording_id": int(row["recording_id"]),
                    "guess": update.get("guess", row["guess"]), "idle_status": update.get("idle_status", row["idle_status"])})
    return summary


def _remove_scratch_leftovers() -> int:
    """Work folders an interrupted scan left behind (decoded audio, a copied MOV) are removed (220).
    A folder another scan is still reading into is left alone."""

    removed = 0
    for folder in scratch_root().glob("media_manglers_raw_bin_*"):
        if not folder.is_dir():
            continue
        lock = folder / WORK_LOCK_NAME
        if lock.exists():
            try:
                with open(lock, "a+b") as handle:
                    _lock_now(handle)
            except OSError:
                continue  # in use
        shutil.rmtree(folder, ignore_errors=True)
        removed += 1
    return removed


# Scanning ----------------------------------------------------------------------------------------


def _say(options: ScanOptions, event: dict[str, Any]) -> None:
    if options.report is not None:
        options.report(event)


def _below_normal_priority() -> None:
    """Run the scan at low priority, CPU and disk, so the PC stays usable (220). Child processes
    (FFmpeg, Whisper) start below normal too."""

    if sys.platform != "win32":
        try:
            os.nice(10)
        except OSError:
            pass
        return
    try:
        import ctypes  # noqa: PLC0415

        kernel = ctypes.windll.kernel32
        handle = kernel.GetCurrentProcess()
        kernel.SetPriorityClass(handle, 0x00004000)  # BELOW_NORMAL_PRIORITY_CLASS
        # Background mode lowers this process's disk priority as well: the scan's own reads of the
        # recordings drive. FFmpeg and Whisper still start below normal (they read only scratch).
        kernel.SetPriorityClass(handle, 0x00100000)  # PROCESS_MODE_BACKGROUND_BEGIN
    except Exception:  # noqa: BLE001 - priority is a courtesy, never a reason to fail
        pass


# 227: the waveform levels helper (track_levels) lowers itself the same way.
below_normal_priority = _below_normal_priority


def _scan_outcome(connection: sqlite3.Connection, options: ScanOptions, path: Path, outcome: str, reason: str,
                  recording_id: int | None = None) -> None:
    """243: one recording's outcome in the Workbench's run of this scan, when the scan is one."""

    if options.records_run_id:
        with connection:
            recording_records.write_outcomes(connection, options.records_run_id, [{
                "item": str(path), "outcome": outcome, "reason": reason, "recording_id": recording_id}],
                reported_by="raw bin scan")


def scan(options: ScanOptions) -> dict[str, Any]:
    """Scan the watched folders into the library. Returns what it did, for the report."""

    root = Path(options.library_root) if options.library_root else library_root()
    if options.folders:
        set_recordings_folders(list(options.folders))
    cache = app_cache.cache_root(options.cache_folder)
    cache_problem = recordings_drive_problem(cache, "cache folder", list(options.folders))
    if cache_problem:
        raise ValueError(cache_problem)
    started_utc = _now()
    summary: dict[str, Any] = {"status": "running", "files_seen": 0, "files_read": 0, "unchanged": 0, "in_use": 0,
                               "skipped": 0, "failed": 0, "bytes_read": 0, "seconds_of_video_read": 0.0,
                               "missing_marked": 0, "guesses": {}, "errors": []}
    unreachable = [folder for folder in options.folders if not Path(folder).is_dir()]
    if unreachable:
        summary.update({"status": "drive_not_reachable",
                        "message": f"Recordings drive not reachable: {', '.join(unreachable)}. Nothing was marked Missing."})
        return summary
    control = _Control(options.control_path)
    holder: dict[str, Any] = {}
    with scan_lock(root):
        _remove_scratch_leftovers()
        connection = connect(root)
        # A scan that was stopped hard could not say so; it did not finish.
        connection.execute("UPDATE scan_runs SET status = 'interrupted' WHERE status = 'running'")
        # New rules or new Track roles reach every recording already in the library first, from what
        # it stored: an unchanged recording is not read for that (220).
        summary["reapplied"] = reapply_rules(connection, track_roles=options.track_roles, cache=cache,
                                             report=lambda event: _say(options, event))
        run_id = int(connection.execute(
            "INSERT INTO scan_runs(started_utc, status) VALUES (?, 'running')", (started_utc,)
        ).lastrowid)
        connection.commit()
        try:
            files, problems = iter_media_files(options.folders, True, SUPPORTED_EXTENSIONS)
            files.sort(key=lambda item: path_key(item))
            if options.only_paths:
                wanted = {path_key(item) for item in options.only_paths}
                files = [item for item in files if path_key(item) in wanted]
            summary["errors"].extend(problems)
            roots = {path_key(folder).rstrip("\\/"): folder for folder in options.folders}
            work: list[tuple[Path, str, os.stat_result, sqlite3.Row | None]] = []

            def seen(location: sqlite3.Row | None) -> None:
                if location is not None:
                    connection.execute("UPDATE locations SET last_seen_utc = ?, missing = 0 WHERE location_id = ?",
                                       (started_utc, int(location["location_id"])))

            for path in files:
                summary["files_seen"] += 1
                try:
                    stat = path.stat()
                except OSError as exc:
                    raise ScanStopped(f"Recordings drive not reachable: {exc}") from exc
                key = path_key(path)
                root_key = next((item for item in roots if key == item or key.startswith(item + os.sep)), "")
                known = _location(connection, key)
                done_before = known is not None and connection.execute(
                    "SELECT 1 FROM recordings WHERE recording_id = ? AND scan_error IS NULL AND scan_rule_version = ?",
                    (int(known["recording_id"]), SCAN_RULE_VERSION),
                ).fetchone() is not None
                # Unchanged, and read successfully by this rule: nothing to read. A recording that could not
                # be read last time is tried again.
                if (done_before and int(known["size_bytes"]) == int(stat.st_size)
                        and int(known["modified_ns"]) == int(stat.st_mtime_ns)):
                    seen(known)
                    summary["unchanged"] += 1
                    continue
                if options.clock() - stat.st_mtime < options.stable_after_seconds:
                    seen(known)
                    summary["in_use"] += 1
                    continue
                work.append((path, root_key, stat, known))
            connection.commit()
            total_bytes = sum(int(stat.st_size) for _path, _root, stat, _known in work)
            done_bytes = 0
            begun = time.monotonic()
            for index, (path, root_key, stat, known) in enumerate(work, start=1):
                _say(options, {"kind": "file_start", "index": index, "total": len(work), "path": str(path),
                               "size_bytes": int(stat.st_size), "done_bytes": done_bytes, "total_bytes": total_bytes,
                               "elapsed": time.monotonic() - begun})
                if control.skipped(path):
                    seen(known)
                    connection.commit()
                    _scan_outcome(connection, options, path, "skipped", "Skipped by you.")
                    summary["skipped"] += 1
                    continue
                try:
                    # A file a list marked before this scan (244) may be a known recording renamed or moved too.
                    if known is None or recording_records.is_stand_in(connection, known):
                        again = _reattach(connection, path, root_key, stat, control)
                        if again is not None:
                            _scan_outcome(connection, options, path, "completed", "Moved; its tags kept.", again[0])
                            summary["files_read"] += 1
                            summary["reattached"] = summary.get("reattached", 0) + 1
                            summary["bytes_read"] += again[1]
                            done_bytes += int(stat.st_size)
                            _say(options, {"kind": "file_done", "index": index, "total": len(work), "path": str(path),
                                           "recording_id": again[0], "guess": "moved", "bytes_read": again[1],
                                           "size_bytes": int(stat.st_size), "done_bytes": done_bytes,
                                           "total_bytes": total_bytes, "elapsed": time.monotonic() - begun})
                            continue
                    found = examine(path, options, control=control, transcriber_holder=holder)
                except RecordingSkipped:
                    seen(known)
                    connection.commit()
                    _scan_outcome(connection, options, path, "skipped", "Skipped by you.")
                    summary["skipped"] += 1
                    _say(options, {"kind": "file_skipped", "index": index, "total": len(work), "path": str(path)})
                    continue
                except ScanStopped:
                    raise
                except Exception as exc:  # noqa: BLE001 - one bad file never stops the scan
                    if not Path(path).exists() or not all(Path(folder).is_dir() for folder in options.folders):
                        raise ScanStopped(f"Recordings drive not reachable: {exc}") from exc
                    found = {"size_bytes": int(stat.st_size), "modified_ns": int(stat.st_mtime_ns), "bytes_read": 0,
                             "guess": decide_guess(int(stat.st_size), None, None, error=str(exc)[:300]),
                             "error": str(exc)[:500]}
                    summary["failed"] += 1
                    summary["errors"].append({"path": str(path), "error": str(exc)[:300]})
                found["rules_roles"] = roles_key(options.track_roles)
                found["setting_roles"] = voice_track.parse_track_roles(_roles_value(options.track_roles))
                recording_id = _store(connection, path, root_key, found, cache, run_id=options.records_run_id)
                summary["files_read"] += 1
                summary["bytes_read"] += int(found.get("bytes_read") or 0)
                summary["seconds_of_video_read"] += float(found.get("duration_seconds") or 0.0)
                guess = found["guess"].guess
                summary["guesses"][guess] = summary["guesses"].get(guess, 0) + 1
                done_bytes += int(stat.st_size)
                connection.execute(
                    "UPDATE scan_runs SET files_read = ?, bytes_read = ?, seconds_of_video_read = ? WHERE run_id = ?",
                    (summary["files_read"], summary["bytes_read"], summary["seconds_of_video_read"], run_id),
                )
                connection.commit()
                _say(options, {"kind": "file_done", "index": index, "total": len(work), "path": str(path),
                               "recording_id": recording_id, "guess": guess, "bytes_read": int(found.get("bytes_read") or 0),
                               "size_bytes": int(stat.st_size), "done_bytes": done_bytes, "total_bytes": total_bytes,
                               "duration_seconds": float(found.get("duration_seconds") or 0.0),
                               "elapsed": time.monotonic() - begun})
            # Only a scan that reached every file marks what it did not see as Missing: not one limited to
            # a few files, not one whose folder walk hit an error, and not one whose folder has gone since.
            complete_walk = not problems and all(Path(folder).is_dir() for folder in options.folders)
            if not complete_walk:
                summary["message"] = "The folder walk was not complete, so nothing was marked Missing."
            with connection:
                for key in roots if (complete_walk and not options.only_paths) else ():
                    marked = connection.execute(
                        "UPDATE locations SET missing = 1 WHERE root_key = ? AND is_current = 1 AND missing = 0 "
                        "AND last_seen_utc < ?",
                        (key, started_utc),
                    ).rowcount
                    summary["missing_marked"] += int(marked or 0)
            summary["status"] = "completed"
        except ScanStopped as exc:
            summary.update({"status": "drive_not_reachable", "message": str(exc)})
        finally:
            connection.execute("UPDATE scan_runs SET finished_utc = ?, status = ?, detail = ? WHERE run_id = ?",
                               (_now(), summary["status"], json.dumps({k: v for k, v in summary.items() if k != "errors"}),
                                run_id))
            connection.commit()
            connection.close()
    app_cache.enforce_cap(cache, options.cache_cap_bytes)
    return summary


# Reading the library -----------------------------------------------------------------------------


EXPORT_FIELDS = [
    "name", "path", "missing", "guess", "guess_reason", "minutes_of_speech", "idle_share", "idle_minutes",
    "idle_note", "decision", "labels", "reviewed_by_inbox", "flag_count", "duration_minutes", "size_gb", "audio_tracks",
    "narration_track", "game_track", "first_seen_utc", "scanned_utc", "content_sha256",
]


# Review Media Inbox's verdict comes through the front door, from the Inbox's records in the same library
# (``recording_records.inbox_reviewed``, ``recording_records.reviewed_by_inbox``; 224, 268).
_reviewed_by_inbox = recording_records.reviewed_by_inbox


def list_recordings(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every recording a scan found, with its current place, tags and the Inbox's verdict, for the screen.
    A copy only Find my bug reports or the player knows (outside the watched folders) is not listed (244)."""

    verdicts = recording_records.inbox_reviewed(connection)
    reviewed_hashes, reviewed_paths = verdicts.hashes, verdicts.paths
    labels: dict[int, list[str]] = {}
    for row in connection.execute(
        "SELECT rl.recording_id, l.name FROM recording_labels rl JOIN labels l ON l.label_id = rl.label_id ORDER BY l.name"
    ):
        labels.setdefault(int(row["recording_id"]), []).append(str(row["name"]))
    rows: list[dict[str, Any]] = []
    # A library read without being moved up (read-only, by an older structure) has no copies a list made.
    scanned_only = (
        "WHERE NOT EXISTS (SELECT 1 FROM locations o WHERE o.recording_id = r.recording_id) OR EXISTS "
        "(SELECT 1 FROM locations s WHERE s.recording_id = r.recording_id AND s.registered_by = 'scan')"
        if any(row[1] == "registered_by" for row in connection.execute("PRAGMA table_info(locations)")) else "")
    for row in connection.execute(
        f"""
        SELECT r.*, l.path AS path, l.path_key AS path_key, l.missing AS missing FROM recordings r
        LEFT JOIN locations l ON l.location_id = (
            SELECT location_id FROM locations WHERE recording_id = r.recording_id AND is_current = 1
            ORDER BY missing, last_seen_utc DESC LIMIT 1)
        {scanned_only}
        ORDER BY r.recording_id
        """
    ):
        item = dict(row)
        item["labels"] = labels.get(int(row["recording_id"]), [])
        item["missing"] = bool(row["missing"]) if row["missing"] is not None else True
        item["reviewed_by_inbox"] = _reviewed_by_inbox(row, reviewed_hashes, reviewed_paths)
        # False until the Inbox's records are in the library: then "not reviewed" only means "not known" (224, F11).
        item["inbox_known"] = verdicts.known
        for name in ("speech_stretches_json", "idle_stretches_json", "active_stretches_json", "track_titles_json", "flags_json"):
            try:
                item[name[:-5]] = json.loads(row[name] or ("{}" if name == "track_titles_json" else "[]"))
            except ValueError:
                item[name[:-5]] = {} if name == "track_titles_json" else []
        rows.append(item)
    return rows


def export_row(item: dict[str, Any]) -> dict[str, Any]:
    """One recording as the export writes it: the words on screen, not internal codes."""

    duration = float(item.get("duration_seconds") or 0.0)
    idle_share = item.get("idle_share")
    return {
        "name": Path(str(item.get("path") or "")).name,
        "path": item.get("path") or "",
        "missing": "yes" if item.get("missing") else "no",
        "guess": GUESS_TEXT.get(str(item.get("guess") or ""), ""),
        "guess_reason": item.get("guess_reason") or "",
        "minutes_of_speech": round(float(item.get("speech_seconds") or 0.0) / 60, 1),
        "idle_share": "" if idle_share is None else f"{round(float(idle_share) * 100)}%",
        "idle_minutes": "" if item.get("idle_seconds") is None else round(float(item["idle_seconds"]) / 60, 1),
        # Why idle time is estimated from the full mix, or unknown (220); blank when it was measured.
        "idle_note": item.get("idle_reason") or "",
        "decision": DECISION_TEXT.get(str(item.get("decision") or DECISION_UNDECIDED), "Undecided"),
        "labels": "; ".join(item.get("labels") or []),
        # 224 (F11, Decision 9): "unknown" while the library cannot say, never "no".
        "reviewed_by_inbox": "yes" if item.get("reviewed_by_inbox") else (
            "no" if item.get("inbox_known", True) else "unknown"),
        "flag_count": "" if item.get("flag_count") is None else int(item["flag_count"]),
        "duration_minutes": round(duration / 60, 1),
        "size_gb": round(int(item.get("size_bytes") or 0) / 1024 ** 3, 2),
        "audio_tracks": item.get("audio_tracks") or "",
        "narration_track": item.get("narration_track") or "",
        "game_track": item.get("game_track") or "",
        "first_seen_utc": item.get("first_seen_utc") or "",
        "scanned_utc": item.get("scanned_utc") or "",
        "content_sha256": item.get("content_sha256") or "",
    }


def export(items: list[dict[str, Any]], destination: Path, *, recordings_folders: list[str] | None = None) -> Path:
    """Write the current view to CSV or JSON, by the file's extension. Never onto the recordings drive."""

    destination = Path(destination)
    problem = recordings_drive_problem(destination.parent, "export folder", recordings_folders)
    if problem:
        raise ValueError(problem)
    rows = [export_row(item) for item in items]
    if destination.suffix.lower() == ".json":
        write_json(destination, rows)
    else:
        write_csv(destination, rows, EXPORT_FIELDS)
    return destination


def set_decision(connection: sqlite3.Connection, recording_ids: Iterable[int], decision: str) -> None:
    if decision not in DECISION_TEXT:
        raise ValueError(f"Not a decision: {decision!r}")
    with connection:
        connection.executemany(
            "UPDATE recordings SET decision = ?, decision_utc = ? WHERE recording_id = ?",
            [(decision, _now(), int(item)) for item in recording_ids],
        )


def label_names(connection: sqlite3.Connection) -> list[str]:
    return [str(row["name"]) for row in connection.execute("SELECT name FROM labels ORDER BY builtin DESC, name")]


def add_label(connection: sqlite3.Connection, name: str) -> str:
    text = " ".join(str(name or "").split())
    if not text:
        raise ValueError("A label needs a name.")
    with connection:
        connection.execute("INSERT OR IGNORE INTO labels(name, builtin) VALUES (?, 0)", (text,))
    return text


def set_label(connection: sqlite3.Connection, recording_ids: Iterable[int], name: str, on: bool) -> None:
    text = add_label(connection, name)
    with connection:
        label_id = int(connection.execute("SELECT label_id FROM labels WHERE name = ?", (text,)).fetchone()["label_id"])
        if on:
            connection.executemany("INSERT OR IGNORE INTO recording_labels(recording_id, label_id) VALUES (?, ?)",
                                   [(int(item), label_id) for item in recording_ids])
        else:
            connection.executemany("DELETE FROM recording_labels WHERE recording_id = ? AND label_id = ?",
                                   [(int(item), label_id) for item in recording_ids])


# Deep scan ---------------------------------------------------------------------------------------


def transcripts_root(root: Path | None = None) -> Path:
    return Path(root or library_root()) / "transcripts"


def deep_scan(connection: sqlite3.Connection, recording_id: int, options: ScanOptions, *,
              transcribe: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
              root: Path | None = None, glossary: Any = None) -> dict[str, Any]:
    """Transcribe one recording's narration track with the shared Whisper path and count its "flag
    for AI" requests (216). The transcript is kept in the library folder: it is slow to rebuild."""

    from ..providers import whisper_local  # noqa: PLC0415
    from .evidence_package import find_requests  # noqa: PLC0415

    row = connection.execute(
        "SELECT r.*, l.path AS path FROM recordings r JOIN locations l ON l.recording_id = r.recording_id "
        "AND l.is_current = 1 AND l.missing = 0 WHERE r.recording_id = ? LIMIT 1", (int(recording_id),)
    ).fetchone()
    if row is None:
        raise ValueError("That recording is not on the drive right now.")
    track = row["narration_track"] or row["other_speech_track"]
    if not track:
        return {"recording_id": int(recording_id), "status": "no_track", "flag_count": None,
                "message": "There is no track with speech to transcribe."}
    folder = transcripts_root(root) / str(row["content_sha256"] or f"recording-{recording_id}")
    work = Path(tempfile.mkdtemp(prefix="media_manglers_deep_scan_", dir=str(scratch_root())))
    try:
        wav = voice_track.extract_track(options.ffmpeg, Path(row["path"]), int(track) - 1, work / "narration.wav")
        request = {"audio_path": str(wav), "output_dir": str(folder), "model_name": options.model_name,
                   "language_code": options.language, "prefer_gpu": options.prefer_gpu,
                   "narration_speech_mode": "Sparse", "glossary_entries": glossary or []}
        result = (transcribe or whisper_local.transcribe_from_request)(request)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    transcript = Path(str(result.get("json_path") or folder / "transcript.json"))
    try:
        segments = json.loads(transcript.read_text(encoding="utf-8")).get("segments") or []
    except (OSError, ValueError):
        segments = []
    flags = find_requests(segments)
    with connection:
        connection.execute(
            "UPDATE recordings SET flag_count = ?, flags_json = ?, transcript_path = ? WHERE recording_id = ?",
            (len(flags), json.dumps(flags), str(transcript), int(recording_id)),
        )
    return {"recording_id": int(recording_id), "status": "transcribed", "flag_count": len(flags), "flags": flags,
            "transcript_path": str(transcript)}


# The helper commands -----------------------------------------------------------------------------


def _options_from(payload: dict[str, Any]) -> ScanOptions:
    folders = payload.get("folders") or []
    if isinstance(folders, str):
        folders = [part.strip() for part in folders.replace("\n", ";").split(";") if part.strip()]
    return ScanOptions(
        folders=[str(item) for item in folders],
        ffmpeg=str(payload.get("ffmpeg") or "ffmpeg"),
        ffprobe=str(payload.get("ffprobe") or "ffprobe"),
        model_name=str(payload.get("model_name") or "base.en"),
        prefer_gpu=bool(payload.get("prefer_gpu", True)),
        language=str(payload.get("language") or "en"),
        track_roles=payload.get("track_roles") or "",
        cache_folder=str(payload.get("cache_folder") or ""),
        cache_cap_bytes=int(payload.get("cache_cap_bytes") or app_cache.DEFAULT_CAP_BYTES),
        control_path=str(payload.get("run_control_path") or ""),
        library_root=str(payload.get("library_root") or ""),
        only_paths=[str(item) for item in payload.get("only_paths") or []],
        records_run_id=str(payload.get("records_run_id") or ""),
        report=_print_progress,
    )


def _print_progress(event: dict[str, Any]) -> None:
    """Progress for Queue / Progress (MM_PROGRESS_V1) and a plain line for the run log."""

    kind = event.get("kind")
    total = int(event.get("total") or 0)
    index = int(event.get("index") or 0)
    name = Path(str(event.get("path") or "")).name
    done, everything = int(event.get("done_bytes") or 0), int(event.get("total_bytes") or 0)
    elapsed = float(event.get("elapsed") or 0.0)
    left = ""
    if done and everything > done and elapsed > 0:
        seconds = int(elapsed * (everything - done) / done)
        left = f", about {seconds // 3600}h {seconds // 60 % 60:02d}m left"
    word = GUESS_TEXT.get(str(event.get("guess")), "Moved, tags kept" if event.get("guess") == "moved" else "")
    if kind == "reapplied":
        # New rules or Track roles reaching the recordings already in the library, before the scan reads.
        record = {"schema": "MM_PROGRESS_V1", "phase": "Applying new rules to the library", "phase_index": 1,
                  "phase_count": 1, "source_name": "", "source_ordinal": index, "source_total": total,
                  "source_completed": index, "source_state": "active", "source_terminal": False,
                  "activity": f"Applying new rules to the library: {index} of {total} (nothing is read from your recordings)",
                  "progress_kind": "work_units", "completed": index, "total": max(1, total)}
        print("MM_PROGRESS_V1 " + json.dumps(record, ensure_ascii=False), flush=True)
        return
    if kind == "file_start":
        activity = f"Reading {name} ({index} of {total}){left}"
    elif kind == "file_done":
        activity = f"{word}: {name} ({index} of {total})"
        print(f"Scanned {index} of {total}: {name} - {word}; "
              f"read {event.get('bytes_read')} of {event.get('size_bytes')} bytes{left}", flush=True)
    else:
        activity = f"Skipped {name}"
    record = {"schema": "MM_PROGRESS_V1", "phase": "Scanning the raw bin", "phase_index": 1, "phase_count": 1,
              "source_name": name, "source_ordinal": index, "source_total": total,
              "source_completed": index if kind == "file_done" else max(0, index - 1),
              "source_state": "active", "source_terminal": False, "activity": activity}
    if everything:
        record.update({"progress_kind": "work_units", "completed": done // (1024 * 1024),
                       "total": max(1, everything // (1024 * 1024))})
    print("MM_PROGRESS_V1 " + json.dumps(record, ensure_ascii=False), flush=True)


def scan_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    # The helper process is the scan's own, so it alone goes to low priority, CPU and disk.
    _below_normal_priority()
    return scan(_options_from(payload))


def reapply_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """The current rules and Track roles applied to the library as it is (220). Reads nothing from the
    recordings drive: only the library database and the cache."""

    options = _options_from(payload)
    root = Path(options.library_root) if options.library_root else library_root()
    cache = app_cache.cache_root(options.cache_folder)
    problem = recordings_drive_problem(cache, "cache folder", list(options.folders) or None)
    if problem:
        raise ValueError(problem)
    connection = connect(root)

    def say(event: dict[str, Any]) -> None:
        print(f"Re-applied {event['index']} of {event['total']}: recording {event['recording_id']} - "
              f"{GUESS_TEXT.get(str(event.get('guess')), '')}; idle {event.get('idle_status') or 'none'}", flush=True)

    try:
        return reapply_rules(connection, track_roles=options.track_roles, cache=cache,
                             report=say)
    finally:
        connection.close()


def deep_scan_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    options = _options_from(payload)
    root = Path(options.library_root) if options.library_root else library_root()
    connection = connect(root)
    try:
        results = []
        for recording_id in payload.get("recording_ids") or []:
            try:
                results.append(deep_scan(connection, int(recording_id), options, root=root,
                                         glossary=payload.get("glossary_entries")))
            except Exception as exc:  # noqa: BLE001 - one recording never stops the others
                results.append({"recording_id": int(recording_id), "status": "failed", "error": str(exc)[:300]})
        return {"results": results}
    finally:
        connection.close()
