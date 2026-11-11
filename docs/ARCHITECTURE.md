# System Architecture — EFI Intelligence Copilot

**System:** EFI Intelligence Copilot  
**Version:** 2.0.0  
**Architecture Style:** Layered, Event-Driven, Grounded Agentic AI Architecture  
**Primary Target:** Holley Terminator X & Terminator X MAX (Agnostic Multi-ECU Core)

---

## 1. Architectural Philosophy

EFI Intelligence Copilot separates low-level binary transport/file ingestion, mathematical filtering and optimization, grounded deterministic tools, and AI reasoning into strict, non-leaky tiers:

```
[ INGESTION & DATA SOURCES ]
   ├── Binary Holley Datalogs (.dl / .dlz - V3 2512-byte & V6 4120-byte headers)
   ├── Holley Global Calibration Files (.terx / .hefi)
   ├── Real-time CAN 2.0B Frames (1 Mbit/s WinUSB / PCAN / SLCAN)
   └── Zero-Touch AutoHandoffWatcher (1.5s background polling of Holley directories)
   │
   ▼
[ DETERMINISTIC PROCESSING & OPTIMIZATION TIER ]
   ├── HolleyDatalogReader (Decompression, struct parsing, multi-channel extraction)
   ├── Transient Filter (|dTPS/dt| <= 25%/s, ECT >= 160°F, DFCO rejection)
   ├── 16x16 VE Matrix Optimizer (RPM vs MAP load binning, Learn table folding)
   └── Mechanical Fuel System Auditor (P_fuel - P_boost == 58.0 PSI differential tracking)
   │
   ▼
[ GROUNDED TOOL EXECUTION TIER ]
   ├── get_vehicle_specs()      (Injects verified vehicle invariants: 4.8L LS, Sloppy S2, 78/75)
   ├── audit_fuel_system()      (Evaluates rail delta pressure vs boost and injector safety)
   ├── get_ve_recommendations() (Generates 16x16 matrix with sample counts and rich/lean deltas)
   └── analyze_datalog()        (Decompresses and summarizes WOT pulls, boost ramps, and AFR tracking)
   │
   ▼
[ AGENTIC AI REASONING TIER (google-genai SDK) ]
   ├── Google Gemini 2.5 Flash / Pro with Function Calling
   ├── Offline Deterministic Fallback Engine (when API key is absent)
   └── Conversational Calibration Co-Driver
   │
   ▼
[ TWO-PANEL TUNING & EXPLANATION STUDIO UI ]
   ├── Left: Gemini Calibration Co-Driver, quick prompt chips, file dropzone, audio alerts
   └── Right: 16x16 VE Heatmap Table, Fold Learn toggle, 1-Click "Copy 16x16 VE (Ctrl+V)"
```

---

## 2. Directory & Package Structure

The production codebase is organized cleanly under `holley_can/`:

```text
holley-can-agent/
├── Holley_EFI_Copilot.exe      # Single standalone Windows executable (~35 MB)
├── portable_entry.py           # PyInstaller entrypoint routing to Studio or CLI
├── build_portable.py           # Automated PyInstaller packaging script
├── requirements.txt            # Python dependencies (google-genai, fastapi, uvicorn, etc.)
│
├── holley_can/                 # Core Python Package
│   ├── __init__.py
│   ├── gemini_agent.py         # Google Gemini 2.5 integration & grounded tool declarations
│   ├── tune_optimizer.py       # 16x16 VE calculation, transient filter, AutoHandoffWatcher
│   ├── datalog_reader.py       # Holley .dl / .dlz binary decompression & parser
│   ├── agent_api.py            # FastAPI REST endpoints, WebSocket broker, auto-watch coordinator
│   ├── live_monitor.py         # Real-time CAN 2.0B listener & telemetry collector
│   ├── holley_usb.py           # Native WinUSB transport for official Holley 558-443 cable
│   ├── config.py               # Hardware profiles, vehicle specs, and baseline constants
│   ├── protocol.py             # 29-bit HEFI arbitration ID decoding & IEEE-754 float unpacking
│   └── static/                 # Streamlined Two-Panel Studio Web Assets
│       ├── index.html          # Studio interface layout
│       ├── style.css           # Modern dark-mode performance styling
│       └── dashboard.js        # WebSocket client, chat manager, VE heatmap renderer
│
├── docs/                       # Engineering Specifications & Protocols
│   ├── AI_ARCHITECTURE.md      # Grounded AI design, safety firewalls, prompt strategies
│   ├── ARCHITECTURE.md         # Full system architecture (this document)
│   ├── CAN_PROTOCOL.md         # Holley HEFI 29-bit CAN 2.0B broadcast specification
│   ├── DIAGNOSTICS.md          # Diagnostic rules, anomaly detection, and evidence chains
│   ├── FIELD_GUIDE_TUNING_LAPTOP.md # Tuning laptop connection & field workflow
│   ├── HARDWARE_SUPPORT.md     # USB-to-CAN adapter compatibility & setup
│   ├── PRODUCT.md              # Product requirements, vision, and philosophy
│   └── ROADMAP.md              # Project status and implementation milestones
│
└── tests/                      # Automated Test Suite (111 unit tests passing)
    ├── test_gemini_agent.py    # Unit tests for Gemini tools and offline fallback
    ├── test_tune_optimizer.py  # Unit tests for VE calculation, transient filter, and watcher
    ├── test_datalog_reader.py  # Unit tests for .dl/.dlz binary decoding
    └── test_protocol.py        # Unit tests for CAN unpacking and signal validation
```

---

## 3. Core Component Architectures

### 3.1 Grounded Gemini Agent Service (`holley_can/gemini_agent.py`)

The AI reasoning engine uses the official `google-genai` SDK targeting **Gemini 2.5 Flash** (default) or **Gemini 2.5 Pro**:

* **Safety Invariant:** The LLM is never given direct access to operating system sockets or CAN hardware.
* **Deterministic Function Calling:** All data is provided through four strictly declared tools:
  1. `get_vehicle_specs()`: Returns the validated 1980 Fairmont platform specifications:
     - GM 4.8L Iron-Block Gen III LS (LM7/LR4)
     - Elgin Sloppy Stage 2 Cam (228/230 @ .050", .585"/.585", 112 LSA)
     - VS Racing 78/75 cast turbocharger on Hooker BlackHeart manifold
     - 58.0 PSI mechanical base fuel rail pressure with 1:1 boost reference
     - Siemens Deka 80 lb/hr injectors, Continental Flex Fuel sensor
     - GM 4L80E transmission, Yank 3600 stall, Sloppy Transbrake staging
  2. `audit_fuel_system(session_id, min_map_kpa)`:
     Audits effective differential fuel pressure ($P_{\text{differential}} = P_{\text{fuel}} - P_{\text{boost}}$) across boost pull windows. Enforces the $58.0 \pm 3.0\text{ PSI}$ invariant.
  3. `get_ve_recommendations(session_id, apply_learn)`:
     Calculates cell-by-cell 16×16 VE correction matrix, steady-state sample counts, and rich/lean deltas.
  4. `analyze_datalog(file_path)`:
     Decompresses and extracts WOT performance metrics, boost ramp rates, AFR tracking, and knock retard events.

* **Offline Deterministic Fallback:**
  When no `GEMINI_API_KEY` is configured, `GeminiAgentService` gracefully falls back to deterministic rule analysis. The user receives complete, instant engineering audits without crashing or blocking.

### 3.2 16×16 VE Optimizer & Transient Filter (`holley_can/tune_optimizer.py`)

Automotive calibrations require high-purity steady-state data. Naive averaging of raw datalogs contaminates VE cells with transient accelerator pump shots and cold enrichment.

The optimizer executes the following pipeline:
1. **Transient Elimination:**
   - Calculates throttle derivative: $\frac{d\text{TPS}}{dt}$.
   - Discards all samples where $|\frac{d\text{TPS}}{dt}| > 25\% / \text{s}$.
2. **Thermal Lockout:**
   - Discards all samples where $\text{Coolant Temp} < 160^\circ\text{F}$.
3. **DFCO Rejection:**
   - Discards samples where throttle is closed ($\text{TPS} < 1\%$) while RPM remains elevated.
4. **Load Bin Mapping:**
   - Maps valid samples into the Holley 16×16 grid:
     - RPM Bins: `[800, 1200, 1600, 2000, 2400, 2800, 3200, 3600, 4000, 4500, 5000, 5500, 6000, 6500, 7000, 7500]`
     - MAP Bins: `[20, 30, 40, 50, 60, 70, 80, 90, 100, 120, 140, 160, 180, 200, 220, 240]` kPa.
5. **Learn Table Folding:**
   $$\text{VE}_{\text{Recommended}} = \text{VE}_{\text{Base}} \times \left(1.0 + \frac{\text{ClosedLoopLearn}_{\%}}{100}\right)$$
6. **Instant Export:**
   Outputs tab-delimited text to `COPY 16x16 VE TABLE (CTRL+V).txt` for direct paste into Holley software.

### 3.3 Zero-Touch AutoHandoffWatcher (`holley_can/tune_optimizer.py`)

To eliminate manual file picking during dyno sessions or track passes, `AutoHandoffWatcher` runs in an asynchronous background daemon thread:
- Checks file timestamps and hashes across:
  - `%USERPROFILE%\Documents\Holley\Terminator X V3\Data Logs\`
  - `%USERPROFILE%\OneDrive\Documents\Holley\Terminator X V3\Data Logs\`
  - `%USERPROFILE%\Documents\Holley\Terminator X V3\Global Files\`
  - `G:\My Drive\Holley\`
  - Removable SD cards / USB flash drives (`D:`, `E:`, `F:`, `G:`, `H:`)
- When a new file is written by Holley software (e.g. after a pull):
  1. Decompresses and parses the log within $50\text{ ms}$.
  2. Updates 16×16 VE table recommendations.
  3. Writes `COPY 16x16 VE TABLE (CTRL+V).txt`.
  4. Triggers automatic Gemini run audit.
  5. Broadcasts the update to the browser UI via WebSocket and triggers an audio chime.

### 3.4 Standalone Executable Packaging (`build_portable.py`)

To ensure flawless execution on the tuning laptop without requiring Python or administrative setup:
- PyInstaller compiles `portable_entry.py` into a single standalone `.exe` (`Holley_EFI_Copilot.exe`).
- Bundles:
  - Python 3.12 embedded interpreter
  - `fastapi`, `uvicorn`, `google-genai`, `python-multipart`
  - HTML/CSS/JS frontend assets into `sys._MEIPASS`
- Runtime path resolver:
  - Reads bundled static assets from `sys._MEIPASS`.
  - Writes outputs (`COPY 16x16 VE TABLE (CTRL+V).txt`, logs, config) to `sys.executable` directory.
- Double-clicking the `.exe` automatically spawns the background server, launches the default browser to `http://localhost:8000`, and activates the auto-watcher.

---

## 4. Hardware Transport Abstraction

The physical CAN layer retains multi-adapter support for users capturing live telemetry:

| Adapter | Backend Driver | Protocol | Status |
|:---|:---|:---|:---|
| **Holley 558-443 USB-CAN** | Native WinUSB (`holley_usb.py`) | HEFI 29-bit CAN 2.0B | `VERIFIED` |
| **PEAK PCAN-USB** | `python-can` (`pcan`) | 29-bit CAN 2.0B @ 1 Mbps | `VERIFIED` |
| **CANable / CANable Pro** | `python-can` (`slcan`) | 29-bit CAN 2.0B @ 1 Mbps | `VERIFIED` |
| **Virtual Simulator** | Pure Python generator | Injected anomaly profiles | `VERIFIED` |

---

## 5. Security & Safety Firewalls

1. **Read-Only Safety Invariant:** Under no circumstances does the application issue write packets, flash commands, or configuration overrides to the vehicle's ECU.
2. **API Key Isolation:** Gemini API keys are entered by the user in the browser and stored strictly in browser `localStorage`. They are never sent to external third parties or committed to version control.
3. **Local Loopback Only:** By default, the FastAPI server binds to `127.0.0.1:8000` to prevent unintended local network exposure.
