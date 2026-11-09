"""The prompt that hands a project to the operator's AI editor (150 Phase 2).

The Workbench never calls an AI service. It writes a prompt the operator pastes into Claude Code or
Codex. The prompt starts with the model, effort and mode to use (the operator can still change them in
the tool), chosen by the project's budget, and gives full paths only.

226: it also names the ``editor_label`` the AI editor passes when it adds a version: its tool and
model, cleaned the way the project keeps it ("claude-opus-5.5").

236: the prompt sends the editor to the brief's "Working with the operator" first: a plan in plain words,
whether it will wait for changes, progress in plain words, and a hand-over that ends with the next steps
in the app, in the app's own words (``APP_LABELS``, which the page's buttons use too, so the two cannot
drift apart), with the technical detail kept in ``technical.md``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .project import clean_editor_label

BRIEF = Path(__file__).with_name("brief.md")


def brief_path(src_root: Path) -> Path:
    """The brief beside the commands the editor runs. In the packaged app the Workbench itself is a
    bundle without the brief; the copy the editor can read is in the Python core it runs."""

    beside_commands = src_root / "media_manglers" / "core" / "race_video" / "brief.md"
    return beside_commands if beside_commands.is_file() else BRIEF

# Budget -> (Claude Code effort, Codex effort). The editor's judgment needs the top model either way.
STAMPS = {
    "light": ("high", "medium"),
    "standard": ("xhigh", "high"),
    "thorough": ("ultracode", "xhigh"),
}
# The defaults only: the operator keeps the names current in Settings > AI Video Editor (174), because
# the tools rename their models every few months.
MODELS = {"claude": "Opus 5.5", "codex": "GPT-6.1 Sol"}
# 236 (item 4g): the AI Video Editor page's own words, which the brief tells the editor to use when it
# hands over. The page builds its buttons from these, and a test checks the brief says them all.
APP_LABELS = {
    "page": "AI Video Editor",
    "videos": "Your videos",
    "continue": "Continue:",
    # The video's toolbar (236 fix round: labelled buttons, each opening a small panel, instead of a ⋯ menu).
    "settings_tool": "Video settings",
    "prompt_tool": "Prompt",
    "story_tool": "Story & review",
    "files_tool": "Files",
    "refresh": "Refresh",
    "fresh": "Start a fresh edit",
    # The play choices on the picture: the preview alone, or the final with the preview beside it.
    "play": "Play the preview",
    "play_final": "Play the final (full quality)",
    "notes": "What should change?",
    "save_notes_claude": "Save notes, copy prompt for Claude Code",
    "save_notes_codex": "…for Codex",
    "approve": "Approve and export…",
    "render": "Render a preview",
}


def editor_label_for(tool: str, model: str = "") -> str:
    """The ``editor_label`` an AI editor passes with each version it adds (226): the tool and the model
    the prompt names, as the project keeps it, for example "claude-opus-5.5"."""

    return clean_editor_label(f"{tool} {model.strip() or MODELS.get(tool, '')}")


def build_prompt(project: Path, *, tool: str, python: str, src_root: Path, feedback_version: int | None = None,
                 model: str = "", scenes: list[str] | None = None) -> str:
    """The prompt for ``tool``. ``scenes`` (236): for a revision, the scenes of the strip the operator's
    notes are about, as the notes file names them ("Pit stop: scenes s07, s08, from 2:15 to 2:45")."""

    if tool not in MODELS:
        raise ValueError("tool must be 'claude' or 'codex'")
    analysis = json.loads((project / "analysis" / "analysis.json").read_text(encoding="utf-8"))
    budget = analysis["settings"]["budget"]
    effort = STAMPS[budget][0 if tool == "claude" else 1]
    meta = json.loads((project / "project.json").read_text(encoding="utf-8"))
    command = f'"{python}" -c "import sys; sys.path.insert(0, r\'{src_root}\'); from media_manglers.cli import main; sys.exit(main(sys.argv[1:]))"'
    lines = [
        f"MODEL: {model.strip() or MODELS[tool]}",
        f"EFFORT: {effort}",
        "MODE: AUTO — execute to completion",
        "",
        "You are the editor for a race video. Read your brief first, completely, and follow it:",
        f"{brief_path(src_root)}",
        "",
        f"Project folder: {project}",
        f"Recording: {meta['source']}",
        f"Start with: {project / 'analysis' / 'digest.md'}",
        f"Budget: {budget} (close looks and review rounds are capped; the commands tell you when you reach the cap).",
        "",
        "Run Media Manglers commands like this (one request file in, one result file out):",
        f"{command} <command> --request-file <request.json> --result-file <result.json>",
        "",
        f'Each time you store a version with race-video-add-version, pass "editor_label": '
        f'"{editor_label_for(tool, model)}" (your tool and model).',
        "",
        'Talk to the operator as the brief\'s "Working with the operator" says: first, in plain words, the story you '
        "plan to tell and whether you will wait for their changes before you cut; then progress in plain words; at the "
        "end the result and the next steps in the app, in the app's own words. Technical detail goes in technical.md "
        "in the version folder, not in your messages.",
    ]
    if feedback_version is not None:
        notes = project / "feedback" / f"v{feedback_version:03d}.md"
        lines += [
            "",
            f"This is a revision. The operator watched version {feedback_version} and wrote: {notes}",
            "Start by saying in plain words what you will change to answer those notes, and anything in them you cannot "
            "do or that conflicts with the brief.",
            f"Make a new version with parent {feedback_version} that answers those notes, review it, and hand it over.",
        ]
        if scenes:
            lines += ["", f"The operator's notes name these scenes of version {feedback_version} (from the story strip "
                          "under the player):", *(f"- {scene}" for scene in scenes)]
    elif meta.get("versions"):
        latest = max(v["version"] for v in meta["versions"])
        lines += ["", f"This edit already has versions up to v{latest:03d}, made earlier. If you were asked to make your "
                      f"own, separate edit, stop and tell the operator to press {APP_LABELS['prompt_tool']}, then "
                      f"{APP_LABELS['fresh']}, on the video's {APP_LABELS['page']} page. Otherwise build on "
                      f"v{latest:03d}, review, revise, and hand it over."]
    else:
        lines += ["", "Make the first version, review it yourself, revise it, and hand it over."]
    lines += ["", "Do not upload, publish, or render the final: the operator approves with "
                  f"{APP_LABELS['approve']} in the app, which makes it."]
    return "\n".join(lines) + "\n"


def describe(project: Path, models: dict[str, str] | None = None) -> dict[str, Any]:
    analysis = json.loads((project / "analysis" / "analysis.json").read_text(encoding="utf-8"))
    budget = analysis["settings"]["budget"]
    chosen = {tool: (models or {}).get(tool) or default for tool, default in MODELS.items()}
    return {"budget": budget,
            "claude": {"model": chosen["claude"], "effort": STAMPS[budget][0],
                       "editor_label": editor_label_for("claude", chosen["claude"])},
            "codex": {"model": chosen["codex"], "effort": STAMPS[budget][1],
                      "editor_label": editor_label_for("codex", chosen["codex"])}}
