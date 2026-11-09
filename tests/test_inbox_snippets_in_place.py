"""Review Media Inbox's audio snippets are written in place, so the host moves nothing (224, Wave B2a, item 2).

The PowerShell host made the targeted evidence's snippets in a scratch folder and moved each into the request's
staging folder with Move-Item, which neither waits for an antivirus-style hold nor names the program holding
the file. For the Inbox it now writes each snippet straight to its place in the staging folder, on the Inbox's
drive; the Python helper then promotes the whole folder with its antivirus-safe move. The other features keep
their scratch folder and move, as before. The real host function runs here, with FFmpeg stood in for.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "Video Mangler.ps1"
FUNCTIONS = ("Invoke-CodexEvidenceAudioTasks", "Ensure-Directory", "Test-MMNonEmptyFile", "ConvertTo-FfmpegSecondsText")


class InboxSnippetsInPlaceTests(unittest.TestCase):
    def _run(self, write_in_place: bool) -> dict:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage = root / "batch" / ".staging" / "targeted-evidence" / "requests" / "abc" / "audio"
            tasks = [
                {"evidence_id": f"e{n}", "relative_path": f"audio/clip-{n}.mp3", "path": str(stage / f"clip-{n}.mp3"),
                 "source_path": str(root / "source.mkv"), "start_seconds": 10.0 * n, "duration_seconds": 4.0,
                 "audio_stream_index": 1}
                for n in (1, 2)
            ]
            (root / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
            names = ",".join(f"'{name}'" for name in FUNCTIONS)
            switch = " -WriteInPlace" if write_in_place else ""
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
                function Wait-MMWhilePaused {{ param($Where) }}
                function Test-MMSourceSkipRequested {{ param($SourcePath) return $false }}
                function Test-MMSkipException {{ param($ErrorRecord) return $false }}
                function Get-MMScratchPath {{ param($Prefix) return (Join-Path '{root / "scratch"}' ($Prefix + '-' + [guid]::NewGuid().ToString('N'))) }}
                $script:MMCurrentSourcePath = ''
                $script:moves = New-Object System.Collections.Generic.List[string]
                $script:outputs = New-Object System.Collections.Generic.List[string]
                function Move-Item {{
                    param([string]$LiteralPath, [string]$Destination, [switch]$Force)
                    [void]$script:moves.Add($Destination)
                    Microsoft.PowerShell.Management\\Move-Item -LiteralPath $LiteralPath -Destination $Destination -Force
                }}
                function Invoke-ExternalCapture {{
                    param($FilePath, $Arguments, $StepName, $HeartbeatSeconds, [switch]$IgnoreExitCode)
                    $values = @($Arguments)
                    for ($i = 0; $i -lt $values.Count; $i++) {{
                        if ($values[$i] -eq '192k') {{
                            [void]$script:outputs.Add([string]$values[$i + 1])
                            [System.IO.File]::WriteAllBytes([string]$values[$i + 1], [byte[]](1, 2, 3))
                        }}
                    }}
                    return [pscustomobject]@{{ ExitCode = 0 }}
                }}
                $tasks = Get-Content -LiteralPath '{root / "tasks.json"}' -Raw | ConvertFrom-Json
                $results = @(Invoke-CodexEvidenceAudioTasks -FFmpegExe 'ffmpeg' -AudioTasks @($tasks){switch})
                @{{ moves = @($script:moves); outputs = @($script:outputs); statuses = @($results | ForEach-Object {{ [string]$_.status }});
                    made = @($tasks | ForEach-Object {{ Test-Path -LiteralPath ([string]$_.path) -PathType Leaf }}) }} | ConvertTo-Json -Compress
                """
            ).strip()
            harness = root / "harness.ps1"
            harness.write_text(source, encoding="utf-8")
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            result["paths"] = [task["path"] for task in tasks]
            return result

    def test_the_inbox_snippets_are_written_where_they_belong_and_never_moved(self) -> None:
        result = self._run(True)
        self.assertEqual(result["moves"], [], "the host moved nothing")
        self.assertEqual(result["outputs"], result["paths"], "FFmpeg wrote each snippet to its place")
        self.assertEqual(result["statuses"], ["created", "created"])
        self.assertEqual(result["made"], [True, True])

    def test_the_other_features_keep_their_scratch_folder_and_move(self) -> None:
        result = self._run(False)
        self.assertEqual(result["moves"], result["paths"])
        self.assertTrue(all("scratch" in output for output in result["outputs"]))
        self.assertEqual(result["made"], [True, True])

    def test_the_inbox_targeted_evidence_asks_for_it(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8-sig")
        call = next(line for line in text.splitlines()
                    if "Invoke-CodexEvidenceAudioTasks -FFmpegExe" in line and "requestPlan.audio_tasks" in line)
        self.assertIn("-WriteInPlace", call)


if __name__ == "__main__":
    unittest.main()
