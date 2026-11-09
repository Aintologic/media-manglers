"""One Whisper settings rule: what every transcription asks Whisper for, from the main settings (226).

The operator sets the Whisper model, the Whisper device (Auto, CPU or GPU), the source language and
the narration speech mode once, in the Workbench's Settings. ``from_settings`` turns them into the
four fields of a Whisper request (``model_name``, ``prefer_gpu``, ``language_code``,
``narration_speech_mode``), so the raw bin, the Inbox and the AI Video Editor ask for the same thing.

- The graphics card is asked for unless the device is CPU; Whisper falls back to the CPU itself.
- A blank (or "auto") language means English, and Auto speech mode means Sparse, as the backend's
  ``Resolve-MMNarrationTranscriptionDefaults`` does for narrated recordings: left to guess, Whisper has
  written a quiet opening down as Welsh or Nynorsk.
- A request the backend already worked out (the Inbox's, ``resolved=True``) is taken as it is: the
  backend has applied that rule and turned the device into ``prefer_gpu``. The PowerShell copy of the
  rule stays on the known-copies list.

``words`` gives the "Words to spell right" list as Whisper's hint and as the corrections, the way
features 1 and 2 build them. ``read_saved_settings`` reads the saved settings for a command the
Workbench did not hand them to, read only.

Core only: the packaged backend carries no Workbench code, so nothing here imports it.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from .spelling_words import SETTING_KEY as SPELLING_WORDS_KEY, split_words
from .transcript_corrections import build_whisper_initial_prompt, normalize_glossary_entries
from .user_folders import workbench_settings_file

# The Workbench's own default model (Settings > Whisper model).
DEFAULT_MODEL = "medium"


def read_saved_settings() -> dict[str, Any]:
    """The operator's saved Workbench settings, read only; {} when there are none or they cannot be read.

    Found the way the output-folder rule finds them (``user_folders.workbench_settings_file``), so a test
    or a build that points MEDIA_MANGLERS_WORKBENCH_APPDATA elsewhere never reads the real ones.
    """

    try:
        saved = json.loads(workbench_settings_file().read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    if not isinstance(saved, dict):
        return {}
    # As the Workbench loads them: the "settings" block, or an old file that is only that block.
    settings = saved.get("settings") if "settings" in saved else saved
    return dict(settings) if isinstance(settings, dict) else {}


def _is_blank_or_auto(value: str) -> bool:
    return value.strip().casefold() in ("", "auto")


def from_settings(
    settings: Mapping[str, Any] | None,
    *,
    default_model: str = DEFAULT_MODEL,
    resolved: bool = False,
) -> dict[str, Any]:
    """The Whisper request fields for these settings: model_name, prefer_gpu, language_code and
    narration_speech_mode.

    ``settings`` are the Workbench's (``whisper_model``, ``whisper_device``, ``language``,
    ``narration_speech_mode``). With ``resolved`` they are a request the backend already worked out
    (``whisper_model``, ``prefer_gpu``, ``language_code``, ``narration_speech_mode``), used as given.
    ``default_model`` is the model when none is set: the Workbench's "medium", or the backend's
    "base.en" for the Inbox.
    """

    values = settings or {}
    model_name = str(values.get("whisper_model") or default_model)
    if resolved:
        return {
            "model_name": model_name,
            "prefer_gpu": bool(values.get("prefer_gpu", True)),
            "language_code": str(values.get("language_code") or ""),
            "narration_speech_mode": str(values.get("narration_speech_mode") or "Auto"),
        }
    language_code = str(values.get("language") or "")
    speech_mode = str(values.get("narration_speech_mode") or "Auto")
    return {
        "model_name": model_name,
        "prefer_gpu": str(values.get("whisper_device") or "Auto") != "CPU",
        "language_code": "en" if _is_blank_or_auto(language_code) else language_code,
        "narration_speech_mode": "Sparse" if _is_blank_or_auto(speech_mode) else speech_mode,
    }


def words(settings: Mapping[str, Any] | None) -> tuple[str, list[str]]:
    """The "Words to spell right" setting as ``(initial_prompt, glossary_entries)``.

    The entries are the list as the Settings page reads it; the prompt is Whisper's hint of preferred
    words, "Preferred terminology: A, B", from the word before each "=" of the operator's own list only,
    as features 1 and 2 build it (``Get-EvidenceTranscriptionInitialPrompt``). "" and [] without words.
    """

    entries = split_words((settings or {}).get(SPELLING_WORDS_KEY))
    prompt = build_whisper_initial_prompt(normalize_glossary_entries(entries, default_scope="profile"))
    return prompt, entries
