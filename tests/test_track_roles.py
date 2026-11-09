"""196 track roles: the narration track is chosen by track names, then the per-track setting,
then detection, and the result says which of the three decided it.

The detector runs for real on synthetic tracks written as WAVs; only the reading of the recording
and Whisper are stood in for. The layout is a typical six-track OBS layout for sim racing:
Track 1 everything, Track 2 the narration, Track 3 the game, Track 4 nothing, Track 5 the spotter
and race engineer, Track 6 music.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core import voice_track  # noqa: E402

import tests.test_voice_track as voice_tests  # noqa: E402  (its WAV and Whisper stand-ins)

SECONDS = 20.0
NAMES_SIX_TRACK = (
    "T1 - Full Mix",
    "T2 - Narration / Discord",
    "T3 - Game / Simulator",
    "T4 - System Default Audio",
    "T5 - Spotters / Race Engineers",
    "T6 - Music",
)
MIC = [(start, start + 1.0) for start in range(0, 20, 4)]  # a phrase every 4 seconds
BUSY = [(start, start + 0.8) for start in range(20)]  # sound 80% of the time
TEAMMATE = " ".join(["we", "should", "pit", "next", "time", "around", "for", "fresh", "tyres", "mate"] * 12)


def _detect(titles: tuple[str, ...], words: dict[int, str], *, setting=None, patterns=None, heard=None,
            preferred=()) -> dict:
    """detect_from_request on a six-track recording with these track names and spoken words."""

    patterns = patterns or {0: BUSY, 1: MIC, 2: BUSY, 3: [], 4: [(start + 2.0, start + 3.0) for start in range(0, 20, 4)], 5: []}
    hearing = voice_tests._transcriber_hearing(words)

    def transcriber(path: Path) -> list[dict[str, object]]:
        if heard is not None:
            heard.append(path.name)
        return hearing(path)

    def extract(_ffmpeg: str, _source: Path, count: int, work_dir: Path, **_kwargs: object) -> dict[int, Path]:
        work_dir.mkdir(parents=True, exist_ok=True)
        outputs = {}
        for ordinal in range(count):
            outputs[ordinal] = work_dir / f"track-{ordinal}.wav"
            voice_tests._write_wav(outputs[ordinal], patterns.get(ordinal, []), seconds=SECONDS)
        return outputs

    streams = [{"tags": {"title": title}} if title else {} for title in titles]
    payload = {"source_path": "synthetic-session.mkv", "preferred_ordinals": list(preferred)}
    if setting is not None:
        payload["track_roles"] = setting
    with tempfile.TemporaryDirectory() as temp, \
            mock.patch.object(voice_track, "probe_audio_streams", return_value=(streams, SECONDS)), \
            mock.patch.object(voice_track, "extract_all_tracks", side_effect=extract), \
            mock.patch.object(voice_track, "whisper_transcriber", return_value=transcriber):
        payload["work_dir"] = temp
        return voice_track.detect_from_request(payload)


class TrackNameTests(unittest.TestCase):
    def test_the_track_named_narration_is_chosen_from_its_name(self) -> None:
        # Track 5's teammate says far more than Track 2's narration: by sound alone the app asks.
        heard: list[str] = []
        result = _detect(NAMES_SIX_TRACK, {1: voice_tests.NARRATION_WORDS, 4: TEAMMATE, 0: TEAMMATE}, heard=heard)
        self.assertEqual((result["status"], result["selected_ordinal"]), ("selected", 1), result["explanation"])
        self.assertEqual(result.get("decided_by"), "track_name")
        self.assertEqual(result.get("decided_by_text"), "from track name")
        self.assertTrue(result["explanation"].startswith("From track name: Track 2 carries your narration"),
                        result["explanation"])
        self.assertIn('"T2 - Narration / Discord"', result["explanation"])
        # Only the narration track is listened to.
        self.assertEqual(heard, ["probe-1.wav"])

    def test_a_named_narration_track_with_no_speech_is_no_narration_not_another_track(self) -> None:
        result = _detect(NAMES_SIX_TRACK, {4: TEAMMATE})
        self.assertEqual(result["status"], "no_narration_found", result["explanation"])
        self.assertEqual(result.get("decided_by"), "track_name")
        self.assertIn("Track 2 is your narration track", result["explanation"])

    def test_name_words_ignore_case_and_a_narration_word_always_wins(self) -> None:
        # 199: a name containing "narration" is always the narration, whatever else it says.
        # This reverses an earlier rule, where a never-word in the same name won.
        self.assertEqual(voice_track.role_from_name("t2 - NARRATION"), voice_track.ROLE_NARRATION)
        self.assertEqual(voice_track.role_from_name("Narration and game mix"), voice_track.ROLE_NARRATION)
        for name in NAMES_SIX_TRACK[2:]:
            self.assertEqual(voice_track.role_from_name(name), voice_track.ROLE_NEVER, name)
        self.assertEqual(voice_track.role_from_name("T1 - Full Mix"), voice_track.ROLE_FULL_MIX)
        self.assertEqual(voice_track.role_from_name("Track1"), voice_track.ROLE_AUTO)
        self.assertEqual(voice_track.role_from_name(""), voice_track.ROLE_AUTO)

    def test_discord_is_never_narration_unless_the_name_says_narration(self) -> None:
        # 199: an operator may move Discord off the narration track. Older recordings that still name
        # Track 2 "T2 - Narration / Discord" keep working.
        self.assertEqual(voice_track.role_from_name("T2 - Narration / Discord"), voice_track.ROLE_NARRATION)
        self.assertEqual(voice_track.role_from_name("T2 - Narration"), voice_track.ROLE_NARRATION)
        for name in ("Discord", "T4 - Discord", "Voice chat", "T5 - VOICE CHAT / Team"):
            self.assertEqual(voice_track.role_from_name(name), voice_track.ROLE_NEVER, name)

    def test_a_recording_named_the_new_way_picks_track_2_from_its_name(self) -> None:
        names = ("T1 - Full Mix", "T2 - Narration", "T3 - Game / Simulator", "T4 - Discord",
                 "T5 - Spotters / Race Engineers", "T6 - Music")
        heard: list[str] = []
        result = _detect(names, {1: voice_tests.NARRATION_WORDS, 3: TEAMMATE, 4: TEAMMATE}, heard=heard,
                         patterns={0: BUSY, 1: MIC, 2: BUSY, 3: [(start + 2.0, start + 3.0) for start in range(0, 20, 4)],
                                   4: [], 5: []})
        self.assertEqual((result["status"], result["selected_ordinal"], result["decided_by"]), ("selected", 1, "track_name"))
        self.assertIn('"T2 - Narration"', result["explanation"])
        self.assertEqual(result["track_roles"]["4"], voice_track.ROLE_NEVER)
        self.assertEqual(heard, ["probe-1.wav"])

    def test_names_win_over_the_setting(self) -> None:
        result = _detect(NAMES_SIX_TRACK, {1: voice_tests.NARRATION_WORDS, 4: TEAMMATE}, setting={"5": "narration"})
        self.assertEqual((result["selected_ordinal"], result.get("decided_by")), (1, "track_name"))

    def test_a_full_mix_is_used_only_when_no_other_track_qualifies(self) -> None:
        names = ("Full Mix", "Mic", "Game", "", "", "")
        activities = {
            0: voice_tests._measured(0, active=0.3, loud=0.3, swing=25.0, bursts_per_minute=20.0),
            1: voice_tests._measured(1, active=0.1, loud=0.1, swing=30.0, bursts_per_minute=20.0),
            2: voice_tests._measured(2, active=0.7, loud=0.7, swing=4.0, bursts_per_minute=2.0),
        }
        titles = dict(enumerate(names[:3]))
        both = {0: voice_track.TrackProbe(0, confident_words=200), 1: voice_track.TrackProbe(1, confident_words=40)}
        result = voice_track.decide_with_roles(activities, both, titles)
        self.assertEqual((result["status"], result["selected_ordinal"]), ("selected", 1), result["explanation"])
        only_mix = {0: voice_track.TrackProbe(0, confident_words=200)}
        result = voice_track.decide_with_roles(activities, only_mix, titles)
        self.assertEqual((result["status"], result["selected_ordinal"]), ("selected", 0), result["explanation"])
        self.assertEqual(result["decided_by"], "auto")


class TrackSettingTests(unittest.TestCase):
    """Recordings made before the tracks were named: the per-track setting decides."""

    UNNAMED = ("", "", "", "", "", "")
    TYPICAL_SETTING = {"1": "auto", "2": "narration", "3": "never", "4": "auto", "5": "never", "6": "never"}

    def test_the_setting_chooses_the_narration_track(self) -> None:
        heard: list[str] = []
        result = _detect(self.UNNAMED, {1: voice_tests.NARRATION_WORDS, 4: TEAMMATE, 0: TEAMMATE},
                         setting=self.TYPICAL_SETTING, heard=heard)
        self.assertEqual((result["status"], result["selected_ordinal"]), ("selected", 1), result["explanation"])
        self.assertEqual((result.get("decided_by"), result.get("decided_by_text")), ("setting", "from your setting"))
        self.assertTrue(result["explanation"].startswith("From your setting: Track 2 carries your narration"),
                        result["explanation"])
        self.assertEqual(heard, ["probe-1.wav"])

    def test_a_silent_narration_track_no_longer_picks_the_spotter_track(self) -> None:
        # A recording where Track 2 is audible but says nothing; Track 5 carries 70 words.
        # Detection alone picks Track 5 silently. With Track 2 set to Narration there is no narration.
        result = _detect(self.UNNAMED, {4: TEAMMATE}, setting=self.TYPICAL_SETTING)
        self.assertEqual(result["status"], "no_narration_found", result["explanation"])
        self.assertIsNone(result["selected_ordinal"])
        self.assertEqual(result.get("decided_by"), "setting")

    def test_never_narration_tracks_are_left_out_of_detection(self) -> None:
        # Only exclusions set: detection decides among the rest, and says which tracks it left out.
        heard: list[str] = []
        result = _detect(self.UNNAMED, {1: voice_tests.NARRATION_WORDS, 4: TEAMMATE},
                         setting={"3": "never", "5": "never", "6": "never"}, heard=heard)
        self.assertEqual((result["status"], result["selected_ordinal"]), ("selected", 1), result["explanation"])
        self.assertEqual(result.get("decided_by"), "auto")
        self.assertIn("Track 3, Track 5 and Track 6 were left out: your setting says they are never narration",
                      result["explanation"])
        self.assertNotIn("probe-4.wav", heard)

    def test_the_setting_is_read_by_track_number(self) -> None:
        self.assertEqual(voice_track.parse_track_roles({"2": "Narration", "3": "never", "4": "auto", "x": "never"}),
                         {1: "narration", 2: "never"})
        self.assertEqual(voice_track.parse_track_roles(["auto", "narration"]), {1: "narration"})
        self.assertEqual(voice_track.parse_track_roles(None), {})


class AutoDetectTests(unittest.TestCase):
    def test_with_no_names_and_no_setting_the_result_says_auto_detected(self) -> None:
        result = _detect(("", "", "", "", "", ""), {1: voice_tests.NARRATION_WORDS})
        self.assertEqual((result["status"], result["selected_ordinal"]), ("selected", 1), result["explanation"])
        self.assertEqual((result.get("decided_by"), result.get("decided_by_text")), ("auto", "auto-detected"))
        self.assertTrue(result["explanation"].startswith("Auto-detected: "), result["explanation"])

    def test_obs_default_track_names_are_no_track_names(self) -> None:
        result = _detect(("Track1", "Track2", "Track3", "Track4", "Track5", "Track6"),
                         {1: voice_tests.NARRATION_WORDS}, setting={"2": "narration"})
        self.assertEqual(result.get("decided_by"), "setting")


if __name__ == "__main__":
    unittest.main()
