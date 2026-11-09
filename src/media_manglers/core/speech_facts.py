"""Speech facts: what the app knows about each recording's speech, and the one narration-track rule (264, 242).

Each recording's speech moments per track are kept in the library, with the rule that measured them and who
measured them, and every feature that decides a narration track asks here first. The moments and the answers belong to
the recording's content (the full hash), so exact copies share them; until the content is known they belong to the
one copy, and only while its file keeps the size and time they were made on. A sampled hash never shares anything.

Detection itself stays in ``voice_track``, which knows nothing of the library: this module sits above both, and it is
the only code that reads or writes these tables, through the library's front door (``recording_records``).

The rule (``narration_answer``), the first that answers wins, after each feature's own reality checks:

1. your confirmed answer for this recording;
2. your saved answer for this exact track layout, only where a screen applies it (the Inbox and the wizard);
3. the track names, then the Track roles setting;
4. the stored automatic pick;
5. fresh detection, with a remembered pick only as a tie-breaker. Nothing here listens: the caller does that.

Stored facts only save work, so a library that cannot be read or written never fails a run: it is logged and ignored.
Moments and answers are personal: never in an export, a package, a ZIP, a log or anything an agent reads. Moments are
taken out of every result a feature keeps (``voice_track.strip_details``), and logs here say counts and error kinds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from . import recording_records, voice_track

_log = logging.getLogger(__name__)

# Who measured or answered, as the library stores it.
BY_RAW_BIN = "raw_bin_scan"
BY_BUGS = "bug_reports"
BY_FULL_REVIEW = "full_review"
BY_TRANSCRIPT_ONLY = "transcript_only"
BY_INBOX = "inbox"
BY_EDITOR = "editor"
BY_BACKGROUND = "background"
ANSWERED_ON_BUGS = "bugs_page"
ANSWERED_IN_INBOX = "inbox_dialog"
ANSWERED_IN_WIZARD = "wizard"
ANSWERED_ON_EDITOR = "editor_page"
# Who decided, as a result says it (design 2.5).
DECIDED_CONFIRMED = "confirmed"
DECIDED_LAYOUT = "layout"
DECIDED_NAME = voice_track.DECIDED_BY_NAME
DECIDED_SETTING = voice_track.DECIDED_BY_SETTING
DECIDED_AUTO = voice_track.DECIDED_BY_AUTO
DECIDED_TIE_BREAK = "auto_tie_break"
YOU_CHOSE_TEXT = "you chose"
# Where Next speech lands, this long before the speech starts, so its first word is heard (design 2.6, Q1).
JUMP_LEAD_SECONDS = 0.5
# The rule every raw bin row without a stored decision was made by: the raw bin first shipped under it. A new rule makes
# them stale like any other stored pick.
RAW_BIN_ROWS_RULE_VERSION = 5

_DB_ERRORS = (OSError, sqlite3.Error, ValueError)
# What a decision keeps beside its columns; the words heard and anything else about the recording stay out.
_DECISION_KEEPS = ("suggested_ordinal", "selection_reason", "uncertain_reason", "competing_ordinals", "track_roles",
                   "decided_by_text")


def roles_key(titles: dict[int, str], setting_roles: dict[int, str] | None) -> str:
    """The Track roles setting in one fixed form, "" for a recording whose tracks have names: names win over the
    setting (``voice_track.track_roles``), so a change to the setting cannot change that recording's answer."""

    source, _roles = voice_track.track_roles(dict(titles), setting_roles)
    if source == voice_track.DECIDED_BY_NAME:
        return ""
    return ",".join(f"{ordinal + 1}={role}" for ordinal, role in sorted((setting_roles or {}).items()))


def preferred_key(ordinals: Iterable[int] | None) -> str:
    """A remembered pick in one fixed form; "" for none. Track 1 is a pick like any other."""

    return ",".join(str(int(value)) for value in sorted({int(value) for value in (ordinals or [])}))


def you_chose_line(chosen: int | None, auto: int | None) -> str:
    """The one calm line when the operator's answer differs from the stored automatic pick (design 2.5), or ""."""

    if chosen is None or auto is None or int(chosen) == int(auto):
        return ""
    return f"You chose Track {int(chosen)}. The app heard your voice on Track {int(auto)}. Your choice is used."


# Who the facts belong to ---------------------------------------------------------------------------------------


def _file_now(path: Any) -> tuple[int, int] | None:
    try:
        stat = os.stat(str(path))
    except (OSError, ValueError):
        return None
    return int(stat.st_size), int(stat.st_mtime_ns)


def _key_clause(copy: dict[str, Any], now: tuple[int, int] | None) -> tuple[str, tuple[Any, ...]] | None:
    """Which rows belong to the file at this copy now: the content's when the copy is confirmed; otherwise the copy's
    own, only while the file has the size and time they were made on."""

    if copy["confirmed"]:
        return "content_sha256 = ?", (copy["content_sha256"],)
    if now is None:
        return None
    return ("content_sha256 IS NULL AND recording_id = ? AND size_bytes = ? AND modified_ns = ?",
            (int(copy["recording_id"]), now[0], now[1]))


def _reader(root: Path | None) -> sqlite3.Connection | None:
    return recording_records.connect_read_only(root)


# Measures -------------------------------------------------------------------------------------------------------


@dataclass
class Measure:
    """One recording's stored measure. ``tracks``: track number (1 = Track 1) to what was measured."""

    measure_id: int
    activity_rule_version: int
    measured_by: str
    duration_seconds: float = 0.0
    titles: dict[int, str] = field(default_factory=dict)
    tracks: dict[int, dict[str, Any]] = field(default_factory=dict)

    @property
    def stale(self) -> bool:
        return self.activity_rule_version != voice_track.ACTIVITY_RULE_VERSION


def _load_measure(connection: sqlite3.Connection, copy: dict[str, Any], path: Any) -> Measure | None:
    clause = _key_clause(copy, _file_now(path))
    if clause is None:
        return None
    row = connection.execute(f"SELECT * FROM voice_measures WHERE {clause[0]}", clause[1]).fetchone()
    if row is None:
        return None
    try:
        titles = {int(key) - 1: str(value) for key, value in json.loads(row["titles_json"] or "{}").items()}
    except (ValueError, TypeError, AttributeError):
        titles = {}
    measure = Measure(int(row["measure_id"]), int(row["activity_rule_version"]), str(row["measured_by"]),
                      float(row["duration_seconds"] or 0.0), titles)
    for item in connection.execute("SELECT * FROM voice_measure_tracks WHERE measure_id = ? ORDER BY track",
                                   (measure.measure_id,)):
        try:
            moments = [(float(start), float(end)) for start, end in json.loads(item["moments_json"] or "[]")]
        except (ValueError, TypeError):
            moments = []
        measure.tracks[int(item["track"])] = {**dict(item), "moments": moments}
    return measure


def known_measure(path: Any, *, root: Path | None = None) -> Measure | None:
    """The stored measure for the file at ``path``, or None. Reads the library and looks at the file's size and time;
    never reads the recording."""

    try:
        connection = _reader(root)
        if connection is None:
            return None
        try:
            copy = recording_records.copy_at(connection, path)
            return _load_measure(connection, copy, path) if copy else None
        finally:
            connection.close()
    except _DB_ERRORS as exc:
        _log.warning("Speech facts could not be read (%s).", type(exc).__name__)
        return None


def _titles_from(detection: dict[str, Any], titles: dict[int, str] | None) -> dict[int, str]:
    if titles is not None:
        return dict(titles)
    named = detection.get("track_titles")
    return {int(number) - 1: str(title) for number, title in named.items()} if isinstance(named, dict) else {}


def write_measure(connection: sqlite3.Connection, *, recording_id: int, content: str, size: int, modified: int,
                  detection: dict[str, Any], measured_by: str, run_id: str = "", titles: dict[int, str] | None = None,
                  duration: float | None = None, setting_roles: dict[int, str] | None = None,
                  preferred: Iterable[int] | None = None) -> int | None:
    """Write what ``detection`` measured for one recording, and its decision if it made one, inside the caller's
    transaction. A later measure of the same recording replaces the moments and keeps what an earlier one heard on a
    track it did not listen to. Returns the measure's number; None when the detection measured nothing."""

    activity = detection.get("track_activity")
    if not isinstance(activity, dict) or not activity:
        return None
    probes = detection.get("track_probes") if isinstance(detection.get("track_probes"), dict) else {}
    now = recording_records._stamp()
    names = _titles_from(detection, titles)
    where = ("content_sha256 = ?", (content,)) if content else (
        "content_sha256 IS NULL AND recording_id = ?", (int(recording_id),))
    row = connection.execute(f"SELECT measure_id, size_bytes, modified_ns FROM voice_measures WHERE {where[0]}",
                             where[1]).fetchone()
    if row is not None and not content and (int(row["size_bytes"]), int(row["modified_ns"])) != (int(size), int(modified)):
        # Another file at this copy now: what was known about the old one goes with it.
        connection.execute("DELETE FROM voice_measures WHERE measure_id = ?", (int(row["measure_id"]),))
        row = None
    values = (int(size), int(modified), float(duration if duration is not None else detection.get("duration_seconds") or 0.0),
              len(activity), json.dumps({str(ordinal + 1): title for ordinal, title in sorted(names.items())}),
              voice_track.ACTIVITY_RULE_VERSION, str(measured_by), run_id or None, now)
    if row is None:
        measure = int(connection.execute(
            "INSERT INTO voice_measures(content_sha256, recording_id, size_bytes, modified_ns, duration_seconds, "
            "track_count, titles_json, activity_rule_version, measured_by, run_id, measured_utc) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (content or None, None if content else int(recording_id), *values)).lastrowid)
    else:
        measure = int(row["measure_id"])
        connection.execute(
            "UPDATE voice_measures SET size_bytes = ?, modified_ns = ?, duration_seconds = ?, track_count = ?, "
            "titles_json = ?, activity_rule_version = ?, measured_by = ?, run_id = ?, measured_utc = ? "
            "WHERE measure_id = ?", (*values, measure))
    for number, item in activity.items():
        heard = probes.get(str(number)) if isinstance(probes.get(str(number)), dict) else None
        moments = item.get("moments")
        if moments is None:
            moments = item.get("intervals") or []
        connection.execute(
            "INSERT INTO voice_measure_tracks(measure_id, track, silent, active_seconds, active_ratio, noise_floor_dbfs, "
            "peak_dbfs, level_swing_db, loud_share, moments_json, confident_words, spotter_words, own_words, "
            "probed_seconds, listened) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(measure_id, track) DO UPDATE SET silent = excluded.silent, active_seconds = excluded.active_seconds, "
            "active_ratio = excluded.active_ratio, noise_floor_dbfs = excluded.noise_floor_dbfs, "
            "peak_dbfs = excluded.peak_dbfs, level_swing_db = excluded.level_swing_db, loud_share = excluded.loud_share, "
            "moments_json = excluded.moments_json, "
            "confident_words = COALESCE(excluded.confident_words, confident_words), "
            "spotter_words = COALESCE(excluded.spotter_words, spotter_words), "
            "own_words = COALESCE(excluded.own_words, own_words), "
            "probed_seconds = COALESCE(excluded.probed_seconds, probed_seconds), "
            "listened = MAX(excluded.listened, listened)",
            (measure, int(number), int(bool(item.get("silent"))), item.get("active_seconds"), item.get("active_ratio"),
             item.get("noise_floor_dbfs"), item.get("peak_dbfs"), item.get("level_swing_db"), item.get("loud_share"),
             json.dumps(moments, separators=(",", ":")),
             heard.get("confident_words") if heard else None, heard.get("spotter_words") if heard else None,
             heard.get("own_words") if heard else None, heard.get("probed_seconds") if heard else None, int(bool(heard))))
    status = str(detection.get("status") or "")
    if status and status != "no_audio":
        _write_decision(connection, measure, detection, status, names, setting_roles, preferred, now)
    return measure


def _write_decision(connection: sqlite3.Connection, measure: int, detection: dict[str, Any], status: str,
                    titles: dict[int, str], setting_roles: dict[int, str] | None, preferred: Iterable[int] | None,
                    now: str) -> None:
    chosen = detection.get("selected_ordinal")
    pick = preferred_key(preferred)
    decided = str(detection.get("decided_by") or "")
    if decided == DECIDED_AUTO and chosen is not None and str(chosen) in pick.split(","):
        decided = DECIDED_TIE_BREAK
    # The per-track summary the invented-line filters read; never the words heard (196).
    tracks = [{key: value for key, value in item.items() if key != "sample_text"}
              for item in detection.get("tracks") or [] if isinstance(item, dict)]
    details = {key: detection[key] for key in _DECISION_KEEPS if key in detection}
    connection.execute(
        "INSERT OR REPLACE INTO voice_decisions(measure_id, voice_rule_version, roles_key, preferred_key, status, "
        "chosen_track, confidence, decided_by, explanation, tracks_json, details_json, decided_utc) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (measure, int(detection.get("rule_version") or voice_track.VOICE_RULE_VERSION), roles_key(titles, setting_roles), pick,
         status, None if chosen is None else int(chosen) + 1, detection.get("confidence"), decided,
         str(detection.get("explanation") or ""), json.dumps(tracks), json.dumps(details), now))


def record_measure(path: Any, detection: dict[str, Any], *, measured_by: str, run_id: str = "", content: str | None = None,
                   titles: dict[int, str] | None = None, duration: float | None = None,
                   setting_roles: dict[int, str] | None = None, preferred: Iterable[int] | None = None,
                   root: Path | None = None) -> bool:
    """Write what was measured, one commit per recording, so a stopped run keeps what it finished. A recording no scan
    has read gets a copy of its own, marked "outside", off the raw bin's list. Any library failure is logged and
    ignored: stored facts only save work, so they can never fail a run. True when something was written."""

    now = _file_now(path)
    if now is None:
        return False
    try:
        connection = recording_records.connect(root, backup=False)
        try:
            with connection:
                copy = recording_records.register_copy(connection, path)
                if copy is None:
                    return False
                key = str(content or "") or (copy["content_sha256"] if copy["confirmed"] else "")
                return write_measure(connection, recording_id=copy["recording_id"], content=key, size=now[0], modified=now[1],
                                     detection=detection, measured_by=measured_by, run_id=run_id, titles=titles,
                                     duration=duration, setting_roles=setting_roles, preferred=preferred) is not None
        finally:
            connection.close()
    except _DB_ERRORS as exc:
        _log.warning("Speech facts could not be stored (%s); the run goes on.", type(exc).__name__)
        return False


def attach_content(connection: sqlite3.Connection, recording_id: int, content: str, *, size: int | None = None,
                   modified: int | None = None) -> None:
    """A measure or answer made before the hash was known becomes shared once a scan confirms the content, inside the
    scan's transaction. With ``size`` and ``modified`` only what was made on that very file: one saved over it since
    inherits nothing."""

    if content:
        recording_records.merge_speech_facts(connection, int(recording_id), int(recording_id), str(content),
                                             size=size, modified=modified)


def keep_with_scan(connection: sqlite3.Connection, *, recording_id: int, previous: int | None, content: str, size: int,
                   modified: int, detection: dict[str, Any], run_id: str, titles: dict[int, str], duration: Any,
                   setting_roles: dict[int, str] | None) -> None:
    """A raw bin scan's measure, inside the transaction that stores the recording. It has a savepoint of its own: a
    failure here is logged and undone by itself, and the scan's own result stays."""

    try:
        connection.execute("SAVEPOINT speech_facts")
    except sqlite3.Error as exc:
        _log.warning("Speech facts could not be stored (%s); the scan goes on.", type(exc).__name__)
        return
    try:
        write_measure(connection, recording_id=recording_id, content=content, size=size, modified=modified, detection=detection,
                      measured_by=BY_RAW_BIN, run_id=run_id, titles=titles,
                      duration=None if duration is None else float(duration), setting_roles=setting_roles)
        attach_content(connection, recording_id, content, size=size, modified=modified)
        if previous and int(previous) != int(recording_id):
            attach_content(connection, int(previous), content, size=size, modified=modified)
        connection.execute("RELEASE speech_facts")
    except (sqlite3.Error, ValueError, TypeError) as exc:
        _log.warning("Speech facts could not be stored (%s); the scan goes on.", type(exc).__name__)
        connection.execute("ROLLBACK TO speech_facts")
        connection.execute("RELEASE speech_facts")


# Your answer ------------------------------------------------------------------------------------------------------


@dataclass
class Answer:
    """The operator's answer for one recording: ``state`` is "confirmed", "cleared" or "none"."""

    state: str = "none"
    track: int | None = None
    by: str = ""
    when: str = ""


def _load_answer(connection: sqlite3.Connection, copy: dict[str, Any], path: Any) -> Answer:
    clause = _key_clause(copy, _file_now(path))
    if clause is None:
        return Answer()
    row = connection.execute(f"SELECT * FROM narration_answers WHERE {clause[0]} ORDER BY answer_id DESC LIMIT 1",
                             clause[1]).fetchone()
    if row is None:
        return Answer()
    if row["cleared_utc"] is not None:
        return Answer("cleared", None, str(row["cleared_by"] or ""), str(row["cleared_utc"]))
    return Answer("confirmed", int(row["track"]), str(row["answered_by"]), str(row["answered_utc"]))


def answer_for(path: Any, *, root: Path | None = None) -> Answer:
    """The operator's answer for the file at ``path``. Quick: reads the library and looks at the file."""

    try:
        connection = _reader(root)
        if connection is None:
            return Answer()
        try:
            copy = recording_records.copy_at(connection, path)
            return _load_answer(connection, copy, path) if copy else Answer()
        finally:
            connection.close()
    except _DB_ERRORS as exc:
        _log.warning("Speech facts could not be read (%s).", type(exc).__name__)
        return Answer()


def confirmed_track(path: Any, *, root: Path | None = None) -> int | None:
    """The track the operator confirmed for this recording (1 = Track 1), or None."""

    answer = answer_for(path, root=root)
    return answer.track if answer.state == "confirmed" else None


def confirm_track(path: Any, track: int, *, by: str, root: Path | None = None) -> bool:
    """Your confirmed answer for this recording, shared by exact copies. The answer it replaces is kept, cleared. A
    library that cannot be written is logged and ignored, as for every stored fact. True when it was stored."""

    now = _file_now(path)
    if now is None or int(track) < 1:
        return False
    try:
        connection = recording_records.connect(root, backup=False)
        try:
            with connection:
                copy = recording_records.register_copy(connection, path)
                if copy is None:
                    return False
                clause = _key_clause(copy, now)
                active = connection.execute(
                    f"SELECT answer_id, track FROM narration_answers WHERE {clause[0]} AND cleared_utc IS NULL", clause[1]).fetchone()
                if active is not None and int(active["track"]) == int(track):
                    return True
                stamp = recording_records._stamp()
                # The row of an older file at this copy can be active too; only one answer per copy can be.
                connection.execute("UPDATE narration_answers SET cleared_utc = ?, cleared_by = ? WHERE cleared_utc IS NULL AND "
                                   + ("content_sha256 = ?" if copy["confirmed"] else "content_sha256 IS NULL AND recording_id = ?"),
                                   (stamp, by, copy["content_sha256"] if copy["confirmed"] else int(copy["recording_id"])))
                connection.execute(
                    "INSERT INTO narration_answers(content_sha256, recording_id, size_bytes, modified_ns, track, answered_by, "
                    "answered_utc) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (copy["content_sha256"] if copy["confirmed"] else None,
                     None if copy["confirmed"] else int(copy["recording_id"]), now[0], now[1], int(track), by, stamp))
                return True
        finally:
            connection.close()
    except _DB_ERRORS as exc:
        _log.warning("Your answer could not be stored (%s).", type(exc).__name__)
        return False


def clear_track(path: Any, *, by: str, root: Path | None = None) -> bool:
    """Automatic again: the answer stays on record, with when and by whom, and the app decides. Recorded even with no
    answer to clear (a row with track 0, cleared at once) when the library knows the copy, so a screen's older choice
    for it (the editor's, kept in its project) also gives way. True when the library holds the result."""

    now = _file_now(path)
    if now is None:
        return False
    try:
        connection = recording_records.connect(root, backup=False)
        try:
            with connection:
                copy = recording_records.copy_at(connection, path)
                if copy is None:
                    return False
                clause = _key_clause(copy, now)
                stamp = recording_records._stamp()
                changed = connection.execute(
                    f"UPDATE narration_answers SET cleared_utc = ?, cleared_by = ? WHERE {clause[0]} AND cleared_utc IS NULL",
                    (stamp, by, *clause[1])).rowcount
                if not changed:
                    connection.execute(
                        "INSERT INTO narration_answers(content_sha256, recording_id, size_bytes, modified_ns, track, "
                        "answered_by, answered_utc, cleared_utc, cleared_by) VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)",
                        (copy["content_sha256"] if copy["confirmed"] else None,
                         None if copy["confirmed"] else int(copy["recording_id"]), now[0], now[1], by, stamp, stamp, by))
                return True
        finally:
            connection.close()
    except _DB_ERRORS as exc:
        _log.warning("Your answer could not be cleared (%s).", type(exc).__name__)
        return False


# The one rule -----------------------------------------------------------------------------------------------------


@dataclass
class NarrationAnswer:
    """What the rule says. ``track`` is 1-based, or None. ``decided_by`` is who decided; "" when nothing has yet.

    ``final`` says the caller may use ``detection`` instead of listening. A track from its name alone (step 3) is not
    final until it was heard, because a named track with no clear speech is "no narration found", not that track; the
    player and the background job only need the track, and a run still listens. ``auto_track`` is the stored automatic
    pick whatever decided, for the "You chose" line."""

    track: int | None = None
    decided_by: str = ""
    final: bool = False
    status: str = ""
    by: str = ""
    when: str = ""
    auto_track: int | None = None
    detection: dict[str, Any] | None = None
    answer_state: str = "none"

    @property
    def you_chose(self) -> str:
        return you_chose_line(self.track, self.auto_track) if self.decided_by == DECIDED_CONFIRMED else ""


def _base_result(path: Any, titles: dict[int, str], duration: float, setting_roles: dict[int, str] | None) -> dict[str, Any]:
    _source, roles = voice_track.track_roles(dict(titles), setting_roles)
    return {"source_path": str(path), "audio_track_count": len(titles), "duration_seconds": duration,
            "rule_version": voice_track.VOICE_RULE_VERSION, "kept_track_wavs": [], "device": "",
            "track_roles": {str(ordinal + 1): roles.get(ordinal, voice_track.ROLE_AUTO) for ordinal in sorted(titles)}}


def _track_rows(titles: dict[int, str], measure: Measure | None) -> list[dict[str, Any]]:
    """Each track as a result lists it, for the invented-line filters: which is silent, from what was measured."""

    rows = []
    for ordinal in sorted(titles):
        measured = measure.tracks.get(ordinal + 1) if measure is not None else None
        rows.append({"ordinal": ordinal, "track_number": ordinal + 1, "title": titles[ordinal],
                     "silent": bool(measured["silent"]) if measured else False})
    return rows


def _confirmed_result(path: Any, track: int, titles: dict[int, str], measure: Measure | None,
                      setting_roles: dict[int, str] | None) -> dict[str, Any]:
    return {**_base_result(path, titles, measure.duration_seconds if measure else 0.0, setting_roles),
            "status": "selected", "selected_ordinal": track - 1, "suggested_ordinal": track - 1, "confidence": 1.0,
            "tracks": _track_rows(titles, measure), "explanation": f"You chose Track {track} for this recording.",
            "decided_by": DECIDED_CONFIRMED, "decided_by_text": YOU_CHOSE_TEXT}


def _stored_decision(connection: sqlite3.Connection, measure: Measure, titles: dict[int, str],
                     setting_roles: dict[int, str] | None, remembered: str) -> sqlite3.Row | None:
    """The stored decision that still answers (design 2.3): this rule and these Track roles; made with no remembered pick,
    or the same one, or one that chose the remembered track. "Uncertain" is never reused: it is asked again."""

    rows = connection.execute(
        "SELECT * FROM voice_decisions WHERE measure_id = ? AND voice_rule_version = ? AND roles_key = ? AND status <> 'uncertain'",
        (measure.measure_id, voice_track.VOICE_RULE_VERSION, roles_key(titles, setting_roles))).fetchall()
    order = {str(row["preferred_key"]): row for row in rows}
    if remembered in order:
        return order[remembered]
    if "" in order:
        return order[""]
    wanted = set(remembered.split(",")) if remembered else set()
    for row in rows:
        if row["chosen_track"] is not None and str(int(row["chosen_track"]) - 1) in wanted:
            return row
    return None


def _automatic_pick(connection: sqlite3.Connection, measure: Measure | None, copy: dict[str, Any], path: Any,
                    titles: dict[int, str], setting_roles: dict[int, str] | None) -> int | None:
    """The stored automatic pick for the "You chose" line: no extra detection runs just to compare."""

    if measure is not None:
        row = connection.execute(
            "SELECT chosen_track FROM voice_decisions WHERE measure_id = ? AND voice_rule_version = ? AND status = 'selected' "
            "ORDER BY preferred_key, decided_utc DESC LIMIT 1", (measure.measure_id, voice_track.VOICE_RULE_VERSION)).fetchone()
        if row is not None and row["chosen_track"] is not None:
            return int(row["chosen_track"])
    return _old_raw_bin_pick(connection, copy, path, titles, setting_roles)


def _old_raw_bin_pick(connection: sqlite3.Connection, copy: dict[str, Any], path: Any, titles: dict[int, str],
                      setting_roles: dict[int, str] | None, roles_value: Any = None) -> int | None:
    """A raw bin row made before speech facts counts as a stored pick (design 2.3), with nothing moved: every row was
    made by this rule, with no remembered pick, when its file is unchanged and the Track roles it used still hold."""

    if not copy["confirmed"] or voice_track.VOICE_RULE_VERSION != RAW_BIN_ROWS_RULE_VERSION:
        return None
    pick = recording_records.scanned_pick(connection, copy["recording_id"])
    if pick is None:
        return None
    if roles_value is not None and voice_track.game_mix_roles_key(roles_value) != str(pick["rules_roles"] or ""):
        return None
    track = int(pick["narration_track"])
    _source, roles = voice_track.track_roles(dict(titles), setting_roles)
    if titles and (track - 1 not in titles or roles.get(track - 1) in (voice_track.ROLE_NEVER, voice_track.ROLE_FULL_MIX)):
        return None
    return track


def _titles_of_scan(connection: sqlite3.Connection, copy: dict[str, Any]) -> dict[int, str]:
    pick = recording_records.scanned_pick(connection, copy["recording_id"])
    try:
        names = json.loads(pick["track_titles_json"] or "{}") if pick else {}
        return {int(number) - 1: str(title) for number, title in names.items()}
    except (ValueError, TypeError, AttributeError):
        return {}


def narration_answer(path: Any, *, titles: dict[int, str] | None = None, track_roles: Any = None, explicit: int | None = None,
                     layout_answer: int | None = None, remembered: Iterable[int] | None = None,
                     root: Path | None = None) -> NarrationAnswer:
    """The one narration-track rule (module note). Quick: it reads the library and looks at the file's size and time, and
    never reads the recording.

    ``titles``: each track's name, {ordinal: name}, when the caller read them; otherwise what was stored. ``track_roles``:
    the Track roles setting as text or a mapping. ``explicit``: a track (1 = Track 1) the screen already holds as your
    choice. ``layout_answer``: your saved answer for this layout, passed only where it applies today (the Inbox and the
    wizard). ``remembered``: the tie-breaker, as ordinals (0 = Track 1); it can only decide in fresh detection."""

    roles_value = voice_track.roles_from_text(track_roles) if isinstance(track_roles, str) else track_roles
    setting_roles = voice_track.parse_track_roles(roles_value)
    connection = copy = measure = None
    answer = Answer()
    try:
        connection = _reader(root)
        if connection is not None:
            copy = recording_records.copy_at(connection, path)
            if copy is not None:
                measure = _load_measure(connection, copy, path)
                answer = _load_answer(connection, copy, path)
                return _answer_with_library(path, connection, copy, measure, answer, titles, roles_value, setting_roles,
                                            explicit, layout_answer, remembered)
    except _DB_ERRORS as exc:
        _log.warning("Speech facts could not be read (%s).", type(exc).__name__)
    finally:
        if connection is not None:
            connection.close()
    return _answer_without_facts(path, titles or {}, setting_roles, explicit, layout_answer)


def _answer_without_facts(path: Any, titles: dict[int, str], setting_roles: dict[int, str] | None, explicit: int | None,
                          layout_answer: int | None) -> NarrationAnswer:
    if explicit is not None:
        return NarrationAnswer(int(explicit), DECIDED_CONFIRMED, True, "selected",
                               detection=_confirmed_result(path, int(explicit), titles, None, setting_roles))
    if layout_answer is not None:
        return NarrationAnswer(int(layout_answer), DECIDED_LAYOUT, False, "selected")
    return _from_names(titles, setting_roles) or NarrationAnswer()


def _from_names(titles: dict[int, str], setting_roles: dict[int, str] | None) -> NarrationAnswer | None:
    if not titles:
        return None
    source, roles = voice_track.track_roles(dict(titles), setting_roles)
    narration = [ordinal for ordinal in sorted(titles) if roles.get(ordinal) == voice_track.ROLE_NARRATION]
    if len(narration) == 1:
        return NarrationAnswer(narration[0] + 1, source, False, "selected")
    return None


def _answer_with_library(path: Any, connection: sqlite3.Connection, copy: dict[str, Any], measure: Measure | None, answer: Answer,
                         titles: dict[int, str] | None, roles_value: Any, setting_roles: dict[int, str] | None,
                         explicit: int | None, layout_answer: int | None, remembered: Iterable[int] | None) -> NarrationAnswer:
    names = dict(titles) if titles is not None else (dict(measure.titles) if measure is not None and measure.titles
                                                     else _titles_of_scan(connection, copy))
    auto = _automatic_pick(connection, measure, copy, path, names, setting_roles)
    # 1. Your confirmed answer for this recording.
    mine = int(explicit) if explicit is not None else answer.track
    if mine is not None and (not names or mine - 1 in names):
        return NarrationAnswer(mine, DECIDED_CONFIRMED, True, "selected", answer.by, answer.when, auto,
                               _confirmed_result(path, mine, names, measure, setting_roles), answer.state)
    # 2. Your saved answer for this exact layout, where it applies.
    if layout_answer is not None:
        return NarrationAnswer(int(layout_answer), DECIDED_LAYOUT, False, "selected", auto_track=auto,
                               answer_state=answer.state)
    # 3 and 4. A stored decision holds what the names and the setting said when it was heard.
    named = _from_names(names, setting_roles)
    old = _old_raw_bin_pick(connection, copy, path, names, setting_roles, roles_value if roles_value is not None else {})
    stored = None
    if measure is not None:
        stored = _stored_decision(connection, measure, names, setting_roles, preferred_key(remembered))
    if stored is not None:
        status = str(stored["status"])
        track = int(stored["chosen_track"]) if stored["chosen_track"] is not None else None
        details = json.loads(stored["details_json"] or "{}")
        decided = str(stored["decided_by"] or "")
        text_key = DECIDED_AUTO if decided == DECIDED_TIE_BREAK else decided
        tracks = json.loads(stored["tracks_json"] or "[]")
        detection = {**_base_result(path, names, measure.duration_seconds, setting_roles), **details, "status": status,
                     "selected_ordinal": None if track is None else track - 1, "confidence": stored["confidence"],
                     "tracks": tracks, "explanation": str(stored["explanation"] or ""), "decided_by": text_key,
                     "decided_by_text": voice_track.DECIDED_BY_TEXT.get(text_key, str(details.get("decided_by_text") or "")),
                     "rule_version": int(stored["voice_rule_version"])}
        return NarrationAnswer(track, decided, True, status, auto_track=auto, detection=detection, answer_state=answer.state)
    if named is not None and old != named.track:
        named.auto_track, named.answer_state = auto, answer.state
        return named
    # 4. An old raw bin row counts as a stored pick, made with no remembered pick.
    if old is not None:
        decided = named.decided_by if named is not None else DECIDED_AUTO
        label = voice_track.DECIDED_BY_TEXT[decided]
        detection = {**_base_result(path, names, measure.duration_seconds if measure else 0.0, setting_roles),
                     "status": "selected", "selected_ordinal": old - 1, "suggested_ordinal": old - 1, "confidence": 1.0,
                     "tracks": _track_rows(names, measure),
                     "explanation": f"{label[0].upper()}{label[1:]}: a raw bin scan found your voice on Track {old}.",
                     "decided_by": decided, "decided_by_text": label}
        return NarrationAnswer(old, decided, True, "selected", auto_track=old, detection=detection, answer_state=answer.state)
    # 5. Fresh detection: the caller listens, or does without.
    return NarrationAnswer(auto_track=auto, answer_state=answer.state)


# Next speech ------------------------------------------------------------------------------------------------------


def _stretches(moments: Iterable[Iterable[float]]) -> tuple[tuple[float, float], ...]:
    return tuple((max(0.0, float(start) - JUMP_LEAD_SECONDS), float(end)) for start, end in moments)


@dataclass
class JumpPoints:
    """Where Next speech stops, on which track, and why there is none when there is none."""

    track: int | None = None
    stretches: tuple[tuple[float, float], ...] = ()
    stale: bool = False
    measured: bool = False
    decided_by: str = ""
    reason: str = ""
    you_chose: str = ""
    # What the background job still has to do for this recording: read it, or only listen.
    needs_read: bool = False
    needs_listen: bool = False


NO_TRACK_REASON = "No Next speech yet: the app could not tell which track is your voice."
NO_NARRATION_REASON = "No Next speech: the app heard no narration in this recording."
NO_SPEECH_REASON = "No Next speech: there is no speech on your narration track."


def jump_points(path: Any, *, track_roles: Any = None, root: Path | None = None) -> JumpPoints:
    """The stretches Next speech uses for this recording: every moment on the narration track, each starting a little
    early. Stale moments still jump until they are measured again, because a jump is only navigation. Quick: never reads
    the recording, and not on the screen's thread when the drive may be asleep (``LevelsService``)."""

    roles_value = voice_track.roles_from_text(track_roles) if isinstance(track_roles, str) else track_roles
    setting_roles = voice_track.parse_track_roles(roles_value)
    connection = None
    try:
        connection = _reader(root)
        copy = recording_records.copy_at(connection, path) if connection is not None else None
        if copy is None:
            return JumpPoints(needs_read=True)
        measure = _load_measure(connection, copy, path)
        answer = _answer_with_library(path, connection, copy, measure, _load_answer(connection, copy, path), None, roles_value,
                                      setting_roles, None, None, None)
        undecided = ""
        if measure is not None and answer.track is None:
            row = connection.execute(
                "SELECT status FROM voice_decisions WHERE measure_id = ? AND voice_rule_version = ? AND roles_key = ? "
                "ORDER BY decided_utc DESC LIMIT 1",
                (measure.measure_id, voice_track.VOICE_RULE_VERSION, roles_key(measure.titles, setting_roles))).fetchone()
            undecided = str(row["status"]) if row is not None else ""
    except _DB_ERRORS as exc:
        _log.warning("Speech facts could not be read (%s).", type(exc).__name__)
        return JumpPoints()
    finally:
        if connection is not None:
            connection.close()
    if measure is None:
        return JumpPoints(track=answer.track, decided_by=answer.decided_by, you_chose=answer.you_chose, needs_read=True)
    points = JumpPoints(track=answer.track, stale=measure.stale, measured=True, decided_by=answer.decided_by,
                        you_chose=answer.you_chose, needs_read=measure.stale)
    if answer.track is None:
        if undecided == "uncertain":
            points.reason = NO_TRACK_REASON
        elif answer.status == "no_narration_found" or undecided == "no_narration_found":
            points.reason = NO_NARRATION_REASON
        else:
            points.needs_listen = True
        return points
    measured = measure.tracks.get(int(answer.track))
    points.stretches = _stretches((measured or {}).get("moments") or [])
    if not points.stretches:
        points.reason = NO_SPEECH_REASON
    return points


# The helper commands ----------------------------------------------------------------------------------------------


def detect_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """The ``voice-track-detect`` helper: the shared detection, then what it measured kept in the library, one commit,
    before the run's next step. Moments are taken out of what is returned, so they can never reach a package's saved
    result or a portable ZIP."""

    result = voice_track.detect_from_request({**payload, "details": True})
    source = str(payload.get("source_path") or "")
    measured_by = str(payload.get("measured_by") or BY_BUGS)
    preferred = [int(value) for value in (payload.get("preferred_ordinals") or []) if str(value).strip().lstrip("-").isdigit()]
    if source:
        record_measure(source, result, measured_by=measured_by, run_id=str(payload.get("run_id") or ""),
                       duration=float(result.get("duration_seconds") or 0.0),
                       setting_roles=voice_track.parse_track_roles(payload.get("track_roles")), preferred=preferred)
    return voice_track.strip_details(result)


def _saved_layout_pick(source: Path, ffprobe: str, layouts_path: str) -> int | None:
    """Your saved answer for this recording's own track layout, as an ordinal (0 = Track 1), or None (design C1.5)."""

    from media_manglers_workbench import audio_detection  # noqa: PLC0415 - the same pattern as review_preparation

    if not layouts_path:
        from media_manglers_workbench.settings import default_settings_path  # noqa: PLC0415

        layouts_path = str(default_settings_path().parent / "narration-layouts.json")
    streams, _duration, profile, _format = audio_detection.probe_source(ffprobe or "ffprobe", source)
    saved = audio_detection.LayoutConfirmationStore(Path(layouts_path)).match(
        audio_detection.layout_fingerprint(streams, profile))
    try:
        ordinal = int(saved.get("audioOrdinal")) if saved else None
    except (TypeError, ValueError):
        return None
    return ordinal if ordinal is not None and any(stream.ordinal == ordinal for stream in streams) else None


def known_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """The ``voice-track-known`` helper, asked before a run listens. It says this recording's remembered pick (from the
    saved answer for its own track layout, else the pick the run gave, else none; Track 1 counts) and, when the rule
    already answers, a result of the same shape ``voice-track-detect`` returns, with no moments in it. It never reads
    the recording. A failure here only means the run listens, as it always did."""

    source = Path(str(payload.get("source_path") or ""))
    given = [int(value) for value in (payload.get("preferred_ordinals") or []) if str(value).strip().lstrip("-").isdigit()]
    fallback = [int(value) for value in (payload.get("fallback_ordinals") or []) if str(value).strip().lstrip("-").isdigit()]
    remembered = list(given)
    if not given and payload.get("use_saved_layouts"):
        try:
            pick = _saved_layout_pick(source, str(payload.get("ffprobe_exe") or ""), str(payload.get("layouts_path") or ""))
        except Exception as exc:  # noqa: BLE001 - no saved answer can be read: no remembered pick
            _log.warning("The saved track layouts could not be read (%s).", type(exc).__name__)
            pick = None
        remembered = [pick] if pick is not None else fallback
    titles: dict[int, str] | None = None
    try:
        streams, _duration = voice_track.probe_audio_streams(str(payload.get("ffprobe_exe") or "ffprobe"), source)
        titles = {index: str((stream.get("tags") or {}).get("title") or "") for index, stream in enumerate(streams)}
    except (OSError, ValueError, RuntimeError) as exc:
        _log.warning("The recording's tracks could not be read (%s).", type(exc).__name__)
    # The setting as saved ("2=narration,3=game"): an old raw bin row is checked against its Game audio entries.
    known = narration_answer(source, titles=titles, track_roles=payload.get("track_roles"), remembered=remembered) \
        if titles is not None else NarrationAnswer()
    return {"preferred_ordinals": remembered, "answer": known.detection if known.final else None,
            "decided_by": known.decided_by if known.final else ""}
