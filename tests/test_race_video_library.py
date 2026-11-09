"""AI Video Editor Phase 3 (150): what the editor page lists, the export, and the mask-drawing still.

Everything is read from real project folders made by the engine, and the export goes through real
FFmpeg on a small synthetic three-panel recording.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers import cli  # noqa: E402
from media_manglers.core.race_video import library  # noqa: E402
from media_manglers.core.race_video.library import export_version, list_projects, panel_still, start_fresh_edit  # noqa: E402
from media_manglers.core.race_video.project import add_version, create_project, record_usage, save_feedback, usage_report  # noqa: E402
from media_manglers.core.race_video.prompt import BRIEF, build_prompt  # noqa: E402
from media_manglers.core.race_video.render import RenderOptions, render_version  # noqa: E402
from media_manglers.core.race_video.timeline import SCHEMA  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
LAYOUT = {"width": 960, "height": 180,
          "panels": {"left": [0, 0, 320, 180], "center": [320, 0, 320, 180], "right": [640, 0, 320, 180]}}


def _timeline(source: Path) -> dict:
    return {"schema": SCHEMA, "source": str(source), "source_layout": LAYOUT, "tracks": {"voice": 0, "game": 1},
            "scenes": [{"id": "s01", "beat": "start", "reason": "test", "in": 1.0, "out": 4.0, "view": "center",
                        "audio": {"voice": 1.0, "game": 0.5}}]}


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class EditorLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / "race.mkv"
        subprocess.run([
            FFMPEG, "-hide_banner", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=s=960x180:r=30:d=8",
            "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:duration=8",
            "-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.05:sample_rate=48000:duration=8",
            "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-shortest", str(cls.source),
        ], check=True)
        cls.options = RenderOptions(ffmpeg=FFMPEG, ffprobe=FFPROBE, masks={}, encoder="x264", hwaccel="none")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def test_an_empty_output_folder_has_no_projects(self) -> None:
        self.assertEqual(list_projects(self.root / "nothing-here"), [])

    def test_the_page_sees_each_version_and_what_it_has(self) -> None:
        output = self.root / "listing"
        project = create_project(output, self.source, "listed")
        first = add_version(project, _timeline(self.source), story="# Story", source_duration=8.0, audio_streams=2)
        second = add_version(project, _timeline(self.source), answers="tighter start", parent=first,
                             source_duration=8.0, audio_streams=2)
        render_version(project, first, "preview", self.options)
        save_feedback(project, first, "The opening is too slow.")
        broken = output / "race-videos" / "broken"
        broken.mkdir(parents=True)
        (broken / "project.json").write_text("{not json", encoding="utf-8")

        projects = list_projects(output)
        self.assertEqual([p["name"] for p in projects], ["listed"], "an unreadable project is skipped")
        summary = projects[0]
        self.assertFalse(summary["analysed"])
        self.assertEqual(summary["current_version"], second)
        newest, oldest = summary["versions"]
        self.assertEqual((newest["label"], newest["parent"], newest["answers"]), ("v002", 1, "tighter start"))
        self.assertEqual((newest["preview"], newest["story"], newest["feedback"]), ("", "", ""))
        self.assertTrue(oldest["story"].endswith("story.md"))
        self.assertTrue(Path(oldest["preview"]).exists())
        self.assertIsNone(oldest["preview_passed"], "no technical check has been run for this preview yet")
        self.assertTrue(oldest["feedback"].endswith("v001.md"))

    def test_every_file_of_an_export_is_on_the_disk_before_it_is_in_place(self) -> None:
        # 183: a system crash a minute after a render once left it damaged after it was reported done.
        from media_manglers.core.race_video import project as project_module

        events: list[tuple[str, str]] = []
        real_flush, real_replace = project_module.flush_to_disk, project_module.os.replace

        def flush(path):
            events.append(("flush", Path(path).name))
            real_flush(path)

        def replace(source, target):
            events.append(("rename", Path(source).name))
            real_replace(source, target)

        project = create_project(self.root / "durable", self.source, "durable")
        version = add_version(project, _timeline(self.source), source_duration=8.0, audio_streams=2)
        with patch.object(project_module, "flush_to_disk", flush), patch.object(project_module.os, "replace", replace):
            result = export_version(project, version, self.options)
        self.assertTrue(result["export"])
        renamed = [name for kind, name in events if kind == "rename"]
        # 226: the scene's picture and sound, the joined picture (each with how it was made), the render,
        # its readable name, its report, the check and the export; temporary names carry the process id.
        pid = os.getpid()
        for expected in (rf"\.[0-9a-f]{{32}}\.{pid}\.tmp\.mkv", rf"\.[0-9a-f]{{32}}\.{pid}\.tmp\.wav",
                         rf"\.[0-9a-f]{{32}}\.{pid}\.tmp\.mp4", r"\.[0-9a-f]{32}\.json\.tmp", rf"\.final\.{pid}\.tmp\.mp4",
                         rf"\.durable-v001-final\.mp4\.{pid}\.tmp", r"\.render-final\.json\.tmp", r"\.qc-final\.json\.tmp",
                         rf"\.durable-v001\.mp4\.{pid}\.tmp"):
            with self.subTest(file=expected):
                self.assertTrue(any(re.fullmatch(expected, name) for name in renamed), renamed)
        for index, (kind, name) in enumerate(events):
            if kind == "rename":
                self.assertEqual(events[index - 1], ("flush", name), f"{name} is flushed just before its rename")

    def test_an_export_is_placed_only_when_the_technical_check_passes(self) -> None:
        project = create_project(self.root / "exporting", self.source, "exported")
        version = add_version(project, _timeline(self.source), source_duration=8.0, audio_streams=2)
        result = export_version(project, version, self.options)
        self.assertTrue(result["technical_check"]["passed"], result["technical_check"])
        exported = Path(result["export"])
        self.assertEqual(exported.name, "exported-v001.mp4")
        self.assertEqual(exported.stat().st_size, Path(result["render"]["output"]).stat().st_size)
        summary = list_projects(self.root / "exporting")[0]
        self.assertEqual(summary["exports"], [str(exported)])
        self.assertTrue(summary["versions"][0]["final_passed"])

        failing = {"passed": False, "checks": [{"check": "loudness", "pass": False, "detail": "test"}]}
        with patch.object(library, "check_video", return_value=failing):
            second = add_version(project, _timeline(self.source), parent=version, source_duration=8.0, audio_streams=2)
            result = export_version(project, second, self.options)
        self.assertEqual(result["export"], "")
        self.assertFalse((project / "export" / "exported-v002.mp4").exists(), "a failed video is never exported")

    def test_the_mask_still_is_one_camera_at_the_recordings_own_size(self) -> None:
        still = panel_still(FFMPEG, self.source, LAYOUT, "right", 2.0, self.root / "still" / "right.png")
        size = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(still)],
                              capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(size, "320,180")
        with self.assertRaisesRegex(ValueError, "unknown panel 'roof'"):
            panel_still(FFMPEG, self.source, LAYOUT, "roof", 2.0, self.root / "still" / "roof.png")
        # 226: taken by the shared frame renderer now, and its failure still names the camera.
        with self.assertRaisesRegex(RuntimeError, "^could not take a still of the right camera: .+"):
            panel_still(FFMPEG, self.root / "no-such-recording.mkv", LAYOUT, "right", 2.0, self.root / "still" / "gone.png")
        self.assertFalse((self.root / "still" / "gone.png").exists())

    def test_the_prompt_names_the_brief_beside_the_commands_the_editor_runs(self) -> None:
        # In the packaged app the Workbench is a bundle without the brief; the editor reads the
        # copy in the Python core whose commands it runs.
        project = create_project(self.root / "brief", self.source, "brief")
        (project / "analysis" / "analysis.json").write_text(json.dumps({"settings": {"budget": "light"}}), encoding="utf-8")
        core = self.root / "python-core" / "src"
        brief = core / "media_manglers" / "core" / "race_video" / "brief.md"
        brief.parent.mkdir(parents=True)
        brief.write_text("# Brief", encoding="utf-8")
        self.assertIn(str(brief), build_prompt(project, tool="claude", python="python", src_root=core))
        elsewhere = build_prompt(project, tool="claude", python="python", src_root=self.root / "no-core")
        self.assertIn(str(BRIEF), elsewhere, "without a core copy, the brief shipped with this code")

    def test_a_fresh_edit_is_separate_from_the_first_and_keeps_it_as_it_was(self) -> None:
        # 171: a second editor must not continue the first editor's work or inherit its spent budget.
        output = self.root / "fresh"
        first = create_project(output, self.source, "race")
        (first / "analysis" / "sheets").mkdir(parents=True)
        (first / "analysis" / "sheets" / "sheet-01.jpg").write_bytes(b"sheet")
        (first / "analysis" / "analysis.json").write_text(json.dumps({"settings": {"budget": "standard"}}), encoding="utf-8")
        (first / "analysis" / "digest.md").write_text("# Race analysis", encoding="utf-8")
        record_usage(first, "contact sheets prepared for the AI editor", 4)
        add_version(first, _timeline(self.source), story="# First editor's story", source_duration=8.0, audio_streams=2)
        record_usage(first, "review rounds", 2, version=1)
        before = (first / "project.json").read_text(encoding="utf-8")

        second = start_fresh_edit(first)
        third = start_fresh_edit(second)

        self.assertEqual((second.name, third.name), ("race-edit-2", "race-edit-3"), "numbered from the original")
        self.assertEqual((first / "project.json").read_text(encoding="utf-8"), before, "the first edit is untouched")
        summary = {p["name"]: p for p in list_projects(output)}
        self.assertEqual(summary["race-edit-2"]["versions"], [])
        self.assertTrue(summary["race-edit-2"]["analysed"], "the analysis came with it, ready at once")
        self.assertEqual(summary["race-edit-2"]["edit_of"], "race")
        self.assertEqual(summary["race-edit-3"]["edit_of"], "race")
        self.assertTrue((second / "analysis" / "sheets" / "sheet-01.jpg").exists())
        self.assertEqual(usage_report(second)["totals"], {"contact sheets prepared for the AI editor": 4},
                         "a fresh budget: only the sheets its editor will read")
        prompt = build_prompt(second, tool="codex", python="python", src_root=self.root / "no-core")
        self.assertIn(str(second / "analysis" / "digest.md"), prompt)
        self.assertIn("Make the first version", prompt)

    def test_a_prompt_for_an_edit_that_has_versions_says_so(self) -> None:
        output = self.root / "continued"
        project = create_project(output, self.source, "race")
        (project / "analysis" / "analysis.json").write_text(json.dumps({"settings": {"budget": "light"}}), encoding="utf-8")
        add_version(project, _timeline(self.source), source_duration=8.0, audio_streams=2)
        prompt = build_prompt(project, tool="codex", python="python", src_root=self.root / "no-core")
        self.assertIn("already has versions up to v001", prompt)
        self.assertIn("Start a fresh edit", prompt)
        self.assertNotIn("Make the first version", prompt)

    def test_the_page_lists_projects_through_the_command_line(self) -> None:
        output = self.root / "cli"
        create_project(output, self.source, "from-cli")
        request = self.root / "projects-request.json"
        result = self.root / "projects-result.json"
        request.write_text(json.dumps({"payload": {"output_root": str(output)}}), encoding="utf-8")
        self.assertEqual(cli.main(["race-video-projects", "--request-file", str(request), "--result-file", str(result)]), 0)
        data = json.loads(result.read_text(encoding="utf-8"))
        self.assertTrue(data["ok"], data)
        self.assertEqual([p["name"] for p in data["data"]["projects"]], ["from-cli"])


class CrashSafeFileTests(unittest.TestCase):
    """183: a finished file is flushed to the disk before it is renamed into place."""

    def test_a_file_is_flushed_before_it_is_renamed_into_place(self) -> None:
        from media_manglers.core.race_video import project as project_module

        events: list[tuple[str, str]] = []
        real_flush, real_replace = project_module.flush_to_disk, project_module.os.replace

        def flush(path):
            events.append(("flush", Path(path).name))
            real_flush(path)

        def replace(source, target):
            events.append(("rename", Path(target).name))
            real_replace(source, target)

        with tempfile.TemporaryDirectory() as temp, \
                patch.object(project_module, "flush_to_disk", flush), \
                patch.object(project_module.os, "replace", replace):
            target = Path(temp) / "project.json"
            project_module.write_json_atomic(target, {"saved": True})
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"saved": True})
        self.assertEqual(events, [("flush", ".project.json.tmp"), ("rename", "project.json")])

    def test_flushing_reaches_the_operating_system(self) -> None:
        from media_manglers.core.race_video import project as project_module

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "render.mp4"
            path.write_bytes(b"data")
            with patch.object(project_module.os, "fsync", wraps=os.fsync) as fsync:
                project_module.flush_to_disk(path)
            self.assertEqual(fsync.call_count, 1)


if __name__ == "__main__":
    unittest.main()
