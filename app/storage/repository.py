"""
Repository for high-performance batch insertion and querying of telemetry sessions.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from app.storage.database import Database
from app.telemetry.sample import NormalizedTelemetrySample


class TelemetryRepository:
    """Provides high-throughput batch writes and optimized query methods."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def insert_session(
        self,
        session_id: str,
        vehicle_id: str,
        session_type: str,
        start_time: float,
        tune_revision: Optional[str] = None,
        driver_notes: Optional[str] = None,
        ambient_temp_f: Optional[float] = None,
        ambient_pressure_kpa: Optional[float] = None,
    ) -> None:
        """Registers a new recording session."""
        sql = """
        INSERT INTO sessions (
            session_id, vehicle_id, session_type, start_time, tune_revision,
            driver_notes, ambient_temp_f, ambient_pressure_kpa, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        with self.db.get_connection() as conn:
            conn.execute(
                sql,
                (
                    session_id,
                    vehicle_id,
                    session_type,
                    start_time,
                    tune_revision,
                    driver_notes,
                    ambient_temp_f,
                    ambient_pressure_kpa,
                    time.time(),
                ),
            )
            conn.commit()

    def update_session_summary(
        self,
        session_id: str,
        end_time: float,
        sample_count: int,
        valid_sample_pct: float,
    ) -> None:
        """Finalizes session metadata upon recording completion."""
        sql = """
        UPDATE sessions
        SET end_time = ?, sample_count = ?, valid_sample_pct = ?
        WHERE session_id = ?;
        """
        with self.db.get_connection() as conn:
            conn.execute(sql, (end_time, sample_count, valid_sample_pct, session_id))
            conn.commit()

    def insert_telemetry_batch(
        self,
        session_id: str,
        samples: List[NormalizedTelemetrySample],
    ) -> None:
        """Inserts a batch of telemetry samples in a single transaction."""
        if not samples:
            return

        sql = """
        INSERT INTO telemetry_samples (
            session_id, timestamp, engine_rpm, map_kpa, baro_kpa, tps,
            coolant_temp, iat, target_afr, afr_measured, fuel_learn,
            closed_loop_active, fuel_pw, ignition_timing, knock_retard,
            battery_voltage, trans_gear, trans_temp, oil_pressure,
            fuel_pressure, vehicle_speed, boost_psi, manifold_vacuum_inhg,
            afr_error_pct, injector_duty_pct, quality_score
        ) VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?
        );
        """

        rows = [
            (
                session_id,
                s.timestamp,
                s.engine_rpm,
                s.map_kpa,
                s.baro_kpa,
                s.tps,
                s.coolant_temp,
                s.iat,
                s.target_afr,
                s.afr_measured,
                s.fuel_learn,
                1 if s.closed_loop_active else 0,
                s.fuel_pw,
                s.ignition_timing,
                s.knock_retard,
                s.battery_voltage,
                s.trans_gear,
                s.trans_temp,
                s.oil_pressure,
                s.fuel_pressure,
                s.vehicle_speed,
                s.boost_psi,
                s.manifold_vacuum_inhg,
                s.afr_error_pct,
                s.injector_duty_pct,
                s.overall_quality_score,
            )
            for s in samples
        ]

        with self.db.get_connection() as conn:
            conn.executemany(sql, rows)
            conn.commit()

    def query_telemetry(
        self,
        session_id: str,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 50000,
    ) -> List[Dict[str, Any]]:
        """Queries time-series telemetry for replay or analysis."""
        conditions = ["session_id = ?"]
        params: List[Any] = [session_id]

        if start_time is not None:
            conditions.append("timestamp >= ?")
            params.append(start_time)
        if end_time is not None:
            conditions.append("timestamp <= ?")
            params.append(end_time)

        sql = f"""
        SELECT * FROM telemetry_samples
        WHERE {' AND '.join(conditions)}
        ORDER BY timestamp ASC
        LIMIT ?;
        """
        params.append(limit)

        with self.db.get_connection() as conn:
            cursor = conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]

    def list_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Lists recent recording sessions."""
        sql = """
        SELECT * FROM sessions
        ORDER BY start_time DESC
        LIMIT ?;
        """
        with self.db.get_connection() as conn:
            cursor = conn.execute(sql, (limit,))
            return [dict(row) for row in cursor.fetchall()]
