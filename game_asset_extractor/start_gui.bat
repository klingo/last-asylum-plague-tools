@echo off
rem Starts the Game Asset Extractor window (no console). Uses the venv next to this file (see README.md), else the Python on PATH.
if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0gui.py"
) else (
    start "" pythonw "%~dp0gui.py"
)
