"""
Hardware Abstraction Layer (HAL).
"""

from app.hardware.interface import ConnectionState, ConnectionStatus, HardwareInterface
from app.hardware.simulator import SimulationScenario, VirtualSimulatorAdapter
from app.hardware.usb_can import UsbCanAdapter
from app.hardware.socketcan import SocketCanAdapter
from app.hardware.holley_usbcan import HolleyUsbCanAdapter
from app.hardware.detection import discover_available_adapters

__all__ = [
    "ConnectionState",
    "ConnectionStatus",
    "HardwareInterface",
    "SimulationScenario",
    "VirtualSimulatorAdapter",
    "UsbCanAdapter",
    "SocketCanAdapter",
    "HolleyUsbCanAdapter",
    "discover_available_adapters",
]
