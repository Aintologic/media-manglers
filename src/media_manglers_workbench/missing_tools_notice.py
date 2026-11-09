"""The start-up notice for a missing required tool (188).

A bar across the top of the page area, never a dialog: it names each missing tool in plain words with
a Download button for its official page, and offers Open Settings > Dependencies and Not now. It is
decided once per launch, by the first readiness check that finishes, and never blocks anything;
Start stays blocked by the readiness rules as before.
"""

from __future__ import annotations

from typing import Callable, Iterable

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from .resources import DependencyStatus
from .tool_sources import TOOL_SOURCES


def missing_required_tools(dependencies: Iterable[DependencyStatus]) -> list[DependencyStatus]:
    """Required tools the check could not use, in the order the check lists them."""

    return [
        item
        for item in dependencies
        if item.required and not item.ready and item.key in TOOL_SOURCES
    ]


class MissingToolsNotice(QFrame):
    def __init__(
        self,
        open_page: Callable[[str], None],
        open_settings: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("missingToolsNotice")
        self.setAccessibleName("Missing tools notice")
        self._open_page = open_page
        self._open_settings = open_settings
        self._decided = False
        self.download_buttons: dict[str, QPushButton] = {}
        # One row, floating over the top edge of the page area rather than pushing the pages down:
        # the pages are laid out for the window's height and Home has no room to spare. A message
        # too long for the row is cut, and shown whole on hover.
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        self.message = QLabel()
        self.message.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.message, 1)
        self._downloads = QHBoxLayout()
        layout.addLayout(self._downloads)
        self.settings_button = QPushButton("Open Settings > Dependencies")
        self.settings_button.clicked.connect(self._settings_clicked)
        self.not_now_button = QPushButton("Not now")
        self.not_now_button.clicked.connect(self.hide)
        layout.addWidget(self.settings_button)
        layout.addWidget(self.not_now_button)
        self.hide()
        if parent is not None:
            parent.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._place()
        return False

    def _place(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(0, 0, parent.width(), self.sizeHint().height())
            self.raise_()

    def showEvent(self, event) -> None:  # noqa: N802
        self._place()
        super().showEvent(event)

    def show_once(self, dependencies: Iterable[DependencyStatus]) -> None:
        missing = missing_required_tools(dependencies)
        if self._decided:
            # Later checks never bring it back. One that finds everything takes it away, and one
            # that finds fewer tools missing updates what it names.
            if not missing:
                self.hide()
            elif not self.isHidden():
                self._fill(missing)
            return
        self._decided = True
        if not missing:
            return
        self._fill(missing)
        self.show()

    def _fill(self, missing: list[DependencyStatus]) -> None:
        for button in self.download_buttons.values():
            self._downloads.removeWidget(button)
            button.deleteLater()
        self.download_buttons.clear()
        names = [item.name for item in missing]
        listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        self.message.setText(
            f"Missing: {listed}. Reviews cannot start until "
            f"{'it is' if len(names) == 1 else 'they are'} installed; everything else still works."
        )
        self.message.setToolTip(self.message.text())
        for item in missing:
            button = QPushButton(f"Download {item.name}")
            button.setAccessibleName(f"Download {item.name}")
            button.setToolTip(f"Open the official {item.name} page in your browser")
            button.clicked.connect(lambda checked=False, key=item.key: self._open_page(key))
            self._downloads.addWidget(button)
            self.download_buttons[item.key] = button

    def _settings_clicked(self) -> None:
        self.hide()
        self._open_settings()
