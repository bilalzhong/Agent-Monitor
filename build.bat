@echo off
setlocal enabledelayedexpansion
title Agent Monitor - Build Script

echo ============================================
echo   Agent Monitor - Windows Build Script
echo ============================================
echo.

:: ---- Python detection & install --------------------------------------------------
set "PYTHON="
for /f "tokens=*" %%i in ('where python 2^>nul') do (
    if not defined PYTHON set "PYTHON=%%i"
)
if defined PYTHON goto :check_python_ver

echo [INFO] Python not found in PATH. Checking winget / Microsoft Store...
where python3 >nul 2>&1 && set "PYTHON=python3"
if defined PYTHON goto :check_python_ver

:: Try common install paths
for %%p in (
    "%LocalAppData%\Programs\Python\Python313\python.exe"
    "%LocalAppData%\Programs\Python\Python312\python.exe"
    "%LocalAppData%\Programs\Python\Python311\python.exe"
    "%LocalAppData%\Programs\Python\Python310\python.exe"
    "%LocalAppData%\Programs\Python\Python39\python.exe"
    "%ProgramFiles%\Python313\python.exe"
    "%ProgramFiles%\Python312\python.exe"
    "%ProgramFiles%\Python311\python.exe"
    "%ProgramFiles%\Python310\python.exe"
    "%ProgramFiles%\Python39\python.exe"
) do (
    if exist %%p (
        set "PYTHON=%%p"
        goto :check_python_ver
    )
)

:: Not found -- try to install
echo [WARN] Python not found.
echo.
echo Python 3 is required to build this project.
echo.
choice /c yn /m "Install Python 3.13 via winget"
if errorlevel 2 exit /b 1

echo [INFO] Installing Python 3.13...
winget install Python.Python.3.13 --accept-source-agreements --accept-package-agreements
if %errorlevel% neq 0 (
    echo [ERROR] winget install failed.
    echo Please install Python manually from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

:: Refresh PATH and retry
set "PATH=%PATH%;%LocalAppData%\Programs\Python\Python313;%LocalAppData%\Programs\Python\Python313\Scripts"
for %%p in ("%LocalAppData%\Programs\Python\Python313\python.exe") do set "PYTHON=%%~p"
if defined PYTHON goto :check_python_ver

echo [ERROR] Python installed but not found. Please restart and re-run this script.
pause
exit /b 1

:check_python_ver
echo [INFO] Found Python: %PYTHON%
for /f "tokens=2" %%v in ('"%PYTHON%" --version 2^>^&1') do set "PYVER=%%v"
echo [INFO] Version: %PYVER%

:: ---- Ensure pip --------------------------------------------------------------
"%PYTHON%" -m pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Bootstrapping pip...
    "%PYTHON%" -m ensurepip --upgrade >nul 2>&1
)

:: ---- Install / upgrade build dependencies --------------------------------------
echo.
echo [1/3] Installing build dependencies...
"%PYTHON%" -m pip install --upgrade pip >nul 2>&1

set "DEPS=pyinstaller pillow pystray paramiko"
for %%d in (%DEPS%) do (
    echo   - %%d...
    "%PYTHON%" -m pip install "%%d" --quiet
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to install %%d.
        pause
        exit /b 1
    )
)
echo   Done.

:: ---- Clean previous build -----------------------------------------------------
echo.
echo [2/3] Cleaning previous build...
if exist "%~dp0build" rmdir /s /q "%~dp0build"
if exist "%~dp0dist"  rmdir /s /q "%~dp0dist"
echo   Done.

:: ---- PyInstaller build -----------------------------------------------------
echo.
echo [3/3] Building Agent-Monitor.exe...
"%PYTHON%" -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name "Agent-Monitor" ^
    --icon "%~dp0app.ico" ^
    --add-data "monitor.py;." ^
    --add-data "remote.py;." ^
    --hidden-import PIL ^
    --hidden-import PIL.Image ^
    --hidden-import PIL.ImageTk ^
    --hidden-import PIL.ImageDraw ^
    --hidden-import pystray ^
    --hidden-import paramiko ^
    --collect-all paramiko ^
    --clean ^
    "%~dp0main.py"

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

:: ---- Verify output ------------------------------------------------------------
set "OUTPUT=%~dp0dist\Agent-Monitor.exe"
if exist "%OUTPUT%" (
    for %%f in ("%OUTPUT%") do set "SIZE=%%~zf"
    set /a "SIZE_MB=!SIZE! / 1048576"
    echo.
    echo ============================================
    echo   Build Successful!
    echo ============================================
    echo.
    echo   Output:  dist\Agent-Monitor.exe
    echo   Size:    !SIZE_MB! MB
    echo.
    echo   Next steps:
    echo   - Run install.bat as Administrator to install
    echo   - Or run dist\Agent-Monitor.exe directly
    echo.
) else (
    echo [ERROR] Build completed but .exe not found.
    pause
    exit /b 1
)

endlocal
pause
