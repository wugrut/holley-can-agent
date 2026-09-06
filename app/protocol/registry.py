"""
Channel definitions and verified protocol registry for Holley HEFI.

Includes strict provenance tracking: distinguishing community reverse-engineered
sources, manufacturer publications, fixture tests, and live hardware verification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Dict, Optional, Set


class VerificationStatus(str, Enum):
    """
    Explicit verification status taxonomy.
    Guarantees no protocol claim is presented as verified without identifying its source.
    """
    HOLLEY_SOURCE_VERIFIED = "HOLLEY_SOURCE_VERIFIED"  # Directly confirmed in official Holley documentation or DBC
    SOURCE_VERIFIED = "SOURCE_VERIFIED"                # Documented in established third-party integration specs (RealDash XML, CANformance, Nefarious)
    LIVE_HARDWARE_VERIFIED = "LIVE_HARDWARE_VERIFIED"  # Empirically captured and validated against a physical Terminator X ECU
    TEST_FIXTURE_VERIFIED = "TEST_FIXTURE_VERIFIED"    # Validated against synthetic unit tests and simulation fixtures
    INFERRED = "INFERRED"                              # Deduced from adjacent channel patterns or mathematical relationships
    UNKNOWN = "UNKNOWN"                                # Unverified / unmapped / speculative


class ChannelCategory(IntEnum):
    """Categorical groupings for telemetry channels."""
    ENGINE = 1
    FUELING = 2
    IGNITION = 3
    TEMPERATURE = 4
    ELECTRICAL = 5
    TRANSMISSION = 6
    INPUTS = 7
    MISC = 8


@dataclass(frozen=True)
class SignalProvenance:
    """Detailed provenance metadata for a single telemetry signal."""
    source_name: str
    verification_status: VerificationStatus
    documentation_ref: str
    endianness: str = "big_endian"
    encoding: str = "ieee754_float32"
    signed: bool = True
    scaling: float = 1.0
    offset: float = 0.0
    notes: str = ""


@dataclass(frozen=True)
class ChannelDef:
    """Definition of an HEFI broadcast channel with explicit provenance metadata."""
    index: int
    name: str                  # Normalized snake_case signal identifier
    label: str                 # Human-readable UI label
    unit: str                  # Standard unit
    category: ChannelCategory
    provenance_a: SignalProvenance
    value_b_name: Optional[str] = None
    value_b_label: Optional[str] = None
    value_b_unit: Optional[str] = None
    provenance_b: Optional[SignalProvenance] = None
    min_val: Optional[float] = None
    max_val: Optional[float] = None

    @property
    def verification_status(self) -> VerificationStatus:
        return self.provenance_a.verification_status


# Standard community source reference string
COMMUNITY_REF = "RealDash Holley XML / Nefarious Motorsports / CANformance / HackingLZ"


# Verified HEFI channel mapping table with per-signal provenance
VERIFIED_CHANNELS: Dict[int, ChannelDef] = {
    1: ChannelDef(
        index=1, name="engine_rpm", label="Engine RPM", unit="rpm", category=ChannelCategory.ENGINE,
        min_val=0, max_val=10000,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF, notes="RPM primary float"),
        value_b_name="rpm_status", value_b_label="RPM Status", value_b_unit="",
        provenance_b=SignalProvenance("Community Reverse-Engineering", VerificationStatus.UNKNOWN, COMMUNITY_REF, notes="Secondary float reserved/status"),
    ),
    2: ChannelDef(
        index=2, name="map_kpa", label="Manifold Absolute Pressure", unit="kPa", category=ChannelCategory.ENGINE,
        min_val=0, max_val=500,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF, notes="MAP primary measurement in kPa"),
        value_b_name="baro_kpa", value_b_label="Barometric Pressure", value_b_unit="kPa",
        provenance_b=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF, notes="Barometric pressure in kPa"),
    ),
    3: ChannelDef(
        index=3, name="tps", label="Throttle Position", unit="%", category=ChannelCategory.ENGINE,
        min_val=0, max_val=100,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF, notes="TPS percentage 0.0 to 100.0%"),
        value_b_name="tps_status", value_b_label="TPS Status", value_b_unit="",
        provenance_b=SignalProvenance("Community Reverse-Engineering", VerificationStatus.UNKNOWN, COMMUNITY_REF),
    ),
    4: ChannelDef(
        index=4, name="coolant_temp", label="Coolant Temp", unit="°F", category=ChannelCategory.TEMPERATURE,
        min_val=-40, max_val=320,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF, notes="Coolant temp broadcast in degrees F"),
        value_b_name="clt_status", value_b_label="CLT Status", value_b_unit="",
        provenance_b=SignalProvenance("Community Reverse-Engineering", VerificationStatus.UNKNOWN, COMMUNITY_REF),
    ),
    5: ChannelDef(
        index=5, name="target_afr", label="Target AFR", unit="AFR", category=ChannelCategory.FUELING,
        min_val=8, max_val=22,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF, notes="ECU target air-fuel ratio from fuel map"),
    ),
    6: ChannelDef(
        index=6, name="afr_bank1", label="AFR Bank 1", unit="AFR", category=ChannelCategory.FUELING,
        min_val=8, max_val=22,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF, notes="Primary wideband O2 Bank 1 (Left)"),
        value_b_name="afr_l_status", value_b_label="Bank 1 O2 Status", value_b_unit="",
        provenance_b=SignalProvenance("Community Reverse-Engineering", VerificationStatus.UNKNOWN, COMMUNITY_REF),
    ),
    7: ChannelDef(
        index=7, name="afr_bank2", label="AFR Bank 2", unit="AFR", category=ChannelCategory.FUELING,
        min_val=8, max_val=22,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF, notes="Secondary wideband O2 Bank 2 (Right)"),
        value_b_name="afr_r_status", value_b_label="Bank 2 O2 Status", value_b_unit="",
        provenance_b=SignalProvenance("Community Reverse-Engineering", VerificationStatus.UNKNOWN, COMMUNITY_REF),
    ),
    8: ChannelDef(
        index=8, name="afr_measured", label="AFR Average", unit="AFR", category=ChannelCategory.FUELING,
        min_val=8, max_val=22,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF, notes="Averaged wideband reading"),
    ),
    9: ChannelDef(
        index=9, name="air_temp_enrich", label="Air Temp Enrichment", unit="%", category=ChannelCategory.FUELING,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF),
    ),
    10: ChannelDef(
        index=10, name="coolant_enrich", label="Coolant Enrichment", unit="%", category=ChannelCategory.FUELING,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF),
    ),
    11: ChannelDef(
        index=11, name="ignition_timing", label="Ignition Timing", unit="°BTDC", category=ChannelCategory.IGNITION,
        min_val=-20, max_val=60,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF, notes="Actual total spark advance"),
        value_b_name="knock_retard", value_b_label="Knock Retard", value_b_unit="°",
        provenance_b=SignalProvenance("Community Reverse-Engineering", VerificationStatus.INFERRED, COMMUNITY_REF, notes="Knock retard degrees inferred from status float"),
    ),
    12: ChannelDef(
        index=12, name="battery_voltage", label="Battery Voltage", unit="V", category=ChannelCategory.ELECTRICAL,
        min_val=0, max_val=20,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF, notes="ECU main switched power supply voltage"),
    ),
    13: ChannelDef(
        index=13, name="fuel_learn", label="Fuel Learn", unit="%", category=ChannelCategory.FUELING,
        min_val=-50, max_val=50,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF, notes="Closed-loop fuel learn table active adjustment"),
    ),
    14: ChannelDef(
        index=14, name="closed_loop_active", label="Closed Loop Flag", unit="bool", category=ChannelCategory.FUELING,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF, notes="1.0 = Active, 0.0 = Open Loop"),
    ),
    15: ChannelDef(
        index=15, name="iat", label="Intake Air Temp", unit="°F", category=ChannelCategory.TEMPERATURE,
        min_val=-40, max_val=300,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF, notes="Manifold air temperature"),
    ),
    16: ChannelDef(
        index=16, name="fuel_pw", label="Fuel Pulse Width", unit="ms", category=ChannelCategory.FUELING,
        min_val=0, max_val=30,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF, notes="Injector pulse width in milliseconds"),
        value_b_name="injector_duty", value_b_label="Injector Duty Cycle", value_b_unit="%",
        provenance_b=SignalProvenance("Community Reverse-Engineering", VerificationStatus.INFERRED, COMMUNITY_REF, notes="Duty cycle calculated or decoded from secondary float"),
    ),
    17: ChannelDef(
        index=17, name="spark_advance", label="Base Spark Advance", unit="°", category=ChannelCategory.IGNITION,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF, notes="Base ignition table advance"),
    ),
    18: ChannelDef(
        index=18, name="idle_speed", label="Target Idle Speed", unit="rpm", category=ChannelCategory.ENGINE,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF, notes="Target idle RPM commanded by ECU"),
        value_b_name="iac_position", value_b_label="IAC Position", value_b_unit="%",
        provenance_b=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF, notes="IAC percentage position"),
    ),
    19: ChannelDef(
        index=19, name="fan1_active", label="Fan 1 Status", unit="bool", category=ChannelCategory.ELECTRICAL,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF, notes="Electric fan 1 output state"),
        value_b_name="fan2_active", value_b_label="Fan 2 Status", value_b_unit="bool",
        provenance_b=SignalProvenance("Community Reverse-Engineering", VerificationStatus.INFERRED, COMMUNITY_REF, notes="Electric fan 2 output state"),
    ),
    20: ChannelDef(
        index=20, name="trans_gear", label="Current Gear", unit="gear", category=ChannelCategory.TRANSMISSION,
        min_val=0, max_val=6,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF, notes="Terminator X MAX 4L60E/4L80E current gear"),
        value_b_name="trans_commanded_gear", value_b_label="Commanded Gear", value_b_unit="gear",
        provenance_b=SignalProvenance("Community Reverse-Engineering", VerificationStatus.INFERRED, COMMUNITY_REF),
    ),
    21: ChannelDef(
        index=21, name="trans_temp", label="Transmission Fluid Temp", unit="°F", category=ChannelCategory.TRANSMISSION,
        min_val=-40, max_val=350,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF, notes="Transmission fluid temperature"),
    ),
    22: ChannelDef(
        index=22, name="tcc_duty", label="TCC Lockup Duty", unit="%", category=ChannelCategory.TRANSMISSION,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF, notes="Torque converter clutch PWM lockup duty"),
        value_b_name="trans_slip_rpm", value_b_label="Converter Slip", value_b_unit="rpm",
        provenance_b=SignalProvenance("Community Reverse-Engineering", VerificationStatus.INFERRED, COMMUNITY_REF),
    ),
    23: ChannelDef(
        index=23, name="output_speed", label="Trans Output Speed", unit="rpm", category=ChannelCategory.TRANSMISSION,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF),
    ),
    24: ChannelDef(
        index=24, name="input_speed", label="Trans Input Speed", unit="rpm", category=ChannelCategory.TRANSMISSION,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF),
    ),
    25: ChannelDef(
        index=25, name="line_pressure", label="Trans Line Pressure Duty", unit="%", category=ChannelCategory.TRANSMISSION,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF),
    ),
    30: ChannelDef(
        index=30, name="oil_pressure", label="Engine Oil Pressure", unit="psi", category=ChannelCategory.ENGINE,
        min_val=0, max_val=150,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF, notes="Optional transducer input"),
    ),
    31: ChannelDef(
        index=31, name="fuel_pressure", label="Fuel Rail Pressure", unit="psi", category=ChannelCategory.FUELING,
        min_val=0, max_val=150,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF, notes="Optional transducer input"),
    ),
    32: ChannelDef(
        index=32, name="vehicle_speed", label="Vehicle Speed", unit="mph", category=ChannelCategory.ENGINE,
        min_val=0, max_val=250,
        provenance_a=SignalProvenance("Community Reverse-Engineering", VerificationStatus.SOURCE_VERIFIED, COMMUNITY_REF, notes="Calibrated vehicle speed"),
    ),
}


class UnknownChannelTracker:
    """Safely tracks observed CAN channel indices that are not yet verified."""

    def __init__(self) -> None:
        self._observed_indices: Set[int] = set()

    def record_unknown(self, index: int) -> None:
        self._observed_indices.add(index)

    def get_unknown_indices(self) -> Set[int]:
        return set(self._observed_indices)
