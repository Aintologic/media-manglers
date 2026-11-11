"""The scripts find FFmpeg, FFprobe and Python the way the Workbench does (188).

The path given, then PATH, then the tool's own install folders; no folder from one machine. When a
tool is missing, the message names it, says where it looked, and gives the official page and the
winget command. Each case runs the scripts' real functions, taken from the file, in a PowerShell
whose PATH and install folders are test folders: no real tool on this PC is moved or hidden.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ("Video Mangler.ps1", "Audio Mangler.ps1")
FUNCTIONS = (
    "Get-ToolSource",
    # Installer plan, Stage 1: the bundled copy's step. The harness has no runtime folder beside it, so these
    # cases prove the order without one; tests/test_own_tools_first.py covers the bundled copy.
    "Get-BundledToolsRoot",
    "Get-BundledToolPath",
    "Get-ToolStandardLocations",
    "Get-ToolGetItText",
    "Resolve-ExecutablePath",
    "Get-FFprobePath",
    "Resolve-CommandOrPath",
    "Resolve-PythonInterpreterPath",
)


def _run(script_name: str, body: str, *, path: Path, local: Path, program_files: Path) -> dict[str, object]:
    script_path = REPO_ROOT / script_name
    ps_source = textwrap.dedent(
        f"""
        $ErrorActionPreference = 'Stop'
        $tokens = $null
        $parseErrors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile('{script_path}', [ref]$tokens, [ref]$parseErrors)
        $wanted = @({", ".join(repr(name) for name in FUNCTIONS)})
        $ast.FindAll({{ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $wanted -contains $node.Name }}, $true) |
            ForEach-Object {{ Invoke-Expression $_.Extent.Text }}
        $env:PATH = '{path}'
        $env:LOCALAPPDATA = '{local}'
        $env:ProgramFiles = '{program_files}'
        $result = @{{ found = ''; error = '' }}
        try {{
        {textwrap.indent(textwrap.dedent(body).strip(), "    ")}
        }}
        catch {{
            $result.error = $_.Exception.Message
        }}
        $result | ConvertTo-Json -Compress
        """
    ).strip()
    with tempfile.TemporaryDirectory() as temp:
        harness = Path(temp) / "tool-harness.ps1"
        harness.write_text(ps_source, encoding="utf-8")
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout)
    return json.loads(completed.stdout.strip().splitlines()[-1])


FIND_FFMPEG = """
$result.found = Resolve-ExecutablePath -PreferredPath $chosen -FallbackCommands @('ffmpeg') -ToolName 'FFmpeg' -ToolKey 'ffmpeg'
"""


class ScriptToolDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.path = root / "path"
        self.local = root / "local"
        self.program_files = root / "programs"
        for folder in (self.path, self.local, self.program_files):
            folder.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _file(self, folder: Path, relative: str) -> Path:
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"test executable")
        return target

    def _run(self, script: str, body: str, chosen: str = "") -> dict[str, object]:
        return _run(
            script,
            f"$chosen = '{chosen}'\n" + body,
            path=self.path,
            local=self.local,
            program_files=self.program_files,
        )

    def test_no_ffmpeg_anywhere_names_the_tool_where_it_looked_the_page_and_winget(self) -> None:
        for script in SCRIPTS:
            with self.subTest(script=script):
                result = self._run(script, FIND_FFMPEG)
                message = str(result["error"])
                self.assertEqual(result["found"], "")
                self.assertIn("FFmpeg not found.", message)
                self.assertIn("PATH (ffmpeg)", message)
                self.assertIn(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe", message)
                self.assertIn("https://ffmpeg.org/download.html", message)
                self.assertIn("winget install --id Gyan.FFmpeg -e", message)
                self.assertNotIn("APPS", message)
                self.assertNotIn("digiKam", message)

    def test_ffmpeg_only_on_path_is_found_without_a_path_given(self) -> None:
        on_path = self._file(self.path, "ffmpeg.exe")
        self._file(self.local, r"Microsoft\WinGet\Links\ffmpeg.exe")
        for script in SCRIPTS:
            with self.subTest(script=script):
                result = self._run(script, FIND_FFMPEG)
                self.assertEqual(result["error"], "")
                self.assertEqual(Path(str(result["found"])), on_path, "PATH comes before the install folders")

    def test_ffmpeg_installed_with_winget_is_found_without_path(self) -> None:
        package = self._file(
            self.local,
            r"Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin\ffmpeg.exe",
        )
        for script in SCRIPTS:
            with self.subTest(script=script):
                result = self._run(script, FIND_FFMPEG)
                self.assertEqual(Path(str(result["found"])), package)
        links = self._file(self.local, r"Microsoft\WinGet\Links\ffmpeg.exe")
        for script in SCRIPTS:
            with self.subTest(script=script, where="links"):
                result = self._run(script, FIND_FFMPEG)
                self.assertEqual(Path(str(result["found"])), links, "the Links folder before the package folder")

    def test_the_path_given_comes_first_and_a_missing_one_gives_way(self) -> None:
        chosen = self._file(self.program_files, r"Tools\ffmpeg.exe")
        on_path = self._file(self.path, "ffmpeg.exe")
        for script in SCRIPTS:
            with self.subTest(script=script):
                self.assertEqual(Path(str(self._run(script, FIND_FFMPEG, str(chosen))["found"])), chosen)
                gone = str(self.program_files / "gone" / "ffmpeg.exe")
                self.assertEqual(Path(str(self._run(script, FIND_FFMPEG, gone)["found"])), on_path)

    def test_ffprobe_is_found_beside_ffmpeg_first(self) -> None:
        ffmpeg = self._file(self.program_files, r"FFmpeg\bin\ffmpeg.exe")
        beside = self._file(self.program_files, r"FFmpeg\bin\ffprobe.exe")
        self._file(self.path, "ffprobe.exe")
        body = f"$result.found = Get-FFprobePath -FFmpegExe '{ffmpeg}'"
        for script in SCRIPTS:
            with self.subTest(script=script):
                self.assertEqual(Path(str(self._run(script, body)["found"])), beside)

    def test_no_ffprobe_says_where_to_get_it(self) -> None:
        ffmpeg = self._file(self.program_files, r"FFmpeg\bin\ffmpeg.exe")
        body = f"$result.found = Get-FFprobePath -FFmpegExe '{ffmpeg}'"
        for script in SCRIPTS:
            with self.subTest(script=script):
                message = str(self._run(script, body)["error"])
                self.assertIn("FFprobe not found.", message)
                self.assertIn("winget install --id Gyan.FFmpeg -e", message)

    def test_python_is_found_in_its_install_folder_and_newest_first(self) -> None:
        self._file(self.local, r"Programs\Python\Python39\python.exe")
        newest = self._file(self.local, r"Programs\Python\Python312\python.exe")
        body = "$result.found = Resolve-PythonInterpreterPath -RequestedValue 'py'"
        for script in SCRIPTS:
            with self.subTest(script=script):
                self.assertEqual(Path(str(self._run(script, body)["found"])), newest)

    def test_no_python_says_where_to_get_it(self) -> None:
        body = "$result.found = Resolve-PythonInterpreterPath -RequestedValue 'py'"
        for script in SCRIPTS:
            with self.subTest(script=script):
                message = str(self._run(script, body)["error"])
                self.assertIn("Python interpreter not found.", message)
                self.assertIn("https://www.python.org/downloads/windows/", message)
                self.assertIn("winget install --id Python.Python.3.12 -e", message)

    def test_the_scripts_default_to_no_ffmpeg_folder(self) -> None:
        for script in SCRIPTS:
            with self.subTest(script=script):
                text = (REPO_ROOT / script).read_text(encoding="utf-8")
                self.assertIn('[string]$FFmpegPath = "",', text)
                self.assertNotIn("APPS\\ffmpeg", text)
                self.assertNotIn("digiKam", text)


if __name__ == "__main__":
    unittest.main()
