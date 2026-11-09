"""Review Media Inbox's store (224): one opener, one folder rule, one lock.

Wave B1 laid the groundwork and Wave B2b moved the records into the library: every Inbox module gets its
connection from ``inbox_records`` and never opens one itself; the store opens the library, and a database file
of its own only for the old ledger the one-time move reads; the Inbox opens nothing until that move is complete;
a reader never writes, makes or registers anything (F4); an action on records that are not there changes
nothing (F5); every command-line action that writes takes the Inbox's lock and is refused in one plain line while
another run holds it; the PowerShell host works the workspace out the same way and passes its own lock to the
helpers it calls inside its Process loop.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
import unittest.mock

from media_manglers.cli import INBOX_EXISTING_RECORDS, INBOX_WRITERS, main
from media_manglers.contracts import CommandEnvelope, read_json_file, write_json_file
from media_manglers.core import (
    inbox_records,
    recording_records,
    review_findings,
    review_inbox,
    review_ledger,
    review_orchestration,
    review_queue,
    review_targeted_evidence,
)

from tests import inbox_library  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE = REPO_ROOT / "src" / "media_manglers" / "core"
SCRIPT = REPO_ROOT / "Video Mangler.ps1"
INBOX_MODULES = sorted(path.name for path in CORE.glob("review_*.py"))


def _registered() -> Path | None:
    connection = inbox_library.connect(read_only=True)
    try:
        return inbox_records.registered_folder(connection)
    finally:
        connection.close()


def _receipts() -> int:
    connection = inbox_library.connect(read_only=True)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM legacy_imports").fetchone()[0])
    finally:
        connection.close()


class OneOpenerTests(unittest.TestCase):
    def test_no_inbox_module_opens_a_database_or_calls_the_old_connector(self) -> None:
        self.assertGreaterEqual(len(INBOX_MODULES), 10)
        for name in INBOX_MODULES:
            text = (CORE / name).read_text(encoding="utf-8")
            with self.subTest(module=name):
                self.assertNotIn("sqlite3.connect(", text)
                self.assertIsNone(re.search(r"\bconnect_ledger\b", text))
                self.assertIsNone(re.search(r"\bensure_ledger_schema\b", text))
                self.assertIsNone(re.search(r"\bfrom\s+sqlite3\s+import\b", text))

    def test_the_old_connector_and_the_lock_class_are_gone_from_their_old_homes(self) -> None:
        self.assertFalse(hasattr(review_ledger, "connect_ledger"))
        self.assertFalse(hasattr(review_ledger, "ensure_ledger_schema"))
        self.assertFalse(hasattr(review_orchestration, "_ProcessLock"))
        self.assertFalse(hasattr(review_orchestration, "_CoordinatorOwnedLock"))

    def test_the_store_opens_a_file_of_its_own_only_for_the_old_ledger_the_move_reads(self) -> None:
        text = (CORE / "inbox_records.py").read_text(encoding="utf-8")
        tree = ast.parse(text)
        opening = sorted({node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                          and "sqlite3.connect(" in (ast.get_source_segment(text, node) or "")})
        # 224 (Wave B2b): the records are opened through the library's front door; only the move's two reads of
        # the old ledger file (and its checked copy) open a file here. Backups are the shared checked copy.
        self.assertEqual(opening, ["read_only_file", "settle_file"])


class OneSafeWriterTests(unittest.TestCase):
    # B1.4: the Inbox's seven safe-write copies hand the replace to safe_write, with their own bytes.
    WRITERS = {
        "review_queue": ("_atomic_bytes", b"queue\n", b"queue\n"),
        "review_findings": ("_atomic_bytes", b"findings\n", b"findings\n"),
        "review_results": ("_atomic_bytes", b"results\n", b"results\n"),
        "review_relocation": ("_atomic_bytes", b"relocation\n", b"relocation\n"),
        "review_orchestration": ("_atomic_json", {"b": 1, "a": "x"}, review_orchestration._canonical_bytes({"b": 1, "a": "x"})),
        "review_finalization": ("_atomic_json", {"b": 1, "a": "x"}, None),
        "review_preparation": ("_atomic_json", {"b": 1, "a": "x"}, None),
    }

    def test_each_of_the_seven_writes_through_safe_write_with_its_own_bytes(self) -> None:
        import importlib

        from media_manglers.core import safe_write

        text = (json.dumps({"b": 1, "a": "x"}, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        text = text.replace(b"\n", os.linesep.encode("ascii"))
        with tempfile.TemporaryDirectory() as folder:
            for name, (helper, value, expected) in self.WRITERS.items():
                module = importlib.import_module(f"media_manglers.core.{name}")
                target = Path(folder) / f"{name}.out"
                with self.subTest(module=name), \
                        unittest.mock.patch.object(safe_write, "write_bytes", wraps=safe_write.write_bytes) as raw, \
                        unittest.mock.patch.object(safe_write, "write_text", wraps=safe_write.write_text) as written:
                    getattr(module, helper)(target, value)
                    self.assertEqual(raw.call_count + written.call_count, 1)
                    self.assertEqual(target.read_bytes(), expected if expected is not None else text)

    def test_no_inbox_module_keeps_a_temporary_file_writer_of_its_own(self) -> None:
        # Each old copy wrote a ".tmp" sibling and replaced the file itself; a copy put back would show it.
        for name in INBOX_MODULES:
            with self.subTest(module=name):
                self.assertIsNone(re.search(r"\.tmp\b", (CORE / name).read_text(encoding="utf-8")))


class WorkspaceTests(unittest.TestCase):
    def test_one_answer_from_settings_a_request_its_cli_part_and_a_path(self) -> None:
        ledger = Path("C:/Evidence/inbox/review-ledger.sqlite")
        expected = ledger.parent
        self.assertEqual(inbox_records.workspace({"review_ledger_path": str(ledger)}), expected)
        self.assertEqual(inbox_records.workspace({"ledger_path": f"  {ledger}  "}), expected)
        self.assertEqual(inbox_records.workspace({"cli": {"ledger_path": str(ledger)}}), expected)
        self.assertEqual(inbox_records.workspace(ledger), expected)
        self.assertEqual(inbox_records.workspace(str(ledger)), expected)
        # 224 (Wave B2b, Q3): the Inbox folder setting, or a request that names the folder itself.
        self.assertEqual(inbox_records.workspace({"review_inbox_folder": str(expected)}), expected)
        self.assertEqual(inbox_records.workspace({"inbox_folder": f"  {expected}  "}), expected)
        self.assertEqual(inbox_records.workspace({"cli": {"inbox_folder": str(expected)}}), expected)
        self.assertEqual(inbox_records.ledger_file({"review_inbox_folder": str(expected)}), ledger)
        self.assertEqual(inbox_records.workspace({"review_inbox_folder": str(expected),
                                                  "review_ledger_path": "C:/Elsewhere/review-ledger.sqlite"}),
                         expected, "the Inbox folder wins over the old ledger setting")
        self.assertEqual(inbox_records.orchestration_folder(ledger), expected / ".orchestration")
        self.assertEqual(inbox_records.lock_file(expected), expected / ".orchestration" / "process.lock")

    def test_every_place_that_worked_the_folder_out_gives_the_same_answer(self) -> None:
        from media_manglers_workbench.main_settings import run_output_folder

        ledger = Path("C:/Evidence/inbox/review-ledger.sqlite")
        self.assertEqual(review_queue.queue_root_for_ledger(str(ledger)), inbox_records.workspace(ledger))
        self.assertEqual(review_orchestration._orchestration_paths(ledger)["lock"],
                         inbox_records.lock_file(inbox_records.workspace(ledger)))
        for action in ("Process", "Prepare"):
            self.assertEqual(run_output_folder({"review_inbox_folder": str(ledger.parent),
                                                "review_inbox_action": action}, inbox=True),
                             os.path.normpath(str(inbox_records.workspace({"review_inbox_folder": str(ledger.parent)}))))

    def test_a_blank_ledger_or_a_folder_name_is_refused(self) -> None:
        for value in ("", "   ", "."):
            with self.subTest(value=value), self.assertRaises(ValueError):
                inbox_records.workspace(value)
        with self.assertRaises(ValueError):
            inbox_records.workspace({"review_ledger_path": ""})


class ReadersNeverWriteTests(unittest.TestCase):
    """F4 in the library (224, Wave B2b): a reader never writes, makes or registers anything."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.ledger = self.root / "inbox" / "review-ledger.sqlite"
        recording_records.connect(backup=False).close()

    def tearDown(self) -> None:
        inbox_records.release_all()
        self.temporary.cleanup()

    def test_an_inbox_folder_with_no_records_reads_none_and_nothing_is_made_or_registered(self) -> None:
        inbox_library.ready()
        self.assertIsNone(inbox_records.connect_read_only(self.ledger))
        self.assertIsNone(_registered())
        self.assertFalse(self.ledger.parent.exists())

    def test_reading_existing_records_changes_nothing_and_takes_no_write_lock(self) -> None:
        inbox_library.ready(self.ledger)
        inbox_records.release_all()
        before = inbox_library.fingerprint()
        connection = inbox_records.connect_read_only(self.ledger)
        assert connection is not None
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM inbox_sources").fetchone()[0], 0)
            # Another writer can take the library's write lock while the reader is open.
            other = sqlite3.connect(inbox_library.library_file(), timeout=0)
            try:
                other.execute("BEGIN IMMEDIATE")
                other.rollback()
            finally:
                other.close()
            with self.assertRaises(sqlite3.OperationalError) as refused:
                connection.execute(
                    "INSERT INTO inbox_sources (provisional_identity, size_bytes, lifecycle_state, first_seen_utc, "
                    "updated_utc) VALUES ('provisional:x', 1, 'pending', 'now', 'now')")
            self.assertIn("readonly", str(refused.exception).replace(" ", ""))
        finally:
            connection.close()
        self.assertEqual(inbox_library.fingerprint(), before)
        self.assertFalse(self.ledger.parent.exists(), "registering the folder made no folder")

    def test_a_library_a_newer_version_moved_on_is_refused_and_left_alone(self) -> None:
        inbox_library.ready(self.ledger)
        inbox_records.release_all()
        raw = inbox_library.connect()
        raw.execute("UPDATE schema_metadata SET value = ? WHERE key = 'schema_version'",
                    (str(recording_records.SCHEMA_VERSION + 1),))
        raw.commit()
        raw.close()
        before = inbox_library.library_file().read_bytes()
        with self.assertRaises(recording_records.LibraryTooNew):
            inbox_records.connect_read_only(self.ledger)
        with self.assertRaises(recording_records.LibraryTooNew):
            inbox_records.connect(self.ledger)
        self.assertEqual(inbox_library.library_file().read_bytes(), before)

    def test_before_the_move_the_inbox_opens_nothing_and_writes_nothing(self) -> None:
        # No move receipt: a helper started before the first new Workbench start (design 4.1).
        with self.assertRaises(inbox_records.InboxNotReady) as refused:
            inbox_records.connect_read_only(self.ledger)
        self.assertEqual(str(refused.exception), inbox_records.NOT_MOVED_YET)
        with self.assertRaises(inbox_records.InboxNotReady):
            inbox_records.connect(self.ledger)
        with self.assertRaises(inbox_records.InboxNotReady):
            with inbox_records.writing(self.ledger):
                self.fail("the write ran")
        self.assertEqual(_receipts(), 0)
        self.assertIsNone(_registered())
        self.assertFalse(self.ledger.parent.exists())
        self.assertFalse(recording_records.inbox_reviewed(inbox_library.connect(read_only=True)).known)

    def test_settle_does_nothing_since_the_records_are_in_the_library(self) -> None:
        inbox_library.ready()
        before = inbox_library.fingerprint()
        self.assertIsNone(inbox_records.settle(self.ledger))
        self.assertEqual(inbox_library.fingerprint(), before)
        self.assertFalse(self.ledger.parent.exists())

    def test_the_move_reads_an_old_ledger_on_a_network_share_too(self) -> None:
        self.ledger.parent.mkdir(parents=True)
        raw = sqlite3.connect(self.ledger)
        raw.execute("CREATE TABLE sources (source_id INTEGER PRIMARY KEY)")
        raw.commit()
        raw.close()
        drive, rest = os.path.splitdrive(str(self.ledger.resolve()))
        share = Path(rf"\\localhost\{drive.rstrip(':')}$" + rest)
        if os.name != "nt" or not share.exists():
            self.skipTest("this PC's administrative share is not reachable")
        connection = inbox_records.read_only_file(share)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 0)
        finally:
            connection.close()

    def test_an_action_that_needs_its_records_makes_and_registers_nothing(self) -> None:
        inbox_library.ready()
        with self.assertRaises(inbox_records.LedgerMissing) as refused:
            inbox_records.connect(self.ledger, must_exist=True)
        self.assertEqual(str(refused.exception),
                         f"There are no Review Media Inbox records for {self.ledger.parent}, so nothing was changed.")
        self.assertIsNone(_registered())
        self.assertFalse(self.ledger.parent.exists())

    def test_every_inbox_reader_leaves_an_inbox_with_no_records_as_it_was(self) -> None:
        # F4: these used to make an empty ledger (and its folder) just by reading.
        inbox_library.ready()
        before = inbox_library.fingerprint()
        self.assertEqual(review_inbox.list_pending_batches(self.ledger), [])
        self.assertEqual(review_queue._batch_rows(self.ledger), ([], 0))
        with self.assertRaises(review_targeted_evidence.TargetedEvidenceError):
            review_targeted_evidence._resolve_batch_root(self.ledger, "batch-x")
        with self.assertRaises(ValueError):
            review_ledger.validate_from_request({"ledger_path": str(self.ledger)})
        self.assertFalse(review_orchestration._restricted_run_is_terminal(
            self.ledger, {"exact_source_restriction": {"selected_source_ids": [1]}}))
        self.assertEqual(review_orchestration._preliminary_sha(self.ledger, "batch-x"), "")
        connection = inbox_library.connect(read_only=True)
        try:
            verdicts = recording_records.inbox_reviewed(connection)
        finally:
            connection.close()
        self.assertTrue(verdicts.known)
        self.assertEqual(verdicts.hashes, set())
        self.assertEqual(inbox_library.fingerprint(), before)
        self.assertIsNone(_registered())
        self.assertFalse(self.ledger.exists())
        self.assertFalse(self.ledger.parent.exists())

    def test_the_recent_duration_reader_closes_its_connection_when_the_query_fails(self) -> None:
        # F4: the connection is closed in a finally, so a failed read never keeps the library open.
        inbox_library.ready(self.ledger)
        inbox_records.release_all()
        raw = inbox_library.connect()
        raw.execute("DROP TABLE inbox_attempts")
        raw.commit()
        raw.close()
        opened: list[sqlite3.Connection] = []
        real_open = recording_records.connect_read_only

        def tracked(*args: object, **kwargs: object) -> sqlite3.Connection | None:
            connection = real_open(*args, **kwargs)
            if connection is not None:
                opened.append(connection)
            return connection

        with unittest.mock.patch.object(recording_records, "connect_read_only", side_effect=tracked):
            estimate = review_orchestration._recent_duration_estimate(self.ledger, {}, 1)
        self.assertIsNone(estimate["estimated_seconds"])
        self.assertEqual(len(opened), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            opened[0].execute("SELECT 1")  # closed, although its query failed


class FindingsImportStopsWithoutALedgerTests(unittest.TestCase):
    def test_an_inbox_folder_with_no_records_is_refused_before_anything_is_copied_or_written(self) -> None:
        # F5: the import used to go on to its write, leaving an empty ledger and a validation record behind.
        inbox_library.ready()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            batch = root / "batches" / "batch-x"
            batch.mkdir(parents=True)
            findings = root / "preliminary-findings.json"
            findings.write_text('{"batch_id": "batch-x", "findings": []}\n', encoding="utf-8")
            ledger = root / "review-ledger.sqlite"
            before = inbox_library.fingerprint()
            result = review_findings.import_from_request({
                "ledger_path": str(ledger), "batch_path": str(batch), "expected_batch_id": "batch-x",
                "findings_path": str(findings),
            })
            self.assertEqual(result["status"], "rejected")
            self.assertIn(review_findings.LEDGER_MISSING_PROBLEM, result["problems"])
            self.assertFalse(ledger.exists())
            self.assertFalse((batch / "imports").exists())
            self.assertEqual(inbox_library.fingerprint(), before)
            self.assertIsNone(_registered())


class LibraryReadOnlyGuardTests(unittest.TestCase):
    def test_the_read_only_library_refuses_a_library_a_newer_build_moved_on(self) -> None:
        # F7: the read-only opener now has the same newer-version guard as the normal one.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            recording_records.connect(root, backup=False).close()
            raw = sqlite3.connect(recording_records.database_path(root))
            raw.execute("UPDATE schema_metadata SET value = ? WHERE key = 'schema_version'",
                        (str(recording_records.SCHEMA_VERSION + 1),))
            raw.commit()
            raw.close()
            with self.assertRaises(recording_records.LibraryTooNew):
                recording_records.connect_read_only(root)
            self.assertEqual(recording_records.list_recordings(root=root), [])


class OneLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.ledger = self.root / "inbox" / "review-ledger.sqlite"
        self.sources = self.root / "sources"
        self.sources.mkdir()
        (self.sources / "clip.mp4").write_bytes(b"synthetic recording")
        inbox_library.ready()

    def tearDown(self) -> None:
        inbox_records.release_all()
        self.temporary.cleanup()

    def _cli(self, command: str, payload: dict) -> tuple[int, dict]:
        request = self.root / f"{command}.request.json"
        result = self.root / f"{command}.result.json"
        write_json_file(request, CommandEnvelope(payload=payload).to_dict())
        code = main([command, "--request-file", str(request), "--result-file", str(result)])
        return code, read_json_file(result)

    def _scan_payload(self, **extra: object) -> dict:
        return {"source_folders": [str(self.sources)], "ledger_path": str(self.ledger), **extra}

    def test_a_command_line_writer_is_refused_in_one_plain_line_while_another_run_holds_the_lock(self) -> None:
        inbox_library.ready(self.ledger)
        before = inbox_library.fingerprint()
        with inbox_records.process_lock(self.ledger) as held:
            self.assertTrue(held.acquired)
            code, result = self._cli("review-media-inbox-scan", self._scan_payload())
        self.assertEqual(code, 1)
        self.assertEqual(result["error"], "The Inbox is busy with another run. Try again when it finishes.")
        self.assertEqual(inbox_library.fingerprint(), before)

    def test_every_writer_is_refused_and_every_reader_is_not(self) -> None:
        inbox_library.ready(self.ledger)
        plan = self.root / "plan.json"
        plan.write_text(json.dumps({"ledger_path": str(self.ledger)}), encoding="utf-8")
        writers = {
            "review-media-inbox-scan": self._scan_payload(),
            "review-media-inbox-prepare": self._scan_payload(evidence_root=str(self.root), scratch_root=str(self.root)),
            "review-media-inbox-repair": {"ledger_path": str(self.ledger), "batch_id": "b", "scratch_root": str(self.root)},
            "review-media-inbox-import-preliminary": {"ledger_path": str(self.ledger), "expected_batch_id": "b"},
            "review-media-inbox-targeted-plan": {"ledger_path": str(self.ledger), "expected_batch_id": "b"},
            "review-media-inbox-targeted-complete": {"plan_path": str(plan), "plan_sha256": "0" * 64},
            "review-media-inbox-import-results": {"ledger_path": str(self.ledger), "expected_batch_id": "b"},
            "review-media-inbox-finalization-preview": {"ledger_path": str(self.ledger), "expected_batch_id": "b"},
            "review-media-inbox-finalize": {"plan_path": str(plan), "plan_sha256": "0" * 64},
        }
        with inbox_records.process_lock(self.ledger):
            for command, payload in writers.items():
                with self.subTest(command=command):
                    _code, result = self._cli(command, payload)
                    self.assertEqual(result["error"], inbox_records.BUSY_MESSAGE)
            for command, payload in {
                "review-ledger-validate": {"ledger_path": str(self.ledger)},
            }.items():
                with self.subTest(reader=command):
                    code, result = self._cli(command, payload)
                    self.assertEqual(code, 0, result)

    def test_the_hosts_own_helpers_pass_its_lock_and_are_not_refused(self) -> None:
        with inbox_records.process_lock(self.ledger):
            code, result = self._cli("review-media-inbox-scan", self._scan_payload(coordinator_lock_held=True))
        self.assertEqual(code, 0, result)
        self.assertEqual(result["data"]["inventory_count"], 1)

    def test_a_free_lock_is_taken_and_let_go(self) -> None:
        code, result = self._cli("review-media-inbox-scan", self._scan_payload())
        self.assertEqual(code, 0, result)
        with inbox_records.process_lock(self.ledger) as again:
            self.assertTrue(again.acquired)

    def test_an_action_on_existing_records_with_no_ledger_is_refused_before_it_touches_anything(self) -> None:
        # F5: with no ledger there is nothing to work on, so such an action is refused before it reads, writes or
        # locks anything. A mistyped ledger path used to get an .orchestration folder and a lock file made for it,
        # and targeted complete and a resumed finalize wrote into their batch before finding the ledger gone.
        self.assertLessEqual(INBOX_EXISTING_RECORDS, INBOX_WRITERS)
        missing = self.root / "no-such-inbox" / "review-ledger.sqlite"
        batch = self.root / "batches" / "b"
        batch.mkdir(parents=True)
        plan = self.root / "plan.json"
        plan.write_text(json.dumps({"ledger_path": str(missing), "batch_path": str(batch)}), encoding="utf-8")
        refusal = f"There are no Review Media Inbox records for {missing.parent}, so nothing was changed."
        before = inbox_library.fingerprint()
        for command in sorted(INBOX_EXISTING_RECORDS):
            if command in {"review-media-inbox-targeted-complete", "review-media-inbox-finalize"}:
                payload = {"plan_path": str(plan), "plan_sha256": "0" * 64}
            else:
                payload = {"ledger_path": str(missing), "expected_batch_id": "b", "batch_id": "b",
                           "batch_path": str(batch), "scratch_root": str(self.root / "scratch")}
            with self.subTest(command=command), unittest.mock.patch.object(
                    inbox_records, "process_lock", side_effect=AssertionError("no lock is taken")):
                code, result = self._cli(command, payload)
                self.assertEqual((code, result["error"]), (1, refusal))
                self.assertFalse(missing.parent.exists())
                self.assertEqual(list(batch.iterdir()), [], "nothing was written into the batch")
                self.assertFalse((self.root / "scratch").exists())
        self.assertEqual(inbox_library.fingerprint(), before)
        self.assertIsNone(_registered())

    def test_before_the_move_every_action_on_existing_records_says_why_and_touches_nothing(self) -> None:
        # 224 (Wave B2b, design 4.1): a library with no move receipt; the Inbox opens nothing yet.
        raw = inbox_library.connect()
        raw.execute("DELETE FROM legacy_imports")
        raw.commit()
        raw.close()
        batch = self.root / "batches" / "b"
        batch.mkdir(parents=True)
        for command in sorted(INBOX_EXISTING_RECORDS - {"review-media-inbox-targeted-complete",
                                                        "review-media-inbox-finalize"}):
            payload = {"ledger_path": str(self.ledger), "expected_batch_id": "b", "batch_id": "b",
                       "batch_path": str(batch), "scratch_root": str(self.root / "scratch")}
            with self.subTest(command=command), unittest.mock.patch.object(
                    inbox_records, "process_lock", side_effect=AssertionError("no lock is taken")):
                code, result = self._cli(command, payload)
                self.assertEqual((code, result["error"]), (1, inbox_records.NOT_MOVED_YET))
                self.assertFalse(self.ledger.parent.exists())
                self.assertEqual(list(batch.iterdir()), [])
        code, result = self._cli("review-media-inbox-scan", self._scan_payload())
        self.assertEqual((code, result["error"]), (1, inbox_records.NOT_MOVED_YET))
        self.assertFalse(self.ledger.parent.exists())
        self.assertIsNone(_registered())

    def test_a_request_that_names_no_ledger_gets_its_own_plain_refusal(self) -> None:
        code, result = self._cli("review-media-inbox-scan", {"source_folders": [str(self.sources)]})
        self.assertEqual(code, 1)
        self.assertIn("ledger_path is required", result["error"])


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "the PowerShell host runs on Windows")
class HostTests(unittest.TestCase):
    def _host(self, body: str) -> str:
        harness = f"""
$ErrorActionPreference = 'Stop'
$tokens = $null; $parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', [ref]$tokens, [ref]$parseErrors)
$wanted = @('Get-ReviewInboxWorkspace', 'Open-ReviewInboxProcessLock')
foreach ($node in $ast.FindAll({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $wanted -contains $n.Name }}, $true)) {{
    Invoke-Expression $node.Extent.Text
}}
{body}
"""
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / "harness.ps1"
            script.write_text(harness, encoding="utf-8-sig")
            completed = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                                       capture_output=True, text=True, timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout

    def test_the_host_works_the_workspace_out_as_python_does(self) -> None:
        samples = [r"C:\Evidence\review-inbox\review-ledger.sqlite", r"D:\a b\c\ledger.sqlite",
                   "C:/Evidence/inbox/review-ledger.sqlite", r"  C:\Evidence\x\review-ledger.sqlite  "]
        body = "\n".join(f"Write-Output (Get-ReviewInboxWorkspace -LedgerPath '{sample}')" for sample in samples)
        lines = self._host(body).splitlines()
        self.assertEqual([os.path.normpath(line) for line in lines],
                         [os.path.normpath(str(inbox_records.workspace(sample))) for sample in samples])

    def test_the_hosts_lock_and_the_python_lock_are_one_lock(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            ledger = Path(folder) / "inbox" / "review-ledger.sqlite"
            with inbox_records.process_lock(ledger) as held:
                self.assertTrue(held.acquired)
                busy = self._host(f"$lock = Open-ReviewInboxProcessLock -LedgerPath '{ledger}'\n"
                                  "Write-Output ($null -eq $lock)")
            self.assertEqual(busy.strip(), "True")
            free = self._host(f"$lock = Open-ReviewInboxProcessLock -LedgerPath '{ledger}'\n"
                              "Write-Output ($null -eq $lock); if ($lock) { $lock.Dispose() }")
            self.assertEqual(free.strip(), "False")

    def test_the_process_loop_and_the_targeted_action_pass_their_lock_to_the_helpers(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        helper = text[text.index("function Invoke-ReviewInboxTargetedEvidence "):]
        helper = helper[: helper.index("\nfunction ")]
        self.assertIn("[switch]$CoordinatorLockHeld", helper)
        self.assertEqual(helper.count("coordinator_lock_held = [bool]$CoordinatorLockHeld"), 2)
        loop = text[text.index('if ($nextAction -and [string]$nextAction.type -eq "render_targeted")'):]
        self.assertIn("-CoordinatorLockHeld", loop[: loop.index("continue")])
        action = text[text.index('if ($ReviewInboxAction -eq "TargetedEvidence") {'):]
        action = action[: action.index("return")]
        # Since Wave B2a it waits up to ten seconds for the lock (Wait-ReviewInboxProcessLock calls the one opener).
        self.assertIn("Wait-ReviewInboxProcessLock", action)
        waiting = text[text.index("function Wait-ReviewInboxProcessLock "):]
        self.assertIn("Open-ReviewInboxProcessLock -LedgerPath $LedgerPath", waiting[: waiting.index("\nfunction ")])
        self.assertIn('throw "The Inbox is busy with another run. Try again when it finishes."', action)
        self.assertIn("-CoordinatorLockHeld", action)
        self.assertIn("$targetedLock.Dispose()", action)
        # The Process loop takes the lock through the same function, which works the folder out with
        # Get-ReviewInboxWorkspace; the host has no second copy of the lock code.
        self.assertIn("Open-ReviewInboxProcessLock -LedgerPath ([string]$reviewNewVideosSettings.LedgerPath)", text)
        self.assertEqual(text.count("[System.IO.FileShare]::None"), 1)
        lock = text[text.index("function Open-ReviewInboxProcessLock "):]
        lock = lock[: lock.index("\nfunction ")]
        self.assertIn('Join-Path (Get-ReviewInboxWorkspace -LedgerPath $LedgerPath) ".orchestration"', lock)


class ReconcileThreadTests(unittest.TestCase):
    def test_a_database_error_in_the_reconcile_thread_is_reported_not_swallowed(self) -> None:
        from PySide6.QtWidgets import QApplication

        from media_manglers_workbench.app import ReviewInboxOperationThread

        QApplication.instance() or QApplication([])

        def locked(_payload: dict) -> dict:
            raise sqlite3.OperationalError("database is locked")

        thread = ReviewInboxOperationThread({}, locked)
        failures: list[str] = []
        thread.operation_failed.connect(failures.append)
        thread.run()  # in this thread, so the signal is delivered at once
        self.assertEqual(failures, ["database is locked"])


if __name__ == "__main__":
    unittest.main()
