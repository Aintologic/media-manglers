"""The built-in player's transcript reader: the right package or none (125).

Every package here is synthetic and is written into a temporary folder. The
recording paths are invented and never exist on disk; nothing needs them to,
because the reader only ever compares their text against the manifest.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers.core.sparse_narration import (  # noqa: E402
    SpeechInterval,
    filter_sparse_decoder_segments,
    offset_segments,
)
from media_manglers.core.transcript_only import make_safe_source_id  # noqa: E402
from media_manglers_workbench.review_package import (  # noqa: E402
    RecordingTranscript,
    TranscriptLine,
    find_package_for_recording,
    line_index_at,
    load_transcript,
    match_source,
    next_line_index,
    previous_line_index,
    reason_text,
    review_copy_for,
    source_digest,
    upcoming_line,
    visible_lines,
)

SESSION_ONE = Path(r"Q:\Captured Sessions\synthetic-session-one.mkv")
SESSION_TWO = Path(r"Q:\Captured Sessions\synthetic-session-two.mkv")
MOVED_SESSION_ONE = Path(r"R:\Moved Sessions\synthetic-session-one.mkv")

FILLER_SENTENCE = (
    "Left out: a stock phrase the transcriber tends to invent over silence or engine noise, "
    'like "thanks for watching".'
)
NO_WORDS_SENTENCE = "Left out: there were no words in it."
REPEATING_SENTENCE = (
    "Left out: the transcriber was repeating itself here, which usually means it was making text up."
)
NOT_CONFIDENT_SENTENCE = "Left out: the transcriber was not confident anyone was speaking here."


def _source_id(recording: Path) -> str:
    """The id the backend gives a path: a tidied stem, then the path hash."""

    return f"{recording.stem}-{source_digest(recording)}"


def _source(recording: Path, **overrides: object) -> dict:
    entry: dict = {
        "source_id": _source_id(recording),
        "physical_source_id": _source_id(recording),
        "source_filename": recording.name,
        "source_path": str(recording),
        "duration_seconds": 600.0,
        "status": "completed",
    }
    entry.update(overrides)
    return entry


def _segment(start: object, end: object, text: object, **numbers: float) -> dict:
    return {"start": start, "end": end, "text": text, **numbers}


def _attempt(chunk: int, attempt: int, start: float, end: float, segments: list[dict]) -> dict:
    return {
        "chunk_index": chunk,
        "attempt": attempt,
        "interval": {"start_seconds": start, "end_seconds": end},
        "metrics": {},
        "segments": segments,
        "filtered_segments": [],
    }


def _filtered(chunk: int, attempt: int, reason: str, segment: dict) -> dict:
    return {"chunk_index": chunk, "attempt": attempt, "reason": reason, "segment": segment}


def _rejected(chunk: int, start: float, end: float) -> dict:
    return {
        "chunk_index": chunk,
        "reason": "repetition_persisted_after_retry",
        "interval": {"start_seconds": start, "end_seconds": end},
        "first_metrics": {},
        "retry_metrics": {},
    }


def _audit(
    *,
    mode: str = "Sparse",
    attempts: list[dict] | None = None,
    filtered: list[dict] | None = None,
    rescued: list[dict] | None = None,
    rejected: list[dict] | None = None,
    rescued_recorded: bool = True,
) -> dict:
    """A ``.transcript.raw.json`` payload in the shape the transcriber writes."""

    payload: dict = {
        "schema_version": 1,
        "language": "en",
        "mode": mode,
        "raw_attempts": attempts or [],
        "filtered_segments": filtered or [],
        "rejected_chunks": rejected or [],
    }
    if rescued_recorded:
        payload["rescued_segments"] = rescued or []
    return payload


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _numbered(segments: list[dict]) -> list[dict]:
    return [{"id": index, **segment} for index, segment in enumerate(segments)]


def _write_package(
    folder: Path,
    sources: list[dict],
    *,
    kept: dict[str, list[dict]] | None = None,
    originals: dict[str, list[dict]] | None = None,
    audits: dict[str, dict] | None = None,
    quality: dict[str, dict] | None = None,
    voice: dict[str, dict] | None = None,
    narration_sources: list[dict] | None = None,
) -> Path:
    """Write a synthetic package under ``folder``; mappings are keyed by file id."""

    root = folder / "codex-evidence-package"
    _write_json(root / "manifest.json", {"schema_version": 1, "sources": sources})
    sources_dir = root / "transcript" / "sources"
    for file_id, segments in (kept or {}).items():
        _write_json(
            sources_dir / f"{file_id}.transcript.json",
            {"language": "en", "correction_count": 0, "segments": _numbered(segments)},
        )
    for file_id, segments in (originals or {}).items():
        _write_json(
            root / "transcript" / "raw" / "sources" / f"{file_id}.transcript.json",
            {"language": "en", "segments": _numbered(segments)},
        )
    for file_id, payload in (audits or {}).items():
        _write_json(sources_dir / f"{file_id}.transcript.raw.json", payload)
    for file_id, payload in (quality or {}).items():
        _write_json(sources_dir / f"{file_id}.transcript.quality.json", payload)
    for file_id, detection in (voice or {}).items():
        _write_json(
            sources_dir / f"{file_id}.voice.json",
            {
                "schema": "mm-voice-detection-v1",
                "source_size": 1024,
                "source_modified_utc": "2026-09-20T10:00:00.0000000Z",
                "detection": detection,
            },
        )
    if narration_sources is not None:
        _write_json(root / "NARRATION_EVIDENCE.json", {"schema_version": 1, "sources": narration_sources})
    return root


def _line(start: float, end: float, kind: str = "kept", text: str = "synthetic line") -> TranscriptLine:
    return TranscriptLine(start=start, end=end, text=text, kind=kind)


class TempFolderTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()


class ModuleIsPureTests(unittest.TestCase):
    def test_importing_the_reader_loads_no_qt_and_no_numpy(self) -> None:
        # A fresh interpreter, because another test file in the same run may
        # already have imported Qt.
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "import media_manglers_workbench.review_package; "
            "print(sorted(name for name in ('PySide6', 'numpy', 'torch', 'whisper') if name in sys.modules))"
        )
        completed = subprocess.run(
            [sys.executable, "-c", code, str(REPO_ROOT / "src")],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "[]")

    def test_the_whole_package_loader_is_never_used(self) -> None:
        # load_evidence_package reads every file of a package. The player asks for one recording's
        # lines, often from a slow disk, so the reader must never reach for it.
        source = (REPO_ROOT / "src" / "media_manglers_workbench" / "review_package.py").read_text(
            encoding="utf-8"
        )
        named: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Name):
                named.add(node.id)
            elif isinstance(node, ast.Attribute):
                named.add(node.attr)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                named.update(alias.name.rsplit(".", 1)[-1] for alias in node.names)
        self.assertIn("resolve_evidence_package_root", named, "the check must be able to see imports")
        self.assertNotIn("load_evidence_package", named)


class SourceDigestTests(unittest.TestCase):
    def test_digest_is_the_ending_the_backend_puts_on_a_source_id(self) -> None:
        backend_id = make_safe_source_id(str(SESSION_ONE), SESSION_ONE.name)
        self.assertTrue(backend_id.endswith("-" + source_digest(SESSION_ONE)), backend_id)
        self.assertEqual(len(source_digest(SESSION_ONE)), 10)

    def test_case_and_slashes_do_not_change_the_digest(self) -> None:
        self.assertEqual(
            source_digest("q:/captured sessions/SYNTHETIC-SESSION-ONE.MKV"),
            source_digest(SESSION_ONE),
        )
        self.assertNotEqual(source_digest(SESSION_ONE), source_digest(SESSION_TWO))


class MatchSourceTests(unittest.TestCase):
    def test_exact_path_matches_whatever_the_case_or_slashes(self) -> None:
        manifest = {
            "sources": [
                _source(SESSION_TWO),
                _source(SESSION_ONE, source_id="no-hash-here", physical_source_id="no-hash-here",
                        source_path="q:/captured sessions/SYNTHETIC-SESSION-ONE.mkv"),
            ]
        }
        matched = match_source(manifest, SESSION_ONE)
        self.assertIsNotNone(matched)
        self.assertEqual(matched["source_id"], "no-hash-here")

    def test_path_hash_on_the_source_id_matches_without_a_stored_path(self) -> None:
        entry = _source(SESSION_ONE, source_path="", source_filename="renamed-in-the-manifest.mkv")
        matched = match_source({"sources": [_source(SESSION_TWO), entry]}, SESSION_ONE)
        self.assertIsNotNone(matched)
        self.assertEqual(matched["source_id"], _source_id(SESSION_ONE))

    def test_path_hash_on_the_physical_source_id_matches(self) -> None:
        entry = _source(SESSION_ONE, source_id="", source_path="", source_filename="")
        matched = match_source({"sources": [entry]}, SESSION_ONE)
        self.assertIsNotNone(matched)
        self.assertEqual(matched["physical_source_id"], _source_id(SESSION_ONE))

    def test_a_moved_recording_matches_on_a_unique_name_and_length(self) -> None:
        manifest = {"sources": [_source(SESSION_ONE, duration_seconds=600.0), _source(SESSION_TWO)]}
        for known in (600.0, 601.4, 598.6, None, 0.0):
            with self.subTest(duration_seconds=known):
                matched = match_source(manifest, MOVED_SESSION_ONE, duration_seconds=known)
                self.assertIsNotNone(matched)
                self.assertEqual(matched["source_id"], _source_id(SESSION_ONE))

    def test_a_manifest_that_does_not_know_the_length_still_matches_on_the_name(self) -> None:
        manifest = {"sources": [_source(SESSION_ONE, duration_seconds=0.0)]}
        self.assertIsNotNone(match_source(manifest, MOVED_SESSION_ONE, duration_seconds=432.0))

    def test_a_name_shared_by_two_sources_is_ambiguous(self) -> None:
        other_folder = Path(r"Q:\Older Sessions") / SESSION_ONE.name
        manifest = {"sources": [_source(SESSION_ONE), _source(other_folder)]}
        self.assertIsNone(match_source(manifest, MOVED_SESSION_ONE, duration_seconds=600.0))

    def test_a_different_length_is_refused(self) -> None:
        manifest = {"sources": [_source(SESSION_ONE, duration_seconds=600.0)]}
        self.assertIsNone(match_source(manifest, MOVED_SESSION_ONE, duration_seconds=602.0))
        self.assertIsNone(match_source(manifest, MOVED_SESSION_ONE, duration_seconds=3600.0))

    def test_a_recording_replaced_at_the_same_path_is_refused(self) -> None:
        # Same path, so the path rule finds the entry - but the file there now is 40 minutes longer
        # than the one the package was made from. It was recorded over or swapped.
        manifest = {"sources": [_source(SESSION_ONE, duration_seconds=600.0)]}
        for known in (3000.0, 601.6, 598.4):
            with self.subTest(duration_seconds=known):
                self.assertIsNone(match_source(manifest, SESSION_ONE, duration_seconds=known))
        for known in (600.0, 601.4, 598.6, None, 0.0):
            with self.subTest(duration_seconds=known):
                matched = match_source(manifest, SESSION_ONE, duration_seconds=known)
                self.assertIsNotNone(matched)
                self.assertEqual(matched["source_path"], str(SESSION_ONE))

    def test_the_path_hash_does_not_outvote_a_different_length(self) -> None:
        entry = _source(SESSION_ONE, source_path="", source_filename="renamed-in-the-manifest.mkv",
                        duration_seconds=600.0)
        manifest = {"sources": [_source(SESSION_TWO), entry]}
        self.assertIsNone(match_source(manifest, SESSION_ONE, duration_seconds=3000.0))
        self.assertIsNotNone(match_source(manifest, SESSION_ONE, duration_seconds=600.5))

    def test_a_length_nobody_wrote_down_refuses_nothing_on_the_path_or_the_hash(self) -> None:
        for stored in (0.0, None, "", "not a number", True, -5):
            with self.subTest(duration_seconds=stored):
                by_path = {"sources": [_source(SESSION_ONE, duration_seconds=stored)]}
                by_hash = {"sources": [_source(SESSION_ONE, source_path="", source_filename="",
                                               duration_seconds=stored)]}
                self.assertIsNotNone(match_source(by_path, SESSION_ONE, duration_seconds=3000.0))
                self.assertIsNotNone(match_source(by_hash, SESSION_ONE, duration_seconds=3000.0))

    def test_a_shared_output_folder_holding_another_recording_shows_nothing(self) -> None:
        # A later run replaced the package in the same folder with a different recording.
        manifest = {"sources": [_source(SESSION_TWO, duration_seconds=600.0)]}
        self.assertIsNone(match_source(manifest, SESSION_ONE, duration_seconds=600.0))

    def test_the_exact_path_is_tried_before_the_file_name(self) -> None:
        # Two sources share the name, so the name alone is ambiguous - but one of them IS this path.
        other_folder = Path(r"Q:\Older Sessions") / SESSION_ONE.name
        manifest = {"sources": [_source(other_folder), _source(SESSION_ONE)]}
        matched = match_source(manifest, SESSION_ONE)
        self.assertIsNotNone(matched)
        self.assertEqual(matched["source_path"], str(SESSION_ONE))

    def test_the_result_is_a_copy(self) -> None:
        manifest = {"sources": [_source(SESSION_ONE)]}
        matched = match_source(manifest, SESSION_ONE)
        matched["source_id"] = "changed"
        self.assertEqual(manifest["sources"][0]["source_id"], _source_id(SESSION_ONE))

    def test_malformed_manifests_never_raise(self) -> None:
        for manifest in (
            {},
            {"sources": None},
            {"sources": "synthetic"},
            {"sources": {"source_path": str(SESSION_ONE)}},
            {"sources": [None, 7, "text", [], {"source_path": 7, "source_id": None, "source_filename": []}]},
            [],
            None,
        ):
            with self.subTest(manifest=manifest):
                self.assertIsNone(match_source(manifest, SESSION_ONE, duration_seconds=600.0))

    def test_a_length_that_cannot_be_read_counts_as_not_known(self) -> None:
        for stored in ("not a number", None, True, [], -5):
            with self.subTest(duration_seconds=stored):
                manifest = {"sources": [{"source_filename": SESSION_ONE.name, "duration_seconds": stored}]}
                self.assertIsNotNone(match_source(manifest, SESSION_ONE, duration_seconds=600.0))


class LoadTranscriptTests(TempFolderTestCase):
    """One package that exercises every rule, then one test per rule."""

    def _standard_package(self, *, rescued_recorded: bool = True) -> Path:
        file_id = _source_id(SESSION_ONE)
        kept = [
            _segment(12.0, 15.5, "The lap counter froze on the second screen."),
            _segment(40.0, 43.0, "Open the Crew Chief settings."),
            _segment(75.2, 76.0, "Car left, car left."),
            _segment(130.0, 131.0, "Tyre temps."),
        ]
        originals = [
            _segment(12.0, 15.5, "The lap counter froze on the second screen."),
            _segment(40.0, 43.0, "Open the crew chef settings."),
            _segment(75.2, 76.0, "Car left, car left."),
            _segment(130.0, 131.0, "Tyre temps."),
        ]
        filler = _segment(20.0, 22.0, " Thanks for watching!", no_speech_prob=0.11, avg_logprob=-0.31,
                          compression_ratio=1.05)
        first_try_drop = _segment(50.0, 52.0, " la la la la la la la la", no_speech_prob=0.3, avg_logprob=-0.4,
                                  compression_ratio=3.1)
        second_try_drop = _segment(55.0, 56.0, " ...", no_speech_prob=0.7, avg_logprob=-1.2,
                                   compression_ratio=0.4)
        mumble = _segment(90.0, 91.0, " hm", no_speech_prob=0.62, avg_logprob=-0.95, compression_ratio=0.5)
        hidden_by_the_span = _segment(205.0, 206.0, " you", no_speech_prob=0.5, avg_logprob=-0.2,
                                      compression_ratio=0.6)
        unknown = _segment(300.0, 301.0, " Something new.", no_speech_prob=0.2)
        attempts = [
            _attempt(1, 1, 11.5, 22.5, [
                _segment(12.0, 15.5, " The lap counter froze on the second screen.", no_speech_prob=0.02,
                         avg_logprob=-0.21, compression_ratio=1.3),
                filler,
            ]),
            # Chunk 2 repeated itself, so it was transcribed twice; the second try is the one used.
            _attempt(2, 1, 39.5, 56.5, [
                _segment(40.0, 43.0, " Open the crew chef settings.", no_speech_prob=0.9, avg_logprob=-2.0,
                         compression_ratio=2.0),
                first_try_drop,
            ]),
            _attempt(2, 2, 39.5, 56.5, [
                _segment(40.0, 43.0, " Open the crew chef settings.", no_speech_prob=0.04, avg_logprob=-0.25,
                         compression_ratio=1.2),
                second_try_drop,
            ]),
            _attempt(3, 1, 74.8, 91.4, [
                _segment(75.2, 76.0, " Car left, car left.", no_speech_prob=0.05, avg_logprob=-0.3,
                         compression_ratio=1.0),
                mumble,
            ]),
            _attempt(4, 1, 200.0, 230.0, [_segment(201.0, 204.0, " first try wording"), hidden_by_the_span]),
            _attempt(4, 2, 200.0, 230.0, [
                _segment(201.0, 204.0, " again and again"),
                _segment(204.0, 207.0, " again and again"),
            ]),
            _attempt(5, 1, 129.5, 131.5, [
                _segment(130.0, 131.0, " Tyre temps.", no_speech_prob=0.35, avg_logprob=-0.8,
                         compression_ratio=0.7),
            ]),
            _attempt(6, 1, 299.5, 301.5, [unknown]),
        ]
        filtered = [
            _filtered(1, 1, "known_filler_phrase", filler),
            _filtered(2, 1, "compression_ratio_threshold", first_try_drop),
            _filtered(2, 2, "known_filler_phrase", second_try_drop),
            _filtered(3, 1, "combined_low_speech_information", mumble),
            _filtered(4, 2, "known_filler_phrase", hidden_by_the_span),
            _filtered(6, 1, "brand_new_reason", unknown),
        ]
        rescued = [
            {
                "chunk_index": 5,
                "attempt": 1,
                "reason": "low_information_kept_near_narration",
                # The audit holds the very segment that was delivered, so the start is the same. The id
                # differs from the delivered line's on purpose: ids are renumbered and never matched on.
                "segment": {"id": 99, **_segment(130.0, 131.0, " Tyre temps.", no_speech_prob=0.35,
                                                 avg_logprob=-0.8, compression_ratio=0.7),
                            "low_information_kept_near_narration": True},
            }
        ]
        return _write_package(
            self.root,
            # The glossary changed one line in the write that made these files, and the manifest says so.
            [_source(SESSION_TWO), _source(SESSION_ONE, selected_audio_stream_index=1,
                                           transcript_correction_count=1,
                                           transcript_quality={"game_spotter_contamination_suspected": True})],
            kept={file_id: kept, _source_id(SESSION_TWO): [_segment(1.0, 2.0, "A line from the other recording.")]},
            originals={file_id: originals},
            audits={file_id: _audit(attempts=attempts, filtered=filtered, rescued=rescued,
                                    rejected=[_rejected(4, 200.0, 230.0)],
                                    rescued_recorded=rescued_recorded)},
            voice={file_id: {"status": "selected", "selected_ordinal": 1, "confidence": 0.93, "tracks": [],
                             "explanation": "Track 2 carries your narration (42 confident spoken words, "
                                            "quiet between phrases)."}},
        )

    def _load(self, root: Path) -> RecordingTranscript:
        result = load_transcript(root, SESSION_ONE, duration_seconds=600.0)
        self.assertIsNotNone(result)
        return result

    def _line_at(self, result: RecordingTranscript, start: float) -> TranscriptLine:
        matches = [line for line in result.lines if line.start == start]
        self.assertEqual(len(matches), 1, f"expected exactly one line at {start}")
        return matches[0]

    def test_kept_and_left_out_lines_are_merged_in_time_order(self) -> None:
        result = self._load(self._standard_package())
        self.assertEqual(
            [(line.start, line.kind) for line in result.lines],
            [
                (12.0, "kept"),
                (20.0, "left_out"),
                (40.0, "kept"),
                (55.0, "left_out"),
                (75.2, "kept"),
                (90.0, "left_out"),
                (130.0, "kept"),
                (200.0, "rejected_span"),
                (300.0, "left_out"),
            ],
        )
        self.assertEqual(result.mode, "Sparse")
        self.assertTrue(result.filtering_ran)
        self.assertTrue(result.audit_available)
        self.assertEqual(result.package_root, self.root / "codex-evidence-package")
        self.assertEqual(result.source_id, _source_id(SESSION_ONE))
        self.assertEqual(result.physical_source_id, _source_id(SESSION_ONE))
        self.assertTrue(all(line.text != "A line from the other recording." for line in result.lines))

    def test_a_kept_and_a_left_out_line_at_the_same_start_put_the_kept_one_first(self) -> None:
        file_id = _source_id(SESSION_ONE)
        dropped = _segment(8.0, 9.0, " Thanks for watching!")
        root = _write_package(
            self.root,
            [_source(SESSION_ONE)],
            kept={file_id: [_segment(8.0, 9.5, "The fuel number is wrong.")]},
            audits={file_id: _audit(attempts=[_attempt(1, 1, 7.5, 10.0, [dropped])],
                                    filtered=[_filtered(1, 1, "known_filler_phrase", dropped)])},
        )
        self.assertEqual([line.kind for line in self._load(root).lines], ["kept", "left_out"])

    def test_each_left_out_line_says_why_in_plain_words(self) -> None:
        result = self._load(self._standard_package())
        filler = self._line_at(result, 20.0)
        self.assertEqual((filler.reason_code, filler.reason_text), ("known_filler_phrase", FILLER_SENTENCE))
        self.assertEqual(filler.text, "Thanks for watching!")
        no_words = self._line_at(result, 55.0)
        self.assertEqual((no_words.reason_code, no_words.reason_text), ("known_filler_phrase", NO_WORDS_SENTENCE))
        mumble = self._line_at(result, 90.0)
        self.assertEqual(
            (mumble.reason_code, mumble.reason_text),
            ("combined_low_speech_information", NOT_CONFIDENT_SENTENCE),
        )
        unknown = self._line_at(result, 300.0)
        self.assertEqual(unknown.reason_code, "brand_new_reason")
        self.assertEqual(unknown.reason_text, 'Left out — reason recorded as "brand_new_reason".')
        for line in result.lines:
            if line.kind == "kept":
                self.assertEqual((line.reason_code, line.reason_text), ("", ""))

    def test_a_chunk_tried_twice_shows_only_the_drops_of_the_try_that_was_used(self) -> None:
        result = self._load(self._standard_package())
        self.assertEqual([line for line in result.lines if line.start == 50.0], [])
        self.assertEqual(self._line_at(result, 55.0).kind, "left_out")

    def test_a_rejected_stretch_becomes_one_span_carrying_the_discarded_text(self) -> None:
        result = self._load(self._standard_package())
        span = self._line_at(result, 200.0)
        self.assertEqual((span.kind, span.end), ("rejected_span", 230.0))
        self.assertEqual(span.reason_code, "repetition_persisted_after_retry")
        # The text of the LAST try, joined; the first try's wording is gone.
        self.assertEqual(span.text, "again and again again and again")
        self.assertEqual(
            span.reason_text,
            "This whole stretch (0:03:20–0:03:50) was thrown out: the transcriber kept repeating itself "
            "even on a second try.",
        )
        self.assertEqual([line for line in result.lines if line.start == 205.0], [],
                         "a drop inside a rejected stretch is covered by the span")

    def test_a_rescued_line_is_matched_by_its_start_time(self) -> None:
        result = self._load(self._standard_package())
        self.assertTrue(result.rescued_known)
        self.assertEqual([line.start for line in result.lines if line.rescued], [130.0])
        self.assertEqual(self._line_at(result, 130.0).kind, "kept")

    def test_a_line_right_next_to_a_rescued_one_is_not_marked_rescued(self) -> None:
        file_id = _source_id(SESSION_ONE)
        # The transcriber stamps lines as little as 0.02 s apart. Only the aside was rescued.
        narration = _segment(10.0, 10.02, " The relative is blank on the left screen.", no_speech_prob=0.03,
                             avg_logprob=-0.2, compression_ratio=1.3)
        aside = _segment(10.02, 10.6, " Bias.", no_speech_prob=0.4, avg_logprob=-0.9, compression_ratio=0.6)
        later_aside = _segment(30.04, 30.5, " Again.", no_speech_prob=0.45, avg_logprob=-0.85,
                               compression_ratio=0.55)
        root = _write_package(
            self.root,
            [_source(SESSION_ONE)],
            kept={file_id: [
                _segment(10.0, 10.02, "The relative is blank on the left screen."),
                _segment(10.02, 10.6, "Bias."),
                # The audit says nothing at all about this one; its neighbour 0.04 s later was rescued.
                _segment(30.0, 30.04, "Fuel reads wrong."),
                _segment(30.04, 30.5, "Again."),
            ]},
            audits={file_id: _audit(
                attempts=[_attempt(1, 1, 9.5, 11.0, [narration, aside]),
                          _attempt(2, 1, 29.5, 31.0, [later_aside])],
                rescued=[
                    {"chunk_index": 1, "attempt": 1, "reason": "low_information_kept_near_narration",
                     "segment": {**aside, "low_information_kept_near_narration": True}},
                    {"chunk_index": 2, "attempt": 1, "reason": "low_information_kept_near_narration",
                     "segment": {**later_aside, "low_information_kept_near_narration": True}},
                ],
            )},
        )
        result = self._load(root)
        self.assertEqual(
            [(line.start, line.rescued) for line in result.lines],
            [(10.0, False), (10.02, True), (30.0, False), (30.04, True)],
        )
        self.assertEqual(
            [line.numbers for line in result.lines],
            [
                (("no_speech_prob", 0.03), ("avg_logprob", -0.2), ("compression_ratio", 1.3)),
                (("no_speech_prob", 0.4), ("avg_logprob", -0.9), ("compression_ratio", 0.6)),
                (),
                (("no_speech_prob", 0.45), ("avg_logprob", -0.85), ("compression_ratio", 0.55)),
            ],
            "a line borrows nothing from the line beside it",
        )

    def test_two_kept_lines_sharing_one_start_are_told_apart_by_their_words(self) -> None:
        file_id = _source_id(SESSION_ONE)
        # The transcriber now and then writes a line with no length at the very start of the next one.
        aside = _segment(10.0, 10.0, " Bias.", no_speech_prob=0.4, avg_logprob=-0.9, compression_ratio=0.6)
        narration = _segment(10.0, 12.0, " The relative is blank on the left screen.", no_speech_prob=0.03,
                             avg_logprob=-0.2, compression_ratio=1.3)
        root = _write_package(
            self.root,
            [_source(SESSION_ONE)],
            kept={file_id: [_segment(10.0, 10.0, "Bias."),
                            _segment(10.0, 12.0, "The relative is blank on the left screen.")]},
            audits={file_id: _audit(
                attempts=[_attempt(1, 1, 9.5, 12.5, [aside, narration])],
                rescued=[{"chunk_index": 1, "attempt": 1, "reason": "low_information_kept_near_narration",
                          "segment": {**aside, "low_information_kept_near_narration": True}}],
            )},
        )
        by_text = {line.text: line for line in self._load(root).lines}
        self.assertTrue(by_text["Bias."].rescued)
        self.assertEqual(by_text["Bias."].numbers,
                         (("no_speech_prob", 0.4), ("avg_logprob", -0.9), ("compression_ratio", 0.6)))
        narration_line = by_text["The relative is blank on the left screen."]
        self.assertFalse(narration_line.rescued)
        self.assertEqual(narration_line.numbers,
                         (("no_speech_prob", 0.03), ("avg_logprob", -0.2), ("compression_ratio", 1.3)))

    def test_a_shared_start_with_words_that_match_nothing_shows_nothing(self) -> None:
        file_id = _source_id(SESSION_ONE)
        aside = _segment(10.0, 10.0, " Bias.", no_speech_prob=0.4, avg_logprob=-0.9, compression_ratio=0.6)
        narration = _segment(10.0, 12.0, " The crew chef is quiet.", no_speech_prob=0.03, avg_logprob=-0.2,
                             compression_ratio=1.3)
        root = _write_package(
            self.root,
            [_source(SESSION_ONE, transcript_correction_count=1)],
            # The glossary changed the second line, and with two lines on one start nothing says which
            # raw wording is whose - so the audit cannot be asked about it either.
            kept={file_id: [_segment(10.0, 10.0, "Bias."), _segment(10.0, 12.0, "The Crew Chief is quiet.")]},
            originals={file_id: [_segment(10.0, 10.0, "Bias."), _segment(10.0, 12.0, "The crew chef is quiet.")]},
            audits={file_id: _audit(
                attempts=[_attempt(1, 1, 9.5, 12.5, [aside, narration])],
                rescued=[{"chunk_index": 1, "attempt": 1, "reason": "low_information_kept_near_narration",
                          "segment": {**aside, "low_information_kept_near_narration": True}}],
            )},
        )
        by_text = {line.text: line for line in self._load(root).lines}
        self.assertTrue(by_text["Bias."].rescued)
        corrected = by_text["The Crew Chief is quiet."]
        self.assertEqual((corrected.rescued, corrected.numbers, corrected.original_text), (False, (), ""))
        self.assertEqual(by_text["Bias."].original_text, "")

    def test_a_corrected_line_is_found_in_the_audit_by_its_wording_before_the_glossary(self) -> None:
        file_id = _source_id(SESSION_ONE)
        # The audit lists two segments on one start; only one of them reached the package.
        stray = _segment(40.0, 40.0, " Crew.", no_speech_prob=0.5, avg_logprob=-1.1, compression_ratio=0.5)
        spoken = _segment(40.0, 43.0, " Open the crew chef settings.", no_speech_prob=0.04, avg_logprob=-0.25,
                          compression_ratio=1.2)
        for corrections, original_text, numbers in (
            (1, "Open the crew chef settings.",
             (("no_speech_prob", 0.04), ("avg_logprob", -0.25), ("compression_ratio", 1.2))),
            # Without the wording before the glossary there is no telling the two apart.
            (0, "", ()),
        ):
            with self.subTest(transcript_correction_count=corrections):
                root = _write_package(
                    self.root / f"corrections-{corrections}",
                    [_source(SESSION_ONE, transcript_correction_count=corrections)],
                    kept={file_id: [_segment(40.0, 43.0, "Open the Crew Chief settings.")]},
                    originals={file_id: [_segment(40.0, 43.0, "Open the crew chef settings.")]},
                    audits={file_id: _audit(attempts=[_attempt(1, 1, 39.5, 43.5, [stray, spoken])])},
                )
                line = self._load(root).lines[0]
                self.assertEqual((line.original_text, line.numbers), (original_text, numbers))

    def test_a_dropped_segment_starting_where_a_kept_line_does_lends_it_no_numbers(self) -> None:
        file_id = _source_id(SESSION_ONE)
        dropped = _segment(8.0, 8.0, " ...", no_speech_prob=0.9, avg_logprob=-1.5, compression_ratio=0.3)
        spoken = _segment(8.0, 9.5, " The fuel number is wrong on the crew chef.", no_speech_prob=0.02,
                          avg_logprob=-0.2, compression_ratio=1.1)
        root = _write_package(
            self.root,
            # A package written a second time: the glossary's change is in the text, the manifest counts
            # nothing new, and the wording before it is gone. The start still names the one kept segment.
            [_source(SESSION_ONE, transcript_correction_count=0)],
            kept={file_id: [_segment(8.0, 9.5, "The fuel number is wrong on the Crew Chief.")]},
            audits={file_id: _audit(attempts=[_attempt(1, 1, 7.5, 10.0, [dropped, spoken])],
                                    filtered=[_filtered(1, 1, "known_filler_phrase", dropped)])},
        )
        kept_line, left_out = self._load(root).lines
        self.assertEqual((kept_line.kind, left_out.kind), ("kept", "left_out"))
        self.assertEqual(kept_line.numbers,
                         (("no_speech_prob", 0.02), ("avg_logprob", -0.2), ("compression_ratio", 1.1)))
        self.assertEqual(left_out.numbers,
                         (("no_speech_prob", 0.9), ("avg_logprob", -1.5), ("compression_ratio", 0.3)))

    def test_an_audit_written_before_rescues_were_recorded_does_not_say(self) -> None:
        result = self._load(self._standard_package(rescued_recorded=False))
        self.assertFalse(result.rescued_known)
        self.assertFalse(any(line.rescued for line in result.lines))
        self.assertTrue(result.audit_available)

    def test_the_transcribers_numbers_are_attached(self) -> None:
        result = self._load(self._standard_package())
        self.assertEqual(
            self._line_at(result, 20.0).numbers,
            (("no_speech_prob", 0.11), ("avg_logprob", -0.31), ("compression_ratio", 1.05)),
        )
        self.assertEqual(
            self._line_at(result, 12.0).numbers,
            (("no_speech_prob", 0.02), ("avg_logprob", -0.21), ("compression_ratio", 1.3)),
        )
        # Chunk 2 was tried twice: the kept line carries the numbers of the try that was used.
        self.assertEqual(
            self._line_at(result, 40.0).numbers,
            (("no_speech_prob", 0.04), ("avg_logprob", -0.25), ("compression_ratio", 1.2)),
        )
        # Only what is known is listed, and a rejected stretch has no numbers of its own.
        self.assertEqual(self._line_at(result, 300.0).numbers, (("no_speech_prob", 0.2),))
        self.assertEqual(self._line_at(result, 200.0).numbers, ())

    def test_the_original_wording_is_kept_only_when_it_differs(self) -> None:
        result = self._load(self._standard_package())
        corrected = self._line_at(result, 40.0)
        self.assertEqual(corrected.text, "Open the Crew Chief settings.")
        self.assertEqual(corrected.original_text, "Open the crew chef settings.")
        self.assertEqual(self._line_at(result, 12.0).original_text, "")

    def test_the_raw_copy_is_believed_only_when_the_manifest_counts_a_glossary_change(self) -> None:
        # The backend copies the transcript over the raw copy on EVERY package write. Written again over
        # the same folder, that transcript is already the corrected one, so a raw copy that differs
        # proves nothing unless the manifest says the glossary changed something in this very write.
        file_id = _source_id(SESSION_ONE)
        cases: list[tuple[str, dict, str]] = [
            ("absent", {}, ""),
            ("zero", {"transcript_correction_count": 0}, ""),
            ("null", {"transcript_correction_count": None}, ""),
            ("true", {"transcript_correction_count": True}, ""),
            ("words", {"transcript_correction_count": "several"}, ""),
            ("one", {"transcript_correction_count": 1}, "Open the crew chef settings."),
            ("text", {"transcript_correction_count": "2"}, "Open the crew chef settings."),
        ]
        for name, overrides, expected in cases:
            with self.subTest(transcript_correction_count=name):
                root = _write_package(
                    self.root / name,
                    [_source(SESSION_ONE, **overrides)],
                    kept={file_id: [_segment(40.0, 43.0, "Open the Crew Chief settings.")]},
                    originals={file_id: [_segment(40.0, 43.0, " Open the crew chef settings.")]},
                )
                self.assertEqual(self._load(root).lines[0].original_text, expected)

    def test_the_wording_of_the_line_beside_it_is_never_shown_as_a_lines_own(self) -> None:
        file_id = _source_id(SESSION_ONE)
        root = _write_package(
            self.root,
            [_source(SESSION_ONE, transcript_correction_count=1)],
            kept={file_id: [_segment(10.0, 10.02, "Fuel reads wrong."), _segment(10.02, 12.0, "Open the Crew Chief.")]},
            # The raw copy has nothing for the first line; the second line's wording is 0.02 s away.
            originals={file_id: [_segment(10.02, 12.0, "Open the crew chef.")]},
        )
        self.assertEqual([line.original_text for line in self._load(root).lines], ["", "Open the crew chef."])

    def test_a_recording_replaced_at_the_same_path_shows_nothing(self) -> None:
        root = self._standard_package()
        self.assertIsNotNone(load_transcript(root, SESSION_ONE, duration_seconds=600.9))
        self.assertIsNone(load_transcript(root, SESSION_ONE, duration_seconds=3000.0))

    def test_mostly_spotter_call_outs_get_the_badge(self) -> None:
        result = self._load(self._standard_package())
        self.assertEqual([line.start for line in result.lines if line.spotter], [75.2])

    def test_a_line_that_only_mentions_a_call_out_is_not_a_spotter_line(self) -> None:
        file_id = _source_id(SESSION_ONE)
        root = _write_package(
            self.root,
            [_source(SESSION_ONE)],
            kept={file_id: [
                _segment(5.0, 9.0, "I heard car left but there was nobody beside me at all."),
                _segment(10.0, 11.0, "Clear right."),
            ]},
        )
        self.assertEqual([line.spotter for line in self._load(root).lines], [False, True])

    def test_the_voice_track_explanation_and_flags_are_read(self) -> None:
        result = self._load(self._standard_package())
        self.assertEqual(
            result.track_explanation,
            "Track 2 carries your narration (42 confident spoken words, quiet between phrases).",
        )
        self.assertEqual(result.transcribed_track, 2)
        self.assertTrue(result.contamination_suspected)

    def test_a_voice_result_without_a_selection_reason_is_fine(self) -> None:
        file_id = _source_id(SESSION_ONE)
        # The "uncertain" shape of the detector: no selection_reason and nothing selected.
        root = _write_package(
            self.root,
            [_source(SESSION_ONE)],
            kept={file_id: [_segment(1.0, 2.0, "The relative is blank.")]},
            voice={file_id: {"status": "uncertain", "selected_ordinal": None, "suggested_ordinal": 2,
                             "confidence": 0.5, "tracks": [], "competing_ordinals": [3],
                             "explanation": "Track 3 and Track 4 carry different speech; the microphone "
                                            "cannot be chosen safely."}},
        )
        result = self._load(root)
        self.assertEqual(
            result.track_explanation,
            "Track 3 and Track 4 carry different speech; the microphone cannot be chosen safely.",
        )
        self.assertIsNone(result.transcribed_track)
        self.assertFalse(result.contamination_suspected)

    def test_the_detected_track_is_used_when_the_manifest_does_not_name_one(self) -> None:
        file_id = _source_id(SESSION_ONE)
        root = _write_package(
            self.root,
            [_source(SESSION_ONE)],
            kept={file_id: [_segment(1.0, 2.0, "The relative is blank.")]},
            voice={file_id: {"status": "selected", "selected_ordinal": 3, "explanation": "Track 4 carries "
                                                                                           "your narration."}},
        )
        result = self._load(root)
        self.assertEqual(result.transcribed_track, 4)
        self.assertEqual(result.track_explanation, "Track 4 carries your narration.")

    def test_a_saved_explanation_about_another_track_is_not_shown(self) -> None:
        file_id = _source_id(SESSION_ONE)
        # Detection once chose Track 2; the operator later picked Track 3 by hand and re-ran.
        root = _write_package(
            self.root,
            [_source(SESSION_ONE, selected_audio_stream_index=2)],
            kept={file_id: [_segment(1.0, 2.0, "The relative is blank.")]},
            voice={file_id: {"status": "selected", "selected_ordinal": 1,
                             "explanation": "Track 2 carries your narration."}},
        )
        result = self._load(root)
        self.assertEqual(result.transcribed_track, 3)
        self.assertEqual(result.track_explanation, "")

    def test_a_question_the_operator_has_answered_is_not_shown_beside_the_answer(self) -> None:
        file_id = _source_id(SESSION_ONE)
        question = {
            "status": "uncertain",
            "uncertain_reason": "speech_on_busy_tracks",
            "selected_ordinal": None,
            "suggested_ordinal": None,
            "competing_ordinals": [1, 0],
            "explanation": "Track 2 (394 clear words) and Track 1 (266) carry speech, but each of them is also "
            "busy with other sound (a full mix, game audio or music), so the app cannot tell which one is your "
            "microphone. Choose the track with your voice.",
        }
        # 142: the app asked, the operator chose Track 2, and it was
        # transcribed. Detection is not run again for a chosen track, so the
        # saved question is still there; showing it now would be out of date.
        answered = _write_package(
            self.root / "answered",
            [_source(SESSION_ONE, selected_audio_stream_index=1, status="completed")],
            kept={file_id: [_segment(1.0, 2.0, "The relative is blank.")]},
            voice={file_id: question},
        )
        result = self._load(answered)
        self.assertEqual(result.transcribed_track, 2)
        self.assertEqual(result.track_explanation, "")
        # Not answered yet: the question is what there is to read. The package
        # writer leaves an empty transcript for a recording it could not use.
        waiting = _write_package(
            self.root / "waiting",
            [_source(SESSION_ONE, selected_audio_stream_index=1, status="failed")],
            kept={file_id: []},
            voice={file_id: question},
        )
        waiting_result = self._load(waiting)
        self.assertEqual(waiting_result.track_explanation, question["explanation"])
        # Nothing was transcribed, so no track is named as the transcript's.
        self.assertIsNone(waiting_result.transcribed_track)
        # A transcript blocked as invented was still made from a track, and
        # that is the track worth hearing to see why.
        blocked = _write_package(
            self.root / "blocked",
            [_source(SESSION_ONE, selected_audio_stream_index=1, status="quality_blocked")],
            kept={file_id: [_segment(1.0, 2.0, "Thank you for watching!")]},
            voice={file_id: question},
        )
        self.assertEqual(self._load(blocked).transcribed_track, 2)

    def test_files_are_named_after_the_physical_source_id(self) -> None:
        logical = _source_id(SESSION_ONE)
        physical = "synthetic-session-o-0123456789ab"
        root = _write_package(
            self.root,
            [_source(SESSION_ONE, physical_source_id=physical, physical_source_id_shortened=True,
                     transcript_correction_count=1)],
            kept={
                physical: [_segment(3.0, 4.0, "Read from the physical file.")],
                logical: [_segment(3.0, 4.0, "A decoy named after the logical id.")],
            },
            originals={physical: [_segment(3.0, 4.0, "Red from the physical file.")]},
            audits={physical: _audit(), logical: _audit(mode="Continuous")},
        )
        result = self._load(root)
        self.assertEqual([line.text for line in result.lines], ["Read from the physical file."])
        self.assertEqual(result.lines[0].original_text, "Red from the physical file.")
        self.assertEqual(result.mode, "Sparse")
        self.assertEqual((result.source_id, result.physical_source_id), (logical, physical))

    def test_the_logical_id_names_the_files_only_when_the_physical_id_is_blank(self) -> None:
        logical = _source_id(SESSION_ONE)
        root = _write_package(
            self.root,
            [_source(SESSION_ONE, physical_source_id="")],
            kept={logical: [_segment(3.0, 4.0, "Read from the logical file.")]},
        )
        result = self._load(root)
        self.assertEqual([line.text for line in result.lines], ["Read from the logical file."])
        self.assertEqual(result.physical_source_id, logical)

    def test_the_manifests_transcript_path_is_used_when_the_file_is_there(self) -> None:
        elsewhere = self.root / "kept-elsewhere" / "custom-name.transcript.json"
        _write_json(elsewhere, {"segments": _numbered([_segment(7.0, 8.0, "Read from the named path.")])})
        _write_json(elsewhere.with_name("custom-name.transcript.raw.json"), _audit(mode="Auto"))
        root = _write_package(
            self.root,
            [_source(SESSION_ONE, transcript_json_path=str(elsewhere))],
            kept={_source_id(SESSION_ONE): [_segment(7.0, 8.0, "Read from the package folder.")]},
        )
        result = self._load(root)
        self.assertEqual([line.text for line in result.lines], ["Read from the named path."])
        self.assertEqual(result.mode, "Auto")

    def test_a_moved_package_falls_back_to_its_own_transcript_folder(self) -> None:
        stale = r"Q:\Reviews\synthetic-run\codex-evidence-package\transcript\sources\gone.transcript.json"
        root = _write_package(
            self.root,
            [_source(SESSION_ONE, transcript_json_path=stale, raw_transcript_json_path=stale)],
            kept={_source_id(SESSION_ONE): [_segment(7.0, 8.0, "Read from the package folder.")]},
        )
        self.assertEqual([line.text for line in self._load(root).lines], ["Read from the package folder."])

    def test_a_package_without_an_audit_still_shows_its_kept_lines(self) -> None:
        file_id = _source_id(SESSION_ONE)
        root = _write_package(
            self.root,
            [_source(SESSION_ONE)],
            kept={file_id: [_segment(1.0, 2.0, "First line."), _segment(5.0, 6.0, "Second line.")]},
        )
        result = self._load(root)
        self.assertFalse(result.audit_available)
        self.assertFalse(result.rescued_known)
        self.assertFalse(result.filtering_ran)
        self.assertEqual(result.mode, "")
        self.assertEqual([(line.kind, line.text) for line in result.lines],
                         [("kept", "First line."), ("kept", "Second line.")])
        self.assertTrue(all(line.numbers == () and not line.rescued for line in result.lines))

    def test_the_mode_is_read_from_the_quality_file_when_the_audit_is_missing(self) -> None:
        file_id = _source_id(SESSION_ONE)
        root = _write_package(
            self.root,
            [_source(SESSION_ONE)],
            kept={file_id: [_segment(1.0, 2.0, "First line.")]},
            quality={file_id: {"schema_version": 1, "mode": "sparse", "quality_blocking": False}},
        )
        result = self._load(root)
        self.assertFalse(result.audit_available)
        self.assertEqual(result.mode, "Sparse")
        self.assertTrue(result.filtering_ran)

    def test_a_recording_transcribed_without_the_filter_says_no_filtering_ran(self) -> None:
        file_id = _source_id(SESSION_ONE)
        for mode in ("Continuous", "Auto"):
            with self.subTest(mode=mode):
                # The exact shape the transcriber writes when the sparse path is not taken.
                root = _write_package(
                    self.root / mode,
                    [_source(SESSION_ONE)],
                    kept={file_id: [_segment(1.0, 2.0, "First line.")]},
                    audits={file_id: _audit(mode=mode)},
                )
                result = self._load(root)
                self.assertEqual(result.mode, mode)
                self.assertFalse(result.filtering_ran)
                self.assertTrue(result.audit_available)
                self.assertEqual([line.kind for line in result.lines], ["kept"])

    def test_no_transcript_file_means_nothing_to_show(self) -> None:
        root = _write_package(self.root, [_source(SESSION_ONE)], audits={_source_id(SESSION_ONE): _audit()})
        self.assertIsNone(load_transcript(root, SESSION_ONE))

    def test_a_package_about_another_recording_shows_nothing(self) -> None:
        other_id = _source_id(SESSION_TWO)
        root = _write_package(
            self.root,
            [_source(SESSION_TWO)],
            kept={other_id: [_segment(1.0, 2.0, "A line from the other recording.")]},
        )
        self.assertIsNone(load_transcript(root, SESSION_ONE, duration_seconds=600.0))
        self.assertIsNotNone(load_transcript(root, SESSION_TWO, duration_seconds=600.0))

    def test_the_run_output_folder_works_as_well_as_the_package_folder(self) -> None:
        root = self._standard_package()
        self.assertEqual(root.parent, self.root)
        from_output_folder = load_transcript(self.root, SESSION_ONE)
        from_package_folder = load_transcript(root, SESSION_ONE)
        self.assertIsNotNone(from_output_folder)
        self.assertEqual(from_output_folder, from_package_folder)
        self.assertEqual(from_output_folder.package_root, root)

    def test_a_missing_package_is_none(self) -> None:
        self.assertIsNone(load_transcript(self.root / "never-written", SESSION_ONE))
        self.assertIsNone(load_transcript("", SESSION_ONE))
        self.assertIsNone(load_transcript(None, SESSION_ONE))

    def test_corrupt_json_never_raises(self) -> None:
        file_id = _source_id(SESSION_ONE)
        root = self._standard_package()
        sources_dir = root / "transcript" / "sources"

        (sources_dir / f"{file_id}.transcript.raw.json").write_text("{ cut short", encoding="utf-8")
        (sources_dir / f"{file_id}.voice.json").write_bytes(b"\xff\xfe\x00 not text")
        (root / "transcript" / "raw" / "sources" / f"{file_id}.transcript.json").write_text("[1, 2]", encoding="utf-8")
        result = self._load(root)
        self.assertFalse(result.audit_available)
        self.assertEqual(result.track_explanation, "")
        self.assertEqual([line.kind for line in result.lines], ["kept"] * 4)
        self.assertTrue(all(line.original_text == "" for line in result.lines))

        (sources_dir / f"{file_id}.transcript.json").write_text("not json at all", encoding="utf-8")
        self.assertIsNone(load_transcript(root, SESSION_ONE))

        (sources_dir / f"{file_id}.transcript.json").write_text('["a list, not an object"]', encoding="utf-8")
        self.assertIsNone(load_transcript(root, SESSION_ONE))

        (root / "manifest.json").write_text("{", encoding="utf-8")
        self.assertIsNone(load_transcript(root, SESSION_ONE))

    def test_a_folder_where_a_file_should_be_never_raises(self) -> None:
        file_id = _source_id(SESSION_ONE)
        root = _write_package(self.root, [_source(SESSION_ONE)],
                              kept={file_id: [_segment(1.0, 2.0, "First line.")]})
        # Reading a directory raises OSError (PermissionError on Windows); it must read as "absent".
        (root / "transcript" / "sources" / f"{file_id}.transcript.raw.json").mkdir()
        result = self._load(root)
        self.assertFalse(result.audit_available)
        self.assertEqual([line.text for line in result.lines], ["First line."])

    def test_wrong_types_never_raise_and_unplaceable_entries_are_skipped(self) -> None:
        file_id = _source_id(SESSION_ONE)
        good_drop = _segment("21.5", 22, " Thanks for watching!", no_speech_prob="0.5", avg_logprob=None,
                             compression_ratio=True)
        root = _write_package(
            self.root,
            [_source(SESSION_ONE, transcript_quality="suspicious", selected_audio_stream_index="1",
                     transcript_json_path=["not", "text"])],
            audits={file_id: {
                "mode": 7,
                "raw_attempts": [None, "text", {"chunk_index": "one", "attempt": 1, "segments": "nope"},
                                 {"chunk_index": 1, "attempt": 1, "segments": [None, {"start": "x"}]}],
                "filtered_segments": [
                    None,
                    7,
                    {"chunk_index": 1, "attempt": 1, "reason": "known_filler_phrase", "segment": "nope"},
                    {"chunk_index": 1, "attempt": 1, "reason": "known_filler_phrase",
                     "segment": _segment(None, 5.0, " no start")},
                    {"chunk_index": 1, "attempt": 1, "reason": "known_filler_phrase",
                     "segment": _segment(4.0, "later", " no end")},
                    {"chunk_index": 1, "attempt": 1, "reason": "known_filler_phrase",
                     "segment": _segment(True, False, " booleans are not times")},
                    {"chunk_index": 1, "attempt": 1, "reason": "known_filler_phrase",
                     "segment": _segment(float("nan"), 9.0, " not a number")},
                    {"chunk_index": 1, "attempt": 1, "reason": None, "segment": good_drop},
                ],
                "rescued_segments": {"not": "a list"},
                "rejected_chunks": [5, {"chunk_index": 9, "interval": [1, 2]},
                                    {"chunk_index": 9, "interval": {"start_seconds": "soon"}}],
            }},
        )
        # Written by hand: json.dumps would refuse nothing here, but the kept file needs odd members too.
        _write_json(
            root / "transcript" / "sources" / f"{file_id}.transcript.json",
            {"segments": [
                None,
                "text",
                _segment(-3.0, -1.0, "Before the start of the recording."),
                _segment(10.0, 9.0, "Ends before it starts."),
                _segment(None, 12.0, "No start."),
                _segment(13.0, 14.0, None),
                _segment(15.0, 16.0, "   "),
                _segment(17, "18.5", "Whole numbers and numeric text are fine."),
            ]},
        )
        result = self._load(root)
        self.assertEqual(
            [(line.start, line.end, line.kind, line.text) for line in result.lines],
            [
                (0.0, 0.0, "kept", "Before the start of the recording."),
                (10.0, 10.0, "kept", "Ends before it starts."),
                (17.0, 18.5, "kept", "Whole numbers and numeric text are fine."),
                (21.5, 22.0, "left_out", "Thanks for watching!"),
            ],
        )
        dropped = result.lines[-1]
        self.assertEqual(dropped.numbers, (("no_speech_prob", 0.5),))
        self.assertEqual(dropped.reason_text, 'Left out — reason recorded as "".')
        self.assertEqual(result.mode, "")
        self.assertFalse(result.rescued_known)
        self.assertFalse(result.contamination_suspected)
        self.assertIsNone(result.transcribed_track)

    def test_segments_that_are_not_a_list_leave_an_empty_transcript(self) -> None:
        file_id = _source_id(SESSION_ONE)
        root = _write_package(self.root, [_source(SESSION_ONE)])
        _write_json(root / "transcript" / "sources" / f"{file_id}.transcript.json", {"segments": "nope"})
        result = self._load(root)
        self.assertEqual(result.lines, ())

    def test_the_reader_matches_what_the_real_filter_writes(self) -> None:
        """Assemble the audit the way the sparse loop does, from the real filter's output."""

        interval = SpeechInterval(100.0, 106.0)
        raw_segments = offset_segments(
            [
                {"start": 0.0, "end": 2.0, "text": " Thanks for watching!", "avg_logprob": -0.3,
                 "compression_ratio": 1.1, "no_speech_prob": 0.1},
                {"start": 2.0, "end": 5.0, "text": " The lap counter froze on the second screen.",
                 "avg_logprob": -0.2, "compression_ratio": 1.3, "no_speech_prob": 0.02},
                {"start": 5.0, "end": 5.5, "text": " Tyre temps.", "avg_logprob": -0.9,
                 "compression_ratio": 0.8, "no_speech_prob": 0.5},
            ],
            interval.start_seconds,
        )
        accepted, dropped = filter_sparse_decoder_segments(raw_segments, context_segments=[])
        self.assertEqual(len(accepted), 2, "the fixture must keep the narration and rescue the aside")
        self.assertEqual(len(dropped), 1, "the fixture must drop the stock phrase")
        audit = {
            "schema_version": 1,
            "language": "en",
            "mode": "Sparse",
            "raw_attempts": [{"chunk_index": 1, "attempt": 1, "interval": interval.to_dict(), "metrics": {},
                              "segments": raw_segments, "filtered_segments": dropped}],
            "filtered_segments": [{"chunk_index": 1, "attempt": 1, **item} for item in dropped],
            "rescued_segments": [
                {"chunk_index": 1, "attempt": 1, "reason": "low_information_kept_near_narration",
                 "segment": segment}
                for segment in accepted
                if segment.get("low_information_kept_near_narration")
            ],
            "rejected_chunks": [],
        }
        file_id = _source_id(SESSION_ONE)
        root = _write_package(
            self.root,
            [_source(SESSION_ONE)],
            kept={file_id: [_segment(item["start"], item["end"], item["text"].strip()) for item in accepted]},
            audits={file_id: audit},
        )
        result = self._load(root)
        self.assertEqual(
            [(line.start, line.kind, line.rescued) for line in result.lines],
            [(100.0, "left_out", False), (102.0, "kept", False), (105.0, "kept", True)],
        )
        self.assertEqual(result.lines[0].reason_text, FILLER_SENTENCE)
        self.assertEqual(
            result.lines[2].numbers,
            (("no_speech_prob", 0.5), ("avg_logprob", -0.9), ("compression_ratio", 0.8)),
        )
        self.assertTrue(result.rescued_known)


class ReasonTextTests(unittest.TestCase):
    def test_every_known_code_has_its_exact_sentence(self) -> None:
        self.assertEqual(reason_text("known_filler_phrase", " Thanks for watching!"), FILLER_SENTENCE)
        self.assertEqual(reason_text("compression_ratio_threshold", " la la la"), REPEATING_SENTENCE)
        # 199: a line another track carries; the track is named when the audit says which.
        self.assertEqual(
            reason_text("heard_on_another_track", " la la la, an invented chorus line", track="Track 6 (T6 - Music)"),
            "Left out: written down from sound on Track 6 (T6 - Music), not from you.",
        )
        self.assertEqual(
            reason_text("heard_on_another_track", " la la la, an invented chorus line"),
            "Left out: written down from sound on another track, not from you.",
        )
        # 203: said where the narration track itself was nearly silent.
        self.assertEqual(
            reason_text("narration_track_near_silent", " I hope you enjoyed it."),
            "Left out: your microphone track was nearly silent here, so these words were not yours.",
        )
        # 199: a phrase said over and over, as Whisper invents over music.
        self.assertEqual(
            reason_text("phrase_loop", " a sample phrase, a sample phrase, a sample phrase"),
            "Left out: one phrase said over and over, which the transcriber tends to invent over music.",
        )
        self.assertEqual(reason_text("combined_low_speech_information", " hm"), NOT_CONFIDENT_SENTENCE)
        self.assertEqual(
            reason_text("repetition_persisted_after_retry", "again and again", start=2467.2, end=2497.2),
            "This whole stretch (0:41:07–0:41:37) was thrown out: the transcriber kept repeating itself "
            "even on a second try.",
        )

    def test_a_dropped_segment_with_no_letters_does_not_blame_a_stock_phrase(self) -> None:
        for text in ("", "   ", "...", "♪ 12 ♪", None):
            with self.subTest(text=text):
                self.assertEqual(reason_text("known_filler_phrase", text), NO_WORDS_SENTENCE)
        self.assertEqual(reason_text("known_filler_phrase"), NO_WORDS_SENTENCE)

    def test_an_unknown_code_is_shown_as_recorded(self) -> None:
        self.assertEqual(
            reason_text("some_future_rule", "Anything."),
            'Left out — reason recorded as "some_future_rule".',
        )

    def test_times_past_an_hour_and_odd_times_are_formatted_safely(self) -> None:
        sentence = reason_text("repetition_persisted_after_retry", start=3725.9, end=float("nan"))
        self.assertIn("(1:02:05–0:00:00)", sentence)
        self.assertIn("(0:00:00–0:00:00)", reason_text("repetition_persisted_after_retry", start=-4.0))


class MovingThroughLinesTests(unittest.TestCase):
    LINES = (
        _line(10.0, 12.0),
        _line(12.0, 15.0, "left_out"),
        _line(40.0, 44.0),
        _line(100.0, 130.0, "rejected_span"),
        _line(200.0, 200.0),
    )

    def test_visible_lines_follow_the_filter(self) -> None:
        self.assertEqual(visible_lines(self.LINES, "all"), list(self.LINES))
        self.assertEqual([line.start for line in visible_lines(self.LINES, "kept")], [10.0, 40.0, 200.0])
        self.assertEqual([line.start for line in visible_lines(self.LINES, "left_out")], [12.0, 100.0],
                         "a stretch thrown out whole counts as left out")
        self.assertEqual(visible_lines(self.LINES, "something else"), list(self.LINES))
        self.assertEqual(visible_lines((), "kept"), [])
        copy = visible_lines(self.LINES, "all")
        copy.clear()
        self.assertEqual(len(self.LINES), 5)

    def test_line_index_at_finds_the_line_being_spoken(self) -> None:
        self.assertIsNone(line_index_at(self.LINES, 0.0))
        self.assertIsNone(line_index_at(self.LINES, 9.99))
        self.assertEqual(line_index_at(self.LINES, 10.0), 0)
        self.assertEqual(line_index_at(self.LINES, 11.99), 0)
        self.assertEqual(line_index_at(self.LINES, 12.0), 1, "a line's end belongs to the line that starts there")
        self.assertIsNone(line_index_at(self.LINES, 15.0))
        self.assertIsNone(line_index_at(self.LINES, 30.0))
        self.assertEqual(line_index_at(self.LINES, 115.0), 3)
        self.assertEqual(line_index_at(self.LINES, 200.0), 4, "a line with no length can still be landed on")
        self.assertIsNone(line_index_at(self.LINES, 200.5))
        self.assertIsNone(line_index_at((), 5.0))

    def test_line_index_at_prefers_the_line_that_started_last(self) -> None:
        overlapping = (_line(100.0, 130.0, "rejected_span"), _line(110.0, 112.0))
        self.assertEqual(line_index_at(overlapping, 105.0), 0)
        self.assertEqual(line_index_at(overlapping, 111.0), 1)
        self.assertEqual(line_index_at(overlapping, 120.0), 0)

    def test_next_line_is_the_first_one_starting_after_now(self) -> None:
        self.assertEqual(next_line_index(self.LINES, 0.0), 0)
        self.assertEqual(next_line_index(self.LINES, 10.0), 1)
        self.assertEqual(next_line_index(self.LINES, 20.0), 2)
        self.assertEqual(next_line_index(self.LINES, 150.0), 4)
        self.assertIsNone(next_line_index(self.LINES, 200.0))
        self.assertIsNone(next_line_index((), 0.0))

    def test_next_line_skips_the_line_a_seek_has_just_landed_on(self) -> None:
        # A seek to 40.0 can land a frame early; "Next line" must not offer line 40.0 again.
        self.assertEqual(next_line_index(self.LINES, 39.97), 3)
        self.assertEqual(next_line_index(self.LINES, 39.9), 2)

    def test_previous_line_works_like_a_cd_player(self) -> None:
        self.assertIsNone(previous_line_index(self.LINES, 5.0), "no line has started yet")
        self.assertEqual(previous_line_index(self.LINES, 42.5), 2, "well into a line: back to its start")
        self.assertEqual(previous_line_index(self.LINES, 41.0), 1, "exactly one second in still goes back a line")
        self.assertEqual(previous_line_index(self.LINES, 40.5), 1, "just started: the line before")
        self.assertEqual(previous_line_index(self.LINES, 40.0), 1)
        self.assertEqual(previous_line_index(self.LINES, 60.0), 2, "between lines: the line that just ended")
        self.assertEqual(previous_line_index(self.LINES, 10.2), 0, "nothing before the first line: restart it")
        self.assertEqual(previous_line_index(self.LINES, 500.0), 4)
        self.assertIsNone(previous_line_index((), 5.0))

    def test_pressing_previous_again_and_again_walks_back_to_the_first_line(self) -> None:
        position = 250.0
        visited = []
        for _press in range(6):
            index = previous_line_index(self.LINES, position)
            visited.append(index)
            position = self.LINES[index].start
        self.assertEqual(visited, [4, 3, 2, 1, 0, 0])

    def test_upcoming_line_names_what_comes_next(self) -> None:
        self.assertEqual(upcoming_line(self.LINES, 20.0), self.LINES[2])
        self.assertEqual(upcoming_line(self.LINES, 0.0), self.LINES[0])
        self.assertEqual(upcoming_line(self.LINES, 10.0), self.LINES[1])
        self.assertIsNone(upcoming_line(self.LINES, 200.0))
        self.assertIsNone(upcoming_line((), 0.0))


class ReviewCopyTests(TempFolderTestCase):
    def _package(self, *, write_video: bool, review_video: str | None = None, manifest: bool = True) -> Path:
        source_id = _source_id(SESSION_ONE)
        relative = review_video or f"artifacts/narration/{source_id}/review_video_{source_id}.mp4"
        root = _write_package(
            self.root,
            [_source(SESSION_TWO), _source(SESSION_ONE)],
            narration_sources=[
                {"source_id": _source_id(SESSION_TWO), "source_filename": SESSION_TWO.name, "review_video": ""},
                {"source_id": source_id, "source_filename": SESSION_ONE.name, "review_video": relative},
            ],
        )
        if write_video:
            target = root / f"artifacts/narration/{source_id}/review_video_{source_id}.mp4"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"synthetic, not a real video")
        if not manifest:
            (root / "manifest.json").unlink()
        return root

    def test_the_review_copy_is_offered_only_when_the_file_exists(self) -> None:
        root = self._package(write_video=True)
        source_id = _source_id(SESSION_ONE)
        expected = root / "artifacts" / "narration" / source_id / f"review_video_{source_id}.mp4"
        self.assertEqual(review_copy_for(root, SESSION_ONE), expected)
        self.assertEqual(review_copy_for(self.root, SESSION_ONE), expected, "the run output folder works too")
        expected.unlink()
        self.assertIsNone(review_copy_for(root, SESSION_ONE))

    def test_a_source_without_a_review_copy_offers_nothing(self) -> None:
        root = self._package(write_video=True)
        self.assertIsNone(review_copy_for(root, SESSION_TWO))
        self.assertIsNone(review_copy_for(root, Path(r"Q:\Captured Sessions\synthetic-session-three.mkv")))

    def test_the_index_alone_is_enough_when_the_manifest_is_gone(self) -> None:
        root = self._package(write_video=True, manifest=False)
        self.assertIsNotNone(review_copy_for(root, SESSION_ONE))
        self.assertIsNone(review_copy_for(root, Path(r"Q:\Captured Sessions\synthetic-session-three.mkv")))

    def test_a_shared_file_name_alone_offers_no_copy(self) -> None:
        # With the recording missing its length cannot be checked, so the name is not enough: this
        # could be another recording that only happens to be called the same.
        for manifest in (True, False):
            with self.subTest(manifest=manifest):
                root = self._package(write_video=True, manifest=manifest)
                self.assertIsNone(review_copy_for(root, MOVED_SESSION_ONE))
                self.assertIsNotNone(review_copy_for(root, SESSION_ONE))

    def test_the_missing_recordings_drive_is_never_touched(self) -> None:
        root = self._package(write_video=True)
        source_id = _source_id(SESSION_ONE)
        expected = root / "artifacts" / "narration" / source_id / f"review_video_{source_id}.mp4"
        # Resolving a path on a sleeping or unplugged drive can hang, and this runs while the operator
        # waits on a message box.
        with patch.object(Path, "resolve", side_effect=AssertionError("the recording's path was resolved")):
            self.assertEqual(review_copy_for(root, SESSION_ONE), expected)
            self.assertIsNone(review_copy_for(root, SESSION_TWO))

    def test_a_path_that_leaves_the_package_is_never_played(self) -> None:
        outside = self.root / "outside.mp4"
        outside.write_bytes(b"synthetic, not a real video")
        for review_video in ("../outside.mp4", str(outside)):
            with self.subTest(review_video=review_video):
                root = self._package(write_video=False, review_video=review_video)
                self.assertIsNone(review_copy_for(root, SESSION_ONE))

    def test_missing_or_corrupt_index_never_raises(self) -> None:
        root = _write_package(self.root, [_source(SESSION_ONE)])
        self.assertIsNone(review_copy_for(root, SESSION_ONE))
        (root / "NARRATION_EVIDENCE.json").write_text("{ cut short", encoding="utf-8")
        self.assertIsNone(review_copy_for(root, SESSION_ONE))
        _write_json(root / "NARRATION_EVIDENCE.json", {"sources": [None, 3, {"source_id": 5, "review_video": 9}]})
        self.assertIsNone(review_copy_for(root, SESSION_ONE))
        self.assertIsNone(review_copy_for(self.root / "never-written", SESSION_ONE))


class FindPackageTests(TempFolderTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.other = _write_package(self.root / "run-other", [_source(SESSION_TWO)])
        self.first = _write_package(self.root / "run-first", [_source(SESSION_ONE)])
        self.second = _write_package(self.root / "run-second", [_source(SESSION_TWO), _source(SESSION_ONE)])

    def test_hints_are_walked_in_order(self) -> None:
        hints = [self.root / "run-other", self.root / "run-first", self.root / "run-second"]
        self.assertEqual(find_package_for_recording(SESSION_ONE, hints), self.first)
        self.assertEqual(find_package_for_recording(SESSION_ONE, list(reversed(hints))), self.second)
        self.assertEqual(find_package_for_recording(SESSION_TWO, hints), self.other)

    def test_a_hint_can_be_the_run_output_folder_or_the_package_folder_itself(self) -> None:
        self.assertEqual(find_package_for_recording(SESSION_ONE, [self.root / "run-first"]), self.first)
        self.assertEqual(find_package_for_recording(SESSION_ONE, [self.first]), self.first)
        self.assertEqual(find_package_for_recording(SESSION_ONE, [str(self.first)]), self.first)

    def test_no_hint_holding_the_recording_means_none(self) -> None:
        self.assertIsNone(find_package_for_recording(SESSION_ONE, []))
        self.assertIsNone(find_package_for_recording(SESSION_ONE, [self.root / "run-other"]))

    def test_blank_missing_and_corrupt_hints_are_passed_over(self) -> None:
        corrupt = self.root / "run-corrupt" / "codex-evidence-package"
        corrupt.mkdir(parents=True)
        (corrupt / "manifest.json").write_text("{ cut short", encoding="utf-8")
        hints = ["", "   ", None, self.root / "never-written", corrupt, self.root / "run-first"]
        self.assertEqual(find_package_for_recording(SESSION_ONE, hints), self.first)

    def test_the_length_is_checked_for_a_moved_recording(self) -> None:
        hints = [self.root / "run-first"]
        self.assertEqual(
            find_package_for_recording(MOVED_SESSION_ONE, hints, duration_seconds=600.5), self.first
        )
        self.assertIsNone(find_package_for_recording(MOVED_SESSION_ONE, hints, duration_seconds=900.0))

    def test_a_package_made_from_the_file_this_one_replaced_is_passed_over(self) -> None:
        # Same path in every package; only the newest run was made from the file that is there now.
        newest = _write_package(self.root / "run-newest", [_source(SESSION_ONE, duration_seconds=3000.0)])
        hints = [self.root / "run-first", self.root / "run-second", self.root / "run-newest"]
        self.assertEqual(find_package_for_recording(SESSION_ONE, hints, duration_seconds=3000.4), newest)
        self.assertIsNone(find_package_for_recording(SESSION_ONE, hints[:2], duration_seconds=3000.4))
        self.assertEqual(find_package_for_recording(SESSION_ONE, hints), self.first,
                         "with no length to go on the path still decides")

    def test_cancelling_stops_the_walk(self) -> None:
        hints = [self.root / "run-other", self.root / "run-first"]
        self.assertIsNone(find_package_for_recording(SESSION_ONE, hints, cancelled=lambda: True))

        asked: list[int] = []

        def cancelled_after_the_first_hint() -> bool:
            asked.append(len(asked))
            return len(asked) > 1

        self.assertIsNone(
            find_package_for_recording(SESSION_ONE, hints, cancelled=cancelled_after_the_first_hint)
        )
        self.assertEqual(len(asked), 2, "asked before every hint, and not again after it said stop")


if __name__ == "__main__":
    unittest.main()
