#!/usr/bin/env bash
# SE Installer — one-command bootstrap (Linux / macOS).
#
# Creates an isolated virtual environment under SE-INSTALLER/.venv, installs
# the se-installer package into it, and forwards every remaining argument to
# the `se-installer` CLI. This is the one-command entry point on POSIX hosts.
#
# Usage:
#   bash install.sh [<se-installer args>]
#
# Examples:
#   bash install.sh tui
#   bash install.sh install --recommended --dry-run
#   bash install.sh list --json
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "bootstrap: Python 3.10+ is required (set PYTHON=... if python3 is not on PATH)." >&2
    exit 1
fi

if [ ! -x "$VENV/bin/python" ]; then
    echo "bootstrap: creating virtual environment at $VENV ..."
    "$PYTHON" -m venv "$VENV"
fi

echo "bootstrap: installing se-installer into the venv ..."
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -e "$ROOT"

echo "bootstrap: running se-installer $*"
if [ -x "$VENV/bin/se-installer" ]; then
    exec "$VENV/bin/se-installer" "$@"
fi
exec "$VENV/bin/python" -m se_installer.cli "$@"