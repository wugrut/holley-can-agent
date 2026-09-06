# Diagnostic Engine Specification

**System:** EFI Intelligence Copilot  
**Tier:** Deterministic Rule Evaluator  
**Status:** In Development  
**Last Updated:** September 2026

---

## 1. Diagnostic Philosophy & Design Principles

The primary failure mode of automated automotive diagnostic tools is **alert fatigue**—overwhelming users with dozens of low-confidence warnings caused by momentary sensor spikes, normal engine transients, or poorly tuned thresholds.

EFI Intelligence Copilot enforces four strict diagnostic principles:

1. **High Confidence Over High Quantity:** A system that accurately identifies five critical, actionable problems is vastly superior to one that generates fifty noisy alerts.
2. **Explicit Evidence Required:** Every finding must provide an auditable chain of evidence: sample counts, standard deviations, time spans, RPM/MAP bins, and comparisons against the vehicle's learned baseline.
3. **Traceable Data Validity:** Every diagnostic reports the percentage of valid, non-stale data samples evaluated (e.g. `data_validity_pct = 99.4%`). If data validity is below $90\%$, confidence is penalized or suppressed.
4. **Separation of Observation, Inference, and Action:** The system never conflates what was observed with why it happened or what should be done.

---

## 2. Structured Diagnostic Object Contract

All diagnostics emit a standardized JSON-serializable dataclass:

```json
{
  "diagnostic_id": "DIAG_FUEL_HIGH_LOAD_DEV",
  "title": "High-Load Fueling Deviation",
  "severity": "warning",
  "category": "fueling",
  "timestamp": 1725578420.5,
  "observation": "Closed-loop fuel learn added an average of +8.2% fuel correction during 4 separate high-load events between 4,800 and 5,600 RPM.",
  "evidence": [
    {"name": "rpm_band", "value": "4800 - 5600 rpm"},
    {"name": "map_range", "value": "91.0 - 99.5 kPa"},
    {"name": "mean_fuel_learn", "value": "+8.2%"},
    {"name": "baseline_fuel_learn", "value": "+1.1%"},
    {"name": "event_count", "value": 4},
    {"name": "total_duration_s", "value": 14.8}
  ],
  "inferred_condition": "Engine requires significantly more fuel in high-load cells than predicted by the base volumetric efficiency table or baseline history.",
  "possible_causes": [
    "Volumetric Efficiency (VE) table values are low in the 4800-5600 RPM / 90-100 kPa region",
    "Fuel delivery restriction or falling fuel rail pressure at high injector duty cycles",
    "Exhaust leak upstream of wideband O2 sensor introducing ambient oxygen"
  ],
  "recommended_tests": [
    "Connect a mechanical pressure gauge or check fuel pressure transducer logs during sustained WOT to verify rail pressure holds steady at base specification (e.g. 58 PSI)",
    "Perform smoke or pressure test on header collector and O2 bung welds",
    "If fuel pressure and mechanical integrity are verified, apply learned fuel trims to the base VE table"
  ],
  "confidence": 0.94,
  "data_validity_pct": 99.8
}
```

---

## 3. Initial High-Confidence Diagnostic Rules

### 3.1 Fueling Diagnostics

#### Rule: `DIAG_FUEL_HIGH_LOAD_DEV` (High-Load Fueling Deviation)
* **Trigger Conditions:**
  1. Engine in WOT or High-Load state ($\text{TPS} \ge 85\%$ and $\text{MAP} \ge 85\,\text{kPa}$).
  2. $\text{RPM} \ge 3500\,\text{rpm}$ sustained for $\ge 1.5\,\text{seconds}$.
  3. Closed-loop learn or closed-loop compensation $|\text{Correction}| \ge 7.0\%$.
  4. Condition repeats across $\ge 2$ distinct acceleration events in the session.
* **Severity:** `warning` ($> 12\%$ triggers `critical`).

#### Rule: `DIAG_FUEL_CLOSED_LOOP_SATURATION` (Fuel Trim Saturation)
* **Trigger Conditions:**
  1. Fuel learn or trim reaches maximum allowed limit (e.g. $+50\%$ or $-50\%$, or user-configured limits).
  2. Sustained for $\ge 3.0\,\text{seconds}$ while engine is warm ($\text{CLT} \ge 160^\circ\text{F}$).
* **Severity:** `critical`.
* **Inferred Condition:** ECU has exhausted its authority to correct air-fuel ratio. Risk of severe lean backfire or plug fouling.

---

### 3.2 Idle Diagnostics

#### Rule: `DIAG_IDLE_RPM_HUNTING` (Idle RPM Oscillation)
* **Trigger Conditions:**
  1. Throttle closed ($\text{TPS} \le 1.0\%$) and vehicle speed $\le 2\,\text{mph}$.
  2. Engine at operating temperature ($\text{CLT} \ge 160^\circ\text{F}$).
  3. RPM oscillates with peak-to-trough amplitude $\ge 200\,\text{rpm}$ at frequency $0.5 - 2.0\,\text{Hz}$.
  4. Sustained for $\ge 6.0\,\text{seconds}$.
* **Severity:** `warning`.
* **Evidence:** FFT dominant frequency, amplitude range, target idle delta.
* **Possible Causes:** IAC valve over-compensating; timing table steep slope around idle cells; idle air bypass screw misadjusted; vacuum leak.

---

### 3.3 Sensor Diagnostics

#### Rule: `DIAG_SENSOR_DROPOUT` (Sensor Signal Dropout)
* **Trigger Conditions:**
  1. Channel received valid frames previously in session.
  2. Signal drops to default zero, NaN, or ceases broadcasting for $\ge 1.0\,\text{second}$ while other ECU telemetry remains active.
* **Severity:** `warning` for auxiliary sensors; `critical` for RPM, MAP, TPS, or CLT.

#### Rule: `DIAG_SENSOR_IMPLAUSIBLE_MAP_TPS` (Implausible Engine Vacuum vs Throttle)
* **Trigger Conditions:**
  1. $\text{TPS} \le 1.0\%$ (idle/deceleration).
  2. $\text{Engine RPM} \ge 2000\,\text{rpm}$.
  3. $\text{MAP} \ge 85\,\text{kPa}$ sustained for $\ge 1.0\,\text{second}$ on a naturally aspirated engine.
* **Severity:** `warning`.
* **Inferred Condition:** High manifold pressure with throttle closed at elevated RPM violates engine vacuum physics. Indicates a severe manifold vacuum leak, disconnected MAP vacuum line, or failed sensor.

---

### 3.4 Electrical & Thermal Diagnostics

#### Rule: `DIAG_ELEC_LOW_VOLTAGE` (Charging System Sinking)
* **Trigger Conditions:**
  1. Engine running ($\text{RPM} \ge 1000\,\text{rpm}$).
  2. $\text{Battery Voltage} < 12.4\,\text{V}$ sustained for $\ge 5.0\,\text{seconds}$.
* **Severity:** `warning` ($< 11.5\,\text{V}$ triggers `critical`).
* **Inferred Condition:** Alternator output insufficient to maintain system voltage under current electrical load. Fuel pump flow and injector dead-times are compromised.

#### Rule: `DIAG_THERMAL_COOLANT_OVERHEAT` (Coolant Temperature Overheat)
* **Trigger Conditions:**
  1. $\text{Coolant Temp} \ge 225^\circ\text{F}$ sustained for $\ge 10\,\text{seconds}$ (`warning`).
  2. $\text{Coolant Temp} \ge 240^\circ\text{F}$ (`critical`).
* **Evidence:** Peak temperature, rate of temperature rise ($^\circ\text{F}/\text{min}$), fan activation state.
