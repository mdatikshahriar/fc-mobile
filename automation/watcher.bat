@echo off
tasklist /FI "WINDOWTITLE eq FC Mobile Reward Watcher*" /FI "IMAGENAME eq cmd.exe" 2>NUL | find /I "cmd.exe" >NUL
if not errorlevel 1 (
    echo Watcher is running - stopping it...
    taskkill /FI "WINDOWTITLE eq FC Mobile Reward Watcher*" /T /F
    echo.
    pause
) else (
    title FC Mobile Reward Watcher
    cd /d "%~dp0"
    echo Starting FC Mobile reward watcher...
    echo Run this file again any time to stop it.
    echo.
    python run.py
    echo.
    echo Watcher stopped.
    pause >nul
)
