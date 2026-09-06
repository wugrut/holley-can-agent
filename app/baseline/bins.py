"""
Operating context classification and multidimensional binning.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RPMBand(str, Enum):
    IDLE = "idle"         # < 1050 RPM
    LOW = "low"           # 1050 - 2200 RPM
    CRUISE = "cruise"     # 2200 - 3500 RPM
    MID = "mid"           # 3500 - 5000 RPM
    HIGH = "high"         # >= 5000 RPM


class LoadBand(str, Enum):
    DECEL = "decel"       # < 32 kPa (high vacuum)
    LIGHT = "light"       # 32 - 55 kPa (light throttle / idle)
    MODERATE = "moderate" # 55 - 85 kPa (part throttle cruise / hill)
    HIGH_NA = "high_na"   # 85 - 105 kPa (atmospheric WOT)
    BOOST = "boost"       # > 105 kPa (forced induction positive pressure)


class ThermalBand(str, Enum):
    COLD = "cold"               # < 160 °F (warmup enrichment active)
    OPERATING = "operating"     # 160 - 215 °F (normal fully warm)
    HOT = "hot"                 # > 215 °F (elevated thermal load)


@dataclass(frozen=True)
class OperatingCondition:
    """Multidimensional operating context key."""
    rpm_band: RPMBand
    load_band: LoadBand
    thermal_band: ThermalBand

    @property
    def key(self) -> str:
        return f"{self.rpm_band.value}_{self.load_band.value}_{self.thermal_band.value}"

    @classmethod
    def classify(cls, rpm: float, map_kpa: float, coolant_temp: float) -> OperatingCondition:
        """Classifies continuous telemetry into a discrete operating bin."""
        # 1. RPM
        if rpm < 1050.0:
            rb = RPMBand.IDLE
        elif rpm < 2200.0:
            rb = RPMBand.LOW
        elif rpm < 3500.0:
            rb = RPMBand.CRUISE
        elif rpm < 5000.0:
            rb = RPMBand.MID
        else:
            rb = RPMBand.HIGH

        # 2. Load / MAP
        if map_kpa < 32.0:
            lb = LoadBand.DECEL
        elif map_kpa < 55.0:
            lb = LoadBand.LIGHT
        elif map_kpa < 85.0:
            lb = LoadBand.MODERATE
        elif map_kpa <= 105.0:
            lb = LoadBand.HIGH_NA
        else:
            lb = LoadBand.BOOST

        # 3. Thermal / CLT
        if coolant_temp < 160.0:
            tb = ThermalBand.COLD
        elif coolant_temp <= 215.0:
            tb = ThermalBand.OPERATING
        else:
            tb = ThermalBand.HOT

        return cls(rpm_band=rb, load_band=lb, thermal_band=tb)
