@echo off
setlocal
title Holley Agentic Tuning Studio - Terminator X MAX
color 0B
echo ===============================================================================
echo    HOLLEY AGENTIC TUNING STUDIO (Terminator X MAX / Racepak / 16x16 VE AI)
echo ===============================================================================
echo  - Auto-Handoff Mode:
echo      * When Terminator X.exe is CLOSED: Streams 1 Mbps Live CAN (HEFI/Racepak)
echo      * When Terminator X.exe is OPEN:   Watches Documents\Holley\Data Logs\
echo        and automatically scores every new .dl / .dlz pull!
echo  - 16x16 VE Table AI: Click "TUNE OPTIMIZER" -> "COPY 16x16 VE TABLE (CTRL+V)"
echo.
echo  Opening Studio at http://127.0.0.1:8420 ...
echo  Press Ctrl+C in this window when finished tuning.
echo ===============================================================================
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

%RUNNER% dashboard --interface holley --channel HOLLEY_USBCAN_0 --port 8420
pause

