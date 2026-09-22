@echo off
title QuantumTrader — Top 30 Terminal Scanner
cd /d "%~dp0"
python console_scanner.py --top 30 --interval 60
pause
