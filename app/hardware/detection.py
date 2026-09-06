"""
Hardware adapter detection and environment discovery.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List


def discover_available_adapters() -> List[Dict[str, Any]]:
    """
    Detects potential CAN interfaces available on the host system.
    Returns list of discovered devices and recommended adapter configurations.
    """
    adapters: List[Dict[str, Any]] = [
        {
            "adapter_type": "simulator",
            "name": "Virtual Telemetry Simulator",
            "channel": "sim_virtual0",
            "available": True,
            "recommended": False,
            "description": "In-memory simulator supporting 10 operational profiles and fault injection",
        }
    ]

    # Check for Linux SocketCAN interfaces
    if sys.platform.startswith("linux"):
        import os
        net_dir = "/sys/class/net"
        if os.path.exists(net_dir):
            for iface in os.listdir(net_dir):
                type_file = os.path.join(net_dir, iface, "type")
                if os.path.exists(type_file):
                    try:
                        with open(type_file, "r") as f:
                            # 280 is ARPHRD_CAN
                            if f.read().strip() == "280":
                                adapters.append({
                                    "adapter_type": "socketcan",
                                    "name": f"Linux SocketCAN ({iface})",
                                    "channel": iface,
                                    "available": True,
                                    "recommended": True,
                                    "description": f"Kernel CAN network interface {iface}",
                                })
                    except Exception:
                        pass

    # Check for serial COM ports on Windows/cross-platform (CANable / SLCAN)
    try:
        import serial.tools.list_ports
        ports = serial.tools.list_ports.comports()
        for p in ports:
            desc = p.description or ""
            is_can_device = any(keyword in desc.lower() for keyword in ["canable", "candlelight", "slcan", "can"])
            adapters.append({
                "adapter_type": "slcan",
                "name": f"SLCAN / Serial ({p.device} - {desc})",
                "channel": p.device,
                "available": True,
                "recommended": is_can_device,
                "description": f"Serial-based CAN interface on {p.device} ({desc})",
            })
    except ImportError:
        pass

    # Check for python-can installed backends
    try:
        import can

        # Check for PCAN-USB availability
        pcan_available = False
        if sys.platform == "win32":
            import os
            sys32 = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "PCANBasic.dll")
            syswow64 = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "SysWOW64", "PCANBasic.dll")
            if os.path.exists(sys32) or os.path.exists(syswow64):
                pcan_available = True

        adapters.append({
            "adapter_type": "pcan",
            "name": "PEAK PCAN-USB (Channel 1)",
            "channel": "PCAN_USBBUS1",
            "available": True,
            "recommended": pcan_available,
            "description": "PEAK-System PCAN-USB at 1 Mbps listen-only mode" + (" (PCANBasic.dll detected)" if pcan_available else ""),
        })

        adapters.append({
            "adapter_type": "usb_can",
            "name": "Generic python-can USB Adapter",
            "channel": "PCAN_USBBUS1",
            "available": True,
            "recommended": False,
            "description": "Configurable python-can backend adapter",
        })
    except ImportError:
        pass

    return adapters

