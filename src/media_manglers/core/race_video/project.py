"""Edit projects: one folder per video, with every version kept (150).

    <output>/race-videos/<name>/
      project.json          recording, its fingerprint, the versions and the current one
      analysis/             built once, reused by every version
      versions/v001/        timeline.json, story.md, review.md, qc json, renders
      feedback/v001.md      the operator's notes on a version
      export/               the approved final file

A version is never edited in place; a revision is a new version that records its parent and
what it answers. Every file is written to a temporary name, flushed to the disk and renamed into
place, so a crash or a cancelled run never leaves a half-written project (183: renaming alone is
not enough; a system crash a minute after a render once left it damaged, because its data was still
in the write cache). The recording is only read.

267: the project's own recording (``project.json`` "source") is the one every version is stored,
rendered and exported from. The AI editor's timeline names a source too; that is only a claim, checked
against the project's recording (``recording_refusal``), never trusted by its file name.

242 (Wave C2, audit H6): a project made from now on is bound to its recording's content at Prepare:
``project.json`` gains a ``recording`` block (the full and sampled hashes, the size and modified time, when it
was bound and how). For a bound project the hash decides whether a file is its recording (``holds_recording``);
an unbound project keeps the checks it had. A recording moved and linked again keeps its old paths in
``source_history``, so the versions stored before still render.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any

from .. import panel_layout, recording_identity, recording_records
from ..frame_render import PANEL_ROLES
from .privacy import layout_problem, load_masks
from .timeline import SCHEMA, layout_of, validate_timeline

PROJECT_SCHEMA = "mm-race-video-project-v1"
# The AI editor's own name for a version (226), such as "claude-opus-5.5": at most this long once cleaned.
EDITOR_LABEL_LENGTH = 32
# 226: the page's choices for one video: its own export quality ("export_quality") and the tracks
# picked by hand at its last Prepare ("tracks", 0-based). The export reads the first; Prepare writes the
# second; the page reads both.
EDITOR_SETTINGS_NAME = "editor-settings.json"


def editor_layout() -> dict[str, Any]:
    """The editor's three-screen layout, built from the shared three-panel geometry (226), so the
    panels have one source; they keep the editor's names (left, center, right), which the operator's
    masks and the AI editor use. It is ``timeline.DEFAULT_LAYOUT``."""

    names = {role: name for name, role in PANEL_ROLES.items()}
    panels = {names[panel["role"]]: [int(panel["crop_x"]), int(panel["crop_y"]), int(panel["crop_width"]),
                                     int(panel["crop_height"])]
              for panel in panel_layout.THREE_PANEL_DEFINITIONS}
    return {"width": panel_layout.THREE_PANEL_COMPOSITE_WIDTH, "height": panel_layout.THREE_PANEL_COMPOSITE_HEIGHT,
            "panels": {name: panels[name] for name in ("left", "center", "right")}}


def flush_to_disk(path: Path) -> None:
    """Wait until a file's data is on the disk, not only in the system's write cache."""

    # Windows flushes a file only through a handle that may write to it.
    with open(path, "rb+") as handle:
        os.fsync(handle.fileno())


def replace_durably(temp: Path, target: Path) -> None:
    """Rename a finished file into place so that a crash leaves either the old file or the whole new one.

    The data is flushed before the rename. On Linux and macOS the folder is flushed after it, so the
    rename itself is on the disk too; NTFS records renames in its journal.
    """

    flush_to_disk(temp)
    os.replace(temp, target)
    if os.name != "nt":
        folder = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(folder)
        finally:
            os.close(folder)


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(text, encoding="utf-8")
    replace_durably(temp, path)


def write_json_atomic(path: Path, data: Any) -> None:
    write_atomic(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def source_fingerprint(source: Path) -> dict[str, Any]:
    stat = source.stat()
    return {"name": source.name, "size": stat.st_size, "modified": int(stat.st_mtime)}


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "video"


# The project's binding to its recording's content (242, Wave C2) ---------------------------------------------
RECORDING_KEY = "recording"
HISTORY_KEY = "source_history"
BOUND_AT_PREPARE = "read at Prepare"  # Prepare read the file once to know it
BOUND_FROM_LIBRARY = "from the library"  # the library had read this very file: nothing was read
BOUND_BY_LINK = "linked by you"  # an older project, linked from the editor page with your confirmation


def binding(meta_or_project: dict[str, Any] | Path) -> dict[str, Any] | None:
    """The project's ``recording`` block, or None for a project that is not bound (made before Wave C2)."""

    meta = meta_or_project if isinstance(meta_or_project, dict) else _read_quietly(Path(meta_or_project) / "project.json")
    found = meta.get(RECORDING_KEY)
    return found if isinstance(found, dict) and str(found.get("content_sha256") or "") else None


def bound_content(project: Path) -> str:
    """The full hash the project is bound to, "" when it is not bound."""

    found = binding(project)
    return str(found["content_sha256"]) if found else ""


def source_history(project: Path) -> list[str]:
    """The paths the project's recording had before it was linked again where it is now (242, Wave C2)."""

    found = _read_quietly(project / "project.json").get(HISTORY_KEY)
    return [str(item.get("source")) for item in found if isinstance(item, dict) and item.get("source")] \
        if isinstance(found, list) else []


def _file_now(path: Path) -> tuple[int, int] | None:
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    return int(stat.st_size), int(stat.st_mtime_ns)


def library_content(path: Path) -> dict[str, Any] | None:
    """The library's content for the file at ``path``, only while the library read this very file (its size and
    modified time unchanged): ``content_sha256`` and ``sampled_sha256``. A quick look; nothing is read from the file."""

    now = _file_now(path)
    copy = recording_records.current_copy(path) if now else None
    if not copy or not copy.get("content_sha256") or (int(copy.get("size_bytes") or -1), int(copy.get("modified_ns") or -1)) != now:
        return None
    return {"content_sha256": str(copy["content_sha256"]), "sampled_sha256": str(copy.get("sampled_sha256") or "")}


def recording_block(source: Path, *, on_progress: Any = None) -> dict[str, Any]:
    """The ``recording`` block for the file at ``source``: from the library when it read this very file (nothing is
    read), else from one front-to-back read of it (``on_progress`` hears how far). Raises when the file changes while
    it is read."""

    before = _file_now(source)
    if before is None:
        raise ValueError(f"{source} is not there, so Media Manglers cannot tell which recording it is.")
    known = library_content(source)
    if known and known["sampled_sha256"]:
        sampled, content, how = known["sampled_sha256"], known["content_sha256"], BOUND_FROM_LIBRARY
    else:
        sampled, content = recording_identity.file_identity(source, on_progress)
        how = BOUND_AT_PREPARE
        if _file_now(source) != before:
            raise ValueError(f"{source} changed while it was read; try again once nothing is writing to it.")
    return {"content_sha256": content, "sampled_sha256": sampled, "size": before[0], "modified_ns": before[1],
            "bound_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "bound_how": how}


def holds_recording(found: dict[str, Any], path: Path, *, own: bool = False, read: bool = True) -> bool | None:
    """Whether the file at ``path`` holds the recording a project is bound to (``found``, its ``recording`` block),
    by the shared identity rule: the project's own path unchanged since it was bound is; the library's confirmed
    content decides when it read that file; otherwise another size or sampled hash is not, and only the full hash
    confirms it. With ``read`` False nothing is read in full, and None means it cannot tell without reading."""

    now = _file_now(path)
    if now is None:
        return False
    if own and now == (int(found.get("size") or -1), int(found.get("modified_ns") or -1)):
        return True
    known = library_content(path)
    if known:
        return known["content_sha256"] == found["content_sha256"]
    if now[0] != int(found.get("size") or -1):
        return False
    remembered = (os.path.normcase(os.path.abspath(str(path))), *now)
    if remembered in _READ_ANSWERS:
        return _READ_ANSWERS[remembered] == found["content_sha256"]
    try:
        if found.get("sampled_sha256") and recording_identity.sampled_sha256_file(path) != found["sampled_sha256"]:
            return False
        if not read:
            return None
        _READ_ANSWERS[remembered] = recording_identity.file_identity(path)[1]
        return _READ_ANSWERS[remembered] == found["content_sha256"]
    except (OSError, RuntimeError):
        return False


# What a whole read of a file found, by its path, size and modified time, so one command reads a file at most once
# (242, Wave C2 review: Prepare asks twice, before and as it makes the project).
_READ_ANSWERS: dict[tuple[str, int, int], str] = {}


def _linked_folder(output_root: Path, source: Path) -> Path | None:
    """The project a recording was linked to again where it is now, under another name (242, Wave C2): a bound
    project whose recording moved there, the first edit before any fresh edit of it."""

    found = []
    try:
        paths = sorted((Path(output_root) / "race-videos").glob("*/project.json"))
    except OSError:
        return None
    for path in paths:
        meta = _read_quietly(path)
        if meta.get(HISTORY_KEY) and binding(meta) and _same_path(meta.get("source") or "", source):
            found.append((bool(meta.get("edit_of")), path.parent))
    return min(found)[1] if found else None


def project_folder(output_root: Path, source: Path, name: str | None = None, *, read: bool = True) -> Path:
    """The project folder for ``source`` under ``output_root``, without making it (226: a run checks
    everything it can before it makes a project). Raises when that folder belongs to another recording.

    242 (Wave C2): for a bound project the hash decides (``holds_recording``); an unbound one keeps the check by
    name, size and time. With ``read`` False (a lookup on the page) nothing is read in full, and a bound project the
    quick checks cannot tell about falls back to that older check."""

    project = output_root / "race-videos" / slug(name or source.stem)
    if name is None and not (project / "project.json").exists():
        # A recording renamed and linked again keeps its video, whose folder has the old name.
        project = _linked_folder(output_root, source) or project
    meta_path = project / "project.json"
    if meta_path.exists():
        meta = read_json(meta_path)
        found = binding(meta)
        same = holds_recording(found, source, own=_same_path(source, meta.get("source") or ""), read=read) \
            if found else None
        if same is False or (same is None and meta.get("source_fingerprint") != source_fingerprint(source)):
            raise ValueError(f"{project} belongs to a different recording; choose another name")
    return project


def create_project(output_root: Path, source: Path, name: str | None = None,
                   recording: dict[str, Any] | None = None) -> Path:
    """Make (or reopen) the project folder for ``source`` under ``output_root``. 242 (Wave C2): a new project
    made with ``recording`` (``recording_block``) is bound to it from the start."""

    project = project_folder(output_root, source, name)
    meta_path = project / "project.json"
    if meta_path.exists():
        return project
    for folder in ("analysis", "versions", "feedback", "export"):
        (project / folder).mkdir(parents=True, exist_ok=True)
    meta = {
        "schema": PROJECT_SCHEMA,
        "source": str(source),
        "source_fingerprint": source_fingerprint(source),
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "versions": [],
        "current_version": None,
    }
    if recording:
        meta[RECORDING_KEY] = dict(recording)
    write_json_atomic(meta_path, meta)
    return project


def update_project(project: Path, **fields: Any) -> dict[str, Any]:
    """Set these fields of ``project.json`` and keep everything else in it (226: what Prepare fixed for
    the project, such as its tracks, layout and the recording's picture size). Read, changed and
    written back at once, so a version the AI editor added a moment ago is kept."""

    path = project / "project.json"
    meta = read_json(path)
    meta.update(fields)
    write_json_atomic(path, meta)
    return meta


def version_dir(project: Path, version: int) -> Path:
    return project / "versions" / f"v{version:03d}"


# What Prepare fixed for the project, and the guards on it (226, decisions A and F) ----------------


def _read_quietly(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def fixed_layout(project: Path) -> dict[str, Any] | None:
    """The camera layout fixed for the project at Prepare: ``project.json``'s, else (a project prepared
    before Wave 7, or a fresh edit of one) its analysis's; None when it has neither."""

    for path in (project / "project.json", project / "analysis" / "analysis.json"):
        layout = _read_quietly(path).get("layout")
        if isinstance(layout, dict):
            return layout
    return None


def prepared_tracks(project: Path) -> dict[str, int]:
    """The voice and game tracks Prepare chose for the project (0-based): ``project.json``'s, else the
    tracks its analysis marks as voice and game (a project prepared before Wave 7); {} when it was
    never prepared."""

    tracks = _read_quietly(project / "project.json").get("tracks")
    if isinstance(tracks, dict):
        found = {name: tracks[name] for name in ("voice", "game") if isinstance(tracks.get(name), int)}
        if found:
            return found
    rows = _read_quietly(project / "analysis" / "analysis.json").get("tracks")
    found = {}
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and row.get("role") in ("voice", "game") and isinstance(row.get("ordinal"), int):
            found.setdefault(str(row["role"]), int(row["ordinal"]))
    return found


def editor_settings(project: Path) -> dict[str, Any]:
    """The page's choices for this video (``editor-settings.json``), {} when it has none (226)."""

    return _read_quietly(project / EDITOR_SETTINGS_NAME)


def set_editor_settings(project: Path, **fields: Any) -> None:
    """Set these fields of ``editor-settings.json`` (None removes one) and keep the others, written whole
    and at once; the file goes when nothing is left in it (226)."""

    path = project / EDITOR_SETTINGS_NAME
    data = editor_settings(project)
    for name, value in fields.items():
        if value is None:
            data.pop(name, None)
        else:
            data[name] = value
    if data:
        write_json_atomic(path, data)
    else:
        path.unlink(missing_ok=True)


def picked_tracks(tracks: Any) -> dict[str, int]:
    """The tracks in a ``project.json`` "tracks" entry that were picked by hand ("override"), 0-based."""

    given = tracks if isinstance(tracks, dict) else {}
    return {name: int(given[name]) for name in ("voice", "game")
            if isinstance(given.get(name), int) and given.get(f"{name}_decided_by") == "override"}


def record_track_overrides(project: Path, tracks: Any) -> None:
    """Keep the tracks Prepare used that were picked by hand in ``editor-settings.json`` ("tracks"), so the
    page shows them picked again when the recording is chosen again (226): a re-prepare from the page
    then keeps them, and the versions made on them still render. Without one, "tracks" goes."""

    set_editor_settings(project, tracks=picked_tracks(tracks) or None)


def layout_refusal(project: Path, layout: Any, what: str) -> str:
    """Why ``layout`` (named ``what`` in the answer) is refused for this project, or "" (226,
    decision F): it differs from the project's fixed layout (the editor's three-screen layout, on
    which the masks are drawn, for a project not prepared yet) in the size, or in a panel that has one
    of the operator's stored masks."""

    reason = layout_problem(layout, fixed_layout(project) or editor_layout(), load_masks())
    if not reason:
        return ""
    return (f"{what} does not match the camera layout this project was prepared with: {reason}. The layout and "
            f"the privacy masks are fixed by Media Manglers, and a request cannot change them; leave {what} out and "
            "the project's own layout is used.")


def _track(ordinal: int) -> str:
    return f"Track {int(ordinal) + 1}"


def tracks_refusal(project: Path, tracks: Any, what: str = "this timeline") -> str:
    """Why an edit with ``tracks`` is refused for this project, or "" (226, decision A): it uses another
    voice or game track than the ones Prepare chose. A project never prepared accepts any. ``what``
    names what asked for the tracks in the answer."""

    prepared = prepared_tracks(project)
    given = tracks if isinstance(tracks, dict) else {}
    differ = [name for name in ("voice", "game") if name in prepared and given.get(name) != prepared[name]]
    if not differ:
        return ""
    said = {"voice": "your voice", "game": "the game sound"}
    chosen = " and ".join(f"{_track(prepared[name])} as {said[name]}" for name in ("voice", "game") if name in prepared)
    used = " and ".join(
        f"{_track(given[name]) if isinstance(given.get(name), int) else 'no track'} as {said[name]}" for name in differ)
    example = ", ".join(f'"{name}": {prepared[name]}' for name in ("voice", "game") if name in prepared)
    return (f"This project was prepared with {chosen}, and an edit can only use the prepared tracks; {what} "
            f"uses {used}. Use \"tracks\": {{{example}}} (0 is Track 1), or prepare the recording again with other "
            "tracks.")


def project_recording(project: Path) -> Path:
    """The project's own recording (267): the file it was made for, as ``project.json`` names it."""

    source = str(_read_quietly(project / "project.json").get("source") or "").strip()
    if not source:
        raise ValueError(f"{project} names no recording in its project.json")
    return Path(source)


def _same_path(first: Any, second: Any) -> bool:
    return os.path.normcase(os.path.abspath(str(first))) == os.path.normcase(os.path.abspath(str(second)))


LINK_HINT = ("Link it on the AI Video Editor page (Link recordings…), which asks you first; until then nothing is "
             "stored or rendered for this project.")


def recording_refusal(project: Path, claimed: Any, what: str = "the timeline's source", *,
                      history: bool = False) -> str:
    """Why ``claimed`` (a path the AI editor gave, named ``what`` in the answer) is refused as this
    project's recording, or "" (267). The project's own recording decides: its path is accepted, however
    it is spelled; another path only when the shared identity rule confirms that it holds the same
    recording (``recording_identity.same_content``), which needs the project's recording where the project
    says it is. A file name alone never decides it.

    242 (Wave C2): for a bound project the hash decides (``holds_recording``), so a file saved over the
    project's own path is refused too, and a recording that moved is recognised and sent to be linked again.
    With ``history`` (a stored version), a path the recording had before it was linked again is its own."""

    recording = project_recording(project)
    found = binding(project)
    if history and any(_same_path(claimed, old) for old in source_history(project)):
        # A version stored before the recording was linked again is rendered from where it is now, so that file is
        # checked as the project's own is.
        claimed = recording
    if _same_path(claimed, recording):
        if found and recording.is_file() and not holds_recording(found, recording, own=True):
            return (f"{what} is {recording}, but the file there is no longer the recording this project was made "
                    "from: another file was saved in its place. Put the project's recording back there; a recording "
                    "is never taken for another by its file name.")
        return ""
    other = Path(str(claimed))
    use = f'Use "source": {json.dumps(str(recording))}, the project\'s own recording.'
    if not recording.is_file():
        if found and holds_recording(found, other):
            return (f"{what} is {other}, which holds this project's recording, but the project still names "
                    f"{recording}, where it is no longer. {LINK_HINT}")
        return (f"{what} is {other}, but this project's recording is {recording}, and it is no longer there, so "
                f"Media Manglers cannot check that {other} is the same recording. Put the recording back at "
                f"{recording}; a recording is never taken for another by its file name.")
    if not other.is_file():
        return f"{what} is {other}, which is not this project's recording and is not there. {use}"
    if holds_recording(found, other) if found else recording_identity.same_content(recording, other):
        return ""
    same_name = " with the same file name" if other.name.casefold() == recording.name.casefold() else ""
    return f"{what} is {other}, a different recording{same_name} from this project's ({recording}). {use}"


def version_recording(project: Path, timeline: dict[str, Any], what: str = "this version's timeline source") -> Path:
    """The recording a stored version is rendered or listened to from (267): always the project's own,
    once the version's timeline is checked to name it (a timeline.json can be edited by hand, and a
    version stored before 267 was checked by its file name only). 242: a version stored before its
    recording was linked again names a path in ``source_history``, which counts as the project's own."""

    refusal = recording_refusal(project, timeline.get("source"), what, history=True)
    if refusal:
        raise ValueError(refusal)
    return project_recording(project)


def timeline_refusal(project: Path, timeline: dict[str, Any]) -> str:
    """Why this project refuses to store or render ``timeline``, or "": its ``source_layout`` would move
    or miss a stored privacy mask, or it uses other tracks than the prepared ones (226)."""

    return (layout_refusal(project, layout_of(timeline), "the timeline's source_layout")
            or tracks_refusal(project, timeline.get("tracks")))


def clean_editor_label(text: Any) -> str:
    """The AI editor's own name for a version (226), made safe for a file name: lower case, letters,
    digits, dots, dashes and underscores (anything else becomes one dash), at most
    ``EDITOR_LABEL_LENGTH`` characters. "" when nothing is left."""

    cleaned = re.sub(r"[^a-z0-9._-]+", "-", str(text or "").casefold()).strip("-._")
    return cleaned[:EDITOR_LABEL_LENGTH].strip("-._")


def add_version(project: Path, timeline: dict[str, Any], *, story: str = "", answers: str = "",
                parent: int | None = None, source_duration: float | None = None,
                audio_streams: int | None = None, editor_label: str = "") -> int:
    """Store a new version and make it current. Refuses a timeline the renderer could not run.

    226: a timeline without a ``source_layout`` gets the project's fixed layout. A timeline is
    refused when its layout would move or miss a stored privacy mask, or when it uses other voice or
    game tracks than Prepare chose (``timeline_refusal``). ``editor_label`` is the AI editor's own
    name for the version (its tool and model, say), kept cleaned as ``editor_label`` in the version's
    entry; the version's ``label`` stays "v003".

    267: a timeline whose source is not the project's recording is refused (``recording_refusal``),
    and the stored version names the project's recording, as ``project.json`` spells it.
    """

    meta = read_json(project / "project.json")
    fixed = fixed_layout(project)
    if fixed is not None and isinstance(timeline, dict) and not timeline.get("source_layout"):
        timeline = dict(timeline, source_layout=fixed)
    problems = validate_timeline(timeline, source_duration=source_duration, audio_streams=audio_streams)
    if problems:
        raise ValueError("the timeline cannot be rendered:\n- " + "\n- ".join(problems))
    refusal = recording_refusal(project, timeline["source"]) or timeline_refusal(project, timeline)
    if refusal:
        raise ValueError(refusal)
    number = max((v["version"] for v in meta["versions"]), default=0) + 1
    if parent is not None and parent not in {v["version"] for v in meta["versions"]}:
        raise ValueError(f"parent version {parent} does not exist")
    folder = version_dir(project, number)
    stored = dict(timeline, source=str(project_recording(project)), schema=SCHEMA, version=number, parent=parent,
                  answers=answers)
    write_json_atomic(folder / "timeline.json", stored)
    if story:
        write_atomic(folder / "story.md", story)
    entry = {
        "version": number,
        "parent": parent,
        "answers": answers,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    label = clean_editor_label(editor_label)
    if label:
        entry["editor_label"] = label
    found = binding(meta)
    if found:
        # 242 (Wave C2): a version keeps the content it was built from.
        entry["content_sha256"] = str(found["content_sha256"])
    meta["versions"].append(entry)
    meta["current_version"] = number
    write_json_atomic(project / "project.json", meta)
    return number


def load_version(project: Path, version: int) -> dict[str, Any]:
    return read_json(version_dir(project, version) / "timeline.json")


def version_entry(project: Path, version: int) -> dict[str, Any]:
    """The version's entry in ``project.json`` (its parent, answers, ``editor_label``, export), {} when
    there is none."""

    for entry in _read_quietly(project / "project.json").get("versions") or []:
        if isinstance(entry, dict) and entry.get("version") == version:
            return entry
    return {}


def export_file(project: Path, entry: dict[str, Any]) -> Path | None:
    """The version's exported video in ``export/``, or None (178): the file its export named in the
    version's entry; for a version exported before that was kept, the name exports had then
    (``<project>-v003.mp4``)."""

    names = [Path(str(entry["export"])).name] if entry.get("export") else []
    if isinstance(entry.get("version"), int):
        names.append(f"{slug(project.name)}-v{int(entry['version']):03d}.mp4")
    for name in names:
        path = project / "export" / name
        if path.is_file():
            return path
    return None


def exported_version(project: Path, name: str) -> int | None:
    """The version whose export in ``export/`` is called ``name`` (226): by the export name kept in its
    entry, or the name exports had before that was kept (``<project>-v003.mp4``); None when none is."""

    for entry in _read_quietly(project / "project.json").get("versions") or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("version"), int):
            continue
        names = {f"{slug(project.name)}-v{entry['version']:03d}.mp4"}
        if entry.get("export"):
            names.add(Path(str(entry["export"])).name)
        if name in names:
            return int(entry["version"])
    return None


def record_export(project: Path, version: int, name: str) -> None:
    """Keep the export's file name in the version's entry (178), so an exported version is told by
    its entry, never by the pattern of a file name. Read, changed and written back at once, so a
    version the AI editor added a moment ago is kept."""

    path = project / "project.json"
    meta = read_json(path)
    for entry in meta.get("versions", []):
        if isinstance(entry, dict) and entry.get("version") == version:
            entry["export"] = name
            entry["exported_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_json_atomic(path, meta)


def record_usage(project: Path, kind: str, count: int, *, version: int | None = None, note: str = "") -> None:
    """Log what was prepared for the AI editor (sheets, close looks, review rounds), for the usage report."""

    meta = read_json(project / "project.json")
    meta.setdefault("ai_usage", []).append({
        "when": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": kind,
        "count": int(count),
        "version": version,
        "note": note,
    })
    write_json_atomic(project / "project.json", meta)


def usage_report(project: Path) -> dict[str, Any]:
    """Totals of what was handed to the AI editor, overall and per version."""

    meta = read_json(project / "project.json")
    totals: dict[str, int] = {}
    per_version: dict[str, dict[str, int]] = {}
    for entry in meta.get("ai_usage", []):
        totals[entry["kind"]] = totals.get(entry["kind"], 0) + entry["count"]
        key = "analysis" if entry.get("version") is None else f"v{entry['version']:03d}"
        bucket = per_version.setdefault(key, {})
        bucket[entry["kind"]] = bucket.get(entry["kind"], 0) + entry["count"]
    return {"totals": totals, "by_version": per_version}


# 236: the scenes of the story strip the operator's notes are about, kept under the notes in the version's
# feedback file, so the AI editor reads them with the notes.
SCENE_NOTES_HEADING = "Scenes these notes are about"


def clock_text(seconds: float) -> str:
    """A time in the edited video as the page says it: "2:05", or "1:02:05" past an hour."""

    whole = max(0, int(round(float(seconds))))
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def scene_note_line(block: dict[str, Any]) -> str:
    """One story block (``timeline.story_blocks``) as a note names it: "Pit stop: scenes s07, s08, from
    2:15 to 2:45 of the video"."""

    ids = [str(scene) for scene in block.get("scenes") or [] if str(scene)]
    start = float(block.get("start") or 0.0)
    end = start + float(block.get("length") or 0.0)
    which = f"scene{'s' if len(ids) != 1 else ''} {', '.join(ids)}, " if ids else ""
    return f"{block['name']}: {which}from {clock_text(start)} to {clock_text(end)} of the video"


def notes_with_scenes(text: str, scenes: list[str]) -> str:
    """The notes as the feedback file keeps them: the operator's words, then the scenes they are about."""

    text = str(text or "").strip()
    if not scenes:
        return text
    return f"{text}\n\n{SCENE_NOTES_HEADING}:\n" + "\n".join(f"- {line}" for line in scenes)


def split_scene_notes(saved: str) -> tuple[str, list[str]]:
    """The operator's words and the scene lines of a saved feedback file (``notes_with_scenes`` read back)."""

    text = str(saved or "").rstrip()
    marker = f"\n{SCENE_NOTES_HEADING}:\n"
    if marker not in "\n" + text + "\n":
        return text.strip(), []
    words, _, listed = ("\n" + text + "\n").rpartition(marker)
    scenes = [line[2:].strip() for line in listed.splitlines() if line.startswith("- ") and line[2:].strip()]
    return words.strip(), scenes


def save_feedback(project: Path, version: int, text: str) -> Path:
    """The operator's plain-language notes on a version, for the AI editor's next revision."""

    if not version_dir(project, version).exists():
        raise ValueError(f"version {version} does not exist")
    path = project / "feedback" / f"v{version:03d}.md"
    write_atomic(path, text.strip() + "\n")
    return path
