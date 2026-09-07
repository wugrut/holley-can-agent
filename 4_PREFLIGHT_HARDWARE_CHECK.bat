@echo off
setlocal
title EFI Intelligence Copilot - Hardware Preflight Check
color 0F
echo ===============================================================================
echo       EFI INTELLIGENCE COPILOT - PREFLIGHT HARDWARE BUS SNIFFER
echo ===============================================================================
echo Sniffs CAN traffic, verifies adapter connectivity, baud rate (1 Mbps),
echo and decodes live Holley Terminator X broadcast frames.
echo.
echo NOTE: With the official Holley USB cable, bus termination is internal
echo       to the Terminator X ECU. No external resistors are needed!
echo.
echo Select interface:
echo   [1] Official Holley USB Cable (Default - Recommended)
echo   [2] PEAK PCAN-USB
echo   [3] CANable / SLCAN (COM port)
echo.
set "CHOICE="
set /p CHOICE="Enter choice [1, 2, or 3, default 1]: "
if "%CHOICE%"=="" set CHOICE=1

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

if "%CHOICE%"=="3" (
    powershell -Command "[System.IO.Ports.SerialPort]::GetPortNames()"
    set /p COMPORT="Enter COM port (e.g. COM3): "
    if "%COMPORT%"=="" set COMPORT=COM3
    %RUNNER% preflight --interface slcan --channel %COMPORT% --seconds 15
) else if "%CHOICE%"=="2" (
    %RUNNER% preflight --interface pcan --channel PCAN_USBBUS1 --seconds 15
) else (
    %RUNNER% preflight --interface holley --channel HOLLEY_USBCAN_0 --seconds 15
)
echo.
pause

