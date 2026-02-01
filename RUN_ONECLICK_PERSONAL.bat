@echo off
chcp 65001 >nul
setlocal EnableExtensions

cd /d "%~dp0"

echo ==================================================
echo LOPA PERSONAL STACK (SAFE+STABLE)
echo - starts: Bridge + API + Web
echo - DOES NOT open browser automatically (prevents duplicate tabs)
echo ==================================================
echo.

start "LOPA BRIDGE" cmd /k ""%CD%\RUN_BRIDGE.bat""
start "LOPA API"    cmd /k ""%CD%\RUN_API.bat""
start "LOPA WEB"    cmd /k ""%CD%\RUN_WEB.bat""

echo.
echo [OPEN MANUALLY ONCE]
echo 1) http://localhost:3000/connect
echo 2) Bridge token 입력 -> Save + Go Recommend
echo.
echo (중복 탭 방지 위해 자동 오픈은 일부러 껐음)
echo.

pause
exit /b 0
