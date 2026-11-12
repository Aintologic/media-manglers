<#
.SYNOPSIS
    Put Media Manglers' own tools into the packaged application folder's runtime folder (installer plan, Stages 4
    and 5). Build-VideoManglerWorkbench.ps1 runs it after the app and python-core are in place.

.DESCRIPTION
    Every part comes from components.lock.json, pinned by SHA-256. Each is fetched once into the build's own cache
    (a .partial file, checked, then renamed; any mismatch stops the build) and then:

    runtime\python   Python 3.12.10 embeddable; Microsoft's C++ runtime DLLs beside python.exe; a static
                     python312._pth (python312.zip, ., Lib\site-packages, ..\..\python-core\src, import site);
                     Lib\site-packages with the Whisper code (a wheel built here from the pinned source, no pip)
                     and truststore; speech-lock.json, the speech libraries the first-launch setup downloads.
                     Everything is compiled to bytecode here, so our Python never writes beside itself.
    runtime\ffmpeg   bin\ from the pinned FFmpeg-Builds win64 gpl-shared 8.1 build, without ffplay; its licence;
                     a note saying where the Corresponding Source is. The encoders, decoders, filters and formats
                     the app needs are checked, and the build stops if one is missing.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$PackageRoot,
    [Parameter(Mandatory)] [string]$BuildPython,
    [Parameter(Mandatory)] [string]$CacheRoot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProgressPreference = "SilentlyContinue"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).ProviderPath
$PackageRoot = [System.IO.Path]::GetFullPath($PackageRoot)
$CacheRoot = [System.IO.Path]::GetFullPath($CacheRoot)
$BuildPython = [System.IO.Path]::GetFullPath($BuildPython)
$lock = Get-Content -LiteralPath (Join-Path $PSScriptRoot "components.lock.json") -Raw | ConvertFrom-Json
$parts = $lock.components
$helper = Join-Path $PSScriptRoot "packaged_runtime.py"
$runtime = Join-Path $PackageRoot "runtime"
$pythonRoot = Join-Path $runtime "python"
$sitePackages = Join-Path $pythonRoot "Lib\site-packages"
$ffmpegRoot = Join-Path $runtime "ffmpeg"

function Assert-Within {
    param([Parameter(Mandatory)] [string]$Path, [Parameter(Mandatory)] [string]$Root)
    $full = [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
    $prefix = [System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    if (-not $full.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing a file step outside $Root`: $full"
    }
}

function Get-Sha256 {
    param([Parameter(Mandatory)] [string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-PinnedComponent {
    # The component's file in the cache: downloaded once, over Windows' own checked connection, into a .partial
    # file, checked against its pinned size and SHA-256, and only then given its name.
    param([Parameter(Mandatory)] $Part, [Parameter(Mandatory)] [string]$Key)
    $folder = Join-Path $CacheRoot $Key
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
    $final = Join-Path $folder $Part.file
    if ((Test-Path -LiteralPath $final -PathType Leaf) -and (Get-Sha256 $final) -eq $Part.sha256) {
        return $final
    }
    $partial = "$final.partial"
    foreach ($leftover in @($partial, $final)) {
        if (Test-Path -LiteralPath $leftover) { Remove-Item -LiteralPath $leftover -Force }
    }
    Write-Host "Downloading the pinned $($Part.name) ($($Part.file))" -ForegroundColor Cyan
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri $Part.url -OutFile $partial -Headers @{ "User-Agent" = "MediaManglers-build" }
    $size = (Get-Item -LiteralPath $partial).Length
    $found = Get-Sha256 $partial
    if ($size -ne [int64]$Part.size -or $found -ne $Part.sha256) {
        Remove-Item -LiteralPath $partial -Force
        throw "$($Part.file) did not match its pin (size $size, SHA-256 $found). Nothing was used."
    }
    Move-Item -LiteralPath $partial -Destination $final
    return $final
}

function Get-PinnedRuntimeDll {
    # A Microsoft C++ runtime file: from the cache, or else from this PC's System32, accepted only when its SHA-256
    # matches the pin and its signature is valid and Microsoft's.
    param([Parameter(Mandatory)] [string]$Name, [Parameter(Mandatory)] [string]$Sha256)
    $folder = Join-Path $CacheRoot "vc-runtime"
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
    $final = Join-Path $folder $Name
    if ((Test-Path -LiteralPath $final -PathType Leaf) -and (Get-Sha256 $final) -eq $Sha256) {
        return $final
    }
    $source = Join-Path $env:WINDIR "System32\$Name"
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "The pinned C++ runtime file $Name is not in the build cache and not on this PC."
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $source
    if ($signature.Status -ne "Valid" -or $signature.SignerCertificate.Subject -notlike "*O=Microsoft Corporation*") {
        throw "$Name on this PC is not validly signed by Microsoft, so it was not used."
    }
    $found = Get-Sha256 $source
    if ($found -ne $Sha256) {
        throw "$Name on this PC is a different version from the pinned one (SHA-256 $found). Update the pin in components.lock.json on purpose, or put the pinned file in $folder."
    }
    Copy-Item -LiteralPath $source -Destination "$final.partial" -Force
    if ((Get-Sha256 "$final.partial") -ne $Sha256) { throw "The copy of $Name did not match its pin." }
    Move-Item -LiteralPath "$final.partial" -Destination $final -Force
    return $final
}

function Invoke-Helper {
    param([Parameter(ValueFromRemainingArguments)] [string[]]$Arguments)
    & $BuildPython -I $helper @Arguments
    if ($LASTEXITCODE -ne 0) { throw "packaged_runtime.py $($Arguments[0]) failed (exit $LASTEXITCODE)." }
}

New-Item -ItemType Directory -Path $CacheRoot -Force | Out-Null
# The bytecode compiled here is read by our own Python, so the build's Python must be the very same version.
$buildVersion = (& $BuildPython -I -c "import sys; print(sys.version.split()[0])" | Select-Object -Last 1)
if ("$buildVersion".Trim() -ne $parts.python.version) {
    throw "The build's Python is $buildVersion, not $($parts.python.version); our own Python would not read its bytecode. Build with -UsePython312BuildRuntime."
}
Assert-Within -Path $runtime -Root $PackageRoot
if (Test-Path -LiteralPath $runtime) { Remove-Item -LiteralPath $runtime -Recurse -Force }

$pythonZip = Get-PinnedComponent $parts.python "python"
$ffmpegZip = Get-PinnedComponent $parts.ffmpeg "ffmpeg"
$whisperSource = Get-PinnedComponent $parts.openai_whisper "openai-whisper"
$setuptoolsWheel = Get-PinnedComponent $parts.setuptools "setuptools"
$truststoreWheel = Get-PinnedComponent $parts.truststore "truststore"

# runtime\python ------------------------------------------------------------------------------------------------
Write-Host "Assembling Media Manglers' own Python (runtime\python)..." -ForegroundColor Cyan
New-Item -ItemType Directory -Path $pythonRoot -Force | Out-Null
Expand-Archive -LiteralPath $pythonZip -DestinationPath $pythonRoot
# Unused standard-library modules left out (the lock says which and why).
$leaveOut = @($parts.python.stdlib_left_out | ForEach-Object { @('--member', $_) })
if ($leaveOut.Count) { Invoke-Helper stdlib-leave-out --zip (Join-Path $pythonRoot "python312.zip") @leaveOut }
foreach ($dll in $parts.vc_runtime.files.PSObject.Properties) {
    Copy-Item -LiteralPath (Get-PinnedRuntimeDll -Name $dll.Name -Sha256 $dll.Value) -Destination (Join-Path $pythonRoot $dll.Name) -Force
}
# Static: the add-ons are put on the path at run time by use_addons(), and only for this Python.
[System.IO.File]::WriteAllText((Join-Path $pythonRoot "python312._pth"),
    "python312.zip`r`n.`r`nLib\site-packages`r`n..\..\python-core\src`r`nimport site`r`n", [System.Text.Encoding]::ASCII)
New-Item -ItemType Directory -Path $sitePackages -Force | Out-Null
$wheelWork = Join-Path $CacheRoot "whisper-build"
$whisperWheel = (& $BuildPython -I $helper whisper-wheel --sdist $whisperSource --setuptools $setuptoolsWheel --work $wheelWork | Select-Object -Last 1)
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $whisperWheel -PathType Leaf)) { throw "The Whisper wheel was not built." }
Invoke-Helper unpack --wheel $whisperWheel --into $sitePackages
Invoke-Helper unpack --wheel $truststoreWheel --into $sitePackages
# The start-up hook: every process our Python starts gets the downloaded speech libraries (use_addons), and only it.
Invoke-Helper addons-hook --into $sitePackages
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "speech-lock.json") -Destination (Join-Path $pythonRoot "speech-lock.json") -Force
# Compiled once, here, with the build's Python 3.12.10, and with paths that name no build folder.
& $BuildPython -I -m compileall -q -j 0 --invalidation-mode unchecked-hash -s $PackageRoot $sitePackages
if ($LASTEXITCODE -ne 0) { throw "Could not compile our own Python's site-packages." }

# runtime\ffmpeg ------------------------------------------------------------------------------------------------
Write-Host "Assembling Media Manglers' own FFmpeg (runtime\ffmpeg)..." -ForegroundColor Cyan
# Unpacked once per pinned file (by its checksum, so a different pin never reuses another file's programs).
$unzipped = Join-Path $CacheRoot ("ffmpeg-unzip\" + $parts.ffmpeg.sha256.Substring(0, 16))
if (-not (Test-Path -LiteralPath $unzipped)) {
    if (Test-Path -LiteralPath "$unzipped.partial") { Remove-Item -LiteralPath "$unzipped.partial" -Recurse -Force }
    Expand-Archive -LiteralPath $ffmpegZip -DestinationPath "$unzipped.partial"
    Move-Item -LiteralPath "$unzipped.partial" -Destination $unzipped
}
$upstream = @(Get-ChildItem -LiteralPath $unzipped -Directory | Select-Object -First 1)[0]
$bin = Join-Path $ffmpegRoot "bin"
New-Item -ItemType Directory -Path $bin -Force | Out-Null
$pinned = @($parts.ffmpeg.bin_sha256.PSObject.Properties | ForEach-Object Name)
foreach ($file in @(Get-ChildItem -LiteralPath (Join-Path $upstream.FullName "bin") -File)) {
    if ($parts.ffmpeg.left_out -contains $file.Name) { continue }
    if ($pinned -notcontains $file.Name) { throw "FFmpeg's bin holds $($file.Name), which components.lock.json does not pin." }
    Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $bin $file.Name)
}
foreach ($pin in $parts.ffmpeg.bin_sha256.PSObject.Properties) {
    $found = Get-Sha256 (Join-Path $bin $pin.Name)
    if ($found -ne $pin.Value) { throw "$($pin.Name) does not match its pin ($found)." }
}
if (Test-Path -LiteralPath (Join-Path $bin "ffplay.exe")) { throw "ffplay.exe is not shipped." }
Copy-Item -LiteralPath (Join-Path $upstream.FullName "LICENSE.txt") -Destination (Join-Path $ffmpegRoot "LICENSE.txt")
$ffmpegNote = @"
FFmpeg $($parts.ffmpeg.version), bundled with Media Manglers

These programs and libraries (bin\) are FFmpeg as built by the FFmpeg-Builds project: the win64 gpl-shared build
of the 8.1 branch, release $($parts.ffmpeg.release), file $($parts.ffmpeg.file),
SHA-256 $($parts.ffmpeg.sha256). ffplay is left out; nothing else was changed.

The build as a whole is licensed under the GNU General Public License, version 3 or later: see LICENSE.txt here
and licenses\GPL-3.0.txt in the Media Manglers folder.

The complete Corresponding Source for these files (FFmpeg and every library built into them, at the exact
versions used, with the FFmpeg-Builds scripts that built them) and an unchanged copy of the file above are offered
next to each Media Manglers release that includes them, for as long as that release is offered.
"@
[System.IO.File]::WriteAllText((Join-Path $ffmpegRoot "README.txt"), $ffmpegNote.Replace("`r`n", "`n").Replace("`n", "`r`n"), [System.Text.UTF8Encoding]::new($false))
$checkReport = Join-Path $CacheRoot "ffmpeg-check.json"
Invoke-Helper ffmpeg-check --ffmpeg (Join-Path $bin "ffmpeg.exe") --needs (Join-Path $PSScriptRoot "ffmpeg-needs.json") --report $checkReport

# Licences and the check of our own Python ------------------------------------------------------------------------
$licences = Join-Path $PackageRoot "licenses"
New-Item -ItemType Directory -Path $licences -Force | Out-Null
$texts = [ordered]@{
    "truststore-MIT.txt"     = @(Get-ChildItem -LiteralPath $sitePackages -Recurse -File -Filter "LICENSE*" | Where-Object { $_.FullName -match '\\truststore-[^\\]+\.dist-info\\' })
    "openai-whisper-MIT.txt" = @(Get-ChildItem -LiteralPath $sitePackages -Recurse -File -Filter "LICENSE*" | Where-Object { $_.FullName -match '\\openai_whisper-[^\\]+\.dist-info\\' })
}
foreach ($entry in $texts.GetEnumerator()) {
    if ($entry.Value.Count -lt 1) { throw "The licence text for $($entry.Key) was not found in its wheel." }
    Copy-Item -LiteralPath $entry.Value[0].FullName -Destination (Join-Path $licences $entry.Key) -Force
}
Copy-Item -LiteralPath (Join-Path $ffmpegRoot "LICENSE.txt") -Destination (Join-Path $licences "FFmpeg-LICENSE.txt") -Force

$probe = @'
import json, sys
from media_manglers.core import private_runtime, speech_setup, whisper_models
import truststore
lock = speech_setup.read_lock(private_runtime.app_folder())
table = whisper_models.model_table()
print(json.dumps({"private_python": private_runtime.is_private_python(), "set_id": lock.set_id if lock else "",
                  "whisper_models": "base.en" in table, "truststore": truststore.__version__,
                  "version": sys.version.split()[0]}))
'@
# Written to a file: Windows PowerShell drops the double quotes of an argument it passes to a program.
$probeFile = Join-Path $CacheRoot "runtime-probe.py"
[System.IO.File]::WriteAllText($probeFile, $probe, [System.Text.UTF8Encoding]::new($false))
$answer = & (Join-Path $pythonRoot "python.exe") -B $probeFile
if ($LASTEXITCODE -ne 0) { throw "Our own Python did not start with its packages." }
$state = $answer | Select-Object -Last 1 | ConvertFrom-Json
if (-not $state.private_python -or -not $state.set_id -or -not $state.whisper_models -or $state.version -ne $parts.python.version) {
    throw "Our own Python is not complete: $answer"
}
# The privacy check's package scan (the generic rules) over everything this step put in place: an upstream file that
# trips a rule is caught here, at build time, not at publishing.
& $BuildPython -I (Join-Path $repoRoot "tools\privacy\privacy_check.py") paths $runtime
if ($LASTEXITCODE -ne 0) { throw "The privacy check found something in runtime\ (see above)." }
foreach ($blocker in @($parts.ffmpeg.publish_blockers)) {
    if ($blocker) { Write-Warning "NOT FOR RELEASE: $blocker" }
}
$sizes = [ordered]@{
    python = (Get-ChildItem -LiteralPath $pythonRoot -Recurse -File | Measure-Object Length -Sum).Sum
    ffmpeg = (Get-ChildItem -LiteralPath $ffmpegRoot -Recurse -File | Measure-Object Length -Sum).Sum
}
Write-Host ("Media Manglers' own tools are in place: Python {0} ({1:N0} bytes, speech set {2}, truststore {3}); FFmpeg {4} ({5:N0} bytes)." -f $state.version, $sizes.python, $state.set_id, $state.truststore, $parts.ffmpeg.version, $sizes.ffmpeg) -ForegroundColor Green
