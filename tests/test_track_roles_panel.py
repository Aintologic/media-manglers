"""196: the per-track narration setting reads one track per row, its label on the left of its
own choice, so a choice cannot be read as belonging to the next track."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from media_manglers_workbench.track_roles import TrackRolesPanel  # noqa: E402


class TrackRolesPanelLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_each_track_has_its_own_row_with_its_label_on_the_left(self) -> None:
        panel = TrackRolesPanel()
        panel.resize(900, 400)
        panel.show()
        self.app.processEvents()
        try:
            labels = {label.text(): label for label in panel.findChildren(QLabel)}
            previous_bottom = -1
            for number, combo in panel.combos.items():
                label = labels.get(f"Track {number}:") or labels.get(f"Track {number}")
                self.assertIsNotNone(label, f"no 'Track {number}:' label: {sorted(labels)}")
                box = combo.geometry()
                text = label.geometry()
                # Its own row, below the one before.
                self.assertGreaterEqual(box.top(), previous_bottom, f"Track {number} shares a row")
                previous_bottom = box.bottom()
                # Its label sits on that row, to the left of its own choice.
                self.assertTrue(text.top() <= box.center().y() <= text.bottom() or
                                box.top() <= text.center().y() <= box.bottom(), f"Track {number} label is off its row")
                self.assertLess(text.right(), box.left())
                # And no other choice is on that row: nothing between a label and the next track.
                for other_number, other in panel.combos.items():
                    if other_number != number:
                        self.assertFalse(other.geometry().intersects(box.adjusted(-2000, 0, 2000, 0)),
                                         f"Track {other_number} is on Track {number}'s row")
            # The label belongs to its choice: Alt+its key and screen readers go to the right one.
            self.assertEqual([labels[f"Track {n}:"].buddy() for n in panel.combos], list(panel.combos.values()))
        finally:
            panel.close()


if __name__ == "__main__":
    unittest.main()
