"""
CAN protocol decoding layer.
"""

from app.protocol.base import ProtocolDecoder
from app.protocol.registry import (
    ChannelCategory,
    ChannelDef,
    SignalProvenance,
    UnknownChannelTracker,
    VERIFIED_CHANNELS,
    VerificationStatus,
)
from app.protocol.hefi import HefiProtocolDecoder, extract_channel_index, extract_ecu_serial, is_hefi_broadcast

__all__ = [
    "ProtocolDecoder",
    "ChannelCategory",
    "ChannelDef",
    "SignalProvenance",
    "VerificationStatus",
    "VERIFIED_CHANNELS",
    "UnknownChannelTracker",
    "HefiProtocolDecoder",
    "extract_channel_index",
    "extract_ecu_serial",
    "is_hefi_broadcast",
]
