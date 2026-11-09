"""One front door to the library (242): no other code opens a database or writes the library's SQL.

Wave A1 puts ``recording_records`` in front of the library. ``raw_bin_library`` is its scan engine and
keeps the SQL for its own tables. Every other module asks the front door. Since Wave B2b (224) Review Media
Inbox's records are in the library too, in its ``inbox_`` tables, and only the Inbox's own modules name them.
Two files still open a database of their own, each listed by name, so a new one fails here until it is routed
or the list is changed on purpose: the Inbox's store (``inbox_records``), which opens only the OLD ledger file,
for the one-time move, and the Archive Catalog (frozen, 245) its catalog. The shared checked copy
(``safe_write``, 224) opens only the backup copy it is making; the database it copies reaches it already open.
"""

from __future__ import annotations

import ast
from pathlib import Path
import re
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "src"
CORE = "media_manglers/core/"
FRONT_DOOR = CORE + "recording_records.py"
SCAN_ENGINE = CORE + "raw_bin_library.py"
INBOX_STORE = CORE + "inbox_records.py"
INBOX_MOVE = CORE + "inbox_move.py"
INBOX_LEDGER = CORE + "review_ledger.py"
INBOX_RELOCATION = CORE + "review_relocation.py"
# Still opening a database of their own: the Inbox's store opens the OLD ledger file only, for the one-time move
# into the library (settle_file, read_only_file) and the move's checked copy of it (224, Wave B2b); and the
# Archive Catalog's own catalog (frozen, 245).
LEGACY_OWNERS = {
    INBOX_STORE,
    CORE + "archive_catalog.py",
}
# The shared checked copy (224, Wave B2a): it opens the copy it is making, to write it and to check it, and
# nothing else. The test below holds it to that.
CHECKED_COPY = CORE + "safe_write.py"
# The Inbox's own modules (224, Wave B2b): the only ones that name the Inbox's tables in the library.
INBOX_MODULES = {
    INBOX_STORE, INBOX_MOVE, INBOX_LEDGER, INBOX_RELOCATION,
    *(CORE + f"review_{name}.py" for name in ("inbox", "queue", "preparation", "findings", "targeted_evidence",
                                              "results", "finalization", "orchestration")),
}
# What an Inbox module may name of the library's own tables, and why:
INBOX_USES_OF_LIBRARY_TABLES = {
    INBOX_STORE: {"legacy_imports", "roots"},  # the move's receipt says whether the Inbox may open; its folder
    INBOX_MOVE: {"legacy_imports", "roots", "recordings"},  # the receipt, the folder, the Mined check
    INBOX_RELOCATION: {"roots"},  # the registered Inbox folder moves with a relocation
    INBOX_LEDGER: {"schema_metadata"},  # the old ledger's own table, inbox_metadata in the library
    # 264 (Wave C1): speech facts name their own tables and nothing else of the library's; what they need from the
    # others (a copy, a scan's pick) they ask the front door, and they open nothing themselves.
    CORE + "speech_facts.py": {"voice_measures", "voice_measure_tracks", "voice_decisions", "narration_answers"},
}
# 242 (Wave C2): the editor's index is written only through the front door (``index_editor_projects``); no other
# module names its tables.
# Every table of the library (F6: Wave A2's contents, marks and resume_points were missing here). Since Wave
# B2b the Inbox's own schema_metadata is inbox_metadata, so the library's schema_metadata is listed too.
LIBRARY_TABLES = ("recordings", "locations", "labels", "recording_labels", "scan_runs", "schema_steps", "runs",
                  "run_items", "run_events", "run_products", "roots", "legacy_imports", "contents", "marks",
                  "resume_points", "schema_metadata", "voice_measures", "voice_measure_tracks", "voice_decisions",
                  "narration_answers", "editor_projects", "editor_versions")
INBOX_TABLES = ("inbox_metadata", "inbox_legacy_reviews", "inbox_sources", "inbox_source_locations",
                "inbox_batches", "inbox_batch_sources", "inbox_attempts", "inbox_findings", "inbox_lifecycle_events",
                "inbox_final_results", "inbox_finalization_runs", "inbox_retention_records", "inbox_relocation_runs")
SQL_VERBS = r"\b(?:FROM|JOIN|INTO|UPDATE|TABLE(?:\s+IF\s+NOT\s+EXISTS)?)\s+"
LIBRARY_SQL = re.compile(SQL_VERBS + r"(" + "|".join(LIBRARY_TABLES) + r")\b")
INBOX_NAME = re.compile(r"\b(?:" + "|".join(sorted(INBOX_TABLES, key=len, reverse=True)) + r")\b")


def _sources() -> dict[str, str]:
    return {path.relative_to(SOURCE).as_posix(): path.read_text(encoding="utf-8")
            for path in sorted(SOURCE.rglob("*.py"))}


class OneOwnerTests(unittest.TestCase):
    def test_the_list_names_every_table_the_library_has(self) -> None:
        from media_manglers.core.recording_records import TABLE_PRIVACY
        from media_manglers.core.review_ledger import INBOX_TABLES as NAMES

        self.assertEqual(set(LIBRARY_TABLES) | set(INBOX_TABLES), set(TABLE_PRIVACY))
        self.assertEqual(set(INBOX_TABLES), set(NAMES.values()))
        self.assertEqual(len(LIBRARY_TABLES), len(set(LIBRARY_TABLES)))

    def test_only_the_front_door_and_the_listed_legacy_owners_open_a_database(self) -> None:
        opening = {name for name, text in _sources().items() if "sqlite3.connect(" in text}
        self.assertEqual(opening - LEGACY_OWNERS - {CHECKED_COPY}, {FRONT_DOOR})

    def test_the_inbox_store_opens_only_the_old_ledger_file(self) -> None:
        text = _sources()[INBOX_STORE]
        opening = {node.name for node in ast.walk(ast.parse(text)) if isinstance(node, ast.FunctionDef)
                   and "sqlite3.connect(" in (ast.get_source_segment(text, node) or "")}
        self.assertEqual(opening, {"settle_file", "read_only_file"})

    def test_the_checked_copy_opens_only_the_copy_it_is_making(self) -> None:
        opened = re.findall(r"sqlite3\.connect\((\w+(?:\(\w+\))?)", _sources()[CHECKED_COPY])
        self.assertEqual(opened, ["partial", "read_only_address(partial)"])

    def test_only_the_front_door_and_the_scan_engine_write_the_librarys_sql(self) -> None:
        allowed = {FRONT_DOOR, SCAN_ENGINE, CORE + "archive_catalog.py"}
        offenders: dict[str, set[str]] = {}
        for name, text in _sources().items():
            if name in allowed:
                continue
            named = {match.group(1) for match in LIBRARY_SQL.finditer(text)}
            extra = named - INBOX_USES_OF_LIBRARY_TABLES.get(name, set())
            if extra:
                offenders[name] = extra
        self.assertEqual(offenders, {})

    def test_only_the_inbox_and_the_front_door_name_the_inboxs_tables(self) -> None:
        naming = {name for name, text in _sources().items() if INBOX_NAME.search(text)}
        self.assertEqual(naming - INBOX_MODULES - {FRONT_DOOR}, set())
        self.assertIn(CORE + "review_preparation.py", naming)

    def test_the_library_reads_the_inboxs_records_over_the_callers_connection(self) -> None:
        sources = _sources()
        calls = re.compile(r"\bconnect_ledger\s*\(|import[^\n]*\bconnect_ledger\b")
        self.assertIsNone(calls.search(sources[FRONT_DOOR]))
        self.assertIsNone(calls.search(sources[SCAN_ENGINE]))
        self.assertIn("?mode=ro", sources[FRONT_DOOR])
        tree = ast.parse(sources[FRONT_DOOR])
        adapters = {node.name: ast.get_source_segment(sources[FRONT_DOOR], node) or "" for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name in {"inbox_reviewed", "inbox_run_outcomes"}}
        self.assertEqual(set(adapters), {"inbox_reviewed", "inbox_run_outcomes"})
        for name, body in adapters.items():
            with self.subTest(adapter=name):
                self.assertIn("connection: sqlite3.Connection", body.split(")")[0])
                self.assertNotIn("sqlite3.connect(", body)
                self.assertIsNone(re.search(r"\bconnect(?:_read_only)?\(", body), "it opens nothing itself")
                self.assertNotIn("inbox_records.", body)


if __name__ == "__main__":
    unittest.main()
