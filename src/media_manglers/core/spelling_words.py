"""The operator's words to spell right, as one saved list (201).

One list feeds Whisper (as its hint of preferred words) and the transcript corrections. Each entry is
a word, optionally followed by how Whisper mishears it: "Brooklands=brook lands" or
"Crew Chief=crew chef|crewchief". It is kept as one text value, one entry per line; commas and
semicolons separate entries too.

226: the parser lives here, in core, so the packaged backend (which carries no Workbench code) and
the AI Video Editor's own commands read the list exactly as the Settings page does. The Workbench's
``spelling_words`` module offers the same function.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

SETTING_KEY = "evidence_transcription_glossary_entries"


def split_words(value: Any) -> list[str]:
    """Entries of the list, in order, each once (by the word before any "=")."""

    if value is None:
        return []
    parts: Iterable[Any] = value if isinstance(value, (list, tuple)) else [value]
    words: list[str] = []
    seen: set[str] = set()
    for part in parts:
        for piece in re.split(r"[,;\r\n]+", str(part or "")):
            entry = piece.strip()
            word = entry.partition("=")[0].strip().casefold()
            if entry and word and word not in seen:
                words.append(entry)
                seen.add(word)
    return words
