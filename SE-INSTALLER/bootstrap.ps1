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

function Update-ProcessPath {
    # A fresh install updates the machine/user PATH, but the current process keeps
    # the old copy. Merge the registry values and the usual tool directories back
    # in so post-install verification sees what was just installed.
    $entries = @()
    foreach ($value in @($env:PATH, [Environment]::GetEnvironmentVariable("Path", "Machine"), [Environment]::GetEnvironmentVariable("Path", "User"))) {
        if (-not $value) { continue }
        foreach ($part in ($value -split ';')) {
            $clean = [Environment]::ExpandEnvironmentVariables($part.Trim())
            if ($clean -and ($entries -notcontains $clean)) { $entries += $clean }
        }
    }
    $hints = @()
    if ($env:ProgramFiles) { $hints += Join-Path $env:ProgramFiles "nodejs" }
    if ($env:APPDATA) { $hints += Join-Path $env:APPDATA "npm" }
    if ($env:LOCALAPPDATA) {
        $hints += Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"
        $hints += Join-Path $env:LOCALAPPDATA "Programs\Python\Launcher"
        $hints += Join-Path $env:LOCALAPPDATA "Programs\Python\Python312"
    }
    $hints += "C:\ProgramData\chocolatey\bin"
    $hints += "C:\Python312"
    $hints += "C:\Program Files\Python312"
    if ($env:USERPROFILE) { $hints += Join-Path $env:USERPROFILE "scoop\shims" }
    foreach ($hint in $hints) {
        if ((Test-Path $hint) -and ($entries -notcontains $hint)) { $entries += $hint }
    }
    $env:PATH = ($entries -join ';')
}

function Add-PythonToPath {
    param([string] $Exe)
    if (-not $Exe) { return }
    $dir = Split-Path -Parent $Exe
    if (-not $dir) { return }
    $parts = $env:PATH -split ';'
    if ($parts -notcontains $dir) { $env:PATH = "$dir;$env:PATH" }
}

function Test-Python310 {
    param([string] $Exe)
    if (-not $Exe) { return $false }
    try {
        $ver = & $Exe -c "import sys; print('ok' if sys.version_info >= (3, 10) else 'old')"
        return (($LASTEXITCODE -eq 0) -and ("$ver" -eq "ok"))
    } catch {
        return $false
    }
}

function Find-PythonExe {
    # 1) `python` on PATH, if it is a real 3.10+ interpreter
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -and (Test-Python310 $cmd.Source)) { return $cmd.Source }

    # 2) the `py` launcher. Resolve the real executable, not the launcher
    #    itself, so venv creation is unambiguous.
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py -and $py.Source) {
        try {
            $ok = & $py.Source -3 -c "import sys; print('ok' if sys.version_info >= (3, 10) else 'old')"
            if ($LASTEXITCODE -eq 0 -and "$ok" -eq "ok") {
                $candidate = & $py.Source -3 -c "import sys; print(sys.executable)"
                if ($LASTEXITCODE -eq 0 -and $candidate) { return "$candidate".Trim() }
            }
        } catch { }
    }
    return $null
}

function Install-PythonExe {
    Write-Host "bootstrap: Python 3.10+ not found; attempting to install Python 3.12 ..."
    $attempted = $false
    $installed = $false

    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget -and $winget.Source) {
        $attempted = $true
        Write-Host "bootstrap: installing Python with winget ..."
        & $winget.Source install --id Python.Python.3.12 --exact --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -eq 0) { $installed = $true }
    }

    if (-not $installed) {
        $choco = Get-Command choco -ErrorAction SilentlyContinue
        if ($choco -and $choco.Source) {
            $attempted = $true
            Write-Host "bootstrap: installing Python with Chocolatey ..."
            & $choco.Source install python --yes --no-progress
            if ($LASTEXITCODE -eq 0) { $installed = $true }
        }
    }

    if (-not $installed) {
        $scoop = Get-Command scoop -ErrorAction SilentlyContinue
        if ($scoop -and $scoop.Source) {
            $attempted = $true
            Write-Host "bootstrap: installing Python with Scoop ..."
            & $scoop.Source install python
            if ($LASTEXITCODE -eq 0) { $installed = $true }
        }
    }

    if (-not $attempted) { return $null }
    Update-ProcessPath
    $found = Find-PythonExe
    Add-PythonToPath $found
    return $found
}

Update-ProcessPath
$DryRun = Test-InstallerArg "--dry-run"
$PythonExe = Find-PythonExe
Add-PythonToPath $PythonExe
if (-not $PythonExe -and -not $DryRun) {
    $PythonExe = Install-PythonExe
}
if (-not $PythonExe) {
    Write-Host "bootstrap: Python 3.10+ is required but was not found on PATH." -ForegroundColor Red
    if ($DryRun) {
        Write-Host "bootstrap: --dry-run does not install prerequisites; install Python and rerun."
    } else {
        Write-Host "bootstrap: no supported package manager was able to install it."
    }
    Write-Host "bootstrap: install Python 3.10+ with one of:"
    Write-Host "  winget install --id Python.Python.3.12 -e"
    Write-Host "  choco install python -y"
    Write-Host "  scoop install python"
    Write-Host "bootstrap: then open a new terminal and rerun this command."
    exit 1
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
# Node/OpenCode may have been installed by this run. Refresh before the MCP
# registration child process probes npx/opencode.
Update-ProcessPath
if ($InstallerExitCode -ne 0) { exit $InstallerExitCode }

$Command = if ($ForwardArgs.Count -gt 0) { $ForwardArgs[0] } else { "" }
# A custom `-c/--components` selection may not include every SE MCP server, so
# registering all of them would leave broken entries. Default/recommended and
# --all installs do include the full set.
$HasExplicitComponents = (
    (Test-InstallerArg "--components") -or
    (Test-InstallerArg "-c") -or
    (@($InstallerArgs | Where-Object { $_ -match '^--components=' }).Count -gt 0)
)
$ShouldRegister = (
    ($Command -ieq "install") -and
    (-not (Test-InstallerArg "--dry-run")) -and
    (-not $SkipMcpRegistration) -and
    (-not $HasExplicitComponents) -and
    (Test-OpenCodeRuntimeRequested)
)

if ($ShouldRegister) {
    # `se install` skips servers whose launcher is missing. Say so explicitly
    # instead of letting the user believe every MCP was registered.
    if (-not (Get-Command npx -ErrorAction SilentlyContinue)) {
        Write-Warning "bootstrap: npx is not available in this process; context7/filesystem will be skipped."
        Write-Warning "bootstrap: open a new terminal and rerun: `"$VenvPython`" `"$SeCli`" install --project `"$RepoRoot`""
    }
    if (-not (Get-Command opencode -ErrorAction SilentlyContinue)) {
        Write-Warning "bootstrap: opencode is not available in this process; the MCP config is still written, but open a new terminal before launching it."
    }

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

if (($Command -ieq "install") -and (-not $DryRun) -and (-not $HasExplicitComponents) -and (Test-OpenCodeRuntimeRequested)) {
    Write-Host ""
    Write-Host "bootstrap: next steps"
    Write-Host "  1. Authenticate OpenCode if it has no provider yet: opencode auth login"
    Write-Host "  2. Start OpenCode from this repository: opencode"
}

if ($Command -ieq "tui") {
    Write-Host ""
    Write-Host "bootstrap: after a TUI install, register the MCP servers once:"
    Write-Host "  `"$VenvPython`" `"$SeCli`" install --project `"$RepoRoot`""
    Write-Host "bootstrap: then authenticate OpenCode: opencode auth login"
}

exit 0
