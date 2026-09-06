"""
Signal validation and quality grading logic.
"""

from __future__ import annotations

import math
import time
from typing import Dict, Tuple

from app.telemetry.quality import SignalQuality
from app.telemetry.signals import TelemetrySignal


# Physical envelope bounds (min, max)
PHYSICAL_BOUNDS: Dict[str, Tuple[float, float]] = {
    "engine_rpm": (0.0, 12000.0),
    "map_kpa": (0.0, 500.0),
    "baro_kpa": (50.0, 125.0),
    "tps": (-2.0, 105.0),
    "coolant_temp": (-40.0, 320.0),
    "iat": (-40.0, 300.0),
    "target_afr": (8.0, 25.0),
    "afr_measured": (7.0, 25.0),
    "afr_bank1": (7.0, 25.0),
    "afr_bank2": (7.0, 25.0),
    "fuel_learn": (-50.0, 50.0),
    "ignition_timing": (-30.0, 65.0),
    "battery_voltage": (0.0, 20.0),
    "fuel_pw": (0.0, 35.0),
    "trans_gear": (0.0, 6.0),
    "trans_temp": (-40.0, 350.0),
    "oil_pressure": (0.0, 150.0),
    "fuel_pressure": (0.0, 150.0),
    "vehicle_speed": (0.0, 250.0),
}


class SignalValidator:
    """Evaluates raw values against physical limits, math validity, and staleness."""

    def __init__(self, staleness_timeout_s: float = 1.5) -> None:
        self.staleness_timeout_s = staleness_timeout_s
        self._last_signal_times: Dict[str, float] = {}
        self._last_signal_values: Dict[str, float] = {}

    def validate(
        self,
        signal_name: str,
        value: float,
        unit: str,
        timestamp: float,
        source: str = "can",
        raw_channel_index: int | None = None,
    ) -> TelemetrySignal:
        """Inspects signal value and produces a validated TelemetrySignal with quality tag."""
        # 1. Math validity check (NaN / Inf)
        if math.isnan(value) or math.isinf(value):
            return TelemetrySignal(
                signal_name=signal_name,
                value=0.0,
                unit=unit,
                timestamp=timestamp,
                source=source,
                quality=SignalQuality.INVALID,
                confidence=0.0,
                raw_channel_index=raw_channel_index,
            )

        # 2. Physical boundary check
        bounds = PHYSICAL_BOUNDS.get(signal_name)
        if bounds is not None:
            min_val, max_val = bounds
            if value < min_val or value > max_val:
                return TelemetrySignal(
                    signal_name=signal_name,
                    value=value,
                    unit=unit,
                    timestamp=timestamp,
                    source=source,
                    quality=SignalQuality.OUT_OF_RANGE,
                    confidence=0.2,
                    raw_channel_index=raw_channel_index,
                )

        # 3. Staleness check
        quality = SignalQuality.SIMULATED if source == "simulator" else SignalQuality.VALID
        now = time.time()
        last_time = self._last_signal_times.get(signal_name)
        if last_time is not None and (now - last_time) > self.staleness_timeout_s:
            quality = SignalQuality.STALE

        # Update tracking
        self._last_signal_times[signal_name] = now
        self._last_signal_values[signal_name] = value

        return TelemetrySignal(
            signal_name=signal_name,
            value=value,
            unit=unit,
            timestamp=timestamp,
            source=source,
            quality=quality,
            confidence=1.0 if quality in (SignalQuality.VALID, SignalQuality.SIMULATED) else 0.5,
            raw_channel_index=raw_channel_index,
        )
