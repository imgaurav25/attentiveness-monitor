@echo off
setlocal

REM ============================================
REM Attentiveness Monitor - Backend Launcher
REM Windows / Python 3.12
REM ============================================

cd /d "%~dp0backend"

echo.
echo Checking for Python 3.12...

py -3.12 --version >nul 2>&1

IF ERRORLEVEL 1 (
    echo.
    echo ERROR: Python 3.12 was not found.
    echo Please install Python 3.12 and try again.
    echo.
    pause
    exit /b 1
)

echo Python 3.12 found.

REM ============================================
REM Create virtual environment if needed
REM ============================================

IF NOT EXIST venv\Scripts\python.exe (
    echo.
    echo Creating Python 3.12 virtual environment...
    py -3.12 -m venv venv

    IF ERRORLEVEL 1 (
        echo.
        echo ERROR: Failed to create virtual environment.
        echo.
        pause
        exit /b 1
    )
)

REM ============================================
REM Activate virtual environment
REM ============================================

call venv\Scripts\activate.bat

REM ============================================
REM Install/check dependencies
REM ============================================

echo.
echo Installing/checking backend dependencies...

python -m pip install -r requirements.txt

IF ERRORLEVEL 1 (
    echo.
    echo ERROR: Failed to install backend dependencies.
    echo.
    pause
    exit /b 1
)

REM ============================================
REM Verify MediaPipe
REM ============================================

echo.
echo Checking MediaPipe...

python -c "import mediapipe as mp; print('MediaPipe version:', mp.__version__); print('Face Mesh API available:', hasattr(mp, 'solutions'))"

IF ERRORLEVEL 1 (
    echo.
    echo ERROR: MediaPipe verification failed.
    echo.
    pause
    exit /b 1
)

REM ============================================
REM Start FastAPI
REM ============================================

echo.
echo Starting backend on http://localhost:8000 ...
echo.

python -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload

pause