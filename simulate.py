"""
simulate.py — Simulation environment for Holley CAN Agent.

Launches the FastAPI server and dashboard configured for a virtual CAN bus,
while running a background task that generates realistic ECU telemetry
including revs, shifts, WOT pulls, boost, and occasional alert conditions.
"""

from __future__ import annotations

import asyncio
import logging
import math
import signal
import sys
import struct
import random
import time
from pathlib import Path

import uvicorn
import yaml
import can

from holley_can.agent_api import DashboardBroadcaster, create_app
from holley_can.alerts import AlertConfig, AlertEngine
from holley_can.listener import CANListener
from holley_can.storage import TimeSeriesStorage

# ─── Logging Setup ───────────────────────────────────────────────────────────

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)-24s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("holley-can-simulator")

# ─── Telemetry Helper Functions ──────────────────────────────────────────────

def make_hefi_can_id(channel_index: int, ecu_serial: int = 0x1A5) -> int:
    """Construct a 29-bit HEFI CAN ID."""
    can_id = 0
    can_id |= (1 << 28)                         # Command bit
    can_id |= (0b111 << 25)                     # Broadcast target
    can_id |= ((channel_index & 0x7FF) << 14)   # Channel index
    can_id |= (0b010 << 11)                     # ECU source
    can_id |= (ecu_serial & 0x7FF)              # Serial
    return can_id

def make_payload(value_a: float, value_b: float = 0.0) -> bytes:
    """Create an 8-byte big-endian IEEE 754 payload."""
    return struct.pack(">ff", value_a, value_b)

# ─── Simulated Telemetry Loop ────────────────────────────────────────────────

async def send_simulated_telemetry(channel: str = "sim_channel"):
    """Generates realistic Terminator X Max telemetry at 10 Hz."""
    logger.info("Starting simulated ECU telemetry generator on virtual channel '%s'...", channel)
    
    # Wait for the listener to open the bus
    await asyncio.sleep(1.0)
    
    try:
        bus = can.Bus(interface="virtual", channel=channel)
    except Exception as e:
        logger.error("Simulator failed to open virtual CAN bus: %s", e)
        return

    ecu_serial = 0x1A5
    t = 0.0
    
    # ECU State Variables
    rpm = 850.0
    tps = 0.0
    map_kpa = 35.0
    coolant = 140.0
    battery = 13.8
    gear = 0
    trans_temp = 120.0
    
    cycle_duration = 35.0  # seconds per cycle

    try:
        while True:
            cycle_time = t % cycle_duration
            
            # ── State Machine ────────────────────────────────────────
            if cycle_time < 5.0:
                # 1. Warm-up / Idle
                target_rpm = 850.0 + random.uniform(-10, 10)
                tps = 0.0
                target_map = 35.0 + random.uniform(-1, 1)
                gear = 0  # Neutral
                
            elif cycle_time < 15.0:
                # 2. Moderate Driving (Accelerating & Shifting)
                accel_t = cycle_time - 5.0
                tps = 25.0 + math.sin(accel_t) * 5.0
                
                # Shifting gears based on time
                if accel_t < 3.0:
                    gear = 1
                    target_rpm = 1200.0 + (accel_t * 600.0)
                elif accel_t < 6.0:
                    gear = 2
                    target_rpm = 1500.0 + ((accel_t - 3.0) * 500.0)
                else:
                    gear = 3
                    target_rpm = 1600.0 + ((accel_t - 6.0) * 400.0)
                    
                target_map = 60.0 + random.uniform(-3, 3)
                
            elif cycle_time < 22.0:
                # 3. Wide Open Throttle (WOT) Drag Pull!
                wot_t = cycle_time - 15.0
                tps = 100.0
                
                if wot_t < 3.0:
                    gear = 3
                    target_rpm = 3200.0 + (wot_t * 900.0)
                    target_map = 180.0 + (wot_t * 15.0)  # Moderate boost
                else:
                    gear = 4
                    target_rpm = 4000.0 + ((wot_t - 3.0) * 700.0)
                    target_map = 220.0 + ((wot_t - 3.0) * 10.0)  # Higher boost
                    
                # ── Trigger simulated overboost alert (around t = 20s)
                if 20.0 <= cycle_time <= 21.5:
                    target_map = 265.0  # Threshold is 250 kPa
                    
            elif cycle_time < 27.0:
                # 4. Deceleration / High Vacuum
                decel_t = cycle_time - 22.0
                tps = 0.0
                gear = 4
                target_rpm = 3000.0 - (decel_t * 400.0)
                target_map = 18.0 + random.uniform(-1, 1)  # Decel vacuum
                
            else:
                # 5. Return to Idle
                target_rpm = 850.0
                tps = 0.0
                target_map = 35.0
                gear = 0
            
            # Smooth interpolation of mechanical parameters
            rpm = (0.75 * rpm) + (0.25 * target_rpm)
            map_kpa = (0.8 * map_kpa) + (0.2 * target_map)
            
            # Coolant temp slowly rises to operating temp (190°F) and stays there
            if coolant < 190.0:
                coolant += 0.08
            else:
                coolant = 190.0 + random.uniform(-1, 1)
                
            # Trans temp behaves similarly
            if trans_temp < 155.0:
                trans_temp += 0.05
            else:
                trans_temp = 155.0 + random.uniform(-0.5, 0.5)

            # Battery voltage behavior (slightly drops under high electric load,
            # or triggers an alert towards the end of the idle cycle)
            if 31.0 <= cycle_time <= 33.0:
                battery = 12.4  # Trigger low battery alert (< 13.0 V)
            else:
                battery = 13.9 + random.uniform(-0.1, 0.1)

            # Target AFR based on MAP/power enrichment
            if tps > 80.0:
                target_afr = 11.5  # Rich under boost
            elif map_kpa > 95.0:
                target_afr = 12.8
            else:
                target_afr = 14.7  # Stoich

            # AFR average follows target with delay
            # ── Trigger simulated Lean AFR alert during WOT (around t = 18s)
            if 17.5 <= cycle_time <= 19.5:
                afr_avg = target_afr + 0.95  # Significantly lean
            else:
                afr_avg = target_afr + random.uniform(-0.12, 0.12)

            # Spark Advance (Ignition Timing)
            if tps > 80.0:
                # Retard timing under boost to prevent knock
                timing = 24.0 - (map_kpa - 100.0) * 0.06
                # ── Trigger simulated Timing Retard / Knock alert (around t = 19s)
                if 18.5 <= cycle_time <= 20.0:
                    timing -= 5.0  # Timing retard alert
            else:
                timing = 16.0 + (rpm / 600.0) + (100.0 - map_kpa) * 0.12

            timing = max(-10.0, min(45.0, timing))
            
            # Oil Pressure
            oil_pressure = 20.0 + (rpm / 8000.0) * 55.0 + random.uniform(-1, 1)
            
            # Construct frame definitions (channel_index, val_a, val_b)
            frames = [
                (1, rpm, 0.0),                  # RPM
                (2, map_kpa, 101.3),            # MAP / Baro
                (3, tps, 0.0),                  # TPS
                (4, coolant, 0.0),              # Coolant temp
                (5, target_afr, 0.0),           # Target AFR
                (8, afr_avg, 0.0),              # Avg AFR
                (11, timing, 0.0),              # Ignition Timing
                (12, battery, 0.0),             # Battery Voltage
                (13, -1.8, 0.0),                # Current Fuel Learn
                (15, 88.0, 0.0),                # IAT
                (20, gear, 0.0),                # Current Gear
                (21, trans_temp, 0.0),          # Trans Temp
                (22, 100.0 if gear == 4 else 0.0, 0.0), # TCC status (locked in 4th)
                (30, oil_pressure, 0.0),        # Oil Pressure
            ]
            
            # Broadcast frames on virtual CAN bus
            for ch_idx, val_a, val_b in frames:
                can_id = make_hefi_can_id(ch_idx, ecu_serial)
                payload = make_payload(val_a, val_b)
                msg = can.Message(
                    arbitration_id=can_id,
                    data=payload,
                    is_extended_id=True
                )
                try:
                    bus.send(msg)
                except Exception as e:
                    logger.debug("Failed to send message on virtual bus: %s", e)
            
            t += 0.1
            await asyncio.sleep(0.1)
            
    except asyncio.CancelledError:
        logger.info("Simulated telemetry generator stopped.")
    finally:
        bus.shutdown()

# ─── Main ────────────────────────────────────────────────────────────────────

import math

async def main():
    # Load base configuration to customize
    config_path = Path("config.yaml")
    if config_path.exists():
        with open(config_path, "r") as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}
        
    # Override for simulation
    can_cfg = {
        "interface": "virtual",
        "channel": "sim_channel",
        "bitrate": 1_000_000,
        "receive_own_messages": False,
    }
    storage_cfg = {
        "database": "./data/holley_can_sim.db",
        "sample_rate_hz": 1.0,
        "retention_days": 1,
        "wal_mode": True,
    }
    alert_cfg = config.get("alerts", {})
    api_cfg = config.get("api", {})
    dash_cfg = config.get("dashboard", {})

    logger.info("═══════════════════════════════════════════════════")
    logger.info("  Holley CAN Agent — Terminator X Max SIMULATOR")
    logger.info("═══════════════════════════════════════════════════")

    # ── Initialize components ────────────────────────────────────────

    # CAN Listener
    listener = CANListener(
        interface=can_cfg.get("interface"),
        channel=can_cfg.get("channel"),
        bitrate=can_cfg.get("bitrate"),
        receive_own_messages=can_cfg.get("receive_own_messages"),
    )

    # Storage
    storage = TimeSeriesStorage(
        db_path=storage_cfg.get("database"),
        sample_rate_hz=storage_cfg.get("sample_rate_hz"),
        retention_days=storage_cfg.get("retention_days"),
        wal_mode=storage_cfg.get("wal_mode"),
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

    listener.subscribe(storage.on_frame)
    listener.subscribe(alert_engine.on_frame)
    listener.subscribe(broadcaster.on_frame)

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
        while True:
            await asyncio.sleep(1.0)
            await alert_engine.check_dropouts()

    periodic_task = asyncio.create_task(periodic_tasks())

    # ── Create FastAPI app ───────────────────────────────────────────

    app = create_app(
        listener=listener,
        storage=storage,
        broadcaster=broadcaster,
        cors_origins=api_cfg.get("cors_origins", ["*"]),
    )

    # ── Start Uvicorn ────────────────────────────────────────────────

    host = api_cfg.get("host", "127.0.0.1")  # local only for simulation
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
            pass  # Windows doesn't support add_signal_handler

    # Start simulation telemetry generator in the background
    telemetry_task = asyncio.create_task(send_simulated_telemetry(can_cfg["channel"]))

    # Run server
    try:
        await server.serve()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        logger.info("Shutting down simulator...")
        telemetry_task.cancel()
        periodic_task.cancel()
        await listener.stop()
        await storage.close()
        logger.info("Simulator offline. Goodbye.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
