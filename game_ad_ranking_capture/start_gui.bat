@echo off
rem Starts the Game AD Ranking Capture window: creates .venv if it is missing, installs the requirements on every
rem start (offline it warns and goes on with what is installed), then opens the window (no console).
rem The first scan downloads the OCR models (about 30 MB), so it needs the internet once.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating the virtual environment...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if errorlevel 1 (
        echo Could not create .venv: install Python 3.12 from python.org, then run this again.
        pause
        exit /b 1
    )
)

echo Installing the requirements...
".venv\Scripts\python.exe" -m pip install --upgrade --quiet -r requirements.txt
if errorlevel 1 (
    echo Installing the requirements failed ^(offline?^), starting with what is installed.
    timeout /t 5
)

start "" ".venv\Scripts\pythonw.exe" gui.py
