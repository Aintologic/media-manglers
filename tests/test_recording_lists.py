"""The never-use list and the already-done map, shared with the built-in player (125)."""

from __future__ import annotations

import ast
import os
from pathlib import Path, PureWindowsPath
import sys
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication, QDialog, QListWidget, QPushButton  # noqa: E402

from media_manglers_workbench import bug_reports, recording_lists  # noqa: E402
from media_manglers_workbench.bug_reports import BugReportsPage, RecordingRow  # noqa: E402
from media_manglers_workbench.recording_lists import (  # noqa: E402
    EXCLUDED_KEY,
    PROCESSED_KEY,
    add_excluded,
    excluded_keys,
    excluded_paths,
    is_excluded,
    path_key,
    processed_dates,
    processed_on,
    recording_status_text,
    remove_excluded,
)
from media_manglers_workbench.runner import RunnerResult  # noqa: E402
from media_manglers_workbench.settings import BUG_REPORT_RECORDING_LIST_KEYS  # noqa: E402

# Invented names only: this repository is public.
EXCLUDED = r"Q:\Captured Sessions\synthetic-never-use.mkv"
SESSION_ONE = r"Q:\Captured Sessions\synthetic-session-one.mkv"
SESSION_TWO = r"Q:\Captured Sessions\synthetic-session-two.mkv"


class PurityTests(unittest.TestCase):
    def test_the_module_imports_no_qt_and_no_project_module(self) -> None:
        """It sits at the bottom of the import graph, so the player, the opener
        and Find my bug reports can all import it without a cycle."""

        tree = ast.parse(Path(recording_lists.__file__).read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = ["." * node.level + (node.module or "")]
            else:
                continue
            offenders += [name for name in names if name.startswith((".", "PySide6", "media_manglers"))]
        self.assertEqual(offenders, [])

    def test_the_setting_names_are_the_ones_kept_on_this_pc(self) -> None:
        # settings.py keeps these two keys out of exports, imports and saved
        # profiles; a renamed key here would quietly lose that protection.
        self.assertEqual((EXCLUDED_KEY, PROCESSED_KEY), tuple(BUG_REPORT_RECORDING_LIST_KEYS))

    def test_find_my_bug_reports_uses_the_same_key_rule(self) -> None:
        self.assertIs(bug_reports._path_key, path_key)


class PathKeyTests(unittest.TestCase):
    def test_the_key_is_the_text_lower_cased(self) -> None:
        self.assertEqual(path_key(SESSION_ONE.upper()), SESSION_ONE.lower())
        self.assertEqual(path_key(Path(SESSION_ONE)), str(Path(SESSION_ONE)).lower())
        self.assertEqual(path_key(""), "")
        # A key is its own key, so a caller may hand over keys or paths alike.
        self.assertEqual(path_key(path_key(SESSION_ONE.upper())), path_key(SESSION_ONE))

    def test_a_path_spells_its_own_slashes(self) -> None:
        forward = SESSION_ONE.replace("\\", "/")
        self.assertEqual(path_key(PureWindowsPath(forward)), SESSION_ONE.lower())
        # Plain text is taken as it is. Every caller hands over a Path or a
        # resolved path's text, so nothing here guesses at what a slash means.
        self.assertEqual(path_key(forward), forward.lower())


class NeverUseListTests(unittest.TestCase):
    def test_a_missing_key_reads_as_an_empty_list(self) -> None:
        settings: dict[str, Any] = {}
        self.assertEqual(excluded_paths(settings), [])
        self.assertEqual(excluded_keys(settings), set())
        self.assertFalse(is_excluded(settings, SESSION_ONE))
        self.assertFalse(remove_excluded(settings, SESSION_ONE))
        self.assertEqual(settings, {}, "reading never writes")

    def test_a_value_of_the_wrong_type_reads_as_an_empty_list(self) -> None:
        for value in (None, "", SESSION_ONE, 7, 1.5, True, {SESSION_ONE: "2026-01-02"}):
            with self.subTest(value=value):
                settings = {EXCLUDED_KEY: value}
                self.assertEqual(excluded_paths(settings), [])
                self.assertEqual(excluded_keys(settings), set())
                self.assertFalse(is_excluded(settings, SESSION_ONE))
                self.assertFalse(remove_excluded(settings, SESSION_ONE))

    def test_settings_that_are_not_a_mapping_never_raise(self) -> None:
        for settings in (None, [], "settings", 7):
            with self.subTest(settings=settings):
                self.assertEqual(excluded_paths(settings), [])
                self.assertEqual(excluded_keys(settings), set())
                self.assertFalse(is_excluded(settings, SESSION_ONE))
                self.assertFalse(add_excluded(settings, SESSION_ONE))
                self.assertFalse(remove_excluded(settings, SESSION_ONE))
                self.assertEqual(processed_dates(settings), {})
                self.assertEqual(processed_on(settings, SESSION_ONE), "")
                self.assertEqual(recording_status_text(settings, SESSION_ONE), "Ready")

    def test_members_that_are_not_text_are_ignored(self) -> None:
        settings = {EXCLUDED_KEY: [SESSION_ONE, None, 7, True, ["nested"], {"a": 1}, "", "   ", Path(SESSION_TWO)]}
        self.assertEqual(excluded_paths(settings), [SESSION_ONE, str(Path(SESSION_TWO))])
        self.assertTrue(is_excluded(settings, SESSION_TWO))
        self.assertFalse(is_excluded(settings, "None"))
        self.assertFalse(is_excluded(settings, ""))

    def test_the_list_handed_back_is_a_copy(self) -> None:
        settings = {EXCLUDED_KEY: [SESSION_ONE]}
        excluded_paths(settings).append(SESSION_TWO)
        self.assertEqual(settings[EXCLUDED_KEY], [SESSION_ONE])

    def test_case_never_matters(self) -> None:
        settings = {EXCLUDED_KEY: [SESSION_ONE]}
        for spelling in (SESSION_ONE, SESSION_ONE.upper(), SESSION_ONE.lower(), Path(SESSION_ONE.upper())):
            with self.subTest(spelling=spelling):
                self.assertTrue(is_excluded(settings, spelling))
        self.assertEqual(excluded_keys(settings), {SESSION_ONE.lower()})
        self.assertFalse(is_excluded(settings, SESSION_TWO))

    def test_slashes_follow_the_path_key_rule(self) -> None:
        settings = {EXCLUDED_KEY: [SESSION_ONE]}
        forward = SESSION_ONE.replace("\\", "/")
        self.assertTrue(is_excluded(settings, PureWindowsPath(forward)))
        self.assertFalse(is_excluded(settings, forward), "plain text is compared as it is")

    def test_add_stores_the_text_exactly_as_given(self) -> None:
        settings: dict[str, Any] = {}
        mixed = r"Q:\Captured Sessions\Synthetic-Session-ONE.mkv"
        self.assertTrue(add_excluded(settings, mixed))
        self.assertEqual(settings[EXCLUDED_KEY], [mixed], "not lower-cased, not resolved, not tidied")
        self.assertTrue(add_excluded(settings, Path(SESSION_TWO)))
        self.assertEqual(settings[EXCLUDED_KEY], [mixed, str(Path(SESSION_TWO))], "oldest first")

    def test_add_twice_keeps_one_entry(self) -> None:
        settings: dict[str, Any] = {}
        self.assertTrue(add_excluded(settings, EXCLUDED))
        self.assertFalse(add_excluded(settings, EXCLUDED))
        self.assertFalse(add_excluded(settings, EXCLUDED.upper()))
        self.assertFalse(add_excluded(settings, Path(EXCLUDED.lower())))
        self.assertEqual(settings[EXCLUDED_KEY], [EXCLUDED])

    def test_add_never_appends_to_the_list_it_found(self) -> None:
        # The stored list can be shared with a defaults dictionary.
        original = [SESSION_ONE]
        settings = {EXCLUDED_KEY: original}
        self.assertTrue(add_excluded(settings, SESSION_TWO))
        self.assertEqual(original, [SESSION_ONE])
        self.assertEqual(settings[EXCLUDED_KEY], [SESSION_ONE, SESSION_TWO])

    def test_add_repairs_a_value_of_the_wrong_type(self) -> None:
        for value in (None, "text", 7, {"a": 1}, [None, 7]):
            with self.subTest(value=value):
                settings = {EXCLUDED_KEY: value}
                self.assertTrue(add_excluded(settings, SESSION_ONE))
                self.assertEqual(settings[EXCLUDED_KEY], [SESSION_ONE])

    def test_add_refuses_a_blank_path(self) -> None:
        settings: dict[str, Any] = {}
        self.assertFalse(add_excluded(settings, ""))
        self.assertFalse(add_excluded(settings, "   "))
        self.assertEqual(settings, {})

    def test_remove_takes_every_spelling_of_the_recording(self) -> None:
        settings = {EXCLUDED_KEY: [SESSION_ONE, SESSION_TWO, SESSION_ONE.upper()]}
        self.assertTrue(remove_excluded(settings, Path(SESSION_ONE.lower())))
        self.assertEqual(settings[EXCLUDED_KEY], [SESSION_TWO])
        self.assertFalse(is_excluded(settings, SESSION_ONE))

    def test_remove_absent_changes_nothing(self) -> None:
        stored = [SESSION_ONE]
        settings = {EXCLUDED_KEY: stored}
        self.assertFalse(remove_excluded(settings, SESSION_TWO))
        self.assertIs(settings[EXCLUDED_KEY], stored)
        self.assertEqual(stored, [SESSION_ONE])
        self.assertFalse(remove_excluded(settings, ""))

    def test_add_then_remove_round_trips(self) -> None:
        settings: dict[str, Any] = {}
        add_excluded(settings, SESSION_ONE)
        add_excluded(settings, SESSION_TWO)
        self.assertTrue(remove_excluded(settings, SESSION_ONE.upper()))
        self.assertFalse(remove_excluded(settings, SESSION_ONE))
        self.assertEqual(settings[EXCLUDED_KEY], [SESSION_TWO])
        self.assertTrue(add_excluded(settings, SESSION_ONE), "allowed again means it can be marked again")


class AlreadyDoneTests(unittest.TestCase):
    def test_a_missing_key_means_never_done(self) -> None:
        self.assertEqual(processed_dates({}), {})
        self.assertEqual(processed_on({}, SESSION_ONE), "")
        self.assertEqual(recording_status_text({}, SESSION_ONE), "Ready")

    def test_a_value_of_the_wrong_type_means_never_done(self) -> None:
        for value in (None, "", "2026-01-02", 7, True, [SESSION_ONE], [[SESSION_ONE, "2026-01-02"]]):
            with self.subTest(value=value):
                settings = {PROCESSED_KEY: value}
                self.assertEqual(processed_dates(settings), {})
                self.assertEqual(processed_on(settings, SESSION_ONE), "")
                self.assertEqual(recording_status_text(settings, SESSION_ONE), "Ready")

    def test_entries_that_are_not_text_are_ignored(self) -> None:
        settings = {
            PROCESSED_KEY: {
                SESSION_ONE: "2026-01-02",
                SESSION_TWO: None,
                EXCLUDED: 20260102,
                7: "2026-01-03",
                "": "2026-01-04",
                r"Q:\Captured Sessions\synthetic-blank-date.mkv": "  ",
            }
        }
        self.assertEqual(processed_dates(settings), {SESSION_ONE.lower(): "2026-01-02"})
        self.assertEqual(processed_on(settings, SESSION_TWO), "")
        self.assertEqual(recording_status_text(settings, EXCLUDED), "Ready")

    def test_the_date_is_found_whatever_the_case(self) -> None:
        # Find my bug reports stores the path as this PC spells it.
        stored = {r"Q:\Captured Sessions\Synthetic-Session-ONE.mkv": "2026-01-02"}
        settings = {PROCESSED_KEY: stored}
        for spelling in (SESSION_ONE, SESSION_ONE.upper(), Path(SESSION_ONE.lower())):
            with self.subTest(spelling=spelling):
                self.assertEqual(processed_on(settings, spelling), "2026-01-02")
        self.assertEqual(processed_on(settings, SESSION_TWO), "")
        self.assertEqual(
            stored,
            {r"Q:\Captured Sessions\Synthetic-Session-ONE.mkv": "2026-01-02"},
            "the stored map is never rewritten by a lookup",
        )

    def test_slashes_follow_the_path_key_rule(self) -> None:
        settings = {PROCESSED_KEY: {SESSION_ONE: "2026-01-02"}}
        forward = SESSION_ONE.replace("\\", "/")
        self.assertEqual(processed_on(settings, PureWindowsPath(forward)), "2026-01-02")
        self.assertEqual(processed_on(settings, forward), "")

    def test_status_text_is_ready_or_done_on_the_date(self) -> None:
        settings = {PROCESSED_KEY: {SESSION_ONE: "2026-01-02"}, EXCLUDED_KEY: [SESSION_TWO]}
        self.assertEqual(recording_status_text(settings, SESSION_ONE.upper()), "Done on 2026-01-02")
        self.assertEqual(recording_status_text(settings, SESSION_TWO), "Ready")


class _HostThatCannotSave:
    """Just enough of the Workbench window for BugReportsPage to be built."""

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self.app_settings: dict[str, Any] = {} if settings is None else settings

    def open_current_log(self) -> None:
        """The results view wires a button to this while the page is built."""


class _StandInHost(_HostThatCannotSave):
    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        super().__init__(settings)
        self.saves = 0
        self.save_error: OSError | None = None

    def save_app_settings(self) -> None:
        if self.save_error is not None:
            raise self.save_error
        self.saves += 1


class BugReportsPageListTests(unittest.TestCase):
    """The page against a stand-in host: no Workbench window is built here."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        # No recording is written unless a test needs the file to be there. The
        # rows only need paths on a local disk, so the page's size lookup
        # fails at once instead of probing a drive.
        self.temp = tempfile.TemporaryDirectory()
        folder = Path(self.temp.name) / "Captured Sessions"
        self.one = folder / "synthetic-session-one.mkv"
        self.two = folder / "Synthetic-Session-TWO.mkv"
        self.three = folder / "synthetic-session-three.mkv"
        self.host = _StandInHost()
        self.page = BugReportsPage(self.host)

    def tearDown(self) -> None:
        self.page.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def _show_rows(self, *paths: Path) -> None:
        self.page.rows = [RecordingRow(path=path) for path in paths]
        self.page._render_choose_table()

    def _names(self) -> list[str]:
        return [row.path.name for row in self.page.rows]

    def _table_names(self) -> list[str]:
        table = self.page.table
        return [table.item(index, 0).text() for index in range(table.rowCount())]

    def test_idle_rows_are_dropped_by_path_key(self) -> None:
        self._show_rows(self.one, self.two, self.three)
        # The player hands over the path as IT spells it, never a row number.
        add_excluded(self.host.app_settings, str(self.two).lower())
        self.page.recording_lists_changed()
        self.assertEqual(self._names(), [self.one.name, self.three.name])
        self.assertEqual(self._table_names(), [self.one.name, self.three.name])

    def test_nothing_on_the_list_leaves_every_row(self) -> None:
        self._show_rows(self.one, self.two)
        self.page.recording_lists_changed()
        self.assertEqual(self._names(), [self.one.name, self.two.name])
        self.assertEqual(self._table_names(), [self.one.name, self.two.name])

    def test_rows_are_left_alone_while_a_run_is_going(self) -> None:
        self._show_rows(self.one, self.two, self.three)
        self.page._render_working_table()
        self.page.running = True
        rows = self.page.rows
        before = list(rows)
        add_excluded(self.host.app_settings, str(self.two))
        self.page.recording_lists_changed()
        # The working table, the Queue / Progress items and Skip selected all
        # index into this very list while a run is going.
        self.assertIs(self.page.rows, rows)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(now is then for now, then in zip(rows, before)))
        self.assertEqual(self.page.table.rowCount(), 3)
        self.assertEqual(self.page.working_table.rowCount(), 3)
        self.assertEqual(self.page.excluded_button.text(), "Never-use list (1)…")
        self.assertFalse(self.page.start_button.isEnabled())

        # Never-use is about future runs: once this one is over it applies.
        self.page.running = False
        self.page.recording_lists_changed()
        self.assertEqual(self._names(), [self.one.name, self.three.name])

    def _mark_never_use_while_running(self) -> None:
        self._show_rows(self.one, self.two, self.three)
        self.page._render_working_table()
        self.page.running = True
        # From the built-in player, mid-run: the rows stay as they are.
        add_excluded(self.host.app_settings, str(self.two))
        self.page.recording_lists_changed()
        self.assertEqual(len(self.page.rows), 3)

    def test_a_never_use_made_during_a_run_is_gone_from_continue_when_the_run_is_stopped(self) -> None:
        self._mark_never_use_while_running()
        # Continue is only offered while the stopped run's folder is there.
        self.page.run_folder = Path(self.temp.name) / "synthetic-stopped-run"
        self.page.run_folder.mkdir()

        self.page.on_finished(RunnerResult(status="cancelled", exit_code=None))

        # Nobody calls recording_lists_changed() by hand here: the end of the
        # run has to do it, or Continue would process the never-use recording.
        self.assertFalse(self.page.running)
        self.assertEqual(self.page.continue_folder, self.page.run_folder)
        self.assertEqual(self.page.start_button.text(), "Continue")
        self.assertEqual(self._names(), [self.one.name, self.three.name])
        self.assertEqual(self._table_names(), [self.one.name, self.three.name])
        self.assertEqual(
            self.host.app_settings["bug_report_stopped_run"]["recordings"],
            [str(self.one), str(self.three)],
        )
        self.assertGreaterEqual(self.host.saves, 1, "the stopped-run record reached the disk")

    def test_a_never_use_made_during_a_run_is_gone_when_the_run_stops_with_nothing_to_continue(self) -> None:
        self._mark_never_use_while_running()
        self.page.run_folder = None

        self.page.on_finished(RunnerResult(status="cancelled", exit_code=None))

        self.assertIsNone(self.page.continue_folder)
        self.assertEqual(self._names(), [self.one.name, self.three.name])
        self.assertEqual(self._table_names(), [self.one.name, self.three.name])

    def test_a_stopped_run_is_restored_without_a_recording_marked_never_use_since(self) -> None:
        folder = Path(self.temp.name) / "synthetic-stopped-run"
        folder.mkdir()
        # The rows of a stopped run come back only for files that are there.
        for path in (self.one, self.two):
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"not really video")
        self.host.app_settings["bug_report_stopped_run"] = {
            "folder": str(folder),
            "recordings": [str(self.one), str(self.two)],
            "tracks": {},
        }
        # Marked after the run stopped; the saved record still names it.
        add_excluded(self.host.app_settings, str(self.two).upper())

        self.page._restore_stopped_run()

        self.assertEqual(self.page.continue_folder, folder)
        self.assertEqual(self._names(), [self.one.name])

    def test_the_caption_follows_the_list(self) -> None:
        self._show_rows(self.one)
        self.assertEqual(self.page.excluded_button.text(), "Never-use list…")
        add_excluded(self.host.app_settings, str(self.two))
        add_excluded(self.host.app_settings, str(self.three))
        self.page.recording_lists_changed()
        self.assertEqual(self.page.excluded_button.text(), "Never-use list (2)…")
        remove_excluded(self.host.app_settings, str(self.two))
        remove_excluded(self.host.app_settings, str(self.three))
        self.page.recording_lists_changed()
        self.assertEqual(self.page.excluded_button.text(), "Never-use list…")
        self.assertEqual(self._names(), [self.one.name], "allowing again never re-adds a row")

    def test_safe_after_the_rows_were_rebuilt_or_reordered(self) -> None:
        self._show_rows(self.one, self.two, self.three)
        # The player remembers only the path. Meanwhile the page rebuilds its
        # rows as new objects and in another order, so a row number or a row
        # object kept from earlier would point at the wrong recording.
        marked = str(self.one)
        self.page.rows = [RecordingRow(path=path) for path in (self.three, self.one, self.two)]
        self.page._render_choose_table()
        add_excluded(self.host.app_settings, marked)
        self.page.recording_lists_changed()
        self.assertEqual(self._names(), [self.three.name, self.two.name])
        self.assertEqual(self._table_names(), [self.three.name, self.two.name])

    def test_safe_when_the_row_is_already_gone(self) -> None:
        self._show_rows(self.one, self.two)
        del self.page.rows[0]
        add_excluded(self.host.app_settings, str(self.one))
        self.page.recording_lists_changed()
        self.assertEqual(self._names(), [self.two.name])
        self.assertEqual(self._table_names(), [self.two.name], "the table is redrawn from the rows")
        self.page.recording_lists_changed()
        self.assertEqual(self._names(), [self.two.name], "telling it twice is harmless")

        self.page.rows = []
        self.page.recording_lists_changed()
        self.assertEqual(self.page.rows, [])
        self.assertEqual(self.page.table.rowCount(), 0)
        self.assertFalse(self.page.start_button.isEnabled())

    def test_the_page_reads_the_settings_the_host_has_now(self) -> None:
        self._show_rows(self.one, self.two)
        # Importing settings replaces the host's whole dictionary.
        self.host.app_settings = {EXCLUDED_KEY: [str(self.one)], PROCESSED_KEY: {str(self.two): "2026-01-02"}}
        self.assertEqual(self.page._excluded(), [str(self.one)])
        self.assertEqual(self.page._excluded_keys(), {path_key(self.one)})
        self.assertEqual(self.page._processed(), {path_key(self.two): "2026-01-02"})
        self.page.recording_lists_changed()
        self.assertEqual(self._names(), [self.two.name])

    def test_the_status_column_says_what_the_shared_helper_says(self) -> None:
        self.host.app_settings[PROCESSED_KEY] = {str(self.two).upper(): "2026-01-02"}
        self._show_rows(self.one, self.two)
        for index, path in enumerate((self.one, self.two)):
            self.assertEqual(
                self.page.table.item(index, 3).text(),
                recording_status_text(self.host.app_settings, path),
            )
        self.assertEqual(self.page.table.item(1, 3).text(), "Done on 2026-01-02")

    def test_never_use_selected_stores_each_path_as_the_row_has_it(self) -> None:
        self._show_rows(self.one, self.two, self.three)
        self.page.table.item(0, 0).setSelected(True)
        self.page.table.item(2, 0).setSelected(True)
        self.page.never_use_selected()
        self.assertEqual(self._names(), [self.two.name], "the rows either side went, not the one between")
        self.assertEqual(sorted(self.host.app_settings[EXCLUDED_KEY]), sorted([str(self.one), str(self.three)]))
        self.assertEqual(self.host.saves, 1)
        self.assertEqual(self.page.excluded_button.text(), "Never-use list (2)…")

    def test_allow_again_takes_it_off_the_list_and_refreshes_the_caption(self) -> None:
        self.host.app_settings[EXCLUDED_KEY] = [str(self.one), str(self.two)]
        self._show_rows(self.three)
        self.assertEqual(self.page.excluded_button.text(), "Never-use list (2)…")
        left_showing: list[str] = []

        def allow_the_first(dialog: QDialog) -> int:
            # Stands in for the modal loop, so no dialog is ever shown.
            listing = dialog.findChild(QListWidget)
            listing.item(0).setSelected(True)
            allow = next(button for button in dialog.findChildren(QPushButton) if button.text() == "Allow again")
            allow.click()
            left_showing.extend(listing.item(index).text() for index in range(listing.count()))
            return 0

        with patch.object(QDialog, "exec", allow_the_first):
            self.page.manage_excluded()
        self.assertEqual(self.host.app_settings[EXCLUDED_KEY], [str(self.two)])
        self.assertEqual(left_showing, [self.two.name])
        self.assertEqual(self.host.saves, 1)
        self.assertEqual(self.page.excluded_button.text(), "Never-use list (1)…")
        self.assertEqual(self._names(), [self.three.name], "allowing again never re-adds a row")

    def test_save_settings_says_whether_it_saved(self) -> None:
        self.assertIs(self.page._save_settings(), True)
        self.assertEqual(self.host.saves, 1)
        self.host.save_error = OSError("synthetic: the disk is full")
        self.assertIs(self.page._save_settings(), False)
        self.assertEqual(self.host.saves, 1)

    def test_a_host_that_cannot_save_counts_as_a_failed_save(self) -> None:
        no_saver = _HostThatCannotSave()
        not_callable = _HostThatCannotSave()
        not_callable.save_app_settings = None
        for host in (no_saver, not_callable):
            with self.subTest(host=vars(host)):
                page = BugReportsPage(host)
                try:
                    self.assertIs(page._save_settings(), False)
                finally:
                    page.deleteLater()


if __name__ == "__main__":
    unittest.main()
