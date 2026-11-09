"""Mouse input for GUI tests, sent the way the operator's mouse sends it.

A test that emits ``view.doubleClicked`` by hand proves only what the slot does
once Qt has decided a double-click happened. It passes for a view whose
double-click was never connected to anything, for a row the mouse could not
reach, and for a view hidden behind another page. That is how double-click to
play went missing from half the lists that show a recording while every test
stayed green (125).

``double_click_row`` sends the events to the WINDOW, the way the operating
system does: Qt itself decides that the second press is a double-click and
finds the widget under the pointer. ``double_click_row_with_a_gap`` sends the
four events a widget receives one at a time and runs something between the two
clicks, for lists that are redrawn while the operator is looking at them (a
real double-click leaves the event loop running for 100-300 ms between them).
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QModelIndex, QPoint, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QComboBox,
    QMenu,
    QScrollArea,
    QStackedWidget,
    QTabWidget,
    QWidget,
)


def bring_to_front(widget: QWidget) -> None:
    """Put ``widget``'s page, tab and stack page in front, as the operator would.

    Only what holds the widget is changed; nothing is clicked.
    """

    child: QWidget = widget
    holder = widget.parentWidget()
    while holder is not None:
        if isinstance(holder, QStackedWidget):
            tabs = holder.parentWidget()
            if isinstance(tabs, QTabWidget) and tabs.indexOf(child) >= 0:
                tabs.setCurrentWidget(child)
            else:
                holder.setCurrentWidget(child)
        child = holder
        holder = holder.parentWidget()
    QApplication.processEvents()


def row_point(view: QAbstractItemView, index: QModelIndex) -> QPoint:
    """Where the mouse lands on ``index``, in the view's viewport.

    The row is scrolled into sight, inside the view and inside any scroll area
    that holds the view. Only the part of the row that is on screen is aimed
    at: a long list row is wider than the list, and its centre can lie on the
    widget next to it. Fails if the pointer would land on anything but this
    view, so a row that is hidden or covered cannot pass.
    """

    holder = view.parentWidget()
    while holder is not None:
        if isinstance(holder, QScrollArea):
            holder.ensureWidgetVisible(view, 0, 0)
        holder = holder.parentWidget()
    view.scrollTo(index)
    QApplication.processEvents()
    viewport = view.viewport()
    row = view.visualRect(index).intersected(viewport.rect())
    holder = view.parentWidget()
    while holder is not None:
        if isinstance(holder, QScrollArea) and holder.widget() is not None:
            # The row itself in sight, not only the list's top edge: on a long page the top of the
            # list can show while the row is still below the fold, under whatever comes next.
            centre = viewport.mapTo(holder.widget(), row.center())
            holder.ensureVisible(centre.x(), centre.y(), 0, row.height())
        holder = holder.parentWidget()
    QApplication.processEvents()
    point = row.center()
    if view.indexAt(point) != index:
        raise AssertionError(f"row {index.row()} is not under the point aimed at; the mouse would hit another row")
    top = view.window()
    landing = top.childAt(viewport.mapTo(top, point))
    if landing is not viewport and not viewport.isAncestorOf(landing):
        raise AssertionError(f"the mouse would land on {landing!r}, not on this view: it is hidden or covered")
    return point


def double_click_row(view: QAbstractItemView, index: QModelIndex) -> None:
    """Double-click ``index`` with the left button, through the window."""

    point = row_point(view, index)
    top = view.window()
    handle = top.windowHandle()
    if handle is None:
        raise AssertionError("the window is not shown, so nothing can be clicked in it")
    QTest.mouseDClick(
        handle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, view.viewport().mapTo(top, point)
    )
    QApplication.processEvents()


def right_click_row(view: QAbstractItemView, index: QModelIndex) -> None:
    """Right-click ``index``: the context-menu event a mouse gives the view."""

    point = row_point(view, index)
    viewport = view.viewport()
    QApplication.sendEvent(
        viewport, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, viewport.mapToGlobal(point))
    )
    QApplication.processEvents()


def widget_point(widget: QWidget) -> QPoint:
    """Where the mouse lands on ``widget``: the middle of the part of it on screen, scrolled into sight in
    any scroll area that holds it. Fails if the pointer would land on anything else, so a hidden or
    covered widget cannot pass."""

    holder = widget.parentWidget()
    while holder is not None:
        if isinstance(holder, QScrollArea):
            holder.ensureWidgetVisible(widget, 0, 0)
        holder = holder.parentWidget()
    QApplication.processEvents()
    if not widget.isVisible():
        raise AssertionError(f"{widget!r} is not shown, so the mouse cannot reach it")
    # A widget wider than its scroll area is only partly on screen; aim at the part that is.
    on_screen = widget.visibleRegion().boundingRect()
    if on_screen.isEmpty():
        raise AssertionError(f"no part of {widget!r} is on screen")
    point = on_screen.center()
    top = widget.window()
    landing = top.childAt(widget.mapTo(top, point))
    if landing is not widget and not widget.isAncestorOf(landing):
        raise AssertionError(f"the mouse would land on {landing!r}, not on {widget!r}: it is hidden or covered")
    return point


def click(widget: QWidget) -> None:
    """Click ``widget``'s centre with the left button, once the mouse can reach it (226)."""

    bring_to_front(widget)
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, widget_point(widget))
    QApplication.processEvents()


def choose_in_combo(combo: QComboBox, text: str) -> None:
    """Open ``combo``'s list with a click and click the item ``text`` in it, as the operator does (226).

    Setting the current index in code would pass for a box the mouse cannot reach or whose list never
    opens; this fails for both, and for an item that is not offered.
    """

    click(combo)
    view = combo.view()
    if not view.isVisible():
        raise AssertionError(f"the list of {combo!r} did not open")
    row = combo.findText(text)
    if row < 0:
        raise AssertionError(f"{text!r} is not offered: {[combo.itemText(i) for i in range(combo.count())]}")
    # A real second click comes a moment later; the list ignores a release that comes too soon.
    QTest.qWait(QApplication.doubleClickInterval() + 50)
    index = view.model().index(row, combo.modelColumn())
    point = row_point(view, index)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QApplication.processEvents()
    if combo.currentText() != text:
        raise AssertionError(f"clicking {text!r} left {combo.currentText()!r} chosen")


def choose_in_panel(button: QWidget, panel: QWidget, text: str) -> None:
    """Open ``panel`` with a click on its toolbar ``button`` and click its choice ``text``, as the operator
    does (236 fix round: the AI Video Editor's toolbar, "Video settings", "Prompt", "Story & review" and
    "Files"). A choice matches by its words or the start of them. Fails for a panel that does not open, a
    choice that is not offered or not shown, and one that is greyed out."""

    if not panel.isVisible():
        click(button)
        QTest.qWait(50)
    if not panel.isVisible():
        raise AssertionError(f"{panel.accessibleName()!r} did not open")
    offered = [choice for choice in panel.findChildren(QAbstractButton) if choice.isVisibleTo(panel)]
    choice = next((item for item in offered if item.text() == text), None) or next(
        (item for item in offered if item.text().startswith(text)), None)
    if choice is None:
        raise AssertionError(f"{text!r} is not offered: {[item.text() for item in offered]}")
    if not choice.isEnabled():
        raise AssertionError(f"{text!r} is greyed out: {choice.toolTip()}")
    click(choice)
    QApplication.processEvents()


def choose_in_menu(button: QWidget, menu: QMenu, *path: str) -> None:
    """Open ``menu`` with a click on ``button`` and click its item ``path[-1]``, opening each submenu named
    before it, as the operator does. An item matches by its words or the start of them (a submenu's title
    can carry its current choice). Fails for a menu that does not open, an item that is not offered, and
    one that is greyed out."""

    click(button)
    QTest.qWait(50)
    current = menu
    for text in path:
        if not current.isVisible():
            raise AssertionError(f"the menu holding {text!r} did not open")
        offered = [action for action in current.actions() if action.text()]
        action = next((item for item in offered if item.text() == text), None) or next(
            (item for item in offered if item.text().startswith(text)), None)
        if action is None:
            raise AssertionError(f"{text!r} is not offered: {[item.text() for item in offered]}")
        if not action.isEnabled():
            raise AssertionError(f"{text!r} is greyed out")
        point = current.actionGeometry(action).center()
        QTest.mouseMove(current, point)
        QTest.mouseClick(current, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        QApplication.processEvents()
        if action.menu() is not None:
            current = action.menu()
            QTest.qWait(50)
    QApplication.processEvents()


def double_click_row_with_a_gap(view: QAbstractItemView, index: QModelIndex, between: Callable[[], object]) -> None:
    """Double-click ``index`` and run ``between`` after the first click.

    What Qt delivers to a widget for a double-click is press, release,
    double-click, release. ``QTest.mouseDClick`` on a widget sends only the
    third of those, so the others are sent around it.
    """

    point = row_point(view, index)
    viewport = view.viewport()
    button = Qt.MouseButton.LeftButton
    none = Qt.KeyboardModifier.NoModifier
    QTest.mousePress(viewport, button, none, point)
    QTest.mouseRelease(viewport, button, none, point)
    between()
    QApplication.processEvents()
    QTest.mouseDClick(viewport, button, none, point)
    QTest.mouseRelease(viewport, button, none, point)
    QApplication.processEvents()
