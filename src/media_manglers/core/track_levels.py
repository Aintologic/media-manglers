"""The sound level of every track of a whole recording, measured once and kept (125 Part 2, 135).

One shared job for the built-in player's waveform lanes and for the waveforms built after a run. A
recording the raw bin library has scanned already has its levels (one value per second for every
audio track, kept by the library under the recording's content); those are used while the library's
row is still that file. Any other recording is measured here, once, by the one decoder's streaming
mode (``voice_track.stream_levels``) with the Raw bin's own rule, so the values are the same however
they were made. The result goes to the cache folder under a key made from the file's name, size and
modified time: the cache file holds no path, name or title, and a changed file is measured again.

Measuring saves what it has every minute and when it is stopped, and the next measure carries on from
there. It pauses while the player asks it to (the run's control file, the shared Pause), and stops
when the control file skips the recording (the shared Skip). It never writes beside the recording and
never into a cache folder on the recordings drive.

The same read can also keep what ``speech_facts`` needs (264: ``facts``): each track's 50 ms levels go to a
checkpoint in the cache folder, so a stop keeps its place, and when the read ends each track's moments are worked out
by the one rule and stored in the library. The narration track is listened for only if nothing else can tell,
on the processor. The checkpoint holds numbers only, and goes once the facts are stored.
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Callable

from . import app_cache, raw_bin_library, recording_records, safe_write, speech_facts, voice_track
from .scratch import scratch_root
from .user_folders import recordings_drive_problem
from .whisper_models import ModelNotApproved

# This job's own cache entries. The raw bin library keeps its levels under "levels", by content.
LEVELS_KIND = "levels-file"
# The 50 ms levels of a measure that also keeps speech facts (264), until they are stored.
FRAMES_KIND = "voice-frames"
FRAMES_PER_SECOND = round(1.0 / voice_track.FRAME_SECONDS)
# A change to how levels are measured makes every entry of an older rule stale.
RULE_VERSION = 1
CHECKPOINT_SECONDS = 60.0
# The player and the after-run builds read progress from these lines.
PROGRESS_PREFIX = "MM_LEVELS "
PROGRESS_SECONDS = 1.0
# How often the control file (Pause, and Skip to stop) is read.
CONTROL_CHECK_SECONDS = 0.25
MAX_TRACKS = 8
STATUS_READY = "ready"
STATUS_STOPPED = "stopped"
STATUS_IN_USE = "in_use"
STATUS_CHANGED = "changed"
STATUS_NO_AUDIO = "no_audio"


@dataclass
class Levels:
    """One level per second (dBFS) for each audio track, numbered from 1."""

    tracks: dict[int, list[float]] = field(default_factory=dict)
    duration_seconds: float = 0.0
    complete: bool = False
    origin: str = ""  # "library" or "measured"

    @property
    def seconds(self) -> int:
        return max((len(values) for values in self.tracks.values()), default=0)


def _stat(source: Path) -> os.stat_result | None:
    try:
        return Path(source).stat()
    except OSError:
        return None


def file_key(source: Path, stat: os.stat_result | None = None) -> str:
    """The cache key: a hash of the file's name, size and modified time, never the name itself."""

    stat = stat or Path(source).stat()
    text = f"{Path(source).name.casefold()}|{int(stat.st_size)}|{int(stat.st_mtime_ns)}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _tracks_from(data: Any) -> dict[int, list[float]]:
    found: dict[int, list[float]] = {}
    if not isinstance(data, dict):
        return found
    for key, values in data.items():
        if isinstance(values, list) and str(key).isdigit():
            found[int(key)] = [float(value) for value in values]
    return found


def library_levels(source: Path, *, cache: Path, stat: os.stat_result | None = None,
                   library_root: Path | None = None) -> Levels | None:
    """The raw bin library's levels for this file, only while its row is current and still this file."""

    stat = stat or _stat(source)
    if stat is None:
        return None
    # Asked of the library's front door, which reads it read-only (242).
    row = recording_records.current_copy(source, root=library_root)
    if (not row or not row["content_sha256"] or int(row["size_bytes"] or -1) != int(stat.st_size)
            or int(row["modified_ns"] or -1) != int(stat.st_mtime_ns)):
        return None
    tracks = _tracks_from(app_cache.get_json(cache, "levels", str(row["content_sha256"])))
    if not tracks:
        return None
    return Levels(tracks=tracks, duration_seconds=float(row["duration_seconds"] or 0.0), complete=True,
                  origin="library")


def measured_levels(source: Path, *, cache: Path, stat: os.stat_result | None = None) -> Levels | None:
    """This job's own entry for this file: complete, or what a stopped measure had reached."""

    stat = stat or _stat(source)
    if stat is None:
        return None
    data = app_cache.get_json(cache, LEVELS_KIND, file_key(source, stat))
    if not isinstance(data, dict) or data.get("rule") != RULE_VERSION:
        return None
    if int(data.get("size") or -1) != int(stat.st_size) or int(data.get("mtime_ns") or -1) != int(stat.st_mtime_ns):
        return None
    tracks = _tracks_from(data.get("tracks"))
    if not tracks:
        return None
    return Levels(tracks=tracks, duration_seconds=float(data.get("duration") or 0.0),
                  complete=bool(data.get("complete")), origin="measured")


def cached_levels(source: Path, *, cache: Path, library_root: Path | None = None) -> Levels | None:
    """The one lookup: the raw bin library's levels first, then this job's own (complete or not)."""

    stat = _stat(source)
    if stat is None:
        return None
    return (library_levels(source, cache=cache, stat=stat, library_root=library_root)
            or measured_levels(source, cache=cache, stat=stat))


def _save(cache: Path, source: Path, stat: os.stat_result, levels: Levels) -> Path:
    # Only numbers: no path, name or title (125).
    return app_cache.put_json(cache, LEVELS_KIND, file_key(source, stat), {
        "rule": RULE_VERSION, "size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns),
        "duration": round(float(levels.duration_seconds), 3), "complete": bool(levels.complete),
        "tracks": {str(track): values for track, values in sorted(levels.tracks.items())},
    })


class _Control:
    """The shared Pause and Skip for this measure, read from its control file a few times a second."""

    def __init__(self, path: str, source: Path, clock: Callable[[], float] = time.monotonic) -> None:
        self.path = Path(path) if path else None
        self.key = os.path.normcase(str(source))
        self.clock = clock
        self.checked = -1e9
        self.state: dict[str, Any] = {}

    def _read(self) -> dict[str, Any]:
        if self.path is not None and self.clock() - self.checked >= CONTROL_CHECK_SECONDS:
            self.checked = self.clock()
            try:
                self.state = json.loads(self.path.read_text(encoding="utf-8")) or {}
            except (OSError, ValueError):
                pass
        return self.state

    def paused(self) -> bool:
        return bool(self._read().get("pause"))

    def stopped(self) -> bool:
        return any(os.path.normcase(str(item)) == self.key for item in self._read().get("skip") or [])


class _Frames:
    """The checkpoint of a read for speech facts: one file of 50 ms levels (every track's, in frame order, as 8-byte
    numbers: the same values ``analyze_track_wav`` works from) and one small file saying how far it is good to."""

    def __init__(self, cache: Path, source: Path, stat: os.stat_result, ordinals: list[int]) -> None:
        key = file_key(source, stat)
        self.data = app_cache.item_path(cache, FRAMES_KIND, key, ".bin")
        self.notes = app_cache.item_path(cache, FRAMES_KIND, key, ".json")
        self.ordinals = ordinals
        self.stamp = {"rule": voice_track.ACTIVITY_RULE_VERSION, "size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns),
                      "tracks": ordinals}
        self.peaks = {ordinal: 0 for ordinal in ordinals}
        self.seconds = 0
        self.complete = False
        self._handle: Any = None

    def resume(self) -> None:
        """Pick up what an earlier read saved, when it was this file under this rule."""

        try:
            saved = json.loads(self.notes.read_text(encoding="utf-8"))
            have = self.data.stat().st_size
        except (OSError, ValueError):
            return
        if not isinstance(saved, dict) or any(saved.get(name) != value for name, value in self.stamp.items()):
            return
        seconds = int(saved.get("seconds") or 0)
        # A finished read may end part way through its last second, so only an unfinished one is measured by its size.
        if have < self._offset(seconds - 1 if saved.get("complete") else seconds):
            return
        self.seconds = seconds
        self.complete = bool(saved.get("complete"))
        self.peaks.update({int(name): int(value) for name, value in (saved.get("peaks") or {}).items()})

    def _offset(self, second: int) -> int:
        return int(second) * FRAMES_PER_SECOND * len(self.ordinals) * 8

    def add(self, first: int, frames: dict[int, list[float]], peaks: dict[int, int]) -> None:
        if self._handle is None:
            self.data.parent.mkdir(parents=True, exist_ok=True)
            self._handle = open(self.data, "r+b" if self.data.exists() else "w+b")
        self._handle.seek(self._offset(first))
        self._handle.truncate()
        count = max((len(values) for values in frames.values()), default=0)
        numbers = array("d", (frames[ordinal][index] for index in range(count) for ordinal in self.ordinals))
        self._handle.write(numbers.tobytes())
        self.seconds = int(first) + (count + FRAMES_PER_SECOND - 1) // FRAMES_PER_SECOND
        for ordinal, value in peaks.items():
            self.peaks[ordinal] = max(self.peaks[ordinal], int(value))

    def save(self, *, complete: bool = False) -> None:
        if self._handle is not None:
            self._handle.flush()
            os.fsync(self._handle.fileno())
        self.complete = complete
        safe_write.write_json(self.notes, {**self.stamp, "seconds": self.seconds, "complete": complete,
                                           "peaks": {str(ordinal): value for ordinal, value in self.peaks.items()}})

    def read(self) -> dict[int, list[float]]:
        self.close()
        numbers = array("d")
        numbers.frombytes(self.data.read_bytes())
        width = len(self.ordinals)
        return {ordinal: list(numbers[place::width]) for place, ordinal in enumerate(self.ordinals)}

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def remove(self) -> None:
        self.close()
        for path in (self.notes, self.data):
            try:
                safe_write.remove(path)
            except OSError:
                pass  # rebuildable, and it is overwritten or capped later


def _store_facts(source: Path, frames: _Frames, streams: list[dict[str, Any]], duration: float, *, ffmpeg: str, facts: dict[str, Any],
                 stopped: Callable[[], bool], work: Path) -> str:
    """The read is over: each track's moments go to the library, the narration track is listened for only if nothing
    else can tell, and the checkpoint goes. A stop while listening keeps the checkpoint, so nothing is read again.
    Returns how it ended: "stored", "stopped" or "not_stored". Never fails the waveform."""

    roles_value = facts.get("track_roles")
    setting_roles = voice_track.parse_track_roles(voice_track.roles_from_text(roles_value))
    titles = {index: str((stream.get("tags") or {}).get("title") or "") for index, stream in enumerate(streams)}
    try:
        levels = frames.read()
    except OSError:
        return "not_stored"
    activities = {ordinal: voice_track.activity_from_frames(levels[ordinal], ordinal, frames.peaks.get(ordinal, 0))
                  for ordinal in frames.ordinals}
    stored = speech_facts.record_measure(source, voice_track.track_details(activities), measured_by=speech_facts.BY_BACKGROUND,
                                         titles=titles, duration=duration, setting_roles=setting_roles)
    if not stored:
        return "not_stored"
    if speech_facts.jump_points(source, track_roles=roles_value).needs_listen:
        try:
            detection = voice_track.detect_from_activities(
                source, activities, streams, duration, ffmpeg_exe=ffmpeg, work_dir=work, setting_roles=setting_roles,
                transcriber=facts.get("transcriber"), stopped=stopped,
                model_name=str(facts.get("model_name") or "base.en"), language_code=str(facts.get("language_code") or "en"))
        except voice_track.ListeningStopped:
            return "stopped"
        except ModelNotApproved as exc:
            # Installer plan, Stage 3: a background job never asks and never downloads. It skips the listening with a
            # note, and a later try listens once the model is approved.
            print(PROGRESS_PREFIX + json.dumps({"listening_skipped": "model_not_approved", "model": exc.model}),
                  flush=True)
            return "not_stored"
        except Exception as exc:  # noqa: BLE001 - listening only adds to what was measured; the player says why
            # The checkpoint stays, so a later try listens without reading the whole recording again.
            print(PROGRESS_PREFIX + json.dumps({"listening_failed": type(exc).__name__}), flush=True)
            return "not_stored"
        speech_facts.record_measure(source, detection, measured_by=speech_facts.BY_BACKGROUND, titles=titles, duration=duration,
                                    setting_roles=setting_roles)
    frames.remove()
    return "stored"


def measure(
    source: Path,
    *,
    ffmpeg: str,
    ffprobe: str,
    cache: Path,
    cap_bytes: int = app_cache.DEFAULT_CAP_BYTES,
    control_path: str = "",
    recordings_folders: list[str] | None = None,
    stable_after_seconds: float = raw_bin_library.STABLE_AFTER_SECONDS,
    stall_seconds: float = voice_track.DECODE_STALL_SECONDS,
    report: Callable[[dict[str, Any]], None] | None = None,
    work_dir: Path | None = None,
    fresh: bool = False,
    facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Measure one recording into the cache, carrying on from what an earlier measure saved.

    ``fresh`` (Measure the sound again) starts from the beginning and replaces this job's own entry. ``facts``
    (264: its Track roles) also keeps speech facts for a recording that has none, by the same read; a recording
    whose waveform is already whole gets that read only, and its levels stay as they are.
    """

    source = Path(source)
    problem = recordings_drive_problem(cache, "cache folder", recordings_folders)
    if problem:
        raise ValueError(problem)
    before = source.stat()
    if stable_after_seconds and time.time() - before.st_mtime < stable_after_seconds:
        return {"status": STATUS_IN_USE, "seconds": 0, "duration": 0.0}
    known = None if fresh else cached_levels(source, cache=cache)
    points = speech_facts.jump_points(source, track_roles=facts.get("track_roles")) if facts is not None else None
    wants_facts = points is not None and (points.needs_read or points.needs_listen)
    whole = known is not None and known.complete
    if whole and not wants_facts:
        return {"status": STATUS_READY, "seconds": known.seconds, "duration": known.duration_seconds,
                "tracks": len(known.tracks), "origin": known.origin}
    streams, duration = voice_track.probe_audio_streams(ffprobe, source)
    ordinals = list(range(min(len(streams), MAX_TRACKS)))
    if not ordinals:
        return {"status": STATUS_NO_AUDIO, "seconds": 0, "duration": duration}
    levels = known if known is not None and (known.origin == "measured" or whole) else Levels(duration_seconds=duration)
    if not whole:
        levels.duration_seconds = duration
        levels.origin = "measured"
    # A part saved earlier is kept to the whole second all its tracks reached.
    start = min((len(levels.tracks.get(ordinal + 1, [])) for ordinal in ordinals), default=0)
    if not whole:
        levels.tracks = {ordinal + 1: list(levels.tracks.get(ordinal + 1, []))[:start] for ordinal in ordinals}
    frames: _Frames | None = None
    if wants_facts:
        frames = _Frames(cache, source, before, ordinals)
        if not fresh:
            frames.resume()
        start = frames.seconds if whole else min(start, frames.seconds)
    control = _Control(control_path, source)
    saved = [time.monotonic()]
    told = [0.0]
    sent = [start]

    def tell(final: bool = False) -> None:
        if report is None:
            return
        if whole:
            # Only the speech facts are being read: the lanes have their levels, and keep them.
            if final or time.monotonic() - told[0] >= PROGRESS_SECONDS:
                told[0] = time.monotonic()
                report({"reading_for_speech": frames.seconds if frames is not None else 0, "duration": duration})
            return
        reached = levels.seconds
        if not final and time.monotonic() - told[0] < PROGRESS_SECONDS:
            return
        told[0] = time.monotonic()
        report({"seconds": reached, "duration": duration, "first": sent[0],
                "tracks": {str(track): values[sent[0]:reached] for track, values in levels.tracks.items()}})
        sent[0] = reached

    def save_all() -> None:
        if not whole:
            _save(cache, source, before, levels)
        if frames is not None:
            try:
                frames.save()
            except OSError:
                pass

    def got(first: int, found: dict[int, list[float]]) -> None:
        if not whole:
            for ordinal, values in found.items():
                track = levels.tracks.setdefault(ordinal + 1, [])
                del track[first:]
                track.extend(values)
        tell()
        if time.monotonic() - saved[0] >= CHECKPOINT_SECONDS:
            saved[0] = time.monotonic()
            save_all()

    def got_frames(first: int, found: dict[int, list[float]], peaks: dict[int, int]) -> None:
        nonlocal frames
        if frames is None:
            return
        try:
            frames.add(first, found, peaks)
        except OSError as exc:
            # A checkpoint that cannot be written only loses the facts of this read, never the waveform.
            print(PROGRESS_PREFIX + json.dumps({"checkpoint_failed": type(exc).__name__}), flush=True)
            frames.close()
            frames = None

    def stop_now() -> bool:
        # What was measured is saved the moment the stop is seen, before FFmpeg is ended: ending it
        # can take a few seconds, and the Workbench may not wait that long.
        if not control.stopped():
            return False
        if not saved_on_stop[0]:
            saved_on_stop[0] = True
            save_all()
        return True

    saved_on_stop = [False]
    work = Path(work_dir) if work_dir is not None else scratch_root() / f"media_manglers_track_levels_{os.getpid()}"
    try:
        # A checkpoint that was finished only waits for its listening: nothing is read again.
        if frames is not None and frames.complete and whole:
            stopped = False
        else:
            _seconds, stopped = voice_track.stream_levels(
                ffmpeg, source, ordinals, work, on_seconds=got, start_second=start,
                paused=control.paused, stopped=stop_now, stall_seconds=stall_seconds, duration=duration,
                on_frames=got_frames if frames is not None else None)
    except Exception:
        if not whole and levels.seconds > start:
            _save(cache, source, before, levels)
        if frames is not None:
            frames.close()
        _remove(work)
        raise
    tell(final=True)
    after = _stat(source)
    if after is None or after.st_size != before.st_size or after.st_mtime_ns != before.st_mtime_ns:
        if frames is not None:
            frames.remove()
        _remove(work)
        return {"status": STATUS_CHANGED, "seconds": levels.seconds, "duration": duration}
    if not whole:
        levels.complete = not stopped
        _save(cache, source, before, levels)
    told_facts = ""
    try:
        if frames is not None:
            if stopped:
                frames.save()
                frames.close()
            else:
                frames.save(complete=True)
                told_facts = _store_facts(source, frames, streams, duration, ffmpeg=ffmpeg, facts=facts or {},
                                          stopped=control.stopped, work=work)
                frames.close()
                stopped = told_facts == "stopped"
    except OSError:
        told_facts = "not_stored"
    _remove(work)
    if levels.complete:
        app_cache.enforce_cap(cache, cap_bytes)
    return {"status": STATUS_STOPPED if stopped else STATUS_READY, "seconds": levels.seconds,
            "duration": duration, "tracks": len(levels.tracks), "origin": levels.origin or "measured",
            **({"facts": told_facts} if told_facts else {})}


def _remove(folder: Path) -> None:
    try:
        for child in Path(folder).iterdir():
            child.unlink(missing_ok=True)
        Path(folder).rmdir()
    except OSError:
        pass


def _print_progress(event: dict[str, Any]) -> None:
    print(PROGRESS_PREFIX + json.dumps(event, separators=(",", ":")), flush=True)


def measure_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """The ``track-levels`` helper: measure the listed recordings one after another, at low priority."""

    raw_bin_library.below_normal_priority()
    cache = app_cache.cache_root(str(payload.get("cache_folder") or ""))
    folders = [str(item) for item in payload.get("recordings_folders") or []] or None
    fresh = {os.path.normcase(str(item)) for item in payload.get("fresh_paths") or []}
    # The Workbench gives a work folder inside its own build folder, so closing it removes both.
    work = Path(str(payload["work_dir"])) if payload.get("work_dir") else None
    results = []
    for value in payload.get("paths") or []:
        path = Path(str(value))
        print(PROGRESS_PREFIX + json.dumps({"path": str(path), "starting": True}), flush=True)
        try:
            outcome = measure(
                path, ffmpeg=str(payload.get("ffmpeg") or "ffmpeg"), ffprobe=str(payload.get("ffprobe") or "ffprobe"),
                cache=cache, cap_bytes=int(payload.get("cache_cap_bytes") or app_cache.DEFAULT_CAP_BYTES),
                control_path=str(payload.get("run_control_path") or ""), recordings_folders=folders,
                report=lambda event, where=str(path): _print_progress({"path": where, **event}),
                work_dir=work, fresh=os.path.normcase(str(path)) in fresh,
                facts=payload.get("facts") if isinstance(payload.get("facts"), dict) else None)
        except Exception as exc:  # noqa: BLE001 - one recording never stops the others
            outcome = {"status": "failed", "error": str(exc)[:300]}
        results.append({"path": str(path), **outcome})
        print(PROGRESS_PREFIX + json.dumps({"path": str(path), "done": outcome.get("status")}), flush=True)
        if outcome.get("status") == STATUS_STOPPED:
            break
    return {"results": results}
