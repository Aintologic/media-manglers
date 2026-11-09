from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from media_manglers.core import review_finalization, review_results, safe_write
from media_manglers.cli import main
from media_manglers.contracts import CommandEnvelope, read_json_file, write_json_file
from tests.test_review_inbox_final_results import ReviewInboxFinalResultsTests
import pytest
from tests import inbox_library  # noqa: E402

# 224 (Wave B2b): the Inbox's records are in this test's library, moved in (nothing to move).
pytestmark = pytest.mark.inbox_moved


class SimulatedCrash(BaseException):
    pass


class ReviewInboxFinalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ReviewInboxFinalResultsTests(methodName="runTest")
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    @property
    def ledger(self) -> Path:
        return self.fixture.fixture.ledger

    @property
    def batch_root(self) -> Path:
        return self.fixture.fixture.batch_root

    @property
    def batch_id(self) -> str:
        return self.fixture.fixture.batch_id

    def _accept(self, dispositions: list[str] | None = None) -> dict:
        document = self.fixture._valid_document()
        for index, disposition in enumerate(dispositions or []):
            self.fixture._set_disposition_for_source(document, index, disposition)
        result = self.fixture._import(document, "finalization-results.json")
        self.assertTrue(result["accepted"], result.get("problems"))
        return result

    def _preview(self, **extra: object) -> dict:
        payload = {
            "ledger_path": str(self.ledger),
            "batch_path": str(self.batch_root),
            "expected_batch_id": self.batch_id,
        }
        payload.update(extra)
        return review_finalization.preview_from_request(payload)

    def _finalize(self, preview: dict, **extra: object) -> dict:
        payload = {
            "plan_path": preview["plan_path"],
            "plan_sha256": preview["plan_sha256"],
            "operator_confirmed": True,
        }
        payload.update(extra)
        return review_finalization.finalize_from_request(payload)

    def _counts(self) -> tuple[int, int, int, int]:
        connection = inbox_library.connect()
        try:
            return (
                int(connection.execute("SELECT COUNT(*) FROM inbox_finalization_runs WHERE batch_id = ?", (self.batch_id,)).fetchone()[0]),
                int(connection.execute("SELECT COUNT(*) FROM inbox_retention_records WHERE batch_id = ?", (self.batch_id,)).fetchone()[0]),
                int(connection.execute("SELECT COUNT(*) FROM inbox_attempts WHERE batch_id = ? AND attempt_type = 'finalization'", (self.batch_id,)).fetchone()[0]),
                int(connection.execute("SELECT COUNT(*) FROM inbox_lifecycle_events WHERE batch_id = ? AND event_type LIKE 'finalization_%'", (self.batch_id,)).fetchone()[0]),
            )
        finally:
            connection.close()

    def _assert_originals_unchanged(self, before: dict[str, tuple[bytes, int, str]]) -> None:
        for raw_path, expected in before.items():
            path = Path(raw_path)
            self.assertTrue(path.is_file())
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns, path.name), expected)

    def _original_snapshot(self) -> dict[str, tuple[bytes, int, str]]:
        connection = inbox_library.connect()
        try:
            paths = [str(row[0]) for row in connection.execute(
                "SELECT DISTINCT sl.original_path FROM inbox_source_locations sl JOIN inbox_batch_sources bs ON bs.source_id = sl.source_id WHERE bs.batch_id = ?",
                (self.batch_id,),
            )]
        finally:
            connection.close()
        return {path: (Path(path).read_bytes(), Path(path).stat().st_mtime_ns, Path(path).name) for path in paths}

    def test_no_findings_preview_execution_retention_integrity_and_original_safety(self) -> None:
        originals = self._original_snapshot()
        self._accept()
        preview = self._preview()
        self.assertEqual(preview["resulting_batch_state"], "finalized_no_findings")
        self.assertGreater(sum(len(source["cleanup_actions"]) for source in preview["sources"]), 0)
        result = self._finalize(preview)
        self.assertEqual(result["status"], "finalized_no_findings")
        for source in preview["sources"]:
            history = Path(source["history_destination"])
            self.assertTrue((history / "package" / "transcript").is_dir())
            self.assertFalse((history / "package" / "visuals").exists())
            self.assertFalse((history / "package" / "targeted-evidence").exists())
            review_finalization._verify_history(history, preview["plan_sha256"], source["source_identity"])
            for action in source["cleanup_actions"]:
                self.assertFalse((self.batch_root / action["batch_relative_path"]).exists())
        self._assert_originals_unchanged(originals)

    def test_keep_generated_evidence_finalizes_without_cleanup_actions(self) -> None:
        originals = self._original_snapshot()
        self._accept()
        preview = self._preview(retention_policy="keep_generated")
        self.assertEqual(preview["plan_version"], 1)
        self.assertTrue(all(source["cleanup_actions"] == [] for source in preview["sources"]))
        result = self._finalize(preview)
        self.assertEqual(result["status"], "finalized_no_findings")
        retained_targeted = False
        for source in result["sources"]:
            package = Path(source["history_destination"]) / "package"
            self.assertTrue((package / "visuals").is_dir())
            retained_targeted = retained_targeted or (package / "targeted-evidence").is_dir()
        self.assertTrue(retained_targeted)
        self._assert_originals_unchanged(originals)

    def test_issue_related_evidence_is_retained(self) -> None:
        self._accept(["existing_issue_updated"])
        preview = self._preview()
        self.assertEqual(preview["resulting_batch_state"], "finalized_with_findings")
        finding_source = next(source for source in preview["sources"] if source["resulting_state"] == "finalized_with_findings")
        self.assertEqual(finding_source["cleanup_actions"], [])
        result = self._finalize(preview)
        self.assertEqual(result["status"], "finalized_with_findings")
        finding_result = next(source for source in result["sources"] if source["resulting_state"] == "finalized_with_findings")
        self.assertTrue((Path(finding_result["history_destination"]) / "package" / "targeted-evidence").is_dir())

    def test_already_implemented_evidence_is_retained(self) -> None:
        self._accept(["already_implemented"])
        preview = self._preview()
        finding_source = next(source for source in preview["sources"] if source["resulting_state"] == "finalized_with_findings")
        self.assertEqual(finding_source["cleanup_actions"], [])
        self.assertEqual(self._finalize(preview)["status"], "finalized_with_findings")

    def test_duplicate_supporting_evidence_is_retained(self) -> None:
        self._accept(["duplicate_supporting_evidence"])
        preview = self._preview()
        finding_source = next(source for source in preview["sources"] if source["resulting_state"] == "finalized_with_findings")
        self.assertEqual(finding_source["cleanup_actions"], [])
        self.assertEqual(self._finalize(preview)["status"], "finalized_with_findings")

    def test_uncertain_source_remains_manual_without_cleanup(self) -> None:
        self._accept(["uncertain_manual_review", "no_actionable_findings"])
        preview = self._preview()
        manual = next(source for source in preview["sources"] if source["resulting_state"] == "needs_manual_review")
        self.assertEqual(manual["cleanup_actions"], [])
        result = self._finalize(preview)
        self.assertEqual(result["status"], "needs_manual_review")

    def test_review_failure_remains_retryable_and_retains_logs(self) -> None:
        logs = self.batch_root / "logs"
        logs.mkdir(exist_ok=True)
        (logs / "synthetic.log").write_text("sanitized synthetic log\n", encoding="utf-8")
        self._accept(["review_failure", "no_actionable_findings"])
        preview = self._preview()
        failed = next(source for source in preview["sources"] if source["resulting_state"] == "retryable_failure")
        self.assertEqual(failed["cleanup_actions"], [])
        result = self._finalize(preview)
        self.assertEqual(result["status"], "retryable_failure")
        failed_result = next(source for source in result["sources"] if source["resulting_state"] == "retryable_failure")
        self.assertTrue((Path(failed_result["history_destination"]) / "logs" / "synthetic.log").is_file())

    def test_operator_confirmation_is_required_and_cancelled_preview_moves_nothing(self) -> None:
        self._accept()
        preview = self._preview()
        before = {action["batch_relative_path"] for source in preview["sources"] for action in source["cleanup_actions"]}
        waiting = review_finalization.finalize_from_request({"plan_path": preview["plan_path"], "plan_sha256": preview["plan_sha256"]})
        self.assertEqual(waiting["status"], "awaiting_operator_confirmation")
        cancelled = review_finalization.finalize_from_request(
            {"plan_path": preview["plan_path"], "plan_sha256": preview["plan_sha256"], "operator_confirmed": True, "cancel_before_start": True}
        )
        self.assertEqual(cancelled["status"], "cancelled_before_execution")
        self.assertTrue(all((self.batch_root / relative).is_file() for relative in before))
        self.assertEqual(self._counts(), (0, 0, 0, 0))

    def test_symlink_and_path_escape_are_rejected(self) -> None:
        self._accept()
        source_file = next((self.batch_root / "sources").rglob("*.jpg"))
        original_is_symlink = Path.is_symlink
        with patch.object(Path, "is_symlink", autospec=True, side_effect=lambda path: path == source_file or original_is_symlink(path)):
            with self.assertRaises(review_finalization.FinalizationError):
                self._preview()
        preview = self._preview()
        plan_path = Path(preview["plan_path"])
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["sources"][0]["cleanup_actions"][0]["batch_relative_path"] = "../outside.dat"
        content = {key: value for key, value in plan.items() if key != "plan_sha256"}
        plan["plan_sha256"] = review_finalization._canonical_sha(content)
        escaped = plan_path.parent / "plan-escaped.json"
        escaped.write_text(json.dumps(plan), encoding="utf-8")
        with self.assertRaises(review_finalization.FinalizationError):
            review_finalization.finalize_from_request(
                {"plan_path": str(escaped), "plan_sha256": plan["plan_sha256"], "operator_confirmed": True}
            )

    def test_changed_prepared_or_results_evidence_after_preview_blocks_all_movement(self) -> None:
        self._accept()
        preview = self._preview()
        retain = preview["sources"][0]["retain_actions"][0]
        path = self.batch_root / retain["batch_relative_path"]
        path.write_bytes(path.read_bytes() + b"changed-after-preview")
        with self.assertRaises((review_finalization.FinalizationError, review_results.FinalResultsError)):
            self._finalize(preview)
        self.assertFalse((self.batch_root / ".finalization" / "quarantine").exists())
        self.assertEqual(self._counts(), (0, 0, 0, 0))

    def test_crash_before_movement_recovers_idempotently(self) -> None:
        self._accept()
        preview = self._preview()
        with self.assertRaises(SimulatedCrash):
            self._finalize(preview, _before_movement=lambda _plan: (_ for _ in ()).throw(SimulatedCrash()))
        self.assertEqual(self._finalize(preview)["status"], "finalized_no_findings")
        counts = self._counts()
        self.assertEqual(self._finalize(preview)["status"], "finalized_no_findings")
        self.assertEqual(counts, self._counts())

    def test_crash_after_planned_journal_before_ledger_start_recovers(self) -> None:
        self._accept()
        preview = self._preview()
        with self.assertRaises(SimulatedCrash):
            self._finalize(
                preview,
                _after_journal_planned=lambda _plan: (_ for _ in ()).throw(SimulatedCrash()),
            )
        self.assertEqual(self._counts(), (0, 0, 0, 0))
        self.assertEqual(self._finalize(preview)["status"], "finalized_no_findings")
        counts = self._counts()
        self.assertEqual(counts[0], 1)
        self.assertEqual(self._finalize(preview)["status"], "finalized_no_findings")
        self.assertEqual(counts, self._counts())

    def test_crash_during_quarantine_recovers(self) -> None:
        self._accept()
        preview = self._preview()
        with self.assertRaises(SimulatedCrash):
            self._finalize(preview, _during_quarantine_movement=lambda _source: (_ for _ in ()).throw(SimulatedCrash()))
        quarantine = self.batch_root / ".finalization" / "quarantine" / preview["plan_sha256"][:24]
        self.assertTrue(any(path.is_file() for path in quarantine.rglob("*")))
        self.assertEqual(self._finalize(preview)["status"], "finalized_no_findings")

    def test_crash_during_history_staging_recovers(self) -> None:
        self._accept()
        preview = self._preview()
        with self.assertRaises(SimulatedCrash):
            self._finalize(preview, _during_history_staging=lambda _source: (_ for _ in ()).throw(SimulatedCrash()))
        self.assertEqual(self._finalize(preview)["status"], "finalized_no_findings")

    def test_crash_after_history_promotion_keeps_quarantine_until_ledger_commit(self) -> None:
        self._accept()
        preview = self._preview()
        quarantine = self.batch_root / ".finalization" / "quarantine" / preview["plan_sha256"][:24]
        with self.assertRaises(SimulatedCrash):
            self._finalize(
                preview,
                _after_history_promotion=lambda _plan: (
                    self.assertTrue(quarantine.is_dir()),
                    (_ for _ in ()).throw(SimulatedCrash()),
                ),
            )
        self.assertEqual(self._finalize(preview)["status"], "finalized_no_findings")

    def test_crash_after_ledger_commit_recovers_without_duplicate_records(self) -> None:
        self._accept()
        preview = self._preview()
        with self.assertRaises(SimulatedCrash):
            self._finalize(preview, _after_ledger_commit=lambda _plan: (_ for _ in ()).throw(SimulatedCrash()))
        before = self._counts()
        result = self._finalize(preview)
        self.assertEqual(result["status"], "finalized_no_findings")
        self.assertEqual(before, self._counts())

    def test_crash_during_cleanup_recovers(self) -> None:
        self._accept()
        preview = self._preview()
        with self.assertRaises(SimulatedCrash):
            self._finalize(preview, _after_cleanup=lambda _plan: (_ for _ in ()).throw(SimulatedCrash()))
        self.assertEqual(self._finalize(preview)["status"], "finalized_no_findings")

    def test_partial_quarantine_deletion_recovers(self) -> None:
        self._accept()
        preview = self._preview()
        # 224 (Wave B2a): the quarantine is deleted by the one antivirus-safe helper.
        real_rmtree = safe_write.shutil.rmtree

        def interrupt_cleanup(path: Path) -> None:
            target = Path(path)
            if "quarantine" in target.parts:
                first = next(item for item in target.rglob("*") if item.is_file())
                first.unlink()
                raise SimulatedCrash()
            real_rmtree(path)

        with patch.object(safe_write.shutil, "rmtree", side_effect=interrupt_cleanup):
            with self.assertRaises(SimulatedCrash):
                self._finalize(preview)
        self.assertEqual(self._finalize(preview)["status"], "finalized_no_findings")

    def test_corrupted_plan_and_journal_fail_closed(self) -> None:
        self._accept()
        preview = self._preview()
        plan_path = Path(preview["plan_path"])
        original = plan_path.read_text(encoding="utf-8")
        plan_path.write_text(original.replace('"plan_version": 1', '"plan_version": 9'), encoding="utf-8")
        with self.assertRaises(review_finalization.FinalizationError):
            self._finalize(preview)
        plan_path.write_text(original, encoding="utf-8")
        with self.assertRaises(SimulatedCrash):
            self._finalize(preview, _before_movement=lambda _plan: (_ for _ in ()).throw(SimulatedCrash()))
        journal = self.batch_root / ".finalization" / f"journal-{preview['plan_sha256'][:24]}.json"
        journal.write_text(journal.read_text(encoding="utf-8").replace('"phase": "planned"', '"phase": "quarantined"'), encoding="utf-8")
        with self.assertRaises(review_finalization.FinalizationError):
            self._finalize(preview)

    def test_cli_previews_and_executes_confirmed_finalization(self) -> None:
        self._accept()
        preview_request = self.fixture.fixture.root / "preview-request.json"
        preview_response = self.fixture.fixture.root / "preview-response.json"
        write_json_file(
            preview_request,
            CommandEnvelope(payload={"ledger_path": str(self.ledger), "batch_path": str(self.batch_root), "expected_batch_id": self.batch_id}).to_dict(),
        )
        self.assertEqual(main(["review-media-inbox-finalization-preview", "--request-file", str(preview_request), "--result-file", str(preview_response)]), 0)
        preview = read_json_file(preview_response)["data"]
        finalize_request = self.fixture.fixture.root / "finalize-request.json"
        finalize_response = self.fixture.fixture.root / "finalize-response.json"
        write_json_file(
            finalize_request,
            CommandEnvelope(payload={"plan_path": preview["plan_path"], "plan_sha256": preview["plan_sha256"], "operator_confirmed": True}).to_dict(),
        )
        self.assertEqual(main(["review-media-inbox-finalize", "--request-file", str(finalize_request), "--result-file", str(finalize_response)]), 0)
        self.assertEqual(read_json_file(finalize_response)["data"]["status"], "finalized_no_findings")


if __name__ == "__main__":
    unittest.main()
