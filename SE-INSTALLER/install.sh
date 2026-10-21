#!/usr/bin/env bash
# SE Installer — one-command bootstrap (Linux / macOS).
#
# Creates an isolated virtual environment under SE-INSTALLER/.venv, installs
# the se-installer package into it, and forwards every remaining argument to
# the `se-installer` CLI. This is the one-command entry point on POSIX hosts.
#
# After a successful `install` (and unless --dry-run is used), it also runs the
# repository's `se install` to register the SE MCP servers for OpenCode. Pass
# --skip-mcp-registration to opt out, for example when installing only another
# runtime.
#
# Usage:
#   bash install.sh [<se-installer args>]
#
# Examples:
#   bash install.sh tui
#   bash install.sh install --recommended --dry-run
#   bash install.sh install --recommended --skip-mcp-registration
#   bash install.sh list --json
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$ROOT/.." && pwd)"
VENV="$ROOT/.venv"
PYTHON="${PYTHON:-python3}"

# `--skip-mcp-registration` is a bootstrap-only switch: se-installer does not
# know it, so strip it before forwarding and remember the intent.
ARGS=()
SKIP_MCP_REGISTRATION=0
for arg in "$@"; do
    if [ "$arg" = "--skip-mcp-registration" ]; then
        SKIP_MCP_REGISTRATION=1
    else
        ARGS+=("$arg")
    fi
done

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

echo "bootstrap: running se-installer ${ARGS[*]:-}"
if [ -x "$VENV/bin/se-installer" ]; then
    if "$VENV/bin/se-installer" ${ARGS[@]+"${ARGS[@]}"}; then
        status=0
    else
        status=$?
    fi
else
    if "$VENV/bin/python" -m se_installer.cli ${ARGS[@]+"${ARGS[@]}"}; then
        status=0
    else
        status=$?
    fi
fi

if [ "$status" -ne 0 ]; then
    exit "$status"
fi

# Auto-register the SE MCP servers after a successful install (never on a
# dry-run, and never when the operator opted out or asked for another runtime).
want_register=1
if [ "$SKIP_MCP_REGISTRATION" -eq 1 ]; then
    want_register=0
fi
if [ "${ARGS[0]:-}" != "install" ]; then
    want_register=0
fi
for arg in ${ARGS[@]+"${ARGS[@]}"}; do
    if [ "$arg" = "--dry-run" ]; then
        want_register=0
    fi
done

opencode_requested=1
if [ "$want_register" -eq 1 ]; then
    i=0
    while [ "$i" -lt "${#ARGS[@]}" ]; do
        case "${ARGS[$i]}" in
            --runtimes)
                opencode_requested=0
                j=$((i + 1))
                while [ "$j" -lt "${#ARGS[@]}" ]; do
                    case "${ARGS[$j]}" in
                        -*) break ;;
                    esac
                    if [ "${ARGS[$j]}" = "opencode" ]; then
                        opencode_requested=1
                    fi
                    j=$((j + 1))
                done
                i=$j
                ;;
            --runtimes=*)
                opencode_requested=0
                case ",${ARGS[$i]#--runtimes=}," in
                    *,opencode,*) opencode_requested=1 ;;
                esac
                ;;
        esac
        i=$((i + 1))
    done
fi

if [ "$want_register" -eq 1 ] && [ "$opencode_requested" -eq 1 ]; then
    if [ -f "$REPO/SCRIPTS/se.py" ]; then
        echo "bootstrap: registering MCP servers with se install ..."
        if "$VENV/bin/python" "$REPO/SCRIPTS/se.py" install --project "$REPO"; then
            :
        else
            status=$?
            echo "bootstrap: MCP registration failed (exit $status); components are installed." >&2
            echo "bootstrap: fix the issue and rerun: \"$VENV/bin/python\" \"$REPO/SCRIPTS/se.py\" install --project \"$REPO\"" >&2
            exit "$status"
        fi
    else
        echo "bootstrap: $REPO/SCRIPTS/se.py not found; skipping MCP registration." >&2
    fi
fi

exit 0
