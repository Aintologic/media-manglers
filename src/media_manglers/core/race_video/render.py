"""Render a timeline version to video with FFmpeg (150).

226 (161, 177, 178): every scene's picture and every scene's sound are rendered on their own from
the untouched recording, into one store per project that all its versions share:

    <project>/scene-cache/<profile>/picture/<key>.mkv   the scene's picture, video only
    <project>/scene-cache/<profile>/sound/<key>.wav     the scene's sound, 48 kHz stereo PCM
    <project>/scene-cache/<profile>/joined/<key>.mp4    the joined picture of a whole edit

Each file has a small ``<key>.json`` beside it saying how it was made. A key is made only of what
changes the file: a scene's picture key does not hold its sound, its id, its beat or its
transitions, so a revision that only changes the sound renders no picture at all (not even the
joined one), and a scene that moved or was renamed is reused. Old per-version ``scenes-*`` folders
are left as they are.

The picture is compressed once: a final's scene pictures are mathematically lossless (NVENC's
lossless mode when it works, else x264 at QP 0), and the join is the one lossy picture encode, at the
export quality chosen. The sound is uncompressed until the loudness step's one AAC encode. Every scene
is a whole number of frames at the render's frame rate and exactly the matching number of samples,
and transitions are whole frames, so picture and sound never drift. The frame rate is the
recording's own, up to 60 (``export_frame_rate``); a preview is half of it from 48 up.

Renders of a project take turns (a lock file per project), and afterwards the store is trimmed to
what the newest versions, the one just rendered and any exported one use (a final's: the newest final
only; an export removes the final's store once the export is placed). After each render a readable
name (``<project>-v003-<editor label>-preview.mp4``) is linked to
the fixed ``renders/preview.mp4`` or ``final.mp4``. The render report (``render-<profile>.json``)
says what really ran: each scene's encoder and decode, what was reused, the frame rate and why, and
the sound lowering that was actually applied.

Privacy: a panel with a mask (white = private) is blurred through it wherever it appears: as its
own view, as an inset, in the full width, inside a crop that reaches into it, or inside another panel
that covers it. Masks belong to the operator's per-user settings; the stored ones are always applied
(226), and the render report says which were.

Every output is written under a temporary name (with the process id) and renamed when complete.

267: a render, and so an export, reads the project's own recording, never the path a version's
timeline names; a timeline naming another recording is refused (``project.version_recording``).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import threading
import time
import uuid
from typing import Any, Callable

from .. import frame_render, whisper_options
# 226: the font for drawn text lives in the one frame renderer; these names stay for the editor's modules.
from ..frame_render import FONT_DIR, font_option as _font  # noqa: F401
from .privacy import build_full_frame_mask, fingerprint, load_masks
from .project import (
    EDITOR_SETTINGS_NAME,
    bound_content,
    export_file,
    read_json,
    replace_durably,
    slug,
    source_fingerprint,
    timeline_refusal,
    version_dir,
    version_entry,
    version_recording,
    write_json_atomic,
)
from .timeline import layout_of, scene_length, validate_timeline

# The size, the frame rate used when the recording's own cannot be read (today's, before 226), and
# the codec settings of each profile. A final's join uses the export quality's settings (QUALITIES).
PROFILES: dict[str, dict[str, Any]] = {
    "preview": {"width": 1280, "height": 720, "fps": 30, "audio_bitrate": "160k",
                "nvenc": ["-preset", "p2", "-rc", "vbr", "-cq", "27", "-b:v", "0"],
                "x264": ["-preset", "veryfast", "-crf", "26"]},
    "final": {"width": 1920, "height": 1080, "fps": 60, "audio_bitrate": "320k",
              "nvenc": ["-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", "19", "-b:v", "16M",
                        "-maxrate", "30M", "-bufsize", "60M", "-profile:v", "high"],
              "x264": ["-preset", "medium", "-crf", "18", "-profile:v", "high"]},
}
LOUDNESS = {"I": -14.0, "TP": -2.0, "LRA": 11.0}
# 170: encoding the sound to AAC can push the true peak up by half a decibel or more after it was
# levelled, so the finished file is measured and, if needed, its sound encoded again a little quieter.
PEAK_CEILING = -1.2   # under the technical check's -1 dBTP limit, with room for measurement noise
PEAK_ATTEMPTS = 3

# Part of every cached scene picture's key: raise it when a change to how scene pictures are built must
# not reuse ones rendered before it (2: full-width and cropped views are masked; 3, 226: a panel over
# another masked camera is masked too; 4, 226: picture only, whole frames, lossless finals).
SCENE_FORMAT = 4
# The same for scene sound files and for joined pictures.
SOUND_FORMAT = 1
JOIN_FORMAT = 1
REPORT_SCHEMA = "mm-race-video-render-v2"

# 226 (161.1): a final's scene pictures are mathematically lossless, so the join is the one lossy
# picture encode; a preview's keep the preview's own settings, for speed.
LOSSLESS = {"nvenc": ["-tune", "lossless"], "x264": ["-preset", "ultrafast", "-qp", "0"]}
PICTURE_FORMATS = {"final": "h264 lossless, yuv420p, video only, mkv",
                   "preview": "h264 at the preview's quality, yuv420p, video only, mkv"}
SOUND_FILE_FORMAT = "pcm_f32le, 48000 Hz, stereo, wav"
SAMPLE_RATE = 48000
SCENE_FADE_SAMPLES = 1920          # 40 ms at the start and end of every scene's sound
FADE_IN_SECONDS, FADE_OUT_SECONDS = 0.8, 1.2   # the whole video's fade in and out (the picture's)
SOUND_FADE_IN_SECONDS = 0.5        # the whole video's sound fades in quicker, as before 226

# 226 (161.5): the export quality. It changes only the final's join (and the final sound's bitrate),
# never the scenes. "youtube" is today's final settings, compressed once. (A keyframe every half second,
# as YouTube's guide suggests, made the file two to four times bigger for no visible gain, so it is
# not used.)
DEFAULT_QUALITY = "youtube"
QUALITIES: dict[str, dict[str, Any]] = {
    "youtube": {"label": "YouTube (recommended)", "nvenc": PROFILES["final"]["nvenc"],
                "x264": PROFILES["final"]["x264"], "audio_bitrate": "320k"},
    "highest": {"label": "Highest quality",
                "nvenc": ["-preset", "p7", "-tune", "hq", "-rc", "vbr", "-cq", "15", "-b:v", "0", "-maxrate", "80M",
                          "-bufsize", "160M", "-profile:v", "high"],
                "x264": ["-preset", "slow", "-crf", "14", "-profile:v", "high"], "audio_bitrate": "320k"},
    "smaller": {"label": "Smaller file",
                "nvenc": ["-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", "23", "-b:v", "8M", "-maxrate", "12M",
                          "-bufsize", "24M", "-profile:v", "high"],
                "x264": ["-preset", "medium", "-crf", "22", "-profile:v", "high"], "audio_bitrate": "192k"},
}
# Where the export quality comes from, in this order: the request, the page's choice for this project
# (``<project>/editor-settings.json``, ``EDITOR_SETTINGS_NAME``), the main setting (Settings > AI Video
# Editor), YouTube.
EXPORT_QUALITY_KEY = "race_video_export_quality"
QUALITY_FROM_REQUEST, QUALITY_FROM_PROJECT = "request", "project"
QUALITY_FROM_MAIN, QUALITY_FROM_DEFAULT = "main_setting", "default"

# 226 (161.2): the frame rate. The recording's rate snaps to the nearest of these within 1%.
STANDARD_RATES = tuple(Fraction(rate) for rate in (
    "24000/1001", "24", "25", "30000/1001", "30", "48", "50", "60000/1001", "60", "90", "100", "120000/1001", "120",
    "144", "165", "240"))
RATE_TOLERANCE = Fraction(1, 100)
EXPORT_RATE_CAP = 60
COUNT_SECONDS = 10.0

# 226: the per-project scene store and its lock.
SCENE_CACHE = "scene-cache"
PICTURE_DIR, SOUND_DIR, JOINED_DIR = "picture", "sound", "joined"
LOCK_NAME = "render.lock"
LOCK_STALE_SECONDS = 6 * 3600       # a lock older than this may be taken over, whoever holds it
LOCK_EMPTY_STALE_SECONDS = 60       # a lock file left empty by a render that stopped while making it
LOCK_RETRY_SECONDS = 2.0
# Only one render at a time takes a stale lock over: it holds this file while it does.
TAKEOVER_NAME = LOCK_NAME + ".takeover"
TAKEOVER_STALE_SECONDS = 60         # one left by a render that stopped while taking over
# A process that started this much later than the lock was written is not the one that wrote it.
PROCESS_START_TOLERANCE = 2.0
NEWEST_PREVIEWS_KEPT = 3
KEY_LENGTH = 32
# A long step says how far it has got at least this often (the Workbench warns after 30 s of silence).
PROGRESS_REPEAT_SECONDS = 5.0
# A readable name longer than this leaves the label out (Windows paths stop at 260 characters).
READABLE_PATH_LIMIT = 240

_CUDA_FAILED = re.compile(r"Failed setup for format cuda")


@dataclass
class RenderOptions:
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    masks: dict[str, Path] = field(default_factory=dict)
    encoder: str = "auto"          # auto | nvenc | x264
    hwaccel: str = "auto"          # auto | cuda | none
    on_progress: Callable[[str], None] | None = None
    # 226: "" means the project's own choice, else the main setting, else YouTube (``export_quality``).
    export_quality: str = ""
    # 226: a validation run only: the final at this [width, height] instead of 1920x1080.
    validation_size: tuple[int, int] | None = None
    # 226: how long to wait for another render of the same project; None waits until it is done.
    lock_wait_seconds: float | None = None


class RenderError(RuntimeError):
    pass


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          stdin=subprocess.DEVNULL)


def _last_line(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _check(cmd: list[str]) -> None:
    result = _run(cmd)
    if result.returncode != 0:
        raise RenderError(f"FFmpeg failed: {result.stderr.strip()[-1500:]}")


_NVENC_OK: dict[str, bool] = {}
_FFMPEG_VERSION: dict[str, str] = {}


def nvenc_available(ffmpeg: str) -> bool:
    """True when this FFmpeg can actually encode on an NVIDIA GPU (not merely lists the encoder)."""

    if ffmpeg not in _NVENC_OK:
        result = _run([ffmpeg, "-hide_banner", "-v", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.1",
                       "-c:v", "h264_nvenc", "-f", "null", "-"])
        _NVENC_OK[ffmpeg] = result.returncode == 0
    return _NVENC_OK[ffmpeg]


def ffmpeg_version(ffmpeg: str) -> str:
    """The FFmpeg build's version, as ``ffmpeg -version`` gives it ("8.1-full_build-..."); "" when unknown."""

    if ffmpeg not in _FFMPEG_VERSION:
        try:
            text = _run([ffmpeg, "-hide_banner", "-version"]).stdout
        except OSError:
            text = ""
        match = re.search(r"ffmpeg version (\S+)", text or "")
        _FFMPEG_VERSION[ffmpeg] = match.group(1) if match else ""
    return _FFMPEG_VERSION[ffmpeg]


def _use_nvenc(options: RenderOptions) -> bool:
    return options.encoder == "nvenc" or (options.encoder == "auto" and nvenc_available(options.ffmpeg))


def _codec(options: RenderOptions, lists: dict[str, list[str]], *, x264: bool = False) -> tuple[str, list[str]]:
    """The encoder to use and its arguments (``-c:v`` included)."""

    if not x264 and _use_nvenc(options):
        return "h264_nvenc", ["-c:v", "h264_nvenc", *lists["nvenc"]]
    return "libx264", ["-c:v", "libx264", *lists["x264"]]


def _video_codec(options: RenderOptions, profile: dict[str, Any]) -> list[str]:
    return _codec(options, profile)[1]


# The frame rate (226, 161.2) ------------------------------------------------------------------


def _parse_rate(text: Any) -> Fraction | None:
    match = re.fullmatch(r"\s*(\d+)(?:/(\d+))?\s*", str(text or ""))
    if not match:
        return None
    numerator, denominator = int(match.group(1)), int(match.group(2) or 1)
    if numerator <= 0 or denominator <= 0:
        return None
    return Fraction(numerator, denominator)


def _sane(rate: Fraction | None) -> bool:
    # MKV can give a base rate of 1000/1 (its millisecond clock); no recording is filmed that fast.
    return rate is not None and 1 <= rate <= 300


def rate_words(rate: Fraction) -> str:
    """A frame rate for people: "60 fps", "59.94 fps"."""

    return f"{float(rate):.3f}".rstrip("0").rstrip(".") + " fps"


def rate_text(rate: Fraction) -> str:
    """A frame rate for FFmpeg: "60" or the exact fraction "60000/1001"."""

    return str(rate)


def export_frame_rate(avg_text: str, r_text: str,
                      count: Callable[[], tuple[float, int] | None] | None = None) -> tuple[Fraction, str]:
    """The final's frame rate for a recording whose FFprobe rates are ``avg_text`` (avg_frame_rate) and
    ``r_text`` (r_frame_rate), and why (226, 161.2).

    The average is preferred; the base rate is used when the average is missing or not a sane rate.
    When both are sane but differ by more than 1%, ``count`` counts the frames over the first 10 s
    (``frame_render.count_frame_rate``) and that is used. The rate snaps to the nearest standard rate
    within 1% (``STANDARD_RATES``), kept as an exact fraction. A rate of 60 or less is kept as it is;
    a higher one is divided by the smallest whole number that brings it to 60 or below (120 to 60,
    119.88 to 59.94, 144 to 48, 100 to 50). When no rate can be read: 60, as before, and the reason
    says so.
    """

    avg, base = _parse_rate(avg_text), _parse_rate(r_text)
    avg_said, base_said = str(avg_text or "").strip() or "missing", str(r_text or "").strip() or "missing"
    if _sane(avg) and _sane(base) and abs(avg - base) > max(avg, base) * RATE_TOLERANCE:
        counted = count() if count is not None else None
        measured = Fraction(counted[0]).limit_denominator(100000) if counted else None
        if _sane(measured):
            how = (f"recording avg_frame_rate {avg_said} and r_frame_rate {base_said} disagree; {counted[1]} frames "
                   f"counted in the first {COUNT_SECONDS:g} s give {float(measured):.3f}")
        else:
            measured = avg
            how = (f"recording avg_frame_rate {avg_said} and r_frame_rate {base_said} disagree and its frames could "
                   "not be counted; the average is used")
    elif _sane(avg):
        measured, how = avg, f"recording avg_frame_rate {avg_said}"
    elif _sane(base):
        measured, how = base, f"recording r_frame_rate {base_said} (its avg_frame_rate {avg_said} is not a frame rate)"
    else:
        rate = Fraction(PROFILES["final"]["fps"])
        return rate, (f"the recording's frame rate could not be read (avg_frame_rate {avg_said}, r_frame_rate "
                      f"{base_said}), so {rate_words(rate)} is used, as before")
    nearest = min(STANDARD_RATES, key=lambda rate: abs(measured - rate))
    if abs(measured - nearest) <= nearest * RATE_TOLERANCE:
        snapped = nearest
        how += f": {rate_words(snapped)}" + (f" ({rate_text(snapped)})" if snapped.denominator != 1 else "")
    else:
        snapped = measured.limit_denominator(1001)
        how += f": {rate_words(snapped)}, not a standard rate"
    if snapped <= EXPORT_RATE_CAP:
        return snapped, how + ", kept"
    divisor = math.ceil(snapped / EXPORT_RATE_CAP)
    exported = snapped / divisor
    return exported, how + f", divided by {divisor} to {rate_words(exported)}"


def preview_frame_rate(export: Fraction) -> Fraction:
    """A preview's frame rate: half the export's when that is 48 or more (60 to 30, 59.94 to 29.97),
    else the export's (25 stays 25)."""

    return export / 2 if export >= 48 else export


def recording_frame_rate(project: Path, source: Path, ffprobe: str) -> tuple[Fraction, str]:
    """The export frame rate of this project's recording, and why: from the rates Prepare stored in
    ``project.json`` ("video"), else (a project prepared before 226) from a probe of the recording."""

    video = _read_quietly(project / "project.json").get("video")
    if isinstance(video, dict) and (video.get("avg_frame_rate") or video.get("r_frame_rate")):
        avg_text, r_text, where = str(video.get("avg_frame_rate") or ""), str(video.get("r_frame_rate") or ""), "Prepare"
    else:
        try:
            probed = frame_render.probe_video(ffprobe, source)
        except (OSError, subprocess.SubprocessError):
            probed = {}
        avg_text, r_text = str(probed.get("frame_rate_text") or ""), str(probed.get("r_frame_rate_text") or "")
        where = "a probe of the recording"
    rate, why = export_frame_rate(avg_text, r_text, lambda: frame_render.count_frame_rate(ffprobe, source,
                                                                                          seconds=COUNT_SECONDS))
    return rate, f"{why} (read by {where})"


def _timescale(fps: Fraction) -> int:
    """The MP4 track's clock: a whole number of ticks per frame (60000 for 59.94, 60000 for 60)."""

    return fps.numerator * 1000 if fps.denominator == 1 else fps.numerator


def _seconds(frames: int | Fraction, fps: Fraction) -> str:
    return f"{float(Fraction(frames) / fps):.6f}"


def frames_to_samples(frames: int, fps: Fraction) -> int:
    return int(round(Fraction(frames) * SAMPLE_RATE / fps))


@dataclass(frozen=True)
class SceneTiming:
    """A scene in whole frames at the render's frame rate (226): it starts at ``start_frame`` and is
    exactly ``frames`` long; its sound is exactly ``samples`` long."""

    start_frame: int
    frames: int
    fps: Fraction

    @property
    def end_frame(self) -> int:
        return self.start_frame + self.frames

    @property
    def samples(self) -> int:
        return frames_to_samples(self.frames, self.fps)

    @property
    def start_sample(self) -> int:
        return frames_to_samples(self.start_frame, self.fps)

    @property
    def start_text(self) -> str:
        return _seconds(self.start_frame, self.fps)

    @property
    def read_text(self) -> str:
        # Read a second more than needed: the scene is cut to its exact length in the filter graph.
        return f"{float(Fraction(self.frames) / self.fps) + 1.0:.6f}"


def scene_timing(scene: dict[str, Any], fps: Fraction) -> SceneTiming:
    start = round(Fraction(str(float(scene["in"]))) * fps)
    frames = max(1, round(Fraction(str(scene_length(scene))) * fps))
    return SceneTiming(int(start), int(frames), fps)


# What a render is made with ----------------------------------------------------------------------


@dataclass(frozen=True)
class _Plan:
    profile: str
    width: int
    height: int
    fps: Fraction
    fps_reason: str
    quality: str           # "preview", or the final's export quality
    quality_source: str    # where a final's export quality came from; "" for a preview

    @property
    def fps_text(self) -> str:
        return rate_text(self.fps)

    @property
    def audio_bitrate(self) -> str:
        return QUALITIES[self.quality]["audio_bitrate"] if self.profile == "final" else PROFILES["preview"]["audio_bitrate"]


def _read_quietly(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _known_quality(value: Any) -> str:
    text = str(value or "").strip().casefold()
    return text if text in QUALITIES else ""


def export_quality(project: Path, requested: str = "") -> tuple[str, str]:
    """The final's export quality and where it came from (226, 161.5): the request's, else the page's
    choice for this project (``editor-settings.json`` "export_quality", an override), else the saved
    main setting (``race_video_export_quality``, read only), else YouTube. An unknown name in a request
    is refused; one in a settings file is passed over."""

    if str(requested or "").strip():
        quality = _known_quality(requested)
        if not quality:
            raise ValueError(f"export_quality must be one of {', '.join(QUALITIES)}, not {requested!r}")
        return quality, QUALITY_FROM_REQUEST
    quality = _known_quality(_read_quietly(project / EDITOR_SETTINGS_NAME).get("export_quality"))
    if quality:
        return quality, QUALITY_FROM_PROJECT
    quality = _known_quality(whisper_options.read_saved_settings().get(EXPORT_QUALITY_KEY))
    if quality:
        return quality, QUALITY_FROM_MAIN
    return DEFAULT_QUALITY, QUALITY_FROM_DEFAULT


def validation_size(value: Any) -> tuple[int, int] | None:
    """A validation run's final size, [width, height] in even pixels, or None."""

    if value is None or value == "" or value == []:
        return None
    try:
        width, height = (int(v) for v in value)
    except (TypeError, ValueError):
        raise ValueError("validation_size must be [width, height] in pixels, for example [2560, 1440]") from None
    if not (16 <= width <= 8192 and 16 <= height <= 8192) or width % 2 or height % 2:
        raise ValueError("validation_size must be [width, height] in even pixels from 16 to 8192")
    return width, height


def _plan(project: Path, timeline: dict[str, Any], profile: str, options: RenderOptions) -> _Plan:
    export, why = recording_frame_rate(project, Path(timeline["source"]), options.ffprobe)
    if profile == "final":
        quality, source = export_quality(project, options.export_quality)
        width, height = options.validation_size or (PROFILES["final"]["width"], PROFILES["final"]["height"])
        return _Plan("final", int(width), int(height), export, why, quality, source)
    fps = preview_frame_rate(export)
    if fps != export:
        why += f"; a preview is half that, {rate_words(fps)}"
    return _Plan("preview", PROFILES["preview"]["width"], PROFILES["preview"]["height"], fps, why, "preview", "")


def _scene_lists(plan: _Plan) -> dict[str, list[str]]:
    return LOSSLESS if plan.profile == "final" else {"nvenc": PROFILES["preview"]["nvenc"],
                                                      "x264": PROFILES["preview"]["x264"]}


def _join_lists(plan: _Plan) -> dict[str, list[str]]:
    if plan.profile != "final":
        return {"nvenc": PROFILES["preview"]["nvenc"], "x264": PROFILES["preview"]["x264"]}
    quality = QUALITIES[plan.quality]
    return {"nvenc": list(quality["nvenc"]), "x264": list(quality["x264"])}


def _digest(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:KEY_LENGTH]


def _mix(scene: dict[str, Any]) -> tuple[float, float, dict[str, Any] | None]:
    mix = scene.get("audio") or {"voice": 1.0, "game": 0.5}
    voice, game = float(mix.get("voice", 0)), float(mix.get("game", 0))
    duck = (scene.get("duck") or {"threshold": 0.02, "ratio": 6, "attack": 20, "release": 600}) \
        if voice > 0 and game > 0 else None
    return voice, game, duck


def _transitions(scenes: list[dict[str, Any]], timings: list[SceneTiming], fps: Fraction) -> list[tuple[str, int]]:
    """Each scene's way in and its length in whole frames (a cut has 0); a dissolve or dip is at least
    one frame and shorter than both scenes."""

    found = [("cut", 0)]
    for index in range(1, len(scenes)):
        kind = scenes[index].get("transition_in", "cut")
        frames = 0
        if kind in ("dissolve", "dip"):
            frames = max(1, round(Fraction(str(float(scenes[index].get("transition_dur", 0.6)))) * fps))
            frames = min(frames, timings[index - 1].frames - 1, timings[index].frames - 1)
        found.append((kind, frames) if frames > 0 else ("cut", 0))
    return found


@dataclass
class _Edit:
    """One version's edit at one plan: its timings, transitions and the keys of every file it uses."""

    scenes: list[dict[str, Any]]
    timings: list[SceneTiming]
    transitions: list[tuple[str, int]]
    picture_keys: list[str]
    sound_keys: list[str]
    joined_key: str
    total_frames: int
    fade_in: int
    fade_out: int

    @property
    def keys(self) -> set[str]:
        return {*self.picture_keys, *self.sound_keys, self.joined_key}


def _edit(timeline: dict[str, Any], plan: _Plan, masks: dict[str, str], source: dict[str, Any]) -> _Edit:
    scenes = list(timeline["scenes"])
    timings = [scene_timing(scene, plan.fps) for scene in scenes]
    transitions = _transitions(scenes, timings, plan.fps)
    layout = layout_of(timeline)
    pictures, sounds = [], []
    for scene, timing in zip(scenes, timings):
        pictures.append(_digest({
            "in_frame": timing.start_frame, "out_frame": timing.end_frame, "view": scene.get("view", "center"),
            "inset": scene.get("inset") or None, "title": scene.get("title") or None, "layout": layout,
            "masks": masks, "source": source, "width": plan.width, "height": plan.height, "fps": plan.fps_text,
            "picture_format": PICTURE_FORMATS[plan.profile], "scene_format": SCENE_FORMAT}))
        voice, game, duck = _mix(scene)
        sounds.append(_digest({
            "in_frame": timing.start_frame, "out_frame": timing.end_frame, "fps": plan.fps_text,
            "start_sample": timing.start_sample, "samples": timing.samples, "audio": {"voice": voice, "game": game},
            "duck": duck, "tracks": timeline["tracks"], "source": source, "sound_format": SOUND_FORMAT}))
    total = timings[0].frames
    for (kind, frames), timing in zip(transitions[1:], timings[1:]):
        total += timing.frames - frames
    fade_in = max(1, round(FADE_IN_SECONDS * plan.fps))
    fade_out = max(1, round(FADE_OUT_SECONDS * plan.fps))
    joined = _digest({"pictures": pictures, "frames": [t.frames for t in timings], "transitions": transitions,
                      "fades": [fade_in, fade_out], "fps": plan.fps_text, "width": plan.width, "height": plan.height,
                      "quality": plan.quality, "settings": _join_lists(plan), "join_format": JOIN_FORMAT})
    return _Edit(scenes, timings, transitions, pictures, sounds, joined, total, fade_in, fade_out)


def scene_store(project: Path, profile: str) -> Path:
    """The project's store of rendered scenes for one profile, shared by every version (226)."""

    return project / SCENE_CACHE / profile


def _temp(path: Path) -> Path:
    return path.with_name(f".{path.stem}.{os.getpid()}.tmp{path.suffix}")


def _made(path: Path, key: str) -> dict[str, Any] | None:
    """How a stored file was made (its ``.json``), when the file is there and was made for ``key``."""

    record = _read_quietly(path.with_suffix(".json"))
    if path.is_file() and record.get("key") == key:
        return record
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Progress -----------------------------------------------------------------------------------------


class _Ticker:
    """The render's status lines (226): the latest is said again, from a small thread, when nothing new
    was said for ``PROGRESS_REPEAT_SECONDS``, so a long FFmpeg step is never silent."""

    def __init__(self, on_progress: Callable[[str], None] | None) -> None:
        self.on_progress = on_progress
        self._lock = threading.Lock()
        self._last: str | None = None
        self._sent = time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def say(self, message: str) -> None:
        if self.on_progress is None:
            return
        with self._lock:
            self._last = message
            self._sent = time.monotonic()
            self.on_progress(message)

    def _watch(self) -> None:
        while not self._stop.wait(min(1.0, max(0.01, PROGRESS_REPEAT_SECONDS / 4))):
            with self._lock:
                if self._last is not None and time.monotonic() - self._sent >= PROGRESS_REPEAT_SECONDS:
                    self._sent = time.monotonic()
                    self.on_progress(self._last)

    def __enter__(self) -> "_Ticker":
        if self.on_progress is not None:
            self._thread = threading.Thread(target=self._watch, name="race-video-render-progress", daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)


# The per-project lock (226) ----------------------------------------------------------------------


_KERNEL32: Any = None
_QUERY_LIMITED_INFORMATION, _STILL_ACTIVE, _ACCESS_DENIED = 0x1000, 259, 5
# Windows counts time in 100 ns steps from 1601; this many of them lie before 1970.
_FILETIME_1970 = 116444736000000000


def _kernel32() -> Any:
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    global _KERNEL32
    if _KERNEL32 is None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.GetProcessTimes.argtypes = (wintypes.HANDLE, *(ctypes.POINTER(wintypes.FILETIME),) * 4)
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        _KERNEL32 = kernel32
    return _KERNEL32


def process_alive(pid: int) -> bool:
    """True while the process ``pid`` runs. On Windows asked with OpenProcess (never ``os.kill``, which
    would end it there)."""

    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes  # noqa: PLC0415
        from ctypes import wintypes  # noqa: PLC0415

        kernel32 = _kernel32()
        handle = kernel32.OpenProcess(_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            # Denied means it is there, run by someone else; any other answer means it is gone.
            return ctypes.get_last_error() == _ACCESS_DENIED
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == _STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def process_start_time(pid: int) -> float | None:
    """When the process ``pid`` started, in seconds since 1970 (226), or None when that cannot be told
    (it has ended, it is someone else's, or this system does not say). Windows: GetProcessTimes; Linux:
    ``/proc``. A process number Windows gives out again belongs to a process that started later."""

    if pid <= 0:
        return None
    if os.name == "nt":
        import ctypes  # noqa: PLC0415
        from ctypes import wintypes  # noqa: PLC0415

        kernel32 = _kernel32()
        handle = kernel32.OpenProcess(_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return None
        try:
            created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
            if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel),
                                            ctypes.byref(user)):
                return None
            ticks = (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
            return (ticks - _FILETIME_1970) / 10_000_000
        finally:
            kernel32.CloseHandle(handle)
    try:
        fields = Path(f"/proc/{int(pid)}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()
        boot = next(int(line.split()[1]) for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines()
                    if line.startswith("btime "))
        return boot + int(fields[19]) / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, StopIteration, AttributeError):
        return None


_OWN_START: list[float | None] = []


def _own_start_time() -> float | None:
    if not _OWN_START:
        _OWN_START.append(process_start_time(os.getpid()))
    return _OWN_START[0]


class ProjectLock:
    """One render of a project at a time (226): the page's and the AI editor's own renders share the
    project's scene store. The lock is ``scene-cache/render.lock``; a render waits while another
    process that is still running holds it, and never deletes a running process's lock. A lock whose
    process has ended, or one older than ``LOCK_STALE_SECONDS``, is taken over. The lock keeps when its
    process started, so a process number given out again to another program does not keep it alive."""

    def __init__(self, project: Path, *, wait_seconds: float | None = None,
                 on_wait: Callable[[str], None] | None = None) -> None:
        self.path = project / SCENE_CACHE / LOCK_NAME
        self.takeover_path = self.path.with_name(TAKEOVER_NAME)
        self.wait_seconds = wait_seconds
        self.on_wait = on_wait
        self.token = uuid.uuid4().hex
        self.waited = 0.0
        self.took_over = ""
        self.held = False

    def _stale(self, holder: dict[str, Any]) -> str:
        """Why the lock held as ``holder`` may be taken over, or "" while its render may still run."""

        try:
            age = time.time() - self.path.stat().st_mtime
        except OSError:
            return ""
        if not holder:
            return "an empty lock left by a render that stopped" if age > LOCK_EMPTY_STALE_SECONDS else ""
        started = holder.get("started_epoch")
        if isinstance(started, (int, float)):
            age = time.time() - float(started)
        if age > LOCK_STALE_SECONDS:
            return f"a lock from {holder.get('started', 'long ago')}, older than {LOCK_STALE_SECONDS // 3600} hours"
        pid = holder.get("pid")
        if holder.get("host") != platform.node() or not isinstance(pid, int):
            return ""
        if not process_alive(pid):
            return f"the lock of process {pid}, which has ended"
        # 226: a running process with that number that started after the lock was written (or not when
        # the lock says its process started) is another program: Windows gives the numbers out again.
        now_started = process_start_time(pid)
        recorded = holder.get("process_started_epoch")
        if now_started is not None and (
                (isinstance(recorded, (int, float)) and abs(now_started - float(recorded)) > PROCESS_START_TOLERANCE)
                or (isinstance(started, (int, float)) and now_started > float(started) + PROCESS_START_TOLERANCE)):
            return f"the lock of process {pid}, which has ended (another program has that process number now)"
        return ""

    def _take_over(self, holder: dict[str, Any]) -> bool:
        """Remove the stale lock that was read as ``holder``, safely while other renders may do the same
        (226). An exclusive ``render.lock.takeover`` is made first (one older than
        ``TAKEOVER_STALE_SECONDS`` was left by a render that stopped, and is removed); under it the lock
        is read again and removed only when it is still that stale lock; then the takeover file goes. A
        lock is never renamed, so a drive without hard links is as safe as any. True when the lock is gone
        (take it at once), False to wait and look again."""

        try:
            handle = os.open(self.takeover_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except (FileExistsError, PermissionError):
            try:
                age = time.time() - self.takeover_path.stat().st_mtime
            except OSError:
                return False    # going away at this moment: look again
            if age <= TAKEOVER_STALE_SECONDS:
                return False    # another render is taking it over
            try:
                self.takeover_path.unlink()
            except OSError:
                return False
            return True
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump({"pid": os.getpid(), "host": platform.node(), "token": self.token}, stream)
            if not self.path.exists():
                return True
            current = _read_quietly(self.path)
            why = self._stale(current) if current == holder else ""
            if not why:
                return True     # not the lock that was read, or no longer stale: look again
            try:
                self.path.unlink()
            except FileNotFoundError:
                return True
            except OSError:
                return False
            self.took_over = why
            return True
        finally:
            if _read_quietly(self.takeover_path).get("token") == self.token:
                try:
                    self.takeover_path.unlink()
                except OSError:
                    pass

    def acquire(self) -> "ProjectLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        told = False
        denied = 0
        while True:
            try:
                handle = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except (FileExistsError, PermissionError):
                # Windows answers "denied" for a lock another render is removing at this moment.
                if not self.path.exists():
                    denied += 1
                    if denied > 100:
                        raise
                    time.sleep(0.05)
                    continue
                holder = _read_quietly(self.path)
                if self._stale(holder) and self._take_over(holder):
                    continue
                if not told and self.on_wait is not None:
                    self.on_wait("Waiting for another render of this project to finish")
                    told = True
                if self.wait_seconds is not None and time.monotonic() - started >= self.wait_seconds:
                    raise RenderError(
                        f"another render of this project is still running (process {holder.get('pid', '?')}, since "
                        f"{holder.get('started', 'a moment ago')}); render again when it has finished") from None
                time.sleep(LOCK_RETRY_SECONDS)
                continue
            self.waited = round(time.monotonic() - started, 1)
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump({"pid": os.getpid(), "host": platform.node(), "started": _now(),
                           "started_epoch": time.time(), "process_started_epoch": _own_start_time(),
                           "token": self.token}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            self.held = True
            return self

    def release(self) -> None:
        self.held = False
        if _read_quietly(self.path).get("token") == self.token:
            try:
                self.path.unlink()
            except OSError:
                pass

    def __enter__(self) -> "ProjectLock":
        return self.acquire()

    def __exit__(self, *_exc: Any) -> None:
        self.release()


def acquire_project_lock(project: Path, options: RenderOptions) -> ProjectLock:
    """Take the project's render lock for a caller that holds it across more than one render step (226:
    the export holds it across the final render, its technical check and its placement). While it waits,
    "Waiting for another render…" is said again every few seconds."""

    with _Ticker(options.on_progress) as ticker:
        return ProjectLock(project, wait_seconds=options.lock_wait_seconds, on_wait=ticker.say).acquire()


# Scene pictures ------------------------------------------------------------------------------------


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\u2019").replace("%", "\\%")


def _title_filters(title: dict[str, Any], w: int, h: int) -> list[str]:
    scale = w / 1920
    start, dur = float(title.get("start", 0.4)), float(title.get("dur", 4.0))
    end = start + dur
    alpha = (f"if(lt(t,{start}),0,if(lt(t,{start}+0.4),(t-{start})/0.4,"
             f"if(lt(t,{end}-0.4),1,if(lt(t,{end}),({end}-t)/0.4,0))))")
    lines = [line for line in str(title["text"]).split("\n") if line.strip()]
    style = title.get("style", "lower")
    out = []
    if style == "label":
        return [f"drawtext={_font(True)}text='{_escape(lines[0])}':fontsize={int(40 * scale)}:fontcolor=white"
                f":alpha='{alpha}':x={int(48 * scale)}:y={int(44 * scale)}:box=1:boxcolor=black@0.55"
                f":boxborderw={int(12 * scale)}"]
    if style == "card":
        y0 = h // 2 - int(60 * scale)
        for i, line in enumerate(lines):
            size = int((64 if i == 0 else 36) * scale)
            out.append(f"drawtext={_font(i == 0)}text='{_escape(line)}':fontsize={size}:fontcolor=white:alpha='{alpha}'"
                       f":x=(w-text_w)/2:y={y0 + i * int(80 * scale)}:box=1:boxcolor=black@0.6"
                       f":boxborderw={int(18 * scale)}")
        return out
    base_y = h - int(190 * scale)
    for i, line in enumerate(lines):
        size = int((44 if i == 0 else 30) * scale)
        out.append(f"drawtext={_font(i == 0)}text='{_escape(line)}':fontsize={size}:fontcolor=white:alpha='{alpha}'"
                   f":x={int(80 * scale)}:y={base_y + i * int(56 * scale)}:box=1:boxcolor=black@0.55"
                   f":boxborderw={int(14 * scale)}")
    return out


class _SceneGraph:
    """Builds one scene's filter graph; extra inputs are privacy masks. ``applied`` is the masked
    cameras the graph blurs."""

    def __init__(self, timeline: dict[str, Any], options: RenderOptions, fps: Any, frame_mask: Path) -> None:
        self.layout = layout_of(timeline)
        self.options = options
        self.fps = fps
        self.frame_mask = frame_mask   # where the whole-frame mask is written if a view needs it
        self.inputs: list[str] = []
        self.parts: list[str] = []
        self.applied: set[str] = set()

    def _image_input(self, path: Path) -> int:
        self.inputs += ["-loop", "1", "-framerate", str(self.fps), "-i", str(path)]
        return len(self.inputs) // 6

    def _mask_input(self, panel: str) -> int | None:
        mask = self.options.masks.get(panel)
        return self._image_input(Path(mask)) if mask else None

    def _masked_panels_in(self, x: int, y: int, w: int, h: int) -> list[str]:
        hits = []
        for panel in self.options.masks:
            if panel not in self.layout["panels"]:
                continue
            px, py, pw, ph = (int(v) for v in self.layout["panels"][panel])
            if x < px + pw and px < x + w and y < py + ph and py < y + h:
                hits.append(panel)
        return hits

    def _region(self, x: int, y: int, cw: int, ch: int, label_in: str, label_out: str) -> None:
        """Crop one region of the recording, blurring every masked camera that falls inside it."""

        hits = self._masked_panels_in(x, y, cw, ch)
        if not hits:
            self.parts.append(f"[{label_in}]crop={cw}:{ch}:{x}:{y},setsar=1[{label_out}]")
            return
        self.applied.update(hits)
        if not self.frame_mask.exists():
            build_full_frame_mask(self.options.ffmpeg, self.layout, self.options.masks, self.frame_mask,
                                  int(self.layout["width"]), int(self.layout["height"]))
        mask = self._image_input(self.frame_mask)
        n = label_out
        self.parts.append(
            f"[{label_in}]crop={cw}:{ch}:{x}:{y},setsar=1,split=2[{n}a][{n}b];"
            f"[{n}b]gblur=sigma=30[{n}bb];[{mask}:v]crop={cw}:{ch}:{x}:{y},format=gray[{n}m];"
            f"[{n}bb][{n}m]alphamerge[{n}bm];[{n}a][{n}bm]overlay=shortest=1[{label_out}]"
        )

    def view(self, view: Any, w: int, h: int, label_in: str, label_out: str) -> None:
        if view == "full":
            bar = int(round(w * self.layout["height"] / self.layout["width"] / 2) * 2)
            self._region(0, 0, int(self.layout["width"]), int(self.layout["height"]), label_in, f"{label_out}r")
            self.parts.append(f"[{label_out}r]scale={w}:{bar},pad={w}:{h}:0:(oh-ih)/2:black,setsar=1[{label_out}]")
            return
        if isinstance(view, dict):
            x, y, cw, ch = (int(v) for v in view["crop"])
            self._region(x, y, cw, ch, label_in, f"{label_out}r")
            self.parts.append(f"[{label_out}r]scale={w}:{h}:flags=lanczos,setsar=1[{label_out}]")
            return
        x, y, pw, ph = (int(v) for v in self.layout["panels"][view])
        if any(panel != view for panel in self._masked_panels_in(x, y, pw, ph)):
            # 226: a panel that covers another camera with a mask (a second name for it, or a wide
            # panel) is cut from the whole-frame mask, so that camera is blurred whatever got past the
            # layout guard.
            self._region(x, y, pw, ph, label_in, f"{label_out}r")
            self.parts.append(f"[{label_out}r]scale={w}:{h}:flags=lanczos,setsar=1[{label_out}]")
            return
        mask = self._mask_input(view)
        if mask is None:
            self.parts.append(f"[{label_in}]crop={pw}:{ph}:{x}:{y},scale={w}:{h}:flags=lanczos,setsar=1[{label_out}]")
            return
        self.applied.add(view)
        n = label_out
        self.parts.append(
            f"[{label_in}]crop={pw}:{ph}:{x}:{y},setsar=1,split=2[{n}a][{n}b];"
            f"[{n}b]gblur=sigma=30[{n}bb];[{mask}:v]scale={pw}:{ph},format=gray[{n}m];"
            f"[{n}bb][{n}m]alphamerge[{n}bm];"
            f"[{n}a][{n}bm]overlay=shortest=1,scale={w}:{h}:flags=lanczos,setsar=1[{label_out}]"
        )


def _picture_command(timeline: dict[str, Any], scene: dict[str, Any], plan: _Plan, options: RenderOptions,
                     timing: SceneTiming, out: Path, frame_mask: Path, hwaccel: bool,
                     codec: list[str]) -> tuple[list[str], set[str]]:
    """One scene's picture: exactly ``timing.frames`` frames at the plan's rate and size, video only."""

    w, h, fps = plan.width, plan.height, plan.fps_text
    graph = _SceneGraph(timeline, options, fps, frame_mask)
    inset = scene.get("inset")
    # Whole frames: padded with the last frame if the recording ends early, then cut to the exact count.
    lead = (f"[0:v]fps={fps},tpad=stop_mode=clone:stop={timing.frames},trim=end_frame={timing.frames},"
            "setpts=PTS-STARTPTS")
    graph.parts.append(f"{lead},split=2[vmain][vinset]" if inset else f"{lead}[vmain]")
    graph.view(scene.get("view", "center"), w, h, "vmain", "vbase")
    current = "vbase"
    if inset:
        iw = int(inset.get("width", 440) * w / 1920)
        ih = int(iw * 9 / 16 / 2) * 2
        margin = int(32 * w / 1920)
        pos = inset.get("pos", "top-right")
        x = f"W-w-{margin}" if "right" in pos else str(margin)
        y = str(margin) if "top" in pos else f"H-h-{margin}"
        graph.view(inset.get("view", "right"), iw, ih, "vinset", "vin")
        graph.parts.append("[vin]drawbox=x=0:y=0:w=iw:h=ih:color=white@0.85:t=2[vinb]")
        graph.parts.append(f"[{current}][vinb]overlay=x={x}:y={y}[vov]")
        current = "vov"
    filters = _title_filters(scene["title"], w, h) if scene.get("title") else []
    filters.append("format=yuv420p")
    graph.parts.append(f"[{current}]{','.join(filters)}[vout]")
    # -v warning: FFmpeg's line when CUDA decoding falls back to the CPU inside a run that succeeds.
    cmd = [options.ffmpeg, "-hide_banner", "-v", "warning", "-y"]
    if hwaccel:
        cmd += ["-hwaccel", "cuda"]
    cmd += ["-ss", timing.start_text, "-t", timing.read_text, "-i", str(timeline["source"]), *graph.inputs,
            "-filter_complex", ";".join(graph.parts), "-map", "[vout]", *codec, "-r", fps, str(out)]
    return cmd, graph.applied


def _cuda_failure(stderr: str) -> str:
    """FFmpeg's words when CUDA decoding could not start and it decoded on the CPU instead, or ""."""

    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if _CUDA_FAILED.search(line):
            context, _, text = line.partition("] ")
            text = text or line
            if index and lines[index - 1].startswith(context + "]"):
                text = f"{lines[index - 1].partition('] ')[2]}; {text}"
            return text
    return ""


def render_scene_picture(timeline: dict[str, Any], scene: dict[str, Any], plan: _Plan, options: RenderOptions,
                         timing: SceneTiming, out: Path, key: str) -> dict[str, Any]:
    """Render one scene's picture into ``out`` and keep how it was made beside it. Returns that record.

    CUDA decoding is used with NVENC (or when asked for); a run that fails with it is tried again on
    the CPU, and when NVENC was chosen by itself and fails, x264 encodes. ``decode`` says what really
    decoded: "cuda", "cpu after CUDA failed: <FFmpeg's line>" (FFmpeg fell back inside the run), "cpu
    after a retry", or "cpu". ``retry_reason`` and ``fallback_reason`` are FFmpeg's last line from the
    run that was tried again on the CPU, and from the NVENC run x264 took over from ("" when none).
    """

    out.parent.mkdir(parents=True, exist_ok=True)
    temp = _temp(out)
    frame_mask = temp.with_name(f"{temp.stem}-privacy.png")
    use_cuda = options.hwaccel == "cuda" or (options.hwaccel == "auto" and nvenc_available(options.ffmpeg))
    lists = _scene_lists(plan)
    encoder, codec = _codec(options, lists)
    started = time.monotonic()
    retried = fell_back = ""
    frame_mask.unlink(missing_ok=True)   # built fresh from today's masks when a view needs it

    def attempt(cuda: bool, args: list[str]) -> tuple[subprocess.CompletedProcess[str], set[str]]:
        command, applied = _picture_command(timeline, scene, plan, options, timing, temp, frame_mask, cuda, args)
        return _run(command), applied

    try:
        cuda = use_cuda
        result, applied = attempt(cuda, codec)
        if result.returncode != 0 and cuda and options.hwaccel == "auto":
            retried = _last_line(result.stderr)
            cuda = False
            result, applied = attempt(cuda, codec)
        if result.returncode != 0 and encoder == "h264_nvenc" and options.encoder == "auto":
            fell_back = _last_line(result.stderr)
            encoder, codec = _codec(options, lists, x264=True)
            result, applied = attempt(cuda, codec)
    finally:
        frame_mask.unlink(missing_ok=True)
    if result.returncode != 0:
        temp.unlink(missing_ok=True)
        raise RenderError(f"scene {scene['id']}: FFmpeg failed: {result.stderr.strip()[-1500:]}")
    if cuda:
        failed = _cuda_failure(result.stderr)
        decode = f"cpu after CUDA failed: {failed}" if failed else "cuda"
    else:
        decode = "cpu after a retry" if retried else "cpu"
    replace_durably(temp, out)   # a cached scene is reused by later renders: it must be whole
    record = {"key": key, "made": _now(), "encoder": encoder, "settings": codec[2:], "decode": decode,
              "retry_reason": retried, "fallback_reason": fell_back, "masks_applied": sorted(applied),
              "format": PICTURE_FORMATS[plan.profile],
              "frames": timing.frames, "fps": plan.fps_text, "width": plan.width, "height": plan.height,
              "scene_format": SCENE_FORMAT, "ffmpeg": ffmpeg_version(options.ffmpeg),
              "seconds": round(time.monotonic() - started, 2)}
    write_json_atomic(out.with_suffix(".json"), record)
    return record


# Scene sound ---------------------------------------------------------------------------------------


def _sound_command(timeline: dict[str, Any], scene: dict[str, Any], options: RenderOptions, timing: SceneTiming,
                   out: Path) -> list[str]:
    """One scene's sound: exactly ``timing.samples`` samples of 48 kHz stereo PCM."""

    tracks = timeline["tracks"]
    voice, game, duck = _mix(scene)
    fmt = "aresample=48000,aformat=channel_layouts=stereo"
    parts: list[str] = []
    if duck is not None:
        parts += [
            f"[0:a:{tracks['voice']}]{fmt},volume={voice},asplit=2[avoice][akey]",
            f"[0:a:{tracks['game']}]{fmt},volume={game}[agame]",
            f"[agame][akey]sidechaincompress=threshold={duck['threshold']}:ratio={duck['ratio']}"
            f":attack={duck['attack']}:release={duck['release']}[aducked]",
            "[avoice][aducked]amix=inputs=2:normalize=0:duration=longest[amixed]",
        ]
        alabel = "amixed"
    else:
        name, gain = ("voice", voice) if voice > 0 else ("game", game)
        parts.append(f"[0:a:{tracks[name]}]{fmt},volume={gain}[asolo]")
        alabel = "asolo"
    samples, fade = timing.samples, min(SCENE_FADE_SAMPLES, max(1, timing.samples // 2))
    parts.append(f"[{alabel}]apad=whole_len={samples},atrim=end_sample={samples},asetpts=PTS-STARTPTS,"
                 f"alimiter=limit=0.9:level=disabled,afade=t=in:ns={fade},"
                 f"afade=t=out:ss={max(0, samples - fade)}:ns={fade}[aout]")
    return [options.ffmpeg, "-hide_banner", "-v", "error", "-y", "-ss", timing.start_text, "-t", timing.read_text,
            "-i", str(timeline["source"]), "-filter_complex", ";".join(parts), "-map", "[aout]",
            "-c:a", "pcm_f32le", "-ar", str(SAMPLE_RATE), "-ac", "2", str(out)]


def render_scene_sound(timeline: dict[str, Any], scene: dict[str, Any], options: RenderOptions,
                       timing: SceneTiming, out: Path, key: str) -> dict[str, Any]:
    """Mix one scene's sound into ``out`` (uncompressed) and keep how it was made beside it."""

    out.parent.mkdir(parents=True, exist_ok=True)
    temp = _temp(out)
    started = time.monotonic()
    result = _run(_sound_command(timeline, scene, options, timing, temp))
    if result.returncode != 0:
        temp.unlink(missing_ok=True)
        raise RenderError(f"scene {scene['id']}: mixing its sound failed: {result.stderr.strip()[-1500:]}")
    replace_durably(temp, out)
    record = {"key": key, "made": _now(), "format": SOUND_FILE_FORMAT, "samples": timing.samples,
              "sound_format": SOUND_FORMAT, "seconds": round(time.monotonic() - started, 2)}
    write_json_atomic(out.with_suffix(".json"), record)
    return record


# The joins ----------------------------------------------------------------------------------------


def _join_picture(files: list[Path], edit: _Edit, plan: _Plan, options: RenderOptions, out: Path) -> dict[str, Any]:
    """The edit's picture: the scene pictures joined with cuts, dissolves and dips, faded in and out,
    encoded once at the profile's quality (a final's: the export quality's)."""

    fps = plan.fps_text
    inputs: list[str] = []
    for path in files:
        inputs += ["-i", str(path)]
    parts = [f"[{i}:v]setpts=PTS-STARTPTS,fps={fps},tpad=stop_mode=clone:stop={t.frames},trim=end_frame={t.frames},"
             f"format=yuv420p[sv{i}]" for i, t in enumerate(edit.timings)]
    current, total = "sv0", edit.timings[0].frames
    for i in range(1, len(files)):
        kind, frames = edit.transitions[i]
        if kind in ("dissolve", "dip"):
            xfade = "fade" if kind == "dissolve" else "fadeblack"
            parts.append(f"[{current}][sv{i}]xfade=transition={xfade}:duration={_seconds(frames, plan.fps)}"
                         f":offset={_seconds(total - frames, plan.fps)}[v{i}]")
            total += edit.timings[i].frames - frames
        else:
            # concat answers on the microsecond clock; fps puts the frames back on the frame clock.
            parts.append(f"[{current}][sv{i}]concat=n=2:v=1:a=0,fps={fps}[v{i}]")
            total += edit.timings[i].frames
        current = f"v{i}"
    parts.append(f"[{current}]fade=t=in:s=0:n={edit.fade_in},fade=t=out:s={max(0, total - edit.fade_out)}"
                 f":n={edit.fade_out},format=yuv420p[vf]")
    lists = _join_lists(plan)
    encoder, codec = _codec(options, lists)
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = _temp(out)
    started = time.monotonic()

    def run(args: list[str]) -> subprocess.CompletedProcess[str]:
        return _run([options.ffmpeg, "-hide_banner", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(parts),
                     "-map", "[vf]", *args, "-r", fps, "-video_track_timescale", str(_timescale(plan.fps)), str(temp)])

    result = run(codec)
    fell_back = ""
    if result.returncode != 0 and encoder == "h264_nvenc" and options.encoder == "auto":
        # 226: why x264 took over is FFmpeg's last line from the NVENC run, kept in the report.
        fell_back = _last_line(result.stderr)
        encoder, codec = _codec(options, lists, x264=True)
        result = run(codec)
    if result.returncode != 0:
        temp.unlink(missing_ok=True)
        raise RenderError(f"joining the picture failed: FFmpeg: {result.stderr.strip()[-1500:]}")
    replace_durably(temp, out)
    return {"encoder": encoder, "settings": codec[2:], "fallback_reason": fell_back, "frames": total, "fps": fps,
            "width": plan.width, "height": plan.height, "quality": plan.quality,
            "seconds": round(time.monotonic() - started, 2)}


def _join_sound(files: list[Path], edit: _Edit, plan: _Plan, options: RenderOptions, out: Path) -> None:
    """The edit's sound, uncompressed: the scene sounds joined with the picture's transitions, sample
    for frame, and padded or cut to exactly the picture's length. It fades in over
    ``SOUND_FADE_IN_SECONDS`` (the picture over ``FADE_IN_SECONDS``) and out with the picture."""

    inputs: list[str] = []
    for path in files:
        inputs += ["-i", str(path)]
    parts = [f"[{i}:a]asetpts=PTS-STARTPTS[sa{i}]" for i in range(len(files))]
    current = "sa0"
    for i in range(1, len(files)):
        kind, frames = edit.transitions[i]
        if kind in ("dissolve", "dip"):
            parts.append(f"[{current}][sa{i}]acrossfade=ns={frames_to_samples(frames, plan.fps)}[a{i}]")
        else:
            parts.append(f"[{current}][sa{i}]concat=n=2:v=0:a=1[a{i}]")
        current = f"a{i}"
    total = frames_to_samples(edit.total_frames, plan.fps)
    fade_in = min(total, round(SOUND_FADE_IN_SECONDS * SAMPLE_RATE))
    fade_out = frames_to_samples(edit.fade_out, plan.fps)
    out_start = frames_to_samples(max(0, edit.total_frames - edit.fade_out), plan.fps)
    parts.append(f"[{current}]afade=t=in:ns={fade_in},afade=t=out:ss={out_start}:ns={fade_out},"
                 f"apad=whole_len={total},atrim=end_sample={total}[af]")
    _check([options.ffmpeg, "-hide_banner", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(parts),
            "-map", "[af]", "-c:a", "pcm_f32le", "-ar", str(SAMPLE_RATE), "-ac", "2", str(out)])


def measure_loudness(ffmpeg: str, path: Path) -> tuple[float | None, float | None]:
    """Integrated loudness (LUFS) and true peak (dBTP) of a file's sound, as the technical check measures them."""

    text = _run([ffmpeg, "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", "ebur128=peak=true",
                 "-f", "null", "-"]).stderr
    i_values = re.findall(r"I:\s+(-?[\d.]+) LUFS", text)
    peaks = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", text)
    return (float(i_values[-1]) if i_values else None, float(peaks[-1]) if peaks else None)


def _loudness(picture: Path, sound: Path, plan: _Plan, options: RenderOptions,
              out: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """The joined picture, copied as it is, with the sound levelled for upload (two-pass loudnorm) and
    encoded to AAC once. When encoding lifts the true peak over the ceiling, the sound alone is
    encoded again a little quieter, from the same uncompressed sound (at most ``PEAK_ATTEMPTS``)."""

    target = f"I={LOUDNESS['I']}:TP={LOUDNESS['TP']}:LRA={LOUDNESS['LRA']}"
    probe = _run([options.ffmpeg, "-hide_banner", "-i", str(sound), "-af",
                  f"loudnorm={target}:print_format=json", "-f", "null", "-"]).stderr
    measured = json.loads(probe[probe.rindex("{"):probe.rindex("}") + 1])
    levelled = (f"loudnorm={target}:linear=true:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
                f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
                f":offset={measured['target_offset']},aresample=48000")
    temp = _temp(out)
    lowered = applied = 0.0
    attempts = 0
    peak: float | None = None
    try:
        while attempts < PEAK_ATTEMPTS:
            attempts += 1
            applied = round(lowered, 2)
            af = levelled + (f",volume=-{applied:.2f}dB" if applied else "")
            _check([options.ffmpeg, "-hide_banner", "-v", "error", "-y", "-i", str(picture), "-i", str(sound),
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-af", af, "-c:a", "aac", "-b:a", plan.audio_bitrate,
                    "-ar", "48000", "-ac", "2", "-video_track_timescale", str(_timescale(plan.fps)),
                    "-movflags", "+faststart", str(temp)])
            _integrated, peak = measure_loudness(options.ffmpeg, temp)
            if peak is None or peak <= PEAK_CEILING:
                break
            lowered += peak - PEAK_CEILING + 0.1
        replace_durably(temp, out)   # 183: on the disk before the render is reported done
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    measured["encoded_true_peak"] = peak
    # 226: only the lowering the file was really encoded with (a fourth try's amount is never applied).
    measured["lowered_after_encoding_db"] = applied
    return measured, {"attempts": attempts, "lowered_db_applied": applied, "encoded_true_peak": peak}


# Readable names (178) -----------------------------------------------------------------------------


def readable_name(project: Path, version: int, profile: str) -> str:
    """The render's readable file name: ``<project>-v003-<editor label>-<profile>.mp4`` (no label part
    when the AI editor gave none)."""

    label = str(version_entry(project, version).get("editor_label") or "")
    base = slug(project.name).lstrip(".").rstrip(". ") or "video"
    return f"{base}-v{version:03d}{'-' + label if label else ''}-{profile}.mp4"


def _renew_readable(project: Path, version: int, profile: str, final: Path) -> tuple[str, str]:
    """Link the readable name to the render just made, through a temporary link and a rename, so the
    name never keeps an older render. Returns the readable file ("" when there is none) and a note.
    Gigabytes are never copied: when a link cannot be made, the render stays and the note says why."""

    readable = final.with_name(readable_name(project, version, profile))
    if len(str(readable)) > READABLE_PATH_LIMIT:
        base = slug(project.name).lstrip(".").rstrip(". ") or "video"
        readable = final.with_name(f"{base}-v{version:03d}-{profile}.mp4")
    if len(str(readable)) > READABLE_PATH_LIMIT:
        return "", "no readable name: the project's folder path is too long for one"
    temp = readable.with_name(f".{readable.name}.{os.getpid()}.tmp")
    temp.unlink(missing_ok=True)
    try:
        os.link(final, temp)
    except OSError as exc:
        problem = f"this drive cannot link the render under a readable name ({exc.strerror or exc})"
    else:
        try:
            replace_durably(temp, readable)
            return str(readable), ""
        except OSError as exc:
            temp.unlink(missing_ok=True)
            problem = f"the readable name could not be renewed; it is probably open in a player ({exc.strerror or exc})"
    # The old readable link would show an older render: it goes, when it can.
    try:
        readable.unlink(missing_ok=True)
    except OSError:
        problem += f"; {readable.name} still shows an earlier render"
    return "", problem


# Trimming the store (226) -------------------------------------------------------------------------


def _trim(project: Path, profile: str, version: int, plan: _Plan, masks: dict[str, str], source: dict[str, Any],
          current: _Edit) -> dict[str, Any]:
    """Remove what no kept version uses from the profile's store, under the render lock. A preview keeps
    what the newest versions, the version just rendered and every exported version use; a final keeps
    only the newest final's. Leftovers of a render that stopped go too (none runs now: the lock). A file
    that cannot be removed is passed over."""

    keep = set(current.keys)
    kept_versions = {version}
    if profile != "final":
        entries = [entry for entry in _read_quietly(project / "project.json").get("versions") or []
                   if isinstance(entry, dict) and isinstance(entry.get("version"), int)]
        numbers = sorted(entry["version"] for entry in entries)
        chosen = set(numbers[-NEWEST_PREVIEWS_KEPT:]) | {e["version"] for e in entries if export_file(project, e)}
        for number in sorted(chosen - {version}):
            try:
                timeline = read_json(version_dir(project, number) / "timeline.json")
                if validate_timeline(timeline):
                    continue
                keep |= _edit(timeline, plan, masks, source).keys
            except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError):
                continue
            kept_versions.add(number)
    removed = failed = 0
    store = scene_store(project, profile)
    for folder in (store / PICTURE_DIR, store / SOUND_DIR, store / JOINED_DIR):
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if not path.name.startswith(".") and path.name.split(".", 1)[0] in keep:
                continue
            try:
                path.unlink()
                removed += 1
            except OSError:
                failed += 1
    return {"versions_kept": sorted(kept_versions), "files_removed": removed, "files_not_removed": failed}


def remove_final_store(project: Path) -> dict[str, Any]:
    """Remove the project's store of final scenes (``scene-cache/final``) once an export is placed
    (226): a final's lossless scenes take hundreds of megabytes per minute of edit, so a project keeps
    them only while a final is being made, and exporting again renders them again. Called with the
    project's render lock held. A file that cannot be removed is passed over."""

    store = scene_store(project, "final")
    removed = failed = 0
    if store.is_dir():
        for folder, _subfolders, files in os.walk(store, topdown=False):
            for name in files:
                try:
                    (Path(folder) / name).unlink()
                    removed += 1
                except OSError:
                    failed += 1
            try:
                Path(folder).rmdir()
            except OSError:
                pass
    return {"files_removed": removed, "files_not_removed": failed, "store_left": store.exists()}


# The render ---------------------------------------------------------------------------------------


def _source_fingerprint(project: Path, timeline: dict[str, Any]) -> dict[str, Any]:
    """What the scene keys know of the recording: its content once the project is bound (242, Wave C2: so a
    recording moved and linked again reuses its scenes, and the first preview after binding renders once), else
    its name, size and time."""

    content = bound_content(project)
    if content:
        return {"content_sha256": content}
    source = Path(timeline["source"])
    try:
        return source_fingerprint(source)
    except OSError:
        return dict(_read_quietly(project / "project.json").get("source_fingerprint") or {"name": source.name})


def render_stem(profile: str, options: RenderOptions | None = None) -> str:
    """The render's file name without ``.mp4`` in the version's ``renders`` folder, and the part its
    report (``render-<stem>.json``) and check (``qc-<stem>.json``) are named by: "preview", "final", or
    for a validation run's final "final-2560x1440" (226), so a validation never replaces the real final."""

    size = options.validation_size if options is not None and profile == "final" else None
    return f"final-{int(size[0])}x{int(size[1])}" if size else profile


def render_version(project: Path, version: int, profile: str = "preview",
                   options: RenderOptions | None = None, *, lock: ProjectLock | None = None) -> dict[str, Any]:
    """Render one version of a project. Returns a report, also written beside the render.

    ``lock`` is the project's render lock when the caller already holds it (226: the export holds one
    lock across the render, its check and its placement); without it the render takes and lets go of
    the lock itself. A validation run's final (``options.validation_size``) is written as
    ``final-<w>x<h>.mp4`` with its own report, gets no readable name and leaves the store untrimmed.
    """

    options = options or RenderOptions()
    if lock is not None and not lock.held:
        raise ValueError("the project's render lock passed to render_version is not held")
    if profile not in PROFILES:
        raise ValueError(f"profile must be one of {sorted(PROFILES)}")
    # 226 (decision F): the operator's stored masks are always applied, whatever the caller passed;
    # a stored mask wins over one passed for the same camera.
    stored = load_masks()
    options = replace(options, masks={**dict(options.masks), **stored})
    folder = version_dir(project, version)
    timeline = json.loads((folder / "timeline.json").read_text(encoding="utf-8"))
    problems = validate_timeline(timeline)
    if problems:
        raise ValueError("the timeline cannot be rendered:\n- " + "\n- ".join(problems))
    # 267: the picture and sound come from the project's own recording, once the timeline is checked
    # to name it; a version naming another recording, even one with the same file name, is refused.
    timeline = dict(timeline, source=str(version_recording(project, timeline)))
    # 226: checked again here, not only when the version was added, because timeline.json can be
    # edited by hand: the project's fixed camera layout and its prepared voice and game tracks.
    refusal = timeline_refusal(project, timeline)
    if refusal:
        raise ValueError(refusal)
    for panel, mask in options.masks.items():
        if not Path(mask).is_file():
            raise ValueError(f"the privacy mask for the {panel} camera is missing: {mask}")
    started = time.monotonic()
    plan = _plan(project, timeline, profile, options)
    renders = folder / "renders"
    renders.mkdir(parents=True, exist_ok=True)
    store = scene_store(project, profile)
    stem = render_stem(profile, options)
    with _Ticker(options.on_progress) as ticker:
        held = lock is not None
        lock = lock if held else ProjectLock(project, wait_seconds=options.lock_wait_seconds, on_wait=ticker.say)
        if not held:
            lock.acquire()
        try:
            report = _render_locked(project, version, profile, timeline, plan, options, stored, renders, store, ticker,
                                    stem)
            report["lock"] = {"waited_seconds": lock.waited, "took_over": lock.took_over}
            report["seconds"] = round(time.monotonic() - started, 1)
            write_json_atomic(renders / f"render-{stem}.json", report)
        finally:
            if not held:
                lock.release()
    return report


def _render_locked(project: Path, version: int, profile: str, timeline: dict[str, Any], plan: _Plan,
                   options: RenderOptions, stored: dict[str, Path], renders: Path, store: Path,
                   ticker: _Ticker, stem: str) -> dict[str, Any]:
    validation = stem != profile
    masks_fp = fingerprint(options.masks)
    source_fp = _source_fingerprint(project, timeline)
    edit = _edit(timeline, plan, masks_fp, source_fp)
    count = len(edit.scenes)
    steps: dict[str, float] = {}
    rows: list[dict[str, Any]] = []
    pictures, sounds = [], []
    pictures_rendered = sounds_rendered = 0

    clock = time.monotonic()
    for index, (scene, timing, key) in enumerate(zip(edit.scenes, edit.timings, edit.picture_keys), start=1):
        target = store / PICTURE_DIR / f"{key}.mkv"
        record = _made(target, key)
        state = "reused"
        if record is None:
            ticker.say(f"Rendering the picture of scene {index} of {count}")
            record = render_scene_picture(timeline, scene, plan, options, timing, target, key)
            state = "rendered"
            pictures_rendered += 1
        pictures.append(target)
        rows.append({"id": scene["id"], "picture": {
            "state": state, "key": key, "file": str(target), "encoder": record.get("encoder", ""),
            "settings": record.get("settings", []), "decode": record.get("decode", ""),
            "format": record.get("format", ""), "masks_applied": record.get("masks_applied", []),
            # 226: why it was tried again on the CPU, or why x264 took over from NVENC: FFmpeg's last line.
            "retry_reason": record.get("retry_reason", ""), "fallback_reason": record.get("fallback_reason", ""),
            "frames": timing.frames, "seconds": record.get("seconds", 0.0) if state == "rendered" else 0.0}})
    steps["scene_pictures"] = round(time.monotonic() - clock, 2)

    clock = time.monotonic()
    for index, (scene, timing, key) in enumerate(zip(edit.scenes, edit.timings, edit.sound_keys), start=1):
        target = store / SOUND_DIR / f"{key}.wav"
        record = _made(target, key)
        state = "reused"
        if record is None:
            ticker.say(f"Mixing the sound of scene {index} of {count}")
            record = render_scene_sound(timeline, scene, options, timing, target, key)
            state = "rendered"
            sounds_rendered += 1
        sounds.append(target)
        rows[index - 1]["sound"] = {"state": state, "key": key, "file": str(target), "samples": timing.samples,
                                    "seconds": record.get("seconds", 0.0) if state == "rendered" else 0.0}
    steps["scene_sounds"] = round(time.monotonic() - clock, 2)

    clock = time.monotonic()
    joined = store / JOINED_DIR / f"{edit.joined_key}.mp4"
    join_record = _made(joined, edit.joined_key)
    join_state = "reused"
    if join_record is None:
        ticker.say("Joining the picture")
        join_record = {"key": edit.joined_key, "made": _now(), **_join_picture(pictures, edit, plan, options, joined)}
        write_json_atomic(joined.with_suffix(".json"), join_record)
        join_state = "rendered"
    steps["picture_join"] = round(time.monotonic() - clock, 2)

    clock = time.monotonic()
    ticker.say("Joining the sound")
    sound = renders / f".sound-{stem}.{os.getpid()}.tmp.wav"
    final = renders / f"{stem}.mp4"
    try:
        _join_sound(sounds, edit, plan, options, sound)
        steps["sound_join"] = round(time.monotonic() - clock, 2)
        clock = time.monotonic()
        ticker.say("Levelling the sound for upload")
        measured, loudness = _loudness(joined, sound, plan, options, final)
    finally:
        sound.unlink(missing_ok=True)
    steps["loudness"] = round(time.monotonic() - clock, 2)

    trimmed: dict[str, Any] | None = None
    if validation:
        # 226: a validation run is measured, never watched or kept: no readable name, and the store is
        # left as it is for the real final.
        readable, note = "", "a validation render has no readable name"
    else:
        readable, note = _renew_readable(project, version, profile, final)
        clock = time.monotonic()
        trimmed = _trim(project, profile, version, plan, masks_fp, source_fp, edit)
        steps["trim"] = round(time.monotonic() - clock, 2)
    encoder = str(join_record.get("encoder") or "")
    return {
        "schema": REPORT_SCHEMA,
        "version": version,
        "profile": profile,
        "output": str(final),
        "expected_duration": round(float(Fraction(edit.total_frames) / plan.fps), 3),
        # Scenes whose picture was rendered or reused (226: the sound is counted on its own).
        "scenes_rendered": pictures_rendered,
        "scenes_reused": count - pictures_rendered,
        "scene_sounds_rendered": sounds_rendered,
        "scene_sounds_reused": count - sounds_rendered,
        "privacy_masks": sorted(options.masks),
        # 226: the masks that fell on a camera of this timeline's layout, and what the operator's
        # stored masks were (by their contents) when it was rendered.
        "privacy_masks_applied": sorted(panel for panel in options.masks if panel in layout_of(timeline)["panels"]),
        "privacy_store_fingerprint": fingerprint(stored),
        # 242 (Wave C2): the recording it was rendered from, by content, once the project is bound; an older
        # project's report keeps the shape it had.
        **({"recording": {"content_sha256": bound_content(project)}} if bound_content(project) else {}),
        # What encoded the picture of this file: the join's encoder, as recorded when it ran.
        "encoder": encoder,
        "seconds": 0.0,
        "loudness_measured": measured,
        "ffmpeg": ffmpeg_version(options.ffmpeg),
        "output_format": {
            "width": plan.width, "height": plan.height, "fps": plan.fps_text, "fps_reason": plan.fps_reason,
            "frames": edit.total_frames,
            "picture": {"codec": "h264", "encoder": encoder, "settings": join_record.get("settings", []),
                        "pixel_format": "yuv420p", "timescale": _timescale(plan.fps)},
            "sound": {"codec": "aac", "bitrate": plan.audio_bitrate, "sample_rate": SAMPLE_RATE, "channels": 2},
        },
        "export_quality": plan.quality if profile == "final" else None,
        "export_quality_source": plan.quality_source if profile == "final" else None,
        "validation_size": [plan.width, plan.height] if validation else None,
        "scene_format": {"picture": PICTURE_FORMATS[profile], "sound": SOUND_FILE_FORMAT},
        "scenes": rows,
        "join": {"picture": {"state": join_state, "key": edit.joined_key, "file": str(joined), "encoder": encoder,
                             "settings": join_record.get("settings", []),
                             # 226: FFmpeg's last line when x264 took over the join from NVENC.
                             "fallback_reason": join_record.get("fallback_reason", ""),
                             "seconds": join_record.get("seconds", 0.0) if join_state == "rendered" else 0.0},
                 "sound": {"seconds": steps["sound_join"]}},
        "loudness": loudness,
        "readable_name": readable,
        "readable_note": note,
        "steps": steps,
        "trim": trimmed,
    }
