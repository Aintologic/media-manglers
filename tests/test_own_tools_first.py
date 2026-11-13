"""Installer plan, Stage 1: both editions use Media Manglers' own tools first, simply and predictably.

- The lookup order: the chosen path, then (FFprobe) beside the FFmpeg in use, then the bundled copy in the
  packaged application folder's runtime folder, then PATH, then the tool's own install folders. The
  Workbench (``tool_sources.find_tool``) and the backend (``Resolve-ExecutablePath``) agree.
- Python: a chosen Python as before; otherwise our private Python, except in the two kept cases (a Python
  on the PC with working CUDA while ours has none; local translation needing Argos, which ours lacks). The
  Workbench (``dependencies.select_python``) and the backend (``Select-PreferredWhisperPythonInterpreter``)
  choose the same Python for the same probes.
- ``use_addons`` acts only for our private Python; ``addons_root`` honours the test override and is the only
  place the add-ons path is built.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers.core import private_runtime, user_folders  # noqa: E402
from media_manglers_workbench import dependencies, resources, tool_sources  # noqa: E402
from media_manglers_workbench.dependencies import (  # noqa: E402
    KEPT_FOR_ARGOS,
    KEPT_FOR_GRAPHICS_CARD,
    select_python,
    translation_needs_argos,
)
from media_manglers_workbench.tool_sources import (  # noqa: E402
    FOUND_BUNDLED,
    FOUND_CHOSEN,
    FOUND_DOWNLOADED,
    FOUND_ON_PC,
    FOUND_WINDOWS,
    find_tool,
    found_by_text,
)

SCRIPT = REPO_ROOT / "Video Mangler.ps1"
AUDIO_SCRIPT = REPO_ROOT / "Audio Mangler.ps1"
ENV = {"LOCALAPPDATA": r"C:\Users\Someone\AppData\Local", "ProgramFiles": r"C:\Program Files",
       "SystemRoot": r"C:\Windows"}
BUNDLED = r"C:\Apps\Media Manglers\runtime"


def _finder(files: set[str], on_path: dict[str, str] | None = None):
    on_path = on_path or {}
    lowered = {item.casefold() for item in files}
    return dict(
        which=lambda name: on_path.get(name),
        is_file=lambda path: str(path).casefold() in lowered,
        environ=ENV,
        expand=lambda pattern: [item for item in files if Path(item).match(pattern)],
    )


def _powershell(source: str, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as temp:
        harness = Path(temp) / "harness.ps1"
        harness.write_text(source, encoding="utf-8")
        return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                              capture_output=True, text=True, timeout=timeout, check=False)


def _load_functions(script: Path, names: list[str]) -> str:
    quoted = ", ".join(f"'{name}'" for name in names)
    return textwrap.dedent(
        f"""
        $tokens = $null; $parseErrors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile('{script}', [ref]$tokens, [ref]$parseErrors)
        foreach ($name in @({quoted})) {{
            $node = $ast.Find({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }}, $true)
            if (-not $node) {{ throw "missing function $name" }}
            . ([scriptblock]::Create($node.Extent.Text))
        }}
        """
    ).strip()


# The lookup order ------------------------------------------------------------------------------------------


class LookupOrderTests(unittest.TestCase):
    ffmpeg = BUNDLED + r"\ffmpeg\bin\ffmpeg.exe"
    ffprobe = BUNDLED + r"\ffmpeg\bin\ffprobe.exe"
    python = BUNDLED + r"\python\python.exe"
    links = r"C:\Users\Someone\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"

    def test_the_bundled_copy_comes_after_the_chosen_path_and_before_path_and_install_folders(self) -> None:
        on_path = {"ffmpeg.exe": r"C:\Path\ffmpeg.exe"}
        found = find_tool("ffmpeg", bundled_dir=BUNDLED, **_finder({self.ffmpeg, self.links, on_path["ffmpeg.exe"]}, on_path))
        self.assertEqual((found.path, found.found_by), (self.ffmpeg, "bundled"))
        chosen = r"C:\Tools\ffmpeg.exe"
        found = find_tool("ffmpeg", chosen, bundled_dir=BUNDLED, **_finder({chosen, self.ffmpeg}))
        self.assertEqual((found.path, found.found_by), (chosen, "chosen"))
        # Without the bundled copy the order is as it was: PATH, then the install folders.
        found = find_tool("ffmpeg", bundled_dir=BUNDLED, **_finder({self.links, on_path["ffmpeg.exe"]}, on_path))
        self.assertEqual((found.path, found.found_by), (r"C:\Path\ffmpeg.exe", "PATH"))

    def test_a_chosen_path_that_is_gone_gives_way_to_the_bundled_copy_and_says_so(self) -> None:
        found = find_tool("ffmpeg", r"C:\Old\ffmpeg.exe", bundled_dir=BUNDLED, **_finder({self.ffmpeg, self.links}))
        self.assertEqual((found.path, found.found_by), (self.ffmpeg, "bundled"))
        self.assertIn("Your chosen path is missing", found.note)

    def test_ffprobe_beside_a_chosen_ffmpeg_first_then_ours(self) -> None:
        beside = r"C:\Tools\ffprobe.exe"
        found = find_tool("ffprobe", beside=r"C:\Tools\ffmpeg.exe", bundled_dir=BUNDLED,
                          **_finder({beside, self.ffprobe}))
        self.assertEqual((found.path, found.found_by), (beside, "beside FFmpeg"))
        found = find_tool("ffprobe", beside=self.ffmpeg, bundled_dir=BUNDLED, **_finder({self.ffprobe}))
        self.assertEqual((found.path, found.found_by), (self.ffprobe, "bundled"))
        found = find_tool("ffprobe", bundled_dir=BUNDLED, **_finder({self.ffprobe}, {"ffprobe.exe": r"C:\Path\ffprobe.exe"}))
        self.assertEqual((found.path, found.found_by), (self.ffprobe, "bundled"))

    def test_python_and_tools_we_do_not_ship(self) -> None:
        found = find_tool("python", bundled_dir=BUNDLED, **_finder({self.python}, {"python.exe": r"C:\Py\python.exe"}))
        self.assertEqual((found.path, found.found_by), (self.python, "bundled"))
        # yt-dlp is not bundled: its order is unchanged.
        found = find_tool("ytdlp", bundled_dir=BUNDLED, **_finder(set(), {"yt-dlp.exe": r"C:\Path\yt-dlp.exe"}))
        self.assertEqual(found.found_by, "PATH")

    def test_the_bundled_folder_is_anchored_on_the_program_never_the_current_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
                os.environ, {resources.RUNTIME_ROOT_OVERRIDE: str(Path(temp) / "elsewhere")}):
            app = Path(temp) / "Media Manglers"
            exe = app / "VideoManglerWorkbench.exe"
            self.assertEqual(tool_sources.bundled_tools_dir(str(exe)), (app / "runtime").resolve())
            # Run by our private Python, the application folder is the one above runtime\python.
            private = app / "runtime" / "python" / "python.exe"
            self.assertEqual(tool_sources.bundled_tools_dir(str(private)), (app / "runtime").resolve())
            previous = os.getcwd()
            os.chdir(temp)
            try:
                self.assertEqual(tool_sources.bundled_tools_dir(str(exe)), (app / "runtime").resolve())
            finally:
                os.chdir(previous)

    def test_where_each_row_says_the_tool_came_from(self) -> None:
        self.assertEqual(found_by_text(self.ffmpeg, bundled_dir=BUNDLED, environ=ENV), FOUND_BUNDLED)
        self.assertEqual(found_by_text(r"C:\Tools\ffmpeg.exe", chosen=r"c:\tools\FFMPEG.exe", bundled_dir=BUNDLED,
                                       environ=ENV), FOUND_CHOSEN)
        self.assertEqual(found_by_text(self.links, bundled_dir=BUNDLED, environ=ENV), FOUND_ON_PC)
        self.assertEqual(found_by_text(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe", environ=ENV),
                         FOUND_WINDOWS)
        self.assertEqual(found_by_text(r"C:\Users\Someone\AppData\Local\MediaManglers\addons\sp-1\torch\__init__.py",
                                       downloaded_dir=r"C:\Users\Someone\AppData\Local\MediaManglers\addons",
                                       environ=ENV), FOUND_DOWNLOADED)
        self.assertEqual(found_by_text("", environ=ENV), "")


class DiscoveredResourcesTests(unittest.TestCase):
    """The Workbench's start-up lookup with a real bundled folder on disk."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = Path(self.temp.name) / "Media Manglers" / "runtime"
        for relative in (r"ffmpeg\bin\ffmpeg.exe", r"ffmpeg\bin\ffprobe.exe", r"python\python.exe"):
            path = self.runtime / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"placeholder")
        self.patch = mock.patch.object(resources, "bundled_tools_dir", return_value=self.runtime)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.temp.cleanup()

    def test_our_own_tools_are_used_and_labelled(self) -> None:
        found = resources.discover_runtime_resources({})
        self.assertEqual(found.ffmpeg_exe, str(self.runtime / "ffmpeg" / "bin" / "ffmpeg.exe"))
        self.assertEqual(found.ffprobe_exe, str(self.runtime / "ffmpeg" / "bin" / "ffprobe.exe"))
        self.assertEqual(found.python_exe, str(self.runtime / "python" / "python.exe"))
        self.assertEqual(found.bundled_dir, str(self.runtime))
        rows = {item.key: item for item in found.dependencies}
        for key in ("python", "ffmpeg", "ffprobe"):
            self.assertEqual(rows[key].found_by, FOUND_BUNDLED, key)

    def test_a_chosen_path_still_wins_and_a_chosen_python_that_is_gone_is_kept(self) -> None:
        chosen = Path(self.temp.name) / "Tools" / "ffmpeg.exe"
        chosen.parent.mkdir()
        chosen.write_bytes(b"placeholder")
        found = resources.discover_runtime_resources({"dependency_ffmpeg_path": str(chosen),
                                                      "dependency_python_path": r"C:\Gone\python.exe"})
        self.assertEqual(found.ffmpeg_exe, str(chosen))
        self.assertEqual(found.python_exe, r"C:\Gone\python.exe")
        rows = {item.key: item for item in found.dependencies}
        self.assertEqual(rows["ffmpeg"].found_by, FOUND_CHOSEN)
        # FFprobe beside the chosen FFmpeg is not there, so ours is used.
        self.assertEqual(found.ffprobe_exe, str(self.runtime / "ffmpeg" / "bin" / "ffprobe.exe"))

    def test_a_source_run_has_no_bundled_folder(self) -> None:
        self.patch.stop()
        try:
            found = resources.discover_runtime_resources({})
            self.assertEqual(found.bundled_dir, "")
        finally:
            self.patch.start()


# The choice of Python ---------------------------------------------------------------------------------------


def _probe(**values: object) -> dict[str, object]:
    probe: dict[str, object] = {"python_version": "3.12.10", "helper_import_ok": True, "whisper_import_ok": True,
                                "torch_import_ok": True, "cuda_available": False, "argos_available": False}
    probe.update(values)
    return probe


# (name, our probe or None, [(other name, probe)], translation needs Argos, expected name, expected note)
SCENARIOS = [
    ("ours when nothing else can do more", _probe(), [("cpu", _probe())], False, "ours", ""),
    ("a Python with working CUDA is kept", _probe(), [("cpu", _probe()), ("gpu", _probe(cuda_available=True))], False,
     "gpu", KEPT_FOR_GRAPHICS_CARD),
    ("CUDA without the helper is not enough", _probe(),
     [("gpu", _probe(cuda_available=True, helper_import_ok=False))], False, "ours", ""),
    ("ours with CUDA keeps ours", _probe(cuda_available=True), [("gpu", _probe(cuda_available=True))], False, "ours", ""),
    ("Argos is kept only when local translation needs it", _probe(), [("argos", _probe(argos_available=True))], True,
     "argos", KEPT_FOR_ARGOS),
    ("no translation, no Argos exception", _probe(), [("argos", _probe(argos_available=True))], False, "ours", ""),
    ("ours with Argos keeps ours", _probe(argos_available=True), [("argos", _probe(argos_available=True))], True,
     "ours", ""),
    ("ours before its speech libraries are set up is still ours", _probe(whisper_import_ok=False, torch_import_ok=False),
     [("cpu", _probe())], False, "ours", ""),
    ("a damaged copy of ours falls back to the healthiest", _probe(helper_import_ok=False),
     [("cpu", _probe()), ("gpu", _probe(cuda_available=True))], False, "gpu", ""),
    ("without ours, the healthiest as before", None, [("cpu", _probe()), ("gpu", _probe(cuda_available=True))], False,
     "gpu", ""),
]


class SelectPythonTests(unittest.TestCase):
    def test_each_case(self) -> None:
        for name, ours, others, argos, expected, note in SCENARIOS:
            with self.subTest(name):
                results = ([("ours", ours)] if ours is not None else []) + list(others)
                private = "ours" if ours is not None else ""
                path, _probe_found, kept = select_python(results, private, translation_needs_argos=argos)
                self.assertEqual(Path(path).name, expected)
                self.assertEqual(kept, note)

    def test_translation_needs_argos(self) -> None:
        self.assertTrue(translation_needs_argos({"translate_to": "de", "processing_mode": "Local"}))
        # M13 of the Wave I-A review: Argos runs only in Local mode, and only for a target other than English.
        self.assertFalse(translation_needs_argos({"translate_to": "de", "processing_mode": "Hybrid"}))
        self.assertFalse(translation_needs_argos({"translate_to": "en", "processing_mode": "Local"}))
        self.assertTrue(translation_needs_argos({"translate_to": "en,de", "processing_mode": "Local"}))
        self.assertTrue(translation_needs_argos({"translate_to": "de"}))
        self.assertFalse(translation_needs_argos({"translate_to": "de", "processing_mode": "AI"}))
        self.assertFalse(translation_needs_argos({"translate_to": "", "processing_mode": "Local"}))

    def test_the_readiness_check_uses_ours_and_says_why_it_kept_another(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = root / "app" / "runtime"
            ours = runtime / "python" / "python.exe"
            gpu = root / "Python312" / "python.exe"
            for path in (ours, gpu):
                path.parent.mkdir(parents=True)
                path.write_bytes(b"placeholder")
            payloads = {str(ours.resolve()): _probe(), str(gpu.resolve()): _probe(cuda_available=True)}

            def runner(argv, _timeout, _env):
                executable = str(Path(argv[0]).resolve())
                if executable in payloads and "-c" in argv:
                    return subprocess.CompletedProcess(argv, 0, json.dumps({**payloads[executable],
                                                                            "python_path": executable}), "")
                return subprocess.CompletedProcess(argv, 1, "", "synthetic")

            res = resources.RuntimeResources(app_root=REPO_ROOT, script_path=None, backend_source_root=None,
                                             icon_path=None, powershell_exe="", python_exe=str(ours), ffmpeg_exe="",
                                             ffprobe_exe="", packaged=True, bundled_dir=str(runtime))
            result = dependencies.run_dependency_preflight(res, selected_model="base.en", runner=runner,
                                                           python_candidates=[str(gpu)])
            row = next(item for item in result.dependencies if item.key == "python")
            self.assertEqual(Path(result.python_exe).resolve(), gpu.resolve())
            self.assertEqual(row.detail, KEPT_FOR_GRAPHICS_CARD)
            self.assertEqual(row.found_by, FOUND_ON_PC)
            # Without the graphics card there, ours is used, and its row says so.
            payloads[str(gpu.resolve())] = _probe()
            result = dependencies.run_dependency_preflight(res, selected_model="base.en", runner=runner,
                                                           python_candidates=[str(gpu)])
            row = next(item for item in result.dependencies if item.key == "python")
            self.assertEqual(Path(result.python_exe).resolve(), ours.resolve())
            self.assertEqual(row.found_by, FOUND_BUNDLED)
            # A chosen Python is the only one looked at, ours included.
            result = dependencies.run_dependency_preflight(res, selected_model="base.en", runner=runner,
                                                           configured_python=str(gpu))
            self.assertEqual(Path(result.python_exe).resolve(), gpu.resolve())


def _ps_probe(probe: dict[str, object]) -> dict[str, object]:
    return {"HelperImportOk": probe["helper_import_ok"], "PythonVersion": probe["python_version"],
            "WhisperImportOk": probe["whisper_import_ok"], "TorchImportOk": probe["torch_import_ok"],
            "CudaAvailable": probe["cuda_available"], "ArgosAvailable": probe["argos_available"], "PythonPath": ""}


class BackendAgreesTests(unittest.TestCase):
    """The backend's own choice (a run of the script on its own) agrees with the Workbench's, case by case."""

    def test_the_backend_chooses_the_same_python(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = root / "app" / "runtime"
            (runtime / "python").mkdir(parents=True)
            (runtime / "python" / "python.exe").write_bytes(b"placeholder")
            cases = []
            for name, ours, others, argos, _expected, _note in SCENARIOS:
                cases.append({"name": name, "ours": _ps_probe(ours) if ours is not None else None,
                              "others": [{"name": other, "probe": _ps_probe(probe)} for other, probe in others],
                              "argos": argos})
            data = root / "cases.json"
            data.write_text(json.dumps(cases), encoding="utf-8")
            source = _load_functions(SCRIPT, ["Get-ToolSource", "Get-BundledToolsRoot", "Get-BundledToolPath",
                                              "Select-PreferredWhisperPythonInterpreter"]) + textwrap.dedent(
                f"""

                $results = @()
                foreach ($case in (Get-Content -LiteralPath '{data}' -Raw | ConvertFrom-Json)) {{
                    $script:BundledToolsRoot = if ($case.ours) {{ '{runtime}' }} else {{ '{root / "none"}' }}
                    $private = Get-BundledToolPath -Key 'python'
                    $script:Probes = @{{}}
                    $script:Paths = @()
                    if ($case.ours) {{ $script:Probes[$private] = $case.ours; $script:Paths += $private }}
                    foreach ($other in $case.others) {{
                        $path = 'C:\\Elsewhere\\' + $other.name + '\\python.exe'
                        $script:Probes[$path] = $other.probe
                        $script:Paths += $path
                    }}
                    function Get-AutoPythonInterpreterCandidates {{ param([string]$PrimaryPythonCommand) return $script:Paths }}
                    function Get-WhisperExecutionMode {{ param([string]$PythonCommand) return $script:Probes[$PythonCommand] }}
                    $chosen = Select-PreferredWhisperPythonInterpreter -PrimaryPythonCommand $script:Paths[0] -TranslationNeedsArgos:([bool]$case.argos)
                    $name = if ($private -and $chosen.Path -eq $private) {{ 'ours' }} else {{ Split-Path (Split-Path $chosen.Path -Parent) -Leaf }}
                    $results += [pscustomobject]@{{ name = $case.name; chosen = $name; note = [string]$chosen.Note }}
                }}
                $results | ConvertTo-Json -Compress
                """)
            run = _powershell(source)
            self.assertEqual(run.returncode, 0, run.stderr)
            found = {item["name"]: item for item in json.loads(run.stdout.strip().splitlines()[-1])}
        for name, _ours, _others, _argos, expected, note in SCENARIOS:
            with self.subTest(name):
                self.assertEqual(found[name]["chosen"], expected)
                if note:
                    self.assertEqual(found[name]["note"], note)

    def test_the_backend_rule_for_local_translation_matches(self) -> None:
        cases = [(["de"], "Local"), (["de"], "Hybrid"), (["de"], ""), (["de"], "AI"), ([], "Local"), (["en"], "Local"),
                 (["en", "de"], "Local"), (["en"], "Hybrid")]
        lines = "\n".join(
            f"[Console]::Out.WriteLine([string](Test-TranslationNeedsArgos -TranslationTargets @({', '.join(repr(t) for t in targets)}) -Mode '{mode}'))"
            for targets, mode in cases)
        run = _powershell(_load_functions(SCRIPT, ["Test-TranslationNeedsArgos"]) + "\n" + lines)
        self.assertEqual(run.returncode, 0, run.stderr)
        answers = [line.strip() == "True" for line in run.stdout.strip().splitlines()]
        expected = [translation_needs_argos({"translate_to": ",".join(t), "processing_mode": m}) for t, m in cases]
        self.assertEqual(answers, expected)


class BackendLookupTests(unittest.TestCase):
    def test_both_scripts_find_our_own_tools_after_the_path_given(self) -> None:
        for script in (SCRIPT, AUDIO_SCRIPT):
            with self.subTest(script=script.name), tempfile.TemporaryDirectory() as temp:
                runtime = Path(temp) / "runtime"
                for relative in (r"ffmpeg\bin\ffmpeg.exe", r"ffmpeg\bin\ffprobe.exe", r"python\python.exe"):
                    path = runtime / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"placeholder")
                chosen = Path(temp) / "chosen" / "ffmpeg.exe"
                chosen.parent.mkdir()
                chosen.write_bytes(b"placeholder")
                source = _load_functions(script, ["Get-ToolSource", "Get-BundledToolsRoot", "Get-BundledToolPath",
                                                  "Get-ToolStandardLocations", "Get-ToolGetItText",
                                                  "Resolve-ExecutablePath", "Get-FFprobePath"]) + textwrap.dedent(
                    f"""

                    $script:BundledToolsRoot = '{runtime}'
                    [Console]::Out.WriteLine((Resolve-ExecutablePath -PreferredPath '{Path(temp) / "gone" / "ffmpeg.exe"}' -FallbackCommands @() -ToolName 'FFmpeg' -ToolKey 'ffmpeg'))
                    [Console]::Out.WriteLine((Resolve-ExecutablePath -PreferredPath '{chosen}' -FallbackCommands @() -ToolName 'FFmpeg' -ToolKey 'ffmpeg'))
                    [Console]::Out.WriteLine((Get-FFprobePath -FFmpegExe '{chosen}'))
                    """)
                run = _powershell(source)
                self.assertEqual(run.returncode, 0, run.stderr)
                lines = [Path(line.strip()) for line in run.stdout.strip().splitlines()]
                self.assertEqual(lines[0], runtime / "ffmpeg" / "bin" / "ffmpeg.exe")
                self.assertEqual(lines[1], chosen)
                # FFprobe is not beside the chosen FFmpeg, so ours is next.
                self.assertEqual(lines[2], runtime / "ffmpeg" / "bin" / "ffprobe.exe")

    def test_the_backend_uses_our_python_unless_one_is_given(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp) / "runtime"
            (runtime / "python").mkdir(parents=True)
            (runtime / "python" / "python.exe").write_bytes(b"placeholder")
            given = Path(temp) / "mine" / "python.exe"
            given.parent.mkdir()
            given.write_bytes(b"placeholder")
            source = _load_functions(SCRIPT, ["Get-ToolSource", "Get-BundledToolsRoot", "Get-BundledToolPath",
                                              "Get-ToolGetItText", "Resolve-CommandOrPath",
                                              "Resolve-PythonInterpreterPath"]) + textwrap.dedent(
                f"""

                $script:BundledToolsRoot = '{runtime}'
                [Console]::Out.WriteLine((Resolve-PythonInterpreterPath -RequestedValue 'python'))
                [Console]::Out.WriteLine((Resolve-PythonInterpreterPath -RequestedValue '{given}' -WasExplicitlySet))
                """)
            run = _powershell(source)
            self.assertEqual(run.returncode, 0, run.stderr)
            lines = [Path(line.strip()) for line in run.stdout.strip().splitlines()]
            self.assertEqual(lines, [runtime / "python" / "python.exe", given])


# Our add-ons, only for our Python -----------------------------------------------------------------------------


class AddonsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.local = self.root / "local"
        self.env = mock.patch.dict(os.environ, {user_folders.WORKBENCH_LOCALAPPDATA_ENV: str(self.local)})
        self.env.start()
        self.app = self.root / "Media Manglers"
        (self.app / "runtime" / "python").mkdir(parents=True)
        (self.app / "Video Mangler.ps1").write_text("# placeholder\n", encoding="utf-8")
        self.private = self.app / "runtime" / "python" / "python.exe"
        self.private.write_bytes(b"placeholder")
        (self.app / "runtime" / "python" / "speech-lock.json").write_text(json.dumps({"set_id": "b1f4a3eb"}),
                                                                         encoding="utf-8")

    def tearDown(self) -> None:
        self.env.stop()
        self.temp.cleanup()

    def test_addons_root_honours_the_test_override(self) -> None:
        self.assertEqual(user_folders.addons_root(), self.local / "MediaManglers" / "addons")
        with mock.patch.dict(os.environ, {user_folders.WORKBENCH_LOCALAPPDATA_ENV: ""}), \
                mock.patch.object(user_folders, "local_data_root", return_value=Path(r"C:\Users\Someone\AppData\Local")):
            self.assertEqual(user_folders.addons_root(), Path(r"C:\Users\Someone\AppData\Local\MediaManglers\addons"))

    def test_use_addons_acts_only_for_our_private_python(self) -> None:
        folder = user_folders.addons_root() / "sp-b1f4a3eb"
        folder.mkdir(parents=True)
        path: list[str] = [r"C:\somewhere"]
        self.assertEqual(private_runtime.use_addons(self.private, path), folder)
        self.assertEqual(path, [r"C:\somewhere", str(folder)])
        # Once only.
        private_runtime.use_addons(self.private, path)
        self.assertEqual(path.count(str(folder)), 1)
        # pythonw.exe is ours too.
        (self.app / "runtime" / "python" / "pythonw.exe").write_bytes(b"placeholder")
        self.assertEqual(private_runtime.use_addons(self.app / "runtime" / "python" / "pythonw.exe", []), folder)
        # A Python on the PC, even one in a folder named python, is never given our files.
        other = self.root / "Python312" / "python.exe"
        other.parent.mkdir()
        other.write_bytes(b"placeholder")
        lookalike = self.root / "other" / "runtime" / "python" / "python.exe"
        lookalike.parent.mkdir(parents=True)
        lookalike.write_bytes(b"placeholder")
        for python in (other, lookalike, Path(sys.executable)):
            untouched: list[str] = []
            self.assertIsNone(private_runtime.use_addons(python, untouched), python)
            self.assertEqual(untouched, [])
        self.assertFalse(private_runtime.is_private_python(sys.executable))

    def test_nothing_is_added_before_the_set_is_downloaded_or_when_none_is_named(self) -> None:
        self.assertIsNone(private_runtime.use_addons(self.private, []))
        (self.app / "runtime" / "python" / "speech-lock.json").write_text("{}", encoding="utf-8")
        (user_folders.addons_root() / "sp-b1f4a3eb").mkdir(parents=True)
        self.assertIsNone(private_runtime.use_addons(self.private, []))

    def test_the_helper_never_imports_a_speech_library_before_use_addons_runs(self) -> None:
        # cli.main calls use_addons first; that is in time only while importing the helper loads none of them.
        code = ("import sys; import media_manglers.cli; "
                "print([m for m in ('numpy', 'torch', 'whisper', 'tiktoken', 'numba') if m in sys.modules])")
        run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False,
                             env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}, cwd=str(REPO_ROOT / "src"))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stdout.strip(), "[]")

    def test_addons_root_is_the_only_place_the_addons_path_is_built(self) -> None:
        # A code search: no other module or script names the add-ons folder as a path.
        pattern = re.compile(r"""["'\\/]addons["'\\/]|["']addons["']""", re.IGNORECASE)
        allowed = REPO_ROOT / "src" / "media_manglers" / "core" / "user_folders.py"
        found: list[str] = []
        files = [*(REPO_ROOT / "src").rglob("*.py"), *REPO_ROOT.glob("*.ps1"), *(REPO_ROOT / "tools").rglob("*.ps1"),
                 *(REPO_ROOT / "tools").rglob("*.py")]
        for path in files:
            if path == allowed or "__pycache__" in path.parts:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                code = line.split("#", 1)[0]
                if pattern.search(code):
                    found.append(f"{path.relative_to(REPO_ROOT)}:{number}")
        self.assertEqual(found, [])
        self.assertIn('ADDONS_FOLDER = "addons"', allowed.read_text(encoding="utf-8"))


# The one-time question about paths saved by an earlier version ---------------------------------------------------


class SavedPathQuestionTests(unittest.TestCase):
    def _window(self, settings: dict, bundled_dir: str):
        from media_manglers_workbench.app import WorkbenchWindow

        fake = types.SimpleNamespace(
            resources=types.SimpleNamespace(bundled_dir=bundled_dir),
            app_settings=dict(settings),
            SAVED_TOOL_PATHS=WorkbenchWindow.SAVED_TOOL_PATHS,
            asked=[],
            saved=0,
            log=[],
        )
        fake.saved_paths_differing_from_bundled = lambda: WorkbenchWindow.saved_paths_differing_from_bundled(fake)
        fake.save_app_settings = lambda: setattr(fake, "saved", fake.saved + 1)
        fake._write_workbench_log = fake.log.append
        fake.start_dependency_check = lambda: None
        return WorkbenchWindow, fake

    def test_asked_once_and_never_changed_silently(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp) / "runtime"
            (runtime / "ffmpeg" / "bin").mkdir(parents=True)
            (runtime / "ffmpeg" / "bin" / "ffmpeg.exe").write_bytes(b"placeholder")
            settings = {"dependency_ffmpeg_path": r"C:\Old\ffmpeg.exe", "dependency_ffprobe_path": "",
                        "dependency_python_path": r"C:\Python312\python.exe"}
            window_class, keep = self._window(settings, str(runtime))
            keep._choose_bundled_tools = lambda saved: keep.asked.append(saved) or False
            window_class.ask_about_saved_tool_paths(keep)
            # Only FFmpeg is bundled here, so only its saved path is asked about, and it is kept.
            self.assertEqual(keep.asked, [[r"C:\Old\ffmpeg.exe"]])
            self.assertEqual(keep.app_settings["dependency_ffmpeg_path"], r"C:\Old\ffmpeg.exe")
            self.assertTrue(keep.app_settings["bundled_tools_question_answered"])
            window_class.ask_about_saved_tool_paths(keep)
            self.assertEqual(len(keep.asked), 1, "asked only once")

            window_class, use = self._window(settings, str(runtime))
            use._choose_bundled_tools = lambda saved: True
            from media_manglers_workbench import app as app_module
            with mock.patch.object(app_module, "discover_runtime_resources", return_value="rediscovered"), \
                    mock.patch.object(app_module.QTimer, "singleShot") as later:
                window_class.ask_about_saved_tool_paths(use)
            self.assertEqual(use.app_settings["dependency_ffmpeg_path"], "")
            self.assertEqual(use.app_settings["dependency_python_path"], r"C:\Python312\python.exe")
            self.assertEqual(use.resources, "rediscovered")
            later.assert_called_once()

    def test_not_asked_without_a_bundled_copy(self) -> None:
        window_class, fake = self._window({"dependency_ffmpeg_path": r"C:\Old\ffmpeg.exe"}, "")
        fake._choose_bundled_tools = lambda saved: self.fail("must not ask")
        window_class.ask_about_saved_tool_paths(fake)
        self.assertNotIn("bundled_tools_question_answered", fake.app_settings)


if __name__ == "__main__":
    unittest.main()
