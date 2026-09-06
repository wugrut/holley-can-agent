@echo off
title EFI Intelligence Copilot - Live CANable / SLCAN Session
color 0E
echo ===============================================================================
echo       EFI INTELLIGENCE COPILOT - LIVE CANABLE / SLCAN SESSION
echo ===============================================================================
echo.
echo Available COM ports on this laptop:
powershell -Command "[System.IO.Ports.SerialPort]::GetPortNames()"
echo.
set /p COMPORT="Enter COM port for CANable (e.g. COM3, COM4) [Default: COM3]: "
if "%COMPORT%"=="" set COMPORT=COM3
echo.
echo Connecting to CANable on %COMPORT% at 1,000,000 bps (Listen-Only)...
echo Press Ctrl+C at any time to stop logging and generate your Intelligence Report.
echo.
if exist "%~dp0efi_copilot.exe" (
    "%~dp0efi_copilot.exe" copilot --interface slcan --channel %COMPORT% --bitrate 1000000 --duration 0 --out-dir "%~dp0reports" --db "%~dp0data\copilot_sessions.db"
) else (
    python "%~dp0portable_entry.py" copilot --interface slcan --channel %COMPORT% --bitrate 1000000 --duration 0 --out-dir "%~dp0reports" --db "%~dp0data\copilot_sessions.db"
)
echo.
pause
