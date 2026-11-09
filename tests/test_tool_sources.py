"""One table of where each tool comes from, the same in the Workbench and the scripts (188)."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers_workbench.resources import DependencyStatus  # noqa: E402
from media_manglers_workbench.tool_sources import (  # noqa: E402
    TOOL_SOURCES,
    find_tool,
    needs_download,
    standard_locations,
)


ENV = {"LOCALAPPDATA": r"C:\Users\Someone\AppData\Local", "ProgramFiles": r"C:\Program Files"}


def _finder(files: set[str], on_path: dict[str, str] | None = None):
    on_path = on_path or {}
    lowered = {item.casefold() for item in files}
    return dict(
        which=lambda name: on_path.get(name),
        is_file=lambda path: str(path).casefold() in lowered,
        environ=ENV,
        expand=lambda pattern: [item for item in files if Path(item).match(pattern)],
    )


class ToolSourceTableTests(unittest.TestCase):
    def test_every_tool_has_an_official_page_and_no_folder_from_one_machine(self) -> None:
        for key, source in TOOL_SOURCES.items():
            with self.subTest(key=key):
                self.assertTrue(source.page.startswith("https://"))
                for variable, pattern in source.standard:
                    self.assertIn(variable, {"LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)", "SystemRoot"})
                    self.assertNotRegex(pattern, r"^[A-Za-z]:", "a folder below a Windows folder, never a drive")

    def test_winget_commands(self) -> None:
        self.assertEqual(TOOL_SOURCES["ffmpeg"].winget_command, "winget install --id Gyan.FFmpeg -e")
        self.assertEqual(TOOL_SOURCES["ffprobe"].winget_command, "winget install --id Gyan.FFmpeg -e")
        self.assertEqual(TOOL_SOURCES["python"].winget_command, "winget install --id Python.Python.3.12 -e")
        self.assertEqual(TOOL_SOURCES["ytdlp"].winget_command, "winget install --id yt-dlp.yt-dlp -e")
        self.assertEqual(TOOL_SOURCES["vlc"].winget_command, "winget install --id VideoLAN.VLC -e")
        self.assertEqual(TOOL_SOURCES["whisper"].winget_command, "")
        self.assertEqual(TOOL_SOURCES["torch"].winget_command, "")


class FindToolTests(unittest.TestCase):
    links = r"C:\Users\Someone\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"
    package = (
        r"C:\Users\Someone\AppData\Local\Microsoft\WinGet\Packages"
        r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin\ffmpeg.exe"
    )

    def test_the_chosen_path_comes_first(self) -> None:
        chosen = r"C:\Tools\ffmpeg.exe"
        found = find_tool("ffmpeg", chosen, **_finder({chosen, self.links}, {"ffmpeg.exe": r"C:\Path\ffmpeg.exe"}))
        self.assertEqual((found.path, found.found_by, found.note), (chosen, "chosen", ""))

    def test_then_path_then_the_install_folders(self) -> None:
        on_path = r"C:\Path\ffmpeg.exe"
        self.assertEqual(find_tool("ffmpeg", **_finder({self.links}, {"ffmpeg.exe": on_path})).path, on_path)
        found = find_tool("ffmpeg", **_finder({self.package}))
        self.assertEqual((found.path, found.found_by), (self.package, "standard"))
        self.assertEqual(find_tool("ffmpeg", **_finder({self.links, self.package})).path, self.links)

    def test_a_chosen_path_that_is_gone_gives_way_and_says_so(self) -> None:
        gone = r"C:\Old\ffmpeg.exe"
        found = find_tool("ffmpeg", gone, **_finder({self.links}))
        self.assertEqual(found.path, self.links)
        self.assertEqual(found.chosen_missing, gone)
        self.assertIn("Your chosen path is missing", found.note)
        self.assertEqual(find_tool("ffmpeg", gone, **_finder(set())).path, "")

    def test_ffprobe_beside_ffmpeg_first(self) -> None:
        beside = r"C:\Tools\ffprobe.exe"
        found = find_tool("ffprobe", beside=r"C:\Tools\ffmpeg.exe",
                          **_finder({beside}, {"ffprobe.exe": r"C:\Path\ffprobe.exe"}))
        self.assertEqual((found.path, found.found_by), (beside, "beside FFmpeg"))

    def test_newest_package_version_first(self) -> None:
        older = self.package.replace("ffmpeg-8.1", "ffmpeg-7.1")
        self.assertEqual(standard_locations(TOOL_SOURCES["ffmpeg"], environ=ENV,
                                            expand=lambda pattern: [older, self.package])[2], self.package)

    def test_version_folders_compare_as_numbers(self) -> None:
        python39 = r"C:\Users\Someone\AppData\Local\Programs\Python\Python39\python.exe"
        python312 = r"C:\Users\Someone\AppData\Local\Programs\Python\Python312\python.exe"
        found = standard_locations(TOOL_SOURCES["python"], environ=ENV,
                                   expand=lambda pattern: [python39, python312] if "Programs" in pattern else [])
        self.assertEqual(found[:2], [python312, python39])
        ffmpeg9 = self.package.replace("ffmpeg-8.1", "ffmpeg-9.1")
        ffmpeg10 = self.package.replace("ffmpeg-8.1", "ffmpeg-10.0")
        found = standard_locations(TOOL_SOURCES["ffmpeg"], environ=ENV, expand=lambda pattern: [ffmpeg9, ffmpeg10])
        self.assertEqual(found[2:], [ffmpeg10, ffmpeg9])

    def test_a_chosen_python_that_is_gone_is_kept_not_replaced(self) -> None:
        # Python keeps its rule: a chosen Python that is missing is reported, never swapped for another.
        from unittest.mock import patch
        from media_manglers_workbench import resources
        from media_manglers_workbench.tool_sources import ToolLookup
        with patch.object(resources, "find_tool", return_value=ToolLookup(r"C:\Other\python.exe", "PATH")):
            found = resources.discover_runtime_resources({"dependency_python_path": r"C:\Gone\python.exe"})
        self.assertEqual(found.python_exe, r"C:\Gone\python.exe")

    def test_which_rows_offer_download(self) -> None:
        self.assertTrue(needs_download(DependencyStatus("FFmpeg", "needs_setup", key="ffmpeg")))
        self.assertTrue(needs_download(DependencyStatus("yt-dlp", "update_recommended", key="ytdlp")))
        self.assertTrue(needs_download(DependencyStatus("VLC media player", "optional", key="vlc")))
        self.assertFalse(needs_download(DependencyStatus("FFmpeg", "ready", key="ffmpeg")))
        self.assertFalse(needs_download(DependencyStatus("FFmpeg", "unavailable", key="ffmpeg")))
        self.assertFalse(needs_download(DependencyStatus("CUDA", "optional", key="cuda")))


def _script_table(script_name: str) -> dict[str, dict[str, object]]:
    ps = textwrap.dedent(
        f"""
        $ErrorActionPreference = 'Stop'
        $tokens = $null; $errors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile('{REPO_ROOT / script_name}', [ref]$tokens, [ref]$errors)
        $ast.FindAll({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-ToolSource' }}, $true) |
            ForEach-Object {{ Invoke-Expression $_.Extent.Text }}
        $table = @{{}}
        foreach ($key in @('ffmpeg', 'ffprobe', 'ytdlp', 'python', 'whisper')) {{
            $source = Get-ToolSource -Key $key
            $table[$key] = @{{ Name = $source.Name; Page = $source.Page; WingetId = $source.WingetId;
                Standard = @($source.Standard | ForEach-Object {{ ,@($_[0], $_[1]) }}) }}
        }}
        $table | ConvertTo-Json -Depth 5 -Compress
        """
    ).strip()
    with tempfile.TemporaryDirectory() as temp:
        harness = Path(temp) / "table.ps1"
        harness.write_text(ps, encoding="utf-8")
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
            capture_output=True, text=True, check=False, timeout=120,
        )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    return json.loads(completed.stdout)


class ScriptTableTests(unittest.TestCase):
    def test_both_scripts_carry_the_workbench_table(self) -> None:
        for script in ("Video Mangler.ps1", "Audio Mangler.ps1"):
            table = _script_table(script)
            for key, entry in table.items():
                with self.subTest(script=script, key=key):
                    source = TOOL_SOURCES[key]
                    self.assertEqual(entry["Page"], source.page)
                    self.assertEqual(entry["WingetId"], source.winget_id)
                    standard = [tuple(item) for item in (entry["Standard"] or [])]
                    self.assertEqual(standard, list(source.standard))


if __name__ == "__main__":
    unittest.main()
