"""Visual evidence for every narrated moment (101).

The operator's projects are overlays and dashboards, so when they describe a
bug the screen is the evidence. Keyword-flagged candidates are not enough: the
agent finds most bugs by reading the full transcript (94). This module turns
the operator's narration itself into "narration moments" and plans, for each:

* full frames and supported panel crops at a regular spacing, from a few
  seconds before the operator starts talking to a few seconds after they stop, within a
  per-recording budget;
* one short, attachable video clip with the operator's narration audio;
* one small review copy of each whole recording, for context around the
  moments (103).

Panel crops of a triple-monitor recording are filed by the monitor they come
from (left, center, right), which is how the operator describes their screens.

Planning is pure Python; rendering is done by the PowerShell backend with the
same frame renderer the candidate evidence uses. ``write_index_from_request``
records what was actually written in ``NARRATION_EVIDENCE.md``/``.json``.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from .panel_layout import THREE_PANEL_DEFINITIONS, normalize_panel_crop_mode, resolve_panel_definitions
from .session_review import local_io_path
from .sparse_narration import is_silence_hallucination_text

MOMENT_MERGE_GAP_SECONDS = 20.0
MOMENT_PAD_SECONDS = 5.0
FRAME_SPACING_SECONDS = 6.0
MAX_FRAMES_PER_SOURCE = 180
CLIP_MAX_SECONDS = 45.0
INDEX_JSON = "NARRATION_EVIDENCE.json"
INDEX_MARKDOWN = "NARRATION_EVIDENCE.md"
USABLE_STATUSES = {"completed", "skipped"}
REVIEW_VIDEO_WIDTH = 1920

# The operator's three monitors, left to right, keyed by the panel role the
# crop geometry uses elsewhere in the package.
SCREEN_BY_ROLE = {
    "overview_cam": ("left_monitor", "Left monitor"),
    "driver_view": ("center_monitor", "Center monitor"),
    "face_cam": ("right_monitor", "Right monitor"),
}


def screen_name(role: str) -> str:
    return SCREEN_BY_ROLE.get(role, (role, role))[0]


def screen_label(role: str) -> str:
    return SCREEN_BY_ROLE.get(role, (role, role.replace("_", " ").title()))[1]


def _timestamp(seconds: float) -> str:
    total_ms = int(round(max(0.0, seconds) * 1000))
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def _file_stamp(seconds: float) -> str:
    return _timestamp(seconds).replace(":", "-").replace(".", "-")


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_segments(transcript_json_path: str | Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(Path(transcript_json_path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    segments = payload.get("segments") if isinstance(payload, dict) else None
    return [segment for segment in segments or [] if isinstance(segment, dict)]


def narration_moments(
    segments: list[dict[str, Any]],
    *,
    duration_seconds: float = 0.0,
    merge_gap_seconds: float = MOMENT_MERGE_GAP_SECONDS,
) -> list[dict[str, Any]]:
    """Group the operator's spoken segments into moments (pauses < gap merge)."""

    spoken = [
        segment
        for segment in sorted(segments, key=lambda item: _float(item.get("start")))
        if str(segment.get("text") or "").strip()
        and not is_silence_hallucination_text(segment.get("text"))
    ]
    moments: list[dict[str, Any]] = []
    for segment in spoken:
        start = _float(segment.get("start"))
        end = max(start, _float(segment.get("end"), start))
        text = str(segment.get("text") or "").strip()
        if moments and start - moments[-1]["end_seconds"] <= merge_gap_seconds:
            moments[-1]["end_seconds"] = max(moments[-1]["end_seconds"], end)
            moments[-1]["texts"].append(text)
            continue
        moments.append({"start_seconds": start, "end_seconds": end, "texts": [text]})
    for index, moment in enumerate(moments, start=1):
        moment["moment_index"] = index
        if duration_seconds > 0:
            moment["end_seconds"] = min(moment["end_seconds"], duration_seconds)
        moment["text"] = " ".join(moment.pop("texts"))
        moment["start"] = _timestamp(moment["start_seconds"])
        moment["end"] = _timestamp(moment["end_seconds"])
    return moments


def _frame_times(
    moments: list[dict[str, Any]],
    *,
    duration_seconds: float,
    spacing_seconds: float,
    pad_seconds: float,
    max_frames: int,
) -> dict[int, list[float]]:
    """Frame times per moment; spacing widens until the budget fits."""

    spacing = max(1.0, spacing_seconds)
    while True:
        plan: dict[int, list[float]] = {}
        total = 0
        for moment in moments:
            start = max(0.0, moment["start_seconds"] - pad_seconds)
            end = moment["end_seconds"] + pad_seconds
            if duration_seconds > 0:
                end = min(end, max(0.0, duration_seconds - 0.5))
            times: list[float] = []
            cursor = start
            while cursor <= end + 1e-6:
                times.append(round(cursor, 3))
                cursor += spacing
            speech_mid = round((moment["start_seconds"] + moment["end_seconds"]) / 2.0, 3)
            if not any(abs(value - speech_mid) < spacing / 2.0 for value in times):
                times.append(speech_mid)
            plan[moment["moment_index"]] = sorted(set(times))
            total += len(plan[moment["moment_index"]])
        if total <= max_frames or spacing >= 120.0:
            return plan
        spacing *= 1.5


def _clip_ranges(moment: dict[str, Any], *, duration_seconds: float, pad_seconds: float, clip_max_seconds: float) -> list[tuple[float, float]]:
    start = max(0.0, moment["start_seconds"] - pad_seconds)
    end = moment["end_seconds"] + pad_seconds
    if duration_seconds > 0:
        end = min(end, duration_seconds)
    ranges: list[tuple[float, float]] = []
    cursor = start
    while cursor < end - 0.5:
        piece_end = min(end, cursor + clip_max_seconds)
        ranges.append((round(cursor, 3), round(piece_end, 3)))
        cursor = piece_end
    return ranges


def plan_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    output_dir = Path(str(payload.get("output_dir") or ""))
    if not str(output_dir):
        raise ValueError("output_dir is required.")
    panel_mode = normalize_panel_crop_mode(payload.get("panel_crop_mode"))
    panel_definitions = resolve_panel_definitions(payload.get("panel_definitions")) or THREE_PANEL_DEFINITIONS
    spacing = _float(payload.get("frame_spacing_seconds"), FRAME_SPACING_SECONDS)
    pad = _float(payload.get("pad_seconds"), MOMENT_PAD_SECONDS)
    max_frames = int(_float(payload.get("max_frames_per_source"), MAX_FRAMES_PER_SOURCE))
    clip_max = _float(payload.get("clip_max_seconds"), CLIP_MAX_SECONDS)
    sources_out: list[dict[str, Any]] = []
    frame_tasks: list[dict[str, Any]] = []
    clip_tasks: list[dict[str, Any]] = []
    review_video_tasks: list[dict[str, Any]] = []
    for source in payload.get("sources") or []:
        if not isinstance(source, dict):
            continue
        status = str(source.get("status") or "").lower()
        source_id = str(source.get("source_id") or "").strip()
        source_path = str(source.get("source_path") or "").strip()
        if status not in USABLE_STATUSES or not source_id or not source_path:
            continue
        duration = _float(source.get("duration_seconds"))
        moments = narration_moments(load_segments(str(source.get("transcript_json_path") or "")), duration_seconds=duration)
        if not moments:
            continue
        base_rel = f"artifacts/narration/{source_id}"
        times_by_moment = _frame_times(
            moments,
            duration_seconds=duration,
            spacing_seconds=spacing,
            pad_seconds=pad,
            max_frames=max_frames,
        )
        mic_ordinal = source.get("selected_audio_stream_index")
        planned_frames: dict[float, dict[str, Any]] = {}
        for moment in moments:
            moment["frames"] = []
            for frame_time in times_by_moment.get(moment["moment_index"], []):
                stamp = _file_stamp(frame_time)
                if frame_time not in planned_frames:
                    frame_rel = f"{base_rel}/frames/{source_id}_{stamp}.jpg"
                    panels = []
                    if panel_mode != "off":
                        for panel in panel_definitions:
                            role = str(panel["role"])
                            screen = screen_name(role)
                            panel_rel = f"{base_rel}/panels/{screen}/{source_id}_{stamp}_{screen}.jpg"
                            panels.append(
                                {
                                    **dict(panel),
                                    "screen": screen,
                                    "screen_label": screen_label(role),
                                    "relative_path": panel_rel,
                                    "path": str(output_dir / panel_rel),
                                    "status": "pending",
                                }
                            )
                    task = {
                        "evidence_id": f"narration-{source_id}",
                        "artifact_id": f"narration-frame:{source_id}:{int(round(frame_time * 1000))}ms",
                        "source_id": source_id,
                        "source_path": source_path,
                        "timestamp_seconds": frame_time,
                        "timestamp": _timestamp(frame_time),
                        "role": "narration",
                        "relative_path": frame_rel,
                        "path": str(output_dir / frame_rel),
                        "panel_crop_mode": panel_mode,
                        "panels": panels,
                        "status": "pending",
                    }
                    planned_frames[frame_time] = task
                    frame_tasks.append(task)
                task = planned_frames[frame_time]
                moment["frames"].append(
                    {
                        "timestamp": task["timestamp"],
                        "full_frame": task["relative_path"],
                        "panels": {panel["screen"]: panel["relative_path"] for panel in task["panels"]},
                    }
                )
            moment["clips"] = []
            for clip_index, (clip_start, clip_end) in enumerate(
                _clip_ranges(moment, duration_seconds=duration, pad_seconds=pad, clip_max_seconds=clip_max),
                start=1,
            ):
                clip_rel = f"{base_rel}/clips/{source_id}_{_file_stamp(clip_start)}.mp4"
                clip_tasks.append(
                    {
                        "source_id": source_id,
                        "source_path": source_path,
                        "start_seconds": clip_start,
                        "duration_seconds": round(clip_end - clip_start, 3),
                        "audio_ordinal": mic_ordinal if mic_ordinal is not None else "",
                        "relative_path": clip_rel,
                        "path": str(output_dir / clip_rel),
                    }
                )
                moment["clips"].append(
                    {
                        "start": _timestamp(clip_start),
                        "end": _timestamp(clip_end),
                        "path": clip_rel,
                        "part": clip_index,
                    }
                )
        review_rel = f"{base_rel}/review_video_{source_id}.mp4"
        review_video_tasks.append(
            {
                "source_id": source_id,
                "source_path": source_path,
                "duration_seconds": duration,
                "audio_ordinal": mic_ordinal if mic_ordinal is not None else "",
                "width": REVIEW_VIDEO_WIDTH,
                "relative_path": review_rel,
                "path": str(output_dir / review_rel),
            }
        )
        sources_out.append(
            {
                "source_id": source_id,
                "source_filename": str(source.get("source_filename") or Path(source_path).name),
                "review_video": review_rel,
                "moments": moments,
            }
        )
    result = {
        "schema_version": 1,
        "sources": sources_out,
        "frame_tasks": frame_tasks,
        "clip_tasks": clip_tasks,
        "review_video_tasks": review_video_tasks,
        "moment_count": sum(len(item["moments"]) for item in sources_out),
    }
    plan_path = str(payload.get("plan_path") or "").strip()
    if payload.get("prune_stale"):
        result["pruned_count"] = _prune_stale_visuals(output_dir, result, plan_path)
    if plan_path:
        Path(plan_path).parent.mkdir(parents=True, exist_ok=True)
        Path(plan_path).write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")
        result["plan_path"] = plan_path
    return result


def _prune_stale_visuals(output_dir: Path, plan: dict[str, Any], previous_plan_path: str) -> int:
    """201: on a Continue, what an earlier run of this package left that this plan does not make.

    Files under artifacts/narration that no task of this plan writes (a moment no longer found, a
    recording with no narrated moments now), and clips and review copies made from another audio
    track (the operator chose another track and pressed Continue), which would otherwise be reused
    by name. Their index goes too, so a later failure never leaves the old one looking current.
    Only asked for when the package is kept as a folder: a workflow that builds a portable ZIP
    keeps its folder exactly as before. Returns how many files were removed.
    """

    def key(path: Any) -> str:
        # The same file, whether written with the Windows long-path prefix or without.
        text = str(path)
        if text.startswith("\\\\?\\UNC\\"):
            text = "\\\\" + text[8:]
        elif text.startswith("\\\\?\\"):
            text = text[4:]
        return os.path.normcase(os.path.abspath(text))

    planned: set[str] = set()
    for task in plan.get("frame_tasks") or []:
        planned.add(key(task["path"]))
        planned.update(key(panel["path"]) for panel in task.get("panels") or [])
    made_from_track = [*(plan.get("clip_tasks") or []), *(plan.get("review_video_tasks") or [])]
    for task in made_from_track:
        planned.add(key(task["path"]))
        # One being made alongside the transcription is written under this name first.
        planned.add(key(Path(task["path"]).with_suffix(".partial.mp4")))
    previous_tracks: dict[str, str] = {}
    try:
        previous = json.loads(Path(previous_plan_path).read_text(encoding="utf-8")) if previous_plan_path else {}
    except (OSError, ValueError):
        previous = {}
    for task in [*(previous.get("clip_tasks") or []), *(previous.get("review_video_tasks") or [])]:
        if isinstance(task, dict) and task.get("path"):
            previous_tracks[key(task["path"])] = str(task.get("audio_ordinal"))
    removed = 0

    def remove(path: Path) -> None:
        nonlocal removed
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass

    for task in made_from_track:
        earlier = previous_tracks.get(key(task["path"]))
        path = local_io_path(Path(task["path"]))
        if earlier is not None and earlier != str(task.get("audio_ordinal")) and path.is_file():
            remove(path)
    narration_root = local_io_path(output_dir / "artifacts" / "narration")
    if narration_root.is_dir():
        plan_file = key(Path(previous_plan_path)) if previous_plan_path else ""
        for folder, _subfolders, names in os.walk(narration_root, topdown=False):
            for name in names:
                path = Path(folder) / name
                plain = key(path)
                if plain not in planned and plain != plan_file:
                    remove(path)
            if Path(folder) != narration_root:
                try:
                    Path(folder).rmdir()
                except OSError:
                    pass
    for name in (INDEX_JSON, INDEX_MARKDOWN):
        path = local_io_path(output_dir / name)
        if path.is_file():
            remove(path)
    return removed


def write_index_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Record the moments and only the files that were actually written."""

    output_dir = Path(str(payload.get("output_dir") or ""))
    plan = payload.get("plan") or {}
    plan_path = str(payload.get("plan_path") or "").strip()
    if not plan and plan_path:
        plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    sources: list[dict[str, Any]] = []
    frames_written = 0
    clips_written = 0
    moments_with_visuals = 0
    moment_total = 0
    review_videos_written = 0
    for source in plan.get("sources") or []:
        review_video = str(source.get("review_video") or "")
        if review_video and (output_dir / review_video).is_file():
            review_videos_written += 1
        else:
            review_video = ""
        moments_out = []
        for moment in source.get("moments") or []:
            moment_total += 1
            frames = []
            for frame in moment.get("frames") or []:
                if not (output_dir / frame["full_frame"]).is_file():
                    continue
                frames_written += 1
                frames.append(
                    {
                        "timestamp": frame["timestamp"],
                        "full_frame": frame["full_frame"],
                        "panels": {
                            role: path
                            for role, path in (frame.get("panels") or {}).items()
                            if (output_dir / path).is_file()
                        },
                    }
                )
            clips = [clip for clip in moment.get("clips") or [] if (output_dir / clip["path"]).is_file()]
            clips_written += len(clips)
            if frames or clips:
                moments_with_visuals += 1
            moments_out.append(
                {
                    "moment_index": moment.get("moment_index"),
                    "start": moment.get("start"),
                    "end": moment.get("end"),
                    "start_seconds": moment.get("start_seconds"),
                    "end_seconds": moment.get("end_seconds"),
                    "text": moment.get("text"),
                    "clips": clips,
                    "frames": frames,
                }
            )
        sources.append(
            {
                **{k: v for k, v in source.items() if k not in {"moments", "review_video"}},
                "review_video": review_video,
                "moments": moments_out,
            }
        )
    index = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "Screenshots and a short clip for every stretch of operator narration, independent of the keyword scan.",
        "moment_count": moment_total,
        "moments_with_visuals": moments_with_visuals,
        "frame_count": frames_written,
        "clip_count": clips_written,
        "review_video_count": review_videos_written,
        "screens": {screen: label for screen, label in SCREEN_BY_ROLE.values()},
        "sources": sources,
    }
    (output_dir / INDEX_JSON).write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / INDEX_MARKDOWN).write_text(_markdown(index), encoding="utf-8")
    return {
        "index_json_path": str(output_dir / INDEX_JSON),
        "index_markdown_path": str(output_dir / INDEX_MARKDOWN),
        "moment_count": moment_total,
        "moments_with_visuals": moments_with_visuals,
        "frame_count": frames_written,
        "clip_count": clips_written,
        "review_video_count": review_videos_written,
    }


def _markdown(index: dict[str, Any]) -> str:
    lines = [
        "# Narration Evidence",
        "",
        "Every stretch where the operator is talking, with a short video clip and",
        "screenshots from a few seconds before the talking starts to a few seconds after it",
        "stops. This does not depend on the keyword scan: use it for any bug you find",
        "in the transcript. Match a transcript timestamp to the moment whose time range",
        "contains it.",
        "",
        "Screenshots of a triple-monitor recording come as the full width plus one",
        "crop per monitor: `left_monitor`, `center_monitor` and `right_monitor`.",
        "Overlay bugs are usually easiest to see in the monitor crop.",
        "",
        "When you draft an issue, name the specific screenshots and clip that show the",
        "problem. They are local files: propose them as attachments and upload nothing",
        "until the operator approves.",
        "",
        f"- Narration moments: {index['moment_count']} ({index['moments_with_visuals']} with visuals)",
        f"- Screenshots: {index['frame_count']}",
        f"- Clips: {index['clip_count']}",
        f"- Small review videos of whole recordings: {index.get('review_video_count', 0)}",
        "",
    ]
    for source in index.get("sources") or []:
        lines.extend([f"## {source.get('source_filename') or source.get('source_id')}", ""])
        if source.get("review_video"):
            lines.extend(
                [
                    f"Small review video of the whole recording: `{source['review_video']}`",
                    "(for context between moments; use the clips and screenshots as issue attachments)",
                    "",
                ]
            )
        for moment in source.get("moments") or []:
            lines.append(f"### {moment['start']} - {moment['end']}")
            lines.append("")
            text = str(moment.get("text") or "").strip()
            if len(text) > 600:
                text = text[:597] + "..."
            lines.append(f"> {text}")
            lines.append("")
            for clip in moment.get("clips") or []:
                lines.append(f"- Clip: `{clip['path']}` ({clip['start']} - {clip['end']})")
            for frame in moment.get("frames") or []:
                panel_text = ", ".join(f"{screen}: `{path}`" for screen, path in (frame.get("panels") or {}).items())
                lines.append(
                    f"- {frame['timestamp']}: `{frame['full_frame']}`" + (f" ({panel_text})" if panel_text else "")
                )
            if not moment.get("clips") and not moment.get("frames"):
                lines.append("- No visuals could be written for this moment.")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
