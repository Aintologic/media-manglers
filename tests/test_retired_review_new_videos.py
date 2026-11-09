"""The old Review New Videos code is gone (224, Wave B2a, F3 and note 2).

The backend's Review New Videos branch ended with a ``return``, so the workflow after it, the only caller of
``Invoke-ReviewNewVideosWorkflow``, could never run. With it gone, the three command-line helpers only that
workflow called (lookup, record and match-sha) have no caller in the app; they are retired with one plain line
instead of being carried into the library (Decision 4). ``-migrate`` and ``-validate`` stay. The Workbench's
own dead Inbox code (two thread classes nothing starts, their fields, a timer nothing starts and two methods
nothing calls) goes with it. Nothing visible changes, because none of it could run.
"""

from __future__ import annotations

from pathlib import Path
import re
import tempfile
import unittest

from media_manglers.cli import INBOX_WRITERS, main
from media_manglers.contracts import CommandEnvelope, read_json_file, write_json_file
from media_manglers.core import inbox_records, review_ledger
import pytest
from tests import inbox_library  # noqa: E402

# 224 (Wave B2b): the Inbox's records are in this test's library, moved in (nothing to move).
pytestmark = pytest.mark.inbox_moved

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "Video Mangler.ps1"
APP = REPO_ROOT / "src" / "media_manglers_workbench" / "app.py"
RETIRED = ("review-ledger-lookup", "review-ledger-record", "review-ledger-match-sha")
RETIRED_LINE = "This old Review New Videos helper was retired; use Review Media Inbox."


class TheDeadBackendCodeIsGone(unittest.TestCase):
    def test_the_never_run_workflow_and_its_helpers_are_gone(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8-sig")
        for name in ("Invoke-ReviewNewVideosWorkflow", "Get-ReviewVideoStableStatus", "Get-ReviewManifestCounts"):
            with self.subTest(name=name):
                self.assertNotIn(name, text)

    def test_the_backend_never_names_a_retired_helper(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8-sig")
        for command in RETIRED:
            with self.subTest(command=command):
                self.assertNotIn(f'"{command}"', text)

    def test_nothing_runs_after_the_review_branch_returns(self) -> None:
        # The branch's last statement is its return: the closing brace follows it directly.
        text = SCRIPT.read_text(encoding="utf-8-sig")
        marker = "No media was copied, transcribed, rendered, moved, renamed, or deleted."
        tail = text[text.index(marker):]
        self.assertRegex(tail, r"\A[^\n]*\n\s*\}\s*\n\s*return\s*\n\}\s*\nif \(\$CodexEvidencePackage\)")

    def test_the_old_helpers_python_code_is_gone(self) -> None:
        for name in ("lookup_from_request", "record_from_request", "match_sha_from_request", "make_ledger_id"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(review_ledger, name))
        # The two that stay, ported in B2b.
        self.assertTrue(hasattr(review_ledger, "migrate_from_request"))
        self.assertTrue(hasattr(review_ledger, "validate_from_request"))


class TheRetiredHelpersRefuseInOneLine(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.ledger = self.root / "inbox" / "review-ledger.sqlite"
        self.video = self.root / "sources" / "clip.mp4"
        self.video.parent.mkdir(parents=True)
        self.video.write_bytes(b"fake video")

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _cli(self, command: str, payload: dict) -> tuple[int, dict]:
        request = self.root / f"{command}.request.json"
        result = self.root / f"{command}.result.json"
        write_json_file(request, CommandEnvelope(payload=payload).to_dict())
        code = main([command, "--request-file", str(request), "--result-file", str(result)])
        return code, read_json_file(result)

    def test_each_retired_helper_refuses_and_writes_nothing(self) -> None:
        payloads = {
            "review-ledger-lookup": {"ledger_path": str(self.ledger), "original_path": str(self.video),
                                     "create_in_progress": True},
            "review-ledger-record": {"ledger_path": str(self.ledger), "original_path": str(self.video),
                                     "status": "kept"},
            "review-ledger-match-sha": {"ledger_path": str(self.ledger), "content_sha256": "a" * 64},
        }
        for command, payload in payloads.items():
            with self.subTest(command=command):
                code, result = self._cli(command, payload)
                self.assertEqual(code, 1)
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"], RETIRED_LINE)
                # Neither a ledger, nor its folder, nor the Inbox's lock folder was made.
                self.assertFalse(self.ledger.parent.exists())

    def test_a_retired_helper_refuses_even_on_a_real_ledger_without_touching_it(self) -> None:
        inbox_library.ready(self.ledger)
        before = inbox_library.fingerprint()  # the Inbox's records, in the library (224, Wave B2b)
        code, result = self._cli("review-ledger-record", {"ledger_path": str(self.ledger),
                                                          "original_path": str(self.video), "status": "kept"})
        self.assertEqual((code, result["error"]), (1, RETIRED_LINE))
        self.assertEqual(inbox_library.fingerprint(), before)

    def test_the_retired_helpers_are_not_inbox_writers(self) -> None:
        # They no longer take the Inbox's lock: they refuse before anything else.
        for command in RETIRED:
            with self.subTest(command=command):
                self.assertNotIn(command, INBOX_WRITERS)


class TheWorkbenchsDeadInboxCodeIsGone(unittest.TestCase):
    def test_the_never_started_threads_fields_timer_and_methods_are_gone(self) -> None:
        text = APP.read_text(encoding="utf-8")
        for name in (
            "ReviewInboxScanThread",
            "ReviewInboxImportThread",
            "review_inbox_scan_thread",
            "review_inbox_import_thread",
            "review_inbox_results_thread",
            "review_inbox_finalization_thread",
            "review_inbox_scan_timer",
            "_refresh_review_inbox_scan_elapsed",
            "_refresh_review_inbox_final_results_status",
        ):
            with self.subTest(name=name):
                self.assertIsNone(re.search(rf"\b{name}\b", text))

    def test_the_live_reconcile_worker_stays(self) -> None:
        text = APP.read_text(encoding="utf-8")
        self.assertIn("class ReviewInboxOperationThread(QThread):", text)
        self.assertIn("self.review_inbox_reconcile_thread", text)


if __name__ == "__main__":
    unittest.main()
