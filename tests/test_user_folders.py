"""Where the apps keep things, and the refusal to keep results in a temp folder (127)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers.core import user_folders  # noqa: E402
from media_manglers.core.user_folders import (  # noqa: E402
    ALLOW_TEMP_OUTPUT_ENV,
    VIDEOS_OVERRIDE_ENV,
    is_temporary_folder,
    temporary_folder_problem,
    videos_folder,
)
from media_manglers_workbench.settings import build_default_settings  # noqa: E402


def _without(*names: str) -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key not in names}


class UserFolderTests(unittest.TestCase):
    def test_override_keeps_tests_out_of_real_folders(self) -> None:
        with patch.dict(os.environ, {VIDEOS_OVERRIDE_ENV: r"Q:\Somewhere\Videos"}):
            self.assertEqual(videos_folder(), Path(r"Q:\Somewhere\Videos"))
            settings = build_default_settings()
        self.assertEqual(Path(settings["output_folder"]), Path(r"Q:\Somewhere\Videos") / "Media Mangler")
        self.assertEqual(Path(settings["default_input_folder"]), Path(r"Q:\Somewhere\Videos"))

    @unittest.skipUnless(sys.platform == "win32", "Windows known folders")
    def test_windows_uses_the_known_videos_folder(self) -> None:
        with patch.dict(os.environ, _without(VIDEOS_OVERRIDE_ENV), clear=True):
            found = videos_folder()
        expected = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('MyVideos')"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertEqual(os.path.normcase(str(found)), os.path.normcase(expected))
        self.assertFalse(is_temporary_folder(found))

    def test_linux_reads_the_xdg_user_folders(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            (home / ".config").mkdir()
            (home / ".config" / "user-dirs.dirs").write_text(
                '# written by xdg-user-dirs-update\nXDG_VIDEOS_DIR="$HOME/Filme"\nXDG_MUSIC_DIR="$HOME/Musik"\n',
                encoding="utf-8",
            )
            with patch.dict(os.environ, _without("XDG_VIDEOS_DIR", "XDG_MUSIC_DIR", "XDG_CONFIG_HOME"), clear=True):
                self.assertEqual(user_folders._xdg_user_folder("videos", home), Path(f"{home}/Filme"))
                self.assertEqual(user_folders._xdg_user_folder("music", home), Path(f"{home}/Musik"))
            (home / ".config" / "user-dirs.dirs").unlink()
            with patch.dict(os.environ, _without("XDG_VIDEOS_DIR", "XDG_CONFIG_HOME"), clear=True):
                self.assertEqual(user_folders._xdg_user_folder("videos", home), home / "Videos")

    def test_temp_folders_are_recognised(self) -> None:
        temp = Path(tempfile.gettempdir())
        for path in (temp, temp / "anything", r"C:\work\temp\_VIDEO_OUTPUT", r"D:\scratch\temp", r"C:\TEMP", r"C:\tmp\out"):
            with self.subTest(path=str(path)):
                self.assertTrue(is_temporary_folder(path))
        for path in ("", r"C:\Users\Example\Videos\Media Mangler", r"D:\Projects\Temp Videos", r"D:\Temporary\out"):
            with self.subTest(path=str(path)):
                self.assertFalse(is_temporary_folder(path))

    def test_problem_is_reported_unless_tests_allow_it(self) -> None:
        with patch.dict(os.environ, _without(ALLOW_TEMP_OUTPUT_ENV), clear=True):
            problem = temporary_folder_problem(r"C:\work\temp\_VIDEO_OUTPUT")
            self.assertIn("is a temporary folder", problem)
            self.assertIn("Choose a folder you keep", problem)
            self.assertEqual(temporary_folder_problem(r"D:\Kept\Videos"), "")
        with patch.dict(os.environ, {ALLOW_TEMP_OUTPUT_ENV: "1"}):
            self.assertEqual(temporary_folder_problem(r"C:\work\temp\_VIDEO_OUTPUT"), "")


@unittest.skipUnless(sys.platform == "win32", "Windows PowerShell")
class ScriptFolderTests(unittest.TestCase):
    """The same rules inside Video Mangler.ps1 and Audio Mangler.ps1, run from the scripts themselves."""

    FUNCTIONS = ("Get-MediaManglersDefaultFolderBase", "Test-IsTemporaryFolder",
                 "Assert-FoldersAreNotTemporary", "Resolve-DefaultInputOutputFolders")

    def _run(self, script: str, body: str, env: dict[str, str]) -> dict:
        names = ",".join(f"'{name}'" for name in self.FUNCTIONS)
        source = textwrap.dedent(
            """
            $ErrorActionPreference = 'Stop'
            $tokens = $null; $parseErrors = $null
            $ast = [System.Management.Automation.Language.Parser]::ParseFile('SCRIPT', [ref]$tokens, [ref]$parseErrors)
            $wanted = @(NAMES)
            foreach ($node in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $wanted -contains $n.Name }, $true)) {
                Invoke-Expression $node.Extent.Text
            }
            """
        ).replace("SCRIPT", str(REPO_ROOT / script)).replace("NAMES", names) + textwrap.dedent(body)
        with tempfile.TemporaryDirectory() as temp:
            harness = Path(temp) / "harness.ps1"
            harness.write_text(source, encoding="utf-8")
            run = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                capture_output=True, text=True, timeout=60, env=env,
            )
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        return json.loads(run.stdout.strip().splitlines()[-1])

    def test_defaults_are_the_users_own_folders_never_a_temp_folder(self) -> None:
        body = """
            $r = Resolve-DefaultInputOutputFolders -CurrentInputFolder '' -CurrentOutputFolder '' -NoPrompt
            [PSCustomObject]@{ input = $r.InputFolder; output = $r.OutputFolder;
                videos = [Environment]::GetFolderPath('MyVideos'); music = [Environment]::GetFolderPath('MyMusic') } | ConvertTo-Json -Compress
        """
        real = _without("MEDIA_MANGLERS_VIDEOS_FOLDER", "MEDIA_MANGLERS_MUSIC_FOLDER")
        for script, folder, prefix in (("Video Mangler.ps1", "videos", "_VIDEO"), ("Audio Mangler.ps1", "music", "_AUDIO")):
            with self.subTest(script=script):
                result = self._run(script, body, real)
                base = Path(result[folder]) / "Media Mangler"
                self.assertEqual(Path(result["input"]), base / f"{prefix}_INPUT")
                self.assertEqual(Path(result["output"]), base / f"{prefix}_OUTPUT")
                self.assertNotIn("TEMP", result["output"].upper())
                overridden = self._run(script, body, {**os.environ, "MEDIA_MANGLERS_VIDEOS_FOLDER": r"Q:\V",
                                                      "MEDIA_MANGLERS_MUSIC_FOLDER": r"Q:\M"})
                expected = r"Q:\V" if folder == "videos" else r"Q:\M"
                self.assertEqual(overridden["output"], expected + rf"\Media Mangler\{prefix}_OUTPUT")

    def test_a_temp_output_folder_is_refused_and_a_temp_input_folder_warned(self) -> None:
        body = r"""
            $temp = Join-Path ([System.IO.Path]::GetTempPath()) 'mm-out'
            $cases = [ordered]@{}
            foreach ($path in @($temp, 'C:\work\temp\_VIDEO_OUTPUT', 'C:\tmp\x', 'D:\Projects\Temp Videos', 'D:\Kept\Videos', '')) {
                $cases[$path] = Test-IsTemporaryFolder -Path $path
            }
            $refused = ''
            try { Assert-FoldersAreNotTemporary -InputFolder 'D:\Kept\In' -OutputFolder 'C:\work\temp\_VIDEO_OUTPUT' } catch { $refused = $_.Exception.Message }
            $warned = Assert-FoldersAreNotTemporary -InputFolder 'C:\work\temp\_VIDEO_INPUT' -OutputFolder 'D:\Kept\Out' 3>&1 | Out-String
            $env:MEDIA_MANGLERS_ALLOW_TEMP_OUTPUT = '1'
            $allowed = 'yes'
            try { Assert-FoldersAreNotTemporary -InputFolder '' -OutputFolder 'C:\work\temp\_VIDEO_OUTPUT' } catch { $allowed = 'no' }
            [PSCustomObject]@{ cases = $cases; refused = $refused; warned = $warned; allowed = $allowed } | ConvertTo-Json -Compress
        """
        env = _without(ALLOW_TEMP_OUTPUT_ENV)
        # Audio Mangler keeps its own copy of the rule until it joins the engine or is retired (Wave 11).
        for script in ("Audio Mangler.ps1",):
            with self.subTest(script=script):
                result = self._run(script, body, env)
                self.assertEqual(list(result["cases"].values()), [True, True, True, False, False, False])
                self.assertIn("is a temporary folder", result["refused"])
                self.assertIn("-OutputFolder", result["refused"])
                self.assertIn("input folder", result["warned"])
                self.assertEqual(result["allowed"], "yes")

    def test_video_mangler_asks_the_one_rule_the_workbench_uses(self) -> None:
        # 211: Video Mangler has no copy of the rule; it asks media_manglers.core.user_folders.
        script_text = (REPO_ROOT / "Video Mangler.ps1").read_text(encoding="utf-8-sig")
        self.assertNotIn("function Test-IsTemporaryFolder", script_text)
        body = r"""
            function Write-MMProgressV1 { }
            $PythonExe = 'PYTHON'
            $refused = ''
            try { Assert-FoldersAreNotTemporary -InputFolder 'D:\Kept\In' -OutputFolder 'C:\work\temp\_VIDEO_OUTPUT' } catch { $refused = $_.Exception.Message }
            $warned = Assert-FoldersAreNotTemporary -InputFolder 'C:\work\temp\_VIDEO_INPUT' -OutputFolder 'D:\Kept\Out' 3>&1 | Out-String
            $kept = 'yes'
            try { Assert-FoldersAreNotTemporary -InputFolder '' -OutputFolder 'D:\Kept\Videos' } catch { $kept = 'no' }
            $env:MEDIA_MANGLERS_ALLOW_TEMP_OUTPUT = '1'
            $allowed = 'yes'
            try { Assert-FoldersAreNotTemporary -InputFolder '' -OutputFolder 'C:\work\temp\_VIDEO_OUTPUT' } catch { $allowed = 'no' }
            [PSCustomObject]@{ refused = $refused; warned = $warned; kept = $kept; allowed = $allowed } | ConvertTo-Json -Compress
        """.replace("PYTHON", sys.executable)
        source = textwrap.dedent(
            f"""
            $ErrorActionPreference = 'Stop'
            $tokens = $null; $parseErrors = $null
            $ast = [System.Management.Automation.Language.Parser]::ParseFile('{REPO_ROOT / "Video Mangler.ps1"}', [ref]$tokens, [ref]$parseErrors)
            foreach ($node in $ast.FindAll({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Parent -is [System.Management.Automation.Language.NamedBlockAst] }}, $false)) {{
                Invoke-Expression $node.Extent.Text
            }}
            $script:MediaManglersPythonCliInfo = [pscustomobject]@{{ Enabled = $true; Root = '{REPO_ROOT / "src"}'; EntryPoint = '' }}
            """
        ) + textwrap.dedent(body)
        with tempfile.TemporaryDirectory() as temp:
            harness = Path(temp) / "harness.ps1"
            harness.write_text(source, encoding="utf-8")
            run = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                                 capture_output=True, text=True, timeout=180, env=_without(ALLOW_TEMP_OUTPUT_ENV))
        self.assertEqual(run.returncode, 0, run.stdout[-2000:] + run.stderr[-2000:])
        result = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertIn("is a temporary folder", result["refused"])
        self.assertIn("-OutputFolder", result["refused"])
        self.assertIn("input folder", result["warned"])
        self.assertEqual((result["kept"], result["allowed"]), ("yes", "yes"))

    def test_the_real_scripts_refuse_before_writing_and_name_only_the_users_folders(self) -> None:
        env = _without(ALLOW_TEMP_OUTPUT_ENV)
        for script, extension in (("Video Mangler.ps1", "mkv"), ("Audio Mangler.ps1", "mp3")):
            with self.subTest(script=script), tempfile.TemporaryDirectory() as temp:
                output = Path(temp) / "results"
                base = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(REPO_ROOT / script),
                        "-InputPath", str(Path(temp) / f"missing.{extension}"), "-OutputFolder", str(output), "-NoPrompt"]
                only_output = subprocess.run(base, capture_output=True, text=True, timeout=120, env=env)
                self.assertNotEqual(only_output.returncode, 0)
                said = only_output.stdout + only_output.stderr
                self.assertIn("is a temporary folder", said)
                self.assertNotIn("input folder", said, "a worked-out input folder is not the user's to fix")
                self.assertFalse(output.exists(), "nothing is written before the refusal")
                named_input = subprocess.run(base + ["-InputFolder", str(Path(temp) / "in")],
                                             capture_output=True, text=True, timeout=120, env=env)
                self.assertIn("input folder", named_input.stdout + named_input.stderr)


if __name__ == "__main__":
    unittest.main()
