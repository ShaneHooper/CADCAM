@echo off
rem G00 CAM launcher for Windows. Double-click it.
rem First run: builds a private Python environment in .venv (takes a few minutes, ~1 GB download).
rem After that it just starts the app. Pass a .gcad file to open it (or drag one onto this file).
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto run

rem build123d (OpenCascade) ships wheels for Python 3.10 to 3.13, so pick one of those
set "PY="
for %%V in (3.12 3.13 3.11 3.10) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>nul && set "PY=python"
)
if not defined PY goto nopython

echo First run: setting up G00 CAM with %PY% ... this takes a few minutes.
%PY% -m venv .venv || goto fail
".venv\Scripts\python.exe" -m pip install --upgrade pip || goto fail
".venv\Scripts\python.exe" -m pip install -e ".[ui]" || goto fail

:run
".venv\Scripts\python.exe" -m gsend_cad %*
if errorlevel 1 pause
exit /b 0

:nopython
echo.
echo Could not find Python 3.10 - 3.13.
echo Install Python 3.12 from https://www.python.org/downloads/ (tick "Add python.exe to PATH"),
echo then double-click G00CAM.bat again.
pause
exit /b 1

:fail
echo.
echo Setup failed - see the messages above. Delete the .venv folder before trying again.
pause
exit /b 1
