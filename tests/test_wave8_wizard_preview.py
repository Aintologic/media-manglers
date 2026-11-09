"""136 (Wave 8): the New Review wizard's Preview track plays in the shared built-in player.

The wizard's own preview player (a sound output made the way that was silent on Windows, a clip cut
from the recording and a little waveform) is gone: one player remains. Preview track opens the
built-in player on the chosen track at the chosen preview region, the "Previewing" line follows what
that player really plays, and a real-player test checks the sound goes to the default device.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QObject, Qt, Signal  # noqa: E402
from PySide6.QtMultimedia import QMediaDevices, QMediaPlayer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.audio_detection import (  # noqa: E402
    AudioPreviewRegion,
    AudioSampleFeatures,
    AudioStreamInfo,
    RankedAudioStream,
    SourceAudioInspection,
)
from media_manglers_workbench.metadata import WORKFLOW_CODEX_EVIDENCE  # noqa: E402
from media_manglers_workbench.runner import FakeRunner  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: E402
from tests.qt_input import bring_to_front, row_point  # noqa: E402
from tests.test_workbench_bug_reports import _resources  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
FFMPEG = shutil.which("ffmpeg")


class StubPlayerWindow(QObject):
    """Stands in for the built-in player window: notes what it was asked to open."""

    track_heard = Signal(str, int)
    cannot_play = Signal(str)
    instances: list["StubPlayerWindow"] = []

    def __init__(self, _host, _opener) -> None:
        super().__init__()
        self.opened: list[tuple] = []
        self.yields = 0
        StubPlayerWindow.instances.append(self)

    def open_target(self, target, **options) -> None:
        self.opened.append((target, options))

    def yield_audio(self) -> None:
        self.yields += 1

    def release_media(self) -> None:
        return None

    def shutdown(self, _wait_ms: int = 0) -> bool:
        return True

    def close(self) -> bool:
        return True

    def windowModality(self):  # noqa: N802
        return Qt.WindowModality.NonModal


def _inspection(source: Path, ordinals=(0, 1), regions=((12.0, 8.0), (40.0, 6.0))) -> SourceAudioInspection:
    streams = [AudioStreamInfo(ordinal, ordinal + 1, title="Microphone" if ordinal == 1 else "Game", channels=1)
               for ordinal in ordinals]
    return SourceAudioInspection(
        source, streams,
        [RankedAudioStream(streams[-1], 4.0, 0.95, ("clean mic",), AudioSampleFeatures())],
        "synthetic-layout", "synthetic recorder", 120.0,
        preview_regions={ordinal: [AudioPreviewRegion(start, length, 1.0, 0.8, f"Audible region {index + 1}")
                                   for index, (start, length) in enumerate(regions)] for ordinal in ordinals},
        selected_ordinal=ordinals[-1],
    )


class WizardPreviewTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window: WorkbenchWindow | None = None
        StubPlayerWindow.instances = []

    def tearDown(self) -> None:
        if self.window is not None:
            self.window._closing_after_smoke = True
            self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def _window(self, **settings) -> WorkbenchWindow:
        settings_path = self.root / "settings.json"
        settings_path.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
            "log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
            "output_folder": str(self.root / "out"), **settings}}), encoding="utf-8")
        self.window = WorkbenchWindow(settings_path=settings_path, profiles_dir=self.root / "profiles",
                                      runner_factory=FakeRunner, resources=_resources())
        self.window.resize(1400, 900)
        self.window.show()
        self.app.processEvents()
        self.window.start_workflow_from_home(WORKFLOW_CODEX_EVIDENCE)
        # The Source step, where the operator is when previewing a track.
        self.window.wizard_steps.setCurrentRow(1)
        self.app.processEvents()
        return self.window

    def _with_sources(self, window: WorkbenchWindow, *names: str) -> list[Path]:
        folder = self.root / "sources"
        folder.mkdir(exist_ok=True)
        sources = []
        for name in names:
            path = folder / name
            if not path.exists():
                path.write_bytes(b"synthetic")
            sources.append(path)
        window.input_path_edit.setText(str(sources[0] if len(sources) == 1 else folder))
        keys = [str(path.resolve()) for path in sources]
        window.audio_expected_sources = keys
        window.audio_inspections = {key: _inspection(Path(key)) for key in keys}
        window.active_audio_source = keys[0]
        window._populate_audio_stream_combo()
        window._refresh_audio_batch_table()
        return [Path(key) for key in keys]

    def _click(self, widget) -> None:
        bring_to_front(widget)
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        self.app.processEvents()


class PreviewTrackTests(WizardPreviewTestCase):
    def test_preview_track_opens_the_shared_player_on_the_track_at_the_region(self) -> None:
        window = self._window()
        (source,) = self._with_sources(window, "session.mkv")
        with mock.patch("media_manglers_workbench.video_open.ReviewPlayerWindow", StubPlayerWindow):
            self._click(window.preview_audio_stream_button)
        stub = StubPlayerWindow.instances[-1]
        target, options = stub.opened[-1]
        self.assertEqual(target.path, source)
        self.assertEqual(target.hear_track, 2)
        self.assertEqual(target.start_seconds, 12.0)
        self.assertEqual(target.stretches, ((12.0, 20.0), (40.0, 46.0)))
        self.assertEqual(target.stretch_kind, "speech")
        self.assertEqual(target.label, "Track 2: is this your microphone?")
        self.assertEqual(options, {"autoplay": True, "insist_on_track": True})
        self.assertIn("— preparing…", window.audio_preview_identity.text())

    def test_the_preview_region_sets_where_the_player_starts(self) -> None:
        window = self._window()
        self._with_sources(window, "session.mkv")
        window.audio_preview_region_combo.setCurrentIndex(1)
        with mock.patch("media_manglers_workbench.video_open.ReviewPlayerWindow", StubPlayerWindow):
            self._click(window.preview_audio_stream_button)
        self.assertEqual(StubPlayerWindow.instances[-1].opened[-1][0].start_seconds, 40.0)

    def test_it_is_always_the_built_in_player_whatever_the_setting_says(self) -> None:
        window = self._window(video_player="vlc")
        self._with_sources(window, "session.mkv")
        with mock.patch("media_manglers_workbench.video_open.ReviewPlayerWindow", StubPlayerWindow), \
                mock.patch.object(window.video_opener, "_launch") as launched:
            self._click(window.preview_audio_stream_button)
        launched.assert_not_called()
        self.assertTrue(StubPlayerWindow.instances[-1].opened)

    def test_previewing_says_ready_only_when_the_player_plays_that_track(self) -> None:
        window = self._window()
        (source,) = self._with_sources(window, "session.mkv")
        with mock.patch("media_manglers_workbench.video_open.ReviewPlayerWindow", StubPlayerWindow):
            self._click(window.preview_audio_stream_button)
        stub = StubPlayerWindow.instances[-1]
        stub.track_heard.emit(str(self.root / "elsewhere.mkv"), 2)
        self.assertNotIn("— ready", window.audio_preview_identity.text())
        stub.track_heard.emit(str(source), 1)
        self.assertNotIn("— ready", window.audio_preview_identity.text(), "the player plays another track")
        stub.track_heard.emit(str(source), 2)
        self.assertIn("— ready", window.audio_preview_identity.text())
        self.assertIn("Playing session.mkv, Track 2 in the built-in player. Confirm it only if you hear your "
                      "microphone narration.", window.audio_stream_status.text())

    def test_a_recording_the_player_cannot_play_says_preview_unavailable_and_the_next_try_opens_again(self) -> None:
        window = self._window()
        (source,) = self._with_sources(window, "session.mkv")
        with mock.patch("media_manglers_workbench.video_open.ReviewPlayerWindow", StubPlayerWindow):
            self._click(window.preview_audio_stream_button)
            stub = StubPlayerWindow.instances[-1]
            stub.cannot_play.emit(str(source))
            self.assertIn("— preview unavailable", window.audio_preview_identity.text())
            self._click(window.preview_audio_stream_button)
        self.assertEqual(len(stub.opened), 2, "the next Preview track opens it again")

    def test_choosing_another_source_pauses_the_player_and_a_late_answer_for_the_old_one_changes_nothing(self) -> None:
        window = self._window()
        first, second = self._with_sources(window, "alpha.mkv", "bravo.mkv")
        with mock.patch("media_manglers_workbench.video_open.ReviewPlayerWindow", StubPlayerWindow):
            self._click(window.preview_audio_stream_button)
            stub = StubPlayerWindow.instances[-1]
            yields = stub.yields
            table = window.audio_batch_table
            row = next(index for index in range(table.rowCount())
                       if str(table.item(index, 0).data(Qt.ItemDataRole.UserRole)) == str(second))
            bring_to_front(table)
            QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                             row_point(table, table.model().index(row, 0)))
            self.app.processEvents()
        self.assertEqual(window.active_audio_source, str(second))
        self.assertGreater(stub.yields, yields, "the player is paused, keeping its place")
        self.assertEqual(len(stub.opened), 1, "choosing a row never opens the player by itself")
        stub.track_heard.emit(str(first), 2)
        self.assertNotIn("— ready", window.audio_preview_identity.text())
        self.assertIn("bravo", window.audio_preview_identity.text())


class OnePlayerTests(unittest.TestCase):
    def test_no_sound_output_or_media_player_is_made_anywhere_but_the_built_in_player(self) -> None:
        made: list[str] = []
        for path in (REPO_ROOT / "src").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = getattr(node.func, "id", getattr(node.func, "attr", ""))
                    if name in {"QAudioOutput", "QMediaPlayer"}:
                        made.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
        self.assertTrue(made)
        self.assertEqual({entry.split(":")[0] for entry in made},
                         {str(Path("src/media_manglers_workbench/review_player.py"))})


@unittest.skipUnless(FFMPEG, "FFmpeg is required")
class RealPlayerPreviewTests(WizardPreviewTestCase):
    def test_preview_track_plays_the_chosen_track_on_the_default_sound_device(self) -> None:
        if QMediaDevices.defaultAudioOutput().isNull():
            self.skipTest("this computer has no default sound device")
        from tests.test_wave8_track_levels import make_tracks

        source = make_tracks(self.root / "sources" / "two-tracks.mkv", [
            "sine=frequency=220:sample_rate=48000:duration={s}",
            "sine=frequency=880:sample_rate=48000:duration={s}",
        ], 30)
        # Quiet enough to go unheard while the suite runs, but not muted: the sound is really sent.
        window = self._window(review_player_volume=0.01)
        key = str(source.resolve())
        window.input_path_edit.setText(str(source))
        window.audio_expected_sources = [key]
        window.audio_inspections = {key: _inspection(Path(key), regions=((5.0, 5.0),))}
        window.active_audio_source = key
        window._populate_audio_stream_combo()
        self._click(window.preview_audio_stream_button)
        deadline = time.monotonic() + 20
        while "— ready" not in window.audio_preview_identity.text() and time.monotonic() < deadline:
            QTest.qWait(50)
        self.assertIn("— ready", window.audio_preview_identity.text())
        player_window = window.video_opener.player_window
        player = player_window._player
        self.assertEqual(player.activeAudioTrack(), 1)
        self.assertEqual(player_window.audio_output.device().id(), QMediaDevices.defaultAudioOutput().id())
        self.assertFalse(player_window.audio_output.isMuted())
        self.assertGreater(player_window.audio_output.volume(), 0.0)
        start = player.position()
        QTest.qWait(800)
        self.assertEqual(player.playbackState(), QMediaPlayer.PlaybackState.PlayingState)
        self.assertGreaterEqual(start, 4_500)
        self.assertGreater(player.position(), start, "it plays on")
        player_window.close()
        self.assertTrue(player_window.shutdown(5000))


if __name__ == "__main__":
    unittest.main()
