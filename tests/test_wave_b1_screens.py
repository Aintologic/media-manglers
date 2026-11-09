"""The two things the operator sees change in Wave B1 (224, design 5.1 items 1 and 2).

1. 275: when the library cannot be opened, one notice says so and why; Find my bug reports asks before it
   adds recordings as new (its never-use and already-done lists are not known that session); Review Media
   Inbox refuses plainly. The lists come back at the next start that opens the library.
2. F1: after a Full Review of a web address, the Inbox opened from the left menu ran New Review's source
   checks when Process new media was clicked, and refused with "Review is not ready" / "URL input is
   supported only for Full Review." Process new media now starts. Every warning pop-up is also written to
   the Workbench log.

The operator's steps are clicks on a shown window (tests/qt_input.py), never emitted signals. The one call
made in code is the Inbox's start behind its greyed-out Process new media button, which no click can reach.
"""

from __future__ import annotations

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

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton  # noqa: E402

from media_manglers.core import recording_records  # noqa: E402
from media_manglers_workbench.app import BUG_REPORTS_PAGE, WorkbenchWindow  # noqa: E402
from media_manglers_workbench.metadata import WORKFLOW_FULL_REVIEW  # noqa: E402
from media_manglers_workbench.runner import RunnerResult  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: E402
from tests.qt_input import bring_to_front, choose_in_combo, click  # noqa: E402
from tests.test_workbench_review_media_inbox import _ready_resources, _status  # noqa: E402

WEB_ADDRESS = "https://www.youtube.com/watch?v=b1example"


class QuickRunner:
    """Stands in for the backend: it records what it was asked to run and finishes at once."""

    commands: list[list[str]] = []

    def cancel(self) -> None:
        return None

    def run(self, command, on_log=None, *, cwd=None) -> RunnerResult:
        QuickRunner.commands.append(list(command.argv))
        return RunnerResult(status="succeeded", exit_code=0, stdout_lines=[], error="")


class ScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window: WorkbenchWindow | None = None
        QuickRunner.commands = []
        self.recordings = self.root / "recordings"
        self.recordings.mkdir()
        self.recording = self.recordings / "race-2026-10-29.mkv"
        self.recording.write_bytes(b"not really video")

    def tearDown(self) -> None:
        self._close()
        self.app.processEvents()
        self.temp.cleanup()

    def _close(self) -> None:
        if self.window:
            self._wait(lambda: self.window.runner_thread is None)
            self.window._closing_after_smoke = True
            self.window.close()
            self.window = None
            self.app.processEvents()

    def _wait(self, condition, seconds: float = 10.0) -> bool:
        deadline = time.monotonic() + seconds
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(20)
        return condition()

    def _window(self, *, library: Path | None = None) -> WorkbenchWindow:
        settings_path = self.root / "settings.json"
        if not settings_path.exists():
            settings_path.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
                "log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
                "output_folder": str(self.root / "output"), "review_source_folders": str(self.recordings),
                "review_inbox_folder": str(self.root / "inbox"),
                "review_local_work_root": str(self.root / "work"), "review_dedupe_mode": "Fast"}}),
                encoding="utf-8")
        self.window = WorkbenchWindow(settings_path=settings_path, profiles_dir=self.root / "profiles",
                                      runner_factory=QuickRunner, resources=_ready_resources(),
                                      review_inbox_reconciler=lambda _payload: _status(),
                                      library_root=library)
        self.window.show()
        self.app.processEvents()
        return self.window

    def _click(self, widget) -> None:
        bring_to_front(widget)
        self.assertTrue(widget.isEnabled(), f"{widget.text() if hasattr(widget, 'text') else widget} is not enabled")
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        self.app.processEvents()

    def _log(self, window: WorkbenchWindow) -> str:
        folder = self.root / "logs"
        return "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in sorted(folder.glob("*")))

    def _home_start(self, window: WorkbenchWindow, title: str) -> QPushButton:
        """The Start button on the Home card titled ``title``."""

        for button in window.findChildren(QPushButton):
            card = button.parentWidget()
            if button.text() == "Start" and card is not None and any(
                    label.text() == title for label in card.findChildren(QLabel)):
                return button
        raise AssertionError(f"no Home card {title!r} with a Start button")


class ProcessNewMediaAfterAWebFullReviewTests(ScreenTests):
    def test_full_review_of_a_web_address_then_the_inbox_from_the_left_menu_then_process_new_media(self) -> None:
        window = self._window()
        # A Full Review of a web address, clicked as the operator does: the Home card's Start, the Source step's
        # "URL" source type, the web address typed in, then on through the steps to Start review.
        self._click(self._home_start(window, "1  Full Review"))
        self.assertEqual(window.current_workflow, WORKFLOW_FULL_REVIEW)
        self._click(window.wizard_next)
        choose_in_combo(window.source_kind_combo, "URL")
        click(window.url_input_edit)
        QTest.keyClicks(window.url_input_edit, WEB_ADDRESS)
        self.app.processEvents()
        for _step in range(4):
            if not window.wizard_next.isVisible():
                break
            self._click(window.wizard_next)
        self._click(window.start_review_button)
        self.assertTrue(self._wait(lambda: window.runner_thread is None))
        self.assertEqual(len(QuickRunner.commands), 1, "the Full Review ran")
        self.assertEqual(window.run_settings.get("input_kind"), "url", "the web address is still New Review's source")

        warnings: list[str] = []

        def no_pop_up(_parent, title, text, *rest):
            warnings.append(f"{title}: {text}")
            return QMessageBox.StandardButton.Cancel

        with mock.patch.object(QMessageBox, "warning", side_effect=no_pop_up):
            # The Inbox from the left menu, not from its Home card.
            self._click(window.nav_buttons["Review Media Inbox"])
            self.assertTrue(self._wait(lambda: window.review_inbox_reconcile_thread is None))
            self._click(window.review_inbox_process_button)
            self.assertTrue(self._wait(lambda: len(QuickRunner.commands) == 2),
                            f"Process new media did not start; it showed {warnings}")
            self.assertTrue(self._wait(lambda: window.runner_thread is None))

        self.assertEqual(warnings, [], "no 'Review is not ready' pop-up")
        argv = QuickRunner.commands[-1]
        self.assertIn("-ReviewMediaInbox", argv)
        self.assertIn("Process", argv)
        self.assertNotIn(WEB_ADDRESS, argv, "the Inbox run never takes New Review's web address")
        self.assertEqual(window.progress_source.text(), "Configured folders")
        self.assertNotIn("URL input is supported only for Full Review", self._log(window))

    def test_every_warning_pop_up_is_written_to_the_workbench_log(self) -> None:
        window = self._window()
        window.start_workflow_from_home(WORKFLOW_FULL_REVIEW)
        window.run_settings.update({"input_kind": "url", "input_path": "not a web address",
                                    "output_folder": str(self.root / "full-review")})
        with mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok) as shown:
            window.start_job()
        shown.assert_called_once()
        self.assertEqual(shown.call_args[0][1], "Review is not ready")
        log = self._log(window)
        self.assertIn("Warning shown: Review is not ready:", log)
        self.assertIn("complete http:// or https:// URLs", log)


class LibraryCannotBeOpenedTests(ScreenTests):
    def _damaged_library(self) -> tuple[Path, bytes]:
        """A library that holds a never-use mark for the recording, then a damaged copy of its file."""

        library = self.root / "library"
        records = recording_records.Records(library)
        try:
            self.assertTrue(records.set_never_use(self.recording, True, by="test"))
        finally:
            records.close()
        database = recording_records.database_path(library)
        good = database.read_bytes()
        database.write_bytes(b"this is not a database " * 200)
        return library, good

    def test_one_notice_says_why_and_the_lists_come_back_at_the_next_good_start(self) -> None:
        library, good = self._damaged_library()
        window = self._window(library=library)
        self.assertIsNone(window.records)
        self.assertTrue(self._wait(lambda: getattr(window, "library_notice", None) is not None
                                   and window.library_notice.isVisible()))
        notice = window.library_notice
        self.assertEqual(notice.windowTitle(), "Your library could not be opened")
        self.assertIn("Your library could not be opened, so your never-use and already-done lists are not shown this "
                      "session", notice.text())
        self.assertIn("Nothing was lost.", notice.text())
        self.assertIn("Why: ", notice.text())
        # 224 (Wave B2a, 5d): a damaged file is said plainly; starting again would not fix it, the backups might.
        self.assertIn("Why: Your library file is damaged, so it cannot be read.", notice.text())
        self.assertIn("The app keeps daily copies in its backups folder", notice.text())
        self.assertFalse(notice.isModal(), "the Workbench still starts and works")
        self.assertIn("Warning shown: Your library could not be opened", self._log(window))
        self._close()

        recording_records.database_path(library).write_bytes(good)
        window = self._window(library=library)
        self.assertIsNotNone(window.records)
        self.assertIsNone(getattr(window, "library_notice", None))
        page = window.bug_reports_page
        self.assertTrue(page._excluded_keys(), "the never-use list is back")

    def test_any_error_opening_the_library_is_said_and_never_stops_the_start(self) -> None:
        # Before, only four kinds of error were caught there; any other one stopped the Workbench starting.
        with mock.patch("media_manglers_workbench.app.Records", side_effect=KeyError("schema_version")):
            window = self._window()
        self.assertIsNone(window.records)
        self.assertTrue(self._wait(lambda: getattr(window, "library_notice", None) is not None))
        self.assertIn("Why: 'schema_version'", window.library_notice.text())

    def test_a_later_start_up_step_that_fails_is_not_called_a_library_that_could_not_be_opened(self) -> None:
        # F12: the library is open and runs go into it; only the start-up sweep failed.
        with mock.patch.object(recording_records.Records, "sweep_interrupted",
                               side_effect=sqlite3.OperationalError("database is locked")):
            window = self._window()
        self.assertIsNotNone(window.records)
        self.assertIsNone(getattr(window, "library_notice", None))
        log = self._log(window)
        self.assertIn("The library is open, but a start-up step did not finish: database is locked", log)
        self.assertNotIn("could not be opened", log)

    def test_find_my_bug_reports_asks_before_it_adds_recordings_as_new(self) -> None:
        library, _good = self._damaged_library()
        window = self._window(library=library)
        page = window.bug_reports_page
        self._click(window.nav_buttons[BUG_REPORTS_PAGE])
        asked: list[str] = []

        def answer(choice):
            def ask(_parent, title, text, *rest):
                asked.append(title)
                return choice
            return ask

        with mock.patch.object(QMessageBox, "warning", side_effect=answer(QMessageBox.StandardButton.Cancel)):
            self._click(page.add_newest_button)
            self.assertTrue(self._wait(lambda: bool(asked)))
        self.assertEqual(asked, ["Your lists could not be read"])
        self.assertEqual(page.rows, [], "nothing was offered as new")

        asked.clear()
        with mock.patch.object(QMessageBox, "warning", side_effect=answer(QMessageBox.StandardButton.Yes)):
            self._click(page.add_newest_button)
            self.assertTrue(self._wait(lambda: bool(page.rows)))
        self.assertEqual([row.path.name for row in page.rows], [self.recording.name], "added only when asked to")

    def test_review_media_inbox_refuses_plainly_and_changes_nothing(self) -> None:
        library, _good = self._damaged_library()
        reconciled: list[dict] = []
        window = self._window(library=library)
        window.review_inbox_reconciler = lambda payload: reconciled.append(payload) or _status()
        self._click(window.nav_buttons["Review Media Inbox"])
        self.app.processEvents()
        self.assertFalse(window.review_inbox_process_button.isEnabled())
        self.assertEqual(window.review_inbox_operator_status.text(), "Needs attention")
        self.assertIn("Review Media Inbox needs your library, which could not be opened this session, so nothing "
                      "was started and nothing was changed.", window.review_inbox_attention.text())
        # The button is greyed out, so no click reaches it; the start behind it refuses as well.
        window.start_review_inbox_process()
        self.app.processEvents()
        self.assertEqual(QuickRunner.commands, [], "no Inbox run started")
        self.assertEqual(reconciled, [], "the Inbox did not even check its queue")
        self.assertFalse((self.root / "inbox").exists(), "nothing was made in the Inbox folder")


class OneWarningHelperTests(ScreenTests):
    def test_no_screen_builds_a_warning_box_itself(self) -> None:
        # F1: every warning pop-up goes through ui_parts.warn, which also writes it to the Workbench log.
        folder = Path(__file__).resolve().parents[1] / "src" / "media_manglers_workbench"
        modules = sorted(path for path in folder.glob("*.py") if path.name != "ui_parts.py")
        self.assertGreater(len(modules), 10)
        for path in modules:
            text = path.read_text(encoding="utf-8")
            with self.subTest(module=path.name):
                for spelling in ("QMessageBox.warning(", "Icon.Warning", "QMessageBox.Warning",
                                 "QMessageBox.critical(", "Icon.Critical", "QMessageBox.Critical"):
                    self.assertNotIn(spelling, text)

    def test_a_notice_that_does_not_stop_the_window_is_logged_and_opens_once_the_window_is_shown(self) -> None:
        from media_manglers_workbench.ui_parts import warn

        window = self._window()
        notice = warn(window, "A notice", "Something could not be done.\n\nWhy: a test.", wait=False)
        self.assertFalse(notice.isVisible(), "it opens from the event loop, so a window still being built is shown first")
        self.assertFalse(notice.isModal())
        self.assertEqual(notice.icon(), QMessageBox.Icon.Warning)
        self.assertTrue(self._wait(notice.isVisible))
        self.assertIn("Warning shown: A notice: Something could not be done. Why: a test.", self._log(window))
        notice.close()


if __name__ == "__main__":
    unittest.main()
