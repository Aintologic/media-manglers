"""Continue after a stop keeps working from the library (115, 244, Wave A2.4).

A stopped Find my bug reports run is kept in the library as the same record settings.json held: its
dated folder, its recordings in order and the track the operator chose for each. Continue picks it up
after a restart, into the same dated folder, without a recording marked never-use since; Start a new
package instead and Start over forget it. It belongs to this PC: Save profile as never copies it into a
profile, applying a profile never brings one back, and a settings export never carries it.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QInputDialog  # noqa: E402

import test_bug_reports_control as control  # noqa: E402
import test_workbench_bug_reports as base  # noqa: E402
from media_manglers_workbench import settings as workbench_settings  # noqa: E402

STOPPED_RUN_KEY = "bug_report_stopped_run"


class ContinueTests(unittest.TestCase):
    setUpClass = classmethod(base.BugReportsPageTests.setUpClass.__func__)
    setUp = base.BugReportsPageTests.setUp
    tearDown = base.BugReportsPageTests.tearDown
    _window = base.BugReportsPageTests._window
    _wait_for_results = base.BugReportsPageTests._wait_for_results

    def _stop_a_run(self, *, track_for_b: int | None = None):
        window = self._window()
        window.runner_factory = control.StoppedBackend
        page = window.bug_reports_page
        page.add_recordings([self.recordings / "a.mkv", self.recordings / "b.mkv"])
        if track_for_b:
            page._set_override(1, track_for_b)
        page.start()
        folder = page.run_folder
        folder.mkdir(parents=True, exist_ok=True)
        self._wait_for_results(page)
        self.assertEqual(page.start_button.text(), "Continue")
        return window, page, folder

    def _restart(self):
        self.window._closing_after_smoke = True
        self.window.close()
        self.app.processEvents()
        # The settings file is written afresh: whatever Continue needs must come from the library.
        return self._window()

    def test_a_stopped_run_continues_after_a_restart_into_the_same_folder(self) -> None:
        window, page, folder = self._stop_a_run(track_for_b=3)
        window.save_app_settings()
        self.assertNotIn(STOPPED_RUN_KEY, json.loads((self.root / "settings.json").read_text(encoding="utf-8"))["settings"])
        self.assertNotIn(STOPPED_RUN_KEY, window.app_settings)

        window = self._restart()
        page = window.bug_reports_page
        self.assertEqual(page.continue_folder, folder)
        self.assertEqual(page.start_button.text(), "Continue")
        self.assertEqual([row.path.name for row in page.rows], ["a.mkv", "b.mkv"])
        self.assertEqual([row.track_override for row in page.rows], [None, 3], "the track you chose comes back")
        page.start()
        self._wait_for_results(page)
        argv = base.ScriptedBackend.instances[-1].argv
        self.assertEqual(Path(argv[argv.index("-OutputFolder") + 1]), folder)
        self.assertIsNone(page.continue_folder)
        self.assertIsNone(window.records.stopped_bug_run(), "a run that started forgets the stopped one")

    def test_continue_leaves_out_a_recording_marked_never_use_since(self) -> None:
        window, _page, folder = self._stop_a_run()
        # Marked from the built-in player after the run stopped; the kept record still names it.
        window.records.set_never_use((self.recordings / "b.mkv").resolve(), True, by="Built-in player")
        window = self._restart()
        page = window.bug_reports_page
        self.assertEqual(page.continue_folder, folder)
        self.assertEqual([row.path.name for row in page.rows], ["a.mkv"])

    def test_start_a_new_package_instead_and_start_over_forget_the_stopped_run(self) -> None:
        window, page, _folder = self._stop_a_run()
        page.start_fresh_button.click()
        self.assertIsNone(page.continue_folder)
        self.assertIsNone(window.records.stopped_bug_run())
        window = self._restart()
        self.assertIsNone(window.bug_reports_page.continue_folder)
        self.assertEqual(window.bug_reports_page.start_button.text(), "Find bug reports")

    def test_a_stopped_run_whose_folder_is_gone_is_forgotten(self) -> None:
        window, _page, folder = self._stop_a_run()
        folder.rename(folder.with_name(folder.name + "-moved"))
        window = self._restart()
        self.assertIsNone(window.bug_reports_page.continue_folder)
        self.assertIsNone(window.records.stopped_bug_run())


class StoppedRunStaysOnThisPcTests(unittest.TestCase):
    setUpClass = classmethod(base.BugReportsPageTests.setUpClass.__func__)
    setUp = base.BugReportsPageTests.setUp
    tearDown = base.BugReportsPageTests.tearDown
    _window = base.BugReportsPageTests._window

    STRAY = {"folder": "Q:\\Private Output\\bug-reports\\2026-10-01_10-00-00",
             "recordings": ["Q:\\Captured Sessions\\synthetic-private.mkv"], "tracks": {}}

    def test_save_profile_as_never_copies_a_stopped_run_into_the_profile(self) -> None:
        window = self._window()
        # What an older settings.json put into the window's run settings at start-up.
        window.run_settings[STOPPED_RUN_KEY] = dict(self.STRAY)
        with patch.object(QInputDialog, "getText", return_value=("Synthetic preset", True)):
            window.save_profile_as()
        saved = json.loads(window.profile_manager.profile_path("Synthetic preset").read_text(encoding="utf-8"))
        self.assertNotIn(STOPPED_RUN_KEY, saved["settings"])
        self.assertNotIn("synthetic-private", json.dumps(saved))

    def test_applying_a_profile_that_holds_one_never_brings_it_back(self) -> None:
        window = self._window()
        path = window.profile_manager.profile_path("Old preset")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schemaVersion": 1, "profileName": "Old preset", "profileType": "custom",
                                    "workflow": window.current_workflow,
                                    "settings": {STOPPED_RUN_KEY: dict(self.STRAY)}}), encoding="utf-8")
        self.assertTrue(window.apply_profile("Old preset", force=True))
        # Every this-PC key keeps what the window had (here: nothing), never the profile's copy.
        self.assertFalse(window.run_settings.get(STOPPED_RUN_KEY))

    def test_a_settings_export_never_carries_a_stopped_run(self) -> None:
        window = self._window()
        settings = dict(window.app_settings)
        settings[STOPPED_RUN_KEY] = dict(self.STRAY)
        bundle = self.root / "bundle.json"
        workbench_settings.export_settings_bundle(bundle, settings, window.profile_manager, include_machine_paths=True)
        self.assertNotIn("synthetic-private", bundle.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
