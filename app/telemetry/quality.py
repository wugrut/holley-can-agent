"""
Signal quality taxonomy and evaluation states.
"""

from __future__ import annotations

from enum import Enum


class SignalQuality(str, Enum):
    """
    Multi-state data quality classification.
    Prevents corrupted or out-of-envelope telemetry from entering analytical baselines.
    """
    VALID = "valid"               # Fresh, plausible, verified sensor reading
    STALE = "stale"               # Value unchanged beyond expected update interval (> 1.0s)
    MISSING = "missing"           # Sensor not installed or channel omitted from ECU broadcast
    OUT_OF_RANGE = "out_of_range" # Value exceeds physically plausible transducer limits
    INVALID = "invalid"           # Corrupted byte stream, IEEE 754 NaN, or +/-Inf
    ESTIMATED = "estimated"       # Synthesized, interpolated, or calculated derivative
    SIMULATED = "simulated"       # Produced by virtual simulator adapter
