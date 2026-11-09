from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core import inbox_records, recording_records, review_inbox, review_ledger, review_queue
from media_manglers.cli import main
from media_manglers.contracts import CommandEnvelope, read_json_file, write_json_file
import pytest
from tests import inbox_library  # noqa: E402

# 224 (Wave B2b): the Inbox's records are in this test's library, moved in (nothing to move).
pytestmark = pytest.mark.inbox_moved


LEGACY_SCHEMA = """
CREATE TABLE reviews (
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
);
CREATE INDEX idx_reviews_fast_key ON reviews(normalized_original_path, size_bytes, modified_utc);
CREATE INDEX idx_reviews_sha ON reviews(content_sha256);
CREATE INDEX idx_reviews_status ON reviews(status);
"""


def _insert_legacy_row(
    connection: sqlite3.Connection,
    *,
    ledger_id: str,
    path: Path,
    status: str,
    content_sha256: str = "",
    package_path: str = "",
) -> None:
    now = "2026-07-01T00:00:00Z"
    connection.execute(
        """
        INSERT INTO reviews (
            ledger_id, original_path, normalized_original_path, size_bytes, modified_utc,
            content_sha256, reviewed_utc, candidate_count, explicit_count, likely_count,
            weak_count, review_needed_count, kept_package_path, status, media_mangler_version,
            error_message, created_utc, updated_utc
        ) VALUES (?, ?, ?, 100, ?, ?, ?, 0, 0, 0, 0, 0, ?, ?, '0.9.4', '', ?, ?)
        """,
        (ledger_id, str(path), os.path.normcase(os.path.abspath(path)), now, content_sha256, now, package_path, status, now, now),
    )


class OlderLedgerIsNotMovedTests(unittest.TestCase):
    """224 (Wave B2b): the in-place upgrade of a v0.9 ledger (the reviews table only) is gone with the ledger
    itself. The one-time move takes only a version 2 ledger; an older one is refused in a plain line and nothing
    changes: the ledger keeps every byte, no note takes its place, and the library holds no Inbox record."""

    def _legacy_ledger(self, root: Path) -> Path:
        ledger = root / "review-ledger.sqlite"
        connection = sqlite3.connect(ledger)
        connection.executescript(LEGACY_SCHEMA)
        for index, status in enumerate(("discarded", "kept", "skipped_duplicate"), start=1):
            _insert_legacy_row(connection, ledger_id=f"row-{index}", path=root / f"legacy-{index}.mkv", status=status)
        connection.commit()
        connection.close()
        return ledger

    def test_a_v0_9_ledger_is_refused_by_the_move_and_left_exactly_as_it_was(self) -> None:
        from media_manglers.core import inbox_move, recording_records  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as library_dir:
            root = Path(temp_dir)
            inbox_library.use_own_library(self, Path(library_dir))
            ledger = self._legacy_ledger(root)
            before = ledger.read_bytes()
            records = recording_records.Records()
            try:
                result = inbox_move.move_ledger(
                    records, {"review_ledger_path": str(ledger)}, settings_path=root / "settings.json",
                    profiles_dir=None, version="test", save_folder=lambda _folder: self.fail("no settings change"))
                connection = records.connection()
                statuses = [row[0] for row in connection.execute(
                    "SELECT status FROM legacy_imports WHERE source = ?", (inbox_records.RECEIPT_SOURCE,))]
                rows = sum(int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                           for table in review_ledger.INBOX_TABLES.values())
                registered = inbox_records.registered_folder(connection)
            finally:
                records.close()
            self.assertEqual(result.status, "restored")
            self.assertIn("structure 0", result.message)
            self.assertIn("only a version 2 ledger is moved", result.message)
            self.assertEqual(statuses, ["restored"])
            self.assertEqual(rows, 0)
            self.assertIsNone(registered)
            self.assertEqual(ledger.read_bytes(), before)
            inbox_records.release_all()
            # The move held the Inbox's lock (its .orchestration folder); no note and no moved copy were made.
            self.assertEqual(sorted(path.name for path in root.iterdir()),
                             [".orchestration", "review-ledger.sqlite"], "no note and no moved copy")
            self.assertEqual(review_ledger.SCHEMA_VERSION, 2, "the preparation signature's number stays 2")


class ExistingLedgerV2CompatibilityTests(unittest.TestCase):
    STATES = (
        "discovered",
        "pending",
        "preparing",
        "prepared",
        "awaiting_external_review",
        "preliminary_findings_received",
        "targeted_evidence_ready",
        "results_received",
        "finalizing",
        "finalized_no_findings",
        "finalized_with_findings",
        "needs_manual_review",
        "needs_audio_confirmation",
        "retryable_failure",
        "source_changed",
        "duplicate",
        "legacy_migration_pending",
    )

    def test_existing_v2_packages_cover_every_lifecycle_state_without_migration(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue_root = Path(temp_dir) / "review-inbox"
            ledger = queue_root / "review-ledger.sqlite"
            inbox_library.ready(ledger)
            connection = inbox_records.connect(ledger)
            now = "2026-07-18T00:00:00Z"
            package_documents: dict[Path, bytes] = {}
            document_expectations: dict[
                Path, tuple[str, str, int, str]
            ] = {}
            finding_states = {
                "preliminary_findings_received",
                "targeted_evidence_ready",
                "results_received",
                "finalizing",
                "finalized_with_findings",
                "needs_manual_review",
            }
            result_states = {
                "results_received",
                "finalizing",
                "finalized_no_findings",
                "finalized_with_findings",
                "needs_manual_review",
            }
            finalization_states = {
                "finalizing",
                "finalized_no_findings",
                "finalized_with_findings",
            }
            try:
                for ordinal, state in enumerate(self.STATES, start=1):
                    source_path = queue_root / "originals" / f"{state}.mp4"
                    source_path.parent.mkdir(parents=True, exist_ok=True)
                    source_bytes = bytes([ordinal])
                    source_path.write_bytes(source_bytes)
                    source_stat = source_path.stat()
                    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
                    source_identity = f"sha256:{source_sha256}"
                    source_token = hashlib.sha256(
                        source_identity.encode("utf-8")
                    ).hexdigest()[:16]
                    preparation_signature = hashlib.sha256(
                        f"existing-v2:{state}".encode("utf-8")
                    ).hexdigest()
                    package_path = queue_root / "batches" / f"batch-{state}"
                    package_path.mkdir(parents=True)
                    source = connection.execute(
                        """
                        INSERT INTO inbox_sources (
                            provisional_identity, stable_identity, content_sha256,
                            sampled_sha256, size_bytes, lifecycle_state,
                            first_seen_utc, updated_utc
                        ) VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                        """,
                        (
                            review_ledger.make_provisional_identity(
                                str(source_path), 1, now
                            ),
                            source_identity,
                            source_sha256,
                            source_sha256,
                            state,
                            now,
                            now,
                        ),
                    )
                    source_id = int(source.lastrowid)
                    source_package = package_path / "sources" / source_token
                    source_package.mkdir(parents=True)
                    source_manifest = {
                        "schema_version": 1,
                        "source_id": source_id,
                        "source_identity": source_identity,
                        "source_token": source_token,
                        "original_location": str(source_path),
                        "original_size_bytes": 1,
                        "original_modified_ns": source_stat.st_mtime_ns,
                        "copy_validation": {
                            "before": {
                                "size_bytes": 1,
                                "modified_ns": source_stat.st_mtime_ns,
                            },
                            "after": {
                                "size_bytes": 1,
                                "modified_ns": source_stat.st_mtime_ns,
                            },
                            "bytes_copied": 1,
                            "sha256": source_sha256,
                        },
                        "media_metadata": {
                            "duration_seconds": 0.0,
                            "audio_streams": [],
                            "video_streams": [],
                            "audio_layout_fingerprint": "",
                        },
                        "audio_selection": {
                            "state": "no_audio",
                            "selected_ordinal": None,
                            "selected_ffmpeg_map": "",
                            "confirmation_source": "no audio streams",
                        },
                        "transcription": {
                            "status": "not_applicable_no_audio",
                            "segments_count": 0,
                        },
                        "visuals": {
                            "frame_count": 0,
                            "frames": [],
                            "panels": [],
                            "supported_panel_ids": [],
                        },
                        "preparation_signature": preparation_signature,
                    }
                    source_manifest_path = source_package / "source-manifest.json"
                    source_manifest_path.write_text(
                        json.dumps(source_manifest, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    batch_manifest = {
                        "schema_version": 1,
                        "batch_id": f"batch-{state}",
                        "status": state,
                        "prepared_sources": [
                            {
                                "source_id": source_id,
                                "source_identity": source_identity,
                                "source_token": source_token,
                                "package_path": str(source_package),
                                "audio_state": "no_audio",
                            }
                        ],
                        "blocked_sources": [],
                        "failed_sources": [],
                    }
                    batch_manifest_path = package_path / "batch-manifest.json"
                    batch_manifest_path.write_text(
                        json.dumps(batch_manifest, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    package_documents[source_manifest_path] = (
                        source_manifest_path.read_bytes()
                    )
                    document_expectations[source_manifest_path] = (
                        "source_manifest",
                        state,
                        source_id,
                        source_identity,
                    )
                    source_integrity = {
                        "schema_version": 1,
                        "complete": True,
                        "files": [
                            {
                                "path": "source-manifest.json",
                                "size_bytes": source_manifest_path.stat().st_size,
                                "sha256": review_ledger.sha256_file(
                                    source_manifest_path
                                ),
                            }
                        ],
                    }
                    source_integrity_path = source_package / "integrity.json"
                    source_integrity_path.write_text(
                        json.dumps(source_integrity, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    package_documents[source_integrity_path] = (
                        source_integrity_path.read_bytes()
                    )
                    document_expectations[source_integrity_path] = (
                        "source_integrity",
                        state,
                        source_id,
                        source_identity,
                    )
                    package_documents[batch_manifest_path] = (
                        batch_manifest_path.read_bytes()
                    )
                    document_expectations[batch_manifest_path] = (
                        "batch_manifest",
                        state,
                        source_id,
                        source_identity,
                    )
                    connection.execute(
                        """
                        INSERT INTO inbox_source_locations (
                            source_id, original_path, normalized_path, size_bytes,
                            modified_utc, modified_ns, is_current, first_seen_utc,
                            last_seen_utc
                        ) VALUES (?, ?, ?, 1, ?, ?, 1, ?, ?)
                        """,
                        (
                            source_id,
                            str(source_path),
                            os.path.normcase(os.path.abspath(source_path)),
                            now,
                            source_stat.st_mtime_ns,
                            now,
                            now,
                        ),
                    )
                    batch_id = f"batch-{state}"
                    connection.execute(
                        """
                        INSERT INTO inbox_batches (
                            batch_id, status, package_path, is_legacy,
                            created_utc, updated_utc
                        ) VALUES (?, ?, ?, 0, ?, ?)
                        """,
                        (batch_id, state, str(package_path), now, now),
                    )
                    connection.execute(
                        """
                        INSERT INTO inbox_batch_sources (
                            batch_id, source_id, ordinal, state,
                            preparation_signature, added_utc, updated_utc
                        ) VALUES (?, ?, 1, ?, ?, ?, ?)
                        """,
                        (
                            batch_id,
                            source_id,
                            state,
                            preparation_signature,
                            now,
                            now,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO inbox_lifecycle_events (
                            source_id, batch_id, event_type, from_state, to_state,
                            details_json, created_utc
                        ) VALUES (?, ?, 'existing_v2_fixture', 'pending', ?, '{}', ?)
                        """,
                        (source_id, batch_id, state, now),
                    )
                    connection.execute(
                        """
                        INSERT INTO inbox_attempts (
                            source_id, batch_id, attempt_type, status,
                            started_utc, completed_utc, settings_hash, error_message
                        ) VALUES (?, ?, 'existing_v2_fixture', ?, ?, ?, ?, '')
                        """,
                        (
                            source_id,
                            batch_id,
                            state,
                            now,
                            now,
                            preparation_signature,
                        ),
                    )
                    finding_id = f"finding-{ordinal:03d}"
                    if state in finding_states:
                        disposition = (
                            "uncertain_manual_review"
                            if state == "needs_manual_review"
                            else "already_implemented"
                        )
                        stage = (
                            "preliminary"
                            if state
                            in {
                                "preliminary_findings_received",
                                "targeted_evidence_ready",
                            }
                            else "final"
                        )
                        finding_status = (
                            "evidence_requested"
                            if stage == "preliminary"
                            else disposition
                        )
                        connection.execute(
                            """
                            INSERT INTO inbox_findings (
                                finding_id, batch_id, source_id, stage, status,
                                details_json, created_utc, updated_utc
                            ) VALUES (?, ?, ?, ?, ?, '{}', ?, ?)
                            """,
                            (
                                finding_id,
                                batch_id,
                                source_id,
                                stage,
                                finding_status,
                                now,
                                now,
                            ),
                        )
                    if state in result_states:
                        disposition = (
                            "no_actionable_findings"
                            if state == "finalized_no_findings"
                            else "uncertain_manual_review"
                            if state == "needs_manual_review"
                            else "already_implemented"
                        )
                        result_finding_id = (
                            None
                            if disposition == "no_actionable_findings"
                            else finding_id
                        )
                        connection.execute(
                            """
                            INSERT INTO inbox_final_results (
                                result_id, batch_id, source_id, finding_id,
                                submission_sha256, preliminary_submission_sha256,
                                disposition, summary, notes,
                                external_assertions_json, details_json,
                                created_utc, updated_utc
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', '[]', '{}', ?, ?)
                            """,
                            (
                                f"result-{ordinal:03d}",
                                batch_id,
                                source_id,
                                result_finding_id,
                                f"{ordinal + 200:064x}",
                                f"{ordinal + 300:064x}",
                                disposition,
                                f"Existing v2 fixture for {state}.",
                                now,
                                now,
                            ),
                        )
                    if state in finalization_states:
                        plan_sha = f"{ordinal + 400:064x}"
                        journal_path = (
                            package_path
                            / ".finalization"
                            / f"journal-{plan_sha[:24]}.json"
                        )
                        journal_path.parent.mkdir()
                        journal_phase = (
                            "planned"
                            if state == "finalizing"
                            else "cleanup_complete"
                        )
                        journal = {
                            "journal_version": 1,
                            "batch_id": batch_id,
                            "plan_sha256": plan_sha,
                            "phase": journal_phase,
                            "created_utc": now,
                            "updated_utc": now,
                            "recovery_count": 0,
                        }
                        if state.startswith("finalized_"):
                            journal.update(
                                {
                                    "resulting_batch_state": state,
                                    "cleanup_completed_utc": now,
                                }
                            )
                        journal["journal_checksum"] = hashlib.sha256(
                            json.dumps(
                                journal,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        ).hexdigest()
                        journal_path.write_text(
                            json.dumps(journal, indent=2, sort_keys=True)
                            + "\n",
                            encoding="utf-8",
                        )
                        package_documents[journal_path] = journal_path.read_bytes()
                        document_expectations[journal_path] = (
                            "finalization_journal",
                            state,
                            source_id,
                            source_identity,
                        )
                        connection.execute(
                            """
                            INSERT INTO inbox_finalization_runs (
                                plan_sha256, batch_id, results_submission_sha256,
                                preliminary_submission_sha256, status, journal_path,
                                created_utc, updated_utc
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                plan_sha,
                                batch_id,
                                f"{ordinal + 200:064x}",
                                f"{ordinal + 300:064x}",
                                (
                                    "planned"
                                    if state == "finalizing"
                                    else "cleanup_complete"
                                ),
                                str(journal_path),
                                now,
                                now,
                            ),
                        )
                        if state.startswith("finalized_"):
                            history_path = (
                                queue_root
                                / "history"
                                / "sources"
                                / source_token
                                / batch_id
                            )
                            history_path.mkdir(parents=True)
                            history_manifest_path = (
                                history_path / "retained-history-manifest.json"
                            )
                            history_manifest_path.write_text(
                                json.dumps(
                                    {
                                        "schema_version": 1,
                                        "plan_sha256": plan_sha,
                                        "batch_id": batch_id,
                                        "source_id": source_id,
                                        "source_identity": source_identity,
                                        "source_token": source_token,
                                        "resulting_state": state,
                                        "complete": True,
                                    },
                                    indent=2,
                                    sort_keys=True,
                                )
                                + "\n",
                                encoding="utf-8",
                            )
                            history_integrity_path = history_path / "integrity.json"
                            history_integrity_path.write_text(
                                json.dumps(
                                    {
                                        "schema_version": 1,
                                        "plan_sha256": plan_sha,
                                        "complete": True,
                                        "files": [
                                            {
                                                "path": "retained-history-manifest.json",
                                                "size_bytes": history_manifest_path.stat().st_size,
                                                "sha256": review_ledger.sha256_file(
                                                    history_manifest_path
                                                ),
                                            }
                                        ],
                                    },
                                    indent=2,
                                    sort_keys=True,
                                )
                                + "\n",
                                encoding="utf-8",
                            )
                            for history_document, kind in (
                                (
                                    history_manifest_path,
                                    "retained_history_manifest",
                                ),
                                (history_integrity_path, "history_integrity"),
                            ):
                                package_documents[history_document] = (
                                    history_document.read_bytes()
                                )
                                document_expectations[history_document] = (
                                    kind,
                                    state,
                                    source_id,
                                    source_identity,
                                )
                            connection.execute(
                                """
                                INSERT INTO inbox_retention_records (
                                    plan_sha256, batch_id, source_id,
                                    resulting_state, history_path, retained_bytes,
                                    disposable_bytes, history_integrity_sha256,
                                    created_utc
                                ) VALUES (?, ?, ?, ?, ?, 1, 0, ?, ?)
                                """,
                                (
                                    plan_sha,
                                    batch_id,
                                    source_id,
                                    state,
                                    str(history_path),
                                    review_ledger.sha256_file(
                                        history_integrity_path
                                    ),
                                    now,
                                ),
                            )
                connection.commit()
                before = [
                    tuple(row)
                    for row in connection.execute(
                        """
                        SELECT s.provisional_identity, s.lifecycle_state,
                               b.batch_id, b.status, b.package_path, bs.state
                        FROM inbox_sources s
                        JOIN inbox_batch_sources bs ON bs.source_id = s.source_id
                        JOIN inbox_batches b ON b.batch_id = bs.batch_id
                        ORDER BY s.source_id
                        """
                    ).fetchall()
                ]
            finally:
                connection.close()

            # 224 (Wave B2b): the records are in the library; its own check reads them as they are.
            result = review_ledger.validate_from_request({"ledger_path": str(ledger)})

            self.assertEqual(review_ledger.SCHEMA_VERSION, 2)
            self.assertEqual(result["schema_version"], recording_records.SCHEMA_VERSION)
            self.assertEqual(result["foreign_key_violation_count"], 0)
            self.assertEqual(list(queue_root.glob("review-ledger.sqlite*")), [], "no ledger file is made")
            connection = inbox_records.connect(ledger)
            try:
                self.assertEqual(recording_records.stored_version(connection), recording_records.SCHEMA_VERSION)
                self.assertEqual(
                    connection.execute("PRAGMA integrity_check").fetchone()[0],
                    "ok",
                )
                self.assertEqual(inbox_records.link_problems(connection), [])
                after = [
                    tuple(row)
                    for row in connection.execute(
                        """
                        SELECT s.provisional_identity, s.lifecycle_state,
                               b.batch_id, b.status, b.package_path, bs.state
                        FROM inbox_sources s
                        JOIN inbox_batch_sources bs ON bs.source_id = s.source_id
                        JOIN inbox_batches b ON b.batch_id = bs.batch_id
                        ORDER BY s.source_id
                        """
                    ).fetchall()
                ]
                self.assertEqual(after, before)
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM inbox_sources").fetchone()[0],
                    len(self.STATES),
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM inbox_batches").fetchone()[0],
                    len(self.STATES),
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM inbox_batch_sources"
                    ).fetchone()[0],
                    len(self.STATES),
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM inbox_lifecycle_events"
                    ).fetchone()[0],
                    len(self.STATES),
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM inbox_attempts").fetchone()[0],
                    len(self.STATES),
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM inbox_findings").fetchone()[0],
                    len(finding_states),
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM inbox_final_results"
                    ).fetchone()[0],
                    len(result_states),
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM inbox_finalization_runs"
                    ).fetchone()[0],
                    len(finalization_states),
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM inbox_retention_records"
                    ).fetchone()[0],
                    2,
                )
                preparation_signatures = [
                    str(row[0])
                    for row in connection.execute(
                        """
                        SELECT preparation_signature
                        FROM inbox_batch_sources
                        ORDER BY source_id
                        """
                    ).fetchall()
                ]
                self.assertEqual(
                    preparation_signatures,
                    [
                        hashlib.sha256(
                            f"existing-v2:{state}".encode("utf-8")
                        ).hexdigest()
                        for state in self.STATES
                    ],
                )
                final_result_rows = {
                    str(row["batch_id"]): (
                        str(row["disposition"]),
                        row["finding_id"],
                    )
                    for row in connection.execute(
                        """
                        SELECT batch_id, disposition, finding_id
                        FROM inbox_final_results
                        ORDER BY batch_id
                        """
                    ).fetchall()
                }
                self.assertEqual(
                    final_result_rows["batch-finalized_no_findings"],
                    ("no_actionable_findings", None),
                )
                self.assertEqual(
                    final_result_rows["batch-needs_manual_review"][0],
                    "uncertain_manual_review",
                )
                self.assertTrue(
                    all(
                        disposition
                        in {
                            "already_implemented",
                            "no_actionable_findings",
                            "uncertain_manual_review",
                        }
                        for disposition, _finding_id in final_result_rows.values()
                    )
                )
                finalization_rows = {
                    str(row["batch_id"]): (
                        str(row["status"]),
                        Path(str(row["journal_path"])),
                    )
                    for row in connection.execute(
                        """
                        SELECT batch_id, status, journal_path
                        FROM inbox_finalization_runs
                        ORDER BY batch_id
                        """
                    ).fetchall()
                }
                self.assertEqual(
                    finalization_rows["batch-finalizing"][0],
                    "planned",
                )
                self.assertEqual(
                    finalization_rows["batch-finalized_no_findings"][0],
                    "cleanup_complete",
                )
                self.assertEqual(
                    finalization_rows["batch-finalized_with_findings"][0],
                    "cleanup_complete",
                )
                for _status, journal_path in finalization_rows.values():
                    self.assertTrue(journal_path.is_file())
                    self.assertEqual(journal_path.parent.name, ".finalization")
                retention_rows = connection.execute(
                    """
                    SELECT batch_id, resulting_state, history_path,
                           history_integrity_sha256
                    FROM inbox_retention_records
                    ORDER BY batch_id
                    """
                ).fetchall()
                for row in retention_rows:
                    history_path = Path(str(row["history_path"]))
                    self.assertTrue(history_path.is_dir())
                    self.assertEqual(
                        history_path.name,
                        str(row["batch_id"]),
                    )
                    self.assertEqual(
                        str(row["resulting_state"]),
                        str(row["batch_id"]).removeprefix("batch-"),
                    )
                    self.assertEqual(
                        str(row["history_integrity_sha256"]),
                        review_ledger.sha256_file(
                            history_path / "integrity.json"
                        ),
                    )
            finally:
                connection.close()
            for path, expected_bytes in package_documents.items():
                self.assertEqual(path.read_bytes(), expected_bytes)
                document = json.loads(path.read_text(encoding="utf-8"))
                kind, state, source_id, source_identity = (
                    document_expectations[path]
                )
                batch_id = f"batch-{state}"
                if kind == "source_manifest":
                    self.assertEqual(document["schema_version"], 1)
                    self.assertEqual(document["source_id"], source_id)
                    self.assertEqual(
                        document["source_identity"], source_identity
                    )
                    self.assertEqual(document["source_token"], path.parent.name)
                    self.assertEqual(
                        document["source_token"],
                        hashlib.sha256(
                            source_identity.encode("utf-8")
                        ).hexdigest()[:16],
                    )
                    self.assertEqual(
                        Path(document["original_location"]),
                        queue_root / "originals" / f"{state}.mp4",
                    )
                    self.assertEqual(
                        document["copy_validation"]["sha256"],
                        source_identity.removeprefix("sha256:"),
                    )
                    self.assertEqual(
                        document["preparation_signature"],
                        hashlib.sha256(
                            f"existing-v2:{state}".encode("utf-8")
                        ).hexdigest(),
                    )
                elif kind == "source_integrity":
                    self.assertEqual(document["schema_version"], 1)
                    self.assertTrue(document["complete"])
                    self.assertEqual(
                        [item["path"] for item in document["files"]],
                        ["source-manifest.json"],
                    )
                    manifest_path = path.parent / "source-manifest.json"
                    self.assertEqual(
                        document["files"][0]["size_bytes"],
                        manifest_path.stat().st_size,
                    )
                    self.assertEqual(
                        document["files"][0]["sha256"],
                        review_ledger.sha256_file(manifest_path),
                    )
                elif kind == "batch_manifest":
                    self.assertEqual(document["schema_version"], 1)
                    self.assertEqual(document["batch_id"], batch_id)
                    self.assertEqual(document["status"], state)
                    self.assertEqual(
                        len(document["prepared_sources"]),
                        1,
                    )
                    prepared = document["prepared_sources"][0]
                    self.assertEqual(prepared["source_id"], source_id)
                    self.assertEqual(
                        prepared["source_identity"], source_identity
                    )
                    self.assertEqual(
                        Path(prepared["package_path"]),
                        path.parent
                        / "sources"
                        / prepared["source_token"],
                    )
                elif kind == "finalization_journal":
                    self.assertEqual(document["journal_version"], 1)
                    self.assertEqual(document["batch_id"], batch_id)
                    expected_phase = (
                        "planned"
                        if state == "finalizing"
                        else "cleanup_complete"
                    )
                    self.assertEqual(document["phase"], expected_phase)
                    checksum = document.pop("journal_checksum")
                    self.assertEqual(
                        checksum,
                        hashlib.sha256(
                            json.dumps(
                                document,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        ).hexdigest(),
                    )
                    self.assertEqual(
                        path.name,
                        f"journal-{document['plan_sha256'][:24]}.json",
                    )
                elif kind == "retained_history_manifest":
                    self.assertEqual(document["schema_version"], 1)
                    self.assertTrue(document["complete"])
                    self.assertEqual(document["batch_id"], batch_id)
                    self.assertEqual(document["source_id"], source_id)
                    self.assertEqual(
                        document["source_identity"], source_identity
                    )
                    self.assertEqual(path.parent.name, batch_id)
                elif kind == "history_integrity":
                    self.assertEqual(document["schema_version"], 1)
                    self.assertTrue(document["complete"])
                    self.assertEqual(
                        [item["path"] for item in document["files"]],
                        ["retained-history-manifest.json"],
                    )
                    history_manifest = (
                        path.parent / "retained-history-manifest.json"
                    )
                    self.assertEqual(
                        document["files"][0]["sha256"],
                        review_ledger.sha256_file(history_manifest),
                    )
                else:
                    self.fail(f"Unhandled compatibility document kind: {kind}")

            queue = review_queue.refresh_queue(
                {"ledger_path": str(ledger)},
                import_external=False,
            )
            active_ids = [
                str(item["batch_id"]) for item in queue["batches"]
            ]
            self.assertEqual(
                active_ids,
                [
                    "batch-awaiting_external_review",
                    "batch-targeted_evidence_ready",
                ],
            )
            self.assertEqual(len(active_ids), len(set(active_ids)))
            internal_ids = [
                str(item["batch_id"]) for item in queue["internal_batches"]
            ]
            expected_internal_ids = {
                f"batch-{state}" for state in self.STATES
            }
            self.assertEqual(set(internal_ids), expected_internal_ids)
            self.assertEqual(len(internal_ids), len(expected_internal_ids))
            self.assertEqual(
                queue["counts"],
                {
                    "ready_for_codex_review": 1,
                    "waiting_on_codex": 1,
                    "additional_local_evidence": 1,
                    "manual_review": 1,
                    "done": 2,
                },
            )
            index = json.loads(
                (queue_root / "queue-index.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                [str(item["batch_id"]) for item in index["batches"]],
                active_ids,
            )
            self.assertEqual(
                len(list((queue_root / "batches").iterdir())),
                len(self.STATES),
            )


class ReviewInboxScanTests(unittest.TestCase):
    def _payload(self, root: Path, source: Path, **overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "source_folders": [str(source)],
            "ledger_path": str(root / "review-ledger.sqlite"),
            "dedupe_mode": "Fast",
        }
        payload.update(overrides)
        return payload

    def _write(self, path: Path, content: bytes, mtime_ns: int | None = None) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        if mtime_ns is not None:
            os.utime(path, ns=(mtime_ns, mtime_ns))
        return path

    def test_scans_more_than_200_files_without_preparation_and_selects_three_oldest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            base = 1_700_000_000_000_000_000
            for index in range(205):
                self._write(source / f"clip-{index:03}.mp4", f"clip-{index}".encode(), base + index * 1_000_000_000)

            result = review_inbox.scan_from_request(self._payload(root, source))

            self.assertEqual(result["inventory_count"], 205)
            self.assertEqual(result["eligible_count"], 205)
            self.assertEqual(len(result["selected_sources"]), 3)
            self.assertTrue(result["scan_only"])
            self.assertFalse(result["preparation_performed"])
            self.assertEqual(result["hash_behavior"]["full_sha256_calls"], 0)
            self.assertEqual(result["settings"]["max_files"], 3)
            self.assertEqual(result["settings"]["max_duration_minutes"], 240)
            self.assertEqual(result["settings"]["concurrency"], 1)
            self.assertEqual(result["settings"]["pending_batch_limit"], 1)
            self.assertFalse(result["soft_duration_boundary"]["hard_wall_clock"])
            self.assertIn("allow the current source to finish safely", result["soft_duration_boundary"]["meaning"])
            selected_names = [Path(item["path"]).name for item in result["selected_sources"]]
            self.assertEqual(selected_names, ["clip-000.mp4", "clip-001.mp4", "clip-002.mp4"])

    def test_fast_reuses_exact_path_stats_and_full_hashes_every_file_only_in_full_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            for index in range(4):
                self._write(source / f"clip-{index}.mp4", f"content-{index}".encode())
            fast = review_inbox.scan_from_request(self._payload(root, source))
            fast_again = review_inbox.scan_from_request(self._payload(root, source))
            full = review_inbox.scan_from_request(
                self._payload(root, source, dedupe_mode="Full", full_scan_acknowledged=True)
            )
            self.assertEqual(fast["hash_behavior"]["full_sha256_calls"], 0)
            self.assertEqual(fast_again["hash_behavior"]["sampled_sha256_calls"], 0)
            self.assertEqual(fast_again["hash_behavior"]["full_sha256_calls"], 0)
            self.assertEqual(full["hash_behavior"]["full_sha256_calls"], 4)

    def test_full_mode_requires_explicit_per_run_warning_acknowledgement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            self._write(source / "clip.mp4", b"content")
            with self.assertRaisesRegex(ValueError, "multiple terabytes"):
                review_inbox.scan_from_request(self._payload(root, source, dedupe_mode="Full"))

    def test_rename_relocation_changed_content_and_exact_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            original = self._write(source / "original.mp4", b"original-content")
            review_inbox.scan_from_request(
                self._payload(root, source, dedupe_mode="Full", full_scan_acknowledged=True)
            )

            relocated = source / "relocated.mp4"
            original.rename(relocated)
            relocation = review_inbox.scan_from_request(self._payload(root, source))
            relocated_row = next(item for item in relocation["sources"] if Path(item["path"]).name == "relocated.mp4")
            self.assertEqual(relocated_row["classification"], "relocated")
            self.assertTrue(relocated_row["identity"].startswith("sha256:"))

            time.sleep(0.01)
            relocated.write_bytes(b"modified-content")
            changed = review_inbox.scan_from_request(self._payload(root, source))
            changed_row = next(item for item in changed["sources"] if Path(item["path"]).name == "relocated.mp4")
            self.assertEqual(changed_row["classification"], "source_changed")

            duplicate = self._write(source / "duplicate.mp4", b"modified-content")
            duplicate_scan = review_inbox.scan_from_request(self._payload(root, source))
            duplicate_row = next(item for item in duplicate_scan["sources"] if Path(item["path"]).name == duplicate.name)
            self.assertEqual(duplicate_row["classification"], "duplicate")
            self.assertTrue(duplicate_row["identity"].startswith("sha256:"))

    def test_pending_batch_is_discovered_and_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            self._write(source / "clip.mp4", b"content")
            first = review_inbox.scan_from_request(self._payload(root, source))
            source_id = int(first["sources"][0]["source_id"])
            connection = inbox_records.connect(root / "review-ledger.sqlite")
            now = "2026-07-18T00:00:00Z"
            connection.execute(
                "INSERT INTO inbox_batches (batch_id,status,package_path,is_legacy,created_utc,updated_utc) VALUES ('batch-1','awaiting_external_review','',0,?,?)",
                (now, now),
            )
            connection.execute(
                "INSERT INTO inbox_batch_sources (batch_id,source_id,ordinal,state,preparation_signature,added_utc,updated_utc) VALUES ('batch-1',?,1,'awaiting_external_review',NULL,?,?)",
                (source_id, now, now),
            )
            connection.commit()
            connection.close()

            second = review_inbox.scan_from_request(self._payload(root, source))
            self.assertEqual(len(second["pending_batches"]), 1)
            self.assertTrue(second["pending_batch_limit_reached"])
            self.assertTrue(second["sources"][0]["pending_batch_excluded"])
            self.assertEqual(second["selected_sources"], [])

    def test_new_config_precedes_legacy_and_cli_precedes_both_without_exporting_other_terms(self) -> None:
        config = {
            "reviewMediaInbox": {"maxFiles": 7, "order": "Newest", "dedupeMode": "Fast"},
            "reviewNewVideos": {"maxFiles": 9, "order": "Oldest", "dedupeMode": "Full"},
            "evidence": {"privateProjectTerm": "must-not-leak"},
        }
        resolved = review_inbox.resolve_settings({"max_files": 2}, config)
        self.assertEqual(resolved["max_files"], 2)
        self.assertEqual(resolved["order"], "newest")
        self.assertEqual(resolved["dedupe_mode"], "Fast")
        self.assertEqual(resolved["config_section"], "reviewMediaInbox")
        self.assertNotIn("must-not-leak", json.dumps(resolved))
        legacy = review_inbox.resolve_settings({}, {"reviewNewVideos": {"maxFiles": 8}})
        self.assertEqual(legacy["max_files"], 8)
        self.assertEqual(legacy["config_section"], "reviewNewVideos")

    def test_workflow_three_and_four_helpers_are_not_imported_or_invoked(self) -> None:
        module_text = (Path(__file__).resolve().parents[1] / "src" / "media_manglers" / "core" / "review_inbox.py").read_text(encoding="utf-8")
        self.assertNotIn("evidence_package", module_text)
        self.assertNotIn("archive_catalog", module_text)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            self._write(source / "clip.mp4", b"content")
            with mock.patch("media_manglers.core.review_inbox.full_sha256_file") as full_hash:
                result = review_inbox.scan_from_request(self._payload(root, source))
            full_hash.assert_not_called()
            self.assertFalse(result["preparation_performed"])

    def test_cli_writes_scan_only_json_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            self._write(source / "clip.mp4", b"content")
            request_path = root / "request.json"
            result_path = root / "result.json"
            write_json_file(request_path, CommandEnvelope(payload=self._payload(root, source)).to_dict())
            exit_code = main(
                [
                    "review-media-inbox-scan",
                    "--request-file",
                    str(request_path),
                    "--result-file",
                    str(result_path),
                ]
            )
            response = read_json_file(result_path)
            self.assertEqual(exit_code, 0)
            self.assertTrue(response["ok"])
            self.assertTrue(response["data"]["scan_only"])
            self.assertEqual(response["data"]["inventory_count"], 1)
            self.assertFalse(response["data"]["preparation_performed"])


if __name__ == "__main__":
    unittest.main()
