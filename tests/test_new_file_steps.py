"""Installer plan, Stage 2: every new file step follows the antivirus rules, proven with simulated holds.

The holds come from ``tests/outside_holder.py``, a separate program that opens files the way a virus scanner, the
search indexer or Explorer does; real antivirus is never relied on. Where a test needs the exact limits (ten
seconds per file, thirty per step) the budget runs on a test clock that moves by exactly each pause, so the limits
are proven with a real hold without the suite waiting that long; the real-clock cases prove the waiting is real.
"""

from __future__ import annotations

import ast
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from media_manglers.core import app_locks, file_steps, safe_write, user_folders  # noqa: E402
from media_manglers.core.safe_write import (  # noqa: E402
    FileInUse,
    FileStepRefused,
    Holder,
    StepBudget,
)
from outside_holder import OutsideHolder  # noqa: E402

# Words no message may contain: no advice to exclude a folder, allow a program, or switch protection off.
FORBIDDEN_ADVICE = ("exclu", "allow list", "allowlist", "whitelist", "turn off", "switch off", "disable",
                    "real-time protection", "antivirus setting", "defender setting")


class StepClock:
    """Moves only when the wait pauses, by exactly the pause."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.pauses: list[float] = []

    def __call__(self) -> float:
        return self.now

    def pause(self, seconds: float) -> None:
        self.pauses.append(seconds)
        self.now += seconds


class FileStepCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        for path in self.root.rglob("*"):
            try:
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            except OSError:
                pass
        self.temp.cleanup()

    def _file(self, relative: str, text: str = "data") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class BudgetTests(FileStepCase):
    def test_the_limits_are_ten_seconds_per_file_and_thirty_per_step(self) -> None:
        budget = StepBudget()
        self.assertEqual((budget.per_file, budget.per_step), (10.0, 30.0))
        self.assertEqual((safe_write.NEW_STEP_FILE_SECONDS, safe_write.NEW_STEP_SECONDS), (10.0, 30.0))

    def test_a_file_held_past_ten_seconds_by_the_clock_stops_naming_the_program(self) -> None:
        target = self._file("addons/sp-1/torch/lib.dll")
        clock = StepClock()
        with OutsideHolder(target, forever=True) as holder:
            with self.assertRaises(FileInUse) as caught:
                safe_write.remove(target, budget=StepBudget(clock=clock), pause=clock.pause)
        self.assertAlmostEqual(clock.now - 1000.0, 10.0, places=6)
        self.assertTrue(target.exists(), "nothing was lost")
        self.assertIn(holder.pid, [found.pid for found in caught.exception.holders])
        self.assertEqual({found.kind for found in caught.exception.holders}, {"program"})
        self.assertIn(f"(process {holder.pid})", str(caught.exception))
        self.assertIn("Nothing was lost", str(caught.exception))

    def test_the_whole_step_stops_at_thirty_seconds_by_the_clock(self) -> None:
        files = [self._file(f"set/file{index}.bin") for index in range(4)]
        clock = StepClock()
        budget = StepBudget(clock=clock)
        holders = [OutsideHolder(path, forever=True) for path in files]
        try:
            waited = []
            for path in files:
                before = clock.now
                with self.assertRaises(FileInUse):
                    safe_write.remove(path, budget=budget, pause=clock.pause)
                waited.append(round(clock.now - before, 6))
        finally:
            for holder in holders:
                holder.close()
        # Ten seconds each for the first three files; the step's thirty are then used up, so the fourth stops
        # without waiting.
        self.assertEqual(waited, [10.0, 10.0, 10.0, 0.0])
        self.assertTrue(all(path.exists() for path in files))

    def test_a_brief_hold_is_waited_for_by_the_real_clock_and_the_step_completes(self) -> None:
        target = self._file("download/model.pt.partial")
        with OutsideHolder(target, seconds=1.5):
            started = time.monotonic()
            safe_write.remove(target, budget=StepBudget())
            elapsed = time.monotonic() - started
        self.assertFalse(target.exists())
        self.assertGreater(elapsed, 0.5, "it really waited")
        self.assertLess(elapsed, 10.0)

    def test_a_hold_that_never_ends_stops_by_the_real_clock(self) -> None:
        target = self._file("download/model.pt.partial")
        with OutsideHolder(target, forever=True):
            started = time.monotonic()
            with self.assertRaises(FileInUse):
                safe_write.remove(target, budget=StepBudget(per_file=1.5, per_step=3.0))
            elapsed = time.monotonic() - started
        # Measured by the clock: Restart Manager's question and the pauses together, not only the pauses.
        self.assertGreaterEqual(elapsed, 1.4)
        self.assertLess(elapsed, 4.0)

    def test_every_file_of_a_large_folder_is_asked_about(self) -> None:
        # An older step asks about the first 512 files only; a new step asks about all of them.
        folder = self.root / "addons" / "sp-1"
        for index in range(700):
            self._file(f"addons/sp-1/pkg/{index:04d}.py", "x")
        held = folder / "pkg" / "0690.py"
        # The real clock: Windows is asked beside the step, and needs real time to answer about 700 files.
        with OutsideHolder(held, forever=True) as holder:
            with self.assertRaises(FileInUse) as caught:
                safe_write.remove_disposable_tree(folder, within=self.root, budget=StepBudget(per_file=4.0,
                                                                                              per_step=4.0))
        self.assertIn(holder.pid, [found.pid for found in caught.exception.holders])
        self.assertEqual(len(list(folder.rglob("*.py"))), 700, "the folder stays whole under its own name")


class StopAtOnceTests(FileStepCase):
    def test_a_read_only_file_stops_at_once(self) -> None:
        target = self._file("addons/sp-1/readme.txt")
        os.chmod(target, stat.S_IREAD)
        clock = StepClock()
        with self.assertRaises(FileStepRefused) as caught:
            safe_write.remove(target, budget=StepBudget(clock=clock), pause=clock.pause)
        self.assertEqual(clock.pauses, [], "no wait")
        self.assertIn("read-only", str(caught.exception))
        self.assertTrue(target.exists())

    def test_another_read_only_file_in_the_folder_does_not_stop_a_real_hold_early(self) -> None:
        folder = self.root / "addons" / "sp-1"
        notes = self._file("addons/sp-1/notes.txt")
        os.chmod(notes, stat.S_IREAD)
        held = self._file("addons/sp-1/torch.dll")
        clock = StepClock()
        reached: list[int | None] = []
        real_rule = safe_write._read_only_path

        def spy(exc: OSError, paths: list[Path]) -> Path | None:
            reached.append(getattr(exc, "winerror", None))
            return real_rule(exc, paths)

        # M9 of the Wave I-A review: a file inside the folder is held (not the folder's own handle), so Windows
        # answers "access denied" and the read-only rule is really reached, and must still not stop the wait.
        with OutsideHolder(held, forever=True) as holder, mock.patch.object(safe_write, "_read_only_path",
                                                                             side_effect=spy):
            with self.assertRaises(FileInUse):
                safe_write.rename_into_place(folder, self.root / "addons" / "sp-2", budget=StepBudget(clock=clock),
                                             pause=clock.pause)
        self.assertIn(5, reached, "Windows said access denied, so the read-only rule looked at the refusal")
        self.assertAlmostEqual(clock.now - 1000.0, 10.0, places=6, msg="it waited the full ten seconds")
        self.assertTrue(held.exists() and notes.exists())
        self.assertIsNotNone(holder.pid)

    def test_a_read_only_file_being_replaced_stops_at_once(self) -> None:
        # M9: replacing a damaged model that is marked read-only; Windows names the target second (filename2).
        partial = self._file("cache/medium.pt.partial", "weights")
        target = self._file("cache/medium.pt", "damaged")
        os.chmod(target, stat.S_IREAD)
        clock = StepClock()
        with self.assertRaises(FileStepRefused) as caught:
            safe_write.place_checked(partial, target, hashlib.sha256(b"weights").hexdigest(), replace=True,
                                     budget=StepBudget(clock=clock), pause=clock.pause)
        self.assertEqual(clock.pauses, [], "no wait")
        self.assertIn("medium.pt could not be put in place: it is marked read-only", str(caught.exception))
        self.assertEqual(target.read_text(encoding="utf-8"), "damaged")
        self.assertTrue(partial.exists(), "nothing was lost")

    def test_an_own_hold_that_begins_after_the_first_refusal_still_stops_at_once(self) -> None:
        # M9: another program held it at the first refusal; then the app itself took it. Asked again, it stops.
        target = self._file("cache/medium.pt")
        clock = StepClock()
        answers = iter([[(4242, 1, "Scanner", "", 0)]])
        refusal = OSError(errno.EACCES, "The process cannot access the file", str(target), 32)

        def refuse() -> None:
            raise refusal

        with mock.patch.object(safe_write, "_holder_details",
                               side_effect=lambda _paths: next(answers, [(os.getpid(), 1, "python.exe", "", 0)])), \
                mock.patch.object(safe_write, "_program_file", return_value="scan.exe"):
            with self.assertRaises(FileInUse) as caught:
                safe_write._with_budget(refuse, [target], "removed", StepBudget(clock=clock), clock.pause,
                                        source=target)
        self.assertIn("fault in the app", str(caught.exception))
        self.assertLess(clock.now - 1000.0, 10.0, "it did not wait out the ten seconds for its own hold")

    def test_the_message_names_the_file_that_is_really_held(self) -> None:
        # M9: an approved download replacing a damaged model, whose old file another program holds.
        partial = self._file("cache/medium.pt.partial", "weights")
        target = self._file("cache/medium.pt", "damaged")
        clock = StepClock()
        with OutsideHolder(target, forever=True) as holder:
            with self.assertRaises(FileInUse) as caught:
                safe_write.place_checked(partial, target, hashlib.sha256(b"weights").hexdigest(), replace=True,
                                         budget=StepBudget(clock=clock), pause=clock.pause)
        text = str(caught.exception)
        self.assertTrue(text.startswith("medium.pt could not be put in place because "), text)
        self.assertIn(f"(process {holder.pid}) has it open", text)
        self.assertTrue(partial.exists() and target.read_text(encoding="utf-8") == "damaged", "nothing was lost")

    def test_a_file_the_app_itself_holds_stops_at_once(self) -> None:
        target = self._file("addons/sp-1/torch.dll")
        clock = StepClock()
        with open(target, "rb"):  # Python opens files with no delete sharing on Windows
            with self.assertRaises(FileInUse) as caught:
                safe_write.remove(target, budget=StepBudget(clock=clock), pause=clock.pause)
        self.assertEqual(clock.pauses, [])
        self.assertIn("fault in the app", str(caught.exception))
        self.assertEqual({found.kind for found in caught.exception.holders}, {"app"})


class MessageTests(unittest.TestCase):
    target = Path(r"C:\Users\Someone\AppData\Local\MediaManglers\addons\sp-1\torch\lib\torch_cpu.dll")

    def test_each_kind_of_holder_gets_its_own_plain_words(self) -> None:
        program = safe_write.new_step_held_message(self.target, "removed", [Holder(4, "Scanner", "program")])
        self.assertIn("because Scanner (process 4) has it open", program)
        # H3 of the Wave I-A review: Windows reports some virus scanners as ordinary programs, so a program is
        # never told to be closed; the step waited, and the message says to wait and try again.
        self.assertIn("Wait a moment", program)
        self.assertNotIn("close", program.casefold())
        service = safe_write.new_step_held_message(self.target, "removed",
                                                   [Holder(7, "Windows Search", "service", "WSearch")])
        self.assertIn("the Windows service Windows Search (process 7)", service)
        self.assertIn("Wait a moment", service)
        workbench = safe_write.new_step_held_message(self.target, "removed",
                                                     [Holder(9, "Media Manglers", "workbench")])
        self.assertIn("Media Manglers is still running", workbench)
        self.assertIn("Close Media Manglers", workbench)
        unknown = safe_write.new_step_held_message(self.target, "removed", [])
        self.assertIn("Windows did not say which", unknown)
        for text in (program, service, workbench, unknown):
            self.assertIn("Nothing was lost", text)

    def test_holders_are_sorted_into_kinds(self) -> None:
        details = [(11, 1, "Windows Search", "WSearch", 3), (12, 1, "Media Manglers", "", 1), (13, 1, "Scanner", "", 1)]
        with mock.patch.object(safe_write, "_holder_details", return_value=details), \
                mock.patch.object(safe_write, "_is_app", return_value=False), \
                mock.patch.object(safe_write, "_program_file",
                                  side_effect=lambda pid: "VideoManglerWorkbench.exe" if pid == 12 else "scan.exe"):
            found = safe_write.holder_list([self.target])
        self.assertEqual([(holder.pid, holder.kind) for holder in found],
                         [(11, "service"), (12, "workbench"), (13, "program")])

    def test_no_message_ever_advises_an_exclusion_or_turning_protection_off(self) -> None:
        texts = [safe_write.new_step_held_message(self.target, done, holders)
                 for done in ("removed", "moved", "put in place")
                 for holders in ([], [Holder(1, "A", "program")], [Holder(2, "B", "service", "b")],
                                 [Holder(3, "C", "workbench")])]
        texts.append(str(safe_write._read_only_refusal(self.target, "removed")))
        texts.append(safe_write._own_message(self.target, "removed"))
        texts.append(safe_write._held_message(self.target, "removed", [self.target]))
        # Every string written in the file-step code, too (its descriptions, which say the rule, aside).
        for module in (safe_write, file_steps, app_locks):
            tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
            described = {id(node.body[0].value) for node in ast.walk(tree)
                         if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body
                         and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
            texts += [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
                      and isinstance(node.value, str) and id(node) not in described]
        for text in texts:
            lowered = text.casefold()
            for word in FORBIDDEN_ADVICE:
                self.assertNotIn(word, lowered, text)


class NewStepTests(FileStepCase):
    def test_a_download_is_put_in_place_only_after_its_checksum_matches(self) -> None:
        import hashlib

        partial = self._file("cache/base.en.pt.mm-partial", "model bytes")
        good = hashlib.sha256(b"model bytes").hexdigest()
        target = self.root / "cache" / "base.en.pt"
        with self.assertRaises(safe_write.DownloadNotChecked):
            safe_write.place_checked(partial, target, "0" * 64)
        self.assertFalse(partial.exists(), "a download that does not match is removed")
        self.assertFalse(target.exists(), "and never looks like the real file")
        partial = self._file("cache/base.en.pt.mm-partial", "model bytes")
        safe_write.place_checked(partial, target, good)
        self.assertEqual(target.read_text(encoding="utf-8"), "model bytes")
        # Never written over, unless the caller replaces a damaged copy after approval.
        again = self._file("cache/base.en.pt.mm-partial", "model bytes")
        with self.assertRaises(FileStepRefused):
            safe_write.place_checked(again, target, good)
        target.write_text("damaged", encoding="utf-8")
        safe_write.place_checked(again, target, good, replace=True)
        self.assertEqual(target.read_text(encoding="utf-8"), "model bytes")

    def test_a_scanner_opening_every_new_file_slows_the_steps_but_loses_nothing(self) -> None:
        import hashlib

        addons = self.root / "addons"
        addons.mkdir()
        with OutsideHolder(addons, watch_folder=True, hold_ms=300) as scanner:
            # A speech-library set built under a temporary name, as Stage 4's setup will, then renamed into place.
            building = addons / "sp-1.tmp"
            for index in range(5):
                path = building / "pkg" / f"module{index}.py"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"value = {index}\n", encoding="utf-8")
            # The scanner has its hands on the new files before the rename, however busy the PC is.
            scanner.wait_opened()
            safe_write.rename_into_place(building, addons / "sp-1", budget=StepBudget())
            # A download checked and put in place while the scanner holds it.
            partial = addons / "model.mm-partial"
            partial.write_bytes(b"weights")
            safe_write.place_checked(partial, addons / "model.pt", hashlib.sha256(b"weights").hexdigest(),
                                     budget=StepBudget())
            # And an older set removed.
            old = addons / "sp-0"
            (old / "pkg").mkdir(parents=True)
            (old / "pkg" / "old.py").write_text("old = 1\n", encoding="utf-8")
            safe_write.remove_disposable_tree(old, within=addons, budget=StepBudget())
            scanner.release()
        self.assertGreater(scanner.scanned, 0, "the scanner really opened the new files")
        self.assertEqual(sorted(path.name for path in (addons / "sp-1" / "pkg").iterdir()),
                         [f"module{index}.py" for index in range(5)])
        self.assertEqual((addons / "model.pt").read_bytes(), b"weights")
        self.assertFalse(old.exists())
        self.assertFalse(any(path.name.startswith(safe_write.TRASH_PREFIX) for path in addons.iterdir()))


class FileStepCommandTests(FileStepCase):
    def _command(self, *args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src"),
               user_folders.WORKBENCH_LOCALAPPDATA_ENV: str(self.root / "local")}
        return subprocess.run([sys.executable, "-m", "media_manglers", "file-step", *args], capture_output=True,
                              text=True, timeout=timeout, env=env, cwd=str(self.root), check=False)

    def test_remove_addons_takes_its_folder_from_addons_root_and_removes_it(self) -> None:
        with mock.patch.dict(os.environ, {user_folders.WORKBENCH_LOCALAPPDATA_ENV: str(self.root / "local")}):
            addons = user_folders.addons_root()
        keep = self._file("local/MediaManglers/Workbench/library/keep.txt", "your library")
        self._file("local/MediaManglers/addons/sp-1/torch/__init__.py")
        run = self._command("remove-addons")
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertTrue(result["ok"])
        self.assertEqual(Path(result["data"]["path"]), addons)
        self.assertFalse(addons.exists())
        self.assertEqual(keep.read_text(encoding="utf-8"), "your library", "data is never touched")
        again = self._command("remove-addons")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertFalse(json.loads(again.stdout.strip().splitlines()[-1])["data"]["removed"])

    def test_remove_addons_held_by_another_program_waits_ten_seconds_then_names_it(self) -> None:
        held = self._file("local/MediaManglers/addons/sp-1/torch/lib/torch_cpu.dll")
        result_file = self.root / "result.json"
        with OutsideHolder(held, forever=True) as holder:
            started = time.monotonic()
            run = self._command("remove-addons", "--result-file", str(result_file), timeout=90)
            elapsed = time.monotonic() - started
        self.assertEqual(run.returncode, 2, run.stderr)
        result = json.loads(result_file.read_text(encoding="utf-8"))
        self.assertFalse(result["ok"])
        self.assertIn(holder.pid, [item["pid"] for item in result["data"]["holders"]])
        self.assertIn(f"(process {holder.pid})", result["error"])
        self.assertTrue(held.exists(), "nothing was lost")
        # The real default budget: ten seconds for the file, by the clock (plus the program's own start-up).
        self.assertGreaterEqual(elapsed, 9.5)
        self.assertLess(elapsed, 30.0)

    def test_remove_addons_finishes_what_an_interrupted_removal_left(self) -> None:
        # M10 of the Wave I-A review: a removal cut short leaves the add-ons under a trash name beside their folder.
        trash = self._file(f"local/MediaManglers/{safe_write.TRASH_PREFIX}0123456789ab/torch/lib.dll").parents[1]
        keep = self._file("local/MediaManglers/Workbench/library/keep.txt", "your library")
        run = self._command("remove-addons")
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertTrue(result["data"]["removed"], result)
        self.assertNotIn("no downloaded add-ons", result["data"]["message"])
        self.assertFalse(trash.exists())
        self.assertEqual(keep.read_text(encoding="utf-8"), "your library", "data is never touched")

    def test_remove_addons_never_reports_success_while_something_is_left(self) -> None:
        held = self._file(f"local/MediaManglers/{safe_write.TRASH_PREFIX}0123456789ab/torch/lib.dll")
        clock = StepClock()
        with mock.patch.dict(os.environ, {user_folders.WORKBENCH_LOCALAPPDATA_ENV: str(self.root / "local")}), \
                OutsideHolder(held, forever=True):
            with self.assertRaises(FileInUse) as caught:
                file_steps.remove_addons(budget=StepBudget(clock=clock), pause=clock.pause)
        self.assertIn(f"{safe_write.TRASH_PREFIX}0123456789ab", str(caught.exception))
        self.assertTrue(held.exists(), "nothing was lost")

    def test_run_carries_out_a_list_of_steps(self) -> None:
        source = self._file("work/a.txt", "a")
        request = self.root / "request.json"
        request.write_text(json.dumps({"payload": {"steps": [
            {"op": "move", "from": str(source), "to": str(self.root / "work" / "b.txt")},
            {"op": "remove", "path": str(self.root / "work" / "b.txt")},
        ]}}), encoding="utf-8")
        run = self._command("run", "--request-file", str(request))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(len(json.loads(run.stdout.strip().splitlines()[-1])["data"]["steps"]), 2)
        self.assertFalse((self.root / "work" / "b.txt").exists())


class SlowQuestionTests(FileStepCase):
    """H4 of the Wave I-A review: asking Windows' Restart Manager who holds a file takes a few milliseconds per file,
    about a minute for a whole speech-library set. A stand-in that takes fifteen seconds to answer proves the step
    keeps trying while it waits for the answer, and never waits past its own limits for it (the real clock)."""

    @staticmethod
    def _slow(_paths: list[Path]) -> list[tuple[int, int, str, str, int]]:
        time.sleep(15)
        return []

    def test_a_slow_answer_never_holds_the_step_past_its_own_limit(self) -> None:
        target = self._file("addons/sp-1/torch/lib/torch_cpu.dll")
        with OutsideHolder(target, forever=True), mock.patch.object(safe_write, "_holder_details",
                                                                     side_effect=self._slow):
            started = time.monotonic()
            with self.assertRaises(FileInUse):
                safe_write.remove(target, budget=StepBudget(per_file=2.0, per_step=4.0))
            elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 1.9)
        self.assertLess(elapsed, 4.0, "the two seconds by the clock, not the fifteen of the question")
        self.assertTrue(target.exists(), "nothing was lost")

    def test_a_brief_hold_ends_the_wait_while_the_slow_answer_is_still_coming(self) -> None:
        target = self._file("addons/sp-1/torch/lib/torch_cpu.dll")
        with OutsideHolder(target, seconds=1.0), mock.patch.object(safe_write, "_holder_details",
                                                                    side_effect=self._slow):
            started = time.monotonic()
            safe_write.remove(target, budget=StepBudget())
            elapsed = time.monotonic() - started
        self.assertFalse(target.exists())
        self.assertLess(elapsed, 5.0, "tried again while Windows was still being asked, and succeeded")

    def test_the_step_limit_holds_across_files_with_a_slow_answer(self) -> None:
        files = [self._file(f"set/file{index}.bin") for index in range(3)]
        holders = [OutsideHolder(path, forever=True) for path in files]
        try:
            budget = StepBudget(per_file=1.5, per_step=2.5)
            with mock.patch.object(safe_write, "_holder_details", side_effect=self._slow):
                started = time.monotonic()
                for path in files:
                    with self.assertRaises(FileInUse):
                        safe_write.remove(path, budget=budget)
                elapsed = time.monotonic() - started
        finally:
            for holder in holders:
                holder.close()
        self.assertGreaterEqual(elapsed, 2.4)
        self.assertLess(elapsed, 4.0, "the step's own limit, by the clock")
        self.assertTrue(all(path.exists() for path in files))


class LargeFolderTests(unittest.TestCase):
    """H4 of the Wave I-A review, on a real folder the size of the speech-library set (16,000 files; the set
    downloaded at first launch has about 23,500). A virus scanner that holds one file for a moment is waited out and
    the step succeeds; one that never lets go stops the step at the ten-second limit by the clock, naming it; the
    app's own hold stops it at once; nothing is ever lost."""

    FILES = 16_000

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.local = cls.root / "local"
        cls.addons = cls.local / "MediaManglers" / "addons"
        cls.building = cls.addons / "sp-1.tmp"
        cls.final = cls.addons / "sp-1"
        cls.held_name = Path("torch") / "lib" / "torch_cpu.dll"
        cls._build()

    @classmethod
    def _build(cls) -> None:
        for index in range(cls.FILES):
            path = cls.building / f"d{index // 400:03d}" / f"m{index:05d}.py"
            if index % 400 == 0:
                path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x = 1\n")
        held = cls.building / cls.held_name
        held.parent.mkdir(parents=True, exist_ok=True)
        held.write_bytes(b"\0" * 65536)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def setUp(self) -> None:
        # Every test starts from the whole set under its temporary name.
        if self.final.exists() and not self.building.exists():
            self._rename(self.final, self.building)
        if not self.building.exists():
            self._build()
        self.held = self.building / self.held_name

    @staticmethod
    def _rename(source: Path, destination: Path) -> None:
        """The test's own rename, which waits for the previous test's ended holder to let go."""

        deadline = time.monotonic() + 20
        while True:
            try:
                os.rename(source, destination)
                return
            except PermissionError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.2)

    def _whole(self, folder: Path) -> bool:
        return sum(len(files) for _root, _folders, files in os.walk(folder)) == self.FILES + 1

    def test_a_brief_outside_hold_is_waited_out_and_the_set_is_put_in_place(self) -> None:
        tries: list[float] = []
        real_rename = os.rename

        def counting(source: object, destination: object) -> None:
            tries.append(time.monotonic())
            real_rename(source, destination)

        with OutsideHolder(self.held, seconds=2.0):
            started = time.monotonic()
            with mock.patch.object(safe_write.os, "rename", side_effect=counting):
                safe_write.rename_into_place(self.building, self.final, budget=StepBudget())
            elapsed = time.monotonic() - started
        self.assertTrue(self._whole(self.final), "the whole set is in place")
        self.assertLess(elapsed, 10.0, "waited out within the ten seconds")
        self.assertGreater(len(tries), 2, "tried again and again while Windows was asked who held it")

    def test_a_file_the_app_itself_holds_stops_the_step_at_once(self) -> None:
        with open(self.held, "rb"):  # Python opens files with no delete sharing on Windows
            started = time.monotonic()
            with self.assertRaises(FileInUse) as caught:
                safe_write.rename_into_place(self.building, self.final, budget=StepBudget())
            elapsed = time.monotonic() - started
        self.assertIn("fault in the app", str(caught.exception))
        self.assertLess(elapsed, 5.0, "it never waits on its own hold")
        self.assertTrue(self._whole(self.building), "nothing was lost")

    def test_a_hold_that_never_ends_stops_at_the_ten_second_limit_and_names_the_program(self) -> None:
        with OutsideHolder(self.held, forever=True) as holder:
            started = time.monotonic()
            with self.assertRaises(FileInUse) as caught:
                safe_write.rename_into_place(self.building, self.final, budget=StepBudget())
            elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 9.5)
        self.assertLess(elapsed, 13.0, "ten seconds by the clock, the question to Windows included")
        self.assertIn(holder.pid, [found.pid for found in caught.exception.holders])
        self.assertTrue(self._whole(self.building), "nothing was lost")
        self.assertFalse(self.final.exists())

    def test_remove_addons_waits_out_a_brief_hold_on_a_set_of_that_size(self) -> None:
        self._rename(self.building, self.final)
        with mock.patch.dict(os.environ, {user_folders.WORKBENCH_LOCALAPPDATA_ENV: str(self.local)}), \
                OutsideHolder(self.final / self.held_name, seconds=2.0):
            started = time.monotonic()
            result = file_steps.remove_addons()
            elapsed = time.monotonic() - started
        self.assertTrue(result["removed"])
        self.assertFalse(self.addons.exists())
        self.assertLess(elapsed, 30.0, "within the step's thirty seconds")


HOLD_LOCK = textwrap.dedent("""
    import sys
    sys.path.insert(0, {src!r})
    from media_manglers.core import app_locks
    print("TAKEN" if app_locks.take_workbench_lock({name!r}) else "REFUSED", flush=True)
    sys.stdin.readline()
""")


class LockTests(unittest.TestCase):
    def _holder(self, name: str) -> subprocess.Popen[str]:
        process = subprocess.Popen([sys.executable, "-c", HOLD_LOCK.format(src=str(REPO_ROOT / "src"), name=name)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.assertEqual(process.stdout.readline().strip(), "TAKEN")
        return process

    def test_one_workbench_at_a_time_for_the_same_data(self) -> None:
        name = f"MediaManglers.Workbench.test-{os.getpid()}-{time.monotonic_ns()}"
        other = self._holder(name)
        try:
            self.assertTrue(app_locks.is_held(name))
            app_locks.release_workbench_lock()
            self.assertFalse(app_locks.take_workbench_lock(name), "a second Workbench is refused")
        finally:
            other.stdin.write("\n")
            other.stdin.flush()
            other.wait(10)
        try:
            self.assertTrue(app_locks.take_workbench_lock(name), "free again once the first one ends")
        finally:
            app_locks.release_workbench_lock()

    def test_test_data_folders_get_a_lock_of_their_own(self) -> None:
        self.assertEqual(app_locks.workbench_lock_name({}), "MediaManglers.Workbench")
        first = app_locks.workbench_lock_name({"MEDIA_MANGLERS_WORKBENCH_LOCALAPPDATA": r"C:\Test\A"})
        second = app_locks.workbench_lock_name({"MEDIA_MANGLERS_WORKBENCH_LOCALAPPDATA": r"C:\Test\B"})
        self.assertTrue(first.startswith("MediaManglers.Workbench."))
        self.assertNotEqual(first, second)

    def test_a_second_workbench_says_so_and_closes_before_opening_anything(self) -> None:
        # L13 of the Wave I-A review: every folder it could open points into one empty folder of the test, so "it
        # opened nothing" is a check that can fail. L12: a launch for a screenshot or a timed check (offscreen, no
        # smoke test) never waits on a box no one can see.
        for arguments in (["--offscreen", "--smoke-test"], ["--offscreen", "--exit-after-ms", "60000"]):
            with self.subTest(arguments=arguments), tempfile.TemporaryDirectory() as temp:
                data = Path(temp) / "data"
                data.mkdir()
                env = {**os.environ, "QT_QPA_PLATFORM": "offscreen",
                       "MEDIA_MANGLERS_WORKBENCH_APPDATA": str(data / "Roaming"),
                       "MEDIA_MANGLERS_WORKBENCH_LOCALAPPDATA": str(data / "Local"),
                       "MEDIA_MANGLERS_LIBRARY_ROOT": str(data / "library"),
                       "MEDIA_MANGLERS_CACHE_ROOT": str(data / "cache"),
                       "MEDIA_MANGLERS_SCRATCH_ROOT": str(data / "scratch"),
                       "MEDIA_MANGLERS_RACE_VIDEO_PRIVACY": str(data / "privacy"),
                       "MEDIA_MANGLERS_VIDEOS_FOLDER": str(data / "Videos"),
                       "MEDIA_MANGLERS_MUSIC_FOLDER": str(data / "Music"),
                       "XDG_CACHE_HOME": str(data / "xdg-cache")}
                name = app_locks.workbench_lock_name(env)
                other = self._holder(name)
                try:
                    code = ("import sys; sys.path.insert(0, %r); from media_manglers_workbench import app; "
                            "sys.exit(app.main(%r))" % (str(REPO_ROOT / "src"), arguments))
                    run = subprocess.run([sys.executable, "-c", code], env=env, cwd=temp, capture_output=True,
                                         text=True, timeout=120, check=False)
                finally:
                    other.stdin.write("\n")
                    other.stdin.flush()
                    other.wait(10)
                self.assertEqual(run.returncode, 4, run.stderr[-2000:])
                self.assertIn("already open", run.stderr)
                self.assertEqual(list(data.rglob("*")), [], "it opened nothing")

    def test_every_helper_run_holds_the_running_lock(self) -> None:
        code = ("import sys, json; sys.path.insert(0, %r); from media_manglers import cli; "
                "from media_manglers.core import app_locks; cli.main([]); "
                "print(json.dumps([app_locks.holding_running_lock(), app_locks.is_held(app_locks.RUNNING_LOCK)]))"
                % str(REPO_ROOT / "src"))
        run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout.strip().splitlines()[-1]), [True, True])

    def test_the_backend_script_holds_the_running_lock_from_its_start(self) -> None:
        script = (REPO_ROOT / "Video Mangler.ps1").read_text(encoding="utf-8")
        param_end = script.index("\n)\n") if "\n)\n" in script else script.index("\n)\r\n")
        first_function = script.index("\nfunction ")
        lock = script.index('New-Object System.Threading.Mutex($false, "MediaManglers.Running")')
        self.assertLess(param_end, lock)
        self.assertLess(lock, first_function, "taken before anything else runs")
        self.assertEqual(app_locks.RUNNING_LOCK, "MediaManglers.Running")


if __name__ == "__main__":
    unittest.main()
