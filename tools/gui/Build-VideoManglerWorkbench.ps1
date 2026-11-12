[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$SmokeTest,
    [switch]$InstallBuildDependencies,
    [switch]$AllowToolDownloads,
    [switch]$UsePython312BuildRuntime,
    [ValidateSet("PyInstaller", "PySideDeploy")]
    [string]$Engine = "PyInstaller",
    [switch]$AllowNuitkaBuild,
    [switch]$DryRun,
    [string]$ValidationLabel = "Gate 4 validation build",
    # Empty means the repository's local-only AREA51\TEMP folder; system temp
    # folders get purged, so the build environment must not live there.
    [string]$BuildRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).ProviderPath
if ([string]::IsNullOrWhiteSpace($BuildRoot)) {
    $BuildRoot = Join-Path $repoRoot "AREA51\TEMP\workbench-build"
}
$distRoot = Join-Path $repoRoot "dist"
$officialOutput = Join-Path $distRoot "VideoManglerWorkbench.dist"
$targetRoot = Join-Path $distRoot "VideoManglerWorkbench"
$targetExe = Join-Path $targetRoot "VideoManglerWorkbench.exe"
$entryExe = Join-Path $targetRoot "video_mangler_workbench_entry.exe"
$specPath = Join-Path $PSScriptRoot "pysidedeploy.spec"
$buildSpecPath = Join-Path $PSScriptRoot "pysidedeploy.build.spec"
$pyInstallerSpecPath = Join-Path $PSScriptRoot "VideoManglerWorkbench.pyinstaller.spec"
$pyInstallerVersionPath = Join-Path $PSScriptRoot "VideoManglerWorkbench.version.txt"
$pyInstallerWorkRoot = Join-Path $BuildRoot "pyinstaller-work"
$manifestPath = Join-Path $PSScriptRoot "VideoManglerWorkbench.manifest"
$venvRoot = Join-Path $BuildRoot "venv"
$venvPython = Join-Path $venvRoot "Scripts\python.exe"
$python312Version = "3.12.10"
$python312Root = Join-Path $BuildRoot "python-$python312Version-embed-amd64"
$python312Exe = Join-Path $python312Root "python.exe"
$python312Archive = Join-Path $BuildRoot "python-$python312Version-embed-amd64.zip"
$python312Url = "https://www.python.org/ftp/python/$python312Version/python-$python312Version-embed-amd64.zip"
$python312Md5 = "FE8EF205F2E9C3BA44D0CF9954E1ABD3"
$pipZipapp = Join-Path $BuildRoot "pip.pyz"
$buildIdentityPath = Join-Path $BuildRoot "workbench-build-identity.json"

function Assert-PathWithin {
    param(
        [Parameter(Mandatory)] [string]$Path,
        [Parameter(Mandatory)] [string]$Root
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $fullRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    $prefix = $fullRoot + [System.IO.Path]::DirectorySeparatorChar
    if (-not $fullPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing filesystem operation outside approved root '$fullRoot': $fullPath"
    }
}

function Remove-VerifiedPath {
    param(
        [Parameter(Mandatory)] [string]$Path,
        [Parameter(Mandatory)] [string]$Root
    )

    Assert-PathWithin -Path $Path -Root $Root
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

function Assert-NothingRunningFrom {
    param([Parameter(Mandatory)] [string]$Root)

    # 179: clearing the folder of a running Workbench deletes every file not in use and then
    # stops, leaving a half-deleted app. Refuse first, before anything is removed.
    $fullRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
    $prefix = $fullRoot + [System.IO.Path]::DirectorySeparatorChar
    $running = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ExecutablePath -and $_.ExecutablePath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)
    })
    if ($running.Count -gt 0) {
        $names = ($running | ForEach-Object { "$($_.Name) (process $($_.ProcessId))" }) -join ", "
        throw "The Workbench is running from $fullRoot ($names). Close it, then build again. Nothing was removed."
    }
}

function Copy-PythonBackendSidecar {
    param([Parameter(Mandatory)] [string]$DestinationRoot)

    $sourcePackage = Join-Path $repoRoot "src\media_manglers"
    $sourceWorkbenchPackage = Join-Path $repoRoot "src\media_manglers_workbench"
    $destinationCore = Join-Path $DestinationRoot "python-core"
    $destinationPackage = Join-Path $destinationCore "src\media_manglers"
    $destinationWorkbenchPackage = Join-Path $destinationCore "src\media_manglers_workbench"
    if (-not (Test-Path -LiteralPath $sourcePackage -PathType Container)) {
        throw "Python backend source not found: $sourcePackage"
    }
    foreach ($sharedDependency in @(
        (Join-Path $sourceWorkbenchPackage "__init__.py"),
        (Join-Path $sourceWorkbenchPackage "audio_detection.py")
    )) {
        if (-not (Test-Path -LiteralPath $sharedDependency -PathType Leaf)) {
            throw "Shared Python backend dependency not found: $sharedDependency"
        }
    }
    New-Item -ItemType Directory -Path $destinationPackage -Force | Out-Null
    New-Item -ItemType Directory -Path $destinationWorkbenchPackage -Force | Out-Null
    Copy-Item -Path (Join-Path $sourcePackage "*") -Destination $destinationPackage -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $sourceWorkbenchPackage "__init__.py") -Destination $destinationWorkbenchPackage -Force
    Copy-Item -LiteralPath (Join-Path $sourceWorkbenchPackage "audio_detection.py") -Destination $destinationWorkbenchPackage -Force
    Copy-Item -LiteralPath (Join-Path $repoRoot "pyproject.toml") -Destination (Join-Path $destinationCore "pyproject.toml") -Force

    foreach ($cache in @(Get-ChildItem -LiteralPath $destinationCore -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue)) {
        Assert-PathWithin -Path $cache.FullName -Root $destinationCore
        Remove-Item -LiteralPath $cache.FullName -Recurse -Force
    }
    foreach ($compiled in @(Get-ChildItem -LiteralPath $destinationCore -Recurse -File -Filter "*.pyc" -ErrorAction SilentlyContinue)) {
        Assert-PathWithin -Path $compiled.FullName -Root $destinationCore
        Remove-Item -LiteralPath $compiled.FullName -Force
    }
    foreach ($required in @(
        "src\media_manglers\__main__.py",
        "src\media_manglers\cli.py",
        "src\media_manglers\core\evidence_package.py",
        "src\media_manglers\core\review_orchestration.py",
        "src\media_manglers\core\review_queue.py",
        "src\media_manglers\core\race_video\render.py",
        "src\media_manglers\core\race_video\library.py",
        "src\media_manglers\core\race_video\brief.md",
        "src\media_manglers_workbench\__init__.py",
        "src\media_manglers_workbench\audio_detection.py"
    )) {
        $requiredPath = Join-Path $destinationCore $required
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
            throw "Packaged Python backend is missing: $requiredPath"
        }
    }
}

function Assert-PythonBackendSidecarImports {
    param(
        [Parameter(Mandatory)] [string]$BuildPython,
        [Parameter(Mandatory)] [string]$PackageRoot
    )

    $sourceRoot = Join-Path $PackageRoot "python-core\src"
    $probePath = Join-Path $PackageRoot ".python-backend-import-probe.py"
    Assert-PathWithin -Path $probePath -Root $PackageRoot
    $probe = @'
import pathlib
import sys
root = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
import media_manglers
from media_manglers.core import review_preparation
from media_manglers import cli
from media_manglers.core.race_video import render as race_video_render
from media_manglers.core.race_video import library as race_video_library
from media_manglers_workbench import audio_detection
for module in (media_manglers, review_preparation, cli, race_video_render, race_video_library, audio_detection):
    origin = pathlib.Path(module.__file__).resolve()
    origin.relative_to(root)
print("PACKAGED_PYTHON_BACKEND_IMPORTS_OK")
'@
    try {
        [System.IO.File]::WriteAllText(
            $probePath,
            $probe,
            [System.Text.UTF8Encoding]::new($false)
        )
        & $BuildPython -I -B $probePath $sourceRoot
        if ($LASTEXITCODE -ne 0) {
            throw "The packaged Python backend could not import its shared audio-layout dependency from python-core."
        }
    }
    finally {
        if (Test-Path -LiteralPath $probePath -PathType Leaf) {
            Remove-Item -LiteralPath $probePath -Force
        }
    }
}

function Set-PackagedBackendNeutralBytecode {
    param(
        [Parameter(Mandatory)] [string]$BuildPython,
        [Parameter(Mandatory)] [string]$PackageRoot
    )

    $coreRoot = Join-Path $PackageRoot "python-core"
    $sourceRoot = Join-Path $coreRoot "src"
    if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) {
        throw "Packaged Python backend source not found for bytecode normalization: $sourceRoot"
    }
    # Remove any bytecode the import check may have produced, then precompile with
    # a path-neutral stored filename so the shipped .pyc never carry the build
    # machine's absolute source path (co_filename). unchecked-hash keeps the
    # precompiled bytecode valid regardless of file timestamps on the user's PC.
    foreach ($cache in @(Get-ChildItem -LiteralPath $coreRoot -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue)) {
        Assert-PathWithin -Path $cache.FullName -Root $coreRoot
        Remove-Item -LiteralPath $cache.FullName -Recurse -Force
    }
    & $BuildPython -I -m compileall -q -j 0 --invalidation-mode unchecked-hash -s $PackageRoot $sourceRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Could not precompile the packaged Python backend with a neutral source path."
    }
}

function Repair-AndAssertPackagedQtRuntimeIntegrity {
    param(
        [Parameter(Mandatory)] [string]$BuildPython,
        [Parameter(Mandatory)] [string]$PackageRoot
    )

    $sitePackages = (& $BuildPython -c "from pathlib import Path; import PySide6; print(Path(PySide6.__file__).parent.parent)").Trim()
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $sitePackages -PathType Container)) {
        throw "The build runtime's site-packages folder could not be resolved for the packaged Qt integrity gate."
    }

    foreach ($family in @("PySide6", "shiboken6")) {
        $sourceFamily = Join-Path $sitePackages $family
        $packagedFamily = Join-Path $PackageRoot "_internal\$family"
        if (-not (Test-Path -LiteralPath $packagedFamily -PathType Container)) {
            throw "The packaged Qt runtime folder is missing: $packagedFamily"
        }

        foreach ($packagedFile in @(Get-ChildItem -LiteralPath $packagedFamily -Recurse -File | Where-Object { $_.Extension -in @(".dll", ".pyd") })) {
            $relativePath = $packagedFile.FullName.Substring($packagedFamily.Length).TrimStart('\', '/')
            $sourceFile = Join-Path $sourceFamily $relativePath
            if (-not (Test-Path -LiteralPath $sourceFile -PathType Leaf)) {
                continue
            }

            $sourceHash = (Get-FileHash -LiteralPath $sourceFile -Algorithm SHA256).Hash
            $packagedHash = (Get-FileHash -LiteralPath $packagedFile.FullName -Algorithm SHA256).Hash
            if ($sourceHash -ne $packagedHash) {
                Write-Warning "Repairing a PyInstaller Qt runtime copy that failed SHA-256 parity: $family\$relativePath"
                Copy-Item -LiteralPath $sourceFile -Destination $packagedFile.FullName -Force
                $packagedHash = (Get-FileHash -LiteralPath $packagedFile.FullName -Algorithm SHA256).Hash
            }
            if ($sourceHash -ne $packagedHash) {
                throw "Packaged Qt runtime integrity verification failed: $family\$relativePath"
            }
        }
    }
}

function Copy-AndAssertPackagedLicences {
    param(
        [Parameter(Mandatory)] [string]$BuildPython,
        [Parameter(Mandatory)] [string]$PackageRoot
    )

    # 138: the package hands out Qt for Python, the FFmpeg libraries inside Qt Multimedia, the
    # Python runtime and the PyInstaller bootloader. Their licence texts go beside the program, and
    # the build fails if a text or a notice entry is missing, or if what the package ships no
    # longer matches the notice.
    $licencesTarget = Join-Path $PackageRoot "licenses"
    New-Item -ItemType Directory -Path $licencesTarget -Force | Out-Null
    Copy-Item -Path (Join-Path $repoRoot "licenses\*") -Destination $licencesTarget -Force
    $runtimeTexts = (& $BuildPython -I -c "import importlib.metadata as m, pathlib, sys; print(pathlib.Path(sys.base_prefix, 'LICENSE.txt')); print(next(f.locate() for f in m.distribution('pyinstaller').files if f.name == 'COPYING.txt')); print(m.version('PySide6'))")
    if ($LASTEXITCODE -ne 0 -or @($runtimeTexts).Count -lt 3) {
        throw "The build runtime's Python and PyInstaller licence texts could not be found."
    }
    Copy-Item -LiteralPath ([string]$runtimeTexts[0]).Trim() -Destination (Join-Path $licencesTarget "Python-LICENSE.txt") -Force
    Copy-Item -LiteralPath ([string]$runtimeTexts[1]).Trim() -Destination (Join-Path $licencesTarget "PyInstaller-COPYING.txt") -Force
    $pysideVersion = ([string]$runtimeTexts[2]).Trim()

    foreach ($name in @("LGPL-3.0.txt", "GPL-3.0.txt", "LGPL-2.1.txt", "zlib.txt", "Qt-third-party.txt", "Mesa-MIT.txt", "Python-incorporated-software.txt", "Python-LICENSE.txt", "PyInstaller-COPYING.txt")) {
        $text = Join-Path $licencesTarget $name
        if (-not (Test-Path -LiteralPath $text -PathType Leaf) -or (Get-Item -LiteralPath $text).Length -eq 0) {
            throw "A licence text is missing from the package: licenses\$name"
        }
    }
    $notices = Get-Content -LiteralPath (Join-Path $PackageRoot "THIRD_PARTY_NOTICES.txt") -Raw
    if (-not $notices.Contains("Bundled with the packaged Workbench")) {
        throw "THIRD_PARTY_NOTICES.txt has no entry for the components the package bundles."
    }
    if (-not $notices.Contains("Qt for Python (PySide6) $pysideVersion")) {
        throw "THIRD_PARTY_NOTICES.txt does not name the bundled PySide6 version ($pysideVersion)."
    }
    $qtRoot = Join-Path $PackageRoot "_internal\PySide6"
    foreach ($library in @(Get-ChildItem -LiteralPath $qtRoot -File -Filter "*.dll" | Where-Object { $_.Name -match '^(avcodec|avformat|avutil|swresample|swscale)-\d+\.dll$' })) {
        if (-not $notices.Contains($library.Name)) {
            throw "The package ships $($library.Name), which THIRD_PARTY_NOTICES.txt does not list."
        }
    }
    foreach ($leftOut in @("Qt6VirtualKeyboard.dll", "plugins\platforminputcontexts\qtvirtualkeyboardplugin.dll", "plugins\tls\qopensslbackend.dll", "..\libssl-3-x64.dll", "..\libcrypto-3-x64.dll")) {
        if (Test-Path -LiteralPath (Join-Path $qtRoot $leftOut)) {
            throw "The package still ships $leftOut, which the build leaves out."
        }
    }
}

function Find-MtExe {
    $candidates = @(
        Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin" -Recurse -Filter "mt.exe" -File -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '\\x64\\mt\.exe$' } |
            Sort-Object FullName -Descending
    )
    if ($candidates.Count -eq 0) {
        throw "Windows SDK mt.exe was not found; the high-DPI application manifest cannot be embedded."
    }
    return $candidates[0].FullName
}

foreach ($required in @(
    $specPath,
    $pyInstallerSpecPath,
    $pyInstallerVersionPath,
    $manifestPath,
    (Join-Path $repoRoot "Video Mangler.ps1"),
    (Join-Path $repoRoot "assets\Video Mangler.ico")
)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required deployment input not found: $required"
    }
}

Assert-PathWithin -Path $officialOutput -Root $distRoot
Assert-PathWithin -Path $targetRoot -Root $distRoot
Assert-PathWithin -Path $venvRoot -Root $BuildRoot
Assert-PathWithin -Path $python312Root -Root $BuildRoot
Assert-PathWithin -Path $pyInstallerWorkRoot -Root $BuildRoot

if ($Engine -eq "PySideDeploy" -and -not $AllowNuitkaBuild -and -not $DryRun) {
    throw "The Nuitka-based PySideDeploy engine is disabled by default after it exhausted Windows commit and destabilized the operator workstation. Use the default PyInstaller engine. Pass -AllowNuitkaBuild only for an explicitly approved diagnostic retry."
}

if (-not $DryRun) {
    Assert-NothingRunningFrom -Root $targetRoot
}

if ($Clean) {
    Write-Host "Cleaning the prior standalone output and project-scoped build environment..." -ForegroundColor Cyan
    Remove-VerifiedPath -Path $officialOutput -Root $distRoot
    Remove-VerifiedPath -Path $targetRoot -Root $distRoot
    Remove-VerifiedPath -Path (Join-Path $PSScriptRoot "deployment") -Root $PSScriptRoot
    Remove-VerifiedPath -Path $venvRoot -Root $BuildRoot
    Remove-VerifiedPath -Path $python312Root -Root $BuildRoot
    Remove-VerifiedPath -Path $pyInstallerWorkRoot -Root $BuildRoot
}

New-Item -ItemType Directory -Path $BuildRoot -Force | Out-Null
New-Item -ItemType Directory -Path $distRoot -Force | Out-Null

$buildPython = $venvPython
$buildEnvironmentLabel = $venvRoot
if ($UsePython312BuildRuntime) {
    if (-not $AllowToolDownloads -and -not (Test-Path -LiteralPath $python312Exe -PathType Leaf)) {
        throw "The local Python 3.12 build runtime is missing. Re-run with -AllowToolDownloads to explicitly download the Python.org embeddable package."
    }
    if (-not (Test-Path -LiteralPath $python312Exe -PathType Leaf)) {
        Write-Host "Downloading Python.org $python312Version embeddable build to $python312Archive" -ForegroundColor Yellow
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri $python312Url -OutFile $python312Archive
        $actualMd5 = (Get-FileHash -LiteralPath $python312Archive -Algorithm MD5).Hash
        if ($actualMd5 -ne $python312Md5) {
            throw "Python 3.12 embeddable archive checksum mismatch. Expected $python312Md5, got $actualMd5."
        }
        New-Item -ItemType Directory -Path $python312Root -Force | Out-Null
        Expand-Archive -LiteralPath $python312Archive -DestinationPath $python312Root -Force
        $pthFile = Get-ChildItem -LiteralPath $python312Root -Filter "python312._pth" -File | Select-Object -First 1
        if (-not $pthFile) {
            throw "The Python 3.12 embeddable path configuration was not found."
        }
        $pthLines = @([System.IO.File]::ReadAllLines($pthFile.FullName))
        $pthLines = @($pthLines | ForEach-Object { if ($_ -eq "#import site") { "import site" } else { $_ } })
        if ($pthLines -notcontains (Join-Path $repoRoot "src")) {
            $pthLines += (Join-Path $repoRoot "src")
        }
        [System.IO.File]::WriteAllLines($pthFile.FullName, $pthLines, [System.Text.UTF8Encoding]::new($false))
    }
    $buildPython = $python312Exe
    $buildEnvironmentLabel = $python312Root
}
elseif (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    $launcher = Get-Command py.exe, py, python.exe, python -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $launcher) {
        throw "Python was not found. Install a supported Python runtime before building the Workbench."
    }
    Write-Host "Creating an isolated build environment under $venvRoot" -ForegroundColor Cyan
    & $launcher.Source -m venv --system-site-packages $venvRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the Workbench build environment."
    }
}

$pysideReady = $true
try {
    & $buildPython -c "from PySide6 import QtCore; print(QtCore.__version__)" 2>$null | Out-Null
    $pysideReady = $LASTEXITCODE -eq 0
}
catch {
    $pysideReady = $false
}

$packagerReady = $true
if ($Engine -eq "PyInstaller") {
    try {
        & $buildPython -c "import PyInstaller; print(PyInstaller.__version__)" 2>$null | Out-Null
        $packagerReady = $LASTEXITCODE -eq 0
    }
    catch {
        $packagerReady = $false
    }
}
else {
    try {
        & $buildPython -c "import nuitka, ordered_set, zstandard" 2>$null | Out-Null
        $packagerReady = $LASTEXITCODE -eq 0
    }
    catch {
        $packagerReady = $false
    }
}

if (-not $pysideReady -or -not $packagerReady) {
    $dependencyDescription = if ($Engine -eq "PyInstaller") {
        "PySide6 6.11.1 and PyInstaller 6.21.0"
    }
    else {
        "PySide6 6.11.1, Nuitka 4.0, ordered-set, and zstandard"
    }
    if ($DryRun) {
        Write-Host "Dry run: $dependencyDescription would be required in $buildEnvironmentLabel." -ForegroundColor Yellow
    }
    elseif (-not $InstallBuildDependencies) {
        throw "Deployment dependencies are missing. Re-run with -InstallBuildDependencies to install $dependencyDescription into $buildEnvironmentLabel."
    }
    else {
        Write-Host "Installing declared build-only dependencies into ${buildEnvironmentLabel}: $dependencyDescription" -ForegroundColor Yellow
        if ($UsePython312BuildRuntime -and -not (Test-Path -LiteralPath $pipZipapp -PathType Leaf)) {
            if (-not $AllowToolDownloads) {
                throw "pip.pyz is missing. Re-run with -AllowToolDownloads to obtain it from bootstrap.pypa.io."
            }
            Invoke-WebRequest -UseBasicParsing -Uri "https://bootstrap.pypa.io/pip/pip.pyz" -OutFile $pipZipapp
        }
        if ($UsePython312BuildRuntime) {
            $sitePackages = Join-Path $python312Root "Lib\site-packages"
            New-Item -ItemType Directory -Path $sitePackages -Force | Out-Null
            [string[]]$portablePackages = @("pip", "setuptools", "wheel")
            if (-not $pysideReady) {
                $portablePackages += "PySide6==6.11.1"
            }
            if ($Engine -eq "PyInstaller") {
                $portablePackages += "PyInstaller==6.21.0"
            }
            else {
                $portablePackages += @("ordered-set", "zstandard")
            }
            & $buildPython $pipZipapp install --disable-pip-version-check --upgrade --target $sitePackages @portablePackages
            if ($LASTEXITCODE -eq 0 -and $Engine -eq "PySideDeploy") {
                & $buildPython -m pip install --disable-pip-version-check --upgrade --no-build-isolation --target $sitePackages "Nuitka==4.0"
            }
        }
        else {
            [string[]]$venvPackages = @(
                if ($Engine -eq "PyInstaller") {
                    "PyInstaller==6.21.0"
                }
                else {
                    "Nuitka==4.0"
                    "ordered-set"
                    "zstandard"
                }
            )
            if (-not $pysideReady) {
                $venvPackages += "PySide6==6.11.1"
            }
            & $buildPython -m pip install --disable-pip-version-check @venvPackages
        }
        if ($LASTEXITCODE -ne 0) {
            throw "Build dependency installation failed."
        }
    }
}

$deployScript = $null
$activeSpec = $specPath
if ($Engine -eq "PySideDeploy") {
    $deployScript = (& $buildPython -c "from pathlib import Path; import PySide6; print(Path(PySide6.__file__).parent / 'scripts' / 'deploy.py')").Trim()
    if (-not (Test-Path -LiteralPath $deployScript -PathType Leaf)) {
        throw "The official PySide6 deploy script was not found: $deployScript"
    }

    $compiler = Get-Command cl.exe, cl, gcc.exe, gcc, clang.exe, clang -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $compiler -and -not $AllowToolDownloads -and -not $DryRun) {
        throw "No supported C/C++ compiler is installed. Re-run with -AllowToolDownloads to explicitly permit Nuitka to download its supported MinGW64 toolchain."
    }
    $buildPythonVersion = (& $buildPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
    if (-not $compiler -and $AllowToolDownloads -and [version]$buildPythonVersion -ge [version]"3.13") {
        throw "Nuitka cannot use its MinGW64 toolchain with Python $buildPythonVersion. Re-run with -UsePython312BuildRuntime so the compiler and Python remain project-scoped."
    }
}

$semanticVersion = ([System.IO.File]::ReadAllText((Join-Path $repoRoot "VERSION"))).Trim()
$fileVersion = "{0}.0" -f $semanticVersion
$fullGitCommit = ""
$shortGitCommit = ""
$dirtyBuild = $null
$gitCommitOutput = @(& git -C $repoRoot rev-parse HEAD 2>$null)
if ($LASTEXITCODE -eq 0 -and $gitCommitOutput.Count -gt 0) {
    $candidateCommit = ([string]$gitCommitOutput[0]).Trim().ToLowerInvariant()
    if ($candidateCommit -match '^[0-9a-f]{40}$') {
        $fullGitCommit = $candidateCommit
        $shortGitCommit = $candidateCommit.Substring(0, 7)
    }
}
$gitStatusOutput = @(& git -C $repoRoot status --porcelain=v1 --untracked-files=normal 2>$null)
if ($LASTEXITCODE -eq 0) {
    $dirtyBuild = $gitStatusOutput.Count -gt 0
}
$buildIdentity = [ordered]@{
    schema_version = 1
    semantic_version = $semanticVersion
    file_version = $fileVersion
    product_version = $fileVersion
    full_git_commit = $fullGitCommit
    short_git_commit = $shortGitCommit
    build_timestamp_utc = [DateTime]::UtcNow.ToString("o")
    packaged = $true
    dirty = $dirtyBuild
    validation_label = $ValidationLabel
}
$buildIdentityJson = $buildIdentity | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($buildIdentityPath, $buildIdentityJson, [System.Text.UTF8Encoding]::new($false))
$oldBuildIdentityPath = $env:MEDIA_MANGLERS_BUILD_IDENTITY_PATH
$env:MEDIA_MANGLERS_BUILD_IDENTITY_PATH = $buildIdentityPath

try {
    if ($Engine -eq "PySideDeploy" -and $AllowToolDownloads) {
        Write-Host "Tool downloads explicitly allowed: Nuitka may download its supported MinGW64 compiler and dependency tools." -ForegroundColor Yellow
        $specText = [System.IO.File]::ReadAllText($specPath)
        $specText = [regex]::Replace(
            $specText,
            '(?m)^extra_args = (.+)$',
            'extra_args = $1 --mingw64 --assume-yes-for-downloads'
        )
        [System.IO.File]::WriteAllText($buildSpecPath, $specText, [System.Text.UTF8Encoding]::new($false))
        $activeSpec = $buildSpecPath
    }

    # Checked again here: the steps above take minutes, and the app may have been opened meanwhile.
    Assert-NothingRunningFrom -Root $targetRoot
    Remove-VerifiedPath -Path $officialOutput -Root $distRoot
    Remove-VerifiedPath -Path $targetRoot -Root $distRoot
    $oldPythonPath = $env:PYTHONPATH
    $env:PYTHONPATH = (Join-Path $repoRoot "src") + $(if ($oldPythonPath) { ";$oldPythonPath" } else { "" })
    Push-Location $repoRoot
    try {
        $buildHostProcess = Get-Process -Id $PID
        $originalPriority = $buildHostProcess.PriorityClass
        try {
            $buildHostProcess.PriorityClass = "BelowNormal"
            if ($Engine -eq "PyInstaller") {
                $pyInstallerArguments = @(
                    "-m", "PyInstaller",
                    "--noconfirm",
                    "--clean",
                    "--distpath", $distRoot,
                    "--workpath", $pyInstallerWorkRoot,
                    $pyInstallerSpecPath
                )
                if ($DryRun) {
                    Write-Host "Dry run: $buildPython $($pyInstallerArguments -join ' ')" -ForegroundColor Cyan
                }
                else {
                    Write-Host "Running the bounded PyInstaller one-folder deployment path..." -ForegroundColor Cyan
                    & $buildPython @pyInstallerArguments
                    if ($LASTEXITCODE -ne 0) {
                        throw "PyInstaller exited with code $LASTEXITCODE."
                    }
                }
            }
            else {
                $deployArguments = @("-c", $activeSpec, "--mode", "standalone", "--name", "VideoManglerWorkbench", "-f")
                if ($DryRun) {
                    $deployArguments += "--dry-run"
                }
                $deployScriptsRoot = Split-Path -Path $deployScript -Parent
                $deployBootstrap = "import runpy, sys; sys.path.insert(0, r'$deployScriptsRoot'); sys.argv=[r'$deployScript'] + sys.argv[1:]; runpy.run_path(r'$deployScript', run_name='__main__')"
                Write-Host "Running the explicitly enabled PySide6/Nuitka deployment path..." -ForegroundColor Cyan
                & $buildPython -c $deployBootstrap @deployArguments
                if ($LASTEXITCODE -ne 0) {
                    throw "pyside6-deploy exited with code $LASTEXITCODE."
                }
            }
        }
        finally {
            $buildHostProcess.PriorityClass = $originalPriority
        }
    }
    finally {
        Pop-Location
        $env:PYTHONPATH = $oldPythonPath
    }

    if ($DryRun) {
        Write-Host "Dry run complete. No executable was produced." -ForegroundColor Green
        return
    }

    if ($Engine -eq "PySideDeploy") {
        if (-not (Test-Path -LiteralPath $officialOutput -PathType Container)) {
            throw "pyside6-deploy did not produce its expected standalone folder: $officialOutput"
        }
        Move-Item -LiteralPath $officialOutput -Destination $targetRoot
        if (-not (Test-Path -LiteralPath $entryExe -PathType Leaf)) {
            throw "The standalone entry executable was not found: $entryExe"
        }
        Move-Item -LiteralPath $entryExe -Destination $targetExe
    }
    elseif (-not (Test-Path -LiteralPath $targetExe -PathType Leaf)) {
        throw "PyInstaller did not produce the required executable: $targetExe"
    }

    if ($Engine -eq "PyInstaller") {
        Repair-AndAssertPackagedQtRuntimeIntegrity -BuildPython $buildPython -PackageRoot $targetRoot
    }

    Copy-Item -LiteralPath (Join-Path $repoRoot "Video Mangler.ps1") -Destination (Join-Path $targetRoot "Video Mangler.ps1") -Force
    Copy-Item -LiteralPath (Join-Path $repoRoot "assets\Video Mangler.ico") -Destination (Join-Path $targetRoot "Video Mangler.ico") -Force
    Copy-Item -LiteralPath (Join-Path $repoRoot "VERSION") -Destination (Join-Path $targetRoot "VERSION") -Force
    Copy-Item -LiteralPath (Join-Path $repoRoot "LICENSE") -Destination (Join-Path $targetRoot "LICENSE.txt") -Force
    Copy-Item -LiteralPath (Join-Path $repoRoot "THIRD_PARTY_NOTICES.txt") -Destination (Join-Path $targetRoot "THIRD_PARTY_NOTICES.txt") -Force
    if ($Engine -eq "PyInstaller") {
        # The checks read the PyInstaller layout (_internal) and its bootloader's licence.
        Copy-AndAssertPackagedLicences -BuildPython $buildPython -PackageRoot $targetRoot
    }
    Copy-Item -LiteralPath $buildIdentityPath -Destination (Join-Path $targetRoot "BUILD_IDENTITY.json") -Force
    Copy-PythonBackendSidecar -DestinationRoot $targetRoot
    Assert-PythonBackendSidecarImports -BuildPython $buildPython -PackageRoot $targetRoot
    Set-PackagedBackendNeutralBytecode -BuildPython $buildPython -PackageRoot $targetRoot
    # Installer plan, Stages 4 and 5: Media Manglers' own Python and FFmpeg, every part pinned by SHA-256 in
    # tools\installer\components.lock.json, in the packaged application folder's runtime folder.
    & (Join-Path $repoRoot "tools\installer\Build-PackagedRuntime.ps1") -PackageRoot $targetRoot -BuildPython $buildPython -CacheRoot (Join-Path $BuildRoot "components")
    $glossariesSource = Join-Path $repoRoot "glossaries"
    if (Test-Path -LiteralPath $glossariesSource -PathType Container) {
        Copy-Item -LiteralPath $glossariesSource -Destination (Join-Path $targetRoot "glossaries") -Recurse -Force
    }
    $workbenchDocsSource = Join-Path $repoRoot "docs\workbench"
    if (Test-Path -LiteralPath $workbenchDocsSource -PathType Container) {
        $workbenchDocsDestination = Join-Path $targetRoot "docs\workbench"
        New-Item -ItemType Directory -Path $workbenchDocsDestination -Force | Out-Null
        Copy-Item -Path (Join-Path $workbenchDocsSource "*") -Destination $workbenchDocsDestination -Recurse -Force
    }

    $mtExe = Find-MtExe
    if ($Engine -eq "PySideDeploy") {
        & $mtExe "-manifest" $manifestPath ("-outputresource:{0};#1" -f $targetExe)
        if ($LASTEXITCODE -ne 0) {
            throw "Embedding the high-DPI application manifest failed."
        }
    }
    $extractedManifest = Join-Path $BuildRoot "embedded-workbench.manifest"
    & $mtExe ("-inputresource:{0};#1" -f $targetExe) ("-out:{0}" -f $extractedManifest)
    if ($LASTEXITCODE -ne 0 -or -not (Select-String -LiteralPath $extractedManifest -SimpleMatch "PerMonitorV2" -Quiet)) {
        throw "The packaged executable does not contain the required PerMonitorV2 manifest."
    }

    if ($SmokeTest) {
        # 159: every build's smoke launch starts from fresh settings, as a first launch on a new PC
        # does; tool paths saved by an earlier build's launch would skip the slow first checks.
        $smokeRoot = Join-Path $BuildRoot "smoke-appdata"
        Remove-VerifiedPath -Path $smokeRoot -Root $BuildRoot
        New-Item -ItemType Directory -Path $smokeRoot -Force | Out-Null
        # 242: every per-user folder the Workbench opens gets a place inside the smoke folder: its
        # settings, its logs, the raw bin library (opened at start-up), the cache and the privacy
        # masks. The launch never opens, upgrades or backs up the operator's own.
        $smokeFolders = [ordered]@{
            MEDIA_MANGLERS_WORKBENCH_APPDATA = Join-Path $smokeRoot "Roaming"
            MEDIA_MANGLERS_WORKBENCH_LOCALAPPDATA = Join-Path $smokeRoot "Local"
            MEDIA_MANGLERS_LIBRARY_ROOT = Join-Path $smokeRoot "Local\MediaManglers\Workbench\library"
            MEDIA_MANGLERS_CACHE_ROOT = Join-Path $smokeRoot "Local\MediaManglers\Workbench\cache"
            MEDIA_MANGLERS_RACE_VIDEO_PRIVACY = Join-Path $smokeRoot "Roaming\MediaManglers\race-video\privacy"
        }
        $oldFolders = @{}
        foreach ($name in $smokeFolders.Keys) {
            $oldFolders[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
            [Environment]::SetEnvironmentVariable($name, $smokeFolders[$name], "Process")
        }
        try {
            # 159: the hang was the close waiting for the start-up readiness check and then
            # refusing; closing now stops the check (193), so a launch ends in seconds however slow
            # the check is. One launch, 30 seconds: a launch that has not ended by then is a real
            # hang. It is recorded (what was running, the app's own log, where each thread was
            # waiting, kept beside the build) and stopped, and the build fails. Any crash fails too.
            $smokeLogs = Join-Path $smokeRoot "Local\MediaManglers\Workbench\logs"
            Write-Host "Smoke-launching the packaged executable..." -ForegroundColor Cyan
            $smoke = [System.Diagnostics.Stopwatch]::StartNew()
            $process = Start-Process -FilePath $targetExe -ArgumentList @("--offscreen", "--smoke-test") -WorkingDirectory $targetRoot -PassThru -WindowStyle Hidden
            if ($process.WaitForExit(30000)) {
                if ($process.ExitCode -ne 0) {
                    $latestLog = Get-ChildItem -LiteralPath $smokeLogs -Filter "*.log" -ErrorAction SilentlyContinue |
                        Sort-Object LastWriteTime | Select-Object -Last 1
                    if ($latestLog) {
                        Write-Host "  The app's log ($($latestLog.Name)):"
                        Get-Content -LiteralPath $latestLog.FullName -Tail 20 | ForEach-Object { Write-Host "    $_" }
                    }
                    throw "Packaged executable smoke launch failed with exit code $($process.ExitCode)."
                }
                Write-Host ("Smoke launch finished in {0:N1} s." -f $smoke.Elapsed.TotalSeconds)
            }
            else {
                Write-Host "Smoke launch did not end within 30 seconds. What was running:" -ForegroundColor Yellow
                $all = @(Get-CimInstance Win32_Process)
                $tree = @($process.Id)
                do {
                    $grown = $false
                    foreach ($item in $all) {
                        if (($tree -contains $item.ParentProcessId) -and -not ($tree -contains $item.ProcessId)) {
                            $tree += $item.ProcessId
                            $grown = $true
                        }
                    }
                } while ($grown)
                foreach ($item in ($all | Where-Object { $tree -contains $_.ProcessId })) {
                    Write-Host ("  {0} {1} {2}" -f $item.ProcessId, $item.Name, $item.CommandLine)
                }
                $latestLog = Get-ChildItem -LiteralPath $smokeLogs -Filter "*.log" -ErrorAction SilentlyContinue |
                    Sort-Object LastWriteTime | Select-Object -Last 1
                if ($latestLog) {
                    Write-Host "  The app's log ($($latestLog.Name)):"
                    Get-Content -LiteralPath $latestLog.FullName -Tail 20 | ForEach-Object { Write-Host "    $_" }
                }
                foreach ($id in ($tree | Sort-Object -Descending)) {
                    Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
                }
                $stacks = Join-Path $smokeLogs "smoke-launch-stacks.txt"
                if ((Test-Path -LiteralPath $stacks) -and (Get-Item -LiteralPath $stacks).Length -gt 0) {
                    $keptStacks = Join-Path $BuildRoot ("smoke-launch-stacks-{0}.txt" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
                    Copy-Item -LiteralPath $stacks -Destination $keptStacks -Force
                    Write-Host "  Where each thread was waiting (written by the app after 15 seconds; kept in $keptStacks):"
                    Get-Content -LiteralPath $stacks -Tail 60 | ForEach-Object { Write-Host "    $_" }
                }
                throw "Packaged executable smoke launch timed out after 30 seconds."
            }
        }
        finally {
            foreach ($name in $oldFolders.Keys) {
                [Environment]::SetEnvironmentVariable($name, $oldFolders[$name], "Process")
            }
        }
    }

    $versionInfo = (Get-Item -LiteralPath $targetExe).VersionInfo
    Write-Host "Video Mangler Workbench standalone build complete." -ForegroundColor Green
    Write-Host "Executable: $targetExe" -ForegroundColor Green
    Write-Host ("File version: {0}; Product version: {1}" -f $versionInfo.FileVersion, $versionInfo.ProductVersion) -ForegroundColor Green
    Write-Host ("Build identity: v{0} | PACKAGED | {1}{2}" -f $semanticVersion, $(if ($shortGitCommit) { $shortGitCommit } else { "UNKNOWN" }), $(if ($dirtyBuild -eq $true) { " | DIRTY" } else { "" })) -ForegroundColor Green
    Write-Host "Backend sidecars: Video Mangler.ps1, python-core, glossaries, runtime (our own Python and FFmpeg)" -ForegroundColor Green
}
finally {
    $env:MEDIA_MANGLERS_BUILD_IDENTITY_PATH = $oldBuildIdentityPath
    if (Test-Path -LiteralPath $buildSpecPath) {
        Remove-Item -LiteralPath $buildSpecPath -Force
    }
}
