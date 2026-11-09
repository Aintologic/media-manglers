param(
    [string]$SuiteManifestPath = "",
    [string]$LaneManifestPath = "",
    [string[]]$LaneId = @(),
    [string[]]$SourceId = @(),
    [ValidateSet("Audio", "Video")]
    [string]$AppSurface = "Audio",
    [string]$OutputRoot = "",
    [string]$PythonExe = "python",
    [int]$HeartbeatSeconds = 15,
    [switch]$DebugMode,
    [switch]$SkipEstimate,
    [switch]$IncludeDeferredRows,
    [switch]$AggregateOnly
)

$ErrorActionPreference = "Stop"

function Ensure-Directory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        $null = New-Item -ItemType Directory -Path $Path -Force
    }
}

function Read-JsonFile {
    param([string]$Path)
    return (Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json)
}

function Write-JsonFile {
    param(
        [string]$Path,
        [object]$Value
    )
    $Value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Format-CommandArgument {
    param([string]$Value)
    if ($Value -match '\s') {
        return ('"{0}"' -f ($Value -replace '"', '\"'))
    }
    return $Value
}

function Format-CommandLine {
    param([string[]]$Arguments)
    $parts = foreach ($argument in $Arguments) {
        Format-CommandArgument -Value ([string]$argument)
    }
    return "powershell.exe " + ($parts -join " ")
}

function Get-ShortBenchmarkToken {
    param(
        [string]$Value,
        [int]$MaxLength = 16,
        [string]$Fallback = "item"
    )
    $safe = [regex]::Replace(([string]$Value).Trim(), '[^A-Za-z0-9._-]', '-')
    $safe = $safe.Trim('-')
    if ([string]::IsNullOrWhiteSpace($safe)) {
        return $Fallback
    }
    if ($safe.Length -gt $MaxLength) {
        return $safe.Substring(0, $MaxLength)
    }
    return $safe
}

function Get-StableBenchmarkHash {
    param(
        [string]$Value,
        [int]$Length = 8
    )
    $hashProvider = [System.Security.Cryptography.SHA1]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes([string]$Value)
        $hashBytes = $hashProvider.ComputeHash($bytes)
        $hashText = ([System.BitConverter]::ToString($hashBytes)).Replace("-", "").ToLowerInvariant()
        if ($Length -lt 1) {
            return $hashText
        }
        return $hashText.Substring(0, [Math]::Min($Length, $hashText.Length))
    }
    finally {
        if ($hashProvider) {
            $hashProvider.Dispose()
        }
    }
}

function Get-StableBenchmarkFolderName {
    param(
        [string]$Prefix,
        [string]$Value,
        [int]$TokenLength = 14,
        [int]$HashLength = 8,
        [string]$Fallback = "item"
    )
    $token = Get-ShortBenchmarkToken -Value $Value -MaxLength $TokenLength -Fallback $Fallback
    $hash = Get-StableBenchmarkHash -Value $Value -Length $HashLength
    return "{0}-{1}-{2}" -f $Prefix, $token, $hash
}

function Select-PythonCommand {
    param([string]$RequestedCommand)
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($RequestedCommand)) {
        $candidates += $RequestedCommand
    }
    $candidates += @("python", "py")
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command) {
            return $command.Name
        }
    }
    throw "Could not resolve a Python command for benchmark aggregation."
}

function Resolve-ManifestSelection {
    param(
        [object[]]$Items,
        [string]$KeyName,
        [string[]]$RequestedIds
    )
    if (-not $RequestedIds -or $RequestedIds.Count -eq 0) {
        return @($Items)
    }

    $requestedMap = @{}
    foreach ($item in $RequestedIds) {
        $requestedMap[$item] = $true
    }
    $selected = @($Items | Where-Object { $requestedMap.ContainsKey([string]$_.$KeyName) })
    $selectedIds = @($selected | ForEach-Object { [string]$_.$KeyName })
    $missing = @($RequestedIds | Where-Object { $_ -notin $selectedIds })
    if ($missing.Count -gt 0) {
        throw ("Unknown {0} value(s): {1}" -f $KeyName, ($missing -join ", "))
    }
    return $selected
}

$repoRoot = Split-Path -Path (Split-Path -Path $PSScriptRoot -Parent) -Parent
if ([string]::IsNullOrWhiteSpace($SuiteManifestPath)) {
    $SuiteManifestPath = Join-Path $PSScriptRoot "manifests\canonical-short.json"
}
if ([string]::IsNullOrWhiteSpace($LaneManifestPath)) {
    $LaneManifestPath = Join-Path $PSScriptRoot "manifests\benchmark-lanes-v1.json"
}

$suiteManifest = Read-JsonFile -Path $SuiteManifestPath
$laneManifest = Read-JsonFile -Path $LaneManifestPath
$selectedSources = Resolve-ManifestSelection -Items @($suiteManifest.sources) -KeyName "source_id" -RequestedIds $SourceId
$selectedLanes = Resolve-ManifestSelection -Items @($laneManifest.lanes | Where-Object { [string]$_.app_surface -eq $AppSurface }) -KeyName "lane_id" -RequestedIds $LaneId
$selectedLanes = @($selectedLanes | Sort-Object pilot_priority, lane_id)

if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    # Benchmark output stays in the repository's local-only AREA51 folder;
    # system temp folders get purged.
    $tempBenchmarkRoot = Join-Path $repoRoot "AREA51\TEMP\benchmarks"
    New-Item -ItemType Directory -Path $tempBenchmarkRoot -Force | Out-Null
    if (Test-Path -LiteralPath $tempBenchmarkRoot) {
        $OutputRoot = Join-Path $tempBenchmarkRoot ("mm-bench-{0}-{1}" -f (Get-ShortBenchmarkToken -Value [string]$suiteManifest.suite_id -MaxLength 12 -Fallback "suite"), $timestamp)
    }
    else {
        $OutputRoot = Join-Path $repoRoot ("test-output\bench\{0}-{1}" -f (Get-ShortBenchmarkToken -Value [string]$suiteManifest.suite_id -MaxLength 12 -Fallback "suite"), $timestamp)
    }
}
elseif (-not [System.IO.Path]::IsPathRooted($OutputRoot)) {
    $OutputRoot = Join-Path $repoRoot $OutputRoot
}
Ensure-Directory -Path $OutputRoot
$OutputRoot = (Resolve-Path -LiteralPath $OutputRoot).ProviderPath

$appScriptPath = Join-Path $repoRoot $(if ($AppSurface -eq "Video") { "Video Mangler.ps1" } else { "Audio Mangler.ps1" })
$pythonCommand = Select-PythonCommand -RequestedCommand $PythonExe
$selectedLaneIds = @($selectedLanes | ForEach-Object { [string]$_.lane_id })
$selectedSourceIds = @($selectedSources | ForEach-Object { [string]$_.source_id })

Write-Host ""
Write-Host ("Benchmark suite: {0}" -f $suiteManifest.suite_label) -ForegroundColor Cyan
Write-Host ("App surface:     {0}" -f $AppSurface) -ForegroundColor Cyan
Write-Host ("Output root:     {0}" -f $OutputRoot) -ForegroundColor Cyan
Write-Host ("Sources:         {0}" -f ($selectedSourceIds -join ", ")) -ForegroundColor Cyan
Write-Host ("Lanes:           {0}" -f ($selectedLaneIds -join ", ")) -ForegroundColor Cyan
Write-Host ""

if (-not $AggregateOnly) {
    foreach ($lane in $selectedLanes) {
        $laneFolderName = Get-StableBenchmarkFolderName -Prefix "lane" -Value ([string]$lane.lane_id) -TokenLength 14 -HashLength 8 -Fallback "lane"
        foreach ($source in $selectedSources) {
            $laneIdValue = [string]$lane.lane_id
            $sourceIdValue = [string]$source.source_id
            if (-not [bool]$lane.supported) {
                Write-Host ("Skipping unsupported lane {0}: {1}" -f $laneIdValue, [string]$lane.deferred_reason) -ForegroundColor Yellow
                continue
            }

            $sourceFolderName = if (-not [string]::IsNullOrWhiteSpace([string]$source.video_id)) {
                [string]$source.video_id
            }
            else {
                Get-StableBenchmarkFolderName -Prefix "src" -Value $sourceIdValue -TokenLength 14 -HashLength 8 -Fallback "source"
            }
            $runRoot = Join-Path (Join-Path $OutputRoot $laneFolderName) $sourceFolderName
            $outputPath = Join-Path $runRoot "output"
            $inputCachePath = Join-Path $runRoot "input-cache"
            $laneMetaPath = Join-Path $runRoot "lane-meta.json"
            Ensure-Directory -Path $runRoot
            Ensure-Directory -Path $outputPath
            Ensure-Directory -Path $inputCachePath

            $argList = @(
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-File", $appScriptPath,
                "-InputPath", [string]$source.url,
                "-InputFolder", $inputCachePath,
                "-OutputFolder", $outputPath,
                "-ProcessingMode", [string]$lane.processing_mode,
                "-HeartbeatSeconds", [string]$HeartbeatSeconds,
                "-NoPrompt"
            )
            if ($SkipEstimate) {
                $argList += "-SkipEstimate"
            }
            if ($DebugMode) {
                $argList += "-DebugMode"
            }
            if (-not [string]::IsNullOrWhiteSpace([string]$lane.translate_to)) {
                $argList += @("-TranslateTo", [string]$lane.translate_to)
            }
            if (-not [string]::IsNullOrWhiteSpace([string]$lane.whisper_model)) {
                $argList += @("-WhisperModel", [string]$lane.whisper_model)
            }
            if (-not [string]::IsNullOrWhiteSpace([string]$lane.whisper_device)) {
                $argList += @("-WhisperDevice", [string]$lane.whisper_device)
            }
            if (-not [string]::IsNullOrWhiteSpace([string]$lane.openai_project)) {
                $argList += @("-OpenAiProject", [string]$lane.openai_project)
            }
            if (-not [string]::IsNullOrWhiteSpace([string]$lane.openai_model)) {
                $argList += @("-OpenAiModel", [string]$lane.openai_model)
            }
            if (-not [string]::IsNullOrWhiteSpace([string]$lane.protected_terms_profile)) {
                $argList += @("-ProtectedTermsProfile", [string]$lane.protected_terms_profile)
            }
            $expectedNamedEntitiesPath = ""
            if ($null -ne $source.PSObject.Properties['expected_named_entities'] -and @($source.expected_named_entities).Count -gt 0) {
                $expectedNamedEntitiesPath = Join-Path $runRoot "expected_named_entities.json"
                (@($source.expected_named_entities) | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $expectedNamedEntitiesPath -Encoding UTF8
            }
            if (-not [string]::IsNullOrWhiteSpace($expectedNamedEntitiesPath)) {
                $argList += @("-ExpectedNamedEntitiesPath", $expectedNamedEntitiesPath)
            }

            $commandText = Format-CommandLine -Arguments $argList
            $laneMeta = [ordered]@{
                benchmark_run_id = "{0}__{1}__{2}" -f [string]$suiteManifest.suite_id, $sourceIdValue, $laneIdValue
                suite_id = [string]$suiteManifest.suite_id
                suite_label = [string]$suiteManifest.suite_label
                source_id = $sourceIdValue
                source_label = [string]$source.title
                source_url = [string]$source.url
                source_folder = $sourceFolderName
                lane_id = $laneIdValue
                lane_label = [string]$lane.label
                lane_folder = $laneFolderName
                app_surface = $AppSurface
                requested_processing_mode = [string]$lane.processing_mode
                requested_translate_to = [string]$lane.translate_to
                requested_whisper_model = [string]$lane.whisper_model
                requested_whisper_device = [string]$lane.whisper_device
                requested_openai_project = [string]$lane.openai_project
                requested_openai_model = [string]$lane.openai_model
                requested_openai_transcription_model = [string]$lane.openai_transcription_model
                requested_protected_terms_profile = [string]$lane.protected_terms_profile
                expected_named_entities = @($source.expected_named_entities)
                expected_named_entities_path = $expectedNamedEntitiesPath
                run_requested_at_utc = (Get-Date).ToUniversalTime().ToString("o")
                input_cache_root = $inputCachePath
                output_root = $outputPath
                summary_csv_path = (Join-Path $outputPath "PROCESSING_SUMMARY.csv")
                lane_meta_path = $laneMetaPath
                command = $commandText
            }
            Write-JsonFile -Path $laneMetaPath -Value $laneMeta

            Write-Host ("Running {0} / {1}" -f $laneIdValue, $sourceIdValue) -ForegroundColor Yellow
            $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
            $runnerError = ""
            $exitCode = 0
            try {
                $startArgumentString = ($argList | ForEach-Object { Format-CommandArgument -Value ([string]$_) }) -join " "
                $childProcess = Start-Process `
                    -FilePath "powershell.exe" `
                    -ArgumentList $startArgumentString `
                    -WorkingDirectory $repoRoot `
                    -NoNewWindow `
                    -Wait `
                    -PassThru
                $exitCode = if ($childProcess) { [int]$childProcess.ExitCode } else { 1 }
            }
            catch {
                $exitCode = 1
                $runnerError = $_.Exception.Message
            }
            $stopwatch.Stop()

            $laneMeta.run_completed_at_utc = (Get-Date).ToUniversalTime().ToString("o")
            $laneMeta.run_duration_seconds = [math]::Round($stopwatch.Elapsed.TotalSeconds, 3)
            $laneMeta.run_exit_code = $exitCode
            if (-not [string]::IsNullOrWhiteSpace($runnerError)) {
                $laneMeta.runner_error = $runnerError
            }
            Write-JsonFile -Path $laneMetaPath -Value $laneMeta

            if ($exitCode -eq 0) {
                Write-Host ("Completed {0} / {1} in {2}s" -f $laneIdValue, $sourceIdValue, $laneMeta.run_duration_seconds) -ForegroundColor Green
            }
            else {
                Write-Host ("Run failed {0} / {1} with exit code {2}" -f $laneIdValue, $sourceIdValue, $exitCode) -ForegroundColor Red
            }
            Write-Host ""
        }
    }
}

$reportArgs = @(
    (Join-Path $PSScriptRoot "benchmark_report.py"),
    "--run-root", $OutputRoot,
    "--suite-manifest", $SuiteManifestPath,
    "--lane-manifest", $LaneManifestPath,
    "--lane-ids", ($selectedLaneIds -join ","),
    "--source-ids", ($selectedSourceIds -join ",")
)
if ($IncludeDeferredRows) {
    $reportArgs += "--include-deferred"
}

& $pythonCommand @reportArgs
if ($LASTEXITCODE -ne 0) {
    throw ("Benchmark report generation failed with exit code {0}." -f $LASTEXITCODE)
}

Write-Host ("Benchmark outputs: {0}" -f (Join-Path $OutputRoot "summary")) -ForegroundColor Green
