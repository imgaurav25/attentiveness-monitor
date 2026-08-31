#!/usr/bin/env bash
# Attentiveness Monitor - Desktop (Tkinter) launcher, macOS/Linux
set -e
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

echo "Installing/checking dependencies..."
pip install -r requirements.txt

echo "Starting Attentiveness Monitor (desktop)..."
python3 desktop_app/app.py
