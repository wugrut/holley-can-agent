"""
main.py — Entry point for the Holley CAN Agent.

Initializes the CAN listener, storage, alert engine, and FastAPI server,
wiring them all together via the subscriber pattern. Runs headlessly
on the GMKtec EVO-X2.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

import uvicorn
import yaml

from holley_can.agent_api import DashboardBroadcaster, create_app
from holley_can.alerts import AlertConfig, AlertEngine
from holley_can.listener import CANListener
from holley_can.storage import TimeSeriesStorage

# ─── Logging Setup ───────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)-24s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("holley-can-agent")


# ─── Configuration ───────────────────────────────────────────────────────────

def load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file."""
    path = Path(config_path)
    if not path.exists():
        logger.warning("Config file not found at %s, using defaults", config_path)
        return {}

    with open(path, "r") as f:
        config = yaml.safe_load(f) or {}

    logger.info("Configuration loaded from %s", config_path)
    return config


# ─── Main ────────────────────────────────────────────────────────────────────

async def main():
    # Load config
    config = load_config()
    can_cfg = config.get("can", {})
    storage_cfg = config.get("storage", {})
    alert_cfg = config.get("alerts", {})
    api_cfg = config.get("api", {})
    dash_cfg = config.get("dashboard", {})

    logger.info("═══════════════════════════════════════════════════")
    logger.info("  Holley CAN Agent — Terminator X Max Interface")
    logger.info("═══════════════════════════════════════════════════")

    # ── Initialize components ────────────────────────────────────────

    # CAN Listener
    listener = CANListener(
        interface=can_cfg.get("interface", "socketcan"),
        channel=can_cfg.get("channel", "can0"),
        bitrate=can_cfg.get("bitrate", 1_000_000),
        receive_own_messages=can_cfg.get("receive_own_messages", False),
    )

    # Storage
    storage = TimeSeriesStorage(
        db_path=storage_cfg.get("database", "./data/holley_can.db"),
        sample_rate_hz=storage_cfg.get("sample_rate_hz", 1.0),
        retention_days=storage_cfg.get("retention_days", 90),
        wal_mode=storage_cfg.get("wal_mode", True),
    )

    # Alert Engine
    alert_config = AlertConfig(
        enabled=alert_cfg.get("enabled", True),
        lean_afr_offset=alert_cfg.get("lean_afr_offset", 0.5),
        rich_afr_offset=alert_cfg.get("rich_afr_offset", 1.0),
        timing_retard_deg=alert_cfg.get("timing_retard_deg", 3.0),
        overboost_map_kpa=alert_cfg.get("overboost_map_kpa", 250.0),
        low_voltage_v=alert_cfg.get("low_voltage_v", 13.0),
        sensor_dropout_s=alert_cfg.get("sensor_dropout_s", 1.0),
        can_error_rate_pct=alert_cfg.get("can_error_rate_pct", 1.0),
    )
    alert_engine = AlertEngine(config=alert_config)

    # Dashboard Broadcaster
    broadcaster = DashboardBroadcaster(
        update_rate_ms=dash_cfg.get("update_rate_ms", 50),
    )

    # ── Wire up subscribers ──────────────────────────────────────────

    # Every decoded frame goes to: storage, alerts, and dashboard broadcast
    listener.subscribe(storage.on_frame)
    listener.subscribe(alert_engine.on_frame)
    listener.subscribe(broadcaster.on_frame)

    # Alerts go to: storage log and dashboard broadcast
    alert_engine.on_alert(
        lambda alert: storage.log_alert(
            severity=alert.severity.value,
            alert_type=alert.alert_type,
            channel=alert.channel,
            message=alert.message,
            value=alert.value,
            threshold=alert.threshold,
        )
    )
    alert_engine.on_alert(broadcaster.on_alert)

    # ── Initialize storage ───────────────────────────────────────────

    await storage.initialize()

    # ── Start CAN listener ───────────────────────────────────────────

    await listener.start()

    # ── Periodic tasks ───────────────────────────────────────────────

    async def periodic_tasks():
        """Run periodic maintenance: dropout checks, data cleanup."""
        cleanup_counter = 0
        while True:
            await asyncio.sleep(1.0)
            await alert_engine.check_dropouts()

            # Run data cleanup every hour
            cleanup_counter += 1
            if cleanup_counter >= 3600:
                cleanup_counter = 0
                await storage.cleanup_old_data()

    periodic_task = asyncio.create_task(periodic_tasks())

    # ── Create FastAPI app ───────────────────────────────────────────

    app = create_app(
        listener=listener,
        storage=storage,
        broadcaster=broadcaster,
        cors_origins=api_cfg.get("cors_origins", ["*"]),
    )

    # ── Start Uvicorn ────────────────────────────────────────────────

    host = api_cfg.get("host", "0.0.0.0")
    port = api_cfg.get("port", 8420)

    logger.info("Starting API server on http://%s:%d", host, port)
    logger.info("Dashboard: http://%s:%d/", host, port)

    uv_config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(uv_config)

    # ── Graceful shutdown ────────────────────────────────────────────

    shutdown_event = asyncio.Event()

    def handle_signal(sig):
        logger.info("Received signal %s, shutting down...", sig)
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: handle_signal(s))
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    # Run server
    try:
        await server.serve()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        logger.info("Shutting down...")
        periodic_task.cancel()
        await listener.stop()
        await storage.close()
        logger.info("Goodbye.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
