"""264 (Wave C1): speech facts in the library and the one narration-track rule.

Each recording's measure and your answer belong to its content, so exact copies share them; until the content is known
they belong to the copy, and only while its file keeps the size and time they were made on. A sampled hash shares
nothing. No test here reads a recording: the facts are written the way the helpers write them, from a detection's result.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core import raw_bin_library, recording_records, voice_track  # noqa: E402

SOURCE = Path(__file__).resolve().parents[1] / "src"
HASH_A = "a" * 64
HASH_B = "b" * 64
FOUR_TRACKS = {0: "Track1", 1: "Track2", 2: "Track3", 3: "Track4"}


def facts():
    # Asked inside each test, so on code without it each test fails by itself rather than the file failing to load.
    from media_manglers.core import speech_facts

    return speech_facts


def detection(selected: int | None = 1, *, status: str = "selected", decided_by: str = "auto", moments=None, rule=None) -> dict:
    """A detection's result as ``detect_voice_track(details=True)`` gives it."""

    moments = moments if moments is not None else {2: [[10.0, 12.5], [20.0, 21.0]], 3: [[30.0, 31.0]]}
    return {
        "source_path": "x", "audio_track_count": 4, "duration_seconds": 100.0,
        "rule_version": voice_track.VOICE_RULE_VERSION if rule is None else rule,
        "status": status, "selected_ordinal": selected, "confidence": 0.9, "decided_by": decided_by,
        "decided_by_text": voice_track.DECIDED_BY_TEXT.get(decided_by, ""), "explanation": "Auto-detected: heard it.",
        "track_roles": {"1": "auto", "2": "auto", "3": "auto", "4": "auto"},
        "tracks": [{"ordinal": 1, "track_number": 2, "title": "Track2", "silent": False, "reason": "19 words",
                    "sample_text": "THE WORDS HEARD"}],
        "track_activity": {str(number): {"silent": False, "active_seconds": 3.0, "active_ratio": 0.1, "noise_floor_dbfs": -70.0,
                                         "peak_dbfs": -10.0, "intervals": [[1.0, 2.0]], "moments": values,
                                         "level_swing_db": 25.0, "loud_share": 0.1} for number, values in moments.items()},
        "track_probes": {"2": {"confident_words": 19, "spotter_words": 0, "own_words": 19, "probed_seconds": 20.0}},
        "track_titles": {str(ordinal + 1): title for ordinal, title in FOUR_TRACKS.items()},
    }


class LibraryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = self.root / "library"
        patcher = mock.patch.dict(os.environ, {recording_records.LIBRARY_ROOT_ENV: str(self.library)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.temp.cleanup)

    def _file(self, name: str = "rec.mkv", text: str = "some bytes") -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def _scanned(self, path: Path, content: str, *, narration: int | None = None, roles: str = "", titles=None,
                 error: str | None = None) -> int:
        """A copy as a raw bin scan leaves it, with the file's size and time."""

        stat = path.stat()
        connection = recording_records.connect(self.library, backup=False)
        try:
            with connection:
                recording_id = int(connection.execute(
                    "INSERT INTO recordings(first_seen_utc, content_sha256, size_bytes, narration_track, rules_roles, "
                    "track_titles_json, scan_error, audio_tracks) VALUES ('2026-01-01', ?, ?, ?, ?, ?, ?, 4)",
                    (content, int(stat.st_size), narration, roles, json.dumps(titles or {}), error)).lastrowid)
                connection.execute(
                    "INSERT INTO locations(recording_id, path, path_key, root_key, size_bytes, modified_ns, is_current, missing, "
                    "first_seen_utc, last_seen_utc) VALUES (?, ?, ?, '', ?, ?, 1, 0, 'x', 'x')",
                    (recording_id, str(path), recording_records.path_key(path), int(stat.st_size), int(stat.st_mtime_ns)))
        finally:
            connection.close()
        return recording_id

    def _rows(self, sql: str, *values) -> list[sqlite3.Row]:
        connection = recording_records.connect(self.library, backup=False)
        try:
            return connection.execute(sql, values).fetchall()
        finally:
            connection.close()

    def _touch(self, path: Path) -> None:
        later = time.time() + 100
        os.utime(path, (later, later))


class StructureTests(LibraryTestCase):
    def test_structure_six_adds_the_four_tables_and_they_are_personal(self) -> None:
        recording_records.connect(self.library, backup=False).close()
        self.assertGreaterEqual(recording_records.SCHEMA_VERSION, 6)  # 7 since Wave C2 (242)
        for table in ("voice_measures", "voice_measure_tracks", "voice_decisions", "narration_answers"):
            with self.subTest(table=table):
                self.assertEqual(recording_records.TABLE_PRIVACY[table], recording_records.PERSONAL)
                self.assertIn(table, recording_records.EXPECTED_STRUCTURE)
                self.assertIn(table, recording_records.KEPT_TABLES)
                self.assertTrue(self._rows(f"PRAGMA table_info({table})"))

    def test_a_library_at_structure_five_moves_up_with_a_backup_and_keeps_its_rows(self) -> None:
        connection = recording_records.connect(self.library, backup=False)
        with connection:
            connection.execute("INSERT INTO recordings(first_seen_utc, content_sha256) VALUES ('x', ?)", (HASH_A,))
            for table in ("voice_measure_tracks", "voice_decisions", "voice_measures", "narration_answers"):
                connection.execute(f"DROP TABLE {table}")
            connection.execute("UPDATE schema_metadata SET value = '5' WHERE key = 'schema_version'")
        connection.close()
        connection = recording_records.connect(self.library, backup=False)
        try:
            self.assertEqual(recording_records.stored_version(connection), recording_records.SCHEMA_VERSION)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM recordings").fetchone()[0], 1)
            step = connection.execute("SELECT from_version, to_version, backup_path FROM schema_steps ORDER BY step_id DESC").fetchone()
        finally:
            connection.close()
        self.assertEqual((step["from_version"], step["to_version"]), (5, recording_records.SCHEMA_VERSION))
        self.assertTrue(Path(step["backup_path"]).is_file(), "a whole backup is taken before the step")

    def test_only_the_new_module_names_the_new_tables(self) -> None:
        names = re.compile(r"\b(voice_measures|voice_measure_tracks|voice_decisions|narration_answers)\b")
        naming = {path.relative_to(SOURCE).as_posix() for path in SOURCE.rglob("*.py") if names.search(path.read_text(encoding="utf-8"))}
        self.assertEqual(naming, {"media_manglers/core/speech_facts.py", "media_manglers/core/recording_records.py"})


class MeasureTests(LibraryTestCase):
    def test_a_measure_is_kept_and_read_back_with_who_measured_it(self) -> None:
        path = self._file()
        self.assertTrue(facts().record_measure(path, detection(), measured_by=facts().BY_BUGS, run_id="run-1"))
        found = facts().known_measure(path)
        self.assertEqual(found.measured_by, "bug_reports")
        self.assertEqual(found.activity_rule_version, voice_track.ACTIVITY_RULE_VERSION)
        self.assertEqual(found.tracks[2]["moments"], [(10.0, 12.5), (20.0, 21.0)])
        self.assertEqual(found.tracks[2]["own_words"], 19)
        self.assertEqual(found.tracks[2]["listened"], 1)
        self.assertEqual(found.tracks[3]["listened"], 0)

    def test_the_words_heard_are_never_kept(self) -> None:
        path = self._file()
        facts().record_measure(path, detection(), measured_by=facts().BY_BUGS)
        connection = sqlite3.connect(self.library / recording_records.DATABASE_NAME)
        try:
            dumped = "\n".join(connection.iterdump())
        finally:
            connection.close()
        self.assertNotIn("THE WORDS HEARD", dumped)
        self.assertNotIn("sample_text", dumped)

    def test_a_recording_no_scan_read_gets_a_copy_of_its_own_off_the_raw_bins_list(self) -> None:
        path = self._file()
        facts().record_measure(path, detection(), measured_by=facts().BY_BUGS)
        row = self._rows("SELECT registered_by FROM locations WHERE path_key = ?", recording_records.path_key(path))[0]
        self.assertEqual(row["registered_by"], recording_records.REGISTERED_OUTSIDE)
        self.assertEqual(recording_records.list_recordings(root=self.library), [])

    def test_a_copys_measure_holds_only_while_its_file_keeps_its_size_and_time(self) -> None:
        path = self._file()
        facts().record_measure(path, detection(), measured_by=facts().BY_BUGS)
        self.assertIsNotNone(facts().known_measure(path))
        self._touch(path)
        self.assertIsNone(facts().known_measure(path), "another modified time")

    def test_a_file_saved_over_a_known_path_inherits_nothing(self) -> None:
        path = self._file()
        facts().confirm_track(path, 3, by=facts().ANSWERED_ON_BUGS)
        facts().record_measure(path, detection(), measured_by=facts().BY_BUGS)
        path.write_text("another size altogether", encoding="utf-8")
        self.assertIsNone(facts().known_measure(path))
        self.assertIsNone(facts().confirmed_track(path))

    def test_two_exact_copies_share_a_measure_and_an_answer_but_not_a_decision_or_never_use(self) -> None:
        first, second = self._file("a.mkv"), self._file("b.mkv")
        first_id, second_id = self._scanned(first, HASH_A), self._scanned(second, HASH_A)
        facts().record_measure(first, detection(), measured_by=facts().BY_BUGS)
        facts().confirm_track(first, 3, by=facts().ANSWERED_ON_BUGS)
        self.assertEqual(facts().known_measure(second).tracks[2]["moments"], [(10.0, 12.5), (20.0, 21.0)])
        self.assertEqual(facts().confirmed_track(second), 3)
        connection = recording_records.connect(self.library, backup=False)
        try:
            raw_bin_library.set_decision(connection, [first_id], raw_bin_library.DECISION_KEEP)
            decisions = {row["recording_id"]: row["decision"] for row in connection.execute("SELECT recording_id, decision FROM recordings")}
        finally:
            connection.close()
        self.assertEqual(decisions[first_id], raw_bin_library.DECISION_KEEP)
        self.assertEqual(decisions[second_id], raw_bin_library.DECISION_UNDECIDED)
        records = recording_records.Records(self.library)
        try:
            records.set_never_use(first, True, by="test")
            keys = records.never_use_keys()
        finally:
            records.close()
        self.assertIn(recording_records.path_key(first), keys)
        self.assertNotIn(recording_records.path_key(second), keys)

    def test_a_sampled_hash_match_shares_nothing(self) -> None:
        first, second = self._file("a.mkv"), self._file("b.mkv")
        facts().record_measure(first, detection(), measured_by=facts().BY_BUGS)
        facts().confirm_track(first, 3, by=facts().ANSWERED_ON_BUGS)
        connection = recording_records.connect(self.library, backup=False)
        with connection:
            connection.execute("UPDATE recordings SET sampled_sha256 = 'same'")
            stat = second.stat()
            recording_id = int(connection.execute("INSERT INTO recordings(first_seen_utc, sampled_sha256, size_bytes) "
                                                  "VALUES ('x', 'same', ?)", (stat.st_size,)).lastrowid)
            connection.execute("INSERT INTO locations(recording_id, path, path_key, root_key, size_bytes, modified_ns, is_current, "
                               "missing, first_seen_utc, last_seen_utc) VALUES (?, ?, ?, '', ?, ?, 1, 0, 'x', 'x')",
                               (recording_id, str(second), recording_records.path_key(second), stat.st_size, stat.st_mtime_ns))
        connection.close()
        self.assertIsNone(facts().known_measure(second))
        self.assertIsNone(facts().confirmed_track(second))

    def test_a_stand_in_a_scan_absorbs_keeps_its_facts(self) -> None:
        moved = self._file("moved.mkv")
        known_id = self._scanned(self._file("gone.mkv", "other"), HASH_A)
        facts().record_measure(moved, detection(), measured_by=facts().BY_BUGS)
        facts().confirm_track(moved, 3, by=facts().ANSWERED_ON_BUGS)
        stand_in = int(self._rows("SELECT recording_id FROM locations WHERE path_key = ?", recording_records.path_key(moved))[0][0])
        connection = recording_records.connect(self.library, backup=False)
        with connection:
            connection.execute("UPDATE locations SET recording_id = ?, registered_by = 'scan' WHERE recording_id = ?",
                               (known_id, stand_in))
            recording_records.absorb_copy(connection, stand_in, known_id, by="raw bin scan")
        connection.close()
        self.assertEqual(self._rows("SELECT content_sha256 FROM voice_measures")[0][0], HASH_A)
        self.assertEqual(self._rows("SELECT content_sha256, track FROM narration_answers")[0]["track"], 3)
        self.assertEqual(self._rows("SELECT COUNT(*) FROM recordings WHERE recording_id = ?", stand_in)[0][0], 0)

    def test_a_measure_made_before_the_hash_was_known_is_shared_once_a_scan_confirms_it(self) -> None:
        path = self._file("a.mkv")
        facts().record_measure(path, detection(), measured_by=facts().BY_BUGS)
        facts().confirm_track(path, 3, by=facts().ANSWERED_ON_BUGS)
        recording_id = int(self._rows("SELECT recording_id FROM voice_measures")[0][0])
        stat = path.stat()
        connection = recording_records.connect(self.library, backup=False)
        with connection:
            connection.execute("UPDATE recordings SET content_sha256 = ? WHERE recording_id = ?", (HASH_A, recording_id))
            connection.execute("UPDATE locations SET size_bytes = ?, modified_ns = ? WHERE recording_id = ?",
                               (stat.st_size, stat.st_mtime_ns, recording_id))
            facts().attach_content(connection, recording_id, HASH_A, size=stat.st_size, modified=stat.st_mtime_ns)
        connection.close()
        twin = self._file("b.mkv")
        self._scanned(twin, HASH_A)
        self.assertIsNotNone(facts().known_measure(twin))
        self.assertEqual(facts().confirmed_track(twin), 3)

    def test_a_library_that_cannot_be_written_never_fails_the_run(self) -> None:
        path = self._file()
        with mock.patch.object(recording_records, "connect", side_effect=sqlite3.OperationalError("database is locked")), \
                self.assertLogs("media_manglers.core.speech_facts", logging.WARNING) as logs:
            self.assertFalse(facts().record_measure(path, detection(), measured_by=facts().BY_BUGS))
            self.assertFalse(facts().confirm_track(path, 3, by=facts().ANSWERED_ON_BUGS))
        for line in logs.output:
            self.assertNotIn(path.name, line, "the log says the kind of error, never the recording")

    def test_a_measure_or_its_log_says_counts_only(self) -> None:
        path = self._file()
        with self.assertNoLogs("media_manglers.core.speech_facts", logging.INFO):
            facts().record_measure(path, detection(), measured_by=facts().BY_BUGS)


class AnswerTests(LibraryTestCase):
    def test_a_cleared_answer_stays_on_record_with_when_and_by_whom(self) -> None:
        path = self._file()
        facts().confirm_track(path, 3, by=facts().ANSWERED_ON_BUGS)
        facts().clear_track(path, by=facts().ANSWERED_ON_EDITOR)
        self.assertIsNone(facts().confirmed_track(path))
        self.assertEqual(facts().answer_for(path).state, "cleared")
        row = self._rows("SELECT track, answered_by, cleared_utc, cleared_by FROM narration_answers")[0]
        self.assertEqual((row["track"], row["answered_by"], row["cleared_by"]), (3, "bugs_page", "editor_page"))
        self.assertTrue(row["cleared_utc"])

    def test_a_new_answer_replaces_the_old_which_stays_cleared(self) -> None:
        path = self._file()
        facts().confirm_track(path, 3, by=facts().ANSWERED_ON_BUGS)
        facts().confirm_track(path, 4, by=facts().ANSWERED_IN_WIZARD)
        self.assertEqual(facts().confirmed_track(path), 4)
        self.assertEqual(len(self._rows("SELECT 1 FROM narration_answers WHERE cleared_utc IS NULL")), 1)
        self.assertEqual(len(self._rows("SELECT 1 FROM narration_answers")), 2)

    def test_the_same_answer_again_changes_nothing(self) -> None:
        path = self._file()
        facts().confirm_track(path, 3, by=facts().ANSWERED_ON_BUGS)
        facts().confirm_track(path, 3, by=facts().ANSWERED_IN_INBOX)
        self.assertEqual(len(self._rows("SELECT 1 FROM narration_answers")), 1)


class TheOneRuleTests(LibraryTestCase):
    def _answer(self, path: Path, **options):
        return facts().narration_answer(path, titles=options.pop("titles", FOUR_TRACKS), **options)

    def test_step_one_your_answer_beats_everything(self) -> None:
        path = self._file()
        facts().record_measure(path, detection(1), measured_by=facts().BY_BUGS, titles=FOUR_TRACKS)
        facts().confirm_track(path, 3, by=facts().ANSWERED_ON_BUGS)
        answer = self._answer(path, layout_answer=1, titles={**FOUR_TRACKS, 1: "Narration"})
        self.assertEqual((answer.track, answer.decided_by, answer.final), (3, "confirmed", True))
        self.assertEqual(answer.by, "bugs_page")
        self.assertEqual(answer.detection["selected_ordinal"], 2)
        self.assertEqual(answer.detection["decided_by"], "confirmed")

    def test_step_two_a_saved_layout_answer_applies_only_where_a_screen_passes_it(self) -> None:
        path = self._file()
        facts().record_measure(path, detection(1), measured_by=facts().BY_BUGS, titles=FOUR_TRACKS)
        self.assertEqual(self._answer(path, layout_answer=4).track, 4)
        self.assertEqual(self._answer(path, layout_answer=4).decided_by, "layout")
        self.assertEqual(self._answer(path).track, 2)

    def test_step_three_a_track_name_answers_without_listening_but_is_not_final_until_heard(self) -> None:
        path = self._file()
        answer = self._answer(path, titles={0: "Game", 1: "My Narration"})
        self.assertEqual((answer.track, answer.decided_by, answer.final), (2, "track_name", False))

    def test_step_three_the_setting_answers_for_a_recording_with_no_track_names(self) -> None:
        path = self._file()
        answer = self._answer(path, track_roles="3=narration")
        self.assertEqual((answer.track, answer.decided_by, answer.final), (3, "setting", False))

    def test_step_four_the_stored_pick_answers_with_the_shape_the_backend_reads(self) -> None:
        path = self._file()
        facts().record_measure(path, detection(1), measured_by=facts().BY_BUGS, titles=FOUR_TRACKS)
        answer = self._answer(path)
        self.assertEqual((answer.track, answer.decided_by, answer.final), (2, "auto", True))
        for key in ("status", "selected_ordinal", "confidence", "explanation", "decided_by", "decided_by_text", "tracks",
                    "track_roles", "rule_version", "kept_track_wavs"):
            self.assertIn(key, answer.detection)
        self.assertEqual(answer.detection["decided_by_text"], "auto-detected")
        self.assertNotIn("track_activity", answer.detection)
        self.assertNotIn("moments", json.dumps(answer.detection))
        self.assertNotIn("sample_text", json.dumps(answer.detection))

    def test_step_five_nothing_known_means_the_caller_listens(self) -> None:
        answer = self._answer(self._file())
        self.assertEqual((answer.track, answer.final), (None, False))

    def test_no_narration_is_a_stored_answer_too(self) -> None:
        path = self._file()
        facts().record_measure(path, detection(None, status="no_narration_found"), measured_by=facts().BY_BUGS, titles=FOUR_TRACKS)
        answer = self._answer(path)
        self.assertEqual((answer.track, answer.status, answer.final), (None, "no_narration_found", True))

    def test_uncertain_is_never_reused(self) -> None:
        path = self._file()
        facts().record_measure(path, detection(None, status="uncertain"), measured_by=facts().BY_BUGS, titles=FOUR_TRACKS)
        self.assertFalse(self._answer(path).final)

    def test_a_stale_rule_makes_a_decision_stale_but_your_answer_never(self) -> None:
        path = self._file()
        facts().record_measure(path, detection(1, rule=voice_track.VOICE_RULE_VERSION - 1), measured_by=facts().BY_BUGS, titles=FOUR_TRACKS)
        self.assertFalse(self._answer(path).final, "heard again, as the package check does")
        facts().confirm_track(path, 3, by=facts().ANSWERED_ON_BUGS)
        self.assertEqual(self._answer(path).track, 3)

    def test_changed_track_roles_make_a_decision_stale_only_for_a_recording_with_no_names(self) -> None:
        path = self._file()
        facts().record_measure(path, detection(1), measured_by=facts().BY_BUGS, titles=FOUR_TRACKS)
        self.assertFalse(self._answer(path, track_roles="4=never").final)
        named = self._file("named.mkv")
        titles = {0: "Game", 1: "Narration"}
        facts().record_measure(named, detection(1, decided_by="track_name"), measured_by=facts().BY_BUGS, titles=titles)
        self.assertTrue(self._answer(named, titles=titles, track_roles="4=never").final)

    def test_the_tie_breaker_rule_for_reusing_a_stored_result(self) -> None:
        path = self._file()
        facts().record_measure(path, detection(1), measured_by=facts().BY_BUGS, titles=FOUR_TRACKS)
        self.assertTrue(self._answer(path, remembered=[3]).final, "made with no remembered pick")
        other = self._file("other.mkv")
        facts().record_measure(other, detection(1), measured_by=facts().BY_BUGS, titles=FOUR_TRACKS, preferred=[2])
        self.assertTrue(self._answer(other, remembered=[2]).final, "the same pick")
        self.assertTrue(self._answer(other, remembered=[1]).final, "it already chose the remembered track")
        self.assertFalse(self._answer(other, remembered=[3]).final, "another pick could change the answer")
        self.assertFalse(self._answer(other).final, "a pick played a part; this one has none")

    def test_track_one_as_a_remembered_pick_is_a_pick_like_any_other(self) -> None:
        self.assertEqual(facts().preferred_key([0]), "0")
        self.assertEqual(facts().preferred_key([]), "")
        path = self._file()
        facts().record_measure(path, detection(0, moments={1: [[1.0, 2.0]]}), measured_by=facts().BY_BUGS, titles=FOUR_TRACKS, preferred=[0])
        row = self._rows("SELECT preferred_key, decided_by FROM voice_decisions")[0]
        self.assertEqual((row["preferred_key"], row["decided_by"]), ("0", "auto_tie_break"))

    def test_an_old_raw_bin_row_works_on_day_one_with_nothing_moved(self) -> None:
        path = self._file()
        self._scanned(path, HASH_A, narration=2)
        answer = self._answer(path)
        self.assertEqual((answer.track, answer.decided_by, answer.final), (2, "auto", True))
        self.assertEqual(answer.detection["selected_ordinal"], 1)
        self.assertEqual(self._rows("SELECT COUNT(*) FROM voice_decisions")[0][0], 0, "nothing was copied")

    def test_an_old_raw_bin_row_is_not_trusted_when_things_changed(self) -> None:
        changed = self._file("changed.mkv")
        self._scanned(changed, HASH_A, narration=2)
        self._touch(changed)
        self.assertFalse(self._answer(changed).final, "the file changed")
        failed = self._file("failed.mkv")
        self._scanned(failed, HASH_B, narration=2, error="could not read")
        self.assertFalse(self._answer(failed).final, "the scan failed")
        roles = self._file("roles.mkv")
        self._scanned(roles, "c" * 64, narration=2, roles="3=game")
        self.assertFalse(self._answer(roles).final, "the Track roles it used have changed")
        self.assertTrue(self._answer(roles, track_roles="3=game").final)
        never = self._file("never.mkv")
        self._scanned(never, "d" * 64, narration=2)
        self.assertFalse(self._answer(never, track_roles="2=never").final, "the setting says it is never narration")

    def test_a_new_detection_rule_makes_an_old_raw_bin_row_stale_too(self) -> None:
        path = self._file()
        self._scanned(path, HASH_A, narration=2)
        with mock.patch.object(voice_track, "VOICE_RULE_VERSION", voice_track.VOICE_RULE_VERSION + 1):
            self.assertFalse(self._answer(path).final)

    def test_a_file_saved_over_a_stand_in_gives_its_facts_to_nothing_when_a_scan_absorbs_it(self) -> None:
        moved = self._file("moved.mkv", "the first file")
        known_id = self._scanned(self._file("gone.mkv", "other"), HASH_A)
        facts().confirm_track(moved, 3, by=facts().ANSWERED_ON_BUGS)
        stand_in = int(self._rows("SELECT recording_id FROM locations WHERE path_key = ?", recording_records.path_key(moved))[0][0])
        moved.write_text("not the same file", encoding="utf-8")
        stat = moved.stat()
        connection = recording_records.connect(self.library, backup=False)
        with connection:
            connection.execute("UPDATE locations SET recording_id = ?, registered_by = 'scan', size_bytes = ?, modified_ns = ? "
                               "WHERE recording_id = ?", (known_id, stat.st_size, stat.st_mtime_ns, stand_in))
            recording_records.absorb_copy(connection, stand_in, known_id, by="raw bin scan", size=stat.st_size, modified=stat.st_mtime_ns)
        connection.close()
        self.assertEqual(self._rows("SELECT COUNT(*) FROM narration_answers WHERE content_sha256 IS NOT NULL")[0][0], 0)

    def test_the_you_chose_line(self) -> None:
        path = self._file()
        facts().confirm_track(path, 3, by=facts().ANSWERED_ON_BUGS)
        self.assertEqual(self._answer(path).you_chose, "", "no automatic pick is stored: no extra detection runs to compare")
        facts().record_measure(path, detection(1), measured_by=facts().BY_BUGS, titles=FOUR_TRACKS)
        self.assertEqual(self._answer(path).you_chose,
                         "You chose Track 3. The app heard your voice on Track 2. Your choice is used.")
        facts().confirm_track(path, 2, by=facts().ANSWERED_ON_BUGS)
        self.assertEqual(self._answer(path).you_chose, "", "they agree")

    def test_no_feature_picks_a_track_any_other_way(self) -> None:
        # Only the helpers named here may run detection; each of them stores what it heard and asks the rule first.
        callers = {path.relative_to(SOURCE).as_posix() for path in SOURCE.rglob("*.py")
                   if "detect_voice_track(" in path.read_text(encoding="utf-8")}
        self.assertEqual(callers, {"media_manglers/core/voice_track.py", "media_manglers/core/raw_bin_library.py",
                                   "media_manglers/core/review_preparation.py", "media_manglers/core/race_video/requests.py"})
        for name, listens in (("review_preparation.py", "voice_detector(source, working_root"),
                              ("race_video/requests.py", "detect_voice_track(")):
            text = (SOURCE / "media_manglers/core" / name).read_text(encoding="utf-8")
            self.assertLess(text.index("speech_facts.narration_answer("), text.rindex(listens), name)
            self.assertIn("details=True", text, name)
        backend = (SOURCE.parent / "Video Mangler.ps1").read_text(encoding="utf-8")
        self.assertEqual(backend.count("= Invoke-VoiceTrackDetection"), 2, "the two places a run listens")
        self.assertEqual(backend.count("Get-MMKnownVoiceDetection -PythonCommand"), 2, "and both ask first")
        self.assertIn('-MeasuredBy "transcript_only"', backend, "Transcript Only says who measured")


class NextSpeechTests(LibraryTestCase):
    def test_jump_points_are_the_narration_tracks_moments_each_a_little_early(self) -> None:
        path = self._file()
        facts().record_measure(path, detection(1), measured_by=facts().BY_BUGS, titles=FOUR_TRACKS)
        points = facts().jump_points(path)
        self.assertEqual(points.track, 2)
        self.assertEqual(points.stretches, ((9.5, 12.5), (19.5, 21.0)))
        self.assertEqual(facts().JUMP_LEAD_SECONDS, 0.5)
        self.assertFalse(points.needs_read or points.needs_listen)

    def test_your_answer_moves_the_jumps_to_your_track_with_nothing_read(self) -> None:
        path = self._file()
        facts().record_measure(path, detection(1), measured_by=facts().BY_BUGS, titles=FOUR_TRACKS)
        facts().confirm_track(path, 3, by=facts().ANSWERED_ON_BUGS)
        points = facts().jump_points(path)
        self.assertEqual(points.stretches, ((29.5, 31.0),))
        self.assertEqual(points.decided_by, "confirmed")

    def test_a_jump_never_starts_before_the_recording(self) -> None:
        path = self._file()
        facts().record_measure(path, detection(1, moments={2: [[0.2, 1.0]]}), measured_by=facts().BY_BUGS, titles=FOUR_TRACKS)
        self.assertEqual(facts().jump_points(path).stretches, ((0.0, 1.0),))

    def test_stale_moments_still_jump_until_they_are_measured_again(self) -> None:
        path = self._file()
        facts().record_measure(path, detection(1), measured_by=facts().BY_BUGS, titles=FOUR_TRACKS)
        with mock.patch.object(voice_track, "ACTIVITY_RULE_VERSION", voice_track.ACTIVITY_RULE_VERSION + 1):
            points = facts().jump_points(path)
        self.assertTrue(points.stale and points.needs_read)
        self.assertEqual(points.stretches, ((9.5, 12.5), (19.5, 21.0)))

    def test_a_recording_never_measured_needs_a_read(self) -> None:
        self.assertTrue(facts().jump_points(self._file()).needs_read)

    def test_a_measure_with_no_answer_needs_listening_and_uncertain_says_why(self) -> None:
        path = self._file()
        activity_only = {key: value for key, value in detection(None).items() if key != "status"}
        facts().record_measure(path, activity_only, measured_by=facts().BY_BACKGROUND, titles=FOUR_TRACKS)
        points = facts().jump_points(path)
        self.assertTrue(points.needs_listen)
        self.assertEqual(points.stretches, ())
        facts().record_measure(path, detection(None, status="uncertain"), measured_by=facts().BY_BACKGROUND, titles=FOUR_TRACKS)
        points = facts().jump_points(path)
        self.assertFalse(points.needs_listen)
        self.assertEqual(points.reason, facts().NO_TRACK_REASON)

    def test_a_raw_bin_row_gives_a_track_but_needs_a_read_for_its_finer_jumps(self) -> None:
        path = self._file()
        self._scanned(path, HASH_A, narration=2)
        points = facts().jump_points(path)
        self.assertEqual(points.track, 2)
        self.assertTrue(points.needs_read)
        facts().record_measure(path, {k: v for k, v in detection(None).items() if k != "status"}, measured_by=facts().BY_BACKGROUND, titles=FOUR_TRACKS)
        points = facts().jump_points(path)
        self.assertFalse(points.needs_read or points.needs_listen)
        self.assertEqual(points.stretches, ((9.5, 12.5), (19.5, 21.0)))


class HelperCommandTests(LibraryTestCase):
    def _known(self, path: Path, **payload):
        streams = [{"tags": {"title": title}} for title in FOUR_TRACKS.values()]
        with mock.patch.object(voice_track, "probe_audio_streams", return_value=(streams, 100.0)):
            return facts().known_from_request({"source_path": str(path), "ffprobe_exe": "ffprobe", **payload})

    def test_the_helper_commands_are_on_the_command_line(self) -> None:
        from media_manglers import cli

        source = (SOURCE / "media_manglers" / "cli.py").read_text(encoding="utf-8")
        self.assertIn('"voice-track-known": speech_facts.known_from_request', source)
        self.assertIn('"voice-track-detect": speech_facts.detect_from_request', source)
        self.assertTrue(cli)

    def test_detection_stores_the_moments_and_returns_none_of_them(self) -> None:
        path = self._file()
        full = {**detection(1), "kept_track_wavs": []}
        with mock.patch.object(voice_track, "detect_from_request", return_value=full) as helper:
            result = facts().detect_from_request({"source_path": str(path), "measured_by": "full_review",
                                                  "preferred_ordinals": [1], "track_roles": {"4": "never"}})
        self.assertTrue(helper.call_args.args[0]["details"], "it asks the detection for its details")
        for key in ("track_activity", "track_probes", "track_levels", "track_titles"):
            self.assertNotIn(key, result)
        self.assertNotIn("moments", json.dumps(result))
        found = facts().known_measure(path)
        self.assertEqual(found.measured_by, "full_review")
        self.assertEqual(found.tracks[2]["moments"], [(10.0, 12.5), (20.0, 21.0)])
        row = self._rows("SELECT preferred_key, roles_key FROM voice_decisions")[0]
        self.assertEqual((row["preferred_key"], row["roles_key"]), ("1", "4=never"))

    def test_a_known_recording_answers_with_no_moments_and_nothing_read(self) -> None:
        path = self._file()
        facts().record_measure(path, detection(1), measured_by=facts().BY_BUGS, titles=FOUR_TRACKS)
        with mock.patch.object(voice_track, "extract_all_tracks", side_effect=AssertionError("read the recording")):
            known = self._known(path)
        self.assertEqual(known["answer"]["selected_ordinal"], 1)
        self.assertNotIn("moments", json.dumps(known))

    def test_an_unknown_recording_says_listen(self) -> None:
        known = self._known(self._file())
        self.assertIsNone(known["answer"])
        self.assertEqual(known["preferred_ordinals"], [])

    def _layouts(self, *entries) -> Path:
        path = self.root / "narration-layouts.json"
        path.write_text(json.dumps({"schemaVersion": 1, "layouts": dict(entries)}), encoding="utf-8")
        return path

    def _with_layout(self, path: Path, layouts: Path, fingerprint: str, **payload):
        from media_manglers_workbench import audio_detection

        probe = ([audio_detection.AudioStreamInfo(ordinal=index, stream_index=index + 1, title=title, language="", codec="aac",
                                                  channels=1, channel_layout="mono", sample_rate=48000, bit_rate=0)
                  for index, title in FOUR_TRACKS.items()], 100.0, "obs", {})
        with mock.patch.object(audio_detection, "probe_source", return_value=probe), \
                mock.patch.object(audio_detection, "layout_fingerprint", return_value=fingerprint):
            return self._known(path, use_saved_layouts=True, layouts_path=str(layouts), **payload)

    def test_the_remembered_pick_is_the_saved_answer_for_this_recordings_own_layout(self) -> None:
        layouts = self._layouts(("this", {"audioOrdinal": 2}), ("other", {"audioOrdinal": 3, "confirmedAt": "2099"}))
        self.assertEqual(self._with_layout(self._file(), layouts, "this")["preferred_ordinals"], [2])

    def test_a_saved_answer_for_another_layout_is_not_used(self) -> None:
        layouts = self._layouts(("other", {"audioOrdinal": 3, "confirmedAt": "2099"}))
        self.assertEqual(self._with_layout(self._file(), layouts, "this")["preferred_ordinals"], [])

    def test_a_remembered_track_one_counts(self) -> None:
        layouts = self._layouts(("this", {"audioOrdinal": 0}))
        self.assertEqual(self._with_layout(self._file(), layouts, "this")["preferred_ordinals"], [0])

    def test_a_layout_with_no_saved_answer_falls_back_to_the_runs_usual_track_only(self) -> None:
        layouts = self._layouts(("other", {"audioOrdinal": 3}))
        self.assertEqual(self._with_layout(self._file(), layouts, "this", fallback_ordinals=[1])["preferred_ordinals"], [1])

    def test_a_remembered_track_one_breaks_a_real_tie(self) -> None:
        # The detection itself, with the pick voice-track-known now gives it: two different voices of equal weight.
        activity = {ordinal: voice_track.TrackActivity(ordinal=ordinal, duration_seconds=600.0, active_ratio=0.2, silent=False,
                                                       intervals=[(float(start), float(start) + 2.0) for start in range(ordinal, 600, 10)],
                                                       loud_share=0.0, level_swing_db=25.0) for ordinal in (0, 1)}
        probes = {ordinal: voice_track.TrackProbe(ordinal=ordinal, confident_words=100, probed_seconds=60.0) for ordinal in (0, 1)}
        untied = voice_track.decide_with_roles(activity, probes, {0: "", 1: ""}, [])
        tied = voice_track.decide_with_roles(activity, probes, {0: "", 1: ""}, [0])
        self.assertEqual(untied["status"], "uncertain")
        self.assertEqual((tied["status"], tied["selected_ordinal"]), ("selected", 0))


if __name__ == "__main__":
    unittest.main()
