from __future__ import annotations

from pathlib import Path
import unittest


class AiReviewRenameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.video_script = (root / "Video Mangler.ps1").read_text(encoding="utf-8")
        cls.audio_script = (root / "Audio Mangler.ps1").read_text(encoding="utf-8")
        cls.evidence_package = (root / "src" / "media_manglers" / "core" / "evidence_package.py").read_text(
            encoding="utf-8"
        )
        cls.transcript_only = (root / "src" / "media_manglers" / "core" / "transcript_only.py").read_text(
            encoding="utf-8"
        )

    def test_new_ai_review_switches_keep_old_aliases(self) -> None:
        for script in (self.video_script, self.audio_script):
            self.assertIn('[Alias("CreateChatGptZip")]', script)
            self.assertIn("[switch]$CreateAiReviewZip", script)
            self.assertIn('[Alias("ChatGptZipMaxMb")]', script)
            self.assertIn("[int]$AiReviewZipMaxMb = 500", script)

        self.assertIn('[Alias("ChatGptZipPanelCropMode")]', self.video_script)
        self.assertIn("[string]$AiReviewZipPanelCropMode = \"Auto\"", self.video_script)

    def test_review_package_outputs_use_ai_names_only(self) -> None:
        for script in (self.video_script, self.audio_script):
            self.assertIn("ai_review_package.zip", script)
            self.assertIn("README_FOR_AI.txt", script)
            self.assertNotIn("chatgpt_review_package.zip", script)
            self.assertNotIn("README_FOR_CHATGPT.txt", script)

    def test_python_handoff_outputs_use_ai_names(self) -> None:
        self.assertIn("README_FOR_AI.md", self.evidence_package)
        self.assertNotIn("README_FOR_CHATGPT.md", self.evidence_package)
        self.assertIn("AI_SEARCH_RESULTS.md", self.transcript_only)
        self.assertNotIn("CHATGPT_SEARCH_RESULTS.md", self.transcript_only)


if __name__ == "__main__":
    unittest.main()
