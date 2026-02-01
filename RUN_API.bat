@echo off
chcp 65001 >nul
setlocal EnableExtensions

set "PY=C:\Users\ajtwl\AppData\Local\Programs\Python\Python313\python.exe"
cd /d "%~dp0"

set "APP_PROFILE=personal"
set "PORT=8000"

echo ==================================================
echo LOPA API
echo ROOT=%CD%
echo APP_PROFILE=%APP_PROFILE%
echo PORT=%PORT%
echo ==================================================
echo.

"%PY%" -m uvicorn api_server:app --host 127.0.0.1 --port %PORT%

pause
exit /b 0
