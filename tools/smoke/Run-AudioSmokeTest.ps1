param(
    [string]$TestAudioFolder = (Join-Path $PSScriptRoot "..\..\test_audio"),
    [string]$AudioPath,
    [string]$PreferredShortAudioPath = (Join-Path $PSScriptRoot "..\..\AREA51\TestData\1_min_test_Video.mp4"),
    [string]$PreferredShortForeignAudioPath = (Join-Path $PSScriptRoot "..\..\AREA51\TestData\German_audio_short_45s.mp3"),
    [string]$RemoteSampleUrl = "https://www.youtube.com/watch?v=1aA1WGON49E",
    [string]$RemoteSampleFallbackUrl = "https://www.youtube.com/watch?v=XRka52Y3kyA",
    [string]$TranslationSampleUrl = "https://www.youtube.com/watch?v=hNaUbuWL8MI",
    [string]$WhisperModel = "base",
    [int]$HeartbeatSeconds = 10,
    [switch]$CopyRawAudio,
    [switch]$SkipEstimate,
    [switch]$AllAudio,
    [switch]$TranslateToEnglish,
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

function Get-SmokeTestAudioFiles {
    param([string]$FolderPath)

    $extensions = @(".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".webm", ".mka", ".mp4")
    return @(Get-ChildItem -LiteralPath $FolderPath -File | Where-Object { $extensions -contains $_.Extension.ToLowerInvariant() } | Sort-Object Name)
}

function Get-RepresentativeSmokeTestAudio {
    param([System.IO.FileInfo[]]$Files)

    foreach ($preferredName in @("gettysburg_address.mp3", "msw028_10_maravigliosamente_jacopodalentini_le_128kb.mp3")) {
        $preferred = $Files | Where-Object { $_.Name -eq $preferredName } | Select-Object -First 1
        if ($preferred) {
            return $preferred
        }
    }

    return $Files | Sort-Object Length | Select-Object -First 1
}

function Invoke-AudioPackaging {
    param(
        [string]$ScriptPath,
        [string]$InputTarget,
        [string]$OutputRoot,
        [string]$WhisperModel,
        [int]$HeartbeatSeconds,
        [switch]$CopyRawAudio,
        [switch]$SkipEstimate,
        [string]$TranslateTo,
        [string]$ProcessingMode,
        [string]$OpenAiProject,
        [string]$ProtectedTermsProfile,
        [switch]$TranslateToEnglish,
        [switch]$IncludeComments
    )

    $args = New-Object System.Collections.Generic.List[string]
    [void]$args.Add("-NoProfile")
    [void]$args.Add("-ExecutionPolicy")
    [void]$args.Add("Bypass")
    [void]$args.Add("-File")
    [void]$args.Add($ScriptPath)
    [void]$args.Add("-InputPath")
    [void]$args.Add($InputTarget)
    [void]$args.Add("-OutputFolder")
    [void]$args.Add($OutputRoot)
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

    if ($CopyRawAudio) {
        [void]$args.Add("-CopyRawAudio")
    }

    if ($SkipEstimate) {
        [void]$args.Add("-SkipEstimate")
    }

    $resolvedTranslateTo = $TranslateTo
    if ($TranslateToEnglish -and [string]::IsNullOrWhiteSpace($resolvedTranslateTo)) {
        $resolvedTranslateTo = "en"
    }

    if (-not [string]::IsNullOrWhiteSpace($resolvedTranslateTo)) {
        [void]$args.Add("-TranslateTo")
        [void]$args.Add($resolvedTranslateTo)
    }

    if ($IncludeComments) {
        [void]$args.Add("-IncludeComments")
    }

    & powershell @($args) | Out-Host
    $commandExitCode = $LASTEXITCODE
    return [int]$commandExitCode
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).ProviderPath
$audioScript = Join-Path $repoRoot "Audio Mangler.ps1"
$validator = Join-Path $repoRoot "tools\validation\Validate-AudioManglerPackage.ps1"
$runId = "{0}-{1}" -f (Get-Date -Format "yyyyMMdd-HHmmss"), ([guid]::NewGuid().ToString("N").Substring(0, 8))
$outputRoot = Join-Path $repoRoot ("test-output\audio-smoke-{0}" -f $runId)
$usingRemoteSample = $false

if (-not (Test-Path -LiteralPath $audioScript)) {
    throw "Main script not found: $audioScript"
}

if (-not (Test-Path -LiteralPath $validator)) {
    throw "Validator script not found: $validator"
}

$audioFiles = @()
if (Test-Path -LiteralPath $TestAudioFolder) {
    $audioFiles = Get-SmokeTestAudioFiles -FolderPath $TestAudioFolder
}

$selectedFiles = @()
$inputTarget = $null

if ($AudioPath) {
    if (-not (Test-Path -LiteralPath $AudioPath)) {
        throw "Requested audio path not found: $AudioPath"
    }
    $selectedFiles = @((Get-Item -LiteralPath $AudioPath))
    $inputTarget = $selectedFiles[0].FullName
}
elseif ($AllAudio) {
    if (-not (Test-Path -LiteralPath $TestAudioFolder)) {
        throw "Test audio folder not found: $TestAudioFolder"
    }
    if ($audioFiles.Count -eq 0) {
        throw "No supported audio files found in $TestAudioFolder"
    }
    $selectedFiles = $audioFiles
    $inputTarget = (Resolve-Path -LiteralPath $TestAudioFolder).ProviderPath
}
elseif ($TranslateToEnglish -and -not [string]::IsNullOrWhiteSpace($PreferredShortForeignAudioPath) -and (Test-Path -LiteralPath $PreferredShortForeignAudioPath)) {
    $selectedFiles = @((Get-Item -LiteralPath $PreferredShortForeignAudioPath))
    $inputTarget = $selectedFiles[0].FullName
}
elseif (-not [string]::IsNullOrWhiteSpace($PreferredShortAudioPath) -and (Test-Path -LiteralPath $PreferredShortAudioPath)) {
    $selectedFiles = @((Get-Item -LiteralPath $PreferredShortAudioPath))
    $inputTarget = $selectedFiles[0].FullName
}
elseif ($audioFiles.Count -gt 0 -and -not $TranslateToEnglish) {
    $representative = Get-RepresentativeSmokeTestAudio -Files $audioFiles
    $selectedFiles = @($representative)
    $inputTarget = $representative.FullName
}
else {
    $usingRemoteSample = $true
    $inputTarget = if ($TranslateToEnglish) { $TranslationSampleUrl } else { $RemoteSampleUrl }
}

New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null

Write-Host ("Audio smoke test output root: {0}" -f $outputRoot) -ForegroundColor Cyan
if (Test-Path -LiteralPath $TestAudioFolder) {
    Write-Host ("Test audio folder:            {0}" -f (Resolve-Path -LiteralPath $TestAudioFolder).ProviderPath) -ForegroundColor Cyan
}
else {
    Write-Host ("Test audio folder:            {0}" -f $TestAudioFolder) -ForegroundColor DarkGray
}
if ($usingRemoteSample) {
    Write-Host ("Remote sample URL:            {0}" -f $inputTarget) -ForegroundColor Cyan
    if (-not $TranslateToEnglish -and -not [string]::IsNullOrWhiteSpace($RemoteSampleFallbackUrl)) {
        Write-Host ("Remote fallback URL:          {0}" -f $RemoteSampleFallbackUrl) -ForegroundColor DarkGray
    }
}
elseif ($AllAudio) {
    Write-Host ("Mode:                         all audio ({0} files)" -f $selectedFiles.Count) -ForegroundColor Cyan
}
else {
    Write-Host ("Audio under test:             {0}" -f $selectedFiles[0].FullName) -ForegroundColor Cyan
}
if ($TranslateToEnglish) {
    Write-Host "Translation mode:             -> en" -ForegroundColor Cyan
}
elseif (-not [string]::IsNullOrWhiteSpace($TranslateTo)) {
    Write-Host ("Translation mode:             -> {0}" -f $TranslateTo) -ForegroundColor Cyan
}
Write-Host ("Processing mode:             {0}" -f $ProcessingMode) -ForegroundColor Cyan
if ($ProcessingMode -eq "AI") {
    Write-Host ("AI project mode:             {0}" -f $OpenAiProject) -ForegroundColor Cyan
}
elseif ($ProcessingMode -eq "Hybrid") {
    Write-Host ("AI project mode:             {0}" -f $OpenAiProject) -ForegroundColor Cyan
    if (-not [string]::IsNullOrWhiteSpace($ProtectedTermsProfile)) {
        Write-Host ("Protected terms profile:     {0}" -f $ProtectedTermsProfile) -ForegroundColor Cyan
    }
}

$exitCode = Invoke-AudioPackaging `
    -ScriptPath $audioScript `
    -InputTarget $inputTarget `
    -OutputRoot $outputRoot `
    -WhisperModel $WhisperModel `
    -HeartbeatSeconds $HeartbeatSeconds `
    -CopyRawAudio:$CopyRawAudio `
    -SkipEstimate:$SkipEstimate `
    -TranslateTo $TranslateTo `
    -ProcessingMode $ProcessingMode `
    -OpenAiProject $OpenAiProject `
    -ProtectedTermsProfile $ProtectedTermsProfile `
    -TranslateToEnglish:$TranslateToEnglish `
    -IncludeComments:$IncludeComments

if ($exitCode -ne 0 -and $usingRemoteSample -and -not $TranslateToEnglish -and -not [string]::IsNullOrWhiteSpace($RemoteSampleFallbackUrl) -and ($inputTarget -ne $RemoteSampleFallbackUrl)) {
    Write-Host ("Primary remote audio smoke sample failed. Retrying with fallback page: {0}" -f $RemoteSampleFallbackUrl) -ForegroundColor Yellow
    $inputTarget = $RemoteSampleFallbackUrl
    $exitCode = Invoke-AudioPackaging `
        -ScriptPath $audioScript `
        -InputTarget $inputTarget `
        -OutputRoot $outputRoot `
        -WhisperModel $WhisperModel `
        -HeartbeatSeconds $HeartbeatSeconds `
        -CopyRawAudio:$CopyRawAudio `
        -SkipEstimate:$SkipEstimate `
        -TranslateTo $TranslateTo `
        -ProcessingMode $ProcessingMode `
        -OpenAiProject $OpenAiProject `
        -ProtectedTermsProfile $ProtectedTermsProfile `
        -TranslateToEnglish:$TranslateToEnglish `
        -IncludeComments:$IncludeComments
}

if ($exitCode -ne 0) {
    throw "Audio smoke test packaging run failed with exit code $exitCode"
}

if ($usingRemoteSample) {
    & $validator -OutputRoot $outputRoot
}
else {
    foreach ($file in $selectedFiles) {
        & $validator -OutputRoot $outputRoot -AudioPath $file.FullName
    }
}

Write-Host ("PASS audio smoke test completed. Output root: {0}" -f $outputRoot) -ForegroundColor Green

if (-not $KeepTestOutput -and (Test-Path -LiteralPath $outputRoot)) {
    Remove-Item -LiteralPath $outputRoot -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Audio smoke output was cleaned up automatically. Use -KeepTestOutput to retain it." -ForegroundColor DarkGray
}
