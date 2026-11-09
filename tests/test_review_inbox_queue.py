from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from media_manglers.core import review_queue
from tests import test_review_inbox_final_results as final_results_tests
from tests import test_review_inbox_preliminary_findings as preliminary_tests
import pytest
from tests import inbox_library  # noqa: E402

# 224 (Wave B2b): the Inbox's records are in this test's library, moved in (nothing to move).
pytestmark = pytest.mark.inbox_moved


class ReviewInboxQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = preliminary_tests.ReviewInboxPreliminaryFindingsTests(methodName="runTest")
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def test_atomic_queue_write_uses_a_short_sibling_name(self) -> None:
        target = self.fixture.root / "queue-index.json"
        fake_uuid = mock.Mock()
        fake_uuid.hex = "c" * 32
        with (
            mock.patch.object(review_queue.uuid, "uuid4", return_value=fake_uuid),
            mock.patch.object(review_queue.os, "replace") as replace,
        ):
            review_queue._atomic_bytes(target, b"{}")
        temporary, destination = map(Path, replace.call_args.args)
        self.assertEqual(temporary.name, f".mm-{'c' * 16}.tmp")
        self.assertEqual(destination, target)

    @property
    def payload(self) -> dict:
        return {"ledger_path": str(self.fixture.ledger)}

    @property
    def preliminary_return(self) -> Path:
        return self.fixture.batch_root / "external-returns" / "preliminary-findings.json"

    def _attempt_count(self) -> int:
        connection = inbox_library.connect()
        try:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM inbox_attempts WHERE batch_id = ? AND attempt_type = 'preliminary_findings_import'",
                    (self.fixture.batch_id,),
                ).fetchone()[0]
            )
        finally:
            connection.close()

    def _lifecycle_event_count(self) -> int:
        connection = inbox_library.connect()
        try:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM inbox_lifecycle_events WHERE batch_id = ? "
                    "AND event_type LIKE 'preliminary_findings_%'",
                    (self.fixture.batch_id,),
                ).fetchone()[0]
            )
        finally:
            connection.close()

    def _write_return(self, document: dict) -> None:
        self.preliminary_return.parent.mkdir(parents=True, exist_ok=True)
        self.preliminary_return.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def test_read_stable_candidate_distinguishes_missing_stable_and_changing_files(self) -> None:
        path = self.fixture.root / "candidate.json"
        missing = review_queue.read_stable_candidate(path)
        self.assertFalse(missing["exists"])
        self.assertFalse(missing["stable"])

        path.write_text('{"ready": true}\n', encoding="utf-8")
        expected_bytes = path.read_bytes()
        stable = review_queue.read_stable_candidate(path)
        self.assertTrue(stable["exists"])
        self.assertTrue(stable["stable"])
        self.assertEqual(stable["content"], expected_bytes)
        self.assertEqual(len(stable["sha256"]), 64)

        original_read = Path.read_bytes

        def mutating_read(candidate: Path) -> bytes:
            content = original_read(candidate)
            if candidate == path:
                candidate.write_bytes(content + b" ")
            return content

        with mock.patch.object(Path, "read_bytes", mutating_read):
            changing = review_queue.read_stable_candidate(path)
        self.assertTrue(changing["exists"])
        self.assertFalse(changing["stable"])
        self.assertEqual(changing["sha256"], "")
        self.assertEqual(changing["content"], b"")

    def test_refresh_writes_deterministic_queue_without_importing_generated_legacy_template(self) -> None:
        ledger_hash_before = inbox_library.fingerprint()
        package_hashes_before = {
            str(path.relative_to(self.fixture.batch_root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.fixture.batch_root.rglob("*")
            if path.is_file()
        }
        first = review_queue.refresh_queue(self.payload)
        self.assertEqual(first["contract_version"], 1)
        self.assertEqual(first["document_type"], review_queue.DOCUMENT_TYPE)
        self.assertEqual(first["queue_root"], str(self.fixture.ledger.parent))
        self.assertEqual(first["counts"]["ready_for_codex_review"], 2)
        self.assertEqual(first["counts"]["waiting_on_codex"], 0)
        self.assertEqual(first["counts"]["additional_local_evidence"], 0)
        self.assertEqual(first["counts"]["manual_review"], 0)
        self.assertEqual(first["counts"]["done"], 0)
        self.assertEqual(first["operator_status"], "Ready for Codex review")
        self.assertEqual(first["imported"], [])
        self.assertEqual(first["attention"], [])
        self.assertFalse(self.preliminary_return.exists())
        self.assertFalse(
            (self.fixture.batch_root / "external-returns" / "review-results.json").exists()
        )
        self.assertTrue(self.preliminary_return.parent.is_dir())
        self.assertEqual(len(first["batches"]), 1)
        entry = first["batches"][0]
        expected_relative = (
            self.fixture.batch_root.resolve()
            .relative_to(self.fixture.ledger.parent.resolve())
            .as_posix()
        )
        self.assertTrue(entry["package_contained"])
        self.assertTrue(entry["returns_contained"])
        self.assertEqual(entry["batch_relative_path"], expected_relative)
        self.assertFalse(Path(entry["batch_relative_path"]).is_absolute())
        self.assertEqual(entry["preliminary_return_path"], str(self.preliminary_return))
        self.assertEqual(
            entry["final_results_return_path"],
            str(self.fixture.batch_root / "external-returns" / "review-results.json"),
        )
        package_hashes_after = {
            str(path.relative_to(self.fixture.batch_root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.fixture.batch_root.rglob("*")
            if path.is_file()
        }
        self.assertEqual(package_hashes_after, package_hashes_before)
        self.assertEqual(
            inbox_library.fingerprint(),
            ledger_hash_before,
        )

        prompt = Path(first["queue_prompt_path"])
        index = Path(first["queue_index_path"])
        self.assertTrue(prompt.is_file())
        self.assertTrue(index.is_file())
        self.assertIn(str(self.preliminary_return), prompt.read_text(encoding="utf-8"))
        prompt_before = prompt.read_bytes()
        index_before = index.read_bytes()

        second = review_queue.refresh_queue(self.payload)
        self.assertEqual(second["imported"], [])
        self.assertEqual(prompt.read_bytes(), prompt_before)
        self.assertEqual(index.read_bytes(), index_before)
        self.assertEqual(self._attempt_count(), 0)
        self.assertEqual(
            inbox_library.fingerprint(),
            ledger_hash_before,
        )

    def test_manual_review_is_retained_visible_and_non_blocking(self) -> None:
        connection = inbox_library.connect()
        try:
            connection.execute(
                "UPDATE inbox_batches SET status = 'needs_manual_review' WHERE batch_id = ?",
                (self.fixture.batch_id,),
            )
            connection.execute(
                "UPDATE inbox_batch_sources SET state = 'needs_manual_review' WHERE batch_id = ?",
                (self.fixture.batch_id,),
            )
            connection.execute(
                """
                UPDATE inbox_sources SET lifecycle_state = 'needs_manual_review'
                WHERE source_id IN (
                    SELECT source_id FROM inbox_batch_sources WHERE batch_id = ?
                )
                """,
                (self.fixture.batch_id,),
            )
            connection.commit()
        finally:
            connection.close()

        ledger_hash_before = inbox_library.fingerprint()
        package_hashes_before = {
            str(path.relative_to(self.fixture.batch_root)): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in self.fixture.batch_root.rglob("*")
            if path.is_file()
        }

        first = review_queue.refresh_queue(self.payload, import_external=False)

        self.assertEqual(
            first["counts"],
            {
                "ready_for_codex_review": 0,
                "waiting_on_codex": 0,
                "additional_local_evidence": 0,
                "manual_review": 2,
                "done": 0,
            },
        )
        self.assertEqual(first["operator_status"], "Manual review available")
        self.assertEqual(first["attention"], [])
        self.assertEqual(first["batches"], [])
        self.assertEqual(
            first["manual_review"],
            [
                {
                    "batch_id": self.fixture.batch_id,
                    "status": "needs_manual_review",
                    "manual_review_count": 2,
                    "batch_relative_path": first["internal_batches"][0][
                        "batch_relative_path"
                    ],
                    "package_contained": True,
                }
            ],
        )
        self.assertEqual(
            first["internal_batches"][0]["operator_state"],
            "manual_review",
        )
        self.assertEqual(
            json.loads(Path(first["queue_index_path"]).read_text(encoding="utf-8"))[
                "manual_review"
            ],
            first["manual_review"],
        )
        prompt = Path(first["queue_prompt_path"])
        index = Path(first["queue_index_path"])
        prompt_before = prompt.read_bytes()
        index_before = index.read_bytes()

        second = review_queue.refresh_queue(self.payload, import_external=False)

        self.assertEqual(second["manual_review"], first["manual_review"])
        self.assertEqual(prompt.read_bytes(), prompt_before)
        self.assertEqual(index.read_bytes(), index_before)
        self.assertEqual(
            inbox_library.fingerprint(),
            ledger_hash_before,
        )
        self.assertEqual(
            {
                str(path.relative_to(self.fixture.batch_root)): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in self.fixture.batch_root.rglob("*")
                if path.is_file()
            },
            package_hashes_before,
        )

    def test_multiple_manual_review_batches_have_additive_source_counts(self) -> None:
        batch_one = self.fixture.ledger.parent / "batches" / "manual-one"
        batch_two = self.fixture.ledger.parent / "batches" / "manual-two"
        batch_one.mkdir(parents=True)
        batch_two.mkdir(parents=True)
        rows = [
            {
                "batch_id": "manual-one",
                "status": "needs_manual_review",
                "batch_path": str(batch_one),
                "source_count": 2,
                "source_states": ["needs_manual_review", "needs_manual_review"],
                "created_utc": "2026-01-01T00:00:00+00:00",
                "updated_utc": "2026-01-01T00:00:00+00:00",
            },
            {
                "batch_id": "manual-two",
                "status": "needs_manual_review",
                "batch_path": str(batch_two),
                "source_count": 1,
                "source_states": ["needs_manual_review"],
                "created_utc": "2026-01-02T00:00:00+00:00",
                "updated_utc": "2026-01-02T00:00:00+00:00",
            },
        ]

        with mock.patch.object(review_queue, "_batch_rows", return_value=(rows, 0)):
            result = review_queue.refresh_queue(self.payload, import_external=False)

        self.assertEqual(result["counts"]["manual_review"], 3)
        self.assertEqual(result["operator_status"], "Manual review available")
        self.assertEqual(result["attention"], [])
        self.assertEqual(
            [item["batch_id"] for item in result["manual_review"]],
            ["manual-one", "manual-two"],
        )
        self.assertEqual(
            [item["manual_review_count"] for item in result["manual_review"]],
            [2, 1],
        )

    def test_external_preliminary_return_is_imported_once_and_updates_queue_counts(self) -> None:
        review_queue.refresh_queue(self.payload, import_external=False)
        document = deepcopy(self.fixture.document)
        document["reviewer_notes"] = "External review completed; no targeted local evidence was requested."
        document["findings"] = [self.fixture._finding()]
        self._write_return(document)

        result = review_queue.refresh_queue(self.payload)
        self.assertEqual(len(result["imported"]), 1)
        self.assertEqual(result["imported"][0]["kind"], "preliminary")
        self.assertEqual(result["imported"][0]["source"], "external_returns")
        self.assertEqual(result["counts"]["ready_for_codex_review"], 0)
        self.assertEqual(result["counts"]["additional_local_evidence"], 1)
        self.assertEqual(result["operator_status"], "Processing")
        self.assertEqual(self._attempt_count(), 2)

        repeated = review_queue.refresh_queue(self.payload)
        self.assertEqual(repeated["imported"], [])
        self.assertEqual(self._attempt_count(), 2)

    def test_invalid_submission_sha_is_reported_once_and_changed_replacement_is_reconsidered(self) -> None:
        review_queue.refresh_queue(self.payload, import_external=False)
        self.preliminary_return.write_text('{"broken":\n', encoding="utf-8")

        first = review_queue.refresh_queue(self.payload)
        self.assertEqual(first["imported"], [])
        self.assertEqual(len(first["attention"]), 1)
        self.assertEqual(first["attention"][0]["code"], "invalid_external_return")
        rejected_sha = first["attention"][0]["sha256"]
        self.assertEqual(len(rejected_sha), 64)
        self.assertEqual(self._attempt_count(), 2)
        self.assertEqual(self._lifecycle_event_count(), 1)

        repeated = review_queue.refresh_queue(self.payload)
        self.assertEqual(repeated["attention"], first["attention"])
        self.assertEqual(self._attempt_count(), 2)
        self.assertEqual(self._lifecycle_event_count(), 1)

        replacement = deepcopy(self.fixture.document)
        replacement["reviewer_notes"] = "Corrected external review return."
        self._write_return(replacement)
        accepted = review_queue.refresh_queue(self.payload)
        self.assertEqual(len(accepted["imported"]), 1)
        self.assertNotEqual(accepted["imported"][0]["sha256"], rejected_sha)
        self.assertEqual(accepted["attention"], [])
        self.assertEqual(self._attempt_count(), 4)

    def test_modified_legacy_working_file_is_imported_when_new_return_is_absent(self) -> None:
        working = self.fixture.batch_root / "preliminary-findings.json"
        document = deepcopy(self.fixture.document)
        document["reviewer_notes"] = "Legacy external reviewer work that differs from the generated baseline."
        document["findings"] = [self.fixture._finding()]
        working.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        result = review_queue.refresh_queue(self.payload)
        self.assertEqual(len(result["imported"]), 1)
        self.assertEqual(result["imported"][0]["source"], "legacy_working_file")
        self.assertEqual(result["counts"]["additional_local_evidence"], 1)

    def test_temporary_sibling_is_ignored_until_exact_return_exists(self) -> None:
        review_queue.refresh_queue(self.payload, import_external=False)
        temporary = self.preliminary_return.parent / ".preliminary-findings.json.writer.tmp"
        temporary.write_text(json.dumps(self.fixture.document), encoding="utf-8")

        result = review_queue.refresh_queue(self.payload)
        self.assertEqual(result["imported"], [])
        self.assertEqual(result["attention"], [])
        self.assertEqual(self._attempt_count(), 0)
        self.assertTrue(temporary.is_file())
        self.assertFalse(self.preliminary_return.exists())

    def test_detected_bytes_are_imported_from_internal_staging_when_return_is_replaced(self) -> None:
        review_queue.refresh_queue(self.payload, import_external=False)
        document = deepcopy(self.fixture.document)
        document["reviewer_notes"] = "The stable candidate must win the post-detection race."
        document["findings"] = [self.fixture._finding()]
        self._write_return(document)
        detected_bytes = self.preliminary_return.read_bytes()
        detected_sha = hashlib.sha256(detected_bytes).hexdigest()
        real_import = review_queue.review_findings.import_from_request
        staged_paths: list[Path] = []

        def replace_then_import(payload: dict) -> dict:
            staged_path = Path(str(payload["findings_path"]))
            staged_paths.append(staged_path)
            self.preliminary_return.write_text('{"replaced": true}\n', encoding="utf-8")
            return real_import(payload)

        with mock.patch.object(
            review_queue.review_findings,
            "import_from_request",
            side_effect=replace_then_import,
        ):
            result = review_queue.refresh_queue(self.payload)

        self.assertEqual(len(result["imported"]), 1)
        self.assertEqual(result["imported"][0]["sha256"], detected_sha)
        self.assertEqual(len(staged_paths), 1)
        self.assertNotEqual(staged_paths[0], self.preliminary_return)
        self.assertEqual(staged_paths[0].parent, self.fixture.batch_root / ".queue-import")
        self.assertFalse(staged_paths[0].exists())
        self.assertFalse((self.fixture.batch_root / ".queue-import").exists())
        self.assertEqual(
            json.loads(self.preliminary_return.read_text(encoding="utf-8")),
            {"replaced": True},
        )

    def test_source_level_attention_and_counts_use_batch_source_states(self) -> None:
        connection = inbox_library.connect()
        try:
            source_id = int(
                connection.execute(
                    "SELECT source_id FROM inbox_batch_sources WHERE batch_id = ? ORDER BY ordinal LIMIT 1",
                    (self.fixture.batch_id,),
                ).fetchone()[0]
            )
            connection.execute(
                "UPDATE inbox_batch_sources SET state = 'retryable_failure' "
                "WHERE batch_id = ? AND source_id = ?",
                (self.fixture.batch_id, source_id),
            )
            connection.commit()
        finally:
            connection.close()

        result = review_queue.refresh_queue(self.payload, import_external=False)
        self.assertEqual(result["counts"]["ready_for_codex_review"], 1)
        self.assertEqual(result["operator_status"], "Needs attention")
        attention = [
            item for item in result["attention"] if item["code"] == "batch_needs_attention"
        ]
        self.assertEqual(len(attention), 1)
        self.assertIn("retryable_failure", attention[0]["message"])

    def test_active_batch_outside_queue_root_fails_closed_without_writing_returns(self) -> None:
        with tempfile.TemporaryDirectory() as outside_temporary:
            outside_batch = Path(outside_temporary) / "batch"
            outside_batch.mkdir()
            connection = inbox_library.connect()
            try:
                connection.execute(
                    "UPDATE inbox_batches SET package_path = ? WHERE batch_id = ?",
                    (str(outside_batch), self.fixture.batch_id),
                )
                connection.commit()
            finally:
                connection.close()

            result = review_queue.refresh_queue(self.payload)

            self.assertEqual(result["imported"], [])
            self.assertEqual(result["operator_status"], "Needs attention")
            self.assertEqual(
                [item["code"] for item in result["attention"]],
                ["batch_package_outside_queue"],
            )
            self.assertEqual(result["batches"], [])
            entry = result["internal_batches"][0]
            self.assertFalse(entry["package_contained"])
            self.assertFalse(entry["returns_contained"])
            self.assertEqual(entry["batch_relative_path"], "")
            self.assertEqual(entry["preliminary_return_path"], "")
            self.assertEqual(entry["final_results_return_path"], "")
            self.assertFalse((outside_batch / "external-returns").exists())
            prompt = Path(result["queue_prompt_path"]).read_text(encoding="utf-8")
            self.assertNotIn(str(outside_batch), prompt)

    def test_import_external_false_only_rebuilds_queue_artifacts(self) -> None:
        document = deepcopy(self.fixture.document)
        document["reviewer_notes"] = "This valid return must remain untouched during status-only refresh."
        self.preliminary_return.parent.mkdir(parents=True, exist_ok=True)
        self._write_return(document)

        result = review_queue.refresh_queue(self.payload, import_external=False)
        self.assertEqual(result["imported"], [])
        self.assertEqual(result["counts"]["ready_for_codex_review"], 2)
        self.assertEqual(self._attempt_count(), 0)
        self.assertEqual(
            json.loads(self.preliminary_return.read_text(encoding="utf-8")),
            document,
        )

    def test_done_count_uses_distinct_finalized_sources(self) -> None:
        connection = inbox_library.connect()
        try:
            connection.execute(
                "UPDATE inbox_sources SET lifecycle_state = 'finalized_no_findings' WHERE source_id IN "
                "(SELECT source_id FROM inbox_batch_sources WHERE batch_id = ?)",
                (self.fixture.batch_id,),
            )
            connection.execute(
                "UPDATE inbox_batch_sources SET state = 'finalized_no_findings' WHERE batch_id = ?",
                (self.fixture.batch_id,),
            )
            connection.execute(
                "UPDATE inbox_batches SET status = 'finalized_no_findings' WHERE batch_id = ?",
                (self.fixture.batch_id,),
            )
            connection.commit()
        finally:
            connection.close()

        result = review_queue.refresh_queue(self.payload, import_external=False)
        self.assertEqual(result["counts"]["done"], 2)
        self.assertEqual(result["counts"]["ready_for_codex_review"], 0)
        self.assertEqual(result["operator_status"], "Done")
        self.assertEqual(result["batches"], [])

    def test_external_queue_excludes_internal_only_batch_states(self) -> None:
        connection = inbox_library.connect()
        try:
            connection.execute(
                "UPDATE inbox_batch_sources SET state = 'preparing' WHERE batch_id = ?",
                (self.fixture.batch_id,),
            )
            connection.execute(
                "UPDATE inbox_batches SET status = 'preparing' WHERE batch_id = ?",
                (self.fixture.batch_id,),
            )
            connection.commit()
        finally:
            connection.close()

        result = review_queue.refresh_queue(self.payload, import_external=False)

        self.assertEqual(result["batches"], [])
        self.assertEqual(len(result["internal_batches"]), 1)
        prompt = Path(result["queue_prompt_path"]).read_text(encoding="utf-8")
        self.assertNotIn(self.fixture.batch_id, prompt)
        index = json.loads(
            Path(result["queue_index_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(index["batches"], [])
        self.assertNotIn("internal_batches", index)

    def test_reconciliation_orders_final_results_before_preliminary_returns(self) -> None:
        entries = [
            {
                "batch_id": "batch-preliminary-a",
                "status": "awaiting_external_review",
                "batch_path": str(self.fixture.batch_root),
                "package_contained": True,
                "returns_contained": True,
            },
            {
                "batch_id": "batch-preliminary-b",
                "status": "awaiting_external_review",
                "batch_path": str(self.fixture.batch_root),
                "package_contained": True,
                "returns_contained": True,
            },
            {
                "batch_id": "batch-final-a",
                "status": "targeted_evidence_ready",
                "batch_path": str(self.fixture.batch_root),
                "package_contained": True,
                "returns_contained": True,
            },
            {
                "batch_id": "batch-final-b",
                "status": "targeted_evidence_ready",
                "batch_path": str(self.fixture.batch_root),
                "package_contained": True,
                "returns_contained": True,
            },
        ]
        order: list[tuple[str, str]] = []

        def candidate(entry: dict, kind: str) -> tuple[dict, str, None]:
            return {
                "path": str(self.fixture.root / f"{entry['batch_id']}-{kind}.json"),
                "sha256": kind.ljust(64, "0"),
            }, "external_returns", None

        def importer(
            _ledger: Path,
            entry: dict,
            kind: str,
            _candidate: dict,
            _source: str,
        ) -> tuple[dict, None]:
            order.append((kind, str(entry["batch_id"])))
            return {"batch_id": entry["batch_id"], "kind": kind}, None

        with (
            mock.patch.object(review_queue, "_submission_candidate", side_effect=candidate),
            mock.patch.object(review_queue, "_import_candidate", side_effect=importer),
        ):
            imported, attention = review_queue._reconcile_external(self.fixture.ledger, entries)
        self.assertEqual(attention, [])
        self.assertEqual(len(imported), 4)
        self.assertEqual(
            order,
            [
                ("final_results", "batch-final-a"),
                ("final_results", "batch-final-b"),
                ("preliminary", "batch-preliminary-a"),
                ("preliminary", "batch-preliminary-b"),
            ],
        )


class ReviewInboxQueueFinalResultsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = final_results_tests.ReviewInboxFinalResultsTests(methodName="runTest")
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def test_initial_generated_final_working_file_is_ignored_then_external_return_imports(self) -> None:
        payload = {"ledger_path": str(self.fixture.fixture.ledger)}
        initial = review_queue.refresh_queue(payload)
        self.assertEqual(initial["imported"], [])
        self.assertEqual(initial["attention"], [])
        self.assertEqual(initial["counts"]["waiting_on_codex"], 2)
        self.assertEqual(initial["operator_status"], "Waiting on Codex")

        return_path = self.fixture.fixture.batch_root / "external-returns" / "review-results.json"
        document = self.fixture._valid_document()
        return_path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        accepted = review_queue.refresh_queue(payload)
        self.assertEqual(len(accepted["imported"]), 1)
        self.assertEqual(accepted["imported"][0]["kind"], "final_results")
        self.assertEqual(accepted["imported"][0]["source"], "external_returns")
        self.assertEqual(accepted["counts"]["waiting_on_codex"], 0)
        self.assertEqual(accepted["operator_status"], "Processing")


if __name__ == "__main__":
    unittest.main()
