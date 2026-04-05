#!/bin/bash
# 🛡️ Liberal IP Roller - Cross-platform Startup Script (Linux/macOS)

echo "[INFO] Checking dependencies for Liberal IP Roller..."

# Ensure we are in the project directory
cd "$(dirname "$0")"

# Check if python is installed
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python3 is not installed. Please install it first."
    exit 1
fi

# Check for virtual environment or global packages
# We recommend running in a venv, but this script will attempt to just run the app.
python3 -m pip install -r requirements.txt --quiet

echo "[INFO] Starting application..."
python3 main.py "$@"
