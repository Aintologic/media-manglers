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
import time
import unittest
from unittest import mock

from media_manglers.core import inbox_records, review_inbox, review_ledger, review_preparation
from media_manglers.core.transcripts import write_transcript_files
from media_manglers_workbench.audio_detection import AudioStreamInfo, layout_fingerprint
import pytest
from tests import inbox_library  # noqa: E402

# 224 (Wave B2b): the Inbox's records are in this test's library, moved in (nothing to move).
pytestmark = pytest.mark.inbox_moved


def _stream(ordinal: int) -> AudioStreamInfo:
    return AudioStreamInfo(
        ordinal=ordinal,
        stream_index=ordinal + 1,
        title=f"Audio {ordinal + 1}",
        language="eng",
        codec="aac",
        channels=2,
        channel_layout="stereo",
        sample_rate=48000,
        bit_rate=128000,
    )


class ReviewInboxPreparationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sources = self.root / "sources"
        self.evidence = self.root / "evidence"
        self.scratch = self.root / "scratch"
        self.ledger = self.root / "ledger.sqlite"
        self.sources.mkdir()
        # Each Inbox a test makes has its own library, as each had its own ledger (224, Wave B2b).
        inbox_library.use_own_library(self, self.root)
        inbox_library.ready(self.ledger)
        self.events: list[tuple[str, object]] = []

    def tearDown(self) -> None:
        inbox_records.release_all()
        self.temporary.cleanup()

    def test_atomic_json_uses_a_short_sibling_name_on_windows(self) -> None:
        target = self.root / "deep" / "transcript-status.json"
        fake_uuid = mock.Mock()
        fake_uuid.hex = "a" * 32
        with (
            mock.patch.object(review_preparation.uuid, "uuid4", return_value=fake_uuid),
            mock.patch.object(review_preparation.os, "replace") as replace,
        ):
            review_preparation._atomic_json(target, {"status": "complete"})
        temporary, destination = map(Path, replace.call_args.args)
        self.assertEqual(temporary.parent, target.parent)
        self.assertEqual(temporary.name, f".mm-{'a' * 16}.tmp")
        self.assertEqual(destination, target)
        self.assertFalse(temporary.exists())

    def test_atomic_json_retries_transient_windows_replace_denial(self) -> None:
        target = self.root / "progress.json"
        real_replace = os.replace
        attempts = 0

        def transient_replace(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                # 224 (Wave B2a): a real sharing violation (Windows error 32), the one refusal waited for.
                raise PermissionError(13, "synthetic sharing violation", None, 32)
            real_replace(source, destination)

        with (
            mock.patch.object(review_preparation.os, "replace", side_effect=transient_replace),
            mock.patch.object(review_preparation.time, "sleep") as sleep,
        ):
            review_preparation._atomic_json(target, {"status": "complete"})

        self.assertEqual(attempts, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"status": "complete"})

    def test_atomic_json_persistent_replace_denial_fails_closed(self) -> None:
        target = self.root / "progress.json"
        target.write_text('{"status":"prior"}\n', encoding="utf-8")
        with (
            mock.patch.object(
                review_preparation.os,
                "replace",
                side_effect=PermissionError(13, "synthetic persistent sharing violation", None, 32),
            ) as replace,
            mock.patch.object(review_preparation.time, "sleep") as sleep,
            self.assertRaises(PermissionError),
        ):
            review_preparation._atomic_json(target, {"status": "replacement"})

        # 224 (Wave B2a): an Inbox step waits up to ten seconds in all, then stops (Decision 2).
        self.assertEqual(replace.call_count, sleep.call_count + 1)
        self.assertAlmostEqual(sum(call.args[0] for call in sleep.call_args_list), 10.0)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"status": "prior"})
        self.assertEqual(list(target.parent.glob(".mm-*.tmp")), [])

    def test_atomic_json_does_not_retry_non_permission_error(self) -> None:
        target = self.root / "progress.json"
        target.write_text('{"status":"prior"}\n', encoding="utf-8")
        with (
            mock.patch.object(
                review_preparation.os,
                "replace",
                side_effect=OSError(28, "synthetic disk error"),
            ) as replace,
            mock.patch.object(review_preparation.time, "sleep") as sleep,
            self.assertRaises(OSError),
        ):
            review_preparation._atomic_json(target, {"status": "replacement"})

        replace.assert_called_once()
        sleep.assert_not_called()
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"status": "prior"})
        self.assertEqual(list(target.parent.glob(".mm-*.tmp")), [])

    def make_sources(self, count: int, *, suffix: str = ".mp4") -> list[Path]:
        paths = []
        for index in range(count):
            path = self.sources / f"source-{index:03d}{suffix}"
            path.write_bytes((f"synthetic-{index}-" * 100).encode("ascii"))
            timestamp = 1_700_000_000 + index
            os.utime(path, (timestamp, timestamp))
            paths.append(path)
        return paths

    def media(self, audio_count: int = 1, *, width: int = 1280, height: int = 720, duration: float = 900.0) -> dict:
        streams = [_stream(index) for index in range(audio_count)]
        recorder = "synthetic-recorder"
        return {
            "duration_seconds": duration,
            "container": "synthetic",
            "bit_rate": 1_000_000,
            "recorder_profile": recorder,
            "video_streams": [{"stream_index": 0, "codec": "h264", "width": width, "height": height}],
            "audio_streams": [
                {
                    "ordinal": item.ordinal,
                    "stream_index": item.stream_index,
                    "title": item.title,
                    "language": item.language,
                    "codec": item.codec,
                    "channels": item.channels,
                    "channel_layout": item.channel_layout,
                    "sample_rate": item.sample_rate,
                    "bit_rate": item.bit_rate,
                    "ffmpeg_map": item.ffmpeg_map,
                }
                for item in streams
            ],
            "audio_layout_fingerprint": layout_fingerprint(streams, recorder),
        }

    def transcribe(self, audio_path: Path, output: Path, _settings: dict) -> dict:
        self.events.append(("transcribe", audio_path.read_text(encoding="utf-8")))
        result = {
            "language": "en",
            "segments": [{"start": 0.0, "end": 1.25, "text": "ordinary narration without deterministic markers"}],
        }
        json_path, srt_path, text_path = write_transcript_files(output, "transcript.json", "transcript.srt", "transcript.txt", result)
        quality = output / "transcript.quality.json"
        quality.write_text('{"quality_blocking": false}\n', encoding="utf-8")
        return {
            "json_path": str(json_path),
            "srt_path": str(srt_path),
            "text_path": str(text_path),
            "quality_json_path": str(quality),
            "segments_count": 1,
            "quality_blocking": False,
        }

    def extract(self, _source: Path, ordinal: int, output: Path) -> None:
        self.events.append(("extract", ordinal))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(f"ordinal={ordinal}", encoding="utf-8")

    def write_test_integrity(
        self,
        package: Path,
        artifact: Path,
        integrity_record: dict[str, object],
    ) -> None:
        artifact_record = {
            "path": artifact.name,
            "size_bytes": artifact.stat().st_size,
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        }
        review_preparation._atomic_json(
            package / "source-manifest.json",
            {"schema_version": 1, "artifact_inventory": [artifact_record]},
        )
        manifest = package / "source-manifest.json"
        manifest_record = {
            "path": manifest.name,
            "size_bytes": manifest.stat().st_size,
            "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        }
        review_preparation._atomic_json(
            package / "integrity.json",
            {
                "complete": True,
                "files": [integrity_record, manifest_record],
            },
        )

    def render(self, _source: Path, media: dict, output: Path) -> dict:
        self.events.append(("render", len(self.events)))
        frames = output / "frames"
        frames.mkdir(parents=True, exist_ok=True)
        count = review_preparation.timeline_frame_count(media["duration_seconds"])
        index = []
        for ordinal in range(1, count + 1):
            path = frames / f"frame-{ordinal:03d}.jpg"
            path.write_bytes(b"synthetic-frame")
            index.append({"ordinal": ordinal, "timestamp_seconds": float(ordinal), "path": f"frames/{path.name}"})
        (output / "contact-sheet.jpg").write_bytes(b"synthetic-sheet")
        review_preparation._atomic_json(output / "timeline-index.json", {"frames": index, "panels": []})
        return {"frame_count": count, "frames": index, "contact_sheet": "contact-sheet.jpg", "panels": []}

    def payload(self, **overrides: object) -> dict:
        payload = {
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
            "media_probe": lambda _path: self.media(),
            "audio_extractor": self.extract,
            "transcriber": self.transcribe,
            "visual_renderer": self.render,
        }
        payload.update(overrides)
        return payload

    def query(self, sql: str, parameters: tuple = ()) -> list[tuple]:
        connection = inbox_library.connect()
        try:
            return connection.execute(sql, parameters).fetchall()
        finally:
            connection.close()

    def test_bounded_selection_is_sequential_and_oldest_first(self) -> None:
        paths = self.make_sources(5)
        result = review_preparation.prepare_from_request(self.payload())
        self.assertEqual(result["status"], "awaiting_external_review")
        self.assertEqual(len(result["prepared_sources"]), 3)
        locations = self.query(
            "SELECT l.original_path FROM inbox_batch_sources bs JOIN inbox_source_locations l ON l.source_id=bs.source_id AND l.is_current=1 WHERE bs.batch_id=? ORDER BY bs.ordinal",
            (result["batch_id"],),
        )
        self.assertEqual([Path(row[0]).name for row in locations], [path.name for path in paths[:3]])
        self.assertEqual([item[0] for item in self.events], ["extract", "transcribe", "render"] * 3)

    def test_executor_rechecks_storage_and_bounds_scratch_for_each_of_ten_sources(
        self,
    ) -> None:
        paths = self.make_sources(10)
        scan = review_inbox.scan_from_request(self.payload(max_files=10))
        source_ids = [
            int(item["source_id"]) for item in scan["selected_sources"]
        ]
        chunks = [
            source_ids[index : index + 3]
            for index in range(0, len(source_ids), 3)
        ]
        self.assertEqual([len(chunk) for chunk in chunks], [3, 3, 3, 1])

        trace: list[tuple[str, str, str]] = []
        cleanup_events: list[str] = []
        active_executor_callbacks = 0
        max_active_executor_callbacks = 0
        scratch_high_water_sources = 0
        current_source = ""

        def scratch_attempt_count() -> int:
            return len(
                {
                    attempt.parent
                    for attempt in self.scratch.glob(
                        "review-inbox/*/attempt-*/source/source.*"
                    )
                }
            )

        def guarded(
            operation: str,
            source_name: str,
            callback: object,
        ) -> object:
            nonlocal active_executor_callbacks
            nonlocal max_active_executor_callbacks
            nonlocal scratch_high_water_sources
            active_executor_callbacks += 1
            max_active_executor_callbacks = max(
                max_active_executor_callbacks, active_executor_callbacks
            )
            try:
                trace.append(("operation", source_name, operation))
                return callback()
            finally:
                scratch_high_water_sources = max(
                    scratch_high_water_sources, scratch_attempt_count()
                )
                active_executor_callbacks -= 1

        def media_probe(source: Path) -> dict:
            nonlocal current_source
            current_source = source.name
            return guarded(
                "media_probe",
                current_source,
                lambda: self.media(duration=0.1),
            )

        def space_probe(path: Path) -> int:
            kind = "scratch" if path == self.scratch else "retained"
            trace.append(("storage", current_source, kind))
            return 100 * 1024**3

        def copy_file(source: Path, destination: Path) -> dict:
            return guarded(
                "copy",
                source.name,
                lambda: review_preparation.stream_verified_copy(
                    source, destination
                ),
            )

        def extract(source: Path, ordinal: int, output: Path) -> None:
            guarded(
                "audio_extract",
                current_source,
                lambda: self.extract(source, ordinal, output),
            )

        def transcribe(audio: Path, output: Path, settings: dict) -> dict:
            return guarded(
                "transcribe",
                current_source,
                lambda: self.transcribe(audio, output, settings),
            )

        def render(source: Path, media: dict, output: Path) -> dict:
            return guarded(
                "render",
                current_source,
                lambda: self.render(source, media, output),
            )

        def progress(event: dict) -> None:
            if event["phase"] == "Cleaning scratch":
                cleanup_events.append(str(event["source_name"]))

        prepared_sources: list[dict] = []
        prepared_ids: list[int] = []
        prepared_chunk_sizes: list[int] = []
        for chunk_index, chunk in enumerate(chunks, start=1):
            result = review_preparation.prepare_selected_from_request(
                self.payload(
                    scan_result=scan,
                    selected_source_ids=chunk,
                    preallocated_batch_id=f"batch-ten-{chunk_index:02d}",
                    media_probe=media_probe,
                    space_probe=space_probe,
                    copy_file=copy_file,
                    audio_extractor=extract,
                    transcriber=transcribe,
                    visual_renderer=render,
                    progress_callback=progress,
                )
            )
            self.assertEqual(result["status"], "awaiting_external_review")
            chunk_sources = list(result["prepared_sources"])
            prepared_chunk_sizes.append(len(chunk_sources))
            prepared_sources.extend(chunk_sources)
            prepared_ids.extend(
                int(item["source_id"]) for item in chunk_sources
            )

        expected_names = [path.name for path in paths]
        self.assertEqual(prepared_chunk_sizes, [3, 3, 3, 1])
        self.assertEqual(prepared_ids, source_ids)
        self.assertEqual(len(prepared_ids), len(set(prepared_ids)))
        self.assertEqual(len(prepared_sources), 10)
        self.assertEqual(max_active_executor_callbacks, 1)
        self.assertEqual(active_executor_callbacks, 0)
        self.assertEqual(scratch_high_water_sources, 1)
        self.assertEqual(cleanup_events, expected_names)
        storage_events = [item for item in trace if item[0] == "storage"]
        self.assertEqual(len(storage_events), 20)
        copy_positions = [
            index
            for index, item in enumerate(trace)
            if item[0] == "operation" and item[2] == "copy"
        ]
        self.assertEqual(len(copy_positions), 10)
        for index, (source_name, position) in enumerate(
            zip(expected_names, copy_positions, strict=True)
        ):
            self.assertEqual(
                trace[position - 2 : position],
                [
                    ("storage", source_name, "scratch"),
                    ("storage", source_name, "retained"),
                ],
                f"source {index + 1} did not receive its storage gate immediately before copy",
            )
        copy_names = [trace[position][1] for position in copy_positions]
        self.assertEqual(copy_names, expected_names)
        self.assertEqual(len(copy_names), len(set(copy_names)))
        for item in prepared_sources:
            manifest = json.loads(
                (
                    Path(item["package_path"]) / "source-manifest.json"
                ).read_text(encoding="utf-8")
            )
            self.assertIn("scratch_free_bytes", manifest["storage_gate"])
            self.assertIn("retained_free_bytes", manifest["storage_gate"])
        self.assertEqual(list(self.scratch.rglob("attempt-*")), [])
        self.assertEqual(
            [path for path in self.scratch.rglob("*") if path.is_file()],
            [],
        )

    def test_executor_prepares_all_205_snapshot_sources_in_hidden_chunks(
        self,
    ) -> None:
        paths = self.make_sources(205)
        scan = review_inbox.scan_from_request(self.payload(max_files=205))
        source_ids = [
            int(item["source_id"]) for item in scan["selected_sources"]
        ]
        chunks = [
            source_ids[index : index + 3]
            for index in range(0, len(source_ids), 3)
        ]
        self.assertEqual([len(chunk) for chunk in chunks], [3] * 68 + [1])

        current_source = ""
        trace: list[tuple[str, str]] = []
        active_executor_callbacks = 0
        max_active_executor_callbacks = 0
        scratch_high_water_sources = 0

        def scratch_attempt_count() -> int:
            return len(
                {
                    attempt.parent
                    for attempt in self.scratch.glob(
                        "review-inbox/*/attempt-*/source/source.*"
                    )
                }
            )

        def guarded(callback: object) -> object:
            nonlocal active_executor_callbacks
            nonlocal max_active_executor_callbacks
            nonlocal scratch_high_water_sources
            active_executor_callbacks += 1
            max_active_executor_callbacks = max(
                max_active_executor_callbacks, active_executor_callbacks
            )
            try:
                return callback()
            finally:
                scratch_high_water_sources = max(
                    scratch_high_water_sources, scratch_attempt_count()
                )
                active_executor_callbacks -= 1

        def media_probe(source: Path) -> dict:
            nonlocal current_source
            current_source = source.name
            return guarded(lambda: self.media(duration=0.1))

        def space_probe(path: Path) -> int:
            kind = "scratch" if path == self.scratch else "retained"
            trace.append((current_source, kind))
            return 100 * 1024**3

        def copy_file(source: Path, destination: Path) -> dict:
            trace.append((source.name, "copy"))
            return guarded(
                lambda: review_preparation.stream_verified_copy(
                    source, destination
                )
            )

        def extract(source: Path, ordinal: int, output: Path) -> None:
            guarded(lambda: self.extract(source, ordinal, output))

        def transcribe(audio: Path, output: Path, settings: dict) -> dict:
            return guarded(lambda: self.transcribe(audio, output, settings))

        def render(source: Path, media: dict, output: Path) -> dict:
            return guarded(lambda: self.render(source, media, output))

        prepared_ids: list[int] = []
        for chunk_index, chunk in enumerate(chunks, start=1):
            result = review_preparation.prepare_selected_from_request(
                self.payload(
                    scan_result=scan,
                    selected_source_ids=chunk,
                    preallocated_batch_id=f"batch-proof-{chunk_index:03d}",
                    media_probe=media_probe,
                    space_probe=space_probe,
                    copy_file=copy_file,
                    audio_extractor=extract,
                    transcriber=transcribe,
                    visual_renderer=render,
                )
            )
            self.assertEqual(result["status"], "awaiting_external_review")
            prepared_ids.extend(
                int(item["source_id"]) for item in result["prepared_sources"]
            )

        expected_names = [path.name for path in paths]
        self.assertEqual(prepared_ids, source_ids)
        self.assertEqual(len(prepared_ids), len(set(prepared_ids)))
        copy_sources = [
            source_name
            for source_name, event_kind in trace
            if event_kind == "copy"
        ]
        self.assertEqual(copy_sources, expected_names)
        self.assertEqual(len(copy_sources), len(set(copy_sources)))
        self.assertEqual(len(trace), 615)
        for index, source_name in enumerate(expected_names):
            self.assertEqual(
                trace[index * 3 : index * 3 + 3],
                [
                    (source_name, "scratch"),
                    (source_name, "retained"),
                    (source_name, "copy"),
                ],
                f"source {index + 1} did not receive its storage gate immediately before copy",
            )
        self.assertEqual(max_active_executor_callbacks, 1)
        self.assertEqual(active_executor_callbacks, 0)
        self.assertEqual(scratch_high_water_sources, 1)
        self.assertEqual(list(self.scratch.rglob("attempt-*")), [])
        self.assertEqual(
            [path for path in self.scratch.rglob("*") if path.is_file()],
            [],
        )

    def test_newest_order_and_max_file_override(self) -> None:
        paths = self.make_sources(4)
        result = review_preparation.prepare_from_request(self.payload(order="newest", max_files=2))
        locations = self.query(
            "SELECT l.original_path FROM inbox_batch_sources bs JOIN inbox_source_locations l ON l.source_id=bs.source_id AND l.is_current=1 WHERE bs.batch_id=? ORDER BY bs.ordinal",
            (result["batch_id"],),
        )
        self.assertEqual([Path(row[0]).name for row in locations], [paths[3].name, paths[2].name])

    def test_pending_batch_limit_returns_existing_batch_without_copy(self) -> None:
        self.make_sources(2)
        first = review_preparation.prepare_from_request(self.payload())
        self.events.clear()
        second = review_preparation.prepare_from_request(self.payload())
        self.assertEqual(second["status"], "pending_batch_limit_reached")
        self.assertEqual(second["pending_batches"][0]["batch_id"], first["batch_id"])
        self.assertEqual(self.events, [])

    def test_soft_duration_boundary_allows_current_then_stops_before_next(self) -> None:
        self.make_sources(3)
        values = iter([0.0, 14_401.0])
        result = review_preparation.prepare_from_request(self.payload(clock=lambda: next(values)))
        self.assertEqual(len(result["prepared_sources"]), 1)
        self.assertEqual(result["stopped_reason"], "soft_duration_boundary")

    def test_cooperative_stop_is_checked_after_current_source(self) -> None:
        self.make_sources(3)
        result = review_preparation.prepare_from_request(self.payload(stop_requested=lambda: True))
        self.assertEqual(len(result["prepared_sources"]), 1)
        self.assertEqual(result["stopped_reason"], "cooperative_stop_after_current_source")

    def test_storage_gate_blocks_before_copy_and_records_retryable_failure(self) -> None:
        source = self.make_sources(1)[0]
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        result = review_preparation.prepare_from_request(self.payload(space_probe=lambda _path: 1))
        self.assertEqual(result["failed_sources"][0]["state"], "retryable_failure")
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
        self.assertEqual(self.events, [])

    def test_stream_copy_hashes_and_preserves_original_metadata(self) -> None:
        source = self.make_sources(1)[0]
        before = source.stat()
        before_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        result = review_preparation.prepare_from_request(self.payload())
        after = source.stat()
        manifest = json.loads((Path(result["prepared_sources"][0]["package_path"]) / "source-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["copy_validation"]["sha256"], before_hash)
        self.assertEqual((before.st_size, before.st_mtime_ns), (after.st_size, after.st_mtime_ns))
        self.assertFalse(any(self.scratch.rglob(source.name)))

    def test_long_original_name_uses_bounded_scratch_name_and_remains_in_manifest(self) -> None:
        # Long, but short enough to be written wherever the test's temp folder is (196: the suite's
        # scratch folder is inside the checkout, a longer path than the system temp folder).
        repeats = max(4, min(10, (250 - len(str(self.sources)) - 5) // len("long-recording-name-")))
        source = self.sources / ("long-recording-name-" * repeats + ".mp4")
        source.write_bytes(b"synthetic-long-name")
        destinations: list[Path] = []

        def copy_file(original: Path, destination: Path) -> dict:
            destinations.append(destination)
            return review_preparation.stream_verified_copy(original, destination)

        result = review_preparation.prepare_from_request(self.payload(copy_file=copy_file))

        self.assertEqual(result["status"], "awaiting_external_review")
        self.assertEqual([path.name for path in destinations], ["source.mp4"])
        self.assertLess(len(destinations[0].name), len(source.name))
        manifest_path = Path(result["prepared_sources"][0]["package_path"]) / "source-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(Path(manifest["original_location"]).name, source.name)

    def test_copy_hash_mismatch_and_source_change_are_safe(self) -> None:
        source = self.make_sources(1)[0]

        def bad_copy(original: Path, target: Path) -> dict:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(original.read_bytes())
            return {"sha256": "0" * 64, "bytes_copied": target.stat().st_size, "before": {}, "after": {}}

        result = review_preparation.prepare_from_request(self.payload(copy_file=bad_copy))
        self.assertEqual(result["failed_sources"][0]["state"], "source_changed")
        self.assertEqual(self.query("SELECT modified_ns FROM inbox_source_locations WHERE is_current=1"), [(None,)])
        self.assertFalse(any(self.scratch.rglob(source.name)))

    def test_process_resume_refreshes_grown_foundation_source_changed_boundary(
        self,
    ) -> None:
        source = self.make_sources(1)[0]
        original_size = source.stat().st_size
        scan = review_inbox.scan_from_request(self.payload())

        def bad_copy(original: Path, target: Path) -> dict:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(original.read_bytes())
            return {
                "sha256": "0" * 64,
                "bytes_copied": target.stat().st_size,
                "before": {},
                "after": {},
            }

        first = review_preparation.prepare_from_request(
            self.payload(
                scan_result=scan,
                copy_file=bad_copy,
            )
        )
        source_id = int(first["failed_sources"][0]["source_id"])
        self.assertEqual(first["failed_sources"][0]["state"], "source_changed")
        self.assertEqual(
            self.query(
                "SELECT modified_ns FROM inbox_source_locations "
                "WHERE source_id = ? AND is_current = 1",
                (source_id,),
            ),
            [(None,)],
        )
        source.write_bytes(source.read_bytes() + b"now-stable-after-growth")
        expected_stat = source.stat()
        expected_sample = review_inbox.sampled_sha256_file(source)
        self.assertGreater(expected_stat.st_size, original_size)
        for state_path in Path(first["batch_path"]).glob(
            ".staging/*/attempt-state.json"
        ):
            prior_state = json.loads(state_path.read_text(encoding="utf-8"))
            prior_state["process_id"] = 0
            review_preparation._atomic_json(state_path, prior_state)
        resume_scan = {
            **scan,
            "sources": [],
            "selected_sources": [],
            "pending_batches": [
                {
                    "batch_id": first["batch_id"],
                    "status": "preparing",
                    "package_path": first["batch_path"],
                }
            ],
        }

        with mock.patch.object(
            review_inbox,
            "scan_from_request",
            side_effect=AssertionError(
                "Foundation recovery must not scan or allocate new media."
            ),
        ):
            recovered = review_preparation.prepare_selected_from_request(
                self.payload(
                    scan_result=resume_scan,
                    selected_source_ids=[],
                    resume_batch_id=first["batch_id"],
                )
            )

        self.assertEqual(recovered["status"], "awaiting_external_review")
        self.assertEqual(recovered["batch_id"], first["batch_id"])
        self.assertEqual(
            [int(item["source_id"]) for item in recovered["prepared_sources"]],
            [source_id],
        )
        self.assertEqual(self.query("SELECT COUNT(*) FROM inbox_batches"), [(1,)])
        self.assertEqual(self.query("SELECT COUNT(*) FROM inbox_batch_sources"), [(1,)])
        self.assertEqual(
            self.query(
                "SELECT size_bytes, modified_ns FROM inbox_source_locations "
                "WHERE source_id = ? AND is_current = 1",
                (source_id,),
            ),
            [(expected_stat.st_size, expected_stat.st_mtime_ns)],
        )
        self.assertEqual(
            self.query(
                "SELECT size_bytes, sampled_sha256 FROM inbox_sources "
                "WHERE source_id = ?",
                (source_id,),
            ),
            [(expected_stat.st_size, expected_sample)],
        )

    def test_process_resume_rejects_changed_foundation_stable_identity(
        self,
    ) -> None:
        source = self.make_sources(1)[0]
        scan = review_inbox.scan_from_request(self.payload())
        selected = dict(scan["selected_sources"][0])
        source_id = int(selected["source_id"])
        original_sha256 = review_ledger.sha256_file(source)
        batch_id = "batch-foundation-stable"
        batch_root = self.ledger.parent / "batches" / batch_id
        connection = inbox_records.connect(self.ledger)
        try:
            connection.execute(
                """
                UPDATE inbox_sources
                SET stable_identity = ?, content_sha256 = ?
                WHERE source_id = ?
                """,
                (
                    review_ledger.stable_identity(original_sha256),
                    original_sha256,
                    source_id,
                ),
            )
            review_preparation._create_batch(
                connection,
                batch_root,
                [selected],
                batch_id=batch_id,
            )
            connection.execute(
                "UPDATE inbox_batches SET status = 'preparing' WHERE batch_id = ?",
                (batch_id,),
            )
            connection.execute(
                """
                UPDATE inbox_batch_sources
                SET state = 'source_changed'
                WHERE batch_id = ? AND source_id = ?
                """,
                (batch_id, source_id),
            )
            connection.execute(
                """
                UPDATE inbox_sources SET lifecycle_state = 'source_changed'
                WHERE source_id = ?
                """,
                (source_id,),
            )
            connection.execute(
                """
                UPDATE inbox_source_locations SET modified_ns = NULL
                WHERE source_id = ? AND is_current = 1
                """,
                (source_id,),
            )
            connection.commit()
        finally:
            connection.close()
        source.write_bytes(b"x" * source.stat().st_size)
        resume_scan = {
            **scan,
            "sources": [],
            "selected_sources": [],
            "pending_batches": [
                {
                    "batch_id": batch_id,
                    "status": "preparing",
                    "package_path": str(batch_root),
                }
            ],
        }

        with mock.patch.object(
            review_inbox,
            "scan_from_request",
            side_effect=AssertionError(
                "Stable foundation recovery must not scan or allocate new media."
            ),
        ):
            with self.assertRaisesRegex(
                review_preparation.SourceChangedError,
                "full SHA-256 identity",
            ):
                review_preparation.prepare_selected_from_request(
                    self.payload(
                        scan_result=resume_scan,
                        selected_source_ids=[],
                        resume_batch_id=batch_id,
                    )
                )

        self.assertEqual(self.query("SELECT COUNT(*) FROM inbox_batches"), [(1,)])
        self.assertEqual(
            self.query(
                "SELECT content_sha256 FROM inbox_sources WHERE source_id = ?",
                (source_id,),
            ),
            [(original_sha256,)],
        )
        self.assertEqual(
            self.query(
                "SELECT modified_ns FROM inbox_source_locations "
                "WHERE source_id = ? AND is_current = 1",
                (source_id,),
            ),
            [(None,)],
        )

    def test_source_mutation_during_copy_is_classified_changed(self) -> None:
        source = self.make_sources(1)[0]

        def mutating_copy(original: Path, target: Path) -> dict:
            target.parent.mkdir(parents=True, exist_ok=True)
            data = original.read_bytes()
            target.write_bytes(data)
            original.write_bytes(data + b"changed")
            return {"sha256": hashlib.sha256(data).hexdigest(), "bytes_copied": len(data), "before": {}, "after": {}}

        result = review_preparation.prepare_from_request(self.payload(copy_file=mutating_copy))
        self.assertEqual(result["failed_sources"][0]["state"], "source_changed")

    def test_no_audio_prepares_visuals_with_explicit_transcript_status(self) -> None:
        self.make_sources(1)
        result = review_preparation.prepare_from_request(self.payload(media_probe=lambda _path: self.media(0)))
        package = Path(result["prepared_sources"][0]["package_path"])
        status = json.loads((package / "source-manifest.json").read_text(encoding="utf-8"))["transcription"]
        self.assertEqual(status["status"], "not_applicable_no_audio")
        self.assertFalse(any(item[0] == "extract" for item in self.events))

    def test_single_audio_auto_resolves_and_exact_selected_stream_is_used(self) -> None:
        self.make_sources(1)
        result = review_preparation.prepare_from_request(self.payload())
        self.assertEqual(result["prepared_sources"][0]["audio_state"], "single-stream")
        self.assertIn(("extract", 0), self.events)

    def test_only_one_audible_stream_auto_resolves_without_choice(self) -> None:
        self.make_sources(1)
        media = self.media(3)
        audibility = {
            "contract_version": 1,
            "source_state": "audible_candidates",
            "threshold_policy": {},
            "full_source_check_completed": False,
            "streams": [
                {
                    "operator_track_number": index + 1,
                    "audio_ordinal": index,
                    "ffprobe_stream_index": index + 1,
                    "ffmpeg_map": f"0:a:{index}",
                    "bounded_state": (
                        "audible_signal"
                        if index == 1
                        else "digital_silence"
                    ),
                    "full_source_checked": index != 1,
                    "decode_succeeded": True,
                    "final_state": (
                        "audible_signal"
                        if index == 1
                        else "digital_silence"
                    ),
                    "preview_regions": [],
                }
                for index in range(3)
            ],
        }

        result = review_preparation.prepare_from_request(
            self.payload(
                media_probe=lambda _path: media,
                audibility_inspector=(
                    lambda _source, _media, _temp_root: audibility
                ),
            )
        )

        self.assertEqual(result["status"], "awaiting_external_review")
        self.assertEqual(
            result["prepared_sources"][0]["audio_state"],
            "single-audible-stream",
        )
        self.assertIn(("extract", 1), self.events)

    def test_unknown_multitrack_blocks_without_copy(self) -> None:
        self.make_sources(1)
        result = review_preparation.prepare_from_request(self.payload(media_probe=lambda _path: self.media(2)))
        self.assertEqual(result["status"], "needs_audio_confirmation")
        self.assertEqual(result["blocked_sources"][0]["state"], "needs_audio_confirmation")
        self.assertEqual(self.events, [])

    def test_all_stream_silent_source_skips_choice_and_whisper_but_keeps_visual_review(
        self,
    ) -> None:
        self.make_sources(1)
        media = self.media(6, duration=45.0)
        audibility = {
            "contract_version": 1,
            "source_state": "no_audible_narration",
            "threshold_policy": {"exact_zero_is_silent": True},
            "full_source_check_completed": True,
            "streams": [
                {
                    "operator_track_number": index + 1,
                    "audio_ordinal": index,
                    "ffprobe_stream_index": index + 1,
                    "ffmpeg_map": f"0:a:{index}",
                    "bounded_state": "digital_silence",
                    "full_source_checked": True,
                    "decode_succeeded": True,
                    "final_state": "digital_silence",
                    "preview_regions": [],
                }
                for index in range(6)
            ],
        }

        result = review_preparation.prepare_from_request(
            self.payload(
                media_probe=lambda _path: media,
                audibility_inspector=(
                    lambda _source, _media, _temp_root: audibility
                ),
            )
        )

        self.assertEqual(result["status"], "awaiting_external_review")
        self.assertEqual(
            result["prepared_sources"][0]["audio_state"],
            "no_audible_narration",
        )
        self.assertFalse(any(event[0] == "extract" for event in self.events))
        self.assertFalse(any(event[0] == "transcribe" for event in self.events))
        package = Path(result["prepared_sources"][0]["package_path"])
        transcript = json.loads(
            (package / "transcript" / "transcript-status.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            transcript["status"],
            "not_applicable_no_audible_narration",
        )
        self.assertTrue(transcript["transcription_skipped"])
        manifest = json.loads(
            (package / "source-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            manifest["audio_selection"]["state"],
            "no_audible_narration",
        )
        self.assertEqual(
            manifest["media_metadata"]["audio_audibility"]["source_state"],
            "no_audible_narration",
        )
        self.assertEqual(
            [
                (
                    item["operator_track_number"],
                    item["audio_ordinal"],
                    item["ffprobe_stream_index"],
                    item["ffmpeg_map"],
                )
                for item in manifest["media_metadata"]["audio_audibility"][
                    "streams"
                ]
            ],
            [
                (index + 1, index, index + 1, f"0:a:{index}")
                for index in range(6)
            ],
        )
        self.assertTrue((package / "visuals" / "contact-sheet.jpg").is_file())
        self.assertIn(
            "visual-only source still requires review",
            (Path(result["batch_path"]) / "CODEX_REVIEW_PROMPT.md")
            .read_text(encoding="utf-8")
            .lower(),
        )
        self.assertEqual(list(package.rglob("*.wav")), [])
        self.assertEqual(list(self.scratch.rglob("*.wav")), [])

    def test_inconclusive_audibility_stops_as_attention_without_copy_or_track(
        self,
    ) -> None:
        self.make_sources(1)
        media = self.media(2)
        audibility = {
            "contract_version": 1,
            "source_state": "inconclusive",
            "threshold_policy": {},
            "full_source_check_completed": True,
            "streams": [
                {
                    "operator_track_number": index + 1,
                    "audio_ordinal": index,
                    "ffprobe_stream_index": index + 1,
                    "ffmpeg_map": f"0:a:{index}",
                    "bounded_state": "inconclusive",
                    "full_source_checked": True,
                    "decode_succeeded": True,
                    "final_state": "inconclusive",
                    "preview_regions": [],
                }
                for index in range(2)
            ],
        }
        result = review_preparation.prepare_from_request(
            self.payload(
                media_probe=lambda _path: media,
                audibility_inspector=(
                    lambda _source, _media, _temp_root: audibility
                ),
            )
        )
        self.assertEqual(result["status"], "preparing")
        self.assertEqual(
            result["failed_sources"][0]["attention_code"],
            "audio_audibility_inconclusive",
        )
        self.assertEqual(self.events, [])
        self.assertEqual(
            self.query("SELECT lifecycle_state FROM inbox_sources"),
            [("retryable_failure",)],
        )

    def test_mixed_layout_never_reuses_a_confirmed_silent_track(
        self,
    ) -> None:
        self.make_sources(1)
        media = self.media(3)
        fingerprint = media["audio_layout_fingerprint"]
        audibility = {
            "contract_version": 1,
            "source_state": "audible_candidates",
            "threshold_policy": {},
            "full_source_check_completed": True,
            "streams": [
                {
                    "operator_track_number": index + 1,
                    "audio_ordinal": index,
                    "ffprobe_stream_index": index + 1,
                    "ffmpeg_map": f"0:a:{index}",
                    "bounded_state": (
                        "audible_signal"
                        if index in {1, 2}
                        else "digital_silence"
                    ),
                    "full_source_checked": index == 0,
                    "decode_succeeded": True,
                    "final_state": (
                        "audible_signal"
                        if index in {1, 2}
                        else "digital_silence"
                    ),
                    "preview_regions": [],
                }
                for index in range(3)
            ],
        }
        stale_confirmation = {
            fingerprint: {
                "layoutFingerprint": fingerprint,
                "audioOrdinal": 0,
                "confirmationSource": "operator",
            }
        }
        blocked = review_preparation.prepare_from_request(
            self.payload(
                media_probe=lambda _path: media,
                audibility_inspector=(
                    lambda _source, _media, _temp_root: audibility
                ),
                audio_confirmations=stale_confirmation,
            )
        )
        self.assertEqual(blocked["status"], "needs_audio_confirmation")
        self.assertEqual(
            blocked["blocked_sources"][0]["audibility_contract_version"],
            1,
        )
        self.assertEqual(
            blocked["blocked_sources"][0]["audio_audibility_state"],
            "audible_candidates",
        )
        self.assertEqual(
            blocked["blocked_sources"][0]["audio_audibility"]["streams"][0][
                "final_state"
            ],
            "digital_silence",
        )
        self.assertEqual(self.events, [])

    def test_exact_layout_confirmation_resumes_and_changed_layout_blocks(self) -> None:
        self.make_sources(1)
        media = self.media(2)
        fingerprint = media["audio_layout_fingerprint"]
        confirmations = {fingerprint: {"layoutFingerprint": fingerprint, "audioOrdinal": 1, "confirmationSource": "operator"}}
        first = review_preparation.prepare_from_request(self.payload(media_probe=lambda _path: media, audio_confirmations=confirmations))
        self.assertEqual(first["prepared_sources"][0]["audio_state"], "confirmed-layout")
        self.assertIn(("extract", 1), self.events)

        other_root = Path(tempfile.mkdtemp(dir=self.root))
        other_sources = other_root / "sources"
        other_sources.mkdir()
        (other_sources / "changed.mp4").write_bytes(b"changed-layout")
        other_ledger = other_root / "ledger.sqlite"
        # A second Inbox: a library of its own, as it had a ledger of its own (224, Wave B2b).
        inbox_library.use_own_library(self, other_root)
        inbox_library.ready(other_ledger)
        changed_media = self.media(3)
        blocked = review_preparation.prepare_from_request(
            self.payload(source_folders=[str(other_sources)], ledger_path=str(other_ledger), evidence_root=str(other_root / "evidence"), scratch_root=str(other_root / "scratch"), media_probe=lambda _path: changed_media, audio_confirmations=confirmations)
        )
        self.assertEqual(blocked["status"], "needs_audio_confirmation")

    def test_marker_free_transcript_and_complete_artifacts_are_retained(self) -> None:
        self.make_sources(1)
        result = review_preparation.prepare_from_request(self.payload())
        package = Path(result["prepared_sources"][0]["package_path"])
        for relative in (
            "source-manifest.json",
            "integrity.json",
            "transcript/transcript.json",
            "transcript/transcript.srt",
            "transcript/transcript.txt",
            "transcript/transcript.quality.json",
            "visuals/timeline-index.json",
            "visuals/contact-sheet.jpg",
            "hints/README.txt",
        ):
            self.assertTrue((package / relative).is_file(), relative)
        self.assertIn("ordinary narration", (package / "transcript" / "transcript.txt").read_text(encoding="utf-8"))

    def test_manifest_integrity_and_lifecycle_relationships_validate(self) -> None:
        self.make_sources(2)
        result = review_preparation.prepare_from_request(self.payload())
        batch_root = Path(result["batch_path"])
        self.assertTrue((batch_root / "batch-manifest.json").is_file())
        self.assertTrue((batch_root / "logs" / "preparation.log").is_file())
        states = self.query("SELECT state FROM inbox_batch_sources WHERE batch_id=? ORDER BY ordinal", (result["batch_id"],))
        self.assertEqual(states, [("awaiting_external_review",), ("awaiting_external_review",)])
        attempts = self.query("SELECT status FROM inbox_attempts WHERE batch_id=? ORDER BY attempt_id", (result["batch_id"],))
        self.assertEqual(attempts, [("prepared",), ("prepared",)])
        signatures = self.query("SELECT preparation_signature FROM inbox_batch_sources WHERE batch_id=?", (result["batch_id"],))
        self.assertTrue(all(len(str(row[0])) == 64 for row in signatures))
        events = self.query("SELECT COUNT(*) FROM inbox_lifecycle_events WHERE batch_id=?", (result["batch_id"],))[0][0]
        self.assertGreaterEqual(events, 7)
        connection = inbox_library.connect()
        try:
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            connection.close()

    def test_prepared_integrity_accepts_zero_byte_artifact_with_exact_hash(self) -> None:
        package = self.root / "zero-byte-package"
        package.mkdir()
        artifact = package / "transcript.srt"
        artifact.write_bytes(b"")
        self.write_test_integrity(
            package,
            artifact,
            {
                "path": artifact.name,
                "size_bytes": 0,
                "sha256": hashlib.sha256(b"").hexdigest(),
            },
        )

        self.assertEqual(review_preparation._validate_source_package(package), 2)

    def test_prepared_integrity_zero_byte_artifact_still_requires_exact_hash(self) -> None:
        package = self.root / "zero-byte-wrong-hash"
        package.mkdir()
        artifact = package / "transcript.srt"
        artifact.write_bytes(b"")
        self.write_test_integrity(
            package,
            artifact,
            {"path": artifact.name, "size_bytes": 0, "sha256": "0" * 64},
        )

        with self.assertRaisesRegex(RuntimeError, "artifact hash changed"):
            review_preparation._validate_source_package(package)

    def test_prepared_integrity_rejects_malformed_recorded_sizes(self) -> None:
        malformed_sizes = {
            "missing": object(),
            "null": None,
            "boolean-false": False,
            "boolean-true": True,
            "string": "0",
            "float": 0.0,
            "negative": -1,
        }
        for name, recorded_size in malformed_sizes.items():
            with self.subTest(name=name):
                package = self.root / f"malformed-size-{name}"
                package.mkdir()
                artifact = package / "artifact.bin"
                artifact.write_bytes(b"")
                record = {
                    "path": artifact.name,
                    "sha256": hashlib.sha256(b"").hexdigest(),
                }
                if name != "missing":
                    record["size_bytes"] = recorded_size
                self.write_test_integrity(package, artifact, record)

                with self.assertRaisesRegex(RuntimeError, "Integrity inventory size is malformed"):
                    review_preparation._validate_source_package(package)

    def test_prepared_integrity_rejects_nonzero_size_mismatch(self) -> None:
        package = self.root / "nonzero-size-mismatch"
        package.mkdir()
        artifact = package / "artifact.bin"
        artifact.write_bytes(b"content")
        self.write_test_integrity(
            package,
            artifact,
            {
                "path": artifact.name,
                "size_bytes": artifact.stat().st_size + 1,
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            },
        )

        with self.assertRaisesRegex(RuntimeError, "artifact size changed"):
            review_preparation._validate_source_package(package)

    def test_one_source_failure_does_not_corrupt_next_source(self) -> None:
        self.make_sources(2)
        calls = 0

        def render(source: Path, media: dict, output: Path) -> dict:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("synthetic render failure")
            return self.render(source, media, output)

        result = review_preparation.prepare_from_request(self.payload(visual_renderer=render))
        self.assertEqual(len(result["failed_sources"]), 1)
        self.assertEqual(len(result["prepared_sources"]), 1)
        self.assertEqual(calls, 2)

    def test_relaunch_excludes_prepared_batch_and_explicit_resume_is_idempotent(self) -> None:
        self.make_sources(1)
        first = review_preparation.prepare_from_request(self.payload())
        second = review_preparation.prepare_from_request(self.payload())
        self.assertEqual(second["status"], "pending_batch_limit_reached")
        resumed = review_preparation.prepare_from_request(self.payload(resume_batch_id=first["batch_id"]))
        self.assertEqual(resumed["status"], "awaiting_external_review")
        self.assertEqual(resumed["prepared_sources"], first["prepared_sources"])
        self.assertEqual(self.query("SELECT COUNT(*) FROM inbox_attempts"), [(1,)])

    def test_crash_recovery_distinguishes_live_reusable_and_invalid_attempts(self) -> None:
        batch = self.evidence / "review-inbox" / "batches" / "batch-test"
        staging = batch / ".staging"
        working = self.scratch / "review-inbox" / "batch-test" / "attempt-2" / "source.mp4"
        working.parent.mkdir(parents=True)
        working.write_bytes(b"reusable")
        for name, payload in (
            ("attempt-1", {"status": "preparing", "process_id": 44}),
            ("attempt-2", {"status": "preparing", "process_id": 45, "working_copy_path": str(working), "expected_size": working.stat().st_size, "expected_sha256": hashlib.sha256(working.read_bytes()).hexdigest()}),
            ("attempt-3", {"status": "preparing", "process_id": 46, "working_copy_path": str(self.root / "outside.mp4"), "expected_size": 1, "expected_sha256": "0" * 64}),
        ):
            review_preparation._atomic_json(staging / name / "attempt-state.json", payload)
        actions = review_preparation.recover_staging(batch, self.scratch, process_checker=lambda pid: pid == 44)
        classes = {item["attempt"]: item["classification"] for item in actions}
        self.assertEqual(classes, {"attempt-1": "still_live", "attempt-2": "stale_reusable", "attempt-3": "stale_restart_required"})
        rerun = review_preparation.recover_staging(batch, self.scratch, process_checker=lambda _pid: False)
        self.assertEqual({item["attempt"] for item in rerun}, {"attempt-1", "attempt-2", "attempt-3"})

    def test_process_resume_adopts_one_verified_stale_copy_and_cleans_scratch(
        self,
    ) -> None:
        source = self.make_sources(1)[0]
        first_scan = review_inbox.scan_from_request(self.payload())
        selected = list(first_scan["selected_sources"])
        batch_id = "batch-recovery-copy"
        batch_root = self.root / "batches" / batch_id
        connection = inbox_records.connect(self.ledger)
        try:
            review_preparation._create_batch(
                connection,
                batch_root,
                selected,
                batch_id=batch_id,
            )
            attempt_id = review_preparation._attempt_start(
                connection,
                int(selected[0]["source_id"]),
                batch_id,
                "crashed-settings",
            )
            newer_attempt_id = review_preparation._attempt_start(
                connection,
                int(selected[0]["source_id"]),
                batch_id,
                "second-crashed-settings",
            )
        finally:
            connection.close()
        working = (
            self.scratch
            / "review-inbox"
            / batch_id
            / f"attempt-{attempt_id}"
            / "source"
            / "source.mp4"
        )
        working.parent.mkdir(parents=True)
        working.write_bytes(source.read_bytes())
        digest = hashlib.sha256(working.read_bytes()).hexdigest()
        # A process that has ended, whose number Windows cannot give out again while this test holds it
        # (224: a made-up number can match a real process, because Windows ignores its last two bits).
        ended = subprocess.Popen([sys.executable, "-c", "pass"])
        ended.wait(30)
        stale_state = {
            "status": "preparing",
            "process_id": ended.pid,
            "source_id": int(selected[0]["source_id"]),
            "working_copy_path": str(working),
            "expected_size": working.stat().st_size,
            "expected_sha256": digest,
            "copy_validated": True,
        }
        for stale_attempt_id in (attempt_id, newer_attempt_id):
            state = (
                batch_root
                / ".staging"
                / f"attempt-{stale_attempt_id}"
                / "attempt-state.json"
            )
            state.parent.mkdir(parents=True)
            review_preparation._atomic_json(state, stale_state)
        resumed_scan = review_inbox.scan_from_request(self.payload())

        def must_not_copy(_source: Path, _target: Path) -> dict:
            raise AssertionError("A second full source copy must not be created.")

        result = review_preparation.prepare_selected_from_request(
            self.payload(
                scan_result=resumed_scan,
                resume_batch_id=batch_id,
                selected_source_ids=[],
                copy_file=must_not_copy,
            )
        )

        self.assertEqual(result["status"], "awaiting_external_review")
        manifest_path = (
            Path(result["prepared_sources"][0]["package_path"])
            / "source-manifest.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertTrue(
            manifest["copy_validation"]["recovered_verified_copy"]
        )
        self.assertFalse(any(self.scratch.rglob("source.mp4")))
        self.assertEqual(
            self.query(
                "SELECT attempt_id, status FROM inbox_attempts "
                "WHERE attempt_id IN (?, ?) ORDER BY attempt_id",
                (attempt_id, newer_attempt_id),
            ),
            [
                (attempt_id, "recovered_restart_required"),
                (newer_attempt_id, "recovered_reused"),
            ],
        )

    def test_a_crash_before_the_first_state_file_or_after_the_copy_leaves_nothing_behind(self) -> None:
        # 224 (Wave B2a, note 5): an attempt that crashed before its first state file was never closed and its
        # scratch folder stayed; one that crashed after the copy left its half-built staging package.
        self.make_sources(1)
        scan = review_inbox.scan_from_request(self.payload())
        selected = list(scan["selected_sources"])
        source_id = int(selected[0]["source_id"])
        batch_id = "batch-crash-windows"
        batch_root = self.root / "batches" / batch_id
        connection = inbox_records.connect(self.ledger)
        try:
            review_preparation._create_batch(connection, batch_root, selected, batch_id=batch_id)
            early = review_preparation._attempt_start(connection, source_id, batch_id, "early-crash")
            late = review_preparation._attempt_start(connection, source_id, batch_id, "late-crash")
        finally:
            connection.close()
        # The early one: its voice check had made scratch, and then it ended before its first state file.
        early_stage = batch_root / ".staging" / f"attempt-{early}"
        early_stage.mkdir(parents=True)
        early_scratch = self.scratch / "review-inbox" / batch_id / f"attempt-{early}"
        (early_scratch / "voice-track").mkdir(parents=True)
        (early_scratch / "voice-track" / "track-1.wav").write_bytes(b"decoded audio")
        # The late one: it ended while its package was being built, after the copy.
        ended = subprocess.Popen([sys.executable, "-c", "pass"])
        ended.wait(30)
        late_stage = batch_root / ".staging" / f"attempt-{late}"
        review_preparation._atomic_json(late_stage / "attempt-state.json", {
            "status": "preparing", "process_id": ended.pid, "source_id": source_id,
            "working_copy_path": str(self.scratch / "review-inbox" / batch_id / f"attempt-{late}" / "source" / "source.mp4"),
            "expected_size": 1, "expected_sha256": "0" * 64, "copy_validated": True})
        (late_stage / "source" / "transcript").mkdir(parents=True)
        (late_stage / "source" / "transcript" / "transcript.json").write_text("{}", encoding="utf-8")

        result = review_preparation.prepare_selected_from_request(
            self.payload(scan_result=review_inbox.scan_from_request(self.payload()), resume_batch_id=batch_id,
                         selected_source_ids=[])
        )

        self.assertEqual(result["status"], "awaiting_external_review")
        self.assertEqual(
            self.query("SELECT attempt_id, status FROM inbox_attempts WHERE attempt_id IN (?, ?) ORDER BY attempt_id",
                       (early, late)),
            [(early, "recovered_restart_required"), (late, "recovered_restart_required")],
        )
        self.assertFalse(early_stage.exists())
        self.assertFalse(early_scratch.exists())
        self.assertFalse((late_stage / "source").exists())
        self.assertEqual(self.query("SELECT COUNT(*) FROM inbox_attempts WHERE status = 'preparing'"), [(0,)])

    def test_resume_reconciles_valid_package_promoted_before_ledger_update(
        self,
    ) -> None:
        self.make_sources(1)
        scan = review_inbox.scan_from_request(self.payload())
        source_id = int(scan["selected_sources"][0]["source_id"])
        first = review_preparation.prepare_selected_from_request(
            self.payload(
                scan_result=scan,
                selected_source_ids=[source_id],
                preallocated_batch_id="batch-promoted-crash",
            )
        )
        self.assertEqual(first["status"], "awaiting_external_review")
        batch_id = str(first["batch_id"])
        connection = inbox_library.connect()
        try:
            connection.execute(
                "UPDATE inbox_batches SET status = 'preparing' WHERE batch_id = ?",
                (batch_id,),
            )
            connection.execute(
                "UPDATE inbox_batch_sources SET state = 'preparing' WHERE batch_id = ?",
                (batch_id,),
            )
            connection.execute(
                """
                UPDATE inbox_sources
                SET lifecycle_state = 'preparing'
                WHERE source_id IN (
                    SELECT source_id FROM inbox_batch_sources WHERE batch_id = ?
                )
                """,
                (batch_id,),
            )
            connection.commit()
        finally:
            connection.close()
        self.events.clear()
        resumed_scan = review_inbox.scan_from_request(self.payload())

        recovered = review_preparation.prepare_selected_from_request(
            self.payload(
                scan_result=resumed_scan,
                resume_batch_id=batch_id,
                selected_source_ids=[],
            )
        )

        self.assertEqual(recovered["status"], "awaiting_external_review")
        self.assertTrue(
            recovered["prepared_sources"][0]["recovered_promoted_package"]
        )
        self.assertEqual(self.events, [])
        self.assertEqual(
            self.query(
                "SELECT state FROM inbox_batch_sources WHERE batch_id = ?",
                (batch_id,),
            ),
            [("awaiting_external_review",)],
        )

    def test_path_containment_rejects_outside_cleanup(self) -> None:
        outside = self.root / "outside.txt"
        outside.write_text("keep", encoding="utf-8")
        with self.assertRaises(ValueError):
            review_preparation._safe_remove(self.scratch, outside)
        self.assertTrue(outside.exists())

    def test_sparse_timeline_formula_and_supported_panel_crops(self) -> None:
        self.assertEqual(review_preparation.timeline_frame_count(0), 6)
        self.assertEqual(review_preparation.timeline_frame_count(1800), 6)
        self.assertEqual(review_preparation.timeline_frame_count(3600), 12)
        self.assertEqual(review_preparation.timeline_frame_count(99_999), 24)
        source = self.root / "synthetic-wide.mp4"
        source.write_bytes(b"not-decoded-by-mocked-run")
        output = self.root / "visuals"
        commands: list[list[str]] = []

        def fake_run(command: list[str], **_kwargs: object) -> object:
            commands.append(command)
            target = Path(command[-1])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"image")
            stderr = ""
            if "showinfo" in command:
                requested = float(command[command.index("-ss") + 1])
                stderr = f"showinfo pts_time:{requested}"
            return mock.Mock(returncode=0, stderr=stderr, stdout="")

        def fake_image(
            _ffprobe: str,
            _root: Path,
            target: Path,
            *,
            expected_width: int = 0,
            expected_height: int = 0,
        ) -> dict[str, object]:
            return {
                "size_bytes": target.stat().st_size,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "width": expected_width or 1,
                "height": expected_height or 1,
            }

        media = self.media(1, width=5760, height=1080, duration=60)
        media["video_frame_timestamps"] = [5.0, 15.0, 25.0, 35.0, 45.0, 55.0]
        with (
            mock.patch.object(review_preparation, "_run", side_effect=fake_run),
            mock.patch.object(
                review_preparation,
                "_validate_rendered_image",
                side_effect=fake_image,
            ),
        ):
            rendered = review_preparation._render_visuals(
                "ffmpeg",
                source,
                media,
                output,
            )
        self.assertEqual(rendered["frame_count"], 6)
        self.assertEqual(len(rendered["panels"]), 18)
        self.assertEqual({item["panel"] for item in rendered["panels"]}, {"overview_cam", "driver_view", "face_cam"})
        self.assertTrue(commands)
        for command in commands:
            self.assertIn("-pix_fmt", command)
            self.assertEqual(command[command.index("-pix_fmt") + 1], "yuvj420p")

        commands.clear()
        compact_output = self.root / "compact-visuals"
        with (
            mock.patch.object(review_preparation, "_run", side_effect=fake_run),
            mock.patch.object(
                review_preparation,
                "_validate_rendered_image",
                side_effect=fake_image,
            ),
        ):
            compact = review_preparation._render_visuals(
                "ffmpeg",
                source,
                media,
                compact_output,
                include_panel_crops=False,
            )
        self.assertEqual(compact["panels"], [])
        self.assertEqual(compact["supported_panel_ids"], ["overview_cam", "driver_view", "face_cam"])
        self.assertFalse((compact_output / "panels").exists())
        self.assertTrue(commands)
        for command in commands:
            self.assertIn("-pix_fmt", command)
            self.assertEqual(command[command.index("-pix_fmt") + 1], "yuvj420p")

    def test_process_mode_uses_explicit_chunks_and_allows_externally_waiting_batches(self) -> None:
        self.make_sources(4)
        scan = review_inbox.scan_from_request(self.payload())
        source_ids = [int(item["source_id"]) for item in scan["sources"]]

        first = review_preparation.prepare_selected_from_request(
            self.payload(
                scan_result=scan,
                selected_source_ids=source_ids[:2],
                preallocated_batch_id="batch-process-first",
                media_probe=lambda _path: self.media(width=5760, height=1080),
            )
        )
        self.assertEqual(first["status"], "awaiting_external_review")
        self.assertEqual(Path(first["batch_path"]), self.ledger.parent / "batches" / "batch-process-first")
        first_manifest = json.loads(
            (Path(first["prepared_sources"][0]["package_path"]) / "source-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(first_manifest["visuals"]["panels"], [])
        self.assertEqual(
            first_manifest["visuals"]["supported_panel_ids"],
            ["overview_cam", "driver_view", "face_cam"],
        )
        first_batch_root = Path(first["batch_path"])
        self.assertFalse(any(path.suffix.casefold() == ".wav" for path in first_batch_root.rglob("*") if path.is_file()))
        self.assertFalse(
            any(
                path.name.casefold().endswith((".mp4", ".mkv", ".mov"))
                for path in first_batch_root.rglob("*")
                if path.is_file()
            )
        )

        rescanned = review_inbox.scan_from_request(self.payload())
        second = review_preparation.prepare_selected_from_request(
            self.payload(
                scan_result=rescanned,
                selected_source_ids=source_ids[2:],
                preallocated_batch_id="batch-process-second",
            )
        )
        self.assertEqual(second["status"], "awaiting_external_review")
        self.assertEqual(self.query("SELECT COUNT(*) FROM inbox_batches"), [(2,)])

    def test_process_mode_rejects_more_than_three_sources(self) -> None:
        with self.assertRaisesRegex(ValueError, "at most three"):
            review_preparation.prepare_selected_from_request(
                self.payload(
                    selected_source_ids=[1, 2, 3, 4],
                    preallocated_batch_id="batch-too-large",
                )
            )

    def test_process_mode_stops_chunk_at_first_audio_choice(self) -> None:
        self.make_sources(2)
        scan = review_inbox.scan_from_request(self.payload())
        source_ids = [int(item["source_id"]) for item in scan["sources"]]
        result = review_preparation.prepare_selected_from_request(
            self.payload(
                scan_result=scan,
                selected_source_ids=source_ids,
                preallocated_batch_id="batch-audio-pause",
                media_probe=lambda _path: self.media(2),
            )
        )
        self.assertEqual(result["status"], "needs_audio_confirmation")
        self.assertEqual(result["stopped_reason"], "needs_audio_confirmation")
        self.assertEqual(len(result["blocked_sources"]), 1)
        self.assertEqual(result["prepared_sources"], [])
        self.assertEqual(self.events, [])
        self.assertEqual(list(self.scratch.rglob("source.*")), [])
        self.assertEqual(list(self.evidence.rglob("transcript-status.json")), [])
        self.assertEqual(list(self.evidence.rglob("contact-sheet.jpg")), [])
        self.assertEqual(
            self.query("SELECT state FROM inbox_batch_sources WHERE batch_id=? ORDER BY ordinal", ("batch-audio-pause",)),
            [("needs_audio_confirmation",), ("pending",)],
        )

    def test_process_mode_prior_elapsed_time_pauses_before_second_source(self) -> None:
        self.make_sources(2)
        scan = review_inbox.scan_from_request(self.payload())
        source_ids = [int(item["source_id"]) for item in scan["sources"]]
        ticks = iter([0.0, 1.0, 2.0])
        result = review_preparation.prepare_selected_from_request(
            self.payload(
                scan_result=scan,
                selected_source_ids=source_ids,
                preallocated_batch_id="batch-time-boundary",
                prior_elapsed_seconds=14_400,
                clock=lambda: next(ticks),
            )
        )
        self.assertEqual(len(result["prepared_sources"]), 1)
        self.assertEqual(result["stopped_reason"], "soft_duration_boundary")
        self.assertGreaterEqual(result["elapsed_seconds"], 14_400)

    def test_process_mode_rejects_source_changed_after_fixed_snapshot(self) -> None:
        source = self.make_sources(1)[0]
        scan = review_inbox.scan_from_request(self.payload())
        source_id = int(scan["sources"][0]["source_id"])
        source.write_bytes(source.read_bytes() + b"changed-after-snapshot")
        result = review_preparation.prepare_selected_from_request(
            self.payload(
                scan_result=scan,
                selected_source_ids=[source_id],
                preallocated_batch_id="batch-snapshot-change",
            )
        )
        self.assertEqual(result["failed_sources"][0]["state"], "source_changed")
        self.assertEqual(self.events, [])

    def test_process_retry_preserves_fixed_snapshot_mtime_boundary(self) -> None:
        source = self.make_sources(1)[0]
        scan = review_inbox.scan_from_request(self.payload())
        source_id = int(scan["sources"][0]["source_id"])
        recorded_modified_ns = int(source.stat().st_mtime_ns)
        changed = b"x" * source.stat().st_size
        source.write_bytes(changed)
        os.utime(
            source,
            ns=(recorded_modified_ns + 1_000_000, recorded_modified_ns + 1_000_000),
        )

        first = review_preparation.prepare_selected_from_request(
            self.payload(
                scan_result=scan,
                selected_source_ids=[source_id],
                preallocated_batch_id="batch-fixed-snapshot-retry",
            )
        )
        self.assertEqual(first["failed_sources"][0]["state"], "source_changed")
        self.assertEqual(
            self.query(
                "SELECT modified_ns FROM inbox_source_locations "
                "WHERE source_id = ? AND is_current = 1",
                (source_id,),
            ),
            [(recorded_modified_ns,)],
        )

        resume_scan = {
            **scan,
            "pending_batches": [
                {
                    "batch_id": first["batch_id"],
                    "status": "preparing",
                    "package_path": first["batch_path"],
                }
            ],
        }
        second = review_preparation.prepare_selected_from_request(
            self.payload(
                scan_result=resume_scan,
                selected_source_ids=[],
                resume_batch_id=first["batch_id"],
            )
        )

        self.assertEqual(second["failed_sources"][0]["state"], "source_changed")
        self.assertEqual(self.events, [])

    def test_workflow_three_and_four_are_not_imported(self) -> None:
        source = Path(review_preparation.__file__).read_text(encoding="utf-8")
        self.assertNotIn("evidence_package", source)
        self.assertNotIn("archive_catalog", source)
        self.assertNotIn("workflow 4", source.lower())

    def test_structured_progress_contract_reports_real_stages_without_fake_percentages(self) -> None:
        self.make_sources(1)
        events: list[dict] = []
        progress_state = self.root / "controls" / "progress.json"
        result = review_preparation.prepare_from_request(
            self.payload(
                progress_callback=events.append,
                progress_state_file_path=str(progress_state),
            )
        )
        self.assertEqual(result["status"], "awaiting_external_review")
        phases = [event["phase"] for event in events]
        for phase in (
            "Validating source",
            "Checking storage",
            "Inspecting audio",
            "Copying and hashing",
            "Transcribing",
            "Rendering neutral visuals",
            "Validating integrity",
            "Promoting package",
            "Cleaning scratch",
            "Awaiting external review",
        ):
            self.assertIn(phase, phases)
        self.assertTrue(all(event["progress_kind"] == "indeterminate" for event in events))
        saved = json.loads(progress_state.read_text(encoding="utf-8"))
        self.assertEqual(saved["schema"], "MM_PROGRESS_V1")
        self.assertEqual(saved["phase"], "Awaiting external review")
        self.assertTrue(saved["updated_at_utc"])

    def test_file_based_cooperative_stop_is_checked_after_current_source(self) -> None:
        self.make_sources(3)
        stop_path = self.root / "controls" / "stop.signal"

        def progress(event: dict) -> None:
            if event["phase"] == "Source prepared" and event["source_ordinal"] == 1:
                stop_path.parent.mkdir(parents=True, exist_ok=True)
                stop_path.write_text("stop\n", encoding="utf-8")

        result = review_preparation.prepare_from_request(
            self.payload(
                progress_callback=progress,
                stop_after_current_file_path=str(stop_path),
            )
        )
        self.assertEqual(len(result["prepared_sources"]), 1)
        self.assertEqual(result["stopped_reason"], "cooperative_stop_after_current_source")


    # 214: Skip on Queue / Progress works for the Inbox as for every other run.

    def control(self, skip: list[str]) -> Path:
        path = self.root / "run-control.json"
        path.write_text(json.dumps({"pause": False, "skip": skip}), encoding="utf-8")
        return path

    def state_of(self, path: Path) -> str:
        return self.query(
            "SELECT s.lifecycle_state FROM inbox_sources s JOIN inbox_source_locations l ON l.source_id = s.source_id AND l.is_current = 1 WHERE l.original_path = ?",
            (str(path),),
        )[0][0]

    def test_a_recording_skipped_before_it_starts_is_never_touched_and_waits_for_next_time(self) -> None:
        paths = self.make_sources(3)
        result = review_preparation.prepare_from_request(self.payload(run_control_path=str(self.control([str(paths[1])]))))
        self.assertEqual([item["source_name"] for item in result["skipped_by_operator"]], [paths[1].name])
        self.assertEqual(len(result["prepared_sources"]), 2)
        self.assertEqual(result["failed_sources"], [])
        self.assertEqual([item[0] for item in self.events], ["extract", "transcribe", "render"] * 2)
        self.assertEqual(self.state_of(paths[1]), "pending")
        self.assertIn("pending", review_inbox.ELIGIBLE_STATES)

    def test_skipping_the_recording_being_prepared_stops_it_at_its_next_step(self) -> None:
        paths = self.make_sources(2)
        control = self.control([])

        def transcribe_then_skip(audio_path: Path, output: Path, settings: dict) -> dict:
            if not self.events or all(item[0] != "transcribe" for item in self.events):
                # The Workbench names a recording by its file name when that is all it was shown.
                control.write_text(json.dumps({"pause": False, "skip": [paths[0].name]}), encoding="utf-8")
            return self.transcribe(audio_path, output, settings)

        result = review_preparation.prepare_from_request(
            self.payload(run_control_path=str(control), transcriber=transcribe_then_skip)
        )
        self.assertEqual([item["source_name"] for item in result["skipped_by_operator"]], [paths[0].name])
        self.assertEqual(len(result["prepared_sources"]), 1)
        self.assertEqual(result["failed_sources"], [])
        self.assertEqual([item[0] for item in self.events], ["extract", "transcribe", "extract", "transcribe", "render"])
        self.assertEqual(self.state_of(paths[0]), "pending")

    def _real_probe_payload(self, probe, **overrides: object) -> dict:
        """The pipeline's own media probe (``probe_media``, here a stand-in that reports as the frame check
        does), not an injected one; the other parts stay this test class's."""

        payload = self.payload(audibility_inspector=lambda _source, media, _temp: (
            review_preparation._injected_probe_audibility(media)), **overrides)
        payload.pop("media_probe")
        patch = mock.patch.object(review_preparation, "probe_media", side_effect=probe)
        patch.start()
        self.addCleanup(patch.stop)
        return payload

    def test_the_frame_check_shows_real_progress_while_the_source_is_validated(self) -> None:
        # 224 (Wave B2a, 5a): "Validating source" sat at 0% for three minutes on a 757 MB recording.
        self.make_sources(1)
        events: list[dict] = []
        progress_state = self.root / "controls" / "progress.json"
        saved: list[dict] = []

        def probe(_ffprobe: str, _source: Path, *, on_report=None) -> dict:
            for checked in (225.0, 450.0, 675.0):
                on_report(checked, 900.0)
                saved.append(json.loads(progress_state.read_text(encoding="utf-8")))
            return self.media()

        result = review_preparation.prepare_from_request(self._real_probe_payload(
            probe, progress_callback=events.append, progress_state_file_path=str(progress_state)))
        self.assertEqual(result["status"], "awaiting_external_review")
        measured = [event for event in events if event["progress_kind"] == "work_units"]
        self.assertEqual([(event["phase"], event["completed"], event["total"], event["work_unit"])
                          for event in measured],
                         [("Validating source", 225, 900, "seconds"), ("Validating source", 450, 900, "seconds"),
                          ("Validating source", 675, 900, "seconds")])
        self.assertEqual(measured[1]["activity"], "Checking the video: 07:30 of 15:00 checked (50%)")
        self.assertEqual([item["completed"] for item in saved], [225, 450, 675], "in the progress state file too")
        others = [event for event in events if event["progress_kind"] != "work_units"]
        self.assertTrue(others and all("work_unit" not in event for event in others))

    def test_a_skip_pressed_during_the_frame_check_stops_it(self) -> None:
        paths = self.make_sources(2)
        control = self.control([])
        reports: list[float] = []

        def probe(_ffprobe: str, source: Path, *, on_report=None) -> dict:
            if source == paths[0]:
                on_report(60.0, 900.0)
                reports.append(60.0)
                control.write_text(json.dumps({"pause": False, "skip": [paths[0].name]}), encoding="utf-8")
                on_report(120.0, 900.0)
                reports.append(120.0)
            return self.media()

        result = review_preparation.prepare_from_request(self._real_probe_payload(
            probe, run_control_path=str(control)))
        self.assertEqual(reports, [60.0], "the report after the Skip stopped the check")
        self.assertEqual([item["source_name"] for item in result["skipped_by_operator"]], [paths[0].name])
        self.assertEqual(len(result["prepared_sources"]), 1)
        self.assertEqual(self.state_of(paths[0]), "pending")

    def test_a_recording_whose_length_is_not_known_shows_how_far_without_a_false_percent(self) -> None:
        # 224 (Wave B2a review): FFprobe gives no length for a recording cut off by a crash; a measure of
        # "00:30 of 00:00 (100%)" would sit at 100% for the whole check.
        self.make_sources(1)
        events: list[dict] = []

        def probe(_ffprobe: str, _source: Path, *, on_report=None) -> dict:
            on_report(30.0, 0.0)
            return self.media()

        review_preparation.prepare_from_request(self._real_probe_payload(probe, progress_callback=events.append))
        checking = [event for event in events if "Checking the video" in event["activity"]]
        self.assertEqual([(event["progress_kind"], event["activity"]) for event in checking],
                         [("indeterminate", "Checking the video: 00:30 checked")])

    def _fake_ffprobe(self, *, skip_after: int, control: Path, marker: Path) -> Path:
        """A stand-in FFprobe run the way the app runs it: the format and streams as JSON, then the packets one by
        one, slowly; after ``skip_after`` packets the operator presses Skip for the recording."""

        script = self.root / "ffprobe.py"
        script.write_text(
            "import json, os, sys, time\n"
            f"CONTROL, MARKER, SKIP_AFTER = {str(control)!r}, {str(marker)!r}, {skip_after}\n"
            "if not any(argument.startswith('packet=') for argument in sys.argv):\n"
            "    print(json.dumps({'format': {'duration': '900', 'format_name': 'matroska'},\n"
            "                      'streams': [{'index': 0, 'codec_type': 'video', 'codec_name': 'h264',\n"
            "                                   'width': 1280, 'height': 720}]}))\n"
            "    sys.exit(0)\n"
            "open(MARKER, 'w').write(str(os.getpid()))\n"
            "for step in range(9000):\n"
            "    print(f'pts_time={step / 10:.6f}|flags={\"K__\" if step == 0 else \"___\"}', flush=True)\n"
            "    if step == SKIP_AFTER:\n"
            "        with open(CONTROL, 'w', encoding='utf-8') as handle:\n"
            "            json.dump({'pause': False, 'skip': [sys.argv[-1]]}, handle)\n"
            "    time.sleep(0.05)\n",
            encoding="utf-8",
        )
        launcher = self.root / "ffprobe.cmd"
        launcher.write_text(f'@"{sys.executable}" -I "{script}" %*\r\n', encoding="ascii")
        return launcher

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and FFprobe are required")
    def test_the_fallback_full_check_shows_its_progress_too(self) -> None:
        # 224 (Wave B2a review): when a screenshot from a packet's time fails, the recording is checked frame by
        # frame once; on a large recording that takes minutes, so it reports how far it has got like the first.
        clip = self.sources / "source-000.mkv"
        made = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                               "testsrc2=size=160x90:rate=30:duration=4", "-c:v", "libx264", "-bf", "3",
                               "-pix_fmt", "yuv420p", str(clip)], capture_output=True, text=True, timeout=120)
        self.assertEqual(made.returncode, 0, made.stderr)
        real_probe = review_preparation.probe_media

        def probe(ffprobe: str, source: Path, *, on_report=None) -> dict:
            media = real_probe(ffprobe, source)
            # A packet list that does not hold for this recording: every time a little after its picture.
            media["video_frame_timestamps"] = review_preparation._PacketTimes(
                round(value + 0.01, 6) for value in media["video_frame_timestamps"])
            return media

        events: list[dict] = []
        payload = self._real_probe_payload(probe, progress_callback=events.append)
        payload.pop("visual_renderer")
        with mock.patch.object(review_preparation.streaming_progress, "REPORT_SECONDS", 0.0), \
                mock.patch.object(review_preparation.streaming_progress, "LOOK_SECONDS", 0.0005):
            result = review_preparation.prepare_from_request(payload)
        self.assertEqual(result["status"], "awaiting_external_review", result)
        again = [event for event in events if event["phase"] == "Rendering neutral visuals"
                 and event["progress_kind"] == "work_units"]
        self.assertTrue(again, "the full check reported how far it had got")
        self.assertTrue(all(event["activity"].startswith("Checking the video again, picture by picture:")
                            and event["work_unit"] == "seconds" for event in again))

    @unittest.skipUnless(os.name == "nt", "the stand-in FFprobe is a Windows command file")
    def test_a_skip_pressed_while_ffprobe_reads_the_recording_stops_ffprobe_itself(self) -> None:
        # 224 (Wave B2a review): through the real probe and the real reader, not a stand-in probe.
        paths = self.make_sources(1)
        control = self.control([])
        marker = self.root / "ffprobe-pid.txt"
        ffprobe = self._fake_ffprobe(skip_after=20, control=control, marker=marker)
        payload = self.payload(ffprobe_exe=str(ffprobe), run_control_path=str(control),
                               audibility_inspector=lambda _source, media, _temp: (
                                   review_preparation._injected_probe_audibility(media)))
        payload.pop("media_probe")
        started = time.monotonic()
        with mock.patch.object(review_preparation.streaming_progress, "REPORT_SECONDS", 0.3):
            result = review_preparation.prepare_from_request(payload)
        self.assertLess(time.monotonic() - started, 60, "stopped at the Skip, not after the whole recording")
        self.assertEqual([item["source_name"] for item in result["skipped_by_operator"]], [paths[0].name])
        pid = int(marker.read_text())
        listed = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        self.assertNotIn(str(pid), listed, "FFprobe was stopped, not left reading the recording")
        self.assertEqual(self.state_of(paths[0]), "pending")

    def test_a_skip_that_arrives_while_a_failure_is_reported_never_ends_the_run(self) -> None:
        # 224 (Wave B2a, note 6): the failure report ran while the skip watch was still set, so a Skip arriving
        # at that moment raised out of the loop and ended the whole run.
        paths = self.make_sources(2)
        control = self.control([])
        failed_once: list[bool] = []

        def fail_then_skip(audio_path: Path, output: Path, settings: dict) -> dict:
            if not failed_once:
                failed_once.append(True)
                control.write_text(json.dumps({"pause": False, "skip": [paths[0].name]}), encoding="utf-8")
                raise RuntimeError("The transcriber stopped.")
            return self.transcribe(audio_path, output, settings)

        result = review_preparation.prepare_from_request(
            self.payload(run_control_path=str(control), transcriber=fail_then_skip)
        )
        self.assertEqual([item["state"] for item in result["failed_sources"]], ["retryable_failure"])
        self.assertEqual(len(result["prepared_sources"]), 1, "the run went on to the next recording")
        self.assertEqual(self.state_of(paths[0]), "retryable_failure")
    # 214: the Inbox uses the shared engine for audio, track choice and invented-line filters.

    def detector(self, result: dict, calls: list) -> object:
        def detect(source: Path, work_dir: Path, keep_dir: Path) -> dict:
            calls.append(source.name)
            kept = []
            if result.get("status") == "selected":
                keep_dir.mkdir(parents=True, exist_ok=True)
                wav = keep_dir / f"track-{result['selected_ordinal']}.wav"
                wav.write_text("decoded by the voice detection", encoding="utf-8")
                kept = [{"ordinal": result["selected_ordinal"], "path": str(wav)}]
            return {**result, "kept_track_wavs": kept}

        return detect

    def test_the_shared_engine_chooses_the_track_and_its_audio_is_not_read_again(self) -> None:
        self.make_sources(1)
        media = self.media(3)
        calls: list = []
        result = review_preparation.prepare_from_request(self.payload(
            media_probe=lambda _path: media,
            voice_detector=self.detector({"status": "selected", "selected_ordinal": 1, "explanation": "Auto-detected: Track 2 is your voice."}, calls),
        ))
        self.assertEqual(result["status"], "awaiting_external_review")
        self.assertEqual(result["prepared_sources"][0]["audio_state"], "voice-detected")
        self.assertEqual(calls, ["source-000.mp4"])
        self.assertEqual(self.events[:2], [("transcribe", "decoded by the voice detection"), ("render", 1)])

    def test_you_are_asked_only_when_the_shared_engine_cannot_tell(self) -> None:
        self.make_sources(1)
        media = self.media(3)
        calls: list = []
        result = review_preparation.prepare_from_request(self.payload(
            media_probe=lambda _path: media,
            voice_detector=self.detector({"status": "uncertain", "selected_ordinal": None}, calls),
        ))
        self.assertEqual(calls, ["source-000.mp4"])
        self.assertEqual(result["status"], "needs_audio_confirmation")
        self.assertEqual(result["blocked_sources"][0]["state"], "needs_audio_confirmation")
        self.assertEqual(self.events, [])

    def test_264_your_answer_for_this_recording_comes_before_your_saved_layout_answer(self) -> None:
        from media_manglers.core import speech_facts

        path = self.make_sources(1)[0]
        speech_facts.confirm_track(path, 3, by=speech_facts.ANSWERED_ON_BUGS)
        media = self.media(3)
        fingerprint = media["audio_layout_fingerprint"]
        calls: list = []
        result = review_preparation.prepare_from_request(self.payload(
            media_probe=lambda _path: media,
            audio_confirmations={fingerprint: {"layoutFingerprint": fingerprint, "audioOrdinal": 1}},
            voice_detector=self.detector({"status": "selected", "selected_ordinal": 0}, calls),
        ))
        self.assertEqual(result["prepared_sources"][0]["audio_state"], "confirmed-recording")
        self.assertEqual(calls, [])
        self.assertIn(("extract", 2), self.events)

    def test_264_a_track_with_no_audible_sound_cannot_be_the_answer_and_the_saved_answer_stays(self) -> None:
        selection = review_preparation._audio_selection(
            {"audio_streams": [{"ordinal": 0, "ffmpeg_map": "0:a:0"}, {"ordinal": 1, "ffmpeg_map": "0:a:1"}, {"ordinal": 2, "ffmpeg_map": "0:a:2"}],
             "audio_layout_fingerprint": "this",
             "audio_audibility": {"source_state": "audible_candidates", "streams": [
                 {"audio_ordinal": 0, "final_state": "audible_signal"}, {"audio_ordinal": 1, "final_state": "audible_signal"},
                 {"audio_ordinal": 2, "final_state": "digital_silence"}]}},
            {"this": {"layoutFingerprint": "this", "audioOrdinal": 1}}, 3)
        self.assertEqual((selection["state"], selection["selected_ordinal"]), ("confirmed-layout", 1))

    def test_264_the_only_audible_track_rule_still_comes_first(self) -> None:
        selection = review_preparation._audio_selection(
            {"audio_streams": [{"ordinal": 0, "ffmpeg_map": "0:a:0"}, {"ordinal": 1, "ffmpeg_map": "0:a:1"}],
             "audio_layout_fingerprint": "this",
             "audio_audibility": {"source_state": "audible_candidates", "streams": [
                 {"audio_ordinal": 0, "final_state": "audible_signal"}, {"audio_ordinal": 1, "final_state": "digital_silence"}]}},
            {}, 2)
        self.assertEqual((selection["state"], selection["selected_ordinal"]), ("single-audible-stream", 0))

    def test_264_your_answer_on_a_track_with_no_audible_sound_is_not_used_and_the_engine_chooses(self) -> None:
        from media_manglers.core import speech_facts

        path = self.make_sources(1)[0]
        speech_facts.confirm_track(path, 3, by=speech_facts.ANSWERED_ON_BUGS)
        media = self.media(3)
        media["audio_audibility"] = {"source_state": "audible_candidates", "contract_version": review_preparation.AUDIBILITY_CONTRACT_VERSION,
                                     "streams": [{"audio_ordinal": ordinal, "ffprobe_stream_index": stream["stream_index"], "ffmpeg_map": stream["ffmpeg_map"],
                                                  "final_state": "digital_silence" if ordinal == 2 else "audible_signal"}
                                                 for ordinal, stream in enumerate(media["audio_streams"])]}
        calls: list = []
        result = review_preparation.prepare_from_request(self.payload(
            media_probe=lambda _path: media,
            audibility_inspector=lambda _source, _media, _work: media["audio_audibility"],
            voice_detector=self.detector({"status": "selected", "selected_ordinal": 1, "explanation": "Auto-detected."}, calls),
        ))
        self.assertEqual(calls, ["source-000.mp4"])
        self.assertEqual(result["prepared_sources"][0]["audio_state"], "voice-detected")
        self.assertIn(("transcribe", "decoded by the voice detection"), self.events)

    def test_264_a_stored_pick_answers_without_listening(self) -> None:
        from media_manglers.core import speech_facts, voice_track

        path = self.make_sources(1)[0]
        speech_facts.record_measure(path, {
            "rule_version": voice_track.VOICE_RULE_VERSION, "status": "selected", "selected_ordinal": 1, "confidence": 0.9,
            "decided_by": "auto", "explanation": "Auto-detected: heard it.", "tracks": [],
            "track_activity": {"2": {"silent": False, "moments": [[1.0, 2.0]]}}}, measured_by=speech_facts.BY_RAW_BIN, titles={})
        media = self.media(3)
        calls: list = []
        result = review_preparation.prepare_from_request(self.payload(
            media_probe=lambda _path: media,
            voice_detector=self.detector({"status": "selected", "selected_ordinal": 0}, calls),
        ))
        self.assertEqual(calls, [], "nothing is listened to")
        self.assertEqual(result["prepared_sources"][0]["audio_state"], "voice-detected")
        self.assertIn(("extract", 1), self.events, "the narration still has to be read")

    def test_your_saved_answer_is_used_without_asking_the_engine(self) -> None:
        self.make_sources(1)
        media = self.media(2)
        fingerprint = media["audio_layout_fingerprint"]
        calls: list = []
        result = review_preparation.prepare_from_request(self.payload(
            media_probe=lambda _path: media,
            audio_confirmations={fingerprint: {"layoutFingerprint": fingerprint, "audioOrdinal": 1}},
            voice_detector=self.detector({"status": "selected", "selected_ordinal": 0}, calls),
        ))
        self.assertEqual(result["prepared_sources"][0]["audio_state"], "confirmed-layout")
        self.assertEqual(calls, [])
        self.assertIn(("extract", 1), self.events)

    def test_the_transcript_goes_through_the_shared_line_filters(self) -> None:
        self.make_sources(1)
        media = self.media(3)
        fingerprint = media["audio_layout_fingerprint"]
        checked: list[dict] = []

        def line_checker(request: dict) -> dict:
            checked.append(request)
            return {"compared_tracks": [3], "kept_count": 1,
                    "dropped": [{"start": 4.0, "end": 6.0, "track_number": 3, "reason": "heard_on_another_track"}]}

        result = review_preparation.prepare_from_request(self.payload(
            media_probe=lambda _path: media,
            audio_confirmations={fingerprint: {"layoutFingerprint": fingerprint, "audioOrdinal": 1}},
            track_roles={"2": "narration", "3": "never"},
            line_checker=line_checker,
        ))
        self.assertEqual(result["status"], "awaiting_external_review")
        self.assertEqual(len(checked), 1)
        detection = checked[0]["detection"]
        self.assertEqual(detection["selected_ordinal"], 1)
        self.assertEqual(detection["track_roles"], {"1": "auto", "2": "narration", "3": "never"})
        self.assertTrue(checked[0]["transcript_json_path"].endswith("transcript.json"))
        package = Path(result["prepared_sources"][0]["package_path"])
        status = json.loads((package / "source-manifest.json").read_text(encoding="utf-8"))["transcription"]
        self.assertEqual([item["reason"] for item in status["lines_dropped"]], ["heard_on_another_track"])

    def test_the_narration_audio_is_read_by_the_shared_extractor(self) -> None:
        self.make_sources(1)
        payload = self.payload(ffmpeg_exe="C:\\Tools\\ffmpeg.exe")
        payload.pop("audio_extractor")
        read: list[tuple] = []

        def extract_track(ffmpeg: str, source: Path, ordinal: int, destination: Path) -> Path:
            read.append((ffmpeg, source.name, ordinal))
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text("shared extractor", encoding="utf-8")
            return destination

        with mock.patch.object(review_preparation.voice_track, "extract_track", side_effect=extract_track):
            result = review_preparation.prepare_from_request(payload)
        self.assertEqual(result["status"], "awaiting_external_review")
        self.assertEqual(read, [("C:\\Tools\\ffmpeg.exe", "source.mp4", 0)])
        self.assertEqual(self.events[0], ("transcribe", "shared extractor"))

if __name__ == "__main__":
    unittest.main()
