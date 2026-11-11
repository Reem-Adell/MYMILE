@echo off
title MYMILE Backend (FastAPI)
echo ===================================================
echo Starting MYMILE Backend Server on http://127.0.0.1:8000
echo ===================================================
cd /d "%~dp0backend"
call .\venv\Scripts\activate
rem --reload-include .env: settings are read once at startup, so restart when backend\.env changes too.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-include .env
pause
