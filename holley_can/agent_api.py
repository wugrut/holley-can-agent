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
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .alerts import Alert, AlertEngine
from .copilot_service import CopilotService
from .gemini_agent import GeminiAgent, GENAI_AVAILABLE
from .listener import CANListener
from .protocol import DecodedFrame
from .storage import TimeSeriesStorage
from .tune_optimizer import AutoHandoffWatcher, PostPullDetector, VETableOptimizer

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
    ve_optimizer = VETableOptimizer(base_fuel_psi=58.0)
    pull_detector = PostPullDetector(base_fuel_psi=58.0)
    gemini_agent = GeminiAgent(ve_optimizer=ve_optimizer)

    async def _on_auto_event(event: Dict[str, Any]):
        """Zero-touch handler triggered when a Holley datalog or tune file is saved."""
        event_type = event.get("type")
        if event_type == "datalog_auto_ingested":
            log_name = event.get("log_name", "datalog")
            log_path = event.get("path")
            scorecard = event.get("scorecard")

            # 1. Sync fresh 16x16 VE Table to disk for Ctrl+V
            try:
                tsv = ve_optimizer.export_holley_tsv(include_learn=True)
                for export_target in [Path("."), Path("G:/My Drive/Holley")]:
                    if export_target.exists():
                        (export_target / "COPY 16x16 VE TABLE (CTRL+V)").write_text(tsv, encoding="utf-8")
                        (export_target / "COPY 16x16 VE TABLE (CTRL+V).txt").write_text(tsv, encoding="utf-8")
            except Exception as e:
                logger.debug("Auto-export clipboard file error: %s", e)

            # 2. Trigger automated Gemini run evaluation
            gemini_answer = None
            try:
                prompt = (
                    f"AUTOMATED POST-PULL AUDIT: A new Holley datalog '{log_name}' was just saved by the tuner.\n"
                )
                if scorecard:
                    prompt += (
                        f"• Peak Boost: {scorecard.get('peak_boost_psi', 0):.1f} PSI @ {scorecard.get('peak_rpm', 0):.0f} RPM\n"
                        f"• Average AFR: {scorecard.get('avg_afr', 0):.2f} vs Target {scorecard.get('avg_target_afr', 0):.2f} (Error: {scorecard.get('afr_error', 0):+.2f})\n"
                        f"• Minimum Fuel Pressure: {scorecard.get('min_fuel_psi', 0):.1f} PSI (effective rail differential: {scorecard.get('min_delta_psi', 0):.1f} PSI vs 58 PSI target)\n"
                        f"• Max Injector Duty Cycle: {scorecard.get('max_duty_pct', 0):.1f}%\n"
                    )
                prompt += (
                    "Audit this run: confirm if 1:1 boost-referenced fuel pressure held safe, "
                    "summarize wideband tracking, and give 2-3 specific tuning takeaways for the next pass."
                )
                gemini_res = await gemini_agent.ask(
                    question=prompt,
                    datalog_path=log_path,
                )
                gemini_answer = gemini_res.get("answer")
            except Exception as e:
                logger.warning("Auto Gemini evaluation error: %s", e)

            # 3. Broadcast to all open WebSocket clients
            matrix_payload = ve_optimizer.get_matrix_payload(include_learn=True)
            matrix_payload["scorecards"] = pull_detector.recent_scorecards
            auto_msg = json.dumps({
                "type": "auto_pull_analyzed",
                "log_name": log_name,
                "scorecard": scorecard,
                "gemini_answer": gemini_answer,
                "matrix": matrix_payload,
                "timestamp": time.time(),
            })
            for ws in list(broadcaster.connections):
                try:
                    await ws.send_text(auto_msg)
                except Exception:
                    pass

        elif event_type == "tune_auto_detected":
            tune_name = event.get("tune_name", "tune")
            tune_path = event.get("path")
            gemini_answer = None
            try:
                prompt = (
                    f"AUTOMATED CALIBRATION AUDIT: A Holley tune file '{tune_name}' was just updated or loaded.\n"
                    f"Audit this calibration against the 1980 Fairmont Turbo LS build: 58 PSI base mechanical rail (1:1 boost ref), "
                    f"Siemens Deka 80s, 4L80E transbrake staging (3000-3200 RPM @ 0-5° BTDC), and standard boost limit of 15-17 PSI. "
                    f"Highlight any critical safety settings or table limits the tuner should verify."
                )
                gemini_res = await gemini_agent.ask(question=prompt)
                gemini_answer = gemini_res.get("answer")
            except Exception as e:
                logger.debug("Tune auto-audit error: %s", e)

            auto_msg = json.dumps({
                "type": "auto_tune_detected",
                "tune_name": tune_name,
                "path": tune_path,
                "gemini_answer": gemini_answer,
                "timestamp": time.time(),
            })
            for ws in list(broadcaster.connections):
                try:
                    await ws.send_text(auto_msg)
                except Exception:
                    pass

    handoff_watcher = AutoHandoffWatcher(
        listener=listener,
        ve_optimizer=ve_optimizer,
        pull_detector=pull_detector,
        on_event_callback=_on_auto_event,
    )
    _last_opt_sample_ts = 0.0

    async def _on_optimizer_frame(frame: DecodedFrame) -> None:
        nonlocal _last_opt_sample_ts
        now = time.time()
        # Sample into VE optimizer and Post-Pull detector at ~10 Hz when RPM arrives
        if frame.name == "rpm" and (now - _last_opt_sample_ts) >= 0.1:
            _last_opt_sample_ts = now
            snap_raw = listener.get_live_snapshot()
            flat = {k: float(v.get("value", 0.0)) for k, v in snap_raw.items() if isinstance(v, dict)}
            if flat.get("rpm", 0.0) > 400.0:
                ve_optimizer.last_source = f"Live ({listener.interface})"
                ve_optimizer.ingest_row(flat)
                scorecard = pull_detector.on_snapshot(flat)
                if scorecard:
                    broadcaster._pending_alerts.append({
                        "severity": scorecard["severity"],
                        "alert_type": "post_pull_scorecard",
                        "channel": "rpm",
                        "message": f"🏁 {scorecard['verdict']}",
                        "value": scorecard["peak_rpm"],
                        "threshold": 0.0,
                        "timestamp": scorecard["timestamp"],
                    })

    listener.subscribe(_on_optimizer_frame)

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI):
        await storage.initialize()
        if not getattr(listener, "_running", False):
            try:
                await listener.start()
            except Exception as e:
                logger.warning(
                    "Could not auto-start CAN listener on boot: %s. Auto-Handoff Watcher active.", e
                )
        await handoff_watcher.start()

        # Start periodic WebSocket heartbeat task (1 Hz) to prevent watchdog timeout on idle bus
        async def _heartbeat_loop():
            while True:
                try:
                    await asyncio.sleep(1.0)
                    if broadcaster.connections:
                        hb_msg = json.dumps({
                            "type": "heartbeat",
                            "stats": listener.stats,
                            "ecu_serial": listener.ecu_serial,
                            "timestamp": time.time(),
                        })
                        dead = []
                        for ws in list(broadcaster.connections):
                            try:
                                await ws.send_text(hb_msg)
                            except Exception:
                                dead.append(ws)
                        for ws in dead:
                            broadcaster.disconnect(ws)
                except asyncio.CancelledError:
                    break
                except Exception as hb_err:
                    logger.debug("Heartbeat error: %s", hb_err)

        heartbeat_task = asyncio.create_task(_heartbeat_loop())
        yield
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        await handoff_watcher.stop()
        if getattr(listener, "_running", False):
            try:
                await listener.stop()
            except Exception:
                pass

    app = FastAPI(
        title="Holley CAN Agent",
        description="Agentic ECU monitoring interface for the Holley Terminator X Max",
        version="0.1.0",
        lifespan=lifespan,
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

    # ── Hardware Diagnostics & Transceiver API ──────────────────────────

    @app.get("/api/hardware/status")
    async def get_hardware_status():
        """Returns live hardware transceiver state, error frames, and discovery status."""
        lock_info = {"locked": False, "processes": []}
        try:
            from app.hardware.detection import check_holley_software_lock
            lock_info = check_holley_software_lock()
        except Exception:
            pass
        return {
            "interface": getattr(listener, "interface", "unknown"),
            "channel": getattr(listener, "channel", "unknown"),
            "bitrate": getattr(listener, "bitrate", 1_000_000),
            "is_running": getattr(listener, "_running", False),
            "ecu_serial": listener.ecu_serial,
            "winusb_lock": lock_info,
            "stats": listener.stats,
        }

    @app.get("/api/hardware/adapters")
    async def get_hardware_adapters():
        """Scans the host system for physical and virtual CAN hardware interfaces."""
        try:
            from app.hardware.detection import discover_available_adapters
            detected = discover_available_adapters()
        except Exception as e:
            detected = [{"adapter_type": "unknown", "name": f"Scan error: {e}", "available": False}]

        return {
            "current_interface": getattr(listener, "interface", "unknown"),
            "current_channel": getattr(listener, "channel", "unknown"),
            "bitrate": getattr(listener, "bitrate", 1_000_000),
            "is_running": getattr(listener, "_running", False),
            "adapters": detected,
        }

    @app.post("/api/hardware/reconnect")
    async def reconnect_hardware(payload: Optional[dict] = None):
        """Probes, restarts, or dynamically switches the CAN hardware listener."""
        try:
            target_iface = None
            target_chan = None
            if payload and isinstance(payload, dict):
                target_iface = payload.get("adapter_type") or payload.get("interface")
                target_chan = payload.get("channel")

            # Fallback auto-selection: on Windows, if interface is socketcan or empty, switch to holley
            if not target_iface:
                current_iface = getattr(listener, "interface", "")
                if sys.platform == "win32" and current_iface in ("socketcan", "unknown", ""):
                    target_iface = "holley"
                    target_chan = "HOLLEY_USBCAN_0"
                else:
                    target_iface = current_iface or ("holley" if sys.platform == "win32" else "socketcan")
                    target_chan = getattr(listener, "channel", "HOLLEY_USBCAN_0" if sys.platform == "win32" else "can0")

            if not target_chan:
                target_chan = "HOLLEY_USBCAN_0" if target_iface in ("holley", "holley_usbcan") else "can0"

            if hasattr(listener, "switch_interface"):
                await listener.switch_interface(target_iface, target_chan, getattr(listener, "bitrate", 1_000_000))
            else:
                await listener.stop()
                listener.interface = target_iface
                listener.channel = target_chan
                await listener.start()

            return {
                "status": "success",
                "message": f"Hardware transceiver active on {listener.interface} ({listener.channel}).",
                "interface": listener.interface,
                "channel": listener.channel,
                "stats": listener.stats,
            }
        except Exception as e:
            err_msg = str(e)
            try:
                from app.hardware.detection import check_holley_software_lock
                lock_info = check_holley_software_lock()
                if lock_info["locked"]:
                    err_msg = f"{err_msg} — {lock_info['hint']}"
            except Exception:
                pass
            logger.error("Hardware reconnect error: %s", err_msg)
            return {"status": "error", "message": err_msg}

    # ── Offline .DL / .DLZ Binary Datalog Discovery & Analysis API ──────

    @app.get("/api/datalogs/discover")
    async def discover_datalogs():
        """Scans Documents/Holley for local .dl, .dlz, and .terx files."""
        from .dl_parser import discover_local_holley_files
        return discover_local_holley_files()

    @app.post("/api/datalogs/analyze")
    async def analyze_datalog_endpoint(payload: Optional[dict] = None):
        """
        Parses a Holley .dl or .dlz binary datalog, returns min/max/avg + WOT summary,
        and optionally injects its peak-RPM telemetry snapshot into the live dashboard.
        """
        from .dl_parser import HolleyDatalogParser, discover_local_holley_files

        file_path = (payload or {}).get("path")
        inject_to_live = (payload or {}).get("inject_to_live", True)
        row_index = int((payload or {}).get("row_index", -1))

        if not file_path:
            found = discover_local_holley_files()
            if not found["datalogs"]:
                return {"status": "error", "message": "No .dl or .dlz files found on disk."}
            file_path = found["datalogs"][0]["path"]

        try:
            parser = HolleyDatalogParser(file_path)
            summary = parser.summarize()
            ve_optimizer.ingest_datalog(file_path)
            if inject_to_live and hasattr(listener, "inject_decoded_frames"):
                frames = parser.to_decoded_frames(row_index=row_index)
                await listener.inject_decoded_frames(frames)
                summary["injected_channels"] = len(frames)
            return {"status": "success", "summary": summary}
        except Exception as e:
            logger.error("Datalog analysis failed for %s: %s", file_path, e)
            return {"status": "error", "message": str(e)}

    # ── AI Tune Optimizer (16x16 VE Matrix + Ctrl+V TSV + Post-Pull) ────

    @app.get("/api/optimizer/matrix")
    async def get_optimizer_matrix(include_learn: bool = Query(True, description="Whether to fold Fuel Learn % into Base VE recommendations")):
        """Returns the 16x16 VE Hit & Correction Matrix, Holley TSV clipboard string, and Post-Pull scorecards."""
        payload = ve_optimizer.get_matrix_payload(include_learn=include_learn)
        payload["handoff_mode"] = handoff_watcher.handoff_mode
        payload["last_auto_ingested_log"] = handoff_watcher.last_auto_ingested_log
        payload["scorecards"] = pull_detector.recent_scorecards
        return payload

    @app.post("/api/optimizer/ingest_datalog")
    async def optimizer_ingest_datalog(payload: Optional[dict] = None):
        """Loads a .dl or .dlz datalog (or latest log in Documents/Holley) into the 16x16 VE Optimizer."""
        from .dl_parser import discover_local_holley_files

        file_path = (payload or {}).get("path")
        if not file_path:
            found = discover_local_holley_files()
            if not found["datalogs"]:
                return {"status": "error", "message": "No .dl or .dlz datalog files found in Documents/Holley."}
            file_path = found["datalogs"][0]["path"]

        try:
            handoff_watcher._ingest_file(file_path)
            parser = HolleyDatalogParser(file_path)
            if hasattr(listener, "inject_decoded_frames"):
                await listener.inject_decoded_frames(parser.to_decoded_frames())
            matrix = ve_optimizer.get_matrix_payload()
            matrix["handoff_mode"] = handoff_watcher.handoff_mode
            matrix["scorecards"] = pull_detector.recent_scorecards
            return {"status": "success", "matrix": matrix}
        except Exception as e:
            logger.error("Optimizer datalog ingest error: %s", e)
            return {"status": "error", "message": str(e)}

    @app.post("/api/datalog/upload")
    async def upload_datalog(file: UploadFile = File(...)):
        """Uploads and analyzes a Holley .dl / .dlz datalog directly from the browser."""
        import os
        upload_dir = Path("./data/uploads")
        upload_dir.mkdir(parents=True, exist_ok=True)
        dest_path = upload_dir / file.filename
        content = await file.read()
        with open(dest_path, "wb") as f:
            f.write(content)

        try:
            from .dl_parser import HolleyDatalogParser
            parser = HolleyDatalogParser(str(dest_path))
            summary = parser.summarize()
            handoff_watcher._ingest_file(str(dest_path))
            matrix = ve_optimizer.get_matrix_payload()
            matrix["scorecards"] = pull_detector.recent_scorecards
            return {
                "status": "success",
                "filename": file.filename,
                "path": str(dest_path),
                "summary": summary,
                "matrix": matrix,
            }
        except Exception as e:
            logger.error("Failed to process uploaded datalog: %s", e)
            return {"status": "error", "message": str(e)}

    @app.post("/api/optimizer/reset")
    async def optimizer_reset():
        """Resets the 16x16 VE accumulator cells for a fresh tuning pass."""
        ve_optimizer.reset()
        pull_detector.recent_scorecards.clear()
        return {"status": "success", "matrix": ve_optimizer.get_matrix_payload()}

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

    # ── AI Copilot ("Ask Your Engine" powered by Gemini 2.5) ─────────────

    @app.post("/api/copilot/ask")
    async def copilot_ask(payload: dict):
        """Processes conversational queries using Gemini 2.5 with grounded EFI tools."""
        question = payload.get("question", "").strip()
        if not question:
            return {"error": "Question cannot be empty."}

        api_key = payload.get("api_key")
        if api_key:
            gemini_agent.set_api_key(api_key)

        snapshot = listener.get_live_snapshot()
        active_alerts = alert_engine.get_active_alerts() if alert_engine else []
        datalog_path = payload.get("datalog_path")

        return await gemini_agent.ask(
            question=question,
            live_snapshot=snapshot,
            active_alerts=active_alerts,
            datalog_path=datalog_path,
        )

    @app.post("/api/copilot/set_key")
    async def copilot_set_key(payload: dict):
        """Dynamically sets or updates the Gemini API key."""
        api_key = payload.get("api_key", "").strip()
        success = gemini_agent.set_api_key(api_key)
        return {
            "status": "success" if success else "error",
            "gemini_active": gemini_agent.is_gemini_active,
            "model": gemini_agent.model_name,
        }

    @app.get("/api/copilot/status")
    async def copilot_status():
        """Returns current Gemini AI status and model."""
        return {
            "gemini_active": gemini_agent.is_gemini_active,
            "model": gemini_agent.model_name,
            "genai_installed": GENAI_AVAILABLE,
            "has_api_key": bool(gemini_agent._api_key),
        }

    @app.get("/api/copilot/suggestions")
    async def copilot_suggestions():
        """Returns recommended questions for quick chip prompts."""
        return {
            "suggestions": [
                "Audit my fuel pressure: is it rising 1:1 with boost to 58 PSI base?",
                "Analyze my last WOT datalog pull and check AFR safety margin",
                "Generate a 16x16 VE table correction with learn trims folded in",
                "Why is my idle hunting or surging around 900 RPM?",
                "Check transbrake staging stability (3000-3200 RPM @ 0-5° BTDC)",
                "Did the 4L80E converter slip excessively under boost?",
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
