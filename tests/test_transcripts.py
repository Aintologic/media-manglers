from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core.artifacts import coerce_segment_records
from media_manglers.core.transcripts import format_srt_time, write_transcript_files


class TranscriptHelpersTests(unittest.TestCase):
    def test_format_srt_time_uses_srt_timestamp_shape(self) -> None:
        self.assertEqual(format_srt_time(65.432), "00:01:05,432")

    def test_coerce_segment_records_normalizes_text(self) -> None:
        segments = coerce_segment_records(
            [{"id": 1, "start": 0.0, "end": 1.0, "text": "  hello  "}],
        )
        self.assertEqual(
            segments,
            [{"id": 1, "start": 0.0, "end": 1.0, "text": "hello"}],
        )

    def test_write_transcript_files_writes_json_text_and_srt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path, srt_path, text_path = write_transcript_files(
                output_dir=temp_dir,
                json_name="transcript.json",
                srt_name="transcript.srt",
                text_name="transcript.txt",
                result={
                    "language": "en",
                    "segments": [
                        {"id": 1, "start": 0.0, "end": 1.5, "text": " Hello world "},
                    ],
                },
            )

            payload = json.loads(Path(json_path).read_text(encoding="utf-8"))
            self.assertEqual(payload["segments"][0]["text"], "Hello world")
            self.assertEqual(Path(text_path).read_text(encoding="utf-8"), "Hello world\n")
            self.assertIn("00:00:00,000 --> 00:00:01,500", Path(srt_path).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
