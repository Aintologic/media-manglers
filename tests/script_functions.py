"""The text of one top-level function in ``Video Mangler.ps1``, for tests that check what a function says.

Slicing to the next ``function`` line made a test depend on which function happened to come next, so deleting
the last one broke it (224). This ends at the function's own closing brace instead: every top-level function
there closes with a ``}`` alone at the start of a line, and nothing inside one does except within a here-string,
which is skipped. ``tests/test_script_functions.py`` checks that against PowerShell's parser for every function.
"""

from __future__ import annotations

import re

_HERE_STRING_OPENS = re.compile(r"@([\"'])\s*$")
_CLOSES = re.compile(r"^\}[ \t]*$")


def function_text(script_text: str, name: str) -> str:
    """From ``function <name> {`` to its closing brace. ``script_text`` is the script read as text."""

    start = script_text.index(f"function {name} {{")
    lines = script_text[start:].splitlines(keepends=True)
    offset = start + len(lines[0])
    inside = None
    for line in lines[1:]:
        bare = line.rstrip("\r\n")
        opens = _HERE_STRING_OPENS.search(bare)
        if inside:
            if bare.startswith(inside):
                inside = None
        elif opens:
            inside = opens.group(1) + "@"
        elif _CLOSES.match(bare):
            return script_text[start:offset + len(bare)]
        offset += len(line)
    raise ValueError(f"function {name} has no closing brace")
