from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
GUI_TOOLS = REPO_ROOT / "tools" / "gui"


class WorkbenchDeploymentTests(unittest.TestCase):
    def _dependency_selection(self, engine: str, *, pyside_ready: bool) -> dict[str, object]:
        script = (GUI_TOOLS / "Build-VideoManglerWorkbench.ps1").read_text(encoding="utf-8")
        start = script.index("[string[]]$venvPackages = @(")
        end = script.index("& $buildPython -m pip install", start)
        selection = script[start:end]
        command = "\n".join(
            (
                f'$Engine = "{engine}"',
                f"$pysideReady = ${str(pyside_ready).lower()}",
                selection,
                "@{ Type = $venvPackages.GetType().FullName; "
                "Count = @($venvPackages).Count; Values = @($venvPackages) } "
                "| ConvertTo-Json -Compress",
            )
        )
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def test_pyinstaller_is_safe_default_and_nuitka_requires_override(self) -> None:
        script = (GUI_TOOLS / "Build-VideoManglerWorkbench.ps1").read_text(encoding="utf-8")
        self.assertIn('[string]$Engine = "PyInstaller"', script)
        self.assertIn('[switch]$AllowNuitkaBuild', script)
        self.assertIn('if ($Engine -eq "PySideDeploy" -and -not $AllowNuitkaBuild', script)
        self.assertIn('Join-Path $targetRoot "VideoManglerWorkbench.exe"', script)

    def test_pyinstaller_uses_onedir_collect_and_embeds_manifest_before_archive(self) -> None:
        spec = (GUI_TOOLS / "VideoManglerWorkbench.pyinstaller.spec").read_text(encoding="utf-8")
        self.assertIn("coll = COLLECT(", spec)
        self.assertIn("manifest=str(manifest_path)", spec)
        self.assertIn("version=str(version_path)", spec)
        self.assertNotIn("onefile", spec.lower())
        self.assertNotIn('"PySide6.QtMultimedia",', spec)
        # The built-in player needs the widgets module as well; neither may
        # ever land in the excludes list.
        self.assertNotIn('"PySide6.QtMultimediaWidgets",', spec)
        self.assertIn('"media_manglers.core.review_queue"', spec)

    def test_pyinstaller_keeps_voice_detection_libraries_out_of_the_package(self) -> None:
        # The Workbench imports the spotter phrase list from voice_track, whose
        # detection functions import numpy (and, on the backend, whisper and
        # torch) internally. PyInstaller follows those, and the Workbench never
        # runs detection in its own process, so they stay out of the package.
        spec = (GUI_TOOLS / "VideoManglerWorkbench.pyinstaller.spec").read_text(encoding="utf-8")
        excludes = spec.split("excludes=[", 1)[1].split("]", 1)[0]
        for name in ("numpy", "torch", "whisper"):
            self.assertIn(f'"{name}",', excludes)

    def test_workbench_never_needs_numpy_to_import(self) -> None:
        # Excluding numpy from the package is only safe while importing the
        # Workbench does not load it. A fresh interpreter proves that.
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0, 'src'); "
                "import media_manglers_workbench.app; "
                "print('numpy' in sys.modules)",
            ],
            cwd=str(REPO_ROOT),
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip().splitlines()[-1], "False")

        script = (GUI_TOOLS / "Build-VideoManglerWorkbench.ps1").read_text(encoding="utf-8")
        guarded_rewrite = re.compile(
            r'if \(\$Engine -eq "PySideDeploy"\) \{\s*& \$mtExe "-manifest"',
            re.MULTILINE,
        )
        self.assertRegex(script, guarded_rewrite)

    def test_deployment_resources_are_versioned_and_high_dpi(self) -> None:
        manifest = (GUI_TOOLS / "VideoManglerWorkbench.manifest").read_text(encoding="utf-8")
        version = (GUI_TOOLS / "VideoManglerWorkbench.version.txt").read_text(encoding="utf-8")
        self.assertIn("PerMonitorV2", manifest)
        self.assertIn("longPathAware", manifest)
        self.assertIn("0.11.0.0", version)
        self.assertIn("VideoManglerWorkbench.exe", version)

    def test_a_hung_smoke_launch_is_recorded_stopped_and_fails_the_build(self) -> None:
        # 159: closing no longer waits for the readiness check, so one launch that has not ended
        # in 30 seconds is a real hang: it is recorded, stopped and fails the build, with no retry
        # to hide it. Any crash fails too, and each build's launch starts from fresh settings.
        script = (GUI_TOOLS / "Build-VideoManglerWorkbench.ps1").read_text(encoding="utf-8")
        block = script[script.index("    if ($SmokeTest) {"):script.index("$versionInfo = ")]
        self.assertNotIn("$attempt", block)
        self.assertEqual(block.count("Start-Process -FilePath $targetExe"), 1)
        self.assertIn("WaitForExit(30000)", block)
        self.assertNotIn("WaitForExit(180000)", block)
        self.assertIn("smoke launch failed with exit code", block)
        self.assertIn("What was running", block)
        self.assertIn("Stop-Process", block)
        self.assertIn('throw "Packaged executable smoke launch timed out after 30 seconds."', block)
        self.assertIn("Remove-VerifiedPath -Path $smokeRoot -Root $BuildRoot", block)
        self.assertLess(block.index("Remove-VerifiedPath -Path $smokeRoot"), block.index("Start-Process"))
        # The stacks are kept beside the build, and the build says the limit the app really uses.
        self.assertIn("smoke-launch-stacks-", block)
        app_source = (REPO_ROOT / "src" / "media_manglers_workbench" / "app.py").read_text(encoding="utf-8")
        self.assertIn("SMOKE_STACK_AFTER_SECONDS = 15", app_source)
        self.assertIn("written by the app after 15 seconds", block)

    def test_the_package_carries_the_notices_and_licence_texts_of_what_it_bundles(self) -> None:
        # 138: Qt for Python and the FFmpeg libraries inside Qt Multimedia are handed out under
        # the LGPL. The notice names each bundled part with its licence, the texts ship in the
        # package, and the build fails rather than ship without them.
        notices = (REPO_ROOT / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8")
        section = notices[notices.index("Bundled with the packaged Workbench"):]
        script = (GUI_TOOLS / "Build-VideoManglerWorkbench.ps1").read_text(encoding="utf-8")
        pinned = re.search(r'"PySide6==([0-9.]+)"', script)
        self.assertIsNotNone(pinned, "the build pins a PySide6 version")
        self.assertIn(f"Qt for Python (PySide6) {pinned.group(1)}", section)
        for text in (
            "GNU Lesser General Public License version 3",
            "GNU Lesser General Public License version 2.1 or later",
            "avcodec-61.dll", "avformat-61.dll", "avutil-59.dll", "swresample-5.dll", "swscale-8.dll",
            "ffmpegmediaplugin.dll", "Python 3.12.10", "opengl32sw.dll", "PyInstaller",
            "Replacing the LGPL libraries", "_internal\\PySide6", "_internal\\shiboken6",
            "https://ffmpeg.org/releases/ffmpeg-7.1.3.tar.xz",
            "https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.1-src/",
        ):
            self.assertIn(text, section, text)
        for name, first_lines in {
            "LGPL-3.0.txt": ("GNU LESSER GENERAL PUBLIC LICENSE", "Version 3, 29 June 2007"),
            "GPL-3.0.txt": ("GNU GENERAL PUBLIC LICENSE", "Version 3, 29 June 2007"),
            "LGPL-2.1.txt": ("GNU LESSER GENERAL PUBLIC LICENSE", "Version 2.1, February 1999"),
            "zlib.txt": ("Copyright (C) 1995-2024 Jean-loup Gailly and Mark Adler",),
            "Qt-third-party.txt": ("Third-party code inside the Qt libraries",),
            "Mesa-MIT.txt": ("Mesa 3D graphics library", "MIT License"),
            "Python-incorporated-software.txt": ("CPython v3.12.10",),
        }.items():
            text = (REPO_ROOT / "licenses" / name).read_text(encoding="utf-8")
            for line in first_lines:
                self.assertIn(line, text[:400], name)
            self.assertIn(f"licenses\\{name}", notices, f"the notice points to {name}")
        self.assertIn("Copy-AndAssertPackagedLicences -BuildPython $buildPython -PackageRoot $targetRoot", script)
        self.assertIn('Copy-Item -Path (Join-Path $repoRoot "licenses\\*") -Destination $licencesTarget', script)
        for check in ("Python-LICENSE.txt", "PyInstaller-COPYING.txt",
                      "does not name the bundled PySide6 version", "which THIRD_PARTY_NOTICES.txt does not list"):
            self.assertIn(check, script)
        # The classic script ZIPs share the notices file; the section says it is about the Workbench.
        self.assertIn("This section applies only to the packaged Workbench folder", section)

    def test_the_spec_leaves_out_the_gpl_only_keyboard_and_the_path_openssl(self) -> None:
        # 138: Qt Virtual Keyboard is GPL-3.0 only and unused; the OpenSSL TLS backend would ship
        # the OpenSSL on the build PC's PATH, so the package would differ from PC to PC.
        spec = (GUI_TOOLS / "VideoManglerWorkbench.pyinstaller.spec").read_text(encoding="utf-8")
        for name in ("qt6virtualkeyboard.dll", "qtvirtualkeyboardplugin.dll", "qopensslbackend.dll",
                     "libssl-3-x64.dll", "libcrypto-3-x64.dll"):
            self.assertIn(f'"{name}"', spec)
        self.assertIn("a.binaries = [entry for entry in a.binaries if Path(entry[0]).name.lower() not in LEFT_OUT_BINARIES]", spec)
        self.assertLess(spec.index("a.binaries = [entry"), spec.index("coll = COLLECT("))

    def test_the_build_refuses_while_the_workbench_runs_from_its_folder(self) -> None:
        # 179: the check comes before every removal of the app folder, so a running Workbench is
        # never left half-deleted.
        script = (GUI_TOOLS / "Build-VideoManglerWorkbench.ps1").read_text(encoding="utf-8")
        self.assertIn("function Assert-NothingRunningFrom", script)
        removals = [i for i in range(len(script)) if script.startswith("Remove-VerifiedPath -Path $targetRoot", i)]
        self.assertTrue(removals)
        for at in removals:
            # The check sits just above each removal (within the same few lines).
            self.assertIn("Assert-NothingRunningFrom -Root $targetRoot", script[max(0, at - 600):at],
                          "each removal of the app folder is preceded by the check")

    def test_deployment_copies_complete_workbench_help_and_correction_backend(self) -> None:
        script = (GUI_TOOLS / "Build-VideoManglerWorkbench.ps1").read_text(encoding="utf-8")
        self.assertIn('"docs\\workbench"', script)
        for name in (
            "README.md",
            "WORKFLOW_HELP.md",
            "TROUBLESHOOTING.md",
            "SCREENSHOT_MAINTENANCE.md",
        ):
            self.assertTrue((REPO_ROOT / "docs" / "workbench" / name).is_file())
        self.assertTrue(
            (REPO_ROOT / "src" / "media_manglers" / "core" / "transcript_corrections.py").is_file()
        )
        self.assertIn('"src\\media_manglers\\core\\review_orchestration.py"', script)
        self.assertIn('"src\\media_manglers\\core\\review_queue.py"', script)
        self.assertIn('"src\\media_manglers_workbench\\audio_detection.py"', script)
        self.assertIn("Assert-PythonBackendSidecarImports", script)
        self.assertIn("root = pathlib.Path(sys.argv[1]).resolve()", script)
        self.assertIn("$BuildPython -I -B $probePath $sourceRoot", script)
        self.assertNotIn("$BuildPython -I -c $probe", script)

        release_script = (
            REPO_ROOT / "tools" / "release" / "Build-Exe.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn('"src\\media_manglers_workbench\\__init__.py"', release_script)
        self.assertIn('"src\\media_manglers_workbench\\audio_detection.py"', release_script)

    def test_deployment_embeds_generated_build_identity(self) -> None:
        script = (GUI_TOOLS / "Build-VideoManglerWorkbench.ps1").read_text(encoding="utf-8")
        spec = (GUI_TOOLS / "VideoManglerWorkbench.pyinstaller.spec").read_text(encoding="utf-8")
        self.assertIn('full_git_commit = $fullGitCommit', script)
        self.assertIn('dirty = $dirtyBuild', script)
        self.assertIn('validation_label = $ValidationLabel', script)
        self.assertIn('MEDIA_MANGLERS_BUILD_IDENTITY_PATH', spec)
        self.assertIn('"media_manglers_workbench"', spec)

    def test_deployment_repairs_and_verifies_frozen_qt_runtime_hashes(self) -> None:
        script = (GUI_TOOLS / "Build-VideoManglerWorkbench.ps1").read_text(encoding="utf-8")
        self.assertIn("Repair-AndAssertPackagedQtRuntimeIntegrity", script)
        self.assertIn('foreach ($family in @("PySide6", "shiboken6"))', script)
        self.assertIn("Get-FileHash -LiteralPath $sourceFile -Algorithm SHA256", script)
        self.assertIn("Packaged Qt runtime integrity verification failed", script)

    def test_windows_powershell_preserves_complete_dependency_arguments(self) -> None:
        pyinstaller = self._dependency_selection("PyInstaller", pyside_ready=True)
        self.assertEqual(pyinstaller["Type"], "System.String[]")
        self.assertEqual(pyinstaller["Count"], 1)
        self.assertEqual(pyinstaller["Values"], ["PyInstaller==6.21.0"])

        pyinstaller_with_pyside = self._dependency_selection(
            "PyInstaller", pyside_ready=False
        )
        self.assertEqual(pyinstaller_with_pyside["Type"], "System.String[]")
        self.assertEqual(
            pyinstaller_with_pyside["Values"],
            ["PyInstaller==6.21.0", "PySide6==6.11.1"],
        )

        pyside_deploy = self._dependency_selection("PySideDeploy", pyside_ready=True)
        self.assertEqual(pyside_deploy["Type"], "System.String[]")
        self.assertEqual(
            pyside_deploy["Values"],
            ["Nuitka==4.0", "ordered-set", "zstandard"],
        )


if __name__ == "__main__":
    unittest.main()
