#!/usr/bin/env bash
# SE Installer — one-command bootstrap (Linux / macOS).
#
# Creates an isolated virtual environment under SE-INSTALLER/.venv, installs
# the se-installer package into it, and forwards every remaining argument to
# the `se-installer` CLI. This is the one-command entry point on POSIX hosts.
#
# After a successful `install` (and unless --dry-run is used), it also runs the
# repository's `se install` to register the SE MCP servers for OpenCode. The TUI
# performs the same registration for the selected MCPs. Pass
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

# `--skip-mcp-registration` is a bootstrap-only switch for `install`: strip it
# before forwarding and remember the intent. The TUI accepts it directly as an
# opt-out, so add it back to the TUI invocation below.
ARGS=()
SKIP_MCP_REGISTRATION=0
DRY_RUN=0
CUSTOM_COMPONENTS=0
for arg in "$@"; do
    if [ "$arg" = "--skip-mcp-registration" ]; then
        SKIP_MCP_REGISTRATION=1
    else
        if [ "$arg" = "--dry-run" ]; then
            DRY_RUN=1
        fi
        ARGS+=("$arg")
    fi
done

RUN_ARGS=()
RUN_ARGS+=(${ARGS[@]+"${ARGS[@]}"})
if [ "${ARGS[0]:-}" = "tui" ] && [ "$SKIP_MCP_REGISTRATION" -eq 1 ]; then
    RUN_ARGS+=("--skip-mcp-registration")
fi

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "bootstrap: Python 3.10+ is required (set PYTHON=... if python3 is not on PATH)." >&2
    echo "bootstrap: Debian/Ubuntu: sudo apt install python3 python3-venv" >&2
    echo "bootstrap: macOS: brew install python@3.12" >&2
    exit 1
fi
if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    echo "bootstrap: $PYTHON is older than 3.10; set PYTHON=... to a 3.10+ interpreter." >&2
    exit 1
fi

if [ ! -x "$VENV/bin/python" ]; then
    echo "bootstrap: creating virtual environment at $VENV ..."
    "$PYTHON" -m venv "$VENV"
fi

echo "bootstrap: installing se-installer into the venv ..."
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -e "$ROOT"

echo "bootstrap: running se-installer ${RUN_ARGS[*]:-}"
if [ -x "$VENV/bin/se-installer" ]; then
    if "$VENV/bin/se-installer" ${RUN_ARGS[@]+"${RUN_ARGS[@]}"}; then
        status=0
    else
        status=$?
    fi
else
    if "$VENV/bin/python" -m se_installer.cli ${RUN_ARGS[@]+"${RUN_ARGS[@]}"}; then
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
    case "$arg" in
        --dry-run)
            want_register=0
            ;;
        --components|-c|--components=*)
            # A custom component selection may not include every SE MCP server.
            want_register=0
            CUSTOM_COMPONENTS=1
            ;;
    esac
done

opencode_requested=1
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

if [ "${ARGS[0]:-}" = "install" ] && [ "$opencode_requested" -eq 1 ] && [ "$DRY_RUN" -eq 0 ] && [ "$CUSTOM_COMPONENTS" -eq 0 ]; then
    echo "bootstrap: next steps"
    echo "  1. Authenticate OpenCode if it has no provider yet: opencode auth login"
    echo "  2. Start OpenCode from this repository: opencode"
fi

if [ "${ARGS[0]:-}" = "tui" ]; then
    echo "bootstrap: TUI finished; selected MCPs are registered automatically after a successful install."
    echo "bootstrap: if OpenCode was installed, authenticate it: opencode auth login"
fi

# Offer to run uninstaller/purge for OpenCode SE artifacts
if [ "${ARGS[0]:-}" = "install" ] && [ "$opencode_requested" -eq 1 ] && [ "$DRY_RUN" -eq 0 ] && [ "$CUSTOM_COMPONENTS" -eq 0 ]; then
    echo ""
    echo "bootstrap: ¿Deseas limpiar artefactos de System Engineering de OpenCode?"
    echo "  (agentes/comandos/skills generados + MCPs SE como se-memory-server, se-skill-server)"
    echo "  Opciones: [s] Sí, interactivo  [n] No  [t] Solo ver plan (dry-run)"
    read -r -p "  > " choice
    case "$choice" in
        s|S|y|Y)
            echo "bootstrap: ejecutando desinstalación interactiva..."
            "$VENV/bin/python" -m se_installer.cli uninstall -i
            ;;
        t|T)
            echo "bootstrap: mostrando plan de desinstalación (dry-run)..."
            "$VENV/bin/python" -m se_installer.cli uninstall --all --dry-run
            ;;
        *)
            echo "bootstrap: omitiendo desinstalación."
            ;;
    esac
fi

exit 0
