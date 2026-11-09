"""The words-to-spell-right list on Settings > General (201). See `spelling_words`."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from .metadata import METADATA_BY_KEY
from .spelling_words import SETTING_KEY, join_words, split_words


class SpellingWordsPanel(QWidget):
    """One entry per line. Owns no settings itself."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("spellingWordsEditor")
        self.editor.setTabChangesFocus(True)
        self.editor.setFixedHeight(110)
        self.editor.setToolTip(METADATA_BY_KEY[SETTING_KEY].tooltip)
        layout.addWidget(self.editor)
        note = QLabel(
            "One word or name per line, spelled the way you want it in transcripts. If Whisper keeps "
            "writing it wrong, add what it writes after an equals sign, for example: Brooklands=brook lands"
        )
        note.setWordWrap(True)
        layout.addWidget(note)

    def load(self, settings: dict[str, Any]) -> None:
        self.editor.setPlainText(join_words(split_words(settings.get(SETTING_KEY))))

    def values(self) -> dict[str, Any]:
        return {SETTING_KEY: join_words(split_words(self.editor.toPlainText()))}
