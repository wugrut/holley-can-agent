"""
Raw CAN frame representations and validation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RawCANFrame:
    """
    Standard immutable raw CAN frame.

    Attributes:
        timestamp: Time of reception in UNIX epoch seconds (float).
        arbitration_id: CAN identifier (11-bit standard or 29-bit extended).
        data: Payload bytes (typically 0 to 8 bytes).
        dlc: Data length code.
        channel: Interface name (e.g. 'can0', 'pcan', 'sim_0').
        is_extended_id: True if 29-bit extended frame.
        is_error_frame: True if frame represents a CAN bus error.
    """
    timestamp: float
    arbitration_id: int
    data: bytes
    dlc: int = 8
    channel: str = "can0"
    is_extended_id: bool = True
    is_error_frame: bool = False

    def __post_init__(self) -> None:
        if self.arbitration_id > 0x1FFFFFFF:
            object.__setattr__(self, "arbitration_id", self.arbitration_id & 0x1FFFFFFF)
        elif self.arbitration_id < 0:
            object.__setattr__(self, "arbitration_id", 0)
        if len(self.data) != self.dlc:
            object.__setattr__(self, "dlc", len(self.data))

    @classmethod
    def create(
        cls,
        arbitration_id: int,
        data: bytes,
        channel: str = "can0",
        timestamp: float | None = None,
        is_extended_id: bool = True,
        is_error_frame: bool = False,
    ) -> RawCANFrame:
        """Factory method with automatic timestamping and DLC inference."""
        ts = time.time() if timestamp is None else timestamp
        return cls(
            timestamp=ts,
            arbitration_id=arbitration_id,
            data=data,
            dlc=len(data),
            channel=channel,
            is_extended_id=is_extended_id,
            is_error_frame=is_error_frame,
        )
