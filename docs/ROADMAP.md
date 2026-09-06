# Product Roadmap & Phased Implementation Plan

**Product:** EFI Intelligence Copilot  
**Status:** In Active Development  
**Current Milestone:** Phase 0 (Docs & Skeleton) & Phase 1 (HAL & Simulator)

---

## 1. Release Schedule & Status Taxonomy

To guarantee that software and simulation success is never confused with live ECU hardware compatibility, components and capabilities are categorized according to the explicit audit taxonomy:

* **`SIMULATED`**: Functionality implemented and validated within the virtual simulator adapter.
* **`FIXTURE_VERIFIED`**: Validated by automated unit tests against synthetic replay data fixtures.
* **`SOURCE_VERIFIED`**: Confirmed by published third-party integration specifications (e.g. RealDash XML, CANformance Wiki, Racepak broadcast guides).
* **`HOLLEY_SOURCE_VERIFIED`**: Directly confirmed by official Holley documentation or vendor DBC files.
* **`LIVE_HARDWARE_VERIFIED`**: Empirically validated with physical bus traces on a running Terminator X / X MAX ECU.
* **`ASSUMED`**: Architecture accommodates this assumption, but empirical verification is pending.
* **`UNKNOWN`**: Unverified, speculative, or unmapped protocol detail (`NEEDS VERIFIED SOURCE`).
* **`BLOCKED`**: Intentionally prohibited (e.g. calibration writes) or blocked pending external physical access.
* **`IMPLEMENTED`**: Code is written, reviewed, and present in the codebase.
* **`FUTURE`**: Formally scheduled for a future milestone; out of current scope.

---

## 2. Phase-by-Phase Roadmap

```
Phase 0 ──► Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4 ──► Phase 5 ──► Phase 6
Skeleton    HAL/Sim     Protocol    Dashboard   Storage     Baseline    Events
                                                                          │
Phase 12 ◄─ Phase 11 ◄─ Phase 10 ◄─ Phase 9  ◄─ Phase 8  ◄─ Phase 7 ◄─────┘
Tune Intel  Reporting   History     Ask Engine  AI Reason   Diagnostics
```

---

### Phase 0: Project Skeleton & Documentation Foundation
* **Status:** `IMPLEMENTED` / `VERIFIED`
* **Deliverables:**
  - Standardized directory layout under `app/`.
  - Comprehensive specification suite in `/docs` (`PRODUCT.md`, `ARCHITECTURE.md`, `CAN_PROTOCOL.md`, `TELEMETRY_SCHEMA.md`, `DIAGNOSTICS.md`, `AI_ARCHITECTURE.md`, `TEST_PLAN.md`, `ROADMAP.md`, `SECURITY.md`, `HARDWARE_SUPPORT.md`).
  - Strict read-only and LLM safety invariants established.

---

### Phase 1: Hardware Abstraction Layer & Telemetry Simulator
* **Status:** `IN PROGRESS`
* **Deliverables:**
  - `HardwareInterface` Protocol definition.
  - `VirtualSimulatorAdapter` supporting 8 deterministic operational profiles with injected anomalies.
  - `UsbCanAdapter` and `SocketCanAdapter` implementations.
  - Unit tests for hardware lifecycle, auto-reconnect, and frame generation.

---

### Phase 2: Protocol Layer & Telemetry Normalization
* **Status:** `SCHEDULED`
* **Deliverables:**
  - Standardized `RawCANFrame` and `TelemetrySignal` dataclasses.
  - Dynamic channel registry and unverified channel observer.
  - Real-time `SignalQuality` assessment (`VALID`, `STALE`, `MISSING`, `OUT_OF_RANGE`, `INVALID`, `SIMULATED`).
  - Derived calculations (boost psi, manifold vacuum inHg, AFR error %, injector duty cycle %).

---

### Phase 3: Live Telemetry Dashboard
* **Status:** `SCHEDULED`
* **Deliverables:**
  - High-frequency live streaming via WebSockets ($20\,\text{Hz}$).
  - Configurable gauges with color-coded warning bands (RPM, MAP, AFR, Timing, Coolant, Voltage).
  - Real-time connection status and signal quality indicators.

---

### Phase 4: Session Recorder & High-Throughput Storage
* **Status:** `SCHEDULED`
* **Deliverables:**
  - SQLite WAL-mode streaming time-series storage.
  - Metadata schema: vehicle profile, session type, weather, tune ID, notes.
  - Chunked stream buffer guaranteeing zero frame drops during multi-hour logging.

---

### Phase 5: Vehicle Baseline Engine
* **Status:** `SCHEDULED`
* **Deliverables:**
  - Multi-dimensional operating bins (RPM $\times$ MAP $\times$ CLT).
  - Robust non-parametric statistics (Median, IQR, 5th/95th percentiles).
  - Persistent baseline models across multiple driving sessions.

---

### Phase 6: Deterministic Event Detection Engine
* **Status:** `SCHEDULED`
* **Deliverables:**
  - Discrete state machines: Engine Start, Stop, Idle, Cruise, Accel, Decel, WOT Pull.
  - Anomaly event triggers: Thermal runaway, voltage sag, sensor dropout.
  - Emits typed `EngineEvent` objects with auditable evidence payloads.

---

### Phase 7: Rule-Based Diagnostic Engine
* **Status:** `SCHEDULED`
* **Deliverables:**
  - High-load fueling deviation rule (`DIAG_FUEL_HIGH_LOAD_DEV`).
  - Idle RPM hunting rule (`DIAG_IDLE_RPM_HUNTING`).
  - Sensor dropout & implausibility rules (`DIAG_SENSOR_DROPOUT`, `DIAG_SENSOR_IMPLAUSIBLE`).
  - Data validity scoring per finding.

---

### Phase 8: AI Interpretation Layer
* **Status:** `SCHEDULED`
* **Deliverables:**
  - Provider-agnostic LLM interface (Gemini, Claude, OpenAI, Local Ollama).
  - Structured findings intake parser.
  - Strictly grounded natural-language explanation and recommendation prompts.

---

### Phase 9: "Ask Your Engine" Conversational Copilot
* **Status:** `SCHEDULED`
* **Deliverables:**
  - Deterministic tool registry for natural language queries.
  - Replay session comparison via conversational prompts.
  - Hallucination prevention guards.

---

### Phase 10: Vehicle Profile & Modification History
* **Status:** `SCHEDULED`
* **Deliverables:**
  - Permanent vehicle spec sheet (engine, injectors, sensors, fuel octane).
  - Modification timeline correlating dates with baseline telemetry shifts.
  - Correlation vs causation linguistic safety guards.

---

### Phase 11: Professional Report Generation
* **Status:** `SCHEDULED`
* **Deliverables:**
  - Comprehensive health report builder (Overall score, Fueling, Idle, Sensors, Thermal, Electrical).
  - Export to Markdown, HTML, and PDF formats.

---

### Phase 12: Tune / Calibration Intelligence
* **Status:** `FUTURE`
* **Deliverables:**
  - Calibration table correlation (read-only VE and Spark table cell overlay).
  - Suggested calibration review cells (zero automatic writes).
