"""201: the small review copy is made while Whisper works, and the package is as before.

The copy reads the whole recording through the graphics card's video decoder, which Whisper does
not use, so it is started when a recording's transcription starts and collected by the narration
visuals. These run the real backend functions of "Video Mangler.ps1"; only Whisper is stood in for.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

from tests.test_skipped_recording_privacy import _run_batch
from tests.test_voice_track import _three_track_recording

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "Video Mangler.ps1"
FFMPEG = shutil.which("ffmpeg")
HAS_NVIDIA = shutil.which("nvidia-smi") is not None


def _powershell(body: str, *, functions: tuple[str, ...] = (), timeout: int = 180) -> dict:
    """Run the backend's own functions (all of them unless named) and return the last JSON line."""

    names = ",".join(f"'{name}'" for name in functions)
    pick = f"$wanted -contains $n.Name" if functions else "$true"
    source = textwrap.dedent(
        f"""
        $ErrorActionPreference = 'Stop'
        $tokens = $null; $parseErrors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', [ref]$tokens, [ref]$parseErrors)
        $wanted = @({names})
        foreach ($node in $ast.FindAll({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Parent -is [System.Management.Automation.Language.NamedBlockAst] -and ({pick}) }}, $false)) {{
            Invoke-Expression $node.Extent.Text
        }}
        function Write-MMProgressV1 {{ }}
        # 214: screenshots are made by the Python helper.
        $PythonExe = '{sys.executable}'
        $script:MediaManglersPythonCliInfo = [pscustomobject]@{{ Enabled = $true; Root = '{REPO_ROOT / "src"}'; EntryPoint = '' }}
        $script:CurrentLogFile = $null
        $script:MMProgressPhase = 'Test'
        $script:MMRunControlPath = ''
        $script:MMCurrentSourcePath = ''
        $script:MMSkipRequested = $false
        $script:MMSkipMessagePrefix = 'MM_SKIP_REQUESTED'
        {body}
        """
    ).strip()
    with tempfile.TemporaryDirectory() as temp:
        harness = Path(temp) / "harness.ps1"
        harness.write_text(source, encoding="utf-8")
        result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                                capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise AssertionError(result.stderr[-4000:])
    return json.loads(result.stdout.strip().splitlines()[-1])


def _h264_recording(path: Path) -> Path:
    """Eight seconds of H.264 with one audio track: something the graphics card can decode."""

    subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:duration=8",
                    "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:duration=8",
                    "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    str(path)], check=True)
    return path


@unittest.skipUnless(FFMPEG and shutil.which("ffprobe"), "FFmpeg is required")
class ReviewCopyAlongsideTheTranscriptionTests(unittest.TestCase):
    def test_the_earlier_two_ways_of_making_the_copy_are_unchanged(self) -> None:
        result = _powershell(
            """
            $sets = @(Get-MMReviewVideoArgumentSets -SourcePath 'D:\\R\\a.mkv' -AudioMap '0:a:1?' -Width 1920 -OutputPath 'C:\\P\\v.partial.mp4')
            [Console]::Out.WriteLine((@{ count = $sets.Count; sets = @($sets | ForEach-Object { ,@($_) | ForEach-Object { $_ -join ' ' } }) } | ConvertTo-Json -Compress))
            """,
            functions=("Get-MMReviewVideoArgumentSets",),
        )
        self.assertEqual(result["count"], 3)
        first, second, third = result["sets"]
        self.assertIn("-hwaccel_output_format cuda", first)
        self.assertIn("scale_cuda=1920:-2", first)
        # Frames nothing else is built from are not decoded: 2.4 times faster on a real recording.
        self.assertIn("-skip_frame:v noref -i D:\\R\\a.mkv", first)
        self.assertEqual(second, "-y -hwaccel cuda -i D:\\R\\a.mkv -map 0:v:0 -map 0:a:1? -vf fps=10,scale=1920:-2 "
                                 "-c:v h264_nvenc -preset p4 -b:v 320k -maxrate 480k -bufsize 640k -pix_fmt yuv420p "
                                 "-c:a aac -b:a 48k -ac 1 -movflags +faststart C:\\P\\v.partial.mp4")
        self.assertEqual(third, "-y -i D:\\R\\a.mkv -map 0:v:0 -map 0:a:1? -vf fps=10,scale=1920:-2 "
                                "-c:v libx264 -preset veryfast -b:v 320k -maxrate 480k -bufsize 640k -pix_fmt yuv420p "
                                "-c:a aac -b:a 48k -ac 1 -movflags +faststart C:\\P\\v.partial.mp4")

    def test_a_copy_started_alongside_is_collected_by_the_narration_visuals(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            recording = _h264_recording(root / "a-session.mkv")
            package = root / "package"
            result = _powershell(
                f"""
                $entry = Start-MMBackgroundReviewVideo -FFmpegExe '{FFMPEG}' -SourcePath '{recording}' -SourceId 'a-1' -AudioOrdinal 0 -OutputRoot '{package}'
                $started = $null -ne $entry
                $path = Get-MMNarrationReviewVideoPath -OutputRoot '{package}' -SourceId 'a-1'
                $task = [pscustomobject]@{{ source_id = 'a-1'; source_path = '{recording}'; duration_seconds = 8; audio_ordinal = 0; width = 1920; path = $path }}
                $results = @(Invoke-NarrationReviewVideoTasks -FFmpegExe '{FFMPEG}' -VideoTasks @($task) -HeartbeatSeconds 0)
                Remove-MMUnclaimedBackgroundReviewVideos -All
                $entryStatus = if ($entry) {{ $entry.Status }} else {{ '' }}
                [Console]::Out.WriteLine((@{{ started = $started; status = $results[0].status; entry = $entryStatus; exists = (Test-Path -LiteralPath $path) }} | ConvertTo-Json -Compress))
                """,
            )
            self.assertTrue(result["started"])
            self.assertEqual(result["status"], "created")
            self.assertTrue(result["exists"])
            if HAS_NVIDIA:
                # Made on the graphics card while "Whisper" ran, not made again afterwards.
                self.assertEqual(result["entry"], "created")
            self.assertEqual(sorted(p.name for p in package.rglob("*.mp4")), ["review_video_a-1.mp4"])

    def test_a_copy_nobody_wants_is_deleted_and_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            recording = _h264_recording(root / "a-session.mkv")
            package = root / "package"
            result = _powershell(
                f"""
                $entry = Start-MMBackgroundReviewVideo -FFmpegExe '{FFMPEG}' -SourcePath '{recording}' -SourceId 'a-1' -AudioOrdinal 0 -OutputRoot '{package}'
                Start-Sleep -Milliseconds 300
                Remove-MMUnclaimedBackgroundReviewVideos -KeepPaths @()
                [Console]::Out.WriteLine((@{{ exited = $entry.Process.HasExited; left = $script:MMBackgroundReviewVideos.Count }} | ConvertTo-Json -Compress))
                """,
            )
            self.assertTrue(result["exited"])
            self.assertEqual(result["left"], 0)
            self.assertEqual(list(package.rglob("*.mp4")), [])

    def test_pause_freezes_a_copy_being_made_alongside(self) -> None:
        # A busy stand-in for FFmpeg; while the run is paused it must use no processor time.
        with tempfile.TemporaryDirectory() as temp:
            control = Path(temp) / "run-control.json"
            control.write_text(json.dumps({"pause": True, "skip": []}), encoding="utf-8")
            body = f"""
                $script:MMRunControlPath = '{control}'
                $script:MMRunControlCache = $null
                $script:MMRunControlReadAt = [datetime]::MinValue
                $busy = Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-Command', 'while ($true) {{ }}') -PassThru -WindowStyle Hidden
                $script:MMBackgroundReviewVideos = [ordered]@{{ 'x' = [pscustomobject]@{{ Status = 'running'; Process = $busy }} }}
                # The first suspend compiles a small helper; do that before measuring.
                Set-MMProcessTreeSuspended -Process $busy -Suspended $false
                Start-Sleep -Milliseconds 500
                $busy.Refresh()
                $before = $busy.TotalProcessorTime.TotalSeconds
                [System.IO.File]::WriteAllText('{control}.waiting', 'x')
                $paused = Wait-MMWhilePaused -Where 'test'
                $busy.Refresh()
                $during = $busy.TotalProcessorTime.TotalSeconds - $before
                Stop-Process -Id $busy.Id -Force
                [Console]::Out.WriteLine((@{{ paused = $paused; during = $during }} | ConvertTo-Json -Compress))
            """
            source_body = textwrap.dedent(body)
            process = None
            try:
                import threading

                def resume() -> None:
                    # Three seconds after the pause has begun, however long the start took.
                    waiting = control.with_name(control.name + ".waiting")
                    deadline = time.monotonic() + 120
                    while not waiting.exists() and time.monotonic() < deadline:
                        time.sleep(0.1)
                    time.sleep(3)
                    control.write_text(json.dumps({"pause": False, "skip": []}), encoding="utf-8")

                threading.Thread(target=resume, daemon=True).start()
                result = _powershell(source_body)
            finally:
                del process
        self.assertGreater(result["paused"], 2.0)
        self.assertLess(result["during"], 0.5, "the copy kept working while the run was paused")

    def test_a_whole_run_leaves_one_finished_copy_per_narrated_recording_and_nothing_half_written(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "recordings"
            folder.mkdir()
            first = _three_track_recording(folder / "a-session.mkv")
            shutil.copy(first, folder / "b-session.mkv")
            out = root / "out"
            failure = _run_batch(root / "run", [first, folder / "b-session.mkv"], out)
            self.assertEqual(failure, "")
            package = out / "codex-evidence-package"
            copies = sorted(path.name for path in package.rglob("review_video_*.mp4"))
            self.assertEqual(len(copies), 2, copies)
            self.assertEqual(list(package.rglob("*.partial.mp4")), [])
            log = (package / "codex_evidence_run.log").read_text(encoding="utf-8-sig")
            self.assertEqual(log.count("started alongside the transcription"), 2)
            # Started before the narration visuals were planned, not after.
            self.assertLess(log.index("started alongside the transcription"), log.index("Narration visuals plan"))
            index = json.loads((package / "NARRATION_EVIDENCE.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(index["review_video_count"], 2)


@unittest.skipUnless(FFMPEG and shutil.which("ffprobe"), "FFmpeg is required")
class ScreenshotBatchesTests(unittest.TestCase):
    def test_splitting_at_a_gap_gives_the_very_same_screenshots(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            recording = root / "a-session.mkv"
            subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi",
                            "-i", "testsrc2=size=320x180:rate=60:duration=40", "-c:v", "libx264", "-g", "120",
                            "-pix_fmt", "yuv420p", str(recording)], check=True)
            times = [1.25, 2.4, 3.95, 21.1, 22.7, 35.33]
            hashes = {}
            for label, gap in (("one batch", 1000.0), ("split", 10.0)):
                folder = root / label
                tasks = ",".join(
                    "[pscustomobject]@{ evidence_id = 'n'; source_id = 'a'; source_path = '%s'; timestamp_seconds = %s; "
                    "relative_path = 'f%d.jpg'; path = '%s'; panel_crop_mode = 'off'; panels = @() }"
                    % (recording, t, i, folder / f"f{i}.jpg") for i, t in enumerate(times))
                result = _powershell(
                    f"""
                    $results = @(Invoke-CodexEvidenceFrameTasks -FFmpegExe '{FFMPEG}' -FrameTasks @({tasks}) -HeartbeatSeconds 0 -MaxGapSeconds {gap})
                    [Console]::Out.WriteLine((@{{ statuses = @($results | ForEach-Object {{ $_.status }}); batches = @($results | ForEach-Object {{ $_.extraction_batch_size }}) }} | ConvertTo-Json -Compress))
                    """,
                )
                self.assertEqual(result["statuses"], ["created"] * len(times))
                hashes[label] = [(folder / f"f{i}.jpg").read_bytes() for i in range(len(times))]
                if label == "split":
                    self.assertEqual(result["batches"], [3, 3, 3, 2, 2, 1])
            self.assertEqual(hashes["one batch"], hashes["split"])


if __name__ == "__main__":
    unittest.main()
