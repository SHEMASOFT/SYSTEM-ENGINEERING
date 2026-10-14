@echo off
rem SE-CONSOLE :: double-click to stop the console started by this tool.
rem Kept free of parentheses, labels and multi-line blocks so it runs under the
rem repository's LF-only line endings (see .gitattributes).
setlocal
set "HERE=%~dp0"
set "PY=python"
where py >nul 2>nul && set "PY=py -3"
%PY% "%HERE%dev_console.py" stop %*
if errorlevel 1 pause
if errorlevel 1 exit /b 1
rem Short pause so a double-clicked window can be read. `ping`, not `timeout`:
rem timeout aborts when stdin is redirected (scripted launches).
ping -n 2 127.0.0.1 >nul 2>&1
exit /b 0
