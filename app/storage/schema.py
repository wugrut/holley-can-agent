"""
SQLite database schema definitions and migrations for time-series session storage.
"""

from __future__ import annotations

CREATE_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    vehicle_id TEXT NOT NULL,
    session_type TEXT NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL,
    tune_revision TEXT,
    driver_notes TEXT,
    ambient_temp_f REAL,
    ambient_pressure_kpa REAL,
    sample_count INTEGER DEFAULT 0,
    valid_sample_pct REAL DEFAULT 100.0,
    created_at REAL NOT NULL
);
"""

CREATE_TELEMETRY_TABLE = """
CREATE TABLE IF NOT EXISTS telemetry_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    engine_rpm REAL NOT NULL,
    map_kpa REAL NOT NULL,
    baro_kpa REAL NOT NULL,
    tps REAL NOT NULL,
    coolant_temp REAL NOT NULL,
    iat REAL NOT NULL,
    target_afr REAL NOT NULL,
    afr_measured REAL NOT NULL,
    fuel_learn REAL NOT NULL,
    closed_loop_active INTEGER NOT NULL,
    fuel_pw REAL NOT NULL,
    ignition_timing REAL NOT NULL,
    knock_retard REAL NOT NULL,
    battery_voltage REAL NOT NULL,
    trans_gear INTEGER NOT NULL,
    trans_temp REAL,
    oil_pressure REAL,
    fuel_pressure REAL,
    vehicle_speed REAL,
    boost_psi REAL NOT NULL,
    manifold_vacuum_inhg REAL NOT NULL,
    afr_error_pct REAL NOT NULL,
    injector_duty_pct REAL NOT NULL,
    quality_score REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);
"""

CREATE_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS session_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    duration_s REAL NOT NULL,
    evidence_json TEXT NOT NULL,
    calculated_metrics_json TEXT NOT NULL,
    confidence REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_telemetry_session_ts ON telemetry_samples(session_id, timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_telemetry_rpm_map ON telemetry_samples(session_id, engine_rpm, map_kpa);",
    "CREATE INDEX IF NOT EXISTS idx_events_session_type ON session_events(session_id, event_type);",
]
