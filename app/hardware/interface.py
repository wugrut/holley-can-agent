"""
Hardware abstraction layer interface protocols and connection status models.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from app.can.frame import RawCANFrame


class ConnectionState(str, Enum):
    """Lifecycle states of a hardware connection."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"        # Connected but elevated error frame rate or dropouts
    RECONNECTING = "reconnecting"
    FAILED = "failed"


@dataclass
class ConnectionStatus:
    """Real-time diagnostic metrics for a physical or virtual CAN adapter."""
    state: ConnectionState = ConnectionState.DISCONNECTED
    adapter_name: str = "unknown"
    channel: str = "none"
    bitrate: int = 1_000_000
    frames_received: int = 0
    frames_dropped: int = 0
    error_frames: int = 0
    bytes_received: int = 0
    last_frame_time: float | None = None
    error_message: str | None = None

    @property
    def is_alive(self) -> bool:
        """Returns true if adapter is connected and actively receiving frames."""
        if self.state not in (ConnectionState.CONNECTED, ConnectionState.DEGRADED):
            return False
        if self.last_frame_time is None:
            return False
        return (time.time() - self.last_frame_time) < 2.0

    @property
    def error_rate_pct(self) -> float:
        """Calculates error frame percentage."""
        total = self.frames_received + self.error_frames
        if total == 0:
            return 0.0
        return (self.error_frames / total) * 100.0


@runtime_checkable
class HardwareInterface(Protocol):
    """
    Protocol contract that all CAN transports must implement.
    
    Guarantees that downstream analytics and logging layers never depend
    on a specific USB dongle, SocketCAN device, or simulation backend.
    """

    async def connect(self) -> bool:
        """Open communication channel. Returns True on success."""
        ...

    async def disconnect(self) -> None:
        """Gracefully terminate communication channel."""
        ...

    async def receive(self, timeout: float = 1.0) -> RawCANFrame | None:
        """
        Receive next raw CAN frame from the transport.
        
        Args:
            timeout: Maximum seconds to await a frame before returning None.
        """
        ...

    def is_connected(self) -> bool:
        """Returns True if the underlying link is operational."""
        ...

    def get_status(self) -> ConnectionStatus:
        """Returns copy of connection and telemetry health metrics."""
        ...

    def reset_metrics(self) -> None:
        """Resets frame and error counters."""
        ...
