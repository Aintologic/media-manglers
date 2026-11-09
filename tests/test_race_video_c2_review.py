"""242 (Wave C2): what the independent review of the wave found, each shown failing before its fix.

Real recordings made with FFmpeg, the real commands and the real library (tests/conftest.py points it at a folder of the
run's own). Only a library failure is simulated, where that is the point of the test.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core import recording_records, track_levels  # noqa: E402
from media_manglers.core.race_video import link  # noqa: E402
from media_manglers.core.race_video import requests as race_requests  # noqa: E402
from media_manglers.core.race_video.library import reconcile  # noqa: E402
from media_manglers.core.race_video.project import add_version, create_project, project_folder, read_json  # noqa: E402
from media_manglers.core.race_video.render import RenderOptions, render_version  # noqa: E402
from tests.test_race_video_recording_authority import FFMPEG, FFPROBE, LAYOUT, make_recording, timeline  # noqa: E402


def _quiet(call, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return call(*args, **kwargs)


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class ReviewFindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_class = tempfile.TemporaryDirectory()
        root = Path(cls.temp_class.name)
        cls.recording = make_recording(root / "drive-a" / "race.mkv", "testsrc")
        cls.other = make_recording(root / "drive-b" / "race.mkv", "rgbtestsrc")
        cls.options = RenderOptions(ffmpeg=FFMPEG, ffprobe=FFPROBE, encoder="x264", hwaccel="none")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp_class.cleanup()

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.out = self.root / "out"
        self.copies = 0

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _copy(self, name: str = "race.mkv") -> Path:
        path = self.root / "work" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.recording, path)
        self.copies += 1
        moment = (1_700_000_000 + 60 * self.copies) * 1_000_000_000
        os.utime(path, ns=(moment, moment))
        return path

    def _prepare(self, source: Path) -> Path:
        result = _quiet(race_requests.prepare_from_request, {
            "source": str(source), "output_root": str(self.out), "budget": "light", "layout": LAYOUT,
            "skip_transcript": True, "track_roles": "", "tracks": {"voice": 0, "game": 1}, "ffmpeg": FFMPEG,
            "ffprobe": FFPROBE})
        return Path(result["project"])

    def _renamed_and_linked(self) -> tuple[Path, Path, Path, int]:
        source = self._copy()
        project = self._prepare(source)
        number = add_version(project, timeline(source), source_duration=12.0, audio_streams=2)
        renamed = source.with_name("renamed.mkv")
        source.rename(renamed)
        link.link_project(project, renamed)
        return project, source, renamed, number

    def test_an_older_version_is_refused_when_a_file_was_saved_over_the_linked_recording(self) -> None:
        project, _old, renamed, number = self._renamed_and_linked()
        shutil.copyfile(self.other, renamed)
        with self.assertRaisesRegex(ValueError, "another file was saved in its place"):
            render_version(project, number, "preview", self.options)

    def test_a_linked_renamed_recording_opens_and_prepares_its_own_video(self) -> None:
        project, _old, renamed, _number = self._renamed_and_linked()
        self.assertEqual(project_folder(self.out, renamed, read=False), project)
        self.assertEqual(self._prepare(renamed), project, "Prepare goes on in the video it has, not a new one")
        self.assertEqual(sorted(path.name for path in (self.out / "race-videos").iterdir()), [project.name])

    def test_a_rename_before_any_scan_is_offered_for_linking(self) -> None:
        source = self._copy()
        project = self._prepare(source)                       # Prepare registers the copy in the library by its path
        source.rename(source.with_name("renamed.mkv"))
        project_json = project / "project.json"
        meta = json.loads(project_json.read_text(encoding="utf-8"))
        meta.pop("recording")                                  # as a video made before Wave C2
        project_json.write_text(json.dumps(meta), encoding="utf-8")
        connection = recording_records.connect_read_only()
        try:
            found = link.evidence_for(project, connection=connection)
        finally:
            connection.close()
        self.assertEqual((found.verdict, found.target), (link.MOVED, str(source.with_name("renamed.mkv"))))

    def test_levels_cut_short_by_a_stopped_job_never_say_the_sound_differs(self) -> None:
        source = self._copy()
        project = create_project(self.out, source, "race")
        seconds = [-30.0 + (index % 7) for index in range(60)]
        analysis = project / "analysis" / "analysis.json"
        analysis.write_text(json.dumps({"duration": 60.0, "loudness_per_second": {"0": seconds, "1": seconds}}),
                            encoding="utf-8")
        cache = self.root / "cache"
        track_levels._save(cache, source, source.stat(), track_levels.Levels(
            tracks={1: seconds[:25], 2: seconds[:25]}, duration_seconds=60.0, complete=False))
        found = link.evidence_for(project, cache=cache)
        self.assertEqual((found.verdict, found.sound_matches), (link.CAN_LINK, None))

    def test_a_second_link_keeps_the_first_kept_copy(self) -> None:
        source = self._copy()
        project = create_project(self.out, source, "race")
        before_first = (project / "project.json").read_bytes()
        link.link_project(project, source)
        renamed = source.with_name("renamed.mkv")
        source.rename(renamed)
        link.link_project(project, renamed)
        self.assertEqual((project / "project.json.before-link").read_bytes(), before_first)
        self.assertTrue((project / "project.json.before-link-2").is_file())

    def test_a_library_that_cannot_be_opened_never_fails_an_agent_command(self) -> None:
        project = self._prepare(self._copy())
        with mock.patch.object(recording_records, "connect", side_effect=RuntimeError("backup did not check out")):
            result = _quiet(race_requests.add_version_from_request,
                            {"project": str(project), "timeline": timeline(project_recording_path(project)),
                             "ffprobe": FFPROBE})
        self.assertEqual(result["version"], 1)

    def test_a_video_made_by_analyze_is_bound_too(self) -> None:
        source = self._copy()
        result = _quiet(race_requests.analyze_from_request, {
            "source": str(source), "output_root": str(self.out), "budget": "light", "layout": LAYOUT,
            "tracks": {"voice": 0, "game": 1}, "ffmpeg": FFMPEG, "ffprobe": FFPROBE})
        self.assertIn("recording", read_json(Path(result["project"]) / "project.json"))

    def test_an_older_video_s_render_report_keeps_its_shape(self) -> None:
        project = create_project(self.out, self.recording, "race")
        number = add_version(project, timeline(self.recording), source_duration=12.0, audio_streams=2)
        report = render_version(project, number, "preview", self.options)
        self.assertNotIn("recording", report)

    def test_an_index_with_nothing_to_change_waits_for_no_writer(self) -> None:
        create_project(self.out, self.recording, "race")
        connection = recording_records.connect(backup=False)
        holder = recording_records.connect(backup=False)
        try:
            reconcile(connection, self.out)
            connection.execute("PRAGMA busy_timeout = 300")
            holder.execute("BEGIN IMMEDIATE")              # a scan or an agent's command writing at this moment
            try:
                self.assertEqual(reconcile(connection, self.out), 0)
            finally:
                holder.rollback()
        finally:
            holder.close()
            connection.close()


def project_recording_path(project: Path) -> Path:
    return Path(read_json(project / "project.json")["source"])


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class WalkFindingTests(unittest.TestCase):
    """What the real-screen walk of the packaged build found, clicked as the operator does."""

    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication  # noqa: PLC0415

        cls.app = QApplication.instance() or QApplication([])
        cls.temp_class = tempfile.TemporaryDirectory()
        cls.recording = make_recording(Path(cls.temp_class.name) / "race.mkv", "testsrc")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp_class.cleanup()

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window = None

    def tearDown(self) -> None:
        if self.window is not None:
            self.window._closing_after_smoke = True
            self.window.close()
            self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def _page(self):
        from media_manglers_workbench.ai_video_editor import PAGE_NAME  # noqa: PLC0415
        from media_manglers_workbench.app import WorkbenchWindow  # noqa: PLC0415
        from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: PLC0415
        from tests.qt_input import click  # noqa: PLC0415
        from tests.test_workbench_ai_video_editor import CoreRunner, _resources  # noqa: PLC0415

        settings = self.root / "settings.json"
        settings.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
            "log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
            "output_folder": str(self.root / "out")}}), encoding="utf-8")
        self.window = WorkbenchWindow(settings_path=settings, profiles_dir=self.root / "profiles",
                                      runner_factory=CoreRunner, resources=_resources())
        self.window.show()
        self.app.processEvents()
        click(self.window.nav_buttons[PAGE_NAME])
        return self.window.ai_video_editor_page, click

    def _source(self, name: str) -> Path:
        path = self.root / "work" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.recording, path)
        return path

    def test_a_recording_renamed_while_the_page_was_hidden_is_offered_when_it_is_shown_again(self) -> None:
        from media_manglers.core.race_video.project import recording_block  # noqa: PLC0415

        source = self._source("race.mkv")
        create_project(self.root / "out", source, "race", recording=recording_block(source))
        page, click = self._page()
        self.assertFalse(page.link_button.isVisible(), "a bound video whose recording is there is not offered")
        click(self.window.nav_buttons["Home"])
        source.rename(source.with_name("renamed.mkv"))
        click(self.window.nav_buttons["AI Video Editor"])
        self.assertTrue(page.link_button.isVisible())
        self.assertIn("1 video is not linked to its recording yet", page.link_line.text())

    def test_each_video_s_link_button_is_in_sight_without_scrolling(self) -> None:
        import time  # noqa: PLC0415

        for name in ("first", "second", "third"):
            create_project(self.root / "out", self._source(f"{name}.mkv"), name)
        page, click = self._page()
        click(page.link_button)
        deadline = time.monotonic() + 30
        while page.link_dialog is None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.02)
        dialog = page.link_dialog
        self.app.processEvents()
        from PySide6.QtWidgets import QScrollArea  # noqa: PLC0415

        viewport = dialog.findChild(QScrollArea).viewport()
        for index in range(2):
            with self.subTest(video=index):
                button = dialog.buttons[index]
                self.assertTrue(button.isVisible())
                top_left = button.mapTo(viewport, button.rect().topLeft())
                bottom = button.mapTo(viewport, button.rect().bottomLeft())
                self.assertTrue(viewport.rect().contains(top_left) and viewport.rect().contains(bottom),
                                f"the button of video {index + 1} is out of the list's view")


if __name__ == "__main__":
    unittest.main()
