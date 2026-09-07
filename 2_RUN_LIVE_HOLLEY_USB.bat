@echo off
setlocal
title EFI Intelligence Copilot - Live Holley USB-CAN Session
color 0B
echo ===============================================================================
echo       EFI INTELLIGENCE COPILOT - LIVE HOLLEY USB-CAN SESSION (1 MBPS)
echo ===============================================================================
echo Target Hardware: Official Holley USB-to-CAN Cable (Part 558-443 via WinUSB)
echo Operating Mode:  PASSIVE LISTEN-ONLY (Zero write transmissions to vehicle)
echo.
echo Note: Please ensure Holley Terminator X software is closed before starting,
echo       as Windows WinUSB allows exclusive access by one application at a time.
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

%RUNNER% copilot --interface holley --channel HOLLEY_USBCAN_0 --bitrate 1000000 --duration 0 --out-dir "%PROJ_ROOT%reports" --db "%PROJ_ROOT%data\copilot_sessions.db"
echo.
pause

