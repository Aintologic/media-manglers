"""A command-line Inbox write waits a moment for the Workbench's status check (224, Wave B2a, item 4).

The Workbench's short status check (reconcile) holds the Inbox's lock for a moment at start, on every visit to
the Inbox page and after Inbox runs. A command-line write (the outside agent's, or one run by hand) that
arrived then was refused once with "The Inbox is busy". It now tries again every quarter second for up to ten
seconds, and only then gives the same one line. Only a real lock refusal counts as busy (note 7): any other
error says plainly what Windows refused. The lock makes only ``.orchestration``, inside an Inbox folder that is
already there, never the folders of a mistyped path (note 10). The lock is held by a separate program here
(``tests/outside_holder.py``), the way another run holds it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.cli import main  # noqa: E402
from media_manglers.contracts import CommandEnvelope, read_json_file, write_json_file  # noqa: E402
from media_manglers.core import inbox_records, review_orchestration  # noqa: E402
from tests.outside_holder import OutsideHolder  # noqa: E402
import pytest
from tests import inbox_library  # noqa: E402

# 224 (Wave B2b): the Inbox's records are in this test's library, moved in (nothing to move).
pytestmark = pytest.mark.inbox_moved

WINDOWS = os.name == "nt"


def _fingerprint(_path: Path) -> str:
    # 224 (Wave B2b): the Inbox's records, in the library, rather than a ledger file's bytes.
    return inbox_library.fingerprint()


class _Inbox(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="inbox-lock-wait-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.sources = self.root / "sources"
        self.sources.mkdir()
        (self.sources / "clip.mp4").write_bytes(b"fake video")
        self.ledger = self.root / "inbox" / "review-ledger.sqlite"
        inbox_library.ready(self.ledger)
        self.lock = inbox_records.lock_file(self.ledger.parent)
        with inbox_records.process_lock(self.ledger):
            pass  # the lock file exists, as it does once any run has taken it

    def _cli(self, command: str, payload: dict) -> tuple[int, dict]:
        request = self.root / f"{command}.request.json"
        result = self.root / f"{command}.result.json"
        write_json_file(request, CommandEnvelope(payload=payload).to_dict())
        code = main([command, "--request-file", str(request), "--result-file", str(result)])
        return code, read_json_file(result)

    def _scan(self) -> dict:
        return {"source_folders": [str(self.sources)], "ledger_path": str(self.ledger)}


@unittest.skipUnless(WINDOWS, "the Inbox's lock is one locked byte, held here by another program")
class CommandLineWriterWaitsTests(_Inbox):
    def test_a_lock_held_for_about_a_second_is_waited_for_and_the_write_succeeds(self) -> None:
        with OutsideHolder(self.lock, lock=True, seconds=1.0):
            started = time.monotonic()
            code, result = self._cli("review-media-inbox-scan", self._scan())
            waited = time.monotonic() - started
        self.assertEqual(code, 0, result)
        self.assertEqual(result["data"]["inventory_count"], 1)
        self.assertGreater(waited, 0.5, "it waited for the other run to let go")

    def test_a_lock_held_past_ten_seconds_gives_the_busy_line_and_writes_nothing(self) -> None:
        before = _fingerprint(self.ledger)
        with OutsideHolder(self.lock, lock=True, forever=True):
            started = time.monotonic()
            code, result = self._cli("review-media-inbox-scan", self._scan())
            waited = time.monotonic() - started
        self.assertEqual((code, result["error"]), (1, inbox_records.BUSY_MESSAGE))
        self.assertGreaterEqual(waited, 9.5)
        self.assertLess(waited, 20)
        self.assertEqual(_fingerprint(self.ledger), before)

    def test_it_tries_again_every_quarter_second_for_ten_seconds(self) -> None:
        pauses: list[float] = []
        with OutsideHolder(self.lock, lock=True, forever=True):
            with self.assertRaises(inbox_records.InboxBusy):
                with inbox_records.writing(self.ledger, pause=pauses.append):
                    self.fail("the write ran without the lock")
        self.assertEqual(set(pauses), {0.25})
        self.assertAlmostEqual(sum(pauses), inbox_records.LOCK_WAIT_SECONDS)

    def test_the_hosts_own_helpers_never_wait(self) -> None:
        # Inside its Process loop the host holds the lock and says so; those helpers go straight on.
        pauses: list[float] = []
        with OutsideHolder(self.lock, lock=True, forever=True):
            with inbox_records.writing(self.ledger, coordinator_lock_held=True, pause=pauses.append):
                pass
        self.assertEqual(pauses, [])


@unittest.skipUnless(WINDOWS, "the PowerShell host runs on Windows")
class TheHostsTargetedEvidenceWaitsTests(_Inbox):
    """The host's TargetedEvidence action takes the lock the same way, with the same short wait."""

    FUNCTIONS = ("Get-ReviewInboxWorkspace", "Open-ReviewInboxProcessLock", "Wait-ReviewInboxProcessLock")

    def _host(self, seconds: float, holder: OutsideHolder | None = None, release_after: float = 0.0) -> dict:
        """Run the host's wait; with ``holder``, let go ``release_after`` seconds after the host started waiting
        (loading the script takes longer than that, so the release is timed from the host's own signal)."""

        import subprocess  # noqa: PLC0415
        import textwrap  # noqa: PLC0415

        script = Path(__file__).resolve().parents[1] / "Video Mangler.ps1"
        ready = self.root / "host-ready.txt"
        names = ",".join(f"'{name}'" for name in self.FUNCTIONS)
        source = textwrap.dedent(f"""
            $ErrorActionPreference = 'Stop'
            $tokens = $null; $parseErrors = $null
            $ast = [System.Management.Automation.Language.Parser]::ParseFile('{script}', [ref]$tokens, [ref]$parseErrors)
            $wanted = @({names})
            foreach ($node in $ast.FindAll({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $wanted -contains $n.Name }}, $true)) {{
                Invoke-Expression $node.Extent.Text
            }}
            [System.IO.File]::WriteAllText('{ready}', 'ready')
            $started = [DateTime]::UtcNow
            $lock = Wait-ReviewInboxProcessLock -LedgerPath '{self.ledger}' -Seconds {seconds}
            $waited = ([DateTime]::UtcNow - $started).TotalSeconds
            $took = $null -ne $lock
            if ($took) {{ $lock.Dispose() }}
            @{{ took = $took; waited = $waited }} | ConvertTo-Json -Compress
            """).strip()
        harness = self.root / "host-lock.ps1"
        harness.write_text(source, encoding="utf-8")
        process = subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if holder is not None:
            deadline = time.monotonic() + 90
            while not ready.exists() and time.monotonic() < deadline and process.poll() is None:
                time.sleep(0.05)
            time.sleep(release_after)
            holder.release()
        stdout, stderr = process.communicate(timeout=120)
        self.assertEqual(process.returncode, 0, stderr)
        return json.loads(stdout.strip().splitlines()[-1])

    def test_the_host_waits_for_a_brief_hold_and_takes_the_lock(self) -> None:
        with OutsideHolder(self.lock) as holder:
            result = self._host(10, holder, release_after=1.0)
        self.assertTrue(result["took"])
        self.assertGreater(result["waited"], 0.5)

    def test_the_host_says_plainly_when_windows_refuses_the_lock_for_another_reason(self) -> None:
        # 224 (Wave B2a review, note 7): a refusal that is not another run holding the lock (here, a read-only lock
        # file, which Windows refuses with "access denied") is said in the host's plain line, not as raw .NET text.
        import stat  # noqa: PLC0415
        import subprocess  # noqa: PLC0415
        import textwrap  # noqa: PLC0415

        os.chmod(self.lock, stat.S_IREAD)
        self.addCleanup(os.chmod, self.lock, stat.S_IREAD | stat.S_IWRITE)
        script = Path(__file__).resolve().parents[1] / "Video Mangler.ps1"
        names = ",".join(f"'{name}'" for name in self.FUNCTIONS)
        harness = self.root / "host-refused.ps1"
        harness.write_text(textwrap.dedent(f"""
            $ErrorActionPreference = 'Stop'
            $tokens = $null; $parseErrors = $null
            $ast = [System.Management.Automation.Language.Parser]::ParseFile('{script}', [ref]$tokens, [ref]$parseErrors)
            $wanted = @({names})
            foreach ($node in $ast.FindAll({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $wanted -contains $n.Name }}, $true)) {{
                Invoke-Expression $node.Extent.Text
            }}
            try {{ $null = Open-ReviewInboxProcessLock -LedgerPath '{self.ledger}'; $said = 'took it' }}
            catch {{ $said = $_.Exception.Message }}
            @{{ said = $said }} | ConvertTo-Json -Compress
            """).strip(), encoding="utf-8")
        completed = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                                   capture_output=True, text=True, timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        said = json.loads(completed.stdout.strip().splitlines()[-1])["said"]
        self.assertTrue(said.startswith("Windows refused to open the Inbox's lock file ("), said)
        self.assertIn("so nothing was done", said)

    def test_the_host_gives_up_at_its_deadline(self) -> None:
        with OutsideHolder(self.lock, forever=True):
            result = self._host(1)
        self.assertFalse(result["took"])
        self.assertGreaterEqual(result["waited"], 0.9)

    def test_the_targeted_evidence_action_uses_the_wait_and_the_process_loop_does_not(self) -> None:
        text = (Path(__file__).resolve().parents[1] / "Video Mangler.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("$targetedLock = Wait-ReviewInboxProcessLock -LedgerPath", text)
        self.assertIn("$processLock = Open-ReviewInboxProcessLock -LedgerPath", text)


@unittest.skipUnless(WINDOWS, "Windows' own refusals")
class OnlyARealRefusalIsBusyTests(_Inbox):
    def test_a_refusal_that_is_not_another_run_says_what_windows_refused_not_busy(self) -> None:
        # Note 7: any error opening the lock read as "busy". Here Windows refuses because the lock's name is a
        # folder ("access denied"), and no other run is involved.
        ledger = self.root / "other-inbox" / "review-ledger.sqlite"
        # A second Inbox: a library of its own (224, Wave B2b).
        inbox_library.use_own_library(self, self.root / "other-library")
        inbox_library.ready()
        inbox_records.lock_file(ledger.parent).mkdir(parents=True)
        with mock.patch("time.sleep") as slept:
            code, result = self._cli("review-media-inbox-scan", {"source_folders": [str(self.sources)],
                                                                 "ledger_path": str(ledger)})
        self.assertEqual(code, 1)
        self.assertNotEqual(result["error"], inbox_records.BUSY_MESSAGE)
        self.assertIn("Windows refused to open the Inbox's lock file (Access is denied", result["error"])
        self.assertEqual(slept.call_count, 0, "it did not wait")

    def test_the_hosts_process_loop_holding_the_lock_is_busy(self) -> None:
        # The PowerShell host's Process loop holds the lock file open with no sharing at all.
        with OutsideHolder(self.lock, exclusive=True, forever=True), mock.patch("time.sleep") as slept:
            code, result = self._cli("review-media-inbox-scan", self._scan())
        self.assertEqual((code, result["error"]), (1, inbox_records.BUSY_MESSAGE))
        self.assertAlmostEqual(sum(call.args[0] for call in slept.call_args_list), inbox_records.LOCK_WAIT_SECONDS)


class TheLockMakesNoFoldersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="inbox-lock-folders-"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_the_lock_never_makes_a_missing_inbox_folder(self) -> None:
        # Note 10: the relocation tool takes this lock first, so a mistyped path left its folders behind.
        missing = self.root / "a-typo" / "inbox"
        with self.assertRaises(inbox_records.InboxFolderMissing) as refused:
            with inbox_records.ProcessLock(inbox_records.lock_file(missing)):
                self.fail("the lock was taken")
        self.assertIn("nothing was changed", str(refused.exception))
        self.assertFalse((self.root / "a-typo").exists())

    def test_the_lock_makes_only_its_own_folder_inside_an_inbox_folder_that_is_there(self) -> None:
        folder = self.root / "inbox"
        folder.mkdir()
        with inbox_records.ProcessLock(inbox_records.lock_file(folder)) as lock:
            self.assertTrue(lock.acquired)
        self.assertEqual([path.name for path in folder.iterdir()], [".orchestration"])

    def test_a_run_that_starts_a_new_inbox_still_makes_its_folder(self) -> None:
        ledger = self.root / "new-inbox" / "review-ledger.sqlite"
        inbox_library.ready()
        with inbox_records.writing(ledger):
            pass
        self.assertTrue((self.root / "new-inbox" / ".orchestration").is_dir())


class TheStatusCheckSaysHowLongItHeldTheLockTests(_Inbox):
    def test_reconcile_reports_how_long_it_held_the_lock(self) -> None:
        result = review_orchestration.reconcile_from_request({"ledger_path": str(self.ledger)})
        self.assertIsInstance(result["lock_held_seconds"], float)
        self.assertGreaterEqual(result["lock_held_seconds"], 0.0)
        self.assertLess(result["lock_held_seconds"], 60.0)


class TheWorkbenchLogsTheHoldTests(unittest.TestCase):
    """The Workbench writes the status check's hold into its log, so the ten seconds can be checked against a
    real measurement on a copy of the operator's Inbox."""

    def test_the_inbox_pages_status_check_writes_its_lock_hold_to_the_log(self) -> None:
        from PySide6.QtCore import Qt  # noqa: PLC0415
        from PySide6.QtTest import QTest  # noqa: PLC0415
        from PySide6.QtWidgets import QApplication  # noqa: PLC0415

        from media_manglers_workbench.app import WorkbenchWindow  # noqa: PLC0415
        from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: PLC0415
        from tests.qt_input import bring_to_front  # noqa: PLC0415
        from tests.test_wave_b1_screens import QuickRunner  # noqa: PLC0415
        from tests.test_workbench_review_media_inbox import _ready_resources, _status  # noqa: PLC0415

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "recordings").mkdir()
            settings_path = root / "settings.json"
            settings_path.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
                "log_folder": str(root / "logs"), "temp_folder": str(root / "temp"),
                "output_folder": str(root / "output"), "review_source_folders": str(root / "recordings"),
                "review_inbox_folder": str(root / "inbox"),
                "review_local_work_root": str(root / "work"), "review_dedupe_mode": "Fast"}}), encoding="utf-8")
            window = WorkbenchWindow(settings_path=settings_path, profiles_dir=root / "profiles",
                                     runner_factory=QuickRunner, resources=_ready_resources(),
                                     review_inbox_reconciler=lambda _payload: {**_status(), "lock_held_seconds": 0.42})
            try:
                window.show()
                app.processEvents()
                button = window.nav_buttons["Review Media Inbox"]
                bring_to_front(button)
                QTest.mouseClick(button, Qt.MouseButton.LeftButton)
                deadline = time.monotonic() + 10
                while window.review_inbox_reconcile_thread is not None and time.monotonic() < deadline:
                    app.processEvents()
                    QTest.qWait(20)
                log = "\n".join(path.read_text(encoding="utf-8", errors="replace")
                                for path in sorted((root / "logs").glob("*")))
                self.assertIn("The Inbox's status check held its lock for 0.42 seconds.", log)
            finally:
                window._closing_after_smoke = True
                window.close()
                app.processEvents()


if __name__ == "__main__":
    unittest.main()
