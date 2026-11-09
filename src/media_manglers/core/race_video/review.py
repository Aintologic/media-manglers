"""Tools the AI editor uses to look closer and to review its own drafts (150 Phase 2).

Everything here runs locally. The parts that need Whisper (the transcript of a cut and the word
timings at cut points) run in the Python that has Whisper installed, the same one the backend uses
for transcription; without it they say so instead of failing silently.

Budget: close looks and review rounds are counted in the project's usage log and capped by the
analysis budget. Asking for more than the budget allows is refused with a plain message unless the
request says ``override``, so the operator stays in control of how much is handed to the AI.

226: all of it runs on the shared engine. Stills come from the one frame renderer and contact sheets
from its one sheet maker (the same pictures as before); the cut's sound is decoded by the one audio
decoder into the scratch folder and written down by the shared Whisper helper, with the operator's
device, language and word list and the quick passes' model; the cut points hear their few seconds
through the shared Whisper loader, cut from the recording by the one-seek window decoder, and take
when the driver talks from the analysis. The camera layout is always the project's own.
"""

from __future__ import annotations

import array
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from .. import activity_timeline, cross_track_check, frame_render, voice_track, whisper_options
from ..frame_render import contact_sheets
from ..scratch import scratch_root
from .analysis import BUDGETS, SCRATCH_PREFIX, clock, STILL_WIDTH, STILL_WORKERS
from .privacy import build_full_frame_mask
from .project import (fixed_layout, read_json, record_usage, version_dir, version_recording, write_atomic,
                      write_json_atomic)
# 226: the editor's modules name the frame renderer's font option ``_font``; kept here for them.
from .render import _font  # noqa: F401
from .timeline import DEFAULT_LAYOUT, scene_length

REVIEW_STILL_INTERVAL = {"light": 12, "standard": 8, "thorough": 6}
# The cut's transcript, as the shared Whisper helper writes it in the scratch folder (226).
CUT_TRANSCRIPT_NAMES = {"json_name": "cut.transcript.json", "srt_name": "cut.transcript.srt",
                        "text_name": "cut.transcript.txt"}
WHISPER_MISSING = ("Whisper is not installed in this Python; run this command with the Python the backend uses "
                   "for transcription")
# A scene is pointed out when this much of it, or more than this share of it, is dead time (226).
DEAD_TIME_NOTE_SECONDS = 10.0
DEAD_TIME_NOTE_SHARE = 0.5


class BudgetExceeded(RuntimeError):
    pass


def _analysis(project: Path) -> dict[str, Any]:
    path = project / "analysis" / "analysis.json"
    if not path.exists():
        raise ValueError("run race-video-analyze first")
    return json.loads(path.read_text(encoding="utf-8"))


def _look_source(project: Path, analysis: dict[str, Any]) -> Path:
    """The recording a close look reads (242, Wave C2): the project's own, as ``project.json`` names it now, so a
    recording linked again where it moved is read where it is; the analysis's own source only for a project file
    that names none."""

    source = str(read_json(project / "project.json").get("source") or "").strip()
    return Path(source or analysis["source"])


def _used(project: Path, kind: str) -> int:
    meta = read_json(project / "project.json")
    return sum(e["count"] for e in meta.get("ai_usage", []) if e["kind"] == kind)


def ffmpeg_dir(ffmpeg: str) -> str:
    """The folder of the FFmpeg in use, so Whisper (which runs FFmpeg itself) finds the same one."""

    found = shutil.which(ffmpeg) or (ffmpeg if Path(ffmpeg).is_file() else "")
    return str(Path(found).resolve().parent) if found else ""


def quick_whisper_fields(whisper: dict[str, Any] | None) -> dict[str, Any]:
    """What a quick pass asks Whisper for besides the model (226): ``prefer_gpu``, ``language_code``,
    ``initial_prompt`` and ``glossary_entries``. The request handlers work them out (the request's
    settings first, then the operator's saved ones); a direct call without them reads the saved
    settings, read only."""

    if whisper is not None:
        return dict(whisper)
    saved = whisper_options.read_saved_settings()
    fields = whisper_options.from_settings(saved)
    prompt, entries = whisper_options.words(saved)
    return {"prefer_gpu": bool(fields["prefer_gpu"]), "language_code": str(fields["language_code"]),
            "initial_prompt": prompt, "glossary_entries": list(entries)}


def close_look(project: Path, start: float, end: float, step: float, panel: str, *, masks: dict[str, Path],
               ffmpeg: str = "ffmpeg", override: bool = False,
               region: list[int] | None = None, times: list[float] | None = None) -> dict[str, Any]:
    """A labelled, privacy-masked sheet of one panel between ``start`` and ``end``.

    ``region`` ([x, y, w, h] inside the panel, in recording pixels) zooms into part of the panel at full
    resolution, for example an on-screen position table that is unreadable in a whole-panel tile.

    226: the panels are the project's own layout (fixed at Prepare; an older project's analysis
    layout), never one from a request.
    """

    analysis = _analysis(project)
    budget = analysis["settings"]["budget"]
    cap = BUDGETS[budget]["close_look_images"]
    used = _used(project, "close-look sheets")
    if used >= cap and not override:
        raise BudgetExceeded(f"the {budget} budget allows {cap} close looks and {used} have been used; "
                             "ask the operator, or pass override")
    layout = fixed_layout(project) or DEFAULT_LAYOUT
    if panel not in layout["panels"]:
        raise ValueError(f"unknown panel '{panel}'")
    if times:
        if not region:
            raise ValueError("a list of times is for zoomed looks; give a region too")
        times = [round(float(t), 2) for t in times][:12]
    else:
        times = []
        t = float(start)
        while t <= float(end) + 1e-6 and len(times) < 36:
            times.append(round(t, 2))
            t += float(step)
    folder = project / "analysis" / "looks" / f"look-{used + 1:02d}"
    shutil.rmtree(folder, ignore_errors=True)   # never hand over pictures left by an unfinished look
    if region:
        px, py, pw, ph = (int(v) for v in layout["panels"][panel])
        rx, ry, rw, rh = (int(v) for v in region)
        if rx < 0 or ry < 0 or rw <= 0 or rh <= 0 or rx + rw > pw or ry + rh > ph:
            raise ValueError(f"region {region} is outside the {panel} panel ({pw}x{ph})")
        box = (px + rx, py + ry, rw // 2 * 2, rh // 2 * 2)
        mask = (build_full_frame_mask(ffmpeg, layout, masks, folder / "mask.png", layout["width"], layout["height"])
                if masks else None)
        times = times[:12]
        # At the recording's own resolution, blurred through the mask in the same run, with the time stamped.
        frame_render.render_stills(ffmpeg, _look_source(project, analysis), times, folder / "stills", crop=box, mask=mask,
                                   stamp=True, quality=3, workers=1, reuse=False)
        tile_w = 640
        tile_h = max(2, int(round(tile_w * box[3] / box[2] / 2)) * 2)
        sheets = contact_sheets(ffmpeg, folder / "stills", len(times), float(start), float(step),
                                (0, 0, box[2], box[3]), folder, tile=(tile_w, tile_h), columns=3, rows=4, label=False)
        record_usage(project, "close-look sheets", 1,
                     note=f"{panel} region {region} {clock(start)}-{clock(end)} every {step} s")
        return {"sheet": str(folder / sheets[0]["file"]), "times": times, "used": used + 1, "allowed": cap}
    height = int(round(STILL_WIDTH * layout["height"] / layout["width"] / 2) * 2)
    mask = build_full_frame_mask(ffmpeg, layout, masks, folder / "mask.png", STILL_WIDTH, height) if masks else None
    # 226: the analysis stills' settings, through the shared frame renderer (the same pictures).
    frame_render.render_stills(ffmpeg, _look_source(project, analysis), times, folder / "stills", scale=(STILL_WIDTH, height),
                               mask=mask, workers=STILL_WORKERS, reuse=False)
    sx = STILL_WIDTH / layout["width"]
    px, py, pw, ph = (int(v) for v in layout["panels"][panel])
    crop = (round(px * sx), round(py * sx), round(pw * sx) // 2 * 2, round(ph * sx) // 2 * 2)
    sheets = contact_sheets(ffmpeg, folder / "stills", len(times), float(start), float(step), crop, folder)
    record_usage(project, "close-look sheets", 1, note=f"{panel} {clock(start)}-{clock(end)} every {step} s")
    return {"sheet": str(folder / sheets[0]["file"]), "times": times, "used": used + 1, "allowed": cap}


# Dead time inside the edit (217, 226) -----------------------------------------------------------


def dead_time_in(start: float, end: float, activity: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The analysis's dead-time stretches that the recording's ``start``-``end`` overlaps, each with how
    many seconds of it fall inside (``inside``), which signal found it (``by``) and, when the picture
    found it, whether it stood still or went black (``kind``). [] without an analysis of dead time."""

    if not isinstance(activity, dict):
        return []
    found_by = activity.get("idle_by") or []
    kinds = activity.get("picture_kinds") or []
    hits = []
    for position, stretch in enumerate(activity.get("idle_stretches") or []):
        try:
            first, last = float(stretch[0]), float(stretch[1])
        except (IndexError, TypeError, ValueError):
            continue
        inside = min(float(end), last) - max(float(start), first)
        if inside <= 0:
            continue
        by = [str(signal) for signal in (found_by[position] if position < len(found_by) else []) or []]
        hits.append({"start": first, "end": last, "inside": inside,
                     "by": by or [activity_timeline.SIGNAL_GAME_AUDIO],
                     "kind": str(kinds[position] if position < len(kinds) else "")})
    return hits


def scene_idle(scene: dict[str, Any], activity: dict[str, Any] | None) -> tuple[float, list[str]]:
    """How many seconds of a scene are dead time, and which signals found that dead time."""

    hits = dead_time_in(float(scene["in"]), float(scene["out"]), activity)
    signals = {signal for hit in hits for signal in hit["by"]}
    order = [activity_timeline.SIGNAL_GAME_AUDIO, activity_timeline.SIGNAL_GAME_PICTURE]
    by = [signal for signal in order if signal in signals] + sorted(signals - set(order))
    return round(sum(hit["inside"] for hit in hits), 1), by


def _found_by(hit: dict[str, Any]) -> str:
    parts = []
    if activity_timeline.SIGNAL_GAME_PICTURE in hit["by"]:
        parts.append("picture black" if hit["kind"] == activity_timeline.PICTURE_BLACK else "picture still")
    if activity_timeline.SIGNAL_GAME_AUDIO in hit["by"]:
        parts.append("game sound quiet")
    return ", ".join(parts) or "no driving found"


def _seconds(value: float) -> str:
    return f"{value:.0f}" if value >= 10 else f"{value:.1f}".removesuffix(".0")


def dead_time_notes(timeline: dict[str, Any], activity: dict[str, Any] | None) -> list[str]:
    """One note per scene that sits in dead time: ``DEAD_TIME_NOTE_SECONDS`` or more of it, or more
    than half of it, for example "scene s07 (12:10-13:40) has 75 s inside dead time 12:00-14:20 (picture
    still, game sound quiet)". Notes only: the AI editor decides what stays (150)."""

    notes = []
    for scene in timeline.get("scenes") or []:
        try:
            start, end = float(scene["in"]), float(scene["out"])
        except (KeyError, TypeError, ValueError):
            continue
        hits = dead_time_in(start, end, activity)
        inside = sum(hit["inside"] for hit in hits)
        if not hits or (inside < DEAD_TIME_NOTE_SECONDS and inside <= (end - start) * DEAD_TIME_NOTE_SHARE):
            continue
        where = " and ".join(f"{clock(hit['start'])}-{clock(hit['end'])} ({_found_by(hit)})" for hit in hits)
        notes.append(f"scene {scene.get('id')} ({clock(start)}-{clock(end)}) has {_seconds(inside)} s inside dead time "
                     f"{where}")
    return notes


def pacing(timeline: dict[str, Any], activity: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Each scene's place in the cut, and (226) how many of its seconds are dead time in the recording
    (``idle_seconds``) with the signals that found it (``idle_by``): 0 and [] without that analysis."""

    rows, position = [], 0.0
    for index, scene in enumerate(timeline["scenes"]):
        if index and scene.get("transition_in") in ("dissolve", "dip"):
            position -= float(scene.get("transition_dur", 0.6))
        idle_seconds, idle_by = scene_idle(scene, activity)
        rows.append({"id": scene["id"], "at": round(position, 1), "length": scene_length(scene),
                     "beat": scene.get("beat", ""), "reason": scene.get("reason", ""),
                     "idle_seconds": idle_seconds, "idle_by": idle_by})
        position += scene_length(scene)
    return rows


def _hear_the_cut(ffmpeg: str, video: Path, model: str, fields: dict[str, Any]) -> str:
    """What a viewer hears in the rendered cut, as "[mm:ss] text" lines (226): its sound decoded by the
    one decoder into the scratch folder and written down by the shared Whisper helper, with real short
    reactions kept. Nothing is left behind."""

    try:
        from ...providers import whisper_local  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - depends on the operator's install
        raise RuntimeError(WHISPER_MISSING) from exc
    work = Path(tempfile.mkdtemp(prefix=f"{SCRATCH_PREFIX}{os.getpid()}_", dir=str(scratch_root())))
    try:
        wav = voice_track.extract_wav(ffmpeg, video, work / "cut-audio.wav", ffmpeg_map="0:a:0")
        folder = work / "transcript"
        try:
            whisper_local.transcribe_from_request({
                "audio_path": str(wav), "output_dir": str(folder), "model_name": str(model),
                "language_code": str(fields["language_code"]), "prefer_gpu": bool(fields["prefer_gpu"]),
                "narration_speech_mode": "Sparse", "initial_prompt": str(fields.get("initial_prompt") or ""),
                "glossary_entries": list(fields.get("glossary_entries") or []), "keep_short_reactions": True,
                "ffmpeg_dir": ffmpeg_dir(ffmpeg), **CUT_TRANSCRIPT_NAMES,
            })
        except ImportError as exc:  # pragma: no cover - depends on the operator's install
            raise RuntimeError(WHISPER_MISSING) from exc
        segments = json.loads((folder / CUT_TRANSCRIPT_NAMES["json_name"]).read_text(encoding="utf-8")).get("segments")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return "\n".join(f"[{clock(float(s['start']))}] {str(s.get('text') or '').strip()}" for s in segments or [])


def review_kit(project: Path, version: int, profile: str = "preview", *, ffmpeg: str = "ffmpeg",
               whisper_model: str = "small", transcribe: bool = True, override: bool = False,
               whisper: dict[str, Any] | None = None) -> dict[str, Any]:
    """Evidence for the editor's self-review of a rendered draft: sheets of the cut, pacing, what a viewer hears.

    226: ``whisper_model`` is the quick passes' model; ``whisper`` the rest of what Whisper is asked
    for (``quick_whisper_fields``). The pacing says which scenes sit in dead time.
    """

    analysis = _analysis(project)
    budget = analysis["settings"]["budget"]
    cap = BUDGETS[budget]["review_rounds"]
    used = _used(project, "review rounds")
    if used >= cap and not override:
        raise BudgetExceeded(f"the {budget} budget allows {cap} review rounds and {used} have been used; "
                             "ask the operator, or pass override")
    folder = version_dir(project, version)
    video = folder / "renders" / f"{profile}.mp4"
    if not video.exists():
        raise ValueError(f"render version {version} ({profile}) first")
    timeline = json.loads((folder / "timeline.json").read_text(encoding="utf-8"))
    out = folder / "review"
    out.mkdir(parents=True, exist_ok=True)
    step = REVIEW_STILL_INTERVAL[budget]
    rows = pacing(timeline, analysis.get("activity"))
    write_json_atomic(out / "pacing.json", rows)

    # The rendered video is already masked in every view, so its stills need no further blurring.
    # Each round takes them again: the version may have been rendered again since the last round.
    duration = sum(scene_length(s) for s in timeline["scenes"]) - sum(
        float(s.get("transition_dur", 0.6)) for i, s in enumerate(timeline["scenes"])
        if i and s.get("transition_in") in ("dissolve", "dip"))
    stills = out / "stills"
    shutil.rmtree(stills, ignore_errors=True)
    for old in out.glob("sheet-*.jpg"):
        old.unlink()
    times = [float(t) for t in range(0, int(duration), step)]
    frame_render.render_stills(ffmpeg, video, times, stills, scale=(1280, 720), workers=1, reuse=False)
    sheets = contact_sheets(ffmpeg, stills, len(times), 0.0, float(step), (0, 0, 1280, 720), out)

    heard = ""
    if transcribe:
        heard = _hear_the_cut(ffmpeg, video, whisper_model, quick_whisper_fields(whisper))
        write_atomic(out / "cut-transcript.txt", heard + "\n")
    record_usage(project, "review rounds", 1, version=version, note=f"{len(sheets)} sheets of the cut")
    record_usage(project, "review sheets", len(sheets), version=version)
    return {"sheets": [str(out / s["file"]) for s in sheets], "pacing": rows,
            "cut_transcript": str(out / "cut-transcript.txt") if heard else "", "round": used + 1, "allowed": cap}


STRADDLE_MARGIN = 0.15


def _voice_talk(project: Path, voice: int) -> tuple[set[int] | None, float | None]:
    """Seconds where the analysis heard the driver talking on ``voice``, and the level their microphone
    counts as talking above (176); (None, None) without an analysis of that track. 226: both come
    from the analysis (the shared voice activity), not measured again here. An analysis made before
    Wave 7 has the seconds but not the level: it is worked out from the analysis's loudness per second
    of that track, by the shared rule (``voice_track.talk_threshold_dbfs``)."""

    path = project / "analysis" / "analysis.json"
    if not path.exists():
        return None, None
    data = json.loads(path.read_text(encoding="utf-8"))
    analysed = next((int(t["ordinal"]) for t in data.get("tracks") or [] if t.get("role") == "voice"), None)
    if analysed is None or analysed != int(voice):
        return None, None
    talking = {second for span in data.get("talking") or [] for second in range(int(span["start"]), int(span["end"]))}
    threshold = data.get("voice_talk_threshold_dbfs")
    if threshold is None:
        threshold = voice_track.talk_threshold_dbfs((data.get("loudness_per_second") or {}).get(str(int(voice))))
    return talking, float(threshold) if threshold is not None else None


def level_at(wav: Path, offset: float, half: float = STRADDLE_MARGIN) -> float:
    """dB RMS of a 16-bit mono WAV in a short window around ``offset`` seconds into it (176)."""

    import wave  # noqa: PLC0415

    with wave.open(str(wav), "rb") as audio:
        rate = audio.getframerate()
        audio.setpos(min(audio.getnframes(), max(0, int((offset - half) * rate))))
        samples = array.array("h", audio.readframes(max(1, int(2 * half * rate))))
    if not samples:
        return -120.0
    rms = math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768
    return max(-120.0, 20 * math.log10(rms)) if rms > 0 else -120.0


def word_cut_by(words: list[dict[str, Any]], at: float, margin: float = STRADDLE_MARGIN) -> str:
    """The word a cut at ``at`` lands inside, or "". A word only counts when it clearly straddles the
    cut by ``margin`` seconds on both sides: word timings from Whisper vary by a few tenths."""

    for word in words:
        if word["start"] < at - margin and word["end"] > at + margin:
            return word["word"]
    return ""


def checked_edges(scenes: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str]]:
    """Scene edges where the sound is actually cut. An edge where one scene continues straight into the
    next (same source time, no transition) is a change of picture only, not a cut in the sound."""

    edges = []
    for index, scene in enumerate(scenes):
        if float((scene.get("audio") or {}).get("voice", 1.0)) <= 0:
            continue
        previous = scenes[index - 1] if index else None
        following = scenes[index + 1] if index + 1 < len(scenes) else None
        def voiced(other: dict[str, Any]) -> bool:
            return float((other.get("audio") or {}).get("voice", 1.0)) > 0

        continues_from = (previous is not None and abs(float(previous["out"]) - float(scene["in"])) < 0.05
                          and scene.get("transition_in", "cut") == "cut" and voiced(previous))
        continues_into = (following is not None and abs(float(scene["out"]) - float(following["in"])) < 0.05
                          and following.get("transition_in", "cut") == "cut" and voiced(following))
        if not continues_from:
            edges.append((scene, "in"))
        if not continues_into:
            edges.append((scene, "out"))
    return edges


def _word_listener(model: str, fields: dict[str, Any]) -> voice_track.Transcriber:
    """The shared Whisper loader's transcriber with each word's time (226)."""

    try:
        return voice_track.whisper_transcriber(str(model), bool(fields["prefer_gpu"]), str(fields["language_code"]),
                                               word_timestamps=True)
    except ImportError as exc:  # pragma: no cover - depends on the operator's install
        raise RuntimeError(WHISPER_MISSING) from exc


def cut_points(project: Path, version: int, *, ffmpeg: str = "ffmpeg", whisper_model: str = "small",
               window: float = 4.0, whisper: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Word timings around every scene start and end, so no cut lands inside a word or sentence.

    226: Whisper (``whisper_model``, the quick passes' model, and ``whisper``: see
    ``quick_whisper_fields``) is loaded only when an edge needs words; an edge where the analysis
    heard no talk does not. Each edge's few seconds are cut from the recording with one short seek.
    """

    timeline = json.loads((version_dir(project, version) / "timeline.json").read_text(encoding="utf-8"))
    # 267: the project's own recording, as a render reads it, never the path the timeline names.
    source = version_recording(project, timeline)
    voice = timeline["tracks"]["voice"]
    work = version_dir(project, version) / "review" / "cut-points"
    work.mkdir(parents=True, exist_ok=True)
    talking, threshold = _voice_talk(project, voice)
    extract = cross_track_check.ffmpeg_extractor(ffmpeg, source)
    listen: voice_track.Transcriber | None = None
    report = []
    for scene, edge in checked_edges(timeline["scenes"]):
        at = float(scene[edge])
        if talking is not None and not any(second in talking for second in range(int(at) - 1, int(at) + 2)):
            # The driver is not talking here; Whisper on a quiet microphone invents words.
            report.append({"scene": scene["id"], "edge": edge, "at": at, "cuts_a_word": "",
                           "words_before": "", "words_after": "", "quiet": True})
            continue
        if listen is None:
            listen = _word_listener(whisper_model, quick_whisper_fields(whisper))
        start = max(0.0, at - window)
        wav = extract(int(voice), start, 2 * window, work / f"{scene['id']}-{edge}.wav")
        segments = listen(wav)
        words = [{"word": str(w["word"]).strip(), "start": round(start + float(w["start"]), 2),
                  "end": round(start + float(w["end"]), 2)}
                 for seg in segments for w in seg.get("words") or []]
        cut = word_cut_by(words, at)
        # 176: Whisper can stretch a word across seconds of silence. A cut where the microphone is
        # silent cannot clip a word, whatever the word timings say.
        silent = bool(cut) and threshold is not None and level_at(wav, at - start) <= threshold
        wav.unlink(missing_ok=True)
        before = [w["word"] for w in words if w["end"] <= at][-5:]
        after = [w["word"] for w in words if w["start"] >= at][:5]
        entry = {
            "scene": scene["id"], "edge": edge, "at": at,
            "cuts_a_word": "" if silent else cut,
            "words_before": " ".join(before), "words_after": " ".join(after),
        }
        if silent:
            entry["microphone_silent_at_cut"] = True
        report.append(entry)
    write_json_atomic(work / "cut-points.json", report)
    return report
