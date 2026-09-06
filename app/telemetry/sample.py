"""
Synchronized normalized telemetry sample aggregating multiple decoded signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from app.telemetry.quality import SignalQuality
from app.telemetry.signals import TelemetrySignal


@dataclass
class NormalizedTelemetrySample:
    """
    Unified point-in-time engine state model across all ECU platforms.
    """
    timestamp: float

    # Core engine parameters
    engine_rpm: float = 0.0
    map_kpa: float = 0.0
    baro_kpa: float = 101.3
    tps: float = 0.0
    coolant_temp: float = 0.0
    iat: float = 0.0

    # Fueling parameters
    target_afr: float = 14.7
    afr_measured: float = 14.7
    afr_bank1: float = 14.7
    afr_bank2: Optional[float] = None
    fuel_learn: float = 0.0
    closed_loop_active: bool = False
    fuel_pw: float = 0.0

    # Ignition & Electrical
    ignition_timing: float = 0.0
    knock_retard: float = 0.0
    battery_voltage: float = 12.0

    # Transmission (Terminator X MAX)
    trans_gear: int = 0
    trans_temp: Optional[float] = None
    tcc_duty: Optional[float] = None

    # Optional / Transducer inputs
    oil_pressure: Optional[float] = None
    fuel_pressure: Optional[float] = None
    vehicle_speed: Optional[float] = None

    # Derived metrics
    boost_psi: float = 0.0
    manifold_vacuum_inhg: float = 0.0
    afr_error_pct: float = 0.0
    injector_duty_pct: float = 0.0

    # Signal mapping and quality tracking
    signals: Dict[str, TelemetrySignal] = field(default_factory=dict)
    overall_quality_score: float = 1.0  # 0.0 to 1.0 based on % valid signals

    def compute_derived_metrics(self) -> None:
        """Calculates standardized physical derivatives."""
        # 1. Boost (psi)
        if self.map_kpa > self.baro_kpa:
            self.boost_psi = round((self.map_kpa - self.baro_kpa) * 0.145038, 2)
            self.manifold_vacuum_inhg = 0.0
        else:
            self.boost_psi = 0.0
            self.manifold_vacuum_inhg = round((self.baro_kpa - self.map_kpa) * 0.295300, 2)

        # 2. AFR Error (%)
        if self.target_afr > 0.0:
            self.afr_error_pct = round(((self.afr_measured - self.target_afr) / self.target_afr) * 100.0, 2)
        else:
            self.afr_error_pct = 0.0

        # 3. Injector duty cycle (%) for 4-stroke
        if self.engine_rpm > 0.0:
            duty = (self.engine_rpm * self.fuel_pw) / 1200.0
            self.injector_duty_pct = min(100.0, round(duty, 2))
        else:
            self.injector_duty_pct = 0.0

    def calculate_quality_score(self) -> float:
        """Calculates the percentage of present signals that have VALID quality."""
        if not self.signals:
            return 1.0
        valid_count = sum(1 for s in self.signals.values() if s.quality in (SignalQuality.VALID, SignalQuality.SIMULATED))
        self.overall_quality_score = valid_count / len(self.signals)
        return self.overall_quality_score
