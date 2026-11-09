"""Prompt draft generation for selected evidence items.

The prompts produced here are the operator's hand-off to an external coding
agent (Claude Code or Codex). They must be self-contained: an agent that
receives only the prompt text must be able to locate the evidence package on
disk, know which repositories exist, and know that the deterministic marker
scan is a hint rather than the finding.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from .evidence import EvidenceCandidate, EvidencePackage


@dataclass(frozen=True, slots=True)
class PromptDraftPaths:
    codex_path: Path
    claude_path: Path
    handoff_path: Path


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    return (cleaned or "evidence-item")[:80]


def _package_root_text(package: EvidencePackage) -> str:
    """Absolute, agent-resolvable location of the evidence package."""
    try:
        return str(package.root.resolve())
    except OSError:
        return str(package.root.absolute())


def _package_relative_path(package: EvidencePackage, path: Path) -> str:
    try:
        return path.resolve().relative_to(package.root.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


def _repo_hinting_payload(package: EvidencePackage) -> dict[str, Any]:
    payload = package.repo_routing_payload or {}
    hinting = payload.get("repo_hinting")
    return hinting if isinstance(hinting, dict) else {}


def _load_project_map(package: EvidencePackage) -> tuple[dict[str, Any], str]:
    """Return the operator's repo map and the path it was read from.

    The map is machine-local operator configuration. It is read here so the
    emitted prompt can name real repositories instead of leaving every item as
    UNKNOWN.
    """
    hinting = _repo_hinting_payload(package)
    raw_path = str(hinting.get("repo_map_path") or "").strip()
    if not raw_path:
        return {}, ""
    path = Path(raw_path)
    if not path.is_absolute():
        path = package.root / path
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:  # noqa: BLE001 - a missing/invalid map must not break export.
        return {}, str(path)
    repos = data.get("repos") if isinstance(data, dict) else None
    return (repos if isinstance(repos, dict) else {}), str(path)


def _project_section(package: EvidencePackage) -> str:
    repos, map_path = _load_project_map(package)
    if not repos:
        return (
            "## My Projects\n\n"
            "No operator repo map was available when this package was built, so every "
            "item below is likely to say `UNKNOWN`. Ask the operator which repository "
            "each item belongs to before opening anything.\n\n"
        )

    lines = [
        "## My Projects",
        "",
        "These are the operator's repositories and the words actually used for each one "
        "while narrating. Route each proposed issue to one of these. If an item matches "
        "none of them, say so and ask rather than guessing.",
        "",
        "| Repository | Project | The operator might call it |",
        "|---|---|---|",
    ]
    for repo_name, entry in repos.items():
        data = entry if isinstance(entry, dict) else {}
        label = str(data.get("project_label") or "").strip() or repo_name
        keywords = data.get("keywords") or []
        if isinstance(keywords, str):
            keywords = [keywords]
        spoken = ", ".join(str(k) for k in keywords[:14]) or "-"
        lines.append(f"| `{repo_name}` | {label} | {spoken} |")
    lines.append("")
    lines.append(f"Source: `{map_path}` (operator-local; do not copy it into any repository).")
    lines.append("")
    lines.append("")
    return "\n".join(lines)


_DETECTION_CAVEAT = """## How This Package Was Built (read this first)

The candidate list in this package was produced by a deterministic marker scan:
it looks for request phrases such as "create a ticket" or "instructions for AI"
in the transcript. A word such as "bug", "ticket" or "fix this" said on its own
is not a request; those moments are listed in `MENTIONED_NOT_ASKED.md` instead.
That scan is a **hint, not the finding**. It is known to:

- miss defects the operator described in plain language without those words;
- promote non-software remarks (driving notes, setup talk) that happen to
  contain a marker word;
- emit titles that are raw transcript fragments.

Therefore: **do not treat the candidate list as the list of issues.** Read the
full transcript yourself and decide what the operator actually reported. Expect
to find defects the scan missed, and expect to discard some it flagged.
"""


_OUTPUT_CONTRACT = """## What To Produce

Produce **draft GitHub issues**, not a narrative recommendation.

For each defect you are confident the operator reported, give:

1. **Repository** - one of the repositories in "My Projects" above.
2. **Title** - written by you, in plain imperative English. Never a transcript
   fragment.
3. **Body** - what the operator observed, when (source file + timestamp), expected vs
   actual behaviour where they stated it, and any later clarification they gave.
4. **Evidence** - the package-relative paths of the screenshots and the clip
   (from `NARRATION_EVIDENCE.md`) that show the problem; say which ones you
   propose to attach to the issue.
5. **Confidence** - and what would raise it.

Then:

- Search existing issues in the target repository and say, per draft, whether it
  is new or a comment on an existing issue (give the number).
- List separately anything you discarded from the candidate list, with the
  reason.
- List separately anything you found that the marker scan missed.
- List anything too ambiguous to file, with the question you need answered.
- Show the operator `MENTIONED_NOT_ASKED.md` with your proposals. It lists moments where
  the operator said a word like "ticket", "bug" or "fix this" without asking for anything.
  The operator decides about each one; never draft or file an issue from it on your own.

**Present all of this to the operator and stop. Do not create, edit or comment
on any GitHub issue until the operator approves the list.**

Before any public write, strip machine-local paths and unrelated personal
content from the text. Do not upload evidence files unless the operator approves a
specific attachment.
"""


def _evidence_lines(package: EvidencePackage, item: EvidenceCandidate) -> list[str]:
    lines = []
    for evidence_file in item.evidence_files:
        lines.append(f"- {evidence_file.label}: `{_package_relative_path(package, evidence_file.path)}`")
    if not lines:
        lines.append("- No evidence files were listed in the parsed package.")
    return lines


def _base_prompt(package: EvidencePackage, item: EvidenceCandidate, tool_name: str) -> str:
    transcript = (
        item.transcript_window_text.strip()
        or item.transcript_excerpt.strip()
        or "(No transcript excerpt available.)"
    )
    evidence = "\n".join(_evidence_lines(package, item))
    root = _package_root_text(package)
    return f"""# {tool_name}: review one ticket candidate

You are reviewing one candidate from a Video Mangler evidence package built from
a screen recording in which the operator narrated aloud while sim racing.

## Package Location

The evidence package is on this machine at:

```
{root}
```

All package-relative paths below resolve against that directory. Read the files
themselves; this prompt is a pointer, not a substitute for them.

{_DETECTION_CAVEAT}
{_project_section(package)}
## This Candidate

- Item type: {item.item_type}
- Evidence ID: {item.item_id}
- Scan-generated title (likely poor): {item.title}
- Source recording: {item.source_filename or "unknown"}
- Timestamp window: {item.timestamp_start or "unknown"} - {item.timestamp_end or "unknown"}
- Marker timestamp: {item.marker_timestamp or "unknown"}
- Scan confidence: {item.confidence or "unknown"}
- Scan repo guess: {item.repo_hint or "UNKNOWN"} ({item.repo_confidence or "unknown"})

## Evidence Files

{evidence}

## Transcript Window Or Excerpt

```text
{transcript}
```

## Required Review Procedure

1. Do not rely on the excerpt above or on `ticket.md`; both are shortened.
2. Read the candidate's `transcript_window.md`.
3. Read the candidate's `narration_context.md`.
4. Read the shared full transcript for this recording. The operator often keeps
   talking about the same defect well outside the candidate's window.
5. Treat a driving pause as a pause, not as the end of the thought.
6. Decide whether post-pause narration belongs to this defect. Do not assume it
   does, and do not assume it does not.
7. Extract: what the operator expected, what happened, how to reproduce it, which project
   it affects, and any correction they made later.
8. Review frames, panel crops and audio together with the timestamps.
9. Decide whether this candidate is a real software defect at all. Driving
   commentary and setup talk are not tickets.

{_OUTPUT_CONTRACT}"""


def build_codex_prompt(package: EvidencePackage, item: EvidenceCandidate) -> str:
    return _base_prompt(package, item, "Codex")


def build_claude_prompt(package: EvidencePackage, item: EvidenceCandidate) -> str:
    return _base_prompt(package, item, "Claude Code")


def _handoff_common(package: EvidencePackage) -> dict[str, Any]:
    repos, map_path = _load_project_map(package)
    return {
        "schema_version": 2,
        "evidence_package_root": _package_root_text(package),
        "project_map_path": map_path,
        "projects": {
            name: {
                "project_label": (entry or {}).get("project_label", ""),
                "keywords": (entry or {}).get("keywords", []),
            }
            for name, entry in repos.items()
        },
        "detection_method": "deterministic_marker_scan",
        "detection_is_authoritative": False,
        "detection_caveat": (
            "The candidate list came from keyword matching on the transcript. It misses "
            "defects described without marker words and promotes non-software remarks "
            "that contain them. Read the full transcript and decide independently."
        ),
        "local_evidence_access_required": True,
        "agent_must_present_before_writing": True,
        "privacy_review_required_before_public_write": True,
    }


def export_prompt_drafts(package: EvidencePackage, item: EvidenceCandidate) -> PromptDraftPaths:
    draft_dir = package.root / "operator-drafts"
    draft_dir.mkdir(parents=True, exist_ok=True)
    basename = _safe_filename(item.item_id)
    codex_path = draft_dir / f"{basename}.codex.md"
    claude_path = draft_dir / f"{basename}.claude.md"
    handoff_path = draft_dir / f"{basename}.handoff.json"
    codex_path.write_text(build_codex_prompt(package, item), encoding="utf-8")
    claude_path.write_text(build_claude_prompt(package, item), encoding="utf-8")
    required_files = [
        {
            "label": evidence_file.label,
            "path": _package_relative_path(package, evidence_file.path),
            "exists": evidence_file.path.exists(),
        }
        for evidence_file in item.evidence_files
    ]
    handoff_payload = {
        **_handoff_common(package),
        "candidate_id": item.item_id,
        "candidate_type": item.item_type,
        "source_filename": item.source_filename,
        "marker_timestamp": item.marker_timestamp,
        "scan_title": item.title,
        "scan_repo_guess": item.repo_hint,
        "requires_github_review": item.requires_github_review,
        "required_files": required_files,
        "required_review_steps": [
            "Do not rely on ticket.md or the shortened excerpt.",
            "Read transcript_window.md.",
            "Read narration_context.md.",
            "Read the shared full transcript; narration often continues outside the window.",
            "Treat driving pauses as pauses, not ticket endings.",
            "Decide whether post-pause narration belongs; do not assume either way.",
            "Extract expected behaviour, observed behaviour, reproduction, affected repo, later corrections.",
            "Review frames, panel crops, audio and timestamps together.",
            "Decide whether this is a software defect at all.",
            "Draft issues, present them to the operator, and wait for approval before writing to GitHub.",
        ],
    }
    handoff_path.write_text(
        json.dumps(handoff_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return PromptDraftPaths(
        codex_path=codex_path,
        claude_path=claude_path,
        handoff_path=handoff_path,
    )


def _moments(count: int) -> str:
    return f"{count} moment" if count == 1 else f"{count} moments"


def build_session_prompt(package: EvidencePackage, tool_name: str) -> str:
    mention_count = sum(1 for item in package.session_mentions if item.record_type == "ticket_mention")
    if not mention_count:
        mention_count = len(package.candidates) + len(package.unrendered_candidates)
    thread_count = len(package.proposed_threads)
    unassigned_count = len(package.unassigned_mention_ids)
    root = _package_root_text(package)
    start_here = (
        _package_relative_path(package, package.start_here_path)
        if package.start_here_path
        else "START_HERE_FOR_TICKET_AGENT.md"
    )
    return f"""# {tool_name}: find the operator's bug reports in this session

The operator recorded a sim-racing session and narrated aloud. Somewhere in that
narration they described defects in software they wrote. Your job is to find them
all and draft the GitHub issues.

## Package Location

The evidence package is on this machine at:

```
{root}
```

Follow `{start_here}`; it is the only reading order. In short:
read `transcript/full_transcript.md` end to end first, then use the session
timeline, `CONSOLIDATED_OUTCOMES.json`, the candidate transcript windows and
narration contexts to locate evidence. All paths are relative to the directory
above.

Two things to know about the evidence:

- The transcripts drop very low-confidence stretches to avoid text Whisper
  invents over engine noise. If a sentence seems cut short, check
  `filtered_segments` in `transcript/sources/*.transcript.raw.json` for that
  timestamp before concluding the operator said nothing. The same file lists, under
  `rescued_segments`, short lines the transcriber was unsure of that were kept
  only because they sit next to real narration; read those with more caution.
- `NARRATION_EVIDENCE.md` lists every stretch where the operator is talking with
  screenshots (full screen and each monitor) and a short video clip, whether or
  not the keyword scan flagged it. The operator's projects are on-screen overlays, so use
  it for every issue: find the moment whose time range contains the timestamp,
  look at the screenshots, and cite the ones that show the problem.
- Keyword-flagged moments also have frames under `artifacts/sources/<source-id>/`
  (see each `evidence_items/<id>/frame_index.csv`).

{_DETECTION_CAVEAT}
The full transcripts are the source of truth. Work through them end to end.

{_project_section(package)}## Session Summary (from the marker scan)

- Ticket mentions flagged: {mention_count}
- Proposed thread groups: {thread_count}
- Unassigned mentions: {unassigned_count}
- Review-needed items: {len(package.review_needed)}
- Mentioned, not asked for: {_moments(len(package.mentioned_not_asked))} (`MENTIONED_NOT_ASKED.md`)
- Package status: {package.package_status.get('status', 'unknown')}

These counts describe the scan's output, not the number of real defects.

## Grouping

Do not create one issue per marker. The deterministic relationship hints are
suggestions, not conclusions. Combine mentions only when they concern the same
defect or the same requested change; keep genuinely separate actions separate.
Cite the source filename and timestamp for every claim.

{_OUTPUT_CONTRACT}"""


def export_session_prompt_drafts(package: EvidencePackage) -> PromptDraftPaths:
    draft_dir = package.root / "operator-drafts"
    draft_dir.mkdir(parents=True, exist_ok=True)
    codex_path = draft_dir / "session.codex.md"
    claude_path = draft_dir / "session.claude.md"
    handoff_path = draft_dir / "session.handoff.json"
    codex_path.write_text(build_session_prompt(package, "Codex"), encoding="utf-8")
    claude_path.write_text(build_session_prompt(package, "Claude Code"), encoding="utf-8")
    handoff_path.write_text(
        json.dumps(
            {
                **_handoff_common(package),
                "start_file": (
                    _package_relative_path(package, package.start_here_path)
                    if package.start_here_path
                    else "START_HERE_FOR_TICKET_AGENT.md"
                ),
                "mention_count": len(package.session_mentions),
                "proposed_thread_count": len(package.proposed_threads),
                "unassigned_mention_ids": package.unassigned_mention_ids,
                "agent_review_required": True,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return PromptDraftPaths(codex_path=codex_path, claude_path=claude_path, handoff_path=handoff_path)
