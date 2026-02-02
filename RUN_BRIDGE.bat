@echo off
chcp 65001 >nul
setlocal EnableExtensions

REM === Python 경로 (네 고정 경로) ===
set "PY=C:\Users\ajtwl\AppData\Local\Programs\Python\Python313\python.exe"

REM === 루트 고정 ===
cd /d "%~dp0"

REM === 프로필 ===
set "APP_PROFILE=personal"

REM === 브릿지 실행 시 자동으로 열릴 Connect URL ===
set "LOPA_WEB_CONNECT_URL=https://lopa-zeta.vercel.app/connect"

REM === 브릿지 포트 ===
set "LOPA_BRIDGE_PORT=12145"

REM === (NEW) API 자동 실행 옵션 ===
set "LOPA_API_AUTO_START=1"
set "LOPA_API_HOST=127.0.0.1"
set "LOPA_API_PORT=8000"
set "LOPA_API_APP=api_server:app"
set "LOPA_API_HEALTH_PATH=/health"
set "LOPA_API_LOG_FILE=lopa_api.log"

REM === (선택) lockfile 자동탐지 실패하면 아래 줄을 실제 경로로 켜기 ===
REM set "LOL_LOCKFILE=C:\Riot Games\League of Legends\lockfile"

echo ==================================================
echo LOPA BRIDGE (with API auto-start)
echo ROOT=%CD%
echo APP_PROFILE=%APP_PROFILE%
echo LOPA_WEB_CONNECT_URL=%LOPA_WEB_CONNECT_URL%
echo LOPA_BRIDGE_PORT=%LOPA_BRIDGE_PORT%
echo LOPA_API_AUTO_START=%LOPA_API_AUTO_START%
echo LOPA_API_PORT=%LOPA_API_PORT%
echo ==================================================
echo.

"%PY%" "lopa_bridge.py"

pause
exit /b 0
