"""Request handlers for the ``race-video-*`` CLI commands (150).

The AI editor (Claude Code or Codex) and the Workbench drive the engine through these, with the
usual ``--request-file``/``--result-file`` JSON contract. A render always runs the technical check
afterwards and stores its result beside the render.

226: Prepare runs on the shared engine. It reads the recording once (every audio track, and the
game picture's keyframes in the same pass), picks the voice and game tracks by the shared Track roles
rule, writes the narration down with the operator's Whisper settings and word list, checks it against
the other tracks, listens for other voices on the game track and watches the race. It says how far it
has got at least every 10 seconds, and redoes a step only when what it depends on has changed: when
nothing has, it does not read the recording again at all. Everything that can refuse a run is checked
before its project folder is made, and a refused first run leaves no project behind. A run stopped from
the Workbench cannot clean up after itself, so the next Prepare, analysis, transcript or review kit
removes the work folder it left (``remove_scratch_leftovers``).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
from typing import Any, Callable

from .. import (cross_track_check, frame_render, recording_records, sparse_narration, speech_facts, voice_track,
                whisper_models, whisper_options)
from ..scratch import scratch_root
from ..spelling_words import SETTING_KEY as SPELLING_WORDS_KEY
from ..user_folders import temporary_folder_problem
from . import game_speech as game_speech_module
from .analysis import (
    NARRATION_STAMP_NAME,
    SCRATCH_PREFIX,
    analysis_is_current,
    analyze,
    clock,
    file_sha256,
    read_recording,
    silent_track_warnings,
)
from .library import EXPORT_REFUSES_VALIDATION, export_version, list_projects, reconcile, start_fresh_edit
from .privacy import default_store, load_masks
from .project import (
    LINK_HINT,
    add_version,
    binding,
    create_project,
    editor_layout,
    fixed_layout,
    layout_refusal,
    library_content,
    prepared_tracks,
    project_folder,
    project_recording,
    read_json,
    record_track_overrides,
    recording_block,
    recording_refusal,
    save_feedback,
    tracks_refusal,
    update_project,
    usage_report,
    version_dir,
    write_json_atomic,
)
from .prompt import build_prompt, describe
from .qc import check_video, expected_from_report, report_beside
from .render import (
    PROCESS_START_TOLERANCE,
    RenderOptions,
    process_alive,
    process_start_time,
    render_stem,
    render_version,
    validation_size as render_validation_size,
)
from .review import close_look, cut_points, dead_time_notes, ffmpeg_dir as _ffmpeg_dir, review_kit
from .timeline import DEFAULT_LAYOUT, validate_timeline

# The settings Prepare uses (226), by the payload key the Workbench page sends; missing from the
# payload, each comes from the operator's saved Workbench settings, under the saved key given here.
TRACK_ROLES_SETTING_KEY = "evidence_track_roles"
QUICK_MODEL_KEY = "race_video_quick_whisper_model"
ENGINE_SETTING_KEYS: dict[str, str] = {
    "track_roles": TRACK_ROLES_SETTING_KEY,
    "whisper_model": "whisper_model",
    "whisper_device": "whisper_device",
    "language": "language",
    "narration_speech_mode": "narration_speech_mode",
    SPELLING_WORDS_KEY: SPELLING_WORDS_KEY,
    QUICK_MODEL_KEY: QUICK_MODEL_KEY,
}
# The quick passes (other voices on the game track, finding the voice by listening) use this Whisper
# model unless the setting says otherwise; "main" means the main Whisper model (226, decision C).
QUICK_MODEL_DEFAULT = "small"
QUICK_MODEL_MAIN = "main"
# The cross-track check compares words with this model, as features 1 and 2 do.
CROSS_CHECK_MODEL = "base.en"
# Bump when the way the editor writes its narration down changes, so every stored one is redone.
NARRATION_RULES_VERSION = 1
NARRATION_NAMES = {"json_name": "narration.transcript.json", "srt_name": "narration.transcript.srt",
                   "text_name": "narration.transcript.txt"}

# Prepare's steps, in order, as the Workbench's Queue / Progress page shows them. 242 (Wave C2): a new video whose
# recording the library has not read starts with one more, before anything is written.
CONFIRMING = "Confirming which recording this is"
READING = "Reading the recording"
WRITING = "Writing down the narration"
CHECKING = "Checking the narration against the other tracks"
LISTENING = "Listening for other voices"
WATCHING = "Watching the race"
PREPARE_PHASES = (READING, WRITING, CHECKING, LISTENING, WATCHING)
# 226: while a step runs, its latest status line is sent again when nothing new was sent for this
# long, so the page hears from Prepare at least every 10 seconds (it warns after 30 s of silence).
PROGRESS_PULSE_SECONDS = 5.0
# How often the narration's progress file is looked at while Whisper writes it.
WHISPER_PROGRESS_SECONDS = 1.0


def _masks(payload: dict[str, Any]) -> dict[str, Path]:
    """The operator's stored masks, always, plus any masks the request adds (226, decision F).

    A request can add a mask for a camera that has none; it can never remove a stored mask or put
    another in its place, and it cannot name another mask store (``privacy_store`` is not read).
    """

    masks = load_masks(default_store())
    given = payload.get("privacy_masks")
    for panel, path in (given.items() if isinstance(given, dict) else ()):
        if path and str(panel) not in masks:
            masks[str(panel)] = Path(path)
    return masks


def _refuse_request_layout(payload: dict[str, Any], project: Path) -> None:
    """A request's ``layout`` that would move or miss a stored privacy mask is refused (226, decision
    F); the project's own layout is what every command uses."""

    if payload.get("layout") is not None:
        refusal = layout_refusal(project, payload["layout"], "the request's layout")
        if refusal:
            raise ValueError(refusal)


def _timeline(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("timeline"), dict):
        return payload["timeline"]
    if payload.get("timeline_path"):
        return json.loads(Path(payload["timeline_path"]).read_text(encoding="utf-8"))
    raise ValueError("give either 'timeline' or 'timeline_path'")


_PRINT_LOCK = threading.Lock()


def _progress(payload: dict[str, Any], phase: str, index: int, count: int, *, activity: str = "",
              state: str = "active", done: bool = False, completed: int | None = None,
              total: int | None = None) -> None:
    """One status line for the Workbench's Queue / Progress page, when the Workbench started this run.

    ``progress_label`` is the item the page shows in its queue; without it nothing is printed. With
    ``total``, the page shows how far the step has got (``completed`` of ``total``).
    """

    label = str(payload.get("progress_label") or "")
    if not label:
        return
    record = {"schema": "MM_PROGRESS_V1", "phase": phase, "phase_index": index, "phase_count": count,
              "source_name": label, "source_ordinal": 1, "source_total": 1, "source_completed": 1 if done else 0,
              "source_state": state, "source_terminal": done, "activity": activity or phase}
    if total:
        record.update({"progress_kind": "work_units", "completed": int(completed or 0), "total": int(total)})
    with _PRINT_LOCK:
        # One write, so a line another thread prints never lands inside it.
        print("MM_PROGRESS_V1 " + json.dumps(record) + "\n", end="", flush=True)


class _Pulse:
    """Prepare's status lines (226): each step's latest line is sent again, from a small thread, when
    nothing new was sent for ``PROGRESS_PULSE_SECONDS``, so a long step is never silent."""

    def __init__(self, payload: dict[str, Any], phases: tuple[str, ...] = PREPARE_PHASES) -> None:
        self.payload = payload
        self.phases = phases
        self._lock = threading.Lock()
        self._last: dict[str, Any] | None = None
        self._sent = time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def send(self, phase: str, activity: str = "", completed: int | None = None, total: int | None = None, *,
             state: str = "active", done: bool = False) -> None:
        line = {"phase": phase, "index": self.phases.index(phase) + 1, "count": len(self.phases),
                "activity": activity, "state": state, "done": done, "completed": completed, "total": total}
        with self._lock:
            self._last = None if done else line
            self._emit(line)

    def _emit(self, line: dict[str, Any]) -> None:
        _progress(self.payload, line["phase"], line["index"], line["count"], activity=line["activity"],
                  state=line["state"], done=line["done"], completed=line["completed"], total=line["total"])
        self._sent = time.monotonic()

    def _watch(self) -> None:
        while not self._stop.wait(min(1.0, max(0.01, PROGRESS_PULSE_SECONDS / 4))):
            with self._lock:
                if self._last is not None and time.monotonic() - self._sent >= PROGRESS_PULSE_SECONDS:
                    self._emit(self._last)

    def __enter__(self) -> "_Pulse":
        if self.payload.get("progress_label"):
            self._thread = threading.Thread(target=self._watch, name="race-video-progress", daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)


def _options(payload: dict[str, Any], phase: str = "Rendering", index: int = 1, count: int = 2) -> RenderOptions:
    """The render's options from a request. 226: ``export_quality`` (youtube, highest or smaller; left
    out, the project's choice, else the main setting) and, for a validation run only,
    ``validation_size`` ([width, height] of the final)."""

    return RenderOptions(
        ffmpeg=str(payload.get("ffmpeg") or "ffmpeg"),
        ffprobe=str(payload.get("ffprobe") or "ffprobe"),
        masks=_masks(payload),
        encoder=str(payload.get("encoder") or "auto"),
        hwaccel=str(payload.get("hwaccel") or "auto"),
        on_progress=lambda message: _progress(payload, phase, index, count, activity=message),
        export_quality=str(payload.get("export_quality") or ""),
        validation_size=render_validation_size(payload.get("validation_size")),
    )


# The settings Prepare uses (226) --------------------------------------------------------------


def engine_settings(payload: dict[str, Any]) -> dict[str, Any]:
    """The settings Prepare uses, by their payload keys (``ENGINE_SETTING_KEYS``): the Track roles text
    ("2=narration,3=game"), the Whisper model, device, language and narration speech mode, the words to
    spell right, and the quick passes' model. A key in the payload wins (the Workbench page sends them;
    so do the tests); a missing one comes from the operator's saved Workbench settings, read only (an
    AI editor's own run). An older page's ``model_name`` stands for the Whisper model."""

    settings: dict[str, Any] = {}
    saved: dict[str, Any] | None = None
    for key, saved_key in ENGINE_SETTING_KEYS.items():
        if key in payload:
            settings[key] = payload[key]
            continue
        if key == "whisper_model" and payload.get("model_name"):
            settings[key] = payload["model_name"]
            continue
        if saved is None:
            saved = whisper_options.read_saved_settings()
        if saved_key in saved:
            settings[key] = saved[saved_key]
    return settings


def quick_model(settings: dict[str, Any], fields: dict[str, Any]) -> str:
    """The quick passes' Whisper model: the setting, "small" by default, the main model for "main"."""

    chosen = str(settings.get(QUICK_MODEL_KEY) or "").strip() or QUICK_MODEL_DEFAULT
    return str(fields["model_name"]) if chosen.casefold() == QUICK_MODEL_MAIN else chosen


def _quick_whisper(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """The quick passes' Whisper model and what else it is asked for, for the review kit and the cut
    points (226, decision C): the request's settings first, then the operator's saved ones; the
    model is the quick passes' setting ("small" unless set), or the request's own ``whisper_model``,
    which these two commands have always taken."""

    settings = engine_settings(payload)
    fields = whisper_options.from_settings(settings)
    prompt, entries = whisper_options.words(settings)
    model = str(payload.get("whisper_model") or "").strip() or quick_model(settings, fields)
    return model, {"prefer_gpu": bool(fields["prefer_gpu"]), "language_code": str(fields["language_code"]),
                   "initial_prompt": prompt, "glossary_entries": list(entries)}


def _words_sha256(prompt: str, entries: list[str]) -> str:
    text = json.dumps({"prompt": prompt, "entries": list(entries)}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def narration_stamp(fields: dict[str, Any], prompt: str, entries: list[str], voice: int,
                    compared: list[int]) -> dict[str, Any]:
    """What the narration transcript is written with (226). Prepare writes it again only when this
    changes: the rules, the Whisper model, language, device choice and speech mode, the word list, the
    voice track, the tracks it is checked against, and the short-reaction option."""

    return {"rules": NARRATION_RULES_VERSION, "model": str(fields["model_name"]), "language": str(fields["language_code"]),
            "prefer_gpu": bool(fields["prefer_gpu"]), "speech_mode": str(fields["narration_speech_mode"]),
            "words": _words_sha256(prompt, entries), "voice": int(voice), "compared": sorted(int(o) for o in compared),
            "keep_short_reactions": True}


def _whisper_request(wav: Path, folder: Path, fields: dict[str, Any], prompt: str, entries: list[str], ffmpeg: str,
                     progress_file: Path | None = None) -> dict[str, Any]:
    """The narration's request to the shared Whisper helper: the operator's Whisper settings and word
    list (the hint and the corrections), real short reactions kept (226, the editor only), and its
    progress as work units when there is a progress file."""

    request = {
        "audio_path": str(wav), "output_dir": str(folder), "model_name": str(fields["model_name"]),
        "language_code": str(fields["language_code"]), "prefer_gpu": bool(fields["prefer_gpu"]),
        "narration_speech_mode": str(fields["narration_speech_mode"]), "initial_prompt": prompt,
        "glossary_entries": list(entries), "keep_short_reactions": True, "ffmpeg_dir": _ffmpeg_dir(ffmpeg),
        **NARRATION_NAMES,
    }
    if progress_file is not None:
        request.update({"progress_file": str(progress_file), "progress_work_units": True})
    return request


def _refuse_output_folder(output_root: Path) -> None:
    """The one output-folder rule (226: in core too, so an AI editor's own run keeps it): never a
    temporary folder, never the drive that holds the recordings."""

    problem = temporary_folder_problem(str(output_root), "folder for edited videos")
    if problem:
        raise ValueError(problem)


class _ProjectRun:
    """The project a run works in (226): ``payload["project"]``, or the one for the recording under
    ``payload["output_root"]`` (the output-folder rule checked first). ``folder`` is where it is, made
    or not, so everything that can refuse the run is checked before ``create`` makes it. A project this
    run made is removed again when the run stops with an error before ``keep`` is called, so a refused
    run leaves no empty project for the page to list."""

    def __init__(self, payload: dict[str, Any], source: Path) -> None:
        self.source = source
        self.name = payload.get("name")
        self.output_root: Path | None = None
        if payload.get("project"):
            self.folder = Path(payload["project"])
        else:
            self.output_root = Path(payload["output_root"])
            _refuse_output_folder(self.output_root)
            self.folder = project_folder(self.output_root, source, self.name)
        self._made = False
        self._parent_made = False

    def create(self, recording: dict[str, Any] | None = None) -> Path:
        if self.output_root is not None:
            self._parent_made = not self.folder.parent.exists()
            made = not self.folder.exists()
            self.folder = create_project(self.output_root, self.source, self.name, recording=recording)
            self._made = made
        return self.folder

    def keep(self) -> None:
        """The run has stored what it decided: the project stays, whatever happens next."""

        self._made = False

    def __enter__(self) -> "_ProjectRun":
        return self

    def __exit__(self, exc_type: Any, *_exc: Any) -> None:
        if exc_type is not None and self._made:
            shutil.rmtree(self.folder, ignore_errors=True)
            if self._parent_made:
                with contextlib.suppress(OSError):
                    self.folder.parent.rmdir()   # only when empty


def validate_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    timeline = _timeline(payload)
    duration = payload.get("source_duration")
    return {"problems": validate_timeline(timeline, source_duration=float(duration) if duration else None)}


def _titles(streams: list[dict[str, Any]]) -> dict[int, str]:
    return {index: str((stream.get("tags") or {}).get("title") or "") for index, stream in enumerate(streams)}


def _refuse_timeline_tracks(timeline: dict[str, Any], streams: list[dict[str, Any]], settings: dict[str, Any],
                            *, prepared_game: bool = False) -> None:
    """226 (decision A), whether or not the project was prepared: a timeline may not use the full mix or a
    track that is never narration as the voice, nor the full mix or a track named as never the game
    (music, a spotter, an engineer, voice chat) as the game sound. By the track names and Track roles.
    Without a game track a Prepare fixed (``prepared_game``), nor a track the Narration track setting
    sets as Never narration when it names the game track (``setting_game_refusal``)."""

    known = _Tracks(_titles(streams), voice_track.roles_from_text(settings.get("track_roles")))
    tracks = timeline.get("tracks") if isinstance(timeline.get("tracks"), dict) else {}
    checks = [("voice", known.voice_problem), ("game", known.game_problem)]
    if not prepared_game:
        checks.append(("game", known.setting_game_problem))
    for name, problem in checks:
        ordinal = tracks.get(name)
        if isinstance(ordinal, int) and not isinstance(ordinal, bool) and ordinal in known.titles and problem(ordinal):
            raise ValueError(f"This timeline's {'voice' if name == 'voice' else 'game'} track cannot be used: "
                             f"{problem(ordinal)}")


def add_version_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Store a version. 226: ``editor_label`` is the AI editor's own name for it (its tool and model),
    and ``notes`` in the result point out each scene that sits in dead time; notes, never a refusal.
    The recording's tracks are probed (the shared probe) and a voice or game track that can never be
    one is refused, prepared project or not. 267: for a project that exists, the recording probed is
    the project's own, once the timeline's source is checked to be it (``recording_refusal``)."""

    timeline = _timeline(payload)
    source = Path(timeline["source"])
    ffprobe = str(payload.get("ffprobe") or "ffprobe")
    with _ProjectRun(payload, source) as run:
        if (run.folder / "project.json").is_file():
            refusal = recording_refusal(run.folder, source)
            if refusal:
                raise ValueError(refusal)
            source = project_recording(run.folder)
            timeline = dict(timeline, source=str(source))
        # Other tracks than the prepared ones: that refusal says which tracks to use instead.
        refusal = tracks_refusal(run.folder, timeline.get("tracks"))
        if refusal:
            raise ValueError(refusal)
        streams: list[dict[str, Any]] | None = None
        duration = 0.0
        if source.exists():
            streams, duration = voice_track.probe_audio_streams(ffprobe, source)
            _refuse_timeline_tracks(timeline, streams, engine_settings(payload),
                                    prepared_game="game" in prepared_tracks(run.folder))
        # 242 (Wave C2 review): a video this command makes is bound to its recording, as Prepare binds one.
        project = run.create(None if (run.folder / "project.json").is_file() else recording_block(source))
        number = add_version(project, timeline, story=str(payload.get("story") or ""),
                             answers=str(payload.get("answers") or ""), parent=payload.get("parent"),
                             source_duration=duration or None, audio_streams=None if streams is None else len(streams),
                             editor_label=str(payload.get("editor_label") or ""))
    activity = _read_json(project / "analysis" / "analysis.json").get("activity")
    index_quietly(project)
    return {"project": str(project), "version": number, "folder": str(version_dir(project, number)),
            "notes": dead_time_notes(timeline, activity)}


def render_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Render a version and check it. 226: a validation run's final (``validation_size``) is written as
    ``final-<w>x<h>.mp4``, with its own report and check (``qc-final-<w>x<h>.json``)."""

    project, version = Path(payload["project"]), int(payload["version"])
    profile = str(payload.get("profile") or "preview")
    _refuse_request_layout(payload, project)
    options = _options(payload)
    _progress(payload, "Rendering", 1, 2)
    report = render_version(project, version, profile, options)
    _progress(payload, "Checking the video", 2, 2)
    qc = check_video(Path(report["output"]), profile, expected_duration=report["expected_duration"],
                     ffmpeg=options.ffmpeg, ffprobe=options.ffprobe, expected=expected_from_report(report))
    write_json_atomic(version_dir(project, version) / "renders" / f"qc-{render_stem(profile, options)}.json", qc)
    _progress(payload, "Checking the video", 2, 2, state="completed", done=True,
              activity="Checked" if qc["passed"] else "Made, but it failed the technical check")
    index_quietly(project)
    return {"render": report, "technical_check": qc}


def check_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """The technical check of one file. 226: the frame size and rate it must have come from the
    request (``expected``: width, height, fps), else from the render report beside the file when it
    describes that file, else from the profile."""

    expected = payload.get("expected_duration")
    path, profile = Path(payload["path"]), str(payload.get("profile") or "final")
    given = payload.get("expected") if isinstance(payload.get("expected"), dict) else {}
    return check_video(path, profile, expected_duration=float(expected) if expected else None,
                       ffmpeg=str(payload.get("ffmpeg") or "ffmpeg"), ffprobe=str(payload.get("ffprobe") or "ffprobe"),
                       expected={**expected_from_report(report_beside(path, profile)), **given})


def feedback_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    path = save_feedback(Path(payload["project"]), int(payload["version"]), str(payload["text"]))
    index_quietly(Path(payload["project"]))
    return {"feedback_path": str(path)}


def _tools(payload: dict[str, Any]) -> tuple[str, str]:
    return str(payload.get("ffmpeg") or "ffmpeg"), str(payload.get("ffprobe") or "ffprobe")


def analyze_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Create or reopen the project for a recording and build its analysis.

    226: the recording is read through the shared decode. The layout is the project's fixed one; a
    request's layout is used only for a project that has none yet, and one that would move or miss a
    stored privacy mask is refused. The tracks (decision A): a project with tracks in ``project.json``
    uses them, and a request naming other ones is refused; for a project without, the request's tracks
    are checked as Prepare checks them (never the full mix, never a track that cannot be the voice or the
    game sound) and stored as chosen ("override"). With no tracks anywhere, an older analysis's voice and
    game roles are kept. A refusal comes before a new project folder is made.

    242 (Wave C2, design 2.7): for a project that exists, the request's ``source`` is a claim, checked as
    add-version checks it (``recording_refusal``), and the analysis is built from the project's own recording.
    """

    remove_scratch_leftovers()
    ffmpeg, ffprobe = _tools(payload)
    source = Path(payload["source"])
    with _ProjectRun(payload, source) as run:
        if (run.folder / "project.json").is_file():
            refusal = recording_refusal(run.folder, source, "the request's source")
            if refusal:
                raise ValueError(refusal)
            source = project_recording(run.folder)
        _refuse_request_layout(payload, run.folder)
        settings = engine_settings(payload)
        meta = _read_json(run.folder / "project.json")
        stored = meta.get("tracks") if isinstance(meta.get("tracks"), dict) else {}
        stored = stored if any(isinstance(stored.get(name), int) for name in ("voice", "game")) else {}
        given = _given_tracks(payload.get("tracks"))
        chosen: dict[str, Any] = {}
        if stored:
            if any(stored.get(name) != value for name, value in given.items()):
                raise ValueError(tracks_refusal(run.folder, {**{name: stored.get(name) for name in ("voice", "game")},
                                                             **given}, "this request"))
            tracks: dict[str, Any] | None = dict(stored)
        elif given:
            streams, _duration = voice_track.probe_audio_streams(ffprobe, source)
            known = _Tracks(_titles(streams), voice_track.roles_from_text(settings.get("track_roles")))
            voice, game = (_chosen(given, name, len(streams)) for name in ("voice", "game"))
            _refuse_choice(known, voice, game)
            for name, ordinal in (("voice", voice), ("game", game)):
                if ordinal is not None:
                    chosen.update({name: ordinal, f"{name}_decided_by": "override"})
            tracks = chosen
        else:
            tracks = prepared_tracks(run.folder) or None
        # 242 (Wave C2 review): a video this command makes is bound to its recording, as Prepare binds one.
        project = run.create(None if (run.folder / "project.json").is_file() else recording_block(source))
        if chosen:
            update_project(project, tracks=chosen)
            record_track_overrides(project, chosen)
        transcript = Path(payload["transcript"]) if payload.get("transcript") else None
        game_speech = Path(payload["game_speech"]) if payload.get("game_speech") else None
        data = analyze(project, source, budget=str(payload.get("budget") or "standard"),
                       tracks=tracks, layout=fixed_layout(project) or payload.get("layout") or DEFAULT_LAYOUT,
                       story_panel=str(payload.get("story_panel") or "center"), masks=_masks(payload),
                       transcript=transcript, game_speech=game_speech, ffmpeg=ffmpeg, ffprobe=ffprobe,
                       on_progress=lambda activity, done, total: _progress(
                           payload, "Watching the race", 3, 3, activity=activity, completed=done, total=total),
                       track_roles=settings.get("track_roles"))
    index_quietly(project)
    return {"project": str(project), "digest": str(project / "analysis" / "digest.md"),
            "sheets": [s["file"] for s in data["sheets"]], "privacy_masked": data["privacy_masked"]}


def transcribe_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Transcribe the narration track with the local Whisper helper (run with the Whisper Python).

    226: with the operator's Whisper settings and word list, and through the same checks as Prepare's
    narration (decision B, ``_check_narration``): against the tracks Prepare compares (the track names,
    the Track roles and the prepared game track; the tracks with sound, when a Prepare has measured
    them), with each line's moments read by one short seek into the recording. The voice track is
    ``voice`` (0-based), else the prepared one; it is decoded on its own into the scratch folder. The
    transcript's stamp is written, so the next Prepare uses it while its settings match.
    """

    from ...providers import whisper_local  # noqa: PLC0415

    remove_scratch_leftovers()
    ffmpeg, ffprobe = _tools(payload)
    project = Path(payload["project"])
    meta = read_json(project / "project.json")
    source = Path(meta["source"])
    folder = project / "analysis" / "transcript"
    settings = engine_settings(payload)
    fields = whisper_options.from_settings(settings)
    prompt, entries = whisper_options.words(settings)
    streams, _duration = voice_track.probe_audio_streams(ffprobe, source)
    known = _Tracks(_titles(streams), voice_track.roles_from_text(settings.get("track_roles")))
    prepared = prepared_tracks(project)
    asked = payload.get("voice")
    voice = _chosen({"voice": prepared.get("voice") if asked is None or asked == "" else asked}, "voice", len(streams))
    if voice is None:
        raise ValueError("Say which track is your voice (\"voice\": 0 is Track 1): this project has no prepared "
                         "voice track.")
    sounding = meta.get("sounding")
    compared = _compared_tracks(known, voice, prepared.get("game"),
                                {int(o) for o in sounding} if isinstance(sounding, list) else None)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / NARRATION_STAMP_NAME).unlink(missing_ok=True)
    work = _scratch_folder()
    try:
        # 214: the one narration-audio decoder every feature uses (the same bytes as before).
        wav = voice_track.extract_track(ffmpeg, source, voice, work / "narration.wav")
        whisper_local.transcribe_from_request(_whisper_request(wav, folder, fields, prompt, entries, ffmpeg))
        _check_narration(folder / NARRATION_NAMES["json_name"], source=source, voice=voice, compared=compared,
                         titles=known.titles, extractor=cross_track_check.ffmpeg_extractor(ffmpeg, source),
                         prefer_gpu=bool(fields["prefer_gpu"]),
                         stamp=narration_stamp(fields, prompt, entries, voice, compared))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"transcript": str(folder / NARRATION_NAMES["json_name"])}


def look_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    ffmpeg, _ = _tools(payload)
    project = Path(payload["project"])
    _refuse_request_layout(payload, project)
    return close_look(project, float(payload["start"]), float(payload["end"]),
                      float(payload.get("step") or 1), str(payload.get("panel") or "center"),
                      masks=_masks(payload), ffmpeg=ffmpeg, override=bool(payload.get("override")),
                      region=payload.get("region"), times=payload.get("times"))


def review_kit_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    remove_scratch_leftovers()
    ffmpeg, _ = _tools(payload)
    project = Path(payload["project"])
    _refuse_request_layout(payload, project)
    transcribe = bool(payload.get("transcribe", True))
    model, whisper = _quick_whisper(payload) if transcribe else ("small", None)
    return review_kit(project, int(payload["version"]), str(payload.get("profile") or "preview"),
                      ffmpeg=ffmpeg, whisper_model=model, transcribe=transcribe,
                      override=bool(payload.get("override")), whisper=whisper)


def cut_points_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    ffmpeg, _ = _tools(payload)
    model, whisper = _quick_whisper(payload)
    report = cut_points(Path(payload["project"]), int(payload["version"]), ffmpeg=ffmpeg,
                        whisper_model=model, whisper=whisper)
    return {"cut_points": report, "cuts_inside_a_word": [r for r in report if r["cuts_a_word"]]}


def usage_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    return usage_report(Path(payload["project"]))


def prompt_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    project = Path(payload["project"])
    version = payload.get("feedback_version")
    tool = str(payload.get("tool") or "claude")
    text = build_prompt(project, tool=tool, python=str(payload["python"]), model=str(payload.get("model") or ""),
                        src_root=Path(payload["src_root"]), feedback_version=int(version) if version else None)
    return {"prompt": text, **describe(project, {tool: str(payload.get("model") or "")})}


RETIRED_SAVE_MASK = ("race-video-save-mask no longer works from the command line: only the operator draws "
                     "privacy masks, in the Workbench (AI Video Editor > Video settings > Privacy masks…). No mask "
                     "was changed.")
RETIRED_PANEL_STILL = ("race-video-panel-still no longer works from the command line: an unblurred camera "
                       "picture is only for the operator's mask editor in the Workbench. No picture was taken.")


def save_mask_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Retired (226, decision F): an agent could overwrite the operator's masks with it."""

    raise ValueError(RETIRED_SAVE_MASK)


def projects_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    return {"projects": list_projects(Path(payload["output_root"]))}


def export_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Render an approved version at its export quality and place it in the project's export folder.

    226: ``validation_size`` is refused here; a validation render is ``race-video-render``'s."""

    if payload.get("validation_size") not in (None, "", []):
        raise ValueError(EXPORT_REFUSES_VALIDATION)
    _refuse_request_layout(payload, Path(payload["project"]))
    _progress(payload, "Rendering the export", 1, 1)
    result = export_version(Path(payload["project"]), int(payload["version"]),
                            _options(payload, "Rendering the export", 1, 1))
    _progress(payload, "Rendering the export", 1, 1, state="completed", done=True,
              activity="Exported and checked" if result["export"] else "Not exported: it failed the technical check")
    index_quietly(Path(payload["project"]))
    return result


def panel_still_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Retired (226, decision F): it wrote an unblurred camera picture into the project the AI reads.
    The mask editor takes its still in-process, into the app's temporary folder."""

    raise ValueError(RETIRED_PANEL_STILL)


# Choosing the tracks (226, decision A) ---------------------------------------------------------


class _Tracks:
    """The recording's tracks as the shared rules see them: their names, the Track roles setting, and
    each track's role from those (names first, then the setting)."""

    def __init__(self, titles: dict[int, str], roles_value: dict[str, str]) -> None:
        self.titles = titles
        self.roles_value = roles_value
        self.source, self.roles = voice_track.track_roles(titles, voice_track.parse_track_roles(roles_value))
        mixes = {ordinal for ordinal, role in self.roles.items() if role == voice_track.ROLE_FULL_MIX}
        named_mix = voice_track.full_mix_track(titles, setting_value=roles_value)
        self.full_mixes = mixes | ({named_mix} if named_mix is not None else set())

    def number(self, ordinal: int) -> str:
        title = self.titles.get(ordinal, "")
        return f'Track {ordinal + 1} ("{title}")' if title else f"Track {ordinal + 1}"

    def why(self, ordinal: int) -> str:
        if self.source == voice_track.DECIDED_BY_NAME:
            return f'its name, "{self.titles.get(ordinal, "")}", says so'
        return "your Narration track setting says so"

    def voice_problem(self, ordinal: int) -> str:
        if ordinal in self.full_mixes:
            return (f"{self.number(ordinal)} is the full mix, which carries every sound ({self.why(ordinal)}), "
                    "so it cannot be your voice.")
        if self.roles.get(ordinal) == voice_track.ROLE_NEVER:
            return f"{self.number(ordinal)} is never narration ({self.why(ordinal)}), so it cannot be your voice."
        return ""

    def game_problem(self, ordinal: int) -> str:
        if ordinal in self.full_mixes:
            return (f"{self.number(ordinal)} is the full mix, which carries every sound, your voice too, so it "
                    "cannot be the game sound.")
        if voice_track.not_game_audio_name(self.titles.get(ordinal, "")):
            return (f"{self.number(ordinal)} is named as sound that is never the game (music, a spotter, an engineer "
                    "or voice chat), so it cannot be the game sound: it must never reach a video as the game.")
        return ""

    def setting_game_problem(self, ordinal: int) -> str:
        return setting_game_refusal(self.titles, self.roles_value, ordinal)

    def narration(self) -> list[int]:
        return [ordinal for ordinal in sorted(self.roles) if self.roles[ordinal] == voice_track.ROLE_NARRATION]


def setting_game_refusal(titles: dict[int, str], track_roles: Any, game: int | None) -> str:
    """Why ``game`` (0-based), picked by hand as the game sound, is refused by the Narration track
    setting, or "" (226, decision A: a music, spotter or full-mix track never reaches a video).

    When the setting names this recording's game track, a track it sets as Never narration is not the
    game sound (it may be music). A setting with no game role keeps the older meaning: settings made
    before Wave 6 used Never narration for the game track. Track names that say what the tracks carry
    come first, as they do for every role, so then the setting is not asked. The page asks the same.
    """

    if game is None:
        return ""
    value = voice_track.roles_from_text(track_roles)
    setting = voice_track.parse_track_roles(value)
    source, _roles = voice_track.track_roles(titles, setting)
    games = voice_track.parse_game_tracks(value)
    named = sorted(games & set(titles))
    never = {ordinal for ordinal, role in setting.items() if role == voice_track.ROLE_NEVER} - games
    if source != voice_track.DECIDED_BY_SETTING or not named or game not in never:
        return ""
    tracks = [f"Track {ordinal + 1}" for ordinal in named]
    return (f"Track {game + 1} is set as Never narration in your Narration track setting (it may be music), and the "
            f"setting names {' and '.join(tracks)} as your game sound; choose {' or '.join(tracks)}, or change "
            "the setting.")


def _chosen(tracks: Any, name: str, count: int) -> int | None:
    """The track the request chose as ``name`` (0-based), or None for Auto."""

    value = (tracks or {}).get(name) if isinstance(tracks, dict) else None
    if value is None or value == "":
        return None
    try:
        ordinal = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"tracks.{name} must be an audio track number (0 for Track 1), not {value!r}.") from None
    if not 0 <= ordinal < count:
        raise ValueError(f"The recording has {count} audio track{'' if count == 1 else 's'}; there is no "
                         f"Track {ordinal + 1} to use as the {'voice' if name == 'voice' else 'game sound'}.")
    return ordinal


def _given_tracks(tracks: Any) -> dict[str, Any]:
    """The voice and game tracks a request names (0-based; a number in text counts), leaving out the
    ones it leaves to Auto."""

    given: dict[str, Any] = {}
    for name in ("voice", "game"):
        value = tracks.get(name) if isinstance(tracks, dict) else None
        if value is None or value == "":
            continue
        try:
            given[name] = int(value)
        except (TypeError, ValueError):
            given[name] = value
    return given


def _refuse_choice(known: _Tracks, voice: int | None, game: int | None) -> None:
    """A voice and game track chosen by hand that can never be used are refused, in plain words (226:
    a game track the Narration track setting sets as Never narration too, when it names the game track)."""

    if voice is not None and game is not None and voice == game:
        raise ValueError(f"Your voice and the game sound must be different tracks (both are Track {voice + 1}).")
    for ordinal, problem in ((voice, known.voice_problem), (game, known.game_problem),
                             (game, known.setting_game_problem)):
        if ordinal is not None and problem(ordinal):
            raise ValueError(problem(ordinal))


def _compared_tracks(known: _Tracks, voice: int, game: int | None, sounding: set[int] | None) -> list[int]:
    """The tracks the narration is checked against (decision B): every other track the names or the
    Track roles call never narration, and the game track; never a full mix, and never a track with no
    sound. ``sounding`` is the tracks with sound, from a read of the recording; without it (no read to
    say) every track counts as having sound."""

    heard = set(known.titles) if sounding is None else set(sounding)
    mix = voice_track.full_mix_track(known.titles, setting_value=known.roles_value, sounding=heard,
                                     narration_ordinal=voice)
    return [ordinal for ordinal in sorted(known.titles)
            if ordinal != voice and ordinal not in known.full_mixes and ordinal != mix and ordinal in heard
            and (known.roles.get(ordinal) == voice_track.ROLE_NEVER or ordinal == game)]


def _decided_text(decided_by: str) -> str:
    return "chosen on the page" if decided_by == "override" else voice_track.DECIDED_BY_TEXT.get(decided_by, decided_by)


def _scratch_folder() -> Path:
    return Path(tempfile.mkdtemp(prefix=f"{SCRATCH_PREFIX}{os.getpid()}_", dir=str(scratch_root())))


# The work folders the race-video commands make under the scratch folder (226): Prepare's, the analysis's
# and the review kit's (``SCRATCH_PREFIX``), and the game track's voices' (``..._game_``), each named with
# the process number of the run that made it and eight random characters.
_LEFTOVER = re.compile(rf"^{re.escape(SCRATCH_PREFIX)}(?:game_)?(\d+)_[a-z0-9_]{{8}}$")


def remove_scratch_leftovers() -> int:
    """Remove the work folders a stopped race-video run left behind (196, 226): Stop in the Workbench
    ends the run's processes at once, so its own clean-up never runs, and a Prepare's folder holds the
    decoded sound of every track (gigabytes for a long race). A folder whose run still goes on is left
    alone; a running process with that number that started after the folder was made is another program
    (Windows gives the numbers out again), so that folder goes too. Called at the start of Prepare, the
    analysis, the transcript and the review kit. Returns how many folders were removed."""

    removed = 0
    for folder in scratch_root().glob(f"{SCRATCH_PREFIX}*"):
        match = _LEFTOVER.match(folder.name)
        if match is None or not folder.is_dir():
            continue
        pid = int(match.group(1))
        if pid == os.getpid():
            continue
        if process_alive(pid):
            started = process_start_time(pid)
            try:
                info = folder.stat()
            except OSError:
                continue
            made = float(getattr(info, "st_birthtime", info.st_ctime))
            if started is None or started <= made + PROCESS_START_TOLERANCE:
                continue  # its run may still be using it
        shutil.rmtree(folder, ignore_errors=True)
        removed += int(not folder.exists())
    return removed


def _stamp_matches(path: Path, stamp: dict[str, Any]) -> bool:
    try:
        return json.loads(path.read_text(encoding="utf-8")) == stamp
    except (OSError, ValueError):
        return False


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _follow_whisper(progress_file: Path, pulse: _Pulse) -> tuple[threading.Event, threading.Thread]:
    """Turn the Whisper helper's progress file into status lines while it writes the narration down."""

    stop = threading.Event()

    def follow() -> None:
        last: tuple[Any, ...] | None = None
        while not stop.wait(WHISPER_PROGRESS_SECONDS):
            state = _read_json(progress_file)
            if not state:
                continue
            if state.get("progress_kind") == "work_units" and state.get("total"):
                done, total = int(state.get("completed") or 0), int(state["total"])
                line: tuple[Any, ...] = (f"{WRITING}: {done} of {total} stretches of speech", done, total)
            else:
                message = str(state.get("message") or "").strip()
                line = (f"{WRITING}: {message}" if message else WRITING, None, None)
            if line != last and not stop.is_set():
                pulse.send(WRITING, *line)
                last = line

    thread = threading.Thread(target=follow, name="race-video-whisper-progress", daemon=True)
    thread.start()
    return stop, thread


def _write_narration(*, wav: Path, folder: Path, source: Path, voice: int, compared: list[int], titles: dict[int, str],
                     wavs: dict[int, Path], fields: dict[str, Any], prompt: str, entries: list[str], ffmpeg: str,
                     stamp: dict[str, Any], pulse: _Pulse, work: Path) -> None:
    """The narration transcript from the decoded voice track, checked against the other tracks
    (decision B), with real short reactions kept only where a real line still anchors them."""

    from ...providers import whisper_local  # noqa: PLC0415

    folder.mkdir(parents=True, exist_ok=True)
    (folder / NARRATION_STAMP_NAME).unlink(missing_ok=True)
    print(f"Writing down the narration (track {voice + 1})...", flush=True)
    pulse.send(WRITING, f"{WRITING}: loading Whisper {fields['model_name']}")
    progress_file = work / "narration-progress.json"
    stop, follower = _follow_whisper(progress_file, pulse)
    try:
        whisper_local.transcribe_from_request(_whisper_request(wav, folder, fields, prompt, entries, ffmpeg, progress_file))
    finally:
        stop.set()
        follower.join(timeout=5)
    _check_narration(folder / NARRATION_NAMES["json_name"], source=source, voice=voice, compared=compared, titles=titles,
                     extractor=cross_track_check.wav_slice_extractor(wavs), prefer_gpu=bool(fields["prefer_gpu"]),
                     stamp=stamp, pulse=pulse)


def _check_narration(json_path: Path, *, source: Path, voice: int, compared: list[int], titles: dict[int, str],
                     extractor: Callable[[int, float, float, Path], Path], prefer_gpu: bool, stamp: dict[str, Any],
                     pulse: _Pulse | None = None) -> dict[str, Any]:
    """Decision B, once Whisper has written the narration down (226): the cross-track and near-silent
    checks against ``compared`` (each line's moments cut by ``extractor``), then the short-reaction
    re-check, so a reaction never hangs on a line those checks took out. The transcript is written again
    without the lines they drop, and its ``stamp`` is written last. Prepare (on the tracks of its one
    read) and ``race-video-transcribe`` (one short seek into the recording per line) both use it, so a
    narration is filtered the same way whichever wrote it."""

    print(f"{CHECKING} ({', '.join(f'Track {o + 1}' for o in compared) or 'its own level only'})...", flush=True)
    if pulse is not None:
        pulse.send(CHECKING)
    result = cross_track_check.check_from_request(
        {"source_path": str(source), "transcript_json_path": str(json_path), "detection": {"selected_ordinal": voice},
         "model_name": CROSS_CHECK_MODEL, "prefer_gpu": bool(prefer_gpu), "language_code": "en"},
        compare_tracks=[{"ordinal": o, "track_number": o + 1, "title": titles.get(o, "")} for o in compared],
        extractor=extractor,
        on_progress=None if pulse is None else
        (lambda done, total: pulse.send(CHECKING, f"{CHECKING}: {done} of {total} lines", done, total)))
    if result.get("dropped"):
        print(f"Left out {len(result['dropped'])} line(s) not said into your microphone.", flush=True)
    # A short reaction is kept only near a real line; the check may have taken that line out.
    raw = _read_json(json_path.with_name("narration.transcript.raw.json"))
    reactions = list(raw.get("short_reactions_kept") or [])
    if reactions:
        transcript = _read_json(json_path)
        kept, dropped = sparse_narration.reanchor_short_reactions(
            transcript.get("segments") or [], reactions, not_anchors=raw.get("rescued_segments") or [])
        if dropped:
            cross_track_check.rewrite_transcript(json_path, transcript, kept, dropped, {
                "short_reactions_kept_count": len(reactions) - len(dropped),
                "short_reactions_without_anchor_count": len(dropped),
            })
    write_json_atomic(json_path.parent / NARRATION_STAMP_NAME, stamp)
    return result


def _models_to_load(*, main: str, quick: str, find_voice: bool, write_narration: bool, compare: bool,
                    listen: bool) -> list[str]:
    """The Whisper models the rest of a Prepare loads, each only for a step it runs (installer plan, Stage 3, review
    M4): the quick passes' model to find the voice by listening and to hear other voices on the game track, the main
    model to write the narration down, and base.en to check its lines against the other tracks, when there are any."""

    models = [quick] if find_voice else []
    if write_narration:
        models += [main, CROSS_CHECK_MODEL] if compare else [main]
    return models + ([quick] if listen else [])




def _may_match(stored: Any, expected: dict[str, Any], unknown: set[str]) -> bool:
    """Whether a stored stamp is ``expected``, or can still turn out to be once the parts in ``unknown`` are known."""

    return (isinstance(stored, dict) and set(stored) == set(expected)
            and all(stored[key] == value for key, value in expected.items() if key not in unknown))


def prepare_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Everything the AI editor needs before it starts, in one run: the project, the narration's
    words, and the analysis. Each step says what it is doing on its own line, for the run's log.

    The words come from the local Whisper helper, so this runs in the Python that has Whisper
    installed. ``skip_transcript`` builds the analysis without them (it still shows when the
    driver talks).

    226: the recording is read once. The voice track is the one the request chose, else the one
    track the names or Track roles call narration, else found by listening; the game track is the one
    chosen, else the shared game-audio rule's. Both are kept in ``project.json`` with what decided
    them, with the layout, the recording's picture size and which tracks have sound; the ones the
    request chose are also kept in ``editor-settings.json``, so the page picks them again when the
    recording is chosen again (``record_track_overrides``). A track that can
    never be the voice or the game sound, or a first layout that would miss a masked camera, is refused,
    in plain words, before the recording is read and before a new project folder is made; a first
    Prepare refused later (no voice or game track found) removes the folder it made.

    The recording is not read at all when nothing it would be read for has changed: both tracks are
    fixed without listening (chosen, or by their names or the Track roles), the layout is stored, the
    narration and the game track's voices are stored with matching stamps (or this run skips them),
    and the stored analysis has the same stills settings and engine (``analysis_is_current``).

    A voice or game track with no sound for the whole recording is used as chosen, with a plain warning
    in the run's log, at the top of the digest and in the result's ``warnings``
    (``analysis.silent_track_warnings``).

    Installer plan, Stage 3 (review M4): every Whisper model the run will load (the main model, base.en for the
    cross-track check, the quick passes' model) is checked before the recording is read and before a new project
    folder is made, so a model not approved stops it at once with what to do. Only a model the run is sure to load
    is checked then; what only the read can tell (the tracks found by listening, a stored narration that may still
    fit) is checked again once it has, before the narration is written down.
    """

    remove_scratch_leftovers()
    ffmpeg, ffprobe = _tools(payload)
    source = Path(payload["source"])
    with _ProjectRun({"output_root": payload["output_root"], "name": payload.get("name")}, source) as run:
        skip_transcript = bool(payload.get("skip_transcript"))
        listen_for_voices = not skip_transcript and not payload.get("skip_game_speech")
        settings = engine_settings(payload)
        fields = whisper_options.from_settings(settings)
        prompt, entries = whisper_options.words(settings)
        quick = quick_model(settings, fields)
        budget = str(payload.get("budget") or "standard")
        story_panel = str(payload.get("story_panel") or "center")

        streams, duration = voice_track.probe_audio_streams(ffprobe, source)
        video = frame_render.probe_video(ffprobe, source)
        titles = _titles(streams)
        if len(streams) < 2:
            raise ValueError(f"The AI Video Editor needs your voice and the game sound on separate audio tracks; this "
                             f"recording has {len(streams)} audio track{'' if len(streams) == 1 else 's'}.")
        known = _Tracks(titles, voice_track.roles_from_text(settings.get("track_roles")))
        voice = _chosen(payload.get("tracks"), "voice", len(streams))
        game = _chosen(payload.get("tracks"), "game", len(streams))
        voice_by = game_by = "override"
        _refuse_choice(known, voice, game)
        # 264: the one rule. Your confirmed answer comes first; it is your pick, whichever screen you gave it on, but
        # an edit needs the voice on a track of its own, so one that can never be the voice stops here (design 2.5).
        stored = speech_facts.narration_answer(source, titles=titles, track_roles=known.roles_value) if voice is None else None
        if stored is not None and stored.decided_by == speech_facts.DECIDED_CONFIRMED:
            voice = int(stored.track) - 1
            if known.voice_problem(voice):
                raise ValueError(f"Choose the voice track: {known.voice_problem(voice)}")
        if voice is None and len(known.narration()) == 1:
            voice, voice_by = known.narration()[0], known.source
        if voice is None and stored is not None and stored.final and stored.track is not None \
                and not known.voice_problem(int(stored.track) - 1):
            voice, voice_by = int(stored.track) - 1, voice_track.DECIDED_BY_AUTO
        if voice is None and skip_transcript:
            raise ValueError("Choose the voice track: the track names and your Narration track setting do not say which "
                             "track is your voice, and finding it means listening with Whisper, which this run skips.")
        if game is None:
            # The shared rule's first steps, the track names and then the Track roles, need no listening.
            named, decided = voice_track.game_audio_track(titles, setting_value=known.roles_value, narration_ordinal=voice)
            if named is not None and decided in (voice_track.DECIDED_BY_NAME, voice_track.DECIDED_BY_SETTING):
                game, game_by = named, decided

        meta = _read_json(run.folder / "project.json")
        stored_analysis = _read_json(run.folder / "analysis" / "analysis.json")
        # The layout is fixed at the project's first Prepare (a project prepared before Wave 7 keeps the
        # one its analysis used): every later Prepare and every command uses it.
        stored_layout = (meta.get("layout") if isinstance(meta.get("layout"), dict) else None) or \
            (stored_analysis.get("layout") if isinstance(stored_analysis.get("layout"), dict) else None)
        if stored_layout is None:
            # 226 (decision F): the first Prepare fixes the request's layout, so it may not move or miss a
            # camera the operator has masked (the masks are drawn on the editor's three-screen layout).
            _refuse_request_layout(payload, run.folder)
        layout = stored_layout or payload.get("layout") or editor_layout()
        picture = {"width": int(video.get("width") or 0), "height": int(video.get("height") or 0),
                   "avg_frame_rate": str(video.get("frame_rate_text") or ""),
                   "r_frame_rate": str(video.get("r_frame_rate_text") or "")}
        masks = _masks(payload)
        # The project's folder, made or not (``run.create`` makes this one): what it stores decides what this run does.
        folder = run.folder / "analysis" / "transcript"
        transcript = folder / NARRATION_NAMES["json_name"]
        game_speech = folder / "game.speech.json"

        def voices_stamp(have_words: bool) -> dict[str, Any]:
            return game_speech_module.stamp(
                model_name=quick, language=str(fields["language_code"]), prefer_gpu=bool(fields["prefer_gpu"]),
                track=int(game), narration_sha256=file_sha256(transcript) if have_words else "")

        def stored_steps(compared: list[int]) -> tuple[bool, bool]:
            # Whether the narration and the game track's voices are stored with the stamps this run would give.
            have_words = transcript.exists() and _stamp_matches(folder / NARRATION_STAMP_NAME,
                                                                 narration_stamp(fields, prompt, entries, voice, compared))
            return have_words, game_speech.exists() and game_speech_module.stored_stamp(game_speech) == voices_stamp(have_words)

        # Can everything be reused as it is, so the recording need not be read?
        reuse: tuple[bool, bool] | None = None
        sounding_stored = meta.get("sounding")
        if (voice is not None and game is not None and voice != game and stored_layout is not None
                and isinstance(sounding_stored, list)):
            tracks = {"voice": voice, "game": game, "voice_decided_by": voice_by, "game_decided_by": game_by}
            have_words, have_heard = stored_steps(_compared_tracks(known, voice, game, {int(o) for o in sounding_stored}))
            if ((skip_transcript or have_words) and (not listen_for_voices or have_heard)
                    and analysis_is_current(run.folder, budget=budget, tracks=tracks, layout=layout,
                                            story_panel=story_panel, masks=masks,
                                            transcript=transcript if have_words else None,
                                            game_speech=game_speech if have_heard else None)):
                reuse = (have_words, have_heard)
        if reuse is None and not skip_transcript:
            # Stage 3 (review M4): the models this run is sure to load, before anything is read or made. The tracks the
            # narration is checked against come from the stored sounding (else every track counts as having sound).
            # While a track is still to be found by the read, a stored narration or stored other voices that may still
            # fit are counted as kept (the check after the read sees whether they are), and a narration written again
            # counts as checked against the game track, which it is whenever the game track has sound.
            sounding = {int(o) for o in sounding_stored} if isinstance(sounding_stored, list) else None
            fixed = voice is not None and game is not None
            compared = _compared_tracks(known, voice, game, sounding) if fixed else []
            keep_words = transcript.exists() and _may_match(
                _read_json(folder / NARRATION_STAMP_NAME),
                narration_stamp(fields, prompt, entries, -1 if voice is None else voice, compared),
                ({"voice"} if voice is None else set()) | (set() if fixed and sounding is not None else {"compared"}))
            keep_voices = _may_match(
                game_speech_module.stored_stamp(game_speech),
                game_speech_module.stamp(model_name=quick, language=str(fields["language_code"]),
                                         prefer_gpu=bool(fields["prefer_gpu"]), track=-1 if game is None else game,
                                         narration_sha256=""),
                {"narration"} | ({"track"} if game is None else set()))
            whisper_models.refuse_unapproved(_models_to_load(
                main=str(fields["model_name"]), quick=quick, find_voice=voice is None, write_narration=not keep_words,
                compare=bool(compared) or not fixed, listen=listen_for_voices and not keep_voices))
        phases, recording = _bind_at_prepare(payload, run, source)
        project = run.create(recording)
        print(f"Project: {project}", flush=True)
        holder: dict[str, Any] = {}

        def quick_transcriber() -> voice_track.Transcriber:
            # Loaded once, for finding the voice and for the game track's voices.
            if "transcriber" not in holder:
                holder["transcriber"] = voice_track.whisper_transcriber(quick, bool(fields["prefer_gpu"]),
                                                                        str(fields["language_code"]))
            return holder["transcriber"]

        work = _scratch_folder()
        try:
            with _Pulse(payload, phases) as pulse:
                read = None
                if reuse is not None:
                    have_transcript, have_voices = reuse
                    print("The recording is not read again: the tracks, the layout, the narration, the other voices "
                          "and the analysis are as they were.", flush=True)
                    pulse.send(READING, f"{READING}: not needed, nothing it is read for has changed")
                    update_project(project, tracks=tracks, layout=layout, video=picture)
                    record_track_overrides(project, tracks)
                    run.keep()
                    print(f"Your voice: Track {voice + 1} ({_decided_text(voice_by)}). "
                          f"The game sound: Track {game + 1} ({_decided_text(game_by)}).", flush=True)
                    _say_warnings(list(stored_analysis.get("warnings") or []))
                    if have_transcript:
                        print("The narration is written down already, with the same settings.", flush=True)
                else:
                    print(f"{READING} once: {len(streams)} audio tracks and the game picture ({clock(duration)})...",
                          flush=True)
                    throttled = _Throttled(pulse, READING)
                    read = read_recording(ffmpeg, source, streams, duration, video, work, story_panel=story_panel,
                                          masked_panels=sorted(masks), on_progress=throttled)
                    # 264: every track's moments from the one read, plus the decision if it listened.
                    roles_for_facts = voice_track.parse_track_roles(known.roles_value)
                    if voice is not None:
                        speech_facts.record_measure(source, voice_track.track_details(read.activities), titles=titles,
                                                    measured_by=speech_facts.BY_EDITOR, duration=duration,
                                                    setting_roles=roles_for_facts)
                    if voice is None:
                        pulse.send(READING, f"{READING}: listening for your voice")
                        detection = voice_track.detect_voice_track(
                            source, ffmpeg_exe=ffmpeg, ffprobe_exe=ffprobe, transcriber=quick_transcriber(),
                            setting_roles=voice_track.parse_track_roles(known.roles_value),
                            decoded=(streams, duration, read.wavs), progress=lambda message: pulse.send(READING, message),
                            details=True)
                        speech_facts.record_measure(source, detection, titles=titles, measured_by=speech_facts.BY_EDITOR,
                                                    duration=duration, setting_roles=roles_for_facts)
                        if detection.get("status") != "selected" or detection.get("selected_ordinal") is None:
                            raise ValueError(f"Choose the voice track: Prepare could not tell which track is your voice. "
                                             f"{str(detection.get('explanation') or '').strip()}".strip())
                        voice = int(detection["selected_ordinal"])
                        voice_by = str(detection.get("decided_by") or voice_track.DECIDED_BY_AUTO)
                        if known.voice_problem(voice):
                            raise ValueError(f"Choose the voice track: your voice was heard only on {known.number(voice)}, "
                                             f"and {known.voice_problem(voice)[0].lower()}{known.voice_problem(voice)[1:]}")
                    if game is None:
                        game, decided = voice_track.game_audio_track(titles, setting_value=known.roles_value,
                                                                     narration_ordinal=voice, activities=read.activities)
                        if game is None:
                            raise ValueError(f"Choose the game track: no game-audio track was found ({decided}). Name "
                                             "the track in OBS, set it as Game audio in your Narration track setting "
                                             "(Settings > General / Startup), or choose it on the page.")
                        game_by = decided
                    if voice == game:
                        raise ValueError(f"Your voice and the game sound must be different tracks (both are Track "
                                         f"{voice + 1}).")
                    tracks = {"voice": voice, "game": game, "voice_decided_by": voice_by, "game_decided_by": game_by}
                    sounding = {ordinal for ordinal, item in read.activities.items() if not item.silent}
                    compared = _compared_tracks(known, voice, game, sounding)
                    have_transcript, have_voices = stored_steps(compared)
                    # Stage 3 (review M4): with the tracks known, the rest of this run's models, before the narration is
                    # written down. A narration written again may give the same words, so stored other voices that
                    # fit but for those words are not counted as heard again yet.
                    writes = not skip_transcript and not have_transcript
                    may_keep_voices = writes and _may_match(game_speech_module.stored_stamp(game_speech),
                                                            voices_stamp(False), {"narration"})
                    whisper_models.refuse_unapproved(_models_to_load(
                        main=str(fields["model_name"]), quick=quick, find_voice=False, write_narration=writes,
                        compare=bool(compared), listen=listen_for_voices and not have_voices and not may_keep_voices))
                    update_project(project, tracks=tracks, layout=layout, video=picture, sounding=sorted(sounding))
                    record_track_overrides(project, tracks)
                    run.keep()
                    print(f"Your voice: Track {voice + 1} ({_decided_text(voice_by)}). "
                          f"The game sound: Track {game + 1} ({_decided_text(game_by)}).", flush=True)
                    # 226: a chosen track with no sound is used as chosen, and said plainly.
                    _say_warnings(silent_track_warnings(tracks, read.levels))

                    read.keep_only({voice, game, *compared})
                    if writes:
                        _write_narration(wav=read.wavs[voice], folder=folder, source=source, voice=voice,
                                         compared=compared, titles=titles, wavs=read.wavs, fields=fields, prompt=prompt,
                                         entries=entries, ffmpeg=ffmpeg,
                                         stamp=narration_stamp(fields, prompt, entries, voice, compared),
                                         pulse=pulse, work=work)
                        have_transcript = True
                        have_voices = (game_speech.exists()
                                       and game_speech_module.stored_stamp(game_speech) == voices_stamp(True))
                    elif have_transcript:
                        print("The narration is written down already, with the same settings.", flush=True)
                    if listen_for_voices and not have_voices:
                        print(f"Listening for other voices on the game sound (track {game + 1})...", flush=True)
                        pulse.send(LISTENING)
                        game_speech_module.listen_to_game_track(
                            read.wavs[game], folder, transcript if have_transcript else None,
                            transcriber=quick_transcriber(), track=game, model_name=quick,
                            language=str(fields["language_code"]), result_stamp=voices_stamp(have_transcript),
                            on_progress=lambda done, total: pulse.send(
                                LISTENING, f"{LISTENING}: {done} of {total} five-minute pieces", done, total))
                        have_voices = True

                print("Watching the race: sound, stills and picture changes...", flush=True)
                pulse.send(WATCHING)
                analyze(project, source, budget=budget, tracks=tracks, layout=layout,
                        story_panel=story_panel, masks=masks, transcript=transcript if have_transcript else None,
                        game_speech=game_speech if have_voices else None, ffmpeg=ffmpeg, ffprobe=ffprobe,
                        on_progress=lambda activity, done, total: pulse.send(WATCHING, activity, done, total),
                        recording=read, track_roles=known.roles_value)
                digest = project / "analysis" / "digest.md"
                print(f"Ready for the AI editor: {digest}", flush=True)
                pulse.send(WATCHING, "Ready for the AI editor", state="completed", done=True)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    data = read_json(project / "analysis" / "analysis.json")
    index_quietly(project)
    return {"project": str(project), "digest": str(project / "analysis" / "digest.md"),
            "sheets": [s["file"] for s in data["sheets"]], "privacy_masked": data["privacy_masked"],
            "warnings": list(data.get("warnings") or [])}


def _bind_at_prepare(payload: dict[str, Any], run: _ProjectRun, source: Path) -> tuple[tuple[str, ...], dict[str, Any] | None]:
    """242 (Wave C2): a new video is bound to its recording's content before anything is written: from the library
    when it read this very file (nothing is read), else by reading it once, the extra step "Confirming which
    recording this is". An existing video keeps what it has (an older one is linked only from the page, Q6); one
    bound to a recording that has moved is refused until it is linked again there. Returns Prepare's steps and the
    binding for a new video (None for an existing one)."""

    meta = _read_json(run.folder / "project.json")
    if meta:
        if (binding(meta) is not None and not _same_recording_path(source, meta.get("source"))
                and not Path(str(meta.get("source") or "")).is_file()):
            raise ValueError(f"This video was made from {meta.get('source')}, which is no longer there; {source} holds the "
                             f"same recording. {LINK_HINT}")
        return PREPARE_PHASES, None
    if library_content(source) is not None:
        print("The library knows this recording already: nothing more to read to confirm it.", flush=True)
        return PREPARE_PHASES, recording_block(source)
    phases = (CONFIRMING, *PREPARE_PHASES)
    print(f"{CONFIRMING}: reading it once...", flush=True)
    with _Pulse(payload, phases) as pulse:
        throttled = _Throttled(pulse, CONFIRMING)
        found = recording_block(source, on_progress=lambda done, total: throttled(
            f"{CONFIRMING}: {done * 100 // max(1, total)}%", done, total))
    return phases, found


def _same_recording_path(first: Any, second: Any) -> bool:
    return os.path.normcase(os.path.abspath(str(first))) == os.path.normcase(os.path.abspath(str(second or "")))


def index_quietly(project: Path) -> None:
    """242 (Wave C2, design 2.8): the library's index of this one project is brought up to date at the end of a
    command. A library that cannot be opened never fails the command; the page repairs the index when it is next
    shown."""

    try:
        connection = recording_records.connect(backup=False)
        try:
            reconcile(connection, Path(project).parent.parent, only=Path(project))
        finally:
            connection.close()
    except Exception as exc:  # noqa: BLE001 - the library only indexes; it never fails a command (Wave C2 review)
        print(f"The library's list of edits was not updated ({type(exc).__name__}); the page will catch up.", flush=True)


def _say_warnings(warnings: list[str]) -> None:
    for warning in warnings:
        print(f"Warning: {warning}", flush=True)


class _Throttled:
    """The read's progress as status lines: at most every two seconds, and always the end of a step."""

    def __init__(self, pulse: _Pulse, phase: str) -> None:
        self.pulse, self.phase = pulse, phase
        self.last = 0.0

    def __call__(self, activity: str, done: int, total: int) -> None:
        now = time.monotonic()
        if done >= total or done == 0 or now - self.last >= 2.0:
            self.last = now
            self.pulse.send(self.phase, activity, done, total)


def fresh_edit_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """A separate edit of the same recording, with no versions and a fresh budget (171)."""

    fresh = start_fresh_edit(Path(payload["project"]))
    index_quietly(fresh)
    return {"project": str(fresh)}
