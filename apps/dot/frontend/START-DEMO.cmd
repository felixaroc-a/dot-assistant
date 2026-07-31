@echo off
REM ============================================================
REM  DOT — Arranque demo local (pitch / desarrollo)
REM  Fuerza API en 127.0.0.1:8000 (NO usa .env.production GCP)
REM  Electron: vite build --mode development + vite preview :5173
REM  (sin Vite HMR — evita SyntaxError en Electron)
REM ============================================================

setlocal
cd /d "%~dp0"

set "BACKEND_DIR=%~dp0..\backend"
set "FRONTEND_DIR=%~dp0"

echo.
echo ============================================================
echo   DOT DEMO — Arranque local
echo ============================================================
echo.
echo  Login demo:  V-12345678  /  test123
echo  API local:   http://127.0.0.1:8000
echo  UI preview:  http://127.0.0.1:5173  (Electron carga esa URL)
echo.
echo ------------------------------------------------------------
echo  INSTRUCCIONES (si prefieres manual)
echo ------------------------------------------------------------
echo.
echo  Terminal 1 — Backend:
echo    cd /d "%BACKEND_DIR%"
echo    python -m uvicorn app.main:app --reload --port 8000
echo.
echo  Terminal 2 — Frontend / Electron:
echo    cd /d "%FRONTEND_DIR%"
echo    npm run desktop:dev
echo.
echo  Nota: desktop:dev hace build local (API 127.0.0.1:8000)
echo        y luego vite preview + Electron. NO uses "npm run desktop"
echo        (ese usa Vite HMR y puede romper Electron).
echo.
echo ------------------------------------------------------------
echo  Lanzar automaticamente en ventanas nuevas?
echo ------------------------------------------------------------
echo.
choice /C SN /M "Abrir Backend + Frontend ahora (S=Si, N=No)"
if errorlevel 2 goto :manual_only
if errorlevel 1 goto :launch

:manual_only
echo.
echo  OK — usa las instrucciones de arriba en dos terminales.
echo  Cuando el backend diga "Uvicorn running" y Electron abra, listo.
echo.
pause
exit /b 0

:launch
echo.
echo  [1/2] Abriendo Backend en ventana nueva...
start "DOT Backend :8000" /D "%BACKEND_DIR%" cmd /k "echo DOT Backend — puerto 8000 & python -m uvicorn app.main:app --reload --port 8000"

echo  Esperando 3s para que el API arranque...
timeout /t 3 /nobreak >nul

echo  [2/2] Abriendo Frontend (build local + preview + Electron)...
start "DOT Frontend Electron" /D "%FRONTEND_DIR%" cmd /k "echo DOT Frontend — desktop:dev & npm run desktop:dev"

echo.
echo  Ventanas lanzadas.
echo  Espera el build de Vite (puede tardar 20-60s) y la ventana Electron.
echo  Login: V-12345678 / test123
echo.
pause
exit /b 0
