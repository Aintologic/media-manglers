from __future__ import annotations

import ast
import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QHeaderView, QTableWidget  # noqa: E402

from media_manglers_workbench.tables import COLUMN_PADDING, make_columns_resizable  # noqa: E402

WORKBENCH = Path(__file__).resolve().parents[1] / "src" / "media_manglers_workbench"


class MakeColumnsResizableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _table(self) -> QTableWidget:
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["Recording", "Voice track", "Status"])
        return table

    def test_every_column_is_interactive_and_last_stretches(self) -> None:
        table = self._table()
        make_columns_resizable(table)
        header = table.horizontalHeader()
        for column in range(table.columnCount()):
            self.assertEqual(header.sectionResizeMode(column), QHeaderView.ResizeMode.Interactive)
        self.assertTrue(header.stretchLastSection())

    def test_fit_texts_makes_room_for_the_longest_label(self) -> None:
        table = self._table()
        long_label = "Transcribed, screenshots next"
        make_columns_resizable(table, fit_texts={1: ["Pending", long_label]})
        needed = table.fontMetrics().horizontalAdvance(long_label) + COLUMN_PADDING
        self.assertGreaterEqual(table.columnWidth(1), needed)

    def test_explicit_width_and_header_label_are_respected(self) -> None:
        table = self._table()
        make_columns_resizable(table, widths={0: 400})
        self.assertGreaterEqual(table.columnWidth(0), 400)
        label_width = table.horizontalHeader().fontMetrics().horizontalAdvance("Voice track")
        self.assertGreaterEqual(table.columnWidth(1), label_width)


class NoLockedColumnsGuardTests(unittest.TestCase):
    """Columns locked with Stretch/ResizeToContents cannot be dragged (112)."""

    def test_workbench_sources_do_not_lock_column_widths(self) -> None:
        offenders = []
        for path in sorted(WORKBENCH.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == "setSectionResizeMode":
                    offenders.append(f"{path.name}:{node.lineno}")
        allowed = {"tables.py"}
        offenders = [item for item in offenders if item.split(":")[0] not in allowed]
        self.assertEqual(offenders, [], "use make_columns_resizable() instead")


if __name__ == "__main__":
    unittest.main()
