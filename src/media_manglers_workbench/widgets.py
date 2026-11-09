"""Workbench controls that prevent accidental mouse-wheel value changes."""

from __future__ import annotations

from PySide6.QtCore import QPointF
from PySide6.QtGui import QFocusEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QSpinBox,
    QWidget,
)


def _scroll_area_for(widget: QWidget) -> QAbstractScrollArea | None:
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QAbstractScrollArea):
            return parent
        parent = parent.parentWidget()
    return None


def _forward_wheel(widget: QWidget, event: QWheelEvent) -> bool:
    scroll_area = _scroll_area_for(widget)
    if scroll_area is None:
        event.ignore()
        return False
    viewport = scroll_area.viewport()
    local_point = widget.mapTo(viewport, event.position().toPoint())
    forwarded = QWheelEvent(
        QPointF(local_point),
        event.globalPosition(),
        event.pixelDelta(),
        event.angleDelta(),
        event.buttons(),
        event.modifiers(),
        event.phase(),
        event.inverted(),
        event.source(),
    )
    QApplication.sendEvent(viewport, forwarded)
    event.accept()
    return True


class _WheelSafeMixin:
    _wheel_armed: bool

    def _init_wheel_safety(self) -> None:
        self._wheel_armed = False

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._wheel_armed = True
        super().mousePressEvent(event)  # type: ignore[misc]

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        self._wheel_armed = False
        super().focusOutEvent(event)  # type: ignore[misc]

    def _wheel_is_deliberate(self) -> bool:
        return self.hasFocus() and self._wheel_armed  # type: ignore[attr-defined]


class WheelSafeComboBox(_WheelSafeMixin, QComboBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_wheel_safety()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if self.view().isVisible() or self._wheel_is_deliberate():
            super().wheelEvent(event)
            return
        _forward_wheel(self, event)


class WheelSafeSpinBox(_WheelSafeMixin, QSpinBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_wheel_safety()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if self._wheel_is_deliberate():
            super().wheelEvent(event)
            return
        _forward_wheel(self, event)


class WheelSafeDoubleSpinBox(_WheelSafeMixin, QDoubleSpinBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_wheel_safety()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if self._wheel_is_deliberate():
            super().wheelEvent(event)
            return
        _forward_wheel(self, event)
