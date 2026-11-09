# Benchmark Results Schema

## Purpose

This document defines the tracked benchmark aggregation outputs written by the benchmark runner/reporting tools.

The benchmark program writes:
- `benchmark-summary.csv`
- `benchmark-results.json`
- `benchmark-summary.md`

These outputs summarize benchmark runs. They do not replace the raw package artifacts.

## Row model

Each benchmark result row represents one source/lane/app run.

## Core identifiers

- `benchmark_run_id`: stable per-row id, usually `<suite_id>__<source_id>__<lane_id>`
- `suite_id`
- `suite_label`
- `source_id`
- `source_label`
- `source_url`
- `video_id`
- `topic_class`
- `app_surface`
- `app_version`
- `lane_id`
- `lane_label`

## Source expectations

- `expected_language`
- `detected_language`
- `target_language`
- `source_duration_seconds`
- `embedded_english_subtitles`

## Requested lane configuration

- `requested_processing_mode`
- `requested_translate_to`
- `requested_whisper_model`
- `requested_whisper_device`
- `requested_openai_project`
- `requested_openai_model`
- `requested_openai_transcription_model`
- `requested_protected_terms_profile`

## Actual run metadata

- `processing_mode`
- `openai_project`
- `transcription_provider`
- `transcription_model`
- `translation_provider_name`
- `translation_model`
- `protected_terms_profile`
- `validation_status`
- `package_status`
- `run_exit_code`
- `run_duration_seconds`
- `real_time_factor`
- `whisper_mode`
- `whisper_requested_device`
- `whisper_selected_device`
- `whisper_device_switch_count`
- `estimated_openai_text_cost_usd`

## Artifact references

- `output_root`
- `package_output_path`
- `summary_csv_path`
- `validation_report_path`
- `source_transcript_txt`
- `source_transcript_json`
- `translated_transcript_txt`
- `translated_transcript_json`
- `lane_meta_path`

## Quality / scoring signals

- `translation_requested`
- `translation_performed`
- `translation_skipped_reason`
- `validation_warning_count`
- `contamination_count`
- `mojibake_count`
- `encoding_artifact_count`
- `compression_warning_count`
- `garbage_pattern_count`
- `failed_translated_segment_count`
- `named_entity_required_count`
- `named_entity_source_present_count`
- `named_entity_translation_present_count`
- `named_entity_source_substitution_count`
- `named_entity_translation_substitution_count`
- `named_entity_source_missing_count`
- `named_entity_translation_missing_count`
- `named_entity_issue_count`
- `brooklands_source_variant_flag`
- `brooklands_to_brooklyn_flag`
- `benchmark_accuracy_penalty`
- `benchmark_speed_penalty`
- `benchmark_cost_penalty`
- `benchmark_score`
- `benchmark_status`

## Named-entity detail payload

`benchmark-results.json` stores a richer per-row `named_entity_checks` payload. Each entry includes:
- `term`
- `category`
- `source_present`
- `translation_present`
- `source_bad_form_matches`
- `translation_bad_form_matches`
- `source_issue`
- `translation_issue`
- `bad_form_matches`
- `issue`

CSV keeps only the rolled-up counts and key boolean flags.

## Benchmark status semantics

- `accepted`: no benchmark-critical corruption detected
- `warning`: package succeeded, but benchmark scoring found quality risks
- `rejected`: run failed or benchmark-critical corruption was detected
- `deferred`: the lane/source was intentionally not run in the current pilot

## Source-vs-translation interpretation

- Source-transcript substitution and omission are tracked separately from
  translation-side corruption.
- `brooklands_source_variant_flag` means the raw/source transcript used a
  Brooklands-like bad form such as `Brooklyns`; it does not mean the already
  fixed Hybrid `Brooklands -> Brooklyn` translation defect came back.
- `brooklands_to_brooklyn_flag` remains reserved for the English
  translation-side corruption.

## Compatibility note

`PROCESSING_SUMMARY.csv` remains the app/package summary surface.
Benchmark outputs are additive and must not break existing validator expectations.
