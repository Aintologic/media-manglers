"""220, after the first full scan: the game track comes from Track roles, and Keep likely needs speech.

A first full scan of a recordings library found two faults. Idle time was "unknown" for most
recordings, and the game track it did use moved between tracks, because the automatic guess stood in
where the track layout was known. And Keep likely was given to recordings with a few seconds of
speech. The rules now:

- When Track roles (or the recording's own track names) say which track is the game audio, that track
  is used and no other is picked instead. When the recording has no such track, or it is silent the
  whole recording, idle time is estimated from the full mix, said so, or it is "unknown" with the reason.
- Keep likely needs at least a minute of speech on the narration track; less is Check, with the reason.
- The library takes the new rules from what it already stored: nothing is read from the recordings.
"""

from __future__ import annotations

import builtins
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core import activity_timeline, app_cache, raw_bin_library, voice_track  # noqa: E402
from tests.test_raw_bin_library import FFMPEG, FFPROBE, HearingTranscriber, make_recording  # noqa: E402

LOUD, SILENT = -20.0, -120.0
PLAIN_SIX = {ordinal: f"Track{ordinal + 1}" for ordinal in range(6)}
OPERATOR_ROLES = "1=full_mix,2=narration,3=game,5=never,6=never"


def driving_with_a_break(seconds: int = 600, quiet: tuple[int, int] = (200, 400)) -> list[float]:
    return [SILENT if quiet[0] <= second < quiet[1] else LOUD for second in range(seconds)]


class GameTrackFromRolesTests(unittest.TestCase):
    def test_a_game_track_set_in_track_roles_is_never_swapped_for_another_track(self) -> None:
        # The setting says Track 3; a recording with one track has no Track 3. The automatic guess
        # used to take Track 1 instead.
        game, why = voice_track.game_audio_track({0: ""}, setting_value={"3": "game"})
        self.assertIsNone(game)
        self.assertIn("Track 3", why)
        # With the track there, the setting wins over the automatic guess, which would take Track 6.
        activities = {ordinal: voice_track.TrackActivity(ordinal=ordinal, duration_seconds=60, silent=ordinal != 5)
                      for ordinal in range(6)}
        self.assertEqual(voice_track.game_audio_track(PLAIN_SIX, narration_ordinal=1, activities=activities),
                         (5, voice_track.DECIDED_BY_AUTO))
        self.assertEqual(voice_track.game_audio_track(PLAIN_SIX, setting_value={"2": "narration", "3": "game"},
                                                      narration_ordinal=1, activities=activities),
                         (2, voice_track.DECIDED_BY_SETTING))

    def test_full_mix_is_a_track_role_and_is_the_narration_of_last_resort(self) -> None:
        from media_manglers_workbench.track_roles import ROLE_CHOICES, format_roles, parse_roles

        self.assertIn(("full_mix", "Full mix"), ROLE_CHOICES)
        self.assertEqual(parse_roles(OPERATOR_ROLES), {1: "full_mix", 2: "narration", 3: "game", 5: "never", 6: "never"})
        self.assertEqual(format_roles(parse_roles(OPERATOR_ROLES)), OPERATOR_ROLES)
        self.assertEqual(voice_track.parse_track_roles({"1": "full_mix"}), {0: voice_track.ROLE_FULL_MIX})
        self.assertEqual(voice_track.full_mix_track(PLAIN_SIX, setting_value={"1": "full_mix"}), 0)
        self.assertEqual(voice_track.full_mix_track({0: "T1 - Full Mix", 1: "T2 - Narration"}), 0)
        self.assertEqual(voice_track.full_mix_track({0: ""}), 0, "a recording's only track is its full mix")
        self.assertIsNone(voice_track.full_mix_track({0: "", 1: ""}))
        script = (Path(__file__).resolve().parents[1] / "Video Mangler.ps1").read_text(encoding="utf-8")
        self.assertIn('$role -in @("narration", "never", "full_mix")', script)

    def test_the_set_game_track_measures_idle_time(self) -> None:
        levels = {0: [LOUD] * 600, 1: [LOUD] * 600, 2: driving_with_a_break()}
        timeline = raw_bin_library.idle_from_levels(
            {0: "", 1: "", 2: ""}, levels, 600, game=2, decided_by=voice_track.DECIDED_BY_SETTING, reason="",
            setting_value={"3": "game"})
        self.assertEqual((timeline.status, timeline.game_track, timeline.idle_seconds), ("measured", 2, 200))

    def test_a_missing_or_silent_game_track_is_estimated_from_the_full_mix(self) -> None:
        roles = raw_bin_library._roles_value(OPERATOR_ROLES)
        # Track 3 is there but silent the whole recording: the full mix (Track 1) is listened to instead.
        levels = {0: driving_with_a_break(), 1: [LOUD] * 600, 2: [SILENT] * 600}
        game, by = voice_track.game_audio_track({0: "", 1: "", 2: ""}, setting_value=roles)
        silent = raw_bin_library.idle_from_levels({0: "", 1: "", 2: ""}, levels, 600, game=game, decided_by=by,
                                                  reason="", setting_value=roles)
        self.assertEqual(silent.status, activity_timeline.STATUS_ESTIMATED)
        self.assertEqual(silent.idle_seconds, 200)
        self.assertIn("estimated from the full mix (track 1)", silent.reason.casefold())
        self.assertIn("Track 3", silent.reason)
        self.assertIn("silent", silent.reason)
        # An early recording with everything on one track: no Track 3 at all.
        game, by = voice_track.game_audio_track({0: ""}, setting_value=roles)
        early = raw_bin_library.idle_from_levels({0: ""}, {0: driving_with_a_break()}, 600, game=game, decided_by=by,
                                                 reason=by, setting_value=roles)
        self.assertEqual((early.status, early.idle_seconds), (activity_timeline.STATUS_ESTIMATED, 200))
        self.assertIn("no Track 3", early.reason)

    def test_without_a_full_mix_to_fall_back_on_idle_time_is_unknown_with_the_reason(self) -> None:
        roles = {"2": "narration", "3": "game"}
        titles = {0: "", 1: "", 2: ""}
        levels = {0: [LOUD] * 600, 1: [LOUD] * 600, 2: [SILENT] * 600}
        game, by = voice_track.game_audio_track(titles, setting_value=roles)
        timeline = raw_bin_library.idle_from_levels(titles, levels, 600, game=game, decided_by=by, reason="",
                                                    setting_value=roles)
        self.assertEqual(timeline.status, "unknown")
        self.assertIn("Track 3", timeline.reason)
        self.assertIn("silent", timeline.reason)
        self.assertIn("no full mix", timeline.reason)
        quiet = raw_bin_library.idle_from_levels(titles, {0: [SILENT] * 60, 1: [SILENT] * 60, 2: [SILENT] * 60}, 60,
                                                 game=game, decided_by=by, reason="", setting_value=roles)
        self.assertEqual(quiet.status, "unknown")
        self.assertIn("silent", quiet.reason)

    def test_the_narration_track_is_never_taken_for_the_full_mix(self) -> None:
        # Review: Track 1 silent, Track 2 your voice, Track 3 the silent game track. Track 2 is the only
        # track with sound, but it is the narration microphone, not a full mix.
        roles = {"2": "narration", "3": "game"}
        titles = {0: "", 1: "", 2: ""}
        levels = {0: [SILENT] * 600, 1: driving_with_a_break(), 2: [SILENT] * 600}
        game, by = voice_track.game_audio_track(titles, setting_value=roles)
        timeline = raw_bin_library.idle_from_levels(titles, levels, 600, game=game, decided_by=by, reason="",
                                                    setting_value=roles, narration=1)
        self.assertEqual(timeline.status, "unknown")
        self.assertIsNone(voice_track.full_mix_track(titles, setting_value=roles, sounding={1}))
        self.assertIsNone(voice_track.full_mix_track({0: ""}, setting_value={"1": "narration"}))

    def test_a_full_mix_set_in_track_roles_is_set_aside_by_the_automatic_guess(self) -> None:
        activities = {ordinal: voice_track.TrackActivity(ordinal=ordinal, silent=False) for ordinal in range(3)}
        plain = {0: "", 1: "", 2: ""}
        self.assertEqual(voice_track.game_audio_track(plain, setting_value={"1": "full_mix", "2": "narration"},
                                                      narration_ordinal=1, activities=activities),
                         (2, voice_track.DECIDED_BY_AUTO))

    def test_the_backend_keeps_the_full_mix_role(self) -> None:
        from tests.test_track_roles_backend import _run

        with tempfile.TemporaryDirectory() as temp:
            result = _run(
                """
                $roles = ConvertTo-MMTrackRoles -Text '1=full_mix,2=narration,3=game,5=never,6=never'
                [ordered]@{ key = Get-MMTrackRolesKey -Roles $roles } | ConvertTo-Json -Compress
                """,
                Path(temp),
            )
        self.assertEqual(result, {"key": "1=full_mix,2=narration,3=never,5=never,6=never"})

    def test_with_no_role_set_the_automatic_guess_stays(self) -> None:
        levels = {0: [LOUD] * 600, 1: [LOUD] * 600, 2: driving_with_a_break()}
        timeline = raw_bin_library.idle_from_levels({0: "", 1: "", 2: ""}, levels, 600, game=2,
                                                    decided_by=voice_track.DECIDED_BY_AUTO, reason="", setting_value={})
        self.assertEqual((timeline.status, timeline.idle_seconds), ("measured", 200))
        unknown = raw_bin_library.idle_from_levels({0: "", 1: "", 2: ""}, levels, 600, game=None, decided_by="",
                                                   reason="more than one track could be the game audio",
                                                   setting_value={})
        self.assertEqual(unknown.status, "unknown")
        self.assertIn("more than one track", unknown.reason)


class NamedNeverGameTrackTests(unittest.TestCase):
    """226: by elimination, the game audio is never a track named for music, a spotter, an engineer,
    Discord or voice chat: that sound must never be published as the game. "System" stays eligible,
    because desktop sound is often the game. Names and Track roles still decide first."""

    SOUNDING = {ordinal: voice_track.TrackActivity(ordinal=ordinal, silent=False) for ordinal in range(3)}

    def test_the_words_that_are_never_the_game_audio(self) -> None:
        self.assertEqual(voice_track.NOT_GAME_AUDIO_NAME_WORDS, ("music", "spotter", "engineer", "discord", "voice chat"))
        self.assertTrue(set(voice_track.NOT_GAME_AUDIO_NAME_WORDS) <= set(voice_track.NEVER_NARRATION_NAME_WORDS))

    def test_the_only_track_left_is_not_the_game_when_its_name_says_never_narration(self) -> None:
        for name in ("T3 - Music", "Spotter", "Race Engineer", "DISCORD", "Voice  Chat"):
            with self.subTest(name=name):
                game, why = voice_track.game_audio_track({0: "Full mix", 1: "", 2: name}, narration_ordinal=1,
                                                         activities=self.SOUNDING)
                self.assertIsNone(game)
                self.assertEqual(why, f"the only track left, Track 3 ({name}), is named as never narration")
        # The same recording without that name: the track left is the game audio, as before.
        self.assertEqual(voice_track.game_audio_track({0: "Full mix", 1: "", 2: ""}, narration_ordinal=1,
                                                      activities=self.SOUNDING), (2, voice_track.DECIDED_BY_AUTO))
        self.assertEqual(voice_track.game_audio_track({0: "Full mix", 1: "", 2: "T3 - System"}, narration_ordinal=1,
                                                      activities=self.SOUNDING), (2, voice_track.DECIDED_BY_AUTO))

    def test_a_music_track_no_longer_stands_in_the_way_of_the_real_game_track(self) -> None:
        # Before, two tracks were left and the guess could not tell.
        self.assertEqual(voice_track.game_audio_track({0: "", 1: "", 2: "Music"}, narration_ordinal=1,
                                                      activities=self.SOUNDING), (0, voice_track.DECIDED_BY_AUTO))
        game, why = voice_track.game_audio_track({0: "Full mix", 1: "Spotter", 2: "Music", 3: ""}, narration_ordinal=3)
        self.assertIsNone(game)
        self.assertEqual(why, "the tracks left, Track 2 (Spotter) and Track 3 (Music), are named as never narration")

    def test_names_and_track_roles_still_decide_first(self) -> None:
        self.assertEqual(voice_track.game_audio_track({0: "Music", 1: "T2 - Narration", 2: "T3 - Game"}),
                         (2, voice_track.DECIDED_BY_NAME))
        self.assertEqual(voice_track.game_audio_track({0: "", 1: "", 2: "Spotter"}, setting_value={"3": "game"}),
                         (2, voice_track.DECIDED_BY_SETTING))
        # A track SET to Never narration stays eligible: settings made before Wave 6 used that for the game.
        activities = {0: voice_track.TrackActivity(ordinal=0, silent=False),
                      1: voice_track.TrackActivity(ordinal=1, silent=False),
                      2: voice_track.TrackActivity(ordinal=2, silent=True)}
        self.assertEqual(voice_track.game_audio_track({0: "", 1: "", 2: ""}, setting_value={"1": "never", "2": "narration"},
                                                      narration_ordinal=1, activities=activities),
                         (0, voice_track.DECIDED_BY_AUTO))

    def test_with_no_game_track_left_idle_time_is_estimated_from_the_full_mix(self) -> None:
        titles = {0: "T1 - Full Mix", 1: "T2 - Narration", 2: "T3 - Spotter"}
        levels = {0: driving_with_a_break(), 1: [LOUD] * 600, 2: [LOUD] * 600}
        game, why = voice_track.game_audio_track(titles, narration_ordinal=1)
        timeline = raw_bin_library.idle_from_levels(titles, levels, 600, game=game, decided_by="", reason=why,
                                                    setting_value={}, narration=1)
        self.assertEqual((timeline.status, timeline.idle_seconds, timeline.game_track),
                         (activity_timeline.STATUS_ESTIMATED, 200, None))
        self.assertEqual(timeline.reason, "Estimated from the full mix (Track 1): the only track left, "
                                          "Track 3 (T3 - Spotter), is named as never narration.")
        # No full mix to estimate from: unknown, naming the track.
        titles = {0: "T1 - Narration", 1: "T2 - Spotter"}
        game, why = voice_track.game_audio_track(titles, narration_ordinal=0)
        timeline = raw_bin_library.idle_from_levels(titles, {0: [LOUD] * 600, 1: [LOUD] * 600}, 600, game=game,
                                                    decided_by="", reason=why, setting_value={}, narration=0)
        self.assertEqual(timeline.status, activity_timeline.STATUS_UNKNOWN)
        self.assertEqual(timeline.reason, "The only track left, Track 2 (T2 - Spotter), is named as never narration, "
                                          "and there is no full mix to estimate it from.")
        # Any other reason the guess could not tell stays unknown, as before.
        self.assertEqual(raw_bin_library.idle_from_levels(
            {0: "", 1: "", 2: ""}, levels, 600, game=None, decided_by="",
            reason="more than one track could be the game audio; name it or set it in Settings",
            setting_value={}).status, activity_timeline.STATUS_UNKNOWN)


class SpeechMinuteTests(unittest.TestCase):
    @staticmethod
    def _with_speech(seconds: float) -> raw_bin_library.Guess:
        return raw_bin_library.decide_guess(5_000_000, 600, {
            "status": "selected", "selected_ordinal": 1,
            "track_activity": {"2": {"active_seconds": seconds}}, "track_probes": {}, "track_roles": {}})

    def test_keep_likely_needs_a_minute_of_speech_on_the_narration_track(self) -> None:
        short = self._with_speech(59.0)
        self.assertEqual(short.guess, raw_bin_library.GUESS_CHECK)
        self.assertIn("59 seconds", short.reason)
        self.assertIn("Track 2", short.reason)
        self.assertEqual(short.narration_track, 2, "jump to speech still knows the narration track")
        enough = self._with_speech(60.0)
        self.assertEqual((enough.guess, enough.reason), (raw_bin_library.GUESS_KEEP, "Track 2 has your narration."))
        self.assertEqual(self._with_speech(3.0).guess, raw_bin_library.GUESS_CHECK)


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg is required")
class ReapplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.raw = self.root / "raw"
        self.library = self.root / "library"
        self.cache = self.root / "cache"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _scan(self, roles: str) -> dict:
        return raw_bin_library.scan(raw_bin_library.ScanOptions(
            folders=[str(self.raw)], ffmpeg=FFMPEG, ffprobe=FFPROBE, transcriber=HearingTranscriber({2}),
            library_root=str(self.library), cache_folder=str(self.cache), stable_after_seconds=0, track_roles=roles))

    def _rows(self) -> list[dict]:
        connection = raw_bin_library.connect(self.library)
        try:
            return raw_bin_library.list_recordings(connection)
        finally:
            connection.close()

    def test_a_silent_game_track_is_estimated_from_the_full_mix_through_the_real_scan(self) -> None:
        make_recording(self.raw / "early.mkv", game_silent=True)
        self._scan("")
        row = self._rows()[0]
        self.assertEqual(row["idle_status"], activity_timeline.STATUS_ESTIMATED)
        self.assertIn("estimated from the full mix (track 1)", row["idle_reason"].casefold())
        self.assertEqual(raw_bin_library.export_row(row)["idle_note"], row["idle_reason"])
        self.assertEqual(row["guess"], raw_bin_library.GUESS_KEEP)
        self.assertGreaterEqual(row["speech_seconds"], 60)

    def test_new_track_roles_and_rules_are_applied_without_reading_the_recordings(self) -> None:
        recording = make_recording(self.raw / "session.mkv", titles=("", "", ""))
        self._scan("2=narration")
        row = self._rows()[0]
        self.assertEqual(row["idle_status"], "unknown", "two tracks could be the game: the guess cannot tell")

        # The operator sets Track roles. A scan reads nothing (the file is unchanged) but the library
        # follows the setting: Track 3 is the game audio.
        again = self._scan(OPERATOR_ROLES)
        self.assertEqual((again["files_read"], again["bytes_read"], again["unchanged"]), (0, 0, 1))
        row = self._rows()[0]
        self.assertEqual((row["game_track"], row["game_track_decided_by"]), (3, voice_track.DECIDED_BY_SETTING))
        self.assertEqual(row["idle_status"], "measured")
        self.assertAlmostEqual(row["idle_seconds"], 70, delta=6)

        # The rules are applied straight to the stored library, with the recordings out of reach: the
        # folder is gone, any open of a file in it is caught, and FFmpeg cannot be started.
        connection = raw_bin_library.connect(self.library)
        with connection:
            connection.execute("UPDATE recordings SET speech_seconds = 59, guess = 'keep_likely', rules_version = 1, "
                               "game_track = 6, game_track_decided_by = 'auto'")
        moved = self.root / "elsewhere"
        shutil.move(str(self.raw), str(moved))
        opened: list[str] = []
        real_open = builtins.open

        def watching_open(file, *args, **kwargs):
            name = os.fspath(file) if isinstance(file, (str, os.PathLike)) else ""
            if recording.name in str(name) or str(moved) in str(name):
                opened.append(str(name))
            return real_open(file, *args, **kwargs)

        with mock.patch.object(builtins, "open", watching_open), mock.patch.object(io, "open", watching_open), \
                mock.patch.object(subprocess, "Popen", side_effect=AssertionError("nothing is decoded")), \
                mock.patch.object(subprocess, "run", side_effect=AssertionError("nothing is probed")):
            summary = raw_bin_library.reapply_rules(connection, track_roles=OPERATOR_ROLES,
                                                    cache=app_cache.cache_root(str(self.cache)))
        connection.close()
        self.assertEqual(opened, [])
        self.assertEqual(summary["recordings"], 1)
        row = self._rows()[0]
        self.assertEqual(row["guess"], raw_bin_library.GUESS_CHECK)
        self.assertIn("59 seconds", row["guess_reason"])
        self.assertEqual((row["game_track"], row["idle_status"]), (3, "measured"))
        self.assertAlmostEqual(row["idle_seconds"], 70, delta=6)

    def test_taking_the_game_role_away_brings_back_the_automatic_guess(self) -> None:
        # Review: an idle time estimated under a game role must not stay "estimated" (or keep its reason)
        # once the role is gone.
        make_recording(self.raw / "early.mkv", titles=("", "", ""), game_silent=True)
        self._scan(OPERATOR_ROLES)
        row = self._rows()[0]
        self.assertEqual(row["idle_status"], activity_timeline.STATUS_ESTIMATED)
        self._scan("2=narration")
        row = self._rows()[0]
        self.assertNotEqual(row["idle_status"], activity_timeline.STATUS_ESTIMATED)
        self.assertFalse(str(row["idle_reason"] or "").startswith("Estimated"), row["idle_reason"])

    def test_a_library_made_by_the_first_wave_6_build_is_upgraded_and_re_applied(self) -> None:
        make_recording(self.raw / "session.mkv", titles=("", "", ""))
        self._scan("2=narration")
        # Make it look like the first build's library: no new columns, schema version 1.
        connection = raw_bin_library.connect(self.library, backup=False)
        with connection:
            for name in ("idle_reason", "rules_version", "rules_roles"):
                connection.execute(f"ALTER TABLE recordings DROP COLUMN {name}")
            connection.execute("UPDATE schema_metadata SET value = '1' WHERE key = 'schema_version'")
            connection.execute("UPDATE recordings SET guess = 'keep_likely', speech_seconds = 3")
        connection.close()
        again = self._scan(OPERATOR_ROLES)
        self.assertEqual((again["files_read"], again["reapplied"]["recordings"]), (0, 1))
        row = self._rows()[0]
        self.assertEqual(row["guess"], raw_bin_library.GUESS_CHECK)
        self.assertEqual((row["game_track"], row["idle_status"]), (3, "measured"))
        connection = raw_bin_library.connect(self.library, backup=False)
        version = connection.execute("SELECT value FROM schema_metadata WHERE key = 'schema_version'").fetchone()[0]
        connection.close()
        self.assertEqual(version, str(raw_bin_library.SCHEMA_VERSION))
        self.assertEqual(self._scan(OPERATOR_ROLES)["reapplied"]["recordings"], 0, "applied once, not every scan")

    def test_a_stored_automatic_pick_of_a_track_named_never_narration_becomes_no_game_track(self) -> None:
        # 226. A library as the Wave 6 rule made it, with every kind of game-track decision in it.
        recordings = {
            "named.mkv": [("mix", "T1 - Full Mix"), ("narration", "T2 - Narration"), ("game", "T3 - Game")],
            "spotter.mkv": [("mix", "T1 - Full Mix"), ("narration", "T2 - Narration"), ("game", "T3 - Spotter")],
            "music.mkv": [("mix", ""), ("narration", ""), ("game", "Music")],
            "two-left.mkv": [("mix", ""), ("narration", ""), ("game", ""), ("game", "Music")],
            "plain.mkv": [("mix", ""), ("narration", ""), ("game", "")],
            "system.mkv": [("mix", "T1 - Full Mix"), ("narration", "T2 - Narration"), ("game", "T3 - System")],
            "silent-game.mkv": [("mix", "T1 - Full Mix"), ("narration", "T2 - Narration"), ("silent", "T3 - Game")],
        }
        for name, tracks in recordings.items():
            recording_with_tracks(self.raw / name, tracks)
        with mock.patch.object(voice_track, "NOT_GAME_AUDIO_NAME_WORDS", (), create=True):
            self._scan("")  # the Wave 6 rule: no name is left out of the one-track-left guess
        connection = raw_bin_library.connect(self.library, backup=False)
        with connection:
            connection.execute("UPDATE recordings SET rules_version = 2")
        connection.close()
        before = {Path(row["path"]).name: row for row in self._rows()}
        picks = {name: (row["game_track"], row["game_track_decided_by"] or "", row["idle_status"])
                 for name, row in before.items()}
        self.assertEqual(picks, {
            "named.mkv": (3, voice_track.DECIDED_BY_NAME, "measured"),
            "spotter.mkv": (3, voice_track.DECIDED_BY_AUTO, "measured"),
            "music.mkv": (3, voice_track.DECIDED_BY_AUTO, "measured"),
            "two-left.mkv": (None, "", "unknown"),
            "plain.mkv": (3, voice_track.DECIDED_BY_AUTO, "measured"),
            "system.mkv": (3, voice_track.DECIDED_BY_AUTO, "measured"),
            "silent-game.mkv": (None, voice_track.DECIDED_BY_NAME, "estimated"),
        })

        # The next scan reads nothing and re-applies the rules from the stored data.
        again = self._scan("")
        self.assertEqual((again["files_read"], again["bytes_read"], again["reapplied"]["recordings"]), (0, 0, 7))
        after = {Path(row["path"]).name: row for row in self._rows()}
        changed = {name: sorted(column for column in before[name] if column != "rules_version"
                                and before[name][column] != after[name][column]) for name in before}
        idle_columns = ["active_stretches", "active_stretches_json", "game_track", "game_track_decided_by",
                        "idle_reason", "idle_seconds", "idle_share", "idle_status", "idle_stretches", "idle_stretches_json"]
        self.assertEqual({name: columns for name, columns in changed.items() if columns},
                         {"spotter.mkv": idle_columns, "music.mkv": idle_columns})
        self.assertEqual({row["rules_version"] for row in after.values()}, {raw_bin_library.RULES_VERSION})
        spotter, music = after["spotter.mkv"], after["music.mkv"]
        self.assertEqual((spotter["game_track"], spotter["game_track_decided_by"], spotter["idle_status"]),
                         (None, "", activity_timeline.STATUS_ESTIMATED))
        self.assertEqual(spotter["idle_reason"], "Estimated from the full mix (Track 1): the only track left, "
                                                 "Track 3 (T3 - Spotter), is named as never narration.")
        self.assertEqual((music["game_track"], music["idle_status"], music["idle_seconds"]), (None, "unknown", None))
        self.assertEqual(music["idle_reason"], "The only track left, Track 3 (Music), is named as never narration, "
                                               "and there is no full mix to estimate it from.")
        self.assertEqual(after["two-left.mkv"]["idle_status"], "unknown", "an undecided row stays so until it is read")

        # Exactly what a fresh scan with the new rule makes of the same recordings.
        raw_bin_library.scan(raw_bin_library.ScanOptions(
            folders=[str(self.raw)], ffmpeg=FFMPEG, ffprobe=FFPROBE, transcriber=HearingTranscriber({2}),
            library_root=str(self.root / "fresh"), cache_folder=str(self.root / "fresh-cache"),
            stable_after_seconds=0, track_roles=""))
        connection = raw_bin_library.connect(self.root / "fresh", backup=False)
        try:
            fresh = {Path(row["path"]).name: row for row in raw_bin_library.list_recordings(connection)}
        finally:
            connection.close()
        for name in ("spotter.mkv", "music.mkv"):
            for column in ("game_track", "game_track_decided_by", "idle_status", "idle_seconds", "idle_share",
                           "idle_stretches", "active_stretches", "idle_reason"):
                self.assertEqual(after[name][column] or None, fresh[name][column] or None, (name, column))
        # Read again, the recording the old rule could not decide gets its real game track.
        self.assertEqual((fresh["two-left.mkv"]["game_track"], fresh["two-left.mkv"]["game_track_decided_by"],
                          fresh["two-left.mkv"]["idle_status"]), (3, voice_track.DECIDED_BY_AUTO, "measured"))

    def test_without_its_cached_levels_such_a_pick_becomes_unknown_and_says_why(self) -> None:
        recording_with_tracks(self.raw / "spotter.mkv", [("mix", "T1 - Full Mix"), ("narration", "T2 - Narration"),
                                                         ("game", "T3 - Spotter")])
        recording_with_tracks(self.raw / "plain.mkv", [("mix", ""), ("narration", ""), ("game", "")])
        with mock.patch.object(voice_track, "NOT_GAME_AUDIO_NAME_WORDS", (), create=True):
            self._scan("")
        cache = app_cache.cache_root(str(self.cache))
        app_cache.clear(cache)
        connection = raw_bin_library.connect(self.library, backup=False)
        with connection:
            connection.execute("UPDATE recordings SET rules_version = 2")
        before = {Path(row["path"]).name: row for row in raw_bin_library.list_recordings(connection)}
        summary = raw_bin_library.reapply_rules(connection, track_roles="", cache=cache)
        after = {Path(row["path"]).name: row for row in raw_bin_library.list_recordings(connection)}
        connection.close()
        self.assertEqual((summary["recordings"], summary["levels_missing"], summary["idle_changed"]), (2, 2, 1))
        self.assertEqual((after["spotter.mkv"]["game_track"], after["spotter.mkv"]["idle_status"],
                          after["spotter.mkv"]["idle_seconds"]), (None, "unknown", None))
        self.assertEqual(after["spotter.mkv"]["idle_reason"],
                         "The only track left, Track 3 (T3 - Spotter), is named as never narration, and this "
                         "recording's sound levels are no longer in the cache, so its idle time cannot be worked "
                         "out again without reading it.")
        self.assertEqual({column: after["plain.mkv"][column] for column in after["plain.mkv"] if column != "rules_version"},
                         {column: before["plain.mkv"][column] for column in before["plain.mkv"] if column != "rules_version"},
                         "without its levels, any other stored idle time is kept as it was")

    def _upgrade_without_levels(self, library: Path, roles: str) -> tuple[dict, dict, dict]:
        """The library as the Wave 6 rules left it (rules version 2), its cached levels gone (Settings >
        Clear cache), then the rules applied again with the same Track roles."""

        cache = app_cache.cache_root(str(self.cache))
        app_cache.clear(cache)
        connection = raw_bin_library.connect(library, backup=False)
        try:
            with connection:
                connection.execute("UPDATE recordings SET rules_version = 2")
            before = {Path(row["path"]).name: row for row in raw_bin_library.list_recordings(connection)}
            summary = raw_bin_library.reapply_rules(connection, track_roles=roles, cache=cache)
            after = {Path(row["path"]).name: row for row in raw_bin_library.list_recordings(connection)}
        finally:
            connection.close()
        return before, after, summary

    def test_a_rule_version_bump_keeps_an_estimate_its_track_roles_decided(self) -> None:
        # 226: the named-never rule changes only an automatic pick. A row its Track roles or its track
        # names decided keeps its idle time and reason when its levels are no longer in the cache.
        recording_with_tracks(self.raw / "silent3.mkv", [("mix", "Track1"), ("narration", "Track2"), ("silent", "Track3")])
        recording_with_tracks(self.raw / "two-tracks.mkv", [("mix", "Track1"), ("narration", "Track2")])
        self._scan(OPERATOR_ROLES)
        named_raw, named_library = self.root / "raw-named", self.root / "library-named"
        recording_with_tracks(named_raw / "named-game-silent.mkv",
                              [("mix", "T1 - Full Mix"), ("narration", "T2 - Narration"), ("silent", "T3 - Game")])
        raw_bin_library.scan(raw_bin_library.ScanOptions(
            folders=[str(named_raw)], ffmpeg=FFMPEG, ffprobe=FFPROBE, transcriber=HearingTranscriber({2}),
            library_root=str(named_library), cache_folder=str(self.cache), stable_after_seconds=0, track_roles=""))
        for library, roles, names in ((self.library, OPERATOR_ROLES, ("silent3.mkv", "two-tracks.mkv")),
                                      (named_library, "", ("named-game-silent.mkv",))):
            before, after, summary = self._upgrade_without_levels(library, roles)
            self.assertEqual((summary["recordings"], summary["levels_missing"], summary["idle_changed"]),
                             (len(names), len(names), 0))
            for name in names:
                with self.subTest(name=name):
                    self.assertEqual(before[name]["idle_status"], activity_timeline.STATUS_ESTIMATED)
                    self.assertTrue(before[name]["idle_reason"].startswith("Estimated from the full mix (Track 1)"),
                                    before[name]["idle_reason"])
                    for column in ("game_track", "game_track_decided_by", "idle_status", "idle_seconds", "idle_share",
                                   "idle_stretches", "active_stretches", "idle_reason"):
                        self.assertEqual(after[name][column], before[name][column], column)
                    self.assertEqual(after[name]["rules_version"], raw_bin_library.RULES_VERSION)

    def test_without_its_levels_an_automatic_pick_the_named_never_rule_takes_away_is_unknown(self) -> None:
        # A narration track whose name mentions the game sends the row down the role path; its stored pick
        # was automatic (the Spotter track), so it is not kept just because the Track roles did not change.
        recording_with_tracks(self.raw / "edge.mkv", [("mix", "T1 - Full Mix"), ("narration", "T2 - Narration over game"),
                                                     ("game", "T3 - Spotter")])
        with mock.patch.object(voice_track, "NOT_GAME_AUDIO_NAME_WORDS", (), create=True):
            self._scan("")
        before, after, _summary = self._upgrade_without_levels(self.library, "")
        self.assertEqual((before["edge.mkv"]["game_track"], before["edge.mkv"]["game_track_decided_by"]),
                         (3, voice_track.DECIDED_BY_AUTO))
        self.assertEqual((after["edge.mkv"]["game_track"], after["edge.mkv"]["idle_status"],
                          after["edge.mkv"]["idle_seconds"]), (None, activity_timeline.STATUS_UNKNOWN, None))
        # The Track roles did not change, so the reason never says they did.
        self.assertNotIn("Track roles changed", after["edge.mkv"]["idle_reason"])
        self.assertTrue(after["edge.mkv"]["idle_reason"].endswith(
            "and this recording's sound levels are no longer in the cache, so its idle time cannot be worked out "
            "again without reading it."), after["edge.mkv"]["idle_reason"])


def recording_with_tracks(path: Path, tracks: list[tuple[str, str]], *, seconds: int = 260,
                          idle: tuple[int, int] = (30, 100)) -> Path:
    """A recording with these (kind, track name) tracks. Kinds: "mix" (steady noise that carries
    everything), "narration" (speech in bursts, 1.2 s of every 4 s), "game" (noise that falls quiet
    while the narration speaks, so the guess never takes it for a route of the microphone, and stops
    for ``idle``) and "silent"."""

    quiet_from, quiet_to = idle
    sources = {
        "mix": f"anoisesrc=color=brown:amplitude=0.2:sample_rate=48000:duration={seconds}",
        "narration": (f"sine=frequency=300:sample_rate=48000:duration={seconds},"
                      "volume='if(lt(mod(t,4),1.2),1,0)':eval=frame"),
        "game": (f"anoisesrc=color=pink:amplitude=0.3:sample_rate=48000:duration={seconds},"
                 f"volume='if(between(t,{quiet_from},{quiet_to}),0,if(lt(mod(t,4),1.5),0.001,1))':eval=frame"),
        "silent": f"anullsrc=r=48000:cl=mono:d={seconds}",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    command = [FFMPEG, "-hide_banner", "-v", "error", "-y"]
    for kind, _title in tracks:
        command += ["-f", "lavfi", "-i", sources[kind]]
    for index in range(len(tracks)):
        command += ["-map", str(index)]
    command += ["-c:a", "aac", "-b:a", "96k"]
    for index, (_kind, title) in enumerate(tracks):
        command += [f"-metadata:s:a:{index}", f"title={title}"]
    subprocess.run(command + [str(path)], check=True)
    return path


if __name__ == "__main__":
    unittest.main()
