"""
Deterministic tool registry for 'Ask Your Engine' conversational queries.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.baseline.engine import BaselineEngine
from app.diagnostics.engine import DiagnosticEngine
from app.diagnostics.finding import StructuredDiagnostic
from app.events.detector import EventDetector
from app.storage.repository import TelemetryRepository
from app.vehicle.history import ModificationTimeline
from app.vehicle.profile import VehicleProfile


class EngineCopilotToolRegistry:
    """
    Executes deterministic data retrieval tools on behalf of the AI reasoning layer.
    Guarantees that telemetry, events, and diagnostic records cannot be fabricated.
    """

    def __init__(
        self,
        repository: TelemetryRepository,
        vehicle_profile: VehicleProfile,
        timeline: ModificationTimeline,
        diagnostic_engine: DiagnosticEngine,
        baseline_engine: Optional[BaselineEngine] = None,
    ) -> None:
        self.repo = repository
        self.profile = vehicle_profile
        self.timeline = timeline
        self.diagnostic_engine = diagnostic_engine
        self.baseline_engine = baseline_engine

    def get_vehicle_profile(self) -> Dict[str, Any]:
        """Returns verified engine, injector, ECU, and sensor configuration."""
        return {
            "vehicle_id": self.profile.vehicle_id,
            "name": self.profile.name,
            "engine": self.profile.engine_name,
            "displacement_liters": self.profile.displacement_liters,
            "cylinders": self.profile.cylinder_count,
            "ecu_type": self.profile.ecu_type,
            "fuel_type": self.profile.fuel_type,
            "injector_flow_lb_hr": self.profile.injector_flow_lb_hr,
            "base_fuel_pressure_psi": self.profile.base_fuel_pressure_psi,
            "rev_limiter_rpm": self.profile.rev_limiter_rpm,
        }

    def get_recent_sessions(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Returns recent recording sessions."""
        return self.repo.list_sessions(limit=limit)

    def get_modification_history(self) -> List[Dict[str, Any]]:
        """Returns timeline of vehicle modifications and maintenance."""
        return [
            {
                "entry_id": e.entry_id,
                "date": e.date,
                "category": e.category,
                "description": e.description,
                "tune_revision": e.tune_revision_id,
                "notes": e.notes,
            }
            for e in self.timeline.entries
        ]

    def query_diagnostics(
        self,
        session_id: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Returns active or session-specific diagnostic findings."""
        # Query recent telemetry to evaluate diagnostics if session_id provided
        if session_id:
            raw_samples = self.repo.query_telemetry(session_id, limit=2000)
            from app.telemetry.sample import NormalizedTelemetrySample
            samples = [
                NormalizedTelemetrySample(
                    timestamp=r["timestamp"],
                    engine_rpm=r["engine_rpm"],
                    map_kpa=r["map_kpa"],
                    tps=r["tps"],
                    coolant_temp=r["coolant_temp"],
                    target_afr=r["target_afr"],
                    afr_measured=r["afr_measured"],
                    fuel_learn=r["fuel_learn"],
                    battery_voltage=r["battery_voltage"],
                )
                for r in raw_samples
            ]
            detector = EventDetector()
            events = []
            for s in samples:
                events.extend(detector.feed_sample(s))
            diags = self.diagnostic_engine.evaluate_session(samples, events)
        else:
            diags = []

        if category:
            diags = [d for d in diags if d.category == category]

        return [
            {
                "diagnostic_id": d.diagnostic_id,
                "title": d.title,
                "severity": d.severity,
                "category": d.category,
                "observation": d.observation,
                "inferred_condition": d.inferred_condition,
                "possible_causes": d.possible_causes,
                "recommended_tests": d.recommended_tests,
                "confidence": d.confidence,
                "evidence": [{"name": e.name, "value": e.value, "unit": e.unit} for e in d.evidence],
            }
            for d in diags
        ]

    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Dynamic dispatch for function calling."""
        tools = {
            "get_vehicle_profile": lambda args: self.get_vehicle_profile(),
            "get_recent_sessions": lambda args: self.get_recent_sessions(**args),
            "get_modification_history": lambda args: self.get_modification_history(),
            "query_diagnostics": lambda args: self.query_diagnostics(**args),
        }
        handler = tools.get(tool_name)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}
        return handler(arguments)
