"""The Inbox's records in a test's own library (224, Wave B2b).

Since Wave B2b Review Media Inbox keeps its records in the library (its ``inbox_`` tables), and it opens nothing
until the one-time move of the old ledger is complete. A test Inbox has no old ledger, so its library is marked
the way the Workbench marks one with nothing to move (``ready``). Tests that read or change the Inbox's tables
directly open the library through ``connect``; their SQL names the ``inbox_`` tables.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
from typing import Any

from media_manglers.core import inbox_records, recording_records


def ready(where: Any = None) -> None:
    """Mark this test's library as having nothing to move (a receipt "complete", as a Workbench start with no
    ledger named writes), unless it already has a receipt. With ``where`` (an Inbox folder, a ledger path or
    settings) that Inbox folder is also registered, as a first Inbox run registers it."""

    connection = recording_records.connect(backup=False)
    try:
        if inbox_records.receipt(connection) is None:
            with connection:
                connection.execute(
                    "INSERT INTO legacy_imports(source, started_utc, finished_utc, status, counts_json, note) VALUES "
                    "(?, '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z', 'complete', ?, ?)",
                    (inbox_records.RECEIPT_SOURCE, json.dumps({"ledger": "none named"}),
                     "nothing to move: no Inbox ledger was named"))
    finally:
        connection.close()
    if where is not None:
        inbox_records.connect(where).close()


def library_file() -> Path:
    return recording_records.database_path()


def connect(*, read_only: bool = False) -> sqlite3.Connection:
    """This test's library, opened directly, as the old tests opened the ledger file."""

    path = library_file()
    if read_only:
        return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    return sqlite3.connect(str(path), timeout=30)


def fingerprint() -> str:
    """One SHA-256 over every row of every Inbox table in this test's library: what "the ledger's bytes are
    unchanged" proved when the records were a file of their own (the library file changes for its own reasons)."""

    from media_manglers.core import inbox_move, review_ledger

    connection = connect(read_only=True)
    try:
        parts = []
        for table in review_ledger.INBOX_TABLES.values():
            columns = [str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')]
            keys = [str(row[1]) for row in sorted(connection.execute(f'PRAGMA table_info("{table}")'),
                                                  key=lambda row: int(row[5])) if int(row[5])]
            parts.append(f"{table}:{inbox_move.fingerprint(connection, table, columns, keys)}")
        return "|".join(parts)
    finally:
        connection.close()


def use_own_library(case: Any, root: Path) -> Path:
    """Give this Inbox a library of its own under ``root`` (a test that makes a second Inbox, which in one library
    would belong to the folder registered first). Restored when ``case`` ends."""

    previous = os.environ.get(recording_records.LIBRARY_ROOT_ENV)
    library = Path(root) / "library"
    os.environ[recording_records.LIBRARY_ROOT_ENV] = str(library)

    def restore() -> None:
        inbox_records.release_all()
        if previous is None:
            os.environ.pop(recording_records.LIBRARY_ROOT_ENV, None)
        else:
            os.environ[recording_records.LIBRARY_ROOT_ENV] = previous

    case.addCleanup(restore)
    return library
