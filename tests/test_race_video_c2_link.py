"""242 (Wave C2, audit H6 and M2): the AI Video Editor's projects are bound to their recording's content.

Real recordings made with FFmpeg, the real Prepare, add-version, render, export and analyze commands, the real
library (``MEDIA_MANGLERS_LIBRARY_ROOT``, set by tests/conftest.py to a folder of the run's own) and real clicks
on the page. Two recordings share a file name and differ in content only.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core import recording_identity, recording_records  # noqa: E402
from media_manglers.core.race_video import analysis as analysis_module  # noqa: E402
from media_manglers.core.race_video import link  # noqa: E402
from media_manglers.core.race_video import requests as race_requests  # noqa: E402
from media_manglers.core.race_video.library import export_version, reconcile, start_fresh_edit  # noqa: E402
from media_manglers.core.race_video.library import list_projects  # noqa: E402
from media_manglers.core.race_video.project import (  # noqa: E402
    add_version,
    create_project,
    read_json,
    version_dir,
)
from media_manglers.core.race_video.render import RenderOptions, render_version  # noqa: E402
from tests.test_race_video_recording_authority import FFMPEG, FFPROBE, LAYOUT, make_recording, timeline  # noqa: E402


def _quiet(call, *args, **kwargs):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = call(*args, **kwargs)
    return result, out.getvalue()


def _seed_library(path: Path) -> str:
    """The library, as a raw bin scan leaves it, holding the file at ``path`` (its hashes, size and time)."""

    sampled, content = recording_identity.file_identity(path)
    stat = path.stat()
    connection = recording_records.connect(backup=False)
    try:
        with connection:
            now = "2026-11-06T00:00:00Z"
            recording_id = int(connection.execute(
                "INSERT INTO recordings(first_seen_utc, size_bytes) VALUES (?, ?)", (now, stat.st_size)).lastrowid)
            connection.execute("UPDATE recordings SET content_sha256 = ?, sampled_sha256 = ? WHERE recording_id = ?",
                               (content, sampled, recording_id))
            connection.execute(
                "INSERT INTO locations(recording_id, path, path_key, root_key, size_bytes, modified_ns, is_current, "
                "missing, first_seen_utc, last_seen_utc, registered_by) VALUES (?, ?, ?, '', ?, ?, 1, 0, ?, ?, 'scan')",
                (recording_id, str(path), recording_records.path_key(path), stat.st_size, stat.st_mtime_ns, now, now))
    finally:
        connection.close()
    return content


def _index_rows() -> list[tuple]:
    connection = recording_records.connect(backup=False)
    try:
        projects = [tuple(row) for row in connection.execute("SELECT * FROM editor_projects ORDER BY project_id")]
        versions = [tuple(row) for row in connection.execute("SELECT * FROM editor_versions ORDER BY project_id, version")]
    finally:
        connection.close()
    return projects + versions


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class EditorLinkTests(unittest.TestCase):
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

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _copy(self, name: str = "race.mkv", folder: str = "work") -> Path:
        """A copy of the recording with a modified time of its own (a whole minute apart from every other copy), so
        only the copy itself has its size and time."""

        path = self.root / folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.recording, path)
        self.copies = getattr(self, "copies", 0) + 1
        moment = (1_700_000_000 + 60 * self.copies) * 1_000_000_000
        os.utime(path, ns=(moment, moment))
        return path

    def _prepare(self, source: Path) -> tuple[Path, str]:
        result, said = _quiet(race_requests.prepare_from_request, {
            "source": str(source), "output_root": str(self.out), "budget": "light", "layout": LAYOUT,
            "skip_transcript": True, "track_roles": "", "tracks": {"voice": 0, "game": 1}, "ffmpeg": FFMPEG,
            "ffprobe": FFPROBE, "progress_label": source.name})
        return Path(result["project"]), said

    def _version(self, project: Path, source: Path) -> int:
        return add_version(project, timeline(source), source_duration=12.0, audio_streams=2)

    # C2.1: binding at Prepare --------------------------------------------------------------------------------

    def test_prepare_binds_a_new_video_and_says_it_is_confirming_the_recording(self) -> None:
        source = self._copy()
        project, said = self._prepare(source)
        bound = read_json(project / "project.json")["recording"]
        self.assertEqual(bound["content_sha256"], recording_identity.file_identity(source)[1])
        self.assertEqual(bound["bound_how"], "read at Prepare")
        self.assertEqual((bound["size"], bound["modified_ns"]), (source.stat().st_size, source.stat().st_mtime_ns))
        steps = [json.loads(line.split(" ", 1)[1]) for line in said.splitlines() if line.startswith("MM_PROGRESS_V1 ")]
        confirming = [step for step in steps if step["phase"] == "Confirming which recording this is"]
        self.assertTrue(confirming, "the extra step is said on Queue / Progress")
        self.assertEqual({step["phase_count"] for step in steps}, {6})
        self.assertEqual(confirming[0]["phase_index"], 1, "it comes before anything else")

    def test_prepare_reads_nothing_more_when_the_library_has_read_the_file(self) -> None:
        source = self._copy()
        content = _seed_library(source)
        project, said = self._prepare(source)
        bound = read_json(project / "project.json")["recording"]
        self.assertEqual((bound["content_sha256"], bound["bound_how"]), (content, "from the library"))
        self.assertNotIn("Confirming which recording this is", said)

    # C2.2: the claim check and the hash-based checks --------------------------------------------------------------

    def test_a_same_named_other_file_is_refused_at_add_version_render_export_and_analyze(self) -> None:
        project, _said = self._prepare(self.recording)
        with self.assertRaisesRegex(ValueError, "different recording with the same file name"):
            race_requests.add_version_from_request({"project": str(project), "timeline": timeline(self.other),
                                                    "ffprobe": FFPROBE})
        number = self._version(project, self.recording)
        stored = version_dir(project, number) / "timeline.json"
        data = json.loads(stored.read_text(encoding="utf-8"))
        stored.write_text(json.dumps(dict(data, source=str(self.other))), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "different recording"):
            render_version(project, number, "preview", self.options)
        with self.assertRaisesRegex(ValueError, "different recording"):
            export_version(project, number, self.options)
        analysis_before = (project / "analysis" / "analysis.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "different recording with the same file name"):
            _quiet(race_requests.analyze_from_request, {"project": str(project), "source": str(self.other),
                                                        "budget": "light", "ffmpeg": FFMPEG, "ffprobe": FFPROBE})
        self.assertEqual((project / "analysis" / "analysis.json").read_bytes(), analysis_before)

    def test_analyze_builds_from_the_project_s_own_recording(self) -> None:
        project, _said = self._prepare(self.recording)
        copy = self._copy("copy.mkv")
        _quiet(race_requests.analyze_from_request, {"project": str(project), "source": str(copy), "budget": "standard",
                                                    "ffmpeg": FFMPEG, "ffprobe": FFPROBE})
        self.assertEqual(read_json(project / "analysis" / "analysis.json")["source"], str(self.recording))

    def test_a_file_saved_over_a_bound_video_s_recording_is_refused(self) -> None:
        source = self._copy()
        project, _said = self._prepare(source)
        shutil.copyfile(self.other, source)
        with self.assertRaisesRegex(ValueError, "another file was saved in its place"):
            self._version(project, source)
        self.assertEqual(read_json(project / "project.json")["versions"], [])

    def test_a_moved_recording_is_sent_to_be_linked_not_told_to_put_it_back(self) -> None:
        source = self._copy()
        project, _said = self._prepare(source)
        moved = self.root / "moved" / "race.mkv"
        moved.parent.mkdir()
        source.rename(moved)
        with self.assertRaisesRegex(ValueError, r"holds this project's recording.*Link recordings"):
            self._version(project, moved)

    # C2.4: linking -----------------------------------------------------------------------------------------------

    def test_a_renamed_recording_is_linked_and_its_older_versions_still_render(self) -> None:
        source = self._copy()
        project, _said = self._prepare(source)
        number = self._version(project, source)
        renamed = source.with_name("race-renamed.mkv")
        source.rename(renamed)
        original = (project / "project.json").read_bytes()
        found = link.evidence_for(project)
        self.assertEqual((found.verdict, found.target), (link.MOVED, str(renamed)))
        link.link_project(project, Path(found.target))
        meta = read_json(project / "project.json")
        self.assertEqual(meta["source"], str(renamed))
        self.assertEqual([item["source"] for item in meta["source_history"]], [str(source)])
        self.assertEqual((project / "project.json.before-link").read_bytes(), original)
        self.assertEqual(meta["versions"], json.loads(original)["versions"], "no version is touched")
        report = render_version(project, number, "preview", self.options)
        self.assertEqual(report["recording"]["content_sha256"], meta["recording"]["content_sha256"])
        self.assertTrue((version_dir(project, number) / "renders" / "preview.mp4").is_file())

    def test_an_older_video_is_linked_where_it_is_without_rebuilding_its_analysis(self) -> None:
        source = self._copy()
        project = create_project(self.out, source, "race")   # as every video before Wave C2 was made
        _quiet(race_requests.analyze_from_request, {"project": str(project), "source": str(source), "budget": "light",
                                                    "tracks": {"voice": 0, "game": 1}, "layout": LAYOUT,
                                                    "ffmpeg": FFMPEG, "ffprobe": FFPROBE})
        built = (project / "analysis" / "analysis.json").read_bytes()
        self.assertNotIn("content", json.loads(built)["engine"])
        found = link.evidence_for(project)
        self.assertEqual((found.verdict, found.target, found.path_there), (link.CAN_LINK, str(source), True))
        self.assertTrue(found.size_matches and found.time_matches)
        link.link_project(project, source)
        meta = read_json(project / "project.json")
        self.assertEqual(meta["recording"]["bound_how"], "linked by you")
        self.assertNotIn("source_history", meta)
        tracks = {"voice": 0, "game": 1, "voice_decided_by": "override", "game_decided_by": "override"}
        self.assertTrue(analysis_module.analysis_is_current(project, budget="light", tracks=tracks, layout=LAYOUT),
                        "an analysis made before the video was linked still matches while the binding agrees")

    def test_a_file_name_alone_is_never_offered(self) -> None:
        source = self._copy()
        project = create_project(self.out, source, "race")
        source.unlink()
        shutil.copy2(self.other, source)                      # the same name, in the same folder: another recording
        elsewhere = self.root / "elsewhere" / "race.mkv"
        elsewhere.parent.mkdir()
        shutil.copy2(self.other, elsewhere)
        found = link.evidence_for(project)
        self.assertEqual((found.verdict, found.target), (link.NO_EVIDENCE, ""))
        before = (project / "project.json").read_bytes()
        for target in (source, elsewhere):
            with self.assertRaisesRegex(ValueError, "not linked"):
                link.link_project(project, target)
        self.assertEqual((project / "project.json").read_bytes(), before)
        self.assertFalse((project / "project.json.before-link").exists())

    def test_a_dry_run_counts_and_writes_nothing(self) -> None:
        here = create_project(self.out, self._copy("here.mkv"), "here")
        renamed = self._copy("away.mkv")
        away = create_project(self.out, renamed, "away")
        renamed.rename(renamed.with_name("away-renamed.mkv"))
        gone = self._copy("gone.mkv")
        create_project(self.out, gone, "gone")
        gone.unlink()
        before = {path: path.read_bytes() for path in self.out.rglob("*") if path.is_file()}
        counts = link.link_check(self.out)
        self.assertEqual({key: counts[key] for key in ("projects", "can_link", "moved", "no_evidence")},
                         {"projects": 3, "can_link": 1, "moved": 1, "no_evidence": 1})
        self.assertEqual({path: path.read_bytes() for path in self.out.rglob("*") if path.is_file()}, before)
        self.assertTrue(here.is_dir() and away.is_dir())

    # Several edits, and the identity in the recipes ------------------------------------------------------------------

    def test_several_edits_of_one_recording_are_joined_by_content(self) -> None:
        from media_manglers_workbench.ai_video_editor_parts import edits_of, knowledge_words  # noqa: PLC0415

        source = self._copy()
        project, _said = self._prepare(source)
        fresh = start_fresh_edit(project)
        self.assertEqual(read_json(fresh / "project.json")["recording"], read_json(project / "project.json")["recording"])
        renamed = source.with_name("renamed.mkv")
        source.rename(renamed)
        row = {"path": str(renamed), "content_sha256": recording_identity.file_identity(renamed)[1]}
        edits = edits_of(row, list_projects(self.out))
        self.assertEqual(sorted(Path(item["folder"]).name for item in edits), sorted([project.name, fresh.name]))
        self.assertIn("AI Video Editor: 2 edits", knowledge_words(row, edits))

    def test_a_bound_video_s_analysis_and_render_name_its_content(self) -> None:
        project, _said = self._prepare(self.recording)
        content = read_json(project / "project.json")["recording"]["content_sha256"]
        self.assertEqual(read_json(project / "analysis" / "analysis.json")["engine"]["content"], content)
        report = render_version(project, self._version(project, self.recording), "preview", self.options)
        self.assertEqual(report["recording"], {"content_sha256": content})

    # C2.3: the index -----------------------------------------------------------------------------------------------

    def test_a_library_at_structure_six_moves_up_to_seven_with_a_backup_and_keeps_its_rows(self) -> None:
        library = self.root / "library"
        connection = recording_records.connect(library, backup=False)
        with connection:
            connection.execute("INSERT INTO recordings(first_seen_utc, content_sha256) VALUES ('x', 'abc')")
            for table in ("editor_versions", "editor_projects"):
                connection.execute(f"DROP TABLE {table}")
            connection.execute("UPDATE schema_metadata SET value = '6' WHERE key = 'schema_version'")
        connection.close()
        connection = recording_records.connect(library, backup=False)
        try:
            self.assertEqual(recording_records.stored_version(connection), 7)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM recordings").fetchone()[0], 1)
            step = connection.execute("SELECT from_version, to_version, backup_path FROM schema_steps "
                                      "ORDER BY step_id DESC").fetchone()
            for table in ("editor_projects", "editor_versions"):
                with self.subTest(table=table):
                    self.assertTrue(connection.execute(f"PRAGMA table_info({table})").fetchall())
                    self.assertEqual(recording_records.TABLE_PRIVACY[table], recording_records.PRIVATE)
                    self.assertIn(table, recording_records.KEPT_TABLES)
        finally:
            connection.close()
        self.assertEqual((step["from_version"], step["to_version"]), (6, 7))
        self.assertTrue(Path(step["backup_path"]).is_file(), "a whole backup is taken before the step")

    def test_reconcile_twice_changes_nothing_and_a_missing_video_is_unavailable_not_deleted(self) -> None:
        first = create_project(self.out, self.recording, "first")
        self._version(first, self.recording)
        second = create_project(self.out, self.recording, "second")
        connection = recording_records.connect(backup=False)
        try:
            self.assertGreater(reconcile(connection, self.out), 0)
            rows = _index_rows()
            self.assertEqual(reconcile(connection, self.out), 0)
            self.assertEqual(_index_rows(), rows)
            shutil.move(str(first), str(self.root / "put-away"))
            reconcile(connection, self.out)
            index = {Path(item["relative_path"]).name: item for item in recording_records.editor_index(connection)}
        finally:
            connection.close()
        self.assertEqual(index["first"]["link_state"], "unavailable")
        self.assertEqual([version["state"] for version in index["first"]["versions"]], ["unavailable"])
        self.assertEqual(index["second"]["link_state"], "unbound")
        self.assertTrue(second.is_dir())
        self.assertNotIn("put-away", json.dumps(index), "the index keeps no whole path")

    def test_a_lost_refresh_is_repaired_on_the_next_and_an_agent_command_indexes_its_project(self) -> None:
        project, _said = self._prepare(self.recording)
        connection = recording_records.connect(backup=False)
        try:
            reconcile(connection, self.out)
            self._version(project, self.recording)                 # written with no index update at all
            self.assertEqual(recording_records.editor_index(connection)[0]["versions"], [])
            reconcile(connection, self.out)
            self.assertEqual([item["version"] for item in recording_records.editor_index(connection)[0]["versions"]], [1])
            _quiet(race_requests.add_version_from_request, {"project": str(project), "timeline": timeline(self.recording),
                                                            "ffprobe": FFPROBE})
            index = recording_records.editor_index(connection)[0]
        finally:
            connection.close()
        self.assertEqual([item["version"] for item in index["versions"]], [1, 2])
        self.assertEqual((index["link_state"], index["content_sha256"]),
                         ("bound", read_json(project / "project.json")["recording"]["content_sha256"]))


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class LinkDialogClickTests(unittest.TestCase):
    """The page's Link recordings… and its dialog, clicked as the operator does (C2-1)."""

    @classmethod
    def setUpClass(cls) -> None:
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

    def test_an_older_video_is_linked_from_the_dialog_by_clicks(self) -> None:
        from media_manglers_workbench.ai_video_editor import PAGE_NAME  # noqa: PLC0415
        from media_manglers_workbench.app import WorkbenchWindow  # noqa: PLC0415
        from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: PLC0415
        from tests.qt_input import click  # noqa: PLC0415
        from tests.test_workbench_ai_video_editor import CoreRunner, _resources  # noqa: PLC0415

        source = self.root / "work" / "race.mkv"
        source.parent.mkdir()
        shutil.copy2(self.recording, source)
        project = create_project(self.root / "out", source, "race")
        settings = self.root / "settings.json"
        settings.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
            "log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
            "output_folder": str(self.root / "out")}}), encoding="utf-8")
        self.window = WorkbenchWindow(settings_path=settings, profiles_dir=self.root / "profiles",
                                      runner_factory=CoreRunner, resources=_resources())
        self.window.show()
        self.app.processEvents()
        click(self.window.nav_buttons[PAGE_NAME])
        page = self.window.ai_video_editor_page
        self.assertTrue(page.link_button.isVisible())
        self.assertIn("1 video is not linked to its recording yet", page.link_line.text())
        click(page.link_button)
        deadline = time.monotonic() + 30
        while page.link_dialog is None and time.monotonic() < deadline:   # the evidence is looked up off the thread
            self.app.processEvents()
            time.sleep(0.02)
        dialog = page.link_dialog
        self.assertIsNotNone(dialog)
        self.assertTrue(dialog.isVisible())
        self.assertIn("Its recording is where it was.", "\n".join(label.text() for label in dialog.findChildren(type(page.link_line))))
        click(dialog.buttons[0])
        deadline = time.monotonic() + 60
        while dialog.states[0].text() not in ("Linked.",) and not dialog.states[0].text().startswith("Not linked") \
                and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.02)
        self.assertEqual(dialog.states[0].text(), "Linked.")
        self.assertEqual(read_json(project / "project.json")["recording"]["bound_how"], "linked by you")
        self.assertTrue((project / "project.json.before-link").is_file())
        click(dialog.close_button)
        self.app.processEvents()
        self.assertFalse(page.link_button.isVisible(), "a linked video is no longer offered")
        connection = recording_records.connect(backup=False)
        try:
            self.assertEqual([row["link_state"] for row in recording_records.editor_index(connection)], ["bound"])
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
