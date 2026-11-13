"""No message, help page or script ever tells the user to close, stop, exclude or switch off security software,
whatever kind of holder Windows reports it as (installer plan, the antivirus rules; H3 of the Wave I-A review).

Windows' Restart Manager reports some virus scanners as ordinary programs and others as Windows services. The app
waits a short, bounded time for a file such a program holds, then either succeeds or stops with a plain message that
names the program; it never advises touching protection. Two checks:

- the real messages, made by the real file steps (new and older) with a real outside hold, while Windows reports the
  holder under the names security software uses, of every kind, ask the user to close, quit, stop, end, disable,
  exclude, allow or turn off nothing at all (only "Close Media Manglers" when Media Manglers itself still has the
  file);
- every sentence a user can read (the strings in the code, the help pages, the READMEs and both scripts) that names
  security software asks nothing of it.
"""

from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from media_manglers.core import file_steps, safe_write, user_folders  # noqa: E402
from media_manglers.core.safe_write import FileInUse, StepBudget  # noqa: E402
from outside_holder import OutsideHolder  # noqa: E402

# What would tell the user to do something to the program holding the file.
ADVICE = re.compile(r"\b(close|closing|quit|stop|stopping|exit|end (?:it|that|the)|kill|disable|turn(?:ing)? off|"
                    r"switch(?:ing)? off|uninstall|pause|exclu\w*|allow\w*|whitelist\w*|add an exception)\b",
                    re.IGNORECASE)
# Words that name security software.
PROTECTION = re.compile(r"\b(scanners?|virus|antivirus|anti-virus|antimalware|anti-malware|malware|protection|"
                        r"security|defender|sophos)\b", re.IGNORECASE)
# Advice to close whatever holds a file: a security program is often that holder, so this is never said.
CLOSE_THE_HOLDER = re.compile(r"\bclose (?:that|the other|any|this|the) program\b|\bclose anything\b",
                              re.IGNORECASE)
# Sentences that state the rule itself rather than advise anything (each is a statement that nothing is asked).
RULE_STATEMENTS = (
    "no antivirus exclusion is needed or made.",
)

# Holders as Windows' Restart Manager reports them: (process, start time, name, service, kind: 0 unknown, 1 a main
# window, 3 a service). Some scanners come as ordinary programs.
SECURITY_HOLDERS = (
    [(4101, 1, "Sophos File Scanner", "", 0)],
    [(4102, 1, "Microsoft Defender Antivirus Service", "WinDefend", 3)],
    [(4103, 1, "Antimalware Service Executable", "", 1)],
    [(4104, 1, "Security scanner", "", 0), (4105, 1, "Windows Defender Antivirus", "WinDefend", 3)],
    [],
)


class StepClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def pause(self, seconds: float) -> None:
        self.now += seconds


def _sentences(text: str) -> list[str]:
    paragraphs = re.split(r"\n\s*\n|\n\s*[-*#|] ", text)
    found: list[str] = []
    for paragraph in paragraphs:
        joined = " ".join(paragraph.split())
        found += [part.strip() for part in re.split(r"(?<=[.!?:;])\s+", joined) if part.strip()]
    return found


class RealMessageTests(unittest.TestCase):
    """The messages the file steps really give, with a real hold, while Windows names security software."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _file(self, relative: str, text: str = "data") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _messages(self, details: list[tuple[int, int, str, str, int]], program: str = "scan.exe") -> list[str]:
        """Every kind of step, new and older, held by a real outside program, with Windows reporting ``details``."""

        messages: list[str] = []
        patches = (mock.patch.object(safe_write, "_holder_details", return_value=details),
                   mock.patch.object(safe_write, "_is_app", return_value=False),
                   mock.patch.object(safe_write, "_program_file", return_value=program))
        for patch in patches:
            patch.start()
        try:
            def caught(action) -> None:
                try:
                    action()
                except (FileInUse, safe_write.FileStepRefused) as exc:
                    messages.append(str(exc))
                else:
                    self.fail("the step was expected to stop while the file was held")

            target = self._file("addons/sp-1/torch/lib/torch_cpu.dll")
            folder = target.parents[2]
            partial = self._file("cache/medium.pt.partial", "weights")
            model = self._file("cache/medium.pt", "damaged")
            sha = hashlib.sha256(b"weights").hexdigest()
            with OutsideHolder(target, forever=True), OutsideHolder(model, forever=True):
                clock = StepClock()
                caught(lambda: safe_write.remove(target, budget=StepBudget(clock=clock), pause=clock.pause))
                clock = StepClock()
                caught(lambda: safe_write.rename_into_place(folder, folder.with_name("sp-2"),
                                                            budget=StepBudget(clock=clock), pause=clock.pause))
                clock = StepClock()
                caught(lambda: safe_write.place_checked(partial, model, sha, replace=True,
                                                        budget=StepBudget(clock=clock), pause=clock.pause))
                clock = StepClock()
                caught(lambda: safe_write.remove_disposable_tree(folder, within=self.root,
                                                                 budget=StepBudget(clock=clock), pause=clock.pause))
                # The older steps (the Inbox's), with their own short wait.
                caught(lambda: safe_write.remove(target, wait=0.2))
                caught(lambda: safe_write.move(target, self.root / "elsewhere.dll", wait=0.2))
                # The uninstaller's command.
                with mock.patch.dict(os.environ, {user_folders.WORKBENCH_LOCALAPPDATA_ENV: str(self.root / "local")}):
                    held = self._file("local/MediaManglers/addons/sp-1/torch/lib.dll")
                    with OutsideHolder(held, forever=True):
                        clock = StepClock()
                        caught(lambda: file_steps.remove_addons(budget=StepBudget(clock=clock), pause=clock.pause))
        finally:
            for patch in patches:
                patch.stop()
        return messages

    def test_no_held_file_message_asks_anything_of_security_software_of_any_kind(self) -> None:
        for details in SECURITY_HOLDERS:
            for message in self._messages(details):
                with self.subTest(holders=[item[2] for item in details], message=message):
                    self.assertIsNone(ADVICE.search(message), message)
                    self.assertIn("Nothing was lost", message)
                    for _pid, _start, name, _service, _kind in details:
                        self.assertIn(name, message, "the program is named")

    def test_only_media_manglers_itself_is_ever_asked_to_be_closed(self) -> None:
        details = [(4201, 1, "Media Manglers", "", 1)]
        for message in self._messages(details, program=safe_write.WORKBENCH_PROGRAM):
            with self.subTest(message=message):
                self.assertIn("Close Media Manglers", message)
                remainder = message.replace("Close Media Manglers", "")
                self.assertIsNone(ADVICE.search(remainder), message)


class EveryReadableTextTests(unittest.TestCase):
    """Every sentence a user can read that names security software asks nothing of it."""

    def _texts(self) -> list[tuple[str, str]]:
        texts: list[tuple[str, str]] = []
        for path in sorted((REPO_ROOT / "src").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            described = {id(node.body[0].value) for node in ast.walk(tree)
                         if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                         and node.body and isinstance(node.body[0], ast.Expr)
                         and isinstance(node.body[0].value, ast.Constant)}
            texts += [(str(path.relative_to(REPO_ROOT)), node.value) for node in ast.walk(tree)
                      if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in described]
        pages = [*sorted((REPO_ROOT / "docs").rglob("*.md")), REPO_ROOT / "README.md"]
        texts += [(str(path.relative_to(REPO_ROOT)), path.read_text(encoding="utf-8")) for path in pages]
        for script in ("Video Mangler.ps1", "Audio Mangler.ps1"):
            for number, line in enumerate((REPO_ROOT / script).read_text(encoding="utf-8").splitlines(), start=1):
                if line.lstrip().startswith("#"):
                    continue
                texts += [(f"{script}:{number}", match) for match in re.findall(r'"([^"]{12,})"', line)]
        return texts

    def test_the_files_read_are_the_real_ones(self) -> None:
        sources = {source.split(":")[0] for source, _text in self._texts()}
        self.assertIn(str(Path("docs/workbench/TROUBLESHOOTING.md")), sources)
        self.assertIn(str(Path("src/media_manglers/core/safe_write.py")), sources)
        self.assertIn("Video Mangler.ps1", sources)

    def test_no_sentence_naming_security_software_asks_anything_of_it(self) -> None:
        found = []
        for source, text in self._texts():
            for sentence in _sentences(text):
                if sentence.casefold() in RULE_STATEMENTS:
                    continue
                if PROTECTION.search(sentence) and ADVICE.search(sentence):
                    found.append(f"{source}: {sentence}")
        self.assertEqual(found, [])

    def test_no_text_ever_says_to_close_whatever_program_holds_a_file(self) -> None:
        found = [f"{source}: {sentence}" for source, text in self._texts() for sentence in _sentences(text)
                 if CLOSE_THE_HOLDER.search(sentence)]
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
