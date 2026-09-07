@echo off
setlocal
title EFI Intelligence Copilot - Live PEAK PCAN-USB Session
color 0A
echo ===============================================================================
echo       EFI INTELLIGENCE COPILOT - LIVE PCAN-USB SESSION (1 MBPS)
echo ===============================================================================
echo Target Hardware: PEAK PCAN-USB (PCAN_USBBUS1)
echo Operating Mode:  PASSIVE LISTEN-ONLY (Zero write transmissions to vehicle)
echo.
echo Press Ctrl+C at any time to stop logging and generate your Intelligence Report.
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

%RUNNER% copilot --interface pcan --channel PCAN_USBBUS1 --bitrate 1000000 --duration 0 --out-dir "%PROJ_ROOT%reports" --db "%PROJ_ROOT%data\copilot_sessions.db"
echo.
pause

