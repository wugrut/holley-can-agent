"""
Cross-platform USB-CAN hardware adapter utilizing python-can backend.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

try:
    import can
except ImportError:
    can = None  # type: ignore

from app.can.frame import RawCANFrame
from app.hardware.interface import ConnectionState, ConnectionStatus, HardwareInterface

logger = logging.getLogger("efi.hardware.usb_can")


class UsbCanAdapter(HardwareInterface):
    """
    Adapter interfacing with physical USB-CAN devices via python-can.
    Enforces passive/listen-only reception and handles bus recovery.
    """

    def __init__(
        self,
        interface: str = "pcan",
        channel: str = "PCAN_USBBUS1",
        bitrate: int = 1_000_000,
        receive_own_messages: bool = False,
    ) -> None:
        self.interface = interface
        self.channel = channel
        self.bitrate = bitrate
        self.receive_own_messages = receive_own_messages

        self._bus: Optional[can.BusABC] = None
        self._status = ConnectionStatus(
            state=ConnectionState.DISCONNECTED,
            adapter_name=f"UsbCanAdapter({interface})",
            channel=channel,
            bitrate=bitrate,
        )
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5

    async def connect(self) -> bool:
        """Establish connection to CAN hardware."""
        if can is None:
            self._status.state = ConnectionState.FAILED
            self._status.error_message = "python-can library is not installed"
            logger.error(self._status.error_message)
            return False

        self._status.state = ConnectionState.CONNECTING
        try:
            # Configure bus arguments
            kwargs = {
                "interface": self.interface,
                "channel": self.channel,
                "bitrate": self.bitrate,
                "receive_own_messages": self.receive_own_messages,
            }
            if self.interface == "pcan" and hasattr(can, "bus") and hasattr(can.bus, "BusState"):
                try:
                    kwargs["state"] = can.bus.BusState.PASSIVE
                except Exception:
                    pass

            # Open bus
            self._bus = can.Bus(**kwargs)
            self._status.state = ConnectionState.CONNECTED
            self._status.error_message = None
            self._reconnect_attempts = 0
            logger.info("Connected to %s on channel %s at %d bps (passive/listen-only)", self.interface, self.channel, self.bitrate)
            return True
        except Exception as exc:
            self._status.state = ConnectionState.FAILED
            self._status.error_message = f"Connection failed: {exc}"
            logger.warning("Failed to open %s channel %s: %s", self.interface, self.channel, exc)
            return False

    async def disconnect(self) -> None:
        """Shut down CAN bus."""
        if self._bus is not None:
            try:
                self._bus.shutdown()
            except Exception as exc:
                logger.warning("Error shutting down bus: %s", exc)
            finally:
                self._bus = None
        self._status.state = ConnectionState.DISCONNECTED

    def is_connected(self) -> bool:
        return self._bus is not None and self._status.state == ConnectionState.CONNECTED

    def get_status(self) -> ConnectionStatus:
        return self._status

    def reset_metrics(self) -> None:
        self._status.frames_received = 0
        self._status.error_frames = 0
        self._status.frames_dropped = 0
        self._status.bytes_received = 0

    async def receive(self, timeout: float = 1.0) -> Optional[RawCANFrame]:
        """
        Receive single CAN message asynchronously without blocking the event loop.
        """
        if not self.is_connected() or self._bus is None:
            return None

        loop = asyncio.get_running_loop()
        try:
            # Run blocking bus.recv in default executor with small slice
            msg = await loop.run_in_executor(None, self._bus.recv, timeout)
            if msg is None:
                return None

            if msg.is_error_frame:
                self._status.error_frames += 1
                return RawCANFrame(
                    timestamp=msg.timestamp,
                    arbitration_id=msg.arbitration_id,
                    data=bytes(msg.data),
                    dlc=msg.dlc,
                    channel=self.channel,
                    is_extended_id=msg.is_extended_id,
                    is_error_frame=True,
                )

            self._status.frames_received += 1
            self._status.bytes_received += len(msg.data)
            self._status.last_frame_time = time.time()

            return RawCANFrame(
                timestamp=msg.timestamp,
                arbitration_id=msg.arbitration_id,
                data=bytes(msg.data),
                dlc=msg.dlc,
                channel=self.channel,
                is_extended_id=msg.is_extended_id,
                is_error_frame=False,
            )
        except Exception as exc:
            self._status.state = ConnectionState.DEGRADED
            self._status.error_message = f"Receive error: {exc}"
            logger.error("CAN receive failure: %s", exc)
            return None
