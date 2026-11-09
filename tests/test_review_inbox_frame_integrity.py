from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest import mock

from media_manglers.core import (
    inbox_records,
    review_ledger,
    review_preparation,
    review_queue,
)
from media_manglers_workbench.audio_detection import (
    AUDIBILITY_CONTRACT_VERSION,
    layout_fingerprint,
)
import pytest
from tests import inbox_library  # noqa: E402

# 224 (Wave B2b): the Inbox's records are in this test's library, moved in (nothing to move).
pytestmark = pytest.mark.inbox_moved


class FramePlanTests(unittest.TestCase):
    def test_short_and_subsecond_sources_use_only_decodable_unique_frames(self) -> None:
        self.assertEqual(
            review_preparation.timeline_timestamps(0.09, [0.023, 0.073]),
            [0.023, 0.073],
        )
        self.assertEqual(
            review_preparation.timeline_timestamps(
                0.8,
                [0.0, 0.0, 0.1000001, 0.1000004, 0.4, 0.7],
            ),
            [0.0, 0.1, 0.4, 0.7],
        )

    def test_nominal_end_is_never_requested(self) -> None:
        self.assertEqual(
            review_preparation.timeline_timestamps(1.0, [0.0, 0.5, 1.0]),
            [0.0, 0.5],
        )
        self.assertEqual(
            review_preparation.timeline_timestamps(0.09, [0.023, 0.073, 0.09]),
            [0.023, 0.073],
        )

    def test_zero_duration_and_one_frame_sources_are_truthful(self) -> None:
        self.assertEqual(review_preparation.timeline_timestamps(0.0, []), [])
        self.assertEqual(review_preparation.timeline_timestamps(0.0, [0.0]), [0.0])
        self.assertEqual(review_preparation.timeline_timestamps(3.0, [1.25]), [1.25])

    def test_variable_rate_plan_is_chronological_and_deterministic(self) -> None:
        frames = [2.9, 0.0, 0.04, 0.11, 0.4, 1.7, 2.0, 2.01, 2.5, 2.8]
        first = review_preparation.timeline_timestamps(3.0, frames)
        second = review_preparation.timeline_timestamps(3.0, list(reversed(frames)))
        self.assertEqual(first, second)
        self.assertEqual(first, sorted(set(first)))
        self.assertEqual(len(first), 6)

    def test_provisional_rounding_deduplicates_without_reaching_duration(self) -> None:
        plan = review_preparation.timeline_timestamps(0.000002)
        self.assertEqual(plan, sorted(set(plan)))
        self.assertTrue(all(0 <= value < 0.000002 for value in plan))


class RenderValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.mkv"
        self.source.write_bytes(b"synthetic")
        self.media = {
            "duration_seconds": 1.0,
            "video_frame_timestamps": [0.1, 0.5],
            "video_streams": [
                {"stream_index": 0, "codec": "h264", "width": 160, "height": 90}
            ],
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_nonzero_ffmpeg_exit_fails(self) -> None:
        completed = subprocess.CompletedProcess(
            ["ffmpeg"],
            1,
            stdout="",
            stderr="forced failure",
        )
        with (
            mock.patch.object(
                review_preparation.subprocess,
                "run",
                return_value=completed,
            ),
            self.assertRaisesRegex(RuntimeError, "forced failure"),
        ):
            review_preparation._run(["ffmpeg"])

    def test_zero_exit_without_output_fails(self) -> None:
        completed = mock.Mock(returncode=0, stdout="", stderr="showinfo pts_time:0.1")
        with (
            mock.patch.object(review_preparation, "_run", return_value=completed),
            self.assertRaisesRegex(RuntimeError, "did not create a regular image"),
        ):
            review_preparation._render_visuals(
                "ffmpeg",
                self.source,
                {**self.media, "video_frame_timestamps": [0.1]},
                self.root / "visuals",
            )

    def test_zero_byte_and_corrupt_images_fail(self) -> None:
        zero = self.root / "zero.jpg"
        zero.write_bytes(b"")
        with self.assertRaisesRegex(RuntimeError, "empty"):
            review_preparation._validate_rendered_image(
                "ffprobe",
                self.root,
                zero,
            )

        corrupt = self.root / "corrupt.jpg"
        corrupt.write_bytes(b"not-an-image")
        probe = mock.Mock(returncode=0, stdout='{"streams":[]}', stderr="")
        with (
            mock.patch.object(review_preparation, "_run", return_value=probe),
            self.assertRaisesRegex(RuntimeError, "not a readable single image"),
        ):
            review_preparation._validate_rendered_image(
                "ffprobe",
                self.root,
                corrupt,
            )

    def test_wrong_dimensions_fail(self) -> None:
        target = self.root / "wrong.jpg"
        target.write_bytes(b"image")
        probe = mock.Mock(
            returncode=0,
            stdout='{"streams":[{"codec_type":"video","width":159,"height":90}]}',
            stderr="",
        )
        with (
            mock.patch.object(review_preparation, "_run", return_value=probe),
            self.assertRaisesRegex(RuntimeError, "expected 160"),
        ):
            review_preparation._validate_rendered_image(
                "ffprobe",
                self.root,
                target,
                expected_width=160,
                expected_height=90,
            )

    def test_partial_render_never_writes_a_complete_timeline(self) -> None:
        calls = 0

        def run(command: list[str], **_kwargs: object) -> object:
            nonlocal calls
            if "showinfo" in command:
                calls += 1
                if calls == 1:
                    Path(command[-1]).write_bytes(b"first-frame")
                requested = command[command.index("-ss") + 1]
                return mock.Mock(
                    returncode=0,
                    stdout="",
                    stderr=f"showinfo pts_time:{requested}",
                )
            raise AssertionError("contact sheet must not start after a frame failure")

        def validate(
            _ffprobe: str,
            _root: Path,
            target: Path,
            **_kwargs: object,
        ) -> dict[str, object]:
            if not target.is_file():
                raise RuntimeError("synthetic missing frame")
            return {
                "size_bytes": target.stat().st_size,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "width": 160,
                "height": 90,
            }

        output = self.root / "partial"
        with (
            mock.patch.object(review_preparation, "_run", side_effect=run),
            mock.patch.object(
                review_preparation,
                "_validate_rendered_image",
                side_effect=validate,
            ),
            self.assertRaisesRegex(RuntimeError, "synthetic missing frame"),
        ):
            review_preparation._render_visuals(
                "ffmpeg",
                self.source,
                self.media,
                output,
                include_panel_crops=False,
            )
        self.assertFalse((output / "timeline-index.json").exists())

    def test_achieved_timestamp_and_frame_metadata_are_recorded(self) -> None:
        def run(command: list[str], **_kwargs: object) -> object:
            target = Path(command[-1])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"image")
            if "showinfo" in command:
                return mock.Mock(
                    returncode=0,
                    stdout="",
                    stderr="showinfo pts_time:0.125",
                )
            return mock.Mock(returncode=0, stdout="", stderr="")

        def validate(
            _ffprobe: str,
            _root: Path,
            target: Path,
            **kwargs: object,
        ) -> dict[str, object]:
            return {
                "size_bytes": target.stat().st_size,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "width": int(kwargs.get("expected_width") or 1),
                "height": int(kwargs.get("expected_height") or 1),
            }

        with (
            mock.patch.object(review_preparation, "_run", side_effect=run),
            mock.patch.object(
                review_preparation,
                "_validate_rendered_image",
                side_effect=validate,
            ),
        ):
            result = review_preparation._render_visuals(
                "ffmpeg",
                self.source,
                {**self.media, "video_frame_timestamps": [0.1]},
                self.root / "achieved",
                include_panel_crops=False,
            )
        frame = result["frames"][0]
        self.assertEqual(frame["requested_timestamp_seconds"], 0.1)
        self.assertEqual(frame["actual_timestamp_seconds"], 0.125)
        self.assertEqual(frame["timestamp_seconds"], 0.125)
        self.assertEqual(frame["width"], 160)
        self.assertEqual(frame["height"], 90)
        self.assertEqual(len(frame["sha256"]), 64)


class PackageReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def package(self, name: str = "source", *, frames: int = 2) -> Path:
        root = self.root / name
        frame_root = root / "visuals" / "frames"
        frame_root.mkdir(parents=True)
        frame_records = []
        for ordinal in range(1, frames + 1):
            target = frame_root / f"frame-{ordinal:03d}.jpg"
            target.write_bytes(f"frame-{ordinal}".encode("ascii"))
            frame_records.append(
                {
                    "ordinal": ordinal,
                    "requested_timestamp_seconds": ordinal / 10,
                    "actual_timestamp_seconds": ordinal / 10,
                    "timestamp_seconds": ordinal / 10,
                    "path": f"frames/{target.name}",
                    "size_bytes": target.stat().st_size,
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    "width": 160,
                    "height": 90,
                }
            )
        (root / "visuals" / "contact-sheet.jpg").write_bytes(b"sheet")
        review_preparation._atomic_json(
            root / "visuals" / "timeline-index.json",
            {"schema_version": 1, "frame_count": frames, "frames": frame_records},
        )
        (root / "hints").mkdir()
        (root / "hints" / "README.txt").write_text("hint\n", encoding="utf-8")
        manifest = {
            "schema_version": 1,
            "source_id": 1,
            "visuals": {
                "frame_count": frames,
                "frames": frame_records,
                "contact_sheet": "contact-sheet.jpg",
                "panels": [],
            },
        }
        review_preparation._complete_source_package(root, manifest)
        return root

    @staticmethod
    def rewrite_manifest_record(root: Path) -> None:
        integrity_path = root / "integrity.json"
        payload = json.loads(integrity_path.read_text(encoding="utf-8"))
        manifest_path = root / "source-manifest.json"
        for record in payload["files"]:
            if record["path"] == "source-manifest.json":
                record["size_bytes"] = manifest_path.stat().st_size
                record["sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        review_preparation._atomic_json(integrity_path, payload)

    def test_valid_short_package_with_fewer_than_six_frames_passes(self) -> None:
        root = self.package(frames=2)
        self.assertGreater(review_preparation._validate_source_package(root), 0)

    def test_declared_frame_missing_and_omitted_from_integrity_fails(self) -> None:
        root = self.package("missing")
        target = root / "visuals" / "frames" / "frame-002.jpg"
        target.unlink()
        integrity_path = root / "integrity.json"
        integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
        integrity["files"] = [
            item for item in integrity["files"] if item["path"] != "visuals/frames/frame-002.jpg"
        ]
        review_preparation._atomic_json(integrity_path, integrity)
        with self.assertRaisesRegex(
            RuntimeError,
            "omitted from integrity|missing or unsafe",
        ):
            review_preparation._validate_source_package(root)

    def test_integrity_entry_missing_from_manifest_fails(self) -> None:
        root = self.package("integrity-extra")
        extra = root / "hints" / "extra.txt"
        extra.write_text("extra\n", encoding="utf-8")
        integrity_path = root / "integrity.json"
        integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
        integrity["files"].append(
            {
                "path": "hints/extra.txt",
                "size_bytes": extra.stat().st_size,
                "sha256": hashlib.sha256(extra.read_bytes()).hexdigest(),
            }
        )
        review_preparation._atomic_json(integrity_path, integrity)
        with self.assertRaisesRegex(RuntimeError, "manifest artifact inventory disagrees"):
            review_preparation._validate_source_package(root)

    def test_extra_unexplained_actual_file_fails(self) -> None:
        root = self.package("actual-extra")
        (root / "unexplained.bin").write_bytes(b"extra")
        with self.assertRaisesRegex(RuntimeError, "actual-file set disagrees"):
            review_preparation._validate_source_package(root)

    def test_duplicate_manifest_and_integrity_paths_fail(self) -> None:
        manifest_root = self.package("duplicate-manifest")
        manifest_path = manifest_root / "source-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["artifact_inventory"].append(dict(manifest["artifact_inventory"][0]))
        review_preparation._atomic_json(manifest_path, manifest)
        self.rewrite_manifest_record(manifest_root)
        with self.assertRaisesRegex(RuntimeError, "duplicate path"):
            review_preparation._validate_source_package(manifest_root)

        integrity_root = self.package("duplicate-integrity")
        integrity_path = integrity_root / "integrity.json"
        integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
        integrity["files"].append(dict(integrity["files"][0]))
        review_preparation._atomic_json(integrity_path, integrity)
        with self.assertRaisesRegex(RuntimeError, "duplicate path"):
            review_preparation._validate_source_package(integrity_root)

    def test_hash_size_traversal_and_complete_flag_fail_closed(self) -> None:
        cases = ("hash", "size", "traversal", "complete")
        for case in cases:
            with self.subTest(case=case):
                root = self.package(case)
                integrity_path = root / "integrity.json"
                integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
                record = next(
                    item
                    for item in integrity["files"]
                    if item["path"].endswith("frame-001.jpg")
                )
                if case == "hash":
                    record["sha256"] = "0" * 64
                    expected = "hash changed"
                elif case == "size":
                    record["size_bytes"] += 1
                    expected = "size changed"
                elif case == "traversal":
                    record["path"] = "../frame-001.jpg"
                    expected = "path is malformed"
                else:
                    integrity["complete"] = False
                    expected = "incomplete"
                review_preparation._atomic_json(integrity_path, integrity)
                with self.assertRaisesRegex(RuntimeError, expected):
                    review_preparation._validate_source_package(root)

    def test_zero_byte_declared_visual_fails_but_zero_byte_nonvisual_is_allowed(self) -> None:
        visual = self.package("zero-visual", frames=1)
        frame = visual / "visuals" / "frames" / "frame-001.jpg"
        frame.write_bytes(b"")
        manifest_path = visual / "source-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        record = next(
            item
            for item in manifest["artifact_inventory"]
            if item["path"].endswith("frame-001.jpg")
        )
        record["size_bytes"] = 0
        record["sha256"] = hashlib.sha256(b"").hexdigest()
        review_preparation._atomic_json(manifest_path, manifest)
        (visual / "integrity.json").unlink()
        integrity = review_preparation._hash_files(visual)
        review_preparation._atomic_json(
            visual / "integrity.json",
            {"schema_version": 1, "complete": True, "files": integrity},
        )
        with self.assertRaisesRegex(RuntimeError, "visual artifact is empty"):
            review_preparation._validate_source_package(visual)

        nonvisual = self.root / "zero-nonvisual"
        nonvisual.mkdir()
        (nonvisual / "transcript.srt").write_bytes(b"")
        review_preparation._complete_source_package(
            nonvisual,
            {"schema_version": 1, "source_id": 1, "visuals": {"frames": [], "panels": []}},
        )
        self.assertGreater(review_preparation._validate_source_package(nonvisual), 0)

    def test_queue_hides_an_invalid_batch(self) -> None:
        batch = self.root / "queue" / "batches" / "batch-test"
        source = self.package("queue/batches/batch-test/sources/token", frames=2)
        review_preparation._atomic_json(
            batch / "batch-manifest.json",
            {
                "schema_version": 1,
                "batch_id": "batch-test",
                "status": "awaiting_external_review",
                "prepared_sources": [
                    {"source_id": 1, "package_path": str(source)}
                ],
            },
        )
        (source / "visuals" / "frames" / "frame-002.jpg").unlink()
        row = {
            "batch_id": "batch-test",
            "status": "awaiting_external_review",
            "batch_path": str(batch),
            "source_count": 1,
            "source_states": ["awaiting_external_review"],
        }
        entry = review_queue._batch_entry(self.root / "queue", row)
        self.assertFalse(entry["package_integrity_valid"])
        self.assertEqual(entry["operator_state"], "needs_attention")
        self.assertEqual(review_queue._externally_reviewable_entries([entry]), [])
        self.assertEqual(
            review_queue._counts([entry], 0)["ready_for_codex_review"],
            0,
        )

    def test_existing_valid_legacy_manifest_remains_readable(self) -> None:
        root = self.package("legacy")
        manifest_path = root / "source-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.pop("artifact_inventory")
        review_preparation._atomic_json(manifest_path, manifest)
        self.rewrite_manifest_record(root)
        self.assertGreater(review_preparation._validate_source_package(root), 0)


class ExistingBatchRepairTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sources = self.root / "sources"
        self.evidence = self.root / "evidence"
        self.scratch = self.root / "scratch"
        self.ledger = self.root / "ledger.sqlite"
        self.sources.mkdir()
        inbox_library.ready(self.ledger)
        for index in range(3):
            source = self.sources / f"source-{index + 1}.mkv"
            source.write_bytes((f"source-{index + 1}-" * 100).encode("ascii"))
            timestamp = 1_700_000_000 + index
            os.utime(source, (timestamp, timestamp))
        self.prepared = review_preparation.prepare_from_request(self.payload())
        self.batch_root = Path(self.prepared["batch_path"])
        self.source_packages = {
            int(item["source_id"]): Path(item["package_path"])
            for item in self.prepared["prepared_sources"]
        }
        self.before_trees = {
            source_id: review_preparation._tree_sha256(path)
            for source_id, path in self.source_packages.items()
        }
        self.make_false_complete(self.source_packages[3])

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def media(_path: Path | None = None) -> dict[str, object]:
        return {
            "duration_seconds": 0.09,
            "container": "synthetic",
            "bit_rate": 1,
            "recorder_profile": "synthetic",
            "video_streams": [
                {"stream_index": 0, "codec": "h264", "width": 160, "height": 90}
            ],
            "video_frame_timestamps": [0.023, 0.073],
            "audio_streams": [],
            "audio_layout_fingerprint": layout_fingerprint([], "synthetic"),
        }

    @staticmethod
    def audibility(
        _source: Path,
        _media: dict[str, object],
        _temp: Path,
    ) -> dict[str, object]:
        return {
            "contract_version": AUDIBILITY_CONTRACT_VERSION,
            "source_state": "no_audio_streams",
            "streams": [],
        }

    @staticmethod
    def render(
        _source: Path,
        _media: dict[str, object],
        output: Path,
    ) -> dict[str, object]:
        frames = output / "frames"
        frames.mkdir(parents=True, exist_ok=True)
        items = []
        for ordinal, timestamp in enumerate((0.023, 0.073), 1):
            target = frames / f"frame-{ordinal:03d}.jpg"
            target.write_bytes(f"frame-{ordinal}".encode("ascii"))
            items.append(
                {
                    "ordinal": ordinal,
                    "requested_timestamp_seconds": timestamp,
                    "actual_timestamp_seconds": timestamp,
                    "timestamp_seconds": timestamp,
                    "path": f"frames/{target.name}",
                    "size_bytes": target.stat().st_size,
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    "width": 160,
                    "height": 90,
                }
            )
        (output / "contact-sheet.jpg").write_bytes(b"sheet")
        review_preparation._atomic_json(
            output / "timeline-index.json",
            {"schema_version": 1, "frame_count": 2, "frames": items},
        )
        return {
            "frame_count": 2,
            "frames": items,
            "contact_sheet": "contact-sheet.jpg",
            "panels": [],
            "supported_panel_ids": [],
        }

    def payload(self, **overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "source_folders": [str(self.sources)],
            "ledger_path": str(self.ledger),
            "evidence_root": str(self.evidence),
            "scratch_root": str(self.scratch),
            "max_files": 3,
            "max_duration_minutes": 240,
            "concurrency": 1,
            "pending_batch_limit": 1,
            "dedupe_mode": "Fast",
            "order": "oldest",
            "space_probe": lambda _path: 100 * 1024**3,
            "media_probe": self.media,
            "audibility_inspector": self.audibility,
            "visual_renderer": self.render,
        }
        payload.update(overrides)
        return payload

    @staticmethod
    def make_false_complete(root: Path) -> None:
        manifest_path = root / "source-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.pop("artifact_inventory", None)
        last = dict(manifest["visuals"]["frames"][-1])
        last["ordinal"] = 3
        last["requested_timestamp_seconds"] = 0.083
        last["actual_timestamp_seconds"] = 0.083
        last["timestamp_seconds"] = 0.083
        last["path"] = "frames/frame-003.jpg"
        manifest["visuals"]["frames"].append(last)
        manifest["visuals"]["frame_count"] = 3
        review_preparation._atomic_json(manifest_path, manifest)
        (root / "integrity.json").unlink()
        integrity = review_preparation._hash_files(root)
        review_preparation._atomic_json(
            root / "integrity.json",
            {"schema_version": 1, "complete": True, "files": integrity},
        )

    def counts(self) -> tuple[int, int, int]:
        connection = inbox_library.connect()
        try:
            attempts = int(
                connection.execute(
                    "SELECT COUNT(*) FROM inbox_attempts WHERE batch_id=? AND attempt_type='repair'",
                    (self.prepared["batch_id"],),
                ).fetchone()[0]
            )
            started = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM inbox_lifecycle_events
                    WHERE batch_id=? AND event_type='prepared_package_repair_started'
                    """,
                    (self.prepared["batch_id"],),
                ).fetchone()[0]
            )
            completed = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM inbox_lifecycle_events
                    WHERE batch_id=? AND event_type='prepared_package_repaired'
                    """,
                    (self.prepared["batch_id"],),
                ).fetchone()[0]
            )
            return attempts, started, completed
        finally:
            connection.close()

    def repair(self, **overrides: object) -> dict[str, object]:
        return review_preparation.repair_from_request(
            self.payload(
                batch_id=self.prepared["batch_id"],
                **overrides,
            )
        )

    def test_repair_detects_only_invalid_source_and_preserves_batch_and_peers(self) -> None:
        result = self.repair()
        self.assertEqual(result["status"], "awaiting_external_review")
        self.assertEqual(
            [item["source_id"] for item in result["repaired_sources"]],
            [3],
        )
        self.assertEqual(
            review_preparation._tree_sha256(self.source_packages[1]),
            self.before_trees[1],
        )
        self.assertEqual(
            review_preparation._tree_sha256(self.source_packages[2]),
            self.before_trees[2],
        )
        self.assertGreater(
            review_preparation._validate_source_package(self.source_packages[3]),
            0,
        )
        manifest = json.loads(
            (self.source_packages[3] / "source-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["visuals"]["frame_count"], 2)
        self.assertEqual(len(manifest["visuals"]["frames"]), 2)
        self.assertTrue(Path(result["repaired_sources"][0]["history_path"]).is_dir())
        connection = inbox_library.connect()
        try:
            self.assertEqual(
                connection.execute(
                    "SELECT status FROM inbox_batches WHERE batch_id=?",
                    (self.prepared["batch_id"],),
                ).fetchone()[0],
                "awaiting_external_review",
            )
            self.assertEqual(
                connection.execute(
                    "SELECT source_id,state FROM inbox_batch_sources WHERE batch_id=? ORDER BY ordinal",
                    (self.prepared["batch_id"],),
                ).fetchall(),
                [
                    (1, "awaiting_external_review"),
                    (2, "awaiting_external_review"),
                    (3, "awaiting_external_review"),
                ],
            )
        finally:
            connection.close()

    def test_repeated_repair_is_idempotent(self) -> None:
        first = self.repair()
        before = self.counts()
        history = list((self.batch_root / "repair-history").rglob("package"))
        second = self.repair()
        self.assertEqual(first["status"], "awaiting_external_review")
        self.assertEqual(second["status"], "already_valid")
        self.assertEqual(self.counts(), before)
        self.assertEqual(list((self.batch_root / "repair-history").rglob("package")), history)

    def test_crash_boundaries_resume_without_duplicate_attempts_or_events(self) -> None:
        for phase in (
            "after_repair_scheduled",
            "during_rerender",
            "after_staging_verified",
            "after_prior_package_retained",
            "after_promotion",
            "after_ledger_commit",
        ):
            with self.subTest(phase=phase):
                # Recreate a distinct corrupt package identity for each phase
                # without allocating a new source or batch.
                if phase != "after_repair_scheduled":
                    # The preceding subtest may have completed its retry.
                    current = self.source_packages[3]
                    if review_preparation._validate_source_package(current):
                        self.make_false_complete(current)
                        connection = inbox_library.connect()
                        try:
                            connection.execute(
                                "UPDATE inbox_batch_sources SET state='awaiting_external_review' "
                                "WHERE batch_id=? AND source_id=3",
                                (self.prepared["batch_id"],),
                            )
                            connection.execute(
                                "UPDATE inbox_sources SET lifecycle_state='awaiting_external_review' "
                                "WHERE source_id=3"
                            )
                            connection.execute(
                                "UPDATE inbox_batches SET status='awaiting_external_review' "
                                "WHERE batch_id=?",
                                (self.prepared["batch_id"],),
                            )
                            connection.commit()
                        finally:
                            connection.close()
                fired = False

                def crash(current: str) -> None:
                    nonlocal fired
                    if current == phase and not fired:
                        fired = True
                        raise RuntimeError(f"synthetic crash at {phase}")

                with self.assertRaisesRegex(RuntimeError, "synthetic crash"):
                    self.repair(repair_fault_injector=crash)
                recovered = self.repair()
                self.assertIn(
                    recovered["status"],
                    {"awaiting_external_review", "already_valid"},
                )
                self.assertGreater(
                    review_preparation._validate_source_package(
                        self.source_packages[3]
                    ),
                    0,
                )
                attempts, started, completed = self.counts()
                self.assertEqual(attempts, started)
                self.assertEqual(completed, started)


if __name__ == "__main__":
    unittest.main()
