param(
    [string]$TestMediaFolder = (Join-Path $PSScriptRoot "..\..\test_media"),
    [string]$VideoPath,
    [string]$PreferredShortFixturePath = (Join-Path $PSScriptRoot "..\..\AREA51\TestData\1_min_test_Video.mp4"),
    [string]$RemoteSampleUrl = "https://www.youtube.com/watch?v=hNaUbuWL8MI",
    [double]$FrameIntervalSeconds = 0.5,
    [string]$WhisperModel = "base",
    [int]$HeartbeatSeconds = 10,
    [switch]$CopyRawVideo,
    [switch]$SkipEstimate,
    [switch]$AllMedia,
    [string]$TranslateTo,
    [ValidateSet("Local", "AI", "Hybrid")]
    [string]$ProcessingMode = "Local",
    [ValidateSet("Private", "Public")]
    [string]$OpenAiProject = "Private",
    [string]$ProtectedTermsProfile = "",
    [switch]$IncludeComments,
    [switch]$KeepTestOutput
)

$ErrorActionPreference = "Stop"

function Get-SmokeTestMediaFiles {
    param([string]$FolderPath)

    $extensions = @(".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm")
    return @(Get-ChildItem -LiteralPath $FolderPath -File | Where-Object { $extensions -contains $_.Extension.ToLowerInvariant() } | Sort-Object Name)
}

function Get-RepresentativeSmokeTestMedia {
    param([System.IO.FileInfo[]]$Files)

    foreach ($preferredName in @("ToS-4k-1920.mov", "bbb_sunflower_1080p_60fps_normal.mp4")) {
        $preferred = $Files | Where-Object { $_.Name -eq $preferredName } | Select-Object -First 1
        if ($preferred) {
            return $preferred
        }
    }

    return $Files | Sort-Object Length | Select-Object -First 1
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).ProviderPath
$videoScript = Join-Path $repoRoot "Video Mangler.ps1"
$validator = Join-Path $repoRoot "tools\validation\Validate-VideoToCodexPackage.ps1"
$runId = "{0}-{1}" -f (Get-Date -Format "yyyyMMdd-HHmmss"), ([guid]::NewGuid().ToString("N").Substring(0, 8))
$outputRoot = Join-Path $repoRoot ("test-output\smoke-{0}" -f $runId)
$usingRemoteSample = $false

if (-not (Test-Path -LiteralPath $videoScript)) {
    throw "Main script not found: $videoScript"
}

if (-not (Test-Path -LiteralPath $validator)) {
    throw "Validator script not found: $validator"
}

$mediaFiles = @()
if (Test-Path -LiteralPath $TestMediaFolder) {
    $mediaFiles = Get-SmokeTestMediaFiles -FolderPath $TestMediaFolder
}

$selectedFiles = @()
$inputTarget = $null

if ($VideoPath) {
    if (-not (Test-Path -LiteralPath $VideoPath)) {
        throw "Requested video path not found: $VideoPath"
    }
    $selectedFiles = @((Get-Item -LiteralPath $VideoPath))
    $inputTarget = $selectedFiles[0].FullName
}
elseif ($AllMedia) {
    if (-not (Test-Path -LiteralPath $TestMediaFolder)) {
        throw "Test media folder not found: $TestMediaFolder"
    }
    if ($mediaFiles.Count -eq 0) {
        throw "No supported media files found in $TestMediaFolder"
    }
    $selectedFiles = $mediaFiles
    $inputTarget = (Resolve-Path -LiteralPath $TestMediaFolder).ProviderPath
}
elseif (-not [string]::IsNullOrWhiteSpace($PreferredShortFixturePath) -and (Test-Path -LiteralPath $PreferredShortFixturePath)) {
    $selectedFiles = @((Get-Item -LiteralPath $PreferredShortFixturePath))
    $inputTarget = $selectedFiles[0].FullName
}
elseif ($mediaFiles.Count -gt 0) {
    $representative = Get-RepresentativeSmokeTestMedia -Files $mediaFiles
    $selectedFiles = @($representative)
    $inputTarget = $representative.FullName
}
else {
    $usingRemoteSample = $true
    $inputTarget = $RemoteSampleUrl
}

New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null

Write-Host ("Smoke test output root: {0}" -f $outputRoot) -ForegroundColor Cyan
if (Test-Path -LiteralPath $TestMediaFolder) {
    Write-Host ("Test media folder:      {0}" -f (Resolve-Path -LiteralPath $TestMediaFolder).ProviderPath) -ForegroundColor Cyan
}
else {
    Write-Host ("Test media folder:      {0}" -f $TestMediaFolder) -ForegroundColor DarkGray
}
if ($usingRemoteSample) {
    Write-Host ("Remote sample URL:      {0}" -f $RemoteSampleUrl) -ForegroundColor Cyan
}
elseif ($AllMedia) {
    Write-Host ("Mode:                   all media ({0} files)" -f $selectedFiles.Count) -ForegroundColor Cyan
}
else {
    Write-Host ("Video under test:       {0}" -f $selectedFiles[0].FullName) -ForegroundColor Cyan
}
Write-Host ("Processing mode:        {0}" -f $ProcessingMode) -ForegroundColor Cyan
if ($ProcessingMode -eq "AI" -or $ProcessingMode -eq "Hybrid") {
    Write-Host ("AI project mode:        {0}" -f $OpenAiProject) -ForegroundColor Cyan
}
if ($ProcessingMode -eq "Hybrid" -and -not [string]::IsNullOrWhiteSpace($ProtectedTermsProfile)) {
    Write-Host ("Protected terms profile:{0}" -f " $ProtectedTermsProfile") -ForegroundColor Cyan
}
Write-Host ("Translation targets:    {0}" -f $(if ([string]::IsNullOrWhiteSpace($TranslateTo)) { "none" } else { $TranslateTo })) -ForegroundColor Cyan

$args = New-Object System.Collections.Generic.List[string]
[void]$args.Add("-NoProfile")
[void]$args.Add("-ExecutionPolicy")
[void]$args.Add("Bypass")
[void]$args.Add("-File")
[void]$args.Add($videoScript)
if ($usingRemoteSample) {
    [void]$args.Add("-InputUrl")
}
else {
    [void]$args.Add("-InputPath")
}
[void]$args.Add($inputTarget)
[void]$args.Add("-OutputFolder")
[void]$args.Add($outputRoot)
[void]$args.Add("-FrameIntervalSeconds")
[void]$args.Add($FrameIntervalSeconds.ToString("0.0", [System.Globalization.CultureInfo]::InvariantCulture))
[void]$args.Add("-WhisperModel")
[void]$args.Add($WhisperModel)
[void]$args.Add("-HeartbeatSeconds")
[void]$args.Add($HeartbeatSeconds.ToString())
[void]$args.Add("-NoPrompt")
[void]$args.Add("-ProcessingMode")
[void]$args.Add($ProcessingMode)

if ($ProcessingMode -eq "AI" -or $ProcessingMode -eq "Hybrid") {
    [void]$args.Add("-OpenAiProject")
    [void]$args.Add($OpenAiProject)
}

if ($ProcessingMode -eq "Hybrid" -and -not [string]::IsNullOrWhiteSpace($ProtectedTermsProfile)) {
    [void]$args.Add("-ProtectedTermsProfile")
    [void]$args.Add($ProtectedTermsProfile)
}

if (-not [string]::IsNullOrWhiteSpace($TranslateTo)) {
    [void]$args.Add("-TranslateTo")
    [void]$args.Add($TranslateTo)
}

if ($CopyRawVideo) {
    [void]$args.Add("-CopyRawVideo")
}

if ($SkipEstimate) {
    [void]$args.Add("-SkipEstimate")
}

if ($IncludeComments) {
    [void]$args.Add("-IncludeComments")
}

& powershell @($args)
if ($LASTEXITCODE -ne 0) {
    throw "Smoke test packaging run failed with exit code $LASTEXITCODE"
}

if ($usingRemoteSample) {
    & $validator -OutputRoot $outputRoot -FrameIntervalSeconds $FrameIntervalSeconds
}
else {
    foreach ($file in $selectedFiles) {
        & $validator -OutputRoot $outputRoot -VideoPath $file.FullName -FrameIntervalSeconds $FrameIntervalSeconds
    }
}

Write-Host ("PASS smoke test completed. Output root: {0}" -f $outputRoot) -ForegroundColor Green

if (-not $KeepTestOutput -and (Test-Path -LiteralPath $outputRoot)) {
    Remove-Item -LiteralPath $outputRoot -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Video smoke output was cleaned up automatically. Use -KeepTestOutput to retain it." -ForegroundColor DarkGray
}
