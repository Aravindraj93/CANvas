@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 goto failure
)
".venv\Scripts\python.exe" -m pip install -e ".[desktop,valuecan]"
if errorlevel 1 goto failure
echo.
echo Setup complete. Install Intrepid Product Drivers if not already installed.
echo Double-click Start_CANvas.bat to open the desktop application.
exit /b 0
:failure
echo Setup failed. Check the error above. Python 3.10 or newer is required.
pause
exit /b 1
