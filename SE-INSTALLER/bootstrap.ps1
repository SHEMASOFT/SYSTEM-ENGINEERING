#Requires -Version 5.1
<#
.SYNOPSIS
    SE Installer — one-command bootstrap (Windows).

.DESCRIPTION
    Creates an isolated virtual environment under SE-INSTALLER\.venv, installs
    the se-installer package into it, and forwards every remaining argument to
    the `se-installer` CLI. This is the one-command entry point for Windows.

    After a successful `install` (and unless --dry-run is used), it also runs
    the repository's `se install` to register the SE MCP servers for OpenCode.
    Pass --skip-mcp-registration to opt out, for example when installing only
    another runtime.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File bootstrap.ps1 tui

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File bootstrap.ps1 install --recommended --dry-run

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File bootstrap.ps1 install --recommended --skip-mcp-registration

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File bootstrap.ps1 list --json
#>
[CmdletBinding()]
param(
    # Every argument after the script name is forwarded verbatim to the
    # `se-installer` CLI. Without this catch-all, `[CmdletBinding()]` rejects
    # positional arguments ("A positional parameter cannot be found that
    # accepts argument 'install'"), which broke the documented one-command
    # entry point on Windows.
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $InstallerArgs
)

$ErrorActionPreference = "Stop"

$InstallerRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$VenvDir       = Join-Path $InstallerRoot ".venv"
$VenvPython    = Join-Path $VenvDir "Scripts\python.exe"
$InstallerExe  = Join-Path $VenvDir "Scripts\se-installer.exe"
$RepoRoot      = Split-Path -Parent $InstallerRoot
$SeCli         = Join-Path $RepoRoot "SCRIPTS\se.py"

# `--skip-mcp-registration` is a bootstrap-only switch: se-installer does not
# know it, so strip it before forwarding and remember the intent.
$SkipMcpRegistration = $false
$ForwardArgs = @()
foreach ($arg in @($InstallerArgs)) {
    if ($arg -ieq "--skip-mcp-registration") {
        $SkipMcpRegistration = $true
    } else {
        $ForwardArgs += $arg
    }
}

function Test-InstallerArg {
    param([string] $Value)
    foreach ($arg in @($InstallerArgs)) {
        if ($arg -ieq $Value) { return $true }
    }
    return $false
}

function Test-OpenCodeRuntimeRequested {
    # se-installer defaults to OpenCode when --runtimes is omitted. When the
    # operator asks for another runtime only (e.g. --runtimes codex), OpenCode
    # MCP registration is not wanted.
    $list = @($InstallerArgs)
    for ($i = 0; $i -lt $list.Count; $i++) {
        $arg = $list[$i]
        if ($arg -ieq "--runtimes") {
            $j = $i + 1
            while ($j -lt $list.Count -and -not $list[$j].StartsWith("-")) {
                if ($list[$j] -ieq "opencode") { return $true }
                $j++
            }
            return $false
        }
        if ($arg -match '^--runtimes=(.+)$') {
            return (($Matches[1] -split ',') -contains "opencode")
        }
    }
    return $true
}

function Find-PythonExe {
    # 1) `python` on PATH, if it is a real 3.10+ interpreter
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) {
        try {
            $ver = & $cmd.Source -c "import sys; print('ok' if sys.version_info >= (3, 10) else 'old')"
            if ("$ver" -eq "ok") { return $cmd.Source }
        } catch { }
    }
    # 2) the `py` launcher, pinned to the 3.x series
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        try {
            $candidate = & py -3 -c "import sys; print(sys.executable)"
            if ($LASTEXITCODE -eq 0 -and $candidate) { return $candidate }
        } catch { }
    }
    return $null
}

$PythonExe = Find-PythonExe
if (-not $PythonExe) {
    Write-Error "Python 3.10+ is required but was not found on PATH. Install it from https://www.python.org/downloads/"
}

Write-Host "bootstrap: python = $PythonExe"
Write-Host "bootstrap: venv   = $VenvDir"

if (-not (Test-Path $VenvPython)) {
    Write-Host "bootstrap: creating virtual environment ..."
    & $PythonExe -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "bootstrap: installing se-installer into the venv ..."
& $VenvPython -m pip install --quiet --upgrade pip
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $VenvPython -m pip install --quiet -e $InstallerRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "bootstrap: running se-installer ..."
if (Test-Path $InstallerExe) {
    & $InstallerExe @ForwardArgs
} else {
    & $VenvPython -m se_installer.cli @ForwardArgs
}
$InstallerExitCode = $LASTEXITCODE
if ($InstallerExitCode -ne 0) { exit $InstallerExitCode }

$Command = if ($ForwardArgs.Count -gt 0) { $ForwardArgs[0] } else { "" }
$ShouldRegister = (
    ($Command -ieq "install") -and
    (-not (Test-InstallerArg "--dry-run")) -and
    (-not $SkipMcpRegistration) -and
    (Test-OpenCodeRuntimeRequested)
)

if ($ShouldRegister) {
    if (-not (Test-Path $SeCli)) {
        Write-Warning "bootstrap: $SeCli not found; skipping MCP registration."
    } else {
        Write-Host "bootstrap: registering MCP servers with se install ..."
        & $VenvPython $SeCli install --project $RepoRoot
        $RegisterExitCode = $LASTEXITCODE
        if ($RegisterExitCode -ne 0) {
            Write-Warning "bootstrap: MCP registration failed (exit $RegisterExitCode); components are installed."
            Write-Warning "bootstrap: fix the issue and rerun: `"$VenvPython`" `"$SeCli`" install --project `"$RepoRoot`""
            exit $RegisterExitCode
        }
    }
}

exit 0