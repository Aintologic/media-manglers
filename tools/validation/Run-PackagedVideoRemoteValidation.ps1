param(
    [Parameter(Mandatory = $true)]
    [string]$InputUrl,

    [string]$PackageZipPath,

    [string]$WorkingRoot,

    [ValidateSet("Private", "Public")]
    [string]$OpenAiProject = "Private",

    [string]$ProtectedTermsProfile = "",

    [double]$FrameIntervalSeconds = 10.0,

    [int]$HeartbeatSeconds = 30,

    [int]$PackagedHeartbeatSeconds = 15,

    [int]$FirstOutputDeadlineSeconds = 30,

    [int]$BootstrapDeadlineSeconds = 60,

    [int]$TimeoutSeconds = 1800,

    [switch]$SkipEstimate
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).ProviderPath
$watchdogHelper = Join-Path $repoRoot "tools\validation\PackagedRunWatchdog.ps1"
$videoValidator = Join-Path $repoRoot "tools\validation\Validate-VideoToCodexPackage.ps1"

if (-not (Test-Path -LiteralPath $watchdogHelper)) {
    throw "Packaged run watchdog helper not found: $watchdogHelper"
}

if (-not (Test-Path -LiteralPath $videoValidator)) {
    throw "Video validator not found: $videoValidator"
}

. $watchdogHelper

function Get-LatestVideoReleaseZip {
    param([string]$ReleaseRoot)

    return Get-ChildItem -LiteralPath $ReleaseRoot -Filter "Video-Mangler-v*.zip" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}

if ([string]::IsNullOrWhiteSpace($PackageZipPath)) {
    $releaseRoot = Join-Path $repoRoot "dist\release"
    $latestZip = Get-LatestVideoReleaseZip -ReleaseRoot $releaseRoot
    if (-not $latestZip) {
        throw "No packaged Video Mangler release zip was found under $releaseRoot"
    }
    $PackageZipPath = $latestZip.FullName
}
elseif (-not (Test-Path -LiteralPath $PackageZipPath)) {
    throw "Requested package zip not found: $PackageZipPath"
}
else {
    $PackageZipPath = (Resolve-Path -LiteralPath $PackageZipPath).ProviderPath
}

if ([string]::IsNullOrWhiteSpace($WorkingRoot)) {
    $runId = Get-Date -Format "yyyyMMdd-HHmmss"
    $WorkingRoot = Join-Path $repoRoot ("test-output\packaged-video-remote-{0}" -f $runId)
}

if (-not (Test-Path -LiteralPath $WorkingRoot)) {
    New-Item -ItemType Directory -Path $WorkingRoot -Force | Out-Null
}

$extractRoot = Join-Path $WorkingRoot "extract"
$outputRoot = Join-Path $WorkingRoot "output"

if (Test-Path -LiteralPath $extractRoot) {
    Remove-Item -LiteralPath $extractRoot -Recurse -Force
}

Expand-Archive -LiteralPath $PackageZipPath -DestinationPath $extractRoot -Force

$exePath = Get-ChildItem -LiteralPath $extractRoot -Recurse -Filter "Video Mangler.exe" -File |
    Select-Object -First 1 -ExpandProperty FullName

if (-not $exePath) {
    throw "Video Mangler.exe was not found after extracting $PackageZipPath"
}

$arguments = New-Object System.Collections.Generic.List[string]
[void]$arguments.Add("-InputUrl")
[void]$arguments.Add($InputUrl)
[void]$arguments.Add("-OutputFolder")
[void]$arguments.Add($outputRoot)
[void]$arguments.Add("-ProcessingMode")
[void]$arguments.Add("Hybrid")
[void]$arguments.Add("-OpenAiProject")
[void]$arguments.Add($OpenAiProject)
[void]$arguments.Add("-FrameIntervalSeconds")
[void]$arguments.Add($FrameIntervalSeconds.ToString("0.0", [System.Globalization.CultureInfo]::InvariantCulture))
[void]$arguments.Add("-HeartbeatSeconds")
[void]$arguments.Add($HeartbeatSeconds.ToString())
[void]$arguments.Add("-NoPrompt")

if (-not [string]::IsNullOrWhiteSpace($ProtectedTermsProfile)) {
    [void]$arguments.Add("-ProtectedTermsProfile")
    [void]$arguments.Add($ProtectedTermsProfile)
}

if ($SkipEstimate) {
    [void]$arguments.Add("-SkipEstimate")
}

$watchdogResult = Invoke-PackagedRunWithWatchdog `
    -FilePath $exePath `
    -Arguments $arguments.ToArray() `
    -Label "Packaged Video Mangler.exe" `
    -WorkingDirectory (Split-Path -Path $exePath -Parent) `
    -OutputRoot $outputRoot `
    -LogRoot $WorkingRoot `
    -HeartbeatSeconds $PackagedHeartbeatSeconds `
    -FirstOutputDeadlineSeconds $FirstOutputDeadlineSeconds `
    -BootstrapDeadlineSeconds $BootstrapDeadlineSeconds `
    -TimeoutSeconds $TimeoutSeconds

& $videoValidator -OutputRoot $outputRoot -FrameIntervalSeconds $FrameIntervalSeconds

$summaryPath = Join-Path $outputRoot "PROCESSING_SUMMARY.csv"
$summaryRow = $null
if (Test-Path -LiteralPath $summaryPath) {
    $summaryRow = Import-Csv -LiteralPath $summaryPath | Select-Object -First 1
}

[pscustomobject]@{
    package_zip = $PackageZipPath
    extracted_exe = $exePath
    working_root = $WorkingRoot
    output_root = $outputRoot
    console_log = $watchdogResult.ConsoleLogPath
    stdout_log = $watchdogResult.StdOutPath
    stderr_log = $watchdogResult.StdErrPath
    package_status = if ($summaryRow) { $summaryRow.package_status } else { $null }
    translation_status = if ($summaryRow) { $summaryRow.translation_status } else { $null }
    openai_summary = if ($summaryRow) { $summaryRow.openai_translation_summary } else { $null }
    protected_terms = if ($summaryRow) { $summaryRow.protected_terms_profile } else { $null }
} | ConvertTo-Json -Depth 4
