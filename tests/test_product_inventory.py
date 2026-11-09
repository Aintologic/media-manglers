"""Product inventory: what the Workbench offers, so no feature can quietly move, hide or drop it.

Governance (CURRENT_PROJECT_TRUTH.md, Product Continuity): new functionality is additive by
default, and a product-inventory test of navigation, Home, workflows and settings guards it (150).

Two lists, kept apart on purpose:

- ``EXPECTED_*``: what the application is supposed to offer. Changing one of these is a change
  to existing user-facing behaviour and needs the operator's approval.
- ``KNOWN_GAPS``: deficiencies that exist today and are tracked for correction. They are recorded
  so the test stays honest, never endorsed as correct. When a gap is fixed, its test here fails
  and asks for the entry to move into the expected lists in the same pull request.

Clicks go through real mouse events on a shown window, never by emitting signals.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.bug_reports import NAV_LABEL as BUGS_LABEL  # noqa: E402
from media_manglers_workbench.bug_reports import PAGE_NAME as BUGS_PAGE  # noqa: E402
from media_manglers_workbench.metadata import WORKFLOWS  # noqa: E402
from media_manglers_workbench.resources import DependencyStatus, RuntimeResources  # noqa: E402
from media_manglers_workbench.runner import FakeRunner  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]

# Navigation rail, top to bottom: (page, button label).
# Design wave D1 (237), approved 2026-10-23: the rail in four groups (governance/UI_RULES.md
# section 9), Settings and Help at the bottom. Every button keeps its text and accessible name.
EXPECTED_NAV = [
    # Make
    ("Home", "Home"),
    (BUGS_PAGE, BUGS_LABEL),
    # 150 Phase 3, approved 2026-10-08: its rail text is "AI Editor" (approved 2026-10-10).
    ("AI Video Editor", "AI Editor"),
    ("New Review", "New"),
    # Library. Wave 6 (220), approved 2026-10-19: the raw bin library and the Review Media Inbox (152).
    ("Raw Bin", "Raw bin"),
    ("Review Media Inbox", "Inbox"),
    # Results
    ("Evidence", "Evidence"),
    ("Session Review", "Session"),
    ("Prompt Drafts", "Drafts"),
    ("History", "History"),
    # Running
    ("Queue / Progress", "Progress"),
    ("Settings", "Settings"),
    ("Help", "Help"),
]

# The rail's group labels, top to bottom (237).
EXPECTED_NAV_GROUPS = ["MAKE", "LIBRARY", "RESULTS", "RUNNING"]

# Every workflow the backend runs, by number and name.
EXPECTED_WORKFLOWS = [
    ("1", "Full Review"),
    ("2", "Transcript Only"),
    ("3", "AI / Ticket Evidence"),
    ("4", "Archive Catalog"),
    ("5", "Review Media Inbox"),
]

# Home: the Find my bug reports card on top, then these cards under "Other tasks".
# 150 Phase 3, approved 2026-10-08: the AI Video Editor card is appended.
# Wave 6 (220), approved 2026-10-19: the Review Media Inbox card is back (152) and the raw bin
# library card sits beside the AI Video Editor's.
EXPECTED_HOME_WORKFLOW_CARDS = ["1", "2", "4", "5", "video-editor", "raw-bin"]

# New: the workflows offered in "What do you want to do?".
EXPECTED_NEW_WORKFLOWS = ["1", "2", "3", "4"]

# Settings tabs, left to right.
EXPECTED_SETTINGS_TABS = [
    "General / Startup",
    "Profiles",
    "Dependencies",
    "Video player",
    "Build information",
    "Advanced / Diagnostics",
    # 150 Phase 3: the AI Video Editor's own settings, added at the end.
    "AI Video Editor",
]

# Deficiencies tracked for correction, never expected behaviour. Key -> issue.
KNOWN_GAPS = {
    "Review Media Inbox is not offered on New": "issue 152",
    "AI / Ticket Evidence has no Home card (it is offered on New)": "issue 152",
}


def _resources() -> RuntimeResources:
    return RuntimeResources(
        app_root=REPO_ROOT,
        script_path=REPO_ROOT / "Video Mangler.ps1",
        backend_source_root=REPO_ROOT / "src",
        icon_path=REPO_ROOT / "assets" / "Video Mangler.ico",
        powershell_exe="powershell",
        python_exe="py",
        ffmpeg_exe="ffmpeg",
        ffprobe_exe="ffprobe",
        packaged=False,
        dependencies=[DependencyStatus("test backend", "ready")],
    )


class ProductInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        settings_path = self.root / "settings.json"
        settings_path.write_text(
            json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
                "log_folder": str(self.root / "logs"),
                "temp_folder": str(self.root / "temp"),
                "output_folder": str(self.root / "out"),
            }}),
            encoding="utf-8",
        )
        self.window = WorkbenchWindow(
            settings_path=settings_path,
            profiles_dir=self.root / "profiles",
            runner_factory=FakeRunner,
            resources=_resources(),
        )
        self.window.resize(1400, 900)
        self.window.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.window._closing_after_smoke = True
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def _click(self, button: QPushButton) -> None:
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.app.processEvents()

    # Expected product behaviour -------------------------------------------------------------

    def test_navigation_offers_every_page_in_order(self) -> None:
        window = self.window
        visible = [
            (page, button.text().strip())
            for page, button in window.nav_buttons.items()
            if button.isVisible()
        ]
        visible.sort(key=lambda item: window.nav_buttons[item[0]].mapTo(window, window.nav_buttons[item[0]].rect().topLeft()).y())
        self.assertEqual([(page, label) for page, label in visible], EXPECTED_NAV)

    def test_the_rail_groups_its_pages_under_small_labels(self) -> None:
        window = self.window
        labels = sorted(window.nav_group_labels.values(), key=lambda label: label.mapTo(window, label.rect().topLeft()).y())
        self.assertEqual([label.text() for label in labels], EXPECTED_NAV_GROUPS)
        for label in labels:
            self.assertTrue(label.isVisible())
        # Each label sits above its first page and below the last page of the group before.
        y = {page: window.nav_buttons[page].mapTo(window, window.nav_buttons[page].rect().topLeft()).y()
             for page, _label in EXPECTED_NAV}
        first = {"MAKE": "Home", "LIBRARY": "Raw Bin", "RESULTS": "Evidence", "RUNNING": "Queue / Progress"}
        for label in labels:
            self.assertLess(label.mapTo(window, label.rect().topLeft()).y(), y[first[label.text()]])
        for page, _label in EXPECTED_NAV:
            self.assertEqual(window.nav_buttons[page].accessibleName(), page)

    def test_every_navigation_button_opens_its_page(self) -> None:
        window = self.window
        for page, _label in EXPECTED_NAV:
            with self.subTest(page=page):
                self._click(window.nav_buttons[page])
                self.assertIs(window.page_stack.currentWidget(), window.pages[page])

    def test_home_offers_find_my_bug_reports_and_the_other_tasks(self) -> None:
        window = self.window
        self._click(window.nav_buttons["Home"])
        self.assertTrue(window.home_bug_reports_button.isVisible())
        visible_cards = [number for number, card in window.home_workflow_cards.items() if card.isVisible()]
        self.assertEqual(visible_cards, EXPECTED_HOME_WORKFLOW_CARDS)
        for number in visible_cards:
            with self.subTest(card=number):
                starts = [b for b in window.home_workflow_cards[number].findChildren(QPushButton) if b.text() == "Start"]
                self.assertEqual(len(starts), 1, "every Home card keeps its Start button")
        self._click(window.home_bug_reports_button)
        self.assertIs(window.page_stack.currentWidget(), window.pages[BUGS_PAGE])

    def test_new_offers_the_existing_workflows(self) -> None:
        selector = self.window.workflow_selector
        offered = [str(selector.itemData(i)) for i in range(selector.count())]
        self.assertEqual(offered, EXPECTED_NEW_WORKFLOWS)

    def test_settings_tabs_are_all_there_in_order(self) -> None:
        tabs = self.window.settings_tabs
        self.assertEqual([tabs.tabText(i) for i in range(tabs.count())], EXPECTED_SETTINGS_TABS)

    def test_every_workflow_still_exists(self) -> None:
        self.assertEqual([(w.number, w.title) for w in WORKFLOWS], EXPECTED_WORKFLOWS)

    def test_every_navigation_button_fits_the_smallest_window(self) -> None:
        # 220: two buttons more on the rail; every one must still be on screen at the minimum size.
        window = self.window
        window.resize(window.minimumSize())
        self.app.processEvents()
        for page, _label in EXPECTED_NAV:
            with self.subTest(page=page):
                button = window.nav_buttons[page]
                bottom = button.mapTo(window, button.rect().bottomLeft()).y()
                self.assertLessEqual(bottom, window.height(), f"{page} is cut off at the smallest window")

    # Known gaps: recorded, not endorsed ------------------------------------------------------

    def _gap_still_present(self, gap: str, present: bool) -> None:
        self.assertTrue(
            present,
            f"Known gap fixed: '{gap}' ({KNOWN_GAPS[gap]}). Move it out of KNOWN_GAPS and into the "
            "expected lists in this pull request.",
        )

    def test_known_gaps_are_still_tracked(self) -> None:
        window = self.window
        self._click(window.nav_buttons["Home"])
        selector = window.workflow_selector
        self._gap_still_present("Review Media Inbox is not offered on New",
                                "5" not in [str(selector.itemData(i)) for i in range(selector.count())])
        self._gap_still_present("AI / Ticket Evidence has no Home card (it is offered on New)",
                                not window.home_workflow_cards["3"].isVisible())


if __name__ == "__main__":
    unittest.main()
