"""The AI Video Editor page (150 Phase 3), clicked like an operator would.

The runs go through the Workbench's shared runner into the real race-video commands of the Python
core, on small synthetic recordings and real FFmpeg. Only Whisper is left out: it is not in the
test runtime, so the stand-in runner asks the prepare command to skip the transcript. The tests set
Track roles, so Auto knows the voice track without listening (226).
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, Qt  # noqa: E402
from PySide6.QtGui import QImage, QMouseEvent, QPalette  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QMessageBox, QPushButton, QWidget  # noqa: E402

from media_manglers.core.race_video.project import add_version, create_project  # noqa: E402
from media_manglers.core.race_video.render import RenderOptions, render_version  # noqa: E402
from media_manglers.core.race_video.requests import ENGINE_SETTING_KEYS  # noqa: E402
from media_manglers.core.race_video.timeline import SCHEMA  # noqa: E402
from media_manglers_workbench.ai_video_editor import PAGE_NAME, AiVideoEditorPage  # noqa: E402
from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.privacy_mask_editor import PrivacyMaskDialog, drawn_path  # noqa: E402
from media_manglers_workbench.resources import DependencyStatus, RuntimeResources  # noqa: E402
from media_manglers_workbench.review_player import ReviewPlayerWindow  # noqa: E402
from media_manglers_workbench.runner import RunnerResult  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: E402
from media_manglers_workbench.theme import DARK_TOKENS  # noqa: E402
from tests.qt_input import bring_to_front, choose_in_combo, choose_in_panel, click, widget_point  # noqa: E402
from tests.test_review_player import FakeAudioOutput, PlayerFactory  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
# The dark theme's colours (theme.py, the UI rulebook's tokens since 237): the one status rule's green
# for done, the accent teal for running, red for failed, and the link colour for an instruction.
STATUS_GREEN = DARK_TOKENS["done"].lower()
STATUS_RUNNING = DARK_TOKENS["accent"].lower()
STATUS_RED = DARK_TOKENS["failed"].lower()
ACCENT_CYAN = DARK_TOKENS["link"].lower()
LAYOUT = {"width": 960, "height": 180,
          "panels": {"left": [0, 0, 320, 180], "center": [320, 0, 320, 180], "right": [640, 0, 320, 180]}}


def _resources() -> RuntimeResources:
    return RuntimeResources(
        app_root=REPO_ROOT, script_path=REPO_ROOT / "Video Mangler.ps1", backend_source_root=REPO_ROOT / "src",
        icon_path=REPO_ROOT / "assets" / "Video Mangler.ico", powershell_exe="powershell",
        python_exe=sys.executable, ffmpeg_exe=FFMPEG or "ffmpeg", ffprobe_exe=FFPROBE or "ffprobe", packaged=False,
        dependencies=[DependencyStatus("test backend", "ready")],
    )


class CoreRunner:
    """Runs the race-video command the page asked for, as its own process, exactly as the app does.

    It runs the page's own command line in a separate Python, as the Workbench's runner would. Running
    it inside this process instead crashed now and then: Python tidied up memory on the runner's
    thread and touched window objects that belong to the main thread.
    """

    instances: list["CoreRunner"] = []

    def __init__(self) -> None:
        self.argv: list[str] = []
        # What the page asked for, before the changes below.
        self.payload: dict = {}
        CoreRunner.instances.append(self)

    def cancel(self) -> None:
        return None

    def run(self, command, on_log=None, *, cwd=None) -> RunnerResult:
        self.argv = list(command.argv)
        args = self.argv[3:]
        request = Path(args[args.index("--request-file") + 1])
        envelope = json.loads(request.read_text(encoding="utf-8"))
        self.payload = copy.deepcopy(envelope["payload"])
        envelope["payload"]["skip_transcript"] = True          # no Whisper in the test runtime
        envelope["payload"]["encoder"] = "x264"
        envelope["payload"]["hwaccel"] = "none"
        if envelope["payload"].get("source") and "layout" not in envelope["payload"]:
            envelope["payload"]["layout"] = LAYOUT
        # 226: no privacy_masks here. The commands always read the stored masks themselves, and
        # tests/conftest.py points the store at an empty folder of the run's own.
        request.write_text(json.dumps(envelope), encoding="utf-8")
        result = subprocess.run(self.argv, cwd=cwd, capture_output=True, text=True, timeout=600)
        for line in result.stdout.splitlines():
            if on_log:
                on_log("stdout", line)
        code = result.returncode
        return RunnerResult(status="succeeded" if code == 0 else "failed", exit_code=code,
                            stdout_lines=[], error="" if code == 0 else (result.stderr.strip()[-300:] or "the command failed"))


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class AiVideoEditorPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.temp_class = tempfile.TemporaryDirectory()
        root = Path(cls.temp_class.name)
        cls.source = root / "race.mkv"
        subprocess.run([
            FFMPEG, "-hide_banner", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=s=960x180:r=30:d=12",
            "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:duration=12",
            "-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.05:sample_rate=48000:duration=12",
            "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-shortest", str(cls.source),
        ], check=True)
        # 226: OBS names its tracks; these names decide the voice and the game sound without any setting.
        cls.titled = root / "titled.mkv"
        subprocess.run([
            FFMPEG, "-hide_banner", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=s=960x180:r=30:d=6",
            "-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.05:sample_rate=48000:duration=6",
            "-f", "lavfi", "-i", "sine=frequency=500:sample_rate=48000:duration=6",
            "-f", "lavfi", "-i", "anoisesrc=color=brown:amplitude=0.1:sample_rate=48000:duration=6",
            "-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:a", "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-metadata:s:a:0", "title=Mic Narration", "-metadata:s:a:1", "title=Music",
            "-metadata:s:a:2", "title=Game", "-shortest", str(cls.titled),
        ], check=True)
        cls.wide = root / "wide.mkv"
        subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=5760x1080:r=5:d=2",
                        "-c:v", "libx264", "-preset", "ultrafast", str(cls.wide)], check=True)
        # Six tracks named as OBS names them, Track1..Track6; Track 3 is silent the whole recording.
        cls.six = root / "six.mkv"
        sounds = [f"sine=frequency={200 + 100 * number}:sample_rate=48000:duration=6" for number in range(6)]
        sounds[2] = "anullsrc=r=48000:cl=mono:d=6"
        command = [FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=960x180:r=30:d=6"]
        for sound in sounds:
            command += ["-f", "lavfi", "-i", sound]
        command += ["-map", "0:v", *[part for number in range(6) for part in ("-map", f"{number + 1}:a")],
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-t", "6"]
        for number in range(6):
            command += [f"-metadata:s:a:{number}", f"title=Track{number + 1}"]
        subprocess.run([*command, str(cls.six)], check=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp_class.cleanup()

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window: WorkbenchWindow | None = None
        CoreRunner.instances = []

    def tearDown(self) -> None:
        if self.window:
            self.window._closing_after_smoke = True
            self.window.close()
            self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def _window(self, **settings) -> WorkbenchWindow:
        path = self.root / "settings.json"
        path.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
            "log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
            "output_folder": str(self.root / "out"), **settings}}), encoding="utf-8")
        self.window = WorkbenchWindow(settings_path=path, profiles_dir=self.root / "profiles",
                                      runner_factory=CoreRunner, resources=_resources())
        self.window.show()
        self.app.processEvents()
        return self.window

    def _click(self, widget) -> None:
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        self.app.processEvents()

    def _open_page(self, window: WorkbenchWindow) -> AiVideoEditorPage:
        self._click(window.nav_buttons[PAGE_NAME])
        self.assertIs(window.page_stack.currentWidget(), window.pages[PAGE_NAME])
        return window.ai_video_editor_page

    def _choose_recording(self, page: AiVideoEditorPage, path: Path) -> None:
        """Choose a recording as the operator does: "Make a video from a recording" on the start view, or
        "Choose a recording…" on a video's first step (236), and wait while its tracks are read (226: on
        a thread of their own). The Raw bin knows no recordings here, so the Windows file picker opens."""

        if page.views.currentWidget() is not page.start_view and not page.choose_button.isVisible():
            click(page.back_button)
        button = page.make_video_button if page.views.currentWidget() is page.start_view else page.choose_button
        with patch("media_manglers_workbench.ai_video_editor.QFileDialog.getOpenFileName",
                   return_value=(str(path), "")):
            click(button)
        self._wait_for_tracks(page)

    @staticmethod
    def _choose(page: AiVideoEditorPage, tool: str, text: str) -> None:
        """A choice of the video's toolbar (236 fix round): its button, then the choice in its panel."""

        choose_in_panel(page.tool_buttons[tool], page.tool_panels[tool], text)

    def _open_video(self, page: AiVideoEditorPage, project: Path) -> None:
        """Click the video's card under "Your videos" (236), from wherever the page is."""

        if page.views.currentWidget() is not page.start_view:
            click(page.back_button)
        click(page._cards[str(project)])
        self.assertIs(page.views.currentWidget(), page.video_view)
        self.assertEqual(page.current_project()["folder"], str(project))

    def _fake_player(self, window: WorkbenchWindow) -> PlayerFactory:
        """The app's one player window, with a stand-in for the media player itself, so nothing really plays."""

        players = PlayerFactory([])
        window.video_opener._player_factory = lambda host, opener: ReviewPlayerWindow(
            host, opener, video_surface_factory=QWidget, player_factory=players, audio_output_factory=FakeAudioOutput)
        return players

    def _wait_for_tracks(self, page: AiVideoEditorPage) -> None:
        deadline = time.monotonic() + 60
        while page.probing and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(20)
        self.assertFalse(page.probing, "the recording's tracks were never read")

    def _wait(self, page: AiVideoEditorPage) -> None:
        deadline = time.monotonic() + 120
        while (page.running or page.host.runner_thread is not None) and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(20)
        self.app.processEvents()
        self.assertFalse(page.running)

    def _assert_status(self, page: AiVideoEditorPage, kind: str, colour: str | None = None) -> None:
        """The status sentence follows the one status rule (213): its statusKind, and the colour it shows."""

        label = page.status_sentence
        self.assertEqual(label.property("statusKind") or "", kind, label.text())
        self.assertEqual(bool(label.property("accent")), kind == "", "only an instruction keeps the cyan accent")
        if colour:
            self.assertEqual(label.palette().color(QPalette.ColorRole.WindowText).name(), colour, label.text())

    def _project_with_a_version(self, window: WorkbenchWindow, editor_label: str = "") -> Path:
        project = create_project(self.root / "out", self.source, "race")
        timeline = {"schema": SCHEMA, "source": str(self.source), "source_layout": LAYOUT, "tracks": {"voice": 0, "game": 1},
                    "scenes": [{"id": "s01", "beat": "start", "reason": "test", "in": 1.0, "out": 5.0, "view": "center",
                                "audio": {"voice": 1.0, "game": 0.5}}]}
        version = add_version(project, timeline, story="# Story\n\nThe driver holds second all race.",
                               source_duration=12.0, audio_streams=2, editor_label=editor_label)
        (project / "versions" / "v001" / "review.md").write_text("# Review\n\nThe ending is weak.", encoding="utf-8")
        (project / "analysis" / "analysis.json").write_text(json.dumps({"settings": {"budget": "light"}}), encoding="utf-8")
        render_version(project, version, "preview", RenderOptions(ffmpeg=FFMPEG, ffprobe=FFPROBE, masks={},
                                                                   encoder="x264", hwaccel="none"))
        window.ai_video_editor_page.refresh()
        return project

    def test_the_page_opens_from_its_button_and_from_its_home_card(self) -> None:
        window = self._window()
        self._click(window.nav_buttons[PAGE_NAME])
        self.assertIs(window.page_stack.currentWidget(), window.pages[PAGE_NAME])
        self._click(window.nav_buttons["Home"])
        self._click(window.home_ai_video_editor_button)
        self.assertIs(window.page_stack.currentWidget(), window.pages[PAGE_NAME])

    def test_preparing_a_recording_runs_like_any_run_and_leaves_evidence_alone(self) -> None:
        # 226: Track 2 is the voice and Track 1 the game sound by the Track roles setting, so both boxes
        # stay on Auto and Prepare decides them without listening.
        window = self._window(last_evidence_package=str(self.root / "earlier-package"),
                              evidence_track_roles="1=game,2=narration")
        page = self._open_page(window)
        self._choose_recording(page, self.source)
        self.assertIn("Check the tracks", page.status_sentence.text())
        self._assert_status(page, "", ACCENT_CYAN)
        self.assertEqual([page.voice_combo.itemText(i) for i in range(page.voice_combo.count())],
                         ["Auto", "Track 1", "Track 2"])
        self.assertTrue(str(page.voice_combo.itemData(1, Qt.ItemDataRole.ToolTipRole)).startswith("Track 1"))
        self.assertIsNone(page.voice_combo.currentData(), "a new recording starts on Auto")
        choose_in_combo(page.budget_combo, "Light")
        click(page.prepare_button)
        self.assertIn("Preparing the recording", page.status_sentence.text())
        self._assert_status(page, "active", STATUS_RUNNING)
        self._wait(page)

        # Wave 5: "Ready for the AI editor" showed cyan; a finished run is green like every feature's.
        self.assertTrue(page.status_sentence.text().startswith("Ready for the AI editor"), page.status_sentence.text())
        self._assert_status(page, "completed", STATUS_GREEN)
        self.assertEqual(window.progress_state_banner.property("operatorState"), "completed")
        argv = CoreRunner.instances[-1].argv
        self.assertIn("race-video-prepare", argv)
        self.assertEqual(argv[0], sys.executable)
        self.assertEqual(window.recent_runs()[0]["workflow_title"], "AI Video Editor: analysis")
        self.assertEqual(window.recent_runs()[0]["status"], "succeeded")
        self.assertEqual(window.app_settings["last_evidence_package"], str(self.root / "earlier-package"),
                         "a video run never becomes the last evidence package")
        # 226: the two remembered track numbers are retired: never written again.
        self.assertNotIn("race_video_voice_track", window.app_settings)
        self.assertNotIn("race_video_game_track", window.app_settings)
        self.assertNotIn("tracks", CoreRunner.instances[-1].payload, "Auto sends no track: the run decides")
        self.assertEqual([p["name"] for p in page.projects], ["race"])
        meta = json.loads((Path(page.projects[0]["folder"]) / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["tracks"], {"voice": 1, "game": 0, "voice_decided_by": "setting", "game_decided_by": "setting"},
                         "the tracks Auto showed are the ones Prepare used")
        # 226 (decision F): no masks are drawn in this run's store, and the page says so, without a pop-up.
        self.assertTrue(page.mask_warning.isVisible())
        self.assertIn("not blurred", page.mask_warning.text())
        self.assertIn("Privacy masks…", page.mask_warning.text())
        self.assertEqual(page.mask_warning.property("statusKind"), "attention")
        self.assertEqual(window.progress_item_states.get("race.mkv"), "completed",
                         "Progress follows the run's own status lines, not just its end")
        self.assertTrue(any(line.startswith("[stdout] MM_PROGRESS_V1 ") and '"Watching the race"' in line
                            for line in window.run_log_lines))
        self.assertTrue(page.projects[0]["analysed"])
        self.assertEqual(page.projects[0]["budget"], "light")
        # 236 fix round: the player's place offers the next step, Copy prompt for Claude Code.
        self.assertTrue(page.empty_copy_button.isEnabled())
        click(page.empty_copy_button)
        self._assert_status(page, "completed", STATUS_GREEN)
        prompt = QApplication.clipboard().text()
        self.assertIn("MODEL: Opus 5.5", prompt)
        self.assertIn(str(Path(page.projects[0]["folder"]) / "analysis" / "digest.md"), prompt)

    def test_auto_shows_the_track_roles_pick_and_a_picked_track_overrides_it(self) -> None:
        # 226 (decision A). The Track roles are the "Narration track" field of Settings > General / Startup,
        # and the page names that field.
        window = self._window(evidence_track_roles="1=game,2=narration")
        page = self._open_page(window)
        self._choose_recording(page, self.source)
        self.assertEqual(page.voice_state.text(),
                         "Auto: Track 2, narration, from your Narration track setting · Using main setting")
        self.assertEqual(page.game_state.text(),
                         "Auto: Track 1, game sound, from your Narration track setting · Using main setting")
        self.assertFalse(page.voice_reset_button.isVisible(), "nothing to reset on Auto")
        self.assertIn("Narration track setting (Settings > General / Startup)", page.voice_combo.toolTip())
        self.assertNotIn("Track roles", page.voice_combo.toolTip() + page.game_combo.toolTip())

        choose_in_combo(page.voice_combo, "Track 1")
        self.assertTrue(page.voice_state.text().startswith("Overridden"), page.voice_state.text())
        self.assertIn("Auto: Track 2, narration, from your Narration track setting", page.voice_state.text())
        self.assertTrue(page.voice_reset_button.isVisible())
        # Track 1 is the game sound by Track roles, so the voice there is the same track twice.
        self.assertIn("same track", page.status_sentence.text())

        click(page.voice_reset_button)
        self.assertEqual(page.voice_combo.currentText(), "Auto")
        self.assertEqual(page.voice_state.text(),
                         "Auto: Track 2, narration, from your Narration track setting · Using main setting")
        self.assertFalse(page.voice_reset_button.isVisible())
        self.assertIn("Check the tracks", page.status_sentence.text())

        # The Track roles are changed on Settings, through its own boxes and its Save button, while the
        # page is hidden: Auto follows them when the page is shown again.
        self._click(window.nav_buttons["Settings"])
        roles = window.settings_track_roles
        bring_to_front(roles)
        choose_in_combo(roles.combos[1], "Narration")
        choose_in_combo(roles.combos[2], "Game audio")
        save = [button for button in window.findChildren(QPushButton) if button.text() == "Save settings"]
        self.assertEqual(len(save), 1)
        with patch.object(QMessageBox, "information"), patch("media_manglers_workbench.app.apply_theme"):
            click(save[0])
        self.assertEqual(window.app_settings["evidence_track_roles"], "1=narration,2=game")
        self.assertFalse(page.isVisible())
        self._open_page(window)
        self.assertEqual(page.voice_state.text(),
                         "Auto: Track 1, narration, from your Narration track setting · Using main setting")
        self.assertEqual(page.game_state.text(),
                         "Auto: Track 2, game sound, from your Narration track setting · Using main setting")

    def test_auto_follows_the_track_names_and_prepare_uses_what_it_showed(self) -> None:
        # 226: names come before the Track roles setting, and a track named Music is never the game sound.
        window = self._window(evidence_track_roles="2=narration,3=game")
        page = self._open_page(window)
        self._choose_recording(page, self.titled)
        self.assertEqual(page.voice_state.text(), "Auto: Track 1, narration, from the track name · Using main setting")
        self.assertEqual(page.game_state.text(), "Auto: Track 3, game sound, from the track name · Using main setting")
        self.assertIn("Track 2  (Music)", str(page.voice_combo.itemData(2, Qt.ItemDataRole.ToolTipRole)))
        click(page.prepare_button)
        self._wait(page)
        self.assertIn("Ready for the AI editor", page.status_sentence.text())
        meta = json.loads((Path(page.projects[0]["folder"]) / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["tracks"], {"voice": 0, "game": 2, "voice_decided_by": "track_name",
                                          "game_decided_by": "track_name"})

    def test_when_only_prepare_can_tell_auto_says_so(self) -> None:
        window = self._window()
        page = self._open_page(window)
        self._choose_recording(page, self.source)
        self.assertEqual(page.voice_state.text(), "Auto: decided during Prepare · Using main setting")
        self.assertEqual(page.game_state.text(), "Auto: decided during Prepare · Using main setting")

    def test_prepare_sends_only_the_overridden_track_and_the_engine_settings_shown(self) -> None:
        # 226: the voice by Track roles (Auto), the game sound picked by hand. The engine settings go
        # with the run as the page has them now, before Settings are saved: the core would otherwise
        # read the saved settings file, which knows none of them.
        window = self._window(evidence_track_roles="2=narration")
        window.app_settings["whisper_device"] = "CPU"
        window.app_settings["race_video_quick_whisper_model"] = "main"
        page = self._open_page(window)
        self._choose_recording(page, self.source)
        self.assertEqual(page.game_state.text(), "Auto: decided during Prepare · Using main setting")
        choose_in_combo(page.game_combo, "Track 1")
        self.assertTrue(page.game_state.text().startswith("Overridden"), page.game_state.text())
        click(page.prepare_button)
        self._wait(page)
        self.assertIn("Ready for the AI editor", page.status_sentence.text())

        payload = CoreRunner.instances[-1].payload
        self.assertEqual(payload["tracks"], {"game": 0}, "only the box with a track picked sends it (0-based)")
        for key, saved in ENGINE_SETTING_KEYS.items():
            with self.subTest(key=key):
                self.assertEqual(payload[key], window.app_settings.get(saved, ""))
        self.assertEqual((payload["track_roles"], payload["whisper_device"], payload["race_video_quick_whisper_model"]),
                         ("2=narration", "CPU", "main"))
        self.assertNotIn("model_name", payload, "the Whisper model goes as whisper_model, with the other settings")
        meta = json.loads((Path(page.projects[0]["folder"]) / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["tracks"], {"voice": 1, "game": 0, "voice_decided_by": "setting", "game_decided_by": "override"})

    def _the_ai_editors_version(self, project: Path, tracks: dict) -> None:
        """A version as the AI editor adds it, on the tracks it was given (the project's own layout)."""

        add_version(project, {"schema": SCHEMA, "source": str(self.source), "tracks": dict(tracks),
                              "scenes": [{"id": "s01", "beat": "start", "reason": "test", "in": 1.0, "out": 5.0,
                                          "view": "center", "audio": {"voice": 1.0, "game": 0.5}}]},
                    story="# Story\n\nA made-up race.", source_duration=12.0, audio_streams=2)

    def test_preparing_a_recording_again_keeps_the_tracks_picked_by_hand(self) -> None:
        # 226 (MJ1): both tracks picked by hand (nothing else says which is which), Prepare, the AI editor
        # makes v001 on them; the recording is chosen again (after drawing masks, say): the boxes show the
        # picks again, Prepare sends them, and v001 still renders.
        window = self._window()
        page = self._open_page(window)
        self._choose_recording(page, self.source)
        choose_in_combo(page.voice_combo, "Track 2")
        choose_in_combo(page.game_combo, "Track 1")
        click(page.prepare_button)
        self._wait(page)
        self.assertIn("Ready for the AI editor", page.status_sentence.text())
        project = Path(page.projects[0]["folder"])
        picked = {"voice": 1, "game": 0, "voice_decided_by": "override", "game_decided_by": "override"}
        self.assertEqual(json.loads((project / "project.json").read_text(encoding="utf-8"))["tracks"], picked)
        self.assertEqual(json.loads((project / "editor-settings.json").read_text(encoding="utf-8")),
                         {"tracks": {"voice": 1, "game": 0}}, "Prepare keeps the picks for the page")
        self._the_ai_editors_version(project, {"voice": 1, "game": 0})

        self._choose_recording(page, self.source)
        self.assertEqual((page.voice_combo.currentText(), page.game_combo.currentText()), ("Track 2", "Track 1"))
        self.assertTrue(page.voice_state.text().startswith("Overridden"), page.voice_state.text())
        self.assertTrue(page.game_state.text().startswith("Overridden"), page.game_state.text())
        self.assertTrue(page.voice_reset_button.isVisible())
        self.assertFalse(page.tracks_warning.isVisible(), "the tracks are the prepared ones")

        # Back on Auto, Prepare would find the voice again by listening: the page says what a change would
        # cost, on the page, without a pop-up; picking Track 2 again clears it.
        with patch.object(QMessageBox, "information") as told, patch.object(QMessageBox, "question") as asked:
            click(page.voice_reset_button)
        told.assert_not_called()
        asked.assert_not_called()
        self.assertTrue(page.tracks_warning.isVisible())
        self.assertIn("Prepare decides your voice again", page.tracks_warning.text())
        self.assertIn("1 version uses Track 2 as your voice and Track 1 as the game sound", page.tracks_warning.text())
        self.assertIn("can no longer be rendered or exported", page.tracks_warning.text())
        self.assertEqual(page.tracks_warning.property("statusKind"), "attention")
        choose_in_combo(page.voice_combo, "Track 2")
        self.assertFalse(page.tracks_warning.isVisible())

        click(page.prepare_button)
        self._wait(page)
        self.assertIn("Ready for the AI editor", page.status_sentence.text())
        self.assertEqual(CoreRunner.instances[-1].payload["tracks"], {"voice": 1, "game": 0}, "the picks are sent again")
        self.assertEqual(json.loads((project / "project.json").read_text(encoding="utf-8"))["tracks"], picked)

        self.assertEqual(page.current_project()["folder"], str(project))
        self.assertEqual([tab.text() for tab in page.version_tabs], ["v001 · newest"])
        # 236: Render a preview is under the video's Files button, and says afterwards what it changed.
        self._choose(page, "files", "Render a preview")
        self._wait(page)
        self.assertIn("Preview ready", page.status_sentence.text())
        self.assertIn("It is the first preview of v001", page.status_sentence.text())
        self.assertTrue((project / "versions" / "v001" / "renders" / "preview.mp4").exists())
        self._choose(page, "files", "Render a preview")
        self._wait(page)
        self.assertIn("It replaced the earlier preview of v001 (0 scenes rendered, 1 reused)", page.status_sentence.text())

    def test_a_prepare_that_would_change_a_videos_tracks_says_so_first(self) -> None:
        # 226 (MJ1): the AI editor adds a version while the page is open; a Prepare with other tracks then
        # first says what it would change, on the page, and runs only when Prepare is pressed again.
        window = self._window()
        page = self._open_page(window)
        self._choose_recording(page, self.source)
        choose_in_combo(page.voice_combo, "Track 1")
        choose_in_combo(page.game_combo, "Track 2")
        click(page.prepare_button)
        self._wait(page)
        self.assertIn("Ready for the AI editor", page.status_sentence.text())
        project = Path(page.projects[0]["folder"])
        self._choose_recording(page, self.source)
        self.assertEqual((page.voice_combo.currentText(), page.game_combo.currentText()), ("Track 1", "Track 2"))
        self.assertFalse(page.tracks_warning.isVisible(), "no version yet: nothing to lose")
        # 236: the page looks for new versions by itself every few seconds, and a version it found shows the
        # warning by itself; this is the version that arrives between two looks.
        page.watch_timer.stop()
        self._the_ai_editors_version(project, {"voice": 0, "game": 1})
        choose_in_combo(page.voice_combo, "Track 2")
        choose_in_combo(page.game_combo, "Track 1")
        with patch.object(QMessageBox, "information") as told, patch.object(QMessageBox, "question") as asked:
            click(page.prepare_button)
        told.assert_not_called()
        asked.assert_not_called()
        self.assertEqual(len(CoreRunner.instances), 1, "the first press only says so")
        self.assertTrue(page.tracks_warning.isVisible())
        self.assertIn("its 1 version uses Track 1 as your voice and Track 2 as the game sound", page.tracks_warning.text())
        self.assertIn("press Prepare again", page.status_sentence.text())

        click(page.prepare_button)
        self._wait(page)
        self.assertEqual(len(CoreRunner.instances), 2)
        self.assertEqual(CoreRunner.instances[-1].payload["tracks"], {"voice": 1, "game": 0})
        self.assertEqual(json.loads((project / "project.json").read_text(encoding="utf-8"))["tracks"]["voice"], 1)
        self.assertFalse(page.tracks_warning.isVisible(), "the boxes are the prepared tracks now")

    def _prepare_card_problems(self, page: AiVideoEditorPage) -> list[str]:
        """Every word cut off and every box squeezed in Prepare's card, as the operator would see them, and
        the page scrolling sideways."""

        window, card = page.window(), page.prepare_card
        problems = []
        for widget in card.findChildren(QWidget):
            if not widget.isVisibleTo(window):
                continue
            if isinstance(widget, QLabel) and widget.text() and widget.wordWrap():
                need = widget.heightForWidth(widget.width())
                if widget.height() < need:
                    problems.append(f"{widget.objectName() or widget.text()[:40]!r} is {widget.height()} px high, needs {need}")
            elif isinstance(widget, (QComboBox, QPushButton)):
                need = widget.minimumSizeHint().height()
                if widget.height() < need:
                    problems.append(f"{widget.objectName() or widget.text()!r} is {widget.height()} px high, needs {need}")
        # Sideways scrolling is checked with the real Windows fonts (tests/design_fit_check_d2.py): this run's
        # offscreen Qt draws every letter as a wide box.
        return problems

    def test_a_silent_track_warning_is_cleared_when_another_recording_is_chosen(self) -> None:
        # 226 review: the warning is about one recording, so it must not stay on screen for the next one.
        window = self._window(evidence_track_roles="2=narration,3=game")
        page = self._open_page(window)
        self._choose_recording(page, self.six)
        click(page.prepare_button)
        self._wait(page)
        self.assertTrue(page.sound_warning.isVisible(), "Track 3 of this recording is silent")
        self._choose_recording(page, self.source)
        self.assertFalse(page.sound_warning.isVisible())
        self.assertEqual(page.sound_warning.text(), "")

    def test_the_prepare_card_never_cuts_its_words_or_squeezes_its_boxes(self) -> None:
        # 226 review: at the smallest window the track states and both warnings were cut off mid-sentence and
        # the track boxes crushed; at the default size too, once both warnings showed. 236: they are in the
        # video's first step now, which Video settings > Your voice opens once the video has a version.
        window = self._window(evidence_track_roles="2=narration,3=game")
        page = self._open_page(window)
        self._choose_recording(page, self.six)
        click(page.prepare_button)
        self._wait(page)
        self.assertIn("Ready for the AI editor", page.status_sentence.text())
        self.assertTrue(page.mask_warning.isVisible(), "no masks are drawn in this run's store")
        self.assertEqual(page.sound_warning.text(), "Track 3, your game sound, is silent for the whole recording; check "
                                                    "your Narration track setting or choose the game track on the page.")
        self.assertEqual(page.sound_warning.property("statusKind"), "attention")
        project = Path(page.projects[0]["folder"])
        add_version(project, {"schema": SCHEMA, "source": str(self.six), "tracks": {"voice": 1, "game": 2},
                              "scenes": [{"id": "s01", "beat": "start", "reason": "test", "in": 1.0, "out": 5.0,
                                          "view": "center", "audio": {"voice": 1.0, "game": 0.5}}]},
                    story="# Story\n\nA made-up race.", source_duration=6.0, audio_streams=6)
        page.refresh()
        self.assertIs(page.stage.currentWidget(), page.poster_page, "the version is shown, ready to play")
        self._choose(page, "settings", "Your voice")
        self.assertIs(page.stage.currentWidget(), page.step_page)
        self.assertTrue(page.back_to_player_button.isVisible())
        choose_in_combo(page.voice_combo, "Track 4")
        self.assertTrue(page.voice_state.text().startswith("Overridden"), page.voice_state.text())
        self.assertTrue(page.tracks_warning.isVisible(), "a Prepare with these tracks would change the video's")
        self.assertTrue(page.mask_warning.isVisible())
        for size in (window.minimumSize(), QSize(1320, 880)):
            with self.subTest(size=(size.width(), size.height())):
                window.resize(size)
                self.app.processEvents()
                QTest.qWait(50)
                self.assertEqual((window.width(), window.height()), (size.width(), size.height()))
                self.assertEqual(self._prepare_card_problems(page), [])
                for widget in (page.voice_combo, page.game_combo, page.budget_combo, page.prepare_button,
                               page.tracks_warning, page.mask_warning):
                    widget_point(widget)
        click(page.back_to_player_button)
        self.assertIs(page.stage.currentWidget(), page.poster_page)

    def test_same_track_twice_is_refused_before_anything_runs(self) -> None:
        for roles, voice, game in (("", "Track 1", "Track 1"),
                                   # The voice picked on the game track Track roles name: Auto's game sound.
                                   ("1=game,2=narration", "Track 1", "Auto")):
            with self.subTest(roles=roles, voice=voice, game=game):
                window = self._window(evidence_track_roles=roles)
                page = self._open_page(window)
                self._choose_recording(page, self.source)
                choose_in_combo(page.voice_combo, voice)
                choose_in_combo(page.game_combo, game)
                with patch.object(QMessageBox, "information") as told:
                    click(page.prepare_button)
                told.assert_called_once()
                self.assertEqual(told.call_args.args[1], "Same track twice")
                self.assertEqual(CoreRunner.instances, [])
                window._closing_after_smoke = True
                window.close()
                self.window = None

    def test_a_game_track_the_setting_sets_as_never_narration_is_refused_before_anything_runs(self) -> None:
        # 226 (decision A): the Narration track setting names Track 3 as the game sound and sets Track 6 as
        # Never narration; Track 6 picked by hand as the game sound is refused on the page, as Prepare would.
        refusal = ("Track 6 is set as Never narration in your Narration track setting (it may be music), and the "
                   "setting names Track 3 as your game sound; choose Track 3, or change the setting.")
        window = self._window(evidence_track_roles="1=full_mix,2=narration,3=game,5=never,6=never")
        page = self._open_page(window)
        self._choose_recording(page, self.six)
        choose_in_combo(page.game_combo, "Track 6")
        self.assertEqual(page.status_sentence.text(), refusal)
        self._assert_status(page, "waiting")   # coloured as the same-track sentence is
        with patch.object(QMessageBox, "information") as told:
            click(page.prepare_button)
        told.assert_called_once()
        self.assertEqual(told.call_args.args[1:], ("Not the game sound", refusal))
        self.assertEqual(CoreRunner.instances, [], "nothing ran")
        choose_in_combo(page.game_combo, "Track 3")
        self.assertIn("Check the tracks", page.status_sentence.text())
        window._closing_after_smoke = True
        window.close()
        self.window = None

        # A setting with no game role (Never narration was the game track before Wave 6) takes the same pick.
        window = self._window(evidence_track_roles="1=full_mix,2=narration,5=never,6=never")
        page = self._open_page(window)
        self._choose_recording(page, self.six)
        choose_in_combo(page.game_combo, "Track 6")
        self.assertIn("Check the tracks", page.status_sentence.text())
        with patch.object(QMessageBox, "information") as told:
            click(page.prepare_button)
        told.assert_not_called()
        self._wait(page)
        self.assertIn("Ready for the AI editor", page.status_sentence.text())
        self.assertEqual(CoreRunner.instances[-1].payload["tracks"], {"game": 5})
        window._closing_after_smoke = True
        window.close()
        self.window = None

        # Back on the setting that names the game track, the same recording comes back with Track 6 as its
        # game sound, as that Prepare picked it; the page refuses it before anything runs.
        window = self._window(evidence_track_roles="1=full_mix,2=narration,3=game,5=never,6=never")
        page = self._open_page(window)
        self._choose_recording(page, self.six)
        self.assertEqual(page.game_combo.currentText(), "Track 6")
        self.assertEqual(page.status_sentence.text(), refusal)
        runs = len(CoreRunner.instances)
        with patch.object(QMessageBox, "information") as told:
            click(page.prepare_button)
        told.assert_called_once()
        self.assertEqual(told.call_args.args[1:], ("Not the game sound", refusal))
        self.assertEqual(len(CoreRunner.instances), runs, "nothing ran")
        self.assertFalse(page.running)

    def test_after_a_prepare_the_video_just_prepared_is_the_one_chosen(self) -> None:
        # 226: "Your videos" kept the video chosen before, so Copy prompt gave that video's prompt.
        window = self._window()
        earlier = self._project_with_a_version(window)
        # The earlier video sorts first (the list is newest first), so the video just prepared is not
        # chosen only because it is the newest.
        meta_path = earlier / "project.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["created"] = "2099-01-01T00:00:00+00:00"
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        page = self._open_page(window)
        self._click(page.refresh_button)
        self._open_video(page, earlier)
        # 236: a new video is made from the start view.
        click(page.back_button)
        self._choose_recording(page, self.titled)
        click(page.prepare_button)
        self._wait(page)
        self.assertIn("Ready for the AI editor", page.status_sentence.text())
        prepared = self.root / "out" / "race-videos" / "titled"
        self.assertEqual([project["folder"] for project in page.projects], [str(earlier), str(prepared)],
                         "the earlier video is first in the list")
        self.assertEqual(page.current_project()["folder"], str(prepared))
        self.assertEqual(page.project_title.text(), "titled")
        self.assertEqual(page.version_tabs, [], "its details are shown, not the other video's")
        # 236 fix round: no version yet, so the player's place says so and offers the one next step.
        self.assertIs(page.stage.currentWidget(), page.empty_page)
        self.assertEqual(page.empty_title.text(), "Your AI agent hasn't made a version yet")
        self.assertFalse(page.empty_prepare_button.isVisible())
        click(page.empty_copy_button)
        self.assertEqual(page.empty_feedback.text(), "Copied. Paste it into Claude Code.")
        prompt = QApplication.clipboard().text()
        self.assertIn(str(prepared / "analysis" / "digest.md"), prompt)
        self.assertNotIn(str(earlier), prompt)

    def test_a_version_shows_its_story_and_review_plays_takes_notes_and_exports(self) -> None:
        window = self._window()
        players = self._fake_player(window)
        project = self._project_with_a_version(window)
        page = self._open_page(window)
        self._open_video(page, project)
        # 236: the story and the editor's own review open from Story & review as a readable page.
        self._choose(page, "story", "The story")
        self.assertTrue(page.story_reader.isVisible())
        self.assertIn("holds second all race", page.story_reader.summary_view.toPlainText())
        self.assertIn("holds second all race", page.story_view.toPlainText())
        page.story_reader.close()
        self._choose(page, "story", "The editor's own review")
        self.assertIn("The ending is weak", page.review_view.toPlainText())
        page.review_reader.close()

        # 236: the play choice on the picture plays it here at once, on the page, in the app's one player.
        self.assertEqual(page.play_button.text(), "Play the preview")
        self.assertFalse(page.play_preview_button.isVisibleTo(page.poster_page), "there is no final yet")
        click(page.play_button)
        player = window.video_opener.player_window
        self.assertIs(player.docked_in, page.player_page)
        self.assertIs(page.stage.currentWidget(), page.player_page)
        self.assertEqual(player.open_path(), project / "versions" / "v001" / "renders" / "preview.mp4")
        self.assertEqual(len(players.players), 1)

        page.feedback_edit.setFocus()
        QTest.keyClicks(page.feedback_edit, "The opening is too slow.")
        self._click(page.save_notes_button)
        self.assertEqual((project / "feedback" / "v001.md").read_text(encoding="utf-8").strip(), "The opening is too slow.")
        self.assertIn("This is a revision", QApplication.clipboard().text())

        # 236 (item 7): Approve and export… says what it does, then exports when asked to.
        click(page.export_button)
        dialog = page.export_dialog
        self.assertTrue(dialog.isVisible())
        words = dialog.what.text()
        # 226 (161.2, 161.5): the export keeps the recording's own frame rate, and says which quality.
        self.assertIn("at the recording's own frame rate up to 60 fps, at the export quality below", words)
        self.assertIn("levels the sound for upload", words)
        self.assertIn("Nothing is uploaded.", words)
        self.assertEqual(dialog.quality_combo.currentText(), "YouTube (recommended)")
        self.assertEqual(dialog.replaces.text(), "v001 has no export yet: it will be made at YouTube (recommended).")
        click(dialog.export_button)
        self.assertIsNone(player.docked_in, "the player goes back to its own window while the export runs")
        self._wait(page)
        self.assertTrue((project / "export" / "race-v001.mp4").exists(), page.status_sentence.text())
        self.assertIn("Exported and checked: race-v001.mp4 (a new file in the export folder)", page.status_sentence.text())
        self._assert_status(page, "completed", STATUS_GREEN)
        self.assertEqual(window.recent_runs()[0]["workflow_title"], "AI Video Editor: export")
        self.assertTrue(page.tool_actions["open_export"].isEnabled())
        self.assertIn("Export ✓", page.files_summary.text())
        self.assertEqual(page._cards[str(project)].pill.text(), "Exported")

    def test_a_videos_own_export_quality_is_kept_cleared_and_used(self) -> None:
        # 226 (161.5, 178): the quality beside "Approve and export…", and the AI editor's label.
        window = self._window()
        project = self._project_with_a_version(window, editor_label="claude-opus-5.5")
        page = self._open_page(window)
        self._open_video(page, project)
        own = project / "editor-settings.json"
        self.assertEqual([tab.text() for tab in page.version_tabs], ["v001 · newest"])
        self.assertIn("v001 by claude-opus-5.5", page.project_details.text())
        # 236: the export quality is in Approve and export… (and under Files), where it is used.
        click(page.export_button)
        self.assertEqual(page.export_quality_combo.currentText(), "YouTube (recommended)")
        self.assertEqual(page.export_quality_state.text(), "Using main setting")

        choose_in_combo(page.export_quality_combo, "Smaller file")
        self.assertEqual(json.loads(own.read_text(encoding="utf-8")), {"export_quality": "smaller"})
        self.assertEqual(page.export_quality_state.text(), "Overridden")
        self.assertEqual(page.export_dialog.replaces.text(), "v001 has no export yet: it will be made at Smaller file.")
        choose_in_combo(page.export_quality_combo, "YouTube (recommended)")
        self.assertFalse(own.exists(), "the main setting's quality again removes this video's own")
        self.assertEqual(page.export_quality_state.text(), "Using main setting")
        page.export_dialog.reject()
        # The same choice under Files: the panel stays open, says which quality and whether it is the main
        # setting's, and the tick moves.
        self._choose(page, "files", "Smaller file")
        self.assertEqual(json.loads(own.read_text(encoding="utf-8")), {"export_quality": "smaller"})
        self.assertTrue(page.tool_panels["files"].isVisible())
        self.assertEqual(page.quality_heading.text(), "Export quality: Smaller file · Overridden")
        self.assertEqual([value for value, button in page.quality_buttons.items() if button.isChecked()], ["smaller"])
        self.assertEqual(page.actions_feedback.text(), "This video exports at Smaller file.")
        page.tool_panels["files"].hide()

        click(page.export_button)
        self.assertEqual(page.export_quality_combo.currentText(), "Smaller file")
        click(page.export_dialog.export_button)
        # 237: the job banner shows how far it has got, so the sentence no longer sends you elsewhere.
        self.assertEqual(page.status_sentence.text(), "Exporting and checking it.")
        self._wait(page)
        self.assertIn("Exported and checked", page.status_sentence.text())
        self.assertNotIn("export_quality", CoreRunner.instances[-1].payload, "the core reads the video's own choice")
        report = json.loads((project / "versions" / "v001" / "renders" / "render-final.json").read_text(encoding="utf-8"))
        self.assertEqual((report["export_quality"], report["export_quality_source"]), ("smaller", "project"))
        self.assertTrue((project / "export" / "race-v001-claude-opus-5.5.mp4").exists())
        # The exported mark comes from the version's own entry, whatever the export is named.
        self.assertIn("Export ✓", page.files_summary.text())
        # A second export says it replaces the first.
        click(page.export_button)
        self.assertEqual(page.export_dialog.replaces.text(), "There is already an export of v001: it will be made again "
                                                             "at Smaller file and replace the one in the export folder.")
        click(page.export_dialog.export_button)
        self._wait(page)
        self.assertIn("(replaced the earlier export)", page.status_sentence.text())

    def test_a_failed_run_says_so(self) -> None:
        window = self._window()
        page = self._open_page(window)
        missing = self.root / "gone.mkv"
        self._choose_recording(page, self.source)
        page.recording = missing
        self._click(page.prepare_button)
        self._wait(page)
        self.assertIn("did not finish", page.status_sentence.text())
        self._assert_status(page, "failed", STATUS_RED)
        latest = window.recent_runs()[0]
        self.assertEqual(latest["status"], "failed")
        # 243: the run's one recording is kept with its outcome.
        kept = [(item["path"], item["outcome"]) for item in window.records.run_items(latest["run_id"])]
        self.assertEqual(kept, [(str(missing), "failed")])

    def test_the_editor_settings_tab_saves_its_own_values(self) -> None:
        window = self._window()
        panel = window.ai_video_editor_settings
        panel.folder_edit.setText(str(self.root / "videos"))
        panel.budget_combo.setCurrentIndex(panel.budget_combo.findData("thorough"))
        # Saving re-applies the theme to every window in the process. In a test run that includes
        # windows earlier tests left behind; this test is about the tab's own values.
        with patch.object(QMessageBox, "information"), patch("media_manglers_workbench.app.apply_theme"):
            window.save_settings_from_page()
        self.assertEqual(window.app_settings["race_video_output_folder"], str(self.root / "videos"))
        self.assertEqual(window.app_settings["race_video_budget"], "thorough")
        self.assertEqual(window.ai_video_editor_page.output_root, self.root / "videos")

    def test_the_settings_tab_saves_export_quality_and_quick_passes_through_save(self) -> None:
        # 226 (decisions C and 161.5), clicked through the tab and its Save button.
        window = self._window()
        panel = window.ai_video_editor_settings
        self._click(window.nav_buttons["Settings"])
        bring_to_front(panel)
        self.assertEqual(panel.quality_combo.currentText(), "YouTube (recommended)")
        self.assertEqual(panel.quick_combo.currentText(), "Whisper small (faster)")
        self.assertEqual(panel.quick_state.text(), "Overridden", "small beside the main model, medium")
        self.assertNotIn("remembered from the last video", panel.note.text())
        self.assertIn("Narration track setting (Settings > General / Startup)", panel.note.text())
        self.assertIn("Auto", panel.note.text())

        choose_in_combo(panel.quality_combo, "Highest quality")
        choose_in_combo(panel.quick_combo, "Use main setting")
        self.assertEqual(panel.quick_state.text(), "Using main setting")
        save = [button for button in window.findChildren(QPushButton) if button.text() == "Save settings"]
        self.assertEqual(len(save), 1)
        with patch.object(QMessageBox, "information"), patch("media_manglers_workbench.app.apply_theme"):
            click(save[0])
        self.assertEqual((window.app_settings["race_video_export_quality"], window.app_settings["race_video_quick_whisper_model"]),
                         ("highest", "main"))
        saved = json.loads((self.root / "settings.json").read_text(encoding="utf-8"))["settings"]
        self.assertEqual((saved["race_video_export_quality"], saved["race_video_quick_whisper_model"]), ("highest", "main"))

        # The page follows the new main setting for a video without its own.
        project = self._project_with_a_version(window)
        page = self._open_page(window)
        self._open_video(page, project)
        click(page.export_button)
        self.assertEqual(page.export_quality_combo.currentText(), "Highest quality")
        self.assertEqual(page.export_quality_state.text(), "Using main setting")
        page.export_dialog.reject()

    def test_the_model_names_in_settings_are_the_ones_the_prompt_uses(self) -> None:
        # 174: the tools rename their models, so the operator keeps the names current here.
        window = self._window()
        panel = window.ai_video_editor_settings
        self.assertEqual(panel.model_edits["codex"].text(), "GPT-6.1 Sol", "today's default")
        panel.model_edits["codex"].setText("GPT-7 Nova")
        with patch.object(QMessageBox, "information"), patch("media_manglers_workbench.app.apply_theme"):
            window.save_settings_from_page()
        self.assertEqual(window.app_settings["race_video_codex_model"], "GPT-7 Nova")
        project = self._project_with_a_version(window)
        page = self._open_page(window)
        self._open_video(page, project)
        # 236: with a version, the prompts are under the video's Prompt button.
        self._choose(page, "prompt", "Copy prompt for Codex")
        self.assertTrue(QApplication.clipboard().text().startswith("MODEL: GPT-7 Nova\n"))
        self.assertEqual(page.actions_feedback.text(), "Copied. Paste it into Codex.")
        self._choose(page, "prompt", "Copy prompt for Claude Code")
        self.assertTrue(QApplication.clipboard().text().startswith("MODEL: Opus 5.5\n"))

    def test_a_fresh_edit_starts_from_the_page_with_its_own_prompt(self) -> None:
        window = self._window()
        project = self._project_with_a_version(window)
        page = self._open_page(window)
        self._open_video(page, project)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self._choose(page, "prompt", "Start a fresh edit")
        fresh = project.parent / "race-edit-2"
        self.assertTrue((fresh / "project.json").exists())
        self.assertEqual(page.current_project()["name"], "race-edit-2", "the new edit is chosen")
        self.assertEqual(page.version_tabs, [])
        self.assertIn("a separate edit of race", page.project_details.text())
        self.assertEqual(page.actions_feedback.text(), "Fresh edit ready")
        self.assertIs(page.stage.currentWidget(), page.empty_page, "the fresh edit has no version yet")
        self._choose(page, "prompt", "Copy prompt for Codex")
        self.assertIn(str(fresh / "analysis" / "digest.md"), QApplication.clipboard().text())
        self.assertEqual(len(json.loads((project / "project.json").read_text(encoding="utf-8"))["versions"]), 1,
                         "the first edit keeps its version")

    def test_painting_a_mask_saves_it_softened_and_keeps_the_drawing(self) -> None:
        store = self.root / "privacy"
        dialog = PrivacyMaskDialog(self.wide, ffmpeg=FFMPEG, store=store)
        dialog.show()
        dialog.camera_combo.setCurrentIndex(dialog.camera_combo.findData("right"))
        dialog.moment.setValue(1)
        self._click(dialog.show_button)
        self.assertFalse(dialog.canvas.still.isNull(), dialog.status.text())
        self.assertEqual((dialog.canvas.still.width(), dialog.canvas.still.height()), (1920, 1080))
        canvas = dialog.canvas
        centre = QPoint(canvas.width() // 2, canvas.height() // 2)
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre)
        for step in range(1, 6):
            point = QPointF(centre.x() + step * 10, centre.y())
            QApplication.sendEvent(canvas, QMouseEvent(QEvent.Type.MouseMove, point, canvas.mapToGlobal(point),
                                                       Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                                                       Qt.KeyboardModifier.NoModifier))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre)
        self._click(dialog.save_button)
        dialog.close()

        saved = json.loads((store / "masks.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["masks"], {"right": "right.png"})
        self.assertTrue(drawn_path(store, "right").exists())
        mask = QImage(str(store / "right.png")).convertToFormat(QImage.Format.Format_Grayscale8)
        self.assertEqual((mask.width(), mask.height()), (1920, 1080))
        self.assertGreater(mask.pixelColor(960, 540).value(), 200, "the painted centre is private")
        self.assertLess(mask.pixelColor(20, 20).value(), 10, "an unpainted corner is not")

    def test_the_mask_editors_camera_still_stays_in_the_apps_temporary_folder(self) -> None:
        # 226: the unblurred camera still is for the operator only. It is written to the app's
        # temporary folder (MEDIA_MANGLERS_SCRATCH_ROOT when set), never beside a project, and goes
        # when the dialog closes.
        scratch = self.root / "app-temp"
        with patch.dict(os.environ, {"MEDIA_MANGLERS_SCRATCH_ROOT": str(scratch)}):
            dialog = PrivacyMaskDialog(self.wide, ffmpeg=FFMPEG, store=self.root / "privacy")
        dialog.show()
        dialog.camera_combo.setCurrentIndex(dialog.camera_combo.findData("left"))
        dialog.moment.setValue(1)
        self._click(dialog.show_button)
        self.assertFalse(dialog.canvas.still.isNull(), dialog.status.text())
        stills = sorted(scratch.rglob("*.png"))
        self.assertEqual([path.name for path in stills], ["left.png"])
        dialog.close()
        self.app.processEvents()
        self.assertFalse(stills[0].parent.exists(), "the still goes when the dialog closes")
        self.assertEqual(sorted(path.name for path in self.wide.parent.glob("*.png")), [],
                         "nothing is written beside the recording")


if __name__ == "__main__":
    unittest.main()
