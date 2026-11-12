# EFI Intelligence Copilot — Tuning Laptop Field Guide
### Holley Terminator X / Terminator X MAX AI Companion & Tuning Manual

This field guide is designed for automotive tuners, calibrators, and dyno operators running **Holley EFI Copilot** on a Windows tuning laptop alongside the Holley Terminator X / X MAX ECU and software.

---

## ⚡ Quick Start: 1-Click Launch (Recommended)

1. **Copy `Holley_EFI_Copilot.exe`** to your tuning laptop (desktop or any folder, or run directly from Google Drive / USB stick).
2. **Double-click `Holley_EFI_Copilot.exe`**.
   - No Python installation, virtual environments, or batch files required.
   - The app automatically launches the local server and opens your default web browser to `http://localhost:8420`.
   - The **Zero-Touch Auto-Pilot File Watcher** immediately begins monitoring your default Holley datalog and tune folders.
3. **Set your Google Gemini API Key** (optional, recommended for live AI commentary):
   - Click the ⚙️ Settings gear in the header.
   - Paste your Gemini API key (stored securely in browser local storage).
   - *If no key is present, the app continues to operate seamlessly using its deterministic rule engine!*

---

## 1. Safety Invariant & Physical Wiring

The Holley Terminator X and Terminator X MAX expose a 4-pin Delphi/Aptiv Metri-Pack 150 female connector on the main engine wiring harness (typically labeled `CAN` or `3RD PARTY CAN`).

### ⚠️ CRITICAL WIRING SAFETY WARNING
> [!CAUTION]
> **PIN C CARRIES +12V SWITCHED VEHICLE POWER.**
> **NEVER connect Pin C to any pin on your USB-CAN adapter!**
> USB-to-CAN adapters operate on +5V USB logic power. Connecting Pin C (+12V–14.4V alternator voltage) will immediately incinerate your USB adapter and can backfeed high voltage into your laptop's USB host controller, destroying the laptop motherboard.

### Holley 4-Pin Metri-Pack 150 Pinout

```
           ┌──────────────┐
     Top   │ [A]      [B] │
     Latch │              │
           │ [C]      [D] │
           └──────────────┘
```

| Pin | Wire Color (Typical) | Function | Adapter Connection | Notes |
|:---:|:---------------------|:---------|:-------------------|:------|
| **A** | **Blue** (or Blue/White) | **CAN High** | **CAN-H** | CAN 2.0B differential signal positive |
| **B** | **White** (or White/Black) | **CAN Low** | **CAN-L** | CAN 2.0B differential signal negative |
| **C** | **Red/White** (or Red) | **+12V Switched** | ⛔ **DO NOT CONNECT** | Cap, isolate, or leave floating! |
| **D** | **Black** (or Black/White) | **Ground / Shield** | **GND** | Essential for common-mode reference |

---

## 2. Bus Termination Verification (60Ω Rule)

A CAN 2.0B bus requires exactly **two 120Ω termination resistors** placed at the opposite physical ends of the communication trunk line, resulting in a net equivalent resistance of **60Ω** across CAN-H and CAN-L.

### Testing Termination with a Digital Multimeter (DMM):
1. **Turn vehicle ignition power OFF completely.**
2. Set your multimeter to **Resistance (Ω)**.
3. Place meter probes into **Pin A (CAN-H)** and **Pin B (CAN-L)**:
   - **55Ω – 65Ω (Nominally 60Ω):** **PERFECT.** Both end-of-line terminators are present.
   - **110Ω – 130Ω (Nominally 120Ω):** **MISSING ONE TERMINATOR.** The bus only has one resistor. Enable the built-in 120Ω jumper or switch on your USB-CAN adapter (e.g. CANable termination jumper).
   - **Megaohms / Open Loop (O.L.):** **NO TERMINATION.** Neither end is terminated, or the wiring harness is fractured.

---

## 3. Windows Device Driver Setup

### Option A: Official Holley USB-to-CAN Cable (Part 558-443) — RECOMMENDED & NATIVE
1. **Zero Extra Drivers Needed:** Uses the cable you already tune with and the pre-installed **Holley USBCAN Driver (WinUSB)** already on your laptop.
2. **No PEAK Software Required:** You do **NOT** need to install PEAK drivers, PCAN-Basic, PCAN-View, or any third-party CAN drivers.
3. Plug the Holley cable into your laptop USB port and the harness CAN port.
4. **Important:** Close the Holley Terminator X tuning software while running Copilot (WinUSB grants exclusive port access).
5. Launch using `2_RUN_LIVE_HOLLEY_USB.bat` (or `4_PREFLIGHT_HARDWARE_CHECK.bat` option 1).

### Option B: PEAK-System PCAN-USB
1. Download and run the official PEAK-System driver installer from [peak-system.com](https://www.peak-system.com/Drivers.523.0.html).
2. The installer automatically registers `PCANBasic.dll` into `C:\Windows\System32`.
3. Plug in your PCAN-USB dongle.
4. Launch using `2_RUN_LIVE_PCAN.bat`.

### Option C: CANable / CANable Pro (SLCAN Mode)
1. Plug the CANable into your laptop USB port.
2. In Windows, open **Device Manager** -> expand **Ports (COM & LPT)**.
3. Identify the port number assigned to the device (e.g., `COM3`, `COM4`).
4. Ensure the termination jumper on the CANable is closed if needed (see Section 2).
5. Launch using `3_RUN_LIVE_CANABLE_SLCAN.bat` and enter the COM port.

---

## 4. Holley ECU Software Broadcast Configuration

To transmit telemetry over CAN, the Terminator X / X MAX ECU broadcast must be enabled in the calibration file:

1. Open your tune in **Holley Terminator X Software** (V2 / V3 / V6).
2. From the top navigation ribbon, select **System Setup** -> **CAN Devices**.
3. Under CAN Broadcast:
   - Set **Channel**: `CAN 1`
   - Set **Speed**: `1 Mbit/sec (1,000,000 bps)`
   - Set **Broadcast Mode**: `Enable Racepak / Broadcast CAN`
4. Write the updated calibration to the ECU (`Transfer -> Send to ECU`).
5. Cycle vehicle ignition (Key OFF for 5 seconds, Key back to ON).

---

## 5. Step-by-Step Zero-Touch Field Tuning Workflow

`
 ┌────────────────────────┐
 │ Step 1: Launch App     │  Double-click 'Holley_EFI_Copilot.exe' on laptop.
 │ Zero-Touch Auto-Watch  │  Studio UI opens in browser; watcher polls Holley folders.
 └───────────┬────────────┘
             ▼
 ┌────────────────────────┐
 │ Step 2: Make Your Pull │  Do dyno pull or street pass in Holley Terminator X software.
 │ Save Datalog (Ctrl+S)  │  Save log (.dl / .dlz) to default Holley folder or SD card.
 └───────────┬────────────┘
             ▼
 ┌────────────────────────┐
 │ Step 3: Instant Audit  │  Copilot detects new log (<1.5s), runs safety audit,
 │ & VE Table Optimizer   │  filters transients, and recalculates 16×16 VE matrix.
 └───────────┬────────────┘
             ▼
 ┌────────────────────────┐
 │ Step 4: 1-Click Copy   │  Click 'Copy 16×16 VE (Ctrl+V)' in the studio UI.
 │ & Paste to Holley Tune │  Open Holley VE Table, select top-left cell, press Ctrl+V.
 └───────────┬────────────┘
             ▼
 ┌────────────────────────┐
 │ Step 5: Ask Gemini     │  Review Gemini AI summary of boost, fuel rail delta,
 │ Deep Insights          │  and knock risk. Ask questions using quick prompts.
 └────────────────────────┘
`

### Auto-Watch Monitored Locations:
The watcher scans every 1.5 seconds across:
- %USERPROFILE%\Documents\Holley\Terminator X V3\Data Logs\
- %USERPROFILE%\OneDrive\Documents\Holley\Terminator X V3\Data Logs\
- %USERPROFILE%\Documents\Holley\Terminator X V3\Global Files\
- G:\My Drive\Holley\
- Connected USB Flash Drives / SD Cards (D:\, E:\, F:\, G:\, H:\)

Whenever a file is saved or dragged into the window:
1. **Audio Bell Chime** plays alert in the browser.
2. **16×16 VE Table** calculates corrections and writes COPY 16x16 VE TABLE (CTRL+V).txt right next to the executable.
3. **Gemini Copilot** produces an engineering explanation of boost ramp rate, fuel rail pressure vs boost 1:1 tracking, and transient lambda safety.


### Safety & Confidence Features

- **Safety banner:** after every pull, a red (critical) or amber (warning) banner appears above the table for lean AFR under boost, injector differential pressure below 55 psi (critical below 52), knock retard, overboost/over-rev, and injector duty. The spoken announcement reports the real findings, and **Copy 16x16 VE asks for confirmation while a critical alert is active.**
- **Per-pass change limit:** no cell moves more than **5%** per pass (marked with a triangle). The tooltip shows the full measured error so you know another pass is needed.
- **Sample-count confidence:** cells with fewer than **5** steady-state samples are left unchanged (striped/dim) instead of being corrected from noise.
- **Comparison:** the panel above the table compares this pull with the previous one (boost, AFR error, fuel differential, knock) and tells you whether the table is improving.
- **Safe auto-ingest:** the watcher waits until Holley has finished writing a log before reading it, and retries a few times if it is still locked.

---

## 6. Troubleshooting Matrix

| Symptom | Probable Cause | Corrective Action |
|:--------|:---------------|:------------------|
| **Holley cable not detected** | Cable unplugged or loose USB connection | Firmly plug the Holley 558-443 cable directly into a laptop USB port (avoid unpowered USB hubs). |
| **WinUSB Access Denied (Error 5 / 32)** | Holley Terminator X software is open | Close Holley EFI tuning software before starting Copilot. WinUSB enforces exclusive single-app access. |
| **0 frames received** (Preflight fails) | Ignition key is in OFF position | Turn ignition switch to RUN/ON to power the ECU. |
| **0 frames received** | Holley broadcast disabled in calibration | Enable CAN Broadcast in Holley software (Section 4). |
| **0 frames received** | Reversed CAN-H / CAN-L wiring | Swap Pin A (Blue) and Pin B (White). |
| **High error frames (>10%)** | Termination impedance incorrect | Measure resistance between Pin A & B; ensure it reads ~60Ω. |
| **High error frames** | Baud rate mismatch | Verify adapter is set to 1,000,000 bps (1 Mbps). |
| **Channel dropout on bumps** | Poor crimp on Metri-Pack connector | Inspect terminal lock and strain-relief at Pin A, B, and D. |
| **PCANBasic library not found** | PEAK adapter selected without driver | Holley cable does NOT need PEAK. If deliberately using PEAK adapter, install PEAK drivers. |

---

*EFI Intelligence Copilot — Engineering Field Guide*
