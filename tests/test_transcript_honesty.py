"""Filler filtering, voice-track choice and honest quality reports (118-121)."""

from __future__ import annotations

from pathlib import Path
import re
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers.core.evidence_package import (  # noqa: E402
    _game_audio_metrics,
    _quality_summary,
    _build_transcript_quality,
)
from media_manglers.core.sparse_narration import (  # noqa: E402
    filter_sparse_decoder_segments,
    is_silence_hallucination_text,
)
from media_manglers.core.voice_track import TrackActivity, TrackProbe, decide  # noqa: E402

SCRIPT = REPO_ROOT / "Video Mangler.ps1"


def segment(text: str, start: float, *, no_speech: float = 0.05, logprob: float = -0.3, compression: float = 1.4) -> dict:
    return {
        "text": text,
        "start": start,
        "end": start + 3.0,
        "no_speech_prob": no_speech,
        "avg_logprob": logprob,
        "compression_ratio": compression,
    }


class FillerFilterTests(unittest.TestCase):
    """119: keep the operator's words, drop what Whisper invents."""

    def test_invented_video_lines_are_dropped_even_when_they_decode_cleanly(self) -> None:
        invented = [
            "Thanks for watching!",
            "I'm sorry for the poor quality of the audio, I'm sorry for the poor quality of the audio.",
            "If you did, please leave a like, comment, and subscribe.",
            "Hi everyone, welcome to my channel.",
            "If you want to see more of this video, go to my website, link in the description",
        ]
        accepted, filtered = filter_sparse_decoder_segments(
            [segment(text, index * 60.0) for index, text in enumerate(invented)]
        )
        self.assertEqual(accepted, [], "invented lines must not reach the transcript")
        self.assertEqual({item["reason"] for item in filtered}, {"known_filler_phrase"})

    def test_short_real_speech_next_to_narration_is_kept(self) -> None:
        """A short aside next to narration was thrown away as low information."""

        narration = segment(
            "so if the export fails, the status panel should say which file it was working on",
            600.0,
        )
        aside = segment("Log file.", 609.8, no_speech=0.35, logprob=-0.9, compression=0.6)
        accepted, filtered = filter_sparse_decoder_segments([narration, aside])
        self.assertEqual([item["text"] for item in accepted], [narration["text"], aside["text"]])
        self.assertEqual(filtered, [])

    def test_the_same_fragment_alone_in_silence_is_still_dropped(self) -> None:
        aside = segment("Log file.", 609.8, no_speech=0.35, logprob=-0.9, compression=0.6)
        accepted, filtered = filter_sparse_decoder_segments([aside])
        self.assertEqual(accepted, [])
        self.assertEqual(filtered[0]["reason"], "combined_low_speech_information")

    def test_narration_from_an_earlier_chunk_also_rescues_a_fragment(self) -> None:
        narration = segment("okay so the export takes a while to finish sometimes", 596.0)
        aside = segment("Log file.", 609.8, no_speech=0.35, logprob=-0.9, compression=0.6)
        accepted, _filtered = filter_sparse_decoder_segments([aside], context_segments=[narration])
        self.assertEqual([item["text"] for item in accepted], [aside["text"]])

    def test_known_filler_is_recognised_inside_longer_text(self) -> None:
        self.assertTrue(is_silence_hallucination_text("Thanks for watching!"))
        self.assertTrue(is_silence_hallucination_text("I'm sorry for the poor quality of the audio."))
        self.assertFalse(
            is_silence_hallucination_text(
                "Note for the AI: create a ticket, the status panel keeps the old value after the restart"
            )
        )


class VoiceTrackChoiceTests(unittest.TestCase):
    """120: one voice on several tracks means the usual microphone wins."""

    def _shared_voice_tracks(self) -> tuple[dict[int, TrackActivity], dict[int, TrackProbe]]:
        # A 10-minute recording whose speech comes in phrases, as a microphone's does (144).
        def speech(ordinal: int, active_ratio: float, peak_dbfs: float, phrases: int) -> TrackActivity:
            return TrackActivity(ordinal=ordinal, duration_seconds=600.0, active_ratio=active_ratio,
                                 peak_dbfs=peak_dbfs, silent=False,
                                 intervals=[(index * 20.0, index * 20.0 + 1.0) for index in range(phrases)])

        activities = {
            0: speech(0, 0.0021, -12.0, 1),
            1: speech(1, 0.1812, -9.0, 20),
            2: speech(2, 0.0021, -14.0, 1),
        }
        probes = {
            0: TrackProbe(ordinal=0, confident_words=14, spotter_words=0, sample_text="one more left side"),
            1: TrackProbe(ordinal=1, confident_words=11, spotter_words=0, sample_text="example microphone narration"),
            2: TrackProbe(ordinal=2, confident_words=13, spotter_words=0, sample_text="one more left side"),
        }
        return activities, probes

    def test_usual_track_is_used_when_the_same_voice_is_on_several_tracks(self) -> None:
        activities, probes = self._shared_voice_tracks()
        shared = [(0, 1), (0, 2), (1, 2)]
        decision = decide(activities, probes, {}, [1], shared)
        self.assertEqual(decision["status"], "selected")
        self.assertEqual(decision["selected_ordinal"], 1, decision["explanation"])
        self.assertEqual(decision["selection_reason"], "usual_microphone_track_in_shared_group")
        self.assertIn("usual microphone track", decision["explanation"])

    def test_without_a_usual_track_the_fullest_capture_still_wins(self) -> None:
        activities, probes = self._shared_voice_tracks()
        decision = decide(activities, probes, {}, [], [(0, 1), (0, 2), (1, 2)])
        self.assertEqual(decision["selected_ordinal"], 0)
        self.assertEqual(decision["selection_reason"], "highest_isolated_speech_score")


class ContaminationTests(unittest.TestCase):
    """120: a transcript full of spotter call-outs must be reported as such."""

    def test_spotter_heavy_transcript_is_flagged(self) -> None:
        text = (
            "Clear. Left side. Clear. Clear. Right side, clear, clear. One more. Still there. "
            "Okay, I want to brake a little earlier into this corner on the next lap"
        )
        metrics = _game_audio_metrics({}, text)
        self.assertTrue(metrics["game_spotter_contamination_suspected"], metrics)
        self.assertGreaterEqual(metrics["game_spotter_word_count"], 5)

    def test_operator_narration_is_not_flagged(self) -> None:
        text = (
            "Note for the AI: create a ticket, the status panel shows the wrong "
            "value for a moment after the restart, then it recovers on the next lap."
        )
        metrics = _game_audio_metrics({}, text)
        self.assertFalse(metrics["game_spotter_contamination_suspected"], metrics)


class QualityReportTests(unittest.TestCase):
    """118: sparse narration is normal; a failed transcript is never low risk."""

    def _source(self, **overrides) -> dict:
        source = {
            "status": "completed",
            "duration_seconds": "2400",
            "narration_speech_mode": "Sparse",
            "segments": [
                {"start": 1600.0, "end": 1620.0, "text": "Note for the AI: create a ticket, the status panel shows the wrong value after the restart"},
            ],
            "audio_stream_count": 6,
            "audio_stream_selection_confirmed": True,
        }
        source.update(overrides)
        return source

    def test_sparse_narration_is_not_suspicious(self) -> None:
        quality = _build_transcript_quality(self._source())
        self.assertEqual(quality["quality_status"], "usable", quality["warning_reasons"])
        self.assertTrue(quality["appears_usable"])

    def test_the_same_transcript_in_full_mode_still_warns(self) -> None:
        quality = _build_transcript_quality(self._source(narration_speech_mode="Full"))
        self.assertIn("long video has very low transcript word count", quality["warning_reasons"])

    def test_failed_transcript_is_not_low_risk(self) -> None:
        quality = _build_transcript_quality(self._source(status="failed", segments=[]))
        self.assertEqual(quality["quality_status"], "failed_needs_retranscription")
        self.assertEqual(quality["risk_classification"], "failed_transcription")

    def test_summary_counts_usable_sources(self) -> None:
        usable = {"transcript_quality": _build_transcript_quality(self._source())}
        failed = {"transcript_quality": _build_transcript_quality(self._source(status="failed", segments=[]))}
        summary = _quality_summary([usable, failed])
        self.assertEqual(summary["usable_source_count"], 1)
        self.assertEqual(summary["source_count"], 2)


class PackageStatusWiringTests(unittest.TestCase):
    def test_status_downgrades_when_a_source_is_unusable(self) -> None:
        text = (REPO_ROOT / "src" / "media_manglers" / "core" / "evidence_package.py").read_text(encoding="utf-8")
        self.assertIn('session_status["status"] = "ready_with_problems"', text)

    def test_file_inputs_do_not_create_an_input_folder(self) -> None:
        """121: a .mmlist run left an empty _VIDEO_INPUT folder behind."""

        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("$inputIsExplicitFile", text)
        guard = re.search(
            r"if \(-not \$ReviewNewVideos -and -not \$inputIsExplicitFile\) \{\s*\r?\n\s*\$InputFolder = Resolve-StartupDirectory",
            text,
        )
        self.assertIsNotNone(guard, "the input-folder resolve must be skipped for file inputs")


if __name__ == "__main__":
    unittest.main()
