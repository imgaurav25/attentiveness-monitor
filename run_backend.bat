@echo off
REM Attentiveness Monitor - Backend (FastAPI) launcher, Windows
cd /d "%~dp0backend"

IF NOT EXIST venv (
    echo Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo Installing/checking backend dependencies...
pip install -r requirements.txt

echo Starting backend on http://localhost:8000 ...
uvicorn server:app --host 0.0.0.0 --port 8000 --reload

pause
