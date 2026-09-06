"""
listener.py — Async CAN bus listener for HEFI broadcast traffic.

Passively listens on a SocketCAN interface, decodes HEFI frames in real time,
and distributes decoded data to storage, WebSocket broadcast, and alert engine.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Optional

import can
from can import Message

from .protocol import (
    CHANNEL_MAP,
    DecodedFrame,
    decode_frame,
    extract_channel_index,
    extract_ecu_serial,
    is_hefi_broadcast,
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
    Async CAN bus listener that decodes HEFI broadcast frames.

    Features:
        - Auto-detects ECU serial from traffic
        - Maintains live state dict of all decoded channels
        - Per-channel ring buffers for recent history (configurable depth)
        - Subscriber pattern for real-time consumers (storage, alerts, dashboard)
    """

    def __init__(
        self,
        interface: str = "socketcan",
        channel: str = "can0",
        bitrate: int = 1_000_000,
        history_depth: int = 600,  # ~10 minutes at 1 Hz
        receive_own_messages: bool = False,
    ):
        self.interface = interface
        self.channel = channel
        self.bitrate = bitrate
        self.history_depth = history_depth
        self.receive_own_messages = receive_own_messages

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

        # CAN bus handle or Holley adapter
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

    # ── Main loop ───────────────────────────────────────────────────────

    async def _listen_loop(self) -> None:
        """Main receive loop — runs in the background."""
        loop = asyncio.get_event_loop()

        while self._running:
            try:
                if self._holley_adapter:
                    msg = await self._holley_adapter.receive(timeout=0.1)
                elif self._bus:
                    # Non-blocking receive with timeout, offloaded to thread pool
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

                # Only process extended (29-bit) frames
                if not msg.is_extended_id:
                    continue

                # Validate as HEFI broadcast
                if not is_hefi_broadcast(msg.arbitration_id):
                    continue

                if len(msg.data) != 8:
                    continue

                # Decode
                ts = msg.timestamp if msg.timestamp else time.time()
                frame = decode_frame(msg.arbitration_id, bytes(msg.data), ts)
                self._frame_count += 1

                # Auto-detect ECU serial from traffic
                self._serial_votes[frame.ecu_serial_bits] += 1
                if self._ecu_serial is None and self._frame_count >= 50:
                    # Pick the most common serial after 50 frames
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
