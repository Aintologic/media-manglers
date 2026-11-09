"""Versioned SQLite ledger for the Review Media Inbox workflow.

This module keeps the ledger's names, its structure and its migrate and validate helpers. Since Wave B1 (224) it
never opens the ledger itself: every connection comes from ``inbox_records``, which also makes and moves up a
ledger (``inbox_records.ensure_structure``) and is the only Inbox code that does.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any


SCHEMA_VERSION = 2
FINALIZED_BATCH_STATES = {"finalized_no_findings", "finalized_with_findings"}
# 224 (Wave B2b): the Inbox's records live in the library, each ledger table under its own name with ``inbox_``
# in front, in the order a copy fills them (every table after the ones it points at). ``relocation_runs`` is in a
# ledger only when a relocation ever ran.
INBOX_TABLES = {
    "schema_metadata": "inbox_metadata",
    "reviews": "inbox_legacy_reviews",
    "sources": "inbox_sources",
    "source_locations": "inbox_source_locations",
    "batches": "inbox_batches",
    "batch_sources": "inbox_batch_sources",
    "attempts": "inbox_attempts",
    "findings": "inbox_findings",
    "lifecycle_events": "inbox_lifecycle_events",
    "final_results": "inbox_final_results",
    "finalization_runs": "inbox_finalization_runs",
    "retention_records": "inbox_retention_records",
    "relocation_runs": "inbox_relocation_runs",
}
# The relocation tool's own record of each relocation (89); its table was made by the tool itself.
RELOCATION_TABLE = """
CREATE TABLE IF NOT EXISTS relocation_runs (
    operation_id TEXT PRIMARY KEY,
    plan_sha256 TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    journal_path TEXT NOT NULL,
    backup_path TEXT NOT NULL,
    mappings_json TEXT NOT NULL,
    counts_json TEXT NOT NULL,
    created_utc TEXT NOT NULL,
    updated_utc TEXT NOT NULL,
    completed_utc TEXT
)
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _backup_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _normalize_path(path_value: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.expanduser(str(path_value or ""))))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def make_fast_key(original_path: str, size_bytes: int, modified_utc: str) -> str:
    return f"{_normalize_path(original_path)}|{int(size_bytes)}|{modified_utc}"


def make_provisional_identity(original_path: str, size_bytes: int, modified_utc: str) -> str:
    token = _sha256_text(make_fast_key(original_path, size_bytes, modified_utc))
    return f"provisional:{token}"


def stable_identity(content_sha256: str) -> str:
    value = str(content_sha256 or "").strip().lower()
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("content_sha256 must be 64 lowercase hexadecimal characters.")
    return f"sha256:{value}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _legacy_schema_statements() -> tuple[str, ...]:
    return (
        """
        CREATE TABLE IF NOT EXISTS reviews (
            ledger_id TEXT PRIMARY KEY,
            original_path TEXT NOT NULL,
            normalized_original_path TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            modified_utc TEXT NOT NULL,
            content_sha256 TEXT,
            reviewed_utc TEXT,
            candidate_count INTEGER DEFAULT 0,
            explicit_count INTEGER DEFAULT 0,
            likely_count INTEGER DEFAULT 0,
            weak_count INTEGER DEFAULT 0,
            review_needed_count INTEGER DEFAULT 0,
            kept_package_path TEXT,
            status TEXT NOT NULL,
            media_mangler_version TEXT,
            error_message TEXT,
            created_utc TEXT NOT NULL,
            updated_utc TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_reviews_fast_key ON reviews(normalized_original_path, size_bytes, modified_utc)",
        "CREATE INDEX IF NOT EXISTS idx_reviews_sha ON reviews(content_sha256)",
        "CREATE INDEX IF NOT EXISTS idx_reviews_status ON reviews(status)",
    )


def _v2_schema_statements() -> tuple[str, ...]:
    return (
        "CREATE TABLE IF NOT EXISTS schema_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        """
        CREATE TABLE IF NOT EXISTS sources (
            source_id INTEGER PRIMARY KEY AUTOINCREMENT,
            provisional_identity TEXT NOT NULL UNIQUE,
            stable_identity TEXT,
            content_sha256 TEXT,
            sampled_sha256 TEXT,
            size_bytes INTEGER NOT NULL,
            lifecycle_state TEXT NOT NULL,
            legacy_ledger_id TEXT UNIQUE,
            migration_provenance TEXT,
            first_seen_utc TEXT NOT NULL,
            updated_utc TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_sources_stable_identity ON sources(stable_identity)",
        "CREATE INDEX IF NOT EXISTS idx_sources_content_sha256 ON sources(content_sha256)",
        "CREATE INDEX IF NOT EXISTS idx_sources_sampled_sha256 ON sources(sampled_sha256, size_bytes)",
        "CREATE INDEX IF NOT EXISTS idx_sources_lifecycle_state ON sources(lifecycle_state)",
        """
        CREATE TABLE IF NOT EXISTS source_locations (
            location_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
            original_path TEXT NOT NULL,
            normalized_path TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            modified_utc TEXT NOT NULL,
            modified_ns INTEGER,
            is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
            first_seen_utc TEXT NOT NULL,
            last_seen_utc TEXT NOT NULL,
            UNIQUE(source_id, normalized_path)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_source_locations_path ON source_locations(normalized_path)",
        "CREATE INDEX IF NOT EXISTS idx_source_locations_current ON source_locations(source_id, is_current)",
        """
        CREATE TABLE IF NOT EXISTS batches (
            batch_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            package_path TEXT,
            is_legacy INTEGER NOT NULL DEFAULT 0 CHECK (is_legacy IN (0, 1)),
            created_utc TEXT NOT NULL,
            updated_utc TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_batches_status ON batches(status)",
        """
        CREATE TABLE IF NOT EXISTS batch_sources (
            batch_id TEXT NOT NULL REFERENCES batches(batch_id) ON DELETE CASCADE,
            source_id INTEGER NOT NULL REFERENCES sources(source_id) ON DELETE RESTRICT,
            ordinal INTEGER NOT NULL,
            state TEXT NOT NULL,
            preparation_signature TEXT,
            added_utc TEXT NOT NULL,
            updated_utc TEXT NOT NULL,
            PRIMARY KEY(batch_id, source_id),
            UNIQUE(batch_id, ordinal)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_batch_sources_source ON batch_sources(source_id, state)",
        """
        CREATE TABLE IF NOT EXISTS attempts (
            attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
            batch_id TEXT REFERENCES batches(batch_id) ON DELETE SET NULL,
            attempt_type TEXT NOT NULL,
            status TEXT NOT NULL,
            started_utc TEXT NOT NULL,
            completed_utc TEXT,
            settings_hash TEXT,
            error_message TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_attempts_source ON attempts(source_id, started_utc)",
        """
        CREATE TABLE IF NOT EXISTS findings (
            finding_id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL REFERENCES batches(batch_id) ON DELETE CASCADE,
            source_id INTEGER NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
            stage TEXT NOT NULL,
            status TEXT NOT NULL,
            start_seconds REAL,
            end_seconds REAL,
            details_json TEXT NOT NULL DEFAULT '{}',
            created_utc TEXT NOT NULL,
            updated_utc TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_findings_source ON findings(source_id, stage)",
        """
        CREATE TABLE IF NOT EXISTS lifecycle_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER REFERENCES sources(source_id) ON DELETE CASCADE,
            batch_id TEXT REFERENCES batches(batch_id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            from_state TEXT,
            to_state TEXT,
            details_json TEXT NOT NULL DEFAULT '{}',
            created_utc TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_lifecycle_events_source ON lifecycle_events(source_id, event_id)",
        """
        CREATE TABLE IF NOT EXISTS final_results (
            result_id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL REFERENCES batches(batch_id) ON DELETE CASCADE,
            source_id INTEGER NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
            finding_id TEXT UNIQUE REFERENCES findings(finding_id) ON DELETE SET NULL,
            submission_sha256 TEXT NOT NULL,
            preliminary_submission_sha256 TEXT NOT NULL,
            disposition TEXT NOT NULL,
            issue_repository TEXT,
            issue_number INTEGER,
            issue_url TEXT,
            issue_action TEXT,
            authorization_note TEXT,
            start_seconds REAL,
            end_seconds REAL,
            summary TEXT NOT NULL,
            notes TEXT NOT NULL,
            external_assertions_json TEXT NOT NULL DEFAULT '[]',
            details_json TEXT NOT NULL DEFAULT '{}',
            created_utc TEXT NOT NULL,
            updated_utc TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_final_results_batch_source ON final_results(batch_id, source_id)",
        "CREATE INDEX IF NOT EXISTS idx_final_results_submission ON final_results(batch_id, submission_sha256)",
        """
        CREATE TABLE IF NOT EXISTS finalization_runs (
            plan_sha256 TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL UNIQUE REFERENCES batches(batch_id) ON DELETE CASCADE,
            results_submission_sha256 TEXT NOT NULL,
            preliminary_submission_sha256 TEXT NOT NULL,
            status TEXT NOT NULL,
            journal_path TEXT NOT NULL,
            created_utc TEXT NOT NULL,
            updated_utc TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_finalization_runs_status ON finalization_runs(status)",
        """
        CREATE TABLE IF NOT EXISTS retention_records (
            plan_sha256 TEXT NOT NULL REFERENCES finalization_runs(plan_sha256) ON DELETE CASCADE,
            batch_id TEXT NOT NULL REFERENCES batches(batch_id) ON DELETE CASCADE,
            source_id INTEGER NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
            resulting_state TEXT NOT NULL,
            history_path TEXT NOT NULL,
            retained_bytes INTEGER NOT NULL,
            disposable_bytes INTEGER NOT NULL,
            history_integrity_sha256 TEXT NOT NULL,
            created_utc TEXT NOT NULL,
            PRIMARY KEY(plan_sha256, source_id)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_retention_records_batch ON retention_records(batch_id, source_id)",
    )


_TABLE_NAME = re.compile(r"\b(TABLE IF NOT EXISTS|REFERENCES|ON)\s+([a-z_]+)\b")


def _in_library(statement: str) -> str:
    """A ledger structure statement for the library: every table named with ``inbox_`` in front, every index
    too (an index name is shared by the whole database)."""

    renamed = _TABLE_NAME.sub(lambda match: f"{match.group(1)} {INBOX_TABLES.get(match.group(2), match.group(2))}",
                              statement)
    return renamed.replace("INDEX IF NOT EXISTS idx_", "INDEX IF NOT EXISTS idx_inbox_")


def library_schema_statements() -> tuple[str, ...]:
    """The Inbox's tables and indexes in the library (its structure step 5): the ledger's own, renamed."""

    return tuple(_in_library(statement)
                 for statement in (*_legacy_schema_statements(), *_v2_schema_statements(), RELOCATION_TABLE))


# The rules the library keeps for the Inbox once its records are in (224, design 3.6): an accepted final result
# is never changed or removed, a retention record never changed except where its history now is (the relocation
# tool moves it with the Inbox folder) and never removed, and no recording the Inbox knows is ever removed. The
# move switches them on as its last database step, so undoing a failed move before that is a plain delete.
_RETENTION_FIXED_COLUMNS = ("plan_sha256", "batch_id", "source_id", "resulting_state", "retained_bytes",
                            "disposable_bytes", "history_integrity_sha256", "created_utc")
GUARD_TRIGGERS = ("inbox_final_results_never_changed", "inbox_final_results_never_removed",
                  "inbox_retention_records_never_changed", "inbox_retention_records_never_removed",
                  "inbox_sources_never_removed")


def library_guard_statements() -> tuple[str, ...]:
    changed = " OR ".join(f"OLD.{column} IS NOT NEW.{column}" for column in _RETENTION_FIXED_COLUMNS)
    return (
        "CREATE TRIGGER IF NOT EXISTS inbox_final_results_never_changed BEFORE UPDATE ON inbox_final_results "
        "BEGIN SELECT RAISE(ABORT, 'An accepted Inbox final result is never changed.'); END",
        "CREATE TRIGGER IF NOT EXISTS inbox_final_results_never_removed BEFORE DELETE ON inbox_final_results "
        "BEGIN SELECT RAISE(ABORT, 'An accepted Inbox final result is never removed.'); END",
        "CREATE TRIGGER IF NOT EXISTS inbox_retention_records_never_changed BEFORE UPDATE ON inbox_retention_records "
        f"WHEN {changed} BEGIN SELECT RAISE(ABORT, 'An Inbox retention record is never changed, except where its "
        "history is.'); END",
        "CREATE TRIGGER IF NOT EXISTS inbox_retention_records_never_removed BEFORE DELETE ON inbox_retention_records "
        "BEGIN SELECT RAISE(ABORT, 'An Inbox retention record is never removed.'); END",
        "CREATE TRIGGER IF NOT EXISTS inbox_sources_never_removed BEFORE DELETE ON inbox_sources "
        "BEGIN SELECT RAISE(ABORT, 'A recording the Inbox knows is never removed.'); END",
    )


def _insert_lifecycle_event(
    connection: sqlite3.Connection,
    *,
    source_id: int | None,
    batch_id: str | None,
    event_type: str,
    from_state: str = "",
    to_state: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO inbox_lifecycle_events
            (source_id, batch_id, event_type, from_state, to_state, details_json, created_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (source_id, batch_id, event_type, from_state, to_state, json.dumps(details or {}, sort_keys=True), _utc_now()),
    )


def validate_ledger(connection: sqlite3.Connection, names: dict[str, str] | None = None) -> dict[str, int]:
    """The ledger's own rules. ``names`` maps each ledger table to the name it has where it is checked: the
    ledger's own names (the default), or ``INBOX_TABLES`` for the Inbox's records in the library (224, Wave B2b),
    where the link check covers only the Inbox's tables."""

    t = {table: (names or {}).get(table, table) for table in INBOX_TABLES}
    legacy_count = int(connection.execute(f"SELECT COUNT(*) FROM {t['reviews']}").fetchone()[0])
    migrated_count = int(
        connection.execute(f"SELECT COUNT(*) FROM {t['sources']} WHERE legacy_ledger_id IS NOT NULL").fetchone()[0]
    )
    if legacy_count != migrated_count:
        raise RuntimeError(
            f"Ledger migration row-count mismatch: legacy={legacy_count}, migrated={migrated_count}."
        )
    if names:
        foreign_key_rows = [row for table in t.values() if _table_exists(connection, table)
                            for row in connection.execute(f"PRAGMA foreign_key_check({table})").fetchall()]
    else:
        foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_rows:
        raise RuntimeError(f"Ledger foreign-key validation failed for {len(foreign_key_rows)} row(s).")
    missing_locations = int(
        connection.execute(
            f"""
            SELECT COUNT(*) FROM {t['sources']} s
            WHERE s.legacy_ledger_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM {t['source_locations']} l WHERE l.source_id = s.source_id)
            """
        ).fetchone()[0]
    )
    if missing_locations:
        raise RuntimeError(f"Ledger migration left {missing_locations} legacy source(s) without a location.")
    invalid_discarded = int(
        connection.execute(
            f"""
            SELECT COUNT(*) FROM {t['sources']} s
            JOIN {t['reviews']} r ON r.ledger_id = s.legacy_ledger_id
            WHERE lower(r.status) = 'discarded' AND s.lifecycle_state <> 'pending'
            """
        ).fetchone()[0]
    )
    if invalid_discarded:
        raise RuntimeError("One or more legacy discarded rows were not requeued as pending.")
    invalid_batch_links = int(
        connection.execute(
            f"""
            SELECT COUNT(*) FROM {t['batch_sources']} bs
            LEFT JOIN {t['batches']} b ON b.batch_id = bs.batch_id
            LEFT JOIN {t['sources']} s ON s.source_id = bs.source_id
            WHERE b.batch_id IS NULL OR s.source_id IS NULL
            """
        ).fetchone()[0]
    )
    if invalid_batch_links:
        raise RuntimeError(f"Ledger contains {invalid_batch_links} invalid batch/source relationship(s).")
    return {
        "legacy_row_count": legacy_count,
        "migrated_provenance_count": migrated_count,
        "foreign_key_violation_count": 0,
        "missing_location_count": 0,
        "invalid_batch_relationship_count": 0,
    }


def _inbox_records():
    # The store imports this module for its structure; this module reaches the store only when a helper runs.
    from . import inbox_records  # noqa: PLC0415

    return inbox_records


def migrate_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """``review-ledger-migrate`` since the Inbox's records live in the library (224, Wave B2b): the library's
    front door moves its structure up whenever it opens, so this opens the Inbox's records for writing (the
    command line runs it under the Inbox's lock) and checks them. It never makes a ledger file and never moves a
    ledger in (only the Workbench's start does that, once)."""

    inbox_records = _inbox_records()
    if not str(payload.get("ledger_path") or payload.get("inbox_folder") or ""):
        raise ValueError("ledger_path is required.")
    connection = inbox_records.connect(payload, must_exist=True)
    try:
        return {"migrated": False, "backup_path": "", **inbox_records.validate(connection)}
    finally:
        connection.close()


def validate_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    # A check only reads (224, F4): it never makes records where there are none.
    inbox_records = _inbox_records()
    connection = inbox_records.connect_read_only(payload)
    if connection is None:
        folder = inbox_records.workspace(payload)
        raise ValueError(f"There are no Review Media Inbox records for {folder}.")
    try:
        return inbox_records.validate(connection)
    finally:
        connection.close()
