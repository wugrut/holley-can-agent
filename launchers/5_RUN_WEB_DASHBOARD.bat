@echo off
title EFI Intelligence Copilot - Live Web Dashboard
color 0D
echo ===============================================================================
echo       EFI INTELLIGENCE COPILOT - REAL-TIME WEB DASHBOARD
echo ===============================================================================
echo Starting live dashboard server at http://127.0.0.1:8420 ...
echo Your default web browser will open automatically.
echo Press Ctrl+C in this window to stop the server.
echo.
if exist "%~dp0efi_copilot.exe" (
    "%~dp0efi_copilot.exe" dashboard --interface holley --channel HOLLEY_USBCAN_0 --port 8420
) else (
    python "%~dp0portable_entry.py" dashboard --interface holley --channel HOLLEY_USBCAN_0 --port 8420
)
pause
