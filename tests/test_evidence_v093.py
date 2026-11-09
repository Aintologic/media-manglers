from __future__ import annotations

from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers.core.evidence_package import (  # noqa: E402
    WINDOWS_LEGACY_ARTIFACT_PATH_BUDGET,
    _apply_outcome_render_policy,
    _apply_artifact_results,
    _artifact_integrity_report,
    _bounded_transcript_physical_source_id,
    _canonicalize_source_artifacts,
    _copy_transcript_sources,
    write_outputs_from_request,
)


def _candidate(evidence_id: str) -> dict[str, object]:
    base = f"evidence_items/{evidence_id}"
    return {
        "evidence_id": evidence_id,
        "source_id": "source-a",
        "source_path": "synthetic-source.mkv",
        "audio_input_path": "synthetic-source.wav",
        "frames": [
            {
                "timestamp_seconds": 12.5,
                "relative_path": f"{base}/frames/full/source-a_00-00-12.500.jpg",
                "path": f"{base}/frames/full/source-a_00-00-12.500.jpg",
                "full_frame_relative_path": f"{base}/frames/full/source-a_00-00-12.500.jpg",
                "full_frame_path": f"{base}/frames/full/source-a_00-00-12.500.jpg",
                "panels": [],
                "status": "pending",
            }
        ],
        "audio_snippet": {
            "relative_path": f"{base}/audio_snippet.mp3",
            "path": f"{base}/audio_snippet.mp3",
            "status": "pending",
            "start_seconds": 10.0,
            "duration_seconds": 20.0,
            "audio_stream_index": 0,
            "input_path": "synthetic-source.wav",
        },
        "supporting_audio_snippets": [],
    }


class EvidenceV093Tests(unittest.TestCase):
    def test_long_output_root_bounds_transcript_physical_ids_without_identity_loss(self) -> None:
        source_id = (
            "session-bravo-profile-compatible-5760x1080-with-a-deliberately-"
            "long-synthetic-fi-c055a14e62"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_root = root / "input"
            input_root.mkdir()
            transcript_json = input_root / "source.json"
            transcript_srt = input_root / "source.srt"
            transcript_txt = input_root / "source.txt"
            transcript_json.write_text(
                '{"language":"en","segments":[]}\n', encoding="utf-8"
            )
            transcript_srt.write_text("", encoding="utf-8")
            transcript_txt.write_text("", encoding="utf-8")
            # 196: the output root is 165 characters wherever the temp folder
            # is (the suite's own scratch folder is deeper than the system one).
            unpadded = len(
                str(
                    root
                    / "long-output-root-"
                    / "codex-correction-review"
                    / "codex-evidence-package"
                )
            )
            output = (
                root
                / ("long-output-root-" + ("x" * (165 - unpadded)))
                / "codex-correction-review"
                / "codex-evidence-package"
            )
            self.assertEqual(len(str(output)), 165)
            sources = [
                {
                    "source_id": source_id,
                    "source_filename": "session-bravo.mkv",
                    "transcript_language": "en",
                    "transcript_json_path": str(transcript_json),
                    "transcript_srt_path": str(transcript_srt),
                    "transcript_txt_path": str(transcript_txt),
                    "raw_segments": [],
                    "segments": [],
                }
            ]

            physical_source_id, shortened = _bounded_transcript_physical_source_id(
                output, source_id
            )
            _copy_transcript_sources(output, sources)

            self.assertTrue(shortened)
            self.assertEqual(sources[0]["source_id"], source_id)
            self.assertEqual(sources[0]["physical_source_id"], physical_source_id)
            self.assertTrue(sources[0]["physical_source_id_shortened"])
            self.assertRegex(physical_source_id, r"-[0-9a-f]{12}$")
            for key in (
                "raw_transcript_json_path",
                "raw_transcript_srt_path",
                "raw_transcript_txt_path",
                "transcript_json_path",
                "transcript_srt_path",
                "transcript_txt_path",
            ):
                physical_path = Path(sources[0][key])
                self.assertLessEqual(
                    len(str(physical_path)), WINDOWS_LEGACY_ARTIFACT_PATH_BUDGET
                )
                self.assertTrue(physical_path.is_file())

    def test_long_output_root_uses_bounded_physical_artifact_paths(self) -> None:
        source_id = (
            "session-bravo-profile-compatible-5760x1080-with-a-deliberately-"
            "long-synthetic-fi-ad2f7c412b"
        )
        candidate = _candidate("ticket-001")
        candidate["source_id"] = source_id
        candidate["frames"][0]["panels"] = [
            {
                "role": "driver_view",
                "label": "Driver View",
                "status": "pending",
            }
        ]
        output = Path(
            r"C:\output\evidence\sample-run\retest\codex-evidence-package"
        )

        frame_tasks, audio_tasks = _canonicalize_source_artifacts(
            [candidate], output
        )

        frame = frame_tasks[0]
        panel = frame["panels"][0]
        audio = audio_tasks[0]
        for artifact in (frame, panel, audio):
            self.assertTrue(artifact["physical_path_shortened"])
            self.assertLessEqual(
                len(artifact["path"]),
                WINDOWS_LEGACY_ARTIFACT_PATH_BUDGET,
            )
            self.assertIn(source_id, artifact["logical_relative_path"])
            self.assertIn(source_id, artifact["artifact_id"])
        self.assertIn("12-500", frame["relative_path"])
        self.assertIn("10-000-20000ms-a0", audio["relative_path"])
        self.assertNotIn(source_id, frame["relative_path"])
        self.assertEqual(
            candidate["frames"][0]["logical_relative_path"],
            frame["logical_relative_path"],
        )
        self.assertEqual(
            candidate["audio_snippet"]["logical_relative_path"],
            audio["logical_relative_path"],
        )

    def test_source_timestamp_union_deduplicates_frames_and_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidates = [_candidate("ticket-001"), _candidate("ticket-002")]
            frame_tasks, audio_tasks = _canonicalize_source_artifacts(candidates, Path(temporary))
        self.assertEqual(len(frame_tasks), 1)
        self.assertEqual(len(audio_tasks), 1)
        self.assertEqual(
            candidates[0]["frames"][0]["canonical_source_relative_path"],
            candidates[1]["frames"][0]["canonical_source_relative_path"],
        )
        self.assertEqual(
            candidates[0]["frames"][0]["relative_path"],
            candidates[1]["frames"][0]["relative_path"],
        )
        self.assertEqual(
            candidates[0]["frames"][0]["artifact_id"],
            candidates[1]["frames"][0]["artifact_id"],
        )
        self.assertEqual(
            candidates[0]["audio_snippet"]["relative_path"],
            candidates[1]["audio_snippet"]["relative_path"],
        )

    def test_fractional_same_second_artifacts_do_not_collide(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = _candidate("ticket-001")
            second = _candidate("ticket-002")
            first["frames"][0]["timestamp_seconds"] = 12.125
            second["frames"][0]["timestamp_seconds"] = 12.875
            first["audio_snippet"]["start_seconds"] = 10.125
            second["audio_snippet"]["start_seconds"] = 10.875
            frame_tasks, audio_tasks = _canonicalize_source_artifacts(
                [first, second], Path(temporary)
            )

        self.assertEqual(len(frame_tasks), 2)
        self.assertEqual(len(audio_tasks), 2)
        self.assertEqual(len({item["relative_path"] for item in frame_tasks}), 2)
        self.assertEqual(len({item["artifact_id"] for item in frame_tasks}), 2)
        self.assertEqual(len({item["relative_path"] for item in audio_tasks}), 2)

    def test_cross_source_artifact_identity_stays_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = _candidate("ticket-001")
            second = _candidate("ticket-002")
            second["source_id"] = "source-b"
            frame_tasks, audio_tasks = _canonicalize_source_artifacts(
                [first, second], Path(temporary)
            )

        self.assertEqual(len(frame_tasks), 2)
        self.assertEqual(len(audio_tasks), 2)
        self.assertEqual(len({item["artifact_id"] for item in frame_tasks}), 2)
        self.assertEqual(len({item["relative_path"] for item in frame_tasks}), 2)

    def test_v092_candidate_local_result_alias_updates_canonical_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = _candidate("ticket-001")
            _canonicalize_source_artifacts([candidate], Path(temporary))
            frame = candidate["frames"][0]
            _apply_artifact_results(
                [candidate],
                {
                    "frames": [
                        {
                            "relative_path": frame["legacy_v092_relative_path"],
                            "status": "created",
                            "full_frame_width": 1920,
                        }
                    ],
                    "audio": [],
                },
            )

        self.assertEqual(frame["status"], "created")
        self.assertEqual(frame["full_frame_width"], 1920)
        self.assertEqual(frame["relative_path"], frame["canonical_source_relative_path"])

    def test_only_provisional_primary_candidates_receive_rich_artifacts(self) -> None:
        primary = _candidate("ticket-001")
        supporting = _candidate("ticket-002")
        correction = _candidate("ticket-003")
        for candidate, classification in (
            (primary, "actionable"),
            (supporting, "supporting_validation"),
            (correction, "correction"),
        ):
            candidate["render_status"] = "rendered"
            candidate["outcome_classification"] = classification
            candidate["outcome_ids"] = ["outcome-001"]
        outcomes = [
            {
                "outcome_id": "outcome-001",
                "primary_candidate_id": "ticket-001",
                "render_eligible": True,
            }
        ]

        rendered, text_only = _apply_outcome_render_policy(
            [primary, supporting, correction], outcomes, [], [], stop_after="Package"
        )

        self.assertEqual([item["evidence_id"] for item in rendered], ["ticket-001"])
        self.assertEqual({item["evidence_id"] for item in text_only}, {"ticket-002", "ticket-003"})
        self.assertTrue(all(not item["frames"] for item in text_only))
        self.assertTrue(
            all(item["audio_snippet"]["status"] == "not_rendered" for item in text_only)
        )

    def test_integrity_report_reconciles_plan_results_and_written_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidates = [_candidate("ticket-001")]
            frame_tasks, audio_tasks = _canonicalize_source_artifacts(candidates, root)
            for task in [*frame_tasks, *audio_tasks]:
                path = Path(task["path"])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic")
                task["status"] = "completed"
            candidates[0]["frames"][0]["status"] = "completed"
            candidates[0]["audio_snippet"]["status"] = "completed"
            report = _artifact_integrity_report(
                root,
                candidates,
                {"frames": frame_tasks, "audio": audio_tasks},
                enforce=True,
            )

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["totals"]["deduplicated_count"], 2)
        self.assertEqual(report["totals"]["written_count"], 2)
        self.assertTrue(report["all_required_paths_exist"])
        self.assertTrue(report["counters_reconciled"])

    def test_integrity_report_fails_when_primary_artifact_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidates = [_candidate("ticket-001")]
            frame_tasks, audio_tasks = _canonicalize_source_artifacts(candidates, root)
            candidates[0]["frames"][0]["status"] = "created"
            candidates[0]["audio_snippet"]["status"] = "created"
            report = _artifact_integrity_report(
                root,
                candidates,
                {
                    "frames": [{**frame_tasks[0], "status": "created"}],
                    "audio": [{**audio_tasks[0], "status": "created"}],
                },
                enforce=True,
            )

        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["all_required_paths_exist"])
        self.assertEqual(len(report["missing_required_artifacts"]), 2)

    def test_gate_b_synthetic_package_is_primary_only_reconciled_and_private(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "package"
            transcript = root / "source.transcript.json"
            transcript.write_text(
                json.dumps({"language": "en", "segments": []}), encoding="utf-8"
            )
            transcript_txt = root / "source.transcript.txt"
            transcript_srt = root / "source.transcript.srt"
            transcript_txt.write_text("Synthetic operator narration.", encoding="utf-8")
            transcript_srt.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nSynthetic operator narration.\n",
                encoding="utf-8",
            )
            rendered: list[dict[str, object]] = []
            frame_results: list[dict[str, object]] = []
            audio_results: list[dict[str, object]] = []
            outcomes: list[dict[str, object]] = []
            shared_frame_relative = "artifacts/sources/source-a/frames/full/source-a_00-00-10-125.jpg"
            for index in range(7):
                evidence_id = f"ticket-{index + 1:03d}"
                outcome_id = f"outcome-{index + 1:03d}"
                milliseconds = 10_125 if index in {0, 2} else 10_875 + (index * 1_000)
                frame_relative = (
                    shared_frame_relative
                    if index in {0, 2}
                    else f"artifacts/sources/source-a/frames/full/source-a_00-00-{milliseconds // 1000:02d}-{milliseconds % 1000:03d}.jpg"
                )
                audio_relative = (
                    f"artifacts/sources/source-a/audio/source-a_00-00-{20 + index:02d}-125_20000ms_a0.mp3"
                )
                frame_path = output / frame_relative
                audio_path = output / audio_relative
                for artifact_path in (frame_path, audio_path):
                    artifact_path.parent.mkdir(parents=True, exist_ok=True)
                    artifact_path.write_bytes(b"synthetic artifact")
                frame = {
                    "artifact_id": f"frame:source-a:{milliseconds}ms",
                    "timestamp_seconds": milliseconds / 1000,
                    "timestamp": f"00:00:{milliseconds / 1000:06.3f}",
                    "relative_path": frame_relative,
                    "canonical_source_relative_path": frame_relative,
                    "path": str(frame_path),
                    "full_frame_relative_path": frame_relative,
                    "full_frame_path": str(frame_path),
                    "panel_crop_mode": "off",
                    "panel_detection": "disabled",
                    "panels": [],
                    "status": "pending",
                }
                audio = {
                    "artifact_id": f"audio:source-a:{20 + index}125ms:20000ms:a0",
                    "relative_path": audio_relative,
                    "canonical_source_relative_path": audio_relative,
                    "path": str(audio_path),
                    "start_seconds": 20.125 + index,
                    "duration_seconds": 20.0,
                    "audio_stream_index": 0,
                    "status": "pending",
                }
                rendered.append(
                    {
                        "evidence_id": evidence_id,
                        "source_id": "source-a",
                        "source_filename": "synthetic-source.mkv",
                        "source_path": r"C:\Synthetic\synthetic-source.mkv",
                        "marker_timestamp_seconds": milliseconds / 1000,
                        "marker_timestamp": f"00:00:{milliseconds / 1000:06.3f}",
                        "timestamp_start_seconds": 0,
                        "timestamp_end_seconds": 60,
                        "timestamp_start": "00:00:00.000",
                        "timestamp_end": "00:01:00.000",
                        "confidence": "explicit",
                        "suggested_issue_title": f"Synthetic provisional cluster {index + 1}",
                        "transcript_excerpt": f"Synthetic request {index + 1}",
                        "detected_marker_phrases": ["make this a ticket"],
                        "render_status": "rendered",
                        "outcome_classification": "actionable",
                        "outcome_ids": [outcome_id],
                        "frames": [frame],
                        "audio_snippet": audio,
                        "supporting_audio_snippets": [],
                        "narration_context": {"entries": []},
                    }
                )
                outcomes.append(
                    {
                        "outcome_id": outcome_id,
                        "record_label": "PROVISIONAL EVIDENCE CLUSTER",
                        "semantic_authority": "evidence_preparation_only",
                        "final_ticket_decision": False,
                        "intent_summary": f"Synthetic provisional cluster {index + 1}",
                        "classification": "actionable",
                        "confidence": "explicit",
                        "confidence_reasons": ["synthetic deterministic fixture"],
                        "source_mentions": [
                            {
                                "candidate_id": evidence_id,
                                "source_id": "source-a",
                                "timestamp_seconds": milliseconds / 1000,
                                "role": "primary",
                            }
                        ],
                        "primary_candidate_id": evidence_id,
                        "primary_choice_reason": "Synthetic deterministic primary.",
                        "supporting_candidate_ids": [],
                        "linked_evidence_candidate_ids": [evidence_id],
                        "corrections": [],
                        "render_eligible": True,
                        "render_skip_reason": "",
                        "unresolved_questions": [],
                        "repository_suggestion": {"review_required": True},
                        "operator_confirmation_state": "unconfirmed",
                    }
                )
                if frame_relative not in {item["relative_path"] for item in frame_results}:
                    frame_results.append({**frame, "status": "created"})
                audio_results.append({**audio, "status": "created"})

            text_only = []
            for evidence_id, classification in (
                ("ticket-008", "supporting_validation"),
                ("ticket-009", "correction"),
            ):
                text_only.append(
                    {
                        **rendered[0],
                        "evidence_id": evidence_id,
                        "render_status": "unrendered",
                        "render_skip_reason": "supporting_or_non_primary_text_only",
                        "outcome_classification": classification,
                        "frames": [],
                        "audio_snippet": {"status": "not_rendered"},
                    }
                )

            result = write_outputs_from_request(
                {
                    "output_dir": str(output),
                    "sources": [
                        {
                            "source_id": "source-a",
                            "source_identifier": "synthetic-source.mkv",
                            "source_filename": "synthetic-source.mkv",
                            "source_path": r"C:\Synthetic\synthetic-source.mkv",
                            "status": "completed",
                            "duration_seconds": 120,
                            "transcript_json_path": str(transcript),
                            "transcript_srt_path": str(transcript_srt),
                            "transcript_txt_path": str(transcript_txt),
                            "transcript_audio_role": "operator_narration",
                        }
                    ],
                    "candidates": rendered,
                    "unrendered_candidates": text_only,
                    "review_needed": [],
                    "outcomes": outcomes,
                    "configuration": {
                        "require_artifact_integrity": True,
                        "evidence_handoff_mode": "Both",
                        "evidence_portable_zip_max_mb": 10,
                    },
                    "artifact_results": {
                        "frames": frame_results,
                        "audio": audio_results,
                        "integrity_enforced": True,
                    },
                }
            )
            integrity = json.loads(
                (output / "EVIDENCE_INTEGRITY_REPORT.json").read_text(encoding="utf-8")
            )
            with zipfile.ZipFile(result["portable_zip_path"], "r") as archive:
                zip_names = archive.namelist()
                zip_text = "\n".join(
                    archive.read(name).decode("utf-8", errors="ignore")
                    for name in zip_names
                    if Path(name).suffix.lower() in {".json", ".md", ".txt", ".csv", ".srt"}
                )

        self.assertEqual(result["candidate_count"], 7)
        self.assertEqual(integrity["status"], "passed")
        self.assertEqual(integrity["categories"]["frames"]["planned_reference_count"], 7)
        self.assertEqual(integrity["categories"]["frames"]["deduplicated_count"], 6)
        self.assertEqual(integrity["categories"]["audio"]["written_count"], 7)
        self.assertTrue(integrity["all_required_paths_exist"])
        self.assertNotIn("script_run.log", zip_names)
        self.assertNotRegex(zip_text, r"(?i)[a-z]:\\")
        self.assertNotIn(os.environ.get("USERNAME", "local-user"), zip_text)

    def test_backend_batches_at_most_200_timestamps_and_uses_filter_scripts(self) -> None:
        script = (REPO_ROOT / "Video Mangler.ps1").read_text(encoding="utf-8-sig")
        # 214: screenshots are made by the one frame renderer, which keeps these rules.
        renderer = (REPO_ROOT / "src" / "media_manglers" / "core" / "frame_render.py").read_text(encoding="utf-8")
        # ffmpeg rejects a select expression with more than 100 terms (105).
        self.assertIn("MAX_FRAMES_PER_BATCH = 90", renderer)
        self.assertIn("len(current) >= max_frames", renderer)
        self.assertIn("MAX_BATCH_SPAN_SECONDS = 240.0", renderer)
        self.assertIn('"-filter_complex_script"', renderer)
        self.assertIn("fps=fps={video['frame_rate_text']},select='{terms}'", renderer)
        self.assertIn('"-ss", seconds_text(seek), "-t", seconds_text(span), "-i"', renderer)
        self.assertIn('-Command "frames-render"', script)
        self.assertIn("Convert-TranscriptSourceWavToFlac", script)
        self.assertIn('.audio.flac', script)
        self.assertIn("Codex evidence source audio batch", script)
        self.assertIn("MM_PROGRESS_V1", script)
        self.assertIn("provider_stage", script)
        self.assertIn("-ProviderMessage", script)
        self.assertIn("-TerminalState succeeded", script)
        self.assertIn("heartbeat_interval_seconds = [math]::Max(10, $HeartbeatSeconds)", script)


if __name__ == "__main__":
    unittest.main()
