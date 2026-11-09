"""Wave 7 (226): the AI Video Editor's renderer and export (161 items 1, 2, 3 and 5, 177, 178).

Real FFmpeg on small synthetic recordings made with lavfi, through the real renderer, export,
technical check and command line (x264 and CPU decoding, as on a PC without an NVIDIA card; the NVENC
tests are skipped where NVENC cannot encode).

- The frame rate: the recording's own, snapped to a standard rate, up to 60; previews half from 48.
- One store of scene pictures and sounds per project, shared by every version: a revision that only
  changes the sound renders no picture at all, and a scene that moved or was renamed is reused.
- Exact timing: whole frames and the matching samples, so picture and sound are the same length.
- Compress once: a final's scenes are lossless, its join the one lossy picture encode.
- The export quality, the honest report, the lock, the store's trim, readable names, export names.
- The technical check finds the report of the readable name and of the export; a validation render
  keeps its own file and report, and an export refuses one; an export holds one lock from its render
  to its placement and then removes the final's scene store; the sound fades in over 0.5 s.
"""

from __future__ import annotations

from array import array
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core import frame_render  # noqa: E402
from media_manglers.core.race_video import library, render  # noqa: E402
from media_manglers.core.race_video.library import export_version, list_projects  # noqa: E402
from media_manglers.core.race_video.project import (  # noqa: E402
    add_version,
    create_project,
    read_json,
    update_project,
    version_dir,
)
from media_manglers.core.race_video.qc import check_video  # noqa: E402
from media_manglers.core.race_video.render import (  # noqa: E402
    RenderOptions,
    export_frame_rate,
    preview_frame_rate,
    render_version,
)
from media_manglers.core.race_video.requests import (  # noqa: E402
    check_from_request,
    export_from_request,
    render_from_request,
)
from media_manglers.core.race_video.timeline import SCHEMA  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
LAYOUT = {"width": 960, "height": 180,
          "panels": {"left": [0, 0, 320, 180], "center": [320, 0, 320, 180], "right": [640, 0, 320, 180]}}
X264 = {"encoder": "x264", "hwaccel": "none"}


def recording(path: Path, rate: str = "30", seconds: int = 12, panel: tuple[int, int] = (320, 180),
              codec: tuple[str, ...] = ("libx264", "-preset", "ultrafast")) -> Path:
    """Three panels side by side (a test pattern, a second pattern, a fine checkerboard on the right),
    at ``rate``; a voice track (a tone) and a game track (pink noise)."""

    w, h = panel
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        FFMPEG, "-hide_banner", "-v", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc2=s={w}x{h}:r={rate}:d={seconds}",
        "-f", "lavfi", "-i", f"testsrc=s={w}x{h}:r={rate}:d={seconds}",
        "-f", "lavfi", "-i", f"nullsrc=s={w}x{h}:r={rate}:d={seconds},geq=lum='if(mod(floor(X/4)+floor(Y/4),2),235,16)':cb=128:cr=128",
        "-f", "lavfi", "-i", f"sine=frequency=300:sample_rate=48000:duration={seconds}",
        "-f", "lavfi", "-i", f"anoisesrc=color=pink:amplitude=0.2:sample_rate=48000:duration={seconds}",
        "-filter_complex", "[0:v][1:v][2:v]hstack=inputs=3,format=yuv420p[v]",
        "-map", "[v]", "-map", "3:a", "-map", "4:a", "-c:v", *codec, "-c:a", "flac", "-t", str(seconds), str(path),
    ], check=True)
    return path


def scene(scene_id: str, start: float, end: float, **extra) -> dict:
    return {"id": scene_id, "beat": "test", "reason": "test", "in": start, "out": end, "view": "center",
            "audio": {"voice": 1.0, "game": 0.5}, **extra}


def three_scenes(**gains) -> list[dict]:
    audio = {"voice": 1.0, "game": 0.5, **gains}
    return [scene("s01", 0.5, 2.5, audio=dict(audio), title={"text": "Test race", "start": 0.2, "dur": 1.5}),
            scene("s02", 3.0, 4.5, view="right", audio=dict(audio), transition_in="dissolve", transition_dur=0.5),
            scene("s03", 5.0, 7.0, view="full", audio=dict(audio), transition_in="cut")]


def timeline(source: Path, scenes: list[dict]) -> dict:
    return {"schema": SCHEMA, "source": str(source), "source_layout": LAYOUT, "tracks": {"voice": 0, "game": 1},
            "scenes": scenes}


def probe(path: Path, *entries: str, count: bool = False) -> dict:
    """The first video stream's ``entries``, as FFprobe gives them."""

    command = [FFPROBE, "-v", "error", "-select_streams", "v:0"]
    if count:
        command.append("-count_frames")
    command += ["-show_entries", "stream=" + ",".join(entries), "-of", "json", str(path)]
    return (json.loads(subprocess.run(command, capture_output=True, text=True, check=True).stdout)["streams"] or [{}])[0]


def picture_md5(path: Path) -> str:
    """The MD5 of a file's video packets, as they are stored (no decode)."""

    out = subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-i", str(path), "-map", "0:v:0", "-c", "copy",
                          "-f", "md5", "-"], capture_output=True, text=True, check=True).stdout
    return out.strip()


def keyframes(path: Path) -> list[int]:
    out = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=flags",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True).stdout
    return [index for index, flags in enumerate(out.split()) if "K" in flags]


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def gray_frame(path: Path, at: float) -> bytes:
    return subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-ss", f"{at:.3f}", "-i", str(path), "-frames:v", "1",
                           "-vf", "format=gray", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout


def detail(path: Path, at: float, box: tuple[int, int, int, int]) -> float:
    """How sharp a part ([x, y, w, h]) of a video's frame at ``at`` seconds is (tens for a checkerboard)."""

    x, y, w, h = box
    raw = subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-ss", f"{at:.2f}", "-i", str(path), "-frames:v", "1",
                          "-vf", f"crop={w}:{h}:{x}:{y},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    rows = [raw[row * w:(row + 1) * w] for row in range(h)]
    return sum(abs(line[i] - line[i + 1]) for line in rows for i in range(w - 1)) / (h * (w - 1))


class FrameRateRuleTests(unittest.TestCase):
    """161.2: the export frame rate from the rates FFprobe gives for a recording."""

    def test_the_recordings_rate_is_snapped_kept_up_to_60_and_divided_above(self) -> None:
        cases = [
            (("60/1", "60/1"), Fraction(60), "kept"),
            (("19001/317", "19001/317"), Fraction(60000, 1001), "kept"),   # what MKV gives for 59.94
            (("30/1", "30/1"), Fraction(30), "kept"),
            (("2997/100", "30000/1001"), Fraction(30000, 1001), "kept"),
            (("25/1", "25/1"), Fraction(25), "kept"),
            (("24000/1001", "24000/1001"), Fraction(24000, 1001), "kept"),
            (("120/1", "120/1"), Fraction(60), "divided by 2"),
            (("120000/1001", "120000/1001"), Fraction(60000, 1001), "divided by 2"),
            (("144/1", "144/1"), Fraction(48), "divided by 3"),
            (("100/1", "100/1"), Fraction(50), "divided by 2"),
            (("240/1", "240/1"), Fraction(60), "divided by 4"),
            (("0/0", "60/1"), Fraction(60), "r_frame_rate 60/1"),       # no average: the base rate
            (("", "1000/1"), Fraction(60), "could not be read"),        # MKV's clock is not a frame rate
            (("", ""), Fraction(60), "as before"),
            (("37/1", "37/1"), Fraction(37), "not a standard rate"),
        ]
        for (avg, base), expected, words in cases:
            with self.subTest(avg=avg, base=base):
                rate, why = export_frame_rate(avg, base)
                self.assertEqual(rate, expected)
                self.assertIn(words, why)

    def test_rates_that_disagree_are_counted(self) -> None:
        rate, why = export_frame_rate("30/1", "60/1", count=lambda: (59.99, 600))
        self.assertEqual(rate, Fraction(60))
        self.assertIn("600 frames counted", why)
        rate, why = export_frame_rate("30/1", "60/1", count=lambda: None)
        self.assertEqual(rate, Fraction(30))
        self.assertIn("could not be counted", why)

    def test_a_preview_is_half_the_export_from_48_up(self) -> None:
        for export, preview in ((Fraction(60), Fraction(30)), (Fraction(60000, 1001), Fraction(30000, 1001)),
                                (Fraction(50), Fraction(25)), (Fraction(48), Fraction(24)), (Fraction(30), Fraction(30)),
                                (Fraction(25), Fraction(25))):
            with self.subTest(export=export):
                self.assertEqual(preview_frame_rate(export), preview)


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class RenderTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.class_temp = tempfile.TemporaryDirectory()
        cls.class_root = Path(cls.class_temp.name)
        cls.source = recording(cls.class_root / "race.mkv")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.class_temp.cleanup()

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = self.root / "appdata"
        patcher = mock.patch.dict(os.environ, {"MEDIA_MANGLERS_WORKBENCH_APPDATA": str(self.settings)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def project(self, name: str, scenes: list[dict] | None = None, source: Path | None = None, **extra) -> Path:
        source = source or self.source
        project = create_project(self.root / "out", source, name)
        add_version(project, timeline(source, scenes or three_scenes()), source_duration=12.0, audio_streams=2, **extra)
        return project

    def options(self, **extra) -> RenderOptions:
        return RenderOptions(ffmpeg=FFMPEG, ffprobe=FFPROBE, **{**X264, **extra})


class ExactTimingTests(RenderTestCase):
    """161.2 and exact timing: a 30 fps and a 59.94 fps recording are exported at their own rate."""

    def check_export(self, source: Path, name: str, rate: str) -> dict:
        project = self.project(name, source=source)
        # The final as an export makes it, checked; not exported, because an export removes the final's
        # scenes once it is placed, and they are looked at here (CheckNamesTests exports at both rates).
        result = render_from_request({"project": str(project), "version": 1, "profile": "final", "ffmpeg": FFMPEG,
                                      "ffprobe": FFPROBE, **X264})
        report, qc = result["render"], result["technical_check"]
        self.assertTrue(qc["passed"], [c for c in qc["checks"] if not c["pass"]])
        self.assertEqual(report["output_format"]["fps"], rate)
        self.assertEqual(report["schema"], "mm-race-video-render-v2")
        fps = Fraction(rate)
        # Exactly the frames the edit has, with picture and sound the same length.
        frames = sum(row["picture"]["frames"] for row in report["scenes"]) - round(Fraction(1, 2) * fps)
        self.assertEqual(report["output_format"]["frames"], frames)
        video = probe(Path(report["output"]), "nb_read_frames", "avg_frame_rate", "duration", count=True)
        self.assertEqual(int(video["nb_read_frames"]), frames)
        self.assertEqual(video["avg_frame_rate"], f"{fps.numerator}/{fps.denominator}")
        self.assertAlmostEqual(float(video["duration"]), float(frames / fps), places=4)
        audio = json.loads(subprocess.run([FFPROBE, "-v", "error", "-select_streams", "a:0", "-show_entries",
                                           "stream=duration", "-of", "json", report["output"]],
                                          capture_output=True, text=True, check=True).stdout)["streams"][0]
        self.assertLess(abs(float(audio["duration"]) - float(video["duration"])), 0.03, "picture and sound the same length")
        for row in report["scenes"]:
            with self.subTest(scene=row["id"]):
                picture = probe(Path(row["picture"]["file"]), "nb_read_frames", count=True)
                self.assertEqual(int(picture["nb_read_frames"]), row["picture"]["frames"])
                self.assertEqual(row["sound"]["samples"], round(row["picture"]["frames"] * 48000 / fps))
                sound = json.loads(subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream=duration_ts,codec_name",
                                                   "-of", "json", row["sound"]["file"]],
                                                  capture_output=True, text=True, check=True).stdout)["streams"][0]
                self.assertEqual((sound["codec_name"], int(sound["duration_ts"])), ("pcm_f32le", row["sound"]["samples"]))
        return report

    def test_a_30_fps_recording_is_exported_at_30(self) -> None:
        report = self.check_export(self.source, "thirty", "30")
        self.assertIn("recording avg_frame_rate 30/1: 30 fps, kept", report["output_format"]["fps_reason"])

    def test_a_59_94_fps_recording_is_exported_at_59_94_and_previewed_at_29_97(self) -> None:
        source = recording(self.root / "ntsc.mkv", rate="60000/1001")
        report = self.check_export(source, "ntsc", "60000/1001")
        self.assertIn("59.94 fps (60000/1001), kept", report["output_format"]["fps_reason"])
        preview = render_version(self.root / "out" / "race-videos" / "ntsc", 1, "preview", self.options())
        self.assertEqual(preview["output_format"]["fps"], "30000/1001")
        qc = check_video(Path(preview["output"]), "preview", expected_duration=preview["expected_duration"],
                         ffmpeg=FFMPEG, ffprobe=FFPROBE, expected=preview["output_format"])
        self.assertTrue(qc["passed"], [c for c in qc["checks"] if not c["pass"]])

    def test_the_rate_prepare_stored_is_used_and_the_check_takes_it_from_the_report(self) -> None:
        project = self.project("stored")
        update_project(project, video={"width": 960, "height": 180, "avg_frame_rate": "60/1", "r_frame_rate": "60/1"})
        result = render_from_request({"project": str(project), "version": 1, "profile": "final", "ffmpeg": FFMPEG,
                                      "ffprobe": FFPROBE, **X264})
        self.assertEqual(result["render"]["output_format"]["fps"], "60")
        self.assertIn("(read by Prepare)", result["render"]["output_format"]["fps_reason"])
        self.assertTrue(result["technical_check"]["passed"], result["technical_check"])
        # The AI editor's own check of the file finds the report beside it; a request's own values win.
        output = result["render"]["output"]
        self.assertTrue(check_from_request({"path": output, "profile": "final", "ffmpeg": FFMPEG, "ffprobe": FFPROBE})["passed"])
        wrong = check_from_request({"path": output, "profile": "final", "ffmpeg": FFMPEG, "ffprobe": FFPROBE,
                                    "expected": {"fps": "60000/1001"}})
        rate = next(c for c in wrong["checks"] if c["check"] == "frame rate")
        self.assertFalse(rate["pass"], "59.94 is not taken for 60")
        self.assertIn("expected 59.940 fps", rate["detail"])

    def test_the_frames_of_a_recording_can_be_counted(self) -> None:
        source = recording(self.root / "count.mkv", rate="60000/1001", seconds=4)
        rate, packets = frame_render.count_frame_rate(FFPROBE, source)
        self.assertAlmostEqual(rate, 60000 / 1001, delta=0.05)
        self.assertGreater(packets, 200)
        self.assertEqual(frame_render.probe_streams(FFPROBE, self.root / "no-such-file.mkv"), {"streams": [], "format": {}})


class SharedStoreTests(RenderTestCase):
    """177: every version of a project shares one store of scene pictures and sounds."""

    def test_a_sound_only_revision_renders_no_picture_and_keeps_the_picture_bit_for_bit(self) -> None:
        project = self.project("sound-only")
        first = render_version(project, 1, "preview", self.options())
        self.assertEqual((first["scenes_rendered"], first["join"]["picture"]["state"]), (3, "rendered"))
        second_version = add_version(project, timeline(self.source, three_scenes(voice=2.0, game=0.2)), parent=1,
                                     answers="louder voice", source_duration=12.0, audio_streams=2)
        second = render_version(project, second_version, "preview", self.options())
        self.assertEqual((second["scenes_rendered"], second["scenes_reused"]), (0, 3), "no scene picture is rendered")
        self.assertEqual([row["picture"]["state"] for row in second["scenes"]], ["reused"] * 3)
        self.assertEqual([row["sound"]["state"] for row in second["scenes"]], ["rendered"] * 3)
        self.assertEqual(second["join"]["picture"]["state"], "reused", "nor the joined picture")
        self.assertEqual(picture_md5(Path(second["output"])), picture_md5(Path(first["output"])),
                         "the new version's picture is the earlier one's, bit for bit")
        self.assertNotEqual(hashlib.sha256(Path(second["output"]).read_bytes()).hexdigest(),
                            hashlib.sha256(Path(first["output"]).read_bytes()).hexdigest(), "the sound is new")
        # Every version's scenes live in the project's one store, none in the version's folder.
        self.assertTrue(all(Path(row["picture"]["file"]).is_relative_to(project / "scene-cache" / "preview" / "picture")
                            for row in second["scenes"]))
        self.assertFalse((version_dir(project, second_version) / "renders" / "scenes-preview").exists())

    def test_a_scene_that_moved_and_was_renamed_is_reused(self) -> None:
        project = self.project("moved")
        first = render_version(project, 1, "preview", self.options())
        one, two, three = three_scenes()
        moved = [dict(three, id="ending", beat="moved"), dict(one, id="opening", transition_in="dissolve",
                                                              transition_dur=0.5), dict(two, id="face", transition_in="cut")]
        number = add_version(project, timeline(self.source, moved), parent=1, source_duration=12.0, audio_streams=2)
        report = render_version(project, number, "preview", self.options())
        self.assertEqual(report["scenes_rendered"], 0)
        self.assertEqual([row["sound"]["state"] for row in report["scenes"]], ["reused"] * 3)
        self.assertEqual({row["picture"]["key"] for row in report["scenes"]},
                         {row["picture"]["key"] for row in first["scenes"]})
        self.assertEqual(report["join"]["picture"]["state"], "rendered", "a new order is a new join")

    def test_the_report_says_what_really_ran(self) -> None:
        project = self.project("report")
        report = render_version(project, 1, "preview", self.options())
        stored = read_json(version_dir(project, 1) / "renders" / "render-preview.json")
        self.assertEqual(stored, report)
        self.assertTrue(report["ffmpeg"])
        for row in report["scenes"]:
            self.assertEqual((row["picture"]["encoder"], row["picture"]["decode"]), ("libx264", "cpu"))
            made = read_json(Path(row["picture"]["file"]).with_suffix(".json"))
            self.assertEqual((made["key"], made["encoder"], made["decode"]), (row["picture"]["key"], "libx264", "cpu"))
        self.assertEqual(report["encoder"], "libx264")
        self.assertEqual(set(report["steps"]), {"scene_pictures", "scene_sounds", "picture_join", "sound_join", "loudness",
                                                "trim"})
        for key in ("version", "profile", "output", "expected_duration", "scenes_rendered", "scenes_reused", "privacy_masks",
                    "privacy_masks_applied", "privacy_store_fingerprint", "encoder", "seconds", "loudness_measured"):
            self.assertIn(key, report, "every key of the first report is still there")
        self.assertIsNone(report["export_quality"])

    def test_every_step_says_so_and_a_long_step_is_never_silent(self) -> None:
        project = self.project("progress")
        said: list[tuple[float, str]] = []
        with mock.patch.object(render, "PROGRESS_REPEAT_SECONDS", 0.05):
            render_version(project, 1, "preview", self.options(on_progress=lambda m: said.append((time.monotonic(), m))))
        messages = [message for _when, message in said]
        for words in ("Rendering the picture of scene 1 of 3", "Rendering the picture of scene 3 of 3",
                      "Mixing the sound of scene 2 of 3", "Joining the picture", "Joining the sound",
                      "Levelling the sound for upload"):
            self.assertIn(words, messages)
        self.assertGreater(len(messages), len(set(messages)), "a step that runs on is said again")
        gaps = [later - earlier for (earlier, _a), (later, _b) in zip(said, said[1:])]
        self.assertLess(max(gaps), 1.0)


class CompressOnceTests(RenderTestCase):
    """161.1: a final's scenes are lossless; its join is the one lossy picture encode."""

    def test_the_final_is_one_lossy_encode_from_lossless_scenes(self) -> None:
        store = self.root / "privacy"
        mask = self.root / "right-mask.png"
        subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi",
                        "-i", "color=black:s=320x180,drawbox=x=0:y=0:w=160:h=180:color=white:t=fill",
                        "-frames:v", "1", str(mask)], check=True)
        from media_manglers.core.race_video import privacy  # noqa: PLC0415

        privacy.save_mask("right", mask, store)
        project = self.project("once")
        update_project(project, layout=LAYOUT)   # as Prepare fixes it: the masks are drawn on this layout
        # A final render, checked (an export would remove the final's scenes once it is placed).
        with mock.patch.dict(os.environ, {"MEDIA_MANGLERS_RACE_VIDEO_PRIVACY": str(store)}):
            result = render_from_request({"project": str(project), "version": 1, "profile": "final", "ffmpeg": FFMPEG,
                                          "ffprobe": FFPROBE, **X264})
        report = result["render"]
        self.assertTrue(result["technical_check"]["passed"], result["technical_check"])
        self.assertEqual(report["scene_format"]["picture"], "h264 lossless, yuv420p, video only, mkv")
        for row in report["scenes"]:
            with self.subTest(scene=row["id"]):
                self.assertEqual(row["picture"]["settings"], ["-preset", "ultrafast", "-qp", "0"])
                stream = probe(Path(row["picture"]["file"]), "codec_name", "profile", "pix_fmt")
                self.assertEqual((stream["codec_name"], stream["profile"], stream["pix_fmt"]),
                                 ("h264", "High 4:4:4 Predictive", "yuv420p"))
                self.assertEqual(Path(row["sound"]["file"]).suffix, ".wav")
        # The one lossy encode: the join, at today's final settings. No keyframe every half second (226:
        # YouTube's spacing made the file two to four times bigger for no visible gain).
        self.assertEqual((report["join"]["picture"]["state"], report["join"]["picture"]["encoder"]), ("rendered", "libx264"))
        self.assertEqual(report["join"]["picture"]["settings"], ["-preset", "medium", "-crf", "18", "-profile:v", "high"])
        self.assertEqual(report["join"]["picture"]["settings"], render.PROFILES["final"]["x264"])
        self.assertNotEqual(keyframes(Path(report["output"]))[:4], [0, 15, 30, 45])
        # The privacy blur is in the lossless scene of the right camera.
        right = Path(report["scenes"][1]["picture"]["file"])
        private, public = detail(right, 0.5, (100, 150, 800, 700)), detail(right, 0.5, (1020, 150, 800, 700))
        self.assertGreater(public, 10)
        self.assertLess(private, public / 5, f"the private half is blurred ({private:.1f} vs {public:.1f})")
        self.assertEqual(report["scenes"][1]["picture"]["masks_applied"], ["right"])

    def test_the_export_quality_comes_from_the_request_the_project_or_the_main_setting(self) -> None:
        project = self.project("quality")
        self.assertEqual(render.export_quality(project), ("youtube", "default"))
        saved = self.settings / "MediaManglers" / "workbench" / "settings.json"
        saved.parent.mkdir(parents=True)
        saved.write_text(json.dumps({"schemaVersion": 1, "settings": {"race_video_export_quality": "highest"}}),
                         encoding="utf-8")
        self.assertEqual(render.export_quality(project), ("highest", "main_setting"))
        (project / "editor-settings.json").write_text(json.dumps({"export_quality": "smaller"}), encoding="utf-8")
        self.assertEqual(render.export_quality(project), ("smaller", "project"))
        self.assertEqual(render.export_quality(project, "youtube"), ("youtube", "request"))
        with self.assertRaisesRegex(ValueError, "export_quality must be one of youtube, highest, smaller"):
            render.export_quality(project, "ultra")
        # A real export at the project's choice: the smaller file's settings, and sound at 192k.
        result = export_version(project, 1, self.options())
        report = result["render"]
        self.assertTrue(result["technical_check"]["passed"], result["technical_check"])
        self.assertEqual((report["export_quality"], report["export_quality_source"]), ("smaller", "project"))
        self.assertEqual(report["output_format"]["sound"]["bitrate"], "192k")
        self.assertIn("22", report["join"]["picture"]["settings"])
        bitrate = json.loads(subprocess.run([FFPROBE, "-v", "error", "-select_streams", "a:0", "-show_entries",
                                             "stream=bit_rate", "-of", "json", report["output"]],
                                            capture_output=True, text=True, check=True).stdout)["streams"][0]["bit_rate"]
        self.assertLess(int(bitrate), 230_000)
        # Another quality only joins again: every scene is reused (the export removed the final's scenes,
        # so the first final after it renders them again).
        first = render_version(project, 1, "final", self.options(export_quality="highest"))
        self.assertEqual(first["scenes_rendered"], 3)
        again = render_version(project, 1, "final", self.options(export_quality="youtube"))
        self.assertEqual((again["scenes_rendered"], again["join"]["picture"]["state"]), (0, "rendered"))
        self.assertEqual((first["export_quality"], first["export_quality_source"]), ("highest", "request"))

    def test_a_validation_run_keeps_its_own_final_and_an_export_refuses_one(self) -> None:
        # 226 (M5): a validation render never replaces the real final, its report or its export.
        project = self.project("bigger")
        exported = export_version(project, 1, self.options())
        self.assertTrue(exported["export"], exported["technical_check"])
        renders = version_dir(project, 1) / "renders"
        real = {name: sha256(renders / name) for name in ("final.mp4", "render-final.json", "qc-final.json")}
        result = render_from_request({"project": str(project), "version": 1, "profile": "final", "ffmpeg": FFMPEG,
                                      "ffprobe": FFPROBE, "validation_size": [640, 360], **X264})
        report = result["render"]
        self.assertEqual(Path(report["output"]), renders / "final-640x360.mp4")
        self.assertEqual((report["output_format"]["width"], report["output_format"]["height"]), (640, 360))
        self.assertEqual(report["validation_size"], [640, 360])
        self.assertTrue(result["technical_check"]["passed"], result["technical_check"])
        self.assertEqual(read_json(renders / "render-final-640x360.json"), report)
        self.assertTrue(read_json(renders / "qc-final-640x360.json")["passed"])
        self.assertEqual({name: sha256(renders / name) for name in real}, real, "the real final is left as it was")
        self.assertTrue(os.path.samefile(renders / "final.mp4", exported["export"]))
        self.assertEqual((report["readable_name"], report["trim"]), ("", None), "no readable name and no trim")
        self.assertEqual(sorted(p.name for p in renders.glob("*final*.mp4")),
                         ["bigger-v001-final.mp4", "final-640x360.mp4", "final.mp4"])
        # The AI editor's own check of the validation file finds that file's own report.
        checked = check_from_request({"path": report["output"], "profile": "final", "ffmpeg": FFMPEG, "ffprobe": FFPROBE})
        self.assertTrue(checked["passed"], checked)
        self.assertEqual((checked["expected"]["width"], checked["expected"]["height"]), (640, 360))
        # An export refuses a validation size, from a request or from the code, and changes nothing.
        meta = read_json(project / "project.json")
        for name, call in (
                ("request", lambda: export_from_request({"project": str(project), "version": 1, "ffmpeg": FFMPEG,
                                                         "ffprobe": FFPROBE, "validation_size": [640, 360], **X264})),
                ("code", lambda: export_version(project, 1, self.options(validation_size=(640, 360))))):
            with self.subTest(export=name), self.assertRaisesRegex(ValueError, "validation_size is for a validation render"):
                call()
        self.assertEqual(read_json(project / "project.json"), meta)
        self.assertEqual(sorted(p.name for p in (project / "export").iterdir()), ["bigger-v001.mp4"])
        with self.assertRaisesRegex(ValueError, "validation_size"):
            render.validation_size([641, 360])


class ExportAndNameTests(RenderTestCase):
    """178: readable render names, the export's name and the exported mark."""

    def test_the_readable_name_is_renewed_after_every_render(self) -> None:
        project = self.project("named", editor_label="Claude Opus")
        renders = version_dir(project, 1) / "renders"
        readable = renders / "named-v001-claude-opus-preview.mp4"
        # A stale name from an earlier render, pointing at another file, is replaced.
        renders.mkdir(parents=True)
        (renders / "old.bin").write_bytes(b"an older render")
        os.link(renders / "old.bin", readable)
        first = render_version(project, 1, "preview", self.options())
        self.assertEqual(first["readable_name"], str(readable))
        self.assertTrue(os.path.samefile(readable, renders / "preview.mp4"))
        os.link(renders / "preview.mp4", renders / "first.bin")
        render_version(project, 1, "preview", self.options())
        self.assertTrue(os.path.samefile(readable, renders / "preview.mp4"), "the name points at the new render")
        self.assertFalse(os.path.samefile(readable, renders / "first.bin"))
        self.assertEqual(sorted(p.name for p in renders.glob("*.mp4")), ["named-v001-claude-opus-preview.mp4", "preview.mp4"])
        # Without a label, the name has none.
        add_version(project, timeline(self.source, three_scenes()), parent=1, source_duration=12.0, audio_streams=2)
        second = render_version(project, 2, "preview", self.options())
        self.assertEqual(Path(second["readable_name"]).name, "named-v002-preview.mp4")

    def test_the_export_name_has_the_label_and_the_entry_keeps_it(self) -> None:
        project = self.project("exported", editor_label="codex-gpt")
        add_version(project, timeline(self.source, three_scenes()), parent=1, source_duration=12.0, audio_streams=2)
        add_version(project, timeline(self.source, three_scenes()), parent=2, source_duration=12.0, audio_streams=2)
        first = export_version(project, 1, self.options())
        second = export_version(project, 2, self.options())
        self.assertEqual(Path(first["export"]).name, "exported-v001-codex-gpt.mp4")
        self.assertEqual(Path(second["export"]).name, "exported-v002.mp4")
        entries = {entry["version"]: entry for entry in read_json(project / "project.json")["versions"]}
        self.assertEqual(entries[1]["export"], "exported-v001-codex-gpt.mp4")
        versions = {v["version"]: v for v in list_projects(self.root / "out")[0]["versions"]}
        self.assertEqual((versions[1]["exported"], versions[1]["export"]), (True, first["export"]))
        self.assertEqual((versions[2]["exported"], versions[2]["export"]), (True, second["export"]))
        self.assertEqual((versions[3]["exported"], versions[3]["export"]), (False, ""))
        # A version exported before the name was kept is still known by the name exports had then.
        (project / "export" / "exported-v003.mp4").write_bytes(b"an export from before")
        versions = {v["version"]: v for v in library.project_summary(project)["versions"]}
        self.assertTrue(versions[3]["exported"])

    def test_an_export_removes_the_final_scene_store_and_exporting_again_renders_it_again(self) -> None:
        # 226 (M11): a final's lossless scenes take hundreds of megabytes a minute; a project keeps them
        # only while a final is being made. The previews' store is left alone.
        project = self.project("disk")
        render_version(project, 1, "preview", self.options())
        previews = sorted(p.name for p in (project / "scene-cache" / "preview").rglob("*"))
        first = export_version(project, 1, self.options())
        self.assertTrue(first["export"], first["technical_check"])
        self.assertFalse((project / "scene-cache" / "final").exists(), "the final's scenes are removed")
        self.assertEqual((first["final_store"]["files_not_removed"], first["final_store"]["store_left"]), (0, False))
        self.assertGreater(first["final_store"]["files_removed"], 0)
        self.assertTrue(Path(first["render"]["output"]).is_file(), "the final itself stays")
        self.assertTrue(os.path.samefile(first["export"], first["render"]["output"]))
        self.assertEqual(sorted(p.name for p in (project / "scene-cache" / "preview").rglob("*")), previews)
        again = export_version(project, 1, self.options())
        self.assertEqual(again["render"]["scenes_rendered"], 3, "exporting again renders the final's scenes again")
        self.assertTrue(again["technical_check"]["passed"], again["technical_check"])
        self.assertFalse((project / "scene-cache" / "final").exists())
        self.assertFalse((project / "scene-cache" / "render.lock").exists())


class CheckNamesTests(RenderTestCase):
    """226 (M2): the technical check of the readable name or the export expects what its render made."""

    def test_the_readable_names_and_the_export_are_checked_against_their_render_report(self) -> None:
        for rate in ("30", "60000/1001"):
            with self.subTest(rate=rate):
                name = "names-30" if rate == "30" else "names-5994"
                source = self.source if rate == "30" else recording(self.root / "ntsc.mkv", rate=rate)
                project = self.project(name, source=source)
                exported = export_version(project, 1, self.options())
                self.assertTrue(exported["export"], exported["technical_check"])
                preview = render_version(project, 1, "preview", self.options())
                renders = version_dir(project, 1) / "renders"
                files = {"readable final": (renders / f"{name}-v001-final.mp4", "final", rate),
                         "export": (Path(exported["export"]), "final", rate),
                         "readable preview": (Path(preview["readable_name"]), "preview", preview["output_format"]["fps"])}
                if rate == "30":
                    # An export copied (an export folder that cannot link) is found by its name, not as the
                    # same file.
                    real_link = os.link

                    def link(source, target, *args, **kwargs):
                        if Path(target).parent.name == "export":
                            raise OSError(1, "Incorrect function")
                        return real_link(source, target, *args, **kwargs)

                    with mock.patch.object(library.os, "link", link):
                        copied = export_version(project, 1, self.options())
                    self.assertFalse(os.path.samefile(copied["export"], copied["render"]["output"]))
                    files["copied export"] = (Path(copied["export"]), "final", rate)
                for label, (path, profile, fps) in files.items():
                    with self.subTest(rate=rate, file=label):
                        self.assertTrue(path.is_file(), path)
                        qc = check_from_request({"path": str(path), "profile": profile, "ffmpeg": FFMPEG, "ffprobe": FFPROBE})
                        self.assertTrue(qc["passed"], [c for c in qc["checks"] if not c["pass"]])
                        self.assertEqual((qc["expected"]["fps"], qc["expected"]["from"]), (fps, "given"))
        # A file no render made is checked against its profile, as before.
        stray = self.root / "out" / "stray.mp4"
        shutil.copyfile(Path(exported["export"]), stray)
        self.assertEqual(check_from_request({"path": str(stray), "profile": "final", "ffmpeg": FFMPEG,
                                             "ffprobe": FFPROBE})["expected"]["from"], "profile")


class SoundFadeTests(RenderTestCase):
    """226 (M7): the finished video's sound fades in over 0.5 s, as before; the picture over 0.8 s."""

    def test_the_sound_fades_in_over_half_a_second_and_the_picture_over_0_8(self) -> None:
        project = self.project("fades", scenes=[scene("s01", 1.0, 4.0, audio={"voice": 1.0, "game": 0.0})])
        report = render_version(project, 1, "preview", self.options())
        raw = subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-i", report["output"], "-map", "0:a:0", "-ac", "1",
                              "-ar", "48000", "-f", "f32le", "-"], capture_output=True, check=True).stdout
        samples = array("f")
        samples.frombytes(raw)

        def level(start: float, end: float) -> float:
            part = samples[int(start * 48000):int(end * 48000)]
            return (sum(value * value for value in part) / len(part)) ** 0.5

        steady = level(1.5, 2.0)
        self.assertAlmostEqual(level(0.2, 0.3) / steady, 0.5, delta=0.1, msg="half way up at a quarter second")
        self.assertGreater(level(0.55, 0.65) / steady, 0.93, "fully up after half a second")
        # The picture: its brightness against the unfaded scene picture, frame 12 of a 24-frame fade.
        unfaded = Path(report["scenes"][0]["picture"]["file"])
        faded, plain = gray_frame(Path(report["output"]), 0.4), gray_frame(unfaded, 0.4)
        ratio = (sum(faded) / len(faded) - 16) / (sum(plain) / len(plain) - 16)
        self.assertAlmostEqual(ratio, 0.5, delta=0.12, msg="the picture is half way up at 0.4 s")


class FallbackReasonTests(RenderTestCase):
    """226 (M10): the render report says why a scene was tried again or x264 took over, in FFmpeg's words."""

    def test_the_report_says_why_a_scene_and_the_join_were_tried_again_or_fell_back(self) -> None:
        project = self.project("fallback", scenes=[scene("s01", 0.5, 2.0), scene("s02", 3.0, 4.5)])
        # NVENC that cannot encode (a preset it does not have), as when the card's driver refuses.
        with mock.patch.object(render, "nvenc_available", return_value=True), \
                mock.patch.dict(render.PROFILES["preview"], {"nvenc": ["-preset", "no-such-preset"]}):
            report = render_version(project, 1, "preview", RenderOptions(ffmpeg=FFMPEG, ffprobe=FFPROBE))
        for row in report["scenes"]:
            picture = row["picture"]
            with self.subTest(scene=row["id"]):
                self.assertEqual((picture["encoder"], picture["decode"]), ("libx264", "cpu after a retry"))
                self.assertTrue(picture["retry_reason"], "why it was tried again on the CPU")
                self.assertTrue(picture["fallback_reason"], "why x264 took over")
                made = read_json(Path(picture["file"]).with_suffix(".json"))
                self.assertEqual((made["retry_reason"], made["fallback_reason"]),
                                 (picture["retry_reason"], picture["fallback_reason"]))
        join = report["join"]["picture"]
        self.assertEqual(join["encoder"], "libx264")
        self.assertTrue(join["fallback_reason"], "why x264 took over the join")
        # Nothing went wrong: nothing to say.
        plain = render_version(self.project("plain"), 1, "preview", self.options())
        self.assertEqual({(row["picture"]["retry_reason"], row["picture"]["fallback_reason"]) for row in plain["scenes"]},
                         {("", "")})
        self.assertEqual(plain["join"]["picture"]["fallback_reason"], "")


class LockTests(RenderTestCase):
    """Two renders of one project take turns; a lock is never taken from a process that still runs."""

    def hold(self, project: Path, pid: int, **extra) -> Path:
        lock = project / "scene-cache" / "render.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(json.dumps({"pid": pid, "host": platform.node(), "started": "earlier",
                                    "started_epoch": time.time(), "token": "someone-else", **extra}), encoding="utf-8")
        return lock

    def other_process(self, seconds: float) -> subprocess.Popen:
        process = subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({seconds})"])
        self.addCleanup(lambda: (process.kill(), process.wait()))
        return process

    def test_a_render_waits_while_another_running_render_holds_the_lock(self) -> None:
        project = self.project("busy")
        other = self.other_process(60)
        lock = self.hold(project, other.pid)
        held = lock.read_text(encoding="utf-8")
        said: list[str] = []
        outcome: dict = {}
        thread = threading.Thread(target=lambda: outcome.update(report=render_version(
            project, 1, "preview", self.options(on_progress=said.append))))
        with mock.patch.object(render, "LOCK_RETRY_SECONDS", 0.2):
            thread.start()
            time.sleep(3)
            self.assertTrue(thread.is_alive(), "the render waits")
            self.assertFalse((version_dir(project, 1) / "renders" / "preview.mp4").exists())
            self.assertEqual(lock.read_text(encoding="utf-8"), held, "the running process's lock is left alone")
            self.assertIn("Waiting for another render of this project to finish", said)
            lock.unlink()   # the other render has finished
            thread.join(timeout=120)
        self.assertIn("report", outcome)
        self.assertGreaterEqual(outcome["report"]["lock"]["waited_seconds"], 2.5)
        self.assertFalse(lock.exists())

    def test_a_render_that_may_not_wait_says_so_and_leaves_the_lock(self) -> None:
        project = self.project("limited")
        other = self.other_process(60)
        lock = self.hold(project, other.pid)
        with mock.patch.object(render, "LOCK_RETRY_SECONDS", 0.2):
            with self.assertRaisesRegex(render.RenderError, f"another render of this project is still running \\(process {other.pid}"):
                render_version(project, 1, "preview", self.options(lock_wait_seconds=0.5))
        self.assertTrue(lock.exists())

    def test_the_lock_of_a_process_that_has_ended_is_taken_over(self) -> None:
        project = self.project("ended")
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()
        self.assertFalse(render.process_alive(gone.pid))
        self.assertTrue(render.process_alive(os.getpid()))
        lock = self.hold(project, gone.pid)
        report = render_version(project, 1, "preview", self.options(lock_wait_seconds=0))
        self.assertIn(f"process {gone.pid}, which has ended", report["lock"]["took_over"])
        self.assertFalse(lock.exists())

    def test_a_lock_older_than_six_hours_is_taken_over(self) -> None:
        project = self.project("old")
        other = self.other_process(60)
        self.hold(project, other.pid, started_epoch=time.time() - 7 * 3600)
        report = render_version(project, 1, "preview", self.options(lock_wait_seconds=0))
        self.assertIn("older than 6 hours", report["lock"]["took_over"])

    def ended(self) -> int:
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()
        return gone.pid

    def test_a_takeover_never_removes_a_live_lock_and_never_renames_one(self) -> None:
        # 226 (M3): this render read a dead process's lock; meanwhile another render took it over and
        # holds it now. The live lock stays, also on a drive that cannot make hard links.
        project = self.project("live")
        lock = self.hold(project, self.ended())
        dead = json.loads(lock.read_text(encoding="utf-8"))
        self.hold(project, os.getpid(), token="live")
        moved: list[str] = []
        real_rename, real_replace = os.rename, os.replace

        def rename(source, target, *args, **kwargs):
            moved.append(Path(source).name)
            return real_rename(source, target, *args, **kwargs)

        def replace(source, target, *args, **kwargs):
            moved.append(Path(source).name)
            return real_replace(source, target, *args, **kwargs)

        with mock.patch.object(render.os, "link", side_effect=OSError(1, "Incorrect function")), \
                mock.patch.object(render.os, "rename", rename), mock.patch.object(render.os, "replace", replace):
            render.ProjectLock(project)._take_over(dead)
        self.assertEqual(json.loads(lock.read_text(encoding="utf-8"))["token"], "live", "the live lock stays")
        self.assertEqual([name for name in moved if name.startswith("render.lock")], [], "a lock is never renamed")
        self.assertEqual(sorted(p.name for p in lock.parent.iterdir()), ["render.lock"], "and nothing is left beside it")

    def test_only_one_render_takes_a_stale_lock_over_at_a_time(self) -> None:
        # 226 (M3): an exclusive render.lock.takeover first; one left by a render that stopped is stale after 60 s.
        project = self.project("takeover")
        pid = self.ended()
        lock = self.hold(project, pid)
        dead = json.loads(lock.read_text(encoding="utf-8"))
        takeover = lock.with_name("render.lock.takeover")
        takeover.write_text(json.dumps({"pid": 1, "token": "another render"}), encoding="utf-8")
        self.assertFalse(render.ProjectLock(project)._take_over(dead), "another render is taking it over: wait")
        self.assertTrue(lock.exists())
        self.assertEqual(json.loads(takeover.read_text(encoding="utf-8"))["token"], "another render")
        old = time.time() - 120
        os.utime(takeover, (old, old))
        report = render_version(project, 1, "preview", self.options(lock_wait_seconds=10))
        self.assertIn(f"process {pid}, which has ended", report["lock"]["took_over"])
        self.assertEqual(sorted(p.name for p in lock.parent.iterdir() if p.name.startswith("render.lock")), [],
                         "the lock and the takeover file are gone")

    def test_a_process_number_given_out_again_does_not_keep_a_lock(self) -> None:
        # 226 (M13): Windows gives process numbers out again. A running process with the lock's number
        # that started after the lock was written, or not when the lock says, is another program.
        project = self.project("reused")
        other = self.other_process(60)
        for case, extra in (("written before it started", {"started_epoch": time.time() - 600}),
                            ("its start time differs", {"process_started_epoch": time.time() - 900})):
            with self.subTest(case=case):
                lock = self.hold(project, other.pid, **extra)
                report = render_version(project, 1, "preview", self.options(lock_wait_seconds=0))
                self.assertIn(f"process {other.pid}, which has ended", report["lock"]["took_over"])
                self.assertFalse(lock.exists())

    def test_the_lock_keeps_when_its_process_started(self) -> None:
        project = self.project("started")
        own = render.process_start_time(os.getpid())
        self.assertIsNotNone(own)
        with render.ProjectLock(project) as held:
            data = json.loads(held.path.read_text(encoding="utf-8"))
        self.assertAlmostEqual(data["process_started_epoch"], own, places=3)
        self.assertLess(own, data["started_epoch"])
        child = self.other_process(30)
        started = render.process_start_time(child.pid)
        self.assertGreater(started, own)
        self.assertLess(abs(started - time.time()), 30)

    def test_an_export_holds_one_lock_from_its_render_to_its_placement(self) -> None:
        # 226 (M4): no other render can replace the final between its check and the export.
        project = self.project("held")
        lock = project / "scene-cache" / "render.lock"
        seen: dict[str, dict] = {}
        real_render, real_check, real_place = render._render_locked, library.check_video, library.replace_durably

        def holder() -> dict:
            return json.loads(lock.read_text(encoding="utf-8")) if lock.exists() else {}

        def rendering(*args, **kwargs):
            seen["render"] = holder()
            return real_render(*args, **kwargs)

        def check(*args, **kwargs):
            seen["check"] = holder()
            return real_check(*args, **kwargs)

        def place(*args, **kwargs):
            seen["placement"] = holder()
            return real_place(*args, **kwargs)

        with mock.patch.object(render, "_render_locked", rendering), mock.patch.object(library, "check_video", check), \
                mock.patch.object(library, "replace_durably", place):
            result = export_version(project, 1, self.options())
        self.assertTrue(result["export"], result["technical_check"])
        for step in ("render", "check", "placement"):
            with self.subTest(step=step):
                self.assertEqual(seen[step].get("pid"), os.getpid(), f"the lock is held during the {step}")
                self.assertEqual(seen[step].get("token"), seen["render"].get("token"), "one lock throughout")
        self.assertFalse(lock.exists(), "let go once the export is placed")
        with self.assertRaisesRegex(ValueError, "not held"):
            render_version(project, 1, "final", self.options(), lock=render.ProjectLock(project))


class TrimTests(RenderTestCase):
    """The store keeps what the newest versions, the one rendered and any exported one use."""

    def test_the_store_keeps_the_newest_versions_and_exported_ones(self) -> None:
        project = create_project(self.root / "out", self.source, "trimmed")
        reports = {}
        for number in range(1, 6):
            # Each version's one scene starts somewhere else, so each has its own picture and sound.
            add_version(project, timeline(self.source, [scene("s01", 0.5 * number, 0.5 * number + 1.5)]),
                        source_duration=12.0, audio_streams=2)
        old_scenes = version_dir(project, 1) / "renders" / "scenes-preview" / "s01.mp4"
        old_scenes.parent.mkdir(parents=True)
        old_scenes.write_bytes(b"a scene from before the store")
        reports[1] = render_version(project, 1, "preview", self.options())
        exported = export_version(project, 1, self.options())
        self.assertTrue(exported["export"])
        for number in range(2, 6):
            reports[number] = render_version(project, number, "preview", self.options())

        def kept(number: int) -> bool:
            row = reports[number]["scenes"][0]
            return Path(row["picture"]["file"]).exists() and Path(row["sound"]["file"]).exists()

        self.assertEqual({number: kept(number) for number in range(1, 6)},
                         {1: True, 2: False, 3: True, 4: True, 5: True})
        self.assertEqual(reports[5]["trim"]["versions_kept"], [1, 3, 4, 5])
        self.assertTrue(old_scenes.exists(), "old per-version scene folders are left as they were")
        # A final keeps only the newest final's (and an export removed the final's scenes altogether).
        self.assertFalse((project / "scene-cache" / "final").exists())
        fourth = render_version(project, 4, "final", self.options())
        render_version(project, 5, "final", self.options())
        self.assertFalse(Path(fourth["scenes"][0]["picture"]["file"]).exists())

    def test_a_file_that_cannot_be_removed_is_passed_over(self) -> None:
        project = self.project("stuck")
        render_version(project, 1, "preview", self.options())
        add_version(project, timeline(self.source, [scene("s01", 6.0, 8.0)]), parent=1, source_duration=12.0,
                    audio_streams=2)
        real = Path.unlink

        def refuse(path, *args, **kwargs):
            if path.suffix == ".mkv" and "scene-cache" in path.parts:
                raise PermissionError("in use")
            return real(path, *args, **kwargs)

        with mock.patch.object(render, "NEWEST_PREVIEWS_KEPT", 1), mock.patch.object(Path, "unlink", refuse):
            report = render_version(project, 2, "preview", self.options())
        self.assertGreater(report["trim"]["files_not_removed"], 0)
        self.assertTrue(Path(report["output"]).exists())


@unittest.skipUnless(FFMPEG and FFPROBE and render.nvenc_available(FFMPEG or "ffmpeg"),
                     "an NVIDIA card that NVENC can encode on is required")
class NvencTests(RenderTestCase):
    def test_a_final_is_lossless_on_nvenc_and_says_how_it_was_decoded(self) -> None:
        project = self.project("nvenc")
        # A checked final (an export would remove its scenes once placed).
        result = render_from_request({"project": str(project), "version": 1, "profile": "final", "ffmpeg": FFMPEG,
                                      "ffprobe": FFPROBE})
        report = result["render"]
        self.assertTrue(result["technical_check"]["passed"], result["technical_check"])
        for row in report["scenes"]:
            with self.subTest(scene=row["id"]):
                self.assertEqual((row["picture"]["encoder"], row["picture"]["settings"]), ("h264_nvenc", ["-tune", "lossless"]))
                self.assertEqual(row["picture"]["decode"], "cuda")
                self.assertEqual(probe(Path(row["picture"]["file"]), "profile")["profile"], "High 4:4:4 Predictive")
        self.assertEqual(report["encoder"], "h264_nvenc")

    def test_a_silent_fall_back_to_the_cpu_is_reported_with_ffmpegs_words(self) -> None:
        # NVDEC decodes H.264 only up to 4096 pixels wide: FFmpeg falls back to the CPU inside the run.
        wide = recording(self.root / "wide.mkv", panel=(1536, 256), seconds=4)
        layout = {"width": 4608, "height": 256,
                  "panels": {"left": [0, 0, 1536, 256], "center": [1536, 0, 1536, 256], "right": [3072, 0, 1536, 256]}}
        project = create_project(self.root / "out", wide, "wide")
        add_version(project, {**timeline(wide, [scene("s01", 0.5, 2.0)]), "source_layout": layout},
                    source_duration=4.0, audio_streams=2)
        report = render_version(project, 1, "preview", RenderOptions(ffmpeg=FFMPEG, ffprobe=FFPROBE))
        decode = report["scenes"][0]["picture"]["decode"]
        self.assertTrue(decode.startswith("cpu after CUDA failed: "), decode)
        self.assertIn("Failed setup for format cuda", decode)


if __name__ == "__main__":
    unittest.main()
