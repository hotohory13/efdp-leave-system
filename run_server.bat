@echo off
REM Change to the folder where this .bat file lives (the project root)
cd /d "%~dp0"

echo Activating virtual environment...
call .venv\Scripts\activate.bat

echo Starting EFDP server...
echo Once it's running, open: http://127.0.0.1:8000/login
echo (Press Ctrl+C in this window to stop the server)
echo.

uvicorn app.main:app --reload

pause
