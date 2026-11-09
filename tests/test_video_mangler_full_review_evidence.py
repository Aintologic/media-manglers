from __future__ import annotations

from pathlib import Path
import unittest


class VideoManglerFullReviewEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script_text = (Path(__file__).resolve().parents[1] / "Video Mangler.ps1").read_text(encoding="utf-8")

    def test_full_review_prompt_defaults_to_include_codex_evidence(self) -> None:
        self.assertIn(
            "Include Codex evidence package / ticket-capture evidence in this full review? [Y/n] (default: Y, auto-selects",
            self.script_text,
        )
        prompt_function = self._function_body("Get-InteractiveFullReviewCodexEvidenceInclusion")
        self.assertIn("interactive default yes", prompt_function)
        self.assertRegex(prompt_function, r"Include\s*=\s*\$true")

    def test_full_review_can_disable_codex_evidence(self) -> None:
        prompt_function = self._function_body("Get-InteractiveFullReviewCodexEvidenceInclusion")
        self.assertIn("interactive no", prompt_function)
        self.assertRegex(prompt_function, r"Include\s*=\s*\$false")
        self.assertIn("[switch]$SkipCodexEvidencePackage", self.script_text)
        self.assertIn("explicit skip", self.script_text)

    def test_standalone_codex_evidence_workflow_still_uses_existing_batch(self) -> None:
        self.assertIn("[switch]$CodexEvidencePackage", self.script_text)
        self.assertIn("3. Codex evidence package / ticket capture mode", self.script_text)
        self.assertIn("if ($CodexEvidencePackage)", self.script_text)
        self.assertIn("-InvocationMode \"standalone\"", self.script_text)
        self.assertGreaterEqual(self.script_text.count("Invoke-CodexEvidencePackageBatch `"), 2)

    def test_full_review_addon_uses_existing_batch_and_records_manifest(self) -> None:
        self.assertIn("[switch]$IncludeCodexEvidencePackage", self.script_text)
        self.assertIn("-InvocationMode \"full-review-addon\"", self.script_text)
        self.assertIn("FULL_REVIEW_RUN_MANIFEST.json", self.script_text)
        self.assertIn("Remote URL Full Review inputs are supported", self.script_text)
        self.assertIn("New-FullReviewRunManifest", self.script_text)

    def test_full_review_addon_invokes_evidence_per_processed_video_folder(self) -> None:
        loop_region = self._script_region("$fullReviewEvidenceWhisperModel = $WhisperModel", "New-FullReviewRunManifest")
        self.assertIn("-InputPath $video.FullName", loop_region)
        self.assertIn("-OutputFolder $result.OutputPath", loop_region)
        self.assertIn("Set-FullReviewCodexEvidenceMetadata", loop_region)
        self.assertIn("New-AiReviewArtifacts", loop_region)
        self.assertNotIn("-OutputFolder $OutputFolder `", loop_region)
        self.assertIn("-ExistingTranscriptJsonPath $result.TranscriptJsonPath", loop_region)
        self.assertIn("-ExistingAudioPath $result.TranscriptSourceWav", loop_region)
        self.assertIn("full_review_all_tracks", loop_region)

    def test_all_track_review_mix_is_effective_downstream_audio_source(self) -> None:
        process_region = self._function_body("Process-Video")
        self.assertIn("Effective transcript audio source for downstream phases", process_region)
        self.assertIn("$transcriptSourceWav = [string]$audioPhaseResult.AllTracksReviewMixWav", process_region)
        self.assertIn("Local Whisper audio translation needs the effective transcript audio source", process_region)
        self.assertIn("TranscriptJsonPath = $transcriptJson", process_region)

    def test_full_review_ai_review_files_and_root_manifest_are_per_video(self) -> None:
        self.assertIn("AI_REVIEW_MANIFEST.json", self.script_text)
        self.assertIn("AI_REVIEW_README.md", self.script_text)
        manifest_function = self._function_body("New-FullReviewRunManifest")
        self.assertIn("processed_videos", manifest_function)
        self.assertIn("failed_videos", manifest_function)
        self.assertIn("evidence_coverage_matrix", manifest_function)
        self.assertIn("ai_review_manifest_path", manifest_function)
        self.assertIn("ai_review_readme_path", manifest_function)
        self.assertIn("codex_evidence_package", manifest_function)
        self.assertIn("scope\"] = \"per-video\"", manifest_function)
        master_readme_function = self._function_body("New-MasterReadme")
        self.assertIn("AI review README", master_readme_function)
        self.assertIn("AI / ticket evidence folder", master_readme_function)
        self.assertIn("Evidence coverage matrix CSV", master_readme_function)

    def test_full_review_writes_agent_neutral_portable_entry_points(self) -> None:
        artifact_function = self._function_body("New-AiReviewArtifacts")
        self.assertIn("README_FOR_AI.md", artifact_function)
        self.assertIn("AI_PACKAGE_MANIFEST.json", artifact_function)
        self.assertIn('path_mode = "package_relative"', artifact_function)
        self.assertIn("path_hash_or_safe_id", artifact_function)
        self.assertIn("Instructions for an AI agent", artifact_function)
        manifest_function = self._function_body("New-FullReviewRunManifest")
        self.assertIn('output_root  = "."', manifest_function)
        self.assertIn("media-manglers-ai-collection-v1", manifest_function)
        master_function = self._function_body("New-MasterReadme")
        self.assertIn("# AI Review Collection", master_function)
        self.assertIn("may be moved to another folder or drive", master_function)
        self.assertIn(
            "Get-PortableDiagnosticText -Message ([string]$item.TranscriptAudioSelection)",
            master_function,
        )

    def test_multi_url_download_failures_continue_and_report_each_source(self) -> None:
        resolver = self._function_body("Resolve-RequestedInputSources")
        self.assertIn("Get-HttpUrlsFromText", resolver)
        self.assertIn("HashSet[string]", resolver)
        self.assertIn("Resolve-RequestedInputSources -RequestedInputValue $requestedInputValue", self.script_text)
        download_region = self._script_region(
            "$remoteSourceOrdinal = 0",
            "elseif ($InputPath)",
        )
        self.assertIn("foreach ($remoteSource in $remoteInputSources)", download_region)
        self.assertIn("$remoteDownloadFailures +=", download_region)
        self.assertIn('FailurePhase = "Download"', download_region)
        self.assertIn("continue", download_region)
        self.assertIn('SourceState "failed"', download_region)

    def test_remote_video_download_retries_transient_provider_failures(self) -> None:
        download_function = self._function_body("Invoke-RemoteVideoDownload")
        self.assertIn("%(title).80B", download_function)
        self.assertNotIn("%(title).120B", download_function)
        self.assertIn('$downloadMaxAttempts = if ($sourceKind -eq "video") { 3 } else { 1 }', download_function)
        self.assertIn("Web video download attempt {0} of {1} failed", download_function)
        self.assertIn("Start-Sleep -Seconds $retryDelaySeconds", download_function)
        self.assertIn("failed after {1} attempts", download_function)
        self.assertIn("Get-ExternalFailureSummary", download_function)

    def test_initial_all_track_manifest_uses_explicit_package_root(self) -> None:
        manifest_function = self._function_body("New-TranscriptSourceManifestPayload")
        self.assertIn("[string]$PackageRoot", manifest_function)
        self.assertIn("-PackageRoot $PackageRoot", manifest_function)
        process_function = self._function_body("Process-Video")
        self.assertEqual(process_function.count("-PackageRoot $videoOutputRoot"), 2)

    def test_external_failures_are_actionable_and_log_writes_tolerate_windows_locks(self) -> None:
        retry_function = self._function_body("Add-LogContentWithRetry")
        self.assertIn("MaxAttempts = 8", retry_function)
        self.assertIn("Start-Sleep -Milliseconds", retry_function)
        summary_function = self._function_body("Get-ExternalFailureSummary")
        self.assertIn("HTTP Error", summary_function)
        self.assertIn("video unavailable", summary_function)
        capture_function = self._function_body("Invoke-ExternalCapture")
        streaming_function = self._function_body("Invoke-ExternalStreaming")
        self.assertIn("Add-LogContentWithRetry", capture_function)
        self.assertIn("Get-ExternalFailureSummary", capture_function)
        self.assertIn("Add-LogContentWithRetry", streaming_function)
        self.assertIn("Get-ExternalFailureSummary", streaming_function)
        self.assertNotIn("See script_run.log", streaming_function)

    def test_full_review_coverage_matrix_is_written_before_root_manifest(self) -> None:
        self.assertIn("function New-EvidenceCoverageMatrix", self.script_text)
        self.assertIn("EVIDENCE_COVERAGE_MATRIX.csv", self.script_text)
        self.assertIn("review_needed_count", self._function_body("New-EvidenceCoverageMatrix"))
        final_region = self._script_region("$fullReviewCodexEvidenceStatus = Resolve-FullReviewCodexEvidenceStatus", "Write-Phase -Name \"Final Summary\"")
        self.assertIn("$coverageMatrixResult = New-EvidenceCoverageMatrix", final_region)
        self.assertIn("-CoverageRows @($coverageMatrixResult.Rows)", final_region)

    def test_ai_review_zip_includes_compact_ai_evidence_supplement_with_size_fallback(self) -> None:
        zip_function = self._function_body("New-AiReviewZipPackage")
        # The files made for the ZIP go to a scratch folder named for this process (201), never
        # into the package; the ZIP itself is written by the one ZIP writer (209).
        self.assertIn('Get-MMScratchPath -Prefix "media_manglers_ai_review_zip"', zip_function)
        self.assertIn('-Command "zip-write"', zip_function)
        self.assertNotIn('_ai_review_zip_temp', zip_function)
        self.assertIn("New-AiReviewEvidenceSupplement", zip_function)
        self.assertIn("New-AiReviewEvidenceSupplementOmissionNote", zip_function)
        self.assertIn("EvidenceSupplementMode", zip_function)
        self.assertIn("omitted-too-large", zip_function)
        supplement_function = self._function_body("New-AiReviewEvidenceSupplement")
        self.assertIn("\"ai_evidence\"", supplement_function)
        self.assertIn("metadata.json", supplement_function)
        self.assertIn("frame_index.csv", supplement_function)
        self.assertIn("frames\\full", supplement_function)
        self.assertIn("frames\\panels", supplement_function)
        self.assertIn("REVIEW_NEEDED.md", supplement_function)
        self.assertIn("REVIEW_NEEDED.json", supplement_function)

    def test_full_review_records_transcript_audio_reuse_boundary(self) -> None:
        artifact_function = self._function_body("New-AiReviewArtifacts")
        self.assertIn("transcript_audio_reuse", artifact_function)
        self.assertIn("metadata_guard_added", artifact_function)
        self.assertIn("Broader transcript/audio reuse is a separate follow-up", artifact_function)

    def test_panel_crop_option_is_visible_and_exact_dimension_only(self) -> None:
        self.assertIn('[ValidateSet("Auto", "On", "Off")]', self.script_text)
        self.assertIn("[string]$EvidencePanelCrops = \"Auto\"", self.script_text)
        self.assertIn("5760x1080 NVIDIA Surround panel crops", self.script_text)
        panel_function = self._function_body("Test-ThreePanelFrame")
        self.assertIn("return ($Width -eq 5760 -and $Height -eq 1080)", panel_function)
        # 214: evidence screenshots use the one frame renderer's rule, the same 5760x1080 one.
        from media_manglers.core import panel_layout
        self.assertEqual((panel_layout.THREE_PANEL_COMPOSITE_WIDTH, panel_layout.THREE_PANEL_COMPOSITE_HEIGHT), (5760, 1080))
        self.assertIn("do not match exact 5760x1080", self.script_text)

    def test_full_review_panel_crop_switches_and_outputs_are_visible(self) -> None:
        self.assertIn("[string]$FullReviewPanelCrops = \"Auto\"", self.script_text)
        self.assertIn("[double]$FullReviewPanelCropCadenceSeconds = 5", self.script_text)
        self.assertIn("frames_panels", self.script_text)
        self.assertIn("panel_frame_index.csv", self.script_text)
        self.assertIn("panel_frame_manifest.json", self.script_text)
        self.assertIn("Export-FullReviewPanelFrames", self.script_text)
        self.assertIn("full_review_panel_crops", self.script_text)

    def test_full_review_audio_inventory_and_transcript_source_metadata_are_visible(self) -> None:
        self.assertIn('[ValidateSet("Auto", "All", "Prompt", "Mixed", "Track")]', self.script_text)
        self.assertIn("[string]$TranscriptAudioStream", self.script_text)
        self.assertIn("[int]$TranscriptAudioTrackOrdinal", self.script_text)
        self.assertIn("[switch]$AudioTrackAudit", self.script_text)
        self.assertIn("audio_tracks.json", self.script_text)
        self.assertIn("audio_tracks.csv", self.script_text)
        self.assertIn("transcript_source.wav", self.script_text)
        self.assertIn("transcript_source_metadata.json", self.script_text)
        self.assertIn("transcript_source_manifest.json", self.script_text)
        self.assertIn("all_audio_tracks_transcript.md", self.script_text)
        self.assertIn("all_audio_tracks_index.csv", self.script_text)
        self.assertIn("all_audio_tracks_manifest.json", self.script_text)
        self.assertIn("TranscriptAudioStream must look like 0:a:1, a:1, or 0:2", self.script_text)
        self.assertIn("Transcript files already exist and transcript_source_metadata.json matches", self.script_text)
        self.assertIn("Existing transcript files were not reused", self.script_text)

    def test_full_review_auto_transcribes_all_audio_tracks_by_default(self) -> None:
        selection_function = self._function_body("Resolve-TranscriptAudioSelection")
        self.assertIn('$normalizedMode -eq "All" -or $normalizedMode -eq "Auto"', selection_function)
        self.assertIn("$selectedStreams = @($streams)", selection_function)
        self.assertIn('$resolvedMode = "All"', selection_function)
        self.assertIn("Full Review should transcribe every detected audio track by default", selection_function)
        self.assertIn("TranscriptAudioMode Prompt requires an interactive run", selection_function)

    def test_all_track_whisper_budget_uses_effective_track_workload(self) -> None:
        process_region = self._function_body("Process-Video")
        self.assertIn("$allTrackEffectiveTranscriptionDurationSeconds", process_region)
        self.assertIn("-EffectiveDurationSeconds $allTrackEffectiveTranscriptionDurationSeconds", process_region)
        self.assertIn("-AudioTrackCount (@($audioPhaseResult.TrackItems).Count)", process_region)
        self.assertIn("-TranscriptAudioModeResolved ([string]$audioPhaseResult.Selection.ModeResolved)", process_region)

    def test_whisper_progress_reports_estimate_overrun_and_hard_budget(self) -> None:
        streaming_function = self._function_body("Invoke-ExternalStreaming")
        self.assertIn("exceeded estimate; continuing because helper is active", streaming_function)
        self.assertIn("over estimate by {0}; hard budget remaining {1}", streaming_function)
        self.assertIn("hard runtime budget exceeded", streaming_function)
        self.assertIn("stopped reporting progress", streaming_function)

    def test_all_track_partial_transcription_is_recorded(self) -> None:
        process_region = self._function_body("Process-Video")
        self.assertIn("TranscriptStatus = \"failed\"", process_region)
        self.assertIn("FailureReason = $failureMessage", process_region)
        self.assertIn("$allTrackTranscriptStatus = if ($trackTranscriptFailureCount", process_region)
        self.assertIn("All-track transcription completed with partial status", process_region)
        coverage_function = self._function_body("Get-FullReviewTranscriptCoverageStatus")
        self.assertIn("all_tracks_transcript_partial", coverage_function)
        self.assertIn("all_tracks_transcript_failed", coverage_function)

    def test_ai_review_zip_omits_all_wav_transcript_sources(self) -> None:
        zip_function = self._function_body("New-AiReviewZipPackage")
        self.assertIn("$audioFolderFull = (Get-Item -LiteralPath $audioFolder).FullName", zip_function)
        # 209: the audio folder goes in through the one ZIP writer, without its WAV files.
        self.assertIn('@{ source = $audioFolder; name = "audio"; exclude_suffixes = @(".wav") }', zip_function)
        self.assertIn('$_.Extension -ine ".wav"', zip_function)
        self.assertIn('$_.Extension -ieq ".wav"', zip_function)
        self.assertIn("audio\\tracks\\track_NN.wav", zip_function)
        self.assertIn("all_tracks_review_mix.wav", zip_function)
        self.assertIn("TRANSCRIPT_SOURCE_WAV_OMITTED.txt", zip_function)

    def test_ai_review_zip_panel_policy_is_budgeted(self) -> None:
        self.assertIn('[ValidateSet("Auto", "Off", "IndexOnly", "Selected")]', self.script_text)
        zip_function = self._function_body("New-AiReviewZipPackage")
        self.assertIn("panel_frame_index.csv", zip_function)
        self.assertIn("panel_frame_manifest.json", zip_function)
        self.assertIn("driver_view", zip_function)
        self.assertIn("AiReviewZipMaxMb", zip_function)
        self.assertIn("PanelImageCount", zip_function)

    def test_codex_evidence_transcript_paths_use_budgeted_physical_source_ids(self) -> None:
        budget_function = self._function_body("Get-BoundedTranscriptPhysicalSourceId")
        self.assertIn("[int]$PathBudget = 240", budget_function)
        self.assertIn(".transcript.quality.json", budget_function)
        self.assertIn("$rawTranscriptSourcesRoot", budget_function)
        self.assertIn("[System.Security.Cryptography.SHA256]::Create()", budget_function)
        self.assertIn("logical source ID remains in manifests", self.script_text)
        batch_function = self._function_body("Invoke-CodexEvidencePackageBatch")
        self.assertIn(
            "$physicalSourceId = Get-BoundedTranscriptPhysicalSourceId",
            batch_function,
        )
        self.assertIn('("{0}.transcript.json" -f $physicalSourceId)', batch_function)
        self.assertIn("physical_source_id   = $physicalSourceId", batch_function)
        self.assertIn("physical_source_id = [string]$_.physical_source_id", batch_function)

    def _function_body(self, function_name: str) -> str:
        marker = f"function {function_name} "
        start = self.script_text.find(marker)
        if start < 0:
            self.fail(f"Could not find function {function_name}")
        next_function = self.script_text.find("\nfunction ", start + len(marker))
        if next_function < 0:
            return self.script_text[start:]
        return self.script_text[start:next_function]

    def _script_region(self, start_marker: str, end_marker: str) -> str:
        start = self.script_text.find(start_marker)
        if start < 0:
            self.fail(f"Could not find start marker {start_marker}")
        end = self.script_text.find(end_marker, start)
        if end < 0:
            self.fail(f"Could not find end marker {end_marker}")
        return self.script_text[start:end]


if __name__ == "__main__":
    unittest.main()
