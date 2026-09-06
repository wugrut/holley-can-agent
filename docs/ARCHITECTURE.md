# System Architecture — EFI Intelligence Copilot

**System:** EFI Intelligence Copilot  
**Version:** 1.0.0-draft  
**Architecture Style:** Layered, Event-Driven, Decoupled Modular Architecture  
**Primary Target:** Holley Terminator X / Terminator X MAX (Agnostic Multi-ECU Core)

---

## 1. Architectural Philosophy

EFI Intelligence Copilot separates low-level physical transport, protocol-specific decoding, normalized telemetry storage, deterministic analytics, and AI reasoning into strict, non-leaky tiers:

```
[ PHYSICAL / TRANSPORT LAYER ]
   │ CAN 2.0B Frames (1 Mbit/s)
   ▼
[ PROTOCOL DECODING TIER ]
   │ Verified Bitfield De-muxing & IEEE 754 Conversion
   ▼
[ TELEMETRY NORMALIZATION TIER ]
   │ Unit Harmonization & Signal Quality Assessment (VALID, STALE, etc.)
   ▼
[ PERSISTENCE & SESSION TIER ]
   │ High-Throughput SQLite WAL Storage
   ▼
[ DETERMINISTIC ANALYTICS TIER ]
   ├── Vehicle Baseline Engine (Multi-dimensional Binned Non-parametric Models)
   ├── Event Detection Engine (Finite State Machines: Idle, Cruise, WOT, etc.)
   └── Diagnostic Engine (Rule-based Evaluator with Evidence Chains)
   │
   ▼ Structured Findings (JSON Contracts)
[ AI INTERPRETATION & REASONING TIER ]
   ├── Deterministic Tool Execution Engine
   └── Conversational "Ask Your Engine" Copilot
```

---

## 2. Directory & Package Structure

The codebase is organized under `app/`, ensuring complete decoupling between modules:

```text
/app
├── __init__.py
├── hardware/              # Hardware Abstraction Layer (HAL)
│   ├── __init__.py
│   ├── interface.py       # HardwareInterface Protocol & ConnectionState
│   ├── simulator.py       # Deterministic multi-scenario CAN simulator
│   ├── socketcan.py       # Linux SocketCAN adapter implementation
│   ├── usb_can.py         # Cross-platform python-can hardware adapter
│   └── detection.py       # USB device discovery and port scanning
│
├── can/                   # CAN Data Layer
│   ├── __init__.py
│   ├── frame.py           # RawCANFrame dataclass and timestamp primitives
│   ├── receiver.py        # Async frame receiver with backpressure queue
│   └── filter.py          # Software & hardware mask/filter configurations
│
├── protocol/              # Protocol Decoding Layer
│   ├── __init__.py
│   ├── hefi.py            # Holley HEFI 29-bit protocol unpacker
│   ├── registry.py        # Channel definitions and dynamic unknown handler
│   └── base.py            # ProtocolDecoder abstract interface
│
├── telemetry/             # Normalized Telemetry Model
│   ├── __init__.py
│   ├── quality.py         # SignalQuality enum & quality grading rules
│   ├── signals.py         # TelemetrySignal dataclass
│   ├── sample.py          # NormalizedTelemetrySample container
│   └── validator.py       # Range, rate-of-change, and staleness validation
│
├── storage/               # Persistent Storage Engine
│   ├── __init__.py
│   ├── database.py        # SQLite connection manager with WAL mode
│   ├── schema.py          # Table definitions, migrations, indexes
│   └── repository.py      # High-performance batch insertion and queries
│
├── sessions/              # Session Management
│   ├── __init__.py
│   ├── manager.py         # Session lifecycle (Start, Record, Stop, Export)
│   └── metadata.py        # Vehicle state, tune revision, ambient weather
│
├── baseline/              # Vehicle Baseline Engine
│   ├── __init__.py
│   ├── bins.py            # Multidimensional operating bins (RPM, MAP, CLT)
│   ├── model.py           # Statistical metrics (median, IQR, quantiles)
│   └── engine.py          # Baseline learner & deviation calculator
│
├── events/                # Deterministic Event Detection
│   ├── __init__.py
│   ├── detector.py        # Event detector pipeline & state machine
│   ├── types.py           # EventType enum & EngineEvent dataclass
│   └── rules/             # Discrete event rules (WOT, idle, thermal, etc.)
│
├── diagnostics/           # Rule-Based Diagnostic Engine
│   ├── __init__.py
│   ├── engine.py          # Diagnostic evaluator
│   ├── finding.py         # StructuredDiagnostic contract
│   └── rules/             # Deterministic rules (fueling, idle, sensors, etc.)
│
├── analytics/             # Time-Series Analytics & Comparisons
│   ├── __init__.py
│   ├── metrics.py         # Calculated metrics (boost, slip, duty cycle)
│   └── compare.py         # Session-to-session comparative algorithms
│
├── ai/                    # AI Interpretation Layer
│   ├── __init__.py
│   ├── provider.py        # Agnostic LLM interface (Gemini, Claude, Local)
│   ├── tools.py           # Deterministic data retrieval tool registry
│   ├── prompts.py         # Strict grounding and evidence attribution prompts
│   └── copilot.py         # "Ask Your Engine" orchestrator
│
├── vehicle/               # Vehicle Profile & History
│   ├── __init__.py
│   ├── profile.py         # Engine specs, sensor config, injector data
│   └── history.py         # Modification timeline & correlation engine
│
├── reports/               # Report Generation
│   ├── __init__.py
│   ├── generator.py       # Report builder & scoring calculator
│   └── templates/         # Markdown, HTML, and text templates
│
└── ui/                    # User Interface Interfaces
    ├── __init__.py
    ├── api.py             # FastAPI REST & WebSocket endpoints
    └── dashboard/         # Static web assets & telemetry visualizers
```

---

## 3. Component Details & Interface Contracts

### 3.1 Hardware Abstraction Layer (HAL)

To guarantee that the application is never locked to a single USB dongle or operating system, all communication goes through the `HardwareInterface` Protocol:

```python
class HardwareInterface(Protocol):
    async def connect(self) -> bool: ...
    async def disconnect(self) -> None: ...
    async def receive(self, timeout: float = 1.0) -> Optional[RawCANFrame]: ...
    def is_connected(self) -> bool: ...
    def get_status(self) -> ConnectionStatus: ...
```

#### Implementations:
1. **`VirtualSimulatorAdapter`:** Generates high-fidelity, deterministic CAN frames at configurable clock rates without real hardware. Supports 8 discrete operational profiles with injected faults.
2. **`UsbCanAdapter`:** Cross-platform interface leveraging `python-can` backends (PCAN, Kvaser, SLCAN/CANable, Vector, USB2CAN).
3. **`SocketCanAdapter`:** Native Linux SocketCAN driver (`can0`) utilizing C-level socket multiplexing with kernel buffering.

### 3.2 Protocol & Decoding Tier

The protocol layer decodes raw binary frames into typed telemetry signals without modifying application state:

```text
RawCANFrame
├── timestamp: float (UNIX epoch seconds with microsecond resolution)
├── channel: str (e.g. "can0", "virtual", "usb")
├── arbitration_id: int (29-bit extended ID)
├── dlc: int (8 bytes)
└── data: bytes
```

Decoding is executed by `HefiProtocolDecoder`:
- Mask: `can_id & 0x1FFFF800`
- Channel Index: `(can_id >> 14) & 0x7FF`
- ECU Serial: `can_id & 0x7FF`
- Payload Unpack: `struct.unpack(">ff", data)` yields `(Value A, Value B)`

If a channel index is encountered that is not present in the verified configuration map, it is forwarded to `UnknownChannelHandler`, which logs the frame to an observation registry without dropping or halting the pipeline.

### 3.3 Normalized Telemetry Model

All decoded signals are converted to `TelemetrySignal` instances and tagged with rigorous quality flags:

```python
class SignalQuality(Enum):
    VALID = "valid"               # Fresh, plausible, verified sensor value
    STALE = "stale"               # Unchanged beyond expected physical period
    MISSING = "missing"           # Expected channel not received in timeout
    OUT_OF_RANGE = "out_of_range" # Violates physical or sensor transducer limits
    INVALID = "invalid"           # Corrupted float (NaN/Inf) or bad payload
    ESTIMATED = "estimated"       # Synthesized or interpolated value
    SIMULATED = "simulated"       # Generated by virtual simulator
```

Signals are aggregated into synchronized `NormalizedTelemetrySample` frames representing a discrete point in engine operation:
- `engine_rpm`: float (rpm)
- `map_kpa`: float (kPa)
- `tps`: float (%)
- `coolant_temp`: float (°F)
- `target_afr`: float (AFR)
- `afr_measured`: float (AFR)
- `fuel_learn`: float (%)
- `battery_voltage`: float (V)
- `trans_gear`: int (0=P/N, 1..4)
- `oil_pressure`: Optional[float] (psi)
- `fuel_pressure`: Optional[float] (psi)

### 3.4 Deterministic Baseline Engine

The baseline engine avoids global averages by binning historical telemetry across operating dimensions:
1. **Engine State:** Crank, Warmup (CLT < 160°F), Hot Idle, Cruise, WOT Pull.
2. **Operating Matrix:** 2D grid of RPM ($500\,\text{rpm}$ bins) $\times$ MAP ($10\,\text{kPa}$ bins).

Within each bin, the engine calculates:
- **Median ($\tilde{x}$):** Central tendency robust against outliers.
- **Interquartile Range ($IQR = Q_3 - Q_1$):** Measure of normal spread.
- **5th and 95th Percentiles:** Realistic operational boundary thresholds.

### 3.5 Deterministic Event Detection Engine

The event engine is a collection of non-allocating, deterministic finite state machines:
- **Engine State Transitions:** Detects stall, cranking, running, and key-off based on RPM and voltage thresholds.
- **Transient Load Events:** Detects rapid throttle opening ($\Delta \text{TPS} / \Delta t > 15\% / 100\text{ms}$) and WOT entry ($\text{TPS} \ge 90\%$).
- **Thermal & Electrical Thresholds:** Rapid coolant rise ($> 5^\circ\text{F} / \text{min}$ sustained) or voltage sag ($< 12.0\,\text{V}$ while engine is running).

Every event emits an `EngineEvent` object:
```json
{
  "event_id": "evt_20260905_0012",
  "event_type": "WOT_PULL",
  "start_time": 1725578410.25,
  "end_time": 1725578414.80,
  "severity": "info",
  "signals_involved": ["rpm", "map_kpa", "tps", "afr_measured", "fuel_learn"],
  "calculated_metrics": {
    "start_rpm": 2800,
    "peak_rpm": 5850,
    "peak_map_kpa": 98.4,
    "mean_fuel_learn": 8.4
  },
  "confidence": 1.0,
  "evidence": "Sustained TPS >= 90% for 4.55s with RPM rise 2800->5850 rpm."
}
```

### 3.6 Rule-Based Diagnostic Engine

Diagnostics are deterministic rules that evaluate session events and baseline deviations against domain heuristics:

```json
{
  "diagnostic_id": "DIAG_FUEL_HIGH_LOAD_DEV",
  "title": "High-Load Fueling Deviation",
  "severity": "warning",
  "observation": "Closed-loop fuel learn averaged +8.2% across 4 separate WOT acceleration events between 4,800 and 5,600 RPM.",
  "evidence": [
    {"metric": "rpm_range", "value": "4800-5600 rpm"},
    {"metric": "map_range", "value": "91-99 kPa"},
    {"metric": "mean_correction", "value": "+8.2%"},
    {"metric": "baseline_correction", "value": "+1.1%"},
    {"metric": "repeated_events", "value": 4}
  ],
  "possible_causes": [
    "Volumetric Efficiency (VE) table under-estimating airflow in 4800-5600 RPM / 95 kPa cells",
    "Fuel rail pressure drop under high injector duty cycle",
    "Exhaust leak upstream of wideband O2 sensor introducing false lean air"
  ],
  "recommended_tests": [
    "Monitor mechanical or transducer fuel pressure during sustained WOT to verify pressure holds steady at 58 PSI",
    "Perform smoke test on exhaust headers and collector joints upstream of O2 sensor",
    "If fuel pressure and exhaust integrity are verified, review base fuel table cells in 4800-5600 RPM range"
  ],
  "confidence": 0.94,
  "data_validity_pct": 99.8
}
```

### 3.7 AI Interpretation Layer & Isolation Barrier

```
┌──────────────────────────────────────────────┐
│             AI ISOLATION BOUNDARY            │
│                                              │
│  The LLM has NO direct CAN access, NO socket │
│  access, and NO calibration write capability.│
└──────────────────────┬───────────────────────┘
                       │
       ┌───────────────┴───────────────┐
       ▼                               ▼
Structured Diagnostic Findings   Deterministic Query Tools
  - Observations                   - get_vehicle_profile()
  - Evidence Metrics               - get_session_summary()
  - Inferred Conditions            - query_telemetry_window()
  - Confidence Scores              - compare_runs()
```

The AI is strictly a natural-language interpreter and conversational assistant. It synthesizes findings, articulates uncertainties, explains engineering principles to enthusiasts, and answers questions using verifiable tool data.
