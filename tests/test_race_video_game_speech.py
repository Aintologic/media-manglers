"""Other people's voices on the game track (172).

Whisper is not in the test runtime, so these tests feed the filter Whisper-shaped segments and check
the digest the analysis writes from a saved result. All lines and times here are invented examples.
"""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core.race_video.game_speech import find_game_speech, sort_game_speech  # noqa: E402


def _seg(start: float, text: str, **scores) -> dict:
    return {"start": start, "end": start + 2.0, "text": text, "no_speech_prob": scores.get("no_speech", 0.1),
            "avg_logprob": scores.get("logprob", -0.3), "compression_ratio": scores.get("compression", 1.2)}


class FindGameSpeechTests(unittest.TestCase):
    def test_real_voices_are_kept_with_their_times(self) -> None:
        kept = find_game_speech([_seg(120.0, " Good battle, thanks."), _seg(240.0, "Car on your left.")], narration=[])
        self.assertEqual([(s["start"], s["text"]) for s in kept], [(120.0, "Good battle, thanks."), (240.0, "Car on your left.")])

    def test_words_whisper_invents_over_engine_noise_are_dropped(self) -> None:
        segments = [_seg(10, "Thank you for watching!"), _seg(20, "you"), _seg(30, "Thanks for watching, see you in the next video")]
        self.assertEqual(find_game_speech(segments, narration=[]), [])

    def test_unsure_lines_are_dropped(self) -> None:
        segments = [_seg(10, "Box box box", no_speech=0.8), _seg(20, "Pit this lap", logprob=-1.4),
                    _seg(30, "go go go go go go go go go", compression=3.1)]
        self.assertEqual(find_game_speech(segments, narration=[]), [])

    def test_the_drivers_own_voice_bleeding_onto_the_game_track_is_not_another_voice(self) -> None:
        narration = [{"start": 499.5, "end": 503.0, "text": "The rear tyres are going off a bit now."}]
        segments = [_seg(500.0, "the rear tyres are going off a bit now"), _seg(900.0, "The rear tyres are going off.")]
        kept = find_game_speech(segments, narration)
        self.assertEqual([s["start"] for s in kept], [900.0], "the same words at another moment are someone else")

    def test_every_line_left_out_keeps_its_reason(self) -> None:
        # 226: the left-out lines are kept apart, each with why, so nothing is dropped unseen.
        narration = [{"start": 499.5, "end": 503.0, "text": "The front left is graining badly now."}]
        segments = [_seg(10, "Thank you for watching!"), _seg(20, "Box box box", no_speech=0.8),
                    _seg(30, "Pit this lap", logprob=-1.4), _seg(40, "Pit window open now, pit window open.", compression=3.1),
                    _seg(500.0, "the front left is graining badly now"), _seg(900.0, " Clear behind, all yours."),
                    _seg(950.0, "  ")]
        kept, left_out = sort_game_speech(segments, narration)
        self.assertEqual(kept, [{"start": 900.0, "end": 902.0, "text": "Clear behind, all yours."}])
        self.assertEqual(kept, find_game_speech(segments, narration))
        self.assertEqual([(item["start"], item["reason"]) for item in left_out],
                         [(10.0, "filler_whisper_writes_over_noise"), (20.0, "probably_not_speech"),
                          (30.0, "whisper_unsure_of_the_words"), (40.0, "repeated_words"),
                          (500.0, "the_drivers_own_voice")])
        self.assertEqual(left_out[1]["text"], "Box box box")

    def test_a_looped_phrase_is_left_out_as_repeated_words_by_the_shared_rule(self) -> None:
        # 226: the shared loop rule (the one every transcript uses) names a looped phrase as repeated
        # words even when Whisper's compression ratio does not show it.
        line = "Stay out, stay on track, stay out, stay on track, stay out, stay on track."
        kept, left_out = sort_game_speech([_seg(60.0, line, compression=1.3)], narration=[])
        self.assertEqual(kept, [])
        self.assertEqual([(item["start"], item["reason"]) for item in left_out], [(60.0, "repeated_words")])


if __name__ == "__main__":
    unittest.main()
