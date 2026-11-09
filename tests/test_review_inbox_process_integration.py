from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from media_manglers.core import (
    inbox_records,
    review_inbox,
    review_ledger,
    review_orchestration,
    review_preparation,
)
import pytest
from tests import inbox_library  # noqa: E402

# 224 (Wave B2b): the Inbox's records are in this test's library, moved in (nothing to move).
pytestmark = pytest.mark.inbox_moved


class ReviewInboxProcessIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sources = self.root / "sources"
        self.scratch = self.root / "scratch"
        self.ledger = self.root / "review-ledger.sqlite"
        self.sources.mkdir()
        inbox_library.ready(self.ledger)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _media_probe(_source: Path) -> dict:
        return {
            "duration_seconds": 60.0,
            "container": "synthetic",
            "bit_rate": 1_000_000,
            "recorder_profile": "issue-84-integration",
            "video_streams": [
                {
                    "stream_index": 0,
                    "codec": "h264",
                    "width": 5760,
                    "height": 1080,
                }
            ],
            "audio_streams": [],
            "audio_layout_fingerprint": hashlib.sha256(b"no-audio").hexdigest(),
        }

    @staticmethod
    def _visual_renderer(_source: Path, media: dict, output: Path) -> dict:
        frames_root = output / "frames"
        frames_root.mkdir(parents=True, exist_ok=True)
        frame_count = review_preparation.timeline_frame_count(
            float(media["duration_seconds"])
        )
        frames = []
        for ordinal in range(1, frame_count + 1):
            frame = frames_root / f"frame-{ordinal:03d}.jpg"
            frame.write_bytes(b"synthetic-frame")
            frames.append(
                {
                    "ordinal": ordinal,
                    "timestamp_seconds": float(ordinal),
                    "path": f"frames/{frame.name}",
                }
            )
        (output / "contact-sheet.jpg").write_bytes(b"synthetic-contact-sheet")
        (output / "timeline-index.json").write_text(
            json.dumps({"frames": frames, "panels": []}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return {
            "frame_count": frame_count,
            "frames": frames,
            "contact_sheet": "contact-sheet.jpg",
            "panels": [],
        }

    @staticmethod
    def _file_hashes(root: Path) -> dict[str, str]:
        return {
            path.relative_to(root).as_posix(): review_ledger.sha256_file(path)
            for path in root.rglob("*")
            if path.is_file()
        }

    def _seed_retained_manual_review(
        self,
        source: Path,
    ) -> tuple[int, str, Path, Path]:
        review_inbox.scan_from_request(
            {
                "source_folders": [str(self.sources)],
                "ledger_path": str(self.ledger),
                "evidence_root": str(self.root),
                "scratch_root": str(self.scratch),
                "dedupe_mode": "Fast",
                "order": "oldest",
                "max_files": 5,
                "pending_batch_limit": 9_999,
            }
        )
        batch_id = "batch-retained-manual"
        package_root = self.root / "batches" / batch_id
        history_root = self.root / "history" / "sources" / "retained-manual"
        package_root.mkdir(parents=True)
        history_root.mkdir(parents=True)
        (package_root / "retained-result.json").write_text(
            json.dumps(
                {
                    "batch_id": batch_id,
                    "status": "needs_manual_review",
                    "synthetic": True,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        history_integrity = history_root / "integrity.json"
        history_integrity.write_text(
            json.dumps(
                {
                    "batch_id": batch_id,
                    "complete": True,
                    "synthetic": True,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        journal_path = package_root / ".finalization" / "journal.json"
        journal_path.parent.mkdir()
        journal_path.write_text(
            json.dumps({"phase": "cleanup_complete", "synthetic": True}, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        now = "2026-01-01T00:00:00+00:00"
        plan_sha = "d" * 64
        results_sha = "e" * 64
        preliminary_sha = "f" * 64
        connection = inbox_records.connect(self.ledger)
        try:
            row = connection.execute(
                """
                SELECT s.source_id
                FROM inbox_sources s
                JOIN inbox_source_locations l ON l.source_id = s.source_id
                WHERE l.normalized_path = ? AND l.is_current = 1
                """,
                (review_inbox._normalize_path(source),),
            ).fetchone()
            self.assertIsNotNone(row)
            source_id = int(row["source_id"])
            connection.execute(
                """
                UPDATE inbox_sources
                SET lifecycle_state = 'needs_manual_review', updated_utc = ?
                WHERE source_id = ?
                """,
                (now, source_id),
            )
            connection.execute(
                """
                INSERT INTO inbox_batches (
                    batch_id, status, package_path, is_legacy, created_utc, updated_utc
                ) VALUES (?, 'needs_manual_review', ?, 0, ?, ?)
                """,
                (batch_id, str(package_root), now, now),
            )
            connection.execute(
                """
                INSERT INTO inbox_batch_sources (
                    batch_id, source_id, ordinal, state, preparation_signature,
                    added_utc, updated_utc
                ) VALUES (?, ?, 1, 'needs_manual_review', ?, ?, ?)
                """,
                (batch_id, source_id, "synthetic-retained-signature", now, now),
            )
            connection.execute(
                """
                INSERT INTO inbox_final_results (
                    result_id, batch_id, source_id, finding_id,
                    submission_sha256, preliminary_submission_sha256,
                    disposition, summary, notes, external_assertions_json,
                    details_json, created_utc, updated_utc
                ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, '[]', '{}', ?, ?)
                """,
                (
                    "result-retained-manual",
                    batch_id,
                    source_id,
                    results_sha,
                    preliminary_sha,
                    "needs_manual_review",
                    "Synthetic retained manual-review result.",
                    "Preserve for continuation regression coverage.",
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO inbox_finalization_runs (
                    plan_sha256, batch_id, results_submission_sha256,
                    preliminary_submission_sha256, status, journal_path,
                    created_utc, updated_utc
                ) VALUES (?, ?, ?, ?, 'cleanup_complete', ?, ?, ?)
                """,
                (
                    plan_sha,
                    batch_id,
                    results_sha,
                    preliminary_sha,
                    str(journal_path),
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO inbox_retention_records (
                    plan_sha256, batch_id, source_id, resulting_state,
                    history_path, retained_bytes, disposable_bytes,
                    history_integrity_sha256, created_utc
                ) VALUES (?, ?, ?, 'needs_manual_review', ?, ?, 0, ?, ?)
                """,
                (
                    plan_sha,
                    batch_id,
                    source_id,
                    str(history_root),
                    sum(
                        path.stat().st_size
                        for path in history_root.rglob("*")
                        if path.is_file()
                    ),
                    review_ledger.sha256_file(history_integrity),
                    now,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return source_id, batch_id, package_root, history_root

    def test_process_creates_one_real_queue_entry_without_altering_source(self) -> None:
        source = self.sources / "oldest.mp4"
        source.write_bytes(b"synthetic-original-media" * 128)
        os.utime(source, (1_700_000_000, 1_700_000_000))
        before = {
            "name": source.name,
            "size": source.stat().st_size,
            "modified_ns": source.stat().st_mtime_ns,
            "sha256": review_ledger.sha256_file(source),
        }

        result = review_orchestration.process_from_request(
            {
                "source_folders": [str(self.sources)],
                "ledger_path": str(self.ledger),
                "evidence_root": str(self.root),
                "scratch_root": str(self.scratch),
                "workload_mode": "next_3",
                "new_source_limit": 3,
                "dedupe_mode": "Fast",
                "order": "oldest",
                "max_duration_minutes": 240,
                "concurrency": 1,
                "space_probe": lambda _path: 100 * 1024**3,
                "media_probe": self._media_probe,
                "visual_renderer": self._visual_renderer,
            }
        )

        self.assertEqual(result["contract_version"], 1)
        self.assertEqual(result["action"], "process")
        self.assertEqual(result["operator_status"], "Ready for Codex review")
        self.assertEqual(result["queue_counts"]["ready_for_codex_review"], 1)
        self.assertEqual(result["queue_counts"]["waiting_on_codex"], 0)
        self.assertFalse(result["run_state"]["active"])
        self.assertFalse(result["run_state"]["resumable"])
        self.assertTrue((self.root / "queue-index.json").is_file())
        self.assertTrue((self.root / "CODEX_REVIEW_QUEUE_PROMPT.md").is_file())
        self.assertFalse(
            (self.root / ".orchestration" / "active-run.json").exists()
        )
        self.assertEqual(
            len(
                list(
                    (self.root / ".orchestration" / "completed-runs").glob(
                        "*.json"
                    )
                )
            ),
            1,
        )

        batches = list((self.root / "batches").iterdir())
        self.assertEqual(len(batches), 1)
        self.assertTrue((batches[0] / "batch-manifest.json").is_file())
        self.assertTrue((batches[0] / "external-returns").is_dir())
        self.assertFalse(
            (batches[0] / "external-returns" / "preliminary-findings.json").exists()
        )
        self.assertFalse(
            (batches[0] / "external-returns" / "review-results.json").exists()
        )
        source_manifests = list(
            (batches[0] / "sources").glob("*/source-manifest.json")
        )
        self.assertEqual(len(source_manifests), 1)
        manifest = json.loads(source_manifests[0].read_text(encoding="utf-8"))
        self.assertEqual(manifest["visuals"]["panels"], [])
        self.assertTrue(manifest["visuals"]["supported_panel_ids"])
        self.assertEqual(list(self.scratch.rglob("*")) if self.scratch.exists() else [], [])

        after = {
            "name": source.name,
            "size": source.stat().st_size,
            "modified_ns": source.stat().st_mtime_ns,
            "sha256": review_ledger.sha256_file(source),
        }
        self.assertEqual(after, before)

    def test_retained_manual_review_coexists_with_exactly_three_new_sources(
        self,
    ) -> None:
        retained_source = self.sources / "retained-manual.mp4"
        pending_sources = [
            self.sources / f"pending-{index:02d}.mp4" for index in range(1, 5)
        ]
        all_sources = [retained_source, *pending_sources]
        source_bytes_before: dict[str, dict[str, int | str]] = {}
        for index, source in enumerate(all_sources):
            source.write_bytes((f"synthetic-coexistence-{index}" * 128).encode())
            modified = 1_700_000_000 + index
            os.utime(source, (modified, modified))
            source_bytes_before[str(source)] = {
                "size": source.stat().st_size,
                "modified_ns": source.stat().st_mtime_ns,
                "sha256": review_ledger.sha256_file(source),
            }

        source_id, batch_id, package_root, history_root = (
            self._seed_retained_manual_review(retained_source)
        )
        connection = inbox_records.connect(self.ledger)
        try:
            retained_database_before = {
                "source": tuple(
                    connection.execute(
                        """
                        SELECT source_id, provisional_identity, stable_identity,
                               content_sha256, sampled_sha256, size_bytes,
                               lifecycle_state, first_seen_utc, updated_utc
                        FROM inbox_sources WHERE source_id = ?
                        """,
                        (source_id,),
                    ).fetchone()
                ),
                "batch": tuple(
                    connection.execute(
                        "SELECT * FROM inbox_batches WHERE batch_id = ?",
                        (batch_id,),
                    ).fetchone()
                ),
                "batch_source": tuple(
                    connection.execute(
                        "SELECT * FROM inbox_batch_sources WHERE batch_id = ?",
                        (batch_id,),
                    ).fetchone()
                ),
                "final_result": tuple(
                    connection.execute(
                        "SELECT * FROM inbox_final_results WHERE batch_id = ?",
                        (batch_id,),
                    ).fetchone()
                ),
                "finalization": tuple(
                    connection.execute(
                        "SELECT * FROM inbox_finalization_runs WHERE batch_id = ?",
                        (batch_id,),
                    ).fetchone()
                ),
                "retention": tuple(
                    connection.execute(
                        "SELECT * FROM inbox_retention_records WHERE batch_id = ?",
                        (batch_id,),
                    ).fetchone()
                ),
            }
        finally:
            connection.close()
        package_hashes_before = self._file_hashes(package_root)
        history_hashes_before = self._file_hashes(history_root)

        result = review_orchestration.process_from_request(
            {
                "source_folders": [str(self.sources)],
                "ledger_path": str(self.ledger),
                "evidence_root": str(self.root),
                "scratch_root": str(self.scratch),
                "workload_mode": "next_3",
                "new_source_limit": 3,
                "dedupe_mode": "Fast",
                "order": "oldest",
                "max_duration_minutes": 240,
                "concurrency": 1,
                "space_probe": lambda _path: 100 * 1024**3,
                "media_probe": self._media_probe,
                "visual_renderer": self._visual_renderer,
            }
        )

        self.assertEqual(
            result["operator_status"],
            "Ready for Codex review",
            result,
        )
        self.assertEqual(result["queue_counts"]["manual_review"], 1)
        self.assertEqual(result["queue_counts"]["ready_for_codex_review"], 3)
        self.assertIsNone(result["attention"])
        self.assertEqual(
            [item["batch_id"] for item in result["manual_review"]],
            [batch_id],
        )
        self.assertEqual(result["run_state"]["selected_count"], 3)
        self.assertEqual(result["run_state"]["completed_count"], 3)
        queue_index = json.loads(
            (self.root / "queue-index.json").read_text(encoding="utf-8")
        )
        self.assertEqual(queue_index["counts"]["manual_review"], 1)
        self.assertEqual(queue_index["manual_review"][0]["batch_id"], batch_id)

        connection = inbox_records.connect(self.ledger)
        try:
            states = {
                Path(row["original_path"]).name: str(row["lifecycle_state"])
                for row in connection.execute(
                    """
                    SELECT l.original_path, s.lifecycle_state
                    FROM inbox_sources s
                    JOIN inbox_source_locations l ON l.source_id = s.source_id
                    WHERE l.is_current = 1
                    """
                )
            }
            retained_database_after = {
                "source": tuple(
                    connection.execute(
                        """
                        SELECT source_id, provisional_identity, stable_identity,
                               content_sha256, sampled_sha256, size_bytes,
                               lifecycle_state, first_seen_utc, updated_utc
                        FROM inbox_sources WHERE source_id = ?
                        """,
                        (source_id,),
                    ).fetchone()
                ),
                "batch": tuple(
                    connection.execute(
                        "SELECT * FROM inbox_batches WHERE batch_id = ?",
                        (batch_id,),
                    ).fetchone()
                ),
                "batch_source": tuple(
                    connection.execute(
                        "SELECT * FROM inbox_batch_sources WHERE batch_id = ?",
                        (batch_id,),
                    ).fetchone()
                ),
                "final_result": tuple(
                    connection.execute(
                        "SELECT * FROM inbox_final_results WHERE batch_id = ?",
                        (batch_id,),
                    ).fetchone()
                ),
                "finalization": tuple(
                    connection.execute(
                        "SELECT * FROM inbox_finalization_runs WHERE batch_id = ?",
                        (batch_id,),
                    ).fetchone()
                ),
                "retention": tuple(
                    connection.execute(
                        "SELECT * FROM inbox_retention_records WHERE batch_id = ?",
                        (batch_id,),
                    ).fetchone()
                ),
            }
        finally:
            connection.close()

        self.assertEqual(states[retained_source.name], "needs_manual_review")
        self.assertEqual(states[pending_sources[0].name], "awaiting_external_review")
        self.assertEqual(states[pending_sources[1].name], "awaiting_external_review")
        self.assertEqual(states[pending_sources[2].name], "awaiting_external_review")
        self.assertEqual(states[pending_sources[3].name], "pending")
        self.assertEqual(retained_database_after, retained_database_before)
        self.assertEqual(self._file_hashes(package_root), package_hashes_before)
        self.assertEqual(self._file_hashes(history_root), history_hashes_before)
        for source in all_sources:
            after = {
                "size": source.stat().st_size,
                "modified_ns": source.stat().st_mtime_ns,
                "sha256": review_ledger.sha256_file(source),
            }
            self.assertEqual(after, source_bytes_before[str(source)])

    def test_paused_process_snapshot_survives_intervening_legacy_scan(self) -> None:
        source = self.sources / "fixed-snapshot.mp4"
        source.write_bytes(b"original-synthetic-media" * 128)
        os.utime(source, (1_700_000_000, 1_700_000_000))
        original_size = source.stat().st_size
        original_modified_ns = source.stat().st_mtime_ns
        stop = self.root / "stop-after-current.signal"
        stop.write_text("stop", encoding="utf-8")

        def must_not_copy(_source: Path, _destination: Path) -> dict:
            raise AssertionError(
                "A source outside the immutable Process snapshot was copied."
            )

        payload = {
            "source_folders": [str(self.sources)],
            "ledger_path": str(self.ledger),
            "evidence_root": str(self.root),
            "scratch_root": str(self.scratch),
            "workload_mode": "next_3",
            "new_source_limit": 3,
            "dedupe_mode": "Fast",
            "order": "oldest",
            "max_duration_minutes": 240,
            "concurrency": 1,
            "stop_after_current_file_path": str(stop),
            "space_probe": lambda _path: 100 * 1024**3,
            "media_probe": self._media_probe,
            "visual_renderer": self._visual_renderer,
            "copy_file": must_not_copy,
        }

        paused = review_orchestration.process_from_request(payload)
        self.assertEqual(paused["run_state"]["status"], "paused_after_current")
        active = review_orchestration._read_journal(
            review_orchestration._orchestration_paths(self.ledger)["active"]
        )
        self.assertIsNotNone(active)
        frozen = dict((active or {})["snapshot"][0])
        self.assertEqual(frozen["path"], str(source))
        self.assertEqual(frozen["size_bytes"], original_size)
        self.assertEqual(frozen["modified_ns"], original_modified_ns)
        self.assertTrue(frozen["identity"])
        self.assertTrue(frozen["sampled_sha256"])

        source.write_bytes(b"changed--synthetic-media" * 128)
        self.assertEqual(source.stat().st_size, original_size)
        changed_modified_ns = original_modified_ns + 1_000_000
        os.utime(
            source,
            ns=(changed_modified_ns, changed_modified_ns),
        )
        legacy_scan = review_inbox.scan_from_request(
            {
                "source_folders": [str(self.sources)],
                "ledger_path": str(self.ledger),
                "evidence_root": str(self.root),
                "scratch_root": str(self.scratch),
                "dedupe_mode": "Fast",
                "order": "oldest",
                "max_files": 3,
                "max_duration_minutes": 240,
                "concurrency": 1,
                "pending_batch_limit": 1,
            }
        )
        self.assertEqual(
            legacy_scan["sources"][0]["modified_ns"],
            changed_modified_ns,
        )
        self.assertNotEqual(
            legacy_scan["sources"][0]["sampled_sha256"],
            frozen["sampled_sha256"],
        )

        stop.unlink()
        retried = review_orchestration.process_from_request(payload)
        self.assertEqual(retried["operator_status"], "Needs attention")
        self.assertEqual(retried["attention"]["code"], "source_changed")
        self.assertEqual(retried["run_state"]["completed_count"], 0)

    def test_restricted_process_scans_every_source_but_prepares_only_target(
        self,
    ) -> None:
        sources = []
        before: dict[str, dict[str, object]] = {}
        for index in range(1, 6):
            source = self.sources / f"source-{index:02d}.mp4"
            source.write_bytes((f"synthetic-source-{index}" * (64 + index)).encode())
            os.utime(
                source,
                (
                    1_700_000_000 + index,
                    1_700_000_000 + index,
                ),
            )
            sources.append(source)
            before[str(source)] = {
                "name": source.name,
                "size": source.stat().st_size,
                "modified_ns": source.stat().st_mtime_ns,
                "sha256": review_ledger.sha256_file(source),
            }
        target = sources[2]
        sampled_sources: list[Path] = []
        copied_sources: list[Path] = []

        def sample_source(path: Path) -> str:
            sampled_sources.append(Path(path))
            return review_inbox.sampled_sha256_file(Path(path))

        def copy_source(source: Path, destination: Path) -> dict:
            copied_sources.append(Path(source))
            return review_preparation.stream_verified_copy(source, destination)

        result = review_orchestration.process_from_request(
            {
                "source_folders": [str(self.sources)],
                "ledger_path": str(self.ledger),
                "evidence_root": str(self.root),
                "scratch_root": str(self.scratch),
                "workload_mode": "next_3",
                "new_source_limit": 3,
                "exact_source_paths": [str(target)],
                "dedupe_mode": "Fast",
                "order": "oldest",
                "max_duration_minutes": 240,
                "concurrency": 1,
                "space_probe": lambda _path: 100 * 1024**3,
                "media_probe": self._media_probe,
                "visual_renderer": self._visual_renderer,
                "sample_hasher": sample_source,
                "copy_file": copy_source,
            }
        )

        self.assertEqual(result["operator_status"], "Ready for Codex review")
        self.assertEqual(result["queue_counts"]["ready_for_codex_review"], 1)
        self.assertEqual(result["run_state"]["status"], "waiting_external_review")
        self.assertEqual(result["run_state"]["selected_count"], 1)
        self.assertEqual(result["run_state"]["exact_source_restriction_count"], 1)
        active = review_orchestration._read_journal(
            review_orchestration._orchestration_paths(self.ledger)["active"]
        )
        self.assertEqual(active["workload"]["scanned_inventory_count"], 5)
        self.assertEqual(
            active["exact_source_restriction"]["scanned_inventory_count"],
            5,
        )
        self.assertEqual(set(sampled_sources), set(sources))
        self.assertEqual(copied_sources, [target])
        batches = list((self.root / "batches").iterdir())
        self.assertEqual(len(batches), 1)
        manifests = list((batches[0] / "sources").glob("*/source-manifest.json"))
        self.assertEqual(len(manifests), 1)
        manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        self.assertEqual(Path(manifest["original_location"]), target)

        connection = inbox_records.connect(self.ledger)
        try:
            states = {
                Path(row["original_path"]).name: row["lifecycle_state"]
                for row in connection.execute(
                    """
                    SELECT l.original_path, s.lifecycle_state
                    FROM inbox_sources s
                    JOIN inbox_source_locations l ON l.source_id = s.source_id
                    WHERE l.is_current = 1
                    """
                )
            }
        finally:
            connection.close()
        self.assertEqual(states[target.name], "awaiting_external_review")
        for source in sources:
            if source != target:
                self.assertEqual(states[source.name], "pending")
            after = {
                "name": source.name,
                "size": source.stat().st_size,
                "modified_ns": source.stat().st_mtime_ns,
                "sha256": review_ledger.sha256_file(source),
            }
            self.assertEqual(after, before[str(source)])

    def test_restricted_fast_scan_blocks_non_target_complete_hash(self) -> None:
        target = self.sources / "approved.mp4"
        decoy = self.sources / "decoy.mp4"
        target.write_bytes(b"approved-synthetic" * 128)
        decoy.write_bytes(b"decoy-synthetic---" * 128)
        review_inbox.scan_from_request(
            {
                "source_folders": [str(self.sources)],
                "ledger_path": str(self.ledger),
                "evidence_root": str(self.root),
                "scratch_root": str(self.scratch),
                "dedupe_mode": "Full",
                "full_scan_acknowledged": True,
                "max_files": 3,
                "pending_batch_limit": 3,
            }
        )
        changed_ns = decoy.stat().st_mtime_ns + 1_000_000_000
        os.utime(decoy, ns=(changed_ns, changed_ns))
        full_hash_calls: list[Path] = []

        result = review_orchestration.process_from_request(
            {
                "source_folders": [str(self.sources)],
                "ledger_path": str(self.ledger),
                "evidence_root": str(self.root),
                "scratch_root": str(self.scratch),
                "workload_mode": "next_3",
                "exact_source_paths": [str(target)],
                "dedupe_mode": "Fast",
                "full_hasher": lambda path: (
                    full_hash_calls.append(Path(path))
                    or review_inbox.full_sha256_file(Path(path))
                ),
            }
        )

        self.assertEqual(result["operator_status"], "Needs attention")
        self.assertEqual(
            result["attention"]["code"],
            "exact_source_restriction_error",
        )
        self.assertEqual(full_hash_calls, [])
        self.assertFalse((self.root / "batches").exists())


if __name__ == "__main__":
    unittest.main()
