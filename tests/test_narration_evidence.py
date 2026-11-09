from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core.narration_evidence import (  # noqa: E402
    narration_moments,
    plan_from_request,
    write_index_from_request,
)


def _transcript(path: Path, segments: list[tuple[float, float, str]]) -> Path:
    path.write_text(
        json.dumps({"segments": [{"start": a, "end": b, "text": t} for a, b, t in segments]}),
        encoding="utf-8",
    )
    return path


class NarrationEvidenceTests(unittest.TestCase):
    def test_moments_follow_speech_not_keywords_and_skip_filler(self) -> None:
        moments = narration_moments(
            [
                {"start": 10, "end": 14, "text": "The delta bar does not cycle."},
                {"start": 20, "end": 24, "text": "See, it stays on session best."},
                {"start": 200, "end": 204, "text": "Thank you for watching!"},
                {"start": 400, "end": 405, "text": "Those two buttons do nothing at all."},
            ]
        )
        self.assertEqual(len(moments), 2)
        self.assertEqual(moments[0]["start"], "00:00:10.000")
        self.assertIn("session best", moments[0]["text"])
        self.assertEqual(moments[1]["start_seconds"], 400)

    def test_plan_gives_every_moment_frames_panels_and_a_clip_within_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            segments = [(float(minute * 60), float(minute * 60 + 20), f"Overlay problem number {minute}") for minute in range(60)]
            transcript = _transcript(root / "t.json", segments)
            plan = plan_from_request(
                {
                    "output_dir": str(root / "pkg"),
                    "panel_crop_mode": "Auto",
                    "max_frames_per_source": 150,
                    "sources": [
                        {"source_id": "s1", "source_path": str(root / "rec.mkv"), "status": "completed",
                         "duration_seconds": 3700, "transcript_json_path": str(transcript), "selected_audio_stream_index": 1},
                        {"source_id": "s2", "source_path": str(root / "silent.mkv"), "status": "no_narration",
                         "duration_seconds": 100, "transcript_json_path": str(transcript)},
                    ],
                }
            )
        moments = plan["sources"][0]["moments"]
        self.assertEqual(len(plan["sources"]), 1)
        self.assertEqual(len(moments), 60)
        self.assertTrue(all(moment["frames"] and moment["clips"] for moment in moments))
        self.assertLessEqual(len(plan["frame_tasks"]), 150 + 60)
        task = plan["frame_tasks"][0]
        self.assertEqual({panel["role"] for panel in task["panels"]}, {"overview_cam", "driver_view", "face_cam"})
        # Crops are filed by the operator's monitors, left to right (103).
        self.assertEqual(
            [panel["screen"] for panel in task["panels"]],
            ["left_monitor", "center_monitor", "right_monitor"],
        )
        self.assertTrue(all(f"/panels/{panel['screen']}/" in panel["relative_path"] for panel in task["panels"]))
        self.assertEqual(set(moments[0]["frames"][0]["panels"]), {"left_monitor", "center_monitor", "right_monitor"})
        # One small review video per usable recording, with the voice track.
        self.assertEqual(len(plan["review_video_tasks"]), 1)
        review = plan["review_video_tasks"][0]
        self.assertEqual(review["audio_ordinal"], 1)
        self.assertLessEqual(review["width"], 1920)
        self.assertEqual(plan["sources"][0]["review_video"], review["relative_path"])
        self.assertTrue(all(clip["audio_ordinal"] == 1 for clip in plan["clip_tasks"]))
        self.assertTrue(all(clip["duration_seconds"] <= 45.0 for clip in plan["clip_tasks"]))

    def test_index_lists_only_files_that_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = _transcript(root / "t.json", [(30.0, 36.0, "The weather icons are too small.")])
            package = root / "pkg"
            plan_path = package / "artifacts" / "narration" / "plan.json"
            plan = plan_from_request(
                {
                    "output_dir": str(package),
                    "plan_path": str(plan_path),
                    "sources": [{"source_id": "s1", "source_path": str(root / "rec.mkv"), "status": "completed",
                                 "duration_seconds": 120, "transcript_json_path": str(transcript)}],
                }
            )
            first = package / plan["frame_tasks"][0]["relative_path"]
            first.parent.mkdir(parents=True, exist_ok=True)
            first.write_bytes(b"jpg")
            clip = package / plan["clip_tasks"][0]["relative_path"]
            clip.parent.mkdir(parents=True, exist_ok=True)
            clip.write_bytes(b"mp4")
            result = write_index_from_request({"output_dir": str(package), "plan_path": str(plan_path)})
            without_review = json.loads((package / "NARRATION_EVIDENCE.json").read_text(encoding="utf-8"))
            review = package / plan["review_video_tasks"][0]["relative_path"]
            review.write_bytes(b"mp4")
            with_review = write_index_from_request({"output_dir": str(package), "plan_path": str(plan_path)})
            markdown = (package / "NARRATION_EVIDENCE.md").read_text(encoding="utf-8")
        self.assertEqual(result["frame_count"], 1)
        self.assertEqual(result["clip_count"], 1)
        self.assertEqual(result["moments_with_visuals"], 1)
        self.assertIn("weather icons are too small", markdown)
        self.assertIn(plan["clip_tasks"][0]["relative_path"], markdown)
        self.assertEqual(result["review_video_count"], 0)
        self.assertEqual(without_review["sources"][0]["review_video"], "")
        self.assertEqual(with_review["review_video_count"], 1)
        self.assertIn(plan["review_video_tasks"][0]["relative_path"], markdown)
        self.assertIn("left_monitor", markdown)


if __name__ == "__main__":
    unittest.main()
