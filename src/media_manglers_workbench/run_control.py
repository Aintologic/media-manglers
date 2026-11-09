"""Skip and pause requests from the Workbench to a running backend (114, 115).

The Workbench writes a small JSON file next to the run's output; the
PowerShell backend reads it about once a second::

    {"pause": false, "skip": ["<full path to a recording>"]}

Skipping stops work on that recording at once (the running tool is ended,
with no slow CPU retry). Pausing suspends the running tool so the PC is free
until Resume. The file is replaced atomically so the backend never reads a
half-written request.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import time

REPLACE_ATTEMPTS = 20
REPLACE_PAUSE_SECONDS = 0.025


class RunControl:
    """The operator's skip/pause requests for one run."""

    FILE_NAME = "run-control.json"

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.paused = False
        self.skipped: list[str] = []

    @classmethod
    def for_folder(cls, folder: Path) -> "RunControl":
        control = cls(Path(folder) / cls.FILE_NAME)
        control.write()
        return control

    def is_skipped(self, source: str | Path) -> bool:
        key = os.path.normcase(str(source))
        return any(os.path.normcase(item) == key for item in self.skipped)

    def skip(self, sources: list[str | Path]) -> list[str]:
        """Ask the backend to skip these recordings; returns the new ones."""

        added = []
        for source in sources:
            text = str(source)
            if text and not self.is_skipped(text):
                self.skipped.append(text)
                added.append(text)
        if added:
            self.write()
        return added

    def set_paused(self, paused: bool) -> None:
        self.paused = bool(paused)
        self.write()

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"pause": self.paused, "skip": list(self.skipped)}
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        # 227: Windows refuses to replace a file the reader has open at that very moment, so the
        # replace is tried again for up to half a second before it gives up.
        for attempt in range(REPLACE_ATTEMPTS):
            try:
                os.replace(temporary, self.path)
                return
            except PermissionError:
                if attempt == REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(REPLACE_PAUSE_SECONDS)
