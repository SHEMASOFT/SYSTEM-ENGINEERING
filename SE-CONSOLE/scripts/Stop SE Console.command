#!/bin/sh
# SE-CONSOLE :: double-click (macOS) to stop the console started by this tool.
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then PY=python3; else PY=python; fi
"$PY" dev_console.py stop || {
  echo
  echo Press Return to close.
  read -r _
  exit 1
}
sleep 1
