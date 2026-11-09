"""Moves, removals and replaces that wait for an antivirus-style hold (224, Wave B2a, items 2 and 3).

Antivirus scanners, the search indexer and Explorer's thumbnails open a file the app has just written for a
moment, and Windows refuses to rename or delete it, or the folder holding it, until they let go. The app's one
helper (``safe_write``) waits a bounded time for such a hold by another program, never for a hold by the app
itself, and never loses data. The holds here are real: a separate program (``tests/outside_holder.py``) opens
the file the way those programs do. No real antivirus is involved, and the timing is deterministic: the helper's
pause is passed in, so a test lets go of the hold during the second pause.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from media_manglers.core import safe_write
from tests.outside_holder import OutsideHolder

WINDOWS = os.name == "nt"


class Pauses:
    """The helper's pause: it records each pause, never sleeps, and runs ``on`` at the pause numbered ``at``."""

    def __init__(self, at: int = 0, on=None) -> None:
        self.taken: list[float] = []
        self.at, self.on = at, on

    def __call__(self, seconds: float) -> None:
        self.taken.append(seconds)
        if len(self.taken) == self.at and self.on is not None:
            self.on()


def _tree(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="av-safe-"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def _file(self, name: str, data: bytes = b"recording evidence\n" * 50) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def _folder(self, name: str) -> Path:
        folder = self.root / name
        self._file(f"{name}/inner.txt", b"inside")
        self._file(f"{name}/sub/deeper.json", b"{}")
        return folder


@unittest.skipUnless(WINDOWS, "Windows refuses to rename or delete a file another program holds open")
class BriefHoldTests(_Base):
    def test_a_brief_hold_on_a_file_is_waited_for_and_the_move_completes(self) -> None:
        source = self._file("staged/clip.wav")
        data = source.read_bytes()
        destination = self.root / "final" / "clip.wav"
        with OutsideHolder(source) as holder:
            pauses = Pauses(at=2, on=holder.release)
            safe_write.move(source, destination, pause=pauses)
        self.assertEqual(len(pauses.taken), 2, "it let go during the second pause; the next try worked")
        self.assertEqual(destination.read_bytes(), data)
        self.assertFalse(source.exists())

    def test_a_folder_rename_blocked_by_one_file_inside_it_waits_and_completes(self) -> None:
        folder = self._folder("stage")
        before = _tree(folder)
        destination = self.root / "promoted"
        with OutsideHolder(folder / "sub" / "deeper.json") as holder:
            pauses = Pauses(at=2, on=holder.release)
            safe_write.move(folder, destination, pause=pauses)
        self.assertEqual(len(pauses.taken), 2)
        self.assertEqual(_tree(destination), before)
        self.assertFalse(folder.exists())

    def test_a_disposable_folder_held_briefly_is_removed(self) -> None:
        folder = self._folder("scratch/attempt-1")
        with OutsideHolder(folder / "inner.txt") as holder:
            pauses = Pauses(at=2, on=holder.release)
            safe_write.remove_disposable_tree(folder, within=self.root / "scratch", pause=pauses)
        self.assertFalse(folder.exists())
        self.assertEqual([path.name for path in (self.root / "scratch").iterdir()], [], "no trash folder is left")

    def test_a_file_a_scan_holds_for_deletion_is_waited_for_and_its_folder_removed(self) -> None:
        # A virus scan often opens a file allowing it to be deleted; Windows then refuses to rename its folder
        # until the scan lets go.
        folder = self._folder("scratch/attempt-5")
        with OutsideHolder(folder / "sub" / "deeper.json", share_delete=True) as holder:
            pauses = Pauses(at=2, on=holder.release)
            safe_write.remove_disposable_tree(folder, within=self.root / "scratch", pause=pauses)
        self.assertFalse(folder.exists())
        self.assertEqual([path.name for path in (self.root / "scratch").iterdir()], [], "no trash folder is left")

    def test_the_ledger_swap_waits_for_a_brief_hold_and_keeps_the_old_file_as_its_backup(self) -> None:
        ledger = self._file("inbox/review-ledger.sqlite", b"old ledger")
        note = self._file("inbox/note.tmp", b"a short note")
        with OutsideHolder(ledger) as holder:
            pauses = Pauses(at=2, on=holder.release)
            backup = safe_write.replace_file(ledger, note, "review-ledger.sqlite.moved", pause=pauses)
        self.assertEqual(ledger.read_bytes(), b"a short note")
        self.assertEqual(backup.read_bytes(), b"old ledger")
        self.assertFalse(note.exists())


@unittest.skipUnless(WINDOWS, "Windows refuses to rename or delete a file another program holds open")
class DeadlineTests(_Base):
    def test_a_hold_past_the_deadline_names_the_program_and_leaves_every_byte_where_it_was(self) -> None:
        source = self._file("staged/clip.wav")
        data = source.read_bytes()
        destination = self.root / "final" / "clip.wav"
        pauses = Pauses()
        with OutsideHolder(source, forever=True) as holder:
            with self.assertRaises(safe_write.FileInUse) as refused:
                safe_write.move(source, destination, pause=pauses)
        message = str(refused.exception)
        self.assertIn("clip.wav could not be moved because", message)
        self.assertIn(f"(process {holder.pid}) has it open", message)
        self.assertIn("Nothing was lost.", message)
        self.assertAlmostEqual(sum(pauses.taken), safe_write.INBOX_WAIT_SECONDS)
        self.assertEqual(pauses.taken[:5], [0.05, 0.1, 0.2, 0.4, 0.8], "quick at first, then once a second")
        self.assertEqual(source.read_bytes(), data)
        self.assertFalse(destination.exists())

    def test_a_folder_held_past_the_deadline_stays_whole_under_its_own_name(self) -> None:
        folder = self._folder("batch/sources/abc")
        before = _tree(folder)
        with OutsideHolder(folder / "inner.txt", forever=True) as holder:
            with self.assertRaises(safe_write.FileInUse) as refused:
                safe_write.move(folder, self.root / "history" / "abc", pause=Pauses())
        self.assertIn(f"(process {holder.pid})", str(refused.exception))
        self.assertEqual(_tree(folder), before)
        self.assertFalse((self.root / "history" / "abc").exists())

    def test_a_disposable_folder_still_held_is_noted_and_removed_at_the_next_run(self) -> None:
        scratch = self.root / "scratch"
        folder = self._folder("scratch/attempt-2")
        leftovers = self.root / ".orchestration" / "leftovers.json"
        with OutsideHolder(folder / "inner.txt", forever=True) as holder:
            with self.assertRaises(safe_write.FileInUse) as refused:
                safe_write.remove_disposable_tree(folder, within=scratch, pause=Pauses(), leftovers=leftovers)
            self.assertIn(f"(process {holder.pid})", str(refused.exception))
            self.assertTrue(folder.is_dir(), "a hold on the rename leaves the folder whole")
            # Still held at the next run: kept on the list, with a plain line saying so.
            still = safe_write.sweep_leftovers(leftovers, pause=Pauses())
            self.assertEqual(len(still), 1)
            self.assertTrue(folder.is_dir())
        # Let go: the next run removes it, and the list.
        self.assertEqual(safe_write.sweep_leftovers(leftovers), [])
        self.assertFalse(folder.exists())
        self.assertFalse(leftovers.exists())

    def test_the_ledger_swap_held_past_the_deadline_changes_neither_file(self) -> None:
        ledger = self._file("inbox/review-ledger.sqlite", b"old ledger")
        note = self._file("inbox/note.tmp", b"a short note")
        with OutsideHolder(ledger, forever=True) as holder:
            with self.assertRaises(safe_write.FileInUse) as refused:
                safe_write.replace_file(ledger, note, "review-ledger.sqlite.moved", pause=Pauses())
        self.assertIn(f"(process {holder.pid})", str(refused.exception))
        self.assertEqual(ledger.read_bytes(), b"old ledger")
        self.assertEqual(note.read_bytes(), b"a short note")
        self.assertFalse((self.root / "inbox" / "review-ledger.sqlite.moved").exists())


@unittest.skipUnless(WINDOWS, "Windows refuses to rename or delete a file another program holds open")
class TheAppNeverWaitsForItselfTests(_Base):
    def test_a_file_the_app_itself_holds_stops_at_once(self) -> None:
        source = self._file("staged/clip.wav")
        pauses = Pauses()
        with open(source, "rb"):
            with self.assertRaises(safe_write.FileInUse) as refused:
                safe_write.move(source, self.root / "final.wav", pause=pauses)
        self.assertEqual(pauses.taken, [], "it did not wait")
        self.assertIn("The app itself still has clip.wav open, so it did not wait. Nothing was moved or removed. "
                      "This is a fault in the app.", str(refused.exception))
        self.assertTrue(source.is_file())

    def test_a_program_the_app_started_counts_as_the_app(self) -> None:
        source = self._file("staged/clip.wav")
        pauses = Pauses()
        with OutsideHolder(source, outside=False):
            with self.assertRaises(safe_write.FileInUse) as refused:
                safe_write.move(source, self.root / "final.wav", pause=pauses)
        self.assertEqual(pauses.taken, [])
        self.assertIn("The app itself still has clip.wav open", str(refused.exception))

    def test_the_workbench_that_started_the_helper_counts_as_the_app_only_with_its_own_start_time(self) -> None:
        source = self._file("staged/clip.wav")
        with OutsideHolder(source, forever=True) as holder:
            started = safe_write._process_start_time(holder.pid)
            self.assertTrue(started)
            # The holder stands in for the Workbench that started this helper.
            with mock.patch.dict(os.environ, {safe_write.APP_PROCESS_VARIABLE: f"{holder.pid}:{started}"}):
                pauses = Pauses()
                with self.assertRaises(safe_write.FileInUse) as refused:
                    safe_write.move(source, self.root / "final.wav", pause=pauses)
                self.assertEqual(pauses.taken, [])
                self.assertIn("The app itself", str(refused.exception))
            # The same process number with another start time is a different program that got the number later.
            with mock.patch.dict(os.environ, {safe_write.APP_PROCESS_VARIABLE: f"{holder.pid}:{started + 1}"}):
                pauses = Pauses()
                with self.assertRaises(safe_write.FileInUse) as refused:
                    safe_write.move(source, self.root / "final.wav", pause=pauses)
                self.assertAlmostEqual(sum(pauses.taken), safe_write.INBOX_WAIT_SECONDS)
                self.assertIn(f"(process {holder.pid}) has it open", str(refused.exception))

    def test_a_removal_the_app_itself_blocks_stops_at_once_too(self) -> None:
        target = self._file("inbox/review-ledger.sqlite", b"x")
        with open(target, "rb"):
            with self.assertRaises(safe_write.FileInUse) as refused:
                safe_write.remove(target, wait=safe_write.INBOX_WAIT_SECONDS, pause=Pauses())
        self.assertIn("The app itself still has review-ledger.sqlite open", str(refused.exception))
        self.assertTrue(target.exists())


class TheWorkbenchNamesItselfTests(unittest.TestCase):
    def test_the_workbench_passes_its_process_number_and_start_time_to_what_it_starts(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(safe_write.APP_PROCESS_VARIABLE, None)
            safe_write.mark_app_process()
            value = os.environ[safe_write.APP_PROCESS_VARIABLE]
        pid, _sep, started = value.partition(":")
        self.assertEqual(int(pid), os.getpid())
        if WINDOWS:
            self.assertEqual(int(started), safe_write._process_start_time(os.getpid()))

    def test_the_workbench_does_it_first_when_it_starts(self) -> None:
        import ast  # noqa: PLC0415

        source = (Path(__file__).resolve().parents[1] / "src" / "media_manglers_workbench" / "app.py").read_text(
            encoding="utf-8")
        main = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == "main")
        calls = [ast.unparse(node.value) for node in main.body if isinstance(node, ast.Expr)]
        self.assertEqual(calls[0], "safe_write.mark_app_process()")


class OtherErrorsFailAtOnceTests(_Base):
    def test_a_path_that_is_not_there_fails_at_once_in_plain_words(self) -> None:
        pauses = Pauses()
        with self.assertRaises(safe_write.FileStepRefused) as refused:
            safe_write.move(self.root / "missing.wav", self.root / "final.wav", pause=pauses)
        self.assertEqual(pauses.taken, [])
        self.assertIn("missing.wav could not be moved: it is not there. Nothing was moved.", str(refused.exception))

    def test_a_refusal_that_is_not_a_hold_is_not_waited_for(self) -> None:
        source = self._file("staged/clip.wav")
        pauses = Pauses()
        refusal = OSError(2, "The system cannot find the path specified", str(source), 3)
        with mock.patch("os.rename", side_effect=refusal):
            with self.assertRaises(safe_write.FileStepRefused) as refused:
                safe_write.move(source, self.root / "final.wav", pause=pauses)
        self.assertEqual(pauses.taken, [])
        self.assertIn("clip.wav could not be moved: Windows refused it (The system cannot find the path specified)",
                      str(refused.exception))
        self.assertTrue(source.is_file())

    def test_nothing_is_ever_written_over(self) -> None:
        source = self._file("a.wav", b"new")
        destination = self._file("b.wav", b"old")
        with self.assertRaises(safe_write.FileStepRefused):
            safe_write.move(source, destination)
        self.assertEqual(destination.read_bytes(), b"old")
        self.assertEqual(source.read_bytes(), b"new")

    def test_a_disposable_removal_never_reaches_outside_its_folder(self) -> None:
        folder = self._folder("keep")
        with self.assertRaises(safe_write.FileStepRefused):
            safe_write.remove_disposable_tree(folder, within=self.root / "scratch")
        with self.assertRaises(safe_write.FileStepRefused):
            safe_write.remove_disposable_tree(self.root / "scratch", within=self.root / "scratch")
        self.assertTrue((folder / "inner.txt").is_file())

    def test_a_file_moving_to_another_drive_is_copied_checked_and_only_then_removed(self) -> None:
        source = self._file("staged/clip.wav")
        data = source.read_bytes()
        destination = self.root / "other" / "clip.wav"
        removed_after: list[bool] = []
        real_remove = safe_write.remove

        def remove(path, **kwargs):
            removed_after.append(destination.is_file() and destination.read_bytes() == data)
            return real_remove(path, **kwargs)

        with mock.patch.object(safe_write, "_same_drive", return_value=False), \
                mock.patch.object(safe_write, "remove", side_effect=remove):
            safe_write.move(source, destination)
        self.assertEqual(removed_after, [True], "the original went only once the checked copy was in place")
        self.assertEqual(destination.read_bytes(), data)
        self.assertFalse(source.exists())
        self.assertEqual(sorted(path.name for path in destination.parent.iterdir()), ["clip.wav"])

    def test_a_copy_to_another_drive_that_does_not_match_is_never_kept(self) -> None:
        source = self._file("staged/clip.wav")
        data = source.read_bytes()
        destination = self.root / "other" / "clip.wav"
        real_hash = safe_write._sha256
        with mock.patch.object(safe_write, "_same_drive", return_value=False), \
                mock.patch.object(safe_write, "_sha256", side_effect=lambda path: "x" if ".partial" in str(path)
                                  else real_hash(path)):
            with self.assertRaises(safe_write.FileStepRefused):
                safe_write.move(source, destination)
        self.assertEqual(source.read_bytes(), data)
        self.assertEqual(list(destination.parent.iterdir()), [])

    def test_a_folder_is_never_moved_to_another_drive(self) -> None:
        folder = self._folder("stage")
        with mock.patch.object(safe_write, "_same_drive", return_value=False):
            with self.assertRaises(safe_write.FileStepRefused):
                safe_write.move(folder, self.root / "other" / "stage")
        self.assertTrue((folder / "inner.txt").is_file())


@unittest.skipUnless(WINDOWS, "Windows refuses to delete a folder while a file in it waits to be deleted")
class CleanUpAfterSuccessTests(_Base):
    """Decision 3: a clean-up after a step succeeded never undoes the result, whatever Windows refuses."""

    def test_a_folder_a_scan_still_holds_for_deletion_is_noted_for_the_next_run(self) -> None:
        folder = self._folder("scratch/attempt-6")
        leftovers = self.root / ".orchestration" / "leftovers.json"
        with OutsideHolder(folder / "sub" / "deeper.json", share_delete=True, forever=True):
            with self.assertRaises(safe_write.FileInUse):
                safe_write.remove_disposable_tree(folder, within=self.root / "scratch", pause=Pauses(),
                                                  leftovers=leftovers)
        self.assertEqual(safe_write.sweep_leftovers(leftovers), [])
        self.assertEqual([path.name for path in (self.root / "scratch").iterdir()], [], "removed at the next run")

    def _not_empty(self, times: int):
        """``shutil.rmtree`` as it goes while a scan holds a file waiting to be deleted: Windows answers "the
        directory is not empty" (error 145) ``times`` times, then the delete completes."""

        real = shutil.rmtree
        calls = [0]

        def rmtree(path, *args, **options):
            calls[0] += 1
            if calls[0] <= times:
                raise OSError(None, "The directory is not empty", str(path), 145)
            return real(path, *args, **options)

        return rmtree

    def test_the_directory_is_not_empty_while_a_delete_completes_is_a_hold(self) -> None:
        # 224 (Wave B2a review): the folder was already renamed to its trash name; deleting it waits for the scan.
        folder = self._folder("scratch/attempt-7")
        pauses = Pauses()
        with mock.patch.object(safe_write.shutil, "rmtree", side_effect=self._not_empty(2)):
            safe_write.remove_disposable_tree(folder, within=self.root / "scratch", pause=pauses)
        self.assertEqual(len(pauses.taken), 2, "waited, then the delete completed")
        self.assertEqual([path.name for path in (self.root / "scratch").iterdir()], [])

    def test_a_trash_folder_still_not_empty_at_the_deadline_is_noted_and_said_truly(self) -> None:
        folder = self._folder("scratch/attempt-8")
        leftovers = self.root / ".orchestration" / "leftovers.json"
        with mock.patch.object(safe_write.shutil, "rmtree", side_effect=self._not_empty(10_000)), \
                mock.patch.object(safe_write, "holders", return_value=[]):
            with self.assertRaises(safe_write.FileInUse) as held:
                safe_write.remove_disposable_tree(folder, within=self.root / "scratch", pause=Pauses(),
                                                  leftovers=leftovers)
        self.assertNotIn("Nothing was moved or removed", str(held.exception), "it was set aside already")
        self.assertEqual(safe_write.sweep_leftovers(leftovers), [])
        self.assertEqual([path.name for path in (self.root / "scratch").iterdir()], [], "removed at the next run")

    def test_preparation_and_finalization_warn_for_any_refused_clean_up_and_carry_on(self) -> None:
        from media_manglers.core import review_finalization, review_preparation  # noqa: PLC0415

        refused = safe_write.FileStepRefused(
            "trash could not be removed: Windows refused it (The directory is not empty). (scratch)")
        warnings: list[str] = []
        with mock.patch.object(safe_write, "remove_disposable_tree", side_effect=refused):
            said = review_preparation._tidy(self.root, self.root / "attempt", None, warnings)
            review_finalization._tidy({"ledger_path": str(self.root / "review-ledger.sqlite")}, {}, self.root,
                                      self.root / "quarantine", warnings)
        self.assertTrue(said.startswith("The result was kept."), said)
        self.assertEqual(len(warnings), 2)
        self.assertTrue(all("Windows refused it" in warning for warning in warnings))


class TrashLeftByACrashTests(_Base):
    """A crash in the middle of deleting a trash folder leaves it under its trash name, on no leftovers list; the
    next clean-up in that folder removes it (224, Wave B2a, approved after Stage 1)."""

    def _crash_leftover(self, parent: str) -> Path:
        # What a delete cut short by a crash leaves: the renamed folder, partly emptied.
        trash = self._folder(f"{parent}/{safe_write.TRASH_PREFIX}0123456789ab")
        (trash / "inner.txt").unlink()
        return trash

    def test_the_next_clean_up_beside_it_removes_a_trash_folder_a_crash_left(self) -> None:
        scratch = self.root / "scratch"
        trash = self._crash_leftover("scratch/batch")
        attempt = self._folder("scratch/batch/attempt-3")
        keep = self._file("scratch/batch/attempt-4/inner.txt")
        safe_write.remove_disposable_tree(attempt, within=scratch, pause=Pauses())
        self.assertFalse(attempt.exists())
        self.assertFalse(trash.exists(), "the trash folder the crash left is gone too")
        self.assertTrue(keep.is_file(), "a real folder beside it is never touched")

    def test_a_clean_up_of_something_already_gone_still_sweeps_beside_it(self) -> None:
        scratch = self.root / "scratch"
        trash = self._crash_leftover("scratch/batch")
        safe_write.remove_disposable_tree(scratch / "batch" / "attempt-9", within=scratch, pause=Pauses())
        self.assertFalse(trash.exists())

    def test_only_trash_names_inside_its_folder_are_swept(self) -> None:
        scratch = self.root / "scratch"
        outside = self._crash_leftover("elsewhere")
        lookalike = self._folder("scratch/batch/mm-trash-but-real-data")
        attempt = self._folder("scratch/batch/attempt-3")
        safe_write.remove_disposable_tree(attempt, within=scratch, pause=Pauses())
        self.assertTrue(outside.is_dir(), "never outside the folder it cleans")
        self.assertTrue((lookalike / "inner.txt").is_file(), "only the app's own trash names")

    @unittest.skipUnless(WINDOWS, "Windows refuses to delete a file another program holds open")
    def test_a_trash_folder_another_program_holds_is_noted_and_never_fails_the_clean_up(self) -> None:
        scratch = self.root / "scratch"
        trash = self._crash_leftover("scratch/batch")
        attempt = self._folder("scratch/batch/attempt-3")
        leftovers = self.root / ".orchestration" / "leftovers.json"
        with OutsideHolder(trash / "sub" / "deeper.json", forever=True):
            safe_write.remove_disposable_tree(attempt, within=scratch, pause=Pauses(), leftovers=leftovers)
            self.assertFalse(attempt.exists(), "the clean-up itself went ahead")
            self.assertTrue(trash.is_dir())
        self.assertEqual(safe_write.sweep_leftovers(leftovers), [])
        self.assertFalse(trash.exists(), "removed at the next run once let go")


if __name__ == "__main__":
    unittest.main()
