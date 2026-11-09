from __future__ import annotations

import csv
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest


def _extract_powershell_function(script_text: str, name: str) -> str:
    needle = f"function {name}"
    start = script_text.find(needle)
    if start < 0:
        raise AssertionError(f"PowerShell function not found: {name}")
    brace_start = script_text.find("{", start)
    if brace_start < 0:
        raise AssertionError(f"PowerShell function has no body: {name}")
    depth = 0
    for index in range(brace_start, len(script_text)):
        char = script_text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return script_text[start : index + 1]
    raise AssertionError(f"PowerShell function body did not close: {name}")


class VideoProcessingSummaryTests(unittest.TestCase):
    def test_newline_url_argument_resolves_to_two_ordered_sources(self) -> None:
        powershell = shutil.which("powershell") or shutil.which("powershell.exe")
        if not powershell:
            self.skipTest("PowerShell is not available")

        repo_root = Path(__file__).resolve().parents[1]
        video_script = (repo_root / "Video Mangler.ps1").read_text(encoding="utf-8-sig")
        extracted_functions = "\n\n".join(
            _extract_powershell_function(video_script, name)
            for name in (
                "Test-IsHttpUrl",
                "Get-HttpUrlsFromText",
                "Resolve-RequestedInputSources",
            )
        )

        urls = [
            "https://www.youtube.com/watch?v=26pyVl4Z5js",
            "https://www.youtube.com/watch?v=YQWbylDTHJo",
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = Path(temp_dir) / "multi-url-argument-test.ps1"
            harness.write_text(
                textwrap.dedent(
                    f"""
                    param([string]$InputValue)
                    $ErrorActionPreference = "Stop"

                    {extracted_functions}

                    $resolved = Resolve-RequestedInputSources -RequestedInputValue $InputValue
                    [PSCustomObject]@{{
                        remote = @($resolved.RemoteInputSources)
                        local = [string]$resolved.InputPath
                    }} | ConvertTo-Json -Compress
                    """
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(harness),
                    "-InputValue",
                    "\n".join(urls),
                ],
                text=True,
                capture_output=True,
                timeout=60,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout.strip())
        self.assertEqual(payload["remote"], urls)
        self.assertEqual(payload["local"], "")

    def test_add_summary_row_counts_words_from_transcript_text_when_summary_value_is_zero(self) -> None:
        powershell = shutil.which("powershell") or shutil.which("powershell.exe")
        if not powershell:
            self.skipTest("PowerShell is not available")

        repo_root = Path(__file__).resolve().parents[1]
        video_script = (repo_root / "Video Mangler.ps1").read_text(encoding="utf-8-sig")
        function_names = [
            "Get-TextWordCount",
            "Get-TranscriptWordCountFromArtifacts",
            "Get-PortablePackagePath",
            "Add-SummaryRow",
        ]
        extracted_functions = "\n\n".join(_extract_powershell_function(video_script, name) for name in function_names)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "transcript.txt"
            summary = root / "PROCESSING_SUMMARY.csv"
            transcript.write_text("one two three four five", encoding="utf-8")
            harness = root / "summary-word-count-test.ps1"
            harness.write_text(
                textwrap.dedent(
                    f"""
                    $ErrorActionPreference = "Stop"
                    $script:AppName = "Video Mangler"
                    function Get-AppVersion {{ return "test" }}
                    function Get-FramesFolderName {{ param([double]$Value) return "frames" }}

                    {extracted_functions}

                    Add-SummaryRow `
                      -SummaryCsv "{summary}" `
                      -SourceVideo "clip.mkv" `
                      -OutputFolderName "clip" `
                      -OutputPath "{root}" `
                      -TranscriptText "{transcript}" `
                      -TranscriptWordCount 0 `
                      -FrameIntervalSeconds 0
                    """
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                text=True,
                capture_output=True,
                timeout=60,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            with summary.open("r", encoding="utf-8-sig", newline="") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["transcript_word_count"], "5")


if __name__ == "__main__":
    unittest.main()
