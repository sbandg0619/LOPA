@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

REM === User env ===
set PY="C:\Users\ajtwl\AppData\Local\Programs\Python\Python313\python.exe"
set WORKDIR=%USERPROFILE%\OneDrive\바탕 화면\lol_pick_ai

cd /d "%WORKDIR%" || (
  echo [ERROR] Cannot cd to WORKDIR: "%WORKDIR%"
  exit /b 1
)

REM === Profile: personal (uses .env.personal via riot_api.py) ===
set APP_PROFILE=personal

REM === Config ===
set SEED=파뽀마블#KRI
set DB=lol_graph_public.db
set DAYS=0
set MATCHES_PER_PLAYER=20
set MAX_PLAYERS=2000

REM === Logging ===
if not exist "logs" mkdir "logs"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set TS=%%i
set LOG=logs\collect_personal_latest_!TS!.log

echo [INFO] APP_PROFILE=%APP_PROFILE% > "%LOG%"
%PY% -V >> "%LOG%" 2>&1

REM 최신 패치 1개만 수집 + 패치 바뀌면 자동 체크포인트 리셋(collector 내부 로직)
%PY% collector_graph.py ^
  --seed "%SEED%" ^
  --db "%DB%" ^
  --target_patch latest ^
  --days %DAYS% ^
  --matches_per_player %MATCHES_PER_PLAYER% ^
  --max_players %MAX_PLAYERS% ^
  --mode dev ^
  >> "%LOG%" 2>&1

if errorlevel 1 (
  echo [ERROR] Collect FAILED. See "%LOG%"
  exit /b 1
)

echo [OK] Collect DONE. See "%LOG%"
endlocal
exit /b 0
