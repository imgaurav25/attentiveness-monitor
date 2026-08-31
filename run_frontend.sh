#!/usr/bin/env bash
# Attentiveness Monitor - Frontend (React/Vite) launcher, macOS/Linux
set -e
cd "$(dirname "$0")/frontend"

if [ ! -d "node_modules" ]; then
    echo "Installing frontend dependencies..."
    npm install
fi

echo "Starting frontend dev server on http://localhost:5173 ..."
npm run dev
