"""
Baseline engine for continuous vehicle learning and deviation scoring.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from app.baseline.bins import OperatingCondition
from app.baseline.model import BaselineCell, RobustStats, VehicleBaselineProfile
from app.telemetry.sample import NormalizedTelemetrySample


class BaselineEngine:
    """
    Learns vehicle-specific behavior partitioned by operating conditions.
    Computes deviation metrics against learned non-parametric profiles.
    """

    def __init__(self, vehicle_id: str, max_samples_per_bin: int = 1000) -> None:
        self.vehicle_id = vehicle_id
        self.max_samples_per_bin = max_samples_per_bin
        self.profile = VehicleBaselineProfile(vehicle_id=vehicle_id)

        # Raw sample buffer: (condition_key, signal_name) -> list of floats
        self._raw_buffers: Dict[Tuple[str, str], List[float]] = defaultdict(list)

    def ingest_sample(self, sample: NormalizedTelemetrySample) -> None:
        """Categorizes sample into operating bin and updates historical distributions."""
        if sample.overall_quality_score < 0.8:
            return  # Exclude corrupted frames from baseline learning

        cond = OperatingCondition.classify(
            rpm=sample.engine_rpm,
            map_kpa=sample.map_kpa,
            coolant_temp=sample.coolant_temp,
        )
        cond_key = cond.key

        tracked_signals = {
            "fuel_learn": sample.fuel_learn,
            "afr_measured": sample.afr_measured,
            "map_kpa": sample.map_kpa,
            "engine_rpm": sample.engine_rpm,
            "coolant_temp": sample.coolant_temp,
            "battery_voltage": sample.battery_voltage,
            "ignition_timing": sample.ignition_timing,
        }

        for sig_name, val in tracked_signals.items():
            key = (cond_key, sig_name)
            buf = self._raw_buffers[key]
            buf.append(val)
            if len(buf) > self.max_samples_per_bin:
                buf.pop(0)

            # Periodically re-calculate robust stats
            if len(buf) % 10 == 0:
                stats = RobustStats.compute(buf)
                if stats:
                    cell_id = f"{cond_key}:{sig_name}"
                    self.profile.cells[cell_id] = BaselineCell(
                        condition_key=cond_key,
                        signal_name=sig_name,
                        stats=stats,
                        last_updated=time.time(),
                    )

    def evaluate_deviation(
        self,
        cond_key: str,
        signal_name: str,
        value: float,
    ) -> Optional[Dict[str, float]]:
        """
        Evaluates value against learned cell baseline.
        Returns delta, IQR distance, and boundary flag if available.
        """
        cell_id = f"{cond_key}:{signal_name}"
        cell = self.profile.cells.get(cell_id)
        if not cell or cell.stats.count < 10:
            return None

        stats = cell.stats
        delta = value - stats.median
        is_outside_p05_p95 = value < stats.p05 or value > stats.p95

        iqr_distance = (abs(delta) / stats.iqr) if stats.iqr > 0.001 else 0.0

        return {
            "median": stats.median,
            "delta": round(delta, 3),
            "iqr": stats.iqr,
            "iqr_distance": round(iqr_distance, 2),
            "is_outside_p05_p95": 1.0 if is_outside_p05_p95 else 0.0,
        }
