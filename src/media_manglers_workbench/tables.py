"""Shared table set-up so every Workbench table behaves like a spreadsheet.

Every column can be dragged wider or narrower, the last column fills the
spare width, and a column can start wide enough for the longest text it
will ever show (for example a status column that later says
"Transcribed, screenshots next"), so nothing is clipped before the
operator touches it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QHeaderView, QTableWidget

from . import theme

# Extra room for cell padding, the sort indicator and a little breathing space.
COLUMN_PADDING = 28
MIN_COLUMN_WIDTH = 48


def make_columns_resizable(
    table: QTableWidget,
    *,
    widths: Mapping[int, int] | None = None,
    fit_texts: Mapping[int, Iterable[str]] | None = None,
    stretch_last: bool = True,
    stretch: int | None = None,
) -> None:
    """Let the operator resize every column of ``table``.

    Call after the header labels are set. ``widths`` gives a starting width
    per column; ``fit_texts`` lists every value a column can show, and the
    column starts wide enough for the longest one. The header label always
    fits. ``stretch`` names a column that takes the spare width instead of the last one.
    """

    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setStretchLastSection(stretch_last)
    header.setMinimumSectionSize(MIN_COLUMN_WIDTH)
    # 237 (UI_RULES.md section 8): headers start where their column's words start.
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    widths = dict(widths or {})
    fit_texts = {column: [str(text) for text in texts] for column, texts in (fit_texts or {}).items()}

    def fit(_unused: int = 0) -> None:
        _fit_columns(table, widths, fit_texts)
        if stretch is not None:
            fill_column(table, stretch)

    if stretch is not None:
        # This column takes the width the others leave, and every column can still be dragged (112).
        header.setStretchLastSection(False)
        table._mm_fill = _FillColumn(table, stretch)

    # 237: measured in the theme's own font, and again whenever the text size changes.
    table._mm_fit_columns = fit
    theme.keep_scaled(table, "_mm_fit_columns", 0)


class _FillColumn(QObject):
    """Keeps one column as wide as the table's spare width whenever the table is resized."""

    def __init__(self, table: QTableWidget, column: int) -> None:
        super().__init__(table)
        self.table, self.column = table, column
        table.viewport().installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Resize:
            fill_column(self.table, self.column)
        return False


def fill_column(table: QTableWidget, column: int) -> None:
    """Give ``column`` the width the other columns leave (never below its own minimum)."""

    others = sum(table.columnWidth(index) for index in range(table.columnCount()) if index != column)
    table.setColumnWidth(column, max(MIN_COLUMN_WIDTH * 3, table.viewport().width() - others))


def grow_to_contents(table: QTableWidget, columns: Iterable[int], fill: int | None = None) -> None:
    """237: widen these columns to what they show now (and their header), never narrower than the
    operator dragged them, then let ``fill`` take what is left."""

    header = table.horizontalHeader()
    cells = table.fontMetrics()
    titles = header.fontMetrics()
    for column in columns:
        item = table.horizontalHeaderItem(column)
        needed = titles.horizontalAdvance(item.text() if item is not None else "") + COLUMN_PADDING
        for row in range(table.rowCount()):
            cell = table.item(row, column)
            if cell is not None:
                needed = max(needed, cells.horizontalAdvance(cell.text()) + COLUMN_PADDING)
        if needed > table.columnWidth(column):
            table.setColumnWidth(column, needed)
    if fill is not None:
        fill_column(table, fill)


def _fit_columns(table: QTableWidget, widths: Mapping[int, int], fit_texts: Mapping[int, list[str]]) -> None:
    header = table.horizontalHeader()
    table.ensurePolished()
    header.ensurePolished()
    header_metrics = header.fontMetrics()
    cell_metrics = table.fontMetrics()
    scale = theme.text_scale()
    for column in range(table.columnCount()):
        item = table.horizontalHeaderItem(column)
        label = item.text() if item is not None else ""
        width = header_metrics.horizontalAdvance(label) + COLUMN_PADDING
        if column in widths:
            width = max(width, int(int(widths[column]) * scale))
        texts = fit_texts.get(column, [])
        if texts:
            longest = max(cell_metrics.horizontalAdvance(text) for text in texts)
            width = max(width, longest + COLUMN_PADDING)
        table.setColumnWidth(column, max(width, MIN_COLUMN_WIDTH))
