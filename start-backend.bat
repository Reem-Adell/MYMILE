@echo off
title MYMILE Backend (FastAPI)
echo ===================================================
echo Starting MYMILE Backend Server on http://127.0.0.1:8000
echo ===================================================
cd /d "%~dp0backend"
call .\venv\Scripts\activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
pause
