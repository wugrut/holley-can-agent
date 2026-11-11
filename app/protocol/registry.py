"""
Channel definitions and verified protocol registry for Holley HEFI.

Includes strict provenance tracking: distinguishing official Holley DBC sources
('HP Dominator & Terminator X DBC.dbc' / 'HARDWIRE HOLLEY DBC FILE.dbc'),
community reverse-engineered sources, fixture tests, and live hardware verification.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Dict, Optional, Set


class VerificationStatus(str, Enum):
    """
    Explicit verification status taxonomy.
    Guarantees no protocol claim is presented as verified without identifying its source.
    """
    HOLLEY_SOURCE_VERIFIED = "HOLLEY_SOURCE_VERIFIED"  # Directly confirmed in official Holley DBC
    SOURCE_VERIFIED = "SOURCE_VERIFIED"                # Documented in third-party integration specs
    LIVE_HARDWARE_VERIFIED = "LIVE_HARDWARE_VERIFIED"  # Empirically captured on a physical Terminator X ECU
    TEST_FIXTURE_VERIFIED = "TEST_FIXTURE_VERIFIED"    # Validated against synthetic unit tests
    INFERRED = "INFERRED"                              # Deduced from adjacent channel patterns
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
    BOOST = 9


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


HOLLEY_DBC_REF = "HP Dominator & Terminator X DBC.dbc / HARDWIRE HOLLEY DBC FILE.dbc"


def _dbc_prov(notes: str = "") -> SignalProvenance:
    return SignalProvenance(
        "Official Holley DBC",
        VerificationStatus.HOLLEY_SOURCE_VERIFIED,
        HOLLEY_DBC_REF,
        notes=notes,
    )


# Official Holley HEFI channel mapping table with per-signal DBC provenance
VERIFIED_CHANNELS: Dict[int, ChannelDef] = {
    1: ChannelDef(
        index=1, name="engine_rpm", label="Engine RPM", unit="rpm", category=ChannelCategory.ENGINE,
        min_val=0, max_val=10000,
        provenance_a=_dbc_prov("BO_ 2650820608 RPM (0x1E005000)"),
        value_b_name="rpm_status", value_b_label="RPM Status", value_b_unit="",
        provenance_b=_dbc_prov("SG_ Status byte"),
    ),
    2: ChannelDef(
        index=2, name="fuel_pw", label="Fuel Pulse Width", unit="ms", category=ChannelCategory.FUELING,
        min_val=0, max_val=30,
        provenance_a=_dbc_prov("BO_ 2650836992 FUEL_INJ_PW (0x1E009000)"),
        value_b_name="injector_duty", value_b_label="Injector Duty Cycle", value_b_unit="%",
        provenance_b=SignalProvenance("Holley DBC / Simulator", VerificationStatus.INFERRED, HOLLEY_DBC_REF),
    ),
    3: ChannelDef(
        index=3, name="injector_duty", label="Injector Duty Cycle", unit="%", category=ChannelCategory.FUELING,
        min_val=0, max_val=100,
        provenance_a=_dbc_prov("BO_ 2650853376 FUEL_DUTY_CYCLE (0x1E00D000)"),
    ),
    4: ChannelDef(
        index=4, name="closed_loop_comp", label="Closed Loop Comp", unit="%", category=ChannelCategory.FUELING,
        min_val=-50, max_val=50,
        provenance_a=_dbc_prov("BO_ 2650869760 FUEL_CLOSED_LOOP_COMP (0x1E011000)"),
    ),
    5: ChannelDef(
        index=5, name="target_afr", label="Target AFR", unit="AFR", category=ChannelCategory.FUELING,
        min_val=8, max_val=22,
        provenance_a=_dbc_prov("BO_ 2650886144 FUEL_TARGET_AFR (0x1E015000)"),
    ),
    6: ChannelDef(
        index=6, name="afr_bank1", label="AFR Bank 1", unit="AFR", category=ChannelCategory.FUELING,
        min_val=8, max_val=22,
        provenance_a=_dbc_prov("BO_ 2650902528 FUEL_AFR_LEFT (0x1E019000)"),
        value_b_name="afr_l_status", value_b_label="Bank 1 O2 Status", value_b_unit="",
        provenance_b=_dbc_prov("SG_ Status byte"),
    ),
    7: ChannelDef(
        index=7, name="afr_bank2", label="AFR Bank 2", unit="AFR", category=ChannelCategory.FUELING,
        min_val=8, max_val=22,
        provenance_a=_dbc_prov("BO_ 2650918912 FUEL_AFR_RIGHT (0x1E01D000)"),
        value_b_name="afr_r_status", value_b_label="Bank 2 O2 Status", value_b_unit="",
        provenance_b=_dbc_prov("SG_ Status byte"),
    ),
    8: ChannelDef(
        index=8, name="afr_measured", label="AFR Average", unit="AFR", category=ChannelCategory.FUELING,
        min_val=8, max_val=22,
        provenance_a=_dbc_prov("BO_ 2650935296 FUEL_AFR_AVERAGE (0x1E021000)"),
    ),
    9: ChannelDef(
        index=9, name="air_temp_enrich", label="Air Temp Enrichment", unit="%", category=ChannelCategory.FUELING,
        provenance_a=_dbc_prov("BO_ 2650951680 FUEL_AIR_TEMP_ENRICH (0x1E025000)"),
    ),
    10: ChannelDef(
        index=10, name="coolant_enrich", label="Coolant Enrichment", unit="%", category=ChannelCategory.FUELING,
        provenance_a=_dbc_prov("BO_ 2650968064 FUEL_COOLANT_ENRICH (0x1E029000)"),
    ),
    11: ChannelDef(
        index=11, name="coolant_afr_offset", label="Coolant AFR Offset", unit="AFR", category=ChannelCategory.FUELING,
        provenance_a=_dbc_prov("BO_ 2650984448 FUEL_COOLANT_AFR_OFFSET (0x1E02D000)"),
    ),
    12: ChannelDef(
        index=12, name="afterstart_enrich", label="Afterstart Enrichment", unit="%", category=ChannelCategory.FUELING,
        provenance_a=_dbc_prov("BO_ 2651000832 FUEL_AFTERSTART_ENRICH (0x1E031000)"),
    ),
    13: ChannelDef(
        index=13, name="fuel_learn", label="Fuel Learn", unit="%", category=ChannelCategory.FUELING,
        min_val=-50, max_val=50,
        provenance_a=_dbc_prov("BO_ 2651017216 FUEL_CURRENT_LEARN_PERCENT (0x1E035000)"),
    ),
    14: ChannelDef(
        index=14, name="closed_loop_active", label="Closed Loop Flag", unit="bool", category=ChannelCategory.FUELING,
        provenance_a=_dbc_prov("BO_ 2651033600 FUEL_CLOSED_LOOP_STATUS (0x1E039000)"),
    ),
    15: ChannelDef(
        index=15, name="learn_status", label="Learn Status", unit="bool", category=ChannelCategory.FUELING,
        provenance_a=_dbc_prov("BO_ 2651049984 FUEL_LEARN_STATUS (0x1E03D000)"),
    ),
    16: ChannelDef(
        index=16, name="fuel_economy", label="Fuel Economy", unit="mpg", category=ChannelCategory.FUELING,
        provenance_a=_dbc_prov("BO_ 2651066368 FUEL_ECONOMY (0x1E041000)"),
    ),
    17: ChannelDef(
        index=17, name="fuel_flow", label="Fuel Flow", unit="lb/hr", category=ChannelCategory.FUELING,
        min_val=0, max_val=2000,
        provenance_a=_dbc_prov("BO_ 2651082752 FUEL_FLOW (0x1E045000)"),
    ),
    21: ChannelDef(
        index=21, name="estimated_ve", label="Estimated VE", unit="%", category=ChannelCategory.FUELING,
        min_val=0, max_val=200,
        provenance_a=_dbc_prov("BO_ 2651148288 ESTIMATED_VE (0x1E055000)"),
    ),
    22: ChannelDef(
        index=22, name="ignition_timing", label="Ignition Timing", unit="°BTDC", category=ChannelCategory.IGNITION,
        min_val=-20, max_val=60,
        provenance_a=_dbc_prov("BO_ 2651164672 SPARK_IGNITION_TIMING (0x1E059000)"),
        value_b_name="knock_retard", value_b_label="Knock Retard", value_b_unit="°",
        provenance_b=SignalProvenance("Holley DBC / Simulator", VerificationStatus.INFERRED, HOLLEY_DBC_REF),
    ),
    23: ChannelDef(
        index=23, name="knock_retard", label="Knock Retard", unit="°", category=ChannelCategory.IGNITION,
        min_val=0, max_val=30,
        provenance_a=_dbc_prov("BO_ 2651181056 SPARK_KNOCK_RETARD (0x1E05D000)"),
    ),
    24: ChannelDef(
        index=24, name="knock_level", label="Knock Level", unit="%", category=ChannelCategory.IGNITION,
        min_val=0, max_val=100,
        provenance_a=_dbc_prov("BO_ 2651197440 KNOCK_LEVEL (0x1E061000)"),
    ),
    26: ChannelDef(
        index=26, name="iac_position", label="IAC Position", unit="%", category=ChannelCategory.ENGINE,
        min_val=0, max_val=100,
        provenance_a=_dbc_prov("BO_ 2651230208 IDLE_IAC_POS (0x1E069000)"),
    ),
    27: ChannelDef(
        index=27, name="idle_speed", label="Target Idle Speed", unit="rpm", category=ChannelCategory.ENGINE,
        provenance_a=_dbc_prov("BO_ 2651246592 IDLE_TARGET_IDLE_SPEED (0x1E06D000)"),
        value_b_name="iac_position", value_b_label="IAC Position", value_b_unit="%",
        provenance_b=SignalProvenance("Holley DBC / Simulator", VerificationStatus.INFERRED, HOLLEY_DBC_REF),
    ),
    28: ChannelDef(
        index=28, name="map_kpa", label="Manifold Absolute Pressure", unit="kPa", category=ChannelCategory.ENGINE,
        min_val=0, max_val=500,
        provenance_a=_dbc_prov("BO_ 2651262976 SENSOR_MAP (0x1E071000)"),
        value_b_name="baro_kpa", value_b_label="Barometric Pressure", value_b_unit="kPa",
        provenance_b=_dbc_prov("Barometric pressure secondary float"),
    ),
    29: ChannelDef(
        index=29, name="tps", label="Throttle Position", unit="%", category=ChannelCategory.ENGINE,
        min_val=0, max_val=100,
        provenance_a=_dbc_prov("BO_ 2651279360 SENSOR_TPS (0x1E075000)"),
        value_b_name="tps_status", value_b_label="TPS Status", value_b_unit="",
        provenance_b=_dbc_prov("SG_ Status byte"),
    ),
    30: ChannelDef(
        index=30, name="iat", label="Intake Air Temp", unit="°F", category=ChannelCategory.TEMPERATURE,
        min_val=-40, max_val=300,
        provenance_a=_dbc_prov("BO_ 2651295744 SENSOR_MAT (0x1E079000)"),
    ),
    31: ChannelDef(
        index=31, name="coolant_temp", label="Coolant Temp", unit="°F", category=ChannelCategory.TEMPERATURE,
        min_val=-40, max_val=320,
        provenance_a=_dbc_prov("BO_ 2651312128 SENSOR_CTS (0x1E07D000)"),
        value_b_name="clt_status", value_b_label="CLT Status", value_b_unit="",
        provenance_b=_dbc_prov("SG_ Status byte"),
    ),
    32: ChannelDef(
        index=32, name="baro_kpa", label="Barometric Pressure", unit="kPa", category=ChannelCategory.ENGINE,
        min_val=50, max_val=120,
        provenance_a=_dbc_prov("BO_ 2651328512 SENSOR_BARO (0x1E081000)"),
    ),
    33: ChannelDef(
        index=33, name="battery_voltage", label="Battery Voltage", unit="V", category=ChannelCategory.ELECTRICAL,
        min_val=0, max_val=20,
        provenance_a=_dbc_prov("BO_ 2651344896 SENSOR_BATT_VOLT (0x1E085000)"),
    ),
    34: ChannelDef(
        index=34, name="oil_pressure", label="Engine Oil Pressure", unit="psi", category=ChannelCategory.ENGINE,
        min_val=0, max_val=150,
        provenance_a=_dbc_prov("BO_ 2651361280 SENSOR_OIL_PRESSURE (0x1E089000)"),
    ),
    35: ChannelDef(
        index=35, name="fuel_pressure", label="Fuel Rail Pressure", unit="psi", category=ChannelCategory.FUELING,
        min_val=0, max_val=150,
        provenance_a=_dbc_prov("BO_ 2651377664 SENSOR_FUEL_PRESSURE (0x1E08D000)"),
    ),
    36: ChannelDef(
        index=36, name="pedal_position", label="Pedal Position", unit="%", category=ChannelCategory.INPUTS,
        min_val=0, max_val=100,
        provenance_a=_dbc_prov("BO_ 2651394048 SENSOR_PEDAL_POSITION (0x1E091000)"),
    ),
    44: ChannelDef(
        index=44, name="fan1_active", label="Fan 1 Status", unit="bool", category=ChannelCategory.ELECTRICAL,
        provenance_a=_dbc_prov("BO_ 2651525120 SYSTEM_FAN1_STATUS (0x1E0B1000)"),
        value_b_name="fan2_active", value_b_label="Fan 2 Status", value_b_unit="bool",
        provenance_b=SignalProvenance("Holley DBC", VerificationStatus.INFERRED, HOLLEY_DBC_REF),
    ),
    45: ChannelDef(
        index=45, name="fan2_active", label="Fan 2 Status", unit="bool", category=ChannelCategory.ELECTRICAL,
        provenance_a=_dbc_prov("BO_ 2651541504 SYSTEM_FAN2_STATUS (0x1E0B5000)"),
    ),
    53: ChannelDef(
        index=53, name="spark_advance", label="Base Spark Advance", unit="°", category=ChannelCategory.IGNITION,
        provenance_a=_dbc_prov("BO_ 2651672576 SYSTEM_BASE_TIMING (0x1E0D5000)"),
    ),
    125: ChannelDef(
        index=125, name="target_fuel_pressure", label="Target Fuel Pressure", unit="psi", category=ChannelCategory.FUELING,
        min_val=0, max_val=150,
        provenance_a=_dbc_prov("BO_ 2652852224 SYSTEM_TARGET_FUEL_PRESSURE (0x1E1F5000)"),
    ),
    132: ChannelDef(
        index=132, name="boost_psig", label="Boost Pressure", unit="psig", category=ChannelCategory.BOOST,
        min_val=0, max_val=60,
        provenance_a=_dbc_prov("BO_ 2652966912 BOOST_PSIG (0x1E211000)"),
    ),
    135: ChannelDef(
        index=135, name="target_boost", label="Target Boost", unit="psig", category=ChannelCategory.BOOST,
        min_val=0, max_val=60,
        provenance_a=_dbc_prov("BO_ 2653016064 BOOST_TARGET_BOOST (0x1E21D000)"),
    ),
    141: ChannelDef(
        index=141, name="boost_build_status", label="Boost Builder / Antilag Status", unit="bool", category=ChannelCategory.BOOST,
        provenance_a=_dbc_prov("BO_ 2653114368 BOOST_BUILD_STATUS (0x1E235000)"),
    ),
    142: ChannelDef(
        index=142, name="boost_solenoid_duty", label="Boost Solenoid Duty", unit="%", category=ChannelCategory.BOOST,
        min_val=0, max_val=100,
        provenance_a=_dbc_prov("BO_ 2653130752 BOOST_SOLENOID_DUTY (0x1E239000)"),
    ),
    219: ChannelDef(
        index=219, name="trans_gear", label="Current Gear", unit="gear", category=ChannelCategory.TRANSMISSION,
        min_val=0, max_val=6,
        provenance_a=_dbc_prov("BO_ 2654392320 TRANS_GEAR (0x1E36D000)"),
        value_b_name="trans_commanded_gear", value_b_label="Commanded Gear", value_b_unit="gear",
        provenance_b=SignalProvenance("Holley DBC", VerificationStatus.INFERRED, HOLLEY_DBC_REF),
    ),
    220: ChannelDef(
        index=220, name="vehicle_speed", label="Vehicle Speed", unit="mph", category=ChannelCategory.ENGINE,
        min_val=0, max_val=250,
        provenance_a=_dbc_prov("BO_ 2654408704 TRANS_SPEED (0x1E371000)"),
    ),
    221: ChannelDef(
        index=221, name="line_pressure", label="Trans Line Pressure Duty", unit="%", category=ChannelCategory.TRANSMISSION,
        min_val=0, max_val=100,
        provenance_a=_dbc_prov("BO_ 2654425088 TRANS_LINE_PRESSURE_PWM (0x1E375000)"),
    ),
    222: ChannelDef(
        index=222, name="input_speed", label="Trans Input Speed", unit="rpm", category=ChannelCategory.TRANSMISSION,
        provenance_a=_dbc_prov("BO_ 2654441472 TRANS_INPUT_SHAFT_SPEED (0x1E379000)"),
    ),
    223: ChannelDef(
        index=223, name="output_speed", label="Trans Output / Accum PWM", unit="rpm", category=ChannelCategory.TRANSMISSION,
        provenance_a=_dbc_prov("BO_ 2654457856 TRANS_ACCUM_PRESSURE_PWM (0x1E37D000)"),
    ),
    224: ChannelDef(
        index=224, name="tcc_duty", label="TCC Lockup Duty", unit="%", category=ChannelCategory.TRANSMISSION,
        provenance_a=_dbc_prov("BO_ 2654474240 TRANS_TCC_DUTY_CYCLE (0x1E381000)"),
        value_b_name="trans_slip_rpm", value_b_label="Converter Slip", value_b_unit="rpm",
        provenance_b=SignalProvenance("Holley DBC", VerificationStatus.INFERRED, HOLLEY_DBC_REF),
    ),
    225: ChannelDef(
        index=225, name="trans_temp", label="Transmission Fluid Temp", unit="°F", category=ChannelCategory.TRANSMISSION,
        min_val=-40, max_val=350,
        provenance_a=_dbc_prov("BO_ 2654490624 TRANS_LINE_TEMP (0x1E385000)"),
    ),
    499: ChannelDef(
        index=499, name="launch_status", label="Race Launch Status", unit="bool", category=ChannelCategory.BOOST,
        provenance_a=_dbc_prov("BO_ 2658979840 RACE_LAUNCH_STATUS (0x1E7CD000)"),
    ),
    519: ChannelDef(
        index=519, name="spool_assist_status", label="Spool Assist / Antilag Output", unit="bool", category=ChannelCategory.BOOST,
        provenance_a=_dbc_prov("BO_ 2659307520 RACE_SPOOL_ASSIST_OUTPUT_STATUS (0x1E81D000)"),
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
