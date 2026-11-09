"""125 Part 2, 134 (Wave 8): what a package found in one recording, and its clips.

A synthetic package with two recordings: each one's moments come only from its own records, kinds
use Session Review's words, an explicit marker that a ticket mention covers is left out, a package
made before the Session timeline still gives its moments, and the narration index is read for its
clips and small review copies without ever leaving the package. Nothing here is a real recording.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers_workbench.review_package import (  # noqa: E402
    MOMENT_NARRATION,
    load_moments,
    moment_seconds,
    narration_files,
    read_narration_index,
    recording_for_source,
    review_copy_for,
    source_digest,
)


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class SyntheticPackage:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.root = folder / "run" / "codex-evidence-package"
        self.first = folder / "recordings" / "first.mkv"
        self.second = folder / "recordings" / "second.mkv"
        self.first_id = f"first-{source_digest(self.first)}"
        self.second_id = f"second-{source_digest(self.second)}"
        write(self.root / "manifest.json", {"sources": [
            {"source_id": self.first_id, "physical_source_id": self.first_id, "source_path": str(self.first),
             "source_filename": "first.mkv", "duration_seconds": 3600.0},
            {"source_id": self.second_id, "physical_source_id": self.second_id, "source_path": str(self.second),
             "source_filename": "second.mkv", "duration_seconds": 1800.0},
        ]})

    def timeline(self, records: list[dict]) -> None:
        write(self.root / "SESSION_TIMELINE.json", {"records": records})

    def narration(self, sources: list[dict]) -> None:
        write(self.root / "NARRATION_EVIDENCE.json", {"schema_version": 1, "sources": sources})


def record(kind: str, source_id: str, seconds: float, *, focused: float = 0.0, excerpt: str = "", status: str = "") -> dict:
    return {"record_type": kind, "mention_id": f"{kind}-{seconds}", "source_id": source_id,
            "timestamp_seconds": seconds, "timestamp": "", "focused_start_seconds": focused,
            "focused_end_seconds": 0.0, "excerpt": excerpt, "render_status": status}


class MomentsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.package = SyntheticPackage(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_only_this_recordings_moments_in_session_reviews_words(self) -> None:
        p = self.package
        p.timeline([
            record("ticket_mention", p.first_id, 130.0, focused=120.0, excerpt="make the fuel number bigger"),
            record("review_needed", p.first_id, 300.0, excerpt="not sure about this one"),
            record("ticket_mention", p.second_id, 50.0, excerpt="another recording"),
        ])
        moments = load_moments(p.root, p.first, duration_seconds=3600.0)
        self.assertEqual([(m.seconds, m.text) for m in moments], [(120.0, "ticket mention"), (300.0, "review needed")])
        self.assertTrue(all(m.finding for m in moments))
        self.assertEqual(moments[0].excerpt, "make the fuel number bigger")

    def test_a_marker_a_ticket_mention_already_covers_is_left_out(self) -> None:
        p = self.package
        p.timeline([
            record("ticket_mention", p.first_id, 130.0, focused=120.0),
            record("explicit_marker", p.first_id, 128.0, status="covered"),
            record("explicit_marker", p.first_id, 900.0, status="uncovered"),
        ])
        moments = load_moments(p.root, p.first)
        self.assertEqual([(m.seconds, m.kind) for m in moments],
                         [(120.0, "ticket_mention"), (900.0, "explicit_marker")])

    def test_the_moments_you_were_talking_come_from_the_narration_index(self) -> None:
        p = self.package
        p.timeline([record("ticket_mention", p.first_id, 130.0, focused=120.0)])
        p.narration([
            {"source_id": p.first_id, "source_filename": "first.mkv", "review_video": "", "moments": [
                {"moment_index": 1, "start_seconds": 61.5, "end_seconds": 70.0, "text": "here I go", "clips": []}]},
            {"source_id": p.second_id, "moments": [{"start_seconds": 10.0, "text": "not this one"}]},
        ])
        moments = load_moments(p.root, p.first)
        narration = [m for m in moments if m.kind == MOMENT_NARRATION]
        self.assertEqual([(m.seconds, m.text, m.finding) for m in narration], [(61.5, "you were talking", False)])
        self.assertEqual([m.seconds for m in moments], [61.5, 120.0], "in time order")

    def test_a_package_made_before_the_session_timeline_still_gives_its_moments(self) -> None:
        p = self.package
        write(p.root / "CANDIDATE_TICKETS.json", {"candidates": [
            {"evidence_id": "C1", "source_id": p.first_id, "timestamp_start_seconds": 200.0,
             "marker_timestamp_seconds": 210.0, "suggested_issue_title": "Fuel number"}]})
        write(p.root / "REVIEW_NEEDED.json", {"review_needed": [
            {"review_id": "R1", "source_id": p.first_id, "timestamp_start_seconds": 400.0,
             "marker_timestamp_seconds": 405.0}]})
        moments = load_moments(p.root, p.first)
        self.assertEqual([(m.seconds, m.kind) for m in moments], [(200.0, "ticket_mention"), (405.0, "review_needed")])

    def test_a_recording_the_package_does_not_list_or_another_length_gets_nothing(self) -> None:
        p = self.package
        p.timeline([record("ticket_mention", p.first_id, 130.0, focused=120.0)])
        self.assertEqual(load_moments(p.root, Path(self.temp.name) / "elsewhere.mkv"), ())
        self.assertEqual(load_moments(p.root, p.first, duration_seconds=100.0), ())

    def test_broken_files_never_raise(self) -> None:
        p = self.package
        (p.root / "SESSION_TIMELINE.json").write_text("{not json", encoding="utf-8")
        (p.root / "NARRATION_EVIDENCE.json").write_text('{"sources": [1, null, {"moments": "x"}]}', encoding="utf-8")
        self.assertEqual(load_moments(p.root, p.first), ())
        self.assertEqual(load_moments(Path(self.temp.name) / "nothing-here", p.first), ())

    def test_the_moment_rule_and_the_manifest_join_moved_unchanged(self) -> None:
        self.assertEqual(moment_seconds(0.0, "", "0:02:05.5"), 125.5)
        self.assertEqual(moment_seconds(None, "x", True), 0.0)
        p = self.package
        manifest = json.loads((p.root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(recording_for_source(manifest, "", p.second_id), str(p.second))
        self.assertEqual(recording_for_source(manifest, "nope"), "")


class NarrationFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.package = SyntheticPackage(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_a_clip_and_a_review_copy_are_listed_inside_the_package(self) -> None:
        p = self.package
        p.narration([{"source_id": p.first_id, "source_filename": "first.mkv",
                      "review_video": f"artifacts/narration/{p.first_id}/review_video_{p.first_id}.mp4",
                      "moments": [{"moment_index": 1, "start_seconds": 61.5, "start": "00:01:01.500", "clips": [
                          {"path": f"artifacts/narration/{p.first_id}/clips/a_1.mp4", "start": "00:00:56.500",
                           "end": "00:01:20.000", "part": 1},
                          {"path": f"artifacts/narration/{p.first_id}/clips/a_2.mp4", "start": "00:01:20.000",
                           "end": "00:01:50.000", "part": 2}]}]}])
        found = narration_files(p.root)
        self.assertEqual(len(found), 1)
        files = found[0]
        self.assertEqual(files.source_filename, "first.mkv")
        self.assertEqual(files.review_copy, p.root / f"artifacts/narration/{p.first_id}/review_video_{p.first_id}.mp4")
        self.assertEqual([(clip.part, clip.parts, clip.seconds, clip.start_seconds) for clip in files.clips],
                         [(1, 2, 61.5, 56.5), (2, 2, 61.5, 80.0)])
        self.assertTrue(all(p.root in clip.path.parents for clip in files.clips))

    def test_a_copy_that_was_not_made_and_a_path_leaving_the_package_are_never_listed(self) -> None:
        p = self.package
        p.narration([{"source_id": p.first_id, "review_video": "", "moments": [
            {"start_seconds": 5.0, "clips": [{"path": "../../outside.mp4"}, {"path": "C:/elsewhere.mp4"}]}]}])
        files = narration_files(p.root)[0]
        self.assertIsNone(files.review_copy)
        self.assertEqual(files.clips, ())

    def test_a_package_without_the_index_lists_nothing_and_the_review_copy_fallback_still_works(self) -> None:
        p = self.package
        self.assertEqual(narration_files(p.root), [])
        self.assertIsNone(read_narration_index(p.root))
        copy = p.root / "artifacts" / "copy.mp4"
        copy.parent.mkdir(parents=True)
        copy.write_bytes(b"x")
        p.narration([{"source_id": p.first_id, "review_video": "artifacts/copy.mp4", "moments": []}])
        self.assertEqual(review_copy_for(p.root, p.first), copy)


if __name__ == "__main__":
    unittest.main()
