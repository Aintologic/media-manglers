"""Wave 7 (226): the AI Video Editor's pictures come out of the one frame renderer byte for byte.

The editor's own picture code at 9e065e4, the last commit before Wave 7, is taken out of git into a
scratch folder and imported beside today's code under another package name. Both run on the same
synthetic recordings, and the SHA-256 of every still and contact sheet must match: the analysis
stills (masked and not), the close looks (whole panel and a zoomed region with its time stamp), the
review kit's stills and sheets, and the mask editor's camera still, first from the shared functions
and then from the editor's own close_look, review_kit and panel_still, old and new. The filter text and commands
the editor built are compared with the shared builder's too. The frame renderer's own functions
from before are checked as well: their source is unchanged and their screenshots are the same.

Skipped, with the reason, when git, that commit or FFmpeg is not available.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers.core import frame_render  # noqa: E402

BASELINE = "9e065e4"
PACKAGE = "mm_baseline_9e065e4"
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
GIT = shutil.which("git")
LAYOUT = {"width": 960, "height": 180,
          "panels": {"left": [0, 0, 320, 180], "center": [320, 0, 320, 180], "right": [640, 0, 320, 180]}}
# The frame renderer's functions from before Wave 7; probe_video gained a field and is checked by its output.
UNCHANGED = ("_run", "_failure", "seconds_text", "is_complete_jpeg", "jpeg_size", "plan_batches", "render_frame",
             "crop_panel", "_panels_of", "_single", "_batch", "_progress_writer", "render_moments", "render_exact",
             "fps_filter", "render_cadence", "render_from_request")


def _baseline_problem() -> str:
    """Why the 9e065e4 code cannot be had here, or "" when it can."""

    if not (FFMPEG and FFPROBE):
        return "FFmpeg and FFprobe are required"
    if not GIT:
        return "git is required to take the 9e065e4 code out of the repository"
    found = subprocess.run([GIT, "-C", str(REPO_ROOT), "cat-file", "-e", f"{BASELINE}^{{commit}}"],
                           capture_output=True, check=False)
    if found.returncode != 0:
        return f"commit {BASELINE} is not in this clone (a shallow clone?)"
    return ""


def _digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _digests(paths) -> list[str]:
    return [_digest(path) for path in paths]


def _clip(path: Path, size: str, seconds: int, rate: int = 30) -> Path:
    subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=size={size}:rate={rate}:duration={seconds}", "-c:v", "libx264", "-g", str(rate * 2),
                    "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def _three_panels(path: Path, seconds: int = 10) -> Path:
    """The editor's test layout: three different 320x180 panels side by side."""

    subprocess.run([
        FFMPEG, "-hide_banner", "-v", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc2=s=320x180:r=30:d={seconds}",
        "-f", "lavfi", "-i", f"testsrc=s=320x180:r=30:d={seconds},drawbox=x=0:y=0:w=320:h=180:color=red:t=fill:enable='gte(t,5)'",
        "-f", "lavfi", "-i", f"testsrc2=s=320x180:r=30:d={seconds},hue=s=0",
        "-filter_complex", "[0:v][1:v][2:v]hstack=inputs=3,format=yuv420p[v]",
        "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", str(path),
    ], check=True)
    return path


def _three_panels_with_sound(path: Path, seconds: int = 30) -> Path:
    """The editor's test layout with a voice track (a tone in bursts) and a game track (pink noise)."""

    subprocess.run([
        FFMPEG, "-hide_banner", "-v", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc2=s=320x180:r=30:d={seconds}",
        "-f", "lavfi", "-i", f"testsrc=s=320x180:r=30:d={seconds},drawbox=x=0:y=0:w=320:h=180:color=red:t=fill:enable='gte(t,12)'",
        "-f", "lavfi", "-i", f"testsrc2=s=320x180:r=30:d={seconds},hue=s=0",
        "-f", "lavfi", "-i", f"sine=frequency=300:sample_rate=48000:duration={seconds},volume='if(lt(mod(t,5),2),1,0)':eval=frame",
        "-f", "lavfi", "-i", f"anoisesrc=color=pink:amplitude=0.05:sample_rate=48000:duration={seconds}",
        "-filter_complex", "[0:v][1:v][2:v]hstack=inputs=3,format=yuv420p[v]",
        "-map", "[v]", "-map", "3:a", "-map", "4:a", "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", "-shortest", str(path),
    ], check=True)
    return path


def _titled_tracks(path: Path, tracks: list[tuple[str, str]], seconds: int = 20) -> Path:
    """A small recording with one FLAC audio track per (lavfi source, track name)."""

    command = [FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size=64x48:rate=5:duration={seconds}"]
    for source, _title in tracks:
        command += ["-f", "lavfi", "-i", source]
    command += ["-map", "0:v", *[part for index in range(len(tracks)) for part in ("-map", f"{index + 1}:a")]]
    for index, (_source, title) in enumerate(tracks):
        command += [f"-metadata:s:a:{index}", f"title={title}"]
    subprocess.run([*command, "-t", str(seconds), "-c:v", "ffv1", "-c:a", "flac", "-ac", "2", "-ar", "48000", str(path)],
                   check=True)
    return path


def _mask(path: Path, drawing: str) -> Path:
    subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=black:s=320x180,{drawing}",
                    "-frames:v", "1", str(path)], check=True)
    return path


class _Recorder:
    """Stands in for FFmpeg: notes each command and leaves an empty file where it would write."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command, *args, **kwargs):
        self.commands.append([str(part) for part in command])
        Path(command[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(command[-1]).write_bytes(b"")
        return subprocess.CompletedProcess(command, 0, "", "")


PROBLEM = _baseline_problem()


@unittest.skipIf(bool(PROBLEM), PROBLEM)
class Wave7IdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        archive = subprocess.run([GIT, "-C", str(REPO_ROOT), "archive", "--format=tar", BASELINE, "src/media_manglers"],
                                 capture_output=True, check=True).stdout
        base = cls.root / "baseline"
        package = (base / PACKAGE).resolve()
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            for member in tar.getmembers():
                prefix = "src/media_manglers/"
                if not member.isfile() or not member.name.startswith(prefix):
                    continue
                target = (package / member.name[len(prefix):]).resolve()
                if not target.is_relative_to(package):
                    raise RuntimeError(f"unexpected path in the {BASELINE} archive: {member.name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(tar.extractfile(member).read())
        cls.base = str(base)
        sys.path.insert(0, cls.base)
        importlib.invalidate_caches()
        writing = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            cls.old_frames = importlib.import_module(f"{PACKAGE}.core.frame_render")
            cls.old_analysis = importlib.import_module(f"{PACKAGE}.core.race_video.analysis")
            cls.old_review = importlib.import_module(f"{PACKAGE}.core.race_video.review")
            cls.old_library = importlib.import_module(f"{PACKAGE}.core.race_video.library")
            cls.old_render = importlib.import_module(f"{PACKAGE}.core.race_video.render")
            cls.old_privacy = importlib.import_module(f"{PACKAGE}.core.race_video.privacy")
            cls.old_project = importlib.import_module(f"{PACKAGE}.core.race_video.project")
            cls.old_cross = importlib.import_module(f"{PACKAGE}.core.cross_track_check")
        finally:
            sys.dont_write_bytecode = writing
        assert Path(cls.old_analysis.__file__).resolve().is_relative_to(package)

        cls.source = _three_panels(cls.root / "race.mkv")
        cls.masks = {"right": _mask(cls.root / "right.png", "drawbox=x=0:y=0:w=160:h=180:color=white:t=fill"),
                     "left": _mask(cls.root / "left.png", "drawbox=x=200:y=40:w=100:h=100:color=white:t=fill")}
        # The whole-frame masks the editor builds: at the stills' size, and at the recording's own size.
        cls.still_mask = cls.old_privacy.build_full_frame_mask(FFMPEG, LAYOUT, cls.masks, cls.root / "mask-1920.png", 1920, 360)
        cls.full_mask = cls.old_privacy.build_full_frame_mask(FFMPEG, LAYOUT, cls.masks, cls.root / "mask-960.png", 960, 180)
        cls.times = [0.0, 1.5, 3.25, 6.0, 9.0]

    @classmethod
    def tearDownClass(cls) -> None:
        for name in [name for name in sys.modules if name == PACKAGE or name.startswith(PACKAGE + ".")]:
            del sys.modules[name]
        if cls.base in sys.path:
            sys.path.remove(cls.base)
        cls.temp.cleanup()

    def folder(self, name: str) -> Path:
        path = self.root / self.id().rsplit(".", 1)[-1] / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    # The stills ------------------------------------------------------------------------------

    def test_the_analysis_stills_are_the_same_masked_and_not(self) -> None:
        for mask in (self.still_mask, None):
            with self.subTest(masked=bool(mask)):
                label = "masked" if mask else "plain"
                old = self.old_analysis.grab_stills(FFMPEG, self.source, self.times, 360, self.folder(f"old-{label}"), mask)
                new = frame_render.render_stills(FFMPEG, self.source, self.times, self.folder(f"new-{label}"),
                                                 scale=(1920, 360), mask=mask)
                self.assertEqual([path.name for path in new], [path.name for path in old])
                self.assertEqual(_digests(new), _digests(old))

    def test_the_close_look_stills_are_the_same_whole_panel_and_zoomed(self) -> None:
        # A zoomed look: a region reaching into the masked right camera, cut at full resolution and stamped.
        box = (600, 20, 200, 120)
        for mask in (self.full_mask, None):
            with self.subTest(masked=bool(mask)):
                label = "masked" if mask else "plain"
                old_dir, new_dir = self.folder(f"old-{label}"), self.folder(f"new-{label}")
                self.old_review._grab_region(FFMPEG, self.source, self.times, box, old_dir, mask)
                new = frame_render.render_stills(FFMPEG, self.source, self.times, new_dir, crop=box, mask=mask,
                                                 stamp=True, quality=3, workers=1, reuse=False)
                old = [old_dir / f"s{index:05d}.jpg" for index in range(len(self.times))]
                self.assertEqual(_digests(new), _digests(old))
                # The look's sheet: 3x4 tiles of 640 wide, no labels.
                tile = (640, max(2, int(round(640 * box[3] / box[2] / 2)) * 2))
                old_sheets = self.old_analysis.contact_sheets(FFMPEG, old_dir, len(self.times), 2.0, 1.5,
                                                              (0, 0, box[2], box[3]), old_dir, tile=tile, columns=3,
                                                              rows=4, label=False)
                new_sheets = frame_render.contact_sheets(FFMPEG, new_dir, len(self.times), 2.0, 1.5,
                                                         (0, 0, box[2], box[3]), new_dir, tile=tile, columns=3,
                                                         rows=4, label=False)
                self.assertEqual(new_sheets, old_sheets)
                self.assertEqual(_digests(new_dir / s["file"] for s in new_sheets),
                                 _digests(old_dir / s["file"] for s in old_sheets))

    def test_the_contact_sheets_are_the_same(self) -> None:
        stills = self.folder("stills")
        self.old_analysis.grab_stills(FFMPEG, self.source, self.times, 360, stills, self.still_mask)
        crop = (640, 0, 640, 360)   # the center panel of a 1920-wide still
        for shape in ({}, {"columns": 2, "rows": 2}):
            with self.subTest(**shape):
                label = "x".join(str(value) for value in shape.values()) or "default"
                old_heard: list[tuple[int, int]] = []
                new_heard: list[tuple[int, int]] = []
                old = self.old_analysis.contact_sheets(FFMPEG, stills, len(self.times), 0.0, 10.0, crop,
                                                       self.folder(f"old-{label}"), **shape,
                                                       on_progress=lambda done, total: old_heard.append((done, total)))
                new = frame_render.contact_sheets(FFMPEG, stills, len(self.times), 0.0, 10.0, crop,
                                                  self.folder(f"new-{label}"), **shape,
                                                  on_progress=lambda done, total: new_heard.append((done, total)))
                self.assertEqual(new, old)
                self.assertEqual(new_heard, old_heard)
                self.assertEqual(_digests(self.folder(f"new-{label}") / s["file"] for s in new),
                                 _digests(self.folder(f"old-{label}") / s["file"] for s in old))

    def test_the_review_kit_stills_and_sheets_are_the_same(self) -> None:
        project = self.folder("project")
        (project / "analysis").mkdir()
        (project / "analysis" / "analysis.json").write_text(json.dumps({"settings": {"budget": "thorough"}}), encoding="utf-8")
        (project / "project.json").write_text(json.dumps({"versions": [{"version": 1}], "current_version": 1}),
                                              encoding="utf-8")
        version = project / "versions" / "v001"
        (version / "renders").mkdir(parents=True)
        (version / "timeline.json").write_text(json.dumps({"scenes": [{"id": "s01", "in": 0.0, "out": 30.0}]}),
                                               encoding="utf-8")
        preview = _clip(version / "renders" / "preview.mp4", "640x360", 30)
        kit = self.old_review.review_kit(project, 1, ffmpeg=FFMPEG, transcribe=False)
        step = self.old_review.REVIEW_STILL_INTERVAL["thorough"]
        times = [float(t) for t in range(0, 30, step)]
        old_stills = sorted((version / "review" / "stills").glob("s*.jpg"))
        self.assertEqual(len(old_stills), len(times))
        new_dir = self.folder("new")
        new = frame_render.render_stills(FFMPEG, preview, times, new_dir / "stills", scale=(1280, 720), quality=4,
                                         workers=1, reuse=False)
        self.assertEqual(_digests(new), _digests(old_stills))
        sheets = frame_render.contact_sheets(FFMPEG, new_dir / "stills", len(times), 0.0, float(step), (0, 0, 1280, 720), new_dir)
        self.assertEqual(_digests(new_dir / s["file"] for s in sheets), _digests(kit["sheets"]))

    def test_the_mask_editors_camera_still_is_the_same(self) -> None:
        for panel in ("left", "right"):
            with self.subTest(panel=panel):
                old = self.old_library.panel_still(FFMPEG, self.source, LAYOUT, panel, 2.5, self.folder("old") / f"{panel}.png")
                new = frame_render.render_stills(FFMPEG, self.source, [2.5], self.folder("new"),
                                                 crop=LAYOUT["panels"][panel], name=f"{panel}.png", workers=1, reuse=False)
                self.assertEqual(_digests(new), [_digest(old)])

    # The editor's own tools, old and new, on the frame renderer (226, W4b) ----------------------

    def _look_project(self, name: str) -> Path:
        project = self.folder(name)
        (project / "analysis").mkdir(exist_ok=True)
        (project / "analysis" / "analysis.json").write_text(json.dumps({
            "settings": {"budget": "thorough"}, "layout": LAYOUT, "source": str(self.source)}), encoding="utf-8")
        (project / "project.json").write_text(json.dumps({"versions": [], "current_version": None}), encoding="utf-8")
        return project

    def test_the_close_looks_themselves_are_the_same_as_before(self) -> None:
        from media_manglers.core.race_video import review

        looks = {"panel": {}, "region": {"region": [0, 0, 320, 180]},
                 "moments": {"region": [40, 20, 200, 120], "times": [1.0, 4.5, 8.0]}}
        for label, extra in looks.items():
            with self.subTest(look=label):
                old = self.old_review.close_look(self._look_project(f"old-{label}"), 1.0, 9.0, 1.5, "right",
                                                 masks=self.masks, ffmpeg=FFMPEG, **extra)
                new = review.close_look(self._look_project(f"new-{label}"), 1.0, 9.0, 1.5, "right",
                                        masks=self.masks, ffmpeg=FFMPEG, **extra)
                self.assertEqual(new["times"], old["times"])
                old_stills = sorted((Path(old["sheet"]).parent / "stills").glob("s*.jpg"))
                new_stills = sorted((Path(new["sheet"]).parent / "stills").glob("s*.jpg"))
                self.assertEqual([path.name for path in new_stills], [path.name for path in old_stills])
                self.assertEqual(_digests(new_stills), _digests(old_stills))
                self.assertEqual(_digest(new["sheet"]), _digest(old["sheet"]))

    def test_the_review_kit_itself_makes_the_same_stills_and_sheets_as_before(self) -> None:
        from media_manglers.core.race_video import review

        preview = _clip(self.folder("clip") / "preview.mp4", "640x360", 30)
        kits = {}
        for label, module in (("old", self.old_review), ("new", review)):
            project = self.folder(label)
            (project / "analysis").mkdir(exist_ok=True)
            (project / "analysis" / "analysis.json").write_text(json.dumps({"settings": {"budget": "thorough"}}),
                                                                encoding="utf-8")
            (project / "project.json").write_text(json.dumps({"versions": [{"version": 1}], "current_version": 1}),
                                                  encoding="utf-8")
            version = project / "versions" / "v001"
            (version / "renders").mkdir(parents=True, exist_ok=True)
            (version / "timeline.json").write_text(json.dumps({"scenes": [{"id": "s01", "in": 0.0, "out": 30.0}]}),
                                                   encoding="utf-8")
            shutil.copyfile(preview, version / "renders" / "preview.mp4")
            kits[label] = (module.review_kit(project, 1, ffmpeg=FFMPEG, transcribe=False),
                           sorted((version / "review" / "stills").glob("s*.jpg")))
        (old, old_stills), (new, new_stills) = kits["old"], kits["new"]
        self.assertEqual(len(new_stills), 5)
        self.assertEqual(_digests(new_stills), _digests(old_stills))
        self.assertEqual(_digests(new["sheets"]), _digests(old["sheets"]))

    def test_the_mask_editors_still_itself_is_the_same_as_before(self) -> None:
        from media_manglers.core.race_video import library

        for panel in ("left", "right"):
            with self.subTest(panel=panel):
                old = self.old_library.panel_still(FFMPEG, self.source, LAYOUT, panel, 2.5, self.folder("old") / f"{panel}.png")
                new = library.panel_still(FFMPEG, self.source, LAYOUT, panel, 2.5, self.folder("new") / f"{panel}.png")
                self.assertEqual(_digest(new), _digest(old))
        self.assertEqual(sorted(path.name for path in self.folder("new").iterdir()), ["left.png", "right.png"],
                         "nothing else is left beside the still")

    # The commands and filter text ---------------------------------------------------------------

    def test_the_analysis_still_commands_are_exactly_the_ones_the_editor_ran(self) -> None:
        for mask in (self.still_mask, None):
            with self.subTest(masked=bool(mask)):
                folder = self.folder("masked" if mask else "plain")
                old, new = _Recorder(), _Recorder()
                with mock.patch.object(self.old_analysis, "_run", old):
                    self.old_analysis.grab_stills(FFMPEG, self.source, self.times, 360, folder, mask)
                with mock.patch.object(frame_render, "_run", new):
                    frame_render.render_stills(FFMPEG, self.source, self.times, folder, scale=(1920, 360), mask=mask,
                                               reuse=False)

                def seek(command: list[str]) -> float:
                    return float(command[command.index("-ss") + 1])

                self.assertEqual(sorted(new.commands, key=seek), sorted(old.commands, key=seek))

    def test_the_close_look_filter_is_the_one_the_editor_built(self) -> None:
        box = (600, 20, 200, 120)
        for mask in (self.full_mask, None):
            with self.subTest(masked=bool(mask)):
                old = _Recorder()
                with mock.patch.object(self.old_review.subprocess, "run", old):
                    self.old_review._grab_region(FFMPEG, self.source, self.times, box, self.folder("old"), mask)
                for seconds, command in zip(self.times, old.commands):
                    made = frame_render.still_command(FFMPEG, self.source, seconds, Path("still.jpg"), crop=box, mask=mask,
                                                      stamp=True, quality=3)
                    option = "-filter_complex" if mask else "-vf"
                    self.assertEqual(made[made.index(option) + 1], command[command.index(option) + 1])
                    self.assertEqual(made[:made.index("-frames:v")], command[:command.index("-frames:v")])
                    self.assertEqual(made[made.index("-q:v") + 1], command[command.index("-q:v") + 1])

    def test_the_render_blur_is_the_one_the_editor_built(self) -> None:
        timeline = {"source": str(self.source), "source_layout": LAYOUT, "tracks": {"voice": 0, "game": 1}}
        frame_mask = self.folder("render") / "frame-privacy.png"
        frame_mask.write_bytes(b"built already")
        graph = self.old_render._SceneGraph(timeline, self.old_render.RenderOptions(masks=self.masks), 30, frame_mask)
        graph.view("full", 1280, 720, "vmain", "vbase")             # a whole-frame view reaches both cameras
        graph.view({"crop": [560, 0, 200, 180]}, 1280, 720, "vmain2", "vcrop")
        graph.view("right", 440, 246, "vinset", "vin")             # a camera panel through its own mask
        self.assertEqual(graph.parts[0], frame_render.privacy_blur_filter(
            crop=(0, 0, 960, 180), mask_fit="crop", sigma=30, setsar=True, shortest=True, source="vmain", mask="1:v",
            prefix="vbaser", out="vbaser"))
        self.assertEqual(graph.parts[2], frame_render.privacy_blur_filter(
            crop=(560, 0, 200, 180), mask_fit="crop", sigma=30, setsar=True, shortest=True, source="vmain2", mask="2:v",
            prefix="vcropr", out="vcropr"))
        self.assertEqual(graph.parts[4], frame_render.privacy_blur_filter(
            crop=(640, 0, 320, 180), sigma=30, setsar=True, shortest=True, source="vinset", mask="3:v", prefix="vin",
            out="vin", after="scale=440:246:flags=lanczos,setsar=1"))

    # The frame renderer's own functions ---------------------------------------------------------

    def test_the_frame_renderers_existing_functions_are_unchanged(self) -> None:
        # Internal issue references in docstrings lost their leading hash later ("#115" became "115");
        # that wording change is not a change to the function, so it is evened out before comparing.
        def source(function) -> str:
            return re.sub(r"#(\d{2,4})\b", r"\1", inspect.getsource(function))

        for name in UNCHANGED:
            with self.subTest(function=name):
                self.assertEqual(source(getattr(frame_render, name)), source(getattr(self.old_frames, name)))
        for name in ("MAX_FRAMES_PER_BATCH", "MAX_GAP_SECONDS", "MAX_BATCH_SPAN_SECONDS", "PANEL_DETECTION"):
            self.assertEqual(getattr(frame_render, name), getattr(self.old_frames, name))
        self.assertEqual(frame_render.SHOWINFO_TIMESTAMP.pattern, self.old_frames.SHOWINFO_TIMESTAMP.pattern)
        old_probe = self.old_frames.probe_video(FFPROBE, self.source)
        new_probe = frame_render.probe_video(FFPROBE, self.source)
        self.assertEqual({key: new_probe[key] for key in old_probe}, old_probe)

    def test_the_frame_renderers_screenshots_are_the_same(self) -> None:
        recording = _clip(self.root / "surround.mkv", "5760x1080", 3)
        panels = [{"role": role, "crop_x": 1920 * index, "crop_y": 0, "crop_width": 1920, "crop_height": 1080}
                  for index, role in enumerate(("overview_cam", "driver_view", "face_cam"))]
        made: dict[str, list[str]] = {}
        for label, module in (("old", self.old_frames), ("new", frame_render)):
            folder = self.folder(label)
            moments = [{"timestamp_seconds": at, "path": str(folder / f"f{i}.jpg"),
                        "panels": [{**panel, "path": str(folder / panel["role"] / f"f{i}.jpg")} for panel in panels]}
                       for i, at in enumerate((0.5, 1.25, 2.5))]
            module.render_moments(FFMPEG, recording, moments, ffprobe_exe=FFPROBE)
            exact = module.render_exact(FFMPEG, recording, [0.4, 1.9], folder / "exact")
            cadence = module.render_cadence(FFMPEG, recording, folder / "cadence", 1.0)
            self.assertTrue(cadence["ok"])
            made[label] = (_digests(Path(m["path"]) for m in moments)
                           + _digests(Path(p["path"]) for m in moments for p in m["panels"])
                           + _digests(Path(item["path"]) for item in exact)
                           + _digests(sorted((folder / "cadence").glob("*.jpg"))))
        self.assertEqual(made["new"], made["old"])

    # The analysis on the shared engine (stage W4a) -------------------------------------------------

    def test_the_analysis_makes_the_same_stills_and_sheets_as_before(self) -> None:
        # analyze() itself, old and new, on the same recording: the stills and contact sheets the AI
        # editor is handed are byte for byte what they were, masked and not.
        from media_manglers.core.race_video import analysis, project

        source = _three_panels_with_sound(self.folder("clip") / "race.mkv")
        for masks in (self.masks, {}):
            with self.subTest(masked=bool(masks)):
                label = "masked" if masks else "plain"
                old_project = self.old_project.create_project(self.folder(f"old-{label}"), source, "race")
                old = self.old_analysis.analyze(old_project, source, budget="thorough", tracks={"voice": 0, "game": 1},
                                                layout=LAYOUT, masks=masks, ffmpeg=FFMPEG, ffprobe=FFPROBE)
                new_project = project.create_project(self.folder(f"new-{label}"), source, "race")
                new = analysis.analyze(new_project, source, budget="thorough", tracks={"voice": 0, "game": 1},
                                       layout=LAYOUT, masks=masks, ffmpeg=FFMPEG, ffprobe=FFPROBE)
                old_stills = sorted((old_project / "analysis" / "stills").glob("s*.jpg"))
                new_stills = sorted((new_project / "analysis" / "stills").glob("s*.jpg"))
                self.assertEqual(len(new_stills), 6)
                self.assertEqual([path.name for path in new_stills], [path.name for path in old_stills])
                self.assertEqual(_digests(new_stills), _digests(old_stills))
                self.assertEqual(new["sheets"], old["sheets"])
                self.assertEqual(_digests(new_project / "analysis" / "sheets" / s["file"] for s in new["sheets"]),
                                 _digests(old_project / "analysis" / "sheets" / s["file"] for s in old["sheets"]))
                self.assertEqual((new["stills"], new["still_interval"], new["privacy_masked"], new["picture_changes"]),
                                 (old["stills"], old["still_interval"], old["privacy_masked"], old["picture_changes"]))

    def test_the_cross_track_check_without_its_new_options_is_what_it_was(self) -> None:
        # Features 1-3 call check_from_request with only a payload: the same lines are dropped, for the
        # same reasons, and every file it rewrites is byte for byte what 9e065e4 wrote.
        from media_manglers.core import cross_track_check
        from media_manglers.core.transcripts import write_transcript_files

        def bursty(freq: int, length: float) -> str:
            return (f"sine=frequency={freq}:sample_rate=48000:duration=20,"
                    f"volume='if(between(mod(t,4),0,{length}),1,0)':eval=frame")

        narration = ("sine=frequency=300:sample_rate=48000:duration=20,"
                     "volume='if(between(t,1,3),1,if(between(t,5,7),0.001,0))':eval=frame")
        names = ("T1 - Full Mix", "T2 - Narration", "T3 - Game / Simulator", "T6 - Music")
        recording = _titled_tracks(self.folder("clip") / "session.mkv", [
            (bursty(200, 3.5), names[0]), (narration, names[1]), (bursty(500, 0.5), names[2]), (bursty(700, 3.5), names[3])])
        detection = {"status": "selected", "selected_ordinal": 1,
                     "track_roles": {"1": "full_mix", "2": "narration", "3": "never", "4": "never"},
                     "tracks": [{"ordinal": o, "track_number": o + 1, "title": names[o], "silent": False} for o in range(4)]}
        segments = [
            {"id": 0, "start": 1.0, "end": 3.0, "text": "the limiter light should stay on when I press the pit button"},
            {"id": 1, "start": 5.0, "end": 7.0, "text": "la la la, an invented chorus line, sung loudly over the music track"},
            {"id": 2, "start": 5.5, "end": 6.5, "text": "la la la"},
            {"id": 3, "start": 2.4, "end": 2.8, "text": "okay"},
            # Every track is quiet here: not said into the microphone.
            {"id": 4, "start": 3.6, "end": 3.95, "text": "I hope you enjoyed it."},
            {"id": 5, "start": 1.2, "end": 2.9, "text": "box box this lap for the soft tyres please"},
        ]

        def hearing(path):
            ordinal = int(Path(path).stem.split("-")[-1])
            words = {2: "box box this lap for the soft tyres please", 3: "drums and guitar only"}.get(ordinal, "")
            return [{"text": words}] if words else []

        results, files = {}, {}
        for label, module in (("old", self.old_cross), ("new", cross_track_check)):
            folder = self.folder(label) / "transcript"
            write_transcript_files(folder, "s.transcript.json", "s.transcript.srt", "s.transcript.txt",
                                   {"language": "en", "segments": [dict(item) for item in segments]})
            (folder / "s.transcript.raw.json").write_text(json.dumps({"filtered_segments": []}), encoding="utf-8")
            (folder / "s.transcript.quality.json").write_text(json.dumps({"filtered_segment_count": 0}), encoding="utf-8")
            with mock.patch.object(module.voice_track, "whisper_transcriber", return_value=hearing):
                results[label] = module.check_from_request({
                    "source_path": str(recording), "ffmpeg_exe": FFMPEG,
                    "transcript_json_path": str(folder / "s.transcript.json"), "detection": detection})
            files[label] = {path.name: path.read_bytes() for path in sorted(folder.iterdir())}
        self.assertEqual(results["new"], results["old"])
        self.assertEqual(files["new"], files["old"])
        self.assertEqual(sorted(item["reason"] for item in results["new"]["dropped"]),
                         ["heard_on_another_track", "heard_on_another_track", "heard_on_another_track",
                          "narration_track_near_silent"], "the check did drop lines, by level, words and its own level")


if __name__ == "__main__":
    unittest.main()
