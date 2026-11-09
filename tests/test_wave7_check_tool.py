"""Wave 7 (226): the Part 1 validation tool, ``tools/validation/run_wave7_check.py``.

The tool is run through its own command line, with real FFmpeg on a small synthetic recording made with
lavfi: 5760x1080, three panels, six audio tracks titled like an OBS recording, and a game panel that
stands still for over a minute (dead time found by the game picture alone). Whisper is not in the test
runtime, so the tool's own check sees that and Prepare skips the transcript. Every folder is the test's
own; the operator's settings, masks and library are never read.

A second synthetic recording has an older track layout (the Track roles' game track is silent; the game
is on Track 6): the tracks picked on the command line, the stop on a silent game track and the
comparison of the analysis with 9e065e4's (``git archive`` of that commit) run on it.
"""

from __future__ import annotations

import csv
import ctypes
from fractions import Fraction
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers.core import frame_render  # noqa: E402

TOOL = REPO_ROOT / "tools" / "validation" / "run_wave7_check.py"
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
RATE, SECONDS, FROZEN = 5, 84, (12, 78)
TITLES = [f"Track{number}" for number in range(1, 7)]
ROLES = "1=full_mix,2=narration,3=game"
# A path Windows does not shorten, so a file can be given a name ending in a dot that an ordinary path
# cannot reach (the listing then cannot read it).
LONG_PATH = "\\\\?\\"
# The tool with its review kit asked about a version that does not exist, so the real kit refuses: how a
# review kit that does not run is made to happen on a fresh project (its budget is not used up yet).
REFUSED_REVIEW_KIT = (
    "import importlib.util, sys\n"
    "spec = importlib.util.spec_from_file_location('run_wave7_check', sys.argv[1])\n"
    "tool = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(tool)\n"
    "real = tool._Editor.call\n"
    "def call(self, kind, command, payload, watch=None):\n"
    "    return real(self, kind, command, {**payload, 'version': 99} if kind == 'review-kit' else payload, watch)\n"
    "tool._Editor.call = call\n"
    "raise SystemExit(tool.main(sys.argv[2:]))\n")
# A stand-in backend (226): a progress bar on the error output as Whisper draws it (a carriage return, no
# line end), and a status line on the normal output after each one, 0.4 s apart.
GLUING_BACKEND = (
    "import json, sys, time\n"
    "def status(number):\n"
    "    record = {'schema': 'MM_PROGRESS_V1', 'phase': 'Writing down the narration', 'activity': f'line {number}',\n"
    "              'completed': number, 'total': 8}\n"
    "    print('MM_PROGRESS_V1 ' + json.dumps(record), flush=True)\n"
    "def main(argv):\n"
    "    status(0)\n"
    "    for number in range(1, 8):\n"
    "        time.sleep(0.4)\n"
    "        sys.stderr.write(f'\\r {number * 12}%|###       | {number * 100}/800 [00:0{number}<00:05, 123.45frames/s]')\n"
    "        sys.stderr.flush()\n"
    "        status(number)\n"
    "    sys.stderr.write('\\n')\n"
    "    sys.stderr.flush()\n"
    "    status(8)\n"
    "    with open(argv[argv.index('--result-file') + 1], 'w', encoding='utf-8') as handle:\n"
    "        json.dump({'ok': True, 'data': {}}, handle)\n"
    "    return 0\n")


def load_tool():
    """The tool as a module, so a test can run one backend command the way the tool runs it."""

    spec = importlib.util.spec_from_file_location("run_wave7_check_under_test", TOOL)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool


def run_tool(*args: str, env: dict[str, str] | None = None, timeout: float = 1200) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, timeout=timeout, cwd=str(REPO_ROOT))


def sha256(path: Path) -> str:
    import hashlib  # noqa: PLC0415

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def six_track_race(path: Path) -> Path:
    """84 s of a 5760x1080 recording at 5 pictures a second with a keyframe every 2 s. The game (centre
    panel) moves, stands still 12-78 s while a clock in its corner ticks, then moves again; the camera
    panels either side show moving noise. Six tracks, Track1-Track6: a full mix, a voice that speaks
    1.2 s of every 4 s, the game's engine (never quiet), music that comes and goes, and two silent ones, in
    AAC as OBS records them."""

    path.parent.mkdir(parents=True, exist_ok=True)
    noise = ("color=gray:size=32x18:rate={rate}:duration={seconds},noise=alls=100:allf=t+u:all_seed={seed},"
             "scale=1920:1080:flags=neighbor")
    first, last = FROZEN[0] * RATE, FROZEN[1] * RATE - 1
    graph = (f"[0:v]split[a][b];[a][b]freezeframes=first={first}:last={last}:replace={first},"
             f"drawtext={frame_render.font_option(True)}text='%{{eif\\:t\\:d}}':fontsize=28:fontcolor=white:x=24:y=24[game];"
             f"{noise.format(rate=RATE, seconds=SECONDS, seed=1)}[left];"
             f"{noise.format(rate=RATE, seconds=SECONDS, seed=2)}[right];"
             "[left][game][right]hstack=inputs=3,format=yuv420p[v]")
    sounds = [f"anoisesrc=color=brown:amplitude=0.2:sample_rate=48000:duration={SECONDS}",
              f"sine=frequency=300:sample_rate=48000:duration={SECONDS},volume='if(lt(mod(t,4),1.2),1,0)':eval=frame",
              f"anoisesrc=color=pink:amplitude=0.3:sample_rate=48000:duration={SECONDS}",
              f"sine=frequency=700:sample_rate=48000:duration={SECONDS},volume='if(lt(mod(t,3),2),1,0.02)':eval=frame",
              f"anullsrc=r=48000:cl=mono:d={SECONDS}", f"anullsrc=r=48000:cl=mono:d={SECONDS}"]
    command = [FFMPEG, "-hide_banner", "-v", "error", "-y",
               "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate={RATE}:duration={SECONDS}"]
    for sound in sounds:
        command += ["-f", "lavfi", "-i", sound]
    command += ["-filter_complex", graph, "-map", "[v]", *[part for index in range(6) for part in ("-map", f"{index + 1}:a")],
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-g", str(2 * RATE), "-keyint_min", str(2 * RATE),
                "-sc_threshold", "0", "-c:a", "aac", "-b:a", "160k"]
    for index, title in enumerate(TITLES):
        command += [f"-metadata:s:a:{index}", f"title={title}"]
    subprocess.run([*command, "-t", str(SECONDS), str(path)], check=True)
    return path


def older_layout_race(path: Path, seconds: int = 30) -> Path:
    """A recording made with an older track layout (226): Track roles call Track 3 the game sound, but it
    is silent the whole recording; the game is on Track 6, an engine that rises and falls. 5760x1080 at 5
    pictures a second, Track1-Track6: a full mix, a voice that speaks 1.2 s of every 4 s, the silent
    Track 3, music, another silent track and the game."""

    path.parent.mkdir(parents=True, exist_ok=True)
    noise = ("color=gray:size=32x18:rate={rate}:duration={seconds},noise=alls=100:allf=t+u:all_seed={seed},"
             "scale=1920:1080:flags=neighbor")
    graph = (f"{noise.format(rate=RATE, seconds=seconds, seed=1)}[left];{noise.format(rate=RATE, seconds=seconds, seed=2)}"
             "[right];[left][0:v][right]hstack=inputs=3,format=yuv420p[v]")
    sounds = [f"anoisesrc=color=brown:amplitude=0.2:sample_rate=48000:duration={seconds}:seed=3",
              f"sine=frequency=300:sample_rate=48000:duration={seconds},volume='if(lt(mod(t,4),1.2),1,0)':eval=frame",
              f"anullsrc=r=48000:cl=mono:d={seconds}",
              f"sine=frequency=700:sample_rate=48000:duration={seconds},volume='if(lt(mod(t,3),2),1,0.02)':eval=frame",
              f"anullsrc=r=48000:cl=mono:d={seconds}",
              f"anoisesrc=color=pink:amplitude=0.3:sample_rate=48000:duration={seconds}:seed=4,"
              "volume='if(lt(mod(t,6),3),1,0.15)':eval=frame"]
    command = [FFMPEG, "-hide_banner", "-v", "error", "-y",
               "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate={RATE}:duration={seconds}"]
    for sound in sounds:
        command += ["-f", "lavfi", "-i", sound]
    command += ["-filter_complex", graph, "-map", "[v]", *[part for index in range(6) for part in ("-map", f"{index + 1}:a")],
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-g", str(2 * RATE), "-c:a", "aac", "-b:a", "160k"]
    for index, title in enumerate(TITLES):
        command += [f"-metadata:s:a:{index}", f"title={title}"]
    subprocess.run([*command, "-t", str(seconds), str(path)], check=True)
    return path


def environment_for(root: Path, recordings: Path, name: str = "work", **settings) -> Path:
    """A work folder with its test environment, from a settings file of the test's own."""

    work = root / name
    source = write_settings(root / f"real-{name}" / "settings.json", **settings)
    done = run_tool("environment", "--work", str(work), "--settings", str(source), "--recordings-folder", str(recordings))
    assert done.returncode == 0, done.stdout + done.stderr
    return work


def prepare_requests(root: Path) -> list[dict]:
    """The payload of every Prepare the editor step ran with the editor folder ``root``, in order."""

    runs = sorted((root / "race-videos" / ".runs").glob("*-prepare"))
    return [json.loads((run / "request.json").read_text(encoding="utf-8"))["payload"] for run in runs]


def write_settings(path: Path, **extra) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    settings = {"dependency_python_path": sys.executable, "dependency_ffmpeg_path": FFMPEG,
                "dependency_ffprobe_path": FFPROBE, "evidence_track_roles": ROLES, "race_video_budget": "light",
                "whisper_model": "medium", "output_folder": str(path.parent / "not-the-work-folder"), **extra}
    path.write_text(json.dumps({"schemaVersion": 8, "settings": settings}, indent=2), encoding="utf-8")
    return path


def files_under(folder: Path) -> dict[str, tuple[int, int]]:
    return {str(path): (path.stat().st_size, path.stat().st_mtime_ns) for path in folder.rglob("*") if path.is_file()}


def mask_store(appdata: Path) -> None:
    """A mask store in the per-user folder the masks are read from (APPDATA is the test's own)."""

    store = appdata / "MediaManglers" / "race-video" / "privacy"
    store.mkdir(parents=True, exist_ok=True)
    for panel in ("left", "right"):
        subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", "color=white:size=1920x1080",
                        "-frames:v", "1", "-pix_fmt", "gray", str(store / f"{panel}.png")], check=True)
    (store / "masks.json").write_text(json.dumps({"masks": {"left": "left.png", "right": "right.png"}}), encoding="utf-8")


class EnvironmentTests(unittest.TestCase):
    """The environment step makes a copy of the settings pointed into the work folder and never writes
    the settings file it reads."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        for path in self.root.rglob("*"):
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        self.temp.cleanup()

    def test_the_copy_points_into_the_work_folder_and_the_source_is_never_written(self) -> None:
        source = write_settings(self.root / "real" / "settings.json", evidence_resume_root=str(self.root / "real-resume"))
        os.chmod(source, stat.S_IREAD)   # a write would fail
        before = (source.read_bytes(), source.stat().st_mtime_ns)
        work, report = self.root / "work", self.root / "report.md"
        done = run_tool("environment", "--work", str(work), "--settings", str(source),
                        "--recordings-folder", str(self.root / "recordings"), "--report", str(report))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), before)
        result = json.loads((work / "environment.json").read_text(encoding="utf-8"))
        self.assertTrue(result["source_unchanged"])
        self.assertEqual(result["source_sha256_before"], result["source_sha256_after"])
        env = result["environment"]
        self.assertEqual(env["MEDIA_MANGLERS_ALLOW_TEMP_OUTPUT"], "1")
        self.assertEqual(env["MEDIA_MANGLERS_RECORDINGS_FOLDERS"], str(self.root / "recordings"))
        for key in ("TEMP", "TMP", "MEDIA_MANGLERS_SCRATCH_ROOT"):
            self.assertEqual(env[key], str(work / "scratch"))
        self.assertEqual(env["MEDIA_MANGLERS_WORKBENCH_APPDATA"], str(work / "gui-appdata"))
        self.assertIn('"MEDIA_MANGLERS_LIBRARY_ROOT"', done.stdout, "the environment is printed")
        copy = Path(result["settings_copy"])
        self.assertEqual(copy, work / "gui-appdata" / "MediaManglers" / "workbench" / "settings.json")
        settings = json.loads(copy.read_text(encoding="utf-8"))["settings"]
        for key in ("output_folder", "race_video_output_folder", "review_evidence_root", "review_ledger_path",
                    "review_inbox_folder", "review_local_work_root", "review_source_folders", "cache_folder", "temp_folder", "log_folder"):
            self.assertTrue(Path(settings[key]).is_relative_to(work), key)
        self.assertEqual(settings["evidence_track_roles"], ROLES, "every other setting is kept")
        self.assertEqual(settings["evidence_resume_root"], "", "features 1-3 never resume from a real folder")
        for name in ("scratch", "test-library", "test-cache", "test-output", "gui-appdata"):
            self.assertTrue((work / name).is_dir(), name)
        self.assertIn("The source settings file was not changed", report.read_text(encoding="utf-8"))

    def test_a_work_folder_in_the_recordings_folder_is_refused(self) -> None:
        recordings = self.root / "recordings"
        recordings.mkdir()
        work = recordings / "work"
        source = write_settings(self.root / "real" / "settings.json")
        done = run_tool("environment", "--work", str(work), "--settings", str(source),
                        "--recordings-folder", str(recordings))
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn("on the drive that holds your recordings", done.stdout)
        self.assertFalse(work.exists(), "nothing is made there")

    def test_a_copy_that_would_replace_its_source_is_refused(self) -> None:
        work = self.root / "work"
        source = write_settings(work / "gui-appdata" / "MediaManglers" / "workbench" / "settings.json")
        before = source.read_bytes()
        done = run_tool("environment", "--work", str(work), "--settings", str(source),
                        "--recordings-folder", str(self.root / "recordings"))
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn("would replace the settings file", done.stdout)
        self.assertEqual(source.read_bytes(), before)


class ListingTests(unittest.TestCase):
    """listing and compare: a file that existed before and changed or went is a difference; a new one
    is only reported."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder = self.root / "recordings"
        (self.folder / "sub").mkdir(parents=True)
        (self.folder / "one.mkv").write_bytes(b"a" * 10)
        (self.folder / "sub" / "two.mkv").write_bytes(b"b" * 20)
        hidden = self.folder / "sub" / "hidden.txt"
        hidden.write_text("x", encoding="utf-8")
        ctypes.windll.kernel32.SetFileAttributesW(str(hidden), 0x2)

    def tearDown(self) -> None:
        for path in self.folder.rglob("*."):
            os.remove(LONG_PATH + str(path))
        self.temp.cleanup()

    def listing(self, name: str) -> Path:
        out = self.root / name
        done = run_tool("listing", "--folder", str(self.folder), "--out", str(out))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return out

    def compare(self, before: Path, after: Path) -> tuple[int, dict]:
        result = self.root / "compare.json"
        done = run_tool("compare", "--before", str(before), "--after", str(after), "--json", str(result))
        return done.returncode, json.loads(result.read_text(encoding="utf-8"))

    def test_hidden_files_are_listed_with_size_and_time(self) -> None:
        with self.listing("before.csv").open(encoding="utf-8", newline="") as handle:
            rows = {Path(row["path"]).name: row for row in csv.DictReader(handle)}
        self.assertEqual(set(rows), {"one.mkv", "two.mkv", "hidden.txt"})
        self.assertEqual(rows["two.mkv"]["size"], "20")
        self.assertTrue(rows["one.mkv"]["modified_utc"].endswith("Z"))

    def test_new_files_are_reported_and_changes_are_differences(self) -> None:
        before = self.listing("before.csv")
        (self.folder / "new-recording.mkv").write_bytes(b"c")
        code, result = self.compare(before, self.listing("after-new.csv"))
        self.assertEqual(code, 0)
        self.assertEqual([Path(path).name for path in result["new_files"]], ["new-recording.mkv"])
        with (self.folder / "sub" / "two.mkv").open("ab") as handle:
            handle.write(b"more")
        (self.folder / "one.mkv").unlink()
        code, result = self.compare(before, self.listing("after-change.csv"))
        self.assertEqual(code, 1)
        self.assertEqual([Path(path).name for path in result["changed"]], ["two.mkv"])
        self.assertEqual([Path(path).name for path in result["removed"]], ["one.mkv"])

    def test_a_listing_inside_the_folder_it_lists_is_refused(self) -> None:
        done = run_tool("listing", "--folder", str(self.folder), "--out", str(self.folder / "list.csv"))
        self.assertEqual(done.returncode, 2)
        self.assertFalse((self.folder / "list.csv").exists())

    def test_a_missing_folder_is_refused(self) -> None:
        out = self.root / "offline.csv"
        done = run_tool("listing", "--folder", str(self.root / "offline"), "--out", str(out))
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn("is not a folder that can be read", done.stdout)
        self.assertFalse(out.exists())

    def test_a_file_that_cannot_be_read_fails_the_listing(self) -> None:
        with open(LONG_PATH + str(self.folder / "sub" / "unreachable."), "wb") as handle:
            handle.write(b"d")
        out, result = self.root / "partial.csv", self.root / "partial.json"
        done = run_tool("listing", "--folder", str(self.folder), "--out", str(out), "--json", str(result))
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertEqual(json.loads(result.read_text(encoding="utf-8"))["unreadable"], 1)
        self.assertIn("1 could not be read", done.stdout)

    def test_compare_refuses_an_empty_before_listing(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        before = self.root / "before-empty.csv"
        done = run_tool("listing", "--folder", str(empty), "--out", str(before))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        done = run_tool("compare", "--before", str(before), "--after", str(self.listing("after.csv")))
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn("has no files", done.stdout)

    def test_an_unexpected_error_stops_the_step_and_leaves_its_result(self) -> None:
        result = self.root / "compare.json"
        done = run_tool("compare", "--before", str(self.root / "missing.csv"), "--after", str(self.listing("after.csv")),
                        "--json", str(result))
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn("STOPPED (unexpected)", done.stdout)
        self.assertIn("missing.csv", json.loads(result.read_text(encoding="utf-8"))["failed"])


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class SmokeDryRunTests(unittest.TestCase):
    """smoke --dry-run builds each feature's command the way its page does, from the settings copy, and
    runs none of them."""

    def test_every_command_is_built_with_folders_in_the_work_folder(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            clip = root / "recordings" / "clip.mkv"
            clip.parent.mkdir(parents=True)
            subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y",
                            "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=5:d=2",
                            "-f", "lavfi", "-i", "sine=duration=2", "-f", "lavfi", "-i", "sine=duration=2:frequency=500",
                            "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264", "-preset", "ultrafast",
                            str(clip)], check=True)
            work = root / "work"
            settings = write_settings(root / "real" / "settings.json")
            done = run_tool("environment", "--work", str(work), "--settings", str(settings),
                            "--recordings-folder", str(clip.parent))
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            done = run_tool("smoke", "--dist", str(REPO_ROOT), "--backend-src", str(REPO_ROOT / "src"), "--clip", str(clip),
                            "--work", str(work), "--dry-run")
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            results = json.loads((work / "results" / "smoke.json").read_text(encoding="utf-8"))
            self.assertEqual(set(results), {"1 Full Review", "2 Find my bug reports", "3 Review Media Inbox",
                                            "3 Raw bin scan"})
            # One copy of the clip in the work folder, and every feature works on it, never on the clip.
            copy = work / "smoke" / "clip" / "clip.mkv"
            self.assertEqual(copy.read_bytes(), clip.read_bytes())
            for feature in ("full-review", "bug-reports", "inbox"):
                argv = json.loads((work / "smoke" / feature / "argv.json").read_text(encoding="utf-8"))
                self.assertTrue(argv, feature)
                self.assertNotIn(str(clip), " ".join(argv), feature)
            full = " ".join(json.loads((work / "smoke" / "full-review" / "argv.json").read_text(encoding="utf-8")))
            self.assertIn(str(copy), full)
            self.assertIn(str(work / "smoke" / "full-review" / "out"), full)
            listed = (work / "smoke" / "bug-reports" / "recordings.mmlist").read_text(encoding="utf-8-sig")
            self.assertIn(str(copy), listed)
            self.assertNotIn(str(clip), listed)
            inbox = " ".join(json.loads((work / "smoke" / "inbox" / "argv.json").read_text(encoding="utf-8")))
            self.assertIn(str(copy.parent), inbox)
            raw = json.loads(Path(results["3 Raw bin scan"]["argv"]).read_text(encoding="utf-8"))
            self.assertIn("raw-bin-scan", raw)
            request = Path(raw[raw.index("--request-file") + 1])
            self.assertTrue(request.is_relative_to(work / "test-library"), "the scan's run is in the test library")
            payload = json.loads(request.read_text(encoding="utf-8"))["payload"]
            self.assertEqual(payload["folders"], [str(copy.parent)])
            self.assertEqual(payload["track_roles"], ROLES)


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class EditorRunTests(unittest.TestCase):
    """The editor step on the synthetic race, once for the class: Prepare through the page's command, the
    scripted test edit, its renders and exports, a validation render and the frame-rate copies."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.source = six_track_race(cls.root / "recordings" / "race.mkv")
        cls.beside = files_under(cls.source.parent)
        cls.work, cls.report = cls.root / "work", cls.root / "report.md"
        # The main setting the export made as the page makes it (no quality in its request) follows.
        settings = write_settings(cls.root / "real" / "settings.json", race_video_export_quality="smaller")
        done = run_tool("environment", "--work", str(cls.work), "--settings", str(settings),
                        "--recordings-folder", str(cls.root / "recordings"))
        assert done.returncode == 0, done.stdout + done.stderr
        extra = ["--skip-transcript"] if importlib.util.find_spec("whisper") else []
        cls.done = run_tool("editor", "--backend-src", str(REPO_ROOT / "src"), "--recording", str(cls.source),
                            "--work", str(cls.work), "--copy-name", "race-clip.mkv", "--scripted-minutes", "0.3",
                            "--qualities", "youtube,smaller", "--validation-size", "640x360", "--fps-copies",
                            "--fps-copy-seconds", "6", "--report", str(cls.report), *extra)
        cls.result = json.loads((cls.work / "results" / "editor-race-clip.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def test_it_ran_to_the_end(self) -> None:
        self.assertNotIn("failed", self.result, self.done.stdout[-3000:] + self.done.stderr[-3000:])
        self.assertEqual(self.done.returncode, 0, self.done.stderr[-3000:])
        self.assertEqual(self.result["failed_checks"], [], "every render passed its technical check")
        lines = self.result["prepare"]["progress_lines"]
        self.assertTrue(lines and all({"t", "phase", "activity"} <= set(line) for line in lines))

    def test_prepare_follows_the_track_roles_and_reads_the_recording_once(self) -> None:
        prepared = self.result["prepare"]
        self.assertEqual(prepared["tracks"], {"voice": 1, "game": 2, "voice_decided_by": "setting",
                                              "game_decided_by": "setting"})
        reads = prepared["reads"]
        self.assertEqual(reads["full_reads"], 1, reads)
        self.assertEqual(reads["part_reads"], 0, reads)
        self.assertGreater(reads["still_seeks"], 0, "the analysis stills are seeks, counted on their own")
        self.assertGreaterEqual(reads["read_share"], 0.9)
        progress = prepared["progress"]
        self.assertGreater(progress["lines"], 3)
        # 242 (Wave C2): a recording the library has not read is first confirmed by its content, then read once.
        self.assertEqual([item["phase"] for item in progress["phases"]][:2],
                         ["Confirming which recording this is", "Reading the recording"])
        self.assertIn("Watching the race", [item["phase"] for item in progress["phases"]])
        if not importlib.util.find_spec("whisper"):
            self.assertIn("Whisper is not installed", self.result["transcript_skipped"])
        self.assertFalse(prepared["transcript"]["written"])

    def test_a_steady_engine_game_track_is_sound_and_the_step_goes_on(self) -> None:
        # 226: the game track (noise that never rises above its own floor) is not among the tracks with
        # speech-like rises ("sounding"), but it is sound, so the silent-game-track stop does not fire.
        prepared = self.result["prepare"]
        self.assertEqual(prepared["sent_tracks"], {}, "Auto sends no tracks")
        self.assertNotIn(2, prepared["sounding"])
        self.assertNotIn("failed", self.result)

    def test_the_still_game_panel_is_dead_time_found_by_the_picture(self) -> None:
        activity = self.result["prepare"]["activity"]
        self.assertEqual(len(activity["idle_stretches"]), 1, activity)
        start, end = activity["idle_stretches"][0]
        self.assertLessEqual(abs(start - FROZEN[0]), 3)
        self.assertLessEqual(abs(end - FROZEN[1]), 3)
        self.assertEqual(activity["idle_by"], [["game_picture"]])
        self.assertIn("(one signal only)", self.report.read_text(encoding="utf-8"))

    def test_the_scripted_edit_has_a_scene_in_dead_time_that_is_flagged(self) -> None:
        scenes = self.result["scenes"]
        self.assertEqual(sum(1 for scene in scenes if scene["dead_time"]), 1)
        self.assertTrue(all(scene["out"] > scene["in"] for scene in scenes))
        v001 = self.result["versions"]["v001"]
        self.assertTrue(v001["notes"], "adding the version points out the scene in dead time")
        self.assertEqual(len(v001["pacing_in_dead_time"]), 1)
        project = Path(self.result["prepare"]["project"])
        meta = json.loads((project / "project.json").read_text(encoding="utf-8"))
        self.assertEqual([entry.get("editor_label") for entry in meta["versions"]], ["wave7-check"] * 3)
        timeline = json.loads((project / "versions" / "v001" / "timeline.json").read_text(encoding="utf-8"))
        self.assertIn("scripted test edit, not an AI edit", timeline["scenes"][0]["reason"])
        self.assertIn("Scripted test edit (written by this tool, not an AI edit)", self.report.read_text(encoding="utf-8"))

    def test_a_sound_only_revision_reuses_every_picture(self) -> None:
        versions = self.result["versions"]
        first, second = versions["v001"]["preview"], versions["v002"]["preview"]
        self.assertEqual(first["picture_renders"], len(self.result["scenes"]))
        self.assertEqual(second["picture_renders"], 0)
        self.assertEqual(second["joined_picture"], "reused")
        for item in (first, second):
            self.assertTrue(item["check_passed"], item)
            self.assertTrue(item["readable_present"], item)
        renders = Path(self.result["prepare"]["project"]) / "versions" / "v003" / "renders"
        self.assertFalse(any(renders.glob("*.mp4")) if renders.is_dir() else False, "v003 is stored, not rendered")

    def test_each_export_quality_and_the_validation_render(self) -> None:
        v002 = self.result["versions"]["v002"]
        self.assertEqual(set(v002["exports"]), {"youtube", "smaller"})
        for quality, item in v002["exports"].items():
            self.assertTrue(item["check_passed"], item)
            self.assertEqual(item["export_quality"], quality)
            self.assertEqual(item["export_quality_source"], "request")
            self.assertEqual(Fraction(str(item["fps"])), RATE, "the recording's own frame rate")
            self.assertIn("wave7-check", Path(item["export"]).name)
            self.assertGreater(item["mb_per_minute"], 0)
        validation = v002["validation"]
        self.assertEqual(validation["size"], [640, 360])
        self.assertTrue(validation["check_passed"], validation)

    def test_every_export_is_kept_and_one_follows_the_main_setting(self) -> None:
        v002 = self.result["versions"]["v002"]
        as_set = v002["export_as_set"]
        self.assertEqual((as_set["export_quality"], as_set["export_quality_source"]), ("smaller", "main_setting"))
        self.assertTrue(as_set["check_passed"], as_set)
        kept = {"as-set": as_set, **v002["exports"]}
        for label, item in kept.items():
            copy = Path(item["kept"])
            self.assertEqual(copy, self.work / "exports" / f"{label}-{Path(item['export']).name}")
            self.assertEqual(sha256(copy), item["kept_sha256"], label)
        self.assertNotEqual(kept["youtube"]["kept_sha256"], kept["smaller"]["kept_sha256"],
                            "each quality's file survives the next export")
        self.assertIn("from main_setting", self.report.read_text(encoding="utf-8"))

    def test_a_second_run_into_the_same_work_folder_is_refused(self) -> None:
        project = Path(self.result["prepare"]["project"])
        before = json.loads((project / "project.json").read_text(encoding="utf-8"))["versions"]
        result = self.root / "second-run.json"
        done = run_tool("editor", "--backend-src", str(REPO_ROOT / "src"), "--recording", str(self.source),
                        "--work", str(self.work), "--copy-name", "race-clip.mkv", "--scripted-minutes", "0.3",
                        "--qualities", "youtube", "--skip-transcript", "--json", str(result))
        self.assertEqual(done.returncode, 2, done.stdout[-3000:] + done.stderr[-3000:])
        self.assertIn("already has a project", json.loads(result.read_text(encoding="utf-8"))["failed"])
        self.assertEqual(json.loads((project / "project.json").read_text(encoding="utf-8"))["versions"], before,
                         "no version was added")
        versions = self.result["versions"]
        self.assertEqual([versions[name]["version"] for name in ("v001", "v002", "v003")], [1, 2, 3])

    def test_the_frame_rate_copies_keep_every_track_and_export_at_their_rate(self) -> None:
        copies = self.result["fps_copies"]
        self.assertEqual(set(copies), {"30", "60000/1001"})
        for rate, item in copies.items():
            self.assertEqual(item["titles"], TITLES)
            self.assertEqual(Fraction(item["exported_fps"]), Fraction(rate))
            self.assertTrue(item["export"]["check_passed"], item)
            self.assertTrue(Path(item["copy"]).is_relative_to(self.work))

    def test_nothing_is_written_beside_the_recording_and_the_scratch_is_empty(self) -> None:
        self.assertEqual(files_under(self.source.parent), self.beside)
        self.assertEqual(list((self.work / "scratch").iterdir()), [])

    # dead-time-frames, on the project this run prepared: nothing is written unless the layout fits and
    # both camera masks are stored, and then only the centre game panel.

    def frames(self, out: Path, recording: str = "", **env_changes: str | None) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        for key, value in env_changes.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return run_tool("dead-time-frames", "--project", self.result["prepare"]["project"], "--recording",
                        recording or self.result["copy"], "--out", str(out), "--work", str(self.work), env=env)

    def test_frames_of_another_recording_are_refused_before_anything_is_written(self) -> None:
        appdata, out = self.root / "appdata-masks-other", self.root / "frames-other"
        mask_store(appdata)
        other = self.result["fps_copies"]["30"]["copy"]   # the same picture size, another recording
        done = self.frames(out, other, MEDIA_MANGLERS_RACE_VIDEO_PRIVACY=None, APPDATA=str(appdata))
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("the project was prepared from", done.stdout)
        self.assertFalse(out.exists())

    def test_a_redirected_mask_store_writes_nothing(self) -> None:
        out = self.root / "frames-redirected"
        done = self.frames(out, MEDIA_MANGLERS_RACE_VIDEO_PRIVACY=str(self.root / "elsewhere"))
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("MEDIA_MANGLERS_RACE_VIDEO_PRIVACY is set", done.stdout)
        self.assertFalse(out.exists())

    def test_without_both_camera_masks_nothing_is_written(self) -> None:
        out = self.root / "frames-no-masks"
        done = self.frames(out, MEDIA_MANGLERS_RACE_VIDEO_PRIVACY=None, APPDATA=str(self.root / "appdata-empty"))
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("no stored privacy mask for the left and right camera", done.stdout)
        self.assertFalse(out.exists())

    def test_with_both_masks_only_the_centre_panel_is_written(self) -> None:
        appdata, out = self.root / "appdata-masks", self.root / "frames"
        mask_store(appdata)
        done = self.frames(out, MEDIA_MANGLERS_RACE_VIDEO_PRIVACY=None, APPDATA=str(appdata))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        index = json.loads((out / "frames.json").read_text(encoding="utf-8"))
        self.assertEqual(index["centre_panel"], [1920, 0, 1920, 1080])
        self.assertEqual(len(index["frames"]), 1)
        self.assertEqual(frame_render.jpeg_size(index["frames"][0]["file"]), (1920, 1080))
        self.assertEqual(index["frames"][0]["found_by"], ["game_picture"])
        self.assertEqual(frame_render.jpeg_size(out / "overview-every-5-minutes.jpg"), (480, 270))


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class ReviewKitFailureTests(unittest.TestCase):
    """A review kit that does not run fails the editor step: its dead-time pacing is part of the check."""

    def test_a_review_kit_that_does_not_run_fails_the_step(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = six_track_race(root / "recordings" / "race.mkv")
            work, report = root / "work", root / "report.md"
            settings = write_settings(root / "real" / "settings.json")
            done = run_tool("environment", "--work", str(work), "--settings", str(settings),
                            "--recordings-folder", str(source.parent))
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            done = subprocess.run(
                [sys.executable, "-c", REFUSED_REVIEW_KIT, str(TOOL), "editor", "--backend-src", str(REPO_ROOT / "src"),
                 "--recording", str(source), "--work", str(work), "--copy-name", "race-clip.mkv", "--scripted-minutes",
                 "0.1", "--qualities", "", "--skip-transcript", "--report", str(report)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1200, cwd=str(REPO_ROOT))
            result = json.loads((work / "results" / "editor-race-clip.json").read_text(encoding="utf-8"))
            self.assertNotIn("failed", result, done.stdout[-3000:] + done.stderr[-3000:])
            self.assertEqual(done.returncode, 1, done.stdout[-3000:] + done.stderr[-3000:])
            self.assertTrue(result["versions"]["v001"]["review_kit_error"])
            self.assertEqual(len(result["problems"]), 1, result.get("problems"))
            self.assertTrue(result["problems"][0].startswith("review kit: "), result["problems"])
            self.assertIn("The review kit did not run", report.read_text(encoding="utf-8"))


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class QuickModelsTests(unittest.TestCase):
    """226 review: --compare-quick-models says plainly when it could not compare the two Whisper models,
    and the step does not pass."""

    def test_with_the_transcript_skipped_the_models_are_not_compared_and_the_step_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = six_track_race(root / "recordings" / "race.mkv")
            work, report = environment_for(root, source.parent), root / "report.md"
            done = run_tool("editor", "--backend-src", str(REPO_ROOT / "src"), "--recording", str(source), "--work",
                            str(work), "--copy-name", "quick.mkv", "--scripted-minutes", "0.1", "--qualities", "",
                            "--skip-transcript", "--compare-quick-models", "--report", str(report))
            result = json.loads((work / "results" / "editor-quick.json").read_text(encoding="utf-8"))
            self.assertEqual(done.returncode, 1, done.stdout[-3000:] + done.stderr[-3000:])
            self.assertFalse(result["quick_models"]["compared"])
            self.assertTrue(any("were not compared" in item for item in result["problems"]), result["problems"])
            self.assertIn("were not compared", report.read_text(encoding="utf-8"))


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class TrackChoiceTests(unittest.TestCase):
    """226: --voice-track and --game-track are sent as the page sends tracks picked by hand, for the
    recording and its frame-rate copies; a game track silent the whole recording stops the step after
    Prepare (exit 2), before any edit is made."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.source = older_layout_race(cls.root / "recordings" / "older.mkv")
        cls.work, cls.report = environment_for(cls.root, cls.source.parent), cls.root / "report.md"
        common = ["editor", "--backend-src", str(REPO_ROOT / "src"), "--recording", str(cls.source), "--work",
                  str(cls.work), "--scripted-minutes", "0.1", "--qualities", "", "--skip-transcript", "--report",
                  str(cls.report)]
        cls.stopped = run_tool(*common, "--copy-name", "auto.mkv")
        cls.picked = run_tool(*common, "--copy-name", "picked.mkv", "--voice-track", "2", "--game-track", "6",
                              "--fps-copies", "--fps-copy-seconds", "4")
        results = cls.work / "results"
        cls.stopped_result = json.loads((results / "editor-auto.json").read_text(encoding="utf-8"))
        cls.picked_result = json.loads((results / "editor-picked.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def test_a_silent_game_track_stops_the_step_before_any_edit(self) -> None:
        result = self.stopped_result
        self.assertEqual(self.stopped.returncode, 2, self.stopped.stdout[-3000:] + self.stopped.stderr[-3000:])
        prepared = result["prepare"]
        self.assertEqual((prepared["tracks"]["game"], prepared["tracks"]["game_decided_by"]), (2, "setting"),
                         "Auto took Track 3 from the Track roles")
        self.assertNotIn(2, prepared["sounding"])
        self.assertTrue(result["failed"].startswith("Track 3, the game track Prepare used for auto, is silent for the "
                                                    "whole recording"), result["failed"])
        self.assertIn("choose the game track with --game-track N", result["failed"])
        self.assertNotIn("versions", result, "no edit was made")
        meta = json.loads((Path(prepared["project"]) / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(meta.get("versions") or [], [])
        self.assertIn("- STOPPED: Track 3, the game track Prepare used for auto", self.report.read_text(encoding="utf-8"))

    def test_tracks_picked_by_hand_are_sent_as_the_page_sends_them(self) -> None:
        result = self.picked_result
        self.assertEqual(self.picked.returncode, 0, self.picked.stdout[-3000:] + self.picked.stderr[-3000:])
        self.assertNotIn("failed", result)
        self.assertEqual(result["chosen_tracks"], {"voice": 1, "game": 5})
        self.assertEqual(result["prepare"]["tracks"], {"voice": 1, "game": 5, "voice_decided_by": "override",
                                                       "game_decided_by": "override"})
        # Every Prepare's request, as the page makes it: only the boxes picked by hand send a track.
        root = Path(result["prepare"]["project"]).parents[1]
        sent = {Path(payload["source"]).name: payload.get("tracks") for payload in prepare_requests(root)}
        self.assertEqual(sent, {"auto.mkv": None, "picked.mkv": {"voice": 1, "game": 5},
                                "fps-30.mkv": {"voice": 1, "game": 5}, "fps-60000.mkv": {"voice": 1, "game": 5}})
        self.assertEqual(set(result["fps_copies"]), {"30", "60000/1001"})
        for rate, item in result["fps_copies"].items():
            with self.subTest(rate=rate):
                self.assertEqual((item["prepare_tracks"]["game"], item["prepare_tracks"]["game_decided_by"]), (5, "override"))
                self.assertTrue(item["export"]["check_passed"], item)
        self.assertEqual(result["failed_checks"], [], "with the game track picked, every render passes")
        self.assertIn("the game sound: Track 6 (chosen by hand)", self.report.read_text(encoding="utf-8"))


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class BackendSourceTests(unittest.TestCase):
    """226: a relative --backend-src is taken from the folder the tool is started in (the backend starts
    in another, where it would find some other copy of the code), and one outside the build and this
    worktree is refused before anything is built."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.clip = self.root / "recordings" / "clip.mkv"
        self.clip.parent.mkdir(parents=True)
        subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=5:d=2",
                        "-f", "lavfi", "-i", "sine=duration=2", "-map", "0:v", "-map", "1:a", "-c:v", "libx264",
                        "-preset", "ultrafast", str(self.clip)], check=True)
        self.work = environment_for(self.root, self.clip.parent)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_a_relative_backend_source_is_the_one_beside_the_tool(self) -> None:
        # run_tool starts the tool in this worktree, so "src" is this worktree's src.
        done = run_tool("smoke", "--dist", str(REPO_ROOT), "--backend-src", "src", "--clip", str(self.clip),
                        "--work", str(self.work), "--dry-run")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        results = json.loads((self.work / "results" / "smoke.json").read_text(encoding="utf-8"))
        argv = json.loads(Path(results["3 Raw bin scan"]["argv"]).read_text(encoding="utf-8"))
        self.assertIn(f"sys.path.insert(0, {str(REPO_ROOT / 'src')!r})", argv[2])

    def test_a_backend_source_outside_the_build_and_this_worktree_is_refused(self) -> None:
        outside = REPO_ROOT.parent / f"not-{REPO_ROOT.name}-a-checkout" / "src"   # never made: the path alone is refused
        result = self.root / "refused.json"
        done = run_tool("smoke", "--dist", str(self.root / "dist"), "--backend-src", str(outside), "--clip", str(self.clip),
                        "--work", str(self.work), "--dry-run", "--json", str(result))
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn(f"The backend source {outside} is outside", json.loads(result.read_text(encoding="utf-8"))["failed"])
        self.assertFalse((self.work / "smoke").exists(), "nothing was built")


BASELINE = "9e065e4"


def baseline_source(target: Path) -> Path | None:
    """``git archive 9e065e4 src`` taken out into ``target``, or None when that commit is not in this
    repository's history."""

    git = shutil.which("git")
    if not git:
        return None
    # Run at the repository's top: started in a folder below it, git archive takes only that folder.
    top = subprocess.run([git, "-C", str(REPO_ROOT), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if top.returncode != 0:
        return None
    archive = subprocess.run([git, "-C", top.stdout.strip(), "archive", "--format=tar", BASELINE, "src"],
                             capture_output=True)
    if archive.returncode != 0:
        return None
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        tar.extractall(target, filter="data")
    return target / "src"


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class CompareAnalysisTests(unittest.TestCase):
    """226: compare-analysis prepares a recording with this build and with 9e065e4's backend, through that
    backend's own command line, on the same tracks, and lists every difference in talk stretches,
    game-sound spikes and track rows."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.baseline = baseline_source(cls.root / "baseline")
        if cls.baseline is None:
            cls.temp.cleanup()
            raise unittest.SkipTest(f"{BASELINE} is not in this repository's history")
        cls.source = older_layout_race(cls.root / "recordings" / "older.mkv")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def compare(self, name: str, *extra: str) -> tuple[subprocess.CompletedProcess, dict, str]:
        work, report = environment_for(self.root, self.source.parent, name), self.root / f"{name}.md"
        done = run_tool("compare-analysis", "--recording", str(self.source), "--work", str(work), "--report", str(report),
                        *extra)
        result = json.loads((work / "results" / "compare-analysis-older.json").read_text(encoding="utf-8"))
        return done, result, report.read_text(encoding="utf-8")

    def test_every_difference_against_9e065e4_is_listed(self) -> None:
        done, result, report = self.compare("against-9e065e4", "--baseline-src", str(self.baseline), "--game-track", "6")
        self.assertEqual(done.returncode, 0, done.stdout[-3000:] + done.stderr[-3000:])
        self.assertEqual(result["baseline"]["tracks"], {"voice": 1, "game": 5}, "the older backend is given these tracks")
        self.assertTrue(Path(result["baseline"]["project"]).is_relative_to(Path(result["this_build"]["project"]).parents[2]))
        # 9e065e4 found talk from the loudness per second; this build joins the voice's speech moments (1.2 s of
        # every 4 s) into one stretch.
        self.assertEqual([(row["kind"], row["old"], row["new"]) for row in result["talking"]],
                         [("only_new", None, {"start": 0, "end": 30})])
        self.assertIn("  - only in this build: 0:00-0:30", report)
        self.assertGreater(result["differences"], 1)
        for row in result["game_sound_spikes"]:
            kind = {"only_old": "only in 9e065e4", "only_new": "only in this build"}.get(row["kind"], row["kind"])
            self.assertIn(f"  - {kind}: ", report)
        for item in result["track_rows"]:
            self.assertIn(f"  - Track {item['track']} {item['field']}: {item['old']!r} in 9e065e4", report)
        self.assertIn(f"Differences: {result['differences']} (listed, not failed)", report)

    def test_the_same_backend_lists_no_difference(self) -> None:
        done, result, report = self.compare("against-itself", "--baseline-src", str(REPO_ROOT / "src"),
                                            "--baseline-label", "this worktree", "--game-track", "6")
        self.assertEqual(done.returncode, 0, done.stdout[-3000:] + done.stderr[-3000:])
        self.assertEqual(result["differences"], 0)
        self.assertTrue(result["talking"])
        self.assertEqual({row["kind"] for row in [*result["talking"], *result["game_sound_spikes"]]}, {"same"})
        self.assertEqual(result["track_rows"], [])
        self.assertIn("Differences: 0", report)

    def test_a_silent_game_track_stops_before_the_older_backend_runs(self) -> None:
        done, result, report = self.compare("silent", "--baseline-src", str(self.baseline))
        self.assertEqual(done.returncode, 2, done.stdout[-3000:] + done.stderr[-3000:])
        self.assertIn("Track 3, the game track Prepare used for older, is silent", result["failed"])
        self.assertNotIn("baseline", result)
        self.assertIn("STOPPED: Track 3", report)


class GluedStatusLineTests(unittest.TestCase):
    """226: the tool reads a backend's normal and error output together, and Whisper's progress bar
    leaves a partial line on the error output, so a status line arrives glued after a bar
    ("...frames/s]MM_PROGRESS_V1 {...}"). Each one still counts, so the longest silence is right."""

    def test_status_lines_glued_after_a_progress_bar_are_counted(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            package = root / "fake-src" / "media_manglers"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "cli.py").write_text(GLUING_BACKEND, encoding="utf-8")
            tool = load_tool()
            resources = types.SimpleNamespace(python_exe=sys.executable, backend_source_root=root / "fake-src")
            run, data = tool._cli(resources, "race-video-prepare", {"source": "made-up.mkv"}, root / "run", root)
            self.assertEqual((run["exit_code"], data), (0, {"ok": True, "data": {}}))
            log = (root / "run" / "log.txt").read_text(encoding="utf-8")
            self.assertIn("frames/s]MM_PROGRESS_V1 {", log, "the status lines did arrive glued")
            self.assertEqual([item["activity"] for item in run["progress"]], [f"line {number}" for number in range(9)])
            summary = tool.progress_summary(run["progress"], run["seconds"])
            self.assertEqual(summary["lines"], 9)
            self.assertLess(summary["longest_gap_between_lines"], 1.5, "the lines came 0.4 s apart")


class EditorStopTests(unittest.TestCase):
    """An unexpected error in the editor step still writes its result file and exits 2 (a stop, not a
    failed check)."""

    def test_an_unexpected_error_stops_the_step_and_leaves_its_result(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            recording = root / "recordings" / "race.mkv"
            recording.parent.mkdir(parents=True)
            recording.write_bytes(b"never read")
            work, report = root / "work", root / "report.md"
            settings = write_settings(root / "real" / "settings.json",
                                      dependency_python_path=str(root / "no-python" / "python.exe"))
            done = run_tool("environment", "--work", str(work), "--settings", str(settings),
                            "--recordings-folder", str(recording.parent))
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            done = run_tool("editor", "--backend-src", str(REPO_ROOT / "src"), "--recording", str(recording),
                            "--work", str(work), "--report", str(report))
            self.assertEqual(done.returncode, 2, done.stdout[-3000:] + done.stderr[-3000:])
            result = json.loads((work / "results" / "editor-race.json").read_text(encoding="utf-8"))
            self.assertIn("unexpected", result["failed"])
            self.assertIn("STOPPED", report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
