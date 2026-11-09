"""PowerShell command construction for the workbench."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Iterable, Mapping

from .job_spec import JobSpec
from .main_settings import review_evidence_root, review_work_root
from .metadata import (
    WORKFLOW_ARCHIVE_CATALOG,
    WORKFLOW_CODEX_EVIDENCE,
    WORKFLOW_FULL_REVIEW,
    WORKFLOW_REVIEW_NEW_VIDEOS,
    WORKFLOW_TRANSCRIPT_ONLY,
    normalize_workflow,
)
from .spelling_words import command_value as spelling_words_command_value


@dataclass(frozen=True, slots=True)
class CommandSpec:
    argv: list[str]
    preview: str


EVIDENCE_EFFECTIVE_COMMAND_FIELDS: tuple[tuple[str, str], ...] = (
    ("language", "Language"),
    ("narration_speech_mode", "NarrationSpeechMode"),
    ("evidence_render_density", "EvidenceRenderDensity"),
    ("evidence_frame_cadence_seconds", "EvidenceFrameCadenceSeconds"),
    ("evidence_max_frames_per_candidate", "EvidenceMaxFramesPerCandidate"),
    ("evidence_profile_setup_name", "EvidenceProfileSetupName"),
)


def _format_number(value: float | int) -> str:
    numeric = float(value)
    if numeric.is_integer():
        return str(int(numeric))
    return str(numeric)


def quote_for_powershell(value: str) -> str:
    """Return a display-only PowerShell single-quoted string."""

    return "'" + value.replace("'", "''") + "'"


def _preview_token(token: str, index: int) -> str:
    if index == 0:
        return token
    if token.startswith("-") and re.fullmatch(r"-[A-Za-z][A-Za-z0-9]*", token):
        return token
    return quote_for_powershell(token)


def build_preview(argv: Iterable[str]) -> str:
    return " ".join(_preview_token(token, index) for index, token in enumerate(argv))


def validate_effective_command(
    settings: Mapping[str, Any],
    command: CommandSpec,
    *,
    workflow: str | None = None,
) -> list[str]:
    """Return operator-facing errors when critical effective values differ from argv."""

    if normalize_workflow(workflow or settings.get("default_workflow")) != WORKFLOW_CODEX_EVIDENCE:
        return []
    errors: list[str] = []
    for setting_key, flag_name in EVIDENCE_EFFECTIVE_COMMAND_FIELDS:
        expected = settings.get(setting_key)
        flag = f"-{flag_name}"
        positions = [index for index, token in enumerate(command.argv) if token == flag]
        if _is_blank(expected):
            if positions:
                errors.append(f"{flag} is present even though the effective setting is blank.")
            continue
        expected_text = _format_value(expected)
        if len(positions) != 1:
            errors.append(f"{flag} must appear exactly once with effective value {expected_text}.")
            continue
        index = positions[0]
        actual = command.argv[index + 1] if index + 1 < len(command.argv) else "<missing>"
        if actual != expected_text:
            errors.append(f"{flag} is {actual}, but the effective setting is {expected_text}.")
    return errors


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple, set)):
        return len(value) == 0
    return False


def _is_false(value: Any) -> bool:
    if isinstance(value, bool):
        return not value
    if isinstance(value, str):
        return value.strip().lower() in {"", "0", "false", "no", "n", "off"}
    return not bool(value)


def _format_value(value: Any) -> str:
    if isinstance(value, float | int):
        return _format_number(value)
    return str(value)


def _split_values(value: Any) -> list[str]:
    if _is_blank(value):
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if "\n" in text or ";" in text:
        parts = re.split(r"[;\r\n]+", text)
        return [part.strip() for part in parts if part.strip()]
    return [text]


def _add_value(argv: list[str], flag: str, value: Any) -> None:
    if _is_blank(value):
        return
    argv.extend([f"-{flag}", _format_value(value)])


def _add_values(argv: list[str], flag: str, value: Any, *, comma_join: bool = False) -> None:
    values = _split_values(value)
    if not values:
        return
    argv.append(f"-{flag}")
    if comma_join:
        argv.append(",".join(values))
    else:
        argv.extend(values)


def _add_switch(argv: list[str], flag: str, value: Any) -> None:
    if not _is_false(value):
        argv.append(f"-{flag}")


def _add_bool_parameter(argv: list[str], flag: str, value: Any, *, default: bool) -> None:
    if _is_blank(value):
        resolved = default
    elif isinstance(value, str):
        resolved = value.strip().lower() not in {"0", "false", "no", "n", "off"}
    else:
        resolved = bool(value)
    argv.extend([f"-{flag}", "On" if resolved else "Off"])


def _base_argv(settings: Mapping[str, Any], powershell_exe: str) -> list[str]:
    repo_root = str(settings.get("repo_root") or "").strip()
    script_path = str(settings.get("script_path") or ".\\Video Mangler.ps1").strip()
    script = JobSpec(repo_root=repo_root, script_path=script_path, input_path="x", output_folder="x").resolved_script_path()
    argv = [
        powershell_exe,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        script,
    ]
    _add_value(argv, "PythonExe", settings.get("python_exe"))
    _add_value(argv, "FFmpegPath", settings.get("ffmpeg_path"))
    _add_value(argv, "FFprobePath", settings.get("ffprobe_path"))
    _add_value(argv, "YtDlpPath", settings.get("ytdlp_path"))
    return argv


def _add_shared_full_review_options(argv: list[str], settings: Mapping[str, Any]) -> None:
    _add_value(argv, "WhisperModel", settings.get("whisper_model"))
    _add_value(argv, "WhisperDevice", settings.get("whisper_device"))
    _add_value(argv, "ProcessingMode", settings.get("processing_mode"))
    _add_value(argv, "TranslationProvider", settings.get("translation_provider"))
    _add_value(argv, "OpenAiModel", settings.get("open_ai_model"))
    # 213: the OpenAI project only means something in AI or Hybrid mode; sent otherwise it is noise.
    if str(settings.get("processing_mode") or "").strip().lower() in {"ai", "hybrid"}:
        _add_value(argv, "OpenAiProject", settings.get("open_ai_project"))
    _add_value(argv, "Language", settings.get("language"))
    _add_value(argv, "TranslateTo", settings.get("translate_to"))
    _add_value(argv, "FrameIntervalSeconds", settings.get("frame_interval_seconds"))
    _add_value(argv, "FullReviewPanelCrops", settings.get("full_review_panel_crops"))
    _add_value(argv, "FullReviewPanelCropCadenceSeconds", settings.get("full_review_panel_crop_cadence_seconds"))
    _add_value(argv, "AiReviewZipPanelCropMode", settings.get("ai_review_zip_panel_crop_mode"))
    _add_value(argv, "TranscriptAudioMode", settings.get("transcript_audio_mode"))
    _add_value(argv, "TranscriptAudioStream", settings.get("transcript_audio_stream"))
    _add_value(argv, "TranscriptAudioTrackOrdinal", settings.get("transcript_audio_track_ordinal"))
    _add_value(
        argv,
        "PreferredTranscriptAudioTrackOrdinal",
        settings.get("preferred_transcript_audio_track_ordinal"),
    )
    _add_value(argv, "AiReviewZipMaxMb", settings.get("ai_review_zip_max_mb"))
    _add_switch(argv, "AudioTrackAudit", settings.get("audio_track_audit"))
    _add_switch(argv, "CopyRawVideo", settings.get("copy_raw_video"))
    _add_switch(argv, "IncludeComments", settings.get("include_comments"))
    _add_switch(argv, "CreateAiReviewZip", settings.get("create_ai_review_zip"))
    _add_switch(argv, "OpenOutputInExplorer", settings.get("open_output_in_explorer"))


def _add_spelling_words(argv: list[str], settings: Mapping[str, Any]) -> None:
    # 201: the whole list as one value; powershell -File binds only the first of several.
    _add_value(
        argv,
        "EvidenceTranscriptionGlossaryEntries",
        spelling_words_command_value(settings.get("evidence_transcription_glossary_entries")),
    )


def _add_evidence_options(argv: list[str], settings: Mapping[str, Any], *, include_whisper: bool = True) -> None:
    if include_whisper:
        _add_value(argv, "WhisperModel", settings.get("whisper_model"))
        _add_value(argv, "WhisperDevice", settings.get("whisper_device"))
    _add_value(argv, "Language", settings.get("language"))
    _add_value(argv, "NarrationSpeechMode", settings.get("narration_speech_mode"))
    _add_value(argv, "PreContextSeconds", settings.get("pre_context_seconds"))
    _add_value(argv, "PostContextSeconds", settings.get("post_context_seconds"))
    _add_value(argv, "NarrationContextPreSeconds", settings.get("narration_context_pre_seconds"))
    _add_value(argv, "NarrationContextPostSeconds", settings.get("narration_context_post_seconds"))
    _add_value(argv, "NarrationPauseThresholdSeconds", settings.get("narration_pause_threshold_seconds"))
    _add_bool_parameter(
        argv,
        "NarrationStopAtNextTicketBoundary",
        settings.get("narration_stop_at_next_ticket_boundary"),
        default=True,
    )
    _add_bool_parameter(
        argv,
        "FragmentedNarrationMode",
        settings.get("fragmented_narration_mode"),
        default=True,
    )
    _add_values(argv, "EvidenceFrameOffsets", settings.get("evidence_frame_offsets"), comma_join=True)
    _add_value(argv, "EvidenceAudioStreamIndex", settings.get("evidence_audio_stream_index"))
    # 196: Auto / Narration / Never narration per track, for recordings without track names.
    _add_value(argv, "EvidenceTrackRoles", settings.get("evidence_track_roles"))
    _add_value(
        argv,
        "EvidenceAudioStreamSelectionsJson",
        settings.get("evidence_audio_stream_selections_json"),
    )
    _add_switch(
        argv,
        "EvidenceAudioStreamSelectionConfirmed",
        settings.get("evidence_audio_stream_selection_confirmed"),
    )
    _add_switch(
        argv,
        "EvidencePreserveSupportingAudio",
        settings.get("evidence_preserve_supporting_audio"),
    )
    _add_value(argv, "EvidenceFrameCadenceSeconds", settings.get("evidence_frame_cadence_seconds"))
    _add_value(argv, "EvidenceMaxFramesPerCandidate", settings.get("evidence_max_frames_per_candidate"))
    _add_value(argv, "EvidenceMaxItems", settings.get("evidence_max_items"))
    _add_values(argv, "EvidenceRenderCandidateIds", settings.get("evidence_render_candidate_ids"), comma_join=True)
    _add_values(argv, "EvidenceRenderOutcomeIds", settings.get("evidence_render_outcome_ids"), comma_join=True)
    _add_value(argv, "EvidenceStopAfter", settings.get("evidence_stop_after"))
    _add_value(argv, "EvidenceRenderDensity", settings.get("evidence_render_density"))
    _add_value(argv, "EvidenceResumeRoot", settings.get("evidence_resume_root"))
    _add_value(argv, "EvidenceHandoffMode", settings.get("evidence_handoff_mode"))
    _add_value(argv, "EvidencePortableZipMaxMb", settings.get("evidence_portable_zip_max_mb"))
    _add_value(argv, "EvidencePanelCrops", settings.get("evidence_panel_crops"))
    _add_value(argv, "EvidenceRepoHintMode", settings.get("evidence_repo_hint_mode"))
    _add_value(argv, "EvidenceTargetRepo", settings.get("evidence_target_repo"))
    _add_value(argv, "EvidenceRepoMapPath", settings.get("evidence_repo_map_path"))
    _add_values(argv, "EvidenceCustomMarkers", settings.get("evidence_custom_markers"))
    _add_values(argv, "EvidenceCustomDomainTerms", settings.get("evidence_custom_domain_terms"))
    _add_value(
        argv,
        "EvidenceTranscriptionGlossaryPath",
        settings.get("evidence_transcription_glossary_path"),
    )
    _add_spelling_words(argv, settings)
    _add_value(argv, "EvidencePanelRoleMapPath", settings.get("evidence_panel_role_map_path"))
    _add_value(argv, "EvidenceTargetProject", settings.get("evidence_target_project"))
    _add_value(argv, "EvidenceApplicationVersion", settings.get("evidence_application_version"))
    _add_value(argv, "EvidenceProfileSetupName", settings.get("evidence_profile_setup_name"))
    _add_value(argv, "EvidenceDashboardRevision", settings.get("evidence_dashboard_revision"))
    _add_value(argv, "EvidenceTestConditions", settings.get("evidence_test_conditions"))
    _add_value(argv, "EvidenceConfigurationNotes", settings.get("evidence_configuration_notes"))


def _add_transcript_options(argv: list[str], settings: Mapping[str, Any]) -> None:
    _add_value(argv, "WhisperModel", settings.get("whisper_model"))
    _add_value(argv, "WhisperDevice", settings.get("whisper_device"))
    _add_switch(argv, "TranscriptOnlyRecurse", settings.get("transcript_only_recurse"))
    _add_switch(argv, "OverwriteTranscripts", settings.get("overwrite_transcripts"))
    _add_switch(argv, "SkipTranscriptOnlyAudio", settings.get("skip_transcript_only_audio"))
    # 214: the main language setting, and the track choice as Package any video for AI's: Auto
    # finds the narration track the shared way (track names, the main narration-track setting, voice
    # detection); a chosen track overrides it. The speech mode follows the track it finds.
    _add_value(argv, "Language", settings.get("language"))
    _add_value(argv, "TranscriptAudioMode", settings.get("transcript_audio_mode"))
    _add_value(argv, "TranscriptAudioStream", settings.get("transcript_audio_stream"))
    _add_value(argv, "TranscriptAudioTrackOrdinal", settings.get("transcript_audio_track_ordinal"))
    _add_value(argv, "EvidenceTrackRoles", settings.get("evidence_track_roles"))
    _add_values(argv, "TranscriptSearchTerms", settings.get("transcript_search_terms"))


def build_workflow_command(
    settings: Mapping[str, Any],
    *,
    workflow: str | None = None,
    powershell_exe: str = "powershell",
) -> CommandSpec:
    """Build a previewable PowerShell command for any Video Mangler workflow."""

    workflow_number = normalize_workflow(workflow or settings.get("default_workflow"))
    argv = _base_argv(settings, powershell_exe)
    input_value = str(settings.get("input_path") or "").strip()
    default_input_folder = str(settings.get("default_input_folder") or "").strip()
    local_input_value = input_value or default_input_folder
    output_folder = str(settings.get("output_folder") or "").strip()

    if workflow_number == WORKFLOW_FULL_REVIEW:
        if input_value:
            input_flag = "InputUrl" if str(settings.get("input_kind") or "local") == "url" else "InputPath"
            _add_value(argv, input_flag, input_value)
        elif default_input_folder and str(settings.get("input_kind") or "local") != "url":
            _add_value(argv, "InputPath", default_input_folder)
        _add_value(argv, "OutputFolder", output_folder)
        if settings.get("include_codex_evidence_package"):
            argv.append("-IncludeCodexEvidencePackage")
            _add_evidence_options(argv, settings, include_whisper=False)
        else:
            # 206: the shared engine's narration-track setting and words to spell right, which the
            # evidence options above carry when the evidence package is included.
            _add_value(argv, "EvidenceTrackRoles", settings.get("evidence_track_roles"))
            _add_spelling_words(argv, settings)
        _add_shared_full_review_options(argv, settings)
    elif workflow_number == WORKFLOW_TRANSCRIPT_ONLY:
        argv.append("-TranscriptOnly")
        _add_value(argv, "InputPath", local_input_value)
        _add_value(argv, "OutputFolder", output_folder)
        _add_transcript_options(argv, settings)
        _add_spelling_words(argv, settings)
        _add_switch(argv, "OpenOutputInExplorer", settings.get("open_output_in_explorer"))
    elif workflow_number == WORKFLOW_CODEX_EVIDENCE:
        argv.append("-CodexEvidencePackage")
        _add_value(argv, "InputPath", local_input_value)
        _add_value(argv, "OutputFolder", output_folder)
        _add_evidence_options(argv, settings)
        _add_switch(argv, "TranscriptOnlyRecurse", settings.get("transcript_only_recurse"))
        _add_switch(argv, "OverwriteTranscripts", settings.get("overwrite_transcripts"))
        _add_switch(argv, "OpenOutputInExplorer", settings.get("open_output_in_explorer"))
    elif workflow_number == WORKFLOW_ARCHIVE_CATALOG:
        if str(settings.get("archive_action") or "build").lower() == "search":
            argv.append("-ArchiveCatalogSearch")
            _add_values(argv, "ArchiveSearchTerms", settings.get("archive_search_terms"))
        else:
            argv.append("-ArchiveCatalog")
            _add_value(argv, "InputPath", local_input_value)
        _add_value(argv, "OutputFolder", output_folder)
        _add_value(argv, "ArchiveSkipMarker", settings.get("archive_skip_marker"))
        _add_value(argv, "ArchiveHashMode", settings.get("archive_hash_mode"))
        _add_value(argv, "ArchiveThumbnailMode", settings.get("archive_thumbnail_mode"))
        _add_value(argv, "ArchiveMaxThumbnailsPerVideo", settings.get("archive_max_thumbnails_per_video"))
        _add_value(argv, "ArchiveS3Bucket", settings.get("archive_s3_bucket"))
        _add_value(argv, "ArchiveS3Prefix", settings.get("archive_s3_prefix"))
        _add_value(argv, "ArchiveCatalogPath", settings.get("archive_catalog_path"))
        _add_value(argv, "ArchiveNotesCsv", settings.get("archive_notes_csv"))
        _add_switch(argv, "ArchiveExportNotesTemplate", settings.get("archive_export_notes_template"))
        _add_switch(argv, "OpenOutputInExplorer", settings.get("open_output_in_explorer"))
    elif workflow_number == WORKFLOW_REVIEW_NEW_VIDEOS:
        argv.append("-ReviewMediaInbox")
        _add_evidence_options(argv, settings)
        _add_value(argv, "ReviewInboxAction", settings.get("review_inbox_action") or "Scan")
        _add_value(
            argv,
            "ReviewInboxWorkload",
            settings.get("review_inbox_workload_mode") or "next_3",
        )
        _add_value(
            argv,
            "ReviewInboxNewSourceLimit",
            settings.get("review_inbox_new_source_limit"),
        )
        exact_source_paths = _split_values(
            settings.get("review_inbox_exact_source_paths")
        )
        _add_value(
            argv,
            "ReviewInboxExactSourcePathsJson",
            (
                json.dumps(
                    exact_source_paths,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                if exact_source_paths
                else ""
            ),
        )
        _add_value(
            argv,
            "ReviewInboxContinuation",
            settings.get("review_inbox_continuation"),
        )
        _add_value(
            argv,
            "ReviewInboxDecisionJson",
            settings.get("review_inbox_decision_json"),
        )
        _add_value(argv, "ReviewInboxResumeBatchId", settings.get("review_inbox_resume_batch_id"))
        _add_value(argv, "ReviewPreliminarySubmissionSha256", settings.get("review_preliminary_submission_sha256"))
        _add_value(argv, "ReviewResultsPath", settings.get("review_results_path"))
        _add_value(argv, "ReviewFinalizationPlanPath", settings.get("review_finalization_plan_path"))
        _add_value(argv, "ReviewFinalizationPlanSha256", settings.get("review_finalization_plan_sha256"))
        _add_switch(argv, "ReviewFinalizationConfirmed", settings.get("review_finalization_confirmed"))
        _add_values(argv, "ReviewSourceFolders", settings.get("review_source_folders"))
        # 214: a blank Inbox folder uses the main one.
        _add_value(argv, "ReviewEvidenceRoot", review_evidence_root(settings))
        _add_value(argv, "ReviewLocalWorkRoot", review_work_root(settings))
        # 224 (Wave B2b): the Inbox folder; its records are in the library. The old ledger setting is not passed.
        _add_value(argv, "ReviewInboxFolder", settings.get("review_inbox_folder"))
        _add_value(argv, "ReviewDedupeMode", settings.get("review_dedupe_mode") or "Fast")
        _add_value(argv, "ReviewInboxOrder", settings.get("review_inbox_order") or "oldest")
        _add_value(argv, "ReviewInboxMaxFiles", settings.get("review_inbox_max_files") or 3)
        _add_value(
            argv,
            "ReviewInboxMaxDurationMinutes",
            settings.get("review_inbox_max_duration_minutes") or 240,
        )
        _add_value(argv, "ReviewInboxConcurrency", 1)
        _add_value(
            argv,
            "ReviewInboxPendingBatchLimit",
            settings.get("review_inbox_pending_batch_limit") or 1,
        )
        _add_switch(argv, "ReviewNoRecurse", settings.get("review_no_recurse"))
        _add_switch(argv, "ReviewFullScanAcknowledged", settings.get("review_full_scan_acknowledged"))
        _add_value(
            argv,
            "ReviewAudioConfirmationsPath",
            settings.get("review_audio_confirmations_path"),
        )
        _add_value(
            argv,
            "ReviewStopAfterCurrentFilePath",
            settings.get("review_stop_after_current_file_path"),
        )
    else:
        raise ValueError(f"Unsupported Video Mangler workflow: {workflow_number}")

    # 114/115: skip/pause requests from the Workbench, and background priority.
    _add_value(argv, "RunControlPath", settings.get("run_control_path"))
    _add_switch(argv, "LowPriority", settings.get("run_low_priority", True))
    _add_switch(argv, "DebugMode", settings.get("debug_mode", True))
    argv.append("-NoPrompt")
    return CommandSpec(argv=argv, preview=build_preview(argv))


def build_codex_evidence_command(job: JobSpec, powershell_exe: str = "powershell") -> CommandSpec:
    job.validate()
    argv = [
        powershell_exe,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        job.resolved_script_path(),
        "-InputPath",
        job.input_path,
        "-OutputFolder",
        job.output_folder,
        "-CodexEvidencePackage",
        "-WhisperModel",
        job.whisper_model,
        "-Language",
        job.language,
        "-NarrationSpeechMode",
        job.narration_speech_mode,
        "-PreContextSeconds",
        _format_number(job.pre_context_seconds),
        "-PostContextSeconds",
        _format_number(job.post_context_seconds),
        "-EvidenceFrameCadenceSeconds",
        _format_number(job.evidence_frame_cadence_seconds),
        "-EvidenceMaxFramesPerCandidate",
        str(job.evidence_max_frames_per_candidate),
        "-EvidenceRenderDensity",
        job.evidence_render_density,
        "-EvidencePanelCrops",
        job.evidence_panel_crops,
        "-EvidenceRepoHintMode",
        job.evidence_repo_hint_mode,
    ]
    if job.evidence_target_repo:
        argv.extend(["-EvidenceTargetRepo", job.evidence_target_repo])
    if job.evidence_repo_map_path:
        argv.extend(["-EvidenceRepoMapPath", job.evidence_repo_map_path])
    if job.evidence_profile_setup_name:
        argv.extend(["-EvidenceProfileSetupName", job.evidence_profile_setup_name])
    if job.no_prompt:
        argv.append("-NoPrompt")
    argv.extend(job.extra_args)
    return CommandSpec(argv=argv, preview=build_preview(argv))
