<#Requires -Version 5.1
<#
.SYNOPSIS
    SE Installer - uninstall SE artifacts from OpenCode (Windows wrapper).

.DESCRIPTION
    Thin wrapper over `se uninstall`. It forwards every argument verbatim to the
    reference CLI, so the wrapper never re-implements the purge logic and cannot
    drift from it. No flags means interactive mode, which lets you pick which
    items to remove and shows what each one does.

.EXAMPLE
    .\uninstall.ps1
    Interactive: select individual items or everything, with a plan preview.

.EXAMPLE
    .\uninstall.ps1 --all --apply
    Remove every detected SE artifact, including SE MCP servers.

.EXAMPLE
    .\uninstall.ps1 --include-untracked-se-mcps --remove-opencode-dir --dry-run
    Preview the plan without writing anything (dry-run is the CLI default).

.EXAMPLE
    .\uninstall.ps1 --help
    Full flag reference.

.NOTES
    Runs from the repository root and prefers the SE-INSTALLER venv interpreter.
#>
[CmdletBinding()]
param(
    # Forwarded verbatim to `se uninstall`; without this catch-all PowerShell
    # rejects positional arguments such as `--all`.
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $UninstallArgs
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$VenvPy = Join-Path $ScriptDir ".venv\Scripts\python.exe"

if (Test-Path $VenvPy) {
    $Py = $VenvPy
} else {
    Write-Warning "bootstrap: SE-INSTALLER venv not found at $VenvPy; falling back to 'python' in PATH."
    $Py = "python"
}

$SeCli = Join-Path $RepoRoot "SCRIPTS\se.py"
if (-not (Test-Path $SeCli)) {
    Write-Error "bootstrap: $SeCli not found; run this wrapper from the SYSTEM-ENGINEERING clone."
    exit 1
}

# No flags means interactive: the CLI decides what to show and offers the plan.
if (-not $UninstallArgs -or $UninstallArgs.Count -eq 0) {
    $UninstallArgs = @("--interactive")
}

# Only supply the project when the caller did not: an explicit --project wins.
$CliArgs = @("uninstall")
if (-not ($UninstallArgs | Where-Object { $_ -eq "--project" -or $_ -like "--project=*" })) {
    $CliArgs += @("--project", $RepoRoot)
}
$CliArgs += $UninstallArgs

Write-Host "bootstrap: se $($CliArgs -join ' ')"
Push-Location $RepoRoot
try {
    & $Py $SeCli @CliArgs
} finally {
    Pop-Location
}

exit $LASTEXITCODE
