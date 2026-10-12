#Requires -Version 5.1
<#
.SYNOPSIS
    SE Installer — one-command bootstrap (Windows).

.DESCRIPTION
    Creates an isolated virtual environment under SE-INSTALLER\.venv, installs
    the se-installer package into it, and forwards every remaining argument to
    the `se-installer` CLI. This is the one-command entry point for Windows.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File bootstrap.ps1 tui

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File bootstrap.ps1 install --recommended --dry-run

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File bootstrap.ps1 list --json
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$InstallerRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$VenvDir       = Join-Path $InstallerRoot ".venv"
$VenvPython    = Join-Path $VenvDir "Scripts\python.exe"
$InstallerExe  = Join-Path $VenvDir "Scripts\se-installer.exe"

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
    & $InstallerExe @args
} else {
    & $VenvPython -m se_installer.cli @args
}
exit $LASTEXITCODE