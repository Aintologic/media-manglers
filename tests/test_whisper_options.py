"""226: one Whisper settings rule, and the requests it replaced left byte for byte as they were.

``whisper_options.from_settings`` turns the main settings into the model, graphics-card and language
fields of a Whisper request; the raw bin page and the Inbox now use it. Their requests are compared
with the ones the 9e065e4 code built (its functions are taken out of git and run beside today's) for
every model, device and language. ``words`` gives the "Words to spell right" list as Whisper's hint and
its corrections; the hint is the one the backend builds for features 1 and 2. The packaged backend
carries no Workbench code, so none of this may import it.
"""

from __future__ import annotations

import ast
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers.core import review_preparation, spelling_words as core_spelling_words  # noqa: E402
from media_manglers.core import user_folders, whisper_options  # noqa: E402
from media_manglers_workbench import settings as workbench_settings  # noqa: E402
from media_manglers_workbench import spelling_words  # noqa: E402

GIT = shutil.which("git")
BASELINE = "9e065e4"
SCRIPT = REPO_ROOT / "Video Mangler.ps1"
MODELS = ("small", "medium", "large", "", None)
DEVICES = ("Auto", "CPU", "GPU", "", None)
LANGUAGES = ("", "en", "de", None)


def _baseline_problem() -> str:
    if not GIT:
        return "git is required to take the 9e065e4 code out of the repository"
    found = subprocess.run([GIT, "-C", str(REPO_ROOT), "cat-file", "-e", f"{BASELINE}^{{commit}}"],
                           capture_output=True, check=False)
    return "" if found.returncode == 0 else f"commit {BASELINE} is not in this clone (a shallow clone?)"


PROBLEM = _baseline_problem()


def baseline_function(relative: str, name: str, namespace: dict):
    """The 9e065e4 version of a module-level function or a method, compiled into ``namespace`` (today's
    module globals, so it calls what today's code calls)."""

    source = subprocess.run([GIT, "-C", str(REPO_ROOT), "show", f"{BASELINE}:{relative}"],
                            capture_output=True, check=True).stdout.decode("utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            text = textwrap.dedent(ast.get_source_segment(source, node))
            scope: dict = {}
            exec(compile(text, f"{BASELINE}:{relative}", "exec"), {**namespace}, scope)  # noqa: S102
            return scope[name]
    raise LookupError(f"{name} is not in {BASELINE}:{relative}")


def _combinations(**values):
    keys = list(values)
    for combination in itertools.product(*(values[key] for key in keys)):
        yield {key: value for key, value in zip(keys, combination) if value is not None}


class FromSettingsTests(unittest.TestCase):
    def test_the_main_settings_become_the_request_fields(self) -> None:
        self.assertEqual(whisper_options.from_settings({"whisper_model": "large", "whisper_device": "CPU",
                                                        "language": "de", "narration_speech_mode": "Continuous"}),
                         {"model_name": "large", "prefer_gpu": False, "language_code": "de",
                          "narration_speech_mode": "Continuous"})
        self.assertEqual(whisper_options.from_settings({}),
                         {"model_name": "medium", "prefer_gpu": True, "language_code": "en",
                          "narration_speech_mode": "Sparse"})

    def test_a_blank_or_auto_language_is_english_and_auto_speech_is_sparse(self) -> None:
        # As the backend's Resolve-MMNarrationTranscriptionDefaults: Whisper left to guess has
        # written a quiet opening down in the wrong language.
        for language in ("", "  ", "auto", "Auto", None):
            with self.subTest(language=language):
                fields = whisper_options.from_settings({"language": language, "narration_speech_mode": "Auto"})
                self.assertEqual((fields["language_code"], fields["narration_speech_mode"]), ("en", "Sparse"))
        self.assertEqual(whisper_options.from_settings({"narration_speech_mode": "Continuous"})["narration_speech_mode"],
                         "Continuous")

    def test_the_graphics_card_is_asked_for_unless_the_device_is_cpu(self) -> None:
        for device, wanted in (("Auto", True), ("GPU", True), ("CPU", False), ("", True)):
            with self.subTest(device=device):
                self.assertIs(whisper_options.from_settings({"whisper_device": device})["prefer_gpu"], wanted)

    def test_a_request_the_backend_worked_out_is_taken_as_it_is(self) -> None:
        self.assertEqual(whisper_options.from_settings({}, default_model="base.en", resolved=True),
                         {"model_name": "base.en", "prefer_gpu": True, "language_code": "",
                          "narration_speech_mode": "Auto"})
        self.assertEqual(whisper_options.from_settings({"whisper_model": "small", "prefer_gpu": False,
                                                        "language_code": "de", "narration_speech_mode": "Sparse"},
                                                       resolved=True),
                         {"model_name": "small", "prefer_gpu": False, "language_code": "de",
                          "narration_speech_mode": "Sparse"})


class SavedSettingsTests(unittest.TestCase):
    """Read only, from the same file the Workbench saves, and never the real one in a test."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = mock.patch.dict(os.environ, {workbench_settings.APPDATA_OVERRIDE_ENV: str(self.root)})
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temp.cleanup()

    def test_the_settings_the_workbench_saved_are_read(self) -> None:
        path = workbench_settings.default_settings_path()
        self.assertEqual(user_folders.workbench_settings_file(), path)
        self.assertTrue(path.resolve().is_relative_to(self.root.resolve()))
        workbench_settings.save_settings({**workbench_settings.build_default_settings(), "whisper_model": "large",
                                          "whisper_device": "CPU", "language": "de",
                                          core_spelling_words.SETTING_KEY: "Brooklands=brook lands\nEau Rouge"}, path)
        before = path.read_bytes()
        saved = whisper_options.read_saved_settings()
        self.assertEqual(path.read_bytes(), before, "read only")
        self.assertEqual(whisper_options.from_settings(saved),
                         {"model_name": "large", "prefer_gpu": False, "language_code": "de",
                          "narration_speech_mode": "Sparse"})
        self.assertEqual(whisper_options.words(saved),
                         ("Preferred terminology: Brooklands, Eau Rouge", ["Brooklands=brook lands", "Eau Rouge"]))

    def test_a_test_run_never_reads_the_operators_own_settings(self) -> None:
        # tests/conftest.py points the settings folder at the run's scratch folder, so any test that
        # reaches read_saved_settings without setting its own folder reads nothing real.
        self.environment.stop()
        try:
            real = user_folders.settings_root() / user_folders.APP_FOLDER / "workbench" / "settings.json"
            self.assertTrue(os.environ.get(workbench_settings.APPDATA_OVERRIDE_ENV, "").strip())
            self.assertNotEqual(user_folders.workbench_settings_file(), real)
            self.assertNotEqual(workbench_settings.default_settings_path(), real)
            self.assertEqual(workbench_settings.default_settings_path(), user_folders.workbench_settings_file())
        finally:
            self.environment.start()

    def test_no_settings_or_unreadable_ones_give_nothing(self) -> None:
        self.assertEqual(whisper_options.read_saved_settings(), {})
        path = user_folders.workbench_settings_file()
        path.parent.mkdir(parents=True)
        for text in ("{not json", "[1, 2]", '{"settings": "no"}'):
            with self.subTest(text=text):
                path.write_text(text, encoding="utf-8")
                self.assertEqual(whisper_options.read_saved_settings(), {})


class WordsTests(unittest.TestCase):
    VALUE = "Brooklands=brook lands|brooklins\n\nEau Rouge, Crew Chief=crew chef;brooklands=again\n  iRacing  "

    def test_the_list_is_read_as_the_settings_page_reads_it(self) -> None:
        self.assertIs(spelling_words.split_words, core_spelling_words.split_words)
        self.assertEqual(spelling_words.SETTING_KEY, core_spelling_words.SETTING_KEY)
        prompt, entries = whisper_options.words({core_spelling_words.SETTING_KEY: self.VALUE})
        self.assertEqual(entries, spelling_words.split_words(self.VALUE))
        self.assertEqual(prompt, "Preferred terminology: Brooklands, Eau Rouge, Crew Chief, iRacing")
        self.assertEqual(whisper_options.words({}), ("", []))

    @unittest.skipIf(bool(PROBLEM), PROBLEM)
    def test_the_parser_is_the_one_from_before(self) -> None:
        old = baseline_function("src/media_manglers_workbench/spelling_words.py", "split_words",
                                vars(core_spelling_words))
        for value in (self.VALUE, None, "", ["a=b", "A", "c;d"], ("x\r\ny",), "=only, word=", 7):
            with self.subTest(value=value):
                self.assertEqual(spelling_words.split_words(value), old(value))

    @unittest.skipUnless(shutil.which("powershell"), "PowerShell is required")
    def test_the_hint_is_the_one_the_backend_builds_for_features_1_and_2(self) -> None:
        # The Workbench hands the list to the backend as one ";"-joined value (201); the backend
        # splits it again and builds Whisper's hint from the word before each "=".
        sent = spelling_words.command_value(self.VALUE)
        source = textwrap.dedent(
            f"""
            $tokens = $null; $parseErrors = $null
            $ast = [System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', [ref]$tokens, [ref]$parseErrors)
            foreach ($name in @('ConvertTo-MMWordList', 'Get-EvidenceTranscriptionInitialPrompt')) {{
                $node = $ast.Find({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }}, $true)
                Invoke-Expression $node.Extent.Text
            }}
            $words = @(ConvertTo-MMWordList -Values @('{sent.replace("'", "''")}'))
            [Console]::Out.Write((@{{ prompt = (Get-EvidenceTranscriptionInitialPrompt -GlossaryEntries $words); words = $words }} | ConvertTo-Json -Compress))
            """
        ).strip()
        run = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", source],
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stderr)
        backend = json.loads(run.stdout.strip().splitlines()[-1])
        prompt, entries = whisper_options.words({core_spelling_words.SETTING_KEY: self.VALUE})
        self.assertEqual(prompt, backend["prompt"])
        self.assertEqual(entries, backend["words"])


@unittest.skipIf(bool(PROBLEM), PROBLEM)
class InboxRequestUnchangedTests(unittest.TestCase):
    def test_the_inbox_whisper_request_is_byte_for_byte_the_same(self) -> None:
        old = baseline_function("src/media_manglers/core/review_preparation.py", "_default_transcriber",
                                vars(review_preparation))
        cases = list(_combinations(whisper_model=("base.en", "medium", "", None), prefer_gpu=(True, False, None),
                                   language_code=("", "en", "de", None),
                                   narration_speech_mode=("Sparse", "Auto", "", None)))
        cases += [{"language": "de", "whisper_device": "CPU", "ffmpeg_exe": "C:\\tools\\ffmpeg.exe",
                   "initial_prompt": "Preferred terminology: A", "glossary_entries": ["A=a"]}]
        sent: list[dict] = []
        with mock.patch.object(review_preparation.whisper_local, "transcribe_from_request",
                               side_effect=lambda payload: sent.append(payload) or {}):
            for settings in cases:
                old(Path("a.wav"), Path("out"), settings)
                review_preparation._default_transcriber(Path("a.wav"), Path("out"), settings)
        self.assertEqual(len(sent), 2 * len(cases))
        for index, settings in enumerate(cases):
            with self.subTest(settings=settings):
                self.assertEqual(json.dumps(sent[2 * index + 1]), json.dumps(sent[2 * index]))


@unittest.skipIf(bool(PROBLEM), PROBLEM)
@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required")
class RawBinRequestUnchangedTests(unittest.TestCase):
    """The raw bin page's scan request, on the real page, for every model, device and language."""

    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        from media_manglers.core import app_cache, raw_bin_library
        from media_manglers_workbench.app import WorkbenchWindow
        from media_manglers_workbench.runner import FakeRunner
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from tests.test_workbench_bug_reports import _resources

        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.raw = self.root / "raw"
        self.raw.mkdir()
        self.environment = mock.patch.dict(os.environ, {raw_bin_library.LIBRARY_ROOT_ENV: str(self.root / "library"),
                                                        app_cache.CACHE_ROOT_ENV: str(self.root / "cache")})
        self.environment.start()
        settings_path = self.root / "settings.json"
        settings_path.write_text(json.dumps({"schemaVersion": workbench_settings.SETTINGS_SCHEMA_VERSION, "settings": {
            "log_folder": str(self.root / "logs"), "temp_folder": str(self.root / "temp"),
            "output_folder": str(self.root / "out"), "review_source_folders": str(self.raw)}}), encoding="utf-8")
        self.window = WorkbenchWindow(settings_path=settings_path, profiles_dir=self.root / "profiles",
                                      runner_factory=FakeRunner, resources=_resources())
        self.window.resize(1400, 900)
        self.window.show()
        self.app.processEvents()
        QTest.mouseClick(self.window.nav_buttons["Raw Bin"], Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.page = self.window.raw_bin_page
        from media_manglers_workbench import raw_bin_page

        self.old_payload = baseline_function("src/media_manglers_workbench/raw_bin_page.py", "_payload",
                                             vars(raw_bin_page))

    def tearDown(self) -> None:
        self.window._closing_after_smoke = True
        self.window.close()
        self.app.processEvents()
        self.environment.stop()
        self.temp.cleanup()

    def _use(self, settings: dict) -> None:
        for key in ("whisper_model", "whisper_device", "language"):
            self.window.app_settings.pop(key, None)
        self.window.app_settings.update(settings)

    def _wave_a_parts(self, payload: dict) -> dict:
        # 242: the scan also says which library it writes to, the one the Workbench has open; the rest of
        # the request is exactly the old one.
        self.assertEqual(payload.pop("library_root"), str(self.window.records.root))
        return payload

    def test_every_model_device_and_language_gives_the_same_request(self) -> None:
        for settings in _combinations(whisper_model=MODELS, whisper_device=DEVICES, language=LANGUAGES):
            with self.subTest(settings=settings):
                self._use(settings)
                self.assertEqual(json.dumps(self._wave_a_parts(self.page._payload())),
                                 json.dumps(self.old_payload(self.page)))

    def test_the_scan_button_sends_it(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        self._use({"whisper_model": "small", "whisper_device": "CPU", "language": "de"})
        wanted = self.old_payload(self.page)
        with mock.patch.object(self.window, "start_external_run", return_value=True) as started:
            QTest.mouseClick(self.page.scan_button, Qt.MouseButton.LeftButton)
        command = started.call_args.args[0]
        request = Path(command.argv[command.argv.index("--request-file") + 1])
        payload = json.loads(request.read_text(encoding="utf-8"))["payload"]
        payload.pop("run_control_path")
        # 243: the run's own number in the library, named by the page, so the scan writes into it.
        self.assertEqual(payload.pop("records_run_id"), started.call_args.kwargs["run_id"])
        self.assertEqual(json.dumps(self._wave_a_parts(payload)), json.dumps(wanted))
        self.assertEqual((payload["model_name"], payload["prefer_gpu"], payload["language"]), ("small", False, "de"))


class CoreNeedsNoWorkbenchTests(unittest.TestCase):
    """The packaged backend ships only two Workbench files (226, review MAJOR 9)."""

    def test_the_whisper_rules_import_without_the_workbench(self) -> None:
        probe = textwrap.dedent(
            """
            import importlib.abc, sys
            class NoWorkbench(importlib.abc.MetaPathFinder):
                def find_spec(self, name, path=None, target=None):
                    if name == "media_manglers_workbench" or name.startswith("media_manglers_workbench."):
                        raise ImportError("the packaged backend has no " + name)
                    return None
            sys.meta_path.insert(0, NoWorkbench())
            sys.path.insert(0, sys.argv[1])
            for name in ("media_manglers.core.whisper_options", "media_manglers.core.spelling_words",
                         "media_manglers.core.sparse_narration", "media_manglers.core.cross_track_check",
                         "media_manglers.providers.whisper_local"):
                importlib.import_module(name)
            print("NO_WORKBENCH_IMPORTS_OK")
            """
        )
        run = subprocess.run([sys.executable, "-B", "-c", probe, str(REPO_ROOT / "src")],
                             capture_output=True, text=True, timeout=120)
        self.assertIn("NO_WORKBENCH_IMPORTS_OK", run.stdout, run.stderr)


if __name__ == "__main__":
    unittest.main()
