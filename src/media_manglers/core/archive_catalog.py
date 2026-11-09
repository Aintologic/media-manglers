"""Archive catalog and Glacier prep index helpers."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from math import ceil, sqrt
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
from typing import Any

from . import exports


SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}
DEFAULT_SKIP_MARKER = "_NO_GLACIER_BACKUP"
DEFAULT_HASH_MODE = "Fast"
DEFAULT_THUMBNAIL_MODE = "Auto"
DEFAULT_MAX_THUMBNAILS = 12
STORAGE_CLASS_TARGET = "DEEP_ARCHIVE"

MANUAL_NOTE_FIELDS = [
    "manual_title",
    "manual_notes",
    "manual_tags",
    "game",
    "track",
    "car",
    "session_type",
    "visible_apps",
    "issue_keywords",
    "archive_status",
]

MANUAL_NOTES_TEMPLATE_FIELDS = [
    "video_id",
    "filename",
    "relative_path",
    "duration",
    "contact_sheet_path",
    *MANUAL_NOTE_FIELDS,
]

CATALOG_FIELDS = [
    "video_id",
    "original_path",
    "scan_root",
    "relative_path",
    "filename",
    "extension",
    "size_bytes",
    "created_utc",
    "modified_utc",
    "inferred_capture_date",
    "capture_date_source",
    "duration",
    "width",
    "height",
    "video_codec",
    "audio_present",
    "audio_stream_count",
    "stream_info_json",
    "hash_status",
    "content_sha256",
    "proposed_s3_bucket",
    "proposed_s3_prefix",
    "proposed_s3_key",
    "scan_timestamp_utc",
    "media_mangler_version",
    "file_status",
    "catalog_status",
    "archive_status",
    "error_message",
    "thumbnail_status",
    "thumbnail_count",
    "thumbnail_paths",
    "contact_sheet_path",
    "transcript_status",
    "transcript_path",
    "transcript_text",
    "short_summary",
    "long_summary",
    "likely_game",
    "track",
    "car",
    "simulator",
    "session_type",
    "visible_apps",
    "issues_observed",
    "keywords",
    "confidence",
    "manual_title",
    "manual_notes",
    "manual_tags",
    "game",
    "issue_keywords",
]

INTEGRITY_FIELDS = [
    "video_id",
    "original_path",
    "relative_path",
    "size_bytes",
    "modified_utc",
    "hash_status",
    "content_sha256",
    "file_status",
    "catalog_status",
    "error_message",
]

UPLOAD_FIELDS = [
    "local_path",
    "proposed_s3_bucket",
    "proposed_s3_prefix",
    "proposed_s3_key",
    "storage_class_target",
    "size_bytes",
    "sha256",
    "hash_status",
    "skip_status",
    "skip_reason",
    "metadata_tag_suggestions",
]

SKIPPED_FIELDS = ["path", "scan_root", "reason", "marker"]
ERROR_FIELDS = ["video_id", "path", "relative_path", "error_stage", "error_message"]
NOTES_IMPORT_REPORT_FIELDS = ["video_id", "status", "updated_fields", "message"]

FTS_FIELDS = [
    "filename",
    "relative_path",
    "transcript_text",
    "manual_title",
    "manual_notes",
    "manual_tags",
    "short_summary",
    "long_summary",
    "keywords",
    "game",
    "track",
    "car",
    "session_type",
    "visible_apps",
    "issue_keywords",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso_from_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_stem(value: str) -> str:
    stem = Path(value).stem
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    return (safe or "video")[:80]


def make_video_id(relative_path: str, size_bytes: int, modified_utc: str, filename: str = "") -> str:
    safe_stem = _safe_stem(filename or relative_path)
    normalized_relative = relative_path.replace("\\", "/").lower()
    seed = f"{normalized_relative}|{int(size_bytes)}|{modified_utc}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    return f"{safe_stem}-{digest}"


def _normalize_hash_mode(value: str) -> str:
    normalized = str(value or DEFAULT_HASH_MODE).strip().lower()
    if normalized not in {"fast", "full", "off"}:
        raise ValueError("ArchiveHashMode must be Fast, Full, or Off.")
    return normalized.title()


def _normalize_thumbnail_mode(value: str) -> str:
    normalized = str(value or DEFAULT_THUMBNAIL_MODE).strip().lower()
    if normalized not in {"auto", "off"}:
        raise ValueError("ArchiveThumbnailMode must be Auto or Off.")
    return normalized.title()


def _relative_to(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return path.name


def _relative_to_catalog(path_value: str, catalog_dir: Path) -> str:
    if not path_value:
        return ""
    path = Path(path_value)
    try:
        return str(path.resolve().relative_to(catalog_dir.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


# 220: the shared CSV and JSON writers, also used by the raw bin library's export.
_write_json = exports.write_json
_write_jsonl = exports.write_jsonl
_write_csv = exports.write_csv
_read_csv = exports.read_csv


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _infer_capture_date(filename: str, modified_utc: str) -> tuple[str, str]:
    match = re.search(r"(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)", filename)
    if match:
        year, month, day = match.groups()
        return f"{year}-{month}-{day}", "filename"
    if modified_utc:
        return modified_utc[:10], "mtime"
    return "", "unknown"


def _proposed_s3_key(prefix: str, capture_date: str, capture_source: str, video_id: str, filename: str) -> str:
    clean_prefix = str(prefix or "").strip().strip("/")
    if capture_date and capture_source != "unknown":
        date_part = f"{capture_date[0:4]}/{capture_date[5:7]}"
    else:
        date_part = "unknown-date"
    parts = [part for part in [clean_prefix, date_part, video_id, filename] if part]
    return "/".join(parts)


def select_thumbnail_timestamps(duration_seconds: float, max_thumbnails: int = DEFAULT_MAX_THUMBNAILS) -> list[float]:
    max_count = max(0, int(max_thumbnails or 0))
    if max_count <= 0:
        return []
    try:
        duration = float(duration_seconds)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        return [0.5][:max_count]

    timestamps: list[float] = []

    def add(value: float) -> None:
        bounded = min(max(0.0, value), max(0.0, duration - 0.5))
        if all(abs(bounded - existing) > 1.0 for existing in timestamps):
            timestamps.append(round(bounded, 3))

    add(min(10.0, max(0.5, duration * 0.05)))
    interval = 600.0 if duration > 3600 else 300.0
    cursor = interval
    while cursor < duration and len(timestamps) < max_count - 1:
        add(cursor)
        cursor += interval
    add(max(0.5, duration - min(10.0, max(1.0, duration * 0.05))))

    if len(timestamps) > max_count:
        timestamps = timestamps[:max_count]
    return sorted(timestamps)


def normalize_ffprobe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    streams = payload.get("streams") or []
    format_payload = payload.get("format") or {}
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    primary_video = video_streams[0] if video_streams else {}
    duration = format_payload.get("duration") or primary_video.get("duration") or ""
    try:
        duration_value = str(round(float(duration), 3))
    except (TypeError, ValueError):
        duration_value = ""
    return {
        "duration": duration_value,
        "width": str(primary_video.get("width") or ""),
        "height": str(primary_video.get("height") or ""),
        "video_codec": str(primary_video.get("codec_name") or ""),
        "audio_present": "true" if audio_streams else "false",
        "audio_stream_count": str(len(audio_streams)),
        "stream_info_json": json.dumps(payload, ensure_ascii=False, sort_keys=True),
    }


def _run_ffprobe(path: Path, ffprobe_path: str) -> dict[str, Any]:
    command = [
        ffprobe_path or "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "ffprobe failed").strip()
        raise RuntimeError(message)
    return normalize_ffprobe_payload(json.loads(result.stdout or "{}"))


def _run_ffmpeg_thumbnail(source: Path, output_path: Path, timestamp: float, ffmpeg_path: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg_path or "ffmpeg",
        "-y",
        "-ss",
        f"{timestamp:.3f}",
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-vf",
        "scale=320:-2",
        "-q:v",
        "4",
        str(output_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0 or not output_path.exists():
        message = (result.stderr or result.stdout or "ffmpeg thumbnail extraction failed").strip()
        raise RuntimeError(message)


def _create_contact_sheet(thumbnail_dir: Path, thumbnails: list[Path], output_path: Path, ffmpeg_path: str) -> str:
    if not thumbnails:
        return "skipped_no_thumbnails"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cols = max(1, int(ceil(sqrt(len(thumbnails)))))
    rows = max(1, int(ceil(len(thumbnails) / cols)))
    command = [
        ffmpeg_path or "ffmpeg",
        "-y",
        "-framerate",
        "1",
        "-i",
        str(thumbnail_dir / "thumb_%04d.jpg"),
        "-vf",
        f"scale=320:-2,tile={cols}x{rows}:padding=8:margin=8",
        "-frames:v",
        "1",
        str(output_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode == 0 and output_path.exists():
        return "created"
    shutil.copyfile(thumbnails[0], output_path)
    return "fallback_single_thumbnail"


def _create_schema(connection: sqlite3.Connection) -> None:
    column_sql = ",\n            ".join(f"{field} TEXT" for field in CATALOG_FIELDS if field != "video_id")
    connection.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS videos (
            video_id TEXT PRIMARY KEY,
            {column_sql}
        );
        CREATE TABLE IF NOT EXISTS batches (
            batch_id TEXT PRIMARY KEY,
            scan_timestamp_utc TEXT,
            scan_roots_json TEXT,
            scanned_count INTEGER,
            added_count INTEGER,
            updated_count INTEGER,
            missing_count INTEGER,
            skipped_count INTEGER,
            error_count INTEGER
        );
        CREATE TABLE IF NOT EXISTS skipped_paths (
            path TEXT,
            scan_root TEXT,
            reason TEXT,
            marker TEXT
        );
        CREATE TABLE IF NOT EXISTS errors (
            video_id TEXT,
            path TEXT,
            relative_path TEXT,
            error_stage TEXT,
            error_message TEXT
        );
        """
    )
    try:
        connection.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS archive_search_fts USING fts5(
                video_id UNINDEXED,
                filename,
                relative_path,
                transcript_text,
                manual_title,
                manual_notes,
                manual_tags,
                short_summary,
                long_summary,
                keywords,
                game,
                track,
                car,
                session_type,
                visible_apps,
                issue_keywords
            );
            """
        )
    except sqlite3.OperationalError:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS archive_search_fts (
                video_id TEXT PRIMARY KEY,
                filename TEXT,
                relative_path TEXT,
                transcript_text TEXT,
                manual_title TEXT,
                manual_notes TEXT,
                manual_tags TEXT,
                short_summary TEXT,
                long_summary TEXT,
                keywords TEXT,
                game TEXT,
                track TEXT,
                car TEXT,
                session_type TEXT,
                visible_apps TEXT,
                issue_keywords TEXT
            );
            """
        )
    connection.commit()


def _fetch_video(connection: sqlite3.Connection, video_id: str) -> dict[str, str] | None:
    connection.row_factory = sqlite3.Row
    row = connection.execute("SELECT * FROM videos WHERE video_id = ?", (video_id,)).fetchone()
    if row is None:
        return None
    return {key: "" if row[key] is None else str(row[key]) for key in row.keys()}


def _fetch_all_videos(connection: sqlite3.Connection) -> list[dict[str, str]]:
    connection.row_factory = sqlite3.Row
    rows = connection.execute("SELECT * FROM videos ORDER BY relative_path, filename").fetchall()
    return [{key: "" if row[key] is None else str(row[key]) for key in row.keys()} for row in rows]


def _fetch_table_rows(connection: sqlite3.Connection, table_name: str, fields: list[str]) -> list[dict[str, str]]:
    connection.row_factory = sqlite3.Row
    rows = connection.execute(f"SELECT {', '.join(fields)} FROM {table_name}").fetchall()
    return [{key: "" if row[key] is None else str(row[key]) for key in row.keys()} for row in rows]


def _upsert_video(connection: sqlite3.Connection, record: dict[str, Any]) -> str:
    existing = _fetch_video(connection, str(record["video_id"]))
    for field in MANUAL_NOTE_FIELDS:
        if existing is not None and field not in record.get("_explicit_manual_fields", set()):
            record[field] = existing.get(field, record.get(field, ""))
    for field in CATALOG_FIELDS:
        record.setdefault(field, "")
    placeholders = ", ".join("?" for _ in CATALOG_FIELDS)
    update_sql = ", ".join(f"{field}=excluded.{field}" for field in CATALOG_FIELDS if field != "video_id")
    connection.execute(
        f"""
        INSERT INTO videos ({", ".join(CATALOG_FIELDS)})
        VALUES ({placeholders})
        ON CONFLICT(video_id) DO UPDATE SET {update_sql}
        """,
        [str(record.get(field, "") or "") for field in CATALOG_FIELDS],
    )
    return "updated" if existing is not None else "added"


def _rebuild_fts(connection: sqlite3.Connection) -> None:
    videos = _fetch_all_videos(connection)
    connection.execute("DELETE FROM archive_search_fts")
    for row in videos:
        connection.execute(
            f"""
            INSERT INTO archive_search_fts (video_id, {", ".join(FTS_FIELDS)})
            VALUES ({", ".join("?" for _ in range(len(FTS_FIELDS) + 1))})
            """,
            [row.get("video_id", ""), *[row.get(field, "") for field in FTS_FIELDS]],
        )
    connection.commit()


def _mark_missing(connection: sqlite3.Connection, scan_roots: list[Path], seen_video_ids: set[str], scan_timestamp: str) -> int:
    if not scan_roots:
        return 0
    rows = _fetch_all_videos(connection)
    missing_count = 0
    root_strings = {str(root.resolve()) for root in scan_roots}
    for row in rows:
        if row.get("video_id", "") in seen_video_ids:
            continue
        if row.get("scan_root", "") not in root_strings:
            continue
        archive_status = row.get("archive_status", "") or "missing"
        connection.execute(
            """
            UPDATE videos
            SET file_status = ?, catalog_status = ?, archive_status = ?, scan_timestamp_utc = ?
            WHERE video_id = ?
            """,
            ("missing", "missing", archive_status, scan_timestamp, row["video_id"]),
        )
        missing_count += 1
    connection.commit()
    return missing_count


def _walk_video_files(root: Path, skip_marker: str) -> tuple[list[Path], list[dict[str, str]]]:
    skipped: list[dict[str, str]] = []
    if root.is_file():
        if root.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS:
            return [root], skipped
        return [], skipped

    videos: list[Path] = []
    marker_name = skip_marker or DEFAULT_SKIP_MARKER
    for current_root, dirs, files in __import__("os").walk(root):
        current = Path(current_root)
        if marker_name in files:
            skipped.append(
                {
                    "path": str(current),
                    "scan_root": str(root.resolve()),
                    "reason": "skip_marker_present",
                    "marker": marker_name,
                }
            )
            dirs[:] = []
            continue
        for filename in files:
            candidate = current / filename
            if candidate.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS:
                videos.append(candidate)
    return sorted(videos), skipped


def _detect_transcript(video_path: Path, output_dir: Path, video_id: str) -> tuple[str, str, str]:
    stem = video_path.stem
    candidates = [
        video_path.with_suffix(".transcript.txt"),
        video_path.parent / f"{stem}.transcript.txt",
        video_path.parent / stem / "transcript" / "transcript.txt",
        output_dir / stem / "transcript" / "transcript.txt",
        output_dir / stem / "transcripts" / f"{video_id}.transcript.txt",
        output_dir / "transcript-only" / "transcripts" / f"{video_id}.transcript.txt",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            text = candidate.read_text(encoding="utf-8", errors="replace")
            return "reused", str(candidate), text[:200000]
    return "skipped", "", ""


def _build_record(
    video_path: Path,
    scan_root: Path,
    catalog_dir: Path,
    output_dir: Path,
    payload: dict[str, Any],
    scan_timestamp: str,
) -> tuple[dict[str, Any], list[dict[str, str]], list[Path]]:
    errors: list[dict[str, str]] = []
    stat = video_path.stat()
    relative_path = _relative_to(video_path, scan_root)
    modified_utc = _iso_from_timestamp(stat.st_mtime)
    created_utc = _iso_from_timestamp(stat.st_ctime)
    video_id = make_video_id(relative_path, stat.st_size, modified_utc, video_path.name)
    capture_date, capture_source = _infer_capture_date(video_path.name, modified_utc)
    hash_mode = _normalize_hash_mode(str(payload.get("hash_mode") or DEFAULT_HASH_MODE))
    thumbnail_mode = _normalize_thumbnail_mode(str(payload.get("thumbnail_mode") or DEFAULT_THUMBNAIL_MODE))
    max_thumbnails = int(payload.get("max_thumbnails_per_video") or DEFAULT_MAX_THUMBNAILS)

    if hash_mode == "Full":
        content_sha256 = _sha256_file(video_path)
        hash_status = "verified_full_sha256"
    elif hash_mode == "Off":
        content_sha256 = ""
        hash_status = "off"
    else:
        content_sha256 = ""
        hash_status = "skipped_fast_mode"

    record: dict[str, Any] = {
        "video_id": video_id,
        "original_path": str(video_path.resolve()),
        "scan_root": str(scan_root.resolve()),
        "relative_path": relative_path,
        "filename": video_path.name,
        "extension": video_path.suffix.lower(),
        "size_bytes": str(stat.st_size),
        "created_utc": created_utc,
        "modified_utc": modified_utc,
        "inferred_capture_date": capture_date,
        "capture_date_source": capture_source,
        "duration": "",
        "width": "",
        "height": "",
        "video_codec": "",
        "audio_present": "",
        "audio_stream_count": "",
        "stream_info_json": "",
        "hash_status": hash_status,
        "content_sha256": content_sha256,
        "proposed_s3_bucket": str(payload.get("s3_bucket") or ""),
        "proposed_s3_prefix": str(payload.get("s3_prefix") or "").strip().strip("/"),
        "proposed_s3_key": "",
        "scan_timestamp_utc": scan_timestamp,
        "media_mangler_version": str(payload.get("media_mangler_version") or ""),
        "file_status": "present",
        "catalog_status": "ok",
        "archive_status": "cataloged",
        "error_message": "",
        "thumbnail_status": "skipped_thumbnail_mode_off" if thumbnail_mode == "Off" else "skipped",
        "thumbnail_count": "0",
        "thumbnail_paths": "",
        "contact_sheet_path": "",
        "transcript_status": "skipped",
        "transcript_path": "",
        "transcript_text": "",
        "short_summary": "",
        "long_summary": "",
        "likely_game": "",
        "track": "",
        "car": "",
        "simulator": "",
        "session_type": "",
        "visible_apps": "",
        "issues_observed": "",
        "keywords": "",
        "confidence": "",
        "manual_title": "",
        "manual_notes": "",
        "manual_tags": "",
        "game": "",
        "issue_keywords": "",
    }
    record["proposed_s3_key"] = _proposed_s3_key(
        record["proposed_s3_prefix"],
        capture_date,
        capture_source,
        video_id,
        video_path.name,
    )

    try:
        record.update(_run_ffprobe(video_path, str(payload.get("ffprobe_path") or "ffprobe")))
    except Exception as exc:
        message = str(exc)
        record["file_status"] = "error"
        record["catalog_status"] = "error"
        record["error_message"] = message
        errors.append(
            {
                "video_id": video_id,
                "path": str(video_path.resolve()),
                "relative_path": relative_path,
                "error_stage": "ffprobe",
                "error_message": message,
            }
        )

    transcript_status, transcript_path, transcript_text = _detect_transcript(video_path, output_dir, video_id)
    record["transcript_status"] = transcript_status
    record["transcript_path"] = transcript_path
    record["transcript_text"] = transcript_text

    thumbnail_paths: list[Path] = []
    if thumbnail_mode == "Auto" and record["catalog_status"] != "error":
        try:
            timestamps = select_thumbnail_timestamps(float(record.get("duration") or 0), max_thumbnails)
            thumb_dir = catalog_dir / "thumbnails" / video_id
            for index, timestamp in enumerate(timestamps, start=1):
                thumb_path = thumb_dir / f"thumb_{index:04d}.jpg"
                _run_ffmpeg_thumbnail(video_path, thumb_path, timestamp, str(payload.get("ffmpeg_path") or "ffmpeg"))
                thumbnail_paths.append(thumb_path)
            contact_sheet_path = catalog_dir / "contact_sheets" / f"{video_id}_contact_sheet.jpg"
            contact_status = _create_contact_sheet(
                thumb_dir,
                thumbnail_paths,
                contact_sheet_path,
                str(payload.get("ffmpeg_path") or "ffmpeg"),
            )
            record["thumbnail_status"] = contact_status
            record["thumbnail_count"] = str(len(thumbnail_paths))
            record["thumbnail_paths"] = ";".join(_relative_to_catalog(str(path), catalog_dir) for path in thumbnail_paths)
            record["contact_sheet_path"] = _relative_to_catalog(str(contact_sheet_path), catalog_dir)
        except Exception as exc:
            message = str(exc)
            record["thumbnail_status"] = "error"
            errors.append(
                {
                    "video_id": video_id,
                    "path": str(video_path.resolve()),
                    "relative_path": relative_path,
                    "error_stage": "thumbnail",
                    "error_message": message,
                }
            )

    return record, errors, thumbnail_paths


def _import_notes(connection: sqlite3.Connection, notes_csv: str) -> list[dict[str, str]]:
    if not notes_csv:
        return []
    notes_path = Path(notes_csv)
    rows = _read_csv(notes_path)
    report: list[dict[str, str]] = []
    for row in rows:
        video_id = str(row.get("video_id") or "").strip()
        if not video_id:
            report.append(
                {
                    "video_id": "",
                    "status": "skipped",
                    "updated_fields": "",
                    "message": "missing video_id",
                }
            )
            continue
        existing = _fetch_video(connection, video_id)
        if existing is None:
            report.append(
                {
                    "video_id": video_id,
                    "status": "skipped",
                    "updated_fields": "",
                    "message": "video_id not found in catalog",
                }
            )
            continue
        update_fields = [field for field in MANUAL_NOTE_FIELDS if field in row]
        if not update_fields:
            report.append(
                {
                    "video_id": video_id,
                    "status": "unchanged",
                    "updated_fields": "",
                    "message": "no recognized manual note fields present",
                }
            )
            continue
        assignments = ", ".join(f"{field} = ?" for field in update_fields)
        connection.execute(
            f"UPDATE videos SET {assignments} WHERE video_id = ?",
            [row.get(field, "") for field in update_fields] + [video_id],
        )
        report.append(
            {
                "video_id": video_id,
                "status": "updated",
                "updated_fields": ";".join(update_fields),
                "message": "",
            }
        )
    connection.commit()
    return report


def _write_sidecars(catalog_dir: Path, rows: list[dict[str, str]]) -> None:
    sidecar_dir = catalog_dir / "sidecars"
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        _write_json(sidecar_dir / f"{row['video_id']}.json", row)


def _write_exports(catalog_dir: Path, rows: list[dict[str, str]], notes_report: list[dict[str, str]]) -> None:
    _write_csv(catalog_dir / "archive_catalog.csv", rows, CATALOG_FIELDS)
    _write_jsonl(catalog_dir / "archive_catalog.jsonl", rows)
    _write_csv(catalog_dir / "archive_integrity_manifest.csv", rows, INTEGRITY_FIELDS)
    _write_csv(catalog_dir / "manual_notes_template.csv", rows, MANUAL_NOTES_TEMPLATE_FIELDS)
    _write_csv(catalog_dir / "manual_notes_import_report.csv", notes_report, NOTES_IMPORT_REPORT_FIELDS)
    _write_sidecars(catalog_dir, rows)

    upload_rows: list[dict[str, str]] = []
    for row in rows:
        upload_rows.append(
            {
                "local_path": row.get("original_path", ""),
                "proposed_s3_bucket": row.get("proposed_s3_bucket", ""),
                "proposed_s3_prefix": row.get("proposed_s3_prefix", ""),
                "proposed_s3_key": row.get("proposed_s3_key", ""),
                "storage_class_target": STORAGE_CLASS_TARGET,
                "size_bytes": row.get("size_bytes", ""),
                "sha256": row.get("content_sha256", ""),
                "hash_status": row.get("hash_status", ""),
                "skip_status": "skipped" if row.get("file_status") == "missing" else "",
                "skip_reason": "missing_from_current_scan" if row.get("file_status") == "missing" else "",
                "metadata_tag_suggestions": _metadata_tags_for_row(row),
            }
        )
    _write_csv(catalog_dir / "archive_upload_manifest.csv", upload_rows, UPLOAD_FIELDS)

    sha_rows = [row for row in rows if row.get("hash_status") == "verified_full_sha256" and row.get("content_sha256")]
    sha_path = catalog_dir / "archive_manifest.sha256.txt"
    if sha_rows:
        sha_path.write_text(
            "".join(f"{row['content_sha256']} *{row['original_path']}\n" for row in sha_rows),
            encoding="utf-8",
        )
    else:
        sha_path.write_text(
            "# No verified SHA-256 rows were produced.\n"
            "# Fast mode records catalog identity, size, mtime, and path metadata only.\n"
            "# Use -ArchiveHashMode Full to compute full-file content hashes.\n",
            encoding="utf-8",
        )

    (catalog_dir / "archive_restore_index.md").write_text(_build_restore_index(rows), encoding="utf-8")


def _metadata_tags_for_row(row: dict[str, str]) -> str:
    tags = []
    for key in ("game", "track", "car", "session_type"):
        value = str(row.get(key, "") or "").strip()
        if value:
            tags.append(f"{key}={value}")
    return ";".join(tags)


def _build_restore_index(rows: list[dict[str, str]]) -> str:
    lines = [
        "# Archive Restore Index",
        "",
        "This is a human lookup aid for choosing which archived object to restore.",
        "",
    ]
    if not rows:
        lines.append("No videos are currently cataloged.")
        return "\n".join(lines).rstrip() + "\n"
    for row in rows:
        notes = row.get("manual_notes", "")
        tags = row.get("manual_tags", "")
        title = row.get("manual_title", "")
        lines.extend(
            [
                f"## {row.get('filename', '')}",
                "",
                f"- Video ID: {row.get('video_id', '')}",
                f"- Manual title: {title}",
                f"- Manual notes: {notes}",
                f"- Manual tags: {tags}",
                f"- Search terms: {row.get('keywords', '') or row.get('issue_keywords', '')}",
                f"- Duration: {row.get('duration', '')}",
                f"- Size bytes: {row.get('size_bytes', '')}",
                f"- SHA-256/hash status: {row.get('content_sha256', '') or '(none)'} / {row.get('hash_status', '')}",
                f"- Proposed S3 bucket/key: {row.get('proposed_s3_bucket', '')} / {row.get('proposed_s3_key', '')}",
                f"- Archive status: {row.get('archive_status', '')}",
                f"- Restore notes: Verify restore need before requesting Deep Archive retrieval.",
                f"- Contact sheet: {row.get('contact_sheet_path', '')}",
                f"- Transcript: {row.get('transcript_path', '')}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _make_fts_query(query: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_./-]+", query)
    if not tokens:
        return ""
    return " AND ".join(f'"{token}"' for token in tokens[:12])


def _search_like(connection: sqlite3.Connection, query: str, limit: int) -> list[dict[str, str]]:
    tokens = [token.lower() for token in re.findall(r"[A-Za-z0-9_./-]+", query)]
    results = []
    for row in _fetch_all_videos(connection):
        haystack = " ".join(str(row.get(field, "") or "") for field in FTS_FIELDS).lower()
        if all(token in haystack for token in tokens):
            row["rank"] = str(len(results) + 1)
            results.append(row)
            if len(results) >= limit:
                break
    return results


def search_catalog_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    catalog_dir = Path(str(payload.get("catalog_path") or "")).expanduser()
    if catalog_dir.name.lower() != "_archive_catalog" and not (catalog_dir / "archive_catalog.sqlite").exists():
        catalog_dir = catalog_dir / "_ARCHIVE_CATALOG"
    db_path = catalog_dir / "archive_catalog.sqlite"
    query = str(payload.get("query") or "").strip()
    limit = int(payload.get("limit") or 25)
    if not db_path.exists():
        raise FileNotFoundError(f"Archive catalog not found: {db_path}")
    if not query:
        raise ValueError("Archive catalog search query is required.")

    connection = sqlite3.connect(db_path)
    _create_schema(connection)
    fts_query = _make_fts_query(query)
    results: list[dict[str, str]]
    try:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT videos.*, bm25(archive_search_fts) AS rank
            FROM archive_search_fts
            JOIN videos ON videos.video_id = archive_search_fts.video_id
            WHERE archive_search_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (fts_query, limit),
        ).fetchall()
        results = [{key: "" if row[key] is None else str(row[key]) for key in row.keys()} for row in rows]
    except sqlite3.OperationalError:
        results = _search_like(connection, query, limit)
    finally:
        connection.close()

    return {
        "catalog_path": str(catalog_dir),
        "query": query,
        "count": len(results),
        "results": [
            {
                "rank": row.get("rank", ""),
                "filename": row.get("filename", ""),
                "relative_path": row.get("relative_path", ""),
                "proposed_s3_key": row.get("proposed_s3_key", ""),
                "duration": row.get("duration", ""),
                "size_bytes": row.get("size_bytes", ""),
                "manual_title": row.get("manual_title", ""),
                "manual_notes": row.get("manual_notes", ""),
                "manual_tags": row.get("manual_tags", ""),
                "summary": row.get("short_summary", ""),
                "keywords": row.get("keywords", "") or row.get("issue_keywords", ""),
                "archive_status": row.get("archive_status", ""),
                "contact_sheet_path": row.get("contact_sheet_path", ""),
            }
            for row in results
        ],
    }


def build_catalog_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    output_dir = Path(str(payload.get("output_dir") or ".")).expanduser().resolve()
    catalog_path_value = str(payload.get("catalog_path") or "").strip()
    catalog_dir = Path(catalog_path_value).expanduser().resolve() if catalog_path_value else output_dir / "_ARCHIVE_CATALOG"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    db_path = catalog_dir / "archive_catalog.sqlite"
    scan_timestamp = _utc_now()
    batch_id = hashlib.sha1(scan_timestamp.encode("utf-8")).hexdigest()[:12]

    input_values = payload.get("input_paths")
    if input_values is None:
        input_value = str(payload.get("input_path") or "").strip()
        input_values = [input_value] if input_value else []
    scan_roots = [Path(str(value)).expanduser().resolve() for value in input_values if str(value or "").strip()]

    skipped_rows: list[dict[str, str]] = []
    error_rows: list[dict[str, str]] = []
    seen_video_ids: set[str] = set()
    scanned_count = 0
    added_count = 0
    updated_count = 0

    connection = sqlite3.connect(db_path)
    _create_schema(connection)

    for scan_input in scan_roots:
        scan_root = scan_input.parent if scan_input.is_file() else scan_input
        videos, skipped = _walk_video_files(scan_input, str(payload.get("skip_marker") or DEFAULT_SKIP_MARKER))
        skipped_rows.extend(skipped)
        for video_path in videos:
            scanned_count += 1
            record, record_errors, _thumbnail_paths = _build_record(
                video_path,
                scan_root,
                catalog_dir,
                output_dir,
                payload,
                scan_timestamp,
            )
            outcome = _upsert_video(connection, record)
            if outcome == "added":
                added_count += 1
            else:
                updated_count += 1
            seen_video_ids.add(str(record["video_id"]))
            error_rows.extend(record_errors)

    missing_count = _mark_missing(connection, [root.parent if root.is_file() else root for root in scan_roots], seen_video_ids, scan_timestamp)
    notes_report = _import_notes(connection, str(payload.get("notes_csv") or ""))
    _rebuild_fts(connection)
    rows = _fetch_all_videos(connection)

    if scan_roots:
        connection.execute("DELETE FROM skipped_paths")
        connection.execute("DELETE FROM errors")
        for row in skipped_rows:
            connection.execute(
                "INSERT INTO skipped_paths (path, scan_root, reason, marker) VALUES (?, ?, ?, ?)",
                [row.get(field, "") for field in SKIPPED_FIELDS],
            )
        for row in error_rows:
            connection.execute(
                "INSERT INTO errors (video_id, path, relative_path, error_stage, error_message) VALUES (?, ?, ?, ?, ?)",
                [row.get(field, "") for field in ERROR_FIELDS],
            )
    else:
        skipped_rows = _fetch_table_rows(connection, "skipped_paths", SKIPPED_FIELDS)
        error_rows = _fetch_table_rows(connection, "errors", ERROR_FIELDS)
    connection.execute(
        """
        INSERT INTO batches (
            batch_id, scan_timestamp_utc, scan_roots_json, scanned_count,
            added_count, updated_count, missing_count, skipped_count, error_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            batch_id,
            scan_timestamp,
            json.dumps([str(root) for root in scan_roots], ensure_ascii=False),
            scanned_count,
            added_count,
            updated_count,
            missing_count,
            len(skipped_rows),
            len(error_rows),
        ),
    )
    connection.commit()
    connection.close()

    _write_exports(catalog_dir, rows, notes_report)
    _write_csv(catalog_dir / "skipped_paths.csv", skipped_rows, SKIPPED_FIELDS)
    _write_csv(catalog_dir / "errors.csv", error_rows, ERROR_FIELDS)
    batch_manifest = {
        "batch_id": batch_id,
        "scan_timestamp_utc": scan_timestamp,
        "catalog_path": str(catalog_dir),
        "sqlite_path": str(db_path),
        "scan_roots": [str(root) for root in scan_roots],
        "hash_mode": _normalize_hash_mode(str(payload.get("hash_mode") or DEFAULT_HASH_MODE)),
        "thumbnail_mode": _normalize_thumbnail_mode(str(payload.get("thumbnail_mode") or DEFAULT_THUMBNAIL_MODE)),
        "skip_marker": str(payload.get("skip_marker") or DEFAULT_SKIP_MARKER),
        "scanned_count": scanned_count,
        "added_count": added_count,
        "updated_count": updated_count,
        "missing_count": missing_count,
        "skipped_count": len(skipped_rows),
        "error_count": len(error_rows),
        "notes_import_count": len([row for row in notes_report if row.get("status") == "updated"]),
        "aws_upload_performed": False,
        "glacier_restore_performed": False,
        "whisper_transcription_performed": False,
    }
    _write_json(catalog_dir / "archive_batch_manifest.json", batch_manifest)

    return {
        **batch_manifest,
        "archive_catalog_sqlite": str(db_path),
        "archive_catalog_csv": str(catalog_dir / "archive_catalog.csv"),
        "archive_catalog_jsonl": str(catalog_dir / "archive_catalog.jsonl"),
        "manual_notes_template": str(catalog_dir / "manual_notes_template.csv"),
        "manual_notes_import_report": str(catalog_dir / "manual_notes_import_report.csv"),
        "archive_restore_index": str(catalog_dir / "archive_restore_index.md"),
        "archive_upload_manifest": str(catalog_dir / "archive_upload_manifest.csv"),
        "archive_manifest_sha256": str(catalog_dir / "archive_manifest.sha256.txt"),
    }
