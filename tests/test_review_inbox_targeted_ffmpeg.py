from __future__ import annotations

from array import array
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from media_manglers.core import inbox_records, review_findings, review_ledger, review_preparation
from media_manglers.core.transcripts import write_transcript_files
from media_manglers_workbench.audio_detection import AudioStreamInfo, layout_fingerprint
import pytest
from tests import inbox_library  # noqa: E402

# 224 (Wave B2b): the Inbox's records are in this test's library, moved in (nothing to move).
pytestmark = pytest.mark.inbox_moved


REPO_ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe") and shutil.which("powershell"), "FFmpeg and Windows PowerShell are required")
class ReviewInboxTargetedFfmpegTests(unittest.TestCase):
    def test_actual_workflow3_frame_panel_and_selected_audio_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources"
            sources.mkdir()
            source = sources / "synthetic-two-track.mp4"
            subprocess.run(
                [
                    shutil.which("ffmpeg") or "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=navy:s=5760x1080:r=1:d=4",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:sample_rate=48000:duration=4",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=880:sample_rate=48000:duration=4",
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-map",
                    "2:a:0",
                    "-c:v",
                    "mpeg4",
                    "-q:v",
                    "12",
                    "-c:a",
                    "aac",
                    "-shortest",
                    str(source),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            original = (source.read_bytes(), source.stat().st_mtime_ns)
            streams = [
                AudioStreamInfo(0, 1, title="440 Hz", codec="aac", channels=1, channel_layout="mono", sample_rate=48000),
                AudioStreamInfo(1, 2, title="880 Hz", codec="aac", channels=1, channel_layout="mono", sample_rate=48000),
            ]
            fingerprint = layout_fingerprint(streams, "synthetic-ffmpeg")

            def media_probe(_path: Path) -> dict:
                return {
                    "duration_seconds": 4.0,
                    "container": "mp4",
                    "bit_rate": 1_000_000,
                    "recorder_profile": "synthetic-ffmpeg",
                    "video_streams": [{"stream_index": 0, "codec": "mpeg4", "width": 5760, "height": 1080}],
                    "audio_streams": [
                        {
                            "ordinal": item.ordinal,
                            "stream_index": item.stream_index,
                            "title": item.title,
                            "language": item.language,
                            "codec": item.codec,
                            "channels": item.channels,
                            "channel_layout": item.channel_layout,
                            "sample_rate": item.sample_rate,
                            "bit_rate": item.bit_rate,
                            "ffmpeg_map": item.ffmpeg_map,
                        }
                        for item in streams
                    ],
                    "audio_layout_fingerprint": fingerprint,
                }

            def extract(_source: Path, ordinal: int, output: Path) -> None:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(f"selected ordinal {ordinal}".encode("ascii"))

            def transcribe(_audio: Path, output: Path, _settings: dict) -> dict:
                result = {"language": "en", "segments": [{"start": 0.0, "end": 1.0, "text": "synthetic"}]}
                json_path, srt_path, text_path = write_transcript_files(output, "transcript.json", "transcript.srt", "transcript.txt", result)
                quality = output / "transcript.quality.json"
                quality.write_text('{"quality_blocking": false}\n', encoding="utf-8")
                return {"json_path": str(json_path), "srt_path": str(srt_path), "text_path": str(text_path), "quality_json_path": str(quality), "segments_count": 1, "quality_blocking": False}

            def render(_source: Path, _media: dict, output: Path) -> dict:
                frame = output / "frames" / "frame-001.jpg"
                frame.parent.mkdir(parents=True, exist_ok=True)
                frame.write_bytes(b"prepared-frame")
                panels = []
                for role in ("driver_view", "overview_cam"):
                    relative = f"panels/frame-001-{role}.jpg"
                    target = output / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(role.encode("ascii"))
                    panels.append({"panel": role, "timestamp_seconds": 2.0, "path": relative})
                (output / "contact-sheet.jpg").write_bytes(b"prepared-sheet")
                index = {"schema_version": 1, "frames": [{"ordinal": 1, "timestamp_seconds": 2.0, "path": "frames/frame-001.jpg"}], "panels": panels}
                review_preparation._atomic_json(output / "timeline-index.json", index)
                return {"frame_count": 1, "frames": index["frames"], "contact_sheet": "contact-sheet.jpg", "panels": panels}

            ledger = root / "review-ledger.sqlite"
            inbox_library.ready(ledger)
            prepared = review_preparation.prepare_from_request(
                {
                    "source_folders": [str(sources)],
                    "ledger_path": str(ledger),
                    "evidence_root": str(root / "evidence"),
                    "scratch_root": str(root / "scratch"),
                    "max_files": 1,
                    "max_duration_minutes": 240,
                    "concurrency": 1,
                    "pending_batch_limit": 1,
                    "dedupe_mode": "Fast",
                    "order": "oldest",
                    "space_probe": lambda _path: 100 * 1024**3,
                    "media_probe": media_probe,
                    "audio_confirmations": {fingerprint: {"layoutFingerprint": fingerprint, "audioOrdinal": 1, "confirmationSource": "operator"}},
                    "audio_extractor": extract,
                    "transcriber": transcribe,
                    "visual_renderer": render,
                }
            )
            batch_root = Path(prepared["batch_path"])
            document = json.loads((batch_root / "preliminary-findings.template.json").read_text(encoding="utf-8"))
            document["findings"] = [
                {
                    "finding_id": "ffmpeg-finding",
                    "source_identity": document["reviewed_source_identities"][0],
                    "request_type": "targeted_evidence",
                    "requests": [
                        {
                            "request_id": "ffmpeg-request",
                            "timestamp": {"kind": "point", "at_seconds": 2.0},
                            "frames": {"requested": True, "before_seconds": 0.0, "after_seconds": 0.0, "max_frames": 1},
                            "panels": {"requested": True, "panel_ids": ["driver_view"], "before_seconds": 0.0, "after_seconds": 0.0},
                            "audio": {"requested": True, "before_seconds": 1.0, "after_seconds": 1.0},
                        }
                    ],
                    "reviewer_notes": "Exercise the actual established frame, panel, and audio render helpers.",
                    "confidence": {"level": "high", "rationale": "Synthetic fixture has known dimensions and tones."},
                }
            ]
            submission = root / "preliminary-findings.json"
            submission.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
            imported = review_findings.import_from_request(
                {"ledger_path": str(ledger), "batch_path": str(batch_root), "expected_batch_id": prepared["batch_id"], "findings_path": str(submission)}
            )
            self.assertTrue(imported["accepted"], imported.get("problems"))
            command = [
                shutil.which("powershell") or "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(REPO_ROOT / "Video Mangler.ps1"),
                "-ReviewMediaInbox",
                "-ReviewInboxAction",
                "TargetedEvidence",
                "-ReviewInboxResumeBatchId",
                str(prepared["batch_id"]),
                "-ReviewPreliminarySubmissionSha256",
                str(imported["submission_sha256"]),
                "-ReviewSourceFolders",
                str(sources),
                "-ReviewEvidenceRoot",
                str(root / "evidence"),
                "-ReviewLocalWorkRoot",
                str(root / "scratch"),
                "-ReviewLedgerPath",
                str(ledger),
                # 127: name the script's own folders too, so its log stays in this test's folder.
                "-InputFolder",
                str(root / "input"),
                "-OutputFolder",
                str(root / "output"),
                "-FFmpegPath",
                shutil.which("ffmpeg") or "ffmpeg",
                "-FFprobePath",
                shutil.which("ffprobe") or "ffprobe",
                "-PythonExe",
                "py",
                "-NoPrompt",
            ]
            run = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, timeout=180)
            self.assertEqual(run.returncode, 0, run.stdout + "\n" + run.stderr)
            result_line = next(line for line in run.stdout.splitlines() if line.startswith("MM_REVIEW_INBOX_RESULT_V1 "))
            result = json.loads(result_line.split(" ", 1)[1])
            self.assertEqual(result["status"], "targeted_evidence_ready")
            request_root = next(batch_root.glob("sources/*/targeted-evidence/f-*/r-*"))
            manifest = json.loads((request_root / "request-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual({item["kind"] for item in manifest["artifact_inventory"]}, {"frame", "panel", "audio"})
            frame = next((request_root / "frames").glob("*.jpg"))
            panel = next((request_root / "panels" / "driver_view").glob("*.jpg"))
            for target, expected in ((frame, "5760,1080"), (panel, "1920,1080")):
                probe = subprocess.run(
                    [shutil.which("ffprobe") or "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(target)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(probe.stdout.strip(), expected)
            audio = request_root / "audio" / "selected-audio.mp3"
            decoded = subprocess.run(
                [shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-i", str(audio), "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                check=True,
                capture_output=True,
                timeout=60,
            ).stdout
            samples = array("h")
            samples.frombytes(decoded)
            crossings = sum((samples[index - 1] < 0 <= samples[index]) or (samples[index - 1] >= 0 > samples[index]) for index in range(1, len(samples)))
            estimated_hz = crossings / 2.0 / (len(samples) / 8000.0)
            self.assertGreater(estimated_hz, 800.0)
            self.assertLess(estimated_hz, 950.0)
            self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), original)


if __name__ == "__main__":
    unittest.main()
