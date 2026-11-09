"""How a finished run is shown, for every feature (213): one rule, one set of words.

Green "Complete" is a run that needs nothing from the operator. Yellow "Complete with warnings" is
for a warning the backend marked as one: a line it logged at [WARN] or PowerShell's "WARNING:".
A notice that needs no action is logged as information and never turns a run yellow. Orange
"Completed with problems" is for a result that is partly unusable; red "Failed" for none at all.
"""

from __future__ import annotations

import re

COMPLETED = "completed"
COMPLETED_WITH_WARNINGS = "complete_with_warnings"
COMPLETED_WITH_PROBLEMS = "completed_with_problems"
FAILED = "failed"
CANCELLED = "cancelled"

STAGE_TEXT = {
    COMPLETED: "Complete",
    COMPLETED_WITH_WARNINGS: "Complete with warnings",
    COMPLETED_WITH_PROBLEMS: "Completed with problems",
    FAILED: "Failed",
    CANCELLED: "Cancelled",
}

# What the backend marks as a warning: Write-Log's "[WARN]" and Write-Warning's "WARNING:". The word
# "warning" inside an ordinary line (a file name, a transcript line) is not one.
_WARNING_LINE = re.compile(r"\[WARN(?:ING)?\]|^\s*WARNING:", re.IGNORECASE)


def counts_as_warning(line: str) -> bool:
    return bool(_WARNING_LINE.search(str(line or "")))


def decide(*, succeeded: bool, warnings: int = 0, problems: int = 0, partial: bool = False) -> str:
    """The state of a finished run from what every feature knows about it."""

    if partial or (succeeded and problems):
        return COMPLETED_WITH_PROBLEMS
    if not succeeded:
        return FAILED
    return COMPLETED_WITH_WARNINGS if warnings else COMPLETED


def stage_text(state: str) -> str:
    return STAGE_TEXT.get(state, STAGE_TEXT[FAILED])


def never_ran(_run_state: str) -> str:
    """The state of a queue item the run never started, after Stop or after a failure (220):
    "Cancelled", the word the headline uses after Stop. "Skipped" stays for an item the operator
    skipped, so it never stands for a recording the run simply did not reach."""

    return CANCELLED
