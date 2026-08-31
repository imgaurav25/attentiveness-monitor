@echo off
REM Attentiveness Monitor - Frontend (React/Vite) launcher, Windows
cd /d "%~dp0frontend"

IF NOT EXIST node_modules (
    echo Installing frontend dependencies...
    call npm install
)

echo Starting frontend dev server on http://localhost:5173 ...
call npm run dev

pause
