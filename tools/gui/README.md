# Video Mangler Workbench Deployment

## Build and test from a fresh clone

Everything below runs from the repository root on 64-bit Windows 10 or 11. Nothing is installed
system-wide by these steps: the build-only Python and its packages go into the repository's
git-ignored `AREA51\TEMP\workbench-build` folder.

You need, once:

- Git, to clone the repository.
- The Windows SDK, for its manifest tool (`mt.exe`), which the build uses to check the
  executable's high-DPI manifest: `winget install --id Microsoft.WindowsSDK.10.0.26100 -e`.
- FFmpeg (includes FFprobe), which many tests use, on `PATH`: `winget install --id Gyan.FFmpeg -e`.
  Open a new PowerShell window after installing it.
- An internet connection for the first build, which downloads Python.org's checksum-verified
  embeddable Python 3.12.10 and the pinned PySide6 and PyInstaller packages from PyPI.
- A short folder path for the clone. Some tests create files more than 200 characters deep inside
  the repository, and Windows refuses paths longer than 260 characters unless long-path support is
  turned on. A clone at a path of 35 characters or fewer, such as `C:\src\media-manglers`, passes
  every test; a clone 53 characters deep failed tests in `tests\test_review_inbox_relocation.py`
  with `unable to open database file`.

1. Clone the repository into a short folder and open PowerShell in it:

   ```powershell
   git clone https://github.com/Aintologic/media-manglers.git C:\src\media-manglers
   cd C:\src\media-manglers
   ```

2. Build the Workbench. The first build also sets up the build-only Python; later builds can leave
   out `-InstallBuildDependencies -AllowToolDownloads`:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File tools\gui\Build-VideoManglerWorkbench.ps1 -Engine PyInstaller -InstallBuildDependencies -AllowToolDownloads -UsePython312BuildRuntime -SmokeTest
   ```

   It ends with `Video Mangler Workbench standalone build complete.` and the build identity, which
   says `CLEAN` only when `git status` shows no changes, untracked files included. The program is
   `dist\VideoManglerWorkbench\VideoManglerWorkbench.exe`; the whole `dist\VideoManglerWorkbench`
   folder is what a release zips.

3. Add the two test-only packages to the same build-only Python:

   ```powershell
   AREA51\TEMP\workbench-build\python-3.12.10-embed-amd64\python.exe -m pip install --disable-pip-version-check pytest==9.1.1 numpy==2.5.3
   ```

4. Run the whole test suite, spread over up to six processes. It prints one `PASSED` or `FAILED`
   line at the end and keeps each process's log under `AREA51\TEMP\test-runs\<time>\`:

   ```powershell
   AREA51\TEMP\workbench-build\python-3.12.10-embed-amd64\python.exe tools\validation\run_tests_parallel.py
   ```

   Tests never use your own Workbench settings, library or folders: `tests\conftest.py` points
   every one of them at scratch folders inside the clone, so do not set the `MEDIA_MANGLERS_*`
   folder variables yourself for a test run. About 30 tests are skipped, each with its reason: most
   compare today's code with a commit from the project's earlier development history, which a
   clone of this repository does not contain, and two need uncommitted local recording cases.
   A test that fails only in the parallel run can be checked by running its file on its own (see
   below) before treating it as a real failure.

To run one test file instead, set `$env:QT_QPA_PLATFORM = 'offscreen'` (or the GUI tests open
real windows) and run `AREA51\TEMP\workbench-build\python-3.12.10-embed-amd64\python.exe -m pytest tests\<file>.py -q -p no:cacheprovider -o "pythonpath=."`.
Before contributing, see `tools/privacy/README.md` for the privacy check that every pull request
must pass.

## How the build works

The supported Windows build uses PyInstaller in one-folder mode. PyInstaller uses a prebuilt Windows bootloader and packages the existing Python and Qt modules without compiling the Workbench through a C/C++ toolchain.

Qt for Python's official `pyside6-deploy` configuration remains checked in as a diagnostic reference. It is not the default on an operator workstation. Even with low-memory mode, one compiler job, and link-time optimization disabled, the Nuitka path exhausted Windows commit on the validation host (`0xC000012D`, `STATUS_COMMITMENT_LIMIT`). The wrapper refuses that engine unless `-Engine PySideDeploy -AllowNuitkaBuild` is explicitly supplied.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\gui\Build-VideoManglerWorkbench.ps1 -Engine PyInstaller -InstallBuildDependencies -AllowToolDownloads -UsePython312BuildRuntime -SmokeTest
```

`-InstallBuildDependencies` installs the declared PySide6 and PyInstaller versions only into the project-scoped build environment under the repository's local-only `AREA51\TEMP\workbench-build` folder (override with `-BuildRoot`). `-UsePython312BuildRuntime` uses Python.org's checksum-verified embeddable Python 3.12.10. `-AllowToolDownloads` explicitly permits that build-only Python and the declared PyPI packages. The default path does not download a compiler, does not compile a bootloader, and does not change the machine's registered Python installation.

The required output is:

```text
dist\VideoManglerWorkbench\VideoManglerWorkbench.exe
```

The standalone folder also contains the proven `Video Mangler.ps1` backend, the `python-core` helper source, glossaries, icon, version, license, third-party notices, and a `licenses` folder with the licence texts of the components the package bundles.

It also carries Media Manglers' own tools in its `runtime` folder (installer plan, Stages 4 and 5), assembled by `tools\installer\Build-PackagedRuntime.ps1` from parts pinned by SHA-256 in `tools\installer\components.lock.json`. The build fetches each part once into `AREA51\TEMP\workbench-build\components` (a `.partial` file, checked, then renamed) and stops on any mismatch:

- `runtime\python`: the Python 3.12.10 embeddable package, Microsoft's C++ runtime DLLs beside `python.exe` (accepted only when they match their pins and carry a valid Microsoft signature), a static `python312._pth`, the Whisper code (a wheel built here from the pinned source with the pinned setuptools, no pip), truststore, the start-up hook that gives this Python its downloaded speech libraries, and `speech-lock.json` (the speech libraries the first-launch setup downloads). Everything is compiled to bytecode at build time.
- `runtime\ffmpeg`: `bin` from the pinned FFmpeg-Builds win64 gpl-shared 8.1 build, without ffplay, with its `LICENSE.txt` and a `README.txt` saying where its source is offered. The build checks it against `tools\installer\ffmpeg-needs.json`, every encoder, decoder, filter and format the app uses, and stops if one is missing.

The speech libraries and Whisper models are not in the package; the app downloads them on the user's PC after asking. `tools\installer\ffmpeg_source_bundle.py` builds FFmpeg's complete Corresponding Source, and a mirror of the pinned FFmpeg file, from `tools\installer\ffmpeg-source-pins.json`; both are kept for publishing next to a release, never published by the build.

The checked-in Per-Monitor V2 manifest is embedded by PyInstaller while it assembles the executable. The wrapper reads that resource back with the Windows SDK manifest tool and fails the build if `PerMonitorV2` is absent; it does not rewrite the finished PyInstaller executable.

Before smoke launch, the wrapper also checks every bundled PySide6 and shiboken6 DLL/PYD against the SHA-256 of its build-runtime source. It retries any mismatched PyInstaller copy once and fails the build if parity is not restored. This prevents a damaged Qt import table from reaching an operator package.

Use `-DryRun` to inspect the selected deployment command without building. Use `-SmokeTest` to launch the packaged executable offscreen, once, from fresh settings, and require a clean exit within 30 seconds; a launch still running then is recorded (what was running, the app's log, where each thread was waiting) and fails the build (159). `-Clean` removes both the prior output and project-scoped build runtime; omit it for normal repeat builds.

## What the package redistributes (138)

The package hands out third-party binaries, so their notices travel with it:

- Qt for Python (PySide6/Shiboken) and the Qt libraries and plugins it carries, under the LGPL-3.0;
- the FFmpeg libraries inside Qt Multimedia (`avcodec`, `avformat`, `avutil`, `swresample`, `swscale`), which the built-in player uses, under the LGPL-2.1 or later. These are not the `ffmpeg.exe`/`ffprobe.exe` programs the reviews use, which are the separate GPL build in `runtime\ffmpeg`;
- the Python runtime, the Mesa software OpenGL that Qt ships, and the PyInstaller bootloader;
- in `runtime`: FFmpeg 8.1 (GPL-3.0-or-later), Python 3.12.10, the Microsoft C++ runtime, openai-whisper and truststore.

`THIRD_PARTY_NOTICES.txt` names each one with its version, licence, licence text and source, and says how a recipient replaces the LGPL libraries: the one-folder layout keeps every Qt and FFmpeg library a separate file under `_internal\PySide6` and `_internal\shiboken6`. The licence texts are copied into the package's `licenses` folder from `licenses\` in the repository, plus the Python runtime's `LICENSE.txt` and PyInstaller's `COPYING.txt` from the build runtime. The build fails if a text or a notice entry is missing, if the notice does not name the bundled PySide6 version, or if the package ships an FFmpeg library the notice does not list.

The spec leaves two things out: Qt Virtual Keyboard, which Qt offers only under the GPL-3.0 and the Workbench does not use, and Qt's OpenSSL TLS backend, which would ship whatever OpenSSL the build PC has on PATH. When PySide6 is upgraded, update the versions in `THIRD_PARTY_NOTICES.txt` in the same change.
