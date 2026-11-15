"""214: Whisper loads in one place, and its main settings reach every feature that transcribes.

The backend kept a backup Whisper script for when the shared helper failed, and the voice probes
loaded Whisper with their own code. Both now go through media_manglers.providers.whisper_local.
Transcript Only gains the main language and speech-mode settings; the Inbox gains the GPU setting.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core import voice_track, whisper_models  # noqa: E402
from media_manglers.providers import whisper_local  # noqa: E402
from media_manglers_workbench.command_builder import build_workflow_command  # noqa: E402
from media_manglers_workbench.metadata import WORKFLOW_TRANSCRIPT_ONLY  # noqa: E402
from media_manglers_workbench.settings import build_default_settings  # noqa: E402
from tests.whisper_test_models import whisper_gets_file_names  # noqa: E402

# H2 of the Wave I-A review: these stand-ins are given a file name; see whisper_gets_file_names.
_FILE_NAMES = whisper_gets_file_names()


def setUpModule() -> None:  # noqa: N802 - unittest's name
    _FILE_NAMES.start()


def tearDownModule() -> None:  # noqa: N802 - unittest's name
    _FILE_NAMES.stop()

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "Video Mangler.ps1"
AUDIO_SCRIPT = REPO_ROOT / "Audio Mangler.ps1"


def _outside_functions(tree: ast.AST):
    """Every node that runs when its module is imported: all but the bodies of functions and lambdas."""

    for child in ast.iter_child_nodes(tree):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield child
        yield from _outside_functions(child)


def _values(argv: list[str], flag: str) -> list[str]:
    return [argv[index + 1] for index, token in enumerate(argv) if token == flag]


def _function_text(name: str, script: Path = SCRIPT) -> str:
    source = textwrap.dedent(
        f"""
        $tokens = $null; $parseErrors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile('{script}', [ref]$tokens, [ref]$parseErrors)
        $node = $ast.Find({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq '{name}' }}, $true)
        [Console]::Out.Write($node.Extent.Text)
        """
    ).strip()
    run = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", source],
                         capture_output=True, text=True, timeout=120)
    return run.stdout


class MainSettingsReachEveryFeatureTests(unittest.TestCase):
    def test_transcript_only_sends_the_main_language_and_its_track_choice(self) -> None:
        settings = {**build_default_settings(), "input_path": "C:\\in\\a.mkv", "output_folder": "C:\\out",
                    "language": "de", "narration_speech_mode": "Sparse", "transcript_audio_mode": "Track",
                    "transcript_audio_track_ordinal": 3, "evidence_track_roles": "2=narration"}
        argv = build_workflow_command(settings, workflow=WORKFLOW_TRANSCRIPT_ONLY).argv
        self.assertEqual(_values(argv, "-Language"), ["de"])
        self.assertEqual(_values(argv, "-TranscriptAudioMode"), ["Track"])
        self.assertEqual(_values(argv, "-TranscriptAudioTrackOrdinal"), ["3"])
        self.assertEqual(_values(argv, "-EvidenceTrackRoles"), ["2=narration"])
        # The speech mode follows the track found, as in Package any video for AI.
        self.assertEqual(_values(argv, "-NarrationSpeechMode"), [])

    def test_transcript_only_speech_mode_follows_the_track_found(self) -> None:
        text = _function_text("Invoke-TranscriptOnlyBatch")
        self.assertEqual(text.count("Invoke-PythonWhisperTranscript `"), 1)
        self.assertIn('-NarrationSpeechMode $(if ($null -ne $narrationDetection) { "Sparse" } else { "Auto" })', text)

    def test_the_inbox_receives_the_main_gpu_setting(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        start = text.index("$reviewProcessPayload = @{")
        payload = text[start:text.index("\n        }", start)]
        self.assertIn('prefer_gpu = ($WhisperDevice -ne "CPU")', payload)


class OneLoaderTests(unittest.TestCase):
    def test_the_voice_probes_load_whisper_through_the_shared_helper(self) -> None:
        model = mock.Mock()
        model.transcribe.return_value = {"segments": [{"text": "hello"}]}
        with mock.patch.object(whisper_local, "load_whisper_model", return_value=model) as load, \
                mock.patch.object(whisper_local, "pick_whisper_device", return_value="cpu") as pick:
            transcribe = voice_track.whisper_transcriber("base.en", False, "en")
            segments = transcribe(Path("probe.wav"))
        pick.assert_called_once_with(False)
        load.assert_called_once_with("base.en", "cpu")
        self.assertEqual(segments, [{"text": "hello"}])

    def test_no_module_but_the_shared_helper_loads_whisper(self) -> None:
        # 226: a scan of every Python module: none outside providers/whisper_local.py calls
        # whisper.load_model or imports whisper at module level. An import inside a function, or in the
        # text of a probe script another Python runs (dependencies.py's version check), is not a load.
        source = REPO_ROOT / "src"
        helper = source / "media_manglers" / "providers" / "whisper_local.py"
        found: list[str] = []
        scanned = 0
        for path in sorted(source.rglob("*.py")):
            if path == helper or "__pycache__" in path.parts:
                continue
            scanned += 1
            tree = ast.parse(path.read_text(encoding="utf-8"))
            relative = path.relative_to(REPO_ROOT).as_posix()
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "load_model"
                        and isinstance(node.func.value, ast.Name) and node.func.value.id == "whisper"):
                    found.append(f"{relative}:{node.lineno} calls whisper.load_model")
            for node in _outside_functions(tree):
                names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                         else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                if any(name == "whisper" or name.startswith("whisper.") for name in names):
                    found.append(f"{relative}:{node.lineno} imports whisper at module level")
        self.assertGreater(scanned, 50, "the whole source tree was scanned")
        self.assertEqual(found, [])
        # The same scan finds the shared helper's own load, so it would find one anywhere else.
        helper_tree = ast.parse(helper.read_text(encoding="utf-8"))
        self.assertTrue(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                            and node.func.attr == "load_model" and isinstance(node.func.value, ast.Name)
                            and node.func.value.id == "whisper" for node in ast.walk(helper_tree)))

    def test_a_cpu_choice_never_asks_for_the_gpu(self) -> None:
        self.assertEqual(whisper_local.pick_whisper_device(False), "cpu")

    def test_the_backend_has_no_backup_whisper_script(self) -> None:
        text = _function_text("Invoke-PythonWhisperTranscriptProcess")
        self.assertTrue(text)
        self.assertNotIn("import whisper", text)

    def test_a_failed_helper_stops_the_transcript_with_its_reason(self) -> None:
        def run(result: str) -> subprocess.CompletedProcess:
            source = textwrap.dedent(
                f"""
                $tokens = $null; $parseErrors = $null
                $ast = [System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', [ref]$tokens, [ref]$parseErrors)
                foreach ($name in @('Invoke-PythonWhisperTranscriptProcess', 'Get-MediaManglersPythonCliUnavailableMessage', 'Ensure-Directory')) {{
                    $node = $ast.Find({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }}, $true)
                    Invoke-Expression $node.Extent.Text
                }}
                function Get-PackagedRuntimeGuidance {{ 'Reinstall.' }}
                function Invoke-MediaManglersPythonCli {{ {result} }}
                try {{
                    Invoke-PythonWhisperTranscriptProcess -PythonCommand 'python' -AudioPath 'a.wav' -TranscriptFolder '{Path(temp) / "t"}' -ModelName 'base.en' -FFmpegExe 'C:\\ff\\ffmpeg.exe' -PreferGpu $false | Out-Null
                    [Console]::Out.WriteLine('NO ERROR')
                }} catch {{ [Console]::Out.WriteLine('ERROR: ' + $_.Exception.Message) }}
                """
            ).strip()
            harness = Path(temp) / "harness.ps1"
            harness.write_text(source, encoding="utf-8")
            return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                                  capture_output=True, text=True, timeout=120)

        with tempfile.TemporaryDirectory() as temp:
            failed = run("[pscustomobject]@{ ExitCode = 1; Result = [pscustomobject]@{ ok = $false; error = 'CUDA out of memory' } }")
            missing = run("$null")
        self.assertIn("ERROR: The Whisper helper failed: CUDA out of memory", failed.stdout, failed.stderr)
        self.assertIn("ERROR: Whisper transcription could not find the packaged python helper", missing.stdout,
                      missing.stderr)


class AudioManglerOneLoaderTests(unittest.TestCase):
    """Audio Mangler, the standalone audio script, kept its own Whisper script for when the shared helper failed.
    When the helper refused a model that was missing or damaged, that script called whisper.load_model itself, and
    Whisper downloaded the model, or replaced the damaged copy, without the operator's approval."""

    def test_audio_mangler_never_loads_whisper_itself(self) -> None:
        # No Python that Audio Mangler can run calls load_model: a Whisper load goes through the shared helper.
        text = AUDIO_SCRIPT.read_text(encoding="utf-8")
        found = [f"Audio Mangler.ps1:{number}: {line.strip()}"
                 for number, line in enumerate(text.splitlines(), start=1) if re.search(r"load_model\s*\(", line)]
        self.assertEqual(found, [])
        # The same search finds the shared helper's own load, so it would find one in the script.
        helper = REPO_ROOT / "src" / "media_manglers" / "providers" / "whisper_local.py"
        self.assertRegex(helper.read_text(encoding="utf-8"), r"whisper\.load_model\s*\(")

    def test_audio_mangler_has_no_backup_whisper_script(self) -> None:
        text = _function_text("Invoke-PythonWhisperTranscriptProcess", AUDIO_SCRIPT)
        self.assertTrue(text)
        self.assertNotIn("import whisper", text)
        self.assertNotIn("Falling back", text)

    def test_a_failed_helper_stops_the_audio_transcript_with_its_reason(self) -> None:
        def quoted(value: str) -> str:
            return "'" + value.replace("'", "''") + "'"

        def run(temp: str, result: str) -> subprocess.CompletedProcess:
            source = textwrap.dedent(
                f"""
                $tokens = $null; $parseErrors = $null
                $ast = [System.Management.Automation.Language.Parser]::ParseFile('{AUDIO_SCRIPT}', [ref]$tokens, [ref]$parseErrors)
                foreach ($name in @('Invoke-PythonWhisperTranscriptProcess', 'Get-MediaManglersPythonCliUnavailableMessage', 'Ensure-Directory')) {{
                    $node = $ast.Find({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }}, $true)
                    Invoke-Expression $node.Extent.Text
                }}
                function Get-PackagedRuntimeGuidance {{ 'Reinstall.' }}
                function Write-Log {{ param([string]$Message, [string]$Level = 'INFO') [Console]::Out.WriteLine('LOG: ' + $Message) }}
                # Anything started besides the helper would be a second Whisper loader.
                function Invoke-ExternalStreaming {{ [Console]::Out.WriteLine('OTHER LOADER STARTED'); [pscustomobject]@{{ ExitCode = 1; StdOut = ''; StdErr = '' }} }}
                function Invoke-ExternalCapture {{ [Console]::Out.WriteLine('OTHER LOADER STARTED'); [pscustomobject]@{{ ExitCode = 1; StdOut = ''; StdErr = '' }} }}
                function Invoke-MediaManglersPythonCli {{ {result} }}
                try {{
                    Invoke-PythonWhisperTranscriptProcess -PythonCommand 'python' -AudioPath 'a.wav' -TranscriptFolder '{Path(temp) / "t"}' -ModelName 'base' -LanguageCode 'en' -FFmpegExe 'C:\\ff\\ffmpeg.exe' -PreferGpu $false | Out-Null
                    [Console]::Out.WriteLine('NO ERROR')
                }} catch {{ [Console]::Out.WriteLine('ERROR: ' + $_.Exception.Message) }}
                """
            ).strip()
            harness = Path(temp) / "harness.ps1"
            harness.write_text(source, encoding="utf-8-sig")
            # Anything the script writes to the temporary folder stays inside this test's own folder.
            return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                                  env={**os.environ, "TEMP": temp, "TMP": temp})

        def refused(message: str) -> str:
            return ("[pscustomobject]@{ ExitCode = 1; Result = [pscustomobject]@{ ok = $false; error = "
                    + quoted(message) + " } }")

        with tempfile.TemporaryDirectory() as temp:
            not_here = whisper_models.not_approved_message("base", whisper_models.MISSING)
            damaged = whisper_models.not_approved_message("base", whisper_models.DAMAGED,
                                                          str(Path(temp) / "whisper" / "base.pt"))
            runs = {
                "model not on this PC": (run(temp, refused(not_here)), "ERROR: The Whisper helper failed: " + not_here),
                "model damaged": (run(temp, refused(damaged)), "ERROR: The Whisper helper failed: " + damaged),
                "helper failed": (run(temp, refused("CUDA out of memory")),
                                  "ERROR: The Whisper helper failed: CUDA out of memory"),
                "no helper": (run(temp, "$null"), "ERROR: Whisper transcription could not find the packaged python helper"),
            }
        for case, (result, expected) in runs.items():
            with self.subTest(case):
                self.assertIn(expected, result.stdout, result.stderr)
                self.assertNotIn("OTHER LOADER STARTED", result.stdout)
                self.assertNotIn("NO ERROR", result.stdout)
        # The error the operator sees carries the refusal's way out.
        error = [line for line in runs["model not on this PC"][0].stdout.splitlines() if line.startswith("ERROR: ")]
        self.assertEqual(len(error), 1)
        self.assertIn("Approve its download in Settings > Dependencies", error[0])


class NarrationDefaultsTests(unittest.TestCase):
    """With the racing preset a blank language is English, for Find my bug reports and the Inbox
    alike; the Inbox used to leave it blank, and Whisper guessed Nynorsk from a quiet opening."""

    def _resolve(self, language: str, mode: str, profile: str, narrated: bool = False) -> dict:
        source = textwrap.dedent(
            f"""
            $tokens = $null; $parseErrors = $null
            $ast = [System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', [ref]$tokens, [ref]$parseErrors)
            $node = $ast.Find({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Resolve-MMNarrationTranscriptionDefaults' }}, $true)
            Invoke-Expression $node.Extent.Text
            Resolve-MMNarrationTranscriptionDefaults -Language '{language}' -NarrationSpeechMode '{mode}' -ProfileName '{profile}' {'-NarratedRecordings' if narrated else ''} | ConvertTo-Json -Compress
            """
        ).strip()
        run = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", source],
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout.strip().splitlines()[-1])

    def test_the_racing_preset_means_english_and_sparse_speech(self) -> None:
        self.assertEqual(self._resolve("", "Auto", "Racing evidence preset (iRacing)"),
                         {"Language": "en", "NarrationSpeechMode": "Sparse"})
        self.assertEqual(self._resolve("de", "Continuous", "iRacing"), {"Language": "de", "NarrationSpeechMode": "Continuous"})
        self.assertEqual(self._resolve("", "Auto", ""), {"Language": "", "NarrationSpeechMode": "Auto"})
        # The Inbox takes only the operator's narrated recordings, whatever profile is chosen.
        self.assertEqual(self._resolve("", "Auto", "", narrated=True), {"Language": "en", "NarrationSpeechMode": "Sparse"})

    def test_find_my_bug_reports_and_the_inbox_both_use_it(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        start = text.index("$reviewProcessPayload = @{")
        payload = text[start:text.index("\n        }", start)]
        self.assertIn("Resolve-MMNarrationTranscriptionDefaults -Language $Language -NarrationSpeechMode $NarrationSpeechMode -NarratedRecordings", payload)
        self.assertIn("$narrationDefaults = Resolve-MMNarrationTranscriptionDefaults", text)

if __name__ == "__main__":
    unittest.main()
