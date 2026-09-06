# Product Requirements & Philosophy — EFI Intelligence Copilot

**Target Platform:** Holley Terminator X & Terminator X MAX (with future EFI platform extensibility)  
**Status:** In Development (Phase 0 / Phase 1)  
**Last Updated:** September 2026

---

## 1. Product Mission & Vision

**EFI Intelligence Copilot** is an intelligence, diagnostics, and decision-support layer that operates alongside aftermarket engine management systems—beginning with the Holley Terminator X and Terminator X MAX.

### Core Philosophy

> **Holley provides ECU control and raw information.**  
> **EFI Intelligence Copilot explains what the data means, identifies anomalies, establishes a vehicle-specific baseline, and recommends what the user should investigate or optimize.**

The product is **NOT** a replacement for Holley EFI software, nor does it seek to duplicate Holley's proprietary calibration suite. Instead, it solves the fundamental problem faced by enthusiasts, amateur tuners, and racers: **data richness paired with interpretation poverty**. While a user can capture hundreds of megabytes of raw sensor values, extracting actionable insights requires hours of manual cross-referencing, deep domain knowledge, and subjective guesswork.

EFI Intelligence Copilot acts as a senior automotive diagnostics engineer sitting in the passenger seat: observing patterns, comparing telemetry against historical baselines, explaining why deviations occur, and suggesting high-value, evidence-backed tests.

---

## 2. Core User Experience & Workflow

The user journey follows a 9-stage closed-loop workflow:

```
CONNECT ──► IDENTIFY ──► MONITOR ──► RECORD ──► ANALYZE ──► EXPLAIN ──► RECOMMEND ──► COMPARE ──► LEARN
```

### High-Level Stage Descriptions

1. **CONNECT:** User plugs in a supported USB-CAN adapter (or connects to network/simulated source). The interface initializes cleanly without manual driver wrangling.
2. **IDENTIFY:** The system verifies bus connectivity, reads broadcast headers, extracts the ECU serial number, and verifies device health.
3. **MONITOR:** Displays live engine status through a clean, modern dashboard highlighting health indices (Fueling, Idle, Thermal, Electrical, Sensors).
4. **RECORD:** High-throughput, deterministic session logger stores every valid telemetry sample, detected event, and ambient condition without frame drops.
5. **ANALYZE:** The deterministic analytical engine scans the session against vehicle baselines and operating conditions.
6. **EXPLAIN:** Structured diagnostic findings are translated into clear, plain-language engineering explanations.
7. **RECOMMEND:** The system proposes prioritized, actionable next steps (e.g. physical mechanical inspections vs calibration review).
8. **COMPARE:** Quantifies differences between runs (before vs after a cam swap, intake upgrade, or tune tweak).
9. **LEARN:** Continuously refines vehicle-specific baselines (normal operating temperatures, idle vacuum, cruise fuel trims).

---

## 3. Strict Safety & Engineering Principles

These rules are mandatory, enforced by code architecture, and non-negotiable across all development phases:

### Principle 1: Zero Calibration Writes in MVP (Read-Only Safety)
* The MVP release is **strictly read-only** with respect to engine calibration and ECU memory.
* Autonomous tune modification is strictly forbidden.
* Calibration flash commands, EEPROM write packets, or proprietary write handshakes will not be implemented or executed.

### Principle 2: Protocol Veracity (Never Invent ECU Protocols)
* Never fabricate CAN IDs, payload bit alignments, scaling factors, or endian formats.
* If a protocol detail is not verified by official vendor documentation, community reverse-engineering with capture validation, or physical test verification, it MUST be tagged:
  `UNKNOWN / NEEDS VERIFIED SOURCE`
* All channel mappings and protocol definitions are configuration-driven and replaceable.

### Principle 3: Strict LLM Isolation (AI Is Reasoning, Not Control)
* The Large Language Model (LLM) has **zero connection** to the physical CAN bus, hardware sockets, or ECU memory.
* Pipeline architecture:
  $$\text{Raw CAN} \rightarrow \text{Validated Telemetry} \rightarrow \text{Deterministic Events/Diagnostics} \rightarrow \text{Structured Findings} \rightarrow \text{AI Interpretation} \rightarrow \text{Human Recommendation}$$
* The AI is an explanation layer that receives structured JSON findings and calls deterministic query tools. It cannot invent data or make safety-critical decisions autonomously.

### Principle 4: Absolute Distinction Between Observation and Inference
* The application strictly separates and labels:
  - **Observed Data:** Exact measured values, units, and timestamps.
  - **Calculated Metrics:** Mathematical derivatives (e.g. AFR error percentage, rate of temperature rise).
  - **Inferred Condition:** Diagnostic hypothesis derived from deterministic rules.
  - **Possible Causes:** Ranked mechanical or calibration possibilities.
  - **Confidence Score:** Numerical metric ($0.0$ to $1.0$) based on sample count, repeatability, and data validity.
  - **Recommended Next Test:** Practical diagnostic step to confirm or refute the hypothesis before altering calibration.

---

## 4. MVP Feature Scope

### Feature A: Hardware Connection & Transport Abstraction
* Automatic USB-CAN adapter detection.
* Connection lifecycle management: Disconnected, Connecting, Active, Degraded, BusOff, Reconnecting.
* Graceful hot-unplug and automatic reconnect.
* CAN bus error monitoring and frame drop rate tracking.

### Feature B: Telemetry Acquisition & Protocol Engine
* Decodes Holley HEFI 29-bit broadcast protocol frames at 1 Mbit/s.
* Extracts ECU serial number and dynamic channel indices.
* Unpacks 8-byte big-endian IEEE 754 float payloads (`Value A` and `Value B`).
* Real-time signal validation and quality classification (`VALID`, `STALE`, `MISSING`, `OUT_OF_RANGE`, `INVALID`, `SIMULATED`).

### Feature C: Time-Series Session Logger
* SQLite WAL-mode streaming storage with low memory overhead.
* Rich metadata schema: vehicle profile, session type (Cold Start, Idle, Cruise, WOT, Dyno, Troubleshooting), driver notes, environmental context.
* Zero data loss on unexpected shutdown or abrupt disconnection.

### Feature D: Interactive Telemetry Replay
* Time-scrubbing synchronized charts.
* Event markers and diagnostic anomaly highlighting.
* Configurable multi-signal overlays (e.g. RPM vs MAP vs Target AFR vs Measured AFR vs Fuel Learn).
* CSV and JSON data export.

### Feature E: Vehicle Baseline Engine
* Context-aware statistical modeling across operating bins (RPM, MAP, TPS, Coolant Temp).
* Robust non-parametric metrics (Median, Interquartile Range, 5th/95th percentiles) rather than naive averages.
* Dynamic baseline learning across multiple sessions.

### Feature F: Deterministic Event Detection
* Discrete state identification: Engine Crank, Idle, Cruise, Rapid Acceleration, Deceleration, Wide Open Throttle (WOT), Thermal Spike, Low Voltage, Sensor Dropout.
* Structured event objects containing start/end timestamps, peak values, and evidence signals.

### Feature G: Deterministic Diagnostic Engine
* Initial high-confidence diagnostic rules:
  1. High-load fueling deviation (lean/rich drift under boost/WOT).
  2. Idle RPM hunting and closed-loop oscillation.
  3. Sensor dropout / implausible sensor relationships (e.g. high MAP with zero TPS).
  4. Charging system instability / low voltage.
  5. Coolant and Intake Air Temperature (IAT) anomalies.
* Explicit evidence chaining with sample validity metrics.

### Feature H: AI Reasoning Layer & "Ask Your Engine"
* Structured JSON findings fed to an LLM provider abstraction.
* Tool-driven conversational query engine: retrieves exact telemetry, compares runs, and explains findings.
* Strictly prevents hallucination of telemetry values.

### Feature I: Professional Reporting
* Comprehensive health report generation (HTML/Markdown/PDF export).
* Domain-specific sub-scores (Fueling, Idle, Sensors, Thermal, Electrical) and prioritized diagnostic action items.

### Feature J: Comprehensive Telemetry Simulator
* Mandatory virtual adapter enabling offline development, CI/CD testing, and demonstration.
* 8 deterministic operational profiles with injected anomalies (idle hunting, lean pull, thermal runaway, sensor dropout).

---

## 5. Non-Goals for MVP

1. **ECU Calibration Writing:** No binary flash routines, table updates, or tune modifications.
2. **Autonomous Closed-Loop Tuning:** No automatic modification of fuel or ignition maps.
3. **Hardware Proprietary Lock-In:** The software must never rely on a single vendor's USB dongle or operating system.
4. **Generic OBD-II Dongle Replacement:** The initial focus is deep aftermarket EFI telemetry via CAN 2.0B, not generic OBD-II PID polling.
