"""214: Pause and Skip on Queue / Progress work for every run, as they do for Find my bug reports.

Only Find my bug reports made the control file the backend reads, so Pause and Skip stayed greyed
out for Package any video for AI (Full Review and Transcript Only) and Review Media Inbox. Every
run the Workbench starts now has one, and the backend honours it in each feature's own loop.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from media_manglers_workbench.app import WorkbenchWindow  # noqa: E402
from media_manglers_workbench.metadata import WORKFLOW_FULL_REVIEW, WORKFLOW_TRANSCRIPT_ONLY  # noqa: E402
from media_manglers_workbench.runner import RunnerResult  # noqa: E402
from media_manglers_workbench.settings import SETTINGS_SCHEMA_VERSION  # noqa: E402
from tests.script_functions import function_text  # noqa: E402
from tests.test_workbench_bug_reports import _resources  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "Video Mangler.ps1"


class HeldBackend:
    """Stands in for Video Mangler.ps1 and keeps running until the test lets it finish."""

    instances: list["HeldBackend"] = []

    def __init__(self) -> None:
        self.argv: list[str] = []
        self.started = threading.Event()
        self.release = threading.Event()
        HeldBackend.instances.append(self)

    def cancel(self) -> None:
        self.release.set()

    def run(self, command, on_log=None, *, cwd=None) -> RunnerResult:
        self.argv = list(command.argv)
        self.started.set()
        self.release.wait(30)
        return RunnerResult(status="succeeded", exit_code=0, stdout_lines=[], error="")


class EveryRunHasQueueControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window: WorkbenchWindow | None = None
        HeldBackend.instances = []
        self.recording = self.root / "recordings" / "a.mkv"
        self.recording.parent.mkdir()
        self.recording.write_bytes(b"not really video")

    def tearDown(self) -> None:
        for backend in HeldBackend.instances:
            backend.release.set()
        if self.window:
            self._wait(lambda: self.window.runner_thread is None)
            self.window._closing_after_smoke = True
            self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def _wait(self, condition, seconds: float = 10.0) -> bool:
        for _ in range(int(seconds * 20)):
            if condition():
                return True
            self.app.processEvents()
            QTest.qWait(50)
        return condition()

    def _start(self, workflow: str) -> tuple[WorkbenchWindow, HeldBackend, Path]:
        settings_path = self.root / "settings.json"
        settings_path.write_text(json.dumps({"schemaVersion": SETTINGS_SCHEMA_VERSION, "settings": {
            "log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
            "output_folder": str(self.root / "out")}}), encoding="utf-8")
        self.window = WorkbenchWindow(settings_path=settings_path, profiles_dir=self.root / "profiles",
                                      runner_factory=HeldBackend, resources=_resources())
        self.window.show()
        self.app.processEvents()
        self.window.start_workflow_from_home(workflow)
        self.window.run_settings["input_path"] = str(self.recording)
        self.window.run_settings["output_folder"] = str(self.root / "out")
        # A message box would wait for a click no test makes; say what it said instead.
        refused = mock.Mock(side_effect=lambda _parent, title, text, *rest: self.fail(f"{title}: {text}"))
        with mock.patch("media_manglers_workbench.app.QMessageBox.warning", refused), \
                mock.patch("media_manglers_workbench.app.QMessageBox.information", refused):
            self.window.start_job()
        self.assertTrue(self._wait(lambda: bool(HeldBackend.instances) and HeldBackend.instances[-1].started.is_set()),
                        "the run did not start")
        backend = HeldBackend.instances[-1]
        control = Path(backend.argv[backend.argv.index("-RunControlPath") + 1])
        return self.window, backend, control

    def test_full_review_and_transcript_only_runs_can_be_paused_and_skipped(self) -> None:
        for workflow in (WORKFLOW_FULL_REVIEW, WORKFLOW_TRANSCRIPT_ONLY):
            with self.subTest(workflow=workflow):
                window, backend, control = self._start(workflow)
                self.assertTrue(control.is_file())
                self.assertTrue(window.pause_button.isEnabled())
                self.assertTrue(window.skip_button.isEnabled())

                QTest.mouseClick(window.pause_button, Qt.MouseButton.LeftButton)
                self.assertTrue(json.loads(control.read_text(encoding="utf-8"))["pause"])
                self.assertEqual(window.pause_button.text(), "Resume")
                QTest.mouseClick(window.pause_button, Qt.MouseButton.LeftButton)
                self.assertFalse(json.loads(control.read_text(encoding="utf-8"))["pause"])

                window.skip_run_sources([str(self.recording.resolve())])
                self.assertEqual(json.loads(control.read_text(encoding="utf-8"))["skip"], [str(self.recording.resolve())])

                backend.release.set()
                self.assertTrue(self._wait(lambda: window.runner_thread is None))
                self.assertFalse(window.pause_button.isEnabled())
                self.assertFalse(control.exists(), "the run's control file is removed when it ends")
                window._closing_after_smoke = True
                window.close()
                self.window = None


class BackendSkipTests(unittest.TestCase):
    """Transcript Only's real loop, with the tools it calls stood in for."""

    FUNCTIONS = (
        "Invoke-TranscriptOnlyBatch", "Get-MMRunControl", "Test-MMSourceSkipRequested", "Test-MMPauseRequested",
        "Test-MMSkipException", "Wait-MMWhilePaused", "Test-MMStartingAppAlive", "Invoke-MMRunControlCheck", "Stop-MMProcessTree",
        # 214: the shared track choice, as Package any video for AI's.
        "Get-MMFullReviewAutoTrackNumber", "Resolve-TranscriptAudioSelection", "Resolve-AudioTrackOrdinal",
        "Export-AllTracksReviewMixWav",
    )

    def _run(self, skip: list[str], *, skip_during_whisper: str = "", tracks: int = 1, narration: int | None = None,
             mode: str = "Auto", track_number: int = 0) -> dict:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "in"
            source.mkdir()
            for name in ("A.mkv", "B.mkv"):
                (source / name).write_bytes(b"x")
            control = root / "run-control.json"
            control.write_text(json.dumps({"pause": False, "skip": [str(source / name) for name in skip]}), encoding="utf-8")
            names = ",".join(f"'{name}'" for name in self.FUNCTIONS)
            harness = root / "harness.ps1"
            harness.write_text(textwrap.dedent(
                f"""
                $ErrorActionPreference = 'Stop'
                $tokens = $null; $parseErrors = $null
                $ast = [System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', [ref]$tokens, [ref]$parseErrors)
                $wanted = @({names})
                foreach ($node in $ast.FindAll({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $wanted -contains $n.Name }}, $true)) {{
                    Invoke-Expression $node.Extent.Text
                }}
                function Write-Log {{ param($Message, $Level) $script:logged += ,@([string]$Level, [string]$Message) }}
                function Write-Phase {{ }}
                function Write-MMProgressV1 {{ }}
                function Normalize-UserPath {{ param($Path) $Path }}
                function Ensure-Directory {{ param($Path) $null = New-Item -ItemType Directory -Force -Path $Path }}
                function Get-VideoFilesFromPath {{ param($Path, [switch]$Recurse) @(Get-ChildItem -LiteralPath $Path -Filter *.mkv | Sort-Object Name) }}
                function Select-MMDistinctVideos {{ param($Videos) $Videos }}
                function Get-TranscriptOnlySourceId {{ param($VideoPath) [IO.Path]::GetFileNameWithoutExtension($VideoPath) }}
                function Get-TranscriptOnlySourceIdentifier {{ param($VideoPath, $SourceRoot) [IO.Path]::GetFileName($VideoPath) }}
                function Get-VideoDurationSeconds {{ 0 }}
                function Get-MMSpellingWords {{ @() }}
                function Get-EvidenceTranscriptionInitialPrompt {{ '' }}
                function Export-AudioMp3 {{ }}
                # 214: the narration WAV comes from the shared decoder, stood in for here.
                function Get-MMScratchPath {{ param($Prefix) Join-Path '{root / "scratch"}' ($Prefix + [guid]::NewGuid().ToString()) }}
                function Remove-MMScratchPath {{ param($Path) Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue }}
                function Export-TranscriptSourceWav {{
                    param($PythonCommand, $FFmpegExe, $InputVideo, $OutputWav, $FfmpegMap, $HeartbeatSeconds, $DurationSeconds,
                          [int[]]$MixOrdinals = @(), $StepName, $AudioFormat, [switch]$Force)
                    $null = Invoke-MMRunControlCheck -StepName 'the narration audio'
                    $null = New-Item -ItemType Directory -Force -Path (Split-Path -Path $OutputWav -Parent)
                    Set-Content -LiteralPath $OutputWav -Value 'RIFF'
                    $what = if (@($MixOrdinals).Count -gt 0) {{ 'mix ' + (@($MixOrdinals) -join ',') }} else {{ $FfmpegMap }}
                    $script:decoded += ,('{{0}}|{{1}}' -f [IO.Path]::GetFileName($InputVideo), $what)
                    'CREATED'
                }}
                function Get-VideoAudioStreams {{
                    param($FFprobeExe, $VideoPath)
                    @(for ($i = 0; $i -lt {tracks}; $i++) {{ [pscustomobject]@{{ ordinal = $i; ffmpeg_map = '0:a:' + $i; title = '' }} }})
                }}
                # Voice detection, stood in for: the narration track it finds, or none.
                function Resolve-MMFullReviewAutoTrack {{
                    {'return $null' if narration is None else '[pscustomobject]@{ Ordinal = ' + str(narration) + '; IsNarration = $true; Detection = [pscustomobject]@{ status = "selected"; selected_ordinal = ' + str(narration) + ' } }'}
                }}
                function Invoke-MMNarrationCrossCheck {{ param($PythonCommand, $FFmpegExe, $VideoPath, $TranscriptJsonPath, $Detection, $PreferGpu, $HeartbeatSeconds) $script:checked += ,[IO.Path]::GetFileName($TranscriptJsonPath) }}
                function Invoke-PythonWhisperTranscript {{
                    param($TranscriptFolder, $JsonName, $SrtName, $TextName, $AudioPath, $NarrationSpeechMode)
                    $script:heard += ,[IO.Path]::GetFileName($AudioPath)
                    $script:modes += ,$NarrationSpeechMode
                    if ('{skip_during_whisper}' -and $script:MMCurrentSourcePath -like '*{skip_during_whisper}') {{
                        Set-Content -LiteralPath '{control}' -Value ('{{"pause": false, "skip": ["' + $script:MMCurrentSourcePath.Replace('\\', '\\\\') + '"]}}')
                        $script:MMRunControlCache = $null
                    }}
                    # As every tool the backend waits on does, look at Pause and Skip while it runs.
                    $null = Invoke-MMRunControlCheck -StepName 'Whisper'
                    foreach ($name in @($JsonName, $SrtName, $TextName)) {{ Set-Content -LiteralPath (Join-Path $TranscriptFolder $name) -Value 'x' }}
                }}
                function Invoke-TranscriptOnlyIndexHelper {{
                    param($PythonCommand, $OutputRoot, $ManifestEntries, $SearchTerms, $HeartbeatSeconds)
                    $null = Invoke-MMRunControlCheck -StepName 'the index'
                    $script:entries = @($ManifestEntries)
                    [pscustomobject]@{{ manifest_json = ''; combined_markdown = ''; search_results_count = 0 }}
                }}
                $script:logged = @()
                $script:decoded = @()
                $script:heard = @()
                $script:modes = @()
                $script:checked = @()
                $script:MMRunControlPath = '{control}'
                $script:MMRunControlCache = $null
                $script:MMRunControlReadAt = [datetime]::MinValue
                $script:MMCurrentSourcePath = ''
                $script:MMSkipRequested = $false
                $script:MMSkipMessagePrefix = 'MM_SKIP_REQUESTED'
                $null = Invoke-TranscriptOnlyBatch -InputPath '{source}' -OutputFolder '{root / "out"}' -PythonCommand 'python' -FFmpegExe 'ffmpeg' -FFprobeExe 'ffprobe' -ModelName 'base.en' -LanguageCode '' -CanUseWhisperGpu $false -TranscriptAudioMode '{mode}' -TranscriptAudioTrackOrdinal {track_number}
                [Console]::Out.WriteLine((@{{
                    states = @($script:entries | ForEach-Object {{ '{{0}}={{1}}' -f $_.source_filename, $_.status }})
                    warnings = @($script:logged | Where-Object {{ $_[0] -in @('WARN', 'ERROR') }} | ForEach-Object {{ $_[1] }})
                    decoded = @($script:decoded)
                    heard = @($script:heard)
                    modes = @($script:modes)
                    checked = @($script:checked)
                    transcripts = @(Get-ChildItem -LiteralPath '{root / "out" / "transcript-only" / "transcripts"}' | ForEach-Object {{ [string]$_.Name }} | Sort-Object)
                }} | ConvertTo-Json -Compress))
                """
            ).strip(), encoding="utf-8")
            run = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                                 capture_output=True, text=True, timeout=120)
            self.assertEqual(run.returncode, 0, run.stdout[-3000:] + run.stderr[-3000:])
            return json.loads(run.stdout.strip().splitlines()[-1])

    def test_a_recording_skipped_before_it_starts_is_skipped_not_failed(self) -> None:
        result = self._run(["A.mkv"])
        self.assertEqual(result["states"], ["A.mkv=skipped", "B.mkv=completed"])
        self.assertEqual(result["warnings"], [])
        # 214: Whisper hears the shared decoder's WAV of Track 1, not the recording itself.
        self.assertEqual(result["decoded"], ["B.mkv|0:a:0"])
        self.assertEqual(result["heard"], ["narration.wav"])
        self.assertEqual(result["transcripts"], ["B.transcript.json", "B.transcript.srt", "B.transcript.txt"])

    def test_skipping_the_last_recording_while_whisper_runs_leaves_the_run_whole(self) -> None:
        result = self._run([], skip_during_whisper="B.mkv")
        self.assertEqual(result["states"], ["A.mkv=completed", "B.mkv=skipped"])
        self.assertEqual(result["warnings"], [])


class TranscriptOnlyTrackChoiceTests(BackendSkipTests):
    """214: Transcript Only chooses its track exactly as Package any video for AI on Auto."""

    test_a_recording_skipped_before_it_starts_is_skipped_not_failed = None
    test_skipping_the_last_recording_while_whisper_runs_leaves_the_run_whole = None

    def test_the_narration_track_is_used_with_the_strict_filter(self) -> None:
        result = self._run([], tracks=3, narration=1)
        self.assertEqual(result["decoded"], ["A.mkv|0:a:1", "B.mkv|0:a:1"])
        self.assertEqual(result["modes"], ["Sparse", "Sparse"])
        self.assertEqual(result["checked"], ["A.transcript.json", "B.transcript.json"])
        self.assertEqual(result["states"], ["A.mkv=completed", "B.mkv=completed"])

    def test_with_no_narration_track_the_full_mix_is_used_with_the_plain_filter(self) -> None:
        result = self._run([], tracks=3, narration=None)
        self.assertEqual(result["decoded"], ["A.mkv|mix 0,1,2", "B.mkv|mix 0,1,2"])
        self.assertEqual(result["modes"], ["Auto", "Auto"])
        self.assertEqual(result["checked"], [])
        self.assertEqual(result["states"], ["A.mkv=completed", "B.mkv=completed"], "never 'no narration found'")

    def test_a_one_track_recording_is_its_full_mix(self) -> None:
        result = self._run([], tracks=1, narration=None)
        self.assertEqual(result["decoded"], ["A.mkv|0:a:0", "B.mkv|0:a:0"])
        self.assertEqual(result["modes"], ["Auto", "Auto"])

    def test_a_chosen_track_overrides_the_detection(self) -> None:
        result = self._run([], tracks=3, narration=1, mode="Track", track_number=3)
        self.assertEqual(result["decoded"], ["A.mkv|0:a:2", "B.mkv|0:a:2"])
        self.assertEqual(result["modes"], ["Auto", "Auto"])


class BackendWiringTests(unittest.TestCase):
    def test_full_review_honours_skip_and_a_run_you_skipped_entirely_has_not_failed(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        loop = text[text.index("foreach ($video in $videos) {\n    $videoQueueOrdinal += 1"):]
        loop = loop[: loop.index("\n}\n")]
        self.assertIn("$script:MMCurrentSourcePath = $video.FullName", loop)
        self.assertIn('$null = Invoke-MMRunControlCheck -StepName "the next recording"', loop)
        # The skip is caught first, so a skipped recording never reaches the failures.
        self.assertIn("    catch {\n        if ((Test-MMSkipException $_) -or $script:MMSkipRequested", loop)
        self.assertIn("($processedItems.Count -eq 0 -and $skippedByYouItems.Count -eq 0)", text)

    def test_the_evidence_steps_give_back_the_recording_they_ran_inside(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        for function in ("Invoke-CodexEvidenceFrameTasks", "Invoke-CodexEvidenceAudioTasks", "Invoke-NarrationClipTasks",
                         "Invoke-NarrationReviewVideoTasks", "Invoke-CodexEvidencePackageBatch"):
            body = function_text(text, function)
            self.assertNotIn('$script:MMCurrentSourcePath = ""', body, function)
            self.assertIn("$script:MMCurrentSourcePath = $mmOuterSourcePath", body, function)

    def test_a_pause_is_information_not_a_warning(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('Write-Log ("Paused by you{0}. The run continues when you press Resume." -f $whereText) "INFO"', text)

    def test_the_inbox_is_handed_the_control_file(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        start = text.index("$reviewProcessPayload = @{")
        self.assertIn("run_control_path = [string]$script:MMRunControlPath", text[start: text.index("\n        }", start)])


if __name__ == "__main__":
    unittest.main()
