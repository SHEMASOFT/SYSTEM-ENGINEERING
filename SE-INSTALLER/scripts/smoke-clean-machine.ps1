#Requires -Version 5.1
<#
.SYNOPSIS
    Reproducible Windows smoke test for the SE one-command bootstrap.

.DESCRIPTION
    Runs the bootstrap in a disposable Windows VM or Windows Sandbox. The
    default ``DryRun`` mode creates the isolated venv, installs se-installer and
    exercises the planning/validation path without installing Python, Node,
    OpenCode or MCP packages. ``Install`` mode performs the real install and
    checks the resulting runtime and MCP registration.

    Run this on a clean image (no Python/Node/OpenCode, and preferably no
    package manager) to validate the path a new operator follows. The script
    writes a JSON report and exits non-zero if any check fails.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File SE-INSTALLER\scripts\smoke-clean-machine.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File SE-INSTALLER\scripts\smoke-clean-machine.ps1 -Mode Install
#>
[CmdletBinding()]
param(
    [ValidateSet("DryRun", "Install")]
    [string] $Mode = "DryRun",
    [string] $ReportPath = ""
)

$ErrorActionPreference = "Stop"

$InstallerRoot = Split-Path -Parent $PSScriptRoot
$RepoRoot = Split-Path -Parent $InstallerRoot
$Bootstrap = Join-Path $InstallerRoot "bootstrap.ps1"
$VenvPython = Join-Path $InstallerRoot ".venv\Scripts\python.exe"
$SeCli = Join-Path $RepoRoot "SCRIPTS\se.py"
if (-not $ReportPath) {
    $ReportPath = Join-Path $env:TEMP ("se-smoke-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".json")
}

$script:Results = @()
$script:Failed = $false

function Add-Result {
    param(
        [string] $Name,
        [string] $Status,
        [string] $Detail,
        [int] $ExitCode = 0,
        [double] $Seconds = 0
    )
    $script:Results += [pscustomobject]@{
        name = $Name
        status = $Status
        detail = $Detail
        exit_code = $ExitCode
        seconds = [math]::Round($Seconds, 2)
    }
    $color = switch ($Status) {
        "PASS" { "Green" }
        "SKIP" { "Yellow" }
        default { "Red" }
    }
    Write-Host ("[{0}] {1} ({2:n1}s)" -f $Status, $Name, $Seconds) -ForegroundColor $color
    if ($Detail) {
        Write-Host ("       " + $Detail) -ForegroundColor DarkGray
    }
}

function Invoke-Step {
    param(
        [string] $Name,
        [scriptblock] $Action,
        [switch] $AllowFailure
    )
    $watch = [Diagnostics.Stopwatch]::StartNew()
    try {
        $output = (& $Action 2>&1 | Out-String).Trim()
        $exit = $LASTEXITCODE
        if ($null -eq $exit) { $exit = 0 }
        $ok = ($exit -eq 0) -or $AllowFailure
        $detail = if ($output) { $output.Split("`n")[-1].Trim() } else { "" }
        $status = if ($ok) { "PASS" } else { "FAIL" }
        if ($ok -and $AllowFailure -and $exit -ne 0) { $status = "WARN" }
        Add-Result -Name $Name -Status $status -Detail $detail -ExitCode $exit -Seconds $watch.Elapsed.TotalSeconds
        if (-not $ok) { $script:Failed = $true }
        return $output
    } catch {
        Add-Result -Name $Name -Status "FAIL" -Detail $_.Exception.Message -ExitCode 1 -Seconds $watch.Elapsed.TotalSeconds
        $script:Failed = $true
        return ""
    }
}

function Get-HostInfo {
    $tools = @("python", "py", "node", "npx", "opencode", "winget", "choco", "scoop")
    $found = foreach ($tool in $tools) {
        $cmd = Get-Command $tool -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source) { "$tool=$($cmd.Source)" }
    }
    return [pscustomobject]@{
        timestamp = (Get-Date).ToString("o")
        mode = $Mode
        os = [System.Environment]::OSVersion.VersionString
        powershell = $PSVersionTable.PSVersion.ToString()
        is_64_bit = [Environment]::Is64BitProcess
        architecture = $env:PROCESSOR_ARCHITECTURE
        tools = @($found)
        report = $ReportPath
    }
}

Write-Host "SE clean-machine smoke test"
Write-Host "  mode:   $Mode"
Write-Host "  repo:   $RepoRoot"
Write-Host "  report: $ReportPath"
Write-Host ""

if (-not (Test-Path $Bootstrap)) {
    Add-Result -Name "bootstrap script" -Status "FAIL" -Detail "$Bootstrap not found"
    $script:Failed = $true
} elseif (-not (Test-Path $SeCli)) {
    Add-Result -Name "se CLI" -Status "FAIL" -Detail "$SeCli not found"
    $script:Failed = $true
} else {
    Invoke-Step -Name "bootstrap install --recommended --dry-run" -Action {
        & $Bootstrap install --recommended --dry-run
    } | Out-Null

    if (-not (Test-Path $VenvPython)) {
        Add-Result -Name "bootstrap venv" -Status "FAIL" -Detail "$VenvPython not found after the dry-run"
        $script:Failed = $true
    } else {
        Invoke-Step -Name "se validate" -Action {
            & $VenvPython $SeCli validate
        } | Out-Null

        Invoke-Step -Name "se doctor" -Action {
            & $VenvPython $SeCli doctor
        } | Out-Null

        Invoke-Step -Name "se install --dry-run" -Action {
            & $VenvPython $SeCli install --dry-run --project $RepoRoot
        } | Out-Null
    }

    if ($Mode -eq "Install") {
        Invoke-Step -Name "bootstrap install --recommended (real)" -Action {
            & $Bootstrap install --recommended
        } | Out-Null

        Invoke-Step -Name "node --version" -Action { & node --version } | Out-Null
        Invoke-Step -Name "npx --version" -Action { & npx --version } | Out-Null
        Invoke-Step -Name "opencode --version" -Action { & opencode --version } | Out-Null

        $config = Join-Path $RepoRoot "opencode.jsonc"
        if (-not (Test-Path $config)) {
            Add-Result -Name "opencode.jsonc" -Status "FAIL" -Detail "$config not found"
            $script:Failed = $true
        } else {
            $text = Get-Content $config -Raw
            $missing = @()
            foreach ($server in @("context7", "filesystem")) {
                if ($text -notmatch [regex]::Escape('"' + $server + '"')) { $missing += $server }
            }
            if ($missing.Count -eq 0) {
                Add-Result -Name "MCP registration" -Status "PASS" -Detail "context7 and filesystem are present in opencode.jsonc"
            } else {
                Add-Result -Name "MCP registration" -Status "FAIL" -Detail ("missing: " + ($missing -join ", "))
                $script:Failed = $true
            }
        }

        Invoke-Step -Name "se doctor after install" -Action {
            & $VenvPython $SeCli doctor
        } | Out-Null
    } else {
        Add-Result -Name "real install and MCP registration" -Status "SKIP" -Detail "use -Mode Install in a disposable VM"
    }
}

$hostInfo = Get-HostInfo
$report = [pscustomobject]@{
    schema = "se.smoke/1"
    status = if ($script:Failed) { "FAIL" } else { "PASS" }
    host = $hostInfo
    checks = $script:Results
}
$report | ConvertTo-Json -Depth 6 | Set-Content -Path $ReportPath -Encoding UTF8

Write-Host ""
Write-Host ("SMOKE: {0} ({1} checks)" -f $report.status, $script:Results.Count)
Write-Host "Report: $ReportPath"
if ($script:Failed) { exit 1 }
exit 0
