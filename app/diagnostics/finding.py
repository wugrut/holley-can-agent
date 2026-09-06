"""
Structured diagnostic finding contracts with evidence attribution.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class DiagnosticEvidenceItem:
    """Individual metric contributing to an evidence chain."""
    name: str
    value: Any
    unit: str = ""
    description: str = ""


@dataclass
class StructuredDiagnostic:
    """
    Standardized finding emitted by the deterministic diagnostic engine.
    Strictly separates observation, evidence, inferred conditions, and recommendations.
    """
    diagnostic_id: str
    title: str
    severity: str                   # 'info' | 'warning' | 'critical'
    category: str                   # 'fueling' | 'idle' | 'sensors' | 'electrical' | 'thermal'
    observation: str
    evidence: List[DiagnosticEvidenceItem] = field(default_factory=list)
    inferred_condition: str = ""
    possible_causes: List[str] = field(default_factory=list)
    recommended_tests: List[str] = field(default_factory=list)
    confidence: float = 1.0
    data_validity_pct: float = 100.0
    timestamp: float = field(default_factory=time.time)
    unique_id: str = field(default_factory=lambda: f"diag_{uuid.uuid4().hex[:10]}")
