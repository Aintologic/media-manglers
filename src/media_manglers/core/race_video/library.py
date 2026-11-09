"""What the AI Video Editor page shows and the export it makes (150 Phase 3).

The page lists the edit projects under the operator's output folder with every version and what
each one has (a story, the editor's review, a preview, the operator's notes, a final render), and
exports an approved version. Everything is read from the project files; nothing here is cached
elsewhere, so the page always shows what is on disk.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any

from .. import frame_render, recording_records
from .project import (
    HISTORY_KEY,
    RECORDING_KEY,
    binding,
    export_file,
    read_json,
    record_export,
    replace_durably,
    slug,
    source_history,
    version_dir,
    version_entry,
    write_json_atomic,
)
from .qc import check_video, expected_from_report
from .render import RenderOptions, acquire_project_lock, readable_name, remove_final_store, render_version

EXPORT_REFUSES_VALIDATION = ("validation_size is for a validation render only (race-video-render with profile "
                             "\"final\"); an export is always the real final, so nothing was exported.")
# 236: the files a version can have, by who made them. The app makes the first ones; any other video in
# the version's folder or its renders folder was made by the AI agent itself.
VIDEO_SUFFIXES = (".mp4", ".mkv", ".mov", ".m4v", ".webm")
ROLE_PREVIEW, ROLE_FINAL, ROLE_EXPORT = "preview", "final", "export"
ROLE_READABLE, ROLE_VALIDATION, ROLE_AGENT = "readable", "validation", "agent"
_VALIDATION_NAME = re.compile(r"^final-\d+x\d+\.mp4$")
# 236 (item 6): what the agent writes beside review.md; the page shows it one click away.
TECHNICAL_REPORT = "technical.md"


def projects_root(output_root: Path) -> Path:
    return output_root / "race-videos"


def _qc_passed(path: Path) -> bool | None:
    if not path.exists():
        return None
    try:
        return bool(json.loads(path.read_text(encoding="utf-8")).get("passed"))
    except (OSError, ValueError):
        return None


def _read_quietly(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def render_format(renders: Path, stem: str) -> dict[str, Any]:
    """What a render made (236): its ``width``, ``height`` and ``fps`` from its render report
    (``render-<stem>.json``), and the ``export_quality`` of a final; {} when the report says none (a
    project rendered before the report kept them)."""

    report = _read_quietly(renders / f"render-{stem}.json")
    made = report.get("output_format") if isinstance(report.get("output_format"), dict) else {}
    found = {name: made[name] for name in ("width", "height", "fps") if made.get(name)}
    if report.get("export_quality"):
        found["export_quality"] = str(report["export_quality"])
    return found


def _file_row(path: Path, role: str, made_by: str) -> dict[str, Any] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return {"role": role, "made_by": made_by, "path": str(path), "name": path.name, "size": int(stat.st_size),
            "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
            "same_as": "", "_id": (stat.st_dev, stat.st_ino) if stat.st_ino else None}


def version_files(project: Path, entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Every video file a version has (236, item 6), the app's first, then the AI agent's own.

    Each is a dict: ``role`` (preview, final, export, readable, validation or agent), ``made_by`` ("app" or
    "agent"), ``path``, ``name``, ``size``, ``modified`` and ``same_as``: the role of an earlier file that is
    the very same file on the disk (a readable name and an export are links to the render, 178), else "".
    The app's names are the fixed ``renders/preview.mp4`` and ``final.mp4``, the readable names linked to
    them, a validation render's ``final-<w>x<h>.mp4`` and the export the version's entry names; any other
    video in the version's folder or its renders folder was made by the agent itself.
    """

    number = int(entry["version"])
    folder = version_dir(project, number)
    renders = folder / "renders"
    base = slug(project.name).lstrip(".").rstrip(". ") or "video"
    readable = {name for profile in (ROLE_PREVIEW, ROLE_FINAL)
                for name in (readable_name(project, number, profile), f"{base}-v{number:03d}-{profile}.mp4")}
    rows: list[dict[str, Any]] = []
    for path, role in ((renders / "preview.mp4", ROLE_PREVIEW), (renders / "final.mp4", ROLE_FINAL)):
        row = _file_row(path, role, "app") if path.is_file() else None
        if row:
            rows.append(row)
    exported = export_file(project, entry)
    if exported is not None:
        row = _file_row(exported, ROLE_EXPORT, "app")
        if row:
            rows.append(row)
    others: list[dict[str, Any]] = []
    for where in (renders, folder):
        try:
            names = sorted(item for item in where.iterdir() if item.is_file())
        except OSError:
            continue
        for path in names:
            if path.name.startswith(".") or path.suffix.lower() not in VIDEO_SUFFIXES:
                continue
            if where == renders and path.name in ("preview.mp4", "final.mp4"):
                continue
            if where == renders and path.name in readable:
                role, made_by = ROLE_READABLE, "app"
            elif where == renders and _VALIDATION_NAME.match(path.name):
                role, made_by = ROLE_VALIDATION, "app"
            else:
                role, made_by = ROLE_AGENT, "agent"
            row = _file_row(path, role, made_by)
            if row:
                others.append(row)
    rows += sorted(others, key=lambda row: (row["made_by"] != "app", row["name"].casefold()))
    seen: dict[Any, str] = {}
    for row in rows:
        key = row.pop("_id")
        if key is None:
            continue
        if key in seen:
            row["same_as"] = seen[key]
        else:
            seen[key] = row["role"]
    return rows


def story_title(path: str | Path) -> str:
    """The story's own title (236): the first heading of ``story.md`` without "Story" and its dash in
    front ("# Story — A wet race at Spa" gives "A wet race at Spa"); "" when it has none."""

    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return ""
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            title = re.sub(r"^(the\s+)?story\s*(?:[-—–:]\s*|$)", "", title, flags=re.IGNORECASE).strip()
            return title
        if line.strip():
            return ""
    return ""


def project_summary(project: Path) -> dict[str, Any]:
    """One project as the page shows it, newest version first.

    236: each version also says what files it has (``files``, ``version_files``), what its preview and
    final are (``preview_format``, ``final_format``), its timeline and its technical report; the project
    says when anything last happened in it (``activity``) and its newest story's title (``story_title``).
    """

    meta = read_json(project / "project.json")
    analysis_path = project / "analysis" / "analysis.json"
    budget = ""
    if analysis_path.exists():
        try:
            budget = json.loads(analysis_path.read_text(encoding="utf-8"))["settings"]["budget"]
        except (OSError, ValueError, KeyError):
            budget = ""
    versions = []
    for entry in sorted(meta.get("versions", []), key=lambda v: v["version"], reverse=True):
        number = int(entry["version"])
        folder = version_dir(project, number)
        renders = folder / "renders"
        exported = export_file(project, entry)
        versions.append({
            "version": number,
            "label": f"v{number:03d}",
            # 226: the AI editor's own name for the version (its tool and model), "" when it gave none.
            "editor_label": str(entry.get("editor_label") or ""),
            "parent": entry.get("parent"),
            "answers": entry.get("answers", ""),
            "created": entry.get("created", ""),
            "folder": str(folder),
            "story": str(folder / "story.md") if (folder / "story.md").exists() else "",
            "review": str(folder / "review.md") if (folder / "review.md").exists() else "",
            "preview": str(renders / "preview.mp4") if (renders / "preview.mp4").exists() else "",
            "preview_passed": _qc_passed(renders / "qc-preview.json"),
            "final": str(renders / "final.mp4") if (renders / "final.mp4").exists() else "",
            "final_passed": _qc_passed(renders / "qc-final.json"),
            # 178: whether the version was exported, and the file, from its own entry (whatever its name).
            "exported": exported is not None,
            "export": str(exported) if exported is not None else "",
            "feedback": str(project / "feedback" / f"v{number:03d}.md")
            if (project / "feedback" / f"v{number:03d}.md").exists() else "",
            "timeline": str(folder / "timeline.json") if (folder / "timeline.json").exists() else "",
            "technical": str(folder / TECHNICAL_REPORT) if (folder / TECHNICAL_REPORT).exists() else "",
            "exported_at": str(entry.get("exported_at") or ""),
            "preview_format": render_format(renders, "preview"),
            "final_format": render_format(renders, "final"),
            "files": version_files(project, entry),
        })
    exports = sorted(str(p) for p in (project / "export").glob("*.mp4")) if (project / "export").exists() else []
    moments = [str(meta.get("created") or "")]
    for entry in meta.get("versions", []):
        moments += [str(entry.get("created") or ""), str(entry.get("exported_at") or "")]
    newest_story = next((version["story"] for version in versions if version["story"]), "")
    return {
        "name": project.name,
        "edit_of": meta.get("edit_of", ""),
        "folder": str(project),
        "source": meta.get("source", ""),
        "created": meta.get("created", ""),
        "activity": max(moments),
        "analysed": analysis_path.exists(),
        "digest": str(project / "analysis" / "digest.md") if (project / "analysis" / "digest.md").exists() else "",
        "budget": budget,
        "current_version": meta.get("current_version"),
        "versions": versions,
        "exports": exports,
        "story_title": story_title(newest_story) if newest_story else "",
        # 242 (Wave C2): the content it is bound to ("" for a project made before), and where its recording was.
        "content_sha256": str((binding(meta) or {}).get("content_sha256") or ""),
        "source_history": source_history(project),
    }


def list_projects(output_root: Path) -> list[dict[str, Any]]:
    """Every edit project under the output folder, most recently created first. Unreadable ones are skipped."""

    root = projects_root(output_root)
    if not root.exists():
        return []
    found = []
    for meta in root.glob("*/project.json"):
        try:
            found.append(project_summary(meta.parent))
        except (OSError, ValueError, KeyError):
            continue
    return sorted(found, key=lambda p: p["created"], reverse=True)


def export_name(project: Path, version: int) -> str:
    """The export's file name (178): ``<project>-v003-<editor label>.mp4``, or ``<project>-v003.mp4``
    when the AI editor gave the version no label."""

    label = str(version_entry(project, version).get("editor_label") or "")
    return f"{slug(project.name)}-v{version:03d}{'-' + label if label else ''}.mp4"


def export_version(project: Path, version: int, options: RenderOptions) -> dict[str, Any]:
    """Render ``version`` at its export quality, check it, and place it in ``export/``.

    The export is only placed when the technical check passes, so ``export/`` never holds a video
    that failed it. It is a hard link to the render when the drive allows one, a copy otherwise.

    226: the final is at the recording's own frame rate (up to 60) and the export quality chosen
    (``options.export_quality``, else the project's choice, else the main setting), and the check
    expects what the render report says it made. The export's name gains the AI editor's label, and
    the name is kept in the version's entry, so the page knows the version was exported.

    226: one project lock is held from the render to the placement, so no other render can replace
    the final between its check and the export. A validation size is refused: it is for a validation
    render only. Once the export is placed, the final's scene store is removed (``remove_final_store``):
    a project uses that disk only while a final is being made.
    """

    if options.validation_size:
        raise ValueError(EXPORT_REFUSES_VALIDATION)
    lock = acquire_project_lock(project, options)
    try:
        report = render_version(project, version, "final", options, lock=lock)
        final = Path(report["output"])
        qc = check_video(final, "final", expected_duration=report["expected_duration"],
                         ffmpeg=options.ffmpeg, ffprobe=options.ffprobe, expected=expected_from_report(report))
        write_json_atomic(final.with_name("qc-final.json"), qc)
        result: dict[str, Any] = {"render": report, "technical_check": qc, "export": ""}
        if not qc["passed"]:
            return result
        target = project / "export" / export_name(project, version)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        temp.unlink(missing_ok=True)
        try:
            os.link(final, temp)
        except OSError:
            shutil.copyfile(final, temp)
        replace_durably(temp, target)
        record_export(project, version, target.name)
        result["export"] = str(target)
        result["final_store"] = remove_final_store(project)
        return result
    finally:
        lock.release()


def panel_still(ffmpeg: str, source: Path, layout: dict[str, Any], panel: str, at: float, out: Path) -> Path:
    """One frame of a camera panel at the recording's own resolution, for drawing its privacy mask.

    This picture is shown only to the operator, on this PC, so the mask can be drawn over it. It is
    never handed to an AI editor: the mask editor writes it to the app's temporary folder, and the
    command that could write it into a project is retired (226).

    226: taken by the one frame renderer (one short seek, the panel cut at the recording's own size,
    the same picture as before), without a console window flashing up in the Workbench.
    """

    if panel not in layout["panels"]:
        raise ValueError(f"unknown panel '{panel}'")
    crop = [int(v) for v in layout["panels"][panel]]
    try:
        frame_render.render_stills(ffmpeg, source, [float(at)], out.parent, crop=crop, name=out.name, workers=1,
                                   reuse=False)
    except RuntimeError as exc:
        # The renderer says "could not take a still at mm:ss: <FFmpeg's words>"; the editor names the camera.
        detail = str(exc).split(": ", 1)[1] if ": " in str(exc) else str(exc)
        raise RuntimeError(f"could not take a still of the {panel} camera: {detail}") from exc
    if not out.exists():
        raise RuntimeError(f"could not take a still of the {panel} camera: FFmpeg wrote no picture")
    return out


def start_fresh_edit(project: Path) -> Path:
    """A separate edit of the same recording, next to ``project``: no versions and a fresh budget (171).

    The analysis is copied, not rebuilt, so the new edit is ready at once; its contact sheets are
    counted in the new edit's usage, since its editor reads them too. ``project`` is not changed.
    """

    meta = read_json(project / "project.json")
    if not (project / "analysis" / "analysis.json").exists():
        raise ValueError("prepare the recording before starting a fresh edit of it")
    base = str(meta.get("edit_of") or project.name)
    number = 2
    while (project.parent / f"{base}-edit-{number}").exists():
        number += 1
    fresh = project.parent / f"{base}-edit-{number}"
    staging = project.parent / f".{fresh.name}.tmp"
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(project / "analysis", staging / "analysis")
    for folder in ("versions", "feedback", "export"):
        (staging / folder).mkdir(parents=True, exist_ok=True)
    sheets = sum(e["count"] for e in meta.get("ai_usage", [])
                 if e.get("kind") == "contact sheets prepared for the AI editor" and e.get("version") is None)
    # 226: what Prepare fixed for the recording comes along: the tracks, the camera layout, the picture size.
    # 242 (Wave C2): so does its binding to the recording, and where the recording was before.
    fixed = {key: meta[key] for key in ("tracks", "layout", "video", RECORDING_KEY, HISTORY_KEY) if key in meta}
    write_json_atomic(staging / "project.json", {
        "schema": meta.get("schema"),
        "source": meta["source"],
        "source_fingerprint": meta["source_fingerprint"],
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "edit_of": base,
        **fixed,
        "versions": [],
        "current_version": None,
        "ai_usage": [{"when": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "kind": "contact sheets prepared for the AI editor", "count": sheets, "version": None,
                      "note": f"copied with the analysis from {project.name}"}] if sheets else [],
    })
    os.replace(staging, fresh)
    return fresh


# The library's index of the projects (242, Wave C2, audit M2) -------------------------------------------------
_DOCUMENTS = ("story", "review", "technical", "feedback", "timeline")


def index_row(output_root: Path, summary: dict[str, Any]) -> dict[str, Any]:
    """One project as the library indexes it (``recording_records.index_editor_projects``), from what its own files
    say (``project_summary``): where it is inside the output folder, its recording, whether it is bound, and each
    version's facts. That an agent's document or render exists is recorded, never what it says."""

    found = binding(Path(summary["folder"])) or {}
    return {
        "relative_path": os.path.relpath(summary["folder"], output_root),
        "source": str(summary.get("source") or ""),
        "content_sha256": str(found.get("content_sha256") or ""),
        "edit_of": str(summary.get("edit_of") or ""),
        "link_state": recording_records.LINK_BOUND if found else recording_records.LINK_UNBOUND,
        "bound_utc": str(found.get("bound_utc") or ""), "bound_how": str(found.get("bound_how") or ""),
        "versions": [{"version": item["version"], "created": item.get("created", ""),
                      "editor_label": item.get("editor_label", ""), "preview_passed": item.get("preview_passed"),
                      "final_passed": item.get("final_passed"), "exported": bool(item.get("exported")),
                      "documents": [name for name in _DOCUMENTS if item.get(name)]}
                     for item in summary.get("versions") or []],
    }


def reconcile(records: Any, output_root: Path, *, projects: list[dict[str, Any]] | None = None,
              only: Path | None = None) -> int:
    """Make the library's index of the editor's projects match the project files under ``output_root`` (audit M2:
    a refresh is a repair signal). It never writes to a project; it is keyed by project and version, so running it
    twice changes nothing; a project no longer on disk is marked unavailable, never deleted. ``records`` is the
    window's open library (``Records``) or a connection; ``projects`` the summaries already read, when the caller has
    them; ``only`` one project folder (an agent's command). Returns how many index rows changed."""

    connection = records.connection() if hasattr(records, "connection") else records
    output_root = Path(output_root)
    if only is not None:
        try:
            summaries = [project_summary(Path(only))] if (Path(only) / "project.json").is_file() else []
        except (OSError, ValueError, KeyError):
            summaries = []
    else:
        summaries = list_projects(output_root) if projects is None else list(projects)
    rows = [index_row(output_root, summary) for summary in summaries]
    return recording_records.index_editor_projects(
        connection, output_root, rows, only=None if only is None else os.path.relpath(Path(only), output_root))
