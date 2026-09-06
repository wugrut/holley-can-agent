# Verification & Test Plan — EFI Intelligence Copilot

**System:** EFI Intelligence Copilot  
**Status:** Active  
**Test Framework:** `pytest`, `pytest-asyncio`  
**Last Updated:** September 2026

---

## 1. Multi-Tier Testing Strategy

```
┌────────────────────────────────────────────────────────┐
│                   Level 4: End-to-End                  │
│       Simulator ──► Session ──► Diagnostics ──► Report │
├────────────────────────────────────────────────────────┤
│                   Level 3: Fault Injection             │
│        Corrupted Frames, Bus-Off, Dropouts, NaNs       │
├────────────────────────────────────────────────────────┤
│                   Level 2: Integration                 │
│         HAL ──► Protocol ──► Telemetry ──► Storage     │
├────────────────────────────────────────────────────────┤
│                   Level 1: Unit Testing                │
│    Bit unpacking, IEEE 754, Binned Stats, Rule Logic   │
└────────────────────────────────────────────────────────┘
```

---

## 2. Unit Testing Suite (`tests/unit/`)

### 2.1 Protocol & Unpacking
* **Bitfield Demuxing:** Test extraction of channel indices $1$ to $32$ and high boundary indices ($2047$) across arbitrary ECU serial numbers.
* **Payload Precision:** Test IEEE 754 float decoding with exact binary representations; ensure zero bit-loss.
* **Edge Cases:** Verify handling of empty payloads, truncated payloads ($< 8$ bytes), and oversized payloads ($> 8$ bytes).

### 2.2 Telemetry Normalization & Quality Grading
* **Physical Envelopes:** Verify `SignalQuality.OUT_OF_RANGE` when TPS exceeds $105\%$, Coolant exceeds $320^\circ\text{F}$, or Battery exceeds $20\,\text{V}$.
* **Corrupted Floats:** Verify that `NaN` and `$\pm\infty$` immediately map to `SignalQuality.INVALID` without raising unhandled exceptions.
* **Staleness Tracking:** Verify that signals with $\Delta t > 1.0\,\text{s}$ transition to `SignalQuality.STALE`.

### 2.3 Statistical Baseline Calculations
* **Non-parametric Metrics:** Validate median, IQR, and percentile calculations against known mathematical fixtures.
* **Bin Isolation:** Ensure 800 RPM idle samples never pollute 5500 RPM WOT baseline cells.

---

## 3. Fault Injection Testing (`tests/fault_injection/`)

The software must **fail safely and visibly**. Fault injection tests verify that corrupted data cannot silently enter diagnostics or corrupt sessions:

| Fault Case | Injected Pattern | Expected System Response |
|------------|------------------|--------------------------|
| **Cable Disconnect** | Socket abruptly closed during active stream | Hardware interface transitions to `DISCONNECTED`; auto-reconnect initiates; alert logged. |
| **Malformed CAN Frame** | Frame with $\text{DLC} = 4$ or $\text{DLC} = 7$ | Dropped with warning log; `error_frame_count` incremented; listener does not crash. |
| **Corrupted Payload** | Payload bytes `7F C0 00 00` (`NaN`) | Evaluated to `SignalQuality.INVALID`; excluded from baseline and diagnostic statistics. |
| **Out-of-Range Sensor** | MAP value decoded as $850\,\text{kPa}$ | Tagged `SignalQuality.OUT_OF_RANGE`; triggers sensor transducer fault check. |
| **Rapid Frame Flood** | 100,000 frames/sec bursts | Backpressure queue drops excess or applies rate-limit; memory footprint remains bounded. |

---

## 4. Replay Fixtures & Synthetic Regression Tests

Located in `data/fixtures/`:
1. `normal_idle.json`: Stable 850 RPM warm idle with steady 35 kPa MAP and stoichiometric AFR.
2. `unstable_idle.json`: Hunting idle with $\pm 250\,\text{rpm}$ oscillation at $1\,\text{Hz}$.
3. `lean_high_load.json`: 5500 RPM WOT pull with $+8.5\%$ fuel learn correction.
4. `rich_cruise.json`: 2200 RPM highway cruise with $-14\%$ fuel trim.
5. `sensor_dropout.json`: Continuous drive where TPS signal abruptly halts.
6. `low_voltage.json`: High RPM pull where system voltage sags from 14.2V to 11.4V.
7. `thermal_event.json`: Coolant temperature climbing from 195°F to 242°F at $10^\circ\text{F}/\text{min}$.
8. `normal_wot.json`: Clean 1st-to-4th gear pull with perfect AFR tracking and zero knock retard.

---

## 5. Automated Test Execution Commands

```bash
# Run entire test suite
pytest -v

# Run protocol and decoder tests only
pytest -v tests/test_protocol.py

# Run hardware and simulator tests
pytest -v tests/test_hardware.py tests/test_simulator.py

# Run fault injection tests
pytest -v tests/test_fault_injection.py
```
