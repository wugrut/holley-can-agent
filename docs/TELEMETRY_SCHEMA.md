# Telemetry Schema & Normalization Specification

**System:** EFI Intelligence Copilot  
**Status:** In Development  
**Last Updated:** September 2026

---

## 1. Design Objectives

The **Normalized Telemetry Model** provides an engine-agnostic, hardware-independent abstraction layer for time-series automotive data. Regardless of whether data originates from a Holley Terminator X, Terminator X MAX, a future aftermarket ECU (e.g. Haltech, FuelTech, MoTeC), or a virtual test harness, downstream analytics, baseline learning, and AI interpretation receive identically structured signals.

### Key Tenets
1. **Graceful Degradation:** The system never assumes all sensors are present. Uninstalled sensors (e.g. auxiliary fuel pressure or Bank 2 wideband) evaluate to `None` with `SignalQuality.MISSING` without crashing the analytical pipeline.
2. **Deterministic Units:** All signals use standardized SI or standard North American automotive engineering units (`rpm`, `kPa`, `°F`, `AFR`, `V`, `psi`, `%`).
3. **Traceable Quality:** Every discrete signal sample carries an explicit `SignalQuality` tag, timestamp, and confidence score.

---

## 2. Signal Quality State Machine

```
              ┌─────────────────────────┐
              │    Incoming CAN Frame   │
              └────────────┬────────────┘
                           │
             ┌─────────────┴─────────────┐
             ▼                           ▼
      [ NaN / Inf / != 8B ]       [ Valid Float32 ]
             │                           │
             ▼                           ▼
   SignalQuality.INVALID         [ Range Check ]
                                         │
                         ┌───────────────┴───────────────┐
                         ▼                               ▼
               [ Out of Physical Bounds ]      [ Within Normal Limits ]
                         │                               │
                         ▼                               ▼
              SignalQuality.OUT_OF_RANGE         [ Staleness Timer ]
                                                         │
                                         ┌───────────────┴───────────────┐
                                         ▼                               ▼
                                  [ dt > 1.0s ]                    [ dt <= 1.0s ]
                                         │                               │
                                         ▼                               ▼
                                SignalQuality.STALE              SignalQuality.VALID
```

### Quality Enumeration

| Quality Value | Meaning | Rule for Analytics / Diagnostics |
|---------------|---------|----------------------------------|
| `VALID` | Verified sensor value within physical boundaries and updated within timeout. | Included in all baselines, metrics, and diagnostic evaluations. |
| `STALE` | Sensor has not transmitted a new value within expected period ($> 1.0\,\text{s}$). | Excluded from transient event detection; triggers sensor latency diagnostic. |
| `MISSING` | Channel not broadcast by ECU or sensor not wired to pin. | Signal set to `None`; rules requiring this sensor are skipped. |
| `OUT_OF_RANGE` | Value violates physical limits (e.g. TPS $< -2\%$ or $> 105\%$). | Flagged as sensor calibration or wiring fault; excluded from engine baselines. |
| `INVALID` | Corrupted byte stream, IEEE 754 `NaN`, or infinite value. | Triggers CAN bus integrity alert; sample dropped from calculations. |
| `ESTIMATED` | Interpolated or derived mathematically (e.g. boost from MAP minus Baro). | Labeled with confidence factor $< 1.0$. |
| `SIMULATED` | Produced by virtual simulator adapter for testing/replay. | Always explicitly tagged to prevent synthetic data entering production vehicle history. |

---

## 3. Normalized Signal Schema

### 3.1 Primary Engine Signals

| Signal Identifier | Type | Unit | Normal Range | Physical Limits | Description |
|-------------------|------|------|--------------|-----------------|-------------|
| `engine_rpm` | `float` | `rpm` | $650 - 7200$ | $0 - 12000$ | Engine crankshaft rotational speed |
| `map_kpa` | `float` | `kPa` | $25 - 250$ | $0 - 500$ | Manifold Absolute Pressure |
| `baro_kpa` | `float` | `kPa` | $90 - 105$ | $50 - 120$ | Ambient barometric pressure |
| `tps` | `float` | `%` | $0.0 - 100.0$ | $-2.0 - 105.0$ | Throttle Position Sensor percentage |
| `oil_pressure` | `Optional[float]` | `psi` | $20 - 80$ | $0 - 150$ | Engine oil pressure (optional transducer) |
| `vehicle_speed` | `Optional[float]` | `mph` | $0 - 160$ | $0 - 250$ | Calibrated ground speed |

### 3.2 Fueling System Signals

| Signal Identifier | Type | Unit | Normal Range | Physical Limits | Description |
|-------------------|------|------|--------------|-----------------|-------------|
| `target_afr` | `float` | `AFR` | $11.5 - 14.7$ | $8.0 - 20.0$ | Commanded Target Air-Fuel Ratio |
| `afr_measured` | `float` | `AFR` | $11.0 - 16.0$ | $7.0 - 25.0$ | Active wideband O2 reading (Bank 1 or Avg) |
| `afr_bank1` | `float` | `AFR` | $11.0 - 16.0$ | $7.0 - 25.0$ | Wideband O2 Bank 1 |
| `afr_bank2` | `Optional[float]` | `AFR` | $11.0 - 16.0$ | $7.0 - 25.0$ | Wideband O2 Bank 2 (dual wideband setups) |
| `fuel_learn` | `float` | `%` | $-15.0 - +15.0$ | $-50.0 - +50.0$ | Active closed-loop fuel learn table trim |
| `closed_loop_active`| `bool` | `bool` | `True/False` | `True/False` | Flag indicating closed-loop fueling control |
| `fuel_pw` | `float` | `ms` | $1.2 - 20.0$ | $0.0 - 30.0$ | Primary injector pulse width |
| `injector_duty` | `float` | `%` | $5.0 - 85.0$ | $0.0 - 100.0$ | Calculated injector duty cycle |
| `fuel_pressure` | `Optional[float]` | `psi` | $40 - 70$ | $0 - 120$ | Fuel rail pressure transducer |

### 3.3 Thermal & Electrical Signals

| Signal Identifier | Type | Unit | Normal Range | Physical Limits | Description |
|-------------------|------|------|--------------|-----------------|-------------|
| `coolant_temp` | `float` | `°F` | $175 - 215$ | $-40 - 320$ | Engine Coolant Temperature (CLT) |
| `iat` | `float` | `°F` | $60 - 140$ | $-40 - 300$ | Intake Air Temperature (Manifold MAT) |
| `battery_voltage` | `float` | `V` | $13.4 - 14.6$ | $0.0 - 20.0$ | Main ECU switched battery voltage |
| `fan1_active` | `bool` | `bool` | `True/False` | `True/False` | Electric cooling fan 1 command |
| `fan2_active` | `bool` | `bool` | `True/False` | `True/False` | Electric cooling fan 2 command |

### 3.4 Transmission Signals (Terminator X MAX)

| Signal Identifier | Type | Unit | Normal Range | Physical Limits | Description |
|-------------------|------|------|--------------|-----------------|-------------|
| `trans_gear` | `int` | `gear` | $0 - 4$ | $0 - 6$ | Current transmission gear ($0=\text{Park/Neutral}$) |
| `trans_temp` | `Optional[float]` | `°F` | $140 - 200$ | $-40 - 350$ | Transmission fluid temperature |
| `tcc_duty` | `Optional[float]` | `%` | $0.0 - 100.0$ | $0.0 - 100.0$ | Torque Converter Clutch PWM lockup duty |
| `trans_slip_rpm` | `Optional[float]` | `rpm` | $0 - 3000$ | $-500 - 8000$ | Converter slip (Input RPM minus Output $\times$ Ratio) |

---

## 4. Calculated & Derived Signals

The normalization tier calculates standardized derivative metrics in real time:

### 1. Boost Pressure (psi)
$$\text{Boost (psi)} = \begin{cases} (\text{MAP} - \text{Baro}) \times 0.145038 & \text{if } \text{MAP} > \text{Baro} \\ 0.0 & \text{otherwise} \end{cases}$$

### 2. Manifold Vacuum (inHg)
$$\text{Vacuum (inHg)} = \begin{cases} (\text{Baro} - \text{MAP}) \times 0.295300 & \text{if } \text{Baro} > \text{MAP} \\ 0.0 & \text{otherwise} \end{cases}$$

### 3. AFR Error (%)
$$\text{AFR Error (\%)} = \frac{\text{AFR}_{\text{measured}} - \text{Target AFR}}{\text{Target AFR}} \times 100$$
*(Positive indicates lean; negative indicates rich)*

### 4. Injector Duty Cycle (%)
$$\text{Duty Cycle (\%)} = \frac{\text{RPM} \times \text{Fuel PW (ms)}}{1200} \quad (\text{for 4-stroke engines})$$
*(Capped at 100.0%)*
