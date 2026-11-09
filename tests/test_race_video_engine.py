"""AI Video Editor engine (150 Phase 1): timeline, projects, renderer, technical check.

The render tests go through real FFmpeg on a small synthetic three-panel recording with two audio
streams, and inspect the output file itself, not the renderer's intentions.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers import cli  # noqa: E402
from media_manglers.core.race_video import render as render_module  # noqa: E402
from media_manglers.core.race_video.project import (  # noqa: E402
    add_version,
    create_project,
    load_version,
    read_json,
    save_feedback,
    version_dir,
)
from media_manglers.core.race_video.render import RenderOptions, render_version  # noqa: E402
from media_manglers.core.race_video.requests import render_from_request  # noqa: E402
from media_manglers.core.race_video.timeline import SCHEMA, validate_timeline  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
LAYOUT = {"width": 960, "height": 180,
          "panels": {"left": [0, 0, 320, 180], "center": [320, 0, 320, 180], "right": [640, 0, 320, 180]}}


def _timeline(source: Path, **overrides) -> dict:
    timeline = {
        "schema": SCHEMA,
        "source": str(source),
        "source_layout": LAYOUT,
        "tracks": {"voice": 0, "game": 1},
        "scenes": [
            {"id": "s01", "beat": "hook", "reason": "test", "in": 0.5, "out": 3.5, "view": "center",
             "inset": {"view": "right", "pos": "top-right", "width": 440},
             "audio": {"voice": 1.0, "game": 0.5},
             "title": {"text": "Test race\nsecond line", "start": 0.2, "dur": 2.0, "style": "lower"}},
            {"id": "s02", "beat": "face", "reason": "test", "in": 4.0, "out": 6.5, "view": "right",
             "audio": {"voice": 1.0, "game": 0.0}, "transition_in": "dissolve", "transition_dur": 0.5,
             "title": {"text": "Lap 2  ·  P16", "start": 0.2, "dur": 1.5, "style": "label"}},
            {"id": "s03", "beat": "end", "reason": "test", "in": 7.0, "out": 10.0, "view": "full",
             "audio": {"voice": 0.0, "game": 1.0}, "transition_in": "dip", "transition_dur": 0.6,
             "title": {"text": "Finished 11th\nof 25", "start": 0.5, "dur": 2.0, "style": "card"}},
        ],
    }
    timeline.update(overrides)
    return timeline


class TimelineValidationTests(unittest.TestCase):
    def test_a_good_timeline_has_no_problems(self) -> None:
        self.assertEqual(validate_timeline(_timeline(Path("race.mkv")), source_duration=12.0, audio_streams=2), [])

    def test_each_mistake_is_named_in_plain_english(self) -> None:
        cases = {
            "after the recording ends": lambda t: t["scenes"][0].update(out=99.0),
            "'out' (1.0) must be after 'in'": lambda t: t["scenes"][0].update({"in": 2.0, "out": 1.0}),
            "unknown view 'roof'": lambda t: t["scenes"][1].update(view="roof"),
            "is outside the 960x180 recording": lambda t: t["scenes"][1].update(view={"crop": [900, 0, 200, 100]}),
            "the id is used twice": lambda t: t["scenes"][1].update(id="s01"),
            "the first scene cannot dissolve": lambda t: t["scenes"][0].update(transition_in="dissolve"),
            "must be shorter than this scene": lambda t: t["scenes"][1].update(transition_dur=9.0),
            "the title runs past the end": lambda t: t["scenes"][0]["title"].update(dur=30.0),
            "audio.voice must be a gain": lambda t: t["scenes"][0]["audio"].update(voice=-1),
            "the recording has 2 audio streams": lambda t: t["tracks"].update(game=5),
        }
        for expected, mutate in cases.items():
            with self.subTest(expected=expected):
                timeline = _timeline(Path("race.mkv"))
                mutate(timeline)
                problems = validate_timeline(timeline, source_duration=12.0, audio_streams=2)
                self.assertTrue(any(expected in p for p in problems), problems)


class ProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "race.mkv"
        self.source.write_bytes(b"stand-in recording")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_versions_are_kept_with_their_parent_and_reason(self) -> None:
        project = create_project(self.root / "out", self.source)
        first = add_version(project, _timeline(self.source), story="the story", answers="first cut")
        revised = _timeline(self.source)
        revised["scenes"][0]["out"] = 3.0
        second = add_version(project, revised, answers="opening too slow", parent=first)
        self.assertEqual((first, second), (1, 2))
        meta = read_json(project / "project.json")
        self.assertEqual(meta["current_version"], 2)
        self.assertEqual([(v["version"], v["parent"], v["answers"]) for v in meta["versions"]],
                         [(1, None, "first cut"), (2, 1, "opening too slow")])
        self.assertEqual(load_version(project, 1)["scenes"][0]["out"], 3.5, "an earlier version is never changed")
        self.assertEqual((version_dir(project, 1) / "story.md").read_text(encoding="utf-8"), "the story")
        self.assertFalse(list(project.rglob(".*.tmp")), "no temporary files are left behind")

    def test_a_timeline_that_cannot_render_is_refused_and_nothing_changes(self) -> None:
        project = create_project(self.root / "out", self.source)
        add_version(project, _timeline(self.source))
        before = (project / "project.json").read_text(encoding="utf-8")
        broken = _timeline(self.source)
        broken["scenes"][0]["view"] = "roof"
        with self.assertRaisesRegex(ValueError, "unknown view"):
            add_version(project, broken)
        self.assertEqual((project / "project.json").read_text(encoding="utf-8"), before)
        self.assertFalse(version_dir(project, 2).exists())

    def test_a_project_belongs_to_one_recording(self) -> None:
        create_project(self.root / "out", self.source, "race")
        other = self.root / "other.mkv"
        other.write_bytes(b"a different recording")
        with self.assertRaisesRegex(ValueError, "different recording"):
            create_project(self.root / "out", other, "race")

    def test_feedback_is_stored_for_the_next_revision(self) -> None:
        project = create_project(self.root / "out", self.source)
        add_version(project, _timeline(self.source))
        path = save_feedback(project, 1, "The opening is too slow.")
        self.assertEqual(path.read_text(encoding="utf-8"), "The opening is too slow.\n")
        with self.assertRaisesRegex(ValueError, "does not exist"):
            save_feedback(project, 7, "nope")


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class RenderTests(unittest.TestCase):
    """Real renders of a synthetic recording: left test pattern, centre pattern, right checkerboard."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / "race.mkv"
        subprocess.run([
            FFMPEG, "-hide_banner", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=12",
            "-f", "lavfi", "-i", "testsrc=s=320x180:r=30:d=12",
            "-f", "lavfi", "-i", "nullsrc=s=320x180:r=30:d=12,geq=lum='if(mod(floor(X/4)+floor(Y/4),2),235,16)':cb=128:cr=128",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=12",
            "-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.3:sample_rate=48000:duration=12",
            "-filter_complex", "[0:v][1:v][2:v]hstack=inputs=3,format=yuv420p[v]",
            "-map", "[v]", "-map", "3:a", "-map", "4:a", "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-shortest", str(cls.source),
        ], check=True)
        # Privacy mask for the right camera: its left half is private.
        cls.mask = cls.root / "right-mask.png"
        subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi",
                        "-i", "color=black:s=320x180,drawbox=x=0:y=0:w=160:h=180:color=white:t=fill",
                        "-frames:v", "1", str(cls.mask)], check=True)
        cls.options = RenderOptions(ffmpeg=FFMPEG, ffprobe=FFPROBE, masks={"right": cls.mask},
                                    encoder="x264", hwaccel="none")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def _project(self, name: str) -> Path:
        project = create_project(self.root / "out", self.source, name)
        add_version(project, _timeline(self.source), source_duration=12.0, audio_streams=2)
        return project

    def test_render_produces_a_video_that_passes_the_technical_check(self) -> None:
        project = self._project("check")
        result = render_from_request({"project": str(project), "version": 1, "profile": "preview",
                                      "ffmpeg": FFMPEG, "ffprobe": FFPROBE, "encoder": "x264", "hwaccel": "none",
                                      "privacy_masks": {"right": str(self.mask)}})
        qc = result["technical_check"]
        failures = [c for c in qc["checks"] if not c["pass"]]
        self.assertTrue(qc["passed"], failures)
        # 3.0 + 2.5 + 3.0 seconds of scenes, minus the 0.5 s dissolve and the 0.6 s dip.
        self.assertAlmostEqual(result["render"]["expected_duration"], 7.4, places=2)
        self.assertAlmostEqual(qc["duration"], 7.4, delta=0.2)
        self.assertTrue((version_dir(project, 1) / "renders" / "qc-preview.json").exists())
        self.assertEqual(result["render"]["privacy_masks"], ["right"])

    def test_unchanged_scenes_are_not_rendered_again(self) -> None:
        project = self._project("cache")
        first = render_version(project, 1, "preview", self.options)
        second = render_version(project, 1, "preview", self.options)
        self.assertEqual((first["scenes_rendered"], first["scenes_reused"]), (3, 0))
        self.assertEqual((second["scenes_rendered"], second["scenes_reused"]), (0, 3))

    def test_the_private_half_of_the_camera_is_blurred_and_the_rest_is_not(self) -> None:
        project = self._project("privacy")
        report = render_version(project, 1, "preview", self.options)
        # 226: scene pictures live in the project's scene store; the report names each one's file.
        scene = Path(report["scenes"][1]["picture"]["file"])
        self.assertEqual(report["scenes"][1]["picture"]["masks_applied"], ["right"])
        raw = subprocess.run([FFMPEG, "-v", "error", "-ss", "1.0", "-i", str(scene), "-frames:v", "1",
                              "-vf", "format=gray", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
        width, height = 1280, 720
        rows = [raw[y * width:(y + 1) * width] for y in range(200, 520)]

        def detail(x0: int, x1: int) -> float:
            # Mean absolute difference between neighbouring pixels: high for a sharp checkerboard.
            total = count = 0
            for row in rows:
                for x in range(x0, x1 - 1):
                    total += abs(row[x] - row[x + 1])
                    count += 1
            return total / count

        private, public = detail(80, 560), detail(720, 1200)
        # 4-pixel squares scaled 4x: a sharp edge every 16 pixels of up to ~220 levels.
        self.assertGreater(public, 10, f"the public half keeps its checkerboard ({public:.1f})")
        self.assertLess(private, public / 5, f"the private half must be blurred ({private:.1f} vs {public:.1f})")

    def test_a_failed_render_leaves_earlier_output_and_the_project_untouched(self) -> None:
        project = self._project("failure")
        render_version(project, 1, "preview", self.options)
        final = version_dir(project, 1) / "renders" / "preview.mp4"
        before_bytes = final.read_bytes()
        before_meta = (project / "project.json").read_text(encoding="utf-8")
        changed = _timeline(self.source)
        changed["scenes"][1]["out"] = 6.0
        changed["scenes"][2]["out"] = 9.5
        add_version(project, changed, parent=1, answers="shorter middle and ending", source_duration=12.0)
        calls = {"n": 0}
        # 226: scene pictures are rendered on their own (the unchanged first scene is reused); the
        # second one this render needs is killed part-way, inside a real FFmpeg run.
        real = render_module._picture_command

        def fail_on_second(*args, **kwargs):
            calls["n"] += 1
            command, applied = real(*args, **kwargs)
            if calls["n"] == 2:
                command = [*command[:-1], "-no-such-option", command[-1]]
            return command, applied

        with patch.object(render_module, "_picture_command", side_effect=fail_on_second):
            with self.assertRaises(render_module.RenderError):
                render_version(project, 2, "preview", self.options)
        self.assertEqual(calls["n"], 2, "one changed scene was rendered before the failure")
        self.assertEqual(final.read_bytes(), before_bytes, "version 1's render is untouched")
        meta = read_json(project / "project.json")
        self.assertEqual(meta["current_version"], 2)
        self.assertEqual(json.loads(before_meta)["versions"], meta["versions"][:1])
        self.assertFalse((version_dir(project, 2) / "renders" / "preview.mp4").exists(), "no half-made final file")
        for folder in (version_dir(project, 2) / "renders", project / "scene-cache"):
            leftovers = [p for p in folder.rglob("*") if p.name.startswith(".")]
            self.assertEqual(leftovers, [], f"no temporary files are left behind in {folder.name}")
        self.assertFalse((project / "scene-cache" / "render.lock").exists(), "the project's render lock is let go")

    def test_a_missing_privacy_mask_stops_the_render(self) -> None:
        project = self._project("nomask")
        options = RenderOptions(ffmpeg=FFMPEG, ffprobe=FFPROBE, masks={"right": self.root / "gone.png"},
                                encoder="x264", hwaccel="none")
        with self.assertRaisesRegex(ValueError, "privacy mask for the right camera is missing"):
            render_version(project, 1, "preview", options)


class CommandLineTests(unittest.TestCase):
    def test_validate_reports_problems_through_the_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            timeline = _timeline(root / "race.mkv")
            timeline["scenes"][1]["view"] = "roof"
            request, result = root / "request.json", root / "result.json"
            request.write_text(json.dumps({"payload": {"timeline": timeline}}), encoding="utf-8")
            code = cli.main(["race-video-validate", "--request-file", str(request), "--result-file", str(result)])
            data = json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual(code, 0)
            self.assertTrue(data["ok"])
            self.assertTrue(any("unknown view 'roof'" in p for p in data["data"]["problems"]))


if __name__ == "__main__":
    unittest.main()
