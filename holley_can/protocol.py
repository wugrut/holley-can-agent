"""
protocol.py — HEFI 3rd-Party CAN Communications Protocol Decoder

Decodes the Holley EFI broadcast CAN protocol used by the Terminator X Max.

CAN ID Structure (29-bit Extended):
  ┌─────────┬────────┬──────────┬──────────────────┬──────────┬────────────┐
  │ Bits    │ 31:29  │   28     │     27:25        │  24:14   │   13:11    │  10:0
  │ Field   │ Flags  │ Cmd=1    │ Target=0b111     │ Ch Index │ Src=0b010  │  Serial
  │         │  (0)   │(bcast)   │ (broadcast)      │(variable)│   (ECU)    │(ECU&0x7FF)
  └─────────┴────────┴──────────┴──────────────────┴──────────┴────────────┘

Payload: 8 bytes = two big-endian IEEE 754 floats
  Bytes 0-3: Value A (primary measurement)
  Bytes 4-7: Value B (secondary / status / quality)

Masking: AND with 0xFFFFF800 strips the ECU serial, leaving the channel index
         in bits 24:14 (shifted >> 14 gives the index number).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


# ─── CAN ID Constants ───────────────────────────────────────────────────────

# Mask to strip the ECU serial number (lower 11 bits) from extended CAN IDs.
HEFI_ID_MASK: int = 0x1FFFF800  # 29-bit safe mask

# Bits 13:11 encode the source device type.
SOURCE_ECU: int = 0b010

# Number of bits to shift right to extract the channel index from a masked ID.
CHANNEL_INDEX_SHIFT: int = 14

# Number of bits to shift right to extract the source serial (ECU serial & 0x7FF).
SERIAL_SHIFT: int = 0
SERIAL_MASK: int = 0x7FF


# ─── Channel Definitions ────────────────────────────────────────────────────

class ChannelCategory(IntEnum):
    """Logical grouping of CAN channels."""
    ENGINE = 1
    FUELING = 2
    IGNITION = 3
    TEMPERATURE = 4
    ELECTRICAL = 5
    TRANSMISSION = 6
    INPUTS = 7
    MISC = 8


@dataclass(frozen=True)
class ChannelDef:
    """Definition of a single HEFI CAN broadcast channel."""
    index: int
    name: str                  # Machine-readable key (snake_case)
    label: str                 # Human-readable label
    unit: str                  # Display unit
    category: ChannelCategory
    value_b_name: Optional[str] = None   # Name for the secondary float, if meaningful
    value_b_label: Optional[str] = None
    value_b_unit: Optional[str] = None
    min_val: Optional[float] = None
    max_val: Optional[float] = None


# Community-reverse-engineered channel map for Holley HEFI broadcast protocol.
# Sources: Nefarious Motorsports, RealDash community, HackingLZ/holley-efi-parser
#
# NOTE: Exact indices may vary by firmware version. The listener auto-discovers
# at startup and validates against this map.
CHANNEL_MAP: dict[int, ChannelDef] = {
    1: ChannelDef(
        index=1, name="rpm", label="RPM", unit="rpm",
        category=ChannelCategory.ENGINE, min_val=0, max_val=8000,
    ),
    2: ChannelDef(
        index=2, name="map_kpa", label="MAP", unit="kPa",
        category=ChannelCategory.ENGINE, min_val=0, max_val=400,
        value_b_name="baro_kpa", value_b_label="Barometric Pressure", value_b_unit="kPa",
    ),
    3: ChannelDef(
        index=3, name="tps", label="Throttle Position", unit="%",
        category=ChannelCategory.ENGINE, min_val=0, max_val=100,
    ),
    4: ChannelDef(
        index=4, name="coolant_temp", label="Coolant Temp", unit="°F",
        category=ChannelCategory.TEMPERATURE, min_val=-40, max_val=300,
    ),
    5: ChannelDef(
        index=5, name="target_afr", label="Target AFR", unit="AFR",
        category=ChannelCategory.FUELING, min_val=10, max_val=20,
    ),
    6: ChannelDef(
        index=6, name="afr_left", label="AFR Bank 1", unit="AFR",
        category=ChannelCategory.FUELING, min_val=8, max_val=22,
    ),
    7: ChannelDef(
        index=7, name="afr_right", label="AFR Bank 2", unit="AFR",
        category=ChannelCategory.FUELING, min_val=8, max_val=22,
    ),
    8: ChannelDef(
        index=8, name="afr_avg", label="AFR Average", unit="AFR",
        category=ChannelCategory.FUELING, min_val=8, max_val=22,
    ),
    9: ChannelDef(
        index=9, name="air_temp_enrich", label="Air Temp Enrichment", unit="%",
        category=ChannelCategory.FUELING,
    ),
    10: ChannelDef(
        index=10, name="coolant_enrich", label="Coolant Enrichment", unit="%",
        category=ChannelCategory.FUELING,
    ),
    11: ChannelDef(
        index=11, name="ignition_timing", label="Ignition Timing", unit="°BTDC",
        category=ChannelCategory.IGNITION, min_val=-20, max_val=50,
    ),
    12: ChannelDef(
        index=12, name="battery_voltage", label="Battery Voltage", unit="V",
        category=ChannelCategory.ELECTRICAL, min_val=0, max_val=18,
    ),
    13: ChannelDef(
        index=13, name="current_learn", label="Fuel Learn", unit="%",
        category=ChannelCategory.FUELING,
    ),
    14: ChannelDef(
        index=14, name="closed_loop", label="Closed Loop Status", unit="",
        category=ChannelCategory.FUELING,
    ),
    15: ChannelDef(
        index=15, name="iat", label="Intake Air Temp", unit="°F",
        category=ChannelCategory.TEMPERATURE, min_val=-40, max_val=300,
    ),
    16: ChannelDef(
        index=16, name="fuel_pw", label="Fuel Pulse Width", unit="ms",
        category=ChannelCategory.FUELING, min_val=0, max_val=25,
    ),
    17: ChannelDef(
        index=17, name="spark_advance", label="Spark Advance", unit="°",
        category=ChannelCategory.IGNITION,
    ),
    18: ChannelDef(
        index=18, name="idle_speed", label="Target Idle", unit="rpm",
        category=ChannelCategory.ENGINE,
    ),
    19: ChannelDef(
        index=19, name="fan_status", label="Fan Status", unit="",
        category=ChannelCategory.ELECTRICAL,
    ),
    # ── Transmission channels (Terminator X Max with 4L80E) ──
    20: ChannelDef(
        index=20, name="trans_gear", label="Current Gear", unit="",
        category=ChannelCategory.TRANSMISSION, min_val=0, max_val=4,
    ),
    21: ChannelDef(
        index=21, name="trans_temp", label="Trans Temp", unit="°F",
        category=ChannelCategory.TRANSMISSION, min_val=-40, max_val=350,
    ),
    22: ChannelDef(
        index=22, name="tcc_status", label="TCC Status", unit="%",
        category=ChannelCategory.TRANSMISSION, min_val=0, max_val=100,
    ),
    23: ChannelDef(
        index=23, name="output_speed", label="Output Shaft Speed", unit="rpm",
        category=ChannelCategory.TRANSMISSION,
    ),
    24: ChannelDef(
        index=24, name="input_speed", label="Input Shaft Speed", unit="rpm",
        category=ChannelCategory.TRANSMISSION,
    ),
    25: ChannelDef(
        index=25, name="line_pressure", label="Line Pressure", unit="psi",
        category=ChannelCategory.TRANSMISSION,
    ),
    # ── Additional engine channels ──
    30: ChannelDef(
        index=30, name="oil_pressure", label="Oil Pressure", unit="psi",
        category=ChannelCategory.ENGINE, min_val=0, max_val=100,
    ),
    31: ChannelDef(
        index=31, name="fuel_pressure", label="Fuel Pressure", unit="psi",
        category=ChannelCategory.FUELING, min_val=0, max_val=100,
    ),
    32: ChannelDef(
        index=32, name="vehicle_speed", label="Vehicle Speed", unit="mph",
        category=ChannelCategory.ENGINE, min_val=0, max_val=200,
    ),
}

# Build reverse lookup: name → ChannelDef
CHANNEL_BY_NAME: dict[str, ChannelDef] = {ch.name: ch for ch in CHANNEL_MAP.values()}


# ─── Decoded Frame ──────────────────────────────────────────────────────────

@dataclass
class DecodedFrame:
    """A decoded HEFI CAN frame."""
    timestamp: float           # Time of receipt (UNIX epoch)
    channel_index: int         # Channel index extracted from CAN ID
    channel_def: Optional[ChannelDef]  # Matched definition, if known
    value_a: float             # Primary measurement value
    value_b: float             # Secondary value (status/quality/second measurement)
    raw_id: int                # Original 29-bit CAN ID
    raw_data: bytes            # Raw 8-byte payload
    ecu_serial_bits: int       # Lower 11 bits of the ECU serial

    @property
    def name(self) -> str:
        return self.channel_def.name if self.channel_def else f"unknown_{self.channel_index}"

    @property
    def label(self) -> str:
        return self.channel_def.label if self.channel_def else f"Channel {self.channel_index}"

    @property
    def unit(self) -> str:
        return self.channel_def.unit if self.channel_def else ""


# ─── Decoder ────────────────────────────────────────────────────────────────

def extract_channel_index(can_id: int) -> int:
    """Extract the channel index (bits 24:14) from a 29-bit HEFI CAN ID."""
    return (can_id >> CHANNEL_INDEX_SHIFT) & 0x7FF


def extract_ecu_serial(can_id: int) -> int:
    """Extract the ECU serial bits (bits 10:0) from a 29-bit HEFI CAN ID."""
    return can_id & SERIAL_MASK


def decode_payload(data: bytes) -> tuple[float, float]:
    """
    Decode an 8-byte HEFI payload into two big-endian IEEE 754 floats.

    Returns:
        (value_a, value_b) — primary measurement and secondary/status value.
    """
    if len(data) != 8:
        raise ValueError(f"Expected 8 bytes, got {len(data)}")
    return struct.unpack(">ff", data)


def decode_frame(can_id: int, data: bytes, timestamp: float) -> DecodedFrame:
    """
    Fully decode a raw HEFI CAN frame.

    Args:
        can_id: 29-bit extended CAN identifier.
        data: 8-byte payload.
        timestamp: Reception timestamp (UNIX epoch).

    Returns:
        DecodedFrame with channel identification and decoded values.
    """
    channel_index = extract_channel_index(can_id)
    ecu_serial = extract_ecu_serial(can_id)
    value_a, value_b = decode_payload(data)
    channel_def = CHANNEL_MAP.get(channel_index)

    return DecodedFrame(
        timestamp=timestamp,
        channel_index=channel_index,
        channel_def=channel_def,
        value_a=value_a,
        value_b=value_b,
        raw_id=can_id,
        raw_data=data,
        ecu_serial_bits=ecu_serial,
    )


def is_hefi_broadcast(can_id: int) -> bool:
    """Check if a CAN ID looks like a valid HEFI broadcast frame."""
    # Bit 28 should be set (command/broadcast flag)
    cmd_bit = (can_id >> 28) & 1
    # Bits 27:25 should be 0b111 (broadcast target)
    target = (can_id >> 25) & 0b111
    # Bits 13:11 should be 0b010 (ECU source)
    source = (can_id >> 11) & 0b111
    return cmd_bit == 1 and target == 0b111 and source == SOURCE_ECU
