@echo off
title XiaoZhiVN Server Engine
cd /d "%~dp0"

echo ===================================================
echo        Dang khoi dong XiaoZhiVN Server Engine...
echo ===================================================

if exist ".venv\Scripts\python.exe" (
    start "" ".venv\Scripts\python.exe" "server\desktop_app.py"
) else if exist "C:\Python313\python.exe" (
    start "" "C:\Python313\python.exe" "server\desktop_app.py"
) else (
    start "" python "server\desktop_app.py"
)

exit

