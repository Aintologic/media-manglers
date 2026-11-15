"""Wave 7 (226): the AI editor's review tools on the shared engine, and the guards on its commands.

Real FFmpeg on small synthetic recordings made with lavfi, through the real race-video handlers and
the real command line. Whisper is not in the test runtime: it stands in through sys.modules, so the
shared Whisper helper and the shared Whisper loader themselves run.

- Privacy (decision F): a request always gets the operator's stored masks; the two commands that
  could change a mask or take an unblurred camera picture refuse; a layout that would move or miss a
  masked camera is refused by every command, and again when a render starts.
- Tracks (decision A): an edit can only use the voice and game tracks Prepare chose.
- The AI editor's own label for a version, and dead time pointed out in the edit (decision D).
- The review kit and the cut points: the quick passes' Whisper model with the operator's settings.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers import cli  # noqa: E402
from media_manglers.core import cross_track_check  # noqa: E402
from media_manglers.core import voice_track  # noqa: E402
from media_manglers.core.race_video import analysis as analysis_module, library, privacy, prompt, review  # noqa: E402
from media_manglers.core.race_video import render as render_module  # noqa: E402
from media_manglers.core.race_video import requests as race_requests  # noqa: E402
from media_manglers.core.race_video.analysis import analyze, clock  # noqa: E402
from media_manglers.core.race_video.project import add_version, create_project, editor_layout, version_dir  # noqa: E402
from media_manglers.core.race_video.render import RenderOptions, render_version  # noqa: E402
from media_manglers.core.race_video.timeline import SCHEMA  # noqa: E402
from media_manglers.core.scratch import scratch_root  # noqa: E402
from media_manglers.core.spelling_words import SETTING_KEY as WORDS_KEY  # noqa: E402
from media_manglers.core.user_folders import settings_root  # noqa: E402
from media_manglers.providers import whisper_local  # noqa: E402
from tests.test_race_video_prepare import (  # noqa: E402
    NAMED,
    NEVER_GAME_REFUSAL,
    NEVER_ROLES,
    OBS_SIX,
    OLDER_ROLES,
    SENTENCES,
    SINGLE,
    FakeWhisper,
    _CpuTorch,
    editor_recording,
)
from tests.whisper_test_models import checked_whisper, whisper_gets_file_names  # noqa: E402

# H2 of the Wave I-A review: these Whisper stand-ins answer by the file they are given; see whisper_gets_file_names.
_FILE_NAMES = whisper_gets_file_names()


def setUpModule() -> None:  # noqa: N802 - unittest's name
    _FILE_NAMES.start()


def tearDownModule() -> None:  # noqa: N802 - unittest's name
    _FILE_NAMES.stop()

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
THREE = {"width": 960, "height": 180,
         "panels": {"left": [0, 0, 320, 180], "center": [320, 0, 320, 180], "right": [640, 0, 320, 180]}}
# The right camera has the operator's mask; these move it, leave it out, or change the frame size.
MOVED = {**THREE, "panels": {**THREE["panels"], "right": [600, 0, 320, 180]}}
DROPPED = {**THREE, "panels": {"left": [0, 0, 320, 180], "center": [320, 0, 320, 180]}}
RESIZED = {**THREE, "width": 1920}
# Only the unmasked left camera differs: allowed.
LEFT_ONLY = {**THREE, "panels": {**THREE["panels"], "left": [0, 0, 300, 180]}}
# A second name for the masked right camera, and a panel as wide as the frame: each would show the
# right camera through no mask of its own.
ALIAS = {**THREE, "panels": {**THREE["panels"], "cam": [640, 0, 320, 180]}}
WIDE = {**THREE, "panels": {**THREE["panels"], "wide": [0, 0, 960, 180]}}


def detail(picture: Path, at: float | None, box: tuple[int, int, int, int]) -> float:
    """How sharp a part ([x, y, w, h]) of a picture, or of a video's frame at ``at`` seconds, is: the
    mean difference between neighbouring pixels in a row, in gray levels. The right camera is a
    checkerboard of 4-pixel squares, so sharp it gives tens; blurred through its mask, about 0."""

    x, y, w, h = box
    command = [FFMPEG, "-hide_banner", "-v", "error"]
    if at is not None:
        command += ["-ss", f"{at:.2f}"]
    command += ["-i", str(picture), "-frames:v", "1", "-vf", f"crop={w}:{h}:{x}:{y},format=gray", "-f", "rawvideo", "-"]
    raw = subprocess.run(command, capture_output=True, check=True).stdout
    rows = [raw[row * w:(row + 1) * w] for row in range(h)]
    return sum(abs(line[i] - line[i + 1]) for line in rows for i in range(w - 1)) / (h * (w - 1))


def three_panel_recording(path: Path, seconds: int = 12) -> Path:
    """Three different 320x180 panels side by side, a keyframe every 2 s, a narration track (a tone
    from 2 to 5 s) and a game track (pink noise), named so Prepare finds them by their names."""

    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        FFMPEG, "-hide_banner", "-v", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc2=s=320x180:r=10:d={seconds}",
        "-f", "lavfi", "-i", f"testsrc=s=320x180:r=10:d={seconds}",
        "-f", "lavfi", "-i", f"nullsrc=s=320x180:r=10:d={seconds},geq=lum='if(mod(floor(X/4)+floor(Y/4),2),235,16)':cb=128:cr=128",
        "-f", "lavfi", "-i", f"sine=frequency=300:sample_rate=48000:duration={seconds},volume='if(between(t,2,5),1,0)':eval=frame",
        "-f", "lavfi", "-i", f"anoisesrc=color=pink:amplitude=0.05:sample_rate=48000:duration={seconds}",
        "-filter_complex", "[0:v][1:v][2:v]hstack=inputs=3,format=yuv420p[v]",
        "-map", "[v]", "-map", "3:a", "-map", "4:a", "-c:v", "libx264", "-preset", "ultrafast", "-g", "20",
        "-c:a", "flac", "-metadata:s:a:0", "title=T1 - Narration", "-metadata:s:a:1", "title=T2 - Game",
        "-t", str(seconds), str(path),
    ], check=True)
    return path


def talk_recording(path: Path, seconds: int = 30) -> Path:
    """One 320x180 picture; the voice track speaks (a tone) from 5 to 8 s only; the game is pink noise."""

    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        FFMPEG, "-hide_banner", "-v", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc2=s=320x180:r=10:d={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=300:sample_rate=48000:duration={seconds},volume='if(between(t,5,8),1,0)':eval=frame",
        "-f", "lavfi", "-i", f"anoisesrc=color=pink:amplitude=0.05:sample_rate=48000:duration={seconds}",
        "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "flac",
        "-t", str(seconds), str(path),
    ], check=True)
    return path


def scene(scene_id: str, start: float, end: float, **extra) -> dict:
    return {"id": scene_id, "beat": "test", "reason": "test", "in": start, "out": end, "view": "center",
            "audio": {"voice": 1.0, "game": 0.5}, **extra}


def timeline(source: Path, scenes: list[dict], **extra) -> dict:
    return {"schema": SCHEMA, "source": str(source), "tracks": {"voice": 0, "game": 1}, "scenes": scenes, **extra}


def run_cli(root: Path, command: str, payload: dict) -> tuple[int, dict]:
    request, result = root / f"{command}-request.json", root / f"{command}-result.json"
    request.write_text(json.dumps({"payload": payload}), encoding="utf-8")
    code = cli.main([command, "--request-file", str(request), "--result-file", str(result)])
    return code, json.loads(result.read_text(encoding="utf-8"))


OPTIONS = {"encoder": "x264", "hwaccel": "none"}


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class EditorTestCase(unittest.TestCase):
    """A synthetic three-panel recording, the operator's mask for its right camera, and a store of the
    test's own (the operator's real masks are never read)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.class_temp = tempfile.TemporaryDirectory()
        root = Path(cls.class_temp.name)
        cls.source = three_panel_recording(root / "race.mkv")
        cls.mask = root / "right-mask.png"
        subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi",
                        "-i", "color=black:s=320x180,drawbox=x=0:y=0:w=160:h=180:color=white:t=fill",
                        "-frames:v", "1", str(cls.mask)], check=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.class_temp.cleanup()

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self._settings = mock.patch.dict(os.environ, {"MEDIA_MANGLERS_WORKBENCH_APPDATA": str(self.root / "appdata")})
        self._settings.start()

    def tearDown(self) -> None:
        self._settings.stop()
        self.temp.cleanup()

    def save_settings(self, **settings) -> None:
        path = self.root / "appdata" / "MediaManglers" / "workbench" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schemaVersion": 1, "settings": settings}), encoding="utf-8")

    def prepare(self, source: Path | None = None, **extra) -> Path:
        payload = {"source": str(source or self.source), "output_root": str(self.root / "out"), "budget": "light",
                   "layout": THREE, "skip_transcript": True, "track_roles": "", "ffmpeg": FFMPEG, "ffprobe": FFPROBE,
                   **extra}
        with contextlib.redirect_stdout(io.StringIO()):
            return Path(race_requests.prepare_from_request(payload)["project"])

    def masked(self):
        """The operator has drawn a mask for the right camera (in a store of this test's own)."""

        store = self.root / "privacy"
        if not (store / "masks.json").exists():
            privacy.save_mask("right", self.mask, store)
        return mock.patch.dict(os.environ, {"MEDIA_MANGLERS_RACE_VIDEO_PRIVACY": str(store)})


class PrivacyGuardTests(EditorTestCase):
    """Decision F: the AI editor's commands cannot switch the camera blur off or move it."""

    def test_the_test_run_never_reads_the_operators_masks(self) -> None:
        store = os.environ.get("MEDIA_MANGLERS_RACE_VIDEO_PRIVACY", "")
        self.assertTrue(store, "tests/conftest.py points the mask store at a folder of the run's own")
        self.assertNotEqual(privacy.default_store(), settings_root() / "MediaManglers" / "race-video" / "privacy")
        self.assertTrue(privacy.default_store().resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()),
                        privacy.default_store())

    def test_a_request_always_gets_the_stored_masks(self) -> None:
        extra = self.root / "extra-centre.png"
        extra.write_bytes(b"png stand-in")
        with self.masked():
            stored = privacy.load_masks()
            self.assertEqual(sorted(stored), ["right"])
            cases = {
                "nothing said": {},
                "an empty set": {"privacy_masks": {}},
                "an empty name for the stored camera": {"privacy_masks": {"right": "", "left": ""}},
                "another mask in the stored one's place": {"privacy_masks": {"right": str(extra)}},
                "an empty store named instead": {"privacy_store": str(self.root / "empty-store")},
            }
            for case, payload in cases.items():
                with self.subTest(case=case):
                    self.assertEqual(race_requests._masks(payload), stored)
            self.assertEqual(race_requests._masks({"privacy_masks": {"center": str(extra)}}),
                             {**stored, "center": extra}, "a request may add a mask for another camera")

    def test_the_command_line_cannot_save_a_mask_or_take_an_unblurred_still(self) -> None:
        project = create_project(self.root / "out", self.source, "race")
        with self.masked():
            store = privacy.default_store()
            before = {path.name: path.read_bytes() for path in store.iterdir()}
            blank = self.root / "blank.png"
            blank.write_bytes(b"not a mask")
            for payload in ({"panel": "right", "image": str(blank)},
                            {"panel": "right", "image": str(blank), "privacy_store": str(self.root / "other")}):
                with self.subTest(payload=sorted(payload)):
                    code, result = run_cli(self.root, "race-video-save-mask", payload)
                    self.assertEqual(code, 1)
                    self.assertIn("only the operator draws privacy masks", result["error"])
            self.assertEqual({path.name: path.read_bytes() for path in store.iterdir()}, before, "the stored mask is kept")
            self.assertFalse((self.root / "other").exists())
            code, result = run_cli(self.root, "race-video-panel-still", {"project": str(project), "panel": "right", "at": 2})
        self.assertEqual(code, 1)
        self.assertIn("an unblurred camera picture is only for the operator's mask editor", result["error"])
        self.assertFalse((project / "masks").exists(), "no unblurred picture in the project the AI reads")

    def test_the_first_prepare_refuses_a_layout_that_misses_a_masked_camera(self) -> None:
        # The masks are drawn on the editor's three-screen layout; a new project may not fix another.
        with self.masked(), self.assertRaises(ValueError) as caught:
            self.prepare(layout=THREE)
        self.assertIn("the request's layout does not match the camera layout", str(caught.exception))
        self.assertIn("it is 960x180, not 5760x1080", str(caught.exception))
        self.assertFalse((self.root / "out" / "race-videos" / "race" / "analysis" / "analysis.json").exists())

    def test_a_timeline_gets_the_projects_layout_and_may_not_move_a_masked_camera(self) -> None:
        project = self.prepare()
        with self.masked():
            number = add_version(project, timeline(self.source, [scene("s01", 1.0, 4.0)]), source_duration=12.0)
            stored = json.loads((version_dir(project, number) / "timeline.json").read_text(encoding="utf-8"))
            self.assertEqual(stored["source_layout"], THREE, "a timeline without a layout gets the project's")
            for name, layout, words in (("moved", MOVED, "it moves the right camera, which has a privacy mask"),
                                        ("dropped", DROPPED, "it leaves out the right camera"),
                                        ("resized", RESIZED, "it is 1920x180, not 960x180")):
                with self.subTest(layout=name), self.assertRaises(ValueError) as caught:
                    add_version(project, timeline(self.source, [scene("s01", 1.0, 4.0)], source_layout=layout))
                self.assertIn("the timeline's source_layout does not match the camera layout", str(caught.exception))
                self.assertIn(words, str(caught.exception))
            add_version(project, timeline(self.source, [scene("s01", 1.0, 4.0)], source_layout=LEFT_ONLY))

    def test_a_timeline_edited_by_hand_is_refused_when_the_render_starts(self) -> None:
        project = self.prepare()
        with self.masked():
            number = add_version(project, timeline(self.source, [scene("s01", 1.0, 3.0)]), source_duration=12.0)
            path = version_dir(project, number) / "timeline.json"
            good = json.loads(path.read_text(encoding="utf-8"))
            options = RenderOptions(ffmpeg=FFMPEG, ffprobe=FFPROBE, masks=privacy.load_masks(), **OPTIONS)
            for name, edited, words in (("layout", {**good, "source_layout": MOVED}, "it moves the right camera"),
                                        ("tracks", {**good, "tracks": {"voice": 1, "game": 0}},
                                         "an edit can only use the prepared tracks")):
                with self.subTest(edited=name):
                    path.write_text(json.dumps(edited), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, words):
                        render_version(project, number, "preview", options)
                    self.assertFalse((version_dir(project, number) / "renders" / "preview.mp4").exists())

    def test_a_request_layout_that_moves_a_masked_camera_is_refused_by_every_command(self) -> None:
        project = self.prepare()
        with self.masked():
            number = add_version(project, timeline(self.source, [scene("s01", 1.0, 3.0)]), source_duration=12.0)
            common = {"project": str(project), "ffmpeg": FFMPEG, "ffprobe": FFPROBE, "layout": MOVED, **OPTIONS}
            commands = {
                "race-video-analyze": (race_requests.analyze_from_request, {"source": str(self.source)}),
                "race-video-look": (race_requests.look_from_request, {"start": 1, "end": 3, "step": 1}),
                "race-video-review-kit": (race_requests.review_kit_from_request, {"version": number, "transcribe": False}),
                "race-video-render": (race_requests.render_from_request, {"version": number}),
                "race-video-export": (race_requests.export_from_request, {"version": number}),
            }
            for command, (handler, extra) in commands.items():
                with self.subTest(command=command), self.assertRaises(ValueError) as caught:
                    handler({**common, **extra})
                self.assertIn("the request's layout does not match the camera layout this project was prepared with",
                              str(caught.exception))
                self.assertIn("a request cannot change them", str(caught.exception))
            self.assertFalse((version_dir(project, number) / "renders").exists(), "nothing was rendered")
            self.assertFalse((project / "analysis" / "looks").exists(), "no close look was taken")

    def test_a_second_name_or_a_wide_panel_over_a_masked_camera_is_refused(self) -> None:
        project = self.prepare()
        with self.masked():
            for name, layout, editor_box in (("cam", ALIAS, [3840, 0, 1920, 1080]), ("wide", WIDE, [0, 0, 5760, 1080])):
                words = f"its {name} panel covers the right camera, which has a privacy mask"
                with self.subTest(panel=name, where="add-version"):
                    with self.assertRaises(ValueError) as caught:
                        race_requests.add_version_from_request({
                            "project": str(project), "ffprobe": FFPROBE,
                            "timeline": timeline(self.source, [scene("s01", 1.0, 3.0, view=name)], source_layout=layout)})
                    self.assertIn("the timeline's source_layout does not match the camera layout", str(caught.exception))
                    self.assertIn(words, str(caught.exception))
                # The masks are drawn on the editor's three-screen layout: this one keeps it and adds the panel.
                first = editor_layout()
                first["panels"][name] = editor_box
                with self.subTest(panel=name, where="first Prepare"):
                    with self.assertRaises(ValueError) as caught:
                        self.prepare(name=f"fresh-{name}", layout=first)
                    self.assertIn("the request's layout does not match the camera layout", str(caught.exception))
                    self.assertIn(words, str(caught.exception))
                    self.assertFalse((self.root / "out" / "race-videos" / f"fresh-{name}").exists(), "no project is left")
        self.assertEqual(json.loads((project / "project.json").read_text(encoding="utf-8"))["versions"], [])

    def test_a_panel_over_a_masked_camera_put_in_by_hand_is_refused_when_the_render_starts(self) -> None:
        project = self.prepare()
        with self.masked():
            number = add_version(project, timeline(self.source, [scene("s01", 1.0, 3.0)]), source_duration=12.0)
            path = version_dir(project, number) / "timeline.json"
            good = json.loads(path.read_text(encoding="utf-8"))
            for name, layout in (("cam", ALIAS), ("wide", WIDE)):
                with self.subTest(panel=name):
                    path.write_text(json.dumps({**good, "source_layout": layout,
                                                "scenes": [scene("s01", 1.0, 3.0, view=name)]}), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, f"its {name} panel covers the right camera"):
                        render_version(project, number, "preview", RenderOptions(ffmpeg=FFMPEG, ffprobe=FFPROBE, **OPTIONS))
                    self.assertFalse((version_dir(project, number) / "renders" / "preview.mp4").exists())

    def test_the_render_blurs_a_panel_over_a_masked_camera_even_past_the_guard(self) -> None:
        # The layout guard is skipped here on purpose: the render itself still blurs the right camera
        # wherever another panel shows it, as its own view, under a second name and in a wide panel.
        project = self.prepare()
        with self.masked():
            number = add_version(project, timeline(self.source, [scene("s01", 1.0, 3.0)]), source_duration=12.0)
            path = version_dir(project, number) / "timeline.json"
            good = json.loads(path.read_text(encoding="utf-8"))
            layout = {**THREE, "panels": {**THREE["panels"], "cam": [640, 0, 320, 180], "wide": [0, 0, 960, 180]}}
            path.write_text(json.dumps({**good, "source_layout": layout, "scenes": [
                scene("s01", 1.0, 3.0, view="right"), scene("s02", 3.0, 5.0, view="cam"),
                scene("s03", 5.0, 7.0, view="wide")]}), encoding="utf-8")
            options = RenderOptions(ffmpeg=FFMPEG, ffprobe=FFPROBE, masks=privacy.load_masks(), **OPTIONS)
            with mock.patch.object(render_module, "timeline_refusal", return_value=""):
                report = render_version(project, number, "preview", options)
        # 226: each scene's picture is in the project's scene store, named in the render report.
        scenes = {row["id"]: Path(row["picture"]["file"]) for row in report["scenes"]}
        # The camera on its own fills 1280x720: its private (left) half is x 0-640. In the wide view the
        # camera is x 853-1280, its private half x 853-1067.
        boxes = {"s01": ((40, 100, 560, 520), (680, 100, 560, 520)), "s02": ((40, 100, 560, 520), (680, 100, 560, 520)),
                 "s03": ((875, 100, 170, 520), (1090, 100, 170, 520))}
        for name, (private_box, public_box) in boxes.items():
            private, public = detail(scenes[name], 1.0, private_box), detail(scenes[name], 1.0, public_box)
            with self.subTest(scene=name):
                self.assertGreater(public, 10, f"the public half keeps its checkerboard ({public:.1f})")
                self.assertLess(private, public / 5, f"the private half is blurred ({private:.1f} vs {public:.1f})")
        self.assertEqual(report["privacy_masks_applied"], ["right"])
        self.assertEqual([row["picture"]["masks_applied"] for row in report["scenes"]], [["right"]] * 3)

    def test_a_close_look_at_a_panel_over_a_masked_camera_is_blurred(self) -> None:
        # A layout fixed before any mask was drawn may name the camera twice. Close looks, like every
        # still, are blurred through the whole-frame mask, so the second name shows it blurred too.
        project = self.prepare(layout=ALIAS)
        with self.masked():
            masks = privacy.load_masks()
            whole = review.close_look(project, 2.0, 3.0, 1.0, "cam", masks=masks, ffmpeg=FFMPEG, override=True)
            zoomed = review.close_look(project, 2.0, 3.0, 1.0, "cam", masks=masks, ffmpeg=FFMPEG, override=True,
                                       region=[0, 0, 320, 180], times=[2.0])
        # Whole panel: 320x180 tiles, the first in the top left (its time label over the top rows).
        private, public = (detail(Path(whole["sheet"]), None, (20, 40, 120, 130)),
                           detail(Path(whole["sheet"]), None, (180, 40, 120, 130)))
        self.assertGreater(public, 10, f"the public half keeps its checkerboard ({public:.1f})")
        self.assertLess(private, public / 5, f"the private half is blurred ({private:.1f} vs {public:.1f})")
        # A zoomed look: 640x360 tiles, the camera at twice its size.
        private, public = (detail(Path(zoomed["sheet"]), None, (40, 80, 240, 260)),
                           detail(Path(zoomed["sheet"]), None, (360, 80, 240, 260)))
        self.assertGreater(public, 10, f"the public half keeps its checkerboard ({public:.1f})")
        self.assertLess(private, public / 5, f"the private half is blurred ({private:.1f} vs {public:.1f})")

    def test_a_render_always_applies_the_stored_masks_and_says_which(self) -> None:
        project = self.prepare()
        number = add_version(project, timeline(self.source, [scene("s01", 1.0, 3.0, view="right")]), source_duration=12.0)
        with self.masked():
            stored = privacy.fingerprint(privacy.load_masks())
            # A caller that passes no masks, or another mask for the same camera, still gets the stored one.
            other = self.root / "nothing-private.png"
            subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=320x180",
                            "-frames:v", "1", str(other)], check=True)
            for name, masks in (("none passed", {}), ("another in its place", {"right": other})):
                with self.subTest(masks=name):
                    report = render_version(project, number, "preview",
                                            RenderOptions(ffmpeg=FFMPEG, ffprobe=FFPROBE, masks=masks, **OPTIONS))
                    self.assertEqual((report["privacy_masks"], report["privacy_masks_applied"]), (["right"], ["right"]))
                    self.assertEqual(report["privacy_store_fingerprint"], stored)
                    stored_report = json.loads((version_dir(project, number) / "renders" / "render-preview.json")
                                               .read_text(encoding="utf-8"))
                    self.assertEqual(stored_report["privacy_store_fingerprint"], stored)
                    scene_file = Path(report["scenes"][0]["picture"]["file"])
                    private, public = (detail(scene_file, 1.0, (40, 100, 560, 520)),
                                       detail(scene_file, 1.0, (680, 100, 560, 520)))
                    self.assertLess(private, public / 5, f"the private half is blurred ({private:.1f} vs {public:.1f})")


class TrackGuardTests(EditorTestCase):
    """Decision A: only the prepared voice and game tracks can reach a video."""

    def test_an_edit_can_only_use_the_prepared_tracks(self) -> None:
        project = self.prepare()
        self.assertEqual(json.loads((project / "project.json").read_text(encoding="utf-8"))["tracks"]["voice"], 0)
        for tracks in ({"voice": 1, "game": 0}, {"voice": 0, "game": 0}):
            with self.subTest(tracks=tracks), self.assertRaises(ValueError) as caught:
                race_requests.add_version_from_request({"project": str(project), "ffprobe": FFPROBE,
                                                        "timeline": timeline(self.source, [scene("s01", 1, 3)], tracks=tracks)})
            self.assertIn("This project was prepared with Track 1 as your voice and Track 2 as the game sound",
                          str(caught.exception))
            self.assertIn('"tracks": {"voice": 0, "game": 1}', str(caught.exception))
        result = race_requests.add_version_from_request({"project": str(project), "ffprobe": FFPROBE,
                                                         "timeline": timeline(self.source, [scene("s01", 1, 3)])})
        self.assertEqual(result["version"], 1)

    def test_a_project_never_prepared_takes_any_tracks(self) -> None:
        project = create_project(self.root / "out", self.source, "unprepared")
        self.assertEqual(add_version(project, timeline(self.source, [scene("s01", 1, 3)], source_layout=THREE,
                                                       tracks={"voice": 1, "game": 0})), 1)

    def test_a_game_track_named_music_is_refused_at_analyze_and_at_add_version(self) -> None:
        source = editor_recording(self.root / "music.mkv", [("narration", "T1 - Narration"), ("game", "T2 - Game"),
                                                            ("music", "T3 - Music")], seconds=8)
        folder = self.root / "out" / "race-videos" / "music"
        common = {"source": str(source), "output_root": str(self.root / "out"), "budget": "light", "layout": SINGLE,
                  "track_roles": "", "ffmpeg": FFMPEG, "ffprobe": FFPROBE}
        music = 'Track 3 ("T3 - Music") is named as sound that is never the game'
        with self.assertRaises(ValueError) as caught, contextlib.redirect_stdout(io.StringIO()):
            race_requests.analyze_from_request({**common, "tracks": {"voice": 0, "game": 2}})
        self.assertIn(music, str(caught.exception))
        self.assertFalse(folder.exists(), "the refused analysis made no project")
        for tracks, words in (({"voice": 0, "game": 2}, f"This timeline's game track cannot be used: {music}"),
                              ({"voice": 2, "game": 1}, "This timeline's voice track cannot be used: Track 3")):
            with self.subTest(tracks=tracks), self.assertRaises(ValueError) as caught:
                race_requests.add_version_from_request({
                    "output_root": str(self.root / "out"), "ffprobe": FFPROBE, "track_roles": "",
                    "timeline": timeline(source, [scene("s01", 1, 3)], tracks=tracks, source_layout=SINGLE)})
            self.assertIn(words, str(caught.exception))
            self.assertFalse(folder.exists(), "the refused version made no project")

        # Tracks that can be used are stored as chosen, and a later request cannot change them.
        with contextlib.redirect_stdout(io.StringIO()):
            race_requests.analyze_from_request({**common, "tracks": {"voice": 0, "game": 1}})
        self.assertEqual(json.loads((folder / "project.json").read_text(encoding="utf-8"))["tracks"],
                         {"voice": 0, "voice_decided_by": "override", "game": 1, "game_decided_by": "override"})
        with self.assertRaises(ValueError) as caught:
            race_requests.analyze_from_request({**common, "tracks": {"game": 2}})
        self.assertIn("an edit can only use the prepared tracks; this request uses Track 3 as the game sound",
                      str(caught.exception))
        roles = [row["role"] for row in json.loads((folder / "analysis" / "analysis.json").read_text(encoding="utf-8"))["tracks"]]
        self.assertEqual(roles, ["voice", "game", "unknown"], "the analysis keeps the stored tracks")
        result = race_requests.add_version_from_request({"project": str(folder), "ffprobe": FFPROBE, "track_roles": "",
                                                         "timeline": timeline(source, [scene("s01", 1, 3)])})
        self.assertEqual(result["version"], 1)

    def test_a_project_never_prepared_still_refuses_the_full_mix_or_music(self) -> None:
        source = editor_recording(self.root / "named.mkv", NAMED, seconds=6)
        project = create_project(self.root / "out", source, "unprepared")
        for tracks, words in (({"voice": 0, "game": 2}, "is the full mix"), ({"voice": 1, "game": 3}, "never the game"),
                              ({"voice": 1, "game": 0}, "is the full mix")):
            with self.subTest(tracks=tracks), self.assertRaisesRegex(ValueError, words):
                race_requests.add_version_from_request({
                    "project": str(project), "ffprobe": FFPROBE, "track_roles": "",
                    "timeline": timeline(source, [scene("s01", 1, 3)], tracks=tracks, source_layout=SINGLE)})
        self.assertEqual(json.loads((project / "project.json").read_text(encoding="utf-8"))["versions"], [])

    def test_a_game_track_the_setting_sets_as_never_narration_is_refused_at_analyze(self) -> None:
        # 226 (decision A): with the Narration track setting naming the game track, a track it sets as
        # Never narration is not the game sound.
        source = editor_recording(self.root / "obs.mkv", OBS_SIX, seconds=6)
        folder = self.root / "out" / "race-videos" / "obs"
        common = {"source": str(source), "output_root": str(self.root / "out"), "budget": "light", "layout": SINGLE,
                  "ffmpeg": FFMPEG, "ffprobe": FFPROBE}
        with self.assertRaises(ValueError) as caught, contextlib.redirect_stdout(io.StringIO()):
            race_requests.analyze_from_request({**common, "track_roles": NEVER_ROLES, "tracks": {"voice": 1, "game": 5}})
        self.assertEqual(str(caught.exception), NEVER_GAME_REFUSAL)
        self.assertFalse(folder.exists(), "the refused analysis made no project")

        # A setting with no game role (Never narration was the game track before Wave 6) still takes the pick.
        with contextlib.redirect_stdout(io.StringIO()):
            race_requests.analyze_from_request({**common, "track_roles": OLDER_ROLES, "tracks": {"voice": 1, "game": 5}})
        self.assertEqual(json.loads((folder / "project.json").read_text(encoding="utf-8"))["tracks"],
                         {"voice": 1, "voice_decided_by": "override", "game": 5, "game_decided_by": "override"})

    def test_a_game_track_the_setting_sets_as_never_narration_is_refused_at_add_version(self) -> None:
        # 226 (decision A): the same at add-version, for a project that was never prepared too.
        source = editor_recording(self.root / "obs-add.mkv", OBS_SIX, seconds=6)
        folder = self.root / "out" / "race-videos" / "obs-add"

        def add(roles: str, **where) -> dict:
            return race_requests.add_version_from_request({
                **where, "ffprobe": FFPROBE, "track_roles": roles,
                "timeline": timeline(source, [scene("s01", 1, 3)], tracks={"voice": 1, "game": 5}, source_layout=SINGLE)})

        unprepared = create_project(self.root / "out", source, "unprepared")
        for where in ({"output_root": str(self.root / "out")}, {"project": str(unprepared)}):
            with self.subTest(where=sorted(where)):
                with self.assertRaises(ValueError) as caught:
                    add(NEVER_ROLES, **where)
                self.assertEqual(str(caught.exception),
                                 f"This timeline's game track cannot be used: {NEVER_GAME_REFUSAL}")
        self.assertFalse(folder.exists(), "the refused version made no project")
        self.assertEqual(json.loads((unprepared / "project.json").read_text(encoding="utf-8"))["versions"], [])

        # A setting with no game role (Never narration was the game track before Wave 6) still takes the pick.
        self.assertEqual(add(OLDER_ROLES, project=str(unprepared))["version"], 1)

    def test_a_fresh_edit_keeps_what_prepare_fixed(self) -> None:
        project = self.prepare()
        fresh = library.start_fresh_edit(project)
        meta, fresh_meta = (json.loads((folder / "project.json").read_text(encoding="utf-8")) for folder in (project, fresh))
        self.assertEqual({key: fresh_meta[key] for key in ("tracks", "layout", "video")},
                         {key: meta[key] for key in ("tracks", "layout", "video")})
        with self.assertRaisesRegex(ValueError, "an edit can only use the prepared tracks"):
            add_version(fresh, timeline(self.source, [scene("s01", 1, 3)], tracks={"voice": 1, "game": 0}))


class EditorLabelTests(EditorTestCase):
    def test_the_ai_editors_label_is_kept_beside_the_version_label(self) -> None:
        project = self.prepare()
        code, result = run_cli(self.root, "race-video-add-version", {
            "project": str(project), "ffprobe": FFPROBE, "editor_label": "Claude Opus 5.5",
            "timeline": timeline(self.source, [scene("s01", 1, 3)])})
        self.assertEqual(code, 0, result)
        long_label = "Some Tool / with a very long model name, version 12"
        race_requests.add_version_from_request({"project": str(project), "ffprobe": FFPROBE, "editor_label": long_label,
                                                "timeline": timeline(self.source, [scene("s01", 1, 3)])})
        race_requests.add_version_from_request({"project": str(project), "ffprobe": FFPROBE,
                                                "timeline": timeline(self.source, [scene("s01", 1, 3)])})
        entries = json.loads((project / "project.json").read_text(encoding="utf-8"))["versions"]
        self.assertEqual(entries[0]["editor_label"], "claude-opus-5.5")
        self.assertEqual(entries[1]["editor_label"], "some-tool-with-a-very-long-model")
        self.assertLessEqual(len(entries[1]["editor_label"]), 32)
        self.assertNotIn("editor_label", entries[2], "no label given, none kept")
        versions = {item["version"]: item for item in library.project_summary(project)["versions"]}
        self.assertEqual((versions[1]["label"], versions[1]["editor_label"]), ("v001", "claude-opus-5.5"))
        self.assertEqual((versions[3]["label"], versions[3]["editor_label"]), ("v003", ""))

    def test_the_prompt_names_the_exact_label_for_its_tool_and_model(self) -> None:
        project = self.prepare()
        claude = prompt.build_prompt(project, tool="claude", python="python", src_root=self.root / "no-core")
        codex = prompt.build_prompt(project, tool="codex", python="python", src_root=self.root / "no-core", model="GPT-7 Nova")
        self.assertIn('pass "editor_label": "claude-opus-5.5"', claude)
        self.assertIn('pass "editor_label": "codex-gpt-7-nova"', codex)
        described = prompt.describe(project, {"codex": "GPT-7 Nova"})
        self.assertEqual((described["claude"]["editor_label"], described["codex"]["editor_label"]),
                         ("claude-opus-5.5", "codex-gpt-7-nova"))


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class DeadTimeTests(unittest.TestCase):
    """Decision D: scenes inside dead time are pointed out, as notes, never refused."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.class_temp = tempfile.TemporaryDirectory()
        root = Path(cls.class_temp.name)
        # The game picture stands still from 10 to 80 s while the game sound goes on.
        cls.source = editor_recording(root / "frozen.mkv", [("narration", "T1 - Narration"), ("engine", "T2 - Game")],
                                      seconds=100, frozen=(10, 80))
        payload = {"source": str(cls.source), "output_root": str(root / "out"), "budget": "light", "layout": SINGLE,
                   "skip_transcript": True, "track_roles": "", "ffmpeg": FFMPEG, "ffprobe": FFPROBE}
        with contextlib.redirect_stdout(io.StringIO()):
            cls.project = Path(race_requests.prepare_from_request(payload)["project"])
        activity = json.loads((cls.project / "analysis" / "analysis.json").read_text(encoding="utf-8"))["activity"]
        assert len(activity["idle_stretches"]) == 1, activity
        cls.idle = tuple(activity["idle_stretches"][0])

    @classmethod
    def tearDownClass(cls) -> None:
        cls.class_temp.cleanup()

    def add(self, scenes: list[dict]) -> dict:
        return race_requests.add_version_from_request({"project": str(self.project), "ffprobe": FFPROBE,
                                                       "timeline": timeline(self.source, scenes)})

    def test_adding_a_version_points_out_each_scene_in_dead_time(self) -> None:
        start, end = self.idle
        scenes = [scene("s01", 2.0, start - 2.0),          # before it
                  scene("s02", start + 5.0, start + 20.0),  # 15 s inside
                  scene("s03", end - 2.0, end + 4.0),       # 2 s of 6: not pointed out
                  scene("s04", end - 8.0, end - 1.0)]       # 7 s, all of it: pointed out
        result = self.add(scenes)
        dead = f"dead time {clock(start)}-{clock(end)} (picture still)"
        self.assertEqual(result["notes"], [
            f"scene s02 ({clock(start + 5)}-{clock(start + 20)}) has 15 s inside {dead}",
            f"scene s04 ({clock(end - 8)}-{clock(end - 1)}) has 7 s inside {dead}",
        ])
        self.assertTrue(Path(result["folder"], "timeline.json").exists(), "a note never stops the version")

    def test_the_review_kits_pacing_says_how_much_of_each_scene_is_dead_time(self) -> None:
        start, _end = self.idle
        result = self.add([scene("s01", 2.0, 5.0), scene("s02", start + 4.0, start + 7.0)])
        render_version(self.project, result["version"], "preview",
                       RenderOptions(ffmpeg=FFMPEG, ffprobe=FFPROBE, masks={}, **OPTIONS))
        kit = review.review_kit(self.project, result["version"], ffmpeg=FFMPEG, transcribe=False, override=True)
        rows = {row["id"]: row for row in kit["pacing"]}
        self.assertEqual((rows["s01"]["idle_seconds"], rows["s01"]["idle_by"]), (0, []))
        self.assertEqual((rows["s02"]["idle_seconds"], rows["s02"]["idle_by"]), (3.0, ["game_picture"]))
        stored = json.loads((Path(result["folder"]) / "review" / "pacing.json").read_text(encoding="utf-8"))
        self.assertEqual(stored, kit["pacing"])

    def test_without_an_analysis_of_dead_time_nothing_is_pointed_out(self) -> None:
        start, _end = self.idle
        scenes = [scene("s01", start + 5.0, start + 20.0)]
        self.assertEqual(review.dead_time_notes(timeline(self.source, scenes), None), [])
        self.assertEqual([(row["idle_seconds"], row["idle_by"]) for row in review.pacing(timeline(self.source, scenes))],
                         [(0, [])])


class ReviewKitTranscriptTests(EditorTestCase):
    """Decision C: the cut is written down by the shared Whisper helper, with the quick passes' model and
    the operator's device, language and word list, from sound decoded into the scratch folder."""

    def test_the_cut_is_written_down_by_the_shared_helper_with_the_operators_settings(self) -> None:
        project = self.prepare()
        number = add_version(project, timeline(self.source, [scene("s01", 1.0, 6.0, audio={"voice": 1.0, "game": 0.0})]),
                             source_duration=12.0)
        render_version(project, number, "preview", RenderOptions(ffmpeg=FFMPEG, ffprobe=FFPROBE, masks={}, **OPTIONS))
        self.save_settings(whisper_device="CPU", language="de", race_video_quick_whisper_model="medium",
                           whisper_model="large", **{WORDS_KEY: "Brooklands"})
        FakeWhisper.loads, FakeWhisper.heard = [], []
        with mock.patch.dict(sys.modules, {"whisper": checked_whisper(FakeWhisper()), "torch": _CpuTorch()}), \
                mock.patch.object(whisper_local, "transcribe_from_request",
                                  wraps=whisper_local.transcribe_from_request) as helper, \
                contextlib.redirect_stdout(io.StringIO()):
            kit = race_requests.review_kit_from_request({"project": str(project), "version": number, "ffmpeg": FFMPEG,
                                                         "language": "en"})
        self.assertEqual(helper.call_count, 1)
        request = helper.call_args.args[0]
        self.assertEqual((request["model_name"], request["prefer_gpu"], request["language_code"],
                          request["narration_speech_mode"], request["keep_short_reactions"]),
                         ("medium", False, "en", "Sparse", True), "a setting in the request wins over the saved one")
        self.assertEqual((request["initial_prompt"], request["glossary_entries"]),
                         ("Preferred terminology: Brooklands", ["Brooklands"]))
        self.assertEqual(FakeWhisper.loads, ["medium"])
        self.assertTrue(Path(request["audio_path"]).resolve().is_relative_to(scratch_root().resolve()),
                        "the cut's sound is decoded into the scratch folder")
        self.assertFalse(Path(request["audio_path"]).parent.exists(), "and removed afterwards")
        review_folder = version_dir(project, number) / "review"
        self.assertEqual(sorted(path.name for path in review_folder.iterdir() if path.is_file()),
                         ["cut-transcript.txt", "pacing.json", "sheet-01.jpg"])
        lines = Path(kit["cut_transcript"]).read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines, "the tone in the cut was heard")
        for line in lines:
            found = re.fullmatch(r"\[(\d\d:\d\d)\] (.+)", line)
            self.assertIsNotNone(found, line)
            self.assertIn(found.group(2), SENTENCES)

    def test_the_quick_model_is_the_setting_main_means_the_main_model_and_the_request_may_name_one(self) -> None:
        self.save_settings(race_video_quick_whisper_model="main", whisper_model="large", whisper_device="GPU")
        model, fields = race_requests._quick_whisper({})
        self.assertEqual((model, fields["prefer_gpu"], fields["language_code"]), ("large", True, "en"))
        self.assertEqual(race_requests._quick_whisper({"whisper_model": "tiny"})[0], "tiny",
                         "the review kit and cut points have always taken a whisper_model")
        self.save_settings()
        self.assertEqual(race_requests._quick_whisper({})[0], "small", "the quick passes stay on small by default")


class _WordModel:
    calls: list[tuple[str, dict]] = []

    def transcribe(self, path, **options) -> dict:
        _WordModel.calls.append((Path(path).name, options))
        # One word across the middle of the 8 s window, which is where the cut is.
        return {"language": "en", "segments": [{"words": [{"word": " Into", "start": 3.5, "end": 4.6}]}]}


class _WordWhisper:
    loads: list[tuple[str, str]] = []

    @staticmethod
    def load_model(name, device=None):
        _WordWhisper.loads.append((name, device))
        return _WordModel()


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class CutPointTests(unittest.TestCase):
    """The cut points hear their few seconds through the shared Whisper loader, only where the analysis
    heard the driver talk, cut from the recording with the one-seek window decoder."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.class_temp = tempfile.TemporaryDirectory()
        cls.source = talk_recording(Path(cls.class_temp.name) / "talk.mkv")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.class_temp.cleanup()

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = create_project(self.root / "out", self.source, "talk")
        analyze(self.project, self.source, budget="light", tracks={"voice": 0, "game": 1}, layout=SINGLE, masks={},
                ffmpeg=FFMPEG, ffprobe=FFPROBE)
        _WordWhisper.loads, _WordModel.calls = [], []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def cut_points(self, scenes: list[dict]) -> list[dict]:
        number = add_version(self.project, timeline(self.source, scenes, source_layout=SINGLE), source_duration=30.0)
        with mock.patch.dict(sys.modules, {"whisper": checked_whisper(_WordWhisper())}), \
                mock.patch.object(cross_track_check, "ffmpeg_extractor", wraps=cross_track_check.ffmpeg_extractor) as cut:
            result = race_requests.cut_points_from_request({"project": str(self.project), "version": number,
                                                            "ffmpeg": FFMPEG, "whisper_device": "CPU"})
        self.extractor = cut
        return result["cut_points"]

    def test_whisper_is_loaded_only_when_an_edge_needs_words(self) -> None:
        report = self.cut_points([scene("s01", 12.0, 20.0)])
        self.assertEqual([(entry["edge"], entry.get("quiet")) for entry in report], [("in", True), ("out", True)])
        self.assertEqual(_WordWhisper.loads, [], "the driver never talks at these edges: no model is loaded")

    def test_each_edge_is_heard_through_the_shared_loader_with_the_quick_model(self) -> None:
        report = self.cut_points([scene("s01", 6.5, 7.5)])
        self.assertEqual(_WordWhisper.loads, [("small", "cpu")], "loaded once, by the shared loader")
        self.assertEqual([name for name, _ in _WordModel.calls], ["s01-in.wav", "s01-out.wav"])
        options = _WordModel.calls[0][1]
        self.assertEqual((options["word_timestamps"], options["language"], options["temperature"]), (True, "en", 0.0))
        self.extractor.assert_called_once_with(FFMPEG, self.source)
        self.assertEqual([(entry["edge"], entry["cuts_a_word"]) for entry in report], [("in", "Into"), ("out", "Into")])
        self.assertEqual(list(report[0]), ["scene", "edge", "at", "cuts_a_word", "words_before", "words_after"])
        self.assertFalse(list((version_dir(self.project, 1) / "review" / "cut-points").glob("*.wav")))

    def test_an_analysis_from_before_wave_7_works_the_talk_level_out_from_its_loudness(self) -> None:
        # The tone stops at 8 s, so a cut at 8.6 s is in silence: with the analysis's talk level it is
        # not a word cut. An older analysis has no such level: it is worked out from its loudness per
        # second of the voice track, by the shared rule, and the silent cut is still found.
        self.assertTrue(self.cut_points([scene("s01", 6.5, 8.6)])[1]["microphone_silent_at_cut"])
        path = self.project / "analysis" / "analysis.json"
        older = json.loads(path.read_text(encoding="utf-8"))
        older.pop("voice_talk_threshold_dbfs")
        path.write_text(json.dumps(older), encoding="utf-8")
        self.assertEqual(review._voice_talk(self.project, 0)[1],
                         voice_track.talk_threshold_dbfs(older["loudness_per_second"]["0"]))
        out = self.cut_points([scene("s01", 6.5, 8.6)])[1]
        self.assertEqual(out["cuts_a_word"], "")
        self.assertTrue(out["microphone_silent_at_cut"])


class SharedPartsTests(unittest.TestCase):
    def test_the_review_tools_have_no_ffmpeg_or_whisper_of_their_own(self) -> None:
        for module in (review, library):
            text = Path(module.__file__).read_text(encoding="utf-8")
            for own in (r"^\s*import (whisper|torch|subprocess)\s*$", r"\bload_model\b", r"\bsubprocess\."):
                with self.subTest(module=module.__name__, own=own):
                    self.assertIsNone(re.search(own, text, re.MULTILINE))
        self.assertFalse(hasattr(review, "_whisper_model"))
        self.assertFalse(hasattr(review, "_grab_region"))
        self.assertIs(cross_track_check._ffmpeg_extractor, cross_track_check.ffmpeg_extractor)

    def test_the_talk_level_comes_from_the_shared_rule_not_a_copy(self) -> None:
        for module in (review, analysis_module):
            text = Path(module.__file__).read_text(encoding="utf-8")
            with self.subTest(module=module.__name__):
                self.assertNotIn("ACTIVE_ABOVE_FLOOR_DB", text)
                self.assertNotIn("ACTIVE_MIN_DBFS", text)

    def test_the_brief_covers_dead_time_the_label_and_the_fixed_privacy(self) -> None:
        brief = prompt.BRIEF.read_text(encoding="utf-8")
        for words in ('"Dead time" section', "**Cut dead time**", "unless it serves the story: a results screen",
                      "`idle_seconds`", "`editor_label`", '"claude-opus"', "`notes`",
                      "The privacy masks and the camera layout are fixed by Media Manglers",
                      "a request cannot remove a mask or change the layout", "Leave `source_layout` out"):
            with self.subTest(words=words):
                self.assertIn(words, brief)
        for retired in ("race-video-save-mask", "race-video-panel-still"):
            self.assertNotIn(retired, brief)
        for command in ("race-video-look", "race-video-add-version", "race-video-render", "race-video-review-kit",
                        "race-video-cut-points", "race-video-feedback", "race-video-usage"):
            self.assertIn(f"`{command}`", brief, "every command the editor uses is still listed")


if __name__ == "__main__":
    unittest.main()
