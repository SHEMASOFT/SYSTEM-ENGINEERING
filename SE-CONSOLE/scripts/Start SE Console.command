#!/bin/sh
# SE-CONSOLE :: double-click (macOS) to start the console in the background.
# Delegates to dev_console.py -- no service, no privileges needed.
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then PY=python3; else PY=python; fi
"$PY" dev_console.py start || {
  echo
  echo SE-CONSOLE did not start ^(see the messages above^).
  echo Press Return to close.
  read -r _
  exit 1
}
open "http://127.0.0.1:8777" 2>/dev/null || true
echo
echo SE-CONSOLE is running: http://127.0.0.1:8777
sleep 2
