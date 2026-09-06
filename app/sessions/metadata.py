"""
Session metadata models and classification types.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SessionType(str, Enum):
    """Categorical classification of driving or dyno session."""
    COLD_START = "cold_start"
    IDLE_TEST = "idle_test"
    STREET_DRIVE = "street_drive"
    CRUISE = "cruise"
    WOT_PULL = "wot_pull"
    DYNO_RUN = "dyno_run"
    TROUBLESHOOTING = "troubleshooting"
    CUSTOM = "custom"


@dataclass
class SessionMetadata:
    """Metadata context associated with a recording session."""
    session_id: str = field(default_factory=lambda: f"sess_{uuid.uuid4().hex[:12]}")
    vehicle_id: str = "default_vehicle"
    session_type: SessionType = SessionType.STREET_DRIVE
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    tune_revision: Optional[str] = None
    driver_notes: Optional[str] = None
    ambient_temp_f: Optional[float] = None
    ambient_pressure_kpa: Optional[float] = 101.3
    sample_count: int = 0
    valid_sample_pct: float = 100.0
