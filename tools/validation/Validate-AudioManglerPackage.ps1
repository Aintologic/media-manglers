param(
    [Parameter(Mandatory = $false)]
    [string]$OutputRoot,

    [Parameter(Mandatory = $false)]
    [string]$AudioPath,

    [string]$PackageFolderName,

    [int]$MinimumSegmentCount = 3
)

$ErrorActionPreference = "Stop"

function Get-LatestSmokeOutputFolder {
    param([string[]]$SearchRoots)

    foreach ($root in ($SearchRoots | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $root)) {
            continue
        }

        $latestSmoke = Get-ChildItem -LiteralPath $root -Directory |
            Where-Object { $_.Name -like 'audio-smoke-*' } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1

        if ($latestSmoke) {
            return $latestSmoke.FullName
        }
    }

    return $null
}

function Resolve-OutputRootPath {
    param(
        [string]$Path,
        [string]$DefaultSmokeRoot
    )

    if (-not [string]::IsNullOrWhiteSpace($Path) -and (Test-Path -LiteralPath $Path)) {
        return (Resolve-Path -LiteralPath $Path).ProviderPath
    }

    $searchRoots = New-Object System.Collections.Generic.List[string]

    if (-not [string]::IsNullOrWhiteSpace($Path)) {
        $parent = Split-Path -Path $Path -Parent
        if (-not [string]::IsNullOrWhiteSpace($parent)) {
            [void]$searchRoots.Add($parent)
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($DefaultSmokeRoot)) {
        [void]$searchRoots.Add($DefaultSmokeRoot)
    }

    $latestSmoke = Get-LatestSmokeOutputFolder -SearchRoots @($searchRoots)
    if ($latestSmoke) {
        return $latestSmoke
    }

    return $Path
}

function Get-PackageDirectories {
    param([string]$RootPath)

    if (-not (Test-Path -LiteralPath $RootPath)) {
        return @()
    }

    return @(Get-ChildItem -LiteralPath $RootPath -Directory | Where-Object {
        (Test-Path -LiteralPath (Join-Path $_.FullName "README_FOR_CODEX.txt")) -or
        (Test-Path -LiteralPath (Join-Path $_.FullName "segment_index.csv"))
    } | Sort-Object Name)
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

function Assert-File {
    param(
        [string]$Path,
        [string]$Label
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Missing required file: $Label ($Path)"
    }

    $item = Get-Item -LiteralPath $Path
    if ($item.Length -le 0) {
        throw "Required file is empty: $Label ($Path)"
    }
}

function Get-SummaryRow {
    param(
        [string]$SummaryCsvPath,
        [string]$PackageFolderName
    )

    if (-not (Test-Path -LiteralPath $SummaryCsvPath)) {
        return $null
    }

    $rows = @(Import-Csv -LiteralPath $SummaryCsvPath)
    if ($rows.Count -eq 0) {
        throw "Processing summary is empty: $SummaryCsvPath"
    }

    $matchingRow = $rows | Where-Object { $_.output_folder_name -eq $PackageFolderName } | Select-Object -First 1
    if ($matchingRow) {
        return $matchingRow
    }

    if ($rows.Count -eq 1) {
        return $rows[0]
    }

    return $null
}

function Assert-ColumnValue {
    param(
        [psobject]$Row,
        [string]$ColumnName,
        [string]$Label
    )

    if (-not ($Row.PSObject.Properties.Name -contains $ColumnName)) {
        throw "Missing required summary column: $ColumnName"
    }

    $value = [string]$Row.$ColumnName
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Summary column is empty: $Label ($ColumnName)"
    }

    return $value
}

function Test-IsHybridSummary {
    param([psobject]$Row)

    if (-not $Row) {
        return $false
    }

    $processingMode = if ($Row.PSObject.Properties.Name -contains "processing_mode") { [string]$Row.processing_mode } else { "" }
    $translationPath = if ($Row.PSObject.Properties.Name -contains "translation_path") { [string]$Row.translation_path } else { "" }

    return ($processingMode -like "Hybrid*") -or ($translationPath -like "*Hybrid Accuracy*")
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).ProviderPath
$defaultSmokeRoot = Join-Path $repoRoot "test-output"

$OutputRoot = Resolve-OutputRootPath -Path $OutputRoot -DefaultSmokeRoot $defaultSmokeRoot

if (-not (Test-Path -LiteralPath $OutputRoot)) {
    throw "Output root not found: $OutputRoot. Run .\tools\smoke\Run-AudioSmokeTest.ps1 first, or pass -OutputRoot to an existing audio package output folder."
}

$packageDirectories = Get-PackageDirectories -RootPath $OutputRoot
if (-not [string]::IsNullOrWhiteSpace($AudioPath)) {
    if (-not (Test-Path -LiteralPath $AudioPath)) {
        throw "Audio path not found: $AudioPath"
    }

    $audioItem = Get-Item -LiteralPath $AudioPath
    $baseName = [System.IO.Path]::GetFileNameWithoutExtension($audioItem.Name)
    $packageFolderName = Get-SafeFolderName -Name $baseName
}
elseif (-not [string]::IsNullOrWhiteSpace($PackageFolderName)) {
    $packageFolderName = Get-SafeFolderName -Name $PackageFolderName
}
elseif ($packageDirectories.Count -eq 1) {
    $packageFolderName = $packageDirectories[0].Name
}
elseif ($packageDirectories.Count -gt 1) {
    $choices = $packageDirectories | ForEach-Object { $_.Name }
    throw ("Multiple package folders found under {0}. Re-run with -PackageFolderName. Choices: {1}" -f $OutputRoot, ($choices -join ", "))
}
else {
    throw "No package folders found under: $OutputRoot"
}

$packageRoot = Join-Path $OutputRoot $packageFolderName
if (-not (Test-Path -LiteralPath $packageRoot)) {
    $choices = $packageDirectories | ForEach-Object { $_.Name }
    if ($choices.Count -gt 0) {
        throw ("Package folder not found: {0}. Available package folders: {1}" -f $packageRoot, ($choices -join ", "))
    }

    throw "Package folder not found: $packageRoot"
}

$reviewAudio = Join-Path $packageRoot "audio\review_audio.mp3"
$transcriptSrt = Join-Path $packageRoot "transcript\transcript_original.srt"
$transcriptJson = Join-Path $packageRoot "transcript\transcript_original.json"
$transcriptText = Join-Path $packageRoot "transcript\transcript_original.txt"
$segmentIndexCsv = Join-Path $packageRoot "segment_index.csv"
$readmePath = Join-Path $packageRoot "README_FOR_CODEX.txt"
$logPath = Join-Path $packageRoot "script_run.log"
$summaryCsv = Join-Path $OutputRoot "PROCESSING_SUMMARY.csv"
$masterReadme = Join-Path $OutputRoot "CODEX_MASTER_README.txt"
$translationsFolder = Join-Path $packageRoot "translations"
$commentsFolder = Join-Path $packageRoot "comments"

Assert-File -Path $reviewAudio -Label "review audio"
Assert-File -Path $transcriptSrt -Label "transcript srt"
Assert-File -Path $transcriptJson -Label "transcript json"
Assert-File -Path $transcriptText -Label "transcript txt"
Assert-File -Path $segmentIndexCsv -Label "segment index csv"
Assert-File -Path $readmePath -Label "readme"
Assert-File -Path $logPath -Label "script log"
Assert-File -Path $summaryCsv -Label "processing summary"
Assert-File -Path $masterReadme -Label "master readme"

$summaryRow = Get-SummaryRow -SummaryCsvPath $summaryCsv -PackageFolderName $packageFolderName
if (-not $summaryRow) {
    throw "Could not find package summary row for $packageFolderName in $summaryCsv"
}

$null = Assert-ColumnValue -Row $summaryRow -ColumnName "package_status" -Label "package status"
$isHybridPackage = Test-IsHybridSummary -Row $summaryRow

if ($isHybridPackage) {
    $validationReportFromSummary = Assert-ColumnValue -Row $summaryRow -ColumnName "translation_validation_report" -Label "translation validation report"
    Assert-File -Path $validationReportFromSummary -Label "translation validation report"

    if (-not ($summaryRow.PSObject.Properties.Name -contains "lane_id")) {
        throw "Missing required summary column: lane_id"
    }

    foreach ($columnName in @(
        "privacy_class",
        "source_language",
        "target_language",
        "transcription_provider",
        "transcription_model",
        "translation_provider_name",
        "translation_model",
        "translation_validation_status"
    )) {
        $null = Assert-ColumnValue -Row $summaryRow -ColumnName $columnName -Label $columnName
    }

    $validationReport = Get-Content -Raw -LiteralPath $validationReportFromSummary | ConvertFrom-Json
    $validationStatus = [string]$validationReport.validation_status
    if ([string]::IsNullOrWhiteSpace($validationStatus)) {
        throw "Hybrid validation report is missing validation_status: $validationReportFromSummary"
    }

    if (@("accepted", "partial", "rejected") -notcontains $validationStatus) {
        throw "Unexpected Hybrid validation status '$validationStatus' in $validationReportFromSummary"
    }
}

$segmentRows = @(Import-Csv -LiteralPath $segmentIndexCsv)
if ($segmentRows.Count -lt $MinimumSegmentCount) {
    throw "Expected at least $MinimumSegmentCount segment rows in $segmentIndexCsv but found $($segmentRows.Count)."
}

if (Test-Path -LiteralPath $translationsFolder) {
    foreach ($translationFolder in @(Get-ChildItem -LiteralPath $translationsFolder -Directory)) {
        Assert-File -Path (Join-Path $translationFolder.FullName "transcript.srt") -Label ("translation srt ({0})" -f $translationFolder.Name)
        Assert-File -Path (Join-Path $translationFolder.FullName "transcript.json") -Label ("translation json ({0})" -f $translationFolder.Name)
        Assert-File -Path (Join-Path $translationFolder.FullName "transcript.txt") -Label ("translation txt ({0})" -f $translationFolder.Name)
        if ($isHybridPackage) {
            Assert-File -Path (Join-Path $translationFolder.FullName "validation_report.json") -Label ("translation validation report ({0})" -f $translationFolder.Name)
        }
    }
}

if (Test-Path -LiteralPath $commentsFolder) {
    Assert-File -Path (Join-Path $commentsFolder "comments.txt") -Label "comments txt"
    Assert-File -Path (Join-Path $commentsFolder "comments.json") -Label "comments json"
}

Write-Host "PASS audio validation completed." -ForegroundColor Green
Write-Host ("Output root:   {0}" -f $OutputRoot)
Write-Host ("Package root:  {0}" -f $packageRoot)
Write-Host ("Segments found:{0,5}" -f $segmentRows.Count)
