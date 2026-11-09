from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


def _load_benchmark_report_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "tools" / "benchmarks" / "benchmark_report.py"
    spec = importlib.util.spec_from_file_location("benchmark_report", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


benchmark_report = _load_benchmark_report_module()


class BenchmarkReportTests(unittest.TestCase):
    def test_build_named_entity_checks_flags_brooklands_to_brooklyn(self) -> None:
        source_entry = {
            "source_id": "de-brooklands",
            "expected_named_entities": [
                {
                    "term": "Brooklands",
                    "category": "track",
                    "expected_in_source": True,
                    "expected_in_translation": True,
                    "bad_forms": ["Brooklyn"],
                }
            ],
        }

        result = benchmark_report.build_named_entity_checks(
            source_entry,
            source_text="Brooklands war eine der ersten Rennstrecken.",
            translation_text="Brooklyn was one of the earliest racetracks.",
        )

        self.assertTrue(result["brooklands_to_brooklyn_flag"])
        self.assertFalse(result["brooklands_source_variant_flag"])
        self.assertEqual(result["named_entity_issue_count"], 1)
        self.assertEqual(result["named_entity_source_substitution_count"], 0)
        self.assertEqual(result["named_entity_translation_substitution_count"], 1)
        self.assertEqual(result["named_entity_source_missing_count"], 0)
        self.assertEqual(result["named_entity_translation_missing_count"], 0)
        self.assertEqual(result["checks"][0]["bad_form_matches"], ["Brooklyn"])
        self.assertEqual(result["checks"][0]["translation_bad_form_matches"], ["Brooklyn"])
        self.assertEqual(result["checks"][0]["source_bad_form_matches"], [])
        self.assertEqual(result["checks"][0]["translation_issue"], "substituted variant in English translation")

    def test_build_named_entity_checks_flags_brooklands_source_variant(self) -> None:
        source_entry = {
            "source_id": "de-brooklands",
            "expected_named_entities": [
                {
                    "term": "Brooklands",
                    "category": "track",
                    "expected_in_source": True,
                    "expected_in_translation": True,
                    "bad_forms": ["Brooklyn", "Brooklyns"],
                }
            ],
        }

        result = benchmark_report.build_named_entity_checks(
            source_entry,
            source_text="Die erste Rennstrecke der Welt entstand in Brooklyns.",
            translation_text="Brooklands was the first racetrack in the world.",
        )

        self.assertTrue(result["brooklands_source_variant_flag"])
        self.assertFalse(result["brooklands_to_brooklyn_flag"])
        self.assertEqual(result["named_entity_issue_count"], 1)
        self.assertEqual(result["named_entity_source_substitution_count"], 1)
        self.assertEqual(result["named_entity_translation_substitution_count"], 0)
        self.assertEqual(result["named_entity_source_missing_count"], 0)
        self.assertEqual(result["named_entity_translation_missing_count"], 0)
        self.assertEqual(result["checks"][0]["source_bad_form_matches"], ["Brooklyns"])
        self.assertEqual(result["checks"][0]["source_issue"], "substituted variant in source transcript")
        self.assertEqual(result["checks"][0]["translation_issue"], "")

    def test_build_named_entity_checks_does_not_fake_translation_missing_without_artifact(self) -> None:
        source_entry = {
            "source_id": "de-brooklands",
            "expected_named_entities": [
                {
                    "term": "Brooklands",
                    "category": "track",
                    "expected_in_source": True,
                    "expected_in_translation": True,
                    "bad_forms": ["Brooklyn", "Brooklyns"],
                }
            ],
        }

        result = benchmark_report.build_named_entity_checks(
            source_entry,
            source_text="Die erste Rennstrecke der Welt entstand in Brooklyns.",
            translation_text="",
        )

        self.assertEqual(result["named_entity_source_substitution_count"], 1)
        self.assertEqual(result["named_entity_translation_substitution_count"], 0)
        self.assertEqual(result["named_entity_source_missing_count"], 0)
        self.assertEqual(result["named_entity_translation_missing_count"], 0)
        self.assertEqual(result["checks"][0]["translation_issue"], "")

    def test_build_named_entity_checks_keeps_close_forms_non_blocking_when_literal_term_exists(self) -> None:
        source_entry = {
            "source_id": "en-simhub",
            "expected_named_entities": [
                {
                    "term": "SimHub",
                    "category": "product",
                    "expected_in_source": True,
                    "expected_in_translation": True,
                    "bad_forms": ["Simub", "sim up", "cimeb"],
                }
            ],
        }

        result = benchmark_report.build_named_entity_checks(
            source_entry,
            source_text="SimHub is open now, but later the transcript drifts to Simub.",
            translation_text="Open SimHub first, even if another segment says sim up.",
        )

        self.assertEqual(result["named_entity_issue_count"], 0)
        self.assertEqual(result["named_entity_source_substitution_count"], 1)
        self.assertEqual(result["named_entity_translation_substitution_count"], 1)
        self.assertEqual(result["named_entity_source_missing_count"], 0)
        self.assertEqual(result["named_entity_translation_missing_count"], 0)
        self.assertEqual(result["checks"][0]["source_bad_form_matches"], ["Simub"])
        self.assertEqual(result["checks"][0]["translation_bad_form_matches"], ["sim up"])
        self.assertEqual(result["checks"][0]["source_issue"], "")
        self.assertEqual(result["checks"][0]["translation_issue"], "")

    def test_collect_results_marks_english_copy_as_translation_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_root = root / "run"
            output_root = run_root / "local-medium-gpu" / "en-control" / "output"
            output_root.mkdir(parents=True)

            suite_manifest_path = root / "suite.json"
            lane_manifest_path = root / "lanes.json"
            source_txt = output_root / "transcript.txt"
            source_txt.write_text("This is already English.", encoding="utf-8")
            summary_csv = output_root / "PROCESSING_SUMMARY.csv"
            lane_meta_path = run_root / "local-medium-gpu" / "en-control" / "lane-meta.json"

            suite_manifest_path.write_text(
                json.dumps(
                    {
                        "suite_id": "canonical-short",
                        "suite_label": "Canonical Short Suite",
                        "sources": [
                            {
                                "source_id": "en-control",
                                "title": "English control",
                                "url": "https://www.youtube.com/watch?v=1aA1WGON49E",
                                "video_id": "1aA1WGON49E",
                                "expected_language": "en",
                                "embedded_english_subtitles": "native_english",
                                "expected_named_entities": [],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            lane_manifest_path.write_text(
                json.dumps(
                    {
                        "lane_manifest_id": "benchmark-lanes-v1",
                        "lanes": [
                            {
                                "lane_id": "local-medium-gpu",
                                "label": "Local medium GPU",
                                "app_surface": "Audio",
                                "processing_mode": "Local",
                                "translate_to": "en",
                                "whisper_model": "medium",
                                "whisper_device": "GPU",
                                "openai_project": "",
                                "openai_model": "",
                                "supported": True,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with summary_csv.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "app_surface",
                        "app_version",
                        "output_path",
                        "source_duration_seconds",
                        "transcript_original_txt",
                        "detected_language",
                        "processing_mode",
                        "openai_project",
                        "transcription_provider",
                        "transcription_model",
                        "translation_provider_name",
                        "translation_model",
                        "translation_validation_status",
                        "package_status",
                        "translation_status",
                        "translation_notes",
                        "openai_translation_summary",
                        "whisper_mode",
                        "whisper_requested_device",
                        "whisper_selected_device",
                        "whisper_device_switch_count",
                        "estimated_openai_text_cost_usd",
                        "validation_warning_count",
                        "contamination_count",
                        "encoding_artifact_count",
                        "compression_warning_count",
                        "failed_translated_segment_count",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "app_surface": "Audio Mangler",
                        "app_version": "0.7.3",
                        "output_path": str(output_root),
                        "source_duration_seconds": "60",
                        "transcript_original_txt": str(source_txt),
                        "detected_language": "en",
                        "processing_mode": "Local",
                        "openai_project": "",
                        "transcription_provider": "Local Whisper",
                        "transcription_model": "medium",
                        "translation_provider_name": "",
                        "translation_model": "",
                        "translation_validation_status": "",
                        "package_status": "SUCCESS",
                        "translation_status": "not used for this file; source already English, original transcript copied",
                        "translation_notes": "",
                        "openai_translation_summary": "OpenAI Translation: not used for this file; source already English, original transcript copied",
                        "whisper_mode": "GPU_CUDA",
                        "whisper_requested_device": "GPU",
                        "whisper_selected_device": "cuda",
                        "whisper_device_switch_count": "0",
                        "estimated_openai_text_cost_usd": "0.000000",
                        "validation_warning_count": "0",
                        "contamination_count": "0",
                        "encoding_artifact_count": "0",
                        "compression_warning_count": "0",
                        "failed_translated_segment_count": "0",
                    }
                )

            lane_meta_path.write_text(
                json.dumps(
                    {
                        "benchmark_run_id": "canonical-short__en-control__local-medium-gpu",
                        "source_id": "en-control",
                        "lane_id": "local-medium-gpu",
                        "app_surface": "Audio",
                        "output_root": str(output_root),
                        "summary_csv_path": str(summary_csv),
                        "run_exit_code": 0,
                        "run_duration_seconds": 42.0,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            payload = benchmark_report.collect_results(
                run_root=run_root,
                suite_manifest_path=suite_manifest_path,
                lane_manifest_path=lane_manifest_path,
                include_deferred=False,
            )

        self.assertEqual(len(payload["results"]), 1)
        row = payload["results"][0]
        self.assertTrue(row["translation_requested"])
        self.assertFalse(row["translation_performed"])
        self.assertEqual(
            row["translation_skipped_reason"],
            "source already English; original transcript copied",
        )
        self.assertIn("requested_openai_transcription_model", row)
        self.assertEqual(row["requested_openai_transcription_model"], "")
        self.assertIn("protected_terms_profile", row)
        self.assertEqual(row["protected_terms_profile"], "")
        self.assertIn("named_entity_source_substitution_count", row)
        self.assertEqual(row["named_entity_source_substitution_count"], 0)
        self.assertIn("named_entity_translation_substitution_count", row)
        self.assertEqual(row["named_entity_translation_substitution_count"], 0)
        self.assertIn("named_entity_source_missing_count", row)
        self.assertEqual(row["named_entity_source_missing_count"], 0)
        self.assertIn("named_entity_translation_missing_count", row)
        self.assertEqual(row["named_entity_translation_missing_count"], 0)
        self.assertIn("brooklands_source_variant_flag", row)
        self.assertFalse(row["brooklands_source_variant_flag"])
        self.assertEqual(row["benchmark_status"], "accepted")


if __name__ == "__main__":
    unittest.main()
