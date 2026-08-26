"""
storage.py — SQLite time-series storage for HEFI CAN data.

Stores decoded CAN frames at a configurable sample rate with automatic
daily compaction and data retention policies. Uses WAL mode for
concurrent read/write from the listener and API layers.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from .protocol import DecodedFrame

logger = logging.getLogger(__name__)

# Schema version for future migrations
SCHEMA_VERSION = 1

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS can_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    channel TEXT NOT NULL,
    label TEXT,
    value_a REAL NOT NULL,
    value_b REAL,
    unit TEXT,
    raw_id INTEGER,
    raw_hex TEXT
);

CREATE INDEX IF NOT EXISTS idx_can_data_timestamp ON can_data(timestamp);
CREATE INDEX IF NOT EXISTS idx_can_data_channel ON can_data(channel);
CREATE INDEX IF NOT EXISTS idx_can_data_channel_timestamp ON can_data(channel, timestamp);

CREATE TABLE IF NOT EXISTS alerts_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    severity TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    channel TEXT,
    message TEXT NOT NULL,
    value REAL,
    threshold REAL
);

CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON alerts_log(timestamp);

CREATE TABLE IF NOT EXISTS log_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL
);
"""


class TimeSeriesStorage:
    """
    SQLite-backed time-series storage with downsampling.

    Accepts decoded CAN frames and stores them at a configurable rate
    (default 1 Hz) to keep database size manageable for long-term retention.
    """

    def __init__(
        self,
        db_path: str = "./data/holley_can.db",
        sample_rate_hz: float = 1.0,
        retention_days: int = 90,
        wal_mode: bool = True,
    ):
        self.db_path = db_path
        self.sample_interval = 1.0 / sample_rate_hz
        self.retention_days = retention_days
        self.wal_mode = wal_mode

        # Track last write time per channel for downsampling
        self._last_write: dict[str, float] = {}

        # Batch buffer for efficient writes
        self._batch: list[tuple] = []
        self._batch_lock = asyncio.Lock()
        self._batch_interval = 1.0  # Flush every 1 second

        self._db: Optional[aiosqlite.Connection] = None
        self._flush_task: Optional[asyncio.Task] = None

    async def initialize(self) -> None:
        """Open the database, create tables, and start the flush loop."""
        # Ensure directory exists
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)

        self._db = await aiosqlite.connect(self.db_path)

        if self.wal_mode:
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA synchronous=NORMAL")

        # Optimize for write-heavy workload
        await self._db.execute("PRAGMA cache_size=-64000")  # 64 MB cache
        await self._db.execute("PRAGMA temp_store=MEMORY")

        await self._db.executescript(CREATE_TABLES_SQL)
        await self._db.commit()

        # Start background flush loop
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info("Storage initialized: %s", self.db_path)

    async def close(self) -> None:
        """Flush remaining data and close the database."""
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        await self._flush_batch()

        if self._db:
            await self._db.close()
            logger.info("Storage closed")

    # ── Frame ingestion ─────────────────────────────────────────────────

    async def on_frame(self, frame: DecodedFrame) -> None:
        """
        Receive a decoded frame from the CAN listener.

        Applies downsampling: only stores one sample per channel per
        sample_interval period.
        """
        name = frame.name
        now = frame.timestamp

        last = self._last_write.get(name, 0)
        if (now - last) < self.sample_interval:
            return  # Skip — too soon since last write for this channel

        self._last_write[name] = now

        row = (
            now,
            name,
            frame.label,
            frame.value_a,
            frame.value_b,
            frame.unit,
            frame.raw_id,
            frame.raw_data.hex(),
        )

        async with self._batch_lock:
            self._batch.append(row)

    async def log_alert(
        self,
        severity: str,
        alert_type: str,
        channel: str,
        message: str,
        value: Optional[float] = None,
        threshold: Optional[float] = None,
    ) -> None:
        """Log an alert event to the database."""
        if self._db:
            await self._db.execute(
                "INSERT INTO alerts_log (timestamp, severity, alert_type, channel, message, value, threshold) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (time.time(), severity, alert_type, channel, message, value, threshold),
            )
            await self._db.commit()

    # ── Query interface ─────────────────────────────────────────────────

    async def query_history(
        self,
        channel: str,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 1000,
        aggregation: Optional[str] = None,
        bucket_seconds: int = 60,
    ) -> list[dict[str, Any]]:
        """
        Query historical data for a channel.

        Args:
            channel: Channel name (e.g., "rpm", "map_kpa").
            start_time: UNIX epoch start (default: 1 hour ago).
            end_time: UNIX epoch end (default: now).
            limit: Max rows to return.
            aggregation: "avg", "min", "max", or None for raw data.
            bucket_seconds: Time bucket size for aggregation.
        """
        if not self._db:
            return []

        if start_time is None:
            start_time = time.time() - 3600
        if end_time is None:
            end_time = time.time()

        if aggregation and aggregation in ("avg", "min", "max"):
            sql = f"""
                SELECT
                    CAST(timestamp / ? AS INTEGER) * ? AS bucket,
                    {aggregation}(value_a) AS value,
                    COUNT(*) AS samples
                FROM can_data
                WHERE channel = ? AND timestamp BETWEEN ? AND ?
                GROUP BY bucket
                ORDER BY bucket
                LIMIT ?
            """
            params = (bucket_seconds, bucket_seconds, channel, start_time, end_time, limit)
        else:
            sql = """
                SELECT timestamp, value_a, value_b, raw_hex
                FROM can_data
                WHERE channel = ? AND timestamp BETWEEN ? AND ?
                ORDER BY timestamp
                LIMIT ?
            """
            params = (channel, start_time, end_time, limit)

        rows = []
        async with self._db.execute(sql, params) as cursor:
            columns = [desc[0] for desc in cursor.description]
            async for row in cursor:
                rows.append(dict(zip(columns, row)))

        return rows

    async def query_alerts(
        self,
        limit: int = 50,
        severity: Optional[str] = None,
        since: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        """Query recent alert log entries."""
        if not self._db:
            return []

        conditions = []
        params: list[Any] = []

        if severity:
            conditions.append("severity = ?")
            params.append(severity)
        if since:
            conditions.append("timestamp > ?")
            params.append(since)

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"""
            SELECT * FROM alerts_log
            WHERE {where}
            ORDER BY timestamp DESC
            LIMIT ?
        """
        params.append(limit)

        rows = []
        async with self._db.execute(sql, params) as cursor:
            columns = [desc[0] for desc in cursor.description]
            async for row in cursor:
                rows.append(dict(zip(columns, row)))

        return rows

    async def get_db_stats(self) -> dict:
        """Return database statistics."""
        if not self._db:
            return {}

        stats = {}
        async with self._db.execute("SELECT COUNT(*) FROM can_data") as cursor:
            row = await cursor.fetchone()
            stats["total_rows"] = row[0]

        async with self._db.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM can_data"
        ) as cursor:
            row = await cursor.fetchone()
            stats["earliest_timestamp"] = row[0]
            stats["latest_timestamp"] = row[1]

        # File size
        try:
            stats["file_size_mb"] = round(
                os.path.getsize(self.db_path) / (1024 * 1024), 2
            )
        except OSError:
            stats["file_size_mb"] = 0

        return stats

    # ── Maintenance ─────────────────────────────────────────────────────

    async def cleanup_old_data(self) -> int:
        """Delete data older than retention_days. Returns rows deleted."""
        if not self._db:
            return 0

        cutoff = time.time() - (self.retention_days * 86400)
        cursor = await self._db.execute(
            "DELETE FROM can_data WHERE timestamp < ?", (cutoff,)
        )
        await self._db.commit()
        deleted = cursor.rowcount
        if deleted > 0:
            logger.info("Cleaned up %d rows older than %d days", deleted, self.retention_days)
            await self._db.execute("PRAGMA optimize")
        return deleted

    # ── Run Logger Sessions ─────────────────────────────────────────────

    async def start_session(self, name: str) -> int:
        """Start a new logging session. Returns the session ID."""
        if not self._db:
            raise RuntimeError("Database not initialized")

        # Automatically stop any current active session first
        await self.stop_active_session()

        now = time.time()
        cursor = await self._db.execute(
            "INSERT INTO log_sessions (name, start_time) VALUES (?, ?)",
            (name, now)
        )
        await self._db.commit()
        session_id = cursor.lastrowid
        logger.info("Started logging session %d: %s", session_id, name)
        return session_id

    async def stop_active_session(self) -> Optional[int]:
        """Stop the currently active session. Returns the stopped session ID, or None."""
        if not self._db:
            return None

        active = await self.get_active_session()
        if not active:
            return None

        session_id = active["id"]
        now = time.time()
        await self._db.execute(
            "UPDATE log_sessions SET end_time = ? WHERE id = ?",
            (now, session_id)
        )
        await self._db.commit()
        logger.info("Stopped logging session %d", session_id)
        return session_id

    async def get_active_session(self) -> Optional[dict[str, Any]]:
        """Return details of the currently active session, if any."""
        if not self._db:
            return None

        async with self._db.execute(
            "SELECT id, name, start_time, end_time FROM log_sessions WHERE end_time IS NULL LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {"id": row[0], "name": row[1], "start_time": row[2], "end_time": row[3]}
        return None

    async def get_sessions(self) -> list[dict[str, Any]]:
        """Return a list of all recorded sessions."""
        if not self._db:
            return []

        rows = []
        async with self._db.execute(
            "SELECT id, name, start_time, end_time FROM log_sessions ORDER BY start_time DESC"
        ) as cursor:
            async for row in cursor:
                rows.append({"id": row[0], "name": row[1], "start_time": row[2], "end_time": row[3]})
        return rows

    async def get_session_data(self, session_id: int) -> list[dict[str, Any]]:
        """Return all can_data rows that fall within the session's time window."""
        if not self._db:
            return []

        # Get session time bounds
        async with self._db.execute(
            "SELECT start_time, end_time FROM log_sessions WHERE id = ?",
            (session_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return []
            start_time, end_time = row

        if end_time is None:
            end_time = time.time()

        # Query all channels in that window
        sql = """
            SELECT timestamp, channel, label, value_a, value_b, unit
            FROM can_data
            WHERE timestamp BETWEEN ? AND ?
            ORDER BY timestamp, channel
        """
        rows = []
        async with self._db.execute(sql, (start_time, end_time)) as cursor:
            columns = [desc[0] for desc in cursor.description]
            async for r in cursor:
                rows.append(dict(zip(columns, r)))
        return rows

    # ── Internal ────────────────────────────────────────────────────────

    async def _flush_loop(self) -> None:
        """Periodically flush the batch buffer to disk."""
        while True:
            try:
                await asyncio.sleep(self._batch_interval)
                await self._flush_batch()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Flush error: %s", e)

    async def _flush_batch(self) -> None:
        """Write buffered rows to SQLite."""
        async with self._batch_lock:
            if not self._batch or not self._db:
                return
            batch = self._batch.copy()
            self._batch.clear()

        await self._db.executemany(
            "INSERT INTO can_data (timestamp, channel, label, value_a, value_b, unit, raw_id, raw_hex) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            batch,
        )
        await self._db.commit()
