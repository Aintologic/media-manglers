"""Design wave D2 (236), the AI Video Editor's core: the story strip, a version's files, the readable
story and review, scene notes, and the agent's side (the brief and the prompt).

Through the real functions on real files: projects made by the core itself, files on the disk, links
made by the operating system.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core.race_video.analysis import BUDGETS  # noqa: E402
from media_manglers.core.race_video.library import list_projects, project_summary, story_title, version_files  # noqa: E402
from media_manglers.core.race_video.project import (  # noqa: E402
    add_version,
    create_project,
    notes_with_scenes,
    save_feedback,
    scene_note_line,
    split_scene_notes,
)
from media_manglers.core.race_video.prompt import APP_LABELS, BRIEF, build_prompt  # noqa: E402
from media_manglers.core.race_video.readable import readable  # noqa: E402
from media_manglers.core.race_video.timeline import SCHEMA, beat_name, story_blocks  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
LAYOUT = {"width": 960, "height": 180,
          "panels": {"left": [0, 0, 320, 180], "center": [320, 0, 320, 180], "right": [640, 0, 320, 180]}}


def _scene(sid: str, beat: str, start: float, end: float, **extra) -> dict:
    return {"id": sid, "beat": beat, "reason": "test", "in": start, "out": end, "view": "center", **extra}


class StoryStripTests(unittest.TestCase):
    def test_scenes_with_the_same_beat_are_one_block_and_a_dissolve_overlaps_the_scene_before(self) -> None:
        timeline = {"scenes": [
            _scene("s01", "start", 0.0, 10.0),
            _scene("s02", "start", 20.0, 25.0, transition_in="dissolve", transition_dur=1.0),
            _scene("s03", "pit_stop", 40.0, 70.0, transition_in="dip", transition_dur=0.5),
            _scene("s04", "", 80.0, 90.0),
            _scene("s05", "Finish", 100.0, 112.5),
        ]}
        self.assertEqual(story_blocks(timeline), [
            {"name": "Start", "start": 0.0, "length": 14.0, "scenes": ["s01", "s02"]},
            {"name": "Pit stop", "start": 13.5, "length": 30.0, "scenes": ["s03"]},
            {"name": "Scene 4", "start": 43.5, "length": 10.0, "scenes": ["s04"]},
            {"name": "Finish", "start": 53.5, "length": 12.5, "scenes": ["s05"]},
        ])

    def test_a_scene_that_cannot_be_read_never_stops_the_strip(self) -> None:
        timeline = {"scenes": [_scene("s01", "start", 0.0, 5.0), {"id": "bad"}, _scene("s03", "end", 9.0, 8.0),
                               _scene("s04", "battle", 10.0, 12.0)]}
        self.assertEqual([block["name"] for block in story_blocks(timeline)], ["Start", "Battle"])
        self.assertEqual(story_blocks({}), [])

    def test_beat_names_read_as_words(self) -> None:
        self.assertEqual([beat_name(beat) for beat in ("pit_stop", "battle for  P5", "", None)],
                         ["Pit stop", "Battle for P5", "", ""])


@unittest.skipUnless(FFMPEG, "FFmpeg is required")
class VersionFilesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.source = Path(cls.temp.name) / "race.mkv"
        subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=960x180:r=30:d=4",
                        "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:duration=4",
                        "-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.05:sample_rate=48000:duration=4",
                        "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264", "-preset", "ultrafast",
                        "-c:a", "aac", "-shortest", str(cls.source)], check=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def _version(self, label: str = "claude-opus-5.5") -> Path:
        project = create_project(self.root / "out", self.source, "race")
        add_version(project, {"schema": SCHEMA, "source": str(self.source), "source_layout": LAYOUT,
                              "tracks": {"voice": 0, "game": 1}, "scenes": [_scene("s01", "start", 0.5, 3.0)]},
                    story="# Story — A test race at Spa\n\n## In short\n\nThe driver holds second.",
                    source_duration=4.0, audio_streams=2, editor_label=label)
        return project

    def test_the_apps_files_and_the_agents_own_are_told_apart(self) -> None:
        # The app's renders are renders/preview.mp4 and final.mp4 with their readable names (links to them);
        # anything else the AI agent made itself, in the version's folder or its renders folder.
        project = self._version()
        renders = project / "versions" / "v001" / "renders"
        renders.mkdir(parents=True)
        (renders / "preview.mp4").write_bytes(b"preview")
        os.link(renders / "preview.mp4", renders / "race-v001-claude-opus-5.5-preview.mp4")
        (renders / "final.mp4").write_bytes(b"final")
        (renders / "final-2560x1440.mp4").write_bytes(b"a validation render")
        (renders / "preview-peak-repair.mp4").write_bytes(b"the agent's own")
        (renders / ".preview.1234.tmp.mp4").write_bytes(b"half written")
        (renders / "render-preview.json").write_text("{}", encoding="utf-8")
        (project / "versions" / "v001" / "my-cut.mkv").write_bytes(b"also the agent's")
        entry = json.loads((project / "project.json").read_text(encoding="utf-8"))["versions"][0]
        rows = version_files(project, entry)
        self.assertEqual([(row["role"], row["made_by"], row["name"], row["same_as"]) for row in rows], [
            ("preview", "app", "preview.mp4", ""),
            ("final", "app", "final.mp4", ""),
            ("validation", "app", "final-2560x1440.mp4", ""),
            ("readable", "app", "race-v001-claude-opus-5.5-preview.mp4", "preview"),
            ("agent", "agent", "my-cut.mkv", ""),
            ("agent", "agent", "preview-peak-repair.mp4", ""),
        ])
        self.assertEqual(rows[0]["size"], len(b"preview"))

    def test_an_export_is_the_same_file_as_the_final(self) -> None:
        # 178: the export is a link to the final when the drive allows one, so the two are one file.
        project = self._version(label="")
        renders = project / "versions" / "v001" / "renders"
        renders.mkdir(parents=True)
        (renders / "final.mp4").write_bytes(b"final")
        (project / "export").mkdir(exist_ok=True)
        os.link(renders / "final.mp4", project / "export" / "race-v001.mp4")
        meta = json.loads((project / "project.json").read_text(encoding="utf-8"))
        meta["versions"][0]["export"] = "race-v001.mp4"
        (project / "project.json").write_text(json.dumps(meta), encoding="utf-8")
        summary = project_summary(project)
        version = summary["versions"][0]
        self.assertTrue(version["exported"])
        self.assertEqual([(row["role"], row["same_as"]) for row in version["files"]], [("final", ""), ("export", "final")])

    def test_a_project_says_its_story_title_and_when_anything_last_happened(self) -> None:
        project = self._version()
        summary = list_projects(self.root / "out")[0]
        self.assertEqual(summary["story_title"], "A test race at Spa")
        created = json.loads((project / "project.json").read_text(encoding="utf-8"))["versions"][0]["created"]
        self.assertEqual(summary["activity"], created)
        self.assertEqual(Path(summary["versions"][0]["timeline"]).name, "timeline.json")
        self.assertEqual(summary["versions"][0]["preview_format"], {})

    def test_story_titles(self) -> None:
        story = self.root / "story.md"
        for text, title in (("# Story — A wet race at a long circuit, 2026-09-01\n", "A wet race at a long circuit, 2026-09-01"),
                            ("# Codex edit - a GT race in the dark\n", "Codex edit - a GT race in the dark"),
                            ("# Story\n\nv2", ""), ("No heading", ""), ("\n\n# The story: Spa\n", "Spa")):
            with self.subTest(text=text):
                story.write_text(text, encoding="utf-8")
                self.assertEqual(story_title(story), title)

    def test_scene_notes_are_kept_under_the_notes_and_read_back(self) -> None:
        project = self._version()
        block = story_blocks({"scenes": [_scene("s07", "pit stop", 0.0, 135.0), _scene("s08", "pit stop", 200.0, 230.0)]})[0]
        line = scene_note_line(block)
        self.assertEqual(line, "Pit stop: scenes s07, s08, from 0:00 to 2:45 of the video")
        saved = save_feedback(project, 1, notes_with_scenes("Pit stop: too long.", [line]))
        text = saved.read_text(encoding="utf-8")
        self.assertEqual(text, "Pit stop: too long.\n\nScenes these notes are about:\n- " + line + "\n")
        self.assertEqual(split_scene_notes(text), ("Pit stop: too long.", [line]))
        self.assertEqual(split_scene_notes("Just words."), ("Just words.", []))
        self.assertEqual(notes_with_scenes("Words", []), "Words")


class ReadableTests(unittest.TestCase):
    def test_the_brief_s_headings_come_first(self) -> None:
        parts = readable("# Review of v002\n\n## In short\n\nGood.\n\n## What works\n\nThe start.\n\n"
                         "## What changed\n\n- Shorter.\n\n## Concerns\n\n- The end.\n")
        self.assertEqual((parts["title"], parts["summary"], parts["changes"], parts["concerns"]),
                         ("Review of v002", "Good.", "- Shorter.", "- The end."))
        self.assertEqual([heading for heading, _body in parts["rest"]], ["What works"])

    def test_files_written_before_the_brief_asked_are_read_by_their_own_headings(self) -> None:
        review = readable("# Review of v002 (round 2 of 2)\nParent: v001. Length 6:30.\n\n## What changed from v001\n"
                          "- Dropped the black opening.\n\n## What works\nGood.\n\n## Still weak (a judgement call)\n"
                          "1. The first frame is black.\n")
        self.assertEqual((review["summary"], review["changes"], review["concerns"]),
                         ("Parent: v001. Length 6:30.", "- Dropped the black opening.", "1. The first frame is black."))
        story = readable("# Story\n\n## In one line\nA rainy race.\n\n## Beats, in order\n1. Start\n")
        self.assertEqual(story["summary"], "A rainy race.")
        codex = readable("# Codex final self-review\n\n## Outcome\nIt passed.\n\n## Remaining limits and sharing decision\n"
                         "None.\n")
        self.assertEqual((codex["summary"], codex["concerns"]), ("It passed.", "None."))

    def test_nothing_is_invented(self) -> None:
        self.assertEqual(readable(""), {"title": "", "summary": "", "changes": "", "concerns": "", "rest": []})
        self.assertEqual(readable("# Only a title")["summary"], "")


class AgentSideTests(unittest.TestCase):
    """236 item 4: the agent's instructions match the app's labels and workflow."""

    def setUp(self) -> None:
        self.brief = BRIEF.read_text(encoding="utf-8")

    def test_the_brief_tells_the_agent_items_4a_to_4g(self) -> None:
        section = self.brief.split("## Working with the operator (read this first)", 1)[1].split("\n## ", 1)[0]
        section = " ".join(section.split())
        for words in ("Start with your plan, in plain words",                  # 4a
                      "Say whether you will wait for them",                     # 4b
                      "If waiting would cause a problem",                       # 4b
                      "Never \"contact sheets\", \"look budget\"",              # 4c
                      "Finish with the result and the exact next steps",       # 4d
                      "Say what to do if the version does not appear",         # 4e
                      "Keep the technical detail apart", "technical.md",      # 4f
                      "One workflow"):                                         # 4g
            with self.subTest(words=words):
                self.assertIn(words, section)
        # 4g: every label of the app the hand-over names is the app's own, in bold (lines wrap anywhere).
        flowing = " ".join(self.brief.split())
        # The fix round: the toolbar's Files, Story & review and Prompt instead of the ⋯ menu, and the play
        # choices on the picture.
        for key in ("page", "videos", "continue", "files_tool", "story_tool", "prompt_tool", "refresh", "fresh", "play",
                    "play_final", "notes", "save_notes_claude", "save_notes_codex", "approve", "render"):
            with self.subTest(label=key):
                self.assertIn(f"**{APP_LABELS[key]}", flowing)

    def test_the_brief_no_longer_asks_the_agent_to_render_the_final(self) -> None:
        self.assertNotIn("then render with the `final` profile", self.brief)
        self.assertIn("Do not render the final", self.brief)
        self.assertIn("`## In short`", self.brief)
        self.assertIn("`## What changed`", self.brief)
        self.assertIn("`## Concerns`", self.brief)

    @unittest.skipUnless(FFMPEG, "FFmpeg is required")
    def test_the_prompt_sends_the_agent_to_the_brief_s_first_section_and_names_the_notes_scenes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "race.mkv"
            subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=960x180:r=30:d=4",
                            "-f", "lavfi", "-i", "sine=duration=4", "-f", "lavfi", "-i", "sine=duration=4",
                            "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264", "-preset", "ultrafast",
                            "-shortest", str(source)], check=True)
            project = create_project(Path(folder) / "out", source, "race")
            (project / "analysis" / "analysis.json").write_text(json.dumps({"settings": {"budget": "light"}}),
                                                                 encoding="utf-8")
            add_version(project, {"schema": SCHEMA, "source": str(source), "source_layout": LAYOUT,
                                  "tracks": {"voice": 0, "game": 1}, "scenes": [_scene("s01", "start", 0.5, 3.0)]},
                        source_duration=4.0, audio_streams=2)
            first = build_prompt(project, tool="claude", python="python", src_root=Path(folder))
            self.assertIn('"Working with the operator"', first)
            self.assertIn("technical.md", first)
            self.assertIn("Do not upload, publish, or render the final: the operator approves with Approve and export…",
                          first)
            self.assertIn("press Prompt, then Start a fresh edit, on the video's AI Video Editor page", first)
            self.assertNotIn("⋯", first)
            revision = build_prompt(project, tool="codex", python="python", src_root=Path(folder), feedback_version=1,
                                    scenes=["Start: scene s01, from 0:00 to 0:03 of the video"])
            self.assertIn("This is a revision", revision)
            self.assertIn("Start by saying in plain words what you will change", revision)
            self.assertIn("- Start: scene s01, from 0:00 to 0:03 of the video", revision)

    def test_the_budgets_the_page_explains_are_the_ones_the_code_uses(self) -> None:
        from media_manglers_workbench.ai_video_editor_parts import budget_words  # noqa: PLC0415

        for budget, spec in BUDGETS.items():
            with self.subTest(budget=budget):
                words = budget_words(budget)
                numbers = [int(number) for number in re.findall(r"\b(\d+)\b", words)]
                self.assertIn(spec["still_interval"], numbers)
                self.assertIn(spec["max_sheets"] * 36, numbers)
                self.assertIn(spec["close_look_images"], numbers)


if __name__ == "__main__":
    unittest.main()
