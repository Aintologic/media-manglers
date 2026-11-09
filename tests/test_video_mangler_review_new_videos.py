from __future__ import annotations

from pathlib import Path
import unittest


class VideoManglerReviewNewVideosTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script_text = (Path(__file__).resolve().parents[1] / "Video Mangler.ps1").read_text(encoding="utf-8")

    def test_review_new_videos_switches_are_exposed(self) -> None:
        for expected in (
            "[switch]$ReviewNewVideos",
            "[Alias(\"ReviewMediaInbox\")]",
            "[ValidateSet(\"Scan\", \"Process\", \"Prepare\", \"TargetedEvidence\", \"ImportResults\", \"PreviewFinalization\", \"Finalize\")]",
            "[string]$ReviewInboxAction = \"Scan\"",
            "[ValidateSet(\"next_3\", \"up_to_n\", \"all_pending\")]",
            "[string]$ReviewInboxWorkload = \"next_3\"",
            "[int]$ReviewInboxNewSourceLimit = 0",
            "[string]$ReviewInboxExactSourcePathsJson = \"\"",
            "[string]$ReviewInboxContinuation = \"\"",
            "[string]$ReviewInboxDecisionJson = \"\"",
            "[string]$ReviewPreliminarySubmissionSha256 = \"\"",
            "[string]$ReviewResultsPath = \"\"",
            "[string]$ReviewFinalizationPlanPath = \"\"",
            "[string]$ReviewFinalizationPlanSha256 = \"\"",
            "[switch]$ReviewFinalizationConfirmed",
            "[string[]]$ReviewSourceFolders = @()",
            "[string]$ReviewEvidenceRoot = \"\"",
            "[string]$ReviewLocalWorkRoot = \"\"",
            "[string]$ReviewLedgerPath = \"\"",
            "[ValidateSet(\"\", \"Fast\", \"Full\")]",
            "[string]$ReviewDedupeMode = \"\"",
            "[string]$ReviewInboxOrder = \"\"",
            "[int]$ReviewInboxMaxFiles = 0",
            "[int]$ReviewInboxMaxDurationMinutes = 0",
            "[int]$ReviewInboxConcurrency = 0",
            "[int]$ReviewInboxPendingBatchLimit = 0",
            "[switch]$ReviewFullScanAcknowledged",
            "[switch]$ReviewNoRecurse",
        ):
            self.assertIn(expected, self.script_text)

    def test_review_new_videos_menu_and_mutual_exclusion_are_wired(self) -> None:
        workflow_function = self._function_body("Get-InteractiveVideoWorkflow")
        self.assertIn("5. Review Media Inbox", workflow_function)
        self.assertIn("ReviewNewVideos = $true", workflow_function)
        self.assertIn("-ReviewNewVideos", self.script_text)
        self.assertIn("$ReviewNewVideos.IsPresent", self.script_text)
        self.assertIn("Choose only one workflow switch", self.script_text)

    def test_review_new_videos_uses_local_config_and_stops_without_sources(self) -> None:
        resolver = self._function_body("Resolve-MediaManglersReviewSettings")
        self.assertIn("reviewMediaInbox", resolver)
        self.assertIn("reviewNewVideos", resolver)
        self.assertIn("SourceFoldersWereExplicit", resolver)
        self.assertIn("EvidenceRootWasExplicit", resolver)
        self.assertIn("LocalWorkRootWasExplicit", resolver)
        self.assertIn("LedgerPathWasExplicit", resolver)
        self.assertIn("DedupeModeWasExplicit", resolver)

        config_region = self._script_region("if ($ReviewNewVideos) {", "if ($includeFullReviewCodexEvidencePackage")
        self.assertIn("Resolve-MediaManglersReviewSettings", config_region)
        self.assertIn("has no source folders configured", config_region)
        self.assertIn("reviewMediaInbox.sourceFolders", config_region)
        self.assertIn("return", config_region)

    def test_review_media_inbox_dispatch_has_explicit_safe_scan_and_prepare_boundary(self) -> None:
        dispatch = self._script_region('Write-Host ("Review Media Inbox {0} configuration:"', "$whisperProbe = $null")
        self.assertIn('"review-media-inbox-prepare"', dispatch)
        self.assertIn('"review-media-inbox-scan"', dispatch)
        self.assertIn('$ReviewInboxAction -eq "Prepare"', dispatch)
        self.assertIn("max_files", dispatch)
        self.assertIn("max_duration_minutes", dispatch)
        self.assertIn("pending_batch_limit", dispatch)
        self.assertIn("Full deduplication hashes every stable file", dispatch)
        self.assertIn("ReviewFullScanAcknowledged", dispatch)
        self.assertIn("progress_state_file_path", self._function_body("Invoke-ReviewLedgerHelper"))
        self.assertIn("-ProgressStateFilePath $progressStatePath", self._function_body("Invoke-ReviewLedgerHelper"))
        self.assertIn('[string]$progressState.Schema -eq "MM_PROGRESS_V1"', self._function_body("Invoke-ExternalStreaming"))
        self.assertIn("No media was copied, transcribed, rendered, moved, renamed, or deleted.", dispatch)
        self.assertIn("return", dispatch)
        self.assertNotIn("Copy-Item", dispatch)
        self.assertNotIn("Invoke-CodexEvidencePackageBatch", dispatch)

    def test_review_new_videos_passes_local_evidence_terms_without_scheduling(self) -> None:
        dispatch = self._script_region('Write-Host ("Review Media Inbox {0} configuration:"', "$whisperProbe = $null")
        self.assertNotIn("Register-ScheduledTask", dispatch)
        self.assertNotIn("schtasks", dispatch.lower())

    def test_process_action_uses_distinct_contract_lock_and_automatic_targeted_loop(self) -> None:
        dispatch = self._script_region('Write-Host ("Review Media Inbox {0} configuration:"', "$whisperProbe = $null")
        self.assertIn('$ReviewInboxAction -eq "Process"', dispatch)
        self.assertIn('"review-media-inbox-process"', dispatch)
        self.assertIn("attach_only = $true", dispatch)
        self.assertIn("MM_REVIEW_INBOX_PROCESS_RESULT_V1", dispatch)
        # 224 (Wave B1): the loop takes the lock through the host's one lock function, which TargetedEvidence
        # uses too; that function is the same exclusive, never-deleted handle with a fresh record.
        self.assertIn("$processLock = Open-ReviewInboxProcessLock -LedgerPath ([string]$reviewNewVideosSettings.LedgerPath)",
                      dispatch)
        self.assertNotIn("[System.IO.File]::Open(", dispatch)
        self.assertNotIn("Remove-Item -LiteralPath $processLockPath", dispatch)
        lock = self._function_body("Open-ReviewInboxProcessLock")
        self.assertIn('"process.lock"', lock)
        self.assertIn("[System.IO.FileMode]::OpenOrCreate", lock)
        self.assertNotIn("[System.IO.FileMode]::CreateNew", lock)
        self.assertIn("[System.IO.FileShare]::None", lock)
        self.assertIn("process_id = $PID", lock)
        self.assertIn('token = [guid]::NewGuid().ToString("N")', lock)
        self.assertIn("$lock.SetLength(0)", lock)
        self.assertNotIn("Remove-Item", lock)
        self.assertIn('"render_targeted"', dispatch)
        self.assertIn("Invoke-ReviewInboxTargetedEvidence", dispatch)
        self.assertIn("continue_automatically", dispatch)
        self.assertIn("between 1 and 9999", dispatch)
        self.assertIn(
            "exact_source_paths = @($reviewInboxExactSourcePaths)",
            dispatch,
        )
        self.assertIn(
            "ReviewInboxExactSourcePathsJson is supported only with "
            "-ReviewInboxAction Process",
            dispatch,
        )
        helper = self._function_body("Invoke-ReviewLedgerHelper")
        self.assertIn('"review-media-inbox-process"', helper)
        self.assertIn('"review-media-inbox-reconcile"', helper)
        self.assertIn('"review-media-inbox-relocate"', helper)

    def test_final_results_and_finalization_dispatch_require_explicit_inputs(self) -> None:
        dispatch = self._script_region('Write-Host ("Review Media Inbox {0} configuration:"', "$whisperProbe = $null")
        for expected in (
            '"review-media-inbox-import-results"',
            '"review-media-inbox-finalization-preview"',
            '"review-media-inbox-finalize"',
            "ReviewResultsPath",
            "ReviewFinalizationPlanPath",
            "ReviewFinalizationPlanSha256",
            "ReviewFinalizationConfirmed",
            "requires -ReviewFinalizationConfirmed",
        ):
            self.assertIn(expected, dispatch)

    def test_targeted_evidence_reuses_workflow3_renderers_and_request_boundary_stop(self) -> None:
        targeted = self._function_body("Invoke-ReviewInboxTargetedEvidence")
        self.assertIn('"review-media-inbox-targeted-plan"', targeted)
        self.assertIn('"review-media-inbox-targeted-complete"', targeted)
        # 214: the shared screenshot and clip makers, not the one-at-a-time copies.
        self.assertIn("Invoke-CodexEvidenceFrameTasks -FFmpegExe", targeted)
        self.assertIn("Invoke-CodexEvidenceAudioTasks -FFmpegExe", targeted)
        self.assertIn("processed_request_signatures", targeted)
        self.assertIn("StopAfterCurrentRequestPath", targeted)
        self.assertIn('Phase "Targeted evidence"', targeted)
        self.assertIn("-ArtifactId $artifactId", targeted)
        self.assertIn("frames", targeted)
        self.assertIn("panels", targeted)
        self.assertIn("audio", targeted)
        self.assertNotIn("Invoke-CodexEvidencePackageBatch", targeted)
        dispatch = self._script_region('Write-Host ("Review Media Inbox {0} configuration:"', "$whisperProbe = $null")
        self.assertIn('$ReviewInboxAction -eq "TargetedEvidence"', dispatch)
        self.assertIn("Invoke-ReviewInboxTargetedEvidence", dispatch)

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
