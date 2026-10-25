#!/usr/bin/env bash
# SE Installer - Uninstall/Purge System Engineering artifacts from OpenCode
# Linux/macOS equivalent of uninstall.ps1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PY="$SCRIPT_DIR/.venv/bin/python"

# Resolve Python interpreter
if [[ ! -x "$VENV_PY" ]]; then
    echo "bootstrap: SE-INSTALLER venv not found at $VENV_PY. Falling back to 'python3' in PATH." >&2
    PY="python3"
else
    PY="$VENV_PY"
fi

# Arguments are forwarded verbatim to `se uninstall`, so this wrapper never
# re-implements the purge logic and cannot drift from it.

SE_CLI="$REPO_ROOT/SCRIPTS/se.py"
if [[ ! -f "$SE_CLI" ]]; then
    echo "bootstrap: $SE_CLI not found; run this wrapper from the SYSTEM-ENGINEERING clone." >&2
    exit 1
fi

# No flags means interactive: the CLI decides what to show and offers the plan.
if [[ $# -eq 0 ]]; then
    set -- --interactive
fi

# Only supply the project when the caller did not: an explicit --project wins.
ARGS=("uninstall")
for arg in "$@"; do
    if [[ "$arg" == "--project" || "$arg" == --project=* ]]; then
        PROJECT_GIVEN=1
        break
    fi
done
if [[ "${PROJECT_GIVEN:-0}" -eq 0 ]]; then
    ARGS+=("--project" "$REPO_ROOT")
fi
ARGS+=("$@")

echo "=== SE OpenCode Uninstall/Purge ==="
echo "Repo: $REPO_ROOT"
echo "Running: $PY $SE_CLI ${ARGS[*]}"
echo ""

cd "$REPO_ROOT"
"$PY" "$SE_CLI" "${ARGS[@]}"