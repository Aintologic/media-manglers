"""Run by tests/test_design_wave_d2.py in a process of its own: the AI Video Editor (236) at a text size in
a 1280x800 window, with the real Windows fonts (the test run's own offscreen Qt draws every letter as a
wide box, so it cannot judge what fits), in every state it has: the start view, a video's first step, the
step after Prepare, a video with versions (its picture with the play choices, and the player on the page),
the panels of its toolbar, and its dialogs.
Prints one JSON report.

Usage: python design_fit_check_d2.py WORK_FOLDER TEXT_SIZE
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_QPA_FONTDIR", str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"))
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])

from media_manglers.core.race_video.project import add_version, create_project  # noqa: E402
from media_manglers.core.race_video.render import RenderOptions, render_version  # noqa: E402
from media_manglers.core.race_video.timeline import SCHEMA  # noqa: E402
from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.resources import DependencyStatus, RuntimeResources  # noqa: E402
from media_manglers_workbench.review_player import ReviewPlayerWindow  # noqa: E402
from media_manglers_workbench.runner import FakeRunner  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: E402
from tests.design_fit_check import _cut  # noqa: E402
from tests.test_review_player import FakeAudioOutput, PlayerFactory  # noqa: E402

FFMPEG, FFPROBE = shutil.which("ffmpeg") or "ffmpeg", shutil.which("ffprobe") or "ffprobe"
LAYOUT = {"width": 960, "height": 180,
          "panels": {"left": [0, 0, 320, 180], "center": [320, 0, 320, 180], "right": [640, 0, 320, 180]}}
BEATS = ("Practice", "Start", "Battle for P5", "Pit stop", "Chase", "Finish")


def settle(ms: int = 200) -> None:
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        APP.processEvents()
        QTest.qWait(20)


def recording(path: Path, seconds: int) -> Path:
    subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=960x180:r=30:d={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=300:sample_rate=48000:duration={seconds}",
                    "-f", "lavfi", "-i", f"anoisesrc=color=pink:amplitude=0.05:sample_rate=48000:duration={seconds}",
                    "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


def clipped(root: QWidget) -> list[str]:
    """The shared check, plus words cut at the side: a one-line label narrower than its words."""

    rail = root.findChild(QWidget, "navRail")
    rail_words = {f"QLabel {label.text()[:50]!r}" for label in rail.findChildren(QLabel)} if rail is not None else set()
    found = [item for item in _cut(root) if item not in rail_words]
    for label in root.findChildren(QLabel):
        if (label.isVisibleTo(root) and label.text() and not label.wordWrap() and label.pixmap().isNull()
                and label.width() + 1 < label.minimumSizeHint().width()):
            found.append(f"QLabel sideways {label.text()[:50]!r}")
    return found


def main() -> int:
    work, size = Path(sys.argv[1]), int(sys.argv[2])
    out = work / "out"
    many = create_project(out, recording(work / "race.mkv", 30), "a-race-with-versions")
    scenes = [{"id": f"s{index + 1:02d}", "beat": beat, "reason": "fit", "in": 1.0 + index * 4, "out": 4.0 + index * 4,
               "view": "center"} for index, beat in enumerate(BEATS)]
    for number in range(1, 6):
        add_version(many, {"schema": SCHEMA, "source": str(work / "race.mkv"), "source_layout": LAYOUT,
                           "tracks": {"voice": 0, "game": 1}, "scenes": scenes},
                    story="# Story — A long name for a race at a famous circuit, in the rain\n\n## In short\n\nIt holds.",
                    source_duration=30.0, audio_streams=2, editor_label="claude-opus-5.5")
    (many / "analysis" / "analysis.json").write_text(json.dumps({"settings": {"budget": "standard"}}), encoding="utf-8")
    (many / "versions" / "v005" / "review.md").write_text(
        "# Review\n\n## In short\n\nGood.\n\n## What changed\n\n- Shorter.\n\n## Concerns\n\n- The end.", encoding="utf-8")
    render_version(many, 5, "preview", RenderOptions(ffmpeg=FFMPEG, ffprobe=FFPROBE, masks={}, encoder="x264",
                                                      hwaccel="none"))
    waiting = create_project(out, recording(work / "waiting.mkv", 6), "a-race-waiting-for-its-agent")
    (waiting / "analysis" / "analysis.json").write_text(json.dumps({"settings": {"budget": "light"}}), encoding="utf-8")
    new = recording(work / "a-new-recording-with-a-long-name.mkv", 6)

    settings = work / "settings.json"
    settings.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
        "log_folder": str(work / "logs"), "temp_folder": str(work / "temp"), "output_folder": str(out),
        "text_size_percent": size, "evidence_track_roles": "1=narration,2=game"}}), encoding="utf-8")
    window = WorkbenchWindow(settings_path=settings, profiles_dir=work / "profiles", runner_factory=FakeRunner,
                             resources=RuntimeResources(
                                 app_root=REPO_ROOT, script_path=REPO_ROOT / "Video Mangler.ps1",
                                 backend_source_root=REPO_ROOT / "src", icon_path=None, powershell_exe="powershell",
                                 python_exe=sys.executable, ffmpeg_exe=FFMPEG, ffprobe_exe=FFPROBE, packaged=False,
                                 dependencies=[DependencyStatus("test backend", "ready")]))
    players = PlayerFactory([])
    window.video_opener._player_factory = lambda host, opener: ReviewPlayerWindow(
        host, opener, video_surface_factory=QWidget, player_factory=players, audio_output_factory=FakeAudioOutput)
    window.resize(1280, 800)
    window.show()
    settle(300)
    window.navigate("AI Video Editor")
    page = window.ai_video_editor_page
    scroll = window.page_stack.scroll_for(page)
    report: dict[str, object] = {"size": [window.width(), window.height()], "states": {}}

    def on_picture() -> list[str]:
        """236 fix round: the play choices sit whole on the picture, and every scene shows its whole name."""

        found = []
        if page.stage.currentWidget() is page.poster_page:
            box, overlay = page.poster.picture_rect(), page.poster.overlay.geometry()
            if not box.contains(overlay):
                found.append(f"the play choices {overlay.getRect()} are not on the picture {box.getRect()}")
            for button in (page.play_button, page.play_preview_button, page.poster_render_button):
                if button.isVisibleTo(page.poster) and not page.poster.overlay.rect().contains(button.geometry()):
                    found.append(f"{button.text()!r} is cut off on the picture")
        for block in page.scene_strip.blocks:
            if block.isVisibleTo(page) and block.width() < block.sizeHint().width():
                found.append(f"the scene {block.block['name']!r} is cut off")
        return found

    def look(name: str, dialog: QWidget | None = None) -> None:
        settle(250)
        entry = {"sideways": scroll.horizontalScrollBar().isVisible(), "cut": clipped(window) + on_picture()}
        if dialog is not None:
            entry["dialog_cut"] = clipped(dialog)
        report["states"][name] = entry

    page.show_start()
    look("start")
    page.set_recording(new)
    deadline = time.monotonic() + 60
    while page.probing and time.monotonic() < deadline:
        settle(50)
    look("first step")
    page.open_video(str(waiting))
    look("waiting for the agent")
    page.open_video(str(many))
    look("poster")
    page.play_choice("main")
    look("playing")
    page.scene_strip.blocks[3].click()
    page.scene_strip.blocks[3].pen.click()
    look("scene note")
    for key, panel in page.tool_panels.items():
        page.open_tool(key)
        look(f"panel {key}", panel)
        panel.hide()
    renders = many / "versions" / "v005" / "renders"
    (renders / "final.mp4").write_bytes((renders / "preview.mp4").read_bytes())
    page.refresh()
    page.show_start()
    page.open_video(str(many))
    look("poster with a final")
    page.show_steps(open_form=True)
    look("tracks over the player")
    page.back_to_player()
    for name, opened, dialog in (("see the prompt first", lambda: page.see_prompt("claude"), page.prompt_dialog),
                                 ("the editor's own review", lambda: page.show_reader("review"), page.review_reader),
                                 ("this version's files", page.show_files, page.files_dialog),
                                 ("approve and export", page.start_export, page.export_dialog)):
        opened()
        look(name, dialog)
        if dialog is page.export_dialog:
            dialog.reject()
        else:
            dialog.hide()
    print("FIT-REPORT " + json.dumps(report))
    window._closing_after_smoke = True
    QTimer.singleShot(0, window.close)
    settle(100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
