from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest

from media_manglers.core import review_results, review_targeted_evidence
from media_manglers.cli import main
from media_manglers.contracts import CommandEnvelope, read_json_file, write_json_file
from tests import test_review_inbox_preliminary_findings as preliminary_tests
from tests import test_review_inbox_targeted_evidence as targeted_tests
import pytest
from tests import inbox_library  # noqa: E402

# 224 (Wave B2b): the Inbox's records are in this test's library, moved in (nothing to move).
pytestmark = pytest.mark.inbox_moved


class SimulatedCrash(BaseException):
    pass


class ReviewInboxFinalResultsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = preliminary_tests.ReviewInboxPreliminaryFindingsTests(methodName="runTest")
        self.fixture.setUp()
        preliminary = deepcopy(self.fixture.document)
        preliminary["findings"] = [self.fixture._finding()]
        imported = self.fixture._import(self.fixture._write(preliminary, "accepted-for-final-results.json"))
        self.preliminary_sha = str(imported["submission_sha256"])
        plan = review_targeted_evidence.plan_from_request(
            {
                "ledger_path": str(self.fixture.ledger),
                "batch_path": str(self.fixture.batch_root),
                "expected_batch_id": self.fixture.batch_id,
                "preliminary_submission_sha256": self.preliminary_sha,
            }
        )
        frames, audio, processed = targeted_tests.ReviewInboxTargetedEvidenceTests._render(plan)
        complete = review_targeted_evidence.complete_from_request(
            {
                "plan_path": plan["plan_path"],
                "plan_sha256": plan["plan_sha256"],
                "frame_results": frames,
                "audio_results": audio,
                "processed_request_signatures": processed,
            }
        )
        self.assertEqual(complete["status"], "targeted_evidence_ready")
        self.template_path = self.fixture.batch_root / "review-results.template.json"
        self.document = json.loads(self.template_path.read_text(encoding="utf-8"))
        self.basis, problems = review_results._targeted_basis(
            self.fixture.ledger,
            self.fixture.batch_root,
            self.fixture.batch_id,
            self.preliminary_sha,
            allowed_states={"targeted_evidence_ready"},
        )
        self.assertEqual(problems, [])

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def _valid_document(self) -> dict:
        document = deepcopy(self.document)
        for index, source in enumerate(document["source_results"], 1):
            source["source_summary"] = f"External review completed for source {index}."
            source["notes"] = "Prepared and targeted evidence were reviewed; GitHub assertions remain external."
            source["results"] = [
                {
                    "result_id": f"result-{index:03d}",
                    "finding_id": None,
                    "acknowledged_preliminary_finding_ids": [],
                    "acknowledged_request_ids": [],
                    "timestamps": [],
                    "disposition": "no_actionable_findings",
                    "summary": "No actionable finding was identified for this source.",
                    "notes": "The complete source review produced no issue action.",
                    "external_assertions": [],
                    "issue": None,
                }
            ]
        document["operator_summary"] = "Every prepared source and targeted request was reviewed."
        document["reviewer_notes"] = "Repository and issue conclusions, if any, are external assertions."
        return document

    def _set_disposition(self, document: dict, disposition: str) -> None:
        self._set_disposition_for_source(document, 0, disposition)

    def _set_disposition_for_source(self, document: dict, source_index: int, disposition: str) -> None:
        result = document["source_results"][source_index]["results"][0]
        result["disposition"] = disposition
        result["summary"] = f"Synthetic final disposition: {disposition}."
        result["notes"] = "Synthetic contract-validation evidence."
        if disposition not in {"no_actionable_findings", "review_failure"}:
            result["finding_id"] = f"final-{source_index + 1}-{disposition}"
            result["acknowledged_preliminary_finding_ids"] = ["finding-001"]
            result["acknowledged_request_ids"] = ["request-001"]
            result["timestamps"] = [{"kind": "range", "start_seconds": 10.0, "end_seconds": 15.0}]
        if disposition in review_results.ISSUE_DISPOSITIONS:
            action = review_results.ISSUE_DISPOSITIONS[disposition]
            result["issue"] = {
                "repository": "example/media-project",
                "issue_number": 17,
                "issue_url": "https://github.com/example/media-project/issues/17",
                "action": action,
                "authorization_note": "Operator approved this synthetic issue action." if action in {"created", "updated"} else "",
            }
            result["external_assertions"] = ["External Codex reports that this GitHub issue action occurred."]

    def _write(self, document: dict, name: str = "review-results-submission.json") -> Path:
        path = self.fixture.root / name
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        return path

    def _import(self, document: dict, name: str = "review-results-submission.json", **extra: object) -> dict:
        payload = {
            "ledger_path": str(self.fixture.ledger),
            "batch_path": str(self.fixture.batch_root),
            "expected_batch_id": self.fixture.batch_id,
            "results_path": str(self._write(document, name)),
        }
        payload.update(extra)
        return review_results.import_from_request(payload)

    def _counts(self) -> tuple[int, int, int, int]:
        connection = inbox_library.connect()
        try:
            return (
                int(connection.execute("SELECT COUNT(*) FROM inbox_final_results WHERE batch_id = ?", (self.fixture.batch_id,)).fetchone()[0]),
                int(connection.execute("SELECT COUNT(*) FROM inbox_findings WHERE batch_id = ? AND stage = 'final'", (self.fixture.batch_id,)).fetchone()[0]),
                int(connection.execute("SELECT COUNT(*) FROM inbox_attempts WHERE batch_id = ? AND attempt_type = 'final_results_import'", (self.fixture.batch_id,)).fetchone()[0]),
                int(connection.execute("SELECT COUNT(*) FROM inbox_lifecycle_events WHERE batch_id = ? AND event_type LIKE 'final_results%'", (self.fixture.batch_id,)).fetchone()[0]),
            )
        finally:
            connection.close()

    def test_generated_schema_template_working_file_readme_and_prompt(self) -> None:
        for name in (
            "review-results.schema.json",
            "review-results.template.json",
            "review-results.json",
            "README_FOR_REVIEW.md",
            "CODEX_REVIEW_PROMPT.md",
        ):
            self.assertTrue((self.fixture.batch_root / name).is_file(), name)
        schema = json.loads((self.fixture.batch_root / "review-results.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["document_type"]["const"], review_results.DOCUMENT_TYPE)
        prompt = (self.fixture.batch_root / "CODEX_REVIEW_PROMPT.md").read_text(encoding="utf-8")
        self.assertIn("open and closed GitHub issues", prompt)
        self.assertIn("explicit operator approval", prompt)
        self.assertIn("external_assertions", prompt)
        self.assertIn("Never edit", prompt)
        working = self.fixture.batch_root / "review-results.json"
        working.write_text('{"operator_work": "preserve exactly"}\n', encoding="utf-8")
        manifest = json.loads((self.fixture.batch_root / "batch-manifest.json").read_text(encoding="utf-8"))
        review_results.write_review_materials(self.fixture.batch_root, manifest)
        self.assertEqual(working.read_text(encoding="utf-8"), '{"operator_work": "preserve exactly"}\n')

    def test_generated_template_hashes_cover_initial_working_and_current_targeted_shapes(self) -> None:
        manifest = json.loads((self.fixture.batch_root / "batch-manifest.json").read_text(encoding="utf-8"))
        generated = review_results.generated_final_results_template_sha256s(self.fixture.batch_root, manifest)
        working = self.fixture.batch_root / "review-results.json"
        current = self.fixture.batch_root / "review-results.template.json"
        working_sha = hashlib.sha256(working.read_bytes()).hexdigest()
        current_sha = hashlib.sha256(current.read_bytes()).hexdigest()

        self.assertNotEqual(working_sha, current_sha)
        self.assertIn(working_sha, generated)
        self.assertIn(current_sha, generated)
        self.assertEqual(len(generated), 2)

    def test_every_supported_disposition_validates(self) -> None:
        for disposition in sorted(review_results.DISPOSITIONS):
            with self.subTest(disposition=disposition):
                document = self._valid_document()
                self._set_disposition(document, disposition)
                self.assertEqual(review_results.validate_document(document, self.basis), [])

    def test_complete_multi_source_no_actionable_results_import(self) -> None:
        result = self._import(self._valid_document())
        self.assertTrue(result["accepted"])
        self.assertEqual(result["status"], "results_received")
        self.assertEqual(result["source_count"], 2)
        self.assertEqual(result["result_count"], 2)
        connection = inbox_library.connect()
        try:
            self.assertEqual(connection.execute("SELECT status FROM inbox_batches WHERE batch_id = ?", (self.fixture.batch_id,)).fetchone()[0], "results_received")
            self.assertEqual({row[0] for row in connection.execute("SELECT state FROM inbox_batch_sources WHERE batch_id = ?", (self.fixture.batch_id,))}, {"results_received"})
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            connection.close()

    def test_unknown_batch_or_source_is_rejected(self) -> None:
        unknown_batch = review_results.import_from_request(
            {
                "ledger_path": str(self.fixture.ledger),
                "batch_path": str(self.fixture.batch_root),
                "expected_batch_id": "unknown-batch",
                "results_path": str(self._write(self._valid_document(), "unknown-batch.json")),
            }
        )
        self.assertFalse(unknown_batch["accepted"])
        document = self._valid_document()
        document["source_results"][0]["source_identity"] = "sha256:" + "f" * 64
        rejected = self._import(document, "unknown-source.json")
        self.assertFalse(rejected["accepted"])
        self.assertTrue(any("unknown" in problem.lower() or "cover" in problem.lower() for problem in rejected["problems"]))

    def test_unknown_preliminary_finding_or_request_is_rejected(self) -> None:
        document = self._valid_document()
        self._set_disposition(document, "already_implemented")
        result = document["source_results"][0]["results"][0]
        result["acknowledged_preliminary_finding_ids"] = ["unknown-finding"]
        result["acknowledged_request_ids"] = ["unknown-request"]
        rejected = self._import(document, "unknown-references.json")
        self.assertFalse(rejected["accepted"])
        self.assertTrue(any("unknown" in problem.lower() for problem in rejected["problems"]))

    def test_missing_targeted_request_acknowledgement_is_rejected(self) -> None:
        document = self._valid_document()
        document["source_results"][0]["targeted_request_acknowledgements"] = []
        rejected = self._import(document, "missing-ack.json")
        self.assertFalse(rejected["accepted"])
        self.assertTrue(any("acknowledge every targeted request" in problem for problem in rejected["problems"]))

    def test_duplicate_result_and_final_finding_ids_are_rejected(self) -> None:
        document = self._valid_document()
        self._set_disposition(document, "already_implemented")
        duplicate = deepcopy(document["source_results"][0]["results"][0])
        document["source_results"][1]["results"] = [duplicate]
        rejected = self._import(document, "duplicate-identities.json")
        self.assertFalse(rejected["accepted"])
        self.assertTrue(any("duplicates another" in problem for problem in rejected["problems"]))

    def test_invalid_timestamps_are_rejected(self) -> None:
        document = self._valid_document()
        self._set_disposition(document, "already_implemented")
        document["source_results"][0]["results"][0]["timestamps"] = [
            {"kind": "range", "start_seconds": 121.0, "end_seconds": 10.0}
        ]
        rejected = self._import(document, "invalid-timestamps.json")
        self.assertFalse(rejected["accepted"])
        self.assertTrue(any("timestamp" in problem.lower() or "end_seconds" in problem for problem in rejected["problems"]))

    def test_unsupported_disposition_is_rejected(self) -> None:
        document = self._valid_document()
        document["source_results"][0]["results"][0]["disposition"] = "silently_close_everything"
        rejected = self._import(document, "unsupported-disposition.json")
        self.assertFalse(rejected["accepted"])
        self.assertTrue(any("unsupported" in problem for problem in rejected["problems"]))

    def test_missing_or_contradictory_issue_reference_is_rejected(self) -> None:
        document = self._valid_document()
        self._set_disposition(document, "existing_issue_matched")
        document["source_results"][0]["results"][0]["issue"]["issue_url"] = "https://github.com/example/media-project/issues/99"
        rejected = self._import(document, "contradictory-issue.json")
        self.assertFalse(rejected["accepted"])
        self.assertTrue(any("exactly match" in problem for problem in rejected["problems"]))

    def test_new_or_updated_issue_requires_authorization_record(self) -> None:
        for disposition in ("new_issue_created", "existing_issue_updated"):
            with self.subTest(disposition=disposition):
                document = self._valid_document()
                self._set_disposition(document, disposition)
                document["source_results"][0]["results"][0]["issue"]["authorization_note"] = ""
                problems = review_results.validate_document(document, self.basis)
                self.assertTrue(any("explicit operator approval" in problem for problem in problems))

    def test_tampered_targeted_evidence_blocks_import(self) -> None:
        targeted_root = next(self.fixture.batch_root.glob("sources/*/targeted-evidence/f-*/r-*"))
        artifact = next(path for path in targeted_root.rglob("*.jpg"))
        artifact.write_bytes(b"tampered-before-final-results")
        rejected = self._import(self._valid_document(), "tampered-targeted.json")
        self.assertFalse(rejected["accepted"])
        self.assertTrue(any("failed integrity" in problem for problem in rejected["problems"]))

    def test_partial_results_and_malformed_json_are_preserved_and_rejected(self) -> None:
        partial = self._valid_document()
        partial["source_results"] = partial["source_results"][:1]
        partial["reviewed_source_identities"] = partial["reviewed_source_identities"][:1]
        rejected = self._import(partial, "partial-results.json")
        self.assertFalse(rejected["accepted"])
        self.assertTrue(Path(rejected["validation_record"]).is_file())
        malformed = self.fixture.root / "malformed-results.json"
        malformed.write_text('{"broken": ', encoding="utf-8")
        malformed_result = review_results.import_from_request(
            {
                "ledger_path": str(self.fixture.ledger),
                "batch_path": str(self.fixture.batch_root),
                "expected_batch_id": self.fixture.batch_id,
                "results_path": str(malformed),
            }
        )
        self.assertFalse(malformed_result["accepted"])
        self.assertTrue(Path(malformed_result["validation_record"]).is_file())

    def test_exact_accepted_rerun_is_idempotent_without_duplicate_rows(self) -> None:
        document = self._valid_document()
        first = self._import(document, "accepted-idempotent.json")
        self.assertTrue(first["accepted"])
        before = self._counts()
        repeat = self._import(document, "accepted-idempotent.json")
        self.assertTrue(repeat["accepted"])
        self.assertTrue(repeat["idempotent"])
        self.assertEqual(before, self._counts())

    def test_exact_rejected_rerun_is_idempotent_with_recorded_problems(self) -> None:
        document = self._valid_document()
        document["source_results"] = []
        first = self._import(document, "rejected-idempotent.json")
        before = self._counts()
        repeat = self._import(document, "rejected-idempotent.json")
        self.assertFalse(repeat["accepted"])
        self.assertTrue(repeat["idempotent"])
        self.assertEqual(first["problems"], repeat["problems"])
        self.assertEqual(before, self._counts())

    def test_staged_crash_resumes_exact_submission(self) -> None:
        document = self._valid_document()
        with self.assertRaises(SimulatedCrash):
            self._import(
                document,
                "staged-crash.json",
                _after_validation_staged=lambda _validation: (_ for _ in ()).throw(SimulatedCrash()),
            )
        retry = self._import(document, "staged-crash.json")
        self.assertTrue(retry["accepted"])
        validation = json.loads(Path(retry["validation_record"]).read_text(encoding="utf-8"))
        self.assertGreaterEqual(validation["resume_count"], 1)

    def test_crash_after_ledger_commit_reconciles_without_duplicates(self) -> None:
        document = self._valid_document()
        with self.assertRaises(SimulatedCrash):
            self._import(
                document,
                "ledger-crash.json",
                _after_ledger_commit=lambda _validation: (_ for _ in ()).throw(SimulatedCrash()),
            )
        before = self._counts()
        retry = self._import(document, "ledger-crash.json")
        self.assertTrue(retry["accepted"])
        self.assertTrue(retry["idempotent"])
        self.assertEqual(before, self._counts())
        validation = json.loads(Path(retry["validation_record"]).read_text(encoding="utf-8"))
        self.assertEqual(validation["import_phase"], "accepted")

    def test_different_submission_cannot_replace_accepted_results(self) -> None:
        accepted = self._valid_document()
        self.assertTrue(self._import(accepted, "immutable-accepted.json")["accepted"])
        corrected = deepcopy(accepted)
        corrected["operator_summary"] = "A different corrected submission that must not overwrite accepted history."
        rejected = self._import(corrected, "immutable-different.json")
        self.assertFalse(rejected["accepted"])
        self.assertTrue(any("immutable" in problem or "supersession" in problem for problem in rejected["problems"]))
        self.assertEqual((self.fixture.batch_root / "review-results.json").read_text(encoding="utf-8"), self._write(accepted, "expected-canonical.json").read_text(encoding="utf-8"))

    def test_rejection_changes_no_lifecycle_and_creates_no_cleanup(self) -> None:
        before_sources = self.fixture._states()
        document = self._valid_document()
        document["source_results"] = []
        rejected = self._import(document, "no-cleanup-rejection.json")
        self.assertFalse(rejected["accepted"])
        self.assertEqual(before_sources, self.fixture._states())
        self.assertFalse((self.fixture.batch_root / ".finalization").exists())
        self.assertFalse((self.fixture.ledger.parent / "history").exists())

    def test_cli_imports_complete_final_results_contract(self) -> None:
        submission = self._write(self._valid_document(), "cli-final-results.json")
        request = self.fixture.root / "cli-request.json"
        response = self.fixture.root / "cli-response.json"
        write_json_file(
            request,
            CommandEnvelope(
                payload={
                    "ledger_path": str(self.fixture.ledger),
                    "batch_path": str(self.fixture.batch_root),
                    "expected_batch_id": self.fixture.batch_id,
                    "results_path": str(submission),
                }
            ).to_dict(),
        )
        self.assertEqual(main(["review-media-inbox-import-results", "--request-file", str(request), "--result-file", str(response)]), 0)
        result = read_json_file(response)
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["status"], "results_received")


if __name__ == "__main__":
    unittest.main()
