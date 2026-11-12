"""
listener.py — Async CAN bus listener for HEFI & Racepak broadcast traffic.

Passively listens on a Holley WinUSB cable, SocketCAN, SLCAN, or Virtual Simulator
interface, auto-detects Holley Standard (HEFI IEEE-754 float32) vs Racepak
(int32BE / 256) broadcast frames in real time, and distributes decoded data
to storage, WebSocket broadcast, and alert engine.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Optional

import can

from .protocol import (
    CHANNEL_BY_NAME,
    CHANNEL_MAP,
    DecodedFrame,
    decode_frame,
    decode_racepak_frame,
    extract_channel_index,
    extract_ecu_serial,
    decode_sensor_status_flags,
    is_ecu_announcement,
    is_hefi_announcement,
    is_hefi_broadcast,
    is_racepak_header_id,
)

logger = logging.getLogger(__name__)


@dataclass
class ChannelSnapshot:
    """Latest state for a single channel."""
    name: str
    label: str
    unit: str
    value: float
    value_b: float
    timestamp: float
    update_count: int = 0


class CANListener:
    """
    Async CAN bus listener that decodes HEFI and Racepak broadcast frames.

    Features:
        - Auto-detects ECU serial from traffic
        - Auto-detects Holley Standard (HEFI 29-bit float32) vs Racepak (int32BE/256) protocol
        - Maintains live state dict of all decoded channels
        - Per-channel ring buffers for recent history (configurable depth)
        - Subscriber pattern for real-time consumers (storage, alerts, dashboard)
    """

    def __init__(
        self,
        interface: str = "holley" if sys.platform == "win32" else "socketcan",
        channel: str = "HOLLEY_USBCAN_0" if sys.platform == "win32" else "can0",
        bitrate: int = 1_000_000,
        history_depth: int = 600,  # ~10 minutes at 1 Hz
        receive_own_messages: bool = False,
        protocol_mode: str = "auto",  # "auto", "hefi", or "racepak"
    ):
        self.interface = interface
        self.channel = channel
        self.bitrate = bitrate
        self.history_depth = history_depth
        self.receive_own_messages = receive_own_messages
        self.protocol_mode = protocol_mode
        self._detected_protocol: str = "hefi" if protocol_mode == "auto" else protocol_mode

        # Live state: channel_name → ChannelSnapshot
        self._live: dict[str, ChannelSnapshot] = {}

        # Recent history: channel_name → deque of (timestamp, value_a, value_b)
        self._history: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=history_depth)
        )

        # Auto-detected ECU serial (lower 11 bits)
        self._ecu_serial: Optional[int] = None
        self._serial_votes: dict[int, int] = defaultdict(int)

        # Discovery: all seen channel indices and their frame counts
        self._discovered: dict[int, int] = defaultdict(int)

        # Subscribers: async callbacks invoked for every decoded frame
        self._subscribers: list[Callable[[DecodedFrame], Coroutine]] = []

        # CAN bus handle or Holley/Simulator adapter
        self._bus: Optional[can.Bus] = None
        self._holley_adapter: Any = None
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Stats
        self._frame_count = 0
        self._error_count = 0
        self._start_time: Optional[float] = None

    # ── Subscriber management ───────────────────────────────────────────

    def subscribe(self, callback: Callable[[DecodedFrame], Coroutine]) -> None:
        """Register an async callback to receive every decoded frame."""
        if callback not in self._subscribers:
            self._subscribers.append(callback)
            logger.info("Subscriber registered: %s", callback.__qualname__)

    def unsubscribe(self, callback: Callable[[DecodedFrame], Coroutine]) -> None:
        """Remove a previously registered subscriber callback."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    # ── Live state access ───────────────────────────────────────────────

    def get_live_snapshot(self) -> dict[str, dict[str, Any]]:
        """Return the current state of all channels as a serializable dict."""
        return {
            name: {
                "name": snap.name,
                "label": snap.label,
                "unit": snap.unit,
                "value": round(snap.value, 3),
                "value_b": round(snap.value_b, 3),
                "circuit_fault": decode_sensor_status_flags(snap.value_b) if snap.value_b else {"healthy": True},
                "timestamp": snap.timestamp,
                "age_ms": round((time.time() - snap.timestamp) * 1000, 1),
            }
            for name, snap in self._live.items()
        }

    def get_channel_value(self, channel_name: str) -> Optional[float]:
        """Get the latest value for a named channel."""
        snap = self._live.get(channel_name)
        return snap.value if snap else None

    def get_channel_history(
        self, channel_name: str, limit: int = 0
    ) -> list[tuple[float, float, float]]:
        """Get recent history for a channel as [(timestamp, value_a, value_b), ...]."""
        history = list(self._history.get(channel_name, []))
        if limit > 0:
            history = history[-limit:]
        return history

    def get_discovery_info(self) -> dict:
        """Return information about all discovered CAN IDs."""
        result = {}
        for idx, count in sorted(self._discovered.items()):
            ch_def = CHANNEL_MAP.get(idx)
            result[idx] = {
                "index": idx,
                "name": ch_def.name if ch_def else f"unknown_{idx}",
                "label": ch_def.label if ch_def else f"Channel {idx}",
                "known": ch_def is not None,
                "frame_count": count,
            }
        return result

    @property
    def ecu_serial(self) -> Optional[int]:
        return self._ecu_serial

    @property
    def stats(self) -> dict:
        uptime = time.time() - self._start_time if self._start_time else 0
        return {
            "running": self._running,
            "protocol_mode": self._detected_protocol,
            "uptime_s": round(uptime, 1),
            "frames_decoded": self._frame_count,
            "error_frames": self._error_count,
            "error_rate_pct": round(
                (self._error_count / max(self._frame_count, 1)) * 100, 3
            ),
            "channels_discovered": len(self._discovered),
            "channels_known": sum(
                1 for idx in self._discovered if idx in CHANNEL_MAP
            ),
            "ecu_serial_bits": self._ecu_serial,
            "fps": round(self._frame_count / max(uptime, 1), 1),
        }

    # ── Lifecycle ───────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the CAN listener in the background."""
        if self._running:
            logger.warning("Listener already running")
            return

        logger.info(
            "Starting CAN listener on %s (%s) at %d bit/s",
            self.channel, self.interface, self.bitrate,
        )

        if self.interface in ("holley", "holley_usbcan"):
            from app.hardware.holley_usbcan import HolleyUsbCanAdapter
            self._holley_adapter = HolleyUsbCanAdapter(bitrate=self.bitrate, channel=self.channel)
            success = await self._holley_adapter.connect()
            if not success:
                err = self._holley_adapter.get_status().error_message or "Failed to connect to Holley USB cable"
                logger.error("Failed to connect Holley adapter: %s", err)
                raise RuntimeError(err)
        elif self.interface in ("simulator", "virtual"):
            from app.hardware.simulator import SimulationScenario, VirtualSimulatorAdapter
            scenario_str = self.channel if self.channel in [s.value for s in SimulationScenario] else "multi_cycle"
            self._holley_adapter = VirtualSimulatorAdapter(
                scenario=SimulationScenario(scenario_str),
                broadcast_hz=20.0,
            )
            await self._holley_adapter.connect()
        else:
            try:
                self._bus = can.Bus(
                    interface=self.interface,
                    channel=self.channel,
                    bitrate=self.bitrate,
                    receive_own_messages=self.receive_own_messages,
                )
            except Exception as e:
                logger.error("Failed to open CAN bus: %s", e)
                raise

        self._running = True
        self._start_time = time.time()
        self._task = asyncio.create_task(self._listen_loop())
        logger.info("CAN listener started")

    async def stop(self) -> None:
        """Stop the CAN listener."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._holley_adapter:
            await self._holley_adapter.disconnect()
            self._holley_adapter = None
        if self._bus:
            self._bus.shutdown()
            self._bus = None
        logger.info("CAN listener stopped")

    async def switch_interface(
        self, interface: str, channel: str, bitrate: int = 1_000_000
    ) -> None:
        """Dynamically stop the current listener and switch to a new adapter."""
        logger.info("Switching CAN interface to %s (%s) at %d bps", interface, channel, bitrate)
        await self.stop()
        self.interface = interface
        self.channel = channel
        self.bitrate = bitrate
        await self.start()

    async def inject_decoded_frames(self, frames: list[DecodedFrame]) -> None:
        """
        Inject decoded frames (e.g. from an offline .dl/.dlz datalog) into live state,
        history buffers, and subscribers.
        """
        for frame in frames:
            self._frame_count += 1
            self._discovered[frame.channel_index] += 1
            self._update_live(frame)
            for callback in self._subscribers:
                try:
                    await callback(frame)
                except Exception as e:
                    logger.error("Subscriber %s error: %s", callback.__qualname__, e)

    # ── Main loop ───────────────────────────────────────────────────────

    async def _listen_loop(self) -> None:
        """Main receive loop — runs in the background."""
        loop = asyncio.get_event_loop()

        while self._running:
            try:
                if self._holley_adapter:
                    msg = await self._holley_adapter.receive(timeout=0.1)
                elif self._bus:
                    msg = await loop.run_in_executor(
                        None, lambda: self._bus.recv(timeout=0.1)
                    )
                else:
                    await asyncio.sleep(0.1)
                    continue

                if msg is None:
                    continue

                if msg.is_error_frame:
                    self._error_count += 1
                    continue

                if not msg.is_extended_id:
                    continue

                ts = msg.timestamp if msg.timestamp else time.time()
                raw_bytes = bytes(msg.data)

                # Detect ECU announcement frames on CAN Bus 1 (e.g. 0x0E001556)
                if is_hefi_announcement(msg.arbitration_id):
                    if is_ecu_announcement(msg.arbitration_id):
                        ecu_ser = extract_ecu_serial(msg.arbitration_id)
                        self._serial_votes[ecu_ser] += 1
                        if self._ecu_serial is None:
                            self._ecu_serial = ecu_ser
                            logger.info(
                                "Detected Terminator X ECU announcement on CAN Bus 1: CAN_ID=0x%08X (Serial 0x%03X / %d)",
                                msg.arbitration_id,
                                ecu_ser,
                                ecu_ser,
                            )
                    continue

                if len(raw_bytes) != 8:
                    continue

                # Auto-detect Racepak header frame (0x1E001000, channel_index == 0)
                if is_racepak_header_id(msg.arbitration_id):
                    if self.protocol_mode == "auto" and self._detected_protocol != "racepak":
                        self._detected_protocol = "racepak"
                        logger.info("Auto-detected Racepak CAN broadcast mode (0x1E001000)")

                decoded_list: list[DecodedFrame] = []
                if self._detected_protocol == "racepak" or is_racepak_header_id(msg.arbitration_id):
                    decoded_list = decode_racepak_frame(msg.arbitration_id, raw_bytes, ts)
                elif is_hefi_broadcast(msg.arbitration_id):
                    decoded_list = [decode_frame(msg.arbitration_id, raw_bytes, ts)]

                for frame in decoded_list:
                    self._frame_count += 1

                    # Auto-detect ECU serial from traffic
                    self._serial_votes[frame.ecu_serial_bits] += 1
                    if self._ecu_serial is None and self._frame_count >= 50:
                        self._ecu_serial = max(
                            self._serial_votes, key=self._serial_votes.get
                        )
                        logger.info(
                            "Auto-detected ECU serial bits: 0x%03X (%d)",
                            self._ecu_serial, self._ecu_serial,
                        )

                    # Track discovery
                    self._discovered[frame.channel_index] += 1

                    # Update live state
                    self._update_live(frame)

                    # Notify subscribers
                    for callback in self._subscribers:
                        try:
                            await callback(frame)
                        except Exception as e:
                            logger.error(
                                "Subscriber %s error: %s",
                                callback.__qualname__, e,
                            )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Listen loop error: %s", e, exc_info=True)
                await asyncio.sleep(0.1)

    def _update_live(self, frame: DecodedFrame) -> None:
        """Update the live state dict and history buffer for a decoded frame."""
        name = frame.name

        if name in self._live:
            self._live[name].value = frame.value_a
            self._live[name].value_b = frame.value_b
            self._live[name].timestamp = frame.timestamp
            self._live[name].update_count += 1
        else:
            self._live[name] = ChannelSnapshot(
                name=name,
                label=frame.label,
                unit=frame.unit,
                value=frame.value_a,
                value_b=frame.value_b,
                timestamp=frame.timestamp,
                update_count=1,
            )

        # Append to ring buffer history
        self._history[name].append(
            (frame.timestamp, frame.value_a, frame.value_b)
        )
