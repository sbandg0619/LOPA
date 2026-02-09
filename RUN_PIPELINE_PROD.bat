@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
pushd "%~dp0"

REM -------------------------
REM Defaults (prod는 .env.public 기준)
REM -------------------------
if not defined APP_PROFILE set "APP_PROFILE=public"
if not defined COLLECT_MODE set "COLLECT_MODE=prod"
if not defined DB set "DB=lol_graph_public.db"
if not defined SEED set "SEED=파뽀마블#KRI"

REM 릴리즈 기본 ON
if not defined DO_RELEASE set "DO_RELEASE=1"
if not defined RELEASE_VARIANT set "RELEASE_VARIANT=public"
if not defined RELEASE_OUT_DIR set "RELEASE_OUT_DIR=release_out"

set "PYTHONUTF8=1"

REM -------------------------
REM ✅ PROD: 개인키용 강제 제한 제거
REM - pacing OFF
REM - throttle env 제거(미설정): riot_api가 헤더 기반으로 자동 한도 추적/조절
REM -------------------------
set "RIOT_PACE_120S="
set "RIOT_THROTTLE_1S="
set "RIOT_THROTTLE_120S="

REM -------------------------
REM Auto-pick Python that has requests+dotenv
REM -------------------------
set "PY_CMD="
set "PY_ARGS="
set "OKPY=0"

if defined PY (
  set "CAND_CMD=%PY%"
  set "CAND_ARGS="
  call :CHECK_PY
  if "!OKPY!"=="1" goto :PY_OK
)

set "CAND_CMD=C:\Users\ajtwl\AppData\Local\Programs\Python\Python313\python.exe"
set "CAND_ARGS="
if exist "!CAND_CMD!" (
  call :CHECK_PY
  if "!OKPY!"=="1" goto :PY_OK
)

set "CAND_CMD=py"
set "CAND_ARGS=-3.13"
call :CHECK_PY
if "!OKPY!"=="1" goto :PY_OK

set "CAND_CMD=python"
set "CAND_ARGS="
call :CHECK_PY
if "!OKPY!"=="1" goto :PY_OK

echo ==================================================
echo APP_PROFILE=%APP_PROFILE%
echo COLLECT_MODE=%COLLECT_MODE%
echo DB=%DB%
echo SEED=%SEED%
echo ROOT=%CD%
echo PY=%PY%
echo PY_CMD=python
echo PY_ARGS=
echo DO_RELEASE=%DO_RELEASE%
echo RELEASE_VARIANT=%RELEASE_VARIANT%
echo RELEASE_OUT_DIR=%RELEASE_OUT_DIR%
echo RIOT_PACE_120S=%RIOT_PACE_120S%
echo RIOT_THROTTLE_1S=%RIOT_THROTTLE_1S%
echo RIOT_THROTTLE_120S=%RIOT_THROTTLE_120S%
echo ==================================================
echo.
echo [ERROR] Cannot find a Python that can import requests+dotenv.
echo Fix 1 (recommended): set PY to your Python313:
echo   set "PY=C:\Users\ajtwl\AppData\Local\Programs\Python\Python313\python.exe"
echo Fix 2: install deps into current python:
echo   python -m pip install -r requirements.txt
echo.
popd
endlocal
pause
exit /b 1

:PY_OK
echo ==================================================
echo APP_PROFILE=%APP_PROFILE%
echo COLLECT_MODE=%COLLECT_MODE%
echo DB=%DB%
echo SEED=%SEED%
echo ROOT=%CD%
echo PY=%PY%
echo PY_CMD=%PY_CMD%
echo PY_ARGS=%PY_ARGS%
echo DO_RELEASE=%DO_RELEASE%
echo RELEASE_VARIANT=%RELEASE_VARIANT%
echo RELEASE_OUT_DIR=%RELEASE_OUT_DIR%
echo RIOT_PACE_120S=%RIOT_PACE_120S%
echo RIOT_THROTTLE_1S=%RIOT_THROTTLE_1S%
echo RIOT_THROTTLE_120S=%RIOT_THROTTLE_120S%
echo ==================================================
echo.

"%PY_CMD%" %PY_ARGS% -V
echo.

echo [INFO] Starting pipeline via tools\pipeline.py ...
echo.

"%PY_CMD%" %PY_ARGS% "%~dp0tools\pipeline.py" %*
set "RC=%ERRORLEVEL%"

echo.
echo [PROD] DONE rc=%RC%
echo.
popd
endlocal
pause
exit /b %RC%

:CHECK_PY
set "OKPY=0"
set "TMP_CMD=%CAND_CMD%"
set "TMP_ARGS=%CAND_ARGS%"
set "TMP_CMD=%TMP_CMD:"=%"

"%TMP_CMD%" %TMP_ARGS% -c "import requests, dotenv; print('OK')" >nul 2>nul
if %ERRORLEVEL%==0 (
  set "OKPY=1"
  set "PY_CMD=%TMP_CMD%"
  set "PY_ARGS=%TMP_ARGS%"
)
exit /b 0
