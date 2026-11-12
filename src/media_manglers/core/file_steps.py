"""The ``file-step`` command: new file steps through the one shared helper, ``safe_write`` (installer plan, Stage 2).

A program that is not Python, the installer's uninstaller or later the PowerShell backend, asks for a file step
here instead of doing it itself, so it follows the same rules: a wait measured by the clock (ten seconds per
file, thirty per step), the program holding a file named in plain words, a read-only file or the app's own
hold stopping at once, and nothing ever lost.

    python -m media_manglers file-step remove-addons [--result-file FILE]
    python -m media_manglers file-step run --request-file FILE [--result-file FILE]

``remove-addons`` removes the downloaded add-ons folder, which it takes from ``user_folders.addons_root()``
and from nowhere else. ``run`` carries out a list of steps, each with its own budget, and stops at the first
that does not succeed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from . import safe_write
from .user_folders import addons_root

STEP_KINDS = ("remove", "remove_tree", "move", "rename_into_place", "place_checked")


def remove_addons(*, budget: safe_write.StepBudget | None = None,
                  pause: Callable[[float], None] | None = None) -> dict[str, Any]:
    """Remove every downloaded add-on set, as the uninstaller does. Data, recordings and models are not here."""

    root = addons_root()
    if not os.path.lexists(root):
        return {"removed": False, "path": str(root),
                "message": "There were no downloaded add-ons to remove."}
    safe_write.remove_disposable_tree(root, within=root.parent, budget=budget or safe_write.StepBudget(),
                                      pause=pause)
    return {"removed": True, "path": str(root), "message": f"Removed the downloaded add-ons ({root})."}


def run_step(step: dict[str, Any], *, budget: safe_write.StepBudget | None = None,
             pause: Callable[[float], None] | None = None) -> dict[str, Any]:
    """Carry out one step. Each kind is a shared ``safe_write`` call; nothing here touches a file itself."""

    kind = str(step.get("op") or "")
    budget = budget or safe_write.StepBudget()
    if kind == "remove":
        safe_write.remove(Path(str(step["path"])), pause=pause, budget=budget)
    elif kind == "remove_tree":
        safe_write.remove_disposable_tree(Path(str(step["path"])), within=Path(str(step["within"])), pause=pause,
                                          budget=budget)
    elif kind == "move":
        safe_write.move(Path(str(step["from"])), Path(str(step["to"])), pause=pause, budget=budget)
    elif kind == "rename_into_place":
        safe_write.rename_into_place(Path(str(step["from"])), Path(str(step["to"])), pause=pause, budget=budget)
    elif kind == "place_checked":
        safe_write.place_checked(Path(str(step["from"])), Path(str(step["to"])), str(step["sha256"]),
                                 replace=bool(step.get("replace")), pause=pause, budget=budget)
    else:
        raise ValueError(f"Unknown file step {kind!r}; known steps are {', '.join(STEP_KINDS)}.")
    return {"op": kind, "ok": True}


def run_steps(steps: list[dict[str, Any]], *, pause: Callable[[float], None] | None = None) -> list[dict[str, Any]]:
    """Carry out ``steps`` in order, each with its own budget; the first that fails stops the rest."""

    return [run_step(step, pause=pause) for step in steps]


def holder_data(exc: safe_write.FileInUse) -> list[dict[str, Any]]:
    return [{"pid": holder.pid, "name": holder.name, "kind": holder.kind, "service": holder.service}
            for holder in exc.holders]
