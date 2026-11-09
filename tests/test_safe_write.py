"""One safe way to replace a small file (242): a crash or a full disk leaves the old file or the whole
new one, never half of it.

Wave A rewrites settings.json when it moves the run history out of it, and settings.json and the profiles
were written straight onto the file: a full disk or a crash in the middle left half a file, and the next
start silently fell back to the defaults (the never-use list, the done list and every saved choice gone).
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from media_manglers.core import safe_write  # noqa: E402
except ImportError:  # shown failing on the code before it existed
    safe_write = None  # type: ignore[assignment]
from media_manglers_workbench import settings as workbench_settings  # noqa: E402

_REAL_IO_OPEN = io.open
_REAL_REPLACE = os.replace


def _held() -> PermissionError:
    """What Windows says when another program has the file open for a moment (a sharing violation)."""

    return PermissionError(13, "The process cannot access the file because it is being used by another process",
                           None, 32)


def _disk_fills_while_writing(target: Path):
    """``open`` as it behaves when the disk fills up while ``target`` itself is opened to be written: the
    file is emptied, then the write fails. Every other file opens normally."""

    def fake_open(file, mode="r", *args, **kwargs):
        if "w" in str(mode) and os.path.normcase(os.path.abspath(str(file))) == os.path.normcase(str(target)):
            _REAL_IO_OPEN(file, mode, *args, **kwargs).close()
            raise OSError(28, "No space left on device")
        return _REAL_IO_OPEN(file, mode, *args, **kwargs)

    return fake_open


def _disk_full(target: Path):
    """Both ways a file is opened (``open`` and ``io.open``, which ``Path.write_text`` uses) behave as a full
    disk does when ``target`` is written straight onto: a writer that does so leaves an empty file."""

    fake = _disk_fills_while_writing(target)
    return mock.patch("builtins.open", side_effect=fake), mock.patch("io.open", side_effect=fake)


class SafeWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="safe-write-"))

    def test_the_new_text_replaces_the_file_and_nothing_else_is_left(self) -> None:
        target = self.folder / "a.json"
        target.write_text("old", encoding="utf-8")
        safe_write.write_text(target, '{"new": true}\n')
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"new": True})
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), ["a.json"])

    def test_the_text_is_on_the_disk_before_the_rename(self) -> None:
        target = self.folder / "b.json"
        order: list[str] = []
        real_fsync = os.fsync

        def fsync(handle: int) -> None:
            order.append("flush")
            real_fsync(handle)

        def replace(source, destination):
            order.append("rename")
            return _REAL_REPLACE(source, destination)

        with mock.patch("os.fsync", side_effect=fsync), mock.patch("os.replace", side_effect=replace):
            safe_write.write_text(target, "data")
        self.assertEqual(order[:2], ["flush", "rename"])

    def test_a_rename_refused_for_a_moment_is_tried_again(self) -> None:
        target = self.folder / "c.json"
        target.write_text("old", encoding="utf-8")
        refusals = iter([_held(), _held()])

        def replace(source, destination):
            refusal = next(refusals, None)
            if refusal is not None:
                raise refusal
            return _REAL_REPLACE(source, destination)

        with mock.patch("os.replace", side_effect=replace), mock.patch("time.sleep"):
            safe_write.write_text(target, "new")
        self.assertEqual(target.read_text(encoding="utf-8"), "new")
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), ["c.json"])

    def test_a_rename_refused_every_time_fails_and_keeps_the_old_file(self) -> None:
        target = self.folder / "d.json"
        target.write_text("old", encoding="utf-8")
        with mock.patch("os.replace", side_effect=_held()), mock.patch("time.sleep") as slept:
            with self.assertRaises(PermissionError):
                safe_write.write_text(target, "new")
        # The app's own small files wait under a second in all (224, Wave B2a: Inbox steps wait longer).
        self.assertAlmostEqual(sum(call.args[0] for call in slept.call_args_list), safe_write.SHORT_WAIT_SECONDS)
        self.assertEqual(target.read_text(encoding="utf-8"), "old")
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), ["d.json"])

    def test_a_refusal_that_is_not_a_hold_fails_at_once(self) -> None:
        # 224 (Wave B2a): only a real hold is waited for.
        target = self.folder / "e.json"
        target.write_text("old", encoding="utf-8")
        with mock.patch("os.replace", side_effect=OSError(2, "path not found", str(target), 3)), \
                mock.patch("time.sleep") as slept:
            with self.assertRaises(FileNotFoundError):
                safe_write.write_text(target, "new")
        self.assertEqual(slept.call_count, 0)
        self.assertEqual(target.read_text(encoding="utf-8"), "old")

    def test_the_temporary_name_is_short_beside_a_long_target(self) -> None:
        target = self.folder / ("x" * 120 + ".json")
        seen: list[str] = []

        def replace(source, destination):
            seen.append(Path(source))
            return _REAL_REPLACE(source, destination)

        with mock.patch("os.replace", side_effect=replace):
            safe_write.write_text(target, "data")
        self.assertLess(len(seen[0].name), 40)
        self.assertEqual(seen[0].parent, target.parent)


@unittest.skipUnless(os.name == "nt", "Windows keeps a file another program has open from being replaced")
class HeldFileTests(unittest.TestCase):
    """224 (Wave B1): a file another program holds open (a virus scan, an indexer, a reader) is waited for a
    short, bounded time; then the write succeeds, or stops with a plain message naming the program. The hold
    here is real. Since Wave B2a it comes from a separate program (``tests/outside_holder.py``): a hold by the
    app itself is never waited for, so this test process holding the file must fail at once."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="safe-held-"))

    def test_a_file_held_for_longer_than_the_wait_is_left_as_it_was_and_the_holder_is_named(self) -> None:
        from tests.outside_holder import OutsideHolder  # noqa: PLC0415

        target = self.folder / "queue-index.json"
        target.write_bytes(b"old")
        with OutsideHolder(target, forever=True) as holder:
            with self.assertRaises(safe_write.FileInUse) as refused:
                safe_write.write_bytes(target, b"new")
        message = str(refused.exception)
        self.assertIn("queue-index.json could not be replaced because", message)
        self.assertIn(f"(process {holder.pid})", message, "the program holding it is named")
        self.assertIn("Nothing was lost", message)
        self.assertIsInstance(refused.exception, PermissionError, "callers that catch PermissionError still do")
        self.assertEqual(target.read_bytes(), b"old")
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), ["queue-index.json"])

    def test_a_file_let_go_during_the_wait_is_replaced(self) -> None:
        from tests.outside_holder import OutsideHolder  # noqa: PLC0415

        target = self.folder / "batch-manifest.json"
        target.write_bytes(b"old")
        # Let go a moment later, like a virus scan finishing.
        with OutsideHolder(target, seconds=0.3):
            safe_write.write_bytes(target, b"new", wait=safe_write.INBOX_WAIT_SECONDS)
        self.assertEqual(target.read_bytes(), b"new")

    def test_a_held_file_that_is_to_be_removed_names_its_holder_too(self) -> None:
        from tests.outside_holder import OutsideHolder  # noqa: PLC0415

        target = self.folder / "review-ledger.sqlite"
        target.write_bytes(b"x")
        with OutsideHolder(target, forever=True) as holder:
            with self.assertRaises(safe_write.FileInUse) as refused:
                safe_write.remove(target)
            self.assertIn("review-ledger.sqlite could not be removed because", str(refused.exception))
            self.assertIn(f"(process {holder.pid})", str(refused.exception))
            self.assertTrue(target.exists())
        safe_write.remove(target)
        safe_write.remove(target)  # already gone: nothing to do
        self.assertFalse(target.exists())

    def test_a_brief_read_by_a_program_the_app_started_is_waited_for(self) -> None:
        # 224 (Wave B2a review): the PowerShell host, which the app started, reads the Inbox's progress file
        # every half second while the helper replaces it. A small file's replace waits for such a read, as it
        # always did; only moves and removals stop at once for the app's own handle.
        from tests.outside_holder import OutsideHolder  # noqa: PLC0415

        target = self.folder / "progress.json"
        target.write_bytes(b"old")
        with OutsideHolder(target, outside=False, seconds=0.3):
            safe_write.write_bytes(target, b"new", wait=safe_write.INBOX_WAIT_SECONDS)
        self.assertEqual(target.read_bytes(), b"new")

    def test_a_small_file_this_app_keeps_open_is_waited_for_the_short_time_only(self) -> None:
        target = self.folder / "settings.json"
        target.write_bytes(b"old")
        with open(target, "rb"), mock.patch("time.sleep") as slept:
            with self.assertRaises(safe_write.FileInUse) as refused:
                safe_write.write_bytes(target, b"new")
        self.assertAlmostEqual(sum(call.args[0] for call in slept.call_args_list), safe_write.SHORT_WAIT_SECONDS)
        self.assertIn("settings.json could not be replaced", str(refused.exception))
        self.assertEqual(target.read_bytes(), b"old")


class SettingsAndProfilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="safe-settings-"))

    def test_a_settings_save_that_fails_while_writing_leaves_the_old_settings_whole(self) -> None:
        path = self.folder / "settings.json"
        settings = workbench_settings.build_default_settings()
        settings["output_folder"] = str(self.folder / "my output")
        workbench_settings.save_settings(settings, path)
        settings["output_folder"] = str(self.folder / "changed output")
        first, second = _disk_full(path)
        with first, second:
            try:
                workbench_settings.save_settings(settings, path)
            except OSError:
                pass
        # Never written straight onto: the whole new file arrived by way of a name of its own.
        stored = json.loads(path.read_text(encoding="utf-8"))["settings"]["output_folder"]
        self.assertEqual(stored, str(self.folder / "changed output"))

    def test_a_profile_save_that_fails_while_writing_leaves_the_old_profile_whole(self) -> None:
        manager = workbench_settings.ProfileManager(profiles_dir=self.folder / "profiles")
        settings = workbench_settings.build_default_settings()
        settings["frame_interval_seconds"] = 7
        path = manager.save("Mine", settings)
        settings["frame_interval_seconds"] = 9
        first, second = _disk_full(path)
        with first, second:
            try:
                manager.save("Mine", settings)
            except OSError:
                pass
        stored = json.loads(path.read_text(encoding="utf-8"))["settings"]["frame_interval_seconds"]
        self.assertEqual(stored, 9)

    def test_a_disk_that_fills_while_the_new_settings_are_written_keeps_the_old_ones_exactly(self) -> None:
        path = self.folder / "settings.json"
        settings = workbench_settings.build_default_settings()
        settings["output_folder"] = str(self.folder / "my output")
        workbench_settings.save_settings(settings, path)
        before = path.read_bytes()
        settings["output_folder"] = str(self.folder / "changed output")

        def full_disk(file, mode="r", *args, **kwargs):
            if "w" in str(mode):
                handle = _REAL_IO_OPEN(file, mode, *args, **kwargs)
                handle.close()
                raise OSError(28, "No space left on device")
            return _REAL_IO_OPEN(file, mode, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=full_disk), mock.patch("io.open", side_effect=full_disk):
            with self.assertRaises(OSError):
                workbench_settings.save_settings(settings, path)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(sorted(item.name for item in self.folder.iterdir()), ["settings.json"])


if __name__ == "__main__":
    unittest.main()
