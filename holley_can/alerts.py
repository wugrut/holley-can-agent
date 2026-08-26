"""
alerts.py — Rule-based anomaly detection engine for HEFI CAN data.

Evaluates decoded frames in real-time against configurable thresholds
to detect dangerous engine conditions: lean/rich AFR, timing retard,
overboost, low voltage, sensor dropout, and CAN bus errors.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Optional

from .protocol import DecodedFrame

logger = logging.getLogger(__name__)


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Alert:
    """An active or recently-fired alert."""
    alert_type: str
    severity: Severity
    channel: str
    message: str
    value: Optional[float] = None
    threshold: Optional[float] = None
    timestamp: float = field(default_factory=time.time)
    duration_s: float = 0.0
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_type": self.alert_type,
            "severity": self.severity.value,
            "channel": self.channel,
            "message": self.message,
            "value": self.value,
            "threshold": self.threshold,
            "timestamp": self.timestamp,
            "duration_s": round(self.duration_s, 2),
            "active": self.active,
        }


@dataclass
class AlertConfig:
    """Configurable thresholds for the alert engine."""
    enabled: bool = True
    lean_afr_offset: float = 0.5       # Wideband > target + offset triggers lean
    rich_afr_offset: float = 1.0       # Wideband < target - offset triggers rich
    timing_retard_deg: float = 3.0     # Timing drop > this from baseline
    overboost_map_kpa: float = 250.0   # MAP threshold for overboost (~22 psi)
    low_voltage_v: float = 13.0        # Battery below this while running
    sensor_dropout_s: float = 1.0      # No update for this long = dropout
    can_error_rate_pct: float = 1.0    # Error frame percentage
    cooldown_s: float = 5.0            # Min seconds between same alert type


class AlertEngine:
    """
    Real-time alert engine evaluating decoded CAN frames.

    Subscribes to the CAN listener and fires alerts when thresholds
    are crossed. Supports alert callbacks for storage logging and
    WebSocket push notifications.
    """

    def __init__(self, config: Optional[AlertConfig] = None):
        self.config = config or AlertConfig()

        # Active alerts: alert_type → Alert
        self._active: dict[str, Alert] = {}

        # Recent alerts (for dashboard display)
        self._recent: list[Alert] = []
        self._max_recent = 100

        # Cooldown tracking: alert_type → last fire timestamp
        self._cooldowns: dict[str, float] = {}

        # Baseline values (learned from initial operation)
        self._timing_baseline: Optional[float] = None
        self._timing_samples: list[float] = []

        # Alert callbacks
        self._callbacks: list[Callable[[Alert], Coroutine]] = []

        # Latest channel values (for cross-channel rules)
        self._latest: dict[str, float] = {}
        self._last_update: dict[str, float] = {}

    def on_alert(self, callback: Callable[[Alert], Coroutine]) -> None:
        """Register an async callback for alert events."""
        self._callbacks.append(callback)

    def get_active_alerts(self) -> list[dict[str, Any]]:
        """Return all currently active alerts."""
        now = time.time()
        result = []
        for alert in self._active.values():
            alert.duration_s = now - alert.timestamp
            result.append(alert.to_dict())
        return result

    def get_recent_alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent alerts (active and resolved)."""
        return [a.to_dict() for a in self._recent[-limit:]]

    # ── Frame evaluation ────────────────────────────────────────────────

    async def on_frame(self, frame: DecodedFrame) -> None:
        """Evaluate a decoded frame against all alert rules."""
        if not self.config.enabled:
            return

        name = frame.name
        value = frame.value_a
        now = frame.timestamp

        # Update latest values
        self._latest[name] = value
        self._last_update[name] = now

        # Run rules
        await self._check_lean_afr(name, value, now)
        await self._check_rich_afr(name, value, now)
        await self._check_timing_retard(name, value, now)
        await self._check_overboost(name, value, now)
        await self._check_low_voltage(name, value, now)
        await self._check_high_coolant(name, value, now)

    async def check_dropouts(self) -> None:
        """
        Check for sensor dropouts. Call periodically (e.g., every second).
        A channel that stops updating for longer than sensor_dropout_s is flagged.
        """
        now = time.time()
        for name, last_ts in self._last_update.items():
            if (now - last_ts) > self.config.sensor_dropout_s:
                await self._fire_alert(
                    alert_type=f"dropout_{name}",
                    severity=Severity.WARNING,
                    channel=name,
                    message=f"Sensor dropout: {name} — no update for {now - last_ts:.1f}s",
                    value=now - last_ts,
                    threshold=self.config.sensor_dropout_s,
                )

    # ── Individual rule checks ──────────────────────────────────────────

    async def _check_lean_afr(self, name: str, value: float, now: float) -> None:
        """Lean AFR: wideband > target + offset at WOT."""
        if name not in ("afr_avg", "afr_left", "afr_right"):
            return

        target = self._latest.get("target_afr")
        tps = self._latest.get("tps", 0)

        if target is None:
            return

        # Only alert at significant throttle (WOT or near-WOT)
        if tps < 80:
            return

        if value > (target + self.config.lean_afr_offset):
            await self._fire_alert(
                alert_type=f"lean_afr_{name}",
                severity=Severity.CRITICAL,
                channel=name,
                message=f"LEAN AFR: {value:.1f} vs target {target:.1f} at {tps:.0f}% TPS",
                value=value,
                threshold=target + self.config.lean_afr_offset,
            )
        else:
            self._resolve_alert(f"lean_afr_{name}")

    async def _check_rich_afr(self, name: str, value: float, now: float) -> None:
        """Rich AFR: wideband < target - offset sustained."""
        if name not in ("afr_avg", "afr_left", "afr_right"):
            return

        target = self._latest.get("target_afr")
        if target is None:
            return

        if value < (target - self.config.rich_afr_offset):
            await self._fire_alert(
                alert_type=f"rich_afr_{name}",
                severity=Severity.WARNING,
                channel=name,
                message=f"Rich AFR: {value:.1f} vs target {target:.1f}",
                value=value,
                threshold=target - self.config.rich_afr_offset,
            )
        else:
            self._resolve_alert(f"rich_afr_{name}")

    async def _check_timing_retard(self, name: str, value: float, now: float) -> None:
        """Ignition timing retard detection (possible knock)."""
        if name != "ignition_timing":
            return

        # Learn baseline from first 100 samples above idle
        rpm = self._latest.get("rpm", 0)
        if rpm > 1500 and len(self._timing_samples) < 100:
            self._timing_samples.append(value)
            if len(self._timing_samples) == 100:
                self._timing_baseline = sum(self._timing_samples) / len(self._timing_samples)
                logger.info("Timing baseline learned: %.1f° BTDC", self._timing_baseline)

        if self._timing_baseline is None:
            return

        retard = self._timing_baseline - value
        if retard > self.config.timing_retard_deg:
            await self._fire_alert(
                alert_type="timing_retard",
                severity=Severity.CRITICAL,
                channel=name,
                message=f"Timing retard: {retard:.1f}° from baseline ({self._timing_baseline:.1f}° → {value:.1f}°) — possible knock",
                value=value,
                threshold=self._timing_baseline - self.config.timing_retard_deg,
            )
        else:
            self._resolve_alert("timing_retard")

    async def _check_overboost(self, name: str, value: float, now: float) -> None:
        """MAP exceeding safe threshold."""
        if name != "map_kpa":
            return

        if value > self.config.overboost_map_kpa:
            await self._fire_alert(
                alert_type="overboost",
                severity=Severity.CRITICAL,
                channel=name,
                message=f"OVERBOOST: {value:.0f} kPa ({(value - 101.325) * 0.145038:.1f} psi boost)",
                value=value,
                threshold=self.config.overboost_map_kpa,
            )
        else:
            self._resolve_alert("overboost")

    async def _check_low_voltage(self, name: str, value: float, now: float) -> None:
        """Battery voltage below threshold while engine is running."""
        if name != "battery_voltage":
            return

        rpm = self._latest.get("rpm", 0)
        if rpm < 400:  # Engine not running
            return

        if value < self.config.low_voltage_v:
            await self._fire_alert(
                alert_type="low_voltage",
                severity=Severity.WARNING,
                channel=name,
                message=f"Low battery: {value:.1f}V (threshold: {self.config.low_voltage_v}V)",
                value=value,
                threshold=self.config.low_voltage_v,
            )
        else:
            self._resolve_alert("low_voltage")

    async def _check_high_coolant(self, name: str, value: float, now: float) -> None:
        """Coolant temperature over safe limit."""
        if name != "coolant_temp":
            return

        if value > 230:  # °F — high but not yet catastrophic
            severity = Severity.CRITICAL if value > 250 else Severity.WARNING
            await self._fire_alert(
                alert_type="high_coolant",
                severity=severity,
                channel=name,
                message=f"High coolant temp: {value:.0f}°F",
                value=value,
                threshold=230,
            )
        else:
            self._resolve_alert("high_coolant")

    # ── Alert management ────────────────────────────────────────────────

    async def _fire_alert(self, **kwargs) -> None:
        """Create or update an alert, respecting cooldown periods."""
        alert_type = kwargs["alert_type"]
        now = time.time()

        # Check cooldown
        last_fire = self._cooldowns.get(alert_type, 0)
        if (now - last_fire) < self.config.cooldown_s:
            return

        self._cooldowns[alert_type] = now

        alert = Alert(**kwargs)

        if alert_type not in self._active:
            self._active[alert_type] = alert
            self._recent.append(alert)

            # Trim recent list
            if len(self._recent) > self._max_recent:
                self._recent = self._recent[-self._max_recent:]

            logger.warning(
                "🚨 ALERT [%s] %s: %s",
                alert.severity.value.upper(),
                alert.alert_type,
                alert.message,
            )

            # Notify callbacks
            for cb in self._callbacks:
                try:
                    await cb(alert)
                except Exception as e:
                    logger.error("Alert callback error: %s", e)

    def _resolve_alert(self, alert_type: str) -> None:
        """Mark an alert as resolved."""
        if alert_type in self._active:
            alert = self._active.pop(alert_type)
            alert.active = False
            alert.duration_s = time.time() - alert.timestamp
            logger.info(
                "✓ Alert resolved [%s] after %.1fs",
                alert_type, alert.duration_s,
            )
