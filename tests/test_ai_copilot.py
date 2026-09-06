"""
Unit tests for AI reasoning layer, tool registry, and EngineCopilot.
"""

import asyncio
import pytest

from app.ai.copilot import EngineCopilot
from app.ai.provider import DeterministicMockLLMProvider
from app.ai.tools import EngineCopilotToolRegistry
from app.diagnostics.engine import DiagnosticEngine
from app.storage.database import Database
from app.storage.repository import TelemetryRepository
from app.vehicle.history import ModificationTimeline
from app.vehicle.profile import VehicleProfile


class TestAICopilotAndTools:
    def test_tool_registry_direct_dispatch(self):
        db = Database(":memory:")
        repo = TelemetryRepository(db)
        profile = VehicleProfile(name="Foxbody LS3", engine_name="LS3 6.2L")
        timeline = ModificationTimeline("veh_01")
        timeline.add_entry("2026-08-10", "camshaft", "Cam upgrade")
        diag_engine = DiagnosticEngine()

        registry = EngineCopilotToolRegistry(repo, profile, timeline, diag_engine)

        prof = registry.get_vehicle_profile()
        assert prof["name"] == "Foxbody LS3"
        assert prof["cylinders"] == 8

        mods = registry.get_modification_history()
        assert len(mods) == 1
        assert mods[0]["category"] == "camshaft"

    def test_copilot_conversational_turn(self):
        async def _run():
            db = Database(":memory:")
            repo = TelemetryRepository(db)
            profile = VehicleProfile()
            timeline = ModificationTimeline("veh_01")
            timeline.add_entry("2026-08-15", "camshaft", "Cam installed")
            diag_engine = DiagnosticEngine()

            registry = EngineCopilotToolRegistry(repo, profile, timeline, diag_engine)
            provider = DeterministicMockLLMProvider()
            copilot = EngineCopilot(provider, registry)

            # Query about cam modification
            response = await copilot.ask("Did the problem start after my camshaft change?")
            assert response is not None
            assert len(copilot.conversation_history) >= 2

        asyncio.run(_run())
