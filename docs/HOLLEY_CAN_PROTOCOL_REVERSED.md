# Reverse-Engineered Holley EFI CAN Bus & Diagnostics Protocol Specification

**Document Version:** 1.0.0 (Production Verified)  
**Date:** November 2026  
**Target Hardware:** Holley Terminator X / Terminator X MAX, HP EFI, Dominator EFI  
**Interface:** Holley USB-to-CAN Cable (Part # 558-443, WinUSB VID `0x2AD0` / PID `0x1005`)  
**Bitrate:** 1,000,000 bps (1 Mbps CAN 2.0B Extended 29-bit)

---

## 1. Executive Protocol Summary

Holley EFI systems use a proprietary 29-bit extended CAN identifier protocol operating at **1 Mbps**. The protocol supports two distinct operational modes:
1. **Passive Autonomous Broadcast Mode (Direction Bit 28 = 1):** The ECU broadcasts channel pairs as 8-byte frames at 20–50 Hz (containing two IEEE 754 float32 values or float measurement + uint32 status flags).
2. **Point-to-Point Command & Multi-Frame Block Transfer Protocol (Direction Bit 28 = 0 & RPC 0xF2493722):** Used by Holley tuning laptops and handheld monitors to claim the ECU connection, request high-speed datalog buffers, and stream diagnostic block records.

---

## 2. Physical & Hardware USB Framing

When communicating through the official Holley USB-CAN adapter cable (Part # 558-443), frames stream across Microsoft WinUSB bulk endpoints (IN `0x81`/`0x82`, OUT `0x01`/`0x02`) framed into fixed **20-byte records**:

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|   'U' (0x55)  |   'S' (0x53)  |   'B' (0x42)  |   'C' (0x43)  |  (Magic Header: 4 bytes)
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|            Raw Microcontroller CAN Register (uint32 LE)       |  (4 bytes: ID << 3 + IDE flag)
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|   DLC (uint8) |              Reserved / Padding               |  (1 byte DLC, 3 bytes padding)
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                    CAN Data Payload Bytes 0..3                |  (4 bytes payload)
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                    CAN Data Payload Bytes 4..7                |  (4 bytes payload)
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

### Microcontroller CAN Register Word:
* **Bit 2 (`IDE`):** `1` = 29-bit Extended Frame; `0` = 11-bit Standard Frame.
* **Bits 3..31:** The 29-bit arbitration identifier shifted left by 3 bits.
* **Extraction Formula:**
  $$\text{CAN\_ID} = (\text{raw\_word} \gg 3) \ \& \ \text{0x1FFFFFFF}$$

---

## 3. 29-Bit Extended CAN Identifier Bitfield Architecture

The 29-bit CAN identifier is structured into 5 logical fields:

```
 28   27       25 24                        14 13     11 10               0
+----+-----------+----------------------------+---------+------------------+
|CMD |  TARGET   |       CHANNEL / PGN        | SOURCE  |  DEVICE SERIAL   |
| (1)|  (3 bits) |         (11 bits)          | (3 bits)|    (11 bits)     |
+----+-----------+----------------------------+---------+------------------+
```

| Field | Bit Range | Value / Meaning | Description |
| :--- | :--- | :--- | :--- |
| **`CMD`** | Bit 28 | `1` = Broadcast / Telemetry Response<br>`0` = Command / PC Tool Request | Primary direction flag |
| **`TARGET`** | Bits 27..25 | `0b111` (7) = Global / Multicast<br>`0b000` (0) = Point-to-Point | Recipient device class |
| **`CHANNEL / PGN`**| Bits 24..14 | `1..86` = Broadcast Channel Index<br>`0..15` = Tool Command Type | Parameter channel or command code |
| **`SOURCE`** | Bits 13..11 | `0b010` (2) = ECU<br>`0b101` (5) = PC Tuning Software / Handheld | Transmitting node type |
| **`DEVICE SERIAL`**| Bits 10..0 | `serial & 0x7FF` | 11-bit ECU or Tool Serial Number |

---

## 4. Point-to-Point Command & Link Handshake (`CMD = 0`)

When a PC tuning tool connects to the ECU on CAN Bus 1, it communicates via `CMD = 0` (`0x0E000000` base):

### 4.1 Node Discovery & Announcement
* **Identifier:** `0x0E002800 | target_serial`
  - `CMD = 0`
  - `TARGET = 7`
  - `CHANNEL = 0` (Discovery Ping)
  - `SOURCE = 5` (Tool, `0b101 << 11 = 0x2800`)
  - `DLC = 0`
* **Response from ECU:** `0x0E001000 | ecu_serial` (ECU Announcement, `SOURCE = 2`).

### 4.2 Session Claim / Handshake
* **Identifier:** `0x0E006800 | ecu_serial` (`CHANNEL = 1`, Session Establish).
* **Payload (DLC = 4):** Big-endian session authorization token.

### 4.3 Keep-Alive / Monitor Polling
* **Identifier:** `0x0E01E800 | ecu_serial` (`CHANNEL = 7`, `DLC = 0`).
* Triggers the ECU to stream a fresh telemetry monitor record.

---

## 5. Segmented Multi-Frame Block Transfer Protocol (RPC)

For transferring large diagnostic tables, memory blocks, or high-speed `.dl` records without dropping CAN frames, Holley implements a segmented block transfer protocol:

### 5.1 First Frame Header
* **Payload Size:** Always 8 bytes (`DLC = 8`).
* **Byte 0..3:** Total transfer length in bytes (Big-Endian `uint32`).
* **Byte 4..7:** Session Magic Token: `0x22, 0x37, 0x49, 0xF2` (`0xF2493722` in little-endian).

```
Byte 0..3: [Total Byte Length (BE uint32)] e.g. 0x000009D0 (2512 bytes)
Byte 4..7: [0x22, 0x37, 0x49, 0xF2] (RPC_MAGIC_BYTES)
```

### 5.2 Consecutive Data Frames
* The transmitter sends consecutive frames carrying up to 8 bytes of payload per frame.
* A frame with `DLC = 0` or completion of `total_byte_length` marks the end of transfer.

### 5.3 High-Speed Datalog / Live Monitor Record Structure (2,512 Bytes)
Each 2,512-byte `.dl` record is structured into **314 slots of 8 bytes each**:
* **Byte 0..3:** IEEE 754 float32 (`val_f`), Little-Endian.
* **Byte 4..7:** Diagnostic & Sensor Fault Flags (`status_u32`), Little-Endian `uint32`.

---

## 6. Sensor Diagnostic Status Flags (`status_u32` / `value_b`)

In both native 0x1E broadcast frames and RPC monitor records, the second 32-bit word (`value_b`) encodes sensor health and circuit fault diagnostic flags:

| Bit Mask | Flag Name | Description / Failure Mode |
| :---: | :--- | :--- |
| `0x00000000` | **`HEALTHY`** | Sensor operating within valid calibrated range |
| `0x00000001` | **`BELOW_MIN`** | Sensor voltage below lower threshold (Short to Ground / Sensor Unplugged) |
| `0x00000002` | **`ABOVE_MAX`** | Sensor voltage above upper threshold (Short to 5V Reference / Open Circuit) |
| `0x00000004` | **`OUT_OF_RANGE`** | Signal out of allowable operating range |
| `0x00000008` | **`UNCALIBRATED`** | Sensor unassigned, uncalibrated, or signal synchronization loss |

---

## 7. Primary Broadcast Channels Reference (0x1E... Series)

| Channel Index | Primary Variable (`value_a`) | Units | Secondary Variable (`value_b`) | Description |
| :---: | :--- | :---: | :--- | :--- |
| **`0x001` (1)** | `rpm` | RPM | `rpm_status` | Engine Speed |
| **`0x002` (2)** | `fuel_pw` | ms | `fuel_pw_status` | Injector Effective Pulse Width |
| **`0x003` (3)** | `injector_duty` | % | `duty_status` | Total Injector Duty Cycle |
| **`0x004` (4)** | `closed_loop_comp` | % | `cl_status` | Active Closed-Loop Fuel Trim Correction |
| **`0x005` (5)** | `target_afr` | AFR | `target_afr_status` | Commanded Target Air/Fuel Ratio |
| **`0x006` (6)** | `afr_left` | AFR | `afr_l_status` | Wideband O2 Bank 1 |
| **`0x007` (7)** | `afr_right` | AFR | `afr_r_status` | Wideband O2 Bank 2 |
| **`0x008` (8)** | `afr_avg` | AFR | `afr_avg_status` | Average Wideband Air/Fuel Ratio |
| **`0x00D` (13)** | `current_learn` | % | `learn_status` | Active ECU Fuel Learning Correction |
| **`0x016` (22)** | `ignition_timing` | °BTDC | `timing_status` | Net Commanded Ignition Spark Advance |
| **`0x017` (23)** | `knock_retard` | ° | `knock_status` | Individual/Total Knock Ignition Retard |
| **`0x01C` (28)** | `map_kpa` | kPa | `map_status` | Manifold Absolute Pressure |
| **`0x01D` (29)** | `tps` | % | `tps_status` | Throttle Position Sensor |
| **`0x01E` (30)** | `iat` | °F | `iat_status` | Manifold Intake Air Temperature |
| **`0x01F` (31)** | `coolant_temp` | °F | `clt_status` | Engine Coolant Temperature |
| **`0x021` (33)** | `battery_voltage` | V | `batt_status` | ECU System Supply Voltage |
| **`0x022` (34)** | `oil_pressure` | psi | `oil_press_status` | Engine Oil Pressure |
| **`0x023` (35)** | `fuel_pressure` | psi | `fuel_press_status` | Fuel Rail Pressure |
| **`0x084` (132)** | `boost_psig` | psig | `boost_status` | Measured Manifold Boost Gauge Pressure |
| **`0x087` (135)** | `target_boost` | psig | `target_boost_status` | Boost Controller Target Pressure |
| **`0x088` (136)** | `trans_brake_status`| Status | `tb_status` | Transbrake / Staging Solenoid State |
| **`0x0DB` (219)** | `trans_gear` | Gear | `gear_status` | 4L80E Commanded Transmission Gear |
| **`0x0DE` (222)** | `input_speed` | RPM | `iss_status` | 4L80E Torque Converter Input Speed |
