"""
Vehicle profile and configuration models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class VehicleProfile:
    """
    Permanent vehicle configuration specification sheet.
    """
    vehicle_id: str = "default_vehicle"
    name: str = "Holley Terminator X Vehicle"
    engine_name: str = "GM LS V8"
    displacement_liters: float = 6.0
    cylinder_count: int = 8
    ecu_type: str = "Holley Terminator X MAX"
    firmware_version: Optional[str] = None
    ecu_serial: Optional[int] = None
    fuel_type: str = "93 Octane Pump Gas"
    injector_flow_lb_hr: float = 42.0
    base_fuel_pressure_psi: float = 58.0       # vehicle-configured (e.g. 58 PSI for LS returnless, 43.5 PSI for standard EFI)
    target_idle_rpm: float = 850.0             # vehicle-configured target idle (overridden by ECU Channel 18 if broadcast)
    is_boosted: bool = False                   # vehicle-configured
    max_boost_psi: Optional[float] = None      # vehicle-configured
    rev_limiter_rpm: float = 6500.0            # vehicle-configured rev limiter threshold
    coolant_warning_f: float = 225.0           # generic heuristic default (OEM boiling margin)
    coolant_critical_f: float = 240.0          # generic heuristic default
    voltage_warning_v: float = 12.2            # generic heuristic default (alternator undercharge threshold)
    fuel_learn_threshold_pct: float = 7.0      # generic heuristic default for VE drift detection
    user_notes: str = ""
    installed_sensors: Dict[str, bool] = field(
        default_factory=lambda: {
            "oil_pressure": True,
            "fuel_pressure": True,
            "wideband_bank2": False,
            "trans_temp": True,
            "vehicle_speed": True,
        }
    )
