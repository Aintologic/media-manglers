"""224 (Wave B2a, 5a): a long read shows real progress, end to end, and the shared pieces 272 reuses.

- One streaming-progress reader (``core/streaming_progress.py``): any job hands it a line parser; it reports
  how far the job has got, stops the job only when it stops moving, and lets a Skip stop it. The audio decode
  uses it, so there is one copy.
- The Inbox's frame check reads the packets' times instead of unpacking every frame, and gets exactly the
  same list, also for clips whose frames are stored out of order; when a screenshot made from a packet's time
  fails, the recording is checked frame by frame once, as before.
- "Work done of total" progress (``work_units``, with its unit) goes from the progress state file through the
  real PowerShell host's relay and heartbeat to the Workbench's Queue / Progress bar and job banner, for a
  stand-in job that is not the Inbox.
- The banner rule for every job (Decision 6): with no measure yet it shows the step's words, never "0%".
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core import review_preparation, streaming_progress, voice_track  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "Video Mangler.ps1"
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def _tool(root: Path, name: str, code: str) -> list[str]:
    """A stand-in tool: a small Python program, run the way the app runs FFprobe or FFmpeg."""

    script = root / f"{name}.py"
    script.write_text(textwrap.dedent(code), encoding="utf-8")
    return [sys.executable, "-I", str(script)]


class SharedReaderTests(unittest.TestCase):
    """The one reader, with a stand-in job that counts bytes (as the Raw bin scan will for 272)."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def bytes_read(line: str) -> float | None:
        key, _, value = line.partition("=")
        return float(value) if key == "bytes_read" else None

    def test_a_stand_in_job_reports_how_far_it_got_and_is_never_stopped_for_taking_long(self) -> None:
        tool = _tool(self.root, "reader", """
            import time
            for step in range(1, 9):
                time.sleep(0.25)
                print(f"bytes_read={step * 1000}", flush=True)
                print("note=still going", flush=True)
            """)
        seen: list[float] = []
        reports: list[tuple[float, int]] = []
        finished = streaming_progress.run(
            tool, read_line=self.bytes_read, stall_message=lambda at: f"stuck at {at}", stall_seconds=1.0,
            on_progress=seen.append, on_report=lambda at: reports.append((at, threading.get_ident())),
            report_seconds=0.3)
        # Two seconds in all, twice the stall limit: it kept moving, so it ran to the end.
        self.assertEqual((finished.returncode, finished.position, finished.complete), (0, 8000.0, True))
        self.assertEqual(seen, [float(step * 1000) for step in range(1, 9)])
        self.assertGreaterEqual(len(reports), 3)
        self.assertEqual([at for at, _ in reports], sorted(at for at, _ in reports))
        self.assertTrue(all(thread == threading.get_ident() for _, thread in reports),
                        "reports are made on the caller's thread, so a Skip raised there stops the run")

    def test_a_job_that_stops_moving_is_stopped_with_its_own_plain_reason(self) -> None:
        tool = _tool(self.root, "stuck", """
            import time
            print("bytes_read=4096", flush=True)
            for _ in range(300):
                print("bytes_read=4096", flush=True)
                time.sleep(0.2)
            """)
        started = time.monotonic()
        with self.assertRaises(streaming_progress.Stalled) as caught:
            streaming_progress.run(tool, read_line=self.bytes_read, stall_seconds=1.0,
                                   stall_message=lambda at: f"Reading stopped at {int(at)} bytes.")
        self.assertLess(time.monotonic() - started, 15, "stopped soon after it stopped moving")
        self.assertEqual(str(caught.exception), "Reading stopped at 4096 bytes.")
        self.assertIsInstance(caught.exception, RuntimeError)

    def test_what_a_report_raises_stops_the_tool_and_is_raised_again(self) -> None:
        marker = self.root / "pid.txt"
        tool = _tool(self.root, "long", f"""
            import os, time
            open({str(marker)!r}, "w").write(str(os.getpid()))
            for step in range(1, 600):
                print(f"bytes_read={{step}}", flush=True)
                time.sleep(0.1)
            """)

        class Skipped(Exception):
            pass

        def skip(_at: float) -> None:
            raise Skipped("Skipped by you.")

        started = time.monotonic()
        with self.assertRaises(Skipped):
            streaming_progress.run(tool, read_line=self.bytes_read, stall_message=str, on_report=skip,
                                   report_seconds=0.5)
        self.assertLess(time.monotonic() - started, 15)
        pid = int(marker.read_text())
        probe = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
        self.assertNotIn(str(pid), probe.stdout, "the tool was stopped, not left reading")

    def test_errors_a_tool_writes_come_back_when_no_error_file_is_given(self) -> None:
        tool = _tool(self.root, "fails", """
            import sys
            sys.stderr.write("Invalid data found when processing input\\n")
            sys.exit(1)
            """)
        finished = streaming_progress.run(tool, read_line=self.bytes_read, stall_message=str)
        self.assertEqual(finished.returncode, 1)
        self.assertEqual(finished.errors, "Invalid data found when processing input")

    def test_the_audio_decode_is_followed_by_the_shared_reader(self) -> None:
        real = streaming_progress.run
        with mock.patch.object(streaming_progress, "run", side_effect=real) as shared:
            code, reached = voice_track.run_while_progressing(
                _tool(self.root, "ffmpeg", "print('out_time_us=2500000', flush=True)\n"),
                stall_seconds=5, stderr_path=self.root / "errors.txt")
        shared.assert_called_once()
        self.assertEqual((code, reached), (0, 2.5))


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and FFprobe are required")
class FrameCheckTests(unittest.TestCase):
    """The packet check gives the full unpack's list, and falls back to it when it must."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def clip(self, name: str, *arguments: str) -> Path:
        target = self.root / name
        run = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *arguments, str(target)],
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stderr)
        return target

    def reordered(self, name: str, rate: int = 30, seconds: int = 4) -> Path:
        # B-frames: the pictures are stored out of the order they are shown in, so the packets' times are not
        # in order either.
        return self.clip(name, "-f", "lavfi", "-i", f"testsrc2=size=160x90:rate={rate}:duration={seconds}",
                         "-c:v", "libx264", "-bf", "3", "-g", "24", "-pix_fmt", "yuv420p")

    def test_reordered_frames_give_the_same_list_from_the_packets_in_both_containers(self) -> None:
        for name in ("reordered.mkv", "reordered.mp4"):
            with self.subTest(container=name):
                source = self.reordered(name)
                packets = review_preparation._probe_decodable_video_timestamps(FFPROBE, source)
                every_frame = review_preparation._probe_decodable_video_timestamps(FFPROBE, source, full=True)
                self.assertTrue(getattr(packets, "from_packets", False), "read from the packets")
                self.assertFalse(getattr(every_frame, "from_packets", False))
                self.assertEqual(len(every_frame), 120)
                self.assertEqual(list(packets), list(every_frame))
                # The packets really were out of order; the list is not.
                raw = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
                                      "packet=pts_time", "-of", "csv=p=0", str(source)],
                                     capture_output=True, text=True).stdout.split()
                self.assertNotEqual([float(value) for value in raw], sorted(float(value) for value in raw))

    def test_the_frame_check_reports_how_far_it_has_got(self) -> None:
        source = self.reordered("long.mkv", rate=60, seconds=40)
        reports: list[tuple[float, float]] = []
        with mock.patch.object(streaming_progress, "REPORT_SECONDS", 0.0), \
                mock.patch.object(streaming_progress, "LOOK_SECONDS", 0.0005):
            media = review_preparation.probe_media(FFPROBE, source, on_report=lambda at, length: reports.append(
                (at, length)))
        self.assertEqual(len(media["video_frame_timestamps"]), 2400)
        self.assertTrue(reports, "progress was reported while the video was checked")
        self.assertTrue(all(length == media["duration_seconds"] for _, length in reports))
        self.assertEqual([at for at, _ in reports], sorted(at for at, _ in reports))

    def test_a_packet_without_a_time_sends_the_recording_to_the_full_check(self) -> None:
        ffprobe = self.root / "ffprobe.cmd"
        script = self.root / "ffprobe.py"
        script.write_text(textwrap.dedent("""
            import sys
            if "-show_frames" in sys.argv:
                for value in ("0.000000", "0.033000", "0.067000"):
                    print(f"best_effort_timestamp_time={value}")
            else:
                print("pts_time=0.000000|flags=K__")
                print("pts_time=N/A|flags=___")
                print("pts_time=0.067000|flags=___")
            """), encoding="utf-8")
        ffprobe.write_text(f'@"{sys.executable}" -I "{script}" %*\r\n', encoding="ascii")
        times = review_preparation._probe_decodable_video_timestamps(str(ffprobe), self.root / "any.mkv")
        self.assertEqual(list(times), [0.0, 0.033, 0.067])
        self.assertFalse(getattr(times, "from_packets", False), "the full check's list")

    def test_a_dropped_or_damaged_packet_is_handled_as_the_decoder_would(self) -> None:
        ffprobe = self.root / "ffprobe.cmd"
        script = self.root / "ffprobe.py"
        script.write_text(textwrap.dedent("""
            import sys
            if "-show_frames" in sys.argv:
                print("best_effort_timestamp_time=0.100000")
            elif "damaged" in sys.argv[-1]:
                print("pts_time=0.100000|flags=K_C")
            else:
                # A packet the decoder is told to drop never becomes a picture.
                print("pts_time=0.000000|flags=_D_")
                print("pts_time=0.100000|flags=K__")
            """), encoding="utf-8")
        ffprobe.write_text(f'@"{sys.executable}" -I "{script}" %*\r\n', encoding="ascii")
        dropped = review_preparation._probe_decodable_video_timestamps(str(ffprobe), self.root / "dropped.mkv")
        self.assertEqual((list(dropped), getattr(dropped, "from_packets", False)), ([0.1], True))
        damaged = review_preparation._probe_decodable_video_timestamps(str(ffprobe), self.root / "damaged.mkv")
        self.assertEqual((list(damaged), getattr(damaged, "from_packets", False)), ([0.1], False))

    def test_a_recording_that_does_not_start_on_a_keyframe_gets_the_full_check(self) -> None:
        # 224 (Wave B2a review): pictures before the first keyframe cannot be unpacked, so their packets' times
        # are not pictures; such a recording is checked frame by frame. A dropped packet before it does not count.
        ffprobe = self.root / "ffprobe.cmd"
        script = self.root / "ffprobe.py"
        script.write_text(textwrap.dedent("""
            import sys
            if "-show_frames" in sys.argv:
                print("best_effort_timestamp_time=0.100000")
            elif "keyed" in sys.argv[-1]:
                print("pts_time=0.000000|flags=_D_")
                print("pts_time=0.100000|flags=K__")
            else:
                print("pts_time=0.000000|flags=___")
                print("pts_time=0.100000|flags=K__")
            """), encoding="utf-8")
        ffprobe.write_text(f'@"{sys.executable}" -I "{script}" %*\r\n', encoding="ascii")
        cut = review_preparation._probe_decodable_video_timestamps(str(ffprobe), self.root / "cut.mkv")
        self.assertEqual((list(cut), getattr(cut, "from_packets", False)), ([0.1], False))
        keyed = review_preparation._probe_decodable_video_timestamps(str(ffprobe), self.root / "keyed.mkv")
        self.assertEqual((list(keyed), getattr(keyed, "from_packets", False)), ([0.1], True))

    def test_how_far_the_check_has_got_counts_from_the_recordings_first_picture(self) -> None:
        ffprobe = self.root / "ffprobe.cmd"
        script = self.root / "ffprobe.py"
        script.write_text(textwrap.dedent("""
            import time
            for step in range(40):
                print(f"pts_time={100 + step / 10:.6f}|flags={'K__' if step == 0 else '___'}", flush=True)
                time.sleep(0.02)
            """), encoding="utf-8")
        ffprobe.write_text(f'@"{sys.executable}" -I "{script}" %*\r\n', encoding="ascii")
        reports: list[float] = []
        with mock.patch.object(streaming_progress, "REPORT_SECONDS", 0.0), \
                mock.patch.object(streaming_progress, "LOOK_SECONDS", 0.01):
            review_preparation._probe_decodable_video_timestamps(str(ffprobe), self.root / "late.mkv",
                                                                 on_report=reports.append)
        self.assertTrue(reports)
        self.assertTrue(all(0 <= at <= 4.0 for at in reports), reports)

    def test_the_fallback_full_check_reports_how_far_it_has_got(self) -> None:
        source = self.reordered("again.mkv", rate=60, seconds=20)
        right = review_preparation._probe_decodable_video_timestamps(FFPROBE, source, full=True)
        wrong = review_preparation._PacketTimes(round(value + 0.005, 6) for value in right)
        media = {"duration_seconds": 20.0, "video_streams": [{"width": 160, "height": 90}],
                 "video_frame_timestamps": wrong}
        reports: list[tuple[float, float]] = []
        with mock.patch.object(streaming_progress, "REPORT_SECONDS", 0.0), \
                mock.patch.object(streaming_progress, "LOOK_SECONDS", 0.0005):
            review_preparation._render_visuals(FFMPEG, source, media, self.root / "visuals", include_panel_crops=False,
                                               ffprobe_exe=FFPROBE, on_report=lambda at, length: reports.append(
                                                   (at, length)))
        self.assertTrue(reports, "the frame-by-frame check said how far it had got")
        self.assertTrue(all(length == 20.0 for _, length in reports))

    def test_a_check_that_stops_moving_is_stopped_with_a_plain_reason(self) -> None:
        ffprobe = self.root / "ffprobe.cmd"
        script = self.root / "ffprobe.py"
        script.write_text(textwrap.dedent("""
            import time
            print("pts_time=65.000000|flags=K__", flush=True)
            time.sleep(60)
            """), encoding="utf-8")
        ffprobe.write_text(f'@"{sys.executable}" -I "{script}" %*\r\n', encoding="ascii")
        started = time.monotonic()
        with mock.patch.object(streaming_progress, "STALL_SECONDS", 1.0), \
                self.assertRaises(RuntimeError) as caught:
            review_preparation._probe_decodable_video_timestamps(str(ffprobe), self.root / "slow.mkv")
        self.assertLess(time.monotonic() - started, 20)
        self.assertIn("Checking the video stopped making progress", str(caught.exception))
        self.assertIn("01:05 into the recording", str(caught.exception))

    def test_a_screenshot_that_misses_its_packet_time_falls_back_to_the_full_check_once(self) -> None:
        source = self.reordered("clip.mkv")
        right = review_preparation._probe_decodable_video_timestamps(FFPROBE, source, full=True)
        # A packet list that does not hold for this recording: every time a little after its picture.
        wrong = review_preparation._PacketTimes(round(value + 0.01, 6) for value in right)
        media = {"duration_seconds": 4.0, "video_streams": [{"width": 160, "height": 90}],
                 "video_frame_timestamps": wrong}
        visuals = review_preparation._render_visuals(FFMPEG, source, media, self.root / "visuals",
                                                     include_panel_crops=False, ffprobe_exe=FFPROBE)
        self.assertEqual(list(media["video_frame_timestamps"]), list(right), "the full check's list is kept")
        for frame in visuals["frames"]:
            self.assertIn(frame["actual_timestamp_seconds"], right)
        self.assertEqual(sorted(p.name for p in (self.root / "visuals" / "frames").iterdir()),
                         [f"frame-{ordinal:03d}.jpg" for ordinal in range(1, visuals["frame_count"] + 1)])

    def test_a_screenshot_failure_with_a_right_list_still_stops_the_package(self) -> None:
        source = self.reordered("clip.mkv")
        media = review_preparation.probe_media(FFPROBE, source)
        self.assertTrue(getattr(media["video_frame_timestamps"], "from_packets", False))
        real = review_preparation._run
        unpacks: list[bool] = []
        real_probe = review_preparation._probe_decodable_video_timestamps

        def failing(command: list[str], *, timeout: int = 300):
            if "showinfo" in command:
                raise RuntimeError("FFmpeg could not read the recording here.")
            return real(command, timeout=timeout)

        def counted(*args, **options):
            unpacks.append(bool(options.get("full")))
            return real_probe(*args, **options)

        with mock.patch.object(review_preparation, "_run", side_effect=failing), \
                mock.patch.object(review_preparation, "_probe_decodable_video_timestamps", side_effect=counted), \
                self.assertRaisesRegex(RuntimeError, "could not read the recording here"):
            review_preparation._render_visuals(FFMPEG, source, media, self.root / "visuals",
                                               include_panel_crops=False, ffprobe_exe=FFPROBE)
        self.assertEqual(unpacks, [True], "checked frame by frame once, then the failure stands")


@unittest.skipUnless(os.name == "nt", "the PowerShell host is checked on Windows")
class HostRelayTests(unittest.TestCase):
    """The real host relays a stand-in helper's work done of total, with its unit, and keeps it between
    reports."""

    FUNCTIONS = (
        "Quote-Argument", "Format-DurationHuman", "Get-ExternalFailureSummary", "Get-MMRunControl",
        "Test-MMSourceSkipRequested", "Test-MMPauseRequested", "Test-MMSkipException", "Get-MMProcessTreeIds",
        "Stop-MMProcessTree", "Set-MMProcessTreeSuspended", "Wait-MMWhilePaused", "Test-MMStartingAppAlive", "Invoke-MMRunControlCheck",
        "Read-ProgressStateFile", "Get-ProgressDeviceValue", "Get-ProgressDeviceTag", "Get-ProgressStateSummary",
        "Get-ProgressStateSignature", "Invoke-ExternalStreaming", "Write-MMProgressV1",
    )

    HELPER = """
        import json, os, sys, time
        from datetime import datetime, timezone
        path = sys.argv[1]
        def state(**fields):
            event = {"schema": "MM_PROGRESS_V1", "phase": "Scanning the raw bin", "source_name": "race.mkv",
                     "source_total": 1, "source_ordinal": 1, "source_state": "active",
                     "updated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), **fields}
            with open(path + ".tmp", "w", encoding="utf-8") as handle:
                json.dump(event, handle)
            for _ in range(40):
                try:
                    os.replace(path + ".tmp", path)
                    return
                except OSError:
                    time.sleep(0.05)
        state(progress_kind="indeterminate", activity="Opening the recording")
        time.sleep(1.2)
        gib = 1024 ** 3
        for done in (6, 12, 18):
            state(progress_kind="work_units", completed=done * gib, total=54 * gib, work_unit="bytes",
                  activity=f"Reading the recording: {done} GB of 54 GB")
            time.sleep(1.2)
        # A long stretch with no new report: the heartbeat carries the last measure.
        time.sleep(3.5)
        """

    def relay(self) -> list[dict]:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            helper = root / "helper.py"
            helper.write_text(textwrap.dedent(self.HELPER), encoding="utf-8")
            state = root / "progress.json"
            names = ",".join(f"'{name}'" for name in self.FUNCTIONS)
            harness = root / "harness.ps1"
            harness.write_text(textwrap.dedent(f"""
                $ErrorActionPreference = 'Stop'
                $tokens = $null; $parseErrors = $null
                $ast = [System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', [ref]$tokens, [ref]$parseErrors)
                $wanted = @({names})
                foreach ($node in $ast.FindAll({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $wanted -contains $n.Name }}, $true)) {{
                    Invoke-Expression $node.Extent.Text
                }}
                function Write-Log {{ }}
                $script:MMRunControlPath = ''
                $script:MMRunControlCache = $null
                $script:MMRunControlReadAt = [datetime]::MinValue
                $script:MMLastResumeAt = $null
                $script:MMProgressPhase = 'Scanning the raw bin'
                $null = Invoke-ExternalStreaming -FilePath '{sys.executable}' -Arguments @('-I', '{helper}', '{state}') -StepName 'raw bin scan' -HeartbeatSeconds 1 -ProgressStateFilePath '{state}'
                """).strip(), encoding="utf-8")
            completed = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                        str(harness)], capture_output=True, text=True, timeout=120)
            self.assertEqual(completed.returncode, 0, completed.stderr)
        return [json.loads(line[len("MM_PROGRESS_V1 "):]) for line in completed.stdout.splitlines()
                if line.startswith("MM_PROGRESS_V1 ")]

    def test_work_done_of_total_reaches_the_workbench_with_its_unit_and_the_heartbeat_keeps_it(self) -> None:
        events = self.relay()
        measured = [event for event in events if event["progress_kind"] == "work_units"]
        gib = 1024 ** 3
        reports = [event for event in measured if not event["heartbeat"]]
        self.assertEqual([event["completed"] for event in reports], [6 * gib, 12 * gib, 18 * gib])
        self.assertTrue(all(event["total"] == 54 * gib and event["work_unit"] == "bytes" for event in measured))
        self.assertIn("Reading the recording: 18 GB of 54 GB", [event["activity"] for event in measured])
        last_report = events.index(reports[-1])
        after = events[last_report + 1:]
        self.assertTrue(after, "the host kept beating after the last report")
        self.assertTrue(all(event["heartbeat"] for event in after))
        self.assertTrue(all(event["progress_kind"] == "work_units" and event["completed"] == 18 * gib
                            for event in after), "a heartbeat never resets a measured step to 'no measure'")
        unmeasured = [event for event in events if event["progress_kind"] != "work_units"]
        self.assertTrue(unmeasured and all(event["work_unit"] == "" for event in unmeasured))
        # Kept for the Workbench test below: the host's own lines, as the Workbench reads them.
        HostRelayTests.relayed = ["MM_PROGRESS_V1 " + json.dumps(event) for event in events]


class _Listener:
    def on_log_line(self, _stream: str, _line: str) -> None:
        pass

    def on_finished(self, _result: object) -> None:
        pass


class WorkbenchShowsWorkDoneTests(unittest.TestCase):
    """The Workbench's Queue / Progress bar and job banner, from the host's lines."""

    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication  # noqa: PLC0415

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        from media_manglers_workbench.app import WorkbenchWindow  # noqa: PLC0415
        from tests.test_design_wave_d1 import _resources  # noqa: PLC0415

        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window = WorkbenchWindow(settings_path=self.root / "settings.json", profiles_dir=self.root / "profiles",
                                      resources=_resources())
        self.window.show()
        self.app.processEvents()
        self.release = threading.Event()
        self.lines: list[str] = []

    def tearDown(self) -> None:
        self.release.set()
        if self.window.runner_thread is not None:
            self.window.runner_thread.wait(10000)
            self.app.processEvents()
        self.window._closing_after_smoke = True
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def start(self, lines: list[str]) -> None:
        from media_manglers_workbench.command_builder import CommandSpec  # noqa: PLC0415
        from media_manglers_workbench.runner import RunnerResult  # noqa: PLC0415

        test = self
        printed = threading.Event()

        class Runner:
            def cancel(self) -> None:
                test.release.set()

            def run(self, command, on_log=None, *, cwd=None) -> RunnerResult:
                for line in lines:
                    on_log("stdout", line)
                printed.set()
                test.release.wait(30)
                return RunnerResult(status="succeeded", exit_code=0, stdout_lines=[], error="")

        self.window.runner_factory = Runner
        started = self.window.start_external_run(
            CommandSpec(["backend"], "backend"), title="Raw bin scan", settings={"output_folder": str(self.root)},
            queue_items=["race.mkv"], listener=_Listener(), evidence_package=False, origin="Raw Bin",
            banner_title="Scanning race.mkv")
        self.assertTrue(started)
        printed.wait(10)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and self.window.progress_bar.maximum() == 0 and any(
                '"work_units"' in line for line in lines):
            self.app.processEvents()
            time.sleep(0.02)
        for _ in range(20):
            self.app.processEvents()

    @unittest.skipUnless(os.name == "nt", "the PowerShell host is checked on Windows")
    def test_a_stand_in_jobs_bytes_show_on_the_bar_and_its_banner_shows_a_real_percent(self) -> None:
        relayed = getattr(HostRelayTests, "relayed", None)
        if relayed is None:
            HostRelayTests("test_work_done_of_total_reaches_the_workbench_with_its_unit_and_the_heartbeat_keeps_it"
                           ).test_work_done_of_total_reaches_the_workbench_with_its_unit_and_the_heartbeat_keeps_it()
            relayed = HostRelayTests.relayed
        self.start(relayed)
        self.assertEqual(self.window.progress_bar.format(), "18.0 GB of 54.0 GB")
        banner = self.window.raw_bin_page.job_banner
        self.assertEqual(banner.info.percent, 33)
        self.assertIn("33%", banner.numbers_label.text())

    def test_a_job_with_no_measure_yet_shows_its_step_words_on_the_banner_never_0_percent(self) -> None:
        event = {"schema": "MM_PROGRESS_V1", "phase": "Validating source", "progress_kind": "indeterminate",
                 "source_name": "race.mkv", "source_completed": 0, "source_total": 1, "source_ordinal": 1,
                 "source_state": "active", "activity": "Rechecking source stability and media metadata"}
        self.start(["MM_PROGRESS_V1 " + json.dumps(event)])
        banner = self.window.raw_bin_page.job_banner
        self.assertIsNone(banner.info.percent)
        self.assertNotIn("0%", banner.numbers_label.text())
        self.assertIn("Rechecking source stability", banner.numbers_label.text())
        self.assertEqual(banner.bar.maximum(), 0, "a moving bar, not one stuck at 0")

    def test_the_frame_check_shows_the_recordings_time_on_the_bar(self) -> None:
        event = {"schema": "MM_PROGRESS_V1", "phase": "Validating source", "progress_kind": "work_units",
                 "completed": 252, "total": 1350, "work_unit": "seconds", "source_name": "race.mkv",
                 "source_completed": 0, "source_total": 1, "source_ordinal": 1, "source_state": "active",
                 "activity": "Checking the video: 04:12 of 22:30 checked (18%)"}
        self.start(["MM_PROGRESS_V1 " + json.dumps(event)])
        self.assertEqual(self.window.progress_bar.format(), "04:12 of 22:30")
        self.assertEqual(self.window.raw_bin_page.job_banner.info.percent, 18)


if __name__ == "__main__":
    unittest.main()
