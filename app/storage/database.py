"""
SQLite connection manager with WAL mode and high-throughput write pragmas.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Generator

from app.storage.schema import CREATE_EVENTS_TABLE, CREATE_INDEXES, CREATE_SESSIONS_TABLE, CREATE_TELEMETRY_TABLE


class Database:
    """Manages SQLite database connections and schema initialization."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        self._mem_conn: sqlite3.Connection | None = None
        if self.db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        else:
            self._mem_conn = sqlite3.connect(":memory:", timeout=30.0)
            self._mem_conn.row_factory = sqlite3.Row
        self._init_schema()

    def get_connection(self) -> sqlite3.Connection:
        """Returns connection configured with WAL mode and high-performance pragmas."""
        if self._mem_conn is not None:
            return self._mem_conn

        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        
        # High-performance pragmas for time-series logging
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA temp_store = MEMORY;")
        conn.execute("PRAGMA cache_size = -64000;")  # 64MB cache
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_schema(self) -> None:
        """Applies schema tables and indexes."""
        with self.get_connection() as conn:
            conn.execute(CREATE_SESSIONS_TABLE)
            conn.execute(CREATE_TELEMETRY_TABLE)
            conn.execute(CREATE_EVENTS_TABLE)
            for idx in CREATE_INDEXES:
                conn.execute(idx)
            conn.commit()
