"""
Unit tests for VehicleProfile and ModificationTimeline.
"""

import pytest

from app.vehicle.history import ModificationTimeline
from app.vehicle.profile import VehicleProfile


class TestVehicleProfileAndHistory:
    def test_vehicle_profile_defaults(self):
        profile = VehicleProfile(
            vehicle_id="veh_mustang_ls3",
            name="1989 Mustang LX",
            engine_name="GM 6.2L LS3",
            rev_limiter_rpm=6800.0,
        )
        assert profile.vehicle_id == "veh_mustang_ls3"
        assert profile.cylinder_count == 8
        assert profile.installed_sensors["oil_pressure"] is True
        assert profile.installed_sensors["wideband_bank2"] is False

    def test_modification_timeline_chronology(self):
        timeline = ModificationTimeline("veh_mustang_ls3")

        timeline.add_entry("2026-08-20", "exhaust", "Long tube headers installed")
        timeline.add_entry("2026-08-10", "camshaft", "BTR Stage 2 Camshaft installed")
        timeline.add_entry("2026-09-01", "tune_revision", "Tune updated for headers", tune_revision_id="Rev_2.0")

        # Verify sorted chronologically
        dates = [e.date for e in timeline.entries]
        assert dates == ["2026-08-10", "2026-08-20", "2026-09-01"]

    def test_non_causal_correlation_statement(self):
        timeline = ModificationTimeline("veh_mustang_ls3")
        timeline.add_entry("2026-08-15", "camshaft", "Cam swap completed")

        statement = timeline.correlate_observation("2026-08-22", "elevated idle vacuum")
        # Ensure it does NOT use 'caused by'
        assert "caused" not in statement.lower()
        assert "was observed following" in statement.lower()
        assert "2026-08-15" in statement
