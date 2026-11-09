@echo off
title MYMILE Launcher
echo ===================================================
echo Launching MYMILE Full-Stack Platform...
echo ===================================================
echo 1. Starting Backend in a new window...
start "MYMILE Backend" cmd /c "%~dp0start-backend.bat"
timeout /t 3 /nobreak >nul
echo 2. Starting Frontend in a new window...
start "MYMILE Frontend" cmd /c "%~dp0start-frontend.bat"
echo ===================================================
echo Done! Both servers are starting up.
echo - Frontend: http://localhost:5173
echo - Backend:  http://127.0.0.1:8000/docs
echo ===================================================
timeout /t 5
