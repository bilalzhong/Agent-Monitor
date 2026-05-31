@echo off
echo Updating Agent Monitor...
taskkill /f /im Agent-Monitor.exe >nul 2>&1
timeout /t 1 /nobreak >nul
copy /y "%~dp0dist\Agent-Monitor.exe" "C:\Program Files\Agent Monitor\Agent-Monitor.exe"
if %errorlevel% equ 0 (
    echo Done! Launch from Start Menu or desktop shortcut.
) else (
    echo Failed - run as Administrator.
)
pause
