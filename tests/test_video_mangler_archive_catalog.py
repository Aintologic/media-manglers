from __future__ import annotations

from pathlib import Path
import unittest


class VideoManglerArchiveCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script_text = (Path(__file__).resolve().parents[1] / "Video Mangler.ps1").read_text(encoding="utf-8")

    def test_archive_catalog_switches_are_exposed(self) -> None:
        for expected in (
            "[switch]$ArchiveCatalog",
            "[switch]$ArchiveCatalogSearch",
            "[string[]]$ArchiveSearchTerms",
            "[string]$ArchiveSkipMarker = \"_NO_GLACIER_BACKUP\"",
            "[ValidateSet(\"Fast\", \"Full\", \"Off\")]",
            "[string]$ArchiveHashMode = \"Fast\"",
            "[ValidateSet(\"Auto\", \"Off\")]",
            "[string]$ArchiveThumbnailMode = \"Auto\"",
            "[int]$ArchiveMaxThumbnailsPerVideo = 12",
            "[string]$ArchiveS3Bucket",
            "[string]$ArchiveS3Prefix",
            "[string]$ArchiveCatalogPath",
            "[string]$ArchiveNotesCsv",
            "[switch]$ArchiveExportNotesTemplate",
        ):
            self.assertIn(expected, self.script_text)

    def test_archive_catalog_menu_option_is_visible(self) -> None:
        workflow_function = self._function_body("Get-InteractiveVideoWorkflow")

        self.assertIn("4. Archive catalog / Glacier prep index", workflow_function)
        self.assertIn("without AWS upload", workflow_function)
        self.assertIn("Get-InteractiveArchiveCatalogAction", workflow_function)

    def test_archive_catalog_uses_python_cli_commands(self) -> None:
        build_function = self._function_body("Invoke-ArchiveCatalogBuildHelper")
        search_function = self._function_body("Invoke-ArchiveCatalogSearchHelper")

        self.assertIn("-Command \"archive-catalog-build\"", build_function)
        self.assertIn("-Command \"archive-catalog-search\"", search_function)
        self.assertIn("archive-catalog-build", self.script_text)
        self.assertIn("archive-catalog-search", self.script_text)

    def test_archive_catalog_preflight_states_no_aws_or_whisper(self) -> None:
        archive_region = self._script_region("if ($ArchiveCatalog -or $ArchiveCatalogSearch)", "$includeFullReviewCodexEvidencePackage = $false")

        self.assertIn("Archive Catalog preflight:", archive_region)
        self.assertIn("catalog notes/template update only", archive_region)
        self.assertIn("no upload will be performed", archive_region)
        self.assertIn("does not upload to AWS, execute Glacier restores, or run Whisper transcription", archive_region)
        self.assertNotIn("Test-PythonWhisper", archive_region)
        self.assertNotIn("Invoke-TranscriptOnlyBatch", archive_region)

    def test_archive_catalog_search_prints_required_result_fields(self) -> None:
        search_writer = self._function_body("Write-ArchiveCatalogSearchResults")

        for label in ("S3 key:", "Duration:", "Size bytes:", "Status:", "Notes:", "Tags:", "Contact:"):
            self.assertIn(label, search_writer)

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
