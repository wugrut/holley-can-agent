"""
TelemetrySignal dataclass representing a discrete, decoded automotive signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.telemetry.quality import SignalQuality


@dataclass(frozen=True)
class TelemetrySignal:
    """
    Normalized, self-describing signal emitted by protocol decoders.

    Attributes:
        signal_name: Unique snake_case signal identifier (e.g. 'engine_rpm').
        value: Physical engineering value.
        unit: Engineering unit string (e.g. 'rpm', 'kPa', 'degF', 'V').
        timestamp: Time of reception in UNIX epoch seconds.
        source: Origin identifier ('can', 'derived', 'simulator').
        quality: SignalQuality classification.
        confidence: Certainty score between 0.0 and 1.0.
        raw_channel_index: Original protocol channel index if applicable.
    """
    signal_name: str
    value: float
    unit: str
    timestamp: float
    source: str = "can"
    quality: SignalQuality = SignalQuality.VALID
    confidence: float = 1.0
    raw_channel_index: Optional[int] = None

    @property
    def is_usable_for_baseline(self) -> bool:
        """Only VALID signals may enter vehicle baseline calculations."""
        return self.quality == SignalQuality.VALID
