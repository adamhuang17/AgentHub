@echo off
chcp 65001 >nul 2>&1
title AgentHub - Stop All Services

setlocal EnableDelayedExpansion

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

echo ============================================
echo   AgentHub - Stopping All Services
echo ============================================
echo.

:: ========== 1. Kill by port (most reliable) ==========
echo [1/4] Killing processes on ports 8000, 4096, 3000 ...
for %%p in (8000 4096 3000) do (
    set "FOUND=0"
    for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%%p " ^| findstr "LISTENING" 2^>nul') do (
        set "FOUND=1"
        echo   Killing PID %%a on port %%p ...
        taskkill /F /PID %%a >nul 2>&1
    )
    if "!FOUND!"=="0" echo   Port %%p - no listener found.
)

:: ========== 2. Kill window titles ==========
echo.
echo [2/4] Closing AgentHub terminal windows ...
taskkill /FI "WINDOWTITLE eq AgentHub-API*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq AgentHub-Runtime*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq AgentHub-Web*" /F >nul 2>&1
echo   Done.

:: ========== 3. Kill python processes running main.py ==========
echo.
echo [3/4] Stopping Python API processes ...
set "PY_COUNT=0"
for /f "tokens=2" %%a in ('wmic process where "commandline like '%%services.api.app.main%%' and name='python.exe'" get processid /format:list 2^>nul ^| findstr "ProcessId"') do (
    for /f "tokens=2 delims==" %%b in ("%%a") do (
        set /a PY_COUNT+=1
        echo   Killing python PID %%b ...
        taskkill /F /PID %%b >nul 2>&1
    )
)
:: Fallback: use tasklist + wmic for broader match
for /f "tokens=2 delims=," %%a in ('wmic process where "name='python.exe'" get processid^,commandline /format:csv 2^>nul ^| findstr "services.api.app.main"') do (
    taskkill /F /PID %%a >nul 2>&1 2>nul
)
if "!PY_COUNT!"=="0" echo   No Python API processes found.

:: ========== 4. Kill bun/node processes under project ==========
echo.
echo [4/4] Stopping Bun/Node processes related to AgentHub ...
set "BUN_NODE_COUNT=0"
:: Kill bun processes that have opencode or app in command line
for /f "tokens=2 delims=," %%a in ('wmic process where "name='bun.exe'" get processid^,commandline /format:csv 2^>nul ^| findstr /i "opencode\|packages\\app"') do (
    set /a BUN_NODE_COUNT+=1
    echo   Killing bun PID %%a ...
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=2 delims=," %%a in ('wmic process where "name='node.exe'" get processid^,commandline /format:csv 2^>nul ^| findstr /i "opencode\|packages\\app\|vite"') do (
    set /a BUN_NODE_COUNT+=1
    echo   Killing node PID %%a ...
    taskkill /F /PID %%a >nul 2>&1
)
if "!BUN_NODE_COUNT!"=="0" echo   No matching Bun/Node processes found.

:: ========== Verify ==========
echo.
echo [INFO] Verifying all ports are free ...
set "REMAIN=0"
for %%p in (8000 4096 3000) do (
    netstat -aon | findstr ":%%p " | findstr "LISTENING" >nul 2>&1
    if not errorlevel 1 (
        echo   [WARN] Port %%p is still in use!
        set "REMAIN=1"
    ) else (
        echo   [OK]   Port %%p is free.
    )
)

echo.
if "!REMAIN!"=="0" (
    echo [SUCCESS] All AgentHub services stopped successfully.
) else (
    echo [WARN] Some ports are still in use. You may need to close them manually.
    echo        Run: netstat -aon ^| findstr ":8000 :4096 :3000"
)

echo.
pause
endlocal
