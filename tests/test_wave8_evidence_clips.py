"""134 (Wave 8): a package's clips and small review copies are listed on the Evidence page and play.

A synthetic package (the test fixture, plus a narration index of its own) is opened on the Evidence
page and driven by clicks: the "[clips]" row lists the recording's small review copy and its clips,
a bug report also lists the clips that overlap it, double-click plays through the shared opener (the
review copy standing in for its recording), a missing file is marked and opens its folder, and a
package without the index loads exactly as before.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.runner import FakeRunner  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: E402
from tests.qt_input import double_click_row, row_point  # noqa: E402
from tests.test_workbench_bug_reports import _resources  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "workbench" / "evidence_package"


class EvidenceClipsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.package = self.root / "run" / "codex-evidence-package"
        shutil.copytree(FIXTURE, self.package)
        self.recording = self.root / "recordings" / "fixture-session.mp4"
        manifest = json.loads((self.package / "manifest.json").read_text(encoding="utf-8"))
        manifest["sources"][0]["source_path"] = str(self.recording)
        (self.package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.window: WorkbenchWindow | None = None

    def tearDown(self) -> None:
        if self.window is not None:
            self.window._closing_after_smoke = True
            self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def _narration(self, *, copy: bool = True, clips: bool = True) -> None:
        folder = self.package / "artifacts" / "narration" / "fixture-source"
        (folder / "clips").mkdir(parents=True, exist_ok=True)
        moments = [
            {"moment_index": 1, "start": "00:02:10.000", "start_seconds": 130.0, "end_seconds": 140.0, "text": "a",
             "clips": [{"path": "artifacts/narration/fixture-source/clips/near.mp4", "start": "00:02:05.000",
                        "end": "00:02:30.000", "part": 1}]},
            {"moment_index": 2, "start": "00:15:00.000", "start_seconds": 900.0, "end_seconds": 910.0, "text": "b",
             "clips": [{"path": "artifacts/narration/fixture-source/clips/far.mp4", "start": "00:14:55.000",
                        "end": "00:15:20.000", "part": 1}]},
        ]
        if clips:
            for name in ("near.mp4", "far.mp4"):
                (folder / "clips" / name).write_bytes(b"synthetic clip")
        if copy:
            (folder / "review_video_fixture-source.mp4").write_bytes(b"synthetic copy")
        (self.package / "NARRATION_EVIDENCE.json").write_text(json.dumps({"schema_version": 1, "sources": [
            {"source_id": "fixture-source", "source_filename": "fixture-session.mp4",
             "review_video": "artifacts/narration/fixture-source/review_video_fixture-source.mp4",
             "moments": moments}]}), encoding="utf-8")

    def _window(self) -> WorkbenchWindow:
        settings_path = self.root / "settings.json"
        settings_path.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
            "log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
            "output_folder": str(self.root / "out")}}), encoding="utf-8")
        self.window = WorkbenchWindow(settings_path=settings_path, profiles_dir=self.root / "profiles",
                                      runner_factory=FakeRunner, resources=_resources())
        self.window.resize(1400, 900)
        self.window.show()
        self.app.processEvents()
        QTest.mouseClick(self.window.nav_buttons["Evidence"], Qt.MouseButton.LeftButton)
        self.app.processEvents()
        return self.window

    def _rows(self, window) -> list[str]:
        return [window.candidate_list.item(row).text() for row in range(window.candidate_list.count())]

    def _files(self, window) -> list[str]:
        return [window.evidence_file_list.item(row).text() for row in range(window.evidence_file_list.count())]

    def _click(self, view, row: int) -> None:
        index = view.model().index(row, 0)
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         row_point(view, index))
        self.app.processEvents()

    def test_the_clips_row_lists_the_review_copy_and_every_clip(self) -> None:
        self._narration()
        window = self._window()
        window.load_package(self.package)
        rows = self._rows(window)
        self.assertEqual(rows[-1], "[clips]  fixture-session.mp4")
        self._click(window.candidate_list, len(rows) - 1)
        self.assertEqual(self._files(window), [
            "Small review copy: review_video_fixture-source.mp4",
            "Clip 1 (0:02:10): near.mp4",
            "Clip 2 (0:15:00): far.mp4",
        ])
        self.assertIsNone(window.current_item)
        for button in (window.rerender_candidate_button, window.export_candidate_prompts_button,
                       window.open_candidate_button, window.play_candidate_button):
            self.assertFalse(button.isEnabled())
            self.assertIn("select a bug report", button.toolTip().lower())
        self.assertIn("fixture-session.mp4", window.candidate_detail.toPlainText())

    def test_double_click_plays_them_and_the_review_copy_stands_in_for_its_recording(self) -> None:
        self._narration()
        window = self._window()
        window.load_package(self.package)
        self._click(window.candidate_list, window.candidate_list.count() - 1)
        with mock.patch.object(window.video_opener, "open", return_value=True) as opened:
            double_click_row(window.evidence_file_list, window.evidence_file_list.model().index(0, 0))
            double_click_row(window.evidence_file_list, window.evidence_file_list.model().index(1, 0))
        copy, clip = (call.args[0] for call in opened.call_args_list)
        self.assertEqual(copy.path.name, "review_video_fixture-source.mp4")
        self.assertEqual(copy.stands_in_for, self.recording)
        self.assertEqual(clip.path.name, "near.mp4")
        self.assertIsNone(clip.stands_in_for)
        self.assertTrue(clip.is_package_file)

    def test_a_bug_report_also_lists_its_recordings_copy_and_the_clips_that_overlap_it(self) -> None:
        self._narration()
        window = self._window()
        before = None
        window.load_package(self.package)
        self._click(window.candidate_list, 0)
        candidate = window.current_item
        self.assertEqual(candidate.item_id, "ticket-001")
        files = self._files(window)
        self.assertEqual(files[-2:], ["Small review copy: review_video_fixture-source.mp4", "Clip 1 (0:02:10): near.mp4"])
        self.assertNotIn("Clip 2 (0:15:00): far.mp4", files, "a clip outside the bug report's time is not listed under it")
        before = [item.label for item in candidate.evidence_files]
        self.assertNotIn("Clip", " ".join(before), "the bug report's own files and drafts do not change")

    def test_a_missing_clip_is_marked_and_opens_the_folder_it_should_be_in(self) -> None:
        self._narration(clips=False)
        window = self._window()
        window.load_package(self.package)
        self._click(window.candidate_list, window.candidate_list.count() - 1)
        self.assertIn("Clip 1 (0:02:10): near.mp4  [missing]", self._files(window))
        with mock.patch.object(window.video_opener, "open", return_value=True) as opened, \
                mock.patch("media_manglers_workbench.app.QDesktopServices.openUrl", return_value=True) as shown:
            double_click_row(window.evidence_file_list, window.evidence_file_list.model().index(1, 0))
        opened.assert_not_called()
        self.assertTrue(shown.call_args.args[0].toLocalFile().replace("/", "\\").endswith("clips"))

    def test_a_package_without_the_narration_index_loads_exactly_as_before(self) -> None:
        window = self._window()
        window.load_package(self.package)
        self.assertFalse(any(row.startswith("[clips]") for row in self._rows(window)))
        self._click(window.candidate_list, 0)
        self.assertFalse(any("Clip" in row or "review copy" in row for row in self._files(window)))

    def test_a_package_with_no_bug_reports_does_not_keep_the_previous_packages_files(self) -> None:
        window = self._window()
        window.load_package(self.package)
        self.assertTrue(self._files(window), "the first package's files are listed")
        empty = self.root / "empty" / "codex-evidence-package"
        empty.mkdir(parents=True)
        (empty / "manifest.json").write_text(json.dumps({"sources": []}), encoding="utf-8")
        window.load_package(empty)
        self.assertEqual(self._rows(window), [])
        self.assertEqual(self._files(window), [])
        self.assertNotIn("ticket-001", window.candidate_detail.toPlainText())


if __name__ == "__main__":
    unittest.main()
