"""
Vehicle modification history and non-causal correlation timeline.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ModificationEntry:
    """Individual modification or maintenance record on the vehicle."""
    entry_id: str
    date: str               # ISO date string (YYYY-MM-DD)
    timestamp: float        # UNIX timestamp for sorting
    category: str           # 'camshaft', 'intake', 'exhaust', 'fuel_system', 'boost', 'tune_revision', 'maintenance'
    description: str
    tune_revision_id: Optional[str] = None
    notes: Optional[str] = None


class ModificationTimeline:
    """
    Chronological timeline of vehicle mechanical and calibration changes.
    Enforces safe linguistic correlation rules without asserting unverified causation.
    """

    def __init__(self, vehicle_id: str) -> None:
        self.vehicle_id = vehicle_id
        self.entries: List[ModificationEntry] = []

    def add_entry(
        self,
        date: str,
        category: str,
        description: str,
        tune_revision_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> ModificationEntry:
        """Adds a verified modification record to timeline."""
        entry_id = f"mod_{len(self.entries) + 1:03d}"
        entry = ModificationEntry(
            entry_id=entry_id,
            date=date,
            timestamp=time.time(),
            category=category,
            description=description,
            tune_revision_id=tune_revision_id,
            notes=notes,
        )
        self.entries.append(entry)
        self.entries.sort(key=lambda e: e.date)
        return entry

    def find_modifications_before(self, date: str) -> List[ModificationEntry]:
        """Returns modifications completed prior to a given session date."""
        return [e for e in self.entries if e.date <= date]

    def correlate_observation(self, observation_date: str, observed_behavior: str) -> str:
        """
        Synthesizes historical context using safe correlative language:
        e.g. 'This behavior was first observed after the camshaft upgrade on 2026-08-15.'
        """
        prior_mods = self.find_modifications_before(observation_date)
        if not prior_mods:
            return f"No modification records precede this observation on {observation_date}."

        latest_mod = prior_mods[-1]
        return (
            f"The change in {observed_behavior} was observed following the {latest_mod.category} "
            f"change ('{latest_mod.description}') logged on {latest_mod.date}. "
            f"Additional baseline runs are recommended to verify if this behavior correlates with that modification."
        )
