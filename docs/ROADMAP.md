# Product Roadmap & Implementation Milestones

**Product:** EFI Intelligence Copilot  
**Status:** In Active Production / Field Testing  
**Current Milestone:** Phase 9 (In-Vehicle Field Testing on 1980 Fairmont Platform)  
**Last Updated:** November 2026

---

## 1. Status Taxonomy

Capabilities and milestones are tracked according to our verification taxonomy:

* **`IMPLEMENTED`**: Code is written, reviewed, tested, and present in repository.
* **`FIXTURE_VERIFIED`**: Validated by automated unit tests against synthetic and real binary fixtures.
* **`HARDWARE_VERIFIED`**: Empirically validated with physical bus traces or official cables (e.g. Holley 558-443).
* **`IN_PROGRESS`**: Under active implementation or real-world field testing.
* **`FUTURE`**: Formally scheduled for subsequent release cycles.

---

## 2. Milestone Progress Overview

```
Phase 0 ──► Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4 ──► Phase 5
Docs        HAL/USB     Protocol    Datalog     VE Engine   Gemini AI
  [✓]         [✓]         [✓]         [✓]         [✓]         [✓]
                                                               │
Phase 9 ◄── Phase 8 ◄── Phase 7 ◄── Phase 6 ◄─────────────────┘
Vehicle     Packaging   Auto-Watch  Studio UI
 [ACTIVE]     [✓]         [✓]         [✓]
```

---

## 3. Completed Phases

### Phase 0: Project Architecture & Safety Foundation
* **Status:** `IMPLEMENTED` / `FIXTURE_VERIFIED`
* **Deliverables:**
  - Decoupled modular architecture under `holley_can/`.
  - Comprehensive specification documents (`PRODUCT.md`, `ARCHITECTURE.md`, `CAN_PROTOCOL.md`, `AI_ARCHITECTURE.md`, `FIELD_GUIDE_TUNING_LAPTOP.md`).
  - Strict read-only safety invariant enforced (no CAN write packets or autonomous ECU flashing).

### Phase 1: Hardware Abstraction & Transport Layer
* **Status:** `IMPLEMENTED` / `HARDWARE_VERIFIED`
* **Deliverables:**
  - `HolleyUsbTransport`: Native WinUSB communication for official Holley 558-443 cable (no PEAK drivers needed).
  - Cross-platform `python-can` support: PEAK PCAN-USB and CANable (SLCAN).
  - Virtual CAN Simulator with 8 deterministic operational profiles.
  - Multi-adapter auto-detection and hardware preflight utility (`4_PREFLIGHT_HARDWARE_CHECK.bat`).

### Phase 2: Protocol Layer & Telemetry Normalization
* **Status:** `IMPLEMENTED` / `FIXTURE_VERIFIED`
* **Deliverables:**
  - 29-bit extended CAN ID de-multiplexer and IEEE 754 big-endian float unpacker.
  - Signal validation pipeline (`VALID`, `STALE`, `OUT_OF_RANGE`, `INVALID`, `SIMULATED`).
  - Derived metric computation: boost psi, AFR error %, fuel rail differential pressure ($P_{\text{fuel}} - P_{\text{boost}}$).

### Phase 3: Binary Datalog Parser (`.dl` and `.dlz`)
* **Status:** `IMPLEMENTED` / `FIXTURE_VERIFIED`
* **Deliverables:**
  - Pure Python decompression and binary struct parser for Holley datalogs:
    - Terminator X V3 (2,512-byte header format).
    - Holley EFI V6 (4,120-byte header format).
  - High-speed slice extraction for WOT acceleration windows, idle stability, and thermal events.

### Phase 4: Deterministic 16×16 VE Optimizer & Transient Filter
* **Status:** `IMPLEMENTED` / `FIXTURE_VERIFIED`
* **Deliverables:**
  - Transient rejection filter:
    - Rejects samples where $|d\text{TPS}/dt| > 25\%/\text{s}$ (accelerator pump transients).
    - Rejects samples where $\text{ECT} < 160^\circ\text{F}$ (cold warm-up).
    - Rejects deceleration fuel cut-off (DFCO) conditions.
  - RPM vs MAP 16×16 load bin mapping matching Holley Terminator X tables.
  - Closed-loop Learn table folding into VE Base.
  - 1-click clipboard formatting: generates tab-delimited text ready for instant `Ctrl+V` into Holley software.

### Phase 5: Grounded Gemini 2.5 Agent Integration
* **Status:** `IMPLEMENTED` / `FIXTURE_VERIFIED`
* **Deliverables:**
  - Official Google `google-genai` SDK integration supporting Gemini 2.5 Flash and Pro.
  - Deterministic tool declarations with parameter schemas:
    - `get_vehicle_specs`: Vehicle invariants for 1980 Fairmont (4.8L LS, Sloppy Stage 2, 78/75 turbo, 4L80E).
    - `audit_fuel_system`: Boost-referenced fuel rail pressure ($58.0 \pm 3.0\text{ PSI}$) tracking check.
    - `get_ve_recommendations`: 16×16 cell-by-cell rich/lean delta matrix and sample counts.
    - `analyze_datalog`: In-depth datalog decompression and performance summary.
  - Offline deterministic fallback engine when no API key is provided.

### Phase 6: Streamlined Two-Panel Studio UI
* **Status:** `IMPLEMENTED` / `FIXTURE_VERIFIED`
* **Deliverables:**
  - Streamlined, high-contrast dark-mode interface:
    - Left Panel: Gemini AI Calibration Co-Driver, quick prompt chips, file dropzone, audio alert notifications, and API key management modal.
    - Right Panel: 16×16 VE Heatmap Table, Fold Learn toggle, cell sample counts, WOT Scorecard banner, and 1-Click "Copy 16×16 VE (Ctrl+V)" button.
  - High-frequency WebSocket communication for instant UI updates.

### Phase 7: Zero-Touch Auto-Pilot File Watcher
* **Status:** `IMPLEMENTED` / `FIXTURE_VERIFIED`
* **Deliverables:**
  - Background daemon thread (`AutoHandoffWatcher`) scanning every 1.5 seconds.
  - Automatically watches default Holley directories:
    - `%USERPROFILE%\Documents\Holley\Terminator X V3\Data Logs\`
    - `%USERPROFILE%\OneDrive\Documents\Holley\Terminator X V3\Data Logs\`
    - `%USERPROFILE%\Documents\Holley\Terminator X V3\Global Files\`
    - `G:\My Drive\Holley\`
    - Connected USB flash drives / SD cards (`D:`, `E:`, `F:`, `G:`, `H:`).
  - Hands-free processing: automatically parses new files, updates VE tables, triggers Gemini run audit, and chimes alert.

### Phase 8: Standalone Portable Single Binary Distribution
* **Status:** `IMPLEMENTED` / `FIXTURE_VERIFIED`
* **Deliverables:**
  - PyInstaller `--onefile` packaging script (`build_portable.py`).
  - Standalone `Holley_EFI_Copilot.exe` (~35 MB) bundling Python 3.12, FastAPI, Uvicorn, Gemini SDK, and static web assets.
  - Automatic browser launch on double-click; zero installation or command-line execution required on the tuning laptop.

---

## 4. Active Milestone

### Phase 9: In-Vehicle Field Validation on 1980 Fairmont Platform
* **Status:** `IN PROGRESS`
* **Target Vehicle:** 1980 Ford Fairmont 4-Door "Boxtop" (GM 4.8L LS, Sloppy S2 Cam, VS Racing 78/75, 4L80E, 58 PSI boost-referenced fuel rail, Siemens Deka 80s).
* **Deliverables:**
  - [x] Preflight USB-to-CAN hardware verification with official Holley 558-443 cable.
  - [x] Baseline dyno/street log capture and binary `.dlz` validation.
  - [x] Zero-touch auto-pilot file watcher validation on tuning laptop.
  - [ ] Live track pass datalog capture and transbrake launch evaluation.
  - [ ] Long-term learn table convergence audit across multiple ambient weather conditions.

---

## 5. Future Roadmap

### Phase 10: Multi-ECU Platform Expansion
* Extend binary datalog parsers and CAN broadcast decoders to:
  - Holley Dominator / HP EFI
  - Haltech Elite / Nexus
  - FuelTech FT550 / FT600
  - Megasquirt / MS3Pro

### Phase 11: Real-Time Audio Voice Assistant
* Voice synthesis and voice recognition for hands-free audio telemetry coaching during dyno pulls or track staging.
