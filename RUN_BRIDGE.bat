@echo off
chcp 65001 >nul
setlocal EnableExtensions

REM === Python 경로 (네 고정 경로) ===
set "PY=C:\Users\ajtwl\AppData\Local\Programs\Python\Python313\python.exe"

REM === 루트 고정 ===
cd /d "%~dp0"

set "APP_PROFILE=personal"

echo ==================================================
echo LOPA BRIDGE
echo ROOT=%CD%
echo APP_PROFILE=%APP_PROFILE%
echo ==================================================
echo.

"%PY%" "lopa_bridge.py"

pause
exit /b 0
