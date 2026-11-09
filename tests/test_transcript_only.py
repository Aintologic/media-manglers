from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core.transcript_only import (
    expand_search_terms,
    make_safe_source_id,
    write_outputs_from_request,
)
from media_manglers.cli import main
from media_manglers.contracts import CommandEnvelope, read_json_file, write_json_file


class TranscriptOnlyTests(unittest.TestCase):
    def test_safe_source_id_uses_stem_and_stable_hash(self) -> None:
        first = make_safe_source_id("/sample/videos/2000-01-01 clip.mkv", "2000-01-01 clip.mkv")
        second = make_safe_source_id("/sample/other/2000-01-01 clip.mkv", "2000-01-01 clip.mkv")

        self.assertRegex(first, r"^2000-01-01_clip-[0-9a-f]{10}$")
        self.assertNotEqual(first, second)

    def test_expand_search_terms_adds_operator_ticket_aliases(self) -> None:
        expanded = expand_search_terms(["make this a ticket"])
        terms = {item["term"] for item in expanded}

        self.assertIn("ticket", terms)
        self.assertIn("issue", terms)
        self.assertIn("make this a to-do item", terms)

    def test_write_outputs_creates_manifest_index_and_search_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript_dir = root / "transcripts"
            transcript_dir.mkdir()
            transcript_json = transcript_dir / "clip-abc.transcript.json"
            transcript_txt = transcript_dir / "clip-abc.transcript.txt"
            transcript_srt = transcript_dir / "clip-abc.transcript.srt"
            audio_path = root / "audio" / "clip-abc.audio.mp3"
            audio_path.parent.mkdir()
            audio_path.write_bytes(b"fake audio")
            transcript_json.write_text(
                json.dumps(
                    {
                        "language": "en",
                        "segments": [
                            {
                                "id": 1,
                                "start": 1.0,
                                "end": 3.5,
                                "text": "Please make this a ticket for later.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            transcript_txt.write_text("Please make this a ticket for later.\n", encoding="utf-8")
            transcript_srt.write_text("", encoding="utf-8")

            result = write_outputs_from_request(
                {
                    "output_dir": str(root),
                    "manifest_entries": [
                        {
                            "source_id": "clip-abc",
                            "source_identifier": "clip.mkv",
                            "source_path": "/sample/videos/clip.mkv",
                            "source_filename": "clip.mkv",
                            "audio_path": str(audio_path),
                            "audio_status": "completed",
                            "audio_error_message": "",
                            "transcript_json_path": str(transcript_json),
                            "transcript_srt_path": str(transcript_srt),
                            "transcript_txt_path": str(transcript_txt),
                            "duration_seconds": "3.5",
                            "status": "completed",
                            "error_message": "",
                        }
                    ],
                    "search_terms": ["issue"],
                }
            )

            self.assertTrue(Path(result["manifest_json_path"]).exists())
            self.assertTrue(Path(result["manifest_csv_path"]).exists())
            combined_text = Path(result["combined_markdown_path"]).read_text(encoding="utf-8")
            self.assertIn("clip.mkv", combined_text)
            self.assertIn("audio/clip-abc.audio.mp3", combined_text.replace("\\", "/"))
            search_text = Path(result["search_markdown_path"]).read_text(encoding="utf-8")
            self.assertIn("make this a ticket", search_text)
            self.assertTrue(Path(result["ai_search_markdown_path"]).exists())
            self.assertEqual(result["per_source_search_result_count"], 1)
            per_source_text = Path(result["per_source_search_result_paths"][0]).read_text(encoding="utf-8")
            self.assertIn("make this a ticket", per_source_text)
            self.assertEqual(result["search_match_count"], 1)

    def test_cli_writes_transcript_only_index_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript_dir = root / "transcripts"
            transcript_dir.mkdir()
            transcript_json = transcript_dir / "clip-def.transcript.json"
            transcript_txt = transcript_dir / "clip-def.transcript.txt"
            transcript_srt = transcript_dir / "clip-def.transcript.srt"
            audio_path = root / "audio" / "clip-def.audio.mp3"
            audio_path.parent.mkdir()
            audio_path.write_bytes(b"fake audio")
            transcript_json.write_text(
                json.dumps(
                    {
                        "language": "en",
                        "segments": [
                            {
                                "start": 0.0,
                                "end": 2.0,
                                "text": "Cheeseburger marker for search.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            transcript_txt.write_text("Cheeseburger marker for search.\n", encoding="utf-8")
            transcript_srt.write_text("", encoding="utf-8")

            request_path = root / "request.json"
            result_path = root / "result.json"
            write_json_file(
                request_path,
                CommandEnvelope(
                    payload={
                        "output_dir": str(root),
                        "manifest_entries": [
                            {
                                "source_id": "clip-def",
                                "source_identifier": "clip.mkv",
                                "source_path": "/sample/videos/clip.mkv",
                                "source_filename": "clip.mkv",
                                "audio_path": str(audio_path),
                                "audio_status": "completed",
                                "audio_error_message": "",
                                "transcript_json_path": str(transcript_json),
                                "transcript_srt_path": str(transcript_srt),
                                "transcript_txt_path": str(transcript_txt),
                                "duration_seconds": "2.0",
                                "status": "completed",
                                "error_message": "",
                            }
                        ],
                        "search_terms": ["cheeseburger"],
                    }
                ).to_dict(),
            )

            exit_code = main(
                [
                    "transcript-only-index",
                    "--request-file",
                    str(request_path),
                    "--result-file",
                    str(result_path),
                ]
            )
            response = read_json_file(result_path)

            self.assertEqual(exit_code, 0)
            self.assertTrue(response["ok"])
            self.assertEqual(response["data"]["search_results_count"], 1)
            self.assertTrue(Path(response["data"]["ai_search_markdown"]).exists())
            self.assertEqual(response["data"]["per_source_search_result_count"], 1)
            self.assertTrue((root / "TRANSCRIPTS_ALL.md").exists())


if __name__ == "__main__":
    unittest.main()
