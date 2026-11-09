"""AI Video Editor Phase 2 (150): watching the race locally, privacy before the AI, the AI budget.

A synthetic 40 s three-panel recording with known events: the story panel turns solid red at 20 s
(a sharp picture change), the game sound jumps at 30 s (a spike), the voice speaks at 5-8 s and
25-28 s, and the right camera's left half is private. Everything is checked in the files produced.
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

from media_manglers.core.race_video import privacy  # noqa: E402
from media_manglers.core.race_video import analysis as analysis_module  # noqa: E402
from media_manglers.core.race_video.analysis import BUDGETS, analyze, still_interval  # noqa: E402
from media_manglers.core.race_video.project import add_version, create_project, usage_report, version_dir  # noqa: E402
from media_manglers.core.race_video.prompt import build_prompt  # noqa: E402
from media_manglers.core.race_video.render import RenderOptions, render_version  # noqa: E402
from media_manglers.core.race_video.requests import _masks  # noqa: E402
from media_manglers.core.race_video.review import (  # noqa: E402
    BudgetExceeded,
    checked_edges,
    close_look,
    cut_points,
    level_at,
    review_kit,
    word_cut_by,
)
from media_manglers.core.race_video.timeline import SCHEMA  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
LAYOUT = {"width": 960, "height": 180,
          "panels": {"left": [0, 0, 320, 180], "center": [320, 0, 320, 180], "right": [640, 0, 320, 180]}}


def _detail(gray: bytes, width: int, x0: int, x1: int, y0: int, y1: int) -> float:
    total = count = 0
    for y in range(y0, y1):
        row = gray[y * width:(y + 1) * width]
        for x in range(x0, x1 - 1):
            total += abs(row[x] - row[x + 1])
            count += 1
    return total / count


class CutPointRuleTests(unittest.TestCase):
    """Word timings vary by a few tenths; a split of continuous sound is not a cut."""

    def test_only_a_word_that_clearly_straddles_the_cut_is_reported(self) -> None:
        words = [{"word": "Good", "start": 10.0, "end": 10.4}, {"word": "job.", "start": 10.5, "end": 10.9}]
        self.assertEqual(word_cut_by(words, 10.2), "Good")
        self.assertEqual(word_cut_by(words, 10.05), "", "a cut 0.05 s into a word is within timing noise")
        self.assertEqual(word_cut_by(words, 10.45), "", "a cut in the gap between words is fine")

    def test_a_scene_that_continues_straight_into_the_next_is_not_a_cut(self) -> None:
        scenes = [
            {"id": "a", "in": 10.0, "out": 20.0, "audio": {"voice": 3.0}},
            {"id": "b", "in": 20.0, "out": 30.0, "audio": {"voice": 3.0}},
            {"id": "c", "in": 50.0, "out": 60.0, "audio": {"voice": 3.0}, "transition_in": "dissolve"},
            {"id": "d", "in": 60.0, "out": 70.0, "audio": {"voice": 0.0}},
        ]
        self.assertEqual([(s["id"], e) for s, e in checked_edges(scenes)],
                         [("a", "in"), ("b", "out"), ("c", "in"), ("c", "out")])


class PrivacyStoreTests(unittest.TestCase):
    def test_masks_are_kept_in_the_operators_store_and_loaded_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / "face.png"
            image.write_bytes(b"png stand-in")
            with patch.dict(os.environ, {"MEDIA_MANGLERS_RACE_VIDEO_PRIVACY": str(root / "store")}):
                privacy.save_mask("right", image)
                self.assertEqual(privacy.load_masks(), {"right": root / "store" / "right.png"})
                self.assertEqual(_masks({}), {"right": root / "store" / "right.png"},
                                 "a request without masks uses the operator's stored masks")
                # 226 (decision F): an empty set no longer switches the stored masks off.
                self.assertEqual(_masks({"privacy_masks": {}}), {"right": root / "store" / "right.png"},
                                 "an empty set does not remove stored masks")


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / "race.mkv"
        subprocess.run([
            FFMPEG, "-hide_banner", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=40",
            "-f", "lavfi", "-i", "testsrc=s=320x180:r=30:d=40,drawbox=x=0:y=0:w=320:h=180:color=red:t=fill:enable='gte(t,20)'",
            "-f", "lavfi", "-i", "nullsrc=s=320x180:r=30:d=40,geq=lum='if(mod(floor(X/4)+floor(Y/4),2),235,16)':cb=128:cr=128",
            "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:duration=40,volume='if(between(t,5,8)+between(t,25,28),1,0)':eval=frame",
            "-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.02:sample_rate=48000:duration=40,volume='if(between(t,30,31),30,1)':eval=frame",
            "-filter_complex", "[0:v][1:v][2:v]hstack=inputs=3,format=yuv420p[v]",
            "-map", "[v]", "-map", "3:a", "-map", "4:a", "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-shortest", str(cls.source),
        ], check=True)
        cls.mask = cls.root / "right-mask.png"
        subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi",
                        "-i", "color=black:s=320x180,drawbox=x=0:y=0:w=160:h=180:color=white:t=fill",
                        "-frames:v", "1", str(cls.mask)], check=True)
        cls.transcript = cls.root / "narration.json"
        cls.transcript.write_text(json.dumps({"segments": [
            {"start": 5.0, "end": 8.0, "text": "Here we go, into turn one."},
            {"start": 25.0, "end": 28.0, "text": "I want that point."},
        ]}), encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def _analyze(self, name: str, budget: str = "standard") -> tuple[Path, dict]:
        project = create_project(self.root / "out", self.source, name)
        data = analyze(project, self.source, budget=budget, tracks={"voice": 0, "game": 1}, layout=LAYOUT,
                       masks={"right": self.mask}, transcript=self.transcript, ffmpeg=FFMPEG, ffprobe=FFPROBE)
        return project, data

    def test_the_race_is_summarised_locally_with_its_known_events(self) -> None:
        project, data = self._analyze("events")
        self.assertEqual(data["stills"], 4, "one still every 10 s of a 40 s recording on the standard budget")
        self.assertEqual([t["role"] for t in data["tracks"]], ["voice", "game"])
        self.assertTrue(any(28 <= s["start"] <= 31 for s in data["game_sound_spikes"]), data["game_sound_spikes"])
        self.assertTrue(any(c["at"] == 20.0 for c in data["picture_changes"]), data["picture_changes"])
        self.assertEqual(len(data["sheets"]), 1)
        sheet = project / "analysis" / "sheets" / data["sheets"][0]["file"]
        self.assertTrue(sheet.exists())
        corner = subprocess.run([FFMPEG, "-v", "error", "-i", str(sheet), "-vf", "crop=8:8:iw-8:ih-8,format=rgb24",
                                 "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
        self.assertLess(max(corner), 40, "an empty tile is black, not green")
        digest = (project / "analysis" / "digest.md").read_text(encoding="utf-8")
        for expected in ("[00:05] Here we go, into turn one.", "Game-sound spikes", "00:20", "privacy masks applied: yes",
                         "never used without the operator's say-so"):
            self.assertIn(expected, digest)

    def test_the_long_steps_report_how_far_they_have_got(self) -> None:
        # 175: a long race showed "no processing update" while it was being watched.
        reports: list[tuple[str, int, int]] = []
        project = create_project(self.root / "out", self.source, "progress")
        with patch("media_manglers.core.race_video.analysis.PROGRESS_EVERY", 0.0):
            analyze(project, self.source, budget="standard", tracks={"voice": 0, "game": 1}, layout=LAYOUT,
                    masks={"right": self.mask}, transcript=self.transcript, ffmpeg=FFMPEG, ffprobe=FFPROBE,
                    on_progress=lambda *report: reports.append(report))
        # 226: the one shared read of the recording (sound and game picture) reports how far it has read.
        sound = [(done, total) for activity, done, total in reports if activity.startswith("Reading the recording")]
        self.assertGreater(len(sound), 1, "the sound is reported as it is read, not only at the start")
        self.assertEqual(sound[0], (0, 40))
        self.assertGreaterEqual(sound[-1][0], 38, sound)
        self.assertIn("Reading the recording: 00:", [a for a, _, _ in reports if "of 00:40" in a][0])
        measured = [activity for activity, _, _ in reports if activity.startswith("Measuring the sound of Track")]
        self.assertEqual(measured, ["Measuring the sound of Track 1 (1 of 2)", "Measuring the sound of Track 2 (2 of 2)"])
        stills = [(done, total) for activity, done, total in reports if activity.startswith("Taking stills")]
        self.assertEqual(stills, [(1, 4), (2, 4), (3, 4), (4, 4)])
        self.assertIn(("Making contact sheets: 1 of 1", 1, 1), reports)

    def test_progress_is_passed_on_a_few_times_a_minute_and_always_at_the_end(self) -> None:
        heard: list[tuple[str, int, int]] = []
        report = analysis_module._Throttle(lambda *r: heard.append(r))
        for done in range(1, 501):
            report("Taking stills", done, 500)
        self.assertEqual(heard, [("Taking stills", 1, 500), ("Taking stills", 500, 500)])

    def test_the_workbench_hears_a_step_with_how_far_it_has_got(self) -> None:
        import contextlib
        import io

        from media_manglers.core.race_video.requests import _progress

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            _progress({"progress_label": "race.mkv"}, "Watching the race", 3, 3,
                      activity="Taking stills: 120 of 336", completed=120, total=336)
            _progress({"progress_label": "race.mkv"}, "Watching the race", 3, 3)
        with_count, without = (json.loads(line.split(" ", 1)[1]) for line in out.getvalue().splitlines())
        self.assertEqual((with_count["progress_kind"], with_count["completed"], with_count["total"]),
                         ("work_units", 120, 336))
        self.assertEqual(with_count["activity"], "Taking stills: 120 of 336")
        self.assertNotIn("progress_kind", without)

    def test_the_digest_lists_other_voices_on_the_game_track(self) -> None:
        # 172: who else can be heard, with times, or plainly that nobody was, or that it was not checked.
        project, _ = self._analyze("no-game-speech")
        digest = (project / "analysis" / "digest.md").read_text(encoding="utf-8")
        self.assertIn("not listened for", digest)
        heard = self.root / "game.speech.json"
        heard.write_text(json.dumps({"segments": [{"start": 31.0, "end": 33.0, "text": "Good battle, thanks."}]}), encoding="utf-8")
        project = create_project(self.root / "out", self.source, "game-speech")
        data = analyze(project, self.source, budget="standard", tracks={"voice": 0, "game": 1}, layout=LAYOUT,
                       masks={"right": self.mask}, transcript=self.transcript, game_speech=heard, ffmpeg=FFMPEG, ffprobe=FFPROBE)
        self.assertEqual(data["game_speech"], [{"start": 31.0, "end": 33.0, "text": "Good battle, thanks."}])
        digest = (project / "analysis" / "digest.md").read_text(encoding="utf-8")
        self.assertIn("## Other voices on the game track", digest)
        self.assertIn("[00:31] Good battle, thanks.", digest)
        heard.write_text(json.dumps({"segments": []}), encoding="utf-8")
        project = create_project(self.root / "out", self.source, "nobody-else")
        analyze(project, self.source, budget="standard", tracks={"voice": 0, "game": 1}, layout=LAYOUT,
                masks={"right": self.mask}, transcript=self.transcript, game_speech=heard, ffmpeg=FFMPEG, ffprobe=FFPROBE)
        self.assertIn("- none heard", (project / "analysis" / "digest.md").read_text(encoding="utf-8"))

    def test_stills_are_blurred_through_the_privacy_mask_before_the_ai_sees_them(self) -> None:
        project, _ = self._analyze("privacy")
        still = project / "analysis" / "stills" / "s00001.jpg"
        gray = subprocess.run([FFMPEG, "-v", "error", "-i", str(still), "-vf", "format=gray", "-f", "rawvideo", "-"],
                              capture_output=True, check=True).stdout
        # The still is 1920x360; the right camera is x 1280-1920, its private half x 1280-1600.
        private = _detail(gray, 1920, 1300, 1580, 40, 320)
        public = _detail(gray, 1920, 1620, 1900, 40, 320)
        self.assertGreater(public, 10, f"the public half keeps its checkerboard ({public:.1f})")
        self.assertLess(private, public / 5, f"the private half is blurred ({private:.1f} vs {public:.1f})")

    def test_an_unchanged_analysis_is_reused_and_sheets_are_counted_once(self) -> None:
        project, first = self._analyze("reuse")
        still = project / "analysis" / "stills" / "s00000.jpg"
        stamp = still.stat().st_mtime_ns
        project_again = create_project(self.root / "out", self.source, "reuse")
        second = analyze(project_again, self.source, budget="standard", tracks={"voice": 0, "game": 1}, layout=LAYOUT,
                         masks={"right": self.mask}, transcript=self.transcript, ffmpeg=FFMPEG, ffprobe=FFPROBE)
        self.assertEqual(second, first)
        self.assertEqual(still.stat().st_mtime_ns, stamp, "no still is taken again")
        self.assertEqual(usage_report(project)["totals"], {"contact sheets prepared for the AI editor": 1})

    def test_talk_and_loudness_come_from_the_shared_decode(self) -> None:
        # 226: one read of the recording through the shared decoder; the levels keep their 0-based keys
        # (cut points look the voice track up by them) and talk is the voice track's shared activity.
        _project, data = self._analyze("shared-levels")
        self.assertEqual(sorted(data["loudness_per_second"]), ["0", "1"])
        self.assertEqual(len(data["loudness_per_second"]["0"]), 40)
        # The tone sounds 5-8 s and 25-28 s; its last 50 ms frame starts at 8.0 s, so the whole seconds
        # that hold speech run to 9 s.
        self.assertEqual(data["talking"], [{"start": 5, "end": 9}, {"start": 25, "end": 29}])
        self.assertEqual(data["voice_talk_threshold_dbfs"], -50.0)
        self.assertEqual(data["activity"]["region"], "whole frame")
        self.assertEqual(data["activity"]["signals"]["game_picture"]["status"], "measured")
        self.assertNotIn("tracks", data["settings"], "the stills do not depend on the tracks")
        self.assertEqual(data["engine"]["tracks"], {"voice": 0, "game": 1})

    def test_when_only_the_engine_changes_the_stills_and_sheets_are_kept(self) -> None:
        # 226: a transcript written again (another word list, say) redoes everything but the pictures.
        project, first = self._analyze("engine-change")
        still, sheet = project / "analysis" / "stills" / "s00000.jpg", project / "analysis" / "sheets" / "sheet-01.jpg"
        stamps = (still.stat().st_mtime_ns, sheet.stat().st_mtime_ns)
        other = self.root / "narration-again.json"
        other.write_text(json.dumps({"segments": [{"start": 25.0, "end": 28.0, "text": "Into the pits next lap."}]}),
                         encoding="utf-8")
        second = analyze(project, self.source, budget="standard", tracks={"voice": 0, "game": 1}, layout=LAYOUT,
                         masks={"right": self.mask}, transcript=other, ffmpeg=FFMPEG, ffprobe=FFPROBE)
        self.assertNotEqual(second["engine"], first["engine"])
        self.assertEqual((still.stat().st_mtime_ns, sheet.stat().st_mtime_ns), stamps, "no still or sheet is made again")
        self.assertEqual(second["sheets"], first["sheets"])
        self.assertEqual(usage_report(project)["totals"], {"contact sheets prepared for the AI editor": 1},
                         "the sheets are not counted again")
        digest = (project / "analysis" / "digest.md").read_text(encoding="utf-8")
        self.assertIn("[00:25] Into the pits next lap.", digest)
        self.assertNotIn("Here we go", digest)

    def test_an_analysis_made_before_wave_7_keeps_its_stills(self) -> None:
        project, first = self._analyze("before-wave-7")
        index = project / "analysis" / "analysis.json"
        older = json.loads(index.read_text(encoding="utf-8"))
        for key in ("engine", "activity", "voice_talk_threshold_dbfs", "game_speech_left_out"):
            older.pop(key)
        older["settings"].update({"tracks": {"voice": 0, "game": 1}, "transcript": str(self.transcript), "game_speech": ""})
        index.write_text(json.dumps(older), encoding="utf-8")
        still = project / "analysis" / "stills" / "s00000.jpg"
        stamp = still.stat().st_mtime_ns
        again = self._rerun(project, {"right": self.mask})
        self.assertEqual(still.stat().st_mtime_ns, stamp)
        self.assertEqual(again["settings"], first["settings"])
        self.assertEqual(again["engine"], first["engine"])
        self.assertEqual(usage_report(project)["totals"], {"contact sheets prepared for the AI editor": 1})

    def _gray(self, image: Path) -> bytes:
        return subprocess.run([FFMPEG, "-v", "error", "-i", str(image), "-vf", "format=gray", "-f", "rawvideo", "-"],
                              capture_output=True, check=True).stdout

    def _rerun(self, project: Path, masks: dict, budget: str = "standard") -> dict:
        return analyze(project, self.source, budget=budget, tracks={"voice": 0, "game": 1}, layout=LAYOUT,
                       masks=masks, transcript=self.transcript, ffmpeg=FFMPEG, ffprobe=FFPROBE)

    def test_adding_or_changing_a_mask_takes_every_still_again(self) -> None:
        project = create_project(self.root / "out", self.source, "mask-change")
        still = project / "analysis" / "stills" / "s00001.jpg"
        self._rerun(project, {})
        gray = self._gray(still)
        self.assertGreater(_detail(gray, 1920, 1300, 1580, 40, 320), 10, "without a mask the camera is sharp")

        data = self._rerun(project, {"right": self.mask})
        gray = self._gray(still)
        private, public = _detail(gray, 1920, 1300, 1580, 40, 320), _detail(gray, 1920, 1620, 1900, 40, 320)
        self.assertTrue(data["privacy_masked"])
        self.assertLess(private, public / 5, f"a mask added later blurs the stills ({private:.1f} vs {public:.1f})")

        moved = self.root / "moved" / "right-mask.png"
        moved.parent.mkdir(exist_ok=True)
        subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi",
                        "-i", "color=black:s=320x180,drawbox=x=160:y=0:w=160:h=180:color=white:t=fill",
                        "-frames:v", "1", str(moved)], check=True)
        self._rerun(project, {"right": moved})
        gray = self._gray(still)
        left_half, right_half = _detail(gray, 1920, 1300, 1580, 40, 320), _detail(gray, 1920, 1620, 1900, 40, 320)
        self.assertLess(right_half, left_half / 5,
                        f"a mask changed under the same name is applied ({right_half:.1f} vs {left_half:.1f})")

    def test_changing_the_budget_takes_the_stills_again_at_the_new_spacing(self) -> None:
        project = create_project(self.root / "out", self.source, "budget-change")
        self._rerun(project, {"right": self.mask}, budget="standard")
        self._rerun(project, {"right": self.mask}, budget="thorough")
        # Thorough takes a still every 5 s, so still 3 is at 15 s, before the story panel turns red at 20 s.
        rgb = subprocess.run([FFMPEG, "-v", "error", "-i", str(project / "analysis" / "stills" / "s00003.jpg"),
                              "-vf", "crop=200:200:860:80,scale=1:1,format=rgb24", "-f", "rawvideo", "-"],
                             capture_output=True, check=True).stdout
        self.assertFalse(rgb[0] > 200 and rgb[1] < 60 and rgb[2] < 60, f"still 3 is from 15 s, not 30 s ({list(rgb)})")

    def test_the_opening_pictures_are_capped_by_the_budget(self) -> None:
        two_hours = 7200.0
        for budget, sheets in (("light", 6), ("standard", 12), ("thorough", 24)):
            interval = still_interval(two_hours, budget)
            stills = len(range(0, int(two_hours), interval))
            self.assertLessEqual(stills, sheets * 36, f"{budget}: {stills} stills at {interval} s")
            # Whole-second spacing can leave the last sheet unused, never more.
            self.assertGreater(stills, (sheets - 2) * 36, f"{budget} uses its allowance, not far less")
        self.assertEqual(still_interval(2785.0, "standard"), 10, "a 46-minute race keeps the usual spacing")
        project, data = self._analyze("cap", budget="light")
        self.assertEqual(data["max_sheets"], 6)
        wide = create_project(self.root / "out", self.source, "cap-wide")
        with patch.dict(BUDGETS["light"], {"max_sheets": 0.05}):
            widened = self._rerun(wide, {"right": self.mask}, "light")
        self.assertGreater(widened["still_interval"], 15)
        self.assertLessEqual(widened["stills"], 2)
        digest = (wide / "analysis" / "digest.md").read_text(encoding="utf-8")
        self.assertIn("widened from 15 s", digest)

    def test_full_width_and_cropped_views_blur_the_cameras(self) -> None:
        project, _ = self._analyze("render-views", budget="thorough")
        timeline = {"schema": SCHEMA, "source": str(self.source), "source_layout": LAYOUT, "tracks": {"voice": 0, "game": 1},
                    "scenes": [{"id": "s01", "beat": "wide", "reason": "test", "in": 10.0, "out": 12.0, "view": "full",
                                "audio": {"voice": 0.0, "game": 1.0}},
                               {"id": "s02", "beat": "crop", "reason": "test", "in": 12.0, "out": 14.0,
                                "view": {"crop": [560, 0, 400, 180]}, "audio": {"voice": 0.0, "game": 1.0}}]}
        version = add_version(project, timeline, source_duration=40.0, audio_streams=2)
        report = render_version(project, version, "preview", RenderOptions(
            ffmpeg=FFMPEG, ffprobe=FFPROBE, masks={"right": self.mask}, encoder="x264", hwaccel="none"))
        video = Path(report["output"])

        def frame(at: float) -> bytes:
            return subprocess.run([FFMPEG, "-v", "error", "-ss", str(at), "-i", str(video), "-frames:v", "1",
                                   "-vf", "format=gray", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout

        # Full width: the 960x180 frame becomes 1280x240 in a 1280x720 picture (y 240-480); the right
        # camera is x 853-1280, its private half x 853-1067.
        gray = frame(1.0)
        private, public = _detail(gray, 1280, 870, 1050, 270, 450), _detail(gray, 1280, 1085, 1265, 270, 450)
        self.assertGreater(public, 10, f"the public half keeps its checkerboard ({public:.1f})")
        self.assertLess(private, public / 5, f"a full-width view blurs the camera ({private:.1f} vs {public:.1f})")
        # Crop x 560-960 fills 1280 px: the private half (x 640-800) is x 256-768, the public half x 768-1280.
        gray = frame(3.0)
        private, public = _detail(gray, 1280, 280, 740, 60, 660), _detail(gray, 1280, 790, 1260, 60, 660)
        self.assertGreater(public, 10, f"the public half keeps its checkerboard ({public:.1f})")
        self.assertLess(private, public / 5, f"a crop over a camera blurs it ({private:.1f} vs {public:.1f})")

    def test_a_review_round_takes_its_stills_from_the_latest_render(self) -> None:
        project, _ = self._analyze("review-fresh", budget="thorough")
        timeline = {"schema": SCHEMA, "source": str(self.source), "source_layout": LAYOUT, "tracks": {"voice": 0, "game": 1},
                    "scenes": [{"id": "s01", "beat": "face", "reason": "test", "in": 10.0, "out": 22.0, "view": "right",
                                "audio": {"voice": 0.0, "game": 1.0}}]}
        version = add_version(project, timeline, source_duration=40.0, audio_streams=2)
        options = {"ffmpeg": FFMPEG, "ffprobe": FFPROBE, "encoder": "x264", "hwaccel": "none"}
        render_version(project, version, "preview", RenderOptions(masks={}, **options))
        review_kit(project, version, ffmpeg=FFMPEG, transcribe=False)
        render_version(project, version, "preview", RenderOptions(masks={"right": self.mask}, **options))
        review_kit(project, version, ffmpeg=FFMPEG, transcribe=False)
        # A still every 6 s on the thorough budget; still 1 is 6 s in, clear of the fade from black.
        gray = self._gray(version_dir(project, version) / "review" / "stills" / "s00001.jpg")
        private, public = _detail(gray, 1280, 40, 600, 60, 660), _detail(gray, 1280, 680, 1240, 60, 660)
        self.assertLess(private, public / 5, f"the second round sees the masked render ({private:.1f} vs {public:.1f})")

    def test_close_looks_stop_at_the_budget_unless_the_operator_overrides(self) -> None:
        project, _ = self._analyze("looks", budget="light")
        for _ in range(4):
            look = close_look(project, 18, 22, 1, "center", masks={"right": self.mask}, ffmpeg=FFMPEG)
            self.assertTrue(Path(look["sheet"]).exists())
        with self.assertRaisesRegex(BudgetExceeded, "light budget allows 4 close looks"):
            close_look(project, 18, 22, 1, "center", masks={"right": self.mask}, ffmpeg=FFMPEG)
        close_look(project, 18, 22, 1, "center", masks={"right": self.mask}, ffmpeg=FFMPEG, override=True)
        self.assertEqual(usage_report(project)["totals"]["close-look sheets"], 5)

    def test_a_zoomed_look_is_full_resolution_and_still_privacy_masked(self) -> None:
        project, _ = self._analyze("region")
        look = close_look(project, 10, 12, 1, "right", masks={"right": self.mask}, ffmpeg=FFMPEG, region=[0, 0, 320, 180])
        self.assertTrue(Path(look["sheet"]).exists())
        still = Path(look["sheet"]).parent / "stills" / "s00000.jpg"
        size = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(still)],
                              capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(size, "320,180", "the region is taken at the recording's own resolution")
        gray = subprocess.run([FFMPEG, "-v", "error", "-i", str(still), "-vf", "format=gray", "-f", "rawvideo", "-"],
                              capture_output=True, check=True).stdout
        private, public = _detail(gray, 320, 10, 150, 20, 160), _detail(gray, 320, 170, 310, 20, 160)
        self.assertLess(private, public / 5, f"the private half stays blurred ({private:.1f} vs {public:.1f})")
        moments = close_look(project, 0, 0, 1, "center", masks={}, ffmpeg=FFMPEG, region=[0, 0, 320, 180],
                             times=[3.0, 21.5, 33.0])
        self.assertEqual(moments["times"], [3.0, 21.5, 33.0], "a zoomed look can take exact moments")
        with self.assertRaisesRegex(ValueError, "outside the right panel"):
            close_look(project, 10, 12, 1, "right", masks={}, ffmpeg=FFMPEG, region=[300, 0, 100, 100])

    def test_a_cut_where_the_microphone_is_silent_is_not_a_word_cut(self) -> None:
        # 176: Whisper stretched "I'm" across seconds of silence, and a silent cut was flagged.
        # The voice track sounds from 5 to 8 s. The cut at 6.5 s is inside a word; the cut at
        # 8.6 s is in silence although the stretched word's timing straddles it.
        project, _ = self._analyze("cut-silence")
        timeline = {"schema": SCHEMA, "source": str(self.source), "source_layout": LAYOUT, "tracks": {"voice": 0, "game": 1},
                    "scenes": [{"id": "s01", "beat": "talk", "reason": "test", "in": 6.5, "out": 8.6, "view": "center",
                                "audio": {"voice": 1.0, "game": 0.5}}]}
        version = add_version(project, timeline, source_duration=40.0, audio_streams=2)
        heard = {"s01-in.wav": ("Here", 6.0, 7.0), "s01-out.wav": ("I'm", 7.5, 10.5)}

        class Model:
            def transcribe(self, path, **_options):
                name = Path(path).name
                word, start, end = heard[name]
                offset = (6.5 if name == "s01-in.wav" else 8.6) - 4.0
                return {"segments": [{"words": [{"word": word, "start": start - offset, "end": end - offset}]}]}

        class Whisper:
            # 226: Whisper stands in through sys.modules, so the shared Whisper loader itself runs.
            @staticmethod
            def load_model(name, device=None):
                return Model()

        with patch.dict(sys.modules, {"whisper": Whisper()}):
            report = cut_points(project, version, ffmpeg=FFMPEG, whisper={"prefer_gpu": False, "language_code": "en"})
        by_edge = {entry["edge"]: entry for entry in report}
        self.assertEqual(by_edge["in"]["cuts_a_word"], "Here", "a cut while the microphone sounds is still flagged")
        self.assertEqual(by_edge["out"]["cuts_a_word"], "", "a silent cut is not flagged")
        self.assertTrue(by_edge["out"]["microphone_silent_at_cut"])

    def test_the_level_at_a_moment_is_measured_from_the_sound_itself(self) -> None:
        wav = self.root / "level.wav"
        subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi",
                        "-i", "sine=frequency=300:sample_rate=16000:duration=4,volume='if(lt(t,2),1,0)':eval=frame",
                        "-ac", "1", "-c:a", "pcm_s16le", str(wav)], check=True)
        self.assertGreater(level_at(wav, 1.0), -30, "FFmpeg's test tone is about -21 dB")
        self.assertLess(level_at(wav, 3.0), -90)

    def test_review_rounds_are_counted_per_version_and_capped(self) -> None:
        project, _ = self._analyze("review", budget="light")
        timeline = {"schema": SCHEMA, "source": str(self.source), "source_layout": LAYOUT, "tracks": {"voice": 0, "game": 1},
                    "scenes": [{"id": "s01", "beat": "talk", "reason": "test", "in": 4.0, "out": 9.0, "view": "center",
                                "audio": {"voice": 1.0, "game": 0.5}},
                               {"id": "s02", "beat": "spike", "reason": "test", "in": 29.0, "out": 33.0, "view": "right",
                                "audio": {"voice": 0.0, "game": 1.0}, "transition_in": "dissolve", "transition_dur": 0.5}]}
        version = add_version(project, timeline, source_duration=40.0, audio_streams=2)
        render_version(project, version, "preview", RenderOptions(ffmpeg=FFMPEG, ffprobe=FFPROBE, masks={"right": self.mask},
                                                                   encoder="x264", hwaccel="none"))
        kit = review_kit(project, version, ffmpeg=FFMPEG, transcribe=False)
        self.assertEqual([row["id"] for row in kit["pacing"]], ["s01", "s02"])
        self.assertEqual(kit["pacing"][1]["at"], 4.5, "the dissolve overlaps the scenes")
        self.assertTrue(all(Path(s).exists() for s in kit["sheets"]))
        with self.assertRaisesRegex(BudgetExceeded, "light budget allows 1 review rounds"):
            review_kit(project, version, ffmpeg=FFMPEG, transcribe=False)
        report = usage_report(project)
        self.assertEqual(report["by_version"]["v001"]["review rounds"], 1)

    def test_the_prompt_states_model_effort_and_mode_by_budget_with_full_paths(self) -> None:
        project, _ = self._analyze("prompt", budget="light")
        python = r"C:\Python\python.exe"
        src = Path(r"C:\App\python-core\src")
        claude = build_prompt(project, tool="claude", python=python, src_root=src)
        codex = build_prompt(project, tool="codex", python=python, src_root=src)
        self.assertEqual(claude.splitlines()[:3], ["MODEL: Opus 5.5", "EFFORT: high", "MODE: AUTO — execute to completion"])
        self.assertEqual(codex.splitlines()[:3], ["MODEL: GPT-6.1 Sol", "EFFORT: medium", "MODE: AUTO — execute to completion"])
        self.assertIn(str(project / "analysis" / "digest.md"), claude)
        self.assertIn("brief.md", claude)
        self.assertIn(python, claude)
        self.assertIn("Do not upload, publish", claude)
        (project / "feedback").mkdir(exist_ok=True)
        revision = build_prompt(project, tool="claude", python=python, src_root=src, feedback_version=1)
        self.assertIn(str(project / "feedback" / "v001.md"), revision)


if __name__ == "__main__":
    unittest.main()
