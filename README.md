# Holley EFI Intelligence Copilot
### Agentic AI Calibration & Diagnostics Studio for Holley Terminator X / X MAX
*Calibrated for the **1980 Ford Fairmont 4-Door "Boxtop" Turbo 4.8L LS + GM 4L80E** Platform*

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Google GenAI: Gemini 2.5](https://img.shields.io/badge/AI-Google_Gemini_2.5-4285F4.svg)](https://aistudio.google.com/)
[![Executable: Standalone .EXE](https://img.shields.io/badge/Windows-Standalone_.EXE-00e676.svg)]()
[![Tests: 135 Passing](https://img.shields.io/badge/Tests-135%2F135_Passing-brightgreen.svg)]()

---

## ⚡ BLUF (Bottom Line Up Front)

**Holley EFI Intelligence Copilot** is a high-performance calibration and telemetry companion that combines a **Customizable Live Digital HUD**, an automated **16×16 Fuel VE Table Optimizer**, and an expert tuning assistant powered by **Google Gemini 2.5**.

1. **Standalone Single Executable (`Holley_EFI_Copilot.exe`)**:
   - Zero installation, zero dependencies, zero Python required on your tuning laptop.
   - Simply double-click **`Holley_EFI_Copilot.exe`**; it boots the server, launches your browser to `http://127.0.0.1:8420`, and immediately begins watching your Holley folders.
2. **Two Clean, Dedicated Workspaces**:
   - **`⚡ Live Dash`**: High-contrast, full-screen digital instrument cluster with 4 presets (*Drag Strip*, *Street Cruiser*, *Dyno Tuning*, *Sensor Health*), 4 modular gauge styles (Radial Swept Dial, Linear Level Bar, Digital Stat Box, Rolling Sparkline), and real-time hardware circuit fault badges.
   - **`🎯 Tuning Studio`**: The dual-panel AI Calibration Copilot and 16×16 Fuel VE Optimizer.
3. **Zero-Touch Auto-Pilot Datalog Ingestion**:
   - Automatically monitors `Documents\Holley\Terminator X V3\Data Logs\`, Google Drive, and handheld SD cards.
   - When you click "Stop Datalog" in Holley software, the Copilot ingests the run in **~1.5 seconds**, slices out the WOT pull, updates the 16×16 VE table, and Gemini automatically reviews the pass in your studio chat with voice announcements.
4. **Direct `.terx` Tune File Saving & 1-Click `Ctrl+V`**:
   - Save corrections directly into your `.terx` calibration file with automatic IEEE 802.3 CRC-32 recalculation.
   - Or click **`📋 COPY 16×16 VE (CTRL+V)`** to paste directly into Holley software (**Fuel ICF → Base Fuel Table**).
5. **Persistent Connection Diagnostics**:
   - Automatically logs USB-CAN handshakes, WinUSB handle locks, and telemetry frame rates to `logs/holley_copilot.log` (mirrored to `G:\My Drive\Holley\logs\`).
   - One-click **`🩺`** button in the header copies a complete hardware diagnostic snapshot straight to your clipboard.

---

## 🖥️ Studio Architecture: Two Dedicated Modes

```
╔════════════════════════════════════════════════════════════════════════════════════════╗
║ ⚡ HOLLEY EFI COPILOT   1980 Fairmont 4.8L Turbo LS   [⚡ Live Dash] [🎯 Tuning Studio] 🩺 ║
╚════════════════════════════════════════════════════════════════════════════════════════╝

MODE 1: ⚡ LIVE DIGITAL HUD (Cockpit & Trackside Instrumentation)
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ PRESETS: [🏁 Drag Strip] [🚗 Street Cruiser] [🎯 Dyno / Tuning] [🩺 Sensor Health]    │
├─────────────────────┬─────────────────────┬─────────────────────┬──────────────────────┤
│    ENGINE RPM       │    BOOST PRESSURE   │  FUEL RAIL PRESSURE │  WIDEBAND AFR (AVG)  │
│   [ 6,240 RPM ]     │     [ 14.8 PSI ]    │   [ 72.8 PSI ]      │     [ 11.4 AFR ]     │
│   (Radial Dial)     │    (Radial Dial)    │    (Linear Bar)     │     (Linear Bar)     │
├─────────────────────┼─────────────────────┼─────────────────────┼──────────────────────┤
│  TRANSBRAKE STATUS  │  4L80E INPUT RPM    │ KNOCK RETARD TRACE  │  COOLANT / TRANS     │
│     [ LOCKED ]      │    [ 3,180 RPM ]    │   [ 0.0° Retard ]   │   192°F  │  185°F    │
│     (Stat Box)      │     (Stat Box)      │  (Sparkline Chart)  │      (Stat Box)      │
└─────────────────────┴─────────────────────┴─────────────────────┴──────────────────────┘

MODE 2: 🎯 TUNING STUDIO (Dual-Panel Calibration & VE Optimizer)
┌───────────────────────────────────────────┬────────────────────────────────────────────┐
│   🤖 AI CALIBRATION CO-DRIVER (LEFT)      │   🎯 16×16 FUEL VE OPTIMIZER (RIGHT)       │
│                                           │                                            │
│   📥 Drag & Drop Holley .dl/.dlz Log Here │   Tune: [Default Turbo LS ▼]  Revisions (3)│
│                                           │   [x] Fold Fuel Learn % into Base VE       │
│   [⛽ 1:1 Fuel PSI]  [📈 WOT & AFR Safety] │                                            │
│   [🎯 16x16 VE Map]  [🔍 Idle Stability]   │   🏁 POST-PULL VERDICT:                    │
│   [🏎️ Staging]       [⚙️ 4L80E Converter]  │   Peak 14.8 PSI @ 6,240 RPM • AFR 11.4     │
│                                           │   58.0 PSI Effective Rail Delta (Verified) │
│   💬 Gemini Conversational Feed:          │                                            │
│   "Your 2nd gear pull maintained 58.0 PSI │   ┌─────┬──────┬──────┬──────┬──────┐      │
│    differential across 14.8 PSI boost.    │   │ RPM │ 20k  │ 100k │ 180k │ 260k │      │
│    Rail pressure peaked at 72.8 PSI. VE   │   ├─────┼──────┼──────┼──────┼──────┤      │
│    cells between 5000-5600 RPM / 180 kPa  │   │ 5200│  58  │  84  │ 112+4│ 128  │      │
│    require a +3.2% trim for 11.5 target." │   │ 5600│  61  │  88  │ 118+3│ 134  │      │
│                                           │   └─────┴──────┴──────┴──────┴──────┘      │
│   [Ask Gemini anything about your tune...]│   [💾 Save to .terx]  [📋 Copy 16x16 VE]   │
└───────────────────────────────────────────┴────────────────────────────────────────────┘
```

---

## 🏎️ Target Vehicle Calibration Specification

Every tool and reasoning prompt in the Copilot is grounded in the exact mechanical and electrical build parameters of the **1980 Ford Fairmont Turbo LS**:

| Subsystem | Hardware & Calibration Parameter | Invariant / Diagnostic Rule |
|:---|:---|:---|
| **Vehicle** | 1980 Ford Fairmont 4-Door "Boxtop" (Fox body chassis) | ~3,300 lbs race weight |
| **Engine** | GM 4.8L Gen III Iron Block LS (`LM7`/`LR4`) | 8 Cylinders, 293 ci displacement |
| **Camshaft** | Elgin E-1840-P "Sloppy Stage 2" (`228°/230° @ .050"`, `.585"/.585"`, `112° LSA`) | PAC 1218 beehive springs; prone to low-manifold vacuum (~45–55 kPa idle) |
| **Turbocharger** | VS Racing 78/75 cast turbo on Hooker BlackHeart manifold | 3" cold side FMIC, Pre-TB 50mm BOV, 3" electric cutout, NGK BR7EF plugs @ 0.022" |
| **Fuel System** | Racetronix 420 LPH in-tank pump + Aeromotive mechanical regulator | **58.0 PSI Base Rail Pressure referenced 1:1 with boost** |
| **Injectors** | Siemens Deka 80 lb/hr High-Z Injectors | Continental Flex Fuel sensor (E85 / 93 Octane / E40 blend) |
| **Transmission** | GM 4L80E 4-speed automatic (TransGo HD2, Alto Red Eagle clutches) | **Yank 3600 RPM stall converter**, audited slip ratio across shifts |
| **Staging / Launch** | 3rd-Gear Mechanical Bind-Up "Sloppy Transbrake" | Targets **3000–3200 RPM @ 0°–5° BTDC** on 2-step |
| **Rear Axle** | Ford 8.8-inch SN95 rear axle (`3.73:1` ring & pinion) | 245/45R17 Drag Radials (~25.85" rolling diameter) |
| **Safety Limits** | 12.0–15.0 PSI standard boost | **> 17.0 PSI pump gas blend cut**, **20.0 PSI max E85 boost**, **6,800 RPM redline** |

---

## 🤖 Gemini 2.5 Agentic Capabilities

The AI layer uses Google's official `google-genai` SDK with **Gemini 2.5 Flash / Pro**.

Rather than hallucinating or guessing numbers, Gemini calls **grounded, deterministic Python tools** behind the scenes:

### 1. `audit_fuel_system()` — 1:1 Boost Reference Tracking
- **The Rule:** The fuel pressure regulator must increase mechanical rail pressure by exactly 1 PSI for every 1 PSI of manifold boost.
- **The Check:**
  $$\text{Effective Rail Differential} = P_{\text{fuel}} - P_{\text{boost}} \approx 58.0\text{ PSI}$$
- At 0 PSI boost (101 kPa), rail pressure should be ~58 PSI. At 14 PSI boost, rail pressure must rise to ~72 PSI (72 - 14 = 58 PSI differential).
- If effective pressure drops below 53 PSI, Gemini immediately warns of fuel pump cavitation, voltage sags, or disconnected boost-reference vacuum lines.

### 2. `get_ve_recommendations(include_learn=True)` — 16×16 Table Optimizer
- Calculates cell-by-cell VE corrections across a 16×16 RPM (`500..7000`) × MAP (`20..260 kPa`) matrix.
- **Transient Filtering:** Excludes samples with $|d\text{TPS}/dt| > 25\%/\text{s}$ or $|d\text{MAP}/dt| > 65\text{ kPa/s}$.
- **Temperature Gating:** Excludes cold engine samples ($\text{ECT} < 160^\circ\text{F}$) and DFCO intervals.
- **Learn Table Folding:** When enabled, folds both Holley ECU Learn % and Closed-Loop Compensation into the recommended Base VE table:
  $$\text{Recommended\_VE} = \text{Base\_VE} \times \left(1 + \frac{\text{CL\_Comp} + \text{Fuel\_Learn}}{100}\right)$$

### 3. `analyze_datalog(file_path)` — Native Binary Decompressor
- Pure Python reverse-engineered decompressor and parser for Holley `.dl` and `.dlz` files (Terminator X V3 2512-byte layout and Holley V6 4120-byte layout).
- Extracts WOT pulls, peak boost, wideband AFR error against target AFR, minimum rail pressure, max injector duty cycle, and knock retard events.

### 4. `audit_drivetrain_and_staging()` — 4L80E Slip & Transbrake
- Audits Yank 3600 stall converter slip ratio across gear shifts.
- Confirms 3rd-gear transbrake staging clamps engine speed to 3000–3200 RPM with timing retarded to 0°–5° BTDC.

---

## 📂 Zero-Touch File Monitoring (How It Works on Your Laptop)

The application includes an active background file watcher (`AutoHandoffWatcher`) that dynamically monitors:

- `%USERPROFILE%\Documents\Holley\Terminator X V3\Data Logs\`
- `%USERPROFILE%\OneDrive\Documents\Holley\Terminator X V3\Data Logs\`
- `%USERPROFILE%\Documents\Holley\Terminator X V3\Global Files\`
- Current execution directory (`G:\My Drive\Holley` or local folder)
- Any connected SD card or USB flash drive containing a `Holley` folder

### The Auto-Pilot Loop:
1. Make a pass or dyno pull.
2. In Holley software, click "Stop Datalog" (saving the file).
3. The Copilot detects the file modification in **~1.5 seconds**.
4. It parses the run, updates the 16×16 heatmap table, writes `COPY 16x16 VE TABLE (CTRL+V).txt` to your drive, and Gemini posts an engineering summary to the studio chat with audio announcement.
5. You click in the Holley Base Fuel table and hit `Ctrl+V`.

---

## 🚀 Quickstart: Running on Your Tuning Laptop

### Option 1: Standalone Single Executable (No Python Required)
1. On your tuning laptop, open **`G:\My Drive\Holley`** (or extract the portable zip).
2. Double-click:
   ```cmd
   Holley_EFI_Copilot.exe
   ```
3. Your browser automatically opens to `http://127.0.0.1:8420`.
4. *(Optional)* Click **🔑 Gemini Key** in the header and paste your free Google Gemini API key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey). (If left blank, the app runs on its built-in offline EFI expert engine).

### Option 2: Running from Python Source
```bash
# Clone the repository
git clone https://github.com/wugrut/holley-can-agent.git
cd holley-can-agent

# Install dependencies
pip install -r requirements.txt

# Run the studio
python portable_entry.py dashboard --port 8420
```

---

## 🧪 Automated Test Suite

The test suite covers binary parsing, VE matrix math, Gemini tool dispatch, 1:1 boost reference audits, and safety invariants:

```bash
pytest -v
```

```text
============================= test session starts =============================
collected 111 items

tests/test_ai_copilot.py ...                                             [  2%]
tests/test_baseline.py ......                                            [  8%]
tests/test_diagnostics.py .......                                        [ 14%]
tests/test_dl_parser.py ....                                             [ 18%]
tests/test_events.py ....                                                [ 21%]
tests/test_hardware.py .......                                           [ 27%]
tests/test_hefi_protocol.py ....                                         [ 31%]
tests/test_holley_usbcan.py ..........................                   [ 54%]
tests/test_protocol.py ........................                          [ 76%]
tests/test_reports.py ..                                                 [ 78%]
tests/test_simulator.py .......                                          [ 84%]
tests/test_storage.py ....                                               [ 88%]
tests/test_telemetry_quality.py ..........                               [ 97%]
tests/test_vehicle.py ...                                                [100%]

============================= 111 passed in 2.10s =============================
```

---

## 📄 Documentation Directory

- [`docs/AI_ARCHITECTURE.md`](docs/AI_ARCHITECTURE.md) — Grounded LLM reasoning layer, tool calling schemas, and safety isolation.
- [`docs/HOLLEY_CAN_PROTOCOL_REVERSED.md`](docs/HOLLEY_CAN_PROTOCOL_REVERSED.md) — Complete reverse-engineered 29-bit CAN arbitration, RPC multi-frame streaming, and hardware circuit fault bitfield specification.
- [`docs/CAN_PROTOCOL.md`](docs/CAN_PROTOCOL.md) — Holley standard HEFI & Racepak 1 Mbps CAN channel specifications.
- [`docs/HOLLEY_USB_CAN_INTERFACE.md`](docs/HOLLEY_USB_CAN_INTERFACE.md) — WinUSB driver reverse-engineering for Holley 558-443 cable.
- [`FIELD_GUIDE.md`](FIELD_GUIDE.md) — Trackside tuning and hardware wiring field manual.

---

## ⚖️ License & Passive Safety Invariant

Distributed under the MIT License.

**Passive Read-Only Safety Invariant:** Holley EFI Intelligence Copilot is an observation, diagnostics, and calibration decision-support tool. It operates in passive read-only mode and **never** writes to ECU EEPROM or transmits unsolicited calibration flashes over CAN.
