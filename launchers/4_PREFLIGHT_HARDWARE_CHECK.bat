@echo off
title EFI Intelligence Copilot - Hardware Preflight Check
color 0F
echo ===============================================================================
echo       EFI INTELLIGENCE COPILOT - PREFLIGHT HARDWARE BUS SNIFFER
echo ===============================================================================
echo Tests USB-CAN adapter, bus termination (60 ohms), baud rate (1 Mbps),
echo and decodes live Holley Terminator X broadcast frames.
echo.
echo Select interface:
echo   [1] Official Holley USB Cable (Default)
echo   [2] PEAK PCAN-USB
echo   [3] CANable / SLCAN (COM port)
echo.
set /p CHOICE="Enter choice [1, 2, or 3, default 1]: "
if "%CHOICE%"=="3" (
    powershell -Command "[System.IO.Ports.SerialPort]::GetPortNames()"
    set /p COMPORT="Enter COM port (e.g. COM3): "
    if "%COMPORT%"=="" set COMPORT=COM3
    if exist "%~dp0efi_copilot.exe" (
        "%~dp0efi_copilot.exe" preflight --interface slcan --channel %COMPORT% --seconds 15
    ) else (
        python "%~dp0portable_entry.py" preflight --interface slcan --channel %COMPORT% --seconds 15
    )
) else if "%CHOICE%"=="2" (
    if exist "%~dp0efi_copilot.exe" (
        "%~dp0efi_copilot.exe" preflight --interface pcan --channel PCAN_USBBUS1 --seconds 15
    ) else (
        python "%~dp0portable_entry.py" preflight --interface pcan --channel PCAN_USBBUS1 --seconds 15
    )
) else (
    if exist "%~dp0efi_copilot.exe" (
        "%~dp0efi_copilot.exe" preflight --interface holley --channel HOLLEY_USBCAN_0 --seconds 15
    ) else (
        python "%~dp0portable_entry.py" preflight --interface holley --channel HOLLEY_USBCAN_0 --seconds 15
    )
)
echo.
pause
