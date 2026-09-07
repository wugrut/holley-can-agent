@echo off
setlocal
title EFI Intelligence Copilot - Live CANable / SLCAN Session
color 0E
echo ===============================================================================
echo       EFI INTELLIGENCE COPILOT - LIVE CANABLE / SLCAN SESSION
echo ===============================================================================
echo.
echo Available COM ports on this laptop:
powershell -Command "[System.IO.Ports.SerialPort]::GetPortNames()"
echo.
set "COMPORT="
set /p COMPORT="Enter COM port for CANable (e.g. COM3, COM4) [Default: COM3]: "
if "%COMPORT%"=="" set COMPORT=COM3
echo.
echo Connecting to CANable on %COMPORT% at 1,000,000 bps (Listen-Only)...
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

%RUNNER% copilot --interface slcan --channel %COMPORT% --bitrate 1000000 --duration 0 --out-dir "%PROJ_ROOT%reports" --db "%PROJ_ROOT%data\copilot_sessions.db"
echo.
pause

