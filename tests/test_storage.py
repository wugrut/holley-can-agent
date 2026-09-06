"""
Unit tests for SQLite WAL time-series storage and SessionManager.
"""

import time
import pytest

from app.sessions.manager import SessionManager
from app.sessions.metadata import SessionType
from app.storage.database import Database
from app.storage.repository import TelemetryRepository
from app.telemetry.sample import NormalizedTelemetrySample


class TestStorageAndSessions:
    def test_database_init_in_memory(self):
        db = Database(":memory:")
        with db.get_connection() as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row["name"] for row in cursor.fetchall()]
            assert "sessions" in tables
            assert "telemetry_samples" in tables
            assert "session_events" in tables

    def test_repository_session_lifecycle(self):
        db = Database(":memory:")
        repo = TelemetryRepository(db)

        session_id = "sess_test_001"
        repo.insert_session(
            session_id=session_id,
            vehicle_id="veh_ls3",
            session_type="street_drive",
            start_time=1000.0,
            tune_revision="Rev_1.2",
            driver_notes="Baseline run",
        )

        sessions = repo.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == session_id
        assert sessions[0]["vehicle_id"] == "veh_ls3"
        assert sessions[0]["tune_revision"] == "Rev_1.2"

        # Update summary
        repo.update_session_summary(
            session_id=session_id,
            end_time=1100.0,
            sample_count=200,
            valid_sample_pct=98.5,
        )

        updated = repo.list_sessions()[0]
        assert updated["end_time"] == 1100.0
        assert updated["sample_count"] == 200
        assert updated["valid_sample_pct"] == 98.5

    def test_telemetry_batch_insert_and_query(self):
        db = Database(":memory:")
        repo = TelemetryRepository(db)

        session_id = "sess_batch_001"
        repo.insert_session(session_id, "veh_fox", "wot_pull", 2000.0)

        samples = []
        for i in range(10):
            s = NormalizedTelemetrySample(
                timestamp=2000.0 + (i * 0.1),
                engine_rpm=800.0 + (i * 50),
                map_kpa=35.0,
                tps=0.0,
                coolant_temp=185.0,
                target_afr=14.7,
                afr_measured=14.7,
                battery_voltage=14.2,
            )
            s.compute_derived_metrics()
            samples.append(s)

        repo.insert_telemetry_batch(session_id, samples)

        results = repo.query_telemetry(session_id)
        assert len(results) == 10
        assert results[0]["engine_rpm"] == 800.0
        assert results[-1]["engine_rpm"] == 1250.0

        # Query time slice
        slice_res = repo.query_telemetry(session_id, start_time=2000.2, end_time=2000.5)
        assert len(slice_res) == 4

    def test_session_manager_auto_flush(self):
        db = Database(":memory:")
        repo = TelemetryRepository(db)
        mgr = SessionManager(repo, buffer_size=5)

        assert not mgr.is_recording
        meta = mgr.start_session(vehicle_id="veh_test", session_type=SessionType.IDLE_TEST)
        assert mgr.is_recording

        # Record 7 samples (buffer size 5 -> should trigger 1 auto-flush of 5, leaving 2 in buffer)
        for i in range(7):
            s = NormalizedTelemetrySample(timestamp=time.time() + i, engine_rpm=850.0)
            mgr.record_sample(s)

        # 5 flushed to db
        db_rows = repo.query_telemetry(meta.session_id)
        assert len(db_rows) == 5

        # End session -> flushes remaining 2
        closed = mgr.end_session()
        assert not mgr.is_recording
        assert closed.sample_count == 7
        assert closed.valid_sample_pct == 100.0

        all_rows = repo.query_telemetry(meta.session_id)
        assert len(all_rows) == 7
