param(
    [switch]$IncludePublicValidation,
    [switch]$KeepTestOutput,
    [switch]$UseLegacyKeyForPublicFallback,
    [string]$SummaryPath
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).ProviderPath
$videoSmokeScript = Join-Path $PSScriptRoot "Run-SmokeTest.ps1"
$audioSmokeScript = Join-Path $PSScriptRoot "Run-AudioSmokeTest.ps1"
$runId = "{0}-{1}" -f (Get-Date -Format "yyyyMMdd-HHmmss"), ([guid]::NewGuid().ToString("N").Substring(0, 8))

if ([string]::IsNullOrWhiteSpace($SummaryPath)) {
    $SummaryPath = Join-Path $repoRoot ("test-output\matrix-summary-{0}.csv" -f $runId)
}

function New-MatrixScenario {
    param(
        [string]$Id,
        [string]$App,
        [string]$Mode,
        [string]$SourceType,
        [string]$Label,
        [string]$ScriptPath,
        [string[]]$Arguments,
        [switch]$RequiresPublicKey
    )

    return [PSCustomObject]@{
        Id                = $Id
        App               = $App
        Mode              = $Mode
        SourceType        = $SourceType
        Label             = $Label
        ScriptPath        = $ScriptPath
        Arguments         = @($Arguments)
        RequiresPublicKey = [bool]$RequiresPublicKey
    }
}

function Invoke-MatrixScenario {
    param([pscustomobject]$Scenario)

    Write-Host ""
    Write-Host ("=== [{0}] {1} ===" -f $Scenario.Id, $Scenario.Label) -ForegroundColor Cyan

    $previousPublicKey = $null
    $injectedPublicKey = $false
    if ($Scenario.RequiresPublicKey -and $UseLegacyKeyForPublicFallback -and [string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY_PUBLIC) -and -not [string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
        $previousPublicKey = $env:OPENAI_API_KEY_PUBLIC
        $env:OPENAI_API_KEY_PUBLIC = $env:OPENAI_API_KEY
        $injectedPublicKey = $true
        Write-Host "Using OPENAI_API_KEY as a process-local OPENAI_API_KEY_PUBLIC fallback for this Public validation row." -ForegroundColor Yellow
    }

    try {
        $commandOutput = & powershell -NoProfile -ExecutionPolicy Bypass -File $Scenario.ScriptPath @($Scenario.Arguments) 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        if ($Scenario.RequiresPublicKey -and $UseLegacyKeyForPublicFallback) {
            if ($null -eq $previousPublicKey) {
                Remove-Item Env:OPENAI_API_KEY_PUBLIC -ErrorAction SilentlyContinue
            }
            else {
                $env:OPENAI_API_KEY_PUBLIC = $previousPublicKey
            }
        }
    }

    $outputLines = @($commandOutput | ForEach-Object { [string]$_ })
    $outputRoot = ""
    for ($index = $outputLines.Count - 1; $index -ge 0; $index--) {
        $line = $outputLines[$index]
        if ($line -match '^(?:Audio smoke test output root|Smoke test output root|Output root)\s*:\s*(.+)$') {
            $outputRoot = $matches[1].Trim()
            break
        }
    }

    $status = if ($exitCode -eq 0) { "PASS" } else { "FAIL" }
    $note = ""
    if ($injectedPublicKey) {
        $note = "Used OPENAI_API_KEY as a process-local OPENAI_API_KEY_PUBLIC fallback."
    }

    if ($status -eq "FAIL") {
        $requestId = ""
        for ($index = $outputLines.Count - 1; $index -ge 0; $index--) {
            $line = $outputLines[$index]
            if ($line -match 'request_id=([A-Za-z0-9_]+)') {
                $requestId = $matches[1]
                break
            }
        }

        $failureLine = @($outputLines | Where-Object { $_ -match 'OpenAI transcription failed with HTTP 401 Unauthorized|Audio smoke test packaging run failed|Smoke test packaging run failed|Processing completed with \d+ hard failure' } | Select-Object -Last 1)
        if ($failureLine.Count -gt 0) {
            $note = if ([string]::IsNullOrWhiteSpace($note)) { $failureLine[0] } else { "{0} {1}" -f $note, $failureLine[0] }
        }
        if (-not [string]::IsNullOrWhiteSpace($requestId)) {
            $note = if ([string]::IsNullOrWhiteSpace($note)) { "request_id=$requestId" } else { "{0} request_id={1}" -f $note, $requestId }
        }
    }

    Write-Host ("Result: {0}" -f $status) -ForegroundColor $(if ($status -eq "PASS") { "Green" } else { "Red" })
    if (-not [string]::IsNullOrWhiteSpace($outputRoot)) {
        Write-Host ("Output root: {0}" -f $outputRoot) -ForegroundColor DarkGray
    }
    if (-not [string]::IsNullOrWhiteSpace($note)) {
        Write-Host ("Note: {0}" -f $note) -ForegroundColor DarkGray
    }

    return [PSCustomObject]@{
        RowId       = $Scenario.Id
        App         = $Scenario.App
        Mode        = $Scenario.Mode
        SourceType  = $Scenario.SourceType
        Scenario    = $Scenario.Label
        Status      = $status
        ExitCode    = $exitCode
        OutputRoot  = $outputRoot
        Note        = $note
    }
}

$scenarios = @(
    (New-MatrixScenario -Id "A" -App "Video" -Mode "Local" -SourceType "English" -Label "VIDEO Local English" -ScriptPath $videoSmokeScript -Arguments @("-TranslateTo", "es", "-ProcessingMode", "Local", "-SkipEstimate")),
    (New-MatrixScenario -Id "B" -App "Video" -Mode "Local" -SourceType "Foreign" -Label "VIDEO Local Foreign" -ScriptPath $videoSmokeScript -Arguments @("-VideoPath", (Join-Path $repoRoot "test-output\translation-provider-fixture\german_clip_jfySUBLx8Ps.webm"), "-TranslateTo", "en", "-ProcessingMode", "Local", "-SkipEstimate")),
    (New-MatrixScenario -Id "C" -App "Video" -Mode "AI Private" -SourceType "English" -Label "VIDEO AI Private English" -ScriptPath $videoSmokeScript -Arguments @("-TranslateTo", "es", "-ProcessingMode", "AI", "-OpenAiProject", "Private", "-SkipEstimate")),
    (New-MatrixScenario -Id "D" -App "Video" -Mode "AI Private" -SourceType "Foreign" -Label "VIDEO AI Private Foreign" -ScriptPath $videoSmokeScript -Arguments @("-VideoPath", (Join-Path $repoRoot "test-output\translation-provider-fixture\german_clip_jfySUBLx8Ps.webm"), "-TranslateTo", "en", "-ProcessingMode", "AI", "-OpenAiProject", "Private", "-SkipEstimate")),
    (New-MatrixScenario -Id "E" -App "Audio" -Mode "Local" -SourceType "English" -Label "AUDIO Local English" -ScriptPath $audioSmokeScript -Arguments @("-AudioPath", (Join-Path $repoRoot "test-output\gui-fixtures\gettysburg_address.mp3"), "-TranslateTo", "es", "-ProcessingMode", "Local", "-SkipEstimate")),
    (New-MatrixScenario -Id "F" -App "Audio" -Mode "Local" -SourceType "Foreign" -Label "AUDIO Local Foreign" -ScriptPath $audioSmokeScript -Arguments @("-TranslateToEnglish", "-ProcessingMode", "Local", "-SkipEstimate")),
    (New-MatrixScenario -Id "G" -App "Audio" -Mode "AI Private" -SourceType "English" -Label "AUDIO AI Private English" -ScriptPath $audioSmokeScript -Arguments @("-AudioPath", (Join-Path $repoRoot "test-output\gui-fixtures\gettysburg_address.mp3"), "-TranslateTo", "es", "-ProcessingMode", "AI", "-OpenAiProject", "Private", "-SkipEstimate")),
    (New-MatrixScenario -Id "H" -App "Audio" -Mode "AI Private" -SourceType "Foreign" -Label "AUDIO AI Private Foreign" -ScriptPath $audioSmokeScript -Arguments @("-TranslateToEnglish", "-ProcessingMode", "AI", "-OpenAiProject", "Private", "-SkipEstimate"))
)

if ($IncludePublicValidation) {
    $scenarios += @(
        (New-MatrixScenario -Id "P1" -App "Video" -Mode "AI Public" -SourceType "Foreign" -Label "VIDEO AI Public Foreign" -ScriptPath $videoSmokeScript -Arguments @("-VideoPath", (Join-Path $repoRoot "test-output\translation-provider-fixture\german_clip_jfySUBLx8Ps.webm"), "-TranslateTo", "en", "-ProcessingMode", "AI", "-OpenAiProject", "Public", "-SkipEstimate") -RequiresPublicKey),
        (New-MatrixScenario -Id "P2" -App "Audio" -Mode "AI Public" -SourceType "English" -Label "AUDIO AI Public English" -ScriptPath $audioSmokeScript -Arguments @("-AudioPath", (Join-Path $repoRoot "test-output\gui-fixtures\gettysburg_address.mp3"), "-TranslateTo", "es", "-ProcessingMode", "AI", "-OpenAiProject", "Public", "-SkipEstimate") -RequiresPublicKey)
    )
}

foreach ($scenario in $scenarios) {
    if ($KeepTestOutput) {
        $scenario.Arguments += "-KeepTestOutput"
    }
}

$summaryFolder = Split-Path -Parent $SummaryPath
if (-not [string]::IsNullOrWhiteSpace($summaryFolder)) {
    New-Item -ItemType Directory -Path $summaryFolder -Force | Out-Null
}

$results = foreach ($scenario in $scenarios) {
    Invoke-MatrixScenario -Scenario $scenario
}

$results | Export-Csv -Path $SummaryPath -NoTypeInformation -Encoding UTF8

Write-Host ""
Write-Host "=== Matrix Summary ===" -ForegroundColor Cyan
$results | Format-Table RowId, App, Mode, SourceType, Status, OutputRoot -AutoSize
Write-Host ("Summary CSV: {0}" -f $SummaryPath) -ForegroundColor Cyan

if (($results | Where-Object { $_.Status -ne "PASS" }).Count -gt 0) {
    exit 1
}

exit 0
