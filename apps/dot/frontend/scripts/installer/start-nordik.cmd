@echo off
setlocal

set "APP_DIR=%~dp0"
set "BACKEND_DIR=%APP_DIR%backend"
set "VENV_PY=%BACKEND_DIR%\.venv\Scripts\python.exe"

if exist "%VENV_PY%" (
  set "PYTHON_EXE=%VENV_PY%"
) else (
  set "PYTHON_EXE=python"
)

start "Nordik Backend" /MIN cmd /c ""cd /d "%BACKEND_DIR%" && "%PYTHON_EXE%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000""
timeout /t 2 /nobreak >nul
start "" "%APP_DIR%NordikDesktop.exe"

endlocal
