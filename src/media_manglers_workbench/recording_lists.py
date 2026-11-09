"""The never-use list, the already-done map and the stopped run, in one place (114, 125, 244).

Find my bug reports keeps two lists about recordings: the recordings the
operator never wants offered again, and the recordings already turned into a
package. The built-in player can mark a recording never-use as well, so both go
through these helpers and can never disagree about what "the same recording"
means or how the lists are kept.

Since Wave A2 (244) the lists and the stopped run Continue picks up live in
the Workbench's library: the host's ``records``, once its ``lists_in_library()``
says the old settings were moved in. While they could not be moved (the library
could not be opened, or the move did not check out this time) they stay in the
settings as before. Every helper takes either one: the library, or the settings
mapping. ``lists_of`` says which a host has now.

No Qt and no project import here, so every rule is testable in milliseconds and
every page can import it without a cycle: the library is asked through its own
methods. The settings file is JSON a person can edit by hand, so every reader
tolerates a missing key, a value of the wrong type and members that are not
text. Reading never raises. A change the library could not save raises
``ListsNotSaved``, an OSError, and changes nothing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
from pathlib import Path, PurePath
import sqlite3
from typing import Any

# list[str]: each recording path exactly as Find my bug reports stored it.
EXCLUDED_KEY = "bug_report_excluded_recordings"
# dict[str, str]: recording path -> the "YYYY-MM-DD" day it became a package.
PROCESSED_KEY = "bug_report_processed_recordings"
# {"folder", "recordings", "tracks"}: the stopped run Continue picks up (115).
STOPPED_RUN_KEY = "bug_report_stopped_run"
LIBRARY_ERRORS = (sqlite3.Error, OSError, ValueError)


class ListsNotSaved(OSError):
    """The library could not save a change to the lists; nothing was changed."""


def path_key(path: Path | str) -> str:
    """The one rule for "is this the same recording": its text, lower-cased.

    Windows ignores case in a path and callers hand over resolved paths, so
    case is the only difference that turns up in practice. Slashes are left
    alone on purpose: a ``Path`` already spells them the way this PC does.
    """

    return str(path).lower()


def held_in_settings(settings: Any) -> bool:
    """Whether the settings still hold either list: they were never moved into the library, so they are read
    there, even while the library cannot be opened (224, Wave B2a, note 12)."""

    return isinstance(settings, Mapping) and bool(excluded_paths(settings) or processed_dates(settings))


def in_library(lists: Any) -> bool:
    """Whether these lists are the library's, not a settings mapping."""

    return not isinstance(lists, Mapping) and callable(getattr(lists, "never_use_keys", None))


def lists_of(host: Any, fallback: MutableMapping[str, Any] | None = None) -> Any:
    """Where ``host`` keeps the lists now: its library once the old settings were moved in, else its
    settings (read fresh: the host replaces that dictionary when settings are imported), else
    ``fallback``."""

    records = getattr(host, "records", None)
    moved = getattr(host, "lists_in_library", None)
    if records is not None and in_library(records) and callable(moved) and moved():
        return records
    settings = getattr(host, "app_settings", None)
    if isinstance(settings, MutableMapping):
        return settings
    return fallback if fallback is not None else {}


def _read(call: Any, default: Any) -> Any:
    try:
        return call()
    except LIBRARY_ERRORS:
        return default


def _write(call: Any) -> Any:
    try:
        return call()
    except ListsNotSaved:
        raise
    except LIBRARY_ERRORS as exc:
        raise ListsNotSaved(f"The library could not save that: {exc}") from exc


def _stored(settings: Mapping[str, Any], key: str) -> Any:
    # A stand-in host can carry settings that are not a mapping at all; that
    # reads as "nothing stored" rather than as an error.
    return settings.get(key) if isinstance(settings, Mapping) else None


def _path_text(member: Any) -> str:
    """One stored member as text, or "" when it cannot be a recording path."""

    if isinstance(member, PurePath):
        return str(member)
    # A hand-edited file can hold null, a number or a nested list here. None
    # of those names a recording, and turning them into text would put a row
    # called "None" on the never-use list.
    return member if isinstance(member, str) and member.strip() else ""


def _settings_excluded(settings: Mapping[str, Any]) -> list[str]:
    value = _stored(settings, EXCLUDED_KEY)
    if not isinstance(value, (list, tuple)):
        return []
    return [text for text in (_path_text(member) for member in value) if text]


def excluded_entries(lists: Any) -> list[dict[str, Any]]:
    """The never-use list, oldest first: each entry's path to show and, in the library, its mark."""

    if in_library(lists):
        return [{"path": str(entry["path"]), "mark_id": entry["mark_id"]}
                for entry in _read(lists.never_use_entries, [])]
    return [{"path": text, "mark_id": None} for text in _settings_excluded(lists)]


def excluded_paths(lists: Any) -> list[str]:
    """The never-use list as stored, oldest first. Always a fresh list."""

    return [entry["path"] for entry in excluded_entries(lists)]


def excluded_keys(lists: Any) -> set[str]:
    if in_library(lists):
        return set(_read(lists.never_use_keys, set()))
    return {path_key(item) for item in excluded_paths(lists)}


def is_excluded(lists: Any, path: Path | str) -> bool:
    return path_key(path) in excluded_keys(lists)


def add_excluded(lists: Any, path: Path | str, *, by: str = "") -> bool:
    """Put a recording on the never-use list; True when it was not there yet.

    The text is stored exactly as given. Find my bug reports hands over the
    resolved path and later compares resolved paths against this list, so
    tidying the text here would let a never-use recording be added again.
    """

    text = str(path)
    if in_library(lists):
        if not text.strip():
            return False
        return bool(_write(lambda: lists.set_never_use(text, True, by=by or "Workbench")))
    if not text.strip() or not isinstance(lists, MutableMapping):
        return False
    current = excluded_paths(lists)
    if path_key(text) in {path_key(item) for item in current}:
        return False
    # A fresh list, never an in-place append: the stored value can be shared
    # with a defaults dictionary, or not be a list at all.
    lists[EXCLUDED_KEY] = [*current, text]
    return True


def remove_excluded(lists: Any, path: Path | str, *, by: str = "", mark_id: int | None = None) -> bool:
    """Allow a recording again; True when it was on the list.

    Every spelling of the same recording goes, not just the first, so a list
    that picked up the same path in two cases is cleared in one go. In the
    library ``mark_id`` also clears that entry of the list itself (a copy whose
    file was replaced since keeps its mark under the path it had).
    """

    if in_library(lists):
        marks = () if mark_id is None else (int(mark_id),)
        return bool(_write(lambda: lists.set_never_use(str(path), False, by=by or "Workbench", mark_ids=marks)))
    if not isinstance(lists, MutableMapping):
        return False
    current = excluded_paths(lists)
    wanted = path_key(path)
    remaining = [item for item in current if path_key(item) != wanted]
    if len(remaining) == len(current):
        return False
    lists[EXCLUDED_KEY] = remaining
    return True


def processed_dates(lists: Any) -> dict[str, str]:
    """The already-done map, keyed by path key so a lookup ignores case.

    Only this copy is lower-cased; the stored map keeps each path the way it
    was written and is never rewritten from here. An entry whose date is not
    text says nothing usable about when, so it is left out. In the library a
    recording identical to one already done counts too (244, decision E).
    """

    if in_library(lists):
        return dict(_read(lists.done_dates, {}))
    value = _stored(lists, PROCESSED_KEY)
    if not isinstance(value, Mapping):
        return {}
    dates: dict[str, str] = {}
    for stored_path, date in value.items():
        text = _path_text(stored_path)
        if text and isinstance(date, str) and date.strip():
            dates[path_key(text)] = date
    return dates


def processed_on(lists: Any, path: Path | str, *, look: bool = True) -> str:
    """The day this recording became a package, or "" when it never did.

    Without ``look`` the recording's file is not looked at (the drive may be
    asleep), so in the library a recording only done through an identical copy
    says nothing yet.
    """

    if in_library(lists):
        return str(_read(lambda: lists.done_on(path, look=look), "") or "")
    return processed_dates(lists).get(path_key(path), "")


def recording_status_text(lists: Any, path: Path | str, *, look: bool = True) -> str:
    """What to say about a recording that is not being worked on right now."""

    done_on = processed_on(lists, path, look=look)
    return f"Done on {done_on}" if done_on else "Ready"


def mark_processed(lists: Any, rows: Iterable[tuple[Path | str, str]], *, day: str, run_id: str = "",
                   by: str = "") -> None:
    """These recordings became a package on ``day``: each one ``(path, "done" | "no_narration")``.

    The settings map keeps the day alone, under the path as given (114); the
    library keeps the outcome and the run as well.
    """

    rows = [(str(path), outcome) for path, outcome in rows]
    if in_library(lists):
        _write(lambda: lists.mark_done(run_id, rows, by=by or "Find my bug reports", day=day))
        return
    if not isinstance(lists, MutableMapping):
        return
    processed = dict(lists.get(PROCESSED_KEY) or {})
    for path, _outcome in rows:
        processed[path] = day
    lists[PROCESSED_KEY] = processed


def stopped_run(lists: Any) -> Any:
    """The stopped run Continue picks up, {"folder", "recordings", "tracks"}, or None."""

    if in_library(lists):
        return _read(lists.stopped_bug_run, None)
    return _stored(lists, STOPPED_RUN_KEY)


def set_stopped_run(lists: Any, record: dict[str, Any] | None, *, run_id: str = "") -> None:
    """Keep a stopped run for Continue, or forget it (None)."""

    if in_library(lists):
        _write(lambda: lists.set_stopped_bug_run(record, run_id=run_id))
        return
    if not isinstance(lists, MutableMapping):
        return
    if record is None:
        lists.pop(STOPPED_RUN_KEY, None)
    else:
        lists[STOPPED_RUN_KEY] = record
