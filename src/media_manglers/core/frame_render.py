"""The one frame renderer (214): every screenshot the app takes is made here.

- ``render_moments``: screenshots at chosen moments (Find my bug reports, and Package any video for
  AI with the evidence add-on). One FFmpeg run decodes a short stretch of the recording and keeps
  the frames asked for; a stretch that fails is made one frame at a time instead.
- ``render_exact``: screenshots that must each be a whole decodable frame, with the time each one
  really shows (Review Media Inbox's timeline).
- ``render_cadence``: one screenshot every so many seconds (Package any video for AI).

The three panels of a 5760x1080 recording come with ``render_moments`` and ``render_exact``.
Screenshots an earlier run of the same package already made whole are kept, not made again.

Wave 7 (226) adds what the AI Video Editor needs, as new functions; the ones above are unchanged.

- ``privacy_blur_filter``: the one filter that blurs a picture through a privacy mask (white =
  private), for the editor's stills, close looks and renders.
- ``render_stills``: stills at chosen times, each read on its own by seeking, scaled or cropped,
  blurred through the mask in the same filter graph (no unmasked picture is ever written), with an
  optional time stamp, as JPEG or PNG, several at a time. A folder of stills is reused only when it
  was made with the same settings and the same mask.
- ``contact_sheets``: sheets of labelled tiles made from a folder of stills.
- The game-picture sampler for 217's signal 2: ``picture_region``, ``picture_input_options``,
  ``picture_output``, ``read_picture_samples`` and ``sample_picture``. Keyframes only, shrunk to
  small gray pictures of the game region, either in a feature's own one read of the recording or on
  their own.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import tempfile
from typing import Any, Callable, Iterable, Sequence

from . import panel_layout, voice_track
from .activity_timeline import PICTURE_SAMPLE_HEIGHT, PICTURE_SAMPLE_WIDTH
from .scratch import scratch_root
from .voice_track import _clock

# One batch is at most this many screenshots: FFmpeg cannot read a select expression with more
# than 100 terms (105).
MAX_FRAMES_PER_BATCH = 90
# 201: a longer gap between two screenshots starts a new batch; decoding the gap costs more than
# starting FFmpeg again.
MAX_GAP_SECONDS = 10.0
# A batch never decodes more than this stretch of the recording.
MAX_BATCH_SPAN_SECONDS = 240.0
SHOWINFO_TIMESTAMP = re.compile(r"\bpts_time:([+-]?(?:\d+(?:\.\d*)?|\.\d+))\b")
PANEL_DETECTION = "three_panel_5760x1080"


def _run(command: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False,
        creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
    )


def _run_bytes(command: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess[bytes]:
    """``_run`` for a command whose output is raw picture bytes (226): the same hidden window, with the
    output kept as bytes and the error text decoded."""

    completed = subprocess.run(command, capture_output=True, timeout=timeout, check=False,
                               creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)))
    completed.stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
    return completed


def _failure(completed: subprocess.CompletedProcess[str]) -> str:
    lines = [line.strip() for line in (completed.stderr or "").splitlines() if line.strip()]
    return lines[-1] if lines else f"FFmpeg exited with {completed.returncode}."


def seconds_text(seconds: float) -> str:
    """A time for FFmpeg, as the backend wrote it: never negative, at most three decimals."""

    text = f"{max(0.0, float(seconds)):.3f}".rstrip("0").rstrip(".")
    return text or "0"


def is_complete_jpeg(path: Path | str) -> bool:
    """115: a whole JPEG ends with the FFD9 end-of-image marker."""

    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() < 4:
                return False
            handle.seek(-2, os.SEEK_END)
            return handle.read(2) == b"\xff\xd9"
    except OSError:
        return False


def jpeg_size(path: Path | str) -> tuple[int, int]:
    """Width and height from a JPEG's frame header."""

    with open(path, "rb") as handle:
        data = handle.read()
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        length = int.from_bytes(data[index + 2:index + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            height = int.from_bytes(data[index + 5:index + 7], "big")
            width = int.from_bytes(data[index + 7:index + 9], "big")
            return width, height
        index += 2 + length
    raise RuntimeError(f"Not a readable JPEG: {Path(path).name}")


def _frame_rate(rate_text: str) -> float:
    """A frame rate written as FFprobe writes it ("60/1", "60000/1001", "30"); 0.0 when unreadable."""

    match = re.fullmatch(r"(\d+)(?:/(\d+))?", rate_text)
    rate = 0.0
    if match:
        denominator = float(match.group(2) or 1)
        rate = float(match.group(1)) / denominator if denominator > 0 else 0.0
    return rate


def probe_video(ffprobe_exe: str, source: Path) -> dict[str, Any]:
    """The first video stream's size and average frame rate.

    226: also the stream's base frame rate (``r_frame_rate``), which the AI Video Editor checks the
    average against before choosing its export frame rate.
    """

    completed = _run([ffprobe_exe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                      "stream=width,height,avg_frame_rate,r_frame_rate", "-of", "json", "--", str(source)], timeout=120)
    try:
        stream = (json.loads(completed.stdout or "{}").get("streams") or [{}])[0]
    except (ValueError, IndexError):
        stream = {}
    rate_text = str(stream.get("avg_frame_rate") or "")
    base_text = str(stream.get("r_frame_rate") or "")
    return {"width": int(stream.get("width") or 0), "height": int(stream.get("height") or 0),
            "frame_rate_text": rate_text, "frame_rate": _frame_rate(rate_text),
            "r_frame_rate_text": base_text, "r_frame_rate": _frame_rate(base_text)}


def probe_streams(ffprobe_exe: str, source: Path, *, timeout: float = 120) -> dict[str, Any]:
    """Every stream and the container of a file, as FFprobe's JSON gives them (226): ``{"streams":
    [...], "format": {...}}``, both always there (empty when the file cannot be read). The AI Video
    Editor's technical check reads a finished render through it, so the editor has no FFprobe call
    of its own."""

    try:
        completed = _run([ffprobe_exe, "-v", "error", "-show_streams", "-show_format", "-of", "json", "--", str(source)],
                         timeout=timeout)
        info = json.loads(completed.stdout or "{}")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        info = {}
    if not isinstance(info, dict):
        info = {}
    streams = info.get("streams") if isinstance(info.get("streams"), list) else []
    container = info.get("format") if isinstance(info.get("format"), dict) else {}
    return {"streams": streams, "format": container}


def count_frame_rate(ffprobe_exe: str, source: Path, *, seconds: float = 10.0,
                     timeout: float = 120) -> tuple[float, int] | None:
    """The first video stream's frame rate counted from its packets over the first ``seconds`` (226):
    the rate, and how many packets it was counted from; None when FFprobe cannot say. The AI Video
    Editor counts when a recording's average and base frame rates disagree."""

    try:
        completed = _run([ffprobe_exe, "-v", "error", "-select_streams", "v:0", "-read_intervals", f"%+{seconds:g}",
                          "-count_packets", "-show_entries", "packet=pts_time:stream=nb_read_packets", "-of", "json",
                          "--", str(source)], timeout=timeout)
        info = json.loads(completed.stdout or "{}")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    times = []
    for packet in (info.get("packets") or []) if isinstance(info, dict) else []:
        try:
            times.append(float(packet["pts_time"]))
        except (KeyError, TypeError, ValueError):
            continue
    if len(times) < 2:
        return None
    span = max(times) - min(times)
    if span <= 0:
        return None
    # The packets are frames; from the first to the last there are one fewer frame steps than frames.
    return (len(times) - 1) / span, len(times)


def plan_batches(
    timestamps: list[float],
    *,
    max_frames: int = MAX_FRAMES_PER_BATCH,
    max_gap_seconds: float = MAX_GAP_SECONDS,
    max_span_seconds: float = MAX_BATCH_SPAN_SECONDS,
) -> list[list[int]]:
    """The screenshots in time order, split into batches (each a list of positions in ``timestamps``)."""

    order = sorted(range(len(timestamps)), key=lambda position: float(timestamps[position]))
    batches: list[list[int]] = []
    current: list[int] = []
    for position in order:
        at = float(timestamps[position])
        if current and (
            len(current) >= max_frames
            or at - float(timestamps[current[-1]]) > max_gap_seconds
            or at - float(timestamps[current[0]]) > max_span_seconds
        ):
            batches.append(current)
            current = []
        current.append(position)
    if current:
        batches.append(current)
    return batches


def render_frame(ffmpeg_exe: str, source: Path, timestamp: float, target: Path) -> tuple[int, int]:
    """One screenshot, read on its own; its width and height."""

    target.parent.mkdir(parents=True, exist_ok=True)
    completed = _run([ffmpeg_exe, "-y", "-ss", seconds_text(timestamp), "-i", str(source), "-map", "0:v:0",
                      "-frames:v", "1", "-q:v", "3", str(target)])
    if completed.returncode != 0 or not target.is_file():
        raise RuntimeError(f"Frame extraction failed at {seconds_text(timestamp)} seconds.")
    return jpeg_size(target)


Runner = Callable[..., Any]


def crop_panel(
    ffmpeg_exe: str,
    image: Path,
    panel: dict[str, Any],
    *,
    run: Runner | None = None,
    pix_fmt: str = "",
) -> Path:
    """One panel (``crop_x``, ``crop_y``, ``crop_width``, ``crop_height``) cut from a screenshot
    already made, to the panel's ``path``. ``pix_fmt`` sets the image's pixel format (the Review
    Media Inbox writes every image as full-range ``yuvj420p``)."""

    target = Path(str(panel["path"]))
    target.parent.mkdir(parents=True, exist_ok=True)
    crop = f"crop={int(panel['crop_width'])}:{int(panel['crop_height'])}:{int(panel['crop_x'])}:{int(panel['crop_y'])}"
    command = [ffmpeg_exe, "-y", "-i", str(image), "-vf", crop, "-frames:v", "1", "-update", "1", "-q:v", "3"]
    if pix_fmt:
        command += ["-pix_fmt", pix_fmt]
    completed = (run or _run)([*command, str(target)], timeout=300)
    if int(getattr(completed, "returncode", 0) or 0) != 0 or not target.is_file():
        raise RuntimeError(f"Panel crop failed for role '{panel.get('role', '')}'.")
    return target


def _panels_of(moment: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(panel) for panel in moment.get("panels") or [] if isinstance(panel, dict)]


def _single(ffmpeg_exe: str, source: Path, moment: dict[str, Any], panel_mode: str) -> dict[str, Any]:
    """A screenshot made one at a time, with its panels: the backend's per-frame path."""

    target = Path(str(moment["path"]))
    panels = _panels_of(moment)
    try:
        width, height = render_frame(ffmpeg_exe, source, float(moment["timestamp_seconds"]), target)
    except Exception as exc:  # noqa: BLE001 - every failure is reported, never raised
        message = str(exc)
        return {"status": "failed", "error": message, "width": 0, "height": 0, "panel_detection": "not_attempted",
                "method": "single", "warnings": [f"Frame extraction failed for {moment.get('name') or target.name}: {message}"],
                "panels": [{"status": "failed", "error": f"Full frame extraction failed: {message}"} for _ in panels]}
    if panel_mode == "off":
        return {"status": "created", "error": "", "width": width, "height": height, "panel_detection": "disabled",
                "method": "single", "warnings": [],
                "panels": [{"status": "disabled", "error": "Panel crops disabled by EvidencePanelCrops=Off."} for _ in panels]}
    if not panel_layout.detect_three_panel_layout(width, height)["panels"]:
        return {"status": "created", "error": "", "width": width, "height": height, "panel_detection": "not_applicable",
                "method": "single", "warnings": [], "panels": [{"status": "not_applicable", "error": ""} for _ in panels]}
    results: list[dict[str, Any]] = []
    warnings: list[str] = []
    for panel in panels:
        try:
            panel_width, panel_height = jpeg_size(crop_panel(ffmpeg_exe, target, panel))
            results.append({"status": "created", "error": "", "width": panel_width, "height": panel_height})
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Panel crop failed for {moment.get('name') or target.name} / {panel.get('role', '')}: {exc}")
            results.append({"status": "failed", "error": str(exc)})
    return {"status": "created", "error": "", "width": width, "height": height, "panel_detection": PANEL_DETECTION,
            "method": "single", "warnings": warnings, "panels": results}


def _batch(
    ffmpeg_exe: str,
    source: Path,
    moments: list[dict[str, Any]],
    video: dict[str, Any],
    render_panels: bool,
    panel_mode: str,
) -> list[dict[str, Any]]:
    """Screenshots of one short stretch from a single FFmpeg run. Raises when the run fails."""

    seek = max(0.0, float(moments[0]["timestamp_seconds"]) - 2.0)
    span = max(1.0, float(moments[-1]["timestamp_seconds"]) - seek + 1.0)
    panel_count = len(_panels_of(moments[0])) if render_panels else 0
    reuse = all(
        is_complete_jpeg(moment["path"]) and (not render_panels or all(is_complete_jpeg(panel["path"]) for panel in _panels_of(moment)))
        for moment in moments
    )
    work = Path(tempfile.mkdtemp(prefix=f"media_manglers_evidence_frames_{os.getpid()}_", dir=str(scratch_root())))
    try:
        if not reuse:
            rate = float(video["frame_rate"])
            terms = "+".join(
                f"eq(n\\,{int(math.floor(max(0.0, float(moment['timestamp_seconds']) - seek) * rate + 0.5))})"
                for moment in moments
            )
            lines = [f"[0:v]fps=fps={video['frame_rate_text']},select='{terms}',setpts=N/FRAME_RATE/TB[sequence];"]
            outputs = ["-map", "[full]", "-vsync", "0", "-q:v", "3", str(work / "full-%04d.jpg")]
            if panel_count:
                lines.append("[sequence]split={0}[full]{1};".format(1 + panel_count, "".join(f"[panelin{i}]" for i in range(panel_count))))
                for index, panel in enumerate(_panels_of(moments[0])):
                    lines.append(f"[panelin{index}]crop={int(panel['crop_width'])}:{int(panel['crop_height'])}:"
                                 f"{int(panel['crop_x'])}:{int(panel['crop_y'])}[panel{index}];")
                    outputs += ["-map", f"[panel{index}]", "-vsync", "0", "-q:v", "3", str(work / f"panel-{index}-%04d.jpg")]
            else:
                lines.append("[sequence]null[full];")
            script = work / "frames.filter"
            script.write_text(os.linesep.join(lines), encoding="utf-8")
            completed = _run([ffmpeg_exe, "-y", "-ss", seconds_text(seek), "-t", seconds_text(span), "-i", str(source),
                              "-filter_complex_script", str(script), *outputs])
            if completed.returncode != 0:
                raise RuntimeError(f"Batched source frame extraction failed (ffmpeg exit code {completed.returncode}). {_failure(completed)}")
        results: list[dict[str, Any]] = []
        for number, moment in enumerate(moments, start=1):
            target = Path(str(moment["path"]))
            if not reuse:
                made = work / f"full-{number:04d}.jpg"
                if not made.is_file():
                    raise RuntimeError(f"Batched source frame output {number} was not created.")
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(made, target)
            width, height = jpeg_size(target)
            panels: list[dict[str, Any]] = []
            for index, panel in enumerate(_panels_of(moment)):
                if render_panels and not reuse:
                    made_panel = work / f"panel-{index}-{number:04d}.jpg"
                    if not made_panel.is_file():
                        raise RuntimeError("Batched panel output was not created.")
                    Path(str(panel["path"])).parent.mkdir(parents=True, exist_ok=True)
                    os.replace(made_panel, Path(str(panel["path"])))
                status = "disabled" if panel_mode == "off" else "created" if render_panels else "not_applicable"
                panels.append({
                    "status": status,
                    "error": "Panel crops disabled by EvidencePanelCrops=Off." if panel_mode == "off" else "",
                    "width": int(panel["crop_width"]) if render_panels else 0,
                    "height": int(panel["crop_height"]) if render_panels else 0,
                })
            results.append({
                "status": "created", "error": "", "width": width, "height": height,
                "panel_detection": "disabled" if panel_mode == "off" else PANEL_DETECTION if render_panels else "not_applicable",
                "panels": panels, "method": "batch", "reused": reuse, "batch_size": len(moments),
                "batch_seek_seconds": seek, "warnings": [],
            })
        return results
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _progress_writer(path_value: str, base: dict[str, Any]) -> Callable[..., None]:
    path = Path(path_value) if path_value else None

    def write(**fields: Any) -> None:
        if path is None:
            return
        event = {"schema": "MM_PROGRESS_V1", "updated_at_utc": datetime.now(timezone.utc).isoformat(), **base, **fields}
        temporary = path.with_name(path.name + ".tmp")
        try:
            temporary.write_text(json.dumps(event), encoding="utf-8")
            os.replace(temporary, path)
        except OSError:
            pass  # Reporting progress must never stop the screenshots.

    return write


def render_moments(
    ffmpeg_exe: str,
    source: Path,
    moments: list[dict[str, Any]],
    *,
    ffprobe_exe: str = "",
    panel_mode: str = "auto",
    max_gap_seconds: float = MAX_GAP_SECONDS,
    on_done: Callable[[int, dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Screenshots at these moments (``timestamp_seconds``, ``path`` and optional ``panels`` with a
    crop and ``path`` each), in batches; a batch that fails is made one frame at a time. One result
    per moment, in the order given. ``on_done`` hears each finished moment's position and result."""

    source = Path(source)
    panel_mode = str(panel_mode or "auto").strip().lower()
    ffprobe_exe = ffprobe_exe or str(Path(ffmpeg_exe).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe"))
    video = probe_video(ffprobe_exe, source) if moments else {}
    render_panels = panel_mode != "off" and bool(panel_layout.detect_three_panel_layout(
        int(video.get("width") or 0), int(video.get("height") or 0))["panels"])
    results: list[dict[str, Any] | None] = [None] * len(moments)
    for positions in plan_batches([float(moment["timestamp_seconds"]) for moment in moments],
                                  max_gap_seconds=max_gap_seconds):
        batch = [moments[position] for position in positions]
        try:
            if float(video.get("frame_rate") or 0.0) <= 0:
                raise RuntimeError("Batched source frame extraction requires a valid average frame rate.")
            made = _batch(ffmpeg_exe, source, batch, video, render_panels, panel_mode)
        except Exception as exc:  # noqa: BLE001 - the per-frame path is the fallback for any failure
            made = []
            for moment in batch:
                single = _single(ffmpeg_exe, source, moment, panel_mode)
                made.append(single)
            made[0]["warnings"] = [
                f"Batched evidence rendering failed; using the compatible per-frame path for this batch. {exc}",
                *made[0].get("warnings", []),
            ]
        for position, result in zip(positions, made):
            results[position] = result
            if on_done is not None:
                on_done(position, result)
    return [result or {"status": "failed", "error": "Not rendered.", "panels": []} for result in results]


def render_exact(
    ffmpeg_exe: str,
    source: Path,
    timestamps: list[float],
    frames_dir: Path,
    *,
    name: str = "frame-{ordinal:03d}.jpg",
    run: Runner | None = None,
    on_frame: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """One whole decodable frame at each of these times, each read on its own with the time it
    really shows (``actual_timestamp_seconds``). Raises when a frame does not say its time.
    ``on_frame`` hears each frame as soon as it is made, before the next is read."""

    frames_dir.mkdir(parents=True, exist_ok=True)
    made: list[dict[str, Any]] = []
    for ordinal, timestamp in enumerate(timestamps, 1):
        target = frames_dir / name.format(ordinal=ordinal)
        completed = (run or _run)([
            ffmpeg_exe, "-y", "-hide_banner", "-nostats", "-v", "info", "-copyts", "-ss", f"{timestamp:.6f}",
            "-i", str(source), "-map", "0:v:0", "-frames:v", "1", "-vf", "showinfo", "-q:v", "3",
            "-pix_fmt", "yuvj420p", str(target),
        ], timeout=300)
        if int(getattr(completed, "returncode", 0) or 0) != 0:
            raise RuntimeError(_failure(completed))
        match = SHOWINFO_TIMESTAMP.search(getattr(completed, "stderr", "") or "")
        if match is None:
            raise RuntimeError(f"Rendered frame {ordinal} did not report its achieved timestamp.")
        item = {"ordinal": ordinal, "requested_timestamp_seconds": timestamp,
                "actual_timestamp_seconds": float(match.group(1)), "path": target}
        if on_frame is not None:
            on_frame(item)
        made.append(item)
    return made


def fps_filter(interval_seconds: float) -> str:
    """FFmpeg's fps filter for one frame every ``interval_seconds``, as the backend wrote it."""

    if not (interval_seconds > 0):
        raise ValueError("The frame interval must be more than zero seconds.")
    return "fps=" + f"{1.0 / float(interval_seconds):.8f}".rstrip("0").rstrip(".")


def render_cadence(
    ffmpeg_exe: str,
    video: Path,
    frames_dir: Path,
    interval_seconds: float,
    *,
    use_gpu: bool = False,
    pattern: str = "frame_%06d.jpg",
    after_fps: str = "scale=1280:-2",
    keep_existing: bool = True,
) -> dict[str, Any]:
    """One screenshot every ``interval_seconds`` (Package any video for AI's screenshots, and its
    panel screenshots with a crop as ``after_fps``): a GPU decode first when asked, the CPU when
    that fails. With ``keep_existing`` a folder that already has its screenshots is kept; otherwise
    they are made again. ``ok`` says whether any screenshot was made."""

    frames_dir = Path(frames_dir)
    wildcard = pattern.replace("%06d", "*")

    def made() -> list[Path]:
        return sorted(frames_dir.glob(wildcard))

    if keep_existing and made():
        return {"method": "SKIPPED_EXISTING", "ok": True, "warnings": [], "frame_count": len(made())}
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in ([] if keep_existing else made()):
        old.unlink(missing_ok=True)
    vf = f"{fps_filter(interval_seconds)},{after_fps}" if after_fps else fps_filter(interval_seconds)
    output = str(frames_dir / pattern)
    warnings: list[str] = []
    if use_gpu:
        completed = _run([ffmpeg_exe, "-y", "-hwaccel", "cuda", "-i", str(video), "-map", "0:v:0", "-vf", vf, "-q:v", "3", output])
        if completed.returncode == 0 and made():
            return {"method": "GPU_DECODE_ATTEMPT", "ok": True, "warnings": [], "frame_count": len(made())}
        warnings.append("GPU-assisted frame extraction failed. Falling back to CPU.")
        for partial in made():
            partial.unlink(missing_ok=True)
    completed = _run([ffmpeg_exe, "-y", "-i", str(video), "-map", "0:v:0", "-vf", vf, "-q:v", "3", output])
    ok = completed.returncode == 0 and bool(made())
    return {"method": "CPU", "ok": ok, "warnings": warnings, "frame_count": len(made()),
            "error": "" if ok else f"Frame extraction failed. {_failure(completed)}"}

def render_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """CLI ``frames-render``: ``mode`` "moments" (``source_path``, ``moments``, ``panel_mode``,
    ``max_gap_seconds``, ``progress_file`` and ``progress`` counts) or "cadence" (``video_path``,
    ``frames_dir``, ``interval_seconds``, ``use_gpu``, ``pattern``, ``after_fps``, ``keep_existing``)."""

    ffmpeg_exe = str(payload.get("ffmpeg_exe") or "ffmpeg")
    if str(payload.get("mode") or "moments") == "cadence":
        return render_cadence(ffmpeg_exe, Path(str(payload["video_path"])), Path(str(payload["frames_dir"])),
                              float(payload["interval_seconds"]), use_gpu=bool(payload.get("use_gpu")),
                              pattern=str(payload.get("pattern") or "frame_%06d.jpg"),
                              after_fps=str(payload.get("after_fps") if payload.get("after_fps") is not None else "scale=1280:-2"),
                              keep_existing=bool(payload.get("keep_existing", True)))
    counts = dict(payload.get("progress") or {})
    done_before = int(counts.get("artifact_completed") or 0)
    total = int(counts.get("artifact_total") or 0)
    write = _progress_writer(str(payload.get("progress_file") or ""), {
        "phase": str(counts.get("phase") or "Rich rendering"), "phase_index": int(counts.get("phase_index") or 4),
        "phase_count": int(counts.get("phase_count") or 4), "progress_kind": "work_units",
        "source_id": str(counts.get("source_id") or ""), "source_name": str(counts.get("source_name") or ""),
        "source_completed": int(counts.get("source_completed") or 0), "source_total": int(counts.get("source_total") or 0),
    })
    moments = [dict(item) for item in payload.get("moments") or [] if isinstance(item, dict)]
    finished = [0]

    def done(position: int, result: dict[str, Any]) -> None:
        finished[0] += 1
        write(completed=done_before + finished[0], total=total, artifact_completed=done_before + finished[0],
              artifact_total=total, activity="Created full and panel evidence frame",
              latest_artifact_path=str(moments[position].get("path") or ""))

    results = render_moments(ffmpeg_exe, Path(str(payload["source_path"])), moments,
                             ffprobe_exe=str(payload.get("ffprobe_exe") or ""),
                             panel_mode=str(payload.get("panel_mode") or "auto"),
                             max_gap_seconds=float(payload.get("max_gap_seconds") or MAX_GAP_SECONDS), on_done=done)
    return {"results": results}


# The AI Video Editor's pictures (226) ---------------------------------------------------------

# Text drawn on a picture (time stamps, sheet labels, titles) uses Segoe UI when Windows has it.
FONT_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
# Stills are taken this many at a time: each is its own short FFmpeg seek.
STILL_WORKERS = 4
# A still that takes longer than this has stalled.
STILL_TIMEOUT_SECONDS = 300
# The record of how a folder's stills were made, kept beside them (see ``render_stills``).
STILLS_KEY = ".stills.json"
STILLS_KEY_SCHEMA = "mm-frame-render-stills-v1"
# A contact sheet is 6x6 tiles of 320x180 unless asked otherwise.
SHEET_COLUMNS, SHEET_ROWS = 6, 6
TILE_W, TILE_H = 320, 180
# The region named for each of the three panels of a 5760x1080 recording. The editor names the
# panels left, center and right; the shared layout names them by what they usually show.
PANEL_ROLES = {"left": "overview_cam", "center": "driver_view", "right": "face_cam"}
REGION_NAMES = {"overview_cam": "left panel", "driver_view": "center panel", "face_cam": "right panel"}
# Why privacy_blur_filter refuses a mask with neither a crop nor a scale.
MASK_NOT_FITTED = ("a privacy mask must be scaled or cropped to match the picture: give a crop or a scale "
                   "(the mask's own size is never assumed to be the recording's)")
WHOLE_FRAME = "whole frame"
# The metadata key that makes FFmpeg write one line, with its time, for every picture sample.
PICTURE_TIME_KEY = "mm_picture_sample"


def font_option(bold: bool) -> str:
    """The ``fontfile`` option of FFmpeg's drawtext for Segoe UI (bold or regular), or "" when the
    font is not there and FFmpeg uses its own. Moved here from the editor's renderer (226)."""

    path = FONT_DIR / ("segoeuib.ttf" if bold else "segoeui.ttf")
    if not path.exists():
        return ""
    return "fontfile='" + str(path).replace("\\", "/").replace(":", "\\:") + "':"


def _crop_text(box: Sequence[int]) -> str:
    x, y, w, h = (int(value) for value in box)
    return f"crop={w}:{h}:{x}:{y}"


def _scale_text(size: Sequence[int]) -> str:
    width, height = (int(value) for value in size)
    return f"scale={width}:{height}"


def privacy_blur_filter(
    *,
    crop: Sequence[int] | None = None,
    scale: Sequence[int] | None = None,
    mask_fit: str = "scale",
    sigma: float = 12,
    setsar: bool = False,
    shortest: bool = False,
    after: str = "",
    source: str = "0:v",
    mask: str = "1:v",
    prefix: str = "",
    out: str = "v",
) -> str:
    """The filter that blurs a picture through a privacy mask (white = private), so no unmasked
    picture leaves FFmpeg (226). One builder for the editor's stills, close looks and renders.

    The picture (``source``) is cut to ``crop`` ([x, y, w, h]) and then scaled to ``scale``
    ([w, h]); ``setsar`` sets square pixels after that. A copy is blurred by ``sigma`` and laid over
    it through the mask (``mask``). ``mask_fit`` says what the mask covers:

    - "scale": exactly the picture's region already (a camera panel's own mask, or a whole-frame
      mask for an uncut picture), at any size; it is scaled to the picture's size (``scale``, or the
      size of ``crop`` when there is no scale).
    - "crop": the whole recording, at its own size; it is cut and scaled the same way as the picture.

    A crop or a scale is required: without either, the mask would be left at its own size and FFmpeg
    refuses the overlay unless that is exactly the recording's, so a ValueError is raised instead.

    ``shortest`` ends the overlay with the picture (a render's looped mask image), ``after`` is more
    filters on the result (a time stamp, a final scale), ``prefix`` starts every inner label (a render
    builds several of these in one graph) and ``out`` names the result.
    """

    if mask_fit not in ("scale", "crop"):
        raise ValueError(f"mask_fit must be 'scale' or 'crop', not {mask_fit!r}")
    if crop is None and scale is None:
        raise ValueError(MASK_NOT_FITTED)
    picture: list[str] = []
    fitted: list[str] = []
    if crop is not None:
        picture.append(_crop_text(crop))
        if mask_fit == "crop":
            fitted.append(_crop_text(crop))
    if scale is not None:
        picture.append(_scale_text(scale))
    if setsar:
        picture.append("setsar=1")
    if mask_fit == "crop":
        if scale is not None:
            fitted.append(_scale_text(scale))
    else:
        fitted.append(_scale_text(scale if scale is not None else list(crop or ())[2:]))
    fitted.append("format=gray")
    lead = ",".join(picture)
    p = prefix
    return (f"[{source}]{lead + ',' if lead else ''}split=2[{p}a][{p}b];[{p}b]gblur=sigma={sigma:g}[{p}bb];"
            f"[{mask}]{','.join(fitted)}[{p}m];[{p}bb][{p}m]alphamerge[{p}bm];"
            f"[{p}a][{p}bm]overlay{'=shortest=1' if shortest else ''}{',' + after if after else ''}[{out}]")


def time_stamp_filter(seconds: float) -> str:
    """The time a still shows, drawn in its top-left corner (the editor's close looks)."""

    return (f"drawtext={font_option(True)}text='{_clock(seconds).replace(':', chr(92) + ':')}':fontsize=22:"
            "fontcolor=yellow:box=1:boxcolor=black@0.7:x=4:y=2")


def still_command(
    ffmpeg_exe: str,
    source: Path,
    seconds: float,
    target: Path,
    *,
    scale: Sequence[int] | None = None,
    crop: Sequence[int] | None = None,
    mask: Path | None = None,
    sigma: float = 12,
    stamp: bool = False,
    quality: int = 4,
) -> list[str]:
    """The FFmpeg command for one still (see ``render_stills``). JPEG unless ``target`` ends in .png."""

    command = [ffmpeg_exe, "-hide_banner", "-v", "error", "-y", "-ss", f"{seconds:.2f}", "-i", str(source)]
    stamp_text = time_stamp_filter(seconds) if stamp else ""
    if mask:
        command += ["-i", str(mask), "-filter_complex",
                    privacy_blur_filter(crop=crop, scale=scale, mask_fit="crop" if crop is not None else "scale",
                                        sigma=sigma, after=stamp_text),
                    "-map", "[v]"]
    else:
        chain = [_crop_text(crop) if crop is not None else "", _scale_text(scale) if scale is not None else "", stamp_text]
        if any(chain):
            command += ["-vf", ",".join(part for part in chain if part)]
    command += ["-frames:v", "1"]
    if Path(target).suffix.lower() != ".png":
        command += ["-q:v", str(int(quality))]
    return [*command, "-f", "image2", str(target)]


def _is_complete_image(path: Path) -> bool:
    if path.suffix.lower() == ".png":
        try:
            with open(path, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                if handle.tell() < 12:
                    return False
                handle.seek(-8, os.SEEK_END)
                return handle.read(8) == b"IEND\xaeB`\x82"
        except OSError:
            return False
    return is_complete_jpeg(path)


def _named_like(name: str) -> re.Pattern[str]:
    """The file names ``name`` (a pattern such as "s{index:05d}.jpg") gives, and their temporary names."""

    match = re.search(r"\{index(?::[^}]*)?\}", name)
    if match is None:
        return re.compile(r"\.?" + re.escape(name))
    return re.compile(r"\.?" + re.escape(name[:match.start()]) + r"\d+" + re.escape(name[match.end():]))


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def render_stills(
    ffmpeg_exe: str,
    source: Path,
    times: Sequence[float],
    out_dir: Path,
    *,
    scale: Sequence[int] | None = None,
    crop: Sequence[int] | None = None,
    mask: Path | None = None,
    sigma: float = 12,
    stamp: bool = False,
    quality: int = 4,
    name: str = "s{index:05d}.jpg",
    start_index: int = 0,
    workers: int = STILL_WORKERS,
    reuse: bool = True,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[Path]:
    """One still at each of ``times`` (seconds into ``source``), in ``out_dir``, in the order given (226).

    Each still is read on its own by seeking just before it, so a long recording is never decoded
    whole; ``workers`` of them are taken at a time. ``crop`` ([x, y, w, h]) cuts a region at the
    recording's own resolution and ``scale`` ([w, h]) sizes the picture. With ``mask`` (a whole-frame
    privacy mask, white = private: at the recording's size when cropping, otherwise any size, scaled
    with the picture) the private parts are blurred by ``sigma`` in the same FFmpeg run, so no
    unmasked still is ever written; a mask needs a ``crop`` or a ``scale`` to fit it to the picture,
    and without either it is refused (ValueError) before anything is taken or the folder is touched.
    ``stamp`` draws the time in a corner. ``quality`` is the JPEG quality (2 best); a
    ``name`` ending in .png makes PNG stills. Stills are named ``name`` with ``index`` counting from
    ``start_index`` ("s00000.jpg" onwards by default); each is written under a temporary name and
    renamed when whole. ``on_progress`` hears how many are done, of how many.

    With ``reuse``, ``out_dir`` keeps a record of how its stills were made (``STILLS_KEY``: the
    recording, the times and every setting above, and the mask's contents). Whole stills are kept
    only when that record matches; otherwise every still in the folder is taken again, and stills
    left from other settings are removed, so a picture masked differently, or not at all, is never
    handed on. Without ``reuse`` every still is taken again and nothing else is touched.
    """

    if mask and crop is None and scale is None:
        raise ValueError(MASK_NOT_FITTED)
    source = Path(source)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = [out_dir / name.format(index=start_index + position) for position in range(len(times))]
    kept = False
    if reuse:
        stat = source.stat()
        key = {
            "schema": STILLS_KEY_SCHEMA,
            "source": str(source), "source_size": stat.st_size, "source_modified_ns": stat.st_mtime_ns,
            "times": [f"{float(seconds):.2f}" for seconds in times],
            "scale": [int(value) for value in scale] if scale is not None else None,
            "crop": [int(value) for value in crop] if crop is not None else None,
            "mask": _file_sha256(Path(mask)) if mask else "",
            "sigma": float(sigma), "stamp": bool(stamp), "quality": int(quality),
            "name": name, "start_index": int(start_index),
        }
        record = out_dir / STILLS_KEY
        try:
            kept = json.loads(record.read_text(encoding="utf-8")) == key
        except (OSError, ValueError):
            kept = False
        if not kept:
            record.unlink(missing_ok=True)
            pattern = _named_like(name)
            for old in out_dir.iterdir():
                if old.is_file() and pattern.fullmatch(old.name):
                    old.unlink(missing_ok=True)
            temporary = record.with_name(record.name + ".tmp")
            temporary.write_text(json.dumps(key, indent=1), encoding="utf-8")
            os.replace(temporary, record)

    def take(position: int) -> Path:
        seconds = float(times[position])
        target = targets[position]
        if kept and _is_complete_image(target):
            return target
        temp = target.with_name(f".{target.name}")
        command = still_command(ffmpeg_exe, source, seconds, temp, scale=scale, crop=crop, mask=mask, sigma=sigma,
                                stamp=stamp, quality=quality)
        try:
            completed = _run(command, timeout=STILL_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            temp.unlink(missing_ok=True)
            raise RuntimeError(f"could not take a still at {_clock(seconds)}: FFmpeg did not finish in "
                               f"{STILL_TIMEOUT_SECONDS} s") from None
        if completed.returncode != 0 or not temp.exists():
            temp.unlink(missing_ok=True)
            raise RuntimeError(f"could not take a still at {_clock(seconds)}: {(completed.stderr or '').strip()[-300:]}")
        temp.replace(target)
        return target

    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
        futures = [pool.submit(take, position) for position in range(len(times))]
        for done, future in enumerate(as_completed(futures), start=1):
            future.result()
            if on_progress:
                on_progress(done, len(futures))
        return [future.result() for future in futures]


def contact_sheets(
    ffmpeg_exe: str,
    stills: Path,
    count: int,
    start: float,
    interval: float,
    crop: Sequence[int],
    out: Path,
    *,
    tile: Sequence[int] = (TILE_W, TILE_H),
    columns: int = SHEET_COLUMNS,
    rows: int = SHEET_ROWS,
    label: bool = True,
    pattern: str = "s%05d.jpg",
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict[str, Any]]:
    """Sheets of tiles cut from ``count`` stills in ``stills`` (named ``pattern``, from 0), each tile
    the ``crop`` ([x, y, w, h]) of one still at ``tile`` size, labelled with its time (``start`` plus
    ``interval`` per still) unless ``label`` is off. 6x6 tiles of 320x180 by default; the tiles left
    over on the last sheet are black. Written to ``out/sheet-NN.jpg``; ``on_progress`` hears each
    sheet. Moved here from the AI Video Editor (226), with the same FFmpeg command."""

    out.mkdir(parents=True, exist_ok=True)
    per = columns * rows
    sheets = []
    x, y, w, h = crop
    tile_w, tile_h = tile
    for number, first in enumerate(range(0, count, per), start=1):
        text = (f"drawtext={font_option(True)}text='%{{eif\\:trunc(({start}+(n+{first})*{interval})/60)\\:d\\:2}}"
                f"\\:%{{eif\\:mod({start}+(n+{first})*{interval}\\,60)\\:d\\:2}}'"
                f":fontsize=20:fontcolor=yellow:box=1:boxcolor=black@0.7:x=4:y=2")
        target = out / f"sheet-{number:02d}.jpg"
        tiles = min(per, count - first)
        result = _run([ffmpeg_exe, "-hide_banner", "-v", "error", "-y", "-framerate", "1", "-start_number", str(first),
                       "-i", str(stills / pattern), "-frames:v", "1", "-q:v", "3",
                       # Black frames after the last still fill a part-empty sheet (the tile filter's own
                       # filler colour does not apply here and leaves the empty tiles green).
                       "-vf", f"crop={w}:{h}:{x}:{y},scale={tile_w}:{tile_h},{text + ',' if label else ''}"
                              f"tpad=stop={per}:stop_mode=add:color=black,tile={columns}x{rows}",
                       str(target)])
        if result.returncode != 0:
            raise RuntimeError(f"could not make contact sheet {number}: {result.stderr.strip()[-300:]}")
        sheets.append({"file": target.name, "from": round(start + first * interval, 1),
                       "to": round(start + (first + tiles - 1) * interval, 1), "tiles": tiles})
        if on_progress:
            on_progress(number, math.ceil(count / per))
    return sheets


# The tiny gray pictures sharp picture changes are scored on (the AI Video Editor's digest).
GRAY_TILE_SIZE = (32, 18)


def gray_tiles(
    ffmpeg_exe: str,
    stills: Path,
    count: int,
    crop: Sequence[int],
    *,
    size: Sequence[int] = GRAY_TILE_SIZE,
    pattern: str = "s%05d.jpg",
) -> list[bytes]:
    """The ``crop`` ([x, y, w, h]) of each of the first ``count`` stills in ``stills`` (named
    ``pattern``, from 0), shrunk to ``size`` gray pixels, one bytes object each, in order (226: moved
    here from the AI Video Editor, with the same FFmpeg command). Raises RuntimeError with FFmpeg's
    last line when the stills cannot be read, so a failure is never mistaken for "no change"."""

    x, y, w, h = (int(value) for value in crop)
    tile_w, tile_h = (int(value) for value in size)
    completed = _run_bytes([ffmpeg_exe, "-hide_banner", "-v", "error", "-framerate", "1", "-i", str(Path(stills) / pattern),
                            "-vf", f"crop={w}:{h}:{x}:{y},scale={tile_w}:{tile_h},format=gray", "-f", "rawvideo", "-"])
    if completed.returncode != 0:
        raise RuntimeError(f"could not read the stills to compare them: {_failure(completed)}")
    raw = completed.stdout or b""
    each = tile_w * tile_h
    return [raw[index * each:(index + 1) * each] for index in range(min(int(count), len(raw) // each))]


# 217 signal 2, the game picture not changing (226) ------------------------------------------

def picture_region(
    width: int,
    height: int,
    *,
    game_panel: str = "center",
    masked_panels: Iterable[str] = (),
) -> tuple[tuple[int, int, int, int], str] | None:
    """The part of the picture signal 2 measures, as ([x, y, w, h], its name), or None.

    On an exact 5760x1080 recording that is the game panel (``game_panel``, "center" by default:
    the editor's panel names or the shared layout's roles), from the shared three-panel geometry:
    the camera panels beside it move while the driver is away and carry the privacy masks. A panel
    that has a mask (``masked_panels``) is never measured, so asking for one gives None, as does an
    unknown panel or a recording with no picture size. Any other size is measured whole.
    """

    width, height = int(width or 0), int(height or 0)
    if width <= 0 or height <= 0:
        return None
    layout = panel_layout.detect_three_panel_layout(width, height)
    if not layout["panels"]:
        return (0, 0, width, height), WHOLE_FRAME
    role = PANEL_ROLES.get(str(game_panel), str(game_panel))
    if role in {PANEL_ROLES.get(str(panel), str(panel)) for panel in masked_panels}:
        return None
    for panel in layout["panels"]:
        if panel["role"] == role:
            box = (int(panel["crop_x"]), int(panel["crop_y"]), int(panel["crop_width"]), int(panel["crop_height"]))
            return box, REGION_NAMES.get(role, f"{role} panel")
    return None


def picture_input_options(keyframes_only: bool = True) -> list[str]:
    """Input options for the game-picture output, placed just before ``-i``: the video decoder
    decodes only the keyframes (the sound is decoded as before). Never add a frame-rate filter after
    this: it would repeat each keyframe to fill the seconds, and the repeats would read as no change."""

    return ["-skip_frame:v:0", "nokey"] if keyframes_only else []


def _filter_value(text: str) -> str:
    """``text`` as an option value inside an FFmpeg filter description: both escaping levels."""

    for special in ("\\", "'", ":"):
        text = text.replace(special, "\\" + special)
    for special in ("\\", "'", "[", "]", ",", ";"):
        text = text.replace(special, "\\" + special)
    return text


def picture_output(
    region: Sequence[int],
    frames_path: Path,
    times_path: Path,
    *,
    map_spec: str = "0:v:0",
) -> list[str]:
    """The output arguments that write the game picture's samples: every decoded picture of
    ``map_spec``, cut to ``region`` ([x, y, w, h]), shrunk to 64x36 gray (each cell the average of
    its area) and appended to ``frames_path`` as raw bytes, with one line naming each picture's time
    in ``times_path``. That line is written by the filter itself, so it works at ``-loglevel error``;
    ``-fps_mode passthrough`` keeps every picture once, at its own time. Added after the sound's
    outputs of a one-read decode (``voice_track.extract_all_tracks``), the sound is unchanged."""

    chain = (f"{_crop_text(region)},scale={PICTURE_SAMPLE_WIDTH}:{PICTURE_SAMPLE_HEIGHT}:flags=area,format=gray,"
             f"metadata=mode=add:key={PICTURE_TIME_KEY}:value=1,"
             f"metadata=mode=print:key={PICTURE_TIME_KEY}:file={_filter_value(str(times_path).replace(chr(92), '/'))}")
    return ["-map", map_spec, "-fps_mode", "passthrough", "-vf", chain,
            "-c:v", "rawvideo", "-pix_fmt", "gray", "-f", "rawvideo", str(frames_path)]


def read_picture_samples(frames_path: Path, times_path: Path) -> tuple[list[float], list[bytes]]:
    """The samples ``picture_output`` wrote: their times in seconds, and each 64x36 gray picture.
    Raises when the two files do not agree (an interrupted read)."""

    size = PICTURE_SAMPLE_WIDTH * PICTURE_SAMPLE_HEIGHT
    try:
        raw = Path(frames_path).read_bytes()
        text = Path(times_path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise RuntimeError(f"The game picture samples were not written: {exc}") from exc
    if len(raw) % size:
        raise RuntimeError("The game picture samples end part-way through a picture.")
    times = [float(value) for value in SHOWINFO_TIMESTAMP.findall(text)]
    frames = [raw[index * size:(index + 1) * size] for index in range(len(raw) // size)]
    if len(frames) != len(times):
        raise RuntimeError(f"The game picture has {len(frames)} samples but {len(times)} sample times.")
    return times, frames


def sample_picture(
    ffmpeg_exe: str,
    source: Path,
    region: Sequence[int],
    work: Path,
    *,
    keyframes_only: bool = True,
    use_gpu: bool = False,
    on_progress: Callable[[float], None] | None = None,
    stall_seconds: float = voice_track.DECODE_STALL_SECONDS,
) -> dict[str, Any]:
    """The game picture's samples read on their own, for a recording whose sound was read already
    (``picture_output`` adds them to a feature's own one read instead). A GPU decode first when
    asked, the CPU when that fails, as ``render_cadence`` does.

    Like the sound's read (``voice_track.run_while_progressing``, 145) it has no time limit while
    FFmpeg keeps moving through the recording, and is stopped when it makes no progress for
    ``stall_seconds``; a stopped read is a failed attempt, so a stalled GPU read is tried again on
    the CPU. ``on_progress`` is told how far into the recording the read is, in seconds (a CPU read
    after a failed GPU one starts again from the beginning).

    Returns ``ok``, ``method``, ``times`` and ``frames`` (``read_picture_samples``), ``sample_count``,
    ``median_spacing_seconds`` (how far apart the samples are; None with fewer than two),
    ``keyframes_only``, ``region``, ``warnings`` and ``error``. Its own files in ``work`` are removed.
    """

    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    frames_path, times_path = work / "picture-samples.raw", work / "picture-sample-times.txt"
    errors_path = work / "picture-errors.txt"

    def attempt(gpu: bool) -> tuple[list[float], list[bytes]]:
        for path in (frames_path, times_path, errors_path):
            path.unlink(missing_ok=True)
        command = [ffmpeg_exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-nostats", "-progress", "pipe:1",
                   "-y"]
        if gpu:
            command += ["-hwaccel", "cuda"]
        command += [*picture_input_options(keyframes_only), "-i", str(source),
                    *picture_output(region, frames_path, times_path)]
        try:
            returncode, _reached = voice_track.run_while_progressing(command, stall_seconds=stall_seconds,
                                                                     stderr_path=errors_path, on_progress=on_progress)
        except RuntimeError as exc:
            # A stall, after FFmpeg is stopped. The shared reason names the audio; this read is the picture.
            raise RuntimeError(str(exc).replace("recording's audio", "recording's picture")) from None
        if returncode != 0:
            try:
                lines = [line.strip() for line in errors_path.read_text(encoding="utf-8", errors="replace").splitlines()
                         if line.strip()]
            except OSError:
                lines = []
            raise RuntimeError(lines[-1] if lines else f"FFmpeg exited with {returncode}.")
        return read_picture_samples(frames_path, times_path)

    result: dict[str, Any] = {"ok": False, "method": "CPU", "times": [], "frames": [], "sample_count": 0,
                              "median_spacing_seconds": None, "keyframes_only": bool(keyframes_only),
                              "region": [int(value) for value in region], "warnings": [], "error": ""}
    try:
        samples = None
        if use_gpu:
            try:
                samples = attempt(True)
                result["method"] = "GPU_DECODE_ATTEMPT"
            except RuntimeError:
                result["warnings"].append("GPU-assisted picture sampling failed. Falling back to CPU.")
        if samples is None:
            try:
                samples = attempt(False)
            except RuntimeError as exc:
                result["error"] = f"The game picture could not be read. {exc}"
                return result
    finally:
        for path in (frames_path, times_path, errors_path):
            path.unlink(missing_ok=True)
    times, frames = samples
    ordered = sorted(times)
    gaps = [later - earlier for earlier, later in zip(ordered, ordered[1:])]
    result.update({"ok": True, "times": times, "frames": frames, "sample_count": len(times),
                   "median_spacing_seconds": round(statistics.median(gaps), 3) if gaps else None})
    return result
