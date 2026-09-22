@echo off
title QuantumTrader Web Dashboard Server
cd /d "%~dp0"
echo =========================================================
echo Starting QuantumTrader Live Web Dashboard...
echo The dashboard will automatically open in your web browser.
echo =========================================================
python app.py
pause
