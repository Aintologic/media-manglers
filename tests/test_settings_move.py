"""The run history moves out of settings.json once, with a backup first (243, Wave A1.6).

settings.json kept up to 30 runs. They move into the library as old runs whose details are unknown: what
History showed for them, nothing invented. Before anything changes, settings.json and the library are
copied into a backup folder of their own. The move is checked; a move that does not check out puts the
library back and leaves settings.json as it was. Only then is the history taken out of settings.json,
written safely and read back. Running the move again adds nothing; entries an older build wrote later
are moved in at the next start.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
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

from media_manglers.core import raw_bin_library, recording_records  # noqa: E402
from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.command_builder import CommandSpec  # noqa: E402
from media_manglers_workbench.runner import FakeRunner  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: E402
from tests.test_workbench_review_media_inbox import _ready_resources  # noqa: E402

try:
    from media_manglers.core.recording_records import Records, import_legacy_settings  # noqa: E402
except ImportError:  # shown failing on the code before the move existed
    Records = import_legacy_settings = None  # type: ignore[assignment]

STATUSES = ("succeeded", "failed", "cancelled", "completed with problems", "completed")


def old_runs(count: int) -> list[dict[str, str]]:
    """``count`` runs as settings.json kept them, newest first."""

    runs = []
    for number in range(count, 0, -1):
        runs.append({
            "timestamp": f"2026-10-{1 + number // 4:02d} {10 + number % 4:02d}:{number % 60:02d}",
            "workflow": "3", "workflow_title": f"Old run {number}", "profile": "",
            "source": f"C:\\Recordings\\race-{number}.mkv", "output": f"C:\\Output\\run-{number}",
            "log": f"C:\\Logs\\run-{number}.log", "status": STATUSES[number % len(STATUSES)],
        })
    return runs


def write_settings(path: Path, settings: dict) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": settings}, indent=2) + "\n").encode()
    path.write_bytes(data)
    return data


class MoveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="settings-move-"))
        self.settings = self.root / "Roaming" / "settings.json"
        self.records = Records(self.root / "library")
        self.addCleanup(self.records.close)
        self.others = {"output_folder": "C:\\Output", "whisper_model": "medium", "recent_output_folders": ["C:\\Output"],
                       "last_evidence_package": "C:\\Output\\pkg"}

    def test_the_run_history_moves_out_once_with_a_backup_taken_first(self) -> None:
        runs = old_runs(30)
        original = write_settings(self.settings, {**self.others, "recent_runs": runs})
        result = import_legacy_settings(self.records, self.settings)
        self.assertEqual(result["status"], "moved")
        self.assertEqual(result["counts"]["recent_runs"], {"read": 30, "added": 30, "already": 0})
        # The backup: settings.json byte for byte, and the library as it was before the move.
        backup = Path(result["backup_folder"])
        self.assertEqual((backup / "settings.json").read_bytes(), original)
        manifest = json.loads((backup / "BACKUP_MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["settings.json"], hashlib.sha256(original).hexdigest())
        copy = sqlite3.connect(f"{(backup / 'raw-bin-library.sqlite').as_uri()}?mode=ro", uri=True)
        try:
            self.assertEqual(copy.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)
        finally:
            copy.close()
        self.assertTrue((backup / "HOW_TO_RESTORE.txt").is_file())
        # settings.json keeps everything else, and no run history.
        saved = json.loads(self.settings.read_text(encoding="utf-8"))["settings"]
        self.assertNotIn("recent_runs", saved)
        self.assertEqual(saved, self.others)
        # History shows every old run as it showed it, newest first, its details unknown.
        history = self.records.list_runs(limit=100)
        self.assertEqual([entry["workflow_title"] for entry in history], [run["workflow_title"] for run in runs])
        self.assertEqual([entry["status"] for entry in history], [run["status"] for run in runs])
        self.assertEqual([entry["timestamp"] for entry in history], [run["timestamp"] for run in runs])
        self.assertTrue(all(entry["legacy"] for entry in history))
        first = self.records.get_run(history[0]["run_id"])
        self.assertEqual((first["details_unknown"], first["started_utc"]), (1, None))
        self.assertEqual(self.records.run_items(history[0]["run_id"]), [], "no recordings are invented")
        receipt = self.records.connection().execute("SELECT status FROM legacy_imports").fetchall()
        self.assertEqual([row[0] for row in receipt], ["complete"])

    def test_history_keeps_the_lists_own_order_when_its_times_are_not_in_order(self) -> None:
        # A clock put back (summer time ending) leaves a newer run with an earlier time: the list's order wins.
        runs = old_runs(4)
        runs[0]["timestamp"], runs[2]["timestamp"] = "2026-10-01 09:00", "2026-10-09 23:59"
        write_settings(self.settings, {**self.others, "recent_runs": runs})
        import_legacy_settings(self.records, self.settings)
        history = self.records.list_runs()
        self.assertEqual([entry["workflow_title"] for entry in history], [run["workflow_title"] for run in runs])
        self.assertEqual([entry["timestamp"] for entry in history], [run["timestamp"] for run in runs])

    def test_moving_twice_adds_nothing_and_an_older_builds_later_runs_come_in(self) -> None:
        runs = old_runs(5)
        write_settings(self.settings, {**self.others, "recent_runs": runs})
        import_legacy_settings(self.records, self.settings)
        self.assertEqual(import_legacy_settings(self.records, self.settings)["status"], "nothing")
        # An older build used afterwards writes its own run into settings.json again, the old ones with it.
        newer = {**old_runs(1)[0], "workflow_title": "A run the older build made", "timestamp": "2026-10-25 09:00"}
        write_settings(self.settings, {**self.others, "recent_runs": [newer, *runs]})
        result = import_legacy_settings(self.records, self.settings)
        self.assertEqual(result["counts"]["recent_runs"], {"read": 6, "added": 1, "already": 5})
        self.assertEqual(self.records.count_runs(), 6)

    def test_an_unreadable_settings_file_is_refused_left_as_it_is_and_a_copy_kept(self) -> None:
        self.settings.parent.mkdir(parents=True)
        self.settings.write_bytes(b'{"settings": {"recent_runs": [ this is not json')
        result = import_legacy_settings(self.records, self.settings)
        self.assertEqual(result["status"], "refused")
        self.assertEqual(self.settings.read_bytes(), b'{"settings": {"recent_runs": [ this is not json')
        self.assertEqual(self.records.count_runs(), 0)
        # The Workbench starts with defaults and its next save writes over the file: the copy is what is left.
        self.assertEqual((Path(result["backup_folder"]) / "settings.json").read_bytes(),
                         b'{"settings": {"recent_runs": [ this is not json')

    def test_a_move_that_does_not_check_out_adds_nothing_keeps_its_receipt_and_leaves_settings_alone(self) -> None:
        original = write_settings(self.settings, {**self.others, "recent_runs": old_runs(4)})
        with mock.patch.object(recording_records, "_check_move", return_value=["a count did not add up"]):
            result = import_legacy_settings(self.records, self.settings)
        self.assertEqual(result["status"], "restored")
        self.assertEqual(self.settings.read_bytes(), original)
        self.assertEqual(self.records.count_runs(), 0, "the library is as it was before the move")
        receipts = self.records.connection().execute("SELECT status, note FROM legacy_imports").fetchall()
        self.assertEqual([(row[0], row[1]) for row in receipts], [("restored", "a count did not add up")])
        # The next start moves it for real.
        self.assertEqual(import_legacy_settings(self.records, self.settings)["status"], "moved")
        self.assertEqual(self.records.count_runs(), 4)

    def _receipts(self) -> list[tuple[str, str]]:
        rows = self.records.connection().execute("SELECT status, note FROM legacy_imports ORDER BY import_id")
        return [(row[0], row[1] or "") for row in rows.fetchall()]

    def test_a_damaged_library_backup_ends_as_failed_and_changes_nothing(self) -> None:
        # 224 (Wave B2a, F8): the library's copy is checked before anything moves; one that does not check out
        # stops the move, its receipt says so, and settings.json and the library are as they were.
        from media_manglers.core import safe_write  # noqa: PLC0415

        original = write_settings(self.settings, {**self.others, "recent_runs": old_runs(4)})

        def damaged(_connection: sqlite3.Connection, partial: Path) -> None:
            Path(partial).write_bytes(b"SQLite format 3\x00" + b"\x00" * 84)

        with mock.patch.object(safe_write, "_backup_into", side_effect=damaged):
            result = import_legacy_settings(self.records, self.settings)
        self.assertEqual(result["status"], "failed")
        self.assertIn("did not check out", result["message"])
        self.assertEqual(self.settings.read_bytes(), original)
        self.assertEqual(self.records.count_runs(), 0)
        [(status, note)] = self._receipts()
        self.assertEqual(status, "failed")
        self.assertIn("did not check out", note)
        self.assertFalse((Path(result["backup_folder"]) / "raw-bin-library.sqlite").exists())
        # The next start moves it for real.
        self.assertEqual(import_legacy_settings(self.records, self.settings)["status"], "moved")
        self.assertEqual(self.records.count_runs(), 4)

    def test_a_backup_that_cannot_be_written_ends_as_failed_never_stuck_at_started(self) -> None:
        from media_manglers.core import safe_write  # noqa: PLC0415

        original = write_settings(self.settings, {**self.others, "recent_runs": old_runs(2)})
        with mock.patch.object(safe_write, "write_text", side_effect=OSError(28, "No space left on device")):
            result = import_legacy_settings(self.records, self.settings)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.settings.read_bytes(), original)
        self.assertEqual(self.records.count_runs(), 0)
        [(status, note)] = self._receipts()
        self.assertEqual(status, "failed")
        self.assertIn("No space left on device", note)

    def test_the_restore_files_are_written_through_the_safe_writer(self) -> None:
        from media_manglers.core import safe_write  # noqa: PLC0415

        write_settings(self.settings, {**self.others, "recent_runs": old_runs(2)})
        with mock.patch.object(safe_write, "write_text", wraps=safe_write.write_text) as written:
            result = import_legacy_settings(self.records, self.settings)
        names = {Path(call.args[0]).name for call in written.call_args_list}
        self.assertLessEqual({"BACKUP_MANIFEST.json", "HOW_TO_RESTORE.txt"}, names)
        manifest = json.loads((Path(result["backup_folder"]) / "BACKUP_MANIFEST.json").read_text(encoding="utf-8"))
        self.assertIn("raw-bin-library.sqlite", manifest)

    def test_a_move_cut_off_at_started_is_marked_failed_interrupted_at_the_next_start(self) -> None:
        with self.records.connection() as connection:
            connection.execute("INSERT INTO legacy_imports(source, started_utc, status) VALUES "
                               "('settings.json', '2026-10-30T10:00:00Z', 'started')")
        write_settings(self.settings, {**self.others, "recent_runs": old_runs(2)})
        self.assertEqual(import_legacy_settings(self.records, self.settings)["status"], "moved")
        self.assertEqual(self._receipts(), [("failed", "interrupted"), ("complete", "")])

    def test_a_settings_file_another_program_holds_now_is_cleaned_at_the_next_start(self) -> None:
        write_settings(self.settings, {**self.others, "recent_runs": old_runs(3)})
        from media_manglers.core import safe_write  # noqa: PLC0415

        with mock.patch.object(safe_write, "write_json", side_effect=PermissionError(13, "in use")):
            first = import_legacy_settings(self.records, self.settings)
        self.assertEqual(first["status"], "imported")
        self.assertIn("recent_runs", json.loads(self.settings.read_text(encoding="utf-8"))["settings"])
        self.assertEqual(import_legacy_settings(self.records, self.settings)["status"], "moved")
        self.assertEqual(self.records.count_runs(), 3)

    def test_a_settings_file_changed_during_the_move_is_cleaned_at_the_next_start(self) -> None:
        write_settings(self.settings, {**self.others, "recent_runs": old_runs(3)})
        real = recording_records._clean_settings
        with mock.patch.object(recording_records, "_clean_settings", return_value=False):
            first = import_legacy_settings(self.records, self.settings)
        self.assertEqual(first["status"], "imported")
        self.assertIn("recent_runs", json.loads(self.settings.read_text(encoding="utf-8"))["settings"])
        self.assertIs(recording_records._clean_settings, real)
        second = import_legacy_settings(self.records, self.settings)
        self.assertEqual((second["status"], second["counts"]["recent_runs"]["added"]), ("moved", 0))
        self.assertEqual(self.records.count_runs(), 3)

    def test_another_workbench_moving_now_is_left_to_it(self) -> None:
        original = write_settings(self.settings, {**self.others, "recent_runs": old_runs(2)})
        holder = open(self.records.root / recording_records.MOVE_LOCK, "a+b")
        try:
            recording_records._lock_now(holder)
            result = import_legacy_settings(self.records, self.settings)
        finally:
            holder.close()
        self.assertEqual(result["status"], "busy")
        self.assertEqual(self.settings.read_bytes(), original)


class WorkbenchMoveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="settings-move-window-"))
        self.settings = self.root / "settings.json"
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

    def _open(self) -> WorkbenchWindow:
        self.window = WorkbenchWindow(settings_path=self.settings, profiles_dir=self.root / "profiles",
                                      runner_factory=FakeRunner, resources=_ready_resources())
        return self.window

    def test_the_workbench_moves_the_history_when_it_starts_and_never_writes_it_back(self) -> None:
        write_settings(self.settings, {"log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
                                       "output_folder": str(self.root / "output"), "recent_runs": old_runs(30)})
        window = self._open()
        self.assertNotIn("recent_runs", window.app_settings)
        self.assertEqual(window.history_list.count(), 30)
        self.assertIn("Old run 30", window.history_list.item(0).text())
        # A 31st run, after the move: the first old run is still there.
        listener = mock.Mock()
        window.start_external_run(CommandSpec(argv=["fake"], preview="fake"), title="New run",
                                  settings=dict(window.app_settings), queue_items=[str(self.root / "a.mkv")],
                                  listener=listener, evidence_package=False)
        self.assertTrue(self._wait(lambda: window.runner_thread is None and listener.on_finished.called))
        window.save_app_settings()
        self.assertNotIn("recent_runs", json.loads(self.settings.read_text(encoding="utf-8"))["settings"])
        shown = [window.history_list.item(row).text() for row in range(window.history_list.count())]
        self.assertEqual(len(shown), 31)
        self.assertIn("New run", shown[0])
        self.assertIn("Old run 1", shown[-1])

    def test_a_settings_file_held_by_another_program_at_start_shows_each_old_run_once(self) -> None:
        # Antivirus or a sync tool holds settings.json while the Workbench starts: the history is in the
        # library, its cleaning waits for the next start, and History never lists the old runs twice.
        write_settings(self.settings, {"log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
                                       "output_folder": str(self.root / "output"), "recent_runs": old_runs(5)})
        from media_manglers.core import safe_write  # noqa: PLC0415

        real = safe_write.write_json

        def held(path, data):
            if Path(path) == self.settings:
                raise PermissionError(13, "in use")
            return real(path, data)

        with mock.patch.object(safe_write, "write_json", side_effect=held):
            window = self._open()
        self.assertEqual(window.records_move["status"], "imported")
        self.assertEqual(window.history_list.count(), 5)
        self.assertNotIn("recent_runs", window.app_settings, "never written back from here")

    def test_an_unreadable_settings_file_is_said_once_without_stopping_the_start(self) -> None:
        self.settings.write_bytes(b"{ not json")
        logged: list[str] = []
        real_log = WorkbenchWindow._write_workbench_log

        def log(window: WorkbenchWindow, line: str) -> None:
            logged.append(line)
            real_log(window, line)

        with mock.patch.object(WorkbenchWindow, "_write_workbench_log", log):
            window = self._open()
        self.assertEqual(window.records_move["status"], "refused")
        self._wait(lambda: window.records_notice.isVisible(), 5.0)
        self.assertTrue(window.records_notice.isVisible())
        self.assertFalse(window.records_notice.isModal())
        self.assertIn("could not be read", window.records_notice.text())
        # 224 (B1, F1): like every warning pop-up, it goes through ui_parts.warn and is written to the log.
        self.assertTrue(any(line.startswith("Warning shown: Your settings could not be read: settings.json could "
                                            "not be read") for line in logged), logged)

    def test_a_workbench_started_like_the_builds_check_keeps_its_library_in_the_throwaway_folder(self) -> None:
        # 242 (R1): the build's start-up check sets only the Workbench's two app-data folders. The library
        # the Workbench opens when it starts goes inside them, never into the operator's own folder.
        throwaway = self.root / "smoke-appdata" / "Local"
        with mock.patch.dict(os.environ, {"MEDIA_MANGLERS_WORKBENCH_LOCALAPPDATA": str(throwaway)}):
            os.environ.pop(raw_bin_library.LIBRARY_ROOT_ENV, None)
            window = self._open()
            self.assertEqual(window.records.root, throwaway / "MediaManglers" / "Workbench" / "library")
            self.assertTrue((window.records.root / "raw-bin-library.sqlite").is_file())


if __name__ == "__main__":
    unittest.main()
