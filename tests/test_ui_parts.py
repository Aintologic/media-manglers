"""The shared parts every screen uses (237, governance/UI_RULES.md section 7).

Clicks go through real mouse events on a shown window (tests/qt_input.py), never by emitting a signal.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from media_manglers_workbench import theme  # noqa: E402
from media_manglers_workbench.ui_parts import (  # noqa: E402
    FlowLayout,
    InlineFeedback,
    JobBanner,
    JobInfo,
    Outcome,
    PageStack,
    SegmentedControl,
    StatusPill,
    StepBar,
    bind_action,
    button_kind,
    repolish,
    set_button_kind,
    set_work_bar,
    time_left_text,
    work_done_text,
)
from tests.qt_input import click  # noqa: E402


class _Row(QWidget):
    """A shown window with one button in a row, as a page would hold it."""

    def __init__(self, text: str = "Copy prompt for Claude Code") -> None:
        super().__init__()
        self.row = QHBoxLayout(self)
        self.button = QPushButton(text)
        self.row.addWidget(self.button)
        self.row.addStretch(1)
        self.resize(700, 80)
        self.show()
        QApplication.processEvents()


class SharedPartsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        theme.apply_theme(cls.app, "Dark", 100)

    def setUp(self) -> None:
        self.windows: list[QWidget] = []

    def tearDown(self) -> None:
        for window in self.windows:
            window.close()
            window.deleteLater()
        QApplication.processEvents()

    def _row(self, text: str = "Copy prompt for Claude Code") -> _Row:
        row = _Row(text)
        self.windows.append(row)
        return row

    # Status pill ----------------------------------------------------------------------------

    def test_a_status_pill_takes_its_colour_from_the_one_status_rule(self) -> None:
        for state, kind in (("completed", "completed"), ("no_narration", "completed"), ("failed", "failed"),
                            ("completed_with_problems", "attention"), ("pending", "waiting"),
                            ("active", "active"), ("skipped by you", "waiting")):
            with self.subTest(state=state):
                pill = StatusPill(state)
                self.assertEqual(pill.kind, kind)
                self.assertEqual(pill.kind, theme.status_kind(state))
        pill = StatusPill("failed", "Could not be used")
        self.assertEqual(pill.text(), "Could not be used")
        self.assertEqual(pill.accessibleName(), "Status: Could not be used")

    # Inline feedback and bind_action --------------------------------------------------------

    def test_feedback_shows_beside_the_button_within_a_quarter_of_a_second_and_it_cannot_fire_twice(self) -> None:
        row = self._row()
        seen: dict[str, object] = {}
        calls: list[int] = []

        def handler() -> Outcome:
            calls.append(1)
            seen["after"] = time.monotonic() - seen["clicked"]
            seen["button text"] = row.button.text()
            seen["feedback"] = (binding.feedback.state, binding.feedback.text(), binding.feedback.isVisible())
            # A second click while it works is refused.
            QTest.mouseClick(row.button, Qt.MouseButton.LeftButton)
            return Outcome.done("Prompt for Claude Code copied")

        binding = bind_action(row.button, handler, working="Copying…", done="Copied")
        seen["clicked"] = time.monotonic()
        click(row.button)
        self.assertEqual(len(calls), 1, "a click while it works is not a second run")
        self.assertLess(seen["after"], 0.25)
        self.assertEqual(seen["button text"], "Copying…")
        # 224 (Wave B2a, Decision 7): the working word shows once, on the button; the line beside it waits for
        # the result.
        self.assertEqual(seen["feedback"], (InlineFeedback.IDLE, "", False))
        # Done: the button has its words back and the line beside it says so.
        self.assertEqual(row.button.text(), "Copy prompt for Claude Code")
        self.assertEqual(binding.feedback.state, InlineFeedback.DONE)
        self.assertEqual(binding.feedback.text(), "Prompt for Claude Code copied")
        self.assertIs(binding.feedback.parentWidget(), row, "the line is in the button's own row")
        self.assertEqual(row.row.indexOf(binding.feedback), row.row.indexOf(row.button) + 1)
        self.assertEqual(binding.feedback.label.property("feedback"), "done")

    def test_done_goes_after_a_few_seconds_and_failed_stays_until_dismissed(self) -> None:
        feedback = InlineFeedback(done_seconds=0.05)
        holder = QWidget()
        QVBoxLayout(holder).addWidget(feedback)
        holder.show()
        self.windows.append(holder)
        feedback.done("Saved a moment ago")
        self.assertTrue(feedback.isVisible())
        QTest.qWait(200)
        self.assertFalse(feedback.isVisible())
        feedback.failed("Not saved: the folder is read-only", "Choose another folder, then press Save settings.")
        QTest.qWait(200)
        self.assertTrue(feedback.isVisible(), "a failure stays")
        self.assertIn("Choose another folder", feedback.text())
        self.assertTrue(feedback.dismiss_button.isVisible())
        click(feedback.dismiss_button)
        self.assertFalse(feedback.isVisible())

    def test_a_failure_says_what_went_wrong_and_what_to_do_next(self) -> None:
        row = self._row("Open package folder")
        binding = bind_action(row.button, lambda: Outcome.failed("The package folder is not there any more.",
                                                                  "Run Find bug reports again."),
                              working="Opening…", done="Opened")
        click(row.button)
        self.assertEqual(binding.feedback.state, InlineFeedback.FAILED)
        self.assertEqual(binding.feedback.text(),
                         "The package folder is not there any more. Run Find bug reports again.")

        def broken() -> None:
            raise OSError("access denied")

        other = self._row("Export drafts")
        failing = bind_action(other.button, broken, working="Exporting…", done="Exported", failed="Not exported:",
                              next_step="Check the folder.")
        click(other.button)
        self.assertEqual(failing.feedback.state, InlineFeedback.FAILED)
        self.assertEqual(failing.feedback.text(), "Not exported: access denied. Check the folder.")
        self.assertEqual(other.button.text(), "Export drafts")

    def test_a_quiet_action_says_nothing_and_a_handler_may_rename_its_button(self) -> None:
        row = self._row("Pause")
        binding = bind_action(row.button, lambda: (row.button.setText("Resume"), Outcome.quiet())[1],
                              working="Pausing…", done="Paused")
        click(row.button)
        self.assertEqual(row.button.text(), "Resume", "the handler's own words are kept")
        self.assertFalse(binding.feedback.isVisible())

    def test_rows_can_share_one_line(self) -> None:
        row = self._row("Copy prompt for Claude Code")
        second = QPushButton("Copy prompt for Codex")
        row.row.insertWidget(1, second)
        shared = InlineFeedback()
        row.row.insertWidget(2, shared)
        bind_action(row.button, lambda: Outcome.done("Claude copied"), working="Copying…", done="Copied", feedback=shared)
        bind_action(second, lambda: Outcome.done("Codex copied"), working="Copying…", done="Copied", feedback=shared)
        click(second)
        self.assertEqual(shared.text(), "Codex copied")
        click(row.button)
        self.assertEqual(shared.text(), "Claude copied")

    # Button kinds ---------------------------------------------------------------------------

    def test_the_four_button_kinds(self) -> None:
        button = QPushButton("Cancel review")
        self.assertEqual(button_kind(button), "secondary")
        for kind in ("primary", "danger", "link", "secondary"):
            set_button_kind(button, kind)
            self.assertEqual(button_kind(button), kind)
        set_button_kind(button, "primary")
        self.assertTrue(button.property("primary"), "the existing primary property is kept")
        with self.assertRaises(ValueError):
            set_button_kind(button, "huge")

    # Job banner -----------------------------------------------------------------------------

    def test_a_job_banner_shows_what_runs_its_percent_and_time_left_and_opens_that_job(self) -> None:
        banner = JobBanner()
        holder = QWidget()
        QVBoxLayout(holder).addWidget(banner)
        holder.resize(900, 120)
        holder.show()
        self.windows.append(holder)
        banner.show_job(JobInfo(token="job-7", title="Rendering a preview of v002", origin="AI Video Editor",
                                percent=42, time_left=time_left_text(65)))
        self.assertTrue(banner.isVisible())
        self.assertEqual(banner.title_label.text(), "Rendering a preview of v002")
        self.assertEqual(banner.numbers_label.text(), "42% · about 1 min left")
        self.assertEqual((banner.bar.minimum(), banner.bar.maximum(), banner.bar.value()), (0, 100, 42))
        self.assertEqual(banner.open_button.text(), "Open in Queue / Progress")
        opened: list[str] = []
        banner.open_requested.connect(opened.append)
        click(banner.open_button)
        self.assertEqual(opened, ["job-7"])
        # Not known yet: a moving bar and no made-up numbers.
        banner.show_job(JobInfo(token="job-7", title="Rendering a preview of v002", detail="Starting"))
        self.assertEqual(banner.bar.maximum(), 0)
        self.assertEqual(banner.numbers_label.text(), "Starting")

    def test_a_finished_job_says_how_it_ended_done_goes_and_failed_stays(self) -> None:
        banner = JobBanner(done_seconds=0.05)
        holder = QWidget()
        QVBoxLayout(holder).addWidget(banner)
        holder.show()
        self.windows.append(holder)
        banner.show_job(JobInfo(token="a", title="Raw bin scan"))
        banner.show_job(JobInfo(token="a", title="Raw bin scan", state="completed", detail="Scan finished"))
        self.assertEqual(banner.title_label.text(), "Done: Raw bin scan")
        self.assertEqual(banner.property("state"), "completed")
        QTest.qWait(200)
        self.assertFalse(banner.isVisible())
        banner.show_job(JobInfo(token="b", title="Raw bin scan"))
        banner.show_job(JobInfo(token="b", title="Raw bin scan", state="failed", detail="The drive is not there"))
        QTest.qWait(200)
        self.assertTrue(banner.isVisible())
        self.assertEqual(banner.title_label.text(), "Failed: Raw bin scan")
        click(banner.dismiss_button)
        self.assertFalse(banner.isVisible())

    def test_a_banner_follows_only_the_jobs_its_page_started(self) -> None:
        from PySide6.QtCore import QObject, Signal

        class Host(QObject):
            changed = Signal()

        host = Host()
        current: dict[str, JobInfo | None] = {"job": None}
        banner = JobBanner()
        banner.follow(host.changed, lambda: current["job"], "Raw Bin")
        current["job"] = JobInfo(token="1", title="Finding bug reports in 3 recordings", origin="Find Bug Reports")
        host.changed.emit()
        self.assertIsNone(banner.info)
        current["job"] = JobInfo(token="2", title="Raw bin scan", origin="Raw Bin", percent=10)
        host.changed.emit()
        self.assertEqual(banner.info.token, "2")

    def test_time_left_in_plain_words(self) -> None:
        self.assertEqual(time_left_text(None), "")
        self.assertEqual(time_left_text(20), "less than a minute left")
        self.assertEqual(time_left_text(6 * 60), "about 6 min left")
        self.assertEqual(time_left_text(2 * 3600 + 600), "about 2 h 10 min left")

    # Step bar, segmented control, wrapping rows, page area ----------------------------------

    def test_a_step_bar_marks_done_current_and_later(self) -> None:
        bar = StepBar(["Choose recording", "Prepare", "AI edits", "Watch and review", "Export"])
        bar.set_current(3)
        self.assertEqual(bar.states(), ["done", "done", "done", "current", "later"])
        self.assertEqual([mark.text() for mark in bar.marks], ["✓", "✓", "✓", "4", "5"])
        self.assertEqual(bar.texts[3].property("stepText"), "current")

    def test_a_chosen_tab_or_segment_is_measured_in_its_bold_weight(self) -> None:
        from PySide6.QtGui import QFont, QFontMetrics

        from media_manglers_workbench.ui_parts import BoldSafeButton

        plain, safe = QPushButton("General / Startup"), BoldSafeButton("General / Startup")
        bold = QFont(safe.font())
        bold.setWeight(QFont.Weight.DemiBold)
        extra = QFontMetrics(bold).horizontalAdvance(safe.text()) - safe.fontMetrics().horizontalAdvance(safe.text())
        self.assertGreaterEqual(safe.sizeHint().width(), plain.sizeHint().width() + max(0, extra))

    def test_a_segmented_control_offers_one_choice(self) -> None:
        control = SegmentedControl([(100, "100%"), (110, "110%"), (125, "125%"), (150, "150%")], name="Text size")
        holder = QWidget()
        QVBoxLayout(holder).addWidget(control)
        holder.show()
        self.windows.append(holder)
        chosen: list[object] = []
        control.changed.connect(chosen.append)
        control.set_value(100)
        click(control.buttons[125])
        self.assertEqual(chosen, [125])
        self.assertEqual(control.value(), 125)
        self.assertFalse(control.buttons[100].isChecked())
        self.assertEqual(control.buttons[150].accessibleName(), "Text size 150%")

    def test_a_button_row_wraps_instead_of_widening_the_page(self) -> None:
        holder = QWidget()
        outer = QVBoxLayout(holder)
        flow = FlowLayout()
        buttons = [QPushButton(text) for text in ("Play this version", "Render a preview", "Approve and export…",
                                                 "Open export folder")]
        for button in buttons:
            flow.addWidget(button)
        outer.addLayout(flow)
        below = QLabel("Export quality")
        outer.addWidget(below)
        holder.show()
        self.windows.append(holder)
        holder.resize(2400, 200)
        QTest.qWait(50)
        self.assertEqual(len({button.y() for button in buttons}), 1, "wide enough: one line")
        holder.resize(320, 300)
        QTest.qWait(50)
        self.assertGreater(buttons[-1].y(), buttons[0].y(), "narrow: the row wraps")
        self.assertLessEqual(holder.minimumSizeHint().width(), max(b.sizeHint().width() for b in buttons) + 40)
        self.assertGreaterEqual(below.y(), buttons[-1].geometry().bottom(), "nothing lands on what is below")

    def test_the_page_area_scrolls_each_page_and_still_names_the_page(self) -> None:
        stack = PageStack()
        first, second = QWidget(), QWidget()
        stack.addWidget(first)
        stack.addWidget(second)
        stack.setCurrentWidget(second)
        self.assertIs(stack.currentWidget(), second)
        self.assertIs(stack.scroll_for(second).widget(), second)
        self.assertTrue(stack.scroll_for(first).widgetResizable())

    # 224 (Wave B2a, 5d) ---------------------------------------------------------------------

    def test_a_box_style_given_after_a_label_is_shown_keeps_its_inner_margin(self) -> None:
        holder = self._row()
        label = QLabel("Use Inbox settings to choose at least one local source folder.")
        label.setWordWrap(True)
        holder.row.insertWidget(0, label)
        QApplication.processEvents()
        self.assertEqual(label.contentsRect(), label.rect(), "a plain label has no box")
        for state in ("error", "ready", "attention"):
            with self.subTest(state=state):
                label.setProperty("operatorState", state)
                repolish(label)
                QApplication.processEvents()
                inner, outer = label.contentsRect(), label.rect()
                # The theme's padding (8 by 10) plus its 1 px border, on every side.
                self.assertGreaterEqual(inner.left() - outer.left(), theme.px(10))
                self.assertGreaterEqual(inner.top() - outer.top(), theme.px(8))
                self.assertGreaterEqual(outer.right() - inner.right(), theme.px(10))
                self.assertGreaterEqual(outer.bottom() - inner.bottom(), theme.px(8))
        label.setProperty("operatorState", "")
        repolish(label)
        QApplication.processEvents()
        self.assertEqual(label.contentsRect(), label.rect(), "and back to plain, with no box")

    def test_how_far_a_job_got_is_said_in_what_it_counts(self) -> None:
        self.assertEqual(work_done_text(252, 1350, "seconds"), "04:12 of 22:30")
        self.assertEqual(work_done_text(4000, 4500, "seconds"), "1:06:40 of 1:15:00")
        self.assertEqual(work_done_text(12 * 1024**3, 54 * 1024**3, "bytes"), "12.0 GB of 54.0 GB")
        self.assertEqual(work_done_text(300 * 1024**2, 900 * 1024**2, "bytes"), "300 MB of 900 MB")
        self.assertEqual(work_done_text(3, 5), "3 of 5")

    def test_a_bar_holds_counts_past_what_a_progress_bar_can_hold(self) -> None:
        bar = QProgressBar()
        set_work_bar(bar, 18 * 1024**3, 54 * 1024**3)
        self.assertLessEqual(bar.maximum(), 2_147_483_647)
        self.assertEqual(round(bar.value() / bar.maximum(), 3), 0.333)
        set_work_bar(bar, 12, 20)
        self.assertEqual((bar.value(), bar.maximum()), (12, 20), "small counts are kept as they are")


class ThemeTokenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        theme.apply_theme(self.app, "Dark", 100)

    def test_the_status_meanings_stay_and_only_the_colours_moved_to_the_tokens(self) -> None:
        self.assertEqual(set(theme.STATUS_COLORS), {"active", "completed", "attention", "failed", "waiting"})
        self.assertEqual(theme.STATUS_COLORS["completed"], theme.DARK_TOKENS["done"])
        self.assertEqual(theme.STATUS_COLORS["attention"], theme.DARK_TOKENS["attention"])
        self.assertEqual(theme.STATUS_COLORS["failed"], theme.DARK_TOKENS["failed"])
        self.assertEqual(theme.STATUS_COLORS["waiting"], theme.DARK_TOKENS["waiting"])
        self.assertEqual(theme.STATUS_COLORS["active"], theme.DARK_TOKENS["accent"], "running is the accent teal")
        # The word -> kind rule (105) is unchanged.
        for state, kind in (("transcribing", "active"), ("succeeded", "completed"), ("cancelled", "attention"),
                            ("could not be used", "failed"), ("pending", "waiting"), ("paused", "attention")):
            self.assertEqual(theme.status_kind(state), kind)

    def test_the_rulebook_colours_fonts_and_sizes(self) -> None:
        # At 96 dpi the rulebook's 11, 9.5, 12.5 and 18 pt land on the nearest whole pixels: 15, 13, 17 and
        # 24 px, which are 11.25, 9.75, 12.75 and 18 pt (237: a font between two pixel sizes is drawn soft).
        dark = theme.build_stylesheet("dark", 100, dpi=96, dpr=1)
        for token in ("#0E1014", "#12151B", "#161A21", "#232833", "#2BB5C9", "#5FD3E3", "#1D2A33", "#E8EAED"):
            self.assertIn(token, dark)
        self.assertIn('font-family: "Segoe UI"; font-size: 11.25pt', dark)
        self.assertIn("font-size: 18.0pt; font-weight: 700", dark, "page titles 18 pt bold")
        self.assertIn("font-size: 12.75pt; font-weight: 600", dark, "section headings 12.5 pt semibold")
        self.assertIn("font-size: 9.75pt", dark, "small labels 9.5 pt")
        # At 144 dpi (a 150% Windows display) they are exact.
        sharp = theme.build_stylesheet("dark", 100, dpi=144, dpr=1)
        self.assertIn('font-size: 11.0pt', sharp)
        self.assertIn('font-size: 9.5pt', sharp)
        self.assertIn("border-left: 3px solid #2BB5C9", dark, "the selection bar")
        self.assertIn("border: 2px solid #2BB5C9", dark, "the focus ring")
        light = theme.build_stylesheet("light", 100)
        for token in ("#F5F7FA", "#FFFFFF", "#D9DEE5", "#14181F", "#5A6472", "#127C8C", "#E3F3F5"):
            self.assertIn(token, light)

    def test_every_drop_down_has_its_arrow_and_the_arrow_ships(self) -> None:
        for name in ("dark", "light"):
            sheet = theme.build_stylesheet(name, 100)
            self.assertIn("QComboBox::down-arrow { image: url(", sheet)
            arrow = Path(__file__).resolve().parents[1] / "src" / "media_manglers_workbench" / "assets" / f"chevron-down-{name}.svg"
            self.assertTrue(arrow.is_file())
            self.assertIn(arrow.as_posix(), sheet)

    def test_a_drop_down_draws_its_arrow(self) -> None:
        from PySide6.QtGui import QColor

        from media_manglers_workbench.widgets import WheelSafeComboBox

        theme.apply_theme(self.app, "Dark", 100)
        combo = WheelSafeComboBox()
        combo.addItems(["Auto", "Track 1"])
        combo.resize(220, 36)
        combo.show()
        QTest.qWait(50)
        image = combo.grab().toImage()
        arrow = QColor(theme.DARK_TOKENS["muted"])
        right = range(combo.width() - 28, combo.width() - 4)
        found = any(
            abs(QColor(image.pixel(x, y)).red() - arrow.red()) < 40
            and abs(QColor(image.pixel(x, y)).green() - arrow.green()) < 40
            and abs(QColor(image.pixel(x, y)).blue() - arrow.blue()) < 40
            for x in right for y in range(6, combo.height() - 6)
        )
        combo.close()
        self.assertTrue(found, "the chevron is drawn at the right of the box")

    def test_text_sizes(self) -> None:
        self.assertEqual(theme.TEXT_SIZES, (100, 110, 125, 150))
        self.assertEqual(theme.normalize_text_size(None), 100)
        self.assertEqual(theme.normalize_text_size("abc"), 100)
        self.assertEqual(theme.normalize_text_size(124), 125)
        self.assertEqual(theme.normalize_text_size(400), 150)
        self.assertEqual(theme.step_text_size(150, 1), 150)
        self.assertEqual(theme.step_text_size(100, -1), 100)
        self.assertEqual(theme.step_text_size(110, 1), 125)
        sheet = theme.build_stylesheet("dark", 150, dpi=96, dpr=1)
        self.assertIn("font-size: 16.5pt", sheet)
        self.assertIn("font-size: 27.0pt", sheet)

    def test_every_font_size_is_a_whole_number_of_screen_pixels_at_every_text_size(self) -> None:
        for dpi, dpr in ((96, 1.0), (96, 1.25), (96, 1.5), (96, 1.75), (120, 1.0), (144, 1.0), (192, 1.0)):
            for size in theme.TEXT_SIZES:
                for kind, base in theme.FONT_SIZES.items():
                    with self.subTest(dpi=dpi, dpr=dpr, size=size, kind=kind):
                        point = theme.whole_pixel_pt(base, size / 100, dpi, dpr)
                        pixels = point * dpi / 72 * dpr
                        self.assertAlmostEqual(pixels, round(pixels), places=3)
                        self.assertLess(abs(pixels - base * size / 100 * dpi / 72 * dpr), 0.51)
        # The old 13.75 pt at 125% was 18.33 px; now 13.5 pt, 18 px.
        self.assertEqual(theme.whole_pixel_pt(11, 1.25, 96, 1), 13.5)

    def test_the_rail_heights_are_in_the_stylesheet_so_a_live_text_size_change_keeps_them(self) -> None:
        button, label = theme.nav_row_heights(1.5)
        sheet = theme.build_stylesheet("dark", 150)
        self.assertIn(f"min-height: {button}px; max-height: {button}px", sheet)
        self.assertIn(f"min-height: {label}px; max-height: {label}px", sheet)

    def test_the_rail_icons_are_one_set_of_line_icons(self) -> None:
        from media_manglers_workbench.ui_parts import NAV_ICON_FOLDER, line_icon

        names = sorted(path.stem for path in NAV_ICON_FOLDER.glob("*.svg"))
        self.assertEqual(len(names), 13)
        for name in names:
            with self.subTest(icon=name):
                svg = (NAV_ICON_FOLDER / f"{name}.svg").read_text(encoding="utf-8")
                self.assertIn('stroke-width="1.8"', svg, "one stroke weight")
                self.assertIn('stroke="currentColor"', svg)
                self.assertIn('fill="none"', svg, "lines, not filled shapes")
                icon = line_icon(name, "#C9CED6", "#5FD3E3", 20)
                off = icon.pixmap(20, 20, QIcon.Mode.Normal, QIcon.State.Off).toImage()
                on = icon.pixmap(20, 20, QIcon.Mode.Normal, QIcon.State.On).toImage()
                self.assertFalse(off.isNull())
                self.assertNotEqual(off, on, "the chosen page's icon is the accent colour")

    def test_a_fixed_size_follows_the_text_size(self) -> None:
        label = QLabel("Selected source")
        theme.apply_theme(self.app, "Dark", 100)
        theme.keep_scaled(label, "setMaximumHeight", 26)
        self.assertEqual(label.maximumHeight(), 26)
        theme.apply_theme(self.app, "Dark", 150)
        self.assertEqual(label.maximumHeight(), 39)
        self.assertAlmostEqual(theme.text_scale(), 1.5)


if __name__ == "__main__":
    unittest.main()
