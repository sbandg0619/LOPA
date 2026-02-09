@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
pushd "%~dp0"

REM -------------------------
REM Defaults
REM -------------------------
if not defined APP_PROFILE set "APP_PROFILE=personal"
if not defined COLLECT_MODE set "COLLECT_MODE=dev"
if not defined DB set "DB=lol_graph_public.db"
if not defined SEED set "SEED=파뽀마블#KRI"

REM 릴리즈 기본 ON (원하면 호출할 때 DO_RELEASE=0으로 덮어써도 됨)
if not defined DO_RELEASE set "DO_RELEASE=1"
if not defined RELEASE_VARIANT set "RELEASE_VARIANT=public"
if not defined RELEASE_OUT_DIR set "RELEASE_OUT_DIR=release_out"

REM Python UTF-8
set "PYTHONUTF8=1"

REM -------------------------
REM ✅ Personal key 보호: 99/120 + pacing ON
REM - pacing: 120초 윈도우를 '고르게' 분산시켜서 갑자기 멈칫(대기)하는 구간을 줄임
REM -------------------------
set "RIOT_PACE_120S=1"
set "RIOT_THROTTLE_1S=19"
set "RIOT_THROTTLE_120S=99"

REM -------------------------
REM Auto-pick Python that has requests+dotenv
REM Priority:
REM  1) PY env var (if set)
REM  2) Known Python313 path (user PC)
REM  3) py -3.13
REM  4) python (PATH)
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
echo [PERSONAL] DONE rc=%RC%
echo.
popd
endlocal
pause
exit /b %RC%

REM -------------------------
REM Subroutine: CHECK_PY
REM Uses CAND_CMD/CAND_ARGS -> sets PY_CMD/PY_ARGS and OKPY=1 if OK
REM -------------------------
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
