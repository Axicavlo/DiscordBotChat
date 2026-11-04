@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run setup.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" tools\build_android.py
if errorlevel 1 (
    echo APK build failed. See the error above.
    pause
    exit /b 1
)
echo APK is ready in dist.
pause
