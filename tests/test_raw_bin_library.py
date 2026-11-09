"""220: the raw bin library (215), the app's guess (216) and idle time from the game audio (217).

Real three-track recordings are made with FFmpeg: a full mix, the narration track and the game track,
named the way OBS names them. Whisper is stood in for by a transcriber that "hears" words only on the
tracks a test says carry speech, so every rule is checked through the real scan, the real one-read
decode and the real voice detection.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core import activity_timeline, app_cache, raw_bin_library, recording_identity, user_folders, voice_track  # noqa: E402
from media_manglers.core.review_inbox import sampled_sha256_file  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
WORDS = "please make the dashboard bigger and move the fuel number next to the lap timer " * 4


class HearingTranscriber:
    """Hears clear words on the given track numbers (1 = Track 1) and nothing elsewhere."""

    def __init__(self, speaking: set[int], words: str = WORDS) -> None:
        self.speaking = speaking
        self.words = words
        self.heard: list[str] = []

    def __call__(self, path: Path) -> list[dict]:
        self.heard.append(Path(path).name)
        name = Path(path).stem  # probe-<ordinal> or cross-<lead>-<other>
        ordinal = int(name.rsplit("-", 1)[-1])
        if ordinal + 1 not in self.speaking:
            return []
        return [{"start": 0.0, "end": 8.0, "text": self.words, "no_speech_prob": 0.05, "avg_logprob": -0.2}]


def make_recording(path: Path, *, seconds: int = 260, narration: bool = True, game_idle: tuple[int, int] = (30, 100),
                   titles: tuple[str, str, str] = ("T1 - Full Mix", "T2 - Narration", "T3 - Game"),
                   game_silent: bool = False) -> Path:
    """Three tracks: a full mix, narration in bursts, and game noise that stops for a while.

    The narration talks for 1.2 s of every 4 s; the default length gives it more than the minute of
    speech that Keep likely needs. ``game_silent``: the game track is there but silent throughout."""

    speech = ("sine=frequency=300:sample_rate=48000:duration={s},volume='if(lt(mod(t,4),1.2),1,0)':eval=frame"
              if narration else "anullsrc=r=48000:cl=mono:d={s}").format(s=seconds)
    quiet_from, quiet_to = game_idle
    game = (f"anullsrc=r=48000:cl=mono:d={seconds}" if game_silent else
            f"anoisesrc=color=pink:amplitude=0.3:sample_rate=48000:duration={seconds},"
            f"volume='if(between(t,{quiet_from},{quiet_to}),0,1)':eval=frame")
    mix = f"anoisesrc=color=brown:amplitude=0.2:sample_rate=48000:duration={seconds}"
    path.parent.mkdir(parents=True, exist_ok=True)
    command = [FFMPEG, "-hide_banner", "-v", "error", "-y",
               "-f", "lavfi", "-i", mix, "-f", "lavfi", "-i", speech, "-f", "lavfi", "-i", game,
               "-map", "0", "-map", "1", "-map", "2", "-c:a", "aac", "-b:a", "96k"]
    for index, title in enumerate(titles):
        command += [f"-metadata:s:a:{index}", f"title={title}"]
    subprocess.run(command + [str(path)], check=True)
    return path


def snapshot(folder: Path) -> dict[str, tuple[int, int, str]]:
    found = {}
    for item in sorted(folder.rglob("*")):
        stat = item.stat()
        digest = hashlib.sha256(item.read_bytes()).hexdigest() if item.is_file() else "folder"
        found[str(item.relative_to(folder))] = (stat.st_size if item.is_file() else 0, stat.st_mtime_ns, digest)
    return found


class IdentityTests(unittest.TestCase):
    def test_one_read_gives_the_inbox_sample_hash_and_the_full_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            for size in (10, 64 * 1024, 200_001, 3 * 1024 * 1024 + 17):
                path = Path(temp) / f"file-{size}.bin"
                data = os.urandom(size)
                path.write_bytes(data)
                for chunk in (1, 4096, 1024 * 1024):
                    identity = recording_identity.StreamingIdentity(size)
                    for start in range(0, size, chunk):
                        identity.update(data[start:start + chunk])
                    sampled, full = identity.finish()
                    self.assertEqual(sampled, sampled_sha256_file(path))
                    self.assertEqual(full, hashlib.sha256(data).hexdigest())

    def test_a_file_not_read_whole_is_refused(self) -> None:
        identity = recording_identity.StreamingIdentity(100)
        identity.update(b"x" * 99)
        with self.assertRaises(RuntimeError):
            identity.finish()


class GameRoleTests(unittest.TestCase):
    def test_game_audio_is_never_narration(self) -> None:
        self.assertEqual(voice_track.parse_track_roles({"3": "game"}), {2: voice_track.ROLE_NEVER})
        self.assertEqual(voice_track.parse_game_tracks({"3": "game", "2": "narration"}), {2})
        # Detection: a game track with the clearest speech is still never chosen as narration.
        activities = {ordinal: voice_track.TrackActivity(ordinal=ordinal, duration_seconds=60, silent=False,
                                                         active_ratio=0.2, burst_seconds=20,
                                                         intervals=[(1.0, 3.0), (10.0, 12.0)])
                      for ordinal in range(3)}
        probes = {2: voice_track.TrackProbe(ordinal=2, confident_words=300, probed_seconds=60)}
        decision = voice_track.decide_with_roles(activities, probes, {0: "", 1: "", 2: ""},
                                                 setting_roles=voice_track.parse_track_roles({"3": "game"}))
        self.assertNotEqual(decision.get("selected_ordinal"), 2)

    def test_the_game_track_comes_from_its_name_then_the_setting_then_what_is_left(self) -> None:
        titles = {0: "T1 - Full Mix", 1: "T2 - Narration", 2: "T3 - Game"}
        self.assertEqual(voice_track.game_audio_track(titles), (2, voice_track.DECIDED_BY_NAME))
        plain = {0: "", 1: "", 2: ""}
        self.assertEqual(voice_track.game_audio_track(plain, setting_value={"1": "game"}),
                         (0, voice_track.DECIDED_BY_SETTING))
        three = {0: "Full mix", 1: "", 2: ""}
        self.assertEqual(voice_track.game_audio_track(three, narration_ordinal=1), (2, voice_track.DECIDED_BY_AUTO))
        game, why = voice_track.game_audio_track(plain)
        self.assertIsNone(game)
        self.assertIn("more than one", why)

    def test_the_settings_panel_and_the_backend_keep_the_game_choice(self) -> None:
        from media_manglers_workbench.track_roles import format_roles, parse_roles

        self.assertEqual(parse_roles("2=narration,3=game"), {2: "narration", 3: "game"})
        self.assertEqual(format_roles({2: "narration", 3: "game", 4: "auto"}), "2=narration,3=game")
        script = (Path(__file__).resolve().parents[1] / "Video Mangler.ps1").read_text(encoding="utf-8")
        self.assertIn('if ($role -eq "game") { $role = "never" }', script)


class TimelineTests(unittest.TestCase):
    def test_a_long_quiet_stretch_on_the_game_track_is_idle(self) -> None:
        levels = [-20.0] * 300 + [-80.0] * 120 + [-20.0] * 180
        timeline = activity_timeline.game_audio_timeline(levels, game_track=2)
        self.assertEqual(timeline.status, "measured")
        self.assertEqual(timeline.idle_stretches, [(300, 420)])
        self.assertEqual(timeline.idle_seconds, 120)
        self.assertAlmostEqual(timeline.idle_share, 0.2)
        self.assertEqual(timeline.active_stretches, [(0, 300), (420, 600)])

    def test_a_short_pause_is_driving_not_idle(self) -> None:
        levels = [-20.0] * 100 + [-80.0] * 40 + [-20.0] * 100
        self.assertEqual(activity_timeline.game_audio_timeline(levels).idle_seconds, 0)

    def test_the_editor_uses_the_shared_span_helper(self) -> None:
        from media_manglers.core.race_video import analysis

        # 226: the editor's spike finder takes the shared helper under its own name.
        self.assertIs(analysis.spans, activity_timeline.spans)

    def test_jump_to_speech_stretches_are_the_shared_helper(self) -> None:
        # 226: moved into the activity timeline for the editor; the raw bin's name still works.
        self.assertIs(raw_bin_library.speech_stretches, activity_timeline.speech_stretches)
        self.assertEqual((raw_bin_library.SPEECH_MERGE_SECONDS, raw_bin_library.SPEECH_MIN_SECONDS), (10.0, 2.0))
        speech = [(1.0, 2.0), (5.04, 6.0), (30.0, 31.0), (40.0, 41.5), (100.0, 101.0)]
        self.assertEqual(activity_timeline.speech_stretches(speech), [[1.0, 6.0], [30.0, 41.5]])
        self.assertEqual(activity_timeline.speech_stretches(speech, gap=2.0, shortest=1.0),
                         [[1.0, 2.0], [30.0, 31.0], [40.0, 41.5], [100.0, 101.0]])


class GuessTests(unittest.TestCase):
    def test_the_four_guesses(self) -> None:
        self.assertEqual(raw_bin_library.decide_guess(10, None, None).guess, raw_bin_library.GUESS_EMPTY)
        self.assertEqual(raw_bin_library.decide_guess(5_000_000, 1.0, None).guess, raw_bin_library.GUESS_EMPTY)
        keep = raw_bin_library.decide_guess(5_000_000, 600, {
            "status": "selected", "selected_ordinal": 1,
            "track_activity": {"2": {"active_seconds": 125.0}}, "track_probes": {}, "track_roles": {}})
        self.assertEqual((keep.guess, keep.narration_track, keep.speech_seconds),
                         (raw_bin_library.GUESS_KEEP, 2, 125.0))
        nothing = raw_bin_library.decide_guess(5_000_000, 600, {
            "status": "no_narration_found", "selected_ordinal": None, "track_probes": {"3": {"own_words": 4}},
            "track_roles": {"2": "narration", "3": "never"}})
        self.assertEqual(nothing.guess, raw_bin_library.GUESS_NOTHING)
        wrong_track = raw_bin_library.decide_guess(5_000_000, 600, {
            "status": "no_narration_found", "selected_ordinal": None, "track_probes": {"3": {"own_words": 160}},
            "track_roles": {"2": "narration", "3": "never"}})
        self.assertEqual((wrong_track.guess, wrong_track.other_speech_track), (raw_bin_library.GUESS_CHECK, 3))
        unsure = raw_bin_library.decide_guess(5_000_000, 600, {"status": "uncertain", "explanation": "close call"})
        self.assertEqual(unsure.guess, raw_bin_library.GUESS_CHECK)
        broken = raw_bin_library.decide_guess(5_000_000, None, None, error="bad header")
        self.assertEqual(broken.guess, raw_bin_library.GUESS_CHECK)


class StorageRuleTests(unittest.TestCase):
    def test_nothing_is_written_inside_a_recordings_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            watched = Path(temp) / "raw"
            watched.mkdir()
            problem = user_folders.recordings_drive_problem(watched / "out", "cache folder", [str(watched)])
            self.assertIn("read-only", problem)
            self.assertEqual(user_folders.recordings_drive_problem(Path(temp) / "elsewhere", "cache folder",
                                                                   [str(watched)]), "")

    def test_a_whole_recordings_drive_is_refused_unless_it_is_the_system_drive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            watched, other = Path(temp) / "raw", Path(temp) / "kept"
            watched.mkdir()
            other.mkdir()
            with mock.patch.object(user_folders, "_system_volume", return_value=-1):
                self.assertIn("read-only", user_folders.recordings_drive_problem(other, "output folder", [str(watched)]))
            self.assertEqual(user_folders.recordings_drive_problem(other, "output folder", [str(watched)]), "")

    def test_a_backend_run_outside_the_app_reads_the_saved_recordings_folders(self) -> None:
        # Review S8: with no word from the Workbench, the rule uses the saved setting.
        with tempfile.TemporaryDirectory() as temp:
            appdata = Path(temp) / "appdata"
            settings = appdata / "MediaManglers" / "workbench" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps({"settings": {"review_source_folders": str(Path(temp) / "raw")}}),
                                encoding="utf-8")
            environment = {key: value for key, value in os.environ.items()
                           if key != user_folders.RECORDINGS_FOLDERS_ENV}
            environment["MEDIA_MANGLERS_WORKBENCH_APPDATA"] = str(appdata)
            with mock.patch.dict(os.environ, environment, clear=True):
                self.assertEqual(user_folders.recordings_folders(), [str(Path(temp) / "raw")])
                self.assertIn("read-only", user_folders.temporary_folder_problem(Path(temp) / "raw" / "out"))
            with mock.patch.dict(os.environ, {user_folders.RECORDINGS_FOLDERS_ENV: ""}):
                self.assertEqual(user_folders.recordings_folders(), [], "the app's word wins, even none")

    def test_the_output_folder_rule_includes_the_recordings_drive(self) -> None:
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {}):
            user_folders.set_recordings_folders([temp])
            self.assertIn("read-only", user_folders.temporary_folder_problem(Path(temp) / "out"))

    def test_a_chosen_cache_folder_gets_its_own_subfolder_and_clear_touches_nothing_else(self) -> None:
        # Review B2: pointing the cache at a folder that holds other files must never delete them.
        with tempfile.TemporaryDirectory() as temp:
            chosen = Path(temp) / "my videos"
            chosen.mkdir()
            mine = chosen / "kept-video.mkv"
            mine.write_bytes(b"x" * 5000)
            os.utime(mine, (1, 1))  # older than anything the cache makes
            root = app_cache.cache_root(str(chosen))
            self.assertEqual(root, chosen / app_cache.CHOSEN_FOLDER_SUBFOLDER)
            app_cache.put_json(root, "levels", "one", {"values": "x" * 1000})
            app_cache.enforce_cap(root, 0)
            app_cache.clear(root)
            self.assertTrue(mine.exists())

    def test_the_cache_keeps_to_its_cap_and_clears(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "cache"
            for index in range(5):
                path = app_cache.put_json(root, "levels", f"item-{index}", {"values": "x" * 1000})
                os.utime(path, (1000 + index, 1000 + index))
            app_cache.get_json(root, "levels", "item-0")  # used just now: kept
            freed = app_cache.enforce_cap(root, 3 * 1100)
            self.assertGreater(freed, 0)
            self.assertIsNotNone(app_cache.get_json(root, "levels", "item-0"))
            self.assertIsNone(app_cache.get_json(root, "levels", "item-1"))
            self.assertGreater(app_cache.clear(root), 0)
            self.assertEqual(app_cache.size_bytes(root), 0)


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg is required")
class ScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.raw = self.root / "raw"
        self.library = self.root / "library"
        self.cache = self.root / "cache"
        self.environment = mock.patch.dict(os.environ, {})
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temp.cleanup()

    def _scan(self, hearing: HearingTranscriber | None = None, folders: list[str] | None = None, **extra) -> dict:
        options = raw_bin_library.ScanOptions(
            folders=folders or [str(self.raw)], ffmpeg=FFMPEG, ffprobe=FFPROBE,
            transcriber=hearing or HearingTranscriber({2}), library_root=str(self.library),
            cache_folder=str(self.cache), stable_after_seconds=0, **extra)
        return raw_bin_library.scan(options)

    def _rows(self) -> list[dict]:
        connection = raw_bin_library.connect(self.library)
        try:
            return raw_bin_library.list_recordings(connection)
        finally:
            connection.close()

    def test_each_file_is_read_once_and_reopening_reads_nothing(self) -> None:
        recording = make_recording(self.raw / "session.mkv")
        first = self._scan()
        self.assertEqual(first["status"], "completed")
        self.assertEqual(first["files_read"], 1)
        self.assertEqual(first["bytes_read"], recording.stat().st_size, "one front-to-back read, whole")
        row = self._rows()[0]
        self.assertEqual(row["guess"], raw_bin_library.GUESS_KEEP)
        self.assertEqual(row["narration_track"], 2)
        self.assertGreater(row["speech_seconds"], 20)
        self.assertTrue(row["speech_stretches"], "jump-to-speech stretches are kept")
        self.assertEqual(row["game_track"], 3)
        self.assertEqual(row["idle_status"], "measured")
        self.assertAlmostEqual(row["idle_seconds"], 70, delta=6)
        self.assertIsNotNone(app_cache.get_json(app_cache.cache_root(str(self.cache)), "levels", row["content_sha256"]))

        again = self._scan()
        self.assertEqual((again["files_read"], again["unchanged"], again["bytes_read"]), (0, 1, 0))

    def test_264_the_scan_keeps_every_tracks_moments_and_its_guess_and_stretches_do_not_change(self) -> None:
        from media_manglers.core import speech_facts

        recording = make_recording(self.raw / "session.mkv")
        self._scan()
        row = self._rows()[0]
        self.assertEqual(row["guess"], raw_bin_library.GUESS_KEEP, "Keep likely is worked out as before")
        measure = speech_facts.known_measure(recording, root=self.library)
        self.assertEqual(measure.measured_by, "raw_bin_scan")
        self.assertEqual(sorted(measure.tracks), [1, 2, 3])
        self.assertGreater(len(measure.tracks[2]["moments"]), 30)
        self.assertEqual(measure.tracks[2]["listened"], 1)
        points = speech_facts.jump_points(recording, root=self.library)
        self.assertEqual((points.track, points.decided_by), (2, "track_name"))
        self.assertFalse(points.needs_read or points.needs_listen)
        self.assertGreater(len(points.stretches), len(row["speech_stretches"]) * 5, "the finer jumps of Q2")
        answer = speech_facts.narration_answer(recording, root=self.library)
        self.assertTrue(answer.final, "a run on this recording need not listen")
        self.assertEqual(answer.detection["selected_ordinal"], 1)

    def test_264_what_a_copy_held_before_its_scan_is_shared_afterwards(self) -> None:
        from media_manglers.core import speech_facts

        recording = make_recording(self.raw / "session.mkv")
        speech_facts.confirm_track(recording, 3, by=speech_facts.ANSWERED_ON_BUGS, root=self.library)
        self._scan()
        self.assertEqual(len(self._rows()), 1, "the copy a list registered is this recording")
        self.assertEqual(speech_facts.confirmed_track(recording, root=self.library), 3)
        twin = self.raw / "twin.mkv"
        shutil.copy2(recording, twin)
        self._scan()
        self.assertEqual(speech_facts.confirmed_track(twin, root=self.library), 3, "exact copies share your answer")
        self.assertIsNotNone(speech_facts.known_measure(twin, root=self.library))

    def test_264_a_stand_in_a_scan_finds_is_a_known_recording_keeps_your_answer(self) -> None:
        from media_manglers.core import speech_facts

        recording = make_recording(self.raw / "session.mkv")
        self._scan()
        moved = self.raw / "renamed.mkv"
        recording.rename(moved)
        speech_facts.confirm_track(moved, 3, by=speech_facts.ANSWERED_ON_BUGS, root=self.library)
        self._scan()
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(speech_facts.confirmed_track(moved, root=self.library), 3)
        self.assertIsNotNone(speech_facts.known_measure(moved, root=self.library), "the measure follows its content")

    def test_264_a_recording_replaced_at_its_path_inherits_nothing(self) -> None:
        from media_manglers.core import speech_facts

        recording = make_recording(self.raw / "session.mkv")
        self._scan()
        speech_facts.confirm_track(recording, 3, by=speech_facts.ANSWERED_ON_BUGS, root=self.library)
        make_recording(self.raw / "session.mkv", seconds=200)
        self.assertIsNone(speech_facts.confirmed_track(recording, root=self.library))
        self._scan()
        self.assertIsNone(speech_facts.confirmed_track(recording, root=self.library))
        self.assertEqual(speech_facts.known_measure(recording, root=self.library).duration_seconds // 10, 20)

    def test_264_a_failure_storing_the_facts_never_fails_the_scan(self) -> None:
        from media_manglers.core import speech_facts

        recording = make_recording(self.raw / "session.mkv")
        with mock.patch.object(speech_facts, "write_measure", side_effect=sqlite3.OperationalError("disk full")):
            summary = self._scan()
        self.assertEqual((summary["status"], summary["files_read"]), ("completed", 1))
        self.assertEqual(self._rows()[0]["narration_track"], 2)
        self.assertIsNone(speech_facts.known_measure(recording, root=self.library))

    def test_tags_follow_a_renamed_or_moved_recording_and_a_scan_never_changes_them(self) -> None:
        recording = make_recording(self.raw / "session.mkv")
        self._scan()
        connection = raw_bin_library.connect(self.library)
        recording_id = raw_bin_library.list_recordings(connection)[0]["recording_id"]
        raw_bin_library.set_decision(connection, [recording_id], raw_bin_library.DECISION_KEEP)
        raw_bin_library.set_label(connection, [recording_id], "YouTube", True)
        raw_bin_library.set_label(connection, [recording_id], "Race night", True)
        connection.close()

        moved = self.raw / "kept" / "renamed.mkv"
        moved.parent.mkdir()
        recording.rename(moved)
        self._scan()
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["recording_id"], recording_id)
        self.assertEqual(rows[0]["decision"], raw_bin_library.DECISION_KEEP)
        self.assertEqual(sorted(rows[0]["labels"]), ["Race night", "YouTube"])
        self.assertEqual(Path(rows[0]["path"]), moved)
        self.assertFalse(rows[0]["missing"])

    def test_adding_one_file_reads_only_that_file_and_two_copies_stay_two_entries(self) -> None:
        recording = make_recording(self.raw / "a.mkv")
        self._scan()
        shutil.copy2(recording, self.raw / "copy of a.mkv")
        result = self._scan()
        self.assertEqual((result["files_read"], result["unchanged"]), (1, 1))
        rows = self._rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["duplicate_of"], rows[0]["recording_id"])

    def test_a_missing_recording_keeps_its_tags_and_an_unreachable_folder_marks_nothing(self) -> None:
        recording = make_recording(self.raw / "a.mkv")
        self._scan()
        connection = raw_bin_library.connect(self.library)
        raw_bin_library.set_decision(connection, [1], raw_bin_library.DECISION_DELETE)
        connection.close()

        away = self.root / "unplugged"
        self.raw.rename(away)
        stopped = self._scan()
        self.assertEqual(stopped["status"], "drive_not_reachable")
        self.assertFalse(self._rows()[0]["missing"], "an unreachable drive marks nothing Missing")

        away.rename(self.raw)
        recording.unlink()
        self._scan()
        row = self._rows()[0]
        self.assertTrue(row["missing"])
        self.assertEqual(row["decision"], raw_bin_library.DECISION_DELETE)

    def test_speech_only_on_the_wrong_track_is_check(self) -> None:
        make_recording(self.raw / "misrouted.mkv", narration=False)
        self._scan(HearingTranscriber({3}, WORDS * 2))
        row = self._rows()[0]
        self.assertEqual(row["guess"], raw_bin_library.GUESS_CHECK)
        self.assertEqual(row["other_speech_track"], 3)

    def test_an_interrupted_scan_loses_only_the_recording_in_progress(self) -> None:
        make_recording(self.raw / "a.mkv")
        make_recording(self.raw / "b.mkv", seconds=90)

        class PowerCut(BaseException):
            pass

        hearing = HearingTranscriber({2})
        recordings_heard: set[Path] = set()

        def cut_on_second(path: Path) -> list[dict]:
            # Each recording is listened to in its own work folder; the power goes during the second.
            recordings_heard.add(Path(path).parent)
            if len(recordings_heard) > 1:
                raise PowerCut()
            return hearing(path)

        with self.assertRaises(PowerCut):
            self._scan(cut_on_second)
        self.assertEqual(len(self._rows()), 1, "the finished recording was kept")
        resumed = self._scan()
        self.assertEqual((resumed["files_read"], resumed["unchanged"]), (1, 1))
        self.assertEqual(len(self._rows()), 2)

    def test_the_app_only_marks_nothing_on_the_recordings_folder_changes(self) -> None:
        make_recording(self.raw / "a.mkv")
        (self.raw / "notes").mkdir()
        before = snapshot(self.raw)
        self._scan()
        connection = raw_bin_library.connect(self.library)
        rows = raw_bin_library.list_recordings(connection)
        raw_bin_library.set_decision(connection, [rows[0]["recording_id"]], raw_bin_library.DECISION_DELETE)
        raw_bin_library.set_label(connection, [rows[0]["recording_id"]], "B-roll", True)
        rows = raw_bin_library.list_recordings(connection)
        connection.close()
        raw_bin_library.export(rows, self.root / "exports" / "view.csv", recordings_folders=[str(self.raw)])
        raw_bin_library.export(rows, self.root / "exports" / "view.json", recordings_folders=[str(self.raw)])
        app_cache.clear(app_cache.cache_root(str(self.cache)))
        with self.assertRaises(ValueError):
            raw_bin_library.export(rows, self.raw / "view.csv", recordings_folders=[str(self.raw)])
        self.assertEqual(snapshot(self.raw), before)
        self.assertEqual(self._rows()[0]["decision"], raw_bin_library.DECISION_DELETE, "Clear cache keeps tags")

    def test_the_export_matches_the_screen(self) -> None:
        make_recording(self.raw / "a.mkv")
        self._scan()
        rows = self._rows()
        csv_path = raw_bin_library.export(rows, self.root / "view.csv")
        json_path = raw_bin_library.export(rows, self.root / "view.json")
        exported = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(exported[0]["guess"], "Keep likely")
        self.assertEqual(exported[0]["name"], "a.mkv")
        self.assertIn("Keep likely", csv_path.read_text(encoding="utf-8"))

    def test_a_recording_that_could_not_be_read_is_tried_again_next_scan(self) -> None:
        # Review B1: a passing problem (Whisper failing to load, say) must not mark a recording for good.
        make_recording(self.raw / "a.mkv")

        def broken(_path: Path) -> list[dict]:
            raise RuntimeError("synthetic speech model failure")

        first = self._scan(broken)
        self.assertEqual(first["failed"], 1)
        self.assertEqual(self._rows()[0]["guess"], raw_bin_library.GUESS_CHECK)
        again = self._scan()
        self.assertEqual((again["files_read"], again["unchanged"]), (1, 0))
        self.assertEqual(self._rows()[0]["guess"], raw_bin_library.GUESS_KEEP, self._rows()[0]["guess_reason"])
        self.assertIsNone(self._rows()[0]["scan_error"])

    def test_a_mov_is_copied_once_to_scratch_hashed_on_the_way_and_the_copy_is_removed(self) -> None:
        # A MOV keeps its index at the end, so FFmpeg cannot decode it from a stream: plan 1b.
        from media_manglers.core.scratch import scratch_root

        recording = make_recording(self.raw / "phone.mov")
        result = self._scan()
        self.assertEqual(result["bytes_read"], recording.stat().st_size, "read once, by the copy")
        self.assertEqual(self._rows()[0]["guess"], raw_bin_library.GUESS_KEEP, self._rows()[0]["guess_reason"])
        self.assertEqual(list(scratch_root().glob("media_manglers_raw_bin_*")), [], "the copy is gone")

    def test_a_moved_recording_is_known_again_without_decoding_or_listening(self) -> None:
        # Review S4: a moved file (a drive letter change, say) gets one hash-only read; its guess stays.
        recording = make_recording(self.raw / "a.mkv")
        self._scan()
        moved = self.raw / "renamed" / "b.mkv"
        moved.parent.mkdir()
        recording.rename(moved)
        listening = HearingTranscriber({2})
        result = self._scan(listening)
        self.assertEqual(result.get("reattached"), 1)
        self.assertEqual(listening.heard, [], "nothing was listened to again")
        self.assertLessEqual(result["bytes_read"], moved.stat().st_size + 3 * 64 * 1024)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(Path(rows[0]["path"]), moved)
        self.assertEqual(rows[0]["guess"], raw_bin_library.GUESS_KEEP)

    def test_known_recordings_not_looked_at_this_time_are_not_marked_missing(self) -> None:
        # Review S2: a recording still being written, or one the operator skipped, is still there.
        recording = make_recording(self.raw / "a.mkv")
        self._scan()
        os.utime(recording)  # changed just now: it may still be recording
        options = raw_bin_library.ScanOptions(folders=[str(self.raw)], ffmpeg=FFMPEG, ffprobe=FFPROBE,
                                              transcriber=HearingTranscriber({2}), library_root=str(self.library),
                                              cache_folder=str(self.cache), stable_after_seconds=3600)
        result = raw_bin_library.scan(options)
        self.assertEqual(result["in_use"], 1)
        self.assertFalse(self._rows()[0]["missing"])

    def test_a_folder_walk_with_a_problem_marks_nothing_missing(self) -> None:
        # Review S1: a walk that could not finish must not turn the files it did not reach Missing.
        recording = make_recording(self.raw / "a.mkv")
        self._scan()
        recording.unlink()
        with mock.patch.object(raw_bin_library, "iter_media_files",
                               return_value=([], [{"path": str(self.raw), "error": "synthetic read error"}])):
            result = self._scan()
        self.assertEqual(result["missing_marked"], 0)
        self.assertFalse(self._rows()[0]["missing"])

    def test_scratch_left_by_a_stopped_scan_is_removed(self) -> None:
        # Review S5: decoded audio from a scan that was stopped hard does not pile up.
        from media_manglers.core.scratch import scratch_root

        leftover = scratch_root() / "media_manglers_raw_bin_leftover-test"
        leftover.mkdir(parents=True, exist_ok=True)
        (leftover / "track-0.wav").write_bytes(b"x" * 1000)
        make_recording(self.raw / "a.mkv")
        self._scan()
        self.assertFalse(leftover.exists())

    def test_the_work_folder_of_a_scan_still_running_is_left_alone(self) -> None:
        # The parallel suite (220): every scan removed every raw bin work folder at its start, so a
        # scan running alongside lost its decoded audio mid-recording.
        from media_manglers.core.scratch import scratch_root

        busy = scratch_root() / "media_manglers_raw_bin_busy-test"
        busy.mkdir(parents=True, exist_ok=True)
        try:
            with raw_bin_library._work_in_use(busy):
                (busy / "track-0.wav").write_bytes(b"x" * 1000)
                make_recording(self.raw / "a.mkv")
                self._scan()
                self.assertTrue((busy / "track-0.wav").exists(), "a work folder in use is kept")
            self._scan()  # nothing new to read, but the leftover pass runs again
            self.assertFalse(busy.exists(), "once its scan has gone, the folder is a leftover")
        finally:
            shutil.rmtree(busy, ignore_errors=True)

    def test_one_backup_a_day_through_sqlite_and_the_newest_are_kept(self) -> None:
        from datetime import date, timedelta

        connection = raw_bin_library.connect(self.library, backup=False)
        for offset in range(16):
            raw_bin_library.daily_backup(connection, self.library, today=date(2026, 10, 1) + timedelta(days=offset))
        self.assertIsNone(raw_bin_library.daily_backup(connection, self.library, today=date(2026, 10, 16)))
        connection.close()
        backups = sorted((self.library / "backups").glob("*.sqlite"))
        self.assertEqual(len(backups), raw_bin_library.BACKUP_KEEP)
        self.assertTrue(backups[-1].name.endswith("2026-10-16.sqlite"))


if __name__ == "__main__":
    unittest.main()
