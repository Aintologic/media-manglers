from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.cli import main
from media_manglers.contracts import CommandEnvelope, read_json_file, write_json_file


class PackageReadmeCliTests(unittest.TestCase):
    def _run_cli(self, payload: dict[str, object]) -> str:
        with tempfile.TemporaryDirectory() as temp_dir:
            request_path = Path(temp_dir) / "request.json"
            result_path = Path(temp_dir) / "result.json"
            readme_path = Path(temp_dir) / "README_FOR_CODEX.txt"

            request_payload = dict(payload)
            request_payload["readme_path"] = str(readme_path)

            write_json_file(
                request_path,
                CommandEnvelope(payload=request_payload).to_dict(),
            )

            exit_code = main(
                [
                    "write-package-readme",
                    "--request-file",
                    str(request_path),
                    "--result-file",
                    str(result_path),
                ]
            )
            response = read_json_file(result_path)

            self.assertEqual(exit_code, 0)
            self.assertTrue(response["ok"])
            self.assertEqual(response["data"]["readme_path"], str(readme_path))

            return readme_path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")

    def test_video_package_readme_cli_matches_expected_text(self) -> None:
        actual = self._run_cli(
            {
                "readme_kind": "video",
                "video_file_name": "1_min_test_Video.mp4",
                "raw_present": "No",
                "audio_present": "Yes",
                "frame_interval_display": "0.5",
                "frames_folder_name": "frames_0p5s",
                "processing_mode_summary": "Local",
                "openai_project_summary": "",
                "transcription_path_details": "Local (Whisper transcription)",
                "detected_language": "en",
                "translation_targets": [],
                "translation_status": "",
                "translation_path_details": "none",
                "translation_notes": "",
                "next_steps": "",
                "comments_summary": "",
                "remote_audio_track_summary": "",
                "package_status": "SUCCESS",
            }
        )
        expected = (
            (Path(__file__).parent / "fixtures" / "readmes" / "video_package_readme.txt")
            .read_text(encoding="utf-8")
            .replace("\r\n", "\n")
        )
        self.assertEqual(actual, expected)

    def test_audio_package_readme_cli_matches_expected_text(self) -> None:
        actual = self._run_cli(
            {
                "readme_kind": "audio",
                "audio_file_name": "1_min_test_Video.mp4",
                "raw_present": "No",
                "processing_mode_summary": "Local",
                "openai_project_summary": "",
                "transcription_path_details": "Local (Whisper transcription)",
                "detected_language": "en",
                "translation_targets": [],
                "translation_status": "",
                "translation_path_details": "none",
                "translation_notes": "",
                "next_steps": "",
                "comments_summary": "",
                "package_status": "SUCCESS",
            }
        )
        expected = (
            (Path(__file__).parent / "fixtures" / "readmes" / "audio_package_readme.txt")
            .read_text(encoding="utf-8")
            .replace("\r\n", "\n")
        )
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
