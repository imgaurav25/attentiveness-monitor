#!/usr/bin/env bash
# Attentiveness Monitor - Backend (FastAPI) launcher, macOS/Linux
set -e
cd "$(dirname "$0")/backend"

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

echo "Installing/checking backend dependencies..."
pip install -r requirements.txt

echo "Starting backend on http://localhost:8000 ..."
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
