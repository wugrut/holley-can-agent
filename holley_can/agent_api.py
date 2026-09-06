"""
agent_api.py — FastAPI REST + WebSocket interface for the Holley CAN Agent.

Exposes live ECU data, historical queries, alert status, and discovery
info via REST endpoints. Streams real-time updates to the web dashboard
via WebSocket.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import csv
import io
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .alerts import Alert, AlertEngine
from .copilot_service import CopilotService
from .listener import CANListener
from .protocol import DecodedFrame
from .storage import TimeSeriesStorage

logger = logging.getLogger(__name__)

# Directory for static files (dashboard)
if getattr(sys, "frozen", False):
    import os
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    STATIC_DIR = Path(base_dir) / "holley_can" / "static"
    if not STATIC_DIR.exists():
        STATIC_DIR = Path(sys.executable).parent / "holley_can" / "static"
else:
    STATIC_DIR = Path(__file__).parent / "static"


class DashboardBroadcaster:
    """
    Manages WebSocket connections and broadcasts live data.

    Throttles updates to a configurable interval to avoid flooding
    slow clients (phones on WiFi).
    """

    def __init__(self, update_rate_ms: int = 50):
        self.connections: list[WebSocket] = []
        self.update_interval = update_rate_ms / 1000.0
        self._last_broadcast = 0.0
        self._pending_data: dict[str, Any] = {}
        self._pending_alerts: list[dict] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.connections.append(ws)
        logger.info("Dashboard client connected (%d total)", len(self.connections))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.connections:
            self.connections.remove(ws)
        logger.info("Dashboard client disconnected (%d remaining)", len(self.connections))

    async def on_frame(self, frame: DecodedFrame) -> None:
        """Buffer frame data for next broadcast cycle."""
        self._pending_data[frame.name] = {
            "name": frame.name,
            "label": frame.label,
            "unit": frame.unit,
            "value": round(frame.value_a, 3),
            "value_b": round(frame.value_b, 3),
            "timestamp": frame.timestamp,
        }

        # Throttled broadcast
        now = time.time()
        if (now - self._last_broadcast) >= self.update_interval:
            await self._broadcast()
            self._last_broadcast = now

    async def on_alert(self, alert: Alert) -> None:
        """Queue an alert for broadcast."""
        self._pending_alerts.append(alert.to_dict())
        await self._broadcast()

    async def _broadcast(self) -> None:
        """Send buffered data to all connected WebSocket clients."""
        if not self.connections:
            self._pending_data.clear()
            self._pending_alerts.clear()
            return

        message = json.dumps({
            "type": "update",
            "channels": self._pending_data,
            "alerts": self._pending_alerts,
            "timestamp": time.time(),
        })

        self._pending_data = {}
        self._pending_alerts = []

        dead: list[WebSocket] = []
        for ws in self.connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws)


def create_app(
    listener: CANListener,
    storage: TimeSeriesStorage,
    broadcaster: DashboardBroadcaster,
    alert_engine: Optional[AlertEngine] = None,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(
        title="Holley CAN Agent",
        description="Agentic ECU monitoring interface for the Holley Terminator X Max",
        version="0.1.0",
    )

    # CORS for local network access
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Serve static files (dashboard)
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ── REST Endpoints ──────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        """Serve the main dashboard page."""
        index_path = STATIC_DIR / "index.html"
        if index_path.exists():
            return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
        return HTMLResponse(
            content="<h1>Holley CAN Agent</h1><p>Dashboard not found. Check static/index.html.</p>"
        )

    @app.get("/api/live")
    async def get_live_data():
        """Current snapshot of all decoded channels."""
        return {
            "channels": listener.get_live_snapshot(),
            "timestamp": time.time(),
            "ecu_serial": listener.ecu_serial,
        }

    @app.get("/api/live/{channel}")
    async def get_live_channel(channel: str):
        """Single channel current value."""
        value = listener.get_channel_value(channel)
        if value is None:
            return {"error": f"Channel '{channel}' not found", "available": list(listener.get_live_snapshot().keys())}
        snapshot = listener.get_live_snapshot().get(channel, {})
        return {"channel": channel, **snapshot}

    @app.get("/api/history")
    async def get_history(
        channel: str = Query(..., description="Channel name"),
        start: Optional[float] = Query(None, description="Start time (UNIX epoch)"),
        end: Optional[float] = Query(None, description="End time (UNIX epoch)"),
        limit: int = Query(1000, le=10000),
        aggregation: Optional[str] = Query(None, regex="^(avg|min|max)$"),
        bucket_seconds: int = Query(60, ge=1, le=86400),
    ):
        """Query historical data with optional aggregation."""
        data = await storage.query_history(
            channel=channel,
            start_time=start,
            end_time=end,
            limit=limit,
            aggregation=aggregation,
            bucket_seconds=bucket_seconds,
        )
        return {
            "channel": channel,
            "count": len(data),
            "data": data,
        }

    @app.get("/api/alerts")
    async def get_alerts(
        active_only: bool = Query(False),
        limit: int = Query(50, le=500),
        since: Optional[float] = Query(None),
    ):
        """Get current alerts."""
        from .alerts import AlertEngine
        # Active alerts from the engine are passed via broadcaster
        active = []
        recent = await storage.query_alerts(limit=limit, since=since)
        return {
            "active": active,
            "recent": recent,
        }

    @app.get("/api/discovery")
    async def get_discovery():
        """List all discovered CAN IDs and their mappings."""
        return {
            "channels": listener.get_discovery_info(),
            "ecu_serial": listener.ecu_serial,
        }

    @app.get("/api/health")
    async def get_health():
        """System health: CAN bus status, error rate, buffer depth, DB stats."""
        db_stats = await storage.get_db_stats()
        return {
            "can": listener.stats,
            "database": db_stats,
            "timestamp": time.time(),
        }

    @app.get("/api/history/channels")
    async def get_available_channels():
        """List all channels that have historical data."""
        snapshot = listener.get_live_snapshot()
        return {
            "channels": [
                {"name": name, "label": info.get("label", name), "unit": info.get("unit", "")}
                for name, info in snapshot.items()
            ]
        }

    # ── Run Logger API ──────────────────────────────────────────────────

    @app.post("/api/log/start")
    async def start_logging(name: str = Query("run_log", description="Session name")):
        """Start a new logging session."""
        session_id = await storage.start_session(name)
        return {"status": "success", "session_id": session_id, "name": name}

    @app.post("/api/log/stop")
    async def stop_logging():
        """Stop the currently active logging session."""
        session_id = await storage.stop_active_session()
        if session_id:
            return {"status": "success", "session_id": session_id}
        return {"status": "error", "message": "No active logging session found"}

    @app.get("/api/log/status")
    async def get_logging_status():
        """Return the current logging status."""
        active = await storage.get_active_session()
        return {
            "logging": active is not None,
            "session": active
        }

    @app.get("/api/log/sessions")
    async def get_sessions():
        """Get all recorded logging sessions."""
        sessions = await storage.get_sessions()
        return {"sessions": sessions}

    @app.get("/api/log/export/{session_id}")
    async def export_session_csv(session_id: int):
        """Export session data as a downloadable CSV stream."""
        data = await storage.get_session_data(session_id)
        
        def generate_csv():
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Header
            writer.writerow(["timestamp", "channel", "label", "value_a", "value_b", "unit"])
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)
            
            for row in data:
                writer.writerow([
                    row["timestamp"],
                    row["channel"],
                    row.get("label", ""),
                    row["value_a"],
                    row.get("value_b", ""),
                    row.get("unit", "")
                ])
                yield output.getvalue()
                output.seek(0)
                output.truncate(0)
                
        headers = {
            "Content-Disposition": f"attachment; filename=holley_session_{session_id}.csv"
        }
        return StreamingResponse(generate_csv(), media_type="text/csv", headers=headers)

    # ── AI Copilot ("Ask Your Engine") ──────────────────────────────────

    copilot_service = CopilotService()

    @app.post("/api/copilot/ask")
    async def copilot_ask(payload: dict):
        """Processes conversational queries grounded in live ECU telemetry."""
        question = payload.get("question", "").strip()
        if not question:
            return {"error": "Question cannot be empty."}

        snapshot = listener.get_live_snapshot()
        active_alerts = alert_engine.get_active_alerts() if alert_engine else []
        return copilot_service.ask(
            question=question,
            snapshot=snapshot,
            active_alerts=active_alerts,
            stats=listener.stats,
        )

    @app.get("/api/copilot/suggestions")
    async def copilot_suggestions():
        """Returns recommended questions for quick chip prompts."""
        return {
            "suggestions": [
                "Why is my idle hunting or surging?",
                "Analyze fuel learn and closed-loop trims",
                "Check boost and air-fuel ratio safety margin",
                "Are there any active warnings or faults?",
                "Check electrical and alternator charging voltage",
                "Summarize current engine health",
            ]
        }

    # ── WebSocket ───────────────────────────────────────────────────────

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        """WebSocket for real-time dashboard updates."""
        await broadcaster.connect(ws)
        try:
            # Send initial snapshot immediately
            await ws.send_text(json.dumps({
                "type": "init",
                "channels": listener.get_live_snapshot(),
                "discovery": listener.get_discovery_info(),
                "stats": listener.stats,
                "timestamp": time.time(),
            }))

            # Keep alive — client can send pings or requests
            while True:
                data = await ws.receive_text()
                if data == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))
                elif data == "snapshot":
                    await ws.send_text(json.dumps({
                        "type": "snapshot",
                        "channels": listener.get_live_snapshot(),
                        "stats": listener.stats,
                    }))
        except WebSocketDisconnect:
            broadcaster.disconnect(ws)
        except Exception as e:
            logger.error("WebSocket error: %s", e)
            broadcaster.disconnect(ws)

    return app
