# CAN Protocol Specification & Verification Audit — Holley HEFI 3rd-Party Broadcast

**Target ECU:** Holley Terminator X & Terminator X MAX  
**Protocol Classification:** Holley EFI (HEFI) 3rd-Party Broadcast / Historical Racepak Stream  
**Audit Date:** September 2026  
**Verification Taxonomy:**
* `HOLLEY_SOURCE_VERIFIED`: Confirmed directly by official Holley published documentation, manual, or official vendor DBC.
* `SOURCE_VERIFIED`: Documented by established third-party integration specifications (e.g. RealDash XML, CANformance Wiki, Nefarious Motorsports, Racepak broadcast guides).
* `LIVE_HARDWARE_VERIFIED`: Empirically validated with bus trace captures from a physical running Terminator X / X MAX ECU.
* `TEST_FIXTURE_VERIFIED`: Validated in automated software unit tests against synthetic fixtures.
* `INFERRED`: Deduced from adjacent channel patterns, mathematical derivatives, or firmware status word behavior.
* `UNKNOWN`: Unverified, unmapped, or proprietary.

---

## 1. Protocol Origins & Authoritative Provenance

### 1.1 Provenance Context
* **Official Holley Stance:** Holley does not publish an open, single official `.dbc` file for general third-party software developers. In the Holley EFI / Terminator X PC software (under *System Parameters > CAN Bus*), this data stream is historically configured as the **"Racepak"** or **"3rd Party Broadcast"** option.
* **Third-Party Integration Standards:** The broadcast format was designed for third-party digital dashes (Racepak, AEM CD-7/CD-5, Dakota Digital, RealDash). These dash manufacturers and community reverse-engineering initiatives (CANformance Engineering, Nefarious Motorsports, HackingLZ `holley-efi-parser`) documented the 29-bit extended identifier layout and payload conventions.
* **Software Implementation Provenance:** The definitions in this repository originate from the documented community specifications and are verified in software unit tests (`TEST_FIXTURE_VERIFIED`). **No live physical ECU captures have been verified yet** (`LIVE_HARDWARE_VERIFIED: PENDING`).

---

## 2. Physical Layer & Bus Topology Audit

| Parameter | Specification | Status | Provenance / Evidence Source |
|-----------|---------------|--------|------------------------------|
| **Standard** | ISO 11898-2 (CAN 2.0B) | `SOURCE_VERIFIED` | Documented across Holley integration guides (AEM/Racepak) |
| **Bitrate** | 1,000,000 bits/sec ($1\,\text{Mbps}$) | `SOURCE_VERIFIED` | Documented in Holley manual & third-party dash setups |
| **Termination** | $120\,\Omega$ at each trunk end ($60\,\Omega$ bus) | `SOURCE_VERIFIED` | Standard ISO 11898 requirement confirmed by Holley tech docs |
| **Harness Connector**| Packard/Delphi Metri-Pack 150 4-Pin | `SOURCE_VERIFIED` | Holley Terminator X Wiring Manual (Pin A=CAN-H, Pin B=CAN-L) |
| **Transmission Mode**| Passive Unsolicited Broadcast | `SOURCE_VERIFIED` | ECU broadcasts continuously; no request frames required |

---

## 3. CAN Identifier Bitfield Audit (29-Bit Extended)

```text
Bits:    31:29    28      27:25       24:14         13:11       10:0
Field:  [Flags] [Cmd]   [Target]    [Ch Index]     [Source]   [ECU Serial]
Width:    3b      1b       3b          11b            3b          11b
Value:    000     1      0b111      0 to 2047       0b010     0 to 2047
                         (Bcast)                     (ECU)    (ECU & 0x7FF)
```

| Bitfield | Bit Range | Value / Rule | Status | Source / Verification |
|----------|-----------|--------------|--------|----------------------|
| **Flags / Reserved** | 31:29 | `000` | `TEST_FIXTURE_VERIFIED` | Standard CAN 29-bit boundary |
| **Command Bit** | 28 | `1` (Broadcast) | `SOURCE_VERIFIED` | Nefarious Motorsports / RealDash XML |
| **Target Address** | 27:25 | `0b111` (Broadcast target) | `SOURCE_VERIFIED` | Nefarious Motorsports / RealDash XML |
| **Channel Index** | 24:14 | 11-bit channel ID ($0 - 2047$) | `SOURCE_VERIFIED` | RealDash XML definitions / CANformance |
| **Source Identifier**| 13:11 | `0b010` (ECU source) | `SOURCE_VERIFIED` | Nefarious Motorsports / RealDash XML |
| **ECU Serial Bits** | 10:0 | `ECU_Serial & 0x7FF` | `SOURCE_VERIFIED` | RealDash XML / Nefarious Motorsports |
| **Masking Algorithm**| `0x1FFFF800` | Strips serial; `>> 14` isolates index | `TEST_FIXTURE_VERIFIED` | Validated in automated test suite |

---

## 4. Payload Structure & Encoding Audit

* **Length:** Exactly 8 bytes (`DLC = 8`).
* **Encoding:** Two 32-bit big-endian IEEE 754 floating-point values (`struct.unpack('>ff')`).
* **Signedness:** Standard IEEE 754 signed floats (supports negative values, e.g. timing advance $-20^\circ$ or $-40^\circ\text{F}$).
* **Scaling / Offset:** Linear $1.0\times + 0.0$ (native floating-point physical units; no arbitrary integer scaling factors).
* **Audit Status:** `SOURCE_VERIFIED` (RealDash / Nefarious); `TEST_FIXTURE_VERIFIED` (Tested with known binary float vectors).

---

## 5. Comprehensive Channel-by-Channel Provenance Audit

| Index | Signal Name | Engineering Unit | Value A Meaning | Value A Status | Value B Meaning | Value B Status | Verification Source |
|---|---|---|---|---|---|---|---|
| **1** | `engine_rpm` | rpm | Engine Speed | `SOURCE_VERIFIED` | Reserved / Status | `UNKNOWN` | RealDash XML / CANformance |
| **2** | `map_kpa` | kPa | Manifold Absolute Pressure | `SOURCE_VERIFIED` | Barometric Pressure (kPa) | `SOURCE_VERIFIED` | RealDash XML (`baro_kpa`) |
| **3** | `tps` | % | Throttle Position ($0 - 100$) | `SOURCE_VERIFIED` | Status | `UNKNOWN` | RealDash XML |
| **4** | `coolant_temp` | °F | Engine Coolant Temp | `SOURCE_VERIFIED` | Status | `UNKNOWN` | RealDash XML |
| **5** | `target_afr` | AFR | Commanded Target AFR | `SOURCE_VERIFIED` | Reserved | `UNKNOWN` | RealDash XML |
| **6** | `afr_bank1` | AFR | Wideband O2 Bank 1 | `SOURCE_VERIFIED` | Sensor Quality/Status | `UNKNOWN` | RealDash XML |
| **7** | `afr_bank2` | AFR | Wideband O2 Bank 2 | `SOURCE_VERIFIED` | Sensor Quality/Status | `UNKNOWN` | RealDash XML |
| **8** | `afr_measured`| AFR | Averaged Wideband AFR | `SOURCE_VERIFIED` | Reserved | `UNKNOWN` | RealDash XML |
| **9** | `air_temp_enrich` | % | IAT Fuel Multiplier | `SOURCE_VERIFIED` | Reserved | `UNKNOWN` | RealDash XML |
| **10**| `coolant_enrich` | % | CLT Warmup Multiplier | `SOURCE_VERIFIED` | Reserved | `UNKNOWN` | RealDash XML |
| **11**| `ignition_timing` | °BTDC | Total Spark Advance | `SOURCE_VERIFIED` | Knock Retard (deg) | `INFERRED` | RealDash XML (Knock in float B) |
| **12**| `battery_voltage`| V | ECU Supply Voltage | `SOURCE_VERIFIED` | Status | `UNKNOWN` | RealDash XML |
| **13**| `fuel_learn` | % | Closed-Loop Fuel Learn | `SOURCE_VERIFIED` | Reserved | `UNKNOWN` | RealDash XML |
| **14**| `closed_loop_active`| flag | 1.0 = Active, 0.0 = Open | `SOURCE_VERIFIED` | Reserved | `UNKNOWN` | RealDash XML |
| **15**| `iat` | °F | Intake Air Temp | `SOURCE_VERIFIED` | Status | `UNKNOWN` | RealDash XML |
| **16**| `fuel_pw` | ms | Injector Pulse Width | `SOURCE_VERIFIED` | Injector Duty Cycle (%) | `INFERRED` | Calculated or secondary float |
| **17**| `spark_advance` | ° | Base Spark Table | `SOURCE_VERIFIED` | Reserved | `UNKNOWN` | RealDash XML |
| **18**| `idle_speed` | rpm | Target Idle RPM | `SOURCE_VERIFIED` | IAC Position (%) | `SOURCE_VERIFIED` | RealDash XML |
| **19**| `fan1_active` | flag | Electric Fan 1 Status | `SOURCE_VERIFIED` | Electric Fan 2 Status | `INFERRED` | RealDash XML |
| **20**| `trans_gear` | gear | 4L60/80E Current Gear | `SOURCE_VERIFIED` | Commanded Gear | `INFERRED` | RealDash XML |
| **21**| `trans_temp` | °F | Trans Fluid Temp | `SOURCE_VERIFIED` | Status | `UNKNOWN` | RealDash XML |
| **22**| `tcc_duty` | % | TCC Lockup PWM Duty | `SOURCE_VERIFIED` | Converter Slip (rpm) | `INFERRED` | RealDash XML |
| **23**| `output_speed` | rpm | Trans Output Shaft RPM | `SOURCE_VERIFIED` | Reserved | `UNKNOWN` | RealDash XML |
| **24**| `input_speed` | rpm | Trans Input/Turbine RPM| `SOURCE_VERIFIED` | Reserved | `UNKNOWN` | RealDash XML |
| **25**| `line_pressure`| % | EPC Solenoid Duty | `SOURCE_VERIFIED` | Reserved | `UNKNOWN` | RealDash XML |
| **30**| `oil_pressure` | psi | Oil Pressure Transducer | `SOURCE_VERIFIED` | Status | `UNKNOWN` | RealDash XML / Custom Input |
| **31**| `fuel_pressure`| psi | Fuel Pressure Transducer| `SOURCE_VERIFIED` | Status | `UNKNOWN` | RealDash XML / Custom Input |
| **32**| `vehicle_speed`| mph | Calibrated Ground Speed | `SOURCE_VERIFIED` | Status | `UNKNOWN` | RealDash XML |
| **>32**| *Unmapped* | - | Custom I/O / Nitrous / Boost | `UNKNOWN` | Reserved | `UNKNOWN` | Logged to `UnknownChannelTracker` |

---

## 6. Explicitly Unknown & Prohibited Protocol Areas

Per mandatory safety engineering rules:

| Protocol Function | Status | Action / Handling |
|-------------------|--------|-------------------|
| **ECU Calibration Writes** | `UNKNOWN` | **STRICTLY PROHIBITED.** No frame generation or write code exists in the codebase. |
| **Proprietary DTC Read/Clear Services** | `UNKNOWN` | **NEEDS VERIFIED SOURCE.** Not polled. Diagnostics are calculated exclusively from continuous broadcast telemetry. |
| **Holley USB Dongle Flash Protocol** | `UNKNOWN` | **STRICTLY PROHIBITED.** Dongle handshake and memory addresses are proprietary to Holley EFI software. |
| **Channels > 32 (Advanced Options)** | `UNKNOWN` | **NEEDS VERIFIED SOURCE.** Encountered frames are captured and logged to `UnknownChannelTracker` without feeding core diagnostic rules. |
| **Live Hardware Validation** | `UNKNOWN` | **PENDING PHYSICAL VEHICLE TEST.** Simulator success does not equal hardware compatibility. |
