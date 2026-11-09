"""214: one frame renderer for every screenshot the app takes.

Find my bug reports, Package any video for AI (its screenshots, its panel screenshots and its
evidence add-on) and Review Media Inbox (its timeline and its targeted evidence) each had their own
way of pulling frames out of a recording. They all go through media_manglers.core.frame_render now.

226 adds what the AI Video Editor needs: one privacy-blur filter, masked stills, contact sheets,
and the game-picture sampler for 217's signal 2. Their FFmpeg output is proved identical to the
editor's own code before Wave 7 in tests/test_wave7_identity.py.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core import activity_timeline, frame_render, voice_track  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "Video Mangler.ps1"
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def _clip(path: Path, size: str, seconds: int, rate: int = 30) -> Path:
    subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=size={size}:rate={rate}:duration={seconds}", "-c:v", "libx264", "-g", str(rate * 2),
                    "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PlanTests(unittest.TestCase):
    def test_batches_split_at_a_gap_a_long_stretch_and_a_full_batch(self) -> None:
        self.assertEqual(frame_render.plan_batches([5.0, 1.0, 2.0, 30.0, 31.0]), [[1, 2, 0], [3, 4]])
        self.assertEqual(frame_render.plan_batches([0.0, 9.0, 18.0, 27.0], max_gap_seconds=10, max_span_seconds=20),
                         [[0, 1, 2], [3]])
        self.assertEqual([len(batch) for batch in frame_render.plan_batches([i * 0.1 for i in range(200)])], [90, 90, 20])

    def test_times_and_cadence_are_written_as_the_backend_wrote_them(self) -> None:
        self.assertEqual([frame_render.seconds_text(value) for value in (0.0, -3.0, 12.0, 12.5, 1.25)],
                         ["0", "0", "12", "12.5", "1.25"])
        self.assertEqual([frame_render.fps_filter(value) for value in (10.0, 3.0, 0.5)],
                         ["fps=0.1", "fps=0.33333333", "fps=2"])


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class RenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_moments_come_in_batches_with_their_panels_and_are_reused_by_a_later_run(self) -> None:
        recording = _clip(self.root / "surround.mkv", "5760x1080", 6)
        panels = [{"role": role, "crop_x": 1920 * index, "crop_y": 0, "crop_width": 1920, "crop_height": 1080}
                  for index, role in enumerate(("overview_cam", "driver_view", "face_cam"))]
        moments = [{"timestamp_seconds": at, "path": str(self.root / "frames" / f"f{i}.jpg"),
                    "panels": [{**panel, "path": str(self.root / "panels" / panel["role"] / f"f{i}.jpg")} for panel in panels]}
                   for i, at in enumerate((4.5, 1.0, 2.25))]
        results = frame_render.render_moments(FFMPEG, recording, moments, ffprobe_exe=FFPROBE)
        self.assertEqual([item["status"] for item in results], ["created"] * 3)
        self.assertEqual({(item["width"], item["height"]) for item in results}, {(5760, 1080)})
        self.assertEqual({item["panel_detection"] for item in results}, {"three_panel_5760x1080"})
        self.assertEqual({item["batch_size"] for item in results}, {3})
        for moment in moments:
            for panel in moment["panels"]:
                self.assertEqual(frame_render.jpeg_size(panel["path"]), (1920, 1080))
        before = [_digest(Path(moment["path"])) for moment in moments]

        again = frame_render.render_moments(FFMPEG, recording, moments, ffprobe_exe=FFPROBE)
        self.assertTrue(all(item["reused"] for item in again))
        self.assertEqual([_digest(Path(moment["path"])) for moment in moments], before)

    def test_a_batch_that_fails_is_made_one_frame_at_a_time(self) -> None:
        recording = _clip(self.root / "plain.mkv", "320x180", 4)
        moments = [{"timestamp_seconds": at, "path": str(self.root / f"f{i}.jpg"), "name": f"f{i}.jpg", "panels": []}
                   for i, at in enumerate((0.5, 2.5))]
        with mock.patch.object(frame_render, "probe_video", return_value={"width": 320, "height": 180,
                                                                           "frame_rate": 0.0, "frame_rate_text": ""}):
            results = frame_render.render_moments(FFMPEG, recording, moments, ffprobe_exe=FFPROBE)
        self.assertEqual([(item["status"], item["method"]) for item in results], [("created", "single")] * 2)
        self.assertEqual({item["panel_detection"] for item in results}, {"not_applicable"})
        self.assertIn("using the compatible per-frame path", results[0]["warnings"][0])

    def test_panels_switched_off_are_not_made(self) -> None:
        recording = _clip(self.root / "surround.mkv", "5760x1080", 2)
        moments = [{"timestamp_seconds": 1.0, "path": str(self.root / "f.jpg"),
                    "panels": [{"role": "face_cam", "crop_x": 3840, "crop_y": 0, "crop_width": 1920, "crop_height": 1080,
                                "path": str(self.root / "face.jpg")}]}]
        result = frame_render.render_moments(FFMPEG, recording, moments, ffprobe_exe=FFPROBE, panel_mode="off")[0]
        self.assertEqual((result["status"], result["panel_detection"], result["panels"][0]["status"]),
                         ("created", "disabled", "disabled"))
        self.assertFalse((self.root / "face.jpg").exists())

    def test_cadence_makes_one_screenshot_every_interval_and_keeps_a_finished_folder(self) -> None:
        recording = _clip(self.root / "plain.mkv", "640x360", 10)
        frames = self.root / "frames_2s"
        made = frame_render.render_cadence(FFMPEG, recording, frames, 2.0)
        self.assertEqual((made["method"], made["ok"], made["frame_count"]), ("CPU", True, 5))
        self.assertEqual(frame_render.jpeg_size(frames / "frame_000001.jpg"), (1280, 720))
        self.assertEqual(frame_render.render_cadence(FFMPEG, recording, frames, 2.0)["method"], "SKIPPED_EXISTING")

        panels = self.root / "face_cam"
        cut = frame_render.render_cadence(FFMPEG, recording, panels, 5.0, pattern="face_cam_%06d.jpg",
                                          after_fps="crop=320:180:320:180", keep_existing=False)
        self.assertEqual((cut["ok"], cut["frame_count"]), (True, 2))
        self.assertEqual(frame_render.jpeg_size(panels / "face_cam_000001.jpg"), (320, 180))

    def test_exact_frames_say_the_time_they_really_show(self) -> None:
        recording = _clip(self.root / "plain.mkv", "320x180", 4, rate=10)
        seen: list[int] = []
        made = frame_render.render_exact(FFMPEG, recording, [0.5, 1.2, 3.0], self.root / "frames",
                                         on_frame=lambda frame: seen.append(frame["ordinal"]))
        self.assertEqual(seen, [1, 2, 3])
        self.assertEqual([round(item["actual_timestamp_seconds"], 3) for item in made], [0.5, 1.2, 3.0])
        self.assertTrue(all(Path(item["path"]).is_file() for item in made))


class OneRendererWiringTests(unittest.TestCase):
    """Every screenshot the backend makes goes through the one renderer."""

    def setUp(self) -> None:
        self.text = SCRIPT.read_text(encoding="utf-8")

    def _function(self, name: str) -> str:
        start = self.text.index(f"function {name} {{")
        return self.text[start: self.text.index("\nfunction ", start + 10)]

    def test_the_backend_has_no_screenshot_maker_of_its_own(self) -> None:
        for gone in ("Invoke-CodexEvidenceFrameTasksLegacy", "Export-CodexEvidenceFrame", "Export-PanelCropImage"):
            self.assertNotIn(f"function {gone} ", self.text)
        self.assertIn('-Command "frames-render"', self._function("Invoke-CodexEvidenceFrameTasks"))
        self.assertIn('-Command "frames-render"', self._function("Invoke-MMFrameCadence"))

    def test_package_any_video_and_the_inbox_targeted_evidence_use_it(self) -> None:
        self.assertIn("Invoke-MMFrameCadence", self._function("Extract-FramesAtInterval"))
        self.assertIn("Invoke-MMFrameCadence", self._function("Export-FullReviewPanelFrames"))
        targeted = self._function("Invoke-ReviewInboxTargetedEvidence")
        self.assertIn("Invoke-CodexEvidenceFrameTasks -FFmpegExe", targeted)
        self.assertIn("Invoke-CodexEvidenceAudioTasks -FFmpegExe", targeted)
        self.assertNotIn("TasksLegacy", targeted)

    def test_the_inbox_timeline_uses_it(self) -> None:
        source = (REPO_ROOT / "src" / "media_manglers" / "core" / "review_preparation.py").read_text(encoding="utf-8")
        visuals = source[source.index("def _render_visuals("): source.index("def _validate_rendered_image(")]
        self.assertIn("frame_render.render_exact(", visuals)
        self.assertIn("frame_render.crop_panel(", visuals)
        self.assertNotIn('"showinfo"', visuals)


# 226: what the AI Video Editor needs from the one frame renderer --------------------------------

def _gray(path: Path) -> bytes:
    return subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                          capture_output=True, check=True).stdout


def _detail(gray: bytes, width: int, x0: int, x1: int, y0: int, y1: int) -> float:
    total = count = 0
    for y in range(y0, y1):
        row = gray[y * width:(y + 1) * width]
        for x in range(x0, x1 - 1):
            total += abs(row[x] - row[x + 1])
            count += 1
    return total / count


def _image(path: Path, size: str, drawing: str) -> Path:
    subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=black:s={size},{drawing}",
                    "-frames:v", "1", str(path)], check=True)
    return path


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


class PrivacyBlurFilterTests(unittest.TestCase):
    """The one builder gives exactly the filter text the editor built in three places before (226)."""

    def test_a_still_scaled_from_the_whole_recording(self) -> None:
        # analysis.grab_stills: the whole frame scaled to 1920 wide, the whole-frame mask scaled with it.
        self.assertEqual(
            frame_render.privacy_blur_filter(scale=(1920, 360)),
            "[0:v]scale=1920:360,split=2[a][b];[b]gblur=sigma=12[bb];[1:v]scale=1920:360,format=gray[m];"
            "[bb][m]alphamerge[bm];[a][bm]overlay[v]")

    def test_a_close_look_cut_at_full_resolution_with_its_time_stamp(self) -> None:
        # review._grab_region: the region cut at the recording's size, the mask cut the same way, then the stamp.
        self.assertEqual(
            frame_render.privacy_blur_filter(crop=(680, 20, 200, 120), mask_fit="crop", after="drawtext=text='x'"),
            "[0:v]crop=200:120:680:20,split=2[a][b];[b]gblur=sigma=12[bb];[1:v]crop=200:120:680:20,format=gray[m];"
            "[bb][m]alphamerge[bm];[a][bm]overlay,drawtext=text='x'[v]")

    def test_a_render_region_and_a_render_panel(self) -> None:
        # render._SceneGraph._region: a crop reaching into masked cameras, through the whole-frame mask.
        self.assertEqual(
            frame_render.privacy_blur_filter(crop=(0, 0, 960, 180), mask_fit="crop", sigma=30, setsar=True,
                                             shortest=True, source="vmain", mask="2:v", prefix="vbaser", out="vbaser"),
            "[vmain]crop=960:180:0:0,setsar=1,split=2[vbasera][vbaserb];[vbaserb]gblur=sigma=30[vbaserbb];"
            "[2:v]crop=960:180:0:0,format=gray[vbaserm];[vbaserbb][vbaserm]alphamerge[vbaserbm];"
            "[vbasera][vbaserbm]overlay=shortest=1[vbaser]")
        # render._SceneGraph.view: one camera panel through its own mask, then scaled to the scene.
        self.assertEqual(
            frame_render.privacy_blur_filter(crop=(640, 0, 320, 180), sigma=30, setsar=True, shortest=True,
                                             source="vmain", mask="1:v", prefix="vbase", out="vbase",
                                             after="scale=1280:720:flags=lanczos,setsar=1"),
            "[vmain]crop=320:180:640:0,setsar=1,split=2[vbasea][vbaseb];[vbaseb]gblur=sigma=30[vbasebb];"
            "[1:v]scale=320:180,format=gray[vbasem];[vbasebb][vbasem]alphamerge[vbasebm];"
            "[vbasea][vbasebm]overlay=shortest=1,scale=1280:720:flags=lanczos,setsar=1[vbase]")

    def test_an_unknown_mask_fit_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            frame_render.privacy_blur_filter(scale=(10, 10), mask_fit="stretch")

    def test_a_mask_with_nothing_to_fit_it_to_is_refused(self) -> None:
        # Without a crop or a scale the mask keeps its own size, and FFmpeg refuses the overlay unless
        # it happens to be exactly the recording's: say so before anything runs.
        for mask_fit in ("scale", "crop"):
            with self.subTest(mask_fit=mask_fit), self.assertRaisesRegex(ValueError, "scaled or cropped"):
                frame_render.privacy_blur_filter(mask_fit=mask_fit)
        with self.assertRaisesRegex(ValueError, "scaled or cropped"):
            frame_render.still_command("ffmpeg", Path("race.mkv"), 1.0, Path("x.jpg"), mask=Path("mask.png"))
        # Without a mask nothing needs fitting.
        self.assertEqual(frame_render.still_command("ffmpeg", Path("race.mkv"), 1.0, Path("x.jpg")),
                         ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-ss", "1.00", "-i", "race.mkv",
                          "-frames:v", "1", "-q:v", "4", "-f", "image2", "x.jpg"])

    def test_the_editors_still_command_is_exactly_what_it_was(self) -> None:
        # The command analysis.grab_stills ran for each still, masked and not.
        target = Path("stills") / ".s00003.jpg"
        self.assertEqual(
            frame_render.still_command("ffmpeg", Path("race.mkv"), 15.0, target, scale=(1920, 360), mask=Path("mask.png")),
            ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-ss", "15.00", "-i", "race.mkv", "-i", "mask.png",
             "-filter_complex", "[0:v]scale=1920:360,split=2[a][b];[b]gblur=sigma=12[bb];[1:v]scale=1920:360,"
             "format=gray[m];[bb][m]alphamerge[bm];[a][bm]overlay[v]", "-map", "[v]",
             "-frames:v", "1", "-q:v", "4", "-f", "image2", str(target)])
        self.assertEqual(
            frame_render.still_command("ffmpeg", Path("race.mkv"), 7.256, target, scale=(1920, 360)),
            ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-ss", "7.26", "-i", "race.mkv", "-vf", "scale=1920:360",
             "-frames:v", "1", "-q:v", "4", "-f", "image2", str(target)])

    def test_the_editors_font_is_the_frame_renderers(self) -> None:
        from media_manglers.core.race_video import analysis, render, review  # noqa: PLC0415

        self.assertIs(render._font, frame_render.font_option)
        self.assertIs(review._font, frame_render.font_option)
        # 226 (W4a): the analysis draws no text of its own any more; its sheets are the frame renderer's.
        self.assertFalse(hasattr(analysis, "_font"))
        self.assertEqual(render.FONT_DIR, frame_render.FONT_DIR)


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class StillTests(unittest.TestCase):
    """Stills at chosen times, blurred through the privacy mask in the same FFmpeg run (226)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.source = _clip(cls.root / "race.mkv", "960x180", 10)
        # Whole-frame masks of the 1920x360 stills: the right camera private, or the left one.
        cls.mask = _image(cls.root / "mask-right.png", "1920x360", "drawbox=x=1280:y=0:w=640:h=360:color=white:t=fill")
        cls.other_mask = _image(cls.root / "mask-left.png", "1920x360", "drawbox=x=0:y=0:w=640:h=360:color=white:t=fill")
        # The same right-camera mask at the recording's own size, for regions cut at full resolution.
        cls.full_mask = _image(cls.root / "mask-full.png", "960x180", "drawbox=x=640:y=0:w=320:h=180:color=white:t=fill")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def test_stills_are_scaled_blurred_through_the_mask_and_named_in_order(self) -> None:
        heard: list[tuple[int, int]] = []
        masked = frame_render.render_stills(FFMPEG, self.source, [0.0, 2.5, 5.0, 7.5], self.root / "masked",
                                            scale=(1920, 360), mask=self.mask,
                                            on_progress=lambda done, total: heard.append((done, total)))
        self.assertEqual([path.name for path in masked], ["s00000.jpg", "s00001.jpg", "s00002.jpg", "s00003.jpg"])
        self.assertEqual(heard[-1], (4, 4))
        self.assertEqual(sorted(done for done, _total in heard), [1, 2, 3, 4])
        self.assertEqual({frame_render.jpeg_size(path) for path in masked}, {(1920, 360)})
        self.assertEqual(sorted(path.name for path in (self.root / "masked").iterdir()),
                         [frame_render.STILLS_KEY, *[path.name for path in masked]], "no temporary still is left")
        plain = frame_render.render_stills(FFMPEG, self.source, [0.0, 2.5, 5.0, 7.5], self.root / "plain",
                                           scale=(1920, 360), reuse=False)
        for blurred, sharp in zip(masked, plain):
            blurred_gray, sharp_gray = _gray(blurred), _gray(sharp)
            self.assertLess(_detail(blurred_gray, 1920, 1300, 1900, 10, 350),
                            0.5 * _detail(sharp_gray, 1920, 1300, 1900, 10, 350), "the private camera is blurred")
            self.assertAlmostEqual(_detail(blurred_gray, 1920, 20, 620, 10, 350),
                                   _detail(sharp_gray, 1920, 20, 620, 10, 350), delta=1.0)
        self.assertFalse((self.root / "plain" / frame_render.STILLS_KEY).exists(), "no record without reuse")

    def test_a_folder_is_reused_only_with_the_same_settings_and_the_same_mask(self) -> None:
        folder = self.root / "reused"
        times = [1.0, 3.0, 6.0, 9.0]

        def take(chosen_times: list[float], mask: Path) -> tuple[list[Path], int]:
            with mock.patch.object(frame_render, "_run", wraps=frame_render._run) as run:
                made = frame_render.render_stills(FFMPEG, self.source, chosen_times, folder, scale=(1920, 360), mask=mask)
            return made, run.call_count

        made, runs = take(times, self.mask)
        self.assertEqual(runs, 4)
        first = [_digest(path) for path in made]
        self.assertTrue((folder / frame_render.STILLS_KEY).is_file())

        self.assertEqual(take(times, self.mask)[1], 0, "the same settings and mask: every still is kept")
        (folder / "s00002.jpg").unlink()
        made, runs = take(times, self.mask)
        self.assertEqual(runs, 1, "only the missing still is taken")
        self.assertEqual([_digest(path) for path in made], first)

        made, runs = take(times, self.other_mask)
        self.assertEqual(runs, 4, "another mask: every still is taken again")
        self.assertNotEqual([_digest(path) for path in made], first)

        made, runs = take(times[:2], self.other_mask)
        self.assertEqual(runs, 2, "other times: taken again")
        self.assertEqual(sorted(path.name for path in folder.glob("s*.jpg")), ["s00000.jpg", "s00001.jpg"],
                         "stills left from other settings are removed")

        (folder / frame_render.STILLS_KEY).unlink()
        self.assertEqual(take(times[:2], self.other_mask)[1], 2, "a folder with no record is taken again")

    def test_close_look_stills_are_cut_at_full_resolution_and_stamped(self) -> None:
        made = frame_render.render_stills(FFMPEG, self.source, [4.0, 8.0], self.root / "look", crop=(680, 20, 200, 120),
                                          mask=self.full_mask, stamp=True, quality=3, workers=1, reuse=False)
        self.assertEqual({frame_render.jpeg_size(path) for path in made}, {(200, 120)})
        command = frame_render.still_command(FFMPEG, self.source, 61.0, Path("x.jpg"), crop=(680, 20, 200, 120),
                                             mask=self.full_mask, stamp=True, quality=3)
        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("[1:v]crop=200:120:680:20,format=gray[m]", graph)
        self.assertIn("text='01\\:01'", graph)
        self.assertEqual(command[command.index("-q:v") + 1], "3")

    def test_a_panel_still_can_be_a_png_at_full_resolution(self) -> None:
        made = frame_render.render_stills(FFMPEG, self.source, [2.0], self.root / "panel", crop=(0, 0, 320, 180),
                                          name="left.png", workers=1, reuse=False)
        self.assertEqual(made, [self.root / "panel" / "left.png"])
        self.assertEqual(made[0].read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(_png_size(made[0]), (320, 180))
        self.assertNotIn("-q:v", frame_render.still_command(FFMPEG, self.source, 2.0, made[0], crop=(0, 0, 320, 180)))

    def test_a_mask_with_neither_a_crop_nor_a_scale_takes_no_still(self) -> None:
        folder = self.root / "refused"
        with self.assertRaisesRegex(ValueError, "scaled or cropped"):
            frame_render.render_stills(FFMPEG, self.source, [1.0, 2.0], folder, mask=self.full_mask)
        self.assertFalse(folder.exists(), "refused before the folder is touched")

    def test_a_still_that_cannot_be_taken_says_when(self) -> None:
        with self.assertRaisesRegex(RuntimeError, r"could not take a still at 00:03"):
            frame_render.render_stills(FFMPEG, self.root / "missing.mkv", [3.0], self.root / "failed", reuse=False)

    def test_contact_sheets_tile_the_stills_with_their_times(self) -> None:
        stills = self.root / "sheet-stills"
        frame_render.render_stills(FFMPEG, self.source, [0.0, 2.0, 4.0, 6.0, 8.0], stills, scale=(1920, 360), reuse=False)
        heard: list[tuple[int, int]] = []
        sheets = frame_render.contact_sheets(FFMPEG, stills, 5, 0.0, 2.5, (640, 0, 640, 360), self.root / "sheets",
                                             columns=2, rows=2, on_progress=lambda done, total: heard.append((done, total)))
        self.assertEqual(sheets, [{"file": "sheet-01.jpg", "from": 0.0, "to": 7.5, "tiles": 4},
                                  {"file": "sheet-02.jpg", "from": 10.0, "to": 10.0, "tiles": 1}])
        self.assertEqual(heard, [(1, 2), (2, 2)])
        self.assertEqual(frame_render.jpeg_size(self.root / "sheets" / "sheet-01.jpg"), (640, 360))
        bare = frame_render.contact_sheets(FFMPEG, stills, 5, 0.0, 2.5, (0, 0, 1920, 360), self.root / "bare",
                                           tile=(160, 30), columns=3, rows=2, label=False)
        self.assertEqual([sheet["tiles"] for sheet in bare], [5])
        self.assertEqual(frame_render.jpeg_size(self.root / "bare" / "sheet-01.jpg"), (480, 60))

    def test_the_probe_also_gives_the_base_frame_rate(self) -> None:
        clip = _clip(self.root / "rate.mkv", "320x180", 2)
        self.assertEqual(frame_render.probe_video(FFPROBE, clip), {
            "width": 320, "height": 180, "frame_rate_text": "30/1", "frame_rate": 30.0,
            "r_frame_rate_text": "30/1", "r_frame_rate": 30.0,
        })


class PictureRegionTests(unittest.TestCase):
    """Signal 2 measures the game, never the cameras beside it (217, 226)."""

    def test_a_three_panel_recording_is_measured_on_its_game_panel(self) -> None:
        # The editor's panel names: left, center and right (as activity_timeline's region field says).
        center = ((1920, 0, 1920, 1080), "center panel")
        self.assertEqual(frame_render.picture_region(5760, 1080), center)
        self.assertEqual(frame_render.picture_region(5760, 1080, masked_panels=("left", "right")), center)
        self.assertEqual(frame_render.picture_region(5760, 1080, game_panel="driver_view", masked_panels=["face_cam"]), center)
        self.assertEqual(frame_render.picture_region(5760, 1080, game_panel="left"), ((0, 0, 1920, 1080), "left panel"))
        self.assertEqual(frame_render.picture_region(5760, 1080, game_panel="right"), ((3840, 0, 1920, 1080), "right panel"))

    def test_a_masked_or_unknown_panel_is_never_measured(self) -> None:
        self.assertIsNone(frame_render.picture_region(5760, 1080, masked_panels=("center",)))
        self.assertIsNone(frame_render.picture_region(5760, 1080, game_panel="right", masked_panels=("face_cam",)))
        self.assertIsNone(frame_render.picture_region(5760, 1080, game_panel="roof"))

    def test_any_other_size_is_measured_whole_and_no_size_not_at_all(self) -> None:
        self.assertEqual(frame_render.picture_region(1920, 1080, masked_panels=("left",)), ((0, 0, 1920, 1080), "whole frame"))
        self.assertEqual(frame_render.picture_region(3840, 1080), ((0, 0, 3840, 1080), "whole frame"))
        self.assertIsNone(frame_render.picture_region(0, 0))

    def test_keyframes_only_and_the_output_keep_every_sample_once(self) -> None:
        self.assertEqual(frame_render.picture_input_options(), ["-skip_frame:v:0", "nokey"])
        self.assertEqual(frame_render.picture_input_options(keyframes_only=False), [])
        output = frame_render.picture_output((1920, 0, 1920, 1080), Path("samples.raw"), Path("times.txt"))
        self.assertEqual(output[:4], ["-map", "0:v:0", "-fps_mode", "passthrough"])
        self.assertEqual(output[-3:], ["-f", "rawvideo", "samples.raw"])
        chain = output[output.index("-vf") + 1]
        self.assertTrue(chain.startswith("crop=1920:1080:1920:0,scale=64:36:flags=area,format=gray,"), chain)
        self.assertNotIn("fps=", chain, "a frame-rate filter would repeat keyframes as unchanged pictures")
        self.assertIn("metadata=mode=print:key=mm_picture_sample:file=times.txt", chain)

    def test_samples_that_do_not_agree_with_their_times_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            frames, times = Path(temp) / "samples.raw", Path(temp) / "times.txt"
            frames.write_bytes(bytes(2 * 64 * 36))
            times.write_text("frame:0    pts:0       pts_time:0\nmm_picture_sample=1\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "2 samples but 1 sample times"):
                frame_render.read_picture_samples(frames, times)
            frames.write_bytes(bytes(64 * 36 + 5))
            with self.assertRaisesRegex(RuntimeError, "part-way through a picture"):
                frame_render.read_picture_samples(frames, times)
            times.write_text(times.read_text(encoding="utf-8") * 2 + "frame:1    pts:2000    pts_time:2.5\n", encoding="utf-8")
            frames.write_bytes(bytes(range(256)) * 9 * 3)
            sample_times, sample_frames = frame_render.read_picture_samples(frames, times)
            self.assertEqual(sample_times, [0.0, 0.0, 2.5])
            self.assertEqual([len(frame) for frame in sample_frames], [2304] * 3)


def _surround_race(path: Path) -> Path:
    """170 s of a 5760x1080 recording at 2 pictures a second, a keyframe every 2 s, two sound tracks.

    The game (center panel) moves, is frozen 20-90 s while a clock in its corner keeps ticking, moves,
    is black 100-165 s, and moves again. The camera panels either side show moving noise throughout.
    """

    rate, seconds = 2, 170
    noise = ("color=gray:size=32x18:rate={rate}:duration={seconds},noise=alls=100:allf=t+u:all_seed={seed},"
             "scale=1920:1080:flags=neighbor")
    graph = (f"[0:v]split[a][b];[a][b]freezeframes=first={20 * rate}:last={90 * rate - 1}:replace={20 * rate},"
             "drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='between(t,100,165)',"
             f"drawtext={frame_render.font_option(True)}text='%{{eif\\:t\\:d}}':fontsize=28:fontcolor=white:x=24:y=24[game];"
             f"{noise.format(rate=rate, seconds=seconds, seed=1)}[left];"
             f"{noise.format(rate=rate, seconds=seconds, seed=2)}[right];"
             "[left][game][right]hstack=inputs=3,format=yuv420p[v]")
    subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y",
                    "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate={rate}:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=300:sample_rate=48000:duration={seconds}",
                    "-f", "lavfi", "-i", f"anoisesrc=color=pink:amplitude=0.05:sample_rate=48000:duration={seconds}:seed=7",
                    "-filter_complex", graph, "-map", "[v]", "-map", "1:a", "-map", "2:a",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-g", str(2 * rate),
                    "-keyint_min", str(2 * rate), "-sc_threshold", "0", "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class GamePictureSamplerTests(unittest.TestCase):
    """Keyframes of the game panel, shrunk to small gray pictures with their real times (217, 226)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.source = _surround_race(cls.root / "surround-race.mkv")
        video = frame_render.probe_video(FFPROBE, cls.source)
        cls.region, cls.region_name = frame_render.picture_region(video["width"], video["height"],
                                                                  masked_panels=("left", "right"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def test_keyframes_come_with_their_real_times_and_find_the_frozen_and_black_game(self) -> None:
        self.assertEqual((self.region, self.region_name), ((1920, 0, 1920, 1080), "center panel"))
        work = self.root / "standalone"
        result = frame_render.sample_picture(FFMPEG, self.source, self.region, work)
        self.assertEqual((result["ok"], result["method"], result["error"], result["warnings"]), (True, "CPU", "", []))
        self.assertEqual(result["times"], [2.0 * index for index in range(85)], "one sample per keyframe, at its time")
        self.assertEqual((result["sample_count"], result["median_spacing_seconds"]), (85, 2.0))
        self.assertEqual({len(frame) for frame in result["frames"]}, {64 * 36})
        self.assertEqual(list(work.iterdir()), [], "the sampler's own files are removed")

        changes, luma = activity_timeline.picture_change_per_second(result["times"], result["frames"], duration=170)
        game = activity_timeline.game_picture_timeline(changes, luma=luma, region=self.region_name)
        self.assertEqual(game.status, activity_timeline.STATUS_MEASURED)
        self.assertEqual(len(game.idle_stretches), 2, game.idle_stretches)
        (frozen_start, frozen_end), (black_start, black_end) = game.idle_stretches
        for found, expected in ((frozen_start, 20), (frozen_end, 90), (black_start, 100), (black_end, 165)):
            self.assertLessEqual(abs(found - expected), 3, game.idle_stretches)
        self.assertEqual(game.picture_kinds, [activity_timeline.PICTURE_STILL, activity_timeline.PICTURE_BLACK])

        # The camera panel beside it never stops moving: measuring it would hide the frozen game.
        camera = frame_render.sample_picture(FFMPEG, self.source, (0, 0, 1920, 1080), self.root / "camera")
        changes, luma = activity_timeline.picture_change_per_second(camera["times"], camera["frames"], duration=170)
        self.assertEqual(activity_timeline.game_picture_timeline(changes, luma=luma).idle_stretches, [])

    def test_the_samples_come_from_the_same_read_as_the_sound_and_the_sound_is_unchanged(self) -> None:
        alone = voice_track.extract_all_tracks(FFMPEG, self.source, 2, self.root / "sound alone")
        # A folder name with every character the filter text has to escape.
        work = self.root / "one read, the [game] picture's; work"
        frames, times = work / "samples.raw", work / "sample-times.txt"
        together = voice_track.extract_all_tracks(
            FFMPEG, self.source, 2, work, input_options=frame_render.picture_input_options(),
            extra_outputs=frame_render.picture_output(self.region, frames, times))
        for ordinal in (0, 1):
            self.assertGreater(alone[ordinal].stat().st_size, 160 * 32000)
            self.assertEqual(_digest(together[ordinal]), _digest(alone[ordinal]), f"track {ordinal + 1} is byte for byte the same")
        sample_times, sample_frames = frame_render.read_picture_samples(frames, times)
        standalone = frame_render.sample_picture(FFMPEG, self.source, self.region, self.root / "standalone-again")
        self.assertEqual(sample_times, standalone["times"])
        self.assertEqual(sample_frames, standalone["frames"])

    def test_a_graphics_card_decode_is_tried_first_and_the_cpu_takes_over_when_it_fails(self) -> None:
        real = voice_track.run_while_progressing

        def no_graphics_card(command, **options):
            if "-hwaccel" in command:
                Path(options["stderr_path"]).write_text("No device available for decoder\n", encoding="utf-8")
                return 1, 0.0
            return real(command, **options)

        with mock.patch.object(voice_track, "run_while_progressing", side_effect=no_graphics_card) as run:
            result = frame_render.sample_picture(FFMPEG, self.source, self.region, self.root / "gpu", use_gpu=True)
        self.assertEqual(run.call_count, 2)
        self.assertEqual((result["ok"], result["method"]), (True, "CPU"))
        self.assertIn("Falling back to CPU", result["warnings"][0])
        self.assertEqual(result["sample_count"], 85)
        # On this PC's own graphics card, or its CPU when the card cannot decode it.
        result = frame_render.sample_picture(FFMPEG, self.source, self.region, self.root / "gpu", use_gpu=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["times"], [2.0 * index for index in range(85)])

    def test_the_read_says_how_far_into_the_recording_it_is(self) -> None:
        # 145 and plan G4: a picture-only read of a long recording is never minutes of silence.
        heard: list[float] = []
        commands: list[list[str]] = []
        real = voice_track.run_while_progressing

        def watched(command, **options):
            commands.append(list(command))
            return real(command, **options)

        work = self.root / "progress"
        with mock.patch.object(voice_track, "run_while_progressing", side_effect=watched):
            result = frame_render.sample_picture(FFMPEG, self.source, self.region, work, on_progress=heard.append)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["sample_count"], 85)
        self.assertIn("-progress", commands[0])
        self.assertEqual(commands[0][commands[0].index("-progress") + 1], "pipe:1")
        self.assertTrue(heard, "the read reported how far it got")
        self.assertEqual(heard, sorted(set(heard)), "only a later position is reported")
        self.assertGreaterEqual(heard[-1], 160.0)
        self.assertLessEqual(heard[-1], 171.0)
        self.assertEqual(list(work.iterdir()), [], "the errors file goes with the sampler's other files")

    def test_a_read_that_stops_moving_is_stopped_and_counts_as_a_failed_attempt(self) -> None:
        # What FFmpeg does when the drive goes to sleep: one position, then nothing.
        real = voice_track.run_while_progressing
        stalled = [sys.executable, "-c", "import time; print('out_time_us=65000000', flush=True); time.sleep(60)"]

        def card_stalls(command, **options):
            return real(stalled if "-hwaccel" in command else command, **options)

        started = time.monotonic()
        with mock.patch.object(voice_track, "run_while_progressing", side_effect=card_stalls) as run:
            result = frame_render.sample_picture(FFMPEG, self.source, self.region, self.root / "card-stalls",
                                                 use_gpu=True, stall_seconds=5.0)
        self.assertLess(time.monotonic() - started, 45, "stopped soon after it stalled, not after its 60 s sleep")
        self.assertEqual(run.call_count, 2)
        self.assertEqual((result["ok"], result["method"], result["sample_count"]), (True, "CPU", 85))
        self.assertIn("Falling back to CPU", result["warnings"][0])

        work = self.root / "stalls"
        with mock.patch.object(voice_track, "run_while_progressing",
                               side_effect=lambda command, **options: real(stalled, **options)):
            result = frame_render.sample_picture(FFMPEG, self.source, self.region, work, stall_seconds=1.0)
        self.assertFalse(result["ok"])
        self.assertTrue(result["error"].startswith("The game picture could not be read."), result["error"])
        self.assertIn("Reading the recording's picture stopped making progress", result["error"])
        self.assertIn("01:05 into the recording", result["error"])
        self.assertEqual((result["times"], result["frames"]), ([], []))
        self.assertEqual(list(work.iterdir()), [], "a stopped read leaves nothing behind")

    def test_a_recording_without_a_picture_cannot_be_sampled(self) -> None:
        sound = self.root / "sound-only.wav"
        subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=duration=2", str(sound)],
                       check=True)
        result = frame_render.sample_picture(FFMPEG, sound, (0, 0, 64, 36), self.root / "no-picture")
        self.assertFalse(result["ok"])
        self.assertTrue(result["error"].startswith("The game picture could not be read."), result["error"])
        self.assertEqual((result["times"], result["frames"]), ([], []))



@unittest.skipUnless(FFMPEG, "FFmpeg is required")
class GrayTilesTests(unittest.TestCase):
    """226: the AI Video Editor's sharp-picture-change check reads its stills through the one frame
    renderer, in its hidden window, and a read that fails says why instead of finding no change."""

    def test_each_still_becomes_a_tiny_gray_tile_through_the_hidden_window_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for index, colour in enumerate(("black", "white", "gray")):
                _image(folder / f"s{index:05d}.jpg", "320x180", f"drawbox=x=0:y=0:w=160:h=180:color={colour}:t=fill")
            with mock.patch.object(frame_render.subprocess, "run", wraps=subprocess.run) as run:
                tiles = frame_render.gray_tiles(FFMPEG, folder, 3, (0, 0, 320, 180))
                two = frame_render.gray_tiles(FFMPEG, folder, 2, (0, 0, 160, 180))
        self.assertEqual([len(tile) for tile in tiles], [32 * 18] * 3)
        self.assertEqual(len(two), 2, "only the stills asked for")
        self.assertLess(max(tiles[0]), 40)
        self.assertGreater(min(two[1]), 200, "the crop is applied before shrinking")
        self.assertEqual(run.call_args.kwargs["creationflags"], int(getattr(subprocess, "CREATE_NO_WINDOW", 0)))

    def test_stills_that_cannot_be_read_raise_with_ffmpegs_reason(self) -> None:
        from media_manglers.core.race_video import analysis

        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for index in range(2):
                (folder / f"s{index:05d}.jpg").write_bytes(b"not a picture")
            with self.assertRaises(RuntimeError) as caught:
                frame_render.gray_tiles(FFMPEG, folder, 2, (0, 0, 320, 180))
            self.assertIn("could not read the stills to compare them: ", str(caught.exception))
            self.assertNotEqual(str(caught.exception).split(": ", 1)[1].strip(), "")
            # The editor's picture changes say so, never "none found".
            with self.assertRaisesRegex(RuntimeError, "could not read the stills"):
                analysis.picture_changes(FFMPEG, folder, 2, (0, 0, 320, 180), [0.0, 10.0])
        self.assertNotIn("subprocess", Path(analysis.__file__).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
