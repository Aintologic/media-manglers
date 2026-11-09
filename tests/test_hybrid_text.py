from __future__ import annotations

import json
import tempfile
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.providers import hybrid_text


class FakeTransport:
    def __init__(
        self,
        *,
        model_ids: list[str] | None = None,
        responses: list[dict[str, object] | Exception] | None = None,
        list_models_error: Exception | None = None,
    ) -> None:
        self.model_ids = list(model_ids or [])
        self.responses = list(responses or [])
        self.list_models_error = list_models_error
        self.list_models_calls = 0
        self.translate_calls: list[dict[str, object]] = []

    def list_models(self) -> list[str]:
        self.list_models_calls += 1
        if self.list_models_error:
            raise self.list_models_error
        return list(self.model_ids)

    def translate_chat_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, object]],
    ) -> dict[str, object]:
        self.translate_calls.append({"model": model, "messages": messages})
        if not self.responses:
            raise AssertionError("No fake transport response was queued.")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class CapturingOpenAiTransport(hybrid_text.OpenAiChatCompletionsTransport):
    def __init__(self) -> None:
        super().__init__(api_key="test-key", api_base_url="https://example.invalid/v1")
        self.requests: list[dict[str, object]] = []

    def _json_request(
        self,
        *,
        method: str,
        endpoint: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self.requests.append(
            {
                "method": method,
                "endpoint": endpoint,
                "payload": payload,
            }
        )
        requested_model = str((payload or {}).get("model") or "").strip()
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"translations":{"1":"translated"}}',
                    }
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "model": requested_model,
        }


class HybridTextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.glossary_path = self.repo_root / "glossaries" / "de-en-sim-racing.json"
        self.source_segments = [
            {
                "id": 1,
                "start": 0.0,
                "end": 1.0,
                "text": "so heißt das in Crew Chief selber",
            },
            {
                "id": 2,
                "start": 1.0,
                "end": 2.0,
                "text": "DRS-Zonen",
            },
            {
                "id": 3,
                "start": 2.0,
                "end": 3.0,
                "text": "Enable iRacing Full Course Yellow at Pit State Messages",
            },
            {
                "id": 4,
                "start": 3.0,
                "end": 4.0,
                "text": "Use Sweary Messages",
            },
        ]
        self.brooklands_expected_entities = [
            {
                "term": "Brooklands",
                "category": "track",
                "expected_in_translation": True,
                "bad_forms": ["Brooklyn", "Brooklyns", "Brooklyn's"],
            }
        ]

    def _write_source_transcript(
        self,
        root: Path,
        *,
        segments: list[dict[str, object]] | None = None,
        extra_payload: dict[str, object] | None = None,
    ) -> Path:
        transcript_path = root / "transcript.json"
        payload = {
            "language": "de",
            "source_language": "de",
            "task": "transcribe",
            "segments": segments or self.source_segments,
        }
        if extra_payload:
            payload.update(extra_payload)
        transcript_path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        return transcript_path

    def test_load_glossary_reads_tracked_profile(self) -> None:
        glossary = hybrid_text.load_glossary(self.glossary_path)

        self.assertEqual(glossary["profile"], "de-en-sim-racing")
        self.assertTrue(any(term["source_term"] == "Crew Chief" for term in glossary["terms"]))

    def test_load_glossary_raises_hybrid_error_when_file_is_missing(self) -> None:
        missing_path = self.repo_root / "glossaries" / "missing-glossary.json"

        with self.assertRaisesRegex(hybrid_text.HybridTranslationError, "protected terms profile file not found"):
            hybrid_text.load_glossary(missing_path)

    def test_load_source_transcript_segments_preserves_order_and_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            transcript_path = self._write_source_transcript(Path(temp_dir))
            transcript = hybrid_text.load_source_transcript_segments(transcript_path)

        self.assertEqual(transcript["language"], "de")
        self.assertEqual([segment["id"] for segment in transcript["segments"]], [1, 2, 3, 4])
        self.assertEqual(transcript["segments"][2]["start"], 2.0)
        self.assertEqual(transcript["segments"][2]["end"], 3.0)

    def test_load_source_transcript_segments_preserves_expected_named_entities(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            transcript_path = self._write_source_transcript(
                Path(temp_dir),
                extra_payload={"expected_named_entities": self.brooklands_expected_entities},
            )
            transcript = hybrid_text.load_source_transcript_segments(transcript_path)

        self.assertEqual(transcript["expected_named_entities"][0]["term"], "Brooklands")
        self.assertEqual(transcript["expected_named_entities"][0]["bad_forms"], ["Brooklyn", "Brooklyns", "Brooklyn's"])

    def test_validate_hybrid_target_languages_defaults_to_en(self) -> None:
        self.assertEqual(hybrid_text.validate_hybrid_target_languages([]), ["en"])
        self.assertEqual(hybrid_text.validate_hybrid_target_languages("en"), ["en"])

    def test_validate_hybrid_target_languages_rejects_non_english_or_multiple(self) -> None:
        with self.assertRaisesRegex(hybrid_text.HybridTranslationError, "exactly one target language"):
            hybrid_text.validate_hybrid_target_languages("de")
        with self.assertRaisesRegex(hybrid_text.HybridTranslationError, "exactly one target language"):
            hybrid_text.validate_hybrid_target_languages(["en", "es"])

    def test_build_segment_batches_is_deterministic_with_context(self) -> None:
        batches = hybrid_text.build_segment_batches(
            self.source_segments,
            batch_size=2,
            context_segments=1,
        )

        self.assertEqual(len(batches), 2)
        self.assertEqual(batches[0]["segment_ids"], [1, 2])
        self.assertEqual(batches[1]["segment_ids"], [3, 4])
        self.assertEqual([item["id"] for item in batches[1]["context_before"]], [2])
        self.assertEqual([item["id"] for item in batches[0]["context_after"]], [3])

    def test_build_translation_request_payload_includes_glossary_and_context(self) -> None:
        glossary = hybrid_text.load_glossary(self.glossary_path)
        batch = hybrid_text.build_segment_batches(
            self.source_segments,
            batch_size=2,
            context_segments=1,
        )[0]

        payload = hybrid_text.build_translation_request_payload(
            batch,
            source_language="de",
            target_language="en",
            glossary=glossary,
            model="gpt-4.1-mini-2025-04-14",
        )

        self.assertEqual(payload["model"], "gpt-4.1-mini-2025-04-14")
        self.assertEqual(payload["expected_segment_ids"], [1, 2])
        user_content = payload["messages"][1]["content"]
        self.assertIn("Crew Chief", str(user_content))
        self.assertIn("Full Course Yellow", str(user_content))
        self.assertIn('"context_after"', str(user_content))

    def test_build_translation_request_payload_generic_mode_omits_profile_specific_examples(self) -> None:
        batch = hybrid_text.build_segment_batches(
            self.source_segments,
            batch_size=2,
            context_segments=1,
        )[0]

        payload = hybrid_text.build_translation_request_payload(
            batch,
            source_language="de",
            target_language="en",
            glossary={"profile": "", "lane_id": "", "terms": []},
            model="gpt-4.1-mini-2025-04-14",
        )

        system_content = str(payload["messages"][0]["content"])
        user_content = str(payload["messages"][1]["content"])
        self.assertNotIn("Crew Chief", system_content)
        self.assertNotIn("Full Course Yellow", system_content)
        self.assertIn('"protected_terms_profile": ""', user_content)

    def test_build_translation_request_payload_includes_expected_named_entities(self) -> None:
        batch = hybrid_text.build_segment_batches(
            self.source_segments,
            batch_size=2,
            context_segments=1,
        )[0]

        payload = hybrid_text.build_translation_request_payload(
            batch,
            source_language="de",
            target_language="en",
            glossary={"profile": "", "lane_id": "", "terms": []},
            model="gpt-4o-mini-2024-07-18",
            expected_named_entities=self.brooklands_expected_entities,
        )

        system_content = str(payload["messages"][0]["content"])
        user_content = str(payload["messages"][1]["content"])
        self.assertIn("Expected named entities may be supplied", system_content)
        self.assertIn('"term": "Brooklands"', user_content)
        self.assertIn('"bad_forms"', user_content)

    def test_parse_translation_response_accepts_keyed_json(self) -> None:
        parsed = hybrid_text.parse_translation_response(
            '```json\n{"translations":{"1":"that is what it is called in Crew Chief itself","2":"DRS zones"}}\n```',
        )

        self.assertEqual(parsed["translations"][1], "that is what it is called in Crew Chief itself")
        self.assertEqual(parsed["translations"][2], "DRS zones")

    def test_validate_translated_segments_flags_contamination_and_mojibake(self) -> None:
        report = hybrid_text.validate_translated_segments(
            source_segments=[self.source_segments[0]],
            translated_segments=[
                {
                    "id": 1,
                    "start": 0.0,
                    "end": 1.0,
                    "text": "Please provide the German transcript segment â€¦",
                }
            ],
        )

        self.assertEqual(report["contamination_count"], 1)
        self.assertEqual(report["mojibake_count"], 1)
        self.assertFalse(report["valid"])

    def test_validate_translated_segments_flags_compression_and_garbage(self) -> None:
        report = hybrid_text.validate_translated_segments(
            source_segments=[self.source_segments[2]],
            translated_segments=[
                {
                    "id": 3,
                    "start": 2.0,
                    "end": 3.0,
                    "text": "aaaaaa",
                }
            ],
        )

        self.assertEqual(report["compression_warning_count"], 1)
        self.assertEqual(report["garbage_pattern_count"], 1)
        self.assertFalse(report["valid"])

    def test_validate_translated_segments_allows_legitimate_repeated_source_phrase(self) -> None:
        report = hybrid_text.validate_translated_segments(
            source_segments=[
                {
                    "id": 10,
                    "start": 0.0,
                    "end": 1.0,
                    "text": "Rennstart geht, eben Green Green Green oder",
                }
            ],
            translated_segments=[
                {
                    "id": 10,
                    "start": 0.0,
                    "end": 1.0,
                    "text": "Race start goes, just Green Green Green or",
                }
            ],
        )

        self.assertEqual(report["garbage_pattern_count"], 0)
        self.assertTrue(report["valid"])

    def test_validate_translated_segments_flags_glossary_violations(self) -> None:
        glossary = hybrid_text.load_glossary(self.glossary_path)
        report = hybrid_text.validate_translated_segments(
            source_segments=[self.source_segments[0]],
            translated_segments=[
                {
                    "id": 1,
                    "start": 0.0,
                    "end": 1.0,
                    "text": "I am the Crew Chief myself.",
                }
            ],
            glossary=glossary,
        )

        self.assertGreater(report["glossary_violation_count"], 0)
        self.assertFalse(report["valid"])

    def test_validate_translated_segments_flags_named_entity_bad_form(self) -> None:
        report = hybrid_text.validate_translated_segments(
            source_segments=[
                {
                    "id": 1,
                    "start": 0.0,
                    "end": 1.0,
                    "text": "Die erste Rennstrecke der Welt wurde 1907 eroffnet.",
                }
            ],
            translated_segments=[
                {
                    "id": 1,
                    "start": 0.0,
                    "end": 1.0,
                    "text": "Brooklyn opened in 1907 as the world's first racetrack.",
                }
            ],
            expected_named_entities=self.brooklands_expected_entities,
        )

        self.assertEqual(report["named_entity_violation_count"], 1)
        self.assertEqual(report["named_entity_violations"][0]["bad_form_matches"], ["Brooklyn"])
        self.assertFalse(report["valid"])

    def test_validate_translated_segments_requires_expected_named_entity_in_final_validation(self) -> None:
        report = hybrid_text.validate_translated_segments(
            source_segments=[
                {
                    "id": 1,
                    "start": 0.0,
                    "end": 1.0,
                    "text": "Die erste Rennstrecke der Welt wurde 1907 eroffnet.",
                }
            ],
            translated_segments=[
                {
                    "id": 1,
                    "start": 0.0,
                    "end": 1.0,
                    "text": "The world's first racetrack opened in 1907.",
                }
            ],
            expected_named_entities=self.brooklands_expected_entities,
            enforce_expected_entity_presence=True,
        )

        self.assertEqual(report["named_entity_violation_count"], 1)
        self.assertIn("missing from English translation", report["named_entity_violations"][0]["issue"])
        self.assertFalse(report["valid"])

    def test_write_translation_artifacts_writes_json_srt_and_text(self) -> None:
        glossary = hybrid_text.load_glossary(self.glossary_path)
        model_resolution = hybrid_text.ModelResolution(
            requested_model="gpt-4.1-mini-2025-04-14",
            used_model="gpt-4.1-mini-2025-04-14",
            approved_models=["gpt-4.1-mini-2025-04-14"],
            accessible_models=["gpt-4.1-mini-2025-04-14"],
            selection_source="default",
            discovery_status="success",
        )
        translated_segments = [
            {
                "id": 1,
                "start": 0.0,
                "end": 1.0,
                "text": "that is what it is called in Crew Chief itself",
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            artifact_paths = hybrid_text.write_translation_artifacts(
                translated_segments,
                output_dir=temp_dir,
                source_language="de",
                target_language="en",
                glossary=glossary,
                validation_status="accepted",
                model_resolution=model_resolution,
            )

            transcript_json = Path(artifact_paths["transcript_json_path"])
            transcript_srt = Path(artifact_paths["transcript_srt_path"])
            transcript_txt = Path(artifact_paths["transcript_txt_path"])

            self.assertTrue(transcript_json.exists())
            self.assertTrue(transcript_srt.exists())
            self.assertTrue(transcript_txt.exists())
            self.assertIn("Crew Chief", transcript_txt.read_text(encoding="utf-8"))

    def test_validate_from_request_writes_validation_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            transcript_path = self._write_source_transcript(temp_root)
            report_path = temp_root / "translations" / "en" / "validation_report.json"

            result = hybrid_text.validate_from_request(
                {
                    "transcript_json_path": str(transcript_path),
                    "translated_segments": [
                        {
                            "id": 1,
                            "start": 0.0,
                            "end": 1.0,
                            "text": "that is what it is called in Crew Chief itself",
                        }
                    ],
                    "glossary_path": str(self.glossary_path),
                    "target_languages": ["en"],
                    "output_report_path": str(report_path),
                }
            )

            self.assertEqual(result["output_report_path"], str(report_path))
            self.assertTrue(report_path.exists())

    def test_resolve_model_selection_uses_visible_default(self) -> None:
        transport = FakeTransport(model_ids=["gpt-4.1-mini-2025-04-14", "gpt-4o-mini-2024-07-18"])

        resolution = hybrid_text.resolve_model_selection(
            project="Private",
            requested_model="",
            transport=transport,
        )

        self.assertEqual(resolution.requested_model, "gpt-4o-mini-2024-07-18")
        self.assertEqual(resolution.used_model, "gpt-4o-mini-2024-07-18")
        self.assertEqual(resolution.selection_source, "default")

    def test_resolve_model_selection_falls_back_to_other_visible_model(self) -> None:
        transport = FakeTransport(model_ids=["gpt-4.1-mini-2025-04-14"])

        resolution = hybrid_text.resolve_model_selection(
            project="Public",
            requested_model="",
            transport=transport,
        )

        self.assertEqual(resolution.requested_model, "gpt-4o-mini-2024-07-18")
        self.assertEqual(resolution.used_model, "gpt-4.1-mini-2025-04-14")
        self.assertEqual(resolution.selection_source, "fallback-accessible")

    def test_resolve_model_selection_rejects_unavailable_explicit_model(self) -> None:
        transport = FakeTransport(model_ids=["gpt-4o-mini-2024-07-18"])

        with self.assertRaisesRegex(hybrid_text.HybridTranslationError, "Model unavailable"):
            hybrid_text.resolve_model_selection(
                project="Public",
                requested_model="gpt-4.1-mini-2025-04-14",
                transport=transport,
            )

    def test_translate_chat_completion_omits_response_format_and_temperature_for_gpt_5_mini(self) -> None:
        transport = CapturingOpenAiTransport()

        transport.translate_chat_completion(
            model="gpt-5-mini",
            messages=[{"role": "user", "content": "hi"}],
        )

        payload = transport.requests[-1]["payload"]
        self.assertIsInstance(payload, dict)
        self.assertNotIn("response_format", payload)
        self.assertNotIn("temperature", payload)

    def test_translate_chat_completion_omits_response_format_and_temperature_for_versioned_gpt_5_mini(self) -> None:
        transport = CapturingOpenAiTransport()

        transport.translate_chat_completion(
            model="gpt-5-mini-2025-08-07",
            messages=[{"role": "user", "content": "hi"}],
        )

        payload = transport.requests[-1]["payload"]
        self.assertIsInstance(payload, dict)
        self.assertNotIn("response_format", payload)
        self.assertNotIn("temperature", payload)

    def test_translate_chat_completion_keeps_response_format_for_gpt_4o_mini(self) -> None:
        transport = CapturingOpenAiTransport()

        transport.translate_chat_completion(
            model="gpt-4o-mini-2024-07-18",
            messages=[{"role": "user", "content": "hi"}],
        )

        payload = transport.requests[-1]["payload"]
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["temperature"], 0)

    def test_translate_chat_completion_keeps_response_format_for_gpt_4_1_mini(self) -> None:
        transport = CapturingOpenAiTransport()

        transport.translate_chat_completion(
            model="gpt-4.1-mini-2025-04-14",
            messages=[{"role": "user", "content": "hi"}],
        )

        payload = transport.requests[-1]["payload"]
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["temperature"], 0)

    def test_get_api_key_for_project_uses_exact_project_variable(self) -> None:
        env = {
            "OPENAI_API_KEY_PRIVATE": "private-key",
            "OPENAI_API_KEY_PUBLIC": "public-key",
        }

        self.assertEqual(hybrid_text.get_api_key_for_project("Private", env=env), "private-key")
        self.assertEqual(hybrid_text.get_api_key_for_project("Public", env=env), "public-key")

    def test_get_api_key_for_project_reports_missing_without_secret(self) -> None:
        with self.assertRaisesRegex(
            hybrid_text.HybridTranslationError,
            "OPENAI_API_KEY_PRIVATE",
        ):
            hybrid_text.get_api_key_for_project("Private", env={})

    def test_run_hybrid_translation_retries_once_and_accepts_repaired_output(self) -> None:
        first_response = {
            "content": json.dumps(
                {
                    "translations": {
                        "1": "translation:",
                        "2": "DRS zones",
                    }
                },
                ensure_ascii=False,
            ),
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "model": "gpt-4.1-mini-2025-04-14",
        }
        second_response = {
            "content": json.dumps(
                {
                    "translations": {
                        "1": "that is what it is called in Crew Chief itself",
                        "2": "DRS zones",
                        "3": "Enable iRacing Full Course Yellow at Pit State Messages",
                        "4": "Use Sweary Messages",
                    }
                },
                ensure_ascii=False,
            ),
            "usage": {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18},
            "model": "gpt-4.1-mini-2025-04-14",
        }
        transport = FakeTransport(
            model_ids=["gpt-4.1-mini-2025-04-14"],
            responses=[first_response, second_response],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            transcript_path = self._write_source_transcript(temp_root)

            result = hybrid_text.run_hybrid_translation(
                transcript_json_path=transcript_path,
                output_dir=temp_root / "translations" / "en",
                glossary_path=self.glossary_path,
                source_language="de",
                target_language="en",
                openai_project="Private",
                requested_model="gpt-4.1-mini-2025-04-14",
                batch_size=4,
                context_segments=1,
                transport=transport,
            )

            self.assertEqual(result["validation_status"], "accepted")
            self.assertTrue(result["retry_used"])
            self.assertEqual(len(transport.translate_calls), 2)
            self.assertTrue(Path(result["validation_report_path"]).exists())
            transcript_txt = Path(result["transcript_artifacts"]["transcript_txt_path"])
            self.assertIn("Crew Chief", transcript_txt.read_text(encoding="utf-8"))

    def test_run_hybrid_translation_allows_generic_mode_without_profile(self) -> None:
        response = {
            "content": json.dumps(
                {
                    "translations": {
                        "1": "that is what it is called there itself",
                        "2": "DRS zones",
                        "3": "Enable iRacing Full Course Yellow at Pit State Messages",
                        "4": "Use Sweary Messages",
                    }
                },
                ensure_ascii=False,
            ),
            "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19},
            "model": "gpt-4.1-mini-2025-04-14",
        }
        transport = FakeTransport(
            model_ids=["gpt-4.1-mini-2025-04-14"],
            responses=[response],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            transcript_path = self._write_source_transcript(temp_root)

            result = hybrid_text.run_hybrid_translation(
                transcript_json_path=transcript_path,
                output_dir=temp_root / "translations" / "en",
                source_language="de",
                target_language="en",
                openai_project="Private",
                requested_model="gpt-4.1-mini-2025-04-14",
                batch_size=8,
                context_segments=1,
                transport=transport,
            )

            self.assertEqual(result["validation_status"], "accepted")
            self.assertEqual(result["glossary_profile"], "")
            self.assertEqual(result["protected_terms_profile"], "")
            self.assertEqual(result["glossary_path"], "")
            self.assertEqual(result["protected_terms_path"], "")
            self.assertEqual(result["protected_terms_violation_count"], 0)

    def test_run_hybrid_translation_retries_named_entity_bad_form_and_accepts_repair(self) -> None:
        source_segments = [
            {
                "id": 1,
                "start": 0.0,
                "end": 2.0,
                "text": "Die erste Rennstrecke der Welt wurde 1907 eroffnet.",
            }
        ]
        first_response = {
            "content": json.dumps(
                {
                    "translations": {
                        "1": "Brooklyn opened in 1907 as the world's first racetrack.",
                    }
                },
                ensure_ascii=False,
            ),
            "usage": {"prompt_tokens": 9, "completion_tokens": 5, "total_tokens": 14},
            "model": "gpt-4o-mini-2024-07-18",
        }
        second_response = {
            "content": json.dumps(
                {
                    "translations": {
                        "1": "Brooklands opened in 1907 as the world's first racetrack.",
                    }
                },
                ensure_ascii=False,
            ),
            "usage": {"prompt_tokens": 11, "completion_tokens": 6, "total_tokens": 17},
            "model": "gpt-4o-mini-2024-07-18",
        }
        transport = FakeTransport(
            model_ids=["gpt-4o-mini-2024-07-18"],
            responses=[first_response, second_response],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            transcript_path = self._write_source_transcript(temp_root, segments=source_segments)

            result = hybrid_text.run_hybrid_translation(
                transcript_json_path=transcript_path,
                output_dir=temp_root / "translations" / "en",
                source_language="de",
                target_language="en",
                openai_project="Public",
                requested_model="gpt-4o-mini-2024-07-18",
                expected_named_entities=self.brooklands_expected_entities,
                batch_size=1,
                context_segments=1,
                transport=transport,
            )

            self.assertEqual(result["validation_status"], "accepted")
            self.assertTrue(result["retry_used"])
            self.assertEqual(result["named_entity_violation_count"], 0)
            self.assertEqual(len(transport.translate_calls), 2)
            retry_payload = str(transport.translate_calls[1]["messages"][1]["content"])
            self.assertIn("Brooklands", retry_payload)
            self.assertIn("Brooklyn", retry_payload)
            transcript_txt = Path(result["transcript_artifacts"]["transcript_txt_path"])
            self.assertIn("Brooklands", transcript_txt.read_text(encoding="utf-8"))

    def test_run_hybrid_translation_recovers_failed_batch_with_single_segment_recovery(self) -> None:
        bad_response = {
            "content": json.dumps(
                {
                    "translations": {
                        "1": "that is what it is called in Crew Chief itself",
                        "2": "DRS zones",
                        "3": "Enable iRacing Full Course Yellow at Pit State Messages",
                        "4": "",
                    }
                },
                ensure_ascii=False,
            ),
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "model": "gpt-4.1-mini-2025-04-14",
        }
        single_segment_responses = [
            {
                "content": json.dumps({"translations": {"1": "that is what it is called in Crew Chief itself"}}, ensure_ascii=False),
                "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
                "model": "gpt-4.1-mini-2025-04-14",
            },
            {
                "content": json.dumps({"translations": {"2": "DRS zones"}}, ensure_ascii=False),
                "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
                "model": "gpt-4.1-mini-2025-04-14",
            },
            {
                "content": json.dumps(
                    {"translations": {"3": "Enable iRacing Full Course Yellow at Pit State Messages"}},
                    ensure_ascii=False,
                ),
                "usage": {"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
                "model": "gpt-4.1-mini-2025-04-14",
            },
            {
                "content": json.dumps({"translations": {"4": "Use Sweary Messages"}}, ensure_ascii=False),
                "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
                "model": "gpt-4.1-mini-2025-04-14",
            },
        ]
        transport = FakeTransport(
            model_ids=["gpt-4.1-mini-2025-04-14"],
            responses=[bad_response, bad_response, *single_segment_responses],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            transcript_path = self._write_source_transcript(temp_root)

            result = hybrid_text.run_hybrid_translation(
                transcript_json_path=transcript_path,
                output_dir=temp_root / "translations" / "en",
                glossary_path=self.glossary_path,
                source_language="de",
                target_language="en",
                openai_project="Private",
                requested_model="gpt-4.1-mini-2025-04-14",
                batch_size=4,
                context_segments=1,
                transport=transport,
            )

            self.assertEqual(result["validation_status"], "accepted")
            self.assertTrue(result["split_recovery_used"])
            self.assertEqual(result["failed_segment_count"], 0)
            self.assertEqual(len(transport.translate_calls), 6)
            self.assertTrue(result["per_batch_results"][0]["split_recovery_used"])
            self.assertEqual(result["per_batch_results"][0]["status"], "accepted")

    def test_run_hybrid_translation_marks_partial_when_batch_keeps_failing(self) -> None:
        bad_response = {
            "content": json.dumps(
                {
                    "translations": {
                        "1": "I am the Crew Chief myself.",
                        "2": "DRS",
                    }
                },
                ensure_ascii=False,
            ),
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "model": "gpt-4.1-mini-2025-04-14",
        }
        good_second_segment = {
            "content": json.dumps({"translations": {"2": "DRS zones"}}, ensure_ascii=False),
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "model": "gpt-4.1-mini-2025-04-14",
        }
        good_third_segment = {
            "content": json.dumps(
                {"translations": {"3": "Enable iRacing Full Course Yellow at Pit State Messages"}},
                ensure_ascii=False,
            ),
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "model": "gpt-4.1-mini-2025-04-14",
        }
        good_fourth_segment = {
            "content": json.dumps({"translations": {"4": "Use Sweary Messages"}}, ensure_ascii=False),
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "model": "gpt-4.1-mini-2025-04-14",
        }
        transport = FakeTransport(
            model_ids=["gpt-4.1-mini-2025-04-14"],
            responses=[bad_response, bad_response, good_second_segment, good_third_segment, good_fourth_segment],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            transcript_path = self._write_source_transcript(temp_root)

            result = hybrid_text.run_hybrid_translation(
                transcript_json_path=transcript_path,
                output_dir=temp_root / "translations" / "en",
                glossary_path=self.glossary_path,
                source_language="de",
                target_language="en",
                openai_project="Private",
                requested_model="gpt-4.1-mini-2025-04-14",
                batch_size=1,
                context_segments=1,
                transport=transport,
            )

            self.assertEqual(result["validation_status"], "partial")
            self.assertEqual(result["failed_segment_count"], 1)
            self.assertEqual(result["per_batch_results"][0]["status"], "failed")
            self.assertEqual(result["per_batch_results"][1]["status"], "accepted")
            transcript_txt = Path(result["transcript_artifacts"]["transcript_txt_path"])
            transcript_text = transcript_txt.read_text(encoding="utf-8")
            self.assertIn("Use Sweary Messages", transcript_text)
            self.assertNotIn("Crew Chief", transcript_text)
            self.assertGreater(result["warning_count"], 0)

    def test_translate_from_request_uses_payload_and_writes_outputs(self) -> None:
        response = {
            "content": json.dumps(
                {
                    "translations": {
                        "1": "that is what it is called in Crew Chief itself",
                        "2": "DRS zones",
                        "3": "Enable iRacing Full Course Yellow at Pit State Messages",
                        "4": "Use Sweary Messages",
                    }
                },
                ensure_ascii=False,
            ),
            "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19},
            "model": "gpt-4.1-mini-2025-04-14",
        }
        transport = FakeTransport(
            model_ids=["gpt-4.1-mini-2025-04-14"],
            responses=[response],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            transcript_path = self._write_source_transcript(temp_root)
            result = hybrid_text.run_hybrid_translation(
                transcript_json_path=transcript_path,
                output_dir=temp_root / "translations" / "en",
                glossary_path=self.glossary_path,
                source_language="de",
                target_language="en",
                openai_project="Private",
                requested_model="gpt-4.1-mini-2025-04-14",
                batch_size=8,
                context_segments=1,
                transport=transport,
            )

            self.assertEqual(result["translation_model"], "gpt-4.1-mini-2025-04-14")
            self.assertEqual(result["openai_project"], "Private")
            self.assertTrue(Path(result["validation_report_path"]).exists())
            self.assertTrue(Path(result["transcript_artifacts"]["transcript_json_path"]).exists())
            self.assertEqual(result["usage"]["total_tokens"], 19)
            self.assertAlmostEqual(result["estimated_cost_usd"], 0.000016, places=10)


if __name__ == "__main__":
    unittest.main()
