"""What the library keeps stays where it belongs (242, Wave A1.6).

Every table has a privacy class. Run history is personal: it is never in the raw bin's CSV/JSON export,
never in a settings bundle, never read by code that makes a package or prompt for an outside agent, and
the move out of settings.json logs counts only. The raw bin's export keeps exactly the columns it always
had.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from media_manglers.core import raw_bin_library, recording_records  # noqa: E402
from media_manglers_workbench import settings as workbench_settings  # noqa: E402
from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: E402
from tests.test_workbench_review_media_inbox import _ready_resources  # noqa: E402

SOURCE = Path(__file__).resolve().parents[1] / "src"
# The only modules that read the library: the front door, its scan engine, and the Workbench's own pages
# and run service. Nothing that makes a package, a prompt or a brief for an outside agent.
LIBRARY_READERS = {
    "media_manglers/core/recording_records.py",
    "media_manglers/core/raw_bin_library.py",
    "media_manglers/core/track_levels.py",
    "media_manglers_workbench/app.py",
    "media_manglers_workbench/raw_bin_page.py",
    "media_manglers_workbench/ai_video_editor.py",
    "media_manglers_workbench/ai_video_editor_parts.py",
    "media_manglers_workbench/bug_reports.py",
    "media_manglers_workbench/run_outcomes.py",
    # 224 (Wave B2b): the Inbox's records live in the library. Its store opens them (and reads the move's
    # receipt), the one-time move writes them, and the command-line relocation tool moves their folder. None of
    # them makes anything for the outside agent; the modules that build its packages never name the library.
    "media_manglers/core/inbox_records.py",
    "media_manglers/core/inbox_move.py",
    "media_manglers/core/review_relocation.py",
    # 264 (Wave C1): speech facts are personal, and this module keeps them. What it hands other modules for the
    # outside agent's features (the Inbox, the AI Video Editor) is a track number, never moments.
    "media_manglers/core/speech_facts.py",
    # 242 (Wave C2): the AI Video Editor's core asks the library which recording a file is (its content hash, a
    # private fact the design keeps in project.json) and keeps the editor's index. Only the calls in
    # EDITOR_LIBRARY_CALLS, never a personal table: the test below holds them to that.
    "media_manglers/core/race_video/project.py",
    "media_manglers/core/race_video/library.py",
    "media_manglers/core/race_video/link.py",
    "media_manglers/core/race_video/requests.py",
}
EDITOR_LIBRARY_CALLS = {"current_copy", "connect", "connect_read_only", "copy_at", "copies_like",
                        "index_editor_projects", "LINK_BOUND", "LINK_UNBOUND"}
# The only modules that may ask for moments (where a recording's speech is): the player's jobs and the facts themselves.
MOMENTS_READERS = {
    "media_manglers/core/speech_facts.py",
    "media_manglers/core/track_levels.py",
    "media_manglers_workbench/app.py",
    "media_manglers_workbench/levels_service.py",
}
PRIVATE_RUN = {
    "timestamp": "2026-10-01 10:00", "workflow": "3", "workflow_title": "Find my bug reports",
    "profile": "", "source": "C:\\Private Recordings\\secret-session.mkv", "output": "C:\\Private Output\\run",
    "log": "C:\\Private Logs\\run.log", "status": "succeeded",
}


class PrivacyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="records-privacy-"))

    def test_every_table_of_the_library_has_a_privacy_class(self) -> None:
        recording_records.connect(self.root / "library", backup=False).close()
        connection = sqlite3.connect(str(self.root / "library" / "raw-bin-library.sqlite"))
        try:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}
        finally:
            connection.close()
        self.assertEqual(tables - set(recording_records.TABLE_PRIVACY), set())

    def test_the_raw_bin_export_has_its_columns_and_no_run_history(self) -> None:
        self.assertEqual(raw_bin_library.EXPORT_FIELDS, [
            "name", "path", "missing", "guess", "guess_reason", "minutes_of_speech", "idle_share", "idle_minutes",
            "idle_note", "decision", "labels", "reviewed_by_inbox", "flag_count", "duration_minutes", "size_gb",
            "audio_tracks", "narration_track", "game_track", "first_seen_utc", "scanned_utc", "content_sha256"])
        # What the export writes comes from list_recordings, which reads the recordings, their places and
        # labels only: none of the personal tables.
        import inspect  # noqa: PLC0415

        source = inspect.getsource(raw_bin_library.list_recordings)
        for table, privacy in recording_records.TABLE_PRIVACY.items():
            if privacy == recording_records.PERSONAL:
                with self.subTest(table=table):
                    self.assertIsNone(re.search(rf"\b(?:FROM|JOIN)\s+{table}\b", source), table)
        records = recording_records.Records(self.root / "library")
        try:
            records.import_legacy_runs([PRIVATE_RUN])
            rows = recording_records.list_recordings(root=self.root / "library")
        finally:
            records.close()
        written = raw_bin_library.export(rows, self.root / "export.json")
        self.assertNotIn("secret-session", written.read_text(encoding="utf-8"))

    def test_no_code_that_makes_something_for_an_outside_agent_reads_the_library(self) -> None:
        reading = {path.relative_to(SOURCE).as_posix() for path in SOURCE.rglob("*.py")
                   if re.search(r"\brecording_records\b", path.read_text(encoding="utf-8"))}
        self.assertEqual(reading - LIBRARY_READERS, set())

    def test_the_editor_asks_the_library_only_which_recording_a_file_is(self) -> None:
        for name in ("project", "library", "link", "requests"):
            text = (SOURCE / "media_manglers" / "core" / "race_video" / f"{name}.py").read_text(encoding="utf-8")
            with self.subTest(module=name):
                used = set(re.findall(r"\brecording_records\.(\w+)", text))
                self.assertEqual(used - EDITOR_LIBRARY_CALLS, set())

    def test_nothing_made_for_an_outside_agent_can_ask_for_where_the_operator_spoke(self) -> None:
        asking = {path.relative_to(SOURCE).as_posix() for path in SOURCE.rglob("*.py")
                  if re.search(r"\b(?:known_measure|jump_points)\(", path.read_text(encoding="utf-8"))}
        self.assertEqual(asking - MOMENTS_READERS, set())


class WorkbenchPrivacyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_the_move_logs_counts_only_and_a_settings_bundle_never_carries_run_history(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="records-privacy-window-"))
        settings = root / "settings.json"
        settings.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
            "log_folder": str(root / "logs"), "temp_folder": str(root / "temp"), "output_folder": str(root / "out"),
            "recent_runs": [PRIVATE_RUN]}}), encoding="utf-8")
        window = WorkbenchWindow(settings_path=settings, profiles_dir=root / "profiles", resources=_ready_resources())
        try:
            log = Path(window.run_log_path).read_text(encoding="utf-8")
            self.assertIn("Run history moved out of settings.json: moved; read 1, added 1", log)
            self.assertNotIn("secret-session", log)
            bundle = root / "bundle.json"
            workbench_settings.export_settings_bundle(bundle, window.app_settings, window.profile_manager,
                                                      include_machine_paths=True)
            self.assertNotIn("secret-session", bundle.read_text(encoding="utf-8"))
            self.assertEqual(window.recent_runs()[0]["source"], PRIVATE_RUN["source"], "History still shows it")
        finally:
            window._closing_after_smoke = True
            window.close()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
