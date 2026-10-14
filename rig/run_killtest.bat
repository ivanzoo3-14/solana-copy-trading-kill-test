@echo off
REM ============================================================
REM  KILL TEST launcher  --  PAPER ONLY, no keys, no orders
REM ============================================================
cd /d "%~dp0"

set PY=C:\LEGION\.venv\Scripts\python.exe
if not exist "%PY%" (
  echo ERROR: python not found at %PY%
  echo Edit this file to point PY at a python with: requests, websockets
  pause
  exit /b 1
)

REM Optional: set a paid RPC + matching websocket for real low latency.
REM Without these it falls back to the public endpoint (slower, rate limited).
REM   set KILLTEST_RPC_URL=https://mainnet.helius-rpc.com/?api-key=YOUR_KEY
REM   set KILLTEST_WS_URL=wss://mainnet.helius-rpc.com/?api-key=YOUR_KEY

if "%~1"=="" (
  echo.
  echo   Usage:
  echo     run_killtest.bat selftest        ^<- run this first
  echo     run_killtest.bat run             ^<- start the kill test
  echo     run_killtest.bat status          ^<- live counters
  echo     run_killtest.bat track           ^<- catch-up forward tracking
  echo     run_killtest.bat verdict         ^<- pre-registered verdict
  echo.
  pause
  exit /b 0
)

if /I "%~1"=="verdict" (
  "%PY%" kt_verdict.py %2 %3
  pause
  exit /b 0
)

REM Control commands are handled by ktctl.py (light: spawns nothing, reads no config)
if /I "%~1"=="status"  ( "%PY%" ktctl.py status  & pause & exit /b 0 )
if /I "%~1"=="start"   ( "%PY%" ktctl.py start   & pause & exit /b 0 )
if /I "%~1"=="stop"    ( "%PY%" ktctl.py stop    & pause & exit /b 0 )
if /I "%~1"=="restart" ( "%PY%" ktctl.py restart & pause & exit /b 0 )
if /I "%~1"=="watch"   ( "%PY%" ktctl.py watch   & exit /b 0 )

"%PY%" kt_run.py %1 %2 %3
pause
