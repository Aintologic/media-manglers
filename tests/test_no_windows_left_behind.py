"""224: a test's own windows do not outlive it, so a process running many tests does not get slower with each one
(tests/conftest.py, _no_windows_left_behind). The tests here run in order; each looks at what the one before left."""

from __future__ import annotations

import threading
import unittest

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import delete, isValid

_left: dict[str, QWidget] = {}
_release = threading.Event()


class _Waits(QThread):
    def run(self) -> None:
        _release.wait(30)


class WindowsLeftBehindTests(unittest.TestCase):
    shared: QWidget

    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])
        cls.shared = QWidget()
        cls.shared.show()

    @classmethod
    def tearDownClass(cls) -> None:
        _release.set()
        for thread in cls.shared.findChildren(QThread):
            thread.wait(5000)
        cls.shared.deleteLater()

    def test_1_a_test_leaves_a_window_and_a_child(self) -> None:
        window = QWidget()
        child = QWidget(window)
        window.show()
        window.close()
        _left.update(window=window, child=child)

    def test_2_the_window_and_its_child_are_gone(self) -> None:
        self.assertFalse(isValid(_left["window"]), "the window of the test before was removed")
        self.assertFalse(isValid(_left["child"]))

    def test_3_a_window_made_before_the_test_stays(self) -> None:
        self.assertTrue(isValid(self.shared))
        self.assertTrue(self.shared.isVisible())

    def test_4_a_window_with_a_running_thread_is_left(self) -> None:
        window = QWidget()
        thread = _Waits(window)
        thread.start()
        _left.update(busy=window, thread=thread)

    def test_5_it_stays_while_the_thread_runs_and_goes_after(self) -> None:
        self.assertTrue(isValid(_left["busy"]), "removing it now would end the process")
        self.assertTrue(_left["thread"].isRunning())
        _release.set()
        self.assertTrue(_left["thread"].wait(5000))

    def test_6_the_window_that_waited_is_gone(self) -> None:
        self.assertFalse(isValid(_left["busy"]))

    def test_7_a_thread_qt_already_deleted_does_not_stop_the_clean_up(self) -> None:
        thread = _Waits()
        delete(thread)
        _left.update(deleted_thread=thread, after_deleted_thread=QWidget())

    def test_8_the_window_of_that_test_is_gone(self) -> None:
        self.assertFalse(isValid(_left["after_deleted_thread"]))
