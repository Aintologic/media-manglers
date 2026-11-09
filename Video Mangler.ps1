param(
    [Alias("InputUrl")]
    [string]$InputPath,
    [string]$InputFolder = "",
    [string]$OutputFolder = "",
    [string]$FFmpegPath = "",
    [string]$FFprobePath = "",
    [string]$PythonExe = "py",
    [string]$YtDlpPath = "yt-dlp",
    [string]$WhisperModel = "base.en",
    [ValidateSet("Auto", "CPU", "GPU")]
    [string]$WhisperDevice = "Auto",
    [string]$Language = "",
    [ValidateSet("Auto", "Sparse", "Continuous")]
    [string]$NarrationSpeechMode = "Auto",
    [string]$TranslateTo = "",
    [ValidateSet("Local", "AI", "Hybrid")]
    [string]$ProcessingMode = "",
    [ValidateSet("Auto", "OpenAI", "Local")]
    [string]$TranslationProvider = "",
    [string]$OpenAiModel = "gpt-5-mini",
    [ValidateSet("Private", "Public")]
    [string]$OpenAiProject = "Private",
    [string]$ProtectedTermsProfile = "",
    [double]$FrameIntervalSeconds = [double]::NaN,
    [int]$HeartbeatSeconds = 10,
    [int]$WhisperTimeoutSeconds = 0,
    [int]$PromptTimeoutSeconds = 60,
    [switch]$CopyRawVideo,
    [switch]$IncludeComments,
    [Alias("CreateChatGptZip")]
    [switch]$CreateAiReviewZip,
    [switch]$KeepTempFiles,
    [switch]$OpenOutputInExplorer,
    [switch]$NoPrompt,
    [switch]$ApproveExpandedRun,
    [switch]$SkipEstimate,
    [switch]$TranscriptOnly,
    [switch]$CodexEvidencePackage,
    [switch]$IncludeCodexEvidencePackage,
    [switch]$SkipCodexEvidencePackage,
    [Alias("ReviewMediaInbox")]
    [switch]$ReviewNewVideos,
    [ValidateSet("Scan", "Process", "Prepare", "TargetedEvidence", "ImportResults", "PreviewFinalization", "Finalize")]
    [string]$ReviewInboxAction = "Scan",
    [ValidateSet("next_3", "up_to_n", "all_pending")]
    [string]$ReviewInboxWorkload = "next_3",
    [int]$ReviewInboxNewSourceLimit = 0,
    [string]$ReviewInboxExactSourcePathsJson = "",
    [string]$ReviewInboxContinuation = "",
    [string]$ReviewInboxDecisionJson = "",
    [string]$ReviewInboxResumeBatchId = "",
    [string]$ReviewPreliminarySubmissionSha256 = "",
    [string]$ReviewResultsPath = "",
    [string]$ReviewFinalizationPlanPath = "",
    [string]$ReviewFinalizationPlanSha256 = "",
    [switch]$ReviewFinalizationConfirmed,
    [string[]]$ReviewSourceFolders = @(),
    [string]$ReviewEvidenceRoot = "",
    [string]$ReviewLocalWorkRoot = "",
    [string]$ReviewLedgerPath = "",
    # 224 (Wave B2b): the Inbox folder; its records are in the Workbench library.
    [string]$ReviewInboxFolder = "",
    [ValidateSet("", "Fast", "Full")]
    [string]$ReviewDedupeMode = "",
    [ValidateSet("", "Oldest", "Newest")]
    [string]$ReviewInboxOrder = "",
    [int]$ReviewInboxMaxFiles = 0,
    [int]$ReviewInboxMaxDurationMinutes = 0,
    [int]$ReviewInboxConcurrency = 0,
    [int]$ReviewInboxPendingBatchLimit = 0,
    [switch]$ReviewFullScanAcknowledged,
    [string]$ReviewAudioConfirmationsPath = "",
    [string]$ReviewStopAfterCurrentFilePath = "",
    [switch]$ReviewNoRecurse,
    [switch]$ArchiveCatalog,
    [switch]$ArchiveCatalogSearch,
    [string[]]$ArchiveSearchTerms = @(),
    [switch]$TranscriptOnlyRecurse,
    [switch]$OverwriteTranscripts,
    [switch]$SkipTranscriptOnlyAudio,
    [string[]]$TranscriptSearchTerms = @(),
    [string]$ArchiveSkipMarker = "_NO_GLACIER_BACKUP",
    [ValidateSet("Fast", "Full", "Off")]
    [string]$ArchiveHashMode = "Fast",
    [ValidateSet("Auto", "Off")]
    [string]$ArchiveThumbnailMode = "Auto",
    [int]$ArchiveMaxThumbnailsPerVideo = 12,
    [string]$ArchiveS3Bucket = "",
    [string]$ArchiveS3Prefix = "",
    [string]$ArchiveCatalogPath = "",
    [string]$ArchiveNotesCsv = "",
    [switch]$ArchiveExportNotesTemplate,
    [double]$PreContextSeconds = 120,
    [double]$PostContextSeconds = 240,
    [double]$NarrationContextPreSeconds = 120,
    [double]$NarrationContextPostSeconds = 600,
    [double]$NarrationPauseThresholdSeconds = 30,
    [ValidateSet("On", "Off")]
    [string]$NarrationStopAtNextTicketBoundary = "On",
    [ValidateSet("On", "Off")]
    [string]$FragmentedNarrationMode = "On",
    [string[]]$EvidenceFrameOffsets = @("-60", "-30", "0", "30", "90", "120"),
    [int]$EvidenceAudioStreamIndex = 0,
    [string]$EvidenceAudioStreamSelectionsJson = "",
    # 196: the per-track setting "Auto / Narration / Never narration" for recordings whose tracks
    # have no names, as "2=narration,3=never" (track number = role; tracks left out are Auto).
    [string]$EvidenceTrackRoles = "",
    [double]$EvidenceFrameCadenceSeconds = 10,
    [int]$EvidenceMaxFramesPerCandidate = 60,
    [int]$EvidenceMaxItems = 50,
    [string[]]$EvidenceRenderCandidateIds = @(),
    [string[]]$EvidenceRenderOutcomeIds = @(),
    [ValidateSet("Transcription", "Consolidation", "Package")]
    [string]$EvidenceStopAfter = "Package",
    [ValidateSet("Compact", "Dense")]
    [string]$EvidenceRenderDensity = "Compact",
    [string]$EvidenceResumeRoot = "",
    [ValidateSet("Local", "PortableZip", "Both")]
    [string]$EvidenceHandoffMode = "Local",
    [int]$EvidencePortableZipMaxMb = 100,
    [ValidateSet("Auto", "On", "Off")]
    [string]$EvidencePanelCrops = "Auto",
    [ValidateSet("Auto", "On", "Off")]
    [string]$FullReviewPanelCrops = "Auto",
    [double]$FullReviewPanelCropCadenceSeconds = 5,
    [ValidateSet("Auto", "Off", "IndexOnly", "Selected")]
    [Alias("ChatGptZipPanelCropMode")]
    [string]$AiReviewZipPanelCropMode = "Auto",
    [ValidateSet("Auto", "All", "Prompt", "Mixed", "Track")]
    [string]$TranscriptAudioMode = "Auto",
    [string]$TranscriptAudioStream = "",
    [int]$TranscriptAudioTrackOrdinal = 0,
    [int]$PreferredTranscriptAudioTrackOrdinal = 0,
    [switch]$AudioTrackAudit,
    [string]$EvidenceTargetRepo = "",
    [string]$EvidenceRepoMapPath = "",
    [ValidateSet("auto", "target-only", "off")]
    [string]$EvidenceRepoHintMode = "auto",
    [string[]]$EvidenceCustomMarkers = @(),
    [string[]]$EvidenceCustomDomainTerms = @(),
    [string]$EvidenceTranscriptionGlossaryPath = "",
    [string[]]$EvidenceTranscriptionGlossaryEntries = @(),
    [switch]$EvidenceAudioStreamSelectionConfirmed,
    [switch]$EvidencePreserveSupportingAudio,
    [string]$EvidencePanelRoleMapPath = "",
    [string]$EvidenceTargetProject = "",
    [string]$EvidenceApplicationVersion = "",
    [string]$EvidenceProfileSetupName = "",
    [string]$EvidenceDashboardRevision = "",
    [string]$EvidenceTestConditions = "",
    [string]$EvidenceConfigurationNotes = "",
    [switch]$WhisperHealthCheck,
    [Alias("VerboseMode")]
    [switch]$DebugMode,
    [Alias("ShowVersion")]
    [switch]$Version,
    [Alias("ChatGptZipMaxMb")]
    [int]$AiReviewZipMaxMb = 500,
    # 114/115: a small JSON file the Workbench rewrites to skip recordings
    # or pause the run ({"pause": true, "skip": ["D:\\...\\file.mkv"]}).
    [string]$RunControlPath = "",
    # 115: run this script and every tool it starts below normal priority,
    # so games and other foreground work keep the PC.
    [switch]$LowPriority
)

$ErrorActionPreference = "Stop"
$script:CurrentLogFile = $null
$script:MMRunControlPath = $RunControlPath
$script:MMRunControlCache = $null
$script:MMRunControlReadAt = [datetime]::MinValue
$script:MMCurrentSourcePath = ""
$script:MMSkipRequested = $false
$script:MMLastResumeAt = $null
$script:MMSkipMessagePrefix = "MM_SKIP_REQUESTED"
if ($LowPriority) {
    try {
        (Get-Process -Id $PID).PriorityClass = [System.Diagnostics.ProcessPriorityClass]::BelowNormal
    }
    catch {
        # Priority is a courtesy; never fail a run over it.
    }
}
$script:AppName = "Video Mangler"
$script:FallbackAppVersion = "0.11.0"
$script:LocalAccuracyWhisperModel = "large"
$script:HybridAccuracyWhisperModel = "medium"
$script:HybridAccuracyGlossaryRelativePath = "glossaries\de-en-sim-racing.json"
$script:HybridAccuracyTranslationDefaultModel = "gpt-4o-mini-2024-07-18"
$script:InteractiveLocalDefaultWhisperModel = "medium"
$script:LocalCpuLongWhisperWarningThresholdSeconds = 900
$script:LocalWhisperLongRunPromptThresholdSeconds = 2700
$script:ExpandedRunConfirmationItemThreshold = 5
$script:OpenAiPrivateTranslationDefaultModel = "gpt-5-mini"
$script:OpenAiPublicTranslationDefaultModel = "gpt-4o-mini-2024-07-18"
$script:OpenAiTranscriptionModel = "whisper-1"
$script:DefaultFullReviewEvidenceTargetRepo = ""
$script:OpenAiPrivateTranslationApprovedModels = @(
    "gpt-5-mini",
    "gpt-5-mini-2025-08-07",
    "gpt-4.1-mini-2025-04-14",
    "gpt-4o-mini-2024-07-18"
)
$script:OpenAiPublicTranslationApprovedModels = @(
    "gpt-4o-mini-2024-07-18",
    "gpt-4.1-mini-2025-04-14"
)
$script:OpenAiPrivateTranscriptionApprovedModels = @(
    "whisper-1"
)
$script:OpenAiModelDiscoveryCache = @{}
$script:SessionOpenAiApiKey = $null
$script:OpenAiTestModeLogged = $false
$script:ResolvedAppBaseDirectory = $null
$script:MediaManglersPythonCliInfo = $null
$script:WhisperCalibrationCache = @{}
$script:PythonInterpreterResolutionNote = $null
$script:DebugModeEnabled = $DebugMode.IsPresent
$script:SessionEstimatedOpenAiTextCostUsd = 0.0
$script:PromptTimeoutSeconds = $PromptTimeoutSeconds

trap {
    $message = if ($_.Exception -and -not [string]::IsNullOrWhiteSpace($_.Exception.Message)) {
        $_.Exception.Message
    }
    else {
        $_.ToString()
    }

    if (-not [string]::IsNullOrWhiteSpace($script:CurrentLogFile)) {
        try {
            Add-Content -LiteralPath $script:CurrentLogFile -Value "----- UNHANDLED FAILURE -----"
            if (-not [string]::IsNullOrWhiteSpace($message)) {
                Add-Content -LiteralPath $script:CurrentLogFile -Value $message
            }
            if ($_.ScriptStackTrace) {
                Add-Content -LiteralPath $script:CurrentLogFile -Value $_.ScriptStackTrace
            }
        }
        catch {
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($message)) {
        Write-Host ""
        Write-Host $message -ForegroundColor Red
    }

    exit 1
}

if ($PromptTimeoutSeconds -lt 0) {
    throw "PromptTimeoutSeconds must be zero or greater. Use 0 to disable timed defaults."
}

function Get-AppVersion {
    if ($script:ResolvedAppVersion) {
        return $script:ResolvedAppVersion
    }

    $candidates = New-Object System.Collections.Generic.List[string]

    if ($PSScriptRoot) {
        $candidates.Add((Join-Path $PSScriptRoot "VERSION"))
    }

    if ($PSScriptRoot) {
        $parentRoot = Split-Path -Path $PSScriptRoot -Parent
        if (-not [string]::IsNullOrWhiteSpace($parentRoot)) {
            $candidates.Add((Join-Path $parentRoot "VERSION"))
        }
    }

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (Test-Path -LiteralPath $candidate) {
            $value = (Get-Content -LiteralPath $candidate | Select-Object -First 1).Trim()
            if (-not [string]::IsNullOrWhiteSpace($value)) {
                $script:ResolvedAppVersion = $value
                return $script:ResolvedAppVersion
            }
        }
    }

    try {
        $processPath = [System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
        if (-not [string]::IsNullOrWhiteSpace($processPath)) {
            $fileVersion = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($processPath).ProductVersion
            if (-not [string]::IsNullOrWhiteSpace($fileVersion)) {
                $script:ResolvedAppVersion = $fileVersion
                return $script:ResolvedAppVersion
            }
        }
    }
    catch {
    }

    $script:ResolvedAppVersion = $script:FallbackAppVersion
    return $script:ResolvedAppVersion
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

function Ensure-Directory {
    param([string]$Path)

    if (-not [string]::IsNullOrWhiteSpace($Path)) {
        if (-not (Test-Path -LiteralPath $Path)) {
            New-Item -ItemType Directory -Path $Path -Force | Out-Null
        }
    }
}

function Get-MediaManglersConfigPath {
    # 224 (Wave B2a): the settings folder the Workbench was given comes first, as for the rest of the app, so
    # a test Workbench never reads the real profile's config. Only tests and test launchers set it.
    $appDataRoot = [Environment]::GetEnvironmentVariable("MEDIA_MANGLERS_WORKBENCH_APPDATA")
    if ([string]::IsNullOrWhiteSpace($appDataRoot)) {
        $appDataRoot = $env:APPDATA
    }
    if ([string]::IsNullOrWhiteSpace($appDataRoot)) {
        $appDataRoot = Join-Path $env:USERPROFILE "AppData\Roaming"
    }

    return (Join-Path (Join-Path $appDataRoot "MediaManglers") "config.json")
}

function New-MediaManglersDefaultConfig {
    return [ordered]@{
        _comment = "Local per-user config. Keep private paths, repo targets, project names, and detector terms here; do not commit this file."
        reviewMediaInbox = [ordered]@{
            sourceFolders = @()
            evidenceRoot = ""
            localWorkRoot = ""
            ledgerPath = ""
            inboxFolder = ""
            dedupeMode = "Fast"
            recurse = $true
            order = "Oldest"
            maxFiles = 3
            maxDurationMinutes = 240
            concurrency = 1
            pendingBatchLimit = 1
        }
        evidence = [ordered]@{
            targetRepo = ""
            repoMapPath = ""
            customMarkers = @()
            customDomainTerms = @()
        }
    }
}

function Get-ObjectPropertyValue {
    param(
        [object]$Object,
        [string]$Name
    )

    if ($null -eq $Object) {
        return $null
    }

    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $null
    }

    return $property.Value
}

function Get-ConfigArrayValue {
    param([object]$Value)

    if ($null -eq $Value) {
        return @()
    }

    if ($Value -is [System.Array]) {
        return @($Value)
    }

    return @($Value)
}

function Get-ConfigStringArrayValue {
    param([object]$Value)

    return @(
        Get-ConfigArrayValue -Value $Value |
            ForEach-Object { [string]$_ } |
            ForEach-Object { $_.Trim() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
}

function Get-MediaManglersUserConfig {
    $configPath = Get-MediaManglersConfigPath
    $created = $false
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        Ensure-Directory (Split-Path -Path $configPath -Parent)
        $json = (New-MediaManglersDefaultConfig | ConvertTo-Json -Depth 8)
        Set-Content -LiteralPath $configPath -Value $json -Encoding UTF8
        $created = $true
    }

    try {
        $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw ("Media Manglers config could not be read as JSON: {0}. {1}" -f $configPath, $_.Exception.Message)
    }

    return [PSCustomObject]@{
        Path = $configPath
        Created = $created
        Config = $config
    }
}

function Resolve-MediaManglersEvidenceSettings {
    param(
        [psobject]$ConfigResult,
        [string]$CliTargetRepo,
        [string]$CliRepoMapPath,
        [array]$CliCustomMarkers = @(),
        [array]$CliCustomDomainTerms = @(),
        [bool]$TargetRepoWasExplicit,
        [bool]$RepoMapPathWasExplicit,
        [bool]$CustomMarkersWereExplicit,
        [bool]$CustomDomainTermsWereExplicit
    )

    $config = if ($ConfigResult) { $ConfigResult.Config } else { $null }
    $evidenceConfig = Get-ObjectPropertyValue -Object $config -Name "evidence"
    $targetRepo = [string]$CliTargetRepo
    $repoMapPath = [string]$CliRepoMapPath
    $customMarkers = @(Get-ConfigArrayValue -Value $CliCustomMarkers)
    $customDomainTerms = @(Get-ConfigArrayValue -Value $CliCustomDomainTerms)

    if (-not $TargetRepoWasExplicit -and [string]::IsNullOrWhiteSpace($targetRepo)) {
        $targetRepo = [string](Get-ObjectPropertyValue -Object $evidenceConfig -Name "targetRepo")
    }
    if (-not $RepoMapPathWasExplicit -and [string]::IsNullOrWhiteSpace($repoMapPath)) {
        $repoMapPath = [string](Get-ObjectPropertyValue -Object $evidenceConfig -Name "repoMapPath")
    }
    if (-not $CustomMarkersWereExplicit) {
        $customMarkers = @(Get-ConfigArrayValue -Value (Get-ObjectPropertyValue -Object $evidenceConfig -Name "customMarkers"))
    }
    if (-not $CustomDomainTermsWereExplicit) {
        $customDomainTerms = @(Get-ConfigArrayValue -Value (Get-ObjectPropertyValue -Object $evidenceConfig -Name "customDomainTerms"))
    }

    return [PSCustomObject]@{
        TargetRepo = $targetRepo
        RepoMapPath = $repoMapPath
        CustomMarkers = @($customMarkers)
        CustomDomainTerms = @($customDomainTerms)
        ConfigPath = $(if ($ConfigResult) { [string]$ConfigResult.Path } else { "" })
        CreatedConfig = $(if ($ConfigResult) { [bool]$ConfigResult.Created } else { $false })
    }
}

function ConvertTo-ConfigBool {
    param(
        [object]$Value,
        [bool]$DefaultValue
    )

    if ($null -eq $Value) {
        return $DefaultValue
    }
    if ($Value -is [bool]) {
        return [bool]$Value
    }
    $text = ([string]$Value).Trim()
    if ($text -match '^(?i)(true|1|yes|y)$') {
        return $true
    }
    if ($text -match '^(?i)(false|0|no|n)$') {
        return $false
    }
    return $DefaultValue
}

function Resolve-MediaManglersReviewSettings {
    param(
        [psobject]$ConfigResult,
        [string[]]$CliSourceFolders = @(),
        [string]$CliEvidenceRoot = "",
        [string]$CliLocalWorkRoot = "",
        [string]$CliLedgerPath = "",
        [string]$CliInboxFolder = "",
        [string]$CliDedupeMode = "",
        [string]$CliOrder = "",
        [int]$CliMaxFiles = 0,
        [int]$CliMaxDurationMinutes = 0,
        [int]$CliConcurrency = 0,
        [int]$CliPendingBatchLimit = 0,
        [bool]$NoRecurse,
        [bool]$SourceFoldersWereExplicit,
        [bool]$EvidenceRootWasExplicit,
        [bool]$LocalWorkRootWasExplicit,
        [bool]$LedgerPathWasExplicit,
        [bool]$DedupeModeWasExplicit,
        [bool]$OrderWasExplicit,
        [bool]$MaxFilesWasExplicit,
        [bool]$MaxDurationWasExplicit,
        [bool]$ConcurrencyWasExplicit,
        [bool]$PendingBatchLimitWasExplicit,
        [string]$OutputFolder
    )

    $configObject = $(if ($ConfigResult) { $ConfigResult.Config } else { $null })
    $reviewConfig = Get-ObjectPropertyValue -Object $configObject -Name "reviewMediaInbox"
    $configSection = "reviewMediaInbox"
    if ($null -eq $reviewConfig) {
        $reviewConfig = Get-ObjectPropertyValue -Object $configObject -Name "reviewNewVideos"
        $configSection = $(if ($null -eq $reviewConfig) { "defaults" } else { "reviewNewVideos" })
    }
    $sourceFolders = if ($SourceFoldersWereExplicit -and @($CliSourceFolders).Count -gt 0) {
        Get-ConfigStringArrayValue -Value $CliSourceFolders
    }
    else {
        Get-ConfigStringArrayValue -Value (Get-ObjectPropertyValue -Object $reviewConfig -Name "sourceFolders")
    }

    $evidenceRoot = [string]$CliEvidenceRoot
    if (-not $EvidenceRootWasExplicit -and [string]::IsNullOrWhiteSpace($evidenceRoot)) {
        $evidenceRoot = [string](Get-ObjectPropertyValue -Object $reviewConfig -Name "evidenceRoot")
    }
    if ([string]::IsNullOrWhiteSpace($evidenceRoot)) {
        $evidenceRoot = Join-Path $OutputFolder "review-new-videos"
    }
    $evidenceRoot = Normalize-UserPath -Path $evidenceRoot

    $localWorkRoot = [string]$CliLocalWorkRoot
    if (-not $LocalWorkRootWasExplicit -and [string]::IsNullOrWhiteSpace($localWorkRoot)) {
        $localWorkRoot = [string](Get-ObjectPropertyValue -Object $reviewConfig -Name "localWorkRoot")
    }
    if ([string]::IsNullOrWhiteSpace($localWorkRoot)) {
        $localWorkRoot = Join-Path ([System.IO.Path]::GetTempPath()) "MediaManglers\ReviewNewVideos"
    }
    $localWorkRoot = Normalize-UserPath -Path $localWorkRoot

    # 224 (Wave B2b): the Inbox folder says where the Inbox is (its records are in the library); the ledger's name in
    # it, a note since the move, is what the Inbox's plans and journals carry. -ReviewLedgerPath still works and means
    # "the folder this file is in", so an old command line finds the same folder.
    $inboxFolder = [string]$CliInboxFolder
    if ([string]::IsNullOrWhiteSpace($inboxFolder) -and -not $LedgerPathWasExplicit -and [string]::IsNullOrWhiteSpace([string]$CliLedgerPath)) {
        $inboxFolder = [string](Get-ObjectPropertyValue -Object $reviewConfig -Name "inboxFolder")
    }
    $ledgerPath = [string]$CliLedgerPath
    if (-not [string]::IsNullOrWhiteSpace($inboxFolder)) {
        $ledgerPath = Join-Path $inboxFolder "review-ledger.sqlite"
    }
    if (-not $LedgerPathWasExplicit -and [string]::IsNullOrWhiteSpace($ledgerPath)) {
        $ledgerPath = [string](Get-ObjectPropertyValue -Object $reviewConfig -Name "ledgerPath")
    }
    if ([string]::IsNullOrWhiteSpace($ledgerPath)) {
        $ledgerPath = Join-Path (Join-Path $evidenceRoot "review-inbox") "review-ledger.sqlite"
    }
    $ledgerPath = Normalize-UserPath -Path $ledgerPath

    $dedupeMode = [string]$CliDedupeMode
    if (-not $DedupeModeWasExplicit -and [string]::IsNullOrWhiteSpace($dedupeMode)) {
        $dedupeMode = [string](Get-ObjectPropertyValue -Object $reviewConfig -Name "dedupeMode")
    }
    if ([string]::IsNullOrWhiteSpace($dedupeMode)) {
        $dedupeMode = "Fast"
    }
    $dedupeMode = (Get-Culture).TextInfo.ToTitleCase($dedupeMode.Trim().ToLowerInvariant())
    if ($dedupeMode -notin @("Fast", "Full")) {
        throw "ReviewDedupeMode must be Fast or Full."
    }

    $configRecurse = ConvertTo-ConfigBool -Value (Get-ObjectPropertyValue -Object $reviewConfig -Name "recurse") -DefaultValue $true
    $recurse = if ($NoRecurse) { $false } else { $configRecurse }

    $order = if ($OrderWasExplicit -and -not [string]::IsNullOrWhiteSpace($CliOrder)) { $CliOrder } else { [string](Get-ObjectPropertyValue -Object $reviewConfig -Name "order") }
    if ([string]::IsNullOrWhiteSpace($order)) { $order = "Oldest" }
    $order = (Get-Culture).TextInfo.ToTitleCase($order.Trim().ToLowerInvariant())
    if ($order -notin @("Oldest", "Newest")) { throw "ReviewInboxOrder must be Oldest or Newest." }

    $maxFiles = if ($MaxFilesWasExplicit) { $CliMaxFiles } else { [int](Get-ObjectPropertyValue -Object $reviewConfig -Name "maxFiles") }
    if ($maxFiles -le 0) { $maxFiles = 3 }
    $maxDurationMinutes = if ($MaxDurationWasExplicit) { $CliMaxDurationMinutes } else { [int](Get-ObjectPropertyValue -Object $reviewConfig -Name "maxDurationMinutes") }
    if ($maxDurationMinutes -le 0) { $maxDurationMinutes = 240 }
    $concurrency = if ($ConcurrencyWasExplicit) { $CliConcurrency } else { [int](Get-ObjectPropertyValue -Object $reviewConfig -Name "concurrency") }
    if ($concurrency -le 0) { $concurrency = 1 }
    if ($concurrency -ne 1) { throw "Review Media Inbox concurrency is fixed at 1 in this foundational release." }
    $pendingBatchLimit = if ($PendingBatchLimitWasExplicit) { $CliPendingBatchLimit } else { [int](Get-ObjectPropertyValue -Object $reviewConfig -Name "pendingBatchLimit") }
    if ($pendingBatchLimit -le 0) { $pendingBatchLimit = 1 }

    return [PSCustomObject]@{
        SourceFolders = @($sourceFolders | ForEach-Object { Normalize-UserPath -Path $_ })
        EvidenceRoot = $evidenceRoot
        LocalWorkRoot = $localWorkRoot
        LedgerPath = $ledgerPath
        DedupeMode = $dedupeMode
        Recurse = [bool]$recurse
        Order = $order
        MaxFiles = [int]$maxFiles
        MaxDurationMinutes = [int]$maxDurationMinutes
        Concurrency = [int]$concurrency
        PendingBatchLimit = [int]$pendingBatchLimit
        ConfigSection = $configSection
        ConfigPath = $(if ($ConfigResult) { [string]$ConfigResult.Path } else { "" })
        CreatedConfig = $(if ($ConfigResult) { [bool]$ConfigResult.Created } else { $false })
    }
}

function Assert-EvidenceTargetRepo {
    param([string]$TargetRepo)

    if (-not [string]::IsNullOrWhiteSpace($TargetRepo) -and $TargetRepo -notmatch '^[^/\s]+/[^/\s]+$') {
        throw "EvidenceTargetRepo must use owner/repo format, for example example-org/example-project."
    }
}

function Resolve-StartupDirectory {
    param(
        [string]$Path,
        [ValidateSet("input","output")]
        [string]$FolderKind,
        [switch]$NoPrompt
    )

    $resolvedPath = Normalize-UserPath -Path $Path
    while ($true) {
        if ([string]::IsNullOrWhiteSpace($resolvedPath)) {
            throw ("Missing {0} folder path." -f $FolderKind)
        }

        if (Test-Path -LiteralPath $resolvedPath -PathType Container) {
            return $resolvedPath
        }

        if (Test-Path -LiteralPath $resolvedPath -PathType Leaf) {
            if ($NoPrompt) {
                throw ("Configured {0} folder path is a file, not a folder: {1}" -f $FolderKind, $resolvedPath)
            }

            Write-Host ""
            Write-Host ("Configured {0} folder path is a file, not a folder: {1}" -f $FolderKind, $resolvedPath) -ForegroundColor Yellow
            Write-Host "Choose a different folder or type Q to quit." -ForegroundColor Yellow
            $replacementPath = Read-Host ("Enter {0} folder path" -f $FolderKind)
            if (-not [string]::IsNullOrWhiteSpace($replacementPath) -and $replacementPath.Trim() -match '^(?i)(q|quit)$') {
                throw ("User canceled at {0} folder setup." -f $FolderKind)
            }
            if (-not [string]::IsNullOrWhiteSpace($replacementPath)) {
                $resolvedPath = Normalize-UserPath -Path $replacementPath
            }
            continue
        }

        if ($NoPrompt) {
            Write-Log ("Creating missing {0} folder for non-interactive run: {1}" -f $FolderKind, $resolvedPath)
            try {
                Ensure-Directory $resolvedPath
                return $resolvedPath
            }
            catch {
                throw ("Could not create folder: {0}" -f $_.Exception.Message)
            }
        }

        Write-Host ""
        Write-Host ("Missing {0} folder: {1}" -f $FolderKind, $resolvedPath) -ForegroundColor Yellow
        $createFolder = Read-TimedYesNoPrompt `
            -Prompt ("Create this folder now? (Y/n, auto-selects Y in {0}s):" -f $script:PromptTimeoutSeconds) `
            -DefaultYes:$true
        if ($createFolder) {
            try {
                Ensure-Directory $resolvedPath
                return $resolvedPath
            }
            catch {
                Write-Host ("Could not create folder: {0}" -f $_.Exception.Message) -ForegroundColor Yellow
                Write-Host "Choose a different folder or type Q to quit." -ForegroundColor Yellow
                $replacementPath = Read-Host ("Enter {0} folder path" -f $FolderKind)
                if (-not [string]::IsNullOrWhiteSpace($replacementPath) -and $replacementPath.Trim() -match '^(?i)(q|quit)$') {
                    throw ("User canceled at {0} folder setup." -f $FolderKind)
                }
                if (-not [string]::IsNullOrWhiteSpace($replacementPath)) {
                    $resolvedPath = Normalize-UserPath -Path $replacementPath
                }
                continue
            }
        }

        if (-not $createFolder) {
            Write-Host "Choose a different folder or type Q to quit." -ForegroundColor Yellow
            $replacementPath = Read-Host ("Enter {0} folder path" -f $FolderKind)
            if (-not [string]::IsNullOrWhiteSpace($replacementPath) -and $replacementPath.Trim() -match '^(?i)(q|quit)$') {
                throw ("User canceled at {0} folder setup." -f $FolderKind)
            }
            if (-not [string]::IsNullOrWhiteSpace($replacementPath)) {
                $resolvedPath = Normalize-UserPath -Path $replacementPath
            }
            continue
        }

    }
}

function Test-IsHttpUrl {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $false
    }

    $uri = $null
    if (-not [System.Uri]::TryCreate($Value, [System.UriKind]::Absolute, [ref]$uri)) {
        return $false
    }

    return $uri.Scheme -in @([System.Uri]::UriSchemeHttp, [System.Uri]::UriSchemeHttps)
}

function Get-HttpUrlsFromText {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return @()
    }

    return @(
        ([regex]::Matches($Value, 'https?://\S+')) |
            ForEach-Object { $_.Value.Trim().Trim(',', ';') } |
            Where-Object { Test-IsHttpUrl -Value $_ }
    )
}

function Resolve-RequestedInputSources {
    param([object]$RequestedInputValue)

    $remoteSources = New-Object System.Collections.Generic.List[string]
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    $localInputPath = ""

    foreach ($candidate in @($RequestedInputValue)) {
        if ($null -eq $candidate) {
            continue
        }
        $candidateText = [string]$candidate
        $detectedUrls = @(Get-HttpUrlsFromText -Value $candidateText)
        if ($detectedUrls.Count -gt 0) {
            foreach ($url in $detectedUrls) {
                if ($seen.Add($url)) {
                    [void]$remoteSources.Add($url)
                }
            }
            continue
        }
        if (-not [string]::IsNullOrWhiteSpace($candidateText)) {
            $localInputPath = $candidateText
        }
    }

    return [PSCustomObject]@{
        RemoteInputSources = @($remoteSources)
        InputPath = $localInputPath
    }
}

function Get-MediaManglersDefaultFolderBase {
    # 127: the user's own Videos folder as the operating system reports it (it follows a move to
    # OneDrive or another drive), never a temp folder. The environment override keeps automated tests
    # out of a real user's folders.
    $override = [Environment]::GetEnvironmentVariable("MEDIA_MANGLERS_VIDEOS_FOLDER")
    if (-not [string]::IsNullOrWhiteSpace($override)) {
        return [System.IO.Path]::Combine($override, "Media Mangler")
    }

    $root = [Environment]::GetFolderPath("MyVideos")
    if ([string]::IsNullOrWhiteSpace($root)) {
        $root = [System.IO.Path]::Combine([Environment]::GetFolderPath("UserProfile"), "Videos")
    }

    return [System.IO.Path]::Combine($root, "Media Mangler")
}

function Assert-FoldersAreNotTemporary {
    param(
        [string]$InputFolder,
        [string]$OutputFolder
    )

    # 127/211: results written into a temp folder can be cleared without warning. The rule lives in
    # one place, media_manglers.core.user_folders, which the Workbench uses too; the backend asks it.
    # Automated tests set MEDIA_MANGLERS_ALLOW_TEMP_OUTPUT=1 for their throw-away output.
    # 220: the same rule refuses the drive that holds the recordings, which the Workbench names in
    # MEDIA_MANGLERS_RECORDINGS_FOLDERS; that refusal holds even for the tests' throw-away output.
    if ([Environment]::GetEnvironmentVariable("MEDIA_MANGLERS_ALLOW_TEMP_OUTPUT") -eq "1" -and
        [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable("MEDIA_MANGLERS_RECORDINGS_FOLDERS"))) {
        return
    }
    $check = $null
    try {
        $check = Invoke-MediaManglersPythonCli -PythonCommand $PythonExe -Command "folder-check" -StepName "Output folder check" `
            -TimeoutSeconds 120 -Payload @{ input_folder = [string]$InputFolder; output_folder = [string]$OutputFolder }
    }
    catch {
        $check = $null
    }
    if ($null -eq $check -or $null -eq $check.Result -or -not [bool]$check.Result.ok) {
        Write-Log "The output folder could not be checked (the Python helper did not answer); the run goes on." "WARN"
        return
    }
    $data = $check.Result.data
    if (-not [string]::IsNullOrWhiteSpace([string]$data.input_warning)) {
        Write-Warning ([string]$data.input_warning)
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$data.output_problem)) {
        throw ("{0} Choose it with -OutputFolder." -f ([string]$data.output_problem).TrimEnd())
    }
}

function Resolve-DefaultInputOutputFolders {
    param(
        [string]$CurrentInputFolder,
        [string]$CurrentOutputFolder,
        [switch]$InputProvided,
        [switch]$OutputProvided,
        [switch]$NoPrompt
    )

    $defaultBase = Get-MediaManglersDefaultFolderBase
    $inputDefault = [System.IO.Path]::Combine($defaultBase, "_VIDEO_INPUT")
    $outputDefault = [System.IO.Path]::Combine($defaultBase, "_VIDEO_OUTPUT")

    if (-not $InputProvided -and -not $OutputProvided) {
        if ($NoPrompt -or (Test-Path -LiteralPath $inputDefault) -or (Test-Path -LiteralPath $outputDefault)) {
            return [PSCustomObject]@{ InputFolder = $inputDefault; OutputFolder = $outputDefault }
        }

        Write-Host ""
        Write-Host ("Media Mangler keeps its folders in your Videos folder: {0}" -f $defaultBase) -ForegroundColor Yellow
        Write-Host ("Recommended input folder:  {0}" -f $inputDefault) -ForegroundColor Cyan
        Write-Host ("Recommended output folder: {0}" -f $outputDefault) -ForegroundColor Cyan
        $baseChoice = Read-TimedDefaultPrompt `
            -Prompt ("Press Enter to use these folders, or type another base folder. Auto-selects in {0}s:" -f $script:PromptTimeoutSeconds) `
            -DefaultValue ""

        if ([string]::IsNullOrWhiteSpace($baseChoice)) {
            return [PSCustomObject]@{ InputFolder = $inputDefault; OutputFolder = $outputDefault }
        }

        $basePath = $baseChoice.Trim()
        return [PSCustomObject]@{
            InputFolder  = Join-Path $basePath "_VIDEO_INPUT"
            OutputFolder = Join-Path $basePath "_VIDEO_OUTPUT"
        }
    }

    $resolvedInput = $CurrentInputFolder
    $resolvedOutput = $CurrentOutputFolder

    if (-not $InputProvided) {
        if ($OutputProvided -and -not [string]::IsNullOrWhiteSpace($CurrentOutputFolder)) {
            $outputParent = Split-Path $CurrentOutputFolder -Parent
            if (-not [string]::IsNullOrWhiteSpace($outputParent)) {
                $resolvedInput = Join-Path $outputParent "_VIDEO_INPUT"
            }
        }
    }

    if (-not $OutputProvided) {
        if ($InputProvided -and -not [string]::IsNullOrWhiteSpace($CurrentInputFolder)) {
            $inputParent = Split-Path $CurrentInputFolder -Parent
            if (-not [string]::IsNullOrWhiteSpace($inputParent)) {
                $resolvedOutput = Join-Path $inputParent "_VIDEO_OUTPUT"
            }
        }
    }

    return [PSCustomObject]@{
        InputFolder  = $resolvedInput
        OutputFolder = $resolvedOutput
    }
}

function Get-YtDlpInstallCommands {
    param([string]$PythonCommand)

    return @(
        "winget install --id yt-dlp.yt-dlp -e",
        "$PythonCommand -m pip install -U yt-dlp"
    )
}

function Write-YtDlpInstallGuidance {
    param([string]$PythonCommand)

    Write-Host ""
    Write-Host "yt-dlp is required to download from YouTube or another supported video URL." -ForegroundColor Yellow
    Write-Host "Install it with one of these commands:" -ForegroundColor Yellow
    foreach ($command in (Get-YtDlpInstallCommands -PythonCommand $PythonCommand)) {
        Write-Host ("  {0}" -f $command) -ForegroundColor Yellow
    }
    Write-Host ""
}

function Get-PackagedRuntimeGuidance {
    return "Use the versioned release ZIP/package as the normal operator handoff. If you use the loose dist\\bin EXE, keep it beside the packaged python-core and glossaries folders."
}

function Get-ProtectedTermsProfileCatalog {
    return @{
        "sim-racing" = [PSCustomObject]@{
            Name         = "sim-racing"
            DisplayName  = "Sim-Racing"
            RelativePath = $script:HybridAccuracyGlossaryRelativePath
        }
    }
}

function Normalize-ProtectedTermsProfileName {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return ""
    }

    switch ($Value.Trim().ToLowerInvariant()) {
        "none" { return "" }
        "generic" { return "" }
        "off" { return "" }
        "default" { return "" }
        "simracing" { return "sim-racing" }
        "sim_racing" { return "sim-racing" }
        default { return $Value.Trim().ToLowerInvariant() }
    }
}

function Resolve-ProtectedTermsProfileSelection {
    param([string]$RequestedProfile)

    $normalizedProfile = Normalize-ProtectedTermsProfileName -Value $RequestedProfile
    if ([string]::IsNullOrWhiteSpace($normalizedProfile)) {
        return [PSCustomObject]@{
            Name       = ""
            DisplayName = "none (generic mode)"
            RelativePath = ""
            Path       = ""
            IsSelected = $false
        }
    }

    $catalog = Get-ProtectedTermsProfileCatalog
    if (-not $catalog.ContainsKey($normalizedProfile)) {
        $availableProfiles = @($catalog.Keys | Sort-Object)
        throw ("Unknown protected terms profile '{0}'. Available profiles: {1}. Use -ProtectedTermsProfile sim-racing, or leave it blank for generic mode." -f $RequestedProfile.Trim(), ($availableProfiles -join ", "))
    }

    $profile = $catalog[$normalizedProfile]
    $resolvedPath = ""
    foreach ($runtimeRoot in @(Get-RuntimeSearchRoots)) {
        $candidatePath = Join-Path $runtimeRoot $profile.RelativePath
        if (-not [string]::IsNullOrWhiteSpace($candidatePath) -and (Test-Path -LiteralPath $candidatePath)) {
            $resolvedPath = (Resolve-Path -LiteralPath $candidatePath).ProviderPath
            break
        }
    }

    return [PSCustomObject]@{
        Name        = $profile.Name
        DisplayName = $profile.DisplayName
        RelativePath = $profile.RelativePath
        Path        = $resolvedPath
        IsSelected  = $true
    }
}

function Get-ProtectedTermsProfileSummary {
    param([psobject]$Selection)

    if ($null -eq $Selection -or -not $Selection.IsSelected) {
        return "none (generic mode)"
    }

    return $Selection.DisplayName
}

function Assert-HybridRuntimePreflight {
    param([psobject]$ProtectedTermsProfileSelection)

    $missingComponents = New-Object System.Collections.Generic.List[string]
    $cliInfo = Get-MediaManglersPythonCliInfo
    if (-not $cliInfo.Enabled) {
        [void]$missingComponents.Add("the python-core helper sidecar")
    }

    if ($ProtectedTermsProfileSelection -and $ProtectedTermsProfileSelection.IsSelected -and [string]::IsNullOrWhiteSpace($ProtectedTermsProfileSelection.Path)) {
        [void]$missingComponents.Add(("the protected terms profile '{0}' ({1})" -f $ProtectedTermsProfileSelection.DisplayName, $ProtectedTermsProfileSelection.RelativePath))
    }

    if ($missingComponents.Count -gt 0) {
        throw ("Hybrid Accuracy preflight stopped before download or transcription because this copy is missing {0}. Use the versioned release ZIP/package as the normal operator handoff. If you intentionally run a loose dist\\bin EXE for local/dev use, keep the required sidecar folders beside the EXE." -f (($missingComponents | Select-Object -Unique) -join " and "))
    }

    return $cliInfo
}

function Get-RequestedOpenAiTranslationModelLabel {
    param(
        [string]$EffectiveMode,
        [string]$RequestedModel,
        [bool]$WasExplicitlySet = $false
    )

    if (-not [string]::IsNullOrWhiteSpace($RequestedModel)) {
        return $RequestedModel.Trim()
    }

    if ($EffectiveMode -eq "Hybrid" -and -not $WasExplicitlySet) {
        return ("auto ({0} default)" -f $script:HybridAccuracyTranslationDefaultModel)
    }

    return "auto"
}

function Get-OpenAiTextPricingPerMillionUsd {
    param([string]$Model)

    switch (Normalize-OpenAiModelId -ModelId $Model) {
        "gpt-4o-mini" { return [PSCustomObject]@{ Input = 0.15; Output = 0.60 } }
        "gpt-4o-mini-2024-07-18" { return [PSCustomObject]@{ Input = 0.15; Output = 0.60 } }
        "gpt-4.1-mini" { return [PSCustomObject]@{ Input = 0.40; Output = 1.60 } }
        "gpt-4.1-mini-2025-04-14" { return [PSCustomObject]@{ Input = 0.40; Output = 1.60 } }
        default { return $null }
    }
}

function Estimate-OpenAiTextCostUsd {
    param(
        [string]$Model,
        [int]$PromptTokens = 0,
        [int]$CompletionTokens = 0
    )

    $pricing = Get-OpenAiTextPricingPerMillionUsd -Model $Model
    if ($null -eq $pricing) {
        return $null
    }

    return ((($PromptTokens * [double]$pricing.Input) + ($CompletionTokens * [double]$pricing.Output)) / 1000000.0)
}

function Format-EstimatedUsd {
    param([object]$Value)

    if ($null -eq $Value -or [string]::IsNullOrWhiteSpace([string]$Value)) {
        return "n/a"
    }

    return ('$' + ([double]$Value).ToString("0.000000", [System.Globalization.CultureInfo]::InvariantCulture))
}

function Get-RoughOpenAiTextCostEstimate {
    param(
        [double]$TotalDurationSeconds,
        [string]$Model,
        [int]$ItemCount = 1
    )

    $pricing = Get-OpenAiTextPricingPerMillionUsd -Model $Model
    if ($null -eq $pricing -or $TotalDurationSeconds -le 0) {
        return $null
    }

    $approxWordCount = [math]::Max(1, [math]::Round($TotalDurationSeconds * 2.6))
    $promptTokens = [math]::Round(($approxWordCount * 1.4) + ([math]::Max(1, $ItemCount) * 350))
    $completionTokens = [math]::Round($approxWordCount * 1.15)
    $estimatedCostUsd = Estimate-OpenAiTextCostUsd -Model $Model -PromptTokens $promptTokens -CompletionTokens $completionTokens

    if ($null -eq $estimatedCostUsd) {
        return $null
    }

    return [PSCustomObject]@{
        PromptTokens      = [int]$promptTokens
        CompletionTokens  = [int]$completionTokens
        EstimatedCostUsd  = [double]$estimatedCostUsd
    }
}

function Write-OperatorNote {
    param(
        [string]$Message,
        [string]$Color = "Cyan",
        [ValidateSet("INFO","WARN")]
        [string]$Level = "INFO"
    )

    Write-Host $Message -ForegroundColor $Color
    Write-Log $Message $Level
}

function Get-RemoteInputScopeSummary {
    param(
        [string[]]$SourceUrls,
        [psobject]$YtDlpInvoker
    )

    $notes = New-Object System.Collections.Generic.List[string]
    $singleUrlCount = 0
    $playlistUrlCount = 0
    $approxResolvedItemCount = 0
    $knownDurationSeconds = 0.0

    foreach ($sourceUrl in @($SourceUrls)) {
        $sourceKind = Get-RemoteSourceKind -SourceUrl $sourceUrl
        if ($sourceKind -eq "playlist") {
            $playlistUrlCount += 1
            if ($YtDlpInvoker) {
                try {
                    $probe = Invoke-ExternalCapture `
                        -FilePath $YtDlpInvoker.FilePath `
                        -Arguments ($YtDlpInvoker.Arguments + @("--flat-playlist", "--dump-single-json", "--no-warnings", "--skip-download", $sourceUrl)) `
                        -StepName "yt-dlp playlist scope probe" `
                        -IgnoreExitCode `
                        -TimeoutSeconds 120

                    if ($probe.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($probe.StdOut)) {
                        $payload = $probe.StdOut | ConvertFrom-Json
                        $entries = @($payload.entries)
                        if ($entries.Count -gt 0) {
                            $approxResolvedItemCount += $entries.Count
                        }

                        foreach ($entry in $entries) {
                            $durationSeconds = 0.0
                            if ($null -ne $entry.duration -and [double]::TryParse([string]$entry.duration, [ref]$durationSeconds) -and $durationSeconds -gt 0) {
                                $knownDurationSeconds += $durationSeconds
                            }
                        }
                    }
                    else {
                        [void]$notes.Add(("Could not resolve playlist size before download: {0}" -f $sourceUrl))
                    }
                }
                catch {
                    [void]$notes.Add(("Could not resolve playlist scope before download: {0}" -f $_.Exception.Message))
                }
            }
            else {
                [void]$notes.Add("yt-dlp is not available, so playlist size could not be confirmed before download.")
            }

            continue
        }

        $singleUrlCount += 1
        $approxResolvedItemCount += 1
        if ($YtDlpInvoker) {
            try {
                $probe = Invoke-ExternalCapture `
                    -FilePath $YtDlpInvoker.FilePath `
                    -Arguments ($YtDlpInvoker.Arguments + @("-J", "--no-warnings", "--no-playlist", $sourceUrl)) `
                    -StepName "yt-dlp single-item scope probe" `
                    -IgnoreExitCode `
                    -TimeoutSeconds 120

                if ($probe.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($probe.StdOut)) {
                    $payload = $probe.StdOut | ConvertFrom-Json
                    $durationSeconds = 0.0
                    if ($null -ne $payload.duration -and [double]::TryParse([string]$payload.duration, [ref]$durationSeconds) -and $durationSeconds -gt 0) {
                        $knownDurationSeconds += $durationSeconds
                    }
                }
            }
            catch {
            }
        }
    }

    return [PSCustomObject]@{
        SingleUrlCount         = $singleUrlCount
        PlaylistUrlCount       = $playlistUrlCount
        ApproxResolvedItemCount = $approxResolvedItemCount
        KnownDurationSeconds   = $knownDurationSeconds
        RequiresConfirmation   = ($playlistUrlCount -gt 0 -or $approxResolvedItemCount -ge $script:ExpandedRunConfirmationItemThreshold)
        Notes                  = @($notes)
    }
}

function Confirm-ExpandedRunScope {
    param(
        [psobject]$ScopeSummary,
        [switch]$NoPrompt,
        [switch]$ApproveExpandedRun
    )

    if ($null -eq $ScopeSummary -or -not $ScopeSummary.RequiresConfirmation) {
        return
    }

    Write-Host ""
    Write-Host "Expanded run confirmation" -ForegroundColor Yellow
    Write-Host "------------------------" -ForegroundColor Yellow
    Write-Host ("Single URLs detected:            {0}" -f $ScopeSummary.SingleUrlCount) -ForegroundColor Yellow
    Write-Host ("Playlist URLs detected:          {0}" -f $ScopeSummary.PlaylistUrlCount) -ForegroundColor Yellow
    Write-Host ("Approximate resolved item count: {0}" -f $(if ($ScopeSummary.ApproxResolvedItemCount -gt 0) { $ScopeSummary.ApproxResolvedItemCount } else { "unknown before download" })) -ForegroundColor Yellow
    Write-Host ("Approximate source duration:     {0}" -f $(if ($ScopeSummary.KnownDurationSeconds -gt 0) { Format-DurationHuman -Seconds $ScopeSummary.KnownDurationSeconds } else { "unknown before download" })) -ForegroundColor Yellow
    if ($ScopeSummary.KnownDurationSeconds -gt 0) {
        Write-Host ("Estimated processing runtime:    at least {0} of source media, likely longer after download/transcription/translation" -f (Format-DurationHuman -Seconds $ScopeSummary.KnownDurationSeconds)) -ForegroundColor Yellow
    }
    else {
        Write-Host "Estimated processing runtime:    unknown before download" -ForegroundColor Yellow
    }
    foreach ($note in @($ScopeSummary.Notes)) {
        if (-not [string]::IsNullOrWhiteSpace($note)) {
            Write-Host ("Note: {0}" -f $note) -ForegroundColor DarkYellow
            Write-Log $note "WARN"
        }
    }

    if ($NoPrompt) {
        if (-not $ApproveExpandedRun) {
            throw "Preflight stopped before download because this remote input expands into a playlist or larger multi-item run. Review the scope interactively, or rerun with -ApproveExpandedRun after you intentionally confirm the expanded run."
        }

        Write-Log "Expanded run scope was explicitly approved with -ApproveExpandedRun."
        return
    }

    $continueExpandedRun = Read-TimedYesNoPrompt `
        -Prompt ("Continue with this expanded run? (y/N, auto-selects N in {0}s):" -f $script:PromptTimeoutSeconds) `
        -DefaultYes:$false
    if (-not $continueExpandedRun) {
        throw "Operator canceled expanded run during preflight."
    }
}

function Test-ConsoleDebugMode {
    return [bool]$script:DebugModeEnabled
}

function Test-WriteLogToConsole {
    param(
        [string]$Message,
        [string]$Level = "INFO"
    )

    if (Test-ConsoleDebugMode) {
        return $true
    }

    if ($Level -in @("ERROR", "FAIL", "PASS")) {
        return $true
    }

    $normalizedMessage = if ([string]::IsNullOrWhiteSpace($Message)) {
        ""
    }
    else {
        $Message.Trim()
    }

    foreach ($pattern in @(
            '^Command:',
            '^\[PY\]',
            '^Tracked Python .* failed\.',
            '^OpenAI .* model discovery',
            '^Whisper runtime probe:',
            '^Whisper runtime action:',
            '^Whisper runtime health:',
            '^OpenAI segment diagnostics:',
            '^Requested processing mode:',
            '^Effective processing mode request:',
            '^Resolved processing mode:',
            '^Requested translation provider:',
            '^Effective translation provider request:',
            '^Output folder root:',
            '^OpenAI failure details',
            '^OpenAI service message',
            '^OpenAI raw response body',
            '^Estimated total runtime:',
            '^Estimated finish time:',
            '^OpenAI transcription request:'
        )) {
        if ($normalizedMessage -match $pattern) {
            return $false
        }
    }

    return $true
}

function Add-LogContentWithRetry {
    param(
        [string]$Path,
        [object]$Value,
        [int]$MaxAttempts = 8
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $false
    }

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            Add-Content -LiteralPath $Path -Value $Value -ErrorAction Stop
            return $true
        }
        catch {
            if ($attempt -lt $MaxAttempts) {
                Start-Sleep -Milliseconds (75 * $attempt)
            }
        }
    }

    return $false
}

function Write-Log {
    param(
        [string]$Message,
        [ValidateSet("INFO","WARN","ERROR","PASS","FAIL")]
        [string]$Level = "INFO"
    )

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$timestamp] [$Level] $Message"
    $infoAccent = $null
    if ($Level -eq "INFO") {
        if ($Message -match '\[GPU->CPU\]') {
            $infoAccent = "Yellow"
        }
        elseif ($Message -match '\[GPU\]') {
            $infoAccent = "Cyan"
        }
        elseif ($Message -match '\[CPU\]') {
            $infoAccent = "DarkYellow"
        }
    }

    if (Test-WriteLogToConsole -Message $Message -Level $Level) {
        switch ($Level) {
            "ERROR" { Write-Host $line -ForegroundColor Red }
            "FAIL"  { Write-Host $line -ForegroundColor Red }
            "PASS"  { Write-Host $line -ForegroundColor Green }
            "WARN"  { Write-Host $line -ForegroundColor Yellow }
            default {
                if ($infoAccent) {
                    Write-Host $line -ForegroundColor $infoAccent
                }
                else {
                    Write-Host $line
                }
            }
        }
    }

    if ($script:CurrentLogFile) {
        $logWriteSucceeded = Add-LogContentWithRetry -Path $script:CurrentLogFile -Value $line

        if (-not $logWriteSucceeded) {
            Write-Host ("[$timestamp] [WARN] Could not write to log file after retries: {0}" -f $script:CurrentLogFile) -ForegroundColor Yellow
        }
    }
}

function Write-MMProgressV1 {
    param(
        [string]$Phase = "",
        [int]$PhaseIndex = 0,
        [int]$PhaseCount = 0,
        [string]$SourceId = "",
        [string]$SourceName = "",
        [string]$OutcomeId = "",
        [string]$ArtifactId = "",
        # 224 (Wave B2a, 272): 64-bit, so a count of bytes past 2 GB fits.
        [long]$Completed = 0,
        [long]$Total = 0,
        [int]$SourceCompleted = 0,
        [int]$SourceTotal = 0,
        [int]$SourceOrdinal = 0,
        [string]$SourceState = "",
        [bool]$SourceTerminal = $false,
        [int]$PreparedCount = 0,
        [int]$BlockedCount = 0,
        [int]$FailedCount = 0,
        [int]$OutcomeCompleted = 0,
        [int]$OutcomeTotal = 0,
        [int]$ArtifactCompleted = 0,
        [int]$ArtifactTotal = 0,
        [ValidateSet("indeterminate","stage","work_units")]
        [string]$ProgressKind = "stage",
        # 224 (Wave B2a, 272): what work_units count ("seconds" of a recording, "bytes"); empty for items.
        [string]$WorkUnit = "",
        [string]$Activity = "",
        [string]$LatestArtifactPath = "",
        [string]$ProviderStage = "",
        [string]$ProviderMessage = "",
        [string]$ProviderDevice = "",
        [string]$ProviderUpdatedAt = "",
        [ValidateSet("","succeeded","failed","cancelled")]
        [string]$TerminalState = "",
        [switch]$Heartbeat
    )

    if (-not $script:MMProgressRunId) {
        $script:MMProgressRunId = [guid]::NewGuid().ToString()
        $script:MMProgressStartedAt = [DateTime]::UtcNow
    }
    if (-not [string]::IsNullOrWhiteSpace($Phase)) {
        $script:MMProgressPhase = $Phase
    }
    if (-not $script:MMProgressContext) { $script:MMProgressContext = [ordered]@{} }
    # 224 (Wave B2b): a heartbeat only says "still working". Once the step has said what it is doing, a heartbeat
    # repeats those words and the step's own counts instead of its own (the internal job name, zeroed counts), for
    # every job; it still keeps the Workbench's "No processing update" timer quiet.
    $keepStepWords = $Heartbeat -and -not [string]::IsNullOrWhiteSpace([string]$script:MMProgressContext["Activity"])
    if ($keepStepWords) {
        foreach ($field in @("Activity", "ProgressKind")) { [void]$PSBoundParameters.Remove($field) }
        $Activity = ""
        foreach ($field in @("SourceOrdinal", "SourceState", "SourceTerminal", "PreparedCount", "BlockedCount", "FailedCount")) {
            if (-not $PSBoundParameters.ContainsKey($field) -and $script:MMProgressContext.Contains($field)) {
                Set-Variable -Name $field -Value $script:MMProgressContext[$field]
            }
        }
    }
    foreach ($field in @(
        "PhaseIndex", "PhaseCount", "SourceId", "SourceName", "OutcomeId", "ArtifactId",
        "Completed", "Total", "SourceCompleted", "SourceTotal", "OutcomeCompleted", "OutcomeTotal",
        "SourceOrdinal", "SourceState", "SourceTerminal", "PreparedCount", "BlockedCount", "FailedCount",
        "ArtifactCompleted", "ArtifactTotal", "ProgressKind", "WorkUnit", "Activity", "LatestArtifactPath"
    )) {
        if ($PSBoundParameters.ContainsKey($field)) {
            $script:MMProgressContext[$field] = Get-Variable -Name $field -ValueOnly
        }
    }
    $context = $script:MMProgressContext
    if (-not $PSBoundParameters.ContainsKey("PhaseIndex") -and $context.Contains("PhaseIndex")) { $PhaseIndex = [int]$context.PhaseIndex }
    if (-not $PSBoundParameters.ContainsKey("PhaseCount") -and $context.Contains("PhaseCount")) { $PhaseCount = [int]$context.PhaseCount }
    if ([string]::IsNullOrWhiteSpace($SourceId) -and $context.Contains("SourceId")) { $SourceId = [string]$context.SourceId }
    if ([string]::IsNullOrWhiteSpace($SourceName) -and $context.Contains("SourceName")) { $SourceName = [string]$context.SourceName }
    if (-not $PSBoundParameters.ContainsKey("Completed") -and $context.Contains("Completed")) { $Completed = [long]$context.Completed }
    if (-not $PSBoundParameters.ContainsKey("Total") -and $context.Contains("Total")) { $Total = [long]$context.Total }
    if (-not $PSBoundParameters.ContainsKey("SourceCompleted") -and $context.Contains("SourceCompleted")) { $SourceCompleted = [int]$context.SourceCompleted }
    if (-not $PSBoundParameters.ContainsKey("SourceTotal") -and $context.Contains("SourceTotal")) { $SourceTotal = [int]$context.SourceTotal }
    if (-not $PSBoundParameters.ContainsKey("OutcomeCompleted") -and $context.Contains("OutcomeCompleted")) { $OutcomeCompleted = [int]$context.OutcomeCompleted }
    if (-not $PSBoundParameters.ContainsKey("OutcomeTotal") -and $context.Contains("OutcomeTotal")) { $OutcomeTotal = [int]$context.OutcomeTotal }
    if (-not $PSBoundParameters.ContainsKey("ArtifactCompleted") -and $context.Contains("ArtifactCompleted")) { $ArtifactCompleted = [int]$context.ArtifactCompleted }
    if (-not $PSBoundParameters.ContainsKey("ArtifactTotal") -and $context.Contains("ArtifactTotal")) { $ArtifactTotal = [int]$context.ArtifactTotal }
    if (-not $PSBoundParameters.ContainsKey("ProgressKind") -and $context.Contains("ProgressKind")) { $ProgressKind = [string]$context.ProgressKind }
    if (-not $PSBoundParameters.ContainsKey("WorkUnit") -and $context.Contains("WorkUnit")) { $WorkUnit = [string]$context.WorkUnit }
    if ([string]::IsNullOrWhiteSpace($Activity) -and $context.Contains("Activity")) { $Activity = [string]$context.Activity }
    if ([string]::IsNullOrWhiteSpace($LatestArtifactPath) -and $context.Contains("LatestArtifactPath")) { $LatestArtifactPath = [string]$context.LatestArtifactPath }
    $elapsed = [math]::Max(0.0, ([DateTime]::UtcNow - $script:MMProgressStartedAt).TotalSeconds)
    if (-not $script:MMProgressPhaseStates) { $script:MMProgressPhaseStates = @{} }
    $phaseKey = $(if ([string]::IsNullOrWhiteSpace($Phase)) { [string]$script:MMProgressPhase } else { $Phase })
    if (-not $script:MMProgressPhaseStates.ContainsKey($phaseKey)) {
        $script:MMProgressPhaseStates[$phaseKey] = [ordered]@{ LastCompleted = 0; LastAt = [DateTime]::UtcNow; Samples = @() }
    }
    $phaseState = $script:MMProgressPhaseStates[$phaseKey]
    if ($ProgressKind -eq "work_units" -and $Completed -lt [long]$phaseState.LastCompleted) {
        # 224 (Wave B2a): the next recording's count starts again; its pace is measured afresh.
        $phaseState.LastCompleted = 0
        $phaseState.LastAt = [DateTime]::UtcNow
        $phaseState.Samples = @()
    }
    if ($ProgressKind -eq "work_units" -and $Completed -gt [long]$phaseState.LastCompleted) {
        $now = [DateTime]::UtcNow
        $itemDelta = $Completed - [long]$phaseState.LastCompleted
        $secondsPerItem = [math]::Max(0.0001, ($now - [DateTime]$phaseState.LastAt).TotalSeconds / $itemDelta)
        $phaseState.Samples = @($phaseState.Samples + $secondsPerItem | Select-Object -Last 10)
        $phaseState.LastCompleted = $Completed
        $phaseState.LastAt = $now
    }
    $sampleValues = @($phaseState.Samples)
    $meanSeconds = if ($sampleValues.Count -gt 0) { [double](($sampleValues | Measure-Object -Average).Average) } else { 0.0 }
    $throughput = if ($meanSeconds -gt 0) { 1.0 / $meanSeconds } else { 0.0 }
    $stableThroughput = $false
    if ($sampleValues.Count -ge 9 -and $meanSeconds -gt 0) {
        $variance = [double](($sampleValues | ForEach-Object { [math]::Pow(([double]$_ - $meanSeconds), 2) } | Measure-Object -Average).Average)
        $stableThroughput = ([math]::Sqrt($variance) / $meanSeconds) -le 0.35
    }
    $etaState = if (-not [string]::IsNullOrWhiteSpace($TerminalState)) {
        "unavailable"
    }
    elseif ($ProgressKind -ne "work_units" -or $Total -le 0) {
        "unavailable"
    }
    elseif ($Completed -lt 10 -or $throughput -le 0 -or -not $stableThroughput) {
        "estimating"
    }
    else {
        "available"
    }
    $payload = [ordered]@{
        schema = "MM_PROGRESS_V1"
        run_id = [string]$script:MMProgressRunId
        phase = $(if ([string]::IsNullOrWhiteSpace($Phase)) { [string]$script:MMProgressPhase } else { $Phase })
        phase_index = $PhaseIndex
        phase_count = $PhaseCount
        source_id = $SourceId
        source_name = $SourceName
        outcome_id = $OutcomeId
        artifact_id = $ArtifactId
        completed = $Completed
        total = $Total
        source_completed = $SourceCompleted
        source_total = $SourceTotal
        source_ordinal = $SourceOrdinal
        source_state = $SourceState
        source_terminal = $SourceTerminal
        prepared_count = $PreparedCount
        blocked_count = $BlockedCount
        failed_count = $FailedCount
        outcome_completed = $OutcomeCompleted
        outcome_total = $OutcomeTotal
        artifact_completed = $ArtifactCompleted
        artifact_total = $ArtifactTotal
        elapsed_seconds = [math]::Round($elapsed, 3)
        throughput_per_second = [math]::Round($throughput, 4)
        eta_state = $etaState
        eta_seconds = $(if ($etaState -eq "available") { [math]::Round(($Total - $Completed) / $throughput, 1) } else { $null })
        heartbeat = [bool]$Heartbeat
        progress_kind = $ProgressKind
        work_unit = $(if ($ProgressKind -eq "work_units") { $WorkUnit } else { "" })
        activity = $Activity
        latest_artifact_path = $LatestArtifactPath
        provider_stage = $ProviderStage
        provider_message = $ProviderMessage
        provider_device = $ProviderDevice
        provider_updated_at = $ProviderUpdatedAt
        terminal_state = $TerminalState
        emitted_at = [DateTime]::UtcNow.ToString("o")
    }
    Write-Host ("MM_PROGRESS_V1 " + ($payload | ConvertTo-Json -Compress -Depth 5))
}

function Read-TimedDefaultPrompt {
    param(
        [string]$Prompt,
        [string]$DefaultValue,
        [int]$TimeoutSeconds = $script:PromptTimeoutSeconds,
        [switch]$NoPrompt
    )

    if ($NoPrompt) {
        Write-Log ("Prompt skipped by -NoPrompt; using default: {0}" -f $DefaultValue)
        return $DefaultValue
    }

    if ($TimeoutSeconds -le 0) {
        return (Read-Host $Prompt)
    }

    $displayPrompt = $Prompt
    if ($displayPrompt -notmatch '\s$') {
        $displayPrompt += " "
    }

    try {
        [void][Console]::KeyAvailable
    }
    catch {
        Write-Host ("{0} [using default: {1}]" -f $displayPrompt.TrimEnd(), $DefaultValue)
        Write-Log ("Prompt could not poll console for timed input; using default: {0}" -f $DefaultValue) "WARN"
        return $DefaultValue
    }

    $buffer = New-Object System.Text.StringBuilder
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    Write-Host -NoNewline $displayPrompt

    while ((Get-Date) -lt $deadline) {
        try {
            if ([Console]::KeyAvailable) {
                $key = [Console]::ReadKey($true)
                if ($key.Key -eq [System.ConsoleKey]::Enter) {
                    Write-Host ""
                    $typed = $buffer.ToString()
                    if ([string]::IsNullOrWhiteSpace($typed)) {
                        return $DefaultValue
                    }
                    return $typed
                }
                if ($key.Key -eq [System.ConsoleKey]::Backspace) {
                    if ($buffer.Length -gt 0) {
                        [void]$buffer.Remove($buffer.Length - 1, 1)
                        Write-Host -NoNewline "`b `b"
                    }
                    continue
                }
                if ($key.Key -eq [System.ConsoleKey]::Escape) {
                    Write-Host ""
                    return ""
                }
                if ($key.KeyChar -and [int][char]$key.KeyChar -ge 32) {
                    [void]$buffer.Append($key.KeyChar)
                    Write-Host -NoNewline $key.KeyChar
                }
            }
        }
        catch {
            Write-Host ""
            Write-Log ("Prompt timed input failed before completion; using default: {0}" -f $DefaultValue) "WARN"
            return $DefaultValue
        }

        Start-Sleep -Milliseconds 100
    }

    Write-Host ""
    Write-Log ("Prompt timed out after {0}s; using default: {1}" -f $TimeoutSeconds, $DefaultValue)
    return $DefaultValue
}

function Read-TimedChoicePrompt {
    param(
        [string]$Prompt,
        [string]$DefaultValue,
        [int]$TimeoutSeconds = $script:PromptTimeoutSeconds,
        [switch]$NoPrompt
    )

    return (Read-TimedDefaultPrompt -Prompt $Prompt -DefaultValue $DefaultValue -TimeoutSeconds $TimeoutSeconds -NoPrompt:$NoPrompt)
}

function Read-TimedYesNoPrompt {
    param(
        [string]$Prompt,
        [bool]$DefaultYes = $true,
        [int]$TimeoutSeconds = $script:PromptTimeoutSeconds,
        [switch]$NoPrompt
    )

    $defaultValue = if ($DefaultYes) { "Y" } else { "N" }
    while ($true) {
        $value = Read-TimedDefaultPrompt -Prompt $Prompt -DefaultValue $defaultValue -TimeoutSeconds $TimeoutSeconds -NoPrompt:$NoPrompt
        if ([string]::IsNullOrWhiteSpace($value)) {
            return [bool]$DefaultYes
        }
        if ($value.Trim() -match '^(?i)(y|yes)$') {
            return $true
        }
        if ($value.Trim() -match '^(?i)(n|no)$') {
            return $false
        }
        Write-Host "Please enter Y, N, or just press Enter for the default." -ForegroundColor Yellow
    }
}

function Read-RequiredPathPrompt {
    param([string]$Prompt)

    return (Read-Host $Prompt)
}

function Initialize-StdInInterop {
    if ("MediaMangler.NativeMethods" -as [type]) {
        return
    }

    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

namespace MediaMangler {
    public static class NativeMethods {
        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern IntPtr GetStdHandle(int nStdHandle);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool PeekNamedPipe(
            IntPtr hNamedPipe,
            IntPtr lpBuffer,
            uint nBufferSize,
            IntPtr lpBytesRead,
            out uint lpTotalBytesAvail,
            IntPtr lpBytesLeftThisMessage);
    }
}
"@
}

function Read-LineWithTimeout {
    param(
        [string]$Prompt,
        [int]$TimeoutSeconds = 30
    )

    $deadline = [System.DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    Write-Host ($Prompt + " ") -NoNewline

    if ([System.Console]::IsInputRedirected) {
        $stdInHandle = [System.IntPtr]::Zero
        $canPollRedirectedInput = $false

        try {
            Initialize-StdInInterop
            $stdInHandle = [MediaMangler.NativeMethods]::GetStdHandle(-10)
            $canPollRedirectedInput = $stdInHandle -ne [System.IntPtr]::Zero -and $stdInHandle.ToInt64() -ne -1
        }
        catch {
            $canPollRedirectedInput = $false
        }

        while ([System.DateTime]::UtcNow -lt $deadline) {
            if ($canPollRedirectedInput) {
                $bytesAvailable = [uint32]0
                $canPeek = $false

                try {
                    $canPeek = [MediaMangler.NativeMethods]::PeekNamedPipe(
                        $stdInHandle,
                        [System.IntPtr]::Zero,
                        [uint32]0,
                        [System.IntPtr]::Zero,
                        [ref]$bytesAvailable,
                        [System.IntPtr]::Zero)
                }
                catch {
                    $canPeek = $false
                }

                if ($canPeek -and $bytesAvailable -gt 0) {
                    $line = [System.Console]::In.ReadLine()
                    Write-Host ""
                    return [PSCustomObject]@{
                        TimedOut = $false
                        Value    = if ($null -eq $line) { "" } else { $line }
                    }
                }
            }

            Start-Sleep -Milliseconds 100
        }

        Write-Host ""
        return [PSCustomObject]@{
            TimedOut = $true
            Value    = ""
        }
    }

    $builder = New-Object System.Text.StringBuilder
    while ([System.DateTime]::UtcNow -lt $deadline) {
        while ([System.Console]::KeyAvailable) {
            $key = [System.Console]::ReadKey($true)

            if ($key.Key -eq [System.ConsoleKey]::Enter) {
                Write-Host ""
                return [PSCustomObject]@{
                    TimedOut = $false
                    Value    = $builder.ToString()
                }
            }

            if ($key.Key -eq [System.ConsoleKey]::Backspace) {
                if ($builder.Length -gt 0) {
                    $builder.Length -= 1
                    Write-Host "`b `b" -NoNewline
                }

                continue
            }

            if (-not [char]::IsControl($key.KeyChar)) {
                [void]$builder.Append($key.KeyChar)
                Write-Host $key.KeyChar -NoNewline
            }
        }

        Start-Sleep -Milliseconds 50
    }

    Write-Host ""
    return [PSCustomObject]@{
        TimedOut = $true
        Value    = ""
    }
}

function Write-Phase {
    param(
        [string]$Name,
        [string]$Detail
    )

    Write-Host ""
    Write-Host ("==== {0} ====" -f $Name) -ForegroundColor Cyan
    if (-not [string]::IsNullOrWhiteSpace($Detail)) {
        Write-Host $Detail -ForegroundColor Cyan
    }

    $message = if ([string]::IsNullOrWhiteSpace($Detail)) {
        "PHASE: $Name"
    }
    else {
        "PHASE: $Name - $Detail"
    }

    Write-Log $message
}

function Write-PhaseResult {
    param(
        [string]$Name,
        [ValidateSet("PASS","FAIL")]
        [string]$Status,
        [string]$Detail
    )

    $message = if ([string]::IsNullOrWhiteSpace($Detail)) {
        "$Name complete"
    }
    else {
        "$Name complete - $Detail"
    }

    Write-Log $message $Status
}

function Invoke-PhaseAction {
    param(
        [string]$Name,
        [string]$Detail,
        [scriptblock]$Action
    )

    Write-Phase -Name $Name -Detail $Detail

    try {
        $result = & $Action
        Write-PhaseResult -Name $Name -Status "PASS" -Detail $Detail
        return $result
    }
    catch {
        Write-PhaseResult -Name $Name -Status "FAIL" -Detail $_.Exception.Message
        throw
    }
}

# 188: where each outside tool comes from, and its own install folders. The Workbench has the same
# table (src\media_manglers_workbench\tool_sources.py); tests\test_tool_sources.py keeps them equal.
# Every tool is looked for in the same order: the path given, then PATH, then these folders.
# Nothing here downloads or installs anything.
function Get-ToolSource {
    param([Parameter(Mandatory)] [string]$Key)

    $sources = @{
        ffmpeg  = @{ Name = "FFmpeg"; Page = "https://ffmpeg.org/download.html"; WingetId = "Gyan.FFmpeg"; Standard = @(
                @("LOCALAPPDATA", "Microsoft\WinGet\Links\ffmpeg.exe"),
                @("ProgramFiles", "WinGet\Links\ffmpeg.exe"),
                @("LOCALAPPDATA", "Microsoft\WinGet\Packages\Gyan.FFmpeg_*\ffmpeg-*\bin\ffmpeg.exe")) }
        ffprobe = @{ Name = "FFprobe"; Page = "https://ffmpeg.org/download.html"; WingetId = "Gyan.FFmpeg"; Standard = @(
                @("LOCALAPPDATA", "Microsoft\WinGet\Links\ffprobe.exe"),
                @("ProgramFiles", "WinGet\Links\ffprobe.exe"),
                @("LOCALAPPDATA", "Microsoft\WinGet\Packages\Gyan.FFmpeg_*\ffmpeg-*\bin\ffprobe.exe")) }
        ytdlp   = @{ Name = "yt-dlp"; Page = "https://github.com/yt-dlp/yt-dlp#installation"; WingetId = "yt-dlp.yt-dlp"; Standard = @(
                @("LOCALAPPDATA", "Microsoft\WinGet\Links\yt-dlp.exe"),
                @("ProgramFiles", "WinGet\Links\yt-dlp.exe"),
                @("LOCALAPPDATA", "Microsoft\WinGet\Packages\yt-dlp.yt-dlp_*\yt-dlp.exe")) }
        python  = @{ Name = "Python"; Page = "https://www.python.org/downloads/windows/"; WingetId = "Python.Python.3.12"; Standard = @(
                @("LOCALAPPDATA", "Programs\Python\Python3*\python.exe"),
                @("LOCALAPPDATA", "Python\pythoncore-3*\python.exe"),
                @("ProgramFiles", "Python3*\python.exe")) }
        whisper = @{ Name = "Local Whisper"; Page = "https://github.com/openai/whisper#setup"; WingetId = ""; Standard = @() }
    }
    return $sources[$Key]
}

function Get-ToolStandardLocations {
    param([Parameter(Mandatory)] [string]$Key)

    $found = New-Object System.Collections.Generic.List[string]
    foreach ($entry in (Get-ToolSource -Key $Key).Standard) {
        $base = [Environment]::GetEnvironmentVariable($entry[0])
        if ([string]::IsNullOrWhiteSpace($base)) {
            continue
        }
        $pattern = Join-Path $base $entry[1]
        if ($pattern.Contains("*")) {
            # Newest version folder first; numbers compare as numbers (Python312 before Python39).
            $byVersion = { [regex]::Replace($_.FullName, '\d+', { param($m) $m.Value.PadLeft(10, '0') }) }
            foreach ($match in @(Get-ChildItem -Path $pattern -File -ErrorAction SilentlyContinue | Sort-Object $byVersion -Descending)) {
                $found.Add($match.FullName)
            }
        }
        else {
            $found.Add($pattern)
        }
    }
    return @($found)
}

function Get-ToolGetItText {
    param([Parameter(Mandatory)] [string]$Key)

    $source = Get-ToolSource -Key $Key
    $text = "Get it from the official page: $($source.Page)"
    if ($source.WingetId) {
        $text += ", or install it with: winget install --id $($source.WingetId) -e"
    }
    return $text
}

function Resolve-ExecutablePath {
    param(
        [string]$PreferredPath,
        [string[]]$FallbackCommands,
        [string[]]$FallbackPaths,
        [string]$ToolName,
        [string]$ToolKey = ""
    )

    # 188: the path given, then PATH, then the tool's own install folders.
    $candidates = New-Object System.Collections.Generic.List[string]
    $looked = New-Object System.Collections.Generic.List[string]

    if (-not [string]::IsNullOrWhiteSpace($PreferredPath)) {
        $candidates.Add($PreferredPath)
        $looked.Add($PreferredPath)
    }

    foreach ($commandName in ($FallbackCommands | Where-Object { $_ })) {
        $looked.Add("PATH ($commandName)")
        $command = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($command -and $command.Source) {
            $candidates.Add($command.Source)
        }
    }

    if ($ToolKey) {
        foreach ($entry in (Get-ToolSource -Key $ToolKey).Standard) {
            $looked.Add(('%{0}%\{1}' -f $entry[0], $entry[1]))
        }
        foreach ($path in (Get-ToolStandardLocations -Key $ToolKey)) {
            $candidates.Add($path)
        }
    }

    foreach ($path in ($FallbackPaths | Where-Object { $_ })) {
        $candidates.Add($path)
        $looked.Add($path)
    }

    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).ProviderPath
        }
    }

    $message = "$ToolName not found. Looked in: $($looked -join '; ')."
    if ($ToolKey) {
        $message += " $(Get-ToolGetItText -Key $ToolKey). Then run again, or give its full path."
    }
    throw $message
}

function Get-FFprobePath {
    param([string]$FFmpegExe)

    # FFprobe ships beside FFmpeg; then PATH, then its own install folders.
    $sibling = Join-Path (Split-Path $FFmpegExe -Parent) "ffprobe.exe"
    return Resolve-ExecutablePath `
        -PreferredPath $sibling `
        -FallbackCommands @("ffprobe") `
        -ToolName "FFprobe" `
        -ToolKey "ffprobe"
}

function Resolve-CommandOrPath {
    param(
        [string]$Value,
        [string]$ToolName,
        [string]$ToolKey = ""
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "$ToolName not specified."
    }

    if (Test-Path -LiteralPath $Value) {
        return (Resolve-Path -LiteralPath $Value).ProviderPath
    }

    $command = Get-Command $Value -ErrorAction SilentlyContinue
    if ($command -and $command.Source) {
        return $command.Source
    }

    $message = "$ToolName not found. Checked command/path: $Value"
    if ($ToolKey) {
        $message += ". $(Get-ToolGetItText -Key $ToolKey)."
    }
    throw $message
}

function Normalize-UserPath {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $Path
    }

    $normalized = $Path.Trim()

    if ($normalized.Length -ge 2) {
        if (($normalized.StartsWith('"') -and $normalized.EndsWith('"')) -or
            ($normalized.StartsWith("'") -and $normalized.EndsWith("'"))) {
            $normalized = $normalized.Substring(1, $normalized.Length - 2).Trim()
        }
    }

    return $normalized
}

function Get-AppBaseDirectory {
    if (-not [string]::IsNullOrWhiteSpace($script:ResolvedAppBaseDirectory)) {
        return $script:ResolvedAppBaseDirectory
    }

    $candidates = New-Object System.Collections.Generic.List[string]
    if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) {
        $candidates.Add($PSScriptRoot)
    }

    try {
        $processPath = [System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
        if (-not [string]::IsNullOrWhiteSpace($processPath)) {
            $processDirectory = Split-Path -Path $processPath -Parent
            if (-not [string]::IsNullOrWhiteSpace($processDirectory)) {
                $candidates.Add($processDirectory)
            }
        }
    }
    catch {
    }

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate)) {
            $script:ResolvedAppBaseDirectory = (Resolve-Path -LiteralPath $candidate).ProviderPath
            return $script:ResolvedAppBaseDirectory
        }
    }

    return $null
}

function Get-RuntimeSearchRoots {
    $candidateRoots = New-Object System.Collections.Generic.List[string]

    if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) {
        $candidateRoots.Add($PSScriptRoot)
    }

    $appBaseDirectory = Get-AppBaseDirectory
    if (-not [string]::IsNullOrWhiteSpace($appBaseDirectory)) {
        $candidateRoots.Add($appBaseDirectory)

        $parentDirectory = Split-Path -Path $appBaseDirectory -Parent
        if (-not [string]::IsNullOrWhiteSpace($parentDirectory)) {
            $candidateRoots.Add($parentDirectory)

            $grandParentDirectory = Split-Path -Path $parentDirectory -Parent
            if (-not [string]::IsNullOrWhiteSpace($grandParentDirectory)) {
                $candidateRoots.Add($grandParentDirectory)
            }
        }
    }

    return @($candidateRoots | Select-Object -Unique)
}

function Get-MediaManglersPythonCliInfo {
    if ($null -ne $script:MediaManglersPythonCliInfo) {
        return $script:MediaManglersPythonCliInfo
    }

    $candidateRoots = New-Object System.Collections.Generic.List[string]
    foreach ($runtimeRoot in @(Get-RuntimeSearchRoots)) {
        $candidateRoots.Add((Join-Path $runtimeRoot "src"))
        $candidateRoots.Add((Join-Path $runtimeRoot "python-core\src"))
    }

    foreach ($candidateRoot in ($candidateRoots | Select-Object -Unique)) {
        $entryPoint = Join-Path $candidateRoot "media_manglers\__main__.py"
        if (Test-Path -LiteralPath $entryPoint) {
            $resolvedRoot = (Resolve-Path -LiteralPath $candidateRoot).ProviderPath
            $script:MediaManglersPythonCliInfo = [PSCustomObject]@{
                Enabled   = $true
                Root      = $resolvedRoot
                EntryPoint = $entryPoint
            }
            return $script:MediaManglersPythonCliInfo
        }
    }

    $script:MediaManglersPythonCliInfo = [PSCustomObject]@{
        Enabled   = $false
        Root      = ""
        EntryPoint = ""
    }
    return $script:MediaManglersPythonCliInfo
}

function Get-MediaManglersPythonCliUnavailableMessage {
    param([string]$FeatureLabel = "This feature")

    return ("{0} could not find the packaged python helper sidecar. {1}" -f $FeatureLabel, (Get-PackagedRuntimeGuidance))
}

function Resolve-PythonInterpreterPath {
    param(
        [string]$RequestedValue,
        [switch]$WasExplicitlySet
    )

    if ($WasExplicitlySet -and -not [string]::IsNullOrWhiteSpace($RequestedValue)) {
        try {
            return Resolve-CommandOrPath -Value $RequestedValue -ToolName "Python interpreter"
        }
        catch {
            throw ("The configured -PythonExe value '{0}' could not be resolved. Point -PythonExe to a usable interpreter. {1}." -f $RequestedValue, (Get-ToolGetItText -Key "python"))
        }
    }

    try {
        return Resolve-CommandOrPath -Value "python" -ToolName "Python interpreter"
    }
    catch {
    }

    $pyLauncher = Get-Command "py" -ErrorAction SilentlyContinue
    if ($pyLauncher -and $pyLauncher.Source) {
        $probe = Invoke-ExternalCapture `
            -FilePath $pyLauncher.Source `
            -Arguments @("-3", "-c", "import sys; print(sys.executable)") `
            -StepName "Resolve Python interpreter via py -3" `
            -IgnoreExitCode `
            -TimeoutSeconds 120

        if ($probe.ExitCode -eq 0) {
            $resolvedInterpreter = ($probe.StdOut -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Last 1).Trim()
            if (-not [string]::IsNullOrWhiteSpace($resolvedInterpreter) -and (Test-Path -LiteralPath $resolvedInterpreter)) {
                return (Resolve-Path -LiteralPath $resolvedInterpreter).ProviderPath
            }
        }
    }

    # 188: last, Python's own install folders.
    foreach ($candidate in (Get-ToolStandardLocations -Key "python")) {
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).ProviderPath
        }
    }

    throw ("Python interpreter not found. Automatic resolution order: explicit -PythonExe, then python, then py -3, then Python's own install folders. {0}. Then run again, or rerun with -PythonExe pointing to a usable interpreter." -f (Get-ToolGetItText -Key "python"))
}

function Get-AutoPythonInterpreterCandidates {
    param([string]$PrimaryPythonCommand)

    $candidates = New-Object System.Collections.Generic.List[string]

    foreach ($candidate in @($PrimaryPythonCommand, "python")) {
        if ([string]::IsNullOrWhiteSpace($candidate)) {
            continue
        }

        try {
            $resolvedCandidate = Resolve-CommandOrPath -Value $candidate -ToolName "Python interpreter"
            if (-not [string]::IsNullOrWhiteSpace($resolvedCandidate)) {
                $candidates.Add($resolvedCandidate)
            }
        }
        catch {
        }
    }

    $pyLauncher = Get-Command "py" -ErrorAction SilentlyContinue
    if ($pyLauncher -and $pyLauncher.Source) {
        $probe = Invoke-ExternalCapture `
            -FilePath $pyLauncher.Source `
            -Arguments @("-3", "-c", "import sys; print(sys.executable)") `
            -StepName "Resolve Python interpreter via py -3" `
            -IgnoreExitCode `
            -TimeoutSeconds 120

        if ($probe.ExitCode -eq 0) {
            $resolvedInterpreter = ($probe.StdOut -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Last 1).Trim()
            if (-not [string]::IsNullOrWhiteSpace($resolvedInterpreter) -and (Test-Path -LiteralPath $resolvedInterpreter)) {
                $candidates.Add((Resolve-Path -LiteralPath $resolvedInterpreter).ProviderPath)
            }
        }
    }

    $whereExe = Get-Command "where.exe" -ErrorAction SilentlyContinue
    if ($whereExe -and $whereExe.Source) {
        $whereResult = Invoke-ExternalCapture `
            -FilePath $whereExe.Source `
            -Arguments @("python") `
            -StepName "Enumerate Python interpreter candidates" `
            -IgnoreExitCode `
            -TimeoutSeconds 30

        if ($whereResult.ExitCode -eq 0) {
            foreach ($match in ($whereResult.StdOut -split "`r?`n")) {
                $trimmedMatch = $match.Trim()
                if (-not [string]::IsNullOrWhiteSpace($trimmedMatch) -and (Test-Path -LiteralPath $trimmedMatch)) {
                    $candidates.Add((Resolve-Path -LiteralPath $trimmedMatch).ProviderPath)
                }
            }
        }
    }

    return @($candidates | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)
}

function Select-PreferredWhisperPythonInterpreter {
    param([string]$PrimaryPythonCommand)

    $candidatePaths = @(Get-AutoPythonInterpreterCandidates -PrimaryPythonCommand $PrimaryPythonCommand)
    if ($candidatePaths.Count -eq 0) {
        return [PSCustomObject]@{
            Path  = $PrimaryPythonCommand
            Probe = $null
            Note  = $null
        }
    }

    $candidateResults = New-Object System.Collections.Generic.List[object]
    $candidateIndex = 0

    foreach ($candidatePath in $candidatePaths) {
        $probe = Get-WhisperExecutionMode -PythonCommand $candidatePath
        $resolvedPath = $candidatePath
        if (-not [string]::IsNullOrWhiteSpace($probe.PythonPath) -and (Test-Path -LiteralPath $probe.PythonPath)) {
            $resolvedPath = (Resolve-Path -LiteralPath $probe.PythonPath).ProviderPath
        }

        $score = 0
        if ($probe.WhisperImportOk) {
            $score += 20
        }
        if ($probe.TorchImportOk) {
            $score += 20
        }
        if ($probe.CudaAvailable) {
            $score += 100
        }
        elseif ($probe.TorchImportOk) {
            $score += 10
        }

        $candidateResults.Add([PSCustomObject]@{
                Index = $candidateIndex
                RequestedPath = $candidatePath
                Path = $resolvedPath
                Probe = $probe
                Score = $score
            })
        $candidateIndex += 1
    }

    $selected = $candidateResults | Sort-Object -Property @{ Expression = "Score"; Descending = $true }, @{ Expression = "Index"; Descending = $false } | Select-Object -First 1
    $primaryCandidate = $candidateResults | Where-Object { $_.Index -eq 0 } | Select-Object -First 1
    $note = $null
    $cudaReadyCandidates = @($candidateResults | Where-Object { $_.Probe -and $_.Probe.CudaAvailable })
    $whisperReadyCandidates = @($candidateResults | Where-Object { $_.Probe -and $_.Probe.WhisperImportOk })
    $primaryResolvedPath = if ($primaryCandidate) { [string]$primaryCandidate.Path } else { [string]$PrimaryPythonCommand }
    $changedInterpreter = -not [string]::Equals([string]$selected.Path, $primaryResolvedPath, [System.StringComparison]::OrdinalIgnoreCase)

    if ($changedInterpreter) {
        if ($selected.Probe -and $selected.Probe.CudaAvailable) {
            $note = ("Auto-selected Python interpreter '{0}' because it reported Whisper with CUDA enabled. Default auto-detected runtime '{1}' was not kept." -f $selected.Path, $primaryResolvedPath)
        }
        elseif ($selected.Probe -and $selected.Probe.WhisperImportOk) {
            $note = ("Auto-selected Python interpreter '{0}' because it reported a healthier Whisper runtime than default auto-detected runtime '{1}'." -f $selected.Path, $primaryResolvedPath)
        }
    }
    elseif ($cudaReadyCandidates.Count -eq 0 -and $whisperReadyCandidates.Count -gt 0) {
        $note = ("No available Python interpreter reported CUDA during startup probing. Local Whisper will run on CPU with interpreter '{0}'." -f $selected.Path)
    }
    elseif ($whisperReadyCandidates.Count -eq 0) {
        $note = ("No probed Python interpreter reported a healthy Whisper runtime. Using '{0}' and continuing with existing fallback behavior." -f $selected.Path)
    }

    return [PSCustomObject]@{
        Path  = [string]$selected.Path
        Probe = $selected.Probe
        Note  = $note
    }
}

function Invoke-MediaManglersPythonCli {
    param(
        [string]$PythonCommand,
        [string]$Command,
        [hashtable]$Payload,
        [string]$StepName,
        [int]$HeartbeatSeconds = 10,
        [int]$TimeoutSeconds = 1800,
        [int]$StallTimeoutSeconds = 0,
        [double]$EstimatedTotalSeconds = 0,
        [string]$ProgressStateFilePath = "",
        [psobject]$CpuFallbackRuntimePlan = $null
    )

    $cliInfo = Get-MediaManglersPythonCliInfo
    if (-not $cliInfo.Enabled) {
        return $null
    }

    # 201: named for this process, so a run after a Stop can remove what this one left.
    $tempRequestJson = Get-MMScratchPath -Prefix "media_manglers_request" -Extension ".json"
    $tempResultJson = Get-MMScratchPath -Prefix "media_manglers_result" -Extension ".json"
    $requestPayload = if ($null -eq $Payload) { @{} } else { $Payload }
    [PSCustomObject]@{ payload = $requestPayload } | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $tempRequestJson -Encoding UTF8

    $previousPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
    $updatedPythonPath = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) {
        $cliInfo.Root
    }
    else {
        "{0};{1}" -f $cliInfo.Root, $previousPythonPath
    }

    [Environment]::SetEnvironmentVariable("PYTHONPATH", $updatedPythonPath, "Process")

    try {
        $commandResult = Invoke-ExternalStreaming `
            -FilePath $PythonCommand `
            -Arguments @("-m", "media_manglers", $Command, "--request-file", $tempRequestJson, "--result-file", $tempResultJson) `
            -StepName $StepName `
            -IgnoreExitCode `
            -HeartbeatSeconds $HeartbeatSeconds `
            -TimeoutSeconds $TimeoutSeconds `
            -StallTimeoutSeconds $StallTimeoutSeconds `
            -EstimatedTotalSeconds $EstimatedTotalSeconds `
            -ProgressStateFilePath $ProgressStateFilePath `
            -CpuFallbackRuntimePlan $CpuFallbackRuntimePlan

        $parsedResult = $null
        if (Test-Path -LiteralPath $tempResultJson) {
            $parsedResult = Get-Content -LiteralPath $tempResultJson -Raw -Encoding UTF8 | ConvertFrom-Json
        }

        return [PSCustomObject]@{
            ExitCode = $commandResult.ExitCode
            Result   = $parsedResult
            Root     = $cliInfo.Root
        }
    }
    finally {
        [Environment]::SetEnvironmentVariable("PYTHONPATH", $previousPythonPath, "Process")
        foreach ($tempPath in @($tempRequestJson, $tempResultJson)) {
            if (Test-Path -LiteralPath $tempPath) {
                Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

function Resolve-YtDlpInvoker {
    param(
        [string]$PreferredCommand,
        [string]$PythonCommand
    )

    $executableCandidates = New-Object System.Collections.Generic.List[string]

    if (-not [string]::IsNullOrWhiteSpace($PreferredCommand)) {
        $executableCandidates.Add($PreferredCommand)
    }

    foreach ($commandName in @("yt-dlp", "yt-dlp.exe")) {
        if (-not [string]::IsNullOrWhiteSpace($commandName)) {
            $executableCandidates.Add($commandName)
        }
    }

    # 188: then yt-dlp's own install folders (Windows Package Manager).
    foreach ($standard in (Get-ToolStandardLocations -Key "ytdlp")) {
        $executableCandidates.Add($standard)
    }

    $userProfile = [Environment]::GetFolderPath("UserProfile")
    $localAppData = [Environment]::GetFolderPath("LocalApplicationData")
    $roamingAppData = [Environment]::GetFolderPath("ApplicationData")
    $fallbackGlobs = @(
        (Join-Path $userProfile "AppData\Roaming\Python\Python*\Scripts\yt-dlp.exe"),
        (Join-Path $localAppData "Programs\Python\Python*\Scripts\yt-dlp.exe"),
        (Join-Path $roamingAppData "Python\Python*\Scripts\yt-dlp.exe")
    )

    foreach ($glob in $fallbackGlobs) {
        $matches = @(Get-ChildItem -Path $glob -File -ErrorAction SilentlyContinue | Sort-Object FullName -Descending)
        foreach ($match in $matches) {
            $executableCandidates.Add($match.FullName)
        }
    }

    foreach ($candidate in ($executableCandidates | Select-Object -Unique)) {
        try {
            $resolved = Resolve-CommandOrPath -Value $candidate -ToolName "yt-dlp"
            return [PSCustomObject]@{
                FilePath    = $resolved
                Arguments   = @()
                DisplayName = $resolved
            }
        }
        catch {
            Write-Log "yt-dlp command candidate '$candidate' unavailable: $($_.Exception.Message)" "WARN"
        }
    }

    $pythonCandidates = New-Object System.Collections.Generic.List[string]
    foreach ($candidate in @($PythonCommand, "py", "python", "python3")) {
        if (-not [string]::IsNullOrWhiteSpace($candidate)) {
            $pythonCandidates.Add($candidate)
        }
    }

    foreach ($pythonCandidate in ($pythonCandidates | Select-Object -Unique)) {
        $moduleCheck = Invoke-ExternalCapture `
            -FilePath $pythonCandidate `
            -Arguments @("-m", "yt_dlp", "--version") `
            -StepName "yt-dlp Python module check ($pythonCandidate)" `
            -TimeoutSeconds 60 `
            -IgnoreExitCode

        if ($moduleCheck.ExitCode -eq 0) {
            return [PSCustomObject]@{
                FilePath    = $pythonCandidate
                Arguments   = @("-m", "yt_dlp")
                DisplayName = "$pythonCandidate -m yt_dlp"
            }
        }
    }

    throw "Remote video URLs require yt-dlp. Install it with 'winget install --id yt-dlp.yt-dlp -e' or 'py -m pip install -U yt-dlp' (official page: $((Get-ToolSource -Key 'ytdlp').Page))."
}

function Test-IsYouTubeUrl {
    param([string]$SourceUrl)

    if ([string]::IsNullOrWhiteSpace($SourceUrl)) {
        return $false
    }

    return $SourceUrl.Trim().ToLowerInvariant() -match '^https?://([a-z0-9-]+\.)?(youtube\.com|youtu\.be)/'
}

function Get-RemoteSourceKind {
    param([string]$SourceUrl)

    $normalized = $SourceUrl.ToLowerInvariant()
    $isYoutube = Test-IsYouTubeUrl -SourceUrl $SourceUrl

    if ($isYoutube -and (
            $normalized -match 'youtube\.com/playlist\?' -or
            ($normalized -match '[?&]list=' -and $normalized -notmatch '[?&]v=' -and $normalized -notmatch 'youtu\.be/')
        )) {
        return "playlist"
    }

    return "video"
}

function Get-PrimaryLanguageTag {
    param([string]$LanguageCode)

    if ([string]::IsNullOrWhiteSpace($LanguageCode)) {
        return ""
    }

    $normalized = $LanguageCode.Trim().Replace("_", "-")
    return ($normalized -split '-')[0].ToLowerInvariant()
}

function Get-CanonicalLanguageCode {
    param([string]$Language)

    if ([string]::IsNullOrWhiteSpace($Language)) {
        return ""
    }

    $normalized = $Language.Trim().ToLowerInvariant().Replace("_", "-")
    switch ($normalized) {
        "english" { return "en" }
        "spanish" { return "es" }
        "french" { return "fr" }
        "german" { return "de" }
        "italian" { return "it" }
        "portuguese" { return "pt" }
        "japanese" { return "ja" }
        "korean" { return "ko" }
        "chinese" { return "zh" }
        "arabic" { return "ar" }
        "russian" { return "ru" }
        default {
            if ($normalized -match '^[a-z]{2,3}(-[a-z0-9]+)?$') {
                return Get-PrimaryLanguageTag -LanguageCode $normalized
            }

            return $normalized
        }
    }
}

function Get-RemoteAudioTrackFormatHints {
    param([psobject]$Format)

    $formatUrl = [string]$Format.url
    $xtags = ""
    if (-not [string]::IsNullOrWhiteSpace($formatUrl) -and $formatUrl -match '[?&]xtags=([^&]+)') {
        $xtags = [System.Uri]::UnescapeDataString($Matches[1])
    }

    $languageFromXtags = ""
    if (-not [string]::IsNullOrWhiteSpace($xtags) -and $xtags -match 'lang=([^:;]+)') {
        $languageFromXtags = $Matches[1].Trim()
    }

    $audioContentTag = ""
    if (-not [string]::IsNullOrWhiteSpace($xtags) -and $xtags -match 'acont=([^:;]+)') {
        $audioContentTag = $Matches[1].Trim().ToLowerInvariant()
    }

    $languageCode = if (-not [string]::IsNullOrWhiteSpace([string]$Format.language)) {
        ([string]$Format.language).Trim()
    }
    else {
        $languageFromXtags
    }

    $languagePreference = 0
    if ($null -ne $Format.PSObject.Properties['language_preference'] -and $null -ne $Format.language_preference) {
        $rawPreference = [string]$Format.language_preference
        if (-not [string]::IsNullOrWhiteSpace($rawPreference)) {
            try {
                $languagePreference = [int]$Format.language_preference
            }
            catch {
                $languagePreference = 0
            }
        }
    }

    $formatNote = [string]$Format.format_note
    $isOriginal = $audioContentTag -like '*original*' -or $formatNote -match '\boriginal\b' -or $languagePreference -ge 10
    $isDefault = $formatNote -match '\bdefault\b' -or ($languagePreference -ge 5 -and -not $isOriginal)
    $isDubbed = $audioContentTag -match 'dubbed|translated' -or $formatNote -match '\bdubbed\b|\btranslated\b'
    $isAudioOnly = ([string]$Format.vcodec).ToLowerInvariant() -eq "none"

    return [PSCustomObject]@{
        LanguageCode       = $languageCode
        LanguagePreference = $languagePreference
        Xtags              = $xtags
        AudioContentTag    = $audioContentTag
        IsOriginal         = $isOriginal
        IsDefault          = $isDefault
        IsDubbed           = $isDubbed
        IsAudioOnly        = $isAudioOnly
        IsMuxed            = (-not $isAudioOnly)
    }
}

function Get-RemoteAudioTrackCandidates {
    param([object[]]$Formats)

    $exactGroups = @{}

    foreach ($format in @($Formats)) {
        if ($null -eq $format) {
            continue
        }

        if (-not $format.PSObject.Properties['acodec']) {
            continue
        }

        $audioCodec = [string]$format.acodec
        if ([string]::IsNullOrWhiteSpace($audioCodec) -or $audioCodec -eq "none") {
            continue
        }

        $hints = Get-RemoteAudioTrackFormatHints -Format $format
        if ([string]::IsNullOrWhiteSpace($hints.LanguageCode)) {
            continue
        }

        $languageCode = $hints.LanguageCode.Trim().Replace("_", "-")
        if (-not $exactGroups.ContainsKey($languageCode)) {
            $exactGroups[$languageCode] = New-Object System.Collections.Generic.List[object]
        }

        $exactGroups[$languageCode].Add([PSCustomObject]@{
            Format = $format
            Hints  = $hints
        })
    }

    if ($exactGroups.Count -eq 0) {
        return @()
    }

    $groupInfos = @()
    foreach ($languageCode in $exactGroups.Keys) {
        $items = @($exactGroups[$languageCode] | ForEach-Object { $_ })
        $primaryTag = Get-PrimaryLanguageTag -LanguageCode $languageCode
        $groupInfos += [PSCustomObject]@{
            LanguageCode = $languageCode
            PrimaryTag   = $primaryTag
            IsOriginal   = (@($items | Where-Object { $_.Hints.IsOriginal })).Count -gt 0
            IsDefault    = (@($items | Where-Object { $_.Hints.IsDefault })).Count -gt 0
            Specificity  = (@($languageCode -split '-')).Count
            ItemCount    = $items.Count
        }
    }

    $mergeTargetByCode = @{}
    foreach ($groupInfo in $groupInfos) {
        $mergeTargetByCode[$groupInfo.LanguageCode] = $groupInfo.LanguageCode
    }

    foreach ($primaryGroup in ($groupInfos | Group-Object -Property PrimaryTag)) {
        $groupCandidates = @($primaryGroup.Group)
        $canonical = $groupCandidates |
            Sort-Object `
                @{ Expression = { if ($_.IsOriginal) { 0 } elseif ($_.IsDefault) { 1 } else { 2 } } }, `
                @{ Expression = { -1 * $_.Specificity } }, `
                @{ Expression = { -1 * $_.ItemCount } }, `
                LanguageCode |
            Select-Object -First 1

        if ($canonical -and ($canonical.IsOriginal -or $canonical.IsDefault)) {
            foreach ($groupCandidate in $groupCandidates) {
                if ($groupCandidate.LanguageCode -ne $canonical.LanguageCode -and -not $groupCandidate.IsOriginal -and -not $groupCandidate.IsDefault) {
                    $mergeTargetByCode[$groupCandidate.LanguageCode] = $canonical.LanguageCode
                }
            }
        }
    }

    $mergedGroups = @{}
    foreach ($languageCode in $exactGroups.Keys) {
        $mergeTarget = $mergeTargetByCode[$languageCode]
        if (-not $mergedGroups.ContainsKey($mergeTarget)) {
            $mergedGroups[$mergeTarget] = New-Object System.Collections.Generic.List[object]
        }

        foreach ($item in @($exactGroups[$languageCode] | ForEach-Object { $_ })) {
            $mergedGroups[$mergeTarget].Add($item)
        }
    }

    $candidates = @()
    foreach ($languageCode in $mergedGroups.Keys) {
        $items = @($mergedGroups[$languageCode] | ForEach-Object { $_ })
        $representative = $items |
            Sort-Object `
                @{ Expression = { if ($_.Hints.IsOriginal) { 0 } elseif ($_.Hints.IsDefault) { 1 } elseif ($_.Hints.IsDubbed) { 2 } else { 3 } } }, `
                @{ Expression = { if ([string]::IsNullOrWhiteSpace($_.Hints.LanguageCode)) { 0 } else { -1 * (@($_.Hints.LanguageCode -split '-')).Count } } }, `
                @{ Expression = { if ($_.Hints.IsAudioOnly) { 0 } else { 1 } } } |
            Select-Object -First 1

        $bestAudioOnly = $items |
            Where-Object { $_.Hints.IsAudioOnly } |
            Sort-Object `
                @{ Expression = { if ($_.Hints.IsOriginal) { 0 } elseif ($_.Hints.IsDefault) { 1 } elseif ($_.Hints.IsDubbed) { 2 } else { 3 } } }, `
                @{ Expression = { if ($null -ne $_.Format.abr) { -1 * [double]$_.Format.abr } elseif ($null -ne $_.Format.tbr) { -1 * [double]$_.Format.tbr } else { 0 } } }, `
                @{ Expression = { if ($null -ne $_.Format.asr) { -1 * [double]$_.Format.asr } else { 0 } } } |
            Select-Object -First 1

        $bestCombined = $items |
            Where-Object { $_.Hints.IsMuxed } |
            Sort-Object `
                @{ Expression = { if ($_.Hints.IsOriginal) { 0 } elseif ($_.Hints.IsDefault) { 1 } elseif ($_.Hints.IsDubbed) { 2 } else { 3 } } }, `
                @{ Expression = { if ($null -ne $_.Format.height) { -1 * [double]$_.Format.height } else { 0 } } }, `
                @{ Expression = { if ($null -ne $_.Format.fps) { -1 * [double]$_.Format.fps } else { 0 } } }, `
                @{ Expression = { if ($null -ne $_.Format.tbr) { -1 * [double]$_.Format.tbr } else { 0 } } } |
            Select-Object -First 1

        $displayLanguageCode = if ($representative) { [string]$representative.Hints.LanguageCode } else { $languageCode }
        $displayName = Get-LanguageDisplayName -Code $displayLanguageCode
        if ([string]::IsNullOrWhiteSpace($displayName)) {
            $displayName = $displayLanguageCode
        }

        $candidateItems = @($items)
        $candidates += [PSCustomObject]@{
            LanguageCode      = $displayLanguageCode
            PrimaryLanguage   = Get-PrimaryLanguageTag -LanguageCode $displayLanguageCode
            DisplayName       = $displayName
            IsOriginal        = (@($candidateItems | Where-Object { $_.Hints.IsOriginal })).Count -gt 0
            IsDefault         = (@($candidateItems | Where-Object { $_.Hints.IsDefault })).Count -gt 0
            IsDubbed          = (@($candidateItems | Where-Object { $_.Hints.IsDubbed })).Count -gt 0
            AudioFormatId     = if ($bestAudioOnly) { [string]$bestAudioOnly.Format.format_id } else { "" }
            CombinedFormatId  = if ($bestCombined) { [string]$bestCombined.Format.format_id } else { "" }
            AvailableFormats  = @($candidateItems | ForEach-Object { [string]$_.Format.format_id } | Select-Object -Unique)
        }
    }

    $sortedCandidates = @(
        $candidates |
            Sort-Object `
                @{ Expression = { if ($_.IsOriginal) { 0 } elseif ($_.IsDefault) { 1 } else { 2 } } }, `
                DisplayName,
                LanguageCode
    )

    $originalCandidate = $sortedCandidates | Where-Object { $_.IsOriginal } | Select-Object -First 1
    $hasConfirmedOriginal = $null -ne $originalCandidate
    $originalPrimaryLanguage = if ($hasConfirmedOriginal) { $originalCandidate.PrimaryLanguage } else { "" }

    foreach ($candidate in $sortedCandidates) {
        $promptSuffix = ""
        $summarySuffix = ""

        if ($candidate.IsOriginal) {
            $promptSuffix = "original/source audio"
            $summarySuffix = "original/source"
        }
        elseif ($candidate.IsDubbed -or ($hasConfirmedOriginal -and $candidate.PrimaryLanguage -ne $originalPrimaryLanguage)) {
            $promptSuffix = "dubbed / translated"
            $summarySuffix = "dubbed/translated"
        }
        elseif ($candidate.IsDefault -and -not $hasConfirmedOriginal) {
            $promptSuffix = "provider default"
            $summarySuffix = "provider default; original/source could not be confirmed from provider metadata"
        }
        elseif ($hasConfirmedOriginal) {
            $promptSuffix = "alternate language track"
            $summarySuffix = "alternate language track"
        }
        else {
            $promptSuffix = "best effort"
            $summarySuffix = "best-effort; original/source could not be confirmed from provider metadata"
        }

        $selectorParts = New-Object System.Collections.Generic.List[string]
        if (-not [string]::IsNullOrWhiteSpace($candidate.AudioFormatId)) {
            $selectorParts.Add(("bv*+{0}" -f $candidate.AudioFormatId))
        }
        if (-not [string]::IsNullOrWhiteSpace($candidate.CombinedFormatId)) {
            $selectorParts.Add($candidate.CombinedFormatId)
        }
        if (-not [string]::IsNullOrWhiteSpace($candidate.LanguageCode)) {
            $selectorParts.Add(("bv*+ba[language={0}]" -f $candidate.LanguageCode))
            $selectorParts.Add(("b[language={0}]" -f $candidate.LanguageCode))
        }
        $selectorParts.Add("bv*+ba/b")

        $candidate | Add-Member -NotePropertyName PromptLabel -NotePropertyValue ("{0} ({1})" -f $candidate.DisplayName, $promptSuffix) -Force
        $candidate | Add-Member -NotePropertyName SummaryValue -NotePropertyValue ("{0} ({1})" -f $candidate.DisplayName, $summarySuffix) -Force
        $candidate | Add-Member -NotePropertyName FormatSelector -NotePropertyValue (($selectorParts | Select-Object -Unique) -join "/") -Force
    }

    return $sortedCandidates
}

function Get-YouTubeAudioTrackProbe {
    param(
        [string]$SourceUrl,
        [psobject]$YtDlpInvoker
    )

    try {
        $probeResult = Invoke-ExternalCapture `
            -FilePath $YtDlpInvoker.FilePath `
            -Arguments ($YtDlpInvoker.Arguments + @("-J", "--no-warnings", "--no-playlist", $SourceUrl)) `
            -StepName "yt-dlp audio-track probe" `
            -TimeoutSeconds 180

        $payload = $probeResult.StdOut | ConvertFrom-Json
        $trackCandidates = @(Get-RemoteAudioTrackCandidates -Formats @($payload.formats))

        return [PSCustomObject]@{
            ProbeOk         = $true
            Title           = [string]$payload.title
            TrackCandidates = $trackCandidates
        }
    }
    catch {
        Write-Log ("Unable to probe YouTube audio-track metadata before download: {0}" -f $_.Exception.Message) "WARN"
        return [PSCustomObject]@{
            ProbeOk         = $false
            Title           = ""
            TrackCandidates = @()
            Error           = $_.Exception.Message
        }
    }
}

function Select-YouTubeAudioTrackRequest {
    param(
        [psobject]$ProbeResult,
        [bool]$InteractiveMode
    )

    $trackCandidates = @()
    if ($ProbeResult -and $ProbeResult.TrackCandidates) {
        $trackCandidates = @($ProbeResult.TrackCandidates)
    }

    $recommendedTrack = $trackCandidates | Where-Object { $_.IsOriginal } | Select-Object -First 1

    if ($trackCandidates.Count -le 1) {
        if ($recommendedTrack) {
            return [PSCustomObject]@{
                Mode          = "explicit"
                RequestedTrack = $recommendedTrack
                LogLine       = ("Remote audio track request: {0} (auto-selected from provider metadata before download)" -f $recommendedTrack.SummaryValue)
            }
        }

        if ($trackCandidates.Count -eq 1) {
            return [PSCustomObject]@{
                Mode          = "auto"
                RequestedTrack = $null
                LogLine       = ("Remote audio track selection: best-effort; provider exposed one labeled track ({0}), but original/source could not be confirmed before download" -f $trackCandidates[0].DisplayName)
            }
        }

        return [PSCustomObject]@{
            Mode          = "auto"
            RequestedTrack = $null
            LogLine       = "Remote audio track selection: best-effort; provider did not expose usable multi-track metadata before download"
        }
    }

    if (-not $InteractiveMode) {
        if ($recommendedTrack) {
            return [PSCustomObject]@{
                Mode          = "explicit"
                RequestedTrack = $recommendedTrack
                LogLine       = ("Remote audio track request: {0} (auto-selected from provider metadata before download)" -f $recommendedTrack.SummaryValue)
            }
        }

        return [PSCustomObject]@{
            Mode          = "auto"
            RequestedTrack = $null
            LogLine       = "Remote audio track selection: best-effort; original/source track could not be confirmed from provider metadata before download"
        }
    }

    while ($true) {
        Write-Host ""
        Write-Host "This video appears to offer multiple audio tracks." -ForegroundColor Cyan
        Write-Host ""
        Write-Host "Available audio tracks:" -ForegroundColor Cyan

        $optionIndex = 1
        foreach ($trackCandidate in $trackCandidates) {
            $line = "{0}. {1}" -f $optionIndex, $trackCandidate.PromptLabel
            if ($recommendedTrack -and $trackCandidate.LanguageCode -eq $recommendedTrack.LanguageCode) {
                $line += "   [recommended]"
            }
            Write-Host $line -ForegroundColor Cyan
            $optionIndex += 1
        }

        $autoChoice = $optionIndex
        $cancelChoice = $optionIndex + 1
        Write-Host ("{0}. Auto pick best available" -f $autoChoice) -ForegroundColor Cyan
        Write-Host ("{0}. Cancel" -f $cancelChoice) -ForegroundColor Cyan
        Write-Host ""

        if ($recommendedTrack) {
            Write-Host "For transcript and translation quality, the original/source audio is usually the best choice." -ForegroundColor Cyan
        }
        else {
            Write-Host "Provider metadata did not clearly identify the original/source audio track, so Auto remains available." -ForegroundColor Yellow
        }

        $promptResult = Read-LineWithTimeout `
            -Prompt $(if ($recommendedTrack) {
                "Press Enter for the recommended track, choose 1-$cancelChoice, or wait 30 seconds to continue automatically with the recommended track."
            }
            else {
                "Press Enter for Auto, choose 1-$cancelChoice, or wait 30 seconds to continue automatically with Auto."
            }) `
            -TimeoutSeconds 30

        if ($promptResult.TimedOut) {
            if ($recommendedTrack) {
                return [PSCustomObject]@{
                    Mode           = "explicit"
                    RequestedTrack = $recommendedTrack
                    LogLine        = ("Audio-track prompt timed out after 30 seconds. Continuing with recommended track: {0}." -f $recommendedTrack.PromptLabel)
                }
            }

            return [PSCustomObject]@{
                Mode           = "auto"
                RequestedTrack = $null
                LogLine        = "Audio-track prompt timed out after 30 seconds. Continuing with Auto because provider metadata did not clearly confirm an original/source audio track."
            }
        }

        $choice = $promptResult.Value
        if ([string]::IsNullOrWhiteSpace($choice)) {
            if ($recommendedTrack) {
                return [PSCustomObject]@{
                    Mode          = "explicit"
                    RequestedTrack = $recommendedTrack
                    LogLine       = ("Remote audio track request: {0} (chosen interactively)" -f $recommendedTrack.SummaryValue)
                }
            }

            return [PSCustomObject]@{
                Mode          = "auto"
                RequestedTrack = $null
                LogLine       = "Remote audio track request: Auto pick best available"
            }
        }

        $parsedChoice = 0
        if (-not [int]::TryParse($choice.Trim(), [ref]$parsedChoice)) {
            Write-Host "Please enter one of the numbers shown in the list." -ForegroundColor Yellow
            continue
        }

        if ($parsedChoice -ge 1 -and $parsedChoice -le $trackCandidates.Count) {
            $selectedTrack = $trackCandidates[$parsedChoice - 1]
            return [PSCustomObject]@{
                Mode          = "explicit"
                RequestedTrack = $selectedTrack
                LogLine       = ("Remote audio track request: {0} (chosen interactively)" -f $selectedTrack.SummaryValue)
            }
        }

        if ($parsedChoice -eq $autoChoice) {
            return [PSCustomObject]@{
                Mode          = "auto"
                RequestedTrack = $null
                LogLine       = "Remote audio track request: Auto pick best available"
            }
        }

        if ($parsedChoice -eq $cancelChoice) {
            throw "User canceled remote audio-track selection."
        }

        Write-Host "Please enter one of the numbers shown in the list." -ForegroundColor Yellow
    }
}

function Get-RemoteAudioTrackInfoFromInfoJson {
    param(
        [string]$InfoJsonPath,
        [psobject[]]$ProbeTrackCandidates,
        [psobject]$RequestedTrack
    )

    if ([string]::IsNullOrWhiteSpace($InfoJsonPath) -or -not (Test-Path -LiteralPath $InfoJsonPath)) {
        return $null
    }

    try {
        $payload = Get-Content -LiteralPath $InfoJsonPath -Raw | ConvertFrom-Json
    }
    catch {
        Write-Log ("Unable to parse yt-dlp info JSON for audio-track details: {0}" -f $_.Exception.Message) "WARN"
        return $null
    }

    $selectedFormats = New-Object System.Collections.Generic.List[object]
    foreach ($selectedFormat in @($payload.requested_formats)) {
        if ($null -ne $selectedFormat) {
            $selectedFormats.Add($selectedFormat)
        }
    }

    if ($selectedFormats.Count -eq 0) {
        foreach ($requestedDownload in @($payload.requested_downloads)) {
            foreach ($selectedFormat in @($requestedDownload.requested_formats)) {
                if ($null -ne $selectedFormat) {
                    $selectedFormats.Add($selectedFormat)
                }
            }
        }
    }

    if ($selectedFormats.Count -eq 0 -and $payload.PSObject.Properties['acodec'] -and [string]$payload.acodec -ne "none") {
        $selectedFormats.Add($payload)
    }

    $selectedCandidates = @(Get-RemoteAudioTrackCandidates -Formats @($selectedFormats | ForEach-Object { $_ }))
    if ($selectedCandidates.Count -eq 0) {
        return $null
    }

    $selectedTrack = $selectedCandidates | Select-Object -First 1
    $referenceCandidates = if ($ProbeTrackCandidates -and @($ProbeTrackCandidates).Count -gt 0) { @($ProbeTrackCandidates) } else { $selectedCandidates }
    $referenceOriginal = $referenceCandidates | Where-Object { $_.IsOriginal } | Select-Object -First 1
    $hasConfirmedOriginal = $null -ne $referenceOriginal

    $summaryValue = $selectedTrack.SummaryValue
    if ($selectedTrack.IsOriginal) {
        $summaryValue = ("{0} (original/source)" -f $selectedTrack.DisplayName)
    }
    elseif ($selectedTrack.IsDubbed -or ($hasConfirmedOriginal -and $selectedTrack.PrimaryLanguage -ne $referenceOriginal.PrimaryLanguage)) {
        $summaryValue = ("{0} (dubbed/translated)" -f $selectedTrack.DisplayName)
    }
    elseif ($selectedTrack.IsDefault -and -not $hasConfirmedOriginal) {
        $summaryValue = ("{0} (provider default; original/source could not be confirmed from provider metadata)" -f $selectedTrack.DisplayName)
    }
    elseif (-not $hasConfirmedOriginal) {
        $summaryValue = ("{0} (best-effort; original/source could not be confirmed from provider metadata)" -f $selectedTrack.DisplayName)
    }

    $mismatchWarning = ""
    if ($RequestedTrack -and -not [string]::IsNullOrWhiteSpace($RequestedTrack.LanguageCode)) {
        if ($RequestedTrack.LanguageCode -ne $selectedTrack.LanguageCode) {
            $mismatchWarning = ("Requested remote audio track: {0}; provider actually delivered: {1}" -f $RequestedTrack.SummaryValue, $summaryValue)
        }
    }

    return [PSCustomObject]@{
        LanguageCode     = $selectedTrack.LanguageCode
        DisplayName      = $selectedTrack.DisplayName
        SummaryValue     = $summaryValue
        SummaryLine      = ("Remote audio track selected: {0}" -f $summaryValue)
        MismatchWarning  = $mismatchWarning
    }
}

function Quote-Argument {
    param([string]$Value)

    if ($null -eq $Value) { return '""' }
    if ($Value -eq "") { return '""' }

    if ($Value -match '[\s"]') {
        return '"' + ($Value -replace '"', '\"') + '"'
    }

    return $Value
}

function Read-ProgressStateFile {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path)) {
        return $null
    }

    try {
        $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
        if ([string]::IsNullOrWhiteSpace($raw)) {
            return $null
        }

        $parsed = $raw | ConvertFrom-Json
        $updatedAtUtc = $null
        if ($parsed.updated_at_utc) {
            try {
                $updatedAtUtc = [datetime]::Parse([string]$parsed.updated_at_utc).ToUniversalTime()
            }
            catch {
                $updatedAtUtc = $null
            }
        }

        if ($null -eq $updatedAtUtc) {
            $updatedAtUtc = (Get-Item -LiteralPath $Path).LastWriteTimeUtc
        }

        return [PSCustomObject]@{
            Schema         = [string]$parsed.schema
            Stage          = [string]$parsed.stage
            Message        = [string]$parsed.message
            Phase          = [string]$parsed.phase
            ProgressKind   = [string]$parsed.progress_kind
            Activity       = [string]$parsed.activity
            SourceName     = [string]$parsed.source_name
            SourceCompleted = [int]$parsed.source_completed
            SourceTotal    = [int]$parsed.source_total
            SourceOrdinal  = [int]$parsed.source_ordinal
            SourceState    = [string]$parsed.source_state
            SourceTerminal = [bool]$parsed.source_terminal
            PreparedCount  = [int]$parsed.prepared_count
            BlockedCount   = [int]$parsed.blocked_count
            FailedCount    = [int]$parsed.failed_count
            TerminalState  = [string]$parsed.terminal_state
            ElapsedSeconds = [double]$parsed.elapsed_seconds
            UpdatedAtUtc   = $updatedAtUtc
            Device         = [string]$parsed.device
            SelectedDevice = [string]$parsed.selected_device
            RequestedDevice = [string]$parsed.requested_device
            DeviceEvent    = [string]$parsed.device_event
            DeviceSwitchCount = [int]$parsed.device_switch_count
            GpuError       = [string]$parsed.gpu_error
            ModelName      = [string]$parsed.model_name
            TaskName       = [string]$parsed.task_name
            # 214: the screenshots made so far, from the one frame renderer.
            HasArtifactCounts = ($null -ne $parsed.PSObject.Properties["artifact_total"])
            PhaseIndex     = [int]$parsed.phase_index
            PhaseCount     = [int]$parsed.phase_count
            SourceId       = [string]$parsed.source_id
            Completed      = [long]$parsed.completed
            Total          = [long]$parsed.total
            WorkUnit       = [string]$parsed.work_unit
            ArtifactCompleted = [int]$parsed.artifact_completed
            ArtifactTotal  = [int]$parsed.artifact_total
            LatestArtifactPath = [string]$parsed.latest_artifact_path
        }
    }
    catch {
        return $null
    }
}

function Get-ProgressDeviceValue {
    param([psobject]$ProgressState)

    if ($null -eq $ProgressState) {
        return ""
    }

    if (-not [string]::IsNullOrWhiteSpace($ProgressState.SelectedDevice) -and $ProgressState.SelectedDevice -ne "pending") {
        return [string]$ProgressState.SelectedDevice
    }

    if (-not [string]::IsNullOrWhiteSpace($ProgressState.Device) -and $ProgressState.Device -ne "pending") {
        return [string]$ProgressState.Device
    }

    return ""
}

function Get-ProgressDeviceTag {
    param([string]$Device)

    if ([string]::IsNullOrWhiteSpace($Device)) {
        return ""
    }

    switch ($Device.Trim().ToLowerInvariant()) {
        "cuda" { return "[GPU]" }
        "gpu"  { return "[GPU]" }
        "cpu"  { return "[CPU]" }
        default { return "" }
    }
}

function Get-ProgressStateSummary {
    param([psobject]$ProgressState)

    if ($null -eq $ProgressState) {
        return ""
    }

    $parts = New-Object System.Collections.Generic.List[string]
    $deviceValue = Get-ProgressDeviceValue -ProgressState $ProgressState
    $deviceTag = Get-ProgressDeviceTag -Device $deviceValue
    if (-not [string]::IsNullOrWhiteSpace($deviceTag)) {
        [void]$parts.Add($deviceTag)
    }
    if (-not [string]::IsNullOrWhiteSpace($ProgressState.Stage)) {
        [void]$parts.Add(("stage {0}" -f $ProgressState.Stage))
    }
    if (-not [string]::IsNullOrWhiteSpace($ProgressState.Message)) {
        [void]$parts.Add([string]$ProgressState.Message)
    }
    if (-not [string]::IsNullOrWhiteSpace($deviceValue)) {
        [void]$parts.Add(("device {0}" -f $deviceValue))
    }

    return ($parts -join "; ")
}

function Get-ProgressStateSignature {
    param([psobject]$ProgressState)

    if ($null -eq $ProgressState) {
        return ""
    }

    if ([string]$ProgressState.Schema -eq "MM_PROGRESS_V1") {
        # 224 (Wave B2a): with the work done so far and the activity line, so a step's progress and a
        # warning said during the same step reach the Workbench too.
        return ("{0}|{1}|{2}|{3}|{4}|{5}|{6}|{7}|{8}|{9}|{10}|{11}|{12}" -f `
            [string]$ProgressState.Phase, `
            [int]$ProgressState.ArtifactCompleted, `
            [string]$ProgressState.SourceName, `
            [int]$ProgressState.SourceCompleted, `
            [int]$ProgressState.SourceOrdinal, `
            [string]$ProgressState.SourceState, `
            [bool]$ProgressState.SourceTerminal, `
            [int]$ProgressState.PreparedCount, `
            [int]$ProgressState.BlockedCount, `
            [int]$ProgressState.FailedCount, `
            [string]$ProgressState.ProgressKind, `
            [long]$ProgressState.Completed, `
            [string]$ProgressState.Activity)
    }

    return ("{0}|{1}|{2}|{3}|{4}|{5}" -f `
        [string]$ProgressState.Stage, `
        [string]$ProgressState.Message, `
        (Get-ProgressDeviceValue -ProgressState $ProgressState), `
        [string]$ProgressState.DeviceEvent, `
        [int]$ProgressState.DeviceSwitchCount, `
        [string]$ProgressState.GpuError)
}

function Get-ExternalFailureSummary {
    param(
        [string]$StdOut,
        [string]$StdErr,
        [int]$MaximumLength = 500
    )

    $lines = @(
        @($StdErr -split "`r?`n") +
        @($StdOut -split "`r?`n") |
            ForEach-Object { ([string]$_).Trim() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($lines.Count -eq 0) {
        return ""
    }

    $priorityLines = @($lines | Where-Object {
        $_ -match '(?i)(^ERROR:|HTTP Error|video unavailable|sign in|requested format|unable to download|not available|unsupported URL|access denied|forbidden)'
    })
    $summary = if ($priorityLines.Count -gt 0) {
        [string]$priorityLines[-1]
    }
    else {
        [string]$lines[-1]
    }

    $summary = ($summary -replace '\s+', ' ').Trim()
    if ($summary.Length -gt $MaximumLength) {
        $summary = $summary.Substring(0, $MaximumLength - 3).TrimEnd() + "..."
    }

    return $summary
}

function Get-MMRunControl {
    # 114/115: the Workbench's skip/pause requests. Read at most once a
    # second; a half-written file keeps the last good state.
    if ([string]::IsNullOrWhiteSpace($script:MMRunControlPath)) { return $null }
    $now = Get-Date
    if ($null -ne $script:MMRunControlCache -and ($now - $script:MMRunControlReadAt).TotalMilliseconds -lt 1000) {
        return $script:MMRunControlCache
    }
    $script:MMRunControlReadAt = $now
    $control = [PSCustomObject]@{ pause = $false; skip = @() }
    if (Test-Path -LiteralPath $script:MMRunControlPath -PathType Leaf) {
        try {
            $raw = [System.IO.File]::ReadAllText($script:MMRunControlPath)
            if (-not [string]::IsNullOrWhiteSpace($raw)) {
                $parsed = $raw | ConvertFrom-Json
                $control.pause = [bool]$parsed.pause
                $control.skip = @(@($parsed.skip) | ForEach-Object { [string]$_ } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
            }
        }
        catch {
            if ($null -ne $script:MMRunControlCache) { return $script:MMRunControlCache }
        }
    }
    $script:MMRunControlCache = $control
    return $control
}

function Test-MMSourceSkipRequested {
    param([string]$SourcePath)
    if ([string]::IsNullOrWhiteSpace($SourcePath)) { return $false }
    $control = Get-MMRunControl
    if ($null -eq $control) { return $false }
    foreach ($item in @($control.skip)) {
        if ([string]::Equals([string]$item, $SourcePath, [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
    }
    return $false
}

function Test-MMPauseRequested {
    $control = Get-MMRunControl
    return [bool]($null -ne $control -and $control.pause)
}

function Test-MMSkipException {
    param($ErrorRecord)
    $message = if ($ErrorRecord -is [System.Management.Automation.ErrorRecord]) { [string]$ErrorRecord.Exception.Message } else { [string]$ErrorRecord }
    return $message.StartsWith([string]$script:MMSkipMessagePrefix)
}

function Get-MMProcessTreeIds {
    param([int]$RootId)
    $ids = New-Object System.Collections.Generic.List[int]
    [void]$ids.Add($RootId)
    try {
        $all = @(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop | Select-Object ProcessId, ParentProcessId)
        $queue = New-Object System.Collections.Generic.Queue[int]
        $queue.Enqueue($RootId)
        while ($queue.Count -gt 0) {
            $parent = $queue.Dequeue()
            foreach ($candidate in $all) {
                $childId = [int]$candidate.ProcessId
                if ([int]$candidate.ParentProcessId -eq $parent -and -not $ids.Contains($childId)) {
                    [void]$ids.Add($childId)
                    $queue.Enqueue($childId)
                }
            }
        }
    }
    catch {
        # Without the process list only the direct child is controlled.
    }
    return @($ids.ToArray())
}

function Stop-MMProcessTree {
    param([System.Diagnostics.Process]$Process)
    if ($null -eq $Process) { return }
    try {
        if (-not $Process.HasExited) { & taskkill.exe /PID $Process.Id /T /F 2>&1 | Out-Null }
    }
    catch { }
    try {
        if (-not $Process.HasExited) { $Process.Kill() }
    }
    catch { }
}

function Set-MMProcessTreeSuspended {
    param(
        [System.Diagnostics.Process]$Process,
        [bool]$Suspended
    )
    if ($null -eq $Process) { return }
    if (-not ("MediaManglers.ProcessControl" -as [type])) {
        Add-Type -Namespace MediaManglers -Name ProcessControl -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("ntdll.dll")] public static extern int NtSuspendProcess(System.IntPtr processHandle);
[System.Runtime.InteropServices.DllImport("ntdll.dll")] public static extern int NtResumeProcess(System.IntPtr processHandle);
'@
    }
    foreach ($id in @(Get-MMProcessTreeIds -RootId $Process.Id)) {
        try {
            $member = [System.Diagnostics.Process]::GetProcessById($id)
            if ($Suspended) {
                [void][MediaManglers.ProcessControl]::NtSuspendProcess($member.Handle)
            }
            else {
                [void][MediaManglers.ProcessControl]::NtResumeProcess($member.Handle)
            }
        }
        catch { }
    }
}

function Wait-MMWhilePaused {
    # 115: hold here while the operator has paused the run. A running tool
    # is suspended, so it stops using the CPU and GPU until Resume.
    param(
        [System.Diagnostics.Process]$Process = $null,
        [string]$Where = ""
    )
    if (-not (Test-MMPauseRequested)) { return 0.0 }
    $pausedAt = Get-Date
    if ($null -ne $Process) { Set-MMProcessTreeSuspended -Process $Process -Suspended $true }
    # 201: and a small review copy being made alongside the transcription.
    $backgroundTools = @(if ($null -ne $script:MMBackgroundReviewVideos) { foreach ($entry in @($script:MMBackgroundReviewVideos.Values)) { if ($entry.Status -eq "running" -and -not $entry.Process.HasExited) { $entry.Process } } })
    foreach ($tool in $backgroundTools) { Set-MMProcessTreeSuspended -Process $tool -Suspended $true }
    $whereText = if ([string]::IsNullOrWhiteSpace($Where)) { "" } else { " during $Where" }
    # 214: the operator's own choice, not a warning; a paused run still ends green.
    Write-Log ("Paused by you{0}. The run continues when you press Resume." -f $whereText) "INFO"
    Write-Host "  Paused. Press Resume in the Workbench to continue." -ForegroundColor Yellow
    $nextBeat = Get-Date
    try {
        while (Test-MMPauseRequested) {
            if ((Get-Date) -ge $nextBeat) {
                # 224 (Wave B2b): a pause is a state of its own, so it says so (a heartbeat would keep the step's words).
                Write-MMProgressV1 -Phase ([string]$script:MMProgressPhase) -ProgressKind indeterminate -Activity "Paused by you"
                $nextBeat = (Get-Date).AddSeconds(10)
            }
            if (-not [string]::IsNullOrWhiteSpace($script:MMCurrentSourcePath) -and (Test-MMSourceSkipRequested -SourcePath $script:MMCurrentSourcePath)) {
                break
            }
            Start-Sleep -Milliseconds 500
        }
    }
    finally {
        if ($null -ne $Process) { Set-MMProcessTreeSuspended -Process $Process -Suspended $false }
        foreach ($tool in $backgroundTools) { Set-MMProcessTreeSuspended -Process $tool -Suspended $false }
    }
    $script:MMLastResumeAt = Get-Date
    $pausedSeconds = ((Get-Date) - $pausedAt).TotalSeconds
    Write-Log ("Resumed after a pause of {0}." -f (Format-DurationHuman -Seconds $pausedSeconds))
    Write-MMProgressV1 -Phase ([string]$script:MMProgressPhase) -ProgressKind indeterminate -Activity "Resumed"
    return $pausedSeconds
}

function Invoke-MMRunControlCheck {
    # 114/115: called while a tool runs. Skipping the current recording
    # stops the tool at once (no CPU retry); pausing suspends it.
    param(
        [System.Diagnostics.Process]$Process = $null,
        [string]$StepName = ""
    )
    if ([string]::IsNullOrWhiteSpace($script:MMRunControlPath)) { return 0.0 }
    $paused = 0.0
    if (-not (Test-MMSourceSkipRequested -SourcePath $script:MMCurrentSourcePath)) {
        $paused = Wait-MMWhilePaused -Process $Process -Where $StepName
    }
    if (Test-MMSourceSkipRequested -SourcePath $script:MMCurrentSourcePath) {
        Stop-MMProcessTree -Process $Process
        $script:MMSkipRequested = $true
        throw ("{0}: skipped by you ({1})." -f $script:MMSkipMessagePrefix, [System.IO.Path]::GetFileName($script:MMCurrentSourcePath))
    }
    return $paused
}

function Test-MMCompleteJpeg {
    # 115: a screenshot from an earlier, interrupted run is reused only when
    # it is a whole JPEG (ends with the FFD9 end-of-image marker).
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    try {
        $stream = [System.IO.File]::OpenRead($Path)
        try {
            if ($stream.Length -lt 4) { return $false }
            [void]$stream.Seek(-2, [System.IO.SeekOrigin]::End)
            $first = $stream.ReadByte()
            $second = $stream.ReadByte()
            return ($first -eq 0xFF -and $second -eq 0xD9)
        }
        finally {
            $stream.Dispose()
        }
    }
    catch {
        return $false
    }
}

function Test-MMNonEmptyFile {
    param([string]$Path)
    return (-not [string]::IsNullOrWhiteSpace($Path)) -and (Test-Path -LiteralPath $Path -PathType Leaf) -and ((Get-Item -LiteralPath $Path).Length -gt 0)
}

function Resolve-MMNarrationTranscriptionDefaults {
    # 214: one rule for the narrated-recording features (Find my bug reports, with its racing
    # preset, and Review Media Inbox, which only takes the operator's narrated recordings): a blank
    # language is English and Auto speech is Sparse, so Whisper does not guess the language from a
    # quiet opening (it wrote Nynorsk for one).
    param([string]$Language, [string]$NarrationSpeechMode = "Auto", [string]$ProfileName = "", [switch]$NarratedRecordings)
    $language = $Language
    $speechMode = if ([string]::IsNullOrWhiteSpace($NarrationSpeechMode)) { "Auto" } else { $NarrationSpeechMode }
    if ($NarratedRecordings -or $ProfileName -match '(?i)iRacing') {
        if ([string]::IsNullOrWhiteSpace($language)) { $language = "en" }
        if ($speechMode -eq "Auto") { $speechMode = "Sparse" }
    }
    return [PSCustomObject]@{ Language = $language; NarrationSpeechMode = $speechMode }
}

function ConvertTo-MMTrackRoles {
    # 196: "2=narration,3=never" -> @{ "2" = "narration"; "3" = "never" }. Auto and anything
    # unreadable are left out, so a blank setting is every track Auto. 220: "full_mix" is kept: the
    # narration choice treats it as a track named "Full Mix", used only when nothing else qualifies.
    param([string]$Text)
    $roles = @{}
    foreach ($part in @(([string]$Text) -split "[,;]")) {
        $pair = $part.Split("=", 2)
        if ($pair.Count -ne 2) { continue }
        $number = 0
        $role = $pair[1].Trim().ToLowerInvariant()
        # 220: "Game audio" is a kind of Never narration; for the narration choice it is exactly that.
        if ($role -eq "game") { $role = "never" }
        if ([int]::TryParse($pair[0].Trim(), [ref]$number) -and $number -ge 1 -and $role -in @("narration", "never", "full_mix")) {
            $roles[[string]$number] = $role
        }
    }
    return $roles
}

function Get-MMTrackRolesKey {
    # The setting in one fixed form, "2=narration,3=never", for the saved voice-track result.
    param([hashtable]$Roles)
    if ($null -eq $Roles) { return "" }
    return (@($Roles.Keys | Sort-Object { [int]$_ } | ForEach-Object { "{0}={1}" -f $_, $Roles[$_] }) -join ",")
}

function Read-MMSavedVoiceDetection {
    # 115: reuse the voice-track result from an earlier run of this package
    # when the recording is unchanged.
    param([string]$Path, [string]$VideoPath, [int[]]$PreferredOrdinals = @(), [string]$TrackRolesKey = "")
    # The selection rule this build's detector uses: voice_track.VOICE_RULE_VERSION.
    $voiceRuleVersion = 5
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    try {
        $saved = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
        $item = Get-Item -LiteralPath $VideoPath
        if ([int64]$saved.source_size -ne [int64]$item.Length -or [string]$saved.source_modified_utc -ne $item.LastWriteTimeUtc.ToString("o")) {
            return $null
        }
        if ($null -eq $saved.detection -or [string]::IsNullOrWhiteSpace([string]$saved.detection.status)) { return $null }
        # 196: a result is this build's answer only when the same selection
        # rule made it with the same usual microphone track, which breaks ties.
        # Anything older is heard again, a track it chose included: a track
        # chosen under another rule is not what this rule would choose (142
        # found older results calling speech no narration).
        if ([string]$saved.schema -ne "mm-voice-detection-v4" -or [string]$saved.rule_version -ne [string]$voiceRuleVersion) {
            return $null
        }
        $savedPreferred = @($saved.preferred_ordinals | Where-Object { $null -ne $_ } | ForEach-Object { [int]$_ })
        if (($savedPreferred -join ",") -ne (@($PreferredOrdinals) -join ",")) {
            return $null
        }
        # 196: and only with the same per-track narration setting.
        $savedRoles = if ($null -ne $saved.PSObject.Properties["track_roles"]) { [string]$saved.track_roles } else { "" }
        if ($savedRoles -ne [string]$TrackRolesKey) {
            return $null
        }
        return $saved.detection
    }
    catch {
        return $null
    }
}

function Get-MMTranscriptSidePath {
    # <name>.transcript.json -> <name>.transcript.<Kind>.json, beside it.
    param([string]$JsonPath, [string]$Kind)
    return (Join-Path (Split-Path -Path $JsonPath -Parent) (([System.IO.Path]::GetFileNameWithoutExtension($JsonPath)) + ".$Kind.json"))
}

function Get-MMTranscribedTrack {
    # The audio ordinal a transcript was made from, as recorded when it was
    # made, or $null when nothing was recorded (142).
    param([string]$JsonPath)
    $trackPath = Get-MMTranscriptSidePath -JsonPath $JsonPath -Kind "track"
    if (-not (Test-Path -LiteralPath $trackPath -PathType Leaf)) { return $null }
    try {
        $value = (Get-Content -LiteralPath $trackPath -Raw -Encoding UTF8 | ConvertFrom-Json).audio_ordinal
        if ($null -eq $value) { return $null }
        return [int]$value
    }
    catch {
        return $null
    }
}

function Test-MMTranscribedTriple {
    # A transcript triple counts as done work only when this backend made it
    # from the track wanted now (142). The package writer leaves an empty
    # triple for every recording it could not transcribe, and a Continue can
    # follow the operator choosing a different track; reusing either would
    # report the track they chose without ever listening to it. A transcript
    # made before its track was recorded is trusted when Whisper's own
    # <name>.quality.json is beside it, which the package writer never writes.
    # With -RequireTrackRecord (the operator named the track) a transcript
    # with no record of its track is never trusted: it may be another one's.
    param([string]$JsonPath, [string]$SrtPath, [string]$TxtPath, [int]$AudioOrdinal = -1, [switch]$RequireTrackRecord)
    if (-not ((Test-Path -LiteralPath $JsonPath) -and (Test-Path -LiteralPath $SrtPath) -and (Test-Path -LiteralPath $TxtPath))) {
        return $false
    }
    $madeFrom = Get-MMTranscribedTrack -JsonPath $JsonPath
    if ($null -ne $madeFrom) {
        return ($AudioOrdinal -lt 0 -or $madeFrom -eq $AudioOrdinal)
    }
    if ($RequireTrackRecord) {
        return $false
    }
    return (Test-Path -LiteralPath (Get-MMTranscriptSidePath -JsonPath $JsonPath -Kind "quality") -PathType Leaf)
}

function Set-MMTranscribedTrack {
    param([string]$JsonPath, [int]$AudioOrdinal)
    $trackPath = Get-MMTranscriptSidePath -JsonPath $JsonPath -Kind "track"
    $payload = [ordered]@{ schema_version = 1; audio_ordinal = $AudioOrdinal; human_track_number = $AudioOrdinal + 1 }
    [System.IO.File]::WriteAllText($trackPath, ($payload | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))
}

function Remove-MMTranscriptFiles {
    # Everything a transcription leaves beside its triple, so nothing of an
    # old one can pass for the new one: the side files mark finished work.
    param([string]$JsonPath, [string]$SrtPath, [string]$TxtPath, [string[]]$AudioPaths = @())
    $paths = @($JsonPath, $SrtPath, $TxtPath) + @("quality", "raw", "vad", "track" | ForEach-Object { Get-MMTranscriptSidePath -JsonPath $JsonPath -Kind $_ }) + @($AudioPaths)
    foreach ($path in $paths) {
        if (-not [string]::IsNullOrWhiteSpace($path) -and (Test-Path -LiteralPath $path)) {
            Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
        }
    }
}

function Remove-MMSkippedRecordingFiles {
    # 196: nothing from a recording the operator skipped goes into the
    # package: not its transcript or the files beside it, not its voice-track
    # result, not its audio. Only the package's own copies are removed; a
    # Full Review transcript reused from elsewhere is left alone.
    param([string]$TranscriptFolder, [string]$AudioFolder, [string]$PhysicalSourceId)
    if ([string]::IsNullOrWhiteSpace($PhysicalSourceId)) { return }
    $base = Join-Path $TranscriptFolder $PhysicalSourceId
    # And the raw copy of what Whisper heard an earlier writing of the package
    # kept beside them (transcript\raw\sources).
    $rawBase = Join-Path (Join-Path (Join-Path (Split-Path -Path $TranscriptFolder -Parent) "raw") "sources") $PhysicalSourceId
    Remove-MMTranscriptFiles -JsonPath ($base + ".transcript.json") -SrtPath ($base + ".transcript.srt") -TxtPath ($base + ".transcript.txt") -AudioPaths @(
        ($base + ".voice.json"),
        (Join-Path $AudioFolder ("{0}.audio.wav" -f $PhysicalSourceId)),
        (Join-Path $AudioFolder ("{0}.audio.flac" -f $PhysicalSourceId)),
        ($rawBase + ".transcript.json"),
        ($rawBase + ".transcript.srt"),
        ($rawBase + ".transcript.txt")
    )
}

function Set-MMSkippedAfterTranscription {
    # 114/196: a recording the operator skipped after its transcript was
    # written is marked skipped and its files are removed, so it is left out
    # of the package. Returns the recordings skipped since the last check.
    param([array]$Entries, [string]$TranscriptFolder, [string]$AudioFolder, [string]$LogMessage)
    # Read the Workbench's requests afresh: a skip pressed in the last second
    # before this check must not be missed for the copy read a moment ago.
    $script:MMRunControlCache = $null
    $newlySkipped = New-Object System.Collections.Generic.List[object]
    foreach ($entry in @($Entries)) {
        if ($null -eq $entry -or [string]$entry.status -eq "operator_skipped") { continue }
        if (-not (Test-MMSourceSkipRequested -SourcePath ([string]$entry.source_path))) { continue }
        $entry.status = "operator_skipped"
        $entry.error_message = "Skipped by you."
        Remove-MMSkippedRecordingFiles -TranscriptFolder $TranscriptFolder -AudioFolder $AudioFolder -PhysicalSourceId ([string]$entry.physical_source_id)
        Write-Log ($LogMessage -f [string]$entry.source_path) "WARN"
        [void]$newlySkipped.Add($entry)
    }
    return @($newlySkipped.ToArray())
}

function Remove-MMRenderedEvidence {
    # 196: what was rendered for the package before a recording was skipped.
    # Every ticket's folder goes, not only the skipped recording's: without
    # it the tickets are numbered again, and a ticket must not reuse the
    # screenshots another ticket left under its new number.
    param([string]$OutputRoot, $DetectResult, [array]$SkippedEntries = @())
    # A ticket or recording id names one folder, never a path above it.
    $isOneName = { param([string]$Name) -not [string]::IsNullOrWhiteSpace($Name) -and $Name -notin @(".", "..") -and $Name.IndexOfAny([System.IO.Path]::GetInvalidFileNameChars()) -lt 0 }
    if ($null -ne $DetectResult) {
        foreach ($candidate in @(@($DetectResult.render_candidates) + @($DetectResult.unrendered_candidates))) {
            $evidenceId = if ($null -ne $candidate) { [string]$candidate.evidence_id } else { "" }
            if (& $isOneName $evidenceId) {
                Remove-MMScratchPath -Path (Join-Path (Join-Path $OutputRoot "evidence_items") $evidenceId)
            }
        }
    }
    foreach ($entry in @($SkippedEntries)) {
        $sourceId = if ($null -ne $entry) { [string]$entry.source_id } else { "" }
        if (& $isOneName $sourceId) {
            Remove-MMScratchPath -Path (Join-Path (Join-Path (Join-Path $OutputRoot "artifacts") "narration") $sourceId)
        }
    }
}

function Remove-MMUnbuiltPackage {
    # 196: no package is built this time and recordings were skipped. What
    # an earlier run of this package wrote (tickets, rendered media, reports,
    # the portable ZIP) holds them, and must not be left looking current.
    # Kept: the transcripts and audio of the recordings not skipped (the
    # skipped ones' are already gone), with the raw copy of what Whisper
    # heard (on a Continue the only one), the run log and the stage manifest,
    # so a Continue can still use them.
    param([string]$OutputRoot)
    if ([string]::IsNullOrWhiteSpace($OutputRoot) -or -not (Test-Path -LiteralPath $OutputRoot -PathType Container)) { return 0 }
    $removed = 0
    $keep = @("transcript", "audio", "codex_evidence_run.log", "WORKFLOW3_STAGE_MANIFEST.json")
    $items = @(Get-ChildItem -LiteralPath $OutputRoot -Force -ErrorAction SilentlyContinue | Where-Object { $keep -notcontains $_.Name })
    $transcriptRoot = Join-Path $OutputRoot "transcript"
    if (Test-Path -LiteralPath $transcriptRoot -PathType Container) {
        $items += @(Get-ChildItem -LiteralPath $transcriptRoot -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -notin @("sources", "raw") })
    }
    $rawRoot = Join-Path $transcriptRoot "raw"
    if (Test-Path -LiteralPath $rawRoot -PathType Container) {
        $items += @(Get-ChildItem -LiteralPath $rawRoot -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne "sources" })
    }
    foreach ($item in $items) {
        Remove-MMScratchPath -Path $item.FullName
        $removed += 1
    }
    return $removed
}

function Save-MMVoiceDetection {
    param([string]$Path, [string]$VideoPath, $Detection, [int[]]$PreferredOrdinals = @(), [string]$TrackRolesKey = "")
    if ($null -eq $Detection) { return }
    try {
        $item = Get-Item -LiteralPath $VideoPath
        Ensure-Directory (Split-Path -Path $Path -Parent)
        # 196: the audio detection kept is used once and then gone, so a
        # saved verdict never names it.
        if ($null -ne $Detection.PSObject.Properties["kept_track_wavs"]) {
            $Detection = $Detection | Select-Object -Property * -ExcludeProperty kept_track_wavs
        }
        # 196: nor what was heard on each track. The saved result sits in the package, and the
        # portable ZIP takes it, so a teammate's or a full mix's words would go with it.
        if ($null -ne $Detection.PSObject.Properties["tracks"]) {
            $savedTracks = @(@($Detection.tracks) | Where-Object { $null -ne $_ } | ForEach-Object {
                $_ | Select-Object -Property * -ExcludeProperty sample_text
            })
            $Detection = $Detection | Select-Object -Property * -ExcludeProperty tracks
            $Detection | Add-Member -NotePropertyName tracks -NotePropertyValue $savedTracks
        }
        $payload = [ordered]@{
            schema = "mm-voice-detection-v4"
            # 196: the rule that made it and the usual track it was given, so a
            # later run reuses it only for the same decision.
            rule_version = $Detection.rule_version
            preferred_ordinals = @($PreferredOrdinals)
            track_roles = [string]$TrackRolesKey
            source_size = [int64]$item.Length
            source_modified_utc = $item.LastWriteTimeUtc.ToString("o")
            detection = $Detection
        }
        [System.IO.File]::WriteAllText($Path, ($payload | ConvertTo-Json -Depth 12), (New-Object System.Text.UTF8Encoding($false)))
    }
    catch {
        Write-Log ("Could not save the voice-track result for reuse: {0}" -f $_.Exception.Message) "WARN"
    }
}

function New-MMSkippedFrameResult {
    param($Task)
    $panels = @(foreach ($panel in @($Task.panels)) {
        if ($null -eq $panel) { continue }
        [PSCustomObject]@{
            role = [string]$panel.role; label = [string]$panel.label; relative_path = [string]$panel.relative_path; path = [string]$panel.path
            crop_x = [int]$panel.crop_x; crop_y = [int]$panel.crop_y; crop_width = [int]$panel.crop_width; crop_height = [int]$panel.crop_height
            panel_image_width = ""; panel_image_height = ""; status = "failed"; error_message = "Skipped by you."
        }
    })
    return [PSCustomObject]@{
        evidence_id = [string]$Task.evidence_id; relative_path = [string]$Task.relative_path; path = [string]$Task.path; full_frame_path = [string]$Task.path
        full_frame_width = ""; full_frame_height = ""; panel_crop_mode = "auto"; panel_detection = "not_attempted"
        panels = $panels; status = "failed"; error_message = "Skipped by you."
    }
}

function New-MMSkippedArtifactResult {
    param($Task)
    return [PSCustomObject]@{
        evidence_id = [string]$Task.evidence_id; relative_path = [string]$Task.relative_path; path = [string]$Task.path
        status = "failed"; error_message = "Skipped by you."
    }
}

function Remove-MMScratchPath {
    # Removes a temporary file or folder. A tool that was just stopped can
    # hold its files for a moment, so this tries again briefly.
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return }
    for ($attempt = 0; $attempt -lt 10 -and (Test-Path -LiteralPath $Path); $attempt++) {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $Path) { Start-Sleep -Milliseconds 200 }
    }
}

function Get-MMScratchPath {
    # 196: a new path for a short-lived work file or folder. It goes in the
    # operating system's temp folder, or under MEDIA_MANGLERS_SCRATCH_ROOT
    # when that is set (the test suite sets it). The name carries this
    # process's id, so a later run can tell whether its owner is still running.
    param(
        [string]$Prefix,
        [string]$Extension = ""
    )
    $root = [Environment]::GetEnvironmentVariable("MEDIA_MANGLERS_SCRATCH_ROOT")
    if ([string]::IsNullOrWhiteSpace($root)) {
        $root = [System.IO.Path]::GetTempPath()
    }
    else {
        $null = [System.IO.Directory]::CreateDirectory($root)
    }
    return (Join-Path $root ("{0}_{1}_{2}{3}" -f $Prefix, $PID, [guid]::NewGuid().ToString(), $Extension))
}

function Remove-MMOrphanedScratch {
    # 196: Stop in the Workbench ends the backend at once, so its clean-up
    # never runs and the decoded audio of every track (gigabytes) is left in
    # the temp folder. This removes the voice detection and FFmpeg progress
    # work files whose owning process is no longer running. A name that is
    # not exactly one of these, or has no process id, is left alone, and so
    # is anything whose owner is still running: another run may be using it.
    $root = [Environment]::GetEnvironmentVariable("MEDIA_MANGLERS_SCRATCH_ROOT")
    if ([string]::IsNullOrWhiteSpace($root)) { $root = [System.IO.Path]::GetTempPath() }
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { return 0 }
    $guid = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
    # 201: and the other work files of a run: helper requests and results, Whisper's scripts and
    # progress, screenshot and audio batches, and the Python helpers' own folders, which carry the
    # helper's process id and a short random name.
    $helper = '[a-z0-9_]{8}'
    $folderPattern = "^media_manglers_(?:voice_work|whisper_calibration|evidence_frames|evidence_audio|ai_review_zip|transcript_only_audio)_(\d+)_$guid$|^media_manglers_(?:cross_check|voice_helper)_(\d+)_$helper$"
    $filePattern = "^(?:media_manglers_(?:voice_progress|whisper_progress|audio_progress|request|result)_(\d+)_$guid\.json(?:\.tmp)?|media_manglers_ffmpeg_progress_(\d+)_$guid\.txt|media_manglers_whisper_(?:probe|transcribe)_(\d+)_$guid\.py)$"
    $removed = 0
    foreach ($item in @(Get-ChildItem -LiteralPath $root -Force -Filter "media_manglers_*" -ErrorAction SilentlyContinue)) {
        $ownerText = ""
        $pattern = if ($item.PSIsContainer) { $folderPattern } else { $filePattern }
        if ($item.Name -cmatch $pattern) {
            $ownerText = @($Matches.Keys | Where-Object { $_ -ne 0 } | Sort-Object | ForEach-Object { $Matches[$_] } | Where-Object { $_ }) | Select-Object -First 1
        }
        $ownerId = 0
        if (-not [int]::TryParse($ownerText, [ref]$ownerId)) { continue }
        if ($ownerId -eq $PID -or $null -ne (Get-Process -Id $ownerId -ErrorAction SilentlyContinue)) { continue }
        Remove-MMScratchPath -Path $item.FullName
        if (-not (Test-Path -LiteralPath $item.FullName)) { $removed += 1 }
    }
    if ($removed -gt 0) {
        Write-Log ("Removed {0} work file(s) left behind by an earlier run that was stopped." -f $removed)
    }
    return $removed
}

function Remove-MMPackageWavFiles {
    # 196: the package ZIP takes every file under audio\, and a .wav there is
    # a whole track of the recording. None is handed to the package writer.
    param([string]$AudioFolder)
    if ([string]::IsNullOrWhiteSpace($AudioFolder) -or -not (Test-Path -LiteralPath $AudioFolder -PathType Container)) { return }
    $removed = 0
    # 214: and what a decode stopped from outside (Stop in the Workbench) left beside its WAV.
    foreach ($decode in @(Get-ChildItem -LiteralPath $AudioFolder -Recurse -Directory -Force -Filter ".*-decode" -ErrorAction SilentlyContinue)) {
        Remove-MMScratchPath -Path $decode.FullName
    }
    foreach ($wav in @(Get-ChildItem -LiteralPath $AudioFolder -Recurse -File -Force -ErrorAction SilentlyContinue | Where-Object { $_.Extension -ieq ".wav" })) {
        Remove-MMScratchPath -Path $wav.FullName
        if (-not (Test-Path -LiteralPath $wav.FullName)) { $removed += 1 }
    }
    if ($removed -gt 0) {
        Write-Log ("Removed {0} .wav file(s) from the package's audio folder before the package was written." -f $removed) "WARN"
    }
}

function Invoke-ExternalCapture {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$StepName = "External command",
        [int]$HeartbeatSeconds = 0,
        [int]$TimeoutSeconds = 1800,
        [switch]$IgnoreExitCode
    )

    $argString = (($Arguments | ForEach-Object { Quote-Argument $_ }) -join " ")
    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    Write-Log "$StepName"
    Write-Log "Command: $FilePath $argString"

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.Arguments = $argString
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi

    [void]$proc.Start()
    $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
    $stderrTask = $proc.StandardError.ReadToEndAsync()

    $start = Get-Date
    $nextHeartbeat = if ($HeartbeatSeconds -gt 0) { $start.AddSeconds($HeartbeatSeconds) } else { $null }

    while (-not $proc.HasExited) {
        Start-Sleep -Milliseconds 500

        $pausedSeconds = Invoke-MMRunControlCheck -Process $proc -StepName $StepName
        if ($pausedSeconds -gt 0) {
            $start = $start.AddSeconds($pausedSeconds)
            if ($nextHeartbeat) { $nextHeartbeat = $nextHeartbeat.AddSeconds($pausedSeconds) }
        }

        $now = Get-Date
        $elapsed = ($now - $start).TotalSeconds

        if ($nextHeartbeat -and $now -ge $nextHeartbeat) {
            Write-Log ("{0} still working... elapsed {1:n0}s" -f $StepName, $elapsed)
            Write-MMProgressV1 -Phase ([string]$script:MMProgressPhase) -ProgressKind indeterminate -Activity $StepName -Heartbeat
            $nextHeartbeat = $now.AddSeconds($HeartbeatSeconds)
        }

        if ($TimeoutSeconds -gt 0 -and $elapsed -ge $TimeoutSeconds) {
            # The whole tree: a launcher's own FFmpeg must not keep reading the recording.
            Stop-MMProcessTree -Process $proc
            throw "$StepName timed out after $TimeoutSeconds seconds."
        }
    }

    $proc.WaitForExit()
    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()
    $sw.Stop()

    if (-not [string]::IsNullOrWhiteSpace($stdout) -and $script:CurrentLogFile) {
        $null = Add-LogContentWithRetry -Path $script:CurrentLogFile -Value "----- STDOUT: $StepName -----"
        $null = Add-LogContentWithRetry -Path $script:CurrentLogFile -Value $stdout
    }

    if (-not [string]::IsNullOrWhiteSpace($stderr) -and $script:CurrentLogFile) {
        $null = Add-LogContentWithRetry -Path $script:CurrentLogFile -Value "----- STDERR: $StepName -----"
        $null = Add-LogContentWithRetry -Path $script:CurrentLogFile -Value $stderr
    }

    if (-not $IgnoreExitCode -and $proc.ExitCode -ne 0) {
        $failureSummary = Get-ExternalFailureSummary -StdOut $stdout -StdErr $stderr
        if ([string]::IsNullOrWhiteSpace($failureSummary)) {
            throw "$StepName failed with exit code $($proc.ExitCode)."
        }
        throw "$StepName failed with exit code $($proc.ExitCode): $failureSummary"
    }

    return [PSCustomObject]@{
        ExitCode        = $proc.ExitCode
        StdOut          = $stdout
        StdErr          = $stderr
        DurationSeconds = [math]::Round($sw.Elapsed.TotalSeconds, 3)
    }
}

function Invoke-ExternalStreaming {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$StepName = "External command",
        [switch]$IgnoreExitCode,
        [int]$HeartbeatSeconds = 30,
        [int]$TimeoutSeconds = 1800,
        [int]$StallTimeoutSeconds = 0,
        [double]$EstimatedTotalSeconds = 0,
        [string]$ProgressStateFilePath = "",
        [psobject]$CpuFallbackRuntimePlan = $null
    )

    $argString = (($Arguments | ForEach-Object { Quote-Argument $_ }) -join " ")

    Write-Log "$StepName"
    Write-Log "Command: $FilePath $argString"

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.Arguments = $argString
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    try {
        $proc = New-Object System.Diagnostics.Process
        $proc.StartInfo = $psi
        [void]$proc.Start()
        $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
        $stderrTask = $proc.StandardError.ReadToEndAsync()

        $start = Get-Date
        $nextHeartbeat = if ($HeartbeatSeconds -gt 0) { (Get-Date).AddSeconds($HeartbeatSeconds) } else { $null }
        $effectiveEstimatedTotalSeconds = [double]$EstimatedTotalSeconds
        $effectiveTimeoutSeconds = [double]$TimeoutSeconds
        $lastProgressSignature = ""
        # 224 (Wave B2a): the helper's last structured state; the heartbeat repeats it, so a step that
        # reports work done never reads as "no measure" between two of its reports.
        $lastRelay = $null
        $lastKnownDevice = ""
        $gpuFallbackHandled = $false
        $estimateExceededLogged = $false

        while (-not $proc.HasExited) {
            Start-Sleep -Milliseconds 500

            $pausedSeconds = Invoke-MMRunControlCheck -Process $proc -StepName $StepName
            if ($pausedSeconds -gt 0) {
                $start = $start.AddSeconds($pausedSeconds)
                if ($nextHeartbeat) { $nextHeartbeat = $nextHeartbeat.AddSeconds($pausedSeconds) }
            }

            $now = Get-Date
            $elapsed = ($now - $start).TotalSeconds
            $progressState = Read-ProgressStateFile -Path $ProgressStateFilePath
            $progressSignature = Get-ProgressStateSignature -ProgressState $progressState
            $currentProgressDevice = Get-ProgressDeviceValue -ProgressState $progressState
            $progressRequestedDevice = if ($progressState) { [string]$progressState.RequestedDevice } else { "" }
            $progressDeviceEvent = if ($progressState) { [string]$progressState.DeviceEvent } else { "" }
            $progressIndicatesGpuFallback = (
                $progressRequestedDevice -eq "cuda" -and
                $currentProgressDevice -eq "cpu" -and
                (
                    $lastKnownDevice -eq "cuda" -or
                    $progressDeviceEvent -eq "gpu_to_cpu_fallback"
                )
            )

            if (-not [string]::IsNullOrWhiteSpace($currentProgressDevice)) {
                $lastKnownDevice = $currentProgressDevice
            }

            if ($progressState -and $progressSignature -ne $lastProgressSignature) {
                if (-not $gpuFallbackHandled -and $progressIndicatesGpuFallback) {
                    $gpuReason = if (-not [string]::IsNullOrWhiteSpace($progressState.GpuError)) {
                        [string]$progressState.GpuError
                    }
                    else {
                        "reason not reported by the helper"
                    }

                    if ($CpuFallbackRuntimePlan) {
                        $previousBudgetLabel = if ($effectiveTimeoutSeconds -gt 0) {
                            Format-DurationHuman -Seconds $effectiveTimeoutSeconds
                        }
                        else {
                            "none"
                        }
                        $rebasedEstimatedTotalSeconds = [math]::Ceiling($elapsed + [double]$CpuFallbackRuntimePlan.EstimatedRuntimeSeconds)
                        $rebasedTimeoutSeconds = [math]::Ceiling($elapsed + [double]$CpuFallbackRuntimePlan.ResolvedTimeoutSeconds)
                        $effectiveEstimatedTotalSeconds = [math]::Max($effectiveEstimatedTotalSeconds, [double]$rebasedEstimatedTotalSeconds)
                        $effectiveTimeoutSeconds = [math]::Max($effectiveTimeoutSeconds, [double]$rebasedTimeoutSeconds)
                        Write-Log ("[GPU->CPU] Local Whisper switched from GPU to CPU after {0}. GPU failure reason: {1}. The helper restarted the full source on CPU, so the runtime budget was rebased from {2} to {3}; estimated total is now {4}." -f `
                            (Format-DurationHuman -Seconds $elapsed), `
                            $gpuReason, `
                            $previousBudgetLabel, `
                            (Format-DurationHuman -Seconds $effectiveTimeoutSeconds), `
                            (Format-DurationHuman -Seconds $effectiveEstimatedTotalSeconds)) "WARN"
                    }
                    else {
                        Write-Log ("[GPU->CPU] Local Whisper switched from GPU to CPU after {0}. GPU failure reason: {1}. The current timeout remains active because this run is using an explicit override." -f `
                            (Format-DurationHuman -Seconds $elapsed), `
                            $gpuReason) "WARN"
                    }

                    $gpuFallbackHandled = $true
                }

                $lastProgressSignature = $progressSignature
                if ([string]$progressState.Schema -eq "MM_PROGRESS_V1") {
                    $relay = @{
                        Phase = [string]$progressState.Phase
                        ProgressKind = $(if ([string]::IsNullOrWhiteSpace([string]$progressState.ProgressKind)) { "indeterminate" } else { [string]$progressState.ProgressKind })
                        Activity = [string]$progressState.Activity
                        SourceName = [string]$progressState.SourceName
                        SourceCompleted = [int]$progressState.SourceCompleted
                        SourceTotal = [int]$progressState.SourceTotal
                        SourceOrdinal = [int]$progressState.SourceOrdinal
                        SourceState = [string]$progressState.SourceState
                        SourceTerminal = [bool]$progressState.SourceTerminal
                        PreparedCount = [int]$progressState.PreparedCount
                        BlockedCount = [int]$progressState.BlockedCount
                        FailedCount = [int]$progressState.FailedCount
                        TerminalState = $(if ([string]$progressState.TerminalState -in @("succeeded", "failed", "cancelled")) { [string]$progressState.TerminalState } else { "" })
                        ProviderUpdatedAt = [string]$progressState.UpdatedAtUtc
                    }
                    if ([bool]$progressState.HasArtifactCounts) {
                        # 214: screenshots report how many are made, as the backend's own did.
                        foreach ($name in @("PhaseIndex", "PhaseCount", "SourceId", "Completed", "Total", "ArtifactCompleted", "ArtifactTotal", "LatestArtifactPath")) {
                            $relay[$name] = $progressState.$name
                        }
                    }
                    if ($relay.ProgressKind -eq "work_units") {
                        # 224 (Wave B2a, 272): work done of total, in its unit, for any helper that says it.
                        $relay.Completed = [long]$progressState.Completed
                        $relay.Total = [long]$progressState.Total
                        $relay.WorkUnit = [string]$progressState.WorkUnit
                    }
                    else {
                        $relay.WorkUnit = ""
                    }
                    Write-MMProgressV1 @relay
                    $lastRelay = $relay
                }
                else {
                    $structuredActivity = Get-ProgressStateSummary -ProgressState $progressState
                    if ([string]::IsNullOrWhiteSpace($structuredActivity)) { $structuredActivity = $StepName }
                    Write-MMProgressV1 `
                        -Phase ([string]$script:MMProgressPhase) `
                        -ProgressKind indeterminate `
                        -Activity $structuredActivity `
                        -ProviderStage ([string]$progressState.Stage) `
                        -ProviderMessage ([string]$progressState.Message) `
                        -ProviderDevice $currentProgressDevice `
                        -ProviderUpdatedAt ([string]$progressState.UpdatedAtUtc)
                }
            }

            $progressUpdatedAtUtc = $null
            if ($progressState -and $progressState.UpdatedAtUtc) {
                $progressUpdatedAtUtc = $progressState.UpdatedAtUtc
            }
            elseif (-not [string]::IsNullOrWhiteSpace($ProgressStateFilePath) -and (Test-Path -LiteralPath $ProgressStateFilePath)) {
                $progressUpdatedAtUtc = (Get-Item -LiteralPath $ProgressStateFilePath).LastWriteTimeUtc
            }

            $progressAgeSeconds = if ($progressUpdatedAtUtc) {
                ((Get-Date).ToUniversalTime() - $progressUpdatedAtUtc).TotalSeconds
            }
            else {
                $elapsed
            }
            if ($null -ne $script:MMLastResumeAt) {
                # A paused helper reports nothing; do not count the pause as a stall.
                $sinceResume = ((Get-Date) - $script:MMLastResumeAt).TotalSeconds
                if ($sinceResume -lt $progressAgeSeconds) { $progressAgeSeconds = $sinceResume }
            }

            if ($nextHeartbeat -and $now -ge $nextHeartbeat) {
                $estimatedTotalLabel = if ($effectiveEstimatedTotalSeconds -gt 0) {
                    Format-DurationHuman -Seconds $effectiveEstimatedTotalSeconds
                }
                else {
                    "unknown"
                }
                $hardBudgetRemainingLabel = if ($effectiveTimeoutSeconds -gt 0) {
                    Format-DurationHuman -Seconds ([math]::Max(0.0, $effectiveTimeoutSeconds - $elapsed))
                }
                else {
                    "unknown"
                }
                $estimatedRemainingLabel = if ($effectiveEstimatedTotalSeconds -gt 0 -and $elapsed -le $effectiveEstimatedTotalSeconds) {
                    Format-DurationHuman -Seconds ([math]::Max(0.0, $effectiveEstimatedTotalSeconds - $elapsed))
                }
                elseif ($effectiveEstimatedTotalSeconds -gt 0) {
                    if (-not $estimateExceededLogged) {
                        Write-Log ("{0} exceeded estimate; continuing because helper is active. Hard budget remaining {1}." -f $StepName, $hardBudgetRemainingLabel) "WARN"
                        $estimateExceededLogged = $true
                    }
                    "over estimate by {0}; hard budget remaining {1}" -f (Format-DurationHuman -Seconds ($elapsed - $effectiveEstimatedTotalSeconds)), $hardBudgetRemainingLabel
                }
                else {
                    "unknown"
                }
                $runtimeBudgetLabel = if ($effectiveTimeoutSeconds -gt 0) {
                    Format-DurationHuman -Seconds $effectiveTimeoutSeconds
                }
                else {
                    "none"
                }
                $progressAgeLabel = if ($progressUpdatedAtUtc) {
                    Format-DurationHuman -Seconds $progressAgeSeconds
                }
                else {
                    "not yet reported"
                }
                $stallWatchdogLabel = if ($StallTimeoutSeconds -gt 0) {
                    Format-DurationHuman -Seconds $StallTimeoutSeconds
                }
                else {
                    "off"
                }
                $progressSummary = Get-ProgressStateSummary -ProgressState $progressState
                $progressSuffix = if ([string]::IsNullOrWhiteSpace($progressSummary)) {
                    ""
                }
                else {
                    ("; helper state {0}" -f $progressSummary)
                }

                $deviceTag = Get-ProgressDeviceTag -Device $currentProgressDevice
                $stepLabel = if ([string]::IsNullOrWhiteSpace($deviceTag)) {
                    $StepName
                }
                else {
                    ("{0} {1}" -f $deviceTag, $StepName)
                }

                Write-Log ("{0} still working... elapsed {1}; estimated total {2}; estimated remaining {3}; runtime budget {4}; last progress update {5} ago; stall watchdog {6}{7}" -f $stepLabel, (Format-DurationHuman -Seconds $elapsed), $estimatedTotalLabel, $estimatedRemainingLabel, $runtimeBudgetLabel, $progressAgeLabel, $stallWatchdogLabel, $progressSuffix)
                $heartbeatActivity = if ([string]::IsNullOrWhiteSpace($progressSummary)) { $StepName } else { $progressSummary }
                if ($null -ne $lastRelay) {
                    # 224 (Wave B2b): what the helper last said, measured or not, is what the heartbeat repeats.
                    Write-MMProgressV1 @lastRelay -Heartbeat
                }
                else {
                    Write-MMProgressV1 `
                        -Phase ([string]$script:MMProgressPhase) `
                        -ProgressKind indeterminate `
                        -Activity $heartbeatActivity `
                        -ProviderStage $(if ($progressState) { [string]$progressState.Stage } else { "" }) `
                        -ProviderMessage $(if ($progressState) { [string]$progressState.Message } else { "" }) `
                        -ProviderDevice $currentProgressDevice `
                        -ProviderUpdatedAt $(if ($progressState) { [string]$progressState.UpdatedAtUtc } else { "" }) `
                        -Heartbeat
                }
                $nextHeartbeat = $now.AddSeconds($HeartbeatSeconds)
            }

            if ($StallTimeoutSeconds -gt 0 -and $progressAgeSeconds -ge $StallTimeoutSeconds) {
                # The whole tree: a helper's own FFmpeg must not keep reading the recording.
                Stop-MMProcessTree -Process $proc
                $progressSummary = Get-ProgressStateSummary -ProgressState $progressState
                if ([string]::IsNullOrWhiteSpace($progressSummary)) {
                    throw "$StepName stopped reporting progress for $(Format-DurationHuman -Seconds $progressAgeSeconds). The stall watchdog is $(Format-DurationHuman -Seconds $StallTimeoutSeconds)."
                }
                throw "$StepName stopped reporting progress for $(Format-DurationHuman -Seconds $progressAgeSeconds). The stall watchdog is $(Format-DurationHuman -Seconds $StallTimeoutSeconds). Last helper state: $progressSummary"
            }

            if ($effectiveTimeoutSeconds -gt 0 -and $elapsed -ge $effectiveTimeoutSeconds) {
                Stop-MMProcessTree -Process $proc
                $progressSummary = Get-ProgressStateSummary -ProgressState $progressState
                if ([string]::IsNullOrWhiteSpace($progressSummary)) {
                    throw "$StepName hard runtime budget exceeded after $(Format-DurationHuman -Seconds $elapsed). Budget: $(Format-DurationHuman -Seconds $effectiveTimeoutSeconds)."
                }
                throw "$StepName hard runtime budget exceeded after $(Format-DurationHuman -Seconds $elapsed). Budget: $(Format-DurationHuman -Seconds $effectiveTimeoutSeconds). Last helper state: $progressSummary"
            }
        }

        $proc.WaitForExit()
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        $sw.Stop()
        $exitCode = $proc.ExitCode

        if (-not [string]::IsNullOrWhiteSpace($stdout)) {
            if (Test-ConsoleDebugMode) {
                ($stdout -split "`r?`n") | ForEach-Object {
                    if ($_ -ne "") {
                        Write-Host $_
                    }
                }
            }
            if ($script:CurrentLogFile) {
                $null = Add-LogContentWithRetry -Path $script:CurrentLogFile -Value $stdout
            }
        }

        if (-not [string]::IsNullOrWhiteSpace($stderr)) {
            if (Test-ConsoleDebugMode) {
                ($stderr -split "`r?`n") | ForEach-Object {
                    if ($_ -ne "") {
                        Write-Host $_ -ForegroundColor Yellow
                    }
                }
            }
            if ($script:CurrentLogFile) {
                $null = Add-LogContentWithRetry -Path $script:CurrentLogFile -Value $stderr
            }
        }

        if (-not $IgnoreExitCode -and $exitCode -ne 0) {
            $failureSummary = Get-ExternalFailureSummary -StdOut $stdout -StdErr $stderr
            if ([string]::IsNullOrWhiteSpace($failureSummary)) {
                throw "$StepName failed with exit code $exitCode."
            }
            throw "$StepName failed with exit code ${exitCode}: $failureSummary"
        }

        return [PSCustomObject]@{
            ExitCode        = $exitCode
            StdOut          = $stdout
            StdErr          = $stderr
            DurationSeconds = [math]::Round($sw.Elapsed.TotalSeconds, 3)
        }
    }
    finally {
        if ($proc) {
            $proc.Dispose()
        }
    }
}

function Invoke-RemoteVideoDownload {
    param(
        [string]$SourceUrl,
        [string]$DownloadFolder,
        [psobject]$YtDlpInvoker,
        [string]$FFmpegExe,
        [switch]$IncludeComments,
        [bool]$InteractiveMode,
        [int]$HeartbeatSeconds = 30
    )

    Ensure-Directory $DownloadFolder

    $sourceKind = Get-RemoteSourceKind -SourceUrl $SourceUrl
    $sessionFolderName = "download-{0}-{1}" -f (Get-Date -Format "yyyyMMdd-HHmmss"), ([guid]::NewGuid().ToString("N").Substring(0, 8))
    $sessionFolder = Join-Path $DownloadFolder $sessionFolderName
    Ensure-Directory $sessionFolder

    $outputTemplate = if ($sourceKind -eq "playlist") {
        "%(playlist_index)05d - %(title).80B [%(id)s].%(ext)s"
    }
    else {
        "%(title).80B [%(id)s].%(ext)s"
    }

    $remoteAudioProbe = $null
    $remoteAudioRequest = $null

    $ffmpegLocation = if ([string]::IsNullOrWhiteSpace($FFmpegExe)) { $null } else { Split-Path -Path $FFmpegExe -Parent }
    $formatArguments = @(
        "--format", "bv*+ba/b",
        "--merge-output-format", "mp4",
        "--format-sort", "res,fps,hdr,vcodec,acodec,ext"
    )

    if ((Test-IsYouTubeUrl -SourceUrl $SourceUrl) -and $sourceKind -eq "video") {
        $remoteAudioProbe = Get-YouTubeAudioTrackProbe -SourceUrl $SourceUrl -YtDlpInvoker $YtDlpInvoker
        $remoteAudioRequest = Select-YouTubeAudioTrackRequest -ProbeResult $remoteAudioProbe -InteractiveMode $InteractiveMode
        if ($remoteAudioRequest -and -not [string]::IsNullOrWhiteSpace($remoteAudioRequest.LogLine)) {
            Write-Log $remoteAudioRequest.LogLine
        }

        if ($remoteAudioRequest -and $remoteAudioRequest.Mode -eq "explicit" -and $remoteAudioRequest.RequestedTrack) {
            $formatArguments = @(
                "--format", $remoteAudioRequest.RequestedTrack.FormatSelector,
                "--merge-output-format", "mp4",
                "--format-sort", "res,fps,hdr,vcodec,acodec,ext"
            )
        }
    }
    elseif ((Test-IsYouTubeUrl -SourceUrl $SourceUrl) -and $sourceKind -eq "playlist") {
        Write-Log "YouTube playlist detected. Audio-track prompts are skipped for playlist downloads; using best-effort per-entry selection from provider metadata." "WARN"
    }

    if (-not [string]::IsNullOrWhiteSpace($ffmpegLocation)) {
        $formatArguments += @("--ffmpeg-location", $ffmpegLocation)
    }

    $playlistArguments = if ($sourceKind -eq "playlist") {
        @("--yes-playlist", "--ignore-errors")
    }
    else {
        @("--no-playlist")
    }
    $downloadArguments = $YtDlpInvoker.Arguments + @(
            "--newline",
            "--restrict-filenames",
            "--print", "after_move:filepath",
            "-P", $sessionFolder,
            "-o", $outputTemplate
        ) + @("--write-info-json") + $(if ($IncludeComments) { @("--write-comments") } else { @() }) + $formatArguments + $playlistArguments + @($SourceUrl)
    $downloadMaxAttempts = if ($sourceKind -eq "video") { 3 } else { 1 }
    $result = $null
    for ($downloadAttempt = 1; $downloadAttempt -le $downloadMaxAttempts; $downloadAttempt++) {
        $result = Invoke-ExternalStreaming `
            -FilePath $YtDlpInvoker.FilePath `
            -Arguments $downloadArguments `
            -StepName ("yt-dlp download ({0})" -f $sourceKind) `
            -IgnoreExitCode `
            -HeartbeatSeconds $HeartbeatSeconds `
            -TimeoutSeconds 7200

        if ($result.ExitCode -eq 0 -or $sourceKind -ne "video") {
            break
        }

        $failureSummary = Get-ExternalFailureSummary -StdOut $result.StdOut -StdErr $result.StdErr
        if ($downloadAttempt -lt $downloadMaxAttempts) {
            $retryDelaySeconds = 5 * $downloadAttempt
            $failureDetail = if ([string]::IsNullOrWhiteSpace($failureSummary)) {
                "exit code $($result.ExitCode)"
            }
            else {
                $failureSummary
            }
            Write-Log ("Web video download attempt {0} of {1} failed: {2}. Retrying in {3} seconds." -f $downloadAttempt, $downloadMaxAttempts, $failureDetail, $retryDelaySeconds) "WARN"
            Start-Sleep -Seconds $retryDelaySeconds
        }
    }

    $supportedExtensions = @(".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm")
    $downloadedPaths = @()

    foreach ($line in ($result.StdOut -split "`r?`n")) {
        $candidate = $line.Trim()
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate)) {
            $item = Get-Item -LiteralPath $candidate
            if (-not $item.PSIsContainer -and $supportedExtensions -contains $item.Extension.ToLowerInvariant()) {
                $downloadedPaths += $item.FullName
            }
        }
    }

    if ($downloadedPaths.Count -eq 0) {
        $downloadedPaths = @(
            Get-ChildItem -LiteralPath $sessionFolder -File -Recurse |
                Where-Object { $supportedExtensions -contains $_.Extension.ToLowerInvariant() } |
                Sort-Object Name |
                ForEach-Object { $_.FullName }
        )
    }

    if ($downloadedPaths.Count -eq 0) {
        throw "yt-dlp finished without producing a supported local video file in $sessionFolder"
    }

    if ($result.ExitCode -ne 0) {
        if ($sourceKind -eq "playlist") {
            Write-Log ("yt-dlp reported some playlist entries as unavailable or inaccessible. Continuing with {0} downloaded video(s)." -f $downloadedPaths.Count) "WARN"
        }
        else {
            $failureSummary = Get-ExternalFailureSummary -StdOut $result.StdOut -StdErr $result.StdErr
            if ([string]::IsNullOrWhiteSpace($failureSummary)) {
                throw ("yt-dlp download ({0}) failed after {1} attempts with exit code {2}." -f $sourceKind, $downloadMaxAttempts, $result.ExitCode)
            }
            throw ("yt-dlp download ({0}) failed after {1} attempts with exit code {2}: {3}" -f $sourceKind, $downloadMaxAttempts, $result.ExitCode, $failureSummary)
        }
    }

    Write-Log ("Remote {0} downloaded. Items: {1}. Cache folder: {2}" -f $sourceKind, $downloadedPaths.Count, $sessionFolder)

    $infoJsonByMediaPath = @{}
    $remoteAudioTrackInfoByMediaPath = @{}
    foreach ($downloadedPath in $downloadedPaths) {
        $basePath = Join-Path ([System.IO.Path]::GetDirectoryName($downloadedPath)) ([System.IO.Path]::GetFileNameWithoutExtension($downloadedPath))
        $infoJsonPath = "$basePath.info.json"
        if (Test-Path -LiteralPath $infoJsonPath) {
            $infoJsonByMediaPath[$downloadedPath] = $infoJsonPath

            $remoteAudioTrackInfo = Get-RemoteAudioTrackInfoFromInfoJson `
                -InfoJsonPath $infoJsonPath `
                -ProbeTrackCandidates $(if ($remoteAudioProbe) { $remoteAudioProbe.TrackCandidates } else { @() }) `
                -RequestedTrack $(if ($remoteAudioRequest) { $remoteAudioRequest.RequestedTrack } else { $null })

            if ($remoteAudioTrackInfo) {
                $remoteAudioTrackInfoByMediaPath[$downloadedPath] = $remoteAudioTrackInfo
                Write-Log $remoteAudioTrackInfo.SummaryLine
                if (-not [string]::IsNullOrWhiteSpace($remoteAudioTrackInfo.MismatchWarning)) {
                    Write-Log $remoteAudioTrackInfo.MismatchWarning "WARN"
                }
            }
        }
    }

    return [PSCustomObject]@{
        SourceKind               = $sourceKind
        DownloadRoot             = $sessionFolder
        DownloadedPaths          = $downloadedPaths
        InfoJsonByMediaPath      = $infoJsonByMediaPath
        RemoteAudioTrackByMediaPath = $remoteAudioTrackInfoByMediaPath
    }
}

function Export-CommentsArtifactsFromInfoJson {
    param(
        [string]$InfoJsonPath,
        [string]$CommentsFolder
    )

    if ([string]::IsNullOrWhiteSpace($InfoJsonPath) -or -not (Test-Path -LiteralPath $InfoJsonPath)) {
        return $null
    }

    $payload = Get-Content -LiteralPath $InfoJsonPath -Raw | ConvertFrom-Json
    $comments = @($payload.comments)
    if ($comments.Count -eq 0) {
        return $null
    }

    Ensure-Directory $CommentsFolder

    $commentsJsonPath = Join-Path $CommentsFolder "comments.json"
    $commentsTextPath = Join-Path $CommentsFolder "comments.txt"

    $normalizedComments = @()
    $textLines = New-Object System.Collections.Generic.List[string]
    [void]$textLines.Add("Public comments export")
    [void]$textLines.Add("======================")
    [void]$textLines.Add("")

    if ($payload.title) {
        [void]$textLines.Add(("Title: {0}" -f $payload.title))
    }
    if ($payload.webpage_url) {
        [void]$textLines.Add(("Source: {0}" -f $payload.webpage_url))
    }
    [void]$textLines.Add(("Comments exported: {0}" -f $comments.Count))
    [void]$textLines.Add("")

    $index = 0
    foreach ($comment in $comments) {
        $index += 1
        $author = [string]$comment.author
        $text = [string]$comment.text
        $timestamp = [string]$comment.timestamp
        $likeCount = [string]$comment.like_count
        $normalizedComments += [PSCustomObject]@{
            id           = [string]$comment.id
            author       = $author
            text         = $text
            timestamp    = $timestamp
            like_count   = $likeCount
            parent       = [string]$comment.parent
            is_favorited = [string]$comment.is_favorited
        }

        [void]$textLines.Add(("[{0}] {1}" -f $index, $(if ([string]::IsNullOrWhiteSpace($author)) { "Unknown author" } else { $author })))
        if (-not [string]::IsNullOrWhiteSpace($timestamp)) {
            [void]$textLines.Add(("Date: {0}" -f $timestamp))
        }
        if (-not [string]::IsNullOrWhiteSpace($likeCount)) {
            [void]$textLines.Add(("Likes: {0}" -f $likeCount))
        }
        [void]$textLines.Add("Comment:")
        [void]$textLines.Add($(if ([string]::IsNullOrWhiteSpace($text)) { "[empty]" } else { $text.Trim() }))
        [void]$textLines.Add("")
    }

    [PSCustomObject]@{
        title         = [string]$payload.title
        webpage_url   = [string]$payload.webpage_url
        extractor_key = [string]$payload.extractor_key
        comment_count = $normalizedComments.Count
        comments      = $normalizedComments
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $commentsJsonPath -Encoding UTF8

    $textLines | Set-Content -LiteralPath $commentsTextPath -Encoding UTF8

    return [PSCustomObject]@{
        CommentsFolder   = $CommentsFolder
        CommentsJsonPath = $commentsJsonPath
        CommentsTextPath = $commentsTextPath
        CommentCount     = $normalizedComments.Count
    }
}

function Test-FrameIntervalValue {
    param([double]$Value)

    if ($Value -lt 0.1 -or $Value -gt 10.0) {
        throw "Frame interval must be between 0.1 and 10.0 seconds."
    }

    $tenths = $Value * 10
    if ([math]::Abs($tenths - [math]::Round($tenths)) -gt 0.000001) {
        throw "Frame interval must be in 0.1 second increments."
    }
}

function Get-FrameIntervalLabel {
    param([double]$Value)

    return $Value.ToString("0.0", [System.Globalization.CultureInfo]::InvariantCulture) -replace '\.', 'p'
}

function Get-FramesFolderName {
    param([double]$Value)

    return "frames_{0}s" -f (Get-FrameIntervalLabel -Value $Value)
}

function Get-InteractiveFrameInterval {
    param([double]$DefaultValue = 0.5)

    while ($true) {
        $defaultText = $DefaultValue.ToString("0.0", [System.Globalization.CultureInfo]::InvariantCulture)
        $raw = Read-TimedDefaultPrompt `
            -Prompt ("Enter frame interval in seconds (0.1 increments). Press Enter for {0}, or wait {1}s for default:" -f $defaultText, $script:PromptTimeoutSeconds) `
            -DefaultValue $defaultText
        if ([string]::IsNullOrWhiteSpace($raw)) {
            return $DefaultValue
        }

        $parsed = 0.0
        if (-not [double]::TryParse($raw.Trim(), [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$parsed)) {
            Write-Host "Please enter a numeric value like 0.3, 0.5, 1.0, or 1.1." -ForegroundColor Yellow
            continue
        }

        try {
            Test-FrameIntervalValue -Value $parsed
            return $parsed
        }
        catch {
            Write-Host $_.Exception.Message -ForegroundColor Yellow
        }
    }
}

function Get-InteractiveInputSource {
    param(
        [string]$DefaultInputFolder,
        [string]$YtDlpCommand,
        [string]$PythonCommand,
        [switch]$LocalOnly,
        [switch]$AllowWorkflowBack
    )

    while ($true) {
        Write-Host ""
        Write-Host "Default local input source:" -ForegroundColor Cyan
        Write-Host $DefaultInputFolder -ForegroundColor Cyan
        if ($LocalOnly) {
            Write-Host "Choose a local video source:" -ForegroundColor Cyan
            Write-Host "This workflow currently uses existing local video files or folders only. Choose the full review package workflow for URLs." -ForegroundColor Yellow
            Write-Host ("  1. Use this folder: {0} (default)" -f $DefaultInputFolder) -ForegroundColor Cyan
            Write-Host "  2. Paste a full local file or folder path" -ForegroundColor Cyan
            if ($AllowWorkflowBack) {
                Write-Host "  B. Back to workflow selection" -ForegroundColor Cyan
                Write-Host "Press Enter for 1, type B to go back, or type Q to quit." -ForegroundColor Cyan
                $localChoice = Read-TimedChoicePrompt `
                    -Prompt ("Enter 1, 2, B, or Q (default 1; auto-selects in {0}s):" -f $script:PromptTimeoutSeconds) `
                    -DefaultValue "1"
            }
            else {
                Write-Host "Press Enter for 1, or type Q to quit." -ForegroundColor Cyan
                $localChoice = Read-TimedChoicePrompt `
                    -Prompt ("Enter 1, 2, or Q (default 1; auto-selects in {0}s):" -f $script:PromptTimeoutSeconds) `
                    -DefaultValue "1"
            }

            if ([string]::IsNullOrWhiteSpace($localChoice)) {
                $localChoice = "1"
            }

            $localChoice = $localChoice.Trim()

            if ($localChoice -match '^(q|quit)$') {
                throw "User canceled at input selection."
            }
            if ($AllowWorkflowBack -and $localChoice -match '^(b|back)$') {
                return [PSCustomObject]@{ Action = "BackToWorkflow" }
            }

            if ($localChoice -eq "1") {
                try {
                    return (Resolve-StartupDirectory -Path $DefaultInputFolder -FolderKind "input")
                }
                catch {
                    Write-Host $_.Exception.Message -ForegroundColor Yellow
                    continue
                }
            }

            if ($localChoice -eq "2") {
                $customInput = Read-RequiredPathPrompt "Paste a full local file or folder path"
                if ([string]::IsNullOrWhiteSpace($customInput)) {
                    Write-Host "A local file or folder path is required." -ForegroundColor Yellow
                    continue
                }

                return (Normalize-UserPath -Path $customInput)
            }

            if ($AllowWorkflowBack) {
                Write-Host "Invalid choice. Enter 1, 2, B, or Q." -ForegroundColor Yellow
            }
            else {
                Write-Host "Invalid choice. Enter 1, 2, or Q." -ForegroundColor Yellow
            }
            continue
        }

        Write-Host "Choose an input method:" -ForegroundColor Cyan
        Write-Host "  1. Paste URLs" -ForegroundColor Cyan
        Write-Host ("  2. Use this folder: {0} (default)" -f $DefaultInputFolder) -ForegroundColor Cyan
        Write-Host "  3. Paste a full local file or folder path" -ForegroundColor Cyan
        Write-Host "Press Enter for 2, or type Q to quit." -ForegroundColor Cyan
        $inputChoice = Read-TimedChoicePrompt `
            -Prompt ("Enter 1, 2, 3, or Q (default 2; auto-selects in {0}s):" -f $script:PromptTimeoutSeconds) `
            -DefaultValue "2"

        if ([string]::IsNullOrWhiteSpace($inputChoice)) {
            $inputChoice = "2"
        }

        $inputChoice = $inputChoice.Trim()

        if ($inputChoice -match '^(q|quit)$') {
            throw "User canceled at input selection."
        }

        if ($inputChoice -eq "1") {
            Write-Host "Paste text containing one or more video or playlist URLs." -ForegroundColor Cyan
            Write-Host "Type DONE on its own line when the paste is complete." -ForegroundColor Cyan

            $remoteInputs = New-Object System.Collections.Generic.List[string]
            $capturedLines = New-Object System.Collections.Generic.List[string]
            $duplicateInputs = New-Object System.Collections.Generic.List[string]
            $lineNumber = 1

            while ($true) {
                $prompt = if ($lineNumber -eq 1) { "Paste line 1" } else { "Next line" }
                $remoteInput = Read-Host $prompt

                if (-not [string]::IsNullOrWhiteSpace($remoteInput) -and $remoteInput.Trim().ToUpperInvariant() -eq "DONE") {
                    break
                }

                [void]$capturedLines.Add($remoteInput)
                $lineNumber += 1
            }

            $parsedUrls = @(Get-HttpUrlsFromText -Value ($capturedLines -join "`n"))
            if ($parsedUrls.Count -eq 0) {
                Write-Host "No valid http/https URLs were found in that pasted text." -ForegroundColor Yellow
                continue
            }

            foreach ($parsedUrl in $parsedUrls) {
                if ($remoteInputs.Contains($parsedUrl)) {
                    if (-not $duplicateInputs.Contains($parsedUrl)) {
                        [void]$duplicateInputs.Add($parsedUrl)
                    }
                    continue
                }

                [void]$remoteInputs.Add($parsedUrl)
            }

            if ($duplicateInputs.Count -gt 0) {
                foreach ($duplicateUrl in $duplicateInputs) {
                    Write-Log "Ignoring duplicate remote URL: $duplicateUrl" "WARN"
                }
            }

            Write-Host ("Captured {0} unique remote URL(s)." -f $remoteInputs.Count) -ForegroundColor Cyan

            try {
                $null = Resolve-YtDlpInvoker -PreferredCommand $YtDlpCommand -PythonCommand $PythonCommand
            }
            catch {
                Write-Host $_.Exception.Message -ForegroundColor Yellow
                Write-YtDlpInstallGuidance -PythonCommand $PythonCommand
                $fallbackChoice = Read-TimedDefaultPrompt `
                    -Prompt ("Press Enter to choose a local file or folder instead, or type Q to stop. Auto-selects local input in {0}s:" -f $script:PromptTimeoutSeconds) `
                    -DefaultValue ""
                if (-not [string]::IsNullOrWhiteSpace($fallbackChoice) -and $fallbackChoice.Trim() -match '^(q|quit)$') {
                    throw
                }
                continue
            }

            foreach ($remoteUrl in $remoteInputs) {
                $sourceKind = Get-RemoteSourceKind -SourceUrl $remoteUrl
                if ($sourceKind -eq "playlist") {
                    Write-Host "Playlist detected. The script will download each video in the playlist before packaging." -ForegroundColor Cyan
                }
            }

            return @($remoteInputs)
        }

        if ($inputChoice -eq "2") {
            try {
                return (Resolve-StartupDirectory -Path $DefaultInputFolder -FolderKind "input")
            }
            catch {
                Write-Host $_.Exception.Message -ForegroundColor Yellow
                continue
            }
        }

        if ($inputChoice -eq "3") {
            $customInput = Read-RequiredPathPrompt "Paste a full local file or folder path"
            if ([string]::IsNullOrWhiteSpace($customInput)) {
                Write-Host "A local file or folder path is required for option 3." -ForegroundColor Yellow
                continue
            }

            return (Normalize-UserPath -Path $customInput)
        }

        Write-Host "Invalid choice. Enter 1, 2, 3, or Q." -ForegroundColor Yellow
    }
}

function Get-InteractiveVideoWorkflow {
    while ($true) {
        Write-Host ""
        Write-Host "Choose a video workflow:" -ForegroundColor Cyan
        Write-Host "" -ForegroundColor Cyan
        Write-Host "1. Full review package: complete AI/human review bundle (default)" -ForegroundColor Cyan
        Write-Host "   Builds proxy video, timeline frames, all audio-track transcripts, transcript/translations," -ForegroundColor DarkCyan
        Write-Host "   optional AI review zip, optional Codex evidence, and high-detail panel crops for 5760x1080 sources." -ForegroundColor DarkCyan
        Write-Host "" -ForegroundColor Cyan
        Write-Host "2. Transcript-only local batch/search: fast text extraction for existing local videos" -ForegroundColor Cyan
        Write-Host "   Creates/searches transcripts without building the full frame/proxy/review package." -ForegroundColor DarkCyan
        Write-Host "   Local files only." -ForegroundColor DarkCyan
        Write-Host "" -ForegroundColor Cyan
        Write-Host "3. Codex evidence package / ticket capture mode: issue-focused evidence from local recordings" -ForegroundColor Cyan
        Write-Host "   Builds an AI-reviewable evidence package with candidate ticket moments, transcript windows," -ForegroundColor DarkCyan
        Write-Host "   audio snippets, full frames, panel crops, marker audit, and issue draft evidence." -ForegroundColor DarkCyan
        Write-Host "" -ForegroundColor Cyan
        Write-Host "4. Archive catalog / Glacier prep index: searchable cold-storage catalog" -ForegroundColor Cyan
        Write-Host "   Builds a small hot catalog for raw local videos before archive storage:" -ForegroundColor DarkCyan
        Write-Host "   metadata, thumbnails/contact sheets, notes template, SQLite/CSV/JSONL, and restore/upload manifests." -ForegroundColor DarkCyan
        Write-Host "   Runs without AWS upload; no AWS upload is performed." -ForegroundColor DarkCyan
        Write-Host "" -ForegroundColor Cyan
        Write-Host "5. Review Media Inbox: bounded, resumable local review queue" -ForegroundColor Cyan
        Write-Host "   Scans configured local recording folders, classifies lifecycle and duplicate state," -ForegroundColor DarkCyan
        Write-Host "   and previews the next bounded batch without copying or preparing media in this foundational pass." -ForegroundColor DarkCyan
        Write-Host ""
        Write-Host "URLs are still available in workflow 1." -ForegroundColor DarkCyan
        Write-Host "Evidence mode scans existing recordings after capture; it does not require interaction while driving or recording." -ForegroundColor DarkCyan
        Write-Host ("Press Enter for 1, or wait {0}s for 1. Type Q to quit." -f $script:PromptTimeoutSeconds) -ForegroundColor Cyan
        $choice = Read-TimedChoicePrompt `
            -Prompt "Enter 1, 2, 3, 4, 5, or Q:" `
            -DefaultValue "1"

        if ([string]::IsNullOrWhiteSpace($choice)) {
            return [PSCustomObject]@{ TranscriptOnly = $false; CodexEvidencePackage = $false; ReviewNewVideos = $false; ArchiveCatalog = $false; ArchiveCatalogSearch = $false }
        }

        $choice = $choice.Trim()
        if ($choice -match '^(q|quit)$') {
            throw "User canceled at workflow selection."
        }
        if ($choice -eq "1") {
            return [PSCustomObject]@{ TranscriptOnly = $false; CodexEvidencePackage = $false; ReviewNewVideos = $false; ArchiveCatalog = $false; ArchiveCatalogSearch = $false }
        }
        if ($choice -eq "2") {
            return [PSCustomObject]@{ TranscriptOnly = $true; CodexEvidencePackage = $false; ReviewNewVideos = $false; ArchiveCatalog = $false; ArchiveCatalogSearch = $false }
        }
        if ($choice -eq "3") {
            return [PSCustomObject]@{ TranscriptOnly = $false; CodexEvidencePackage = $true; ReviewNewVideos = $false; ArchiveCatalog = $false; ArchiveCatalogSearch = $false }
        }
        if ($choice -eq "4") {
            $archiveAction = Get-InteractiveArchiveCatalogAction
            return [PSCustomObject]@{ TranscriptOnly = $false; CodexEvidencePackage = $false; ReviewNewVideos = $false; ArchiveCatalog = [bool]$archiveAction.Build; ArchiveCatalogSearch = [bool]$archiveAction.Search }
        }
        if ($choice -eq "5") {
            return [PSCustomObject]@{ TranscriptOnly = $false; CodexEvidencePackage = $false; ReviewNewVideos = $true; ArchiveCatalog = $false; ArchiveCatalogSearch = $false }
        }

        Write-Host "Invalid choice. Enter 1, 2, 3, 4, 5, or Q." -ForegroundColor Yellow
    }
}

function Get-InteractiveArchiveCatalogAction {
    while ($true) {
        Write-Host ""
        Write-Host "Archive catalog:" -ForegroundColor Cyan
        Write-Host "  B. Build/update archive catalog (default)" -ForegroundColor Cyan
        Write-Host "  S. Search archive catalog" -ForegroundColor Cyan
        $choice = Read-TimedChoicePrompt `
            -Prompt ("Enter B or S (default B; auto-selects in {0}s):" -f $script:PromptTimeoutSeconds) `
            -DefaultValue "B"
        if ([string]::IsNullOrWhiteSpace($choice) -or $choice.Trim() -match '(?i)^(b|build)$') {
            return [PSCustomObject]@{ Build = $true; Search = $false }
        }
        if ($choice.Trim() -match '(?i)^(s|search)$') {
            return [PSCustomObject]@{ Build = $false; Search = $true }
        }
        Write-Host "Invalid choice. Enter B or S." -ForegroundColor Yellow
    }
}

function Get-InteractiveFullReviewCodexEvidenceInclusion {
    $include = Read-TimedYesNoPrompt `
        -Prompt ("Include Codex evidence package / ticket-capture evidence in this full review? [Y/n] (default: Y, auto-selects in {0}s):" -f $script:PromptTimeoutSeconds) `
        -DefaultYes $true
    if ($include) {
        return [PSCustomObject]@{
            Include = $true
            Source  = "interactive default yes"
        }
    }

    return [PSCustomObject]@{
        Include = $false
        Source  = "interactive no"
    }
}

function Get-EvidencePanelCropModeSummary {
    param([string]$Mode)

    $normalizedMode = if ([string]::IsNullOrWhiteSpace($Mode)) { "Auto" } else { $Mode.Trim() }
    switch ($normalizedMode.ToLowerInvariant()) {
        "off" { return "Off (panel crops disabled; full-resolution evidence frames are still generated)" }
        "on" { return "On (exact 5760x1080 NVIDIA Surround frames split into overview_cam, driver_view, and face_cam crops)" }
        default { return "Auto (exact 5760x1080 NVIDIA Surround frames split into overview_cam, driver_view, and face_cam crops)" }
    }
}

function Get-InteractiveTranscriptSearchTerms {
    Write-Host ""
    Write-Host "Optional transcript search:" -ForegroundColor Cyan
    Write-Host "Enter literal search terms separated by commas, or press Enter to skip." -ForegroundColor Cyan
    $value = Read-TimedDefaultPrompt `
        -Prompt ("Search terms (press Enter to skip; auto-skips in {0}s):" -f $script:PromptTimeoutSeconds) `
        -DefaultValue ""
    if ([string]::IsNullOrWhiteSpace($value)) {
        return @()
    }

    return @(
        $value.Split(",") |
            ForEach-Object { $_.Trim() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
}

function Read-InteractiveNonNegativeDouble {
    param(
        [string]$Prompt,
        [double]$DefaultValue
    )

    while ($true) {
        $defaultText = $DefaultValue.ToString("0.###", [System.Globalization.CultureInfo]::InvariantCulture)
        $raw = Read-TimedDefaultPrompt `
            -Prompt ("{0} [{1}] (auto-selects in {2}s):" -f $Prompt, $defaultText, $script:PromptTimeoutSeconds) `
            -DefaultValue $defaultText
        if ([string]::IsNullOrWhiteSpace($raw)) {
            return $DefaultValue
        }

        $parsed = 0.0
        if (-not [double]::TryParse($raw.Trim(), [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$parsed)) {
            Write-Host "Please enter a numeric value." -ForegroundColor Yellow
            continue
        }
        if ($parsed -lt 0) {
            Write-Host "Please enter zero or a positive number." -ForegroundColor Yellow
            continue
        }

        return $parsed
    }
}

function Read-InteractiveNonNegativeInt {
    param(
        [string]$Prompt,
        [int]$DefaultValue
    )

    while ($true) {
        $defaultText = [string]$DefaultValue
        $raw = Read-TimedDefaultPrompt `
            -Prompt ("{0} [{1}] (auto-selects in {2}s):" -f $Prompt, $defaultText, $script:PromptTimeoutSeconds) `
            -DefaultValue $defaultText
        if ([string]::IsNullOrWhiteSpace($raw)) {
            return $DefaultValue
        }

        $parsed = 0
        if (-not [int]::TryParse($raw.Trim(), [ref]$parsed)) {
            Write-Host "Please enter a whole number." -ForegroundColor Yellow
            continue
        }
        if ($parsed -lt 0) {
            Write-Host "Please enter zero or a positive number." -ForegroundColor Yellow
            continue
        }

        return $parsed
    }
}

function Read-InteractiveEvidenceFrameOffsets {
    param([string[]]$DefaultValues)

    $defaultText = @($DefaultValues) -join ","
    while ($true) {
        $raw = Read-TimedDefaultPrompt `
            -Prompt ("Frame offsets in seconds relative to marker [{0}] (auto-selects in {1}s):" -f $defaultText, $script:PromptTimeoutSeconds) `
            -DefaultValue $defaultText
        if ([string]::IsNullOrWhiteSpace($raw)) {
            return @($DefaultValues)
        }

        try {
            $null = Resolve-EvidenceFrameOffsets -Values @($raw)
            return @($raw)
        }
        catch {
            Write-Host $_.Exception.Message -ForegroundColor Yellow
        }
    }
}

function Read-InteractiveEvidencePanelCropMode {
    param([string]$DefaultValue = "Auto")

    while ($true) {
        $raw = Read-TimedDefaultPrompt `
            -Prompt ("5760x1080 NVIDIA Surround panel crops [Auto/On/Off, blank for {0}] (auto-selects in {1}s):" -f $DefaultValue, $script:PromptTimeoutSeconds) `
            -DefaultValue $DefaultValue
        if ([string]::IsNullOrWhiteSpace($raw)) {
            return $DefaultValue
        }

        $value = $raw.Trim()
        if ($value -match '^(?i)(auto|on|off)$') {
            return ((Get-Culture).TextInfo.ToTitleCase($value.ToLowerInvariant()))
        }

        Write-Host "Enter Auto, On, or Off." -ForegroundColor Yellow
    }
}

function Get-InteractiveCodexEvidenceSettings {
    param(
        [double]$DefaultPreContextSeconds,
        [double]$DefaultPostContextSeconds,
        [double]$DefaultNarrationContextPreSeconds,
        [double]$DefaultNarrationContextPostSeconds,
        [double]$DefaultNarrationPauseThresholdSeconds,
        [bool]$DefaultNarrationStopAtNextTicketBoundary,
        [bool]$DefaultFragmentedNarrationMode,
        [string[]]$DefaultFrameOffsets,
        [double]$DefaultFrameCadenceSeconds,
        [int]$DefaultMaxFramesPerCandidate,
        [int]$DefaultMaxItems,
        [string]$DefaultPanelCropMode = "Auto"
    )

    Write-Host ""
    Write-Host "Codex evidence package settings:" -ForegroundColor Cyan
    Write-Host ("  Pre-context:  {0} seconds before each marker" -f $DefaultPreContextSeconds) -ForegroundColor Cyan
    Write-Host ("  Post-context: {0} seconds after each marker" -f $DefaultPostContextSeconds) -ForegroundColor Cyan
    Write-Host ("  Narration context: {0} seconds before / {1} seconds after (transcript only)" -f $DefaultNarrationContextPreSeconds, $DefaultNarrationContextPostSeconds) -ForegroundColor Cyan
    Write-Host ("  Fragmented narration: {0}; pause threshold: {1}s; stop at next ticket boundary: {2}" -f $DefaultFragmentedNarrationMode, $DefaultNarrationPauseThresholdSeconds, $DefaultNarrationStopAtNextTicketBoundary) -ForegroundColor Cyan
    Write-Host ("  Frame offsets: {0}" -f (@($DefaultFrameOffsets) -join ",")) -ForegroundColor Cyan
    Write-Host ("  Frame cadence: every {0} seconds, capped at {1} frames per candidate" -f $DefaultFrameCadenceSeconds, $DefaultMaxFramesPerCandidate) -ForegroundColor Cyan
    Write-Host ("  Max candidate items: {0}" -f $DefaultMaxItems) -ForegroundColor Cyan
    Write-Host ("  5760x1080 NVIDIA Surround panel crops: {0}" -f (Get-EvidencePanelCropModeSummary -Mode $DefaultPanelCropMode)) -ForegroundColor Cyan
    Write-Host "Recommended balanced context: 2 minutes before / 4 minutes after. Press Enter to use this, or N to customize." -ForegroundColor Cyan
    $useRecommended = Read-TimedYesNoPrompt `
        -Prompt ("Use recommended evidence settings? (Y/n, auto-selects Y in {0}s):" -f $script:PromptTimeoutSeconds) `
        -DefaultYes $true

    if ($useRecommended) {
        return [PSCustomObject]@{
            PreContextSeconds        = $DefaultPreContextSeconds
            PostContextSeconds       = $DefaultPostContextSeconds
            NarrationContextPreSeconds = $DefaultNarrationContextPreSeconds
            NarrationContextPostSeconds = $DefaultNarrationContextPostSeconds
            NarrationPauseThresholdSeconds = $DefaultNarrationPauseThresholdSeconds
            NarrationStopAtNextTicketBoundary = $DefaultNarrationStopAtNextTicketBoundary
            FragmentedNarrationMode = $DefaultFragmentedNarrationMode
            FrameOffsets             = @($DefaultFrameOffsets)
            FrameCadenceSeconds      = $DefaultFrameCadenceSeconds
            MaxFramesPerCandidate    = $DefaultMaxFramesPerCandidate
            MaxItems                 = $DefaultMaxItems
            PanelCropMode            = $DefaultPanelCropMode
        }
    }
    return [PSCustomObject]@{
        PreContextSeconds        = Read-InteractiveNonNegativeDouble -Prompt "Seconds before marker to include" -DefaultValue $DefaultPreContextSeconds
        PostContextSeconds       = Read-InteractiveNonNegativeDouble -Prompt "Seconds after marker to include" -DefaultValue $DefaultPostContextSeconds
        NarrationContextPreSeconds = Read-InteractiveNonNegativeDouble -Prompt "Transcript-only narration seconds before marker" -DefaultValue $DefaultNarrationContextPreSeconds
        NarrationContextPostSeconds = Read-InteractiveNonNegativeDouble -Prompt "Transcript-only narration seconds after marker" -DefaultValue $DefaultNarrationContextPostSeconds
        NarrationPauseThresholdSeconds = Read-InteractiveNonNegativeDouble -Prompt "Seconds of silence treated as a driving pause" -DefaultValue $DefaultNarrationPauseThresholdSeconds
        NarrationStopAtNextTicketBoundary = Read-TimedYesNoPrompt -Prompt ("Stop narration context at the next explicit ticket boundary? (Y/n, auto-selects Y in {0}s):" -f $script:PromptTimeoutSeconds) -DefaultYes $DefaultNarrationStopAtNextTicketBoundary
        FragmentedNarrationMode = Read-TimedYesNoPrompt -Prompt ("Keep longer transcript-only context for fragmented driving narration? (Y/n, auto-selects Y in {0}s):" -f $script:PromptTimeoutSeconds) -DefaultYes $DefaultFragmentedNarrationMode
        FrameOffsets             = @(Read-InteractiveEvidenceFrameOffsets -DefaultValues @($DefaultFrameOffsets))
        FrameCadenceSeconds      = Read-InteractiveNonNegativeDouble -Prompt "Seconds between candidate-window frame samples" -DefaultValue $DefaultFrameCadenceSeconds
        MaxFramesPerCandidate    = Read-InteractiveNonNegativeInt -Prompt "Maximum frames per candidate" -DefaultValue $DefaultMaxFramesPerCandidate
        MaxItems                 = Read-InteractiveNonNegativeInt -Prompt "Maximum candidate ticket items to keep" -DefaultValue $DefaultMaxItems
        PanelCropMode            = Read-InteractiveEvidencePanelCropMode -DefaultValue $DefaultPanelCropMode
    }
}

function Format-DurationHuman {
    param([double]$Seconds)

    if ($Seconds -lt 0) { $Seconds = 0 }
    $ts = [TimeSpan]::FromSeconds([math]::Round($Seconds))
    if ($ts.TotalHours -ge 1) {
        return "{0:0}h {1:00}m {2:00}s" -f [math]::Floor($ts.TotalHours), $ts.Minutes, $ts.Seconds
    }
    elseif ($ts.TotalMinutes -ge 1) {
        return "{0:0}m {1:00}s" -f [math]::Floor($ts.TotalMinutes), $ts.Seconds
    }
    else {
        return "{0:0}s" -f [math]::Floor($ts.TotalSeconds)
    }
}

function Get-LocalWhisperModelFamily {
    param([string]$ModelName)

    $normalized = if ([string]::IsNullOrWhiteSpace($ModelName)) {
        ""
    }
    else {
        $ModelName.Trim().ToLowerInvariant()
    }

    if ($normalized.EndsWith(".en")) {
        $normalized = $normalized.Substring(0, $normalized.Length - 3)
    }

    foreach ($family in @("tiny", "base", "small", "medium", "large", "turbo")) {
        if ($normalized -eq $family -or
            $normalized.StartsWith($family + "-") -or
            $normalized.StartsWith($family + ".") -or
            $normalized.StartsWith($family + "_")) {
            return $family
        }
    }

    return "default"
}

function Get-LocalWhisperRuntimeProfile {
    param(
        [string]$ModelName,
        [bool]$CanUseWhisperGpu
    )

    $profiles = @{
        cpu = @{
            tiny    = @{ Rtf = 0.75; StartupSeconds = 15.0 }
            base    = @{ Rtf = 1.00; StartupSeconds = 20.0 }
            small   = @{ Rtf = 1.40; StartupSeconds = 30.0 }
            medium  = @{ Rtf = 2.60; StartupSeconds = 45.0 }
            large   = @{ Rtf = 5.50; StartupSeconds = 75.0 }
            turbo   = @{ Rtf = 1.10; StartupSeconds = 25.0 }
            default = @{ Rtf = 3.00; StartupSeconds = 45.0 }
        }
        gpu = @{
            tiny    = @{ Rtf = 0.15; StartupSeconds = 10.0 }
            base    = @{ Rtf = 0.20; StartupSeconds = 12.0 }
            small   = @{ Rtf = 0.28; StartupSeconds = 20.0 }
            medium  = @{ Rtf = 0.45; StartupSeconds = 30.0 }
            large   = @{ Rtf = 0.90; StartupSeconds = 45.0 }
            turbo   = @{ Rtf = 0.22; StartupSeconds = 18.0 }
            default = @{ Rtf = 0.60; StartupSeconds = 30.0 }
        }
    }

    $runtimeKey = if ($CanUseWhisperGpu) { "gpu" } else { "cpu" }
    $modelFamily = Get-LocalWhisperModelFamily -ModelName $ModelName
    $selected = if ($profiles[$runtimeKey].ContainsKey($modelFamily)) {
        $profiles[$runtimeKey][$modelFamily]
    }
    else {
        $profiles[$runtimeKey]["default"]
    }

    return [PSCustomObject]@{
        RuntimeKey       = $runtimeKey
        RuntimePathLabel = if ($CanUseWhisperGpu) { "GPU-capable" } else { "CPU-only" }
        ModelFamily      = $modelFamily
        Rtf              = [double]$selected.Rtf
        StartupSeconds   = [double]$selected.StartupSeconds
    }
}

function Get-LocalWhisperCalibrationRecommendation {
    param(
        [double]$SourceDurationSeconds,
        [double]$EstimatedRuntimeSeconds,
        [string]$ModelName,
        [bool]$CanUseWhisperGpu
    )

    $duration = [math]::Max(0.0, [double]$SourceDurationSeconds)
    $estimate = [math]::Max(0.0, [double]$EstimatedRuntimeSeconds)
    $modelFamily = Get-LocalWhisperModelFamily -ModelName $ModelName

    if ($duration -le 0) {
        return [PSCustomObject]@{
            Recommended  = $false
            SampleSeconds = 0
            Reason       = "source duration was unavailable"
        }
    }

    if ($duration -lt 900.0) {
        return [PSCustomObject]@{
            Recommended   = $false
            SampleSeconds = 0
            Reason        = "source media is short enough that a calibration pass would add unnecessary overhead"
        }
    }

    $shouldForce = (-not $CanUseWhisperGpu -and $modelFamily -eq "large" -and $duration -ge 600.0)
    if (-not $shouldForce -and $estimate -lt 1800.0) {
        return [PSCustomObject]@{
            Recommended   = $false
            SampleSeconds = 0
            Reason        = "the heuristic estimate is not long enough to justify a separate calibration sample"
        }
    }

    return [PSCustomObject]@{
        Recommended   = $true
        SampleSeconds = [int][math]::Round([math]::Min(60.0, [math]::Max(30.0, $duration * 0.02)))
        Reason        = "long local runs benefit from a short machine-local calibration sample"
    }
}

function Test-LocalWhisperCalibrationStatusIsWarningWorthy {
    param([string]$Status)

    if ([string]::IsNullOrWhiteSpace($Status)) {
        return $false
    }

    $normalized = $Status.Trim().ToLowerInvariant()
    foreach ($marker in @(
            "short enough",
            "not long enough",
            "used short-sample calibration",
            "explicit -whispertimeoutseconds override"
        )) {
        if ($normalized.Contains($marker)) {
            return $false
        }
    }

    return $true
}

function Get-LocalWhisperAdaptiveRuntimePlanFallback {
    param(
        [double]$SourceDurationSeconds,
        [string]$ModelName,
        [bool]$CanUseWhisperGpu,
        [int]$HeartbeatSeconds = 10,
        [int]$WhisperTimeoutSeconds = 0,
        [string]$Task = "transcribe",
        [psobject]$CalibrationData = $null,
        [string]$CalibrationStatus = "",
        [double]$EffectiveDurationSeconds = 0,
        [int]$AudioTrackCount = 0,
        [string]$TranscriptAudioModeResolved = ""
    )

    $sourceDuration = [math]::Max(0.0, [double]$SourceDurationSeconds)
    $effectiveDuration = [math]::Max(0.0, [double]$EffectiveDurationSeconds)
    if ($effectiveDuration -le 0) {
        $effectiveDuration = $sourceDuration
    }
    $duration = $effectiveDuration
    $heartbeat = [math]::Max(1, [int]$HeartbeatSeconds)
    $explicitTimeout = [math]::Max(0, [int]$WhisperTimeoutSeconds)
    $trackCount = [math]::Max(0, [int]$AudioTrackCount)
    $profile = Get-LocalWhisperRuntimeProfile -ModelName $ModelName -CanUseWhisperGpu $CanUseWhisperGpu
    $taskFactor = if ($Task -eq "translate") { 1.05 } else { 1.00 }
    $fallbackRtf = [double]$profile.Rtf * $taskFactor
    $startupSeconds = [double]$profile.StartupSeconds

    if ($duration -gt 0) {
        $fallbackEstimate = [math]::Max(30.0, $startupSeconds + ($duration * $fallbackRtf))
    }
    else {
        $fallbackEstimate = [math]::Max(30.0, $startupSeconds + (900.0 * $fallbackRtf))
    }

    $estimate = $fallbackEstimate
    $estimateSource = "heuristic_profile"
    $calibrationUsed = $false
    $observedRtf = 0.0
    $calibrationClipSeconds = 0.0
    $calibrationElapsedSeconds = 0.0
    $effectiveCalibrationStatus = $CalibrationStatus

    if ($CalibrationData) {
        $calibrationClipSeconds = [math]::Max(0.0, [double]$CalibrationData.SampleDurationSeconds)
        $calibrationElapsedSeconds = [math]::Max(0.0, [double]$CalibrationData.ElapsedSeconds)

        if ($calibrationClipSeconds -gt 0 -and $calibrationElapsedSeconds -gt 0) {
            $rawProcessingSeconds = [math]::Max($calibrationClipSeconds * 0.25, $calibrationElapsedSeconds - $startupSeconds)
            $observedRtf = [math]::Max($fallbackRtf * 0.80, $rawProcessingSeconds / $calibrationClipSeconds)
            $estimate = [math]::Max($fallbackEstimate * 0.90, $startupSeconds + ($duration * $observedRtf))
            $estimateSource = "sample_calibration"
            $calibrationUsed = $true
            $effectiveCalibrationStatus = "used short-sample calibration"
        }
        elseif ($CalibrationData.PSObject.Properties["Reason"] -and -not [string]::IsNullOrWhiteSpace([string]$CalibrationData.Reason)) {
            $effectiveCalibrationStatus = [string]$CalibrationData.Reason
        }
    }

    $recommendation = Get-LocalWhisperCalibrationRecommendation `
        -SourceDurationSeconds $duration `
        -EstimatedRuntimeSeconds $estimate `
        -ModelName $ModelName `
        -CanUseWhisperGpu $CanUseWhisperGpu

    $budgetMarginSeconds = [math]::Max(1800.0, $estimate * 1.5)
    $adaptiveTimeoutSeconds = [int][math]::Ceiling($estimate + $budgetMarginSeconds)
    $resolvedTimeoutSeconds = if ($explicitTimeout -gt 0) { $explicitTimeout } else { $adaptiveTimeoutSeconds }
    $baseStallSeconds = [math]::Max(240, $heartbeat * 12)

    if ($resolvedTimeoutSeconds -gt 120) {
        $stallTimeoutSeconds = [math]::Max(60, [math]::Min($baseStallSeconds, $resolvedTimeoutSeconds - 30))
    }
    else {
        $stallTimeoutSeconds = [math]::Max(30, [math]::Min($baseStallSeconds, [math]::Max(30, $resolvedTimeoutSeconds - 10)))
    }

    $warnings = New-Object System.Collections.Generic.List[string]
    if ($calibrationUsed) {
        [void]$warnings.Add("Adaptive hard runtime budget was refined with a short calibration sample and still includes conservative padding.")
    }
    elseif (Test-LocalWhisperCalibrationStatusIsWarningWorthy -Status $effectiveCalibrationStatus) {
        [void]$warnings.Add(("Calibration skipped or unavailable: {0}." -f $effectiveCalibrationStatus))
    }
    if ($explicitTimeout -gt 0) {
        [void]$warnings.Add("Explicit -WhisperTimeoutSeconds override is active and wins over the adaptive hard runtime budget.")
    }

    return [PSCustomObject]@{
        SourceDurationSeconds           = [int][math]::Round($sourceDuration)
        EffectiveDurationSeconds        = [int][math]::Round($effectiveDuration)
        AudioTrackCount                 = [int]$trackCount
        TranscriptAudioModeResolved     = [string]$TranscriptAudioModeResolved
        ModelName                       = $ModelName
        ModelFamily                     = $profile.ModelFamily
        RuntimePath                     = $profile.RuntimeKey
        RuntimePathLabel                = $profile.RuntimePathLabel
        TaskName                        = $Task
        EstimatedRuntimeSeconds         = [int][math]::Ceiling($estimate)
        FallbackEstimateSeconds         = [int][math]::Ceiling($fallbackEstimate)
        AdaptiveTimeoutSeconds          = $adaptiveTimeoutSeconds
        ResolvedTimeoutSeconds          = $resolvedTimeoutSeconds
        StallTimeoutSeconds             = [int]$stallTimeoutSeconds
        BudgetMarginSeconds             = [int][math]::Ceiling($resolvedTimeoutSeconds - $estimate)
        HeartbeatSeconds                = $heartbeat
        EstimateSource                  = $estimateSource
        TimeoutSource                   = if ($explicitTimeout -gt 0) { "explicit_override" } else { "adaptive_runtime_budget" }
        FallbackRtf                     = [math]::Round($fallbackRtf, 3)
        StartupSeconds                  = [int][math]::Round($startupSeconds)
        CalibrationUsed                 = $calibrationUsed
        CalibrationStatus               = $effectiveCalibrationStatus
        CalibrationClipSeconds          = [int][math]::Round($calibrationClipSeconds)
        CalibrationElapsedSeconds       = [int][math]::Ceiling($calibrationElapsedSeconds)
        ObservedRtf                     = [math]::Round($observedRtf, 3)
        CalibrationRecommended          = [bool]$recommendation.Recommended
        CalibrationSampleSeconds        = [int]$recommendation.SampleSeconds
        CalibrationRecommendationReason = [string]$recommendation.Reason
        LongRunPromptRecommended        = [bool]($duration -gt 0 -and $estimate -ge $script:LocalWhisperLongRunPromptThresholdSeconds)
        Warnings                        = @($warnings)
    }
}

function ConvertTo-LocalWhisperRuntimePlan {
    param([psobject]$Data)

    return [PSCustomObject]@{
        SourceDurationSeconds           = [int]$Data.source_duration_seconds
        EffectiveDurationSeconds        = [int]$Data.effective_duration_seconds
        AudioTrackCount                 = [int]$Data.audio_track_count
        TranscriptAudioModeResolved     = [string]$Data.transcript_audio_mode
        ModelName                       = [string]$Data.model_name
        ModelFamily                     = [string]$Data.model_family
        RuntimePath                     = [string]$Data.runtime_path
        RuntimePathLabel                = [string]$Data.runtime_path_label
        TaskName                        = [string]$Data.task_name
        EstimatedRuntimeSeconds         = [int]$Data.estimated_runtime_seconds
        FallbackEstimateSeconds         = [int]$Data.fallback_estimate_seconds
        AdaptiveTimeoutSeconds          = [int]$Data.adaptive_timeout_seconds
        ResolvedTimeoutSeconds          = [int]$Data.resolved_timeout_seconds
        StallTimeoutSeconds             = [int]$Data.stall_timeout_seconds
        BudgetMarginSeconds             = [int]$Data.budget_margin_seconds
        HeartbeatSeconds                = [int]$Data.heartbeat_seconds
        EstimateSource                  = [string]$Data.estimate_source
        TimeoutSource                   = [string]$Data.timeout_source
        FallbackRtf                     = [double]$Data.fallback_rtf
        StartupSeconds                  = [int]$Data.startup_seconds
        CalibrationUsed                 = [bool]$Data.calibration_used
        CalibrationStatus               = [string]$Data.calibration_status
        CalibrationClipSeconds          = [int]$Data.calibration_clip_seconds
        CalibrationElapsedSeconds       = [int]$Data.calibration_elapsed_seconds
        ObservedRtf                     = [double]$Data.observed_rtf
        CalibrationRecommended          = [bool]$Data.calibration_recommended
        CalibrationSampleSeconds        = [int]$Data.calibration_sample_seconds
        CalibrationRecommendationReason = [string]$Data.calibration_recommendation_reason
        LongRunPromptRecommended        = [bool]$Data.long_run_prompt_recommended
        Warnings                        = @($Data.warnings)
    }
}

function Get-LocalWhisperAdaptiveRuntimePlan {
    param(
        [string]$PythonCommand,
        [double]$SourceDurationSeconds,
        [string]$ModelName,
        [bool]$CanUseWhisperGpu,
        [int]$HeartbeatSeconds = 10,
        [int]$WhisperTimeoutSeconds = 0,
        [string]$Task = "transcribe",
        [psobject]$CalibrationData = $null,
        [string]$CalibrationStatus = "",
        [double]$EffectiveDurationSeconds = 0,
        [int]$AudioTrackCount = 0,
        [string]$TranscriptAudioModeResolved = ""
    )

    $payload = @{
        source_duration_seconds    = $SourceDurationSeconds
        effective_duration_seconds = $EffectiveDurationSeconds
        audio_track_count          = $AudioTrackCount
        transcript_audio_mode      = $TranscriptAudioModeResolved
        model_name                 = $ModelName
        gpu_capable                = $CanUseWhisperGpu
        heartbeat_seconds          = $HeartbeatSeconds
        explicit_timeout_seconds   = $WhisperTimeoutSeconds
        task_name                  = $Task
    }

    if ($CalibrationData) {
        $payload.calibration = @{
            sample_duration_seconds = [double]$CalibrationData.SampleDurationSeconds
            elapsed_seconds         = [double]$CalibrationData.ElapsedSeconds
        }
    }
    elseif (-not [string]::IsNullOrWhiteSpace($CalibrationStatus)) {
        $payload.calibration = @{
            reason = $CalibrationStatus
        }
    }

    $cliResult = Invoke-MediaManglersPythonCli `
        -PythonCommand $PythonCommand `
        -Command "whisper-plan" `
        -Payload $payload `
        -StepName "Whisper runtime planning" `
        -HeartbeatSeconds 0 `
        -TimeoutSeconds 60

    if ($cliResult) {
        if ($cliResult.ExitCode -eq 0 -and $cliResult.Result -and $cliResult.Result.ok) {
            return ConvertTo-LocalWhisperRuntimePlan -Data $cliResult.Result.data
        }

        $cliError = if ($cliResult.Result -and -not [string]::IsNullOrWhiteSpace($cliResult.Result.error)) {
            [string]$cliResult.Result.error
        }
        else {
            "Tracked Python CLI helper failed before returning a result."
        }
        Write-Log ("Tracked Whisper runtime planning helper failed. Falling back to the PowerShell heuristic. {0}" -f $cliError) "WARN"
    }

    return Get-LocalWhisperAdaptiveRuntimePlanFallback `
        -SourceDurationSeconds $SourceDurationSeconds `
        -ModelName $ModelName `
        -CanUseWhisperGpu $CanUseWhisperGpu `
        -HeartbeatSeconds $HeartbeatSeconds `
        -WhisperTimeoutSeconds $WhisperTimeoutSeconds `
        -Task $Task `
        -CalibrationData $CalibrationData `
        -CalibrationStatus $CalibrationStatus `
        -EffectiveDurationSeconds $EffectiveDurationSeconds `
        -AudioTrackCount $AudioTrackCount `
        -TranscriptAudioModeResolved $TranscriptAudioModeResolved
}

function Get-LocalWhisperCalibrationCacheKey {
    param(
        [string]$AudioPath,
        [string]$ModelName,
        [bool]$CanUseWhisperGpu
    )

    $normalizedPath = if ([string]::IsNullOrWhiteSpace($AudioPath)) {
        ""
    }
    else {
        try {
            (Resolve-Path -LiteralPath $AudioPath).ProviderPath.ToLowerInvariant()
        }
        catch {
            $AudioPath.Trim().ToLowerInvariant()
        }
    }

    return ("{0}|{1}|{2}" -f $normalizedPath, $(Get-LocalWhisperModelFamily -ModelName $ModelName), $(if ($CanUseWhisperGpu) { "gpu" } else { "cpu" }))
}

function Get-LocalWhisperSmallerModelChoices {
    param([string]$ModelName)

    switch (Get-LocalWhisperModelFamily -ModelName $ModelName) {
        "large" { return @("medium", "small") }
        "medium" { return @("small") }
        default { return @() }
    }
}

function Get-InteractiveLocalWhisperLongRunDecision {
    param(
        [string]$ModelName,
        [psobject]$Plan
    )

    $smallerModels = @(Get-LocalWhisperSmallerModelChoices -ModelName $ModelName)

    while ($true) {
        Write-Host ""
        Write-Host "Local Whisper runtime warning" -ForegroundColor Yellow
        Write-Host ("Source duration:              {0}" -f (Format-DurationHuman -Seconds $Plan.SourceDurationSeconds)) -ForegroundColor Yellow
        if ($Plan.PSObject.Properties["AudioTrackCount"] -and [int]$Plan.AudioTrackCount -gt 0) {
            Write-Host ("Audio tracks detected:        {0}" -f [int]$Plan.AudioTrackCount) -ForegroundColor Yellow
        }
        if ($Plan.PSObject.Properties["TranscriptAudioModeResolved"] -and -not [string]::IsNullOrWhiteSpace([string]$Plan.TranscriptAudioModeResolved)) {
            Write-Host ("Transcript mode:              {0}" -f [string]$Plan.TranscriptAudioModeResolved) -ForegroundColor Yellow
        }
        if ($Plan.PSObject.Properties["EffectiveDurationSeconds"] -and [int]$Plan.EffectiveDurationSeconds -gt 0) {
            Write-Host ("Effective transcription work: {0}" -f (Format-DurationHuman -Seconds $Plan.EffectiveDurationSeconds)) -ForegroundColor Yellow
        }
        Write-Host ("Selected Whisper model:       {0}" -f $ModelName) -ForegroundColor Yellow
        Write-Host ("Local Whisper path:           {0}" -f $Plan.RuntimePathLabel) -ForegroundColor Yellow
        Write-Host ("Estimated transcription:      {0}" -f (Format-DurationHuman -Seconds $Plan.EstimatedRuntimeSeconds)) -ForegroundColor Yellow
        Write-Host ("Runtime budget:               {0}" -f (Format-DurationHuman -Seconds $Plan.ResolvedTimeoutSeconds)) -ForegroundColor Yellow
        Write-Host ("Stall watchdog:               {0}" -f (Format-DurationHuman -Seconds $Plan.StallTimeoutSeconds)) -ForegroundColor Yellow

        $choices = New-Object System.Collections.Generic.List[string]
        [void]$choices.Add("Press Enter to continue")
        if ($smallerModels -contains "medium") {
            [void]$choices.Add("type M for medium")
        }
        if ($smallerModels -contains "small") {
            [void]$choices.Add("type S for small")
        }
        [void]$choices.Add("type X to cancel")

        $defaultModelLabel = if ([string]::IsNullOrWhiteSpace($ModelName)) { "current" } else { $ModelName }
        $choice = Read-TimedChoicePrompt `
            -Prompt ("{0}. Auto-continues with {1}/default in {2}s:" -f ($choices -join ", "), $defaultModelLabel, $script:PromptTimeoutSeconds) `
            -DefaultValue "continue"
        if ([string]::IsNullOrWhiteSpace($choice) -or $choice.Trim().ToUpperInvariant() -eq "CONTINUE") {
            return [PSCustomObject]@{
                Action    = "continue"
                ModelName = $ModelName
            }
        }

        switch ($choice.Trim().ToUpperInvariant()) {
            "M" {
                if ($smallerModels -contains "medium") {
                    return [PSCustomObject]@{
                        Action    = "switch_model"
                        ModelName = "medium"
                    }
                }
            }
            "S" {
                if ($smallerModels -contains "small") {
                    return [PSCustomObject]@{
                        Action    = "switch_model"
                        ModelName = "small"
                    }
                }
            }
            "X" {
                return [PSCustomObject]@{
                    Action    = "cancel"
                    ModelName = $ModelName
                }
            }
        }

        Write-Host "Invalid choice. Press Enter, type M, type S, or type X." -ForegroundColor Yellow
    }
}

function Write-LocalWhisperRuntimePlanLog {
    param(
        [string]$Task,
        [string]$ModelName,
        [psobject]$Plan
    )

    $sourceDurationLabel = if ($Plan.SourceDurationSeconds -gt 0) {
        Format-DurationHuman -Seconds $Plan.SourceDurationSeconds
    }
    else {
        "unknown"
    }

    $effectiveDurationSeconds = if ($Plan.PSObject.Properties["EffectiveDurationSeconds"]) {
        [double]$Plan.EffectiveDurationSeconds
    }
    else {
        [double]$Plan.SourceDurationSeconds
    }
    $effectiveDurationLabel = if ($effectiveDurationSeconds -gt 0) {
        Format-DurationHuman -Seconds $effectiveDurationSeconds
    }
    else {
        "unknown"
    }
    $audioTrackCountLabel = if ($Plan.PSObject.Properties["AudioTrackCount"] -and [int]$Plan.AudioTrackCount -gt 0) {
        [string][int]$Plan.AudioTrackCount
    }
    else {
        "not reported"
    }
    $transcriptModeLabel = if ($Plan.PSObject.Properties["TranscriptAudioModeResolved"] -and -not [string]::IsNullOrWhiteSpace([string]$Plan.TranscriptAudioModeResolved)) {
        [string]$Plan.TranscriptAudioModeResolved
    }
    else {
        "not reported"
    }
    $workloadLabel = if ($Task -eq "translate") { "effective Whisper workload" } else { "effective transcription workload" }

    Write-Log ("Local Whisper {0} plan: source duration {1}; audio tracks {2}; transcript mode {3}; {4} {5}; model {6}; local path {7}; estimated duration {8}; hard runtime budget {9}; stall watchdog {10}; estimate source {11}." -f $Task, $sourceDurationLabel, $audioTrackCountLabel, $transcriptModeLabel, $workloadLabel, $effectiveDurationLabel, $ModelName, $Plan.RuntimePathLabel, (Format-DurationHuman -Seconds $Plan.EstimatedRuntimeSeconds), (Format-DurationHuman -Seconds $Plan.ResolvedTimeoutSeconds), (Format-DurationHuman -Seconds $Plan.StallTimeoutSeconds), $Plan.EstimateSource)

    if ($Plan.CalibrationUsed) {
        Write-Log ("Calibration sample: {0} clip completed in {1}; runtime estimate stayed conservative at about {2:0.00}x real time." -f (Format-DurationHuman -Seconds $Plan.CalibrationClipSeconds), (Format-DurationHuman -Seconds $Plan.CalibrationElapsedSeconds), $Plan.ObservedRtf)
    }
    elseif (-not [string]::IsNullOrWhiteSpace($Plan.CalibrationStatus)) {
        Write-Log ("Calibration status: {0}" -f $Plan.CalibrationStatus)
    }

    if ($Plan.TimeoutSource -eq "explicit_override") {
        Write-Log ("Using explicit -WhisperTimeoutSeconds override: {0} seconds ({1})." -f $Plan.ResolvedTimeoutSeconds, (Format-DurationHuman -Seconds $Plan.ResolvedTimeoutSeconds)) "WARN"
    }

    foreach ($warning in @($Plan.Warnings)) {
        Write-Log $warning "WARN"
    }
}

function Get-LocalWhisperPromptEstimateLabel {
    param(
        [double]$SourceDurationSeconds,
        [double]$MinMultiplier,
        [double]$MaxMultiplier
    )

    if ($SourceDurationSeconds -gt 0) {
        $minimumSeconds = [math]::Max(10.0, $SourceDurationSeconds * $MinMultiplier)
        $maximumSeconds = [math]::Max(($minimumSeconds + 5.0), ($SourceDurationSeconds * $MaxMultiplier))
        return ("about {0} to {1}" -f (Format-DurationHuman -Seconds $minimumSeconds), (Format-DurationHuman -Seconds $maximumSeconds))
    }

    return ("about {0:0.0}x to {1:0.0}x the source duration" -f $MinMultiplier, $MaxMultiplier)
}

function Test-LocalWhisperLongCpuRunRisk {
    param(
        [string]$ModelName,
        [bool]$CanUseWhisperGpu,
        [double]$DurationSeconds
    )

    if ($CanUseWhisperGpu) {
        return $false
    }

    if ($DurationSeconds -lt $script:LocalCpuLongWhisperWarningThresholdSeconds) {
        return $false
    }

    $normalizedModel = if ([string]::IsNullOrWhiteSpace($ModelName)) {
        ""
    }
    else {
        $ModelName.Trim().ToLowerInvariant()
    }

    return (
        $normalizedModel -eq "large" -or
        $normalizedModel.StartsWith("large-") -or
        $normalizedModel.StartsWith("large.") -or
        $normalizedModel.StartsWith("large_")
    )
}

function Write-LocalWhisperLongCpuRunWarning {
    param(
        [string]$ModelName,
        [double]$DurationSeconds
    )

    $durationLabel = if ($DurationSeconds -gt 0) {
        Format-DurationHuman -Seconds $DurationSeconds
    }
    else {
        "long media"
    }

    Write-Log ("This Local run is using Whisper model '{0}' on CPU for about {1}. Longer CPU-only Local Whisper runs can still take a very long time, so the script now uses an adaptive runtime budget plus a separate stall watchdog." -f $ModelName, $durationLabel) "WARN"
}

function Select-MMDistinctVideos {
    # 199: each recording once, in the order given. A recording list from Find my bug reports
    # is the operator's own order; a folder is already read in name order.
    param([array]$Videos)
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    $distinct = New-Object System.Collections.Generic.List[object]
    foreach ($video in @($Videos)) {
        if ($null -eq $video) { continue }
        if ($seen.Add([string]$video.FullName)) { [void]$distinct.Add($video) }
    }
    return @($distinct.ToArray())
}

function Get-VideoFilesFromPath {
    param(
        [string]$Path,
        [switch]$Recurse
    )

    $extensions = Get-SupportedVideoExtensions
    $Path = Normalize-UserPath -Path $Path

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Path not found: $Path"
    }

    $item = Get-Item -LiteralPath $Path

    if (-not $item.PSIsContainer -and $item.Extension -ieq ".mmlist") {
        # A recording list (one full path per line) lets the Workbench process
        # several hand-picked recordings as one package without copying them (95).
        $listed = New-Object System.Collections.Generic.List[object]
        foreach ($line in @(Get-Content -LiteralPath $item.FullName -Encoding UTF8)) {
            $entry = ([string]$line).Trim().Trim('"')
            if ([string]::IsNullOrWhiteSpace($entry) -or $entry.StartsWith("#")) { continue }
            if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) {
                throw "Recording in the list was not found: $entry"
            }
            $listedItem = Get-Item -LiteralPath $entry
            if ($extensions -contains $listedItem.Extension.ToLowerInvariant()) {
                [void]$listed.Add($listedItem)
            }
        }
        return @($listed.ToArray())
    }

    if ($item.PSIsContainer) {
        $search = if ($Recurse) {
            Get-ChildItem -LiteralPath $Path -File -Recurse
        }
        else {
            Get-ChildItem -LiteralPath $Path -File
        }
        return @($search | Where-Object { $extensions -contains $_.Extension.ToLowerInvariant() } | Sort-Object FullName)
    }

    if ($extensions -notcontains $item.Extension.ToLowerInvariant()) {
        throw "Unsupported video file type: $($item.FullName)"
    }

    return @($item)
}

function Get-SupportedVideoExtensions {
    return @(".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm")
}

function Test-PythonWhisper {
    param([string]$PythonCommand)

    $result = Invoke-ExternalCapture `
        -FilePath $PythonCommand `
        -Arguments @("-c", "import whisper; print('whisper_ok')") `
        -StepName "Python Whisper import test" `
        -IgnoreExitCode

    if ($result.ExitCode -ne 0 -or $result.StdOut -notmatch 'whisper_ok') {
        throw "Python/openai-whisper not available via '$PythonCommand'. Install with: py -m pip install -U openai-whisper (official page: $((Get-ToolSource -Key 'whisper').Page))"
    }
}

function Test-VideoHasAudio {
    param(
        [string]$FFprobeExe,
        [string]$VideoPath
    )

    $probe = Invoke-ExternalCapture `
        -FilePath $FFprobeExe `
        -Arguments @(
            "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            $VideoPath
        ) `
        -StepName "FFprobe audio stream check" `
        -IgnoreExitCode

    return ($probe.StdOut -match 'audio')
}

function Get-VideoAudioStreams {
    param(
        [string]$FFprobeExe,
        [string]$VideoPath
    )

    $probe = Invoke-ExternalCapture `
        -FilePath $FFprobeExe `
        -Arguments @(
            "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=index,codec_type,codec_name,channels,channel_layout,sample_rate,duration:stream_tags=title,language,handler_name:stream_disposition=default",
            "-of", "json",
            $VideoPath
        ) `
        -StepName "FFprobe audio stream details" `
        -IgnoreExitCode

    if ($probe.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($probe.StdOut)) {
        return @()
    }

    try {
        $payload = $probe.StdOut | ConvertFrom-Json
    }
    catch {
        Write-Log ("Unable to parse ffprobe audio stream details for '{0}': {1}" -f $VideoPath, $_.Exception.Message) "WARN"
        return @()
    }

    $streams = New-Object System.Collections.Generic.List[object]
    $ordinal = 0
    foreach ($stream in @($payload.streams)) {
        $tags = $stream.tags
        $disposition = $stream.disposition
        $trackNumber = $ordinal + 1
        $streamIndex = if ($null -ne $stream.index) { [int]$stream.index } else { $ordinal }
        $title = if ($tags -and $tags.title) { [string]$tags.title } else { "" }
        $handlerName = if ($tags -and $tags.handler_name) { [string]$tags.handler_name } else { "" }
        [void]$streams.Add([PSCustomObject]@{
            ordinal                    = $ordinal
            audio_ordinal              = ("a:{0}" -f $ordinal)
            vlc_track_number           = $trackNumber
            vlc_track_label            = ("Track {0}" -f $trackNumber)
            ffmpeg_map                 = ("0:a:{0}" -f $ordinal)
            absolute_stream_index      = $streamIndex
            absolute_stream_specifier  = ("0:{0}" -f $streamIndex)
            stream_index               = $streamIndex
            codec_name                 = [string]$stream.codec_name
            channels                   = if ($null -ne $stream.channels) { [int]$stream.channels } else { 0 }
            channel_layout             = [string]$stream.channel_layout
            sample_rate                = [string]$stream.sample_rate
            language                   = if ($tags -and $tags.language) { [string]$tags.language } else { "" }
            title                      = $title
            handler_name               = $handlerName
            duration                   = if ($null -ne $stream.duration) { [string]$stream.duration } else { "" }
            default_disposition        = if ($disposition -and $null -ne $disposition.default) { [int]$disposition.default } else { 0 }
            display                    = ("Track {0} | ffmpeg map 0:a:{1} | absolute stream 0:{2}" -f $trackNumber, $ordinal, $streamIndex)
        })
        $ordinal += 1
    }

    return @($streams.ToArray())
}

function Get-VideoPrimaryVideoStream {
    param(
        [string]$FFprobeExe,
        [string]$VideoPath
    )

    $probe = Invoke-ExternalCapture `
        -FilePath $FFprobeExe `
        -Arguments @(
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=index,codec_name,width,height",
            "-of", "json",
            $VideoPath
        ) `
        -StepName "FFprobe video stream details" `
        -IgnoreExitCode

    if ($probe.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($probe.StdOut)) {
        return [PSCustomObject]@{ Width = 0; Height = 0; CodecName = ""; StreamIndex = 0 }
    }

    try {
        $payload = $probe.StdOut | ConvertFrom-Json
        $stream = @($payload.streams | Select-Object -First 1)[0]
        if ($null -eq $stream) {
            return [PSCustomObject]@{ Width = 0; Height = 0; CodecName = ""; StreamIndex = 0 }
        }
        return [PSCustomObject]@{
            Width       = if ($null -ne $stream.width) { [int]$stream.width } else { 0 }
            Height      = if ($null -ne $stream.height) { [int]$stream.height } else { 0 }
            CodecName   = [string]$stream.codec_name
            StreamIndex = if ($null -ne $stream.index) { [int]$stream.index } else { 0 }
        }
    }
    catch {
        Write-Log ("Unable to parse ffprobe video stream details for '{0}': {1}" -f $VideoPath, $_.Exception.Message) "WARN"
        return [PSCustomObject]@{ Width = 0; Height = 0; CodecName = ""; StreamIndex = 0 }
    }
}

function Export-AudioTrackInventory {
    param(
        [array]$AudioStreams,
        [string]$JsonPath,
        [string]$CsvPath
    )

    Ensure-Directory (Split-Path -Path $JsonPath -Parent)
    $rows = @($AudioStreams | ForEach-Object {
        [PSCustomObject]@{
            vlc_track_label           = [string]$_.vlc_track_label
            vlc_track_number          = [int]$_.vlc_track_number
            audio_ordinal             = [string]$_.audio_ordinal
            ffmpeg_map                = [string]$_.ffmpeg_map
            absolute_stream_specifier = [string]$_.absolute_stream_specifier
            absolute_stream_index     = [int]$_.absolute_stream_index
            codec                     = [string]$_.codec_name
            channels                  = [int]$_.channels
            channel_layout            = [string]$_.channel_layout
            sample_rate               = [string]$_.sample_rate
            language                  = [string]$_.language
            title                     = [string]$_.title
            handler_name              = [string]$_.handler_name
            duration                  = [string]$_.duration
            default_disposition       = [int]$_.default_disposition
        }
    })

    ($rows | ConvertTo-Json -Depth 5) | Set-Content -LiteralPath $JsonPath -Encoding UTF8
    if ($rows.Count -gt 0) {
        $rows | Export-Csv -LiteralPath $CsvPath -NoTypeInformation -Encoding UTF8
    }
    else {
        [PSCustomObject]@{
            vlc_track_label           = ""
            vlc_track_number          = ""
            audio_ordinal             = ""
            ffmpeg_map                = ""
            absolute_stream_specifier = ""
            absolute_stream_index     = ""
            codec                     = ""
            channels                  = ""
            channel_layout            = ""
            sample_rate               = ""
            language                  = ""
            title                     = ""
            handler_name              = ""
            duration                  = ""
            default_disposition       = ""
        } | Export-Csv -LiteralPath $CsvPath -NoTypeInformation -Encoding UTF8
    }
}

function Write-AudioTrackInventoryToConsole {
    param([array]$AudioStreams)

    Write-Host ""
    Write-Host "Audio track inventory" -ForegroundColor Cyan
    Write-Host "---------------------" -ForegroundColor Cyan
    foreach ($stream in @($AudioStreams)) {
        $descriptor = @(
            [string]$stream.display,
            ("codec {0}" -f [string]$stream.codec_name),
            ("channels {0}" -f [string]$stream.channels),
            ("layout {0}" -f $(if ([string]::IsNullOrWhiteSpace([string]$stream.channel_layout)) { "unknown" } else { [string]$stream.channel_layout })),
            ("sample rate {0}" -f $(if ([string]::IsNullOrWhiteSpace([string]$stream.sample_rate)) { "unknown" } else { [string]$stream.sample_rate }))
        ) -join "; "
        Write-Host ("- {0}" -f $descriptor)
        if (-not [string]::IsNullOrWhiteSpace([string]$stream.title) -or -not [string]::IsNullOrWhiteSpace([string]$stream.handler_name)) {
            Write-Host ("  tags: title='{0}', handler='{1}', language='{2}'" -f [string]$stream.title, [string]$stream.handler_name, [string]$stream.language)
        }
    }
    Write-Host ""
}

function Resolve-AudioStreamSpecifier {
    param(
        [string]$Specifier,
        [array]$AudioStreams
    )

    $value = if ($null -eq $Specifier) { "" } else { $Specifier.Trim() }
    if ([string]::IsNullOrWhiteSpace($value)) {
        return $null
    }

    $ordinal = $null
    $absoluteIndex = $null
    if ($value -match '^0:a:(\d+)$') {
        $ordinal = [int]$Matches[1]
    }
    elseif ($value -match '^a:(\d+)$') {
        $ordinal = [int]$Matches[1]
    }
    elseif ($value -match '^0:(\d+)$') {
        $absoluteIndex = [int]$Matches[1]
    }
    else {
        throw "TranscriptAudioStream must look like 0:a:1, a:1, or 0:2."
    }

    if ($null -ne $ordinal) {
        $match = @($AudioStreams | Where-Object { [int]$_.ordinal -eq $ordinal } | Select-Object -First 1)
        if ($match.Count -eq 0) {
            throw ("TranscriptAudioStream '{0}' did not match a detected audio ordinal." -f $Specifier)
        }
        return $match[0]
    }

    $absoluteMatch = @($AudioStreams | Where-Object { [int]$_.absolute_stream_index -eq $absoluteIndex } | Select-Object -First 1)
    if ($absoluteMatch.Count -eq 0) {
        throw ("TranscriptAudioStream '{0}' did not match a detected audio stream." -f $Specifier)
    }
    return $absoluteMatch[0]
}

function Resolve-AudioTrackOrdinal {
    param(
        [int]$TrackOrdinal,
        [array]$AudioStreams
    )

    if ($TrackOrdinal -le 0) {
        return $null
    }

    $audioOrdinal = $TrackOrdinal - 1
    $match = @($AudioStreams | Where-Object { [int]$_.ordinal -eq $audioOrdinal } | Select-Object -First 1)
    if ($match.Count -eq 0) {
        throw ("Requested VLC-style Track {0}, but only {1} audio track(s) were detected." -f $TrackOrdinal, @($AudioStreams).Count)
    }
    return $match[0]
}

function Test-AudioStreamLooksLikeMicrophone {
    param([psobject]$AudioStream)

    $haystack = ((@(
        [string]$AudioStream.title,
        [string]$AudioStream.handler_name,
        [string]$AudioStream.language,
        [string]$AudioStream.channel_layout
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join " ").ToLowerInvariant()

    return ($haystack -match '(mic|microphone|commentary|commentator|voice|operator|crew|radio|headset|talk)')
}

function Resolve-TranscriptAudioSelection {
    param(
        [array]$AudioStreams,
        [string]$Mode,
        [string]$StreamSpecifier,
        [int]$TrackOrdinal,
        [int]$PreferredTrackOrdinal,
        [bool]$InteractiveMode
    )

    $streams = @($AudioStreams)
    if ($streams.Count -eq 0) {
        return $null
    }

    $selected = $null
    $selectedStreams = @()
    $reason = ""
    $confidence = "low"
    $warning = ""
    $normalizedMode = if ([string]::IsNullOrWhiteSpace($Mode)) { "Auto" } else { $Mode.Trim() }
    $resolvedMode = $normalizedMode
    $isAllTracks = $false

    if (-not [string]::IsNullOrWhiteSpace($StreamSpecifier)) {
        $selected = Resolve-AudioStreamSpecifier -Specifier $StreamSpecifier -AudioStreams $streams
        $selectedStreams = @($selected)
        $reason = ("explicit TranscriptAudioStream '{0}'" -f $StreamSpecifier)
        $confidence = "high"
        $resolvedMode = "Track"
    }
    elseif ($TrackOrdinal -gt 0) {
        $selected = Resolve-AudioTrackOrdinal -TrackOrdinal $TrackOrdinal -AudioStreams $streams
        $selectedStreams = @($selected)
        $reason = ("explicit TranscriptAudioTrackOrdinal Track {0}" -f $TrackOrdinal)
        $confidence = "high"
        $resolvedMode = "Track"
    }
    elseif ($normalizedMode -eq "Track") {
        throw "TranscriptAudioMode Track requires -TranscriptAudioStream or -TranscriptAudioTrackOrdinal."
    }
    elseif ($normalizedMode -eq "Mixed") {
        $selected = $streams[0]
        $selectedStreams = @($selected)
        $reason = "TranscriptAudioMode Mixed preserved the current/default first audio stream behavior"
        $confidence = if ($streams.Count -eq 1) { "medium" } else { "low" }
        if ($streams.Count -gt 1) {
            $warning = "Multiple audio tracks were detected; Mixed mode selected the first audio stream for compatibility."
        }
    }
    elseif ($PreferredTrackOrdinal -gt 0) {
        $selected = Resolve-AudioTrackOrdinal -TrackOrdinal $PreferredTrackOrdinal -AudioStreams $streams
        $selectedStreams = @($selected)
        $reason = ("preferred transcript audio track Track {0}" -f $PreferredTrackOrdinal)
        $confidence = "medium"
        $resolvedMode = "Track"
    }
    elseif ($normalizedMode -eq "All" -or $normalizedMode -eq "Auto") {
        $selected = $streams[0]
        $selectedStreams = @($streams)
        $isAllTracks = $true
        $resolvedMode = "All"
        if ($streams.Count -eq 1) {
            $reason = "TranscriptAudioMode $normalizedMode resolved to All for the single detected audio track"
            $confidence = "high"
        }
        else {
            $reason = "TranscriptAudioMode $normalizedMode resolved to All because Full Review should transcribe every detected audio track by default"
            $confidence = "high"
        }
    }
    elseif ($normalizedMode -eq "Prompt") {
        if (-not $InteractiveMode) {
            throw "TranscriptAudioMode Prompt requires an interactive run. Use Auto/All, Mixed, or Track for -NoPrompt runs."
        }
        if ($streams.Count -eq 1) {
            $selected = $streams[0]
            $selectedStreams = @($selected)
            $reason = "single audio stream available for explicit Prompt mode"
            $confidence = "high"
            $resolvedMode = "Track"
        }
        else {
            $answer = Read-TimedDefaultPrompt `
                -Prompt ("Select transcript audio by VLC-style Track number, ffmpeg map (0:a:N), or absolute stream (0:N). Press Enter for Track 1; auto-selects Track 1 in {0}s:" -f $script:PromptTimeoutSeconds) `
                -DefaultValue ""
            if ([string]::IsNullOrWhiteSpace($answer)) {
                $selected = $streams[0]
                $selectedStreams = @($selected)
                $reason = "interactive default Track 1"
                $confidence = "low"
                $warning = "Multiple tracks were detected and the operator accepted the default Track 1."
                $resolvedMode = "Track"
            }
            elseif ($answer.Trim() -match '^\d+$') {
                $selected = Resolve-AudioTrackOrdinal -TrackOrdinal ([int]$answer.Trim()) -AudioStreams $streams
                $selectedStreams = @($selected)
                $reason = ("interactive selected Track {0}" -f [int]$answer.Trim())
                $confidence = "high"
                $resolvedMode = "Track"
            }
            else {
                $selected = Resolve-AudioStreamSpecifier -Specifier $answer -AudioStreams $streams
                $selectedStreams = @($selected)
                $reason = ("interactive selected stream '{0}'" -f $answer.Trim())
                $confidence = "high"
                $resolvedMode = "Track"
            }
        }
    }

    return [PSCustomObject]@{
        SelectedStream = $selected
        SelectedStreams = @($selectedStreams)
        Mode           = $normalizedMode
        ModeResolved   = $resolvedMode
        IsAllTracks    = [bool]$isAllTracks
        Reason         = $reason
        Confidence     = $confidence
        Warning        = $warning
    }
}

function Get-VideoDurationSeconds {
    param(
        [string]$FFprobeExe,
        [string]$VideoPath
    )

    $probe = Invoke-ExternalCapture `
        -FilePath $FFprobeExe `
        -Arguments @(
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            $VideoPath
        ) `
        -StepName "FFprobe duration" `
        -IgnoreExitCode

    $raw = ($probe.StdOut | Select-Object -First 1).Trim()
    $duration = 0.0
    [void][double]::TryParse($raw, [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$duration)
    return $duration
}

function Test-FFmpegNvencSupport {
    param([string]$FFmpegExe)

    try {
        $output = & $FFmpegExe -hide_banner -encoders 2>&1 | Out-String
        return ($output -match 'h264_nvenc')
    }
    catch {
        return $false
    }
}

function Test-FFmpegCudaHwaccelSupport {
    param([string]$FFmpegExe)

    try {
        $output = & $FFmpegExe -hide_banner -hwaccels 2>&1 | Out-String
        return ($output -match 'cuda')
    }
    catch {
        return $false
    }
}

function Test-NvidiaSmiAvailable {
    try {
        $null = Get-Command "nvidia-smi" -ErrorAction Stop
        $output = & nvidia-smi -L 2>&1 | Out-String
        return (-not [string]::IsNullOrWhiteSpace($output) -and $output -match 'GPU')
    }
    catch {
        return $false
    }
}

function Get-WhisperExecutionMode {
    param([string]$PythonCommand)

    $cliResult = Invoke-MediaManglersPythonCli `
        -PythonCommand $PythonCommand `
        -Command "whisper-probe" `
        -Payload @{} `
        -StepName "Whisper GPU capability probe"

    if ($cliResult) {
        if ($cliResult.ExitCode -eq 0 -and $cliResult.Result -and $cliResult.Result.ok) {
            $data = $cliResult.Result.data
            return [PSCustomObject]@{
                WhisperImportOk = [bool]$data.whisper_import_ok
                TorchImportOk   = [bool]$data.torch_import_ok
                CudaAvailable   = [bool]$data.cuda_available
                Device          = [string]$data.device
                SelectedDevice  = [string]$data.selected_device
                SelectedDeviceName = [string]$data.selected_device_name
                CudaDeviceCount = [int]$data.cuda_device_count
                CudaDeviceNames = @($data.cuda_device_names | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } | ForEach-Object { [string]$_ })
                TorchVersion    = [string]$data.torch_version
                CudaVersion     = [string]$data.cuda_version
                PythonPath      = [string]$data.python_path
                PythonVersion   = [string]$data.python_version
                Error           = [string]$data.error
            }
        }

        $cliError = if ($cliResult.Result -and -not [string]::IsNullOrWhiteSpace($cliResult.Result.error)) {
            [string]$cliResult.Result.error
        }
        else {
            "Tracked Python CLI helper failed before returning a result."
        }
        Write-Log ("Tracked Python whisper probe failed. Falling back to the legacy inline helper. {0}" -f $cliError) "WARN"
    }

    $tempPy = Get-MMScratchPath -Prefix "media_manglers_whisper_probe" -Extension ".py"

$pyCode = @'
print("[PY-PROBE] Python process started", flush=True)
import json
import sys

result = {
    "python_path": sys.executable,
    "python_version": sys.version.split()[0],
    "whisper_import_ok": False,
    "torch_import_ok": False,
    "cuda_available": False,
    "device": "cpu",
    "selected_device": "cpu",
    "selected_device_name": "",
    "cuda_device_count": 0,
    "cuda_device_names": [],
    "torch_version": None,
    "cuda_version": None,
    "error": None
}

try:
    print("[PY-PROBE] Importing whisper...", flush=True)
    import whisper
    result["whisper_import_ok"] = True
except Exception as ex:
    result["error"] = f"whisper import failed: {ex}"

try:
    print("[PY-PROBE] Importing torch...", flush=True)
    import torch
    result["torch_import_ok"] = True
    result["torch_version"] = getattr(torch, "__version__", None)
    result["cuda_version"] = getattr(torch.version, "cuda", None)
    result["cuda_available"] = bool(torch.cuda.is_available())
    result["selected_device"] = "cuda" if result["cuda_available"] else "cpu"
    result["device"] = result["selected_device"]
    try:
        result["cuda_device_count"] = int(torch.cuda.device_count())
    except Exception:
        result["cuda_device_count"] = 0
    if result["cuda_available"] and result["cuda_device_count"] > 0:
        for index in range(result["cuda_device_count"]):
            try:
                device_name = str(torch.cuda.get_device_name(index) or "").strip()
            except Exception:
                device_name = ""
            if device_name:
                result["cuda_device_names"].append(device_name)
        if result["cuda_device_names"]:
            result["selected_device_name"] = result["cuda_device_names"][0]
except Exception as ex:
    if result["error"]:
        result["error"] += f" | torch import failed: {ex}"
    else:
        result["error"] = f"torch import failed: {ex}"

print(json.dumps(result), flush=True)
'@

    Set-Content -Path $tempPy -Value $pyCode -Encoding UTF8

    try {
        $raw = Invoke-ExternalCapture `
            -FilePath $PythonCommand `
            -Arguments @($tempPy) `
            -StepName "Whisper GPU capability probe" `
            -IgnoreExitCode

        if ($raw.ExitCode -ne 0) {
            return [PSCustomObject]@{
                WhisperImportOk = $false
                TorchImportOk   = $false
                CudaAvailable   = $false
                Device          = "cpu"
                SelectedDevice  = "cpu"
                SelectedDeviceName = ""
                CudaDeviceCount = 0
                CudaDeviceNames = @()
                TorchVersion    = ""
                CudaVersion     = ""
                PythonPath      = $PythonCommand
                PythonVersion   = ""
                Error           = "Python probe failed. See log."
            }
        }

        $parsedJsonLine = ($raw.StdOut -split "`r?`n" | Where-Object { $_.Trim().StartsWith("{") -and $_.Trim().EndsWith("}") } | Select-Object -Last 1)
        if (-not $parsedJsonLine) {
            throw "Probe did not return valid JSON."
        }

        $parsed = $parsedJsonLine | ConvertFrom-Json

        return [PSCustomObject]@{
            WhisperImportOk = [bool]$parsed.whisper_import_ok
            TorchImportOk   = [bool]$parsed.torch_import_ok
            CudaAvailable   = [bool]$parsed.cuda_available
            Device          = [string]$parsed.device
            SelectedDevice  = [string]$parsed.selected_device
            SelectedDeviceName = [string]$parsed.selected_device_name
            CudaDeviceCount = [int]$parsed.cuda_device_count
            CudaDeviceNames = @($parsed.cuda_device_names | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } | ForEach-Object { [string]$_ })
            TorchVersion    = [string]$parsed.torch_version
            CudaVersion     = [string]$parsed.cuda_version
            PythonPath      = [string]$parsed.python_path
            PythonVersion   = [string]$parsed.python_version
            Error           = [string]$parsed.error
        }
    }
    catch {
        return [PSCustomObject]@{
            WhisperImportOk = $false
            TorchImportOk   = $false
            CudaAvailable   = $false
            Device          = "cpu"
            SelectedDevice  = "cpu"
            SelectedDeviceName = ""
            CudaDeviceCount = 0
            CudaDeviceNames = @()
            TorchVersion    = ""
            CudaVersion     = ""
            PythonPath      = $PythonCommand
            PythonVersion   = ""
            Error           = $_.Exception.Message
        }
    }
    finally {
        if (Test-Path $tempPy) {
            Remove-Item $tempPy -Force -ErrorAction SilentlyContinue
        }
    }
}

function Get-WhisperProbeDeviceNames {
    param([psobject]$WhisperProbe)

    $deviceNames = New-Object System.Collections.Generic.List[string]
    if ($null -eq $WhisperProbe) {
        return @()
    }

    if ($null -ne $WhisperProbe.PSObject.Properties["CudaDeviceNames"]) {
        foreach ($deviceName in @($WhisperProbe.CudaDeviceNames)) {
            $trimmed = [string]$deviceName
            if (-not [string]::IsNullOrWhiteSpace($trimmed)) {
                $deviceNames.Add($trimmed.Trim())
            }
        }
    }

    if ($deviceNames.Count -eq 0 -and -not [string]::IsNullOrWhiteSpace([string]$WhisperProbe.SelectedDeviceName)) {
        $deviceNames.Add(([string]$WhisperProbe.SelectedDeviceName).Trim())
    }

    return @($deviceNames | Select-Object -Unique)
}

function Get-WhisperProbeAssessment {
    param([psobject]$WhisperProbe)

    $deviceNames = @(Get-WhisperProbeDeviceNames -WhisperProbe $WhisperProbe)
    $deviceNamesText = if ($deviceNames.Count -gt 0) { $deviceNames -join ", " } else { "none" }

    $code = "misconfigured_or_uncertain"
    $label = "Local Whisper runtime misconfigured or uncertain"
    $summary = "The selected Python runtime is not ready for a trustworthy Local Whisper run yet."
    $action = "Fix the selected Python runtime before starting a long Local Whisper run."
    $isReady = $false

    if ($WhisperProbe -and $WhisperProbe.WhisperImportOk -and $WhisperProbe.TorchImportOk -and $WhisperProbe.CudaAvailable) {
        if ($deviceNames.Count -gt 0 -or [int]$WhisperProbe.CudaDeviceCount -gt 0) {
            $code = "gpu_capable_for_whisper"
            $label = "GPU-capable for Local Whisper"
            $summary = "This machine can run Local Whisper on CUDA in the selected Python runtime."
            $action = "You can use this box for real CUDA Local Whisper runs."
            $isReady = $true
        }
        else {
            $summary = "PyTorch reported CUDA available, but no CUDA devices were reported by the selected Python runtime."
            $action = "Treat this machine as uncertain and repair the Python/CUDA runtime before a long Local Whisper run."
        }
    }
    elseif ($WhisperProbe -and $WhisperProbe.WhisperImportOk -and $WhisperProbe.TorchImportOk) {
        $code = "cpu_only_for_whisper"
        $label = "CPU-only for Local Whisper"
        $summary = "This machine can run Local Whisper on CPU, but CUDA is not available in the selected Python runtime."
        $action = "CPU-only validation is fine here. Use a separate GPU-capable box for real CUDA sign-off."
        $isReady = $true
    }
    elseif ($WhisperProbe -and $WhisperProbe.WhisperImportOk -and -not $WhisperProbe.TorchImportOk) {
        $summary = "Whisper imported, but PyTorch did not import cleanly in the selected Python runtime."
        $action = "Repair the PyTorch install or pick a different Python interpreter before starting Local Whisper."
    }
    elseif ($WhisperProbe -and $WhisperProbe.TorchImportOk -and -not $WhisperProbe.WhisperImportOk) {
        $summary = "PyTorch imported, but whisper did not import cleanly in the selected Python runtime."
        $action = "Install or repair openai-whisper before starting Local Whisper."
    }

    return [PSCustomObject]@{
        Code            = $code
        Label           = $label
        Summary         = $summary
        Action          = $action
        IsReady         = $isReady
        DeviceNames     = @($deviceNames)
        DeviceNamesText = $deviceNamesText
    }
}

function Write-WhisperProbeReport {
    param(
        [psobject]$WhisperProbe,
        [bool]$IncludeNvidiaPresence = $false,
        [bool]$NvidiaPresent = $false,
        [bool]$EmitLogOutput = $true
    )

    $assessment = Get-WhisperProbeAssessment -WhisperProbe $WhisperProbe

    if ($IncludeNvidiaPresence) {
        Write-Host ("NVIDIA GPU detected (nvidia-smi): {0}" -f $(if ($NvidiaPresent) { "Yes" } else { "No" }))
    }

    Write-Host ("Whisper runtime health:          {0}" -f $assessment.Label)
    Write-Host ("Whisper health summary:          {0}" -f $assessment.Summary)
    Write-Host ("Whisper next step:               {0}" -f $assessment.Action)
    Write-Host ("Selected Python interpreter:     {0}" -f $(if ($WhisperProbe.PythonPath) { $WhisperProbe.PythonPath } else { "unknown" }))
    Write-Host ("Python runtime version:          {0}" -f $(if ($WhisperProbe.PythonVersion) { $WhisperProbe.PythonVersion } else { "unknown" }))
    Write-Host ("PyTorch version:                 {0}" -f $(if ($WhisperProbe.TorchVersion) { $WhisperProbe.TorchVersion } else { "unavailable" }))
    Write-Host ("PyTorch CUDA version:            {0}" -f $(if ($WhisperProbe.CudaVersion) { $WhisperProbe.CudaVersion } else { "unavailable" }))
    Write-Host ("cuda_available:                  {0}" -f $(if ($WhisperProbe.CudaAvailable) { "true" } else { "false" }))
    Write-Host ("Detected GPU devices:            {0}" -f $assessment.DeviceNamesText)
    Write-Host ("Selected Local Whisper device:   {0}" -f $(if ($WhisperProbe.SelectedDevice) { $WhisperProbe.SelectedDevice } else { "unknown" }))
    if ($WhisperProbe.Error) {
        Write-Host ("Whisper probe notes:             {0}" -f $WhisperProbe.Error)
    }

    if ($EmitLogOutput) {
        Write-Log ("Whisper runtime health: {0}. {1}" -f $assessment.Label, $assessment.Summary)
        Write-Log ("Whisper runtime action: {0}" -f $assessment.Action)
        Write-Log ("Whisper runtime probe: selected Python interpreter {0}; python version {1}; torch version {2}; torch CUDA version {3}; cuda_available {4}; detected GPU devices {5}; selected Local Whisper device {6}." -f `
            $(if ($WhisperProbe.PythonPath) { $WhisperProbe.PythonPath } else { "unknown" }), `
            $(if ($WhisperProbe.PythonVersion) { $WhisperProbe.PythonVersion } else { "unknown" }), `
            $(if ($WhisperProbe.TorchVersion) { $WhisperProbe.TorchVersion } else { "unavailable" }), `
            $(if ($WhisperProbe.CudaVersion) { $WhisperProbe.CudaVersion } else { "unavailable" }), `
            $(if ($WhisperProbe.CudaAvailable) { "true" } else { "false" }), `
            $assessment.DeviceNamesText, `
            $(if ($WhisperProbe.SelectedDevice) { $WhisperProbe.SelectedDevice } else { "unknown" }))
        if ($WhisperProbe.Error) {
            Write-Log ("Whisper runtime probe notes: {0}" -f $WhisperProbe.Error) "WARN"
        }
    }

    return $assessment
}

function Invoke-WhisperHealthCheck {
    param(
        [string]$PythonCommand,
        [bool]$PythonLauncherWasExplicit = $false
    )

    $nvidiaPresent = Test-NvidiaSmiAvailable
    $whisperProbe = $null
    if (-not $PythonLauncherWasExplicit) {
        $pythonSelection = Select-PreferredWhisperPythonInterpreter -PrimaryPythonCommand $PythonCommand
        if ($pythonSelection) {
            if (-not [string]::IsNullOrWhiteSpace($pythonSelection.Path)) {
                $PythonCommand = $pythonSelection.Path
            }
            $whisperProbe = $pythonSelection.Probe
            $script:PythonInterpreterResolutionNote = $pythonSelection.Note
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($script:PythonInterpreterResolutionNote)) {
        Write-Log $script:PythonInterpreterResolutionNote "WARN"
    }

    if ($null -eq $whisperProbe) {
        $whisperProbe = Get-WhisperExecutionMode -PythonCommand $PythonCommand
    }

    Write-Host ""
    Write-Host "Local Whisper Runtime Health"
    Write-Host "----------------------------"
    $assessment = Write-WhisperProbeReport -WhisperProbe $whisperProbe -IncludeNvidiaPresence $true -NvidiaPresent $nvidiaPresent -EmitLogOutput $false
    Write-Host ""
    if ($assessment.IsReady) {
        Write-Host ("Health check result:            {0}" -f $assessment.Label) -ForegroundColor Green
        return [PSCustomObject]@{
            PythonCommand = $PythonCommand
            Probe         = $whisperProbe
            Assessment    = $assessment
        }
    }

    throw "Local Whisper runtime health check did not pass. $($assessment.Summary)"
}

function New-CodexReadme {
    param(
        [string]$ReadmePath,
        [string]$VideoFileName,
        [string]$RawPresent,
        [string]$AudioPresent,
        [double]$FrameIntervalSeconds,
        [string]$ProcessingModeSummary,
        [string]$OpenAiProjectSummary,
        [string]$TranscriptionPathDetails,
        [string]$DetectedLanguage,
        [string[]]$TranslationTargets,
        [string]$TranslationPathDetails,
        [string]$CommentsSummary,
        [string]$RemoteAudioTrackSummary,
        [string]$PackageStatus = "SUCCESS",
        [string]$TranslationStatus = "",
        [string]$TranslationNotes = "",
        [string]$NextSteps = "",
        [string]$PanelFramesSummary = "",
        [string]$PanelFramesPath = "",
        [string]$PanelFrameIndexPath = "",
        [string]$TranscriptSourceSummary = "",
        [string]$TranscriptSourceMetadataPath = "",
        [string]$TranscriptSourceManifestPath = "",
        [string]$AllAudioTracksTranscriptPath = "",
        [string]$AllAudioTracksIndexPath = "",
        [string]$AllAudioTracksManifestPath = "",
        [string]$PythonCommand = ""
    )

    $framesFolderName = Get-FramesFolderName -Value $FrameIntervalSeconds
    $packageRoot = Split-Path -Path $ReadmePath -Parent
    $PanelFramesPath = Get-PortablePackagePath -PackageRoot $packageRoot -TargetPath $PanelFramesPath
    $PanelFrameIndexPath = Get-PortablePackagePath -PackageRoot $packageRoot -TargetPath $PanelFrameIndexPath
    $TranscriptSourceMetadataPath = Get-PortablePackagePath -PackageRoot $packageRoot -TargetPath $TranscriptSourceMetadataPath
    $TranscriptSourceManifestPath = Get-PortablePackagePath -PackageRoot $packageRoot -TargetPath $TranscriptSourceManifestPath
    $AllAudioTracksTranscriptPath = Get-PortablePackagePath -PackageRoot $packageRoot -TargetPath $AllAudioTracksTranscriptPath
    $AllAudioTracksIndexPath = Get-PortablePackagePath -PackageRoot $packageRoot -TargetPath $AllAudioTracksIndexPath
    $AllAudioTracksManifestPath = Get-PortablePackagePath -PackageRoot $packageRoot -TargetPath $AllAudioTracksManifestPath

    if (-not [string]::IsNullOrWhiteSpace($PythonCommand)) {
        $cliResult = $null

        try {
            $cliResult = Invoke-MediaManglersPythonCli `
                -PythonCommand $PythonCommand `
                -Command "write-package-readme" `
                -Payload @{
                    readme_kind                = "video"
                    readme_path                = $ReadmePath
                    video_file_name            = $VideoFileName
                    raw_present                = $RawPresent
                    audio_present              = $AudioPresent
                    frame_interval_display     = [string]$FrameIntervalSeconds
                    frames_folder_name         = $framesFolderName
                    processing_mode_summary    = $ProcessingModeSummary
                    openai_project_summary     = $OpenAiProjectSummary
                    transcription_path_details = $TranscriptionPathDetails
                    detected_language          = $DetectedLanguage
                    translation_targets        = @($TranslationTargets)
                    translation_path_details   = $TranslationPathDetails
                    comments_summary           = $CommentsSummary
                    remote_audio_track_summary = $RemoteAudioTrackSummary
                    package_status             = $PackageStatus
                    translation_status         = $TranslationStatus
                    translation_notes          = $TranslationNotes
                    next_steps                 = $NextSteps
                    panel_frames_summary       = $PanelFramesSummary
                    panel_frames_path          = $PanelFramesPath
                    panel_frame_index_path     = $PanelFrameIndexPath
                    transcript_source_summary  = $TranscriptSourceSummary
                    transcript_source_metadata_path = $TranscriptSourceMetadataPath
                    transcript_source_manifest_path = $TranscriptSourceManifestPath
                    all_audio_tracks_transcript_path = $AllAudioTracksTranscriptPath
                    all_audio_tracks_index_path = $AllAudioTracksIndexPath
                    all_audio_tracks_manifest_path = $AllAudioTracksManifestPath
                } `
                -StepName "Python package README writer" `
                -HeartbeatSeconds 10 `
                -TimeoutSeconds 120
        }
        catch {
            Write-Log ("Tracked Python package README writer failed. Falling back to the legacy PowerShell README writer. {0}" -f $_.Exception.Message) "WARN"
            $cliResult = $null
        }

        if ($cliResult) {
            if ($cliResult.ExitCode -eq 0 -and $cliResult.Result -and $cliResult.Result.ok) {
                return
            }

            $cliError = if ($cliResult.Result -and -not [string]::IsNullOrWhiteSpace($cliResult.Result.error)) {
                [string]$cliResult.Result.error
            }
            else {
                "Tracked Python CLI helper failed before returning a result."
            }
            Write-Log ("Tracked Python package README writer failed. Falling back to the legacy PowerShell README writer. {0}" -f $cliError) "WARN"
        }
    }

@"
README_FOR_CODEX

This folder contains a Video Mangler review package for:
$VideoFileName

What is included:
- raw\                            original source video (only if you chose to keep a copy)
- proxy\review_proxy_1280.mp4     review copy for playback
- $framesFolderName\frame_000001.jpg ...
- audio\audio.mp3                 only when the source has spoken audio
- audio\audio_tracks.json / .csv  detected audio track inventory
- audio\transcript_source_manifest.json all-track extraction/transcript manifest when all tracks are transcribed
- transcript\transcript.srt / .json / .txt
- transcript\tracks\              per-track transcript files when multiple audio tracks are present
- transcript\all_audio_tracks_transcript.md combined all-track transcript handoff when present
- transcript\all_audio_tracks_index.csv and all_audio_tracks_manifest.json all-track transcript index and manifest when present
- translations\<lang>\transcript.srt / .json / .txt when translation was requested
- comments\comments.txt / .json   public comments export when available and requested
- frame_index.csv                 timestamp index for the extracted frames
- frames_panels\                  high-detail 1920x1080 panel crops when an exact 5760x1080 source was detected
- audio\transcript_source.wav      selected single audio source used for transcription in Mixed/Track mode
- audio\transcript_source_metadata.json selected single-stream reuse-guard metadata in Mixed/Track mode
- script_run.log                  processing log, including raw OpenAI error details when available

A good review order:
1. Start with transcript\transcript.txt when audio is present.
2. Watch proxy\review_proxy_1280.mp4 for pacing, sequence, and spoken context.
3. Use frame_index.csv to map timestamps to the extracted frames.
4. Check translations\<lang>\ if you asked for translated text.
5. Check comments\ if public source comments were included for context.
6. Use raw video only if the derived review assets are not enough.

Notes:
- Package status: $(if ($PackageStatus -eq "PARTIAL_SUCCESS") { "partial success" } else { "success" })
- Selected frame interval: $FrameIntervalSeconds seconds
- Frames folder: $framesFolderName
- Raw video present: $RawPresent
- Audio present in source: $AudioPresent
- Processing mode used: $(if ([string]::IsNullOrWhiteSpace($ProcessingModeSummary)) { "Local" } else { $ProcessingModeSummary })
- AI project mode: $(if ([string]::IsNullOrWhiteSpace($OpenAiProjectSummary)) { "not applicable (Local mode)" } else { $OpenAiProjectSummary })
- Transcription path used: $(if ([string]::IsNullOrWhiteSpace($TranscriptionPathDetails)) { "none" } else { $TranscriptionPathDetails })
- Detected source language: $(if ([string]::IsNullOrWhiteSpace($DetectedLanguage)) { "not available" } else { $DetectedLanguage })
- Remote audio track selected: $(if ([string]::IsNullOrWhiteSpace($RemoteAudioTrackSummary)) { "not applicable (local source or provider metadata unavailable)" } else { $RemoteAudioTrackSummary })
- Translation targets: $(if ($TranslationTargets -and $TranslationTargets.Count -gt 0) { $TranslationTargets -join ", " } else { "none" })
- Translation status: $(if ([string]::IsNullOrWhiteSpace($TranslationStatus)) { "not requested" } else { $TranslationStatus })
- Translation path used: $(if ([string]::IsNullOrWhiteSpace($TranslationPathDetails)) { "none" } else { $TranslationPathDetails })
- Translation notes: $(if ([string]::IsNullOrWhiteSpace($TranslationNotes)) { "none" } else { $TranslationNotes })
- Next steps: $(if ([string]::IsNullOrWhiteSpace($NextSteps)) { "none" } else { $NextSteps })
- Comments: $(if ([string]::IsNullOrWhiteSpace($CommentsSummary)) { "not included" } else { $CommentsSummary })
- Full Review panel crops: $(if ([string]::IsNullOrWhiteSpace($PanelFramesSummary)) { "not evaluated" } else { $PanelFramesSummary })
- Panel frames folder: $(if ([string]::IsNullOrWhiteSpace($PanelFramesPath)) { "not created" } else { $PanelFramesPath })
- Panel frame index: $(if ([string]::IsNullOrWhiteSpace($PanelFrameIndexPath)) { "not created" } else { $PanelFrameIndexPath })
- Transcript audio source: $(if ([string]::IsNullOrWhiteSpace($TranscriptSourceSummary)) { "not available" } else { $TranscriptSourceSummary })
- Transcript source metadata: $(if ([string]::IsNullOrWhiteSpace($TranscriptSourceMetadataPath)) { "not available" } else { $TranscriptSourceMetadataPath })
- Transcript source manifest: $(if ([string]::IsNullOrWhiteSpace($TranscriptSourceManifestPath)) { "not available" } else { $TranscriptSourceManifestPath })
- All audio tracks transcript: $(if ([string]::IsNullOrWhiteSpace($AllAudioTracksTranscriptPath)) { "not available" } else { $AllAudioTracksTranscriptPath })
- All audio tracks index: $(if ([string]::IsNullOrWhiteSpace($AllAudioTracksIndexPath)) { "not available" } else { $AllAudioTracksIndexPath })
- All audio tracks manifest: $(if ([string]::IsNullOrWhiteSpace($AllAudioTracksManifestPath)) { "not available" } else { $AllAudioTracksManifestPath })
"@ | Set-Content -LiteralPath $ReadmePath -Encoding UTF8
}

function New-AiReviewReadme {
    param(
        [string]$ReadmePath,
        [string]$SourceVideoName,
        [string]$FramesFolderName,
        [bool]$ProxyIncluded,
        [string]$FrameSelectionNote,
        [string[]]$TranslationTargets,
        [bool]$CommentsIncluded,
        [string]$PanelCropMode = "Auto",
        [bool]$PanelManifestIncluded = $false,
        [int]$PanelImageCount = 0,
        [string]$PanelSelectionNote = ""
    )

@"
AI_REVIEW_PACKAGE

Source video:
$SourceVideoName

Package contents:
- audio\audio.mp3
- audio\audio_tracks.json / .csv
- audio\transcript_source_manifest.json
- audio\transcript_source_metadata.json
- audio\TRANSCRIPT_SOURCE_WAV_OMITTED.txt when local WAV transcript sources exist but were excluded from this ZIP
- $FramesFolderName\frame_*.jpg
- transcript\transcript.srt / .json / .txt
- transcript\tracks\track_NN_transcript.* when all tracks were transcribed
- transcript\all_audio_tracks_transcript.md
- transcript\all_audio_tracks_index.csv
- transcript\all_audio_tracks_manifest.json
- $(if ($TranslationTargets -and $TranslationTargets.Count -gt 0) { "translations\<lang>\transcript.*" } else { "no translated transcript files were requested" })
- $(if ($CommentsIncluded) { "comments\comments.txt and comments\comments.json" } else { "no public comments export is included" })
- frame_index.csv
$(if ($PanelManifestIncluded) { "- frames_panels\panel_frame_index.csv and panel_frame_manifest.json" } else { "- no Full Review panel frame index/manifest is included" })
$(if ($PanelImageCount -gt 0) { "- selected high-detail frames_panels\ crops ($PanelImageCount image files)" } else { "- no high-detail panel crop images are included in this ZIP" })
$(if ($ProxyIncluded) { "- proxy\review_proxy_1280.mp4" } else { "- proxy video omitted to stay under upload size limits" })

Frame selection:
$FrameSelectionNote

Panel crop selection:
Mode: $PanelCropMode
$(if ([string]::IsNullOrWhiteSpace($PanelSelectionNote)) { "Panel crops were not available for this package." } else { $PanelSelectionNote })

Suggested prompts:
1) Ask for a summary of the original transcript first.
2) Ask ChatGPT to review visual events using frame_index.csv and the extracted frames.
3) If translations are included, ask it to compare the translated wording against the original transcript.
4) If comments are included, ask whether the public reaction adds useful context.
5) If proxy video is included, ask it to cross-check key moments against the proxy.
"@ | Set-Content -LiteralPath $ReadmePath -Encoding UTF8
}

function Get-PathSizeBytes {
    param([string]$LiteralPath)

    if (-not (Test-Path -LiteralPath $LiteralPath)) {
        return [int64]0
    }

    if (Test-Path -LiteralPath $LiteralPath -PathType Container) {
        # 209: a size estimate only; a folder past the Windows path limit must not stop it (the
        # ZIP itself is written by the long-path-safe writer and its real size is checked).
        $measured = (Get-ChildItem -LiteralPath $LiteralPath -File -Recurse -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
        if ($null -eq $measured) {
            return [int64]0
        }

        return [int64]$measured
    }

    return [int64](Get-Item -LiteralPath $LiteralPath).Length
}

function New-AiReviewFrameIndex {
    param(
        [string]$SourceFrameIndexCsv,
        [string]$DestinationFrameIndexCsv,
        [array]$SelectedFrames
    )

    $selectedNames = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($frame in $SelectedFrames) {
        [void]$selectedNames.Add($frame.Name)
    }

    $rows = @(Import-Csv -LiteralPath $SourceFrameIndexCsv | Where-Object { $selectedNames.Contains($_.filename) })
    if ($rows.Count -eq 0) {
        throw "No matching frame index rows were found for the selected AI review frame subset."
    }

    $rows | Export-Csv -LiteralPath $DestinationFrameIndexCsv -NoTypeInformation -Encoding UTF8
}

function Set-NotePropertyValue {
    param(
        [psobject]$Object,
        [string]$Name,
        $Value
    )

    $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value -Force
}

function Copy-FileIfExists {
    param(
        [string]$SourcePath,
        [string]$DestinationPath
    )

    if ([string]::IsNullOrWhiteSpace($SourcePath) -or -not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
        return $false
    }

    $destinationFolder = Split-Path -Path $DestinationPath -Parent
    if (-not [string]::IsNullOrWhiteSpace($destinationFolder)) {
        Ensure-Directory $destinationFolder
    }
    Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath -Force
    return $true
}

function New-AiReviewEvidenceSupplement {
    param(
        [psobject]$ProcessedItem,
        [string]$DestinationRoot,
        [switch]$IncludeMedia,
        [int]$MaxImagesPerCandidate = 12
    )

    $aiEvidenceRoot = Join-Path $DestinationRoot "ai_evidence"
    if (Test-Path -LiteralPath $aiEvidenceRoot) {
        Remove-Item -LiteralPath $aiEvidenceRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    Ensure-Directory $aiEvidenceRoot

    $notes = New-Object System.Collections.Generic.List[string]
    [void]$notes.Add("This is a compact supplement from the per-video Codex evidence package.")
    [void]$notes.Add("It is intentionally smaller than the full codex-evidence-package folder.")
    if ($IncludeMedia) {
        [void]$notes.Add(("Selected candidate full-frame and panel-crop images are capped at {0} images per candidate folder." -f $MaxImagesPerCandidate))
    }
    else {
        [void]$notes.Add("Image evidence was omitted from this ZIP supplement to respect AiReviewZipMaxMb.")
    }

    $docsRoot = Join-Path $aiEvidenceRoot "docs"
    Ensure-Directory $docsRoot
    $textFiles = @(
        @{ Source = (Join-Path $ProcessedItem.OutputPath "AI_REVIEW_MANIFEST.json"); Name = "AI_REVIEW_MANIFEST.json" },
        @{ Source = (Join-Path $ProcessedItem.OutputPath "AI_REVIEW_README.md"); Name = "AI_REVIEW_README.md" }
    )

    if (-not [string]::IsNullOrWhiteSpace($ProcessedItem.CodexEvidenceOutputRoot) -and (Test-Path -LiteralPath $ProcessedItem.CodexEvidenceOutputRoot -PathType Container)) {
        foreach ($name in @(
            "README_FOR_AI.md",
            "EVIDENCE_QUALITY_REPORT.md",
            "CANDIDATE_TICKETS.md",
            "CANDIDATE_TICKETS.json",
            "REVIEW_NEEDED.md",
            "REVIEW_NEEDED.json",
            "SESSION_TIMELINE.md",
            "MARKER_AUDIT.md",
            "MARKER_AUDIT.json",
            "REPO_ROUTING_HINTS.md",
            "REPO_ROUTING_HINTS.json",
            "manifest.json",
            "manifest.summary.json"
        )) {
            $textFiles += @{ Source = (Join-Path $ProcessedItem.CodexEvidenceOutputRoot $name); Name = $name }
        }
    }

    foreach ($entry in $textFiles) {
        $null = Copy-FileIfExists -SourcePath $entry.Source -DestinationPath (Join-Path $docsRoot $entry.Name)
    }

    $evidenceItemsRoot = if (-not [string]::IsNullOrWhiteSpace($ProcessedItem.CodexEvidenceOutputRoot)) {
        Join-Path $ProcessedItem.CodexEvidenceOutputRoot "evidence_items"
    }
    else {
        ""
    }

    if (-not [string]::IsNullOrWhiteSpace($evidenceItemsRoot) -and (Test-Path -LiteralPath $evidenceItemsRoot -PathType Container)) {
        $candidateDestinationRoot = Join-Path $aiEvidenceRoot "evidence_items"
        Ensure-Directory $candidateDestinationRoot
        $candidates = @(Get-ChildItem -LiteralPath $evidenceItemsRoot -Directory | Sort-Object Name)
        foreach ($candidate in $candidates) {
            $candidateDestination = Join-Path $candidateDestinationRoot $candidate.Name
            Ensure-Directory $candidateDestination
            foreach ($name in @("ticket.md", "metadata.json", "transcript_window.md", "frame_index.csv")) {
                $null = Copy-FileIfExists -SourcePath (Join-Path $candidate.FullName $name) -DestinationPath (Join-Path $candidateDestination $name)
            }

            if ($IncludeMedia) {
                $imageCount = 0
                $fullFrames = Join-Path $candidate.FullName "frames\full"
                if (Test-Path -LiteralPath $fullFrames -PathType Container) {
                    $fullDestination = Join-Path $candidateDestination "frames\full"
                    Ensure-Directory $fullDestination
                    foreach ($image in @(Get-ChildItem -LiteralPath $fullFrames -File | Where-Object { $_.Extension -match '^(?i)\.(jpg|jpeg|png)$' } | Sort-Object Name | Select-Object -First $MaxImagesPerCandidate)) {
                        Copy-Item -LiteralPath $image.FullName -Destination (Join-Path $fullDestination $image.Name) -Force
                        $imageCount += 1
                    }
                }

                $panelFrames = Join-Path $candidate.FullName "frames\panels"
                if (Test-Path -LiteralPath $panelFrames -PathType Container) {
                    foreach ($panelFolder in @(Get-ChildItem -LiteralPath $panelFrames -Directory | Sort-Object Name)) {
                        $remaining = [math]::Max(0, $MaxImagesPerCandidate - $imageCount)
                        if ($remaining -le 0) {
                            break
                        }
                        $panelDestination = Join-Path (Join-Path $candidateDestination "frames\panels") $panelFolder.Name
                        Ensure-Directory $panelDestination
                        foreach ($image in @(Get-ChildItem -LiteralPath $panelFolder.FullName -File | Where-Object { $_.Extension -match '^(?i)\.(jpg|jpeg|png)$' } | Sort-Object Name | Select-Object -First $remaining)) {
                            Copy-Item -LiteralPath $image.FullName -Destination (Join-Path $panelDestination $image.Name) -Force
                            $imageCount += 1
                        }
                    }
                }
            }
        }
    }

    $notesPath = Join-Path $aiEvidenceRoot "AI_EVIDENCE_SUPPLEMENT_NOTES.txt"
    $notes | Set-Content -LiteralPath $notesPath -Encoding UTF8

    return [PSCustomObject]@{
        RootPath     = $aiEvidenceRoot
        SizeBytes    = Get-PathSizeBytes -LiteralPath $aiEvidenceRoot
        MediaIncluded = [bool]$IncludeMedia
    }
}

function New-AiReviewEvidenceSupplementOmissionNote {
    param(
        [string]$DestinationRoot,
        [int]$MaxSizeMb
    )

    $aiEvidenceRoot = Join-Path $DestinationRoot "ai_evidence"
    if (Test-Path -LiteralPath $aiEvidenceRoot) {
        Remove-Item -LiteralPath $aiEvidenceRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    Ensure-Directory $aiEvidenceRoot
    @(
        "The per-video Codex evidence package exists, but the compact ZIP supplement could not fit within AiReviewZipMaxMb.",
        ("AiReviewZipMaxMb: {0}" -f $MaxSizeMb),
        "Open AI_REVIEW_README.md beside the ZIP and review codex-evidence-package directly from the canonical per-video folder."
    ) | Set-Content -LiteralPath (Join-Path $aiEvidenceRoot "SUPPLEMENT_OMITTED.txt") -Encoding UTF8

    return [PSCustomObject]@{
        RootPath     = $aiEvidenceRoot
        SizeBytes    = Get-PathSizeBytes -LiteralPath $aiEvidenceRoot
        MediaIncluded = $false
    }
}

function Get-PortablePackagePath {
    param(
        [string]$PackageRoot,
        [string]$TargetPath
    )

    if ([string]::IsNullOrWhiteSpace($PackageRoot) -or [string]::IsNullOrWhiteSpace($TargetPath)) {
        return ""
    }

    try {
        $rootFull = [System.IO.Path]::GetFullPath($PackageRoot).TrimEnd([char[]]@('\', '/'))
        $targetFull = [System.IO.Path]::GetFullPath($TargetPath)
        if ($targetFull.Equals($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
            return "."
        }
        $rootPrefix = $rootFull + [System.IO.Path]::DirectorySeparatorChar
        if (-not $targetFull.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            return ""
        }
        return $targetFull.Substring($rootPrefix.Length).Replace('\', '/')
    }
    catch {
        return ""
    }
}

function Get-PortableDiagnosticText {
    param([string]$Message)

    if ([string]::IsNullOrWhiteSpace($Message)) {
        return ""
    }
    return ([regex]::Replace($Message, '(?i)(?:[a-z]:[\\/]|\\\\)[^\r\n]+', '<local path>')).Trim()
}

function ConvertTo-PortableTrackTranscripts {
    param(
        [string]$PackageRoot,
        [array]$TrackTranscripts
    )

    return @($TrackTranscripts | ForEach-Object {
        [ordered]@{
            stream = $_.Stream
            extraction_status = [string]$_.ExtractionStatus
            transcript_status = [string]$_.TranscriptStatus
            failure_reason = [string]$_.FailureReason
            wav_path = Get-PortablePackagePath -PackageRoot $PackageRoot -TargetPath ([string]$_.WavPath)
            json_path = Get-PortablePackagePath -PackageRoot $PackageRoot -TargetPath ([string]$_.JsonPath)
            srt_path = Get-PortablePackagePath -PackageRoot $PackageRoot -TargetPath ([string]$_.SrtPath)
            text_path = Get-PortablePackagePath -PackageRoot $PackageRoot -TargetPath ([string]$_.TextPath)
            markdown_path = Get-PortablePackagePath -PackageRoot $PackageRoot -TargetPath ([string]$_.MarkdownPath)
        }
    })
}

function New-AiReviewArtifacts {
    param(
        [psobject]$ProcessedItem,
        [bool]$AiReviewZipRequested,
        [int]$AiReviewZipMaxMb,
        [string]$EvidencePanelCropMode = "Auto",
        [string]$EvidenceTargetRepo = ""
    )

    $manifestPath = Join-Path $ProcessedItem.OutputPath "AI_REVIEW_MANIFEST.json"
    $readmePath = Join-Path $ProcessedItem.OutputPath "AI_REVIEW_README.md"
    $portableReadmePath = Join-Path $ProcessedItem.OutputPath "README_FOR_AI.md"
    $portableManifestPath = Join-Path $ProcessedItem.OutputPath "AI_PACKAGE_MANIFEST.json"
    $aiReviewZipPath = Join-Path $ProcessedItem.OutputPath "ai_review_package.zip"

    $codexEvidence = [ordered]@{
        requested        = [bool]$ProcessedItem.CodexEvidenceRequested
        selection_source = [string]$ProcessedItem.CodexEvidenceSelectionSource
        status           = [string]$ProcessedItem.CodexEvidenceStatus
        skip_reason      = [string]$ProcessedItem.CodexEvidenceSkipReason
        output_root      = Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.CodexEvidenceOutputRoot)
        manifest_path    = Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.CodexEvidenceManifestPath)
        readme_path      = Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.CodexEvidenceReadmePath)
        quality_report   = Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.CodexEvidenceQualityReport)
        candidate_count  = [int]$ProcessedItem.CodexEvidenceCandidateCount
        review_needed_count = [int]$ProcessedItem.CodexEvidenceReviewNeededCount
        review_needed_path = Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.CodexEvidenceReviewNeededPath)
        visual_followup_required_count = [int]$ProcessedItem.CodexEvidenceVisualFollowupCount
        target_repo_hint = $EvidenceTargetRepo
    }

    $payload = [ordered]@{
        generated_at = (Get-Date).ToString("o")
        app_surface  = $script:AppName
        app_version  = (Get-AppVersion)
        source_video = [ordered]@{
            name = [string]$ProcessedItem.SourceVideoName
            path_hash_or_safe_id = Get-Sha256ShortText -Value ([string]$ProcessedItem.SourceVideoPath)
            width = [int]$ProcessedItem.SourceWidth
            height = [int]$ProcessedItem.SourceHeight
        }
        path_mode = "package_relative"
        canonical_review_folder = "."
        normal_full_review_assets = [ordered]@{
            readme = "README_FOR_AI.md"
            legacy_readme = "README_FOR_CODEX.txt"
            frame_index = "frame_index.csv"
            proxy = "proxy/review_proxy_1280.mp4"
            frames = ([string]$ProcessedItem.FramesFolderName).Replace('\', '/')
            audio = "audio"
            transcript = "transcript"
            translations = "translations"
        }
        ai_review_package = [ordered]@{
            requested = [bool]$AiReviewZipRequested
            path = $(if ($AiReviewZipRequested) { "ai_review_package.zip" } else { "" })
            max_mb = [int]$AiReviewZipMaxMb
            compact_ai_evidence_folder = "ai_evidence"
            panel_crop_mode = [string]$ProcessedItem.AiReviewZipPanelCropMode
        }
        codex_evidence_package = $codexEvidence
        full_review_panel_crops = [ordered]@{
            source_width = [int]$ProcessedItem.SourceWidth
            source_height = [int]$ProcessedItem.SourceHeight
            mode = [string]$ProcessedItem.FullReviewPanelCropMode
            generated = [bool]$ProcessedItem.FullReviewPanelCropsGenerated
            status = [string]$ProcessedItem.FullReviewPanelCropStatus
            skip_reason = [string]$ProcessedItem.FullReviewPanelCropSkipReason
            cadence_seconds = [double]$ProcessedItem.FullReviewPanelCropCadenceSeconds
            frame_count = [int]$ProcessedItem.FullReviewPanelFrameCount
            index_path = Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.PanelFrameIndexPath)
            manifest_path = Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.PanelFrameManifestPath)
            output_root = Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.PanelFramesPath)
            crop_geometry = @($ProcessedItem.FullReviewPanelCropGeometry)
        }
        codex_evidence_panel_crops = [ordered]@{
            mode = $EvidencePanelCropMode
            source_dimension_rule = "Only exact 5760x1080 source frames are split into panel crops."
            panels = @(
                [ordered]@{ role = "overview_cam"; label = "Overview Cam"; crop = "1920:1080:0:0" },
                [ordered]@{ role = "driver_view"; label = "Driver View"; crop = "1920:1080:1920:0" },
                [ordered]@{ role = "face_cam"; label = "Face Cam"; crop = "1920:1080:3840:0" }
            )
        }
        transcript_audio_source = [ordered]@{
            inventory_json = Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.AudioTracksJson)
            inventory_csv = Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.AudioTracksCsv)
            audio_track_count = [int]$ProcessedItem.AudioTrackCount
            transcript_audio_mode_resolved = [string]$ProcessedItem.TranscriptAudioModeResolved
            is_all_tracks = [bool]$ProcessedItem.IsAllAudioTracksTranscript
            transcript_source_wav = Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.TranscriptSourceWav)
            metadata_path = Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.TranscriptSourceMetadataPath)
            manifest_path = Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.TranscriptSourceManifestPath)
            selection_summary = [string]$ProcessedItem.TranscriptAudioSelection
            track_wav_folder = Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.AudioTrackWavFolder)
            all_tracks_review_mix_wav = Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.AllTracksReviewMixWav)
            all_tracks_review_mix_status = [string]$ProcessedItem.AllTracksReviewMixStatus
            all_audio_tracks_transcript = Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.AllAudioTracksTranscriptPath)
            all_audio_tracks_index = Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.AllAudioTracksIndexPath)
            all_audio_tracks_manifest = Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.AllAudioTracksManifestPath)
            per_track_transcripts = @(ConvertTo-PortableTrackTranscripts -PackageRoot $ProcessedItem.OutputPath -TrackTranscripts @($ProcessedItem.TrackTranscripts))
        }
        transcript_audio_reuse = [ordered]@{
            status = $(if ($ProcessedItem.CodexEvidenceStatus -eq "included") { "full_review_addon_reuses_available_transcript_audio" } else { "metadata_guard_added" })
            follow_up = "Broader transcript/audio reuse is a separate follow-up. This release reuses already-created Full Review transcript/audio only for the per-video Codex evidence add-on when the guarded files are present."
        }
    }

    ($payload | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $manifestPath -Encoding UTF8

    $lines = @()
    $lines += "# AI Review Folder"
    $lines += ""
    $lines += "This is the canonical review folder for one processed source video."
    $lines += ""
    $lines += "Source video: $($ProcessedItem.SourceVideoName)"
    $lines += "Canonical folder: . (all paths in this folder are package-relative)"
    $lines += ""
    $lines += "Start here:"
    $lines += "- README_FOR_CODEX.txt for the normal Full Review package."
    if ($AiReviewZipRequested) {
        $lines += "- ai_review_package.zip for compact upload; when Codex evidence exists it includes an ai_evidence supplement."
    }
    else {
        $lines += "- ai_review_package.zip was not requested for this run."
    }
    if ($ProcessedItem.CodexEvidenceStatus -eq "included") {
        $lines += "- codex-evidence-package\\ for the full ticket-capture evidence package."
        $lines += "- codex-evidence-package\\EVIDENCE_QUALITY_REPORT.md and MARKER_AUDIT.md before deciding whether to file or update tickets."
        if (-not [string]::IsNullOrWhiteSpace($ProcessedItem.CodexEvidenceManifestPath)) {
            $lines += "- AI / ticket evidence manifest: $(Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.CodexEvidenceManifestPath))"
        }
        if (-not [string]::IsNullOrWhiteSpace($ProcessedItem.CodexEvidenceReviewNeededPath)) {
            $lines += "- Review-needed evidence: $(Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.CodexEvidenceReviewNeededPath))"
        }
    }
    else {
        $lines += "- Codex evidence package status: $($ProcessedItem.CodexEvidenceStatus)"
        if (-not [string]::IsNullOrWhiteSpace($ProcessedItem.CodexEvidenceSkipReason)) {
            $lines += "- Codex evidence note: $($ProcessedItem.CodexEvidenceSkipReason)"
        }
    }
    $lines += ""
    $lines += "Panel crops:"
    $lines += "- Full Review panel crops: $($ProcessedItem.PanelFramesSummary)"
    if (-not [string]::IsNullOrWhiteSpace($ProcessedItem.PanelFrameIndexPath)) {
        $lines += "- Full Review panel index: $(Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.PanelFrameIndexPath))"
    }
    if (-not [string]::IsNullOrWhiteSpace($ProcessedItem.PanelFramesPath)) {
        $lines += "- High-detail panel frames: $(Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.PanelFramesPath))"
    }
    $lines += "- Codex evidence panel crops: $(Get-EvidencePanelCropModeSummary -Mode $EvidencePanelCropMode)"
    $lines += "- Exact 5760x1080 sources split into Overview Cam, Driver View, and Face Cam crops."
    $lines += "- Use Driver View crops for small dashboard/UI/button/overlay details when they exist."
    $lines += ""
    $lines += "Transcript audio source:"
    $lines += "- $($ProcessedItem.TranscriptAudioSelection)"
    if (-not [string]::IsNullOrWhiteSpace($ProcessedItem.TranscriptSourceMetadataPath)) {
        $lines += "- Transcript source metadata: $(Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.TranscriptSourceMetadataPath))"
    }
    if (-not [string]::IsNullOrWhiteSpace($ProcessedItem.TranscriptSourceManifestPath)) {
        $lines += "- Transcript source manifest: $(Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.TranscriptSourceManifestPath))"
    }
    if (-not [string]::IsNullOrWhiteSpace($ProcessedItem.AllAudioTracksTranscriptPath)) {
        $lines += "- All audio tracks transcript: $(Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.AllAudioTracksTranscriptPath))"
    }
    if (-not [string]::IsNullOrWhiteSpace($ProcessedItem.AllAudioTracksIndexPath)) {
        $lines += "- All audio tracks index: $(Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.AllAudioTracksIndexPath))"
    }
    $lines += ""
    $lines += "Transcript/audio reuse:"
    $lines += "- Full Review Codex evidence add-on reuses the guarded Full Review transcript/audio when present. Broader reuse design and acceptance are a separate follow-up."
    $lines += ""
    $lines += "Machine-readable index:"
    $lines += "- AI_REVIEW_MANIFEST.json"
    $lines | Set-Content -LiteralPath $readmePath -Encoding UTF8

    $portableLines = @(
        '# AI Study Package',
        '',
        'This self-contained folder is learning material prepared from one source video. It may be moved to another folder or drive without changing any links below.',
        '',
        '## Instructions for an AI agent',
        '',
        '1. Read this file and `AI_PACKAGE_MANIFEST.json` first.',
        '2. Read `transcript/` for the spoken explanation and use timestamps to connect it to `frame_index.csv` and the extracted frame folders.',
        '3. Inspect `proxy/review_proxy_1280.mp4` or selected frames when the transcript refers to visual details.',
        '4. Treat the material as reference evidence, not as automatically verified truth. State conflicts or missing evidence.',
        '5. If `codex-evidence-package/` exists, treat it as optional AI / ticket evidence; the main study package remains complete without it.',
        '',
        '## Source',
        '',
        ("- Name: {0}" -f [string]$ProcessedItem.SourceVideoName),
        ("- Safe source ID: {0}" -f (Get-Sha256ShortText -Value ([string]$ProcessedItem.SourceVideoPath))),
        '',
        '## Main material',
        '',
        '- `transcript/` - searchable transcript files',
        '- `frame_index.csv` - timestamps for extracted visuals',
        ("- `{0}/` - extracted frames" -f ([string]$ProcessedItem.FramesFolderName).Replace('\', '/')),
        '- `proxy/review_proxy_1280.mp4` - review-sized video',
        '- `audio/` - audio and track-selection details when present',
        '- `AI_REVIEW_MANIFEST.json` - detailed machine-readable inventory',
        '',
        'All paths in the package manifests are relative to this folder. No original machine path is required to use the package.'
    )
    $portableLines | Set-Content -LiteralPath $portableReadmePath -Encoding UTF8

    $portablePayload = [ordered]@{
        schema = "media-manglers-ai-package-v1"
        generated_at = (Get-Date).ToString("o")
        path_mode = "package_relative"
        start_here = "README_FOR_AI.md"
        source = [ordered]@{
            name = [string]$ProcessedItem.SourceVideoName
            path_hash_or_safe_id = Get-Sha256ShortText -Value ([string]$ProcessedItem.SourceVideoPath)
        }
        assets = [ordered]@{
            detailed_manifest = "AI_REVIEW_MANIFEST.json"
            transcript = "transcript"
            frame_index = "frame_index.csv"
            frames = ([string]$ProcessedItem.FramesFolderName).Replace('\', '/')
            panel_frames = Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.PanelFramesPath)
            proxy = "proxy/review_proxy_1280.mp4"
            audio = "audio"
            translations = "translations"
            ai_ticket_evidence = Get-PortablePackagePath -PackageRoot $ProcessedItem.OutputPath -TargetPath ([string]$ProcessedItem.CodexEvidenceOutputRoot)
            compact_zip = $(if ($AiReviewZipRequested) { "ai_review_package.zip" } else { "" })
        }
    }
    ($portablePayload | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $portableManifestPath -Encoding UTF8

    Set-NotePropertyValue -Object $ProcessedItem -Name "AiReviewManifestPath" -Value $manifestPath
    Set-NotePropertyValue -Object $ProcessedItem -Name "AiReviewReadmePath" -Value $readmePath
    Set-NotePropertyValue -Object $ProcessedItem -Name "AiReviewZipPath" -Value $(if ($AiReviewZipRequested) { $aiReviewZipPath } else { "" })
    Set-NotePropertyValue -Object $ProcessedItem -Name "PortableAiReadmePath" -Value $portableReadmePath
    Set-NotePropertyValue -Object $ProcessedItem -Name "PortableAiManifestPath" -Value $portableManifestPath

    return [PSCustomObject]@{
        ManifestPath = $manifestPath
        ReadmePath   = $readmePath
    }
}

function Set-FullReviewCodexEvidenceMetadata {
    param(
        [psobject]$ProcessedItem,
        [bool]$Requested,
        [string]$SelectionSource,
        [string]$Status,
        [string]$SkipReason = "",
        [psobject]$EvidenceResult = $null
    )

    Set-NotePropertyValue -Object $ProcessedItem -Name "CodexEvidenceRequested" -Value ([bool]$Requested)
    Set-NotePropertyValue -Object $ProcessedItem -Name "CodexEvidenceSelectionSource" -Value $SelectionSource
    Set-NotePropertyValue -Object $ProcessedItem -Name "CodexEvidenceStatus" -Value $Status
    Set-NotePropertyValue -Object $ProcessedItem -Name "CodexEvidenceSkipReason" -Value $SkipReason
    Set-NotePropertyValue -Object $ProcessedItem -Name "CodexEvidenceOutputRoot" -Value $(if ($EvidenceResult) { [string]$EvidenceResult.OutputRoot } else { "" })
    Set-NotePropertyValue -Object $ProcessedItem -Name "CodexEvidenceManifestPath" -Value $(if ($EvidenceResult) { [string]$EvidenceResult.ManifestPath } else { "" })
    Set-NotePropertyValue -Object $ProcessedItem -Name "CodexEvidenceReadmePath" -Value $(if ($EvidenceResult) { [string]$EvidenceResult.ReadmePath } else { "" })
    Set-NotePropertyValue -Object $ProcessedItem -Name "CodexEvidenceQualityReport" -Value $(if ($EvidenceResult) { [string]$EvidenceResult.QualityReport } else { "" })
    Set-NotePropertyValue -Object $ProcessedItem -Name "CodexEvidenceCandidateCount" -Value $(if ($EvidenceResult) { [int]$EvidenceResult.CandidateCount } else { 0 })
    Set-NotePropertyValue -Object $ProcessedItem -Name "CodexEvidenceReviewNeededCount" -Value $(if ($EvidenceResult) { [int]$EvidenceResult.ReviewNeededCount } else { 0 })
    Set-NotePropertyValue -Object $ProcessedItem -Name "CodexEvidenceReviewNeededPath" -Value $(if ($EvidenceResult) { [string]$EvidenceResult.ReviewNeededPath } else { "" })
    Set-NotePropertyValue -Object $ProcessedItem -Name "CodexEvidenceVisualFollowupCount" -Value $(if ($EvidenceResult) { [int]$EvidenceResult.VisualFollowupCount } else { 0 })
}

function Resolve-FullReviewCodexEvidenceStatus {
    param(
        [array]$ProcessedItems,
        [array]$FailedItems = @(),
        [bool]$Requested,
        [string]$DefaultStatus
    )

    if (-not $Requested) {
        return $DefaultStatus
    }

    $statuses = @($ProcessedItems | ForEach-Object { [string]$_.CodexEvidenceStatus } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($statuses.Count -eq 0) {
        if (@($FailedItems).Count -gt 0) {
            return "failed"
        }
        return "requested"
    }
    if (@($statuses | Where-Object { $_ -eq "failed" }).Count -gt 0) {
        return "failed"
    }
    if (@($FailedItems).Count -gt 0) {
        return "partial"
    }
    if (@($statuses | Where-Object { $_ -eq "included" }).Count -gt 0 -and @($statuses | Where-Object { $_ -eq "skipped" }).Count -gt 0) {
        return "partial"
    }
    if (@($statuses | Where-Object { $_ -eq "included" }).Count -gt 0) {
        return "included"
    }
    if (@($statuses | Where-Object { $_ -eq "skipped" }).Count -eq $statuses.Count) {
        return "skipped"
    }

    return $DefaultStatus
}

function Get-Sha256ShortText {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return ""
    }
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
        $hash = $sha256.ComputeHash($bytes)
        return (($hash | ForEach-Object { $_.ToString("x2") }) -join "").Substring(0, 16)
    }
    finally {
        $sha256.Dispose()
    }
}

function Get-FullReviewFailurePhase {
    param([string]$Message)

    $text = if ([string]::IsNullOrWhiteSpace($Message)) { "" } else { $Message }
    if ($text -match "Codex evidence") { return "CodexEvidence" }
    if ($text -match "Translation|translate|Whisper audio translation") { return "Translation" }
    if ($text -match "Transcript|transcription|Whisper") { return "Transcript" }
    if ($text -match "Audio") { return "Audio" }
    if ($text -match "Proxy") { return "Proxy" }
    if ($text -match "Frame|frames") { return "Frames" }
    return "FullReview"
}

function Get-ArtifactCoverageStatus {
    param(
        [string]$Path,
        [string]$MissingLabel = "missing",
        [string]$PresentLabel = "present",
        [string]$BlankLabel = "not_available"
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $BlankLabel
    }
    if (Test-Path -LiteralPath $Path) {
        return $PresentLabel
    }
    return $MissingLabel
}

function Get-FullReviewTranscriptCoverageStatus {
    param(
        [string]$OutputPath,
        [string]$TranscriptJsonPath = "",
        [string]$AllAudioTracksTranscriptPath = "",
        [string]$AllAudioTracksManifestPath = "",
        [string]$AudioPresent = ""
    )

    if ($AudioPresent -eq "No") {
        return "no_audio"
    }
    $jsonPath = if (-not [string]::IsNullOrWhiteSpace($TranscriptJsonPath)) {
        $TranscriptJsonPath
    }
    elseif (-not [string]::IsNullOrWhiteSpace($OutputPath)) {
        Join-Path $OutputPath "transcript\transcript.json"
    }
    else {
        ""
    }
    $allTrackPath = if (-not [string]::IsNullOrWhiteSpace($AllAudioTracksTranscriptPath)) {
        $AllAudioTracksTranscriptPath
    }
    elseif (-not [string]::IsNullOrWhiteSpace($OutputPath)) {
        Join-Path $OutputPath "transcript\all_audio_tracks_transcript.md"
    }
    else {
        ""
    }
    $allTrackManifestPath = if (-not [string]::IsNullOrWhiteSpace($AllAudioTracksManifestPath)) {
        $AllAudioTracksManifestPath
    }
    elseif (-not [string]::IsNullOrWhiteSpace($OutputPath)) {
        Join-Path $OutputPath "transcript\all_audio_tracks_manifest.json"
    }
    else {
        ""
    }
    if (-not [string]::IsNullOrWhiteSpace($allTrackManifestPath) -and (Test-Path -LiteralPath $allTrackManifestPath -PathType Leaf)) {
        try {
            $allTrackManifest = Get-Content -LiteralPath $allTrackManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $manifestStatus = [string]$allTrackManifest.transcript_status
            $failedTrackCount = if ($null -ne $allTrackManifest.failed_track_count) { [int]$allTrackManifest.failed_track_count } else { 0 }
            if ($manifestStatus -eq "failed") {
                return "all_tracks_transcript_failed"
            }
            if ($manifestStatus -eq "partial" -or $failedTrackCount -gt 0) {
                return "all_tracks_transcript_partial"
            }
        }
        catch {
            return "all_tracks_transcript_manifest_unreadable"
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($allTrackPath) -and (Test-Path -LiteralPath $allTrackPath -PathType Leaf)) {
        return "all_tracks_transcript_available"
    }
    if (-not [string]::IsNullOrWhiteSpace($jsonPath) -and (Test-Path -LiteralPath $jsonPath -PathType Leaf)) {
        return "transcript_available"
    }
    return "missing"
}

function New-EvidenceCoverageMatrix {
    param(
        [string]$OutputRoot,
        [array]$ProcessedItems,
        [array]$FailedItems,
        [bool]$CodexEvidenceRequested
    )

    $rows = New-Object System.Collections.Generic.List[object]

    foreach ($item in @($ProcessedItems)) {
        $codexStatus = if ([string]::IsNullOrWhiteSpace([string]$item.CodexEvidenceStatus)) { "not_requested" } else { [string]$item.CodexEvidenceStatus }
        $candidateCount = if ($null -ne $item.PSObject.Properties["CodexEvidenceCandidateCount"]) { [int]$item.CodexEvidenceCandidateCount } else { 0 }
        $reviewNeededCount = if ($null -ne $item.PSObject.Properties["CodexEvidenceReviewNeededCount"]) { [int]$item.CodexEvidenceReviewNeededCount } else { 0 }
        $notes = New-Object System.Collections.Generic.List[string]
        if ($item.PackageStatus -eq "PARTIAL_SUCCESS") {
            [void]$notes.Add("normal package partial")
        }
        if ($codexStatus -ne "included" -and $CodexEvidenceRequested) {
            [void]$notes.Add("requested Codex evidence not fully included")
        }
        if ($reviewNeededCount -gt 0) {
            [void]$notes.Add("review-needed evidence requires visual follow-up")
        }
        [void]$rows.Add([PSCustomObject]@{
            source_video_name = [string]$item.SourceVideoName
            source_path_hash_or_safe_id = Get-Sha256ShortText -Value ([string]$item.SourceVideoPath)
            output_folder_name = [string]$item.OutputFolderName
            package_status = [string]$item.PackageStatus
            failure_phase = ""
            transcript_status = Get-FullReviewTranscriptCoverageStatus -OutputPath ([string]$item.OutputPath) -TranscriptJsonPath ([string]$item.TranscriptJsonPath) -AllAudioTracksTranscriptPath ([string]$item.AllAudioTracksTranscriptPath) -AllAudioTracksManifestPath ([string]$item.AllAudioTracksManifestPath) -AudioPresent ([string]$item.AudioPresent)
            ai_review_manifest = Get-ArtifactCoverageStatus -Path ([string]$item.AiReviewManifestPath)
            ai_review_zip = Get-ArtifactCoverageStatus -Path ([string]$item.AiReviewZipPath) -BlankLabel "not_requested"
            codex_evidence_package_status = $codexStatus
            candidate_count = $candidateCount
            review_needed_count = $reviewNeededCount
            visual_followup_required_count = $(if ($null -ne $item.PSObject.Properties["CodexEvidenceVisualFollowupCount"]) { [int]$item.CodexEvidenceVisualFollowupCount } else { 0 })
            full_review_panel_crops = [string]$item.FullReviewPanelCropStatus
            notes = (($notes.ToArray()) -join "; ")
            next_step = $(if ($codexStatus -eq "included" -and $reviewNeededCount -eq 0) { "review candidate tickets normally" } elseif ($codexStatus -eq "included") { "review REVIEW_NEEDED.md before ticket decisions" } elseif ($CodexEvidenceRequested) { "rerun or inspect failed evidence packaging" } else { "codex evidence not requested" })
        })
    }

    foreach ($item in @($FailedItems)) {
        $sourceName = if (-not [string]::IsNullOrWhiteSpace([string]$item.SourceVideoName)) {
            [string]$item.SourceVideoName
        }
        elseif (-not [string]::IsNullOrWhiteSpace([string]$item.VideoPath)) {
            Split-Path -Path ([string]$item.VideoPath) -Leaf
        }
        else {
            "unknown"
        }
        $sourcePath = if (-not [string]::IsNullOrWhiteSpace([string]$item.SourceVideoPath)) { [string]$item.SourceVideoPath } else { [string]$item.VideoPath }
        $outputPath = [string]$item.OutputPath
        $aiManifestPath = if ([string]::IsNullOrWhiteSpace($outputPath)) { "" } else { Join-Path $outputPath "AI_REVIEW_MANIFEST.json" }
        $aiReviewZipPath = if ([string]::IsNullOrWhiteSpace($outputPath)) { "" } else { Join-Path $outputPath "ai_review_package.zip" }
        $panelManifestPath = if ([string]::IsNullOrWhiteSpace($outputPath)) { "" } else { Join-Path $outputPath "frames_panels\panel_frame_manifest.json" }
        $codexStatus = if (-not [string]::IsNullOrWhiteSpace([string]$item.CodexEvidenceStatus)) { [string]$item.CodexEvidenceStatus } elseif ($CodexEvidenceRequested) { "not_attempted" } else { "not_requested" }
        $phase = if (-not [string]::IsNullOrWhiteSpace([string]$item.FailurePhase)) { [string]$item.FailurePhase } else { Get-FullReviewFailurePhase -Message ([string]$item.Message) }
        [void]$rows.Add([PSCustomObject]@{
            source_video_name = $sourceName
            source_path_hash_or_safe_id = Get-Sha256ShortText -Value $sourcePath
            output_folder_name = [string]$item.OutputFolderName
            package_status = "failed"
            failure_phase = $phase
            transcript_status = Get-FullReviewTranscriptCoverageStatus -OutputPath $outputPath -AudioPresent ([string]$item.AudioPresent)
            ai_review_manifest = Get-ArtifactCoverageStatus -Path $aiManifestPath
            ai_review_zip = Get-ArtifactCoverageStatus -Path $aiReviewZipPath -BlankLabel "not_requested"
            codex_evidence_package_status = $codexStatus
            candidate_count = 0
            review_needed_count = 0
            visual_followup_required_count = 0
            full_review_panel_crops = Get-ArtifactCoverageStatus -Path $panelManifestPath -PresentLabel "present" -BlankLabel "not_available"
            notes = Get-PortableDiagnosticText -Message ([string]$item.Message)
            next_step = $(if ($phase -eq "CodexEvidence") { "inspect per-video Codex evidence failure" } else { "rerun or inspect script_run.log before trusting missing evidence" })
        })
    }

    $csvPath = Join-Path $OutputRoot "EVIDENCE_COVERAGE_MATRIX.csv"
    $markdownPath = Join-Path $OutputRoot "EVIDENCE_COVERAGE_MATRIX.md"
    @($rows.ToArray()) | Export-Csv -LiteralPath $csvPath -NoTypeInformation -Encoding UTF8

    $lines = @()
    $lines += "# Evidence Coverage Matrix"
    $lines += ""
    $lines += "This matrix reports whether each Full Review source produced the review artifacts needed for downstream ticket review."
    $lines += ""
    $lines += "| Source | Package | Transcript | AI review | AI review ZIP | Codex evidence | Candidates | Review needed | Next step |"
    $lines += "| --- | --- | --- | --- | --- | --- | ---: | ---: | --- |"
    foreach ($row in @($rows.ToArray())) {
        $lines += ("| {0} | {1} | {2} | {3} | {4} | {5} | {6} | {7} | {8} |" -f `
            ([string]$row.source_video_name).Replace("|", "\|"),
            ([string]$row.package_status).Replace("|", "\|"),
            ([string]$row.transcript_status).Replace("|", "\|"),
            ([string]$row.ai_review_manifest).Replace("|", "\|"),
            ([string]$row.ai_review_zip).Replace("|", "\|"),
            ([string]$row.codex_evidence_package_status).Replace("|", "\|"),
            [int]$row.candidate_count,
            [int]$row.review_needed_count,
            ([string]$row.next_step).Replace("|", "\|"))
    }
    $lines | Set-Content -LiteralPath $markdownPath -Encoding UTF8

    return [PSCustomObject]@{
        CsvPath = $csvPath
        MarkdownPath = $markdownPath
        Rows = @($rows.ToArray())
    }
}

function New-AiReviewZipPackage {
    param(
        [psobject]$ProcessedItem,
        [int]$MaxSizeMb = 500,
        [string]$PanelCropMode = "Auto"
    )

    $maxBytes = [int64]$MaxSizeMb * 1MB
    $panelPolicyMode = if ([string]::IsNullOrWhiteSpace($PanelCropMode)) { "Auto" } else { (Get-Culture).TextInfo.ToTitleCase($PanelCropMode.Trim().ToLowerInvariant()) }
    $framesFolder = Join-Path $ProcessedItem.OutputPath $ProcessedItem.FramesFolderName
    $framesPanelsFolder = Join-Path $ProcessedItem.OutputPath "frames_panels"
    $panelFrameIndex = Join-Path $framesPanelsFolder "panel_frame_index.csv"
    $panelFrameManifest = Join-Path $framesPanelsFolder "panel_frame_manifest.json"
    $audioFolder = Join-Path $ProcessedItem.OutputPath "audio"
    $audioFolderFull = ""
    $transcriptFolder = Join-Path $ProcessedItem.OutputPath "transcript"
    $translationsFolder = Join-Path $ProcessedItem.OutputPath "translations"
    $commentsFolder = Join-Path $ProcessedItem.OutputPath "comments"
    $frameIndexCsv = Join-Path $ProcessedItem.OutputPath "frame_index.csv"
    $proxyVideo = Join-Path $ProcessedItem.OutputPath "proxy\review_proxy_1280.mp4"
    $zipPath = Join-Path $ProcessedItem.OutputPath "ai_review_package.zip"
    $requiredPaths = @($framesFolder, $frameIndexCsv)
    foreach ($optionalPath in @($audioFolder, $transcriptFolder, $translationsFolder, $commentsFolder)) {
        if (Test-Path -LiteralPath $optionalPath) {
            $requiredPaths += $optionalPath
        }
    }
    if (Test-Path -LiteralPath $audioFolder -PathType Container) {
        $audioFolderFull = (Get-Item -LiteralPath $audioFolder).FullName
    }

    foreach ($path in $requiredPaths) {
        if (-not (Test-Path -LiteralPath $path)) {
            throw "Cannot build AI review zip because required item is missing: $path"
        }
    }

    $allFrames = @(Get-ChildItem -LiteralPath $framesFolder -Filter "frame_*.jpg" -File | Sort-Object Name)
    if ($allFrames.Count -eq 0) {
        throw "Cannot build AI review zip because no extracted frames were found in $framesFolder"
    }

    $nonFrameBaseBytes = [int64]0
    foreach ($path in ($requiredPaths | Where-Object { $_ -ne $framesFolder })) {
        if ($path -eq $audioFolder -and (Test-Path -LiteralPath $audioFolder -PathType Container)) {
            $audioZipFiles = @(Get-ChildItem -LiteralPath $audioFolder -File -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.Extension -ine ".wav" })
            foreach ($audioZipFile in $audioZipFiles) {
                $nonFrameBaseBytes += [int64]$audioZipFile.Length
            }
        }
        else {
            $nonFrameBaseBytes += Get-PathSizeBytes -LiteralPath $path
        }
    }

    $panelMetadataPaths = @()
    $panelMetadataAvailable = (
        $panelPolicyMode -ne "Off" -and
        (Test-Path -LiteralPath $panelFrameIndex -PathType Leaf) -and
        (Test-Path -LiteralPath $panelFrameManifest -PathType Leaf)
    )
    if ($panelMetadataAvailable) {
        $panelMetadataPaths = @($panelFrameIndex, $panelFrameManifest)
        foreach ($panelMetadataPath in $panelMetadataPaths) {
            $nonFrameBaseBytes += Get-PathSizeBytes -LiteralPath $panelMetadataPath
        }
    }

    # 201/209: named for this process, so a run after a Stop removes what this one left.
    $tempRoot = Get-MMScratchPath -Prefix "media_manglers_ai_review_zip"
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
    Ensure-Directory $tempRoot

    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem

        $evidenceSupplementPlan = $null
        $evidenceSupplementMode = "none"
        $hasPerVideoEvidence = (
            $ProcessedItem.CodexEvidenceStatus -eq "included" -and
            -not [string]::IsNullOrWhiteSpace($ProcessedItem.CodexEvidenceOutputRoot) -and
            (Test-Path -LiteralPath $ProcessedItem.CodexEvidenceOutputRoot -PathType Container)
        )
        if ($hasPerVideoEvidence) {
            $fullEvidenceTemp = Join-Path $tempRoot "_evidence_full"
            $fullEvidenceSupplement = New-AiReviewEvidenceSupplement -ProcessedItem $ProcessedItem -DestinationRoot $fullEvidenceTemp -IncludeMedia
            if (($nonFrameBaseBytes + [int64]$fullEvidenceSupplement.SizeBytes) -le $maxBytes) {
                $evidenceSupplementPlan = $fullEvidenceSupplement
                $evidenceSupplementMode = "text-and-selected-images"
            }
            else {
                $textEvidenceTemp = Join-Path $tempRoot "_evidence_text"
                $textEvidenceSupplement = New-AiReviewEvidenceSupplement -ProcessedItem $ProcessedItem -DestinationRoot $textEvidenceTemp
                if (($nonFrameBaseBytes + [int64]$textEvidenceSupplement.SizeBytes) -le $maxBytes) {
                    $evidenceSupplementPlan = $textEvidenceSupplement
                    $evidenceSupplementMode = "text-only"
                }
                else {
                    $noteEvidenceTemp = Join-Path $tempRoot "_evidence_note"
                    $noteEvidenceSupplement = New-AiReviewEvidenceSupplementOmissionNote -DestinationRoot $noteEvidenceTemp -MaxSizeMb $MaxSizeMb
                    $evidenceSupplementPlan = $noteEvidenceSupplement
                    $evidenceSupplementMode = "omitted-too-large"
                }
            }

            if ($evidenceSupplementPlan) {
                $nonFrameBaseBytes += [int64]$evidenceSupplementPlan.SizeBytes
            }
        }

        $proxyBytes = if (Test-Path -LiteralPath $proxyVideo) { [int64](Get-Item -LiteralPath $proxyVideo).Length } else { [int64]0 }

        $samplingStep = 1
        while ($samplingStep -le $allFrames.Count) {
            if (Test-Path -LiteralPath $zipPath) {
                Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue
            }

            # 209: package files go into the ZIP straight from the package, through the one ZIP
            # writer (long-path safe); only files made for the ZIP are written to this folder.
            $stagingRoot = Join-Path $tempRoot "ai_review"
            if (Test-Path -LiteralPath $stagingRoot) {
                Remove-Item -LiteralPath $stagingRoot -Recurse -Force -ErrorAction SilentlyContinue
            }
            Ensure-Directory $stagingRoot
            $zipEntries = New-Object System.Collections.Generic.List[object]

            if (Test-Path -LiteralPath $audioFolder) {
                [void]$zipEntries.Add(@{ source = $audioFolder; name = "audio"; exclude_suffixes = @(".wav") })
                $omittedAudioWavFiles = @(Get-ChildItem -LiteralPath $audioFolder -File -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.Extension -ieq ".wav" })
                if ($omittedAudioWavFiles.Count -gt 0) {
                    $stagedAudioFolder = Join-Path $stagingRoot "audio"
                    Ensure-Directory $stagedAudioFolder
                    @(
                        "One or more local WAV transcript sources exist in the Full Review folder but are omitted from this ZIP to preserve the ChatGPT upload size budget.",
                        "Omitted WAV files include transcript_source.wav, audio\tracks\track_NN.wav, or all_tracks_review_mix.wav when those files exist locally.",
                        "Use audio\transcript_source_metadata.json or audio\transcript_source_manifest.json to see which audio stream(s) were selected for transcription."
                    ) | Set-Content -LiteralPath (Join-Path $stagedAudioFolder "TRANSCRIPT_SOURCE_WAV_OMITTED.txt") -Encoding UTF8
                }
            }
            foreach ($folderEntry in @(@($transcriptFolder, "transcript"), @($translationsFolder, "translations"), @($commentsFolder, "comments"))) {
                if (Test-Path -LiteralPath $folderEntry[0]) {
                    [void]$zipEntries.Add(@{ source = $folderEntry[0]; name = $folderEntry[1] })
                }
            }
            if ($evidenceSupplementPlan -and -not [string]::IsNullOrWhiteSpace($evidenceSupplementPlan.RootPath) -and (Test-Path -LiteralPath $evidenceSupplementPlan.RootPath -PathType Container)) {
                [void]$zipEntries.Add(@{ source = [string]$evidenceSupplementPlan.RootPath; name = (Split-Path -Path ([string]$evidenceSupplementPlan.RootPath) -Leaf) })
            }

            $selectedFrames = @()
            for ($i = 0; $i -lt $allFrames.Count; $i += $samplingStep) {
                $selectedFrames += $allFrames[$i]
            }

            $selectedFrameBytes = [int64]0
            foreach ($frame in $selectedFrames) {
                $selectedFrameBytes += [int64]$frame.Length
                [void]$zipEntries.Add(@{ source = $frame.FullName; name = ("{0}/{1}" -f $ProcessedItem.FramesFolderName, $frame.Name) })
            }

            $stagedFrameIndex = Join-Path $stagingRoot "frame_index.csv"
            New-AiReviewFrameIndex `
                -SourceFrameIndexCsv $frameIndexCsv `
                -DestinationFrameIndexCsv $stagedFrameIndex `
                -SelectedFrames $selectedFrames

            $panelImageBytes = [int64]0
            $panelImagesIncluded = 0
            $panelSelectionNote = "Full Review panel crops were not present for this package."
            if ($panelMetadataAvailable) {
                [void]$zipEntries.Add(@{ source = $panelFrameIndex; name = "frames_panels/panel_frame_index.csv" })
                [void]$zipEntries.Add(@{ source = $panelFrameManifest; name = "frames_panels/panel_frame_manifest.json" })
                $panelSelectionNote = "Panel index and manifest are included."

                if ($panelPolicyMode -eq "IndexOnly") {
                    $panelSelectionNote = "Panel index and manifest are included; high-detail panel images were intentionally omitted by AiReviewZipPanelCropMode=IndexOnly."
                }
                else {
                    $remainingForPanelImages = [int64]($maxBytes - ($nonFrameBaseBytes + $selectedFrameBytes))
                    if ($remainingForPanelImages -gt 0) {
                        $panelCandidateImages = New-Object System.Collections.Generic.List[object]
                        $driverImages = @(Get-ChildItem -LiteralPath (Join-Path $framesPanelsFolder "driver_view") -Filter "*.jpg" -File -ErrorAction SilentlyContinue | Sort-Object Name)
                        $overviewImages = @(Get-ChildItem -LiteralPath (Join-Path $framesPanelsFolder "overview_cam") -Filter "*.jpg" -File -ErrorAction SilentlyContinue | Sort-Object Name)
                        $faceImages = @(Get-ChildItem -LiteralPath (Join-Path $framesPanelsFolder "face_cam") -Filter "*.jpg" -File -ErrorAction SilentlyContinue | Sort-Object Name)
                        for ($panelIndex = 0; $panelIndex -lt $driverImages.Count; $panelIndex++) {
                            [void]$panelCandidateImages.Add([PSCustomObject]@{ Role = "driver_view"; File = $driverImages[$panelIndex] })
                            if ($panelIndex -lt $overviewImages.Count) {
                                [void]$panelCandidateImages.Add([PSCustomObject]@{ Role = "overview_cam"; File = $overviewImages[$panelIndex] })
                            }
                            if ($panelIndex -lt $faceImages.Count) {
                                [void]$panelCandidateImages.Add([PSCustomObject]@{ Role = "face_cam"; File = $faceImages[$panelIndex] })
                            }
                        }

                        foreach ($candidate in @($panelCandidateImages.ToArray())) {
                            $file = $candidate.File
                            if ($null -eq $file) {
                                continue
                            }
                            $fileBytes = [int64]$file.Length
                            if (($panelImageBytes + $fileBytes) -gt $remainingForPanelImages) {
                                continue
                            }
                            [void]$zipEntries.Add(@{ source = $file.FullName; name = ("frames_panels/{0}/{1}" -f [string]$candidate.Role, $file.Name) })
                            $panelImageBytes += $fileBytes
                            $panelImagesIncluded += 1
                        }
                    }

                    if ($panelImagesIncluded -gt 0) {
                        $panelSelectionNote = ("Panel index and manifest are included. {0} high-detail panel image(s) are included, prioritized as Driver View first with synchronized Overview Cam and Face Cam images when space remained." -f $panelImagesIncluded)
                    }
                    else {
                        $panelSelectionNote = "Panel index and manifest are included, but high-detail panel images were omitted to stay within AiReviewZipMaxMb. Open the local Full Review folder's frames_panels directory for the full panel set."
                    }
                }
            }

            $includeProxy = $false
            if ($proxyBytes -gt 0 -and (($nonFrameBaseBytes + $selectedFrameBytes + $panelImageBytes + $proxyBytes) -le $maxBytes)) {
                $includeProxy = $true
                [void]$zipEntries.Add(@{ source = $proxyVideo; name = "proxy/review_proxy_1280.mp4" })
            }

            $frameSelectionNote = if ($samplingStep -le 1) {
                "All extracted frames are included."
            }
            else {
                "Every $samplingStep-th extracted frame is included automatically to stay under the upload limit."
            }

            $aiReviewReadme = Join-Path $stagingRoot "README_FOR_AI.txt"
            New-AiReviewReadme `
                -ReadmePath $aiReviewReadme `
                -SourceVideoName $ProcessedItem.SourceVideoName `
                -FramesFolderName $ProcessedItem.FramesFolderName `
                -ProxyIncluded:$includeProxy `
                -FrameSelectionNote $frameSelectionNote `
                -TranslationTargets $ProcessedItem.TranslationTargets `
                -CommentsIncluded:(Test-Path -LiteralPath $commentsFolder) `
                -PanelCropMode $panelPolicyMode `
                -PanelManifestIncluded:$panelMetadataAvailable `
                -PanelImageCount $panelImagesIncluded `
                -PanelSelectionNote $panelSelectionNote

            foreach ($portableRootFileName in @("README_FOR_AI.md", "AI_PACKAGE_MANIFEST.json", "AI_REVIEW_MANIFEST.json", "AI_REVIEW_README.md")) {
                $portableRootFile = Join-Path $ProcessedItem.OutputPath $portableRootFileName
                if (Test-Path -LiteralPath $portableRootFile -PathType Leaf) {
                    [void]$zipEntries.Add(@{ source = $portableRootFile; name = $portableRootFileName })
                }
            }
            # The files made for the ZIP, at its root.
            [void]$zipEntries.Add(@{ source = $stagingRoot; name = "" })

            $zipWrite = Invoke-MediaManglersPythonCli -PythonCommand $PythonExe -Command "zip-write" -StepName "AI review ZIP" `
                -TimeoutSeconds 3600 -Payload @{ zip_path = $zipPath; entries = @($zipEntries.ToArray()) }
            if ($null -eq $zipWrite -or $null -eq $zipWrite.Result -or -not [bool]$zipWrite.Result.ok) {
                $zipError = if ($zipWrite -and $zipWrite.Result) { [string]$zipWrite.Result.error } else { "the Python helper did not answer" }
                throw ("The AI review ZIP could not be written: {0}" -f $zipError)
            }

            $zipSize = [int64]$zipWrite.Result.data.size_bytes
            if ($zipSize -le $maxBytes) {
                return [PSCustomObject]@{
                    ZipPath           = $zipPath
                    ZipSizeMb         = [math]::Round($zipSize / 1MB, 2)
                    ProxyIncluded     = $includeProxy
                    FrameSamplingStep = $samplingStep
                    IncludedFrameCount = $selectedFrames.Count
                    EvidenceSupplementMode = $evidenceSupplementMode
                    PanelCropMode = $panelPolicyMode
                    PanelManifestIncluded = $panelMetadataAvailable
                    PanelImageCount = $panelImagesIncluded
                }
            }

            Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue

            if ($selectedFrames.Count -le 1) {
                break
            }

            if ($samplingStep -eq 1) {
                $samplingStep = 2
            }
            else {
                $samplingStep = $samplingStep * 2
            }
        }

        throw "AI review zip exceeded $MaxSizeMb MB even after automatically thinning the frame set."
    }
    finally {
        if (Test-Path -LiteralPath $tempRoot) {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Resolve-WhisperDevicePreference {
    param(
        [ValidateSet("Auto", "CPU", "GPU")]
        [string]$RequestedDevice = "Auto",
        [psobject]$WhisperProbe,
        [bool]$RequiresLocalWhisper
    )

    $normalizedDevice = if ([string]::IsNullOrWhiteSpace($RequestedDevice)) {
        "Auto"
    }
    else {
        $RequestedDevice.Trim()
    }

    $gpuCapable = $false
    if ($WhisperProbe -and $WhisperProbe.WhisperImportOk -and $WhisperProbe.TorchImportOk -and $WhisperProbe.CudaAvailable) {
        $gpuCapable = $true
    }

    if (-not $RequiresLocalWhisper) {
        return [PSCustomObject]@{
            RequestedDevice = $normalizedDevice
            PreferGpu       = $false
            SummaryLabel    = "not used in AI Private mode"
        }
    }

    switch ($normalizedDevice) {
        "Auto" {
            return [PSCustomObject]@{
                RequestedDevice = "Auto"
                PreferGpu       = $gpuCapable
                SummaryLabel    = if ($gpuCapable) { "Auto (GPU preferred with CPU fallback)" } else { "Auto (CPU fallback)" }
            }
        }
        "CPU" {
            return [PSCustomObject]@{
                RequestedDevice = "CPU"
                PreferGpu       = $false
                SummaryLabel    = "CPU forced"
            }
        }
        "GPU" {
            if (-not $gpuCapable) {
                throw "WhisperDevice GPU was requested, but the selected Local Whisper runtime is not GPU-capable on this machine."
            }

            return [PSCustomObject]@{
                RequestedDevice = "GPU"
                PreferGpu       = $true
                SummaryLabel    = "GPU requested with CPU fallback"
            }
        }
    }
}

function New-MasterReadme {
    param(
        [string]$MasterReadmePath,
        [string]$OutputRoot,
        [array]$ProcessedItems,
        [array]$FailedItems = @(),
        [double]$FrameIntervalSeconds,
        [string]$FullReviewRunManifestPath = "",
        [string]$CoverageMatrixCsvPath = "",
        [string]$CoverageMatrixMarkdownPath = "",
        [string]$CodexEvidencePackageStatus = "",
        [string]$CodexEvidencePackageOutput = "",
        [string]$CodexEvidencePackageManifest = "",
        [string]$EvidencePanelCropMode = "Auto"
    )

    $lines = @()
    $lines += "# AI Review Collection"
    $lines += ""
    $lines += "This self-contained folder contains one Video Mangler study package per processed source video. Point an AI agent at this folder and ask it to read this file before reviewing the package folders."
    $lines += ""
    $lines += "All paths below are relative to this folder, so the collection may be moved to another folder or drive."
    $lines += ""
    $lines += "Selected frame interval:"
    $lines += "$FrameIntervalSeconds seconds"
    $lines += ""
    if (-not [string]::IsNullOrWhiteSpace($CodexEvidencePackageStatus)) {
        $lines += "AI / ticket evidence add-on:"
        $lines += "- Status: $CodexEvidencePackageStatus"
        if (-not [string]::IsNullOrWhiteSpace($FullReviewRunManifestPath)) {
            $lines += "- Full Review run manifest: $(Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath $FullReviewRunManifestPath)"
        }
        if (-not [string]::IsNullOrWhiteSpace($CoverageMatrixCsvPath)) {
            $lines += "- Evidence coverage matrix CSV: $(Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath $CoverageMatrixCsvPath)"
        }
        if (-not [string]::IsNullOrWhiteSpace($CoverageMatrixMarkdownPath)) {
            $lines += "- Evidence coverage matrix Markdown: $(Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath $CoverageMatrixMarkdownPath)"
        }
        $lines += "- Panel crops: $(Get-EvidencePanelCropModeSummary -Mode $EvidencePanelCropMode)"
        $lines += "- Scope: per-video; open each package folder's README_FOR_AI.md first and its optional ticket-evidence folder when present."
        $lines += ""
    }
    $lines += "Typical package contents:"
    $lines += "- proxy\review_proxy_1280.mp4"
    $lines += "- $(Get-FramesFolderName -Value $FrameIntervalSeconds)\frame_000001.jpg ..."
    $lines += "- audio\audio.mp3 when the source has audio"
    $lines += "- audio\audio_tracks.json / .csv when the source has audio"
    $lines += "- audio\transcript_source_manifest.json for all-track transcript runs"
    $lines += "- transcript\transcript.srt / .json / .txt"
    $lines += "- transcript\tracks\ and transcript\all_audio_tracks_* when all audio tracks were transcribed"
    $lines += "- translations\<lang>\transcript.* when requested"
    $lines += "- comments\comments.* when available and requested"
    $lines += "- frame_index.csv"
    $lines += "- README_FOR_AI.md (portable, agent-neutral starting point)"
    $lines += "- AI_PACKAGE_MANIFEST.json (portable machine-readable inventory)"
    $lines += "- README_FOR_CODEX.txt (legacy compatibility)"
    $lines += "- script_run.log (includes raw OpenAI error details when available)"
    $lines += ""
    $lines += "Processed packages:"
    foreach ($item in $ProcessedItems) {
        $packageSuffix = if ($item.PackageStatus -eq "PARTIAL_SUCCESS") { " (partial success)" } else { "" }
        $lines += "- $($item.OutputFolderName)  <=  $($item.SourceVideoName)$packageSuffix"
        if (-not [string]::IsNullOrWhiteSpace($item.AiReviewReadmePath)) {
            $lines += "  AI review README: $(Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$item.AiReviewReadmePath))"
        }
        if (-not [string]::IsNullOrWhiteSpace($item.AiReviewManifestPath)) {
            $lines += "  AI review manifest: $(Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$item.AiReviewManifestPath))"
        }
        if (-not [string]::IsNullOrWhiteSpace($item.PanelFramesSummary)) {
            $lines += "  Full Review panel crops: $($item.PanelFramesSummary)"
        }
        if (-not [string]::IsNullOrWhiteSpace($item.PanelFrameIndexPath)) {
            $lines += "  Panel frame index: $(Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$item.PanelFrameIndexPath))"
        }
        if (-not [string]::IsNullOrWhiteSpace($item.TranscriptAudioSelection)) {
            $portableTranscriptAudioSelection = Get-PortableDiagnosticText -Message ([string]$item.TranscriptAudioSelection)
            $lines += "  Transcript audio source: $portableTranscriptAudioSelection"
        }
        if (-not [string]::IsNullOrWhiteSpace($item.AllAudioTracksTranscriptPath)) {
            $lines += "  All audio tracks transcript: $(Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$item.AllAudioTracksTranscriptPath))"
        }
        if (-not [string]::IsNullOrWhiteSpace($item.CodexEvidenceStatus)) {
            $reviewNeededSummary = if ($null -ne $item.PSObject.Properties["CodexEvidenceReviewNeededCount"]) { "; review-needed $($item.CodexEvidenceReviewNeededCount)" } else { "" }
            $lines += "  AI / ticket evidence: $($item.CodexEvidenceStatus) (candidates $($item.CodexEvidenceCandidateCount)$reviewNeededSummary)"
        }
        if (-not [string]::IsNullOrWhiteSpace($item.CodexEvidenceOutputRoot)) {
            $lines += "  AI / ticket evidence folder: $(Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$item.CodexEvidenceOutputRoot))"
        }
        if (-not [string]::IsNullOrWhiteSpace($item.CodexEvidenceManifestPath)) {
            $lines += "  AI / ticket evidence manifest: $(Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$item.CodexEvidenceManifestPath))"
        }
    }

    if (@($FailedItems).Count -gt 0) {
        $lines += ""
        $lines += "Failed or incomplete source items:"
        foreach ($item in @($FailedItems)) {
            $sourceName = if (-not [string]::IsNullOrWhiteSpace([string]$item.SourceVideoName)) {
                [string]$item.SourceVideoName
            }
            elseif (-not [string]::IsNullOrWhiteSpace([string]$item.VideoPath)) {
                Split-Path -Path ([string]$item.VideoPath) -Leaf
            }
            else {
                "unknown"
            }
            $phase = if (-not [string]::IsNullOrWhiteSpace([string]$item.FailurePhase)) { [string]$item.FailurePhase } else { Get-FullReviewFailurePhase -Message ([string]$item.Message) }
            $lines += "- $sourceName ($phase): $(Get-PortableDiagnosticText -Message ([string]$item.Message))"
        }
        $lines += ""
        $lines += "Do not treat missing Codex evidence, AI review manifests, or AI review ZIPs for failed rows as proof that no ticket/update evidence exists. Inspect the evidence coverage matrix and rerun or review logs as needed."
    }

    $lines | Set-Content -LiteralPath $MasterReadmePath -Encoding UTF8
    $lines | Set-Content -LiteralPath (Join-Path $OutputRoot "README_FOR_AI.md") -Encoding UTF8
}

function New-FullReviewRunManifest {
    param(
        [string]$ManifestPath,
        [string]$OutputRoot,
        [array]$ProcessedItems,
        [array]$FailedItems,
        [bool]$CodexEvidenceRequested,
        [string]$CodexEvidenceSelectionSource,
        [string]$CodexEvidenceStatus,
        [string]$CodexEvidenceSkipReason = "",
        [psobject]$CodexEvidenceResult = $null,
        [string]$EvidencePanelCropMode = "Auto",
        [string]$EvidenceTargetRepo = "",
        [array]$CoverageRows = @(),
        [string]$CoverageMatrixCsvPath = "",
        [string]$CoverageMatrixMarkdownPath = ""
    )

    $codexEvidence = [ordered]@{
        requested        = [bool]$CodexEvidenceRequested
        selection_source = $CodexEvidenceSelectionSource
        status           = $CodexEvidenceStatus
        skip_reason      = $CodexEvidenceSkipReason
        output_root      = ""
        manifest_path    = ""
        readme_path      = ""
        quality_report   = ""
        candidate_count  = 0
        review_needed_count = 0
        visual_followup_required_count = 0
        target_repo_hint = $EvidenceTargetRepo
        panel_crops      = [ordered]@{
            mode                  = $EvidencePanelCropMode
            source_dimension_rule = "Only exact 5760x1080 source frames are split into panel crops."
            panels                = @(
                [ordered]@{ role = "overview_cam"; label = "Overview Cam"; crop = "1920:1080:0:0" },
                [ordered]@{ role = "driver_view"; label = "Driver View"; crop = "1920:1080:1920:0" },
                [ordered]@{ role = "face_cam"; label = "Face Cam"; crop = "1920:1080:3840:0" }
            )
        }
    }

    if ($CodexEvidenceResult) {
        $codexEvidence.output_root = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$CodexEvidenceResult.OutputRoot)
        $codexEvidence.manifest_path = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$CodexEvidenceResult.ManifestPath)
        $codexEvidence.readme_path = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$CodexEvidenceResult.ReadmePath)
        $codexEvidence.quality_report = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$CodexEvidenceResult.QualityReport)
        $codexEvidence.candidate_count = [int]$CodexEvidenceResult.CandidateCount
        $codexEvidence.review_needed_count = [int]$CodexEvidenceResult.ReviewNeededCount
        $codexEvidence.visual_followup_required_count = [int]$CodexEvidenceResult.VisualFollowupCount
    }

    $processedVideoEntries = @($ProcessedItems | ForEach-Object {
        [ordered]@{
            source_video_name = [string]$_.SourceVideoName
            source_path_hash_or_safe_id = Get-Sha256ShortText -Value ([string]$_.SourceVideoPath)
            output_folder_name = [string]$_.OutputFolderName
            output_path = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$_.OutputPath)
            package_status = [string]$_.PackageStatus
            portable_ai_readme_path = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$_.PortableAiReadmePath)
            portable_ai_manifest_path = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$_.PortableAiManifestPath)
            ai_review_manifest_path = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$_.AiReviewManifestPath)
            ai_review_readme_path = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$_.AiReviewReadmePath)
            ai_review_package_path = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$_.AiReviewZipPath)
            source_dimensions = [ordered]@{
                width = [int]$_.SourceWidth
                height = [int]$_.SourceHeight
            }
            full_review_panel_crops = [ordered]@{
                mode = [string]$_.FullReviewPanelCropMode
                generated = [bool]$_.FullReviewPanelCropsGenerated
                status = [string]$_.FullReviewPanelCropStatus
                skip_reason = [string]$_.FullReviewPanelCropSkipReason
                cadence_seconds = [double]$_.FullReviewPanelCropCadenceSeconds
                frame_count = [int]$_.FullReviewPanelFrameCount
                index_path = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$_.PanelFrameIndexPath)
                manifest_path = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$_.PanelFrameManifestPath)
                output_root = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$_.PanelFramesPath)
            }
            transcript_audio_source = [ordered]@{
                selection_summary = [string]$_.TranscriptAudioSelection
                inventory_json = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$_.AudioTracksJson)
                inventory_csv = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$_.AudioTracksCsv)
                audio_track_count = [int]$_.AudioTrackCount
                transcript_audio_mode_resolved = [string]$_.TranscriptAudioModeResolved
                is_all_tracks = [bool]$_.IsAllAudioTracksTranscript
                transcript_source_wav = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$_.TranscriptSourceWav)
                metadata_path = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$_.TranscriptSourceMetadataPath)
                manifest_path = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$_.TranscriptSourceManifestPath)
                track_wav_folder = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$_.AudioTrackWavFolder)
                all_tracks_review_mix_wav = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$_.AllTracksReviewMixWav)
                all_tracks_review_mix_status = [string]$_.AllTracksReviewMixStatus
                all_audio_tracks_transcript = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$_.AllAudioTracksTranscriptPath)
                all_audio_tracks_index = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$_.AllAudioTracksIndexPath)
                all_audio_tracks_manifest = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$_.AllAudioTracksManifestPath)
                per_track_transcripts = @(ConvertTo-PortableTrackTranscripts -PackageRoot $OutputRoot -TrackTranscripts @($_.TrackTranscripts))
            }
            codex_evidence_package = [ordered]@{
                requested        = [bool]$_.CodexEvidenceRequested
                selection_source = [string]$_.CodexEvidenceSelectionSource
                status           = [string]$_.CodexEvidenceStatus
                skip_reason      = [string]$_.CodexEvidenceSkipReason
                output_root      = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$_.CodexEvidenceOutputRoot)
                manifest_path    = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$_.CodexEvidenceManifestPath)
                readme_path      = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$_.CodexEvidenceReadmePath)
                quality_report   = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$_.CodexEvidenceQualityReport)
                candidate_count  = [int]$_.CodexEvidenceCandidateCount
                review_needed_count = $(if ($null -ne $_.PSObject.Properties["CodexEvidenceReviewNeededCount"]) { [int]$_.CodexEvidenceReviewNeededCount } else { 0 })
                review_needed_path = $(if ($null -ne $_.PSObject.Properties["CodexEvidenceReviewNeededPath"]) { Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$_.CodexEvidenceReviewNeededPath) } else { "" })
                visual_followup_required_count = $(if ($null -ne $_.PSObject.Properties["CodexEvidenceVisualFollowupCount"]) { [int]$_.CodexEvidenceVisualFollowupCount } else { 0 })
            }
        }
    })

    $failedVideoEntries = @($FailedItems | ForEach-Object {
        $sourceName = if (-not [string]::IsNullOrWhiteSpace([string]$_.SourceVideoName)) {
            [string]$_.SourceVideoName
        }
        elseif (-not [string]::IsNullOrWhiteSpace([string]$_.VideoPath)) {
            Split-Path -Path ([string]$_.VideoPath) -Leaf
        }
        else {
            "unknown"
        }
        [ordered]@{
            source_video_name = $sourceName
            source_path_hash_or_safe_id = Get-Sha256ShortText -Value $(if (-not [string]::IsNullOrWhiteSpace([string]$_.SourceVideoPath)) { [string]$_.SourceVideoPath } else { [string]$_.VideoPath })
            output_folder_name = [string]$_.OutputFolderName
            output_path = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath ([string]$_.OutputPath)
            failure_phase = $(if (-not [string]::IsNullOrWhiteSpace([string]$_.FailurePhase)) { [string]$_.FailurePhase } else { Get-FullReviewFailurePhase -Message ([string]$_.Message) })
            message = Get-PortableDiagnosticText -Message ([string]$_.Message)
            codex_evidence_requested = [bool]$CodexEvidenceRequested
            codex_evidence_status = $(if (-not [string]::IsNullOrWhiteSpace([string]$_.CodexEvidenceStatus)) { [string]$_.CodexEvidenceStatus } elseif ($CodexEvidenceRequested) { "not_attempted" } else { "not_requested" })
        }
    })
    $codexEvidence["scope"] = "per-video"
    $codexEvidence["per_video_package_count"] = @($ProcessedItems | Where-Object { $_.CodexEvidenceStatus -eq "included" }).Count
    $codexEvidence["per_video_candidate_count"] = (@($ProcessedItems | ForEach-Object { if ($null -ne $_.PSObject.Properties["CodexEvidenceCandidateCount"]) { [int]$_.CodexEvidenceCandidateCount } else { 0 } }) | Measure-Object -Sum).Sum
    $codexEvidence["per_video_review_needed_count"] = (@($ProcessedItems | ForEach-Object { if ($null -ne $_.PSObject.Properties["CodexEvidenceReviewNeededCount"]) { [int]$_.CodexEvidenceReviewNeededCount } else { 0 } }) | Measure-Object -Sum).Sum
    $codexEvidence["per_video"] = @($processedVideoEntries | ForEach-Object {
        $itemEvidence = $_["codex_evidence_package"]
        [ordered]@{
            source_video_name = $_["source_video_name"]
            output_path = $_["output_path"]
            ai_review_manifest_path = $_["ai_review_manifest_path"]
            ai_review_readme_path = $_["ai_review_readme_path"]
            status = $itemEvidence["status"]
            output_root = $itemEvidence["output_root"]
            manifest_path = $itemEvidence["manifest_path"]
            candidate_count = $itemEvidence["candidate_count"]
            review_needed_count = $itemEvidence["review_needed_count"]
            review_needed_path = $itemEvidence["review_needed_path"]
            visual_followup_required_count = $itemEvidence["visual_followup_required_count"]
            skip_reason = $itemEvidence["skip_reason"]
        }
    })
    $codexEvidence["requested_but_missing_package_count"] = @($CoverageRows | Where-Object { $_.codex_evidence_package_status -in @("failed", "not_attempted", "requested") }).Count

    $payload = [ordered]@{
        generated_at = (Get-Date).ToString("o")
        app_surface  = $script:AppName
        app_version  = (Get-AppVersion)
        path_mode    = "package_relative"
        output_root  = "."
        full_review  = [ordered]@{
            processed_package_count = @($ProcessedItems).Count
            failed_package_count    = @($FailedItems).Count
            processed_videos        = $processedVideoEntries
            failed_videos           = $failedVideoEntries
            evidence_coverage_matrix = [ordered]@{
                csv_path = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath $CoverageMatrixCsvPath
                markdown_path = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath $CoverageMatrixMarkdownPath
                row_count = @($CoverageRows).Count
                rows = @($CoverageRows)
            }
        }
        codex_evidence_package = $codexEvidence
    }

    ($payload | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $ManifestPath -Encoding UTF8

    $portableCollection = [ordered]@{
        schema = "media-manglers-ai-collection-v1"
        generated_at = (Get-Date).ToString("o")
        path_mode = "package_relative"
        start_here = "README_FOR_AI.md"
        detailed_run_manifest = Get-PortablePackagePath -PackageRoot $OutputRoot -TargetPath $ManifestPath
        packages = @($processedVideoEntries | ForEach-Object {
            [ordered]@{
                source_video_name = $_["source_video_name"]
                package_status = $_["package_status"]
                folder = $_["output_path"]
                start_here = $_["portable_ai_readme_path"]
                manifest = $_["portable_ai_manifest_path"]
            }
        })
        failures = @($failedVideoEntries)
    }
    ($portableCollection | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath (Join-Path $OutputRoot "AI_PACKAGE_MANIFEST.json") -Encoding UTF8
}

function Get-TranslationTargets {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return @()
    }

    return @(
        $Value -split '[,\s]+' |
            ForEach-Object { $_.Trim().ToLowerInvariant() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Select-Object -Unique
    )
}

function Get-InteractiveTranslationProvider {
    param(
        [string]$DefaultValue = "Auto",
        [ref]$WasExplicitSelection = $null
    )

    while ($true) {
        Write-Host ""
        Write-Host "Translation provider" -ForegroundColor Cyan
        Write-Host "Video Mangler always transcribes the original spoken source first." -ForegroundColor Cyan
        Write-Host "That source-derived transcript is the preferred base for translation." -ForegroundColor Cyan
        Write-Host "  1. Auto   best available per target (default)" -ForegroundColor Cyan
        Write-Host "  2. OpenAI best quality, needs a configured OpenAI API key" -ForegroundColor Cyan
        Write-Host "  3. Local  free fallback using local tools on this PC" -ForegroundColor Cyan

        $choice = Read-TimedChoicePrompt `
            -Prompt ("Press Enter for Auto, or type 1, 2, or 3. Auto-selects in {0}s:" -f $script:PromptTimeoutSeconds) `
            -DefaultValue "Auto"
        if ([string]::IsNullOrWhiteSpace($choice)) {
            if ($WasExplicitSelection) {
                $WasExplicitSelection.Value = $false
            }
            return $DefaultValue
        }

        switch ($choice.Trim()) {
            "1" {
                if ($WasExplicitSelection) {
                    $WasExplicitSelection.Value = $true
                }
                return "Auto"
            }
            "Auto" {
                if ($WasExplicitSelection) {
                    $WasExplicitSelection.Value = $false
                }
                return "Auto"
            }
            "2" {
                if ($WasExplicitSelection) {
                    $WasExplicitSelection.Value = $true
                }
                return "OpenAI"
            }
            "3" {
                if ($WasExplicitSelection) {
                    $WasExplicitSelection.Value = $true
                }
                return "Local"
            }
            default {
                Write-Host "Please enter 1, 2, 3, or just press Enter for Auto." -ForegroundColor Yellow
            }
        }
    }
}

function Get-OpenAiKeyPreference {
    $projectMode = if ([string]::IsNullOrWhiteSpace($OpenAiProject)) {
        "Private"
    }
    else {
        $OpenAiProject.Trim()
    }

    $primaryVariable = if ($projectMode -eq "Public") {
        "OPENAI_API_KEY_PUBLIC"
    }
    else {
        "OPENAI_API_KEY_PRIVATE"
    }

    return [PSCustomObject]@{
        ProjectMode         = $projectMode
        PrimaryVariable     = $primaryVariable
        LegacyVariable      = "OPENAI_API_KEY"
        AllowLegacyFallback = ($projectMode -eq "Private")
    }
}

function Get-InteractiveProcessingMode {
    param([string]$DefaultValue = "Local")

    while ($true) {
        Write-Host ""
        Write-Host "Processing mode" -ForegroundColor Cyan
        Write-Host "Choose the full workflow you want Video Mangler to use." -ForegroundColor Cyan
        Write-Host "  1. Local   transcription and translation stay on this PC" -ForegroundColor Cyan
        Write-Host "  2. AI      uses OpenAI where the selected AI project mode allows it" -ForegroundColor Cyan
        Write-Host "  3. Hybrid  Hybrid Accuracy keeps audio local and uses OpenAI for English text translation" -ForegroundColor Cyan

        $choice = Read-TimedChoicePrompt `
            -Prompt ("Press Enter for Local, or type 1, 2, or 3. Auto-selects in {0}s:" -f $script:PromptTimeoutSeconds) `
            -DefaultValue "Local"
        if ([string]::IsNullOrWhiteSpace($choice)) {
            return $DefaultValue
        }

        switch ($choice.Trim().ToLowerInvariant()) {
            "1" { return "Local" }
            "local" { return "Local" }
            "2" { return "AI" }
            "ai" { return "AI" }
            "3" { return "Hybrid" }
            "hybrid" { return "Hybrid" }
            default { Write-Host "Please enter 1, 2, 3, or just press Enter for Local." -ForegroundColor Yellow }
        }
    }
}

function Get-InteractiveOpenAiProjectMode {
    param([string]$DefaultValue = "Private")

    while ($true) {
        Write-Host ""
        Write-Host "OpenAI project mode" -ForegroundColor Cyan
        Write-Host "  1. Private  private OpenAI project (default)" -ForegroundColor Cyan
        Write-Host "  2. Public   public/shared OpenAI project" -ForegroundColor Cyan

        $choice = Read-TimedChoicePrompt `
            -Prompt ("Press Enter for Private, or type 1 or 2. Auto-selects in {0}s:" -f $script:PromptTimeoutSeconds) `
            -DefaultValue "Private"
        if ([string]::IsNullOrWhiteSpace($choice)) {
            return $DefaultValue
        }

        switch ($choice.Trim().ToLowerInvariant()) {
            "1" { return "Private" }
            "private" { return "Private" }
            "2" { return "Public" }
            "public" { return "Public" }
            default { Write-Host "Please enter 1, 2, or just press Enter for Private." -ForegroundColor Yellow }
        }
    }
}

function Get-InteractiveLocalWhisperSourceDurationSeconds {
    param(
        [string]$InputPath,
        [string]$FFprobeExe,
        [switch]$Recurse
    )

    if ([string]::IsNullOrWhiteSpace($InputPath)) {
        return 0.0
    }

    try {
        $normalizedInput = Normalize-UserPath -Path $InputPath
        if (-not (Test-Path -LiteralPath $normalizedInput)) {
            return 0.0
        }

        $totalDuration = 0.0
        foreach ($videoItem in @(Get-VideoFilesFromPath -Path $normalizedInput -Recurse:$Recurse)) {
            $duration = Get-VideoDurationSeconds -FFprobeExe $FFprobeExe -VideoPath $videoItem.FullName
            if ($duration -gt 0) {
                $totalDuration += $duration
            }
        }

        return $totalDuration
    }
    catch {
        return 0.0
    }
}

function Get-InteractiveLocalWhisperModelSelection {
    param(
        [string]$DefaultValue = "medium",
        [double]$SourceDurationSeconds = 0.0,
        [bool]$CanUseWhisperGpu = $false,
        [string]$WorkflowLabel = "selected workflow"
    )

    $estimateLabel = if ($CanUseWhisperGpu) { "GPU-capable Whisper estimate" } else { "CPU-only Whisper estimate" }

    $choices = @(
        [PSCustomObject]@{
            Key         = "1"
            Model       = "small"
            Description = "fastest, lower accuracy"
            Estimate    = Get-LocalWhisperPromptEstimateLabel -SourceDurationSeconds $SourceDurationSeconds -MinMultiplier $(if ($CanUseWhisperGpu) { 0.20 } else { 0.8 }) -MaxMultiplier $(if ($CanUseWhisperGpu) { 0.50 } else { 1.4 })
        },
        [PSCustomObject]@{
            Key         = "2"
            Model       = "medium"
            Description = "balanced"
            Estimate    = Get-LocalWhisperPromptEstimateLabel -SourceDurationSeconds $SourceDurationSeconds -MinMultiplier $(if ($CanUseWhisperGpu) { 0.35 } else { 1.3 }) -MaxMultiplier $(if ($CanUseWhisperGpu) { 0.80 } else { 2.2 })
        },
        [PSCustomObject]@{
            Key         = "3"
            Model       = "large"
            Description = "slowest, best accuracy"
            Estimate    = Get-LocalWhisperPromptEstimateLabel -SourceDurationSeconds $SourceDurationSeconds -MinMultiplier $(if ($CanUseWhisperGpu) { 0.75 } else { 2.0 }) -MaxMultiplier $(if ($CanUseWhisperGpu) { 1.40 } else { 4.0 })
        }
    )

    while ($true) {
        Write-Host ""
        Write-Host "Local Whisper model" -ForegroundColor Cyan
        Write-Host ("Choose the Local transcription model for the {0}. These are rough transcription-only estimates, not guarantees." -f $WorkflowLabel) -ForegroundColor Cyan
        if ($SourceDurationSeconds -gt 0) {
            Write-Host ("Source duration: {0}" -f (Format-DurationHuman -Seconds $SourceDurationSeconds)) -ForegroundColor Cyan
        }

        foreach ($choice in $choices) {
            $defaultSuffix = if ($choice.Model -eq $DefaultValue) { " (default)" } else { "" }
            Write-Host ("  {0}. {1}{2}  {3}; {4} {5}" -f $choice.Key, $choice.Model, $defaultSuffix, $choice.Description, $estimateLabel, $choice.Estimate) -ForegroundColor Cyan
        }

        Write-Host "Large note: on CPU-only systems, longer files can still take a very long time. Media Mangler now uses an adaptive hard runtime budget plus a separate stall watchdog." -ForegroundColor Yellow

        $choice = Read-TimedChoicePrompt `
            -Prompt ("Press Enter for {0}, or type 1, 2, 3, small, medium, or large. Auto-selects in {1}s:" -f $DefaultValue, $script:PromptTimeoutSeconds) `
            -DefaultValue $DefaultValue
        if ([string]::IsNullOrWhiteSpace($choice)) {
            return [PSCustomObject]@{
                Model       = $DefaultValue
                UsedDefault = $true
            }
        }

        switch ($choice.Trim().ToLowerInvariant()) {
            "1" { return [PSCustomObject]@{ Model = "small"; UsedDefault = $false } }
            "2" { return [PSCustomObject]@{ Model = "medium"; UsedDefault = $false } }
            "3" { return [PSCustomObject]@{ Model = "large"; UsedDefault = $false } }
            "small" { return [PSCustomObject]@{ Model = "small"; UsedDefault = $false } }
            "medium" { return [PSCustomObject]@{ Model = "medium"; UsedDefault = $false } }
            "large" { return [PSCustomObject]@{ Model = "large"; UsedDefault = $false } }
            default {
                Write-Host "Please enter 1, 2, 3, small, medium, large, or just press Enter for the default." -ForegroundColor Yellow
            }
        }
    }
}

function Get-InteractiveTranslationTargets {
    param([string]$DefaultTarget = "en")

    while ($true) {
        $translate = Read-TimedYesNoPrompt `
            -Prompt ("Translate the transcript into another language? (Y/n, auto-selects Y in {0}s):" -f $script:PromptTimeoutSeconds) `
            -DefaultYes $true
        if ($translate) {
            while ($true) {
                $targetInput = Read-TimedDefaultPrompt `
                    -Prompt ("Enter the target language code(s) like en, es, fr or en,es. Press Enter for {0}, or wait {1}s for default:" -f $DefaultTarget, $script:PromptTimeoutSeconds) `
                    -DefaultValue $DefaultTarget
                if ([string]::IsNullOrWhiteSpace($targetInput)) {
                    return $DefaultTarget
                }

                $normalizedTargets = @(Get-TranslationTargets -Value $targetInput)
                if ($normalizedTargets.Count -gt 0) {
                    return ($normalizedTargets -join ",")
                }

                Write-Host "Please enter at least one language code like en, es, fr, or en,es." -ForegroundColor Yellow
            }
        }

        return ""
    }
}

function Get-ProcessingModeSummary {
    param(
        [string]$EffectiveMode,
        [string]$ProjectMode
    )

    if ($EffectiveMode -eq "Hybrid") {
        return "Hybrid Accuracy"
    }

    if ($EffectiveMode -ne "AI") {
        return "Local"
    }

    if ($ProjectMode -eq "Public") {
        return "AI Public"
    }

    return "AI Private"
}

function Get-TranscriptionProviderDetails {
    param(
        [string]$EffectiveMode,
        [string]$ProjectMode,
        [string]$Model = ""
    )

    if ($EffectiveMode -eq "Hybrid") {
        return "Local (Whisper transcription, Hybrid keeps audio on this PC)"
    }

    if ($EffectiveMode -ne "AI") {
        return "Local (Whisper transcription)"
    }

    if ($ProjectMode -eq "Public") {
        return "Local (Whisper transcription, AI Public keeps audio on this PC)"
    }

    $resolvedModel = if ([string]::IsNullOrWhiteSpace($Model)) {
        $script:OpenAiTranscriptionModel
    }
    else {
        $Model.Trim()
    }

    return ("OpenAI ({0} transcription)" -f $resolvedModel)
}

function Get-TranslationModeSummary {
    param(
        [string]$EffectiveMode,
        [string]$ProjectMode,
        [string]$Model,
        [bool]$TranslationRequested = $true
    )

    if (-not $TranslationRequested) {
        return "not requested"
    }

    if ($EffectiveMode -eq "Hybrid") {
        $projectLabel = if ([string]::IsNullOrWhiteSpace($ProjectMode)) { "Private" } else { $ProjectMode }
        if ([string]::IsNullOrWhiteSpace($Model)) {
            return ("OpenAI text translation ({0} project; audio kept local)" -f $projectLabel)
        }

        return ("OpenAI text translation via {0} ({1} project; audio kept local)" -f $Model, $projectLabel)
    }

    if ($EffectiveMode -eq "AI") {
        $projectLabel = if ([string]::IsNullOrWhiteSpace($ProjectMode)) { "Private" } else { $ProjectMode }
        if ([string]::IsNullOrWhiteSpace($Model)) {
            return ("OpenAI translation ({0} project)" -f $projectLabel)
        }

        return ("OpenAI translation via {0} ({1} project)" -f $Model, $projectLabel)
    }

    return "Local translation on this PC"
}

function Get-TranslationModeForProcessingMode {
    param([string]$EffectiveMode)

    if ($EffectiveMode -eq "AI" -or $EffectiveMode -eq "Hybrid") {
        return "OpenAI"
    }

    return "Local"
}

function Resolve-ProcessingModeRequest {
    param(
        [string]$RequestedMode = "",
        [switch]$WasExplicitlySet,
        [string]$RequestedLegacyTranslationProvider = "",
        [switch]$LegacyProviderWasExplicitlySet,
        [switch]$InteractiveMode
    )

    $requestedModeValue = if ([string]::IsNullOrWhiteSpace($RequestedMode)) {
        ""
    }
    else {
        $RequestedMode.Trim()
    }

    $legacyProviderValue = if ([string]::IsNullOrWhiteSpace($RequestedLegacyTranslationProvider)) {
        ""
    }
    else {
        $RequestedLegacyTranslationProvider.Trim()
    }

    $selectionSource = "default"
    $effectiveMode = $requestedModeValue
    $resolutionNotes = New-Object System.Collections.Generic.List[string]

    if ($WasExplicitlySet) {
        $selectionSource = "explicit"
        if ([string]::IsNullOrWhiteSpace($effectiveMode)) {
            $effectiveMode = "Local"
        }

        if ($LegacyProviderWasExplicitlySet) {
            $legacyMappedMode = switch ($legacyProviderValue) {
                "Local"  { "Local" }
                "OpenAI" { "AI" }
                "Auto"   { if (Test-OpenAiTranslationAvailable) { "AI" } else { "Local" } }
                default  { "" }
            }

            if (-not [string]::IsNullOrWhiteSpace($legacyMappedMode) -and $legacyMappedMode -ne $effectiveMode) {
                [void]$resolutionNotes.Add(("ProcessingMode {0} overrides legacy TranslationProvider {1}." -f $effectiveMode, $legacyProviderValue))
            }
        }
    }
    elseif ($LegacyProviderWasExplicitlySet) {
        $selectionSource = "legacy TranslationProvider"
        switch ($legacyProviderValue) {
            "Local" {
                $effectiveMode = "Local"
                [void]$resolutionNotes.Add("Legacy TranslationProvider Local maps to ProcessingMode Local.")
            }
            "OpenAI" {
                $effectiveMode = "AI"
                [void]$resolutionNotes.Add("Legacy TranslationProvider OpenAI maps to ProcessingMode AI.")
            }
            "Auto" {
                if (Test-OpenAiTranslationAvailable) {
                    $effectiveMode = "AI"
                    [void]$resolutionNotes.Add("Legacy TranslationProvider Auto mapped to ProcessingMode AI because an OpenAI key is available.")
                }
                else {
                    $effectiveMode = "Local"
                    [void]$resolutionNotes.Add("Legacy TranslationProvider Auto mapped to ProcessingMode Local because no OpenAI key is available.")
                }
            }
            default {
                $effectiveMode = "Local"
                [void]$resolutionNotes.Add(("Unknown legacy TranslationProvider value '{0}' was treated as Local." -f $legacyProviderValue))
            }
        }
    }
    elseif ($InteractiveMode) {
        $effectiveMode = Get-InteractiveProcessingMode -DefaultValue "Local"
        $selectionSource = "interactive"
    }
    else {
        $effectiveMode = "Local"
        [void]$resolutionNotes.Add("Processing mode defaulted to Local because no explicit mode was provided.")
    }

    return [PSCustomObject]@{
        RequestedMode        = $requestedModeValue
        EffectiveMode        = $effectiveMode
        SelectionSource      = $selectionSource
        ResolutionNote       = ($resolutionNotes -join " ")
        RequestedLegacyValue = $legacyProviderValue
    }
}

function Test-OpenAiDiagnosticsEnabled {
    $diagnosticsSetting = [Environment]::GetEnvironmentVariable("MM_OPENAI_DIAGNOSTICS")
    if ([string]::IsNullOrWhiteSpace($diagnosticsSetting)) {
        return $false
    }

    return $diagnosticsSetting.Trim() -notmatch '^(?i)(0|false|no|off)$'
}

function Normalize-OpenAiModelId {
    param([string]$ModelId)

    if ([string]::IsNullOrWhiteSpace($ModelId)) {
        return ""
    }

    return $ModelId.Trim().ToLowerInvariant()
}

function Get-OpenAiApprovedTranslationModels {
    param([string]$ProjectMode)

    if ($ProjectMode -eq "Public") {
        return @($script:OpenAiPublicTranslationApprovedModels)
    }

    return @($script:OpenAiPrivateTranslationApprovedModels)
}

function Get-OpenAiApprovedTranscriptionModels {
    param([string]$ProjectMode)

    if ($ProjectMode -eq "Public") {
        return @()
    }

    return @($script:OpenAiPrivateTranscriptionApprovedModels)
}

function Get-OpenAiApprovedModelFallbackDefault {
    param(
        [ValidateSet("Translation", "Transcription")]
        [string]$Capability,
        [string]$ProjectMode
    )

    if ($Capability -eq "Translation") {
        if ($ProjectMode -eq "Public") {
            return $script:OpenAiPublicTranslationDefaultModel
        }

        return $script:OpenAiPrivateTranslationDefaultModel
    }

    return $script:OpenAiTranscriptionModel
}

function Resolve-OpenAiApprovedModelName {
    param(
        [string]$RequestedModel,
        [string[]]$ApprovedModels
    )

    $normalizedRequestedModel = Normalize-OpenAiModelId -ModelId $RequestedModel
    if ([string]::IsNullOrWhiteSpace($normalizedRequestedModel)) {
        return $null
    }

    foreach ($approvedModel in @($ApprovedModels)) {
        if ((Normalize-OpenAiModelId -ModelId $approvedModel) -eq $normalizedRequestedModel) {
            return $approvedModel
        }
    }

    return $null
}

function Get-OpenAiApprovedAccessibleModels {
    param(
        [string[]]$ApprovedModels,
        [string[]]$AccessibleModels
    )

    $accessibleLookup = @{}
    foreach ($modelId in @($AccessibleModels)) {
        $normalizedModelId = Normalize-OpenAiModelId -ModelId $modelId
        if (-not [string]::IsNullOrWhiteSpace($normalizedModelId)) {
            $accessibleLookup[$normalizedModelId] = $true
        }
    }

    $matches = New-Object System.Collections.Generic.List[string]
    foreach ($approvedModel in @($ApprovedModels)) {
        $normalizedApprovedModel = Normalize-OpenAiModelId -ModelId $approvedModel
        if ($accessibleLookup.ContainsKey($normalizedApprovedModel)) {
            [void]$matches.Add($approvedModel)
        }
    }

    return $matches.ToArray()
}

function Test-OpenAiModelDiscoveryFallbackAllowed {
    param([PSCustomObject]$DiscoveryResult)

    if ($null -eq $DiscoveryResult) {
        return $false
    }

    if ($DiscoveryResult.Success) {
        return $false
    }

    if ($DiscoveryResult.Skipped) {
        return $true
    }

    $failureCategory = ""
    if ($DiscoveryResult.FailureDetails) {
        $failureCategory = [string]$DiscoveryResult.FailureDetails.Category
    }

    return $failureCategory -in @("", "Network", "Timeout", "ServerError", "Unexpected")
}

function Get-OpenAiAccessibleModelIds {
    param(
        [string]$ProjectMode,
        [string]$ProviderLabel = "OpenAI model discovery"
    )

    $resolvedProjectMode = if ([string]::IsNullOrWhiteSpace($ProjectMode)) {
        "Private"
    }
    else {
        $ProjectMode.Trim()
    }

    $cacheKey = $resolvedProjectMode.ToLowerInvariant()
    if ($script:OpenAiModelDiscoveryCache.ContainsKey($cacheKey)) {
        return $script:OpenAiModelDiscoveryCache[$cacheKey]
    }

    $testMode = Get-OpenAiTestMode
    if (-not [string]::IsNullOrWhiteSpace($testMode)) {
        $result = [PSCustomObject]@{
            Success        = $false
            Skipped        = $true
            ModelIds       = @()
            Endpoint       = "https://api.openai.com/v1/models"
            ErrorMessage   = ("OpenAI model discovery was skipped because MM_TEST_OPENAI_MODE='{0}' is active." -f $testMode)
            NextStep       = ""
            FailureDetails = $null
        }
        $script:OpenAiModelDiscoveryCache[$cacheKey] = $result
        return $result
    }

    $apiKey = Get-OpenAiApiKey -Required -ProviderLabel $ProviderLabel
    $endpoint = "https://api.openai.com/v1/models"

    try {
        $response = Invoke-RestMethod -Method Get -Uri $endpoint -Headers @{ Authorization = "Bearer $apiKey" }
        $modelIds = @(
            $response.data |
                ForEach-Object { [string]$_.id } |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
                Select-Object -Unique
        )

        $result = [PSCustomObject]@{
            Success        = $true
            Skipped        = $false
            ModelIds       = @($modelIds)
            Endpoint       = $endpoint
            ErrorMessage   = ""
            NextStep       = ""
            FailureDetails = $null
        }
    }
    catch {
        $failureDetails = Get-OpenAiFailureDetails -Exception $_.Exception
        $errorMessage = if ($failureDetails -and -not [string]::IsNullOrWhiteSpace($failureDetails.UserMessage)) {
            $failureDetails.UserMessage
        }
        else {
            ("OpenAI model discovery failed: {0}" -f $_.Exception.Message)
        }

        $nextStep = if ($failureDetails -and -not [string]::IsNullOrWhiteSpace($failureDetails.NextStep)) {
            $failureDetails.NextStep
        }
        else {
            "Check the OpenAI project permissions and network access, then try again."
        }

        $result = [PSCustomObject]@{
            Success        = $false
            Skipped        = $false
            ModelIds       = @()
            Endpoint       = $endpoint
            ErrorMessage   = $errorMessage
            NextStep       = $nextStep
            FailureDetails = $failureDetails
        }
    }

    $script:OpenAiModelDiscoveryCache[$cacheKey] = $result
    return $result
}

function Resolve-OpenAiApprovedModelSelection {
    param(
        [ValidateSet("Translation", "Transcription")]
        [string]$Capability,
        [string]$ProjectMode,
        [string]$RequestedModel = "",
        [switch]$WasExplicitlySet
    )

    $resolvedProjectMode = if ([string]::IsNullOrWhiteSpace($ProjectMode)) {
        "Private"
    }
    else {
        $ProjectMode.Trim()
    }

    $approvedModels = if ($Capability -eq "Translation") {
        Get-OpenAiApprovedTranslationModels -ProjectMode $resolvedProjectMode
    }
    else {
        Get-OpenAiApprovedTranscriptionModels -ProjectMode $resolvedProjectMode
    }

    if (@($approvedModels).Count -eq 0) {
        throw ("OpenAI {0} model selection is not available for AI {1}." -f $Capability.ToLowerInvariant(), $resolvedProjectMode)
    }

    $defaultModel = Get-OpenAiApprovedModelFallbackDefault -Capability $Capability -ProjectMode $resolvedProjectMode
    $requestedApprovedModel = $null
    if ($WasExplicitlySet -and -not [string]::IsNullOrWhiteSpace($RequestedModel)) {
        $requestedApprovedModel = Resolve-OpenAiApprovedModelName -RequestedModel $RequestedModel -ApprovedModels $approvedModels
        if ([string]::IsNullOrWhiteSpace($requestedApprovedModel)) {
            throw ("OpenAI {0} model '{1}' is not allowed for AI {2}. Approved models: {3}" -f $Capability.ToLowerInvariant(), $RequestedModel.Trim(), $resolvedProjectMode, ($approvedModels -join ", "))
        }
    }

    $providerLabel = if ($Capability -eq "Translation") { "OpenAI translation" } else { "OpenAI transcription" }
    $discoveryResult = Get-OpenAiAccessibleModelIds -ProjectMode $resolvedProjectMode -ProviderLabel $providerLabel
    if ($discoveryResult.Success) {
        $accessibleApprovedModels = @(Get-OpenAiApprovedAccessibleModels -ApprovedModels $approvedModels -AccessibleModels $discoveryResult.ModelIds)

        if (Test-OpenAiDiagnosticsEnabled) {
            Write-Log ("OpenAI {0} model discovery for AI {1}: approved visible models = {2}" -f $Capability.ToLowerInvariant(), $resolvedProjectMode, $(if ($accessibleApprovedModels.Count -gt 0) { $accessibleApprovedModels -join ", " } else { "none" }))
        }

        if ($requestedApprovedModel) {
            if ($accessibleApprovedModels -contains $requestedApprovedModel) {
                return [PSCustomObject]@{
                    ResolvedModel            = $requestedApprovedModel
                    SelectionSource          = "explicit"
                    ResolutionNote           = ("OpenAI {0} model '{1}' was explicitly requested and confirmed for AI {2}." -f $Capability.ToLowerInvariant(), $requestedApprovedModel, $resolvedProjectMode)
                    ApprovedModels           = @($approvedModels)
                    AccessibleApprovedModels = @($accessibleApprovedModels)
                    DiscoveryStatus          = "success"
                }
            }

            throw ("OpenAI {0} model '{1}' is approved for AI {2}, but this API key/project cannot access it. Approved models visible to this key: {3}. Expected approved models: {4}" -f $Capability.ToLowerInvariant(), $requestedApprovedModel, $resolvedProjectMode, $(if ($accessibleApprovedModels.Count -gt 0) { $accessibleApprovedModels -join ", " } else { "none" }), ($approvedModels -join ", "))
        }

        if ($accessibleApprovedModels.Count -gt 0) {
            return [PSCustomObject]@{
                ResolvedModel            = $accessibleApprovedModels[0]
                SelectionSource          = "detected"
                ResolutionNote           = ("OpenAI {0} model auto-detected from the approved AI {1} allowlist: {2}" -f $Capability.ToLowerInvariant(), $resolvedProjectMode, $accessibleApprovedModels[0])
                ApprovedModels           = @($approvedModels)
                AccessibleApprovedModels = @($accessibleApprovedModels)
                DiscoveryStatus          = "success"
            }
        }

        throw ("OpenAI {0} cannot continue because AI {1} does not have access to any approved models. Expected one of: {2}" -f $Capability.ToLowerInvariant(), $resolvedProjectMode, ($approvedModels -join ", "))
    }

    if (-not (Test-OpenAiModelDiscoveryFallbackAllowed -DiscoveryResult $discoveryResult)) {
        $errorSuffix = if (-not [string]::IsNullOrWhiteSpace($discoveryResult.NextStep)) {
            (" {0}" -f $discoveryResult.NextStep)
        }
        else {
            ""
        }

        throw ("OpenAI {0} model discovery failed before a safe approved model could be confirmed for AI {1}. {2}{3}" -f $Capability.ToLowerInvariant(), $resolvedProjectMode, $discoveryResult.ErrorMessage, $errorSuffix)
    }

    if ($requestedApprovedModel) {
        return [PSCustomObject]@{
            ResolvedModel            = $requestedApprovedModel
            SelectionSource          = "explicit"
            ResolutionNote           = ("OpenAI {0} model discovery could not confirm visibility. Using the approved explicit model '{1}' for AI {2}. {3}" -f $Capability.ToLowerInvariant(), $requestedApprovedModel, $resolvedProjectMode, $discoveryResult.ErrorMessage)
            ApprovedModels           = @($approvedModels)
            AccessibleApprovedModels = @()
            DiscoveryStatus          = "fallback"
        }
    }

    $fallbackModel = $defaultModel
    if ([string]::IsNullOrWhiteSpace((Resolve-OpenAiApprovedModelName -RequestedModel $fallbackModel -ApprovedModels $approvedModels))) {
        $fallbackModel = @($approvedModels)[0]
    }

    return [PSCustomObject]@{
        ResolvedModel            = $fallbackModel
        SelectionSource          = "fallback-default"
        ResolutionNote           = ("OpenAI {0} model discovery could not confirm visibility. Falling back to the approved default '{1}' for AI {2}. {3}" -f $Capability.ToLowerInvariant(), $fallbackModel, $resolvedProjectMode, $discoveryResult.ErrorMessage)
        ApprovedModels           = @($approvedModels)
        AccessibleApprovedModels = @()
        DiscoveryStatus          = "fallback"
    }
}

function Find-EnvironmentVariableValue {
    param([string]$Name)

    foreach ($scope in @(
            [System.EnvironmentVariableTarget]::Process,
            [System.EnvironmentVariableTarget]::User,
            [System.EnvironmentVariableTarget]::Machine)) {
        $candidate = [Environment]::GetEnvironmentVariable($Name, $scope)
        if (-not [string]::IsNullOrWhiteSpace($candidate)) {
            return [string]$candidate
        }
    }

    return $null
}

function Get-HybridAccuracyGlossaryPath {
    $candidatePaths = New-Object System.Collections.Generic.List[string]

    foreach ($runtimeRoot in @(Get-RuntimeSearchRoots)) {
        $candidatePaths.Add((Join-Path $runtimeRoot $script:HybridAccuracyGlossaryRelativePath))
    }

    foreach ($candidatePath in ($candidatePaths | Select-Object -Unique)) {
        if (-not [string]::IsNullOrWhiteSpace($candidatePath) -and (Test-Path -LiteralPath $candidatePath)) {
            return (Resolve-Path -LiteralPath $candidatePath).ProviderPath
        }
    }

    $searchedPaths = (($candidatePaths | Select-Object -Unique) -join "; ")
    throw ("Hybrid Accuracy could not find its packaged protected terms profile asset '{0}'. {1} Searched: {2}" -f $script:HybridAccuracyGlossaryRelativePath, (Get-PackagedRuntimeGuidance), $searchedPaths)
}

function Assert-HybridAccuracyOpenAiProjectKey {
    param([string]$ProjectMode)

    $resolvedProjectMode = if ([string]::IsNullOrWhiteSpace($ProjectMode)) {
        "Private"
    }
    else {
        $ProjectMode.Trim()
    }

    $variableName = if ($resolvedProjectMode -eq "Public") {
        "OPENAI_API_KEY_PUBLIC"
    }
    else {
        "OPENAI_API_KEY_PRIVATE"
    }

    $value = Find-EnvironmentVariableValue -Name $variableName
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw ("Hybrid Accuracy translation needs {0} for OpenAiProject {1}." -f $variableName, $resolvedProjectMode)
    }

    return $variableName
}

function Invoke-HybridAccuracyTextTranslation {
    param(
        [string]$PythonCommand,
        [string]$TranscriptJsonPath,
        [string]$TranslationFolder,
        [string]$SourceLanguage,
        [string]$TargetLanguage = "en",
        [string]$GlossaryPath,
        [string]$OpenAiProject = "Private",
        [string]$RequestedModel = "",
        [int]$HeartbeatSeconds = 10
    )

    Ensure-Directory $TranslationFolder
    $validationReportPath = Join-Path $TranslationFolder "validation_report.json"
    $cliResult = Invoke-MediaManglersPythonCli `
        -PythonCommand $PythonCommand `
        -Command "hybrid-translate" `
        -Payload @{
            transcript_json_path = $TranscriptJsonPath
            output_dir           = $TranslationFolder
            output_report_path   = $validationReportPath
            source_language      = $SourceLanguage
            target_language      = $TargetLanguage
            glossary_path        = $GlossaryPath
            openai_project       = $OpenAiProject
            requested_model      = $RequestedModel
        } `
        -StepName ("Hybrid Accuracy text translation ({0})" -f $TargetLanguage) `
        -HeartbeatSeconds $HeartbeatSeconds `
        -TimeoutSeconds 300

    if (-not $cliResult) {
        throw (Get-MediaManglersPythonCliUnavailableMessage -FeatureLabel "Hybrid Accuracy text translation")
    }

    if ($cliResult -and $cliResult.ExitCode -eq 0 -and $cliResult.Result -and $cliResult.Result.ok) {
        $data = $cliResult.Result.data
        $usage = $data.usage
        if (-not $usage) {
            $usage = @{}
        }

        $transcriptArtifacts = $data.transcript_artifacts
        if (-not $transcriptArtifacts) {
            $transcriptArtifacts = @{}
        }

        return [PSCustomObject]@{
            ValidationStatus       = [string]$data.validation_status
            OutputStatus           = [string]$data.output_status
            WarningCount           = [int]($data.warning_count)
            ContaminationCount     = [int]($data.contamination_count)
            MojibakeCount          = [int]($data.mojibake_count)
            EncodingArtifactCount  = [int]($data.encoding_artifact_count)
            GlossaryViolationCount = [int]($data.glossary_violation_count)
            CompressionWarningCount = [int]($data.compression_warning_count)
            FailedSegmentCount     = [int]($data.failed_segment_count)
            SegmentCount           = [int]($data.segment_count)
            SourceWordCount        = [int]($data.source_word_count)
            TranslatedWordCount    = [int]($data.translated_word_count)
            EnglishSourceRatio     = if ($null -ne $data.english_source_ratio -and $data.english_source_ratio -ne "") { [double]$data.english_source_ratio } else { $null }
            ValidationReportPath   = [string]$data.validation_report_path
            TranscriptJsonPath     = [string]$transcriptArtifacts.transcript_json_path
            TranscriptSrtPath      = [string]$transcriptArtifacts.transcript_srt_path
            TranscriptTextPath     = [string]$transcriptArtifacts.transcript_txt_path
            GlossaryPath           = [string]$data.glossary_path
            GlossaryProfile        = [string]$data.glossary_profile
            LaneId                 = [string]$data.lane_id
            PrivacyClass           = [string]$data.privacy_class
            RequestedModel         = [string]$data.requested_model
            UsedModel              = [string]$data.used_model
            OpenAiProject          = [string]$data.openai_project
            RetryUsed              = [bool]$data.retry_used
            UsagePromptTokens      = [int]($usage.prompt_tokens)
            UsageCompletionTokens  = [int]($usage.completion_tokens)
            UsageTotalTokens       = [int]($usage.total_tokens)
            EstimatedCostUsd       = if ($null -ne $data.estimated_cost_usd -and $data.estimated_cost_usd -ne "") { [double]$data.estimated_cost_usd } else { $null }
            Errors                 = @($data.errors)
            SegmentWarnings        = @($data.segment_warnings)
            PerBatchResults        = @($data.per_batch_results)
        }
    }

    $cliError = if ($cliResult -and $cliResult.Result -and -not [string]::IsNullOrWhiteSpace($cliResult.Result.error)) {
        [string]$cliResult.Result.error
    }
    else {
        "Hybrid Accuracy Python helper failed before returning a result."
    }

    throw $cliError
}

function Get-OpenAiProjectModeSummary {
    $keyPreference = Get-OpenAiKeyPreference
    if ($keyPreference.ProjectMode -eq "Public") {
        return "Public (explicit)"
    }

    return "Private (default)"
}

function Get-OpenAiKeyRequirementText {
    param([string]$ProviderLabel = "OpenAI translation")

    $keyPreference = Get-OpenAiKeyPreference
    if ($keyPreference.AllowLegacyFallback) {
        return ("{0} cannot continue until {1} is set, or legacy {2} is available." -f $ProviderLabel, $keyPreference.PrimaryVariable, $keyPreference.LegacyVariable)
    }

    return ("{0} cannot continue until {1} is set. Public mode requires an explicit Public project key." -f $ProviderLabel, $keyPreference.PrimaryVariable)
}

function Get-OpenAiKeyTroubleshootingText {
    return "Check the selected OpenAI API key, make sure it belongs to the intended OpenAI Platform project, and turn on Request permission for Chat Completions."
}

function Get-OpenAiSetupInstructionLines {
    param(
        [string]$ProviderLabel = "OpenAI translation",
        [ValidateSet("Interactive", "NonInteractive")]
        [string]$Audience = "NonInteractive"
    )

    $keyPreference = Get-OpenAiKeyPreference
    $lines = @(
        ("{0} was selected, but no API key is available." -f $ProviderLabel),
        "",
        ("Current key profile: {0}" -f (Get-OpenAiProjectModeSummary)),
        ("Preferred environment variable: {0}" -f $keyPreference.PrimaryVariable),
        "",
        ("To use {0}, create a key in your OpenAI Platform account:" -f $ProviderLabel),
        "https://platform.openai.com/api-keys",
        "",
        "Recommended setup for normal use:",
        "- Owned by you",
        "- Dedicated project",
        "- Restricted",
        "- Turn on Request for Chat Completions (/v1/chat/completions)",
        "- Leave unrelated permissions off or set them to None",
        "- Read Only will not work",
        "",
        "Service accounts are mainly for shared or server automation, not normal personal desktop use.",
        "ChatGPT subscriptions and OpenAI API billing are separate.",
        ("If API billing or credits are missing, {0} will not run." -f $ProviderLabel.ToLowerInvariant()),
        "OpenAI API usage may cost money.",
        "If you are unsure, use Private."
    )

    if ($keyPreference.ProjectMode -eq "Public") {
        $lines += "Public mode only works when you explicitly choose -OpenAiProject Public."
        $lines += "The script cannot infer a key's sharing behavior from the secret value."
    }
    else {
        $lines += "Private is the default and safest mode."
        $lines += ("Legacy fallback is still supported for older setups: {0}" -f $keyPreference.LegacyVariable)
    }

    $lines += ""
    $lines += "Use it now:"
    $lines += ('  $env:{0}="sk-..."' -f $keyPreference.PrimaryVariable)
    $lines += "Save it for later:"
    $lines += ('  [System.Environment]::SetEnvironmentVariable("{0}","sk-...","User")' -f $keyPreference.PrimaryVariable)

    if ($Audience -eq "Interactive") {
        $lines += "If you save it for later, open a new PowerShell window before re-checking."
    }
    else {
        if ($keyPreference.ProjectMode -eq "Public") {
            $lines += "Then open a new PowerShell window and rerun with -ProcessingMode AI -OpenAiProject Public."
        }
        else {
            $lines += "Then open a new PowerShell window and rerun with -ProcessingMode AI -OpenAiProject Private."
        }
        $lines += "Do not hardcode the key or commit it to GitHub."
        $lines += "If you do not want OpenAI, rerun with -ProcessingMode Local."
    }

    return $lines
}

function Get-OpenAiSetupInstructionsText {
    param(
        [string]$ProviderLabel = "OpenAI translation"
    )

    return ((Get-OpenAiSetupInstructionLines -ProviderLabel $ProviderLabel -Audience "NonInteractive") -join "`n")
}

function Show-OpenAiSetupGuidance {
    param(
        [string]$ProviderLabel = "OpenAI translation"
    )

    Write-Host ""
    foreach ($line in (Get-OpenAiSetupInstructionLines -ProviderLabel $ProviderLabel -Audience "NonInteractive")) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            Write-Host ""
            continue
        }

        if ($line.StartsWith("  ")) {
            Write-Host $line -ForegroundColor DarkYellow
            continue
        }

        Write-Host $line -ForegroundColor Yellow
    }
}

function Read-OpenAiApiKeyForCurrentRun {
    if ([System.Console]::IsInputRedirected) {
        $rawValue = Read-Host "Paste the OpenAI API key for this run only"
        return [string]$rawValue
    }

    $secureValue = Read-Host "Paste the OpenAI API key for this run only" -AsSecureString
    if ($null -eq $secureValue) {
        return ""
    }

    return [pscredential]::new("openai", $secureValue).GetNetworkCredential().Password
}

function Get-InteractiveOpenAiRecoveryDecision {
    $showSetupGuidance = $true
    while ($true) {
        Write-Host ""
        if ($showSetupGuidance) {
            foreach ($line in (Get-OpenAiSetupInstructionLines -ProviderLabel "OpenAI translation" -Audience "Interactive")) {
                if ([string]::IsNullOrWhiteSpace($line)) {
                    Write-Host ""
                    continue
                }

                if ($line.StartsWith("  ")) {
                    Write-Host $line -ForegroundColor DarkYellow
                    continue
                }

                Write-Host $line -ForegroundColor Yellow
            }
            $showSetupGuidance = $false
        }
        Write-Host "Choose how to continue:" -ForegroundColor Yellow
        Write-Host "  1. Paste API key for this run only" -ForegroundColor Cyan
        Write-Host "  2. Re-check after setting the OpenAI API key externally" -ForegroundColor Cyan
        Write-Host "  3. Switch to Auto" -ForegroundColor Cyan
        Write-Host "  4. Switch to Local" -ForegroundColor Cyan
        Write-Host "  5. Cancel" -ForegroundColor Cyan

        $choice = Read-Host "Type 1, 2, 3, 4, or 5"
        switch ($choice.Trim()) {
            "1" {
                $pastedKey = [string](Read-OpenAiApiKeyForCurrentRun)
                if ([string]::IsNullOrWhiteSpace($pastedKey)) {
                    Write-Host "No API key was pasted. Try again or choose a different option." -ForegroundColor Yellow
                    continue
                }

                $script:SessionOpenAiApiKey = $pastedKey.Trim()
                return [PSCustomObject]@{
                    EffectiveProvider = "OpenAI"
                    ResolutionNote    = "OpenAI translation was selected. Using an API key pasted for this run only."
                }
            }
            "2" {
                if (Test-OpenAiTranslationAvailable) {
                    return [PSCustomObject]@{
                        EffectiveProvider = "OpenAI"
                        ResolutionNote    = "OpenAI translation was selected. An OpenAI API key was found after re-check."
                    }
                }

                Write-Host "An OpenAI API key still is not set. Set it in another window, then re-check, or choose a different option." -ForegroundColor Yellow
            }
            "3" {
                return [PSCustomObject]@{
                    EffectiveProvider = "Auto"
                    ResolutionNote    = "OpenAI translation was selected, but the OpenAI API key is missing. Interactive recovery selected: Auto."
                }
            }
            "4" {
                return [PSCustomObject]@{
                    EffectiveProvider = "Local"
                    ResolutionNote    = "OpenAI translation was selected, but the OpenAI API key is missing. Interactive recovery selected: Local."
                }
            }
            "5" {
                throw (Get-OpenAiKeyRequirementText)
            }
            default {
                Write-Host "Please type 1, 2, 3, 4, or 5." -ForegroundColor Yellow
            }
        }
    }
}

function Convert-ToSrtTimestamp {
    param([double]$Seconds)

    $totalMs = [int][math]::Round($Seconds * 1000)
    $hours = [math]::Floor($totalMs / 3600000)
    $totalMs = $totalMs % 3600000
    $minutes = [math]::Floor($totalMs / 60000)
    $totalMs = $totalMs % 60000
    $secondsPart = [math]::Floor($totalMs / 1000)
    $millis = $totalMs % 1000
    return ("{0:00}:{1:00}:{2:00},{3:000}" -f $hours, $minutes, $secondsPart, $millis)
}

function Write-TranscriptArtifactsFromSegments {
    param(
        [string]$OutputFolder,
        [array]$Segments,
        [string]$Language,
        [string]$JsonName,
        [string]$SrtName,
        [string]$TextName,
        [string]$Task = "translate",
        [string]$SourceLanguage = ""
    )

    Ensure-Directory $OutputFolder

    $jsonPath = Join-Path $OutputFolder $JsonName
    $srtPath = Join-Path $OutputFolder $SrtName
    $textPath = Join-Path $OutputFolder $TextName

    $jsonPayload = [PSCustomObject]@{
        language        = $Language
        source_language = $SourceLanguage
        task            = $Task
        text            = (($Segments | ForEach-Object { $_.text }) -join " ").Trim()
        segments        = @(
            $Segments | ForEach-Object {
                [PSCustomObject]@{
                    id    = $_.id
                    start = $_.start
                    end   = $_.end
                    text  = $_.text
                }
            }
        )
    }

    $jsonPayload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $jsonPath -Encoding UTF8

    $srtBuilder = New-Object System.Text.StringBuilder
    $textBuilder = New-Object System.Text.StringBuilder
    $index = 1
    foreach ($segment in $Segments) {
        $text = [string]$segment.text
        if ([string]::IsNullOrWhiteSpace($text)) {
            continue
        }

        [void]$srtBuilder.AppendLine($index)
        [void]$srtBuilder.AppendLine(("{0} --> {1}" -f (Convert-ToSrtTimestamp -Seconds $segment.start), (Convert-ToSrtTimestamp -Seconds $segment.end)))
        [void]$srtBuilder.AppendLine($text.Trim())
        [void]$srtBuilder.AppendLine("")
        [void]$textBuilder.AppendLine($text.Trim())
        $index += 1
    }

    $srtBuilder.ToString() | Set-Content -LiteralPath $srtPath -Encoding UTF8
    $textBuilder.ToString() | Set-Content -LiteralPath $textPath -Encoding UTF8

    return [PSCustomObject]@{
        JsonPath = $jsonPath
        SrtPath  = $srtPath
        TextPath = $textPath
    }
}

function Get-OpenAiTestMode {
    $rawMode = [string][Environment]::GetEnvironmentVariable("MM_TEST_OPENAI_MODE", [System.EnvironmentVariableTarget]::Process)
    if ([string]::IsNullOrWhiteSpace($rawMode)) {
        return ""
    }

    $normalized = $rawMode.Trim().ToLowerInvariant().Replace("-", "_").Replace(" ", "_")
    switch ($normalized) {
        "success"              { return "success" }
        "401"                  { return "unauthorized" }
        "unauthorized"         { return "unauthorized" }
        "invalid_key"          { return "unauthorized" }
        "403"                  { return "permission_denied" }
        "permission"           { return "permission_denied" }
        "permission_denied"    { return "permission_denied" }
        "429"                  { return "rate_limit" }
        "rate_limit"           { return "rate_limit" }
        "rate_limit_exceeded"  { return "rate_limit" }
        "quota"                { return "quota" }
        "billing"              { return "quota" }
        "credits"              { return "quota" }
        "no_credits"           { return "quota" }
        "insufficient_quota"   { return "quota" }
        "500"                  { return "server_error" }
        "server_error"         { return "server_error" }
        "timeout"              { return "timeout" }
        "network"              { return "network" }
        default {
            throw "Unsupported MM_TEST_OPENAI_MODE value '$rawMode'. Use success, unauthorized, permission_denied, rate_limit, quota, server_error, timeout, or network."
        }
    }
}

function Get-OpenAiQuotaUserMessage {
    return "OpenAI rejected this request because API billing or credits are not available for this project or account. ChatGPT subscriptions and API billing are separate. Add payment details / credits in the OpenAI API billing settings, wait a few minutes, then try again."
}

function Get-OpenAiQuotaNextStep {
    return "After API billing is active, retry the translation, or rerun with -ProcessingMode Local to keep everything on this PC."
}

function Get-OpenAiFailureCategoryLabel {
    param([string]$Category)

    switch ($Category) {
        "Quota"            { return "quota/billing" }
        "RateLimit"        { return "rate limit" }
        "Unauthorized"     { return "unauthorized/bad key" }
        "PermissionDenied" { return "permission denied" }
        "Timeout"          { return "timeout" }
        "Network"          { return "network" }
        "ServerError"      { return "server error" }
        default            { return "unknown" }
    }
}

function Get-OpenAiHeaderValue {
    param(
        $Headers,
        [string[]]$Names
    )

    if ($null -eq $Headers -or $null -eq $Names) {
        return ""
    }

    foreach ($name in $Names) {
        if ([string]::IsNullOrWhiteSpace($name)) {
            continue
        }

        try {
            $values = $null
            if ($Headers.TryGetValues($name, [ref]$values)) {
                $joined = @($values) -join ", "
                if (-not [string]::IsNullOrWhiteSpace($joined)) {
                    return $joined
                }
            }
        }
        catch {
        }

        try {
            $value = $Headers[$name]
            if ($null -ne $value) {
                $joined = if ($value -is [System.Collections.IEnumerable] -and -not ($value -is [string])) {
                    @($value) -join ", "
                }
                else {
                    [string]$value
                }

                if (-not [string]::IsNullOrWhiteSpace($joined)) {
                    return $joined
                }
            }
        }
        catch {
        }

        try {
            $values = $Headers.GetValues($name)
            if ($values) {
                $joined = @($values) -join ", "
                if (-not [string]::IsNullOrWhiteSpace($joined)) {
                    return $joined
                }
            }
        }
        catch {
        }
    }

    return ""
}

function Normalize-OpenAiResponseText {
    param([string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return ""
    }

    $trimmed = $Text.Trim()
    try {
        return (($trimmed | ConvertFrom-Json) | ConvertTo-Json -Depth 20 -Compress)
    }
    catch {
        return (($trimmed -replace "\r\n", " ") -replace "\n", " ").Trim()
    }
}

function Get-OpenAiErrorResponseText {
    param([System.Exception]$Exception)

    if ($null -eq $Exception) {
        return ""
    }

    $response = $Exception.Response
    if ($null -eq $response) {
        return ""
    }

    try {
        if ($response.Content -and $response.Content -is [System.Net.Http.HttpContent]) {
            return [string]$response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        }
    }
    catch {
    }

    try {
        if ($Exception.ErrorDetails -and -not [string]::IsNullOrWhiteSpace($Exception.ErrorDetails.Message)) {
            return [string]$Exception.ErrorDetails.Message
        }
    }
    catch {
    }

    try {
        $stream = $response.GetResponseStream()
        if ($null -eq $stream) {
            return ""
        }

        try {
            $reader = New-Object System.IO.StreamReader($stream)
            return [string]$reader.ReadToEnd()
        }
        finally {
            if ($reader) {
                $reader.Dispose()
            }
            $stream.Dispose()
        }
    }
    catch {
        return ""
    }
}

function Get-OpenAiFailureDetails {
    param([System.Exception]$Exception)

    if ($null -eq $Exception) {
        return $null
    }

    $statusCode = 0
    $statusDescription = ""
    $errorCode = ""
    $errorType = ""
    $errorParam = ""
    $serviceMessage = ""
    $rawResponseBody = ""
    $responseBody = ""
    $requestId = ""
    $category = ""
    $recoverable = $false
    $userMessage = if ([string]::IsNullOrWhiteSpace($Exception.Message)) { "The OpenAI request failed." } else { [string]$Exception.Message }
    $nextStep = "Check script_run.log for the OpenAI response details, then try again or rerun with -ProcessingMode Local."
    $showSetupGuidance = $false

    if ($Exception.Data -and $Exception.Data.Contains("OpenAiFailureCategory")) {
        $category = [string]$Exception.Data["OpenAiFailureCategory"]
        $recoverable = [bool]$Exception.Data["OpenAiRecoverable"]
        $statusCode = [int]$Exception.Data["OpenAiStatusCode"]
        $statusDescription = [string]$Exception.Data["OpenAiStatusDescription"]
        $errorCode = [string]$Exception.Data["OpenAiErrorCode"]
        $errorType = [string]$Exception.Data["OpenAiErrorType"]
        $errorParam = [string]$Exception.Data["OpenAiErrorParam"]
        $serviceMessage = [string]$Exception.Data["OpenAiServiceMessage"]
        $rawResponseBody = [string]$Exception.Data["OpenAiResponseBody"]
        $responseBody = Normalize-OpenAiResponseText -Text $rawResponseBody
        $requestId = [string]$Exception.Data["OpenAiRequestId"]
        $userMessage = [string]$Exception.Data["OpenAiUserMessage"]
        $nextStep = [string]$Exception.Data["OpenAiNextStep"]
        $showSetupGuidance = [bool]$Exception.Data["OpenAiShowSetupGuidance"]
    }
    else {
        $response = $Exception.Response
        if ($response) {
            try {
                if ($response.StatusCode) {
                    $statusCode = [int]$response.StatusCode
                }
            }
            catch {
                $statusCode = 0
            }

            try {
                if ($response.ReasonPhrase) {
                    $statusDescription = [string]$response.ReasonPhrase
                }
            }
            catch {
            }

            if ([string]::IsNullOrWhiteSpace($statusDescription)) {
                try {
                    if ($response.StatusDescription) {
                        $statusDescription = [string]$response.StatusDescription
                    }
                }
                catch {
                }
            }

            $requestId = Get-OpenAiHeaderValue -Headers $response.Headers -Names @("x-request-id", "request-id")
            if ([string]::IsNullOrWhiteSpace($requestId) -and $response.Content) {
                $requestId = Get-OpenAiHeaderValue -Headers $response.Content.Headers -Names @("x-request-id", "request-id")
            }
        }

        $rawResponseBody = Get-OpenAiErrorResponseText -Exception $Exception
        $responseBody = Normalize-OpenAiResponseText -Text $rawResponseBody
        if (-not [string]::IsNullOrWhiteSpace($responseBody)) {
            try {
                $parsed = $responseBody | ConvertFrom-Json
                if ($parsed.error) {
                    $serviceMessage = [string]$parsed.error.message
                    $errorCode = [string]$parsed.error.code
                    $errorType = [string]$parsed.error.type
                    $errorParam = [string]$parsed.error.param
                }
            }
            catch {
            }
        }

        $messageParts = New-Object System.Collections.Generic.List[string]
        $currentException = $Exception
        while ($currentException) {
            if (-not [string]::IsNullOrWhiteSpace($currentException.Message)) {
                [void]$messageParts.Add([string]$currentException.Message)
            }
            $currentException = $currentException.InnerException
        }
        foreach ($detail in @($serviceMessage, $errorCode, $errorType, $errorParam, $statusDescription, $responseBody)) {
            if (-not [string]::IsNullOrWhiteSpace($detail)) {
                [void]$messageParts.Add([string]$detail)
            }
        }

        $combinedMessage = $messageParts -join " "

        if (($statusCode -eq 429) -and ($combinedMessage -match '(?i)insufficient_quota|quota|billing|credit|credits|balance|payment|billing_hard_limit|billing_not_active')) {
            $category = "Quota"
            $recoverable = $true
            $userMessage = Get-OpenAiQuotaUserMessage
            $nextStep = Get-OpenAiQuotaNextStep
        }
        elseif (($statusCode -eq 401) -or ($combinedMessage -match '(?i)unauthorized|invalid api key|incorrect api key|invalid_api_key|authentication')) {
            $category = "Unauthorized"
            $recoverable = $true
            $userMessage = "OpenAI rejected the request with 401 Unauthorized. The API key is missing, invalid, or not usable for this project."
            $nextStep = Get-OpenAiKeyTroubleshootingText
            $showSetupGuidance = $true
        }
        elseif (($statusCode -eq 403) -or ($combinedMessage -match '(?i)permission denied|permission_denied|forbidden|access denied|does not have access|insufficient permissions|not allowed')) {
            $category = "PermissionDenied"
            $recoverable = $true
            $userMessage = "OpenAI rejected the request because this API key or project does not have permission to call Chat Completions."
            $nextStep = "Check the OpenAI Platform project, model access, and Request permission for Chat Completions, then try again."
            $showSetupGuidance = $true
        }
        elseif (($statusCode -eq 429) -or ($combinedMessage -match '(?i)rate limit|rate_limit|rate_limit_exceeded|too many requests|requests per min|tokens per min|requests per day|tokens per day')) {
            $category = "RateLimit"
            $recoverable = $true
            $userMessage = "OpenAI rate-limited the translation request because too many API requests were sent in a short time (429 Too Many Requests)."
            $nextStep = "Wait a moment, then retry, or rerun with -ProcessingMode Local."
        }
        elseif ($statusCode -ge 500 -and $statusCode -lt 600) {
            $category = "ServerError"
            $recoverable = $true
            $userMessage = ("OpenAI returned a server error ({0})." -f $statusCode)
            $nextStep = "Retry later, or rerun with -ProcessingMode Local."
        }
        elseif ($combinedMessage -match '(?i)timed out|timeout|operation has timed out') {
            $category = "Timeout"
            $recoverable = $true
            $userMessage = "The OpenAI request timed out before translation completed."
            $nextStep = "Retry later, or rerun with -ProcessingMode Local."
        }
        elseif ($combinedMessage -match '(?i)no such host is known|name or service not known|could not resolve|unable to connect|connection.*failed|connection.*closed|network') {
            $category = "Network"
            $recoverable = $true
            $userMessage = "The OpenAI request failed before a response came back from the service."
            $nextStep = "Check the network connection, then retry or rerun with -ProcessingMode Local."
        }
        elseif ($statusCode -gt 0) {
            if (-not [string]::IsNullOrWhiteSpace($serviceMessage)) {
                $userMessage = ("OpenAI returned HTTP {0}. {1}" -f $statusCode, $serviceMessage)
            }
            else {
                $userMessage = ("OpenAI returned HTTP {0}." -f $statusCode)
            }
        }
        elseif (-not [string]::IsNullOrWhiteSpace($serviceMessage)) {
            $userMessage = ("The OpenAI request failed. {0}" -f $serviceMessage)
        }
    }

    if ([string]::IsNullOrWhiteSpace($category)) {
        $category = "Unknown"
    }

    $categoryLabel = Get-OpenAiFailureCategoryLabel -Category $category
    $diagnosticParts = New-Object System.Collections.Generic.List[string]
    if (-not [string]::IsNullOrWhiteSpace($categoryLabel)) {
        [void]$diagnosticParts.Add($categoryLabel)
    }
    if ($statusCode -gt 0) {
        if ([string]::IsNullOrWhiteSpace($statusDescription)) {
            [void]$diagnosticParts.Add(("HTTP {0}" -f $statusCode))
        }
        else {
            [void]$diagnosticParts.Add(("HTTP {0} {1}" -f $statusCode, $statusDescription))
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($errorCode)) {
        [void]$diagnosticParts.Add(("error.code={0}" -f $errorCode))
    }
    if (-not [string]::IsNullOrWhiteSpace($errorType)) {
        [void]$diagnosticParts.Add(("error.type={0}" -f $errorType))
    }
    if (-not [string]::IsNullOrWhiteSpace($errorParam)) {
        [void]$diagnosticParts.Add(("error.param={0}" -f $errorParam))
    }
    if (-not [string]::IsNullOrWhiteSpace($requestId)) {
        [void]$diagnosticParts.Add(("request_id={0}" -f $requestId))
    }

    return [PSCustomObject]@{
        Category          = $category
        CategoryLabel     = $categoryLabel
        Recoverable       = $recoverable
        StatusCode        = $statusCode
        StatusDescription = $statusDescription
        ErrorCode         = $errorCode
        ErrorType         = $errorType
        ErrorParam        = $errorParam
        ServiceMessage    = $serviceMessage
        RawResponseBody   = $rawResponseBody
        ResponseBody      = $responseBody
        RequestId         = $requestId
        UserMessage       = $userMessage
        NextStep          = $nextStep
        DiagnosticSummary = ($diagnosticParts -join "; ")
        ShowSetupGuidance = $showSetupGuidance
    }
}

function Write-OpenAiSegmentDiagnostic {
    param(
        [string]$DiagnosticsFolder,
        [int]$SegmentIndex,
        [string]$TargetLanguage,
        [string]$Model,
        [string]$Endpoint,
        [string]$RequestBody,
        [int]$StatusCode = 0,
        [string]$ResponseBody = ""
    )

    if ([string]::IsNullOrWhiteSpace($DiagnosticsFolder)) {
        return
    }

    Ensure-Directory $DiagnosticsFolder
    $diagnosticPath = Join-Path $DiagnosticsFolder ("segment_{0:D3}.json" -f $SegmentIndex)
    $payload = [ordered]@{
        timestamp_utc   = (Get-Date).ToUniversalTime().ToString("o")
        segment_index   = $SegmentIndex
        target_language = $TargetLanguage
        model           = $Model
        endpoint        = $Endpoint
        request_body    = $RequestBody
        http_status     = $StatusCode
    }

    if (-not [string]::IsNullOrWhiteSpace($ResponseBody)) {
        $payload.response_body = $ResponseBody
    }

    [PSCustomObject]$payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $diagnosticPath -Encoding UTF8
}

function Get-OpenAiProviderFailureText {
    param([PSCustomObject]$FailureDetails)

    if ($null -eq $FailureDetails) {
        return "OpenAI failed"
    }

    $parts = New-Object System.Collections.Generic.List[string]
    if (-not [string]::IsNullOrWhiteSpace($FailureDetails.CategoryLabel)) {
        [void]$parts.Add($FailureDetails.CategoryLabel)
    }
    if ($FailureDetails.StatusCode -gt 0) {
        [void]$parts.Add(("HTTP {0}" -f $FailureDetails.StatusCode))
    }
    if (-not [string]::IsNullOrWhiteSpace($FailureDetails.ErrorCode)) {
        [void]$parts.Add(("code={0}" -f $FailureDetails.ErrorCode))
    }
    elseif (-not [string]::IsNullOrWhiteSpace($FailureDetails.ErrorType)) {
        [void]$parts.Add(("type={0}" -f $FailureDetails.ErrorType))
    }

    if ($parts.Count -eq 0) {
        return "OpenAI failed"
    }

    return ("OpenAI failed ({0})" -f ($parts -join ", "))
}

function Write-OpenAiFailureDiagnostics {
    param(
        [string]$TargetLanguage,
        [PSCustomObject]$FailureDetails
    )

    if ($null -eq $FailureDetails) {
        return
    }

    if (-not [string]::IsNullOrWhiteSpace($FailureDetails.DiagnosticSummary)) {
        Write-Log ("OpenAI failure details for '{0}': {1}" -f $TargetLanguage, $FailureDetails.DiagnosticSummary) "WARN"
    }
    if (-not [string]::IsNullOrWhiteSpace($FailureDetails.ServiceMessage)) {
        Write-Log ("OpenAI service message for '{0}': {1}" -f $TargetLanguage, $FailureDetails.ServiceMessage) "WARN"
    }
    if (-not [string]::IsNullOrWhiteSpace($FailureDetails.ResponseBody)) {
        $bodyLine = ("OpenAI raw response body for '{0}': {1}" -f $TargetLanguage, $FailureDetails.ResponseBody)
        if ($bodyLine.Length -le 700 -or -not $script:CurrentLogFile) {
            Write-Log $bodyLine "WARN"
        }
        else {
            Write-Log ("OpenAI raw response body for '{0}' was captured in script_run.log." -f $TargetLanguage) "WARN"
            $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
            Add-Content -LiteralPath $script:CurrentLogFile -Value ("[{0}] [WARN] {1}" -f $timestamp, $bodyLine)
        }
    }
}

function New-OpenAiTranslationException {
    param(
        [string]$TargetLanguage,
        [string]$FailureCategory,
        [string]$UserMessage,
        [string]$NextStep,
        [int]$StatusCode = 0,
        [string]$StatusDescription = "",
        [string]$ErrorCode = "",
        [string]$ErrorType = "",
        [string]$ErrorParam = "",
        [string]$ServiceMessage = "",
        [string]$ResponseBody = "",
        [string]$RequestId = "",
        [bool]$Recoverable = $false,
        [bool]$ShowSetupGuidance = $false,
        [System.Exception]$InnerException = $null
    )

    $message = "OpenAI translation failed for language '$TargetLanguage'. $UserMessage"
    $exception = if ($InnerException) {
        New-Object System.Exception($message, $InnerException)
    }
    else {
        New-Object System.Exception($message)
    }

    $exception.Data["OpenAiFailureCategory"] = $FailureCategory
    $exception.Data["OpenAiRecoverable"] = $Recoverable
    $exception.Data["OpenAiStatusCode"] = $StatusCode
    $exception.Data["OpenAiStatusDescription"] = $StatusDescription
    $exception.Data["OpenAiErrorCode"] = $ErrorCode
    $exception.Data["OpenAiErrorType"] = $ErrorType
    $exception.Data["OpenAiErrorParam"] = $ErrorParam
    $exception.Data["OpenAiServiceMessage"] = $ServiceMessage
    $exception.Data["OpenAiResponseBody"] = $ResponseBody
    $exception.Data["OpenAiRequestId"] = $RequestId
    $exception.Data["OpenAiUserMessage"] = $UserMessage
    $exception.Data["OpenAiNextStep"] = $NextStep
    $exception.Data["OpenAiShowSetupGuidance"] = $ShowSetupGuidance
    return $exception
}

function Get-InteractiveOpenAiRuntimeRecoveryDecision {
    param(
        [string]$TargetLanguage,
        [PSCustomObject]$FailureDetails,
        [bool]$CanUseLocalFallback,
        [string]$LocalFallbackNote = ""
    )

    while ($true) {
        Write-Host ""
        Write-Host ("OpenAI translation for '{0}' hit a recoverable problem." -f $TargetLanguage) -ForegroundColor Yellow
        Write-Host $FailureDetails.UserMessage -ForegroundColor Yellow
        if (-not [string]::IsNullOrWhiteSpace($LocalFallbackNote)) {
            Write-Host $LocalFallbackNote -ForegroundColor DarkYellow
        }
        if ($FailureDetails.ShowSetupGuidance) {
            foreach ($line in (Get-OpenAiSetupInstructionLines -ProviderLabel "OpenAI translation" -Audience "Interactive")) {
                if ([string]::IsNullOrWhiteSpace($line)) {
                    Write-Host ""
                    continue
                }

                if ($line.StartsWith("  ")) {
                    Write-Host $line -ForegroundColor DarkYellow
                    continue
                }

                Write-Host $line -ForegroundColor Yellow
            }
        }

        Write-Host "Choose how to continue:" -ForegroundColor Yellow
        Write-Host "  1. Retry OpenAI for this target" -ForegroundColor Cyan
        if ($CanUseLocalFallback) {
            Write-Host "  2. Switch remaining translation targets to Local" -ForegroundColor Cyan
            Write-Host "  3. Stop translating and keep the completed outputs" -ForegroundColor Cyan
            Write-Host "  4. Cancel this package" -ForegroundColor Cyan
        }
        else {
            Write-Host "  2. Stop translating and keep the completed outputs" -ForegroundColor Cyan
            Write-Host "  3. Cancel this package" -ForegroundColor Cyan
        }

        $choice = if ($CanUseLocalFallback) {
            Read-Host "Type 1, 2, 3, or 4"
        }
        else {
            Read-Host "Type 1, 2, or 3"
        }

        switch ($choice.Trim()) {
            "1" {
                return [PSCustomObject]@{
                    Action         = "Retry"
                    ResolutionNote = ("OpenAI translation for '{0}' was retried after an interactive recovery prompt." -f $TargetLanguage)
                }
            }
            "2" {
                if ($CanUseLocalFallback) {
                    return [PSCustomObject]@{
                        Action         = "UseLocal"
                        ResolutionNote = ("OpenAI translation for '{0}' hit a recoverable problem. Interactive recovery switched the remaining translation targets to Local." -f $TargetLanguage)
                    }
                }

                return [PSCustomObject]@{
                    Action         = "Stop"
                    ResolutionNote = ("OpenAI translation for '{0}' hit a recoverable problem. Interactive recovery kept the completed outputs and stopped further translation work." -f $TargetLanguage)
                }
            }
            "3" {
                if ($CanUseLocalFallback) {
                    return [PSCustomObject]@{
                        Action         = "Stop"
                        ResolutionNote = ("OpenAI translation for '{0}' hit a recoverable problem. Interactive recovery kept the completed outputs and stopped further translation work." -f $TargetLanguage)
                    }
                }

                throw "User canceled the package after an OpenAI translation failure."
            }
            "4" {
                if ($CanUseLocalFallback) {
                    throw "User canceled the package after an OpenAI translation failure."
                }
            }
            default {
                if ($CanUseLocalFallback) {
                    Write-Host "Please type 1, 2, 3, or 4." -ForegroundColor Yellow
                }
                else {
                    Write-Host "Please type 1, 2, or 3." -ForegroundColor Yellow
                }
            }
        }
    }
}

function Get-OpenAiApiKey {
    param(
        [switch]$Required,
        [string]$ProviderLabel = "OpenAI translation"
    )

    $testMode = Get-OpenAiTestMode
    if (-not [string]::IsNullOrWhiteSpace($testMode)) {
        return "__MM_TEST_OPENAI_MODE__"
    }

    $apiKey = [string]$script:SessionOpenAiApiKey
    if ([string]::IsNullOrWhiteSpace($apiKey)) {
        $keyPreference = Get-OpenAiKeyPreference
        $apiKey = Find-EnvironmentVariableValue -Name $keyPreference.PrimaryVariable
        if ([string]::IsNullOrWhiteSpace($apiKey) -and $keyPreference.AllowLegacyFallback) {
            $apiKey = Find-EnvironmentVariableValue -Name $keyPreference.LegacyVariable
        }
    }

    if ($Required -and [string]::IsNullOrWhiteSpace($apiKey)) {
        Show-OpenAiSetupGuidance -ProviderLabel $ProviderLabel
        throw (Get-OpenAiKeyRequirementText -ProviderLabel $ProviderLabel)
    }

    if ([string]::IsNullOrWhiteSpace($apiKey)) {
        return $null
    }

    return $apiKey.Trim()
}

function Test-OpenAiTranslationAvailable {
    if (-not [string]::IsNullOrWhiteSpace((Get-OpenAiTestMode))) {
        return $true
    }

    return -not [string]::IsNullOrWhiteSpace((Get-OpenAiApiKey))
}

function Resolve-TranslationProviderRequest {
    param(
        [string]$RequestedProvider = "Auto",
        [switch]$WasExplicitlySet,
        [switch]$InteractiveMode
    )

    $requestedProviderValue = if ([string]::IsNullOrWhiteSpace($RequestedProvider)) {
        "Auto"
    }
    else {
        $RequestedProvider.Trim()
    }

    $selectionSource = if ($WasExplicitlySet) { "explicit" } else { "default" }
    $effectiveProvider = $requestedProviderValue
    $resolutionNote = $null

    if ($requestedProviderValue -eq "OpenAI" -and -not (Test-OpenAiTranslationAvailable)) {
        if (-not $WasExplicitlySet) {
            $effectiveProvider = "Auto"
            $resolutionNote = "OpenAI was present without an explicit user override, but the selected OpenAI API key is missing. Falling back to Auto."
        }
        elseif ($InteractiveMode) {
            $recoveryDecision = Get-InteractiveOpenAiRecoveryDecision
            $effectiveProvider = $recoveryDecision.EffectiveProvider
            $resolutionNote = $recoveryDecision.ResolutionNote
        }
        else {
            Show-OpenAiSetupGuidance -ProviderLabel "OpenAI translation"
            throw (Get-OpenAiKeyRequirementText)
        }
    }

    return [PSCustomObject]@{
        RequestedProvider = $requestedProviderValue
        EffectiveProvider = $effectiveProvider
        SelectionSource   = $selectionSource
        ResolutionNote    = $resolutionNote
    }
}

function Test-WhisperModelSupportsTranslation {
    param([string]$ModelName)

    if ([string]::IsNullOrWhiteSpace($ModelName)) {
        return $true
    }

    return -not $ModelName.Trim().ToLowerInvariant().EndsWith(".en")
}

function Get-ArgosModuleStatus {
    param(
        [string]$PythonCommand,
        [int]$HeartbeatSeconds = 10
    )

    $cliResult = Invoke-MediaManglersPythonCli `
        -PythonCommand $PythonCommand `
        -Command "argos-status" `
        -Payload @{} `
        -StepName "Argos Translate module check" `
        -HeartbeatSeconds $HeartbeatSeconds `
        -TimeoutSeconds 120

    if ($cliResult) {
        if ($cliResult.ExitCode -eq 0 -and $cliResult.Result -and $cliResult.Result.ok) {
            $data = $cliResult.Result.data
            return [PSCustomObject]@{
                ModuleInstalled = [bool]$data.module_installed
                Error           = [string]$data.error
            }
        }

        $cliError = if ($cliResult.Result -and -not [string]::IsNullOrWhiteSpace($cliResult.Result.error)) {
            [string]$cliResult.Result.error
        }
        else {
            "Tracked Python CLI helper failed before returning a result."
        }
        Write-Log ("Tracked Python Argos status check failed. Falling back to the legacy inline helper. {0}" -f $cliError) "WARN"
    }

    $probe = Invoke-ExternalCapture `
        -FilePath $PythonCommand `
        -Arguments @("-c", "import argostranslate.translate") `
        -StepName "Argos Translate module check" `
        -IgnoreExitCode `
        -HeartbeatSeconds $HeartbeatSeconds `
        -TimeoutSeconds 120

    return [PSCustomObject]@{
        ModuleInstalled = ($probe.ExitCode -eq 0)
        Error           = [string]$probe.StdErr
    }
}

function Get-TranslationProviderPreflightNotes {
    param(
        [string]$EffectiveProvider,
        [string[]]$TranslationTargets,
        [string]$ModelName,
        [string]$PythonCommand,
        [bool]$InteractiveMode,
        [int]$HeartbeatSeconds = 10
    )

    $normalizedTargets = @($TranslationTargets | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)
    if ($normalizedTargets.Count -eq 0) {
        return @()
    }

    if ($EffectiveProvider -ne "Local") {
        return @()
    }

    if (($normalizedTargets -contains "en") -and -not (Test-WhisperModelSupportsTranslation -ModelName $ModelName)) {
        throw ("Local translation to English needs a multilingual Whisper model. The selected model '{0}' is English-only. Use 'large' or another supported Whisper model that does not end in '.en', or rerun with -ProcessingMode AI." -f $ModelName)
    }

    $needsArgos = (@($normalizedTargets | Where-Object { $_ -ne "en" })).Count -gt 0
    if (-not $needsArgos) {
        return @()
    }

    $argosStatus = Get-ArgosModuleStatus -PythonCommand $PythonCommand -HeartbeatSeconds $HeartbeatSeconds
    if ($argosStatus.ModuleInstalled) {
        return @()
    }

    $messageLines = @(
        "Local translation was selected for one or more non-English targets, but Argos Translate is not installed on this PC.",
        "Argos Translate is required for the Local path when the target language is not English.",
        "Install it with:",
        ("  {0} -m pip install argostranslate" -f (Quote-Argument $PythonCommand)),
        "Once the source language is detected, Media Manglers can then prepare the needed Argos language packages.",
        "You can also rerun with -ProcessingMode AI."
    )

    if (-not $InteractiveMode) {
        throw ($messageLines -join "`n")
    }

    return @(($messageLines -join " "))
}

function Get-ArgosInstallCommandHints {
    param(
        [string]$SourceLanguageCode,
        [string]$TargetLanguageCode
    )

    $pairs = New-Object System.Collections.Generic.List[string]
    if (-not [string]::IsNullOrWhiteSpace($SourceLanguageCode) -and -not [string]::IsNullOrWhiteSpace($TargetLanguageCode) -and ($SourceLanguageCode -ne $TargetLanguageCode)) {
        [void]$pairs.Add(("translate-{0}_{1}" -f $SourceLanguageCode, $TargetLanguageCode))
        if ($SourceLanguageCode -ne "en" -and $TargetLanguageCode -ne "en") {
            [void]$pairs.Add(("translate-{0}_{1}" -f $SourceLanguageCode, "en"))
            [void]$pairs.Add(("translate-{0}_{1}" -f "en", $TargetLanguageCode))
        }
    }

    $commands = New-Object System.Collections.Generic.List[string]
    [void]$commands.Add("python -m pip install argostranslate")
    [void]$commands.Add("argospm update")
    foreach ($pair in ($pairs | Select-Object -Unique)) {
        [void]$commands.Add(("argospm install {0}" -f $pair))
    }

    return @($commands | Select-Object -Unique)
}

function Invoke-ArgosProbe {
    param(
        [string]$PythonCommand,
        [string]$SourceLanguageCode,
        [string]$TargetLanguageCode,
        [int]$HeartbeatSeconds = 10
    )

    $cliResult = Invoke-MediaManglersPythonCli `
        -PythonCommand $PythonCommand `
        -Command "argos-probe" `
        -Payload @{
            from_code = $SourceLanguageCode
            to_code   = $TargetLanguageCode
        } `
        -StepName ("Argos probe ({0}->{1})" -f $SourceLanguageCode, $TargetLanguageCode) `
        -HeartbeatSeconds $HeartbeatSeconds `
        -TimeoutSeconds 300

    if ($cliResult) {
        if ($cliResult.ExitCode -eq 0 -and $cliResult.Result -and $cliResult.Result.ok) {
            $data = $cliResult.Result.data
            return [PSCustomObject]@{
                ModuleInstalled    = [bool]$data.module_installed
                CanTranslate       = [bool]$data.can_translate
                InstalledLanguages = @($data.installed_languages)
                Error              = [string]$data.error
            }
        }

        $cliError = if ($cliResult.Result -and -not [string]::IsNullOrWhiteSpace($cliResult.Result.error)) {
            [string]$cliResult.Result.error
        }
        else {
            "Tracked Python CLI helper failed before returning a result."
        }
        Write-Log ("Tracked Python Argos probe failed. Falling back to the legacy inline helper. {0}" -f $cliError) "WARN"
    }

    $tempPy = Join-Path ([System.IO.Path]::GetTempPath()) ("argos_probe_" + [guid]::NewGuid().ToString() + ".py")
    $pyCode = @'
import json
import sys

from_code = sys.argv[1]
to_code = sys.argv[2]
result = {
    "module_installed": False,
    "can_translate": False,
    "installed_languages": [],
    "error": ""
}

try:
    import argostranslate.translate
    result["module_installed"] = True
    languages = argostranslate.translate.get_installed_languages()
    codes = set()
    for language in languages:
        code = getattr(language, "code", "")
        if code:
            codes.add(code)
    result["installed_languages"] = sorted(codes)

    try:
        translation = argostranslate.translate.get_translation_from_codes(from_code, to_code)
        result["can_translate"] = translation is not None
    except Exception as ex:
        result["error"] = str(ex)
except Exception as ex:
    result["error"] = str(ex)

print(json.dumps(result), flush=True)
'@

    Set-Content -LiteralPath $tempPy -Value $pyCode -Encoding UTF8

    try {
        $result = Invoke-ExternalStreaming `
            -FilePath $PythonCommand `
            -Arguments @($tempPy, $SourceLanguageCode, $TargetLanguageCode) `
            -StepName ("Argos probe ({0}->{1})" -f $SourceLanguageCode, $TargetLanguageCode) `
            -IgnoreExitCode `
            -HeartbeatSeconds $HeartbeatSeconds `
            -TimeoutSeconds 300

        $parsedJsonLine = ($result.StdOut -split "`r?`n" | Where-Object { $_.Trim().StartsWith("{") -and $_.Trim().EndsWith("}") } | Select-Object -Last 1)
        if (-not $parsedJsonLine) {
            return [PSCustomObject]@{
                ModuleInstalled    = $false
                CanTranslate       = $false
                InstalledLanguages = @()
                Error              = "Argos probe did not return a parsable result."
            }
        }

        $parsed = $parsedJsonLine | ConvertFrom-Json
        return [PSCustomObject]@{
            ModuleInstalled    = [bool]$parsed.module_installed
            CanTranslate       = [bool]$parsed.can_translate
            InstalledLanguages = @($parsed.installed_languages)
            Error              = [string]$parsed.error
        }
    }
    finally {
        if (Test-Path -LiteralPath $tempPy) {
            Remove-Item -LiteralPath $tempPy -Force -ErrorAction SilentlyContinue
        }
    }
}

function Install-ArgosTranslationSupport {
    param(
        [string]$PythonCommand,
        [string]$SourceLanguageCode,
        [string]$TargetLanguageCode,
        [int]$HeartbeatSeconds = 10
    )

    $probe = Invoke-ArgosProbe `
        -PythonCommand $PythonCommand `
        -SourceLanguageCode $SourceLanguageCode `
        -TargetLanguageCode $TargetLanguageCode `
        -HeartbeatSeconds $HeartbeatSeconds

    if (-not $probe.ModuleInstalled) {
        $pipResult = Invoke-ExternalStreaming `
            -FilePath $PythonCommand `
            -Arguments @("-m", "pip", "install", "argostranslate") `
            -StepName "Install Argos Translate" `
            -IgnoreExitCode `
            -HeartbeatSeconds $HeartbeatSeconds `
            -TimeoutSeconds 1800

        if ($pipResult.ExitCode -ne 0) {
            throw "Could not install Argos Translate with pip. See script_run.log for the exact pip error."
        }
    }

    $cliResult = Invoke-MediaManglersPythonCli `
        -PythonCommand $PythonCommand `
        -Command "argos-install" `
        -Payload @{
            from_code = $SourceLanguageCode
            to_code   = $TargetLanguageCode
        } `
        -StepName ("Install Argos language support ({0}->{1})" -f $SourceLanguageCode, $TargetLanguageCode) `
        -HeartbeatSeconds $HeartbeatSeconds `
        -TimeoutSeconds 3600

    if ($cliResult) {
        if ($cliResult.ExitCode -eq 0 -and $cliResult.Result -and $cliResult.Result.ok) {
            $data = $cliResult.Result.data
            if (-not [bool]$data.success) {
                $errorMessage = [string]$data.error
                if ([string]::IsNullOrWhiteSpace($errorMessage)) {
                    $errorMessage = "Argos did not report a usable translation route after installation."
                }

                throw $errorMessage
            }

            return
        }

        $cliError = if ($cliResult.Result -and -not [string]::IsNullOrWhiteSpace($cliResult.Result.error)) {
            [string]$cliResult.Result.error
        }
        else {
            "Tracked Python CLI helper failed before returning a result."
        }
        Write-Log ("Tracked Python Argos install helper failed. Falling back to the legacy inline helper. {0}" -f $cliError) "WARN"
    }

    $tempPy = Join-Path ([System.IO.Path]::GetTempPath()) ("argos_install_" + [guid]::NewGuid().ToString() + ".py")
    $pyCode = @'
import json
import sys
import traceback

from_code = sys.argv[1]
to_code = sys.argv[2]

result = {
    "success": False,
    "attempted_pairs": [],
    "installed_pairs": [],
    "error": ""
}

def log(msg):
    print(msg, flush=True)

try:
    import argostranslate.package
    import argostranslate.translate
except Exception:
    traceback.print_exc(file=sys.stderr)
    sys.exit(10)

def add_pair(pairs, seen, source_code, target_code):
    if not source_code or not target_code or source_code == target_code:
        return
    key = (source_code, target_code)
    if key in seen:
        return
    seen.add(key)
    pairs.append(key)

def install_pair(available_packages, source_code, target_code):
    package_to_install = next(
        (
            package
            for package in available_packages
            if getattr(package, "from_code", "") == source_code and getattr(package, "to_code", "") == target_code
        ),
        None,
    )
    if package_to_install is None:
        raise RuntimeError(f"No Argos package index entry found for {source_code}->{target_code}")

    download_path = package_to_install.download()
    argostranslate.package.install_from_path(download_path)

try:
    pairs = []
    seen = set()
    add_pair(pairs, seen, from_code, to_code)
    if from_code != "en" and to_code != "en":
        add_pair(pairs, seen, from_code, "en")
        add_pair(pairs, seen, "en", to_code)

    log("[PY] Updating Argos package index...")
    argostranslate.package.update_package_index()
    available_packages = argostranslate.package.get_available_packages()

    for source_code, target_code in pairs:
        result["attempted_pairs"].append({"from": source_code, "to": target_code})
        try:
            log(f"[PY] Installing Argos package {source_code}->{target_code}...")
            install_pair(available_packages, source_code, target_code)
            result["installed_pairs"].append({"from": source_code, "to": target_code})
        except Exception as ex:
            log(f"[PY] Install note for {source_code}->{target_code}: {ex}")

    try:
        translation = argostranslate.translate.get_translation_from_codes(from_code, to_code)
        result["success"] = translation is not None
        if not result["success"]:
            result["error"] = f"Argos still cannot translate {from_code}->{to_code} after installation."
    except Exception as ex:
        result["error"] = str(ex)

    print(json.dumps(result), flush=True)
except Exception:
    traceback.print_exc(file=sys.stderr)
    sys.exit(20)
'@

    Set-Content -LiteralPath $tempPy -Value $pyCode -Encoding UTF8

    try {
        $result = Invoke-ExternalStreaming `
            -FilePath $PythonCommand `
            -Arguments @($tempPy, $SourceLanguageCode, $TargetLanguageCode) `
            -StepName ("Install Argos language support ({0}->{1})" -f $SourceLanguageCode, $TargetLanguageCode) `
            -IgnoreExitCode `
            -HeartbeatSeconds $HeartbeatSeconds `
            -TimeoutSeconds 3600

        if ($result.ExitCode -ne 0) {
            throw "Argos package installation failed. See script_run.log for the exact Python error."
        }

        $parsedJsonLine = ($result.StdOut -split "`r?`n" | Where-Object { $_.Trim().StartsWith("{") -and $_.Trim().EndsWith("}") } | Select-Object -Last 1)
        if (-not $parsedJsonLine) {
            throw "Argos package installation did not return a parsable result. See script_run.log."
        }

        $parsed = $parsedJsonLine | ConvertFrom-Json
        if (-not [bool]$parsed.success) {
            $errorMessage = [string]$parsed.error
            if ([string]::IsNullOrWhiteSpace($errorMessage)) {
                $errorMessage = "Argos did not report a usable translation route after installation."
            }

            throw $errorMessage
        }
    }
    finally {
        if (Test-Path -LiteralPath $tempPy) {
            Remove-Item -LiteralPath $tempPy -Force -ErrorAction SilentlyContinue
        }
    }
}

function Ensure-ArgosTranslationSupport {
    param(
        [string]$PythonCommand,
        [string]$SourceLanguageCode,
        [string]$TargetLanguageCode,
        [bool]$InteractiveMode,
        [int]$HeartbeatSeconds = 10
    )

    $sourceCode = [string]$SourceLanguageCode
    $targetCode = [string]$TargetLanguageCode

    if ([string]::IsNullOrWhiteSpace($sourceCode) -or $sourceCode -eq "unknown") {
        throw "Local translation needs a known source language code. Try -ProcessingMode AI, or rerun with -Language if you know the source language."
    }

    $probe = Invoke-ArgosProbe `
        -PythonCommand $PythonCommand `
        -SourceLanguageCode $sourceCode `
        -TargetLanguageCode $targetCode `
        -HeartbeatSeconds $HeartbeatSeconds

    if ($probe.CanTranslate) {
        return "ready"
    }

    $sourceDisplayName = Get-LanguageDisplayName -Code $sourceCode
    $targetDisplayName = Get-LanguageDisplayName -Code $targetCode
    $commandHints = @(Get-ArgosInstallCommandHints -SourceLanguageCode $sourceCode -TargetLanguageCode $targetCode)

    $messageLines = @()
    if (-not $probe.ModuleInstalled) {
        $messageLines += "Local translation is missing Argos Translate."
    }
    else {
        $messageLines += ("Local translation does not have the needed Argos language package for {0} -> {1} yet." -f $sourceDisplayName, $targetDisplayName)
    }
    $messageLines += ("This unlocks a free local translation path for {0} -> {1} without needing an OpenAI account." -f $sourceDisplayName, $targetDisplayName)
    $messageLines += "OpenAI is usually smoother, but Local keeps the translated transcript on this PC."
    $messageLines += "Suggested install commands:"
    foreach ($command in $commandHints) {
        $messageLines += ("  {0}" -f $command)
    }

    if (-not $InteractiveMode) {
        throw ($messageLines -join "`n")
    }

    Write-Host ""
    foreach ($line in $messageLines) {
        Write-Host $line -ForegroundColor Yellow
    }
    Write-Host ""

    while ($true) {
        $choice = Read-Host "Type I to install now, S to skip this translation, or C to cancel"
        switch ($choice.Trim().ToLowerInvariant()) {
            "i" {
                Install-ArgosTranslationSupport `
                    -PythonCommand $PythonCommand `
                    -SourceLanguageCode $sourceCode `
                    -TargetLanguageCode $targetCode `
                    -HeartbeatSeconds $HeartbeatSeconds
                return "installed"
            }
            "s" {
                return "skip"
            }
            "c" {
                throw "User canceled while preparing local translation support."
            }
            default {
                Write-Host "Please type I, S, or C." -ForegroundColor Yellow
            }
        }
    }
}

function Resolve-TranslationTargetProvider {
    param(
        [string]$TranslationMode,
        [string]$TargetLanguage,
        [string]$DetectedLanguage,
        [string]$ModelName,
        [string]$PythonCommand,
        [bool]$InteractiveMode,
        [int]$HeartbeatSeconds = 10
    )

    $targetLanguageCode = Get-CanonicalLanguageCode -Language $TargetLanguage
    $detectedLanguageCode = Get-CanonicalLanguageCode -Language $DetectedLanguage

    if (-not [string]::IsNullOrWhiteSpace($targetLanguageCode) -and $targetLanguageCode -eq $detectedLanguageCode) {
        return [PSCustomObject]@{
            Action = "ready"
            Provider = "Original transcript copy"
            Note = ""
        }
    }

    if ($TranslationMode -eq "OpenAI") {
        return [PSCustomObject]@{
            Action = "ready"
            Provider = "OpenAI"
            Note = ""
        }
    }

    if ($TranslationMode -eq "Local") {
        if ($TargetLanguage -eq "en") {
            if (-not (Test-WhisperModelSupportsTranslation -ModelName $ModelName)) {
                throw "Local translation to English needs a multilingual Whisper model. Use 'large' or another supported Whisper model that does not end in '.en', or use -ProcessingMode AI."
            }

            return [PSCustomObject]@{
                Action = "ready"
                Provider = "Local (Whisper audio translation)"
                Note = ""
            }
        }

        $argosStatus = Ensure-ArgosTranslationSupport `
            -PythonCommand $PythonCommand `
            -SourceLanguageCode $DetectedLanguage `
            -TargetLanguageCode $TargetLanguage `
            -InteractiveMode:$InteractiveMode `
            -HeartbeatSeconds $HeartbeatSeconds

        if ($argosStatus -eq "skip") {
            return [PSCustomObject]@{
                Action = "skip"
                Provider = "Local (Argos Translate)"
                Note = ("Skipping translation target '{0}' because local Argos support was not installed." -f $TargetLanguage)
            }
        }

        return [PSCustomObject]@{
            Action = "ready"
            Provider = "Local (Argos Translate)"
            Note = ""
        }
    }

    if ($TranslationMode -eq "Auto") {
        if (Test-OpenAiTranslationAvailable) {
            return [PSCustomObject]@{
                Action = "ready"
                Provider = "OpenAI"
                Note = ""
            }
        }

        return Resolve-TranslationTargetProvider `
            -TranslationMode "Local" `
            -TargetLanguage $TargetLanguage `
            -DetectedLanguage $DetectedLanguage `
            -ModelName $ModelName `
            -PythonCommand $PythonCommand `
            -InteractiveMode:$InteractiveMode `
            -HeartbeatSeconds $HeartbeatSeconds
    }

    throw "Unsupported translation mode '$TranslationMode'."
}

function Invoke-OpenAiSegmentTranslation {
    param(
        [array]$Segments,
        [string]$SourceLanguage,
        [string]$TargetLanguage,
        [string]$Model,
        [int]$HeartbeatSeconds = 10,
        [string]$DiagnosticsFolder = ""
    )

    $apiKey = Get-OpenAiApiKey -Required
    $testMode = Get-OpenAiTestMode
    $endpoint = "https://api.openai.com/v1/chat/completions"
    if (-not [string]::IsNullOrWhiteSpace($testMode) -and -not $script:OpenAiTestModeLogged) {
        Write-Log ("MM_TEST_OPENAI_MODE='{0}' active. OpenAI translation calls are being simulated for this run." -f $testMode) "WARN"
        $script:OpenAiTestModeLogged = $true
    }

    $headers = @{
        Authorization = "Bearer $apiKey"
    }
    $contentType = "application/json; charset=utf-8"

    $translatedSegments = @()
    $usagePromptTokens = 0
    $usageCompletionTokens = 0
    $usageTotalTokens = 0
    $usedModel = ""
    $lastProgress = Get-Date
    $segmentIndex = 0
    foreach ($segment in $Segments) {
        $segmentIndex += 1
        $text = [string]$segment.text
        if ([string]::IsNullOrWhiteSpace($text)) {
            $translatedSegments += [PSCustomObject]@{
                id    = $segment.id
                start = $segment.start
                end   = $segment.end
                text  = ""
            }
            continue
        }

        if (((Get-Date) - $lastProgress).TotalSeconds -ge $HeartbeatSeconds) {
            Write-Log ("OpenAI translation still working... {0}/{1} segments translated" -f $segmentIndex, $Segments.Count)
            $lastProgress = Get-Date
        }

        $userPrompt = if ([string]::IsNullOrWhiteSpace($SourceLanguage)) {
            "Translate this spoken transcript segment into $TargetLanguage. Return only the translated text.`n`n$text"
        }
        else {
            "Translate this spoken transcript segment from $SourceLanguage into $TargetLanguage. Return only the translated text.`n`n$text"
        }

        $body = @{
            model = $Model
            messages = @(
                @{
                    role = "system"
                    content = "You translate transcript segments. Return only the translated text with no commentary, labels, or quotes."
                },
                @{
                    role = "user"
                    content = $userPrompt
                }
            )
        } | ConvertTo-Json -Depth 6

        try {
            if ($testMode -eq "success") {
                $translatedText = ("[MM_TEST_OPENAI_SUCCESS:{0}] {1}" -f $TargetLanguage, $text).Trim()
                if ([string]::IsNullOrWhiteSpace($usedModel)) {
                    $usedModel = $Model
                }
            }
            elseif ($testMode -eq "unauthorized") {
                $responseBody = '{"error":{"message":"Incorrect API key provided: sk-test-invalid","type":"invalid_request_error","param":null,"code":"invalid_api_key"}}'
                throw (New-OpenAiTranslationException `
                        -TargetLanguage $TargetLanguage `
                        -FailureCategory "Unauthorized" `
                        -UserMessage "OpenAI rejected the request with 401 Unauthorized. The API key is missing, invalid, or not usable for this project." `
                        -NextStep (Get-OpenAiKeyTroubleshootingText) `
                        -StatusCode 401 `
                        -StatusDescription "Unauthorized" `
                        -ErrorCode "invalid_api_key" `
                        -ErrorType "invalid_request_error" `
                        -ServiceMessage "Incorrect API key provided: sk-test-invalid" `
                        -ResponseBody $responseBody `
                        -Recoverable:$true `
                        -ShowSetupGuidance:$true)
            }
            elseif ($testMode -eq "permission_denied") {
                $responseBody = '{"error":{"message":"You do not have permission to access Chat Completions for this project.","type":"invalid_request_error","param":"model","code":"permission_denied"}}'
                throw (New-OpenAiTranslationException `
                        -TargetLanguage $TargetLanguage `
                        -FailureCategory "PermissionDenied" `
                        -UserMessage "OpenAI rejected the request because this API key or project does not have permission to call Chat Completions." `
                        -NextStep "Check the OpenAI Platform project, model access, and Request permission for Chat Completions, then try again." `
                        -StatusCode 403 `
                        -StatusDescription "Forbidden" `
                        -ErrorCode "permission_denied" `
                        -ErrorType "invalid_request_error" `
                        -ErrorParam "model" `
                        -ServiceMessage "You do not have permission to access Chat Completions for this project." `
                        -ResponseBody $responseBody `
                        -Recoverable:$true `
                        -ShowSetupGuidance:$true)
            }
            elseif ($testMode -eq "rate_limit") {
                $responseBody = '{"error":{"message":"Rate limit reached for requests per min. Please try again in 20s.","type":"rate_limit_error","param":null,"code":"rate_limit_exceeded"}}'
                throw (New-OpenAiTranslationException `
                        -TargetLanguage $TargetLanguage `
                        -FailureCategory "RateLimit" `
                        -UserMessage "OpenAI rate-limited the translation request because too many API requests were sent in a short time (429 Too Many Requests)." `
                        -NextStep "Wait a moment, then retry, or rerun with -ProcessingMode Local." `
                        -StatusCode 429 `
                        -StatusDescription "Too Many Requests" `
                        -ErrorCode "rate_limit_exceeded" `
                        -ErrorType "rate_limit_error" `
                        -ServiceMessage "Rate limit reached for requests per min. Please try again in 20s." `
                        -ResponseBody $responseBody `
                        -Recoverable:$true)
            }
            elseif ($testMode -eq "quota") {
                $responseBody = '{"error":{"message":"You exceeded your current quota, please check your plan and billing details.","type":"insufficient_quota","param":null,"code":"insufficient_quota"}}'
                throw (New-OpenAiTranslationException `
                        -TargetLanguage $TargetLanguage `
                        -FailureCategory "Quota" `
                        -UserMessage (Get-OpenAiQuotaUserMessage) `
                        -NextStep (Get-OpenAiQuotaNextStep) `
                        -StatusCode 429 `
                        -StatusDescription "Too Many Requests" `
                        -ErrorCode "insufficient_quota" `
                        -ErrorType "insufficient_quota" `
                        -ServiceMessage "You exceeded your current quota, please check your plan and billing details." `
                        -ResponseBody $responseBody `
                        -Recoverable:$true)
            }
            elseif ($testMode -eq "server_error") {
                $responseBody = '{"error":{"message":"The server had an error while processing your request.","type":"server_error","param":null,"code":null}}'
                throw (New-OpenAiTranslationException `
                        -TargetLanguage $TargetLanguage `
                        -FailureCategory "ServerError" `
                        -UserMessage "OpenAI returned a server error (500)." `
                        -NextStep "Retry later, or rerun with -ProcessingMode Local." `
                        -StatusCode 500 `
                        -StatusDescription "Internal Server Error" `
                        -ErrorType "server_error" `
                        -ServiceMessage "The server had an error while processing your request." `
                        -ResponseBody $responseBody `
                        -Recoverable:$true)
            }
            elseif ($testMode -eq "timeout") {
                throw (New-OpenAiTranslationException `
                        -TargetLanguage $TargetLanguage `
                        -FailureCategory "Timeout" `
                        -UserMessage "The OpenAI request timed out before translation completed." `
                        -NextStep "Retry later, or rerun with -ProcessingMode Local." `
                        -Recoverable:$true)
            }
            elseif ($testMode -eq "network") {
                throw (New-OpenAiTranslationException `
                        -TargetLanguage $TargetLanguage `
                        -FailureCategory "Network" `
                        -UserMessage "The OpenAI request failed before a response came back from the service." `
                        -NextStep "Check the network connection, then retry or rerun with -ProcessingMode Local." `
                        -Recoverable:$true)
            }
            else {
                $bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($body)
                $response = Invoke-RestMethod -Method Post -Uri $endpoint -Headers $headers -ContentType $contentType -Body $bodyBytes
                $translatedText = [string]$response.choices[0].message.content
                if (-not [string]::IsNullOrWhiteSpace([string]$response.model)) {
                    $usedModel = [string]$response.model
                }
                elseif ([string]::IsNullOrWhiteSpace($usedModel)) {
                    $usedModel = $Model
                }
                if ($null -ne $response.usage) {
                    if ($null -ne $response.usage.prompt_tokens) {
                        $usagePromptTokens += [int]$response.usage.prompt_tokens
                    }
                    if ($null -ne $response.usage.completion_tokens) {
                        $usageCompletionTokens += [int]$response.usage.completion_tokens
                    }
                    if ($null -ne $response.usage.total_tokens) {
                        $usageTotalTokens += [int]$response.usage.total_tokens
                    }
                }
                Write-OpenAiSegmentDiagnostic `
                    -DiagnosticsFolder $DiagnosticsFolder `
                    -SegmentIndex $segmentIndex `
                    -TargetLanguage $TargetLanguage `
                    -Model $Model `
                    -Endpoint $endpoint `
                    -RequestBody $body `
                    -StatusCode 200
            }
        }
        catch {
            $failureDetails = Get-OpenAiFailureDetails -Exception $_.Exception
            if ($failureDetails) {
                Write-OpenAiSegmentDiagnostic `
                    -DiagnosticsFolder $DiagnosticsFolder `
                    -SegmentIndex $segmentIndex `
                    -TargetLanguage $TargetLanguage `
                    -Model $Model `
                    -Endpoint $endpoint `
                    -RequestBody $body `
                    -StatusCode $failureDetails.StatusCode `
                    -ResponseBody $(if (-not [string]::IsNullOrWhiteSpace($failureDetails.RawResponseBody)) { $failureDetails.RawResponseBody } else { $failureDetails.ResponseBody })
                Write-OpenAiFailureDiagnostics -TargetLanguage $TargetLanguage -FailureDetails $failureDetails
                if ($_.Exception.Data -and $_.Exception.Data.Contains("OpenAiFailureCategory")) {
                    throw $_.Exception
                }

                throw (New-OpenAiTranslationException `
                        -TargetLanguage $TargetLanguage `
                        -FailureCategory $failureDetails.Category `
                        -UserMessage $failureDetails.UserMessage `
                        -NextStep $failureDetails.NextStep `
                        -StatusCode $failureDetails.StatusCode `
                        -StatusDescription $failureDetails.StatusDescription `
                        -ErrorCode $failureDetails.ErrorCode `
                        -ErrorType $failureDetails.ErrorType `
                        -ErrorParam $failureDetails.ErrorParam `
                        -ServiceMessage $failureDetails.ServiceMessage `
                        -ResponseBody $failureDetails.ResponseBody `
                        -RequestId $failureDetails.RequestId `
                        -Recoverable:$failureDetails.Recoverable `
                        -ShowSetupGuidance:$failureDetails.ShowSetupGuidance `
                        -InnerException $_.Exception)
            }

            throw "OpenAI translation failed for language '$TargetLanguage'. $($_.Exception.Message)"
        }

        $translatedSegments += [PSCustomObject]@{
            id    = $segment.id
            start = $segment.start
            end   = $segment.end
            text  = $translatedText.Trim()
        }
    }

    if ([string]::IsNullOrWhiteSpace($usedModel)) {
        $usedModel = $Model
    }
    if ($usageTotalTokens -le 0) {
        $usageTotalTokens = $usagePromptTokens + $usageCompletionTokens
    }

    $estimatedCostUsd = Estimate-OpenAiTextCostUsd `
        -Model $usedModel `
        -PromptTokens $usagePromptTokens `
        -CompletionTokens $usageCompletionTokens

    return [PSCustomObject]@{
        Segments              = $translatedSegments
        RequestedModel        = $Model
        UsedModel             = $usedModel
        UsagePromptTokens     = [int]$usagePromptTokens
        UsageCompletionTokens = [int]$usageCompletionTokens
        UsageTotalTokens      = [int]$usageTotalTokens
        EstimatedCostUsd      = if ($null -ne $estimatedCostUsd) { [double]$estimatedCostUsd } else { $null }
    }
}

function Invoke-ArgosSegmentTranslation {
    param(
        [string]$PythonCommand,
        [array]$Segments,
        [string]$SourceLanguageCode,
        [string]$TargetLanguageCode,
        [int]$HeartbeatSeconds = 10
    )

    $cliPayloadSegments = @(
        $Segments | ForEach-Object {
            @{
                id    = $_.id
                start = $_.start
                end   = $_.end
                text  = $_.text
            }
        }
    )

    $cliResult = Invoke-MediaManglersPythonCli `
        -PythonCommand $PythonCommand `
        -Command "argos-translate" `
        -Payload @{
            from_code = $SourceLanguageCode
            to_code   = $TargetLanguageCode
            segments  = $cliPayloadSegments
        } `
        -StepName ("Argos translation ({0}->{1})" -f $SourceLanguageCode, $TargetLanguageCode) `
        -HeartbeatSeconds $HeartbeatSeconds `
        -TimeoutSeconds 3600

    if ($cliResult) {
        if ($cliResult.ExitCode -eq 0 -and $cliResult.Result -and $cliResult.Result.ok) {
            return @(
                $cliResult.Result.data.segments | ForEach-Object {
                    [PSCustomObject]@{
                        id    = $_.id
                        start = [double]$_.start
                        end   = [double]$_.end
                        text  = [string]$_.text
                    }
                }
            )
        }

        $cliError = if ($cliResult.Result -and -not [string]::IsNullOrWhiteSpace($cliResult.Result.error)) {
            [string]$cliResult.Result.error
        }
        else {
            "Tracked Python CLI helper failed before returning a result."
        }
        Write-Log ("Tracked Python Argos translation helper failed. Falling back to the legacy inline helper. {0}" -f $cliError) "WARN"
    }

    $tempPy = Join-Path ([System.IO.Path]::GetTempPath()) ("argos_translate_" + [guid]::NewGuid().ToString() + ".py")
    $tempInputJson = Join-Path ([System.IO.Path]::GetTempPath()) ("argos_translate_input_" + [guid]::NewGuid().ToString() + ".json")
    $tempOutputJson = Join-Path ([System.IO.Path]::GetTempPath()) ("argos_translate_output_" + [guid]::NewGuid().ToString() + ".json")

    $segmentsPayload = [PSCustomObject]@{
        segments = @(
            $Segments | ForEach-Object {
                [PSCustomObject]@{
                    id    = $_.id
                    start = $_.start
                    end   = $_.end
                    text  = $_.text
                }
            }
        )
    }
    $segmentsPayload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $tempInputJson -Encoding UTF8

    $pyCode = @'
import json
import sys
import traceback

input_path = sys.argv[1]
output_path = sys.argv[2]
from_code = sys.argv[3]
to_code = sys.argv[4]

def log(msg):
    print(msg, flush=True)

try:
    import argostranslate.translate
except Exception:
    traceback.print_exc(file=sys.stderr)
    sys.exit(10)

try:
    with open(input_path, "r", encoding="utf-8-sig") as f:
        payload = json.load(f)

    translation = argostranslate.translate.get_translation_from_codes(from_code, to_code)
    segments = payload.get("segments") or []
    translated_segments = []

    for index, segment in enumerate(segments, start=1):
        text = (segment.get("text") or "").strip()
        translated_text = translation.translate(text) if text else ""
        translated_segments.append({
            "id": segment.get("id"),
            "start": segment.get("start"),
            "end": segment.get("end"),
            "text": translated_text.strip()
        })

        if index == 1 or index % 25 == 0 or index == len(segments):
            log(f"[PY] Argos translation still working... {index}/{len(segments)} segments translated")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"segments": translated_segments}, f, ensure_ascii=False, indent=2)

    print(json.dumps({
        "output_path": output_path,
        "segments_count": len(translated_segments)
    }), flush=True)
except Exception:
    traceback.print_exc(file=sys.stderr)
    sys.exit(20)
'@

    Set-Content -LiteralPath $tempPy -Value $pyCode -Encoding UTF8

    try {
        $result = Invoke-ExternalStreaming `
            -FilePath $PythonCommand `
            -Arguments @($tempPy, $tempInputJson, $tempOutputJson, $SourceLanguageCode, $TargetLanguageCode) `
            -StepName ("Argos translation ({0}->{1})" -f $SourceLanguageCode, $TargetLanguageCode) `
            -IgnoreExitCode `
            -HeartbeatSeconds $HeartbeatSeconds `
            -TimeoutSeconds 3600

        if ($result.ExitCode -ne 0) {
            throw "Argos translation failed. See script_run.log for the exact Python error."
        }

        if (-not (Test-Path -LiteralPath $tempOutputJson)) {
            throw "Argos translation did not produce an output file."
        }

        $payload = Get-Content -LiteralPath $tempOutputJson -Raw | ConvertFrom-Json
        return @(
            $payload.segments | ForEach-Object {
                [PSCustomObject]@{
                    id    = $_.id
                    start = [double]$_.start
                    end   = [double]$_.end
                    text  = [string]$_.text
                }
            }
        )
    }
    finally {
        foreach ($tempPath in @($tempPy, $tempInputJson, $tempOutputJson)) {
            if (Test-Path -LiteralPath $tempPath) {
                Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

function Get-LanguageDisplayName {
    param([string]$Code)

    if ([string]::IsNullOrWhiteSpace($Code)) {
        return ""
    }

    $normalized = $Code.Trim().Replace("_", "-")

    try {
        $culture = [System.Globalization.CultureInfo]::GetCultureInfo($normalized)
        if ($culture -and -not [string]::IsNullOrWhiteSpace($culture.EnglishName) -and $culture.EnglishName -notmatch '^Unknown language') {
            return $culture.EnglishName
        }
    }
    catch {
    }

    switch ((Get-PrimaryLanguageTag -LanguageCode $normalized)) {
        "en" { return "English" }
        "es" { return "Spanish" }
        "fr" { return "French" }
        "de" { return "German" }
        "it" { return "Italian" }
        "pt" { return "Portuguese" }
        "ja" { return "Japanese" }
        "ko" { return "Korean" }
        "zh" { return "Chinese" }
        "ar" { return "Arabic" }
        "ru" { return "Russian" }
        "uk" { return "Ukrainian" }
        "hi" { return "Hindi" }
        "tr" { return "Turkish" }
        "pl" { return "Polish" }
        "nl" { return "Dutch" }
        "id" { return "Indonesian" }
        "vi" { return "Vietnamese" }
        "th" { return "Thai" }
        "tl" { return "Filipino" }
        "ur" { return "Urdu" }
        "hu" { return "Hungarian" }
        "cs" { return "Czech" }
        "ro" { return "Romanian" }
        "sv" { return "Swedish" }
        "yue" { return "Cantonese" }
        default { return $normalized }
    }
}

function Get-TranscriptSegments {
    param([string]$TranscriptJsonPath)

    if (-not (Test-Path -LiteralPath $TranscriptJsonPath)) {
        throw "Transcript JSON not found: $TranscriptJsonPath"
    }

    $payload = Get-Content -LiteralPath $TranscriptJsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $segments = @()
    $index = 0
    foreach ($segment in @($payload.segments)) {
        $segments += [PSCustomObject]@{
            id    = if ($null -ne $segment.id) { [int]$segment.id } else { $index }
            start = [double]$segment.start
            end   = [double]$segment.end
            text  = [string]$segment.text
        }
        $index += 1
    }

    return [PSCustomObject]@{
        Language       = [string]$payload.language
        SourceLanguage = [string]$payload.source_language
        Segments       = $segments
    }
}

function Get-TextWordCount {
    param(
        [string]$Text
    )

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return 0
    }

    return [int]([regex]::Matches($Text, "\p{L}[\p{L}\p{N}'-]*|\p{N}+").Count)
}

function Get-TranscriptWordCountFromArtifacts {
    param(
        [string]$TranscriptTextPath,
        [string]$TranscriptJsonPath
    )

    if (-not [string]::IsNullOrWhiteSpace($TranscriptTextPath) -and (Test-Path -LiteralPath $TranscriptTextPath)) {
        return Get-TextWordCount -Text (Get-Content -LiteralPath $TranscriptTextPath -Raw)
    }

    if (-not [string]::IsNullOrWhiteSpace($TranscriptJsonPath) -and (Test-Path -LiteralPath $TranscriptJsonPath)) {
        $payload = Get-TranscriptSegments -TranscriptJsonPath $TranscriptJsonPath
        $count = 0
        foreach ($segment in @($payload.Segments)) {
            $count += Get-TextWordCount -Text ([string]$segment.text)
        }
        return [int]$count
    }

    return 0
}

function Add-SummaryRow {
    param(
        [string]$SummaryCsv,
        [string]$SourceVideo,
        [string]$OutputFolderName,
        [string]$OutputPath,
        [int]$FrameCount,
        [string]$ProxyVideo,
        [string]$AudioFile,
        [string]$TranscriptSrt,
        [string]$TranscriptJson,
        [string]$TranscriptText,
        [string]$RawCopied,
        [string]$AudioPresent,
        [string]$DetectedLanguage,
        [string]$ProcessingModeSummary,
        [string]$OpenAiProjectSummary,
        [string]$TranscriptionPath,
        [string]$TranslationTargets,
        [string]$TranslationPath,
        [string]$CommentsText,
        [string]$CommentsJson,
        [string]$CommentsSummary,
        [string]$RemoteAudioTrack,
        [string]$ProxyMode,
        [string]$FrameMode,
        [string]$WhisperMode,
        [double]$FrameIntervalSeconds,
        [string]$PackageStatus,
        [string]$TranslationStatus,
        [string]$TranslationNotes,
        [string]$NextSteps,
        [string]$TranslationTranscriptJson = "",
        [string]$TranslationTranscriptSrt = "",
        [string]$TranslationTranscriptText = "",
        [string]$TranslationValidationReport = "",
        [string]$LaneId = "",
        [string]$PrivacyClass = "",
        [string]$SourceLanguage = "",
        [string]$TargetLanguage = "",
        [string]$TranscriptionProvider = "",
        [string]$TranscriptionModel = "",
        [string]$TranslationProviderName = "",
        [string]$TranslationModel = "",
        [int]$TranscriptWordCount = 0,
        [int]$TranslatedWordCount = 0,
        [string]$EnglishSourceRatio = "",
        [int]$ValidationWarningCount = 0,
        [int]$ContaminationCount = 0,
        [int]$EncodingArtifactCount = 0,
        [int]$GlossaryViolationCount = 0,
        [int]$CompressionWarningCount = 0,
        [string]$TranslationValidationStatus = "",
        [string]$EstimatedOpenAiTextCostUsd = "",
        [int]$FailedTranslatedSegmentCount = 0,
        [string]$GlossaryProfile = "",
        [string]$GlossaryPath = "",
        [string]$ProtectedTermsProfile = "",
        [string]$ProtectedTermsPath = "",
        [string]$OpenAiTranslationSummary = "",
        [double]$SourceDurationSeconds = 0,
        [string]$WhisperRequestedDevice = "",
        [string]$WhisperSelectedDevice = "",
        [int]$WhisperDeviceSwitchCount = 0,
        [string]$TranscriptSourceWav = "",
        [string]$TranscriptSourceMetadata = "",
        [string]$TranscriptSourceManifest = "",
        [string]$TranscriptAudioSelection = "",
        [int]$AudioTrackCount = 0,
        [string]$TranscriptAudioModeResolved = "",
        [string]$AllAudioTracksTranscript = "",
        [string]$AllAudioTracksIndex = "",
        [string]$AllAudioTracksManifest = "",
        [string]$PanelFrameIndex = "",
        [string]$PanelFrameManifest = "",
        [string]$PanelFramesSummary = ""
    )

    $resolvedTranscriptWordCount = [int]$TranscriptWordCount
    if ($resolvedTranscriptWordCount -le 0) {
        $resolvedTranscriptWordCount = Get-TranscriptWordCountFromArtifacts `
            -TranscriptTextPath $TranscriptText `
            -TranscriptJsonPath $TranscriptJson
    }

    $summaryRoot = Split-Path -Path $SummaryCsv -Parent
    foreach ($pathVariableName in @(
        "OutputPath", "ProxyVideo", "AudioFile", "TranscriptSrt", "TranscriptJson", "TranscriptText",
        "CommentsText", "CommentsJson", "TranslationTranscriptJson", "TranslationTranscriptSrt",
        "TranslationTranscriptText", "TranslationValidationReport", "GlossaryPath", "ProtectedTermsPath",
        "TranscriptSourceWav", "TranscriptSourceMetadata", "TranscriptSourceManifest",
        "AllAudioTracksTranscript", "AllAudioTracksIndex", "AllAudioTracksManifest",
        "PanelFrameIndex", "PanelFrameManifest"
    )) {
        $pathValue = [string](Get-Variable -Name $pathVariableName -ValueOnly)
        Set-Variable -Name $pathVariableName -Value (Get-PortablePackagePath -PackageRoot $summaryRoot -TargetPath $pathValue)
    }

    $row = [PSCustomObject]@{
        app_surface            = $script:AppName
        app_version            = (Get-AppVersion)
        source_video           = $SourceVideo
        output_folder_name     = $OutputFolderName
        output_path            = $OutputPath
        source_duration_seconds = [math]::Round([double]$SourceDurationSeconds, 3)
        frame_count            = $FrameCount
        frame_interval_seconds = $FrameIntervalSeconds
        frames_folder          = (Get-FramesFolderName -Value $FrameIntervalSeconds)
        proxy_video            = $ProxyVideo
        audio_file             = $AudioFile
        transcript_srt         = $TranscriptSrt
        transcript_json        = $TranscriptJson
        transcript_txt         = $TranscriptText
        raw_copied             = $RawCopied
        audio_present          = $AudioPresent
        detected_language      = $DetectedLanguage
        processing_mode        = $ProcessingModeSummary
        openai_project         = $OpenAiProjectSummary
        transcription_path     = $TranscriptionPath
        translation_targets    = $TranslationTargets
        translation_path       = $TranslationPath
        translation_provider   = $TranslationPath
        package_status         = $PackageStatus
        translation_status     = $TranslationStatus
        translation_notes      = $TranslationNotes
        next_steps             = $NextSteps
        translation_transcript_json = $TranslationTranscriptJson
        translation_transcript_srt  = $TranslationTranscriptSrt
        translation_transcript_txt  = $TranslationTranscriptText
        translation_validation_report = $TranslationValidationReport
        lane_id                = $LaneId
        privacy_class          = $PrivacyClass
        source_language        = $SourceLanguage
        target_language        = $TargetLanguage
        transcription_provider = $TranscriptionProvider
        transcription_model    = $TranscriptionModel
        translation_provider_name = $TranslationProviderName
        translation_model      = $TranslationModel
        transcript_word_count  = $resolvedTranscriptWordCount
        translated_word_count  = $TranslatedWordCount
        english_source_ratio   = $EnglishSourceRatio
        validation_warning_count = $ValidationWarningCount
        contamination_count    = $ContaminationCount
        encoding_artifact_count = $EncodingArtifactCount
        glossary_violation_count = $GlossaryViolationCount
        compression_warning_count = $CompressionWarningCount
        translation_validation_status = $TranslationValidationStatus
        estimated_openai_text_cost_usd = $EstimatedOpenAiTextCostUsd
        failed_translated_segment_count = $FailedTranslatedSegmentCount
        glossary_profile       = $GlossaryProfile
        glossary_path          = $GlossaryPath
        protected_terms_profile = $ProtectedTermsProfile
        protected_terms_path   = $ProtectedTermsPath
        openai_translation_summary = $OpenAiTranslationSummary
        whisper_requested_device = $WhisperRequestedDevice
        whisper_selected_device = $WhisperSelectedDevice
        whisper_device_switch_count = $WhisperDeviceSwitchCount
        transcript_source_wav = $TranscriptSourceWav
        transcript_source_metadata = $TranscriptSourceMetadata
        transcript_source_manifest = $TranscriptSourceManifest
        transcript_audio_selection = $TranscriptAudioSelection
        audio_track_count = $AudioTrackCount
        transcript_audio_mode_resolved = $TranscriptAudioModeResolved
        all_audio_tracks_transcript = $AllAudioTracksTranscript
        all_audio_tracks_index = $AllAudioTracksIndex
        all_audio_tracks_manifest = $AllAudioTracksManifest
        panel_frame_index = $PanelFrameIndex
        panel_frame_manifest = $PanelFrameManifest
        panel_frames_summary = $PanelFramesSummary
        comments_text          = $CommentsText
        comments_json          = $CommentsJson
        comments_summary       = $CommentsSummary
        remote_audio_track     = $RemoteAudioTrack
        proxy_mode             = $ProxyMode
        frame_mode             = $FrameMode
        whisper_mode           = $WhisperMode
    }

    if (-not (Test-Path $SummaryCsv)) {
        $row | Export-Csv -LiteralPath $SummaryCsv -NoTypeInformation -Encoding UTF8
    }
    else {
        $row | Export-Csv -LiteralPath $SummaryCsv -NoTypeInformation -Encoding UTF8 -Append
    }
}

function Invoke-PythonWhisperTranscriptProcess {
    param(
        [string]$PythonCommand,
        [string]$AudioPath,
        [string]$TranscriptFolder,
        [string]$ModelName,
        [string]$LanguageCode,
        [string]$FFmpegExe,
        [bool]$PreferGpu,
        [ValidateSet("transcribe","translate")]
        [string]$Task = "transcribe",
        [string]$JsonName = "transcript.json",
        [string]$SrtName = "transcript.srt",
        [string]$TextName = "transcript.txt",
        [string]$InitialPrompt = "",
        # 206: the operator's words to spell right, corrected in the transcript as written.
        [array]$GlossaryEntries = @(),
        [ValidateSet("Auto", "Sparse", "Continuous")]
        [string]$NarrationSpeechMode = "Auto",
        [int]$HeartbeatSeconds = 10,
        [int]$TimeoutSeconds = 0,
        [int]$StallTimeoutSeconds = 0,
        [double]$EstimatedTotalSeconds = 0,
        [string]$ProgressStateFilePath = "",
        [string]$StepName = "Python Whisper transcription",
        [psobject]$CpuFallbackRuntimePlan = $null
    )

    Ensure-Directory $TranscriptFolder

    $cliResult = Invoke-MediaManglersPythonCli `
        -PythonCommand $PythonCommand `
        -Command "whisper-transcribe" `
        -Payload @{
            audio_path                = $AudioPath
            output_dir                = $TranscriptFolder
            model_name                = $ModelName
            language_code             = $LanguageCode
            ffmpeg_dir                = $(Split-Path $FFmpegExe -Parent)
            prefer_gpu                = $PreferGpu
            task_name                 = $Task
            json_name                 = $JsonName
            srt_name                  = $SrtName
            text_name                 = $TextName
            initial_prompt            = $InitialPrompt
            glossary_entries          = @($GlossaryEntries)
            narration_speech_mode     = $NarrationSpeechMode
            progress_file             = $ProgressStateFilePath
            heartbeat_interval_seconds = [math]::Max(10, $HeartbeatSeconds)
        } `
        -StepName $StepName `
        -HeartbeatSeconds $HeartbeatSeconds `
        -TimeoutSeconds $TimeoutSeconds `
        -StallTimeoutSeconds $StallTimeoutSeconds `
        -EstimatedTotalSeconds $EstimatedTotalSeconds `
        -ProgressStateFilePath $ProgressStateFilePath `
        -CpuFallbackRuntimePlan $CpuFallbackRuntimePlan

    if ($cliResult) {
        if ($cliResult.ExitCode -eq 0 -and $cliResult.Result -and $cliResult.Result.ok) {
            $data = $cliResult.Result.data
            return [PSCustomObject]@{
                Device   = [string]$data.device
                Fp16     = [bool]$data.fp16
                JsonPath = [string]$data.json_path
                SrtPath  = [string]$data.srt_path
                TextPath = [string]$data.text_path
                Language = [string]$data.language
                GpuError = [string]$data.gpu_error
                RequestedDevice = [string]$data.requested_device
                SelectedDevice = [string]$data.selected_device
                DeviceSwitchCount = [int]$data.device_switch_count
                RawJsonPath = [string]$data.raw_json_path
                VadJsonPath = [string]$data.vad_json_path
                QualityJsonPath = [string]$data.quality_json_path
                QualityBlocking = [bool]$data.quality_blocking
                RecordingWpm = [double]$data.recording_wpm
                ActiveSpeechWpm = [double]$data.active_speech_wpm
            }
        }

        $cliError = if ($cliResult.Result -and -not [string]::IsNullOrWhiteSpace($cliResult.Result.error)) {
            [string]$cliResult.Result.error
        }
        else {
            "Tracked Python CLI helper failed before returning a result."
        }
        # 214: the shared helper is the only way Whisper runs. The legacy inline script that used
        # to stand in when it failed wrote transcripts without the invented-line filters.
        throw ("The Whisper helper failed: {0}" -f $cliError)
    }

    throw (Get-MediaManglersPythonCliUnavailableMessage -FeatureLabel "Whisper transcription")
}

function Invoke-LocalWhisperCalibration {
    param(
        [string]$PythonCommand,
        [string]$AudioPath,
        [string]$FFmpegExe,
        [string]$ModelName,
        [string]$LanguageCode,
        [bool]$PreferGpu,
        [string]$Task,
        [double]$SampleSeconds,
        [int]$HeartbeatSeconds = 10
    )

    if ($SampleSeconds -le 0) {
        return [PSCustomObject]@{
            Success = $false
            Reason  = "calibration sample duration was not usable"
        }
    }

    Write-Log ("Running a short Local Whisper calibration sample ({0}) to estimate this machine's speed..." -f (Format-DurationHuman -Seconds $SampleSeconds))

    $tempRoot = Get-MMScratchPath -Prefix "media_manglers_whisper_calibration"
    $sampleAudioPath = Join-Path $tempRoot "whisper_calibration_sample.mp3"
    $progressStateFilePath = Join-Path $tempRoot "whisper_calibration_progress.json"
    Ensure-Directory $tempRoot

    try {
        Invoke-ExternalCapture `
            -FilePath $FFmpegExe `
            -Arguments @(
                "-y",
                "-i", $AudioPath,
                "-t", ("{0:0.###}" -f $SampleSeconds),
                "-vn",
                "-acodec", "libmp3lame",
                "-b:a", "128k",
                $sampleAudioPath
            ) `
            -StepName "Create Whisper calibration sample" `
            -TimeoutSeconds 300 | Out-Null

        $samplePlan = Get-LocalWhisperAdaptiveRuntimePlan `
            -PythonCommand $PythonCommand `
            -SourceDurationSeconds $SampleSeconds `
            -ModelName $ModelName `
            -CanUseWhisperGpu $PreferGpu `
            -HeartbeatSeconds $HeartbeatSeconds `
            -WhisperTimeoutSeconds 0 `
            -Task $Task

        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        try {
            $null = Invoke-PythonWhisperTranscriptProcess `
                -PythonCommand $PythonCommand `
                -AudioPath $sampleAudioPath `
                -TranscriptFolder $tempRoot `
                -ModelName $ModelName `
                -LanguageCode $LanguageCode `
                -FFmpegExe $FFmpegExe `
                -PreferGpu $PreferGpu `
                -Task $Task `
                -JsonName "calibration.json" `
                -SrtName "calibration.srt" `
                -TextName "calibration.txt" `
                -HeartbeatSeconds $HeartbeatSeconds `
                -TimeoutSeconds $samplePlan.ResolvedTimeoutSeconds `
                -StallTimeoutSeconds $samplePlan.StallTimeoutSeconds `
                -EstimatedTotalSeconds $samplePlan.EstimatedRuntimeSeconds `
                -ProgressStateFilePath $progressStateFilePath `
                -StepName "Python Whisper calibration"
        }
        finally {
            $sw.Stop()
        }

        Write-Log ("Calibration sample finished in {0} for a {1} clip." -f (Format-DurationHuman -Seconds $sw.Elapsed.TotalSeconds), (Format-DurationHuman -Seconds $SampleSeconds))

        return [PSCustomObject]@{
            Success               = $true
            SampleDurationSeconds = [math]::Round($SampleSeconds, 3)
            ElapsedSeconds        = [math]::Round($sw.Elapsed.TotalSeconds, 3)
            Reason                = "sample calibration completed"
        }
    }
    catch {
        Write-Log ("Calibration sample failed. Falling back to the conservative heuristic estimate. {0}" -f $_.Exception.Message) "WARN"
        return [PSCustomObject]@{
            Success = $false
            Reason  = $_.Exception.Message
        }
    }
    finally {
        if (Test-Path -LiteralPath $tempRoot) {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Invoke-PythonWhisperTranscript {
    param(
        [string]$PythonCommand,
        [string]$AudioPath,
        [string]$TranscriptFolder,
        [string]$ModelName,
        [string]$LanguageCode,
        [string]$FFmpegExe,
        [bool]$PreferGpu,
        [ValidateSet("transcribe","translate")]
        [string]$Task = "transcribe",
        [string]$JsonName = "transcript.json",
        [string]$SrtName = "transcript.srt",
        [string]$TextName = "transcript.txt",
        [string]$InitialPrompt = "",
        # 206: the operator's words to spell right, corrected in the transcript as written.
        [array]$GlossaryEntries = @(),
        [ValidateSet("Auto", "Sparse", "Continuous")]
        [string]$NarrationSpeechMode = "Auto",
        [double]$SourceDurationSeconds = 0,
        [double]$EffectiveDurationSeconds = 0,
        [int]$AudioTrackCount = 0,
        [string]$TranscriptAudioModeResolved = "",
        [int]$HeartbeatSeconds = 10,
        [int]$WhisperTimeoutSeconds = 0,
        [bool]$InteractiveMode = $false,
        [bool]$AllowInteractiveLongRunPrompt = $true
    )

    Ensure-Directory $TranscriptFolder

    $resolvedModelName = $ModelName
    $heuristicPlan = $null

    while ($true) {
        $heuristicPlan = Get-LocalWhisperAdaptiveRuntimePlan `
            -PythonCommand $PythonCommand `
            -SourceDurationSeconds $SourceDurationSeconds `
            -ModelName $resolvedModelName `
            -CanUseWhisperGpu $PreferGpu `
            -HeartbeatSeconds $HeartbeatSeconds `
            -WhisperTimeoutSeconds $WhisperTimeoutSeconds `
            -Task $Task `
            -EffectiveDurationSeconds $EffectiveDurationSeconds `
            -AudioTrackCount $AudioTrackCount `
            -TranscriptAudioModeResolved $TranscriptAudioModeResolved

        if (-not $InteractiveMode -or -not $AllowInteractiveLongRunPrompt -or -not $heuristicPlan.LongRunPromptRecommended) {
            break
        }

        $decision = Get-InteractiveLocalWhisperLongRunDecision -ModelName $resolvedModelName -Plan $heuristicPlan
        if ($decision.Action -eq "cancel") {
            throw "Cancelled before starting the long Local Whisper run."
        }
        if ($decision.Action -eq "switch_model") {
            Write-Log ("Operator switched Local Whisper model from '{0}' to '{1}' for this run." -f $resolvedModelName, $decision.ModelName) "WARN"
            $resolvedModelName = $decision.ModelName
            continue
        }

        break
    }

    $calibrationData = $null
    $calibrationStatus = ""
    if ($WhisperTimeoutSeconds -gt 0) {
        $calibrationStatus = "skipped because explicit -WhisperTimeoutSeconds override was supplied"
    }
    elseif ($heuristicPlan.CalibrationRecommended) {
        $cacheKey = Get-LocalWhisperCalibrationCacheKey -AudioPath $AudioPath -ModelName $resolvedModelName -CanUseWhisperGpu $PreferGpu
        if ($script:WhisperCalibrationCache.ContainsKey($cacheKey)) {
            $calibrationData = $script:WhisperCalibrationCache[$cacheKey]
            $calibrationStatus = "reused cached short-sample calibration from this run"
        }
        else {
            $calibrationAttempt = Invoke-LocalWhisperCalibration `
                -PythonCommand $PythonCommand `
                -AudioPath $AudioPath `
                -FFmpegExe $FFmpegExe `
                -ModelName $resolvedModelName `
                -LanguageCode $LanguageCode `
                -PreferGpu $PreferGpu `
                -Task $Task `
                -SampleSeconds $heuristicPlan.CalibrationSampleSeconds `
                -HeartbeatSeconds $HeartbeatSeconds

            if ($calibrationAttempt.Success) {
                $calibrationData = $calibrationAttempt
                $script:WhisperCalibrationCache[$cacheKey] = $calibrationAttempt
            }
            else {
                $calibrationStatus = $calibrationAttempt.Reason
            }
        }
    }
    elseif (-not [string]::IsNullOrWhiteSpace($heuristicPlan.CalibrationRecommendationReason)) {
        $calibrationStatus = $heuristicPlan.CalibrationRecommendationReason
    }

    $runtimePlan = if ($calibrationData) {
        Get-LocalWhisperAdaptiveRuntimePlan `
            -PythonCommand $PythonCommand `
            -SourceDurationSeconds $SourceDurationSeconds `
            -ModelName $resolvedModelName `
            -CanUseWhisperGpu $PreferGpu `
            -HeartbeatSeconds $HeartbeatSeconds `
            -WhisperTimeoutSeconds $WhisperTimeoutSeconds `
            -Task $Task `
            -CalibrationData $calibrationData `
            -EffectiveDurationSeconds $EffectiveDurationSeconds `
            -AudioTrackCount $AudioTrackCount `
            -TranscriptAudioModeResolved $TranscriptAudioModeResolved
    }
    else {
        Get-LocalWhisperAdaptiveRuntimePlan `
            -PythonCommand $PythonCommand `
            -SourceDurationSeconds $SourceDurationSeconds `
            -ModelName $resolvedModelName `
            -CanUseWhisperGpu $PreferGpu `
            -HeartbeatSeconds $HeartbeatSeconds `
            -WhisperTimeoutSeconds $WhisperTimeoutSeconds `
            -Task $Task `
            -CalibrationStatus $calibrationStatus `
            -EffectiveDurationSeconds $EffectiveDurationSeconds `
            -AudioTrackCount $AudioTrackCount `
            -TranscriptAudioModeResolved $TranscriptAudioModeResolved
    }

    Write-LocalWhisperRuntimePlanLog -Task $Task -ModelName $resolvedModelName -Plan $runtimePlan

    $cpuFallbackRuntimePlan = $null
    if ($PreferGpu -and $runtimePlan.TimeoutSource -eq "adaptive_runtime_budget") {
        $cpuFallbackRuntimePlan = Get-LocalWhisperAdaptiveRuntimePlan `
            -PythonCommand $PythonCommand `
            -SourceDurationSeconds $SourceDurationSeconds `
            -ModelName $resolvedModelName `
            -CanUseWhisperGpu $false `
            -HeartbeatSeconds $HeartbeatSeconds `
            -WhisperTimeoutSeconds 0 `
            -Task $Task `
            -CalibrationStatus "GPU plan was used initially; CPU fallback now uses the conservative CPU heuristic." `
            -EffectiveDurationSeconds $EffectiveDurationSeconds `
            -AudioTrackCount $AudioTrackCount `
            -TranscriptAudioModeResolved $TranscriptAudioModeResolved
    }

    $progressStateFilePath = Get-MMScratchPath -Prefix "media_manglers_whisper_progress" -Extension ".json"
    $stepName = if ($Task -eq "translate") { "Python Whisper translation" } else { "Python Whisper transcription" }

    try {
        $result = Invoke-PythonWhisperTranscriptProcess `
            -PythonCommand $PythonCommand `
            -AudioPath $AudioPath `
            -TranscriptFolder $TranscriptFolder `
            -ModelName $resolvedModelName `
            -LanguageCode $LanguageCode `
            -FFmpegExe $FFmpegExe `
            -PreferGpu $PreferGpu `
            -Task $Task `
            -JsonName $JsonName `
            -SrtName $SrtName `
            -TextName $TextName `
            -InitialPrompt $InitialPrompt `
            -GlossaryEntries @($GlossaryEntries) `
            -NarrationSpeechMode $NarrationSpeechMode `
            -HeartbeatSeconds $HeartbeatSeconds `
            -TimeoutSeconds $runtimePlan.ResolvedTimeoutSeconds `
            -StallTimeoutSeconds $runtimePlan.StallTimeoutSeconds `
            -EstimatedTotalSeconds $runtimePlan.EstimatedRuntimeSeconds `
            -ProgressStateFilePath $progressStateFilePath `
            -StepName $stepName `
            -CpuFallbackRuntimePlan $cpuFallbackRuntimePlan

        $result | Add-Member -NotePropertyName ModelNameUsed -NotePropertyValue $resolvedModelName -Force
        $result | Add-Member -NotePropertyName RuntimePlan -NotePropertyValue $runtimePlan -Force
        return $result
    }
    finally {
        if (Test-Path -LiteralPath $progressStateFilePath) {
            Remove-Item -LiteralPath $progressStateFilePath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Invoke-OpenAiAudioTranscriptionRequest {
    param(
        [string]$AudioPath,
        [string]$LanguageCode,
        [string]$Model = ""
    )

    Add-Type -AssemblyName System.Net.Http
    $apiKey = Get-OpenAiApiKey -Required -ProviderLabel "OpenAI transcription"
    $endpoint = "https://api.openai.com/v1/audio/transcriptions"
    $resolvedModel = if ([string]::IsNullOrWhiteSpace($Model)) { $script:OpenAiTranscriptionModel } else { $Model.Trim() }
    $httpClient = New-Object System.Net.Http.HttpClient
    $httpClient.Timeout = [System.TimeSpan]::FromMinutes(20)
    $httpClient.DefaultRequestHeaders.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", $apiKey)

    $fileStream = [System.IO.File]::OpenRead($AudioPath)
    $form = New-Object System.Net.Http.MultipartFormDataContent

    try {
        $fileContent = New-Object System.Net.Http.StreamContent($fileStream)
        $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("audio/mpeg")
        $form.Add($fileContent, "file", [System.IO.Path]::GetFileName($AudioPath))
        $form.Add((New-Object System.Net.Http.StringContent($resolvedModel, [System.Text.Encoding]::UTF8)), "model")
        $form.Add((New-Object System.Net.Http.StringContent("verbose_json", [System.Text.Encoding]::UTF8)), "response_format")

        if (-not [string]::IsNullOrWhiteSpace($LanguageCode)) {
            $form.Add((New-Object System.Net.Http.StringContent($LanguageCode.Trim(), [System.Text.Encoding]::UTF8)), "language")
        }

        $response = $httpClient.PostAsync($endpoint, $form).GetAwaiter().GetResult()
        $responseText = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) {
            $requestId = ""
            try {
                $requestId = ($response.Headers.GetValues("x-request-id") | Select-Object -First 1)
            }
            catch {
            }

            $normalizedResponseBody = Normalize-OpenAiResponseText -Text $responseText
            if (-not [string]::IsNullOrWhiteSpace($normalizedResponseBody)) {
                Write-Log ("OpenAI raw response body for transcription: {0}" -f $normalizedResponseBody) "WARN"
            }

            $errorText = if ([string]::IsNullOrWhiteSpace($normalizedResponseBody)) {
                ("OpenAI transcription failed with HTTP {0} {1}." -f ([int]$response.StatusCode), [string]$response.ReasonPhrase)
            }
            else {
                ("OpenAI transcription failed with HTTP {0} {1}. {2}" -f ([int]$response.StatusCode), [string]$response.ReasonPhrase, $normalizedResponseBody)
            }

            if (-not [string]::IsNullOrWhiteSpace($requestId)) {
                $errorText = ("{0} request_id={1}" -f $errorText, $requestId)
            }

            throw $errorText
        }

        return ($responseText | ConvertFrom-Json)
    }
    finally {
        if ($form) {
            $form.Dispose()
        }
        if ($fileStream) {
            $fileStream.Dispose()
        }
        if ($httpClient) {
            $httpClient.Dispose()
        }
    }
}

function New-OpenAiTranscriptionChunkPlan {
    param(
        [string]$AudioPath,
        [string]$FFmpegExe,
        [string]$FFprobeExe,
        [int]$HeartbeatSeconds = 10
    )

    $maxUploadBytes = 24MB
    $audioItem = Get-Item -LiteralPath $AudioPath
    $durationSeconds = Get-VideoDurationSeconds -FFprobeExe $FFprobeExe -VideoPath $AudioPath
    if ($audioItem.Length -le $maxUploadBytes) {
        return [PSCustomObject]@{
            TempRoot = ""
            Chunks   = @(
                [PSCustomObject]@{
                    Path            = $AudioPath
                    StartSeconds    = 0.0
                    DurationSeconds = $durationSeconds
                }
            )
        }
    }

    if ($durationSeconds -le 0) {
        throw "Could not determine audio duration for OpenAI transcription chunking."
    }

    $bytesPerSecond = [double]$audioItem.Length / [Math]::Max($durationSeconds, 1.0)
    $dynamicChunkSeconds = [Math]::Floor(($maxUploadBytes * 0.9) / [Math]::Max($bytesPerSecond, 1.0))
    $chunkSeconds = [int][Math]::Min(600, [Math]::Max(60, $dynamicChunkSeconds))
    $tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("openai_transcription_chunks_" + [guid]::NewGuid().ToString())
    Ensure-Directory $tempRoot

    $chunks = New-Object System.Collections.Generic.List[object]
    $chunkIndex = 0
    for ($startSeconds = 0.0; $startSeconds -lt $durationSeconds; $startSeconds += $chunkSeconds) {
        $chunkIndex += 1
        $remainingSeconds = [Math]::Max(0.0, ($durationSeconds - $startSeconds))
        $currentDuration = [Math]::Min([double]$chunkSeconds, $remainingSeconds)
        $chunkPath = Join-Path $tempRoot ("chunk_{0:D3}.mp3" -f $chunkIndex)
        $startText = $startSeconds.ToString("0.###", [System.Globalization.CultureInfo]::InvariantCulture)
        $durationText = $currentDuration.ToString("0.###", [System.Globalization.CultureInfo]::InvariantCulture)

        $result = Invoke-ExternalCapture `
            -FilePath $FFmpegExe `
            -Arguments @("-y", "-ss", $startText, "-t", $durationText, "-i", $AudioPath, "-vn", "-c:a", "libmp3lame", "-b:a", "192k", $chunkPath) `
            -StepName ("OpenAI transcription chunk {0}" -f $chunkIndex) `
            -HeartbeatSeconds $HeartbeatSeconds

        if ($result.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $chunkPath)) {
            throw ("OpenAI transcription chunk {0} could not be created." -f $chunkIndex)
        }

        $chunkItem = Get-Item -LiteralPath $chunkPath
        if ($chunkItem.Length -gt $maxUploadBytes) {
            throw ("OpenAI transcription chunk {0} is still larger than the upload limit." -f $chunkIndex)
        }

        [void]$chunks.Add([PSCustomObject]@{
                Path            = $chunkPath
                StartSeconds    = $startSeconds
                DurationSeconds = $currentDuration
            })
    }

    return [PSCustomObject]@{
        TempRoot = $tempRoot
        Chunks   = $chunks.ToArray()
    }
}

function Invoke-OpenAiWhisperTranscript {
    param(
        [string]$AudioPath,
        [string]$TranscriptFolder,
        [string]$LanguageCode,
        [string]$Model = "",
        [string]$FFmpegExe,
        [string]$FFprobeExe,
        [string]$JsonName = "transcript.json",
        [string]$SrtName = "transcript.srt",
        [string]$TextName = "transcript.txt",
        [int]$HeartbeatSeconds = 10
    )

    Ensure-Directory $TranscriptFolder
    $resolvedModel = if ([string]::IsNullOrWhiteSpace($Model)) { $script:OpenAiTranscriptionModel } else { $Model.Trim() }
    $chunkPlan = New-OpenAiTranscriptionChunkPlan `
        -AudioPath $AudioPath `
        -FFmpegExe $FFmpegExe `
        -FFprobeExe $FFprobeExe `
        -HeartbeatSeconds $HeartbeatSeconds

    $segments = New-Object System.Collections.Generic.List[object]
    $detectedLanguage = ""
    $segmentId = 0

    try {
        foreach ($chunk in @($chunkPlan.Chunks)) {
            Write-Log ("OpenAI transcription request: {0} (offset {1:0.###}s)" -f (Split-Path -Path $chunk.Path -Leaf), [double]$chunk.StartSeconds)
            $payload = Invoke-OpenAiAudioTranscriptionRequest `
                -AudioPath $chunk.Path `
                -LanguageCode $LanguageCode `
                -Model $resolvedModel

            if ([string]::IsNullOrWhiteSpace($detectedLanguage) -and -not [string]::IsNullOrWhiteSpace([string]$payload.language)) {
                $detectedLanguage = [string]$payload.language
            }

            $payloadSegments = @($payload.segments)
            if ($payloadSegments.Count -eq 0 -and -not [string]::IsNullOrWhiteSpace([string]$payload.text)) {
                $payloadSegments = @(
                    [PSCustomObject]@{
                        start = 0.0
                        end   = [double]$chunk.DurationSeconds
                        text  = [string]$payload.text
                    }
                )
            }

            foreach ($segment in $payloadSegments) {
                $text = [string]$segment.text
                if ([string]::IsNullOrWhiteSpace($text)) {
                    continue
                }

                [void]$segments.Add([PSCustomObject]@{
                        id    = $segmentId
                        start = [double]$chunk.StartSeconds + [double]$segment.start
                        end   = [double]$chunk.StartSeconds + [double]$segment.end
                        text  = $text
                    })
                $segmentId += 1
            }
        }

        if ($segments.Count -eq 0) {
            throw "OpenAI transcription completed but returned no transcript segments."
        }

        $artifacts = Write-TranscriptArtifactsFromSegments `
            -OutputFolder $TranscriptFolder `
            -Segments $segments.ToArray() `
            -Language $(if ([string]::IsNullOrWhiteSpace($detectedLanguage)) { $LanguageCode } else { $detectedLanguage }) `
            -SourceLanguage $(if ([string]::IsNullOrWhiteSpace($detectedLanguage)) { $LanguageCode } else { $detectedLanguage }) `
            -Task "transcribe" `
            -JsonName $JsonName `
            -SrtName $SrtName `
            -TextName $TextName

        return [PSCustomObject]@{
            Device   = "openai"
            Fp16     = $false
            JsonPath = $artifacts.JsonPath
            SrtPath  = $artifacts.SrtPath
            TextPath = $artifacts.TextPath
            Language = $(if ([string]::IsNullOrWhiteSpace($detectedLanguage)) { [string]$LanguageCode } else { [string]$detectedLanguage })
            GpuError = ""
        }
    }
    finally {
        if ($chunkPlan -and -not [string]::IsNullOrWhiteSpace($chunkPlan.TempRoot) -and (Test-Path -LiteralPath $chunkPlan.TempRoot)) {
            Remove-Item -LiteralPath $chunkPlan.TempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Get-FpsFilterForInterval {
    param([double]$FrameIntervalSeconds)

    Test-FrameIntervalValue -Value $FrameIntervalSeconds
    $fps = 1.0 / $FrameIntervalSeconds
    return ("fps={0}" -f $fps.ToString("0.########", [System.Globalization.CultureInfo]::InvariantCulture))
}

function New-ProxyVideo {
    param(
        [string]$FFmpegExe,
        [string]$InputVideo,
        [string]$OutputVideo,
        [bool]$HasAudio,
        [bool]$UseGpu,
        [int]$HeartbeatSeconds = 10
    )

    if (Test-Path -LiteralPath $OutputVideo) {
        Write-Log "Proxy video already exists. Skipping."
        return "SKIPPED_EXISTING"
    }

    $gpuArgs = @("-y", "-hwaccel", "cuda", "-i", $InputVideo, "-map", "0:v:0")
    $cpuArgs = @("-y", "-i", $InputVideo, "-map", "0:v:0")

    if ($HasAudio) {
        $gpuArgs += @("-map", "0:a:0", "-vf", "scale=1280:-2", "-c:v", "h264_nvenc", "-preset", "p5", "-cq", "23", "-c:a", "aac", "-b:a", "192k", $OutputVideo)
        $cpuArgs += @("-map", "0:a:0", "-vf", "scale=1280:-2", "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-c:a", "aac", "-b:a", "192k", $OutputVideo)
    }
    else {
        $gpuArgs += @("-vf", "scale=1280:-2", "-c:v", "h264_nvenc", "-preset", "p5", "-cq", "23", "-an", $OutputVideo)
        $cpuArgs += @("-vf", "scale=1280:-2", "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-an", $OutputVideo)
    }

    if ($UseGpu) {
        Write-Log "Creating proxy video with NVIDIA NVENC..."

        $gpuResult = Invoke-ExternalCapture -FilePath $FFmpegExe -Arguments $gpuArgs -StepName "Proxy generation (GPU)" -HeartbeatSeconds $HeartbeatSeconds -IgnoreExitCode
        if ($gpuResult.ExitCode -eq 0 -and (Test-Path -LiteralPath $OutputVideo)) {
            return "GPU_NVENC"
        }

        Write-Log "GPU proxy generation failed. Falling back to CPU libx264." "WARN"
        if (Test-Path -LiteralPath $OutputVideo) {
            Remove-Item -LiteralPath $OutputVideo -Force -ErrorAction SilentlyContinue
        }
    }

    Write-Log "Creating proxy video with CPU libx264..."
    $cpuResult = Invoke-ExternalCapture -FilePath $FFmpegExe -Arguments $cpuArgs -StepName "Proxy generation (CPU)" -HeartbeatSeconds $HeartbeatSeconds
    if ($cpuResult.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $OutputVideo)) {
        throw "Proxy video generation failed."
    }

    return "CPU_LIBX264"
}

function Extract-FramesAtInterval {
    param(
        [string]$FFmpegExe,
        [string]$InputVideo,
        [string]$FramesFolder,
        [bool]$UseGpu,
        [double]$FrameIntervalSeconds,
        [int]$HeartbeatSeconds = 10,
        [string]$PythonCommand = ""
    )

    # 214: made by the one frame renderer, as every screenshot is: a GPU decode first when asked,
    # the CPU when that fails, and a folder that already has its screenshots is kept.
    Test-FrameIntervalValue -Value $FrameIntervalSeconds
    Write-Log ("Extracting frames every {0} seconds{1}..." -f $FrameIntervalSeconds, $(if ($UseGpu) { " with CUDA decode attempt" } else { " with CPU path" }))
    $render = Invoke-MMFrameCadence -FFmpegExe $FFmpegExe -InputVideo $InputVideo -FramesFolder $FramesFolder -UseGpu $UseGpu `
        -FrameIntervalSeconds $FrameIntervalSeconds -HeartbeatSeconds $HeartbeatSeconds -StepName "Frame extraction" -PythonCommand $PythonCommand
    if ([string]$render.method -eq "SKIPPED_EXISTING") {
        Write-Log "Frames already exist. Skipping frame extraction."
        return "SKIPPED_EXISTING"
    }
    foreach ($warning in @($render.warnings)) {
        if (-not [string]::IsNullOrWhiteSpace([string]$warning)) { Write-Log ([string]$warning) "WARN" }
    }
    if (-not [bool]$render.ok) {
        throw "Frame extraction failed."
    }
    return [string]$render.method
}

function Export-AudioMp3 {
    # 214: the package's MP3 is made by the shared decoder, as every audio file is: no time limit
    # while FFmpeg keeps moving, stopped with anything it started when it makes no progress, and
    # renamed into place only when it is whole.
    param(
        [string]$FFmpegExe,
        [string]$InputVideo,
        [string]$AudioFile,
        [int]$AudioStreamIndex = 0,
        [int]$HeartbeatSeconds = 10,
        # The Python that runs the shared decoder; the backend's own when not given.
        [string]$PythonCommand = "",
        # How long FFmpeg may make no progress before it is stopped (the shared rule's 180 s).
        [int]$StallTimeoutSeconds = 180
    )

    if (Test-Path -LiteralPath $AudioFile) {
        Write-Log "Audio file already exists. Skipping extraction."
        return "SKIPPED_EXISTING"
    }

    $null = Export-TranscriptSourceWav `
        -PythonCommand $PythonCommand `
        -FFmpegExe $FFmpegExe `
        -InputVideo $InputVideo `
        -OutputWav $AudioFile `
        -FfmpegMap ("0:a:{0}" -f [math]::Max(0, [int]$AudioStreamIndex)) `
        -AudioFormat "mp3" `
        -StepName "Audio extraction" `
        -HeartbeatSeconds $HeartbeatSeconds `
        -StallTimeoutSeconds $StallTimeoutSeconds
    return "CREATED"
}

function Get-SourceFileSignature {
    param([string]$Path)

    $item = Get-Item -LiteralPath $Path
    $signatureText = "{0}|{1}|{2}" -f $item.FullName, $item.Length, $item.LastWriteTimeUtc.ToString("o")
    $sha1 = [System.Security.Cryptography.SHA1]::Create()
    try {
        $hashBytes = $sha1.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($signatureText))
    }
    finally {
        $sha1.Dispose()
    }
    $hash = -join ($hashBytes | ForEach-Object { $_.ToString("x2") })
    return [PSCustomObject]@{
        path_hash_or_safe_id = $hash.Substring(0, 16)
        size_bytes         = [int64]$item.Length
        modified_utc       = $item.LastWriteTimeUtc.ToString("o")
        signature_basis    = "path|size|mtime_utc"
        signature_sha1     = $hash
    }
}

function Get-TranscriptExtractionSettings {
    param([string]$FfmpegMap)

    return [PSCustomObject]@{
        ffmpeg_map     = $FfmpegMap
        output_format  = "wav"
        codec          = "pcm_s16le"
        channels       = 1
        sample_rate_hz = 16000
    }
}

function Export-TranscriptSourceWav {
    # 214: the narration WAV (16 kHz mono 16-bit PCM) is made by the shared decoder,
    # media_manglers.core.voice_track.extract_wav, as for every other feature. It has no time limit
    # while FFmpeg keeps moving and stops FFmpeg when it makes no progress for StallTimeoutSeconds
    # (145). The backend still pauses and skips the helper (with its FFmpeg) like any other tool.
    param(
        [string]$FFmpegExe,
        [string]$InputVideo,
        [string]$OutputWav,
        [string]$FfmpegMap,
        # Full Review's all-tracks review mix: these audio tracks mixed into one, in place of FfmpegMap.
        [int[]]$MixOrdinals = @(),
        # The Python that runs the shared decoder; the backend's own when not given.
        [string]$PythonCommand = "",
        [int]$HeartbeatSeconds = 10,
        # How long FFmpeg may make no progress before it is stopped. 0 or less uses the shared decoder's 180.
        [int]$StallTimeoutSeconds = 180,
        [double]$DurationSeconds = 0,
        [string]$StepName = "Transcript source WAV extraction",
        # 214: "mp3" makes the package's listening copy (Export-AudioMp3) by the same decoder.
        [ValidateSet("wav", "mp3")]
        [string]$AudioFormat = "wav",
        [switch]$Force
    )

    if ((Test-Path -LiteralPath $OutputWav) -and -not $Force) {
        Write-Log "Transcript source WAV already exists. Skipping extraction."
        return "SKIPPED_EXISTING"
    }
    if ((Test-Path -LiteralPath $OutputWav) -and $Force) {
        Remove-Item -LiteralPath $OutputWav -Force -ErrorAction SilentlyContinue
    }

    Ensure-Directory (Split-Path -Path $OutputWav -Parent)
    $stallSeconds = if ($StallTimeoutSeconds -gt 0) { $StallTimeoutSeconds } else { 180 }
    # The decode is made here, next to the WAV, which takes its name only when FFmpeg has finished.
    $decodeFolder = Join-Path (Split-Path -Path $OutputWav -Parent) (".{0}-decode" -f [System.IO.Path]::GetFileNameWithoutExtension($OutputWav))
    $progressStatePath = Get-MMScratchPath -Prefix "media_manglers_audio_progress" -Extension ".json"
    try {
        $cli = Invoke-MediaManglersPythonCli `
            -PythonCommand $(if ([string]::IsNullOrWhiteSpace($PythonCommand)) { [string]$PythonExe } else { $PythonCommand }) `
            -Command "audio-extract" `
            -StepName $StepName `
            -HeartbeatSeconds $HeartbeatSeconds `
            -TimeoutSeconds 0 `
            -StallTimeoutSeconds ($stallSeconds + 60) `
            -ProgressStateFilePath $progressStatePath `
            -Payload @{
                ffmpeg_exe               = $FFmpegExe
                source_path              = $InputVideo
                output_path              = $OutputWav
                ffmpeg_map               = $FfmpegMap
                mix_ordinals             = @($MixOrdinals)
                work_dir                 = $decodeFolder
                stall_seconds            = $stallSeconds
                duration_seconds         = $DurationSeconds
                audio_format             = $AudioFormat
                progress_state_file_path = $progressStatePath
            }
        if ($null -eq $cli) {
            throw (Get-MediaManglersPythonCliUnavailableMessage -FeatureLabel $StepName)
        }
        if ($cli.ExitCode -ne 0 -or -not $cli.Result -or -not [bool]$cli.Result.ok -or -not (Test-Path -LiteralPath $OutputWav -PathType Leaf)) {
            $reason = if ($cli.Result -and -not [string]::IsNullOrWhiteSpace([string]$cli.Result.error)) { [string]$cli.Result.error } else { "the helper stopped before it said why" }
            throw ("{0} failed: {1}" -f $StepName, $reason)
        }
    }
    catch {
        # 196: stopped half way (no progress, a skip, a failure), nothing of the track may be
        # left beside the package: not the decode the helper could not clear up, not the WAV.
        Remove-MMScratchPath -Path $decodeFolder
        Remove-MMScratchPath -Path $OutputWav
        throw
    }
    finally {
        Remove-MMScratchPath -Path $progressStatePath
        Remove-MMScratchPath -Path ($progressStatePath + ".tmp")
    }

    return "CREATED"
}

function Test-MMTranscriptWavFormat {
    # 196: what a WAV file's header says, read from its RIFF chunks (other
    # chunks such as LIST are skipped). Returns $null when it is not a WAV
    # that can be read.
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    try {
        $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
        try {
            $reader = New-Object System.IO.BinaryReader($stream)
            if ($stream.Length -lt 12) { return $null }
            $riff = [System.Text.Encoding]::ASCII.GetString($reader.ReadBytes(4))
            [void]$reader.ReadUInt32()
            $wave = [System.Text.Encoding]::ASCII.GetString($reader.ReadBytes(4))
            if ($riff -ne "RIFF" -or $wave -ne "WAVE") { return $null }
            $format = $null
            $dataBytes = [int64]-1
            while ($stream.Position + 8 -le $stream.Length) {
                $chunkId = [System.Text.Encoding]::ASCII.GetString($reader.ReadBytes(4))
                $chunkSize = [int64]$reader.ReadUInt32()
                $next = $stream.Position + $chunkSize + ($chunkSize % 2)
                if ($chunkId -eq "fmt ") {
                    if ($chunkSize -lt 16) { return $null }
                    $formatTag = [int]$reader.ReadUInt16()
                    $channels = [int]$reader.ReadUInt16()
                    $sampleRate = [int64]$reader.ReadUInt32()
                    [void]$reader.ReadUInt32()
                    [void]$reader.ReadUInt16()
                    $bitsPerSample = [int]$reader.ReadUInt16()
                    $format = @{ FormatTag = $formatTag; Channels = $channels; SampleRate = $sampleRate; BitsPerSample = $bitsPerSample }
                }
                elseif ($chunkId -eq "data") {
                    # A file cut short holds less than its header says.
                    $dataBytes = [Math]::Min($chunkSize, $stream.Length - $stream.Position)
                    break
                }
                $stream.Position = $next
            }
            if ($null -eq $format -or $dataBytes -lt 0) { return $null }
            $bytesPerSecond = $format.SampleRate * $format.Channels * [Math]::Max(1, [int]($format.BitsPerSample / 8))
            return [PSCustomObject]@{
                SampleRate    = $format.SampleRate
                Channels      = $format.Channels
                BitsPerSample = $format.BitsPerSample
                FormatTag     = $format.FormatTag
                DataBytes     = $dataBytes
                Seconds       = if ($bytesPerSecond -gt 0) { [Math]::Round($dataBytes / $bytesPerSecond, 3) } else { 0.0 }
            }
        }
        finally {
            $stream.Dispose()
        }
    }
    catch {
        return $null
    }
}

function Export-MMNarrationWav {
    # 196: the narration WAV for Find my bug reports. Voice detection has
    # already decoded the chosen track to the same 16 kHz mono 16-bit PCM
    # the extraction makes, and kept it, so that file is used and the
    # recording is read once, not twice. When nothing sound was kept for this
    # track (a saved verdict, a Continue, a track the operator chose), the
    # track is extracted from the recording, stopped only when FFmpeg stops
    # moving (145).
    param(
        [string]$FFmpegExe,
        [string]$InputVideo,
        [string]$OutputWav,
        [int]$AudioOrdinal,
        $KeptWavs = @(),
        # The Python that runs the shared decoder; the backend's own when not given.
        [string]$PythonCommand = "",
        [int]$HeartbeatSeconds = 10
    )

    $kept = @(@($KeptWavs) | Where-Object { $null -ne $_ -and $null -ne $_.ordinal -and [int]$_.ordinal -eq $AudioOrdinal }) | Select-Object -First 1
    if ($null -ne $kept -and -not [string]::IsNullOrWhiteSpace([string]$kept.path)) {
        $keptPath = [string]$kept.path
        $format = Test-MMTranscriptWavFormat -Path $keptPath
        if ($null -ne $format -and $format.FormatTag -eq 1 -and $format.SampleRate -eq 16000 -and $format.Channels -eq 1 -and $format.BitsPerSample -eq 16 -and $format.DataBytes -gt 0) {
            try {
                Ensure-Directory (Split-Path -Path $OutputWav -Parent)
                Move-Item -LiteralPath $keptPath -Destination $OutputWav -Force -ErrorAction Stop
                Write-Log ("Transcript source WAV for Track {0}: reused the decoded audio from voice detection; the recording was not read again. {1}" -f ($AudioOrdinal + 1), $OutputWav)
                return "REUSED_VOICE_DETECTION"
            }
            catch {
                Write-Log ("The audio voice detection kept for Track {0} could not be moved ({1}); reading the track from the recording instead." -f ($AudioOrdinal + 1), $_.Exception.Message) "WARN"
                # A move between drives that stopped half way leaves part of a
                # file, which the extraction would otherwise keep as finished.
                Remove-MMScratchPath -Path $OutputWav
            }
        }
        else {
            Write-Log ("The audio voice detection kept for Track {0} is not usable; reading the track from the recording instead." -f ($AudioOrdinal + 1)) "WARN"
        }
        Remove-MMScratchPath -Path $keptPath
    }

    return (Export-TranscriptSourceWav `
        -FFmpegExe $FFmpegExe `
        -InputVideo $InputVideo `
        -OutputWav $OutputWav `
        -FfmpegMap ("0:a:{0}" -f $AudioOrdinal) `
        -PythonCommand $PythonCommand `
        -HeartbeatSeconds $HeartbeatSeconds `
        -StallTimeoutSeconds 180)
}

function Convert-TranscriptSourceWavToFlac {
    param(
        [string]$FFmpegExe,
        [string]$InputWav,
        [string]$OutputFlac,
        [int]$HeartbeatSeconds = 10
    )

    if (Test-Path -LiteralPath $OutputFlac -PathType Leaf) {
        return "SKIPPED_EXISTING"
    }
    if (-not (Test-Path -LiteralPath $InputWav -PathType Leaf)) {
        throw "Transcript source WAV was not found for lossless compaction."
    }

    Ensure-Directory (Split-Path -Path $OutputFlac -Parent)
    $temporaryFlac = $OutputFlac + ".partial.flac"
    Remove-Item -LiteralPath $temporaryFlac -Force -ErrorAction SilentlyContinue
    try {
        $result = Invoke-ExternalCapture `
            -FilePath $FFmpegExe `
            -Arguments @("-y", "-i", $InputWav, "-vn", "-c:a", "flac", "-compression_level", "8", $temporaryFlac) `
            -StepName "Transcript narration FLAC compaction" `
            -HeartbeatSeconds $HeartbeatSeconds
        if ($result.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $temporaryFlac -PathType Leaf)) {
            throw "Transcript narration FLAC compaction failed."
        }
        Move-Item -LiteralPath $temporaryFlac -Destination $OutputFlac -Force
        Remove-Item -LiteralPath $InputWav -Force
    }
    finally {
        Remove-Item -LiteralPath $temporaryFlac -Force -ErrorAction SilentlyContinue
    }
    return "CREATED"
}

function New-TranscriptSourceMetadata {
    param(
        [psobject]$Selection,
        [psobject]$SourceSignature,
        [string]$TranscriptSourcePath,
        [string]$ExtractionStatus,
        [string]$TranscriptStatus = "pending"
    )

    $stream = $Selection.SelectedStream
    $settings = Get-TranscriptExtractionSettings -FfmpegMap ([string]$stream.ffmpeg_map)
    return [ordered]@{
        generated_at = (Get-Date).ToString("o")
        selected_audio_stream = [ordered]@{
            vlc_track_label           = [string]$stream.vlc_track_label
            vlc_track_number          = [int]$stream.vlc_track_number
            audio_ordinal             = [string]$stream.audio_ordinal
            ffmpeg_map                = [string]$stream.ffmpeg_map
            absolute_stream_specifier = [string]$stream.absolute_stream_specifier
            absolute_stream_index     = [int]$stream.absolute_stream_index
            codec                     = [string]$stream.codec_name
            channels                  = [int]$stream.channels
            channel_layout            = [string]$stream.channel_layout
            sample_rate               = [string]$stream.sample_rate
            language                  = [string]$stream.language
            title                     = [string]$stream.title
            handler_name              = [string]$stream.handler_name
            default_disposition       = [int]$stream.default_disposition
        }
        selection_reason = [string]$Selection.Reason
        confidence       = [string]$Selection.Confidence
        warning          = [string]$Selection.Warning
        source_file_signature = $SourceSignature
        extraction_settings   = $settings
        extraction_command_summary = ("ffmpeg -i <source> -map {0} -vn -ac 1 -ar 16000 -c:a pcm_s16le transcript_source.wav" -f [string]$stream.ffmpeg_map)
        transcript_source_path = $(if ([string]::IsNullOrWhiteSpace($TranscriptSourcePath)) { "" } else { "audio/" + (Split-Path -Path $TranscriptSourcePath -Leaf) })
        extraction_status      = $ExtractionStatus
        transcript_status      = $TranscriptStatus
    }
}

function Write-TranscriptSourceMetadata {
    param(
        [string]$MetadataPath,
        [object]$Metadata
    )

    Ensure-Directory (Split-Path -Path $MetadataPath -Parent)
    ($Metadata | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $MetadataPath -Encoding UTF8
}

function Test-TranscriptSourceMetadataMatches {
    param(
        [string]$MetadataPath,
        [psobject]$Selection,
        [psobject]$SourceSignature
    )

    if (-not (Test-Path -LiteralPath $MetadataPath)) {
        return $false
    }

    try {
        $metadata = Get-Content -LiteralPath $MetadataPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        return $false
    }

    $stream = $Selection.SelectedStream
    $settings = Get-TranscriptExtractionSettings -FfmpegMap ([string]$stream.ffmpeg_map)
    if ([string]$metadata.selected_audio_stream.ffmpeg_map -ne [string]$stream.ffmpeg_map) {
        return $false
    }
    if ([int]$metadata.selected_audio_stream.absolute_stream_index -ne [int]$stream.absolute_stream_index) {
        return $false
    }
    if ([string]$metadata.source_file_signature.signature_sha1 -ne [string]$SourceSignature.signature_sha1) {
        return $false
    }
    if ([string]$metadata.extraction_settings.codec -ne [string]$settings.codec) {
        return $false
    }
    if ([int]$metadata.extraction_settings.channels -ne [int]$settings.channels) {
        return $false
    }
    if ([int]$metadata.extraction_settings.sample_rate_hz -ne [int]$settings.sample_rate_hz) {
        return $false
    }

    return $true
}

function Set-TranscriptSourceMetadataStatus {
    param(
        [string]$MetadataPath,
        [string]$TranscriptStatus
    )

    if (-not (Test-Path -LiteralPath $MetadataPath)) {
        return
    }
    try {
        $metadata = Get-Content -LiteralPath $MetadataPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($metadata.PSObject.Properties.Name -contains "transcript_status") {
            $metadata.transcript_status = $TranscriptStatus
        }
        else {
            $metadata | Add-Member -NotePropertyName "transcript_status" -NotePropertyValue $TranscriptStatus
        }
        $updatedAtUtc = (Get-Date).ToUniversalTime().ToString("o")
        if ($metadata.PSObject.Properties.Name -contains "updated_at_utc") {
            $metadata.updated_at_utc = $updatedAtUtc
        }
        else {
            $metadata | Add-Member -NotePropertyName "updated_at_utc" -NotePropertyValue $updatedAtUtc
        }
        ($metadata | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $MetadataPath -Encoding UTF8
    }
    catch {
        Write-Log ("Unable to update transcript source metadata status: {0}" -f $_.Exception.Message) "WARN"
    }
}

function Get-AudioTrackFileStem {
    param([psobject]$AudioStream)

    return ("track_{0:00}" -f [int]$AudioStream.vlc_track_number)
}

function Export-AllTracksReviewMixWav {
    param(
        [string]$FFmpegExe,
        [string]$InputVideo,
        [array]$AudioStreams,
        [string]$OutputWav,
        [string]$PythonCommand = "",
        [int]$HeartbeatSeconds = 10,
        [switch]$Force
    )

    $streams = @($AudioStreams)
    if ($streams.Count -eq 0) {
        return "SKIPPED_NO_AUDIO"
    }

    if ((Test-Path -LiteralPath $OutputWav) -and -not $Force) {
        Write-Log "All-tracks review mix WAV already exists. Skipping extraction."
        return "SKIPPED_EXISTING"
    }
    if ((Test-Path -LiteralPath $OutputWav) -and $Force) {
        Remove-Item -LiteralPath $OutputWav -Force -ErrorAction SilentlyContinue
    }

    Ensure-Directory (Split-Path -Path $OutputWav -Parent)
    if ($streams.Count -eq 1) {
        return (Export-TranscriptSourceWav `
                -FFmpegExe $FFmpegExe `
                -InputVideo $InputVideo `
                -OutputWav $OutputWav `
                -FfmpegMap ([string]$streams[0].ffmpeg_map) `
                -PythonCommand $PythonCommand `
                -HeartbeatSeconds $HeartbeatSeconds `
                -Force:$Force)
    }

    # 214: the mix is made by the same shared decoder, stopped only when FFmpeg stops moving.
    try {
        $null = Export-TranscriptSourceWav `
            -FFmpegExe $FFmpegExe `
            -InputVideo $InputVideo `
            -OutputWav $OutputWav `
            -MixOrdinals @($streams | ForEach-Object { [int]$_.ordinal }) `
            -PythonCommand $PythonCommand `
            -HeartbeatSeconds $HeartbeatSeconds `
            -StepName "All-tracks review mix WAV extraction" `
            -Force:$Force
    }
    catch {
        if (Test-MMSkipException $_) { throw }
        Write-Log ("All-tracks review mix WAV extraction failed; per-track transcripts will still be generated. {0}" -f $_.Exception.Message) "WARN"
        return "FAILED"
    }

    return "CREATED"
}

function New-TranscriptSourceManifestPayload {
    param(
        [string]$PackageRoot,
        [psobject]$Selection,
        [psobject]$SourceSignature,
        [array]$TrackItems,
        [string]$AllTracksReviewMixWav = "",
        [string]$AllTracksReviewMixStatus = "",
        [string]$TranscriptStatus = "pending",
        [array]$TranscriptItems = @(),
        [string]$AllTracksTranscriptPath = "",
        [string]$AllTracksIndexPath = "",
        [string]$AllTracksManifestPath = ""
    )

    $trackRows = @($TrackItems | ForEach-Object {
        $stream = $_.Stream
        [ordered]@{
            vlc_track_label           = [string]$stream.vlc_track_label
            vlc_track_number          = [int]$stream.vlc_track_number
            audio_ordinal             = [string]$stream.audio_ordinal
            ffmpeg_map                = [string]$stream.ffmpeg_map
            absolute_stream_specifier = [string]$stream.absolute_stream_specifier
            absolute_stream_index     = [int]$stream.absolute_stream_index
            codec                     = [string]$stream.codec_name
            channels                  = [int]$stream.channels
            channel_layout            = [string]$stream.channel_layout
            sample_rate               = [string]$stream.sample_rate
            language                  = [string]$stream.language
            title                     = [string]$stream.title
            handler_name              = [string]$stream.handler_name
            wav_path                  = $(if ([string]::IsNullOrWhiteSpace([string]$_.WavPath)) { "" } else { "audio/tracks/" + (Split-Path -Path ([string]$_.WavPath) -Leaf) })
            extraction_status         = [string]$_.ExtractionStatus
        }
    })

    return [ordered]@{
        generated_at = (Get-Date).ToString("o")
        transcript_audio_mode_requested = [string]$Selection.Mode
        transcript_audio_mode_resolved = [string]$Selection.ModeResolved
        audio_track_count = @($TrackItems).Count
        selection_reason = [string]$Selection.Reason
        source_file_signature = $SourceSignature
        tracks = @($trackRows)
        all_tracks_review_mix_wav = $(if ([string]::IsNullOrWhiteSpace($AllTracksReviewMixWav)) { "" } else { "audio/" + (Split-Path -Path $AllTracksReviewMixWav -Leaf) })
        all_tracks_review_mix_status = $AllTracksReviewMixStatus
        transcript_status = $TranscriptStatus
        per_track_transcripts = @(ConvertTo-PortableTrackTranscripts -PackageRoot $PackageRoot -TrackTranscripts @($TranscriptItems))
        all_audio_tracks_transcript = $(if ([string]::IsNullOrWhiteSpace($AllTracksTranscriptPath)) { "" } else { "transcript/" + (Split-Path -Path $AllTracksTranscriptPath -Leaf) })
        all_audio_tracks_index = $(if ([string]::IsNullOrWhiteSpace($AllTracksIndexPath)) { "" } else { "transcript/" + (Split-Path -Path $AllTracksIndexPath -Leaf) })
        all_audio_tracks_manifest = $(if ([string]::IsNullOrWhiteSpace($AllTracksManifestPath)) { "" } else { "transcript/" + (Split-Path -Path $AllTracksManifestPath -Leaf) })
    }
}

function Write-TranscriptSourceManifest {
    param(
        [string]$ManifestPath,
        [object]$Payload
    )

    Ensure-Directory (Split-Path -Path $ManifestPath -Parent)
    ($Payload | ConvertTo-Json -Depth 10) | Set-Content -LiteralPath $ManifestPath -Encoding UTF8
}

function Test-AllTracksTranscriptManifestMatches {
    param(
        [string]$ManifestPath,
        [array]$AudioStreams,
        [psobject]$SourceSignature
    )

    if (-not (Test-Path -LiteralPath $ManifestPath)) {
        return $false
    }

    try {
        $manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        return $false
    }

    if ([string]$manifest.transcript_audio_mode_resolved -ne "All") {
        return $false
    }
    if ([string]$manifest.source_file_signature.signature_sha1 -ne [string]$SourceSignature.signature_sha1) {
        return $false
    }
    $manifestTracks = @($manifest.tracks)
    $streams = @($AudioStreams)
    if ($manifestTracks.Count -ne $streams.Count) {
        return $false
    }
    foreach ($stream in $streams) {
        $match = @($manifestTracks | Where-Object {
                [string]$_.ffmpeg_map -eq [string]$stream.ffmpeg_map -and
                [int]$_.absolute_stream_index -eq [int]$stream.absolute_stream_index
            })
        if ($match.Count -eq 0) {
            return $false
        }
    }

    return $true
}

function New-TrackTranscriptMarkdown {
    param(
        [string]$OutputPath,
        [psobject]$TrackItem,
        [array]$Segments,
        [string]$SourceVideoName,
        [string]$TranscriptStatus,
        [string]$FailureReason = ""
    )

    $stream = $TrackItem.Stream
    $lines = New-Object System.Collections.Generic.List[string]
    [void]$lines.Add(("# {0} - ffmpeg {1} - absolute {2}" -f [string]$stream.vlc_track_label, [string]$stream.ffmpeg_map, [string]$stream.absolute_stream_specifier))
    [void]$lines.Add("")
    [void]$lines.Add(("- Source video: {0}" -f $SourceVideoName))
    [void]$lines.Add(("- Codec/channels/sample rate: {0}; {1}; {2}" -f [string]$stream.codec_name, [string]$stream.channels, [string]$stream.sample_rate))
    [void]$lines.Add(("- Extraction status: {0}" -f [string]$TrackItem.ExtractionStatus))
    [void]$lines.Add(("- Transcript status: {0}" -f $TranscriptStatus))
    if (-not [string]::IsNullOrWhiteSpace($FailureReason)) {
        [void]$lines.Add(("- Failure reason: {0}" -f $FailureReason))
    }
    [void]$lines.Add("")
    foreach ($segment in @($Segments)) {
        $startText = Convert-ToSrtTimestamp -Seconds ([double]$segment.start)
        [void]$lines.Add(("- {0} {1}" -f $startText, ([string]$segment.text).Trim()))
    }

    $lines | Set-Content -LiteralPath $OutputPath -Encoding UTF8
}

function Write-AllAudioTracksTranscriptSummary {
    param(
        [string]$TranscriptPath,
        [string]$IndexPath,
        [string]$ManifestPath,
        [string]$SourceVideoName,
        [array]$TranscriptItems,
        [string]$ResolvedMode,
        [string]$AllTracksReviewMixWav,
        [string]$AllTracksReviewMixStatus,
        [string]$TranscriptStatus = "generated"
    )

    Ensure-Directory (Split-Path -Path $TranscriptPath -Parent)

    $summaryLines = New-Object System.Collections.Generic.List[string]
    [void]$summaryLines.Add("# All Audio Tracks Transcript")
    [void]$summaryLines.Add("")
    [void]$summaryLines.Add(("- Source video: {0}" -f $SourceVideoName))
    [void]$summaryLines.Add(("- Transcript mode: {0}" -f $ResolvedMode))
    [void]$summaryLines.Add(("- Audio tracks transcribed: {0}" -f @($TranscriptItems).Count))
    [void]$summaryLines.Add(("- Track transcript statuses: generated {0}; failed {1}" -f @($TranscriptItems | Where-Object { [string]$_.TranscriptStatus -eq "generated" }).Count, @($TranscriptItems | Where-Object { [string]$_.TranscriptStatus -ne "generated" }).Count))
    [void]$summaryLines.Add("")

    $indexRows = New-Object System.Collections.Generic.List[object]
    foreach ($item in @($TranscriptItems)) {
        $stream = $item.Stream
        [void]$summaryLines.Add(("# {0} - ffmpeg {1} - absolute {2}" -f [string]$stream.vlc_track_label, [string]$stream.ffmpeg_map, [string]$stream.absolute_stream_specifier))
        [void]$summaryLines.Add("")
        [void]$summaryLines.Add(("- Codec/channels/sample rate: {0}; {1}; {2}" -f [string]$stream.codec_name, [string]$stream.channels, [string]$stream.sample_rate))
        [void]$summaryLines.Add(("- Extraction status: {0}" -f [string]$item.ExtractionStatus))
        [void]$summaryLines.Add(("- Transcript status: {0}" -f [string]$item.TranscriptStatus))
        if (-not [string]::IsNullOrWhiteSpace([string]$item.FailureReason)) {
            [void]$summaryLines.Add(("- Failure reason: {0}" -f [string]$item.FailureReason))
        }
        [void]$summaryLines.Add(("- Transcript text: {0}" -f [string]$item.TextPath))
        [void]$summaryLines.Add("")
        $trackTextPath = [string]$item.TextPath
        $trackText = if (-not [string]::IsNullOrWhiteSpace($trackTextPath) -and (Test-Path -LiteralPath $trackTextPath)) {
            (Get-Content -LiteralPath $trackTextPath -Raw -Encoding UTF8).Trim()
        }
        else {
            ""
        }
        if ([string]::IsNullOrWhiteSpace($trackText)) {
            [void]$summaryLines.Add("_No transcript text was produced for this track._")
        }
        else {
            [void]$summaryLines.Add($trackText)
        }
        [void]$summaryLines.Add("")

        [void]$indexRows.Add([PSCustomObject]@{
                vlc_track_label           = [string]$stream.vlc_track_label
                vlc_track_number          = [int]$stream.vlc_track_number
                ffmpeg_map                = [string]$stream.ffmpeg_map
                absolute_stream_specifier = [string]$stream.absolute_stream_specifier
                codec                     = [string]$stream.codec_name
                channels                  = [int]$stream.channels
                sample_rate               = [string]$stream.sample_rate
                extraction_status         = [string]$item.ExtractionStatus
                transcript_status         = [string]$item.TranscriptStatus
                failure_reason            = [string]$item.FailureReason
                wav_path                  = [string]$item.WavPath
                json_path                 = [string]$item.JsonPath
                srt_path                  = [string]$item.SrtPath
                text_path                 = [string]$item.TextPath
                markdown_path             = [string]$item.MarkdownPath
            })
    }

    $summaryLines | Set-Content -LiteralPath $TranscriptPath -Encoding UTF8
    if ($indexRows.Count -gt 0) {
        $indexRows | Export-Csv -LiteralPath $IndexPath -NoTypeInformation -Encoding UTF8
    }

    $payload = [ordered]@{
        generated_at = (Get-Date).ToString("o")
        source_video = $SourceVideoName
        transcript_audio_mode_resolved = $ResolvedMode
        transcript_status = $TranscriptStatus
        audio_track_count = @($TranscriptItems).Count
        generated_track_count = @($TranscriptItems | Where-Object { [string]$_.TranscriptStatus -eq "generated" }).Count
        failed_track_count = @($TranscriptItems | Where-Object { [string]$_.TranscriptStatus -ne "generated" }).Count
        all_tracks_review_mix_wav = $AllTracksReviewMixWav
        all_tracks_review_mix_status = $AllTracksReviewMixStatus
        all_audio_tracks_transcript = $TranscriptPath
        all_audio_tracks_index = $IndexPath
        tracks = @($TranscriptItems | ForEach-Object {
                [ordered]@{
                    vlc_track_label = [string]$_.Stream.vlc_track_label
                    ffmpeg_map = [string]$_.Stream.ffmpeg_map
                    absolute_stream_specifier = [string]$_.Stream.absolute_stream_specifier
                    wav_path = [string]$_.WavPath
                    transcript_status = [string]$_.TranscriptStatus
                    failure_reason = [string]$_.FailureReason
                    json_path = [string]$_.JsonPath
                    srt_path = [string]$_.SrtPath
                    text_path = [string]$_.TextPath
                    markdown_path = [string]$_.MarkdownPath
                }
            })
    }
    ($payload | ConvertTo-Json -Depth 10) | Set-Content -LiteralPath $ManifestPath -Encoding UTF8
}

function Get-BenchmarkProxySeconds {
    param(
        [string]$FFmpegExe,
        [string]$FFprobeExe,
        [string]$VideoPath,
        [bool]$HasAudio,
        [bool]$UseGpu
    )

    $tempOut = Join-Path ([System.IO.Path]::GetTempPath()) ("proxy_bench_" + [guid]::NewGuid().ToString() + ".mp4")
    $sampleSeconds = Get-BenchmarkSampleDurationSeconds -FFprobeExe $FFprobeExe -VideoPath $VideoPath -MaximumSampleSeconds 20.0

    try {
        if ($sampleSeconds -le 0) {
            return $null
        }

        $sampleText = $sampleSeconds.ToString([System.Globalization.CultureInfo]::InvariantCulture)

        if ($UseGpu) {
            $gpuArgs = @("-y", "-hwaccel", "cuda", "-ss", "0", "-t", $sampleText, "-i", $VideoPath, "-map", "0:v:0")
            if ($HasAudio) {
                $gpuArgs += @("-map", "0:a:0", "-vf", "scale=1280:-2", "-c:v", "h264_nvenc", "-preset", "p5", "-cq", "23", "-c:a", "aac", "-b:a", "192k", $tempOut)
            }
            else {
                $gpuArgs += @("-vf", "scale=1280:-2", "-c:v", "h264_nvenc", "-preset", "p5", "-cq", "23", "-an", $tempOut)
            }

            $gpuResult = Invoke-ExternalCapture -FilePath $FFmpegExe -Arguments $gpuArgs -StepName "Benchmark proxy generation (GPU)" -IgnoreExitCode
            if ($gpuResult.ExitCode -eq 0) {
                return [PSCustomObject]@{Elapsed=$gpuResult.DurationSeconds; Sample=$sampleSeconds}
            }
        }

        $cpuArgs = @("-y", "-ss", "0", "-t", $sampleText, "-i", $VideoPath, "-map", "0:v:0")
        if ($HasAudio) {
            $cpuArgs += @("-map", "0:a:0", "-vf", "scale=1280:-2", "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-c:a", "aac", "-b:a", "192k", $tempOut)
        }
        else {
            $cpuArgs += @("-vf", "scale=1280:-2", "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-an", $tempOut)
        }

        $cpuResult = Invoke-ExternalCapture -FilePath $FFmpegExe -Arguments $cpuArgs -StepName "Benchmark proxy generation (CPU)"
        return [PSCustomObject]@{Elapsed=$cpuResult.DurationSeconds; Sample=$sampleSeconds}
    }
    finally {
        if (Test-Path $tempOut) { Remove-Item $tempOut -Force -ErrorAction SilentlyContinue }
    }
}

function Get-BenchmarkFramesSeconds {
    param(
        [string]$FFmpegExe,
        [string]$FFprobeExe,
        [string]$VideoPath,
        [bool]$UseGpu,
        [double]$FrameIntervalSeconds
    )

    $tempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("frames_bench_" + [guid]::NewGuid().ToString())
    Ensure-Directory $tempDir
    $sampleSeconds = Get-BenchmarkSampleDurationSeconds -FFprobeExe $FFprobeExe -VideoPath $VideoPath -MaximumSampleSeconds 30.0
    $fpsFilter = Get-FpsFilterForInterval -FrameIntervalSeconds $FrameIntervalSeconds
    $vf = "$fpsFilter,scale=1280:-2"
    $outputPattern = Join-Path $tempDir "frame_%06d.jpg"

    try {
        if ($sampleSeconds -le 0) {
            return $null
        }

        $sampleText = $sampleSeconds.ToString([System.Globalization.CultureInfo]::InvariantCulture)
        if ($UseGpu) {
            $gpuResult = Invoke-ExternalCapture `
                -FilePath $FFmpegExe `
                -Arguments @("-y", "-hwaccel", "cuda", "-ss", "0", "-t", $sampleText, "-i", $VideoPath, "-map", "0:v:0", "-vf", $vf, "-q:v", "3", $outputPattern) `
                -StepName "Benchmark frame extraction (GPU)" `
                -IgnoreExitCode

            if ($gpuResult.ExitCode -eq 0 -and @(Get-ChildItem $tempDir -Filter "frame_*.jpg" -ErrorAction SilentlyContinue).Count -gt 0) {
                return [PSCustomObject]@{Elapsed=$gpuResult.DurationSeconds; Sample=$sampleSeconds}
            }

            Get-ChildItem $tempDir -Filter "frame_*.jpg" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
        }

        $cpuResult = Invoke-ExternalCapture `
            -FilePath $FFmpegExe `
            -Arguments @("-y", "-ss", "0", "-t", $sampleText, "-i", $VideoPath, "-map", "0:v:0", "-vf", $vf, "-q:v", "3", $outputPattern) `
            -StepName "Benchmark frame extraction (CPU)"

        return [PSCustomObject]@{Elapsed=$cpuResult.DurationSeconds; Sample=$sampleSeconds}
    }
    finally {
        if (Test-Path $tempDir) { Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue }
    }
}

function Get-BenchmarkAudioSeconds {
    param(
        [string]$FFmpegExe,
        [string]$FFprobeExe,
        [string]$VideoPath
    )

    $tempOut = Join-Path ([System.IO.Path]::GetTempPath()) ("audio_bench_" + [guid]::NewGuid().ToString() + ".mp3")
    $sampleSeconds = Get-BenchmarkSampleDurationSeconds -FFprobeExe $FFprobeExe -VideoPath $VideoPath -MaximumSampleSeconds 45.0

    try {
        if ($sampleSeconds -le 0) {
            return $null
        }

        $sampleText = $sampleSeconds.ToString([System.Globalization.CultureInfo]::InvariantCulture)
        $result = Invoke-ExternalCapture `
            -FilePath $FFmpegExe `
            -Arguments @("-y", "-ss", "0", "-t", $sampleText, "-i", $VideoPath, "-map", "0:a:0", "-vn", "-c:a", "libmp3lame", "-b:a", "192k", $tempOut) `
            -StepName "Benchmark audio extraction"

        return [PSCustomObject]@{Elapsed=$result.DurationSeconds; Sample=$sampleSeconds}
    }
    finally {
        if (Test-Path $tempOut) { Remove-Item $tempOut -Force -ErrorAction SilentlyContinue }
    }
}

function Get-BenchmarkSampleDurationSeconds {
    param(
        [string]$FFprobeExe,
        [string]$VideoPath,
        [double]$MaximumSampleSeconds
    )

    $duration = Get-VideoDurationSeconds -FFprobeExe $FFprobeExe -VideoPath $VideoPath
    if ($duration -le 0) {
        return 0.0
    }

    return [math]::Min($duration, $MaximumSampleSeconds)
}

function Get-BestEffortEstimate {
    param(
        [array]$Videos,
        [string]$FFmpegExe,
        [string]$FFprobeExe,
        [string]$PythonCommand,
        [string]$ModelName,
        [string]$LanguageCode,
        [bool]$CanUseFfmpegGpu,
        [bool]$CanUseWhisperGpu,
        [double]$FrameIntervalSeconds,
        [string]$TranscriptAudioMode = "Auto"
    )

    try {
        $totalDuration = 0.0
        $effectiveTranscriptionDuration = 0.0
        $audioTrackCount = 0
        $videosWithAudio = 0
        $firstAudioVideo = $null
        $normalizedTranscriptAudioMode = if ([string]::IsNullOrWhiteSpace($TranscriptAudioMode)) { "Auto" } else { (Get-Culture).TextInfo.ToTitleCase($TranscriptAudioMode.Trim().ToLowerInvariant()) }
        $estimateAllTracks = ($normalizedTranscriptAudioMode -eq "Auto" -or $normalizedTranscriptAudioMode -eq "All")
        $warnings = New-Object System.Collections.Generic.List[string]
        foreach ($video in $Videos) {
            $videoDuration = Get-VideoDurationSeconds -FFprobeExe $FFprobeExe -VideoPath $video.FullName
            $totalDuration += $videoDuration
            try {
                $streams = @(Get-VideoAudioStreams -FFprobeExe $FFprobeExe -VideoPath $video.FullName)
                if ($streams.Count -gt 0) {
                    $videosWithAudio += 1
                    $audioTrackCount += $streams.Count
                    if ($null -eq $firstAudioVideo) {
                        $firstAudioVideo = $video
                    }

                    if ($estimateAllTracks) {
                        $effectiveTranscriptionDuration += ($videoDuration * [math]::Max(1, $streams.Count))
                    }
                    else {
                        $effectiveTranscriptionDuration += $videoDuration
                    }
                }
            }
            catch {
                $warnings.Add(("Audio-track count estimate unavailable for '{0}': {1}" -f $video.Name, $_.Exception.Message))
            }
        }

        if ($Videos.Count -eq 0 -or $totalDuration -le 0) {
            return $null
        }

        $sampleVideo = $Videos[0]
        $hasAudio = Test-VideoHasAudio -FFprobeExe $FFprobeExe -VideoPath $sampleVideo.FullName
        $hasAnyAudio = ($videosWithAudio -gt 0 -or $hasAudio)
        $audioBenchmarkVideo = if ($firstAudioVideo) { $firstAudioVideo } else { $sampleVideo }
        $resolvedTranscriptAudioModeForEstimate = if ($hasAnyAudio) {
            if ($estimateAllTracks) { "All" } else { $normalizedTranscriptAudioMode }
        }
        else {
            "None"
        }

        Write-Phase -Name "Estimate" -Detail "Running best-effort runtime estimate. Failures here will not stop processing."

        $proxyBench = $null
        $framesBench = $null
        $audioBench = $null

        try {
            $proxyBench = Get-BenchmarkProxySeconds -FFmpegExe $FFmpegExe -FFprobeExe $FFprobeExe -VideoPath $sampleVideo.FullName -HasAudio $hasAudio -UseGpu $CanUseFfmpegGpu
        }
        catch {
            $warnings.Add("Proxy estimate unavailable: $($_.Exception.Message)")
        }

        try {
            $framesBench = Get-BenchmarkFramesSeconds -FFmpegExe $FFmpegExe -FFprobeExe $FFprobeExe -VideoPath $sampleVideo.FullName -UseGpu $CanUseFfmpegGpu -FrameIntervalSeconds $FrameIntervalSeconds
        }
        catch {
            $warnings.Add("Frame estimate unavailable: $($_.Exception.Message)")
        }

        if ($hasAnyAudio) {
            try {
                $audioBench = Get-BenchmarkAudioSeconds -FFmpegExe $FFmpegExe -FFprobeExe $FFprobeExe -VideoPath $audioBenchmarkVideo.FullName
            }
            catch {
                $warnings.Add("Audio estimate unavailable: $($_.Exception.Message)")
            }
        }

        $proxyEstimate = 0.0
        $framesEstimate = 0.0
        $audioEstimate = 0.0
        $whisperEstimate = 0.0

        if ($proxyBench) {
            $proxyEstimate = ($proxyBench.Elapsed / $proxyBench.Sample) * $totalDuration
        }

        if ($framesBench) {
            $frameLoadFactor = 0.5 / $FrameIntervalSeconds
            $framesEstimate = (($framesBench.Elapsed / $framesBench.Sample) * $totalDuration) * $frameLoadFactor
        }

        if ($audioBench) {
            $audioEstimate = ($audioBench.Elapsed / $audioBench.Sample) * $totalDuration
        }

        if ($hasAnyAudio) {
            $whisperFactor = if ($CanUseWhisperGpu) { 0.45 } else { 1.25 }
            $durationForTranscriptionEstimate = if ($effectiveTranscriptionDuration -gt 0) { $effectiveTranscriptionDuration } else { $totalDuration }
            $whisperEstimate = $durationForTranscriptionEstimate * $whisperFactor
            $warnings.Add(("Whisper estimate uses a {0} heuristic rather than a transcription benchmark so estimation can never kill the real run." -f $(if ($CanUseWhisperGpu) { "GPU" } else { "CPU" })))
            if ($estimateAllTracks -and $audioTrackCount -gt $videosWithAudio) {
                $warnings.Add(("Transcript estimate uses all-track mode: {0} audio tracks across {1} video(s), effective transcription duration {2}." -f $audioTrackCount, $videosWithAudio, (Format-DurationHuman $durationForTranscriptionEstimate)))
            }
        }

        $indexEstimate = (($totalDuration / [math]::Max($FrameIntervalSeconds, 0.1)) * 0.0025)
        $totalEstimate = $proxyEstimate + $framesEstimate + $audioEstimate + $whisperEstimate + $indexEstimate

        return [PSCustomObject]@{
            TotalDurationSeconds   = $totalDuration
            ProxyEstimateSeconds   = $proxyEstimate
            FramesEstimateSeconds  = $framesEstimate
            AudioEstimateSeconds   = $audioEstimate
            WhisperEstimateSeconds = $whisperEstimate
            IndexEstimateSeconds   = $indexEstimate
            TotalEstimateSeconds   = $totalEstimate
            AudioTrackCount         = $audioTrackCount
            VideosWithAudio         = $videosWithAudio
            TranscriptAudioModeResolved = $resolvedTranscriptAudioModeForEstimate
            EffectiveTranscriptionDurationSeconds = $effectiveTranscriptionDuration
            Warnings               = @($warnings)
        }
    }
    catch {
        Write-Log "Runtime estimation failed. Continuing with processing. $($_.Exception.Message)" "WARN"
        return $null
    }
}

function Build-FrameIndex {
    param(
        [string]$FramesFolder,
        [string]$FrameIndexCsv,
        [double]$FrameIntervalSeconds,
        [string]$FramesFolderName,
        [int]$HeartbeatSeconds = 10
    )

    Write-Log "Building frame index..."
    "frame_number,seconds,timestamp,filename,relative_path" | Set-Content -LiteralPath $FrameIndexCsv -Encoding UTF8

    $frames = @(Get-ChildItem -LiteralPath $FramesFolder -Filter "frame_*.jpg" | Sort-Object Name)
    $nextHeartbeat = if ($HeartbeatSeconds -gt 0) { (Get-Date).AddSeconds($HeartbeatSeconds) } else { $null }

    for ($i = 0; $i -lt $frames.Count; $i++) {
        $frame = $frames[$i]
        if ($frame.BaseName -match '^frame_(\d+)$') {
            $frameNumber = [int]$matches[1]
            $seconds = [math]::Round(($frameNumber - 1) * $FrameIntervalSeconds, 3)
            $timestamp = [TimeSpan]::FromSeconds($seconds).ToString("hh\:mm\:ss\.fff")
            $relativePath = "$FramesFolderName/$($frame.Name)"
            "$frameNumber,$seconds,$timestamp,$($frame.Name),$relativePath" | Add-Content -LiteralPath $FrameIndexCsv
        }

        $processed = $i + 1
        $now = Get-Date
        if (($nextHeartbeat -and $now -ge $nextHeartbeat) -or ($processed % 250 -eq 0 -and $processed -lt $frames.Count)) {
            Write-Log ("Frame indexing still working... {0}/{1} frames indexed" -f $processed, $frames.Count)
            if ($HeartbeatSeconds -gt 0) {
                $nextHeartbeat = $now.AddSeconds($HeartbeatSeconds)
            }
        }
    }

    return $frames.Count
}

function Process-Video {
    param(
        [string]$VideoPath,
        [string]$BaseOutputFolder,
        [string]$FFmpegExe,
        [string]$FFprobeExe,
        [string]$PythonCommand,
        [string]$ModelName,
        [string]$LanguageCode,
        [string[]]$TranslationTargets,
        [string]$SourceInfoJsonPath,
        [psobject]$RemoteAudioTrackInfo,
        [bool]$DoCopyRaw,
        [bool]$CommentsRequested,
        [string]$SummaryCsv,
        [bool]$CanUseFfmpegGpu,
        [bool]$CanUseWhisperGpu,
        [bool]$InteractiveMode,
        [string]$RequestedProcessingMode,
        [string]$ProcessingModeSelectionSource,
        [string]$ProcessingModeResolutionNote,
        [string]$ProcessingMode,
        [string]$OpenAiProject,
        [string]$RequestedTranslationProvider,
        [string]$TranslationProviderSelectionSource,
        [string]$TranslationProviderResolutionNote,
        [string]$TranslationProvider,
        [string]$OpenAiModel,
        [string]$OpenAiTranscriptionModel,
        [psobject]$ProtectedTermsProfileSelection = $null,
        [double]$FrameIntervalSeconds,
        [string]$FullReviewPanelCropMode = "Auto",
        [double]$FullReviewPanelCropCadenceSeconds = 5,
        [string]$TranscriptAudioMode = "Auto",
        [string]$TranscriptAudioStream = "",
        [int]$TranscriptAudioTrackOrdinal = 0,
        [int]$PreferredTranscriptAudioTrackOrdinal = 0,
        [bool]$AudioTrackAudit = $false,
        [int]$WhisperTimeoutSeconds = 0,
        [int]$HeartbeatSeconds = 10
    )

    if (-not (Test-Path -LiteralPath $VideoPath)) {
        throw "Input video not found: $VideoPath"
    }

    $videoItem = Get-Item -LiteralPath $VideoPath
    $baseName = [System.IO.Path]::GetFileNameWithoutExtension($videoItem.Name)
    $safeBaseName = Get-SafeFolderName $baseName

    $framesFolderName = Get-FramesFolderName -Value $FrameIntervalSeconds
    $videoOutputRoot = Join-Path $BaseOutputFolder $safeBaseName
    $rawFolder = Join-Path $videoOutputRoot "raw"
    $proxyFolder = Join-Path $videoOutputRoot "proxy"
    $framesFolder = Join-Path $videoOutputRoot $framesFolderName
    $audioFolder = Join-Path $videoOutputRoot "audio"
    $transcriptFolder = Join-Path $videoOutputRoot "transcript"
    $translationsFolder = Join-Path $videoOutputRoot "translations"
    $commentsFolder = Join-Path $videoOutputRoot "comments"

    $proxyVideo = Join-Path $proxyFolder "review_proxy_1280.mp4"
    $audioFile = Join-Path $audioFolder "audio.mp3"
    $audioTracksJson = Join-Path $audioFolder "audio_tracks.json"
    $audioTracksCsv = Join-Path $audioFolder "audio_tracks.csv"
    $audioTrackWavFolder = Join-Path $audioFolder "tracks"
    $allTracksReviewMixWav = Join-Path $audioFolder "all_tracks_review_mix.wav"
    $transcriptSourceManifestPath = Join-Path $audioFolder "transcript_source_manifest.json"
    $transcriptSourceWav = Join-Path $audioFolder "transcript_source.wav"
    $transcriptSourceMetadataPath = Join-Path $audioFolder "transcript_source_metadata.json"
    $transcriptTracksFolder = Join-Path $transcriptFolder "tracks"
    $allAudioTracksTranscriptPath = Join-Path $transcriptFolder "all_audio_tracks_transcript.md"
    $allAudioTracksIndexPath = Join-Path $transcriptFolder "all_audio_tracks_index.csv"
    $allAudioTracksManifestPath = Join-Path $transcriptFolder "all_audio_tracks_manifest.json"
    $transcriptSrt = Join-Path $transcriptFolder "transcript.srt"
    $transcriptJson = Join-Path $transcriptFolder "transcript.json"
    $transcriptText = Join-Path $transcriptFolder "transcript.txt"
    $frameIndexCsv = Join-Path $videoOutputRoot "frame_index.csv"
    $readmeFile = Join-Path $videoOutputRoot "README_FOR_CODEX.txt"
    $rawVideoPath = Join-Path $rawFolder $videoItem.Name
    $logFile = Join-Path $videoOutputRoot "script_run.log"
    $openAiDiagnosticsFolder = ""

    Ensure-Directory $videoOutputRoot
    Ensure-Directory $proxyFolder
    Ensure-Directory $framesFolder

    $script:CurrentLogFile = $logFile
    "==== Script run started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====" | Set-Content -LiteralPath $logFile -Encoding UTF8

    Write-Host ""
    Write-Host "==================================================" -ForegroundColor Cyan
    Write-Host ("Processing: {0}" -f $videoItem.FullName) -ForegroundColor Cyan
    Write-Host ("Output:     {0}" -f $videoOutputRoot) -ForegroundColor Cyan
    Write-Host "==================================================" -ForegroundColor Cyan
    Write-Host ""

    Write-Log "Processing video: $($videoItem.FullName)"
    Write-Log "Output folder: $videoOutputRoot"
    Write-Log "Selected frame interval: $FrameIntervalSeconds seconds"
    $processingModeSummary = Get-ProcessingModeSummary -EffectiveMode $ProcessingMode -ProjectMode $OpenAiProject
    $openAiProjectSummary = if ($ProcessingMode -eq "AI" -or $ProcessingMode -eq "Hybrid") { $OpenAiProject } else { "" }
    $transcriptionPathDetails = Get-TranscriptionProviderDetails -EffectiveMode $ProcessingMode -ProjectMode $OpenAiProject -Model $OpenAiTranscriptionModel
    $diagnosticsSetting = [Environment]::GetEnvironmentVariable("MM_OPENAI_DIAGNOSTICS")
    if (-not [string]::IsNullOrWhiteSpace($diagnosticsSetting)) {
        $normalizedDiagnosticsSetting = $diagnosticsSetting.Trim()
        if ($normalizedDiagnosticsSetting -notmatch '^(?i)(0|false|no|off)$') {
            if ($normalizedDiagnosticsSetting -match '^(?i)(1|true|yes|on)$') {
                $openAiDiagnosticsFolder = Join-Path $videoOutputRoot "openai_diagnostics"
            }
            elseif ([System.IO.Path]::IsPathRooted($normalizedDiagnosticsSetting)) {
                $openAiDiagnosticsFolder = $normalizedDiagnosticsSetting
            }
            else {
                $openAiDiagnosticsFolder = Join-Path $videoOutputRoot $normalizedDiagnosticsSetting
            }

            Ensure-Directory $openAiDiagnosticsFolder
            Write-Log ("OpenAI segment diagnostics: {0}" -f $openAiDiagnosticsFolder)
        }
    }
    $loggedRequestedProcessingMode = if ([string]::IsNullOrWhiteSpace($RequestedProcessingMode)) {
        $ProcessingMode
    }
    else {
        $RequestedProcessingMode
    }
    $loggedProcessingSelectionSource = if ([string]::IsNullOrWhiteSpace($ProcessingModeSelectionSource)) {
        "default"
    }
    else {
        $ProcessingModeSelectionSource
    }
    Write-Log ("Requested processing mode: {0} ({1})" -f $loggedRequestedProcessingMode, $loggedProcessingSelectionSource)
    if ($ProcessingMode -ne $loggedRequestedProcessingMode) {
        Write-Log ("Effective processing mode request: {0}" -f $processingModeSummary)
    }
    if (-not [string]::IsNullOrWhiteSpace($ProcessingModeResolutionNote)) {
        Write-Log $ProcessingModeResolutionNote "WARN"
    }
    Write-Log ("Resolved processing mode: {0}" -f $processingModeSummary)
    Write-Log ("Transcription path selected: {0}" -f $transcriptionPathDetails)
    if ($ProcessingMode -eq "Local" -or $ProcessingMode -eq "Hybrid") {
        Write-Log ("Local Whisper model: {0}" -f $ModelName)
    }
    if ($ProcessingMode -eq "Hybrid") {
        Write-Log ("Protected terms profile: {0}" -f (Get-ProtectedTermsProfileSummary -Selection $ProtectedTermsProfileSelection))
    }
    if ($ProcessingMode -eq "AI" -or $ProcessingMode -eq "Hybrid") {
        Write-Log ("OpenAI project mode: {0}" -f $OpenAiProject)
        if ($ProcessingMode -eq "AI" -and -not [string]::IsNullOrWhiteSpace($OpenAiTranscriptionModel) -and $OpenAiProject -eq "Private") {
            Write-Log ("OpenAI transcription model: {0}" -f $OpenAiTranscriptionModel)
        }
        if ($TranslationTargets.Count -gt 0 -and -not [string]::IsNullOrWhiteSpace($requestedOpenAiTranslationModelLabel)) {
            Write-Log ("OpenAI translation model: {0}" -f $requestedOpenAiTranslationModelLabel)
        }
    }
    if ($TranslationTargets.Count -gt 0) {
        $loggedRequestedProvider = if ([string]::IsNullOrWhiteSpace($RequestedTranslationProvider)) {
            $TranslationProvider
        }
        else {
            $RequestedTranslationProvider
        }
        $loggedSelectionSource = if ([string]::IsNullOrWhiteSpace($TranslationProviderSelectionSource)) {
            "default"
        }
        else {
            $TranslationProviderSelectionSource
        }

        Write-Log ("Requested translation provider: {0} ({1})" -f $loggedRequestedProvider, $loggedSelectionSource)
        if ($TranslationProvider -ne $loggedRequestedProvider) {
            Write-Log ("Effective translation provider request: {0}" -f $TranslationProvider)
        }
        if (-not [string]::IsNullOrWhiteSpace($TranslationProviderResolutionNote)) {
            Write-Log $TranslationProviderResolutionNote "WARN"
        }
    }
    if ($RemoteAudioTrackInfo -and -not [string]::IsNullOrWhiteSpace($RemoteAudioTrackInfo.SummaryLine)) {
        Write-Log $RemoteAudioTrackInfo.SummaryLine
        if (-not [string]::IsNullOrWhiteSpace($RemoteAudioTrackInfo.MismatchWarning)) {
            Write-Log $RemoteAudioTrackInfo.MismatchWarning "WARN"
        }
    }

    $preflightResult = Invoke-PhaseAction -Name "Preflight" -Detail $videoItem.Name -Action {
        $phaseHasAudio = Test-VideoHasAudio -FFprobeExe $FFprobeExe -VideoPath $videoItem.FullName
        $phaseAudioPresentText = if ($phaseHasAudio) { "Yes" } else { "No" }
        $phaseDuration = Get-VideoDurationSeconds -FFprobeExe $FFprobeExe -VideoPath $videoItem.FullName
        $phaseVideoStream = Get-VideoPrimaryVideoStream -FFprobeExe $FFprobeExe -VideoPath $videoItem.FullName
        $phaseAudioStreams = @(Get-VideoAudioStreams -FFprobeExe $FFprobeExe -VideoPath $videoItem.FullName)
        Write-Log "Source audio present: $phaseAudioPresentText"
        Write-Log ("Source duration: {0}" -f (Format-DurationHuman $phaseDuration))
        Write-Log ("Source dimensions: {0}x{1}" -f [int]$phaseVideoStream.Width, [int]$phaseVideoStream.Height)
        Write-Log ("Detected audio streams: {0}" -f $phaseAudioStreams.Count)

        return [PSCustomObject]@{
            HasAudio         = $phaseHasAudio
            AudioPresentText = $phaseAudioPresentText
            DurationSeconds  = $phaseDuration
            VideoStream      = $phaseVideoStream
            AudioStreams     = @($phaseAudioStreams)
        }
    }
    $hasAudio = [bool]$preflightResult.HasAudio
    $audioPresentText = [string]$preflightResult.AudioPresentText
    $sourceDurationSeconds = [double]$preflightResult.DurationSeconds
    $sourceVideoStream = $preflightResult.VideoStream
    $sourceVideoWidth = if ($sourceVideoStream) { [int]$sourceVideoStream.Width } else { 0 }
    $sourceVideoHeight = if ($sourceVideoStream) { [int]$sourceVideoStream.Height } else { 0 }
    $audioStreams = @($preflightResult.AudioStreams)

    if ($DoCopyRaw) {
        Invoke-PhaseAction -Name "Raw" -Detail $videoItem.Name -Action {
            Ensure-Directory $rawFolder
            if (-not (Test-Path -LiteralPath $rawVideoPath)) {
                Write-Log "Copying raw video..."
                Copy-Item -LiteralPath $videoItem.FullName -Destination $rawVideoPath -Force
            }
            else {
                Write-Log "Raw video already copied. Skipping."
            }
        } | Out-Null
    }

    $proxyMode = Invoke-PhaseAction -Name "Proxy" -Detail $videoItem.Name -Action {
        New-ProxyVideo `
            -FFmpegExe $FFmpegExe `
            -InputVideo $videoItem.FullName `
            -OutputVideo $proxyVideo `
            -HasAudio $hasAudio `
            -UseGpu $CanUseFfmpegGpu `
            -HeartbeatSeconds $HeartbeatSeconds
    }

    $frameMode = Invoke-PhaseAction -Name "Frames" -Detail ("{0} at {1:0.0}s" -f $videoItem.Name, $FrameIntervalSeconds) -Action {
        Extract-FramesAtInterval `
            -FFmpegExe $FFmpegExe `
            -InputVideo $videoItem.FullName `
            -FramesFolder $framesFolder `
            -UseGpu $CanUseFfmpegGpu `
            -FrameIntervalSeconds $FrameIntervalSeconds `
            -HeartbeatSeconds $HeartbeatSeconds `
            -PythonCommand $PythonCommand
    }

    $panelFrameResult = Invoke-PhaseAction -Name "Panel frames" -Detail ("{0} at {1:0.0}s" -f $videoItem.Name, $FullReviewPanelCropCadenceSeconds) -Action {
        Export-FullReviewPanelFrames `
            -FFmpegExe $FFmpegExe `
            -InputVideo $videoItem.FullName `
            -OutputRoot $videoOutputRoot `
            -SourceWidth $sourceVideoWidth `
            -SourceHeight $sourceVideoHeight `
            -Mode $FullReviewPanelCropMode `
            -CadenceSeconds $FullReviewPanelCropCadenceSeconds `
            -UseGpu $CanUseFfmpegGpu `
            -HeartbeatSeconds $HeartbeatSeconds `
            -PythonCommand $PythonCommand
    }

    $whisperMode = "SKIPPED_NO_AUDIO"
    $transcriptionUsesOpenAi = ($ProcessingMode -eq "AI" -and $OpenAiProject -eq "Private")
    $resolvedWhisperModel = $ModelName
    $audioPhaseResult = $null
    $transcriptionFailureNotes = New-Object System.Collections.Generic.List[string]
    $transcriptionNextSteps = New-Object System.Collections.Generic.List[string]

    if ($hasAudio) {
        $audioPhaseResult = Invoke-PhaseAction -Name "Audio" -Detail $videoItem.Name -Action {
            Ensure-Directory $audioFolder
            Export-AudioTrackInventory -AudioStreams $audioStreams -JsonPath $audioTracksJson -CsvPath $audioTracksCsv
            if ($AudioTrackAudit -or $audioStreams.Count -gt 1) {
                Write-AudioTrackInventoryToConsole -AudioStreams $audioStreams
            }
            foreach ($stream in @($audioStreams)) {
                Write-Log ("Audio inventory: {0}; codec {1}; channels {2}; layout {3}; sample_rate {4}; title '{5}'; handler '{6}'" -f `
                    [string]$stream.display, `
                    [string]$stream.codec_name, `
                    [string]$stream.channels, `
                    [string]$stream.channel_layout, `
                    [string]$stream.sample_rate, `
                    [string]$stream.title, `
                    [string]$stream.handler_name)
            }

            # 206: on Auto, the narration track the shared way, or the full mix.
            $autoTrackOrdinal = Get-MMFullReviewAutoTrackNumber -AudioStreams $audioStreams -Mode $TranscriptAudioMode `
                -StreamSpecifier $TranscriptAudioStream -TrackOrdinal $TranscriptAudioTrackOrdinal -PreferredTrackOrdinal $PreferredTranscriptAudioTrackOrdinal `
                -PythonCommand $PythonCommand -FFmpegExe $FFmpegExe -FFprobeExe $FFprobeExe -VideoPath $videoItem.FullName `
                -PreferGpu $CanUseWhisperGpu -TrackRolesText ([string]$EvidenceTrackRoles) -HeartbeatSeconds $HeartbeatSeconds
            $selection = Resolve-TranscriptAudioSelection `
                -AudioStreams $audioStreams `
                -Mode $TranscriptAudioMode `
                -StreamSpecifier $TranscriptAudioStream `
                -TrackOrdinal $(if ($autoTrackOrdinal -gt 0) { $autoTrackOrdinal } else { $TranscriptAudioTrackOrdinal }) `
                -PreferredTrackOrdinal $PreferredTranscriptAudioTrackOrdinal `
                -InteractiveMode:$InteractiveMode
            if ($null -eq $selection -or $null -eq $selection.SelectedStream) {
                throw "No audio stream could be selected for transcript extraction."
            }

            $selectedStream = $selection.SelectedStream
            $selectedStreams = @($selection.SelectedStreams)
            if ($selectedStreams.Count -eq 0) {
                $selectedStreams = @($selectedStream)
            }
            Write-Log ("Transcript audio mode resolved: {0}; selected track count: {1}; reason: {2}; confidence: {3}" -f [string]$selection.ModeResolved, $selectedStreams.Count, [string]$selection.Reason, [string]$selection.Confidence)
            if (-not [string]::IsNullOrWhiteSpace([string]$selection.Warning)) {
                Write-Log ([string]$selection.Warning) "WARN"
            }

            $sourceSignature = Get-SourceFileSignature -Path $videoItem.FullName
            $reviewAudioStatus = Export-AudioMp3 -FFmpegExe $FFmpegExe -InputVideo $videoItem.FullName -AudioFile $audioFile -HeartbeatSeconds $HeartbeatSeconds -PythonCommand $PythonCommand
            $metadataMatches = $false
            $trackItems = @()
            $transcriptSourceStatus = ""
            $allTracksReviewMixStatus = ""

            if ([bool]$selection.IsAllTracks) {
                $metadataMatches = Test-AllTracksTranscriptManifestMatches `
                    -ManifestPath $transcriptSourceManifestPath `
                    -AudioStreams $selectedStreams `
                    -SourceSignature $sourceSignature
                $forceTranscriptSource = -not $metadataMatches
                Ensure-Directory $audioTrackWavFolder
                foreach ($stream in $selectedStreams) {
                    $trackStem = Get-AudioTrackFileStem -AudioStream $stream
                    $trackWavPath = Join-Path $audioTrackWavFolder ("{0}.wav" -f $trackStem)
                    $trackStatus = Export-TranscriptSourceWav `
                        -FFmpegExe $FFmpegExe `
                        -InputVideo $videoItem.FullName `
                        -OutputWav $trackWavPath `
                        -FfmpegMap ([string]$stream.ffmpeg_map) `
                        -PythonCommand $PythonCommand `
                        -HeartbeatSeconds $HeartbeatSeconds `
                        -Force:$forceTranscriptSource
                    $trackItems += [PSCustomObject]@{
                        Stream = $stream
                        WavPath = $trackWavPath
                        ExtractionStatus = $trackStatus
                    }
                }

                $allTracksReviewMixStatus = Export-AllTracksReviewMixWav `
                    -FFmpegExe $FFmpegExe `
                    -InputVideo $videoItem.FullName `
                    -AudioStreams $selectedStreams `
                    -OutputWav $allTracksReviewMixWav `
                    -PythonCommand $PythonCommand `
                    -HeartbeatSeconds $HeartbeatSeconds `
                    -Force:$forceTranscriptSource
                if (Test-Path -LiteralPath $allTracksReviewMixWav) {
                    $transcriptSourceWav = $allTracksReviewMixWav
                }
                $transcriptSourceStatus = "ALL_TRACKS"
                $manifest = New-TranscriptSourceManifestPayload `
                    -PackageRoot $videoOutputRoot `
                    -Selection $selection `
                    -SourceSignature $sourceSignature `
                    -TrackItems @($trackItems) `
                    -AllTracksReviewMixWav $allTracksReviewMixWav `
                    -AllTracksReviewMixStatus $allTracksReviewMixStatus `
                    -TranscriptStatus "pending"
                Write-TranscriptSourceManifest -ManifestPath $transcriptSourceManifestPath -Payload $manifest
            }
            else {
                $metadataMatches = Test-TranscriptSourceMetadataMatches `
                    -MetadataPath $transcriptSourceMetadataPath `
                    -Selection $selection `
                    -SourceSignature $sourceSignature
                $forceTranscriptSource = -not $metadataMatches
                $transcriptSourceStatus = Export-TranscriptSourceWav `
                    -FFmpegExe $FFmpegExe `
                    -InputVideo $videoItem.FullName `
                    -OutputWav $transcriptSourceWav `
                    -FfmpegMap ([string]$selectedStream.ffmpeg_map) `
                    -PythonCommand $PythonCommand `
                    -HeartbeatSeconds $HeartbeatSeconds `
                    -Force:$forceTranscriptSource

                $metadata = New-TranscriptSourceMetadata `
                    -Selection $selection `
                    -SourceSignature $sourceSignature `
                    -TranscriptSourcePath $transcriptSourceWav `
                    -ExtractionStatus $transcriptSourceStatus `
                    -TranscriptStatus "pending"
                Write-TranscriptSourceMetadata -MetadataPath $transcriptSourceMetadataPath -Metadata $metadata
                $trackItems = @([PSCustomObject]@{
                        Stream = $selectedStream
                        WavPath = $transcriptSourceWav
                        ExtractionStatus = $transcriptSourceStatus
                    })
            }

            return [PSCustomObject]@{
                Selection = $selection
                SelectedStream = $selectedStream
                SelectedStreams = @($selectedStreams)
                IsAllTracks = [bool]$selection.IsAllTracks
                MetadataMatches = [bool]$metadataMatches
                ReviewAudioStatus = $reviewAudioStatus
                TranscriptSourceStatus = $transcriptSourceStatus
                TranscriptSourceWav = $transcriptSourceWav
                TranscriptSourceMetadataPath = $transcriptSourceMetadataPath
                TranscriptSourceManifestPath = $transcriptSourceManifestPath
                TrackItems = @($trackItems)
                AllTracksReviewMixWav = $allTracksReviewMixWav
                AllTracksReviewMixStatus = $allTracksReviewMixStatus
            }
        }

        if ($audioPhaseResult -and -not [string]::IsNullOrWhiteSpace([string]$audioPhaseResult.TranscriptSourceWav)) {
            $transcriptSourceWav = [string]$audioPhaseResult.TranscriptSourceWav
        }
        if ($audioPhaseResult -and [bool]$audioPhaseResult.IsAllTracks -and -not [string]::IsNullOrWhiteSpace([string]$audioPhaseResult.AllTracksReviewMixWav) -and (Test-Path -LiteralPath ([string]$audioPhaseResult.AllTracksReviewMixWav))) {
            $transcriptSourceWav = [string]$audioPhaseResult.AllTracksReviewMixWav
        }
        Write-Log ("Effective transcript audio source for downstream phases: {0}" -f $(if ([string]::IsNullOrWhiteSpace($transcriptSourceWav)) { "none" } else { $transcriptSourceWav }))

        $transcriptResult = Invoke-PhaseAction -Name "Transcript" -Detail $videoItem.Name -Action {
            Ensure-Directory $transcriptFolder
            if ($audioPhaseResult.IsAllTracks) {
                $canReuseAllTrackTranscript = (
                    [bool]$audioPhaseResult.MetadataMatches -and
                    (Test-Path -LiteralPath $transcriptSrt) -and
                    (Test-Path -LiteralPath $transcriptJson) -and
                    (Test-Path -LiteralPath $transcriptText) -and
                    (Test-Path -LiteralPath $allAudioTracksTranscriptPath) -and
                    (Test-Path -LiteralPath $allAudioTracksIndexPath) -and
                    (Test-Path -LiteralPath $allAudioTracksManifestPath)
                )
                if ($canReuseAllTrackTranscript) {
                    Write-Log "All-track transcript files already exist and transcript_source_manifest.json matches the selected audio streams/source/settings. Skipping new transcription."
                    return [PSCustomObject]@{
                        Device   = "existing"
                        JsonPath = $transcriptJson
                        SrtPath  = $transcriptSrt
                        TextPath = $transcriptText
                        Language = ""
                        GpuError = ""
                    }
                }

                if ((Test-Path -LiteralPath $transcriptSrt) -or (Test-Path -LiteralPath $transcriptJson) -or (Test-Path -LiteralPath $transcriptText)) {
                    Write-Log "Existing transcript files were not reused because all-track transcript source metadata was missing or did not match. Regenerating all-track transcript." "WARN"
                    foreach ($existingTranscriptPath in @($transcriptSrt, $transcriptJson, $transcriptText, $allAudioTracksTranscriptPath, $allAudioTracksIndexPath, $allAudioTracksManifestPath)) {
                        if (Test-Path -LiteralPath $existingTranscriptPath) {
                            Remove-Item -LiteralPath $existingTranscriptPath -Force -ErrorAction SilentlyContinue
                        }
                    }
                }

                Ensure-Directory $transcriptTracksFolder
                $trackTranscriptItems = @()
                $combinedSegments = New-Object System.Collections.Generic.List[object]
                $combinedSegmentId = 0
                $trackDevices = New-Object System.Collections.Generic.List[string]
                $trackGpuErrors = New-Object System.Collections.Generic.List[string]
                $allTrackLanguage = ""
                $allTrackEffectiveTranscriptionDurationSeconds = [math]::Max($sourceDurationSeconds, $sourceDurationSeconds * [math]::Max(1, @($audioPhaseResult.TrackItems).Count))
                $trackTranscriptSuccessCount = 0
                $trackTranscriptFailureCount = 0

                foreach ($trackItem in @($audioPhaseResult.TrackItems)) {
                    $stream = $trackItem.Stream
                    $trackStem = Get-AudioTrackFileStem -AudioStream $stream
                    $trackJsonName = "${trackStem}_transcript.json"
                    $trackSrtName = "${trackStem}_transcript.srt"
                    $trackTextName = "${trackStem}_transcript.txt"
                    $trackMarkdownPath = Join-Path $transcriptTracksFolder ("${trackStem}_transcript.md")
                    Write-Log ("Transcribing {0} ({1}; absolute {2})..." -f [string]$stream.vlc_track_label, [string]$stream.ffmpeg_map, [string]$stream.absolute_stream_specifier)

                    try {
                        if ($transcriptionUsesOpenAi) {
                            $trackResult = Invoke-OpenAiWhisperTranscript `
                                -AudioPath ([string]$trackItem.WavPath) `
                                -TranscriptFolder $transcriptTracksFolder `
                                -LanguageCode $LanguageCode `
                                -Model $OpenAiTranscriptionModel `
                                -FFmpegExe $FFmpegExe `
                                -FFprobeExe $FFprobeExe `
                                -JsonName $trackJsonName `
                                -SrtName $trackSrtName `
                                -TextName $trackTextName `
                                -HeartbeatSeconds $HeartbeatSeconds
                        }
                        else {
                            $trackResult = Invoke-PythonWhisperTranscript `
                                -PythonCommand $PythonCommand `
                                -AudioPath ([string]$trackItem.WavPath) `
                                -TranscriptFolder $transcriptTracksFolder `
                                -ModelName $resolvedWhisperModel `
                                -LanguageCode $LanguageCode `
                                -FFmpegExe $FFmpegExe `
                                -PreferGpu $CanUseWhisperGpu `
                                -Task "transcribe" `
                                -JsonName $trackJsonName `
                                -SrtName $trackSrtName `
                                -TextName $trackTextName `
                                -SourceDurationSeconds $sourceDurationSeconds `
                                -EffectiveDurationSeconds $allTrackEffectiveTranscriptionDurationSeconds `
                                -AudioTrackCount (@($audioPhaseResult.TrackItems).Count) `
                                -TranscriptAudioModeResolved ([string]$audioPhaseResult.Selection.ModeResolved) `
                                -InitialPrompt (Get-EvidenceTranscriptionInitialPrompt -GlossaryEntries (Get-MMSpellingWords)) `
                                -GlossaryEntries (Get-MMSpellingWords) `
                                -HeartbeatSeconds $HeartbeatSeconds `
                                -WhisperTimeoutSeconds $WhisperTimeoutSeconds `
                                -InteractiveMode:$InteractiveMode `
                                -AllowInteractiveLongRunPrompt:$InteractiveMode

                            if ($trackResult.ModelNameUsed) {
                                $resolvedWhisperModel = [string]$trackResult.ModelNameUsed
                            }
                        }

                        if ($trackResult.Device) {
                            [void]$trackDevices.Add([string]$trackResult.Device)
                        }
                        if ($trackResult.GpuError) {
                            [void]$trackGpuErrors.Add([string]$trackResult.GpuError)
                        }

                        $trackData = Get-TranscriptSegments -TranscriptJsonPath $trackResult.JsonPath
                        if ([string]::IsNullOrWhiteSpace($allTrackLanguage) -and -not [string]::IsNullOrWhiteSpace($trackResult.Language)) {
                            $allTrackLanguage = [string]$trackResult.Language
                        }
                        if ([string]::IsNullOrWhiteSpace($allTrackLanguage) -and -not [string]::IsNullOrWhiteSpace($trackData.Language)) {
                            $allTrackLanguage = [string]$trackData.Language
                        }

                        New-TrackTranscriptMarkdown `
                            -OutputPath $trackMarkdownPath `
                            -TrackItem $trackItem `
                            -Segments @($trackData.Segments) `
                            -SourceVideoName $videoItem.Name `
                            -TranscriptStatus "generated"

                        foreach ($segment in @($trackData.Segments)) {
                            if ([string]::IsNullOrWhiteSpace([string]$segment.text)) {
                                continue
                            }
                            [void]$combinedSegments.Add([PSCustomObject]@{
                                    id    = $combinedSegmentId
                                    start = [double]$segment.start
                                    end   = [double]$segment.end
                                    text  = ("[{0}] {1}" -f [string]$stream.vlc_track_label, ([string]$segment.text).Trim())
                                })
                            $combinedSegmentId += 1
                        }

                        $trackTranscriptItems += [PSCustomObject]@{
                            Stream = $stream
                            WavPath = [string]$trackItem.WavPath
                            ExtractionStatus = [string]$trackItem.ExtractionStatus
                            TranscriptStatus = "generated"
                            FailureReason = ""
                            JsonPath = [string]$trackResult.JsonPath
                            SrtPath = [string]$trackResult.SrtPath
                            TextPath = [string]$trackResult.TextPath
                            MarkdownPath = $trackMarkdownPath
                        }
                        $trackTranscriptSuccessCount += 1
                    }
                    catch {
                        $trackTranscriptFailureCount += 1
                        $failureMessage = $_.Exception.Message
                        Write-Log ("All-track transcription failed for {0}; completed tracks will be preserved and remaining tracks will continue. {1}" -f [string]$stream.vlc_track_label, $failureMessage) "WARN"
                        [void]$transcriptionFailureNotes.Add(("Transcript partial: {0} failed: {1}" -f [string]$stream.vlc_track_label, $failureMessage))
                        [void]$transcriptionNextSteps.Add(("Review {0} and all_audio_tracks_manifest.json before trusting the all-track transcript." -f $trackMarkdownPath))

                        New-TrackTranscriptMarkdown `
                            -OutputPath $trackMarkdownPath `
                            -TrackItem $trackItem `
                            -Segments @() `
                            -SourceVideoName $videoItem.Name `
                            -TranscriptStatus "failed" `
                            -FailureReason $failureMessage

                        $trackTranscriptItems += [PSCustomObject]@{
                            Stream = $stream
                            WavPath = [string]$trackItem.WavPath
                            ExtractionStatus = [string]$trackItem.ExtractionStatus
                            TranscriptStatus = "failed"
                            FailureReason = $failureMessage
                            JsonPath = ""
                            SrtPath = ""
                            TextPath = ""
                            MarkdownPath = $trackMarkdownPath
                        }
                        continue
                    }
                }

                if ([string]::IsNullOrWhiteSpace($allTrackLanguage)) {
                    $allTrackLanguage = if ([string]::IsNullOrWhiteSpace($LanguageCode)) { "unknown" } else { $LanguageCode }
                }

                $allTrackTranscriptStatus = if ($trackTranscriptFailureCount -gt 0 -and $trackTranscriptSuccessCount -gt 0) {
                    "partial"
                }
                elseif ($trackTranscriptFailureCount -gt 0) {
                    "failed"
                }
                else {
                    "generated"
                }

                if ($trackTranscriptFailureCount -gt 0 -and $trackTranscriptSuccessCount -gt 0) {
                    $packageStatus = "PARTIAL_SUCCESS"
                    Write-Log ("All-track transcription completed with partial status: {0} generated track(s), {1} failed track(s)." -f $trackTranscriptSuccessCount, $trackTranscriptFailureCount) "WARN"
                }

                $combinedArtifacts = $null
                if ($combinedSegments.Count -gt 0) {
                    $combinedArtifacts = Write-TranscriptArtifactsFromSegments `
                        -OutputFolder $transcriptFolder `
                        -Segments $combinedSegments.ToArray() `
                        -Language $allTrackLanguage `
                        -SourceLanguage $allTrackLanguage `
                        -Task "transcribe" `
                        -JsonName "transcript.json" `
                        -SrtName "transcript.srt" `
                        -TextName "transcript.txt"
                }

                Write-AllAudioTracksTranscriptSummary `
                    -TranscriptPath $allAudioTracksTranscriptPath `
                    -IndexPath $allAudioTracksIndexPath `
                    -ManifestPath $allAudioTracksManifestPath `
                    -SourceVideoName $videoItem.Name `
                    -TranscriptItems @($trackTranscriptItems) `
                    -ResolvedMode ([string]$audioPhaseResult.Selection.ModeResolved) `
                    -AllTracksReviewMixWav ([string]$audioPhaseResult.AllTracksReviewMixWav) `
                    -AllTracksReviewMixStatus ([string]$audioPhaseResult.AllTracksReviewMixStatus) `
                    -TranscriptStatus $allTrackTranscriptStatus

                $sourceSignature = Get-SourceFileSignature -Path $videoItem.FullName
                $manifest = New-TranscriptSourceManifestPayload `
                    -PackageRoot $videoOutputRoot `
                    -Selection $audioPhaseResult.Selection `
                    -SourceSignature $sourceSignature `
                    -TrackItems @($audioPhaseResult.TrackItems) `
                    -AllTracksReviewMixWav ([string]$audioPhaseResult.AllTracksReviewMixWav) `
                    -AllTracksReviewMixStatus ([string]$audioPhaseResult.AllTracksReviewMixStatus) `
                    -TranscriptStatus $allTrackTranscriptStatus `
                    -TranscriptItems @($trackTranscriptItems) `
                    -AllTracksTranscriptPath $allAudioTracksTranscriptPath `
                    -AllTracksIndexPath $allAudioTracksIndexPath `
                    -AllTracksManifestPath $allAudioTracksManifestPath
                Write-TranscriptSourceManifest -ManifestPath $transcriptSourceManifestPath -Payload $manifest

                if ($combinedSegments.Count -eq 0) {
                    throw ("All-track transcription failed for all selected audio tracks. Wrote partial/failure manifests to {0} and {1}." -f $allAudioTracksManifestPath, $transcriptSourceManifestPath)
                }

                $resolvedDevice = if (@($trackDevices | Where-Object { $_ -eq "openai" }).Count -gt 0) {
                    "openai"
                }
                elseif (@($trackDevices | Where-Object { $_ -eq "cuda" }).Count -gt 0 -and @($trackDevices | Where-Object { $_ -ne "cuda" }).Count -eq 0) {
                    "cuda"
                }
                else {
                    "cpu"
                }
                return [PSCustomObject]@{
                    Device   = $resolvedDevice
                    JsonPath = $combinedArtifacts.JsonPath
                    SrtPath  = $combinedArtifacts.SrtPath
                    TextPath = $combinedArtifacts.TextPath
                    Language = $allTrackLanguage
                    GpuError = (($trackGpuErrors | Select-Object -Unique) -join " | ")
                    TrackTranscripts = @($trackTranscriptItems)
                    AllAudioTracksTranscriptPath = $allAudioTracksTranscriptPath
                    AllAudioTracksIndexPath = $allAudioTracksIndexPath
                    AllAudioTracksManifestPath = $allAudioTracksManifestPath
                }
            }

            if ((Test-Path -LiteralPath $transcriptSrt) -and (Test-Path -LiteralPath $transcriptJson) -and (Test-Path -LiteralPath $transcriptText)) {
                if ($audioPhaseResult.MetadataMatches) {
                    Write-Log "Transcript files already exist and transcript_source_metadata.json matches the selected audio stream/source/settings. Skipping new transcription."
                    Set-TranscriptSourceMetadataStatus -MetadataPath $transcriptSourceMetadataPath -TranscriptStatus "reused"
                    return [PSCustomObject]@{
                        Device   = "existing"
                        JsonPath = $transcriptJson
                        SrtPath  = $transcriptSrt
                        TextPath = $transcriptText
                        Language = ""
                        GpuError = ""
                    }
                }

                Write-Log "Existing transcript files were not reused because transcript source metadata was missing or did not match the selected audio stream/source/settings. Regenerating transcript." "WARN"
                foreach ($existingTranscriptPath in @($transcriptSrt, $transcriptJson, $transcriptText)) {
                    if (Test-Path -LiteralPath $existingTranscriptPath) {
                        Remove-Item -LiteralPath $existingTranscriptPath -Force -ErrorAction SilentlyContinue
                    }
                }
            }

            if ($transcriptionUsesOpenAi) {
                Write-Log ("Generating transcript with OpenAI transcription ({0})..." -f $OpenAiTranscriptionModel)

                $phaseTranscriptResult = Invoke-OpenAiWhisperTranscript `
                    -AudioPath $transcriptSourceWav `
                    -TranscriptFolder $transcriptFolder `
                    -LanguageCode $LanguageCode `
                    -Model $OpenAiTranscriptionModel `
                    -FFmpegExe $FFmpegExe `
                    -FFprobeExe $FFprobeExe `
                    -JsonName "transcript.json" `
                    -SrtName "transcript.srt" `
                    -TextName "transcript.txt" `
                    -HeartbeatSeconds $HeartbeatSeconds
            }
            else {
                Write-Log ("Preparing Local Whisper transcript with model '{0}' on {1}..." -f $resolvedWhisperModel, $(if ($CanUseWhisperGpu) { "GPU-capable path" } else { "CPU-only path" }))

                $phaseTranscriptResult = Invoke-PythonWhisperTranscript `
                    -PythonCommand $PythonCommand `
                    -AudioPath $transcriptSourceWav `
                    -TranscriptFolder $transcriptFolder `
                    -ModelName $resolvedWhisperModel `
                    -LanguageCode $LanguageCode `
                    -FFmpegExe $FFmpegExe `
                    -PreferGpu $CanUseWhisperGpu `
                    -Task "transcribe" `
                    -JsonName "transcript.json" `
                    -SrtName "transcript.srt" `
                    -TextName "transcript.txt" `
                    -SourceDurationSeconds $sourceDurationSeconds `
                    -EffectiveDurationSeconds $sourceDurationSeconds `
                    -AudioTrackCount (@($audioPhaseResult.SelectedStreams).Count) `
                    -TranscriptAudioModeResolved ([string]$audioPhaseResult.Selection.ModeResolved) `
                    -InitialPrompt (Get-EvidenceTranscriptionInitialPrompt -GlossaryEntries (Get-MMSpellingWords)) `
                    -GlossaryEntries (Get-MMSpellingWords) `
                    -NarrationSpeechMode $(if ($null -ne $script:MMFullReviewNarration) { "Sparse" } else { "Auto" }) `
                    -HeartbeatSeconds $HeartbeatSeconds `
                    -WhisperTimeoutSeconds $WhisperTimeoutSeconds `
                    -InteractiveMode:$InteractiveMode `
                    -AllowInteractiveLongRunPrompt:$InteractiveMode

                if ($phaseTranscriptResult.ModelNameUsed) {
                    $resolvedWhisperModel = [string]$phaseTranscriptResult.ModelNameUsed
                }
                if ($null -ne $script:MMFullReviewNarration) {
                    # 206: the narration filter Find my bug reports uses: lines another track
                    # carries, and lines said where the narration track was near silent, go.
                    $null = Invoke-MMNarrationCrossCheck -PythonCommand $PythonCommand -FFmpegExe $FFmpegExe `
                        -VideoPath $videoItem.FullName -TranscriptJsonPath $transcriptJson -Detection $script:MMFullReviewNarration `
                        -PreferGpu $CanUseWhisperGpu -HeartbeatSeconds $HeartbeatSeconds
                }
            }

            if (-not (Test-Path -LiteralPath $transcriptSrt)) {
                throw "Expected SRT not found: $transcriptSrt"
            }

            if (-not (Test-Path -LiteralPath $transcriptJson)) {
                throw "Expected JSON not found: $transcriptJson"
            }

            if (-not (Test-Path -LiteralPath $transcriptText)) {
                throw "Expected transcript text file not found: $transcriptText"
            }

            Set-TranscriptSourceMetadataStatus -MetadataPath $transcriptSourceMetadataPath -TranscriptStatus "generated"
            return $phaseTranscriptResult
        }

        if ($transcriptResult.Device -eq "openai") {
            $whisperMode = "OPENAI"
        }
        elseif ($transcriptResult.Device -eq "cuda") {
            $whisperMode = "GPU_CUDA"
        }
        elseif ($transcriptResult.Device -eq "existing") {
            $whisperMode = "SKIPPED_EXISTING"
        }
        else {
            $whisperMode = "CPU"
        }

        if ($transcriptResult.GpuError) {
            Write-Log ("[GPU->CPU] Whisper GPU fallback reason: {0}" -f $transcriptResult.GpuError) "WARN"
        }

        if ($transcriptResult.Device -ne "openai" -and $transcriptResult.Device -ne "existing") {
            Write-Log ("Whisper transcript completed using {0} {1}." -f (Get-ProgressDeviceTag -Device $transcriptResult.Device), $transcriptResult.Device)
        }
    }
    else {
        Write-Log "Skipping audio extraction: source file has no audio stream."
        Write-Log "Skipping transcript generation: source file has no audio stream."
        $audioFile = ""
        $audioTracksJson = ""
        $audioTracksCsv = ""
        $audioTrackWavFolder = ""
        $allTracksReviewMixWav = ""
        $transcriptSourceManifestPath = ""
        $transcriptSourceWav = ""
        $transcriptSourceMetadataPath = ""
        $transcriptTracksFolder = ""
        $allAudioTracksTranscriptPath = ""
        $allAudioTracksIndexPath = ""
        $allAudioTracksManifestPath = ""
        $transcriptSrt = ""
        $transcriptJson = ""
        $transcriptText = ""
        Write-PhaseResult -Name "Audio" -Status "PASS" -Detail "Skipped because source has no audio"
        Write-PhaseResult -Name "Transcript" -Status "PASS" -Detail "Skipped because source has no audio"
    }

    $detectedLanguage = ""
    $completedTargets = New-Object System.Collections.Generic.List[string]
    $translationProviderDetails = New-Object System.Collections.Generic.List[string]
    $translationRecoveryNotes = New-Object System.Collections.Generic.List[string]
    $translationFailureNotes = New-Object System.Collections.Generic.List[string]
    $translationNextSteps = New-Object System.Collections.Generic.List[string]
    $activeTranslationMode = [string]$TranslationProvider
    $packageStatus = "SUCCESS"
    $shouldFailRun = $false
    $translationStopRequested = $false
    $commentsTextPath = ""
    $commentsJsonPath = ""
    $commentsSummary = ""
    $hybridTranslationResult = $null
    $hybridTranslationTranscriptJson = ""
    $hybridTranslationTranscriptSrt = ""
    $hybridTranslationTranscriptText = ""
    $hybridValidationReport = ""
    $translationUsedOpenAi = $false
    $openAiTranslationSummaryParts = New-Object System.Collections.Generic.List[string]
    $translationModelSummaryParts = New-Object System.Collections.Generic.List[string]
    $translationValidationSummaryParts = New-Object System.Collections.Generic.List[string]
    $protectedTermsProfileSummaryParts = New-Object System.Collections.Generic.List[string]
    $protectedTermsPathSummaryParts = New-Object System.Collections.Generic.List[string]
    $estimatedOpenAiTextCostValue = [double]0.0
    $hasEstimatedOpenAiTextCost = $false

    if ($hasAudio -and (Test-Path -LiteralPath $transcriptJson)) {
        $transcriptData = Get-TranscriptSegments -TranscriptJsonPath $transcriptJson
        if (-not $transcriptData.Segments -or $transcriptData.Segments.Count -eq 0) {
            throw "Transcript generation completed but no segments were found."
        }

        $detectedLanguage = if ($transcriptResult -and -not [string]::IsNullOrWhiteSpace($transcriptResult.Language)) {
            $transcriptResult.Language
        }
        elseif (-not [string]::IsNullOrWhiteSpace($transcriptData.Language)) {
            $transcriptData.Language
        }
        elseif (-not [string]::IsNullOrWhiteSpace($LanguageCode)) {
            $LanguageCode
        }
        else {
            "unknown"
        }

        Write-Log "Detected source language: $detectedLanguage"

        $normalizedTargets = @($TranslationTargets | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)
        if ($ProcessingMode -ne "Hybrid" -and $TranslationProvider -eq "OpenAI" -and $normalizedTargets.Count -gt 0 -and -not (Test-OpenAiTranslationAvailable)) {
            Show-OpenAiSetupGuidance -ProviderLabel "OpenAI translation"
            throw (Get-OpenAiKeyRequirementText)
        }

        foreach ($targetLanguage in $normalizedTargets) {
            if ($translationStopRequested) {
                break
            }

            $phaseDetail = ("{0} -> {1}" -f $videoItem.Name, $targetLanguage)
            Write-Phase -Name "Translation" -Detail $phaseDetail

            $providerUsed = ""
            $translationPhaseCompleted = $false
            $pendingOpenAiFallbackDetails = $null
            $translationFolder = Join-Path $translationsFolder $targetLanguage

            while (-not $translationPhaseCompleted) {
                try {
                    $providerPlan = Resolve-TranslationTargetProvider `
                        -TranslationMode $activeTranslationMode `
                        -TargetLanguage $targetLanguage `
                        -DetectedLanguage $detectedLanguage `
                        -ModelName $resolvedWhisperModel `
                        -PythonCommand $PythonCommand `
                        -InteractiveMode:$InteractiveMode `
                        -HeartbeatSeconds $HeartbeatSeconds

                    if ($providerPlan.Action -eq "skip") {
                        Write-Log $providerPlan.Note "WARN"
                        $packageStatus = "PARTIAL_SUCCESS"
                        if ($pendingOpenAiFallbackDetails) {
                            [void]$translationFailureNotes.Add(("{0}: {1} Local fallback was skipped. {2}" -f $targetLanguage, $pendingOpenAiFallbackDetails.UserMessage, $providerPlan.Note))
                            [void]$translationNextSteps.Add($pendingOpenAiFallbackDetails.NextStep)
                            $pendingOpenAiFallbackDetails = $null
                        }
                        else {
                            [void]$translationFailureNotes.Add($providerPlan.Note)
                            [void]$translationNextSteps.Add(("Install local translation support or rerun with -ProcessingMode AI for target '{0}'." -f $targetLanguage))
                        }

                        Write-PhaseResult -Name "Translation" -Status "PASS" -Detail ("{0} (skipped)" -f $phaseDetail)
                        $translationPhaseCompleted = $true
                        break
                    }

                    $providerUsed = $providerPlan.Provider
                    Write-Log ("Translation provider for {0}: {1} (mode: {2})" -f $targetLanguage, $providerUsed, $activeTranslationMode)

                    Ensure-Directory $translationsFolder
                    Ensure-Directory $translationFolder

                    if ($providerUsed -eq "Original transcript copy") {
                        $detectedLanguageCode = Get-CanonicalLanguageCode -Language $detectedLanguage
                        $targetLanguageCode = Get-CanonicalLanguageCode -Language $targetLanguage
                        $sourceDisplayCode = if (-not [string]::IsNullOrWhiteSpace($detectedLanguageCode)) { $detectedLanguageCode } else { $detectedLanguage }
                        if ($detectedLanguageCode -eq "en") {
                            $openAiTranslationNote = "OpenAI Translation: not used for this file; source already English, original transcript copied"
                        }
                        else {
                            $sourceDisplayName = Get-LanguageDisplayName -Code $sourceDisplayCode
                            $openAiTranslationNote = ("OpenAI Translation: not used for this file; target already matches the detected source language ({0}), original transcript copied" -f $sourceDisplayName)
                        }

                        Write-OperatorNote $openAiTranslationNote -Color DarkCyan
                        [void]$openAiTranslationSummaryParts.Add($openAiTranslationNote)
                        $providerUsed = "Original transcript copy (no OpenAI call)"
                        $null = Write-TranscriptArtifactsFromSegments `
                            -OutputFolder $translationFolder `
                            -Segments $transcriptData.Segments `
                            -Language $(if (-not [string]::IsNullOrWhiteSpace($targetLanguageCode)) { $targetLanguageCode } else { $targetLanguage }) `
                            -SourceLanguage $(if (-not [string]::IsNullOrWhiteSpace($detectedLanguageCode)) { $detectedLanguageCode } else { $detectedLanguage }) `
                            -Task "copy" `
                            -JsonName "transcript.json" `
                            -SrtName "transcript.srt" `
                            -TextName "transcript.txt"
                    }
                    elseif ($providerUsed -eq "Local (Whisper audio translation)") {
                        $whisperTranslationLanguageCode = if (-not [string]::IsNullOrWhiteSpace($detectedLanguage) -and $detectedLanguage -ne "unknown") {
                            $detectedLanguage
                        }
                        else {
                            $LanguageCode
                        }
                        $whisperTranslationLanguageLabel = if ([string]::IsNullOrWhiteSpace($whisperTranslationLanguageCode)) {
                            "auto-detect"
                        }
                        else {
                            $whisperTranslationLanguageCode
                        }
                        Write-Log ("Running local Whisper audio translation to English with model '{0}' and source language hint '{1}'." -f $resolvedWhisperModel, $whisperTranslationLanguageLabel)
                        $tempJsonName = "transcript_whisper_translate.json"
                        $tempSrtName = "transcript_whisper_translate.srt"
                        $tempTextName = "transcript_whisper_translate.txt"
                        if ([string]::IsNullOrWhiteSpace($transcriptSourceWav) -or -not (Test-Path -LiteralPath $transcriptSourceWav -PathType Leaf)) {
                            throw "Local Whisper audio translation needs the effective transcript audio source, but it was not found: $transcriptSourceWav"
                        }
                        $translateResult = Invoke-PythonWhisperTranscript `
                            -PythonCommand $PythonCommand `
                            -AudioPath $transcriptSourceWav `
                            -TranscriptFolder $translationFolder `
                            -ModelName $resolvedWhisperModel `
                            -LanguageCode $whisperTranslationLanguageCode `
                            -FFmpegExe $FFmpegExe `
                            -PreferGpu $CanUseWhisperGpu `
                            -Task "translate" `
                            -JsonName $tempJsonName `
                            -SrtName $tempSrtName `
                            -TextName $tempTextName `
                            -SourceDurationSeconds $sourceDurationSeconds `
                            -EffectiveDurationSeconds $sourceDurationSeconds `
                            -AudioTrackCount $(if ($audioPhaseResult) { @($audioPhaseResult.SelectedStreams).Count } else { 0 }) `
                            -TranscriptAudioModeResolved $(if ($audioPhaseResult -and $audioPhaseResult.Selection) { [string]$audioPhaseResult.Selection.ModeResolved } else { "" }) `
                            -HeartbeatSeconds $HeartbeatSeconds `
                            -WhisperTimeoutSeconds $WhisperTimeoutSeconds `
                            -InitialPrompt (Get-EvidenceTranscriptionInitialPrompt -GlossaryEntries (Get-MMSpellingWords)) `
                            -GlossaryEntries (Get-MMSpellingWords) `
                            -InteractiveMode:$InteractiveMode `
                            -AllowInteractiveLongRunPrompt:$false

                        $translatedData = Get-TranscriptSegments -TranscriptJsonPath $translateResult.JsonPath
                        $null = Write-TranscriptArtifactsFromSegments `
                            -OutputFolder $translationFolder `
                            -Segments $translatedData.Segments `
                            -Language "en" `
                            -SourceLanguage $detectedLanguage `
                            -Task "translate" `
                            -JsonName "transcript.json" `
                            -SrtName "transcript.srt" `
                            -TextName "transcript.txt"

                        foreach ($tempPath in @(
                            (Join-Path $translationFolder $tempJsonName),
                            (Join-Path $translationFolder $tempSrtName),
                            (Join-Path $translationFolder $tempTextName)
                        )) {
                            if (Test-Path -LiteralPath $tempPath) {
                                Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
                            }
                        }
                    }
                    elseif ($providerUsed -eq "Local (Argos Translate)") {
                        $translatedSegments = Invoke-ArgosSegmentTranslation `
                            -PythonCommand $PythonCommand `
                            -Segments $transcriptData.Segments `
                            -SourceLanguageCode $detectedLanguage `
                            -TargetLanguageCode $targetLanguage `
                            -HeartbeatSeconds $HeartbeatSeconds

                        $null = Write-TranscriptArtifactsFromSegments `
                            -OutputFolder $translationFolder `
                            -Segments $translatedSegments `
                            -Language $targetLanguage `
                            -SourceLanguage $detectedLanguage `
                            -Task "translate" `
                            -JsonName "transcript.json" `
                            -SrtName "transcript.srt" `
                            -TextName "transcript.txt"
                    }
                    else {
                        if ($ProcessingMode -eq "Hybrid") {
                            $providerUsed = "Hybrid Accuracy text translation"
                            $requestedModelLabel = Get-RequestedOpenAiTranslationModelLabel -EffectiveMode $ProcessingMode -RequestedModel $OpenAiModel
                            $protectedTermsProfileDisplay = Get-ProtectedTermsProfileSummary -Selection $ProtectedTermsProfileSelection
                            $protectedTermsProfilePath = if ($ProtectedTermsProfileSelection -and $ProtectedTermsProfileSelection.IsSelected) { $ProtectedTermsProfileSelection.Path } else { "" }
                            Write-OperatorNote ("OpenAI Translation: {0} / {1} / text-only" -f $OpenAiProject, $requestedModelLabel)
                            Write-Log "Hybrid Accuracy keeps source audio local and uploads transcript text only for English translation."
                            Write-Log ("Protected terms profile: {0}" -f $protectedTermsProfileDisplay)
                            $hybridTranslationResult = Invoke-HybridAccuracyTextTranslation `
                                -PythonCommand $PythonCommand `
                                -TranscriptJsonPath $transcriptJson `
                                -TranslationFolder $translationFolder `
                                -SourceLanguage $detectedLanguage `
                                -TargetLanguage $targetLanguage `
                                -GlossaryPath $protectedTermsProfilePath `
                                -OpenAiProject $OpenAiProject `
                                -RequestedModel $OpenAiModel `
                                -HeartbeatSeconds $HeartbeatSeconds

                            $providerUsed = if ([string]::IsNullOrWhiteSpace($hybridTranslationResult.UsedModel)) {
                                "Hybrid Accuracy text translation"
                            }
                            else {
                                "Hybrid Accuracy text translation via $($hybridTranslationResult.UsedModel)"
                            }

                            $hybridTranslationTranscriptJson = $hybridTranslationResult.TranscriptJsonPath
                            $hybridTranslationTranscriptSrt = $hybridTranslationResult.TranscriptSrtPath
                            $hybridTranslationTranscriptText = $hybridTranslationResult.TranscriptTextPath
                            $hybridValidationReport = $hybridTranslationResult.ValidationReportPath
                            $translationUsedOpenAi = $true

                            $resolvedRequestedModel = if (-not [string]::IsNullOrWhiteSpace($hybridTranslationResult.RequestedModel)) {
                                $hybridTranslationResult.RequestedModel
                            }
                            else {
                                $requestedModelLabel
                            }
                            $resolvedUsedModel = if (-not [string]::IsNullOrWhiteSpace($hybridTranslationResult.UsedModel)) {
                                $hybridTranslationResult.UsedModel
                            }
                            else {
                                $resolvedRequestedModel
                            }
                            $resolvedValidationStatus = if (-not [string]::IsNullOrWhiteSpace($hybridTranslationResult.ValidationStatus)) {
                                $hybridTranslationResult.ValidationStatus
                            }
                            else {
                                "unknown"
                            }
                            [void]$openAiTranslationSummaryParts.Add((
                                "{0}={1} / requested {2} / used {3} / validation {4}" -f `
                                    $targetLanguage, `
                                    $hybridTranslationResult.OpenAiProject, `
                                    $resolvedRequestedModel, `
                                    $resolvedUsedModel, `
                                    $resolvedValidationStatus
                            ))
                            if (-not [string]::IsNullOrWhiteSpace($resolvedUsedModel)) {
                                [void]$translationModelSummaryParts.Add($resolvedUsedModel)
                            }
                            [void]$translationValidationSummaryParts.Add(("{0}={1}" -f $targetLanguage, $resolvedValidationStatus))
                            [void]$protectedTermsProfileSummaryParts.Add($protectedTermsProfileDisplay)
                            if (-not [string]::IsNullOrWhiteSpace($protectedTermsProfilePath)) {
                                [void]$protectedTermsPathSummaryParts.Add($protectedTermsProfilePath)
                            }
                            if ($null -ne $hybridTranslationResult.EstimatedCostUsd) {
                                $estimatedOpenAiTextCostValue += [double]$hybridTranslationResult.EstimatedCostUsd
                                $hasEstimatedOpenAiTextCost = $true
                            }

                            Write-Log ("Hybrid translation project: {0}" -f $hybridTranslationResult.OpenAiProject)
                            Write-Log ("Hybrid requested translation model: {0}" -f $resolvedRequestedModel)
                            Write-Log ("Hybrid used translation model: {0}" -f $resolvedUsedModel)
                            Write-Log ("Hybrid privacy class: {0}" -f $hybridTranslationResult.PrivacyClass)
                            Write-Log ("Hybrid validation status: {0}" -f $resolvedValidationStatus)
                            Write-Log ("Hybrid validation report: {0}" -f $hybridValidationReport)
                            Write-OperatorNote ("OpenAI Translation: requested {0}; used {1}; validation {2}" -f $resolvedRequestedModel, $resolvedUsedModel, $resolvedValidationStatus)

                            if ($resolvedValidationStatus -ne "accepted") {
                                $packageStatus = "PARTIAL_SUCCESS"
                                [void]$translationFailureNotes.Add((
                                    "{0}: Hybrid Accuracy translation finished with status '{1}' ({2}/{3} segments translated)." -f `
                                        $targetLanguage, `
                                        $resolvedValidationStatus, `
                                        ($hybridTranslationResult.SegmentCount - $hybridTranslationResult.FailedSegmentCount), `
                                        $hybridTranslationResult.SegmentCount
                                ))
                                [void]$translationNextSteps.Add(("Review {0}" -f $hybridValidationReport))
                            }

                            if ($hybridTranslationResult.WarningCount -gt 0) {
                                [void]$translationRecoveryNotes.Add((
                                    "{0}: Hybrid warnings={1}, contamination={2}, mojibake={3}, protected terms={4}, compression={5}." -f `
                                        $targetLanguage, `
                                        $hybridTranslationResult.WarningCount, `
                                        $hybridTranslationResult.ContaminationCount, `
                                        $hybridTranslationResult.MojibakeCount, `
                                        $hybridTranslationResult.GlossaryViolationCount, `
                                        $hybridTranslationResult.CompressionWarningCount
                                ))
                            }
                            if ($hybridTranslationResult.RetryUsed) {
                                [void]$translationRecoveryNotes.Add(("{0}: Hybrid retry/repair prompt was used." -f $targetLanguage))
                            }
                        }
                        else {
                            $targetDisplayName = Get-LanguageDisplayName -Code $targetLanguage
                            $sourceDisplayName = Get-LanguageDisplayName -Code $detectedLanguage
                            $requestedModelLabel = Get-RequestedOpenAiTranslationModelLabel -EffectiveMode $ProcessingMode -RequestedModel $OpenAiModel
                            Write-OperatorNote ("OpenAI Translation: {0} / {1} / transcript text" -f $OpenAiProject, $requestedModelLabel)
                            $openAiTranslationResult = Invoke-OpenAiSegmentTranslation `
                                -Segments $transcriptData.Segments `
                                -SourceLanguage $sourceDisplayName `
                                -TargetLanguage $targetDisplayName `
                                -Model $OpenAiModel `
                                -HeartbeatSeconds $HeartbeatSeconds `
                                -DiagnosticsFolder $openAiDiagnosticsFolder
                            $translatedSegments = $openAiTranslationResult.Segments
                            $translationUsedOpenAi = $true

                            $resolvedRequestedModel = if (-not [string]::IsNullOrWhiteSpace($openAiTranslationResult.RequestedModel)) {
                                $openAiTranslationResult.RequestedModel
                            }
                            else {
                                $requestedModelLabel
                            }
                            $resolvedUsedModel = if (-not [string]::IsNullOrWhiteSpace($openAiTranslationResult.UsedModel)) {
                                $openAiTranslationResult.UsedModel
                            }
                            else {
                                $resolvedRequestedModel
                            }
                            $resolvedValidationStatus = "not run (AI mode)"
                            $providerUsed = if ([string]::IsNullOrWhiteSpace($resolvedUsedModel)) {
                                "OpenAI text translation"
                            }
                            else {
                                "OpenAI text translation via $resolvedUsedModel"
                            }
                            [void]$openAiTranslationSummaryParts.Add((
                                "{0}={1} / requested {2} / used {3} / validation {4}" -f `
                                    $targetLanguage, `
                                    $OpenAiProject, `
                                    $resolvedRequestedModel, `
                                    $resolvedUsedModel, `
                                    $resolvedValidationStatus
                            ))
                            if (-not [string]::IsNullOrWhiteSpace($resolvedUsedModel)) {
                                [void]$translationModelSummaryParts.Add($resolvedUsedModel)
                            }
                            [void]$translationValidationSummaryParts.Add(("{0}={1}" -f $targetLanguage, $resolvedValidationStatus))
                            if ($null -ne $openAiTranslationResult.EstimatedCostUsd) {
                                $estimatedOpenAiTextCostValue += [double]$openAiTranslationResult.EstimatedCostUsd
                                $hasEstimatedOpenAiTextCost = $true
                            }
                            Write-OperatorNote ("OpenAI Translation: requested {0}; used {1}; validation {2}" -f $resolvedRequestedModel, $resolvedUsedModel, $resolvedValidationStatus)

                            $null = Write-TranscriptArtifactsFromSegments `
                                -OutputFolder $translationFolder `
                                -Segments $translatedSegments `
                                -Language $targetLanguage `
                                -SourceLanguage $detectedLanguage `
                                -Task "translate" `
                                -JsonName "transcript.json" `
                                -SrtName "transcript.srt" `
                                -TextName "transcript.txt"
                        }
                    }

                    [void]$completedTargets.Add($targetLanguage)
                    [void]$translationProviderDetails.Add(("{0}={1}" -f $targetLanguage, $providerUsed))
                    if ($pendingOpenAiFallbackDetails) {
                        [void]$translationRecoveryNotes.Add(("{0}: {1} Fell back to {2}." -f $targetLanguage, $pendingOpenAiFallbackDetails.UserMessage, $providerUsed))
                        $pendingOpenAiFallbackDetails = $null
                    }

                    Write-PhaseResult -Name "Translation" -Status "PASS" -Detail $phaseDetail
                    $translationPhaseCompleted = $true
                }
                catch {
                    $failureDetails = if ($providerUsed -eq "OpenAI") { Get-OpenAiFailureDetails -Exception $_.Exception } else { $null }
                    if ($providerUsed -eq "OpenAI" -and $failureDetails -and $failureDetails.Recoverable) {
                        [void]$translationProviderDetails.Add(("{0}={1}" -f $targetLanguage, (Get-OpenAiProviderFailureText -FailureDetails $failureDetails)))
                        if ($activeTranslationMode -eq "Auto") {
                            Write-Log ("OpenAI translation for '{0}' hit a recoverable problem. {1}" -f $targetLanguage, $failureDetails.UserMessage) "WARN"
                            $activeTranslationMode = "Local"
                            $pendingOpenAiFallbackDetails = $failureDetails
                            $providerUsed = ""
                            continue
                        }

                        if ($activeTranslationMode -eq "OpenAI" -and $InteractiveMode) {
                            $canUseLocalFallback = $true
                            $localFallbackNote = ""
                            try {
                                $null = Resolve-TranslationTargetProvider `
                                    -TranslationMode "Local" `
                                    -TargetLanguage $targetLanguage `
                                    -DetectedLanguage $detectedLanguage `
                                    -ModelName $ModelName `
                                    -PythonCommand $PythonCommand `
                                    -InteractiveMode:$InteractiveMode `
                                    -HeartbeatSeconds $HeartbeatSeconds
                            }
                            catch {
                                $canUseLocalFallback = $false
                                $localFallbackNote = $_.Exception.Message
                            }

                            $decision = Get-InteractiveOpenAiRuntimeRecoveryDecision `
                                -TargetLanguage $targetLanguage `
                                -FailureDetails $failureDetails `
                                -CanUseLocalFallback:$canUseLocalFallback `
                                -LocalFallbackNote $localFallbackNote
                            if (-not [string]::IsNullOrWhiteSpace($decision.ResolutionNote)) {
                                Write-Log $decision.ResolutionNote "WARN"
                            }

                            if ($decision.Action -eq "Retry") {
                                $providerUsed = ""
                                continue
                            }

                            if ($decision.Action -eq "UseLocal") {
                                $activeTranslationMode = "Local"
                                $pendingOpenAiFallbackDetails = $failureDetails
                                $providerUsed = ""
                                continue
                            }

                            Write-PhaseResult -Name "Translation" -Status "FAIL" -Detail $_.Exception.Message
                            $packageStatus = "PARTIAL_SUCCESS"
                            [void]$translationFailureNotes.Add(("{0}: {1}" -f $targetLanguage, $failureDetails.UserMessage))
                            [void]$translationNextSteps.Add($failureDetails.NextStep)
                            $translationStopRequested = $true
                            $translationPhaseCompleted = $true
                            break
                        }

                        Write-PhaseResult -Name "Translation" -Status "FAIL" -Detail $_.Exception.Message
                        $packageStatus = "PARTIAL_SUCCESS"
                        $shouldFailRun = $true
                        [void]$translationFailureNotes.Add(("{0}: {1}" -f $targetLanguage, $failureDetails.UserMessage))
                        [void]$translationNextSteps.Add($failureDetails.NextStep)
                        $translationStopRequested = $true
                        $translationPhaseCompleted = $true
                        break
                    }

                    if ($pendingOpenAiFallbackDetails) {
                        Write-PhaseResult -Name "Translation" -Status "FAIL" -Detail $_.Exception.Message
                        $packageStatus = "PARTIAL_SUCCESS"
                        [void]$translationFailureNotes.Add(("{0}: {1} Local fallback could not finish: {2}" -f $targetLanguage, $pendingOpenAiFallbackDetails.UserMessage, $_.Exception.Message))
                        [void]$translationNextSteps.Add($pendingOpenAiFallbackDetails.NextStep)
                        $pendingOpenAiFallbackDetails = $null
                        $translationPhaseCompleted = $true
                        break
                    }

                    Write-PhaseResult -Name "Translation" -Status "FAIL" -Detail $_.Exception.Message
                    throw
                }
            }
        }
    }
    elseif ($TranslationTargets.Count -gt 0) {
        Write-Log "Translation was requested, but this source has no readable audio stream. Skipping translated transcript output." "WARN"
        $packageStatus = "PARTIAL_SUCCESS"
        [void]$translationFailureNotes.Add("Translation was requested, but this source has no readable audio stream.")
        [void]$translationNextSteps.Add("Use a source with readable audio or rerun without -TranslateTo.")
    }

    if ($translationUsedOpenAi) {
        if ($hasEstimatedOpenAiTextCost) {
            $script:SessionEstimatedOpenAiTextCostUsd += $estimatedOpenAiTextCostValue
            Write-OperatorNote (
                "OpenAI text cost: this file {0}; session total {1}" -f `
                    (Format-EstimatedUsd $estimatedOpenAiTextCostValue), `
                    (Format-EstimatedUsd $script:SessionEstimatedOpenAiTextCostUsd)
            ) -Color DarkCyan
        }
        else {
            Write-OperatorNote "OpenAI text cost: estimate unavailable for this file." -Color DarkCyan
        }
    }

    if ($CommentsRequested -and -not [string]::IsNullOrWhiteSpace($SourceInfoJsonPath) -and (Test-Path -LiteralPath $SourceInfoJsonPath)) {
        $commentArtifacts = Invoke-PhaseAction -Name "Comments" -Detail $videoItem.Name -Action {
            Export-CommentsArtifactsFromInfoJson -InfoJsonPath $SourceInfoJsonPath -CommentsFolder $commentsFolder
        }

        if ($commentArtifacts) {
            $commentsTextPath = $commentArtifacts.CommentsTextPath
            $commentsJsonPath = $commentArtifacts.CommentsJsonPath
            $commentsSummary = ("{0} public comments exported" -f $commentArtifacts.CommentCount)
            Write-Log $commentsSummary
        }
        else {
            $commentsSummary = "requested, but no public comments were returned by yt-dlp"
            Write-Log $commentsSummary "WARN"
        }
    }

    $frameCount = Invoke-PhaseAction -Name "Index" -Detail $videoItem.Name -Action {
        Build-FrameIndex `
            -FramesFolder $framesFolder `
            -FrameIndexCsv $frameIndexCsv `
            -FrameIntervalSeconds $FrameIntervalSeconds `
            -FramesFolderName $framesFolderName `
            -HeartbeatSeconds $HeartbeatSeconds
    }

    if ($frameCount -le 0) {
        throw "No frames were extracted to $framesFolder"
    }
    $rawPresent = if ($DoCopyRaw) { "Yes" } else { "No" }
    $normalizedTargetsForSummary = @($TranslationTargets | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)
    $missingTranslationTargets = @($normalizedTargetsForSummary | Where-Object { $completedTargets -notcontains $_ })
    $translationProviderText = if ($translationProviderDetails.Count -gt 0) {
        ($translationProviderDetails | Select-Object -Unique) -join "; "
    }
    else {
        "none"
    }
    $translationStatusParts = New-Object System.Collections.Generic.List[string]
    if ($normalizedTargetsForSummary.Count -eq 0) {
        [void]$translationStatusParts.Add("not requested")
    }
    else {
        [void]$translationStatusParts.Add(("completed: {0}" -f $(if ($completedTargets.Count -gt 0) { (@($completedTargets) -join ", ") } else { "none" })))
        if ($missingTranslationTargets.Count -gt 0) {
            [void]$translationStatusParts.Add(("not completed: {0}" -f ($missingTranslationTargets -join ", ")))
        }
    }
    if ($hybridTranslationResult) {
        $hybridProtectedTermsSummary = if ($protectedTermsProfileSummaryParts.Count -gt 0) {
            ($protectedTermsProfileSummaryParts | Select-Object -Unique) -join ", "
        }
        elseif ($ProtectedTermsProfileSelection -and $ProtectedTermsProfileSelection.IsSelected) {
            $ProtectedTermsProfileSelection.DisplayName
        }
        else {
            "none (generic mode)"
        }
        $hybridValidationSummary = if ($translationValidationSummaryParts.Count -gt 0) {
            (($translationValidationSummaryParts | Select-Object -Unique) -join "; ")
        }
        else {
            $hybridTranslationResult.ValidationStatus
        }
        [void]$translationStatusParts.Add(("hybrid validation: {0}" -f $hybridValidationSummary))
        $translationProviderText = if (-not [string]::IsNullOrWhiteSpace($hybridTranslationResult.UsedModel)) {
            ("en=Hybrid Accuracy text translation via {0} ({1} project; {2}; protected terms {3}; validation {4})" -f `
                $hybridTranslationResult.UsedModel, `
                $hybridTranslationResult.OpenAiProject, `
                $hybridTranslationResult.PrivacyClass, `
                $hybridProtectedTermsSummary, `
                $hybridValidationSummary)
        }
        else {
            ("en=Hybrid Accuracy text translation ({0} project; {1}; protected terms {2}; validation {3})" -f `
                $hybridTranslationResult.OpenAiProject, `
                $hybridTranslationResult.PrivacyClass, `
                $hybridProtectedTermsSummary, `
                $hybridValidationSummary)
        }
    }
    $translationStatusText = $translationStatusParts -join "; "
    $translationNotesParts = @($transcriptionFailureNotes) + @($translationRecoveryNotes) + @($translationFailureNotes)
    if ($hybridTranslationResult) {
        $hybridNoteParts = New-Object System.Collections.Generic.List[string]
        [void]$hybridNoteParts.Add(("privacy: {0}" -f $hybridTranslationResult.PrivacyClass))
        [void]$hybridNoteParts.Add(("protected terms profile: {0}" -f $(if ($protectedTermsProfileSummaryParts.Count -gt 0) { ($protectedTermsProfileSummaryParts | Select-Object -Unique) -join ", " } else { "none (generic mode)" })))
        [void]$hybridNoteParts.Add(("validation report: {0}" -f $hybridTranslationResult.ValidationReportPath))
        [void]$hybridNoteParts.Add(("warnings={0}; contamination={1}; mojibake={2}; protected terms={3}; compression={4}" -f `
                $hybridTranslationResult.WarningCount, `
                $hybridTranslationResult.ContaminationCount, `
                $hybridTranslationResult.MojibakeCount, `
                $hybridTranslationResult.GlossaryViolationCount, `
                $hybridTranslationResult.CompressionWarningCount))
        if ($hybridTranslationResult.RetryUsed) {
            [void]$hybridNoteParts.Add("repair retry used: yes")
        }
        if (-not [string]::IsNullOrWhiteSpace($hybridTranslationResult.RequestedModel) -and $hybridTranslationResult.RequestedModel -ne $hybridTranslationResult.UsedModel) {
            [void]$hybridNoteParts.Add(("requested model: {0}" -f $hybridTranslationResult.RequestedModel))
        }
        $translationNotesParts += @($hybridNoteParts)
    }
    $translationNotesText = if ($translationNotesParts.Count -gt 0) {
        ($translationNotesParts | Select-Object -Unique) -join " | "
    }
    else {
        ""
    }
    $nextSteps = @($transcriptionNextSteps) + @($translationNextSteps)
    $nextStepsText = if ($nextSteps.Count -gt 0) {
        ($nextSteps | Select-Object -Unique) -join " | "
    }
    else {
        ""
    }
    $transcriptionProviderName = if ($transcriptionUsesOpenAi) { "OpenAI" } else { "Local Whisper" }
    $transcriptionModelUsed = if ($transcriptionUsesOpenAi) {
        $OpenAiTranscriptionModel
    }
    else {
        $resolvedWhisperModel
    }
    $usedCopyTranslation = $translationProviderDetails | Where-Object { $_ -like "*=Original transcript copy (no OpenAI call)" }
    $translationProviderNameForSummary = if ($hybridTranslationResult) {
        "Hybrid Accuracy text translation"
    }
    elseif ($translationUsedOpenAi) {
        "OpenAI text translation"
    }
    elseif (@($usedCopyTranslation).Count -gt 0) {
        "Original transcript copy"
    }
    else {
        ""
    }
    $translationModelForSummary = if ($translationModelSummaryParts.Count -gt 0) {
        ($translationModelSummaryParts | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique) -join ", "
    }
    else {
        ""
    }
    $translatedWordCountForSummary = if ($hybridTranslationResult) { [int]$hybridTranslationResult.TranslatedWordCount } else { 0 }
    $sourceWordCountForSummary = if ($hybridTranslationResult) { [int]$hybridTranslationResult.SourceWordCount } else { 0 }
    $englishSourceRatioForSummary = if ($hybridTranslationResult -and $null -ne $hybridTranslationResult.EnglishSourceRatio) {
        ([double]$hybridTranslationResult.EnglishSourceRatio).ToString("0.0000", [System.Globalization.CultureInfo]::InvariantCulture)
    }
    else {
        ""
    }
    $translationValidationStatusForSummary = if ($translationValidationSummaryParts.Count -gt 0) {
        ($translationValidationSummaryParts | Select-Object -Unique) -join "; "
    }
    else {
        ""
    }
    $estimatedOpenAiTextCostForSummary = if ($hasEstimatedOpenAiTextCost) {
        ([double]$estimatedOpenAiTextCostValue).ToString("0.000000", [System.Globalization.CultureInfo]::InvariantCulture)
    }
    elseif (@($usedCopyTranslation).Count -gt 0) {
        "0.000000"
    }
    else {
        ""
    }
    $protectedTermsProfileForSummary = if ($protectedTermsProfileSummaryParts.Count -gt 0) {
        ($protectedTermsProfileSummaryParts | Select-Object -Unique) -join ", "
    }
    elseif ($hybridTranslationResult) {
        "none (generic mode)"
    }
    else {
        ""
    }
    $protectedTermsPathForSummary = if ($protectedTermsPathSummaryParts.Count -gt 0) {
        ($protectedTermsPathSummaryParts | Select-Object -Unique) -join "; "
    }
    else {
        ""
    }
    $openAiTranslationSummary = if ($openAiTranslationSummaryParts.Count -gt 0) {
        ($openAiTranslationSummaryParts | Select-Object -Unique) -join "; "
    }
    else {
        ""
    }

    if ($packageStatus -eq "PARTIAL_SUCCESS") {
        Write-Log ("Package marked as partial success. Translation status: {0}" -f $translationStatusText) "WARN"
        if (-not [string]::IsNullOrWhiteSpace($translationProviderText) -and $translationProviderText -ne "none") {
            Write-Log ("Translation path used: {0}" -f $translationProviderText) "WARN"
        }
        if (-not [string]::IsNullOrWhiteSpace($translationNotesText)) {
            Write-Log ("Translation notes: {0}" -f $translationNotesText) "WARN"
        }
        if (-not [string]::IsNullOrWhiteSpace($nextStepsText)) {
            Write-Log ("Next steps: {0}" -f $nextStepsText) "WARN"
        }
    }
    elseif (-not [string]::IsNullOrWhiteSpace($translationNotesText)) {
        Write-Log ("Translation recovery notes: {0}" -f $translationNotesText) "WARN"
    }

    $panelFramesPath = Join-Path $videoOutputRoot "frames_panels"
    $panelFramesGenerated = ($panelFrameResult -and [bool]$panelFrameResult.generated)
    $panelFrameIndexPath = if ($panelFramesGenerated -and -not [string]::IsNullOrWhiteSpace([string]$panelFrameResult.index_path)) {
        [string]$panelFrameResult.index_path
    }
    else {
        ""
    }
    $panelFrameManifestPath = if ($panelFramesGenerated -and -not [string]::IsNullOrWhiteSpace([string]$panelFrameResult.manifest_path)) {
        [string]$panelFrameResult.manifest_path
    }
    else {
        ""
    }
    $panelFramesSummary = if ($panelFrameResult) {
        if ([bool]$panelFrameResult.generated) {
            ("generated {0} frame slot(s) at {1}s cadence from {2}x{3} source" -f [int]$panelFrameResult.frame_count, [double]$panelFrameResult.cadence_seconds, $sourceVideoWidth, $sourceVideoHeight)
        }
        elseif (-not [string]::IsNullOrWhiteSpace([string]$panelFrameResult.skip_reason)) {
            ("{0}: {1}" -f [string]$panelFrameResult.status, [string]$panelFrameResult.skip_reason)
        }
        else {
            [string]$panelFrameResult.status
        }
    }
    else {
        "not evaluated"
    }
    $selectedTranscriptTrackCount = if ($audioPhaseResult) { @($audioPhaseResult.SelectedStreams).Count } else { 0 }
    $transcriptAudioModeResolved = if ($audioPhaseResult -and $audioPhaseResult.Selection) { [string]$audioPhaseResult.Selection.ModeResolved } else { "" }
    $transcriptSourceMetadataForSummary = if ($audioPhaseResult -and [bool]$audioPhaseResult.IsAllTracks) { "" } else { $transcriptSourceMetadataPath }
    $transcriptSourceSummary = if ($audioPhaseResult -and [bool]$audioPhaseResult.IsAllTracks) {
        ("All audio tracks ({0}); reason: {1}; confidence: {2}; transcript: {3}" -f $selectedTranscriptTrackCount, [string]$audioPhaseResult.Selection.Reason, [string]$audioPhaseResult.Selection.Confidence, $allAudioTracksTranscriptPath)
    }
    elseif ($audioPhaseResult -and $audioPhaseResult.SelectedStream) {
        ("{0}; reason: {1}; confidence: {2}" -f [string]$audioPhaseResult.SelectedStream.display, [string]$audioPhaseResult.Selection.Reason, [string]$audioPhaseResult.Selection.Confidence)
    }
    else {
        "not available"
    }

    Invoke-PhaseAction -Name "README" -Detail $videoItem.Name -Action {
        New-CodexReadme `
            -ReadmePath $readmeFile `
            -VideoFileName $videoItem.Name `
            -RawPresent $rawPresent `
            -AudioPresent $audioPresentText `
            -FrameIntervalSeconds $FrameIntervalSeconds `
            -ProcessingModeSummary $processingModeSummary `
            -OpenAiProjectSummary $openAiProjectSummary `
            -TranscriptionPathDetails $transcriptionPathDetails `
            -DetectedLanguage $detectedLanguage `
            -TranslationTargets @($normalizedTargetsForSummary) `
            -TranslationPathDetails $translationProviderText `
            -CommentsSummary $commentsSummary `
            -RemoteAudioTrackSummary $(if ($RemoteAudioTrackInfo) { $RemoteAudioTrackInfo.SummaryValue } else { "" }) `
            -PackageStatus $packageStatus `
            -TranslationStatus $translationStatusText `
            -TranslationNotes $translationNotesText `
            -NextSteps $nextStepsText `
            -PanelFramesSummary $panelFramesSummary `
            -PanelFramesPath $(if ($panelFramesGenerated) { $panelFramesPath } else { "" }) `
            -PanelFrameIndexPath $panelFrameIndexPath `
            -TranscriptSourceSummary $transcriptSourceSummary `
            -TranscriptSourceMetadataPath $transcriptSourceMetadataForSummary `
            -TranscriptSourceManifestPath $transcriptSourceManifestPath `
            -AllAudioTracksTranscriptPath $allAudioTracksTranscriptPath `
            -AllAudioTracksIndexPath $allAudioTracksIndexPath `
            -AllAudioTracksManifestPath $allAudioTracksManifestPath `
            -PythonCommand $PythonCommand
    } | Out-Null

    Add-SummaryRow `
        -SummaryCsv $SummaryCsv `
        -SourceVideo $videoItem.Name `
        -OutputFolderName $safeBaseName `
        -OutputPath $videoOutputRoot `
        -SourceDurationSeconds $sourceDurationSeconds `
        -FrameCount $frameCount `
        -ProxyVideo $proxyVideo `
        -AudioFile $audioFile `
        -TranscriptSrt $transcriptSrt `
        -TranscriptJson $transcriptJson `
        -TranscriptText $transcriptText `
        -RawCopied $rawPresent `
        -AudioPresent $audioPresentText `
        -DetectedLanguage $detectedLanguage `
        -ProcessingModeSummary $processingModeSummary `
        -OpenAiProjectSummary $openAiProjectSummary `
        -TranscriptionPath $transcriptionPathDetails `
        -TranslationTargets ((@($normalizedTargetsForSummary)) -join ", ") `
        -TranslationPath $translationProviderText `
        -CommentsText $commentsTextPath `
        -CommentsJson $commentsJsonPath `
        -CommentsSummary $commentsSummary `
        -RemoteAudioTrack $(if ($RemoteAudioTrackInfo) { $RemoteAudioTrackInfo.SummaryValue } else { "" }) `
        -ProxyMode $proxyMode `
        -FrameMode $frameMode `
        -WhisperMode $whisperMode `
        -WhisperRequestedDevice $(if ($transcriptResult) { $transcriptResult.RequestedDevice } else { "" }) `
        -WhisperSelectedDevice $(if ($transcriptResult) { $transcriptResult.SelectedDevice } else { "" }) `
        -WhisperDeviceSwitchCount $(if ($transcriptResult) { $transcriptResult.DeviceSwitchCount } else { 0 }) `
        -TranscriptSourceWav $transcriptSourceWav `
        -TranscriptSourceMetadata $transcriptSourceMetadataForSummary `
        -TranscriptSourceManifest $transcriptSourceManifestPath `
        -TranscriptAudioSelection $transcriptSourceSummary `
        -AudioTrackCount $selectedTranscriptTrackCount `
        -TranscriptAudioModeResolved $transcriptAudioModeResolved `
        -AllAudioTracksTranscript $allAudioTracksTranscriptPath `
        -AllAudioTracksIndex $allAudioTracksIndexPath `
        -AllAudioTracksManifest $allAudioTracksManifestPath `
        -PanelFrameIndex $panelFrameIndexPath `
        -PanelFrameManifest $panelFrameManifestPath `
        -PanelFramesSummary $panelFramesSummary `
        -FrameIntervalSeconds $FrameIntervalSeconds `
        -PackageStatus $packageStatus `
        -TranslationStatus $translationStatusText `
        -TranslationNotes $translationNotesText `
        -NextSteps $nextStepsText `
        -TranslationTranscriptJson $hybridTranslationTranscriptJson `
        -TranslationTranscriptSrt $hybridTranslationTranscriptSrt `
        -TranslationTranscriptText $hybridTranslationTranscriptText `
        -TranslationValidationReport $hybridValidationReport `
        -LaneId $(if ($hybridTranslationResult) { $hybridTranslationResult.LaneId } else { "" }) `
        -PrivacyClass $(if ($hybridTranslationResult) { $hybridTranslationResult.PrivacyClass } else { "" }) `
        -SourceLanguage $detectedLanguage `
        -TargetLanguage $(if ($hybridTranslationResult) { "en" } else { "" }) `
        -TranscriptionProvider $transcriptionProviderName `
        -TranscriptionModel $transcriptionModelUsed `
        -TranslationProviderName $translationProviderNameForSummary `
        -TranslationModel $translationModelForSummary `
        -TranscriptWordCount $sourceWordCountForSummary `
        -TranslatedWordCount $translatedWordCountForSummary `
        -EnglishSourceRatio $englishSourceRatioForSummary `
        -ValidationWarningCount $(if ($hybridTranslationResult) { $hybridTranslationResult.WarningCount } else { 0 }) `
        -ContaminationCount $(if ($hybridTranslationResult) { $hybridTranslationResult.ContaminationCount } else { 0 }) `
        -EncodingArtifactCount $(if ($hybridTranslationResult) { $hybridTranslationResult.EncodingArtifactCount } else { 0 }) `
        -GlossaryViolationCount $(if ($hybridTranslationResult) { $hybridTranslationResult.GlossaryViolationCount } else { 0 }) `
        -CompressionWarningCount $(if ($hybridTranslationResult) { $hybridTranslationResult.CompressionWarningCount } else { 0 }) `
        -TranslationValidationStatus $translationValidationStatusForSummary `
        -EstimatedOpenAiTextCostUsd $estimatedOpenAiTextCostForSummary `
        -FailedTranslatedSegmentCount $(if ($hybridTranslationResult) { $hybridTranslationResult.FailedSegmentCount } else { 0 }) `
        -GlossaryProfile $(if ($hybridTranslationResult) { $hybridTranslationResult.GlossaryProfile } else { "" }) `
        -GlossaryPath $(if ($hybridTranslationResult) { $hybridTranslationResult.GlossaryPath } else { "" }) `
        -ProtectedTermsProfile $protectedTermsProfileForSummary `
        -ProtectedTermsPath $protectedTermsPathForSummary `
        -OpenAiTranslationSummary $openAiTranslationSummary

    return [PSCustomObject]@{
        SourceVideoName  = $videoItem.Name
        SourceVideoPath  = $videoItem.FullName
        OutputFolderName = $safeBaseName
        OutputPath       = $videoOutputRoot
        FrameCount       = $frameCount
        SourceWidth      = $sourceVideoWidth
        SourceHeight     = $sourceVideoHeight
        AudioPresent     = $audioPresentText
        AudioTracksJson  = $audioTracksJson
        AudioTracksCsv   = $audioTracksCsv
        AudioTrackCount  = $selectedTranscriptTrackCount
        TranscriptAudioModeResolved = $transcriptAudioModeResolved
        IsAllAudioTracksTranscript = $(if ($audioPhaseResult) { [bool]$audioPhaseResult.IsAllTracks } else { $false })
        TranscriptSourceWav = $transcriptSourceWav
        TranscriptJsonPath = $transcriptJson
        TranscriptSrtPath = $transcriptSrt
        TranscriptTextPath = $transcriptText
        TranscriptSourceMetadataPath = $transcriptSourceMetadataForSummary
        TranscriptSourceManifestPath = $transcriptSourceManifestPath
        TranscriptAudioSelection = $transcriptSourceSummary
        AudioTrackWavFolder = $audioTrackWavFolder
        AllTracksReviewMixWav = $(if ($audioPhaseResult) { [string]$audioPhaseResult.AllTracksReviewMixWav } else { "" })
        AllTracksReviewMixStatus = $(if ($audioPhaseResult) { [string]$audioPhaseResult.AllTracksReviewMixStatus } else { "" })
        TrackTranscripts = @($(if ($transcriptResult -and $transcriptResult.TrackTranscripts) { $transcriptResult.TrackTranscripts } else { @() }))
        AllAudioTracksTranscriptPath = $allAudioTracksTranscriptPath
        AllAudioTracksIndexPath = $allAudioTracksIndexPath
        AllAudioTracksManifestPath = $allAudioTracksManifestPath
        ProcessingMode   = $processingModeSummary
        OpenAiProject    = $openAiProjectSummary
        ProxyMode        = $proxyMode
        FrameMode        = $frameMode
        WhisperMode      = $whisperMode
        TranscriptionPath = $transcriptionPathDetails
        DetectedLanguage = $detectedLanguage
        TranslationTargets = @($completedTargets)
        TranslationProvider = $translationProviderText
        CommentsSummary  = $commentsSummary
        RemoteAudioTrack = $(if ($RemoteAudioTrackInfo) { $RemoteAudioTrackInfo.SummaryValue } else { "" })
        FramesFolderName = $framesFolderName
        PanelFramesPath  = $(if ($panelFramesGenerated) { $panelFramesPath } else { "" })
        PanelFrameIndexPath = $panelFrameIndexPath
        PanelFrameManifestPath = $panelFrameManifestPath
        PanelFramesSummary = $panelFramesSummary
        PanelFrameResult = $panelFrameResult
        FullReviewPanelCropMode = $FullReviewPanelCropMode
        FullReviewPanelCropsGenerated = $panelFramesGenerated
        FullReviewPanelCropStatus = $(if ($panelFrameResult) { [string]$panelFrameResult.status } else { "not_evaluated" })
        FullReviewPanelCropSkipReason = $(if ($panelFrameResult) { [string]$panelFrameResult.skip_reason } else { "" })
        FullReviewPanelCropCadenceSeconds = [double]$FullReviewPanelCropCadenceSeconds
        FullReviewPanelFrameCount = $(if ($panelFrameResult) { [int]$panelFrameResult.frame_count } else { 0 })
        FullReviewPanelCropGeometry = @($panelFrameResult.crop_geometry)
        PackageStatus    = $packageStatus
        TranslationStatus = $translationStatusText
        TranslationNotes = $translationNotesText
        NextSteps        = $nextStepsText
        TranslationModel = $translationModelForSummary
        TranslationValidationStatus = $translationValidationStatusForSummary
        OpenAiTranslationSummary = $openAiTranslationSummary
        EstimatedOpenAiTextCostUsd = $estimatedOpenAiTextCostForSummary
        ProtectedTermsProfile = $protectedTermsProfileForSummary
        ValidationReport = $hybridValidationReport
        ShouldFailRun    = $shouldFailRun
    }
}

function Get-TranscriptOnlySourceId {
    param([string]$VideoPath)

    $item = Get-Item -LiteralPath $VideoPath
    $safeStem = Get-SafeFolderName $item.BaseName
    if ([string]::IsNullOrWhiteSpace($safeStem)) {
        $safeStem = "source"
    }
    if ($safeStem.Length -gt 80) {
        $safeStem = $safeStem.Substring(0, 80).TrimEnd("_", "-", ".")
    }

    $hashInput = $item.FullName.Replace("\", "/").ToLowerInvariant()
    $sha1 = [System.Security.Cryptography.SHA1]::Create()
    try {
        $hashBytes = $sha1.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($hashInput))
    }
    finally {
        $sha1.Dispose()
    }
    $shortHash = -join ($hashBytes[0..4] | ForEach-Object { $_.ToString("x2") })
    return ("{0}-{1}" -f $safeStem, $shortHash)
}

function Get-BoundedTranscriptPhysicalSourceId {
    param(
        [string]$SourceId,
        [string]$OutputRoot,
        [int]$PathBudget = 240
    )

    if ([string]::IsNullOrWhiteSpace($SourceId)) {
        $SourceId = "source"
    }
    if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
        throw "A transcript output root is required before physical source paths can be budgeted."
    }

    $transcriptSourcesRoot = Join-Path (Join-Path $OutputRoot "transcript") "sources"
    $rawTranscriptSourcesRoot = Join-Path (Join-Path (Join-Path $OutputRoot "transcript") "raw") "sources"
    $audioRoot = Join-Path $OutputRoot "audio"
    $fixedPaths = @(
        (Join-Path $transcriptSourcesRoot ".transcript.quality.json"),
        (Join-Path $transcriptSourcesRoot ".transcript.raw.json"),
        (Join-Path $rawTranscriptSourcesRoot ".transcript.json"),
        (Join-Path $audioRoot ".audio.wav"),
        (Join-Path $audioRoot ".audio.flac")
    )
    $maxFixedLength = [int](($fixedPaths | Measure-Object -Property Length -Maximum).Maximum)
    $maxSourceIdLength = $PathBudget - $maxFixedLength
    if ($maxSourceIdLength -lt 16) {
        throw ("The selected output root is too long for safe transcript artifacts within the {0}-character Windows compatibility budget: {1}" -f $PathBudget, $OutputRoot)
    }
    if ($SourceId.Length -le $maxSourceIdLength) {
        return $SourceId
    }

    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $hashBytes = $sha256.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($SourceId))
    }
    finally {
        $sha256.Dispose()
    }
    $digest = -join ($hashBytes[0..5] | ForEach-Object { $_.ToString("x2") })
    $prefixLength = [math]::Max(1, $maxSourceIdLength - $digest.Length - 1)
    $prefix = $SourceId.Substring(0, [math]::Min($SourceId.Length, $prefixLength)).TrimEnd("_", "-", ".")
    if ([string]::IsNullOrWhiteSpace($prefix)) {
        $prefix = "s"
    }
    return ("{0}-{1}" -f $prefix, $digest)
}

function Get-TranscriptOnlySourceIdentifier {
    param(
        [string]$VideoPath,
        [string]$SourceRoot
    )

    $item = Get-Item -LiteralPath $VideoPath
    if ([string]::IsNullOrWhiteSpace($SourceRoot)) {
        return $item.Name
    }

    try {
        $sourceItem = Get-Item -LiteralPath $SourceRoot
        $basePath = if ($sourceItem.PSIsContainer) { $sourceItem.FullName } else { Split-Path -Path $sourceItem.FullName -Parent }
        $baseFull = [System.IO.Path]::GetFullPath($basePath)
        $fileFull = [System.IO.Path]::GetFullPath($item.FullName)
        if (-not $baseFull.EndsWith([System.IO.Path]::DirectorySeparatorChar)) {
            $baseFull = $baseFull + [System.IO.Path]::DirectorySeparatorChar
        }

        $baseUri = New-Object System.Uri $baseFull
        $fileUri = New-Object System.Uri $fileFull
        $relative = $baseUri.MakeRelativeUri($fileUri).ToString()
        if (-not [string]::IsNullOrWhiteSpace($relative)) {
            return [System.Uri]::UnescapeDataString($relative).Replace("/", [System.IO.Path]::DirectorySeparatorChar)
        }
    }
    catch {
    }

    return $item.Name
}

function Invoke-TranscriptOnlyIndexHelper {
    param(
        [string]$PythonCommand,
        [string]$OutputRoot,
        [array]$ManifestEntries,
        [string[]]$SearchTerms,
        [int]$HeartbeatSeconds = 10
    )

    $cliResult = Invoke-MediaManglersPythonCli `
        -PythonCommand $PythonCommand `
        -Command "transcript-only-index" `
        -Payload @{
            output_dir        = $OutputRoot
            manifest_entries = @($ManifestEntries)
            search_terms     = @($SearchTerms)
        } `
        -StepName "Transcript-only index" `
        -HeartbeatSeconds $HeartbeatSeconds `
        -TimeoutSeconds 300

    if (-not $cliResult) {
        throw "Tracked Python CLI helper is unavailable, so transcript-only indexes could not be written."
    }

    if ($cliResult.ExitCode -ne 0 -or -not $cliResult.Result -or -not $cliResult.Result.ok) {
        $message = if ($cliResult.Result -and -not [string]::IsNullOrWhiteSpace($cliResult.Result.error)) {
            [string]$cliResult.Result.error
        }
        else {
            "Tracked Python transcript-only helper failed before returning a result."
        }
        throw $message
    }

    return $cliResult.Result.data
}

function Invoke-ArchiveCatalogBuildHelper {
    param(
        [string]$PythonCommand,
        [string]$InputPath,
        [string]$OutputFolder,
        [string]$CatalogPath,
        [string]$SkipMarker,
        [string]$HashMode,
        [string]$ThumbnailMode,
        [int]$MaxThumbnailsPerVideo,
        [string]$S3Bucket,
        [string]$S3Prefix,
        [string]$NotesCsv,
        [switch]$ExportNotesTemplate,
        [string]$FFmpegExe,
        [string]$FFprobeExe,
        [int]$HeartbeatSeconds = 10
    )

    $payload = @{
        input_path               = $InputPath
        output_dir               = $OutputFolder
        catalog_path             = $CatalogPath
        skip_marker              = $SkipMarker
        hash_mode                = $HashMode
        thumbnail_mode           = $ThumbnailMode
        max_thumbnails_per_video = $MaxThumbnailsPerVideo
        s3_bucket                = $S3Bucket
        s3_prefix                = $S3Prefix
        notes_csv                = $NotesCsv
        export_notes_template    = [bool]$ExportNotesTemplate
        ffmpeg_path              = $FFmpegExe
        ffprobe_path             = $FFprobeExe
        media_mangler_version    = (Get-AppVersion)
    }

    $cliResult = Invoke-MediaManglersPythonCli `
        -PythonCommand $PythonCommand `
        -Command "archive-catalog-build" `
        -Payload $payload `
        -StepName "Archive catalog build" `
        -HeartbeatSeconds $HeartbeatSeconds `
        -TimeoutSeconds 7200

    if (-not $cliResult) {
        throw "Tracked Python CLI helper is unavailable, so the archive catalog could not be built."
    }

    if ($cliResult.ExitCode -ne 0 -or -not $cliResult.Result -or -not $cliResult.Result.ok) {
        $message = if ($cliResult.Result -and -not [string]::IsNullOrWhiteSpace($cliResult.Result.error)) {
            [string]$cliResult.Result.error
        }
        else {
            "Tracked Python archive catalog build helper failed before returning a result."
        }
        throw $message
    }

    return $cliResult.Result.data
}

function Invoke-ArchiveCatalogSearchHelper {
    param(
        [string]$PythonCommand,
        [string]$CatalogPath,
        [string]$Query,
        [int]$HeartbeatSeconds = 10
    )

    $cliResult = Invoke-MediaManglersPythonCli `
        -PythonCommand $PythonCommand `
        -Command "archive-catalog-search" `
        -Payload @{
            catalog_path = $CatalogPath
            query        = $Query
            limit        = 25
        } `
        -StepName "Archive catalog search" `
        -HeartbeatSeconds $HeartbeatSeconds `
        -TimeoutSeconds 300

    if (-not $cliResult) {
        throw "Tracked Python CLI helper is unavailable, so the archive catalog could not be searched."
    }

    if ($cliResult.ExitCode -ne 0 -or -not $cliResult.Result -or -not $cliResult.Result.ok) {
        $message = if ($cliResult.Result -and -not [string]::IsNullOrWhiteSpace($cliResult.Result.error)) {
            [string]$cliResult.Result.error
        }
        else {
            "Tracked Python archive catalog search helper failed before returning a result."
        }
        throw $message
    }

    return $cliResult.Result.data
}

function Invoke-ReviewLedgerHelper {
    param(
        [string]$PythonCommand,
        [ValidateSet("review-media-inbox-scan", "review-media-inbox-reconcile", "review-media-inbox-process", "review-media-inbox-prepare", "review-media-inbox-relocate", "review-media-inbox-targeted-plan", "review-media-inbox-targeted-complete", "review-media-inbox-import-results", "review-media-inbox-finalization-preview", "review-media-inbox-finalize", "review-media-inbox-finalization-status")]
        [string]$Command,
        [hashtable]$Payload,
        [int]$HeartbeatSeconds = 10
    )

    $progressStatePath = if ($Command -in @("review-media-inbox-prepare", "review-media-inbox-process")) {
        # 224 (Wave B2a): through the one scratch-folder rule, so a test run keeps it in its own folder.
        Get-MMScratchPath -Prefix "media_manglers_review_progress" -Extension ".json"
    }
    else {
        ""
    }
    if (-not [string]::IsNullOrWhiteSpace($progressStatePath)) {
        $Payload.progress_state_file_path = $progressStatePath
    }

    try {
        $cliResult = Invoke-MediaManglersPythonCli `
            -PythonCommand $PythonCommand `
            -Command $Command `
            -Payload $Payload `
            -StepName $Command `
            -HeartbeatSeconds $HeartbeatSeconds `
            -TimeoutSeconds $(if ($Command -in @("review-media-inbox-prepare", "review-media-inbox-process")) { 604800 } else { 1800 }) `
            -ProgressStateFilePath $progressStatePath
    }
    finally {
        if (-not [string]::IsNullOrWhiteSpace($progressStatePath) -and (Test-Path -LiteralPath $progressStatePath)) {
            Remove-Item -LiteralPath $progressStatePath -Force -ErrorAction SilentlyContinue
        }
    }

    if (-not $cliResult) {
        throw "Tracked Python CLI helper is unavailable, so review ledger operation '$Command' could not run."
    }

    if ($cliResult.ExitCode -ne 0 -or -not $cliResult.Result -or -not $cliResult.Result.ok) {
        $message = if ($cliResult.Result -and -not [string]::IsNullOrWhiteSpace($cliResult.Result.error)) {
            [string]$cliResult.Result.error
        }
        else {
            "Tracked Python review ledger helper failed before returning a result."
        }
        throw $message
    }

    return $cliResult.Result.data
}

function Write-ArchiveCatalogSearchResults {
    param([psobject]$SearchResult)

    $count = 0
    if ($SearchResult -and $SearchResult.results) {
        $count = @($SearchResult.results).Count
    }

    Write-Host ""
    Write-Host ("Archive catalog search: {0}" -f $SearchResult.query) -ForegroundColor Cyan
    Write-Host ("Catalog: {0}" -f $SearchResult.catalog_path) -ForegroundColor Cyan
    Write-Host ("Matches: {0}" -f $count) -ForegroundColor Cyan

    if ($count -eq 0) {
        Write-Host "No matches found." -ForegroundColor Yellow
        return
    }

    $index = 1
    foreach ($row in @($SearchResult.results)) {
        Write-Host ""
        Write-Host ("{0}. {1}" -f $index, $row.filename) -ForegroundColor Cyan
        Write-Host ("   Path:       {0}" -f $row.relative_path)
        Write-Host ("   S3 key:     {0}" -f $row.proposed_s3_key)
        Write-Host ("   Duration:   {0}" -f $row.duration)
        Write-Host ("   Size bytes: {0}" -f $row.size_bytes)
        Write-Host ("   Status:     {0}" -f $row.archive_status)
        Write-Host ("   Title:      {0}" -f $row.manual_title)
        Write-Host ("   Notes:      {0}" -f $row.manual_notes)
        Write-Host ("   Tags:       {0}" -f $row.manual_tags)
        Write-Host ("   Keywords:   {0}" -f $row.keywords)
        Write-Host ("   Contact:    {0}" -f $row.contact_sheet_path)
        $index += 1
    }
}

function ConvertTo-FfmpegSecondsText {
    param([double]$Seconds)

    return ([math]::Max(0.0, $Seconds)).ToString("0.###", [System.Globalization.CultureInfo]::InvariantCulture)
}

function Resolve-EvidenceFrameOffsets {
    param([string[]]$Values)

    $offsets = New-Object System.Collections.Generic.List[double]
    foreach ($value in @($Values)) {
        if ([string]::IsNullOrWhiteSpace([string]$value)) {
            continue
        }

        foreach ($part in ([string]$value).Split(",")) {
            if ([string]::IsNullOrWhiteSpace($part)) {
                continue
            }

            $parsed = 0.0
            if (-not [double]::TryParse($part.Trim(), [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$parsed)) {
                throw "EvidenceFrameOffsets values must be numeric seconds. Could not parse '$part'."
            }
            [void]$offsets.Add($parsed)
        }
    }

    if ($offsets.Count -eq 0) {
        throw "EvidenceFrameOffsets must contain at least one numeric offset."
    }

    return [double[]]$offsets.ToArray()
}

function Test-ThreePanelFrame {
    param(
        [int]$Width,
        [int]$Height
    )

    return ($Width -eq 5760 -and $Height -eq 1080)
}

function Get-ThreePanelDefinitions {
    return @(
        [PSCustomObject]@{ role = "overview_cam"; label = "Overview Cam"; crop_x = 0; crop_y = 0; crop_width = 1920; crop_height = 1080; crop_filter = "1920:1080:0:0" },
        [PSCustomObject]@{ role = "driver_view"; label = "Driver View"; crop_x = 1920; crop_y = 0; crop_width = 1920; crop_height = 1080; crop_filter = "1920:1080:1920:0" },
        [PSCustomObject]@{ role = "face_cam"; label = "Face Cam"; crop_x = 3840; crop_y = 0; crop_width = 1920; crop_height = 1080; crop_filter = "1920:1080:3840:0" }
    )
}

function Export-FullReviewPanelFrames {
    param(
        [string]$FFmpegExe,
        [string]$InputVideo,
        [string]$OutputRoot,
        [int]$SourceWidth,
        [int]$SourceHeight,
        [string]$Mode = "Auto",
        [double]$CadenceSeconds = 5,
        [bool]$UseGpu,
        [int]$HeartbeatSeconds = 10,
        [string]$PythonCommand = ""
    )

    $normalizedMode = if ([string]::IsNullOrWhiteSpace($Mode)) { "Auto" } else { (Get-Culture).TextInfo.ToTitleCase($Mode.Trim().ToLowerInvariant()) }
    $framesPanelsRoot = Join-Path $OutputRoot "frames_panels"
    $indexPath = Join-Path $framesPanelsRoot "panel_frame_index.csv"
    $manifestPath = Join-Path $framesPanelsRoot "panel_frame_manifest.json"
    $panelDefinitions = @(Get-ThreePanelDefinitions)
    $result = [ordered]@{
        status = "skipped"
        mode = $normalizedMode
        source_width = [int]$SourceWidth
        source_height = [int]$SourceHeight
        generated = $false
        skip_reason = ""
        cadence_seconds = [double]$CadenceSeconds
        frame_count = 0
        index_path = ""
        manifest_path = ""
        crop_geometry = @($panelDefinitions | ForEach-Object {
            [ordered]@{ role = [string]$_.role; label = [string]$_.label; crop = [string]$_.crop_filter }
        })
        panels = @($panelDefinitions | ForEach-Object {
            [ordered]@{
                role = [string]$_.role
                label = [string]$_.label
                crop = [string]$_.crop_filter
                directory = ""
                frame_count = 0
            }
        })
    }

    if ($normalizedMode -eq "Off") {
        $result.status = "disabled"
        $result.skip_reason = "FullReviewPanelCrops=Off."
        Write-Log "Full Review panel crops disabled by FullReviewPanelCrops=Off."
        return [PSCustomObject]$result
    }

    if (-not (Test-ThreePanelFrame -Width $SourceWidth -Height $SourceHeight)) {
        $result.status = "skipped"
        $result.skip_reason = ("Source dimensions {0}x{1} do not match exact 5760x1080 three-panel layout." -f $SourceWidth, $SourceHeight)
        Write-Log ("Full Review panel crops skipped: {0}" -f $result.skip_reason)
        return [PSCustomObject]$result
    }

    Ensure-Directory $framesPanelsRoot
    Test-FrameIntervalValue -Value $CadenceSeconds
    $panelResults = New-Object System.Collections.Generic.List[object]
    $indexRows = New-Object System.Collections.Generic.List[object]
    $maxFrameCount = 0

    foreach ($panel in $panelDefinitions) {
        $panelFolder = Join-Path $framesPanelsRoot ([string]$panel.role)
        Ensure-Directory $panelFolder
        Get-ChildItem -LiteralPath $panelFolder -Filter "*.jpg" -File -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue

        # 214: made by the one frame renderer, as every screenshot is: a GPU decode first when
        # asked, the CPU when that fails.
        $panelMade = $false
        try {
            $render = Invoke-MMFrameCadence -FFmpegExe $FFmpegExe -InputVideo $InputVideo -FramesFolder $panelFolder -UseGpu $UseGpu `
                -FrameIntervalSeconds $CadenceSeconds -Pattern (([string]$panel.role) + "_%06d.jpg") -KeepExisting $false `
                -AfterFps ("crop={0}:{1}:{2}:{3}" -f [int]$panel.crop_width, [int]$panel.crop_height, [int]$panel.crop_x, [int]$panel.crop_y) `
                -HeartbeatSeconds $HeartbeatSeconds -StepName ("Full Review panel frame extraction ({0})" -f [string]$panel.role) -PythonCommand $PythonCommand
            if (@($render.warnings).Count -gt 0) {
                Write-Log ("Full Review panel frame GPU extraction failed for {0}; falling back to CPU." -f [string]$panel.role) "WARN"
            }
            $panelMade = [bool]$render.ok
        }
        catch {
            if (Test-MMSkipException $_) { throw }
            Write-Log ("Full Review panel frames could not be made for {0}: {1}" -f [string]$panel.role, $_.Exception.Message) "WARN"
        }

        $files = @(Get-ChildItem -LiteralPath $panelFolder -Filter "*.jpg" -File -ErrorAction SilentlyContinue | Sort-Object Name)
        $status = if ($panelMade -and $files.Count -gt 0) { "created" } else { "failed" }
        if ($files.Count -gt $maxFrameCount) {
            $maxFrameCount = $files.Count
        }
        $relativePanelFolder = "frames_panels\{0}" -f [string]$panel.role
        [void]$panelResults.Add([ordered]@{
            role = [string]$panel.role
            label = [string]$panel.label
            crop = [string]$panel.crop_filter
            directory = $panelFolder
            relative_directory = $relativePanelFolder
            frame_count = [int]$files.Count
            status = $status
        })

        for ($i = 0; $i -lt $files.Count; $i++) {
            $timestamp = [math]::Round(([double]$i * [double]$CadenceSeconds), 3)
            [void]$indexRows.Add([PSCustomObject]@{
                frame_number = $i + 1
                timestamp_seconds = $timestamp
                panel_role = [string]$panel.role
                panel_label = [string]$panel.label
                crop = [string]$panel.crop_filter
                frame_path = ("frames_panels\{0}\{1}" -f [string]$panel.role, $files[$i].Name)
            })
        }
    }

    if ($indexRows.Count -gt 0) {
        $indexRows | Export-Csv -LiteralPath $indexPath -NoTypeInformation -Encoding UTF8
    }

    $result.status = if (@($panelResults | Where-Object { $_["status"] -eq "failed" }).Count -gt 0) { "partial" } else { "generated" }
    $result.generated = ($maxFrameCount -gt 0)
    $result.frame_count = [int]$maxFrameCount
    $result.index_path = $indexPath
    $result.manifest_path = $manifestPath
    $result.panels = @($panelResults.ToArray())
    $result.crop_geometry = @($panelDefinitions | ForEach-Object {
        [ordered]@{ role = [string]$_.role; label = [string]$_.label; crop = [string]$_.crop_filter }
    })

    ($result | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    Write-Log ("Full Review panel crops {0}: {1} synchronized frame slot(s) under {2}" -f $result.status, $result.frame_count, $framesPanelsRoot)
    return [PSCustomObject]$result
}

function Invoke-CodexEvidenceDetectHelper {
    param(
        [string]$PythonCommand,
        [string]$OutputRoot,
        [array]$Sources,
        [double]$PreContextSeconds,
        [double]$PostContextSeconds,
        [double]$NarrationContextPreSeconds,
        [double]$NarrationContextPostSeconds,
        [double]$NarrationPauseThresholdSeconds,
        [bool]$NarrationStopAtNextTicketBoundary,
        [bool]$FragmentedNarrationMode,
        [double[]]$FrameOffsets,
        [double]$FrameCadenceSeconds,
        [int]$MaxFramesPerCandidate,
        [int]$MaxItems,
        [array]$RenderCandidateIds = @(),
        [array]$RenderOutcomeIds = @(),
        [ValidateSet("Transcription", "Consolidation", "Package")]
        [string]$StopAfter = "Package",
        [ValidateSet("Compact", "Dense")]
        [string]$RenderDensity = "Compact",
        [ValidateSet("Auto", "Sparse", "Continuous")]
        [string]$SpeechMode = "Auto",
        [string]$ResumeRoot = "",
        [string]$HandoffMode = "Local",
        [int]$PortableZipMaxMb = 100,
        [string]$PanelCropMode = "Auto",
        [string]$InvocationMode = "standalone",
        [string]$TargetRepo = "",
        [string]$RepoMapPath = "",
        [string]$RepoHintMode = "auto",
        [array]$CustomMarkers = @(),
        [array]$CustomDomainTerms = @(),
        [string]$TranscriptionGlossaryPath = "",
        [array]$TranscriptionGlossaryEntries = @(),
        [bool]$PreserveSupportingAudio = $false,
        [string]$PanelRoleMapPath = "",
        [hashtable]$RunMetadata = @{},
        [int]$HeartbeatSeconds = 10
    )

    $cliResult = Invoke-MediaManglersPythonCli `
        -PythonCommand $PythonCommand `
        -Command "evidence-package-detect" `
        -Payload @{
            output_dir             = $OutputRoot
            sources                = @($Sources)
            pre_context_seconds    = $PreContextSeconds
            post_context_seconds   = $PostContextSeconds
            narration_context_pre_seconds = $NarrationContextPreSeconds
            narration_context_post_seconds = $NarrationContextPostSeconds
            narration_pause_threshold_seconds = $NarrationPauseThresholdSeconds
            narration_stop_at_next_ticket_boundary = $NarrationStopAtNextTicketBoundary
            fragmented_narration_mode = $FragmentedNarrationMode
            merge_gap_seconds      = 90
            frame_offsets_seconds  = @($FrameOffsets)
            frame_cadence_seconds  = $FrameCadenceSeconds
            max_frames_per_candidate = $MaxFramesPerCandidate
            max_items              = $MaxItems
            render_candidate_ids   = @($RenderCandidateIds)
            render_outcome_ids     = @($RenderOutcomeIds)
            stop_after             = $StopAfter
            render_density         = $RenderDensity
            evidence_handoff_mode  = $HandoffMode
            evidence_portable_zip_max_mb = $PortableZipMaxMb
            panel_crop_mode        = $PanelCropMode
            invocation_mode        = $InvocationMode
            target_repo            = $TargetRepo
            repo_map_path          = $RepoMapPath
            repo_hint_mode         = $RepoHintMode
            custom_markers         = @($CustomMarkers)
            custom_domain_terms    = @($CustomDomainTerms)
            transcription_glossary_path = $TranscriptionGlossaryPath
            transcription_glossary_entries = @($TranscriptionGlossaryEntries)
            preserve_supporting_audio = $PreserveSupportingAudio
            panel_role_map_path    = $PanelRoleMapPath
            run_metadata           = $RunMetadata
        } `
        -StepName "Codex evidence detection" `
        -HeartbeatSeconds $HeartbeatSeconds `
        -TimeoutSeconds 300

    if (-not $cliResult) {
        throw "Tracked Python CLI helper is unavailable, so Codex evidence detection could not run."
    }

    if ($cliResult.ExitCode -ne 0 -or -not $cliResult.Result -or -not $cliResult.Result.ok) {
        $message = if ($cliResult.Result -and -not [string]::IsNullOrWhiteSpace($cliResult.Result.error)) {
            [string]$cliResult.Result.error
        }
        else {
            "Tracked Python Codex evidence detection helper failed before returning a result."
        }
        throw $message
    }

    return $cliResult.Result.data
}

function Invoke-CodexEvidenceWriteHelper {
    param(
        [string]$PythonCommand,
        [string]$OutputRoot,
        [array]$Sources,
        [array]$Candidates,
        [array]$UnrenderedCandidates = @(),
        [array]$ReviewNeeded = @(),
        [array]$Outcomes = @(),
        [psobject]$Configuration,
        [int]$TruncatedCandidateCount,
        [array]$FrameResults,
        [array]$AudioResults,
        [int]$HeartbeatSeconds = 10
    )

    $cliResult = Invoke-MediaManglersPythonCli `
        -PythonCommand $PythonCommand `
        -Command "evidence-package-write" `
        -Payload @{
            output_dir                  = $OutputRoot
            sources                     = @($Sources)
            candidates                  = @($Candidates)
            unrendered_candidates       = @($UnrenderedCandidates)
            review_needed               = @($ReviewNeeded)
            outcomes                    = @($Outcomes)
            configuration               = $Configuration
            truncated_candidates_count  = $TruncatedCandidateCount
            artifact_results            = @{
                frames             = @($FrameResults)
                audio              = @($AudioResults)
                integrity_enforced = $true
            }
        } `
        -StepName "Codex evidence package writer" `
        -HeartbeatSeconds $HeartbeatSeconds `
        -TimeoutSeconds 300

    if (-not $cliResult) {
        throw "Tracked Python CLI helper is unavailable, so Codex evidence outputs could not be written."
    }

    if ($cliResult.ExitCode -ne 0 -or -not $cliResult.Result -or -not $cliResult.Result.ok) {
        $message = if ($cliResult.Result -and -not [string]::IsNullOrWhiteSpace($cliResult.Result.error)) {
            [string]$cliResult.Result.error
        }
        else {
            "Tracked Python Codex evidence writer failed before returning a result."
        }
        throw $message
    }

    return $cliResult.Result.data
}

function Export-CodexEvidenceAudioSnippet {
    param(
        [string]$FFmpegExe,
        [string]$InputVideo,
        [double]$StartSeconds,
        [double]$DurationSeconds,
        [string]$OutputAudio,
        [int]$AudioStreamIndex = 0,
        [int]$HeartbeatSeconds = 10
    )

    if ($DurationSeconds -le 0) {
        throw "Audio snippet duration is zero."
    }

    Ensure-Directory (Split-Path -Path $OutputAudio -Parent)
    $startText = ConvertTo-FfmpegSecondsText -Seconds $StartSeconds
    $durationText = ConvertTo-FfmpegSecondsText -Seconds $DurationSeconds
    $result = Invoke-ExternalCapture `
        -FilePath $FFmpegExe `
        -Arguments @("-y", "-ss", $startText, "-t", $durationText, "-i", $InputVideo, "-map", ("0:a:{0}" -f $AudioStreamIndex), "-vn", "-c:a", "libmp3lame", "-b:a", "192k", $OutputAudio) `
        -StepName "Codex evidence audio snippet" `
        -HeartbeatSeconds $HeartbeatSeconds `
        -IgnoreExitCode

    if ($result.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $OutputAudio)) {
        throw "Audio snippet extraction failed from $startText for $durationText seconds."
    }
}

function New-MMFailedFrameResult {
    # 214: a screenshot the one frame renderer could not make, with the reason.
    param($Task, [string]$Message, [string]$PanelMode = "auto")
    $panels = @(foreach ($panel in @($Task.panels)) {
        if ($null -eq $panel) { continue }
        [PSCustomObject]@{
            role = [string]$panel.role; label = [string]$panel.label; relative_path = [string]$panel.relative_path; path = [string]$panel.path
            crop_x = [int]$panel.crop_x; crop_y = [int]$panel.crop_y; crop_width = [int]$panel.crop_width; crop_height = [int]$panel.crop_height
            panel_image_width = ""; panel_image_height = ""; status = "failed"; error_message = ("Full frame extraction failed: {0}" -f $Message)
        }
    })
    return [PSCustomObject]@{
        evidence_id = [string]$Task.evidence_id; relative_path = [string]$Task.relative_path; path = [string]$Task.path; full_frame_path = [string]$Task.path
        full_frame_width = ""; full_frame_height = ""; panel_crop_mode = $PanelMode; panel_detection = "not_attempted"
        panels = $panels; status = "failed"; error_message = $Message
    }
}

function Invoke-MMFrameCadence {
    # 214: one screenshot every so many seconds, made by the one frame renderer.
    param(
        [string]$FFmpegExe,
        [string]$InputVideo,
        [string]$FramesFolder,
        [bool]$UseGpu,
        [double]$FrameIntervalSeconds,
        [string]$Pattern = "frame_%06d.jpg",
        [string]$AfterFps = "scale=1280:-2",
        [bool]$KeepExisting = $true,
        [int]$HeartbeatSeconds = 10,
        [string]$StepName = "Frame extraction",
        [string]$PythonCommand = ""
    )
    $cli = Invoke-MediaManglersPythonCli `
        -PythonCommand $(if ([string]::IsNullOrWhiteSpace($PythonCommand)) { [string]$PythonExe } else { $PythonCommand }) `
        -Command "frames-render" `
        -StepName $StepName `
        -HeartbeatSeconds $HeartbeatSeconds `
        -TimeoutSeconds 604800 `
        -Payload @{
            mode = "cadence"
            ffmpeg_exe = $FFmpegExe
            video_path = $InputVideo
            frames_dir = $FramesFolder
            interval_seconds = $FrameIntervalSeconds
            use_gpu = [bool]$UseGpu
            pattern = $Pattern
            after_fps = $AfterFps
            keep_existing = [bool]$KeepExisting
        }
    if ($null -eq $cli) {
        throw (Get-MediaManglersPythonCliUnavailableMessage -FeatureLabel "Screenshots")
    }
    if ($cli.ExitCode -ne 0 -or -not $cli.Result -or -not $cli.Result.ok) {
        $reason = if ($cli.Result -and -not [string]::IsNullOrWhiteSpace([string]$cli.Result.error)) { [string]$cli.Result.error } else { "the helper stopped before it said why" }
        throw ("The screenshots could not be made: {0}" -f $reason)
    }
    return $cli.Result.data
}

function Invoke-CodexEvidenceFrameTasks {
    param(
        [string]$FFmpegExe,
        [array]$FrameTasks,
        [int]$HeartbeatSeconds = 10,
        # 201: a longer gap between two screenshots starts a new batch.
        [double]$MaxGapSeconds = 10.0,
        # How these screenshots show on Queue / Progress.
        [string]$ProgressPhase = "Rich rendering",
        [int]$ProgressPhaseIndex = 4,
        [int]$ProgressPhaseCount = 4,
        # The Python that runs the one frame renderer; the backend's own when not given.
        [string]$PythonCommand = ""
    )
    # 214: every screenshot is made by the one frame renderer (media_manglers.core.frame_render):
    # batches of a short stretch each, and one frame at a time for a batch that fails.
    # Full Review runs these inside its own recording; give it back when done, so Skip still finds it.
    $mmOuterSourcePath = [string]$script:MMCurrentSourcePath

    $tasks = @($FrameTasks | Where-Object { $null -ne $_ })
    if ($tasks.Count -eq 0) {
        return @()
    }
    $results = New-Object System.Collections.Generic.List[object]
    $groups = @($tasks | Group-Object { "{0}|{1}" -f [string]$_.source_id, [string]$_.source_path })
    $artifactCompleted = 0
    $artifactTotal = $tasks.Count
    $sourceIndex = 0

    foreach ($group in $groups) {
        $sourceIndex += 1
        $sourceTasks = @($group.Group | Sort-Object {[double]$_.timestamp_seconds})
        $firstTask = $sourceTasks[0]
        $groupSourcePath = [string]$firstTask.source_path
        $sourceName = [System.IO.Path]::GetFileName($groupSourcePath)
        $script:MMCurrentSourcePath = $groupSourcePath
        $null = Wait-MMWhilePaused -Where "screenshots"
        if (Test-MMSourceSkipRequested -SourcePath $groupSourcePath) {
            # 114: no screenshots for a recording the operator skipped.
            foreach ($skippedTask in $sourceTasks) { [void]$results.Add((New-MMSkippedFrameResult -Task $skippedTask)); $artifactCompleted += 1 }
            continue
        }
        $panelMode = if ($null -ne $firstTask.PSObject.Properties["panel_crop_mode"] -and -not [string]::IsNullOrWhiteSpace([string]$firstTask.panel_crop_mode)) {
            ([string]$firstTask.panel_crop_mode).Trim().ToLowerInvariant()
        }
        else {
            "auto"
        }
        $moments = @(foreach ($task in $sourceTasks) {
            @{
                timestamp_seconds = [double]$task.timestamp_seconds
                path = [string]$task.path
                name = [string]$task.relative_path
                panels = @(foreach ($panel in @($task.panels)) {
                    if ($null -eq $panel) { continue }
                    @{ role = [string]$panel.role; path = [string]$panel.path; crop_x = [int]$panel.crop_x; crop_y = [int]$panel.crop_y; crop_width = [int]$panel.crop_width; crop_height = [int]$panel.crop_height }
                })
            }
        })
        Write-MMProgressV1 -Phase $ProgressPhase -PhaseIndex $ProgressPhaseIndex -PhaseCount $ProgressPhaseCount -SourceId ([string]$firstTask.source_id) -SourceName $sourceName -Completed $artifactCompleted -Total $artifactTotal -SourceCompleted ($sourceIndex - 1) -SourceTotal $groups.Count -ArtifactCompleted $artifactCompleted -ArtifactTotal $artifactTotal -ProgressKind work_units -Activity ("Rendering {0} screenshot(s)" -f $sourceTasks.Count)
        $progressPath = Get-MMScratchPath -Prefix "media_manglers_frames_progress" -Extension ".json"
        try {
            $cli = Invoke-MediaManglersPythonCli `
                -PythonCommand $(if ([string]::IsNullOrWhiteSpace($PythonCommand)) { [string]$PythonExe } else { $PythonCommand }) `
                -Command "frames-render" `
                -StepName ("Screenshots for {0}" -f $sourceName) `
                -HeartbeatSeconds $HeartbeatSeconds `
                -TimeoutSeconds 604800 `
                -ProgressStateFilePath $progressPath `
                -Payload @{
                    mode = "moments"
                    ffmpeg_exe = $FFmpegExe
                    source_path = $groupSourcePath
                    panel_mode = $panelMode
                    max_gap_seconds = $MaxGapSeconds
                    moments = $moments
                    progress_file = $progressPath
                    progress = @{
                        phase = $ProgressPhase; phase_index = $ProgressPhaseIndex; phase_count = $ProgressPhaseCount
                        source_id = [string]$firstTask.source_id; source_name = $sourceName
                        source_completed = ($sourceIndex - 1); source_total = $groups.Count
                        artifact_completed = $artifactCompleted; artifact_total = $artifactTotal
                    }
                }
            if ($null -eq $cli) {
                throw (Get-MediaManglersPythonCliUnavailableMessage -FeatureLabel "Screenshots")
            }
            if ($cli.ExitCode -ne 0 -or -not $cli.Result -or -not $cli.Result.ok) {
                $reason = if ($cli.Result -and -not [string]::IsNullOrWhiteSpace([string]$cli.Result.error)) { [string]$cli.Result.error } else { "the helper stopped before it said why" }
                throw ("The screenshots could not be made: {0}" -f $reason)
            }
            $made = @($cli.Result.data.results)
            $reusedCount = 0
            for ($i = 0; $i -lt $sourceTasks.Count; $i++) {
                $task = $sourceTasks[$i]
                $frame = $made[$i]
                foreach ($warning in @($frame.warnings)) {
                    if (-not [string]::IsNullOrWhiteSpace([string]$warning)) { Write-Log ([string]$warning) "WARN" }
                }
                if ([bool]$frame.reused) { $reusedCount += 1 }
                $taskPanels = @($task.panels | Where-Object { $null -ne $_ })
                $madePanels = @($frame.panels)
                $panelResults = @(for ($j = 0; $j -lt $taskPanels.Count; $j++) {
                    $panel = $taskPanels[$j]
                    $madePanel = if ($j -lt $madePanels.Count) { $madePanels[$j] } else { $null }
                    $panelWidth = if ($null -ne $madePanel -and [int]$madePanel.width -gt 0) { [int]$madePanel.width } else { "" }
                    $panelHeight = if ($null -ne $madePanel -and [int]$madePanel.height -gt 0) { [int]$madePanel.height } else { "" }
                    [PSCustomObject]@{
                        role = [string]$panel.role; label = [string]$panel.label; relative_path = [string]$panel.relative_path; path = [string]$panel.path
                        crop_x = [int]$panel.crop_x; crop_y = [int]$panel.crop_y; crop_width = [int]$panel.crop_width; crop_height = [int]$panel.crop_height
                        panel_image_width = $panelWidth; panel_image_height = $panelHeight
                        status = $(if ($null -ne $madePanel) { [string]$madePanel.status } else { "failed" }); error_message = $(if ($null -ne $madePanel) { [string]$madePanel.error } else { "Not rendered." })
                    }
                })
                $created = ([string]$frame.status -eq "created")
                $result = [ordered]@{
                    evidence_id = [string]$task.evidence_id; relative_path = [string]$task.relative_path; path = [string]$task.path; full_frame_path = [string]$task.path
                    full_frame_width = $(if ($created) { [int]$frame.width } else { "" }); full_frame_height = $(if ($created) { [int]$frame.height } else { "" }); panel_crop_mode = $panelMode
                    panel_detection = [string]$frame.panel_detection
                    panels = $panelResults; status = [string]$frame.status; error_message = [string]$frame.error
                }
                if ([string]$frame.method -eq "batch") {
                    $result.extraction_batch_size = [int]$frame.batch_size
                    $result.extraction_batch_seek_seconds = [double]$frame.batch_seek_seconds
                }
                [void]$results.Add([PSCustomObject]$result)
                $artifactCompleted += 1
            }
            if ($reusedCount -gt 0) {
                Write-Log ("Reusing {0} screenshot(s) an earlier run of this package already made." -f $reusedCount)
            }
            Write-MMProgressV1 -Phase $ProgressPhase -PhaseIndex $ProgressPhaseIndex -PhaseCount $ProgressPhaseCount -SourceId ([string]$firstTask.source_id) -SourceName $sourceName -Completed $artifactCompleted -Total $artifactTotal -SourceCompleted $sourceIndex -SourceTotal $groups.Count -ArtifactCompleted $artifactCompleted -ArtifactTotal $artifactTotal -ProgressKind work_units -Activity "Created full and panel evidence frame" -LatestArtifactPath ([string]$sourceTasks[-1].path)
        }
        catch {
            if ((Test-MMSkipException $_) -or (Test-MMSourceSkipRequested -SourcePath $groupSourcePath)) {
                $script:MMSkipRequested = $false
                # 214: the operator's own choice, not a warning.
                Write-Log ("Screenshots skipped by you for {0}." -f $sourceName) "INFO"
                foreach ($skippedTask in $sourceTasks) { [void]$results.Add((New-MMSkippedFrameResult -Task $skippedTask)); $artifactCompleted += 1 }
                continue
            }
            $message = $_.Exception.Message
            Write-Log ("Screenshots could not be made for {0}: {1}" -f $sourceName, $message) "WARN"
            foreach ($failedTask in $sourceTasks) { [void]$results.Add((New-MMFailedFrameResult -Task $failedTask -Message $message -PanelMode $panelMode)); $artifactCompleted += 1 }
        }
        finally {
            if (Test-Path -LiteralPath $progressPath) { Remove-Item -LiteralPath $progressPath -Force -ErrorAction SilentlyContinue }
        }
    }
    $script:MMCurrentSourcePath = $mmOuterSourcePath
    return @($results.ToArray())
}

function Invoke-CodexEvidenceAudioTasksLegacy {
    param(
        [string]$FFmpegExe,
        [array]$AudioTasks,
        [int]$HeartbeatSeconds = 10
    )

    $results = New-Object System.Collections.Generic.List[object]
    foreach ($task in @($AudioTasks)) {
        if ($null -eq $task) {
            continue
        }

        $status = "failed"
        $errorMessage = ""
        $outputPath = [string]$task.path
        $inputMediaPath = if (-not [string]::IsNullOrWhiteSpace([string]$task.audio_input_path)) {
            [string]$task.audio_input_path
        }
        else {
            [string]$task.source_path
        }
        try {
            Export-CodexEvidenceAudioSnippet `
                -FFmpegExe $FFmpegExe `
                -InputVideo $inputMediaPath `
                -StartSeconds ([double]$task.start_seconds) `
                -DurationSeconds ([double]$task.duration_seconds) `
                -OutputAudio $outputPath `
                -AudioStreamIndex $(if ($null -ne $task.PSObject.Properties["audio_stream_index"]) { [int]$task.audio_stream_index } else { 0 }) `
                -HeartbeatSeconds $HeartbeatSeconds
            $status = "created"
        }
        catch {
            $errorMessage = $_.Exception.Message
            Write-Log ("Codex evidence audio snippet extraction failed for {0}: {1}" -f [string]$task.relative_path, $errorMessage) "WARN"
        }

        [void]$results.Add([PSCustomObject]@{
            evidence_id   = [string]$task.evidence_id
            relative_path = [string]$task.relative_path
            path          = $outputPath
            status        = $status
            error_message = $errorMessage
        })
    }

    return @($results.ToArray())
}

function Invoke-CodexEvidenceAudioTasks {
    param(
        [string]$FFmpegExe,
        [array]$AudioTasks,
        [int]$HeartbeatSeconds = 10,
        # 224 (Wave B2a): Review Media Inbox's targeted evidence writes each snippet straight to its place in
        # the request's staging folder, on the Inbox's drive, so nothing is moved here: the Python helper then
        # promotes the whole folder with its antivirus-safe move.
        [switch]$WriteInPlace
    )
    # 214: Full Review runs these inside its own recording; give it back when done, so Skip still finds it.
    $mmOuterSourcePath = [string]$script:MMCurrentSourcePath
    $tasks = @($AudioTasks | Where-Object { $null -ne $_ })
    if ($tasks.Count -eq 0) { return @() }
    $results = New-Object System.Collections.Generic.List[object]
    $groups = @($tasks | Group-Object {
        $inputPath = if (-not [string]::IsNullOrWhiteSpace([string]$_.audio_input_path)) { [string]$_.audio_input_path } else { [string]$_.source_path }
        $ordinal = if ($null -ne $_.PSObject.Properties["audio_stream_index"]) { [int]$_.audio_stream_index } else { 0 }
        "{0}|{1}" -f $inputPath, $ordinal
    })
    foreach ($group in $groups) {
        $batch = @($group.Group)
        $first = $batch[0]
        $inputPath = if (-not [string]::IsNullOrWhiteSpace([string]$first.audio_input_path)) { [string]$first.audio_input_path } else { [string]$first.source_path }
        $ordinal = if ($null -ne $first.PSObject.Properties["audio_stream_index"]) { [int]$first.audio_stream_index } else { 0 }
        $script:MMCurrentSourcePath = [string]$first.source_path
        $null = Wait-MMWhilePaused -Where "audio snippets"
        if (Test-MMSourceSkipRequested -SourcePath ([string]$first.source_path)) {
            foreach ($task in $batch) { [void]$results.Add((New-MMSkippedArtifactResult -Task $task)) }
            continue
        }
        $alreadyMade = @($batch | Where-Object { -not (Test-MMNonEmptyFile -Path ([string]$_.path)) }).Count -eq 0
        if ($alreadyMade) {
            # 115: a resumed run keeps the snippets an earlier run made.
            foreach ($task in $batch) {
                [void]$results.Add([PSCustomObject]@{
                    evidence_id = [string]$task.evidence_id; relative_path = [string]$task.relative_path; path = [string]$task.path
                    status = "created"; error_message = ""; extraction_batch_size = $batch.Count
                })
            }
            continue
        }
        $batchRoot = Get-MMScratchPath -Prefix "media_manglers_evidence_audio"
        try {
            Ensure-Directory $batchRoot
            $filterPath = Join-Path $batchRoot "audio.filter"
            $labels = @(for ($i = 0; $i -lt $batch.Count; $i++) { "[src$i]" }) -join ""
            $lines = New-Object System.Collections.Generic.List[string]
            [void]$lines.Add(("[0:a:{0}]asplit={1}{2};" -f $ordinal, $batch.Count, $labels))
            for ($i = 0; $i -lt $batch.Count; $i++) {
                $start = ConvertTo-FfmpegSecondsText -Seconds ([double]$batch[$i].start_seconds)
                $end = ConvertTo-FfmpegSecondsText -Seconds ([double]$batch[$i].start_seconds + [double]$batch[$i].duration_seconds)
                [void]$lines.Add(("[src{0}]atrim=start={1}:end={2},asetpts=PTS-STARTPTS[a{0}];" -f $i, $start, $end))
                Ensure-Directory (Split-Path -Path ([string]$batch[$i].path) -Parent)
            }
            [System.IO.File]::WriteAllText($filterPath, ($lines -join [Environment]::NewLine), (New-Object System.Text.UTF8Encoding($false)))
            $arguments = New-Object System.Collections.Generic.List[string]
            foreach ($value in @("-y", "-i", $inputPath, "-filter_complex_script", $filterPath)) { [void]$arguments.Add($value) }
            for ($i = 0; $i -lt $batch.Count; $i++) {
                $snippetTemp = if ($WriteInPlace) { [string]$batch[$i].path } else { Join-Path $batchRoot ("snippet-{0:d4}.mp3" -f ($i + 1)) }
                foreach ($value in @("-map", "[a$i]", "-c:a", "libmp3lame", "-b:a", "192k", $snippetTemp)) { [void]$arguments.Add($value) }
            }
            $capture = Invoke-ExternalCapture -FilePath $FFmpegExe -Arguments @($arguments.ToArray()) -StepName ("Codex evidence source audio batch ({0} snippets)" -f $batch.Count) -HeartbeatSeconds $HeartbeatSeconds -IgnoreExitCode
            if ($capture.ExitCode -ne 0) { throw "Batched source audio extraction failed." }
            if (-not $WriteInPlace) {
                for ($i = 0; $i -lt $batch.Count; $i++) {
                    $snippetTemp = Join-Path $batchRoot ("snippet-{0:d4}.mp3" -f ($i + 1))
                    if (-not (Test-Path -LiteralPath $snippetTemp -PathType Leaf)) { throw "Batched source audio output was not created." }
                    Move-Item -LiteralPath $snippetTemp -Destination ([string]$batch[$i].path) -Force
                }
            }
            foreach ($task in $batch) {
                if (-not (Test-Path -LiteralPath ([string]$task.path) -PathType Leaf)) { throw "Batched source audio output was not created." }
                [void]$results.Add([PSCustomObject]@{
                    evidence_id = [string]$task.evidence_id; relative_path = [string]$task.relative_path; path = [string]$task.path
                    status = "created"; error_message = ""; extraction_batch_size = $batch.Count
                })
            }
        }
        catch {
            if ((Test-MMSkipException $_) -or (Test-MMSourceSkipRequested -SourcePath ([string]$first.source_path))) {
                $script:MMSkipRequested = $false
                foreach ($task in $batch) { [void]$results.Add((New-MMSkippedArtifactResult -Task $task)) }
                continue
            }
            Write-Log ("Batched evidence audio extraction failed; using the compatible per-snippet path. {0}" -f $_.Exception.Message) "WARN"
            foreach ($item in @(Invoke-CodexEvidenceAudioTasksLegacy -FFmpegExe $FFmpegExe -AudioTasks $batch -HeartbeatSeconds $HeartbeatSeconds)) { [void]$results.Add($item) }
        }
        finally {
            if (Test-Path -LiteralPath $batchRoot) { Remove-Item -LiteralPath $batchRoot -Recurse -Force -ErrorAction SilentlyContinue }
        }
    }
    $script:MMCurrentSourcePath = $mmOuterSourcePath
    return @($results.ToArray())
}

function Get-ReviewInboxWorkspace {
    # 224 (Wave B1): the Inbox's folder, worked out in this one place, as inbox_records.workspace does it in
    # Python: the folder that holds the ledger the settings name. Nothing moves on disk.
    param([string]$LedgerPath)

    if ([string]::IsNullOrWhiteSpace($LedgerPath)) {
        throw "Review Media Inbox needs a ledger path."
    }
    return (Split-Path -Parent $LedgerPath.Trim())
}

function Open-ReviewInboxProcessLock {
    # 224 (Wave B1): the Inbox's one lock, <workspace>\.orchestration\process.lock, held with no sharing; the
    # Process loop and the TargetedEvidence action both take it here. $null when another run holds it. The handle
    # is released when the caller disposes it or this process ends.
    param([string]$LedgerPath)

    $lockRoot = Join-Path (Get-ReviewInboxWorkspace -LedgerPath $LedgerPath) ".orchestration"
    New-Item -ItemType Directory -Path $lockRoot -Force | Out-Null
    $lockPath = Join-Path $lockRoot "process.lock"
    try {
        $lock = [System.IO.File]::Open(
            $lockPath,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
    }
    catch [System.IO.IOException] {
        # 224 (Wave B2a, note 7): only another run holding the file (a sharing or lock violation) is busy;
        # anything else says what Windows refused.
        $refusal = $_.Exception
        while ($refusal -isnot [System.IO.IOException] -and $null -ne $refusal.InnerException) { $refusal = $refusal.InnerException }
        $code = $refusal.HResult -band 0xFFFF
        if ($code -eq 32 -or $code -eq 33) {
            return $null
        }
        throw ("Windows refused to open the Inbox's lock file ({0}), so nothing was done. ({1})" -f ([string]$refusal.Message).Trim().TrimEnd('.'), $lockPath)
    }
    catch [System.UnauthorizedAccessException] {
        # 224 (Wave B2a review, note 7): "access denied" (a read-only lock file, a folder this account may not
        # change) is said plainly too.
        $refusal = $_.Exception
        while ($refusal -isnot [System.UnauthorizedAccessException] -and $null -ne $refusal.InnerException) { $refusal = $refusal.InnerException }
        throw ("Windows refused to open the Inbox's lock file ({0}), so nothing was done. ({1})" -f ([string]$refusal.Message).Trim().TrimEnd('.'), $lockPath)
    }
    try {
        $lock.SetLength(0)
        $record = @{
            schema_version = 1
            token = [guid]::NewGuid().ToString("N")
            process_id = $PID
            created_utc = [DateTime]::UtcNow.ToString("o")
        } | ConvertTo-Json -Compress
        $recordBytes = [System.Text.Encoding]::UTF8.GetBytes($record)
        $lock.Write($recordBytes, 0, $recordBytes.Length)
        $lock.Flush($true)
    }
    catch {
        # The caller never receives a handle it could release, so it is released here.
        $lock.Dispose()
        throw
    }
    return $lock
}

function Wait-ReviewInboxProcessLock {
    # 224 (Wave B2a, item 4): the TargetedEvidence action, like the command-line writers, tries again every quarter
    # second for up to ten seconds while the Workbench's short status check holds the lock; $null after that. The
    # Process loop, whose lock the app holds itself, never waits.
    param([string]$LedgerPath, [double]$Seconds = 10)

    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    while ($true) {
        $lock = Open-ReviewInboxProcessLock -LedgerPath $LedgerPath
        if ($null -ne $lock) {
            return $lock
        }
        if ([DateTime]::UtcNow -ge $deadline) {
            return $null
        }
        Start-Sleep -Milliseconds 250
    }
}

function Invoke-ReviewInboxTargetedEvidence {
    param(
        [string]$PythonCommand,
        [string]$LedgerPath,
        [string]$BatchId,
        [string]$PreliminarySubmissionSha256 = "",
        [string]$FFmpegExe,
        [string]$StopAfterCurrentRequestPath = "",
        [int]$HeartbeatSeconds = 10,
        # 224 (Wave B1): the caller already holds the Inbox's lock (the Process loop, or the TargetedEvidence
        # action), so the plan and complete helpers must not take it again.
        [switch]$CoordinatorLockHeld
    )

    if ([string]::IsNullOrWhiteSpace($BatchId)) {
        throw "Targeted evidence requires -ReviewInboxResumeBatchId for the accepted preliminary-findings batch."
    }

    $planPayload = @{
        ledger_path = $LedgerPath
        expected_batch_id = $BatchId
        preliminary_submission_sha256 = $PreliminarySubmissionSha256
        coordinator_lock_held = [bool]$CoordinatorLockHeld
    }
    $plan = Invoke-ReviewLedgerHelper `
        -PythonCommand $PythonCommand `
        -Command "review-media-inbox-targeted-plan" `
        -Payload $planPayload `
        -HeartbeatSeconds $HeartbeatSeconds

    if ([string]$plan.status -eq "targeted_evidence_ready") {
        return $plan
    }

    $requestPlans = @($plan.request_plans | Where-Object { $null -ne $_ })
    $pendingPlans = @($requestPlans | Where-Object { -not [bool]$_.existing_complete })
    $frameResults = New-Object System.Collections.Generic.List[object]
    $audioResults = New-Object System.Collections.Generic.List[object]
    $processedSignatures = New-Object System.Collections.Generic.List[string]
    $requestIndex = 0
    $cooperativeStop = $false

    foreach ($requestPlan in $pendingPlans) {
        if (
            -not [string]::IsNullOrWhiteSpace($StopAfterCurrentRequestPath) -and
            (Test-Path -LiteralPath $StopAfterCurrentRequestPath)
        ) {
            $cooperativeStop = $true
            break
        }

        $requestIndex += 1
        $sourceName = [System.IO.Path]::GetFileName([string]$requestPlan.source_verification_before.source_path)
        $outcomeId = "{0}/{1}" -f [string]$requestPlan.finding_id, [string]$requestPlan.request_id
        $artifactTotal = @($requestPlan.frame_tasks).Count + @($requestPlan.audio_tasks).Count
        $evidenceTypes = New-Object System.Collections.Generic.List[string]
        if (@($requestPlan.frame_tasks | Where-Object { [bool]$_.retain_full_frame }).Count -gt 0) { [void]$evidenceTypes.Add("frames") }
        if (@($requestPlan.frame_tasks | Where-Object { @($_.panels).Count -gt 0 }).Count -gt 0) { [void]$evidenceTypes.Add("panels") }
        if (@($requestPlan.audio_tasks).Count -gt 0) { [void]$evidenceTypes.Add("audio") }
        $artifactId = @($evidenceTypes.ToArray()) -join "+"
        Write-MMProgressV1 `
            -Phase "Targeted evidence" `
            -PhaseIndex 1 `
            -PhaseCount 1 `
            -SourceId ([string]$requestPlan.source_token) `
            -SourceName $sourceName `
            -OutcomeId $outcomeId `
            -ArtifactId $artifactId `
            -Completed ($requestIndex - 1) `
            -Total $pendingPlans.Count `
            -ArtifactCompleted 0 `
            -ArtifactTotal $artifactTotal `
            -ProgressKind work_units `
            -Activity ("Rendering targeted request {0} of {1}" -f $requestIndex, $pendingPlans.Count)

        # 214: the shared screenshot and clip makers, as every other feature uses.
        foreach ($item in @(Invoke-CodexEvidenceFrameTasks -FFmpegExe $FFmpegExe -FrameTasks @($requestPlan.frame_tasks) -HeartbeatSeconds $HeartbeatSeconds -ProgressPhase "Targeted evidence" -ProgressPhaseIndex 1 -ProgressPhaseCount 1 -PythonCommand $PythonCommand)) {
            [void]$frameResults.Add($item)
        }
        foreach ($item in @(Invoke-CodexEvidenceAudioTasks -FFmpegExe $FFmpegExe -AudioTasks @($requestPlan.audio_tasks) -HeartbeatSeconds $HeartbeatSeconds -WriteInPlace)) {
            [void]$audioResults.Add($item)
        }
        [void]$processedSignatures.Add([string]$requestPlan.render_signature)

        Write-MMProgressV1 `
            -Phase "Targeted evidence" `
            -PhaseIndex 1 `
            -PhaseCount 1 `
            -SourceId ([string]$requestPlan.source_token) `
            -SourceName $sourceName `
            -OutcomeId $outcomeId `
            -ArtifactId $artifactId `
            -Completed $requestIndex `
            -Total $pendingPlans.Count `
            -ArtifactCompleted $artifactTotal `
            -ArtifactTotal $artifactTotal `
            -ProgressKind work_units `
            -Activity "Targeted request render finished" `
            -LatestArtifactPath ([string]$requestPlan.stage_root)

        if (
            -not [string]::IsNullOrWhiteSpace($StopAfterCurrentRequestPath) -and
            (Test-Path -LiteralPath $StopAfterCurrentRequestPath)
        ) {
            $cooperativeStop = $true
            break
        }
    }

    $completePayload = @{
        plan_path = [string]$plan.plan_path
        plan_sha256 = [string]$plan.plan_sha256
        frame_results = @($frameResults.ToArray())
        audio_results = @($audioResults.ToArray())
        processed_request_signatures = @($processedSignatures.ToArray())
        cooperative_stop = $cooperativeStop
        coordinator_lock_held = [bool]$CoordinatorLockHeld
    }
    $result = Invoke-ReviewLedgerHelper `
        -PythonCommand $PythonCommand `
        -Command "review-media-inbox-targeted-complete" `
        -Payload $completePayload `
        -HeartbeatSeconds $HeartbeatSeconds

    $terminalState = if ([string]$result.status -eq "targeted_evidence_ready") { "succeeded" } elseif ($cooperativeStop) { "cancelled" } else { "failed" }
    Write-MMProgressV1 `
        -Phase "Targeted evidence" `
        -PhaseIndex 1 `
        -PhaseCount 1 `
        -Completed ([int]$result.completed_request_count) `
        -Total ([int]$result.request_count) `
        -ProgressKind work_units `
        -Activity ("Targeted evidence finished with status: {0}" -f [string]$result.status) `
        -LatestArtifactPath ([string]$result.batch_path) `
        -TerminalState $terminalState
    return $result
}

function Invoke-TranscriptOnlyBatch {
    param(
        [string]$InputPath,
        [string]$OutputFolder,
        [string]$PythonCommand,
        [string]$FFmpegExe,
        [string]$FFprobeExe,
        [string]$ModelName,
        [string]$LanguageCode,
        [bool]$CanUseWhisperGpu,
        [int]$WhisperTimeoutSeconds = 0,
        [int]$HeartbeatSeconds = 10,
        [switch]$TranscriptOnlyRecurse,
        [switch]$OverwriteTranscripts,
        [switch]$KeepAudio,
        [string[]]$SearchTerms = @(),
        # 214: the track choice, as Package any video for AI's: Auto finds the narration track the
        # shared way; Track (with a track number or stream) overrides it.
        [string]$TranscriptAudioMode = "Auto",
        [string]$TranscriptAudioStream = "",
        [int]$TranscriptAudioTrackOrdinal = 0,
        [string]$TrackRolesText = ""
    )

    if ([string]::IsNullOrWhiteSpace($InputPath)) {
        throw "Transcript-only mode needs a local source file or folder."
    }

    $sourcePath = Normalize-UserPath $InputPath
    if (-not (Test-Path -LiteralPath $sourcePath)) {
        throw "Transcript-only source path not found: $sourcePath"
    }

    $sourceItem = Get-Item -LiteralPath $sourcePath
    $videos = @(Get-VideoFilesFromPath -Path $sourcePath -Recurse:$TranscriptOnlyRecurse)
    if (-not $videos -or $videos.Count -eq 0) {
        throw "No supported video files found for transcript-only mode. Supported extensions include .mkv."
    }
    $videos = @(Select-MMDistinctVideos -Videos $videos)

    $outputRoot = Join-Path $OutputFolder "transcript-only"
    $transcriptsFolder = Join-Path $outputRoot "transcripts"
    $audioFolder = Join-Path $outputRoot "audio"
    Ensure-Directory $outputRoot
    Ensure-Directory $transcriptsFolder
    if ($KeepAudio) {
        Ensure-Directory $audioFolder
    }

    $script:CurrentLogFile = Join-Path $outputRoot "transcript_only_run.log"
    "==== Transcript-only run started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====" | Set-Content -LiteralPath $script:CurrentLogFile -Encoding UTF8

    Write-Phase -Name "Transcript-Only" -Detail ("Processing {0} local video item(s)" -f $videos.Count)
    Write-Log ("Transcript-only source: {0}" -f $sourcePath)
    Write-Log ("Transcript-only output: {0}" -f $outputRoot)
    Write-Log ("Transcript-only recurse: {0}" -f ([bool]$TranscriptOnlyRecurse))
    Write-Log ("Transcript overwrite: {0}" -f ([bool]$OverwriteTranscripts))
    Write-Log ("Transcript-only audio extraction: {0}" -f ([bool]$KeepAudio))

    $manifestEntries = New-Object System.Collections.Generic.List[object]
    $sourceRoot = if ($sourceItem.PSIsContainer) { $sourceItem.FullName } else { Split-Path -Path $sourceItem.FullName -Parent }
    $processedIndex = 0

    foreach ($video in $videos) {
        $processedIndex += 1
        $sourceId = Get-TranscriptOnlySourceId -VideoPath $video.FullName
        $sourceIdentifier = Get-TranscriptOnlySourceIdentifier -VideoPath $video.FullName -SourceRoot $sourceRoot
        $jsonPath = Join-Path $transcriptsFolder ("{0}.transcript.json" -f $sourceId)
        $srtPath = Join-Path $transcriptsFolder ("{0}.transcript.srt" -f $sourceId)
        $txtPath = Join-Path $transcriptsFolder ("{0}.transcript.txt" -f $sourceId)
        $audioPath = if ($KeepAudio) { Join-Path $audioFolder ("{0}.audio.mp3" -f $sourceId) } else { "" }
        $audioStatus = if ($KeepAudio) { "pending" } else { "not_requested" }
        $audioErrorMessage = ""
        $status = "failed"
        $errorMessage = ""
        $durationSeconds = ""
        $noNarrationDetected = $false

        Write-Host ("[{0}/{1}] Transcript-only: {2}" -f $processedIndex, $videos.Count, $video.Name) -ForegroundColor Cyan
        Write-Log ("Transcript-only item {0}/{1}: {2}" -f $processedIndex, $videos.Count, $video.FullName)
        # 214: Pause and Skip from Queue / Progress, as Find my bug reports has them.
        $script:MMCurrentSourcePath = $video.FullName
        $script:MMSkipRequested = $false

        try {
            $null = Invoke-MMRunControlCheck -StepName "the next recording"
            try {
                $durationValue = Get-VideoDurationSeconds -FFprobeExe $FFprobeExe -VideoPath $video.FullName
                if ($durationValue -gt 0) {
                    $durationSeconds = ([math]::Round($durationValue, 3)).ToString([System.Globalization.CultureInfo]::InvariantCulture)
                }
            }
            catch {
                Write-Log ("Duration probe failed for transcript-only item '{0}': {1}" -f $video.FullName, $_.Exception.Message) "WARN"
            }

            # The kept MP3 is an output for the operator; the transcript is made from the narration WAV.
            if ($KeepAudio) {
                try {
                    if ((Test-Path -LiteralPath $audioPath) -and -not $OverwriteTranscripts) {
                        $audioStatus = "skipped"
                        Write-Log ("Skipping existing transcript-only audio file for {0}" -f $video.FullName)
                    }
                    else {
                        if ((Test-Path -LiteralPath $audioPath) -and $OverwriteTranscripts) {
                            Remove-Item -LiteralPath $audioPath -Force -ErrorAction SilentlyContinue
                        }

                        $null = Export-AudioMp3 `
                            -FFmpegExe $FFmpegExe `
                            -InputVideo $video.FullName `
                            -AudioFile $audioPath `
                            -HeartbeatSeconds $HeartbeatSeconds `
                            -PythonCommand $PythonCommand
                        $audioStatus = "completed"
                    }
                }
                catch {
                    if (Test-MMSkipException $_) { throw }
                    $audioStatus = "failed"
                    $audioErrorMessage = $_.Exception.Message
                    Write-Log ("Transcript-only audio extraction failed for '{0}'; the transcript is still made. {1}" -f $video.FullName, $audioErrorMessage) "WARN"
                }
            }

            $transcriptTripleExists = (Test-Path -LiteralPath $jsonPath) -and (Test-Path -LiteralPath $srtPath) -and (Test-Path -LiteralPath $txtPath)
            if ($transcriptTripleExists -and -not $OverwriteTranscripts) {
                $status = "skipped"
                Write-Log ("Skipping existing transcript triple for {0}" -f $video.FullName)
            }
            else {
                if ($OverwriteTranscripts) {
                    foreach ($existingPath in @($jsonPath, $srtPath, $txtPath, $audioPath)) {
                        if (Test-Path -LiteralPath $existingPath) {
                            Remove-Item -LiteralPath $existingPath -Force -ErrorAction SilentlyContinue
                        }
                    }
                }

                # 214: the narration track chosen the shared way, exactly as Package any video for AI
                # on Auto: track names, the main narration-track setting, then voice detection. The
                # narration track gets the strict narration filter; with none, the full mix is
                # transcribed with the plain one, and the run never says "no narration found".
                # Whisper hears the WAV the shared decoder makes, as in every other feature.
                $audioStreams = @(Get-VideoAudioStreams -FFprobeExe $FFprobeExe -VideoPath $video.FullName)
                if ($audioStreams.Count -eq 0) {
                    throw "The recording has no audio track to transcribe."
                }
                $autoTrackNumber = Get-MMFullReviewAutoTrackNumber -AudioStreams $audioStreams -Mode $TranscriptAudioMode `
                    -StreamSpecifier $TranscriptAudioStream -TrackOrdinal $TranscriptAudioTrackOrdinal -PreferredTrackOrdinal 0 `
                    -PythonCommand $PythonCommand -FFmpegExe $FFmpegExe -FFprobeExe $FFprobeExe -VideoPath $video.FullName `
                    -PreferGpu $CanUseWhisperGpu -TrackRolesText $TrackRolesText -HeartbeatSeconds $HeartbeatSeconds -MeasuredBy "transcript_only"
                $narrationDetection = $script:MMFullReviewNarration
                $selection = Resolve-TranscriptAudioSelection -AudioStreams $audioStreams -Mode $TranscriptAudioMode `
                    -StreamSpecifier $TranscriptAudioStream `
                    -TrackOrdinal $(if ($autoTrackNumber -gt 0) { $autoTrackNumber } else { $TranscriptAudioTrackOrdinal }) `
                    -PreferredTrackOrdinal 0 -InteractiveMode:$false
                if ($null -eq $selection -or $null -eq $selection.SelectedStream) {
                    throw "No audio track could be chosen for the transcript."
                }
                Write-Log ("Transcript-only audio for '{0}': {1} ({2})" -f $video.Name, $(if ([bool]$selection.IsAllTracks) { "the full mix" } else { "Track {0}" -f ([int]$selection.SelectedStream.ordinal + 1) }), [string]$selection.Reason)
                $sourceSeconds = if ([string]::IsNullOrWhiteSpace($durationSeconds)) { 0 } else { [double]::Parse($durationSeconds, [System.Globalization.CultureInfo]::InvariantCulture) }
                $wavRoot = Get-MMScratchPath -Prefix "media_manglers_transcript_only_audio"
                try {
                    $narrationWav = Join-Path $wavRoot "narration.wav"
                    if ([bool]$selection.IsAllTracks) {
                        $mixStatus = Export-AllTracksReviewMixWav -FFmpegExe $FFmpegExe -InputVideo $video.FullName `
                            -AudioStreams @($selection.SelectedStreams) -OutputWav $narrationWav -PythonCommand $PythonCommand `
                            -HeartbeatSeconds $HeartbeatSeconds -Force
                        if ($mixStatus -eq "FAILED" -or -not (Test-Path -LiteralPath $narrationWav)) {
                            throw "The full mix of the recording's audio tracks could not be made."
                        }
                    }
                    else {
                        $null = Export-TranscriptSourceWav `
                            -PythonCommand $PythonCommand `
                            -FFmpegExe $FFmpegExe `
                            -InputVideo $video.FullName `
                            -OutputWav $narrationWav `
                            -FfmpegMap ([string]$selection.SelectedStream.ffmpeg_map) `
                            -HeartbeatSeconds $HeartbeatSeconds `
                            -DurationSeconds $sourceSeconds `
                            -Force
                    }
                    $null = Invoke-PythonWhisperTranscript `
                        -PythonCommand $PythonCommand `
                        -AudioPath $narrationWav `
                        -TranscriptFolder $transcriptsFolder `
                        -ModelName $ModelName `
                        -LanguageCode $LanguageCode `
                        -FFmpegExe $FFmpegExe `
                        -PreferGpu $CanUseWhisperGpu `
                        -Task "transcribe" `
                        -JsonName ([System.IO.Path]::GetFileName($jsonPath)) `
                        -SrtName ([System.IO.Path]::GetFileName($srtPath)) `
                        -TextName ([System.IO.Path]::GetFileName($txtPath)) `
                        -SourceDurationSeconds $sourceSeconds `
                        -HeartbeatSeconds $HeartbeatSeconds `
                        -WhisperTimeoutSeconds $WhisperTimeoutSeconds `
                        -NarrationSpeechMode $(if ($null -ne $narrationDetection) { "Sparse" } else { "Auto" }) `
                        -InitialPrompt (Get-EvidenceTranscriptionInitialPrompt -GlossaryEntries (Get-MMSpellingWords)) `
                        -GlossaryEntries (Get-MMSpellingWords) `
                        -InteractiveMode:$false `
                        -AllowInteractiveLongRunPrompt:$false
                    if ($null -ne $narrationDetection) {
                        # The narration filter Package any video for AI uses: lines another track
                        # carries, and lines said where the narration track was near silent, go.
                        $null = Invoke-MMNarrationCrossCheck -PythonCommand $PythonCommand -FFmpegExe $FFmpegExe `
                            -VideoPath $video.FullName -TranscriptJsonPath $jsonPath -Detection $narrationDetection `
                            -PreferGpu $CanUseWhisperGpu -HeartbeatSeconds $HeartbeatSeconds
                    }
                }
                finally {
                    Remove-MMScratchPath -Path $wavRoot
                }
                if (-not ((Test-Path -LiteralPath $jsonPath) -and (Test-Path -LiteralPath $srtPath) -and (Test-Path -LiteralPath $txtPath))) {
                    throw "Whisper completed but the expected transcript JSON/SRT/TXT triple was not found."
                }

                $status = "completed"
            }
        }
        catch {
            if ((Test-MMSkipException $_) -or $script:MMSkipRequested -or (Test-MMSourceSkipRequested -SourcePath $video.FullName)) {
                $script:MMSkipRequested = $false
                $status = "skipped"
                $errorMessage = "Skipped by you."
                Write-Host ("SKIPPED by you: {0}" -f $video.Name) -ForegroundColor Yellow
                # 213: the operator's own choice, not a warning.
                Write-Log ("Skipped by you: '{0}'. No transcript is made for this recording." -f $video.FullName) "INFO"
                foreach ($partialPath in @($jsonPath, $srtPath, $txtPath)) {
                    if (Test-Path -LiteralPath $partialPath) { Remove-Item -LiteralPath $partialPath -Force -ErrorAction SilentlyContinue }
                }
            }
            else {
                $status = "failed"
                $errorMessage = $_.Exception.Message
                Write-Host ("FAIL transcript-only {0}" -f $video.FullName) -ForegroundColor Red
                Write-Host $errorMessage -ForegroundColor Red
                Write-Log ("Transcript-only failure for '{0}': {1}" -f $video.FullName, $errorMessage) "ERROR"
            }
        }

        [void]$manifestEntries.Add([PSCustomObject]@{
            source_id            = $sourceId
            source_identifier    = $sourceIdentifier
            source_path          = $video.FullName
            source_filename      = $video.Name
            audio_path           = $audioPath
            audio_status         = $audioStatus
            audio_error_message  = $audioErrorMessage
            transcript_json_path = $jsonPath
            transcript_srt_path  = $srtPath
            transcript_txt_path  = $txtPath
            duration_seconds     = $durationSeconds
            status               = $status
            error_message        = $errorMessage
        })
    }

    # 214: no recording is current now, so a skipped last one cannot stop the index step.
    $script:MMCurrentSourcePath = ""
    $manifestEntryArray = @($manifestEntries.ToArray())
    $indexResult = Invoke-TranscriptOnlyIndexHelper `
        -PythonCommand $PythonCommand `
        -OutputRoot $outputRoot `
        -ManifestEntries $manifestEntryArray `
        -SearchTerms @($SearchTerms) `
        -HeartbeatSeconds $HeartbeatSeconds

    $completedCount = @($manifestEntries | Where-Object { $_.status -eq "completed" }).Count
    $skippedCount = @($manifestEntries | Where-Object { $_.status -eq "skipped" }).Count
    $failedCount = @($manifestEntries | Where-Object { $_.status -eq "failed" }).Count

    Write-Phase -Name "Transcript-Only Summary" -Detail "Batch complete"
    Write-Host ("Completed: {0}" -f $completedCount)
    Write-Host ("Skipped:   {0}" -f $skippedCount)
    Write-Host ("Failed:    {0}" -f $failedCount)
    Write-Host ("Output:    {0}" -f $outputRoot)
    Write-Host ("Manifest:  {0}" -f $indexResult.manifest_json)
    Write-Host ("Index:     {0}" -f $indexResult.combined_markdown)
    if (@($SearchTerms).Count -gt 0) {
        Write-Host ("Search matches: {0}" -f $indexResult.search_results_count)
        Write-Host ("Search CSV:     {0}" -f $indexResult.search_csv)
        Write-Host ("Search MD:      {0}" -f $indexResult.search_markdown)
        Write-Host ("Per-file search folder: {0}" -f $indexResult.search_results_dir)
        Write-Host ("ChatGPT search handoff: {0}" -f $indexResult.ai_search_markdown)
    }
    else {
        Write-Host "Search:    no search terms supplied; no search result files written."
    }

    if (($completedCount + $skippedCount) -eq 0) {
        throw "Transcript-only mode produced zero usable transcript outputs. See transcript_manifest.json for recorded failures."
    }

    return [PSCustomObject]@{
        OutputRoot       = $outputRoot
        CompletedCount   = $completedCount
        SkippedCount     = $skippedCount
        FailedCount      = $failedCount
        ManifestJson     = [string]$indexResult.manifest_json
        ManifestCsv      = [string]$indexResult.manifest_csv
        CombinedMarkdown = [string]$indexResult.combined_markdown
        SearchCsv        = [string]$indexResult.search_csv
        SearchMarkdown   = [string]$indexResult.search_markdown
        SearchMatchCount = [int]$indexResult.search_results_count
    }
}

function ConvertTo-MMWordList {
    # 201: the operator's words to spell right. The Workbench sends the whole list as one
    # value, because powershell -File binds only the first of several values to a parameter.
    # Entries are separated by commas, semicolons or new lines; "Word=heard as|also heard as".
    param([array]$Values = @())

    $words = New-Object System.Collections.Generic.List[string]
    foreach ($value in @($Values)) {
        foreach ($part in ([string]$value -split '[,;\r\n]+')) {
            $text = $part.Trim()
            if (-not [string]::IsNullOrWhiteSpace($text)) { [void]$words.Add($text) }
        }
    }
    return @($words.ToArray())
}

function Get-EvidenceTranscriptionInitialPrompt {
    param(
        [string]$GlossaryPath = "",
        [array]$GlossaryEntries = @()
    )

    # 201: only the operator's own list feeds Whisper. Its starting words (iRacing, SimHub,
    # Crew Chief) are seeded into the Workbench setting, not added here as well.
    $terms = New-Object System.Collections.Generic.List[string]
    foreach ($entry in @($GlossaryEntries)) {
        $text = [string]$entry
        if ([string]::IsNullOrWhiteSpace($text)) { continue }
        $canonical = $text.Split("=", 2)[0].Trim()
        if (-not [string]::IsNullOrWhiteSpace($canonical) -and -not $terms.Contains($canonical)) {
            [void]$terms.Add($canonical)
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($GlossaryPath) -and (Test-Path -LiteralPath $GlossaryPath -PathType Leaf)) {
        try {
            $payload = Get-Content -LiteralPath $GlossaryPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $jsonText = $payload | ConvertTo-Json -Depth 20 -Compress
            foreach ($match in [regex]::Matches($jsonText, '"canonical"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"')) {
                $canonical = [regex]::Unescape([string]$match.Groups[1].Value).Trim()
                if (-not [string]::IsNullOrWhiteSpace($canonical) -and -not $terms.Contains($canonical)) {
                    [void]$terms.Add($canonical)
                }
            }
        }
        catch {
            Write-Log ("Transcription glossary prompt bias was skipped because the glossary could not be read: {0}" -f $_.Exception.Message) "WARN"
        }
    }
    if ($terms.Count -eq 0) { return "" }
    return "Preferred terminology: " + (@($terms) -join ", ")
}

function Invoke-NarrationClipTasks {
    param(
        [string]$FFmpegExe,
        [array]$ClipTasks,
        [int]$HeartbeatSeconds = 10
    )
    # 214: Full Review runs these inside its own recording; give it back when done, so Skip still finds it.
    $mmOuterSourcePath = [string]$script:MMCurrentSourcePath

    $results = New-Object System.Collections.Generic.List[object]
    $index = 0
    foreach ($clip in @($ClipTasks)) {
        $index += 1
        $script:MMCurrentSourcePath = [string]$clip.source_path
        $null = Wait-MMWhilePaused -Where "narration clips"
        if (Test-MMSourceSkipRequested -SourcePath ([string]$clip.source_path)) {
            [void]$results.Add([PSCustomObject]@{ path = [string]$clip.path; status = "failed"; error_message = "Skipped by you." })
            continue
        }
        if (Test-MMNonEmptyFile -Path ([string]$clip.path)) {
            # 115: clips are written under a temporary name and renamed when
            # finished, so a clip that exists is whole; reuse it on resume.
            [void]$results.Add([PSCustomObject]@{ path = [string]$clip.path; status = "created"; error_message = "" })
            continue
        }
        $clipTempPath = [System.IO.Path]::ChangeExtension([string]$clip.path, ".partial.mp4")
        Ensure-Directory (Split-Path -Path ([string]$clip.path) -Parent)
        $start = ConvertTo-FfmpegSecondsText -Seconds ([double]$clip.start_seconds)
        $duration = ConvertTo-FfmpegSecondsText -Seconds ([double]$clip.duration_seconds)
        $audioMap = if ([string]::IsNullOrWhiteSpace([string]$clip.audio_ordinal)) { "0:a:0?" } else { "0:a:{0}?" -f [int]$clip.audio_ordinal }
        Write-MMProgressV1 -Phase "Narration visuals" -PhaseIndex 4 -PhaseCount 4 -SourceId ([string]$clip.source_id) -SourceName ([System.IO.Path]::GetFileName([string]$clip.source_path)) -Completed ($index - 1) -Total @($ClipTasks).Count -ProgressKind work_units -Activity ("Cutting narration clip {0} of {1}" -f $index, @($ClipTasks).Count)
        $status = "failed"
        $message = ""
        # GPU decode + NVENC first; plain CPU encode as the fallback.
        $attempts = @(
            @("-y", "-hwaccel", "cuda", "-ss", $start, "-t", $duration, "-i", [string]$clip.source_path, "-map", "0:v:0", "-map", $audioMap, "-vf", "scale=2880:-2", "-c:v", "h264_nvenc", "-preset", "p4", "-b:v", "1400k", "-maxrate", "1800k", "-bufsize", "2800k", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k", "-ac", "1", "-movflags", "+faststart", $clipTempPath),
            @("-y", "-ss", $start, "-t", $duration, "-i", [string]$clip.source_path, "-map", "0:v:0", "-map", $audioMap, "-vf", "scale=2880:-2", "-c:v", "libx264", "-preset", "veryfast", "-b:v", "1400k", "-maxrate", "1800k", "-bufsize", "2800k", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k", "-ac", "1", "-movflags", "+faststart", $clipTempPath)
        )
        foreach ($arguments in $attempts) {
            try {
                $capture = Invoke-ExternalCapture -FilePath $FFmpegExe -Arguments $arguments -StepName ("Narration clip {0} of {1}" -f $index, @($ClipTasks).Count) -HeartbeatSeconds $HeartbeatSeconds -IgnoreExitCode
                if ($capture.ExitCode -eq 0 -and (Test-MMNonEmptyFile -Path $clipTempPath)) {
                    Move-Item -LiteralPath $clipTempPath -Destination ([string]$clip.path) -Force
                    $status = "created"
                    break
                }
                $message = ("ffmpeg exit code {0}" -f $capture.ExitCode)
            }
            catch {
                $message = $_.Exception.Message
                if (Test-MMSkipException $_) { $script:MMSkipRequested = $false; $message = "Skipped by you."; break }
            }
        }
        if (Test-Path -LiteralPath $clipTempPath) { Remove-Item -LiteralPath $clipTempPath -Force -ErrorAction SilentlyContinue }
        if ($status -ne "created") {
            Write-Log ("Narration clip failed for {0} at {1}: {2}" -f [string]$clip.source_id, $start, $message) "WARN"
        }
        [void]$results.Add([PSCustomObject]@{ path = [string]$clip.path; status = $status; error_message = $message })
    }
    $script:MMCurrentSourcePath = $mmOuterSourcePath
    return @($results.ToArray())
}

function Invoke-NarrationReviewVideoTasks {
    # 103: a small review copy of each whole recording, next to the
    # per-moment clips, so the agent can see what happened between moments.
    param(
        [string]$FFmpegExe,
        [array]$VideoTasks,
        [int]$HeartbeatSeconds = 10
    )
    # 214: Full Review runs these inside its own recording; give it back when done, so Skip still finds it.
    $mmOuterSourcePath = [string]$script:MMCurrentSourcePath

    $results = New-Object System.Collections.Generic.List[object]
    $index = 0
    foreach ($task in @($VideoTasks)) {
        $index += 1
        $script:MMCurrentSourcePath = [string]$task.source_path
        $null = Wait-MMWhilePaused -Where "review videos"
        if (Test-MMSourceSkipRequested -SourcePath ([string]$task.source_path)) {
            [void]$results.Add([PSCustomObject]@{ path = [string]$task.path; status = "failed"; error_message = "Skipped by you." })
            continue
        }
        if (Test-MMNonEmptyFile -Path ([string]$task.path)) {
            # 115: written under a temporary name first, so an existing file is whole.
            [void]$results.Add([PSCustomObject]@{ path = [string]$task.path; status = "created"; error_message = "" })
            continue
        }
        $videoTempPath = [System.IO.Path]::ChangeExtension([string]$task.path, ".partial.mp4")
        Ensure-Directory (Split-Path -Path ([string]$task.path) -Parent)
        $audioMap = if ([string]::IsNullOrWhiteSpace([string]$task.audio_ordinal)) { "0:a:0?" } else { "0:a:{0}?" -f [int]$task.audio_ordinal }
        $width = if ([int]$task.width -gt 0) { [int]$task.width } else { 1920 }
        $timeout = [int][Math]::Max(1800, [Math]::Ceiling([double]$task.duration_seconds) + 1800)
        Write-MMProgressV1 -Phase "Narration visuals" -PhaseIndex 4 -PhaseCount 4 -SourceId ([string]$task.source_id) -SourceName ([System.IO.Path]::GetFileName([string]$task.source_path)) -Completed ($index - 1) -Total @($VideoTasks).Count -ProgressKind work_units -Activity ("Making the small review video of {0}" -f [System.IO.Path]::GetFileName([string]$task.source_path))
        $attempts = @(Get-MMReviewVideoArgumentSets -SourcePath ([string]$task.source_path) -AudioMap $audioMap -Width $width -OutputPath $videoTempPath)
        # 201: one started alongside the transcription is finished first. If it did not work,
        # the graphics-card way it used is not tried again here.
        $firstAttempt = 0
        $background = Get-MMBackgroundReviewVideo -Path ([string]$task.path)
        if ($null -ne $background) {
            $background.Claimed = $true
            if ([string]$background.AudioOrdinal -ne [string]$task.audio_ordinal) {
                Stop-MMBackgroundReviewVideo -Entry $background -RemoveFinished
            }
            elseif (Complete-MMBackgroundReviewVideo -Entry $background -HeartbeatSeconds $HeartbeatSeconds -TimeoutSeconds $timeout) {
                [void]$results.Add([PSCustomObject]@{ path = [string]$task.path; status = "created"; error_message = "" })
                continue
            }
            elseif (Test-MMSourceSkipRequested -SourcePath ([string]$task.source_path)) {
                [void]$results.Add([PSCustomObject]@{ path = [string]$task.path; status = "failed"; error_message = "Skipped by you." })
                continue
            }
            else {
                $firstAttempt = 1
            }
        }
        $status = "failed"
        $message = ""
        for ($attemptIndex = $firstAttempt; $attemptIndex -lt $attempts.Count; $attemptIndex++) {
            $arguments = [string[]]$attempts[$attemptIndex]
            try {
                $capture = Invoke-ExternalCapture -FilePath $FFmpegExe -Arguments $arguments -StepName ("Review video {0} of {1}" -f $index, @($VideoTasks).Count) -HeartbeatSeconds $HeartbeatSeconds -TimeoutSeconds $timeout -IgnoreExitCode
                if ($capture.ExitCode -eq 0 -and (Test-MMNonEmptyFile -Path $videoTempPath)) {
                    Move-Item -LiteralPath $videoTempPath -Destination ([string]$task.path) -Force
                    $status = "created"
                    break
                }
                $message = ("ffmpeg exit code {0}" -f $capture.ExitCode)
            }
            catch {
                $message = $_.Exception.Message
                if (Test-MMSkipException $_) { $script:MMSkipRequested = $false; $message = "Skipped by you."; break }
            }
        }
        if (Test-Path -LiteralPath $videoTempPath) { Remove-Item -LiteralPath $videoTempPath -Force -ErrorAction SilentlyContinue }
        if ($status -ne "created") {
            Write-Log ("Review video failed for {0}: {1}" -f [string]$task.source_id, $message) "WARN"
            if (Test-Path -LiteralPath ([string]$task.path)) {
                Remove-Item -LiteralPath ([string]$task.path) -Force -ErrorAction SilentlyContinue
            }
        }
        [void]$results.Add([PSCustomObject]@{ path = [string]$task.path; status = $status; error_message = $message })
    }
    $script:MMCurrentSourcePath = $mmOuterSourcePath
    return @($results.ToArray())
}

function Get-MMReviewVideoArgumentSets {
    # 103/201: the small review copy, about 110 MB per hour, three ways. First all on the
    # graphics card: decoded, thinned to 10 frames a second and shrunk there, so no full-size
    # frame is copied to the processor and Whisper, running at the same time, keeps its speed. Frames
    # no other frame is built from (about two thirds of an OBS recording) are not decoded at all:
    # at 10 frames a second they are not needed, and it is 2.4 times faster.
    # Then decoded on the card and shrunk on the processor, then the processor alone.
    param(
        [string]$SourcePath,
        [string]$AudioMap = "0:a:0?",
        [int]$Width = 1920,
        [string]$OutputPath
    )
    $filter = "fps=10,scale={0}:-2" -f $Width
    $sets = New-Object System.Collections.Generic.List[object]
    [void]$sets.Add([string[]]@("-y", "-nostdin", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-skip_frame:v", "noref", "-i", $SourcePath, "-map", "0:v:0", "-map", $AudioMap, "-vf", ("fps=10,scale_cuda={0}:-2" -f $Width), "-c:v", "h264_nvenc", "-preset", "p4", "-b:v", "320k", "-maxrate", "480k", "-bufsize", "640k", "-c:a", "aac", "-b:a", "48k", "-ac", "1", "-movflags", "+faststart", $OutputPath))
    [void]$sets.Add([string[]]@("-y", "-hwaccel", "cuda", "-i", $SourcePath, "-map", "0:v:0", "-map", $AudioMap, "-vf", $filter, "-c:v", "h264_nvenc", "-preset", "p4", "-b:v", "320k", "-maxrate", "480k", "-bufsize", "640k", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "48k", "-ac", "1", "-movflags", "+faststart", $OutputPath))
    [void]$sets.Add([string[]]@("-y", "-i", $SourcePath, "-map", "0:v:0", "-map", $AudioMap, "-vf", $filter, "-c:v", "libx264", "-preset", "veryfast", "-b:v", "320k", "-maxrate", "480k", "-bufsize", "640k", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "48k", "-ac", "1", "-movflags", "+faststart", $OutputPath))
    return $sets.ToArray()
}

function Get-MMNarrationReviewVideoPath {
    # The path narration_evidence.plan_from_request gives a recording's review copy.
    param([string]$OutputRoot, [string]$SourceId)
    return [System.IO.Path]::GetFullPath((Join-Path $OutputRoot ("artifacts\narration\{0}\review_video_{0}.mp4" -f $SourceId)))
}

function Get-MMBackgroundReviewVideo {
    param([string]$Path)
    if ($null -eq $script:MMBackgroundReviewVideos -or [string]::IsNullOrWhiteSpace($Path)) { return $null }
    $key = ([System.IO.Path]::GetFullPath($Path)).ToLowerInvariant()
    if ($script:MMBackgroundReviewVideos.Contains($key)) { return $script:MMBackgroundReviewVideos[$key] }
    return $null
}

function Start-MMBackgroundReviewVideo {
    # 201: the small review copy reads the whole recording through the graphics card's video
    # decoder, which Whisper does not use, and Whisper reads only the narration audio. So the
    # copy is made while Whisper writes the narration down, instead of after everything else.
    # It is collected by Invoke-NarrationReviewVideoTasks; one that is not wanted in the end
    # (no narrated moments, skipped, a later failure) is deleted, so the package is as before.
    param(
        [string]$FFmpegExe,
        [string]$SourcePath,
        [string]$SourceId,
        [int]$AudioOrdinal,
        [string]$OutputRoot
    )
    if ([string]::IsNullOrWhiteSpace($FFmpegExe) -or [string]::IsNullOrWhiteSpace($SourceId) -or [string]::IsNullOrWhiteSpace($OutputRoot)) { return $null }
    if ($null -eq $script:MMBackgroundReviewVideos) { $script:MMBackgroundReviewVideos = [ordered]@{} }
    $path = Get-MMNarrationReviewVideoPath -OutputRoot $OutputRoot -SourceId $SourceId
    $key = $path.ToLowerInvariant()
    if ($script:MMBackgroundReviewVideos.Contains($key)) { return $script:MMBackgroundReviewVideos[$key] }
    # 115: a whole one an earlier run of this package made is reused, as before.
    if (Test-MMNonEmptyFile -Path $path) { return $null }
    $tempPath = [System.IO.Path]::ChangeExtension($path, ".partial.mp4")
    try {
        Ensure-Directory (Split-Path -Path $path -Parent)
        $arguments = (Get-MMReviewVideoArgumentSets -SourcePath $SourcePath -AudioMap ("0:a:{0}?" -f $AudioOrdinal) -Width 1920 -OutputPath $tempPath)[0]
        $argString = (($arguments | ForEach-Object { Quote-Argument $_ }) -join " ")
        Write-Log ("Small review video of {0} started alongside the transcription." -f [System.IO.Path]::GetFileName($SourcePath))
        Write-Log "Command: $FFmpegExe $argString"
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $FFmpegExe
        $psi.Arguments = $argString
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.CreateNoWindow = $true
        $proc = New-Object System.Diagnostics.Process
        $proc.StartInfo = $psi
        [void]$proc.Start()
        $entry = [PSCustomObject]@{
            Path = $path
            TempPath = $tempPath
            SourcePath = $SourcePath
            AudioOrdinal = [string]$AudioOrdinal
            Process = $proc
            StdOut = $proc.StandardOutput.ReadToEndAsync()
            StdErr = $proc.StandardError.ReadToEndAsync()
            StartedAt = Get-Date
            Status = "running"
            Claimed = $false
        }
        $script:MMBackgroundReviewVideos[$key] = $entry
        return $entry
    }
    catch {
        Write-Log ("The small review video could not be started alongside the transcription; it is made later instead. {0}" -f $_.Exception.Message) "WARN"
        Remove-MMScratchPath -Path $tempPath
        return $null
    }
}

function Stop-MMBackgroundReviewVideo {
    param($Entry, [switch]$RemoveFinished)
    if ($null -eq $Entry) { return }
    if ($Entry.Status -eq "running") {
        Stop-MMProcessTree -Process $Entry.Process
        try { [void]$Entry.Process.WaitForExit(5000) } catch { }
        $Entry.Status = "stopped"
    }
    Remove-MMScratchPath -Path $Entry.TempPath
    if ($RemoveFinished -and $Entry.Status -eq "created") {
        Remove-MMScratchPath -Path $Entry.Path
        $Entry.Status = "removed"
    }
}

function Complete-MMBackgroundReviewVideo {
    # Waits for one started alongside the transcription. True when the finished file is in place.
    param($Entry, [int]$HeartbeatSeconds = 10, [int]$TimeoutSeconds = 0)
    if ($null -eq $Entry) { return $false }
    if ($Entry.Status -ne "running") { return ($Entry.Status -eq "created" -and (Test-MMNonEmptyFile -Path $Entry.Path)) }
    $name = [System.IO.Path]::GetFileName([string]$Entry.SourcePath)
    $proc = $Entry.Process
    $waitStart = Get-Date
    $nextBeat = if ($HeartbeatSeconds -gt 0) { $waitStart.AddSeconds($HeartbeatSeconds) } else { $null }
    while (-not $proc.HasExited) {
        Start-Sleep -Milliseconds 500
        # Wait-MMWhilePaused suspends this copy too while the run is paused.
        $pausedSeconds = Wait-MMWhilePaused -Where "the small review video"
        if ($pausedSeconds -gt 0) {
            $waitStart = $waitStart.AddSeconds($pausedSeconds)
            if ($nextBeat) { $nextBeat = $nextBeat.AddSeconds($pausedSeconds) }
        }
        if (Test-MMSourceSkipRequested -SourcePath ([string]$Entry.SourcePath)) {
            Stop-MMBackgroundReviewVideo -Entry $Entry
            return $false
        }
        $now = Get-Date
        if ($nextBeat -and $now -ge $nextBeat) {
            Write-Log ("Review video of {0} still working... elapsed {1:n0}s" -f $name, ($now - $Entry.StartedAt).TotalSeconds)
            # 224 (Wave B2b): waiting for the review video is this step's own words, so they are said, not a heartbeat's.
            Write-MMProgressV1 -Phase ([string]$script:MMProgressPhase) -ProgressKind indeterminate -Activity ("Making the small review video of {0}" -f $name)
            $nextBeat = $now.AddSeconds($HeartbeatSeconds)
        }
        if ($TimeoutSeconds -gt 0 -and ($now - $waitStart).TotalSeconds -ge $TimeoutSeconds) {
            Stop-MMBackgroundReviewVideo -Entry $Entry
            Write-Log ("The small review video of {0} timed out after {1} seconds; it is made again the earlier way." -f $name, $TimeoutSeconds) "WARN"
            return $false
        }
    }
    $proc.WaitForExit()
    $stderr = ""
    try { $null = $Entry.StdOut.GetAwaiter().GetResult(); $stderr = $Entry.StdErr.GetAwaiter().GetResult() } catch { }
    if (-not [string]::IsNullOrWhiteSpace($stderr) -and $script:CurrentLogFile) {
        $null = Add-LogContentWithRetry -Path $script:CurrentLogFile -Value ("----- STDERR: Review video of {0} (made alongside the transcription) -----" -f $name)
        $null = Add-LogContentWithRetry -Path $script:CurrentLogFile -Value $stderr
    }
    if ($proc.ExitCode -eq 0 -and (Test-MMNonEmptyFile -Path $Entry.TempPath)) {
        Move-Item -LiteralPath $Entry.TempPath -Destination $Entry.Path -Force
        $Entry.Status = "created"
        Write-Log ("Small review video of {0} finished alongside the transcription in {1:n0}s." -f $name, ((Get-Date) - $Entry.StartedAt).TotalSeconds)
        return $true
    }
    $Entry.Status = "failed"
    Remove-MMScratchPath -Path $Entry.TempPath
    Write-Log ("The small review video of {0} made on the graphics card failed (ffmpeg exit code {1}); it is made again the earlier way." -f $name, $proc.ExitCode) "WARN"
    return $false
}

function Wait-MMBackgroundReviewVideos {
    # Before the next recording is read: two readers on one drive slow each other down.
    param([int]$HeartbeatSeconds = 10)
    if ($null -eq $script:MMBackgroundReviewVideos) { return }
    foreach ($entry in @($script:MMBackgroundReviewVideos.Values)) {
        if ($entry.Status -ne "running") { continue }
        Write-Host ("  Finishing the small review video of {0} before reading the next recording." -f [System.IO.Path]::GetFileName([string]$entry.SourcePath))
        $null = Complete-MMBackgroundReviewVideo -Entry $entry -HeartbeatSeconds $HeartbeatSeconds
    }
}

function Remove-MMUnclaimedBackgroundReviewVideos {
    # Stops and deletes every copy started alongside a transcription that the narration visuals
    # did not take: one the plan has no task for (keep only -KeepPaths), or all at the end.
    param([string[]]$KeepPaths = @(), [switch]$All)
    if ($null -eq $script:MMBackgroundReviewVideos) { return }
    $keep = @($KeepPaths | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { ([System.IO.Path]::GetFullPath([string]$_)).ToLowerInvariant() })
    foreach ($key in @($script:MMBackgroundReviewVideos.Keys)) {
        $entry = $script:MMBackgroundReviewVideos[$key]
        if ($entry.Claimed -and -not $All) { continue }
        if (-not $All -and ($keep -contains $key)) { continue }
        Stop-MMBackgroundReviewVideo -Entry $entry -RemoveFinished:(-not $entry.Claimed)
        $script:MMBackgroundReviewVideos.Remove($key)
    }
}

function Invoke-NarrationEvidence {
    # 101: screenshots and a short clip for every stretch of operator
    # narration, independent of the keyword scan.
    param(
        [string]$PythonCommand,
        [string]$FFmpegExe,
        [string]$OutputRoot,
        [array]$Sources,
        [string]$PanelCropMode = "Auto",
        [int]$HeartbeatSeconds = 10,
        # 201: on a Continue, remove the narration visuals an earlier run left that this run does
        # not make. Only for a package kept as a folder; a portable ZIP's folder stays as before.
        [switch]$PruneStale
    )

    $planPath = Join-Path $OutputRoot "artifacts\narration\plan.json"
    $sourcePayload = @($Sources | ForEach-Object {
        @{
            source_id = [string]$_.source_id
            source_path = [string]$_.source_path
            source_filename = [string]$_.source_filename
            status = [string]$_.status
            duration_seconds = [string]$_.duration_seconds
            transcript_json_path = [string]$_.transcript_json_path
            selected_audio_stream_index = [int]$_.selected_audio_stream_index
        }
    })
    Write-MMProgressV1 -Phase "Narration visuals" -PhaseIndex 4 -PhaseCount 4 -ProgressKind stage -Activity "Planning screenshots and clips for every narrated moment"
    $planResult = Invoke-MediaManglersPythonCli -PythonCommand $PythonCommand -Command "narration-evidence-plan" -StepName "Narration visuals plan" -HeartbeatSeconds $HeartbeatSeconds -Payload @{
        output_dir = $OutputRoot
        sources = $sourcePayload
        panel_crop_mode = $PanelCropMode
        plan_path = $planPath
        prune_stale = [bool]$PruneStale
    }
    if ($null -eq $planResult -or $null -eq $planResult.Result -or -not [bool]$planResult.Result.ok) {
        $detail = if ($planResult -and $planResult.Result) { [string]$planResult.Result.error } else { "no result" }
        Write-Log ("Narration visuals could not be planned: {0}" -f $detail) "WARN"
        return $null
    }
    $plan = $planResult.Result.data
    if ([int]$plan.pruned_count -gt 0) {
        Write-Log ("Removed {0} narration file(s) an earlier run of this package left that this run does not make." -f [int]$plan.pruned_count)
    }
    $frameTasks = @($plan.frame_tasks)
    $clipTasks = @($plan.clip_tasks)
    $reviewVideoTasks = @($plan.review_video_tasks | Where-Object { $null -ne $_ })
    # 201: a copy made alongside the transcription of a recording the plan has no review copy for goes.
    Remove-MMUnclaimedBackgroundReviewVideos -KeepPaths @($reviewVideoTasks | ForEach-Object { [string]$_.path })
    Write-Host ("Narration visuals: {0} moment(s), {1} screenshot(s), {2} clip(s), {3} small review video(s)" -f [int]$plan.moment_count, $frameTasks.Count, $clipTasks.Count, $reviewVideoTasks.Count) -ForegroundColor Cyan
    if ($frameTasks.Count -gt 0) {
        try {
            $null = Invoke-CodexEvidenceFrameTasks -FFmpegExe $FFmpegExe -FrameTasks $frameTasks -HeartbeatSeconds $HeartbeatSeconds -PythonCommand $PythonCommand
        }
        catch {
            Write-Log ("Narration screenshots failed: {0}" -f $_.Exception.Message) "WARN"
        }
    }
    if ($clipTasks.Count -gt 0) {
        $null = Invoke-NarrationClipTasks -FFmpegExe $FFmpegExe -ClipTasks $clipTasks -HeartbeatSeconds $HeartbeatSeconds
    }
    if ($reviewVideoTasks.Count -gt 0) {
        $null = Invoke-NarrationReviewVideoTasks -FFmpegExe $FFmpegExe -VideoTasks $reviewVideoTasks -HeartbeatSeconds $HeartbeatSeconds
    }
    $writeResult = Invoke-MediaManglersPythonCli -PythonCommand $PythonCommand -Command "narration-evidence-write" -StepName "Narration visuals index" -HeartbeatSeconds $HeartbeatSeconds -Payload @{
        output_dir = $OutputRoot
        plan_path = $planPath
    }
    if ($null -eq $writeResult -or $null -eq $writeResult.Result -or -not [bool]$writeResult.Result.ok) {
        Write-Log "Narration visuals index could not be written." "WARN"
        return $null
    }
    $data = $writeResult.Result.data
    Write-Host ("Narration visuals written: {0} of {1} moment(s) with visuals, {2} screenshot(s), {3} clip(s), {4} small review video(s)" -f [int]$data.moments_with_visuals, [int]$data.moment_count, [int]$data.frame_count, [int]$data.clip_count, [int]$data.review_video_count)
    return $data
}

function Invoke-MMNarrationCrossCheck {
    # 199: lines of the narration transcript that another track carries at the same moment
    # (music played out loud, the game, a spotter, voice chat) are not the operator's. The helper
    # plays each line from the recording's never-narration tracks and rewrites the transcript
    # without the ones it hears there. A failure leaves the transcript as it was.
    param(
        [string]$PythonCommand,
        [string]$FFmpegExe,
        [string]$VideoPath,
        [string]$TranscriptJsonPath,
        $Detection,
        [bool]$PreferGpu = $true,
        [int]$HeartbeatSeconds = 10
    )
    if ($null -eq $Detection -or $null -eq $Detection.PSObject.Properties["track_roles"]) { return $null }
    try {
        $cliResult = Invoke-MediaManglersPythonCli `
            -PythonCommand $PythonCommand `
            -Command "narration-cross-check" `
            -StepName "Checking the narration against the other tracks" `
            -HeartbeatSeconds $HeartbeatSeconds `
            -TimeoutSeconds 1800 `
            -Payload @{
                source_path          = $VideoPath
                ffmpeg_exe           = $FFmpegExe
                transcript_json_path = $TranscriptJsonPath
                detection            = $Detection
                model_name           = "base.en"
                prefer_gpu           = [bool]$PreferGpu
                language_code        = "en"
            }
    }
    catch {
        Write-Log ("Checking the narration against the other tracks could not run for '{0}': {1}" -f $VideoPath, $_.Exception.Message) "WARN"
        return $null
    }
    if ($null -eq $cliResult -or $null -eq $cliResult.Result -or -not [bool]$cliResult.Result.ok) {
        $detail = if ($cliResult -and $cliResult.Result) { [string]$cliResult.Result.error } else { "no result" }
        Write-Log ("Checking the narration against the other tracks failed for '{0}': {1}" -f $VideoPath, $detail) "WARN"
        return $null
    }
    $data = $cliResult.Result.data
    foreach ($line in @($data.dropped)) {
        if ($null -eq $line) { continue }
        if ([string]$line.reason -eq "narration_track_near_silent") {
            # 203: said where the narration track itself was near silent.
            Write-Log ("Narration line at {0}s left out: Track {1}, the narration track, was near silent then." -f $line.start, $line.track_number)
        }
        else {
            Write-Log ("Narration line at {0}s left out: it was heard on Track {1} ({2})." -f $line.start, $line.track_number, $line.track_title)
        }
    }
    return $data
}

function Invoke-VoiceTrackDetection {
    param(
        [string]$PythonCommand,
        [string]$FFmpegExe,
        [string]$FFprobeExe,
        [string]$VideoPath,
        [double]$DurationSeconds = 0,
        [bool]$PreferGpu = $true,
        [string]$ModelName = "base.en",
        [int[]]$PreferredOrdinals = @(),
        # 196: the per-track narration setting, @{ "2" = "narration"; "3" = "never" }.
        [hashtable]$TrackRoles = @{},
        [int]$HeartbeatSeconds = 10,
        # 145: no limit on total time. The helper reports each step and is
        # stopped only when nothing new arrives for this long. It is longer
        # than the helper's own decode stall limit, so the plainer reason wins.
        [int]$StallTimeoutSeconds = 600,
        # 196: where the helper keeps the decoded audio of the track it chose
        # (and of the usual track), listed in the result as kept_track_wavs.
        # Empty keeps nothing.
        [string]$KeepWavDir = "",
        # 264: who is asking, as the library keeps it with what this measures.
        [string]$MeasuredBy = "bug_reports"
    )

    Write-Host ("  Listening to every audio track to find your voice: {0}" -f (Split-Path -Path $VideoPath -Leaf)) -ForegroundColor Cyan
    # Why detection failed, for the operator's message about this recording.
    $script:MMVoiceDetectionError = ""
    # The decoded audio (gigabytes for a long race) goes to a folder made and
    # removed here, so it is gone even when the helper is stopped and cannot
    # clean up after itself. What a run stopped from the Workbench left is
    # removed first (196).
    $null = Remove-MMOrphanedScratch
    $progressStatePath = Get-MMScratchPath -Prefix "media_manglers_voice_progress" -Extension ".json"
    $voiceWorkDir = Get-MMScratchPath -Prefix "media_manglers_voice_work"
    try {
        Ensure-Directory $voiceWorkDir
        $cliResult = Invoke-MediaManglersPythonCli `
            -PythonCommand $PythonCommand `
            -Command "voice-track-detect" `
            -StepName "Voice track detection" `
            -HeartbeatSeconds $HeartbeatSeconds `
            -TimeoutSeconds 0 `
            -StallTimeoutSeconds $StallTimeoutSeconds `
            -ProgressStateFilePath $progressStatePath `
            -Payload @{
                source_path   = $VideoPath
                ffmpeg_exe    = $FFmpegExe
                ffprobe_exe   = $FFprobeExe
                work_dir      = $voiceWorkDir
                model_name    = $ModelName
                prefer_gpu    = [bool]$PreferGpu
                language_code = "en"
                preferred_ordinals = @($PreferredOrdinals)
                track_roles = $(if ($null -eq $TrackRoles) { @{} } else { $TrackRoles })
                progress_state_file_path = $progressStatePath
                keep_wavs_dir = $KeepWavDir
                measured_by = $MeasuredBy
            }
    }
    catch {
        $script:MMVoiceDetectionError = $_.Exception.Message
        Write-Log ("Voice track detection could not run for '{0}': {1}" -f $VideoPath, $_.Exception.Message) "WARN"
        return $null
    }
    finally {
        Remove-MMScratchPath -Path $progressStatePath
        Remove-MMScratchPath -Path ($progressStatePath + ".tmp")
        Remove-MMScratchPath -Path $voiceWorkDir
    }
    if ($null -eq $cliResult -or $null -eq $cliResult.Result -or -not [bool]$cliResult.Result.ok) {
        $detail = if ($cliResult -and $cliResult.Result) { [string]$cliResult.Result.error } else { "no result" }
        $script:MMVoiceDetectionError = $detail
        Write-Log ("Voice track detection failed for '{0}': {1}" -f $VideoPath, $detail) "WARN"
        return $null
    }
    $data = $cliResult.Result.data
    foreach ($track in @($data.tracks)) {
        Write-Log ("Voice detection Track {0}: score={1}; words={2}; active_ratio={3}; {4}" -f [int]$track.track_number, $track.score, [int]$track.confident_words, $track.active_ratio, [string]$track.reason)
    }
    Write-Log ("Voice detection result for '{0}': {1} (confidence {2}). {3}" -f $VideoPath, [string]$data.status, $data.confidence, [string]$data.explanation)
    return $data
}

function Get-MMKnownVoiceDetection {
    # 264: what the library already knows, asked before a run listens. Quick: it reads the library and looks
    # at the file's size and time, and never reads the recording. Returns the helper's data: preferred_ordinals (this
    # recording's own remembered pick), answer (a result of the shape voice-track-detect returns, with no moments
    # in it, or $null) and decided_by. $null when the helper could not say: the run then listens, as it always did.
    param(
        [string]$PythonCommand,
        [string]$FFprobeExe,
        [string]$VideoPath,
        [int[]]$PreferredOrdinals = @(),
        [int[]]$FallbackOrdinals = @(),
        [bool]$UseSavedLayouts = $false,
        # The setting as saved, "2=narration,3=game": an old raw bin row is checked against its Game audio entries.
        [string]$TrackRolesText = "",
        [int]$HeartbeatSeconds = 10
    )
    try {
        $cliResult = Invoke-MediaManglersPythonCli `
            -PythonCommand $PythonCommand `
            -Command "voice-track-known" `
            -StepName "Voice track lookup" `
            -HeartbeatSeconds $HeartbeatSeconds `
            -TimeoutSeconds 300 `
            -Payload @{
                source_path = $VideoPath
                ffprobe_exe = $FFprobeExe
                preferred_ordinals = @($PreferredOrdinals)
                fallback_ordinals = @($FallbackOrdinals)
                use_saved_layouts = [bool]$UseSavedLayouts
                track_roles = [string]$TrackRolesText
            }
    }
    catch {
        Write-Log ("The library could not be asked about '{0}'; listening instead. {1}" -f (Split-Path -Path $VideoPath -Leaf), $_.Exception.Message) "WARN"
        return $null
    }
    if ($null -eq $cliResult -or $null -eq $cliResult.Result -or -not [bool]$cliResult.Result.ok) { return $null }
    return $cliResult.Result.data
}

function Get-MMSpellingWords {
    # 206: the operator's words to spell right, for every feature that transcribes.
    return @(ConvertTo-MMWordList -Values @($script:EvidenceTranscriptionGlossaryEntries))
}

function Resolve-MMFullReviewAutoTrack {
    # 206: Full Review on Auto finds the narration track the way Find my bug reports does: track
    # names, the per-track setting, then voice detection. Full Review is for any video, so when no
    # narration track is found it never says so: a track named or set as the full mix is used, and
    # failing that the caller transcribes every track, as Auto always did. Returns the track to
    # use (0-based Ordinal; IsNarration; the Detection), or $null for every track.
    param(
        [string]$PythonCommand,
        [string]$FFmpegExe,
        [string]$FFprobeExe,
        [string]$VideoPath,
        [bool]$PreferGpu = $true,
        [string]$TrackRolesText = "",
        [int]$HeartbeatSeconds = 10,
        [string]$MeasuredBy = "full_review"
    )
    $detection = $null
    try {
        # 264: the library first; no remembered pick here, as this feature never had one.
        $trackRoles = ConvertTo-MMTrackRoles -Text $TrackRolesText
        $known = Get-MMKnownVoiceDetection -PythonCommand $PythonCommand -FFprobeExe $FFprobeExe -VideoPath $VideoPath -TrackRolesText $TrackRolesText -HeartbeatSeconds $HeartbeatSeconds
        if ($null -ne $known -and $null -ne $known.answer) {
            $detection = $known.answer
            Write-Log ("The library already knows the voice track of '{0}' ({1}); nothing is listened to." -f (Split-Path -Path $VideoPath -Leaf), [string]$detection.status)
        }
        else {
            $detection = Invoke-VoiceTrackDetection -PythonCommand $PythonCommand -FFmpegExe $FFmpegExe -FFprobeExe $FFprobeExe `
                -VideoPath $VideoPath -PreferGpu $PreferGpu -PreferredOrdinals @() -TrackRoles $trackRoles `
                -HeartbeatSeconds $HeartbeatSeconds -KeepWavDir "" -MeasuredBy $MeasuredBy
        }
    }
    catch {
        Write-Log ("Finding the narration track did not work for '{0}'; every track is transcribed. {1}" -f $VideoPath, $_.Exception.Message) "WARN"
        return $null
    }
    if ($null -ne $detection -and [string]$detection.status -eq "selected") {
        $decidedBy = if ($null -ne $detection.PSObject.Properties["decided_by_text"] -and -not [string]::IsNullOrWhiteSpace([string]$detection.decided_by_text)) { [string]$detection.decided_by_text } else { "auto-detected" }
        Write-Host ("  Voice found on Track {0} ({1}); only that track is transcribed." -f ([int]$detection.selected_ordinal + 1), $decidedBy) -ForegroundColor Green
        return [PSCustomObject]@{ Ordinal = [int]$detection.selected_ordinal; IsNarration = $true; Detection = $detection }
    }
    if ($null -ne $detection -and $null -ne $detection.PSObject.Properties["track_roles"] -and $null -ne $detection.track_roles) {
        foreach ($role in @($detection.track_roles.PSObject.Properties | Sort-Object { [int]$_.Name })) {
            if ([string]$role.Value -eq "full_mix" -and [int]$role.Name -ge 1) {
                Write-Host ("  No narration track found; the full mix, Track {0}, is transcribed." -f [int]$role.Name)
                return [PSCustomObject]@{ Ordinal = [int]$role.Name - 1; IsNarration = $false; Detection = $detection }
            }
        }
    }
    Write-Host "  No narration track found; every audio track is transcribed."
    return $null
}

function Get-MMFullReviewAutoTrackNumber {
    # 206: the track number (1-based) Full Review's Auto transcribes, or 0 for every track as Auto
    # always did. A chosen track, a preferred track and a one-track video are used as before, with
    # no detection. Sets $script:MMFullReviewNarration to the voice-track result when the track is
    # the narration, so the narration filter runs on its transcript.
    param(
        [array]$AudioStreams = @(),
        [string]$Mode = "Auto",
        [string]$StreamSpecifier = "",
        [int]$TrackOrdinal = 0,
        [int]$PreferredTrackOrdinal = 0,
        [string]$PythonCommand,
        [string]$FFmpegExe,
        [string]$FFprobeExe,
        [string]$VideoPath,
        [bool]$PreferGpu = $true,
        [string]$TrackRolesText = "",
        [int]$HeartbeatSeconds = 10,
        [string]$MeasuredBy = "full_review"
    )
    $script:MMFullReviewNarration = $null
    if ($Mode -ne "Auto" -or @($AudioStreams).Count -le 1 -or -not [string]::IsNullOrWhiteSpace($StreamSpecifier) -or $TrackOrdinal -gt 0 -or $PreferredTrackOrdinal -gt 0 -or [string]::IsNullOrWhiteSpace($PythonCommand)) {
        return 0
    }
    $autoTrack = Resolve-MMFullReviewAutoTrack -PythonCommand $PythonCommand -FFmpegExe $FFmpegExe -FFprobeExe $FFprobeExe `
        -VideoPath $VideoPath -PreferGpu $PreferGpu -TrackRolesText $TrackRolesText -HeartbeatSeconds $HeartbeatSeconds -MeasuredBy $MeasuredBy
    if ($null -eq $autoTrack) { return 0 }
    if ([bool]$autoTrack.IsNarration) { $script:MMFullReviewNarration = $autoTrack.Detection }
    return ([int]$autoTrack.Ordinal + 1)
}

function Get-MMRecordingOutcomeLines {
    # The recordings a run could not use (Problems) and those with no narration (NoNarration),
    # one "<file>: <reason>" line each. 196: a recording with no narration is a correct result,
    # not a problem: it is reported on its own, and alone it does not make the run fail.
    param($ManifestEntries, $DetectedSources)
    $problems = New-Object System.Collections.Generic.List[string]
    $noNarration = New-Object System.Collections.Generic.List[string]
    foreach ($entry in @($ManifestEntries)) {
        if ($null -eq $entry) { continue }
        if ([string]$entry.status -eq "no_narration") {
            [void]$noNarration.Add(("{0}: {1}" -f [string]$entry.source_filename, (Get-CodexEvidenceProblemReason -Entry $entry)))
        }
        elseif ([string]$entry.status -in @("failed", "quality_blocked")) {
            [void]$problems.Add(("{0}: {1}" -f [string]$entry.source_filename, (Get-CodexEvidenceProblemReason -Entry $entry)))
        }
    }
    foreach ($detectedSource in @($DetectedSources)) {
        if ($null -eq $detectedSource) { continue }
        $detectedQuality = $detectedSource.transcript_quality
        if ($null -eq $detectedQuality -or [string]$detectedSource.status -notin @("completed", "skipped")) { continue }
        if ([string]$detectedQuality.quality_status -eq "no_narration_found") {
            [void]$noNarration.Add(("{0}: no narration found - the microphone track is silent or it is the wrong track" -f [string]$detectedSource.source_filename))
        }
    }
    return [pscustomobject]@{ Problems = $problems; NoNarration = $noNarration }
}

function Get-CodexEvidenceProblemReason {
    param([object]$Entry)

    $status = [string]$Entry.status
    $message = [string]$Entry.error_message
    if ($status -eq "no_narration") {
        # 142: the detector says what it heard ("Your usual microphone track,
        # Track 2, is silent. ..."), so that is what the operator reads.
        if ([string]::IsNullOrWhiteSpace($message)) {
            return "no narration found - no audio track has clear speech in this recording"
        }
        return ("no narration found - {0}" -f $message.Trim())
    }
    if ($status -eq "quality_blocked") {
        return "the transcript looks invented (for example 'Thank you for watching' on silence), so it was not used"
    }
    if ($message -match '^Multiple audio tracks:') {
        return "the app could not tell which track is your microphone - press Fix and continue, right-click this recording, choose the track with your voice, then press Continue"
    }
    if ($message -match '(?i)nothing new for (\d+) seconds, ([0-9:]+) into the recording') {
        # 145: reading the recording stopped, in voice detection or in the
        # narration extraction. Another track would not help, so the operator
        # reads where it stopped and what to check.
        return ("reading the recording stopped {0} into it (nothing new for {1} seconds) - the drive may have gone to sleep or been disconnected; make sure it is awake and connected, then press Fix and continue, then Continue" -f $Matches[2], $Matches[1])
    }
    if ($message -match '(?i)Voice track detection stopped reporting progress for ([^.]+)\.') {
        # 145: the helper's watchdog stopped voice detection while it was
        # reading or listening to the recording. Another track would not help.
        return ("voice detection stopped making progress while reading or listening to the recording (nothing new for {0}) - the drive may have gone to sleep or been disconnected; make sure it is awake and connected, then press Fix and continue, then Continue" -f $Matches[1].Trim())
    }
    if ($message -match '(?i)automatic voice detection failed') {
        return "voice detection could not run - press Fix and continue, right-click this recording, choose the track with your voice, then press Continue"
    }
    if ($message -match '(?i)no audio streams') {
        return "the recording has no audio"
    }
    if ($message -match '(?i)audio extraction failed') {
        return "the microphone audio could not be read from the recording"
    }
    if ($message -match '(?i)Whisper|transcri') {
        return "transcription failed (see the run log for details)"
    }
    if ([string]::IsNullOrWhiteSpace($message)) {
        return ("status {0}" -f $status)
    }
    $firstSentence = ($message -split '(?<=\.)\s', 2)[0]
    return $firstSentence
}

function Invoke-CodexEvidencePackageBatch {
    param(
        [string]$InputPath,
        [string]$OutputFolder,
        [string]$PythonCommand,
        [string]$FFmpegExe,
        [string]$FFprobeExe,
        [string]$ModelName,
        [string]$LanguageCode,
        [bool]$CanUseWhisperGpu,
        [int]$WhisperTimeoutSeconds = 0,
        [int]$HeartbeatSeconds = 10,
        [switch]$Recurse,
        [switch]$OverwriteTranscripts,
        [double]$PreContextSeconds = 120,
        [double]$PostContextSeconds = 240,
        [double]$NarrationContextPreSeconds = 120,
        [double]$NarrationContextPostSeconds = 600,
        [double]$NarrationPauseThresholdSeconds = 30,
        [bool]$NarrationStopAtNextTicketBoundary = $true,
        [bool]$FragmentedNarrationMode = $true,
        [double[]]$FrameOffsets = @(-60, -30, 0, 30, 90, 120),
        [int]$AudioStreamIndex = 0,
        [string]$AudioStreamSelectionsJson = "",
        [string]$TrackRoles = "",
        [double]$FrameCadenceSeconds = 10,
        [int]$MaxFramesPerCandidate = 60,
        [int]$MaxItems = 50,
        [array]$RenderCandidateIds = @(),
        [array]$RenderOutcomeIds = @(),
        [ValidateSet("Transcription", "Consolidation", "Package")]
        [string]$StopAfter = "Package",
        [ValidateSet("Compact", "Dense")]
        [string]$RenderDensity = "Compact",
        [ValidateSet("Auto", "Sparse", "Continuous")]
        [string]$SpeechMode = "Auto",
        [string]$ResumeRoot = "",
        [string]$HandoffMode = "Local",
        [int]$PortableZipMaxMb = 100,
        [string]$PanelCropMode = "Auto",
        [string]$InvocationMode = "standalone",
        [string]$TargetRepo = "",
        [string]$RepoMapPath = "",
        [string]$RepoHintMode = "auto",
        [array]$CustomMarkers = @(),
        [array]$CustomDomainTerms = @(),
        [string]$TranscriptionGlossaryPath = "",
        [array]$TranscriptionGlossaryEntries = @(),
        [bool]$AudioStreamSelectionConfirmed = $false,
        [bool]$PreserveSupportingAudio = $false,
        [string]$PanelRoleMapPath = "",
        [hashtable]$RunMetadata = @{},
        [string]$ExistingTranscriptJsonPath = "",
        [string]$ExistingTranscriptSrtPath = "",
        [string]$ExistingTranscriptTextPath = "",
        [string]$ExistingAudioPath = "",
        [string]$ExistingTranscriptSource = "",
        # How long voice detection may report nothing new before it is
        # stopped (145). Tests set it short.
        [int]$VoiceDetectionStallTimeoutSeconds = 600
    )
    # 214: Full Review runs these inside its own recording; give it back when done, so Skip still finds it.
    $mmOuterSourcePath = [string]$script:MMCurrentSourcePath

    # 201: small review copies started alongside a transcription; see Start-MMBackgroundReviewVideo.
    $script:MMBackgroundReviewVideos = [ordered]@{}
    try {
    if ([string]::IsNullOrWhiteSpace($InputPath)) {
        throw "Codex evidence package mode needs a local source file or folder."
    }

    $sourcePath = Normalize-UserPath $InputPath
    if (-not (Test-Path -LiteralPath $sourcePath)) {
        throw "Codex evidence package source path not found: $sourcePath"
    }

    $sourceItem = Get-Item -LiteralPath $sourcePath
    $videos = @(Get-VideoFilesFromPath -Path $sourcePath -Recurse:$Recurse)
    if (-not $videos -or $videos.Count -eq 0) {
        throw "No supported video files found for Codex evidence package mode. Supported extensions include .mkv."
    }
    $videos = @(Select-MMDistinctVideos -Videos $videos)

    $audioStreamSelections = $null
    if (-not [string]::IsNullOrWhiteSpace($AudioStreamSelectionsJson)) {
        try {
            $audioStreamSelections = $AudioStreamSelectionsJson | ConvertFrom-Json
        }
        catch {
            throw ("EvidenceAudioStreamSelectionsJson is invalid JSON: {0}" -f $_.Exception.Message)
        }
    }

    $outputRoot = if ([string]::IsNullOrWhiteSpace($ResumeRoot)) {
        Join-Path $OutputFolder "codex-evidence-package"
    }
    else {
        Normalize-UserPath $ResumeRoot
    }
    $stageManifestPath = Join-Path $outputRoot "WORKFLOW3_STAGE_MANIFEST.json"
    $resumeManifest = $null
    if (-not [string]::IsNullOrWhiteSpace($ResumeRoot) -and -not (Test-Path -LiteralPath $stageManifestPath -PathType Leaf)) {
        throw "EvidenceResumeRoot does not contain WORKFLOW3_STAGE_MANIFEST.json. Refusing an unverified resume."
    }
    if (-not [string]::IsNullOrWhiteSpace($ResumeRoot)) {
        try {
            $resumeManifest = Get-Content -LiteralPath $stageManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        }
        catch {
            throw ("EvidenceResumeRoot stage manifest could not be read: {0}" -f $_.Exception.Message)
        }
        if ([string]$resumeManifest.language -ne [string]$LanguageCode -or [string]$resumeManifest.narration_speech_mode -ne [string]$SpeechMode -or [string]$resumeManifest.profile_setup_name -ne [string]$RunMetadata.profile_setup_name -or [string]$resumeManifest.render_density -ne [string]$RenderDensity) {
            throw "EvidenceResumeRoot language, narration mode, profile, or render density does not match this run."
        }
    }
    $transcriptSourcesFolder = Join-Path (Join-Path $outputRoot "transcript") "sources"
    $audioFolder = Join-Path $outputRoot "audio"
    # 196: voice detection keeps the decoded audio of the track it chose
    # here, so the narration is not read from the recording a second time.
    # It is on the same drive as the narration WAV, so using it is a rename.
    # No source id in the path: the ids are sized to fit audio\<id>.audio.wav.
    # The package ZIP takes .wav files, so this folder is removed after each
    # recording, whatever happened to it.
    $voiceWavFolder = Join-Path $audioFolder "voice-work"
    Ensure-Directory $outputRoot
    Ensure-Directory $transcriptSourcesFolder
    Ensure-Directory $audioFolder

    $script:CurrentLogFile = Join-Path $outputRoot "codex_evidence_run.log"
    "==== Codex evidence package run started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====" | Set-Content -LiteralPath $script:CurrentLogFile -Encoding UTF8
    # 201: what a run that was stopped left in the temp folder goes before this one starts.
    $null = Remove-MMOrphanedScratch

    Write-Phase -Name "Codex Evidence Package" -Detail ("Processing {0} local video item(s)" -f $videos.Count)
    Write-Host "This mode scans existing recordings after capture; it does not require interaction while driving or recording." -ForegroundColor Cyan
    Write-Log ("Codex evidence source: {0}" -f $sourcePath)
    Write-Log ("Codex evidence output: {0}" -f $outputRoot)
    Write-Log ("Codex evidence recurse: {0}" -f ([bool]$Recurse))
    Write-Log ("Transcript overwrite: {0}" -f ([bool]$OverwriteTranscripts))
    Write-Log ("Evidence context window: {0}s before / {1}s after" -f $PreContextSeconds, $PostContextSeconds)
    Write-Log ("Narration context: {0}s before / {1}s after; pause threshold {2}s; fragmented={3}; stop at next ticket boundary={4}" -f $NarrationContextPreSeconds, $NarrationContextPostSeconds, $NarrationPauseThresholdSeconds, $FragmentedNarrationMode, $NarrationStopAtNextTicketBoundary)
    Write-Log "Evidence merge gap: 90s"
    Write-Log ("Evidence frame offsets: {0}" -f (@($FrameOffsets) -join ", "))
    Write-Log ("Evidence frame cadence: every {0}s, max {1} frames per candidate" -f $FrameCadenceSeconds, $MaxFramesPerCandidate)
    Write-Log ("Evidence panel crops: {0}" -f (Get-EvidencePanelCropModeSummary -Mode $PanelCropMode))
    Write-Log ("Codex evidence invocation mode: {0}" -f $InvocationMode)
    Write-Log ("Evidence audio stream index: {0}" -f $AudioStreamIndex)
    $trackRoleSetting = ConvertTo-MMTrackRoles -Text $TrackRoles
    $trackRolesKey = Get-MMTrackRolesKey -Roles $trackRoleSetting
    Write-Log ("Narration track setting for recordings without track names: {0}" -f $(if ($trackRolesKey) { $trackRolesKey } else { "every track Auto" }))
    Write-Log ("Evidence max items: {0}" -f $MaxItems)
    Write-Log ("Evidence selected render candidate IDs: {0}" -f $(if (@($RenderCandidateIds).Count -eq 0) { "automatic first candidates within render budget" } else { @($RenderCandidateIds) -join ", " }))
    Write-Log ("Evidence agent handoff mode: {0}; portable ZIP max: {1} MB" -f $HandoffMode, $PortableZipMaxMb)
    Write-Log ("Evidence repo hint mode: {0}" -f $RepoHintMode)
    Write-Log ("Evidence target repo hint: {0}" -f $(if ([string]::IsNullOrWhiteSpace($TargetRepo)) { "none" } else { $TargetRepo }))
    Write-Log ("Evidence repo map path: {0}" -f $(if ([string]::IsNullOrWhiteSpace($RepoMapPath)) { "none" } else { $RepoMapPath }))
    Write-Log ("Evidence custom marker count: {0}" -f @($CustomMarkers).Count)
    Write-Log ("Evidence custom domain-term count: {0}" -f @($CustomDomainTerms).Count)
    $TranscriptionGlossaryEntries = @(ConvertTo-MMWordList -Values @($TranscriptionGlossaryEntries))
    Write-Log ("Evidence transcription glossary entry count: {0}" -f @($TranscriptionGlossaryEntries).Count)
    Write-Log ("Evidence operator narration stream confirmed: {0}" -f $AudioStreamSelectionConfirmed)
    $transcriptionInitialPrompt = Get-EvidenceTranscriptionInitialPrompt `
        -GlossaryPath $TranscriptionGlossaryPath `
        -GlossaryEntries @($TranscriptionGlossaryEntries)
    if ($InvocationMode -eq "full-review-addon" -and -not [string]::IsNullOrWhiteSpace($ExistingTranscriptJsonPath)) {
        Write-Log ("Full Review transcript reuse candidate: {0}" -f $ExistingTranscriptJsonPath)
    }

    $manifestEntries = New-Object System.Collections.Generic.List[object]
    $sourceRoot = if ($sourceItem.PSIsContainer) { $sourceItem.FullName } else { Split-Path -Path $sourceItem.FullName -Parent }
    $processedIndex = 0
    # Microphone tracks clearly identified earlier in this run. Recordings in
    # one run usually come from the same rig, so when no usual track is known
    # the track found earlier breaks a tie between voices (105).
    $runVoiceOrdinalCounts = @{}

    foreach ($video in $videos) {
        # 201: a review copy still being made of the recording before is finished first.
        Wait-MMBackgroundReviewVideos -HeartbeatSeconds $HeartbeatSeconds
        $processedIndex += 1
        $sourceId = Get-TranscriptOnlySourceId -VideoPath $video.FullName
        $physicalSourceId = Get-BoundedTranscriptPhysicalSourceId -SourceId $sourceId -OutputRoot $outputRoot
        $videoSourceRoot = if ($sourceItem.Extension -ieq ".mmlist") { $video.DirectoryName } else { $sourceRoot }
        $sourceIdentifier = Get-TranscriptOnlySourceIdentifier -VideoPath $video.FullName -SourceRoot $videoSourceRoot
        $jsonPath = Join-Path $transcriptSourcesFolder ("{0}.transcript.json" -f $physicalSourceId)
        $srtPath = Join-Path $transcriptSourcesFolder ("{0}.transcript.srt" -f $physicalSourceId)
        $txtPath = Join-Path $transcriptSourcesFolder ("{0}.transcript.txt" -f $physicalSourceId)
        $workingAudioWavPath = Join-Path $audioFolder ("{0}.audio.wav" -f $physicalSourceId)
        $audioPath = Join-Path $audioFolder ("{0}.audio.flac" -f $physicalSourceId)
        $audioStatus = "pending"
        $audioErrorMessage = ""
        $audioMethod = "extracted_audio"
        $transcriptionInputPath = ""
        $transcriptionInputMethod = "extracted_audio"
        $transcriptReuseStatus = "not_reused"
        $reusedTranscriptJsonPath = ""
        $reusedTranscriptSrtPath = ""
        $reusedTranscriptTextPath = ""
        $audioStreams = @()
        $selectedAudioStream = $null
        $status = "failed"
        $errorMessage = ""
        $durationSeconds = ""
        $noNarrationDetected = $false
        $videoAudioStreamIndex = [int]$AudioStreamIndex
        $videoAudioSelectionConfirmed = [bool]$AudioStreamSelectionConfirmed
        $videoAudioConfirmationSource = if ($videoAudioSelectionConfirmed) { "explicit parameter" } else { "unconfirmed" }
        # Audio voice detection kept for this recording only; anything left
        # by a run that crashed is not this recording's.
        $keptVoiceWavs = @()
        # 199: this recording's own voice-track result only; never the one before it.
        $voiceDetection = $null
        Remove-MMScratchPath -Path $voiceWavFolder
        if ($null -ne $audioStreamSelections) {
            $selectionProperty = $audioStreamSelections.PSObject.Properties | Where-Object {
                [string]::Equals([string]$_.Name, [string]$video.FullName, [System.StringComparison]::OrdinalIgnoreCase)
            } | Select-Object -First 1
            if ($null -ne $selectionProperty -and $null -ne $selectionProperty.Value) {
                $videoAudioStreamIndex = [int]$selectionProperty.Value.audioOrdinal
                $videoAudioSelectionConfirmed = $true
                $videoAudioConfirmationSource = [string]$selectionProperty.Value.confirmationSource
            }
        }

        Write-Host ("[{0}/{1}] Codex evidence transcript: {2}" -f $processedIndex, $videos.Count, $video.Name) -ForegroundColor Cyan
        Write-Log ("Codex evidence item {0}/{1}: {2}" -f $processedIndex, $videos.Count, $video.FullName)
        if ($physicalSourceId -ne $sourceId) {
            Write-Log ("Transcript physical source ID shortened for Windows path compatibility; logical source ID remains in manifests. logical={0}; physical={1}" -f $sourceId, $physicalSourceId)
        }
        Write-MMProgressV1 -Phase "Transcription" -PhaseIndex 1 -PhaseCount 4 -SourceId $sourceId -SourceName $video.Name -Completed ($processedIndex - 1) -Total $videos.Count -SourceCompleted ($processedIndex - 1) -SourceTotal $videos.Count -ProgressKind work_units -Activity ("Preparing operator narration for {0}" -f $video.Name)
        $script:MMCurrentSourcePath = $video.FullName
        $script:MMSkipRequested = $false

        try {
            # 114/115: a recording skipped before it started is never
            # touched; a pause holds here before the next recording begins.
            $null = Invoke-MMRunControlCheck -StepName "the next recording"
            try {
                $durationValue = Get-VideoDurationSeconds -FFprobeExe $FFprobeExe -VideoPath $video.FullName
                if ($durationValue -gt 0) {
                    $durationSeconds = ([math]::Round($durationValue, 3)).ToString([System.Globalization.CultureInfo]::InvariantCulture)
                }
            }
            catch {
                Write-Log ("Duration probe failed for Codex evidence item '{0}': {1}" -f $video.FullName, $_.Exception.Message) "WARN"
            }

            $canReuseFullReviewTranscript = (
                $InvocationMode -eq "full-review-addon" -and
                $videos.Count -eq 1 -and
                -not $OverwriteTranscripts -and
                -not [string]::IsNullOrWhiteSpace($ExistingTranscriptJsonPath) -and
                -not [string]::IsNullOrWhiteSpace($ExistingTranscriptSrtPath) -and
                -not [string]::IsNullOrWhiteSpace($ExistingTranscriptTextPath) -and
                (Test-Path -LiteralPath $ExistingTranscriptJsonPath -PathType Leaf) -and
                (Test-Path -LiteralPath $ExistingTranscriptSrtPath -PathType Leaf) -and
                (Test-Path -LiteralPath $ExistingTranscriptTextPath -PathType Leaf)
            )

            try {
                $audioStreams = @(Get-VideoAudioStreams -FFprobeExe $FFprobeExe -VideoPath $video.FullName)
                if ($audioStreams.Count -gt 0) {
                    foreach ($stream in $audioStreams) {
                        Write-Log ("Codex evidence audio stream: ordinal={0}; stream_index={1}; map={2}; codec={3}; channels={4}; layout={5}; language={6}; title={7}" -f `
                            [int]$stream.ordinal, [int]$stream.stream_index, [string]$stream.ffmpeg_map, [string]$stream.codec_name, [int]$stream.channels, [string]$stream.channel_layout, [string]$stream.language, [string]$stream.title)
                    }
                    $operatorConfirmedThisFile = $videoAudioSelectionConfirmed -and ($videoAudioConfirmationSource -in @("operator", "explicit parameter"))
                    # 196: a one-track recording is looked at too when its only track has a name
                    # (other than OBS's own "Track1") or a role in the setting, so a track that is
                    # never narration is never transcribed. A plain one-track recording is used as before.
                    $onlyTrackHasRole = $audioStreams.Count -eq 1 -and (
                        $trackRoleSetting.ContainsKey("1") -or (
                            -not [string]::IsNullOrWhiteSpace([string]$audioStreams[0].title) -and
                            [string]$audioStreams[0].title -notmatch '^\s*track\s*\d+\s*$'))
                    if (($audioStreams.Count -gt 1 -or $onlyTrackHasRole) -and $InvocationMode -ne "review-new-videos" -and -not $operatorConfirmedThisFile) {
                        # 94: the operator's voice is not always on the same track, so a
                        # remembered track number is only a fallback. Listen to every
                        # track of THIS recording and pick the one with isolated speech.
                        $preferredOrdinals = @()
                        $runUsualOrdinals = @()
                        if ($videoAudioSelectionConfirmed -or [int]$videoAudioStreamIndex -gt 0) {
                            $preferredOrdinals = @([int]$videoAudioStreamIndex)
                        }
                        elseif ($runVoiceOrdinalCounts.Count -gt 0) {
                            $runUsual = ($runVoiceOrdinalCounts.GetEnumerator() | Sort-Object -Property Value -Descending | Select-Object -First 1).Key
                            $runUsualOrdinals = @([int]$runUsual)
                        }
                        # 264: this recording's own remembered pick (the saved answer for its track layout, else
                        # the run's usual track, else none; Track 1 counts), and what the library already knows.
                        $knownVoice = Get-MMKnownVoiceDetection -PythonCommand $PythonCommand -FFprobeExe $FFprobeExe -VideoPath $video.FullName `
                            -PreferredOrdinals $preferredOrdinals -FallbackOrdinals $runUsualOrdinals -UseSavedLayouts ($preferredOrdinals.Count -eq 0) `
                            -TrackRolesText ([string]$TrackRoles) -HeartbeatSeconds $HeartbeatSeconds
                        if ($null -ne $knownVoice) {
                            $preferredOrdinals = @(@($knownVoice.preferred_ordinals) | Where-Object { $null -ne $_ } | ForEach-Object { [int]$_ })
                        }
                        elseif ($preferredOrdinals.Count -eq 0) {
                            $preferredOrdinals = $runUsualOrdinals
                        }
                        if ($runUsualOrdinals.Count -gt 0 -and ($preferredOrdinals -join ",") -eq ($runUsualOrdinals -join ",")) {
                            Write-Log ("No usual microphone track is remembered; Track {0} was your microphone earlier in this run." -f ([int]$runUsualOrdinals[0] + 1))
                        }
                        $voiceCachePath = Join-Path $transcriptSourcesFolder ("{0}.voice.json" -f $physicalSourceId)
                        $voiceDetection = $null
                        # Your confirmed answer comes before anything an earlier run of this package heard.
                        if ($null -eq $knownVoice -or [string]$knownVoice.decided_by -ne "confirmed") {
                            $voiceDetection = Read-MMSavedVoiceDetection -Path $voiceCachePath -VideoPath $video.FullName -PreferredOrdinals $preferredOrdinals -TrackRolesKey $trackRolesKey
                        }
                        if ($null -ne $voiceDetection) {
                            Write-Log ("Reusing the voice-track result from an earlier run of this package for '{0}' ({1})." -f $video.Name, [string]$voiceDetection.status)
                        }
                        elseif ($null -ne $knownVoice -and $null -ne $knownVoice.answer) {
                            $voiceDetection = $knownVoice.answer
                            Write-Log ("The library already knows the voice track of '{0}' ({1}, {2}); nothing is listened to." -f $video.Name, [string]$voiceDetection.status, [string]$knownVoice.decided_by)
                            # The package keeps its own resume guard (115), as for a track it heard itself. Your
                            # answer is not that: it stays in the library, so Automatic can take it back.
                            if ([string]$knownVoice.decided_by -ne "confirmed") {
                                Save-MMVoiceDetection -Path $voiceCachePath -VideoPath $video.FullName -Detection $voiceDetection -PreferredOrdinals $preferredOrdinals -TrackRolesKey $trackRolesKey
                            }
                        }
                        else {
                            # 196: when Full Review's transcript is reused nothing is
                            # transcribed here, so no audio is kept only to be deleted.
                            $keepVoiceWavDir = if ($canReuseFullReviewTranscript) { "" } else { $voiceWavFolder }
                            $voiceDetection = Invoke-VoiceTrackDetection `
                                -PreferredOrdinals $preferredOrdinals `
                                -TrackRoles $trackRoleSetting `
                                -PythonCommand $PythonCommand `
                                -FFmpegExe $FFmpegExe `
                                -FFprobeExe $FFprobeExe `
                                -VideoPath $video.FullName `
                                -DurationSeconds $(if ([string]::IsNullOrWhiteSpace($durationSeconds)) { 0 } else { [double]::Parse($durationSeconds, [System.Globalization.CultureInfo]::InvariantCulture) }) `
                                -PreferGpu $CanUseWhisperGpu `
                                -HeartbeatSeconds $HeartbeatSeconds `
                                -StallTimeoutSeconds $VoiceDetectionStallTimeoutSeconds `
                                -KeepWavDir $keepVoiceWavDir
                            if ($voiceDetection -and $null -ne $voiceDetection.PSObject.Properties["kept_track_wavs"]) {
                                $keptVoiceWavs = @($voiceDetection.kept_track_wavs | Where-Object { $null -ne $_ })
                                $voiceDetection.PSObject.Properties.Remove("kept_track_wavs")
                            }
                            if ($voiceDetection -and ([string]$voiceDetection.status -in @("selected", "no_narration_found", "uncertain"))) {
                                Save-MMVoiceDetection -Path $voiceCachePath -VideoPath $video.FullName -Detection $voiceDetection -PreferredOrdinals $preferredOrdinals -TrackRolesKey $trackRolesKey
                            }
                        }
                        $voiceStatus = if ($voiceDetection) { [string]$voiceDetection.status } else { "error" }
                        # 196: the remembered track is no fallback when its name or the setting says
                        # it is never narration, or it is the full mix kept as a last resort.
                        $rememberedNumber = [string]([int]$videoAudioStreamIndex + 1)
                        $rememberedRole = ""
                        if ($voiceDetection -and $null -ne $voiceDetection.PSObject.Properties["track_roles"] -and $null -ne $voiceDetection.track_roles) {
                            $roleProperty = $voiceDetection.track_roles.PSObject.Properties[$rememberedNumber]
                            if ($null -ne $roleProperty) { $rememberedRole = [string]$roleProperty.Value }
                        }
                        if ([string]::IsNullOrWhiteSpace($rememberedRole) -and $trackRoleSetting.ContainsKey($rememberedNumber)) {
                            $rememberedRole = [string]$trackRoleSetting[$rememberedNumber]
                        }
                        $rememberedIsNotNarration = $rememberedRole -in @("never", "full_mix")
                        if ($voiceStatus -eq "selected") {
                            $detectedOrdinal = [int]$voiceDetection.selected_ordinal
                            if ($videoAudioSelectionConfirmed -and $detectedOrdinal -ne [int]$videoAudioStreamIndex) {
                                Write-Log ("Remembered narration Track {0} replaced by detected Track {1} for '{2}'." -f ($videoAudioStreamIndex + 1), ($detectedOrdinal + 1), $video.Name) "WARN"
                            }
                            $videoAudioStreamIndex = $detectedOrdinal
                            $videoAudioSelectionConfirmed = $true
                            if ([double]$voiceDetection.confidence -ge 0.9) {
                                $runVoiceOrdinalCounts[$detectedOrdinal] = 1 + [int]$runVoiceOrdinalCounts[$detectedOrdinal]
                            }
                            $videoAudioConfirmationSource = if ($null -ne $knownVoice -and [string]$knownVoice.decided_by -eq "confirmed") { "operator" } else { ("automatic voice detection: {0}" -f [string]$voiceDetection.explanation) }
                            # 196: what decided it ("from track name", "from your setting", "auto-detected").
                            $decidedByText = if ($null -ne $voiceDetection.PSObject.Properties["decided_by_text"] -and -not [string]::IsNullOrWhiteSpace([string]$voiceDetection.decided_by_text)) { [string]$voiceDetection.decided_by_text } else { "auto-detected" }
                            Write-Host ("  Voice found on Track {0} ({1})." -f ($detectedOrdinal + 1), $decidedByText) -ForegroundColor Green
                        }
                        elseif ($voiceStatus -eq "no_narration_found") {
                            $status = "no_narration"
                            $errorMessage = [string]$voiceDetection.explanation
                            $noNarrationDetected = $true
                            Write-Host ("  No narration found in this recording: {0}" -f $errorMessage) -ForegroundColor Yellow
                            throw [System.OperationCanceledException]::new("no_narration")
                        }
                        elseif ($videoAudioSelectionConfirmed -and -not (
                                # 142: speech only on busy tracks, and none of it on the
                                # remembered track. Transcribing that track would be a
                                # guess against what was just heard, so the operator is asked.
                                $voiceStatus -eq "uncertain" -and
                                [string]$voiceDetection.uncertain_reason -eq "speech_on_busy_tracks" -and
                                -not (@(@($voiceDetection.competing_ordinals) | ForEach-Object { [int]$_ }) -contains [int]$videoAudioStreamIndex)
                            ) -and -not $rememberedIsNotNarration) {
                            Write-Log ("Voice detection was {0} for '{1}'; using the remembered narration Track {2}." -f $voiceStatus, $video.Name, ($videoAudioStreamIndex + 1)) "WARN"
                            $videoAudioConfirmationSource = ("{0}; automatic detection {1}" -f $videoAudioConfirmationSource, $voiceStatus)
                        }
                        elseif ($voiceStatus -eq "uncertain") {
                            # 142: the explanation says why (two different voices, or
                            # speech only on tracks busy with other sound), so this
                            # sentence claims neither. "Multiple audio tracks:" is kept:
                            # the problem reason and the rethrow below match on it.
                            throw ("Multiple audio tracks: the app could not tell which track is your microphone in '{0}'. {1} In Find my bug reports, press Fix and continue, right-click this recording, choose the track with your voice, then press Continue. The backend will not guess." -f $video.Name, [string]$voiceDetection.explanation)
                        }
                        else {
                            $voiceFailure = $voiceStatus
                            if ($null -eq $voiceDetection -and -not [string]::IsNullOrWhiteSpace([string]$script:MMVoiceDetectionError)) {
                                $voiceFailure = "{0}: {1}" -f $voiceStatus, ([string]$script:MMVoiceDetectionError).Trim()
                            }
                            throw ("Multiple audio tracks were detected for '{0}' and automatic voice detection failed ({1}). Choose the microphone track for this recording in the Workbench. The backend will not silently use Track 1." -f $video.Name, $voiceFailure)
                        }
                    }
                    $selectedAudioStream = $audioStreams | Where-Object { [int]$_.ordinal -eq [int]$videoAudioStreamIndex } | Select-Object -First 1
                    if ($null -eq $selectedAudioStream) {
                        throw ("Requested operator narration Track {0} (audio ordinal {1}), but only {2} audio stream(s) were detected for '{3}'. Re-inspect and confirm this source." -f ($videoAudioStreamIndex + 1), $videoAudioStreamIndex, $audioStreams.Count, $video.FullName)
                    }
                    if ($audioStreams.Count -gt 1) {
                        Write-Log ("Operator narration selected: Track {0}; audio ordinal={1}; stream_index={2}; map={3}; title={4}; confirmation={5}. Other streams remain supporting evidence only." -f ($videoAudioStreamIndex + 1), $videoAudioStreamIndex, [int]$selectedAudioStream.stream_index, [string]$selectedAudioStream.ffmpeg_map, [string]$selectedAudioStream.title, $videoAudioConfirmationSource)
                    }
                }
                else {
                    Write-Log ("No audio streams detected for Codex evidence item '{0}'." -f $video.FullName) "WARN"
                }
            }
            catch [System.OperationCanceledException] {
                throw
            }
            catch {
                $probeMessage = [string]$_.Exception.Message
                if ((Test-MMSkipException $_) -or $probeMessage.StartsWith("Multiple audio tracks") -or $probeMessage.StartsWith("Requested operator narration")) {
                    throw
                }
                throw ("Audio stream probe failed for Codex evidence item '{0}': {1}" -f $video.FullName, $probeMessage)
            }

            if ($canReuseFullReviewTranscript) {
                $jsonPath = $ExistingTranscriptJsonPath
                $srtPath = $ExistingTranscriptSrtPath
                $txtPath = $ExistingTranscriptTextPath
                $reusedTranscriptJsonPath = $ExistingTranscriptJsonPath
                $reusedTranscriptSrtPath = $ExistingTranscriptSrtPath
                $reusedTranscriptTextPath = $ExistingTranscriptTextPath
                $transcriptReuseStatus = "reused_full_review_transcript"
                $status = "skipped"
                $transcriptionInputPath = $ExistingAudioPath
                $transcriptionInputMethod = if ([string]::IsNullOrWhiteSpace($ExistingTranscriptSource)) { "full_review_existing_transcript" } else { $ExistingTranscriptSource }
                if (-not [string]::IsNullOrWhiteSpace($ExistingAudioPath) -and (Test-Path -LiteralPath $ExistingAudioPath -PathType Leaf)) {
                    $audioPath = $ExistingAudioPath
                    $audioStatus = "reused_full_review"
                    $audioMethod = "reused_full_review_audio"
                }
                else {
                    $audioStatus = "not_available"
                    $audioMethod = "reused_full_review_transcript_only"
                    $transcriptionInputPath = ""
                }
                Write-Log ("Reusing Full Review transcript/audio for Codex evidence item '{0}' (transcript source: {1}; audio status: {2})." -f $video.FullName, $transcriptionInputMethod, $audioStatus)
            }
            else {
            $transcriptTripleExists = Test-MMTranscribedTriple -JsonPath $jsonPath -SrtPath $srtPath -TxtPath $txtPath -AudioOrdinal ([int]$videoAudioStreamIndex) -RequireTrackRecord:($videoAudioConfirmationSource -eq "operator")
            if ($transcriptTripleExists -and -not $OverwriteTranscripts) {
                $status = "skipped"
                # A transcript blocked as invented stays blocked when reused.
                $reusedQualityPath = Get-MMTranscriptSidePath -JsonPath $jsonPath -Kind "quality"
                if (Test-Path -LiteralPath $reusedQualityPath -PathType Leaf) {
                    try {
                        if ([bool]((Get-Content -LiteralPath $reusedQualityPath -Raw -Encoding UTF8 | ConvertFrom-Json).quality_blocking)) {
                            $status = "quality_blocked"
                        }
                    }
                    catch {
                        throw ("Sparse narration quality audit could not be read: {0}" -f $_.Exception.Message)
                    }
                }
                if (-not (Test-Path -LiteralPath $audioPath -PathType Leaf) -and (Test-Path -LiteralPath $workingAudioWavPath -PathType Leaf)) {
                    $null = Convert-TranscriptSourceWavToFlac -FFmpegExe $FFmpegExe -InputWav $workingAudioWavPath -OutputFlac $audioPath -HeartbeatSeconds $HeartbeatSeconds
                }
                $audioStatus = if (Test-Path -LiteralPath $audioPath) { "skipped" } else { "not_available" }
                $transcriptionInputPath = if (Test-Path -LiteralPath $audioPath) { $audioPath } else { "" }
                $audioMethod = if (Test-Path -LiteralPath $audioPath) { "lossless_flac" } else { "not_available" }
                $transcriptionInputMethod = "existing_transcript"
                $transcriptReuseStatus = "reused_codex_transcript"
                Write-Log ("Skipping existing Codex evidence transcript triple for {0}" -f $video.FullName)
            }
            else {
                $madeFromTrack = Get-MMTranscribedTrack -JsonPath $jsonPath
                if ($null -ne $madeFromTrack -and $madeFromTrack -ne [int]$videoAudioStreamIndex) {
                    Write-Log ("Transcript of '{0}' was made from Track {1}; transcribing Track {2} instead." -f $video.Name, ($madeFromTrack + 1), ($videoAudioStreamIndex + 1))
                }
                # Nothing already here is proven to be this track's (142): an
                # empty placeholder, another track's transcript, or audio an
                # interrupted run extracted from another track. Extraction and
                # the lossless copy both keep a file that is already there, so
                # it all goes, and this transcription starts clean.
                Remove-MMTranscriptFiles -JsonPath $jsonPath -SrtPath $srtPath -TxtPath $txtPath -AudioPaths @($workingAudioWavPath, $audioPath)

                if ($audioStreams.Count -eq 0) {
                    throw "Codex evidence package mode could not transcribe this source because no audio streams were detected."
                }

                try {
                    # After the clearing above: the audio voice detection kept
                    # is moved in under the narration WAV's own name.
                    $audioExtractionStatus = Export-MMNarrationWav `
                        -FFmpegExe $FFmpegExe `
                        -InputVideo $video.FullName `
                        -OutputWav $workingAudioWavPath `
                        -AudioOrdinal ([int]$videoAudioStreamIndex) `
                        -KeptWavs $keptVoiceWavs `
                        -PythonCommand $PythonCommand `
                        -HeartbeatSeconds $HeartbeatSeconds
                    $audioStatus = if ($audioExtractionStatus -eq "SKIPPED_EXISTING") { "skipped" } else { "completed" }
                    $audioPreparedBy = if ($audioExtractionStatus -eq "REUSED_VOICE_DETECTION") { "audio decoded by voice detection" } else { "extracted audio" }
                    Write-Log ("Codex evidence transcription audio prepared: {0} (method: {1}; Track {2}; audio ordinal: {3})" -f $workingAudioWavPath, $audioPreparedBy, ($videoAudioStreamIndex + 1), $videoAudioStreamIndex)
                }
                catch {
                    $audioStatus = "failed"
                    $audioErrorMessage = $_.Exception.Message
                    throw ("Codex evidence audio extraction failed for '{0}'. Evidence mode will not fall back to raw-video Whisper because that produced untrustworthy transcripts in real validation. {1}" -f $video.FullName, $audioErrorMessage)
                }

                $transcriptionInputPath = $workingAudioWavPath
                $transcriptionInputMethod = "extracted_audio"
                if ($StopAfter -eq "Package") {
                    # 201: the small review copy is made while Whisper works.
                    $null = Start-MMBackgroundReviewVideo -FFmpegExe $FFmpegExe -SourcePath $video.FullName -SourceId $sourceId -AudioOrdinal ([int]$videoAudioStreamIndex) -OutputRoot $outputRoot
                }
                $null = Invoke-PythonWhisperTranscript `
                    -PythonCommand $PythonCommand `
                    -AudioPath $transcriptionInputPath `
                    -TranscriptFolder $transcriptSourcesFolder `
                    -ModelName $ModelName `
                    -LanguageCode $LanguageCode `
                    -FFmpegExe $FFmpegExe `
                    -PreferGpu $CanUseWhisperGpu `
                    -Task "transcribe" `
                    -JsonName ([System.IO.Path]::GetFileName($jsonPath)) `
                    -SrtName ([System.IO.Path]::GetFileName($srtPath)) `
                    -TextName ([System.IO.Path]::GetFileName($txtPath)) `
                    -InitialPrompt $transcriptionInitialPrompt `
                    -NarrationSpeechMode $SpeechMode `
                    -SourceDurationSeconds $(if ([string]::IsNullOrWhiteSpace($durationSeconds)) { 0 } else { [double]::Parse($durationSeconds, [System.Globalization.CultureInfo]::InvariantCulture) }) `
                    -HeartbeatSeconds $HeartbeatSeconds `
                    -WhisperTimeoutSeconds $WhisperTimeoutSeconds `
                    -InteractiveMode:$false `
                    -AllowInteractiveLongRunPrompt:$false

                if (-not ((Test-Path -LiteralPath $jsonPath) -and (Test-Path -LiteralPath $srtPath) -and (Test-Path -LiteralPath $txtPath))) {
                    throw "Whisper completed but the expected transcript JSON/SRT/TXT triple was not found."
                }
                # Which track this transcript is of, so a Continue reuses it
                # only for that track (142).
                Set-MMTranscribedTrack -JsonPath $jsonPath -AudioOrdinal ([int]$videoAudioStreamIndex)
                # 199: drop the lines another track carries at the same moment.
                $null = Invoke-MMNarrationCrossCheck -PythonCommand $PythonCommand -FFmpegExe $FFmpegExe `
                    -VideoPath $video.FullName -TranscriptJsonPath $jsonPath -Detection $voiceDetection `
                    -PreferGpu $CanUseWhisperGpu -HeartbeatSeconds $HeartbeatSeconds

                $null = Convert-TranscriptSourceWavToFlac -FFmpegExe $FFmpegExe -InputWav $workingAudioWavPath -OutputFlac $audioPath -HeartbeatSeconds $HeartbeatSeconds
                $transcriptionInputPath = $audioPath
                $audioMethod = "lossless_flac"

                $qualityPath = Join-Path $transcriptSourcesFolder (([System.IO.Path]::GetFileNameWithoutExtension($jsonPath)) + ".quality.json")
                $qualityBlocking = $false
                if (Test-Path -LiteralPath $qualityPath) {
                    try {
                        $qualityBlocking = [bool]((Get-Content -LiteralPath $qualityPath -Raw -Encoding UTF8 | ConvertFrom-Json).quality_blocking)
                    }
                    catch {
                        throw ("Sparse narration quality audit could not be read: {0}" -f $_.Exception.Message)
                    }
                }
                $status = if ($qualityBlocking) { "quality_blocked" } else { "completed" }
            }
            }
        }
        catch [System.OperationCanceledException] {
            if (-not $noNarrationDetected) { throw }
            $status = "no_narration"
            # 199: a correct result, not a warning; a warning made the run "Complete with warnings".
            Write-Log ("No narration found for '{0}': {1}" -f $video.FullName, $errorMessage)
        }
        catch {
            if ((Test-MMSkipException $_) -or $script:MMSkipRequested -or (Test-MMSourceSkipRequested -SourcePath $video.FullName)) {
                # 114: the operator skipped this recording; not a failure.
                $status = "operator_skipped"
                $errorMessage = "Skipped by you."
                $script:MMSkipRequested = $false
                # 201: nor is a small review copy of it made.
                Stop-MMBackgroundReviewVideo -Entry (Get-MMBackgroundReviewVideo -Path (Get-MMNarrationReviewVideoPath -OutputRoot $outputRoot -SourceId $sourceId))
                # 196: whenever it was skipped, and whatever an earlier run
                # of this package left of it.
                Remove-MMSkippedRecordingFiles -TranscriptFolder $transcriptSourcesFolder -AudioFolder $audioFolder -PhysicalSourceId $physicalSourceId
                Write-Host ("SKIPPED by you: {0}" -f $video.Name) -ForegroundColor Yellow
                # 213: the operator's own choice, not a warning.
                Write-Log ("Skipped by you: '{0}'. Nothing from this recording goes into the package." -f $video.FullName) "INFO"
            }
            else {
                $status = "failed"
                $errorMessage = $_.Exception.Message
                Write-Host ("FAIL Codex evidence transcript {0}" -f $video.FullName) -ForegroundColor Red
                Write-Host $errorMessage -ForegroundColor Red
                Write-Log ("Codex evidence transcript failure for '{0}': {1}" -f $video.FullName, $errorMessage) "ERROR"
            }
        }
        finally {
            # 196: whatever happened to this recording (no narration, a
            # question, a skip, a reused transcript), audio voice detection
            # kept and nothing used must not reach the package.
            Remove-MMScratchPath -Path $voiceWavFolder
            # Nor may the narration WAV. Once transcribed it has been turned
            # into the lossless copy and deleted; one still here belongs to a
            # recording whose transcription failed or was skipped.
            Remove-MMScratchPath -Path $workingAudioWavPath
        }

        [void]$manifestEntries.Add([PSCustomObject]@{
            source_id            = $sourceId
            physical_source_id   = $physicalSourceId
            physical_source_id_shortened = [bool]($physicalSourceId -ne $sourceId)
            source_identifier    = $sourceIdentifier
            source_path          = $video.FullName
            source_filename      = $video.Name
            audio_path           = $audioPath
            audio_status         = $audioStatus
            audio_error_message  = $audioErrorMessage
            audio_method         = $audioMethod
            audio_stream_count   = @($audioStreams).Count
            audio_streams        = @($audioStreams)
            selected_audio_stream_index = [int]$videoAudioStreamIndex
            selected_human_track_number = [int]($videoAudioStreamIndex + 1)
            selected_audio_stream = $selectedAudioStream
            audio_stream_selection_confirmed = [bool]$videoAudioSelectionConfirmed
            audio_stream_confirmation_source = [string]$videoAudioConfirmationSource
            transcript_audio_role = "operator_narration"
            transcription_input_path = $transcriptionInputPath
            transcription_input_method = $transcriptionInputMethod
            transcript_reuse_status = $transcriptReuseStatus
            reused_transcript_json_path = $reusedTranscriptJsonPath
            reused_transcript_srt_path = $reusedTranscriptSrtPath
            reused_transcript_txt_path = $reusedTranscriptTextPath
            raw_video_transcription_used = $false
            transcript_json_path = $jsonPath
            transcript_srt_path  = $srtPath
            transcript_txt_path  = $txtPath
            transcript_raw_json_path = Join-Path $transcriptSourcesFolder (([System.IO.Path]::GetFileNameWithoutExtension($jsonPath)) + ".raw.json")
            transcript_vad_json_path = Join-Path $transcriptSourcesFolder (([System.IO.Path]::GetFileNameWithoutExtension($jsonPath)) + ".vad.json")
            transcript_quality_json_path = Join-Path $transcriptSourcesFolder (([System.IO.Path]::GetFileNameWithoutExtension($jsonPath)) + ".quality.json")
            narration_speech_mode = $SpeechMode
            duration_seconds     = $durationSeconds
            status               = $status
            error_message        = $errorMessage
        })
        # Each recording's own outcome, so the queue shows which ones were
        # used, which had no narration and which failed (105).
        # A usable recording is only "transcribed" here: its screenshots and
        # clips come later, so it is not finished until the run ends.
        $itemState = switch ($status) {
            "completed" { "transcribed" }
            "skipped" { "transcribed" }
            "no_narration" { "no_narration" }
            "operator_skipped" { "skipped" }
            default { "failed" }
        }
        Write-MMProgressV1 -Phase "Transcription" -PhaseIndex 1 -PhaseCount 4 -SourceId $sourceId -SourceName $video.Name -Completed $processedIndex -Total $videos.Count -SourceCompleted $processedIndex -SourceTotal $videos.Count -SourceState $itemState -SourceTerminal:($itemState -ne "transcribed") -ProgressKind work_units -Activity ("Transcription {0}: {1}" -f $status, $video.Name) -LatestArtifactPath $jsonPath
    }
    $script:MMCurrentSourcePath = $mmOuterSourcePath
    # Once more before the package is written, which would take any .wav left here.
    Remove-MMScratchPath -Path $voiceWavFolder
    Remove-MMPackageWavFiles -AudioFolder $audioFolder
    # 114: a recording skipped after its transcript was written is left out
    # of the package too.
    $null = Set-MMSkippedAfterTranscription -Entries @($manifestEntries.ToArray()) -TranscriptFolder $transcriptSourcesFolder -AudioFolder $audioFolder `
        -LogMessage "Skipped by you after transcription: '{0}'. Its transcript is left out of the package."

    $manifestEntryArray = @($manifestEntries.ToArray())
    $completedCount = @($manifestEntries | Where-Object { $_.status -eq "completed" }).Count
    $skippedCount = @($manifestEntries | Where-Object { $_.status -eq "skipped" }).Count
    $failedCount = @($manifestEntries | Where-Object { $_.status -eq "failed" }).Count
    $qualityBlockedCount = @($manifestEntries | Where-Object { $_.status -eq "quality_blocked" }).Count
    $noNarrationCount = @($manifestEntries | Where-Object { $_.status -eq "no_narration" }).Count

    if ($resumeManifest) {
        if ([int]$resumeManifest.source_count -ne $manifestEntryArray.Count) {
            throw "EvidenceResumeRoot source count does not match this run."
        }
        foreach ($entry in $manifestEntryArray) {
            $prior = @($resumeManifest.sources | Where-Object { [string]$_.source_id -eq [string]$entry.source_id }) | Select-Object -First 1
            if (-not $prior) { throw ("EvidenceResumeRoot is missing source identity {0}." -f [string]$entry.source_id) }
            $currentSignature = Get-SourceFileSignature -Path ([string]$entry.source_path)
            if ([string]$prior.source_signature.signature_sha1 -ne [string]$currentSignature.signature_sha1 -or [int]$prior.selected_audio_stream_index -ne [int]$entry.selected_audio_stream_index) {
                throw ("EvidenceResumeRoot identity or confirmed audio mapping changed for source {0}." -f [string]$entry.source_id)
            }
        }
    }

    $stageManifest = [ordered]@{
        schema_version = 1
        completed_stage = "Transcription"
        language = $LanguageCode
        narration_speech_mode = $SpeechMode
        profile_setup_name = [string]$RunMetadata.profile_setup_name
        render_density = $RenderDensity
        source_count = $manifestEntryArray.Count
        sources = @($manifestEntryArray | ForEach-Object {
            $signature = Get-SourceFileSignature -Path ([string]$_.source_path)
            [ordered]@{
                source_id = [string]$_.source_id
                physical_source_id = [string]$_.physical_source_id
                physical_source_id_shortened = [bool]$_.physical_source_id_shortened
                source_signature = $signature
                selected_audio_stream_index = [int]$_.selected_audio_stream_index
                selected_human_track_number = [int]$_.selected_human_track_number
                transcript_json_path = [string]$_.transcript_json_path
                transcript_quality_json_path = [string]$_.transcript_quality_json_path
                status = [string]$_.status
            }
        })
    }
    ($stageManifest | ConvertTo-Json -Depth 10) | Set-Content -LiteralPath $stageManifestPath -Encoding UTF8

    if ($StopAfter -eq "Transcription") {
        # 196: no package is built this time. One an earlier run built in
        # this folder (Continue) holds a recording skipped now, and its ZIP
        # too, so it must not be left looking current.
        $operatorSkippedCount = @($manifestEntryArray | Where-Object { $_.status -eq "operator_skipped" }).Count
        if ($operatorSkippedCount -gt 0) {
            $removedEarlier = Remove-MMUnbuiltPackage -OutputRoot $outputRoot
            if ($removedEarlier -gt 0) {
                Write-Log ("{0} of {1} recording(s) were skipped by you and the run stopped after transcription, so no package was built. Removed {2} item(s) an earlier run left in this package folder; nothing from a skipped recording is in it." -f $operatorSkippedCount, $manifestEntryArray.Count, $removedEarlier) "WARN"
            }
        }
        $transcriptionTerminalState =if ($failedCount -gt 0 -or $qualityBlockedCount -gt 0) { "failed" } else { "succeeded" }
        Write-MMProgressV1 -Phase "Transcription" -PhaseIndex 1 -PhaseCount 4 -Completed $manifestEntryArray.Count -Total $manifestEntryArray.Count -SourceCompleted $manifestEntryArray.Count -SourceTotal $manifestEntryArray.Count -ProgressKind work_units -Activity ("Transcription gate {0}" -f $transcriptionTerminalState) -LatestArtifactPath $stageManifestPath -TerminalState $transcriptionTerminalState
        Write-Phase -Name "Codex Evidence Transcription" -Detail "Stopped after requested transcription gate"
        return [PSCustomObject]@{
            OutputRoot = $outputRoot
            Stage = "Transcription"
            CompletedCount = $completedCount
            SkippedCount = $skippedCount
            FailedCount = $failedCount
            QualityBlockedCount = $qualityBlockedCount
            StageManifestPath = $stageManifestPath
        }
    }
    # Honest failure reporting (94): recordings whose transcript failed or was
    # blocked by the quality gate are left out of bug detection instead of
    # blocking every other recording, and they are named at the end of the run.
    if ($qualityBlockedCount -gt 0) {
        Write-Log ("Transcript quality gate blocked {0} recording(s); they are excluded from bug detection and reported at the end of the run." -f $qualityBlockedCount) "WARN"
        Write-Host ("WARNING: {0} recording(s) produced a transcript that looks invented (for example 'Thank you for watching' on silence). They will not be used." -f $qualityBlockedCount) -ForegroundColor Yellow
    }
    if (($completedCount + $skippedCount) -eq 0) {
        $operatorSkippedCount = @($manifestEntryArray | Where-Object { $_.status -eq "operator_skipped" }).Count
        if ($operatorSkippedCount -gt 0) {
            $removedEarlier = Remove-MMUnbuiltPackage -OutputRoot $outputRoot
            $skipSummary = if ($operatorSkippedCount -eq $manifestEntryArray.Count) { "Every recording was skipped by you" } else { ("{0} of {1} recording(s) were skipped by you and none of the others could be used" -f $operatorSkippedCount, $manifestEntryArray.Count) }
            Write-Log ("{0}, so no package was built. Removed {1} item(s) an earlier run left in this package folder; nothing from a skipped recording is in it." -f $skipSummary, $removedEarlier) "WARN"
        }
        $noUsableLines = @($manifestEntryArray | ForEach-Object { "  - {0}: {1}" -f [string]$_.source_filename, (Get-CodexEvidenceProblemReason -Entry $_) })
        throw ("No usable narration transcript was produced, so no package was built. Recordings:`n{0}" -f ($noUsableLines -join "`n"))
    }

    Write-MMProgressV1 -Phase "Outcome consolidation" -PhaseIndex 2 -PhaseCount 4 -SourceCompleted $manifestEntryArray.Count -SourceTotal $manifestEntryArray.Count -ProgressKind indeterminate -Activity "Classifying mentions and consolidating operator outcomes"
    $detectArguments = @{
        PythonCommand = $PythonCommand
        OutputRoot = $outputRoot
        Sources = $manifestEntryArray
        PreContextSeconds = $PreContextSeconds
        PostContextSeconds = $PostContextSeconds
        NarrationContextPreSeconds = $NarrationContextPreSeconds
        NarrationContextPostSeconds = $NarrationContextPostSeconds
        NarrationPauseThresholdSeconds = $NarrationPauseThresholdSeconds
        NarrationStopAtNextTicketBoundary = $NarrationStopAtNextTicketBoundary
        FragmentedNarrationMode = $FragmentedNarrationMode
        FrameOffsets = @($FrameOffsets)
        FrameCadenceSeconds = $FrameCadenceSeconds
        MaxFramesPerCandidate = $MaxFramesPerCandidate
        MaxItems = $MaxItems
        RenderCandidateIds = @($RenderCandidateIds)
        RenderOutcomeIds = @($RenderOutcomeIds)
        StopAfter = $StopAfter
        RenderDensity = $RenderDensity
        HandoffMode = $HandoffMode
        PortableZipMaxMb = $PortableZipMaxMb
        PanelCropMode = $PanelCropMode
        InvocationMode = $InvocationMode
        TargetRepo = $TargetRepo
        RepoMapPath = $RepoMapPath
        RepoHintMode = $RepoHintMode
        CustomMarkers = @($CustomMarkers)
        CustomDomainTerms = @($CustomDomainTerms)
        TranscriptionGlossaryPath = $TranscriptionGlossaryPath
        TranscriptionGlossaryEntries = @($TranscriptionGlossaryEntries)
        PreserveSupportingAudio = $PreserveSupportingAudio
        PanelRoleMapPath = $PanelRoleMapPath
        RunMetadata = $RunMetadata
        HeartbeatSeconds = $HeartbeatSeconds
    }
    # 196: the Workbench lets the operator skip a recording while its package
    # is built. The same skip check runs again before anything is handed to
    # the package writer; a recording skipped by then is left out, and what
    # was found or rendered from it is found and rendered again without it.
    $packageSkipCheck = @{
        Entries = $manifestEntryArray
        TranscriptFolder = $transcriptSourcesFolder
        AudioFolder = $audioFolder
        LogMessage = "Skipped by you while the package was built: '{0}'. Nothing from this recording goes into the package."
    }
    do {
        $detectResult = Invoke-CodexEvidenceDetectHelper @detectArguments
    } while (@(Set-MMSkippedAfterTranscription @packageSkipCheck).Count -gt 0)
    # The stage manifest says which recordings were skipped in the end.
    $syncStageStatuses = {
        foreach ($stageSource in @($stageManifest.sources)) {
            $finalEntry = @($manifestEntryArray | Where-Object { [string]$_.source_id -eq [string]$stageSource.source_id }) | Select-Object -First 1
            if ($null -ne $finalEntry) { $stageSource.status = [string]$finalEntry.status }
        }
    }
    & $syncStageStatuses

    if ($detectResult.configuration -and $detectResult.configuration.repo_hinting) {
        foreach ($warning in @($detectResult.configuration.repo_hinting.warnings)) {
            if (-not [string]::IsNullOrWhiteSpace([string]$warning)) {
                Write-Log ("Repo hint warning: {0}" -f [string]$warning) "WARN"
                Write-Host ("Repo hint warning: {0}" -f [string]$warning) -ForegroundColor Yellow
            }
        }
    }

    if ($StopAfter -eq "Consolidation") {
        while ($true) {
        Remove-MMPackageWavFiles -AudioFolder $audioFolder
        $writeResult = Invoke-CodexEvidenceWriteHelper `
            -PythonCommand $PythonCommand `
            -OutputRoot $outputRoot `
            -Sources @($detectResult.sources) `
            -Candidates @($detectResult.render_candidates) `
            -UnrenderedCandidates @($detectResult.unrendered_candidates) `
            -ReviewNeeded @($detectResult.review_needed) `
            -Outcomes @($detectResult.outcomes) `
            -Configuration $detectResult.configuration `
            -TruncatedCandidateCount ([int]$detectResult.truncated_candidates_count) `
            -FrameResults @() `
            -AudioResults @() `
            -HeartbeatSeconds $HeartbeatSeconds
        # 196: skipped while the package was being written: it is written
        # again without that recording, as when the run goes on to render.
        $lateSkips = @(Set-MMSkippedAfterTranscription @packageSkipCheck)
        if ($lateSkips.Count -eq 0) { break }
        Remove-MMRenderedEvidence -OutputRoot $outputRoot -DetectResult $detectResult -SkippedEntries $lateSkips
        do {
            $detectResult = Invoke-CodexEvidenceDetectHelper @detectArguments
        } while (@(Set-MMSkippedAfterTranscription @packageSkipCheck).Count -gt 0)
        }
        & $syncStageStatuses
        $stageManifest.completed_stage = "Consolidation"
        $stageManifest.outcome_count = [int]$detectResult.outcome_count
        ($stageManifest | ConvertTo-Json -Depth 10) | Set-Content -LiteralPath $stageManifestPath -Encoding UTF8
        Write-MMProgressV1 -Phase "Outcome consolidation" -PhaseIndex 2 -PhaseCount 4 -OutcomeCompleted ([int]$detectResult.outcome_count) -OutcomeTotal ([int]$detectResult.outcome_count) -ProgressKind stage -Activity "Consolidation complete" -LatestArtifactPath ([string]$writeResult.manifest_path)
        Write-MMProgressV1 -Phase "Outcome consolidation" -PhaseIndex 2 -PhaseCount 4 -OutcomeCompleted ([int]$detectResult.outcome_count) -OutcomeTotal ([int]$detectResult.outcome_count) -ProgressKind stage -Activity "Consolidation gate succeeded" -LatestArtifactPath ([string]$writeResult.manifest_path) -TerminalState succeeded
        Write-Phase -Name "Codex Evidence Consolidation" -Detail "Stopped after requested consolidation gate"
        return [PSCustomObject]@{
            OutputRoot = $outputRoot
            Stage = "Consolidation"
            OutcomeCount = [int]$detectResult.outcome_count
            CandidateCount = [int]$detectResult.detected_candidate_count
            StageManifestPath = $stageManifestPath
            ManifestPath = [string]$writeResult.manifest_path
        }
    }

    while ($true) {
    Write-Phase -Name "Codex Evidence Artifacts" -Detail ("Extracting frames/audio for {0} candidate item(s)" -f [int]$detectResult.candidate_count)
    Write-MMProgressV1 -Phase "Artifact planning" -PhaseIndex 3 -PhaseCount 4 -OutcomeCompleted 0 -OutcomeTotal ([int]$detectResult.outcome_count) -ArtifactCompleted 0 -ArtifactTotal (@($detectResult.frame_tasks).Count + @($detectResult.audio_tasks).Count) -ProgressKind stage -Activity "Planning deduplicated source artifacts"
    $frameResults = Invoke-CodexEvidenceFrameTasks `
        -FFmpegExe $FFmpegExe `
        -FrameTasks @($detectResult.frame_tasks) `
        -HeartbeatSeconds $HeartbeatSeconds `
        -PythonCommand $PythonCommand
    $audioResults = Invoke-CodexEvidenceAudioTasks `
        -FFmpegExe $FFmpegExe `
        -AudioTasks @($detectResult.audio_tasks) `
        -HeartbeatSeconds $HeartbeatSeconds

    # 196: once more, immediately before the package writer.
    $lateSkips = @(Set-MMSkippedAfterTranscription @packageSkipCheck)
    if ($lateSkips.Count -gt 0) {
        Remove-MMRenderedEvidence -OutputRoot $outputRoot -DetectResult $detectResult -SkippedEntries $lateSkips
        do {
            $detectResult = Invoke-CodexEvidenceDetectHelper @detectArguments
        } while (@(Set-MMSkippedAfterTranscription @packageSkipCheck).Count -gt 0)
        continue
    }

    Remove-MMPackageWavFiles -AudioFolder $audioFolder
    $writeResult = Invoke-CodexEvidenceWriteHelper `
        -PythonCommand $PythonCommand `
        -OutputRoot $outputRoot `
        -Sources @($detectResult.sources) `
        -Candidates @($detectResult.render_candidates) `
        -UnrenderedCandidates @($detectResult.unrendered_candidates) `
        -ReviewNeeded @($detectResult.review_needed) `
        -Outcomes @($detectResult.outcomes) `
        -Configuration $detectResult.configuration `
        -TruncatedCandidateCount ([int]$detectResult.truncated_candidates_count) `
        -FrameResults @($frameResults) `
        -AudioResults @($audioResults) `
        -HeartbeatSeconds $HeartbeatSeconds

    $narrationEvidence = Invoke-NarrationEvidence `
        -PythonCommand $PythonCommand `
        -FFmpegExe $FFmpegExe `
        -OutputRoot $outputRoot `
        -Sources @($manifestEntryArray) `
        -PanelCropMode $PanelCropMode `
        -HeartbeatSeconds $HeartbeatSeconds `
        -PruneStale:($HandoffMode -eq "Local")

    # Skipped while the package was being written or its narration visuals
    # made: the package is built again without that recording.
    $lateSkips = @(Set-MMSkippedAfterTranscription @packageSkipCheck)
    if ($lateSkips.Count -eq 0) { break }
    Remove-MMRenderedEvidence -OutputRoot $outputRoot -DetectResult $detectResult -SkippedEntries $lateSkips
    do {
        $detectResult = Invoke-CodexEvidenceDetectHelper @detectArguments
    } while (@(Set-MMSkippedAfterTranscription @packageSkipCheck).Count -gt 0)
    }
    & $syncStageStatuses
    # 196: a recording skipped while the package was built is not counted
    # as transcribed, here or by the check that a usable transcript is left.
    $completedCount = @($manifestEntryArray | Where-Object { $_.status -eq "completed" }).Count
    $skippedCount = @($manifestEntryArray | Where-Object { $_.status -eq "skipped" }).Count
    $failedCount = @($manifestEntryArray | Where-Object { $_.status -eq "failed" }).Count
    $qualityBlockedCount = @($manifestEntryArray | Where-Object { $_.status -eq "quality_blocked" }).Count

    $stageManifest.completed_stage = "Package"
    $stageManifest.outcome_count = [int]$detectResult.outcome_count
    $integrityTotals = $writeResult.artifact_integrity.totals
    $stageManifest.artifact_integrity_status = [string]$writeResult.artifact_integrity.status
    $stageManifest.artifact_planned_reference_count = [int]$integrityTotals.planned_reference_count
    $stageManifest.artifact_deduplicated_count = [int]$integrityTotals.deduplicated_count
    $stageManifest.artifact_renderer_result_count = [int]$integrityTotals.renderer_result_count
    $stageManifest.artifact_written_count = [int]$integrityTotals.written_count
    $stageManifest.artifact_skipped_count = [int]$integrityTotals.skipped_count
    $stageManifest.artifact_failed_count = [int]$integrityTotals.failed_count
    $stageManifest.frame_artifact_count = [int]$writeResult.artifact_integrity.categories.frames.written_count
    $stageManifest.panel_artifact_count = [int]$writeResult.artifact_integrity.categories.panels.written_count
    $stageManifest.audio_artifact_count = [int]$writeResult.artifact_integrity.categories.audio.written_count
    ($stageManifest | ConvertTo-Json -Depth 10) | Set-Content -LiteralPath $stageManifestPath -Encoding UTF8
    $runOutcomes = Get-MMRecordingOutcomeLines -ManifestEntries $manifestEntryArray -DetectedSources @($detectResult.sources)
    $problemRecordings = $runOutcomes.Problems
    $noNarrationRecordings = $runOutcomes.NoNarration
    $packageTerminalState = if ($problemRecordings.Count -gt 0) { "failed" } else { "succeeded" }
    $packageActivity = if ($problemRecordings.Count -gt 0) { ("Package built, but {0} recording(s) could not be used" -f $problemRecordings.Count) } else { "Package rendering and integrity checks succeeded" }
    Write-MMProgressV1 -Phase "Rich rendering" -PhaseIndex 4 -PhaseCount 4 -Completed ([int]$integrityTotals.written_count) -Total ([int]$integrityTotals.deduplicated_count) -OutcomeCompleted ([int]$detectResult.outcome_count) -OutcomeTotal ([int]$detectResult.outcome_count) -ArtifactCompleted ([int]$integrityTotals.written_count) -ArtifactTotal ([int]$integrityTotals.deduplicated_count) -ProgressKind work_units -Activity $packageActivity -LatestArtifactPath ([string]$writeResult.manifest_path) -TerminalState $packageTerminalState

    $confidenceCounts = $writeResult.confidence_counts
    $explicitCount = if ($confidenceCounts) { [int]$confidenceCounts.explicit } else { 0 }
    $likelyCount = if ($confidenceCounts) { [int]$confidenceCounts.likely } else { 0 }
    $weakCount = if ($confidenceCounts) { [int]$confidenceCounts.weak } else { 0 }
    $qualitySummary = $writeResult.quality_summary
    $suspiciousSourceCount = if ($qualitySummary) { [int]$qualitySummary.suspicious_source_count } else { 0 }
    $reviewNeededCount = [int]$writeResult.review_needed_count
    $visualFollowupCount = [int]$writeResult.visual_followup_required_count

    if ($problemRecordings.Count -gt 0) {
        Write-Phase -Name "Codex Evidence Summary" -Detail ("Package INCOMPLETE: {0} of {1} recording(s) could not be used" -f $problemRecordings.Count, $manifestEntryArray.Count)
        Write-Host "Recordings that need attention:" -ForegroundColor Yellow
        foreach ($problemLine in $problemRecordings) {
            Write-Host ("  - {0}" -f $problemLine) -ForegroundColor Yellow
            Write-Log ("Recording needs attention: {0}" -f $problemLine) "WARN"
        }
    }
    else {
        Write-Phase -Name "Codex Evidence Summary" -Detail "Package complete"
    }
    if ($noNarrationRecordings.Count -gt 0) {
        Write-Host "Recordings with no narration, so nothing to report from them:"
        foreach ($noNarrationLine in $noNarrationRecordings) {
            Write-Host ("  - {0}" -f $noNarrationLine)
            Write-Log ("Recording had no narration: {0}" -f $noNarrationLine)
        }
    }
    Write-Host ("Transcripts completed: {0}" -f $completedCount)
    Write-Host ("Transcripts skipped:   {0}" -f $skippedCount)
    Write-Host ("Transcripts failed:    {0}" -f $failedCount)
    Write-Host ("Suspicious transcripts: {0}" -f $suspiciousSourceCount)
    Write-Host ("Candidate tickets:     {0}" -f [int]$writeResult.candidate_count)
    Write-Host ("All detected tickets:  {0}" -f [int]$writeResult.detected_candidate_count)
    Write-Host ("Indexed, not rendered: {0}" -f [int]$writeResult.unrendered_candidate_count)
    if ([int]$writeResult.unrendered_candidate_count -gt 0) {
        Write-Host ("WARNING: Rich evidence render budget left {0} candidate(s) indexed without frames/audio. Review ALL_CANDIDATES.md or rerun selected IDs." -f [int]$writeResult.unrendered_candidate_count) -ForegroundColor Yellow
    }
    Write-Host ("Review-needed items:   {0}" -f $reviewNeededCount)
    Write-Host ("Visual follow-up:      {0}" -f $visualFollowupCount)
    Write-Host ("Confidence counts:     explicit={0}, likely={1}, weak={2}" -f $explicitCount, $likelyCount, $weakCount)
    Write-Host ("Output:                {0}" -f $outputRoot)
    Write-Host ("README_FOR_AI:    {0}" -f [string]$writeResult.readme_path)
    Write-Host ("Quality report:        {0}" -f [string]$writeResult.quality_report_path)
    Write-Host ("Repo routing hints:    {0}" -f [string]$writeResult.repo_routing_hints_markdown_path)
    Write-Host ("Candidate tickets MD:  {0}" -f [string]$writeResult.candidate_tickets_markdown_path)
    Write-Host "This mode scans existing recordings after capture; it does not require interaction while driving or recording." -ForegroundColor Cyan

    if (($completedCount + $skippedCount) -eq 0) {
        throw "Codex evidence package mode produced zero usable transcript outputs. See manifest.json for recorded failures."
    }

    return [PSCustomObject]@{
        OutputRoot        = $outputRoot
        CompletedCount    = $completedCount
        SkippedCount      = $skippedCount
        FailedCount       = $failedCount
        QualityBlockedCount = $qualityBlockedCount
        ProblemCount      = $problemRecordings.Count
        ProblemRecordings = @($problemRecordings.ToArray())
        NoNarrationCount  = $noNarrationRecordings.Count
        NoNarrationRecordings = @($noNarrationRecordings.ToArray())
        CandidateCount    = [int]$writeResult.candidate_count
        DetectedCandidateCount = [int]$writeResult.detected_candidate_count
        UnrenderedCandidateCount = [int]$writeResult.unrendered_candidate_count
        ReviewNeededCount = $reviewNeededCount
        VisualFollowupCount = $visualFollowupCount
        ReadmePath        = [string]$writeResult.readme_path
        CandidateMarkdown = [string]$writeResult.candidate_tickets_markdown_path
        ReviewNeededPath  = [string]$writeResult.review_needed_markdown_path
        QualityReport     = [string]$writeResult.quality_report_path
        RepoRoutingHints   = [string]$writeResult.repo_routing_hints_markdown_path
        ManifestPath      = [string]$writeResult.manifest_path
    }
    }
    finally {
        # Whatever ended the run: no copy is left running, half-written or unwanted.
        Remove-MMUnclaimedBackgroundReviewVideos -All
    }
}

$appVersion = Get-AppVersion

if ($Version) {
    Write-Host ("{0} v{1}" -f $script:AppName, $appVersion) -ForegroundColor Cyan
    return
}

$workflowSelectionCount = 0
foreach ($workflowSelected in @($TranscriptOnly.IsPresent, $CodexEvidencePackage.IsPresent, $ReviewNewVideos.IsPresent, $ArchiveCatalog.IsPresent, $ArchiveCatalogSearch.IsPresent)) {
    if ($workflowSelected) {
        $workflowSelectionCount += 1
    }
}
if ($workflowSelectionCount -gt 1) {
    throw "Choose only one workflow switch: -TranscriptOnly, -CodexEvidencePackage, -ReviewNewVideos, -ArchiveCatalog, or -ArchiveCatalogSearch."
}
if ($IncludeCodexEvidencePackage -and $SkipCodexEvidencePackage) {
    throw "Choose either -IncludeCodexEvidencePackage or -SkipCodexEvidencePackage, not both."
}
if (($ArchiveCatalog -or $ArchiveCatalogSearch) -and ($IncludeCodexEvidencePackage -or $SkipCodexEvidencePackage)) {
    throw "-IncludeCodexEvidencePackage and -SkipCodexEvidencePackage apply to the Full Review workflow only, not archive catalog workflows."
}
if ($PreContextSeconds -lt 0 -or $PostContextSeconds -lt 0) {
    throw "PreContextSeconds and PostContextSeconds must be zero or greater."
}
if ($NarrationContextPreSeconds -lt 0 -or $NarrationContextPostSeconds -lt 0) {
    throw "NarrationContextPreSeconds and NarrationContextPostSeconds must be zero or greater."
}
if ($NarrationPauseThresholdSeconds -lt 0) {
    throw "NarrationPauseThresholdSeconds must be zero or greater."
}
if ($EvidenceAudioStreamIndex -lt 0) {
    throw "EvidenceAudioStreamIndex must be zero or greater."
}
if ($EvidencePortableZipMaxMb -le 0) {
    throw "EvidencePortableZipMaxMb must be greater than zero."
}
if ($TranscriptAudioTrackOrdinal -lt 0) {
    throw "TranscriptAudioTrackOrdinal must be zero or greater."
}
if ($PreferredTranscriptAudioTrackOrdinal -lt 0) {
    throw "PreferredTranscriptAudioTrackOrdinal must be zero or greater."
}
if ($EvidenceFrameCadenceSeconds -lt 0) {
    throw "EvidenceFrameCadenceSeconds must be zero or greater."
}
if ($FullReviewPanelCropCadenceSeconds -le 0) {
    throw "FullReviewPanelCropCadenceSeconds must be greater than zero."
}
if ($EvidenceMaxFramesPerCandidate -lt 0) {
    throw "EvidenceMaxFramesPerCandidate must be zero or greater."
}
if ($EvidenceMaxItems -lt 0) {
    throw "EvidenceMaxItems must be zero or greater."
}
if ($ArchiveMaxThumbnailsPerVideo -lt 0) {
    throw "ArchiveMaxThumbnailsPerVideo must be zero or greater."
}
if ([string]::IsNullOrWhiteSpace($ArchiveSkipMarker)) {
    $ArchiveSkipMarker = "_NO_GLACIER_BACKUP"
}
$EvidencePanelCrops = if ([string]::IsNullOrWhiteSpace($EvidencePanelCrops)) { "Auto" } else { (Get-Culture).TextInfo.ToTitleCase($EvidencePanelCrops.Trim().ToLowerInvariant()) }
$FullReviewPanelCrops = if ([string]::IsNullOrWhiteSpace($FullReviewPanelCrops)) { "Auto" } else { (Get-Culture).TextInfo.ToTitleCase($FullReviewPanelCrops.Trim().ToLowerInvariant()) }
$AiReviewZipPanelCropMode = if ([string]::IsNullOrWhiteSpace($AiReviewZipPanelCropMode)) { "Auto" } else { (Get-Culture).TextInfo.ToTitleCase($AiReviewZipPanelCropMode.Trim().ToLowerInvariant()) }
$TranscriptAudioMode = if ([string]::IsNullOrWhiteSpace($TranscriptAudioMode)) { "Auto" } else { (Get-Culture).TextInfo.ToTitleCase($TranscriptAudioMode.Trim().ToLowerInvariant()) }
if (-not [string]::IsNullOrWhiteSpace($EvidenceTargetRepo)) {
    $EvidenceTargetRepo = $EvidenceTargetRepo.Trim()
    Assert-EvidenceTargetRepo -TargetRepo $EvidenceTargetRepo
}
if (-not [string]::IsNullOrWhiteSpace($EvidenceRepoMapPath)) {
    $EvidenceRepoMapPath = $EvidenceRepoMapPath.Trim()
}
if (-not [string]::IsNullOrWhiteSpace($EvidenceTranscriptionGlossaryPath)) {
    $EvidenceTranscriptionGlossaryPath = Normalize-UserPath -Path $EvidenceTranscriptionGlossaryPath
}
if (-not [string]::IsNullOrWhiteSpace($EvidencePanelRoleMapPath)) {
    $EvidencePanelRoleMapPath = Normalize-UserPath -Path $EvidencePanelRoleMapPath
}
$effectiveEvidenceCustomMarkers = @($EvidenceCustomMarkers)
$effectiveEvidenceCustomDomainTerms = @($EvidenceCustomDomainTerms)
$resolvedEvidenceFrameOffsets = Resolve-EvidenceFrameOffsets -Values @($EvidenceFrameOffsets)

Write-Host ("{0} v{1}" -f $script:AppName, $appVersion) -ForegroundColor Cyan
$pythonLauncherWasExplicit = $PSBoundParameters.ContainsKey("PythonExe")
$PythonExe = Resolve-PythonInterpreterPath `
    -RequestedValue $PythonExe `
    -WasExplicitlySet:$pythonLauncherWasExplicit

if ($WhisperHealthCheck) {
    Write-Phase -Name "Local Whisper Health" -Detail "Validating the Local Whisper runtime on this machine"
    $null = Invoke-WhisperHealthCheck -PythonCommand $PythonExe -PythonLauncherWasExplicit:$pythonLauncherWasExplicit
    return
}

Write-Phase -Name "Preflight" -Detail "Resolving tools and inputs"

$FFmpegPath = Resolve-ExecutablePath `
    -PreferredPath $FFmpegPath `
    -FallbackCommands @("ffmpeg") `
    -ToolName "FFmpeg" `
    -ToolKey "ffmpeg"
$FFprobePath = if (-not [string]::IsNullOrWhiteSpace($FFprobePath)) {
    Resolve-CommandOrPath -Value $FFprobePath -ToolName "FFprobe" -ToolKey "ffprobe"
}
else {
    Get-FFprobePath -FFmpegExe $FFmpegPath
}

$resolvedDefaults = Resolve-DefaultInputOutputFolders `
    -CurrentInputFolder $InputFolder `
    -CurrentOutputFolder $OutputFolder `
    -InputProvided:$($PSBoundParameters.ContainsKey("InputFolder")) `
    -OutputProvided:$($PSBoundParameters.ContainsKey("OutputFolder")) `
    -NoPrompt:$NoPrompt
$InputFolder = $resolvedDefaults.InputFolder
$OutputFolder = $resolvedDefaults.OutputFolder
# Warn about the input folder only when the user named it; one worked out from the output folder
# is covered by the output folder's own refusal.
Assert-FoldersAreNotTemporary `
    -InputFolder $(if ($PSBoundParameters.ContainsKey("InputFolder")) { $InputFolder } else { "" }) `
    -OutputFolder $OutputFolder

$requestedInputValue = $InputPath
if (-not $PSBoundParameters.ContainsKey("InputPath") -and -not $NoPrompt) {
    $allowWorkflowSelection = (
        -not $PSBoundParameters.ContainsKey("TranscriptOnly") -and
        -not $PSBoundParameters.ContainsKey("CodexEvidencePackage") -and
        -not $PSBoundParameters.ContainsKey("ReviewNewVideos") -and
        -not $PSBoundParameters.ContainsKey("ArchiveCatalog") -and
        -not $PSBoundParameters.ContainsKey("ArchiveCatalogSearch")
    )
    while ($true) {
        if ($allowWorkflowSelection) {
            $interactiveWorkflow = Get-InteractiveVideoWorkflow
            $TranscriptOnly = [bool]$interactiveWorkflow.TranscriptOnly
            $CodexEvidencePackage = [bool]$interactiveWorkflow.CodexEvidencePackage
            $ReviewNewVideos = [bool]$interactiveWorkflow.ReviewNewVideos
            $ArchiveCatalog = [bool]$interactiveWorkflow.ArchiveCatalog
            $ArchiveCatalogSearch = [bool]$interactiveWorkflow.ArchiveCatalogSearch
        }

        if ($ArchiveCatalogSearch -or $ReviewNewVideos) {
            break
        }

        $localOnlyWorkflow = ($TranscriptOnly -or $CodexEvidencePackage -or $ReviewNewVideos -or $ArchiveCatalog)
        $requestedInputValue = Get-InteractiveInputSource `
            -DefaultInputFolder $InputFolder `
            -YtDlpCommand $YtDlpPath `
            -PythonCommand $PythonExe `
            -LocalOnly:$localOnlyWorkflow `
            -AllowWorkflowBack:$allowWorkflowSelection

        if ($requestedInputValue -is [psobject] -and $null -ne $requestedInputValue.PSObject.Properties["Action"] -and $requestedInputValue.Action -eq "BackToWorkflow") {
            continue
        }

        break
    }
}

$remoteInputSources = @()
$InputPath = $null

$resolvedInputSources = Resolve-RequestedInputSources -RequestedInputValue $requestedInputValue
$remoteInputSources = @($resolvedInputSources.RemoteInputSources)
$InputPath = [string]$resolvedInputSources.InputPath

if (-not $PSBoundParameters.ContainsKey("InputPath") -and $InputPath -and (Test-Path -LiteralPath $InputPath -PathType Container)) {
    $InputFolder = $InputPath
}

$inputSourceDisplay = if ($remoteInputSources.Count -gt 0) {
    $remoteInputSources -join "; "
}
elseif ($InputPath) {
    $InputPath
}
else {
    $InputFolder
}

$requestedOutputFolder = $OutputFolder
if (-not $PSBoundParameters.ContainsKey("OutputFolder") -and -not $NoPrompt) {
    Write-Host ""
    Write-Host "Default output folder:"
    Write-Host $requestedOutputFolder
    $customOutput = Read-TimedDefaultPrompt `
        -Prompt ("Press Enter to use that folder, or type a different full output folder path. Auto-selects in {0}s:" -f $script:PromptTimeoutSeconds) `
        -DefaultValue ""
    if (-not [string]::IsNullOrWhiteSpace($customOutput)) {
        $requestedOutputFolder = $customOutput.Trim()
    }
}

$OutputFolder = Resolve-StartupDirectory -Path $requestedOutputFolder -FolderKind "output" -NoPrompt:$NoPrompt
# A run whose input is an explicit file (a .mmlist list of recordings, or one
# video) never reads an input folder, so do not create one beside the output
# (121).
$inputIsExplicitFile = (
    -not [string]::IsNullOrWhiteSpace($InputPath) -and
    (Test-Path -LiteralPath $InputPath -PathType Leaf)
)
if (-not $ReviewNewVideos -and -not $inputIsExplicitFile) {
    $InputFolder = Resolve-StartupDirectory -Path $InputFolder -FolderKind "input" -NoPrompt:$NoPrompt
}
elseif ($inputIsExplicitFile) {
    Write-Log ("Input is a file, so no input folder was created or required: {0}" -f $InputPath)
}

if ($ArchiveCatalog -or $ArchiveCatalogSearch) {
    if (-not $PSBoundParameters.ContainsKey("ArchiveCatalogPath") -and -not $NoPrompt) {
        $defaultCatalogPath = Join-Path $OutputFolder "_ARCHIVE_CATALOG"
        Write-Host ""
        Write-Host "Default archive catalog path:"
        Write-Host $defaultCatalogPath
        $customCatalogPath = Read-TimedDefaultPrompt `
            -Prompt ("Press Enter to use that catalog path, or type a different full catalog folder path. Auto-selects in {0}s:" -f $script:PromptTimeoutSeconds) `
            -DefaultValue ""
        if (-not [string]::IsNullOrWhiteSpace($customCatalogPath)) {
            $ArchiveCatalogPath = $customCatalogPath.Trim()
        }
    }

    if ($ArchiveCatalogSearch) {
        if (-not $PSBoundParameters.ContainsKey("ArchiveSearchTerms") -and -not $NoPrompt) {
            $termsValue = Read-Host "Search archive catalog. Enter terms"
            if (-not [string]::IsNullOrWhiteSpace($termsValue)) {
                $ArchiveSearchTerms = @($termsValue)
            }
        }
        if (@($ArchiveSearchTerms).Count -eq 0) {
            throw "Archive catalog search requires -ArchiveSearchTerms or interactive search terms."
        }
    }

    if ($ArchiveCatalog -and -not $NoPrompt) {
        if (-not $PSBoundParameters.ContainsKey("ArchiveHashMode")) {
            $hashChoice = Read-TimedChoicePrompt `
                -Prompt ("Hash mode: Fast (default), Full, Off. Auto-selects Fast in {0}s:" -f $script:PromptTimeoutSeconds) `
                -DefaultValue "Fast"
            if (-not [string]::IsNullOrWhiteSpace($hashChoice)) {
                $ArchiveHashMode = (Get-Culture).TextInfo.ToTitleCase($hashChoice.Trim().ToLowerInvariant())
            }
        }
        if (-not $PSBoundParameters.ContainsKey("ArchiveThumbnailMode")) {
            $thumbnailChoice = Read-TimedChoicePrompt `
                -Prompt ("Thumbnail mode: Auto (default), Off. Auto-selects Auto in {0}s:" -f $script:PromptTimeoutSeconds) `
                -DefaultValue "Auto"
            if (-not [string]::IsNullOrWhiteSpace($thumbnailChoice)) {
                $ArchiveThumbnailMode = (Get-Culture).TextInfo.ToTitleCase($thumbnailChoice.Trim().ToLowerInvariant())
            }
        }
        if (-not $PSBoundParameters.ContainsKey("ArchiveMaxThumbnailsPerVideo")) {
            $maxThumbsChoice = Read-TimedDefaultPrompt `
                -Prompt ("Max thumbnails per video (default {0}; auto-selects in {1}s):" -f $ArchiveMaxThumbnailsPerVideo, $script:PromptTimeoutSeconds) `
                -DefaultValue ([string]$ArchiveMaxThumbnailsPerVideo)
            if (-not [string]::IsNullOrWhiteSpace($maxThumbsChoice)) {
                $parsedMaxThumbs = 0
                if (-not [int]::TryParse($maxThumbsChoice.Trim(), [ref]$parsedMaxThumbs) -or $parsedMaxThumbs -lt 0) {
                    throw "ArchiveMaxThumbnailsPerVideo must be zero or greater."
                }
                $ArchiveMaxThumbnailsPerVideo = $parsedMaxThumbs
            }
        }
        if (-not $PSBoundParameters.ContainsKey("ArchiveS3Bucket")) {
            $bucketChoice = Read-TimedDefaultPrompt `
                -Prompt ("Optional S3 bucket name for prep manifests (press Enter to leave blank; auto-skips in {0}s):" -f $script:PromptTimeoutSeconds) `
                -DefaultValue ""
            if (-not [string]::IsNullOrWhiteSpace($bucketChoice)) {
                $ArchiveS3Bucket = $bucketChoice.Trim()
            }
        }
        if (-not $PSBoundParameters.ContainsKey("ArchiveS3Prefix")) {
            $prefixChoice = Read-TimedDefaultPrompt `
                -Prompt ("Optional S3 prefix for prep manifests (press Enter to leave blank; auto-skips in {0}s):" -f $script:PromptTimeoutSeconds) `
                -DefaultValue ""
            if (-not [string]::IsNullOrWhiteSpace($prefixChoice)) {
                $ArchiveS3Prefix = $prefixChoice.Trim()
            }
        }
        if (-not $PSBoundParameters.ContainsKey("ArchiveNotesCsv")) {
            $notesChoice = Read-TimedDefaultPrompt `
                -Prompt ("Optional manual notes CSV to import now (press Enter to skip; auto-skips in {0}s):" -f $script:PromptTimeoutSeconds) `
                -DefaultValue ""
            if (-not [string]::IsNullOrWhiteSpace($notesChoice)) {
                $ArchiveNotesCsv = Normalize-UserPath -Path $notesChoice.Trim()
            }
        }
        if (-not $PSBoundParameters.ContainsKey("ArchiveExportNotesTemplate")) {
            $ArchiveExportNotesTemplate = Read-TimedYesNoPrompt `
                -Prompt ("Export/update manual notes template? (Y/n, auto-selects Y in {0}s):" -f $script:PromptTimeoutSeconds) `
                -DefaultYes $true
        }
    }

    if ($ArchiveCatalogPath) {
        $ArchiveCatalogPath = Normalize-UserPath -Path $ArchiveCatalogPath
    }
    if ($ArchiveNotesCsv) {
        $ArchiveNotesCsv = Normalize-UserPath -Path $ArchiveNotesCsv
    }
    $ArchiveHashMode = (Get-Culture).TextInfo.ToTitleCase($ArchiveHashMode.Trim().ToLowerInvariant())
    $ArchiveThumbnailMode = (Get-Culture).TextInfo.ToTitleCase($ArchiveThumbnailMode.Trim().ToLowerInvariant())
    if ($ArchiveHashMode -notin @("Fast", "Full", "Off")) {
        throw "ArchiveHashMode must be Fast, Full, or Off."
    }
    if ($ArchiveThumbnailMode -notin @("Auto", "Off")) {
        throw "ArchiveThumbnailMode must be Auto or Off."
    }

    $archiveCatalogDisplayPath = if (-not [string]::IsNullOrWhiteSpace($ArchiveCatalogPath)) { $ArchiveCatalogPath } else { Join-Path $OutputFolder "_ARCHIVE_CATALOG" }
    $archiveBootstrapRoot = if ($ArchiveCatalog) { $archiveCatalogDisplayPath } else { $OutputFolder }
    Ensure-Directory $archiveBootstrapRoot
    $bootstrapLog = Join-Path $archiveBootstrapRoot "_script_bootstrap.log"
    $script:CurrentLogFile = $bootstrapLog
    "==== Bootstrap started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====" | Set-Content -Path $bootstrapLog -Encoding UTF8

    if ($ArchiveCatalogSearch) {
        $searchQuery = (@($ArchiveSearchTerms) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join " "
        Write-Log ("Archive catalog search terms: {0}" -f $searchQuery)
        $searchResult = Invoke-ArchiveCatalogSearchHelper `
            -PythonCommand $PythonExe `
            -CatalogPath $archiveCatalogDisplayPath `
            -Query $searchQuery `
            -HeartbeatSeconds $HeartbeatSeconds
        Write-ArchiveCatalogSearchResults -SearchResult $searchResult
        return
    }

    if ($remoteInputSources.Count -gt 0) {
        throw "Archive catalog supports local video files/folders only; remote URLs are not supported."
    }

    $archiveCatalogUpdateOnly = (
        $NoPrompt -and
        -not $PSBoundParameters.ContainsKey("InputPath") -and
        (-not [string]::IsNullOrWhiteSpace($ArchiveNotesCsv) -or $ArchiveExportNotesTemplate)
    )
    $archiveInputPath = ""
    if (-not $archiveCatalogUpdateOnly) {
        $archiveInputPath = if ($InputPath) { $InputPath } else { $InputFolder }
        $archiveInputPath = Normalize-UserPath -Path $archiveInputPath
        if (-not (Test-Path -LiteralPath $archiveInputPath)) {
            throw "Archive catalog source path not found: $archiveInputPath"
        }
    }
    if ($ArchiveNotesCsv -and -not (Test-Path -LiteralPath $ArchiveNotesCsv -PathType Leaf)) {
        throw "Archive notes CSV not found: $ArchiveNotesCsv"
    }

    Write-Host ""
    Write-Host "Archive Catalog preflight:" -ForegroundColor Cyan
    Write-Host ("  Scan root:          {0}" -f $(if ($archiveCatalogUpdateOnly) { "(none; catalog notes/template update only)" } else { $archiveInputPath }))
    Write-Host ("  Skip marker:        {0}" -f $ArchiveSkipMarker)
    Write-Host ("  Hash mode:          {0}" -f $ArchiveHashMode)
    Write-Host ("  Thumbnail mode:     {0}" -f $ArchiveThumbnailMode)
    Write-Host ("  Max thumbnails:     {0}" -f $ArchiveMaxThumbnailsPerVideo)
    Write-Host ("  Output catalog path:{0}" -f (" " + $archiveCatalogDisplayPath))
    Write-Host "  AWS upload:         no upload will be performed" -ForegroundColor Yellow

    Write-Log ("Archive catalog source: {0}" -f $(if ($archiveCatalogUpdateOnly) { "(none; catalog notes/template update only)" } else { $archiveInputPath }))
    Write-Log ("Archive catalog path: {0}" -f $archiveCatalogDisplayPath)
    Write-Log ("Archive hash mode: {0}" -f $ArchiveHashMode)
    Write-Log ("Archive thumbnail mode: {0}" -f $ArchiveThumbnailMode)
    Write-Log ("Archive max thumbnails per video: {0}" -f $ArchiveMaxThumbnailsPerVideo)
    Write-Log "Archive catalog does not upload to AWS, execute Glacier restores, or run Whisper transcription."

    $archiveResult = Invoke-ArchiveCatalogBuildHelper `
        -PythonCommand $PythonExe `
        -InputPath $archiveInputPath `
        -OutputFolder $OutputFolder `
        -CatalogPath $ArchiveCatalogPath `
        -SkipMarker $ArchiveSkipMarker `
        -HashMode $ArchiveHashMode `
        -ThumbnailMode $ArchiveThumbnailMode `
        -MaxThumbnailsPerVideo $ArchiveMaxThumbnailsPerVideo `
        -S3Bucket $ArchiveS3Bucket `
        -S3Prefix $ArchiveS3Prefix `
        -NotesCsv $ArchiveNotesCsv `
        -ExportNotesTemplate:$ArchiveExportNotesTemplate `
        -FFmpegExe $FFmpegPath `
        -FFprobeExe $FFprobePath `
        -HeartbeatSeconds $HeartbeatSeconds

    Write-Host ""
    Write-Host "Archive catalog complete." -ForegroundColor Green
    Write-Host ("  Catalog path:  {0}" -f $archiveResult.catalog_path)
    Write-Host ("  SQLite:        {0}" -f $archiveResult.archive_catalog_sqlite)
    Write-Host ("  Scanned:       {0}" -f $archiveResult.scanned_count)
    Write-Host ("  Added:         {0}" -f $archiveResult.added_count)
    Write-Host ("  Updated:       {0}" -f $archiveResult.updated_count)
    Write-Host ("  Missing:       {0}" -f $archiveResult.missing_count)
    Write-Host ("  Skipped:       {0}" -f $archiveResult.skipped_count)
    Write-Host ("  Errors:        {0}" -f $archiveResult.error_count)
    Write-Host ("  Notes template:{0}" -f (" " + $archiveResult.manual_notes_template))
    Write-Host "  AWS upload:    no upload was performed" -ForegroundColor Yellow

    Write-Log ("Archive catalog completed. Scanned={0}; added={1}; updated={2}; missing={3}; skipped={4}; errors={5}; catalog={6}" -f $archiveResult.scanned_count, $archiveResult.added_count, $archiveResult.updated_count, $archiveResult.missing_count, $archiveResult.skipped_count, $archiveResult.error_count, $archiveResult.catalog_path)

    if ($OpenOutputInExplorer) {
        Invoke-Item -LiteralPath $archiveResult.catalog_path
    }

    return
}

$includeFullReviewCodexEvidencePackage = $false
$fullReviewCodexEvidenceSelectionSource = "not requested"
$fullReviewCodexEvidenceStatus = "not_requested"
$fullReviewCodexEvidenceSkipReason = ""
$fullReviewCodexEvidenceResult = $null
$reviewNewVideosSettings = $null
$isFullReviewWorkflow = (-not $TranscriptOnly -and -not $CodexEvidencePackage -and -not $ReviewNewVideos -and -not $ArchiveCatalog -and -not $ArchiveCatalogSearch)
if ($isFullReviewWorkflow) {
    if ($SkipCodexEvidencePackage) {
        $includeFullReviewCodexEvidencePackage = $false
        $fullReviewCodexEvidenceSelectionSource = "explicit skip"
        $fullReviewCodexEvidenceStatus = "disabled"
    }
    elseif ($IncludeCodexEvidencePackage) {
        $includeFullReviewCodexEvidencePackage = $true
        $fullReviewCodexEvidenceSelectionSource = "explicit include"
        $fullReviewCodexEvidenceStatus = "requested"
    }
    elseif (-not $NoPrompt) {
        $fullReviewEvidenceChoice = Get-InteractiveFullReviewCodexEvidenceInclusion
        $includeFullReviewCodexEvidencePackage = [bool]$fullReviewEvidenceChoice.Include
        $fullReviewCodexEvidenceSelectionSource = [string]$fullReviewEvidenceChoice.Source
        $fullReviewCodexEvidenceStatus = if ($includeFullReviewCodexEvidencePackage) { "requested" } else { "disabled" }
    }
    else {
        $includeFullReviewCodexEvidencePackage = $false
        $fullReviewCodexEvidenceSelectionSource = "non-interactive default off"
        $fullReviewCodexEvidenceStatus = "not_requested"
    }

}
elseif ($IncludeCodexEvidencePackage -or $SkipCodexEvidencePackage) {
    throw "-IncludeCodexEvidencePackage and -SkipCodexEvidencePackage apply to the Full Review workflow only. Use -CodexEvidencePackage by itself for standalone evidence mode."
}

$evidenceConfigNeeded = ($CodexEvidencePackage -or $ReviewNewVideos -or $includeFullReviewCodexEvidencePackage)
if ($evidenceConfigNeeded) {
    $mediaManglersConfig = Get-MediaManglersUserConfig
    if ($mediaManglersConfig.Created) {
        Write-Host ("Created generic local Media Manglers config: {0}" -f $mediaManglersConfig.Path) -ForegroundColor Cyan
        Write-Host "Put private project names, repo targets, and detector terms in that local file, not in the repo." -ForegroundColor Cyan
    }
    $resolvedEvidenceConfig = Resolve-MediaManglersEvidenceSettings `
        -ConfigResult $mediaManglersConfig `
        -CliTargetRepo $EvidenceTargetRepo `
        -CliRepoMapPath $EvidenceRepoMapPath `
        -CliCustomMarkers @($EvidenceCustomMarkers) `
        -CliCustomDomainTerms @($EvidenceCustomDomainTerms) `
        -TargetRepoWasExplicit:$($PSBoundParameters.ContainsKey("EvidenceTargetRepo")) `
        -RepoMapPathWasExplicit:$($PSBoundParameters.ContainsKey("EvidenceRepoMapPath")) `
        -CustomMarkersWereExplicit:$($PSBoundParameters.ContainsKey("EvidenceCustomMarkers")) `
        -CustomDomainTermsWereExplicit:$($PSBoundParameters.ContainsKey("EvidenceCustomDomainTerms"))
    $EvidenceTargetRepo = if ([string]::IsNullOrWhiteSpace([string]$resolvedEvidenceConfig.TargetRepo)) { "" } else { [string]$resolvedEvidenceConfig.TargetRepo }
    $EvidenceRepoMapPath = if ([string]::IsNullOrWhiteSpace([string]$resolvedEvidenceConfig.RepoMapPath)) { "" } else { [string]$resolvedEvidenceConfig.RepoMapPath }
    $effectiveEvidenceCustomMarkers = @($resolvedEvidenceConfig.CustomMarkers)
    $effectiveEvidenceCustomDomainTerms = @($resolvedEvidenceConfig.CustomDomainTerms)
    Assert-EvidenceTargetRepo -TargetRepo $EvidenceTargetRepo
    if (-not [string]::IsNullOrWhiteSpace($EvidenceRepoMapPath)) {
        $EvidenceRepoMapPath = Normalize-UserPath -Path $EvidenceRepoMapPath
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$resolvedEvidenceConfig.ConfigPath)) {
        Write-Host ("Evidence local config: {0}" -f [string]$resolvedEvidenceConfig.ConfigPath) -ForegroundColor Cyan
    }
}

if ($ReviewNewVideos) {
    $reviewNewVideosSettings = Resolve-MediaManglersReviewSettings `
        -ConfigResult $mediaManglersConfig `
        -CliSourceFolders @($ReviewSourceFolders) `
        -CliEvidenceRoot $ReviewEvidenceRoot `
        -CliLocalWorkRoot $ReviewLocalWorkRoot `
        -CliLedgerPath $ReviewLedgerPath `
        -CliInboxFolder $ReviewInboxFolder `
        -CliDedupeMode $ReviewDedupeMode `
        -CliOrder $ReviewInboxOrder `
        -CliMaxFiles $ReviewInboxMaxFiles `
        -CliMaxDurationMinutes $ReviewInboxMaxDurationMinutes `
        -CliConcurrency $ReviewInboxConcurrency `
        -CliPendingBatchLimit $ReviewInboxPendingBatchLimit `
        -NoRecurse:$ReviewNoRecurse `
        -SourceFoldersWereExplicit:$($PSBoundParameters.ContainsKey("ReviewSourceFolders")) `
        -EvidenceRootWasExplicit:$($PSBoundParameters.ContainsKey("ReviewEvidenceRoot")) `
        -LocalWorkRootWasExplicit:$($PSBoundParameters.ContainsKey("ReviewLocalWorkRoot")) `
        -LedgerPathWasExplicit:$($PSBoundParameters.ContainsKey("ReviewLedgerPath")) `
        -DedupeModeWasExplicit:$($PSBoundParameters.ContainsKey("ReviewDedupeMode")) `
        -OrderWasExplicit:$($PSBoundParameters.ContainsKey("ReviewInboxOrder")) `
        -MaxFilesWasExplicit:$($PSBoundParameters.ContainsKey("ReviewInboxMaxFiles")) `
        -MaxDurationWasExplicit:$($PSBoundParameters.ContainsKey("ReviewInboxMaxDurationMinutes")) `
        -ConcurrencyWasExplicit:$($PSBoundParameters.ContainsKey("ReviewInboxConcurrency")) `
        -PendingBatchLimitWasExplicit:$($PSBoundParameters.ContainsKey("ReviewInboxPendingBatchLimit")) `
        -OutputFolder $OutputFolder

    if (@($reviewNewVideosSettings.SourceFolders).Count -eq 0) {
        Write-Host ""
        Write-Host "Review Media Inbox has no source folders configured." -ForegroundColor Yellow
        Write-Host ("Local config: {0}" -f $reviewNewVideosSettings.ConfigPath) -ForegroundColor Cyan
        Write-Host "Add local recording folders under reviewMediaInbox.sourceFolders (legacy reviewNewVideos is also read), or pass -ReviewSourceFolders." -ForegroundColor Cyan
        Write-Host "The public repo ships only generic placeholders; private project paths and terms belong in this local config file." -ForegroundColor Cyan
        return
    }
}

if ($includeFullReviewCodexEvidencePackage -and $EvidenceRepoHintMode -ne "off" -and [string]::IsNullOrWhiteSpace($EvidenceTargetRepo)) {
    if (-not [string]::IsNullOrWhiteSpace($script:DefaultFullReviewEvidenceTargetRepo)) {
        $EvidenceTargetRepo = $script:DefaultFullReviewEvidenceTargetRepo
        Write-Host ("Codex evidence target repo profile: {0} (override with -EvidenceTargetRepo)" -f $EvidenceTargetRepo) -ForegroundColor Cyan
    }
    else {
        Write-Host "Codex evidence target repo profile: none configured by default. Use -EvidenceTargetRepo, -EvidenceRepoMapPath, or local config for repo hints." -ForegroundColor Cyan
    }
}

if (($TranscriptOnly -or $CodexEvidencePackage) -and -not $PSBoundParameters.ContainsKey("TranscriptOnlyRecurse") -and -not $NoPrompt) {
    $TranscriptOnlyRecurse = Read-TimedYesNoPrompt `
        -Prompt ("Scan subfolders too for this local batch mode? (y/N, auto-selects N in {0}s):" -f $script:PromptTimeoutSeconds) `
        -DefaultYes $false
}

if (($TranscriptOnly -or $CodexEvidencePackage) -and -not $PSBoundParameters.ContainsKey("OverwriteTranscripts") -and -not $NoPrompt) {
    $OverwriteTranscripts = Read-TimedYesNoPrompt `
        -Prompt ("Overwrite existing transcript/audio files? (y/N, auto-selects N in {0}s):" -f $script:PromptTimeoutSeconds) `
        -DefaultYes $false
}

$keepTranscriptOnlyAudio = -not $SkipTranscriptOnlyAudio
if ($TranscriptOnly -and -not $PSBoundParameters.ContainsKey("SkipTranscriptOnlyAudio") -and -not $NoPrompt) {
    $keepTranscriptOnlyAudio = Read-TimedYesNoPrompt `
        -Prompt ("Extract and save audio files with transcript-only outputs? (Y/n, auto-selects Y in {0}s):" -f $script:PromptTimeoutSeconds) `
        -DefaultYes $true
}

if ($TranscriptOnly -and -not $PSBoundParameters.ContainsKey("TranscriptSearchTerms") -and -not $NoPrompt) {
    $TranscriptSearchTerms = @(Get-InteractiveTranscriptSearchTerms)
}

if ($CodexEvidencePackage -and -not $NoPrompt) {
    $evidenceSettingsWereExplicit = (
        $PSBoundParameters.ContainsKey("PreContextSeconds") -or
        $PSBoundParameters.ContainsKey("PostContextSeconds") -or
        $PSBoundParameters.ContainsKey("NarrationContextPreSeconds") -or
        $PSBoundParameters.ContainsKey("NarrationContextPostSeconds") -or
        $PSBoundParameters.ContainsKey("NarrationPauseThresholdSeconds") -or
        $PSBoundParameters.ContainsKey("NarrationStopAtNextTicketBoundary") -or
        $PSBoundParameters.ContainsKey("FragmentedNarrationMode") -or
        $PSBoundParameters.ContainsKey("EvidenceFrameOffsets") -or
        $PSBoundParameters.ContainsKey("EvidenceFrameCadenceSeconds") -or
        $PSBoundParameters.ContainsKey("EvidenceMaxFramesPerCandidate") -or
        $PSBoundParameters.ContainsKey("EvidenceMaxItems")
    )
    if (-not $evidenceSettingsWereExplicit) {
        $interactiveEvidenceSettings = Get-InteractiveCodexEvidenceSettings `
            -DefaultPreContextSeconds $PreContextSeconds `
            -DefaultPostContextSeconds $PostContextSeconds `
            -DefaultNarrationContextPreSeconds $NarrationContextPreSeconds `
            -DefaultNarrationContextPostSeconds $NarrationContextPostSeconds `
            -DefaultNarrationPauseThresholdSeconds $NarrationPauseThresholdSeconds `
            -DefaultNarrationStopAtNextTicketBoundary ($NarrationStopAtNextTicketBoundary -eq "On") `
            -DefaultFragmentedNarrationMode ($FragmentedNarrationMode -eq "On") `
            -DefaultFrameOffsets @($EvidenceFrameOffsets) `
            -DefaultFrameCadenceSeconds $EvidenceFrameCadenceSeconds `
            -DefaultMaxFramesPerCandidate $EvidenceMaxFramesPerCandidate `
            -DefaultMaxItems $EvidenceMaxItems `
            -DefaultPanelCropMode $EvidencePanelCrops
        $PreContextSeconds = [double]$interactiveEvidenceSettings.PreContextSeconds
        $PostContextSeconds = [double]$interactiveEvidenceSettings.PostContextSeconds
        $NarrationContextPreSeconds = [double]$interactiveEvidenceSettings.NarrationContextPreSeconds
        $NarrationContextPostSeconds = [double]$interactiveEvidenceSettings.NarrationContextPostSeconds
        $NarrationPauseThresholdSeconds = [double]$interactiveEvidenceSettings.NarrationPauseThresholdSeconds
        $NarrationStopAtNextTicketBoundary = if ([bool]$interactiveEvidenceSettings.NarrationStopAtNextTicketBoundary) { "On" } else { "Off" }
        $FragmentedNarrationMode = if ([bool]$interactiveEvidenceSettings.FragmentedNarrationMode) { "On" } else { "Off" }
        $EvidenceFrameOffsets = @($interactiveEvidenceSettings.FrameOffsets)
        $EvidenceFrameCadenceSeconds = [double]$interactiveEvidenceSettings.FrameCadenceSeconds
        $EvidenceMaxFramesPerCandidate = [int]$interactiveEvidenceSettings.MaxFramesPerCandidate
        $EvidenceMaxItems = [int]$interactiveEvidenceSettings.MaxItems
        $EvidencePanelCrops = [string]$interactiveEvidenceSettings.PanelCropMode
        $resolvedEvidenceFrameOffsets = Resolve-EvidenceFrameOffsets -Values @($EvidenceFrameOffsets)
    }
}
if ($CodexEvidencePackage -and -not $NoPrompt -and $EvidenceRepoHintMode -ne "off" -and -not $PSBoundParameters.ContainsKey("EvidenceTargetRepo")) {
    $value = Read-TimedDefaultPrompt `
        -Prompt ("Target repo hint for this evidence package? Press Enter to auto-detect from repo map or leave unknown, or paste owner/repo. Auto-selects blank in {0}s:" -f $script:PromptTimeoutSeconds) `
        -DefaultValue ""
    if (-not [string]::IsNullOrWhiteSpace($value)) {
        $EvidenceTargetRepo = $value.Trim()
        if ($EvidenceTargetRepo -notmatch '^[^/\s]+/[^/\s]+$') {
            throw "EvidenceTargetRepo must use owner/repo format, for example example-org/example-project."
        }
    }
}

$doCopyRaw = $CopyRawVideo.IsPresent
if (-not $TranscriptOnly -and -not $CodexEvidencePackage -and -not $ReviewNewVideos -and -not $PSBoundParameters.ContainsKey("CopyRawVideo") -and -not $NoPrompt) {
    $doCopyRaw = Read-TimedYesNoPrompt `
        -Prompt ("Copy original source video into raw folder? (Y/n, auto-selects Y in {0}s):" -f $script:PromptTimeoutSeconds) `
        -DefaultYes $true
}

$doCreateAiReviewZip = $CreateAiReviewZip.IsPresent
if (-not $TranscriptOnly -and -not $CodexEvidencePackage -and -not $ReviewNewVideos -and -not $PSBoundParameters.ContainsKey("CreateAiReviewZip") -and -not $NoPrompt) {
    $doCreateAiReviewZip = Read-TimedYesNoPrompt `
        -Prompt ("Create an AI review zip package for each completed video? (Y/n, auto-selects Y in {0}s):" -f $script:PromptTimeoutSeconds) `
        -DefaultYes $true
}

$doOpenOutputInExplorer = $OpenOutputInExplorer.IsPresent
if (-not $PSBoundParameters.ContainsKey("OpenOutputInExplorer") -and -not $NoPrompt) {
    $doOpenOutputInExplorer = Read-TimedYesNoPrompt `
        -Prompt ("Open Windows Explorer to the output folder when finished? (Y/n, auto-selects Y in {0}s):" -f $script:PromptTimeoutSeconds) `
        -DefaultYes $true
}

$translationProviderWasExplicit = $PSBoundParameters.ContainsKey("TranslationProvider")
$processingModeWasExplicit = $PSBoundParameters.ContainsKey("ProcessingMode")
if ($TranscriptOnly -or $CodexEvidencePackage -or $ReviewNewVideos) {
    if ($processingModeWasExplicit -and $ProcessingMode -ne "Local") {
        throw "Transcript-only, Codex evidence package, and Review New Videos workflows support Local Whisper transcription only. AI Private/Hybrid behavior is not supported in these MVP workflows."
    }
    if ($translationProviderWasExplicit -and -not [string]::IsNullOrWhiteSpace($TranslationProvider) -and $TranslationProvider -ne "Local") {
        throw "Transcript-only, Codex evidence package, and Review New Videos workflows support Local Whisper transcription only. AI Private/Hybrid behavior is not supported in these MVP workflows."
    }

    $processingModeResolution = [PSCustomObject]@{
        RequestedMode        = [string]$ProcessingMode
        EffectiveMode        = "Local"
        SelectionSource      = $(if ($ReviewNewVideos) { "review-new-videos" } elseif ($CodexEvidencePackage) { "codex-evidence-package" } else { "transcript-only" })
        ResolutionNote       = $(if ($ReviewNewVideos) { "Review New Videos mode uses Local Whisper transcription only." } elseif ($CodexEvidencePackage) { "Codex evidence package mode uses Local Whisper transcription only." } else { "Transcript-only mode uses Local Whisper transcription only." })
        # 213: how these modes always work, not a warning.
        ResolutionNoteLevel  = "INFO"
        RequestedLegacyValue = [string]$TranslationProvider
    }
}
else {
    $processingModeResolution = Resolve-ProcessingModeRequest `
        -RequestedMode $ProcessingMode `
        -WasExplicitlySet:$processingModeWasExplicit `
        -RequestedLegacyTranslationProvider $TranslationProvider `
        -LegacyProviderWasExplicitlySet:$translationProviderWasExplicit `
        -InteractiveMode:$(-not $NoPrompt)
}
$ProcessingMode = $processingModeResolution.EffectiveMode

if (($ProcessingMode -eq "AI" -or $ProcessingMode -eq "Hybrid") -and -not $PSBoundParameters.ContainsKey("OpenAiProject") -and -not $NoPrompt) {
    $OpenAiProject = Get-InteractiveOpenAiProjectMode -DefaultValue "Private"
}
elseif ([string]::IsNullOrWhiteSpace($OpenAiProject)) {
    $OpenAiProject = "Private"
}
else {
    $OpenAiProject = $OpenAiProject.Trim()
}

$openAiProjectResolutionNote = $null
if ($ProcessingMode -ne "AI" -and $ProcessingMode -ne "Hybrid" -and $PSBoundParameters.ContainsKey("OpenAiProject")) {
    $openAiProjectResolutionNote = ("OpenAiProject {0} was provided, but OpenAiProject only applies in AI or Hybrid mode." -f $OpenAiProject)
}

$interactiveWhisperEstimateProbe = $null
$interactiveWhisperCanUseGpuForEstimate = $false
if (-not $NoPrompt -and $ProcessingMode -eq "Local") {
    try {
        $interactiveWhisperEstimateProbe = Get-WhisperExecutionMode -PythonCommand $PythonExe
        $interactiveWhisperCanUseGpuForEstimate = ($WhisperDevice -ne "CPU" -and $interactiveWhisperEstimateProbe -and [bool]$interactiveWhisperEstimateProbe.CudaAvailable)
    }
    catch {
        $interactiveWhisperCanUseGpuForEstimate = $false
    }
}

$whisperModelWasExplicit = $PSBoundParameters.ContainsKey("WhisperModel")
$whisperModelResolutionNote = $null
if (-not [string]::IsNullOrWhiteSpace($WhisperModel)) {
    $WhisperModel = $WhisperModel.Trim()
}
if (-not $whisperModelWasExplicit -and $ProcessingMode -eq "Hybrid") {
    $originalWhisperModel = $WhisperModel
    $WhisperModel = $script:HybridAccuracyWhisperModel
    $whisperModelResolutionNote = ("Hybrid Accuracy defaulted Whisper from '{0}' to '{1}' so the initial lane stays on the planned local-medium transcription path." -f $originalWhisperModel, $WhisperModel)
}
elseif (-not $ReviewNewVideos -and -not $whisperModelWasExplicit -and $ProcessingMode -eq "Local") {
    if (-not $NoPrompt) {
        $interactiveWhisperSelection = Get-InteractiveLocalWhisperModelSelection `
            -DefaultValue $script:InteractiveLocalDefaultWhisperModel `
            -SourceDurationSeconds $(if ($ReviewNewVideos) { 0 } else { Get-InteractiveLocalWhisperSourceDurationSeconds -InputPath $(if ($InputPath) { $InputPath } else { $InputFolder }) -FFprobeExe $FFprobePath -Recurse:$TranscriptOnlyRecurse }) `
            -CanUseWhisperGpu:$interactiveWhisperCanUseGpuForEstimate `
            -WorkflowLabel $(if ($ReviewNewVideos) { "Review New Videos workflow" } elseif ($CodexEvidencePackage) { "Codex evidence package workflow" } elseif ($TranscriptOnly) { "transcript-only workflow" } else { "full review package workflow" })
        $WhisperModel = $interactiveWhisperSelection.Model
        if ($interactiveWhisperSelection.UsedDefault) {
            $whisperModelResolutionNote = ("Local interactive mode defaulted Whisper to '{0}' as the recommended balance between speed and accuracy." -f $WhisperModel)
        }
    }
    else {
        $originalWhisperModel = $WhisperModel
        $WhisperModel = $script:LocalAccuracyWhisperModel
        $whisperModelResolutionNote = ("Local non-interactive mode defaulted Whisper from '{0}' to '{1}' because scripted Local runs still preserve the accuracy-first default." -f $originalWhisperModel, $WhisperModel)
    }
}

$translationTargetsResolutionNote = $null
if ($TranscriptOnly -or $CodexEvidencePackage -or $ReviewNewVideos) {
    if ($PSBoundParameters.ContainsKey("TranslateTo") -and -not [string]::IsNullOrWhiteSpace($TranslateTo)) {
        throw "Transcript-only, Codex evidence package, and Review New Videos workflows do not support translation. Rerun without -TranslateTo, or use the normal Video Mangler workflow."
    }
    $TranslateTo = ""
    $translationTargetsResolutionNote = $(if ($ReviewNewVideos) { "Review New Videos mode does not request translation outputs." } elseif ($CodexEvidencePackage) { "Codex evidence package mode does not request translation outputs." } else { "Transcript-only mode does not request translation outputs." })
}
elseif ($ProcessingMode -eq "Hybrid" -and -not $PSBoundParameters.ContainsKey("TranslateTo") -and [string]::IsNullOrWhiteSpace($TranslateTo)) {
    $TranslateTo = "en"
    $translationTargetsResolutionNote = "Hybrid Accuracy defaulted TranslateTo to 'en' because Hybrid v1 currently supports source-language to English only."
}
elseif (-not $PSBoundParameters.ContainsKey("TranslateTo") -and -not $NoPrompt) {
    $TranslateTo = Get-InteractiveTranslationTargets -DefaultTarget "en"
}

$translationTargets = @(Get-TranslationTargets -Value $TranslateTo)
if ($ProcessingMode -eq "Hybrid" -and ($translationTargets.Count -ne 1 -or $translationTargets[0] -ne "en")) {
    throw "Hybrid Accuracy currently supports exactly one target language: English ('en'). Use -TranslateTo en, or use Local/AI mode for other target-language combinations."
}
$protectedTermsProfileSelection = if ($ProcessingMode -eq "Hybrid") {
    Resolve-ProtectedTermsProfileSelection -RequestedProfile $ProtectedTermsProfile
}
else {
    Resolve-ProtectedTermsProfileSelection -RequestedProfile ""
}
$protectedTermsProfileSummary = Get-ProtectedTermsProfileSummary -Selection $protectedTermsProfileSelection

$TranslationProvider = Get-TranslationModeForProcessingMode -EffectiveMode $ProcessingMode
$requestedLegacyTranslationProvider = if ($translationProviderWasExplicit) { $PSBoundParameters["TranslationProvider"] } else { "" }
$translationProviderResolution = [PSCustomObject]@{
    RequestedProvider = [string]$requestedLegacyTranslationProvider
    EffectiveProvider = $TranslationProvider
    SelectionSource   = if ($translationProviderWasExplicit) { "legacy compatibility flag" } else { "processing mode" }
    ResolutionNote    = if ($translationProviderWasExplicit) {
        "TranslationProvider is a legacy compatibility flag. ProcessingMode is the primary operator-facing control."
    }
    else {
        $null
    }
}

$openAiModelWasExplicit = $PSBoundParameters.ContainsKey("OpenAiModel")
$openAiTranslationModelResolution = $null
if ($ProcessingMode -eq "AI") {
    if ($translationTargets.Count -gt 0) {
        $openAiTranslationModelResolution = Resolve-OpenAiApprovedModelSelection `
            -Capability "Translation" `
            -ProjectMode $OpenAiProject `
            -RequestedModel $OpenAiModel `
            -WasExplicitlySet:$openAiModelWasExplicit
        $OpenAiModel = $openAiTranslationModelResolution.ResolvedModel
    }
    elseif ($openAiModelWasExplicit -and -not [string]::IsNullOrWhiteSpace($OpenAiModel)) {
        $OpenAiModel = $OpenAiModel.Trim()
    }
    else {
        $OpenAiModel = Get-OpenAiApprovedModelFallbackDefault -Capability "Translation" -ProjectMode $OpenAiProject
    }
}
elseif ($ProcessingMode -eq "Hybrid") {
    if ($translationTargets.Count -gt 0 -and $openAiModelWasExplicit -and -not [string]::IsNullOrWhiteSpace($OpenAiModel)) {
        $OpenAiModel = $OpenAiModel.Trim()
    }
    elseif ($translationTargets.Count -gt 0) {
        $OpenAiModel = ""
    }
}
elseif (-not $openAiModelWasExplicit -or [string]::IsNullOrWhiteSpace($OpenAiModel)) {
    $OpenAiModel = $script:OpenAiPrivateTranslationDefaultModel
}

$ResolvedOpenAiTranscriptionModel = $script:OpenAiTranscriptionModel
$processingModeSummary = Get-ProcessingModeSummary -EffectiveMode $ProcessingMode -ProjectMode $OpenAiProject
$transcriptionPathSummary = Get-TranscriptionProviderDetails -EffectiveMode $ProcessingMode -ProjectMode $OpenAiProject -Model $ResolvedOpenAiTranscriptionModel
$translationModeSummary = Get-TranslationModeSummary `
    -EffectiveMode $ProcessingMode `
    -ProjectMode $OpenAiProject `
    -Model $OpenAiModel `
    -TranslationRequested:($translationTargets.Count -gt 0)
$requestedOpenAiTranslationModelLabel = if ($translationTargets.Count -gt 0 -and ($ProcessingMode -eq "AI" -or $ProcessingMode -eq "Hybrid")) {
    Get-RequestedOpenAiTranslationModelLabel -EffectiveMode $ProcessingMode -RequestedModel $OpenAiModel -WasExplicitlySet:$openAiModelWasExplicit
}
else {
    ""
}

if (($ProcessingMode -eq "Local" -or ($ProcessingMode -eq "AI" -and $OpenAiProject -eq "Public")) -and $translationTargets.Count -gt 0) {
    if (-not $whisperModelWasExplicit -and -not (Test-WhisperModelSupportsTranslation -ModelName $WhisperModel)) {
        $originalModel = $WhisperModel
        $WhisperModel = $WhisperModel -replace '\.en$', ''
        Write-Host ("Translation was requested, so Video Mangler switched Whisper from '{0}' to '{1}' to work from the original spoken source." -f $originalModel, $WhisperModel) -ForegroundColor Yellow
    }
    elseif ($whisperModelWasExplicit -and -not (Test-WhisperModelSupportsTranslation -ModelName $WhisperModel)) {
        throw "Translation needs a multilingual Whisper model. The selected model '$WhisperModel' is English-only. Use 'large' or another supported Whisper model that does not end in '.en'."
    }
}

$translationProviderPreflightNotes = @()
if ($translationTargets.Count -gt 0) {
    $translationProviderPreflightNotes = @(Get-TranslationProviderPreflightNotes `
            -EffectiveProvider $TranslationProvider `
            -TranslationTargets $translationTargets `
            -ModelName $WhisperModel `
            -PythonCommand $PythonExe `
            -InteractiveMode:$(-not $NoPrompt) `
            -HeartbeatSeconds $HeartbeatSeconds)
}

if ($TranscriptOnly -or $CodexEvidencePackage -or $ReviewNewVideos) {
    if ([double]::IsNaN($FrameIntervalSeconds)) {
        $FrameIntervalSeconds = 0.0
    }
}
elseif ([double]::IsNaN($FrameIntervalSeconds)) {
    if ($NoPrompt) {
        $FrameIntervalSeconds = 0.5
    }
    else {
        $FrameIntervalSeconds = Get-InteractiveFrameInterval -DefaultValue 0.5
    }
}

if (-not $TranscriptOnly -and -not $CodexEvidencePackage -and -not $ReviewNewVideos) {
    Test-FrameIntervalValue -Value $FrameIntervalSeconds
}

$bootstrapRoot = if ($TranscriptOnly) { Join-Path $OutputFolder "transcript-only" } elseif ($CodexEvidencePackage) { Join-Path $OutputFolder "codex-evidence-package" } elseif ($ReviewNewVideos) { Join-Path $OutputFolder "review-new-videos" } else { $OutputFolder }
Ensure-Directory $bootstrapRoot
$bootstrapLog = Join-Path $bootstrapRoot "_script_bootstrap.log"
$script:CurrentLogFile = $bootstrapLog
"==== Bootstrap started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====" | Set-Content -Path $bootstrapLog -Encoding UTF8
Write-Log "Selected frame interval: $FrameIntervalSeconds seconds"
Write-Log "Output folder root: $OutputFolder"
if ($isFullReviewWorkflow) {
    Write-Log ("Full Review Codex evidence package: {0} ({1})" -f $(if ($includeFullReviewCodexEvidencePackage) { "included" } else { $fullReviewCodexEvidenceStatus }), $fullReviewCodexEvidenceSelectionSource)
}
else {
    Write-Log ("Full Review Codex evidence package: not applicable ({0})" -f $(if ($ReviewNewVideos) { "review-new-videos workflow" } elseif ($CodexEvidencePackage) { "standalone Codex evidence workflow" } else { "transcript-only workflow" }))
}
Write-Log ("Evidence panel crops: {0}" -f (Get-EvidencePanelCropModeSummary -Mode $EvidencePanelCrops))
if ($isFullReviewWorkflow) {
    Write-Log ("Full Review panel crops: {0}; cadence {1} seconds" -f $FullReviewPanelCrops, $FullReviewPanelCropCadenceSeconds)
    Write-Log ("Transcript audio mode: {0}; stream '{1}'; track ordinal {2}; preferred track ordinal {3}" -f $TranscriptAudioMode, $TranscriptAudioStream, $TranscriptAudioTrackOrdinal, $PreferredTranscriptAudioTrackOrdinal)
    Write-Log ("AI review ZIP panel crop mode: {0}" -f $AiReviewZipPanelCropMode)
}
Write-Log ("Requested processing mode: {0} ({1})" -f $(if ([string]::IsNullOrWhiteSpace($processingModeResolution.RequestedMode)) { $ProcessingMode } else { $processingModeResolution.RequestedMode }), $processingModeResolution.SelectionSource)
if ($ProcessingMode -ne $processingModeResolution.RequestedMode -and -not [string]::IsNullOrWhiteSpace($processingModeResolution.RequestedMode)) {
    Write-Log ("Effective processing mode request: {0}" -f $processingModeSummary)
}
if (-not [string]::IsNullOrWhiteSpace($processingModeResolution.ResolutionNote)) {
    Write-Log $processingModeResolution.ResolutionNote $(if ($processingModeResolution.PSObject.Properties["ResolutionNoteLevel"]) { [string]$processingModeResolution.ResolutionNoteLevel } else { "WARN" })
}
if (-not [string]::IsNullOrWhiteSpace($openAiProjectResolutionNote)) {
    # 213: a setting this mode does not use; nothing to act on.
    Write-Log $openAiProjectResolutionNote "INFO"
}
if (-not [string]::IsNullOrWhiteSpace($translationTargetsResolutionNote)) {
    Write-Log $translationTargetsResolutionNote
}
if (-not [string]::IsNullOrWhiteSpace($script:PythonInterpreterResolutionNote)) {
    Write-Log $script:PythonInterpreterResolutionNote "WARN"
}
if (-not [string]::IsNullOrWhiteSpace($whisperModelResolutionNote)) {
    Write-Log $whisperModelResolutionNote
}
Write-Log ("Resolved processing mode: {0}" -f $processingModeSummary)
Write-Log ("Transcription path selected: {0}" -f $transcriptionPathSummary)
if ($ProcessingMode -eq "Hybrid") {
    Write-Log ("Protected terms profile: {0}" -f $protectedTermsProfileSummary)
}
if ($ProcessingMode -eq "Local" -or $ProcessingMode -eq "Hybrid") {
    Write-Log ("Local Whisper model: {0}" -f $WhisperModel)
    Write-Log ("Local Whisper timeout mode: {0}" -f $(if ($WhisperTimeoutSeconds -gt 0) { "explicit override ({0}s)" -f $WhisperTimeoutSeconds } else { "adaptive" }))
}
if ($ProcessingMode -eq "AI" -or $ProcessingMode -eq "Hybrid") {
    Write-Log ("OpenAI project mode: {0}" -f $OpenAiProject)
    if ($translationTargets.Count -gt 0) {
        if ($openAiTranslationModelResolution -and -not [string]::IsNullOrWhiteSpace($openAiTranslationModelResolution.ResolutionNote)) {
            Write-Log $openAiTranslationModelResolution.ResolutionNote
        }
        Write-Log ("OpenAI translation model: {0}" -f $requestedOpenAiTranslationModelLabel)
    }
}
if ($translationTargets.Count -gt 0) {
    Write-Log ("Translation targets selected: {0}" -f ($translationTargets -join ", "))
    Write-Log ("Translation path selected: {0}" -f $translationModeSummary)
    if (-not [string]::IsNullOrWhiteSpace($translationProviderResolution.RequestedProvider)) {
        Write-Log ("Requested legacy TranslationProvider: {0} ({1})" -f $translationProviderResolution.RequestedProvider, $translationProviderResolution.SelectionSource)
        Write-Log ("Effective translation provider request: {0}" -f $TranslationProvider)
    }
    if (-not [string]::IsNullOrWhiteSpace($translationProviderResolution.ResolutionNote)) {
        Write-Log $translationProviderResolution.ResolutionNote "WARN"
    }
    foreach ($preflightNote in $translationProviderPreflightNotes) {
        Write-Log $preflightNote "WARN"
    }
}
if ($ProcessingMode -eq "Hybrid" -and $translationTargets.Count -gt 0) {
    $null = Assert-HybridRuntimePreflight -ProtectedTermsProfileSelection $protectedTermsProfileSelection
    if ($protectedTermsProfileSelection.IsSelected -and -not [string]::IsNullOrWhiteSpace($protectedTermsProfileSelection.Path)) {
        Write-Log ("Protected terms profile asset: {0}" -f $protectedTermsProfileSelection.Path)
    }
}
if ($TranscriptOnly) {
    if ($remoteInputSources.Count -gt 0) {
        throw "Transcript-only MVP supports local video files/folders only; remote URLs are not supported."
    }

    $transcriptOnlyInputPath = if ($InputPath) { $InputPath } else { $InputFolder }
    $transcriptOnlyInputPath = Normalize-UserPath -Path $transcriptOnlyInputPath
    if (-not (Test-Path -LiteralPath $transcriptOnlyInputPath)) {
        throw "Transcript-only source path not found: $transcriptOnlyInputPath"
    }

    $whisperProbe = $null
    if (-not $pythonLauncherWasExplicit) {
        $pythonSelection = Select-PreferredWhisperPythonInterpreter -PrimaryPythonCommand $PythonExe
        if ($pythonSelection) {
            if (-not [string]::IsNullOrWhiteSpace($pythonSelection.Path)) {
                $PythonExe = $pythonSelection.Path
            }
            $whisperProbe = $pythonSelection.Probe
            $script:PythonInterpreterResolutionNote = $pythonSelection.Note
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($script:PythonInterpreterResolutionNote)) {
        Write-Log $script:PythonInterpreterResolutionNote "WARN"
    }

    Test-PythonWhisper -PythonCommand $PythonExe
    if ($null -eq $whisperProbe) {
        $whisperProbe = Get-WhisperExecutionMode -PythonCommand $PythonExe
    }

    $whisperDevicePreference = Resolve-WhisperDevicePreference `
        -RequestedDevice $WhisperDevice `
        -WhisperProbe $whisperProbe `
        -RequiresLocalWhisper:$true
    $canUseWhisperGpu = [bool]$whisperDevicePreference.PreferGpu

    $transcriptOnlyResult = Invoke-TranscriptOnlyBatch `
        -InputPath $transcriptOnlyInputPath `
        -OutputFolder $OutputFolder `
        -PythonCommand $PythonExe `
        -FFmpegExe $FFmpegPath `
        -FFprobeExe $FFprobePath `
        -ModelName $WhisperModel `
        -LanguageCode $Language `
        -CanUseWhisperGpu $canUseWhisperGpu `
        -WhisperTimeoutSeconds $WhisperTimeoutSeconds `
        -HeartbeatSeconds $HeartbeatSeconds `
        -TranscriptOnlyRecurse:$TranscriptOnlyRecurse `
        -OverwriteTranscripts:$OverwriteTranscripts `
        -KeepAudio:$keepTranscriptOnlyAudio `
        -SearchTerms @($TranscriptSearchTerms) `
        -TranscriptAudioMode $TranscriptAudioMode `
        -TranscriptAudioStream $TranscriptAudioStream `
        -TranscriptAudioTrackOrdinal $TranscriptAudioTrackOrdinal `
        -TrackRolesText ([string]$EvidenceTrackRoles)

    if ($doOpenOutputInExplorer) {
        Invoke-Item -LiteralPath $transcriptOnlyResult.OutputRoot
    }

    return
}
if ($ReviewNewVideos) {
    if ($remoteInputSources.Count -gt 0) {
        throw "Review New Videos supports configured local video files/folders only; remote URLs are not supported."
    }

    Write-Host ""
    Write-Host ("Review Media Inbox {0} configuration:" -f $ReviewInboxAction.ToLowerInvariant()) -ForegroundColor Cyan
    Write-Host ("  Config:          {0}" -f $reviewNewVideosSettings.ConfigPath)
    Write-Host ("  Source folders:  {0}" -f (@($reviewNewVideosSettings.SourceFolders) -join "; "))
    Write-Host ("  Evidence root:   {0}" -f $reviewNewVideosSettings.EvidenceRoot)
    Write-Host ("  Local work root: {0}" -f $reviewNewVideosSettings.LocalWorkRoot)
    Write-Host ("  Inbox folder:    {0}" -f (Split-Path -Parent ([string]$reviewNewVideosSettings.LedgerPath)))
    Write-Host ("  Recurse:         {0}" -f ([bool]$reviewNewVideosSettings.Recurse))
    Write-Host ("  Ordering:        {0} first" -f $reviewNewVideosSettings.Order)
    Write-Host ("  Maximum files:   {0}" -f $reviewNewVideosSettings.MaxFiles)
    Write-Host ("  Soft duration:   {0} minutes (do not start another source after the boundary; the current source may finish safely)" -f $reviewNewVideosSettings.MaxDurationMinutes)
    Write-Host ("  Concurrency:     {0}" -f $reviewNewVideosSettings.Concurrency)
    Write-Host ("  Pending batches: {0}" -f $reviewNewVideosSettings.PendingBatchLimit)

    if ($ReviewInboxAction -in @("Scan", "Process") -and $reviewNewVideosSettings.DedupeMode -eq "Full") {
        $fullWarning = "Full deduplication hashes every stable file in the configured inventory. It may read multiple terabytes, take a long time, and place sustained read load on source drives. Fast is the normal default."
        Write-Warning $fullWarning
        Write-Log $fullWarning "WARN"
        if (-not $ReviewFullScanAcknowledged) {
            throw "Full Review Media Inbox scan requires -ReviewFullScanAcknowledged for this run."
        }
    }

    $reviewInboxExactSourcePaths = @()
    if (-not [string]::IsNullOrWhiteSpace($ReviewInboxExactSourcePathsJson)) {
        if ($ReviewInboxAction -ne "Process") {
            throw "ReviewInboxExactSourcePathsJson is supported only with -ReviewInboxAction Process."
        }
        if (-not $ReviewInboxExactSourcePathsJson.TrimStart().StartsWith("[")) {
            throw "ReviewInboxExactSourcePathsJson must contain a JSON array of absolute local paths."
        }
        try {
            $parsedExactSourcePaths = (
                $ReviewInboxExactSourcePathsJson |
                    ConvertFrom-Json -ErrorAction Stop
            )
            $reviewInboxExactSourcePaths = @(
                $parsedExactSourcePaths |
                    ForEach-Object { [string]$_ }
            )
        }
        catch {
            throw "ReviewInboxExactSourcePathsJson must contain a valid JSON array of absolute local paths."
        }
    }

    if ($ReviewInboxAction -eq "Process") {
        if ($ReviewInboxWorkload -eq "up_to_n" -and ($ReviewInboxNewSourceLimit -lt 1 -or $ReviewInboxNewSourceLimit -gt 9999)) {
            throw "Up to N requires -ReviewInboxNewSourceLimit between 1 and 9999."
        }

        $reviewDecision = $null
        if (-not [string]::IsNullOrWhiteSpace($ReviewInboxDecisionJson)) {
            try {
                $reviewDecision = $ReviewInboxDecisionJson | ConvertFrom-Json -ErrorAction Stop
            }
            catch {
                throw "ReviewInboxDecisionJson must contain valid JSON from the Workbench continuation."
            }
        }
        $reviewProcessPayload = @{
            source_folders = @($reviewNewVideosSettings.SourceFolders)
            ledger_path = [string]$reviewNewVideosSettings.LedgerPath
            evidence_root = [string]$reviewNewVideosSettings.EvidenceRoot
            scratch_root = [string]$reviewNewVideosSettings.LocalWorkRoot
            recurse = [bool]$reviewNewVideosSettings.Recurse
            dedupe_mode = [string]$reviewNewVideosSettings.DedupeMode
            order = "oldest"
            max_files = 3
            max_duration_minutes = 240
            concurrency = 1
            pending_batch_limit = [int]$reviewNewVideosSettings.PendingBatchLimit
            full_scan_acknowledged = [bool]$ReviewFullScanAcknowledged
            workload_mode = [string]$ReviewInboxWorkload
            new_source_limit = $(if ($ReviewInboxWorkload -eq "up_to_n") { [int]$ReviewInboxNewSourceLimit } else { 3 })
            exact_source_paths = @($reviewInboxExactSourcePaths)
            coordinator_lock_held = $true
            continuation = [string]$ReviewInboxContinuation
            decision = $reviewDecision
            ffmpeg_exe = $FFmpegPath
            ffprobe_exe = $(if ([string]::IsNullOrWhiteSpace($FFprobePath)) { "ffprobe" } else { $FFprobePath })
            whisper_model = $WhisperModel
            language_code = (Resolve-MMNarrationTranscriptionDefaults -Language $Language -NarrationSpeechMode $NarrationSpeechMode -NarratedRecordings).Language
            narration_speech_mode = (Resolve-MMNarrationTranscriptionDefaults -Language $Language -NarrationSpeechMode $NarrationSpeechMode -NarratedRecordings).NarrationSpeechMode
            # 214: the main GPU setting, which the Inbox used to drop.
            prefer_gpu = ($WhisperDevice -ne "CPU")
            # 214: Skip from Queue / Progress, seen at the next step of the recording being prepared.
            run_control_path = [string]$script:MMRunControlPath
            # 214: the main track setting, which the shared voice detection and line filters read.
            track_roles = (ConvertTo-MMTrackRoles -Text ([string]$EvidenceTrackRoles))
            # 206: the operator's words to spell right, as every feature that transcribes gets them.
            glossary_entries = @(Get-MMSpellingWords)
            initial_prompt = (Get-EvidenceTranscriptionInitialPrompt -GlossaryEntries (Get-MMSpellingWords))
            audio_confirmations_path = $(if (-not [string]::IsNullOrWhiteSpace($ReviewAudioConfirmationsPath)) { $ReviewAudioConfirmationsPath } elseif ([string]::IsNullOrWhiteSpace([string]$reviewNewVideosSettings.ConfigPath)) { "" } else { Join-Path (Split-Path -Parent ([string]$reviewNewVideosSettings.ConfigPath)) "narration-layouts.json" })
            stop_after_current_file_path = $ReviewStopAfterCurrentFilePath
            emit_progress = $true
        }

        $processLock = $null
        try {
            # Hold the exclusive Windows file handle for the complete
            # coordinator loop. A crashed owner releases the handle
            # automatically; the diagnostic file itself is never deleted.
            # The TargetedEvidence action takes the same lock the same way (224).
            $processLock = Open-ReviewInboxProcessLock -LedgerPath ([string]$reviewNewVideosSettings.LedgerPath)

            if ($null -eq $processLock) {
                $reviewResult = Invoke-ReviewLedgerHelper `
                    -PythonCommand $PythonExe `
                    -Command "review-media-inbox-process" `
                    -Payload @{ ledger_path = [string]$reviewNewVideosSettings.LedgerPath; attach_only = $true } `
                    -HeartbeatSeconds $HeartbeatSeconds
                $reviewResult | Add-Member -NotePropertyName concurrent_process_attached -NotePropertyValue $true -Force
                $reviewResult | Add-Member -NotePropertyName operator_status -NotePropertyValue "Processing" -Force
                Write-Host ("MM_REVIEW_INBOX_PROCESS_RESULT_V1 {0}" -f ($reviewResult | ConvertTo-Json -Compress -Depth 24))
                return
            }

            $reviewResult = $null
            $loopCompleted = $false
            for ($processStep = 0; $processStep -lt 10000; $processStep++) {
                $reviewResult = Invoke-ReviewLedgerHelper `
                    -PythonCommand $PythonExe `
                    -Command "review-media-inbox-process" `
                    -Payload $reviewProcessPayload `
                    -HeartbeatSeconds $HeartbeatSeconds

                $nextAction = $reviewResult.next_action
                if ($nextAction -and [string]$nextAction.type -eq "render_targeted") {
                    $targetedResult = Invoke-ReviewInboxTargetedEvidence `
                        -PythonCommand $PythonExe `
                        -LedgerPath ([string]$reviewNewVideosSettings.LedgerPath) `
                        -BatchId ([string]$nextAction.batch_id) `
                        -PreliminarySubmissionSha256 ([string]$nextAction.preliminary_submission_sha256) `
                        -FFmpegExe $FFmpegPath `
                        -StopAfterCurrentRequestPath $ReviewStopAfterCurrentFilePath `
                        -HeartbeatSeconds $HeartbeatSeconds `
                        -CoordinatorLockHeld
                    $reviewProcessPayload.targeted_result = $targetedResult
                    $reviewProcessPayload.continuation = [string]$reviewResult.continuation
                    $reviewProcessPayload.decision = $null
                    continue
                }
                if ([bool]$reviewResult.continue_automatically) {
                    $reviewProcessPayload.continuation = [string]$reviewResult.continuation
                    $reviewProcessPayload.decision = $null
                    continue
                }
                $loopCompleted = $true
                break
            }
            if (-not $loopCompleted) {
                throw "Review Media Inbox Process exceeded its internal safe-action limit without reaching an operator or completion boundary."
            }
        }
        finally {
            if ($null -ne $processLock) {
                $processLock.Dispose()
                $processLock = $null
            }
        }

        Write-Host ""
        Write-Host ("Review Media Inbox processing stopped at: {0}" -f [string]$reviewResult.operator_status) -ForegroundColor Green
        Write-Host ("MM_REVIEW_INBOX_PROCESS_RESULT_V1 {0}" -f ($reviewResult | ConvertTo-Json -Compress -Depth 24))
        return
    }

    if ($ReviewInboxAction -in @("ImportResults", "PreviewFinalization", "Finalize")) {
        if ([string]::IsNullOrWhiteSpace($ReviewInboxResumeBatchId)) {
            throw "Review Media Inbox action '$ReviewInboxAction' requires -ReviewInboxResumeBatchId."
        }
        if ($ReviewInboxAction -eq "ImportResults" -and [string]::IsNullOrWhiteSpace($ReviewResultsPath)) {
            throw "ImportResults requires -ReviewResultsPath."
        }
        if ($ReviewInboxAction -eq "Finalize" -and ([string]::IsNullOrWhiteSpace($ReviewFinalizationPlanPath) -or [string]::IsNullOrWhiteSpace($ReviewFinalizationPlanSha256))) {
            throw "Finalize requires -ReviewFinalizationPlanPath and -ReviewFinalizationPlanSha256 from an approved preview."
        }
        if ($ReviewInboxAction -eq "Finalize" -and -not $ReviewFinalizationConfirmed) {
            throw "Finalize requires -ReviewFinalizationConfirmed after the operator reviews the exact retention and cleanup preview."
        }

        $reviewFinalCommand = switch ($ReviewInboxAction) {
            "ImportResults" { "review-media-inbox-import-results" }
            "PreviewFinalization" { "review-media-inbox-finalization-preview" }
            "Finalize" { "review-media-inbox-finalize" }
        }
        $reviewFinalPayload = @{
            ledger_path = [string]$reviewNewVideosSettings.LedgerPath
            expected_batch_id = $ReviewInboxResumeBatchId
            results_path = $ReviewResultsPath
            plan_path = $ReviewFinalizationPlanPath
            plan_sha256 = $ReviewFinalizationPlanSha256
            operator_confirmed = [bool]$ReviewFinalizationConfirmed
        }
        $reviewResult = Invoke-ReviewLedgerHelper `
            -PythonCommand $PythonExe `
            -Command $reviewFinalCommand `
            -Payload $reviewFinalPayload `
            -HeartbeatSeconds $HeartbeatSeconds
        Write-Host ""
        Write-Host ("Review Media Inbox {0} finished with status: {1}" -f $ReviewInboxAction, [string]$reviewResult.status) -ForegroundColor Green
        Write-Host ("  Batch: {0}" -f [string]$reviewResult.batch_id)
        if ($ReviewInboxAction -eq "PreviewFinalization") {
            Write-Host ("  Plan:  {0}" -f [string]$reviewResult.plan_path)
            Write-Warning "Review the exact retained/disposable file counts and paths before explicitly confirming finalization."
        }
        Write-Host ("MM_REVIEW_INBOX_RESULT_V1 {0}" -f ($reviewResult | ConvertTo-Json -Compress -Depth 16))
        return
    }

    if ($ReviewInboxAction -eq "TargetedEvidence") {
        # 224 (Wave B1): the whole action holds the Inbox's lock, as Process does, so no other run renders or
        # imports into this batch between its plan and its completion.
        $targetedLock = Wait-ReviewInboxProcessLock -LedgerPath ([string]$reviewNewVideosSettings.LedgerPath)
        if ($null -eq $targetedLock) {
            throw "The Inbox is busy with another run. Try again when it finishes."
        }
        try {
            $reviewResult = Invoke-ReviewInboxTargetedEvidence `
                -PythonCommand $PythonExe `
                -LedgerPath ([string]$reviewNewVideosSettings.LedgerPath) `
                -BatchId $ReviewInboxResumeBatchId `
                -PreliminarySubmissionSha256 $ReviewPreliminarySubmissionSha256 `
                -FFmpegExe $FFmpegPath `
                -StopAfterCurrentRequestPath $ReviewStopAfterCurrentFilePath `
                -HeartbeatSeconds $HeartbeatSeconds `
                -CoordinatorLockHeld
        }
        finally {
            $targetedLock.Dispose()
        }
        Write-Host ""
        Write-Host ("Review Media Inbox targeted evidence finished with status: {0}" -f [string]$reviewResult.status) -ForegroundColor Green
        Write-Host ("  Batch:             {0}" -f [string]$reviewResult.batch_id)
        Write-Host ("  Requests complete: {0}/{1}" -f [int]$reviewResult.completed_request_count, [int]$reviewResult.request_count)
        Write-Host ("  Failed requests:   {0}" -f @($reviewResult.failed_requests).Count)
        Write-Host ("MM_REVIEW_INBOX_RESULT_V1 {0}" -f ($reviewResult | ConvertTo-Json -Compress -Depth 12))
        return
    }

    $reviewHelperCommand = if ($ReviewInboxAction -eq "Prepare") { "review-media-inbox-prepare" } else { "review-media-inbox-scan" }
    $reviewPayload = @{
        source_folders = @($reviewNewVideosSettings.SourceFolders)
        ledger_path = $reviewNewVideosSettings.LedgerPath
        evidence_root = $reviewNewVideosSettings.EvidenceRoot
        scratch_root = $reviewNewVideosSettings.LocalWorkRoot
        recurse = [bool]$reviewNewVideosSettings.Recurse
        dedupe_mode = [string]$reviewNewVideosSettings.DedupeMode
        order = ([string]$reviewNewVideosSettings.Order).ToLowerInvariant()
        max_files = [int]$reviewNewVideosSettings.MaxFiles
        max_duration_minutes = [int]$reviewNewVideosSettings.MaxDurationMinutes
        concurrency = [int]$reviewNewVideosSettings.Concurrency
        pending_batch_limit = [int]$reviewNewVideosSettings.PendingBatchLimit
        full_scan_acknowledged = [bool]$ReviewFullScanAcknowledged
        ffmpeg_exe = $FFmpegPath
        ffprobe_exe = $(if ([string]::IsNullOrWhiteSpace($FFprobePath)) { "ffprobe" } else { $FFprobePath })
        whisper_model = $WhisperModel
        language_code = (Resolve-MMNarrationTranscriptionDefaults -Language $Language -NarrationSpeechMode $NarrationSpeechMode -NarratedRecordings).Language
        narration_speech_mode = (Resolve-MMNarrationTranscriptionDefaults -Language $Language -NarrationSpeechMode $NarrationSpeechMode -NarratedRecordings).NarrationSpeechMode
        audio_confirmations_path = $(if (-not [string]::IsNullOrWhiteSpace($ReviewAudioConfirmationsPath)) { $ReviewAudioConfirmationsPath } elseif ([string]::IsNullOrWhiteSpace([string]$reviewNewVideosSettings.ConfigPath)) { "" } else { Join-Path (Split-Path -Parent ([string]$reviewNewVideosSettings.ConfigPath)) "narration-layouts.json" })
        stop_after_current_file_path = $ReviewStopAfterCurrentFilePath
        emit_progress = ($ReviewInboxAction -eq "Prepare")
        resume_batch_id = $ReviewInboxResumeBatchId
    }
    $reviewResult = Invoke-ReviewLedgerHelper `
        -PythonCommand $PythonExe `
        -Command $reviewHelperCommand `
        -Payload $reviewPayload `
        -HeartbeatSeconds $HeartbeatSeconds

    Write-Host ""
    if ($ReviewInboxAction -eq "Prepare") {
        Write-Host ("Review Media Inbox preparation finished with status: {0}" -f [string]$reviewResult.status) -ForegroundColor Green
        if (-not [string]::IsNullOrWhiteSpace([string]$reviewResult.batch_id)) {
            Write-Host ("  Batch:            {0}" -f [string]$reviewResult.batch_id)
            Write-Host ("  Batch path:       {0}" -f [string]$reviewResult.batch_path)
        }
        Write-Host ("  Prepared sources: {0}" -f @($reviewResult.prepared_sources).Count)
        Write-Host ("  Blocked sources:  {0}" -f @($reviewResult.blocked_sources).Count)
        Write-Host ("  Failed sources:   {0}" -f @($reviewResult.failed_sources).Count)
        Write-Host ("MM_REVIEW_INBOX_RESULT_V1 {0}" -f ($reviewResult | ConvertTo-Json -Compress -Depth 12))
    }
    else {
        Write-Host "Review Media Inbox metadata scan complete." -ForegroundColor Green
        Write-Host ("  Inventory:        {0}" -f [int]$reviewResult.inventory_count)
        Write-Host ("  Eligible:         {0}" -f [int]$reviewResult.eligible_count)
        Write-Host ("  Selected preview: {0}" -f @($reviewResult.selected_sources).Count)
        Write-Host ("  Pending batches:  {0}" -f @($reviewResult.pending_batches).Count)
        Write-Host "No media was copied, transcribed, rendered, moved, renamed, or deleted." -ForegroundColor Cyan
    }
    return
}
if ($CodexEvidencePackage) {
    if ($remoteInputSources.Count -gt 0) {
        throw "Codex evidence package MVP supports local video files/folders only; remote URLs are not supported."
    }

    $codexEvidenceInputPath = if ($InputPath) { $InputPath } else { $InputFolder }
    $codexEvidenceInputPath = Normalize-UserPath -Path $codexEvidenceInputPath
    if (-not (Test-Path -LiteralPath $codexEvidenceInputPath)) {
        throw "Codex evidence package source path not found: $codexEvidenceInputPath"
    }

    $whisperProbe = $null
    if (-not $pythonLauncherWasExplicit) {
        $pythonSelection = Select-PreferredWhisperPythonInterpreter -PrimaryPythonCommand $PythonExe
        if ($pythonSelection) {
            if (-not [string]::IsNullOrWhiteSpace($pythonSelection.Path)) {
                $PythonExe = $pythonSelection.Path
            }
            $whisperProbe = $pythonSelection.Probe
            $script:PythonInterpreterResolutionNote = $pythonSelection.Note
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($script:PythonInterpreterResolutionNote)) {
        Write-Log $script:PythonInterpreterResolutionNote "WARN"
    }

    Test-PythonWhisper -PythonCommand $PythonExe
    if ($null -eq $whisperProbe) {
        $whisperProbe = Get-WhisperExecutionMode -PythonCommand $PythonExe
    }

    $whisperDevicePreference = Resolve-WhisperDevicePreference `
        -RequestedDevice $WhisperDevice `
        -WhisperProbe $whisperProbe `
        -RequiresLocalWhisper:$true
    $canUseWhisperGpu = [bool]$whisperDevicePreference.PreferGpu

    $narrationDefaults = Resolve-MMNarrationTranscriptionDefaults -Language $Language -NarrationSpeechMode $NarrationSpeechMode -ProfileName $EvidenceProfileSetupName
    $effectiveEvidenceLanguage = $narrationDefaults.Language
    $effectiveNarrationSpeechMode = $narrationDefaults.NarrationSpeechMode
    $effectiveEvidenceFrameCadence = $EvidenceFrameCadenceSeconds
    $effectiveEvidenceMaxFrames = $EvidenceMaxFramesPerCandidate
    if (-not $PSBoundParameters.ContainsKey("EvidenceFrameCadenceSeconds")) {
        $effectiveEvidenceFrameCadence = if ($EvidenceRenderDensity -eq "Dense") { 1 } else { 15 }
    }
    if (-not $PSBoundParameters.ContainsKey("EvidenceMaxFramesPerCandidate")) {
        $effectiveEvidenceMaxFrames = if ($EvidenceRenderDensity -eq "Dense") { 220 } else { 24 }
    }

    $codexEvidenceResult = Invoke-CodexEvidencePackageBatch `
        -InputPath $codexEvidenceInputPath `
        -OutputFolder $OutputFolder `
        -PythonCommand $PythonExe `
        -FFmpegExe $FFmpegPath `
        -FFprobeExe $FFprobePath `
        -ModelName $WhisperModel `
        -LanguageCode $effectiveEvidenceLanguage `
        -CanUseWhisperGpu $canUseWhisperGpu `
        -WhisperTimeoutSeconds $WhisperTimeoutSeconds `
        -HeartbeatSeconds $HeartbeatSeconds `
        -Recurse:$TranscriptOnlyRecurse `
        -OverwriteTranscripts:$OverwriteTranscripts `
        -PreContextSeconds $PreContextSeconds `
        -PostContextSeconds $PostContextSeconds `
        -NarrationContextPreSeconds $NarrationContextPreSeconds `
        -NarrationContextPostSeconds $NarrationContextPostSeconds `
        -NarrationPauseThresholdSeconds $NarrationPauseThresholdSeconds `
        -NarrationStopAtNextTicketBoundary ($NarrationStopAtNextTicketBoundary -eq "On") `
        -FragmentedNarrationMode ($FragmentedNarrationMode -eq "On") `
        -FrameOffsets @($resolvedEvidenceFrameOffsets) `
        -AudioStreamIndex $EvidenceAudioStreamIndex `
        -AudioStreamSelectionsJson $EvidenceAudioStreamSelectionsJson `
        -TrackRoles $EvidenceTrackRoles `
        -FrameCadenceSeconds $effectiveEvidenceFrameCadence `
        -MaxFramesPerCandidate $effectiveEvidenceMaxFrames `
        -MaxItems $EvidenceMaxItems `
        -RenderCandidateIds @($EvidenceRenderCandidateIds) `
        -RenderOutcomeIds @($EvidenceRenderOutcomeIds) `
        -StopAfter $EvidenceStopAfter `
        -RenderDensity $EvidenceRenderDensity `
        -SpeechMode $effectiveNarrationSpeechMode `
        -ResumeRoot $EvidenceResumeRoot `
        -HandoffMode $EvidenceHandoffMode `
        -PortableZipMaxMb $EvidencePortableZipMaxMb `
        -PanelCropMode $EvidencePanelCrops `
        -InvocationMode "standalone" `
        -TargetRepo $EvidenceTargetRepo `
        -RepoMapPath $EvidenceRepoMapPath `
        -RepoHintMode $EvidenceRepoHintMode `
        -CustomMarkers @($effectiveEvidenceCustomMarkers) `
        -CustomDomainTerms @($effectiveEvidenceCustomDomainTerms) `
        -TranscriptionGlossaryPath $EvidenceTranscriptionGlossaryPath `
        -TranscriptionGlossaryEntries @($EvidenceTranscriptionGlossaryEntries) `
        -AudioStreamSelectionConfirmed:$EvidenceAudioStreamSelectionConfirmed `
        -PreserveSupportingAudio:$EvidencePreserveSupportingAudio `
        -PanelRoleMapPath $EvidencePanelRoleMapPath `
        -RunMetadata @{
            target_project = $EvidenceTargetProject
            target_repository = $EvidenceTargetRepo
            application_version = $EvidenceApplicationVersion
            profile_setup_name = $EvidenceProfileSetupName
            dashboard_revision = $EvidenceDashboardRevision
            test_conditions = $EvidenceTestConditions
            configuration_notes = $EvidenceConfigurationNotes
        }

    if ($doOpenOutputInExplorer) {
        Invoke-Item -LiteralPath $codexEvidenceResult.OutputRoot
    }

    if ([int]$codexEvidenceResult.ProblemCount -gt 0) {
        # Non-zero exit so the Workbench reports "completed with problems"
        # instead of "complete" (94). The package for the usable recordings
        # has been written and is kept.
        Write-Host ("ERROR: {0} recording(s) could not be used; the package covers the rest. {1}" -f [int]$codexEvidenceResult.ProblemCount, (@($codexEvidenceResult.ProblemRecordings) -join "; "))
        exit 2
    }
    exit 0
}
if ($remoteInputSources.Count -gt 0) {
    $scopeProbeInvoker = $null
    try {
        $scopeProbeInvoker = Resolve-YtDlpInvoker -PreferredCommand $YtDlpPath -PythonCommand $PythonExe
    }
    catch {
        Write-Log ("Remote scope probe could not resolve yt-dlp: {0}" -f $_.Exception.Message) "WARN"
    }

    $remoteInputScopeSummary = Get-RemoteInputScopeSummary -SourceUrls $remoteInputSources -YtDlpInvoker $scopeProbeInvoker
    Confirm-ExpandedRunScope `
        -ScopeSummary $remoteInputScopeSummary `
        -NoPrompt:$NoPrompt `
        -ApproveExpandedRun:$ApproveExpandedRun
}

$masterReadme = Join-Path $OutputFolder "CODEX_MASTER_README.txt"
$summaryCsv = Join-Path $OutputFolder "PROCESSING_SUMMARY.csv"
$fullReviewRunManifest = Join-Path $OutputFolder "FULL_REVIEW_RUN_MANIFEST.json"
$downloadedInputPaths = @()
$downloadedInputCount = 0
$downloadedInputKinds = @()
$sourceInfoJsonByVideoPath = @{}
$remoteAudioTrackByVideoPath = @{}
$sourceUrlByVideoPath = @{}
$remoteDownloadFailures = @()
$doIncludeComments = $IncludeComments.IsPresent

try {
    $videos = @()

    if ($remoteInputSources.Count -gt 0) {
    $downloadCacheFolder = $InputFolder
    $doIncludeComments = $IncludeComments.IsPresent
    if (-not $PSBoundParameters.ContainsKey("IncludeComments") -and -not $NoPrompt) {
        $doIncludeComments = Read-TimedYesNoPrompt `
            -Prompt ("If comments are available for a YouTube source, save them in the package too? (Y/n, auto-selects Y in {0}s):" -f $script:PromptTimeoutSeconds) `
            -DefaultYes $true
    }

    $ytDlpInvoker = Resolve-YtDlpInvoker -PreferredCommand $YtDlpPath -PythonCommand $PythonExe
    Write-Log "Downloading remote input with $($ytDlpInvoker.DisplayName)"

    $remoteSourceOrdinal = 0
    foreach ($remoteSource in $remoteInputSources) {
        $remoteSourceOrdinal += 1
        Write-MMProgressV1 -Phase "Download" -SourceId (Get-Sha256ShortText -Value $remoteSource) -SourceName $remoteSource -SourceOrdinal $remoteSourceOrdinal -SourceTotal $remoteInputSources.Count -SourceState "active" -SourceTerminal:$false -ProgressKind stage -Activity ("Downloading web video {0} of {1}" -f $remoteSourceOrdinal, $remoteInputSources.Count)
        try {
            $downloadResult = Invoke-PhaseAction -Name "Download" -Detail $remoteSource -Action {
                Invoke-RemoteVideoDownload `
                    -SourceUrl $remoteSource `
                    -DownloadFolder $downloadCacheFolder `
                    -YtDlpInvoker $ytDlpInvoker `
                    -FFmpegExe $FFmpegPath `
                    -IncludeComments:$doIncludeComments `
                    -InteractiveMode:$(-not $NoPrompt) `
                    -HeartbeatSeconds $HeartbeatSeconds
            }
        }
        catch {
            $remoteDownloadFailures += [PSCustomObject]@{
                SourceVideoName = $remoteSource
                SourceVideoPath = $remoteSource
                OutputFolderName = ""
                OutputPath = ""
                VideoPath = $remoteSource
                FailurePhase = "Download"
                Message = $_.Exception.Message
                CodexEvidenceStatus = $(if ($includeFullReviewCodexEvidencePackage) { "not_attempted" } else { $fullReviewCodexEvidenceStatus })
                AudioPresent = ""
            }
            Write-MMProgressV1 -Phase "Download" -SourceId (Get-Sha256ShortText -Value $remoteSource) -SourceName $remoteSource -SourceOrdinal $remoteSourceOrdinal -SourceTotal $remoteInputSources.Count -SourceState "failed" -SourceTerminal:$true -FailedCount $remoteDownloadFailures.Count -ProgressKind stage -Activity ("Download failed for web video {0} of {1}: {2}" -f $remoteSourceOrdinal, $remoteInputSources.Count, $_.Exception.Message)
            Write-Host ("FAIL download {0}: {1}" -f $remoteSource, $_.Exception.Message) -ForegroundColor Red
            Write-Log ("Remote download failed for '{0}': {1}" -f $remoteSource, $_.Exception.Message) "ERROR"
            continue
        }

        $downloadedInputPaths += $downloadResult.DownloadRoot
        $downloadedInputKinds += $downloadResult.SourceKind
        $downloadedInputCount += @($downloadResult.DownloadedPaths).Count
        $infoJsonMap = @{}
        if ($null -ne $downloadResult.PSObject.Properties['InfoJsonByMediaPath'] -and $downloadResult.InfoJsonByMediaPath) {
            $infoJsonMap = $downloadResult.InfoJsonByMediaPath
        }
        $remoteAudioMap = @{}
        if ($null -ne $downloadResult.PSObject.Properties['RemoteAudioTrackByMediaPath'] -and $downloadResult.RemoteAudioTrackByMediaPath) {
            $remoteAudioMap = $downloadResult.RemoteAudioTrackByMediaPath
        }
        foreach ($downloadedPath in @($downloadResult.DownloadedPaths)) {
            $sourceUrlByVideoPath[$downloadedPath] = $remoteSource
            if ($infoJsonMap.ContainsKey($downloadedPath)) {
                $sourceInfoJsonByVideoPath[$downloadedPath] = $infoJsonMap[$downloadedPath]
            }
            if ($remoteAudioMap.ContainsKey($downloadedPath)) {
                $remoteAudioTrackByVideoPath[$downloadedPath] = $remoteAudioMap[$downloadedPath]
            }
        }
        $videos += @($downloadResult.DownloadedPaths | ForEach-Object { Get-Item -LiteralPath $_ })
        Write-MMProgressV1 -Phase "Download" -SourceId (Get-Sha256ShortText -Value $remoteSource) -SourceName $remoteSource -SourceOrdinal $remoteSourceOrdinal -SourceTotal $remoteInputSources.Count -SourceState "prepared" -SourceTerminal:$false -PreparedCount $downloadedInputCount -FailedCount $remoteDownloadFailures.Count -ProgressKind stage -Activity ("Prepared web video {0} of {1}" -f $remoteSourceOrdinal, $remoteInputSources.Count)
    }
}
elseif ($InputPath) {
    $videos = Get-VideoFilesFromPath -Path $InputPath
}
else {
    $videos = Get-VideoFilesFromPath -Path $InputFolder

    if ((-not $videos -or $videos.Count -eq 0) -and -not $NoPrompt) {
        Write-Host "No supported video files found in the selected local input source." -ForegroundColor Yellow
        $manual = Get-InteractiveInputSource `
            -DefaultInputFolder $InputFolder `
            -YtDlpCommand $YtDlpPath `
            -PythonCommand $PythonExe

        $manualRemoteSources = @()
        if ($manual -is [System.Array]) {
            $manualRemoteSources = @($manual)
        }
        elseif (Test-IsHttpUrl -Value $manual) {
            $manualRemoteSources = @([string]$manual)
        }

        if ($manualRemoteSources.Count -gt 0) {
            $downloadCacheFolder = $InputFolder
            $doIncludeComments = $IncludeComments.IsPresent
            if (-not $PSBoundParameters.ContainsKey("IncludeComments") -and -not $NoPrompt) {
                $doIncludeComments = Read-TimedYesNoPrompt `
                    -Prompt ("If comments are available for a YouTube source, save them in the package too? (Y/n, auto-selects Y in {0}s):" -f $script:PromptTimeoutSeconds) `
                    -DefaultYes $true
            }
            $ytDlpInvoker = Resolve-YtDlpInvoker -PreferredCommand $YtDlpPath -PythonCommand $PythonExe
            Write-Log "Downloading remote input with $($ytDlpInvoker.DisplayName)"

            $downloadedInputPaths = @()
            $downloadedInputKinds = @()
            $downloadedInputCount = 0
            $videos = @()

            foreach ($manualRemoteSource in $manualRemoteSources) {
                $downloadResult = Invoke-PhaseAction -Name "Download" -Detail $manualRemoteSource -Action {
                    Invoke-RemoteVideoDownload `
                        -SourceUrl $manualRemoteSource `
                        -DownloadFolder $downloadCacheFolder `
                        -YtDlpInvoker $ytDlpInvoker `
                        -FFmpegExe $FFmpegPath `
                        -IncludeComments:$doIncludeComments `
                        -InteractiveMode:$(-not $NoPrompt) `
                        -HeartbeatSeconds $HeartbeatSeconds
                }

                $downloadedInputPaths += $downloadResult.DownloadRoot
                $downloadedInputKinds += $downloadResult.SourceKind
                $downloadedInputCount += @($downloadResult.DownloadedPaths).Count
                $infoJsonMap = @{}
                if ($null -ne $downloadResult.PSObject.Properties['InfoJsonByMediaPath'] -and $downloadResult.InfoJsonByMediaPath) {
                    $infoJsonMap = $downloadResult.InfoJsonByMediaPath
                }
                $remoteAudioMap = @{}
                if ($null -ne $downloadResult.PSObject.Properties['RemoteAudioTrackByMediaPath'] -and $downloadResult.RemoteAudioTrackByMediaPath) {
                    $remoteAudioMap = $downloadResult.RemoteAudioTrackByMediaPath
                }
                foreach ($downloadedPath in @($downloadResult.DownloadedPaths)) {
                    if ($infoJsonMap.ContainsKey($downloadedPath)) {
                        $sourceInfoJsonByVideoPath[$downloadedPath] = $infoJsonMap[$downloadedPath]
                    }
                    if ($remoteAudioMap.ContainsKey($downloadedPath)) {
                        $remoteAudioTrackByVideoPath[$downloadedPath] = $remoteAudioMap[$downloadedPath]
                    }
                }
                $videos += @($downloadResult.DownloadedPaths | ForEach-Object { Get-Item -LiteralPath $_ })
            }

            $inputSourceDisplay = $manualRemoteSources -join "; "
        }
        else {
            $inputSourceDisplay = $manual
            $videos = Get-VideoFilesFromPath -Path $manual
        }
    }
}

if (-not $videos -or $videos.Count -eq 0) {
    if ($remoteDownloadFailures.Count -gt 0) {
        throw ("No web videos could be downloaded. First failure: {0}" -f $remoteDownloadFailures[0].Message)
    }
    throw "No supported video files found to process."
}

$videos = @($videos | Sort-Object FullName -Unique)

if (Test-Path $summaryCsv) {
    Remove-Item $summaryCsv -Force
}

$videosWithAudio = @()
foreach ($video in $videos) {
    try {
        if (Test-VideoHasAudio -FFprobeExe $FFprobePath -VideoPath $video.FullName) {
            $videosWithAudio += $video
        }
    }
    catch {
        Write-Log "Audio probe warning for $($video.FullName): $($_.Exception.Message)" "WARN"
    }
}

if ($ProcessingMode -eq "AI" -and $OpenAiProject -eq "Private" -and $videosWithAudio.Count -gt 0) {
    $openAiTranscriptionModelResolution = Resolve-OpenAiApprovedModelSelection `
        -Capability "Transcription" `
        -ProjectMode $OpenAiProject `
        -RequestedModel $script:OpenAiTranscriptionModel
    $ResolvedOpenAiTranscriptionModel = $openAiTranscriptionModelResolution.ResolvedModel
    $transcriptionPathSummary = Get-TranscriptionProviderDetails -EffectiveMode $ProcessingMode -ProjectMode $OpenAiProject -Model $ResolvedOpenAiTranscriptionModel
    if ($openAiTranscriptionModelResolution -and -not [string]::IsNullOrWhiteSpace($openAiTranscriptionModelResolution.ResolutionNote)) {
        Write-Log $openAiTranscriptionModelResolution.ResolutionNote
    }
}

if ($ProcessingMode -eq "AI" -and (($OpenAiProject -eq "Private" -and $videosWithAudio.Count -gt 0) -or $translationTargets.Count -gt 0)) {
    $requiredOpenAiLabel = if ($ProcessingMode -eq "AI" -and $OpenAiProject -eq "Private" -and $videosWithAudio.Count -gt 0) {
        "AI mode"
    }
    else {
        "OpenAI translation"
    }
    $null = Get-OpenAiApiKey -Required -ProviderLabel $requiredOpenAiLabel
}
elseif ($ProcessingMode -eq "Hybrid" -and $translationTargets.Count -gt 0) {
    $null = Assert-HybridAccuracyOpenAiProjectKey -ProjectMode $OpenAiProject
}

$requiresLocalWhisper = ($ProcessingMode -ne "AI" -or $OpenAiProject -eq "Public")
$whisperProbe = $null
if ($videosWithAudio.Count -gt 0 -and $requiresLocalWhisper -and -not $pythonLauncherWasExplicit) {
    $pythonSelection = Select-PreferredWhisperPythonInterpreter -PrimaryPythonCommand $PythonExe
    if ($pythonSelection) {
        if (-not [string]::IsNullOrWhiteSpace($pythonSelection.Path)) {
            $PythonExe = $pythonSelection.Path
        }
        $whisperProbe = $pythonSelection.Probe
        $script:PythonInterpreterResolutionNote = $pythonSelection.Note
    }
}
if (-not [string]::IsNullOrWhiteSpace($script:PythonInterpreterResolutionNote)) {
    Write-Log $script:PythonInterpreterResolutionNote "WARN"
}

if ($videosWithAudio.Count -gt 0 -and $requiresLocalWhisper) {
    Test-PythonWhisper -PythonCommand $PythonExe
}

$nvencSupported = Test-FFmpegNvencSupport -FFmpegExe $FFmpegPath
$cudaHwaccelSupported = Test-FFmpegCudaHwaccelSupport -FFmpegExe $FFmpegPath
$nvidiaPresent = Test-NvidiaSmiAvailable
if ($null -eq $whisperProbe) {
    $whisperProbe = Get-WhisperExecutionMode -PythonCommand $PythonExe
}

$canUseFfmpegGpu = $false
if ($nvencSupported -and $cudaHwaccelSupported -and $nvidiaPresent) {
    $canUseFfmpegGpu = $true
}

$whisperDevicePreference = Resolve-WhisperDevicePreference `
    -RequestedDevice $WhisperDevice `
    -WhisperProbe $whisperProbe `
    -RequiresLocalWhisper:$requiresLocalWhisper
$canUseWhisperGpu = [bool]$whisperDevicePreference.PreferGpu
$localWhisperPathSummary = [string]$whisperDevicePreference.SummaryLabel

if (Test-ConsoleDebugMode) {
    Write-Host ""
    Write-Host "Resolved tools"
    Write-Host "--------------"
    Write-Host ("FFmpeg:   {0}" -f $FFmpegPath)
    Write-Host ("FFprobe:  {0}" -f $FFprobePath)
    Write-Host ("Python:   {0}" -f $PythonExe)
    Write-Host ""
    Write-Host "Hardware Acceleration Detection"
    Write-Host "-------------------------------"
    Write-Host ("FFmpeg CUDA hwaccel support:     {0}" -f $(if ($cudaHwaccelSupported) { "Yes" } else { "No" }))
    Write-Host ("FFmpeg NVENC support:            {0}" -f $(if ($nvencSupported) { "Yes" } else { "No" }))
    Write-Host ("Whisper/PyTorch CUDA available:  {0}" -f $(if ($canUseWhisperGpu) { "Yes" } else { "No" }))
    $null = Write-WhisperProbeReport -WhisperProbe $whisperProbe -IncludeNvidiaPresence $true -NvidiaPresent $nvidiaPresent
    Write-Host ""
    Write-Host ("Proxy path selected:             {0}" -f $(if ($canUseFfmpegGpu) { "GPU preferred with CPU fallback" } else { "CPU fallback" }))
    Write-Host ("Frame extraction path selected:  {0}" -f $(if ($canUseFfmpegGpu) { "GPU preferred with CPU fallback" } else { "CPU" }))
    Write-Host ("Local Whisper path:             {0}" -f $localWhisperPathSummary)
    Write-Host ("Local Whisper timeout mode:      {0}" -f $(if ($WhisperTimeoutSeconds -gt 0) { "explicit override ({0}s)" -f $WhisperTimeoutSeconds } else { "adaptive" }))
    Write-Host ("Selected frame interval:         {0} seconds" -f $FrameIntervalSeconds)
    Write-Host ("Heartbeat interval:              {0} seconds" -f $HeartbeatSeconds)
    Write-Host ("Input source:                    {0}" -f $inputSourceDisplay)
    if ($downloadedInputPaths.Count -gt 0) {
        Write-Host ("Downloaded input cache:          {0}" -f ($downloadedInputPaths -join "; "))
        Write-Host ("Downloaded source type:          {0}" -f ($downloadedInputKinds -join ", "))
        Write-Host ("Downloaded video count:          {0}" -f $downloadedInputCount)
    }
    Write-Host ("Output folder:                   {0}" -f $OutputFolder)
    Write-Host ("Processing mode:                 {0}" -f $processingModeSummary)
    if ($isFullReviewWorkflow) {
        Write-Host ("Full Review Codex evidence:     {0} ({1})" -f $(if ($includeFullReviewCodexEvidencePackage) { "included" } else { $fullReviewCodexEvidenceStatus }), $fullReviewCodexEvidenceSelectionSource)
    }
    Write-Host ("Evidence panel crops:           {0}" -f (Get-EvidencePanelCropModeSummary -Mode $EvidencePanelCrops))
    if ($ProcessingMode -eq "Local" -or $ProcessingMode -eq "Hybrid") {
        Write-Host ("Local Whisper model:            {0}" -f $WhisperModel)
        Write-Host ("Local Whisper device request:   {0}" -f $WhisperDevice)
    }
    if ($ProcessingMode -eq "Hybrid") {
        Write-Host ("Protected terms profile:        {0}" -f $protectedTermsProfileSummary)
    }
    if ($ProcessingMode -eq "AI" -or $ProcessingMode -eq "Hybrid") {
        Write-Host ("OpenAI project mode:             {0}" -f $OpenAiProject)
        if ($ProcessingMode -eq "AI" -and $OpenAiProject -eq "Private" -and $videosWithAudio.Count -gt 0) {
            Write-Host ("OpenAI transcription model:      {0}" -f $ResolvedOpenAiTranscriptionModel)
        }
        if ($translationTargets.Count -gt 0) {
            Write-Host ("OpenAI translation model:        {0}" -f $requestedOpenAiTranslationModelLabel)
        }
    }
    Write-Host ("Transcription path selected:     {0}" -f $transcriptionPathSummary)
    Write-Host ("Translation targets:             {0}" -f $(if ($translationTargets.Count -gt 0) { $translationTargets -join ", " } else { "none" }))
    Write-Host ("Translation path selected:       {0}" -f $translationModeSummary)
    Write-Host ("Comments export:                 {0}" -f $(if ($IncludeComments.IsPresent -or $doIncludeComments) { "requested when available" } else { "off" }))
    Write-Host ""
    Write-Host "Videos to process:"
    $videos | ForEach-Object { Write-Host " - $($_.FullName)" }
    Write-Host ""
}
else {
    Write-Host ""
    Write-Host ("Run plan: {0} video item(s), mode {1}, output {2}" -f $videos.Count, $processingModeSummary, $OutputFolder) -ForegroundColor Cyan
    Write-Host ("Translations: {0}" -f $(if ($translationTargets.Count -gt 0) { $translationTargets -join ", " } else { "none" })) -ForegroundColor Cyan
    Write-Host ("Video path: proxy/frame GPU preference {0}; Local Whisper {1}" -f $(if ($canUseFfmpegGpu) { "enabled with CPU fallback" } else { "off" }), $localWhisperPathSummary) -ForegroundColor Cyan
    if ($isFullReviewWorkflow) {
        Write-Host ("Codex evidence package: {0} ({1})" -f $(if ($includeFullReviewCodexEvidencePackage) { "included" } else { $fullReviewCodexEvidenceStatus }), $fullReviewCodexEvidenceSelectionSource) -ForegroundColor Cyan
    }
    Write-Host ("Evidence panel crops: {0}" -f (Get-EvidencePanelCropModeSummary -Mode $EvidencePanelCrops)) -ForegroundColor Cyan
    if ($ProcessingMode -eq "Hybrid") {
        Write-Host ("Hybrid translation: text-only OpenAI via {0}" -f $OpenAiProject) -ForegroundColor Cyan
        Write-Host ("Protected terms: {0}" -f $protectedTermsProfileSummary) -ForegroundColor Cyan
    }
    Write-Host ("Use -DebugMode for full tool and helper detail. script_run.log keeps the deep trace.") -ForegroundColor DarkCyan
    Write-Host ""
}

$estimate = $null
if (-not $SkipEstimate) {
    $estimate = Get-BestEffortEstimate `
        -Videos $videos `
        -FFmpegExe $FFmpegPath `
        -FFprobeExe $FFprobePath `
        -PythonCommand $PythonExe `
        -ModelName $WhisperModel `
        -LanguageCode $Language `
        -CanUseFfmpegGpu $canUseFfmpegGpu `
        -CanUseWhisperGpu $canUseWhisperGpu `
        -FrameIntervalSeconds $FrameIntervalSeconds `
        -TranscriptAudioMode $TranscriptAudioMode
}
else {
    Write-Log "Skipping runtime estimate because -SkipEstimate was requested." "WARN"
}

if ($estimate) {
    Write-Host "Estimated completion for this run"
    Write-Host "---------------------------------"
    Write-Host ("Total media duration:   {0}" -f (Format-DurationHuman $estimate.TotalDurationSeconds))
    Write-Host ("Proxy generation:       {0}" -f (Format-DurationHuman $estimate.ProxyEstimateSeconds))
    Write-Host ("Frame extraction:       {0}" -f (Format-DurationHuman $estimate.FramesEstimateSeconds))
    Write-Host ("Audio extraction:       {0}" -f (Format-DurationHuman $estimate.AudioEstimateSeconds))
    Write-Host ("Audio tracks detected:  {0}" -f $estimate.AudioTrackCount)
    Write-Host ("Transcript mode:        {0}" -f $estimate.TranscriptAudioModeResolved)
    Write-Host ("Effective transcription:{0}" -f (" " + (Format-DurationHuman $estimate.EffectiveTranscriptionDurationSeconds)))
    Write-Host ("Whisper transcription:  {0}" -f (Format-DurationHuman $estimate.WhisperEstimateSeconds))
    Write-Host ("Index/build overhead:   {0}" -f (Format-DurationHuman $estimate.IndexEstimateSeconds))
    Write-Host ("Estimated total:        {0}" -f (Format-DurationHuman $estimate.TotalEstimateSeconds))
    Write-Host ""

    if ($estimate.Warnings) {
        # 213: notes about how rough the estimate is; nothing for the operator to act on.
        foreach ($warning in $estimate.Warnings) {
            Write-Log $warning "INFO"
        }
    }

    $eta = (Get-Date).AddSeconds($estimate.TotalEstimateSeconds)
    Write-Host ("Estimated finish time:  {0}" -f $eta.ToString("yyyy-MM-dd hh:mm:ss tt"))
    Write-Host ""
    Write-Log ("Estimated total runtime: {0}" -f (Format-DurationHuman $estimate.TotalEstimateSeconds))
    Write-Log ("Estimated finish time: {0}" -f $eta.ToString("yyyy-MM-dd hh:mm:ss tt"))

    if ($translationTargets.Count -gt 0 -and ($ProcessingMode -eq "AI" -or $ProcessingMode -eq "Hybrid")) {
        $estimatedOpenAiModelForPreview = if (-not [string]::IsNullOrWhiteSpace($OpenAiModel)) { $OpenAiModel } else { $script:HybridAccuracyTranslationDefaultModel }
        $roughOpenAiTextCostEstimate = Get-RoughOpenAiTextCostEstimate `
            -TotalDurationSeconds $estimate.TotalDurationSeconds `
            -Model $estimatedOpenAiModelForPreview `
            -ItemCount $videos.Count
        if ($roughOpenAiTextCostEstimate) {
            Write-Host ("OpenAI text cost estimate:      about {0} if translation is needed for every file" -f (Format-EstimatedUsd $roughOpenAiTextCostEstimate.EstimatedCostUsd)) -ForegroundColor Cyan
            if ($translationTargets -contains "en") {
                Write-Host "OpenAI text cost note:          English-source files can still land at `$0 when the original transcript is copied." -ForegroundColor DarkCyan
            }
            if ($ProcessingMode -eq "AI" -and $OpenAiProject -eq "Private") {
                Write-Host "OpenAI cost note:               this preview covers tracked text translation only, not OpenAI audio transcription." -ForegroundColor DarkCyan
            }
            Write-Host ""
        }
    }
}

$processedItems = @()
$failedItems = @($remoteDownloadFailures)
# 214: recordings the operator skipped from Queue / Progress; not failures.
$skippedByYouItems = @()
$aiReviewPackages = @()
$fullReviewEvidenceWhisperModel = $WhisperModel
$fullReviewEvidenceDevicePreference = $null
$fullReviewEvidenceRuntimePrepared = $false
$fullReviewRemoteEvidenceSkipReason = "Remote URL Full Review inputs are supported for the normal package workflow, but remote-URL Codex evidence mode is intentionally out of scope."

$videoQueueOrdinal = 0
foreach ($video in $videos) {
    $videoQueueOrdinal += 1
    $queueSourceName = if ($sourceUrlByVideoPath.ContainsKey($video.FullName)) { [string]$sourceUrlByVideoPath[$video.FullName] } else { [string]$video.FullName }
    $queueSourceOrdinal = $videoQueueOrdinal
    Write-MMProgressV1 -Phase "Full Review" -SourceId (Get-Sha256ShortText -Value $queueSourceName) -SourceName $queueSourceName -SourceOrdinal $queueSourceOrdinal -SourceTotal $videos.Count -SourceState "active" -SourceTerminal:$false -ProgressKind stage -Activity ("Reviewing item {0} of {1}" -f $queueSourceOrdinal, $videos.Count)
    # 214: Pause and Skip from Queue / Progress, as Find my bug reports has them.
    $script:MMCurrentSourcePath = $video.FullName
    $script:MMSkipRequested = $false
    try {
        # A recording skipped before it started is never touched; a pause holds here first.
        $null = Invoke-MMRunControlCheck -StepName "the next recording"
        $result = Process-Video `
            -VideoPath $video.FullName `
            -BaseOutputFolder $OutputFolder `
            -FFmpegExe $FFmpegPath `
            -FFprobeExe $FFprobePath `
            -PythonCommand $PythonExe `
            -ModelName $WhisperModel `
            -LanguageCode $Language `
            -TranslationTargets $translationTargets `
            -SourceInfoJsonPath $(if ($sourceInfoJsonByVideoPath.ContainsKey($video.FullName)) { $sourceInfoJsonByVideoPath[$video.FullName] } else { "" }) `
            -RemoteAudioTrackInfo $(if ($remoteAudioTrackByVideoPath.ContainsKey($video.FullName)) { $remoteAudioTrackByVideoPath[$video.FullName] } else { $null }) `
            -DoCopyRaw:$doCopyRaw `
            -CommentsRequested:$doIncludeComments `
            -SummaryCsv $summaryCsv `
            -CanUseFfmpegGpu $canUseFfmpegGpu `
            -CanUseWhisperGpu $canUseWhisperGpu `
            -InteractiveMode:$(-not $NoPrompt) `
            -RequestedProcessingMode $processingModeResolution.RequestedMode `
            -ProcessingModeSelectionSource $processingModeResolution.SelectionSource `
            -ProcessingModeResolutionNote $processingModeResolution.ResolutionNote `
            -ProcessingMode $ProcessingMode `
            -OpenAiProject $OpenAiProject `
            -RequestedTranslationProvider $translationProviderResolution.RequestedProvider `
            -TranslationProviderSelectionSource $translationProviderResolution.SelectionSource `
            -TranslationProviderResolutionNote $translationProviderResolution.ResolutionNote `
            -TranslationProvider $TranslationProvider `
            -OpenAiModel $OpenAiModel `
            -OpenAiTranscriptionModel $ResolvedOpenAiTranscriptionModel `
            -ProtectedTermsProfileSelection $protectedTermsProfileSelection `
            -FrameIntervalSeconds $FrameIntervalSeconds `
            -FullReviewPanelCropMode $FullReviewPanelCrops `
            -FullReviewPanelCropCadenceSeconds $FullReviewPanelCropCadenceSeconds `
            -TranscriptAudioMode $TranscriptAudioMode `
            -TranscriptAudioStream $TranscriptAudioStream `
            -TranscriptAudioTrackOrdinal $TranscriptAudioTrackOrdinal `
            -PreferredTranscriptAudioTrackOrdinal $PreferredTranscriptAudioTrackOrdinal `
            -AudioTrackAudit:$AudioTrackAudit `
            -WhisperTimeoutSeconds $WhisperTimeoutSeconds `
            -HeartbeatSeconds $HeartbeatSeconds

        $processedItems += $result

        if ($includeFullReviewCodexEvidencePackage) {
            $fullReviewUsesRemoteInput = ($remoteInputSources.Count -gt 0 -or $downloadedInputCount -gt 0 -or $sourceInfoJsonByVideoPath.ContainsKey($video.FullName))
            if ($fullReviewUsesRemoteInput) {
                Set-FullReviewCodexEvidenceMetadata `
                    -ProcessedItem $result `
                    -Requested:$true `
                    -SelectionSource $fullReviewCodexEvidenceSelectionSource `
                    -Status "skipped" `
                    -SkipReason $fullReviewRemoteEvidenceSkipReason
                Write-Host ("Codex evidence package skipped for {0}: {1}" -f $result.SourceVideoName, $fullReviewRemoteEvidenceSkipReason) -ForegroundColor Yellow
                Write-Log ("Codex evidence package skipped for Full Review item '{0}': {1}" -f $result.SourceVideoName, $fullReviewRemoteEvidenceSkipReason) "WARN"
            }
            else {
                try {
                    if (-not $fullReviewEvidenceRuntimePrepared) {
                        if (-not $whisperModelWasExplicit -and $ProcessingMode -eq "AI" -and $OpenAiProject -eq "Private") {
                            $fullReviewEvidenceWhisperModel = $script:InteractiveLocalDefaultWhisperModel
                            Write-Log ("Full Review Codex evidence package defaulted Local Whisper model to '{0}' because AI Private Full Review does not otherwise use Local Whisper." -f $fullReviewEvidenceWhisperModel)
                        }

                        Test-PythonWhisper -PythonCommand $PythonExe
                        if ($null -eq $whisperProbe) {
                            $whisperProbe = Get-WhisperExecutionMode -PythonCommand $PythonExe
                        }
                        $fullReviewEvidenceDevicePreference = Resolve-WhisperDevicePreference `
                            -RequestedDevice $WhisperDevice `
                            -WhisperProbe $whisperProbe `
                            -RequiresLocalWhisper:$true
                        $fullReviewEvidenceRuntimePrepared = $true
                    }

                    $perVideoEvidenceResult = Invoke-CodexEvidencePackageBatch `
                        -InputPath $video.FullName `
                        -OutputFolder $result.OutputPath `
                        -PythonCommand $PythonExe `
                        -FFmpegExe $FFmpegPath `
                        -FFprobeExe $FFprobePath `
                        -ModelName $fullReviewEvidenceWhisperModel `
                        -LanguageCode $Language `
                        -CanUseWhisperGpu ([bool]$fullReviewEvidenceDevicePreference.PreferGpu) `
                        -WhisperTimeoutSeconds $WhisperTimeoutSeconds `
                        -HeartbeatSeconds $HeartbeatSeconds `
                        -Recurse:$false `
                        -OverwriteTranscripts:$OverwriteTranscripts `
                        -PreContextSeconds $PreContextSeconds `
                        -PostContextSeconds $PostContextSeconds `
                        -NarrationContextPreSeconds $NarrationContextPreSeconds `
                        -NarrationContextPostSeconds $NarrationContextPostSeconds `
                        -NarrationPauseThresholdSeconds $NarrationPauseThresholdSeconds `
                        -NarrationStopAtNextTicketBoundary ($NarrationStopAtNextTicketBoundary -eq "On") `
                        -FragmentedNarrationMode ($FragmentedNarrationMode -eq "On") `
                        -FrameOffsets @($resolvedEvidenceFrameOffsets) `
                        -AudioStreamIndex $EvidenceAudioStreamIndex `
                        -AudioStreamSelectionsJson $EvidenceAudioStreamSelectionsJson `
                        -TrackRoles $EvidenceTrackRoles `
                        -FrameCadenceSeconds $EvidenceFrameCadenceSeconds `
                        -MaxFramesPerCandidate $EvidenceMaxFramesPerCandidate `
                        -MaxItems $EvidenceMaxItems `
                        -RenderCandidateIds @($EvidenceRenderCandidateIds) `
                        -HandoffMode $EvidenceHandoffMode `
                        -PortableZipMaxMb $EvidencePortableZipMaxMb `
                        -PanelCropMode $EvidencePanelCrops `
                        -InvocationMode "full-review-addon" `
                        -TranscriptionGlossaryEntries (Get-MMSpellingWords) `
                        -TargetRepo $EvidenceTargetRepo `
                        -RepoMapPath $EvidenceRepoMapPath `
                        -RepoHintMode $EvidenceRepoHintMode `
                        -CustomMarkers @($effectiveEvidenceCustomMarkers) `
                        -CustomDomainTerms @($effectiveEvidenceCustomDomainTerms) `
                        -AudioStreamSelectionConfirmed:$EvidenceAudioStreamSelectionConfirmed `
                        -ExistingTranscriptJsonPath $result.TranscriptJsonPath `
                        -ExistingTranscriptSrtPath $result.TranscriptSrtPath `
                        -ExistingTranscriptTextPath $result.TranscriptTextPath `
                        -ExistingAudioPath $result.TranscriptSourceWav `
                        -ExistingTranscriptSource $(if ($result.IsAllAudioTracksTranscript) { "full_review_all_tracks" } else { "full_review_selected_track" })
                    Set-FullReviewCodexEvidenceMetadata `
                        -ProcessedItem $result `
                        -Requested:$true `
                        -SelectionSource $fullReviewCodexEvidenceSelectionSource `
                        -Status "included" `
                        -EvidenceResult $perVideoEvidenceResult
                }
                catch {
                    Set-FullReviewCodexEvidenceMetadata `
                        -ProcessedItem $result `
                        -Requested:$true `
                        -SelectionSource $fullReviewCodexEvidenceSelectionSource `
                        -Status "failed" `
                        -SkipReason $_.Exception.Message
                    $failedItems += [PSCustomObject]@{
                        SourceVideoName = $result.SourceVideoName
                        SourceVideoPath = $video.FullName
                        OutputFolderName = $result.OutputFolderName
                        OutputPath = $result.OutputPath
                        VideoPath = ("Codex evidence package add-on for {0}" -f $video.FullName)
                        FailurePhase = "CodexEvidence"
                        Message   = $_.Exception.Message
                        CodexEvidenceStatus = "failed"
                        AudioPresent = $result.AudioPresent
                    }
                    Write-Host ""
                    Write-Host ("FAIL Codex evidence package add-on for {0}" -f $result.SourceVideoName) -ForegroundColor Red
                    Write-Host $_.Exception.Message -ForegroundColor Red
                    Write-Log ("Full Review Codex evidence package failed for '{0}': {1}" -f $result.SourceVideoName, $_.Exception.Message) "ERROR"
                }
            }
        }
        else {
            Set-FullReviewCodexEvidenceMetadata `
                -ProcessedItem $result `
                -Requested:$false `
                -SelectionSource $fullReviewCodexEvidenceSelectionSource `
                -Status $fullReviewCodexEvidenceStatus
        }
        Set-NotePropertyValue -Object $result -Name "AiReviewZipPanelCropMode" -Value $AiReviewZipPanelCropMode

        $null = New-AiReviewArtifacts `
            -ProcessedItem $result `
            -AiReviewZipRequested:$doCreateAiReviewZip `
            -AiReviewZipMaxMb $AiReviewZipMaxMb `
            -EvidencePanelCropMode $EvidencePanelCrops `
            -EvidenceTargetRepo $EvidenceTargetRepo

        if ($doCreateAiReviewZip) {
            $zipInfo = Invoke-PhaseAction -Name "AI review zip" -Detail $result.SourceVideoName -Action {
                New-AiReviewZipPackage -ProcessedItem $result -MaxSizeMb $AiReviewZipMaxMb -PanelCropMode $AiReviewZipPanelCropMode
            }
            Set-NotePropertyValue -Object $result -Name "AiReviewZipPath" -Value $zipInfo.ZipPath
            $aiReviewPackages += [PSCustomObject]@{
                SourceVideoName = $result.SourceVideoName
                ZipPath         = $zipInfo.ZipPath
                ZipSizeMb       = $zipInfo.ZipSizeMb
                ProxyIncluded   = $zipInfo.ProxyIncluded
                EvidenceSupplementMode = $zipInfo.EvidenceSupplementMode
                PanelCropMode = $zipInfo.PanelCropMode
                PanelManifestIncluded = $zipInfo.PanelManifestIncluded
                PanelImageCount = $zipInfo.PanelImageCount
            }
        }
        Write-MMProgressV1 -Phase "Full Review" -SourceId (Get-Sha256ShortText -Value $queueSourceName) -SourceName $queueSourceName -SourceOrdinal $queueSourceOrdinal -SourceTotal $videos.Count -SourceState "completed" -SourceTerminal:$true -SourceCompleted $queueSourceOrdinal -ProgressKind work_units -Activity ("Completed item {0} of {1}" -f $queueSourceOrdinal, $videos.Count) -LatestArtifactPath $result.OutputPath
    }
    catch {
        if ((Test-MMSkipException $_) -or $script:MMSkipRequested -or (Test-MMSourceSkipRequested -SourcePath $video.FullName)) {
            $script:MMSkipRequested = $false
            $skippedByYouItems += [PSCustomObject]@{ SourceVideoName = $video.Name; SourceVideoPath = $video.FullName }
            Write-Host ("SKIPPED by you: {0}" -f $video.Name) -ForegroundColor Yellow
            # 213: the operator's own choice, not a warning.
            Write-Log ("Skipped by you: '{0}'. No package is made for this recording." -f $video.FullName) "INFO"
            Write-MMProgressV1 -Phase "Full Review" -SourceId (Get-Sha256ShortText -Value $queueSourceName) -SourceName $queueSourceName -SourceOrdinal $queueSourceOrdinal -SourceTotal $videos.Count -SourceState "skipped" -SourceTerminal:$true -ProgressKind stage -Activity ("Skipped item {0} of {1}" -f $queueSourceOrdinal, $videos.Count)
            continue
        }
        $failedOutputFolderName = Get-SafeFolderName ([System.IO.Path]::GetFileNameWithoutExtension($video.Name))
        $failedOutputPath = Join-Path $OutputFolder $failedOutputFolderName
        $failedItems += [PSCustomObject]@{
            SourceVideoName = $video.Name
            SourceVideoPath = $video.FullName
            OutputFolderName = $failedOutputFolderName
            OutputPath = $failedOutputPath
            VideoPath = $video.FullName
            FailurePhase = Get-FullReviewFailurePhase -Message $_.Exception.Message
            Message   = $_.Exception.Message
            CodexEvidenceStatus = $(if ($includeFullReviewCodexEvidencePackage) { "not_attempted" } else { $fullReviewCodexEvidenceStatus })
            AudioPresent = ""
        }

        Write-Host ""
        Write-Host ("FAIL {0}" -f $video.FullName) -ForegroundColor Red
        Write-Host $_.Exception.Message -ForegroundColor Red
        Write-MMProgressV1 -Phase "Full Review" -SourceId (Get-Sha256ShortText -Value $queueSourceName) -SourceName $queueSourceName -SourceOrdinal $queueSourceOrdinal -SourceTotal $videos.Count -SourceState "failed" -SourceTerminal:$true -FailedCount $failedItems.Count -ProgressKind stage -Activity ("Review failed for item {0} of {1}: {2}" -f $queueSourceOrdinal, $videos.Count, $_.Exception.Message)

        if ($script:CurrentLogFile) {
            Add-Content -LiteralPath $script:CurrentLogFile -Value "----- FAILURE -----"
            Add-Content -LiteralPath $script:CurrentLogFile -Value $_.Exception.Message
            if ($_.ScriptStackTrace) {
                Add-Content -LiteralPath $script:CurrentLogFile -Value $_.ScriptStackTrace
            }
        }
    }
}

# 214: no recording is current now, so a skipped last one cannot stop the steps after the loop.
$script:MMCurrentSourcePath = ""
$fullReviewCodexEvidenceStatus = Resolve-FullReviewCodexEvidenceStatus `
    -ProcessedItems $processedItems `
    -FailedItems $failedItems `
    -Requested:$includeFullReviewCodexEvidencePackage `
    -DefaultStatus $fullReviewCodexEvidenceStatus
if ($includeFullReviewCodexEvidencePackage -and $fullReviewCodexEvidenceStatus -eq "skipped") {
    $fullReviewCodexEvidenceSkipReason = $fullReviewRemoteEvidenceSkipReason
}
elseif ($includeFullReviewCodexEvidencePackage -and $fullReviewCodexEvidenceStatus -eq "failed") {
    $fullReviewCodexEvidenceSkipReason = "One or more per-video Codex evidence packages failed. See FULL_REVIEW_RUN_MANIFEST.json for per-video status."
}
elseif ($includeFullReviewCodexEvidencePackage -and $fullReviewCodexEvidenceStatus -eq "partial") {
    $fullReviewCodexEvidenceSkipReason = "One or more videos did not produce requested Codex evidence. See EVIDENCE_COVERAGE_MATRIX.md and FULL_REVIEW_RUN_MANIFEST.json."
}

$coverageMatrixResult = New-EvidenceCoverageMatrix `
    -OutputRoot $OutputFolder `
    -ProcessedItems $processedItems `
    -FailedItems $failedItems `
    -CodexEvidenceRequested:$includeFullReviewCodexEvidencePackage

New-FullReviewRunManifest `
    -ManifestPath $fullReviewRunManifest `
    -OutputRoot $OutputFolder `
    -ProcessedItems $processedItems `
    -FailedItems $failedItems `
    -CodexEvidenceRequested:$includeFullReviewCodexEvidencePackage `
    -CodexEvidenceSelectionSource $fullReviewCodexEvidenceSelectionSource `
    -CodexEvidenceStatus $fullReviewCodexEvidenceStatus `
    -CodexEvidenceSkipReason $fullReviewCodexEvidenceSkipReason `
    -CodexEvidenceResult $fullReviewCodexEvidenceResult `
    -EvidencePanelCropMode $EvidencePanelCrops `
    -EvidenceTargetRepo $EvidenceTargetRepo `
    -CoverageRows @($coverageMatrixResult.Rows) `
    -CoverageMatrixCsvPath $coverageMatrixResult.CsvPath `
    -CoverageMatrixMarkdownPath $coverageMatrixResult.MarkdownPath

New-MasterReadme `
    -MasterReadmePath $masterReadme `
    -OutputRoot $OutputFolder `
    -ProcessedItems $processedItems `
    -FailedItems $failedItems `
    -FrameIntervalSeconds $FrameIntervalSeconds `
    -FullReviewRunManifestPath $fullReviewRunManifest `
    -CoverageMatrixCsvPath $coverageMatrixResult.CsvPath `
    -CoverageMatrixMarkdownPath $coverageMatrixResult.MarkdownPath `
    -CodexEvidencePackageStatus $fullReviewCodexEvidenceStatus `
    -CodexEvidencePackageOutput $(if ($fullReviewCodexEvidenceResult) { [string]$fullReviewCodexEvidenceResult.OutputRoot } else { "" }) `
    -CodexEvidencePackageManifest $(if ($fullReviewCodexEvidenceResult) { [string]$fullReviewCodexEvidenceResult.ManifestPath } else { "" }) `
    -EvidencePanelCropMode $EvidencePanelCrops

Write-Phase -Name "Final Summary" -Detail "Packaging complete"
$partialItems = @($processedItems | Where-Object { $_.PackageStatus -eq "PARTIAL_SUCCESS" })
$blockingPartialItems = @($processedItems | Where-Object { $_.ShouldFailRun })
Write-Host ("Successful packages: {0}" -f ($processedItems.Count - $partialItems.Count))
Write-Host ("Partial packages:    {0}" -f $partialItems.Count)
Write-Host ("Failed packages:     {0}" -f $failedItems.Count)
Write-Host ("Output root:         {0}" -f $OutputFolder)
Write-Host ("Master README:       {0}" -f $masterReadme)
Write-Host ("Processing summary:  {0}" -f $summaryCsv)
Write-Host ("Run manifest:        {0}" -f $fullReviewRunManifest)
Write-Host ("Coverage matrix:     {0}" -f $coverageMatrixResult.MarkdownPath)
Write-Host ("Codex evidence:      {0} ({1})" -f $fullReviewCodexEvidenceStatus, $fullReviewCodexEvidenceSelectionSource)
if (-not [string]::IsNullOrWhiteSpace($fullReviewCodexEvidenceSkipReason)) {
    Write-Host ("  Evidence note:     {0}" -f $fullReviewCodexEvidenceSkipReason)
}
if ($translationTargets.Count -gt 0 -and ($ProcessingMode -eq "AI" -or $ProcessingMode -eq "Hybrid")) {
    Write-Host ("Estimated OpenAI text total: {0}" -f (Format-EstimatedUsd $script:SessionEstimatedOpenAiTextCostUsd))
    if ($ProcessingMode -eq "AI" -and $OpenAiProject -eq "Private") {
        Write-Host "OpenAI cost note:           text total only; OpenAI audio transcription is not included." -ForegroundColor DarkCyan
    }
}

foreach ($item in $processedItems) {
    if ($item.PackageStatus -eq "PARTIAL_SUCCESS") {
        Write-Host ("PARTIAL {0}" -f $item.SourceVideoName) -ForegroundColor Yellow
    }
    else {
        Write-Host ("PASS {0}" -f $item.SourceVideoName) -ForegroundColor Green
    }
    Write-Host ("  Output:  {0}" -f $item.OutputPath)
    Write-Host ("  Mode:    {0}" -f $item.ProcessingMode)
    if (-not [string]::IsNullOrWhiteSpace($item.OpenAiProject)) {
        Write-Host ("  AI:      {0}" -f $item.OpenAiProject)
    }
    Write-Host ("  Proxy:   {0}" -f $item.ProxyMode)
    Write-Host ("  Frames:  {0}" -f $item.FrameMode)
    Write-Host ("  Trans:   {0}" -f $item.TranscriptionPath)
    Write-Host ("  Engine:  {0}" -f $item.WhisperMode)
    Write-Host ("  Lang:    {0}" -f $(if ([string]::IsNullOrWhiteSpace($item.DetectedLanguage)) { "n/a" } else { $item.DetectedLanguage }))
    Write-Host ("  Xlate:   {0}" -f $(if ($item.TranslationTargets.Count -gt 0) { $item.TranslationTargets -join ", " } else { "none" }))
    Write-Host ("  Path:    {0}" -f $(if ([string]::IsNullOrWhiteSpace($item.TranslationProvider) -or $item.TranslationProvider -eq "none") { "none" } else { $item.TranslationProvider }))
    if (-not [string]::IsNullOrWhiteSpace($item.ProtectedTermsProfile)) {
        Write-Host ("  Terms:   {0}" -f $item.ProtectedTermsProfile)
    }
    if (-not [string]::IsNullOrWhiteSpace($item.OpenAiTranslationSummary)) {
        Write-Host ("  OpenAI:  {0}" -f $item.OpenAiTranslationSummary)
    }
    if (-not [string]::IsNullOrWhiteSpace($item.EstimatedOpenAiTextCostUsd)) {
        Write-Host ("  AI Cost: {0}" -f (Format-EstimatedUsd $item.EstimatedOpenAiTextCostUsd))
    }
    if (-not [string]::IsNullOrWhiteSpace($item.TranslationStatus)) {
        Write-Host ("  Status:  {0}" -f $item.TranslationStatus)
    }
    if (-not [string]::IsNullOrWhiteSpace($item.TranslationNotes)) {
        Write-Host ("  Notes:   {0}" -f $item.TranslationNotes)
    }
    if (-not [string]::IsNullOrWhiteSpace($item.NextSteps)) {
        Write-Host ("  Next:    {0}" -f $item.NextSteps)
    }
    if (-not [string]::IsNullOrWhiteSpace($item.CommentsSummary)) {
        Write-Host ("  Comments:{0}" -f " $($item.CommentsSummary)")
    }
    if (-not [string]::IsNullOrWhiteSpace($item.AiReviewReadmePath)) {
        Write-Host ("  AI read: {0}" -f $item.AiReviewReadmePath)
    }
    if (-not [string]::IsNullOrWhiteSpace($item.CodexEvidenceStatus)) {
        Write-Host ("  Evidence:{0}" -f " $($item.CodexEvidenceStatus)")
        if (-not [string]::IsNullOrWhiteSpace($item.CodexEvidenceOutputRoot)) {
            Write-Host ("  Ev path: {0}" -f $item.CodexEvidenceOutputRoot)
        }
        if (-not [string]::IsNullOrWhiteSpace($item.CodexEvidenceManifestPath)) {
            Write-Host ("  Ev json: {0}" -f $item.CodexEvidenceManifestPath)
        }
    }
}

foreach ($zip in $aiReviewPackages) {
    Write-Host ("AI review ZIP {0}" -f $zip.SourceVideoName) -ForegroundColor Cyan
    Write-Host ("  File:   {0}" -f $zip.ZipPath)
    Write-Host ("  SizeMB: {0}" -f $zip.ZipSizeMb)
    Write-Host ("  Proxy:  {0}" -f $(if ($zip.ProxyIncluded) { "included" } else { "omitted to stay under limit" }))
    if (-not [string]::IsNullOrWhiteSpace($zip.EvidenceSupplementMode) -and $zip.EvidenceSupplementMode -ne "none") {
        Write-Host ("  AI evidence supplement: {0}" -f $zip.EvidenceSupplementMode)
    }
}

foreach ($item in $failedItems) {
    Write-Host ("FAIL {0}" -f $item.VideoPath) -ForegroundColor Red
    Write-Host ("  Error: {0}" -f $item.Message) -ForegroundColor Red
}

if ($skippedByYouItems.Count -gt 0) {
    Write-Log ("Skipped by you: {0} recording(s)." -f $skippedByYouItems.Count) "INFO"
}
# 214: a run where you skipped every recording did what you asked; it has not failed.
if ($failedItems.Count -gt 0 -or $blockingPartialItems.Count -gt 0 -or ($processedItems.Count -eq 0 -and $skippedByYouItems.Count -eq 0)) {
    Write-Log ("FAIL: Processing completed with {0} hard failure(s) and {1} partial package(s) requiring attention." -f $failedItems.Count, $blockingPartialItems.Count) "ERROR"
    throw ("Processing completed with {0} hard failure(s) and {1} partial package(s) requiring attention." -f $failedItems.Count, $blockingPartialItems.Count)
}

Write-Log ("PASS: Processed {0} video(s). Partial packages: {1}. Output root: {2}" -f $processedItems.Count, $partialItems.Count, $OutputFolder)
}
finally {
    if (-not $KeepTempFiles) {
        foreach ($downloadPath in @($downloadedInputPaths | Select-Object -Unique)) {
            if (-not [string]::IsNullOrWhiteSpace($downloadPath) -and (Test-Path -LiteralPath $downloadPath)) {
                Remove-Item -LiteralPath $downloadPath -Recurse -Force -ErrorAction SilentlyContinue
            }
        }

        if (Test-Path -LiteralPath $bootstrapLog) {
            Remove-Item -LiteralPath $bootstrapLog -Force -ErrorAction SilentlyContinue
        }
    }
}

if ($doOpenOutputInExplorer) {
    try {
        Invoke-Item -LiteralPath $OutputFolder
        Write-Log "Opened output folder in Windows Explorer."
    }
    catch {
        Write-Log "Could not open output folder in Windows Explorer: $($_.Exception.Message)" "WARN"
    }
}
