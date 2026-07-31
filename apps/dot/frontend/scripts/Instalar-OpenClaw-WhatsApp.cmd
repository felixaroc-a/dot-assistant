@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo [Nordik] Instalando dependencias del proyecto (si hace falta^)...
call npm install
if errorlevel 1 goto :err
echo.
call npm run setup:openclaw
if errorlevel 1 goto :err
echo.
echo [Nordik] Proceso terminado correctamente.
pause
exit /b 0
:err
echo.
echo [Nordik] Hubo un error. Revisa los mensajes de arriba (Node 22.12+, Git en Windows).
pause
exit /b 1
