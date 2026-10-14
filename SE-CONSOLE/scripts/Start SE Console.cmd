@echo off
rem SE-CONSOLE :: double-click to start the console in the background.
rem Delegates to dev_console.py -- no service, no privileges needed.
rem Kept free of parentheses, labels and multi-line blocks so it runs under the
rem repository's LF-only line endings (see .gitattributes).
setlocal
set "HERE=%~dp0"
set "PY=python"
where py >nul 2>nul && set "PY=py -3"
%PY% "%HERE%dev_console.py" start %*
if errorlevel 1 echo.
if errorlevel 1 echo SE-CONSOLE did not start. See the messages above.
if errorlevel 1 pause
if errorlevel 1 exit /b 1
start "" "http://127.0.0.1:8777"
echo.
echo SE-CONSOLE is running: http://127.0.0.1:8777
rem Short pause so a double-clicked window can be read. `ping`, not `timeout`:
rem timeout aborts when stdin is redirected (scripted launches).
ping -n 3 127.0.0.1 >nul 2>&1
exit /b 0
