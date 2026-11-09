from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from media_manglers.cli import main
from media_manglers.contracts import CommandEnvelope, read_json_file, write_json_file
from media_manglers.core import inbox_records, review_findings, review_inbox, review_ledger, review_preparation
from media_manglers_workbench.audio_detection import layout_fingerprint
import pytest
from tests import inbox_library  # noqa: E402

# 224 (Wave B2b): the Inbox's records are in this test's library, moved in (nothing to move).
pytestmark = pytest.mark.inbox_moved


class ReviewInboxPreliminaryFindingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sources = self.root / "sources"
        self.sources.mkdir()
        self.evidence = self.root / "evidence"
        self.scratch = self.root / "scratch"
        self.ledger = self.root / "review-ledger.sqlite"
        # Each Inbox a test makes has its own library, as each had its own ledger (224, Wave B2b).
        inbox_library.use_own_library(self, self.root)
        inbox_library.ready(self.ledger)
        self.prepare_result = self._prepare(2)
        self.batch_id = str(self.prepare_result["batch_id"])
        self.batch_root = Path(self.prepare_result["batch_path"])
        self.template_path = self.batch_root / "preliminary-findings.template.json"
        self.document = json.loads(self.template_path.read_text(encoding="utf-8"))
        self.identities = list(self.document["reviewed_source_identities"])

    def tearDown(self) -> None:
        inbox_records.release_all()
        self.temporary.cleanup()

    def _prepare(self, count: int) -> dict:
        for index in range(count):
            source = self.sources / f"source-{index:02d}.mp4"
            source.write_bytes((f"synthetic-source-{index}" * 20).encode("ascii"))
            timestamp = 1_700_000_000 + index
            os.utime(source, (timestamp, timestamp))

        def media_probe(_path: Path) -> dict:
            return {
                "duration_seconds": 120.0,
                "container": "synthetic",
                "bit_rate": 1_000_000,
                "recorder_profile": "synthetic",
                "video_streams": [{"stream_index": 0, "codec": "h264", "width": 5760, "height": 1080}],
                "audio_streams": [],
                "audio_layout_fingerprint": layout_fingerprint([], "synthetic"),
            }

        def render(_source: Path, _media: dict, output: Path) -> dict:
            frame = output / "frames" / "frame-001.jpg"
            panel = output / "panels" / "frame-001-driver_view.jpg"
            frame.parent.mkdir(parents=True, exist_ok=True)
            panel.parent.mkdir(parents=True, exist_ok=True)
            frame.write_bytes(b"synthetic-frame")
            panel.write_bytes(b"synthetic-panel")
            (output / "contact-sheet.jpg").write_bytes(b"synthetic-sheet")
            index = {
                "schema_version": 1,
                "frame_count": 1,
                "frames": [{"ordinal": 1, "timestamp_seconds": 60.0, "path": "frames/frame-001.jpg"}],
                "panels": [{"panel": "driver_view", "timestamp_seconds": 60.0, "path": "panels/frame-001-driver_view.jpg"}],
            }
            review_preparation._atomic_json(output / "timeline-index.json", index)
            return {"frame_count": 1, "frames": index["frames"], "contact_sheet": "contact-sheet.jpg", "panels": index["panels"]}

        return review_preparation.prepare_from_request(
            {
                "source_folders": [str(self.sources)],
                "ledger_path": str(self.ledger),
                "evidence_root": str(self.evidence),
                "scratch_root": str(self.scratch),
                "max_files": count,
                "max_duration_minutes": 240,
                "concurrency": 1,
                "pending_batch_limit": 1,
                "dedupe_mode": "Fast",
                "order": "oldest",
                "space_probe": lambda _path: 100 * 1024**3,
                "media_probe": media_probe,
                "visual_renderer": render,
            }
        )

    def _finding(self, identity: str | None = None) -> dict:
        return {
            "finding_id": "finding-001",
            "source_identity": identity or self.identities[0],
            "request_type": "targeted_evidence",
            "requests": [
                {
                    "request_id": "request-001",
                    "timestamp": {"kind": "range", "start_seconds": 10.0, "end_seconds": 15.0},
                    "frames": {"requested": True, "before_seconds": 2.0, "after_seconds": 2.0, "max_frames": 5},
                    "panels": {"requested": False, "panel_ids": [], "before_seconds": 0.0, "after_seconds": 0.0},
                    "audio": {"requested": False, "before_seconds": 0.0, "after_seconds": 0.0},
                }
            ],
            "reviewer_notes": "The neutral timeline is not detailed enough to verify this moment.",
            "confidence": {"level": "medium", "rationale": "The transcript and timeline suggest a bounded follow-up."},
        }

    def _write(self, document: dict, name: str = "submission.json") -> Path:
        path = self.root / name
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        return path

    def _import(self, path: Path) -> dict:
        return review_findings.import_from_request(
            {
                "ledger_path": str(self.ledger),
                "batch_path": str(self.batch_root),
                "expected_batch_id": self.batch_id,
                "findings_path": str(path),
            }
        )

    def _states(self) -> tuple[str, list[str]]:
        connection = inbox_library.connect()
        try:
            batch = str(connection.execute("SELECT status FROM inbox_batches WHERE batch_id = ?", (self.batch_id,)).fetchone()[0])
            sources = [str(row[0]) for row in connection.execute("SELECT state FROM inbox_batch_sources WHERE batch_id = ? ORDER BY ordinal", (self.batch_id,)).fetchall()]
            return batch, sources
        finally:
            connection.close()

    def test_prepared_batch_contains_schema_template_prompt_readme_and_working_file(self) -> None:
        for name in (
            "preliminary-findings.schema.json",
            "preliminary-findings.template.json",
            "preliminary-findings.json",
            "README_FOR_REVIEW.md",
            "CODEX_REVIEW_PROMPT.md",
        ):
            self.assertTrue((self.batch_root / name).is_file(), name)
        schema = json.loads((self.batch_root / "preliminary-findings.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["contract_version"]["const"], review_findings.CONTRACT_VERSION)
        prompt = (self.batch_root / "CODEX_REVIEW_PROMPT.md").read_text(encoding="utf-8")
        self.assertIn("open and closed GitHub issues", prompt)
        self.assertIn("Do not write final results", prompt)
        self.assertIn("Never edit batch/source manifests", prompt)
        self.assertNotIn(str(self.sources), prompt)

    def test_refreshing_review_materials_does_not_overwrite_working_submission(self) -> None:
        working = self.batch_root / "preliminary-findings.json"
        working.write_text('{"operator_edit": true}\n', encoding="utf-8")
        manifest = json.loads((self.batch_root / "batch-manifest.json").read_text(encoding="utf-8"))
        review_findings.write_review_materials(self.batch_root, manifest)
        self.assertEqual(working.read_text(encoding="utf-8"), '{"operator_edit": true}\n')

    def test_valid_findings_are_preserved_and_imported(self) -> None:
        document = deepcopy(self.document)
        document["findings"] = [self._finding()]
        result = self._import(self._write(document))
        self.assertTrue(result["accepted"])
        self.assertEqual(result["status"], "preliminary_findings_received")
        self.assertTrue(Path(result["submission_record"]).is_file())
        validation = json.loads(Path(result["validation_record"]).read_text(encoding="utf-8"))
        self.assertTrue(validation["accepted"])
        self.assertEqual(validation["finding_count"], 1)

    def test_point_request_supports_frames_supported_panels_and_audio_context(self) -> None:
        document = deepcopy(self.document)
        finding = self._finding()
        finding["requests"][0] = {
            "request_id": "request-point",
            "timestamp": {"kind": "point", "at_seconds": 60.0},
            "frames": {"requested": True, "before_seconds": 2.0, "after_seconds": 2.0, "max_frames": 5},
            "panels": {"requested": True, "panel_ids": ["driver_view"], "before_seconds": 1.0, "after_seconds": 1.0},
            "audio": {"requested": True, "before_seconds": 10.0, "after_seconds": 10.0},
        }
        document["findings"] = [finding]
        context = {
            "batch_id": self.batch_id,
            "sources": {
                self.identities[0]: {
                    "source_id": 1,
                    "duration_seconds": 120.0,
                    "panel_ids": ["driver_view"],
                    "audio_available": True,
                },
                self.identities[1]: {
                    "source_id": 2,
                    "duration_seconds": 120.0,
                    "panel_ids": ["driver_view"],
                    "audio_available": True,
                },
            },
        }
        self.assertEqual(review_findings.validate_document(document, context), [])

    def test_supported_panel_metadata_allows_targeted_crop_without_eager_panel_files(self) -> None:
        source_record = self.prepare_result["prepared_sources"][0]
        source_root = Path(source_record["package_path"])
        manifest_path = source_root / "source-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["visuals"]["panels"] = []
        manifest["visuals"]["supported_panel_ids"] = ["overview_cam", "driver_view", "face_cam"]
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        integrity_path = source_root / "integrity.json"
        integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
        manifest_record = next(item for item in integrity["files"] if item["path"] == "source-manifest.json")
        manifest_record["size_bytes"] = manifest_path.stat().st_size
        manifest_record["sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        integrity_path.write_text(json.dumps(integrity, indent=2) + "\n", encoding="utf-8")

        batch_manifest = json.loads((self.batch_root / "batch-manifest.json").read_text(encoding="utf-8"))
        problems: list[str] = []
        context = review_findings._load_source_manifests(self.batch_root, batch_manifest, problems)
        self.assertEqual(problems, [])
        self.assertEqual(
            context[str(source_record["source_identity"])]["panel_ids"],
            ["driver_view", "face_cam", "overview_cam"],
        )

    def test_no_targeted_evidence_requests_is_valid_but_not_final(self) -> None:
        result = self._import(self._write(self.document))
        self.assertTrue(result["accepted"])
        self.assertEqual(result["finding_count"], 0)
        self.assertEqual(result["request_count"], 0)
        batch, sources = self._states()
        self.assertEqual(batch, "preliminary_findings_received")
        self.assertEqual(sources, ["awaiting_external_review", "awaiting_external_review"])

    def test_unknown_batch_is_rejected(self) -> None:
        document = deepcopy(self.document)
        document["batch_id"] = "batch-unknown"
        result = self._import(self._write(document))
        self.assertFalse(result["accepted"])
        self.assertTrue(any("must exactly match" in item for item in result["problems"]))

    def test_unknown_source_is_rejected(self) -> None:
        document = deepcopy(self.document)
        document["findings"] = [self._finding("sha256:" + "f" * 64)]
        result = self._import(self._write(document))
        self.assertFalse(result["accepted"])
        self.assertTrue(any("source_identity is unknown" in item for item in result["problems"]))

    def test_duplicate_finding_id_is_rejected(self) -> None:
        document = deepcopy(self.document)
        document["findings"] = [self._finding(), self._finding(self.identities[1])]
        result = self._import(self._write(document))
        self.assertFalse(result["accepted"])
        self.assertTrue(any("finding_id duplicates" in item for item in result["problems"]))

    def test_negative_inverted_and_out_of_duration_ranges_report_all_problems(self) -> None:
        document = deepcopy(self.document)
        findings = []
        ranges = ((-1.0, 2.0), (20.0, 10.0), (100.0, 121.0))
        for index, (start, end) in enumerate(ranges):
            finding = self._finding()
            finding["finding_id"] = f"finding-{index}"
            finding["requests"][0]["request_id"] = f"request-{index}"
            finding["requests"][0]["timestamp"] = {"kind": "range", "start_seconds": start, "end_seconds": end}
            findings.append(finding)
        document["findings"] = findings
        result = self._import(self._write(document))
        self.assertFalse(result["accepted"])
        joined = "\n".join(result["problems"])
        self.assertIn("non-negative", joined)
        self.assertIn("greater than start_seconds", joined)
        self.assertIn("exceeds the source duration", joined)

    def test_malformed_json_is_rejected_and_preserved(self) -> None:
        path = self.root / "malformed.json"
        path.write_text('{"contract_version": 1,', encoding="utf-8")
        result = self._import(path)
        self.assertFalse(result["accepted"])
        self.assertTrue(any("Malformed JSON" in item for item in result["problems"]))
        self.assertTrue(Path(result["validation_record"]).is_file())

    def test_unsupported_request_type_is_rejected(self) -> None:
        document = deepcopy(self.document)
        finding = self._finding()
        finding["request_type"] = "final_issue_decision"
        document["findings"] = [finding]
        result = self._import(self._write(document))
        self.assertFalse(result["accepted"])
        self.assertTrue(any("request_type must be" in item for item in result["problems"]))

    def test_final_disposition_fields_are_rejected_from_preliminary_contract(self) -> None:
        document = deepcopy(self.document)
        finding = self._finding()
        finding["final_disposition"] = "new_issue_created"
        document["findings"] = [finding]
        result = self._import(self._write(document))
        self.assertFalse(result["accepted"])
        self.assertTrue(any("final_disposition is not supported" in item for item in result["problems"]))

    def test_request_context_sizes_are_bounded(self) -> None:
        document = deepcopy(self.document)
        finding = self._finding()
        finding["requests"][0]["frames"]["before_seconds"] = 61.0
        finding["requests"][0]["frames"]["max_frames"] = 25
        document["findings"] = [finding]
        result = self._import(self._write(document))
        self.assertFalse(result["accepted"])
        joined = "\n".join(result["problems"])
        self.assertIn("between 0 and 60 seconds", joined)
        self.assertIn("integer from 0 through 24", joined)

    def test_unsupported_panel_request_is_rejected(self) -> None:
        document = deepcopy(self.document)
        finding = self._finding()
        finding["requests"][0]["panels"] = {
            "requested": True,
            "panel_ids": ["unsupported_panel"],
            "before_seconds": 1.0,
            "after_seconds": 1.0,
        }
        document["findings"] = [finding]
        result = self._import(self._write(document))
        self.assertFalse(result["accepted"])
        self.assertTrue(any("unsupported panels" in item for item in result["problems"]))

    def test_partial_review_is_rejected(self) -> None:
        document = deepcopy(self.document)
        document["reviewed_source_identities"] = [self.identities[0]]
        result = self._import(self._write(document))
        self.assertFalse(result["accepted"])
        self.assertTrue(any("review is partial" in item for item in result["problems"]))

    def test_integrity_mismatch_is_rejected(self) -> None:
        source_token = self.prepare_result["prepared_sources"][0]["source_token"]
        artifact = self.batch_root / "sources" / source_token / "visuals" / "frames" / "frame-001.jpg"
        artifact.write_bytes(b"tampered")
        result = self._import(self._write(self.document))
        self.assertFalse(result["accepted"])
        self.assertTrue(any("artifact" in item.lower() and "changed" in item.lower() for item in result["problems"]))

    def test_exact_reimport_is_idempotent(self) -> None:
        document = deepcopy(self.document)
        document["findings"] = [self._finding()]
        path = self._write(document)
        first = self._import(path)
        second = self._import(path)
        self.assertTrue(first["accepted"])
        self.assertTrue(second["accepted"])
        self.assertTrue(second["idempotent"])
        connection = inbox_library.connect()
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM inbox_findings").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM inbox_attempts WHERE attempt_type='preliminary_findings_import'").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM inbox_lifecycle_events WHERE event_type='preliminary_findings_imported'").fetchone()[0], 2)
        finally:
            connection.close()

    def test_exact_reimport_recovers_stale_validation_record_from_ledger(self) -> None:
        document = deepcopy(self.document)
        document["findings"] = [self._finding()]
        path = self._write(document)
        first = self._import(path)
        validation_path = Path(first["validation_record"])
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        validation["accepted"] = False
        validation["resulting_batch_state"] = "awaiting_external_review"
        validation_path.write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")

        second = self._import(path)

        self.assertTrue(second["accepted"])
        self.assertTrue(second["idempotent"])
        reconciled = json.loads(validation_path.read_text(encoding="utf-8"))
        self.assertTrue(reconciled["accepted"])
        self.assertEqual(reconciled["import_phase"], "accepted")
        self.assertEqual(reconciled["resulting_batch_state"], "preliminary_findings_received")
        self.assertIn("reconciled_from_ledger_utc", reconciled)

    def _assert_interrupted_import_recovers(self, interruption: str) -> None:
        class SimulatedCrash(BaseException):
            pass

        class CrashBeforeCommitConnection:
            def __init__(self, connection):
                self.connection = connection

            def __getattr__(self, name):
                return getattr(self.connection, name)

            def commit(self) -> None:
                raise SimulatedCrash("simulated crash before SQLite commit")

        document = deepcopy(self.document)
        document["findings"] = [self._finding()]
        path = self._write(document)
        submission_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        validation_path = self.batch_root / "imports" / "preliminary-findings" / submission_sha[:24] / "validation.json"
        real_connect = inbox_records.connect
        call_count = 0

        # 224 (Wave B1): the import's readers open the ledger read-only, so its first writing connection is
        # the one that holds the import's transaction.
        def interrupted_connect(ledger_path, **options):
            nonlocal call_count
            call_count += 1
            if call_count == 1 and interruption == "before_begin":
                raise SimulatedCrash("simulated crash before SQLite transaction")
            connection = real_connect(ledger_path, **options)
            if call_count == 1 and interruption == "before_commit":
                return CrashBeforeCommitConnection(connection)
            return connection

        with patch.object(review_findings.inbox_records, "connect", side_effect=interrupted_connect):
            with self.assertRaises(SimulatedCrash):
                self._import(path)

        staged = json.loads(validation_path.read_text(encoding="utf-8"))
        self.assertEqual(staged["import_phase"], "staged")
        self.assertFalse(staged["accepted"])
        connection = inbox_library.connect()
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM inbox_findings").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM inbox_attempts WHERE attempt_type='preliminary_findings_import'").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM inbox_lifecycle_events WHERE event_type LIKE 'preliminary_findings_%'").fetchone()[0], 0)
        finally:
            connection.close()

        recovered = self._import(path)
        repeated = self._import(path)

        self.assertTrue(recovered["accepted"])
        self.assertFalse(recovered["idempotent"])
        self.assertTrue(repeated["accepted"])
        self.assertTrue(repeated["idempotent"])
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        self.assertEqual(validation["import_phase"], "accepted")
        self.assertEqual(validation["resume_count"], 1)
        connection = inbox_library.connect()
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM inbox_findings").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM inbox_attempts WHERE attempt_type='preliminary_findings_import'").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM inbox_lifecycle_events WHERE event_type='preliminary_findings_imported'").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM inbox_lifecycle_events WHERE event_type='preliminary_findings_rejected'").fetchone()[0], 0)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            connection.close()

    def test_staged_import_recovers_after_crash_before_transaction_begins(self) -> None:
        self._assert_interrupted_import_recovers("before_begin")

    def test_staged_import_recovers_after_crash_before_transaction_commits(self) -> None:
        self._assert_interrupted_import_recovers("before_commit")

    def test_genuinely_rejected_submission_is_idempotently_rejected(self) -> None:
        document = deepcopy(self.document)
        document["findings"] = [self._finding("sha256:" + "e" * 64)]
        path = self._write(document)
        first = self._import(path)
        validation_path = Path(first["validation_record"])
        before = json.loads(validation_path.read_text(encoding="utf-8"))
        stale = dict(before)
        stale["import_phase"] = "staged"
        stale["problems"] = []
        validation_path.write_text(json.dumps(stale, indent=2) + "\n", encoding="utf-8")
        connection = inbox_library.connect()
        try:
            counts_before = (
                connection.execute("SELECT COUNT(*) FROM inbox_findings").fetchone()[0],
                connection.execute("SELECT COUNT(*) FROM inbox_attempts WHERE attempt_type='preliminary_findings_import'").fetchone()[0],
                connection.execute("SELECT COUNT(*) FROM inbox_lifecycle_events WHERE event_type='preliminary_findings_rejected'").fetchone()[0],
            )
        finally:
            connection.close()

        second = self._import(path)

        self.assertFalse(first["accepted"])
        self.assertFalse(second["accepted"])
        self.assertTrue(second["idempotent"])
        self.assertEqual(second["problems"], first["problems"])
        self.assertEqual(before["import_phase"], "rejected")
        reconciled = json.loads(validation_path.read_text(encoding="utf-8"))
        self.assertEqual(reconciled["import_phase"], "rejected")
        self.assertEqual(reconciled["problems"], first["problems"])
        self.assertIn("reconciled_from_ledger_utc", reconciled)
        connection = inbox_library.connect()
        try:
            counts_after = (
                connection.execute("SELECT COUNT(*) FROM inbox_findings").fetchone()[0],
                connection.execute("SELECT COUNT(*) FROM inbox_attempts WHERE attempt_type='preliminary_findings_import'").fetchone()[0],
                connection.execute("SELECT COUNT(*) FROM inbox_lifecycle_events WHERE event_type='preliminary_findings_rejected'").fetchone()[0],
            )
        finally:
            connection.close()
        self.assertEqual(counts_after, counts_before)

    def test_lifecycle_transition_affects_only_sources_with_findings(self) -> None:
        document = deepcopy(self.document)
        document["findings"] = [self._finding(self.identities[1])]
        result = self._import(self._write(document))
        self.assertTrue(result["accepted"])
        batch, sources = self._states()
        self.assertEqual(batch, "preliminary_findings_received")
        self.assertEqual(sources, ["awaiting_external_review", "preliminary_findings_received"])
        connection = inbox_library.connect()
        try:
            row = connection.execute("SELECT stage, status FROM inbox_findings WHERE finding_id='finding-001'").fetchone()
            self.assertEqual(row, ("preliminary", "evidence_requested"))
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            connection.close()

    def test_relaunch_restores_truthful_preliminary_state(self) -> None:
        document = deepcopy(self.document)
        document["findings"] = [self._finding()]
        self.assertTrue(self._import(self._write(document))["accepted"])
        batches = review_inbox.list_pending_batches(self.ledger)
        self.assertEqual(batches[0]["status"], "preliminary_findings_received")
        self.assertEqual(batches[0]["sources"][0]["classification"], "preliminary_findings_received")

    def test_rejection_changes_no_state_and_triggers_no_cleanup_or_finalization(self) -> None:
        before_state = self._states()
        before_files = {str(path.relative_to(self.batch_root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in self.batch_root.rglob("*") if path.is_file() and "imports" not in path.parts}
        document = deepcopy(self.document)
        document["findings"] = [self._finding("sha256:" + "e" * 64)]
        result = self._import(self._write(document))
        self.assertFalse(result["accepted"])
        self.assertEqual(self._states(), before_state)
        after_files = {str(path.relative_to(self.batch_root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in self.batch_root.rglob("*") if path.is_file() and "imports" not in path.parts}
        self.assertEqual(after_files, before_files)
        connection = inbox_library.connect()
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM inbox_findings").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM inbox_lifecycle_events WHERE to_state LIKE 'finalized%'").fetchone()[0], 0)
        finally:
            connection.close()

    def test_github_issues_only_governance_coexists_with_review_materials(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        self.assertFalse((repo_root / "TODO.md").exists())
        agents = (repo_root / "AGENTS.md").read_text(encoding="utf-8")
        docs = (repo_root / "docs" / "README.md").read_text(encoding="utf-8")
        self.assertIn("GitHub Issues are the sole authoritative tracker", agents)
        self.assertIn("GitHub Issues", docs)
        self.assertIn("Review Media Inbox", docs)

    def test_cli_import_command_writes_machine_readable_result(self) -> None:
        document = deepcopy(self.document)
        document["findings"] = [self._finding()]
        findings_path = self._write(document)
        request_path = self.root / "cli-request.json"
        result_path = self.root / "cli-result.json"
        write_json_file(
            request_path,
            CommandEnvelope(
                payload={
                    "ledger_path": str(self.ledger),
                    "batch_path": str(self.batch_root),
                    "expected_batch_id": self.batch_id,
                    "findings_path": str(findings_path),
                }
            ).to_dict(),
        )
        exit_code = main(
            [
                "review-media-inbox-import-preliminary",
                "--request-file",
                str(request_path),
                "--result-file",
                str(result_path),
            ]
        )
        response = read_json_file(result_path)
        self.assertEqual(exit_code, 0)
        self.assertTrue(response["ok"])
        self.assertTrue(response["data"]["accepted"])


if __name__ == "__main__":
    unittest.main()
