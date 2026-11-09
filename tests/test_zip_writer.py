"""209: one long-path-safe ZIP writer for every ZIP the app builds.

Full Review's AI review ZIP copied its files with plain listings, so a folder whose own path was
past the Windows limit was skipped with no error, the gap 197 fixed in the portable ZIP. Both ZIPs
now go through media_manglers.core.zip_writer. These hold whether or not Windows long paths are on.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.core.zip_writer import list_files, local_io_path, write_zip  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "Video Mangler.ps1"


@contextlib.contextmanager
def _long_temp():
    """A temporary folder removed through the long-path form, which plain cleanup cannot do."""

    folder = tempfile.mkdtemp()
    try:
        yield folder
    finally:
        shutil.rmtree(local_io_path(Path(folder)), ignore_errors=True)


def _make(path: Path, data: bytes = b"synthetic") -> Path:
    local_io_path(path.parent).mkdir(parents=True, exist_ok=True)
    local_io_path(path).write_bytes(data)
    return path


@unittest.skipUnless(os.name == "nt", "Windows extended-length paths only")
class ZipWriterTests(unittest.TestCase):
    def test_files_under_a_too_long_folder_are_listed_and_written(self) -> None:
        with _long_temp() as temp:
            root = Path(temp) / "package"
            deep = root / ("a" * 120) / ("b" * 120) / ("c" * 40)
            files = [_make(deep / "notes.md"), _make(root / "top.txt"), _make(root / "skip.wav")]
            listed = list_files(root, exclude_suffixes={".wav"})
            result = write_zip(Path(temp) / "out.zip", [
                {"source": str(root), "name": "pkg", "exclude_suffixes": [".wav"]},
                {"name": "made/README.txt", "data": "made for the ZIP"},
            ])
            with zipfile.ZipFile(Path(temp) / "out.zip") as archive:
                names = set(archive.namelist())
                made = archive.read("made/README.txt").decode("utf-8")
        self.assertGreater(len(str(deep)), 260)
        self.assertEqual(listed, sorted(files[:2], key=lambda path: path.relative_to(root).as_posix().lower()))
        self.assertIn("pkg/" + files[0].relative_to(root).as_posix(), names)
        self.assertIn("pkg/top.txt", names)
        self.assertNotIn("pkg/skip.wav", names)
        self.assertEqual((made, result["file_count"]), ("made for the ZIP", 3))

    def test_full_reviews_zip_keeps_files_under_a_too_long_folder(self) -> None:
        with _long_temp() as temp:
            package = Path(temp) / "review"
            frames = "frames_10s"
            _make(package / frames / "frame_000001.jpg", b"\xff\xd8jpeg\xff\xd9")
            (package / "frame_index.csv").write_text('"filename","timestamp"\n"frame_000001.jpg","00:00:00"\n', encoding="utf-8")
            _make(package / "audio" / "audio.mp3")
            _make(package / "audio" / "transcript_source.wav")
            deep = package / "transcript" / ("t" * 120) / ("u" * 120)
            _make(deep / "track_02_transcript.txt", b"the first Brooklands livery")
            _make(package / "transcript" / "transcript.txt")
            zip_path = package / "ai_review_package.zip"
            source = textwrap.dedent(
                f"""
                $ErrorActionPreference = 'Stop'
                $tokens = $null; $parseErrors = $null
                $ast = [System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', [ref]$tokens, [ref]$parseErrors)
                foreach ($node in $ast.FindAll({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Parent -is [System.Management.Automation.Language.NamedBlockAst] }}, $false)) {{
                    Invoke-Expression $node.Extent.Text
                }}
                function Write-MMProgressV1 {{ }}
                $script:CurrentLogFile = $null
                $PythonExe = '{sys.executable}'
                $script:MediaManglersPythonCliInfo = [pscustomobject]@{{ Enabled = $true; Root = '{REPO_ROOT / "src"}'; EntryPoint = '' }}
                $item = [pscustomobject]@{{ OutputPath = '{package}'; FramesFolderName = '{frames}'; SourceVideoName = 'clip.mkv';
                    TranslationTargets = @(); CodexEvidenceStatus = 'not_requested'; CodexEvidenceOutputRoot = '' }}
                $result = New-AiReviewZipPackage -ProcessedItem $item -MaxSizeMb 50 -PanelCropMode 'Off'
                [Console]::Out.WriteLine((@{{ zip = [string]$result.ZipPath; frames = [int]$result.IncludedFrameCount }} | ConvertTo-Json -Compress))
                """
            ).strip()
            harness = Path(temp) / "harness.ps1"
            harness.write_text(source, encoding="utf-8")
            run = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                                 capture_output=True, text=True, timeout=300)
            self.assertEqual(run.returncode, 0, run.stdout[-3000:] + run.stderr[-3000:])
            result = json.loads(run.stdout.strip().splitlines()[-1])
            with zipfile.ZipFile(zip_path) as archive:
                names = set(archive.namelist())
        self.assertEqual(Path(result["zip"]), zip_path)
        self.assertGreater(len(str(deep)), 260)
        self.assertIn("transcript/" + (deep / "track_02_transcript.txt").relative_to(package / "transcript").as_posix(), names)
        for expected in ("transcript/transcript.txt", "audio/audio.mp3", "audio/TRANSCRIPT_SOURCE_WAV_OMITTED.txt",
                         f"{frames}/frame_000001.jpg", "frame_index.csv", "README_FOR_AI.txt"):
            self.assertIn(expected, names)
        self.assertNotIn("audio/transcript_source.wav", names)


if __name__ == "__main__":
    unittest.main()
