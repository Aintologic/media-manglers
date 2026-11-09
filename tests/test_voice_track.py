from __future__ import annotations

from array import array
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable
import unittest
from unittest import mock
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core.voice_track import (
    TrackActivity,
    TrackProbe,
    analyze_track_wav,
    choose_probe_windows,
    confident_speech,
    count_spotter_words,
    decide,
    extract_all_tracks,
    run_while_progressing,
    shares_speech,
    write_probe_wav,
)


def _write_wav(path: Path, pattern: list[tuple[float, float]], *, seconds: float, rate: int = 16000) -> None:
    """Write a tone that is on during each (start, end) interval, digital silence otherwise."""

    samples = array("h")
    for index in range(int(seconds * rate)):
        t = index / rate
        on = any(start <= t < end for start, end in pattern)
        samples.append(int(9000 * math.sin(2 * math.pi * 220 * t)) if on else 0)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(samples.tobytes())


def _three_track_recording(path: Path) -> Path:
    """A 20 s mkv like an OBS recording: a video track and three 48 kHz stereo FLAC tracks.

    Track 1 is noise that is loud 80% of the time (a game mix: busy, not steady enough to be
    taken for a noise floor), Track 2 a tone that is on one second in four (a push-to-talk
    microphone) and Track 3 is digital silence.
    """

    subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-v", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc=size=64x48:rate=5:duration=20",
                    "-f", "lavfi", "-i", "anoisesrc=d=20:r=48000:a=0.3,"
                                         "volume='if(lt(mod(t,1),0.8),1,0.01)':eval=frame",
                    "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:duration=20,"
                                         "volume='if(lt(mod(t,4),1),1,0)':eval=frame",
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                    "-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:a", "-t", "20",
                    "-c:v", "ffv1", "-c:a", "flac", "-ac", "2", "-ar", "48000", str(path)], check=True)
    return path


def _transcriber_hearing(words: dict[int, str]) -> Callable[[Path], list[dict[str, object]]]:
    """Whisper stood in for: each probe file is answered with the words of its track."""

    def transcriber(path: Path) -> list[dict[str, object]]:
        text = words.get(int(path.stem.split("-")[-1]), "")
        return [{"text": text, "no_speech_prob": 0.05, "avg_logprob": -0.3}] if text else []

    return transcriber


NARRATION_WORDS = " ".join(["the", "delta", "bar", "keeps", "jumping", "around", "in", "the", "corner"] * 10)


def _activity(ordinal: int, *, silent: bool = False, active_ratio: float = 0.05) -> TrackActivity:
    # Speech comes in phrases (144): give a sounding track about ten separate bursts per minute
    # of sound, as a microphone has, so the phrase test does not take it for a steady bed.
    sounding_minutes = 0.0 if silent else active_ratio * 300.0 / 60.0
    intervals = [(float(index * 6), float(index * 6 + 2)) for index in range(max(1, round(sounding_minutes * 10)))]
    return TrackActivity(ordinal=ordinal, duration_seconds=300.0, peak_dbfs=-10.0, active_ratio=active_ratio,
                         silent=silent, intervals=[] if silent else intervals)


class VoiceTrackDecisionTests(unittest.TestCase):
    def test_picks_isolated_speech_over_full_mix_containing_the_same_voice(self) -> None:
        # Shape A: Track 1 is the full mix (voice + game), Track 2 the mic.
        activities = {0: _activity(0, active_ratio=0.71), 1: _activity(1, active_ratio=0.10), 4: _activity(4, silent=True)}
        probes = {0: TrackProbe(0, confident_words=21), 1: TrackProbe(1, confident_words=15)}
        result = decide(activities, probes)
        self.assertEqual(result["status"], "selected")
        self.assertEqual(result["selected_ordinal"], 1)

    def test_microphone_on_a_different_track_is_found_per_recording(self) -> None:
        # Shape B: Track 2 is digital silence, the voice is on Track 5.
        activities = {0: _activity(0, active_ratio=0.02), 1: _activity(1, silent=True), 4: _activity(4, active_ratio=0.02)}
        probes = {0: TrackProbe(0), 4: TrackProbe(4, confident_words=14)}
        result = decide(activities, probes)
        self.assertEqual(result["status"], "selected")
        self.assertEqual(result["selected_ordinal"], 4)

    def test_music_with_lyrics_is_never_chosen_as_narration(self) -> None:
        # Shape C: microphone silent, only a music track has words.
        activities = {0: _activity(0, silent=True), 1: _activity(1, silent=True), 5: _activity(5, active_ratio=0.62)}
        probes = {5: TrackProbe(5, confident_words=120)}
        result = decide(activities, probes)
        # Never chosen. With no usual microphone track known, 120 words cannot
        # be told from someone talking over a game, so the operator is asked
        # (142) instead of being told the recording is empty.
        self.assertIsNone(result["selected_ordinal"])
        self.assertEqual(result["status"], "uncertain")
        self.assertNotIn("silent", result["explanation"].lower())

    def test_two_isolated_voices_are_uncertain_not_guessed(self) -> None:
        activities = {0: _activity(0, active_ratio=0.05), 1: _activity(1, active_ratio=0.05)}
        probes = {0: TrackProbe(0, confident_words=20), 1: TrackProbe(1, confident_words=18)}
        result = decide(activities, probes)
        self.assertEqual(result["status"], "uncertain")
        self.assertIsNone(result["selected_ordinal"])
        self.assertEqual(result["suggested_ordinal"], 0)

    def test_spotter_track_loses_to_operator_microphone(self) -> None:
        activities = {0: _activity(0, active_ratio=0.04), 1: _activity(1, active_ratio=0.04)}
        probes = {
            0: TrackProbe(0, confident_words=20, spotter_words=16),
            1: TrackProbe(1, confident_words=12, spotter_words=0),
        }
        result = decide(activities, probes)
        self.assertEqual(result["selected_ordinal"], 1)


    def test_same_microphone_on_several_tracks_is_one_voice_not_uncertain(self) -> None:
        # Shape D: OBS routes the microphone to Tracks 2, 4 and 6 at
        # different gains. They speak at the same moments, so they are one source.
        import numpy as np

        speech = np.zeros(2000, dtype=bool)
        speech[100:300] = True
        speech[900:1100] = True
        quieter = speech.copy()
        quieter[100:140] = False
        activities = {
            1: _activity(1, active_ratio=0.28),
            3: _activity(3, active_ratio=0.28),
            5: _activity(5, active_ratio=0.18),
        }
        activities[1].active_flags = speech
        activities[3].active_flags = speech.copy()
        activities[5].active_flags = quieter
        probes = {1: TrackProbe(1, confident_words=122), 3: TrackProbe(3, confident_words=122), 5: TrackProbe(5, confident_words=112)}
        result = decide(activities, probes)
        self.assertEqual(result["status"], "selected")
        self.assertEqual(result["selected_ordinal"], 1)
        self.assertIn("also on Track", result["explanation"])

    def test_usual_track_breaks_a_tie_between_different_voices(self) -> None:
        activities = {0: _activity(0, active_ratio=0.05), 1: _activity(1, active_ratio=0.05)}
        probes = {0: TrackProbe(0, confident_words=20), 1: TrackProbe(1, confident_words=18)}
        result = decide(activities, probes, preferred_ordinals=[1])
        self.assertEqual(result["status"], "selected")
        self.assertEqual(result["selected_ordinal"], 1)
        self.assertIn("usual microphone", result["explanation"])


    def test_usual_track_with_little_speech_beats_a_talkative_race_engineer(self) -> None:
        # Shape E: Track 5 is a race-engineer app reading out pit-lane
        # call-outs, Tracks 1 and 3 are mixes, and the operator said only a
        # few words on the usual Track 2 (105).
        activities = {
            0: _activity(0, active_ratio=0.0586),
            1: _activity(1, active_ratio=0.0355),
            2: _activity(2, active_ratio=0.0636),
            3: _activity(3, silent=True),
            4: _activity(4, active_ratio=0.0323),
        }
        probes = {
            0: TrackProbe(0, confident_words=63),
            1: TrackProbe(1, confident_words=14),
            2: TrackProbe(2, confident_words=68),
            4: TrackProbe(4, confident_words=113, spotter_words=10),
        }
        self.assertEqual(decide(activities, probes)["status"], "uncertain")
        result = decide(activities, probes, preferred_ordinals=[1])
        self.assertEqual(result["status"], "selected")
        self.assertEqual(result["selected_ordinal"], 1)
        self.assertIn("usual microphone", result["explanation"])

    def test_usual_track_does_not_win_when_it_only_carries_the_spotter(self) -> None:
        activities = {0: _activity(0, active_ratio=0.05), 1: _activity(1, active_ratio=0.05)}
        probes = {0: TrackProbe(0, confident_words=40), 1: TrackProbe(1, confident_words=10, spotter_words=8)}
        result = decide(activities, probes, preferred_ordinals=[1])
        self.assertEqual(result["selected_ordinal"], 0)

    def test_backend_uses_the_track_found_earlier_in_the_run_as_the_usual_track(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "Video Mangler.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("$runVoiceOrdinalCounts = @{}", script)
        self.assertIn("was your microphone earlier in this run", script)
        self.assertIn("$runVoiceOrdinalCounts[$detectedOrdinal] = 1 +", script)

    def test_crew_chief_call_outs_count_as_spotter_words(self) -> None:
        self.assertGreaterEqual(count_spotter_words("Okay, pit speed is 50 miles per hour. The exit's clear. Go, go, go."), 10)

    def test_mix_proven_to_repeat_the_microphone_is_not_a_competing_voice(self) -> None:
        # Shape D: Track 1 is a quiet game mix that also carries the mic.
        activities = {0: _activity(0, active_ratio=0.07), 1: _activity(1, active_ratio=0.28)}
        probes = {0: TrackProbe(0, confident_words=57), 1: TrackProbe(1, confident_words=122)}
        self.assertEqual(decide(activities, probes)["status"], "uncertain")
        result = decide(activities, probes, shared_speech=[(1, 0)])
        self.assertEqual(result["status"], "selected")
        self.assertEqual(result["selected_ordinal"], 1)

    def test_shares_speech_compares_what_was_said(self) -> None:
        lead = {"delta", "bar", "cycling", "widgets", "bigger", "icons"}
        self.assertTrue(shares_speech(lead, lead | {"clear", "right"}))
        self.assertFalse(shares_speech(lead, {"car", "left", "clear", "right"}))


class HonestVerdictTests(unittest.TestCase):
    """A recording full of speech is never reported as empty (142).

    The shapes are example track layouts: numbers only. In the layout used
    here, Track 1 records everything (game and voice) and Track 2 the
    microphone alone, so the voice is on two tracks in every recording.
    """

    USUAL = [1]  # Track 2

    def _talked_a_lot(self) -> tuple[dict[int, TrackActivity], dict[int, TrackProbe]]:
        # The operator talked for most of it, so the microphone track itself is
        # active two thirds of the time and the mix even more.
        activities = {
            0: _activity(0, active_ratio=0.8097),
            1: _activity(1, active_ratio=0.6657),
            2: _activity(2, active_ratio=0.4829),
            3: _activity(3, silent=True),
            4: _activity(4, silent=True),
            5: _activity(5, silent=True),
        }
        probes = {0: TrackProbe(0, confident_words=266), 1: TrackProbe(1, confident_words=394, spotter_words=2), 2: TrackProbe(2)}
        return activities, probes

    def test_hundreds_of_words_on_busy_tracks_are_put_to_the_operator_not_called_silence(self) -> None:
        activities, probes = self._talked_a_lot()
        for usual in (self.USUAL, []):
            with self.subTest(usual=usual):
                result = decide(activities, probes, preferred_ordinals=usual)
                self.assertEqual(result["status"], "uncertain")
                self.assertEqual(result["uncertain_reason"], "speech_on_busy_tracks")
                self.assertIsNone(result["selected_ordinal"])
                # Asking means asking: nothing is put forward to be picked.
                self.assertIsNone(result["suggested_ordinal"])
                self.assertEqual(result["competing_ordinals"], [1, 0])
                text = result["explanation"]
                self.assertNotIn("silent", text.lower())
                self.assertIn("Track 2 (392 clear words) and Track 1 (266)", text)
                self.assertIn("cannot tell which one is your microphone", text)
        self.assertIn("Track 2 is your usual microphone track.", decide(activities, probes, preferred_ordinals=self.USUAL)["explanation"])

    def test_speech_on_the_usual_microphone_track_is_always_put_to_the_operator(self) -> None:
        # One voice on two identical busy tracks, a game track with no words.
        activities = {0: _activity(0, active_ratio=0.67), 1: _activity(1, active_ratio=0.67), 5: _activity(5, active_ratio=0.66)}
        probes = {0: TrackProbe(0, confident_words=67), 1: TrackProbe(1, confident_words=67), 5: TrackProbe(5)}
        result = decide(activities, probes, preferred_ordinals=self.USUAL)
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(sorted(result["competing_ordinals"]), [0, 1])
        self.assertIn("Track 2 is your usual microphone track.", result["explanation"])

    def test_a_little_game_speech_while_the_microphone_says_nothing_is_no_narration_said_plainly(self) -> None:
        # Tracks 1 and 3 carry the same game audio, with a few words of it; the
        # microphone track has sound (breathing, the room) but no words.
        activities = {0: _activity(0, active_ratio=0.81), 1: _activity(1, active_ratio=0.21), 2: _activity(2, active_ratio=0.83)}
        probes = {0: TrackProbe(0, confident_words=43), 1: TrackProbe(1), 2: TrackProbe(2, confident_words=43)}
        result = decide(activities, probes, preferred_ordinals=self.USUAL)
        self.assertEqual(result["status"], "no_narration_found")
        text = result["explanation"]
        self.assertIn("Your usual microphone track, Track 2, has sound but no clear speech.", text)
        self.assertIn("Track 1 (43 words), Track 3 (43 words)", text)
        # It is not silent, so it is not called silent.
        self.assertNotIn("silent", text.lower())
        # With no usual track known, those words could be anyone's: ask.
        self.assertEqual(decide(activities, probes)["status"], "uncertain")

    def test_the_microphone_is_called_silent_only_when_it_is(self) -> None:
        activities = {
            0: _activity(0, active_ratio=0.58),
            1: _activity(1, silent=True),
            2: _activity(2, active_ratio=0.58),
            5: _activity(5, active_ratio=0.55),
        }
        probes = {0: TrackProbe(0, confident_words=6), 2: TrackProbe(2, confident_words=6), 5: TrackProbe(5, confident_words=18)}
        result = decide(activities, probes, preferred_ordinals=self.USUAL)
        self.assertEqual(result["status"], "no_narration_found")
        self.assertIn("Your usual microphone track, Track 2, is silent.", result["explanation"])
        self.assertIn("Track 6 (18 words)", result["explanation"])

    def test_talking_amounts_of_speech_are_put_to_the_operator_even_off_the_usual_track(self) -> None:
        # The voice can move to another track (94). Two minutes of sample with
        # this many words is someone talking, not a line of game radio.
        activities = {0: _activity(0, active_ratio=0.02), 1: _activity(1, silent=True), 5: _activity(5, active_ratio=0.6)}
        probes = {0: TrackProbe(0, confident_words=2), 5: TrackProbe(5, confident_words=150)}
        result = decide(activities, probes, preferred_ordinals=self.USUAL)
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(result["competing_ordinals"], [5])
        self.assertIn("Track 6 carries speech (150 clear words)", result["explanation"])
        self.assertIn("cannot tell whether it is your microphone", result["explanation"])

    def test_a_full_mix_carrying_the_spotter_and_the_operator_is_not_called_empty(self) -> None:
        # 300 clear words, 130 of them spotter call-outs: 170 are someone else's.
        activities = {0: _activity(0, active_ratio=0.8), 1: _activity(1, silent=True)}
        probes = {0: TrackProbe(0, confident_words=300, spotter_words=130)}
        for usual in (self.USUAL, []):
            with self.subTest(usual=usual):
                result = decide(activities, probes, preferred_ordinals=usual)
                self.assertEqual(result["status"], "uncertain")
                self.assertNotIn("No audio track carries clear speech", result["explanation"])
        # The count shown is what the choice is made on: words besides the
        # call-outs. 1000 words that are nearly all call-outs are "a little".
        activities = {0: _activity(0, active_ratio=0.8), 1: _activity(1, silent=True)}
        probes = {0: TrackProbe(0, confident_words=1000, spotter_words=910)}
        result = decide(activities, probes, preferred_ordinals=self.USUAL)
        self.assertEqual(result["status"], "no_narration_found")
        self.assertIn("Track 1 (90 words)", result["explanation"])
        # A usual track that is only call-outs is described as that.
        activities = {0: _activity(0, active_ratio=0.8), 1: _activity(1, active_ratio=0.1)}
        probes = {0: TrackProbe(0, confident_words=20), 1: TrackProbe(1, confident_words=6, spotter_words=6)}
        result = decide(activities, probes, preferred_ordinals=self.USUAL)
        self.assertEqual(result["status"], "no_narration_found")
        self.assertIn("Track 2, carries only spotter call-outs.", result["explanation"])

    def test_a_usual_track_the_recording_does_not_have_is_no_usual_track(self) -> None:
        # The remembered microphone is Track 3; this recording has two tracks.
        activities = {0: _activity(0, active_ratio=0.8), 1: _activity(1, silent=True)}
        probes = {0: TrackProbe(0, confident_words=80)}
        result = decide(activities, probes, preferred_ordinals=[2])
        self.assertEqual(result["status"], "uncertain")
        self.assertNotIn("usual microphone", result["explanation"])

    def test_a_quiet_track_is_not_called_busy_when_the_rule_passes_it_over(self) -> None:
        # The top score went to a 2-word track, which is too little to choose. The 5-word track is
        # quiet between phrases, so it is not "busy", and since the Wave 1 rule (196) a track with too few words
        # no longer stands in its way: it is the only track with speech of its own, and is chosen.
        activities = {0: _activity(0, active_ratio=0.01), 2: _activity(2, active_ratio=0.45)}
        probes = {0: TrackProbe(0, confident_words=2), 2: TrackProbe(2, confident_words=5)}
        result = decide(activities, probes)
        self.assertEqual((result["status"], result["selected_ordinal"]), ("selected", 2))
        self.assertNotIn("busy", result["explanation"])
        self.assertIn("Track 3 carries your narration (5 confident spoken words, quiet between phrases)",
                      result["explanation"])

    def test_no_speech_on_any_track_is_no_narration(self) -> None:
        activities = {0: _activity(0, active_ratio=0.3), 1: _activity(1, active_ratio=0.17), 5: _activity(5, active_ratio=0.44)}
        probes = {0: TrackProbe(0), 1: TrackProbe(1), 5: TrackProbe(5)}
        for usual in (self.USUAL, []):
            with self.subTest(usual=usual):
                result = decide(activities, probes, preferred_ordinals=usual)
                self.assertEqual(result["status"], "no_narration_found")
                self.assertIn("No audio track carries clear speech", result["explanation"])

    def test_detection_asks_once_and_spends_no_extra_listening_on_a_question_it_cannot_settle(self) -> None:
        """Through detect_voice_track itself, with real WAV analysis.

        Only the decoding of the recording and Whisper are stood in for: the
        tracks are written as WAVs, and the transcriber answers by file.
        """

        from unittest import mock

        from media_manglers.core import voice_track

        # A tone that is on 80% and 67% of the time: both tracks busy.
        seconds = 20.0
        busy_mix = [(start, start + 0.8) for start in range(20)]
        busy_mic = [(start, start + 0.67) for start in range(20)]
        # Nine-word sentences: a short phrase said back to back is a loop Whisper invents (199).
        words = {0: " ".join(["game"] * 3 + ["and", "voice", "are", "mixed", "together", "with", "the", "engine", "here"] * 13),
                 1: " ".join(["the", "delta", "bar", "keeps", "jumping", "around", "in", "the", "corner"] * 20)}
        heard: list[str] = []

        def transcriber(path: Path) -> list[dict[str, object]]:
            heard.append(path.name)
            ordinal = int(path.stem.split("-")[-1])
            return [{"text": words.get(ordinal, ""), "no_speech_prob": 0.05, "avg_logprob": -0.3}]

        def extract(_ffmpeg: str, _source: Path, count: int, work_dir: Path, **_kwargs: object) -> dict[int, Path]:
            work_dir.mkdir(parents=True, exist_ok=True)
            outputs = {}
            for ordinal, pattern in enumerate((busy_mix, busy_mic, [])[:count]):
                outputs[ordinal] = work_dir / f"track-{ordinal}.wav"
                _write_wav(outputs[ordinal], pattern, seconds=seconds)
            return outputs

        streams = [{"tags": {"title": f"Track{n}"}} for n in (1, 2, 3)]
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(
            voice_track, "probe_audio_streams", return_value=(streams, seconds)
        ), mock.patch.object(voice_track, "extract_all_tracks", side_effect=extract):
            result = voice_track.detect_voice_track(
                Path(temp_dir) / "synthetic-session.mkv",
                work_dir=Path(temp_dir),
                transcriber=transcriber,
                preferred_ordinals=[1],
            )
        self.assertEqual(result["status"], "uncertain")
        # The busy usual Track 2 falls to silence between phrases like a microphone, so it is a
        # second voice against the busy Track 1 (142(b)): still a question, never a guess.
        self.assertEqual(result["uncertain_reason"], "busy_voice")
        self.assertIsNone(result["selected_ordinal"])
        self.assertNotIn("silent", result["explanation"].lower())
        # One sample per audible track, and one comparison of the two voices: a second voice that
        # turns out to be the same speech could settle it (196). Nothing is listened to twice.
        self.assertEqual(sorted(heard), ["cross-1-0.wav", "cross-1-1.wav", "probe-0.wav", "probe-1.wav"])


class VoiceTrackSignalTests(unittest.TestCase):
    def test_confident_speech_ignores_whisper_filler_and_low_confidence(self) -> None:
        segments = [
            {"text": "Thank you.", "no_speech_prob": 0.8, "avg_logprob": -0.3},
            {"text": "you", "no_speech_prob": 0.7, "avg_logprob": -0.7},
            {"text": "The delta bar is not cycling.", "no_speech_prob": 0.05, "avg_logprob": -0.3},
            {"text": "mumble words here", "no_speech_prob": 0.1, "avg_logprob": -1.4},
        ]
        words, spotter, sample = confident_speech(segments)
        self.assertEqual(words, 6)
        self.assertEqual(spotter, 0)
        self.assertIn("delta bar", sample)

    def test_spotter_phrases_are_counted(self) -> None:
        self.assertEqual(count_spotter_words("Car left. Clear left. Green flag, green flag."), 8)
        self.assertEqual(count_spotter_words("The fuel widget is too small"), 0)

    def test_silent_track_and_bursty_track_are_told_apart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            silent = root / "silent.wav"
            bursty = root / "bursty.wav"
            _write_wav(silent, [], seconds=6.0)
            _write_wav(bursty, [(1.0, 2.0), (4.0, 4.8)], seconds=6.0)
            silent_activity = analyze_track_wav(silent, 0)
            bursty_activity = analyze_track_wav(bursty, 1)
            windows = choose_probe_windows(bursty_activity)
            probe = root / "probe.wav"
            seconds = write_probe_wav(bursty, windows, probe)
        self.assertTrue(silent_activity.silent)
        self.assertEqual(choose_probe_windows(silent_activity), [])
        self.assertFalse(bursty_activity.silent)
        self.assertLess(bursty_activity.active_ratio, 0.5)
        self.assertEqual(len(bursty_activity.intervals), 2)
        self.assertGreater(seconds, 1.5)

    def test_probe_windows_are_spread_over_a_long_recording(self) -> None:
        intervals = [(float(minute * 60), float(minute * 60 + 5)) for minute in range(120)]
        activity = TrackActivity(ordinal=1, duration_seconds=7200.0, peak_dbfs=-10.0, active_ratio=0.01, silent=False, intervals=intervals)
        windows = choose_probe_windows(activity, max_seconds=60.0)
        self.assertLessEqual(sum(end - start for start, end in windows), 80.0)
        self.assertLess(windows[0][0], 600.0)
        self.assertGreater(windows[-1][0], 6000.0)


class DecodeProgressTests(unittest.TestCase):
    """145: a decode is stopped only when it stops moving, never for taking long."""

    SLOW = (
        "import sys, time\n"
        "for step in range(1, 13):\n"
        "    time.sleep(0.3)\n"
        "    print(f'out_time_us={step * 1000000}', flush=True)\n"
        "print('progress=end', flush=True)\n"
    )
    STALLED = (
        "import sys, time\n"
        "print('out_time_us=65000000', flush=True)\n"
        "time.sleep(60)\n"
    )
    # What FFmpeg 8.1 really does when its input stops: it keeps printing the
    # same position and progress=continue twice a second.
    REPORTING_BUT_STUCK = (
        "import sys, time\n"
        "print('out_time_us=65000000', flush=True)\n"
        "for _ in range(150):\n"
        "    time.sleep(0.2)\n"
        "    print('out_time_us=65000000', flush=True)\n"
        "    print('progress=continue', flush=True)\n"
    )

    def test_a_slow_decode_that_keeps_moving_is_not_stopped(self) -> None:
        # 3.6 s in all, three times longer than the stall period, but it never pauses for long.
        with tempfile.TemporaryDirectory() as temp:
            code, reached = run_while_progressing([sys.executable, "-c", self.SLOW], stall_seconds=1.2,
                                                  stderr_path=Path(temp) / "errors.txt")
        self.assertEqual(code, 0)
        self.assertEqual(reached, 12.0)

    def test_a_decode_that_stops_moving_is_stopped_with_a_plain_reason(self) -> None:
        started = time.monotonic()
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(RuntimeError) as caught:
            run_while_progressing([sys.executable, "-c", self.STALLED], stall_seconds=1.0,
                                  stderr_path=Path(temp) / "errors.txt")
        self.assertLess(time.monotonic() - started, 15, "stopped soon after it stalled, not after its 60 s sleep")
        message = str(caught.exception)
        self.assertIn("stopped making progress", message)
        self.assertIn("01:05 into the recording", message)

    def test_a_decode_that_keeps_reporting_but_does_not_move_is_stopped(self) -> None:
        started = time.monotonic()
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(RuntimeError) as caught:
            run_while_progressing([sys.executable, "-c", self.REPORTING_BUT_STUCK], stall_seconds=1.0,
                                  stderr_path=Path(temp) / "errors.txt")
        self.assertLess(time.monotonic() - started, 15, "progress=continue on the same position is not movement")
        self.assertIn("01:05 into the recording", str(caught.exception))

    def test_decode_progress_is_reported_only_when_it_moves(self) -> None:
        moving: list[float] = []
        stuck: list[float] = []
        with tempfile.TemporaryDirectory() as temp:
            run_while_progressing([sys.executable, "-c", self.SLOW], stall_seconds=1.2,
                                  stderr_path=Path(temp) / "errors.txt", on_progress=moving.append)
            with self.assertRaises(RuntimeError):
                run_while_progressing([sys.executable, "-c", self.REPORTING_BUT_STUCK], stall_seconds=1.0,
                                      stderr_path=Path(temp) / "errors-2.txt", on_progress=stuck.append)
        self.assertEqual(moving, [float(step) for step in range(1, 13)])
        self.assertEqual(stuck, [65.0])

    def test_time_the_whole_tool_was_suspended_is_not_a_stall(self) -> None:
        # The clock jumps 30 s once, as it does for a process that Pause
        # suspended: the decode had not stalled, it was not running. The jump
        # is made on a look by the loop that decides, never by the thread that
        # reads FFmpeg's output: a jump there moves "last progress" along with
        # it, and the gap would never be seen.
        offset = [0.0]
        calls = [0]
        loop_thread = threading.get_ident()

        def clock() -> float:
            if threading.get_ident() == loop_thread:
                calls[0] += 1
                if calls[0] == 6:
                    offset[0] += 30.0
            return time.monotonic() + offset[0]

        with tempfile.TemporaryDirectory() as temp:
            code, reached = run_while_progressing([sys.executable, "-c", self.SLOW], stall_seconds=1.2,
                                                  stderr_path=Path(temp) / "errors.txt", clock=clock)
        self.assertGreater(calls[0], 6)
        self.assertEqual(code, 0)
        self.assertEqual(reached, 12.0)

    @unittest.skipUnless(sys.platform == "win32", "Pause suspends processes on Windows")
    def test_a_long_pause_is_not_called_a_stall(self) -> None:
        """Pause the decode the way the Workbench does: the helper and its FFmpeg together.

        The real ``Set-MMProcessTreeSuspended`` from the backend suspends the
        whole tree for 7 s; the decode is stalled after 2 s without progress.
        """

        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            started_marker = root / "fake-started.txt"
            pid_file = root / "pid.txt"
            ready_marker = root / "suspender-ready.txt"
            fake = (
                "import sys, time\n"
                f"open({str(started_marker)!r}, 'w').close()\n"
                "for step in range(1, 41):\n"
                "    time.sleep(0.5)\n"
                "    print(f'out_time_us={step * 1000000}', flush=True)\n"
                "print('progress=end', flush=True)\n"
            )
            helper = root / "helper.py"
            helper.write_text(
                "import sys\n"
                f"sys.path.insert(0, {str(repo / 'src')!r})\n"
                "from pathlib import Path\n"
                "from media_manglers.core.voice_track import run_while_progressing\n"
                "try:\n"
                f"    code, reached = run_while_progressing([sys.executable, '-c', {fake!r}], stall_seconds=2.0,\n"
                f"                                          stderr_path=Path({str(root / 'errors.txt')!r}))\n"
                "    print(f'exit {code} reached {reached}', flush=True)\n"
                "except RuntimeError as exc:\n"
                "    print(f'stopped: {exc}', flush=True)\n",
                encoding="utf-8",
            )
            suspender = root / "suspend.ps1"
            suspender.write_text(
                "$ErrorActionPreference = 'Stop'\n"
                "$tokens = $null; $parseErrors = $null\n"
                f"$ast = [System.Management.Automation.Language.Parser]::ParseFile('{repo / 'Video Mangler.ps1'}', [ref]$tokens, [ref]$parseErrors)\n"
                "$wanted = @('Get-MMProcessTreeIds', 'Set-MMProcessTreeSuspended')\n"
                "foreach ($node in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $wanted -contains $n.Name }, $true)) {\n"
                "    Invoke-Expression $node.Extent.Text\n"
                "}\n"
                f"New-Item -ItemType File -Path '{ready_marker}' | Out-Null\n"
                f"while (-not (Test-Path -LiteralPath '{pid_file}')) {{ Start-Sleep -Milliseconds 100 }}\n"
                f"$process = [System.Diagnostics.Process]::GetProcessById([int](Get-Content -LiteralPath '{pid_file}'))\n"
                "$ids = @(Get-MMProcessTreeIds -RootId $process.Id)\n"
                "Set-MMProcessTreeSuspended -Process $process -Suspended $true\n"
                "Start-Sleep -Seconds 7\n"
                "Set-MMProcessTreeSuspended -Process $process -Suspended $false\n"
                "Write-Output $ids.Count\n",
                encoding="utf-8",
            )
            pauser = subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(suspender)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            deadline = time.monotonic() + 60
            while not ready_marker.exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertTrue(ready_marker.exists(), "the backend's suspend function loaded")
            decode = subprocess.Popen([sys.executable, "-I", str(helper)], stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True)
            while not started_marker.exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            time.sleep(1.0)
            pid_file.write_text(str(decode.pid), encoding="ascii")
            pause_out, pause_err = pauser.communicate(timeout=60)
            decode_out, decode_err = decode.communicate(timeout=60)
        self.assertEqual(pauser.returncode, 0, pause_err)
        self.assertGreaterEqual(int(pause_out.strip().splitlines()[-1]), 2, "the helper and its FFmpeg were both paused")
        self.assertEqual(decode_out.strip(), "exit 0 reached 40.0", decode_err)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required")
    def test_every_track_is_still_decoded_with_progress_on(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "two-tracks.mkv"
            subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-v", "error", "-y",
                            "-f", "lavfi", "-i", "sine=frequency=300:duration=3",
                            "-f", "lavfi", "-i", "anoisesrc=duration=3",
                            "-map", "0:a", "-map", "1:a", "-c:a", "flac", str(source)], check=True)
            wavs = extract_all_tracks(shutil.which("ffmpeg"), source, 2, root / "work", duration_seconds=3.0)
            for ordinal, path in wavs.items():
                with wave.open(str(path), "rb") as audio:
                    self.assertAlmostEqual(audio.getnframes() / audio.getframerate(), 3.0, delta=0.1, msg=ordinal)
            self.assertFalse((root / "work" / "decode-errors.txt").exists())


class DetectionProgressTests(unittest.TestCase):
    """The backend's stall watchdog sees the detector working, step by step."""

    @staticmethod
    def _two_bursty_tracks(path: Path) -> None:
        # Two different half-second tones, on at different moments: both audible, neither continuous.
        subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-v", "error", "-y",
                        "-f", "lavfi", "-i", "aevalsrc=exprs='if(lt(mod(t\\,2)\\,0.5)\\,0.5*sin(2*PI*300*t)\\,0)':d=8:s=16000",
                        "-f", "lavfi", "-i", "aevalsrc=exprs='if(between(mod(t\\,2)\\,1\\,1.5)\\,0.5*sin(2*PI*500*t)\\,0)':d=8:s=16000",
                        "-map", "0:a", "-map", "1:a", "-c:a", "flac", str(path)], check=True)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
    def test_detection_writes_plain_progress_while_it_works(self) -> None:
        import json
        from unittest import mock

        from media_manglers.core import voice_track

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "two-tracks.mkv"
            self._two_bursty_tracks(source)
            state_path = root / "progress.json"
            seen: list[dict[str, object]] = []

            def transcriber(_path: Path) -> list[dict[str, object]]:
                seen.append(json.loads(state_path.read_text(encoding="utf-8")))
                return []

            with mock.patch.object(voice_track, "whisper_transcriber", return_value=transcriber):
                result = voice_track.detect_from_request({
                    "source_path": str(source),
                    "ffmpeg_exe": shutil.which("ffmpeg"),
                    "ffprobe_exe": shutil.which("ffprobe"),
                    "work_dir": str(root / "work"),
                    "progress_state_file_path": str(state_path),
                })
            final = json.loads(state_path.read_text(encoding="utf-8"))
            leftovers = sorted(path.name for path in root.iterdir())
        self.assertEqual(result["audio_track_count"], 2)
        self.assertEqual([state["message"] for state in seen], [
            "Finding your voice: listening to Track 1 (1 of 2)",
            "Finding your voice: listening to Track 2 (2 of 2)",
        ])
        for state in [*seen, final]:
            self.assertEqual(set(state), {"message", "elapsed_seconds", "updated_at_utc"}, state)
            self.assertTrue(str(state["updated_at_utc"]).endswith("Z"), state)
        self.assertEqual(final["message"], "Finding your voice: done")
        self.assertNotIn("progress.json.tmp", leftovers)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
    def test_decode_position_is_reported_while_the_tracks_are_read(self) -> None:
        from unittest import mock

        from media_manglers.core import voice_track

        messages: list[str] = []
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "two-tracks.mkv"
            self._two_bursty_tracks(source)
            with mock.patch.object(voice_track, "whisper_transcriber", return_value=lambda _path: []):
                voice_track.detect_voice_track(source, ffmpeg_exe=shutil.which("ffmpeg"),
                                               ffprobe_exe=shutil.which("ffprobe"), work_dir=root / "work",
                                               progress=messages.append)
        self.assertEqual(messages[0], "Finding your voice: looking at the audio tracks")
        self.assertTrue(any(message.startswith("Finding your voice: reading the audio, ") and message.endswith(" of 00:08")
                            for message in messages), messages)
        self.assertIn("Finding your voice: measuring Track 1 of 2", messages)
        self.assertIn("Finding your voice: measuring Track 2 of 2", messages)
        self.assertIn("Finding your voice: loading the speech model", messages)

    def test_every_step_is_named_and_none_reads_as_a_transcription_result(self) -> None:
        """Through detect_voice_track, with real WAV analysis and the cross-check.

        The Workbench changes a recording's row when the activity starts with
        "Transcription" (completed, failed, ...); detection messages travel as
        that activity, so none of them may start that way.
        """

        from unittest import mock

        from media_manglers.core import voice_track

        seconds = 20.0
        first = [(float(start), start + 0.5) for start in range(0, 20, 2)]
        second = [(start + 1.0, start + 1.5) for start in range(0, 20, 2)]
        # Ten-word sentences: a short phrase said back to back is a loop Whisper invents (199).
        words = {0: " ".join(["the", "delta", "bar", "keeps", "jumping", "around", "in", "the", "corner", "again"] * 10),
                 1: " ".join(["what", "a", "lovely", "evening", "outside", "with", "the", "sun", "going", "down"] * 10)}

        def transcriber(path: Path) -> list[dict[str, object]]:
            return [{"text": words[int(path.stem.split("-")[-1])], "no_speech_prob": 0.05, "avg_logprob": -0.3}]

        def extract(_ffmpeg: str, _source: Path, count: int, work_dir: Path, **_kwargs: object) -> dict[int, Path]:
            work_dir.mkdir(parents=True, exist_ok=True)
            outputs = {}
            for ordinal, pattern in enumerate((first, second)[:count]):
                outputs[ordinal] = work_dir / f"track-{ordinal}.wav"
                _write_wav(outputs[ordinal], pattern, seconds=seconds)
            return outputs

        messages: list[str] = []
        streams = [{"tags": {"title": f"Track{n}"}} for n in (1, 2)]
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(
            voice_track, "probe_audio_streams", return_value=(streams, seconds)
        ), mock.patch.object(voice_track, "extract_all_tracks", side_effect=extract), mock.patch.object(
            voice_track, "whisper_transcriber", return_value=transcriber
        ):
            result = voice_track.detect_voice_track(Path(temp_dir) / "synthetic-session.mkv",
                                                    work_dir=Path(temp_dir), progress=messages.append)
        self.assertEqual(result.get("uncertain_reason"), "competing_voices", result)
        lead = int(result["suggested_ordinal"]) + 1
        self.assertEqual(messages, [
            "Finding your voice: looking at the audio tracks",
            "Finding your voice: measuring Track 1 of 2",
            "Finding your voice: measuring Track 2 of 2",
            "Finding your voice: loading the speech model",
            "Finding your voice: listening to Track 1 (1 of 2)",
            "Finding your voice: listening to Track 2 (2 of 2)",
            f"Finding your voice: checking Track {lead}'s speech against the other tracks",
            f"Finding your voice: checking whether Track {lead} and Track {3 - lead} carry the same voice",
            "Finding your voice: done",
        ])
        for message in messages:
            self.assertFalse(message.lower().startswith("transcription"), message)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class VoiceWavReuseTests(unittest.TestCase):
    """196: the chosen track's decoded audio is kept, so the recording is read once, not twice.

    Real FFmpeg, real probing and decoding of a synthetic recording; only Whisper is stood in for.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = tempfile.TemporaryDirectory()
        cls.recording = _three_track_recording(Path(cls._temp.name) / "synthetic-session.mkv")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temp.cleanup()

    def _detect(self, words: dict[int, str], **kwargs: object) -> dict[str, object]:
        from media_manglers.core import voice_track

        return voice_track.detect_voice_track(self.recording, ffmpeg_exe=shutil.which("ffmpeg"),
                                              ffprobe_exe=shutil.which("ffprobe"),
                                              transcriber=_transcriber_hearing(words), **kwargs)

    def test_the_chosen_tracks_decoded_audio_is_kept_for_transcription(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            messages: list[str] = []
            result = self._detect({1: NARRATION_WORDS}, work_dir=root / "work",
                                  keep_wavs_dir=root / "keep", progress=messages.append)
            self.assertEqual((result["status"], result["selected_ordinal"]), ("selected", 1), result)
            kept = result["kept_track_wavs"]
            self.assertEqual([(item["ordinal"], item["track_number"]) for item in kept], [(1, 2)])
            kept_path = Path(kept[0]["path"])
            self.assertEqual(kept_path, root / "keep" / "track-1.wav")
            self.assertEqual((kept[0]["sample_rate_hz"], kept[0]["channels"]), (16000, 1))
            self.assertAlmostEqual(kept[0]["seconds"], 20.0, delta=0.1)
            with wave.open(str(kept_path), "rb") as audio:
                self.assertEqual((audio.getframerate(), audio.getnchannels(), audio.getsampwidth()), (16000, 1, 2))
                kept_frames = audio.readframes(audio.getnframes())
            # The same samples the backend's own extraction makes, with its exact arguments
            # (Export-TranscriptSourceWav), so Whisper hears exactly what it heard before.
            extracted = root / "extracted.wav"
            subprocess.run([shutil.which("ffmpeg"), "-y", "-i", str(self.recording), "-map", "0:a:1", "-vn",
                            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(extracted)],
                           check=True, capture_output=True)
            with wave.open(str(extracted), "rb") as audio:
                self.assertEqual(kept_frames, audio.readframes(audio.getnframes()))
            # Only the kept track is left; the rest of the decode is gone with the scratch folder.
            self.assertEqual(sorted(path.name for path in (root / "keep").iterdir()), ["track-1.wav"])
            self.assertFalse((root / "work" / "voice-track-probe").exists())
        # Moving the audio can take a while across drives; the backend's watchdog is told first.
        self.assertIn("Finding your voice: keeping the decoded audio for the narration", messages)
        self.assertLess(messages.index("Finding your voice: keeping the decoded audio for the narration"),
                        messages.index("Finding your voice: done"))

    def test_the_remembered_track_is_kept_too_when_detection_asks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # Speech only on the busy Track 1, while the usual microphone track (Track 3) is silent:
            # the operator is asked, and the usual track's audio is kept for the answer.
            # (A busy usual track whose level falls to silence between phrases is now chosen
            # outright as a microphone, 142(b), so it no longer makes the app ask.)
            result = self._detect({0: NARRATION_WORDS}, work_dir=root / "work",
                                  keep_wavs_dir=root / "keep", preferred_ordinals=[2])
            self.assertEqual(result["status"], "uncertain", result)
            self.assertIsNone(result["selected_ordinal"])
            kept = result["kept_track_wavs"]
            self.assertEqual([item["ordinal"] for item in kept], [2])
            self.assertTrue(Path(kept[0]["path"]).is_file())
            self.assertEqual(sorted(path.name for path in (root / "keep").iterdir()), ["track-2.wav"])

    def test_nothing_is_kept_when_there_is_no_narration_or_no_one_asked(self) -> None:
        from media_manglers.core import voice_track

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self._detect({}, work_dir=root / "work", keep_wavs_dir=root / "keep")
            self.assertEqual(result["status"], "no_narration_found", result)
            self.assertEqual(result["kept_track_wavs"], [])
            self.assertEqual(list((root / "keep").glob("*.wav")) if (root / "keep").exists() else [], [])

            # Without a keep folder, a track that was chosen is not kept, and the detector's own
            # scratch folder is still removed.
            owned = root / "owned-scratch"

            def own_scratch(*_args: object, **_kwargs: object) -> str:
                owned.mkdir()
                return str(owned)

            with mock.patch.object(voice_track.tempfile, "mkdtemp", side_effect=own_scratch):
                result = self._detect({1: NARRATION_WORDS})
            self.assertEqual((result["status"], result["selected_ordinal"]), ("selected", 1), result)
            self.assertEqual(result["kept_track_wavs"], [])
            self.assertFalse(owned.exists())

    def test_the_request_passes_the_keep_folder_through(self) -> None:
        from media_manglers.core import voice_track

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with mock.patch.object(voice_track, "whisper_transcriber",
                                   return_value=_transcriber_hearing({1: NARRATION_WORDS})):
                result = voice_track.detect_from_request({
                    "source_path": str(self.recording),
                    "ffmpeg_exe": shutil.which("ffmpeg"),
                    "ffprobe_exe": shutil.which("ffprobe"),
                    "work_dir": str(root / "work"),
                    "keep_wavs_dir": str(root / "keep"),
                })
            self.assertEqual(result["selected_ordinal"], 1, result)
            self.assertEqual([item["ordinal"] for item in result["kept_track_wavs"]], [1])
            self.assertTrue((root / "keep" / "track-1.wav").is_file())


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class RuleVersionTests(unittest.TestCase):
    """196: every result names the selection rule that made it, so a saved one from another rule is not trusted."""

    def test_every_result_names_the_rule_that_made_it(self) -> None:
        from media_manglers.core import voice_track

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            recording = _three_track_recording(root / "synthetic-session.mkv")
            silent = root / "no-audio.mkv"
            subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-v", "error", "-y",
                            "-f", "lavfi", "-i", "testsrc=size=64x48:rate=5:duration=2",
                            "-c:v", "ffv1", str(silent)], check=True)
            results = {
                "selected": voice_track.detect_voice_track(recording, ffmpeg_exe=shutil.which("ffmpeg"),
                                                           ffprobe_exe=shutil.which("ffprobe"),
                                                           transcriber=_transcriber_hearing({1: NARRATION_WORDS})),
                "no_narration_found": voice_track.detect_voice_track(recording, ffmpeg_exe=shutil.which("ffmpeg"),
                                                                     ffprobe_exe=shutil.which("ffprobe"),
                                                                     transcriber=_transcriber_hearing({})),
                "no_audio": voice_track.detect_voice_track(silent, ffmpeg_exe=shutil.which("ffmpeg"),
                                                           ffprobe_exe=shutil.which("ffprobe")),
            }
        for status, result in results.items():
            self.assertEqual(result["status"], status, result)
            self.assertEqual(result["rule_version"], voice_track.VOICE_RULE_VERSION, status)
        self.assertIsInstance(voice_track.VOICE_RULE_VERSION, int)


def _measured(ordinal: int, *, active: float = 0.0, loud: float | None = None, swing: float | None = None,
              bursts_per_minute: float = 0.0, seconds: float = 1800.0) -> TrackActivity:
    """A track as analyze_track_wav measures it: share of time with sound, share of loud frames,
    level swing inside sounding stretches and separate sound bursts per minute of sound."""

    sounding_minutes = active * seconds / 60.0
    bursts = round(bursts_per_minute * sounding_minutes)
    activity = TrackActivity(ordinal=ordinal, duration_seconds=seconds, peak_dbfs=-120.0 if not active else -10.0,
                             active_ratio=active, silent=not active,
                             intervals=[(float(index), float(index) + 0.5) for index in range(bursts)])
    activity.level_swing_db = swing
    activity.loud_share = loud
    return activity


class WaveOneTrackRuleTests(unittest.TestCase):
    """196: 142(b) and 144 together, on measured track shapes."""

    def test_a_loud_track_that_never_goes_quiet_is_not_taken_for_the_microphone(self) -> None:
        # Shape F (144): Track 6 is music at -50 dBFS or louder 99% of the time, but so
        # steady that only 3% of its frames rise above its own floor, and its lyrics give 112 words.
        # The quiet microphone on Track 2 says less. With no usual track known, today picks Track 6.
        activities = {
            0: _measured(0, active=0.667, loud=0.667, swing=3.9, bursts_per_minute=3.5),
            1: _measured(1, active=0.157, loud=0.158, swing=4.6, bursts_per_minute=35.1),
            2: _measured(2, active=0.653, loud=0.653, swing=3.8, bursts_per_minute=3.0),
            3: _measured(3), 4: _measured(4),
            5: _measured(5, active=0.03, loud=0.99, swing=None, bursts_per_minute=94.9),
        }
        probes = {0: TrackProbe(0, confident_words=10), 1: TrackProbe(1, confident_words=6),
                  2: TrackProbe(2, confident_words=28, spotter_words=4), 5: TrackProbe(5, confident_words=112)}
        result = decide(activities, probes)
        self.assertEqual((result["status"], result.get("selected_ordinal")), ("selected", 1), result["explanation"])

    def test_a_busy_usual_microphone_that_falls_silent_between_phrases_is_chosen(self) -> None:
        # Shape G (142 part b): the usual Track 2 has sound 67% of the time, so it counts
        # as busy, but its level swings 44 dB inside those stretches, as a microphone does, and it
        # holds 392 words of its own. Track 1 is the busy full mix, and the cross-check proves it
        # repeats Track 2's words. Today the app still asks.
        activities = {
            0: _measured(0, active=0.81, loud=0.812, swing=15.7, bursts_per_minute=8.4, seconds=651.0),
            1: _measured(1, active=0.666, loud=0.666, swing=43.9, bursts_per_minute=16.3, seconds=651.0),
            2: _measured(2, active=0.483, loud=0.483, swing=3.4, bursts_per_minute=0.8, seconds=651.0),
            3: _measured(3, seconds=651.0), 4: _measured(4, seconds=651.0), 5: _measured(5, seconds=651.0),
        }
        probes = {0: TrackProbe(0, confident_words=266), 1: TrackProbe(1, confident_words=394, spotter_words=2)}
        result = decide(activities, probes, preferred_ordinals=[1], shared_speech=[(1, 0)])
        self.assertEqual((result["status"], result.get("selected_ordinal")), ("selected", 1), result["explanation"])

    def test_sound_that_does_not_come_in_phrases_is_a_bed_not_a_microphone(self) -> None:
        # 144: under half the time with sound and not loud, but only one long burst a minute.
        activities = {
            1: _measured(1, active=0.2, loud=0.2, swing=6.0, bursts_per_minute=1.0),
            2: _measured(2, active=0.1, loud=0.1, swing=30.0, bursts_per_minute=20.0),
        }
        probes = {1: TrackProbe(1, confident_words=80), 2: TrackProbe(2, confident_words=40)}
        result = decide(activities, probes)
        self.assertEqual((result["status"], result.get("selected_ordinal")), ("selected", 2), result["explanation"])

    def test_a_microphone_with_a_noisy_floor_is_not_thrown_out_as_loud(self) -> None:
        # The loud test spares a track whose level still swings 15 dB or more: a microphone whose
        # floor sits near -50 dBFS is loud most of the time, yet falls far between phrases.
        activities = {
            1: _measured(1, active=0.3, loud=0.8, swing=22.0, bursts_per_minute=20.0),
            2: _measured(2, active=0.653, loud=0.653, swing=3.8, bursts_per_minute=3.0),
        }
        probes = {1: TrackProbe(1, confident_words=60), 2: TrackProbe(2, confident_words=28)}
        result = decide(activities, probes)
        self.assertEqual((result["status"], result.get("selected_ordinal")), ("selected", 1), result["explanation"])


def _pcm(map_spec: str, target: Path) -> list[str]:
    return ["-map", map_spec, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(target)]


class DecodeOptionsTests(unittest.TestCase):
    """226: the one decoder takes options before its input and outputs after the tracks, so a
    feature can read the picture in the same pass. Without them the command is what it was."""

    @staticmethod
    def _capture() -> tuple[list[tuple[list[str], float]], Callable[..., tuple[int, float]]]:
        seen: list[tuple[list[str], float]] = []

        def run(command, *, stall_seconds, stderr_path, on_progress=None, clock=None):
            seen.append((list(command), stall_seconds))
            Path(stderr_path).write_text("", encoding="utf-8")
            for token in command:
                if str(token).endswith(".wav"):
                    Path(token).parent.mkdir(parents=True, exist_ok=True)
                    Path(token).write_bytes(b"")
            return 0, 0.0

        return seen, run

    def test_without_the_new_options_the_command_is_exactly_as_before(self) -> None:
        from media_manglers.core import voice_track

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, work = root / "session.mkv", root / "work"
            seen, run = self._capture()
            with mock.patch.object(voice_track, "run_while_progressing", run):
                extract_all_tracks("ffmpeg", source, 2, work)
                voice_track.extract_wav("ffmpeg", source, root / "out.wav", ffmpeg_map="0:a:1")
        head = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-nostats", "-progress", "pipe:1",
                "-y", "-i", str(source)]
        self.assertEqual(seen[0], (head + _pcm("0:a:0", work / "track-0.wav") + _pcm("0:a:1", work / "track-1.wav"),
                                   voice_track.DECODE_STALL_SECONDS))
        folder = voice_track.decode_work_dir(root / "out.wav")
        self.assertEqual(seen[1], (head + _pcm("0:a:1", folder / "track.wav"), voice_track.DECODE_STALL_SECONDS))

    def test_input_options_go_before_the_input_and_extra_outputs_after_the_tracks(self) -> None:
        from media_manglers.core import voice_track

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, work = root / "session.mkv", root / "work"
            seen, run = self._capture()
            extra = ["-map", "0:v:0", "-f", "rawvideo", str(work / "frames.raw")]
            with mock.patch.object(voice_track, "run_while_progressing", run):
                wavs = extract_all_tracks("ffmpeg", source, 2, work, ordinals=[1],
                                          input_options=["-skip_frame:v:0", "nokey"], extra_outputs=extra)
        self.assertEqual(wavs, {1: work / "track-1.wav"})
        self.assertEqual(seen[0][0], ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-nostats",
                                      "-progress", "pipe:1", "-y", "-skip_frame:v:0", "nokey", "-i", str(source)]
                         + _pcm("0:a:1", work / "track-1.wav") + extra)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required")
    def test_a_picture_output_in_the_same_read_leaves_the_wavs_byte_for_byte(self) -> None:
        import hashlib

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "session.mkv"
            # 20 s at 5 frames a second, a keyframe every 2 s, and three audio tracks.
            subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-v", "error", "-y",
                            "-f", "lavfi", "-i", "testsrc=size=64x48:rate=5:duration=20",
                            "-f", "lavfi", "-i", "anoisesrc=d=20:r=48000:a=0.3",
                            "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:duration=20",
                            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                            "-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:a", "-t", "20",
                            "-c:v", "libx264", "-g", "10", "-keyint_min", "10", "-sc_threshold", "0",
                            "-c:a", "aac", "-b:a", "96k", str(source)], check=True)
            plain = extract_all_tracks(shutil.which("ffmpeg"), source, 3, root / "plain")
            frames = root / "both" / "frames.raw"
            both = extract_all_tracks(
                shutil.which("ffmpeg"), source, 3, root / "both", input_options=["-skip_frame:v:0", "nokey"],
                extra_outputs=["-map", "0:v:0", "-fps_mode", "passthrough", "-vf", "scale=64:36,format=gray",
                               "-pix_fmt", "gray", "-f", "rawvideo", str(frames)])
            digest = {name: [hashlib.sha256(path.read_bytes()).hexdigest() for _ordinal, path in sorted(wavs.items())]
                      for name, wavs in (("plain", plain), ("both", both))}
            picture = frames.read_bytes()
        self.assertEqual(digest["plain"], digest["both"])
        self.assertTrue(picture)
        self.assertEqual(len(picture) % (64 * 36), 0)
        self.assertEqual(len(picture) // (64 * 36), 10, "keyframes only, not all 100 frames")


class WordTimingsTests(unittest.TestCase):
    """226: the shared transcriber can keep Whisper's word timings (the editor's cut points)."""

    SEGMENTS = [{"start": 0.0, "end": 1.0, "text": " box box",
                 "words": [{"word": " box", "start": 0.0, "end": 0.4}, {"word": " box", "start": 0.5, "end": 0.9}]}]

    def _transcribe(self, device: str, **options):
        from media_manglers.core import voice_track
        from media_manglers.providers import whisper_local

        model = mock.Mock()
        model.transcribe.return_value = {"segments": [dict(item) for item in self.SEGMENTS]}
        with mock.patch.object(whisper_local, "load_whisper_model", return_value=model) as load, \
                mock.patch.object(whisper_local, "pick_whisper_device", return_value=device):
            transcribe = voice_track.whisper_transcriber("small", device == "cuda", "en", **options)
            segments = transcribe(Path("probe.wav"))
        load.assert_called_once_with("small", device)
        return model, segments

    def test_without_word_timings_whisper_is_asked_exactly_as_before(self) -> None:
        model, _segments = self._transcribe("cpu")
        model.transcribe.assert_called_once_with("probe.wav", language="en", task="transcribe", verbose=None,
                                                 fp16=False, condition_on_previous_text=False, temperature=0.0)
        model, _segments = self._transcribe("cuda")
        self.assertIs(model.transcribe.call_args.kwargs["fp16"], True)

    def test_word_timings_are_asked_for_and_kept(self) -> None:
        model, segments = self._transcribe("cuda", word_timestamps=True)
        model.transcribe.assert_called_once_with("probe.wav", language="en", task="transcribe", verbose=None,
                                                 fp16=True, condition_on_previous_text=False, temperature=0.0,
                                                 word_timestamps=True)
        self.assertEqual(segments[0]["words"], self.SEGMENTS[0]["words"])



class TalkLevelRuleTests(unittest.TestCase):
    """226: the level a track counts as active (talking) above is one shared rule, used on 50 ms frames
    by the activity measure and on stored levels per second by the AI Video Editor's cut points."""

    def test_the_quiet_and_the_level_above_it_come_from_one_rule(self) -> None:
        from media_manglers.core import voice_track

        levels = [-80.0] * 85 + [-20.0] * 15
        self.assertEqual(voice_track.noise_floor_dbfs(levels), -80.0, "the quietest 15% stay at or under it")
        self.assertEqual(voice_track.noise_floor_dbfs([-30.0] * 10 + [-60.0] * 10), -60.0)
        self.assertEqual(voice_track.active_threshold_dbfs(-80.0), voice_track.ACTIVE_MIN_DBFS, "never below the minimum")
        self.assertEqual(voice_track.active_threshold_dbfs(-40.0), -40.0 + voice_track.ACTIVE_ABOVE_FLOOR_DB)
        self.assertEqual(voice_track.talk_threshold_dbfs(levels), -50.0)
        self.assertEqual(voice_track.talk_threshold_dbfs([-41.27] * 20 + [-10.0] * 5), -29.3)
        self.assertIsNone(voice_track.talk_threshold_dbfs([]))
        self.assertIsNone(voice_track.talk_threshold_dbfs(None))
        self.assertIsNone(voice_track.talk_threshold_dbfs([-90.0] * 10), "a silent track has no talk level")

    def test_the_activity_measure_uses_the_rule(self) -> None:
        from media_manglers.core import voice_track

        floors: list[float] = []
        real_floor = voice_track.noise_floor_dbfs

        def floor(levels):
            floors.append(real_floor(levels))
            return floors[-1]

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "talk.wav"
            _write_wav(path, [(1.0, 2.0), (3.0, 3.5)], seconds=6.0)
            with mock.patch.object(voice_track, "noise_floor_dbfs", side_effect=floor),                     mock.patch.object(voice_track, "active_threshold_dbfs", wraps=voice_track.active_threshold_dbfs) as above:
                activity = analyze_track_wav(path, 0)
        self.assertEqual(len(floors), 1)
        above.assert_called_once_with(floors[0])
        self.assertEqual(activity.noise_floor_dbfs, round(floors[0], 2))
        self.assertFalse(activity.silent)


if __name__ == "__main__":
    unittest.main()
