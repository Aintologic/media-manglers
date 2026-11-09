"""Find my bug reports and the built-in player keep their lists in the library (244, Wave A2.3).

The Bugs page's Never use this recording, the Never-use list... dialog and its Allow again, Add newest,
Add, Include ones already done, the status column and caption, and the "done" a finished run leaves; the
player's Never use this recording, its Undo and Allow again, and its This recording row. Each one works
exactly as before, with the same words, and now reads and writes the library instead of settings.json,
which keeps neither list. A recording whose identical copy was already mined counts as done (decision E).

The page runs in a real Workbench window with the scripted backend; the player in its own window with
the stand-in host its other tests use, given a real library.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QDialog, QListWidget, QPushButton  # noqa: E402

import test_workbench_bug_reports as base  # noqa: E402
from media_manglers.core.recording_records import Records  # noqa: E402
from tests.test_recording_marks import store_copy, write_recording  # noqa: E402
from tests.test_review_player import SESSION_ONE, SESSION_TWO, FakePage, WindowTestCase  # noqa: E402

TODAY = datetime.now().strftime("%Y-%m-%d")
# The settings keys the lists and the stopped run were kept in (114, 115).
EXCLUDED_KEY = "bug_report_excluded_recordings"
LIST_KEYS = (EXCLUDED_KEY, "bug_report_processed_recordings", "bug_report_stopped_run")


class BugsPageLibraryTests(unittest.TestCase):
    setUpClass = classmethod(base.BugReportsPageTests.setUpClass.__func__)
    setUp = base.BugReportsPageTests.setUp
    tearDown = base.BugReportsPageTests.tearDown
    _window = base.BugReportsPageTests._window
    _wait_for_results = base.BugReportsPageTests._wait_for_results

    def _saved_settings(self, window) -> dict:
        window.save_app_settings()
        return json.loads((self.root / "settings.json").read_text(encoding="utf-8"))["settings"]

    def test_never_use_and_done_are_kept_in_the_library_and_settings_json_holds_neither(self) -> None:
        window = self._window()
        page = window.bug_reports_page
        a, b = self.recordings / "a.mkv", self.recordings / "b.mkv"
        page.add_recordings([a, b])
        page.table.selectRow(0)
        page.never_use_selected()
        self.assertEqual([row.path.name for row in page.rows], ["b.mkv"])
        self.assertEqual(page.excluded_button.text(), "Never-use list (1)…")
        page.add_recordings([a])
        self.assertEqual([row.path.name for row in page.rows], ["b.mkv"])
        self.assertEqual(page.status_sentence.text(),
                         "1 recording is on your never-use list, so left out. Use Never-use list… to allow them again.")

        base.ScriptedBackend.lines = [base.PROGRESS % ("b.mkv", "Transcription completed: b.mkv")]
        page.start()
        self._wait_for_results(page)

        saved = self._saved_settings(window)
        for key in LIST_KEYS:
            self.assertNotIn(key, saved)
            self.assertNotIn(key, window.app_settings)
        self.assertIn(str(a.resolve()).lower(), window.records.never_use_keys())
        self.assertEqual(window.records.done_on(b.resolve()), TODAY)

        page.start_over()
        page.newest_count.setValue(5)
        page.add_newest_recordings()
        self.assertEqual(page.rows, [], "done and never-use recordings are not offered again")
        self.assertEqual(page.status_sentence.text(),
                         "No new recordings: the newest ones are already done or on your never-use list. "
                         "Tick Include ones already done to add them anyway.")
        page.include_done_check.setChecked(True)
        page.add_newest_recordings()
        self.assertEqual([row.path.name for row in page.rows], ["b.mkv"], "never-use still wins")
        self.assertEqual(page.table.item(0, 3).text(), f"Done on {TODAY}")

    def test_a_recording_whose_identical_copy_was_mined_counts_as_done(self) -> None:
        window = self._window()
        page = window.bug_reports_page
        here = write_recording(self.recordings / "c.mkv", seed=4)
        other_drive = self.root / "backup-drive"
        copy = write_recording(other_drive / "c-copy.mkv", seed=4)
        store_copy(window.records, here, self.recordings)
        store_copy(window.records, copy, other_drive)
        page.add_recordings([copy])
        base.ScriptedBackend.lines = [base.PROGRESS % ("c-copy.mkv", "Transcription completed: c-copy.mkv")]
        page.start()
        self._wait_for_results(page)
        page.start_over()

        for name in ("a.mkv", "b.mkv"):
            (self.recordings / name).unlink()
        page.newest_count.setValue(5)
        page.add_newest_recordings()
        self.assertEqual(page.rows, [], "the identical copy was mined already")
        page.add_recordings([here])
        self.assertEqual(page.table.item(0, 3).text(), f"Done on {TODAY}")
        page.table.selectRow(0)
        page.never_use_selected()
        self.assertNotIn(str(copy.resolve()).lower(), window.records.never_use_keys(), "never use stays per copy")

    def test_no_narration_is_kept_as_its_own_outcome_and_reads_done_as_before(self) -> None:
        window = self._window()
        page = window.bug_reports_page
        b = self.recordings / "b.mkv"
        page.add_recordings([b])
        base.ScriptedBackend.lines = [
            base.OUTCOME % ("b.mkv", "no_narration", "true", "no_narration", "b.mkv"),
            base.PROGRESS % ("b.mkv", "Building the package"),
        ]
        page.start()
        self._wait_for_results(page)
        outcomes = [row[0] for row in window.records.connection().execute(
            "SELECT outcome FROM marks WHERE kind = 'bugs_done'")]
        self.assertEqual(outcomes, ["no_narration"])
        page.start_over()
        page.add_recordings([b])
        self.assertEqual(page.table.item(0, 3).text(), f"Done on {TODAY}")

    def test_the_never_use_list_dialog_reads_the_library_and_allow_again_takes_one_off(self) -> None:
        window = self._window()
        page = window.bug_reports_page
        a, b = self.recordings / "a.mkv", self.recordings / "b.mkv"
        page.add_recordings([a, b])
        page.table.selectAll()
        page.never_use_selected()
        self.assertEqual(page.excluded_button.text(), "Never-use list (2)…")
        shown: list[tuple[str, str]] = []
        left: list[str] = []

        def allow_the_first(dialog: QDialog) -> int:
            listing = dialog.findChild(QListWidget)
            shown.extend((listing.item(i).text(), listing.item(i).toolTip()) for i in range(listing.count()))
            listing.item(0).setSelected(True)
            next(button for button in dialog.findChildren(QPushButton) if button.text() == "Allow again").click()
            left.extend(listing.item(i).text() for i in range(listing.count()))
            return 0

        with patch.object(QDialog, "exec", allow_the_first):
            page.manage_excluded()
        # Oldest first, as the settings list was: Never use takes the selected rows from the bottom up.
        self.assertEqual(shown, [("b.mkv", str(b.resolve())), ("a.mkv", str(a.resolve()))])
        self.assertEqual(left, ["a.mkv"])
        self.assertEqual(page._excluded(), [str(a.resolve())])
        self.assertEqual(page.excluded_button.text(), "Never-use list (1)…")
        self.assertEqual(page.rows, [], "allowing again never re-adds a row")
        cleared = window.records.connection().execute(
            "SELECT COUNT(*) FROM marks WHERE kind = 'never_use' AND cleared_by IS NOT NULL").fetchone()[0]
        self.assertEqual(cleared, 1, "the mark is kept, cleared")

    def test_the_lists_stay_in_the_settings_while_the_library_cannot_take_them(self) -> None:
        # The move did not check out this time: everything works as before, from settings.json.
        with patch("media_manglers_workbench.app.import_legacy_settings",
                   return_value={"status": "restored", "counts": {}, "message": "a count did not add up"}):
            window = self._window()
        page = window.bug_reports_page
        page.add_recordings([self.recordings / "a.mkv", self.recordings / "b.mkv"])
        page.table.selectRow(0)
        page.never_use_selected()
        self.assertEqual(window.app_settings[EXCLUDED_KEY], [str((self.recordings / "a.mkv").resolve())])
        self.assertEqual(window.records.never_use_keys(), set())


class PlayerLibraryTests(WindowTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.records = Records(self.root / "library")
        self.host.records = self.records
        self.host.lists_in_library = lambda: True
        self.page = FakePage(self.events)
        self.host.bug_reports_page = self.page

    def tearDown(self) -> None:
        self.records.close()
        super().tearDown()

    def _sequence_window(self):
        window = self._window()
        player = self._open(window, sequence=self._sequence(SESSION_ONE, SESSION_TWO), autoplay=True)
        player.move_to(83_000)
        return window, player

    def test_never_use_then_undo_go_through_the_library(self) -> None:
        window, _player = self._sequence_window()
        window.never_use_button.click()
        one = str(self.root / SESSION_ONE)
        self.assertIn(one.lower(), self.records.never_use_keys())
        self.assertNotIn(EXCLUDED_KEY, self.host.app_settings)
        self.assertEqual(self.page.changes, 1)
        self.assertEqual(window.windowTitle(), f"{SESSION_TWO} — Built-in player")
        self.assertEqual(window.banner_label.text(), f'You marked "{SESSION_ONE}" never-use.')

        window.undo_button.click()
        self.assertEqual(self.records.never_use_keys(), set())
        reopened = self.factory.players[-1]
        reopened.report_loaded()
        self.assertEqual(window.windowTitle(), f"{SESSION_ONE} — Built-in player")
        self.assertEqual(reopened.play_calls, 0, "back where it was, paused")
        self.assertEqual(window.never_use_button.text(), "Never use this recording")
        self.assertEqual(self.page.changes, 2)

    def test_allow_again_takes_it_off_in_the_library(self) -> None:
        window = self._window()
        self._open(window, autoplay=True)
        window.never_use_current()
        self.assertEqual(window.never_use_button.text(), "Allow again")
        self.assertEqual(window.recording_status_label.text(), "On your never-use list")
        window.never_use_button.click()
        self.assertEqual(self.records.never_use_keys(), set())
        self.assertEqual(window.never_use_button.text(), "Never use this recording")
        self.assertEqual(window.recording_status_label.text(), "Ready")

    def test_a_library_that_cannot_save_is_reported_and_does_not_advance(self) -> None:
        window, player = self._sequence_window()
        with patch.object(Records, "set_never_use", side_effect=sqlite3.OperationalError("database is locked")):
            window.never_use_current()
        self.assertIn("Could not save that — try again", window.banner_label.text())
        self.assertEqual(len(self.factory.players), 1, "not advanced")
        self.assertEqual(self.page.changes, 0)
        self.assertEqual(window.never_use_button.text(), "Never use this recording")
        window.never_use_current()
        self.assertEqual(len(self.factory.players), 2, "trying again works")

    def test_the_this_recording_row_says_done_from_the_library(self) -> None:
        self.records.mark_done("", [(self.root / SESSION_ONE, "done")], by="Find my bug reports", day="2026-10-20")
        window = self._window()
        self._open(window, autoplay=True)
        self.assertEqual(window.recording_status_label.text(), "Done on 2026-10-20")


if __name__ == "__main__":
    unittest.main()
