"""Each feature writes its own final outcome per recording, when it knows it (243, Wave A1.4).

History knew only what the process's exit code suggested, written before the Inbox applied its lifecycle,
before Find my bug reports corrected it, and never corrected at all for a raw bin scan: a scan that could
not reach the recordings drive was saved as "succeeded". Now every run keeps each recording's outcome:
New Review from the backend's own per-recording lines and this run's own files, Find my bug reports from
its rows, the Inbox from its run journal and its ledger (read-only), a raw bin scan from what it stores,
the AI Video Editor from its result. Nothing is guessed: a recording nobody reported on says so.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from media_manglers.core import inbox_records, raw_bin_library, recording_records, review_ledger, review_orchestration  # noqa: E402
from media_manglers.core.recording_records import Records  # noqa: E402
from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402

try:
    from media_manglers_workbench import run_outcomes  # noqa: E402
except ImportError:  # shown failing on the code before the features wrote their outcomes
    run_outcomes = None  # type: ignore[assignment]
from media_manglers_workbench.metadata import WORKFLOW_FULL_REVIEW  # noqa: E402
from media_manglers_workbench.runner import FakeRunner, RunnerResult  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: E402
from tests.test_raw_bin_library import FFMPEG, FFPROBE, HearingTranscriber, make_recording  # noqa: E402
from tests.test_workbench_review_media_inbox import _ready_resources  # noqa: E402
import pytest
from tests import inbox_library  # noqa: E402

# 224 (Wave B2b): the Inbox's records are in this test's library, moved in (nothing to move).
pytestmark = pytest.mark.inbox_moved


class ReaderTests(unittest.TestCase):
    """The run's own files, read only when this run wrote them."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="run-outcomes-"))
        self.a, self.b, self.c, self.d = (str(self.root / name) for name in ("a.mkv", "b.mkv", "c.mkv", "d.mkv"))

    def _transcript_manifest(self, entries: list[dict]) -> Path:
        folder = self.root / "out" / "transcript-only"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "transcript_manifest.json"
        path.write_text(json.dumps(entries), encoding="utf-8")
        return path

    def test_transcript_only_says_each_recordings_outcome_and_who_skipped_it(self) -> None:
        self._transcript_manifest([
            {"source_path": self.a, "status": "completed"},
            {"source_path": self.b, "status": "skipped", "error_message": "Skipped by you."},
            {"source_path": self.c, "status": "skipped", "error_message": ""},
            {"source_path": self.d, "status": "failed", "error_message": "no audio"},
        ])
        found = run_outcomes.transcript_only_outcomes(self.root / "out", since=time.time() - 60)
        self.assertEqual(found[recording_records.path_key(self.a)], ("completed", ""))
        self.assertEqual(found[recording_records.path_key(self.b)], ("skipped", "Skipped by you."))
        self.assertEqual(found[recording_records.path_key(self.c)][0], "completed", "its transcript was already there")
        self.assertEqual(found[recording_records.path_key(self.d)], ("failed", "no audio"))

    def test_a_manifest_an_earlier_run_left_is_not_this_runs_word(self) -> None:
        manifest = self._transcript_manifest([{"source_path": self.a, "status": "completed"}])
        old = time.time() - 3600
        os.utime(manifest, (old, old))
        self.assertEqual(run_outcomes.transcript_only_outcomes(self.root / "out", since=time.time() - 60), {})

    def test_a_ticket_package_says_no_narration_as_a_result_of_its_own(self) -> None:
        package = self.root / "package"
        package.mkdir()
        (package / "manifest.json").write_text(json.dumps({"sources": [
            {"source_path": self.a, "status": "completed"},
            {"source_path": self.b, "status": "completed",
             "transcript_quality": {"quality_status": "no_narration_found"}},
            {"source_path": self.c, "status": "operator_skipped"},
            {"source_path": self.d, "status": "quality_blocked"},
        ]}), encoding="utf-8")
        found = run_outcomes.package_outcomes(package, since=time.time() - 60)
        self.assertEqual([found[recording_records.path_key(path)][0] for path in (self.a, self.b, self.c, self.d)],
                         ["completed", "no_narration", "skipped", "failed"])

    def test_nothing_is_guessed_for_a_recording_nobody_reported_on(self) -> None:
        outcomes = run_outcomes.wizard_outcomes(
            [self.a, self.b, self.c, self.d],
            reported={self.a: "completed", self.b: "pending", self.c: "pending", self.d: "active"},
            final={self.a: "completed", self.b: "completed", self.c: "cancelled", self.d: "failed"},
            from_files={recording_records.path_key(self.b): ("no_narration", "")})
        self.assertEqual([(item["outcome"], item["reported_by"]) for item in outcomes],
                         [("completed", "progress lines"), ("no_narration", "run files"), ("cancelled", "run end"),
                          ("not_reported", "run end")])


class InboxOutcomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="run-outcomes-inbox-"))
        self.ledger = self.root / "inbox" / "review-ledger.sqlite"
        inbox_library.ready(self.ledger)
        connection = inbox_library.connect()
        with connection:
            for source_id, state in ((1, "awaiting_external_review"), (2, "retryable_failure"),
                                     (3, "needs_manual_review"), (4, "pending")):
                connection.execute(
                    "INSERT INTO inbox_sources(source_id, provisional_identity, size_bytes, lifecycle_state, first_seen_utc, "
                    "updated_utc) VALUES (?, ?, 10, ?, '2026-10-25T00:00:00Z', '2026-10-25T00:00:00Z')",
                    (source_id, f"provisional:{source_id}", state))
        connection.close()
        orchestration = self.ledger.parent / ".orchestration" / "completed-runs"
        orchestration.mkdir(parents=True)
        self.paths = [str(self.root / f"r{number}.mkv") for number in range(1, 5)]
        # Written by the Inbox's own journal writer, in the shape the Inbox keeps it.
        review_orchestration._write_journal(orchestration / "run-7.json", {
            "run_id": "run-7", "status": "complete",
            "snapshot": [{"source_id": str(number), "path": path} for number, path in enumerate(self.paths, start=1)],
            "completed_source_ids": ["1", "2", "3"],
        })

    def outcomes(self, run: str, **options: object) -> list[dict]:
        # 224 (Wave B2b): read from the Inbox's records in the library, over the caller's connection.
        connection = inbox_library.connect(read_only=True)
        try:
            return recording_records.inbox_run_outcomes(connection, run, **options)
        finally:
            connection.close()

    def test_each_recording_the_run_took_says_where_the_ledger_has_it_now(self) -> None:
        before = inbox_library.fingerprint()
        outcomes = self.outcomes("run-7")
        self.assertEqual([(item["item"], item["outcome"]) for item in outcomes], [
            (self.paths[0], "completed"), (self.paths[1], "failed"), (self.paths[2], "completed_with_problems"),
            (self.paths[3], "cancelled")])
        self.assertEqual(outcomes[0]["reason"], "awaiting external review")
        self.assertEqual(inbox_library.fingerprint(), before, "the Inbox's records are only read")

    def test_a_run_picked_up_again_counts_only_what_it_did_itself(self) -> None:
        # The Inbox keeps one journal for a Process run it picks up again later; a recording an earlier
        # Workbench run of it already counted is not counted again.
        outcomes = self.outcomes("run-7", already_counted={recording_records.path_key(self.paths[0])})
        self.assertEqual([item["item"] for item in outcomes], self.paths[1:])

    def test_another_runs_journal_or_none_gives_nothing(self) -> None:
        self.assertEqual(self.outcomes("run-8"), [])
        self.assertEqual(self.outcomes(""), [])


@unittest.skipUnless(shutil.which(FFMPEG) and shutil.which(FFPROBE), "needs FFmpeg")
class RawBinScanOutcomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="run-outcomes-scan-"))
        self.raw, self.library, self.cache = self.root / "raw", self.root / "library", self.root / "cache"
        self.raw.mkdir()
        self.records = Records(self.library)
        self.addCleanup(self.records.close)

    def _scan(self, run_id: str) -> dict:
        options = raw_bin_library.ScanOptions(
            folders=[str(self.raw)], ffmpeg=FFMPEG, ffprobe=FFPROBE, transcriber=HearingTranscriber({2}),
            library_root=str(self.library), cache_folder=str(self.cache), stable_after_seconds=0, records_run_id=run_id)
        return raw_bin_library.scan(options)

    def test_a_scan_writes_each_recording_it_read_into_its_run(self) -> None:
        make_recording(self.raw / "race.mkv", seconds=30)
        run_id = self.records.open_run(kind="raw_scan", title="Raw bin scan", items=[str(self.raw)])
        self.assertEqual(self._scan(run_id)["files_read"], 1)
        items = [item for item in self.records.run_items(run_id) if item["kind"] == "recording"]
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0]["path"], items[0]["outcome"], items[0]["reported_by"]),
                         (str(self.raw / "race.mkv"), "completed", "raw bin scan"))
        self.assertTrue(items[0]["recording_id"], "linked to the recording the scan stored")
        # A scan that finds it unchanged reads nothing, and counts it rather than listing it.
        again = self.records.open_run(kind="raw_scan", title="Raw bin scan", items=[str(self.raw)])
        self.assertEqual(self._scan(again)["unchanged"], 1)
        self.assertEqual([item["kind"] for item in self.records.run_items(again)], ["folder"])


class WindowOutcomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="run-outcomes-window-"))
        self.window: WorkbenchWindow | None = None

    def tearDown(self) -> None:
        if self.window is not None:
            self._wait(lambda: self.window.runner_thread is None)
            self.window._closing_after_smoke = True
            self.window.close()
            self.app.processEvents()

    def _wait(self, condition, seconds: float = 10.0) -> bool:
        deadline = time.monotonic() + seconds
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        return condition()

    def _open(self, runner=FakeRunner, **settings: str) -> WorkbenchWindow:
        path = self.root / "settings.json"
        path.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
            "log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
            "output_folder": str(self.root / "output"), **settings}}), encoding="utf-8")
        self.window = WorkbenchWindow(settings_path=path, profiles_dir=self.root / "profiles", runner_factory=runner,
                                      resources=_ready_resources())
        return self.window

    def test_a_raw_bin_scan_that_could_not_reach_the_drive_is_failed_in_history(self) -> None:
        window = self._open()
        page = window.raw_bin_page
        run_id = window.records.open_run(kind="raw_scan", title="Raw bin scan", items=[str(self.root / "gone")])
        window.records.end_run(run_id, process_status="succeeded", exit_code=0)
        page.running, page.run_folder = "scan", self.root / "scan-run"
        page.run_folder.mkdir()
        (page.run_folder / "result.json").write_text(json.dumps({"ok": True, "data": {
            "status": "drive_not_reachable", "message": "Recordings drive not reachable: E:\\Raw."}}), encoding="utf-8")
        page.on_finished(RunnerResult(status="succeeded", exit_code=0, run_id=run_id))
        entry = window.records.get_history_entry(run_id)
        self.assertEqual(entry["status"], "failed")
        self.assertEqual(window.records.get_run(run_id)["headline"], "Recordings drive not reachable: E:\\Raw.")

    def test_a_full_review_keeps_what_the_backend_reported_for_each_recording(self) -> None:
        recordings = self.root / "recordings"
        recordings.mkdir()
        good, unreported = recordings / "good.mkv", recordings / "quiet.mkv"
        for path in (good, unreported):
            path.write_bytes(b"not really video")
        line = "MM_PROGRESS_V1 " + json.dumps({
            "schema": "MM_PROGRESS_V1", "phase": "Packaging", "progress_kind": "indeterminate",
            "source_name": good.name, "source_completed": 1, "source_total": 2, "source_ordinal": 1,
            "source_state": "completed", "source_terminal": True, "activity": "done"})
        window = self._open(lambda: FakeRunner(stdout=[line], exit_code=1))
        window.start_workflow_from_home(WORKFLOW_FULL_REVIEW)
        window.run_settings["input_path"] = str(recordings)
        window.run_settings["output_folder"] = str(self.root / "output")
        refused = mock.Mock(side_effect=lambda _parent, title, text, *rest: self.fail(f"{title}: {text}"))
        with mock.patch("media_manglers_workbench.app.QMessageBox.warning", refused), \
                mock.patch("media_manglers_workbench.app.QMessageBox.information", refused):
            window.start_job()
        self.assertTrue(self._wait(lambda: window.runner_thread is None))
        run = window.recent_runs()[0]
        outcomes = {Path(item["path"]).name: (item["outcome"], item["reported_by"])
                    for item in window.records.run_items(run["run_id"])}
        self.assertEqual(outcomes, {"good.mkv": ("completed", "progress lines"),
                                    "quiet.mkv": ("not_reported", "run end")})
        self.assertEqual(run["status"], "completed with problems",
                         "one recording done and one not: the state Progress shows (213)")


if __name__ == "__main__":
    unittest.main()
