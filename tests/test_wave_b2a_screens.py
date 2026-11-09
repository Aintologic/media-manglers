"""What the operator sees change in Wave B2a (224, plan 5d and note 1), on a shown window.

1. The Inbox's red error box and green "Ready for Codex review" box keep their inner margin: the text no longer
   touches the outline.
2. "Needs attention" is said once: with nothing being measured the Inbox shows no bar, only its heading.
3. One working word per button (Decision 7): while "Add newest" works, the button says "Adding…" and the line
   beside it does not say it again behind the pop-up.
4. When the library cannot be opened, the notice says why in plain words (the raw text is kept in the log),
   and does not call lists unseen that are still in the settings (note 12).
5. An Inbox run always shows "Configured folders" in Queue / Progress, never New Review's file (note 1).

Clicks go through real input events (tests/qt_input.py); the states the operator meets are set up, not
emitted.
"""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QLabel, QMessageBox  # noqa: E402

from media_manglers.core import recording_records  # noqa: E402
from media_manglers_workbench import theme  # noqa: E402
from media_manglers_workbench.app import BUG_REPORTS_PAGE  # noqa: E402
from tests.test_wave_b1_screens import QuickRunner, ScreenTests  # noqa: E402
from tests.test_workbench_review_media_inbox import _status  # noqa: E402


class InboxBoxesTests(ScreenTests):
    def setUp(self) -> None:
        super().setUp()
        theme.apply_theme(self.app, "Dark", 100)

    def _inner_margin(self, label) -> tuple[int, int, int, int]:
        inner, outer = label.contentsRect(), label.rect()
        return (inner.left() - outer.left(), inner.top() - outer.top(), outer.right() - inner.right(),
                outer.bottom() - inner.bottom())

    def test_the_error_box_and_the_ready_box_keep_their_inner_margin(self) -> None:
        window = self._window()
        self._click(window.nav_buttons["Review Media Inbox"])
        self.assertTrue(self._wait(lambda: window.review_inbox_reconcile_thread is None))
        window._apply_review_inbox_status(_status(
            operator_status="Needs attention",
            attention={"message": "Use Inbox settings to choose at least one local source folder."}))
        self.app.processEvents()
        box = window.review_inbox_attention
        self.assertTrue(box.isVisible())
        self.assertEqual(box.property("operatorState"), "error")
        left, top, right, bottom = self._inner_margin(box)
        self.assertGreaterEqual(min(left, right), theme.px(10), "text pressed against the red outline")
        self.assertGreaterEqual(min(top, bottom), theme.px(8))
        window._apply_review_inbox_status(_status(operator_status="Ready for Codex review"))
        self.app.processEvents()
        heading = window.review_inbox_operator_status
        self.assertEqual(heading.property("operatorState"), "ready")
        left, top, right, bottom = self._inner_margin(heading)
        self.assertGreaterEqual(min(left, right), theme.px(10), "text pressed against the green outline")
        self.assertGreaterEqual(min(top, bottom), theme.px(8))

    def test_needs_attention_is_said_once_with_no_bar_while_nothing_is_measured(self) -> None:
        window = self._window()
        self._click(window.nav_buttons["Review Media Inbox"])
        self.assertTrue(self._wait(lambda: window.review_inbox_reconcile_thread is None))
        window._apply_review_inbox_status(_status(
            operator_status="Needs attention", attention={"message": "Use Inbox settings to choose a folder."}))
        self.app.processEvents()
        self.assertEqual(window.review_inbox_operator_status.text(), "Needs attention")
        self.assertTrue(window.review_inbox_operator_status.isVisible())
        self.assertFalse(window.review_inbox_progress_bar.isVisible(), "no second 'Needs attention' on a bar")
        shown = [label.text() for label in window.pages["Review Media Inbox"].findChildren(type(
            window.review_inbox_operator_status)) if label.isVisible()]
        self.assertEqual(shown.count("Needs attention"), 1)
        for idle in ("Done", "Waiting on Codex"):
            with self.subTest(status=idle):
                window._apply_review_inbox_status(_status(operator_status=idle))
                self.app.processEvents()
                self.assertFalse(window.review_inbox_progress_bar.isVisible())
        # Something measured: the bar is back.
        window._apply_review_inbox_status(_status(operator_status="Processing", run_state={
            "active": True, "current_source_total": 3, "completed_count": 1}))
        self.app.processEvents()
        self.assertTrue(window.review_inbox_progress_bar.isVisible())
        self.assertEqual(window.review_inbox_progress_bar.format(), "1 of 3")


class OneWorkingWordTests(ScreenTests):
    def test_add_newest_says_adding_once_on_the_button_never_again_beside_it(self) -> None:
        window = self._window()
        page = window.bug_reports_page
        self._click(window.nav_buttons[BUG_REPORTS_PAGE])
        seen: list[tuple[str, str]] = []

        def pop_up(_parent, title, text, *rest):
            # What is on screen behind the pop-up while Add newest works: the button, and every feedback line.
            beside = [label.text() for label in page.findChildren(QLabel)
                      if label.objectName() == "inlineFeedbackText" and label.isVisible()]
            seen.append((page.add_newest_button.text(), " ".join(beside)))
            return QMessageBox.StandardButton.Cancel

        with mock.patch.object(page, "_lists_unreadable", return_value=True), \
                mock.patch.object(QMessageBox, "warning", side_effect=pop_up):
            self._click(page.add_newest_button)
            self.assertTrue(self._wait(lambda: bool(seen)))
        button_text, beside = seen[0]
        self.assertEqual(button_text, "Adding…")
        self.assertNotIn("Adding", beside, "the working word is said once, on the button")
        self.assertEqual(page.add_newest_button.text(), "Add newest", "its words are back afterwards")


class LibraryNoticeTests(ScreenTests):
    def _damaged(self) -> Path:
        library = self.root / "library"
        recording_records.Records(library).close()
        recording_records.database_path(library).write_bytes(b"this is not a database " * 200)
        return library

    def test_a_damaged_library_is_said_in_plain_words_and_the_raw_reason_is_kept_in_the_log(self) -> None:
        window = self._window(library=self._damaged())
        self.assertTrue(self._wait(lambda: getattr(window, "library_notice", None) is not None))
        text = window.library_notice.text()
        self.assertIn("Why: Your library file is damaged, so it cannot be read.", text)
        self.assertIn("Starting again will not fix this. The app keeps daily copies in its backups folder:", text)
        self.assertIn(str(self.root / "library" / "backups"), text)
        self.assertNotIn("file is not a database", text, "the raw text is not the reason on screen")
        self.assertIn("file is not a database", self._log(window), "it is kept in the log")

    def test_lists_still_in_the_settings_are_not_called_unseen(self) -> None:
        settings = self.root / "settings.json"
        self._window().close()
        self.window = None
        import json  # noqa: PLC0415

        data = json.loads(settings.read_text(encoding="utf-8"))
        data["settings"]["bug_report_excluded_recordings"] = [str(self.recording)]
        settings.write_text(json.dumps(data), encoding="utf-8")
        window = self._window(library=self._damaged())
        self.assertTrue(self._wait(lambda: getattr(window, "library_notice", None) is not None))
        text = window.library_notice.text()
        self.assertNotIn("not shown this session", text)
        self.assertIn("still in your settings, so Find my bug reports uses them as before", text)
        self.assertIn("Review Media Inbox does not run this session.", text)

    def test_add_newest_does_not_ask_while_the_lists_are_read_from_the_settings(self) -> None:
        # 224 (Wave B2a review, note 12): its question said the lists were not shown, though they were read.
        import json  # noqa: PLC0415

        settings = self.root / "settings.json"
        self._window().close()
        self.window = None
        done_before = self.recordings / "done-before.mkv"
        done_before.write_bytes(b"not really video")
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["settings"]["bug_report_excluded_recordings"] = [str(done_before)]
        settings.write_text(json.dumps(data), encoding="utf-8")
        window = self._window(library=self._damaged())
        page = window.bug_reports_page
        self._click(window.nav_buttons[BUG_REPORTS_PAGE])
        asked: list[str] = []

        def ask(_parent, title, text, *rest):
            asked.append(title)
            return QMessageBox.StandardButton.Cancel

        with mock.patch.object(QMessageBox, "warning", side_effect=ask):
            self._click(page.add_newest_button)
            self.assertTrue(self._wait(lambda: bool(page.rows) or bool(asked)))
        self.assertEqual(asked, [], "no 'Your lists could not be read' question")
        self.assertEqual([row.path.name for row in page.rows], [self.recording.name],
                         "the never-use list from the settings still applies")


class InboxRunSourceTests(ScreenTests):
    def test_an_inbox_run_shows_configured_folders_never_new_reviews_file(self) -> None:
        window = self._window()
        # What New Review's source box still holds from an earlier run: a local recording.
        window.run_settings.update({"input_kind": "local", "input_path": str(self.recording)})
        self._click(window.nav_buttons["Review Media Inbox"])
        self.assertTrue(self._wait(lambda: window.review_inbox_reconcile_thread is None))
        self._click(window.review_inbox_process_button)
        self.assertTrue(self._wait(lambda: bool(QuickRunner.commands)))
        self.assertTrue(self._wait(lambda: window.runner_thread is None))
        self.assertIn("-ReviewMediaInbox", QuickRunner.commands[-1])
        self.assertEqual(window.progress_source.text(), "Configured folders")
        self.assertNotIn(str(self.recording), window.progress_queue_items, "New Review's file is not its queue")
        self.assertNotIn(self.recording.name, [window.progress_queue_table.item(row, 0).text()
                                               for row in range(window.progress_queue_table.rowCount())])


if __name__ == "__main__":
    unittest.main()
