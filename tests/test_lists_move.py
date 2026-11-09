"""Find my bug reports' lists and stopped run move out of settings.json once (244, Wave A2.5).

The never-use list, the already-done map and the stopped run move into the library with a backup first:
settings.json byte for byte, every custom profile, and the library. An old never-use entry has no date and
no bytes to prove anything, so it stays an old entry, matched by its path exactly as before. An old done
entry keeps its date with an unknown outcome, and is tied to a recording only when the library proves the
same bytes were at that path on that day; otherwise it stays an old entry, never given to whatever file is
there now and never shared with an identical copy. The keys are then taken out of settings.json and the
stray copies out of custom profiles; built-in profiles are never touched. Moving twice adds nothing, and a
mark cleared since is never brought back; entries an older build writes later move in at the next start.
"""

from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from media_manglers.core import recording_records  # noqa: E402
from media_manglers.core.recording_records import Records, import_legacy_settings  # noqa: E402
from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: E402
from tests.test_recording_marks import store_copy, write_recording  # noqa: E402
from tests.test_workbench_review_media_inbox import _ready_resources  # noqa: E402

NEVER = "bug_report_excluded_recordings"
DONE = "bug_report_processed_recordings"
STOPPED = "bug_report_stopped_run"
TODAY = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


def write_settings(path: Path, settings: dict) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": settings}, indent=2) + "\n").encode()
    path.write_bytes(data)
    return data


def write_profile(folder: Path, name: str, settings: dict, *, kind: str = "custom") -> bytes:
    folder.mkdir(parents=True, exist_ok=True)
    data = json.dumps({"schemaVersion": 2, "profileName": name, "profileType": kind, "workflow": "3",
                       "settings": settings}, indent=2).encode()
    (folder / f"{name}.json").write_bytes(data)
    return data


class _MoveCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = self.root / "Roaming" / "settings.json"
        self.profiles = self.root / "Roaming" / "profiles"
        self.records = Records(self.root / "library")
        self.others = {"output_folder": "C:\\Output", "whisper_model": "medium", "input_path": "Q:\\Inbox"}

    def tearDown(self) -> None:
        self.records.close()
        self.temp.cleanup()

    def _move(self) -> dict:
        return import_legacy_settings(self.records, self.settings, self.profiles)

    def _saved(self) -> dict:
        return json.loads(self.settings.read_text(encoding="utf-8"))["settings"]

    def _profiles_held(self):
        """Every write into the profiles folder fails, as when another program holds the file."""

        from media_manglers.core import safe_write  # noqa: PLC0415

        real = safe_write.write_json

        def held(path, data):
            if Path(path).parent == self.profiles:
                raise PermissionError(13, "in use")
            return real(path, data)

        return mock.patch.object(safe_write, "write_json", side_effect=held)


class MoveTests(_MoveCase):
    def test_the_lists_and_the_stopped_run_move_in_once_with_a_backup_first(self) -> None:
        stopped = {"folder": str(self.root / "out" / "bug-reports" / "2026-10-01_10-00-00"),
                   "recordings": ["Q:\\Captured\\one.mkv", "Q:\\Captured\\Two.MKV"], "tracks": {"Q:\\Captured\\Two.MKV": 3}}
        original = write_settings(self.settings, {**self.others, NEVER: ["Q:\\Captured\\never.mkv"],
                                                  DONE: {"Q:\\Captured\\done-1.mkv": "2026-09-01",
                                                         "Q:\\Captured\\done-2.mkv": "2026-09-02"},
                                                  STOPPED: stopped})
        custom = write_profile(self.profiles, "My preset", {"whisper_model": "large", STOPPED: stopped, NEVER: [],
                                                            DONE: {}, "recent_runs": [{"source": "Q:\\x.mkv"}]})
        builtin = write_profile(self.profiles, "Built-in preset", {"whisper_model": "small", NEVER: [], DONE: {}},
                                kind="built-in")

        result = self._move()

        self.assertEqual(result["status"], "moved")
        counts = result["counts"]
        self.assertEqual(counts[NEVER], {"read": 1, "added": 1, "already": 0})
        self.assertEqual(counts[DONE], {"read": 2, "added": 2, "already": 0, "tied_to_a_recording": 0, "old_list": 2})
        self.assertEqual(counts[STOPPED], {"read": 1, "added": 1, "already": 0, "ignored": 0})
        self.assertEqual(counts["profiles"], {"custom": 1, "with_strays": 1, "cleaned": 1, "left": 0})
        # The backup: settings.json and the custom profile byte for byte, the library as it was.
        backup = Path(result["backup_folder"])
        self.assertEqual((backup / "settings.json").read_bytes(), original)
        self.assertEqual((backup / "profiles" / "My preset.json").read_bytes(), custom)
        manifest = json.loads((backup / "BACKUP_MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["profiles/My preset.json"], hashlib.sha256(custom).hexdigest())
        copy = sqlite3.connect(f"{(backup / 'raw-bin-library.sqlite').as_uri()}?mode=ro", uri=True)
        try:
            self.assertEqual(copy.execute("SELECT COUNT(*) FROM marks").fetchone()[0], 0)
        finally:
            copy.close()
        self.assertIn("profiles", (backup / "HOW_TO_RESTORE.txt").read_text(encoding="utf-8"))
        # settings.json keeps everything else; the profiles keep everything else; built-in is untouched.
        self.assertEqual(self._saved(), self.others)
        profile = json.loads((self.profiles / "My preset.json").read_text(encoding="utf-8"))
        self.assertEqual(profile["settings"], {"whisper_model": "large"})
        self.assertEqual(profile["profileName"], "My preset")
        self.assertEqual((self.profiles / "Built-in preset.json").read_bytes(), builtin)
        # The library answers what settings.json answered.
        self.assertEqual(self.records.never_use_keys() & {"q:\\captured\\never.mkv"}, {"q:\\captured\\never.mkv"})
        self.assertEqual(self.records.never_use_entries()[0]["path"], "Q:\\Captured\\never.mkv")
        dates = self.records.done_dates()
        self.assertEqual((dates["q:\\captured\\done-1.mkv"], dates["q:\\captured\\done-2.mkv"]),
                         ("2026-09-01", "2026-09-02"))
        self.assertEqual(self.records.stopped_bug_run(), stopped)
        receipt = self.records.connection().execute("SELECT status, counts_json FROM legacy_imports").fetchall()
        self.assertEqual([row[0] for row in receipt], ["complete"])

    def test_moving_twice_adds_nothing_and_a_mark_cleared_since_never_comes_back(self) -> None:
        lists = {NEVER: ["Q:\\Captured\\never.mkv", "Q:\\Captured\\other.mkv"], DONE: {"Q:\\Captured\\d.mkv": "2026-09-01"}}
        write_settings(self.settings, {**self.others, **lists})
        self._move()
        self.assertTrue(self.records.set_never_use("Q:\\Captured\\never.mkv", False, by="Find Bug Reports"))
        # An older build used afterwards writes its lists back into settings.json, with one new entry.
        write_settings(self.settings, {**self.others, NEVER: [*lists[NEVER], "Q:\\Captured\\new.mkv"],
                                       DONE: {**lists[DONE], "Q:\\Captured\\new-done.mkv": "2026-10-20"}})
        result = self._move()
        self.assertEqual(result["counts"][NEVER], {"read": 3, "added": 1, "already": 2})
        self.assertEqual(result["counts"][DONE]["added"], 1)
        keys = self.records.never_use_keys()
        self.assertNotIn("q:\\captured\\never.mkv", keys, "allowed again stays allowed")
        self.assertIn("q:\\captured\\new.mkv", keys)
        self.assertEqual(self.records.done_dates()["q:\\captured\\new-done.mkv"], "2026-10-20")
        self.assertEqual(self._move()["status"], "nothing")

    def test_an_old_done_entry_is_tied_to_a_recording_only_when_the_library_proves_it(self) -> None:
        watched = self.root / "watched"
        proven = write_recording(watched / "proven.mkv", seed=1)
        too_new = write_recording(watched / "first-seen-later.mkv", seed=2)
        touched = write_recording(watched / "changed-since.mkv", seed=3)
        twin = write_recording(self.root / "backup" / "proven-copy.mkv", seed=1)
        twin_of_too_new = write_recording(self.root / "backup" / "later-copy.mkv", seed=2)
        for path in (proven, too_new, touched):
            store_copy(self.records, path, watched)
        store_copy(self.records, twin, self.root / "backup")
        store_copy(self.records, twin_of_too_new, self.root / "backup")
        os.utime(touched, ns=(touched.stat().st_atime_ns, touched.stat().st_mtime_ns + 5_000_000_000))
        write_settings(self.settings, {**self.others, DONE: {
            str(proven): TODAY, str(too_new): YESTERDAY, str(touched): TODAY, "Q:\\Gone\\not-known.mkv": TODAY}})

        counts = self._move()["counts"][DONE]

        self.assertEqual((counts["tied_to_a_recording"], counts["old_list"]), (1, 3))
        dates = self.records.done_dates()
        self.assertEqual(dates[str(twin).lower()], TODAY, "a proven entry is shared with the identical copy")
        self.assertNotIn(str(twin_of_too_new).lower(), dates, "an old entry is never shared")
        # Every old entry still works by its path, exactly as before.
        for path, day in ((proven, TODAY), (too_new, YESTERDAY), (touched, TODAY)):
            self.assertEqual(dates[str(path).lower()], day)
        self.assertEqual(dates["q:\\gone\\not-known.mkv"], TODAY)
        mined = {Path(row["path"]).name: row["mined"] for row in self.records.list_recordings()}
        self.assertEqual(mined["proven.mkv"], "Bugs")
        self.assertEqual(mined["proven-copy.mkv"], "Bugs")
        self.assertEqual(mined["first-seen-later.mkv"], "Bugs (old list)")
        self.assertEqual(mined["changed-since.mkv"], "Bugs (old list)")
        self.assertEqual(mined["later-copy.mkv"], "")

    def test_an_old_never_use_entry_works_by_its_path_exactly_as_before(self) -> None:
        watched = self.root / "watched"
        here = write_recording(watched / "Never Again.mkv", seed=5)
        twin = write_recording(self.root / "backup" / "never-again-copy.mkv", seed=5)
        store_copy(self.records, here, watched)
        store_copy(self.records, twin, self.root / "backup")
        write_settings(self.settings, {**self.others, NEVER: [str(here).upper()]})
        self._move()
        keys = self.records.never_use_keys()
        self.assertIn(str(here).lower(), keys)
        self.assertNotIn(str(twin).lower(), keys)
        self.assertEqual([entry["path"] for entry in self.records.never_use_entries()], [str(here).upper()])
        self.assertTrue(self.records.set_never_use(here, False, by="Find Bug Reports"))
        self.assertEqual(self.records.never_use_keys(), set())

    def test_empty_lists_an_older_build_saved_are_taken_out(self) -> None:
        write_settings(self.settings, {**self.others, NEVER: [], DONE: {}})
        self.assertEqual(self._move()["status"], "moved")
        self.assertEqual(self._saved(), self.others)

    def test_a_move_that_does_not_check_out_changes_nothing_and_is_tried_again(self) -> None:
        original = write_settings(self.settings, {**self.others, NEVER: ["Q:\\Captured\\never.mkv"],
                                                  STOPPED: {"folder": "Q:\\Out\\run", "recordings": [], "tracks": {}}})
        custom = write_profile(self.profiles, "My preset", {STOPPED: {"folder": "Q:\\Out\\run"}})
        with mock.patch.object(recording_records, "_check_move", return_value=["a count did not add up"]):
            result = self._move()
        self.assertEqual(result["status"], "restored")
        self.assertEqual(self.settings.read_bytes(), original)
        self.assertEqual((self.profiles / "My preset.json").read_bytes(), custom)
        self.assertEqual(self.records.never_use_keys(), set())
        self.assertIsNone(self.records.stopped_bug_run())
        self.assertEqual(self._move()["status"], "moved")
        self.assertIn("q:\\captured\\never.mkv", self.records.never_use_keys())

    def test_a_broken_settings_file_is_refused_and_nothing_else_is_touched(self) -> None:
        self.settings.parent.mkdir(parents=True)
        self.settings.write_bytes(b'{"settings": {"bug_report_excluded_recordings": [ not json')
        custom = write_profile(self.profiles, "My preset", {STOPPED: {"folder": "Q:\\Out\\run"}})
        result = self._move()
        self.assertEqual(result["status"], "refused")
        self.assertEqual((self.profiles / "My preset.json").read_bytes(), custom)
        self.assertEqual(self.records.never_use_keys(), set())

    def test_a_profile_that_cannot_be_written_now_is_cleaned_at_the_next_start(self) -> None:
        write_settings(self.settings, {**self.others, NEVER: ["Q:\\Captured\\never.mkv"]})
        write_profile(self.profiles, "My preset", {"whisper_model": "large", STOPPED: {"folder": "Q:\\Out\\run"}})
        with self._profiles_held():
            first = self._move()
        self.assertEqual(first["status"], "imported")
        self.assertEqual(first["counts"]["profiles"]["left"], 1)
        second = self._move()
        self.assertEqual(second["status"], "nothing", "settings.json has nothing left to move")
        self.assertEqual(second["counts"]["profiles"]["cleaned"], 1)
        profile = json.loads((self.profiles / "My preset.json").read_text(encoding="utf-8"))
        self.assertEqual(profile["settings"], {"whisper_model": "large"})

    def test_a_profile_that_stays_unwritable_is_not_backed_up_again_at_every_start(self) -> None:
        write_settings(self.settings, {**self.others, NEVER: ["Q:\\Captured\\never.mkv"]})
        write_profile(self.profiles, "My preset", {"whisper_model": "large", STOPPED: {"folder": "Q:\\Out\\run"}})
        backups = self.root / "library" / "backups" / "migrations"
        with self._profiles_held():
            results = [self._move() for _start in range(3)]
        self.assertEqual([result["status"] for result in results], ["imported", "nothing", "nothing"])
        self.assertEqual([result["counts"]["profiles"]["left"] for result in results], [1, 1, 1])
        self.assertEqual(len(list(backups.glob("*/raw-bin-library.sqlite"))), 1,
                         "the library is copied once, not at every start")
        self.assertEqual(len(list(backups.glob("*/profiles/My preset.json"))), 1,
                         "the profile as it is now was backed up once")

    def test_a_stray_copy_in_a_profile_alone_backs_up_that_profile_only(self) -> None:
        settings = write_settings(self.settings, self.others)
        custom = write_profile(self.profiles, "My preset", {"whisper_model": "large", STOPPED: {"folder": "Q:\\Out\\run"}})
        write_profile(self.profiles, "Tidy preset", {"whisper_model": "small"})
        result = self._move()
        self.assertEqual(result["status"], "nothing", "settings.json has nothing to move")
        self.assertEqual(result["counts"]["profiles"], {"custom": 2, "with_strays": 1, "cleaned": 1, "left": 0})
        folder = Path(result["backup_folder"])
        self.assertEqual(sorted(item.relative_to(folder).as_posix() for item in folder.rglob("*") if item.is_file()),
                         ["BACKUP_MANIFEST.json", "HOW_TO_RESTORE.txt", "profiles/My preset.json"])
        self.assertEqual((folder / "profiles" / "My preset.json").read_bytes(), custom)
        manifest = json.loads((folder / "BACKUP_MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["profiles/My preset.json"], hashlib.sha256(custom).hexdigest())
        self.assertEqual(self.settings.read_bytes(), settings, "settings.json is not touched")
        profile = json.loads((self.profiles / "My preset.json").read_text(encoding="utf-8"))
        self.assertEqual(profile["settings"], {"whisper_model": "large"})
        self.assertEqual(self._move(), {"status": "nothing", "counts": {}})


class WorkbenchListsMoveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_the_workbench_moves_the_lists_when_it_starts_and_logs_counts_only(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="lists-move-window-"))
        settings = root / "settings.json"
        write_settings(settings, {"log_folder": str(root / "logs"), "temp_folder": str(root / "temp"),
                                  "output_folder": str(root / "out"),
                                  NEVER: ["Q:\\Private Recordings\\secret-never.mkv", "Q:\\Private Recordings\\b.mkv"],
                                  DONE: {"Q:\\Private Recordings\\secret-done.mkv": "2026-09-01"}})
        window = WorkbenchWindow(settings_path=settings, profiles_dir=root / "profiles", resources=_ready_resources())
        try:
            self.assertTrue(window.lists_in_library())
            for key in (NEVER, DONE, STOPPED):
                self.assertNotIn(key, window.app_settings)
            self.assertEqual(window.bug_reports_page.excluded_button.text(), "Never-use list (2)…")
            log = Path(window.run_log_path).read_text(encoding="utf-8")
            self.assertIn("Find my bug reports' lists moved out of settings.json: moved; never-use read 2, added 2", log)
            self.assertNotIn("secret", log)
            window.save_app_settings()
            saved = json.loads(settings.read_text(encoding="utf-8"))["settings"]
            for key in (NEVER, DONE, STOPPED):
                self.assertNotIn(key, saved)
        finally:
            window._closing_after_smoke = True
            window.close()
            self.app.processEvents()

    def test_a_stray_copy_in_a_profile_alone_is_taken_out_at_start_and_logged_as_counts(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="lists-move-window-"))
        settings = root / "settings.json"
        write_settings(settings, {"log_folder": str(root / "logs"), "temp_folder": str(root / "temp"),
                                  "output_folder": str(root / "out")})
        write_profile(root / "profiles", "My preset", {"whisper_model": "large",
                                                       STOPPED: {"folder": "Q:\\Private Output\\secret-run"}})
        window = WorkbenchWindow(settings_path=settings, profiles_dir=root / "profiles", resources=_ready_resources())
        try:
            self.assertTrue(window.lists_in_library())
            log = Path(window.run_log_path).read_text(encoding="utf-8")
            self.assertIn("Stray copies of Find my bug reports' lists taken out of custom profiles: cleaned 1 of 1.", log)
            self.assertNotIn("moved out of settings.json", log, "settings.json had nothing to move")
            self.assertNotIn("secret", log)
            profile = json.loads((root / "profiles" / "My preset.json").read_text(encoding="utf-8"))
            self.assertEqual(profile["settings"], {"whisper_model": "large"})
        finally:
            window._closing_after_smoke = True
            window.close()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
