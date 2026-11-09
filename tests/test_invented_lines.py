"""214: lines Whisper invents in a narrated recording are left out, the same every run.

When the plain decode of a quiet stretch fails Whisper's own checks, it samples at random
(temperature 0.2, then 0.4) and keeps the last sample even when that fails its confidence bar too.
Nothing seeded that, so each run wrote different invented lines there, and a long one-word line
("A" over 24 seconds) was kept by being next to another guess. The shared filters now drop a guess
Whisper rates below its bar, a line with too few words for its length, and Whisper writing its own
prompt back; none of them can keep another line; every decode is seeded; and the package checks
flag such a line if one is ever kept.
"""

from __future__ import annotations

from pathlib import Path
import random
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core.evidence_package import _build_transcript_quality  # noqa: E402
from media_manglers.core.sparse_narration import (  # noqa: E402
    filter_sparse_decoder_segments,
    silence_hallucination_metrics,
)
from media_manglers.providers import whisper_local  # noqa: E402

PROMPT = "Preferred terminology: Brooklands, Eau Rouge, Crew Chief"


def _seg(start: float, end: float, text: str, *, temperature: float = 0.0, logprob: float = -0.4,
         no_speech: float = 0.1, compression: float = 1.2) -> dict:
    return {"start": start, "end": end, "text": f" {text}", "temperature": temperature, "avg_logprob": logprob,
            "no_speech_prob": no_speech, "compression_ratio": compression}


def _texts(segments: list[dict]) -> list[str]:
    return [segment["text"].strip() for segment in segments]


class FilterTests(unittest.TestCase):
    def test_a_guess_below_whispers_bar_is_dropped_and_keeps_nothing_else(self) -> None:
        # The shape of the kept invented lines: a sampled sentence Whisper rates low, and a
        # one-word line beside it that used to be kept for sitting next to "narration".
        guess = _seg(107.4, 113.4, "a sampled sentence that nobody said at all", temperature=0.4, logprob=-1.92,
                     no_speech=0.45, compression=1.30)
        beside = _seg(136.2, 160.3, "A", temperature=0.4, logprob=-2.55, no_speech=0.49, compression=0.84)
        kept, filtered = filter_sparse_decoder_segments([guess, beside])
        self.assertEqual(kept, [])
        self.assertEqual({item["reason"] for item in filtered}, {"sampled_low_confidence"})

    def test_one_word_over_a_long_stretch_is_dropped_even_from_the_plain_decode(self) -> None:
        kept, filtered = filter_sparse_decoder_segments([_seg(10.0, 34.0, "The", logprob=-0.5)])
        self.assertEqual(kept, [])
        self.assertEqual(filtered[0]["reason"], "too_few_words_for_its_length")

    def test_a_real_line_stretched_over_a_long_time_stays(self) -> None:
        # Whisper often stretches a short real line over silence: only one word over a long stretch goes.
        slow = _seg(2870.3, 2888.8, "a short real line stretched over the quiet", logprob=-0.24)
        lead_in = _seg(2518.7, 2545.2, "so then", logprob=-0.69)
        kept, filtered = filter_sparse_decoder_segments([slow, lead_in])
        self.assertEqual(len(kept), 2, filtered)

    def test_whisper_writing_its_prompt_back_is_dropped(self) -> None:
        echo = _seg(1720.0, 1722.0, "Brooklands, Eau Rouge, Crew Chief", temperature=0.4, logprob=-0.68)
        real = _seg(1730.0, 1733.0, "the Brooklands livery is wrong", logprob=-0.4)
        kept, filtered = filter_sparse_decoder_segments([echo, real], prompt_text=PROMPT)
        self.assertEqual(_texts(kept), ["the Brooklands livery is wrong"])
        self.assertEqual(filtered[0]["reason"], "prompt_echo")

    def test_real_short_lines_and_confident_samples_stay(self) -> None:
        lines = [
            _seg(1573.9, 1576.9, "is this thing on", logprob=-0.44),
            _seg(1732.9, 1734.9, "testing testing", logprob=-0.85, no_speech=0.1),
            _seg(1655.0, 1662.5, "add a dark mode toggle and create a ticket", logprob=-0.36),
            _seg(1800.0, 1803.0, "a confident sampled line", temperature=0.4, logprob=-0.7),
        ]
        kept, filtered = filter_sparse_decoder_segments(lines, prompt_text=PROMPT)
        self.assertEqual(len(kept), 4, filtered)


class CheckTests(unittest.TestCase):
    def test_a_kept_invented_line_is_counted_and_listed(self) -> None:
        metrics = silence_hallucination_metrics([_seg(136.2, 160.3, "A"), _seg(1655.0, 1662.5, "a real line here")])
        self.assertEqual(metrics["suspect_line_count"], 1)
        self.assertEqual(metrics["silence_hallucination_segment_count"], 1)
        self.assertEqual(metrics["suspect_lines"][0]["reason"], "too_few_words_for_its_length")

    def test_the_package_check_warns_about_one_kept_invented_line(self) -> None:
        source = {"status": "completed", "duration_seconds": "1866", "narration_speech_mode": "Sparse",
                  "audio_stream_count": 6, "audio_stream_selection_confirmed": True,
                  "segments": [_seg(136.2, 160.3, "A"),
                               _seg(1655.0, 1662.5, "add a dark mode toggle and create a ticket about it")]}
        quality = _build_transcript_quality(source)
        # A warning to look at, not a transcript to distrust.
        self.assertEqual(quality["quality_status"], "usable_with_warnings")
        self.assertTrue(any("look invented" in reason and "02:16" in reason for reason in quality["warning_reasons"]),
                        quality["warning_reasons"])


class SeedTests(unittest.TestCase):
    def test_every_decode_is_seeded_first(self) -> None:
        source = Path(whisper_local.__file__).read_text(encoding="utf-8")
        calls = [match.start() for match in re.finditer(r"model\.transcribe\(", source)]
        self.assertEqual(len(calls), 3)
        for position in calls:
            self.assertIn("seed_whisper_decoder()", source[max(0, position - 120):position])

    def test_a_seeded_decoder_repeats_itself(self) -> None:
        whisper_local.seed_whisper_decoder()
        first = [random.random() for _ in range(3)]
        whisper_local.seed_whisper_decoder()
        self.assertEqual(first, [random.random() for _ in range(3)])


if __name__ == "__main__":
    unittest.main()
