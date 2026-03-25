@echo off
chcp 65001 >nul 2>&1

set KOBITO_PORT=8300
if defined KOBITO_PORT set PORT=%KOBITO_PORT%
if not defined PORT set PORT=8300

REM Check if server is already running
netstat -ano | findstr "LISTENING" | findstr ":%PORT% " >nul 2>&1
if not errorlevel 1 (
    echo Server already running on port %PORT%
    start http://localhost:%PORT%
    exit /b
)

REM Start server in background
echo Starting server on port %PORT%...
start "kobito_agent server" python "%~dp0project\agent_manager\run.py"

REM Wait for server to be ready (max 30 seconds)
set count=0

:wait
ping -n 2 127.0.0.1 >nul 2>&1
curl -s --connect-timeout 1 http://localhost:%PORT%/api/agents >nul 2>&1
if not errorlevel 1 goto ready
set /a count=count+1
if %count% GEQ 30 (
    echo Error: Server startup timed out
    exit /b 1
)
goto wait

:ready
echo Server ready
start http://localhost:%PORT%
