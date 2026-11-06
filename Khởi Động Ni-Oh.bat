@echo off
title Ni-Oh Server Engine
cd /d "%~dp0"

echo ===================================================
echo        Dang khoi dong Ni-Oh Server Engine...
echo ===================================================

:: Kiem tra virtualenv
if exist ".venv\Scripts\python.exe" (
    start "" ".venv\Scripts\python.exe" -m server.desktop_app
) else (
    start "" python -m server.desktop_app
)

exit
