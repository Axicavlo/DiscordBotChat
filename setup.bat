@echo off
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Setup complete. Run start.bat.
pause
exit /b 0
:failed
echo Setup failed. Check Python installation and network connection.
pause
exit /b 1
