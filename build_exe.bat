@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name ChatBot --add-data "assets;assets" app.py
if errorlevel 1 goto failed
echo Build complete: dist\ChatBot.exe
exit /b 0
:failed
echo Build failed.
exit /b 1
