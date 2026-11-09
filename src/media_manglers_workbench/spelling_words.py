"""The operator's words to spell right, on the Settings page (201).

One list feeds Whisper (as its hint of preferred words) and the transcript corrections. Each
entry is a word, optionally followed by how Whisper mishears it: "Brooklands=brook lands" or
"Crew Chief=crew chef|crewchief". It is kept as one text value, one entry per line. Earlier
versions described the value as comma-separated, so commas and semicolons separate entries too.

The backend reads it as ``-EvidenceTranscriptionGlossaryEntries``. The whole list goes as one
value, joined with ";", because powershell -File binds only the first of several values.
"""

from __future__ import annotations

from typing import Any, Iterable

from media_manglers.core import spelling_words as _core_spelling_words

from .metadata import STARTER_SPELLING_WORDS

SETTING_KEY = _core_spelling_words.SETTING_KEY
# 226: the one parser lives in core, where the packaged backend and the AI Video Editor's commands
# can reach it (they carry no Workbench code); it is offered here unchanged.
split_words = _core_spelling_words.split_words


def join_words(words: Iterable[str]) -> str:
    return "\n".join(split_words(list(words)))


def with_starter_words(value: Any) -> str:
    """The saved list, kept as it is, with any starting word it lacks added at the end."""

    return join_words([*split_words(value), *STARTER_SPELLING_WORDS])


def command_value(value: Any) -> str:
    return ";".join(split_words(value))
