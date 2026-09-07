@echo off
setlocal
title EFI Intelligence Copilot - Offline Simulator Demo
color 0B
echo ===============================================================================
echo       EFI INTELLIGENCE COPILOT - OFFLINE SIMULATOR DEMO
echo ===============================================================================
echo Running 15-second multi-cycle engine simulation test...
echo No CAN hardware required. Validates analytics, baselines, and report engines.
echo.

set "SCRIPT_DIR=%~dp0"
if exist "%SCRIPT_DIR%efi_copilot.exe" (
    set "RUNNER="%SCRIPT_DIR%efi_copilot.exe""
    set "PROJ_ROOT=%SCRIPT_DIR%"
) else (
    if exist "%SCRIPT_DIR%portable_entry.py" (
        set "PROJ_ROOT=%SCRIPT_DIR%"
    ) else if exist "%SCRIPT_DIR%..\portable_entry.py" (
        set "PROJ_ROOT=%SCRIPT_DIR%..\"
    ) else (
        echo [ERROR] Could not locate portable_entry.py or efi_copilot.exe!
        pause
        exit /b 1
    )

    if exist "%PROJ_ROOT%.venv\Scripts\python.exe" (
        set "RUNNER="%PROJ_ROOT%.venv\Scripts\python.exe" "%PROJ_ROOT%portable_entry.py""
    ) else (
        python -c "import yaml" >nul 2>nul
        if errorlevel 1 (
            echo [!] Dependencies missing in active Python. Installing from requirements.txt...
            pip install -r "%PROJ_ROOT%requirements.txt"
        )
        set "RUNNER=python "%PROJ_ROOT%portable_entry.py""
    )
)

%RUNNER% simulator --duration 15 --scenario multi_cycle --out-dir "%PROJ_ROOT%reports" --db "%PROJ_ROOT%data\copilot_sessions.db"
echo.
echo ===============================================================================
echo Demo complete! Check the 'reports' folder for your generated Markdown and HTML reports.
echo ===============================================================================
pause

