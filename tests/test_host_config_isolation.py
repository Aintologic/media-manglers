"""224 (Wave B2a, 5b): a test Workbench's PowerShell host never reads the real profile's config.json.

The host found config.json only through the real APPDATA folder and ignored MEDIA_MANGLERS_WORKBENCH_APPDATA,
the override the rest of the app honours, so the sandboxed test Workbench read the operator's real one. Here
the real host runs with a decoy profile (APPDATA) holding a marked config.json and a sandbox in the override:
the "Config:" line names the sandbox, the decoy is untouched, and its marker shows up nowhere. The Inbox's
progress file follows the scratch-folder rule too.
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
SCRIPT = REPO_ROOT / "Video Mangler.ps1"
MARKER = "DECOY-PROFILE-MARKER-7f3a"


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "the PowerShell host runs on Windows")
class HostConfigIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_the_real_host_reads_the_sandbox_config_never_the_real_profiles(self) -> None:
        decoy = self.root / "profile" / "Roaming"
        decoy_config = decoy / "MediaManglers" / "config.json"
        decoy_config.parent.mkdir(parents=True)
        decoy_config.write_text(json.dumps({
            "reviewMediaInbox": {"sourceFolders": [str(self.root / MARKER)], "evidenceRoot": "", "localWorkRoot": "",
                                 "ledgerPath": "", "recurse": True},
            "evidence": {"targetRepo": "", "customMarkers": [MARKER], "customDomainTerms": [MARKER]},
        }, indent=2), encoding="utf-8")
        before = (decoy_config.read_bytes(), decoy_config.stat().st_mtime_ns)
        sandbox = self.root / "sandbox" / "Roaming"
        sources = self.root / "sources"
        sources.mkdir()
        env = {**os.environ, "APPDATA": str(decoy), "MEDIA_MANGLERS_WORKBENCH_APPDATA": str(sandbox),
               "MEDIA_MANGLERS_SCRATCH_ROOT": str(self.root / "scratch"), "MEDIA_MANGLERS_ALLOW_TEMP_OUTPUT": "1"}
        run = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), "-ReviewMediaInbox",
             "-ReviewInboxAction", "Scan", "-ReviewSourceFolders", str(sources),
             "-ReviewEvidenceRoot", str(self.root / "evidence"), "-ReviewLocalWorkRoot", str(self.root / "work"),
             "-ReviewLedgerPath", str(self.root / "inbox" / "review-ledger.sqlite"),
             "-InputFolder", str(self.root / "input"), "-OutputFolder", str(self.root / "output"),
             "-PythonExe", sys.executable, "-NoPrompt"],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=300)
        said = run.stdout + "\n" + run.stderr
        config_lines = [line.strip() for line in run.stdout.splitlines() if line.strip().startswith("Config:")]
        self.assertEqual(len(config_lines), 1, said)
        self.assertEqual(config_lines[0].split(":", 1)[1].strip(), str(sandbox / "MediaManglers" / "config.json"))
        self.assertEqual((decoy_config.read_bytes(), decoy_config.stat().st_mtime_ns), before, "the decoy is untouched")
        self.assertNotIn(MARKER, said)
        for path in self.root.rglob("*"):
            if path.is_file() and path != decoy_config:
                self.assertNotIn(MARKER.encode(), path.read_bytes(), f"the decoy's marker reached {path}")

    def test_the_inbox_progress_file_follows_the_scratch_folder_rule(self) -> None:
        scratch = self.root / "scratch"
        harness = self.root / "harness.ps1"
        harness.write_text(textwrap.dedent(f"""
            $ErrorActionPreference = 'Stop'
            $tokens = $null; $parseErrors = $null
            $ast = [System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', [ref]$tokens, [ref]$parseErrors)
            $wanted = @('Invoke-ReviewLedgerHelper', 'Get-MMScratchPath')
            foreach ($node in $ast.FindAll({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $wanted -contains $n.Name }}, $true)) {{
                Invoke-Expression $node.Extent.Text
            }}
            $script:Seen = ''
            function Invoke-MediaManglersPythonCli {{
                param($PythonCommand, $Command, $Payload, $StepName, $HeartbeatSeconds, $TimeoutSeconds, $ProgressStateFilePath)
                $script:Seen = $ProgressStateFilePath
                [pscustomobject]@{{ ExitCode = 0; Result = [pscustomobject]@{{ ok = $true; data = @{{}} }} }}
            }}
            $env:MEDIA_MANGLERS_SCRATCH_ROOT = '{scratch}'
            $null = Invoke-ReviewLedgerHelper -PythonCommand 'py' -Command 'review-media-inbox-process' -Payload @{{}}
            @{{ path = $script:Seen }} | ConvertTo-Json -Compress
            """).strip(), encoding="utf-8")
        run = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stderr)
        path = Path(json.loads(run.stdout.strip().splitlines()[-1])["path"])
        self.assertEqual(path.parent, scratch)
        self.assertTrue(path.name.startswith("media_manglers_review_progress_"))


if __name__ == "__main__":
    unittest.main()
