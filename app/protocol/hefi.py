"""
Holley HEFI 29-bit broadcast protocol decoder.
"""

from __future__ import annotations

import struct
from typing import List, Optional

from app.can.frame import RawCANFrame
from app.protocol.base import ProtocolDecoder
from app.protocol.registry import VERIFIED_CHANNELS, ChannelDef, UnknownChannelTracker
from app.telemetry.quality import SignalQuality
from app.telemetry.signals import TelemetrySignal
from app.telemetry.validator import SignalValidator

# Bitfield bit shifts and masks for 29-bit HEFI identifier
HEFI_ID_MASK: int = 0x1FFFF800
CHANNEL_INDEX_SHIFT: int = 14
SERIAL_MASK: int = 0x7FF
SOURCE_ECU: int = 0b010


def extract_channel_index(can_id: int) -> int:
    """Extracts channel index (bits 24:14) from 29-bit CAN ID."""
    return (can_id >> CHANNEL_INDEX_SHIFT) & 0x7FF


def extract_ecu_serial(can_id: int) -> int:
    """Extracts lower 11 bits of ECU serial (bits 10:0)."""
    return can_id & SERIAL_MASK


def is_hefi_broadcast(can_id: int) -> bool:
    """Validates command, target, and source bitfields."""
    cmd_bit = (can_id >> 28) & 1
    target = (can_id >> 25) & 0b111
    source = (can_id >> 11) & 0b111
    return cmd_bit == 1 and target == 0b111 and source == SOURCE_ECU


class HefiProtocolDecoder(ProtocolDecoder):
    """
    Decodes Holley HEFI 29-bit broadcast frames into validated TelemetrySignals.
    """

    def __init__(self, validator: Optional[SignalValidator] = None) -> None:
        self.validator = validator or SignalValidator()
        self.unknown_tracker = UnknownChannelTracker()

    def can_decode(self, frame: RawCANFrame) -> bool:
        """Verifies if frame is an extended HEFI broadcast."""
        if not frame.is_extended_id or frame.is_error_frame or len(frame.data) != 8:
            return False
        return is_hefi_broadcast(frame.arbitration_id)

    def decode(self, frame: RawCANFrame) -> List[TelemetrySignal]:
        """Unpacks 8-byte payload into TelemetrySignal objects."""
        if not self.can_decode(frame):
            return []

        channel_index = extract_channel_index(frame.arbitration_id)
        try:
            val_a, val_b = struct.unpack(">ff", frame.data)
        except Exception:
            return []

        signals: List[TelemetrySignal] = []
        source_tag = "simulator" if "sim" in frame.channel else "can"
        channel_def = VERIFIED_CHANNELS.get(channel_index)

        if channel_def is None:
            # Unmapped / unverified channel index
            self.unknown_tracker.record_unknown(channel_index)
            # Emit as unverified telemetry signal without crashing
            sig_a = TelemetrySignal(
                signal_name=f"unverified_ch_{channel_index}_a",
                value=val_a,
                unit="raw",
                timestamp=frame.timestamp,
                source=source_tag,
                quality=SignalQuality.ESTIMATED,
                confidence=0.3,
                raw_channel_index=channel_index,
            )
            signals.append(sig_a)
            return signals

        # 1. Primary Value A
        sig_a = self.validator.validate(
            signal_name=channel_def.name,
            value=val_a,
            unit=channel_def.unit,
            timestamp=frame.timestamp,
            source=source_tag,
            raw_channel_index=channel_index,
        )
        signals.append(sig_a)

        # 2. Secondary Value B (if defined in channel definition)
        if channel_def.value_b_name:
            sig_b = self.validator.validate(
                signal_name=channel_def.value_b_name,
                value=val_b,
                unit=channel_def.value_b_unit or "",
                timestamp=frame.timestamp,
                source=source_tag,
                raw_channel_index=channel_index,
            )
            signals.append(sig_b)

        return signals
