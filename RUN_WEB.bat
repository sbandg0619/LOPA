@echo off
chcp 65001 >nul
setlocal EnableExtensions

cd /d "%~dp0\web"

REM === node / npm 경로 ===
set "NODE_DIR=C:\Program Files\nodejs"
set "PATH=%NODE_DIR%;%PATH%"

echo ==================================================
echo LOPA WEB (Next dev)
echo DIR=%CD%
echo NODE_DIR=%NODE_DIR%
echo ==================================================
echo.

REM npm.cmd 직접 실행(환경에 npm이 없던 문제 방지)
"%NODE_DIR%\npm.cmd" run dev

pause
exit /b 0
