"""Where the helper's short-lived work files go (196).

The app follows the operating system's convention: work files go in the temp folder. When
``MEDIA_MANGLERS_SCRATCH_ROOT`` is set (the test suite sets it), they go under that folder
instead, including everything made through :mod:`tempfile`.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile

SCRATCH_ROOT_ENV = "MEDIA_MANGLERS_SCRATCH_ROOT"


def scratch_override() -> Path | None:
    """The folder ``MEDIA_MANGLERS_SCRATCH_ROOT`` names, or ``None`` when it is not set."""

    value = os.environ.get(SCRATCH_ROOT_ENV, "").strip()
    return Path(value) if value else None


def scratch_root() -> Path:
    """The folder for short-lived work files: the override when set, else the temp folder."""

    override = scratch_override()
    if override is None:
        return Path(tempfile.gettempdir())
    override.mkdir(parents=True, exist_ok=True)
    return override


def use_scratch_root() -> None:
    """Send this process's :mod:`tempfile` files under the override, when one is set."""

    override = scratch_override()
    if override is not None:
        override.mkdir(parents=True, exist_ok=True)
        tempfile.tempdir = str(override)
