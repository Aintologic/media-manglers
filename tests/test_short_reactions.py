"""226: the AI Video Editor's "keep short reactions" rule, and features 1-3 left exactly as they were.

The sampled-guess bar (214) drops a line Whisper sampled at random and rates below its own bar. It
also dropped the operator's real short reactions, an exclamation said once, on its own, while driving.
With ``keep_short_reactions`` such a line comes back only when it is its own short burst, the
microphone is really loud at that moment, and a real line is close by. Nothing else changes: with the
option off (every feature but the editor) every file Whisper's helper writes is byte for byte what
the 9e065e4 code wrote.

The narration is made by FFmpeg: tone bursts at known levels, over silence or a quiet hum, so the
voice-activity chunks and the measured levels are real. Whisper itself is not installed in the test
runtime; a scripted model answers for each chunk with made-up lines, as in test_whisper_local.
"""

from __future__ import annotations

import io
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers.core import cross_track_check, sparse_narration as sn  # noqa: E402
from media_manglers.providers import whisper_local  # noqa: E402
from tests.whisper_test_models import checked_whisper, whisper_gets_file_names  # noqa: E402

# H2 of the Wave I-A review: these Whisper stand-ins answer by the file they are given; see whisper_gets_file_names.
_FILE_NAMES = whisper_gets_file_names()


def setUpModule() -> None:  # noqa: N802 - unittest's name
    _FILE_NAMES.start()


def tearDownModule() -> None:  # noqa: N802 - unittest's name
    _FILE_NAMES.stop()

FFMPEG = shutil.which("ffmpeg")
GIT = shutil.which("git")
BASELINE = "9e065e4"
PACKAGE = "mm_baseline_9e065e4_whisper"
ANCHOR_TEXT = "the rear tyres are going off now"

# Whisper's numbers for a plain, confident decode and for a guess sampled below its bar.
REAL = {"temperature": 0.0, "avg_logprob": -0.3, "no_speech_prob": 0.05, "compression_ratio": 1.2}
GUESS = {"temperature": 0.4, "avg_logprob": -1.5, "no_speech_prob": 0.4, "compression_ratio": 0.5}


def _amplitude(dbfs: float) -> float:
    """The peak of a sine whose RMS is ``dbfs``."""

    return math.sqrt(2.0) * 10.0 ** (dbfs / 20.0)


def narration(path: Path, bursts: list[tuple[float, float, float]], *, seconds: float = 40.0,
              hum_dbfs: float | None = None) -> Path:
    """A 16 kHz mono 16-bit narration WAV made by FFmpeg: a 400 Hz tone at each (start, end, dBFS)
    burst, over silence or a 100 Hz hum at ``hum_dbfs``. Whole cycles fit every 20 ms and 50 ms frame,
    so a burst's measured level is the level asked for."""

    terms = [f"{_amplitude(level):.8f}*between(t,{start},{end})*sin(2*PI*400*t)" for start, end, level in bursts]
    if hum_dbfs is not None:
        terms.append(f"{_amplitude(hum_dbfs):.8f}*sin(2*PI*100*t)")
    expression = "+".join(terms) or "0"
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"aevalsrc=exprs='{expression}':s=16000:d={seconds}", "-ac", "1", "-c:a", "pcm_s16le", str(path)],
                   check=True)
    return path


def line(intervals: list, chunk: int, start: float, end: float, text: str, numbers: dict) -> dict:
    """A line Whisper writes for chunk ``chunk`` (1-based), placed at ``start``-``end`` seconds of the
    recording: the decoder reports times from the chunk's own start."""

    offset = intervals[chunk - 1].start_seconds
    return {"start": round(start - offset, 3), "end": round(end - offset, 3), "text": f" {text}", **numbers}


class ScriptedModel:
    """Answers each chunk (chunk-0001.wav, ...) with its scripted lines; a chunk given a list of
    attempts answers its first decode with the first, a retry with the next."""

    script: dict[int, list] = {}
    calls: list[int] = []

    def transcribe(self, audio_path: str, **_kwargs: object) -> dict:
        name = Path(audio_path).stem  # the whole recording (0) outside Sparse mode
        chunk = int(name.split("-")[1]) if name.startswith("chunk-") else 0
        ScriptedModel.calls.append(chunk)
        answer = self.script.get(chunk, [])
        if answer and isinstance(answer[0], list):
            answer = answer[min(ScriptedModel.calls.count(chunk), len(answer)) - 1]
        return {"language": "en", "segments": [dict(item) for item in answer]}


class _CpuTorch:
    __version__ = "0.0.0+cpu"
    version = SimpleNamespace(cuda="")
    cuda = SimpleNamespace(is_available=lambda: False, device_count=lambda: 0)


class _ScriptedWhisper:
    @staticmethod
    def load_model(model_name: str, device: str) -> ScriptedModel:
        return ScriptedModel()


def transcribe(module, wav: Path, output: Path, script: dict[int, list], **payload: object) -> dict:
    """Runs ``module.transcribe_from_request`` (today's or the baseline's) on ``wav`` with the scripted
    model, and returns what it returned plus every file it wrote, by name."""

    ScriptedModel.script, ScriptedModel.calls = script, []
    request = {"audio_path": str(wav), "output_dir": str(output), "model_name": "medium", "language_code": "en",
               "prefer_gpu": False, "task_name": "transcribe", "narration_speech_mode": "Sparse",
               "heartbeat_interval_seconds": 60, **payload}
    with mock.patch.dict(sys.modules, {"whisper": checked_whisper(_ScriptedWhisper()), "torch": _CpuTorch()}, clear=False):
        result = module.transcribe_from_request(request)
    files = {item.name: item.read_bytes() for item in sorted(output.iterdir()) if item.is_file()}
    return {"result": result, "files": files}


def read(run: dict, name: str) -> dict:
    return json.loads(run["files"][name].decode("utf-8"))


def texts(run: dict) -> list[str]:
    return [item["text"].strip() for item in read(run, "transcript.json")["segments"]]


@unittest.skipUnless(FFMPEG, "FFmpeg is required")
class ShortReactionRuleTests(unittest.TestCase):
    """Each condition of the rule, on both sides of its edge."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runs = 0

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_case(self, bursts, lines_for, *, hum_dbfs=None, keep=True, seconds=40.0, **payload) -> tuple[dict, list]:
        """Makes the narration, finds its chunks, scripts Whisper's lines for them, transcribes."""

        self.runs += 1
        wav = narration(self.root / f"case-{self.runs}" / "narration.wav", bursts, hum_dbfs=hum_dbfs, seconds=seconds)
        intervals, _audit = sn.detect_speech_intervals(wav)
        script = lines_for(intervals)
        if keep:
            payload["keep_short_reactions"] = True
        return transcribe(whisper_local, wav, self.root / f"case-{self.runs}" / "out", script, **payload), intervals

    @staticmethod
    def anchored(reactions: list[tuple[float, float, str]], *, anchor=(2.0, 4.0)):
        """Scripts the anchor line in chunk 1 and one reaction (a guess) in each later chunk."""

        def lines_for(intervals):
            script = {1: [line(intervals, 1, anchor[0], anchor[1], ANCHOR_TEXT, REAL)]}
            for number, (start, end, text) in enumerate(reactions, start=2):
                script[number] = [line(intervals, number, start, end, text, GUESS)]
            return script

        return lines_for

    def kept_reactions(self, run: dict) -> list[str]:
        return [item["segment"]["text"].strip() for item in read(run, "transcript.raw.json")["short_reactions_kept"]]

    # The rule as a whole ---------------------------------------------------------------------

    def test_a_loud_short_reaction_near_a_real_line_is_kept_and_listed(self) -> None:
        run, _ = self.run_case([(2.0, 4.0, -25.0), (10.0, 11.0, -30.0)], self.anchored([(10.0, 11.0, "Oh wow.")]))
        self.assertEqual(texts(run), [ANCHOR_TEXT, "Oh wow."])
        raw, quality = read(run, "transcript.raw.json"), read(run, "transcript.quality.json")
        [kept] = raw["short_reactions_kept"]
        self.assertEqual((kept["chunk_index"], kept["attempt"], kept["segment"]["start"], kept["anchor_start"]),
                         (2, 1, 10.0, 2.0))
        self.assertAlmostEqual(kept["line_dbfs"], -30.0, delta=0.2)
        self.assertEqual(kept["segment"]["id"], 1, "the audit holds the line as delivered")
        self.assertEqual(quality["short_reactions_kept_count"], 1)
        self.assertEqual(run["result"]["short_reactions_kept_count"], 1)
        # It left the list of dropped lines; the attempt's own record still shows what the filter did.
        self.assertEqual(raw["filtered_segments"], [])
        attempt = next(item for item in raw["raw_attempts"] if item["chunk_index"] == 2)
        self.assertEqual([item["reason"] for item in attempt["filtered_segments"]], ["sampled_low_confidence"])

    def test_without_the_option_the_reaction_stays_dropped_and_nothing_new_is_written(self) -> None:
        run, _ = self.run_case([(2.0, 4.0, -25.0), (10.0, 11.0, -30.0)], self.anchored([(10.0, 11.0, "Oh wow.")]),
                               keep=False)
        self.assertEqual(texts(run), [ANCHOR_TEXT])
        for name, data in run["files"].items():
            self.assertNotIn(b"short_reaction", data, name)
        self.assertNotIn("short_reactions_kept_count", run["result"])
        self.assertEqual([item["reason"] for item in read(run, "transcript.raw.json")["filtered_segments"]],
                         ["sampled_low_confidence"])

    # Shape -----------------------------------------------------------------------------------

    def test_three_words_are_kept_and_four_are_not(self) -> None:
        run, _ = self.run_case([(2.0, 4.0, -25.0), (8.0, 9.0, -30.0), (12.0, 13.0, -30.0)],
                               self.anchored([(8.0, 9.0, "oh my word"), (12.0, 13.0, "oh my word again")]))
        self.assertEqual(self.kept_reactions(run), ["oh my word"])

    def test_a_line_of_three_seconds_is_kept_and_a_longer_one_is_not(self) -> None:
        # Both chunks are exactly 3.0 s (2.3 s of sound, padded by the VAD); the second line runs past it.
        run, intervals = self.run_case(
            [(2.0, 4.0, -25.0), (8.0, 10.3, -30.0), (14.0, 16.3, -30.0)],
            lambda iv: {1: [line(iv, 1, 2.0, 4.0, ANCHOR_TEXT, REAL)],
                        2: [line(iv, 2, iv[1].start_seconds, iv[1].start_seconds + 3.0, "first one", GUESS)],
                        3: [line(iv, 3, iv[2].start_seconds, iv[2].start_seconds + 3.01, "second one", GUESS)]})
        self.assertEqual([round(item.duration_seconds, 3) for item in intervals[1:]], [3.0, 3.0])
        self.assertEqual(self.kept_reactions(run), ["first one"])

    def test_a_chunk_of_three_seconds_is_kept_and_a_longer_one_is_not(self) -> None:
        run, intervals = self.run_case([(2.0, 4.0, -25.0), (8.0, 10.3, -30.0), (14.0, 16.32, -30.0)],
                                       self.anchored([(8.0, 9.0, "first one"), (14.0, 15.0, "second one")]))
        self.assertEqual([round(item.duration_seconds, 3) for item in intervals[1:]], [3.0, 3.02])
        self.assertEqual(self.kept_reactions(run), ["first one"])

    def test_two_lines_in_the_chunk_are_kept_and_three_are_not(self) -> None:
        def lines_for(iv):
            return {1: [line(iv, 1, 2.0, 4.0, ANCHOR_TEXT, REAL)],
                    2: [line(iv, 2, 8.0, 8.6, "first one", GUESS), line(iv, 2, 8.6, 9.0, "Thank you.", REAL)],
                    3: [line(iv, 3, 12.0, 12.5, "second one", GUESS), line(iv, 3, 12.5, 12.8, "Thank you.", REAL),
                        line(iv, 3, 12.8, 13.0, "Bye.", REAL)]}

        run, _ = self.run_case([(2.0, 4.0, -25.0), (8.0, 9.0, -30.0), (12.0, 13.0, -30.0)], lines_for)
        self.assertEqual(self.kept_reactions(run), ["first one"])

    # Level -----------------------------------------------------------------------------------

    def test_above_minus_47_dbfs_is_kept_and_below_is_not(self) -> None:
        run, _ = self.run_case([(2.0, 4.0, -25.0), (8.0, 9.0, -46.5), (12.0, 13.0, -47.5)],
                               self.anchored([(8.0, 9.0, "first one"), (12.0, 13.0, "second one")]))
        raw = read(run, "transcript.raw.json")
        self.assertEqual(self.kept_reactions(run), ["first one"])
        self.assertAlmostEqual(raw["short_reactions_kept"][0]["line_dbfs"], -46.5, delta=0.1)

    def test_twelve_db_over_the_recordings_quiet_is_kept_and_less_is_not(self) -> None:
        # A hum at -55 dBFS is the recording's quiet, so the bar is -43; both lines are above -47.
        run, _ = self.run_case([(2.0, 4.0, -25.0), (8.0, 9.0, -42.0), (12.0, 13.0, -44.0)],
                               self.anchored([(8.0, 9.0, "first one"), (12.0, 13.0, "second one")]), hum_dbfs=-55.0)
        vad = read(run, "transcript.vad.json")
        self.assertAlmostEqual(sn.rms_dbfs(vad["noise_floor"]), -55.0, delta=0.1)
        self.assertEqual(self.kept_reactions(run), ["first one"])

    # Anchor ----------------------------------------------------------------------------------

    def test_a_real_line_15_seconds_away_anchors_it_and_one_further_away_does_not(self) -> None:
        for start, kept in ((19.0, ["Oh wow."]), (19.01, [])):
            with self.subTest(gap=round(start - 4.0, 3)):
                run, _ = self.run_case([(2.0, 4.0, -25.0), (19.0, 20.0, -30.0)],
                                       self.anchored([(start, start + 0.8, "Oh wow.")]))
                self.assertEqual(self.kept_reactions(run), kept)

    def test_the_real_line_may_come_after_the_reaction(self) -> None:
        def lines_for(iv):
            return {1: [line(iv, 1, 2.0, 3.0, "Oh wow.", GUESS)], 2: [line(iv, 2, 18.0, 20.0, ANCHOR_TEXT, REAL)]}

        run, _ = self.run_case([(2.0, 3.0, -30.0), (18.0, 20.0, -25.0)], lines_for)
        self.assertEqual(self.kept_reactions(run), ["Oh wow."])

    def test_a_line_kept_only_for_sitting_near_narration_or_a_short_line_anchors_nothing(self) -> None:
        def lines_for(iv):
            low_information = {"temperature": 0.0, "avg_logprob": -0.8, "no_speech_prob": 0.3, "compression_ratio": 0.8}
            return {1: [line(iv, 1, 2.0, 4.0, ANCHOR_TEXT, REAL)],
                    2: [line(iv, 2, 60.0, 62.0, "four words kept nearby", low_information)],
                    3: [line(iv, 3, 70.0, 71.0, "short real", REAL)],
                    4: [line(iv, 4, 75.0, 76.0, "Oh wow.", GUESS)]}

        run, _ = self.run_case([(2.0, 4.0, -25.0), (60.0, 62.0, -30.0), (70.0, 71.0, -30.0), (75.0, 76.0, -30.0)],
                               lines_for, seconds=90.0)
        raw = read(run, "transcript.raw.json")
        self.assertEqual([item["segment"]["text"] for item in raw["rescued_segments"]], [" four words kept nearby"])
        self.assertIn("short real", texts(run))
        self.assertEqual(raw["short_reactions_kept"], [])
        self.assertNotIn("Oh wow.", texts(run))

    # What it never lets back -----------------------------------------------------------------

    def test_filler_a_prompt_echo_and_one_word_over_a_long_stretch_never_come_back(self) -> None:
        prompt = "Preferred terminology: Brooklands, Eau Rouge"

        def lines_for(iv):
            return {1: [line(iv, 1, 2.0, 4.0, ANCHOR_TEXT, REAL)],
                    2: [line(iv, 2, 8.0, 9.0, "Thank you.", GUESS)],
                    3: [line(iv, 3, 12.0, 13.0, "Eau Rouge.", GUESS)],
                    4: [line(iv, 4, 16.0, 25.0, "Hmm", GUESS)]}

        run, _ = self.run_case([(2.0, 4.0, -25.0), (8.0, 9.0, -30.0), (12.0, 13.0, -30.0), (16.0, 25.0, -30.0)],
                               lines_for, initial_prompt=prompt)
        raw = read(run, "transcript.raw.json")
        self.assertEqual(texts(run), [ANCHOR_TEXT])
        self.assertEqual(raw["short_reactions_kept"], [])
        self.assertEqual(sorted(item["reason"] for item in raw["filtered_segments"]),
                         ["known_filler_phrase", "prompt_echo", "sampled_low_confidence"])
        long_one = next(item["segment"] for item in raw["filtered_segments"] if item["reason"] == "sampled_low_confidence")
        self.assertTrue(sn.is_one_word_over_a_long_stretch(long_one))
        self.assertFalse(sn.only_fault_is_the_sampled_bar(long_one))

    def test_reactions_that_loop_a_phrase_are_dropped_and_take_no_other_line_with_them(self) -> None:
        # Said once more, the real line's phrase would be a loop across lines (199). The reactions
        # that make it one go; the real line, kept without the option, stays.
        def lines_for(iv):
            return {1: [line(iv, 1, 2.0, 4.0, "oh my god oh my god", REAL)],
                    2: [line(iv, 2, 6.0, 7.0, "oh my god", GUESS)],
                    3: [line(iv, 3, 9.0, 10.0, "Nice one.", GUESS)]}

        bursts = [(2.0, 4.0, -25.0), (6.0, 7.0, -30.0), (9.0, 10.0, -30.0)]
        on, _ = self.run_case(bursts, lines_for)
        off, _ = self.run_case(bursts, lines_for, keep=False)
        self.assertEqual(texts(off), ["oh my god oh my god"])
        self.assertEqual(texts(on), ["oh my god oh my god", "Nice one."])
        raw = read(on, "transcript.raw.json")
        self.assertIn(("phrase_loop", " oh my god"),
                      [(item["reason"], item["segment"]["text"]) for item in raw["filtered_segments"]])

    def test_a_reaction_left_out_is_listed_once_with_its_reason_and_never_marked_kept(self) -> None:
        # Two reactions are considered and left out: one loops the real line's phrase; the other's only
        # real line nearby goes as a loop across chunks (chunk 3 repeats it and is thrown out). Each is
        # listed once among the dropped lines, with why it was left out and the chunk and attempt it
        # came from, not also as the sampled guess it was dropped as first, and it is not marked kept.
        def looping(iv):
            return {1: [line(iv, 1, 2.0, 4.0, "oh my god oh my god", REAL)],
                    2: [line(iv, 2, 6.0, 7.0, "oh my god", GUESS)],
                    3: [line(iv, 3, 9.0, 10.0, "Nice one.", GUESS)]}

        def anchor_goes(iv):
            return {1: [line(iv, 1, 2.0, 3.0, "a sample phrase, a sample phrase", REAL)],
                    2: [line(iv, 2, 6.0, 7.0, "Oh wow.", GUESS)],
                    3: [line(iv, 3, 10.0, 11.0, "a sample phrase, a sample phrase", REAL)],
                    4: [line(iv, 4, 30.0, 32.0, "and into the pit lane now", REAL)]}

        cases = (
            ("loop", [(2.0, 4.0, -25.0), (6.0, 7.0, -30.0), (9.0, 10.0, -30.0)], looping,
             ["oh my god oh my god", "Nice one."], "phrase_loop"),
            ("no anchor", [(2.0, 3.0, -25.0), (6.0, 7.0, -30.0), (10.0, 11.0, -25.0), (30.0, 32.0, -25.0)],
             anchor_goes, ["and into the pit lane now"], sn.SHORT_REACTION_NO_ANCHOR_REASON),
        )
        for name, bursts, lines_for, delivered, reason in cases:
            with self.subTest(name):
                run, _ = self.run_case(bursts, lines_for)
                raw, quality = read(run, "transcript.raw.json"), read(run, "transcript.quality.json")
                self.assertEqual(texts(run), delivered)
                listed = [item for item in raw["filtered_segments"]
                          if (item["segment"]["start"], item["segment"]["end"]) == (6.0, 7.0)]
                self.assertEqual([(item.get("chunk_index"), item.get("attempt"), item["reason"]) for item in listed],
                                 [(2, 1, reason)], raw["filtered_segments"])
                self.assertNotIn(sn.SHORT_REACTION_MARK, json.dumps(raw["filtered_segments"]))
                self.assertEqual(quality["filtered_segment_count"], len(raw["filtered_segments"]))
                self.assertEqual(quality["short_reactions_kept_count"], len(raw["short_reactions_kept"]))
                # The attempt's own record still shows what the sampled-guess bar did.
                attempt = next(item for item in raw["raw_attempts"] if item["chunk_index"] == 2)
                self.assertEqual([item["reason"] for item in attempt["filtered_segments"]], [sn.SHORT_REACTION_REASON])

    def test_only_the_attempt_that_was_used_gives_reactions(self) -> None:
        # Chunk 2's first decode repeats the real line, so it is decoded again; the guess beside the
        # repeat is in the discarded attempt only. Chunk 3 repeats it every time and is thrown out.
        def lines_for(iv):
            repeat = line(iv, 2, 8.6, 9.0, ANCHOR_TEXT, REAL)
            repeat3 = line(iv, 3, 12.6, 13.0, ANCHOR_TEXT, REAL)
            return {1: [line(iv, 1, 2.0, 4.0, ANCHOR_TEXT, REAL)],
                    2: [[line(iv, 2, 8.0, 8.5, "first one", GUESS), repeat], []],
                    3: [[line(iv, 3, 12.0, 12.5, "second one", GUESS), repeat3]]}

        run, _ = self.run_case([(2.0, 4.0, -25.0), (8.0, 9.0, -30.0), (12.0, 13.0, -30.0)], lines_for)
        raw = read(run, "transcript.raw.json")
        self.assertEqual([item["chunk_index"] for item in raw["rejected_chunks"]], [3])
        self.assertEqual(sorted({(item["chunk_index"], item["attempt"]) for item in raw["raw_attempts"]}),
                         [(1, 1), (2, 1), (2, 2), (3, 1), (3, 2)])
        self.assertEqual(raw["short_reactions_kept"], [])
        self.assertEqual(texts(run), [ANCHOR_TEXT])


class ShortReactionEdgeTests(unittest.TestCase):
    """The exact edges, on the predicates the pass uses."""

    def test_the_shape_edges(self) -> None:
        guess = {"start": 10.0, "end": 13.0, "text": " one two three", **GUESS}
        self.assertTrue(sn.is_short_burst(guess, 3.0, 2))
        self.assertFalse(sn.is_short_burst({**guess, "end": 13.001}, 3.0, 2))
        self.assertFalse(sn.is_short_burst(guess, 3.001, 2))
        self.assertFalse(sn.is_short_burst(guess, 3.0, 3))
        self.assertFalse(sn.is_short_burst({**guess, "text": " one two three four"}, 3.0, 2))
        # VAD and decoder times carry three decimals; their difference is not let past by rounding noise.
        self.assertTrue(sn.is_short_burst({**guess, "start": 9.65, "end": 12.65}, 12.65 - 9.65, 2))

    def test_the_level_edges(self) -> None:
        self.assertFalse(sn.is_live_microphone(-47.0, -120.0))
        self.assertTrue(sn.is_live_microphone(-46.99, -120.0))
        self.assertTrue(sn.is_live_microphone(-40.0, -52.0))
        self.assertFalse(sn.is_live_microphone(-40.01, -52.0))

    def test_the_anchor_edge(self) -> None:
        reaction = {"start": 19.0, "end": 19.8, "text": " Oh wow.", **GUESS}
        real = {"start": 2.0, "end": 4.0, "text": f" {ANCHOR_TEXT}", **REAL}
        self.assertIs(sn.short_reaction_anchor(reaction, [real]), real)
        self.assertIsNone(sn.short_reaction_anchor({**reaction, "start": 19.001}, [real]))
        after = {**real, "start": 34.8, "end": 36.0}
        self.assertIs(sn.short_reaction_anchor(reaction, [after]), after)
        self.assertIsNone(sn.short_reaction_anchor(reaction, [{**after, "start": 34.801}]))
        self.assertIsNone(sn.short_reaction_anchor(reaction, [{**real, "text": " only three words"}]))


@unittest.skipUnless(FFMPEG, "FFmpeg is required")
class ReanchorTests(unittest.TestCase):
    """The editor drops lines after the transcript is written (cross-track, near silent); a kept
    reaction whose real line went with them goes too."""

    def test_a_reaction_hanging_on_a_line_the_near_silent_check_drops_goes_too(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # Whisper wrote a confident line over a microphone at -52 dBFS: invented, and the only
            # real-looking line near the loud reaction.
            wav = narration(root / "narration.wav", [(2.0, 4.0, -52.0), (10.0, 11.0, -30.0), (40.0, 43.0, -25.0)],
                            seconds=60.0)
            intervals, _audit = sn.detect_speech_intervals(wav)
            script = {1: [line(intervals, 1, 2.0, 4.0, ANCHOR_TEXT, REAL)],
                      2: [line(intervals, 2, 10.0, 11.0, "Oh wow.", GUESS)],
                      3: [line(intervals, 3, 40.0, 43.0, "and into the pit lane now", REAL)]}
            run = transcribe(whisper_local, wav, root / "out", script, keep_short_reactions=True)
            raw = read(run, "transcript.raw.json")
            self.assertEqual([item["segment"]["text"].strip() for item in raw["short_reactions_kept"]], ["Oh wow."])
            delivered = read(run, "transcript.json")["segments"]
            kept, dropped = cross_track_check.cross_check_segments(
                delivered, [], cross_track_check.wav_slice_extractor({0: wav}), lambda path: [], root / "check",
                narration_ordinal=0)
            self.assertEqual([item["reason"] for item in dropped], ["narration_track_near_silent"])
            kept, gone = sn.reanchor_short_reactions(kept, raw["short_reactions_kept"],
                                                     not_anchors=raw["rescued_segments"])
        self.assertEqual([item["text"].strip() for item in kept], ["and into the pit lane now"])
        self.assertEqual([(item["reason"], item["segment"]["text"].strip()) for item in gone],
                         [("short_reaction_without_anchor", "Oh wow.")])

    def test_a_reaction_whose_line_survives_stays_and_a_rescued_line_is_no_anchor(self) -> None:
        reaction = {"id": 1, "start": 10.0, "end": 11.0, "text": " Oh wow."}
        real = {"id": 0, "start": 2.0, "end": 4.0, "text": f" {ANCHOR_TEXT}"}
        kept, gone = sn.reanchor_short_reactions([real, reaction], [{"segment": dict(reaction)}])
        self.assertEqual((kept, gone), ([real, reaction], []))
        kept, gone = sn.reanchor_short_reactions([real, reaction], [{"segment": dict(reaction)}],
                                                 not_anchors=[{"segment": dict(real)}])
        self.assertEqual((kept, [item["segment"]["text"] for item in gone]), ([real], [" Oh wow."]))


# Features 1-3 unchanged ---------------------------------------------------------------------------

def _baseline_problem() -> str:
    if not FFMPEG:
        return "FFmpeg is required"
    if not GIT:
        return "git is required to take the 9e065e4 code out of the repository"
    found = subprocess.run([GIT, "-C", str(REPO_ROOT), "cat-file", "-e", f"{BASELINE}^{{commit}}"],
                           capture_output=True, check=False)
    return "" if found.returncode == 0 else f"commit {BASELINE} is not in this clone (a shallow clone?)"


def load_baseline(root: Path) -> SimpleNamespace:
    """The 9e065e4 ``media_manglers`` package, unpacked under another name with its own imports pointing
    at itself, so the old Whisper helper runs with the old filters."""

    archive = subprocess.run([GIT, "-C", str(REPO_ROOT), "archive", "--format=tar", BASELINE, "src/media_manglers"],
                             capture_output=True, check=True).stdout
    package = (root / PACKAGE).resolve()
    own = re.compile(r"^(\s*)(from|import) media_manglers(?=[.\s])", re.MULTILINE)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            prefix = "src/media_manglers/"
            if not member.isfile() or not member.name.startswith(prefix):
                continue
            target = (package / member.name[len(prefix):]).resolve()
            if not target.is_relative_to(package):
                raise RuntimeError(f"unexpected path in the {BASELINE} archive: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            data = tar.extractfile(member).read()
            if target.suffix == ".py":
                data = own.sub(lambda match: f"{match.group(1)}{match.group(2)} {PACKAGE}", data.decode("utf-8")).encode("utf-8")
            target.write_bytes(data)
    import importlib

    sys.path.insert(0, str(root))
    importlib.invalidate_caches()
    writing = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        modules = SimpleNamespace(
            whisper_local=importlib.import_module(f"{PACKAGE}.providers.whisper_local"),
            cross_track_check=importlib.import_module(f"{PACKAGE}.core.cross_track_check"),
            sparse_narration=importlib.import_module(f"{PACKAGE}.core.sparse_narration"),
        )
    finally:
        sys.dont_write_bytecode = writing
    for module in vars(modules).values():
        assert Path(module.__file__).resolve().is_relative_to(package), module.__file__
    assert modules.whisper_local.filter_sparse_decoder_segments.__module__.startswith(PACKAGE)
    return modules


def unload_baseline(root: Path) -> None:
    for name in [name for name in sys.modules if name == PACKAGE or name.startswith(PACKAGE + ".")]:
        del sys.modules[name]
    if str(root) in sys.path:
        sys.path.remove(str(root))


def recorded_style_script(intervals: list) -> dict[int, list]:
    """Every kind of line the sparse filters judge, as recorded runs have them: real narration, a
    short guess (a reaction with the option on), a long guess, filler, a low-information line kept
    near narration, a cross-chunk loop, a chunk decoded again, and a chunk thrown out."""

    low = {"temperature": 0.0, "avg_logprob": -0.8, "no_speech_prob": 0.3, "compression_ratio": 0.8}
    loop = "a sample phrase, a sample phrase"
    return {
        1: [line(intervals, 1, 2.0, 4.0, ANCHOR_TEXT, REAL)],
        2: [line(intervals, 2, 6.0, 7.0, "Oh wow.", GUESS)],
        3: [line(intervals, 3, 9.0, 9.8, "and the gap is closing fast", REAL),
            line(intervals, 3, 9.8, 10.2, "Thanks for watching!", REAL), line(intervals, 3, 10.2, 10.5, "box", low)],
        4: [line(intervals, 4, 13.0, 19.0, "a sampled sentence nobody said at all", GUESS)],
        # Repeats the first line, so it is decoded again; the second decode is the one used.
        5: [[line(intervals, 5, 21.0, 21.5, "Nice one.", GUESS), line(intervals, 5, 21.6, 22.0, ANCHOR_TEXT, REAL)],
            [line(intervals, 5, 21.0, 21.5, "Nice one.", GUESS)]],
        # Repeats it every time, so it is thrown out.
        6: [[line(intervals, 6, 24.0, 24.4, ANCHOR_TEXT, REAL), line(intervals, 6, 24.5, 25.0, "Whoa!", GUESS)]],
        7: [line(intervals, 7, 28.0, 29.0, loop, REAL)],
        8: [line(intervals, 8, 31.0, 32.0, loop, REAL)],
    }


RECORDED_STYLE_BURSTS = [(2.0, 4.0, -25.0), (6.0, 7.0, -30.0), (9.0, 10.5, -40.0), (13.0, 19.0, -35.0),
                         (21.0, 22.0, -30.0), (24.0, 25.0, -30.0), (28.0, 29.0, -28.0), (31.0, 32.0, -28.0)]
CONTINUOUS_SCRIPT = {0: [
    {"start": 2.0, "end": 4.0, "text": f" {ANCHOR_TEXT}", **REAL},
    {"start": 6.0, "end": 7.0, "text": " Oh wow.", **GUESS},
    {"start": 9.8, "end": 10.2, "text": " Thanks for watching!", **REAL},
    {"start": 28.0, "end": 29.0, "text": " a sample phrase, a sample phrase, a sample phrase", **REAL},
]}

PROBLEM = _baseline_problem()


@unittest.skipIf(bool(PROBLEM), PROBLEM)
class FeaturesOneToThreeUnchangedTests(unittest.TestCase):
    """With the new options off, today's Whisper helper writes what the 9e065e4 one wrote."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.old = load_baseline(cls.root / "baseline")
        cls.wav = narration(cls.root / "narration.wav", RECORDED_STYLE_BURSTS, hum_dbfs=-62.0)
        cls.intervals, _audit = sn.detect_speech_intervals(cls.wav)

    @classmethod
    def tearDownClass(cls) -> None:
        unload_baseline(cls.root / "baseline")
        cls.temp.cleanup()

    def both(self, name: str, **payload) -> tuple[dict, dict]:
        script = recorded_style_script(self.intervals)
        old = transcribe(self.old.whisper_local, self.wav, self.root / name / "old", script)
        new = transcribe(whisper_local, self.wav, self.root / name / "new", script, **payload)
        return old, new

    def assert_same(self, old: dict, new: dict) -> None:
        self.assertEqual(sorted(old["files"]), sorted(new["files"]))
        for name in old["files"]:
            self.assertEqual(old["files"][name], new["files"][name], name)
        paths = {key for key, value in old["result"].items() if str(value).startswith(str(self.root))}
        self.assertEqual({key: value for key, value in old["result"].items() if key not in paths},
                         {key: value for key, value in new["result"].items() if key not in paths})

    def test_the_recorded_style_run_covers_every_kind_of_line(self) -> None:
        self.assertEqual(len(self.intervals), 8)
        _old, new = self.both("coverage", keep_short_reactions=True)
        raw = read(new, "transcript.raw.json")
        self.assertEqual({item["reason"] for item in raw["filtered_segments"]},
                         {"known_filler_phrase", "sampled_low_confidence", "phrase_loop"})
        self.assertEqual([item["chunk_index"] for item in raw["rejected_chunks"]], [6, 8])
        self.assertEqual(len(raw["rescued_segments"]), 1)
        # On, only the reactions from used attempts come back ("Whoa!" was in a thrown-out chunk).
        self.assertEqual([item["segment"]["text"].strip() for item in raw["short_reactions_kept"]],
                         ["Oh wow.", "Nice one."])

    def test_with_the_option_absent_every_file_is_the_same(self) -> None:
        self.assert_same(*self.both("absent"))

    def test_with_the_option_off_every_file_is_the_same(self) -> None:
        self.assert_same(*self.both("off", keep_short_reactions=False, progress_work_units=False))

    def test_with_the_option_on_the_transcript_only_gains_the_reactions(self) -> None:
        old, new = self.both("on", keep_short_reactions=True)
        before = [(item["start"], item["text"].strip()) for item in read(old, "transcript.json")["segments"]]
        after = [(item["start"], item["text"].strip()) for item in read(new, "transcript.json")["segments"]]
        added = [(item["segment"]["start"], item["segment"]["text"].strip())
                 for item in read(new, "transcript.raw.json")["short_reactions_kept"]]
        self.assertEqual(len(added), 2)
        self.assertEqual(sorted(before + added), after)

    def test_continuous_mode_writes_the_same_transcript_with_the_option_on_or_off(self) -> None:
        # Continuous mode has no sampled-guess bar, so it drops no reaction to keep. Off (absent or
        # False), every file is the same. On, the transcript JSON, SRT and TXT are the same, and only the
        # raw and quality audits (and the result) gain the empty list of kept reactions and its count, 0.
        transcript = ("transcript.json", "transcript.srt", "transcript.txt")
        for name, payload in (("continuous-off", {}), ("continuous-off-explicit", {"keep_short_reactions": False}),
                              ("continuous-on", {"keep_short_reactions": True})):
            with self.subTest(name):
                old = transcribe(self.old.whisper_local, self.wav, self.root / name / "old", CONTINUOUS_SCRIPT,
                                 narration_speech_mode="Continuous")
                new = transcribe(whisper_local, self.wav, self.root / name / "new", CONTINUOUS_SCRIPT,
                                 narration_speech_mode="Continuous", **payload)
                self.assertEqual(texts(new), [ANCHOR_TEXT, "Oh wow."])
                if not payload.get("keep_short_reactions"):
                    self.assert_same(old, new)
                    continue
                self.assertEqual(sorted(old["files"]), sorted(new["files"]))
                for file_name in transcript:
                    self.assertEqual(new["files"][file_name], old["files"][file_name], file_name)
                self.assertEqual({file_name for file_name in old["files"] if new["files"][file_name] != old["files"][file_name]},
                                 {"transcript.raw.json", "transcript.quality.json"})
                raw_old, raw_new = read(old, "transcript.raw.json"), read(new, "transcript.raw.json")
                self.assertEqual(raw_new.pop("short_reactions_kept"), [])
                self.assertEqual(raw_new, raw_old)
                quality_old, quality_new = read(old, "transcript.quality.json"), read(new, "transcript.quality.json")
                self.assertEqual(quality_new.pop("short_reactions_kept_count"), 0)
                self.assertEqual(quality_new, quality_old)
                paths = {key for key, value in old["result"].items() if str(value).startswith(str(self.root))}
                result_old = {key: value for key, value in old["result"].items() if key not in paths}
                result_new = {key: value for key, value in new["result"].items() if key not in paths}
                self.assertEqual(result_new.pop("short_reactions_kept_count"), 0)
                self.assertEqual(result_new, result_old)

    def test_the_level_measure_is_the_one_the_cross_track_check_used(self) -> None:
        self.assertIs(cross_track_check.peak_dbfs, sn.peak_dbfs)
        self.assertEqual(cross_track_check.NEAR_SILENT_DBFS, self.old.cross_track_check.NEAR_SILENT_DBFS)
        self.assertEqual(cross_track_check.CROSS_CHECK_PEAK_SHARE, self.old.cross_track_check.CROSS_CHECK_PEAK_SHARE)
        cut = cross_track_check.wav_slice_extractor({0: self.wav})
        for index, (start, end) in enumerate(((0.0, 40.0), (2.0, 4.0), (8.0, 8.3), (12.0, 13.5), (30.5, 30.8),
                                              (39.9, 41.0), (5.0, 5.0))):
            with self.subTest(start=start, end=end):
                piece = cut(0, start, end - start, self.root / "cuts" / f"cut-{index}.wav")
                self.assertEqual(cross_track_check.peak_dbfs(piece), self.old.cross_track_check.peak_dbfs(piece))
                self.assertEqual(sn.span_peak_dbfs(self.wav, start, end), self.old.cross_track_check.peak_dbfs(piece))


if __name__ == "__main__":
    unittest.main()
