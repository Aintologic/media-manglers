"""No Inbox write stays open while a recording or a retained file is read (224, Wave B1, design 2.3).

When the Inbox's records move into the library (Wave B2), a long Inbox write would hold up every other writer
of the library: a raw bin scan, a run starting, a Never-use mark. So scan, preparation and finalization's
commit read, hash and copy first, and then write in one short transaction.

Each test probes the ledger's own write lock at the moment a file is read: another connection asks for the
write lock and is refused only while a write transaction is open. The probe needs nothing from the code under
test, so the same tests show the old code holding the lock (it did, across every hash, copy and check).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from media_manglers.core import review_finalization, review_inbox, review_ledger, review_preparation
import pytest
from tests import inbox_library  # noqa: E402

# 224 (Wave B2b): the Inbox's records are in this test's library, moved in (nothing to move).
pytestmark = pytest.mark.inbox_moved


def _write_lock_held(ledger: Path) -> bool:
    """Whether a write transaction is open on the Inbox's records right now, in any connection: in the library,
    which holds them since 224 (Wave B2b), whatever ``ledger`` names."""

    probe = sqlite3.connect(inbox_library.library_file(), timeout=0)
    try:
        try:
            probe.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc):
                return True
            raise
        probe.rollback()
        return False
    finally:
        probe.close()


class ScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sources = self.root / "sources"
        self.sources.mkdir()
        self.ledger = self.root / "inbox" / "review-ledger.sqlite"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _recording(self, index: int) -> Path:
        path = self.sources / f"recording-{index}.mp4"
        path.write_bytes((f"recording {index} " * 5000).encode("ascii"))
        return path

    def test_no_write_transaction_is_open_while_a_recording_is_hashed(self) -> None:
        for index in range(3):
            self._recording(index)
        base = {"source_folders": [str(self.sources)], "ledger_path": str(self.ledger)}
        review_inbox.scan_from_request(base)
        self._recording(3)
        seen: list[tuple[str, str, bool]] = []

        def sampled(path: Path) -> str:
            seen.append(("sampled", path.name, _write_lock_held(self.ledger)))
            return review_inbox.sampled_sha256_file(path)

        def full(path: Path) -> str:
            seen.append(("full", path.name, _write_lock_held(self.ledger)))
            return review_inbox.full_sha256_file(path)

        result = review_inbox.scan_from_request({
            **base, "dedupe_mode": "Full", "full_scan_acknowledged": True, "sample_hasher": sampled, "full_hasher": full,
        })
        self.assertEqual(result["inventory_count"], 4)
        self.assertEqual(len([item for item in seen if item[0] == "full"]), 4)
        self.assertEqual([item for item in seen if item[2]], [], "a recording was hashed inside a write transaction")
        # Every recording's writes reached the ledger.
        connection = inbox_library.connect()
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM inbox_sources WHERE content_sha256 IS NOT NULL").fetchone()[0], 4)
        finally:
            connection.close()

    def test_a_fast_scan_of_unchanged_recordings_reads_none_of_them_and_still_records_them_seen(self) -> None:
        for index in range(3):
            self._recording(index)
        base = {"source_folders": [str(self.sources)], "ledger_path": str(self.ledger)}
        review_inbox.scan_from_request(base)

        def never(_path: Path) -> str:
            raise AssertionError("An unchanged recording must not be read by a Fast scan.")

        connection = inbox_library.connect()
        try:
            before = {row[0]: row[1] for row in connection.execute("SELECT location_id, last_seen_utc FROM inbox_source_locations")}
        finally:
            connection.close()
        time.sleep(0.01)
        review_inbox.scan_from_request({**base, "sample_hasher": never, "full_hasher": never})
        connection = inbox_library.connect()
        try:
            after = {row[0]: row[1] for row in connection.execute("SELECT location_id, last_seen_utc FROM inbox_source_locations")}
        finally:
            connection.close()
        self.assertEqual(set(after), set(before))
        self.assertTrue(all(after[key] > before[key] for key in before), "the seen times were committed")


class PreparationTests(unittest.TestCase):
    def setUp(self) -> None:
        # Imported here, so its own tests are not collected a second time from this file.
        from tests.test_review_inbox_preparation import ReviewInboxPreparationTests  # noqa: PLC0415

        self.fixture = ReviewInboxPreparationTests(methodName="runTest")
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def _state(self, source_id: int) -> tuple[str, str]:
        rows = self.fixture.query(
            "SELECT s.lifecycle_state, bs.state FROM inbox_sources s JOIN inbox_batch_sources bs ON bs.source_id = s.source_id "
            "WHERE s.source_id = ?", (source_id,))
        return rows[0]

    def test_no_write_transaction_is_open_while_the_recording_is_copied_and_checked(self) -> None:
        self.fixture.make_sources(1)
        ledger = self.fixture.ledger
        scan = review_inbox.scan_from_request(self.fixture.payload())
        source_id = int(scan["selected_sources"][0]["source_id"])
        seen: list[tuple[str, bool]] = []
        real_hash = review_ledger.sha256_file

        def copy(source: Path, target: Path) -> dict:
            seen.append(("copy", _write_lock_held(ledger)))
            return review_preparation.stream_verified_copy(source, target)

        def hashed(path: Path) -> str:
            seen.append((f"hash {path.name}", _write_lock_held(ledger)))
            return real_hash(path)

        payload = self.fixture.payload(scan_result=scan, selected_source_ids=[source_id],
                                       preallocated_batch_id="batch-short-writes", copy_file=copy)
        # Every other step that reads, decodes, transcribes or renders the recording, as the fixture supplies them.
        steps = ("media_probe", "audio_extractor", "transcriber", "visual_renderer")
        for step in steps:
            def probed(*args, _real=payload[step], _step=step, **kwargs):
                seen.append((_step, _write_lock_held(ledger)))
                return _real(*args, **kwargs)

            payload[step] = probed
        with mock.patch.object(review_ledger, "sha256_file", side_effect=hashed):
            result = review_preparation.prepare_selected_from_request(payload)
        self.assertEqual(result["status"], "awaiting_external_review")
        self.assertLessEqual({"copy", *steps}, {name for name, _held in seen})
        self.assertEqual([item for item in seen if item[1]], [], "the recording was read inside a write transaction")

    def test_a_crash_while_copying_leaves_preparing_committed_and_the_next_run_finishes(self) -> None:
        self.fixture.make_sources(1)
        scan = review_inbox.scan_from_request(self.fixture.payload())
        source_id = int(scan["selected_sources"][0]["source_id"])
        batch_id = "batch-power-cut"

        class PowerCut(BaseException):
            pass

        def cut_while_copying(source: Path, target: Path) -> dict:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes()[:8])
            raise PowerCut("the power went off while the recording was copied")

        # A real crash runs no clean-up, so nothing is removed on the way out.
        with mock.patch.object(review_preparation, "_safe_remove"), self.assertRaises(PowerCut):
            review_preparation.prepare_selected_from_request(self.fixture.payload(
                scan_result=scan, selected_source_ids=[source_id], preallocated_batch_id=batch_id,
                copy_file=cut_while_copying))

        # "preparing" was committed before the copy started, and its attempt-state file is there for recovery.
        self.assertEqual(self._state(source_id), ("preparing", "preparing"))
        states = sorted((self.fixture.root / "batches" / batch_id / ".staging").glob("*/attempt-state.json"))
        self.assertEqual(len(states), 1)
        state = json.loads(states[0].read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "preparing")
        self.assertEqual(self.fixture.query("SELECT status FROM inbox_attempts WHERE source_id = ?", (source_id,)),
                         [("preparing",)])
        # The crashed process has gone: a process that has ended, whose number Windows cannot give out again
        # while this test holds it.
        ended = subprocess.Popen([sys.executable, "-c", "pass"])
        ended.wait(30)
        state["process_id"] = ended.pid
        states[0].write_text(json.dumps(state), encoding="utf-8")

        resumed = review_inbox.scan_from_request(self.fixture.payload())
        result = review_preparation.prepare_selected_from_request(self.fixture.payload(
            scan_result=resumed, resume_batch_id=batch_id, selected_source_ids=[]))

        self.assertEqual(result["status"], "awaiting_external_review")
        self.assertEqual(self._state(source_id), ("awaiting_external_review", "awaiting_external_review"))
        self.assertEqual(self.fixture.query("SELECT status FROM inbox_attempts WHERE source_id = ? ORDER BY attempt_id",
                                            (source_id,)), [("recovered_restart_required",), ("prepared",)])
        self.assertEqual(self.fixture.query("SELECT COUNT(*) FROM inbox_batch_sources WHERE batch_id = ?", (batch_id,)), [(1,)])
        self.assertEqual(self.fixture.query("PRAGMA foreign_key_check"), [])
        # The partial copy from the crash was removed by the recovery, after its commit.
        self.assertFalse(any(self.fixture.scratch.rglob("source.mp4")))

    def _recover_in_a_process_of_its_own(self, batch: Path) -> list[str]:
        """recover_staging run in a separate process with no console, so that a Ctrl+C the old check would
        send cannot reach this test run: a regression then fails here instead of ending the run."""

        source = str(Path(review_preparation.__file__).resolve().parents[2])
        script = "\n".join([
            "import json, sys",
            f"sys.path.insert(0, {source!r})",
            "from pathlib import Path",
            "from media_manglers.core import review_preparation",
            "actions = review_preparation.recover_staging(Path(sys.argv[1]), Path(sys.argv[2]))",
            "print(json.dumps([item['classification'] for item in actions]))",
        ])
        completed = subprocess.run(
            [sys.executable, "-c", script, str(batch), str(self.fixture.scratch)],
            capture_output=True, text=True, timeout=120,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout.strip().splitlines()[-1])

    def test_recovery_never_ends_a_program_that_has_a_crashed_attempts_process_number(self) -> None:
        # The old check, os.kill(pid, 0), sends Ctrl+C on Windows (signal 0 is CTRL_C_EVENT) to the processes
        # sharing the console: run against the old code in this test process, it ended the whole test run and
        # the PowerShell window it ran in. A live attempt must instead be left alone and reported still running.
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            batch = self.fixture.root / "batches" / "batch-live"
            review_preparation._atomic_json(batch / ".staging" / "attempt-1" / "attempt-state.json",
                                            {"status": "preparing", "process_id": child.pid})
            self.assertEqual(self._recover_in_a_process_of_its_own(batch), ["still_live"])
            time.sleep(0.2)
            self.assertIsNone(child.poll(), "the recovery ended a running program")
        finally:
            child.kill()
            child.wait(10)

    def test_a_program_that_was_given_a_crashed_attempts_number_later_is_not_that_attempt(self) -> None:
        # After a crash Windows can give the number to another program; it started after the attempt last
        # wrote its state, so the attempt is stale and the batch is not held up waiting for that program.
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            batch = self.fixture.root / "batches" / "batch-reused"
            state = batch / ".staging" / "attempt-1" / "attempt-state.json"
            review_preparation._atomic_json(state, {"status": "preparing", "process_id": child.pid})
            an_hour_ago = time.time() - 3600
            os.utime(state, (an_hour_ago, an_hour_ago))
            actions = review_preparation.recover_staging(batch, self.fixture.scratch)
            self.assertEqual([item["classification"] for item in actions], ["stale_restart_required"])
            self.assertIsNone(child.poll(), "the other program was left alone")
        finally:
            child.kill()
            child.wait(10)


class FinalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        from tests.test_review_inbox_finalization import ReviewInboxFinalizationTests  # noqa: PLC0415

        self.fixture = ReviewInboxFinalizationTests(methodName="runTest")
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def test_no_write_transaction_is_open_while_the_retained_history_is_checked(self) -> None:
        self.fixture._accept()
        preview = self.fixture._preview()
        seen: list[bool] = []
        real_verify = review_finalization._verify_history

        def verify(history: Path, plan_sha: str, identity: str) -> str:
            seen.append(_write_lock_held(self.fixture.ledger))
            return real_verify(history, plan_sha, identity)

        with mock.patch.object(review_finalization, "_verify_history", side_effect=verify):
            result = self.fixture._finalize(preview)
        self.assertEqual(result["status"], "finalized_no_findings")
        self.assertGreater(len(seen), len(preview["sources"]), "the commit checks the history again")
        self.assertNotIn(True, seen, "retained history was hashed inside a write transaction")


if __name__ == "__main__":
    unittest.main()
