@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Campaign Manager
cd /d "%~dp0"

REM ==========================================================================
REM  Campaign Manager - one-click local run
REM
REM  Usage:
REM    Run.bat                  start on port 8000 and open the browser
REM    Run.bat 8123             start on a custom port
REM    Run.bat nobrowser        start without opening the browser
REM    Run.bat dev              start with auto-reload (code changes apply live)
REM    Run.bat rebuild          force a fresh build of the React interface
REM
REM  Safe to double-click. First run installs Python deps into .venv if the
REM  current interpreter lacks them; it never installs anything system-wide.
REM ==========================================================================

set "PORT=8000"
set "OPEN=1"
set "RELOAD="
set "FORCE_BUILD="
set "CHECK="

:parse
if "%~1"=="" goto parsed
set "ARG=%~1"
if /i "%ARG%"=="nobrowser" ( set "OPEN=0" ) else if /i "%ARG%"=="dev" ( set "RELOAD=--reload" ) else if /i "%ARG%"=="rebuild" ( set "FORCE_BUILD=1" ) else if /i "%ARG%"=="check" ( set "CHECK=1" ) else set "PORT=%ARG%"
shift
goto parse
:parsed

echo ============================================================
echo   Campaign Manager  -  starting up
echo ============================================================
echo.

REM ---------------------------------------------------------------- config ---
if not exist ".env" (
  echo [env] No .env found - creating one from .env.example
  copy /y ".env.example" ".env" >nul
  echo [env] IMPORTANT: open .env and set OCC_ADMIN_PASSWORD before signing in.
  echo.
)

REM ---------------------------------------------------------------- python ---
set "PYCMD="
where py >nul 2>nul && set "PYCMD=py -3"
if defined PYCMD goto have_python
where python >nul 2>nul && set "PYCMD=python"
if defined PYCMD goto have_python
echo [error] Python 3 was not found on PATH.
echo [error] Install Python 3.12 from https://www.python.org/downloads/ and re-run.
goto fail
:have_python

for /f "delims=" %%i in ('%PYCMD% -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%i"
if not defined PYEXE (
  echo [error] Could not start Python with "%PYCMD%".
  goto fail
)

REM ------------------------------------------------------------ dependencies --
if exist ".venv\Scripts\python.exe" goto use_venv
"%PYEXE%" -c "import fastapi, uvicorn" >nul 2>nul
if not errorlevel 1 goto use_system

:make_venv
echo [python] Dependencies missing - creating .venv and installing requirements.txt
echo [python] This happens once and can take a few minutes.
"%PYEXE%" -m venv .venv
if errorlevel 1 goto fail
set "PYEXE=%CD%\.venv\Scripts\python.exe"
"%PYEXE%" -m pip install --quiet --upgrade pip
if errorlevel 1 goto fail
"%PYEXE%" -m pip install --quiet -r requirements.txt
if errorlevel 1 goto fail
echo [python] Dependencies installed.
goto deps_ready

:use_venv
set "PYEXE=%CD%\.venv\Scripts\python.exe"
echo [python] Using .venv
goto deps_ready

:use_system
echo [python] Using the installed Python environment (dependencies already present)
goto deps_ready

:deps_ready

REM ------------------------------------------------------------------- ui ----
if defined FORCE_BUILD goto build_ui
if exist "static\dist\app.js" goto ui_ready

:build_ui
echo [ui] Building the React interface...
where npm >nul 2>nul
if errorlevel 1 (
  echo [ui] WARNING: npm was not found, so the interface cannot be rebuilt.
  echo [ui] Install Node.js 20+ and re-run, or restore the committed static\dist folder.
  goto ui_ready
)
pushd frontend
if not exist "node_modules" (
  echo [ui] Installing frontend packages...
  call npm install --no-audit --no-fund
  if errorlevel 1 (
    popd
    goto fail
  )
)
call npm run build
if errorlevel 1 (
  popd
  goto fail
)
popd
echo [ui] Build complete.
goto ui_ready

:ui_ready

if not defined CHECK goto serve

echo.
echo [check] Setup looks good. Nothing was started.
echo [check]   Python   : %PYEXE%
echo [check]   Port     : %PORT%
echo [check]   React UI : static\dist\app.js present
echo [check] Run "Run.bat" to start the app.
goto end

REM ---------------------------------------------------------------- serve ----
:serve
echo.
echo [serve] Campaign Manager is starting on http://127.0.0.1:%PORT%
if "%OPEN%"=="1" start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 4; Start-Process 'http://127.0.0.1:%PORT%'"
echo [serve] The browser opens automatically in a moment.
echo [serve] Press Ctrl+C in this window to stop the app.
echo.

"%PYEXE%" -m uvicorn app.main:app --host 127.0.0.1 --port %PORT% %RELOAD%
goto end

:fail
echo.
echo [error] Startup failed. Review the messages above.
echo.
pause
endlocal
exit /b 1

:end
endlocal
