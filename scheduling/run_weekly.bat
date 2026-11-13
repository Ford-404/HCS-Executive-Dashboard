@echo off
REM Runs the weekly National Active Project Summary. Used by Windows Task Scheduler.
cd /d "%~dp0.."
if not exist logs mkdir logs
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m report %* >> "logs\scheduler.log" 2>&1
) else (
    python -m report %* >> "logs\scheduler.log" 2>&1
)
exit /b %ERRORLEVEL%
