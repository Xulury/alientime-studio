@echo off
setlocal EnableExtensions
title Alien Time Listing Studio
rem ------------------------------------------------------------------------------------------
rem  Alien Time Listing Studio - one-click start for Windows.
rem  Double-click this file. It sets everything up on the first run, starts the studio
rem  (backend + web interface) and opens it in your browser.
rem  Developer mode (live reload, needs Node.js):  start-studio.bat dev
rem  Other options: --port 8001  --no-browser  --reinstall  --rebuild
rem ------------------------------------------------------------------------------------------
cd /d "%~dp0"

set "PYEXE="

rem 1) The studio's own environment, if it already exists
if exist ".venv\Scripts\python.exe" (
  call :check ".venv\Scripts\python.exe"
  if not errorlevel 1 set "PYEXE=".venv\Scripts\python.exe""
)
if defined PYEXE goto :found

rem 2) The Python launcher (python.org installs)
call :check py -3.13
if not errorlevel 1 ( set "PYEXE=py -3.13" & goto :found )
call :check py -3.12
if not errorlevel 1 ( set "PYEXE=py -3.12" & goto :found )
call :check py -3
if not errorlevel 1 ( set "PYEXE=py -3" & goto :found )

rem 3) python on PATH
call :check python
if not errorlevel 1 ( set "PYEXE=python" & goto :found )

rem 4) Common install folders
for %%P in ("%LOCALAPPDATA%\Programs\Python\Python313\python.exe" "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" "%ProgramFiles%\Python313\python.exe" "%ProgramFiles%\Python312\python.exe" "%USERPROFILE%\anaconda3\python.exe" "%USERPROFILE%\miniconda3\python.exe") do (
  if not defined PYEXE if exist "%%~P" (
    call :check "%%~P"
    if not errorlevel 1 set "PYEXE="%%~P""
  )
)
if defined PYEXE goto :found

echo.
echo [studio] Python 3.12 or newer was not found on this computer.
winget --version >nul 2>nul
if not "%errorlevel%"=="0" goto :nopython
choice /C YN /M "[studio] Install Python 3.12 now with winget"
if errorlevel 2 goto :nopython
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
  set "PYEXE="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
  goto :found
)
echo [studio] Python could not be installed automatically.
goto :nopython

:nopython
echo [studio] Install Python 3.12 or 3.13 from https://www.python.org/downloads/windows/
echo [studio] (tick "Add python.exe to PATH" in the installer), then double-click this file again.
goto :end_pause

:found
call %PYEXE% "%~dp0scripts\launch_studio.py" %*
if errorlevel 1 goto :end_pause
endlocal
exit /b 0

:end_pause
echo.
echo [studio] Press any key to close this window.
pause >nul
endlocal
exit /b 1

rem ---- returns 0 when the given Python command is version 3.12 or newer -------------------
:check
call %* -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
exit /b %errorlevel%
