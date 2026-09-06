"""
Native Linux SocketCAN adapter with kernel buffering and link state monitoring.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.hardware.interface import ConnectionState, ConnectionStatus
from app.hardware.usb_can import UsbCanAdapter

logger = logging.getLogger("efi.hardware.socketcan")


class SocketCanAdapter(UsbCanAdapter):
    """
    Specialized hardware adapter for Linux SocketCAN interfaces (e.g. can0, vcan0).
    Inherits UsbCanAdapter while enforcing SocketCAN driver conventions.
    """

    def __init__(
        self,
        channel: str = "can0",
        bitrate: int = 1_000_000,
        fd: bool = False,
    ) -> None:
        super().__init__(
            interface="socketcan",
            channel=channel,
            bitrate=bitrate,
            receive_own_messages=False,
        )
        self.fd = fd
        self._status = ConnectionStatus(
            state=ConnectionState.DISCONNECTED,
            adapter_name=f"SocketCanAdapter({channel})",
            channel=channel,
            bitrate=bitrate,
        )
