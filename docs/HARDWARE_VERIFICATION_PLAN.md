# Physical Hardware Verification Plan: Holley Terminator X / X MAX

**Target Hardware:** Holley Terminator X (550-916 / 550-917) & Terminator X MAX (550-926 / 550-927)  
**Document Status:** Approved Protocol Verification Protocol  
**Verification Level:** Moving from `SOURCE_VERIFIED` to `LIVE_HARDWARE_VERIFIED`  
**Last Updated:** September 2026

---

## 1. Objective & Purpose

The existing automated test suite (78/78 tests) demonstrates software correctness against community reverse-engineered specifications (`SOURCE_VERIFIED`) and synthetic regression fixtures (`TEST_FIXTURE_VERIFIED`). 

**Simulation and fixture success does NOT constitute proof of physical ECU compatibility.**

This Hardware Verification Plan establishes the mandatory, step-by-step procedure required to test, capture, validate, and verify the EFI Intelligence Copilot against a real, physical Holley Terminator X / X MAX ECU before claiming `LIVE_HARDWARE_VERIFIED` status.

---

## 2. Required Test Hardware & Equipment

| Equipment | Specification | Purpose |
|-----------|---------------|---------|
| **Target ECU** | Holley Terminator X or Terminator X MAX | Physical device under test. |
| **CAN Interface** | PEAK PCAN-USB (IPEH-002021/002022) or candleLight (CANable v2) | Physical USB-to-CAN adapter with galvanically isolated transceiver preferred. |
| **Wiring Harness Tap** | Delphi/Packard Metri-Pack 150 4-pin male connector | Connects to Terminator X J3/CAN splitter connector. |
| **Terminating Resistor** | $120\,\Omega \pm 1\%$, $1/4\text{W}$ metal film resistor | Bus termination (if adapter internal termination jumper is disabled). |
| **Digital Multimeter** | Calibrated DMM with $\Omega$ measurement | Verifies unpowered bus resistance before connection. |
| **Host PC** | Linux (SocketCAN) or Windows (PEAK-Basic) | Running packet capture and decoder validation tools. |

---

## 3. Physical Wiring & Pinout

Terminator X / X MAX main harness CAN connector (4-pin Metri-Pack 150):

```
       ┌───────────┐
     ┌─┘  Latch    └─┐
   ┌─┴───────────────┴─┐
   │   [A]       [B]   │    Pin A: CAN High (Red/White or White wire)
   │                   │    Pin B: CAN Low (Black/White or Blue wire)
   │   [C]       [D]   │    Pin C: Switched +12V (DO NOT CONNECT TO PC)
   └───────────────────┘    Pin D: Ground / Shield (Optional reference ground)
```

> [!CAUTION]
> **ELECTRICAL HAZARD**:
> NEVER connect Pin C (+12V switched vehicle power) to the USB-CAN adapter's logic pins. Only Pin A (CAN-H) and Pin B (CAN-L), and optionally Pin D (Ground), should connect to the CAN transceiver.

---

## 4. Pre-Connection Resistance Verification

Before attaching the USB-CAN adapter to the host computer:

1. Turn vehicle ignition **OFF** and disconnect battery ground terminal.
2. Connect multimeter test probes across Pin A (CAN-H) and Pin B (CAN-L).
3. **Acceptance Criteria:**
   * Resistance must read **$58.0\,\Omega - 62.0\,\Omega$**.
   * If reading is $\sim 120\,\Omega$: Missing one terminating resistor on bus trunk.
   * If reading is $\sim 0\,\Omega$: Dead short between CAN-H and CAN-L; do NOT proceed.
   * If reading is $> 1000\,\Omega$: Open circuit; verify wiring harness continuity.

---

## 5. Safe Passive-Listening Procedure

To guarantee that the physical ECU cannot be interfered with, the CAN transport MUST be placed into **Listen-Only / Silent Mode**:

### On Linux (SocketCAN):
```bash
# Bring down interface
sudo ip link set can0 down

# Configure 1 Mbps bitrate and enforce LISTEN-ONLY mode (no ACK or transmission on bus)
sudo ip link set can0 type can bitrate 1000000 listen-only on

# Bring interface up
sudo ip link set can0 up

# Verify state
ip -details link show can0
```

### On Windows (PCAN-USB):
In `app/hardware/usb_can.py`, verify that `receive_own_messages=False` and initialize the PCAN channel in passive receive mode.

---

## 6. Target ECU Firmware Versions

The validation trial must record and test against specific Holley firmware revisions:
1. **Firmware V1 / Build 004x:** Legacy Terminator X firmware.
2. **Firmware V2 / Build 008x:** Standard production Terminator X.
3. **Firmware V3 / Build 010x+:** Current release supporting advanced nitrous/boost features.

---

## 7. Execution Stages & Capture Checklist

### Stage 1: Key-On, Engine-Off (KOEO)
1. Turn ignition switch to **RUN** (do not crank).
2. Start raw frame capture:
   ```bash
   candump -tz -l can0
   ```
3. **Expected Telemetry Verification:**
   - Channel 1 (RPM): Must read $0.0\,\text{rpm}$.
   - Channel 2 (MAP): Must read current atmospheric barometric pressure ($95 - 103\,\text{kPa}$ at sea level).
   - Channel 3 (TPS): Sweep throttle pedal smoothly from $0\%$ to $100\%$; verify decoded value tracks pedal linearly without inversion or scaling offset.
   - Channel 4 (Coolant Temp): Must read ambient temperature ($50 - 90^\circ\text{F}$ on cold engine).
   - Channel 12 (Battery Voltage): Must read battery resting voltage ($12.0 - 12.8\,\text{V}$).

### Stage 2: Engine Cranking
1. Crank engine for 3–5 seconds.
2. **Expected Telemetry Verification:**
   - Channel 1 (RPM): Must register cranking speed ($150 - 280\,\text{rpm}$).
   - Channel 12 (Battery Voltage): Must dip to $10.0 - 11.5\,\text{V}$ under starter load.

### Stage 3: Warmup & Warm Idle
1. Start engine and allow coolant to warm from ambient to operating temperature ($180 - 195^\circ\text{F}$).
2. **Expected Telemetry Verification:**
   - Channel 1 (RPM): Fast idle ($1000 - 1200\,\text{rpm}$) transitioning down to target idle ($750 - 850\,\text{rpm}$).
   - Channel 14 (Closed Loop Flag): Transitions from $0.0$ (Open Loop warmup) to $1.0$ (Closed Loop active once CLT exceeds closed-loop threshold).
   - Channel 6 / 8 (AFR): Wideband reading stabilizes around Target AFR ($14.7 \pm 0.3\,\text{AFR}$).
   - Channel 13 (Fuel Learn): Closed-loop learn trims active.

### Stage 4: Steady-State Rev & Throttle Blip
1. Blip throttle in neutral to 2500 RPM.
2. Verify transient response: TPS rises, MAP rises toward atmospheric, fuel pulse width widens.

---

## 8. Frame Comparison & Decoder Validation Procedure

1. Convert raw `candump` log into replay JSON format.
2. Feed recorded frames into `app/protocol/hefi.py` (`HefiProtocolDecoder`).
3. **Bitwise Difference Comparison:**
   - Compare decoded floats against Holley EFI PC software live gauge display recorded concurrently.
   - Delta tolerance between Holley PC display and decoded telemetry must be $\le 0.1\%$ across all channels.
4. **Unknown Frame Audit:**
   - Inspect `UnknownChannelTracker.get_unknown_indices()`.
   - Any observed channel index outside 1–25, 30–32 must be logged with timestamp, frequency, and byte trace for manual disassembly.

---

## 9. Failure Handling & Abort Conditions

The physical verification trial must be **aborted immediately** if any of the following occur:
1. **Bus Error Frame Flood:** CAN bus error rate exceeds $1.0\%$ (indicates incorrect bitrate, missing termination, or loose wiring).
2. **ECU Resets / Check Engine LED:** Any unexpected ECU power cycle or fault light.
3. **Implausible Floating-Point Decoding:** Any critical sensor reads `NaN`, infinite, or severely reversed sign (e.g. coolant temp reading $-40^\circ\text{F}$ on warm engine indicates endian mismatch).
4. **Ground Potential Difference:** Any voltage measured between adapter shield ground and vehicle chassis exceeding $0.2\,\text{V}$ (indicates improper ground loop; isolate immediately).

---

## 10. Promotion to `LIVE_HARDWARE_VERIFIED`

A channel or protocol feature may be promoted from `SOURCE_VERIFIED` to `LIVE_HARDWARE_VERIFIED` in `app/protocol/registry.py` **ONLY** after:
1. Physical bus trace is captured on a running vehicle per this procedure.
2. Raw CAN frame log is committed to `data/captures/` with vehicle and firmware metadata.
3. Automated regression tests pass using the recorded physical trace.
