"""
portable_entry.py — Unified Master Entry Point for EFI Intelligence Copilot.

Designed for standalone execution on Windows tuning laptops (with or without Python installed).
Provides:
  1. copilot   — Live telemetry logging, baseline learning, event detection, and report generation.
  2. preflight — Hardware bus sniffer, bitrate verifier, termination tester, and frame analyzer.
  3. dashboard — Real-time web dashboard & WebSocket server (with auto-launching browser).
  4. simulator — Virtual ECU simulator for offline testing without vehicle hardware.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import time
import webbrowser
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# Force UTF-8 encoding on Windows console to prevent UnicodeEncodeError
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)-22s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("efi-copilot")


# ─── Configuration Loader ───────────────────────────────────────────────────

def get_base_path() -> Path:
    """Returns the root directory of the application (handles PyInstaller bundles)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def load_config(config_path: Optional[str] = None) -> dict:
    """Loads configuration YAML file, falling back to sane defaults."""
    base_dir = get_base_path()
    candidates = []
    if config_path:
        candidates.append(Path(config_path))
    candidates.extend([
        base_dir / "config.yaml",
        base_dir / "config.portable.yaml",
        Path("config.yaml"),
    ])

    for p in candidates:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                logger.info("Loaded configuration from: %s", p)
                return cfg
            except Exception as e:
                logger.warning("Error reading config %s: %s", p, e)

    logger.info("Using default in-memory configuration.")
    return {}


# ─── Mode 1: Preflight Hardware Bus Sniffer ──────────────────────────────────

async def run_preflight(
    interface: str,
    channel: str,
    bitrate: int = 1_000_000,
    sniff_seconds: float = 12.0,
) -> None:
    """
    Non-destructive hardware sniffer to verify CAN bus connectivity, termination,
    baud rate (1 Mbps), and Holley HEFI frame reception before starting a tune or log.
    """
    from app.hardware.detection import discover_available_adapters
    from app.hardware.usb_can import UsbCanAdapter
    from app.protocol.hefi import HefiProtocolDecoder, is_hefi_broadcast

    print("\n" + "═" * 76)
    print("  EFI INTELLIGENCE COPILOT — HARDWARE PREFLIGHT CHECK & BUS SNIFFER")
    print("═" * 76)

    # 1. Discover Adapters
    print("\n[1/3] Scanning Host System for CAN Adapters...")
    adapters = discover_available_adapters()
    for idx, ad in enumerate(adapters, 1):
        rec = " ⭐ [RECOMMENDED]" if ad.get("recommended") else ""
        print(f"   [{idx}] {ad['name']} ({ad['adapter_type']}:{ad['channel']}){rec}")
        print(f"       Description: {ad['description']}")

    # 2. Connect to Specified or Default Adapter
    print(f"\n[2/3] Connecting to Target Interface: {interface} on {channel} at {bitrate:,} bps...")
    print("       (Operating in Passive Listen-Only Mode — zero write transmissions)")

    if interface in ("holley", "holley_usbcan"):
        from app.hardware.holley_usbcan import HolleyUsbCanAdapter
        adapter = HolleyUsbCanAdapter(channel=channel, bitrate=bitrate)
    else:
        adapter = UsbCanAdapter(interface=interface, channel=channel, bitrate=bitrate)

    connected = await adapter.connect()
    if not connected:
        status = adapter.get_status()
        err_msg = status.error_message or "Unknown connection failure"
        print(f"\n❌ FAILED TO CONNECT to {interface} on {channel}!")
        print(f"   Error: {err_msg}")
        print("\n🔧 TROUBLESHOOTING CHECKLIST:")
        if interface in ("holley", "holley_usbcan"):
            print("  1. Cable Check: Verify your Holley USB-to-CAN cable is plugged securely into the laptop.")
            print("  2. Driver Check: Ensure 'Holley USBCAN Driver (WinUSB)' is installed.")
            print("  3. Exclusive Access Check: Close Holley Terminator X / EFI software if it is currently open.")
            print("     (Windows WinUSB does not allow two applications to access the cable simultaneously).")
        else:
            print("  1. Driver check: If using Peak PCAN-USB, install PCAN-Basic driver from PEAK-System.")
            print("  2. COM Port check: If using CANable, check Windows Device Manager -> Ports (COM & LPT).")
            print("     Specify the exact COM port (e.g. --channel COM3).")
            print("  3. Cable check: Ensure USB cable is firmly connected directly to laptop (avoid unpowered hubs).")
        return

    print("   ✓ Connection established. Listening for 29-bit Holley broadcast frames...")
    print(f"   Sniffing bus for {sniff_seconds:.0f} seconds (Press Ctrl+C to stop early)...")

    decoder = HefiProtocolDecoder()
    frame_counts: Dict[int, int] = defaultdict(int)
    channel_samples: Dict[str, float] = {}
    error_frames = 0
    total_frames = 0
    start_time = time.time()

    try:
        while time.time() - start_time < sniff_seconds:
            frame = await adapter.receive(timeout=0.2)
            if frame is None:
                continue

            total_frames += 1
            if frame.is_error_frame:
                error_frames += 1
                continue

            frame_counts[frame.arbitration_id] += 1
            if is_hefi_broadcast(frame.arbitration_id):
                signals = decoder.decode(frame)
                for s in signals:
                    channel_samples[s.signal_name] = s.value

            # Brief live counter
            elapsed = time.time() - start_time
            fps = total_frames / max(0.1, elapsed)
            print(f"\r   ► Sniffing... Frames Received: {total_frames} | Errors: {error_frames} | Rate: {fps:.1f} fps", end="", flush=True)

    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        final_status = adapter.get_status()
        try:
            await adapter.disconnect()
        except Exception:
            pass
        print("\n")

    # 3. Analyze Results & Print Diagnostic Report
    duration = max(0.1, time.time() - start_time)
    print("═" * 76)
    print("  PREFLIGHT BUS DIAGNOSTIC REPORT")
    print("═" * 76)
    print(f"  Interface Tested:       {interface} ({channel})")
    print(f"  Sniff Duration:         {duration:.1f} seconds")
    print(f"  USB Bytes Ingested:     {final_status.bytes_received:,} bytes")
    print(f"  Raw Packets Seen:       {final_status.raw_packets_seen}")
    print(f"  Valid CAN Frames:       {total_frames}")
    print(f"  Malformed Packets:      {final_status.malformed_packets}")
    print(f"  CAN Bus Error Frames:   {error_frames}")
    print(f"  Unique CAN IDs Seen:    {len(frame_counts)}")

    if total_frames == 0:
        if final_status.bytes_received > 0:
            print("\n⚠️ USB STREAM ACTIVITY DETECTED, BUT ZERO VALID CAN FRAMES DECODED")
            print(f"  - USB Stream Ingested: {final_status.bytes_received:,} bytes ({final_status.raw_packets_seen} candidate packets).")
            print(f"  - Malformed/Unparsed:  {final_status.malformed_packets} packets.")
            print("  Action: Enable raw diagnostic mode with 'set HOLLEY_DEBUG_RAW_PACKETS=1' to inspect wire frames.")
        else:
            print("\n🚨 CRITICAL: NO CAN FRAMES DETECTED ON BUS (0 bytes / 0 frames received)")
            print("\nPossible Causes & Action Items:")
            if interface in ("holley", "holley_usbcan"):
                print("  ⭐ NOTE: If your Holley Terminator X software already communicates with the ECU over this cable,")
                print("     your harness wiring, pinout, and bus termination are ALREADY CORRECT. No resistors needed!")
                print("  1. Ignition Switch in RUN: Turn vehicle ignition switch to RUN / ON (ECU needs 12V power).")
                print("  2. Holley CAN Broadcast Disabled:")
                print("     - Open Holley Terminator X Software -> System Setup -> CAN Devices.")
                print("     - Verify 'Enable CAN Broadcast' (or Racepak broadcast at 1 Mbps) is turned ON.")
                print("     - Send updated calibration to ECU, then cycle ignition switch.")
                print("  3. Close Holley Tuning Software:")
                print("     - Windows WinUSB enforces exclusive hardware access by one program at a time.")
                print("     - Make sure Holley Terminator X software is completely closed.")
            else:
                print("  1. Ignition Switch OFF: Turn vehicle ignition switch to RUN / ON (ECU needs 12V power).")
                print("  2. Holley CAN Broadcast Disabled:")
                print("     - Open Holley Terminator X Software -> System Setup -> CAN Devices.")
                print("     - Verify 'Enable CAN Broadcast' (or Racepak broadcast) is turned ON.")
                print("  3. Wiring Pinout Disconnect (Holley 4-pin Metri-Pack connector):")
                print("     - Pin A: Blue (CAN High) -> Connect to CAN-H on adapter")
                print("     - Pin B: White (CAN Low) -> Connect to CAN-L on adapter")
                print("     - Pin C: Red/White (+12V Power) -> DO NOT CONNECT TO DONGLE!")
                print("     - Pin D: Black (Ground / Shield) -> Connect to GND on adapter")
                print("  4. Bus Termination Resistor Missing (Only needed for generic/raw CAN adapters):")
                print("     - Turn vehicle power OFF.")
                print("     - Measure resistance between CAN-H (Pin A) and CAN-L (Pin B) using a multimeter.")
                print("     - Normal Reading: 55Ω to 65Ω (nominally 60Ω from two parallel 120Ω resistors).")
                print("     - If reading is ~120Ω: One terminator is missing. Enable 120Ω jumper on your USB-CAN adapter.")
                print("     - If reading is OPEN / Megaohms: Both terminators missing or wiring broken.")
    elif error_frames > total_frames * 0.1:
        print("\n⚠️ WARNING: HIGH CAN BUS ERROR RATE DETECTED")
        print(f"  Error frames account for {error_frames / total_frames * 100:.1f}% of traffic.")
        print("  Common causes:")
        print("  - Baud rate mismatch: Confirm Holley is set to 1,000,000 bps (1 Mbps).")
        print("  - Improper termination: Measure resistance across CAN-H and CAN-L (should be ~60Ω).")
        print("  - Loose ground / shield wire on Pin D.")
    else:
        print("\n✅ SUCCESS: CAN BUS IS HEALTHY AND BROADCASTING AT 1 MBPS!")
        print(f"  Bus throughput: {total_frames / duration:.1f} frames/sec")

        if channel_samples:
            print("\n  Decoded Live Channel Telemetry:")
            print("  ┌───────────────────────┬──────────────┬──────────────┐")
            print("  │ Channel Name          │ Live Value   │ Status       │")
            print("  ├───────────────────────┼──────────────┼──────────────┤")
            for ch_name, val in sorted(channel_samples.items()):
                print(f"  │ {ch_name:<21} │ {val:>10.2f}   │ Verified     │")
            print("  └───────────────────────┴──────────────┴──────────────┘")
            print("\n  The system is fully verified and ready for live Copilot recording!")
        else:
            print("\n  Note: CAN frames were received, but none matched standard 29-bit Holley HEFI IDs.")
            print("  Verify ECU broadcast configuration in Holley EFI software.")
    print("═" * 76 + "\n")


# ─── Mode 2: Copilot Analytical Session Runner ───────────────────────────────

async def run_copilot_session(
    interface: str = "simulator",
    channel: str = "sim_virtual0",
    bitrate: int = 1_000_000,
    scenario_name: str = "multi_cycle",
    duration_s: float = 15.0,
    db_path: str = "./data/copilot_sessions.db",
    out_dir: str = "./reports",
    vehicle_name: str = "Holley Terminator X MAX Vehicle",
    engine_spec: str = "6.0L LS V8",
) -> None:
    """
    Runs a full telemetry recording, baseline estimation, deterministic event detection,
    rule-based diagnostic pass, and produces Markdown and HTML reports.
    """
    from app.baseline.engine import BaselineEngine
    from app.diagnostics.engine import DiagnosticEngine
    from app.events.detector import EventDetector
    from app.hardware.simulator import SimulationScenario, VirtualSimulatorAdapter
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

    # Ensure output directories exist
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    print("\n" + "═" * 76)
    print("  EFI INTELLIGENCE COPILOT — SESSION RECORDING & ANALYSIS")
    print("═" * 76)
    logger.info("Initializing Storage & Engines (DB: %s)...", db_path)

    db = Database(db_path)
    repo = TelemetryRepository(db)
    session_mgr = SessionManager(repo, buffer_size=25)

    profile = VehicleProfile(name=vehicle_name, engine_name=engine_spec)
    timeline = ModificationTimeline(profile.vehicle_id)

    decoder = HefiProtocolDecoder()
    baseline_engine = BaselineEngine(profile.vehicle_id)
    detector = EventDetector()
    diag_engine = DiagnosticEngine(baseline_engine)
    report_gen = ReportGenerator(profile)

    # Initialize Hardware / Transport
    if interface in ("simulator", "virtual"):
        try:
            scenario = SimulationScenario(scenario_name)
        except ValueError:
            logger.warning("Unknown scenario '%s', defaulting to multi_cycle", scenario_name)
            scenario = SimulationScenario.MULTI_CYCLE
        logger.info("Using VirtualSimulatorAdapter with scenario: %s", scenario.value)
        adapter = VirtualSimulatorAdapter(scenario=scenario, broadcast_hz=20.0)
    elif interface in ("holley", "holley_usbcan"):
        from app.hardware.holley_usbcan import HolleyUsbCanAdapter
        logger.info("Connecting to Holley USB-to-CAN Cable (WinUSB) at %d bps...", bitrate)
        adapter = HolleyUsbCanAdapter(channel=channel, bitrate=bitrate)
    else:
        logger.info("Connecting to physical CAN transport: %s on %s at %d bps...", interface, channel, bitrate)
        adapter = UsbCanAdapter(interface=interface, channel=channel, bitrate=bitrate)

    connected = await adapter.connect()
    if not connected:
        err = adapter.get_status().error_message or "Connection failed"
        logger.error("Could not connect to CAN interface %s (%s): %s. Aborting session.", interface, channel, err)
        print(f"\n❌ FAILED TO CONNECT to {interface} on {channel}: {err}")
        return

    # Start Session
    session_type = SessionType.TROUBLESHOOTING if interface in ("simulator", "virtual") else SessionType.STREET_DRIVE
    session_meta = session_mgr.start_session(
        vehicle_id=profile.vehicle_id,
        session_type=session_type,
        driver_notes=f"Recorded via {interface}:{channel}",
    )
    logger.info("Session started: %s (Type: %s)", session_meta.session_id, session_type.value)

    if duration_s > 0:
        print(f"Logging for {duration_s:.1f} seconds. (Press Ctrl+C to finish early and generate report)...")
    else:
        print("Logging indefinitely. Press Ctrl+C when finished to generate intelligence report...")

    recorded_samples: list[NormalizedTelemetrySample] = []
    detected_events = []
    current_sample = NormalizedTelemetrySample(timestamp=time.time())
    start_time = time.time()
    last_print = 0.0

    try:
        while True:
            if duration_s > 0 and (time.time() - start_time) >= duration_s:
                break

            frame = await adapter.receive(timeout=0.1)
            if frame is None:
                continue

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

            # Flush sample on RPM frame arrival
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

                # Periodic terminal status
                if time.time() - last_print >= 1.0:
                    last_print = time.time()
                    print(
                        f"\r  [LOGGING] Samples: {len(recorded_samples):>5} │ "
                        f"RPM: {current_sample.engine_rpm:>5.0f} │ "
                        f"MAP: {current_sample.map_kpa:>5.1f} kPa │ "
                        f"TPS: {current_sample.tps:>4.1f}% │ "
                        f"AFR: {current_sample.afr_measured:>4.2f} │ "
                        f"CLT: {current_sample.coolant_temp:>5.1f}°F │ "
                        f"Events: {len(detected_events):>2}",
                        end="",
                        flush=True,
                    )

                current_sample = NormalizedTelemetrySample(timestamp=time.time())

    except (asyncio.CancelledError, KeyboardInterrupt):
        print("\nStopping recording session upon user request...")
    finally:
        print("\n")
        await adapter.disconnect()
        flushed_events = detector.flush(time.time())
        detected_events.extend(flushed_events)
        closed_session = session_mgr.end_session()

    logger.info("Session %s finalized. Total samples recorded: %d", closed_session.session_id, len(recorded_samples))

    # Evaluate Diagnostics
    logger.info("Running deterministic diagnostic engine against recorded telemetry...")
    diagnostics = diag_engine.evaluate_session(recorded_samples, detected_events)
    logger.info("Diagnostic complete. Findings: %d", len(diagnostics))

    # Generate Reports (Markdown and HTML)
    report_md = report_gen.generate_markdown(closed_session, diagnostics)
    report_html = report_gen.generate_html(closed_session, diagnostics)

    md_file = Path(out_dir) / f"report_{closed_session.session_id}.md"
    html_file = Path(out_dir) / f"report_{closed_session.session_id}.html"

    with open(md_file, "w", encoding="utf-8") as f:
        f.write(report_md)
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(report_html)

    logger.info("Saved Markdown report to: %s", md_file.resolve())
    logger.info("Saved HTML report to:     %s", html_file.resolve())

    # Print summary to console
    print("\n" + "═" * 76)
    print(report_md)
    print("═" * 76)
    print(f"\n📄 Offline HTML Report generated: {html_file.resolve()}")
    print("   Double-click the HTML file to open it in your web browser.\n")


# ─── Mode 3: Real-Time Web Dashboard ─────────────────────────────────────────

def run_dashboard(
    interface: str = "simulator",
    channel: str = "sim_virtual0",
    bitrate: int = 1_000_000,
    host: str = "127.0.0.1",
    port: int = 8420,
    open_browser: bool = True,
    config_dict: Optional[dict] = None,
) -> None:
    """Launches the real-time FastAPI dashboard with WebSocket telemetry streamer."""
    import uvicorn
    from holley_can.agent_api import DashboardBroadcaster, create_app
    from holley_can.alerts import AlertConfig, AlertEngine
    from holley_can.listener import CANListener
    from holley_can.storage import TimeSeriesStorage

    cfg = config_dict or {}
    storage_cfg = cfg.get("storage", {})
    alert_cfg = cfg.get("alerts", {})
    dash_cfg = cfg.get("dashboard", {})

    print("\n" + "═" * 76)
    print("  EFI INTELLIGENCE COPILOT — LIVE WEB DASHBOARD")
    print("═" * 76)
    print(f"  Interface:  {interface}:{channel} @ {bitrate:,} bps")
    print(f"  Dashboard:  http://{host}:{port}")
    print("  Press Ctrl+C to stop the dashboard server.\n")

    # If simulator, run background telemetry thread
    if interface in ("simulator", "virtual"):
        channel = "sim_channel"
        interface = "virtual"

    # Initialize components
    listener = CANListener(
        interface=interface,
        channel=channel,
        bitrate=bitrate,
        receive_own_messages=False,
    )

    db_path = storage_cfg.get("database", "./data/holley_can.db")
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

    storage = TimeSeriesStorage(
        db_path=db_path,
        sample_rate_hz=storage_cfg.get("sample_rate_hz", 1.0),
        retention_days=storage_cfg.get("retention_days", 90),
        wal_mode=storage_cfg.get("wal_mode", True),
    )

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
    broadcaster = DashboardBroadcaster(update_rate_ms=dash_cfg.get("update_rate_ms", 50))

    # Wire up subscribers
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

    app = create_app(
        listener=listener,
        storage=storage,
        alert_engine=alert_engine,
        broadcaster=broadcaster,
        cors_origins=["*"],
    )

    if open_browser:
        def _open():
            time.sleep(1.2)
            webbrowser.open(f"http://{host}:{port}")
        import threading
        threading.Thread(target=_open, daemon=True).start()

    # Run Uvicorn server
    uvicorn.run(app, host=host, port=port, log_level="info")


# ─── Master CLI Router ───────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="efi_copilot",
        description="EFI Intelligence Copilot for Holley Terminator X / X MAX",
    )
    subparsers = parser.add_subparsers(dest="command", help="Operational mode")

    # Global config option
    parser.add_argument("--config", type=str, default=None, help="Path to config.yaml")

    # Subcommand: copilot
    copilot_p = subparsers.add_parser("copilot", help="Record session, learn baselines, and generate report")
    copilot_p.add_argument("--interface", type=str, default=None, help="CAN interface (holley, pcan, slcan, socketcan, simulator)")
    copilot_p.add_argument("--channel", type=str, default=None, help="Channel name or COM port (e.g. HOLLEY_USBCAN_0, PCAN_USBBUS1, COM3, can0)")
    copilot_p.add_argument("--bitrate", type=int, default=1_000_000, help="Bitrate in bps (default: 1000000)")
    copilot_p.add_argument("--scenario", type=str, default="wot_pull_lean_dev", help="Simulation scenario if using simulator")
    copilot_p.add_argument("--duration", type=float, default=12.0, help="Duration in seconds (0 for infinite until Ctrl+C)")
    copilot_p.add_argument("--db", type=str, default="./data/copilot_sessions.db", help="SQLite database output path")
    copilot_p.add_argument("--out-dir", type=str, default="./reports", help="Reports output directory")
    copilot_p.add_argument("--vehicle-name", type=str, default="Holley Terminator X MAX Vehicle", help="Vehicle identifier")

    # Subcommand: preflight
    preflight_p = subparsers.add_parser("preflight", help="Bus sniffer & connection tester for tuning laptop")
    preflight_p.add_argument("--interface", type=str, default="holley", help="CAN interface (holley, pcan, slcan, socketcan)")
    preflight_p.add_argument("--channel", type=str, default=None, help="Channel name or COM port (e.g. HOLLEY_USBCAN_0, PCAN_USBBUS1, COM3)")
    preflight_p.add_argument("--bitrate", type=int, default=1_000_000, help="Bitrate in bps (default: 1000000)")
    preflight_p.add_argument("--seconds", type=float, default=12.0, help="Sniff duration in seconds")

    # Subcommand: dashboard
    dash_p = subparsers.add_parser("dashboard", help="Start real-time web dashboard and open browser")
    dash_p.add_argument("--interface", type=str, default=None, help="CAN interface (holley, pcan, slcan, simulator)")
    dash_p.add_argument("--channel", type=str, default=None, help="Channel name or COM port")
    dash_p.add_argument("--bitrate", type=int, default=1_000_000, help="Bitrate in bps")
    dash_p.add_argument("--port", type=int, default=8420, help="HTTP server port (default: 8420)")
    dash_p.add_argument("--no-browser", action="store_true", help="Do not auto-open browser")

    # Subcommand: simulator
    sim_p = subparsers.add_parser("simulator", help="Quick run with virtual simulator demo")
    sim_p.add_argument("--scenario", type=str, default="wot_pull_lean_dev", help="Simulation scenario")
    sim_p.add_argument("--duration", type=float, default=10.0, help="Duration in seconds")
    sim_p.add_argument("--db", type=str, default="./data/copilot_sessions.db", help="SQLite database output path")
    sim_p.add_argument("--out-dir", type=str, default="./reports", help="Reports output directory")
    sim_p.add_argument("--vehicle-name", type=str, default="Holley Terminator X MAX Vehicle", help="Vehicle identifier")

    args = parser.parse_args()
    config = load_config(args.config)
    can_cfg = config.get("can", {})

    # Default to 'copilot' if no subcommand provided
    command = args.command or "copilot"

    def default_channel_for_interface(iface: str) -> str:
        if iface in ("holley", "holley_usbcan"):
            return "HOLLEY_USBCAN_0"
        elif iface in ("simulator", "virtual"):
            return "sim_virtual0"
        elif iface == "pcan":
            return "PCAN_USBBUS1"
        return "can0"

    if command == "preflight":
        iface = args.interface or can_cfg.get("interface", "holley")
        chan = args.channel or can_cfg.get("channel") or default_channel_for_interface(iface)
        br = args.bitrate or can_cfg.get("bitrate", 1_000_000)
        asyncio.run(run_preflight(interface=iface, channel=chan, bitrate=br, sniff_seconds=args.seconds))

    elif command in ("copilot", "simulator"):
        arg_iface = getattr(args, "interface", None)
        arg_chan = getattr(args, "channel", None)
        arg_br = getattr(args, "bitrate", None)
        is_sim = command == "simulator" or (arg_iface in ("simulator", "virtual"))
        iface = "simulator" if is_sim else (arg_iface or can_cfg.get("interface", "holley"))
        chan = "sim_virtual0" if is_sim else (arg_chan or can_cfg.get("channel") or default_channel_for_interface(iface))
        br = arg_br or can_cfg.get("bitrate", 1_000_000)
        scenario = getattr(args, "scenario", "wot_pull_lean_dev")
        dur = getattr(args, "duration", 10.0)

        asyncio.run(
            run_copilot_session(
                interface=iface,
                channel=chan,
                bitrate=br,
                scenario_name=scenario,
                duration_s=dur,
                db_path=getattr(args, "db", "./data/copilot_sessions.db"),
                out_dir=getattr(args, "out_dir", "./reports"),
                vehicle_name=getattr(args, "vehicle_name", "Holley Terminator X MAX Vehicle"),
            )
        )

    elif command == "dashboard":
        raw_iface = args.interface or can_cfg.get("interface")
        if not raw_iface or (sys.platform == "win32" and raw_iface == "socketcan"):
            iface = "holley"
        else:
            iface = raw_iface
        chan = args.channel or can_cfg.get("channel") or default_channel_for_interface(iface)
        br = args.bitrate or can_cfg.get("bitrate", 1_000_000)
        port = args.port or config.get("api", {}).get("port", 8420)
        run_dashboard(
            interface=iface,
            channel=chan,
            bitrate=br,
            port=port,
            open_browser=not args.no_browser,
            config_dict=config,
        )


if __name__ == "__main__":
    main()
