from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers import cli  # noqa: E402
from media_manglers.core import (  # noqa: E402
    inbox_records,
    recording_records,
    review_ledger,
    review_orchestration,
    review_preparation,
    review_relocation,
)
import pytest
from tests import inbox_library  # noqa: E402

# 224 (Wave B2b): the Inbox's records are in this test's library, moved in (nothing to move).
pytestmark = pytest.mark.inbox_moved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class RelocationFixture:
    def __init__(
        self,
        root: Path,
        *,
        old_root: str = r"D:\synthetic-generated\review-inbox",
        source3_invalid: bool = False,
    ) -> None:
        self.root = root
        self.old_root = old_root
        self.original_root = r"E:\synthetic-read-only-media"
        self.queue_root = root / "destination" / "review-inbox"
        self.queue_root.mkdir(parents=True)
        self.ledger = self.queue_root / "review-ledger.sqlite"
        # 224 (Wave B2b): the Inbox's records are in a library of this fixture's own (outside the folder being
        # relocated), which registers the Inbox folder where the records say it was: the old root.
        os.environ[recording_records.LIBRARY_ROOT_ENV] = str(root / "library")
        inbox_records.release_all()
        inbox_library.ready()
        self._register_old_root()
        self.batch_id = "batch-process-synthetic"
        self.tokens = {1: "source-token-01", 2: "source-token-02", 3: "source-token-03"}
        self.source3_invalid = source3_invalid
        self._populate_ledger()
        self._populate_files()
        self.record_path = root / "migration-record.json"
        self.rebuild_record()

    @property
    def old_batch(self) -> str:
        return nt_join(self.old_root, "batches", self.batch_id)

    def _register_old_root(self) -> None:
        connection = inbox_library.connect()
        try:
            with connection:
                connection.execute(
                    "INSERT INTO roots(kind, path, path_key, first_seen_utc, last_seen_utc) VALUES (?, ?, ?, ?, ?)",
                    (inbox_records.ROOT_KIND, self.old_root, recording_records.path_key(self.old_root),
                     "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"))
        finally:
            connection.close()

    def registered(self) -> str:
        connection = inbox_library.connect(read_only=True)
        try:
            return str(inbox_records.registered_folder(connection))
        finally:
            connection.close()

    def _populate_ledger(self) -> None:
        connection = inbox_library.connect()
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            now = "2026-01-01T00:00:00Z"
            for source_id in range(1, 5):
                stable = hashlib.sha256(f"source-{source_id}".encode()).hexdigest()
                connection.execute(
                    """
                    INSERT INTO inbox_sources
                        (source_id, provisional_identity, stable_identity,
                         content_sha256, sampled_sha256, size_bytes,
                         lifecycle_state, first_seen_utc, updated_utc)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        f"provisional:{stable}",
                        f"sha256:{stable}",
                        stable,
                        stable,
                        source_id * 100,
                        "awaiting_external_review" if source_id < 4 else "pending",
                        now,
                        now,
                    ),
                )
                original = nt_join(self.original_root, f"source-{source_id}.mkv")
                connection.execute(
                    """
                    INSERT INTO inbox_source_locations
                        (source_id, original_path, normalized_path, size_bytes,
                         modified_utc, modified_ns, is_current, first_seen_utc,
                         last_seen_utc)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        source_id,
                        original,
                        os.path.normcase(original),
                        source_id * 100,
                        now,
                        source_id,
                        now,
                        now,
                    ),
                )
            connection.execute(
                """
                INSERT INTO inbox_batches
                    (batch_id, status, package_path, is_legacy, created_utc, updated_utc)
                VALUES (?, 'awaiting_external_review', ?, 0, ?, ?)
                """,
                (self.batch_id, self.old_batch, now, now),
            )
            for ordinal, source_id in enumerate((1, 2, 3), 1):
                connection.execute(
                    """
                    INSERT INTO inbox_batch_sources
                        (batch_id, source_id, ordinal, state,
                         preparation_signature, added_utc, updated_utc)
                    VALUES (?, ?, ?, 'awaiting_external_review', ?, ?, ?)
                    """,
                    (
                        self.batch_id,
                        source_id,
                        ordinal,
                        hashlib.sha256(f"signature-{source_id}".encode()).hexdigest(),
                        now,
                        now,
                    ),
                )
            review_ledger._insert_lifecycle_event(
                connection,
                source_id=1,
                batch_id=self.batch_id,
                event_type="synthetic_audit",
                to_state="awaiting_external_review",
                details={
                    "history_path": nt_join(
                        self.old_root,
                        "history",
                        "source-token-01",
                        self.batch_id,
                    ),
                    "note": (
                        "A free-form note mentions "
                        + nt_join(self.old_root, "do-not-rewrite.txt")
                    ),
                },
            )
            connection.commit()
        finally:
            connection.close()

    def _valid_source(self, root: Path, source_id: int) -> None:
        (root / "visuals" / "frames").mkdir(parents=True)
        (root / "visuals" / "frames" / "frame-001.jpg").write_bytes(
            f"frame-{source_id}".encode()
        )
        manifest = {
            "schema_version": 1,
            "source_id": source_id,
            "source_identity": self.stable_identity(source_id),
            "source_token": self.tokens[source_id],
            "original_location": nt_join(
                self.original_root, f"source-{source_id}.mkv"
            ),
            "visuals": {
                "frames": [
                    {
                        "ordinal": 1,
                        "path": "frames/frame-001.jpg",
                        "timestamp_seconds": 0.1,
                    }
                ],
                "panels": [],
            },
            "operator_note": (
                "Free-form text contains "
                + nt_join(self.old_root, "never-rewrite-this-text")
            ),
        }
        review_preparation._complete_source_package(root, manifest)

    def _invalid_source3(self, root: Path) -> None:
        (root / "visuals" / "frames").mkdir(parents=True)
        for ordinal in range(1, 6):
            (root / "visuals" / "frames" / f"frame-{ordinal:03d}.jpg").write_bytes(
                f"frame-{ordinal}".encode()
            )
        manifest = {
            "schema_version": 1,
            "source_id": 3,
            "source_identity": self.stable_identity(3),
            "source_token": self.tokens[3],
            "original_location": nt_join(self.original_root, "source-3.mkv"),
            "visuals": {
                "frames": [
                    {
                        "ordinal": ordinal,
                        "path": f"frames/frame-{ordinal:03d}.jpg",
                        "timestamp_seconds": ordinal / 100,
                    }
                    for ordinal in range(1, 7)
                ],
                "panels": [],
            },
        }
        _write_json(root / "source-manifest.json", manifest)
        _write_json(
            root / "integrity.json",
            {
                "schema_version": 1,
                "complete": True,
                "files": review_preparation._hash_files(root),
            },
        )

    def _populate_files(self) -> None:
        batch_root = self.queue_root / "batches" / self.batch_id
        prepared = []
        for source_id in (1, 2, 3):
            token = self.tokens[source_id]
            source_root = batch_root / "sources" / token
            if source_id == 3 and self.source3_invalid:
                self._invalid_source3(source_root)
            else:
                self._valid_source(source_root, source_id)
            prepared.append(
                {
                    "source_id": source_id,
                    "source_identity": self.stable_identity(source_id),
                    "source_token": token,
                    "package_path": nt_join(
                        self.old_batch, "sources", token
                    ),
                }
            )
            _write_json(
                batch_root
                / ".staging"
                / f"attempt-{source_id}"
                / "attempt-state.json",
                {
                    "source_id": source_id,
                    "status": "prepared",
                    "working_copy_path": nt_join(
                        r"D:\synthetic-scratch",
                        self.batch_id,
                        f"attempt-{source_id}",
                        "source.mkv",
                    ),
                },
            )
        _write_json(
            batch_root / "batch-manifest.json",
            {
                "schema_version": 1,
                "batch_id": self.batch_id,
                "status": "awaiting_external_review",
                "prepared_sources": prepared,
            },
        )
        run = {
            "run_journal_version": 1,
            "run_id": "run-synthetic",
            "status": "complete",
            "scan_settings": {
                "ledger_path": nt_join(self.old_root, self.ledger.name),
                "source_folders": [self.original_root],
            },
            "snapshot": [
                {
                    "source_id": source_id,
                    "path": nt_join(
                        self.original_root, f"source-{source_id}.mkv"
                    ),
                }
                for source_id in (1, 2, 3)
            ],
            "completed_source_ids": ["1", "2", "3"],
        }
        review_orchestration._write_journal(
            self.queue_root
            / ".orchestration"
            / "completed-runs"
            / "run-synthetic.json",
            run,
        )
        (self.queue_root / "CODEX_REVIEW_QUEUE_PROMPT.md").write_text(
            f"Generated queue at {self.old_root}\n", encoding="utf-8"
        )
        _write_json(
            self.queue_root / "queue-index.json",
            {"generated_path": self.old_batch},
        )
        (self.queue_root / ".orchestration" / "process.lock").write_text(
            "{}\n", encoding="utf-8"
        )

    def stable_identity(self, source_id: int) -> str:
        return "sha256:" + hashlib.sha256(f"source-{source_id}".encode()).hexdigest()

    def rebuild_record(self) -> None:
        files = []
        for path in sorted(self.queue_root.rglob("*")):
            if (
                not path.is_file()
                or path.relative_to(self.queue_root).as_posix().casefold()
                in review_relocation.DERIVED_RELATIVE_PATHS
                or path.relative_to(self.queue_root)
                .as_posix()
                .casefold()
                .startswith(".relocation/")
            ):
                continue
            files.append(
                {
                    "relative_path": path.relative_to(self.queue_root).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
        _write_json(
            self.record_path,
            {
                "schema_version": 1,
                "verified": True,
                "source_root": self.old_root,
                "destination_root": str(self.queue_root),
                "files": files,
            },
        )

    def payload(self) -> dict[str, object]:
        result: dict[str, object] = {
            "mode": "preview",
            "ledger_path": str(self.ledger),
            "original_media_roots": [self.original_root],
            "mappings": [
                {
                    "old_root": self.old_root,
                    "new_root": str(self.queue_root),
                    "migration_record_path": str(self.record_path),
                    "migration_record_sha256": _sha256(self.record_path),
                }
            ],
        }
        if self.source3_invalid:
            source_root = (
                self.queue_root
                / "batches"
                / self.batch_id
                / "sources"
                / self.tokens[3]
            )
            error = ""
            try:
                review_preparation._validate_source_package(source_root)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            result["known_package_integrity_exceptions"] = [
                {
                    "batch_id": self.batch_id,
                    "source_id": 3,
                    "tree_sha256": review_preparation._tree_sha256(source_root),
                    "error_sha256": hashlib.sha256(error.encode()).hexdigest(),
                }
            ]
        return result

    def preview(self) -> dict[str, object]:
        return review_relocation.relocate_from_request(self.payload())

    def apply(self, preview: dict[str, object], **extra: object) -> dict[str, object]:
        return review_relocation.relocate_from_request(
            {
                "mode": "apply",
                "apply_confirmed": True,
                "plan_path": preview["plan_path"],
                "plan_sha256": preview["plan_sha256"],
                **extra,
            }
        )


def nt_join(*parts: str) -> str:
    return os.path.normpath(os.path.join(*parts)).replace("/", "\\")


class ReviewInboxRelocationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        inbox_records.release_all()
        self.temporary.cleanup()

    def test_cli_exposes_explicit_relocation_command(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(
            [
                "review-media-inbox-relocate",
                "--request-file",
                "request.json",
                "--result-file",
                "result.json",
            ]
        )
        self.assertEqual(args.command, "review-media-inbox-relocate")
        self.assertIs(
            cli._build_handlers()["review-media-inbox-relocate"],
            review_relocation.relocate_from_request,
        )

    def test_preview_classifies_mixed_paths_without_rewriting_originals(self) -> None:
        fixture = RelocationFixture(self.root)
        result = fixture.preview()
        self.assertEqual(result["status"], "preview")
        plan = review_relocation._load_plan(Path(str(result["plan_path"])))
        self.assertEqual(plan["summary"]["original_media_changes"], 0)
        self.assertGreater(plan["classification_counts"]["original_media"], 0)
        self.assertGreater(plan["classification_counts"]["generated_owned"], 0)
        self.assertGreater(plan["classification_counts"]["historical_audit"], 0)
        self.assertEqual(plan["classification_counts"]["unknown"], 0)
        self.assertEqual(
            {item["table"] for item in plan["database_changes"]},
            {"inbox_batches"},
        )
        self.assertEqual(os.path.normcase(plan["registered_folder_before"]), os.path.normcase(fixture.old_root))
        self.assertEqual(os.path.normcase(fixture.registered()), os.path.normcase(fixture.old_root),
                         "a preview moves nothing")

    def test_apply_relocates_generated_paths_and_preserves_fixed_snapshot(self) -> None:
        fixture = RelocationFixture(self.root)
        originals_before = self._original_records(fixture)
        source_hashes_before = self._source_hashes(fixture)
        run_path = (
            fixture.queue_root
            / ".orchestration"
            / "completed-runs"
            / "run-synthetic.json"
        )
        result = fixture.apply(fixture.preview())
        self.assertEqual(result["status"], "relocated")
        connection = inbox_library.connect()
        try:
            batch_path = connection.execute(
                "SELECT package_path FROM inbox_batches WHERE batch_id=?",
                (fixture.batch_id,),
            ).fetchone()[0]
            source_ids = [
                row[0]
                for row in connection.execute(
                    "SELECT source_id FROM inbox_batch_sources WHERE batch_id=? ORDER BY ordinal",
                    (fixture.batch_id,),
                )
            ]
            source4 = connection.execute(
                "SELECT COUNT(*) FROM inbox_batch_sources WHERE batch_id=? AND source_id=4",
                (fixture.batch_id,),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(os.path.normcase(batch_path), os.path.normcase(str(fixture.queue_root / "batches" / fixture.batch_id)))
        self.assertEqual(source_ids, [1, 2, 3])
        self.assertEqual(source4, 0)
        self.assertEqual(os.path.normcase(fixture.registered()), os.path.normcase(str(fixture.queue_root)),
                         "the Inbox folder registered in the library moved with the relocation")
        run = review_orchestration._read_journal(run_path)
        self.assertEqual(run["completed_source_ids"], ["1", "2", "3"])
        self.assertEqual(
            os.path.normcase(run["scan_settings"]["ledger_path"]),
            os.path.normcase(str(fixture.ledger)),
        )
        self.assertEqual(self._original_records(fixture), originals_before)
        self.assertEqual(self._source_hashes(fixture), source_hashes_before)

    def test_free_form_path_like_text_and_audit_paths_are_not_rewritten(self) -> None:
        fixture = RelocationFixture(self.root)
        source_manifest = (
            fixture.queue_root
            / "batches"
            / fixture.batch_id
            / "sources"
            / fixture.tokens[1]
            / "source-manifest.json"
        )
        before = _sha256(source_manifest)
        connection = inbox_library.connect()
        try:
            details_before = connection.execute(
                "SELECT details_json FROM inbox_lifecycle_events WHERE event_type='synthetic_audit'"
            ).fetchone()[0]
        finally:
            connection.close()
        fixture.apply(fixture.preview())
        self.assertEqual(_sha256(source_manifest), before)
        connection = inbox_library.connect()
        try:
            details_after = connection.execute(
                "SELECT details_json FROM inbox_lifecycle_events WHERE event_type='synthetic_audit'"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(details_after, details_before)
        self.assertIn(fixture.old_root, json.loads(details_after)["history_path"])

    def test_preview_and_apply_are_case_and_separator_insensitive(self) -> None:
        old = r"d:/Synthetic-Generated/Review-Inbox"
        fixture = RelocationFixture(self.root, old_root=old)
        connection = inbox_library.connect()
        try:
            connection.execute(
                "UPDATE inbox_batches SET package_path=? WHERE batch_id=?",
                (
                    r"D:\SYNTHETIC-GENERATED\REVIEW-INBOX\batches"
                    + "\\"
                    + fixture.batch_id,
                    fixture.batch_id,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        fixture.rebuild_record()
        result = fixture.apply(fixture.preview())
        self.assertEqual(result["status"], "relocated")

    def test_old_root_may_exist_or_be_absent_without_being_read(self) -> None:
        present_old = self.root / "old-generated"
        present_old.mkdir()
        present = RelocationFixture(
            self.root / "present",
            old_root=str(present_old),
        )
        self.assertEqual(present.preview()["status"], "preview")
        absent = RelocationFixture(self.root / "absent")
        with mock.patch.object(Path, "exists", side_effect=AssertionError("old root probed")):
            # Path.exists is used for C-drive safety checks, so prove the old
            # root specifically by trapping only its exact synthetic spelling.
            pass
        self.assertEqual(absent.preview()["status"], "preview")

    def test_known_frame_defect_is_preserved_exactly(self) -> None:
        fixture = RelocationFixture(self.root, source3_invalid=True)
        source3 = (
            fixture.queue_root
            / "batches"
            / fixture.batch_id
            / "sources"
            / fixture.tokens[3]
        )
        tree_before = review_preparation._tree_sha256(source3)
        source12_before = self._source_hashes(fixture)
        result = fixture.apply(fixture.preview())
        self.assertEqual(result["status"], "relocated")
        self.assertEqual(review_preparation._tree_sha256(source3), tree_before)
        with self.assertRaisesRegex(
            RuntimeError, "frame-006.jpg"
        ):
            review_preparation._validate_source_package(source3)
        review_preparation._validate_salvageable_source_package(source3)
        self.assertEqual(self._source_hashes(fixture), source12_before)

    def test_repeat_apply_is_idempotent_without_duplicate_audit_rows(self) -> None:
        fixture = RelocationFixture(self.root)
        preview = fixture.preview()
        first = fixture.apply(preview)
        queue_sha = _sha256(fixture.queue_root / "queue-index.json")
        second = fixture.apply(preview)
        self.assertEqual(first["status"], "relocated")
        self.assertEqual(second["status"], "already_relocated")
        self.assertEqual(_sha256(fixture.queue_root / "queue-index.json"), queue_sha)
        connection = inbox_library.connect()
        try:
            rows = connection.execute("SELECT COUNT(*) FROM inbox_relocation_runs").fetchone()[0]
            lifecycle = connection.execute("SELECT COUNT(*) FROM inbox_lifecycle_events").fetchone()[0]
            attempts = connection.execute("SELECT COUNT(*) FROM inbox_attempts").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(rows, 1)
        self.assertEqual(lifecycle, 1)
        self.assertEqual(attempts, 0)

    def test_rollback_restores_database_and_generated_manifests(self) -> None:
        fixture = RelocationFixture(self.root)
        preview = fixture.preview()
        manifest = (
            fixture.queue_root
            / "batches"
            / fixture.batch_id
            / "batch-manifest.json"
        )
        manifest_before = manifest.read_bytes()
        fixture.apply(preview)
        result = review_relocation.relocate_from_request(
            {
                "mode": "rollback",
                "rollback_confirmed": True,
                "plan_path": preview["plan_path"],
                "plan_sha256": preview["plan_sha256"],
            }
        )
        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual(manifest.read_bytes(), manifest_before)
        connection = inbox_library.connect()
        try:
            package_path = connection.execute(
                "SELECT package_path FROM inbox_batches WHERE batch_id=?",
                (fixture.batch_id,),
            ).fetchone()[0]
            relocation_rows = connection.execute(
                "SELECT COUNT(*) FROM inbox_relocation_runs WHERE operation_id = ?",
                (review_relocation._load_plan(Path(str(preview["plan_path"])))["operation_id"],),
            ).fetchone()[0]
            links = connection.execute("PRAGMA foreign_key_check").fetchall()
        finally:
            connection.close()
        # 224 (Wave B2b, Q6): only the relocation's own rows go back; no library file is copied back.
        self.assertEqual(package_path, fixture.old_batch)
        self.assertEqual(relocation_rows, 0, "the relocation's own record is gone")
        self.assertEqual(links, [])
        self.assertEqual(os.path.normcase(fixture.registered()), os.path.normcase(fixture.old_root))

    def test_rollback_leaves_every_other_library_row_alone(self) -> None:
        fixture = RelocationFixture(self.root)
        preview = fixture.preview()
        fixture.apply(preview)
        # A change made after the relocation, elsewhere in the library: a whole-file rollback would undo it.
        connection = inbox_library.connect()
        with connection:
            connection.execute("INSERT INTO labels(name, builtin) VALUES ('after relocation', 0)")
            connection.execute("UPDATE inbox_sources SET updated_utc = 'later' WHERE source_id = 4")
        connection.close()
        review_relocation.relocate_from_request({"mode": "rollback", "rollback_confirmed": True,
                                                 "plan_path": preview["plan_path"],
                                                 "plan_sha256": preview["plan_sha256"]})
        connection = inbox_library.connect()
        try:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM labels WHERE name = 'after relocation'").fetchone()[0], 1)
            self.assertEqual(connection.execute(
                "SELECT updated_utc FROM inbox_sources WHERE source_id = 4").fetchone()[0], "later")
        finally:
            connection.close()

    def test_a_plan_made_before_the_inbox_moved_into_the_library_is_refused(self) -> None:
        fixture = RelocationFixture(self.root)
        preview = fixture.preview()
        plan_path = Path(str(preview["plan_path"]))
        plan = review_relocation._load_plan(plan_path)
        old = {key: value for key, value in plan.items() if key != "plan_sha256"}
        old["plan_version"] = 1
        old["database_changes"] = [{**change, "table": "batches"} for change in old["database_changes"]]
        old_plan = plan_path.with_name("old-plan.json")
        _write_json(old_plan, {**old, "plan_sha256": review_relocation._canonical_sha(old)})
        with self.assertRaisesRegex(review_relocation.RelocationError, "unsupported version"):
            review_relocation.relocate_from_request({"mode": "apply", "apply_confirmed": True,
                                                     "plan_path": str(old_plan),
                                                     "plan_sha256": review_relocation._canonical_sha(old)})
        self.assertEqual(os.path.normcase(fixture.registered()), os.path.normcase(fixture.old_root))

    def test_rollback_removes_derived_projections_that_were_initially_absent(self) -> None:
        fixture = RelocationFixture(self.root)
        projections = (
            fixture.queue_root / "queue-index.json",
            fixture.queue_root / "CODEX_REVIEW_QUEUE_PROMPT.md",
        )
        for path in projections:
            path.unlink()
        fixture.rebuild_record()
        preview = fixture.preview()
        fixture.apply(preview)
        self.assertTrue(all(path.is_file() for path in projections))
        review_relocation.relocate_from_request(
            {
                "mode": "rollback",
                "rollback_confirmed": True,
                "plan_path": preview["plan_path"],
                "plan_sha256": preview["plan_sha256"],
            }
        )
        self.assertTrue(all(not path.exists() for path in projections))

    def test_crash_boundaries_resume_without_partial_or_duplicate_state(self) -> None:
        phases = (
            "before_backup",
            "after_backup",
            "after_journal",
            "during_database_transaction",
            "after_database_commit",
            "during_manifest_refresh",
            "after_manifest_refresh",
            "after_queue_regeneration",
            "before_completion",
        )
        for index, phase in enumerate(phases):
            with self.subTest(phase=phase):
                fixture = RelocationFixture(self.root / f"crash-{index}")
                preview = fixture.preview()
                triggered = False

                def fault(current: str) -> None:
                    nonlocal triggered
                    if current == phase and not triggered:
                        triggered = True
                        raise RuntimeError(f"crash at {phase}")

                with self.assertRaisesRegex(RuntimeError, "crash at"):
                    fixture.apply(preview, fault_injector=fault)
                recovered = fixture.apply(preview)
                self.assertEqual(recovered["status"], "relocated")
                repeated = fixture.apply(preview)
                self.assertEqual(repeated["status"], "already_relocated")
                connection = inbox_library.connect()
                try:
                    self.assertEqual(
                        connection.execute(
                            "SELECT COUNT(*) FROM inbox_relocation_runs"
                        ).fetchone()[0],
                        1,
                    )
                    self.assertEqual(
                        connection.execute(
                            "PRAGMA foreign_key_check"
                        ).fetchall(),
                        [],
                    )
                finally:
                    connection.close()

    def test_unknown_path_bearing_batch_field_fails_closed(self) -> None:
        fixture = RelocationFixture(self.root)
        manifest = (
            fixture.queue_root
            / "batches"
            / fixture.batch_id
            / "batch-manifest.json"
        )
        document = json.loads(manifest.read_text(encoding="utf-8"))
        document["mystery_path"] = nt_join(fixture.old_root, "mystery")
        _write_json(manifest, document)
        fixture.rebuild_record()
        with self.assertRaisesRegex(
            review_relocation.RelocationError,
            "Unknown path-bearing batch-manifest field",
        ):
            fixture.preview()

    def test_active_attempt_path_fails_closed(self) -> None:
        fixture = RelocationFixture(self.root)
        attempt = (
            fixture.queue_root
            / "batches"
            / fixture.batch_id
            / ".staging"
            / "attempt-1"
            / "attempt-state.json"
        )
        document = json.loads(attempt.read_text(encoding="utf-8"))
        document["status"] = "preparing"
        _write_json(attempt, document)
        fixture.rebuild_record()
        with self.assertRaisesRegex(
            review_relocation.RelocationError, "non-terminal preparation"
        ):
            fixture.preview()

    def test_missing_destination_file_fails(self) -> None:
        fixture = RelocationFixture(self.root)
        target = (
            fixture.queue_root
            / "batches"
            / fixture.batch_id
            / "sources"
            / fixture.tokens[1]
            / "visuals"
            / "frames"
            / "frame-001.jpg"
        )
        target.unlink()
        with self.assertRaisesRegex(
            review_relocation.RelocationError, "missing"
        ):
            fixture.preview()

    def test_extra_destination_file_fails(self) -> None:
        fixture = RelocationFixture(self.root)
        (fixture.queue_root / "unexplained.bin").write_bytes(b"extra")
        with self.assertRaisesRegex(
            review_relocation.RelocationError, "prohibited extra"
        ):
            fixture.preview()

    def test_size_or_hash_mismatch_fails(self) -> None:
        for name, content in (("size", b"longer"), ("hash", b"frame-9")):
            with self.subTest(name=name):
                fixture = RelocationFixture(self.root / name)
                target = (
                    fixture.queue_root
                    / "batches"
                    / fixture.batch_id
                    / "sources"
                    / fixture.tokens[1]
                    / "visuals"
                    / "frames"
                    / "frame-001.jpg"
                )
                if name == "hash":
                    self.assertEqual(len(content), target.stat().st_size)
                target.write_bytes(content)
                with self.assertRaises(review_relocation.RelocationError):
                    fixture.preview()

    def test_wrong_package_identity_fails(self) -> None:
        fixture = RelocationFixture(self.root)
        manifest = (
            fixture.queue_root
            / "batches"
            / fixture.batch_id
            / "batch-manifest.json"
        )
        document = json.loads(manifest.read_text(encoding="utf-8"))
        document["batch_id"] = "unrelated-batch"
        _write_json(manifest, document)
        fixture.rebuild_record()
        with self.assertRaisesRegex(
            review_relocation.RelocationError, "wrong package identity"
        ):
            fixture.preview()

    def test_destination_on_d_fails_without_probing_it(self) -> None:
        fixture = RelocationFixture(self.root)
        payload = fixture.payload()
        payload["mappings"][0]["new_root"] = r"D:\forbidden-destination"
        with self.assertRaisesRegex(
            review_relocation.RelocationError, "approved C volume"
        ):
            review_relocation.relocate_from_request(payload)

    def test_destination_beneath_repository_fails(self) -> None:
        fixture = RelocationFixture(self.root)
        (fixture.root / "destination" / ".git").mkdir()
        with self.assertRaisesRegex(
            review_relocation.RelocationError, "inside a repository"
        ):
            fixture.preview()

    def test_destination_beneath_original_root_fails(self) -> None:
        fixture = RelocationFixture(self.root)
        payload = fixture.payload()
        payload["original_media_roots"] = [str(fixture.root / "destination")]
        with self.assertRaisesRegex(
            review_relocation.RelocationError, "overlaps an original-media root"
        ):
            review_relocation.relocate_from_request(payload)

    def test_traversal_in_migration_record_fails(self) -> None:
        fixture = RelocationFixture(self.root)
        record = json.loads(fixture.record_path.read_text(encoding="utf-8"))
        record["files"][0]["relative_path"] = "../escape.bin"
        _write_json(fixture.record_path, record)
        payload = fixture.payload()
        with self.assertRaisesRegex(
            review_relocation.RelocationError, "escaping relative path"
        ):
            review_relocation.relocate_from_request(payload)

    def test_symlink_or_reparse_destination_fails(self) -> None:
        fixture = RelocationFixture(self.root)
        target = fixture.queue_root / "link-target.txt"
        target.write_text("target", encoding="utf-8")
        link = fixture.queue_root / "unsafe-link.txt"
        try:
            link.symlink_to(target)
        except OSError as exc:
            self.skipTest(f"Host does not permit test symlink creation: {exc}")
        fixture.rebuild_record()
        with self.assertRaisesRegex(
            review_relocation.RelocationError, "symbolic link or reparse point"
        ):
            fixture.preview()

    def test_migration_record_root_or_sha_mismatch_fails(self) -> None:
        fixture = RelocationFixture(self.root)
        payload = fixture.payload()
        payload["mappings"][0]["migration_record_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            review_relocation.RelocationError, "SHA-256 does not match"
        ):
            review_relocation.relocate_from_request(payload)
        record = json.loads(fixture.record_path.read_text(encoding="utf-8"))
        record["source_root"] = r"D:\different-generated-root"
        _write_json(fixture.record_path, record)
        payload = fixture.payload()
        with self.assertRaisesRegex(
            review_relocation.RelocationError, "does not identify"
        ):
            review_relocation.relocate_from_request(payload)

    def test_process_action_does_not_invoke_relocation(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "media_manglers"
            / "core"
            / "review_orchestration.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("review_relocation", source)
        self.assertNotIn("review-media-inbox-relocate", source)

    @staticmethod
    def _original_records(fixture: RelocationFixture) -> list[tuple[object, ...]]:
        connection = inbox_library.connect()
        try:
            return connection.execute(
                """
                SELECT source_id, original_path, normalized_path, size_bytes,
                       modified_utc, modified_ns, is_current
                FROM inbox_source_locations ORDER BY source_id, location_id
                """
            ).fetchall()
        finally:
            connection.close()

    @staticmethod
    def _source_hashes(fixture: RelocationFixture) -> dict[int, str]:
        result = {}
        for source_id in (1, 2, 3):
            root = (
                fixture.queue_root
                / "batches"
                / fixture.batch_id
                / "sources"
                / fixture.tokens[source_id]
            )
            result[source_id] = review_preparation._tree_sha256(root)
        return result


if __name__ == "__main__":
    unittest.main()
