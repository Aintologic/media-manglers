"""The edit timeline: every decision the renderer needs for one version of a video (150).

A timeline is plain JSON, written by the AI editor and kept per version:

    {
      "schema": "mm-race-video-timeline-v1",
      "source": "<recording>",
      "source_layout": {"width": 5760, "height": 1080,
                        "panels": {"left": [0, 0, 1920, 1080], "center": [...], "right": [...]}},
      "tracks": {"voice": 1, "game": 2},          # audio stream ordinals in the recording
      "scenes": [
        {"id": "s01", "beat": "hook", "reason": "...", "in": 12.0, "out": 26.5,
         "view": "center" | "left" | "right" | "full" | {"crop": [x, y, w, h]},
         "inset": {"view": "right", "pos": "top-right", "width": 440},          # optional
         "audio": {"voice": 3.0, "game": 0.5},  # gains; the game ducks under the voice
         "transition_in": "cut" | "dissolve" | "dip", "transition_dur": 0.5,     # optional
         "title": {"text": "Lap 2  ·  P16", "start": 0.4, "dur": 3.0,
                   "style": "lower" | "label" | "card"}}                         # optional
      ]
    }

``validate_timeline`` returns plain-English problems; an empty list means the renderer can run it.
``story_blocks`` turns the scenes into the story strip the AI Video Editor page shows under its player
(236): one block per beat, with where it starts in the edited video.
"""

from __future__ import annotations

from typing import Any

SCHEMA = "mm-race-video-timeline-v1"
DEFAULT_LAYOUT = {
    "width": 5760,
    "height": 1080,
    "panels": {"left": [0, 0, 1920, 1080], "center": [1920, 0, 1920, 1080], "right": [3840, 0, 1920, 1080]},
}
TRANSITIONS = {"cut", "dissolve", "dip"}
TITLE_STYLES = {"lower", "label", "card"}
INSET_POSITIONS = {"top-left", "top-right", "bottom-left", "bottom-right"}
MAX_GAIN = 8.0


def layout_of(timeline: dict[str, Any]) -> dict[str, Any]:
    layout = timeline.get("source_layout") or DEFAULT_LAYOUT
    return {"width": int(layout["width"]), "height": int(layout["height"]), "panels": dict(layout["panels"])}


def scene_length(scene: dict[str, Any]) -> float:
    return round(float(scene["out"]) - float(scene["in"]), 3)


def beat_name(beat: Any) -> str:
    """A scene's beat as the page shows it (236): "pit_stop" or "pit stop" becomes "Pit stop"; "" for none."""

    text = " ".join(str(beat or "").replace("_", " ").split())
    return text[:1].upper() + text[1:]


def story_blocks(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    """The story as the page's scene strip shows it (236): one block for each run of scenes with the same
    beat, in order, with where it starts in the edited video and how long it lasts, in seconds.

    A dissolve or a dip overlaps the end of the scene before it by its length, as the render does, so a
    block starts where the player finds it. A scene with no beat is named by its place ("Scene 3"). A
    scene that cannot be read is passed over: the strip never stops a version from showing.
    """

    blocks: list[dict[str, Any]] = []
    at = 0.0
    previous = 0.0
    for index, scene in enumerate(timeline.get("scenes") or []):
        try:
            length = scene_length(scene)
        except (KeyError, TypeError, ValueError):
            continue
        if length <= 0:
            continue
        overlap = 0.0
        if blocks and scene.get("transition_in", "cut") in ("dissolve", "dip"):
            try:
                overlap = min(float(scene.get("transition_dur", 0.6)), length, previous)
            except (TypeError, ValueError):
                overlap = 0.0
        start = max(0.0, at - max(0.0, overlap))
        at = start + length
        previous = length
        name = beat_name(scene.get("beat")) or f"Scene {index + 1}"
        if blocks and blocks[-1]["name"] == name:
            blocks[-1]["length"] = round(at - blocks[-1]["start"], 3)
            blocks[-1]["scenes"].append(str(scene.get("id") or ""))
            continue
        blocks.append({"name": name, "start": round(start, 3), "length": round(length, 3),
                       "scenes": [str(scene.get("id") or "")]})
    return blocks


def _view_problem(view: Any, layout: dict[str, Any], where: str) -> str | None:
    if isinstance(view, str):
        if view == "full" or view in layout["panels"]:
            return None
        return f"{where}: unknown view '{view}' (use one of {sorted([*layout['panels'], 'full'])} or a crop)"
    if isinstance(view, dict) and isinstance(view.get("crop"), list) and len(view["crop"]) == 4:
        x, y, w, h = (float(v) for v in view["crop"])
        if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > layout["width"] or y + h > layout["height"]:
            return f"{where}: crop {view['crop']} is outside the {layout['width']}x{layout['height']} recording"
        return None
    return f"{where}: a view must be a panel name, 'full', or {{'crop': [x, y, w, h]}}"


def validate_timeline(timeline: dict[str, Any], *, source_duration: float | None = None,
                      audio_streams: int | None = None) -> list[str]:
    """Every reason the renderer could not run this timeline, in plain English."""

    problems: list[str] = []
    if timeline.get("schema") != SCHEMA:
        problems.append(f"schema must be '{SCHEMA}'")
    if not timeline.get("source"):
        problems.append("source (the recording) is missing")
    try:
        layout = layout_of(timeline)
    except (KeyError, TypeError, ValueError):
        return [*problems, "source_layout must give width, height and panels"]
    tracks = timeline.get("tracks") or {}
    for name in ("voice", "game"):
        ordinal = tracks.get(name)
        if not isinstance(ordinal, int) or ordinal < 0:
            problems.append(f"tracks.{name} must be an audio stream number (0 or more)")
        elif audio_streams is not None and ordinal >= audio_streams:
            problems.append(f"tracks.{name} is stream {ordinal}, but the recording has {audio_streams} audio streams")
    scenes = timeline.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return [*problems, "a timeline needs at least one scene"]
    seen: set[str] = set()
    previous_length = None
    for index, scene in enumerate(scenes):
        sid = str(scene.get("id") or f"#{index + 1}")
        where = f"scene {sid}"
        if sid in seen:
            problems.append(f"{where}: the id is used twice")
        seen.add(sid)
        try:
            start, end = float(scene["in"]), float(scene["out"])
        except (KeyError, TypeError, ValueError):
            problems.append(f"{where}: needs numeric 'in' and 'out' times in seconds")
            continue
        if start < 0 or end <= start:
            problems.append(f"{where}: 'out' ({end}) must be after 'in' ({start})")
        if source_duration is not None and end > source_duration + 0.05:
            problems.append(f"{where}: ends at {end:.2f} s, after the recording ends ({source_duration:.2f} s)")
        problem = _view_problem(scene.get("view", "center"), layout, where)
        if problem:
            problems.append(problem)
        inset = scene.get("inset")
        if inset:
            problem = _view_problem(inset.get("view", "right"), layout, f"{where} inset")
            if problem:
                problems.append(problem)
            if inset.get("pos", "top-right") not in INSET_POSITIONS:
                problems.append(f"{where}: inset position must be one of {sorted(INSET_POSITIONS)}")
        audio = scene.get("audio") or {}
        for name, gain in audio.items():
            if name not in ("voice", "game"):
                problems.append(f"{where}: unknown audio source '{name}' (use voice and game)")
            elif not isinstance(gain, (int, float)) or gain < 0 or gain > MAX_GAIN:
                problems.append(f"{where}: audio.{name} must be a gain from 0 to {MAX_GAIN}")
        transition = scene.get("transition_in", "cut")
        if transition not in TRANSITIONS:
            problems.append(f"{where}: transition_in must be one of {sorted(TRANSITIONS)}")
        elif transition != "cut":
            if index == 0:
                problems.append(f"{where}: the first scene cannot dissolve from a previous one")
            duration = float(scene.get("transition_dur", 0.6))
            length = end - start
            if duration <= 0 or duration >= length or (previous_length is not None and duration >= previous_length):
                problems.append(f"{where}: transition_dur {duration} must be shorter than this scene and the one before")
        title = scene.get("title")
        if title:
            if not str(title.get("text", "")).strip():
                problems.append(f"{where}: a title needs text")
            if title.get("style", "lower") not in TITLE_STYLES:
                problems.append(f"{where}: title style must be one of {sorted(TITLE_STYLES)}")
            if float(title.get("start", 0)) + float(title.get("dur", 0)) > end - start + 0.05:
                problems.append(f"{where}: the title runs past the end of the scene")
        previous_length = end - start
    return problems
