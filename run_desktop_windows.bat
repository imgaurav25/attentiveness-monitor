@echo off
REM Attentiveness Monitor - Desktop (Tkinter) launcher, Windows
cd /d "%~dp0"

IF NOT EXIST venv (
    echo Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo Installing/checking dependencies...
pip install -r requirements.txt

echo Starting Attentiveness Monitor (desktop)...
python desktop_app\app.py

pause
