"""
protocol.py — Unified Holley HEFI 29-Bit & Racepak CAN Communications Protocol Decoder

Supports BOTH broadcast modes available on the Holley Terminator X / X MAX:
  1. Holley Standard (HEFI 29-bit IEEE 754 float32 broadcast, matching official
     'HP Dominator & Terminator X DBC.dbc' & 'HARDWIRE HOLLEY DBC FILE.dbc')
  2. Racepak (CAN Bus 2 'Racepak' mode, packing two signed int32BE / 256.0
     fixed-point values per 8-byte frame, ported from AutoDashBackEnd/racepakDecoder.js)

CAN ID Structure (29-bit Extended):
  ┌─────────┬────────┬──────────┬──────────────────┬──────────┬────────────┐
  │ Bits    │ 31:29  │   28     │     27:25        │  24:14   │   13:11    │  10:0      │
  │ Field   │ Flags  │ Cmd=1    │ Target=0b111/000 │ Ch Index │ Src=0b010  │  Serial    │
  │         │  (0)   │(bcast)   │ (broadcast)      │(variable)│   (ECU)    │(ECU&0x7FF) │
  └─────────┴────────┴──────────┴──────────────────┴──────────┴────────────┘
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Callable, Optional


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
    BOOST = 9


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


# Official Holley DBC Channel Map (verified against HP Dominator & Terminator X DBC.dbc
# and HARDWIRE HOLLEY DBC FILE.dbc from holley-efi-parser).
CHANNEL_MAP: dict[int, ChannelDef] = {
    # ── Core Engine & Fueling (Indices 1–21) ──
    1: ChannelDef(
        index=1, name="rpm", label="RPM", unit="rpm",
        category=ChannelCategory.ENGINE, min_val=0, max_val=10000,
    ),
    2: ChannelDef(
        index=2, name="fuel_pw", label="Fuel Pulse Width", unit="ms",
        category=ChannelCategory.FUELING, min_val=0, max_val=30,
    ),
    3: ChannelDef(
        index=3, name="injector_duty", label="Injector Duty Cycle", unit="%",
        category=ChannelCategory.FUELING, min_val=0, max_val=100,
    ),
    4: ChannelDef(
        index=4, name="closed_loop_comp", label="Closed Loop Comp", unit="%",
        category=ChannelCategory.FUELING, min_val=-50, max_val=50,
    ),
    5: ChannelDef(
        index=5, name="target_afr", label="Target AFR", unit="AFR",
        category=ChannelCategory.FUELING, min_val=8, max_val=22,
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
        index=11, name="coolant_afr_offset", label="Coolant AFR Offset", unit="AFR",
        category=ChannelCategory.FUELING,
    ),
    12: ChannelDef(
        index=12, name="afterstart_enrich", label="Afterstart Enrichment", unit="%",
        category=ChannelCategory.FUELING,
    ),
    13: ChannelDef(
        index=13, name="current_learn", label="Fuel Learn", unit="%",
        category=ChannelCategory.FUELING, min_val=-50, max_val=50,
    ),
    14: ChannelDef(
        index=14, name="closed_loop", label="Closed Loop Status", unit="",
        category=ChannelCategory.FUELING,
    ),
    15: ChannelDef(
        index=15, name="learn_status", label="Learn Status", unit="",
        category=ChannelCategory.FUELING,
    ),
    16: ChannelDef(
        index=16, name="fuel_economy", label="Fuel Economy", unit="mpg",
        category=ChannelCategory.FUELING,
    ),
    17: ChannelDef(
        index=17, name="fuel_flow", label="Fuel Flow", unit="lb/hr",
        category=ChannelCategory.FUELING, min_val=0, max_val=2000,
    ),
    18: ChannelDef(
        index=18, name="map_roc", label="MAP Rate of Change", unit="kPa/s",
        category=ChannelCategory.ENGINE,
    ),
    19: ChannelDef(
        index=19, name="tps_roc", label="TPS Rate of Change", unit="%/s",
        category=ChannelCategory.ENGINE,
    ),
    20: ChannelDef(
        index=20, name="tuning_change", label="Tuning Change", unit="%",
        category=ChannelCategory.FUELING,
    ),
    21: ChannelDef(
        index=21, name="estimated_ve", label="Estimated VE", unit="%",
        category=ChannelCategory.FUELING, min_val=0, max_val=200,
    ),
    # ── Ignition & Knock (Indices 22–24) ──
    22: ChannelDef(
        index=22, name="ignition_timing", label="Ignition Timing", unit="°BTDC",
        category=ChannelCategory.IGNITION, min_val=-20, max_val=60,
    ),
    23: ChannelDef(
        index=23, name="knock_retard", label="Knock Retard", unit="°",
        category=ChannelCategory.IGNITION, min_val=0, max_val=30,
    ),
    24: ChannelDef(
        index=24, name="knock_level", label="Knock Level", unit="%",
        category=ChannelCategory.IGNITION, min_val=0, max_val=100,
    ),
    # ── Idle Control (Indices 26–27) ──
    26: ChannelDef(
        index=26, name="iac_position", label="IAC Position", unit="%",
        category=ChannelCategory.ENGINE, min_val=0, max_val=100,
    ),
    27: ChannelDef(
        index=27, name="idle_speed", label="Target Idle", unit="rpm",
        category=ChannelCategory.ENGINE, min_val=0, max_val=3000,
    ),
    # ── Primary Engine Sensors (Indices 28–36) ──
    28: ChannelDef(
        index=28, name="map_kpa", label="MAP", unit="kPa",
        category=ChannelCategory.ENGINE, min_val=0, max_val=500,
        value_b_name="baro_kpa", value_b_label="Barometric Pressure", value_b_unit="kPa",
    ),
    29: ChannelDef(
        index=29, name="tps", label="Throttle Position", unit="%",
        category=ChannelCategory.ENGINE, min_val=0, max_val=100,
    ),
    30: ChannelDef(
        index=30, name="iat", label="Intake Air Temp", unit="°F",
        category=ChannelCategory.TEMPERATURE, min_val=-40, max_val=300,
    ),
    31: ChannelDef(
        index=31, name="coolant_temp", label="Coolant Temp", unit="°F",
        category=ChannelCategory.TEMPERATURE, min_val=-40, max_val=320,
    ),
    32: ChannelDef(
        index=32, name="baro_kpa", label="Barometric Pressure", unit="kPa",
        category=ChannelCategory.ENGINE, min_val=50, max_val=120,
    ),
    33: ChannelDef(
        index=33, name="battery_voltage", label="Battery Voltage", unit="V",
        category=ChannelCategory.ELECTRICAL, min_val=0, max_val=20,
    ),
    34: ChannelDef(
        index=34, name="oil_pressure", label="Oil Pressure", unit="psi",
        category=ChannelCategory.ENGINE, min_val=0, max_val=150,
    ),
    35: ChannelDef(
        index=35, name="fuel_pressure", label="Fuel Pressure", unit="psi",
        category=ChannelCategory.FUELING, min_val=0, max_val=150,
    ),
    36: ChannelDef(
        index=36, name="pedal_position", label="Pedal Position", unit="%",
        category=ChannelCategory.INPUTS, min_val=0, max_val=100,
    ),
    # ── System Status, Rev Limiters & Outputs (Indices 37–60) ──
    37: ChannelDef(
        index=37, name="rev_limit_main", label="Main Rev Limit Status", unit="",
        category=ChannelCategory.IGNITION,
    ),
    38: ChannelDef(
        index=38, name="rev_limit_1", label="Rev Limit #1 Status", unit="",
        category=ChannelCategory.IGNITION,
    ),
    39: ChannelDef(
        index=39, name="rev_limit_2", label="Rev Limit #2 Status", unit="",
        category=ChannelCategory.IGNITION,
    ),
    41: ChannelDef(
        index=41, name="timing_retard_1", label="Timing Retard #1", unit="°",
        category=ChannelCategory.IGNITION,
    ),
    42: ChannelDef(
        index=42, name="timing_retard_2", label="Timing Retard #2", unit="°",
        category=ChannelCategory.IGNITION,
    ),
    43: ChannelDef(
        index=43, name="timing_retard_3", label="Timing Retard #3", unit="°",
        category=ChannelCategory.IGNITION,
    ),
    44: ChannelDef(
        index=44, name="fan_status", label="Fan #1 Status", unit="",
        category=ChannelCategory.ELECTRICAL,
    ),
    45: ChannelDef(
        index=45, name="fan2_status", label="Fan #2 Status", unit="",
        category=ChannelCategory.ELECTRICAL,
    ),
    46: ChannelDef(
        index=46, name="fuel_pump2_status", label="Fuel Pump #2 Status", unit="",
        category=ChannelCategory.FUELING,
    ),
    48: ChannelDef(
        index=48, name="lockup_status", label="Converter Lockup Status", unit="",
        category=ChannelCategory.TRANSMISSION,
    ),
    49: ChannelDef(
        index=49, name="sensor_warning", label="Sensor Warning Status", unit="",
        category=ChannelCategory.MISC,
    ),
    50: ChannelDef(
        index=50, name="sensor_caution", label="Sensor Caution Status", unit="",
        category=ChannelCategory.MISC,
    ),
    51: ChannelDef(
        index=51, name="base_fuel_lb", label="Base Fuel Flow", unit="lb/hr",
        category=ChannelCategory.FUELING,
    ),
    52: ChannelDef(
        index=52, name="base_fuel_ve", label="Base Fuel VE", unit="%",
        category=ChannelCategory.FUELING,
    ),
    53: ChannelDef(
        index=53, name="spark_advance", label="Base Timing", unit="°",
        category=ChannelCategory.IGNITION,
    ),
    54: ChannelDef(
        index=54, name="base_target_afr", label="Base Target AFR", unit="AFR",
        category=ChannelCategory.FUELING,
    ),
    55: ChannelDef(
        index=55, name="base_ign_dwell", label="Base Ignition Dwell", unit="ms",
        category=ChannelCategory.IGNITION,
    ),
    # ── Boost Control & Antilag (Indices 125–148) ──
    125: ChannelDef(
        index=125, name="target_fuel_pressure", label="Target Fuel Pressure", unit="psi",
        category=ChannelCategory.FUELING, min_val=0, max_val=150,
    ),
    126: ChannelDef(
        index=126, name="system_boost_psig", label="System Boost", unit="psig",
        category=ChannelCategory.BOOST, min_val=0, max_val=60,
    ),
    130: ChannelDef(
        index=130, name="boost_gear", label="Boost Gear", unit="",
        category=ChannelCategory.BOOST,
    ),
    131: ChannelDef(
        index=131, name="boost_stage", label="Boost Manual Stage", unit="",
        category=ChannelCategory.BOOST,
    ),
    132: ChannelDef(
        index=132, name="boost_psig", label="Boost Pressure", unit="psig",
        category=ChannelCategory.BOOST, min_val=0, max_val=60,
    ),
    133: ChannelDef(
        index=133, name="boost_speed", label="Boost Speed", unit="mph",
        category=ChannelCategory.BOOST,
    ),
    134: ChannelDef(
        index=134, name="boost_time", label="Boost Timer", unit="s",
        category=ChannelCategory.BOOST,
    ),
    135: ChannelDef(
        index=135, name="target_boost", label="Target Boost", unit="psig",
        category=ChannelCategory.BOOST, min_val=0, max_val=60,
    ),
    136: ChannelDef(
        index=136, name="trans_brake_status", label="Trans Brake Status", unit="",
        category=ChannelCategory.BOOST,
    ),
    141: ChannelDef(
        index=141, name="boost_build_status", label="Boost Builder / Antilag Status", unit="",
        category=ChannelCategory.BOOST,
    ),
    142: ChannelDef(
        index=142, name="boost_solenoid_duty", label="Boost Solenoid Duty", unit="%",
        category=ChannelCategory.BOOST, min_val=0, max_val=100,
    ),
    143: ChannelDef(
        index=143, name="boost_safety", label="Boost Safety Status", unit="",
        category=ChannelCategory.BOOST,
    ),
    147: ChannelDef(
        index=147, name="boost_fill_duty", label="Dome Fill Solenoid Duty", unit="%",
        category=ChannelCategory.BOOST,
    ),
    148: ChannelDef(
        index=148, name="boost_vent_duty", label="Dome Vent Solenoid Duty", unit="%",
        category=ChannelCategory.BOOST,
    ),
    # ── Transmission Channels (Terminator X MAX 4L60E / 4L80E, Indices 219–230, 496–498) ──
    219: ChannelDef(
        index=219, name="trans_gear", label="Current Gear", unit="",
        category=ChannelCategory.TRANSMISSION, min_val=0, max_val=6,
    ),
    220: ChannelDef(
        index=220, name="vehicle_speed", label="Vehicle Speed", unit="mph",
        category=ChannelCategory.TRANSMISSION, min_val=0, max_val=250,
    ),
    221: ChannelDef(
        index=221, name="line_pressure", label="Line Pressure PWM", unit="%",
        category=ChannelCategory.TRANSMISSION, min_val=0, max_val=100,
    ),
    222: ChannelDef(
        index=222, name="input_speed", label="Input Shaft Speed", unit="rpm",
        category=ChannelCategory.TRANSMISSION, min_val=0, max_val=10000,
    ),
    223: ChannelDef(
        index=223, name="output_speed", label="Accum Pressure / Output Speed", unit="%",
        category=ChannelCategory.TRANSMISSION,
    ),
    224: ChannelDef(
        index=224, name="tcc_status", label="TCC Duty Cycle", unit="%",
        category=ChannelCategory.TRANSMISSION, min_val=0, max_val=100,
    ),
    225: ChannelDef(
        index=225, name="trans_temp", label="Trans Temp", unit="°F",
        category=ChannelCategory.TRANSMISSION, min_val=-40, max_val=350,
    ),
    230: ChannelDef(
        index=230, name="trans_range_pos", label="4L80E Range Switch Pos", unit="",
        category=ChannelCategory.TRANSMISSION,
    ),
    238: ChannelDef(
        index=238, name="dbw_tb_position", label="DBW Throttle Body Pos", unit="%",
        category=ChannelCategory.INPUTS, min_val=0, max_val=100,
    ),
    # ── Terminator X MAX Custom Inputs / Advanced Tables (Flex Fuel & Sloppy Transbrake) ──
    262: ChannelDef(
        index=262, name="adv_launch_input", label="Adv Launch Input", unit="",
        category=ChannelCategory.INPUTS,
    ),
    266: ChannelDef(
        index=266, name="adv_1d_1", label="Adv 1D Table #1 (Flex Fuel Offset)", unit="%",
        category=ChannelCategory.FUELING,
    ),
    274: ChannelDef(
        index=274, name="adv_2d_1", label="Adv 2D Table #1 (Staging Timing Retard)", unit="°",
        category=ChannelCategory.IGNITION,
    ),
    298: ChannelDef(
        index=298, name="ethanol_pct", label="Flex Fuel Ethanol % (IO Input 1)", unit="%",
        category=ChannelCategory.FUELING, min_val=0, max_val=100,
    ),
    299: ChannelDef(
        index=299, name="io_input_2", label="IO Input #2", unit="",
        category=ChannelCategory.INPUTS,
    ),
    300: ChannelDef(
        index=300, name="io_input_3", label="IO Input #3", unit="",
        category=ChannelCategory.INPUTS,
    ),
    301: ChannelDef(
        index=301, name="io_input_4", label="IO Input #4", unit="",
        category=ChannelCategory.INPUTS,
    ),
    475: ChannelDef(
        index=475, name="staging_input_1", label="Staging / Transbrake Input #1", unit="",
        category=ChannelCategory.BOOST,
    ),
    498: ChannelDef(
        index=498, name="line_pressure_psi", label="Actual Line Pressure", unit="psi",
        category=ChannelCategory.TRANSMISSION, min_val=0, max_val=300,
    ),
    # ── Race / Launch / Spool Assist (Indices 499–524) ──
    499: ChannelDef(
        index=499, name="launch_status", label="Race Launch Status", unit="",
        category=ChannelCategory.BOOST,
    ),
    519: ChannelDef(
        index=519, name="spool_assist_status", label="Spool Assist / Antilag Output", unit="",
        category=ChannelCategory.BOOST,
    ),
}

# Build reverse lookup: name → ChannelDef
CHANNEL_BY_NAME: dict[str, ChannelDef] = {ch.name: ch for ch in CHANNEL_MAP.values()}


# ─── Racepak CAN Bus 2 Protocol Map (Ported from AutoDashBackEnd) ───────────
# When Terminator X V3 -> Basic I/O -> CAN Bus -> CAN Bus 2 Type is set to "Racepak",
# the ECU broadcasts 8-byte frames on 0x1E001000..0x1E049000 containing TWO
# big-endian signed 32-bit integers scaled by 1/256.0 (or 1/1000.0 for RTC).

RACEPAK_CAN_MAP: dict[int, tuple[tuple[str, float], Optional[tuple[str, float]]]] = {
    0x1E001000: (("rpm", 256.0), None),                         # Bytes 0..3: RTC (ms), Bytes 4..7: RPM * 256
    0x1E005000: (("fuel_pw", 256.0), ("fuel_flow", 256.0)),     # Injector PW (ms), Fuel Flow (lb/hr)
    0x1E009000: (("closed_loop", 256.0), ("injector_duty", 256.0)),  # CL Status, Duty Cycle (%)
    0x1E00D000: (("afr_left", 256.0), ("closed_loop_comp", 256.0)),  # AFR Left, CL Comp (%)
    0x1E011000: (("target_afr", 256.0), ("afr_right", 256.0)),  # Target AFR, AFR Right
    0x1E015000: (("ignition_timing", 256.0), ("afr_avg", 256.0)),    # Ignition Timing (deg), AFR Average
    0x1E019000: (("map_kpa", 256.0), ("knock_retard", 256.0)),  # MAP (kPa), Knock Retard (deg)
    0x1E01D000: (("iat", 256.0), ("tps", 256.0)),               # MAT (°F), TPS (%)
    0x1E021000: (("baro_kpa", 256.0), ("coolant_temp", 256.0)), # Baro (kPa), CTS (°F)
    0x1E025000: (("oil_pressure", 256.0), ("battery_voltage", 256.0)),  # Oil Pressure (psi), Battery (V)
    0x1E029000: (("pedal_position", 256.0), ("fuel_pressure", 256.0)),  # Pedal Pos (%), Fuel Pressure (psi)
    0x1E049000: (("line_pressure", 256.0), ("vehicle_speed", 256.0)),   # Line Pressure (%), Speed (mph)
}


# ─── Decoded Frame ──────────────────────────────────────────────────────────

@dataclass
class DecodedFrame:
    """A decoded HEFI or Racepak CAN frame."""
    timestamp: float           # Time of receipt (UNIX epoch)
    channel_index: int         # Channel index extracted from CAN ID
    channel_def: Optional[ChannelDef]  # Matched definition, if known
    value_a: float             # Primary measurement value
    value_b: float             # Secondary value (status/quality/second measurement)
    raw_id: int                # Original 29-bit CAN ID
    raw_data: bytes            # Raw 8-byte payload
    ecu_serial_bits: int       # Lower 11 bits of the ECU serial
    protocol: str = "hefi"     # "hefi" (Holley Standard) or "racepak"

    @property
    def name(self) -> str:
        return self.channel_def.name if self.channel_def else f"unknown_{self.channel_index}"

    @property
    def label(self) -> str:
        return self.channel_def.label if self.channel_def else f"Channel {self.channel_index}"

    @property
    def unit(self) -> str:
        return self.channel_def.unit if self.channel_def else ""


# ─── Decoder Functions ──────────────────────────────────────────────────────

def extract_channel_index(can_id: int) -> int:
    """Extract the channel index (bits 24:14) from a 29-bit HEFI CAN ID."""
    return (can_id >> CHANNEL_INDEX_SHIFT) & 0x7FF


def extract_ecu_serial(can_id: int) -> int:
    """Extract the ECU serial bits (bits 10:0) from a 29-bit HEFI CAN ID."""
    return can_id & SERIAL_MASK


def build_can_id(channel_index: int, ecu_serial: int = 0x556) -> int:
    """
    Construct a 29-bit Holley Standard (HEFI) broadcast CAN ID:
      Bit 28:       1 (Broadcast)
      Bits 25..27:  0b111 (Broadcast target = 7)
      Bits 14..24:  channel_index (11 bits)
      Bits 11..13:  0b010 (Source = ECU)
      Bits 0..10:   ecu_serial (11 bits)
    """
    return (
        (1 << 28)
        | (0b111 << 25)
        | ((channel_index & 0x7FF) << 14)
        | (0b010 << 11)
        | (ecu_serial & 0x7FF)
    )


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
    Decode a raw Holley Standard (HEFI 29-bit IEEE 754 float) CAN frame.
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
        protocol="hefi",
    )


def is_racepak_header_id(can_id: int) -> bool:
    """
    Returns True if the CAN ID is the Racepak-exclusive RTC+RPM beacon (0x1E001xxx,
    where channel_index == 0 and source == 0b010).
    In Holley Standard mode, channel_index 0 is never broadcast (RPM starts at index 1).
    """
    masked = can_id & HEFI_ID_MASK
    return masked == 0x1E001000


def decode_racepak_frame(can_id: int, data: bytes, timestamp: float) -> list[DecodedFrame]:
    """
    Decode an 8-byte Racepak CAN frame (ported from AutoDashBackEnd/src/CAN/racepakDecoder.js).
    Each Racepak frame packs two big-endian int32 values scaled by 1/256.0.
    Returns 1 or 2 DecodedFrame objects mapped to standard CHANNEL_BY_NAME definitions.
    """
    if len(data) != 8:
        return []

    masked_id = can_id & HEFI_ID_MASK
    mapping = RACEPAK_CAN_MAP.get(masked_id)
    if mapping is None:
        return []

    ecu_serial = extract_ecu_serial(can_id)
    raw_int_a, raw_int_b = struct.unpack(">ii", data)
    frames: list[DecodedFrame] = []

    # Special handling for 0x1E001000: bytes 0..3 = RTC (ms), bytes 4..7 = RPM * 256
    if masked_id == 0x1E001000:
        rpm_val = raw_int_b / 256.0
        rtc_sec = raw_int_a / 1000.0
        ch_def = CHANNEL_BY_NAME.get("rpm")
        frames.append(
            DecodedFrame(
                timestamp=timestamp,
                channel_index=ch_def.index if ch_def else 1,
                channel_def=ch_def,
                value_a=rpm_val,
                value_b=rtc_sec,
                raw_id=can_id,
                raw_data=data,
                ecu_serial_bits=ecu_serial,
                protocol="racepak",
            )
        )
        return frames

    entry_a, entry_b = mapping
    if entry_a:
        name_a, scale_a = entry_a
        ch_def_a = CHANNEL_BY_NAME.get(name_a)
        frames.append(
            DecodedFrame(
                timestamp=timestamp,
                channel_index=ch_def_a.index if ch_def_a else extract_channel_index(can_id),
                channel_def=ch_def_a,
                value_a=raw_int_a / scale_a,
                value_b=0.0,
                raw_id=can_id,
                raw_data=data,
                ecu_serial_bits=ecu_serial,
                protocol="racepak",
            )
        )

    if entry_b:
        name_b, scale_b = entry_b
        ch_def_b = CHANNEL_BY_NAME.get(name_b)
        frames.append(
            DecodedFrame(
                timestamp=timestamp,
                channel_index=ch_def_b.index if ch_def_b else extract_channel_index(can_id),
                channel_def=ch_def_b,
                value_a=raw_int_b / scale_b,
                value_b=0.0,
                raw_id=can_id,
                raw_data=data,
                ecu_serial_bits=ecu_serial,
                protocol="racepak",
            )
        )

    return frames


def is_hefi_broadcast(can_id: int) -> bool:
    """
    Check if a 29-bit CAN ID looks like a valid HEFI broadcast frame.

    Supports both:
      - Historical Racepak / 3rd-party broadcast format (target=0b111 -> 0x1E...)
      - Terminator X / X MAX native broadcast stream (target=0b000 -> 0x10...)
    """
    clean_id = can_id & 0x1FFFFFFF
    cmd_bit = (clean_id >> 28) & 1
    if cmd_bit != 1:
        return False

    channel_index = (clean_id >> 14) & 0x7FF
    if channel_index == 0:
        return False

    target = (clean_id >> 25) & 0b111
    return target in (0b000, 0b111)


def is_hefi_announcement(can_id: int) -> bool:
    """
    Returns True if the 29-bit CAN ID is a Holley CAN Bus 1 node announcement /
    heartbeat frame (cmd_bit == 0, target == 0b111 -> 0x0E...).
    """
    clean_id = can_id & 0x1FFFFFFF
    return (clean_id & 0x1E000000) == 0x0E000000


def is_ecu_announcement(can_id: int) -> bool:
    """
    Returns True if the 29-bit CAN ID is a Terminator X / HP / Dominator ECU
    announcement frame on CAN Bus 1 (e.g. 0x0E001556).

    Verified from Terminator X.exe (0x3c1600):
      - cmd_bit (bit 28) == 0
      - target (bits 25..27) == 7 (0x0E...)
      - source_id (bits 14..24) in (0, 1)
      - source_status (bits 11..13) == 2 (ECU active heartbeat)
      - ecu_serial (bits 0..10) == 11-bit ECU serial (e.g. 0x556)
    """
    clean_id = can_id & 0x1FFFFFFF
    if (clean_id & 0x1E000000) != 0x0E000000:
        return False
    source_id = (clean_id >> 14) & 0x7FF
    source_status = (clean_id >> 11) & 0x7
    return source_id in (0, 1) and source_status == 2


# ─── Option 2: Reverse-Engineered Diagnostic & RPC Command Protocol ────────

# RPC Multi-frame Block Transfer Magic (LE: 0xF2493722)
RPC_MAGIC_BYTES: bytes = b"\x22\x37\x49\xf2"
RPC_MAGIC_U32: int = 0xF2493722

# Device Type Identifiers in Bits 13:11
DEVICE_TYPE_BROADCAST: int = 0b000
DEVICE_TYPE_ECU: int = 0b010        # 2 = ECU
DEVICE_TYPE_TOOL: int = 0b101       # 5 = PC Software / Handheld Tool


def build_command_can_id(command_index: int, target_serial: int, source_type: int = DEVICE_TYPE_TOOL) -> int:
    """
    Constructs a 29-bit extended CAN ID for PC tool commands directed to an ECU.
    Bit 28 = 0 (Command), Target = 0b111 (0x0E000000 base).
    """
    can_id = 0x0E000000
    can_id |= (command_index & 0x7FF) << 14
    can_id |= (source_type & 0x7) << 11
    can_id |= (target_serial & 0x7FF)
    return can_id


def is_rpc_start_frame(dlc: int, payload: bytes) -> tuple[bool, int]:
    """
    Checks if a CAN frame begins a multi-frame 0xF2493722 RPC response.
    Returns (True, total_byte_length) if matched, otherwise (False, 0).
    """
    if dlc == 8 and len(payload) >= 8 and payload[4:8] == RPC_MAGIC_BYTES:
        total_len = struct.unpack_from(">I", payload, 0)[0]
        return True, total_len
    return False, 0


def decode_sensor_status_flags(status_val: float | int) -> dict[str, Any]:
    """
    Decodes the 32-bit status/diagnostic word (value_b) accompanying sensor channels.
    Bitflags:
      Bit 0 (0x01): Sensor Value Below Minimum / Short to Ground
      Bit 1 (0x02): Sensor Value Above Maximum / Open Circuit / Short to 5V
      Bit 2 (0x04): Out of Range Warning
      Bit 3 (0x08): Sensor Uncalibrated or Signal Loss
    """
    u32 = int(status_val) if isinstance(status_val, float) else status_val
    return {
        "healthy": u32 == 0,
        "below_min": bool(u32 & 0x01),
        "above_max": bool(u32 & 0x02),
        "out_of_range": bool(u32 & 0x04),
        "uncalibrated": bool(u32 & 0x08),
        "raw_status": u32,
    }


