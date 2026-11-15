"""Which Python the app looks at and how it looks (M11, M12 and M14 of the Wave I-A review).

- M11: the Workbench and ``Video Mangler.ps1`` find the Pythons on this PC from one list, so a Python of yours that
  Python's own installer left off PATH (it relies on ``py``) is found beside ours on both sides.
- M12: the readiness probe counts the helper as working only when its own command module loads, as every helper step
  needs (a Python too old for it was kept with every row ready, and then every step failed).
- M14: no Python the app starts to look at writes compiled bytecode, into a Python on the PC or into Media
  Manglers' own folder.
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
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers_workbench import dependencies  # noqa: E402
from media_manglers_workbench.resources import RuntimeResources  # noqa: E402

SCRIPT = REPO_ROOT / "Video Mangler.ps1"
WINDOWS = os.environ.get("SystemRoot", r"C:\Windows")
FUNCTIONS = ("Get-ExternalFailureSummary", "Get-MMRunControl", "Test-MMSourceSkipRequested", "Test-MMPauseRequested",
             "Test-MMSkipException", "Get-MMProcessTreeIds", "Stop-MMProcessTree", "Set-MMProcessTreeSuspended",
             "Wait-MMWhilePaused", "Test-MMStartingAppAlive", "Invoke-MMRunControlCheck", "Invoke-ExternalCapture", "Quote-Argument",
             "Format-DurationHuman", "Get-ProgressDeviceValue", "Get-ProgressStateSignature", "Read-ProgressStateFile",
             "Get-ToolSource", "Get-BundledToolsRoot", "Get-BundledToolPath", "Get-ToolStandardLocations",
             "Resolve-CommandOrPath", "Get-AutoPythonInterpreterCandidates")


def _placeholder(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"placeholder")
    return path


@unittest.skipUnless(os.name == "nt", "the Python lookup is Windows' own")
class OneCandidateListTests(unittest.TestCase):
    def test_both_sides_find_your_python_beside_ours_from_one_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / "Media Manglers"
            ours = _placeholder(app / "runtime" / "python" / "python.exe")
            _placeholder(app / "Video Mangler.ps1")
            # Python's installer, with its default choices: in its own folder, not on PATH.
            yours = _placeholder(root / "Local" / "Programs" / "Python" / "Python312" / "python.exe")
            env = {"PATH": str(Path(WINDOWS) / "System32"), "LOCALAPPDATA": str(root / "Local"),
                   "ProgramFiles": str(root / "Program Files")}
            self.assertIsNone(shutil.which("python", path=env["PATH"]))

            def failing_runner(argv: list[str], _timeout: int, _env: object) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(argv, 1, "", "nothing")

            resources = RuntimeResources(app_root=app, script_path=app / "Video Mangler.ps1",
                                         backend_source_root=None, icon_path=None, powershell_exe="",
                                         python_exe=str(ours), ffmpeg_exe="", ffprobe_exe="", packaged=True,
                                         bundled_dir=str(app / "runtime"))
            with mock.patch.dict(os.environ, env):
                workbench = dependencies.discover_python_candidates(resources, runner=failing_runner)
            self.assertIn(str(yours.resolve()), workbench, "the Workbench finds your Python beside ours")

            names = ",".join(f"'{name}'" for name in FUNCTIONS)
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
                function Write-MMProgressV1 {{ }}
                function Add-LogContentWithRetry {{ }}
                $script:CurrentLogFile = $null
                $script:MMRunControlPath = $null
                $script:BundledToolsRoot = '{app / "runtime"}'
                ConvertTo-Json -Compress @(Get-AutoPythonInterpreterCandidates -PrimaryPythonCommand '{ours}')
            """).strip(), encoding="utf-8")
            run = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                                 capture_output=True, text=True, timeout=120, check=False,
                                 env={**os.environ, **env, "SystemRoot": WINDOWS})
            self.assertEqual(run.returncode, 0, run.stderr)
            script = json.loads(run.stdout.strip().splitlines()[-1])
            script = [script] if isinstance(script, str) else script
            self.assertIn(str(yours.resolve()).casefold(), [item.casefold() for item in script])
            self.assertEqual(sorted(item.casefold() for item in workbench), sorted(item.casefold() for item in script),
                             "one list on both sides")


class HelperImportTests(unittest.TestCase):
    def test_a_python_that_cannot_load_the_helpers_command_module_is_not_counted_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / "src" / "media_manglers"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            # What Python 3.9 says at the helper's first dataclass: the package imports, its commands do not.
            (package / "cli.py").write_text(
                "raise TypeError(\"dataclass() got an unexpected keyword argument 'slots'\")\n", encoding="utf-8")
            code = f"import sys; sys.path[0:0] = [{str(package.parent)!r}]\n" + dependencies._PYTHON_PROBE
            result = dependencies._default_runner([sys.executable, "-c", code, "medium"], 120, None)
        probe = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertFalse(probe["helper_import_ok"])
        self.assertIn("slots", probe["error"])


class NoBytecodeTests(unittest.TestCase):
    def test_every_readiness_probe_runs_with_bytecode_writing_off(self) -> None:
        with mock.patch.dict(os.environ):
            os.environ.pop(dependencies.NO_BYTECODE, None)
            result = dependencies._default_runner(
                [sys.executable, "-c", "import os, sys; print(os.environ.get('PYTHONDONTWRITEBYTECODE'), "
                                       "sys.dont_write_bytecode)"], 60, None)
        self.assertEqual(result.stdout.split(), ["1", "True"])

    def test_the_real_probe_writes_no_compiled_files_into_the_code_it_loads(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "python-core" / "src"
            shutil.copytree(REPO_ROOT / "src" / "media_manglers", source / "media_manglers",
                            ignore=shutil.ignore_patterns("__pycache__"))
            code = f"import sys; sys.path[0:0] = [{str(source)!r}]\n" + dependencies._PYTHON_PROBE
            with mock.patch.dict(os.environ):
                os.environ.pop(dependencies.NO_BYTECODE, None)
                result = dependencies._default_runner([sys.executable, "-c", code, "medium"], 120, None)
            self.assertTrue(json.loads(result.stdout.strip().splitlines()[-1])["helper_import_ok"], result.stderr)
            written = [str(path.relative_to(source)) for path in source.rglob("*.pyc")]
        self.assertEqual(written, [], "nothing compiled was written beside the app's own code")

    def test_the_workbench_turns_it_off_for_everything_it_starts_before_anything_starts(self) -> None:
        from media_manglers_workbench import app

        with mock.patch.dict(os.environ):
            os.environ.pop(dependencies.NO_BYTECODE, None)
            app.prepare_child_environment()
            self.assertEqual(os.environ.get(dependencies.NO_BYTECODE), "1")
        text = (REPO_ROOT / "src" / "media_manglers_workbench" / "app.py").read_text(encoding="utf-8")
        main = text[text.index("\ndef main("):]
        self.assertLess(main.index("prepare_child_environment()"), main.index("take_workbench_lock("))

    def test_both_scripts_turn_it_off_before_they_start_any_python(self) -> None:
        for name in ("Video Mangler.ps1", "Audio Mangler.ps1"):
            with self.subTest(script=name):
                text = (REPO_ROOT / name).read_text(encoding="utf-8")
                self.assertLess(text.index('$env:PYTHONDONTWRITEBYTECODE = "1"'), text.index("\nfunction "))


def _script_run(body: str, functions: tuple[str, ...], temp: Path) -> str:
    names = ",".join(f"'{name}'" for name in functions)
    harness = temp / "harness.ps1"
    harness.write_text(textwrap.dedent(f"""
        $ErrorActionPreference = 'Stop'
        $tokens = $null; $parseErrors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', [ref]$tokens, [ref]$parseErrors)
        $wanted = @({names})
        foreach ($node in $ast.FindAll({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $wanted -contains $n.Name }}, $true)) {{
            Invoke-Expression $node.Extent.Text
        }}
        function Write-Log {{ }}
    """).strip() + "\n" + textwrap.dedent(body).strip(), encoding="utf-8")
    run = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                         capture_output=True, text=True, timeout=120, check=False)
    return (run.stdout + run.stderr).strip()


@unittest.skipUnless(os.name == "nt", "the script's advice is checked on Windows")
class ArgosAndInstallAdviceTests(unittest.TestCase):
    """M13 and L14 of the Wave I-A review: our own Python has no pip and is never changed, so it is never told to
    pip-install anything; any other Python gets a line PowerShell runs as pasted."""

    FUNCTIONS = ("Test-MediaManglersOwnPython", "Quote-Argument", "Test-WhisperModelSupportsTranslation",
                 "Get-TranslationProviderPreflightNotes", "Get-YtDlpInstallCommands")

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.ours = _placeholder(self.root / "Media Manglers" / "runtime" / "python" / "python.exe")
        _placeholder(self.root / "Media Manglers" / "Video Mangler.ps1")
        self.yours = _placeholder(self.root / "My Python" / "python.exe")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _preflight(self, python: Path) -> str:
        return _script_run(f"""
            function Get-ArgosModuleStatus {{ return [PSCustomObject]@{{ ModuleInstalled = $false }} }}
            try {{
                Get-TranslationProviderPreflightNotes -EffectiveProvider 'Local' -TranslationTargets @('es') `
                    -ModelName 'medium' -PythonCommand '{python}' -InteractiveMode:$false -HeartbeatSeconds 15
                'NO MESSAGE'
            }} catch {{ 'REFUSED: ' + $_.Exception.Message }}
        """, self.FUNCTIONS, self.root)

    def test_our_own_python_is_never_told_to_pip_install_argos(self) -> None:
        text = self._preflight(self.ours)
        self.assertIn("REFUSED", text)
        self.assertNotIn("pip", text)
        self.assertIn("Python of your own that has Argos Translate", text)

    def test_another_python_gets_a_line_powershell_runs_as_pasted(self) -> None:
        text = self._preflight(self.yours)
        self.assertIn(f'& "{self.yours}" -m pip install argostranslate', text)

    def test_the_yt_dlp_advice_never_names_our_own_python(self) -> None:
        text = _script_run(f"""
            (Get-YtDlpInstallCommands -PythonCommand '{self.ours}') -join ' | '
            '---'
            (Get-YtDlpInstallCommands -PythonCommand '{self.yours}') -join ' | '
        """, self.FUNCTIONS, self.root)
        ours, yours = text.split("---")
        self.assertNotIn("pip", ours)
        self.assertIn(f'& "{self.yours}" -m pip install -U yt-dlp', yours)

    def test_the_script_applies_its_argos_exception_before_its_translation_check(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        exception = text.index("Select-PreferredWhisperPythonInterpreter -PrimaryPythonCommand $PythonExe -TranslationNeedsArgos\n")
        self.assertLess(exception, text.index("$translationProviderPreflightNotes = @(Get-TranslationProviderPreflightNotes"))


class StaleTranslationChoiceTests(unittest.TestCase):
    def test_start_asks_for_readiness_again_when_the_translation_setting_changed(self) -> None:
        import types

        from media_manglers_workbench.app import WorkbenchWindow

        host = types.SimpleNamespace(readiness_translation_argos=False, private_python=lambda: "python.exe",
                                     run_settings={"translate_to": "es", "processing_mode": "Local"})
        reasons = WorkbenchWindow.translation_choice_blockers(host)
        self.assertEqual(len(reasons), 1)
        self.assertIn("Refresh readiness", reasons[0])
        host.run_settings = {"translate_to": "en", "processing_mode": "Local"}
        self.assertEqual(WorkbenchWindow.translation_choice_blockers(host), [], "English needs no Argos")
        host.private_python = lambda: ""
        host.run_settings = {"translate_to": "es", "processing_mode": "Local"}
        self.assertEqual(WorkbenchWindow.translation_choice_blockers(host), [], "no Python of ours to choose against")


if __name__ == "__main__":
    unittest.main()
