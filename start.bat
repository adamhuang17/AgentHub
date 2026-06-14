@echo off
chcp 65001 >nul 2>&1
title AgentHub - Start All Services

setlocal EnableDelayedExpansion

:: ========== Project Root ==========
set "ROOT=%~dp0"
:: Remove trailing backslash
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

cd /d "%ROOT%"

:: ========== Load .env ==========
if exist ".env" (
    echo [INFO] Loading .env ...
    for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
        set "line=%%a"
        if not "!line:~0,1!"=="#" (
            if not "%%a"=="" (
                set "%%a=%%b"
            )
        )
    )
) else (
    echo [WARN] .env file not found, using defaults.
)

:: ========== Defaults ==========
if not defined PORT set "PORT=8000"
if not defined HOST set "HOST=127.0.0.1"
if not defined AGENTHUB_DB_PATH set "AGENTHUB_DB_PATH=var/agenthub.sqlite3"
if not defined AGENTHUB_ARTIFACT_STORE_DIR set "AGENTHUB_ARTIFACT_STORE_DIR=var/artifacts"
if not defined AGENTHUB_STATIC_DEPLOY_DIR set "AGENTHUB_STATIC_DEPLOY_DIR=var/static-deployments"
if not defined VITE_AGENTHUB_API_BASE (
    if defined AGENTHUB_API_BASE_URL (
        set "VITE_AGENTHUB_API_BASE=%AGENTHUB_API_BASE_URL%"
    ) else (
        set "VITE_AGENTHUB_API_BASE=http://127.0.0.1:%PORT%"
    )
)

:: ========== Ensure var directories ==========
if not exist "var" mkdir "var"
if not exist "var\artifacts" mkdir "var\artifacts"
if not exist "var\static-deployments" mkdir "var\static-deployments"

:: ========== Prerequisite Checks ==========
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] python not found in PATH. Please install Python 3.11+.
    pause
    exit /b 1
)

where bun >nul 2>&1
if errorlevel 1 (
    echo [ERROR] bun not found in PATH. Please install Bun.
    pause
    exit /b 1
)

if not exist "services\api\app\main.py" (
    echo [ERROR] Backend missing: services\api\app\main.py
    pause
    exit /b 1
)

if not exist "apps\web\packages\opencode\package.json" (
    echo [ERROR] Agent runtime missing: apps\web\packages\opencode\package.json
    pause
    exit /b 1
)

:: ========== Kill stale processes on target ports ==========
echo [INFO] Checking for stale processes on ports %PORT%, 4096, 3000 ...
for %%p in (%PORT% 4096 3000) do (
    for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%%p " ^| findstr "LISTENING" 2^>nul') do (
        echo [INFO] Killing stale PID %%a on port %%p ...
        taskkill /F /PID %%a >nul 2>&1
    )
)

:: ========== Start API Backend (Python) ==========
echo [INFO] Starting AgentHub API on http://%HOST%:%PORT% ...
start "AgentHub-API" cmd /c "cd /d "%ROOT%" && set PORT=%PORT%&& set HOST=%HOST%&& set AGENTHUB_DB_PATH=%AGENTHUB_DB_PATH%&& set AGENTHUB_ARTIFACT_STORE_DIR=%AGENTHUB_ARTIFACT_STORE_DIR%&& set AGENTHUB_STATIC_DEPLOY_DIR=%AGENTHUB_STATIC_DEPLOY_DIR%&& set AGENTHUB_ENV=%AGENTHUB_ENV%&& set AGENTHUB_PUBLIC_BASE_URL=%AGENTHUB_PUBLIC_BASE_URL%&& set AGENTHUB_API_BASE_URL=%AGENTHUB_API_BASE_URL%&& set AGENTHUB_WEB_BASE_URL=%AGENTHUB_WEB_BASE_URL%&& set OPENCODE_API_BASE=%OPENCODE_API_BASE%&& set AGENTHUB_TURN_ROUTER_BACKEND=%AGENTHUB_TURN_ROUTER_BACKEND%&& set AGENTHUB_TURN_ROUTER_BASE_URL=%AGENTHUB_TURN_ROUTER_BASE_URL%&& set AGENTHUB_TURN_ROUTER_API_KEY=%AGENTHUB_TURN_ROUTER_API_KEY%&& set AGENTHUB_TURN_ROUTER_MODEL=%AGENTHUB_TURN_ROUTER_MODEL%&& set AGENTHUB_MODEL_PROVIDER=%AGENTHUB_MODEL_PROVIDER%&& set AGENTHUB_CUSTOM_OPENAI_API_BASE=%AGENTHUB_CUSTOM_OPENAI_API_BASE%&& set AGENTHUB_CUSTOM_OPENAI_API_KEY=%AGENTHUB_CUSTOM_OPENAI_API_KEY%&& set AGENTHUB_CUSTOM_OPENAI_MODEL=%AGENTHUB_CUSTOM_OPENAI_MODEL%&& set AGENTHUB_CODEX_EXECUTABLE=%AGENTHUB_CODEX_EXECUTABLE%&& set AGENTHUB_CODEX_TIMEOUT_SECONDS=%AGENTHUB_CODEX_TIMEOUT_SECONDS%&& set AGENTHUB_CODEX_IGNORE_USER_CONFIG=%AGENTHUB_CODEX_IGNORE_USER_CONFIG%&& set AGENTHUB_CODEX_DISABLE_FEATURES=%AGENTHUB_CODEX_DISABLE_FEATURES%&& set AGENTHUB_ENABLE_CLAUDE_CODE_REAL_CLI=%AGENTHUB_ENABLE_CLAUDE_CODE_REAL_CLI%&& set CLAUDE_CODE_GIT_BASH_PATH=%CLAUDE_CODE_GIT_BASH_PATH%&& set AGENTHUB_ANTHROPIC_TIMEOUT_SECONDS=%AGENTHUB_ANTHROPIC_TIMEOUT_SECONDS%&& set AGENTHUB_CLAUDE_ANTHROPIC_BASE_URL=%AGENTHUB_CLAUDE_ANTHROPIC_BASE_URL%&& set AGENTHUB_CLAUDE_ANTHROPIC_AUTH_TOKEN=%AGENTHUB_CLAUDE_ANTHROPIC_AUTH_TOKEN%&& set AGENTHUB_CLAUDE_DEFAULT_OPUS_MODEL=%AGENTHUB_CLAUDE_DEFAULT_OPUS_MODEL%&& set AGENTHUB_CLAUDE_DEFAULT_SONNET_MODEL=%AGENTHUB_CLAUDE_DEFAULT_SONNET_MODEL%&& set AGENTHUB_CLAUDE_DEFAULT_HAIKU_MODEL=%AGENTHUB_CLAUDE_DEFAULT_HAIKU_MODEL%&& python -B -m services.api.app.main"

:: ========== Start Agent Runtime (Bun) ==========
echo [INFO] Starting Agent Runtime on http://127.0.0.1:4096 ...
start "AgentHub-Runtime" cmd /c "cd /d "%ROOT%\apps\web" && bun run --cwd packages/opencode --conditions=browser src/index.ts serve --hostname 127.0.0.1 --port 4096 --cors http://127.0.0.1:3000 --cors http://localhost:3000"

:: ========== Start Web Frontend (Bun/Vite) ==========
echo [INFO] Starting Web Frontend on http://127.0.0.1:3000 ...
start "AgentHub-Web" cmd /c "cd /d "%ROOT%\apps\web" && set VITE_AGENTHUB_API_BASE=%VITE_AGENTHUB_API_BASE%&& bun --cwd packages/app dev"

:: ========== Wait and verify ==========
echo.
echo ============================================
echo   AgentHub All Services Starting...
echo ============================================
echo   API Backend:   http://%HOST%:%PORT%
echo   Agent Runtime: http://127.0.0.1:4096
echo   Web Frontend:  http://127.0.0.1:3000/agenthub
echo ============================================
echo.
echo [INFO] Waiting 5 seconds to verify services ...
timeout /t 5 /nobreak >nul

:: Verify each port
set "ALL_OK=1"
for %%p in (%PORT% 4096 3000) do (
    netstat -aon | findstr ":%%p " | findstr "LISTENING" >nul 2>&1
    if errorlevel 1 (
        echo [WARN] Port %%p is not listening yet - service may still be starting.
        set "ALL_OK=0"
    ) else (
        echo [OK]   Port %%p is listening.
    )
)

if "!ALL_OK!"=="1" (
    echo.
    echo [SUCCESS] All services are up! Open http://127.0.0.1:3000/agenthub
) else (
    echo.
    echo [INFO] Some services may still be starting. Check the individual windows.
)

echo.
echo Press any key to close this window (services will keep running) ...
pause >nul
endlocal
