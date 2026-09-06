@echo off
title EFI Intelligence Copilot - Offline Simulator Demo
color 0B
echo ===============================================================================
echo       EFI INTELLIGENCE COPILOT - OFFLINE SIMULATOR DEMO
echo ===============================================================================
echo Running 15-second multi-cycle engine simulation test...
echo No CAN hardware required. Validates analytics, baselines, and report engines.
echo.
if exist "%~dp0efi_copilot.exe" (
    "%~dp0efi_copilot.exe" simulator --duration 15 --scenario multi_cycle --out-dir "%~dp0reports" --db "%~dp0data\copilot_sessions.db"
) else (
    python "%~dp0portable_entry.py" simulator --duration 15 --scenario multi_cycle --out-dir "%~dp0reports" --db "%~dp0data\copilot_sessions.db"
)
echo.
echo ===============================================================================
echo Demo complete! Check the 'reports' folder for your generated Markdown & HTML reports.
echo ===============================================================================
pause
