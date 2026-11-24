@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    call Setup_CANvas.bat
    if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -c "import PySide6.QtWidgets, ics" >nul 2>&1
if errorlevel 1 (
    call Setup_CANvas.bat
    if errorlevel 1 exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "desktop_entry.py"
