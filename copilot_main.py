"""
copilot_main.py — CLI and service runner for EFI Intelligence Copilot.

Supports running with physical hardware or the deterministic virtual simulator,
executing real-time baseline learning, deterministic event detection,
and automated intelligence report generation.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import time
from pathlib import Path

from app.baseline.engine import BaselineEngine
from app.diagnostics.engine import DiagnosticEngine
from app.events.detector import EventDetector
from app.hardware.simulator import SimulationScenario, VirtualSimulatorAdapter
from app.hardware.socketcan import SocketCanAdapter
from app.hardware.usb_can import UsbCanAdapter
from app.protocol.hefi import HefiProtocolDecoder
from app.reports.generator import ReportGenerator
from app.sessions.manager import SessionManager
from app.sessions.metadata import SessionType
from app.storage.database import Database
from app.storage.repository import TelemetryRepository
from app.telemetry.sample import NormalizedTelemetrySample
from app.vehicle.history import ModificationTimeline
from app.vehicle.profile import VehicleProfile

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)-22s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("efi-copilot")


async def run_copilot(
    use_simulator: bool = True,
    scenario_name: str = "multi_cycle",
    duration_s: float = 10.0,
    db_path: str = "./data/copilot_sessions.db",
    vehicle_name: str = "Holley Terminator X MAX Vehicle",
) -> None:
    """Orchestrates an EFI Intelligence Copilot recording and analytical run."""
    logger.info("Initializing EFI Intelligence Copilot...")

    # 1. Initialize Storage & Sessions
    db = Database(db_path)
    repo = TelemetryRepository(db)
    session_mgr = SessionManager(repo, buffer_size=20)

    # 2. Initialize Vehicle Profile & Timeline
    profile = VehicleProfile(name=vehicle_name, engine_name="6.0L V8")
    timeline = ModificationTimeline(profile.vehicle_id)
    timeline.add_entry("2026-08-15", "camshaft", "Stage 2 Camshaft")

    # 3. Initialize Analytical Engines
    decoder = HefiProtocolDecoder()
    baseline_engine = BaselineEngine(profile.vehicle_id)
    detector = EventDetector()
    diag_engine = DiagnosticEngine(baseline_engine)
    report_gen = ReportGenerator(profile)

    # 4. Initialize Hardware Interface
    if use_simulator:
        scenario = SimulationScenario(scenario_name)
        logger.info("Using VirtualSimulatorAdapter with scenario: %s", scenario.value)
        adapter = VirtualSimulatorAdapter(scenario=scenario, broadcast_hz=20.0)
    else:
        logger.info("Using UsbCanAdapter (passive listen-only mode)...")
        adapter = UsbCanAdapter(channel="PCAN_USBBUS1")

    connected = await adapter.connect()
    if not connected:
        logger.error("Failed to connect to hardware transport.")
        return

    # Start Session
    session_meta = session_mgr.start_session(
        vehicle_id=profile.vehicle_id,
        session_type=SessionType.STREET_DRIVE,
        driver_notes=f"Run with scenario {scenario_name}",
    )
    logger.info("Session started: %s", session_meta.session_id)

    recorded_samples: list[NormalizedTelemetrySample] = []
    detected_events = []

    # Current sample aggregation state
    current_sample = NormalizedTelemetrySample(timestamp=time.time())

    start_time = time.time()
    try:
        while time.time() - start_time < duration_s:
            frame = await adapter.receive(timeout=0.1)
            if frame is None:
                continue

            # Decode CAN frame into signals
            signals = decoder.decode(frame)
            for sig in signals:
                current_sample.signals[sig.signal_name] = sig
                if sig.signal_name == "engine_rpm":
                    current_sample.engine_rpm = sig.value
                elif sig.signal_name == "map_kpa":
                    current_sample.map_kpa = sig.value
                elif sig.signal_name == "baro_kpa":
                    current_sample.baro_kpa = sig.value
                elif sig.signal_name == "tps":
                    current_sample.tps = sig.value
                elif sig.signal_name == "coolant_temp":
                    current_sample.coolant_temp = sig.value
                elif sig.signal_name == "target_afr":
                    current_sample.target_afr = sig.value
                elif sig.signal_name == "afr_measured":
                    current_sample.afr_measured = sig.value
                elif sig.signal_name == "fuel_learn":
                    current_sample.fuel_learn = sig.value
                elif sig.signal_name == "battery_voltage":
                    current_sample.battery_voltage = sig.value

            # When RPM frame arrives, commit sample slice
            if any(s.signal_name == "engine_rpm" for s in signals):
                current_sample.timestamp = frame.timestamp
                current_sample.compute_derived_metrics()
                current_sample.calculate_quality_score()

                session_mgr.record_sample(current_sample)
                baseline_engine.ingest_sample(current_sample)
                evts = detector.feed_sample(current_sample)
                if evts:
                    detected_events.extend(evts)
                    for ev in evts:
                        logger.info("⚡ EVENT DETECTED: %s (%s) — %s", ev.event_type.value, ev.severity.value, ev.evidence)

                recorded_samples.append(current_sample)
                current_sample = NormalizedTelemetrySample(timestamp=time.time())

    except asyncio.CancelledError:
        pass
    finally:
        await adapter.disconnect()
        flushed_events = detector.flush(time.time())
        detected_events.extend(flushed_events)
        closed_session = session_mgr.end_session()

    logger.info("Session %s ended. Total samples: %d", closed_session.session_id, len(recorded_samples))

    # 5. Run Rule-Based Diagnostics
    diagnostics = diag_engine.evaluate_session(recorded_samples, detected_events)
    logger.info("Diagnostic evaluation complete. Findings: %d", len(diagnostics))

    # 6. Generate Intelligence Report
    report_md = report_gen.generate_markdown(closed_session, diagnostics)
    report_path = Path("./data") / f"report_{closed_session.session_id}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    logger.info("Saved intelligence report to: %s", report_path)
    print("\n" + "=" * 70)
    print(report_md)
    print("=" * 70 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="EFI Intelligence Copilot")
    parser.add_argument("--simulator", action="store_true", default=True, help="Use virtual simulator")
    parser.add_argument("--scenario", type=str, default="wot_pull_lean_dev", help="Simulator scenario name")
    parser.add_argument("--duration", type=float, default=6.0, help="Run duration in seconds")
    parser.add_argument("--db", type=str, default="./data/copilot_sessions.db", help="SQLite database path")
    args = parser.parse_args()

    asyncio.run(
        run_copilot(
            use_simulator=args.simulator,
            scenario_name=args.scenario,
            duration_s=args.duration,
            db_path=args.db,
        )
    )


if __name__ == "__main__":
    main()
