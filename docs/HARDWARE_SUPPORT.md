# Hardware Interface & Adapter Support Matrix

**System:** EFI Intelligence Copilot  
**Status:** In Development  
**Last Updated:** September 2026

---

## 1. Supported Adapters & Transport Matrix

| Adapter Family | Bus / Transport | Driver / Backend | Supported Platforms | Compatibility Status |
|----------------|-----------------|------------------|---------------------|----------------------|
| **Official Holley USB-to-CAN Cable (558-443)** | USB 2.0 | `app.hardware.holley_usbcan` (WinUSB) | Windows | `IMPLEMENTED` / `VERIFIED` |
| **Virtual Telemetry Simulator** | Memory / In-Process | `app.hardware.simulator` | All (Win/Linux/macOS) | `IMPLEMENTED` / `VERIFIED` |
| **PEAK-System PCAN-USB / Pro** | USB 2.0 | `python-can` (`pcan`) / SocketCAN | Windows, Linux | `VERIFIED` (SocketCAN tested) |
| **CANable / candleLight** | USB 2.0 (CDC/WinUSB) | `gs_usb` / SocketCAN / `slcan` | Windows, Linux | `VERIFIED` (candleLight firmware) |
| **Kvaser Leaf Light v2** | USB 2.0 | `python-can` (`kvaser`) | Windows, Linux | `ASSUMED` (Standard CAN 2.0B) |
| **Vector VN1610 / VN1630** | USB 2.0 / 3.0 | `python-can` (`vector`) | Windows | `ASSUMED` (Standard CAN 2.0B) |
| **SocketCAN Native Adapters** | PCIe / SPI / USB | Native Linux Kernel (`can0`) | Linux | `VERIFIED` |

---

## 2. Wiring & Physical Connection Guide

### 2.1 Holley Harness Connector Pinout
On the Holley Terminator X and Terminator X MAX harnesses, the 3rd-party broadcast CAN bus terminates at a 4-pin Packard/Delphi Metri-Pack 150 male/female connector (typically labeled `CAN` or `3rd Party CAN`):

```
       ┌───────────┐
     ┌─┘  Latch    └─┐
   ┌─┴───────────────┴─┐
   │   [A]       [B]   │    Pin A: CAN High (CAN-H)
   │                   │    Pin B: CAN Low (CAN-L)
   │   [C]       [D]   │    Pin C: +12V Switched Power (Optional)
   └───────────────────┘    Pin D: Ground / Shield
```

### 2.2 Termination Resistor Installation
* A high-speed CAN bus requires exactly two $120\,\Omega$ termination resistors located at the physical ends of the bus trunk.
* If connecting a USB-CAN dongle directly to the Terminator X harness, verify whether your USB-CAN dongle includes an internal termination jumper. If not, install a $120\,\Omega$ $1/4\text{W}$ metal film resistor between Pin A (CAN-H) and Pin B (CAN-L).
* **Verification Measurement:** With the vehicle battery disconnected, measure resistance between CAN-H and CAN-L at any bus tap using a digital multimeter. The resistance **MUST** read approximately $60\,\Omega$ ($58 - 63\,\Omega$). A reading of $120\,\Omega$ indicates missing termination; $0\,\Omega$ indicates a dead short.

---

## 3. Connection Lifecycle & Graceful Reconnect

The hardware layer implements an asynchronous state machine:

```
[ DISCONNECTED ] ──(connect)──► [ CONNECTING ] ──(bus init)──► [ ACTIVE ]
       ▲                              │                           │
       │                        (init failure)               (frame timeout
       │                              ▼                       or error)
       └──────(max retries)───── [ RECONNECTING ] ◄───────────────┘
```

1. **Hot-Unplug Protection:** If the USB adapter is unplugged during an active session, the receiver catches the OS pipe error, transitions to `RECONNECTING`, and safely pauses the session without data corruption.
2. **Auto-Discovery:** Scans available COM ports and CAN interfaces to identify connected supported adapters automatically.
