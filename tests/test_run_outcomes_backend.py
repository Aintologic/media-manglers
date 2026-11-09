"""196: a recording with no narration is a correct result, not a problem.

The backend lists recordings it could not use apart from those that simply had no narration, so
the run neither fails nor "needs attention" because of them. The PowerShell functions are parsed
out of "Video Mangler.ps1" and run on their own, as in test_voice_verdict_backend.py.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

from tests.script_functions import function_text

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "Video Mangler.ps1"


def _run(body: str, folder: Path) -> dict:
    source = textwrap.dedent(
        f"""
        $ErrorActionPreference = 'Stop'
        $tokens = $null; $parseErrors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', [ref]$tokens, [ref]$parseErrors)
        $wanted = @('Get-MMRecordingOutcomeLines', 'Get-CodexEvidenceProblemReason', 'Select-MMDistinctVideos',
                    'Get-VideoFilesFromPath', 'Get-SupportedVideoExtensions', 'Normalize-UserPath')
        foreach ($node in $ast.FindAll({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $wanted -contains $n.Name }}, $true)) {{
            Invoke-Expression $node.Extent.Text
        }}
        {body}
        """
    ).strip()
    harness = folder / "harness.ps1"
    harness.write_text(source, encoding="utf-8")
    process = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                             capture_output=True, text=True, timeout=120)
    if process.returncode != 0:
        raise AssertionError(process.stderr)
    return json.loads(process.stdout.strip().splitlines()[-1])


class RunOutcomeTests(unittest.TestCase):
    def test_no_narration_is_listed_apart_from_recordings_that_could_not_be_used(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = _run(
                """
                $entries = @(
                    [pscustomobject]@{ source_filename = 'a.mkv'; status = 'completed' },
                    [pscustomobject]@{ source_filename = 'b.mkv'; status = 'no_narration'; error_message = 'From your setting: Track 2 has no clear speech.' },
                    [pscustomobject]@{ source_filename = 'c.mkv'; status = 'failed'; error_message = 'the recording could not be read' }
                )
                $detected = @(
                    [pscustomobject]@{ source_filename = 'd.mkv'; status = 'completed'; transcript_quality = [pscustomobject]@{ quality_status = 'no_narration_found' } }
                )
                $outcome = Get-MMRecordingOutcomeLines -ManifestEntries $entries -DetectedSources $detected
                [ordered]@{ problems = @($outcome.Problems); none = @($outcome.NoNarration) } | ConvertTo-Json -Compress
                """,
                Path(temp),
            )
        self.assertEqual([line.split(":")[0] for line in result["problems"]], ["c.mkv"])
        self.assertEqual([line.split(":")[0] for line in result["none"]], ["b.mkv", "d.mkv"])
        self.assertTrue(all("no narration found" in line for line in result["none"]), result["none"])

    def test_only_recordings_that_could_not_be_used_fail_the_run(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8-sig")
        body = function_text(text, "Invoke-CodexEvidencePackageBatch")
        self.assertIn("$runOutcomes = Get-MMRecordingOutcomeLines", body)
        self.assertIn('Write-Host "Recordings with no narration, so nothing to report from them:"', body)
        self.assertIn('Write-Log ("Recording had no narration: {0}" -f $noNarrationLine)', body)
        # "Needs attention", the failed progress state and the run's exit code 2 come from
        # $problemRecordings alone, which no longer holds a recording with no narration.
        self.assertIn('$packageTerminalState = if ($problemRecordings.Count -gt 0) { "failed" } else { "succeeded" }', body)
        self.assertIn('if ([int]$codexEvidenceResult.ProblemCount -gt 0) {', text)
        self.assertIn("ProblemCount      = $problemRecordings.Count", body)


    def test_a_recording_with_no_narration_is_logged_as_information_not_a_warning(self) -> None:
        # 199: the Workbench counts [WARN] lines as warnings, so this one made a run whose only
        # outcome was no narration say "Complete with warnings".
        text = SCRIPT.read_text(encoding="utf-8-sig")
        body = function_text(text, "Invoke-CodexEvidencePackageBatch")
        line = next(line for line in body.splitlines() if 'Write-Log ("No narration found for' in line)
        self.assertNotIn('"WARN"', line)


    def test_recordings_run_in_the_order_they_were_listed(self) -> None:
        # 199: Find my bug reports hands over its list in the operator's order; the backend used
        # to sort it by path. A folder is still read in name order.
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for name in ("c.mkv", "a.mkv", "b.mkv"):
                (folder / name).write_bytes(b"not really video")
            listed = folder / "recordings.mmlist"
            listed.write_text("\n".join(str(folder / name) for name in ("c.mkv", "a.mkv", "b.mkv", "a.mkv")),
                              encoding="utf-8")
            result = _run(
                f"""
                $fromList = @(Select-MMDistinctVideos -Videos @(Get-VideoFilesFromPath -Path '{listed}'))
                $fromFolder = @(Select-MMDistinctVideos -Videos @(Get-VideoFilesFromPath -Path '{folder}'))
                [ordered]@{{ list = @($fromList | ForEach-Object Name); folder = @($fromFolder | ForEach-Object Name) }} | ConvertTo-Json -Compress
                """,
                folder,
            )
        self.assertEqual(result, {"list": ["c.mkv", "a.mkv", "b.mkv"], "folder": ["a.mkv", "b.mkv", "c.mkv"]})

    def test_the_evidence_and_transcript_runs_keep_that_order(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8-sig")
        for name in ("Invoke-CodexEvidencePackageBatch", "Invoke-TranscriptOnlyBatch"):
            body = function_text(text, name)
            self.assertIn("$videos = @(Select-MMDistinctVideos -Videos $videos)", body, name)
            self.assertNotIn("Sort-Object FullName -Unique", body, name)


if __name__ == "__main__":
    unittest.main()
