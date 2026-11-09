"""The story and the editor's own review, short summary first (236, item 5).

The AI editor writes ``story.md`` and ``review.md`` in its own words. The brief asks it to start each
with "## In short" and, in the review, "## What changed" and "## Concerns"; the page shows those three
first and keeps the rest one click away. Files written before the brief asked for that are read by
their headings: "In one line" or "Outcome" is the summary, "What changed from v001" the changes, "Still
weak" or "Remaining limits" the concerns. Nothing is invented: a part the file does not have is "".
"""

from __future__ import annotations

import re
from typing import Any

SUMMARY_HEADINGS = ("in short", "in one line", "story in one line", "the story in one line", "summary", "outcome")
CHANGES_HEADINGS = ("what changed", "key changes", "changes", "revision")
CONCERNS_HEADINGS = ("concerns", "still weak", "what is weak", "weak", "problems", "remaining limits", "limits",
                     "sharing check")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def _words(heading: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", heading.casefold()).split())


def sections(text: str) -> tuple[str, str, list[tuple[str, str]]]:
    """``text`` split as the page reads it: its title (the first "#" heading), what comes before the first
    section, and each section as (heading, body). Deeper headings stay inside their section."""

    title, intro, found = "", [], []
    heading, body = None, []
    for line in str(text or "").splitlines():
        match = _HEADING.match(line)
        if match and len(match.group(1)) == 1 and not title and heading is None and not any(intro):
            title = match.group(2)
            continue
        if match and len(match.group(1)) == 2:
            if heading is not None:
                found.append((heading, "\n".join(body).strip()))
            heading, body = match.group(2), []
            continue
        (body if heading is not None else intro).append(line)
    if heading is not None:
        found.append((heading, "\n".join(body).strip()))
    return title, "\n".join(intro).strip(), found


def _first(found: list[tuple[str, str]], names: tuple[str, ...], used: set[int]) -> str:
    for index, (heading, body) in enumerate(found):
        words = _words(heading)
        if index not in used and body and any(words == name or words.startswith(name + " ") for name in names):
            used.add(index)
            return body
    return ""


def readable(text: str) -> dict[str, Any]:
    """The parts the page shows first: ``title``, ``summary``, ``changes`` and ``concerns`` (Markdown, ""
    when the file has none), and ``rest``: every other section as (heading, body), in order."""

    title, intro, found = sections(text)
    used: set[int] = set()
    summary = _first(found, SUMMARY_HEADINGS, used)
    if not summary and intro:
        summary = intro.split("\n\n", 1)[0].strip()
    changes = _first(found, CHANGES_HEADINGS, used)
    concerns = _first(found, CONCERNS_HEADINGS, used)
    rest = [part for index, part in enumerate(found) if index not in used]
    return {"title": title, "summary": summary, "changes": changes, "concerns": concerns, "rest": rest}
