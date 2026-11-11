# Product Requirements & Philosophy — EFI Intelligence Copilot

**Target Platform:** Holley Terminator X & Terminator X MAX (with future EFI platform extensibility)  
**Status:** In Active Production / Field Testing  
**Last Updated:** November 2026

---

## 1. Product Mission & Vision

**EFI Intelligence Copilot** is an AI-powered calibration companion, diagnostic auditor, and decision-support layer designed specifically for aftermarket engine management systems—headlined by the Holley Terminator X and Terminator X MAX.

### Core Philosophy

> **Holley provides ECU control and raw data capture.**  
> **EFI Intelligence Copilot explains what the data means, optimizes 16×16 VE fuel tables, identifies mechanical and sensor anomalies, audits boost-referenced fuel systems, and acts as an expert calibration co-driver.**

The product is **NOT** a replacement for Holley EFI software, nor does it attempt to flash tunes directly into the ECU. Instead, it eliminates the bottleneck faced by grassroots racers and dyno tuners: **data richness paired with interpretation poverty**. Rather than squinting at squiggly datalog lines across hundreds of megabytes of binary logs, Copilot automatically extracts Wide-Open Throttle (WOT) pulls, verifies critical fuel rail pressure tracking, filters transient pedal noise, recalculates the entire 16×16 VE table, and generates plain-language, engineering-grounded explanations.

---

## 2. Core User Experience & Zero-Touch Workflow

The user experience centers on a fast, hands-free loop designed for the tuning laptop:

```
  ┌─────────────────────────┐
  │  1. Zero-Touch Auto-Run │  Double-click Holley_EFI_Copilot.exe on laptop.
  │     Background Watcher  │  Automatically monitors Holley Data Logs & tunes.
  └────────────┬────────────┘
               ▼
  ┌─────────────────────────┐
  │  2. Dyno Pull / Pass    │  Do your pull; Holley software saves .dl / .dlz log.
  │     Instant Acquisition │  Copilot detects the file in <1.5s.
  └────────────┬────────────┘
               ▼
  ┌─────────────────────────┐
  │  3. Transient Filtering │  Discards TPS tip-in/tip-out spikes (>25%/s) and
  │     & VE Optimization   │  cold coolant (<160°F). Folds Learn into 16×16 VE table.
  └────────────┬────────────┘
               ▼
  ┌─────────────────────────┐
  │  4. 1-Click Copy/Paste  │  Click "Copy 16×16 VE (Ctrl+V)" and paste directly
  │     into Holley Tune    │  into the Holley Terminator X Base Fuel Table.
  └────────────┬────────────┘
               ▼
  ┌─────────────────────────┐
  │  5. Gemini AI Audit     │  Gemini 2.5 reviews fuel system tracking (58 PSI rail delta),
  │     & Interactive Chat  │  boost ramp rate, and knock risk with grounded tools.
  └─────────────────────────┘
```

---

## 3. Strict Safety & Engineering Principles

These rules are mandatory, enforced by code architecture, and non-negotiable:

### Principle 1: Zero Calibration Writes (Read-Only Safety Invariant)
* The software is **strictly read-only** with respect to vehicle hardware, CAN bus communication, and ECU firmware.
* Autonomous CAN write packets, tune flashing, or EEPROM modification are strictly forbidden.
* Calibration changes are applied safely by the user via copy-paste into official Holley software.

### Principle 2: Deterministic Foundation First, AI Interpretation Second
* The AI layer does **not** hallucinate sensor values or guess calibrations.
* Pipeline architecture:
  $$\text{Datalog / CAN} \rightarrow \text{Deterministic Filtering} \rightarrow \text{Mathematical VE Calculation} \rightarrow \text{Grounded Tools} \rightarrow \text{Gemini AI Commentary}$$
* The Gemini LLM accesses data exclusively through deterministic inspection tools (`get_vehicle_specs`, `audit_fuel_system`, `get_ve_recommendations`, `analyze_datalog`).
* When no API key is provided, the application continues to run seamlessly using its built-in rule engine.

### Principle 3: Absolute Distinction Between Observation and Inference
* The studio UI strictly separates and labels:
  - **Observed Data:** Exact measured values, units, and timestamps.
  - **Calculated Metrics:** Fuel rail delta pressure ($P_{\text{fuel}} - P_{\text{boost}}$), AFR error percentage, rate of TPS change.
  - **Inferred Condition:** Diagnostic findings (e.g. "Fuel Pump Capacity Exhausted", "False Knock Event").
  - **Action Items:** Practical mechanical checks before modifying ignition or fuel tables.

---

## 4. Feature Matrix

### Feature A: Streamlined Two-Panel Tuning & Explanation Studio
* **Left Panel (Gemini AI Calibration Co-Driver):**
  - Conversational interface powered by Google Gemini 2.5 (`google-genai` SDK).
  - Quick-prompt diagnostic chips: "Audit Fuel System", "Optimize 16×16 VE Table", "WOT Health Check", "Detect Knock & Timing Retard".
  - Interactive file dropzone supporting drag-and-drop `.dl`, `.dlz`, `.terx`, and `.hefi` files.
  - Browser-side audio alert when new datalogs are processed.
* **Right Panel (16×16 VE Heatmap Table & Scorecard):**
  - Color-coded VE correction heatmap (rich vs lean deltas).
  - Cell-by-cell steady-state sample count display.
  - Toggle to fold Holley Closed-Loop Learn table directly into VE Base.
  - **1-Click "Copy 16×16 VE (Ctrl+V)" button**: Formats the entire 16×16 matrix into tab-delimited text ready for instant paste into Holley software.
  - WOT Performance Scorecard banner with peak boost, AFR tracking, and fuel safety indices.

### Feature B: Zero-Touch Auto-Pilot File Watcher
* Background thread (`AutoHandoffWatcher`) polling every 1.5 seconds across:
  - `%USERPROFILE%\Documents\Holley\Terminator X V3\Data Logs\`
  - `%USERPROFILE%\OneDrive\Documents\Holley\Terminator X V3\Data Logs\`
  - `%USERPROFILE%\Documents\Holley\Terminator X V3\Global Files\`
  - `G:\My Drive\Holley\`
  - Removable USB drives and SD cards (`D:`, `E:`, `F:`, `G:`, `H:`)
* Automatically parses new logs, updates the studio over WebSockets, and writes `COPY 16x16 VE TABLE (CTRL+V).txt` right next to the executable.

### Feature C: Binary Datalog Parser (`.dl` and `.dlz`)
* Native decompression and parsing of Holley binary log formats:
  - Terminator X V3 (2,512-byte headers).
  - Holley EFI V6 (4,120-byte headers).
* Full channel extraction: RPM, MAP, TPS, Target AFR, Measured AFR, Closed-Loop Compensation, Learn Status, Fuel Pressure, Coolant Temp, MAT/IAT, Ignition Timing, Knock Retard, Battery Voltage.

### Feature D: Deterministic 16×16 VE Optimizer
* Maps raw datalog samples into standard 16×16 Holley RPM vs MAP load bins.
* Transient rejection filter:
  - Discards samples where $|d\text{TPS}/dt| > 25\%/\text{s}$ (accelerator pump transients).
  - Discards samples where $\text{ECT} < 160^\circ\text{F}$ (cold enrichment warm-up).
  - Discards deceleration fuel cut-off (DFCO) events.
* Computes weighted cellular corrections with sample confidence thresholds.

### Feature E: Fuel System Differential Pressure Audit
* Enforces the critical 58 PSI boost-referenced rail pressure invariant:
  $$P_{\text{differential}} = P_{\text{fuel}} - P_{\text{boost}} \approx 58.0 \pm 3.0\text{ PSI}$$
* Identifies fuel pump capacity exhaustion, clogged fuel filters, and kinked reference lines before engine damage occurs.

### Feature F: Single Standalone Executable (`Holley_EFI_Copilot.exe`)
* Bundles Python runtime, FastAPI backend, Uvicorn server, Gemini SDK, and responsive web assets into a single portable `.exe` (~35 MB).
* Zero dependencies, zero installation, and zero configuration on the tuning laptop.

---

## 5. Non-Goals

1. **Autonomous ECU Flashing:** The software will never write binary files or calibration tables directly over CAN to the ECU.
2. **Proprietary Hardware Lock-In:** Operates with native Holley USB-to-CAN cables (558-443), standard USB-CAN dongles (PEAK, CANable), or purely from saved log files without any CAN hardware.
3. **Gauge Cluster Duplication:** Does not attempt to replace primary in-dash physical or digital cluster displays; focused entirely on calibration intelligence and diagnostic decision-support.
