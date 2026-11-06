@echo off
title Ni-Oh Server Engine
cd /d "%~dp0"
set PYTHONPATH=%~dp0

echo ===================================================
echo        Dang khoi dong Ni-Oh Server Engine...
echo ===================================================

if exist ".venv\Scripts\python.exe" (
    start "" ".venv\Scripts\python.exe" -m server.desktop_app
) else if exist "C:\Python313\python.exe" (
    start "" "C:\Python313\python.exe" -m server.desktop_app
) else (
    start "" python -m server.desktop_app
)

timeout /t 1 >nul
start http://localhost:8001
exit
