from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core.session_review import (  # noqa: E402
    build_portable_agent_zip,
    build_session_review,
    local_io_path,
    write_session_review_artifacts,
)


def _candidate(
    candidate_id: str,
    minute: int,
    text: str,
    *,
    marker: str = "this needs to be a ticket",
    rendered: bool = True,
    continuation: list[str] | None = None,
) -> dict[str, object]:
    seconds = minute * 60
    return {
        "evidence_id": candidate_id,
        "source_id": "two-hour-session",
        "source_filename": "iracing-session.mkv",
        "marker_timestamp_seconds": seconds,
        "marker_timestamp": f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:00.000",
        "timestamp_start_seconds": seconds - 90,
        "timestamp_end_seconds": seconds + 120,
        "detected_marker_phrases": [marker],
        "confidence": "explicit",
        "transcript_excerpt": text,
        "suggested_issue_title": text,
        "ticket_path": f"evidence_items/{candidate_id}/ticket.md",
        "transcript_window_path": f"evidence_items/{candidate_id}/transcript_window.md",
        "narration_context_path": f"evidence_items/{candidate_id}/narration_context.md",
        "narration_context_json_path": f"evidence_items/{candidate_id}/narration_context.json",
        "full_transcript_paths": {
            "full_transcript_markdown": "transcript/full_transcript.md",
            "full_transcript_json": "transcript/full_transcript.json",
        },
        "render_status": "rendered" if rendered else "unrendered",
        "render_skip_reason": "" if rendered else "rich_evidence_limit",
        "frames": [{"status": "completed"}] if rendered else [],
        "audio_snippet": {"status": "completed" if rendered else "not_rendered"},
        "likely_target_repo": "owner/sim-tools",
        "repo_confidence": "high",
        "narration_context": {
            "entries": [{"kind": "speech", "text": text}],
            "continuation_phrases": continuation or [],
            "new_ticket_phrases": [marker] if "new ticket" in marker else [],
            "closing_phrases": [],
        },
    }


class SessionReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidates = [
            _candidate(
                "ticket-001",
                5,
                "The relative delta overlay loses sector colors after the lap resets.",
            ),
            _candidate(
                "ticket-002",
                25,
                "The relative delta overlay again loses sector colors when a new lap begins.",
            ),
            _candidate(
                "ticket-003",
                45,
                "New ticket: the pit limiter audio chime is delayed in traffic.",
                marker="new ticket",
                rendered=False,
            ),
            _candidate(
                "ticket-004",
                90,
                "Back to that ticket: relative delta overlay sector colors vanish after reset.",
                continuation=["back to that ticket"],
            ),
        ]

    def test_complete_session_relates_distant_mentions_without_grouping_unrelated_ticket(self) -> None:
        session = build_session_review(candidates=self.candidates, review_needed=[], marker_audit={})

        related_pairs = {
            frozenset((item["mention_a"], item["mention_b"])): item
            for item in session["relationships"]
        }
        self.assertIn(
            related_pairs[frozenset(("ticket-001", "ticket-002"))]["classification"],
            {"strong possible relation", "explicit link"},
        )
        self.assertIn(
            related_pairs[frozenset(("ticket-002", "ticket-004"))]["classification"],
            {"strong possible relation", "explicit link"},
        )
        self.assertNotIn(
            related_pairs[frozenset(("ticket-003", "ticket-004"))]["classification"],
            {"strong possible relation", "explicit link"},
        )
        grouped = {mention for thread in session["proposed_threads"] for mention in thread["mention_ids"]}
        self.assertIn("ticket-001", grouped)
        self.assertIn("ticket-002", grouped)
        self.assertIn("ticket-004", grouped)
        self.assertNotIn("ticket-003", grouped)
        self.assertEqual(session["unassigned_mentions"][0]["mention_id"], "ticket-003")

    def test_session_artifacts_contain_required_agent_instructions_and_schemas(self) -> None:
        session = build_session_review(candidates=self.candidates, review_needed=[], marker_audit={})
        outcomes = [
            {
                "outcome_id": "outcome-001",
                "record_label": "PROVISIONAL EVIDENCE CLUSTER",
                "source_mentions": [
                    {
                        "candidate_id": "ticket-001",
                        "timestamp": "00:05:00.000",
                        "role": "primary",
                    }
                ],
                "primary_choice_reason": "Deterministic actionable source order.",
                "unresolved_questions": [],
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            status = write_session_review_artifacts(root, session, outcomes=outcomes)

            required = (
                "START_HERE_FOR_TICKET_AGENT.md",
                "AGENT_REVIEW_MANIFEST.json",
                "SESSION_TIMELINE.md",
                "SESSION_TIMELINE.json",
                "TICKET_THREAD_HINTS.md",
                "TICKET_THREAD_HINTS.json",
                "UNASSIGNED_MENTIONS.md",
                "UNASSIGNED_MENTIONS.json",
                "PACKAGE_STATUS.json",
                "operator-drafts/session.codex.md",
                "operator-drafts/session.claude.md",
            )
            self.assertTrue(all((root / relative).exists() for relative in required))
            start = (root / "START_HERE_FOR_TICKET_AGENT.md").read_text(encoding="utf-8")
            timeline = json.loads((root / "SESSION_TIMELINE.json").read_text(encoding="utf-8"))
            hints = json.loads((root / "TICKET_THREAD_HINTS.json").read_text(encoding="utf-8"))
            handoff = json.loads(
                (root / "operator-drafts" / "session.handoff.json").read_text(encoding="utf-8")
            )

        self.assertIn("Do not create one ticket per marker automatically", start)
        self.assertIn("Check existing GitHub issues", start)
        self.assertIn("PROVISIONAL EVIDENCE CLUSTERS", start)
        self.assertIn("CONSOLIDATED_OUTCOMES.json", start)
        self.assertEqual(timeline["schema_version"], 1)
        self.assertEqual(len(timeline["records"]), 4)
        self.assertTrue(hints["relationships"])
        self.assertEqual(status["status"], "ready")
        self.assertEqual(status["semantic_authority"], "evidence_preparation_only")
        self.assertEqual(handoff["provisional_evidence_cluster_count"], 1)

    def test_all_timeline_record_types_share_required_agent_fields(self) -> None:
        marker_audit = {
            "markers": [
                {
                    "source_id": "two-hour-session",
                    "source_filename": "iracing-session.mkv",
                    "timestamp_seconds": 1800,
                    "timestamp": "00:30:00.000",
                    "marker_phrase": "this needs to be a ticket",
                    "surrounding_transcript_snippet": "Relative overlay marker only.",
                    "status": "indexed",
                }
            ]
        }
        review_needed = [
            {
                "review_id": "review-001",
                "source_filename": "iracing-session.mkv",
                "timestamp_start_seconds": 4200,
                "timestamp_start": "01:10:00.000",
                "reason": "visual follow-up",
                "transcript_excerpt": "The selected row may be clipped.",
            }
        ]
        session = build_session_review(
            candidates=self.candidates,
            review_needed=review_needed,
            marker_audit=marker_audit,
        )
        required = {
            "mention_id",
            "source_filename",
            "timestamp",
            "marker_phrase",
            "confidence",
            "excerpt",
            "narration_context_path",
            "full_transcript_paths",
            "render_status",
            "frame_available",
            "audio_available",
            "repo_hint",
            "distinctive_topic_terms",
            "continuation_phrases",
            "split_phrases",
            "closing_phrases",
            "possible_related_mention_ids",
            "warnings",
        }
        self.assertEqual(
            {record["record_type"] for record in session["timeline"]},
            {"ticket_mention", "review_needed", "explicit_marker"},
        )
        for record in session["timeline"]:
            self.assertTrue(required.issubset(record), record["record_type"])

    def test_portable_zip_keeps_text_first_and_indexes_omitted_media(self) -> None:
        session = build_session_review(candidates=self.candidates, review_needed=[], marker_audit={})
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_session_review_artifacts(root, session, portable_zip_max_mb=1)
            candidate_dir = root / "evidence_items" / "ticket-001"
            candidate_dir.mkdir(parents=True)
            (candidate_dir / "ticket.md").write_text("ticket summary", encoding="utf-8")
            (candidate_dir / "frame.jpg").write_bytes(b"x" * (2 * 1024 * 1024))

            result = build_portable_agent_zip(root, max_size_mb=1)
            omitted = json.loads((root / "OMITTED_MEDIA.json").read_text(encoding="utf-8"))
            status = json.loads((root / "PACKAGE_STATUS.json").read_text(encoding="utf-8"))
            with zipfile.ZipFile(result["zip_path"], "r") as archive:
                names = set(archive.namelist())
                zipped_status = json.loads(archive.read("PACKAGE_STATUS.json"))
            actual_zip_size = Path(result["zip_path"]).stat().st_size

        self.assertIn("START_HERE_FOR_TICKET_AGENT.md", names)
        self.assertIn("AGENT_REVIEW_MANIFEST.json", names)
        self.assertIn("SESSION_TIMELINE.json", names)
        self.assertIn("evidence_items/ticket-001/ticket.md", names)
        self.assertIn("OMITTED_MEDIA.json", names)
        self.assertNotIn("evidence_items/ticket-001/frame.jpg", names)
        self.assertEqual(omitted["omitted_media"][0]["candidate_or_mention_id"], "ticket-001")
        self.assertEqual(omitted["omitted_media"][0]["timestamp"], "00:05:00.000")
        self.assertEqual(result["omitted_media_count"], 1)
        self.assertEqual(status["portable_zip_size_bytes"], actual_zip_size)
        self.assertFalse(status["portable_zip_size_is_estimate"])
        self.assertTrue(zipped_status["portable_zip_size_is_estimate"])
        self.assertLess(abs(zipped_status["portable_zip_size_bytes"] - result["zip_size_bytes"]), 1024)
        self.assertEqual(result["privacy_status"], "passed")
        self.assertIn("PORTABLE_PRIVACY_REPORT.json", names)

    def test_engine_session_prompt_is_self_contained_and_issue_shaped(self) -> None:
        """issue 94: the engine writes its own hand-off prompt. It must carry the
        same contract as the app's copy, or a real run still emits an unusable
        prompt even though prompts.py was fixed."""
        session = build_session_review(candidates=self.candidates, review_needed=[], marker_audit={})
        projects = {
            "Aintologic/media-manglers": {
                "project_label": "Video Mangler Workbench",
                "keywords": ["the workbench", "the mangler"],
            },
            "Example/overlay-hub": {
                "project_label": "Overlay Hub",
                "keywords": ["the hub", "the overlay"],
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_session_review_artifacts(root, session, projects=projects)

            prompt = (root / "operator-drafts" / "session.codex.md").read_text(encoding="utf-8")

            # the agent must be able to find the evidence from the prompt alone
            self.assertIn(str(root.resolve()), prompt)
            self.assertNotIn("`../START_HERE_FOR_TICKET_AGENT.md`", prompt)
            self.assertNotIn("../AGENT_REVIEW_MANIFEST.json", prompt)

            # the marker scan is a hint, not the finding
            self.assertIn("hint, not the finding", prompt)
            self.assertIn("do not treat the candidate list as the list of issues", prompt.lower())

            # real repositories, not UNKNOWN
            self.assertIn("Aintologic/media-manglers", prompt)
            self.assertIn("Example/overlay-hub", prompt)
            self.assertIn("the overlay", prompt)

            # issues, with an approval gate
            self.assertIn("Produce **draft GitHub issues**", prompt)
            self.assertIn("until the operator approves the list", prompt)

            handoff = json.loads(
                (root / "operator-drafts" / "session.handoff.json").read_text(encoding="utf-8")
            )
            self.assertEqual(handoff["package_root"], str(root.resolve()))
            self.assertNotEqual(handoff["package_root"], "..")
            self.assertFalse(handoff["detection_is_authoritative"])
            self.assertTrue(handoff["agent_must_present_before_writing"])
            self.assertIn("Example/overlay-hub", handoff["projects"])

    def test_engine_session_prompt_says_so_when_no_repo_map_is_configured(self) -> None:
        """With no repo map the prompt must admit it rather than silently
        emitting a table the agent cannot use."""
        session = build_session_review(candidates=self.candidates, review_needed=[], marker_audit={})
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_session_review_artifacts(root, session)
            prompt = (root / "operator-drafts" / "session.codex.md").read_text(encoding="utf-8")
            self.assertIn("No operator repo map was available", prompt)
            self.assertIn("ask the operator", prompt.lower())
            # still self-contained
            self.assertIn(str(root.resolve()), prompt)

    def test_portable_zip_sanitizes_local_private_fields_and_excludes_logs(self) -> None:
        session = build_session_review(candidates=self.candidates, review_needed=[], marker_audit={})
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_session_review_artifacts(root, session)
            (root / "script_run.log").write_text(
                "Command: tool.exe --source C:\\Private\\recording.mkv --token secret-value",
                encoding="utf-8",
            )
            (root / "local-fields.json").write_text(
                json.dumps(
                    {
                        "source_path": r"C:\Private\recording.mkv",
                        "layout_fingerprint": "private-layout-value",
                        # Distinctive values: short decimals such as 0.1 collide with ISO-8601
                        # microsecond timestamps in generated files (97).
                        "voice_enrollment_vector": [0.7318264519, 0.9142857361],
                        "api_key": "private-key-value",
                        "operator": os.environ.get("USERNAME", "local-user"),
                    }
                ),
                encoding="utf-8",
            )

            result = build_portable_agent_zip(root, max_size_mb=2)
            privacy = json.loads(
                (root / "PORTABLE_PRIVACY_REPORT.json").read_text(encoding="utf-8")
            )
            with zipfile.ZipFile(result["zip_path"], "r") as archive:
                names = set(archive.namelist())
                combined = "\n".join(
                    archive.read(name).decode("utf-8", errors="ignore")
                    for name in names
                    if Path(name).suffix.lower() in {".json", ".md", ".txt", ".csv", ".srt"}
                )
                local_fields = [
                    json.loads(archive.read(name).decode("utf-8"))
                    for name in names
                    if Path(name).name == "local-fields.json"
                ]

        self.assertNotIn("script_run.log", names)
        for payload in local_fields:
            vector = payload.get("voice_enrollment_vector")
            self.assertFalse(
                isinstance(vector, list) and any(isinstance(item, float) for item in vector),
                "voice_enrollment_vector survived sanitization as raw numbers",
            )
        self.assertNotIn("7318264519", combined)
        self.assertNotIn("9142857361", combined)
        self.assertNotIn(r"C:\Private", combined)
        self.assertNotIn("private-layout-value", combined)
        self.assertNotIn("private-key-value", combined)
        self.assertEqual(privacy["status"], "passed")
        self.assertFalse(privacy["matched_values_recorded"])
        self.assertGreater(privacy["sanitized_value_count_by_category"]["local_path"], 0)
        self.assertGreater(
            privacy["sanitized_value_count_by_category"]["biometric_local_identifier"], 0
        )

    def test_portable_zip_fails_closed_on_forbidden_binary_residue(self) -> None:
        session = build_session_review(candidates=self.candidates, review_needed=[], marker_audit={})
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_session_review_artifacts(root, session)
            (root / "opaque.bin").write_bytes(b"binary-prefix C:\\Private\\source.mkv binary-suffix")

            with self.assertRaisesRegex(RuntimeError, "privacy preflight failed"):
                build_portable_agent_zip(root, max_size_mb=2)
            privacy = json.loads(
                (root / "PORTABLE_PRIVACY_REPORT.json").read_text(encoding="utf-8")
            )
            status = json.loads((root / "PACKAGE_STATUS.json").read_text(encoding="utf-8"))

        self.assertEqual(privacy["status"], "failed")
        self.assertGreater(privacy["residual_match_count_by_category"]["local_path"], 0)
        self.assertEqual(status["status"], "failed_privacy")
        self.assertFalse((root / "ticket-agent-handoff.zip").exists())

    def test_portable_zip_binary_probe_preserves_byte_boundaries(self) -> None:
        session = build_session_review(candidates=self.candidates, review_needed=[], marker_audit={})
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_session_review_artifacts(root, session)
            (root / "compressed.bin").write_bytes(
                b"binary-prefix \\\\synthetic" + bytes([0xFF]) + b"\\share binary-suffix"
            )

            result = build_portable_agent_zip(root, max_size_mb=2)
            privacy = json.loads(
                (root / "PORTABLE_PRIVACY_REPORT.json").read_text(encoding="utf-8")
            )

        self.assertEqual(result["privacy_status"], "passed")
        self.assertEqual(privacy["residual_match_count_by_category"]["local_path"], 0)

    @unittest.skipUnless(os.name == "nt", "Windows extended-length paths only")
    def test_portable_zip_reads_extended_length_media_paths(self) -> None:
        session = build_session_review(candidates=self.candidates, review_needed=[], marker_audit={})
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_session_review_artifacts(root, session)
            # 196: the frame's folder is 251 characters wherever the temp folder is (the suite's
            # own scratch folder is deeper than the system one); the file itself is longer than 260.
            padding = 90 - (len(str(root)) - 45)
            self.assertGreater(padding, 0)
            long_file = (
                root
                / "artifacts"
                / ("source-" + "a" * padding)
                / ("frames-" + "b" * 90)
                / ("frame-" + "c" * 40 + ".jpg")
            )
            io_file = local_io_path(long_file)
            io_file.parent.mkdir(parents=True)
            io_file.write_bytes(b"synthetic-media")

            result = build_portable_agent_zip(root, max_size_mb=2)
            with zipfile.ZipFile(result["zip_path"], "r") as archive:
                names = set(archive.namelist())
            local_io_path(long_file).unlink()
            for directory in (
                long_file.parent,
                long_file.parent.parent,
                long_file.parent.parent.parent,
            ):
                local_io_path(directory).rmdir()

        self.assertEqual(len(str(long_file.parent)), 251)
        self.assertGreater(len(str(long_file)), 260)
        self.assertIn(long_file.relative_to(root).as_posix(), names)

    @unittest.skipUnless(os.name == "nt", "Windows extended-length paths only")
    def test_portable_zip_keeps_files_in_a_folder_whose_own_path_is_too_long(self) -> None:
        # 197: a folder past the 260-character limit was never listed, so everything in it was
        # left out of the ZIP with no error. Holds whether or not Windows long paths are enabled.
        session = build_session_review(candidates=self.candidates, review_needed=[], marker_audit={})
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_session_review_artifacts(root, session)
            deep = root / "artifacts" / ("a" * 120) / ("b" * 120) / ("c" * 60)
            files = [deep / "frame-1.jpg", deep / "notes.md"]
            local_io_path(deep).mkdir(parents=True)
            for path in files:
                local_io_path(path).write_bytes(b"synthetic")
            result = build_portable_agent_zip(root, max_size_mb=2)
            with zipfile.ZipFile(result["zip_path"], "r") as archive:
                names = set(archive.namelist())
            for path in files:
                local_io_path(path).unlink()
            for directory in (deep, deep.parent, deep.parent.parent):
                local_io_path(directory).rmdir()

        self.assertGreater(len(str(deep)), 260)
        for path in files:
            self.assertIn(path.relative_to(root).as_posix(), names)

    def test_eight_generic_unknown_mentions_do_not_form_a_thread(self) -> None:
        candidates = []
        for index in range(8):
            candidate = _candidate(
                f"ticket-{index + 1:03d}",
                index + 1,
                "Dashboard ticket bug issue should be fixed.",
            )
            candidate["likely_target_repo"] = "UNKNOWN"
            candidate["repo_confidence"] = "unknown"
            candidates.append(candidate)

        session = build_session_review(candidates=candidates, review_needed=[], marker_audit={})

        self.assertEqual(session["proposed_threads"], [])
        self.assertEqual(len(session["unassigned_mentions"]), 8)
        self.assertTrue(
            all(
                relation["relationship_score"] == 0
                and not relation["confirmed_repo_match"]
                for relation in session["relationships"]
            )
        )

    def test_actionable_review_group_uses_marker_time_and_is_unassigned(self) -> None:
        review = {
            "review_id": "review-001",
            "source_id": "synthetic",
            "source_filename": "synthetic-session.mkv",
            "timestamp_start_seconds": 30,
            "timestamp_start": "00:00:30.000",
            "marker_timestamp_seconds": 90,
            "marker_timestamp": "00:01:30.000",
            "timestamp_end_seconds": 150,
            "timestamp_end": "00:02:30.000",
            "confidence": "review-needed",
            "reason": "uncandidated_actionable_request",
            "promotion_status": "unassigned_ticket_mention",
            "transcript_excerpt": "Add a synthetic incident bar to the dashboard.",
            "grouped_occurrence_count": 3,
        }
        session = build_session_review(candidates=[], review_needed=[review], marker_audit={})

        record = session["timeline"][0]
        self.assertEqual(record["timestamp_seconds"], 90)
        self.assertEqual(record["timestamp"], "00:01:30.000")
        self.assertEqual(record["grouped_occurrence_count"], 3)
        self.assertEqual(session["unassigned_mentions"][0]["mention_id"], "review-001")


if __name__ == "__main__":
    unittest.main()
