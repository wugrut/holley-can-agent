# EFI Intelligence Copilot — Tuning Laptop Field Guide
### Holley Terminator X / Terminator X MAX CAN Bus Connection Manual

This field guide is designed for automotive tuners, calibrators, and dyno operators connecting a Windows laptop directly to the Holley Terminator X / X MAX CAN bus.

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

## 5. Step-by-Step Field Tuning Workflow

```
 ┌──────────────────────┐
 │  Step 1: Preflight   │  Run '4_PREFLIGHT_HARDWARE_CHECK.bat'
 │  Hardware Sniffer    │  Verify ~60Ω, 1 Mbps, and live frame reception
 └──────────┬───────────┘
            ▼
 ┌──────────────────────┐
 │  Step 2: Start Log   │  Run '2_RUN_LIVE_HOLLEY_USB.bat' (or '2_RUN_LIVE_HOLLEY_CABLE.bat')
 │  Before Pull / Drive │  System runs in listen-only mode (zero write traffic)
 └──────────┬───────────┘
            ▼
 ┌──────────────────────┐
 │  Step 3: Dyno / Road │  Make your pull or driving loop. Terminal displays
 │  Telemetry Capture   │  real-time RPM, MAP, AFR, CLT, and detected events.
 └──────────┬───────────┘
            ▼
 ┌──────────────────────┐
 │  Step 4: Stop Log    │  Press Ctrl+C in the command window.
 │  Generate Reports    │  Auto-generates Markdown & HTML reports in /reports/
 └──────────┬───────────┘
            ▼
 ┌──────────────────────┐
 │  Step 5: Review &    │  Open 'reports/report_<session_id>.html' in browser.
 │  Evidence Action     │  Review baseline deltas, fueling trims, and action items.
 └──────────────────────┘
```

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
