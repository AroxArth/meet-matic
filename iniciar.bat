@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM Usa el entorno virtual si existe; si no, el Python del sistema.
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m transcriptor
) else (
    python -m transcriptor
)

pause
