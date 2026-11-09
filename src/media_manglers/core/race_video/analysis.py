"""Watching the race, locally and for free (150 Phase 2).

Built once per project and reused by every version, the analysis turns a long recording into a
short written digest plus a few contact sheets, so the AI editor reads text first and looks only
at the pictures that matter. Everything here runs on the operator's PC with FFmpeg; nothing calls
an AI service.

- Loudness per second for every audio track, from the shared one-read decode (226): the same
  levels every feature measures.
- Moments where the game sound jumps (often contact, a crash or a spin) and where the driver talks
  (the shared voice activity of the narration track).
- Dead time (217, 226): stretches where nobody is driving, found by the game sound staying quiet
  (signal 1) or the game picture standing still (signal 2, read in the same pass as the sound).
- Stills sampled by seeking at the budget's interval (some recorders write a keyframe every
  quarter-second, which makes "every keyframe" impractically slow), blurred through the operator's
  privacy masks before anything else sees them, by the shared frame renderer. Each budget caps the
  contact sheets; a long recording gets stills further apart rather than more sheets. When the masks
  or the spacing change, every still is taken again.
- Contact sheets of the story panel, labelled with times, and sharp picture changes between stills.
- A text digest (``digest.md``) and the same data as JSON (``analysis.json``), led by a warning when
  the voice or game track has no sound for the whole recording (226).

On a long race the slow parts (reading the recording, taking the stills, making the sheets) report
how far they have got as they go (175), so the Workbench shows progress rather than a silence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import tempfile
import time
from typing import Any, Callable

from .. import activity_timeline, frame_render, voice_track
from ..activity_timeline import spans
from ..scratch import scratch_root
from .privacy import build_full_frame_mask, fingerprint
from .project import record_usage, write_atomic, write_json_atomic
from .timeline import DEFAULT_LAYOUT

ANALYSIS_SCHEMA = "mm-race-video-analysis-v1"
BUDGETS: dict[str, dict[str, Any]] = {
    "light": {"still_interval": 15, "max_sheets": 6, "review_rounds": 1, "close_look_images": 4},
    "standard": {"still_interval": 10, "max_sheets": 12, "review_rounds": 2, "close_look_images": 10},
    "thorough": {"still_interval": 5, "max_sheets": 24, "review_rounds": 3, "close_look_images": 25},
}
STILL_WIDTH = 1920
STILL_WORKERS = 4        # stills taken at a time, each its own short seek
PROGRESS_EVERY = 2.0     # seconds between progress reports from one step
ProgressReport = Callable[[str, int, int], None]   # what is happening, how much is done, of how much
SHEET_COLUMNS, SHEET_ROWS = frame_render.SHEET_COLUMNS, frame_render.SHEET_ROWS
TILE_W, TILE_H = frame_render.TILE_W, frame_render.TILE_H
# Prepare's and the analysis's own work folders under the scratch folder (226), removed when done.
SCRATCH_PREFIX = "media_manglers_race_video_"
# Beside the narration transcript: what it was written with (226), so Prepare redoes it only when
# that changes.
NARRATION_STAMP_NAME = "narration.stamp.json"
# Bump when the analysis's own rules change (levels, talk, spikes, dead time), so a stored analysis is
# worked out again; its stills are kept when only this changes. 2: the digest warns of a voice or game
# track with no sound, and the dead-time note no longer names an estimate it did not use.
ANALYSIS_RULES_VERSION = 2
# Talk: speech moments closer than this are one stretch, and a stretch shorter than this is left out.
TALK_GAP_SECONDS = 3
TALK_SHORTEST_SECONDS = 2
# Sharp picture changes between consecutive stills: the mean difference of their 32x18 gray pictures.
PICTURE_CHANGE_THRESHOLD = 40.0
# What neither dead-time signal can see, said wherever dead time is shown (226).
CANNOT_TELL = ("Neither signal can tell a replay, another car's camera or a moving menu from driving: "
               "to the game sound and the game picture they look like racing, so dead time there is not listed.")


def still_interval(duration: float, budget: str) -> int:
    """Seconds between stills: the budget's usual spacing, widened so the sheets stay within its cap."""

    allowance = max(1, int(BUDGETS[budget]["max_sheets"] * SHEET_COLUMNS * SHEET_ROWS))
    return max(int(BUDGETS[budget]["still_interval"]), math.ceil(int(duration) / allowance))


# 226: the one shared clock, under the name the editor's modules import.
clock = voice_track.clock


# The one read of the recording (226) ------------------------------------------------------------


@dataclass
class PictureSamples:
    """The game picture's samples from the one read (217 signal 2), or why there are none."""

    times: list[float] = field(default_factory=list)
    frames: list[bytes] = field(default_factory=list, repr=False)
    region: str = ""          # the part of the picture measured: "center panel" or "whole frame"
    problem: str = ""         # why the game picture could not be measured, when it could not
    keyframe_spacing: float | None = None


@dataclass
class RecordingRead:
    """What one read of the recording gave (226): every audio track decoded to a 16 kHz WAV (``wavs``,
    by 0-based ordinal, in a scratch folder the caller owns), each track's activity and level per
    second, and the game picture's samples."""

    streams: list[dict[str, Any]]
    duration: float
    video: dict[str, Any]
    wavs: dict[int, Path]
    activities: dict[int, Any]
    picture: PictureSamples
    reads: int = 1            # full reads of the recording it took (2 when the combined read failed)

    @property
    def levels(self) -> dict[int, list[float]]:
        return {ordinal: list(item.second_levels or []) for ordinal, item in sorted(self.activities.items())}

    @property
    def titles(self) -> dict[int, str]:
        return {index: str((stream.get("tags") or {}).get("title") or "") for index, stream in enumerate(self.streams)}

    def keep_only(self, ordinals: set[int] | list[int]) -> None:
        """Delete the decoded audio of every other track at once (a long race's WAVs are large)."""

        wanted = {int(value) for value in ordinals}
        for ordinal in [ordinal for ordinal in self.wavs if ordinal not in wanted]:
            Path(self.wavs.pop(ordinal)).unlink(missing_ok=True)


def _clause(text: Any) -> str:
    return str(text or "").strip().rstrip(".").strip()


def read_recording(ffmpeg: str, source: Path, streams: list[dict[str, Any]], duration: float,
                   video: dict[str, Any], work: Path, *, story_panel: str = "center",
                   masked_panels: list[str] | tuple[str, ...] = (),
                   on_progress: ProgressReport | None = None) -> RecordingRead:
    """Read the recording once (226): every audio track to its own 16 kHz WAV under ``work`` and, in
    the same FFmpeg run, the game picture's keyframes, shrunk to 64x36 gray (signal 2 of 217). Then
    each track's activity and level per second, by the shared rules.

    The game picture is the story panel of a 5760x1080 recording (never a camera panel; never a panel
    with a privacy mask) or the whole frame of any other size (``frame_render.picture_region``). When the
    combined read fails, the sound is read again on its own and the picture is marked not measured,
    with the reason; so it is when the keyframes are too far apart to measure. ``on_progress`` hears
    "Reading the recording: mm:ss of mm:ss" with seconds read, then each track being measured.
    """

    work.mkdir(parents=True, exist_ok=True)
    length = max(1, int(duration))
    total = clock(duration)

    def moved(seconds: float) -> None:
        if on_progress is not None:
            on_progress(f"Reading the recording: {clock(seconds)} of {total}", min(length, int(seconds)), length)

    if on_progress is not None:
        on_progress(f"Reading the recording: {clock(0)} of {total}", 0, length)
    picture = PictureSamples()
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    found = frame_render.picture_region(width, height, game_panel=story_panel, masked_panels=list(masked_panels))
    wavs: dict[int, Path] | None = None
    reads = 0
    if found is None:
        picture.problem = ("the recording has no picture to measure" if width <= 0 or height <= 0 else
                           f"the {story_panel} panel has a privacy mask, so its picture is never measured")
    else:
        box, picture.region = found
        frames_path, times_path = work / "picture-samples.raw", work / "picture-sample-times.txt"
        try:
            reads += 1
            wavs = voice_track.extract_all_tracks(
                ffmpeg, source, len(streams), work / "tracks", duration_seconds=duration, on_progress=moved,
                input_options=frame_render.picture_input_options(),
                extra_outputs=frame_render.picture_output(box, frames_path, times_path))
            try:
                picture.times, picture.frames = frame_render.read_picture_samples(frames_path, times_path)
            except RuntimeError as exc:
                picture.problem = f"the game picture's samples could not be read ({_clause(exc)})"
        except RuntimeError as exc:
            wavs = None
            # FFmpeg's last line says what went wrong without the folders it names before it.
            lines = [line.strip() for line in str(exc).replace("ffmpeg could not decode the audio tracks: ", "").splitlines()
                     if line.strip()]
            why = _clause(lines[-1] if lines else "") or "FFmpeg stopped"
            picture.problem = f"the game picture could not be read in the same pass as the sound ({why})"
        finally:
            frames_path.unlink(missing_ok=True)
            times_path.unlink(missing_ok=True)
        if not picture.problem:
            ordered = sorted(picture.times)
            gaps = [later - earlier for earlier, later in zip(ordered, ordered[1:])]
            picture.keyframe_spacing = round(statistics.median(gaps), 3) if gaps else None
            if picture.keyframe_spacing is None:
                picture.problem = "the recording's picture has fewer than two keyframes to compare"
            elif picture.keyframe_spacing > activity_timeline.PICTURE_MAX_GAP_SECONDS:
                picture.problem = (f"the recording's keyframes are {picture.keyframe_spacing:.0f} s apart, more than "
                                   f"the {activity_timeline.PICTURE_MAX_GAP_SECONDS:.0f} s the picture check can measure")
        if picture.problem:
            picture.times, picture.frames = [], []
    if wavs is None:
        reads += 1
        wavs = (voice_track.extract_all_tracks(ffmpeg, source, len(streams), work / "tracks",
                                               duration_seconds=duration, on_progress=moved)
                if streams else {})
    # FFmpeg's last position is the last picture it wrote (a keyframe), not the end: say the read is done.
    moved(duration)
    activities: dict[int, Any] = {}
    for position, (ordinal, path) in enumerate(sorted(wavs.items()), start=1):
        if on_progress is not None:
            on_progress(f"Measuring the sound of Track {ordinal + 1} ({position} of {len(wavs)})", position - 1,
                        len(wavs))
        activities[ordinal] = voice_track.analyze_track_wav(path, ordinal)
    return RecordingRead(streams=list(streams), duration=float(duration), video=dict(video), wavs=dict(wavs),
                         activities=activities, picture=picture, reads=reads)


def _read_alone(ffmpeg: str, ffprobe: str, source: Path, story_panel: str, masks: dict[str, Path],
                report: ProgressReport | None) -> RecordingRead:
    """The one read for an analysis made on its own (the ``race-video-analyze`` command), not from
    Prepare: the same decode, in a scratch folder that is removed at once (only levels are kept)."""

    streams, duration = voice_track.probe_audio_streams(ffprobe, source)
    video = frame_render.probe_video(ffprobe, source)
    work = Path(tempfile.mkdtemp(prefix=f"{SCRATCH_PREFIX}{os.getpid()}_", dir=str(scratch_root())))
    try:
        return read_recording(ffmpeg, source, streams, duration, video, work, story_panel=story_panel,
                              masked_panels=sorted(masks), on_progress=report)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# What the analysis finds ----------------------------------------------------------------------


def sound_spikes(levels: list[float], window: int = 30, jump_db: float = 9.0, floor_db: float = -35.0) -> list[dict[str, Any]]:
    """Seconds where a track is much louder than its surroundings: often contact, a crash or a spin.
    Editing analysis, not a shared job; it reads the shared levels (226)."""

    flags = []
    for second, level in enumerate(levels):
        around = levels[max(0, second - window):second + window + 1]
        baseline = statistics.median(around)
        flags.append(level >= floor_db and level - baseline >= jump_db)
    events = []
    for start, end in spans(flags, gap=3):
        peak = max(range(start, end), key=lambda s: levels[s])
        events.append({"start": start, "end": end, "peak_db": levels[peak]})
    return events


def voice_talk(activity: Any) -> tuple[list[dict[str, int]], float | None]:
    """When the driver talks, from the narration track's shared voice activity (226): its speech
    moments joined into stretches (``activity_timeline.speech_stretches``), in whole seconds, and the
    level their microphone counts as talking above, for cut points (176). None for the level when the
    track has no sound."""

    if activity is None:
        return [], None
    stretches = activity_timeline.speech_stretches(activity.intervals, gap=TALK_GAP_SECONDS,
                                                   shortest=TALK_SHORTEST_SECONDS)
    talking = [{"start": int(math.floor(start)), "end": int(math.ceil(end))} for start, end in stretches]
    if activity.peak_dbfs < voice_track.SILENT_PEAK_DBFS:
        return talking, None
    threshold = voice_track.active_threshold_dbfs(float(activity.noise_floor_dbfs))
    return talking, round(threshold, 1)


def picture_changes(ffmpeg: str, stills: Path, count: int, crop: tuple[int, int, int, int],
                    times: list[float], threshold: float = PICTURE_CHANGE_THRESHOLD) -> list[dict[str, Any]]:
    """Consecutive stills of the story panel that differ sharply (a replay starting, a spin, a new screen).
    Scored by the one picture-difference measure signal 2 uses (226); the stills are read through the
    frame renderer, and a read that fails raises with FFmpeg's reason instead of finding nothing."""

    if count < 2:
        return []
    frames = frame_render.gray_tiles(ffmpeg, stills, count, crop)
    changes = []
    for i in range(1, len(frames)):
        diff = activity_timeline.mean_abs_difference(frames[i], frames[i - 1])
        if diff >= threshold:
            changes.append({"at": round(times[i], 1), "difference": round(diff, 1)})
    return changes


_SILENT_WORDS = {"voice": ("your voice", "your voice track"), "game": ("your game sound", "the game track")}


def silent_track_warnings(tracks: dict[str, Any] | None, levels: dict[int, list[float]]) -> list[str]:
    """A plain warning for the voice or game track Prepare uses when it is silent for the whole
    recording (226), by the rule the dead time uses for that (``activity_timeline.is_silent`` on the
    read's levels per second; a steady engine noise is sound), saying what to check: the Narration track
    setting or the track's name when one of those chose it, else another track on the page. The choice
    itself stands (220)."""

    warnings: list[str] = []
    for name, (words, which) in _SILENT_WORDS.items():
        ordinal = _ordinal(tracks, name)
        if ordinal is None or ordinal not in levels or not activity_timeline.is_silent(levels[ordinal]):
            continue
        decided = str((tracks or {}).get(f"{name}_decided_by") or "")
        if decided == voice_track.DECIDED_BY_SETTING:
            advice = f"check your Narration track setting or choose {which} on the page"
        elif decided == voice_track.DECIDED_BY_NAME:
            advice = f"check the track's name in OBS or choose {which} on the page"
        else:
            advice = f"choose another track as {words} on the page"
        warnings.append(f"Track {ordinal + 1}, {words}, is silent for the whole recording; {advice}.")
    return warnings


def dead_time(recording: RecordingRead, *, voice: int | None, game: int | None, game_decided_by: str = "",
              track_roles: Any = None) -> activity_timeline.ActivityTimeline:
    """Dead time from both signals (217, 226). Signal 1, the game sound quiet, is the raw bin's: from
    the game track's levels, estimated from the full mix when the game track named by its name or the
    Track roles (or chosen on the page) is silent the whole recording. Signal 2, the game picture still,
    from the picture samples of the same read; not measured, with the reason, when the picture could
    not be read or its keyframes are too far apart."""

    duration = recording.duration
    if game is None:
        sound = activity_timeline.unknown("No game-audio track was chosen for this recording.", duration)
    else:
        from ..raw_bin_library import idle_from_levels  # noqa: PLC0415 - the raw bin's own rules, imported when used

        decided_by = voice_track.DECIDED_BY_SETTING if game_decided_by == "override" else str(game_decided_by or "")
        sound = idle_from_levels(recording.titles, recording.levels, duration, game=int(game), decided_by=decided_by,
                                 reason="", setting_value=voice_track.roles_from_text(track_roles),
                                 narration=None if voice is None else int(voice))
    samples = recording.picture
    if samples.problem:
        problem = _clause(samples.problem)
        picture = activity_timeline.unknown(f"{problem[:1].upper()}{problem[1:]}.", duration)
        picture.region = samples.region
    else:
        changes, luma = activity_timeline.picture_change_per_second(samples.times, samples.frames, duration=duration)
        picture = activity_timeline.game_picture_timeline(changes, luma=luma, region=samples.region)
    return activity_timeline.combined_timeline(sound, picture)


class _Throttle:
    """Passes a progress report on at most every ``PROGRESS_EVERY`` seconds, and always the last one."""

    def __init__(self, report: ProgressReport | None) -> None:
        self.report = report
        self.last = 0.0

    def __call__(self, activity: str, done: int, total: int) -> None:
        now = time.monotonic()
        if self.report and (done >= total or now - self.last >= PROGRESS_EVERY):
            self.last = now
            self.report(activity, done, total)


def _segments(transcript: Path | None) -> list[dict[str, Any]]:
    if not transcript or not transcript.exists():
        return []
    data = json.loads(transcript.read_text(encoding="utf-8"))
    return [{"start": round(float(s["start"]), 1), "end": round(float(s["end"]), 1), "text": str(s["text"]).strip()}
            for s in data.get("segments") or [] if str(s.get("text", "")).strip()]


def file_sha256(path: Path | None) -> str:
    """The SHA-256 of a file's bytes, or "" when there is no file."""

    if not path or not Path(path).is_file():
        return ""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read_stamp(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def engine_of(tracks: dict[str, Any] | None, transcript: Path | None, game_speech: Path | None,
              content: str = "") -> dict[str, Any]:
    """Everything an analysis depends on apart from its stills (226): the analysis rules, the shared
    levels and activity rules, the tracks, and what the transcript and the game-track voices were made
    with (their stamps) and contain (their SHA-256). 242 (Wave C2): for a bound project, also the
    recording's content (its full hash)."""

    tracks = dict(tracks or {})
    narration_stamp = _read_stamp(transcript.parent / NARRATION_STAMP_NAME) if transcript else None
    heard = _read_stamp(game_speech) if game_speech else None
    found = {"content": content} if content else {}
    return {
        **found,
        "rules": ANALYSIS_RULES_VERSION,
        "levels": "voice_track.analyze_track_wav second_levels (16 kHz mono)",
        "activity": {"game_audio": activity_timeline.GAME_AUDIO_RULE_VERSION,
                     "game_picture": activity_timeline.GAME_PICTURE_RULE_VERSION,
                     "combined": activity_timeline.COMBINED_RULE_VERSION},
        "tracks": {key: tracks.get(key) for key in ("voice", "game", "voice_decided_by", "game_decided_by")
                   if key in tracks},
        "transcript": {"stamp": narration_stamp, "sha256": file_sha256(transcript)},
        "game_speech": {"stamp": (heard or {}).get("stamp"), "sha256": file_sha256(game_speech)},
    }


def _project_content(project: Path) -> str:
    """The full hash the project is bound to, "" when it is not (242, Wave C2)."""

    meta = _read_stamp(project / "project.json") or {}
    found = meta.get("recording")
    return str(found.get("content_sha256") or "") if isinstance(found, dict) else ""


def _binding_agrees(project: Path) -> bool:
    """Whether the project's binding and its older fingerprint describe the same file (its size and its whole
    second of modification), so an analysis made before the project was bound was made from that recording."""

    meta = _read_stamp(project / "project.json") or {}
    found, old = meta.get("recording"), meta.get("source_fingerprint")
    if not isinstance(found, dict) or not isinstance(old, dict):
        return False
    try:
        return (int(found.get("size") or -1) == int(old.get("size") or -2)
                and int(found.get("modified_ns") or 0) // 1_000_000_000 == int(old.get("modified") or -1))
    except (TypeError, ValueError):
        return False


def _same_engine(project: Path, existing: dict[str, Any], engine: dict[str, Any]) -> bool:
    """The stored analysis was made by this engine. 242 (Wave C2): an analysis made before its project was bound
    has no content; it still matches while the project's binding and old fingerprint agree, so binding a project
    never rebuilds its analysis."""

    stored = existing.get("engine")
    if stored == engine:
        return True
    if not isinstance(stored, dict) or "content" in stored or "content" not in engine:
        return False
    return stored == {key: value for key, value in engine.items() if key != "content"} and _binding_agrees(project)


def _same_pictures(existing: dict[str, Any], settings: dict[str, Any]) -> bool:
    """The stored analysis's stills were taken with these settings. An analysis written before Wave 7
    kept more in its settings; only what the stills depend on counts (226)."""

    stored = existing.get("settings") or {}
    return all(stored.get(key) == value for key, value in settings.items())


def _pictures_on_disk(folder: Path, existing: dict[str, Any], count: int) -> bool:
    if int(existing.get("stills") or -1) != count or not isinstance(existing.get("sheets"), list):
        return False
    stills = all((folder / "stills" / f"s{index:05d}.jpg").is_file() for index in range(count))
    return stills and all((folder / "sheets" / str(sheet.get("file") or "")).is_file() for sheet in existing["sheets"])


def _settings_of(budget: str, story_panel: str, layout: dict[str, Any], masks: dict[str, Path]) -> dict[str, Any]:
    """What the stills and contact sheets depend on."""

    return {"budget": budget, "story_panel": story_panel, "layout": layout, "masks": fingerprint(masks)}


def analysis_is_current(project: Path, *, budget: str = "standard", tracks: dict[str, Any] | None = None,
                        layout: dict[str, Any] | None = None, story_panel: str = "center",
                        masks: dict[str, Path] | None = None, transcript: Path | None = None,
                        game_speech: Path | None = None) -> bool:
    """True when ``analyze`` with these would hand back the stored analysis as it is: the same stills
    settings and the same engine (226). Prepare then has no need to read the recording."""

    index = project / "analysis" / "analysis.json"
    existing = _read_stamp(index) if index.exists() else None
    if existing is None:
        return False
    settings = _settings_of(budget, story_panel, layout or DEFAULT_LAYOUT, masks or {})
    return _same_pictures(existing, settings) and _same_engine(
        project, existing, engine_of(tracks, transcript, game_speech, _project_content(project)))


def _ordinal(tracks: dict[str, Any] | None, name: str) -> int | None:
    value = (tracks or {}).get(name)
    return int(value) if isinstance(value, int) or (isinstance(value, str) and value.strip().isdigit()) else None


def analyze(project: Path, source: Path, *, budget: str = "standard", tracks: dict[str, Any] | None = None,
            layout: dict[str, Any] | None = None, story_panel: str = "center", masks: dict[str, Path] | None = None,
            transcript: Path | None = None, game_speech: Path | None = None,
            ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe",
            on_progress: ProgressReport | None = None, recording: RecordingRead | None = None,
            track_roles: Any = None) -> dict[str, Any]:
    """Build (or reuse) the project's analysis. Returns the analysis data.

    ``on_progress`` hears what is happening and how far it has got, a few times a minute (175).

    226: ``recording`` is Prepare's one read of the recording (levels, activities, picture samples);
    without it (the ``race-video-analyze`` command) the recording is read here, through the same shared
    decode. ``tracks`` may also say what decided the game track (``game_decided_by``), and
    ``track_roles`` is the Track roles setting: a game track named or set in it that is silent the
    whole recording has its dead time estimated from the full mix, as the raw bin does.

    Reuse: with the same stills settings (budget, story panel, layout, masks) and the same engine
    (``engine_of``), the stored analysis is returned as it is. When only the engine differs, everything
    but the stills and contact sheets is worked out again; the sheets are kept and not counted again.
    """

    if budget not in BUDGETS:
        raise ValueError(f"budget must be one of {sorted(BUDGETS)}")
    folder = project / "analysis"
    index = folder / "analysis.json"
    layout = layout or DEFAULT_LAYOUT
    masks = masks or {}
    settings = _settings_of(budget, story_panel, layout, masks)
    engine = engine_of(tracks, transcript, game_speech, _project_content(project))
    existing = _read_stamp(index) if index.exists() else None
    same_pictures = existing is not None and _same_pictures(existing, settings)
    if same_pictures and _same_engine(project, existing, engine):
        return existing
    report = _Throttle(on_progress)
    if not same_pictures:
        # Pictures from an earlier analysis may be unmasked, masked differently or taken at another
        # spacing: none of them may be reused.
        for stale in ("stills", "sheets"):
            shutil.rmtree(folder / stale, ignore_errors=True)
    if recording is None:
        recording = _read_alone(ffmpeg, ffprobe, source, story_panel, masks, report)
    duration = recording.duration
    interval = still_interval(duration, budget)
    times = [float(t) for t in range(0, int(duration), interval)]
    keep_pictures = same_pictures and _pictures_on_disk(folder, existing, len(times))
    if same_pictures and not keep_pictures:
        for stale in ("stills", "sheets"):
            shutil.rmtree(folder / stale, ignore_errors=True)

    levels = recording.levels
    voice, game = _ordinal(tracks, "voice"), _ordinal(tracks, "game")
    roles = {ordinal: role for role, ordinal in (("voice", voice), ("game", game)) if ordinal is not None}
    titles = recording.titles
    track_rows = []
    for ordinal in range(len(recording.streams)):
        values = levels.get(ordinal, [])
        audible = [v for v in values if v > -90]
        track_rows.append({
            "ordinal": ordinal, "track": ordinal + 1, "title": titles.get(ordinal, ""),
            "role": roles.get(ordinal, "unknown"),
            "median_db": round(statistics.median(audible), 1) if audible else None,
            "audible_share": round(len(audible) / len(values), 2) if values else 0.0,
        })
    spikes = sound_spikes(levels[game]) if game is not None and levels.get(game) else []
    talking, talk_threshold_dbfs = voice_talk(recording.activities.get(voice) if voice is not None else None)
    warnings = silent_track_warnings(tracks, levels)
    timeline = dead_time(recording, voice=voice, game=game,
                         game_decided_by=str((tracks or {}).get("game_decided_by") or ""), track_roles=track_roles)
    activity = {**timeline.to_dict(), "cannot_tell": CANNOT_TELL}
    write_json_atomic(folder / "activity.json", activity)

    height = int(round(STILL_WIDTH * layout["height"] / layout["width"] / 2) * 2)
    stills_dir = folder / "stills"
    sx = STILL_WIDTH / layout["width"]
    px, py, pw, ph = (int(v) for v in layout["panels"][story_panel])
    crop = (round(px * sx), round(py * sx), round(pw * sx) // 2 * 2, round(ph * sx) // 2 * 2)
    if keep_pictures:
        sheets = list(existing["sheets"])
        masked = bool(existing.get("privacy_masked"))
    else:
        mask = build_full_frame_mask(ffmpeg, layout, masks, folder / "privacy-mask.png", STILL_WIDTH, height) if masks else None
        frame_render.render_stills(ffmpeg, source, times, stills_dir, scale=(STILL_WIDTH, height), mask=mask,
                                   workers=STILL_WORKERS, reuse=False,
                                   on_progress=lambda done, total: report(f"Taking stills: {done} of {total}", done, total))
        sheets = frame_render.contact_sheets(
            ffmpeg, stills_dir, len(times), 0.0, interval, crop, folder / "sheets",
            on_progress=lambda done, total: report(f"Making contact sheets: {done} of {total}", done, total))
        masked = bool(mask)
    report("Looking for sharp picture changes", 0, 1)
    changes = picture_changes(ffmpeg, stills_dir, len(times), crop, times)
    segments = _segments(transcript)
    voices: list[dict[str, Any]] | None = None
    left_out = 0
    if game_speech and game_speech.exists():
        heard = json.loads(game_speech.read_text(encoding="utf-8"))
        voices = heard.get("segments") or []
        left_out = len(heard.get("left_out") or [])

    data = {
        "schema": ANALYSIS_SCHEMA,
        "settings": settings,
        "engine": engine,
        "source": str(source),
        "duration": round(duration, 1),
        "layout": layout,
        "still_interval": interval,
        "budget_interval": BUDGETS[budget]["still_interval"],
        "max_sheets": BUDGETS[budget]["max_sheets"],
        "stills": len(times),
        "privacy_masked": masked,
        # 226: a voice or game track with no sound for the whole recording, said first in the digest.
        "warnings": warnings,
        "tracks": track_rows,
        # 0-based track numbers as text: review.py and older projects look the voice track up by them.
        "loudness_per_second": {str(k): v for k, v in levels.items()},
        "voice_talk_threshold_dbfs": talk_threshold_dbfs,
        "talking": talking,
        "game_sound_spikes": spikes,
        "picture_changes": changes,
        "activity": activity,
        "sheets": sheets,
        "transcript": segments,
        # 172: other people's voices on the game track; None when the game track was not listened to.
        "game_speech": voices,
        "game_speech_left_out": left_out,
    }
    write_json_atomic(index, data)
    write_atomic(folder / "digest.md", digest(data))
    if not keep_pictures:
        record_usage(project, "contact sheets prepared for the AI editor", len(sheets),
                     note=f"{budget} budget, a still every {interval} s of the {sheets and sheets[0]['tiles']}-tile sheets")
    return json.loads(json.dumps(data, ensure_ascii=False))


def _length(seconds: float) -> str:
    minutes, rest = divmod(max(0, int(seconds)), 60)
    return f"{minutes} min {rest} s"


def _dead_time_lines(activity: dict[str, Any] | None) -> list[str]:
    """The digest's dead-time section (226): each stretch, with what found it."""

    lines = ["## Dead time (no driving found)", ""]
    if not activity:
        return [*lines, "- not measured: this analysis was made before dead time was looked for", ""]
    if activity.get("status") == activity_timeline.STATUS_UNKNOWN:
        lines.append(f"- not measured: {_clause(activity.get('reason')) or 'neither the game sound nor the game picture could be measured'}")
    else:
        stretches = activity.get("idle_stretches") or []
        found_by = activity.get("idle_by") or []
        kinds = activity.get("picture_kinds") or []
        for position, (start, end) in enumerate(stretches):
            by = set(found_by[position]) if position < len(found_by) else {activity_timeline.SIGNAL_GAME_AUDIO}
            picture = "black" if (kinds[position] if position < len(kinds) else "") == activity_timeline.PICTURE_BLACK else "still"
            if activity_timeline.SIGNAL_GAME_PICTURE in by and activity_timeline.SIGNAL_GAME_AUDIO in by:
                what = f"game picture {picture} and game sound quiet"
            elif activity_timeline.SIGNAL_GAME_PICTURE in by:
                what = f"game picture {picture} while the game sound goes on (often the pits, a repair or the grid)"
            else:
                what = "game sound quiet"
            lines.append(f"- {clock(start)}-{clock(end)} ({_length(end - start)}): {what}")
        if not stretches:
            lines.append("- none found")
        if activity.get("reason"):
            lines.append(f"- note: {_clause(activity['reason'])}.")
    lines += ["", str(activity.get("cannot_tell") or CANNOT_TELL),
              "Cut dead time unless it serves the story.", ""]
    return lines


def digest(data: dict[str, Any]) -> str:
    """The short written summary the AI editor reads first."""

    spacing = f"one every {data['still_interval']} s"
    usual = data.get("budget_interval", data["still_interval"])
    if data["still_interval"] > usual:
        spacing += (f" (widened from {usual} s to stay within the {data['settings']['budget']} budget's "
                    f"{data['max_sheets']} contact sheets)")
    masks = "yes" if data["privacy_masked"] else "no masks set, so the camera panels are not blurred"
    lines = [f"# Race analysis: {Path(data['source']).name}", ""]
    for warning in data.get("warnings") or []:
        lines += [f"**Warning:** {warning}", ""]
    lines += [
        f"- Length: {clock(data['duration'])}. Stills: {spacing} "
        f"({data['stills']}), privacy masks applied: {masks}.",
        f"- Budget: {data['settings']['budget']}. Look at the contact sheets below before asking for closer looks.",
        "",
        "## Audio tracks",
        "",
        "| Track | Title | Role | Typical level | Audible |",
        "|---|---|---|---|---|",
    ]
    for t in data["tracks"]:
        level = f"{t['median_db']} dB" if t["median_db"] is not None else "silent"
        lines.append(f"| {t['track']} | {t['title'] or '-'} | {t['role']} | {level} | {int(t['audible_share'] * 100)}% |")
    lines += ["", "Only the voice and game tracks are used in an edit. A track marked unknown is never used without the "
              "operator's say-so: a spare track can carry music, which must not be published.", ""]
    lines += ["## Game-sound spikes (often contact, a crash or a spin)", ""]
    lines += [f"- {clock(s['start'])}-{clock(s['end'])} (peak {s['peak_db']} dB)" for s in data["game_sound_spikes"]] or ["- none found"]
    lines += ["", "## Sharp picture changes on the story panel", ""]
    lines += [f"- {clock(c['at'])}" for c in data["picture_changes"]] or ["- none found"]
    lines += [""] + _dead_time_lines(data.get("activity"))
    lines += ["## Contact sheets (story panel)", ""]
    lines += [f"- `analysis/sheets/{s['file']}`: {clock(s['from'])} to {clock(s['to'])}" for s in data["sheets"]]
    lines += ["", "## When the driver talks", ""]
    if data["transcript"]:
        lines += [f"[{clock(s['start'])}] {s['text']}" for s in data["transcript"]]
    else:
        lines += [f"- {clock(s['start'])}-{clock(s['end'])}" for s in data["talking"]] or ["- no speech found"]
        lines += ["", "No transcript was supplied; run `race-video-transcribe` for the words."]
    lines += ["", "## Other voices on the game track (voice chat, spotter, race control)", ""]
    voices = data.get("game_speech")
    if voices is None:
        lines += ["- not listened for: the game track was not transcribed"]
    elif not voices:
        lines += ["- none heard"]
    else:
        lines += ["Not the driver. List these in the sharing check.", ""]
        lines += [f"[{clock(s['start'])}] {s['text']}" for s in voices]
    left_out = int(data.get("game_speech_left_out") or 0)
    if voices is not None and left_out:
        one = left_out == 1
        lines += ["", f"Left out: {left_out} more line{'' if one else 's'} heard on the game track "
                  f"{'was' if one else 'were'} not clearly another voice, so {'it is' if one else 'they are'} not "
                  "listed here and not to be reported. Each is in `analysis/transcript/game.speech.json` under "
                  "\"left_out\", with the reason."]
    return "\n".join(lines) + "\n"
