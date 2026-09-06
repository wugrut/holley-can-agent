@echo off
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
if exist "%~dp0efi_copilot.exe" (
    "%~dp0efi_copilot.exe" copilot --interface pcan --channel PCAN_USBBUS1 --bitrate 1000000 --duration 0 --out-dir "%~dp0reports" --db "%~dp0data\copilot_sessions.db"
) else (
    python "%~dp0portable_entry.py" copilot --interface pcan --channel PCAN_USBBUS1 --bitrate 1000000 --duration 0 --out-dir "%~dp0reports" --db "%~dp0data\copilot_sessions.db"
)
echo.
pause
