"""Skip, pause and resume for long bug-report runs (114, 115)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
import wave

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from media_manglers.core.evidence_package import _quality_summary  # noqa: E402
from media_manglers_workbench.bug_reports import (  # noqa: E402
    RunSummary,
    format_duration,
    newest_recordings,
    results_headline,
    summarize_package,
)
from media_manglers_workbench.command_builder import build_workflow_command  # noqa: E402
from media_manglers_workbench.metadata import WORKFLOW_CODEX_EVIDENCE  # noqa: E402
from media_manglers_workbench.run_control import RunControl  # noqa: E402
from media_manglers_workbench.settings import build_default_settings  # noqa: E402

SCRIPT = REPO_ROOT / "Video Mangler.ps1"


class RunControlFileTests(unittest.TestCase):
    def test_skip_and_pause_are_written_for_the_backend(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            control = RunControl.for_folder(Path(temp))
            self.assertEqual(json.loads(control.path.read_text(encoding="utf-8")), {"pause": False, "skip": []})
            added = control.skip([r"D:\\Rec\\A.mkv", r"d:\\rec\\a.mkv", r"D:\\Rec\\B.mkv"])
            self.assertEqual(len(added), 2, "the same recording is only listed once, whatever its case")
            control.set_paused(True)
            payload = json.loads(control.path.read_text(encoding="utf-8"))
            self.assertTrue(payload["pause"])
            self.assertEqual(len(payload["skip"]), 2)
            self.assertFalse(control.path.with_suffix(".tmp").exists())


class CommandTests(unittest.TestCase):
    def test_command_passes_control_file_and_low_priority(self) -> None:
        settings = build_default_settings()
        settings.update({"input_path": r"C:\\in\\list.mmlist", "output_folder": r"C:\\out", "run_control_path": r"C:\\out\\run-control.json"})
        argv = build_workflow_command(settings, workflow=WORKFLOW_CODEX_EVIDENCE).argv
        self.assertIn("-RunControlPath", argv)
        self.assertEqual(argv[argv.index("-RunControlPath") + 1], r"C:\\out\\run-control.json")
        self.assertIn("-LowPriority", argv)
        settings["run_low_priority"] = False
        self.assertNotIn("-LowPriority", build_workflow_command(settings, workflow=WORKFLOW_CODEX_EVIDENCE).argv)


class PackageSummaryTests(unittest.TestCase):
    def test_skipped_recordings_are_not_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "sources": [
                            {"status": "completed", "transcript_quality": {"quality_status": "usable"}},
                            {"status": "operator_skipped", "transcript_quality": {"quality_status": "skipped_by_operator"}},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            summary = summarize_package(root, "succeeded", [])
        self.assertEqual((summary.usable, summary.total, summary.skipped), (1, 1, 1))
        self.assertIn("1 skipped by you", results_headline(summary))

    def test_quality_summary_keeps_skipped_out_of_suspicious(self) -> None:
        sources = [
            {"transcript_quality": {"quality_status": "usable", "appears_usable": True}},
            {"transcript_quality": {"quality_status": "skipped_by_operator", "appears_usable": False, "risk_classification": "skipped_by_operator"}},
        ]
        summary = _quality_summary(sources)
        self.assertEqual(summary["skipped_by_operator_source_count"], 1)
        self.assertEqual(summary["suspicious_source_count"], 0)
        self.assertEqual(summary["usable_source_count"], 1)
        self.assertFalse(summary["all_sources_suspicious"])

    def test_headline_without_skips_is_unchanged(self) -> None:
        summary = RunSummary(status="complete", package_root=Path("."), usable=2, total=2)
        self.assertNotIn("skipped", results_headline(summary))


class RecordingPickTests(unittest.TestCase):
    def test_add_newest_leaves_out_done_and_never_use_recordings(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            paths = []
            for index, name in enumerate(("old.mkv", "done.mkv", "new.mkv")):
                path = folder / name
                path.write_bytes(b"x")
                os.utime(path, (1_000_000 + index, 1_000_000 + index))
                paths.append(path)
            picked = newest_recordings(folder, 2, leave_out={str(paths[1]).lower()})
        self.assertEqual([path.name for path in picked], ["new.mkv", "old.mkv"])

    def test_duration_is_plain_english(self) -> None:
        self.assertEqual(format_duration(4 * 3600 - 180), "3 h 57 min")
        self.assertEqual(format_duration(37 * 60), "37 min")


@unittest.skipUnless(os.name == "nt", "PowerShell behaviour is checked on Windows")
class BackendRunControlTests(unittest.TestCase):
    """Run the real backend functions against a real child process."""

    FUNCTIONS = (
        "Quote-Argument",
        "Format-DurationHuman",
        "Get-ExternalFailureSummary",
        "Get-MMRunControl",
        "Test-MMSourceSkipRequested",
        "Test-MMPauseRequested",
        "Test-MMSkipException",
        "Get-MMProcessTreeIds",
        "Stop-MMProcessTree",
        "Set-MMProcessTreeSuspended",
        "Wait-MMWhilePaused",
        "Invoke-MMRunControlCheck",
        "Test-MMCompleteJpeg",
        "Invoke-ExternalCapture",
    )

    def _run(self, body: str, control: dict | None, *, flip_after: float | None = None, timeout: int = 60) -> dict:
        with tempfile.TemporaryDirectory() as temp:
            control_path = Path(temp) / "run-control.json"
            if control is not None:
                control_path.write_text(json.dumps(control), encoding="utf-8")
            names = ",".join(f"'{name}'" for name in self.FUNCTIONS)
            source = textwrap.dedent(
                f"""
                $ErrorActionPreference = 'Stop'
                $tokens = $null; $parseErrors = $null
                $ast = [System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', [ref]$tokens, [ref]$parseErrors)
                $wanted = @({names})
                foreach ($node in $ast.FindAll({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $wanted -contains $n.Name }}, $true)) {{
                    Invoke-Expression $node.Extent.Text
                }}
                function Write-Log {{ }}
                function Write-MMProgressV1 {{ }}
                function Add-LogContentWithRetry {{ }}
                $script:CurrentLogFile = $null
                $script:MMProgressPhase = 'Test'
                $script:MMRunControlPath = '{control_path}'
                $script:MMRunControlCache = $null
                $script:MMRunControlReadAt = [datetime]::MinValue
                $script:MMCurrentSourcePath = 'D:\\Rec\\A.mkv'
                $script:MMSkipRequested = $false
                $script:MMLastResumeAt = $null
                $script:MMSkipMessagePrefix = 'MM_SKIP_REQUESTED'
                {body}
                """
            ).strip()
            harness = Path(temp) / "harness.ps1"
            harness.write_text(source, encoding="utf-8")
            process = subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if flip_after is not None:
                time.sleep(flip_after)
                control_path.write_text(json.dumps({"pause": False, "skip": []}), encoding="utf-8")
            stdout, stderr = process.communicate(timeout=timeout)
            self.assertEqual(process.returncode, 0, stderr)
            return json.loads(stdout.strip().splitlines()[-1])

    CHILD = "-FilePath 'powershell.exe' -Arguments @('-NoProfile', '-Command', 'Start-Sleep -Seconds 20')"

    def test_skipping_the_current_recording_stops_its_tool_at_once(self) -> None:
        result = self._run(
            f"""
            $sw = [Diagnostics.Stopwatch]::StartNew()
            $message = ''
            try {{ $null = Invoke-ExternalCapture {self.CHILD} -StepName 'child' }} catch {{ $message = $_.Exception.Message }}
            @{{ seconds = $sw.Elapsed.TotalSeconds; message = $message; skipFlag = $script:MMSkipRequested }} | ConvertTo-Json -Compress
            """,
            {"pause": False, "skip": ["d:\\rec\\a.mkv"]},
        )
        self.assertTrue(result["message"].startswith("MM_SKIP_REQUESTED"), result)
        self.assertTrue(result["skipFlag"])
        self.assertLess(result["seconds"], 10, "a skipped tool must not run to the end")

    def test_other_recordings_in_the_skip_list_do_not_stop_this_one(self) -> None:
        result = self._run(
            """
            $capture = Invoke-ExternalCapture -FilePath 'powershell.exe' -Arguments @('-NoProfile', '-Command', 'exit 0') -StepName 'child'
            @{ exit = $capture.ExitCode } | ConvertTo-Json -Compress
            """,
            {"pause": False, "skip": ["D:\\Rec\\Other.mkv"]},
        )
        self.assertEqual(result["exit"], 0)

    def test_pause_holds_the_tool_until_resume_without_timing_out(self) -> None:
        result = self._run(
            """
            $sw = [Diagnostics.Stopwatch]::StartNew()
            $capture = Invoke-ExternalCapture -FilePath 'powershell.exe' -Arguments @('-NoProfile', '-Command', 'Start-Sleep -Milliseconds 500; exit 0') -StepName 'child' -TimeoutSeconds 3
            @{ seconds = $sw.Elapsed.TotalSeconds; exit = $capture.ExitCode } | ConvertTo-Json -Compress
            """,
            {"pause": True, "skip": []},
            flip_after=6.0,
        )
        self.assertEqual(result["exit"], 0)
        self.assertGreaterEqual(result["seconds"], 4.0, "the run must wait while paused")

    def test_only_whole_screenshots_are_reused(self) -> None:
        result = self._run(
            """
            $folder = Join-Path $env:TEMP ('mm-jpeg-' + [guid]::NewGuid().ToString('N'))
            New-Item -ItemType Directory -Path $folder | Out-Null
            $whole = Join-Path $folder 'whole.jpg'; [IO.File]::WriteAllBytes($whole, [byte[]](0xFF,0xD8,1,2,3,0xFF,0xD9))
            $cut = Join-Path $folder 'cut.jpg'; [IO.File]::WriteAllBytes($cut, [byte[]](0xFF,0xD8,1,2,3,4))
            $out = @{ whole = (Test-MMCompleteJpeg -Path $whole); cut = (Test-MMCompleteJpeg -Path $cut); missing = (Test-MMCompleteJpeg -Path (Join-Path $folder 'none.jpg')) }
            Remove-Item -LiteralPath $folder -Recurse -Force
            $out | ConvertTo-Json -Compress
            """,
            None,
        )
        self.assertEqual(result, {"whole": True, "cut": False, "missing": False})


@unittest.skipUnless(os.name == "nt", "PowerShell behaviour is checked on Windows")
class BackendProgressLimitTests(unittest.TestCase):
    """Voice detection and narration extraction are stopped only when they stop moving.

    The real backend functions run real child processes: a stand-in helper and
    a stand-in FFmpeg that report progress the way the real ones do, and the
    real FFmpeg on a generated recording.
    """

    FUNCTIONS = BackendRunControlTests.FUNCTIONS + (
        "Read-ProgressStateFile",
        "Get-ProgressDeviceValue",
        "Get-ProgressDeviceTag",
        "Get-ProgressStateSummary",
        "Get-ProgressStateSignature",
        "Invoke-ExternalStreaming",
        "Get-MediaManglersPythonCliInfo",
        "Invoke-MediaManglersPythonCli",
        "Invoke-VoiceTrackDetection",
        "Export-TranscriptSourceWav",
        "Export-AudioMp3",
        "Ensure-Directory",
        "Remove-MMScratchPath",
        "Get-MediaManglersPythonCliUnavailableMessage",
        "Get-MMScratchPath",
        "Remove-MMOrphanedScratch",
        "Test-ConsoleDebugMode",
        "Get-CodexEvidenceProblemReason",
    )
    _run = BackendRunControlTests._run

    # Collect what the backend logs, and point the Python helper at a folder.
    PRELUDE = """
        $script:Logs = New-Object System.Collections.Generic.List[string]
        function Write-Log { param([string]$Message, [string]$Level = 'INFO') $script:Logs.Add(('{0} {1}' -f $Level, $Message)) }
        $script:MediaManglersPythonCliInfo = [pscustomobject]@{ Enabled = $true; Root = [System.IO.Path]::GetTempPath(); EntryPoint = '' }
        """

    # 214: the narration WAV is made by the shared decoder through the real Python helper.
    PRELUDE_SHARED = PRELUDE + """
        $script:MediaManglersPythonCliInfo = [pscustomobject]@{ Enabled = $true; Root = 'SRC'; EntryPoint = '' }
        """.replace("SRC", str(REPO_ROOT / "src"))

    HELPER = textwrap.dedent(
        """
        import json, os, subprocess, sys, time
        from datetime import datetime, timezone
        args = sys.argv[1:]
        with open(args[args.index('--request-file') + 1], encoding='utf-8-sig') as handle:
            payload = json.load(handle)['payload']
        with open(RECORD, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle)
        work = payload.get('work_dir')
        if work:
            os.makedirs(os.path.join(work, 'voice-track-probe'), exist_ok=True)
            with open(os.path.join(work, 'voice-track-probe', 'track-0.wav'), 'wb') as handle:
                handle.write(b'0' * 4096)
        def report(message):
            path = payload['progress_state_file_path']
            state = {'message': message, 'elapsed_seconds': 0,
                     'updated_at_utc': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}
            with open(path + '.tmp', 'w', encoding='utf-8') as handle:
                json.dump(state, handle)
            for _ in range(20):
                try:
                    os.replace(path + '.tmp', path)
                    return
                except OSError:
                    time.sleep(0.05)
        if MODE == 'working':
            for step in range(14):
                report(f'Finding your voice: step {step}')
                time.sleep(0.3)
            data = {'status': 'selected', 'selected_ordinal': 1, 'confidence': 1.0, 'tracks': [], 'explanation': 'heard'}
            with open(args[args.index('--result-file') + 1], 'w', encoding='utf-8') as handle:
                json.dump({'ok': True, 'data': data, 'error': ''}, handle)
        else:
            report('Finding your voice: reading the audio, 00:10 of 01:00:00')
            time.sleep(0.3)
            report('Finding your voice: reading the audio, 00:20 of 01:00:00')
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
            with open(CHILD, 'w', encoding='ascii') as handle:
                handle.write(str(child.pid))
            time.sleep(60)
        """
    )

    # Real FFmpeg, as the shared decoder runs it: progress on stdout ("-progress pipe:1").
    FFMPEG = textwrap.dedent(
        """
        import json, os, sys, time
        args = sys.argv[1:]
        with open(RECORD, 'w', encoding='utf-8') as handle:
            json.dump({'args': args, 'pid': os.getpid()}, handle)
        if args[args.index('-progress') + 1] != 'pipe:1':
            sys.stderr.write('progress is not on pipe:1\\n')
            sys.exit(2)
        if MODE == 'fails':
            sys.stderr.write("Stream map '0:a:9' matches no streams.\\n")
            sys.exit(1)
        if MODE == 'stuck':
            # FFmpeg writes the WAV as it reads, so a stuck one has written part of it.
            with open(args[-1], 'wb') as partial:
                partial.write(b'RIFF' + bytes(1000000))
                partial.flush()
                with open(RECORD, 'w', encoding='utf-8') as handle:
                    json.dump({'args': args, 'pid': os.getpid(), 'partial_bytes': 1000004}, handle)
                if globals().get('CONTROL'):
                    # The operator presses Skip for this recording.
                    with open(CONTROL, 'w', encoding='utf-8') as handle:
                        json.dump({'pause': False, 'skip': [SKIP]}, handle)
                # FFmpeg 8.1 with a stalled input: same position, progress=continue, forever.
                while True:
                    print('out_time_us=65000000', flush=True)
                    print('progress=continue', flush=True)
                    time.sleep(0.2)
        for step in range(1, STEPS + 1):
            print(f'out_time_us={step * 300000}', flush=True)
            print('progress=continue', flush=True)
            time.sleep(0.3)
        print('progress=end', flush=True)
        with open(args[-1], 'wb') as handle:
            handle.write(b'RIFF')
        """
    )

    # A slow drive: FFmpeg reports one position, then nothing new for 4.5 s.
    # The operator presses Pause 1.5 s into that wait, once the backend has
    # seen the position, and the run resumes later.
    PAUSING = textwrap.dedent(
        """
        import json, sys, time
        args = sys.argv[1:]
        print('out_time_us=1000000', flush=True)
        print('progress=continue', flush=True)
        # Short sleeps: time spent suspended by the pause does not count towards these waits.
        for _ in range(15):
            time.sleep(0.1)
        with open(CONTROL, 'w', encoding='utf-8') as handle:
            json.dump({'pause': True, 'skip': []}, handle)
        for _ in range(30):
            time.sleep(0.1)
        for step in range(2, 6):
            print(f'out_time_us={step * 1000000}', flush=True)
            print('progress=continue', flush=True)
            time.sleep(0.2)
        print('progress=end', flush=True)
        with open(args[-1], 'wb') as handle:
            handle.write(b'RIFF')
        """
    )

    def _extract(self, root: Path, ffmpeg: Path, output: Path, extra: str = "") -> str:
        """The backend call, with this test's scratch folder and Python."""

        return (f"$($env:MEDIA_MANGLERS_SCRATCH_ROOT = '{root / 'scratch'}'; "
                f"Export-TranscriptSourceWav -PythonCommand '{sys.executable}' -FFmpegExe '{ffmpeg}' "
                f"-InputVideo '{root / 'session.mkv'}' -OutputWav '{output}' -FfmpegMap '0:a:1' {extra})")

    def _fake(self, root: Path, name: str, code: str, **values: object) -> Path:
        script = root / f"{name}.py"
        script.write_text(
            "".join(f"{key} = {value!r}\n" for key, value in values.items()) + code, encoding="utf-8"
        )
        launcher = root / f"{name}.cmd"
        launcher.write_text(f'@"{sys.executable}" -I "{script}" %*\r\n', encoding="ascii")
        return launcher

    def test_voice_detection_has_only_a_stall_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            record = root / "payload.json"
            helper = self._fake(root, "helper", self.HELPER, RECORD=str(record), MODE="working", CHILD="")
            result = self._run(
                self.PRELUDE
                + f"""
                $data = Invoke-VoiceTrackDetection -PythonCommand '{helper}' -FFmpegExe 'ffmpeg' -FFprobeExe 'ffprobe' -VideoPath '{root / "session.mkv"}' -DurationSeconds 3600 -StallTimeoutSeconds 2 -HeartbeatSeconds 1
                @{{ status = [string]$data.status; logs = @($script:Logs) }} | ConvertTo-Json -Compress
                """,
                None,
            )
            payload = json.loads(record.read_text(encoding="utf-8"))
            progress_left = Path(payload["progress_state_file_path"]).exists()
            work_left = Path(payload["work_dir"]).exists()
        self.assertEqual(result["status"], "selected", result["logs"])
        logs = "\n".join(result["logs"])
        self.assertIn("runtime budget none", logs, "voice detection is never stopped for taking long")
        self.assertIn("stall watchdog 2s", logs)
        self.assertIn("Finding your voice: step", logs, "the helper's own words reach the log")
        self.assertFalse(progress_left, "the progress file is removed")
        self.assertFalse(work_left, "the decoded audio folder is removed")

    def test_voice_detection_that_stops_reporting_is_stopped_with_its_child(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            record = root / "payload.json"
            child = root / "child.pid"
            helper = self._fake(root, "helper", self.HELPER, RECORD=str(record), MODE="stuck", CHILD=str(child))
            result = self._run(
                self.PRELUDE
                + f"""
                $sw = [Diagnostics.Stopwatch]::StartNew()
                $data = Invoke-VoiceTrackDetection -PythonCommand '{helper}' -FFmpegExe 'ffmpeg' -FFprobeExe 'ffprobe' -VideoPath '{root / "session.mkv"}' -DurationSeconds 3600 -StallTimeoutSeconds 2 -HeartbeatSeconds 1
                $seconds = $sw.Elapsed.TotalSeconds
                Start-Sleep -Seconds 1
                $childId = [int](Get-Content -LiteralPath '{child}')
                $alive = $null -ne (Get-Process -Id $childId -ErrorAction SilentlyContinue)
                @{{ isNull = ($null -eq $data); seconds = $seconds; childAlive = $alive; reason = [string]$script:MMVoiceDetectionError; logs = @($script:Logs) }} | ConvertTo-Json -Compress
                """,
                None,
            )
            payload = json.loads(record.read_text(encoding="utf-8"))
            work_left = Path(payload["work_dir"]).exists()
        self.assertTrue(result["isNull"])
        self.assertLess(result["seconds"], 20)
        warnings = [line for line in result["logs"] if line.startswith("WARN ")]
        self.assertTrue(any("stopped reporting progress" in line for line in warnings), result["logs"])
        self.assertIn("stopped reporting progress", result["reason"], "the reason reaches the operator's message")
        self.assertIn("reading the audio, 00:20", result["reason"])
        self.assertFalse(result["childAlive"], "the helper's own child process is stopped with it")
        self.assertFalse(work_left, "a stopped helper leaves no decoded audio behind")

    def test_wav_extraction_that_keeps_moving_is_not_stopped_for_taking_long(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            record = root / "ffmpeg.json"
            output = root / "out" / "voice.wav"
            ffmpeg = self._fake(root, "ffmpeg", self.FFMPEG, RECORD=str(record), MODE="moving", STEPS=13)
            result = self._run(
                self.PRELUDE_SHARED
                + f"""
                $status = {self._extract(root, ffmpeg, output, '-StallTimeoutSeconds 1')}
                @{{ status = [string]$status; logs = @($script:Logs) }} | ConvertTo-Json -Compress
                """,
                None,
            )
            args = json.loads(record.read_text(encoding="utf-8"))["args"]
            scratch_left = list((root / "scratch").glob("*")) if (root / "scratch").exists() else []
            made, decode_left = output.is_file(), (root / "out" / ".voice-decode").exists()
        self.assertEqual(result["status"], "CREATED", result["logs"])
        self.assertEqual(args[args.index("-progress") + 1], "pipe:1")
        self.assertTrue(made)
        self.assertFalse(decode_left, "the decode folder is removed")
        self.assertEqual(scratch_left, [], "the progress file is removed")
        self.assertTrue(any("audio-extract" in line for line in result["logs"]), "made by the shared decoder")

    def test_wav_extraction_that_keeps_moving_has_no_limit_on_total_time(self) -> None:
        # The backend's clock runs ten minutes on each time it is read, so this
        # short extraction looks to it like one that takes hours. The fixed
        # limit 145 removed was 30 minutes.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ffmpeg = self._fake(root, "ffmpeg", self.FFMPEG, RECORD=str(root / "ffmpeg.json"), MODE="moving", STEPS=13)
            result = self._run(
                self.PRELUDE_SHARED
                + f"""
                $script:clockReads = 0
                function Get-Date {{ $script:clockReads += 1; return [datetime]::Now.AddMinutes(10 * $script:clockReads) }}
                $status = ''
                $message = ''
                try {{ $status = {self._extract(root, ffmpeg, root / "out" / "voice.wav", '-StallTimeoutSeconds 86400 -HeartbeatSeconds 1')} }} catch {{ $message = $_.Exception.Message }}
                @{{ status = [string]$status; message = $message; clockReads = $script:clockReads; logs = @($script:Logs) }} | ConvertTo-Json -Compress
                """,
                None,
            )
        self.assertEqual(result["message"], "")
        self.assertEqual(result["status"], "CREATED")
        self.assertGreater(result["clockReads"] * 10, 60, "the backend saw over an hour go by")
        self.assertIn("runtime budget none", "\n".join(result["logs"]))

    def test_wav_extraction_that_reports_but_does_not_move_is_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            record = root / "ffmpeg.json"
            ffmpeg = self._fake(root, "ffmpeg", self.FFMPEG, RECORD=str(record), MODE="stuck", STEPS=0)
            result = self._run(
                self.PRELUDE_SHARED
                + f"""
                $sw = [Diagnostics.Stopwatch]::StartNew()
                $message = ''
                try {{ $null = {self._extract(root, ffmpeg, root / "out" / "voice.wav", '-StallTimeoutSeconds 2')} }} catch {{ $message = $_.Exception.Message }}
                $seconds = $sw.Elapsed.TotalSeconds
                Start-Sleep -Seconds 1
                $fakeId = [int]((Get-Content -LiteralPath '{record}' -Raw | ConvertFrom-Json).pid)
                $alive = $null -ne (Get-Process -Id $fakeId -ErrorAction SilentlyContinue)
                @{{ seconds = $seconds; message = $message; alive = $alive }} | ConvertTo-Json -Compress
                """,
                None,
            )
            scratch_left = list((root / "scratch").glob("*")) if (root / "scratch").exists() else []
        self.assertLess(result["seconds"], 15, "a stuck extraction is stopped soon, not after 30 minutes")
        self.assertIn("stopped making progress", result["message"])
        self.assertIn("01:05 into the recording", result["message"])
        self.assertFalse(result["alive"], "FFmpeg itself is stopped, not only its launcher")
        self.assertEqual(scratch_left, [])

    def test_a_stopped_extraction_leaves_no_part_of_the_narration_audio(self) -> None:
        # 196: what FFmpeg wrote before it was stopped would otherwise stay in
        # the package's audio folder, and the package ZIP takes .wav files.
        outcomes = {}
        for case in ("stalled", "skipped"):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                record = root / "ffmpeg.json"
                control = root / "run-control.json"
                output = root / "audio" / "session.audio.wav"
                ffmpeg = self._fake(root, "ffmpeg", self.FFMPEG, RECORD=str(record), MODE="stuck", STEPS=0,
                                    CONTROL=str(control) if case == "skipped" else "", SKIP="D:\\Rec\\A.mkv")
                result = self._run(
                    self.PRELUDE_SHARED
                    + f"""
                    $script:MMRunControlPath = '{control}'
                    $message = ''
                    try {{ $null = {self._extract(root, ffmpeg, output, '-StallTimeoutSeconds 2')} }} catch {{ $message = $_.Exception.Message }}
                    $reason = Get-CodexEvidenceProblemReason -Entry ([pscustomobject]@{{ status = 'failed'; error_message = $message }})
                    @{{ message = $message; reason = $reason }} | ConvertTo-Json -Compress
                    """,
                    None,
                )
                written = json.loads(record.read_text(encoding="utf-8")).get("partial_bytes", 0)
                outcomes[case] = (result, written, output.exists() or (root / "audio" / ".session.audio-decode").exists())
        stalled, stalled_written, stalled_left = outcomes["stalled"]
        skipped, skipped_written, skipped_left = outcomes["skipped"]
        self.assertIn("stopped making progress", stalled["message"])
        self.assertTrue(skipped["message"].startswith("MM_SKIP_REQUESTED"), skipped)
        self.assertGreater(stalled_written, 0, "FFmpeg had written part of the WAV")
        self.assertGreater(skipped_written, 0, "FFmpeg had written part of the WAV")
        self.assertFalse(stalled_left, "a stalled extraction leaves no part of the WAV behind")
        self.assertFalse(skipped_left, "a skipped extraction leaves no part of the WAV behind")
        # What the operator reads names the stall and the drive, not a track to choose.
        self.assertIn("01:05", stalled["reason"])
        self.assertIn("the drive may have gone to sleep or been disconnected", stalled["reason"])
        self.assertNotIn("could not be read from the recording", stalled["reason"])

    def test_pause_is_not_a_stall_during_extraction(self) -> None:
        # The pause lands while FFmpeg is waiting on a slow drive, and lasts
        # longer than the stall limit. Only the time it was running counts.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            control = root / "run-control.json"
            control.write_text(json.dumps({"pause": False, "skip": []}), encoding="utf-8")
            ffmpeg = self._fake(root, "ffmpeg", self.PAUSING, CONTROL=str(control))

            def resume_later() -> None:
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    try:
                        if json.loads(control.read_text(encoding="utf-8")).get("pause"):
                            break
                    except (OSError, ValueError):
                        pass
                    time.sleep(0.1)
                time.sleep(10)
                control.write_text(json.dumps({"pause": False, "skip": []}), encoding="utf-8")

            resumer = threading.Thread(target=resume_later, daemon=True)
            resumer.start()
            result = self._run(
                self.PRELUDE_SHARED
                + f"""
                $script:MMRunControlPath = '{control}'
                $sw = [Diagnostics.Stopwatch]::StartNew()
                $status = ''
                $message = ''
                try {{ $status = {self._extract(root, ffmpeg, root / "out" / "voice.wav", '-StallTimeoutSeconds 8')} }} catch {{ $message = $_.Exception.Message }}
                @{{ seconds = $sw.Elapsed.TotalSeconds; status = [string]$status; message = $message; logs = @($script:Logs) }} | ConvertTo-Json -Compress
                """,
                None,
                timeout=120,
            )
            resumer.join(timeout=30)
        self.assertTrue(any("Paused by you" in line for line in result["logs"]), result["logs"])
        self.assertEqual(result["message"], "")
        self.assertEqual(result["status"], "CREATED")
        self.assertGreaterEqual(result["seconds"], 9.0, "the run must wait while paused")

    def test_the_package_mp3_has_no_time_limit_and_is_stopped_when_stuck(self) -> None:
        # 214: the MP3 had its own fixed 30-minute limit; it is on the shared rule now.
        outcomes = {}
        for case, mode, steps, stall in (("moving", "moving", 13, 86400), ("stuck", "stuck", 0, 2)):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                record = root / "ffmpeg.json"
                audio = root / "audio" / "audio.mp3"
                ffmpeg = self._fake(root, "ffmpeg", self.FFMPEG, RECORD=str(record), MODE=mode, STEPS=steps)
                clock = ("$script:clockReads = 0\n"
                         "function Get-Date { $script:clockReads += 1; return [datetime]::Now.AddMinutes(10 * $script:clockReads) }"
                         if case == "moving" else "")
                result = self._run(self.PRELUDE_SHARED + f"""
                    {clock}
                    $env:MEDIA_MANGLERS_SCRATCH_ROOT = '{root / "scratch"}'
                    $status = ''
                    $message = ''
                    try {{ $status = Export-AudioMp3 -PythonCommand '{sys.executable}' -FFmpegExe '{ffmpeg}' -InputVideo '{root / "x.mkv"}' -AudioFile '{audio}' -StallTimeoutSeconds {stall} }} catch {{ $message = $_.Exception.Message }}
                    @{{ status = [string]$status; message = $message; logs = @($script:Logs) }} | ConvertTo-Json -Compress
                    """, None)
                args = json.loads(record.read_text(encoding="utf-8"))["args"]
                outcomes[case] = (result, args, audio.exists(), (root / "audio" / ".audio-decode").exists())
        moving, moving_args, moving_made, _ = outcomes["moving"]
        stuck, _, stuck_left, stuck_decode_left = outcomes["stuck"]
        self.assertEqual(moving["status"], "CREATED", moving["logs"])
        self.assertTrue(moving_made)
        self.assertIn("libmp3lame", moving_args)
        self.assertIn("runtime budget none", "\n".join(moving["logs"]))
        self.assertIn("stopped making progress", stuck["message"])
        self.assertFalse(stuck_left or stuck_decode_left, "nothing of the MP3 is left under any name")

    def test_a_failed_extraction_says_why_and_leaves_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "out" / "voice.wav"
            ffmpeg = self._fake(root, "ffmpeg", self.FFMPEG, RECORD=str(root / "ffmpeg.json"), MODE="fails", STEPS=0)
            result = self._run(
                self.PRELUDE_SHARED
                + f"""
                $message = ''
                try {{ $null = {self._extract(root, ffmpeg, output)} }} catch {{ $message = $_.Exception.Message }}
                @{{ message = $message }} | ConvertTo-Json -Compress
                """,
                None,
            )
            left = output.exists() or (root / "out" / ".voice-decode").exists()
        self.assertIn("Transcript source WAV extraction failed", result["message"])
        self.assertIn("matches no streams", result["message"])
        self.assertFalse(left)

    def test_an_existing_wav_is_kept_unless_forced(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            record = root / "ffmpeg.json"
            output = root / "out" / "voice.wav"
            output.parent.mkdir(parents=True)
            output.write_bytes(b"RIFF-earlier")
            ffmpeg = self._fake(root, "ffmpeg", self.FFMPEG, RECORD=str(record), MODE="moving", STEPS=1)
            kept = self._run(self.PRELUDE_SHARED + f"""
                $status = {self._extract(root, ffmpeg, output)}
                @{{ status = [string]$status }} | ConvertTo-Json -Compress
                """, None)
            ran_before = record.exists()
            forced = self._run(self.PRELUDE_SHARED + f"""
                $status = {self._extract(root, ffmpeg, output, '-Force')}
                @{{ status = [string]$status }} | ConvertTo-Json -Compress
                """, None)
        self.assertEqual(kept["status"], "SKIPPED_EXISTING")
        self.assertFalse(ran_before, "FFmpeg is not run for a WAV that is already there")
        self.assertEqual(forced["status"], "CREATED")

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required")
    def test_real_ffmpeg_extraction_goes_through_the_shared_decoder(self) -> None:
        from media_manglers.core import voice_track

        ffmpeg = shutil.which("ffmpeg")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "two-tracks.mkv"
            subprocess.run([ffmpeg, "-hide_banner", "-v", "error", "-y",
                            "-f", "lavfi", "-i", "sine=frequency=300:duration=3",
                            "-f", "lavfi", "-i", "anoisesrc=duration=3",
                            "-map", "0:a", "-map", "1:a", "-c:a", "flac", str(source)], check=True)
            output = root / "out" / "voice.wav"
            result = self._run(
                self.PRELUDE_SHARED
                + f"""
                $env:MEDIA_MANGLERS_SCRATCH_ROOT = '{root / "scratch"}'
                $status = Export-TranscriptSourceWav -PythonCommand '{sys.executable}' -FFmpegExe '{ffmpeg}' -InputVideo '{source}' -OutputWav '{output}' -FfmpegMap '0:a:1' -StallTimeoutSeconds 180
                @{{ status = [string]$status; logs = @($script:Logs) }} | ConvertTo-Json -Compress
                """,
                None,
            )
            with wave.open(str(output), "rb") as audio:
                seconds = audio.getnframes() / audio.getframerate()
            shared = voice_track.extract_track(ffmpeg, source, 1, root / "shared" / "voice.wav")
            same = output.read_bytes() == shared.read_bytes()
        self.assertEqual(result["status"], "CREATED", result["logs"])
        self.assertAlmostEqual(seconds, 3.0, delta=0.1)
        self.assertTrue(same, "the backend's WAV is the shared decoder's WAV")
        self.assertTrue(any("audio-extract" in line for line in result["logs"]))


class BackendWiringTests(unittest.TestCase):
    def test_the_narration_wav_has_one_decoder(self) -> None:
        # 214: the backend has no FFmpeg decode of its own for the narration audio.
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn('"pcm_s16le", $', text)
        self.assertNotIn("function Get-MMFfmpegProgressSeconds", text)
        start = text.index("function Export-TranscriptSourceWav {")
        self.assertIn('-Command "audio-extract"', text[start:text.index("\nfunction ", start + 10)])
        # Every call passes the Python that runs the shared decoder (a call runs on with backticks).
        calls = re.findall(r"(?<!function )(Export-(?:TranscriptSourceWav|MMNarrationWav|AllTracksReviewMixWav) `\r?\n(?:[^\n]*`\r?\n)*[^\n]*\n)", text)
        self.assertGreaterEqual(len(calls), 6)
        for call in calls:
            self.assertIn("-PythonCommand", call, call)
    def test_backend_honours_skip_and_pause_everywhere_it_waits(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("[string]$RunControlPath", text)
        self.assertIn("[switch]$LowPriority", text)
        self.assertEqual(text.count("Invoke-MMRunControlCheck -Process $proc"), 2, "both tool-wait loops check skip/pause")
        for function in ("Invoke-NarrationClipTasks", "Invoke-NarrationReviewVideoTasks", "Invoke-CodexEvidenceAudioTasks"):
            start = text.index(f"function {function} {{")
            body = text[start : text.index("\nfunction ", start + 10)]
            self.assertIn("Test-MMSourceSkipRequested", body, function)
            self.assertIn("Wait-MMWhilePaused", body, function)
        self.assertIn('"operator_skipped" { "skipped" }', text)
        self.assertIn(".voice.json", text, "voice-track picks are saved for a continued run")


if __name__ == "__main__":
    unittest.main()
