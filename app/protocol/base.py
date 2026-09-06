"""
Abstract protocol decoder interface.
"""

from __future__ import annotations

from typing import List, Protocol, runtime_checkable

from app.can.frame import RawCANFrame
from app.telemetry.signals import TelemetrySignal


@runtime_checkable
class ProtocolDecoder(Protocol):
    """
    Protocol decoder interface responsible for transforming raw CAN frames
    into normalized TelemetrySignal instances.
    """

    def can_decode(self, frame: RawCANFrame) -> bool:
        """Returns True if the frame matches this protocol's ID pattern."""
        ...

    def decode(self, frame: RawCANFrame) -> List[TelemetrySignal]:
        """
        Decodes raw CAN frame payload into one or more TelemetrySignals.
        Returns empty list if frame cannot be decoded or is malformed.
        """
        ...
