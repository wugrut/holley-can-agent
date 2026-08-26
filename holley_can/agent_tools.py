"""
agent_tools.py — Agent-callable tool definitions for ECU interaction.

These functions expose the CAN listener and storage as high-level tools
that an LLM-based agent (like Antigravity) can invoke for conversational
analysis of live and historical ECU data.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from .listener import CANListener
from .storage import TimeSeriesStorage
from .alerts import AlertEngine


class ECUAgentTools:
    """
    High-level tool functions for agentic ECU interaction.

    Each method is designed to be directly callable by an AI agent,
    returning structured data suitable for natural language interpretation.
    """

    def __init__(
        self,
        listener: CANListener,
        storage: TimeSeriesStorage,
        alert_engine: AlertEngine,
    ):
        self.listener = listener
        self.storage = storage
        self.alerts = alert_engine

    async def get_live_ecu_data(self) -> dict[str, Any]:
        """
        Get a complete snapshot of all live ECU channels.

        Returns current values for RPM, MAP, AFR, timing, temperatures,
        transmission state, and more. Each channel includes its value,
        unit, and data freshness (age in ms).

        Use this to answer questions like:
        - "What's my current RPM and MAP?"
        - "Is the engine running?"
        - "What gear am I in?"
        """
        snapshot = self.listener.get_live_snapshot()
        stats = self.listener.stats

        return {
            "summary": self._build_summary(snapshot),
            "channels": snapshot,
            "engine_running": self._is_engine_running(snapshot),
            "ecu_serial": self.listener.ecu_serial,
            "uptime_s": stats.get("uptime_s", 0),
            "timestamp": time.time(),
        }

    async def get_channel_value(self, channel: str) -> dict[str, Any]:
        """
        Get the current value for a specific channel.

        Args:
            channel: Channel name (e.g., "rpm", "map_kpa", "afr_avg",
                     "ignition_timing", "coolant_temp", "battery_voltage",
                     "trans_gear", "tcc_status").

        Use this to answer questions like:
        - "What's my AFR right now?"
        - "What's the coolant temperature?"
        """
        value = self.listener.get_channel_value(channel)
        snapshot = self.listener.get_live_snapshot()
        channel_info = snapshot.get(channel)

        if channel_info is None:
            available = list(snapshot.keys())
            return {
                "error": f"Channel '{channel}' not found",
                "available_channels": available,
            }

        return {
            "channel": channel,
            **channel_info,
        }

    async def query_ecu_history(
        self,
        channel: str,
        duration_minutes: int = 60,
        aggregation: str = "avg",
        bucket_seconds: int = 60,
    ) -> dict[str, Any]:
        """
        Query historical ECU data for analysis.

        Args:
            channel: Channel name (e.g., "rpm", "map_kpa", "afr_avg").
            duration_minutes: How far back to look (default: 60 min).
            aggregation: "avg", "min", or "max".
            bucket_seconds: Time bucket size for aggregation.

        Use this to answer questions like:
        - "What was my average MAP over the last hour?"
        - "What was the peak RPM in the last 30 minutes?"
        - "Show me AFR history from the last 10 minutes."
        """
        end_time = time.time()
        start_time = end_time - (duration_minutes * 60)

        data = await self.storage.query_history(
            channel=channel,
            start_time=start_time,
            end_time=end_time,
            aggregation=aggregation,
            bucket_seconds=bucket_seconds,
        )

        # Compute summary statistics
        values = [row.get("value", row.get("value_a", 0)) for row in data if row]
        stats = {}
        if values:
            stats = {
                "min": round(min(values), 3),
                "max": round(max(values), 3),
                "avg": round(sum(values) / len(values), 3),
                "samples": len(values),
            }

        return {
            "channel": channel,
            "duration_minutes": duration_minutes,
            "aggregation": aggregation,
            "bucket_seconds": bucket_seconds,
            "statistics": stats,
            "data": data,
        }

    async def check_anomalies(self) -> dict[str, Any]:
        """
        Check for active alerts and recent anomalies.

        Returns currently active alerts (lean AFR, timing retard,
        overboost, low voltage, etc.) and recently resolved alerts.

        Use this to answer questions like:
        - "Are there any problems right now?"
        - "Has there been any knock detected?"
        - "Any lean conditions today?"
        """
        active = self.alerts.get_active_alerts()
        recent = self.alerts.get_recent_alerts(limit=20)
        db_alerts = await self.storage.query_alerts(limit=50)

        return {
            "status": "alerts_active" if active else "all_clear",
            "active_alerts": active,
            "active_count": len(active),
            "recent_alerts": recent,
            "historical_alerts": db_alerts,
        }

    async def analyze_wot_pull(
        self,
        duration_seconds: int = 30,
    ) -> dict[str, Any]:
        """
        Analyze the most recent WOT (Wide Open Throttle) pull.

        Looks back through recent history to find a period where TPS
        was >90% and analyzes AFR deviation from target, timing retard
        events, peak MAP, and RPM range.

        Args:
            duration_seconds: How far back to search for WOT events.

        Use this to answer questions like:
        - "How was my last WOT pull?"
        - "Was the AFR on target during my last pull?"
        - "Did I get any knock on the last run?"
        """
        end_time = time.time()
        start_time = end_time - duration_seconds

        # Get raw data for key channels
        channels = ["rpm", "map_kpa", "afr_avg", "target_afr", "ignition_timing", "tps"]
        channel_data: dict[str, list] = {}
        for ch in channels:
            channel_data[ch] = await self.storage.query_history(
                channel=ch, start_time=start_time, end_time=end_time
            )

        # Find WOT periods (TPS > 90%)
        tps_data = channel_data.get("tps", [])
        wot_periods = []
        in_wot = False
        wot_start = None

        for row in tps_data:
            val = row.get("value_a", 0)
            ts = row.get("timestamp", 0)
            if val > 90 and not in_wot:
                in_wot = True
                wot_start = ts
            elif val <= 90 and in_wot:
                in_wot = False
                wot_periods.append({"start": wot_start, "end": ts, "duration": ts - wot_start})

        if in_wot and wot_start:
            wot_periods.append({"start": wot_start, "end": end_time, "duration": end_time - wot_start})

        if not wot_periods:
            return {
                "status": "no_wot_detected",
                "message": f"No WOT events found in the last {duration_seconds} seconds.",
                "search_window_s": duration_seconds,
            }

        # Analyze the last WOT period
        last_wot = wot_periods[-1]

        # Get AFR deviation during WOT
        afr_data = [
            r for r in channel_data.get("afr_avg", [])
            if last_wot["start"] <= r.get("timestamp", 0) <= last_wot["end"]
        ]
        target_data = [
            r for r in channel_data.get("target_afr", [])
            if last_wot["start"] <= r.get("timestamp", 0) <= last_wot["end"]
        ]

        afr_values = [r.get("value_a", 0) for r in afr_data]
        target_values = [r.get("value_a", 0) for r in target_data]

        afr_analysis = {}
        if afr_values and target_values:
            avg_afr = sum(afr_values) / len(afr_values)
            avg_target = sum(target_values) / len(target_values)
            afr_analysis = {
                "avg_afr": round(avg_afr, 2),
                "avg_target": round(avg_target, 2),
                "deviation": round(avg_afr - avg_target, 2),
                "min_afr": round(min(afr_values), 2),
                "max_afr": round(max(afr_values), 2),
                "on_target": abs(avg_afr - avg_target) < 0.3,
            }

        # Peak MAP/RPM during WOT
        rpm_data = [
            r.get("value_a", 0)
            for r in channel_data.get("rpm", [])
            if last_wot["start"] <= r.get("timestamp", 0) <= last_wot["end"]
        ]
        map_data = [
            r.get("value_a", 0)
            for r in channel_data.get("map_kpa", [])
            if last_wot["start"] <= r.get("timestamp", 0) <= last_wot["end"]
        ]

        return {
            "status": "wot_analyzed",
            "wot_period": last_wot,
            "total_wot_events": len(wot_periods),
            "afr_analysis": afr_analysis,
            "peak_rpm": round(max(rpm_data), 0) if rpm_data else None,
            "peak_map_kpa": round(max(map_data), 1) if map_data else None,
            "peak_boost_psi": round((max(map_data) - 101.325) * 0.145038, 1) if map_data else None,
        }

    async def get_transmission_status(self) -> dict[str, Any]:
        """
        Get current 4L80E transmission status.

        Returns gear position, TCC status, fluid temperature, and
        shaft speeds if available.

        Use this to answer questions like:
        - "What gear am I in?"
        - "Is the torque converter locked?"
        - "What's the trans temp?"
        """
        trans_channels = ["trans_gear", "trans_temp", "tcc_status", "output_speed", "input_speed", "line_pressure"]
        snapshot = self.listener.get_live_snapshot()

        result = {}
        for ch in trans_channels:
            if ch in snapshot:
                result[ch] = snapshot[ch]

        gear = self.listener.get_channel_value("trans_gear")
        gear_names = {0: "Park/Neutral", 1: "1st", 2: "2nd", 3: "3rd", 4: "4th (OD)"}

        return {
            "gear": gear_names.get(int(gear), f"Unknown ({gear})") if gear is not None else "N/A",
            "gear_number": gear,
            "channels": result,
        }

    # ── Helpers ──────────────────────────────────────────────────────────

    def _is_engine_running(self, snapshot: dict) -> bool:
        rpm_info = snapshot.get("rpm", {})
        rpm = rpm_info.get("value", 0) if rpm_info else 0
        return rpm > 300

    def _build_summary(self, snapshot: dict) -> str:
        """Build a human-readable summary of current engine state."""
        parts = []

        rpm = snapshot.get("rpm", {}).get("value", 0)
        if rpm > 300:
            parts.append(f"Engine running at {rpm:.0f} RPM")
        else:
            parts.append("Engine OFF")
            return " | ".join(parts)

        map_val = snapshot.get("map_kpa", {}).get("value")
        if map_val:
            boost_psi = (map_val - 101.325) * 0.145038
            if boost_psi > 0.5:
                parts.append(f"Boost: {boost_psi:.1f} psi")
            else:
                parts.append(f"Vacuum: {(101.325 - map_val) * 0.295300:.1f} inHg")

        afr = snapshot.get("afr_avg", {}).get("value")
        target = snapshot.get("target_afr", {}).get("value")
        if afr and target:
            parts.append(f"AFR: {afr:.1f} (target {target:.1f})")

        timing = snapshot.get("ignition_timing", {}).get("value")
        if timing:
            parts.append(f"Timing: {timing:.1f}°")

        coolant = snapshot.get("coolant_temp", {}).get("value")
        if coolant:
            parts.append(f"Coolant: {coolant:.0f}°F")

        gear = snapshot.get("trans_gear", {}).get("value")
        if gear is not None:
            gear_names = {0: "P/N", 1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}
            parts.append(f"Gear: {gear_names.get(int(gear), '?')}")

        return " | ".join(parts)
