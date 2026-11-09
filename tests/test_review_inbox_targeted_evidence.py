from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from media_manglers.cli import main
from media_manglers.contracts import CommandEnvelope, read_json_file, write_json_file
from media_manglers.core import inbox_records, review_findings, review_inbox, review_ledger, review_targeted_evidence
from tests import test_review_inbox_preliminary_findings as preliminary_tests
from tests import test_review_inbox_preparation as preparation_tests
import pytest
from tests import inbox_library  # noqa: E402

# 224 (Wave B2b): the Inbox's records are in this test's library, moved in (nothing to move).
pytestmark = pytest.mark.inbox_moved


class SimulatedCrash(BaseException):
    pass


class ReviewInboxTargetedEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = preliminary_tests.ReviewInboxPreliminaryFindingsTests(methodName="runTest")
        self.fixture.setUp()
        self.document = deepcopy(self.fixture.document)
        self.document["findings"] = [self.fixture._finding()]
        imported = self.fixture._import(self.fixture._write(self.document, "accepted-targeted.json"))
        self.assertTrue(imported["accepted"])
        self.submission_sha = str(imported["submission_sha256"])

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def _plan(self, **extra: object) -> dict:
        payload = {
            "ledger_path": str(self.fixture.ledger),
            "batch_path": str(self.fixture.batch_root),
            "expected_batch_id": self.fixture.batch_id,
            "preliminary_submission_sha256": self.submission_sha,
        }
        payload.update(extra)
        return review_targeted_evidence.plan_from_request(payload)

    @staticmethod
    def _render(plan: dict, *, omit_last: bool = False) -> tuple[list[dict], list[dict], list[str]]:
        frame_results: list[dict] = []
        audio_results: list[dict] = []
        processed: list[str] = []
        pending = [item for item in plan["request_plans"] if not item.get("existing_complete")]
        if omit_last:
            pending = pending[:-1]
        for request in pending:
            for task in request.get("frame_tasks") or []:
                path = Path(task["path"])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"frame:{task['timestamp_seconds']}".encode("ascii"))
                panels = []
                for panel in task.get("panels") or []:
                    panel_path = Path(panel["path"])
                    panel_path.parent.mkdir(parents=True, exist_ok=True)
                    panel_path.write_bytes(f"panel:{panel['role']}".encode("ascii"))
                    panels.append({"path": str(panel_path), "status": "created", "role": panel["role"]})
                frame_results.append({"path": str(path), "status": "created", "panels": panels})
            for task in request.get("audio_tasks") or []:
                path = Path(task["path"])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic-audio")
                audio_results.append({"path": str(path), "status": "created"})
            processed.append(str(request["render_signature"]))
        return frame_results, audio_results, processed

    def _complete(self, plan: dict, **extra: object) -> dict:
        frames, audio, processed = self._render(plan)
        payload = {
            "plan_path": plan["plan_path"],
            "plan_sha256": plan["plan_sha256"],
            "frame_results": frames,
            "audio_results": audio,
            "processed_request_signatures": processed,
        }
        payload.update(extra)
        return review_targeted_evidence.complete_from_request(payload)

    def _counts(self) -> tuple[int, int, int]:
        return self._counts_for_ledger(self.fixture.ledger, self.fixture.batch_id)

    @staticmethod
    def _counts_for_ledger(ledger: Path, batch_id: str) -> tuple[int, int, int]:
        connection = inbox_library.connect()
        try:
            attempts = int(connection.execute("SELECT COUNT(*) FROM inbox_attempts WHERE attempt_type LIKE 'targeted_evidence%'").fetchone()[0])
            events = int(connection.execute("SELECT COUNT(*) FROM inbox_lifecycle_events WHERE event_type LIKE 'targeted_evidence%'").fetchone()[0])
            findings = int(connection.execute("SELECT COUNT(*) FROM inbox_findings WHERE batch_id = ?", (batch_id,)).fetchone()[0])
            return attempts, events, findings
        finally:
            connection.close()

    @staticmethod
    def _prepared_audio_fixture() -> tuple[object, dict, Path, dict, str]:
        fixture = preparation_tests.ReviewInboxPreparationTests(methodName="runTest")
        fixture.setUp()
        fixture.make_sources(1)
        media = fixture.media(2, width=5760, height=1080, duration=120.0)
        fingerprint = media["audio_layout_fingerprint"]
        confirmations = {fingerprint: {"layoutFingerprint": fingerprint, "audioOrdinal": 1, "confirmationSource": "operator"}}

        def render(source: Path, media_info: dict, output: Path) -> dict:
            result = fixture.render(source, media_info, output)
            index_path = output / "timeline-index.json"
            index = json.loads(index_path.read_text(encoding="utf-8"))
            panels = []
            for role in ("driver_view", "overview_cam"):
                relative = f"panels/frame-001-{role}.jpg"
                target = output / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(f"panel:{role}".encode("ascii"))
                panels.append({"panel": role, "timestamp_seconds": 1.0, "path": relative})
            index["panels"] = panels
            review_targeted_evidence.review_preparation._atomic_json(index_path, index)
            result["panels"] = panels
            return result

        prepared = review_targeted_evidence.review_preparation.prepare_from_request(
            fixture.payload(media_probe=lambda _path: media, audio_confirmations=confirmations, visual_renderer=render)
        )
        batch_root = Path(prepared["batch_path"])
        document = json.loads((batch_root / "preliminary-findings.template.json").read_text(encoding="utf-8"))
        return fixture, prepared, batch_root, document, str(document["reviewed_source_identities"][0])

    def test_requires_a_completely_accepted_preliminary_submission(self) -> None:
        connection = inbox_records.connect(self.fixture.ledger)
        try:
            connection.execute("DELETE FROM inbox_attempts WHERE attempt_type = 'preliminary_findings_import'")
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(RuntimeError, "not completely accepted"):
            self._plan()

    def test_plan_revalidates_preserved_submission_and_package_integrity(self) -> None:
        history = self.fixture.batch_root / "imports" / "preliminary-findings" / self.submission_sha[:24]
        (history / "preliminary-findings.json").write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "SHA-256 no longer matches"):
            self._plan()

    def test_deterministic_frame_plan_honors_bounds_and_maximum(self) -> None:
        plan = self._plan()
        request = plan["request_plans"][0]
        timestamps = [float(item["timestamp_seconds"]) for item in request["frame_tasks"]]
        self.assertEqual(timestamps, sorted(timestamps))
        self.assertLessEqual(len(timestamps), 5)
        self.assertTrue(all(8.0 <= value <= 17.0 for value in timestamps))
        self.assertIn(10.0, timestamps)
        self.assertIn(15.0, timestamps)

    def test_point_frame_only_request_preserves_the_requested_point(self) -> None:
        fixture = preliminary_tests.ReviewInboxPreliminaryFindingsTests(methodName="runTest")
        fixture.setUp()
        try:
            document = deepcopy(fixture.document)
            finding = fixture._finding()
            finding["requests"][0]["timestamp"] = {"kind": "point", "at_seconds": 60.0}
            document["findings"] = [finding]
            imported = fixture._import(fixture._write(document, "point-frame.json"))
            plan = review_targeted_evidence.plan_from_request(
                {"ledger_path": str(fixture.ledger), "batch_path": str(fixture.batch_root), "expected_batch_id": fixture.batch_id, "preliminary_submission_sha256": imported["submission_sha256"]}
            )
            request = plan["request_plans"][0]
            self.assertIn(60.0, [item["timestamp_seconds"] for item in request["frame_tasks"]])
            self.assertEqual(request["interval"]["requested_interval"], {"start_seconds": 60.0, "end_seconds": 60.0})
        finally:
            fixture.tearDown()

    def test_effective_intervals_clip_at_source_start_and_end_with_warnings(self) -> None:
        fixture = preliminary_tests.ReviewInboxPreliminaryFindingsTests(methodName="runTest")
        fixture.setUp()
        try:
            document = deepcopy(fixture.document)
            findings = []
            for index, point in enumerate((1.0, 119.0), 1):
                finding = fixture._finding()
                finding["finding_id"] = f"clip-{index}"
                request = finding["requests"][0]
                request["request_id"] = f"clip-request-{index}"
                request["timestamp"] = {"kind": "point", "at_seconds": point}
                request["frames"]["before_seconds"] = 10.0
                request["frames"]["after_seconds"] = 10.0
                findings.append(finding)
            document["findings"] = findings
            imported = fixture._import(fixture._write(document, "clipped.json"))
            plan = review_targeted_evidence.plan_from_request(
                {"ledger_path": str(fixture.ledger), "batch_path": str(fixture.batch_root), "expected_batch_id": fixture.batch_id, "preliminary_submission_sha256": imported["submission_sha256"]}
            )
            intervals = [item["interval"] for item in plan["request_plans"]]
            self.assertEqual(intervals[0]["effective_interval"]["start_seconds"], 0.0)
            self.assertEqual(intervals[1]["effective_interval"]["end_seconds"], 120.0)
            self.assertTrue(all(item["warnings"] for item in intervals))
        finally:
            fixture.tearDown()

    def test_plan_uses_bounded_tokens_and_workflow3_task_shapes(self) -> None:
        request = self._plan()["request_plans"][0]
        relative = Path(request["final_root"]).relative_to(self.fixture.batch_root)
        self.assertLess(max(len(part) for part in relative.parts), 40)
        task = request["frame_tasks"][0]
        self.assertEqual(task["panel_crop_mode"], "off")
        self.assertIn("source_path", task)
        self.assertIn("timestamp_seconds", task)
        self.assertIn("relative_path", task)

    def test_completion_rejects_a_rewritten_plan_that_escapes_batch_roots(self) -> None:
        plan = self._plan()
        plan_path = Path(plan["plan_path"])
        document = json.loads(plan_path.read_text(encoding="utf-8"))
        document["request_plans"][0]["final_root"] = str(self.fixture.root / "outside-target")
        review_targeted_evidence._atomic_json(plan_path, document)
        rewritten_sha = review_ledger.sha256_file(plan_path)
        with self.assertRaisesRegex(RuntimeError, "outside its approved root"):
            review_targeted_evidence.complete_from_request(
                {"plan_path": str(plan_path), "plan_sha256": rewritten_sha, "processed_request_signatures": []}
            )

    def test_source_is_fully_reverified_without_modifying_original(self) -> None:
        source = self.fixture.sources / "source-00.mp4"
        before = (source.read_bytes(), source.stat().st_mtime_ns)
        plan = self._plan()
        after = (source.read_bytes(), source.stat().st_mtime_ns)
        self.assertEqual(before, after)
        self.assertEqual(plan["request_plans"][0]["source_verification_before"]["content_sha256"], self.fixture.identities[0].split(":", 1)[1])

    def test_recorded_relocation_is_resolved_and_marked_current(self) -> None:
        original = self.fixture.sources / "source-00.mp4"
        relocated = self.fixture.sources / "renamed-source.mp4"
        original.rename(relocated)
        connection = inbox_records.connect(self.fixture.ledger)
        try:
            source_id = int(connection.execute("SELECT source_id FROM inbox_sources WHERE stable_identity = ?", (self.fixture.identities[0],)).fetchone()[0])
            now = "2026-07-19T00:00:00Z"
            stat = relocated.stat()
            connection.execute(
                "INSERT INTO inbox_source_locations (source_id, original_path, normalized_path, size_bytes, modified_ns, modified_utc, is_current, first_seen_utc, last_seen_utc) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)",
                (source_id, str(relocated), os.path.normcase(str(relocated.resolve())), stat.st_size, stat.st_mtime_ns, now, now, now),
            )
            connection.commit()
        finally:
            connection.close()
        request = self._plan()["request_plans"][0]
        self.assertEqual(Path(request["source_verification_before"]["source_path"]), relocated)
        self.assertTrue(request["source_verification_before"]["relocated"])

    def test_changed_source_isolated_as_source_changed_without_render_tasks(self) -> None:
        (self.fixture.sources / "source-00.mp4").write_bytes(b"changed-after-acceptance")
        plan = self._plan()
        self.assertEqual(plan["request_plans"], [])
        self.assertEqual(plan["source_failures"][0]["state"], "source_changed")
        connection = inbox_records.connect(self.fixture.ledger)
        try:
            state = connection.execute("SELECT state FROM inbox_batch_sources WHERE batch_id = ? ORDER BY ordinal", (self.fixture.batch_id,)).fetchone()[0]
            self.assertEqual(state, "source_changed")
        finally:
            connection.close()

    def test_missing_source_is_retryable_and_preserves_the_request(self) -> None:
        (self.fixture.sources / "source-00.mp4").unlink()
        plan = self._plan()
        self.assertEqual(plan["request_plans"], [])
        self.assertEqual(plan["source_failures"][0]["state"], "retryable_failure")
        history = self.fixture.batch_root / "imports" / "preliminary-findings" / self.submission_sha[:24] / "preliminary-findings.json"
        self.assertTrue(history.is_file())

    def test_source_change_during_full_hash_is_detected_before_tasks_are_built(self) -> None:
        source = self.fixture.sources / "source-00.mp4"

        def changing_hasher(path: Path) -> str:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            path.write_bytes(path.read_bytes() + b"changed-during-read")
            return digest

        plan = self._plan(full_hasher=changing_hasher)
        self.assertEqual(plan["request_plans"], [])
        self.assertEqual(plan["source_failures"][0]["state"], "source_changed")
        self.assertIn("changed while", plan["source_failures"][0]["error"])

    def test_complete_promotes_integrity_checked_package_and_lifecycle(self) -> None:
        result = self._complete(self._plan())
        self.assertEqual(result["status"], "targeted_evidence_ready")
        final_root = next(self.fixture.batch_root.glob("sources/*/targeted-evidence/f-*/r-*"))
        manifest = json.loads((final_root / "request-manifest.json").read_text(encoding="utf-8"))
        integrity = json.loads((final_root / "integrity.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["complete"])
        self.assertTrue(integrity["complete"])
        self.assertNotIn(str(self.fixture.sources), json.dumps(manifest))
        batches = review_inbox.list_pending_batches(self.fixture.ledger)
        self.assertEqual(batches[0]["status"], "targeted_evidence_ready")
        self.assertEqual(batches[0]["targeted_completed_request_count"], 1)

    def test_retry_after_crash_between_promotion_and_ledger_commit_is_idempotent(self) -> None:
        plan = self._plan()
        frames, audio, processed = self._render(plan)
        payload = {
            "plan_path": plan["plan_path"],
            "plan_sha256": plan["plan_sha256"],
            "frame_results": frames,
            "audio_results": audio,
            "processed_request_signatures": processed,
            "_after_promotion": lambda _item: (_ for _ in ()).throw(SimulatedCrash()),
        }
        with self.assertRaises(SimulatedCrash):
            review_targeted_evidence.complete_from_request(payload)
        recovered = self._plan()
        self.assertTrue(recovered["request_plans"][0]["existing_complete"])
        result = review_targeted_evidence.complete_from_request(
            {"plan_path": recovered["plan_path"], "plan_sha256": recovered["plan_sha256"], "processed_request_signatures": []}
        )
        self.assertEqual(result["status"], "targeted_evidence_ready")

    def test_retry_after_crash_after_ledger_commit_repairs_prompt_without_duplicates(self) -> None:
        plan = self._plan()
        frames, audio, processed = self._render(plan)
        with self.assertRaises(SimulatedCrash):
            review_targeted_evidence.complete_from_request(
                {
                    "plan_path": plan["plan_path"],
                    "plan_sha256": plan["plan_sha256"],
                    "frame_results": frames,
                    "audio_results": audio,
                    "processed_request_signatures": processed,
                    "_after_ledger_commit": lambda _item: (_ for _ in ()).throw(SimulatedCrash()),
                }
            )
        before = self._counts()
        result = self._plan()
        after = self._counts()
        self.assertEqual(result["status"], "targeted_evidence_ready")
        self.assertEqual(before, after)
        prompt = (self.fixture.batch_root / "CODEX_REVIEW_PROMPT.md").read_text(encoding="utf-8")
        self.assertIn("Targeted evidence ready for external review", prompt)

    def test_exact_retry_creates_no_duplicate_attempts_events_or_findings(self) -> None:
        self._complete(self._plan())
        before = self._counts()
        retry = self._plan()
        self.assertTrue(retry["idempotent"])
        self.assertEqual(before, self._counts())

    def test_tampered_completed_package_is_quarantined_and_ready_state_is_downgraded_for_recovery(self) -> None:
        self._complete(self._plan())
        final_root = next(self.fixture.batch_root.glob("sources/*/targeted-evidence/f-*/r-*"))
        artifact = next(path for path in final_root.rglob("*.jpg"))
        artifact.write_bytes(b"tampered")
        recovery = self._plan()
        self.assertEqual(recovery["status"], "ready_to_render")
        self.assertTrue(recovery["warnings"])
        self.assertTrue(any((self.fixture.batch_root / ".staging" / "targeted-evidence" / "quarantine").iterdir()))
        connection = inbox_records.connect(self.fixture.ledger)
        try:
            self.assertEqual(connection.execute("SELECT status FROM inbox_batches WHERE batch_id = ?", (self.fixture.batch_id,)).fetchone()[0], "preliminary_findings_received")
        finally:
            connection.close()

    def test_integrity_rejects_manifest_frame_removed_with_its_integrity_record(self) -> None:
        self._complete(self._plan())
        final_root = next(self.fixture.batch_root.glob("sources/*/targeted-evidence/f-*/r-*"))
        manifest = json.loads((final_root / "request-manifest.json").read_text(encoding="utf-8"))
        frame = next(item for item in manifest["artifact_inventory"] if item["kind"] == "frame")
        (final_root / frame["path"]).unlink()
        integrity_path = final_root / "integrity.json"
        integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
        integrity["files"] = [item for item in integrity["files"] if item["path"] != frame["path"]]
        review_targeted_evidence._atomic_json(integrity_path, integrity)

        valid, problems = review_targeted_evidence._verify_integrity(final_root, manifest["render_signature"])

        self.assertFalse(valid)
        self.assertTrue(any("manifest-declared" in problem or "omits a required" in problem for problem in problems))

    def test_integrity_rejects_manifest_panel_removed_with_its_integrity_record(self) -> None:
        self._complete(self._plan())
        final_root = next(self.fixture.batch_root.glob("sources/*/targeted-evidence/f-*/r-*"))
        manifest_path = final_root / "request-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        panel_path = final_root / "panels" / "synthetic-panel.jpg"
        panel_path.parent.mkdir(parents=True, exist_ok=True)
        panel_path.write_bytes(b"synthetic-targeted-panel")
        manifest["artifact_inventory"].append(
            {"artifact_id": "panel:synthetic:12.000", "kind": "panel", "panel_id": "synthetic", "timestamp_seconds": 12.0, "path": "panels/synthetic-panel.jpg"}
        )
        review_targeted_evidence._atomic_json(manifest_path, manifest)
        integrity_path = final_root / "integrity.json"
        integrity_path.unlink()
        review_targeted_evidence._atomic_json(
            integrity_path,
            {
                "schema_version": 1,
                "render_version": review_targeted_evidence.RENDER_VERSION,
                "render_signature": manifest["render_signature"],
                "complete": True,
                "files": review_targeted_evidence.review_preparation._hash_files(final_root),
            },
        )
        panel_path.unlink()
        integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
        integrity["files"] = [item for item in integrity["files"] if item["path"] != "panels/synthetic-panel.jpg"]
        review_targeted_evidence._atomic_json(integrity_path, integrity)

        valid, problems = review_targeted_evidence._verify_integrity(final_root, manifest["render_signature"])

        self.assertFalse(valid)
        self.assertTrue(any("synthetic-panel.jpg" in problem for problem in problems))

    def test_integrity_rejects_duplicate_inventory_path(self) -> None:
        self._complete(self._plan())
        final_root = next(self.fixture.batch_root.glob("sources/*/targeted-evidence/f-*/r-*"))
        manifest = json.loads((final_root / "request-manifest.json").read_text(encoding="utf-8"))
        integrity_path = final_root / "integrity.json"
        integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
        manifest_record = next(item for item in integrity["files"] if item["path"] == "request-manifest.json")
        integrity["files"].append(deepcopy(manifest_record))
        review_targeted_evidence._atomic_json(integrity_path, integrity)

        valid, problems = review_targeted_evidence._verify_integrity(final_root, manifest["render_signature"])

        self.assertFalse(valid)
        self.assertTrue(any("duplicate path" in problem for problem in problems))

    def test_integrity_rejects_record_path_outside_request_package(self) -> None:
        self._complete(self._plan())
        final_root = next(self.fixture.batch_root.glob("sources/*/targeted-evidence/f-*/r-*"))
        manifest = json.loads((final_root / "request-manifest.json").read_text(encoding="utf-8"))
        integrity_path = final_root / "integrity.json"
        integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
        integrity["files"].append({"path": "../outside.bin", "size_bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()})
        review_targeted_evidence._atomic_json(integrity_path, integrity)

        valid, problems = review_targeted_evidence._verify_integrity(final_root, manifest["render_signature"])

        self.assertFalse(valid)
        self.assertTrue(any("escapes the request package" in problem for problem in problems))

    def test_integrity_rejects_unexplained_file_even_when_integrity_lists_it(self) -> None:
        self._complete(self._plan())
        final_root = next(self.fixture.batch_root.glob("sources/*/targeted-evidence/f-*/r-*"))
        manifest = json.loads((final_root / "request-manifest.json").read_text(encoding="utf-8"))
        unexplained = final_root / "unexplained.bin"
        unexplained.write_bytes(b"not-declared-by-request-manifest")
        integrity_path = final_root / "integrity.json"
        integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
        integrity["files"].append(
            {"path": "unexplained.bin", "size_bytes": unexplained.stat().st_size, "sha256": review_ledger.sha256_file(unexplained)}
        )
        review_targeted_evidence._atomic_json(integrity_path, integrity)

        valid, problems = review_targeted_evidence._verify_integrity(final_root, manifest["render_signature"])

        self.assertFalse(valid)
        self.assertTrue(any("unexplained file" in problem for problem in problems))

    def test_integrity_rejects_modified_request_manifest_without_refreshed_record(self) -> None:
        self._complete(self._plan())
        final_root = next(self.fixture.batch_root.glob("sources/*/targeted-evidence/f-*/r-*"))
        manifest_path = final_root / "request-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["warnings"] = ["synthetic tamper"]
        review_targeted_evidence._atomic_json(manifest_path, manifest)

        valid, problems = review_targeted_evidence._verify_integrity(final_root, manifest["render_signature"])

        self.assertFalse(valid)
        self.assertTrue(
            any("request-manifest.json" in problem and ("size changed" in problem or "hash changed" in problem) for problem in problems)
        )

    def test_partial_batch_invalid_ready_source_is_downgraded_and_only_its_request_rerenders(self) -> None:
        fixture = preliminary_tests.ReviewInboxPreliminaryFindingsTests(methodName="runTest")
        fixture.setUp()
        try:
            document = deepcopy(fixture.document)
            finding_a = fixture._finding(fixture.identities[0])
            finding_b = fixture._finding(fixture.identities[1])
            finding_b["finding_id"] = "finding-002"
            finding_b["requests"][0]["request_id"] = "request-002"
            document["findings"] = [finding_a, finding_b]
            imported = fixture._import(fixture._write(document, "partial-batch-recovery.json"))
            payload = {
                "ledger_path": str(fixture.ledger),
                "batch_path": str(fixture.batch_root),
                "expected_batch_id": fixture.batch_id,
                "preliminary_submission_sha256": imported["submission_sha256"],
            }
            initial_plan = review_targeted_evidence.plan_from_request(payload)
            initial_result = self._complete(initial_plan)
            self.assertEqual(initial_result["status"], "targeted_evidence_ready")

            request_roots: dict[str, Path] = {}
            for root in fixture.batch_root.glob("sources/*/targeted-evidence/f-*/r-*"):
                request_manifest = json.loads((root / "request-manifest.json").read_text(encoding="utf-8"))
                request_roots[str(request_manifest["source_identity"])] = root
            source_a_identity, source_b_identity = fixture.identities
            source_a_root = request_roots[source_a_identity]
            source_b_root = request_roots[source_b_identity]
            source_b_integrity_before = review_ledger.sha256_file(source_b_root / "integrity.json")

            connection = inbox_records.connect(fixture.ledger)
            try:
                source_rows = {
                    str(row["stable_identity"]): int(row["source_id"])
                    for row in connection.execute("SELECT source_id, stable_identity FROM inbox_sources WHERE stable_identity IN (?, ?)", fixture.identities)
                }
                source_a_id = source_rows[source_a_identity]
                source_b_id = source_rows[source_b_identity]
                now = review_targeted_evidence._utc_now()
                connection.execute("UPDATE inbox_sources SET lifecycle_state = 'retryable_failure', updated_utc = ? WHERE source_id = ?", (now, source_b_id))
                connection.execute(
                    "UPDATE inbox_batch_sources SET state = 'retryable_failure', updated_utc = ? WHERE batch_id = ? AND source_id = ?",
                    (now, fixture.batch_id, source_b_id),
                )
                connection.execute("UPDATE inbox_batches SET status = 'preliminary_findings_received', updated_utc = ? WHERE batch_id = ?", (now, fixture.batch_id))
                connection.commit()
            finally:
                connection.close()

            damaged_manifest = json.loads((source_a_root / "request-manifest.json").read_text(encoding="utf-8"))
            damaged_artifact = source_a_root / damaged_manifest["artifact_inventory"][0]["path"]
            damaged_artifact.write_bytes(b"damaged-source-a-artifact")
            before_recovery_counts = self._counts_for_ledger(fixture.ledger, fixture.batch_id)

            recovery_plan = review_targeted_evidence.plan_from_request(payload)
            after_first_plan_counts = self._counts_for_ledger(fixture.ledger, fixture.batch_id)
            repeated_plan = review_targeted_evidence.plan_from_request(payload)
            self.assertEqual(after_first_plan_counts, self._counts_for_ledger(fixture.ledger, fixture.batch_id))
            self.assertEqual(before_recovery_counts[0], after_first_plan_counts[0])
            self.assertEqual(before_recovery_counts[2], after_first_plan_counts[2])
            self.assertEqual(source_b_integrity_before, review_ledger.sha256_file(source_b_root / "integrity.json"))
            self.assertEqual(
                {item["source_identity"] for item in recovery_plan["request_plans"] if not item.get("existing_complete")},
                {source_a_identity},
            )
            self.assertEqual(
                {item["source_identity"] for item in recovery_plan["request_plans"] if item.get("existing_complete")},
                {source_b_identity},
            )
            self.assertEqual(
                {item["source_identity"] for item in repeated_plan["request_plans"] if not item.get("existing_complete")},
                {source_a_identity},
            )
            preserved_submission = (
                fixture.batch_root
                / "imports"
                / "preliminary-findings"
                / str(imported["submission_sha256"])[:24]
                / "preliminary-findings.json"
            )
            self.assertTrue(preserved_submission.is_file())
            quarantine = fixture.batch_root / ".staging" / "targeted-evidence" / "quarantine"
            self.assertEqual(len(list(quarantine.iterdir())), 1)
            connection = inbox_records.connect(fixture.ledger)
            try:
                states = {
                    str(row["stable_identity"]): str(row["state"])
                    for row in connection.execute(
                        "SELECT s.stable_identity, bs.state FROM inbox_batch_sources bs JOIN inbox_sources s ON s.source_id = bs.source_id WHERE bs.batch_id = ?",
                        (fixture.batch_id,),
                    )
                }
                self.assertEqual(states[source_a_identity], "preliminary_findings_received")
                self.assertEqual(states[source_b_identity], "retryable_failure")
                self.assertNotEqual(connection.execute("SELECT status FROM inbox_batches WHERE batch_id = ?", (fixture.batch_id,)).fetchone()[0], "targeted_evidence_ready")
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                connection.close()

            recovered_result = self._complete(repeated_plan)
            self.assertEqual(recovered_result["status"], "targeted_evidence_ready")
            recovered_counts = self._counts_for_ledger(fixture.ledger, fixture.batch_id)
            final_plan = review_targeted_evidence.plan_from_request(payload)
            self.assertTrue(final_plan["idempotent"])
            self.assertEqual(recovered_counts, self._counts_for_ledger(fixture.ledger, fixture.batch_id))
            self.assertEqual(before_recovery_counts[0], recovered_counts[0])
            self.assertEqual(before_recovery_counts[2], recovered_counts[2])
            active_roots = list(fixture.batch_root.glob("sources/*/targeted-evidence/f-*/r-*"))
            self.assertEqual(len(active_roots), 2)
            self.assertTrue(all(review_targeted_evidence._verify_integrity(root, json.loads((root / "request-manifest.json").read_text(encoding="utf-8"))["render_signature"])[0] for root in active_roots))
        finally:
            fixture.tearDown()

    def test_tampered_prepared_package_artifact_blocks_rendering(self) -> None:
        artifact = next(self.fixture.batch_root.glob("sources/*/visuals/frames/*.jpg"))
        artifact.write_bytes(b"tampered-prepared-evidence")
        with self.assertRaisesRegex(RuntimeError, "failed revalidation"):
            self._plan()

    def test_long_finding_and_request_ids_remain_manifest_data_not_physical_names(self) -> None:
        fixture = preliminary_tests.ReviewInboxPreliminaryFindingsTests(methodName="runTest")
        fixture.setUp()
        try:
            document = deepcopy(fixture.document)
            finding = fixture._finding()
            finding["finding_id"] = "finding-" + "x" * 56
            finding["requests"][0]["request_id"] = "request-" + "y" * 56
            document["findings"] = [finding]
            imported = fixture._import(fixture._write(document, "long-identities.json"))
            self.assertTrue(imported["accepted"])
            plan = review_targeted_evidence.plan_from_request(
                {"ledger_path": str(fixture.ledger), "batch_path": str(fixture.batch_root), "expected_batch_id": fixture.batch_id, "preliminary_submission_sha256": imported["submission_sha256"]}
            )
            item = plan["request_plans"][0]
            self.assertLessEqual(len(Path(item["final_root"]).name), 18)
            stage_manifest = json.loads((Path(item["stage_root"]) / "request-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(stage_manifest["finding_id"], finding["finding_id"])
            self.assertEqual(stage_manifest["request_id"], finding["requests"][0]["request_id"])
        finally:
            fixture.tearDown()

    def test_multiple_findings_requests_for_one_source_and_multiple_sources_are_accounted(self) -> None:
        fixture = preliminary_tests.ReviewInboxPreliminaryFindingsTests(methodName="runTest")
        fixture.setUp()
        try:
            document = deepcopy(fixture.document)
            first = fixture._finding()
            first["requests"].append(deepcopy(first["requests"][0]))
            first["requests"][1]["request_id"] = "request-002"
            second = fixture._finding(fixture.identities[1])
            second["finding_id"] = "finding-002"
            second["requests"][0]["request_id"] = "request-003"
            document["findings"] = [first, second]
            imported = fixture._import(fixture._write(document, "multi-source.json"))
            plan = review_targeted_evidence.plan_from_request(
                {"ledger_path": str(fixture.ledger), "batch_path": str(fixture.batch_root), "expected_batch_id": fixture.batch_id, "preliminary_submission_sha256": imported["submission_sha256"]}
            )
            self.assertEqual(plan["request_count"], 3)
            self.assertEqual(len({item["source_id"] for item in plan["request_plans"]}), 2)
            frames, audio, processed = self._render(plan)
            result = review_targeted_evidence.complete_from_request(
                {"plan_path": plan["plan_path"], "plan_sha256": plan["plan_sha256"], "frame_results": frames, "audio_results": audio, "processed_request_signatures": processed}
            )
            self.assertEqual(result["status"], "targeted_evidence_ready")
            self.assertEqual(result["completed_request_count"], 3)
        finally:
            fixture.tearDown()

    def test_partial_request_failure_retries_only_unresolved_work(self) -> None:
        fixture = preliminary_tests.ReviewInboxPreliminaryFindingsTests(methodName="runTest")
        fixture.setUp()
        try:
            document = deepcopy(fixture.document)
            finding = fixture._finding()
            finding["requests"].append(deepcopy(finding["requests"][0]))
            finding["requests"][1]["request_id"] = "request-002"
            document["findings"] = [finding]
            imported = fixture._import(fixture._write(document, "partial-failure.json"))
            plan = review_targeted_evidence.plan_from_request(
                {"ledger_path": str(fixture.ledger), "batch_path": str(fixture.batch_root), "expected_batch_id": fixture.batch_id, "preliminary_submission_sha256": imported["submission_sha256"]}
            )
            first_only = {**plan, "request_plans": [plan["request_plans"][0]]}
            frames, audio, processed = self._render(first_only)
            processed.append(plan["request_plans"][1]["render_signature"])
            partial = review_targeted_evidence.complete_from_request(
                {"plan_path": plan["plan_path"], "plan_sha256": plan["plan_sha256"], "frame_results": frames, "audio_results": audio, "processed_request_signatures": processed}
            )
            self.assertEqual(partial["status"], "retryable_failure")
            self.assertEqual(partial["unresolved_request_count"], 1)
            retry = review_targeted_evidence.plan_from_request(
                {"ledger_path": str(fixture.ledger), "batch_path": str(fixture.batch_root), "expected_batch_id": fixture.batch_id, "preliminary_submission_sha256": imported["submission_sha256"]}
            )
            self.assertEqual(sum(bool(item.get("existing_complete")) for item in retry["request_plans"]), 1)
            retry_frames, retry_audio, retry_processed = self._render(retry)
            complete = review_targeted_evidence.complete_from_request(
                {"plan_path": retry["plan_path"], "plan_sha256": retry["plan_sha256"], "frame_results": retry_frames, "audio_results": retry_audio, "processed_request_signatures": retry_processed}
            )
            self.assertEqual(complete["status"], "targeted_evidence_ready")
        finally:
            fixture.tearDown()

    def test_crash_before_promotion_leaves_no_final_package_and_replans_clean_staging(self) -> None:
        plan = self._plan()
        frames, _audio, _processed = self._render(plan)
        self.assertTrue(frames)
        final_root = Path(plan["request_plans"][0]["final_root"])
        stage_root = Path(plan["request_plans"][0]["stage_root"])
        self.assertFalse(final_root.exists())
        self.assertTrue(stage_root.exists())
        retry = self._plan()
        self.assertFalse(final_root.exists())
        self.assertTrue(Path(retry["request_plans"][0]["stage_root"]).exists())

    def test_unsupported_panel_definition_is_revalidated_before_rendering(self) -> None:
        fixture = preliminary_tests.ReviewInboxPreliminaryFindingsTests(methodName="runTest")
        fixture.setUp()
        try:
            document = deepcopy(fixture.document)
            finding = fixture._finding()
            finding["requests"][0]["panels"] = {"requested": True, "panel_ids": ["driver_view"], "before_seconds": 1.0, "after_seconds": 1.0}
            document["findings"] = [finding]
            imported = fixture._import(fixture._write(document, "panel-revalidation.json"))
            with patch("media_manglers.core.review_targeted_evidence.panel_layout.resolve_panel_definitions", return_value=[]):
                plan = review_targeted_evidence.plan_from_request(
                    {"ledger_path": str(fixture.ledger), "batch_path": str(fixture.batch_root), "expected_batch_id": fixture.batch_id, "preliminary_submission_sha256": imported["submission_sha256"]}
                )
            self.assertEqual(plan["request_plans"], [])
            self.assertIn("no longer supported", plan["source_failures"][0]["error"])
        finally:
            fixture.tearDown()

    def test_no_request_submission_records_explicit_accounting_and_becomes_ready(self) -> None:
        fixture = preliminary_tests.ReviewInboxPreliminaryFindingsTests(methodName="runTest")
        fixture.setUp()
        try:
            imported = fixture._import(fixture._write(fixture.document, "no-requests.json"))
            plan = review_targeted_evidence.plan_from_request(
                {
                    "ledger_path": str(fixture.ledger),
                    "batch_path": str(fixture.batch_root),
                    "expected_batch_id": fixture.batch_id,
                    "preliminary_submission_sha256": imported["submission_sha256"],
                }
            )
            self.assertEqual(plan["request_count"], 0)
            result = review_targeted_evidence.complete_from_request(
                {"plan_path": plan["plan_path"], "plan_sha256": plan["plan_sha256"], "processed_request_signatures": []}
            )
            self.assertEqual(result["status"], "targeted_evidence_ready")
            connection = inbox_records.connect(fixture.ledger)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM inbox_attempts WHERE attempt_type = 'targeted_evidence_accounting'").fetchone()[0], 2)
            finally:
                connection.close()
        finally:
            fixture.tearDown()

    def test_missing_renderer_result_fails_safely_and_does_not_mark_batch_ready(self) -> None:
        plan = self._plan()
        request = plan["request_plans"][0]
        result = review_targeted_evidence.complete_from_request(
            {
                "plan_path": plan["plan_path"],
                "plan_sha256": plan["plan_sha256"],
                "processed_request_signatures": [request["render_signature"]],
            }
        )
        self.assertEqual(result["status"], "retryable_failure")
        self.assertTrue(result["failed_requests"])
        self.assertNotEqual(review_inbox.list_pending_batches(self.fixture.ledger)[0]["status"], "targeted_evidence_ready")

    def test_cooperative_stop_leaves_unprocessed_request_resumable(self) -> None:
        second = self.fixture._finding(self.fixture.identities[1])
        second["finding_id"] = "finding-002"
        second["requests"][0]["request_id"] = "request-002"
        # Rebuild the fixture because accepted submissions are immutable.
        fixture = preliminary_tests.ReviewInboxPreliminaryFindingsTests(methodName="runTest")
        fixture.setUp()
        try:
            document = deepcopy(fixture.document)
            first = fixture._finding()
            second = fixture._finding(fixture.identities[1])
            second["finding_id"] = "finding-002"
            second["requests"][0]["request_id"] = "request-002"
            document["findings"] = [first, second]
            imported = fixture._import(fixture._write(document, "two-requests.json"))
            plan = review_targeted_evidence.plan_from_request(
                {"ledger_path": str(fixture.ledger), "batch_path": str(fixture.batch_root), "expected_batch_id": fixture.batch_id, "preliminary_submission_sha256": imported["submission_sha256"]}
            )
            frames, audio, processed = self._render({**plan, "request_plans": [plan["request_plans"][0]]})
            result = review_targeted_evidence.complete_from_request(
                {"plan_path": plan["plan_path"], "plan_sha256": plan["plan_sha256"], "frame_results": frames, "audio_results": audio, "processed_request_signatures": processed, "cooperative_stop": True}
            )
            self.assertEqual(result["status"], "cooperative_stop")
            self.assertEqual(result["unresolved_request_count"], 1)
            retry = review_targeted_evidence.plan_from_request(
                {"ledger_path": str(fixture.ledger), "batch_path": str(fixture.batch_root), "expected_batch_id": fixture.batch_id, "preliminary_submission_sha256": imported["submission_sha256"]}
            )
            self.assertEqual(sum(not item.get("existing_complete") for item in retry["request_plans"]), 1)
        finally:
            fixture.tearDown()

    def test_cli_plan_command_returns_machine_readable_render_plan(self) -> None:
        request = self.fixture.root / "targeted-request.json"
        result = self.fixture.root / "targeted-result.json"
        write_json_file(
            request,
            CommandEnvelope(
                payload={
                    "ledger_path": str(self.fixture.ledger),
                    "batch_path": str(self.fixture.batch_root),
                    "expected_batch_id": self.fixture.batch_id,
                    "preliminary_submission_sha256": self.submission_sha,
                }
            ).to_dict(),
        )
        self.assertEqual(main(["review-media-inbox-targeted-plan", "--request-file", str(request), "--result-file", str(result)]), 0)
        output = read_json_file(result)
        self.assertTrue(output["ok"])
        self.assertEqual(output["data"]["action"], "targeted_evidence")

    def test_foreign_keys_remain_valid_after_completion(self) -> None:
        self._complete(self._plan())
        connection = inbox_records.connect(self.fixture.ledger)
        try:
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            connection.close()

    def test_panel_only_request_discards_working_full_frames_and_retains_supported_crops(self) -> None:
        fixture = preliminary_tests.ReviewInboxPreliminaryFindingsTests(methodName="runTest")
        fixture.setUp()
        try:
            document = deepcopy(fixture.document)
            finding = fixture._finding()
            request = finding["requests"][0]
            request["frames"] = {"requested": False, "before_seconds": 0.0, "after_seconds": 0.0, "max_frames": 1}
            request["panels"] = {"requested": True, "panel_ids": ["driver_view"], "before_seconds": 1.0, "after_seconds": 1.0}
            document["findings"] = [finding]
            imported = fixture._import(fixture._write(document, "panel-only.json"))
            plan = review_targeted_evidence.plan_from_request(
                {"ledger_path": str(fixture.ledger), "batch_path": str(fixture.batch_root), "expected_batch_id": fixture.batch_id, "preliminary_submission_sha256": imported["submission_sha256"]}
            )
            self.assertTrue(plan["request_plans"][0]["frame_tasks"])
            self.assertTrue(all(not task["retain_full_frame"] for task in plan["request_plans"][0]["frame_tasks"]))
            frames, audio, processed = self._render(plan)
            result = review_targeted_evidence.complete_from_request(
                {"plan_path": plan["plan_path"], "plan_sha256": plan["plan_sha256"], "frame_results": frames, "audio_results": audio, "processed_request_signatures": processed}
            )
            self.assertEqual(result["status"], "targeted_evidence_ready")
            final_root = next(fixture.batch_root.glob("sources/*/targeted-evidence/f-*/r-*"))
            manifest = json.loads((final_root / "request-manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["artifact_inventory"])
            self.assertTrue(all(item["kind"] == "panel" for item in manifest["artifact_inventory"]))
            self.assertFalse(any((final_root / "frames").glob("*.jpg")))
        finally:
            fixture.tearDown()

    def test_audio_request_uses_the_previously_confirmed_selected_ordinal(self) -> None:
        fixture = preparation_tests.ReviewInboxPreparationTests(methodName="runTest")
        fixture.setUp()
        try:
            fixture.make_sources(1)
            media = fixture.media(2, width=5760, height=1080, duration=120.0)
            fingerprint = media["audio_layout_fingerprint"]
            confirmations = {fingerprint: {"layoutFingerprint": fingerprint, "audioOrdinal": 1, "confirmationSource": "operator"}}
            prepared = review_targeted_evidence.review_preparation.prepare_from_request(
                fixture.payload(media_probe=lambda _path: media, audio_confirmations=confirmations)
            )
            batch_root = Path(prepared["batch_path"])
            document = json.loads((batch_root / "preliminary-findings.template.json").read_text(encoding="utf-8"))
            identity = document["reviewed_source_identities"][0]
            document["findings"] = [
                {
                    "finding_id": "audio-finding",
                    "source_identity": identity,
                    "request_type": "targeted_evidence",
                    "requests": [
                        {
                            "request_id": "audio-request",
                            "timestamp": {"kind": "point", "at_seconds": 60.0},
                            "frames": {"requested": False, "before_seconds": 0.0, "after_seconds": 0.0, "max_frames": 1},
                            "panels": {"requested": False, "panel_ids": [], "before_seconds": 0.0, "after_seconds": 0.0},
                            "audio": {"requested": True, "before_seconds": 5.0, "after_seconds": 7.0},
                        }
                    ],
                    "reviewer_notes": "Listen to the confirmed narration stream around this point.",
                    "confidence": {"level": "medium", "rationale": "The transcript needs bounded audio confirmation."},
                }
            ]
            submission = fixture.root / "audio-findings.json"
            submission.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
            imported = review_findings.import_from_request(
                {"ledger_path": str(fixture.ledger), "batch_path": str(batch_root), "expected_batch_id": prepared["batch_id"], "findings_path": str(submission)}
            )
            self.assertTrue(imported["accepted"])
            plan = review_targeted_evidence.plan_from_request(
                {"ledger_path": str(fixture.ledger), "batch_path": str(batch_root), "expected_batch_id": prepared["batch_id"], "preliminary_submission_sha256": imported["submission_sha256"]}
            )
            task = plan["request_plans"][0]["audio_tasks"][0]
            self.assertEqual(task["audio_stream_index"], 1)
            self.assertEqual(task["duration_seconds"], 12.0)
            frames, audio, processed = self._render(plan)
            result = review_targeted_evidence.complete_from_request(
                {"plan_path": plan["plan_path"], "plan_sha256": plan["plan_sha256"], "frame_results": frames, "audio_results": audio, "processed_request_signatures": processed}
            )
            self.assertEqual(result["status"], "targeted_evidence_ready")
            final_root = next(batch_root.glob("sources/*/targeted-evidence/f-*/r-*"))
            manifest = json.loads((final_root / "request-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["selected_audio_ordinal"], 1)
            self.assertEqual(manifest["artifact_inventory"][0]["selected_audio_ordinal"], 1)
        finally:
            fixture.tearDown()

    def test_combined_frame_panel_audio_request_produces_only_requested_artifact_kinds(self) -> None:
        fixture, prepared, batch_root, document, identity = self._prepared_audio_fixture()
        try:
            document["findings"] = [
                {
                    "finding_id": "combined-finding",
                    "source_identity": identity,
                    "request_type": "targeted_evidence",
                    "requests": [
                        {
                            "request_id": "combined-request",
                            "timestamp": {"kind": "range", "start_seconds": 55.0, "end_seconds": 65.0},
                            "frames": {"requested": True, "before_seconds": 2.0, "after_seconds": 2.0, "max_frames": 4},
                            "panels": {"requested": True, "panel_ids": ["driver_view", "overview_cam"], "before_seconds": 1.0, "after_seconds": 1.0},
                            "audio": {"requested": True, "before_seconds": 5.0, "after_seconds": 5.0},
                        }
                    ],
                    "reviewer_notes": "Compare the visible and selected narration evidence in this bounded interval.",
                    "confidence": {"level": "medium", "rationale": "All three requested evidence types are needed."},
                }
            ]
            submission = fixture.root / "combined-findings.json"
            submission.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
            imported = review_findings.import_from_request(
                {"ledger_path": str(fixture.ledger), "batch_path": str(batch_root), "expected_batch_id": prepared["batch_id"], "findings_path": str(submission)}
            )
            plan = review_targeted_evidence.plan_from_request(
                {"ledger_path": str(fixture.ledger), "batch_path": str(batch_root), "expected_batch_id": prepared["batch_id"], "preliminary_submission_sha256": imported["submission_sha256"]}
            )
            self.assertEqual(len(plan["request_plans"][0]["frame_tasks"]), 4)
            self.assertTrue(all(len(task["panels"]) == 2 for task in plan["request_plans"][0]["frame_tasks"]))
            self.assertEqual(len(plan["request_plans"][0]["audio_tasks"]), 1)
            frames, audio, processed = self._render(plan)
            result = review_targeted_evidence.complete_from_request(
                {"plan_path": plan["plan_path"], "plan_sha256": plan["plan_sha256"], "frame_results": frames, "audio_results": audio, "processed_request_signatures": processed}
            )
            self.assertEqual(result["status"], "targeted_evidence_ready")
            final_root = next(batch_root.glob("sources/*/targeted-evidence/f-*/r-*"))
            manifest = json.loads((final_root / "request-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual({item["kind"] for item in manifest["artifact_inventory"]}, {"frame", "panel", "audio"})
        finally:
            fixture.tearDown()

    def test_missing_or_invalid_selected_audio_is_rejected_during_task_conversion(self) -> None:
        fixture, prepared, batch_root, document, identity = self._prepared_audio_fixture()
        try:
            document["findings"] = [
                {
                    "finding_id": "audio-invalid",
                    "source_identity": identity,
                    "request_type": "targeted_evidence",
                    "requests": [
                        {
                            "request_id": "audio-invalid-request",
                            "timestamp": {"kind": "point", "at_seconds": 60.0},
                            "frames": {"requested": False, "before_seconds": 0.0, "after_seconds": 0.0, "max_frames": 1},
                            "panels": {"requested": False, "panel_ids": [], "before_seconds": 0.0, "after_seconds": 0.0},
                            "audio": {"requested": True, "before_seconds": 2.0, "after_seconds": 2.0},
                        }
                    ],
                    "reviewer_notes": "Prove an invalid selected ordinal is not silently replaced.",
                    "confidence": {"level": "medium", "rationale": "Selected-stream safety is required."},
                }
            ]
            submission = fixture.root / "invalid-audio-findings.json"
            submission.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
            imported = review_findings.import_from_request(
                {"ledger_path": str(fixture.ledger), "batch_path": str(batch_root), "expected_batch_id": prepared["batch_id"], "findings_path": str(submission)}
            )
            original = review_targeted_evidence._source_manifest

            def invalid_manifest(context: dict, source_identity: str) -> dict:
                manifest = deepcopy(original(context, source_identity))
                manifest["audio_selection"]["selected_ordinal"] = 99
                return manifest

            with patch("media_manglers.core.review_targeted_evidence._source_manifest", side_effect=invalid_manifest):
                plan = review_targeted_evidence.plan_from_request(
                    {"ledger_path": str(fixture.ledger), "batch_path": str(batch_root), "expected_batch_id": prepared["batch_id"], "preliminary_submission_sha256": imported["submission_sha256"]}
                )
            self.assertEqual(plan["request_plans"], [])
            self.assertIn("selected-audio ordinal", plan["source_failures"][0]["error"])
        finally:
            fixture.tearDown()


if __name__ == "__main__":
    unittest.main()
