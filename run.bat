@echo off
title Liberal IP Roller
echo [INFO] Checking dependencies for Liberal IP Roller...

if exist requirements.txt (
    pip install -q -r requirements.txt
) else (
    echo [ERROR] requirements.txt not found! Please ensure it exists in the folder.
    pause
    exit /b
)

echo [INFO] Starting application...
python main.py
pause
