@echo off
setlocal EnableExtensions
chcp 65001 >nul
pushd "%~dp0"

REM --------------------------------------------------
REM Defaults (wrapper bat에서 넘겨주면 그 값 그대로 사용)
REM --------------------------------------------------
if not defined APP_PROFILE set "APP_PROFILE=personal"
if not defined COLLECT_MODE set "COLLECT_MODE=dev"
if not defined DB set "DB=lol_graph_public.db"
if not defined SEED set "SEED=파뽀마블#KRI"

REM --------------------------------------------------
REM Python selection: PY가 있으면 그걸 사용 (따옴표 없이 "경로만" 넣기)
REM 예) set "PY=C:\Users\ajtwl\AppData\Local\Programs\Python\Python313\python.exe"
REM --------------------------------------------------
set "PY_EXE="
if defined PY set "PY_EXE=%PY%"
if "%PY_EXE%"=="" set "PY_EXE=python"

REM --------------------------------------------------
REM Sanity check: requests / dotenv import 가능해야 함
REM --------------------------------------------------
"%PY_EXE%" -c "import requests, dotenv; print('OK')" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] This Python cannot import requests/dotenv: "%PY_EXE%"
  echo It means you are NOT using the python where you installed requirements.txt.
  echo Fix example:
  echo   "%PY_EXE%" -m pip install -r requirements.txt
  echo.
  popd
  endlocal
  exit /b 1
)

echo.
echo [INFO] Starting pipeline via tools\pipeline.py ...
echo.

REM --------------------------------------------------
REM Run pipeline (logging is done inside tools\pipeline.py)
REM --------------------------------------------------
"%PY_EXE%" -u "%~dp0tools\pipeline.py"
set "RC=%ERRORLEVEL%"

echo.
echo [DONE] rc=%RC%
echo.

popd
endlocal
exit /b %RC%
