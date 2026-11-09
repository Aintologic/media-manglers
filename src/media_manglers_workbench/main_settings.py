"""One main setting per shared job, and a feature's own value only as an override (214).

A feature that can follow a main setting says beside its own field whether it does: "Using main
setting" or "Overridden". This module holds that rule for every screen, and the values the run
really uses.

- Package any video for AI's track choice follows the main narration-track setting (Settings >
  General) while it is Auto with no track forced; choosing a track overrides it.
- Review Media Inbox's evidence folder follows the main output folder, and its scratch / work folder
  follows the app's temporary folder, while left blank (or set to that same folder).
- The AI Video Editor's track boxes follow the Track roles setting on Auto; its quick passes follow
  the main Whisper model on "Use main setting"; a video's export quality follows Settings > AI Video
  Editor until that video chooses its own (226).
"""

from __future__ import annotations

import os
from typing import Any, Mapping

USING_MAIN_SETTING = "Using main setting"
OVERRIDDEN = "Overridden"


def _same_folder(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return os.path.normcase(os.path.normpath(left)) == os.path.normcase(os.path.normpath(right))


def folder_state(own: Any, main: Any) -> str:
    """Whether a feature's own folder follows the main one: blank, or that same folder."""

    own_text = str(own or "").strip()
    return USING_MAIN_SETTING if not own_text or _same_folder(own_text, str(main or "").strip()) else OVERRIDDEN


def main_temp_folder(settings: Mapping[str, Any]) -> str:
    """The app's temporary folder: the setting, or the app's own default."""

    from .settings import default_temp_folder

    return str(settings.get("temp_folder") or "").strip() or str(default_temp_folder())


def review_evidence_root(settings: Mapping[str, Any]) -> str:
    """The Inbox's evidence folder as the run uses it: its own, or the main output folder.

    The main output folder is Settings' Default output folder (``main_output_folder``, which the
    Workbench adds), never what the New Review wizard's output field holds at the moment."""

    main = settings.get("main_output_folder") if "main_output_folder" in settings else settings.get("output_folder")
    return str(settings.get("review_evidence_root") or "").strip() or str(main or "").strip()


def run_output_folder(
    settings: Mapping[str, Any],
    *,
    inbox: bool = False,
    result: Mapping[str, Any] | None = None,
) -> str:
    """214: the one answer to "where did this run write?", for every feature.

    ``settings`` is the run's own snapshot, taken when it started, never what a page shows now. For
    every feature but Review Media Inbox it is the run's output folder. For the Inbox it is where
    that Inbox run writes: what its result says (``queue_root``, or ``batch_path`` for a single
    batch) once it has said it; before that, Process and Prepare keep their queue and batches in the
    Inbox folder (``review_inbox_folder``, 224 F9), and anything else writes in the effective evidence
    folder."""

    if not inbox:
        return str(settings.get("output_folder") or "").strip()
    reported = result or {}
    written = str(reported.get("queue_root") or reported.get("batch_path") or "").strip()
    if written:
        return written
    action = str(settings.get("review_inbox_action") or "").strip()
    evidence = review_evidence_root(settings)
    folder = str(settings.get("review_inbox_folder") or "").strip()
    if action in ("Process", "Prepare") and folder:
        # 224 (Wave B2b): the Inbox folder itself.
        return os.path.normpath(folder)
    if action == "Prepare" and evidence:
        return os.path.join(evidence, "review-inbox")
    return evidence


def review_work_root(settings: Mapping[str, Any]) -> str:
    """The Inbox's scratch / work folder as the run uses it: its own, or the app's temporary folder."""

    return str(settings.get("review_local_work_root") or "").strip() or main_temp_folder(settings)


def track_choice_state(mode: Any, track_number: Any = 0) -> str:
    """Package any video for AI follows the main narration-track setting only on Auto with no
    track forced. 226: so do the AI Video Editor's voice and game-sound boxes (Auto, or a track
    picked for one recording)."""

    try:
        number = int(track_number or 0)
    except (TypeError, ValueError):
        number = 0
    return USING_MAIN_SETTING if str(mode or "Auto").strip() == "Auto" and number == 0 else OVERRIDDEN


def quick_passes_state(quick: Any, main_model: Any) -> str:
    """226 (decision C): the AI Video Editor's quick passes follow the main Whisper model on "main"
    (Use main setting), or while their own model is that same model; Whisper small beside another
    main model overrides it."""

    from media_manglers.core.race_video.requests import QUICK_MODEL_DEFAULT, QUICK_MODEL_MAIN
    from media_manglers.core.whisper_options import DEFAULT_MODEL

    chosen = str(quick or "").strip().casefold() or QUICK_MODEL_DEFAULT
    if chosen == QUICK_MODEL_MAIN:
        return USING_MAIN_SETTING
    main = str(main_model or "").strip().casefold() or DEFAULT_MODEL
    return USING_MAIN_SETTING if chosen == main else OVERRIDDEN


def project_choice_state(own: Any) -> str:
    """226: a choice one project keeps for itself (the AI Video Editor's export quality for one
    video) overrides the main setting; without one, the project follows it."""

    return OVERRIDDEN if str(own or "").strip() else USING_MAIN_SETTING


def main_folder_text(path: str) -> str:
    """How a main folder is shown beside a field that follows it."""

    return f"{USING_MAIN_SETTING} ({path})" if path else USING_MAIN_SETTING

