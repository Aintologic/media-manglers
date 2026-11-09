"""Package README writers for tracked Media Manglers artifact steps."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _coerce_text(value: Any, default: str = "") -> str:
    text = "" if value is None else str(value)
    return default if not text.strip() else text


def _coerce_targets(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]

    targets: list[str] = []
    for item in value:
        text = _coerce_text(item)
        if text:
            targets.append(text)
    return targets


def _join_lines(lines: list[str]) -> str:
    return "\n".join(lines) + "\n"


def build_video_package_readme(payload: dict[str, Any]) -> str:
    video_file_name = _coerce_text(payload.get("video_file_name"))
    raw_present = _coerce_text(payload.get("raw_present"))
    audio_present = _coerce_text(payload.get("audio_present"))
    frame_interval_display = _coerce_text(payload.get("frame_interval_display"))
    frames_folder_name = _coerce_text(payload.get("frames_folder_name"))
    processing_mode_summary = _coerce_text(payload.get("processing_mode_summary"), "Local")
    openai_project_summary = _coerce_text(
        payload.get("openai_project_summary"),
        "not applicable (Local mode)",
    )
    transcription_path_details = _coerce_text(
        payload.get("transcription_path_details"),
        "none",
    )
    detected_language = _coerce_text(payload.get("detected_language"), "not available")
    remote_audio_track_summary = _coerce_text(
        payload.get("remote_audio_track_summary"),
        "not applicable (local source or provider metadata unavailable)",
    )
    translation_targets = _coerce_targets(payload.get("translation_targets"))
    translation_status = _coerce_text(payload.get("translation_status"), "not requested")
    translation_path_details = _coerce_text(
        payload.get("translation_path_details"),
        "none",
    )
    translation_notes = _coerce_text(payload.get("translation_notes"), "none")
    next_steps = _coerce_text(payload.get("next_steps"), "none")
    comments_summary = _coerce_text(payload.get("comments_summary"), "not included")
    package_status = _coerce_text(payload.get("package_status"), "SUCCESS")
    panel_frames_summary = _coerce_text(payload.get("panel_frames_summary"), "not evaluated")
    panel_frames_path = _coerce_text(payload.get("panel_frames_path"), "not created")
    panel_frame_index_path = _coerce_text(payload.get("panel_frame_index_path"), "not created")
    transcript_source_summary = _coerce_text(payload.get("transcript_source_summary"), "not available")
    transcript_source_metadata_path = _coerce_text(
        payload.get("transcript_source_metadata_path"),
        "not available",
    )
    transcript_source_manifest_path = _coerce_text(
        payload.get("transcript_source_manifest_path"),
        "not available",
    )
    all_audio_tracks_transcript_path = _coerce_text(
        payload.get("all_audio_tracks_transcript_path"),
        "not available",
    )
    all_audio_tracks_index_path = _coerce_text(
        payload.get("all_audio_tracks_index_path"),
        "not available",
    )
    all_audio_tracks_manifest_path = _coerce_text(
        payload.get("all_audio_tracks_manifest_path"),
        "not available",
    )

    return _join_lines(
        [
            "README_FOR_CODEX",
            "",
            "This folder contains a Video Mangler review package for:",
            video_file_name,
            "",
            "What is included:",
            "- raw\\                            original source video (only if you chose to keep a copy)",
            "- proxy\\review_proxy_1280.mp4     review copy for playback",
            f"- {frames_folder_name}\\frame_000001.jpg ...",
            "- audio\\audio.mp3                 only when the source has spoken audio",
            "- audio\\audio_tracks.json / .csv  detected audio track inventory",
            "- audio\\transcript_source_manifest.json all-track extraction/transcript manifest when all tracks are transcribed",
            "- transcript\\transcript.srt / .json / .txt",
            "- transcript\\tracks\\              per-track transcript files when multiple audio tracks are present",
            "- transcript\\all_audio_tracks_transcript.md combined all-track transcript handoff when present",
            "- transcript\\all_audio_tracks_index.csv and all_audio_tracks_manifest.json all-track transcript index and manifest when present",
            "- translations\\<lang>\\transcript.srt / .json / .txt when translation was requested",
            "- comments\\comments.txt / .json   public comments export when available and requested",
            "- frame_index.csv                 timestamp index for the extracted frames",
            "- frames_panels\\                  high-detail 1920x1080 panel crops when an exact 5760x1080 source was detected",
            "- audio\\transcript_source.wav      selected single audio source used for transcription in Mixed/Track mode",
            "- audio\\transcript_source_metadata.json selected single-stream reuse-guard metadata in Mixed/Track mode",
            "- script_run.log                  processing log, including raw OpenAI error details when available",
            "",
            "A good review order:",
            "1. Start with transcript\\transcript.txt when audio is present.",
            "2. Watch proxy\\review_proxy_1280.mp4 for pacing, sequence, and spoken context.",
            "3. Use frame_index.csv to map timestamps to the extracted frames.",
            "4. Check translations\\<lang>\\ if you asked for translated text.",
            "5. Check comments\\ if public source comments were included for context.",
            "6. Use raw video only if the derived review assets are not enough.",
            "",
            "Notes:",
            f"- Package status: {'partial success' if package_status == 'PARTIAL_SUCCESS' else 'success'}",
            f"- Selected frame interval: {frame_interval_display} seconds",
            f"- Frames folder: {frames_folder_name}",
            f"- Raw video present: {raw_present}",
            f"- Audio present in source: {audio_present}",
            f"- Processing mode used: {processing_mode_summary}",
            f"- AI project mode: {openai_project_summary}",
            f"- Transcription path used: {transcription_path_details}",
            f"- Detected source language: {detected_language}",
            f"- Remote audio track selected: {remote_audio_track_summary}",
            f"- Translation targets: {', '.join(translation_targets) if translation_targets else 'none'}",
            f"- Translation status: {translation_status}",
            f"- Translation path used: {translation_path_details}",
            f"- Translation notes: {translation_notes}",
            f"- Next steps: {next_steps}",
            f"- Comments: {comments_summary}",
            f"- Full Review panel crops: {panel_frames_summary}",
            f"- Panel frames folder: {panel_frames_path}",
            f"- Panel frame index: {panel_frame_index_path}",
            f"- Transcript audio source: {transcript_source_summary}",
            f"- Transcript source metadata: {transcript_source_metadata_path}",
            f"- Transcript source manifest: {transcript_source_manifest_path}",
            f"- All audio tracks transcript: {all_audio_tracks_transcript_path}",
            f"- All audio tracks index: {all_audio_tracks_index_path}",
            f"- All audio tracks manifest: {all_audio_tracks_manifest_path}",
        ]
    )


def build_audio_package_readme(payload: dict[str, Any]) -> str:
    audio_file_name = _coerce_text(payload.get("audio_file_name"))
    raw_present = _coerce_text(payload.get("raw_present"))
    processing_mode_summary = _coerce_text(payload.get("processing_mode_summary"), "Local")
    openai_project_summary = _coerce_text(
        payload.get("openai_project_summary"),
        "not applicable (Local mode)",
    )
    transcription_path_details = _coerce_text(
        payload.get("transcription_path_details"),
        "none",
    )
    detected_language = _coerce_text(payload.get("detected_language"))
    translation_targets = _coerce_targets(payload.get("translation_targets"))
    translation_status = _coerce_text(payload.get("translation_status"), "not requested")
    translation_path_details = _coerce_text(
        payload.get("translation_path_details"),
        "none",
    )
    translation_notes = _coerce_text(payload.get("translation_notes"), "none")
    next_steps = _coerce_text(payload.get("next_steps"), "none")
    comments_summary = _coerce_text(payload.get("comments_summary"), "not included")
    package_status = _coerce_text(payload.get("package_status"), "SUCCESS")

    return _join_lines(
        [
            "README_FOR_CODEX",
            "",
            "This folder contains an Audio Mangler review package for:",
            audio_file_name,
            "",
            "What is included:",
            "- raw\\                            original source audio (only if you chose to keep a copy)",
            "- audio\\review_audio.mp3          clean listening copy for review",
            "- transcript\\transcript_original.srt / .json / .txt",
            "- translations\\<lang>\\transcript.srt / .json / .txt when translation was requested",
            "- comments\\comments.txt / .json   public comments export when available and requested",
            "- segment_index.csv               timestamp index for the original transcript",
            "- script_run.log                  processing log, including raw OpenAI error details when available",
            "",
            "A good review order:",
            "1. Start with transcript\\transcript_original.txt for the quick read.",
            "2. Use transcript\\transcript_original.srt or segment_index.csv when you need timestamps.",
            "3. Open translations\\<lang>\\ only if you asked for translated text.",
            "4. Use audio\\review_audio.mp3 when tone, pronunciation, or emphasis matters.",
            "5. Check comments\\ if public source comments were included for extra context.",
            "",
            "Notes:",
            f"- Package status: {'partial success' if package_status == 'PARTIAL_SUCCESS' else 'success'}",
            f"- Processing mode used: {processing_mode_summary}",
            f"- AI project mode: {openai_project_summary}",
            f"- Transcription path used: {transcription_path_details}",
            f"- Detected source language: {detected_language}",
            f"- Translation targets: {', '.join(translation_targets) if translation_targets else 'none'}",
            f"- Translation status: {translation_status}",
            f"- Translation path used: {translation_path_details}",
            f"- Translation notes: {translation_notes}",
            f"- Next steps: {next_steps}",
            f"- Comments: {comments_summary}",
            f"- Raw audio present: {raw_present}",
        ]
    )


def write_package_readme_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    readme_path = _coerce_text(payload.get("readme_path"))
    readme_kind = _coerce_text(payload.get("readme_kind")).lower()

    if not readme_path:
        raise ValueError("readme_path is required.")

    if readme_kind == "video":
        content = build_video_package_readme(payload)
    elif readme_kind == "audio":
        content = build_audio_package_readme(payload)
    else:
        raise ValueError("readme_kind must be 'video' or 'audio'.")

    destination = Path(readme_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8-sig")

    return {
        "readme_kind": readme_kind,
        "readme_path": str(destination),
        "line_count": len(content.replace("\r\n", "\n").split("\n")),
    }
