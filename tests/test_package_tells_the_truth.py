"""What the package says about each recording, through the real writer.

Every test here builds its sources the way ``Video Mangler.ps1`` writes its
manifest entries and runs them through ``build_package_from_request``
(detection, then the package writer), because 118 shipped green while its
test handed ``_build_transcript_quality`` a key the pipeline never delivered.
"""

from __future__ import annotations

from pathlib import Path
import json
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers.core.evidence_package import build_package_from_request  # noqa: E402

SPARSE_WARNINGS = (
    "long video has very low transcript word count",
    "transcript is unexpectedly short for source duration",
)

AUTOMATIC_REASON = (
    "automatic voice detection: Track 2 carries isolated speech; the other tracks are quiet or busy."
)


def _streams(count: int) -> list[dict[str, object]]:
    return [
        {
            "ordinal": ordinal,
            "stream_index": ordinal + 1,
            "ffmpeg_map": f"0:a:{ordinal}",
            "codec_name": "aac",
            "channels": 2,
            "channel_layout": "stereo",
            "language": "",
            "title": "",
        }
        for ordinal in range(count)
    ]


def _write_whisper_output(folder: Path, physical_id: str, segments: list[dict[str, object]]) -> dict[str, str]:
    """The three files the backend's transcription step leaves in the package."""

    folder.mkdir(parents=True, exist_ok=True)
    paths = {
        "transcript_json_path": folder / f"{physical_id}.transcript.json",
        "transcript_srt_path": folder / f"{physical_id}.transcript.srt",
        "transcript_txt_path": folder / f"{physical_id}.transcript.txt",
    }
    paths["transcript_json_path"].write_text(
        json.dumps({"language": "en", "segments": segments}), encoding="utf-8"
    )
    paths["transcript_srt_path"].write_text(
        "".join(f"{i}\n00:00:00,000 --> 00:00:01,000\n{s['text']}\n\n" for i, s in enumerate(segments, 1)),
        encoding="utf-8",
    )
    paths["transcript_txt_path"].write_text(
        "".join(f"{s['text']}\n" for s in segments), encoding="utf-8"
    )
    return {key: str(value) for key, value in paths.items()}


def _backend_entry(output: Path, **overrides: object) -> dict[str, object]:
    """One source exactly as the backend's manifest entry carries it."""

    source_id = str(overrides.pop("source_id", "race-session"))
    segments = overrides.pop(
        "segments",
        [
            {
                "id": 1,
                "start": 1600.0,
                "end": 1620.0,
                "text": "Make this a ticket, the pit board shows the wrong lap after the restart.",
            }
        ],
    )
    entry: dict[str, object] = {
        "source_id": source_id,
        "physical_source_id": source_id,
        "physical_source_id_shortened": False,
        "source_identifier": f"{source_id}.mkv",
        "source_path": str(output.parent / f"{source_id}.mkv"),
        "source_filename": f"{source_id}.mkv",
        "audio_path": str(output / "audio" / f"{source_id}.audio.flac"),
        "audio_status": "completed",
        "audio_error_message": "",
        "audio_method": "extracted_audio",
        "audio_stream_count": 3,
        "audio_streams": _streams(3),
        "selected_audio_stream_index": 1,
        "selected_human_track_number": 2,
        "selected_audio_stream": _streams(3)[1],
        "audio_stream_selection_confirmed": True,
        "audio_stream_confirmation_source": "operator",
        "transcript_audio_role": "operator_narration",
        "transcription_input_path": str(output / "audio" / f"{source_id}.audio.flac"),
        "transcription_input_method": "extracted_audio",
        "transcript_reuse_status": "not_reused",
        "reused_transcript_json_path": "",
        "reused_transcript_srt_path": "",
        "reused_transcript_txt_path": "",
        "raw_video_transcription_used": False,
        "narration_speech_mode": "Sparse",
        "duration_seconds": "2400",
        "status": "completed",
        "error_message": "",
    }
    if segments is not None:
        entry.update(_write_whisper_output(output / "transcript" / "sources", source_id, list(segments)))
    entry.update(overrides)
    return entry


def _build(output: Path, sources: list[dict[str, object]], **extra: object) -> dict[str, object]:
    return build_package_from_request(
        {"output_dir": str(output), "sources": sources, "max_items": 20, **extra}
    )


def _manifest_source(output: Path, source_id: str = "race-session") -> dict[str, object]:
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    return next(item for item in manifest["sources"] if item["source_id"] == source_id)


class SparseNarrationReachesThePackageTests(unittest.TestCase):
    """118: the exemption must hold in a real package, not only in memory."""

    def test_sparse_recording_gets_no_word_count_warnings_in_the_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "package"
            _build(output, [_backend_entry(output)])
            quality = _manifest_source(output)["transcript_quality"]
            for warning in SPARSE_WARNINGS:
                self.assertNotIn(warning, quality["warning_reasons"])
            self.assertEqual(quality["quality_status"], "usable", quality["warning_reasons"])
            report = (output / "EVIDENCE_QUALITY_REPORT.md").read_text(encoding="utf-8")
            for warning in SPARSE_WARNINGS:
                self.assertNotIn(warning, report)

    def test_continuous_recording_still_gets_both_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "package"
            _build(output, [_backend_entry(output, narration_speech_mode="Continuous")])
            quality = _manifest_source(output)["transcript_quality"]
            for warning in SPARSE_WARNINGS:
                self.assertIn(warning, quality["warning_reasons"])

    def test_the_manifest_records_the_speech_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "package"
            _build(output, [_backend_entry(output)])
            self.assertEqual(_manifest_source(output)["narration_speech_mode"], "Sparse")


class UnchosenTrackTests(unittest.TestCase):
    """A recording waiting for the operator's track choice names no track."""

    def _waiting(self, output: Path) -> dict[str, object]:
        # What the backend writes after "Multiple audio tracks:" is thrown:
        # status failed, no stream extracted, the index still the usual track.
        return _backend_entry(
            output,
            segments=None,
            status="failed",
            error_message=(
                "Multiple audio tracks: the app could not tell which track is your microphone "
                "in 'race-session.mkv'. Speech was heard on Track 1 and Track 2."
            ),
            audio_status="pending",
            selected_audio_stream=None,
            audio_stream_selection_confirmed=False,
            audio_stream_confirmation_source="unconfirmed",
            transcript_json_path=str(output / "transcript" / "sources" / "race-session.transcript.json"),
            transcript_srt_path=str(output / "transcript" / "sources" / "race-session.transcript.srt"),
            transcript_txt_path=str(output / "transcript" / "sources" / "race-session.transcript.txt"),
        )

    def test_no_stream_is_called_the_operator_narration(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "package"
            _build(output, [self._waiting(output)])
            source = _manifest_source(output)
            roles = [stream.get("role") for stream in source["audio_streams"]]
            self.assertNotIn("operator_narration", roles, roles)
            self.assertEqual(source["selected_audio_stream"], {})
            self.assertEqual(source["audio_stream_selection_status"], "not_chosen")

    def test_the_quality_report_does_not_name_a_selected_stream(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "package"
            _build(output, [self._waiting(output)])
            report = (output / "EVIDENCE_QUALITY_REPORT.md").read_text(encoding="utf-8")
            self.assertIn("- Selected audio stream: not recorded", report)
            self.assertNotIn('"ffmpeg_map": "0:a:0"', report)

    def test_a_chosen_track_is_still_the_operator_narration(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "package"
            _build(output, [_backend_entry(output)])
            source = _manifest_source(output)
            roles = {stream["ordinal"]: stream.get("role") for stream in source["audio_streams"]}
            self.assertEqual(roles, {0: "supporting_audio", 1: "operator_narration", 2: "supporting_audio"})
            self.assertEqual(source["selected_audio_stream"]["ffmpeg_map"], "0:a:1")


class WhoChoseTheTrackTests(unittest.TestCase):
    """An automatic pick is not the operator's choice."""

    def test_an_automatic_pick_is_recorded_as_automatic_with_its_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "package"
            _build(output, [_backend_entry(output, audio_stream_confirmation_source=AUTOMATIC_REASON)])
            source = _manifest_source(output)
            self.assertEqual(source["audio_stream_selection_status"], "automatic")
            self.assertEqual(source["audio_stream_confirmation_source"], AUTOMATIC_REASON)
            report = (output / "EVIDENCE_QUALITY_REPORT.md").read_text(encoding="utf-8")
            self.assertIn("- Audio stream selection: automatic", report)
            self.assertIn(AUTOMATIC_REASON, report)

    def test_the_operators_choice_is_recorded_as_operator_selected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "package"
            _build(output, [_backend_entry(output, audio_stream_confirmation_source="operator")])
            self.assertEqual(_manifest_source(output)["audio_stream_selection_status"], "operator_selected")


class RawTranscriptSurvivesAContinueTests(unittest.TestCase):
    """transcript/raw keeps what Whisper heard when a package is written again."""

    ALIAS = "Mayfeld Park"
    CANONICAL = "Mayfield Park"

    def test_raw_copy_keeps_the_original_wording_after_a_second_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "package"
            entry = _backend_entry(
                output,
                segments=[
                    {
                        "id": 1,
                        "start": 1600.0,
                        "end": 1620.0,
                        "text": f"Make this a ticket, the pit board is wrong at {self.ALIAS}.",
                        "avg_logprob": -0.21,
                        "no_speech_prob": 0.03,
                    }
                ],
            )
            glossary = {"transcription_glossary_entries": [f"{self.CANONICAL}={self.ALIAS}"]}
            raw_folder = output / "transcript" / "raw" / "sources"
            corrected_txt = output / "transcript" / "sources" / "race-session.transcript.txt"

            _build(output, [dict(entry)], **glossary)
            self.assertIn(self.ALIAS, (raw_folder / "race-session.transcript.txt").read_text(encoding="utf-8"))
            self.assertIn(self.CANONICAL, corrected_txt.read_text(encoding="utf-8"))

            # Continue: the backend reuses the transcript, whose paths now
            # point at the package's own corrected copy.
            entry["transcript_reuse_status"] = "reused_existing_transcript"
            _build(output, [dict(entry)], **glossary)

            for suffix in (".transcript.txt", ".transcript.srt", ".transcript.json"):
                raw_text = (raw_folder / f"race-session{suffix}").read_text(encoding="utf-8")
                self.assertIn(self.ALIAS, raw_text, suffix)
            raw_payload = json.loads((raw_folder / "race-session.transcript.json").read_text(encoding="utf-8"))
            self.assertNotIn(self.CANONICAL, raw_payload["segments"][0]["text"])
            # Still Whisper's own file, not one rebuilt from segments.
            self.assertEqual(raw_payload["segments"][0]["avg_logprob"], -0.21)
            self.assertNotIn("correction_count", raw_payload)
            raw_full = (output / "transcript" / "raw" / "full_transcript.md").read_text(encoding="utf-8")
            self.assertIn(self.ALIAS, raw_full)
            corrections = json.loads((output / "TRANSCRIPT_CORRECTIONS.json").read_text(encoding="utf-8"))
            self.assertEqual(corrections["correction_record_count"], 1)


if __name__ == "__main__":
    unittest.main()
