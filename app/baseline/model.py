"""
Robust statistical baseline data models (non-parametric metrics).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import numpy as np


@dataclass
class RobustStats:
    """Non-parametric summary statistics robust against transient outliers."""
    count: int = 0
    median: float = 0.0
    q25: float = 0.0
    q75: float = 0.0
    iqr: float = 0.0
    p05: float = 0.0
    p95: float = 0.0
    min_val: float = 0.0
    max_val: float = 0.0

    @classmethod
    def compute(cls, values: List[float]) -> Optional[RobustStats]:
        """Calculates robust metrics from a list of numerical samples."""
        if not values:
            return None

        arr = np.array(values, dtype=np.float64)
        count = len(arr)
        if count < 5:
            # Insufficient samples for quantile estimation
            med = float(np.median(arr))
            return cls(
                count=count,
                median=med,
                q25=med,
                q75=med,
                iqr=0.0,
                p05=float(np.min(arr)),
                p95=float(np.max(arr)),
                min_val=float(np.min(arr)),
                max_val=float(np.max(arr)),
            )

        q25, med, q75 = np.percentile(arr, [25, 50, 75])
        p05, p95 = np.percentile(arr, [5, 95])
        iqr = q75 - q25

        return cls(
            count=count,
            median=round(float(med), 3),
            q25=round(float(q25), 3),
            q75=round(float(q75), 3),
            iqr=round(float(iqr), 3),
            p05=round(float(p05), 3),
            p95=round(float(p95), 3),
            min_val=round(float(np.min(arr)), 3),
            max_val=round(float(np.max(arr)), 3),
        )


@dataclass
class BaselineCell:
    """Represents learned normal envelope for a specific signal within an operating bin."""
    condition_key: str
    signal_name: str
    stats: RobustStats
    last_updated: float


@dataclass
class VehicleBaselineProfile:
    """Full multidimensional baseline model for a specific vehicle."""
    vehicle_id: str
    cells: Dict[str, BaselineCell] = field(default_factory=dict)
