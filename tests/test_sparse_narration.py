from __future__ import annotations

from array import array
from pathlib import Path
import math
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core.sparse_narration import (
    chunk_repetition_metrics,
    chunk_repetition_requires_retry,
    detect_speech_intervals,
    filter_sparse_decoder_segments,
    is_silence_hallucination_text,
    repetition_is_blocking,
    repetition_metrics,
    repetition_requires_retry,
    silence_hallucination_metrics,
)


def _write_fixture(path: Path, *, seconds: float = 8.0, sample_rate: int = 16000) -> None:
    samples = array("h")
    for index in range(int(seconds * sample_rate)):
        time_seconds = index / sample_rate
        active = 2.0 <= time_seconds <= 3.2 or 5.0 <= time_seconds <= 6.0
        value = int(8000 * math.sin(2 * math.pi * 220 * time_seconds)) if active else 0
        samples.append(value)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(samples.tobytes())


def _write_quiet_speech_with_loud_reference(path: Path, *, sample_rate: int = 16000) -> None:
    samples = array("h")
    for index in range(10 * sample_rate):
        time_seconds = index / sample_rate
        amplitude = 0
        if 2.0 <= time_seconds <= 3.0:
            amplitude = 400
        elif 6.0 <= time_seconds <= 7.0:
            amplitude = 10000
        samples.append(int(amplitude * math.sin(2 * math.pi * 220 * time_seconds)))
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(samples.tobytes())


class SparseNarrationTests(unittest.TestCase):
    def test_detects_and_pads_speech_intervals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "speech.wav"
            _write_fixture(path)
            intervals, audit = detect_speech_intervals(path)
        self.assertEqual(len(intervals), 2)
        self.assertLess(intervals[0].start_seconds, 2.0)
        self.assertGreater(intervals[0].end_seconds, 3.2)
        self.assertGreater(audit["active_speech_seconds"], 2.0)

    def test_quiet_speech_is_not_masked_by_louder_reference_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mixed-level-speech.wav"
            _write_quiet_speech_with_loud_reference(path)
            intervals, _ = detect_speech_intervals(path)
        self.assertTrue(any(item.start_seconds < 2.1 and item.end_seconds > 2.9 for item in intervals))

    def test_repetition_guard_blocks_loops(self) -> None:
        segments = [
            {"text": "same loop"},
            {"text": "same loop"},
            {"text": "same loop"},
            {"text": "different"},
        ]
        metrics = repetition_metrics(segments)
        self.assertEqual(metrics["max_consecutive_identical_segments"], 3)
        self.assertTrue(repetition_requires_retry(metrics))
        self.assertTrue(repetition_is_blocking(metrics))

    def test_repetition_guard_allows_normal_narration(self) -> None:
        metrics = repetition_metrics(
            [{"text": "first request"}, {"text": "supporting detail"}, {"text": "expected result"}]
        )
        self.assertFalse(repetition_is_blocking(metrics))
        self.assertFalse(repetition_requires_retry(metrics))

    def test_four_consecutive_segments_fail_final_gate(self) -> None:
        metrics = repetition_metrics([{"text": "same"}] * 4)
        self.assertTrue(repetition_requires_retry(metrics))
        self.assertTrue(repetition_is_blocking(metrics))

    def test_cross_chunk_hallucination_phrase_requires_retry(self) -> None:
        prior = [{"text": "Thanks for reviewing"}]
        candidate = [{"text": "Thanks for reviewing"}]
        metrics = chunk_repetition_metrics(prior, candidate)
        self.assertEqual(metrics["cumulative_repeated_segment_ratio"], 0.5)
        self.assertTrue(chunk_repetition_requires_retry(metrics))

    def test_short_repeated_acknowledgement_does_not_poison_later_chunks(self) -> None:
        prior = [{"text": "All right"}, {"text": "First requested change"}]
        candidate = [{"text": "All right"}, {"text": "Second requested change"}]
        metrics = chunk_repetition_metrics(prior, candidate)
        self.assertEqual(metrics["cumulative_repeated_segment_ratio"], 0.0)
        self.assertFalse(chunk_repetition_requires_retry(metrics))

    def test_decoder_filter_preserves_raw_rejection_reasons(self) -> None:
        accepted, filtered = filter_sparse_decoder_segments(
            [
                {"text": "requested change", "compression_ratio": 1.2, "no_speech_prob": 0.1, "avg_logprob": -0.2},
                {"text": "generic outro phrase", "compression_ratio": 0.7, "no_speech_prob": 0.7, "avg_logprob": -0.8},
                {"text": "decoder loop", "compression_ratio": 2.5, "no_speech_prob": 0.1, "avg_logprob": -0.2},
            ]
        )
        self.assertEqual([item["text"] for item in accepted], ["requested change"])
        self.assertEqual(
            [item["reason"] for item in filtered],
            ["combined_low_speech_information", "compression_ratio_threshold"],
        )

    def test_silence_hallucination_is_detected_and_not_counted_as_narration(self) -> None:
        # Whisper on a silent track can write one stock outro line over and over (94).
        segments = [{"text": "Thank you for watching!"} for _ in range(8)] + [{"text": "Hello."}]
        metrics = silence_hallucination_metrics(segments)
        self.assertTrue(metrics["silence_hallucination_suspected"])
        self.assertTrue(metrics["no_narration_found"])
        self.assertEqual(metrics["narration_word_count"], 0)

    def test_real_narration_with_an_occasional_thank_you_is_not_flagged(self) -> None:
        segments = [
            {"text": "The delta bar is not cycling when I press the button."},
            {"text": "Thank you."},
            {"text": "Make that a ticket for the dashboard."},
            {"text": "Okay."},
        ]
        metrics = silence_hallucination_metrics(segments)
        self.assertFalse(metrics["silence_hallucination_suspected"])
        self.assertFalse(metrics["no_narration_found"])
        self.assertGreater(metrics["narration_word_count"], 10)

    def test_empty_transcript_is_no_narration_not_usable(self) -> None:
        metrics = silence_hallucination_metrics([])
        self.assertTrue(metrics["no_narration_found"])
        self.assertFalse(metrics["silence_hallucination_suspected"])
        self.assertTrue(is_silence_hallucination_text("   "))
        self.assertTrue(is_silence_hallucination_text("Thanks for watching, please subscribe!"))
        self.assertFalse(is_silence_hallucination_text("Thanks, the pit strategy page is broken"))



class InventedLineTests(unittest.TestCase):
    """199: lines Whisper invents over music."""

    LOOP = "So, so, um, well, a sample phrase, a sample phrase, a sample phrase"

    def test_a_line_that_loops_a_phrase_is_invented(self) -> None:
        self.assertTrue(is_silence_hallucination_text(self.LOOP))
        self.assertTrue(is_silence_hallucination_text("oh la la, oh la la, oh la la"))

    def test_lines_whisper_invents_over_music_are_invented(self) -> None:
        for text in (
            "Sorry, we are not sure how to translate this sample line.",
            "This sample line is only filler, it's something that's been said "
            "before in another made-up test.",
        ):
            self.assertTrue(is_silence_hallucination_text(text), text)

    def test_outro_lines_whisper_invents_over_quiet_audio_are_invented(self) -> None:
        # 201: outro lines of the kind Whisper writes over a quiet stretch of audio.
        for text in (
            "That was the whole demo clip, I hope you enjoyed it. I hope you enjoyed it.",
            "That is all for this demo clip, please like, comment and subscribe to the channel",
        ):
            self.assertTrue(is_silence_hallucination_text(text), text)

    def test_hoping_someone_enjoyed_something_once_is_kept(self) -> None:
        for text in (
            "I hope you enjoyed it, the new fuel page finally works after the update.",
            "Subscribe the overlay to the channel settings and the delta bar stays put.",
        ):
            self.assertFalse(is_silence_hallucination_text(text), text)

    def test_real_narration_that_repeats_itself_is_kept(self) -> None:
        for text in (
            "No, no, no, no, the delta bar is wrong again.",
            "Left, left, left. Car left. Okay.",
            "The delta bar, the delta bar, the delta bar keeps jumping around in the corner and "
            "I need someone to look at why it does that on every lap at this track.",
            "Create a ticket. Create a ticket for the fuel display.",
            "I'm not sure how to fix the pit board, it keeps jumping.",
            # Three requests in one line: the phrase repeats, with other words between.
            "Make this a ticket for export ordering. Next issue, make this a ticket for menu sorting. "
            "Another bug, make this a ticket for label contrast.",
        ):
            self.assertFalse(is_silence_hallucination_text(text), text)

    def test_the_filter_names_a_phrase_loop(self) -> None:
        accepted, filtered = filter_sparse_decoder_segments(
            [
                {"text": "the limiter light should stay on", "compression_ratio": 1.2, "no_speech_prob": 0.1,
                 "avg_logprob": -0.2, "start": 1.0},
                {"text": self.LOOP, "compression_ratio": 1.9, "no_speech_prob": 0.0, "avg_logprob": -0.3,
                 "start": 4.0},
            ]
        )
        self.assertEqual([item["text"] for item in accepted], ["the limiter light should stay on"])
        self.assertEqual([item["reason"] for item in filtered], ["phrase_loop"])

    def test_a_loop_spread_over_neighbouring_lines_is_dropped_and_real_lines_stay(self) -> None:
        from media_manglers.core.sparse_narration import drop_phrase_loops

        segments = [
            {"start": 600.0, "end": 603.0, "text": "the limiter light should stay on"},
            {"start": 639.0, "end": 642.0, "text": "a sample phrase, a sample phrase"},
            {"start": 644.0, "end": 647.0, "text": "a sample phrase, a sample phrase"},
            {"start": 650.0, "end": 653.0, "text": "make that a ticket for the dashboard"},
            # The same phrase said again much later is not part of the loop.
            {"start": 900.0, "end": 903.0, "text": "a sample phrase"},
        ]
        kept, dropped = drop_phrase_loops(segments)
        self.assertEqual([item["start"] for item in kept], [600.0, 650.0, 900.0])
        # The same short phrase said again tens of seconds apart is the operator, not a loop.
        # A loop's lines follow each other within seconds.
        said_again = [{"start": start, "end": start + 1.5, "text": "[Track 1] Okay, that works."}
                      for start in (300.0, 317.0, 346.0)]
        kept_again, dropped_again = drop_phrase_loops(said_again)
        self.assertEqual((len(kept_again), dropped_again), (3, []))
        self.assertEqual([(item["reason"], item["segment"]["start"]) for item in dropped],
                         [("phrase_loop", 639.0), ("phrase_loop", 644.0)])


if __name__ == "__main__":
    unittest.main()
