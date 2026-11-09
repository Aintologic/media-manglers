"""Metadata-only discovery and classification for Review Media Inbox."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Callable, Iterable

from . import inbox_records, recording_identity, review_ledger


DEFAULT_MAX_FILES = 3
DEFAULT_MAX_DURATION_MINUTES = 240
DEFAULT_CONCURRENCY = 1
DEFAULT_PENDING_BATCH_LIMIT = 1
DEFAULT_ORDER = "oldest"
DEFAULT_DEDUPE_MODE = "Fast"
SAMPLE_CHUNK_BYTES = recording_identity.SAMPLE_CHUNK_BYTES
SUPPORTED_EXTENSIONS = {
    ".avi",
    ".m2ts",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".mts",
    ".ts",
    ".webm",
    ".wmv",
}
FULL_SCAN_WARNING = (
    "Full deduplication hashes every stable file in the configured inventory. "
    "It may read multiple terabytes and can take a long time while placing sustained read load on source drives. "
    "Fast is the normal default; Full requires explicit confirmation for this run."
)
PENDING_BATCH_STATES = {
    "preparing",
    "prepared",
    "awaiting_external_review",
    "preliminary_findings_received",
    "targeted_evidence_ready",
    "results_received",
    "finalizing",
}
ELIGIBLE_STATES = {"discovered", "pending", "retryable_failure", "source_changed", "legacy_migration_pending"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _modified_utc(stat: os.stat_result) -> str:
    return datetime.fromtimestamp(stat.st_mtime_ns / 1_000_000_000, timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_path(path: Path | str) -> str:
    return os.path.normcase(os.path.abspath(os.path.expanduser(str(path))))


def sampled_sha256_file(path: Path, *, chunk_bytes: int = SAMPLE_CHUNK_BYTES) -> str:
    # 220: the one "same recording" rule, shared with the raw bin library.
    return recording_identity.sampled_sha256_file(path, chunk_bytes=chunk_bytes)


def full_sha256_file(path: Path) -> str:
    return review_ledger.sha256_file(path)


def _stable_full_hash(path: Path, hasher: Callable[[Path], str]) -> str:
    before = path.stat()
    digest = hasher(path).lower()
    after = path.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise RuntimeError(f"Source changed while hashing: {path}")
    return digest


def resolve_settings(
    cli_values: dict[str, Any] | None,
    local_config: dict[str, Any] | None,
) -> dict[str, Any]:
    cli = dict(cli_values or {})
    config = dict(local_config or {})
    section = config.get("reviewMediaInbox")
    config_section_name = "reviewMediaInbox"
    if not isinstance(section, dict):
        section = config.get("reviewNewVideos")
        config_section_name = "reviewNewVideos" if isinstance(section, dict) else "defaults"
    if not isinstance(section, dict):
        section = {}

    def choose(cli_name: str, config_name: str, default: Any) -> Any:
        if cli_name in cli and cli[cli_name] is not None:
            return cli[cli_name]
        if config_name in section and section[config_name] is not None:
            return section[config_name]
        return default

    dedupe_mode = str(choose("dedupe_mode", "dedupeMode", DEFAULT_DEDUPE_MODE)).strip().title()
    if dedupe_mode not in {"Fast", "Full"}:
        raise ValueError("dedupe_mode must be Fast or Full.")
    order = str(choose("order", "order", DEFAULT_ORDER)).strip().lower()
    if order not in {"oldest", "newest"}:
        raise ValueError("order must be oldest or newest.")
    max_files = int(choose("max_files", "maxFiles", DEFAULT_MAX_FILES))
    max_duration = int(choose("max_duration_minutes", "maxDurationMinutes", DEFAULT_MAX_DURATION_MINUTES))
    concurrency = int(choose("concurrency", "concurrency", DEFAULT_CONCURRENCY))
    pending_limit = int(choose("pending_batch_limit", "pendingBatchLimit", DEFAULT_PENDING_BATCH_LIMIT))
    if max_files < 1:
        raise ValueError("max_files must be at least 1.")
    if max_duration < 1:
        raise ValueError("max_duration_minutes must be at least 1.")
    if concurrency != 1:
        raise ValueError("Review Media Inbox concurrency is fixed at 1 in this foundational release.")
    if pending_limit < 1:
        raise ValueError("pending_batch_limit must be at least 1.")
    source_folders_value = choose("source_folders", "sourceFolders", [])
    source_folders = [str(value) for value in (source_folders_value or []) if str(value).strip()]
    return {
        "source_folders": source_folders,
        "ledger_path": str(choose("ledger_path", "ledgerPath", "")),
        "recurse": bool(choose("recurse", "recurse", True)),
        "dedupe_mode": dedupe_mode,
        "order": order,
        "max_files": max_files,
        "max_duration_minutes": max_duration,
        "concurrency": concurrency,
        "pending_batch_limit": pending_limit,
        "config_section": config_section_name,
        # A saved profile/config must never satisfy the per-run Full warning contract.
        "full_scan_acknowledged": bool(cli.get("full_scan_acknowledged", False)),
    }


def _iter_media_files(source_folders: Iterable[str], recurse: bool, extensions: set[str]) -> tuple[list[Path], list[dict[str, str]]]:
    found: dict[str, Path] = {}
    errors: list[dict[str, str]] = []
    for raw_folder in source_folders:
        folder = Path(raw_folder).expanduser()
        if not folder.exists():
            errors.append({"path": str(folder), "error": "source path does not exist"})
            continue
        candidates: Iterable[Path]
        if folder.is_file():
            candidates = (folder,)
        else:
            candidates = folder.rglob("*") if recurse else folder.glob("*")
        try:
            for candidate in candidates:
                if candidate.is_file() and candidate.suffix.lower() in extensions:
                    found[_normalize_path(candidate)] = candidate
        except OSError as exc:
            errors.append({"path": str(folder), "error": str(exc)})
    return list(found.values()), errors


# 220: the one folder walk for the recordings folders, shared with the raw bin library.
iter_media_files = _iter_media_files


def _source_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return None if row is None else {key: row[key] for key in row.keys()}


def _pending_batches(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT b.batch_id, b.status, b.package_path, b.created_utc,
               COUNT(bs.source_id) AS source_count,
               SUM(CASE WHEN bs.state = 'needs_audio_confirmation' THEN 1 ELSE 0 END) AS blocked_count,
               SUM(CASE WHEN bs.state IN ('retryable_failure', 'source_changed') THEN 1 ELSE 0 END) AS failed_count
        FROM inbox_batches b
        LEFT JOIN inbox_batch_sources bs ON bs.batch_id = b.batch_id
        WHERE b.status NOT IN ('finalized_no_findings', 'finalized_with_findings')
        GROUP BY b.batch_id
        ORDER BY b.created_utc
        """
    ).fetchall()
    batches: list[dict[str, Any]] = []
    for row in rows:
        batch = {key: row[key] for key in row.keys()}
        source_rows = connection.execute(
            """
            SELECT bs.source_id, bs.ordinal, bs.state,
                   s.provisional_identity, s.stable_identity, s.size_bytes,
                   sl.original_path, sl.modified_utc
            FROM inbox_batch_sources bs
            JOIN inbox_sources s ON s.source_id = bs.source_id
            LEFT JOIN inbox_source_locations sl ON sl.location_id = (
                SELECT current.location_id
                FROM inbox_source_locations current
                WHERE current.source_id = bs.source_id AND current.is_current = 1
                ORDER BY current.last_seen_utc DESC, current.location_id DESC
                LIMIT 1
            )
            WHERE bs.batch_id = ?
            ORDER BY bs.ordinal
            """,
            (row["batch_id"],),
        ).fetchall()
        batch["sources"] = [
            {
                "source_id": int(source["source_id"]),
                "path": str(source["original_path"] or ""),
                "identity": str(source["stable_identity"] or source["provisional_identity"] or ""),
                "identity_kind": "stable" if source["stable_identity"] else "provisional",
                "classification": str(source["state"]),
                "pending_batch_excluded": True,
                "size_bytes": int(source["size_bytes"] or 0),
                "modified_utc": str(source["modified_utc"] or ""),
                "batch_ordinal": int(source["ordinal"]),
            }
            for source in source_rows
        ]
        accepted = connection.execute(
            """
            SELECT settings_hash FROM inbox_attempts
            WHERE batch_id = ? AND attempt_type = 'preliminary_findings_import'
              AND status = 'accepted' AND completed_utc IS NOT NULL
            ORDER BY attempt_id DESC LIMIT 1
            """,
            (row["batch_id"],),
        ).fetchone()
        accepted_sha = str(accepted["settings_hash"] or "") if accepted else ""
        raw_finding_rows = connection.execute(
            "SELECT details_json FROM inbox_findings WHERE batch_id = ? AND stage = 'preliminary' ORDER BY finding_id",
            (row["batch_id"],),
        ).fetchall()
        finding_details: list[dict[str, Any]] = []
        for finding_row in raw_finding_rows:
            try:
                details = json.loads(str(finding_row["details_json"] or "{}"))
            except json.JSONDecodeError:
                continue
            if isinstance(details, dict) and (not accepted_sha or str(details.get("submission_sha256") or "") == accepted_sha):
                finding_details.append(details)
        request_count = 0
        for details in finding_details:
            request_count += len(details.get("requests") or [])
        completed_signatures: set[str] = set()
        event_rows = connection.execute(
            "SELECT details_json FROM inbox_lifecycle_events WHERE batch_id = ? AND event_type = 'targeted_evidence_request_completed'",
            (row["batch_id"],),
        ).fetchall()
        for event_row in event_rows:
            try:
                details = json.loads(str(event_row["details_json"] or "{}"))
            except json.JSONDecodeError:
                continue
            if (
                isinstance(details, dict)
                and str(details.get("preliminary_submission_sha256") or "") == accepted_sha
                and details.get("render_signature")
            ):
                completed_signatures.add(str(details["render_signature"]))
        batch["preliminary_finding_count"] = len(finding_details)
        batch["targeted_request_count"] = request_count
        batch["targeted_completed_request_count"] = min(request_count, len(completed_signatures))
        batch["preliminary_submission_sha256"] = accepted_sha
        accepted_results = connection.execute(
            """
            SELECT settings_hash FROM inbox_attempts
            WHERE batch_id = ? AND attempt_type = 'final_results_import'
              AND status = 'accepted' AND completed_utc IS NOT NULL
            ORDER BY attempt_id DESC LIMIT 1
            """,
            (row["batch_id"],),
        ).fetchone()
        batch["final_results_submission_sha256"] = str(accepted_results["settings_hash"] or "") if accepted_results else ""
        batch["final_result_count"] = int(
            connection.execute("SELECT COUNT(*) FROM inbox_final_results WHERE batch_id = ?", (row["batch_id"],)).fetchone()[0]
        )
        finalization = connection.execute(
            """
            SELECT plan_sha256, status, journal_path
            FROM inbox_finalization_runs WHERE batch_id = ?
            ORDER BY updated_utc DESC, plan_sha256 DESC LIMIT 1
            """,
            (row["batch_id"],),
        ).fetchone()
        if finalization is not None:
            plan_sha = str(finalization["plan_sha256"] or "")
            package = Path(str(batch.get("package_path") or ""))
            batch["finalization_plan_sha256"] = plan_sha
            batch["finalization_status"] = str(finalization["status"] or "")
            batch["finalization_journal_path"] = str(finalization["journal_path"] or "")
            batch["finalization_plan_path"] = str(package / ".finalization" / f"plan-{plan_sha[:24]}.json") if plan_sha else ""
        batch["history_destinations"] = [
            str(history[0])
            for history in connection.execute(
                "SELECT history_path FROM inbox_retention_records WHERE batch_id = ? ORDER BY source_id",
                (row["batch_id"],),
            ).fetchall()
        ]
        batches.append(batch)
    return batches


def list_pending_batches(ledger_path: str | Path) -> list[dict[str, Any]]:
    """Return active batches without scanning or reading source media."""

    # A reader (224, F4): it never makes, moves up or locks the ledger.
    connection = inbox_records.connect_read_only(ledger_path)
    if connection is None:
        return []
    try:
        return _pending_batches(connection)
    finally:
        connection.close()


def _pending_source_ids(connection: sqlite3.Connection) -> set[int]:
    rows = connection.execute(
        """
        SELECT DISTINCT bs.source_id
        FROM inbox_batch_sources bs
        JOIN inbox_batches b ON b.batch_id = bs.batch_id
        WHERE b.status NOT IN ('finalized_no_findings', 'finalized_with_findings')
        """
    ).fetchall()
    return {int(row[0]) for row in rows}


def _find_location(connection: sqlite3.Connection, normalized_path: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT l.*, s.provisional_identity, s.stable_identity, s.content_sha256,
               s.sampled_sha256, s.lifecycle_state
        FROM inbox_source_locations l
        JOIN inbox_sources s ON s.source_id = l.source_id
        WHERE l.normalized_path = ? AND l.is_current = 1
        ORDER BY l.last_seen_utc DESC LIMIT 1
        """,
        (normalized_path,),
    ).fetchone()


def _insert_source(
    connection: sqlite3.Connection,
    *,
    path: Path,
    stat: os.stat_result,
    sampled_sha256: str | None,
    content_sha256: str | None,
    state: str,
) -> int:
    modified_utc = _modified_utc(stat)
    provisional = review_ledger.make_provisional_identity(str(path), stat.st_size, modified_utc)
    stable = review_ledger.stable_identity(content_sha256) if content_sha256 else None
    now = _utc_now()
    cursor = connection.execute(
        """
        INSERT INTO inbox_sources
            (provisional_identity, stable_identity, content_sha256, sampled_sha256, size_bytes,
             lifecycle_state, legacy_ledger_id, migration_provenance, first_seen_utc, updated_utc)
        VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
        """,
        (provisional, stable, content_sha256, sampled_sha256, stat.st_size, state, now, now),
    )
    source_id = int(cursor.lastrowid)
    connection.execute(
        """
        INSERT INTO inbox_source_locations
            (source_id, original_path, normalized_path, size_bytes, modified_utc, modified_ns,
             is_current, first_seen_utc, last_seen_utc)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (source_id, str(path), _normalize_path(path), stat.st_size, modified_utc, stat.st_mtime_ns, now, now),
    )
    review_ledger._insert_lifecycle_event(
        connection,
        source_id=source_id,
        batch_id=None,
        event_type="source_discovered",
        to_state=state,
        details={"identity_kind": "stable" if content_sha256 else "provisional"},
    )
    return source_id


def _add_location(connection: sqlite3.Connection, source_id: int, path: Path, stat: os.stat_result) -> None:
    now = _utc_now()
    connection.execute("UPDATE inbox_source_locations SET is_current = 0 WHERE source_id = ?", (source_id,))
    connection.execute(
        """
        INSERT INTO inbox_source_locations
            (source_id, original_path, normalized_path, size_bytes, modified_utc, modified_ns,
             is_current, first_seen_utc, last_seen_utc)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(source_id, normalized_path) DO UPDATE SET
            original_path=excluded.original_path,
            size_bytes=excluded.size_bytes,
            modified_utc=excluded.modified_utc,
            modified_ns=excluded.modified_ns,
            is_current=1,
            last_seen_utc=excluded.last_seen_utc
        """,
        (source_id, str(path), _normalize_path(path), stat.st_size, _modified_utc(stat), stat.st_mtime_ns, now, now),
    )


def _has_other_live_location(connection: sqlite3.Connection, source_id: int, current_path: Path) -> bool:
    rows = connection.execute(
        "SELECT original_path FROM inbox_source_locations WHERE source_id = ? AND is_current = 1",
        (source_id,),
    ).fetchall()
    current_normalized = _normalize_path(current_path)
    return any(
        _normalize_path(str(row[0])) != current_normalized and Path(str(row[0])).exists()
        for row in rows
    )


def _update_seen_location(connection: sqlite3.Connection, location_id: int, path: Path, stat: os.stat_result) -> None:
    connection.execute(
        """
        UPDATE inbox_source_locations
        SET original_path = ?, size_bytes = ?, modified_utc = ?, modified_ns = ?, last_seen_utc = ?, is_current = 1
        WHERE location_id = ?
        """,
        (str(path), stat.st_size, _modified_utc(stat), stat.st_mtime_ns, _utc_now(), location_id),
    )


def scan_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    cli_values = payload.get("cli") if isinstance(payload.get("cli"), dict) else payload
    settings = resolve_settings(cli_values, config)
    if not settings["ledger_path"]:
        raise ValueError("ledger_path is required for Review Media Inbox scanning.")
    if not settings["source_folders"]:
        raise ValueError("At least one source folder is required for Review Media Inbox scanning.")
    if settings["dedupe_mode"] == "Full" and not settings["full_scan_acknowledged"]:
        raise ValueError(FULL_SCAN_WARNING)

    extension_values = payload.get("extensions") or cli_values.get("extensions") or SUPPORTED_EXTENSIONS
    extensions = {str(value).lower() if str(value).startswith(".") else f".{str(value).lower()}" for value in extension_values}
    files, scan_errors = _iter_media_files(settings["source_folders"], settings["recurse"], extensions)
    files.sort(key=lambda item: (_normalize_path(item)))

    full_hasher = payload.get("full_hasher") if callable(payload.get("full_hasher")) else full_sha256_file
    sample_hasher = payload.get("sample_hasher") if callable(payload.get("sample_hasher")) else sampled_sha256_file
    cancel_requested = payload.get("cancel_requested") if callable(payload.get("cancel_requested")) else (lambda: False)
    connection = inbox_records.connect(settings["ledger_path"])
    results: list[dict[str, Any]] = []
    full_hash_count = 0
    sampled_hash_count = 0
    cancelled = False
    try:
        pending_batches = _pending_batches(connection)
        pending_source_ids = _pending_source_ids(connection)
        for path in files:
            if cancel_requested():
                cancelled = True
                break
            try:
                stat = path.stat()
                normalized = _normalize_path(path)
                existing_location = _find_location(connection, normalized)
                unchanged = (
                    existing_location is not None
                    and int(existing_location["size_bytes"]) == int(stat.st_size)
                    and existing_location["modified_ns"] is not None
                    and int(existing_location["modified_ns"]) == int(stat.st_mtime_ns)
                )
                if unchanged and settings["dedupe_mode"] == "Fast":
                    source_id = int(existing_location["source_id"])
                    _update_seen_location(connection, int(existing_location["location_id"]), path, stat)
                    classification = str(existing_location["lifecycle_state"])
                    identity = str(existing_location["stable_identity"] or existing_location["provisional_identity"])
                    results.append(
                        {
                            "path": str(path),
                            "source_id": source_id,
                            "identity": identity,
                            "classification": classification,
                            "identity_kind": "stable" if existing_location["stable_identity"] else "provisional",
                            "pending_batch_excluded": source_id in pending_source_ids,
                            "size_bytes": stat.st_size,
                            "modified_utc": _modified_utc(stat),
                            "modified_ns": stat.st_mtime_ns,
                            "sampled_sha256": str(
                                existing_location["sampled_sha256"] or ""
                            ),
                            "content_sha256": str(
                                existing_location["content_sha256"] or ""
                            ),
                        }
                    )
                    continue

                # 224 (Wave B1): what the recordings before this one wrote is committed before this one is
                # read, so no write transaction is open while a recording is hashed (a Full scan can hash for
                # minutes). A recording the Fast scan finds unchanged is never read, so its seen time simply
                # waits for the next commit.
                if connection.in_transaction:
                    connection.commit()
                sampled = sample_hasher(path)
                sampled_hash_count += 1
                sample_matches = connection.execute(
                    "SELECT * FROM inbox_sources WHERE size_bytes = ? AND sampled_sha256 = ? ORDER BY source_id",
                    (stat.st_size, sampled),
                ).fetchall()
                should_full_hash = settings["dedupe_mode"] == "Full"
                if existing_location is not None and existing_location["content_sha256"]:
                    should_full_hash = True
                if any(row["content_sha256"] for row in sample_matches):
                    should_full_hash = True

                content_sha256: str | None = None
                if should_full_hash:
                    content_sha256 = _stable_full_hash(path, full_hasher)
                    full_hash_count += 1

                content_match = None
                if content_sha256:
                    content_match = connection.execute(
                        "SELECT * FROM inbox_sources WHERE content_sha256 = ? ORDER BY source_id LIMIT 1",
                        (content_sha256,),
                    ).fetchone()

                if (
                    existing_location is not None
                    and existing_location["content_sha256"]
                    and content_sha256
                    and existing_location["content_sha256"] != content_sha256
                ):
                    connection.execute(
                        "UPDATE inbox_source_locations SET is_current = 0 WHERE location_id = ?",
                        (existing_location["location_id"],),
                    )
                    source_id = _insert_source(
                        connection,
                        path=path,
                        stat=stat,
                        sampled_sha256=sampled,
                        content_sha256=content_sha256,
                        state="source_changed",
                    )
                    classification = "source_changed"
                elif content_match is not None and (existing_location is None or int(content_match["source_id"]) != int(existing_location["source_id"])):
                    canonical_source_id = int(content_match["source_id"])
                    if _has_other_live_location(connection, canonical_source_id, path):
                        source_id = _insert_source(
                            connection,
                            path=path,
                            stat=stat,
                            sampled_sha256=sampled,
                            content_sha256=content_sha256,
                            state="duplicate",
                        )
                        classification = "duplicate"
                    else:
                        source_id = canonical_source_id
                        _add_location(connection, source_id, path, stat)
                        connection.execute(
                            "UPDATE inbox_sources SET sampled_sha256 = ?, updated_utc = ? WHERE source_id = ?",
                            (sampled, _utc_now(), source_id),
                        )
                        classification = "relocated"
                        review_ledger._insert_lifecycle_event(
                            connection,
                            source_id=source_id,
                            batch_id=None,
                            event_type="source_relocated",
                            details={"identity": review_ledger.stable_identity(content_sha256)},
                        )
                elif existing_location is not None:
                    source_id = int(existing_location["source_id"])
                    _update_seen_location(connection, int(existing_location["location_id"]), path, stat)
                    connection.execute(
                        """
                        UPDATE inbox_sources SET sampled_sha256 = ?, content_sha256 = COALESCE(?, content_sha256),
                            stable_identity = COALESCE(?, stable_identity), size_bytes = ?, updated_utc = ?
                        WHERE source_id = ?
                        """,
                        (
                            sampled,
                            content_sha256,
                            review_ledger.stable_identity(content_sha256) if content_sha256 else None,
                            stat.st_size,
                            _utc_now(),
                            source_id,
                        ),
                    )
                    classification = str(existing_location["lifecycle_state"])
                else:
                    source_id = _insert_source(
                        connection,
                        path=path,
                        stat=stat,
                        sampled_sha256=sampled,
                        content_sha256=content_sha256,
                        state="pending",
                    )
                    classification = "pending"

                source = connection.execute("SELECT * FROM inbox_sources WHERE source_id = ?", (source_id,)).fetchone()
                identity = str(source["stable_identity"] or source["provisional_identity"])
                results.append(
                    {
                        "path": str(path),
                        "source_id": source_id,
                        "identity": identity,
                        "classification": classification,
                        "identity_kind": "stable" if source["stable_identity"] else "provisional",
                        "pending_batch_excluded": source_id in pending_source_ids,
                        "size_bytes": stat.st_size,
                        "modified_utc": _modified_utc(stat),
                        "modified_ns": stat.st_mtime_ns,
                        "sampled_sha256": str(source["sampled_sha256"] or ""),
                        "content_sha256": str(source["content_sha256"] or ""),
                    }
                )
            except (OSError, RuntimeError) as exc:
                scan_errors.append({"path": str(path), "error": str(exc)})
        connection.commit()
    finally:
        connection.close()

    reverse = settings["order"] == "newest"
    results.sort(key=lambda item: (item["modified_utc"], item["path"].casefold()), reverse=reverse)
    eligible = [
        item
        for item in results
        if item["classification"] in ELIGIBLE_STATES and not item["pending_batch_excluded"]
    ]
    pending_limit_reached = len(pending_batches) >= settings["pending_batch_limit"]
    selected = [] if pending_limit_reached or cancelled else eligible[: settings["max_files"]]
    counts: dict[str, int] = {}
    for item in results:
        counts[item["classification"]] = counts.get(item["classification"], 0) + 1

    return {
        "contract_version": 1,
        "scan_only": True,
        "cancelled": cancelled,
        "complete": not cancelled,
        "settings": settings,
        "soft_duration_boundary": {
            "minutes": settings["max_duration_minutes"],
            "meaning": "Once elapsed time reaches the limit, do not start another source; allow the current source to finish safely.",
            "hard_wall_clock": False,
        },
        "full_scan_warning": FULL_SCAN_WARNING,
        "full_scan_warning_required": settings["dedupe_mode"] == "Full",
        "inventory_count": len(results),
        "classification_counts": counts,
        "sources": results,
        "eligible_count": len(eligible),
        "selected_sources": selected,
        "pending_batches": pending_batches,
        "pending_batch_limit_reached": pending_limit_reached,
        "hash_behavior": {
            "sampled_sha256_calls": sampled_hash_count,
            "full_sha256_calls": full_hash_count,
        },
        "scan_errors": scan_errors,
        "preparation_performed": False,
    }
