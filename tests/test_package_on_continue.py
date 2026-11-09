"""201: a Continue leaves nothing of an earlier run looking current, and ZIPs are as before.

Find my bug reports keeps its package as a folder (handoff mode Local) in a new dated folder per
run; only Continue runs again in the same folder. There, narration visuals the earlier run made
that this run does not (moments no longer found, clips made from another audio track) are removed,
inside the run's own package folder only.

Workflows that build a portable ZIP (AI / Ticket Evidence with Portable ZIP or Both) are not
changed at all: their ZIP still holds the whole package, and nothing of their folder is pruned.
These run the real backend; only Whisper is stood in for.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

from tests.test_skipped_recording_privacy import _run_batch
from tests.test_voice_track import _three_track_recording


def _narration_folder(package: Path) -> Path:
    folders = [path for path in (package / "artifacts" / "narration").iterdir() if path.is_dir()]
    return next(folder for folder in folders if folder.name.startswith("a-session"))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class ContinueLeavesNothingStaleTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = tempfile.TemporaryDirectory()
        folder = Path(cls._temp.name) / "recordings"
        folder.mkdir()
        first = _three_track_recording(folder / "a-session.mkv")
        # _run_batch treats the second recording as the one a test may skip; none is skipped here.
        shutil.copy(first, folder / "b-session.mkv")
        cls.recordings = [first, folder / "b-session.mkv"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temp.cleanup()

    def _first_run_then_continue(self, root: Path, *, arguments: str = "") -> tuple[Path, Path, dict]:
        out = root / "out"
        self.assertEqual(_run_batch(root / "first", self.recordings, out, arguments=arguments), "")
        package = out / "codex-evidence-package"
        own = _narration_folder(package)
        # What an earlier run of this package can leave: a clip of a moment no longer found, the
        # visuals of a recording that has no narrated moments now, and a review copy and clips made
        # from another audio track (the operator chose another track and pressed Continue).
        (own / "clips" / "old-moment.mp4").write_bytes(b"an earlier run's clip")
        gone = package / "artifacts" / "narration" / "gone-session-0000000000" / "clips"
        gone.mkdir(parents=True)
        (gone / "gone.mp4").write_bytes(b"an earlier run's clip")
        plan_path = package / "artifacts" / "narration" / "plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        for task in plan["clip_tasks"] + plan["review_video_tasks"]:
            task["audio_ordinal"] = 0
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        review = next(own.glob("review_video_*.mp4"))
        review.write_bytes(b"made from Track 1")
        self.assertEqual(_run_batch(root / "continue", self.recordings, out, arguments=arguments), "")
        return package, own, plan

    def test_a_continue_removes_what_this_run_does_not_make(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            package, own, _plan = self._first_run_then_continue(Path(temp))
            self.assertFalse((own / "clips" / "old-moment.mp4").exists())
            self.assertFalse((package / "artifacts" / "narration" / "gone-session-0000000000").exists())
            # Made again from the narration track, not kept from Track 1.
            review = next(own.glob("review_video_*.mp4"))
            self.assertNotEqual(review.read_bytes(), b"made from Track 1")
            # Everything the index lists is there, and nothing else is in the narration folder.
            index = json.loads((package / "NARRATION_EVIDENCE.json").read_text(encoding="utf-8-sig"))
            listed = {source["review_video"] for source in index["sources"]}
            for source in index["sources"]:
                for moment in source["moments"]:
                    listed.update(clip["path"] for clip in moment["clips"])
                    for frame in moment["frames"]:
                        listed.add(frame["full_frame"])
                        listed.update(frame["panels"].values())
            on_disk = {path.relative_to(package).as_posix()
                       for path in (package / "artifacts" / "narration").rglob("*")
                       if path.is_file() and path.name != "plan.json"}
            self.assertEqual(on_disk, listed)
            self.assertFalse((package / "ticket-agent-handoff.zip").exists())

    def test_a_workflow_that_builds_a_zip_is_left_exactly_as_before(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            package, own, _plan = self._first_run_then_continue(Path(temp), arguments="-HandoffMode PortableZip")
            # Nothing of its folder is pruned on a Continue: as before this wave.
            self.assertTrue((own / "clips" / "old-moment.mp4").exists())
            self.assertTrue((package / "artifacts" / "narration" / "gone-session-0000000000" / "clips" / "gone.mp4").exists())

    def test_a_workflow_that_builds_a_zip_still_gets_the_whole_package_in_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            out = root / "out"
            self.assertEqual(_run_batch(root / "run", self.recordings, out, arguments="-HandoffMode PortableZip"), "")
            package = out / "codex-evidence-package"
            archive_path = package / "ticket-agent-handoff.zip"
            self.assertTrue(archive_path.is_file())
            with zipfile.ZipFile(archive_path) as archive:
                zipped = {name for name in archive.namelist() if not name.endswith("/")}
            omitted = set()
            omitted_path = package / "OMITTED_MEDIA.json"
            if omitted_path.is_file():
                omitted = {item["path"] for item in json.loads(omitted_path.read_text(encoding="utf-8-sig")).get("omitted") or []}
            # As before this wave the ZIP is made before the narration visuals, so it holds every
            # file the package had then: everything except the run log, the ZIP itself and what was
            # written after it.
            later = {"NARRATION_EVIDENCE.json", "NARRATION_EVIDENCE.md", "PORTABLE_PRIVACY_REPORT.json"}
            expected = {path.relative_to(package).as_posix() for path in package.rglob("*")
                        if path.is_file() and path.suffix != ".log" and path.name != archive_path.name
                        and not path.relative_to(package).as_posix().startswith("artifacts/narration/")
                        and path.name not in later} - omitted
            self.assertTrue(expected)
            self.assertEqual(expected - zipped, set())


if __name__ == "__main__":
    unittest.main()
