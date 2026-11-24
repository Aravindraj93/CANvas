@echo off
setlocal
cd /d "%~dp0"
call Setup_CANvas.bat
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install "pyinstaller>=6.0"
if errorlevel 1 goto failure
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --windowed --name CANvas --collect-all can --collect-all cantools --collect-all ics --hidden-import can.interfaces.ics_neovi --hidden-import can.interfaces.virtual desktop_entry.py
if errorlevel 1 goto failure
echo.
echo Build complete: dist\CANvas\CANvas.exe
echo Keep the entire dist\CANvas folder together when copying the application.
pause
exit /b 0
:failure
echo Build failed. Check the error above.
pause
exit /b 1
