@echo off
title QuantumTrader Web Dashboard Server
cd /d "%~dp0"
echo =========================================================
echo Starting QuantumTrader Local Server on http://127.0.0.1:5000
echo =========================================================
start http://127.0.0.1:5000
python app.py
pause
