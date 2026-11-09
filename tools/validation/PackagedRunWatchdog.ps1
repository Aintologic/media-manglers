function Get-PackagedRunWatchdogLabelToken {
    param([string]$Label)

    if ([string]::IsNullOrWhiteSpace($Label)) {
        return "packaged-run"
    }

    $token = $Label.ToLowerInvariant() -replace "[^a-z0-9]+", "-"
    $token = $token.Trim("-")

    if ([string]::IsNullOrWhiteSpace($token)) {
        return "packaged-run"
    }

    return $token
}

function Invoke-PackagedRunWithWatchdog {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [string[]]$Arguments = @(),

        [Parameter(Mandatory = $true)]
        [string]$Label,

        [string]$WorkingDirectory,

        [string]$OutputRoot,

        [string]$LogRoot,

        [int]$HeartbeatSeconds = 15,

        [int]$FirstOutputDeadlineSeconds = 30,

        [int]$BootstrapDeadlineSeconds = 60,

        [int]$TimeoutSeconds = 1800,

        [string]$BootstrapRelativePath = "_script_bootstrap.log"
    )

    if (-not (Test-Path -LiteralPath $FilePath)) {
        throw "Packaged executable not found: $FilePath"
    }

    if ([string]::IsNullOrWhiteSpace($WorkingDirectory)) {
        $WorkingDirectory = Split-Path -Path $FilePath -Parent
    }

    if (-not [string]::IsNullOrWhiteSpace($OutputRoot) -and -not (Test-Path -LiteralPath $OutputRoot)) {
        New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
    }

    if ([string]::IsNullOrWhiteSpace($LogRoot)) {
        if (-not [string]::IsNullOrWhiteSpace($OutputRoot)) {
            $LogRoot = $OutputRoot
        }
        else {
            $LogRoot = $WorkingDirectory
        }
    }

    if (-not (Test-Path -LiteralPath $LogRoot)) {
        New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
    }

    $labelToken = Get-PackagedRunWatchdogLabelToken -Label $Label
    $stdoutPath = Join-Path $LogRoot ("_{0}.stdout.log" -f $labelToken)
    $stderrPath = Join-Path $LogRoot ("_{0}.stderr.log" -f $labelToken)
    $consoleLogPath = Join-Path $LogRoot ("_{0}.console.log" -f $labelToken)

    Remove-Item -LiteralPath $stdoutPath, $stderrPath, $consoleLogPath -Force -ErrorAction SilentlyContinue

    $bootstrapPath = $null
    if (-not [string]::IsNullOrWhiteSpace($OutputRoot) -and -not [string]::IsNullOrWhiteSpace($BootstrapRelativePath)) {
        $bootstrapPath = Join-Path $OutputRoot $BootstrapRelativePath
    }

    Write-Host ("Running: {0}" -f $Label) -ForegroundColor Cyan

    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $Arguments `
        -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -PassThru

    $start = Get-Date
    $nextHeartbeat = if ($HeartbeatSeconds -gt 0) { $start.AddSeconds($HeartbeatSeconds) } else { $null }
    $firstOutputObserved = $false
    $bootstrapObserved = $false
    $terminationMessage = $null

    while (-not $process.HasExited) {
        Start-Sleep -Seconds 1

        $now = Get-Date
        $elapsedSeconds = [int][Math]::Floor(($now - $start).TotalSeconds)
        $stdoutLength = if (Test-Path -LiteralPath $stdoutPath) { (Get-Item -LiteralPath $stdoutPath).Length } else { 0 }
        $stderrLength = if (Test-Path -LiteralPath $stderrPath) { (Get-Item -LiteralPath $stderrPath).Length } else { 0 }
        $haveOutput = ($stdoutLength + $stderrLength) -gt 0

        if (-not $firstOutputObserved -and $haveOutput) {
            $firstOutputObserved = $true
            Write-Host ("{0}: first console output observed after {1}s" -f $Label, $elapsedSeconds) -ForegroundColor DarkCyan
        }

        if ($bootstrapPath -and -not $bootstrapObserved -and (Test-Path -LiteralPath $bootstrapPath)) {
            $bootstrapObserved = $true
            Write-Host ("{0}: bootstrap log observed after {1}s" -f $Label, $elapsedSeconds) -ForegroundColor DarkCyan
        }

        if ($nextHeartbeat -and $now -ge $nextHeartbeat) {
            $statusParts = New-Object System.Collections.Generic.List[string]
            [void]$statusParts.Add(("output={0}" -f $(if ($firstOutputObserved) { "yes" } else { "no" })))
            if ($bootstrapPath) {
                [void]$statusParts.Add(("bootstrap={0}" -f $(if ($bootstrapObserved) { "yes" } else { "no" })))
            }
            Write-Host ("{0}: still running... elapsed {1}s; {2}" -f $Label, $elapsedSeconds, ($statusParts -join "; ")) -ForegroundColor DarkGray
            $nextHeartbeat = $now.AddSeconds($HeartbeatSeconds)
        }

        if (-not $firstOutputObserved -and $FirstOutputDeadlineSeconds -gt 0 -and $elapsedSeconds -ge $FirstOutputDeadlineSeconds) {
            $terminationMessage = "{0} produced no console output within {1} seconds." -f $Label, $FirstOutputDeadlineSeconds
            try { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue } catch { }
            break
        }

        if ($bootstrapPath -and -not $bootstrapObserved -and $BootstrapDeadlineSeconds -gt 0 -and $elapsedSeconds -ge $BootstrapDeadlineSeconds) {
            $terminationMessage = "{0} produced no bootstrap evidence within {1} seconds. Expected: {2}" -f $Label, $BootstrapDeadlineSeconds, $bootstrapPath
            try { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue } catch { }
            break
        }

        if ($TimeoutSeconds -gt 0 -and $elapsedSeconds -ge $TimeoutSeconds) {
            $terminationMessage = "{0} exceeded the packaged-run timeout of {1} seconds." -f $Label, $TimeoutSeconds
            try { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue } catch { }
            break
        }
    }

    try { $process.WaitForExit() } catch { }
    $elapsedTotalSeconds = [math]::Round(((Get-Date) - $start).TotalSeconds, 1)
    $exitCode = $null

    try {
        $process.Refresh()
        $exitCode = $process.ExitCode
    }
    catch {
        $exitCode = $null
    }

    $stdoutText = if (Test-Path -LiteralPath $stdoutPath) { Get-Content -LiteralPath $stdoutPath -Raw } else { "" }
    $stderrText = if (Test-Path -LiteralPath $stderrPath) { Get-Content -LiteralPath $stderrPath -Raw } else { "" }
    $consoleSections = New-Object System.Collections.Generic.List[string]
    $summaryPath = if (-not [string]::IsNullOrWhiteSpace($OutputRoot)) { Join-Path $OutputRoot "PROCESSING_SUMMARY.csv" } else { $null }
    $scriptRunLog = if (-not [string]::IsNullOrWhiteSpace($OutputRoot)) {
        Get-ChildItem -LiteralPath $OutputRoot -Recurse -Filter "script_run.log" -File -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    else {
        $null
    }

    if (-not [string]::IsNullOrWhiteSpace($stdoutText)) {
        [void]$consoleSections.Add($stdoutText.TrimEnd())
    }

    if (-not [string]::IsNullOrWhiteSpace($stderrText)) {
        [void]$consoleSections.Add(("----- STDERR -----`r`n{0}" -f $stderrText.TrimEnd()))
    }

    if ($consoleSections.Count -gt 0) {
        Set-Content -LiteralPath $consoleLogPath -Value ($consoleSections -join "`r`n") -Encoding UTF8
    }

    if ($null -eq $exitCode -and [string]::IsNullOrWhiteSpace($terminationMessage)) {
        if (-not [string]::IsNullOrWhiteSpace($stderrText)) {
            $exitCode = -1
        }
        elseif (($summaryPath -and (Test-Path -LiteralPath $summaryPath)) -or $scriptRunLog) {
            $exitCode = 0
        }
    }

    if ($null -eq $exitCode) {
        $exitCode = -1
    }

    if (-not [string]::IsNullOrWhiteSpace($terminationMessage)) {
        throw ("{0} Console log: {1} StdOut: {2} StdErr: {3}" -f $terminationMessage, $consoleLogPath, $stdoutPath, $stderrPath)
    }

    if ($exitCode -ne 0) {
        throw ("{0} failed with exit code {1}. Console log: {2} StdOut: {3} StdErr: {4}" -f $Label, $exitCode, $consoleLogPath, $stdoutPath, $stderrPath)
    }

    Write-Host ("PASS {0} completed in {1}s" -f $Label, $elapsedTotalSeconds) -ForegroundColor Green

    return [pscustomobject]@{
        ExitCode            = $exitCode
        ElapsedSeconds      = $elapsedTotalSeconds
        StdOutPath          = $stdoutPath
        StdErrPath          = $stderrPath
        ConsoleLogPath      = $consoleLogPath
        FirstOutputObserved = $firstOutputObserved
        BootstrapObserved   = $bootstrapObserved
        BootstrapPath       = $bootstrapPath
    }
}
