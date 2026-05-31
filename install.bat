@echo off
setlocal enabledelayedexpansion
echo ============================================
echo   Agent Monitor - Windows Installer
echo ============================================
echo.

:: Check admin privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Please run as Administrator!
    echo Right-click install.bat ^> "Run as administrator"
    pause
    exit /b 1
)

set "INSTALL_DIR=C:\Program Files\Agent Monitor"
set "EXE_NAME=Agent-Monitor.exe"
set "SOURCE=%~dp0dist\%EXE_NAME%"

:: Check if exe exists
if not exist "%SOURCE%" (
    echo [ERROR] %SOURCE% not found!
    echo Please build first: pyinstaller --onefile --windowed --name "Agent-Monitor" --icon=app.ico main.py
    pause
    exit /b 1
)

echo [1/4] Creating install directory...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

echo [2/4] Copying application...
copy /Y "%SOURCE%" "%INSTALL_DIR%\%EXE_NAME%" >nul
if %errorlevel% neq 0 (
    echo [ERROR] Failed to copy files.
    pause
    exit /b 1
)

echo [3/4] Creating Start Menu shortcut...
set "START_MENU=%ProgramData%\Microsoft\Windows\Start Menu\Programs\Agent Monitor"
if not exist "%START_MENU%" mkdir "%START_MENU%"

powershell -Command ^
    "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%START_MENU%\Agent Monitor.lnk'); $s.TargetPath = '%INSTALL_DIR%\%EXE_NAME%'; $s.WorkingDirectory = '%INSTALL_DIR%'; $s.IconLocation = '%INSTALL_DIR%\%EXE_NAME%'; $s.Description = 'Agent Monitor - Claude Code Status Indicator'; $s.Save()"

echo [4/4] Creating Desktop shortcut...
powershell -Command ^
    "$desktop = [Environment]::GetFolderPath('Desktop'); $ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut(\"$desktop\Agent Monitor.lnk\"); $s.TargetPath = '%INSTALL_DIR%\%EXE_NAME%'; $s.WorkingDirectory = '%INSTALL_DIR%'; $s.IconLocation = '%INSTALL_DIR%\%EXE_NAME%'; $s.Description = 'Agent Monitor - Claude Code Status Indicator'; $s.Save()"

echo.
echo ============================================
echo   Installation Complete!
echo ============================================
echo.
echo   Installed to: %INSTALL_DIR%
echo   Start Menu:  Agent Monitor
echo   Desktop:     Agent Monitor
echo.
echo   You can now:
echo   - Pin to taskbar: Right-click shortcut ^> "Pin to taskbar"
echo   - Pin to Start:   Right-click shortcut ^> "Pin to Start"
echo.
pause
