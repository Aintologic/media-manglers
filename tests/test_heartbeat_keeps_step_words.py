"""224 (Wave B2b): the host's "still working" heartbeat keeps the step's words, for every job.

Every ten seconds the PowerShell host sends a heartbeat line so the Workbench's "No processing update" timer
stays quiet while a long step runs. The heartbeat used to send its own words: for an Inbox step that has no
measure (for example "Finding your voice"), that was the internal job name ("review-media-inbox-process"),
which then replaced the step's words on the Inbox page and the job banner, and it also set the step's
Blocked and Failed counts back to 0. Now a heartbeat repeats what the step last said, so only the timer moves.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "Video Mangler.ps1"

FUNCTIONS = (
    "Quote-Argument", "Format-DurationHuman", "Get-ExternalFailureSummary", "Get-MMRunControl",
    "Test-MMSourceSkipRequested", "Test-MMPauseRequested", "Test-MMSkipException", "Get-MMProcessTreeIds",
    "Stop-MMProcessTree", "Set-MMProcessTreeSuspended", "Wait-MMWhilePaused", "Test-MMStartingAppAlive", "Invoke-MMRunControlCheck",
    "Read-ProgressStateFile", "Get-ProgressDeviceValue", "Get-ProgressDeviceTag", "Get-ProgressStateSummary",
    "Get-ProgressStateSignature", "Invoke-ExternalStreaming", "Invoke-ExternalCapture", "Write-MMProgressV1",
)

# A stand-in for an Inbox step with no measure: it says what it is doing once, then works for a while.
INBOX_STEP = """
    import json, os, sys, time
    from datetime import datetime, timezone
    path = sys.argv[1]
    event = {"schema": "MM_PROGRESS_V1", "phase": "Finding your voice", "progress_kind": "indeterminate",
             "activity": "Choosing the narration track the way every feature does", "source_name": "race.mkv",
             "source_total": 3, "source_ordinal": 2, "source_state": "active", "prepared_count": 1,
             "blocked_count": 1, "failed_count": 0,
             "updated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    with open(path + ".tmp", "w", encoding="utf-8") as handle:
        json.dump(event, handle)
    os.replace(path + ".tmp", path)
    time.sleep(4.5)
    """


def _run_host(body: str, helper_code: str = "") -> list[dict]:
    """Run ``body`` in the real host's own functions (parsed from the script) and return its progress lines."""

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        helper = root / "helper.py"
        helper.write_text(textwrap.dedent(helper_code), encoding="utf-8")
        state = root / "progress.json"
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
            $script:MMRunControlPath = ''
            $script:MMRunControlCache = $null
            $script:MMRunControlReadAt = [datetime]::MinValue
            $script:MMLastResumeAt = $null
            $python = '{sys.executable}'
            $helper = '{helper}'
            $state = '{state}'
            """).strip() + "\n" + textwrap.dedent(body).strip(), encoding="utf-8")
        completed = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                                   capture_output=True, text=True, timeout=120)
        if completed.returncode != 0:
            raise AssertionError(completed.stderr or completed.stdout)
    return [json.loads(line[len("MM_PROGRESS_V1 "):]) for line in completed.stdout.splitlines()
            if line.startswith("MM_PROGRESS_V1 ")]


@unittest.skipUnless(sys.platform == "win32", "the host runs on Windows PowerShell")
class HeartbeatKeepsTheStepWordsTests(unittest.TestCase):
    def test_an_inbox_step_with_no_measure_keeps_its_words_and_counts_between_reports(self) -> None:
        events = _run_host("""
            $script:MMProgressPhase = 'Preparing'
            $null = Invoke-ExternalStreaming -FilePath $python -Arguments @('-I', $helper, $state) -StepName 'review-media-inbox-process' -HeartbeatSeconds 1 -ProgressStateFilePath $state
            """, INBOX_STEP)
        beats = [event for event in events if event["heartbeat"]]
        self.assertGreaterEqual(len(beats), 2, "the host kept the timer alive while the step worked")
        self.assertNotIn("review-media-inbox-process", {event["activity"] for event in events},
                         "the internal job name never reaches the screen")
        self.assertTrue(all(event["activity"] == "Choosing the narration track the way every feature does"
                            for event in beats), [event["activity"] for event in beats])
        self.assertTrue(all((event["source_ordinal"], event["prepared_count"], event["blocked_count"]) == (2, 1, 1)
                            for event in beats), "a heartbeat never sets the step's counts back to 0")

    def test_a_tool_heartbeat_keeps_the_words_the_step_said_before_it(self) -> None:
        events = _run_host("""
            $script:MMProgressPhase = 'Screenshots'
            Write-MMProgressV1 -Phase 'Screenshots' -ProgressKind indeterminate -Activity 'Making the screenshots of race.mkv'
            $null = Invoke-ExternalCapture -FilePath $python -Arguments @('-I', $helper) -StepName 'ffmpeg screenshot batch 7' -HeartbeatSeconds 1
            """, "import time\ntime.sleep(3.5)\n")
        beats = [event for event in events if event["heartbeat"]]
        self.assertGreaterEqual(len(beats), 2)
        self.assertTrue(all(event["activity"] == "Making the screenshots of race.mkv" for event in beats),
                        [event["activity"] for event in beats])

    def test_a_step_that_has_said_nothing_yet_is_still_named_by_its_heartbeat(self) -> None:
        events = _run_host("""
            $script:MMProgressPhase = 'Audio'
            $null = Invoke-ExternalCapture -FilePath $python -Arguments @('-I', $helper) -StepName 'Extracting the narration audio' -HeartbeatSeconds 1
            """, "import time\ntime.sleep(2.5)\n")
        beats = [event for event in events if event["heartbeat"]]
        self.assertTrue(beats and all(event["activity"] == "Extracting the narration audio" for event in beats))


if __name__ == "__main__":
    unittest.main()
