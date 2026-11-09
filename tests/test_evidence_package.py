from __future__ import annotations

import json
import csv
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core.evidence_package import build_package_from_request, detect_from_request, detect_three_panel_layout
from media_manglers.core.panel_layout import panel_crop_configuration
from media_manglers.cli import main
from media_manglers.contracts import (
    CommandEnvelope,
    EvidenceNarrationSettings,
    read_json_file,
    write_json_file,
)


FRAGMENTED_NARRATION_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "evidence" / "fragmented_narration.transcript.json"
)


def _write_transcript(path: Path, segments: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"language": "en", "segments": segments}), encoding="utf-8")


def _source(root: Path, transcript: Path, duration: float = 300.0, **extra: object) -> dict[str, object]:
    source = {
        "source_id": "clip-abc",
        "source_identifier": "clip.mp4",
        "source_path": str(root / "clip.mp4"),
        "source_filename": "clip.mp4",
        "duration_seconds": duration,
        "status": "completed",
        "error_message": "",
        "transcript_json_path": str(transcript),
        "transcript_srt_path": str(transcript.with_suffix(".transcript.srt")),
        "transcript_txt_path": str(transcript.with_suffix(".transcript.txt")),
    }
    source.update(extra)
    return source


def _write_repo_map(path: Path, repos: dict[str, dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"repos": repos}, indent=2), encoding="utf-8")


class EvidencePackageTests(unittest.TestCase):
    def test_narration_request_contract_normalizes_all_five_fields(self) -> None:
        settings = EvidenceNarrationSettings.from_payload(
            {
                "narration_context_pre_seconds": "180",
                "narration_context_post_seconds": 900,
                "narration_pause_threshold_seconds": "30.5",
                "narration_stop_at_next_ticket_boundary": "false",
                "fragmented_narration_mode": "true",
            }
        )
        self.assertEqual(
            settings.to_dict(),
            {
                "narration_context_pre_seconds": 180.0,
                "narration_context_post_seconds": 900.0,
                "narration_pause_threshold_seconds": 30.5,
                "narration_stop_at_next_ticket_boundary": False,
                "fragmented_narration_mode": True,
            },
        )

    def test_detection_merges_nearby_ticket_windows_and_keeps_explicit_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [
                    {"id": 1, "start": 40.0, "end": 45.0, "text": "Here is useful context before the marker."},
                    {"id": 2, "start": 65.0, "end": 70.0, "text": "Please make this a ticket for the export problem."},
                    # 199: a word like "issue" alone no longer makes a ticket; a likely request phrase
                    # nearby still joins the explicit ticket's window.
                    {"id": 3, "start": 100.0, "end": 103.0, "text": "This should be fixed in the review package too."},
                ],
            )

            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript)],
                    "pre_context_seconds": 30,
                    "post_context_seconds": 60,
                    "frame_offsets_seconds": [-30, 0, 30],
                    "max_items": 50,
                }
            )

            self.assertEqual(result["candidate_count"], 1)
            candidate = result["candidates"][0]
            self.assertEqual(candidate["confidence"], "explicit")
            self.assertIn("make this a ticket", candidate["detected_marker_phrases"])
            self.assertIn("this should be fixed", candidate["detected_marker_phrases"])
            self.assertEqual(candidate["timestamp_start_seconds"], 35.0)
            self.assertEqual(candidate["timestamp_end_seconds"], 160.0)

    def test_review_needed_detects_implicit_ui_domain_without_candidate_ticket(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [
                    {
                        "id": 1,
                        "start": 20.0,
                        "end": 25.0,
                        "text": "The dashboard is not showing the purple sector label.",
                    }
                ],
            )

            result = build_package_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=120.0)],
                    "pre_context_seconds": 10,
                    "post_context_seconds": 20,
                    "max_items": 50,
                }
            )

            self.assertEqual(result["candidate_count"], 0)
            self.assertEqual(result["review_needed_count"], 1)
            item = result["review_needed"][0]
            self.assertEqual(item["reason"], "implicit_issue_with_ui_or_domain_context")
            self.assertTrue(item["visual_followup_required"])
            self.assertIn("not showing", item["implicit_phrases"])
            self.assertIn("dashboard", item["domain_terms"])
            review_md = (root / "out" / "REVIEW_NEEDED.md").read_text(encoding="utf-8")
            manifest = json.loads((root / "out" / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("Review-needed items: 1", review_md)
            self.assertEqual(manifest["review_needed_count"], 1)
            self.assertEqual(manifest["visual_followup_required_count"], 1)

    def test_review_needed_does_not_trigger_on_domain_terms_alone(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [{"id": 1, "start": 20.0, "end": 25.0, "text": "The SimHub dashboard sector is purple."}],
            )

            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=120.0)],
                    "max_items": 50,
                }
            )

            self.assertEqual(result["candidate_count"], 0)
            self.assertEqual(result["review_needed_count"], 0)

    def test_review_needed_flags_suspicious_transcript_with_domain_terms_for_visual_followup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [{"id": 1, "start": 5.0, "end": 8.0, "text": "dashboard dashboard dashboard"}],
            )

            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=1200.0)],
                    "max_items": 50,
                }
            )

            self.assertEqual(result["candidate_count"], 0)
            self.assertEqual(result["review_needed_count"], 1)
            self.assertEqual(result["review_needed"][0]["reason"], "transcript_quality_visual_followup")
            self.assertEqual(result["visual_followup_required_count"], 1)

    def test_another_ticket_splits_overlapping_context_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [
                    {"id": 1, "start": 100.0, "end": 105.0, "text": "Make this a ticket for the dashboard menu."},
                    {"id": 2, "start": 120.0, "end": 125.0, "text": "Another ticket for the Example App font size."},
                ],
            )

            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=500.0)],
                    "pre_context_seconds": 60,
                    "post_context_seconds": 240,
                    "merge_gap_seconds": 90,
                    "max_items": 50,
                }
            )

            self.assertEqual(result["candidate_count"], 2)
            self.assertEqual(result["candidates"][0]["timestamp_start_seconds"], 40.0)
            self.assertEqual(result["candidates"][1]["timestamp_start_seconds"], 60.0)

    def test_strong_boundary_marker_splits_overlapping_context_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [
                    {"id": 1, "start": 100.0, "end": 105.0, "text": "Make this a ticket for the dashboard menu."},
                    {"id": 2, "start": 120.0, "end": 125.0, "text": "Next thing, change I want to make is the SimHub list order."},
                ],
            )

            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=500.0)],
                    "pre_context_seconds": 60,
                    "post_context_seconds": 240,
                    "merge_gap_seconds": 90,
                    "max_items": 50,
                }
            )

            self.assertEqual(result["candidate_count"], 2)
            self.assertIn("next thing", result["candidates"][1]["detected_marker_phrases"])

    def test_natural_fix_phrase_creates_likely_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [{"id": 1, "start": 15.0, "end": 18.0, "text": "This needs to be fixed before the next release."}],
            )

            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=60.0)],
                    "pre_context_seconds": 5,
                    "post_context_seconds": 10,
                    "max_items": 50,
                }
            )

            self.assertEqual(result["candidate_count"], 1)
            candidate = result["candidates"][0]
            self.assertEqual(candidate["confidence"], "likely")
            self.assertIn("this needs to be fixed", candidate["detected_marker_phrases"])

    def test_a_request_handed_to_the_ai_is_found_and_outranks_passing_ticket_remarks(self) -> None:
        # 151: a request introduced by "instructions for AI", with no ticket word, is found, and
        # passing remarks that merely contain "ticket" do not outrank it.
        for spelling in ("OK, instructions for AI.", "OK, instructions for A.I."):
            with self.subTest(spelling=spelling), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                transcript = root / "clip-abc.transcript.json"
                _write_transcript(
                    transcript,
                    [
                        {"id": 1, "start": 60.0, "end": 64.0, "text": "There's a ticket booth by the pit lane exit."},
                        {"id": 2, "start": 300.0, "end": 303.0, "text": spelling},
                        {"id": 3, "start": 303.5, "end": 309.0,
                         "text": "Give the lap table a copy button that puts the times on the clipboard."},
                        {"id": 4, "start": 309.5, "end": 316.0,
                         "text": "Show a short message when the copy has worked."},
                        {"id": 5, "start": 700.0, "end": 704.0, "text": "The cartoon had a talking ticket machine, ha."},
                    ],
                )

                result = detect_from_request(
                    {
                        "output_dir": str(root / "out"),
                        "sources": [_source(root, transcript, duration=900.0)],
                        "pre_context_seconds": 5,
                        "post_context_seconds": 20,
                        "max_items": 50,
                    }
                )

                handed = [c for c in result["candidates"]
                          if c["timestamp_start_seconds"] <= 300.0 <= c["timestamp_end_seconds"]]
                self.assertEqual(len(handed), 1, result["candidates"])
                self.assertEqual(handed[0]["confidence"], "explicit")
                self.assertTrue(any("instructions for" in phrase for phrase in handed[0]["detected_marker_phrases"]))
                rank = {"supporting": 0, "weak": 1, "likely": 2, "explicit": 3}
                for other in result["candidates"]:
                    if other is not handed[0]:
                        self.assertLess(rank[other["confidence"]], rank["explicit"], other)

    def test_a_marker_phrase_matches_whole_words_only(self) -> None:
        from media_manglers.core.evidence_package import _count_phrase, _phrase_occurs

        self.assertFalse(_phrase_occurs("There's a ticket booth by the pit exit.", "here's a ticket"))
        self.assertTrue(_phrase_occurs("Here's a ticket for the export.", "here's a ticket"))
        self.assertFalse(_phrase_occurs("Down the racetrack this lap.", "track this"))
        self.assertFalse(_phrase_occurs("That prefix it uses is odd.", "fix it"))
        self.assertTrue(_phrase_occurs("Two new features for the editor.", "new feature"), "a plural still counts")
        self.assertFalse(_phrase_occurs("Some tickets here.", "ticket"), "a single word stays exact")
        self.assertEqual(_count_phrase("Tickets, tickets and a ticket.", "tickets"), 2)
        self.assertTrue(_phrase_occurs("OK, a note for A.I. here.", "note for a.i"))

    def test_natural_todo_and_issue_phrases_create_explicit_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [
                    {"id": 1, "start": 10.0, "end": 12.0, "text": "Add this to the todo for installer output."},
                    {"id": 2, "start": 50.0, "end": 52.0, "text": "Make an issue ticket for the missing route."},
                    {"id": 3, "start": 90.0, "end": 92.0, "text": "Open a GitHub issue for the dashboard text."},
                ],
            )

            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=120.0)],
                    "pre_context_seconds": 2,
                    "post_context_seconds": 2,
                    "merge_gap_seconds": 5,
                    "max_items": 50,
                }
            )

            self.assertEqual(result["candidate_count"], 3)
            detected = [set(candidate["detected_marker_phrases"]) for candidate in result["candidates"]]
            self.assertTrue(all(candidate["confidence"] == "explicit" for candidate in result["candidates"]))
            self.assertIn("add this to the todo", detected[0])
            self.assertIn("make an issue ticket", detected[1])
            self.assertIn("open a GitHub issue", detected[2])

    def test_marker_audit_tracks_new_natural_operator_phrases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [
                    {"id": 1, "start": 5.0, "end": 6.0, "text": "Make an issue for the first review."},
                    {"id": 2, "start": 15.0, "end": 16.0, "text": "Create an issue for the second review."},
                    {"id": 3, "start": 25.0, "end": 26.0, "text": "Make an issue ticket for the third review."},
                    {"id": 4, "start": 35.0, "end": 36.0, "text": "Add this to the todo for the fourth review."},
                    {"id": 5, "start": 45.0, "end": 46.0, "text": "This needs to be fixed before handoff."},
                    {"id": 6, "start": 55.0, "end": 56.0, "text": "Open a GitHub issue for the dashboard text."},
                    {"id": 7, "start": 65.0, "end": 66.0, "text": "Track this after the run."},
                    {"id": 8, "start": 75.0, "end": 76.0, "text": "Capture this for follow up."},
                ],
            )

            result = build_package_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=120.0)],
                    "pre_context_seconds": 1,
                    "post_context_seconds": 1,
                    "max_items": 50,
                }
            )

            audit = json.loads(Path(result["marker_audit_json_path"]).read_text(encoding="utf-8"))
            audited_phrases = {hit["marker_phrase"] for hit in audit["markers"]}
            expected = {
                "make an issue",
                "create an issue",
                "make an issue ticket",
                "add this to the todo",
                "this needs to be fixed",
                "open a GitHub issue",
                "track this",
                "capture this",
            }
            self.assertTrue(expected.issubset(audited_phrases))

    def test_new_strong_boundary_phrases_split_overlapping_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [
                    {"id": 1, "start": 100.0, "end": 105.0, "text": "Make this a ticket for the dashboard menu."},
                    {"id": 2, "start": 120.0, "end": 125.0, "text": "Track this for the SimHub config page."},
                ],
            )

            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=500.0)],
                    "pre_context_seconds": 60,
                    "post_context_seconds": 240,
                    "merge_gap_seconds": 90,
                    "max_items": 50,
                }
            )

            self.assertEqual(result["candidate_count"], 2)
            second = result["candidates"][1]
            self.assertIn("track this", second["detected_marker_phrases"])
            self.assertEqual(second["boundary_marker_events"][0]["detected_marker_phrases"], ["track this", "simhub"])

    def test_broad_we_need_to_phrase_without_fix_does_not_create_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [{"id": 1, "start": 5.0, "end": 8.0, "text": "We need to check the replay before posting."}],
            )

            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=60.0)],
                    "pre_context_seconds": 5,
                    "post_context_seconds": 5,
                    "max_items": 50,
                }
            )

            self.assertEqual(result["candidate_count"], 0)

    def test_marker_audit_generation_and_candidate_coverage_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [
                    {
                        "id": 1,
                        "start": 43.0,
                        "end": 46.0,
                        "text": "Ticket. Put the dashboards at the top of the dashboard menu inside SimHub.",
                    }
                ],
            )

            result = build_package_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=300.0)],
                    "pre_context_seconds": 120,
                    "post_context_seconds": 240,
                    "max_items": 50,
                }
            )

            marker_json = Path(result["marker_audit_json_path"])
            marker_md = Path(result["marker_audit_markdown_path"])
            self.assertTrue(marker_json.exists())
            self.assertTrue(marker_md.exists())
            audit = json.loads(marker_json.read_text(encoding="utf-8"))
            self.assertGreaterEqual(audit["summary"]["explicit_marker_hits"], 1)
            ticket_hits = [hit for hit in audit["markers"] if hit["marker_phrase"] == "ticket"]
            self.assertTrue(ticket_hits)
            self.assertEqual(ticket_hits[0]["status"], "covered")
            self.assertIn("ticket-001", ticket_hits[0]["candidate_ids"])
            self.assertIn("dashboards", result["candidates"][0]["suggested_issue_title"].lower())
            manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
            self.assertIn("marker_audit_summary", manifest)
            self.assertIn("Marker Coverage", Path(result["readme_path"]).read_text(encoding="utf-8"))
            self.assertIn("Marker Coverage", Path(result["candidate_tickets_markdown_path"]).read_text(encoding="utf-8"))

    def test_marker_audit_indexes_explicit_markers_beyond_rich_render_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [
                    {"id": 1, "start": 10.0, "end": 12.0, "text": "Make this a ticket for the first issue."},
                    {"id": 2, "start": 250.0, "end": 252.0, "text": "Another ticket for the second issue."},
                ],
            )

            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=500.0)],
                    "pre_context_seconds": 1,
                    "post_context_seconds": 1,
                    "max_items": 1,
                }
            )

            self.assertEqual(result["candidate_count"], 1)
            self.assertEqual(result["detected_candidate_count"], 2)
            self.assertEqual(result["unrendered_candidate_count"], 1)
            self.assertGreater(result["marker_audit_summary"]["indexed_unrendered_marker_hits"], 0)
            indexed = [
                hit
                for hit in result["marker_audit"]["markers"]
                if hit["status"] == "indexed-unrendered"
            ]
            self.assertTrue(indexed)
            self.assertIn("ticket-002", indexed[0]["unrendered_candidate_ids"])

    def test_fragmented_narration_context_is_separate_from_frames_and_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "fragmented.transcript.json"
            transcript.write_text(FRAGMENTED_NARRATION_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

            result = build_package_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=1200.0)],
                    "pre_context_seconds": 90,
                    "post_context_seconds": 120,
                    "narration_context_pre_seconds": 120,
                    "narration_context_post_seconds": 600,
                    "narration_pause_threshold_seconds": 30,
                    "narration_stop_at_next_ticket_boundary": True,
                    "fragmented_narration_mode": True,
                    "frame_offsets_seconds": [-90, -60, -30, 0, 30, 60, 120],
                    "frame_cadence_seconds": 1,
                    "max_frames_per_candidate": 220,
                    "max_items": 20,
                }
            )

            self.assertEqual(result["detected_candidate_count"], 2)
            candidate = result["all_candidates"][0]
            self.assertEqual(candidate["confidence"], "explicit")
            self.assertIn("this needs to be a ticket", candidate["detected_marker_phrases"])
            self.assertEqual(candidate["timestamp_start_seconds"], 510.0)
            self.assertEqual(candidate["timestamp_end_seconds"], 720.0)
            self.assertEqual(candidate["narration_context_start_seconds"], 480.0)
            self.assertEqual(candidate["narration_context_end_seconds"], 900.0)
            self.assertTrue(candidate["narration_context_has_pre_marker_explanation"])
            self.assertTrue(candidate["narration_context_has_followup_after_pause"])
            self.assertEqual(candidate["narration_context_boundary_type"], "new_ticket")

            narration = candidate["narration_context"]
            speech_entries = [entry for entry in narration["entries"] if entry["kind"] == "speech"]
            pause_entries = [entry for entry in narration["entries"] if entry["kind"] == "pause"]
            speech_text = " ".join(entry["text"] for entry in speech_entries)
            self.assertIn("relative delta panel disappears", speech_text)
            self.assertIn("display comes back", speech_text)
            self.assertIn("color also flips", speech_text)
            self.assertNotIn("pit limiter", speech_text)
            self.assertGreaterEqual(len(pause_entries), 2)
            resumed = next(entry for entry in speech_entries if "display comes back" in entry["text"])
            self.assertEqual(resumed["label"], "possible_continuation_after_driving_pause")

            frames = candidate["frames"]
            self.assertLessEqual(len(frames), 220)
            self.assertTrue(all(510.0 <= frame["timestamp_seconds"] <= 720.0 for frame in frames))
            self.assertEqual(candidate["audio_snippet"]["start_seconds"], 510.0)
            self.assertEqual(candidate["audio_snippet"]["duration_seconds"], 210.0)
            self.assertFalse(candidate["audio_snippet"]["was_capped"])

            narration_md = (
                root / "out" / "evidence_items" / "ticket-001" / "narration_context.md"
            ).read_text(encoding="utf-8")
            narration_json = json.loads(
                (root / "out" / "evidence_items" / "ticket-001" / "narration_context.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn("possible continuation after driving pause", narration_md)
            self.assertIn("driving pause:", narration_md)
            self.assertIn("transcript/full_transcript.md", narration_md)
            self.assertEqual(narration_json["boundary"]["type"], "new_ticket")
            self.assertTrue((root / "out" / "transcript" / "full_transcript.json").exists())
            self.assertTrue((root / "out" / "transcript" / "full_transcript.md").exists())

    def test_audio_cap_and_frame_window_remain_independent_from_narration_horizon(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [{"id": 1, "start": 400.0, "end": 405.0, "text": "This needs to be a ticket."}],
            )
            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=1500.0)],
                    "pre_context_seconds": 180,
                    "post_context_seconds": 180,
                    "narration_context_pre_seconds": 300,
                    "narration_context_post_seconds": 900,
                    "frame_offsets_seconds": [-180, 0, 180],
                    "frame_cadence_seconds": 30,
                    "max_frames_per_candidate": 20,
                    "max_items": 20,
                }
            )
            candidate = result["candidates"][0]
            self.assertEqual(candidate["timestamp_start_seconds"], 220.0)
            self.assertEqual(candidate["timestamp_end_seconds"], 580.0)
            self.assertEqual(candidate["narration_context_start_seconds"], 100.0)
            self.assertEqual(candidate["narration_context_end_seconds"], 1300.0)
            self.assertEqual(candidate["audio_snippet"]["duration_seconds"], 300.0)
            self.assertTrue(candidate["audio_snippet"]["was_capped"])
            self.assertTrue(all(220.0 <= frame["timestamp_seconds"] <= 580.0 for frame in candidate["frames"]))

    def test_continuation_and_closing_cues_link_without_creating_extra_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [
                    {"id": 1, "start": 100.0, "end": 105.0, "text": "This needs to be a ticket for the overlay."},
                    {"id": 2, "start": 200.0, "end": 210.0, "text": "Back to that ticket. The failure also happens on replay."},
                    {"id": 3, "start": 300.0, "end": 305.0, "text": "Done with that ticket."},
                ],
            )
            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=600.0)],
                    "pre_context_seconds": 10,
                    "post_context_seconds": 20,
                    "narration_context_pre_seconds": 20,
                    "narration_context_post_seconds": 500,
                    "narration_pause_threshold_seconds": 30,
                    "max_items": 20,
                }
            )

            self.assertEqual(result["detected_candidate_count"], 1)
            candidate = result["candidates"][0]
            narration = candidate["narration_context"]
            self.assertEqual(candidate["narration_context_boundary_type"], "closing")
            self.assertEqual(candidate["narration_context_end_seconds"], 305.0)
            self.assertIn("back to that ticket", narration["continuation_phrases"])
            self.assertIn("done with that ticket", narration["closing_phrases"])
            continuation = next(
                entry for entry in narration["entries"] if entry.get("segment_id") == 2
            )
            self.assertEqual(continuation["label"], "explicit_continuation_cue")

    def test_narration_horizon_warns_when_speech_may_continue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [
                    {"id": 1, "start": 100.0, "end": 105.0, "text": "That needs to be a ticket."},
                    {"id": 2, "start": 150.0, "end": 170.0, "text": "The explanation is still continuing at the configured horizon."},
                ],
            )
            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=500.0)],
                    "pre_context_seconds": 5,
                    "post_context_seconds": 10,
                    "narration_context_pre_seconds": 20,
                    "narration_context_post_seconds": 60,
                    "narration_pause_threshold_seconds": 30,
                    "max_items": 20,
                }
            )
            candidate = result["candidates"][0]
            self.assertTrue(candidate["narration_context_reached_horizon"])
            self.assertIn("may still be continuing", candidate["narration_context_warning"])

    def test_fragmented_narration_off_uses_focused_window_without_horizon_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [
                    {"id": 1, "start": 100.0, "end": 105.0, "text": "This needs to be a ticket."},
                    {"id": 2, "start": 108.0, "end": 115.0, "text": "The focused explanation continues."},
                ],
            )
            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=500.0)],
                    "pre_context_seconds": 5,
                    "post_context_seconds": 10,
                    "fragmented_narration_mode": False,
                    "narration_context_pre_seconds": 120,
                    "narration_context_post_seconds": 600,
                    "max_items": 20,
                }
            )

            candidate = result["candidates"][0]
            self.assertEqual(candidate["narration_context_start_seconds"], 95.0)
            self.assertEqual(candidate["narration_context_end_seconds"], 110.0)
            self.assertEqual(candidate["narration_context_boundary_type"], "focused_window_end")
            self.assertFalse(candidate["narration_context_reached_horizon"])
            self.assertEqual(candidate["narration_context_warning"], "")

    def test_overflow_index_can_be_rerun_by_stable_candidate_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [
                    {"id": 1, "start": 10.0, "end": 12.0, "text": "This needs to be a ticket for the first display."},
                    {"id": 2, "start": 250.0, "end": 252.0, "text": "Another ticket for the second display."},
                ],
            )
            request = {
                "output_dir": str(root / "out"),
                "sources": [_source(root, transcript, duration=500.0)],
                "pre_context_seconds": 1,
                "post_context_seconds": 1,
                "max_items": 1,
            }
            first = build_package_from_request(request)
            all_index = json.loads((root / "out" / "ALL_CANDIDATES.json").read_text(encoding="utf-8"))
            self.assertEqual(all_index["detected_candidate_count"], 2)
            self.assertEqual(all_index["unrendered_candidate_count"], 1)
            overflow = all_index["candidates"][1]
            self.assertEqual(overflow["evidence_id"], "ticket-002")
            self.assertEqual(overflow["render_status"], "unrendered")
            self.assertEqual(overflow["render_skip_reason"], "rich_evidence_limit")
            self.assertTrue((root / "out" / overflow["narration_context_path"]).exists())

            rerun = detect_from_request(
                {
                    **request,
                    "output_dir": str(root / "rerun"),
                    "render_candidate_ids": ["ticket-002"],
                }
            )
            self.assertEqual([item["evidence_id"] for item in rerun["candidates"]], ["ticket-002"])
            self.assertEqual(rerun["unrendered_candidates"][0]["evidence_id"], "ticket-001")
            self.assertTrue(rerun["candidates"][0]["frames"])

    def test_suspicious_transcript_risk_classification_separates_short_and_high_risk(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            short_transcript = root / "short.transcript.json"
            long_transcript = root / "long.transcript.json"
            repeated_segments = [{"id": 1, "start": 0.0, "end": 60.0, "text": " ".join(["You"] * 150)}]
            _write_transcript(short_transcript, repeated_segments)
            _write_transcript(long_transcript, repeated_segments)

            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [
                        _source(root, short_transcript, duration=120.0, source_id="short-clip"),
                        _source(root, long_transcript, duration=3600.0, source_id="long-clip"),
                    ],
                    "max_items": 50,
                }
            )

            quality_by_source = {source["source_id"]: source["transcript_quality"] for source in result["sources"]}
            self.assertEqual(
                quality_by_source["short-clip"]["risk_classification"],
                "suspicious_low_risk_short_clip",
            )
            self.assertEqual(
                quality_by_source["long-clip"]["risk_classification"],
                "suspicious_high_risk",
            )
            self.assertEqual(result["quality_summary"]["suspicious_high_risk_source_count"], 1)

    def test_sparse_safe_repetition_is_usable_with_non_blocking_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "safe-repetition.transcript.json"
            vocabulary = (
                "ticket widget layout panel folder label border export warning column margin "
                "dashboard header footer sector unit tooltip cursor filter window preset "
                "shortcut control preview status summary spacing operator review evidence "
                "source frame audio transcript compact outcome support correction validation"
            ).split()
            segments = []
            for index in range(30):
                text = "All right" if index in {2, 12, 22} else " ".join(
                    vocabulary[(index * step) % len(vocabulary)] for step in (1, 7, 13, 19)
                )
                segments.append(
                    {
                        "id": index + 1,
                        "start": float(index * 5),
                        "end": float(index * 5 + 2),
                        "text": text,
                    }
                )
            _write_transcript(transcript, segments)

            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=300.0, source_id="safe-repetition")],
                    "max_items": 50,
                }
            )

            quality = result["sources"][0]["transcript_quality"]
            self.assertEqual(quality["repeated_segment_ratio"], 0.0667)
            self.assertEqual(quality["max_consecutive_identical_segments"], 1)
            self.assertEqual(quality["quality_status"], "usable_with_warnings")
            self.assertTrue(quality["appears_usable"])
            self.assertEqual(quality["risk_classification"], "usable")

    def test_selected_audio_stream_array_is_normalized_to_single_stream(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(transcript, [{"id": 1, "start": 10.0, "end": 12.0, "text": "Make this a ticket."}])

            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [
                        _source(
                            root,
                            transcript,
                            selected_audio_stream=[
                                {
                                    "ordinal": 0,
                                    "ffmpeg_map": "0:a:0",
                                    "stream_index": 1,
                                    "codec_name": "aac",
                                }
                            ],
                        )
                    ],
                    "max_items": 50,
                }
            )

            selected = result["sources"][0]["selected_audio_stream"]
            self.assertEqual(selected["ffmpeg_map"], "0:a:0")
            self.assertEqual(selected["stream_index"], 1)

    def test_write_outputs_includes_pause_markers_and_json_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [
                    {"id": 1, "start": 1.0, "end": 3.0, "text": "We need to fix the first setup step."},
                    {"id": 2, "start": 55.0, "end": 58.0, "text": "More detail after a long pause."},
                ],
            )

            result = build_package_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=120)],
                    "pre_context_seconds": 5,
                    "post_context_seconds": 60,
                    "frame_offsets_seconds": [0],
                    "max_items": 50,
                    "artifact_results": {
                        "frames": [
                            {
                                "relative_path": "evidence_items/ticket-001/frames/full/clip-abc_00-00-01.jpg",
                                "path": str(root / "out" / "evidence_items/ticket-001/frames/full/clip-abc_00-00-01.jpg"),
                                "full_frame_path": str(root / "out" / "evidence_items/ticket-001/frames/full/clip-abc_00-00-01.jpg"),
                                "full_frame_width": 1280,
                                "full_frame_height": 720,
                                "panel_detection": "not_applicable",
                                "status": "created",
                                "error_message": "",
                            }
                        ],
                        "audio": [
                            {
                                "relative_path": "evidence_items/ticket-001/audio_snippet.mp3",
                                "path": str(root / "out" / "evidence_items/ticket-001/audio_snippet.mp3"),
                                "status": "created",
                                "error_message": "",
                            }
                        ],
                    },
                }
            )

            self.assertTrue(Path(result["manifest_path"]).exists())
            tickets = json.loads(Path(result["candidate_tickets_json_path"]).read_text(encoding="utf-8"))
            self.assertEqual(len(tickets["candidates"]), 1)
            window_text = (root / "out" / "evidence_items" / "ticket-001" / "transcript_window.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("[pause: 52.0 seconds]", window_text)
            metadata = json.loads((root / "out" / "evidence_items" / "ticket-001" / "metadata.json").read_text(encoding="utf-8"))
            self.assertTrue(any(frame["status"] == "created" for frame in metadata["frames"]))
            self.assertEqual(metadata["audio_snippet"]["status"], "created")

    def test_quality_flags_repeated_word_transcript_and_marker_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [
                    {"id": 1, "start": 0.0, "end": 100.0, "text": " ".join(["You"] * 250)},
                    {"id": 2, "start": 100.0, "end": 200.0, "text": "yeah yeah yeah"},
                ],
            )

            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=3600.0)],
                    "max_items": 50,
                }
            )

            quality = result["sources"][0]["transcript_quality"]
            self.assertFalse(quality["appears_usable"])
            self.assertIn("very low unique-word ratio", quality["warning_reasons"])
            self.assertEqual(quality["ticket_marker_counts"]["ticket"], 0)
            self.assertEqual(quality["dominant_word"], "you")

    def test_quality_counts_ticket_dashboard_and_simhub_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [
                    {
                        "id": 1,
                        "start": 10.0,
                        "end": 12.0,
                        "text": "Ticket. Put the dashboards at the top of the dashboard menu inside SimHub.",
                    },
                    {
                        "id": 2,
                        "start": 20.0,
                        "end": 23.0,
                        "text": "Make that like a maintenance ticket for the overlay.",
                    },
                ],
            )

            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=60.0)],
                    "max_items": 50,
                }
            )

            quality = result["sources"][0]["transcript_quality"]
            self.assertGreaterEqual(quality["ticket_marker_counts"]["ticket"], 2)
            self.assertEqual(quality["ticket_marker_counts"]["dashboard"], 1)
            self.assertEqual(quality["ticket_marker_counts"]["simhub"], 1)
            self.assertEqual(quality["ticket_marker_counts"]["maintenance"], 1)

    def test_custom_marker_terms_can_be_added_per_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [{"id": 1, "start": 10.0, "end": 12.0, "text": "The local widget needs a ticket."}],
            )

            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=60.0)],
                    "custom_markers": [{"phrase": "local widget", "confidence": "likely"}],
                    "max_items": 50,
                }
            )

            self.assertEqual(result["candidate_count"], 1)
            self.assertIn("local widget", result["candidates"][0]["detected_marker_phrases"])
            self.assertEqual(result["configuration"]["custom_marker_count"], 1)

    def test_custom_domain_terms_can_be_added_per_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [{"id": 1, "start": 10.0, "end": 12.0, "text": "The custom gauge is not showing."}],
            )

            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=60.0)],
                    "custom_domain_terms": ["custom gauge"],
                    "max_items": 50,
                }
            )

            self.assertEqual(result["candidate_count"], 0)
            self.assertEqual(result["review_needed_count"], 1)
            self.assertEqual(result["configuration"]["custom_domain_term_count"], 1)

    def test_duplicate_candidate_grouping_marks_a_renamed_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.transcript.json"
            second = root / "second.transcript.json"
            segments = [{"id": 1, "start": 90.0, "end": 95.0, "text": "Make a ticket for this dashboard issue."}]
            _write_transcript(first, segments)
            _write_transcript(second, segments)
            source_one = _source(root, first, duration=300.0)
            source_two = _source(
                root,
                second,
                duration=300.0,
                source_id="renamed-clip",
                source_identifier="renamed_clip.mp4",
                source_path=str(root / "renamed_clip.mp4"),
                source_filename="renamed_clip.mp4",
            )

            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [source_one, source_two],
                    "pre_context_seconds": 10,
                    "post_context_seconds": 10,
                    "max_items": 50,
                }
            )

            self.assertEqual(result["candidate_count"], 2)
            duplicate = result["candidates"][1]
            self.assertEqual(duplicate["duplicate_role"], "supporting_duplicate")
            self.assertEqual(duplicate["duplicate_of"], "ticket-001")

    def test_frame_cadence_and_max_frame_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(transcript, [{"id": 1, "start": 100.0, "end": 102.0, "text": "Here is a ticket."}])

            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=500.0)],
                    "pre_context_seconds": 60,
                    "post_context_seconds": 120,
                    "frame_offsets_seconds": [-60, 0, 120],
                    "frame_cadence_seconds": 10,
                    "max_frames_per_candidate": 8,
                    "max_items": 50,
                }
            )

            frames = result["candidates"][0]["frames"]
            self.assertLessEqual(len(frames), 8)
            self.assertTrue(any(frame["role"] == "offset" for frame in frames))
            self.assertTrue(any(frame["role"] == "cadence" for frame in frames))

    def test_three_panel_layout_detection(self) -> None:
        detected = detect_three_panel_layout(5760, 1080)
        self.assertEqual(detected["panel_detection"], "three_panel_5760x1080")
        self.assertEqual([panel["role"] for panel in detected["panels"]], ["overview_cam", "driver_view", "face_cam"])
        self.assertEqual(detected["panels"][1]["crop_x"], 1920)
        self.assertEqual(detected["panels"][2]["crop_x"], 3840)

        not_applicable = detect_three_panel_layout(1920, 1080)
        self.assertEqual(not_applicable["panel_detection"], "not_applicable")
        self.assertEqual(not_applicable["panels"], [])

        near_miss_width = detect_three_panel_layout(5761, 1080)
        self.assertEqual(near_miss_width["panel_detection"], "not_applicable")
        near_miss_height = detect_three_panel_layout(5760, 1081)
        self.assertEqual(near_miss_height["panel_detection"], "not_applicable")

    def test_shared_panel_crop_configuration_geometry(self) -> None:
        config = panel_crop_configuration("Auto")
        self.assertEqual(config["mode"], "auto")
        self.assertEqual(
            [panel["crop_filter"] for panel in config["panels"]],
            ["1920:1080:0:0", "1920:1080:1920:0", "1920:1080:3840:0"],
        )

    def test_detect_records_panel_crop_mode_and_full_review_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(transcript, [{"id": 1, "start": 1.0, "end": 2.0, "text": "Make this a ticket."}])

            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=30.0)],
                    "pre_context_seconds": 0,
                    "post_context_seconds": 5,
                    "frame_offsets_seconds": [0],
                    "frame_cadence_seconds": 0,
                    "max_frames_per_candidate": 1,
                    "max_items": 50,
                    "panel_crop_mode": "Auto",
                    "invocation_mode": "full-review-addon",
                }
            )

            self.assertEqual(result["configuration"]["invocation_mode"], "full-review-addon")
            panel_config = result["configuration"]["panel_crops"]
            self.assertEqual(panel_config["mode"], "auto")
            self.assertEqual(panel_config["panels"][0]["crop_filter"], "1920:1080:0:0")
            self.assertEqual(panel_config["panels"][1]["crop_filter"], "1920:1080:1920:0")
            self.assertEqual(panel_config["panels"][2]["crop_filter"], "1920:1080:3840:0")
            frame = result["candidates"][0]["frames"][0]
            self.assertEqual(frame["panel_crop_mode"], "auto")
            self.assertEqual(result["frame_tasks"][0]["panel_crop_mode"], "auto")

    def test_panel_crop_off_disables_panel_plans_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(transcript, [{"id": 1, "start": 1.0, "end": 2.0, "text": "Make this a ticket."}])

            detected = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=30.0)],
                    "pre_context_seconds": 0,
                    "post_context_seconds": 5,
                    "frame_offsets_seconds": [0],
                    "frame_cadence_seconds": 0,
                    "max_frames_per_candidate": 1,
                    "max_items": 50,
                    "panel_crop_mode": "Off",
                }
            )

            frame = detected["candidates"][0]["frames"][0]
            self.assertEqual(frame["panel_crop_mode"], "off")
            self.assertEqual(frame["panel_detection"], "disabled")
            self.assertEqual(frame["panels"], [])

            result = build_package_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=30.0)],
                    "pre_context_seconds": 0,
                    "post_context_seconds": 5,
                    "frame_offsets_seconds": [0],
                    "frame_cadence_seconds": 0,
                    "max_frames_per_candidate": 1,
                    "max_items": 50,
                    "panel_crop_mode": "Off",
                    "artifact_results": {
                        "frames": [
                            {
                                "relative_path": frame["relative_path"],
                                "path": frame["path"],
                                "full_frame_path": frame["full_frame_path"],
                                "full_frame_width": 5760,
                                "full_frame_height": 1080,
                                "panel_crop_mode": "off",
                                "panel_detection": "disabled",
                                "status": "created",
                                "error_message": "",
                                "panels": [],
                            }
                        ],
                        "audio": [],
                    },
                }
            )
            manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["configuration"]["panel_crops"]["mode"], "off")
            metadata = json.loads((root / "out" / "evidence_items" / "ticket-001" / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["frames"][0]["panel_detection"], "disabled")
            self.assertEqual(metadata["frames"][0]["panels"], [])

    def test_detect_plans_full_frames_and_safe_panel_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(transcript, [{"id": 1, "start": 1.0, "end": 2.0, "text": "Make this a ticket."}])

            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=30.0)],
                    "pre_context_seconds": 0,
                    "post_context_seconds": 5,
                    "frame_offsets_seconds": [0],
                    "frame_cadence_seconds": 0,
                    "max_frames_per_candidate": 1,
                    "max_items": 50,
                }
            )

            frame = result["candidates"][0]["frames"][0]
            self.assertEqual(
                frame["relative_path"],
                "artifacts/sources/clip-abc/frames/full/clip-abc_00-00-01-000.jpg",
            )
            self.assertEqual(frame["full_frame_relative_path"], frame["relative_path"])
            self.assertEqual([panel["role"] for panel in frame["panels"]], ["overview_cam", "driver_view", "face_cam"])
            self.assertEqual(
                frame["panels"][1]["relative_path"],
                "artifacts/sources/clip-abc/frames/panels/driver_view/clip-abc_00-00-01-000_driver_view.jpg",
            )

    def test_build_outputs_panel_metadata_frame_index_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(transcript, [{"id": 1, "start": 1.0, "end": 2.0, "text": "Make this a ticket."}])
            full_rel = "evidence_items/ticket-001/frames/full/clip-abc_00-00-01.jpg"
            panel_base = "evidence_items/ticket-001/frames/panels"

            result = build_package_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=30.0)],
                    "pre_context_seconds": 0,
                    "post_context_seconds": 5,
                    "frame_offsets_seconds": [0],
                    "frame_cadence_seconds": 0,
                    "max_frames_per_candidate": 1,
                    "max_items": 50,
                    "artifact_results": {
                        "frames": [
                            {
                                "relative_path": full_rel,
                                "path": str(root / "out" / full_rel),
                                "full_frame_path": str(root / "out" / full_rel),
                                "full_frame_width": 5760,
                                "full_frame_height": 1080,
                                "panel_detection": "three_panel_5760x1080",
                                "status": "created",
                                "error_message": "",
                                "panels": [
                                    {
                                        "role": "overview_cam",
                                        "label": "Overview Cam",
                                        "relative_path": f"{panel_base}/overview_cam/clip-abc_00-00-01_overview_cam.jpg",
                                        "path": str(root / "out" / panel_base / "overview_cam" / "clip-abc_00-00-01_overview_cam.jpg"),
                                        "crop_x": 0,
                                        "crop_y": 0,
                                        "crop_width": 1920,
                                        "crop_height": 1080,
                                        "panel_image_width": 1920,
                                        "panel_image_height": 1080,
                                        "status": "created",
                                        "error_message": "",
                                    },
                                    {
                                        "role": "driver_view",
                                        "label": "Driver View",
                                        "relative_path": f"{panel_base}/driver_view/clip-abc_00-00-01_driver_view.jpg",
                                        "path": str(root / "out" / panel_base / "driver_view" / "clip-abc_00-00-01_driver_view.jpg"),
                                        "crop_x": 1920,
                                        "crop_y": 0,
                                        "crop_width": 1920,
                                        "crop_height": 1080,
                                        "panel_image_width": 1920,
                                        "panel_image_height": 1080,
                                        "status": "created",
                                        "error_message": "",
                                    },
                                    {
                                        "role": "face_cam",
                                        "label": "Face Cam",
                                        "relative_path": f"{panel_base}/face_cam/clip-abc_00-00-01_face_cam.jpg",
                                        "path": str(root / "out" / panel_base / "face_cam" / "clip-abc_00-00-01_face_cam.jpg"),
                                        "crop_x": 3840,
                                        "crop_y": 0,
                                        "crop_width": 1920,
                                        "crop_height": 1080,
                                        "panel_image_width": 1920,
                                        "panel_image_height": 1080,
                                        "status": "created",
                                        "error_message": "",
                                    },
                                ],
                            }
                        ],
                        "audio": [],
                    },
                }
            )

            metadata = json.loads((root / "out" / "evidence_items" / "ticket-001" / "metadata.json").read_text(encoding="utf-8"))
            frame = metadata["frames"][0]
            self.assertEqual(frame["full_frame_width"], 5760)
            self.assertEqual(frame["panel_detection"], "three_panel_5760x1080")
            self.assertEqual(frame["panels"][1]["role"], "driver_view")
            self.assertEqual(frame["panels"][1]["status"], "created")

            with (root / "out" / "evidence_items" / "ticket-001" / "frame_index.csv").open(
                newline="", encoding="utf-8"
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 3)
            self.assertEqual(
                rows[1]["full_frame_path"],
                "artifacts/sources/clip-abc/frames/full/clip-abc_00-00-01-000.jpg",
            )
            self.assertEqual(rows[1]["full_frame_width"], "5760")
            self.assertEqual(rows[1]["panel_crop_mode"], "auto")
            self.assertEqual(rows[1]["panel_role"], "driver_view")
            self.assertEqual(rows[1]["panel_crop_x"], "1920")
            self.assertEqual(rows[1]["panel_image_width"], "1920")

            ticket_text = (root / "out" / "evidence_items" / "ticket-001" / "ticket.md").read_text(encoding="utf-8")
            self.assertIn("review the panel crops first", ticket_text)
            self.assertIn("Driver View", ticket_text)
            readme_text = Path(result["readme_path"]).read_text(encoding="utf-8")
            self.assertIn("Driver View crops", readme_text)

    def test_frame_times_stay_inside_video_duration_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(transcript, [{"id": 1, "start": 9.9, "end": 10.0, "text": "Make this a ticket."}])

            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=10.0)],
                    "pre_context_seconds": 1,
                    "post_context_seconds": 5,
                    "frame_offsets_seconds": [5],
                    "frame_cadence_seconds": 10,
                    "max_frames_per_candidate": 10,
                    "max_items": 50,
                }
            )

            timestamps = [frame["timestamp_seconds"] for frame in result["candidates"][0]["frames"]]
            self.assertLessEqual(max(timestamps), 9.75)

    def test_quality_report_and_manifest_include_quality_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(transcript, [{"id": 1, "start": 5.0, "end": 6.0, "text": "Make this a ticket."}])

            result = build_package_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [
                        _source(
                            root,
                            transcript,
                            duration=60,
                            audio_path=str(root / "audio" / "clip-abc.audio.mp3"),
                            audio_status="completed",
                            audio_method="extracted_audio",
                            audio_stream_count=2,
                            selected_audio_stream_index=0,
                        )
                    ],
                    "pre_context_seconds": 5,
                    "post_context_seconds": 10,
                    "max_items": 50,
                }
            )

            self.assertTrue(Path(result["quality_report_path"]).exists())
            quality_report = Path(result["quality_report_path"]).read_text(encoding="utf-8")
            self.assertIn("Evidence Quality Report", quality_report)
            self.assertIn("Audio method: extracted_audio", quality_report)
            manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
            self.assertIn("quality_summary", manifest)
            self.assertIn("transcript_quality", manifest["sources"][0])
            self.assertEqual(manifest["sources"][0]["audio_method"], "extracted_audio")

    def test_weak_marker_sets_insufficient_evidence_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(transcript, [{"id": 1, "start": 5.0, "end": 6.0, "text": "Remember this."}])

            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript)],
                    "pre_context_seconds": 5,
                    "post_context_seconds": 5,
                    "max_items": 50,
                }
            )

            self.assertEqual(result["candidate_count"], 1)
            self.assertEqual(result["candidates"][0]["confidence"], "weak")
            self.assertTrue(result["candidates"][0]["not_enough_evidence"])

    def test_max_items_truncates_candidate_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [
                    # 199: requests, not single words said in passing.
                    {"id": 1, "start": 10.0, "end": 12.0, "text": "Make a ticket for the first area."},
                    {"id": 2, "start": 200.0, "end": 202.0, "text": "Open an issue for the second area."},
                    {"id": 3, "start": 400.0, "end": 402.0, "text": "Make this a task for the third area."},
                ],
            )

            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=500)],
                    "pre_context_seconds": 5,
                    "post_context_seconds": 5,
                    "max_items": 2,
                }
            )

            self.assertEqual(result["candidate_count"], 2)
            self.assertEqual(result["truncated_candidates_count"], 1)

    def test_cli_writes_evidence_package_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [{"id": 1, "start": 5.0, "end": 8.0, "text": "Codex should make a ticket from this."}],
            )
            request_path = root / "request.json"
            result_path = root / "result.json"
            write_json_file(
                request_path,
                CommandEnvelope(
                    payload={
                        "output_dir": str(root / "out"),
                        "sources": [_source(root, transcript, duration=30)],
                        "pre_context_seconds": 5,
                        "post_context_seconds": 10,
                        "max_items": 50,
                    }
                ).to_dict(),
            )

            exit_code = main(["evidence-package-build", "--request-file", str(request_path), "--result-file", str(result_path)])
            response = read_json_file(result_path)

            self.assertEqual(exit_code, 0)
            self.assertTrue(response["ok"])
            self.assertEqual(response["data"]["candidate_count"], 1)
            self.assertTrue((root / "out" / "README_FOR_AI.md").exists())

    def test_repo_hints_default_to_unknown_without_target_or_map(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(transcript, [{"id": 1, "start": 5.0, "end": 8.0, "text": "Make this a ticket."}])

            result = build_package_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=30)],
                    "pre_context_seconds": 5,
                    "post_context_seconds": 10,
                    "max_items": 50,
                }
            )

            candidate = result["candidates"][0]
            self.assertEqual(candidate["likely_target_repo"], "UNKNOWN")
            self.assertEqual(candidate["repo_confidence"], "unknown")
            self.assertTrue(candidate["requires_github_review"])
            self.assertTrue((root / "out" / "REPO_ROUTING_HINTS.md").exists())
            self.assertTrue((root / "out" / "REPO_ROUTING_HINTS.json").exists())
            readme = (root / "out" / "README_FOR_AI.md").read_text(encoding="utf-8")
            self.assertIn("Review `REPO_ROUTING_HINTS.md`", readme)

    def test_evidence_target_repo_override_wins_and_is_written_to_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(
                transcript,
                [{"id": 1, "start": 5.0, "end": 8.0, "text": "Make this a ticket for the SimHub dashboard."}],
            )

            result = build_package_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=30)],
                    "target_repo": "example-org/example-project",
                    "repo_hint_mode": "auto",
                    "max_items": 50,
                }
            )

            candidate = result["candidates"][0]
            self.assertEqual(candidate["likely_target_repo"], "example-org/example-project")
            self.assertEqual(candidate["repo_confidence"], "operator_specified")
            self.assertEqual(candidate["repo_hint_source"], "operator_target")
            self.assertTrue(candidate["requires_github_review"])
            candidate_md = (root / "out" / "CANDIDATE_TICKETS.md").read_text(encoding="utf-8")
            ticket_md = (root / "out" / "evidence_items" / "ticket-001" / "ticket.md").read_text(encoding="utf-8")
            self.assertIn("Repo routing hint: example-org/example-project", candidate_md)
            self.assertIn("Repo Routing Hint", ticket_md)
            self.assertIn("Confirm with GitHub issue lookup", ticket_md)

    def test_repo_hints_ignore_the_tools_own_profile_name(self) -> None:
        """109: 'iRacing Ticket Evidence - Balanced' routed narration to the Workbench."""

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            repo_map = root / "config" / "evidence_repo_hints.json"
            _write_repo_map(
                repo_map,
                {
                    "Example/overlay-hub": {"project_label": "Overlay hub", "keywords": ["dashboard"]},
                    "Aintologic/media-manglers": {
                        "project_label": "Media Manglers",
                        "keywords": ["ticket evidence", "evidence package"],
                    },
                },
            )
            _write_transcript(
                transcript,
                [{"id": 1, "start": 5.0, "end": 8.0,
                  "text": "That's a bug here. The dashboard doesn't know turn six has a name."}],
            )
            result = build_package_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=30)],
                    "repo_map_path": str(repo_map),
                    "run_metadata": {"profile_setup_name": "iRacing Ticket Evidence - Balanced",
                                     "application_version": "Video Mangler evidence package"},
                    "max_items": 50,
                }
            )
            candidate = result["candidates"][0]
            self.assertEqual(candidate["likely_target_repo"], "Example/overlay-hub")
            self.assertNotIn(
                "Aintologic/media-manglers",
                [item["repo"] for item in candidate.get("alternate_repos") or []],
            )

    def test_repo_map_keyword_scoring_sets_high_confidence_and_manifest_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            repo_map = root / "config" / "evidence_repo_hints.json"
            _write_repo_map(
                repo_map,
                {
                    "example-org/example-project": {
                        "project_label": "Example App / Example Project",
                        "keywords": ["SimHub", "lap timer", "dashboard", "brake bias", "sector", "slowdown"],
                    },
                    "Aintologic/media-manglers": {
                        "project_label": "Media Manglers",
                        "keywords": ["evidence package", "transcript"],
                    },
                },
            )
            _write_transcript(
                transcript,
                [
                    {
                        "id": 1,
                        "start": 5.0,
                        "end": 8.0,
                        "text": "Make this a ticket for the SimHub lap timer dashboard, brake bias, sector, and slowdown display.",
                    }
                ],
            )

            result = build_package_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=30)],
                    "repo_map_path": str(repo_map),
                    "max_items": 50,
                }
            )

            candidate = result["candidates"][0]
            self.assertEqual(candidate["likely_target_repo"], "example-org/example-project")
            self.assertEqual(candidate["target_project_label"], "Example App / Example Project")
            self.assertEqual(candidate["repo_confidence"], "high")
            self.assertEqual(candidate["repo_hint_source"], "repo_map")
            manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["repo_hint_summary"]["target_repo_counts"]["example-org/example-project"], 1)
            routing = json.loads(Path(result["repo_routing_hints_json_path"]).read_text(encoding="utf-8"))
            self.assertEqual(routing["summary"]["requires_github_review_count"], 1)
            prompt = (root / "out" / "operator-drafts" / "session.claude.md").read_text(encoding="utf-8")
            self.assertIn("example-org/example-project", prompt)
            self.assertNotIn("No operator repo map", prompt)

    def test_project_list_is_read_from_nested_write_time_configuration(self) -> None:
        # 94: the two-step backend passes the detect configuration, where the
        # repo map lives under repo_hinting; the prompt said "no repo map".
        from media_manglers.core.evidence_package import _configured_projects

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_map = Path(temp_dir) / "repo-map.json"
            _write_repo_map(repo_map, {"Owner/one": {"project_label": "One", "keywords": ["x"]}})
            projects = _configured_projects(
                {"repo_hinting": {"mode": "auto", "repo_map_path": str(repo_map), "repo_map_loaded": True}}
            )
        self.assertIn("Owner/one", projects)

    def test_repo_map_tie_marks_candidate_ambiguous_with_alternate_repos(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            repo_map = root / "repo-map.json"
            _write_repo_map(
                repo_map,
                {
                    "example-org/a-alpha": {"project_label": "Alpha", "keywords": ["dashboard"]},
                    "example-org/b-beta": {"project_label": "Beta", "keywords": ["dashboard"]},
                },
            )
            _write_transcript(
                transcript,
                [{"id": 1, "start": 5.0, "end": 8.0, "text": "Make this a ticket for the dashboard."}],
            )

            result = build_package_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=30)],
                    "repo_map_path": str(repo_map),
                    "max_items": 50,
                }
            )

            candidate = result["candidates"][0]
            self.assertTrue(candidate["repo_hint_is_ambiguous"])
            self.assertEqual(candidate["repo_confidence"], "low")
            self.assertEqual(candidate["likely_target_repo"], "example-org/a-alpha")
            self.assertEqual(candidate["alternate_repos"][0]["repo"], "example-org/b-beta")
            routing_md = Path(result["repo_routing_hints_markdown_path"]).read_text(encoding="utf-8")
            self.assertIn("Candidates With Ambiguous Repo Hints", routing_md)
            self.assertIn("ticket-001", routing_md)

    def test_invalid_repo_map_warns_and_falls_back_to_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            repo_map = root / "bad-map.json"
            repo_map.write_text("{ invalid json", encoding="utf-8")
            _write_transcript(transcript, [{"id": 1, "start": 5.0, "end": 8.0, "text": "Make this a ticket."}])

            result = build_package_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=30)],
                    "repo_map_path": str(repo_map),
                    "max_items": 50,
                }
            )

            candidate = result["candidates"][0]
            self.assertEqual(candidate["likely_target_repo"], "UNKNOWN")
            self.assertTrue(result["configuration"]["repo_hinting"]["warnings"])
            routing_md = Path(result["repo_routing_hints_markdown_path"]).read_text(encoding="utf-8")
            self.assertIn("Repo hint map could not be loaded", routing_md)

    def test_scoped_glossary_preserves_raw_and_writes_correction_audit(self) -> None:
        canonical = "Pixel Garden 480"
        alias = "Pickle Garden 480"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            raw_text = f"Make this a ticket for the {alias} overlay."
            _write_transcript(
                transcript,
                [{"id": 1, "start": 12.0, "end": 16.0, "text": raw_text}],
            )
            result = build_package_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=60)],
                    "transcription_glossary_entries": [f"{canonical}={alias}"],
                    "max_items": 10,
                }
            )

            self.assertIn(canonical, result["candidates"][0]["transcript_excerpt"])
            self.assertIn(canonical, result["candidates"][0]["suggested_issue_title"])
            self.assertNotIn("make this a ticket", result["candidates"][0]["suggested_issue_title"].lower())
            corrections = json.loads(
                (root / "out" / "TRANSCRIPT_CORRECTIONS.json").read_text(encoding="utf-8")
            )
            self.assertEqual(corrections["correction_record_count"], 1)
            self.assertEqual(corrections["corrections"][0]["raw_text"], raw_text)
            self.assertIn(canonical, corrections["corrections"][0]["corrected_text"])
            raw_full = (root / "out" / "transcript" / "raw" / "full_transcript.md").read_text(encoding="utf-8")
            corrected_full = (root / "out" / "transcript" / "full_transcript.md").read_text(encoding="utf-8")
            self.assertIn(alias, raw_full)
            self.assertNotIn(alias, corrected_full)
            self.assertIn(canonical, corrected_full)

    def test_supporting_game_audio_transcript_does_not_create_operator_ticket(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            operator_transcript = root / "operator.transcript.json"
            game_transcript = root / "game.transcript.json"
            _write_transcript(
                operator_transcript,
                [{"id": 1, "start": 10, "end": 14, "text": "Make this a ticket for the export ordering."}],
            )
            _write_transcript(
                game_transcript,
                [
                    {"id": 1, "start": 10, "end": 11, "text": "Car left, still there, clear left. That's a bug."},
                    {"id": 2, "start": 12, "end": 13, "text": "Car left, still there, clear left. That's a bug."},
                ],
            )
            operator = _source(root, operator_transcript, duration=60)
            operator.update(
                {
                    "audio_streams": [
                        {"ordinal": 0, "codec_name": "aac", "title": "Microphone"},
                        {"ordinal": 1, "codec_name": "aac", "title": "Game"},
                    ],
                    "selected_audio_stream_index": 0,
                    "selected_audio_stream": {"ordinal": 0, "codec_name": "aac", "title": "Microphone"},
                    "audio_stream_selection_confirmed": True,
                }
            )
            game = _source(root, game_transcript, duration=60)
            game.update(
                {
                    "source_id": "clip-game-audio",
                    "source_filename": "clip-game-audio.mkv",
                    "transcript_audio_role": "supporting_audio",
                }
            )
            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [operator, game],
                    "max_items": 10,
                    "preserve_supporting_audio": True,
                }
            )

            self.assertEqual(result["candidate_count"], 1)
            self.assertEqual(result["candidates"][0]["source_id"], "clip-abc")
            self.assertEqual(result["configuration"]["supporting_audio_source_count"], 1)
            self.assertEqual(len(result["candidates"][0]["supporting_audio_snippets"]), 1)
            self.assertEqual(result["candidates"][0]["supporting_audio_snippets"][0]["audio_stream_index"], 1)
            self.assertEqual(len(result["audio_tasks"]), 2)
            game_quality = next(source for source in result["sources"] if source["source_id"] == "clip-game-audio")["transcript_quality"]
            self.assertTrue(game_quality["game_spotter_contamination_suspected"])

    def test_repeated_marker_segments_cluster_into_one_mention(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip.transcript.json"
            repeated = "That's a big bug, make this a ticket for the timing banner."
            _write_transcript(
                transcript,
                [
                    {"id": 1, "start": 20, "end": 23, "text": repeated},
                    {"id": 2, "start": 24, "end": 27, "text": repeated},
                    {"id": 3, "start": 28, "end": 31, "text": repeated},
                ],
            )
            result = detect_from_request(
                {"output_dir": str(root / "out"), "sources": [_source(root, transcript)], "max_items": 10}
            )
            self.assertEqual(result["candidate_count"], 1)
            event = result["candidates"][0]["marker_events"][0]
            self.assertEqual(len(event["duplicate_occurrences"]), 2)

    def test_explicit_boundaries_split_three_requests_inside_one_segment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip.transcript.json"
            _write_transcript(
                transcript,
                [
                    {
                        "id": 1,
                        "start": 10,
                        "end": 40,
                        "text": (
                            "Make this a ticket for export ordering. "
                            "Next issue, make this a ticket for menu sorting. "
                            "Another bug, make this a ticket for label contrast."
                        ),
                    }
                ],
            )
            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=90)],
                    "pre_context_seconds": 30,
                    "post_context_seconds": 60,
                    "max_items": 10,
                }
            )
            self.assertEqual(result["candidate_count"], 3)
            self.assertEqual(len({item["suggested_issue_title"] for item in result["candidates"]}), 3)

    def test_intent_correction_does_not_create_a_second_ticket(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip.transcript.json"
            _write_transcript(
                transcript,
                [
                    {"id": 1, "start": 10, "end": 14, "text": "Make this a ticket for the panel."},
                    {"id": 2, "start": 15, "end": 20, "text": "Actually, I'm sorry, not a fix - a feature. Same ticket."},
                ],
            )
            result = detect_from_request(
                {"output_dir": str(root / "out"), "sources": [_source(root, transcript)], "max_items": 10}
            )
            self.assertEqual(result["candidate_count"], 1)
            narration = result["candidates"][0]["narration_context"]
            self.assertIn("same ticket", narration["continuation_phrases"])

    def test_review_needed_windows_group_and_promote_actionable_extended_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip.transcript.json"
            _write_transcript(
                transcript,
                [
                    {"id": 1, "start": 90, "end": 94, "text": "I want to add an incident bar to the dashboard."},
                    {"id": 2, "start": 98, "end": 102, "text": "The incident bar should show the latest event."},
                    {"id": 3, "start": 106, "end": 110, "text": "The dashboard needs to show that incident bar."},
                ],
            )
            result = build_package_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=180)],
                    "pre_context_seconds": 60,
                    "post_context_seconds": 90,
                    "max_items": 10,
                }
            )
            self.assertEqual(result["candidate_count"], 0)
            self.assertEqual(result["review_needed_count"], 1)
            item = result["review_needed"][0]
            self.assertEqual(item["marker_timestamp_seconds"], 90.0)
            self.assertEqual(item["grouped_occurrence_count"], 3)
            self.assertEqual(item["promotion_status"], "unassigned_ticket_mention")
            timeline = json.loads((root / "out" / "SESSION_TIMELINE.json").read_text(encoding="utf-8"))
            review_record = next(record for record in timeline["records"] if record["record_type"] == "review_needed")
            self.assertEqual(review_record["timestamp_seconds"], 90.0)
            unassigned = json.loads((root / "out" / "UNASSIGNED_MENTIONS.json").read_text(encoding="utf-8"))
            self.assertIn("review-001", [mention["mention_id"] for mention in unassigned["mentions"]])

    def test_quality_warns_on_repetition_language_and_gibberish(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip.transcript.json"
            bad = "Brrrkr zzztrn qqqplm nnnkrt bbbgrt cccdrt pppklm xxxtrn."
            _write_transcript(
                transcript,
                [
                    {"id": 1, "start": 1, "end": 3, "text": bad},
                    {"id": 2, "start": 4, "end": 6, "text": bad},
                    {"id": 3, "start": 7, "end": 9, "text": bad},
                    {"id": 4, "start": 10, "end": 12, "text": "Привет мир dashboard."},
                ],
            )
            result = detect_from_request(
                {"output_dir": str(root / "out"), "sources": [_source(root, transcript, duration=900)]}
            )
            quality = result["sources"][0]["transcript_quality"]
            self.assertEqual(quality["quality_status"], "suspicious")
            self.assertGreaterEqual(quality["repeated_segment_count"], 2)
            self.assertGreaterEqual(quality["gibberish_like_segment_count"], 2)
            self.assertFalse(quality["appears_usable"])

    def test_source_aware_crop_map_adds_dashboard_monitor_role(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip.transcript.json"
            _write_transcript(
                transcript,
                [{"id": 1, "start": 10, "end": 14, "text": "Make this a ticket for the dashboard monitor."}],
            )
            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=60)],
                    "frame_offsets_seconds": [0],
                    "max_frames_per_candidate": 1,
                    "panel_role_mapping": {
                        "panels": [
                            {
                                "role": "top_dashboard_monitor",
                                "label": "Top Dashboard Monitor",
                                "purpose": "Dedicated dashboard evidence",
                                "expected_evidence_types": ["dashboard UI"],
                                "crop_x": 0,
                                "crop_y": 0,
                                "crop_width": 1920,
                                "crop_height": 360,
                            }
                        ]
                    },
                }
            )
            panel = next(
                item
                for item in result["candidates"][0]["frames"][0]["panels"]
                if item["role"] == "top_dashboard_monitor"
            )
            self.assertEqual(panel["purpose"], "Dedicated dashboard evidence")
            self.assertIn("dashboard UI", panel["expected_evidence_types"])

    def test_ticket_markdown_keeps_exhaustive_frames_in_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip.transcript.json"
            _write_transcript(
                transcript,
                [{"id": 1, "start": 30, "end": 34, "text": "Make this a ticket for export ordering."}],
            )
            result = build_package_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": [_source(root, transcript, duration=120)],
                    "pre_context_seconds": 20,
                    "post_context_seconds": 40,
                    "frame_offsets_seconds": [-20, -10, 0, 10, 20, 30, 40],
                    "frame_cadence_seconds": 1,
                    "max_frames_per_candidate": 50,
                    "max_items": 10,
                }
            )
            candidate = result["candidates"][0]
            ticket = (root / "out" / candidate["ticket_path"]).read_text(encoding="utf-8")
            self.assertLessEqual(ticket.count("- Full frame:"), 3)
            self.assertIn("Exhaustive frame inventory", ticket)
            self.assertTrue((root / "out" / candidate["frame_index_path"]).is_file())

    def test_a_recording_waiting_for_a_track_choice_is_missing_not_empty(self) -> None:
        # 142: the backend could not tell which track is the microphone, so
        # the recording was never transcribed. It is full of speech: nothing in
        # the package may tell the agent it had no narration.
        asked = (
            "Multiple audio tracks: the app could not tell which track is your microphone in 'asked.mkv'. "
            "Track 2 (394 clear words) and Track 1 (266) carry speech, but each of them is also busy with other "
            "sound (a full mix, game audio or music), so the app cannot tell which one is your microphone. "
            "In Find my bug reports, press Fix and continue, right-click this recording, choose the track with "
            "your voice, then press Continue. The backend will not guess."
        )
        quiet = "Your usual microphone track, Track 2, has sound but no clear speech."
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            placeholder = root / "asked.transcript.json"
            none_found = root / "quiet.transcript.json"
            real = root / "real.transcript.json"
            _write_transcript(placeholder, [])
            _write_transcript(none_found, [])
            _write_transcript(
                real,
                [{"id": 1, "start": 30.0, "end": 36.0, "text": "Please make this a ticket, the delta bar is broken."}],
            )
            sources = [
                {
                    **_source(root, placeholder, duration=650.0, status="failed", error_message=asked),
                    "source_id": "asked",
                    "source_filename": "asked.mkv",
                    "audio_stream_count": 6,
                },
                {
                    **_source(root, none_found, duration=650.0, status="no_narration", error_message=quiet),
                    "source_id": "quiet",
                    "source_filename": "quiet.mkv",
                    "audio_stream_count": 6,
                },
                {**_source(root, real), "source_id": "real", "source_filename": "real.mkv"},
            ]
            # The real "evidence-package-build" path: detection, then every file.
            build_package_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": sources,
                    "pre_context_seconds": 10,
                    "post_context_seconds": 20,
                    "max_items": 50,
                }
            )
            out = root / "out"
            readme = (out / "README_FOR_AI.md").read_text(encoding="utf-8")
            report = (out / "EVIDENCE_QUALITY_REPORT.md").read_text(encoding="utf-8")
            status = json.loads((out / "PACKAGE_STATUS.json").read_text(encoding="utf-8"))
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))

        by_id = {source["source_id"]: source["transcript_quality"] for source in manifest["sources"]}
        waiting = by_id["asked"]
        self.assertEqual(waiting["quality_status"], "needs_track_choice")
        self.assertEqual(waiting["risk_classification"], "needs_track_choice")
        self.assertFalse(waiting["no_narration_found"])
        self.assertFalse(waiting["appears_usable"])
        # Word counts of a transcript that was never made say nothing.
        self.assertEqual(
            waiting["warning_reasons"], ["not transcribed yet: the operator has to choose which audio track is the microphone"]
        )
        self.assertIn("missing, not empty", waiting["recommended_action"])
        self.assertEqual(manifest["quality_summary"]["needs_track_choice_source_count"], 1)
        self.assertIn("still need a voice-track choice", readme)
        self.assertIn("- Waiting for a voice-track choice: 1", report)
        self.assertTrue(any("voice-track choice" in warning for warning in status.get("warnings", [])))
        # A genuine "no narration" says what was heard, not that a selected
        # track was silent: no track was selected.
        none = by_id["quiet"]
        self.assertEqual(none["quality_status"], "no_narration_found")
        self.assertIn(quiet, none["risk_reason"])
        self.assertIn(f"no narration found: {quiet}", none["warning_reasons"])
        for reason in (*waiting["warning_reasons"], *none["warning_reasons"], waiting["risk_reason"], none["risk_reason"]):
            self.assertNotIn("selected microphone track", reason)
        self.assertEqual(by_id["real"]["quality_status"], "usable")

    def test_silent_and_invented_transcripts_are_reported_and_never_scanned(self) -> None:
        # 94: a silent microphone track or Whisper filler on silence must not
        # be labelled usable, and must never produce ticket candidates.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            silent = root / "silent.transcript.json"
            invented = root / "invented.transcript.json"
            real = root / "real.transcript.json"
            _write_transcript(silent, [])
            _write_transcript(
                invented,
                [
                    {"id": index, "start": float(index * 10), "end": float(index * 10 + 2), "text": "Thank you for watching!"}
                    for index in range(8)
                ],
            )
            _write_transcript(
                real,
                [{"id": 1, "start": 30.0, "end": 36.0, "text": "Please make this a ticket, the delta bar is broken."}],
            )
            sources = [
                {**_source(root, silent), "source_id": "silent", "source_filename": "silent.mkv"},
                {**_source(root, invented), "source_id": "invented", "source_filename": "invented.mkv"},
                {**_source(root, real), "source_id": "real", "source_filename": "real.mkv"},
            ]
            result = detect_from_request(
                {
                    "output_dir": str(root / "out"),
                    "sources": sources,
                    "pre_context_seconds": 10,
                    "post_context_seconds": 20,
                    "max_items": 50,
                }
            )

        by_id = {source["source_id"]: source for source in result["sources"]}
        self.assertEqual(by_id["silent"]["transcript_quality"]["quality_status"], "no_narration_found")
        self.assertFalse(by_id["silent"]["transcript_quality"]["appears_usable"])
        self.assertTrue(by_id["invented"]["transcript_quality"]["silence_hallucination_suspected"])
        self.assertEqual(by_id["invented"]["transcript_quality"]["quality_status"], "no_narration_found")
        self.assertFalse(by_id["invented"]["transcript_quality"]["appears_usable"])
        self.assertEqual(by_id["real"]["transcript_quality"]["quality_status"], "usable")
        candidate_sources = {candidate["source_id"] for candidate in result["candidates"]}
        self.assertEqual(candidate_sources, {"real"})


class MentionedNotAskedTests(unittest.TestCase):
    """199: a word like "ticket" or "fix this" said in passing is not a request. It never makes
    a ticket on its own, and it is never hidden either: it is listed for the operator to decide."""

    SEGMENTS = [
        {"id": 1, "start": 15.0, "end": 18.0, "text": "Perhaps a restart will fix this."},
        {"id": 2, "start": 140.0, "end": 143.0, "text": "The ticket price for that event went up again."},
        {"id": 3, "start": 260.0, "end": 266.0, "text": "Create a ticket for the fuel display, it shows the wrong lap."},
    ]

    def _build(self, root: Path, *, status: str = "completed") -> dict:
        transcript = root / "clip-abc.transcript.json"
        _write_transcript(transcript, self.SEGMENTS)
        return build_package_from_request(
            {
                "output_dir": str(root / "out"),
                "sources": [_source(root, transcript, duration=300.0, status=status)],
                "pre_context_seconds": 5,
                "post_context_seconds": 10,
                "max_items": 50,
            }
        )

    def test_a_passing_remark_is_listed_and_never_made_a_ticket(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = self._build(root)
            out = root / "out"
            listed = json.loads((out / "MENTIONED_NOT_ASKED.json").read_text(encoding="utf-8"))
            markdown = (out / "MENTIONED_NOT_ASKED.md").read_text(encoding="utf-8")
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            audit = json.loads((out / "MARKER_AUDIT.json").read_text(encoding="utf-8"))
        # Only the real request is a ticket, and "wrong" inside it does not make a second one.
        self.assertEqual(result["candidate_count"], 1)
        self.assertIn("create a ticket", result["candidates"][0]["detected_marker_phrases"])
        items = listed["items"]
        self.assertEqual([(item["timestamp"], item["words"]) for item in items],
                         [("00:00:15.000", ["fix this"]), ("00:02:20.000", ["ticket"])])
        self.assertEqual(items[0]["text"], "Perhaps a restart will fix this.")
        self.assertEqual(items[1]["source_filename"], "clip.mp4")
        self.assertIn("# Mentioned, not asked for", markdown)
        self.assertIn("00:02:20.000", markdown)
        self.assertIn("The ticket price for that event went up again.", markdown)
        self.assertEqual(manifest["mentioned_not_asked_count"], 2)
        self.assertEqual(manifest["mentioned_not_asked_markdown_path"], "MENTIONED_NOT_ASKED.md")
        # The audit does not report the listed remark as a marker nobody covered.
        self.assertEqual(audit["summary"]["uncovered_marker_hits"], 0)
        remark = next(hit for hit in audit["markers"] if hit["timestamp"] == "00:02:20.000")
        self.assertEqual(remark["status"], "mentioned_not_asked")

    def test_a_remark_right_after_a_request_is_listed_too(self) -> None:
        # A request, then a passing remark seconds later, inside the ticket's evidence window.
        # The remark is not part of the request and must not vanish.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(transcript, [
                {"id": 0, "start": 6.1, "end": 8.1, "text": "Instructions for AI"},
                {"id": 1, "start": 8.1, "end": 10.1, "text": "Create a ticket"},
                {"id": 2, "start": 10.1, "end": 14.1, "text": "The pit board should show the gap to the car behind"},
                {"id": 3, "start": 17.6, "end": 21.9, "text": "Perhaps a restart will fix this."},
            ])
            result = build_package_from_request({
                "output_dir": str(root / "out"),
                "sources": [_source(root, transcript, duration=32.0)],
                "pre_context_seconds": 120, "post_context_seconds": 240, "max_items": 50,
            })
            listed = json.loads((root / "out" / "MENTIONED_NOT_ASKED.json").read_text(encoding="utf-8"))
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual([(item["timestamp_seconds"], item["words"]) for item in listed["items"]],
                         [(17.6, ["fix this"])])

    def test_requests_said_in_other_words_are_still_tickets(self) -> None:
        # Real request styles must not be lost: common phrasings, and "Ticket." or "Bug:" said as a
        # heading at the start of a sentence. Inside a sentence the word stays a mention.
        lines = [
            (20.0, "Make a ticket for the dashboard order."),
            (200.0, "Open an issue for the pit board, it flickers."),
            (380.0, "Ticket. Put the dashboards at the top of the menu."),
            (560.0, "Okay. Bug: the delta bar resets every lap."),
            (740.0, "Here is a ticket for the fuel display."),
            (920.0, "The ticket price for that event went up again."),
            (1100.0, "That corner was a bug, honestly, I always miss it."),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "clip-abc.transcript.json"
            _write_transcript(transcript, [{"id": i, "start": t, "end": t + 3, "text": text} for i, (t, text) in enumerate(lines)])
            result = build_package_from_request({
                "output_dir": str(root / "out"),
                "sources": [_source(root, transcript, duration=1300.0)],
                "pre_context_seconds": 5, "post_context_seconds": 10, "max_items": 50,
            })
            listed = json.loads((root / "out" / "MENTIONED_NOT_ASKED.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(item["marker_timestamp_seconds"] for item in result["candidates"]),
                         [20.0, 200.0, 380.0, 560.0, 740.0])
        self.assertEqual([item["timestamp_seconds"] for item in listed["items"]], [920.0, 1100.0])

    def test_a_skipped_recording_is_not_listed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._build(root, status="operator_skipped")
            listed = json.loads((root / "out" / "MENTIONED_NOT_ASKED.json").read_text(encoding="utf-8"))
        self.assertEqual(listed["items"], [])

    def test_the_agent_is_told_to_show_the_list_and_never_file_from_it(self) -> None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
        from media_manglers_workbench.evidence import load_evidence_package
        from media_manglers_workbench.prompts import build_session_prompt

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._build(root)
            start_here = (root / "out" / "START_HERE_FOR_TICKET_AGENT.md").read_text(encoding="utf-8")
            prompt = build_session_prompt(load_evidence_package(root / "out"), "Claude Code")
        for text in (start_here, prompt):
            self.assertIn("MENTIONED_NOT_ASKED.md", text)
            self.assertIn("never draft or file an issue from it on your own", text)
        self.assertIn("2 moments", prompt)


if __name__ == "__main__":
    unittest.main()
