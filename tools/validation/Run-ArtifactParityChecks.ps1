param(
    [ValidateSet("Source", "Release", "All")]
    [string]$Surface = "All",
    [string]$VideoPath = (Join-Path $PSScriptRoot "..\..\AREA51\TestData\1_min_test_Video.mp4"),
    [string]$AudioPath = (Join-Path $PSScriptRoot "..\..\AREA51\TestData\1_min_test_Video.mp4"),
    [double]$FrameIntervalSeconds = 0.5,
    [string]$WhisperModel = "base",
    [int]$PackagedHeartbeatSeconds = 15,
    [int]$FirstOutputDeadlineSeconds = 30,
    [int]$BootstrapDeadlineSeconds = 60,
    [int]$PackagedTimeoutSeconds = 1800,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).ProviderPath
$fixturePath = Join-Path $repoRoot "tests\fixtures\parity\local_artifact_hashes.json"
$versionPath = Join-Path $repoRoot "VERSION"
$videoValidator = Join-Path $repoRoot "tools\validation\Validate-VideoToCodexPackage.ps1"
$audioValidator = Join-Path $repoRoot "tools\validation\Validate-AudioManglerPackage.ps1"
$buildScript = Join-Path $repoRoot "tools\release\Build-Exe.ps1"
$watchdogHelper = Join-Path $repoRoot "tools\validation\PackagedRunWatchdog.ps1"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$runRoot = Join-Path $repoRoot ("test-output\artifact-parity-{0}" -f $timestamp)

if (-not (Test-Path -LiteralPath $watchdogHelper)) {
    throw "Packaged run watchdog helper not found: $watchdogHelper"
}

. $watchdogHelper

function Ensure-Directory {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Remove-PathIfPresent {
    param([string]$Path)

    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

function Invoke-NativeAndRequireSuccess {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$Label
    )

    Write-Host ("Running: {0}" -f $Label) -ForegroundColor Cyan
    & $FilePath @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw ("{0} failed with exit code {1}" -f $Label, $LASTEXITCODE)
    }
}

function Invoke-ExeAndRequireSuccess {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$Label,
        [string]$OutputRoot
    )

    Invoke-PackagedRunWithWatchdog `
        -FilePath $FilePath `
        -Arguments $Arguments `
        -Label $Label `
        -WorkingDirectory (Split-Path -Path $FilePath -Parent) `
        -OutputRoot $OutputRoot `
        -LogRoot $OutputRoot `
        -HeartbeatSeconds $PackagedHeartbeatSeconds `
        -FirstOutputDeadlineSeconds $FirstOutputDeadlineSeconds `
        -BootstrapDeadlineSeconds $BootstrapDeadlineSeconds `
        -TimeoutSeconds $PackagedTimeoutSeconds | Out-Null
}

function Invoke-PowerShellFile {
    param(
        [string]$ScriptPath,
        [string[]]$Arguments,
        [string]$Label
    )

    Invoke-NativeAndRequireSuccess `
        -FilePath "powershell" `
        -Arguments (@("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $ScriptPath) + $Arguments) `
        -Label $Label
}

function Get-SafeFolderName {
    param([string]$Name)

    $invalid = [System.IO.Path]::GetInvalidFileNameChars()
    $safe = $Name
    foreach ($char in $invalid) {
        $safe = $safe.Replace($char, "_")
    }

    return $safe.Trim()
}

function Get-NormalizedArtifactContent {
    param(
        [string]$ArtifactPath,
        [string]$OutputRoot,
        [string]$PackageRoot
    )

    $text = Get-Content -LiteralPath $ArtifactPath -Raw -Encoding UTF8
    $normalized = $text -replace "`r`n", "`n"

    foreach ($replacement in @(
        [PSCustomObject]@{ Source = $PackageRoot; Token = "__PACKAGE_ROOT__" },
        [PSCustomObject]@{ Source = $OutputRoot; Token = "__OUTPUT_ROOT__" }
    )) {
        if (-not [string]::IsNullOrWhiteSpace($replacement.Source)) {
            $normalized = [regex]::Replace(
                $normalized,
                [regex]::Escape($replacement.Source),
                $replacement.Token
            )
        }
    }

    return $normalized
}

function Get-Sha256Hash {
    param([string]$Text)

    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return [System.BitConverter]::ToString($sha.ComputeHash($bytes)).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Test-SegmentIndexArtifact {
    param(
        [string]$ArtifactPath,
        [string]$OutputRoot,
        [psobject]$Artifact
    )

    $headers = @()
    $headerLine = Get-Content -LiteralPath $ArtifactPath -TotalCount 1 -Encoding UTF8
    if (-not [string]::IsNullOrWhiteSpace($headerLine)) {
        $headers = @(
            ($headerLine -replace "^\uFEFF", "") -split "," |
                ForEach-Object { $_.Trim('"') }
        )
    }

    $rows = @(Import-Csv -LiteralPath $ArtifactPath)
    $transcriptPath = Join-Path $OutputRoot $Artifact.transcript_relative_path
    if (-not (Test-Path -LiteralPath $transcriptPath)) {
        return [PSCustomObject]@{
            Passed   = $false
            Expected = "segment index must match transcript_original.json"
            Actual   = "missing transcript json"
            Lines    = ($rows.Count + 1)
        }
    }

    $transcriptPayload = Get-Content -LiteralPath $transcriptPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $segments = @($transcriptPayload.segments)
    $minimumRows = [int]$Artifact.minimum_rows
    $expectedHeaders = @($Artifact.required_headers)
    $headersMatch = (($headers -join "|") -eq ($expectedHeaders -join "|"))
    $rowCountMatchesTranscript = ($rows.Count -eq $segments.Count)
    $rowCountOk = ($rows.Count -ge $minimumRows)
    $sequenceOk = $true

    for ($index = 0; $index -lt $rows.Count; $index++) {
        if ([int]$rows[$index].segment_number -ne ($index + 1)) {
            $sequenceOk = $false
            break
        }
    }

    $passed = $headersMatch -and $rowCountMatchesTranscript -and $rowCountOk -and $sequenceOk
    $actual = "rows={0}; transcript_segments={1}; headers={2}; sequence_ok={3}" -f `
        $rows.Count, `
        $segments.Count, `
        ($headers -join ","), `
        $sequenceOk

    return [PSCustomObject]@{
        Passed   = $passed
        Expected = "rows>={0}; transcript_match; headers={1}" -f $minimumRows, ($expectedHeaders -join ",")
        Actual   = $actual
        Lines    = ($rows.Count + 1)
    }
}

function Test-ArtifactSet {
    param(
        [psobject]$FixtureSection,
        [string]$OutputRoot,
        [string]$SurfaceLabel,
        [string]$AppLabel
    )

    $results = @()
    $packageRoot = Join-Path $OutputRoot $FixtureSection.package_folder

    foreach ($artifact in @($FixtureSection.artifacts)) {
        $artifactPath = Join-Path $OutputRoot $artifact.relative_path
        if (-not (Test-Path -LiteralPath $artifactPath)) {
            Write-Host ("FAIL {0}/{1}: missing {2}" -f $SurfaceLabel, $AppLabel, $artifact.name) -ForegroundColor Red
            $results += [PSCustomObject]@{
                Surface    = $SurfaceLabel
                App        = $AppLabel
                Artifact   = $artifact.name
                Passed     = $false
                Expected   = [string]$artifact.hash
                Actual     = "<missing>"
                ExpectedLn = [int]$artifact.lines
                ActualLn   = 0
            }
            continue
        }

        $comparisonMode = if (-not [string]::IsNullOrWhiteSpace([string]$artifact.comparison_mode)) {
            [string]$artifact.comparison_mode
        }
        else {
            "exact_hash"
        }

        if ($comparisonMode -eq "segment_index_consistency") {
            $segmentCheck = Test-SegmentIndexArtifact -ArtifactPath $artifactPath -OutputRoot $OutputRoot -Artifact $artifact
            if ($segmentCheck.Passed) {
                Write-Host ("PASS {0}/{1}: {2}" -f $SurfaceLabel, $AppLabel, $artifact.name) -ForegroundColor Green
            }
            else {
                Write-Host (
                    "FAIL {0}/{1}: {2} ({3}; actual {4})" -f
                    $SurfaceLabel,
                    $AppLabel,
                    $artifact.name,
                    $segmentCheck.Expected,
                    $segmentCheck.Actual
                ) -ForegroundColor Red
            }

            $results += [PSCustomObject]@{
                Surface    = $SurfaceLabel
                App        = $AppLabel
                Artifact   = $artifact.name
                Passed     = $segmentCheck.Passed
                Expected   = $segmentCheck.Expected
                Actual     = $segmentCheck.Actual
                ExpectedLn = 0
                ActualLn   = [int]$segmentCheck.Lines
            }
            continue
        }

        $normalized = Get-NormalizedArtifactContent `
            -ArtifactPath $artifactPath `
            -OutputRoot $OutputRoot `
            -PackageRoot $packageRoot
        $actualHash = Get-Sha256Hash -Text $normalized
        $actualLines = ($normalized -split "`n").Count
        $passed = ($actualHash -eq [string]$artifact.hash -and $actualLines -eq [int]$artifact.lines)

        if ($passed) {
            Write-Host ("PASS {0}/{1}: {2}" -f $SurfaceLabel, $AppLabel, $artifact.name) -ForegroundColor Green
        }
        else {
            Write-Host (
                "FAIL {0}/{1}: {2} (expected {3}/{4} lines, actual {5}/{6} lines)" -f
                $SurfaceLabel,
                $AppLabel,
                $artifact.name,
                $artifact.hash,
                $artifact.lines,
                $actualHash,
                $actualLines
            ) -ForegroundColor Red
        }

        $results += [PSCustomObject]@{
            Surface    = $SurfaceLabel
            App        = $AppLabel
            Artifact   = $artifact.name
            Passed     = $passed
            Expected   = [string]$artifact.hash
            Actual     = $actualHash
            ExpectedLn = [int]$artifact.lines
            ActualLn   = $actualLines
        }
    }

    return $results
}

function Invoke-VideoSourceRun {
    param(
        [string]$InputPath,
        [string]$OutputRoot
    )

    $scriptPath = Join-Path $repoRoot "Video Mangler.ps1"
    Invoke-PowerShellFile `
        -ScriptPath $scriptPath `
        -Arguments @(
            "-InputPath", $InputPath,
            "-OutputFolder", $OutputRoot,
            "-FrameIntervalSeconds", $FrameIntervalSeconds.ToString("0.0", [System.Globalization.CultureInfo]::InvariantCulture),
            "-WhisperModel", $WhisperModel,
            "-SkipEstimate",
            "-NoPrompt",
            "-ProcessingMode", "Local"
        ) `
        -Label "Source Video Mangler"

    Invoke-PowerShellFile `
        -ScriptPath $videoValidator `
        -Arguments @(
            "-OutputRoot", $OutputRoot,
            "-VideoPath", $InputPath,
            "-FrameIntervalSeconds", $FrameIntervalSeconds.ToString("0.0", [System.Globalization.CultureInfo]::InvariantCulture)
        ) `
        -Label "Validate source video package"
}

function Invoke-AudioSourceRun {
    param(
        [string]$InputPath,
        [string]$OutputRoot
    )

    $scriptPath = Join-Path $repoRoot "Audio Mangler.ps1"
    Invoke-PowerShellFile `
        -ScriptPath $scriptPath `
        -Arguments @(
            "-InputPath", $InputPath,
            "-OutputFolder", $OutputRoot,
            "-WhisperModel", $WhisperModel,
            "-SkipEstimate",
            "-NoPrompt",
            "-ProcessingMode", "Local"
        ) `
        -Label "Source Audio Mangler"

    Invoke-PowerShellFile `
        -ScriptPath $audioValidator `
        -Arguments @(
            "-OutputRoot", $OutputRoot,
            "-AudioPath", $InputPath
        ) `
        -Label "Validate source audio package"
}

function Get-ReleaseZipPath {
    param([string]$Pattern)

    $releaseRoot = Join-Path $repoRoot "dist\release"
    $candidate = Get-ChildItem -LiteralPath $releaseRoot -Filter $Pattern -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if (-not $candidate) {
        throw "Release zip not found for pattern: $Pattern"
    }

    return $candidate.FullName
}

function Expand-ReleaseZipAndFindExe {
    param(
        [string]$ZipPath,
        [string]$ExeName,
        [string]$DestinationRoot
    )

    Remove-PathIfPresent -Path $DestinationRoot
    Ensure-Directory $DestinationRoot
    Expand-Archive -LiteralPath $ZipPath -DestinationPath $DestinationRoot -Force

    $exe = Get-ChildItem -LiteralPath $DestinationRoot -Recurse -Filter $ExeName -File |
        Select-Object -First 1
    if (-not $exe) {
        throw "Executable not found after extracting $ZipPath"
    }

    return $exe.FullName
}

function Invoke-VideoReleaseRun {
    param(
        [string]$ExePath,
        [string]$InputPath,
        [string]$OutputRoot
    )

    Invoke-ExeAndRequireSuccess `
        -FilePath $ExePath `
        -Arguments @(
            "-InputPath", $InputPath,
            "-OutputFolder", $OutputRoot,
            "-FrameIntervalSeconds", $FrameIntervalSeconds.ToString("0.0", [System.Globalization.CultureInfo]::InvariantCulture),
            "-WhisperModel", $WhisperModel,
            "-SkipEstimate",
            "-NoPrompt",
            "-ProcessingMode", "Local"
        ) `
        -Label "Release Video Mangler.exe" `
        -OutputRoot $OutputRoot

    Invoke-PowerShellFile `
        -ScriptPath $videoValidator `
        -Arguments @(
            "-OutputRoot", $OutputRoot,
            "-VideoPath", $InputPath,
            "-FrameIntervalSeconds", $FrameIntervalSeconds.ToString("0.0", [System.Globalization.CultureInfo]::InvariantCulture)
        ) `
        -Label "Validate release video package"
}

function Invoke-AudioReleaseRun {
    param(
        [string]$ExePath,
        [string]$InputPath,
        [string]$OutputRoot
    )

    Invoke-ExeAndRequireSuccess `
        -FilePath $ExePath `
        -Arguments @(
            "-InputPath", $InputPath,
            "-OutputFolder", $OutputRoot,
            "-WhisperModel", $WhisperModel,
            "-SkipEstimate",
            "-NoPrompt",
            "-ProcessingMode", "Local"
        ) `
        -Label "Release Audio Mangler.exe" `
        -OutputRoot $OutputRoot

    Invoke-PowerShellFile `
        -ScriptPath $audioValidator `
        -Arguments @(
            "-OutputRoot", $OutputRoot,
            "-AudioPath", $InputPath
        ) `
        -Label "Validate release audio package"
}

if (-not (Test-Path -LiteralPath $fixturePath)) {
    throw "Parity fixture manifest not found: $fixturePath"
}

if (-not (Test-Path -LiteralPath $VideoPath)) {
    throw "Video fixture input not found: $VideoPath"
}

if (-not (Test-Path -LiteralPath $AudioPath)) {
    throw "Audio fixture input not found: $AudioPath"
}

$fixtures = Get-Content -LiteralPath $fixturePath -Raw -Encoding UTF8 | ConvertFrom-Json
$videoInputPath = (Resolve-Path -LiteralPath $VideoPath).ProviderPath
$audioInputPath = (Resolve-Path -LiteralPath $AudioPath).ProviderPath
Ensure-Directory $runRoot

$allResults = @()

if ($Surface -in @("Source", "All")) {
    $sourceRoot = Join-Path $runRoot "source"
    $sourceVideoRoot = Join-Path $sourceRoot "video"
    $sourceAudioRoot = Join-Path $sourceRoot "audio"
    Ensure-Directory $sourceRoot

    Invoke-VideoSourceRun -InputPath $videoInputPath -OutputRoot $sourceVideoRoot
    Invoke-AudioSourceRun -InputPath $audioInputPath -OutputRoot $sourceAudioRoot

    $allResults += Test-ArtifactSet -FixtureSection $fixtures.video -OutputRoot $sourceVideoRoot -SurfaceLabel "source" -AppLabel "video"
    $allResults += Test-ArtifactSet -FixtureSection $fixtures.audio -OutputRoot $sourceAudioRoot -SurfaceLabel "source" -AppLabel "audio"
}

if ($Surface -in @("Release", "All")) {
    if (-not $SkipBuild) {
        Invoke-PowerShellFile -ScriptPath $buildScript -Arguments @("-App", "All") -Label "Build release executables and zips"
    }

    $releaseRoot = Join-Path $runRoot "release"
    $extractRoot = Join-Path $releaseRoot "extracted"
    $releaseVideoRoot = Join-Path $releaseRoot "video-output"
    $releaseAudioRoot = Join-Path $releaseRoot "audio-output"
    Ensure-Directory $releaseRoot

    $videoZip = Get-ReleaseZipPath -Pattern "Video-Mangler-v*.zip"
    $audioZip = Get-ReleaseZipPath -Pattern "Audio-Mangler-v*.zip"
    $videoExe = Expand-ReleaseZipAndFindExe -ZipPath $videoZip -ExeName "Video Mangler.exe" -DestinationRoot (Join-Path $extractRoot "video")
    $audioExe = Expand-ReleaseZipAndFindExe -ZipPath $audioZip -ExeName "Audio Mangler.exe" -DestinationRoot (Join-Path $extractRoot "audio")

    Invoke-VideoReleaseRun -ExePath $videoExe -InputPath $videoInputPath -OutputRoot $releaseVideoRoot
    Invoke-AudioReleaseRun -ExePath $audioExe -InputPath $audioInputPath -OutputRoot $releaseAudioRoot

    $allResults += Test-ArtifactSet -FixtureSection $fixtures.video -OutputRoot $releaseVideoRoot -SurfaceLabel "release" -AppLabel "video"
    $allResults += Test-ArtifactSet -FixtureSection $fixtures.audio -OutputRoot $releaseAudioRoot -SurfaceLabel "release" -AppLabel "audio"
}

$failed = @($allResults | Where-Object { -not $_.Passed })
Write-Host ""
Write-Host "Artifact parity summary" -ForegroundColor Cyan
Write-Host ("Run root: {0}" -f $runRoot)
Write-Host ("Checks:   {0}" -f $allResults.Count)
Write-Host ("Failed:   {0}" -f $failed.Count)

if ($failed.Count -gt 0) {
    throw ("Artifact parity checks failed for {0} artifact(s)." -f $failed.Count)
}

Write-Host "PASS artifact parity checks completed." -ForegroundColor Green
