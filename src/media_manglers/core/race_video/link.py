"""Linking an older AI Video Editor project to its recording (242, Wave C2, audit H6, operator decision Q6).

A project made before Wave C2 knows its recording only by path, name, size and whole-second time. It keeps working
exactly as before until the operator links it, from one dialog on the editor page, one project at a time, after
seeing the evidence:

- the recording's name, folder, size and length;
- whether the path, the size and the time still match;
- whether the library has read that copy (and so knows its hash);
- for a recording that moved, the library's copies of the same size and time, and files of the same size and time
  in the folder it was in (a rename);
- whether the sound matches: the analysis's loudness per second against the cached levels of the file, when both
  exist (the same per-second levels, so this is independent of the file name).

A file name alone is never offered as a match. Linking writes ``project.json`` only: a copy is kept first as
``project.json.before-link``, the ``recording`` block and (for a moved recording) the old path in ``source_history``
are added and ``source`` names where the recording is now; the file is written with the shared safe writer and read
back. Nothing else in the project changes, and putting the kept copy back undoes it.

``link_check`` is the same look as a dry run: it writes nothing and reads no recording.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import statistics
from typing import Any, Callable

from .. import recording_records, safe_write, track_levels
from .project import BOUND_BY_LINK, HISTORY_KEY, RECORDING_KEY, binding, recording_block

CAN_LINK, MOVED, NO_EVIDENCE = "can_link", "moved", "no_evidence"
BEFORE_LINK = "project.json.before-link"
VIDEO_SUFFIXES = (".mkv", ".mp4", ".mov", ".avi", ".m4v", ".webm")
# The sound matches when, on every track both have, the per-second levels differ by at most this much in the middle
# (the median), over at least this many seconds the two share.
SOUND_MEDIAN_DB = 1.5
SOUND_MIN_SECONDS = 20


@dataclass
class Evidence:
    """What the link dialog shows for one project, and what it would link to."""

    project: Path
    source: str
    size: int | None = None
    length_seconds: float | None = None
    path_there: bool = False
    size_matches: bool = False
    time_matches: bool = False
    library_has_hash: bool = False
    candidates: list[dict[str, Any]] = field(default_factory=list)
    sound_matches: bool | None = None
    verdict: str = NO_EVIDENCE
    target: str = ""

    def lines(self) -> list[str]:
        """The evidence in plain words, for the dialog. Paths are the operator's own, shown only on this PC."""

        source = Path(self.source)
        said = [f"Recording: {source.name}", f"Folder: {source.parent}"]
        if self.size is not None:
            said.append(f"Size: {self.size / 1024 ** 3:.2f} GB" if self.size >= 1024 ** 3 else f"Size: {self.size:,} bytes")
        if self.length_seconds:
            minutes, seconds = divmod(int(round(self.length_seconds)), 60)
            said.append(f"Length: {minutes}:{seconds:02d}")
        if self.path_there:
            matches = [what for what, ok in (("the size", self.size_matches), ("the time", self.time_matches)) if ok]
            differs = [what for what, ok in (("the size", self.size_matches), ("the time", self.time_matches)) if not ok]
            said.append("The file is still there" + (f"; {' and '.join(matches)} still match" if matches else "")
                        + (f"; {' and '.join(differs)} differ" if differs else "") + ".")
        else:
            said.append("The file is no longer there.")
        said.append("The library has read this file and knows its content." if self.library_has_hash
                    else "The library has not read this file yet; linking reads it once.")
        if self.candidates:
            places = ", ".join(str(item["path"]) for item in self.candidates)
            said.append(f"A file of the same size and time: {places}")
        if self.sound_matches is not None:
            said.append("The sound matches what Prepare measured." if self.sound_matches
                        else "The sound does not match what Prepare measured.")
        return said


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def needs_link(meta: dict[str, Any]) -> bool:
    """Whether a project (its ``project.json``) is offered in the link dialog: it is not bound to its recording yet,
    or it is and its recording is no longer where it names it (moved or renamed)."""

    if not meta:
        return False
    return binding(meta) is None or not Path(str(meta.get("source") or "")).is_file()


def unbound_projects(output_root: Path) -> list[Path]:
    """The project folders under ``output_root`` the link dialog offers (``needs_link``)."""

    root = Path(output_root) / "race-videos"
    try:
        folders = sorted(item.parent for item in root.glob("*/project.json"))
    except OSError:
        return []
    return [folder for folder in folders if needs_link(_read(folder / "project.json"))]


def _expected(meta: dict[str, Any]) -> tuple[int, int, str]:
    """The size, whole second of modification and content (or "") the project's recording had: the binding's for a
    bound project, else the older fingerprint's. Raises ValueError when the project file has neither."""

    found = binding(meta)
    if found:
        return int(found["size"]), int(found["modified_ns"]) // 1_000_000_000, str(found["content_sha256"])
    old = meta.get("source_fingerprint") if isinstance(meta.get("source_fingerprint"), dict) else {}
    try:
        return int(old.get("size")), int(old.get("modified")), ""
    except (TypeError, ValueError) as exc:
        raise ValueError("the project file says nothing about its recording's size and time") from exc


def _loudness(project: Path) -> dict[int, list[float]]:
    levels = _read(project / "analysis" / "analysis.json").get("loudness_per_second")
    found: dict[int, list[float]] = {}
    for key, values in (levels.items() if isinstance(levels, dict) else ()):
        if str(key).isdigit() and isinstance(values, list):
            found[int(key)] = [float(value) for value in values]
    return found


def sound_matches(analysis_levels: dict[int, list[float]], cached: dict[int, list[float]]) -> bool | None:
    """Whether two sets of per-second levels (0-based tracks) are the same recording's sound; None when they share
    too little to tell."""

    compared = []
    for track in sorted(set(analysis_levels) & set(cached)):
        first, second = analysis_levels[track], cached[track]
        pairs = [(a, b) for a, b in zip(first, second) if a > -90 or b > -90]
        if len(pairs) < SOUND_MIN_SECONDS:
            continue
        compared.append(statistics.median(abs(a - b) for a, b in pairs) <= SOUND_MEDIAN_DB
                        and abs(len(first) - len(second)) <= 2)
    return all(compared) if compared else None


def _sound(project: Path, target: Path, cache: Path | None) -> bool | None:
    if cache is None:
        return None
    analysis = _loudness(project)
    if not analysis:
        return None
    levels = track_levels.cached_levels(target, cache=cache)
    if levels is None or not levels.complete:
        # Levels a stopped job left half done say nothing either way (Wave C2 review).
        return None
    return sound_matches(analysis, {track - 1: values for track, values in levels.tracks.items()})


def _siblings(source: Path, size: int, modified: int) -> list[dict[str, Any]]:
    """Files beside where the recording was with its size and whole second of modification (a rename). A quick look
    at the folder; nothing is read from any file."""

    found = []
    try:
        items = list(source.parent.iterdir())
    except OSError:
        return []
    for item in sorted(items):
        if item.suffix.lower() not in VIDEO_SUFFIXES or item == source:
            continue
        try:
            stat = item.stat()
        except OSError:
            continue
        if int(stat.st_size) == size and int(stat.st_mtime) == modified:
            found.append({"path": str(item), "content_sha256": "", "confirmed": False})
    return found


def evidence_for(project: Path, *, connection: sqlite3.Connection | None = None,
                 cache: Path | None = None) -> Evidence:
    """The evidence for one unbound project and what it would link to. ``connection`` is the library, read only
    (None: no library); ``cache`` the levels cache for the sound check (None: not asked). Reads no recording."""

    meta = _read(Path(project) / "project.json")
    source = Path(str(meta.get("source") or ""))
    found = Evidence(project=Path(project), source=str(source))
    found.length_seconds = _read(Path(project) / "analysis" / "analysis.json").get("duration")
    try:
        size, modified, content = _expected(meta)
    except ValueError:
        return found
    found.size = size
    try:
        stat = source.stat() if str(source) else None
    except OSError:
        stat = None
    if stat is not None:
        found.path_there = True
        found.size_matches = int(stat.st_size) == size
        found.time_matches = int(stat.st_mtime) == modified
    copy = recording_records.copy_at(connection, source) if connection is not None and found.path_there else None
    found.library_has_hash = bool(copy and copy["confirmed"])
    if found.path_there and found.size_matches and found.time_matches:
        found.target = str(source)
    else:
        library = (recording_records.copies_like(connection, size, modified_seconds=modified)
                   if connection is not None else [])
        if content:
            # A bound project's recording is known by its content: a library copy of other content is not it.
            library = [item for item in library if item["content_sha256"] in ("", content)]
        # Only files that are there now, and never the place the recording was (a library that has not scanned since
        # still lists it there).
        library = [item for item in library if os.path.normcase(str(item["path"])) != os.path.normcase(str(source))
                   and os.path.isfile(str(item["path"]))]
        seen = {os.path.normcase(str(item["path"])) for item in library}
        found.candidates = library + [item for item in _siblings(source, size, modified)
                                      if os.path.normcase(item["path"]) not in seen]
        contents = {item["content_sha256"] for item in found.candidates if item["content_sha256"]}
        unknown = [item for item in found.candidates if not item["content_sha256"]]
        # One recording, by its content or a single file: several different files are never guessed between.
        if len(found.candidates) == 1 or (len(contents) == 1 and not unknown):
            found.target = str(found.candidates[0]["path"])
            found.library_has_hash = bool(found.candidates[0].get("confirmed"))
    if found.target:
        found.sound_matches = _sound(Path(project), Path(found.target), cache)
        if found.sound_matches is False:
            found.target = ""
    if found.target:
        found.verdict = CAN_LINK if found.target == str(source) else MOVED
    return found


def link_check(output_root: Path, *, library_root: Path | None = None, cache: Path | None = None,
               projects: list[Path] | None = None) -> dict[str, Any]:
    """The link dialog's look at every unbound project, as a dry run: how many can be linked where they are, how many
    moved, how many have no evidence. Writes nothing and reads no recording; the library is opened read-only."""

    connection = recording_records.connect_read_only(library_root)
    try:
        found = [evidence_for(folder, connection=connection, cache=cache)
                 for folder in (projects if projects is not None else unbound_projects(output_root))]
    finally:
        if connection is not None:
            connection.close()
    return {"projects": len(found), "can_link": sum(item.verdict == CAN_LINK for item in found),
            "moved": sum(item.verdict == MOVED for item in found),
            "no_evidence": sum(item.verdict == NO_EVIDENCE for item in found), "evidence": found}


def link_project(project: Path, target: Path, *, on_progress: Callable[[int, int], None] | None = None) -> dict[str, Any]:
    """Link ``project`` to the recording at ``target``, once the operator confirmed it. The evidence is checked again
    first (the size and whole second of modification of the project's fingerprint). ``project.json`` is kept as
    ``project.json.before-link``, then written with the binding (and, for a moved recording, its new path and the old
    one in ``source_history``) through the shared safe writer, and read back; a failure leaves it as it was. Returns
    the binding."""

    project, target = Path(project), Path(target)
    path = project / "project.json"
    original = path.read_bytes()
    meta = json.loads(original.decode("utf-8"))
    if not needs_link(meta):
        raise ValueError(f"{project.name} is linked to its recording already; nothing was changed.")
    size, modified, content = _expected(meta)
    try:
        stat = target.stat()
    except OSError as exc:
        raise ValueError(f"{target} is not there, so {project.name} was not linked.") from exc
    if (int(stat.st_size), int(stat.st_mtime)) != (size, modified):
        raise ValueError(f"{target} is not the size and time {project.name} was made from, so it was not linked.")
    block = dict(recording_block(target, on_progress=on_progress), bound_how=BOUND_BY_LINK)
    if content and block["content_sha256"] != content:
        raise ValueError(f"{target} is a different recording from the one {project.name} was made from, so it was "
                         "not linked.")
    linked = dict(meta)
    linked[RECORDING_KEY] = block
    if os.path.normcase(os.path.abspath(str(target))) != os.path.normcase(os.path.abspath(str(meta.get("source") or ""))):
        history = list(meta.get(HISTORY_KEY) or []) if isinstance(meta.get(HISTORY_KEY), list) else []
        history.append({"source": str(meta.get("source") or ""),
                        "until": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        linked[HISTORY_KEY] = history
        linked["source"] = str(target)
    # The first kept copy is never written over: a later link keeps its own beside it (Wave C2 review).
    kept = project / BEFORE_LINK
    number = 2
    while kept.exists():
        kept = project / f"{BEFORE_LINK}-{number}"
        number += 1
    safe_write.write_bytes(kept, original)
    if path.read_bytes() != original:
        safe_write.remove(kept)
        raise ValueError(f"{project.name} changed while it was being linked (the AI editor may have added a version); "
                         "nothing was changed. Try again.")
    safe_write.write_json(path, linked)
    if _read(path) != linked:
        safe_write.write_bytes(path, original)
        raise ValueError(f"{project.name}'s project file did not read back as written, so it was put back as it was.")
    return block
