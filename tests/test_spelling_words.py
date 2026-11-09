"""201: one list of words to spell right, on Settings > General, is what Whisper is given.

The operator types the words on the Settings page and saves; a Find my bug reports run hands the
whole list to the backend as one value, and the backend's own functions turn it into Whisper's
hint. Nothing else adds words of its own.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from media_manglers_workbench.app import TRANSIENT_PROFILE_KEYS, WorkbenchWindow  # noqa: E402
from media_manglers_workbench.command_builder import build_workflow_command  # noqa: E402
from media_manglers_workbench.metadata import WORKFLOW_CODEX_EVIDENCE  # noqa: E402
from media_manglers_workbench.settings import build_default_settings, load_settings  # noqa: E402
from tests.test_workbench_bug_reports import ScriptedBackend, _resources  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "Video Mangler.ps1"
KEY = "evidence_transcription_glossary_entries"


def whisper_hint(argv_value: str | None) -> str:
    """What the backend's own functions give Whisper for this -EvidenceTranscriptionGlossaryEntries value."""

    entries = "@()" if argv_value is None else "@('" + argv_value.replace("'", "''") + "')"
    source = textwrap.dedent(
        f"""
        $ErrorActionPreference = 'Stop'
        $tokens = $null; $parseErrors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', [ref]$tokens, [ref]$parseErrors)
        $wanted = @('ConvertTo-MMWordList', 'Get-EvidenceTranscriptionInitialPrompt')
        foreach ($node in $ast.FindAll({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $wanted -contains $n.Name }}, $true)) {{
            Invoke-Expression $node.Extent.Text
        }}
        function Write-Log {{ }}
        $entries = {entries}
        if (Get-Command ConvertTo-MMWordList -ErrorAction SilentlyContinue) {{ $entries = @(ConvertTo-MMWordList -Values $entries) }}
        $prompt = Get-EvidenceTranscriptionInitialPrompt -GlossaryEntries $entries
        [Console]::Out.WriteLine((@{{ prompt = [string]$prompt }} | ConvertTo-Json -Compress))
        """
    ).strip()
    with tempfile.TemporaryDirectory() as temp:
        harness = Path(temp) / "harness.ps1"
        harness.write_text(source, encoding="utf-8")
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
            capture_output=True, text=True, timeout=120,
        )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout.strip().splitlines()[-1])["prompt"]


class SettingsKeepTheOperatorsWordsTests(unittest.TestCase):
    def _load(self, schema: int, words: str) -> dict:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            path.write_text(json.dumps({"schemaVersion": schema, "settings": {KEY: words}}), encoding="utf-8")
            return load_settings(path)

    def test_a_new_install_starts_with_the_three_starting_words(self) -> None:
        self.assertEqual(build_default_settings()[KEY].splitlines(), ["iRacing", "SimHub", "Crew Chief"])

    def test_saved_words_are_kept_and_the_starting_words_added_once(self) -> None:
        settings = self._load(6, "Brooklands=brook lands, SimHub")
        self.assertEqual(settings[KEY].splitlines(), ["Brooklands=brook lands", "SimHub", "iRacing", "Crew Chief"])

    def test_a_starting_word_the_operator_removed_stays_removed(self) -> None:
        settings = self._load(7, "Brooklands=brook lands\nSimHub")
        self.assertEqual(settings[KEY].splitlines(), ["Brooklands=brook lands", "SimHub"])

    def test_the_list_belongs_to_the_operator_not_to_a_profile(self) -> None:
        self.assertIn(KEY, TRANSIENT_PROFILE_KEYS)


class TheWholeListReachesWhisperTests(unittest.TestCase):
    def test_the_whole_list_goes_to_the_backend_as_one_value(self) -> None:
        settings = {**build_default_settings(), KEY: "Brooklands=brook lands\niRacing\nTurn Ten=turn 10|turn ten"}
        argv = build_workflow_command(settings, workflow=WORKFLOW_CODEX_EVIDENCE).argv
        flag = argv.index("-EvidenceTranscriptionGlossaryEntries")
        self.assertEqual(argv[flag + 1], "Brooklands=brook lands;iRacing;Turn Ten=turn 10|turn ten")
        self.assertTrue(argv[flag + 2].startswith("-"), "a second value would be dropped by powershell -File")

    def test_whisper_is_given_every_word_of_the_list(self) -> None:
        self.assertEqual(
            whisper_hint("Brooklands=brook lands;iRacing;SimHub;Crew Chief"),
            "Preferred terminology: Brooklands, iRacing, SimHub, Crew Chief",
        )

    def test_words_written_with_commas_are_separate_words(self) -> None:
        self.assertEqual(whisper_hint("Brooklands, Eau Rouge"), "Preferred terminology: Brooklands, Eau Rouge")

    def test_an_empty_list_gives_whisper_no_words_of_the_apps_own(self) -> None:
        self.assertEqual(whisper_hint(None), "")


class AnApostropheMakesTheWholeTripTests(unittest.TestCase):
    """201: "Word=heard as|ain't heard" goes from the saved settings, through a real powershell -File
    launch and the backend's own functions, to Whisper's hint and to the transcript corrections."""

    ENTRY = "Brooklands=brook lands|brookland|brook'lands|ain't brooklands"

    def _trip(self) -> dict:
        from media_manglers.core.transcript_corrections import correct_text, load_transcription_glossary

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings_path = root / "settings.json"
            settings_path.write_text(json.dumps({"schemaVersion": 7, "settings": {KEY: self.ENTRY + "\niRacing"}}),
                                     encoding="utf-8")
            settings = load_settings(settings_path)
            argv = build_workflow_command(settings, workflow=WORKFLOW_CODEX_EVIDENCE).argv
            value = argv[argv.index("-EvidenceTranscriptionGlossaryEntries") + 1]
            payload_path = root / "payload.json"
            harness = root / "harness.ps1"
            harness.write_text(textwrap.dedent(
                f"""
                param([string[]]$EvidenceTranscriptionGlossaryEntries = @())
                $ErrorActionPreference = 'Stop'
                $tokens = $null; $parseErrors = $null
                $ast = [System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', [ref]$tokens, [ref]$parseErrors)
                $wanted = @('ConvertTo-MMWordList', 'Get-EvidenceTranscriptionInitialPrompt')
                foreach ($node in $ast.FindAll({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $wanted -contains $n.Name }}, $true)) {{
                    Invoke-Expression $node.Extent.Text
                }}
                function Write-Log {{ }}
                $entries = @(ConvertTo-MMWordList -Values @($EvidenceTranscriptionGlossaryEntries))
                $prompt = Get-EvidenceTranscriptionInitialPrompt -GlossaryEntries $entries
                # As Invoke-MediaManglersPythonCli writes a helper's request.
                [PSCustomObject]@{{ payload = @{{ transcription_glossary_entries = @($entries); prompt = $prompt }} }} | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath '{payload_path}' -Encoding UTF8
                """
            ).strip(), encoding="utf-8")
            # As the Workbench's runner launches the backend: an argument list, not a shell string.
            result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness),
                                     "-EvidenceTranscriptionGlossaryEntries", value],
                                    capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(payload_path.read_text(encoding="utf-8-sig"))["payload"]
        glossary = load_transcription_glossary(payload)
        return {
            "value": value,
            "prompt": payload["prompt"],
            "aliases": next(e["aliases"] for e in glossary["entries"] if e["canonical"] == "Brooklands"),
            "straight": correct_text("this is the first Ain't Brooklands livery, brook'lands too", glossary["entries"])[0],
            "curly": correct_text("this is the first ain’t brooklands livery, brook’lands too", glossary["entries"])[0],
        }

    def test_the_apostrophe_reaches_whisper_and_the_corrections(self) -> None:
        trip = self._trip()
        self.assertEqual(trip["value"], self.ENTRY + ";iRacing")
        self.assertEqual(trip["prompt"], "Preferred terminology: Brooklands, iRacing")
        self.assertEqual(trip["aliases"], ["brook lands", "brookland", "brook'lands", "ain't brooklands"])
        self.assertEqual(trip["straight"], "this is the first Brooklands livery, Brooklands too")

    def test_a_curly_apostrophe_from_whisper_is_corrected_too(self) -> None:
        self.assertEqual(self._trip()["curly"], "this is the first Brooklands livery, Brooklands too")


class SettingsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window: WorkbenchWindow | None = None
        ScriptedBackend.instances = []
        ScriptedBackend.write_package = True
        ScriptedBackend.exit_code = 0
        ScriptedBackend.lines = []
        self.recording = self.root / "recordings" / "a.mkv"
        self.recording.parent.mkdir()
        self.recording.write_bytes(b"not really video")

    def tearDown(self) -> None:
        if self.window:
            self.window._closing_after_smoke = True
            self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def test_words_typed_on_the_settings_page_reach_whisper(self) -> None:
        from tests.qt_input import bring_to_front

        settings_path = self.root / "settings.json"
        settings_path.write_text(json.dumps({"schemaVersion": 6, "settings": {
            "log_folder": str(self.root / "logs"),
            "temp_folder": str(self.root / "temp"),
            "output_folder": str(self.root / "out"),
            KEY: "Brooklands=brook lands",
        }}), encoding="utf-8")
        self.window = window = WorkbenchWindow(
            settings_path=settings_path,
            profiles_dir=self.root / "profiles",
            runner_factory=ScriptedBackend,
            resources=_resources(),
        )
        window.show()
        self.app.processEvents()
        editor = window.settings_spelling_words.editor
        bring_to_front(editor)
        window.show()
        self.app.processEvents()
        self.assertEqual(editor.toPlainText().splitlines(), ["Brooklands=brook lands", "iRacing", "SimHub", "Crew Chief"])

        QTest.mouseClick(editor.viewport(), Qt.MouseButton.LeftButton)
        QTest.keyClick(editor, Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(editor, Qt.Key.Key_Return)
        QTest.keyClicks(editor, "Turn Ten=turn 10")
        save = next(button for button in window.findChildren(QPushButton) if button.text() == "Save settings")
        with patch("media_manglers_workbench.app.QMessageBox.information"):
            QTest.mouseClick(save, Qt.MouseButton.LeftButton)
        saved = json.loads(settings_path.read_text(encoding="utf-8"))["settings"]
        self.assertEqual(saved[KEY].splitlines(), ["Brooklands=brook lands", "iRacing", "SimHub", "Crew Chief", "Turn Ten=turn 10"])

        page = window.bug_reports_page
        page.add_recordings([self.recording])
        page.start()
        deadline = time.monotonic() + 10
        while page.running and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        argv = ScriptedBackend.instances[-1].argv
        value = argv[argv.index("-EvidenceTranscriptionGlossaryEntries") + 1]
        self.assertEqual(
            whisper_hint(value),
            "Preferred terminology: Brooklands, iRacing, SimHub, Crew Chief, Turn Ten",
        )


if __name__ == "__main__":
    unittest.main()
