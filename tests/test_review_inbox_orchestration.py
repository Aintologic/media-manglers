from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from media_manglers.core import inbox_records, review_orchestration
import pytest
from tests import inbox_library  # noqa: E402

# 224 (Wave B2b): the Inbox's records are in this test's library, moved in (nothing to move).
pytestmark = pytest.mark.inbox_moved


def _source(index: int) -> dict[str, object]:
    return {
        "source_id": index,
        "identity": f"provisional:{index:04d}",
        "path": f"C:\\synthetic\\source-{index:04d}.mp4",
        "classification": "pending",
        "pending_batch_excluded": False,
        "size_bytes": index * 100,
        "modified_utc": f"2026-01-01T00:{index // 60:02d}:{index % 60:02d}+00:00",
    }


def _inventory(count: int) -> dict[str, object]:
    return {
        "settings": {},
        "eligible_sources": [_source(index) for index in range(1, count + 1)],
    }


def _queue(
    root: Path,
    *,
    batches: list[dict[str, object]] | None = None,
    attention: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "contract_version": 1,
        "document_type": "review_media_inbox_queue",
        "queue_root": str(root),
        "queue_prompt_path": str(root / "CODEX_REVIEW_QUEUE_PROMPT.md"),
        "queue_index_path": str(root / "queue-index.json"),
        "counts": {
            "ready_for_codex_review": 0,
            "waiting_on_codex": 0,
            "additional_local_evidence": 0,
            "manual_review": 0,
            "done": 0,
        },
        "batches": list(batches or []),
        "attention": list(attention or []),
        "operator_status": "Done",
    }


class ReviewInboxOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.ledger = self.root / "review-ledger.sqlite"
        self.payload: dict[str, object] = {
            "ledger_path": str(self.ledger),
            "source_folders": [str(self.root / "sources")],
            "evidence_root": str(self.root),
            "scratch_root": str(self.root / "scratch"),
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_atomic_run_journal_uses_a_short_sibling_name(self) -> None:
        target = self.root / ".orchestration" / "active-run.json"
        with (
            patch.object(review_orchestration.uuid, "uuid4") as uuid4,
            patch.object(review_orchestration.os, "replace") as replace,
        ):
            uuid4.return_value.hex = "b" * 32
            review_orchestration._atomic_json(target, {"run": {}})
        temporary, destination = map(Path, replace.call_args.args)
        self.assertEqual(temporary.name, f".mm-{'b' * 16}.tmp")
        self.assertEqual(destination, target)
        # 224 (Wave B1): the journal is written by the one safe writer, which never leaves its temporary file.
        self.assertFalse(temporary.exists())

    def _prepare_result(self, payload: dict[str, object]) -> dict[str, object]:
        selected = list(payload["selected_sources"])
        first = int(selected[0]["source_id"])
        return {
            "contract_version": 1,
            "status": "awaiting_external_review",
            "batch_id": f"batch-{first:04d}",
            "batch_path": str(self.root / "batches" / f"batch-{first:04d}"),
        }

    def _filesystem_inventory(
        self,
        specs: list[dict[str, object]],
        *,
        configured_root: Path | None = None,
        recurse: bool = False,
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        source_root = configured_root or (self.root / "sources")
        source_root.mkdir(parents=True, exist_ok=True)
        sources: list[dict[str, object]] = []
        counts: dict[str, int] = {}
        eligible_states = {
            "discovered",
            "pending",
            "retryable_failure",
            "source_changed",
            "legacy_migration_pending",
        }
        for index, spec in enumerate(specs, start=1):
            path = Path(spec.get("path") or (source_root / f"source-{index:04d}.mp4"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((f"restricted-source-{index}" * index).encode("utf-8"))
            stat = path.stat()
            classification = str(spec.get("classification") or "pending")
            item: dict[str, object] = {
                "source_id": index,
                "identity": f"provisional:restricted:{index:04d}",
                "path": str(path),
                "classification": classification,
                "pending_batch_excluded": bool(
                    spec.get("pending_batch_excluded", False)
                ),
                "size_bytes": stat.st_size,
                "modified_ns": stat.st_mtime_ns,
                "modified_utc": f"2026-01-01T00:00:{index:02d}+00:00",
                "sampled_sha256": f"{index:064x}",
            }
            sources.append(item)
            counts[classification] = counts.get(classification, 0) + 1
        eligible = [
            dict(item)
            for item in sources
            if str(item["classification"]) in eligible_states
            and not bool(item["pending_batch_excluded"])
        ]
        return (
            {
                "settings": {
                    "source_folders": [str(source_root)],
                    "recurse": recurse,
                    "ledger_path": str(self.ledger),
                },
                "sources": sources,
                "eligible_sources": eligible,
                "inventory_count": len(sources),
                "classification_counts": counts,
            },
            sources,
        )

    def _drive_automatic(
        self,
        first: dict[str, object],
        payload: dict[str, object],
    ) -> dict[str, object]:
        result = first
        safety = 0
        while result["continue_automatically"]:
            safety += 1
            self.assertLess(safety, 100)
            result = review_orchestration.process_from_request(
                {**payload, "continuation": result["continuation"]}
            )
        return result

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_next_three_uses_one_hidden_batch_and_archives_completed_run(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
    ) -> None:
        refresh_queue.return_value = _queue(self.root)
        scan_inventory.return_value = _inventory(10)
        prepare_selected.side_effect = self._prepare_result

        result = review_orchestration.process_from_request(self.payload)

        self.assertEqual(result["operator_status"], "Done")
        self.assertEqual(result["workload"]["mode"], "next_3")
        self.assertEqual(result["run_state"]["selected_count"], 3)
        self.assertEqual(result["run_state"]["completed_count"], 3)
        self.assertEqual(
            [item["source_id"] for item in prepare_selected.call_args.args[0]["selected_sources"]],
            [1, 2, 3],
        )
        prepare_payload = prepare_selected.call_args.args[0]
        self.assertEqual(prepare_payload["selected_source_ids"], [1, 2, 3])
        self.assertRegex(
            prepare_payload["preallocated_batch_id"],
            r"^batch-process-[0-9a-f]{16}$",
        )
        self.assertEqual(
            prepare_payload["scan_result"]["settings"]["ledger_path"],
            str(self.ledger),
        )
        self.assertEqual(
            prepare_payload["scan_result"]["settings"]["max_duration_minutes"],
            240.0,
        )
        self.assertEqual(prepare_payload["prior_elapsed_seconds"], 0.0)
        self.assertFalse((self.root / ".orchestration" / "active-run.json").exists())
        self.assertEqual(
            len(list((self.root / ".orchestration" / "completed-runs").glob("*.json"))),
            1,
        )

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_up_to_ten_uses_hidden_chunks_three_three_three_one(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
    ) -> None:
        refresh_queue.return_value = _queue(self.root)
        scan_inventory.return_value = _inventory(14)
        prepare_selected.side_effect = self._prepare_result
        payload = {
            **self.payload,
            "workload_mode": "up_to_n",
            "new_source_limit": 10,
        }

        first = review_orchestration.process_from_request(payload)
        result = self._drive_automatic(first, payload)

        self.assertEqual(result["run_state"]["selected_count"], 10)
        chunks = [
            [item["source_id"] for item in call.args[0]["selected_sources"]]
            for call in prepare_selected.call_args_list
        ]
        self.assertEqual(chunks, [[1, 2, 3], [4, 5, 6], [7, 8, 9], [10]])
        self.assertEqual(
            [
                call.args[0]["selected_source_ids"]
                for call in prepare_selected.call_args_list
            ],
            chunks,
        )
        self.assertEqual(
            len(
                {
                    call.args[0]["preallocated_batch_id"]
                    for call in prepare_selected.call_args_list
                }
            ),
            4,
        )
        self.assertEqual(scan_inventory.call_count, 1)

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_all_pending_205_requires_confirmation_then_exhausts_fixed_snapshot(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
    ) -> None:
        refresh_queue.return_value = _queue(self.root)
        scan_inventory.return_value = _inventory(205)
        prepare_selected.side_effect = self._prepare_result
        payload = {
            **self.payload,
            "workload_mode": "all_pending",
            "recent_preparation_durations_seconds": [10, 20, 30],
            "space_probe": lambda _path: 10**15,
        }

        confirmation_result = review_orchestration.process_from_request(payload)

        self.assertFalse(confirmation_result["continue_automatically"])
        confirmation = confirmation_result["all_pending_confirmation"]
        self.assertEqual(confirmation["eligible_source_count"], 205)
        self.assertEqual(confirmation["total_source_bytes"], sum(i * 100 for i in range(1, 206)))
        self.assertEqual(prepare_selected.call_count, 0)

        confirmed = review_orchestration.process_from_request(
            {
                **payload,
                "continuation": confirmation_result["continuation"],
                "decision": {
                    "type": "all_pending",
                    "token": confirmation["token"],
                    "confirmed": True,
                },
            }
        )
        result = self._drive_automatic(confirmed, payload)

        self.assertEqual(result["run_state"]["selected_count"], 205)
        self.assertEqual(result["run_state"]["completed_count"], 205)
        self.assertEqual(prepare_selected.call_count, 69)
        self.assertEqual(
            [len(call.args[0]["selected_sources"]) for call in prepare_selected.call_args_list],
            ([3] * 68) + [1],
        )

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_snapshot_does_not_admit_sources_discovered_after_run_start(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
    ) -> None:
        refresh_queue.return_value = _queue(self.root)
        scan_inventory.return_value = _inventory(5)
        prepare_selected.side_effect = self._prepare_result
        payload = {
            **self.payload,
            "workload_mode": "up_to_n",
            "new_source_limit": 5,
        }

        first = review_orchestration.process_from_request(payload)
        scan_inventory.return_value = _inventory(20)
        self._drive_automatic(first, payload)

        flattened = [
            int(item["source_id"])
            for call in prepare_selected.call_args_list
            for item in call.args[0]["selected_sources"]
        ]
        self.assertEqual(flattened, [1, 2, 3, 4, 5])
        self.assertEqual(scan_inventory.call_count, 1)

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_preliminary_sha")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_targeted_evidence_is_returned_to_powershell_before_new_sources(
        self,
        refresh_queue,
        preliminary_sha,
        scan_inventory,
        prepare_selected,
    ) -> None:
        preliminary_sha.return_value = "a" * 64
        refresh_queue.return_value = _queue(
            self.root,
            batches=[
                {
                    "batch_id": "batch-existing",
                    "batch_path": str(self.root / "batches" / "batch-existing"),
                    "status": "preliminary_findings_received",
                }
            ],
        )

        result = review_orchestration.process_from_request(self.payload)

        self.assertTrue(result["continue_automatically"])
        self.assertEqual(
            result["next_action"],
            {
                "type": "render_targeted",
                "batch_id": "batch-existing",
                "batch_path": str(self.root / "batches" / "batch-existing"),
                "preliminary_submission_sha256": "a" * 64,
            },
        )
        scan_inventory.assert_not_called()
        prepare_selected.assert_not_called()

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_preliminary_sha")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_existing_targeted_work_then_initialises_selected_new_source_budget(
        self,
        refresh_queue,
        preliminary_sha,
        scan_inventory,
        prepare_selected,
    ) -> None:
        batch_root = self.root / "batches" / "batch-existing"
        preliminary_sha.return_value = "a" * 64
        waiting_queue = _queue(
            self.root,
            batches=[
                {
                    "batch_id": "batch-existing",
                    "batch_path": str(batch_root),
                    "status": "targeted_evidence_ready",
                },
                {
                    "batch_id": "batch-new",
                    "batch_path": str(self.root / "batches" / "batch-new"),
                    "status": "awaiting_external_review",
                },
            ],
        )
        waiting_queue["operator_status"] = "Waiting on Codex"
        waiting_queue["counts"]["waiting_on_codex"] = 2
        preliminary_queue = _queue(
            self.root,
            batches=[
                {
                    "batch_id": "batch-existing",
                    "batch_path": str(batch_root),
                    "status": "preliminary_findings_received",
                }
            ],
        )
        targeted_queue = _queue(
            self.root,
            batches=[
                {
                    "batch_id": "batch-existing",
                    "batch_path": str(batch_root),
                    "status": "targeted_evidence_ready",
                }
            ],
        )
        refresh_queue.side_effect = [
            preliminary_queue,
            preliminary_queue,
            targeted_queue,
            targeted_queue,
            waiting_queue,
        ]
        scan_inventory.return_value = _inventory(2)
        prepare_selected.return_value = {
            "status": "awaiting_external_review",
            "batch_id": "batch-new",
            "batch_path": str(self.root / "batches" / "batch-new"),
            "prepared_sources": [{"source_id": 1}, {"source_id": 2}],
        }
        payload = {
            **self.payload,
            "workload_mode": "up_to_n",
            "new_source_limit": 2,
        }

        targeted = review_orchestration.process_from_request(payload)
        completed = review_orchestration.process_from_request(
            {**payload, "continuation": targeted["continuation"]}
        )

        self.assertEqual(targeted["next_action"]["type"], "render_targeted")
        self.assertEqual(completed["run_state"]["selected_count"], 2)
        self.assertEqual(completed["run_state"]["completed_count"], 2)
        self.assertEqual(completed["operator_status"], "Waiting on Codex")
        scan_inventory.assert_called_once()
        prepare_selected.assert_called_once()

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_invalid_external_return_blocks_new_source_allocation(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
    ) -> None:
        refresh_queue.return_value = _queue(
            self.root,
            attention=[
                {
                    "code": "invalid_external_return",
                    "message": "Replace the invalid stable return file.",
                }
            ],
        )

        result = review_orchestration.process_from_request(self.payload)

        self.assertEqual(result["operator_status"], "Needs attention")
        self.assertEqual(result["attention"]["code"], "invalid_external_return")
        scan_inventory.assert_not_called()
        prepare_selected.assert_not_called()

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_retained_manual_review_does_not_block_next_three(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
    ) -> None:
        retained = {
            "batch_id": "batch-manual",
            "batch_path": str(self.root / "batches" / "batch-manual"),
            "batch_relative_path": "batches/batch-manual",
            "status": "needs_manual_review",
            "operator_state": "manual_review",
            "source_count": 1,
            "source_states": ["needs_manual_review"],
            "package_contained": True,
        }
        queue = _queue(self.root, batches=[])
        queue["internal_batches"] = [retained]
        queue["counts"]["manual_review"] = 1
        queue["operator_status"] = "Manual review available"
        queue["manual_review"] = [
            {
                "batch_id": "batch-manual",
                "status": "needs_manual_review",
                "manual_review_count": 1,
                "batch_relative_path": "batches/batch-manual",
                "package_contained": True,
            }
        ]
        refresh_queue.return_value = queue
        scan_inventory.return_value = _inventory(5)
        prepare_selected.return_value = {
            "status": "awaiting_external_review",
            "batch_id": "batch-new",
            "batch_path": str(self.root / "batches" / "batch-new"),
            "prepared_sources": [
                {"source_id": 1},
                {"source_id": 2},
                {"source_id": 3},
            ],
        }

        result = review_orchestration.process_from_request(self.payload)

        scan_inventory.assert_called_once()
        prepare_selected.assert_called_once()
        self.assertEqual(
            [
                item["source_id"]
                for item in prepare_selected.call_args.args[0]["selected_sources"]
            ],
            [1, 2, 3],
        )
        self.assertEqual(
            prepare_selected.call_args.args[0]["scan_result"]["pending_batches"],
            [],
        )
        self.assertEqual(result["run_state"]["selected_count"], 3)
        self.assertEqual(result["operator_status"], "Manual review available")
        self.assertEqual(result["queue_counts"]["manual_review"], 1)
        self.assertEqual(result["manual_review"], queue["manual_review"])
        self.assertIsNone(result["attention"])

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_stop_after_current_pauses_and_next_process_resumes_exact_snapshot(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
    ) -> None:
        refresh_queue.return_value = _queue(self.root)
        scan_inventory.return_value = _inventory(5)
        prepare_selected.side_effect = self._prepare_result
        stop = {"requested": False}

        def prepare_then_stop(payload: dict[str, object]) -> dict[str, object]:
            result = self._prepare_result(payload)
            stop["requested"] = True
            return result

        prepare_selected.side_effect = prepare_then_stop
        payload = {
            **self.payload,
            "workload_mode": "up_to_n",
            "new_source_limit": 5,
            "stop_requested": lambda: stop["requested"],
        }

        paused = review_orchestration.process_from_request(payload)

        self.assertEqual(paused["run_state"]["status"], "paused_after_current")
        self.assertEqual(paused["run_state"]["completed_count"], 3)
        self.assertEqual(paused["run_state"]["remaining_count"], 2)
        stop["requested"] = False
        prepare_selected.side_effect = self._prepare_result
        resumed = review_orchestration.process_from_request(
            {**payload, "continuation": paused["continuation"]}
        )

        self.assertEqual(resumed["run_state"]["status"], "complete")
        chunks = [
            [item["source_id"] for item in call.args[0]["selected_sources"]]
            for call in prepare_selected.call_args_list
        ]
        self.assertEqual(chunks, [[1, 2, 3], [4, 5]])

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_external_stop_marker_pauses_after_current_preparation_action(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
    ) -> None:
        marker = self.root / "stop-after-current.requested"
        refresh_queue.return_value = _queue(self.root)
        scan_inventory.return_value = _inventory(5)

        def prepare(payload: dict[str, object]) -> dict[str, object]:
            self.assertFalse(payload["stop_requested"]())
            marker.write_text("stop", encoding="utf-8")
            self.assertTrue(payload["stop_requested"]())
            return self._prepare_result(payload)

        prepare_selected.side_effect = prepare
        result = review_orchestration.process_from_request(
            {
                **self.payload,
                "workload_mode": "up_to_n",
                "new_source_limit": 5,
                "stop_after_current_file_path": str(marker),
            }
        )

        self.assertEqual(result["run_state"]["status"], "paused_after_current")
        self.assertEqual(result["run_state"]["completed_count"], 3)
        self.assertEqual(result["run_state"]["remaining_count"], 2)
        self.assertFalse(result["continue_automatically"])

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_preliminary_sha")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_stop_marker_prevents_scheduling_the_next_targeted_render(
        self,
        refresh_queue,
        preliminary_sha,
        scan_inventory,
        prepare_selected,
    ) -> None:
        marker = self.root / "stop-after-current.requested"
        targeted_queue = _queue(
            self.root,
            batches=[
                {
                    "batch_id": "batch-targeted",
                    "batch_path": str(self.root / "batches" / "batch-targeted"),
                    "status": "preliminary_findings_received",
                }
            ],
        )
        refresh_queue.return_value = targeted_queue
        preliminary_sha.return_value = "d" * 64
        payload = {
            **self.payload,
            "stop_after_current_file_path": str(marker),
        }

        first = review_orchestration.process_from_request(payload)
        self.assertEqual(first["next_action"]["type"], "render_targeted")
        self.assertTrue(first["run_state"]["active"])
        marker.write_text("stop", encoding="utf-8")

        paused = review_orchestration.process_from_request(
            {**payload, "continuation": first["continuation"]}
        )

        self.assertEqual(paused["run_state"]["status"], "paused_after_current")
        self.assertFalse(paused["continue_automatically"])
        self.assertIsNone(paused["next_action"])
        scan_inventory.assert_not_called()
        prepare_selected.assert_not_called()

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_soft_limit_is_cumulative_across_chunks_and_resumable_on_next_process(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
    ) -> None:
        refresh_queue.return_value = _queue(self.root)
        scan_inventory.return_value = _inventory(4)
        prepare_selected.side_effect = self._prepare_result
        clock_values = iter([0.0, 14_400.0])
        payload = {
            **self.payload,
            "workload_mode": "up_to_n",
            "new_source_limit": 4,
            "clock": lambda: next(clock_values),
        }

        paused = review_orchestration.process_from_request(payload)

        self.assertEqual(paused["run_state"]["status"], "paused_soft_limit")
        self.assertEqual(paused["run_state"]["remaining_count"], 1)
        resume_clock = iter([20_000.0, 20_001.0])
        resumed = review_orchestration.process_from_request(
            {
                **payload,
                "clock": lambda: next(resume_clock),
                "continuation": paused["continuation"],
            }
        )
        self.assertEqual(resumed["run_state"]["status"], "complete")
        self.assertEqual(resumed["run_state"]["total_elapsed_seconds"], 14_401.0)

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_audio_pause_resumes_the_same_hidden_batch_after_confirmed_decision(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
    ) -> None:
        batch_path = self.root / "batches" / "batch-audio"
        no_work = _queue(self.root)
        audio_queue = _queue(
            self.root,
            batches=[
                {
                    "batch_id": "batch-audio",
                    "batch_path": str(batch_path),
                    "status": "needs_audio_confirmation",
                }
            ],
        )
        refresh_queue.side_effect = [
            no_work,
            no_work,
            audio_queue,
            audio_queue,
            audio_queue,
            no_work,
        ]
        scan_inventory.return_value = _inventory(3)
        prepare_selected.side_effect = [
            {
                "status": "needs_audio_confirmation",
                "batch_id": "batch-audio",
                "batch_path": str(batch_path),
                "blocked_sources": [{"source_id": 1}],
            },
            {
                "status": "awaiting_external_review",
                "batch_id": "batch-audio",
                "batch_path": str(batch_path),
            },
        ]

        paused = review_orchestration.process_from_request(self.payload)

        self.assertEqual(paused["operator_status"], "Needs audio choice")
        choice = paused["audio_choice"]
        completed = review_orchestration.process_from_request(
            {
                **self.payload,
                "continuation": paused["continuation"],
                "decision": {
                    "type": "audio",
                    "token": choice["token"],
                    "confirmed": True,
                },
            }
        )

        self.assertEqual(completed["run_state"]["status"], "complete")
        self.assertEqual(prepare_selected.call_count, 2)
        self.assertEqual(
            prepare_selected.call_args_list[1].args[0]["resume_batch_id"],
            "batch-audio",
        )
        self.assertEqual(
            [
                item["source_id"]
                for item in prepare_selected.call_args_list[1].args[0]["selected_sources"]
            ],
            [1, 2, 3],
        )
        self.assertEqual(
            prepare_selected.call_args_list[1].args[0]["selected_source_ids"],
            [1, 2, 3],
        )
        self.assertNotIn(
            "preallocated_batch_id",
            prepare_selected.call_args_list[1].args[0],
        )

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_fresh_existing_preparing_batch_resumes_before_new_source_scan(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
    ) -> None:
        batch_root = self.root / "batches" / "batch-interrupted"
        interrupted = _queue(
            self.root,
            batches=[
                {
                    "batch_id": "batch-interrupted",
                    "batch_path": str(batch_root),
                    "source_count": 2,
                    "status": "preparing",
                }
            ],
        )
        refresh_queue.side_effect = [
            interrupted,
            interrupted,
            _queue(self.root),
        ]
        prepare_selected.return_value = {
            "status": "awaiting_external_review",
            "batch_id": "batch-interrupted",
            "batch_path": str(batch_root),
        }

        result = review_orchestration.process_from_request(self.payload)

        self.assertEqual(result["run_state"]["status"], "complete")
        scan_inventory.assert_called_once()
        resume_payload = prepare_selected.call_args.args[0]
        self.assertEqual(resume_payload["resume_batch_id"], "batch-interrupted")
        self.assertEqual(resume_payload["selected_source_ids"], [])
        self.assertNotIn("preallocated_batch_id", resume_payload)
        self.assertEqual(
            resume_payload["scan_result"]["pending_batches"][0]["batch_id"],
            "batch-interrupted",
        )

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_local_work_pending_does_not_consume_cursor_or_new_source_quota(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
    ) -> None:
        no_work = _queue(self.root)
        existing_work = _queue(
            self.root,
            batches=[
                {
                    "batch_id": "batch-existing",
                    "batch_path": str(self.root / "batches" / "batch-existing"),
                    "status": "preparing",
                }
            ],
        )
        refresh_queue.side_effect = [
            no_work,
            no_work,
            existing_work,
        ]
        scan_inventory.return_value = _inventory(4)
        prepare_selected.return_value = {
            "status": "local_work_pending",
            "pending_batches": [
                {
                    "batch_id": "batch-existing",
                    "status": "preparing",
                }
            ],
            "message": "Recover existing work first.",
        }

        result = review_orchestration.process_from_request(
            {
                **self.payload,
                "workload_mode": "up_to_n",
                "new_source_limit": 4,
            }
        )

        self.assertTrue(result["continue_automatically"])
        self.assertEqual(result["run_state"]["completed_count"], 0)
        self.assertEqual(result["run_state"]["remaining_count"], 4)
        envelope = json.loads(
            (self.root / ".orchestration" / "active-run.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(envelope["run"]["cursor"], 0)
        self.assertEqual(
            envelope["run"]["pending_resume"]["batch_id"],
            "batch-existing",
        )
        self.assertEqual(
            [item["source_id"] for item in envelope["run"]["inflight_chunk"]],
            [1, 2, 3],
        )

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_prepare_failure_consumes_assigned_quota_but_blocks_more_allocation(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
    ) -> None:
        batch_root = self.root / "batches" / "batch-failed"
        no_work = _queue(self.root)
        failed_work = _queue(
            self.root,
            batches=[
                {
                    "batch_id": "batch-failed",
                    "batch_path": str(batch_root),
                    "status": "preparing",
                }
            ],
        )
        refresh_queue.side_effect = [
            no_work,
            no_work,
            failed_work,
        ]
        scan_inventory.return_value = _inventory(4)
        prepare_selected.return_value = {
            "status": "preparing",
            "batch_id": "batch-failed",
            "batch_path": str(batch_root),
            "failed_sources": [
                {
                    "source_id": 1,
                    "state": "source_changed",
                    "message": "The source changed during preparation.",
                }
            ],
        }

        result = review_orchestration.process_from_request(
            {
                **self.payload,
                "workload_mode": "up_to_n",
                "new_source_limit": 4,
            }
        )

        self.assertEqual(result["operator_status"], "Needs attention")
        self.assertEqual(result["attention"]["code"], "source_changed")
        self.assertEqual(result["run_state"]["completed_count"], 0)
        self.assertEqual(result["run_state"]["remaining_count"], 4)
        self.assertFalse(result["continue_automatically"])
        prepare_selected.assert_called_once()

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_corrected_retryable_batch_resumes_before_any_new_allocation(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
    ) -> None:
        batch_root = self.root / "batches" / "batch-retry"
        retry_attention = {
            "batch_id": "batch-retry",
            "code": "batch_needs_attention",
            "message": "The batch contains retryable work.",
            "states": ["retryable_failure"],
        }
        no_work = _queue(self.root)
        preparing = _queue(
            self.root,
            batches=[
                {
                    "batch_id": "batch-retry",
                    "batch_path": str(batch_root),
                    "status": "preparing",
                }
            ],
        )
        retrying = _queue(
            self.root,
            batches=[
                {
                    "batch_id": "batch-retry",
                    "batch_path": str(batch_root),
                    "status": "preparing",
                }
            ],
            attention=[retry_attention],
        )
        awaiting = _queue(
            self.root,
            batches=[
                {
                    "batch_id": "batch-retry",
                    "batch_path": str(batch_root),
                    "status": "awaiting_external_review",
                }
            ],
        )
        refresh_queue.side_effect = [
            no_work,
            no_work,
            retrying,
            preparing,
            preparing,
            awaiting,
        ]
        scan_inventory.return_value = _inventory(4)
        prepare_selected.side_effect = [
            {
                "status": "preparing",
                "batch_id": "batch-retry",
                "batch_path": str(batch_root),
                "failed_sources": [
                    {
                        "source_id": 1,
                        "state": "retryable_failure",
                        "message": "Storage was temporarily unavailable.",
                    }
                ],
            },
            {
                "status": "awaiting_external_review",
                "batch_id": "batch-retry",
                "batch_path": str(batch_root),
                "prepared_sources": [
                    {"source_id": 1},
                    {"source_id": 2},
                    {"source_id": 3},
                ],
            },
        ]
        payload = {
            **self.payload,
            "workload_mode": "up_to_n",
            "new_source_limit": 4,
        }

        failed = review_orchestration.process_from_request(payload)
        resumed = review_orchestration.process_from_request(
            {**payload, "continuation": failed["continuation"]}
        )

        self.assertEqual(failed["operator_status"], "Needs attention")
        self.assertTrue(resumed["continue_automatically"])
        self.assertEqual(resumed["run_state"]["completed_count"], 3)
        self.assertEqual(resumed["run_state"]["remaining_count"], 1)
        self.assertEqual(prepare_selected.call_count, 2)
        retry_payload = prepare_selected.call_args_list[1].args[0]
        self.assertEqual(retry_payload["resume_batch_id"], "batch-retry")
        scan_inventory.assert_called_once()

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_crash_after_batch_creation_resumes_preallocated_batch_without_quota_drift(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
    ) -> None:
        captured: dict[str, str] = {}
        refresh_calls = {"count": 0}

        def refresh(_payload: dict[str, object], *, import_external: bool):
            refresh_calls["count"] += 1
            if refresh_calls["count"] <= 2:
                return _queue(self.root)
            if refresh_calls["count"] in {3, 4}:
                batch_id = captured["batch_id"]
                return _queue(
                    self.root,
                    batches=[
                        {
                            "batch_id": batch_id,
                            "batch_path": str(self.root / "batches" / batch_id),
                            "source_count": 3,
                            "status": "preparing",
                        }
                    ],
                )
            return _queue(self.root)

        refresh_queue.side_effect = refresh
        scan_inventory.return_value = _inventory(4)

        def prepare(payload: dict[str, object]) -> dict[str, object]:
            if "batch_id" not in captured:
                captured["batch_id"] = str(payload["preallocated_batch_id"])
                raise KeyboardInterrupt("simulated process death")
            self.assertEqual(payload["resume_batch_id"], captured["batch_id"])
            self.assertEqual(payload["selected_source_ids"], [1, 2, 3])
            return {
                "status": "awaiting_external_review",
                "batch_id": captured["batch_id"],
                "batch_path": str(self.root / "batches" / captured["batch_id"]),
            }

        prepare_selected.side_effect = prepare
        payload = {
            **self.payload,
            "workload_mode": "up_to_n",
            "new_source_limit": 4,
        }
        with self.assertRaisesRegex(KeyboardInterrupt, "process death"):
            review_orchestration.process_from_request(payload)

        before = json.loads(
            (self.root / ".orchestration" / "active-run.json").read_text(
                encoding="utf-8"
            )
        )["run"]
        self.assertEqual(before["cursor"], 0)
        self.assertEqual(before["inflight_batch_id"], captured["batch_id"])

        resumed = review_orchestration.process_from_request(payload)

        self.assertTrue(resumed["continue_automatically"])
        self.assertEqual(resumed["run_state"]["completed_count"], 3)
        self.assertEqual(resumed["run_state"]["remaining_count"], 1)
        self.assertEqual(prepare_selected.call_count, 2)
        self.assertEqual(scan_inventory.call_count, 1)

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_crash_after_awaiting_batch_commit_reconciles_without_duplicate_insert(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
    ) -> None:
        captured: dict[str, str] = {}
        refresh_calls = {"count": 0}

        def refresh(_payload: dict[str, object], *, import_external: bool):
            refresh_calls["count"] += 1
            if "batch_id" not in captured:
                return _queue(self.root)
            batch_id = captured["batch_id"]
            return _queue(
                self.root,
                batches=[
                    {
                        "batch_id": batch_id,
                        "batch_path": str(self.root / "batches" / batch_id),
                        "source_count": 3,
                        "status": "awaiting_external_review",
                    }
                ],
            )

        def prepare(payload: dict[str, object]) -> dict[str, object]:
            captured["batch_id"] = str(payload["preallocated_batch_id"])
            return {
                "status": "awaiting_external_review",
                "batch_id": captured["batch_id"],
                "batch_path": str(
                    self.root / "batches" / captured["batch_id"]
                ),
                "prepared_sources": [
                    {"source_id": 1},
                    {"source_id": 2},
                    {"source_id": 3},
                ],
            }

        clock_calls = {"count": 0}

        def crash_after_commit() -> float:
            clock_calls["count"] += 1
            if clock_calls["count"] == 1:
                return 0.0
            raise KeyboardInterrupt("simulated post-commit process death")

        refresh_queue.side_effect = refresh
        scan_inventory.return_value = _inventory(4)
        prepare_selected.side_effect = prepare
        payload = {
            **self.payload,
            "workload_mode": "up_to_n",
            "new_source_limit": 4,
        }

        with self.assertRaisesRegex(
            KeyboardInterrupt,
            "post-commit process death",
        ):
            review_orchestration.process_from_request(
                {**payload, "clock": crash_after_commit}
            )

        before = json.loads(
            (self.root / ".orchestration" / "active-run.json").read_text(
                encoding="utf-8"
            )
        )["run"]
        self.assertEqual(before["cursor"], 0)
        self.assertEqual(before["inflight_batch_id"], captured["batch_id"])
        self.assertEqual(
            [item["source_id"] for item in before["inflight_chunk"]],
            [1, 2, 3],
        )

        (self.root / ".orchestration" / "stop.requested").write_text(
            "stop",
            encoding="utf-8",
        )
        resumed = review_orchestration.process_from_request(payload)

        self.assertEqual(resumed["run_state"]["status"], "paused_after_current")
        self.assertEqual(resumed["run_state"]["completed_count"], 3)
        self.assertEqual(resumed["run_state"]["remaining_count"], 1)
        self.assertEqual(prepare_selected.call_count, 1)
        self.assertEqual(scan_inventory.call_count, 1)
        after = json.loads(
            (self.root / ".orchestration" / "active-run.json").read_text(
                encoding="utf-8"
            )
        )["run"]
        self.assertEqual(after["cursor"], 3)
        self.assertEqual(after["inflight_chunk"], [])
        self.assertEqual(after["inflight_batch_id"], "")
        self.assertEqual(
            after["batches"],
            [
                {
                    "batch_id": captured["batch_id"],
                    "source_count": 3,
                    "status": "awaiting_external_review",
                }
            ],
        )

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_safe_preparation_error_returns_versioned_attention_contract(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
    ) -> None:
        refresh_queue.return_value = _queue(self.root)
        scan_inventory.return_value = _inventory(3)
        private_detail = r"C:\private-media\operator\synthetic.mp4 could not be read"
        prepare_selected.side_effect = RuntimeError(private_detail)

        result = review_orchestration.process_from_request(self.payload)

        self.assertEqual(result["contract_version"], 1)
        self.assertEqual(
            result["document_type"],
            "review_media_inbox_process_result",
        )
        self.assertEqual(result["operator_status"], "Needs attention")
        self.assertEqual(result["attention"]["code"], "preparation_error")
        self.assertNotIn(private_detail, result["attention"]["message"])
        self.assertNotIn("RuntimeError", result["attention"]["message"])
        self.assertEqual(
            result["attention"]["details"],
            f"RuntimeError: {private_detail}",
        )
        self.assertEqual(result["run_state"]["status"], "needs_attention")
        self.assertFalse(result["continue_automatically"])
        self.assertEqual(refresh_queue.call_count, 3)
        self.assertFalse(refresh_queue.call_args_list[0].kwargs["import_external"])
        self.assertTrue(refresh_queue.call_args_list[1].kwargs["import_external"])
        self.assertFalse(refresh_queue.call_args_list[2].kwargs["import_external"])

    @patch.object(review_orchestration, "_finalize")
    @patch.object(review_orchestration, "_preview_finalization")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_cleanup_uses_one_aggregate_token_and_persists_safe_keep_decision(
        self,
        refresh_queue,
        scan_inventory,
        preview_finalization,
        finalize,
    ) -> None:
        batch_root = self.root / "batches" / "batch-results"
        scan_inventory.return_value = _inventory(0)
        refresh_queue.return_value = _queue(
            self.root,
            batches=[
                {
                    "batch_id": "batch-results",
                    "batch_path": str(batch_root),
                    "status": "results_received",
                }
            ],
        )

        def preview(payload: dict[str, object]) -> dict[str, object]:
            keep = payload["retention_policy"] == "keep_generated"
            return {
                "batch_id": "batch-results",
                "batch_root": str(batch_root),
                "plan_sha256": ("b" if keep else "a") * 64,
                "plan_path": str(batch_root / f"plan-{'keep' if keep else 'compact'}.json"),
                "disposable_bytes": 0 if keep else 1234,
                "sources": [{"source_identity": "sha256:" + ("c" * 64)}],
            }

        preview_finalization.side_effect = preview
        finalize.return_value = {
            "status": "finalized_no_findings",
            "batch_id": "batch-results",
        }

        confirmation_result = review_orchestration.process_from_request(self.payload)

        confirmation = confirmation_result["cleanup_confirmation"]
        self.assertEqual(confirmation["disposable_bytes"], 1234)
        self.assertEqual(confirmation["default_choice"], "keep_generated")
        completed = review_orchestration.process_from_request(
            {
                **self.payload,
                "continuation": confirmation_result["continuation"],
                "decision": {
                    "type": "cleanup",
                    "token": confirmation["token"],
                    "choice": "keep_generated",
                },
            }
        )

        self.assertEqual(completed["run_state"]["status"], "complete")
        policies = [
            call.args[0]["retention_policy"] for call in preview_finalization.call_args_list
        ]
        self.assertIn("compact", policies)
        self.assertIn("keep_generated", policies)
        finalize.assert_called_once()
        archived = next(
            (self.root / ".orchestration" / "completed-runs").glob("*.json")
        )
        envelope = json.loads(archived.read_text(encoding="utf-8"))
        self.assertEqual(
            envelope["run"]["cleanup_decision"]["choice"],
            "keep_generated",
        )
        scan_inventory.assert_called_once()

    @patch.object(review_orchestration, "_execute_cleanup")
    @patch.object(review_orchestration, "_preview_finalization")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_cleanup_decision_is_reused_after_crash_for_identical_plan_token(
        self,
        refresh_queue,
        scan_inventory,
        preview_finalization,
        execute_cleanup,
    ) -> None:
        batch_root = self.root / "batches" / "batch-results"
        scan_inventory.return_value = _inventory(0)
        results_queue = _queue(
            self.root,
            batches=[
                {
                    "batch_id": "batch-results",
                    "batch_path": str(batch_root),
                    "status": "results_received",
                }
            ],
        )
        refresh_queue.return_value = results_queue
        preview_finalization.return_value = {
            "batch_id": "batch-results",
            "batch_root": str(batch_root),
            "plan_sha256": "a" * 64,
            "plan_path": str(batch_root / "plan.json"),
            "disposable_bytes": 321,
            "sources": [{"source_identity": "sha256:" + ("b" * 64)}],
        }
        execute_cleanup.side_effect = KeyboardInterrupt("synthetic crash")

        prompt = review_orchestration.process_from_request(self.payload)
        confirmation = prompt["cleanup_confirmation"]
        with self.assertRaisesRegex(KeyboardInterrupt, "synthetic crash"):
            review_orchestration.process_from_request(
                {
                    **self.payload,
                    "continuation": prompt["continuation"],
                    "decision": {
                        "type": "cleanup",
                        "token": confirmation["token"],
                        "choice": "remove_temporary",
                    },
                }
            )

        envelope = json.loads(
            (self.root / ".orchestration" / "active-run.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            envelope["run"]["cleanup_decision"]["choice"],
            "remove_temporary",
        )
        execute_cleanup.side_effect = None
        execute_cleanup.return_value = []

        completed = review_orchestration.process_from_request(self.payload)

        self.assertIsNone(completed["cleanup_confirmation"])
        self.assertEqual(completed["run_state"]["status"], "complete")
        self.assertEqual(execute_cleanup.call_count, 2)
        scan_inventory.assert_called_once()

    @patch.object(review_orchestration, "_execute_cleanup")
    @patch.object(review_orchestration, "_preview_finalization")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_changed_cleanup_plan_requires_fresh_confirmation_after_crash(
        self,
        refresh_queue,
        scan_inventory,
        preview_finalization,
        execute_cleanup,
    ) -> None:
        batch_root = self.root / "batches" / "batch-results"
        refresh_queue.return_value = _queue(
            self.root,
            batches=[
                {
                    "batch_id": "batch-results",
                    "batch_path": str(batch_root),
                    "status": "results_received",
                }
            ],
        )
        plan = {"sha": "a" * 64}

        def preview(_payload: dict[str, object]) -> dict[str, object]:
            return {
                "batch_id": "batch-results",
                "batch_root": str(batch_root),
                "plan_sha256": plan["sha"],
                "plan_path": str(batch_root / "plan.json"),
                "disposable_bytes": 321,
                "sources": [{"source_identity": "sha256:" + ("b" * 64)}],
            }

        preview_finalization.side_effect = preview
        execute_cleanup.side_effect = KeyboardInterrupt("synthetic crash")
        prompt = review_orchestration.process_from_request(self.payload)
        with self.assertRaisesRegex(KeyboardInterrupt, "synthetic crash"):
            review_orchestration.process_from_request(
                {
                    **self.payload,
                    "continuation": prompt["continuation"],
                    "decision": {
                        "type": "cleanup",
                        "token": prompt["cleanup_confirmation"]["token"],
                        "choice": "remove_temporary",
                    },
                }
            )
        plan["sha"] = "c" * 64
        execute_cleanup.side_effect = None

        changed = review_orchestration.process_from_request(self.payload)

        self.assertIsNotNone(changed["cleanup_confirmation"])
        self.assertNotEqual(
            changed["cleanup_confirmation"]["token"],
            prompt["cleanup_confirmation"]["token"],
        )
        self.assertEqual(execute_cleanup.call_count, 1)
        scan_inventory.assert_not_called()

    @patch.object(review_orchestration, "_execute_cleanup")
    @patch.object(review_orchestration, "_preview_finalization")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_cleanup_stop_resumes_remaining_matching_plans_without_reprompt(
        self,
        refresh_queue,
        scan_inventory,
        preview_finalization,
        execute_cleanup,
    ) -> None:
        marker = self.root / "stop-after-current.requested"
        scan_inventory.return_value = _inventory(0)

        def batch(batch_id: str) -> dict[str, object]:
            return {
                "batch_id": batch_id,
                "batch_path": str(self.root / "batches" / batch_id),
                "status": "results_received",
            }

        both = _queue(
            self.root,
            batches=[batch("batch-a"), batch("batch-b")],
        )
        remaining = _queue(self.root, batches=[batch("batch-b")])
        refresh_queue.side_effect = [
            both,
            both,
            both,
            both,
            remaining,
            remaining,
            remaining,
            _queue(self.root),
        ]

        def preview(payload: dict[str, object]) -> dict[str, object]:
            batch_id = str(payload["expected_batch_id"])
            suffix = "a" if batch_id == "batch-a" else "b"
            batch_root = self.root / "batches" / batch_id
            return {
                "batch_id": batch_id,
                "batch_root": str(batch_root),
                "plan_sha256": suffix * 64,
                "plan_path": str(batch_root / "plan.json"),
                "disposable_bytes": 100,
                "sources": [{"source_identity": "sha256:" + ("c" * 64)}],
            }

        preview_finalization.side_effect = preview

        def execute_first(
            _ledger: Path,
            previews: list[dict[str, object]],
            choice: str,
            *,
            stop_requested,
        ) -> list[dict[str, object]]:
            self.assertEqual(choice, "remove_temporary")
            self.assertEqual([item["batch_id"] for item in previews], ["batch-a", "batch-b"])
            marker.write_text("stop", encoding="utf-8")
            self.assertTrue(stop_requested())
            return [{"batch_id": "batch-a"}]

        execute_cleanup.side_effect = execute_first
        payload = {
            **self.payload,
            "stop_after_current_file_path": str(marker),
        }
        prompt = review_orchestration.process_from_request(payload)
        paused = review_orchestration.process_from_request(
            {
                **payload,
                "continuation": prompt["continuation"],
                "decision": {
                    "type": "cleanup",
                    "token": prompt["cleanup_confirmation"]["token"],
                    "choice": "remove_temporary",
                },
            }
        )

        self.assertEqual(paused["run_state"]["status"], "paused_after_current")
        self.assertIsNone(paused["cleanup_confirmation"])
        marker.unlink()
        execute_cleanup.side_effect = None
        execute_cleanup.return_value = [{"batch_id": "batch-b"}]

        completed = review_orchestration.process_from_request(
            {**payload, "continuation": paused["continuation"]}
        )

        self.assertEqual(completed["run_state"]["status"], "complete")
        self.assertIsNone(completed["cleanup_confirmation"])
        self.assertEqual(execute_cleanup.call_count, 2)
        second_previews = execute_cleanup.call_args_list[1].args[1]
        self.assertEqual(
            [item["batch_id"] for item in second_previews],
            ["batch-b"],
        )
        scan_inventory.assert_called_once()

    @patch.object(review_orchestration, "_recover_finalizing")
    @patch.object(review_orchestration, "_recover_preparation_staging")
    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_reconcile_recovers_started_work_without_scanning_or_preparing(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
        recover_preparation,
        recover_finalizing,
    ) -> None:
        events: list[str] = []
        first_queue = _queue(
            self.root,
            batches=[
                {
                    "batch_id": "batch-recovery",
                    "batch_path": str(self.root / "batches" / "batch-recovery"),
                    "status": "preparing",
                }
            ],
        )
        final_queue = _queue(self.root)

        def refresh(_payload, *, import_external):
            events.append(f"refresh:{import_external}")
            return first_queue if not import_external else final_queue

        def recover_staging(queue, request):
            events.append("recover:preparation")
            self.assertIs(queue, first_queue)
            self.assertIs(request, self.payload)
            return [
                {
                    "batch_id": "batch-recovery",
                    "classification": "stale_reusable",
                }
            ]

        def recover_journals(queue, ledger):
            events.append("recover:finalization")
            self.assertIs(queue, first_queue)
            self.assertEqual(ledger, self.ledger)
            return True

        refresh_queue.side_effect = refresh
        recover_preparation.side_effect = recover_staging
        recover_finalizing.side_effect = recover_journals
        recover_preparation.return_value = [
            {
                "batch_id": "batch-recovery",
                "classification": "stale_reusable",
            }
        ]

        result = review_orchestration.reconcile_from_request(self.payload)

        self.assertEqual(result["action"], "reconcile")
        self.assertEqual(refresh_queue.call_count, 2)
        refresh_queue.assert_called_with(self.payload, import_external=True)
        recover_preparation.assert_called_once_with(first_queue, self.payload)
        recover_finalizing.assert_called_once_with(first_queue, self.ledger)
        self.assertEqual(
            events,
            [
                "refresh:False",
                "recover:preparation",
                "recover:finalization",
                "refresh:True",
            ],
        )
        self.assertEqual(
            result["recovery"],
            [
                {
                    "batch_id": "batch-recovery",
                    "classification": "stale_reusable",
                },
                {"kind": "finalization", "classification": "recovered"},
            ],
        )
        scan_inventory.assert_not_called()
        prepare_selected.assert_not_called()

    @patch.object(review_orchestration, "_recover_finalizing")
    @patch.object(review_orchestration, "_recover_preparation_staging")
    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_process_recovers_started_work_before_importing_external_returns(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
        recover_preparation,
        recover_finalizing,
    ) -> None:
        events: list[str] = []
        initial_queue = _queue(self.root)
        imported_queue = _queue(self.root)

        def refresh(_payload, *, import_external):
            events.append(f"refresh:{import_external}")
            return imported_queue if import_external else initial_queue

        def recover_staging(queue, request):
            events.append("recover:preparation")
            self.assertIs(queue, initial_queue)
            self.assertIs(request, self.payload)
            return []

        def recover_journals(queue, ledger):
            events.append("recover:finalization")
            self.assertIs(queue, initial_queue)
            self.assertEqual(ledger, self.ledger)
            return False

        refresh_queue.side_effect = refresh
        recover_preparation.side_effect = recover_staging
        recover_finalizing.side_effect = recover_journals
        scan_inventory.return_value = _inventory(0)

        result = review_orchestration.process_from_request(self.payload)

        self.assertEqual(result["run_state"]["status"], "complete")
        self.assertEqual(
            events,
            [
                "refresh:False",
                "recover:preparation",
                "recover:finalization",
                "refresh:True",
            ],
        )
        prepare_selected.assert_not_called()

    @patch.object(review_orchestration, "_recover_preparation_staging")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_process_recovery_error_keeps_private_diagnostics_out_of_message(
        self,
        refresh_queue,
        recover_preparation,
    ) -> None:
        private_detail = r"C:\private-media\operator\staging could not be recovered"
        refresh_queue.return_value = _queue(self.root)
        recover_preparation.side_effect = review_orchestration.OrchestrationError(
            private_detail
        )

        result = review_orchestration.process_from_request(self.payload)

        self.assertEqual(result["operator_status"], "Needs attention")
        self.assertEqual(result["attention"]["code"], "recovery_error")
        self.assertNotIn(private_detail, result["attention"]["message"])
        self.assertNotIn("RuntimeError", result["attention"]["message"])
        self.assertEqual(
            result["attention"]["details"],
            f"OrchestrationError: {private_detail}",
        )
        self.assertEqual(result["run_state"]["status"], "needs_attention")

    @patch.object(review_orchestration, "_refresh_queue")
    def test_initial_queue_projection_error_returns_safe_process_contract(
        self,
        refresh_queue,
    ) -> None:
        private_detail = r"C:\private-queue\review-ledger.sqlite could not be opened"
        refresh_queue.side_effect = review_orchestration.OrchestrationError(
            private_detail
        )

        result = review_orchestration.process_from_request(self.payload)

        self.assertEqual(result["document_type"], "review_media_inbox_process_result")
        self.assertEqual(result["operator_status"], "Needs attention")
        self.assertEqual(result["attention"]["code"], "recovery_error")
        self.assertNotIn(private_detail, result["attention"]["message"])
        self.assertEqual(
            result["attention"]["details"],
            f"OrchestrationError: {private_detail}",
        )

    @patch.object(review_orchestration, "_refresh_queue")
    def test_initial_queue_projection_error_returns_safe_reconcile_contract(
        self,
        refresh_queue,
    ) -> None:
        private_detail = r"C:\private-queue\queue-index.json could not be rebuilt"
        refresh_queue.side_effect = review_orchestration.OrchestrationError(
            private_detail
        )

        result = review_orchestration.reconcile_from_request(self.payload)

        self.assertEqual(result["document_type"], "review_media_inbox_process_result")
        self.assertEqual(result["action"], "reconcile")
        self.assertEqual(result["operator_status"], "Needs attention")
        self.assertNotIn(private_detail, result["attention"]["message"])
        self.assertEqual(
            result["attention"]["details"],
            f"OrchestrationError: {private_detail}",
        )

    @patch.object(review_orchestration, "_recover_finalizing")
    @patch.object(review_orchestration, "_recover_preparation_staging")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_reconcile_attaches_read_only_while_process_lock_is_owned(
        self,
        refresh_queue,
        recover_preparation,
        recover_finalizing,
    ) -> None:
        paths = review_orchestration._orchestration_paths(self.ledger)
        paths["root"].mkdir(parents=True)
        run = review_orchestration._new_run(self.payload, _inventory(2))
        run["status"] = "preparing"
        review_orchestration._write_journal(paths["active"], run)
        index_path = self.root / "queue-index.json"
        index_path.write_text(
            json.dumps(
                {
                    "contract_version": 1,
                    "document_type": "review_media_inbox_queue",
                    "operator_status": "Ready for Codex review",
                    "counts": {
                        "ready_for_codex_review": 2,
                        "waiting_on_codex": 0,
                        "additional_local_evidence": 0,
                        "done": 0,
                    },
                }
            ),
            encoding="utf-8",
        )
        with inbox_records.ProcessLock(paths["lock"]) as owner:
            self.assertTrue(owner.acquired)
            journal_before = paths["active"].read_bytes()
            index_before = index_path.read_bytes()
            result = review_orchestration.reconcile_from_request(self.payload)

        self.assertEqual(result["attention"]["code"], "process_already_running")
        self.assertEqual(result["operator_status"], "Processing")
        self.assertEqual(result["queue_counts"]["ready_for_codex_review"], 2)
        self.assertEqual(paths["active"].read_bytes(), journal_before)
        self.assertEqual(index_path.read_bytes(), index_before)
        refresh_queue.assert_not_called()
        recover_preparation.assert_not_called()
        recover_finalizing.assert_not_called()

    @patch.object(review_orchestration, "_refresh_queue")
    def test_existing_process_lock_attaches_without_starting_another(
        self,
        refresh_queue,
    ) -> None:
        paths = review_orchestration._orchestration_paths(self.ledger)
        paths["root"].mkdir(parents=True)
        with inbox_records.ProcessLock(paths["lock"]) as owner:
            self.assertTrue(owner.acquired)
            result = review_orchestration.process_from_request(self.payload)

        self.assertEqual(result["attention"]["code"], "process_already_running")
        refresh_queue.assert_not_called()

    def test_python_and_powershell_share_one_exclusive_coordinator_lock(
        self,
    ) -> None:
        if os.name != "nt":
            self.skipTest("Cross-runtime coordinator locking is Windows-specific.")
        powershell = (
            Path(os.environ.get("WINDIR", r"C:\Windows"))
            / "System32"
            / "WindowsPowerShell"
            / "v1.0"
            / "powershell.exe"
        )
        if not powershell.is_file():
            self.skipTest("Windows PowerShell is unavailable.")

        paths = review_orchestration._orchestration_paths(self.ledger)
        paths["root"].mkdir(parents=True)
        ready = self.root / "powershell-lock.ready"
        stop = self.root / "powershell-lock.stop"
        holder_script = (
            "$h=[System.IO.File]::Open($env:MM_LOCK_PATH,"
            "[System.IO.FileMode]::OpenOrCreate,"
            "[System.IO.FileAccess]::ReadWrite,"
            "[System.IO.FileShare]::None);"
            "[System.IO.File]::WriteAllText($env:MM_READY_PATH,'ready');"
            "while(-not (Test-Path -LiteralPath $env:MM_STOP_PATH))"
            "{Start-Sleep -Milliseconds 20};"
            "$h.Dispose()"
        )
        holder_environment = {
            **os.environ,
            "MM_LOCK_PATH": str(paths["lock"]),
            "MM_READY_PATH": str(ready),
            "MM_STOP_PATH": str(stop),
        }
        holder = subprocess.Popen(
            [
                str(powershell),
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                holder_script,
            ],
            creationflags=subprocess.CREATE_NO_WINDOW,
            env=holder_environment,
        )
        try:
            deadline = time.monotonic() + 10.0
            while not ready.is_file() and holder.poll() is None:
                if time.monotonic() >= deadline:
                    self.fail("PowerShell did not acquire the coordinator lock.")
                time.sleep(0.02)
            self.assertIsNone(holder.poll())
            with inbox_records.ProcessLock(paths["lock"]) as contender:
                self.assertFalse(contender.acquired)
        finally:
            stop.write_text("stop", encoding="utf-8")
            try:
                holder.wait(timeout=10)
            except subprocess.TimeoutExpired:
                holder.kill()
                holder.wait(timeout=5)

        contender_script = (
            "try{"
            "$h=[System.IO.File]::Open($env:MM_LOCK_PATH,"
            "[System.IO.FileMode]::OpenOrCreate,"
            "[System.IO.FileAccess]::ReadWrite,"
            "[System.IO.FileShare]::None);"
            "$h.Dispose();exit 0"
            "}catch [System.IO.IOException]{exit 23}"
        )
        with inbox_records.ProcessLock(paths["lock"]) as owner:
            self.assertTrue(owner.acquired)
            blocked = subprocess.run(
                [
                    str(powershell),
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    contender_script,
                ],
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
                env={**os.environ, "MM_LOCK_PATH": str(paths["lock"])},
                timeout=10,
            )
            self.assertEqual(blocked.returncode, 23)

    @patch.object(review_orchestration, "_refresh_queue")
    def test_attach_only_reads_active_journal_and_queue_index_without_mutation(
        self,
        refresh_queue,
    ) -> None:
        paths = review_orchestration._orchestration_paths(self.ledger)
        paths["root"].mkdir(parents=True)
        run = review_orchestration._new_run(self.payload, _inventory(2))
        run["status"] = "preparing"
        run["cursor"] = 1
        run["elapsed_seconds"] = 12.5
        review_orchestration._write_journal(paths["active"], run)
        (self.root / "queue-index.json").write_text(
            json.dumps(
                {
                    "contract_version": 1,
                    "document_type": "review_media_inbox_queue",
                    "operator_status": "Ready for Codex review",
                    "counts": {
                        "ready_for_codex_review": 4,
                        "waiting_on_codex": 2,
                        "additional_local_evidence": 1,
                        "done": 18,
                    },
                    "batches": [],
                    "attention": [],
                }
            ),
            encoding="utf-8",
        )
        journal_before = paths["active"].read_bytes()
        index_before = (self.root / "queue-index.json").read_bytes()

        result = review_orchestration.process_from_request(
            {**self.payload, "attach_only": True}
        )

        self.assertEqual(result["run_state"]["run_id"], run["run_id"])
        self.assertEqual(result["run_state"]["status"], "preparing")
        self.assertEqual(result["queue_counts"]["ready_for_codex_review"], 4)
        self.assertEqual(
            result["queue_prompt_path"],
            str(self.root / "CODEX_REVIEW_QUEUE_PROMPT.md"),
        )
        self.assertEqual(
            result["queue_index_path"],
            str(self.root / "queue-index.json"),
        )
        self.assertEqual(
            set(result["run_state"]),
            {
                "run_id",
                "status",
                "workload_mode",
                "new_source_limit",
                "active",
                "selected_count",
                "completed_count",
                "remaining_count",
                "current_batch_id",
                "current_source_id",
                "current_source_name",
                "current_source_ordinal",
                "current_source_total",
                "current_activity",
                "elapsed_seconds",
                "total_elapsed_seconds",
                "stop_requested",
                "resumable",
            },
        )
        self.assertEqual(paths["active"].read_bytes(), journal_before)
        self.assertEqual((self.root / "queue-index.json").read_bytes(), index_before)
        refresh_queue.assert_not_called()

    @patch.object(review_orchestration, "_refresh_queue")
    def test_stop_request_only_signals_owner_and_does_not_race_run_journal(
        self,
        refresh_queue,
    ) -> None:
        paths = review_orchestration._orchestration_paths(self.ledger)
        paths["root"].mkdir(parents=True)
        run = review_orchestration._new_run(self.payload, _inventory(2))
        run["status"] = "preparing"
        review_orchestration._write_journal(paths["active"], run)
        journal_before = paths["active"].read_bytes()

        result = review_orchestration.process_from_request(
            {**self.payload, "request_stop": True}
        )

        self.assertEqual(result["operator_status"], "Processing")
        self.assertTrue(paths["stop"].is_file())
        self.assertEqual(paths["active"].read_bytes(), journal_before)
        self.assertFalse(result["run_state"]["stop_requested"])
        refresh_queue.assert_not_called()

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_powershell_owned_lock_bypasses_internal_lock_without_releasing_it(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
    ) -> None:
        paths = review_orchestration._orchestration_paths(self.ledger)
        paths["root"].mkdir(parents=True)
        lock_content = json.dumps(
            {
                "schema_version": 1,
                "token": "powershell-owner",
                "process_id": os.getpid(),
                "created_utc": "2026-01-01T00:00:00+00:00",
            }
        )
        paths["lock"].write_text(lock_content, encoding="utf-8")
        refresh_queue.return_value = _queue(self.root)
        scan_inventory.return_value = _inventory(0)

        result = review_orchestration.process_from_request(
            {**self.payload, "coordinator_lock_held": True}
        )

        self.assertEqual(result["run_state"]["status"], "complete")
        self.assertEqual(paths["lock"].read_text(encoding="utf-8"), lock_content)
        self.assertEqual(
            [call.kwargs["import_external"] for call in refresh_queue.call_args_list],
            [False, True],
        )
        prepare_selected.assert_not_called()

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_direct_cli_reuses_unowned_diagnostic_lock_file(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
    ) -> None:
        paths = review_orchestration._orchestration_paths(self.ledger)
        paths["root"].mkdir(parents=True)
        paths["lock"].write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "token": "stale",
                    "process_id": os.getpid() + 100_000,
                    "created_utc": "2026-01-01T00:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        refresh_queue.return_value = _queue(self.root)
        scan_inventory.return_value = _inventory(0)

        result = review_orchestration.process_from_request(self.payload)

        self.assertEqual(result["run_state"]["status"], "complete")
        self.assertTrue(paths["lock"].exists())
        record = json.loads(paths["lock"].read_text(encoding="utf-8"))
        self.assertNotEqual(record["token"], "stale")
        self.assertEqual(record["process_id"], os.getpid())
        prepare_selected.assert_not_called()

    @patch("media_manglers.core.review_inbox.scan_from_request")
    def test_scan_inventory_preserves_explicit_full_setting(self, scan) -> None:
        scan.return_value = {
            "settings": {"ledger_path": str(self.ledger)},
            "sources": [],
        }

        review_orchestration._scan_inventory(
            {**self.payload, "dedupe_mode": "Full"}
        )

        request = scan.call_args.args[0]
        self.assertEqual(request["dedupe_mode"], "Full")
        self.assertEqual(request["order"], "oldest")
        self.assertEqual(request["max_files"], 9_999)

    @patch.object(review_orchestration, "_refresh_queue")
    def test_changed_journal_checksum_fails_closed(self, refresh_queue) -> None:
        paths = review_orchestration._orchestration_paths(self.ledger)
        paths["root"].mkdir(parents=True)
        paths["active"].write_text(
            json.dumps(
                {
                    "journal_version": 1,
                    "run": {"run_id": "tampered"},
                    "run_sha256": "0" * 64,
                }
            ),
            encoding="utf-8",
        )

        for action in (
            review_orchestration.reconcile_from_request,
            review_orchestration.process_from_request,
        ):
            with self.subTest(action=action.__name__):
                result = action(self.payload)
                self.assertEqual(
                    result["document_type"],
                    "review_media_inbox_process_result",
                )
                self.assertEqual(result["operator_status"], "Needs attention")
                self.assertIn("checksum", result["attention"]["details"])
                self.assertNotIn(
                    "checksum",
                    result["attention"]["message"].lower(),
                )
                self.assertTrue(paths["active"].is_file())
        refresh_queue.assert_not_called()

    @patch.object(
        review_orchestration,
        "_reconcile_committed_inflight_batch",
        side_effect=review_orchestration.OrchestrationError(
            "private committed chunk mismatch"
        ),
    )
    @patch.object(review_orchestration, "_refresh_queue")
    def test_committed_chunk_recovery_error_returns_safe_process_contract(
        self,
        refresh_queue,
        _reconcile_committed,
    ) -> None:
        paths = review_orchestration._orchestration_paths(self.ledger)
        run = review_orchestration._new_run(self.payload, _inventory(3))
        review_orchestration._write_active(paths, run)
        refresh_queue.return_value = _queue(self.root)

        result = review_orchestration.process_from_request(self.payload)

        self.assertEqual(
            result["document_type"],
            "review_media_inbox_process_result",
        )
        self.assertEqual(result["operator_status"], "Needs attention")
        self.assertEqual(result["attention"]["code"], "recovery_error")
        self.assertNotIn(
            "private committed chunk mismatch",
            result["attention"]["message"],
        )
        self.assertIn(
            "private committed chunk mismatch",
            result["attention"]["details"],
        )

    @patch.object(
        review_orchestration,
        "_handle_external_work",
        side_effect=review_orchestration.OrchestrationError(
            "private stale cleanup decision"
        ),
    )
    @patch.object(review_orchestration, "_refresh_queue")
    def test_external_work_error_returns_safe_process_contract(
        self,
        refresh_queue,
        _handle_external_work,
    ) -> None:
        refresh_queue.return_value = _queue(self.root)

        result = review_orchestration.process_from_request(self.payload)

        self.assertEqual(result["operator_status"], "Needs attention")
        self.assertEqual(result["attention"]["code"], "external_work_error")
        self.assertNotIn(
            "private stale cleanup decision",
            result["attention"]["message"],
        )
        self.assertIn(
            "private stale cleanup decision",
            result["attention"]["details"],
        )

    def test_up_to_n_rejects_non_positive_and_out_of_range_values(self) -> None:
        for value in (0, -1, 10_000, True, 1.0, 1.5, "not-a-number"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    review_orchestration._normalise_workload(
                        {
                            "workload_mode": "up_to_n",
                            "new_source_limit": value,
                        }
                    )

    def test_time_estimate_requires_three_valid_recent_successes(self) -> None:
        for values in ([], [10], [10, 20]):
            with self.subTest(values=values):
                result = review_orchestration._recent_duration_estimate(
                    self.ledger,
                    {"recent_preparation_durations_seconds": values},
                    5,
                )
                self.assertIsNone(result["estimated_seconds"])
                self.assertEqual(result["basis"], "No reliable time estimate yet")

        reliable = review_orchestration._recent_duration_estimate(
            self.ledger,
            {"recent_preparation_durations_seconds": [10, 20, 30]},
            5,
        )
        self.assertEqual(reliable["sample_count"], 3)
        self.assertEqual(reliable["median_source_seconds"], 20.0)
        self.assertEqual(reliable["estimated_seconds"], 100.0)

    def test_all_pending_capacity_uses_canonical_ledger_parent(self) -> None:
        from media_manglers.core import review_preparation

        probes: list[Path] = []
        payload = {
            **self.payload,
            "workload_mode": "all_pending",
            "evidence_root": str(self.root / "legacy-evidence"),
            "space_probe": lambda path: probes.append(path) or 10**12,
        }
        run = review_orchestration._new_run(payload, _inventory(3))

        confirmation = review_orchestration._all_pending_confirmation(
            self.ledger,
            payload,
            run,
        )

        self.assertEqual(confirmation["evidence_free_bytes"], 10**12)
        expected = review_preparation.estimate_storage(
            300,
            review_orchestration.SOFT_LIMIT_MINUTES * 60.0,
            review_preparation.timeline_frame_count(
                review_orchestration.SOFT_LIMIT_MINUTES * 60.0
            ),
            0,
        )
        self.assertEqual(
            confirmation["estimated_peak_temporary_bytes"],
            expected["scratch_required_bytes"],
        )
        self.assertIn(self.root, probes)
        self.assertNotIn(self.root / "legacy-evidence", probes)

    @patch("media_manglers.core.review_inbox.scan_from_request")
    def test_scan_errors_fail_closed_before_source_allocation(self, scan) -> None:
        scan.return_value = {
            "settings": {"ledger_path": str(self.ledger)},
            "sources": [_source(1)],
            "scan_errors": [
                {
                    "path": str(self.root / "sources" / "unreadable.mp4"),
                    "error": "access denied",
                }
            ],
        }

        with self.assertRaisesRegex(
            review_orchestration.OrchestrationError,
            "Inbox scanning reported 1 error",
        ):
            review_orchestration._scan_inventory(self.payload)

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_stop_arriving_during_initial_scan_starts_no_source(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
    ) -> None:
        paths = review_orchestration._orchestration_paths(self.ledger)

        def scan(_payload: dict[str, object]) -> dict[str, object]:
            paths["root"].mkdir(parents=True, exist_ok=True)
            paths["stop"].write_text("stop", encoding="utf-8")
            return _inventory(3)

        refresh_queue.return_value = _queue(self.root)
        scan_inventory.side_effect = scan

        result = review_orchestration.process_from_request(self.payload)

        self.assertEqual(result["run_state"]["status"], "paused_after_current")
        self.assertEqual(result["run_state"]["completed_count"], 0)
        self.assertEqual(result["run_state"]["remaining_count"], 3)
        self.assertTrue(result["run_state"]["stop_requested"])
        prepare_selected.assert_not_called()

    def test_run_summary_uses_legacy_cursor_but_preserves_exact_partial_progress(
        self,
    ) -> None:
        legacy_run = {
            "run_id": "legacy-v1",
            "status": "paused_after_current",
            "workload": {"mode": "next_3", "requested_limit": 3},
            "snapshot": [_source(1), _source(2), _source(3)],
            "cursor": 2,
        }

        legacy_summary = review_orchestration._run_summary(legacy_run)
        current_summary = review_orchestration._run_summary(
            {
                **legacy_run,
                "run_id": "current-v1",
                "cursor": 3,
                "completed_source_ids": ["1"],
            }
        )

        self.assertEqual(legacy_summary["completed_count"], 2)
        self.assertEqual(legacy_summary["remaining_count"], 1)
        self.assertEqual(current_summary["completed_count"], 1)
        self.assertEqual(current_summary["remaining_count"], 2)

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_progress_counts_only_prepared_sources_after_partial_failure(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
    ) -> None:
        refresh_queue.return_value = _queue(self.root)
        scan_inventory.return_value = _inventory(4)
        prepare_selected.return_value = {
            "status": "preparing",
            "batch_id": "batch-partial",
            "prepared_sources": [{"source_id": 1}],
            "blocked_sources": [],
            "failed_sources": [
                {
                    "source_id": 2,
                    "state": "source_changed",
                    "message": "Source changed.",
                }
            ],
        }

        result = review_orchestration.process_from_request(
            {
                **self.payload,
                "workload_mode": "up_to_n",
                "new_source_limit": 4,
            }
        )

        self.assertEqual(result["run_state"]["completed_count"], 1)
        self.assertEqual(result["run_state"]["remaining_count"], 3)
        self.assertEqual(result["run_state"]["current_source_id"], 2)
        self.assertEqual(result["run_state"]["current_source_ordinal"], 2)

    def test_empty_exact_source_restriction_preserves_next_three(self) -> None:
        selected, restriction = review_orchestration._restricted_snapshot(
            {**self.payload, "exact_source_paths": []},
            _inventory(5),
        )

        self.assertEqual([item["source_id"] for item in selected], [1, 2, 3])
        self.assertIsNone(restriction)

    def test_exact_source_restriction_requires_literal_absolute_paths(self) -> None:
        for value in ("relative-source.mp4", "~/source.mp4"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    review_orchestration.ExactSourceRestrictionError,
                    "absolute local path",
                ):
                    review_orchestration._normalise_exact_source_paths(
                        {"exact_source_paths": [value]}
                    )

    def test_exact_source_snapshot_uses_full_scan_counts_and_oldest_order(
        self,
    ) -> None:
        inventory, sources = self._filesystem_inventory(
            [{} for _index in range(5)]
        )
        selected, restriction = review_orchestration._restricted_snapshot(
            {
                **self.payload,
                "exact_source_paths": [
                    str(sources[3]["path"]),
                    str(sources[1]["path"]),
                ],
            },
            inventory,
        )

        self.assertEqual([item["source_id"] for item in selected], [2, 4])
        self.assertEqual(restriction["selected_source_ids"], [2, 4])
        self.assertEqual(
            [item["source_id"] for item in restriction["bound_sources"]],
            [2, 4],
        )
        self.assertEqual(restriction["scanned_inventory_count"], 5)
        self.assertEqual(restriction["scan_classification_counts"], {"pending": 5})

    def test_two_and_three_exact_sources_work_within_workload_limit(self) -> None:
        inventory, sources = self._filesystem_inventory(
            [{} for _index in range(4)]
        )
        for count in (2, 3):
            with self.subTest(count=count):
                selected, restriction = review_orchestration._restricted_snapshot(
                    {
                        **self.payload,
                        "exact_source_paths": [
                            str(item["path"]) for item in sources[:count]
                        ],
                    },
                    inventory,
                )
                self.assertEqual(len(selected), count)
                self.assertEqual(len(restriction["selected_source_ids"]), count)

    def test_duplicate_exact_paths_are_deduplicated_without_duplicate_work(
        self,
    ) -> None:
        inventory, sources = self._filesystem_inventory([{}])
        path = str(sources[0]["path"])

        selected, restriction = review_orchestration._restricted_snapshot(
            {
                **self.payload,
                "exact_source_paths": [path, path, path.upper()],
            },
            inventory,
        )

        self.assertEqual([item["source_id"] for item in selected], [1])
        self.assertEqual(restriction["selected_source_ids"], [1])
        self.assertEqual(len(restriction["requested_paths"]), 1)

    def test_exact_source_enforces_root_and_recurse_boundaries(self) -> None:
        configured_root = self.root / "sources"
        configured_root.mkdir(parents=True, exist_ok=True)
        cases = (
            ("outside", self.root / "outside" / "source.mp4"),
            ("nested", configured_root / "nested" / "source.mp4"),
        )
        for name, path in cases:
            with self.subTest(name=name):
                inventory, sources = self._filesystem_inventory(
                    [{"path": path}],
                    configured_root=configured_root,
                    recurse=False,
                )
                with self.assertRaisesRegex(
                    review_orchestration.ExactSourceRestrictionError,
                    "outside the configured source roots or recurse boundary",
                ):
                    review_orchestration._restricted_snapshot(
                        {
                            **self.payload,
                            "exact_source_paths": [str(sources[0]["path"])],
                        },
                        inventory,
                    )

    def test_exact_source_follows_existing_lifecycle_selection_rules(self) -> None:
        inventory, sources = self._filesystem_inventory(
            [
                {"classification": "pending"},
                {"classification": "source_changed"},
                {"classification": "pending", "pending_batch_excluded": True},
                {"classification": "duplicate"},
                {"classification": "finalized_no_findings"},
            ]
        )
        selected, _restriction = review_orchestration._restricted_snapshot(
            {
                **self.payload,
                "exact_source_paths": [
                    str(sources[0]["path"]),
                    str(sources[1]["path"]),
                ],
            },
            inventory,
        )
        self.assertEqual([item["source_id"] for item in selected], [1, 2])

        for source in sources[2:]:
            with self.subTest(classification=source["classification"]):
                with self.assertRaisesRegex(
                    review_orchestration.ExactSourceRestrictionError,
                    "not eligible",
                ):
                    review_orchestration._restricted_snapshot(
                        {
                            **self.payload,
                            "exact_source_paths": [str(source["path"])],
                        },
                        inventory,
                    )

    def test_exact_source_rejects_limit_and_all_pending_combinations(self) -> None:
        inventory, sources = self._filesystem_inventory([{}, {}])
        paths = [str(item["path"]) for item in sources]

        with self.assertRaisesRegex(
            review_orchestration.ExactSourceRestrictionError,
            "exceeds the selected workload limit",
        ):
            review_orchestration._restricted_snapshot(
                {
                    **self.payload,
                    "workload_mode": "up_to_n",
                    "new_source_limit": 1,
                    "exact_source_paths": paths,
                },
                inventory,
            )
        with self.assertRaisesRegex(
            review_orchestration.ExactSourceRestrictionError,
            "cannot be combined with All pending",
        ):
            review_orchestration._restricted_snapshot(
                {
                    **self.payload,
                    "workload_mode": "all_pending",
                    "exact_source_paths": paths[:1],
                },
                inventory,
            )

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_unknown_exact_source_fails_before_preparation_without_fallback(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
    ) -> None:
        inventory, _sources = self._filesystem_inventory([{}, {}, {}])
        unknown = self.root / "sources" / "not-scanned.mp4"
        unknown.write_bytes(b"not in the fixed scan")
        refresh_queue.return_value = _queue(self.root)
        scan_inventory.return_value = inventory

        result = review_orchestration.process_from_request(
            {
                **self.payload,
                "exact_source_paths": [str(unknown)],
            }
        )

        self.assertEqual(result["operator_status"], "Needs attention")
        self.assertEqual(
            result["attention"]["code"],
            "exact_source_restriction_error",
        )
        prepare_selected.assert_not_called()
        journal = review_orchestration._read_journal(
            self.root / ".orchestration" / "active-run.json"
        )
        self.assertEqual(journal["status"], "needs_attention")
        self.assertEqual(
            journal["pending_exact_source_paths"],
            [str(unknown)],
        )

    @patch.object(
        review_orchestration,
        "_restricted_run_is_terminal",
        return_value=False,
    )
    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_only_exact_source_is_prepared_and_waiting_run_cannot_expand(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
        restricted_terminal,
    ) -> None:
        inventory, sources = self._filesystem_inventory([{}, {}, {}, {}])
        refresh_queue.return_value = _queue(self.root)
        scan_inventory.return_value = inventory
        prepare_selected.side_effect = self._prepare_result
        payload = {
            **self.payload,
            "exact_source_paths": [str(sources[2]["path"])],
        }

        first = review_orchestration.process_from_request(payload)
        second = review_orchestration.process_from_request(
            {
                **self.payload,
                "continuation": first["continuation"],
            }
        )

        self.assertEqual(first["run_state"]["status"], "waiting_external_review")
        self.assertEqual(second["run_state"]["status"], "waiting_external_review")
        self.assertEqual(first["run_state"]["selected_count"], 1)
        self.assertTrue(first["run_state"]["exact_source_restriction"])
        self.assertEqual(first["run_state"]["exact_source_restriction_count"], 1)
        self.assertEqual(prepare_selected.call_count, 1)
        prepared = prepare_selected.call_args.args[0]["selected_sources"]
        self.assertEqual([item["source_id"] for item in prepared], [3])
        self.assertEqual(scan_inventory.call_count, 1)
        journal = review_orchestration._read_journal(
            self.root / ".orchestration" / "active-run.json"
        )
        self.assertEqual(
            journal["exact_source_restriction"]["selected_source_ids"],
            [3],
        )
        restricted_terminal.return_value = True
        completed = review_orchestration.process_from_request(
            {
                **self.payload,
                "continuation": second["continuation"],
            }
        )
        self.assertEqual(completed["run_state"]["status"], "complete")
        self.assertFalse(
            (self.root / ".orchestration" / "active-run.json").exists()
        )

    @patch.object(
        review_orchestration,
        "_restricted_run_is_terminal",
        return_value=False,
    )
    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_stop_and_relaunch_restore_same_restricted_source_ids(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
        _restricted_terminal,
    ) -> None:
        inventory, sources = self._filesystem_inventory([{}, {}, {}])
        refresh_queue.return_value = _queue(self.root)
        scan_inventory.return_value = inventory
        prepare_selected.side_effect = self._prepare_result
        stop_payload = {
            **self.payload,
            "exact_source_paths": [str(sources[1]["path"])],
            "stop_requested": lambda: True,
        }

        paused = review_orchestration.process_from_request(stop_payload)
        resumed = review_orchestration.process_from_request(
            {
                **self.payload,
                "continuation": paused["continuation"],
            }
        )

        self.assertEqual(paused["run_state"]["status"], "paused_after_current")
        self.assertEqual(paused["run_state"]["completed_count"], 0)
        self.assertEqual(resumed["run_state"]["status"], "waiting_external_review")
        self.assertEqual(
            [item["source_id"] for item in prepare_selected.call_args.args[0]["selected_sources"]],
            [2],
        )
        self.assertEqual(scan_inventory.call_count, 1)
        self.assertEqual(
            scan_inventory.call_args.args[0]["exact_source_paths"],
            [str(sources[1]["path"])],
        )

    @patch.object(review_orchestration, "_prepare_selected")
    @patch.object(review_orchestration, "_scan_inventory")
    @patch.object(review_orchestration, "_refresh_queue")
    def test_active_restricted_run_rejects_changed_source_request(
        self,
        refresh_queue,
        scan_inventory,
        prepare_selected,
    ) -> None:
        inventory, sources = self._filesystem_inventory([{}, {}])
        refresh_queue.return_value = _queue(self.root)
        scan_inventory.return_value = inventory
        paused = review_orchestration.process_from_request(
            {
                **self.payload,
                "exact_source_paths": [str(sources[0]["path"])],
                "stop_requested": lambda: True,
            }
        )

        result = review_orchestration.process_from_request(
            {
                **self.payload,
                "continuation": paused["continuation"],
                "exact_source_paths": [str(sources[1]["path"])],
            }
        )

        self.assertEqual(result["operator_status"], "Needs attention")
        self.assertEqual(
            result["attention"]["code"],
            "exact_source_restriction_error",
        )
        prepare_selected.assert_not_called()
        journal = review_orchestration._read_journal(
            self.root / ".orchestration" / "active-run.json"
        )
        self.assertEqual(
            journal["pending_exact_source_paths"],
            [str(sources[0]["path"])],
        )

    @patch.object(review_orchestration, "_refresh_queue")
    def test_restriction_and_workload_are_journaled_before_existing_attention(
        self,
        refresh_queue,
    ) -> None:
        inventory, sources = self._filesystem_inventory([{}, {}, {}])
        refresh_queue.return_value = _queue(
            self.root,
            attention=[
                {
                    "code": "stable_invalid_external_return",
                    "message": "Correct the invalid external return.",
                }
            ],
        )
        payload = {
            **self.payload,
            "workload_mode": "up_to_n",
            "new_source_limit": 1,
            "exact_source_paths": [str(sources[1]["path"])],
        }

        result = review_orchestration.process_from_request(payload)

        self.assertEqual(result["operator_status"], "Needs attention")
        journal = review_orchestration._read_journal(
            self.root / ".orchestration" / "active-run.json"
        )
        self.assertEqual(
            journal["pending_exact_source_paths"],
            [str(sources[1]["path"])],
        )
        self.assertEqual(journal["workload"]["mode"], "up_to_n")
        self.assertEqual(journal["workload"]["requested_limit"], 1)

        review_orchestration._initialise_pending_workload(
            journal,
            self.payload,
            inventory,
        )
        self.assertEqual(journal["workload"]["mode"], "up_to_n")
        self.assertEqual(journal["workload"]["requested_limit"], 1)
        self.assertEqual(
            journal["exact_source_restriction"]["selected_source_ids"],
            [2],
        )
        self.assertEqual(
            [item["source_id"] for item in journal["snapshot"]],
            [2],
        )

    @patch.object(review_orchestration, "_refresh_queue")
    def test_restriction_is_journaled_before_existing_audio_choice(
        self,
        refresh_queue,
    ) -> None:
        inventory, sources = self._filesystem_inventory([{}])
        batch_path = self.root / "batches" / "batch-audio"
        batch_path.mkdir(parents=True)
        (batch_path / "batch-manifest.json").write_text(
            json.dumps(
                {
                    "blocked_sources": [
                        {
                            "source_id": 41,
                            "state": "needs_audio_confirmation",
                            "layout_fingerprint": "audible-layout",
                            "audibility_contract_version": 1,
                            "audio_audibility_state": "audible_candidates",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        refresh_queue.return_value = _queue(
            self.root,
            batches=[
                {
                    "batch_id": "batch-audio",
                    "batch_path": str(batch_path),
                    "status": "needs_audio_confirmation",
                }
            ],
        )

        result = review_orchestration.process_from_request(
            {
                **self.payload,
                "exact_source_paths": [str(sources[0]["path"])],
            }
        )

        self.assertEqual(result["operator_status"], "Needs audio choice")
        journal = review_orchestration._read_journal(
            self.root / ".orchestration" / "active-run.json"
        )
        self.assertEqual(
            journal["pending_exact_source_paths"],
            [str(sources[0]["path"])],
        )

    def test_legacy_audio_choice_is_reinspected_before_any_track_can_be_offered(
        self,
    ) -> None:
        batch_path = self.root / "batches" / "legacy-audio"
        batch_path.mkdir(parents=True)
        manifest_path = batch_path / "batch-manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "blocked_sources": [
                        {
                            "source_id": 1,
                            "state": "needs_audio_confirmation",
                            "layout_fingerprint": "legacy-layout",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        queue = _queue(
            self.root,
            batches=[
                {
                    "batch_id": "legacy-audio",
                    "batch_path": str(batch_path),
                    "status": "needs_audio_confirmation",
                }
            ],
        )
        self.assertIsNone(review_orchestration._audio_choice(queue))

        current = json.loads(manifest_path.read_text(encoding="utf-8"))
        current["blocked_sources"][0].update(
            {
                "audibility_contract_version": 1,
                "audio_audibility_state": "audible_candidates",
            }
        )
        manifest_path.write_text(json.dumps(current), encoding="utf-8")
        choice = review_orchestration._audio_choice(queue)
        self.assertEqual(choice["source_id"], 1)
        self.assertEqual(choice["layout_fingerprint"], "legacy-layout")


if __name__ == "__main__":
    unittest.main()
