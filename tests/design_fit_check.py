"""Run by tests/test_design_wave_d1.py in a process of its own: the Workbench at a text size in a
1280x800 window, with the real Windows fonts (the test run's own offscreen Qt draws every letter as a
wide box, so it cannot judge what fits). Prints one JSON report.

Usage: python design_fit_check.py SETTINGS_FOLDER TEXT_SIZE
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_QPA_FONTDIR", str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"))
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton,
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QWidget,
)

APP = QApplication.instance() or QApplication([])

from media_manglers_workbench.app import NAV_GROUPS, PAGE_NAMES, WorkbenchWindow  # noqa: E402
from media_manglers_workbench.resources import DependencyStatus, RuntimeResources  # noqa: E402
from media_manglers_workbench.runner import FakeRunner  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: E402


def _short(widget: QWidget) -> bool:
    """A visible control smaller than it needs to be: its words would be cut off."""

    if isinstance(widget, QLabel):
        if not widget.text():
            return False
        if widget.wordWrap():
            return widget.width() > 0 and widget.height() + 1 < widget.heightForWidth(widget.width())
        return widget.height() + 1 < widget.minimumSizeHint().height()
    if isinstance(widget, QAbstractButton):
        if not widget.text():
            return False
        # The words themselves (and the icon) against the button, not the padded size Qt would like.
        metrics = widget.fontMetrics()
        if not isinstance(widget, QPushButton):
            # A tick box or a choice: its words sit beside the box.
            return widget.height() + 1 < metrics.height()
        icon = widget.iconSize().width() + 4 if not widget.icon().isNull() else 0
        return (widget.height() < metrics.height() + 2
                or widget.width() < metrics.horizontalAdvance(widget.text()) + icon + 4)
    hint = widget.minimumSizeHint()
    return widget.height() + 1 < hint.height() or widget.width() + 1 < hint.width()


def _cut(root: QWidget) -> list[str]:
    found = []
    for widget in root.findChildren(QWidget):
        if isinstance(widget, (QAbstractButton, QLabel, QComboBox, QLineEdit)) and widget.isVisibleTo(root) and _short(widget):
            text = widget.text() if hasattr(widget, "text") else ""
            found.append(f"{type(widget).__name__} {str(text)[:50]!r}")
    return found


def main() -> int:
    folder, size = Path(sys.argv[1]), int(sys.argv[2])
    settings = folder / "settings.json"
    settings.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
        "log_folder": str(folder / "logs"), "temp_folder": str(folder / "temp"), "output_folder": str(folder / "out"),
        "race_video_output_folder": str(folder / "videos"), "text_size_percent": size}}), encoding="utf-8")
    window = WorkbenchWindow(settings_path=settings, profiles_dir=folder / "profiles", runner_factory=FakeRunner,
                             resources=RuntimeResources(
                                 app_root=REPO_ROOT, script_path=REPO_ROOT / "Video Mangler.ps1",
                                 backend_source_root=REPO_ROOT / "src", icon_path=None, powershell_exe="powershell",
                                 python_exe="py", ffmpeg_exe="ffmpeg", ffprobe_exe="ffprobe", packaged=False,
                                 dependencies=[DependencyStatus("test backend", "ready")]))
    window.resize(1280, 800)
    window.show()
    for _ in range(3):
        APP.processEvents()
    report: dict[str, object] = {"size": [window.width(), window.height()], "sideways": [], "cut": [],
                                 "rail_off_screen": [], "rail_scrolls": False, "tabs_off_screen": []}
    rail = window.nav_rail.findChild(QScrollArea, "navGroupsScroll")
    for page in PAGE_NAMES:
        window.navigate(page)
        for _ in range(3):
            APP.processEvents()
        tabs = [window.settings_tabs.widget(i) for i in range(window.settings_tabs.count())] if page == "Settings" else [None]
        for index, _tab in enumerate(tabs):
            if page == "Settings":
                window.settings_tabs.setCurrentIndex(index)
                for _ in range(3):
                    APP.processEvents()
            name = f"{page} / {window.settings_tabs.tabText(index)}" if page == "Settings" else page
            if window.page_stack.scroll_for(window.pages[page]).horizontalScrollBar().isVisible():
                report["sideways"].append(name)
            report["cut"] += [f"{name}: {item}" for item in _cut(window)]
        button = window.nav_buttons[page]
        if button.mapTo(window, button.rect().bottomLeft()).y() > window.height():
            report["rail_off_screen"].append(page)
    report["rail_scrolls"] = rail.verticalScrollBar().isVisible()
    window.navigate("Settings")
    APP.processEvents()
    for button in window.settings_tab_strip.buttons:
        if button.mapTo(window, button.rect().topRight()).x() > window.width():
            report["tabs_off_screen"].append(button.text())
    report["groups"] = [group for group, _pages in NAV_GROUPS]
    print("FIT-REPORT " + json.dumps(report))
    window._closing_after_smoke = True
    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
