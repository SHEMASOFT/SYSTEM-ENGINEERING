<#
.SYNOPSIS
    SE Installer Web - Launch interactive web-based installer.
.DESCRIPTION
    Installs dependencies if needed, finds a free port, starts the FastAPI server,
    opens the browser, and handles cleanup on exit.
.EXAMPLE
    .\install-web.ps1                    # Auto port, open browser
    .\install-web.ps1 --port 8080       # Specific port
    .\install-web.ps1 --no-browser      # Don't open browser
    .\install-web.ps1 --help            # Show help
.NOTES
    Requires Python 3.10+ and the SE repository.
#>

param(
    [int]$Port = 0,              # 0 = auto-find free port
    [switch]$NoBrowser,
    [switch]$Help,
    [switch]$Dev,                # Dev mode with --reload
    [string]$Host = "127.0.0.1"
)

if ($Help) {
    @"
SE Installer Web - Interactive web-based installer

Usage:
  .\install-web.ps1 [options]

Options:
  --port <n>       Port to use (0 = auto-find free port, default: 0)
  --host <ip>      Host to bind (default: 127.0.0.1)
  --no-browser     Don't open browser automatically
  --dev            Development mode with auto-reload
  --help           Show this help

Examples:
  .\install-web.ps1
  .\install-web.ps1 --port 8080
  .\install-web.ps1 --dev --no-browser
"@
    exit 0
}

# -------- Helpers --------
function Find-FreePort {
    param([int]$StartPort = 8765, [int]$MaxAttempts = 20)
    for ($p = $StartPort; $p -lt $StartPort + $MaxAttempts; $p++) {
        $listener = $null
        try {
            $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $p)
            $listener.Start()
            $listener.Stop()
            return $p
        } catch {
            if ($listener) { $listener.Stop() }
        }
    }
    throw "No free port found in range $StartPort-$($StartPort + $MaxAttempts)"
}

function Test-PythonVersion {
    $py = "python"
    if (-not (Get-Command $py -ErrorAction SilentlyContinue)) {
        Write-Error "Python no encontrado en PATH. Instala Python 3.10+ (winget install Python.Python.3.12)"
        return $false
    }
    $version = & $py -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    $parts = $version.Split('.')
    if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 10)) {
        Write-Error "Python 3.10+ requerido. Versión actual: $version"
        return $false
    }
    return $true
}

function Install-Dependencies {
    param($RepoRoot)
    Write-Host "Instalando dependencias del instalador web..." -ForegroundColor Cyan
    $py = "python"
    $webDir = Join-Path $RepoRoot "SCRIPTS\se_installer_web"
    if (Test-Path (Join-Path $webDir "pyproject.toml")) {
        & $py -m pip install -q -e $webDir
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Falló la instalación de dependencias"
            return $false
        }
    }
    return $true
}

function Start-Server {
    param($RepoRoot, $Host, $Port, $Dev, $NoBrowser)

    $py = "python"
    $scriptPath = Join-Path $RepoRoot "SCRIPTS\se_installer_web\se_installer_web\main.py"

    if (-not (Test-Path $scriptPath)) {
        Write-Error "No se encuentra main.py en $scriptPath"
        return $false
    }

    $args = @($scriptPath, "--host", $Host, "--port", $Port)
    if ($Dev) { $args += "--reload" }

    Write-Host "Iniciando servidor en http://$Host:$Port ..." -ForegroundColor Cyan
    Write-Host "Presiona Ctrl+C para detener" -ForegroundColor Gray

    if (-not $NoBrowser) {
        Start-Sleep -Milliseconds 500
        $url = "http://$Host:$Port"
        Write-Host "Abriendo navegador: $url" -ForegroundColor Green
        try { Start-Process $url } catch { Write-Warning "No se pudo abrir navegador automáticamente. Abre manualmente: $url" }
    }

    # Run in foreground so Ctrl+C works
    & $py @args
    return $LASTEXITCODE -eq 0
}

# -------- Main --------
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot = Join-Path $RepoRoot ".."
$RepoRoot = Resolve-Path $RepoRoot

Write-Host "=== SE Installer Web ===" -ForegroundColor Cyan
Write-Host "Repo: $RepoRoot"

if (-not (Test-PythonVersion)) { exit 1 }

# Determine port
if ($Port -eq 0) {
    $Port = Find-FreePort
    Write-Host "Puerto auto-seleccionado: $Port" -ForegroundColor Gray
}

# Install dependencies
if (-not (Install-Dependencies $RepoRoot)) { exit 1 }

# Start server
$success = Start-Server -RepoRoot $RepoRoot -Host $Host -Port $Port -Dev $Dev -NoBrowser $NoBrowser
exit $LASTEXITCODE