"""
Event data types and classification schemas for deterministic event detection.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class EventType(str, Enum):
    ENGINE_START = "engine_start"
    ENGINE_STOP = "engine_stop"
    IDLE = "idle"
    IDLE_HUNTING = "idle_hunting"
    CRUISE = "cruise"
    ACCELERATION = "acceleration"
    DECELERATION = "deceleration"
    WOT_PULL = "wot_pull"
    THERMAL_EVENT = "thermal_event"
    VOLTAGE_SAG = "voltage_sag"
    SENSOR_DROPOUT = "sensor_dropout"
    FUELING_DEVIATION = "fueling_deviation"


class EventSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class EngineEvent:
    """
    Discrete, auditable engine event identified by deterministic state rules.
    """
    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:10]}")
    event_type: EventType = EventType.IDLE
    severity: EventSeverity = EventSeverity.INFO
    start_time: float = 0.0
    end_time: float = 0.0
    duration_s: float = 0.0
    signals_involved: List[str] = field(default_factory=list)
    calculated_metrics: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    evidence: str = ""
