@echo off
title EFI Intelligence Copilot - Live Holley USB Cable Session
color 0B
echo ===============================================================================
echo       EFI INTELLIGENCE COPILOT - LIVE HOLLEY USB CABLE SESSION (1 MBPS)
echo ===============================================================================
echo Target Hardware: Official Holley USB-to-CAN Cable (Part 558-443 via WinUSB)
echo Operating Mode:  PASSIVE LISTEN-ONLY (Zero write transmissions to vehicle)
echo.
echo Note: Please ensure Holley Terminator X software is closed before starting,
echo       as Windows WinUSB allows exclusive access by one application at a time.
echo.
echo Press Ctrl+C at any time to stop logging and generate your Intelligence Report.
echo.
if exist "%~dp0efi_copilot.exe" (
    "%~dp0efi_copilot.exe" copilot --interface holley --channel HOLLEY_USBCAN_0 --bitrate 1000000 --duration 0 --out-dir "%~dp0reports" --db "%~dp0data\copilot_sessions.db"
) else (
    python "%~dp0portable_entry.py" copilot --interface holley --channel HOLLEY_USBCAN_0 --bitrate 1000000 --duration 0 --out-dir "%~dp0reports" --db "%~dp0data\copilot_sessions.db"
)
echo.
pause
