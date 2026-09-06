"""
Deterministic finite state machine detector for engine events.
"""

from __future__ import annotations

from typing import Dict, List, Optional
import numpy as np

from app.events.types import EngineEvent, EventSeverity, EventType
from app.telemetry.sample import NormalizedTelemetrySample


class EventDetector:
    """
    Evaluates streaming normalized telemetry samples and emits typed EngineEvents
    with explicit evidence payloads and metrics.
    """

    def __init__(self) -> None:
        self.was_running = False

        # Active state tracking
        self._active_wot: Optional[Dict] = None
        self._active_idle: Optional[Dict] = None
        self._active_thermal: Optional[Dict] = None
        self._active_voltage: Optional[Dict] = None

        self._recent_rpms: List[float] = []

    def feed_sample(self, s: NormalizedTelemetrySample) -> List[EngineEvent]:
        """Processes a single telemetry sample and emits any completed or triggered events."""
        events: List[EngineEvent] = []

        # 1. Engine Running State Transitions (Start / Stop)
        is_running = s.engine_rpm > 400.0
        if is_running and not self.was_running:
            events.append(
                EngineEvent(
                    event_type=EventType.ENGINE_START,
                    severity=EventSeverity.INFO,
                    start_time=s.timestamp,
                    end_time=s.timestamp,
                    duration_s=0.0,
                    signals_involved=["engine_rpm", "battery_voltage"],
                    calculated_metrics={"rpm": s.engine_rpm, "voltage": s.battery_voltage},
                    confidence=1.0,
                    evidence=f"Engine RPM crossed 400 RPM threshold ({s.engine_rpm:.0f} RPM).",
                )
            )
            self.was_running = True
        elif not is_running and self.was_running:
            events.append(
                EngineEvent(
                    event_type=EventType.ENGINE_STOP,
                    severity=EventSeverity.INFO,
                    start_time=s.timestamp,
                    end_time=s.timestamp,
                    duration_s=0.0,
                    signals_involved=["engine_rpm"],
                    calculated_metrics={"rpm": s.engine_rpm},
                    confidence=1.0,
                    evidence="Engine RPM dropped below running threshold.",
                )
            )
            self.was_running = False

        if not is_running:
            return events

        # 2. WOT Pull State Machine (TPS >= 85%, MAP >= 85 kPa)
        is_wot = s.tps >= 85.0 and s.map_kpa >= 85.0
        if is_wot:
            if self._active_wot is None:
                self._active_wot = {
                    "start_time": s.timestamp,
                    "start_rpm": s.engine_rpm,
                    "peak_rpm": s.engine_rpm,
                    "peak_map": s.map_kpa,
                    "learn_values": [s.fuel_learn],
                    "afr_values": [s.afr_measured],
                }
            else:
                self._active_wot["peak_rpm"] = max(self._active_wot["peak_rpm"], s.engine_rpm)
                self._active_wot["peak_map"] = max(self._active_wot["peak_map"], s.map_kpa)
                self._active_wot["learn_values"].append(s.fuel_learn)
                self._active_wot["afr_values"].append(s.afr_measured)
        else:
            if self._active_wot is not None:
                duration = s.timestamp - self._active_wot["start_time"]
                if duration >= 0.5:  # Minimum 500ms duration for valid pull
                    mean_learn = float(np.mean(self._active_wot["learn_values"]))
                    mean_afr = float(np.mean(self._active_wot["afr_values"]))
                    events.append(
                        EngineEvent(
                            event_type=EventType.WOT_PULL,
                            severity=EventSeverity.INFO if abs(mean_learn) < 7.0 else EventSeverity.WARNING,
                            start_time=self._active_wot["start_time"],
                            end_time=s.timestamp,
                            duration_s=round(duration, 2),
                            signals_involved=["tps", "map_kpa", "engine_rpm", "fuel_learn", "afr_measured"],
                            calculated_metrics={
                                "start_rpm": round(self._active_wot["start_rpm"], 0),
                                "peak_rpm": round(self._active_wot["peak_rpm"], 0),
                                "peak_map_kpa": round(self._active_wot["peak_map"], 1),
                                "mean_fuel_learn": round(mean_learn, 2),
                                "mean_afr": round(mean_afr, 2),
                            },
                            confidence=1.0,
                            evidence=(
                                f"Sustained WOT ({self._active_wot['peak_map']:.1f} kPa) for {duration:.1f}s, "
                                f"RPM {self._active_wot['start_rpm']:.0f} -> {self._active_wot['peak_rpm']:.0f}, "
                                f"mean fuel learn {mean_learn:+.1f}%."
                            ),
                        )
                    )
                self._active_wot = None

        # 3. Idle & Idle Hunting Detection
        is_idle_cond = s.tps <= 1.5 and s.engine_rpm < 1150.0 and (s.vehicle_speed is None or s.vehicle_speed < 2.5)
        if is_idle_cond:
            self._recent_rpms.append(s.engine_rpm)
            if len(self._recent_rpms) > 40:
                self._recent_rpms.pop(0)

            if self._active_idle is None:
                self._active_idle = {
                    "start_time": s.timestamp,
                    "clt": s.coolant_temp,
                }
            else:
                duration = s.timestamp - self._active_idle["start_time"]
                # If warm idle has lasted > 3 seconds, check for hunting
                if duration >= 3.0 and len(self._recent_rpms) >= 8 and s.coolant_temp >= 160.0:
                    rpm_range = max(self._recent_rpms) - min(self._recent_rpms)
                    if rpm_range >= 180.0 and not self._active_idle.get("hunting_emitted"):
                        events.append(
                            EngineEvent(
                                event_type=EventType.IDLE_HUNTING,
                                severity=EventSeverity.WARNING,
                                start_time=self._active_idle["start_time"],
                                end_time=s.timestamp,
                                duration_s=round(duration, 2),
                                signals_involved=["engine_rpm", "tps", "coolant_temp", "map_kpa"],
                                calculated_metrics={
                                    "min_rpm": min(self._recent_rpms),
                                    "max_rpm": max(self._recent_rpms),
                                    "rpm_amplitude": round(rpm_range, 0),
                                },
                                confidence=0.95,
                                evidence=f"Warm idle RPM oscillating with amplitude {rpm_range:.0f} RPM over {duration:.1f}s.",
                            )
                        )
                        self._active_idle["hunting_emitted"] = True
        else:
            self._active_idle = None
            self._recent_rpms.clear()

        # 4. Thermal Overheat Event (CLT >= 225 °F)
        if s.coolant_temp >= 225.0:
            if self._active_thermal is None:
                self._active_thermal = {
                    "start_time": s.timestamp,
                    "peak_clt": s.coolant_temp,
                }
            else:
                self._active_thermal["peak_clt"] = max(self._active_thermal["peak_clt"], s.coolant_temp)
        else:
            if self._active_thermal is not None:
                duration = s.timestamp - self._active_thermal["start_time"]
                events.append(
                    EngineEvent(
                        event_type=EventType.THERMAL_EVENT,
                        severity=EventSeverity.WARNING if self._active_thermal["peak_clt"] < 235.0 else EventSeverity.CRITICAL,
                        start_time=self._active_thermal["start_time"],
                        end_time=s.timestamp,
                        duration_s=round(duration, 2),
                        signals_involved=["coolant_temp"],
                        calculated_metrics={"peak_coolant_temp": round(self._active_thermal["peak_clt"], 1)},
                        confidence=1.0,
                        evidence=f"Coolant temperature exceeded 225°F threshold, peaking at {self._active_thermal['peak_clt']:.1f}°F for {duration:.1f}s.",
                    )
                )
                self._active_thermal = None

        # 5. Low Voltage Sag (< 12.2 V while running)
        if s.battery_voltage < 12.2:
            if self._active_voltage is None:
                self._active_voltage = {
                    "start_time": s.timestamp,
                    "min_voltage": s.battery_voltage,
                }
            else:
                self._active_voltage["min_voltage"] = min(self._active_voltage["min_voltage"], s.battery_voltage)
        else:
            if self._active_voltage is not None:
                duration = s.timestamp - self._active_voltage["start_time"]
                if duration >= 1.0:
                    events.append(
                        EngineEvent(
                            event_type=EventType.VOLTAGE_SAG,
                            severity=EventSeverity.WARNING if self._active_voltage["min_voltage"] >= 11.5 else EventSeverity.CRITICAL,
                            start_time=self._active_voltage["start_time"],
                            end_time=s.timestamp,
                            duration_s=round(duration, 2),
                            signals_involved=["battery_voltage"],
                            calculated_metrics={"min_voltage": round(self._active_voltage["min_voltage"], 2)},
                            confidence=1.0,
                            evidence=f"Battery voltage dropped below 12.2V (sagged to {self._active_voltage['min_voltage']:.2f}V) for {duration:.1f}s.",
                        )
                    )
                self._active_voltage = None

        return events

    def flush(self, timestamp: float) -> List[EngineEvent]:
        """Finalizes any open event upon session completion."""
        events: List[EngineEvent] = []
        if self._active_wot is not None:
            duration = timestamp - self._active_wot["start_time"]
            if duration >= 0.5:
                mean_learn = float(np.mean(self._active_wot["learn_values"]))
                events.append(
                    EngineEvent(
                        event_type=EventType.WOT_PULL,
                        severity=EventSeverity.INFO,
                        start_time=self._active_wot["start_time"],
                        end_time=timestamp,
                        duration_s=round(duration, 2),
                        signals_involved=["tps", "map_kpa", "engine_rpm", "fuel_learn"],
                        calculated_metrics={"peak_rpm": round(self._active_wot["peak_rpm"], 0), "mean_fuel_learn": round(mean_learn, 2)},
                        confidence=1.0,
                        evidence=f"WOT pull finished at session end ({duration:.1f}s duration).",
                    )
                )
            self._active_wot = None
        return events
