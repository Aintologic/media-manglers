from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.cli import main
from media_manglers.contracts import CommandEnvelope, read_json_file, write_json_file
from media_manglers.core import archive_catalog
from media_manglers.core.archive_catalog import (
    build_catalog_from_request,
    normalize_ffprobe_payload,
    search_catalog_from_request,
    select_thumbnail_timestamps,
)


PROBE_OK = {
    "duration": "615.5",
    "width": "1920",
    "height": "1080",
    "video_codec": "h264",
    "audio_present": "true",
    "audio_stream_count": "1",
    "stream_info_json": "{}",
}


class ArchiveCatalogTests(unittest.TestCase):
    def _write_video(self, root: Path, relative: str, content: bytes = b"fake video") -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def _read_csv(self, path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    def test_folder_walk_includes_supported_media_and_skips_marker_descendants(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            keep = self._write_video(root, "keep/session.mp4")
            self._write_video(root, "keep/readme.txt")
            skipped_dir = root / "skip_me"
            skipped_dir.mkdir()
            (skipped_dir / "_NO_GLACIER_BACKUP").write_text("", encoding="utf-8")
            self._write_video(skipped_dir, "nested/skipped.mkv")

            videos, skipped = archive_catalog._walk_video_files(root, "_NO_GLACIER_BACKUP")

            self.assertEqual([path.resolve() for path in videos], [keep.resolve()])
            self.assertEqual(len(skipped), 1)
            self.assertEqual(skipped[0]["reason"], "skip_marker_present")

    def test_build_creates_sqlite_exports_sidecar_and_notes_template(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir = root / "input"
            output_dir = root / "output"
            self._write_video(input_dir, "Spa Race.mp4")

            with mock.patch.object(archive_catalog, "_run_ffprobe", return_value=PROBE_OK):
                result = build_catalog_from_request(
                    {
                        "input_path": str(input_dir),
                        "output_dir": str(output_dir),
                        "thumbnail_mode": "Off",
                        "media_mangler_version": "0.8.5",
                    }
                )

            catalog_dir = Path(result["catalog_path"])
            self.assertTrue((catalog_dir / "archive_catalog.sqlite").exists())
            self.assertTrue((catalog_dir / "archive_catalog.csv").exists())
            self.assertTrue((catalog_dir / "archive_catalog.jsonl").exists())
            self.assertTrue((catalog_dir / "archive_integrity_manifest.csv").exists())
            self.assertTrue((catalog_dir / "archive_upload_manifest.csv").exists())
            self.assertTrue((catalog_dir / "archive_restore_index.md").exists())
            self.assertTrue((catalog_dir / "manual_notes_template.csv").exists())
            sidecars = list((catalog_dir / "sidecars").glob("*.json"))
            self.assertEqual(len(sidecars), 1)
            sidecar = json.loads(sidecars[0].read_text(encoding="utf-8"))
            self.assertEqual(sidecar["filename"], "Spa Race.mp4")
            self.assertEqual(sidecar["hash_status"], "skipped_fast_mode")
            self.assertEqual(result["scanned_count"], 1)

    def test_ffprobe_payload_normalization(self) -> None:
        normalized = normalize_ffprobe_payload(
            {
                "format": {"duration": "12.3456"},
                "streams": [
                    {"codec_type": "video", "codec_name": "hevc", "width": 3840, "height": 2160},
                    {"codec_type": "audio", "codec_name": "aac"},
                ],
            }
        )

        self.assertEqual(normalized["duration"], "12.346")
        self.assertEqual(normalized["width"], "3840")
        self.assertEqual(normalized["height"], "2160")
        self.assertEqual(normalized["video_codec"], "hevc")
        self.assertEqual(normalized["audio_present"], "true")
        self.assertEqual(normalized["audio_stream_count"], "1")

    def test_unprobeable_media_writes_errors_and_does_not_abort(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir = root / "input"
            output_dir = root / "output"
            self._write_video(input_dir, "bad.mp4")
            self._write_video(input_dir, "also-bad.webm")

            result = build_catalog_from_request(
                {
                    "input_path": str(input_dir),
                    "output_dir": str(output_dir),
                    "ffprobe_path": str(root / "missing-ffprobe.exe"),
                    "thumbnail_mode": "Off",
                }
            )

            self.assertEqual(result["scanned_count"], 2)
            self.assertEqual(result["error_count"], 2)
            errors = self._read_csv(Path(result["catalog_path"]) / "errors.csv")
            self.assertEqual(len(errors), 2)
            rows = self._read_csv(Path(result["catalog_path"]) / "archive_catalog.csv")
            self.assertEqual({row["catalog_status"] for row in rows}, {"error"})

    def test_thumbnail_selection_honors_max_cap_and_includes_finalish_frame(self) -> None:
        timestamps = select_thumbnail_timestamps(7200, 3)

        self.assertLessEqual(len(timestamps), 3)
        self.assertGreaterEqual(timestamps[-1], 7180)

    def test_manual_notes_import_updates_fts_without_wiping_unrelated_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir = root / "input"
            output_dir = root / "output"
            video_path = self._write_video(input_dir, "session.mp4")
            video_path.with_suffix(".transcript.txt").write_text(
                "Existing transcript mentions dashboard issue.",
                encoding="utf-8",
            )

            with mock.patch.object(archive_catalog, "_run_ffprobe", return_value=PROBE_OK):
                result = build_catalog_from_request(
                    {
                        "input_path": str(input_dir),
                        "output_dir": str(output_dir),
                        "thumbnail_mode": "Off",
                    }
                )

            catalog_dir = Path(result["catalog_path"])
            rows = self._read_csv(catalog_dir / "archive_catalog.csv")
            video_id = rows[0]["video_id"]
            connection = sqlite3.connect(catalog_dir / "archive_catalog.sqlite")
            connection.execute("UPDATE videos SET short_summary = ? WHERE video_id = ?", ("Keep this summary", video_id))
            connection.commit()
            connection.close()

            notes_csv = root / "notes.csv"
            notes_csv.write_text(
                "video_id,manual_notes,manual_tags,game,track,car,session_type,visible_apps,issue_keywords\n"
                f"{video_id},Spa Ferrari GT3 dashboard review,\"Spa,Ferrari,GT3\",iRacing,Spa,Ferrari 296,practice,SimHub,dashboard issue\n",
                encoding="utf-8",
            )
            build_catalog_from_request(
                {
                    "output_dir": str(output_dir),
                    "catalog_path": str(catalog_dir),
                    "notes_csv": str(notes_csv),
                    "thumbnail_mode": "Off",
                }
            )

            search_result = search_catalog_from_request(
                {"catalog_path": str(catalog_dir), "query": "Spa Ferrari GT3"}
            )
            self.assertEqual(search_result["count"], 1)
            self.assertIn("dashboard review", search_result["results"][0]["manual_notes"])
            connection = sqlite3.connect(catalog_dir / "archive_catalog.sqlite")
            summary = connection.execute("SELECT short_summary FROM videos WHERE video_id = ?", (video_id,)).fetchone()[0]
            connection.close()
            self.assertEqual(summary, "Keep this summary")

    def test_transcript_detection_marks_reused_or_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir = root / "input"
            output_dir = root / "output"
            reused = self._write_video(input_dir, "with-transcript.mp4")
            reused.with_suffix(".transcript.txt").write_text("Transcript text", encoding="utf-8")
            self._write_video(input_dir, "without-transcript.mp4")

            with mock.patch.object(archive_catalog, "_run_ffprobe", return_value=PROBE_OK):
                result = build_catalog_from_request(
                    {
                        "input_path": str(input_dir),
                        "output_dir": str(output_dir),
                        "thumbnail_mode": "Off",
                    }
                )

            rows = {row["filename"]: row for row in self._read_csv(Path(result["catalog_path"]) / "archive_catalog.csv")}
            self.assertEqual(rows["with-transcript.mp4"]["transcript_status"], "reused")
            self.assertEqual(rows["without-transcript.mp4"]["transcript_status"], "skipped")

    def test_fast_hash_is_honest_and_full_hash_writes_verified_sha_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir = root / "input"
            fast_output = root / "fast"
            full_output = root / "full"
            video = self._write_video(input_dir, "hash-me.mp4", b"hash me")

            with mock.patch.object(archive_catalog, "_run_ffprobe", return_value=PROBE_OK):
                fast_result = build_catalog_from_request(
                    {
                        "input_path": str(input_dir),
                        "output_dir": str(fast_output),
                        "hash_mode": "Fast",
                        "thumbnail_mode": "Off",
                    }
                )
                full_result = build_catalog_from_request(
                    {
                        "input_path": str(input_dir),
                        "output_dir": str(full_output),
                        "hash_mode": "Full",
                        "thumbnail_mode": "Off",
                    }
                )

            fast_sha = (Path(fast_result["catalog_path"]) / "archive_manifest.sha256.txt").read_text(encoding="utf-8")
            self.assertIn("No verified SHA-256 rows", fast_sha)
            full_sha = (Path(full_result["catalog_path"]) / "archive_manifest.sha256.txt").read_text(encoding="utf-8")
            self.assertIn(hashlib.sha256(video.read_bytes()).hexdigest(), full_sha)
            full_rows = self._read_csv(Path(full_result["catalog_path"]) / "archive_integrity_manifest.csv")
            self.assertEqual(full_rows[0]["hash_status"], "verified_full_sha256")

    def test_incremental_rescan_preserves_notes_and_marks_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir = root / "input"
            output_dir = root / "output"
            video = self._write_video(input_dir, "missing-later.mp4")

            with mock.patch.object(archive_catalog, "_run_ffprobe", return_value=PROBE_OK):
                first = build_catalog_from_request(
                    {
                        "input_path": str(input_dir),
                        "output_dir": str(output_dir),
                        "thumbnail_mode": "Off",
                    }
                )
            catalog_dir = Path(first["catalog_path"])
            video_id = self._read_csv(catalog_dir / "archive_catalog.csv")[0]["video_id"]
            notes_csv = root / "notes.csv"
            notes_csv.write_text(f"video_id,manual_notes\n{video_id},Do not lose me\n", encoding="utf-8")
            build_catalog_from_request(
                {
                    "output_dir": str(output_dir),
                    "catalog_path": str(catalog_dir),
                    "notes_csv": str(notes_csv),
                    "thumbnail_mode": "Off",
                }
            )

            video.unlink()
            with mock.patch.object(archive_catalog, "_run_ffprobe", return_value=PROBE_OK):
                second = build_catalog_from_request(
                    {
                        "input_path": str(input_dir),
                        "output_dir": str(output_dir),
                        "thumbnail_mode": "Off",
                    }
                )

            rows = self._read_csv(catalog_dir / "archive_catalog.csv")
            self.assertEqual(second["missing_count"], 1)
            self.assertEqual(rows[0]["file_status"], "missing")
            self.assertEqual(rows[0]["manual_notes"], "Do not lose me")

    def test_notes_only_update_preserves_existing_skipped_paths_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir = root / "input"
            output_dir = root / "output"
            self._write_video(input_dir, "keep.mp4")
            skip_dir = input_dir / "skip"
            skip_dir.mkdir(parents=True)
            (skip_dir / "_NO_GLACIER_BACKUP").write_text("", encoding="utf-8")
            self._write_video(skip_dir, "skipped.mp4")

            with mock.patch.object(archive_catalog, "_run_ffprobe", return_value=PROBE_OK):
                result = build_catalog_from_request(
                    {
                        "input_path": str(input_dir),
                        "output_dir": str(output_dir),
                        "thumbnail_mode": "Off",
                    }
                )
            catalog_dir = Path(result["catalog_path"])
            self.assertEqual(len(self._read_csv(catalog_dir / "skipped_paths.csv")), 1)

            video_id = self._read_csv(catalog_dir / "archive_catalog.csv")[0]["video_id"]
            notes_csv = root / "notes.csv"
            notes_csv.write_text(f"video_id,manual_notes\n{video_id},Preserve skip rows\n", encoding="utf-8")
            build_catalog_from_request(
                {
                    "output_dir": str(output_dir),
                    "catalog_path": str(catalog_dir),
                    "notes_csv": str(notes_csv),
                    "thumbnail_mode": "Off",
                }
            )

            self.assertEqual(len(self._read_csv(catalog_dir / "skipped_paths.csv")), 1)

    def test_cli_archive_catalog_build_and_search_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir = root / "input"
            output_dir = root / "output"
            self._write_video(input_dir, "cli.mp4")
            request_path = root / "request.json"
            result_path = root / "result.json"
            write_json_file(
                request_path,
                CommandEnvelope(
                    payload={
                        "input_path": str(input_dir),
                        "output_dir": str(output_dir),
                        "thumbnail_mode": "Off",
                    }
                ).to_dict(),
            )

            with mock.patch.object(archive_catalog, "_run_ffprobe", return_value=PROBE_OK):
                exit_code = main(
                    [
                        "archive-catalog-build",
                        "--request-file",
                        str(request_path),
                        "--result-file",
                        str(result_path),
                    ]
                )
            response = read_json_file(result_path)

            self.assertEqual(exit_code, 0)
            self.assertTrue(response["ok"])
            catalog_dir = Path(response["data"]["catalog_path"])
            self.assertTrue((catalog_dir / "archive_catalog.sqlite").exists())

            search_request = root / "search-request.json"
            search_result = root / "search-result.json"
            write_json_file(
                search_request,
                CommandEnvelope(payload={"catalog_path": str(catalog_dir), "query": "cli"}).to_dict(),
            )
            search_exit_code = main(
                [
                    "archive-catalog-search",
                    "--request-file",
                    str(search_request),
                    "--result-file",
                    str(search_result),
                ]
            )
            search_response = read_json_file(search_result)

            self.assertEqual(search_exit_code, 0)
            self.assertTrue(search_response["ok"])
            self.assertEqual(search_response["data"]["count"], 1)

    def test_archive_code_does_not_add_machine_local_paths(self) -> None:
        module_text = Path(archive_catalog.__file__).read_text(encoding="utf-8")

        # No absolute drive path of any kind (for example X:\folder or X:/folder) is written into the module.
        self.assertIsNone(re.search(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][A-Za-z]", module_text))


if __name__ == "__main__":
    unittest.main()
