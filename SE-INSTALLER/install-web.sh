#!/usr/bin/env bash
# SE Installer Web - Launch interactive web-based installer (Linux/macOS)
#
# Installs dependencies if needed, finds a free port, starts the FastAPI server,
# opens the browser, and handles cleanup on exit.
#
# Usage:
#   ./install-web.sh [options]
#
# Options:
#   --port <n>       Port to use (0 = auto-find free port, default: 0)
#   --host <ip>      Host to bind (default: 127.0.0.1)
#   --no-browser     Don't open browser automatically
#   --dev            Development mode with auto-reload
#   --help           Show this help
#
# Examples:
#   ./install-web.sh
#   ./install-web.sh --port 8080
#   ./install-web.sh --dev --no-browser

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="${PYTHON:-python3}"

PORT=0
HOST="127.0.0.1"
NO_BROWSER=0
DEV=0
HELP=0

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --port) PORT="${2:-}"; shift ;;
        --host) HOST="${2:-}"; shift ;;
        --no-browser) NO_BROWSER=1 ;;
        --dev) DEV=1 ;;
        -h|--help) HELP=1 ;;
        *) echo "Opción desconocida: $1" >&2; exit 1 ;;
    esac
    shift
done

if [[ $HELP -eq 1 ]]; then
    cat <<EOF
SE Installer Web - Interactive web-based installer

Usage:
  ./install-web.sh [options]

Options:
  --port <n>       Port to use (0 = auto-find free port, default: 0)
  --host <ip>      Host to bind (default: 127.0.0.1)
  --no-browser     Don't open browser automatically
  --dev            Development mode with auto-reload
  --help           Show this help

Examples:
  ./install-web.sh
  ./install-web.sh --port 8080
  ./install-web.sh --dev --no-browser
EOF
    exit 0
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
NC='\033[0m' # No Color

log_info() { echo -e "${CYAN}$*${NC}"; }
log_ok() { echo -e "${GREEN}$*${NC}"; }
log_warn() { echo -e "${YELLOW}$*${NC}"; }
log_err() { echo -e "${RED}$*${NC}" >&2; }

# Check Python version
check_python() {
    if ! command -v "$PYTHON" >/dev/null 2>&1; then
        log_err "Python 3.10+ requerido (instala python3/python3-venv en Debian/Ubuntu, brew install python@3.12 en macOS)"
        return 1
    fi
    if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        log_err "$PYTHON es más antiguo que 3.10"
        return 1
    fi
    return 0
}

# Find free port
find_free_port() {
    local start_port="${1:-8765}"
    local max_attempts="${2:-20}"
    for ((p = start_port; p < start_port + max_attempts; p++)); do
        if ! ss -ltn | grep -q ":$p "; then
            echo "$p"
            return 0
        fi
    done
    log_err "No hay puerto libre en rango $start_port-$((start_port + max_attempts))"
    return 1
}

# Install dependencies
install_deps() {
    log_info "Instalando dependencias del instalador web..."
    local web_dir="$REPO_ROOT/SCRIPTS/se_installer_web"
    if [[ -f "$web_dir/pyproject.toml" ]]; then
        "$PYTHON" -m pip install -q -e "$web_dir"
        if [[ $? -ne 0 ]]; then
            log_err "Falló la instalación de dependencias"
            return 1
        fi
    fi
    return 0
}

# Start server
start_server() {
    local script_path="$REPO_ROOT/SCRIPTS/se_installer_web/se_installer_web/main.py"
    if [[ ! -f "$script_path" ]]; then
        log_err "No se encuentra main.py en $script_path"
        return 1
    fi

    local args=("$script_path" "--host" "$HOST" "--port" "$PORT")
    [[ $DEV -eq 1 ]] && args+=("--reload")

    log_info "Iniciando servidor en http://$HOST:$PORT ..."
    log_info "Presiona Ctrl+C para detener"
    echo

    if [[ $NO_BROWSER -eq 0 ]]; then
        sleep 0.5
        local url="http://$HOST:$PORT"
        log_ok "Abriendo navegador: $url"
        if command -v xdg-open >/dev/null 2>&1; then
            xdg-open "$url" >/dev/null 2>&1 &
        elif command -v open >/dev/null 2>&1; then
            open "$url" >/dev/null 2>&1 &
        else
            log_warn "No se pudo abrir navegador automáticamente. Abre manualmente: $url"
        fi
    fi

    # Run in foreground
    "$PYTHON" "${args[@]}"
    return $?
}

# Main
log_info "=== SE Installer Web ==="
log_info "Repo: $REPO_ROOT"

if ! check_python; then exit 1; fi

# Determine port
if [[ $PORT -eq 0 ]]; then
    PORT=$(find_free_port)
    log_info "Puerto auto-seleccionado: $PORT"
fi

# Install dependencies
if ! install_deps; then exit 1; fi

# Trap Ctrl+C
trap 'echo; log_info "Deteniendo servidor..."; exit 0' INT TERM

# Start server
start_server
exit $?