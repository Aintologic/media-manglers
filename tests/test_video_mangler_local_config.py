from __future__ import annotations

import json
from pathlib import Path
import unittest


class VideoManglerLocalConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.root = root
        cls.script_text = (root / "Video Mangler.ps1").read_text(encoding="utf-8")
        cls.gitignore_text = (root / ".gitignore").read_text(encoding="utf-8")
        cls.example_config = json.loads(
            (root / "docs" / "examples" / "media-manglers.config.example.json").read_text(encoding="utf-8")
        )

    def test_local_config_path_and_template_are_repo_safe(self) -> None:
        self.assertIn("function Get-MediaManglersConfigPath", self.script_text)
        self.assertIn("$env:APPDATA", self.script_text)
        self.assertIn("MediaManglers", self.script_text)
        self.assertIn("config.json", self.script_text)
        self.assertIn("function New-MediaManglersDefaultConfig", self.script_text)
        self.assertIn("targetRepo", self.script_text)
        self.assertIn("repoMapPath", self.script_text)
        self.assertIn("customMarkers", self.script_text)
        self.assertIn("customDomainTerms", self.script_text)

    def test_evidence_config_precedence_hooks_are_present(self) -> None:
        self.assertIn("[string[]]$EvidenceCustomMarkers = @()", self.script_text)
        self.assertIn("[string[]]$EvidenceCustomDomainTerms = @()", self.script_text)
        resolver = self._function_body("Resolve-MediaManglersEvidenceSettings")
        self.assertIn("TargetRepoWasExplicit", resolver)
        self.assertIn("RepoMapPathWasExplicit", resolver)
        self.assertIn("CustomMarkersWereExplicit", resolver)
        self.assertIn("CustomDomainTermsWereExplicit", resolver)

    def test_workflow_three_merges_local_custom_terms_into_detection(self) -> None:
        detect_helper = self._function_body("Invoke-CodexEvidenceDetectHelper")
        self.assertIn("custom_markers", detect_helper)
        self.assertIn("custom_domain_terms", detect_helper)
        batch_helper = self._function_body("Invoke-CodexEvidencePackageBatch")
        self.assertIn("CustomMarkers", batch_helper)
        self.assertIn("CustomDomainTerms", batch_helper)
        standalone_region = self._script_region(
            "$codexEvidenceResult = Invoke-CodexEvidencePackageBatch `",
            "if ($doOpenOutputInExplorer)",
        )
        self.assertIn("-CustomMarkers @($effectiveEvidenceCustomMarkers)", standalone_region)
        self.assertIn("-CustomDomainTerms @($effectiveEvidenceCustomDomainTerms)", standalone_region)

    def test_config_copies_are_ignored_and_example_is_generic(self) -> None:
        self.assertIn("media-manglers.config.json", self.gitignore_text)
        self.assertIn("**/MediaManglers/config.json", self.gitignore_text)
        self.assertEqual(self.example_config["evidence"]["targetRepo"], "owner/example-project")
        self.assertEqual(self.example_config["reviewMediaInbox"]["dedupeMode"], "Fast")
        self.assertEqual(self.example_config["reviewMediaInbox"]["maxFiles"], 3)
        self.assertEqual(self.example_config["reviewMediaInbox"]["maxDurationMinutes"], 240)
        self.assertIn("customMarkers", self.example_config["evidence"])
        self.assertIn("customDomainTerms", self.example_config["evidence"])

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
