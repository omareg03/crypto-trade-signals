@echo off
title Push QuantumTrader to GitHub
cd /d "%~dp0"
echo ==============================================================================
echo        QUANTUM TRADER v2.0 - PUSH TO GITHUB REPOSITORY
echo ==============================================================================
echo.
echo Checking repository status...
git status
echo.
set /p REPO_URL="Enter your GitHub repo URL (Press Enter for default: https://github.com/omareg03/crypto-trade-signals.git): "
if "%REPO_URL%"=="" set REPO_URL=https://github.com/omareg03/crypto-trade-signals.git

echo.
echo Setting remote origin to: %REPO_URL%
git remote remove origin 2>nul
git remote add origin %REPO_URL%
git branch -M main

echo.
echo Staging and committing all project files...
git add .
git commit -m "QuantumTrader v2.0 - Verified Top 30 Multi-Asset Trading Signals & Mobile Web Dashboard" 2>nul

echo.
echo Pushing to GitHub (main branch)...
git push -u origin main

if %ERRORLEVEL% equ 0 (
    echo.
    echo ==============================================================================
    echo [SUCCESS] Your repository has been pushed to GitHub!
    echo Next step: Go to https://render.com and connect 'crypto-trade-signals'.
    echo ==============================================================================
) else (
    echo.
    echo ==============================================================================
    echo [NOTE] Push completed or requires GitHub authentication.
    echo If prompted by GitHub, sign in or enter your Personal Access Token.
    echo ==============================================================================
)
echo.
pause
