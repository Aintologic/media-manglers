"""206: the shared engine's settings reach every feature that transcribes, and Package any video for
AI makes its ZIP by default."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core import review_preparation  # noqa: E402
from media_manglers_workbench.command_builder import build_workflow_command  # noqa: E402
from media_manglers_workbench.metadata import (  # noqa: E402
    WORKFLOW_FULL_REVIEW,
    WORKFLOW_REVIEW_NEW_VIDEOS,
    WORKFLOW_TRANSCRIPT_ONLY,
)
from media_manglers_workbench.settings import build_default_settings, load_settings  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
WORDS = "Brooklands=brook lands\nEau Rouge"


def _argv(workflow: str, **changes: object) -> list[str]:
    settings = {**build_default_settings(), "input_path": "C:\\in\\a.mkv", "output_folder": "C:\\out",
                "evidence_transcription_glossary_entries": WORDS, "evidence_track_roles": "2=narration,3=never", **changes}
    return build_workflow_command(settings, workflow=workflow).argv


def _values(argv: list[str], flag: str) -> list[str]:
    return [argv[index + 1] for index, token in enumerate(argv) if token == flag]


class ZipByDefaultTests(unittest.TestCase):
    def _load(self, schema: int, value: bool) -> dict:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            path.write_text(json.dumps({"schemaVersion": schema, "settings": {"create_ai_review_zip": value}}),
                            encoding="utf-8")
            return load_settings(path)

    def test_full_review_makes_its_zip_by_default(self) -> None:
        self.assertTrue(build_default_settings()["create_ai_review_zip"])
        self.assertIn("-CreateAiReviewZip", _argv(WORKFLOW_FULL_REVIEW))

    def test_unticking_it_still_turns_it_off(self) -> None:
        self.assertNotIn("-CreateAiReviewZip", _argv(WORKFLOW_FULL_REVIEW, create_ai_review_zip=False))

    def test_an_off_saved_under_the_old_default_is_turned_on_once(self) -> None:
        self.assertTrue(self._load(7, False)["create_ai_review_zip"])
        self.assertFalse(self._load(8, False)["create_ai_review_zip"])


class EngineSettingsReachEveryFeatureTests(unittest.TestCase):
    def test_full_review_gets_the_words_and_the_track_setting(self) -> None:
        argv = _argv(WORKFLOW_FULL_REVIEW)
        self.assertEqual(_values(argv, "-EvidenceTranscriptionGlossaryEntries"), ["Brooklands=brook lands;Eau Rouge"])
        self.assertEqual(_values(argv, "-EvidenceTrackRoles"), ["2=narration,3=never"])

    def test_full_review_with_the_evidence_add_on_gets_each_once(self) -> None:
        argv = _argv(WORKFLOW_FULL_REVIEW, include_codex_evidence_package=True)
        self.assertEqual(len(_values(argv, "-EvidenceTranscriptionGlossaryEntries")), 1)
        self.assertEqual(len(_values(argv, "-EvidenceTrackRoles")), 1)

    def test_transcript_only_and_the_inbox_get_the_words(self) -> None:
        for workflow in (WORKFLOW_TRANSCRIPT_ONLY, WORKFLOW_REVIEW_NEW_VIDEOS):
            self.assertEqual(_values(_argv(workflow), "-EvidenceTranscriptionGlossaryEntries"),
                             ["Brooklands=brook lands;Eau Rouge"], workflow)

    def test_the_inbox_prepare_step_hands_the_words_to_whisper(self) -> None:
        sent: dict = {}
        with mock.patch.object(review_preparation.whisper_local, "transcribe_from_request",
                               side_effect=lambda payload: sent.update(payload) or {}):
            review_preparation._default_transcriber(Path("a.wav"), Path("out"), {
                "glossary_entries": ["Brooklands=brook lands"], "initial_prompt": "Preferred terminology: Brooklands"})
        self.assertEqual(sent["glossary_entries"], ["Brooklands=brook lands"])
        self.assertEqual(sent["initial_prompt"], "Preferred terminology: Brooklands")

    def test_the_inbox_request_carries_the_words(self) -> None:
        text = (REPO_ROOT / "Video Mangler.ps1").read_text(encoding="utf-8-sig")
        start = text.index("$reviewProcessPayload = @{")
        payload = text[start: text.index("\n        }", start)]
        self.assertIn("glossary_entries = @(Get-MMSpellingWords)", payload)
        self.assertIn("initial_prompt = (Get-EvidenceTranscriptionInitialPrompt -GlossaryEntries (Get-MMSpellingWords))", payload)


if __name__ == "__main__":
    unittest.main()
