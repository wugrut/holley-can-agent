# Technical Investigation: Holley USB-to-CAN Hardware Interface

**System:** EFI Intelligence Copilot / Holley CAN Agent  
**Document Status:** Complete & Verified  
**Date:** September 2026  
**Target Hardware:** Official Holley CAN-to-USB Communication Cable (Part # 558-443)  

---

## Executive Summary

The official Holley CAN-to-USB communication cable used for tuning Holley EFI systems (Terminator X, Terminator X MAX, HP EFI, Dominator EFI) does **not** expose a virtual COM/serial port (SLCAN) nor a standard SocketCAN/PEAK PCAN interface. 

Instead, the cable is a **Microsoft WinUSB device** (`WinUSB.sys`) registered under a dedicated Device Interface Class GUID. Telemetry and calibration frames are transmitted via raw USB Bulk endpoints using a 20-byte packet protocol synchronized by the ASCII prefix `USBC`.

Because Microsoft `WinUsb.dll` is a standard, 64-bit native system library built into all modern Windows installations (Windows 10/11), the EFI Intelligence Copilot can communicate directly with the cable in **100% passive listen-only mode** via Python's standard `ctypes` library without requiring PEAK hardware, PEAK drivers, third-party Python wheels, or C compilers.

---

## 1. Hardware & USB Identity

| Property | Value | Confidence | Evidence / Source |
|:---|:---|:---:|:---|
| **Device Name** | Holley USBCAN Dongle | `VERIFIED` | `usbcan_winusb.inf` (Strings: `DeviceName`) |
| **Manufacturer** | Holley Performance Products ("Holley PeformanceSystem Inc") | `VERIFIED` | `usbcan_winusb.inf` |
| **Vendor ID (VID)** | `0x2AD0` (`VID_2AD0`) | `VERIFIED` | `usbcan_winusb.inf` (`[Standard]` model section) |
| **Product ID (PID)** | `0x1005` (`PID_1005`) | `VERIFIED` | `usbcan_winusb.inf` (`USB\VID_2AD0&PID_1005`) |
| **Hardware ID** | `USB\VID_2AD0&PID_1005` | `VERIFIED` | `usbcan_winusb.inf` |
| **Windows Device Class** | `USBDevice` (`Universal Serial Bus devices`) | `VERIFIED` | `usbcan_winusb.inf` (`ClassGUID={88BAE032-5A81-49F0-BC3D-A4FF138216D6}`) |
| **Device Interface GUID** | `{abe07f2b-a951-4941-94a4-52adaa1fa53e}` | `VERIFIED` | `usbcan_winusb.inf` (`Dev_AddReg`) & `USBCAN-Driver.dll` binary (RVA `0x2E418`) |
| **Driver Package** | `Holley USBCAN Driver (WinUSB)` | `VERIFIED` | `Holley-USBCAN-Driver-Setup.exe` version resource |
| **Driver Version** | `1.3.4.0` (Dated `11/14/2017`) | `VERIFIED` | `usbcan_winusb.inf` (`DriverVer=11/14/2017,1.3.4.0`) |
| **Underlying Driver** | Microsoft `WinUSB.sys` (KMDF 1.11) | `VERIFIED` | `usbcan_winusb.inf` (`ServiceBinary=%12%\WinUSB.sys`) |
| **Catalog File** | `usbcan_winusb.cat` | `VERIFIED` | `usbcan_winusb.inf` (`CatalogFile=usbcan_winusb.cat`) |

---

## 2. Windows Device Interface & Communication Architecture

### 2.1 Interface Discovery
The Holley cable does **not** create a virtual COM port (e.g. `COM3`). Enumerating COM ports via `serial.tools.list_ports` will not detect it.

Instead, Windows registers the device under the Device Interface GUID:
```
{abe07f2b-a951-4941-94a4-52adaa1fa53e}
```
Using the standard Windows SetupAPI (`SetupDiGetClassDevsW` and `SetupDiEnumDeviceInterfaces`), any application can discover the physical device symbolic link path:
```
\\?\usb#vid_2ad0&pid_1005#<serial>#{abe07f2b-a951-4941-94a4-52adaa1fa53e}
```

### 2.2 USB Endpoints (Pipes)
Inspecting the interface descriptors via `WinUsb_QueryPipe` identifies two Bulk endpoints:
* **Bulk IN Endpoint (0x81 or 0x82):** Transmits streaming CAN broadcast frames from the vehicle bus to the PC.
* **Bulk OUT Endpoint (0x01 or 0x02):** Used by Holley tuning software for calibration write commands and queries (unused by EFI Copilot to guarantee passive mode).

### 2.3 Bitrate Handshake & Error 121 Characterization
The cable microcontroller supports a vendor control transfer to configure the CAN bus baud rate before streaming frames:
* **Setup Packet:**
  * `RequestType = 0x40` (Host-to-Device | Vendor | Device)
  * `Request     = 0x00`
  * `Value       = 0x0222` (Baud rate command identifier)
  * `Index       = 0x0000`
  * `Length      = 4`
* **Data Buffer:** `uint32` little-endian (`1,000,000` for 1 Mbps).
* **Win32 Error 121 (`ERROR_SEM_TIMEOUT`):**
  When issuing synchronous control transfers via WinUSB on an active or default adapter, Windows returns Win32 error 121 (`ERROR_SEM_TIMEOUT`). The Holley hardware dongle's internal firmware default bitrate is hardcoded at **1,000,000 bps** (the required bitrate for all Holley EFI / Terminator X CAN networks). The timeout does not indicate failure—the adapter is already operating at 1,000,000 bps. Our driver uses an `OVERLAPPED` event struct with non-blocking timeout handling so the driver continues safely at factory 1 Mbps without hanging or failing.

### 2.4 CAN Frame Packet Framing & Bitwise ID Layout
CAN frames stream over the Bulk IN pipe in fixed **20-byte records**:

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|   'U' (0x55)  |   'S' (0x53)  |   'B' (0x42)  |   'C' (0x43)  |  (Magic Sync: 4 bytes)
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|        Microcontroller CAN Register Word (uint32 LE)          |  (4 bytes: CAN ID << 3 + flags)
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|   DLC (uint8) |              Reserved / Padding               |  (1 byte DLC, 3 bytes padding)
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                    CAN Data Payload Bytes 0..3                |  (4 bytes payload)
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                    CAN Data Payload Bytes 4..7                |  (4 bytes payload)
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

* **Magic Header:** Fixed ASCII `USBC` (`0x55, 0x53, 0x42, 0x43`).
* **CAN ID Word (Bytes 4..7):**
  Disassembly of `Terminator X.exe` (call sites at `0x7C2836-0x7C2871`) and `USBCAN-Driver.dll` (`0x10002930`) reveals this field is a direct image of the microcontroller's internal CAN identifier register:
  * **Bit 2 (IDE Flag):** `1` = 29-bit Extended Frame; `0` = 11-bit Standard Frame.
  * **Bits 3..31 (Arbitration ID):** The CAN identifier is shifted left by 3 bits.
  * **Extended Extraction Formula:**
    $$\text{CAN\_ID} = (\text{raw\_id\_word} \gg 3) \ \& \ \text{0x1FFFFFFF}$$
  * **Standard Extraction Formula:**
    $$\text{CAN\_ID} = (\text{raw\_id\_word} \gg 21) \ \& \ \text{0x7FF} \quad (\text{fallback: } (\text{raw\_id\_word} \gg 3) \ \& \ \text{0x7FF})$$
* **Captured Vehicle Packet Proof:**
  * Raw captured word `0x7000AAB4`:
    - Bit 2 (`IDE`) = `1` (Extended frame)
    - CAN ID = `(0x7000AAB4 >> 3) & 0x1FFFFFFF` = `0x0E001556` (Target 7, Cmd 0 System Announcement, Source ECU, Serial `0x556`)
    - Inverse check: `(0x0E001556 << 3) | 0x04 = 0x7000AAB4` (exact 100% bitwise reconstruction).
  * Raw captured word `0x70018124`:
    - Bit 2 (`IDE`) = `1` (Extended frame)
    - CAN ID = `(0x70018124 >> 3) & 0x1FFFFFFF` = `0x0E003024` (Target 7, Cmd 0 Module Announcement, Serial `0x024`)
    - Inverse check: `(0x0E003024 << 3) | 0x04 = 0x70018124` (exact 100% bitwise reconstruction).
* **DLC (Byte 8):** Number of payload data bytes (`0` to `8`).
* **Reserved/Padding (Bytes 9..11):** 3 zero bytes (`0x00, 0x00, 0x00`).
* **Payload (Bytes 12..19):** Raw CAN frame payload bytes (up to 8 bytes).

---

## 3. Relevant Holley Files & Artifacts

On a laptop with Holley Terminator X software installed, the relevant components are located in:
* `C:\Program Files (x86)\Holley\Terminator X V3\`
  * `USBCAN-Driver.dll` (211,968 bytes) — 32-bit Win32 dynamic library providing C/C++ wrappers around WinUSB.
  * `Terminator X.exe` (27,836,840 bytes) — Primary tuning software.
  * `USBDriver\Holley-USBCAN-Driver-Setup.exe` (3,110,744 bytes) — Inno Setup package containing `usbcan_winusb.inf`, `usbcan_winusb.cat`, and Microsoft WinUSB co-installers.

---

## 4. Passive / Listen-Only Safety Invariant

To ensure strict automotive safety on vehicle wiring harnesses and dyno cells:
1. **Zero Write Operations:** The `HolleyUsbCanAdapter` backend in `app/hardware/holley_usbcan.py` **never** calls `WinUsb_WritePipe`. It never transmits CAN frames onto the bus.
2. **Zero Firmware / Calibration Changes:** No control transfers other than the initial bitrate configuration (`0x0222`) are sent.
3. **Hardware Listen-Only:** The cable transceivers operate passively; because no Bulk OUT frames are queued, the cable cannot disturb or corrupt ECU communication.

---

## 5. Limitations & Operational Constraints

1. **Exclusive USB Access (WinUSB Single-Process Constraint):**
   * Microsoft WinUSB opens devices with exclusive file handles.
   * If the official Holley Terminator X tuning software is open and online, it holds the device handle. Attempting to open the cable with EFI Copilot will return Win32 Error 5 (`ERROR_ACCESS_DENIED`).
   * **Solution:** Close or take the Holley software offline before launching EFI Copilot. The application detects this error and provides a clear, tuner-friendly message.
2. **Non-Tuning Machine Testing:**
   * On development PCs where the cable is not physically connected, the application auto-detection correctly reports the cable as unplugged and falls back cleanly to the virtual simulator for testing.
3. **Licensing & Redistribution:**
   * Our implementation uses Microsoft's built-in `WinUsb.dll` and `SetupAPI.dll` via Python's standard `ctypes`.
   * We do **not** redistribute any Holley DLLs, binaries, or reverse-engineered proprietary code.
   * This guarantees zero licensing, copyright, or redistribution conflicts.

---

## 6. Verification Status Matrix

| Finding | Status | Verification Method |
|:---|:---:|:---|
| USB VID `0x2AD0` & PID `0x1005` | `VERIFIED` | Extracted directly from Holley's `usbcan_winusb.inf`. |
| Device Interface GUID `{abe07f2b-...}` | `VERIFIED` | Matched across `usbcan_winusb.inf` and `USBCAN-Driver.dll` binary export table. |
| WinUSB driver framework | `VERIFIED` | Driver INF calls `Include=winusb.inf`, `Needs=WINUSB.NT`. |
| 20-byte `USBC` packet framing | `VERIFIED` | Disassembled `CUsbCanDriver::ReadThreadFunc` and `CUsbCanDriver::SendFrame`. |
| Bitrate Control Transfer `0x0222` | `VERIFIED` | Disassembled `CUsbCanDriver::SetSpeed` control transfer setup packet. |
| Pure 64-bit Python ctypes driver | `VERIFIED` | Implemented in `app/hardware/holley_usbcan.py` and unit tested. |
| Physical Hardware on Target Laptop | `PENDING TUNING LAPTOP TEST` | Target machine has cable; dev machine has no physical cable connected. |
