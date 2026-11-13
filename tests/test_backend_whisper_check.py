"""The backend's own Whisper check with Media Manglers' own Python (H1 of the Wave I-A review).

Before a local transcript, ``Video Mangler.ps1`` checks Whisper by starting the run's Python with a bare
``import whisper`` (``Test-PythonWhisper``). Our own Python finds its speech libraries only in the add-on set
downloaded at first launch; since Stage 4 a start-up hook in its own ``site-packages`` puts that set on the path in
every process, so the bare check sees it. These tests run the real check from the script with a real Python laid out
exactly as the packaged build lays out ours (its ``._pth``, the hook, ``speech-lock.json``), on a test add-ons
folder: with the set there it passes; without it, the message points to Set up, never to pip, which cannot help
(our Python has no pip, and the next run would use it again).
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

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers.core import private_runtime, user_folders  # noqa: E402

SCRIPT = REPO_ROOT / "Video Mangler.ps1"
FUNCTIONS = ("Get-ExternalFailureSummary", "Get-MMRunControl", "Test-MMSourceSkipRequested", "Test-MMPauseRequested",
             "Test-MMSkipException", "Get-MMProcessTreeIds", "Stop-MMProcessTree", "Set-MMProcessTreeSuspended",
             "Wait-MMWhilePaused", "Test-MMStartingAppAlive", "Invoke-MMRunControlCheck", "Invoke-ExternalCapture", "Get-ToolSource",
             "Quote-Argument", "Format-DurationHuman", "Get-ProgressDeviceValue", "Get-ProgressStateSignature",
             "Read-ProgressStateFile", "Test-MediaManglersOwnPython", "Test-PythonWhisper")
EMBEDDED = (Path(sys.executable).parent / "python312.zip").is_file()


@unittest.skipUnless(os.name == "nt" and EMBEDDED, "needs Windows and the embedded Python the build ships")
class BackendWhisperCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.app = root / "Media Manglers"
        python = self.app / "runtime" / "python"
        python.mkdir(parents=True)
        for item in Path(sys.executable).parent.iterdir():
            if item.is_file():
                shutil.copy2(item, python / item.name)
        # The build's own ._pth (tools/installer/Build-PackagedRuntime.ps1), with the helper code from this checkout.
        (python / "python312._pth").write_text(
            f"python312.zip\n.\nLib\\site-packages\n{REPO_ROOT / 'src'}\nimport site\n", encoding="ascii")
        site = python / "Lib" / "site-packages"
        site.mkdir(parents=True)
        private_runtime.write_addons_hook(site)
        (python / private_runtime.SPEECH_LOCK_FILE).write_text(json.dumps({"set_id": "h1test"}), encoding="utf-8")
        (self.app / private_runtime.APP_MARKER).write_text("# the packaged application folder's marker\n",
                                                            encoding="utf-8")
        self.python = python / "python.exe"
        self.local = root / "local"
        self.addon_set = self.local / "MediaManglers" / "addons" / "sp-h1test"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _check(self, python: Path) -> tuple[int, str]:
        names = ",".join(f"'{name}'" for name in FUNCTIONS)
        source = textwrap.dedent(f"""
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
            try {{ Test-PythonWhisper -PythonCommand '{python}'; 'CHECK PASSED' }} catch {{ 'CHECK FAILED: ' + $_.Exception.Message }}
        """).strip()
        harness = Path(self.temp.name) / "harness.ps1"
        harness.write_text(source, encoding="utf-8")
        env = {**os.environ, user_folders.WORKBENCH_LOCALAPPDATA_ENV: str(self.local), "PYTHONDONTWRITEBYTECODE": "1"}
        run = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                             capture_output=True, text=True, timeout=120, env=env, check=False)
        return run.returncode, (run.stdout + run.stderr).strip()

    def test_our_python_with_its_speech_set_passes_the_bare_whisper_check(self) -> None:
        (self.addon_set / "whisper").mkdir(parents=True)
        (self.addon_set / "whisper" / "__init__.py").write_text("FROM_THE_ADDON_SET = True\n", encoding="utf-8")
        _code, output = self._check(self.python)
        self.assertIn("CHECK PASSED", output)

    def test_our_python_without_its_speech_set_points_to_set_up_never_to_pip(self) -> None:
        _code, output = self._check(self.python)
        self.assertIn("CHECK FAILED", output)
        self.assertIn("Set up", output)
        self.assertIn("Settings > Dependencies", output)
        self.assertNotIn("pip", output)

    def test_a_python_of_your_own_without_whisper_still_gets_its_install_advice(self) -> None:
        _code, output = self._check(Path(sys.executable))
        self.assertIn("CHECK FAILED", output)
        self.assertIn("pip install -U openai-whisper", output)


if __name__ == "__main__":
    unittest.main()
