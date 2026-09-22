@echo off
title QuantumTrader — Top 10 Terminal Scanner
cd /d "%~dp0"
python console_scanner.py --top 10 --interval 60
pause
