param(
    [ValidateSet("Video", "Audio", "All")]
    [string]$App = "All",
    [switch]$KeepPackageStaging
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).ProviderPath
$distFolder = Join-Path $repoRoot "dist"
$binRoot = Join-Path $distFolder "bin"
$releaseRoot = Join-Path $distFolder "release"
$stagingRoot = Join-Path $distFolder "staging"
$archiveRoot = Join-Path $distFolder "archive"
$releaseArchiveRoot = Join-Path $archiveRoot "release"
$versionFile = Join-Path $repoRoot "VERSION"
$pyprojectFile = Join-Path $repoRoot "pyproject.toml"
$pythonCoreSourceRoot = Join-Path $repoRoot "src"
$glossariesSourceRoot = Join-Path $repoRoot "glossaries"
$docsRoot = Join-Path $repoRoot "docs"
$guidesRoot = Join-Path $docsRoot "guides"
$releaseNotesRoot = Join-Path $docsRoot "release-notes"
$modulePath = Join-Path $HOME "Documents\PowerShell\Modules\ps2exe\1.0.17\ps2exe.psm1"

function Ensure-Directory {
    param([string]$Path)

    if (-not [string]::IsNullOrWhiteSpace($Path) -and -not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Remove-PathIfPresent {
    param([string]$Path)

    if (-not [string]::IsNullOrWhiteSpace($Path) -and (Test-Path -LiteralPath $Path)) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

function Remove-DirectoryIfEmpty {
    param([string]$Path)

    if (-not [string]::IsNullOrWhiteSpace($Path) -and (Test-Path -LiteralPath $Path)) {
        $item = Get-Item -LiteralPath $Path
        if ($item.PSIsContainer -and @((Get-ChildItem -LiteralPath $Path -Force)).Count -eq 0) {
            Remove-Item -LiteralPath $Path -Force
        }
    }
}

function Copy-DirectoryContents {
    param(
        [string]$SourceRoot,
        [string]$DestinationRoot
    )

    if (-not (Test-Path -LiteralPath $SourceRoot -PathType Container)) {
        throw "Directory copy source not found: $SourceRoot"
    }

    Ensure-Directory $DestinationRoot

    foreach ($directory in @(Get-ChildItem -LiteralPath $SourceRoot -Recurse -Directory -Force)) {
        $relativePath = $directory.FullName.Substring($SourceRoot.Length).TrimStart('\', '/')
        if (-not [string]::IsNullOrWhiteSpace($relativePath)) {
            Ensure-Directory (Join-Path $DestinationRoot $relativePath)
        }
    }

    foreach ($file in @(Get-ChildItem -LiteralPath $SourceRoot -Recurse -File -Force)) {
        $relativePath = $file.FullName.Substring($SourceRoot.Length).TrimStart('\', '/')
        $destinationFile = Join-Path $DestinationRoot $relativePath
        Ensure-Directory ([System.IO.Path]::GetDirectoryName($destinationFile))
        [System.IO.File]::Copy($file.FullName, $destinationFile, $true)
    }
}

function Assert-PythonCoreSidecar {
    param([string]$PythonCoreRoot)

    $requiredFiles = @(
        "pyproject.toml",
        "src\media_manglers\__init__.py",
        "src\media_manglers\__main__.py",
        "src\media_manglers\cli.py",
        "src\media_manglers\contracts.py",
        "src\media_manglers_workbench\__init__.py",
        "src\media_manglers_workbench\audio_detection.py"
    )

    foreach ($requiredRelativePath in $requiredFiles) {
        $requiredPath = Join-Path $PythonCoreRoot $requiredRelativePath
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
            throw "Python core sidecar is missing required file: $requiredPath"
        }
    }

    $unexpectedArtifacts = @(
        Get-ChildItem -LiteralPath $PythonCoreRoot -Recurse -Force -ErrorAction SilentlyContinue |
            Where-Object {
                ($_.PSIsContainer -and $_.Name -eq "__pycache__") -or
                (-not $_.PSIsContainer -and $_.Extension -eq ".pyc")
            }
    )
    if ($unexpectedArtifacts.Count -gt 0) {
        $artifactList = ($unexpectedArtifacts | Select-Object -ExpandProperty FullName) -join ", "
        throw "Python core sidecar still contains compiled Python artifacts: $artifactList"
    }
}

function Copy-PythonCoreSidecar {
    param(
        [string]$PythonCoreSourceRoot,
        [string]$PyprojectFile,
        [string]$DestinationRoot
    )

    $sourcePackageRoot = Join-Path $PythonCoreSourceRoot "media_manglers"
    $sourceWorkbenchPackageRoot = Join-Path $PythonCoreSourceRoot "media_manglers_workbench"
    if (-not (Test-Path -LiteralPath $sourcePackageRoot)) {
        throw "Python core package not found: $sourcePackageRoot"
    }
    foreach ($sharedDependency in @(
        (Join-Path $sourceWorkbenchPackageRoot "__init__.py"),
        (Join-Path $sourceWorkbenchPackageRoot "audio_detection.py")
    )) {
        if (-not (Test-Path -LiteralPath $sharedDependency -PathType Leaf)) {
            throw "Shared Python core dependency not found: $sharedDependency"
        }
    }

    if (-not (Test-Path -LiteralPath $PyprojectFile)) {
        throw "Python core pyproject not found: $PyprojectFile"
    }

    $destinationPythonCoreRoot = Join-Path $DestinationRoot "python-core"
    $destinationSourceRoot = Join-Path $destinationPythonCoreRoot "src"
    $destinationPackageRoot = Join-Path $destinationSourceRoot "media_manglers"
    $destinationWorkbenchPackageRoot = Join-Path $destinationSourceRoot "media_manglers_workbench"

    Remove-PathIfPresent -Path $destinationPythonCoreRoot
    Ensure-Directory $destinationSourceRoot
    Ensure-Directory $destinationPackageRoot
    Ensure-Directory $destinationWorkbenchPackageRoot

    Copy-DirectoryContents -SourceRoot $sourcePackageRoot -DestinationRoot $destinationPackageRoot
    [System.IO.File]::Copy(
        (Join-Path $sourceWorkbenchPackageRoot "__init__.py"),
        (Join-Path $destinationWorkbenchPackageRoot "__init__.py"),
        $true
    )
    [System.IO.File]::Copy(
        (Join-Path $sourceWorkbenchPackageRoot "audio_detection.py"),
        (Join-Path $destinationWorkbenchPackageRoot "audio_detection.py"),
        $true
    )
    [System.IO.File]::Copy($PyprojectFile, (Join-Path $destinationPythonCoreRoot "pyproject.toml"), $true)

    foreach ($cacheDirectory in @(Get-ChildItem -LiteralPath $destinationPythonCoreRoot -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue)) {
        Remove-Item -LiteralPath $cacheDirectory.FullName -Recurse -Force
    }

    foreach ($compiledFile in @(
        Get-ChildItem -LiteralPath $destinationPythonCoreRoot -Recurse -File -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension -eq ".pyc" }
    )) {
        Remove-Item -LiteralPath $compiledFile.FullName -Force
    }

    Assert-PythonCoreSidecar -PythonCoreRoot $destinationPythonCoreRoot
}

function Copy-GlossarySidecar {
    param(
        [string]$GlossariesSourceRoot,
        [string]$DestinationRoot
    )

    if (-not (Test-Path -LiteralPath $GlossariesSourceRoot -PathType Container)) {
        throw "Glossary asset folder not found: $GlossariesSourceRoot"
    }

    $destinationGlossariesRoot = Join-Path $DestinationRoot "glossaries"
    Remove-PathIfPresent -Path $destinationGlossariesRoot
    Copy-DirectoryContents -SourceRoot $GlossariesSourceRoot -DestinationRoot $destinationGlossariesRoot
}

function Move-ItemToArchive {
    param(
        [string]$Path,
        [string]$ArchiveRoot
    )

    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path)) {
        return $false
    }

    Ensure-Directory $ArchiveRoot

    $item = Get-Item -LiteralPath $Path
    $destinationPath = Join-Path $ArchiveRoot $item.Name

    if (Test-Path -LiteralPath $destinationPath) {
        Remove-Item -LiteralPath $destinationPath -Recurse -Force
    }

    Move-Item -LiteralPath $Path -Destination $destinationPath -Force
    return $true
}

if (-not (Test-Path -LiteralPath $versionFile)) {
    throw "Version file not found: $versionFile"
}

if (-not (Test-Path -LiteralPath $modulePath)) {
    throw "ps2exe module not found at: $modulePath"
}

$appVersion = (Get-Content -LiteralPath $versionFile | Select-Object -First 1).Trim()
if ([string]::IsNullOrWhiteSpace($appVersion)) {
    throw "Version file is empty: $versionFile"
}

$releaseNotes = Join-Path $releaseNotesRoot ("RELEASE_NOTES_v{0}.txt" -f $appVersion)
if (-not (Test-Path -LiteralPath $releaseNotes)) {
    throw "Release notes file not found: $releaseNotes"
}

$appConfigs = @(
    [PSCustomObject]@{
        Key             = "Video"
        ScriptFile      = "Video Mangler.ps1"
        PackageExeName  = "Video Mangler.exe"
        BinExeName      = "Video-Mangler.exe"
        ReleaseZipName  = "Video-Mangler-v{0}.zip" -f $appVersion
        ReleaseFolder   = "Video-Mangler-v{0}" -f $appVersion
        IconFile        = "assets\Video Mangler.ico"
        ProductName     = "Video Mangler"
        Description     = "Builds review packages from local videos, remote URLs, and YouTube inputs."
        AppGuide        = "VIDEO_MANGLER.txt"
    }
    [PSCustomObject]@{
        Key             = "Audio"
        ScriptFile      = "Audio Mangler.ps1"
        PackageExeName  = "Audio Mangler.exe"
        BinExeName      = "Audio-Mangler.exe"
        ReleaseZipName  = "Audio-Mangler-v{0}.zip" -f $appVersion
        ReleaseFolder   = "Audio-Mangler-v{0}" -f $appVersion
        IconFile        = "assets\Audio Mangler.ico"
        ProductName     = "Audio Mangler"
        Description     = "Builds transcript-first review packages from local audio, direct URLs, pages, and YouTube inputs."
        AppGuide        = "AUDIO_MANGLER.txt"
    }
)

$selectedApps = if ($App -eq "All") {
    $appConfigs
}
else {
    @($appConfigs | Where-Object { $_.Key -eq $App })
}

if ($selectedApps.Count -eq 0) {
    throw "No app configuration matched: $App"
}

New-Item -ItemType Directory -Path $distFolder -Force | Out-Null
New-Item -ItemType Directory -Path $binRoot -Force | Out-Null
New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null

Import-Module $modulePath -Force

$currentReleaseAssetNames = @(
    $appConfigs | ForEach-Object { $_.ReleaseZipName }
)
$archiveRunRoot = Join-Path $releaseArchiveRoot ("cleanup-{0}-{1}" -f (Get-Date -Format "yyyyMMdd-HHmmss"), ([guid]::NewGuid().ToString("N").Substring(0, 8)))
$archivedReleaseItems = New-Object System.Collections.Generic.List[string]

foreach ($releaseItem in @(Get-ChildItem -LiteralPath $releaseRoot -Force -ErrorAction SilentlyContinue)) {
    if (-not $releaseItem.PSIsContainer -and $currentReleaseAssetNames -contains $releaseItem.Name) {
        continue
    }

    if (Move-ItemToArchive -Path $releaseItem.FullName -ArchiveRoot $archiveRunRoot) {
        $archivedReleaseItems.Add($releaseItem.Name) | Out-Null
    }
}

if ($archivedReleaseItems.Count -gt 0) {
    Write-Host ("Archived legacy release artifacts to: {0}" -f $archiveRunRoot) -ForegroundColor Yellow
    foreach ($archivedItem in $archivedReleaseItems) {
        Write-Host (" - {0}" -f $archivedItem) -ForegroundColor DarkYellow
    }
}

foreach ($appConfig in $selectedApps) {
    $inputFile = Join-Path $repoRoot $appConfig.ScriptFile
    $outputFile = Join-Path $binRoot $appConfig.BinExeName
    $iconFile = Join-Path $repoRoot $appConfig.IconFile
    $stagingFolder = Join-Path $stagingRoot $appConfig.ReleaseFolder
    $releaseZip = Join-Path $releaseRoot $appConfig.ReleaseZipName
    $appFolder = Join-Path $stagingFolder "app"
    $docsFolder = Join-Path $stagingFolder "docs"

    $appGuideSource = Join-Path $guidesRoot $appConfig.AppGuide
    $readmeTextSource = Join-Path $guidesRoot "README.txt"

    foreach ($requiredPath in @($inputFile, $iconFile, $appGuideSource, $readmeTextSource, (Join-Path $repoRoot "THIRD_PARTY_NOTICES.txt"), (Join-Path $repoRoot "LICENSE"), $pyprojectFile, (Join-Path $pythonCoreSourceRoot "media_manglers"), $glossariesSourceRoot)) {
        if (-not (Test-Path -LiteralPath $requiredPath)) {
            throw "Required file not found: $requiredPath"
        }
    }

    if (Test-Path -LiteralPath $outputFile) {
        Remove-Item -LiteralPath $outputFile -Force
    }

    Invoke-ps2exe `
        -inputFile $inputFile `
        -outputFile $outputFile `
        -iconFile $iconFile `
        -title $appConfig.ProductName `
        -product $appConfig.ProductName `
        -description $appConfig.Description `
        -company "Media Manglers" `
        -copyright "Copyright (c) 2026 Media Manglers Contributors" `
        -version $appVersion

    Remove-PathIfPresent -Path $stagingFolder
    Remove-PathIfPresent -Path $releaseZip

    try {
        Ensure-Directory $appFolder
        Ensure-Directory $docsFolder
        Ensure-Directory $releaseRoot

        Copy-PythonCoreSidecar -PythonCoreSourceRoot $pythonCoreSourceRoot -PyprojectFile $pyprojectFile -DestinationRoot $binRoot
        Copy-GlossarySidecar -GlossariesSourceRoot $glossariesSourceRoot -DestinationRoot $binRoot
        Copy-Item -LiteralPath $outputFile -Destination (Join-Path $appFolder $appConfig.PackageExeName) -Force
        Copy-PythonCoreSidecar -PythonCoreSourceRoot $pythonCoreSourceRoot -PyprojectFile $pyprojectFile -DestinationRoot $appFolder
        Copy-GlossarySidecar -GlossariesSourceRoot $glossariesSourceRoot -DestinationRoot $appFolder
        Copy-Item -LiteralPath $readmeTextSource -Destination (Join-Path $docsFolder "README.txt") -Force
        Copy-Item -LiteralPath $appGuideSource -Destination (Join-Path $docsFolder $appConfig.AppGuide) -Force
        Copy-Item -LiteralPath $releaseNotes -Destination (Join-Path $docsFolder ([System.IO.Path]::GetFileName($releaseNotes))) -Force
        Copy-Item -LiteralPath (Join-Path $repoRoot "THIRD_PARTY_NOTICES.txt") -Destination (Join-Path $docsFolder "THIRD_PARTY_NOTICES.txt") -Force
        Copy-Item -LiteralPath (Join-Path $repoRoot "LICENSE") -Destination (Join-Path $docsFolder "LICENSE.txt") -Force
        Copy-Item -LiteralPath $versionFile -Destination (Join-Path $docsFolder "VERSION.txt") -Force

        Compress-Archive -LiteralPath $stagingFolder -DestinationPath $releaseZip -CompressionLevel Optimal
    }
    finally {
        if (-not $KeepPackageStaging) {
            Remove-PathIfPresent -Path $stagingFolder
        }
    }

    Write-Host ("Built {0}: {1}" -f $appConfig.ProductName, $outputFile) -ForegroundColor Green
    Write-Host ("Loose exe:   {0}" -f $outputFile) -ForegroundColor Green
    Write-Host ("Release zip: {0}" -f $releaseZip) -ForegroundColor Green
    Write-Host "Runtime sidecars: python-core and glossaries were refreshed in dist\\bin and the release zip app folder" -ForegroundColor Green
    if ($KeepPackageStaging) {
        Write-Host ("Package staging kept: {0}" -f $stagingFolder) -ForegroundColor Yellow
    }
}

if (-not $KeepPackageStaging) {
    Remove-DirectoryIfEmpty -Path $stagingRoot
}
